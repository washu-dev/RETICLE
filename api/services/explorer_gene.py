"""Gene-explorer payload service (ported from prototype/web/app.py).

Builds the per-gene payload the Explorer page renders: knockout behavior across
BioGRID screens, split by assay domain (fitness / stress / reporter) with summary
stats, a histogram, and per-condition / per-process fact ledgers.

This is a faithful port of the prototype's `gene_payload()` — the JSON shape is
preserved byte-for-byte so the ported Explorer frontend consumes it unchanged.
The only change from the prototype is the data source: queries go through
`services.db_service.db_fetchall` (same AWS RDS `reticle` schema) instead of the
prototype's private copy of that helper.
"""

import re
from collections import defaultdict

import numpy as np

from services.db_service import db_fetchall

HIST_BINS = 26  # over [-1, 1]


def resolve_symbol_variants(s: str) -> list[str]:
    """Index-friendly set of casings (human TP53 / mouse Trp53 etc.)."""
    s = s.strip()
    return list(dict.fromkeys([s, s.upper(), s.lower(), s.capitalize()]))


def _pack(r: dict) -> dict:
    return {
        "screen_id": r["SCREEN_ID"],
        "cell_line": r["CELL_LINE"] or "—",
        "screen_type": r["SCREEN_TYPE"] or "",
        "analysis": r["ANALYSIS"] or "",
        "phenotype": r["PHENOTYPE"] or "",
        "rationale": (r["SCREEN_RATIONALE"] or "")[:120],
        "percentile": round(r["pct"], 4),
        "is_hit": int(r["is_hit"]),
    }


def domain_block(rows: list, full: bool = True) -> dict:
    """Summary stats (+ optional hist/rug/top-lists) for one set of screen rows."""
    pct = np.array([r["pct"] for r in rows], dtype=float)
    n = len(pct)
    n_hits = int(sum(r["is_hit"] for r in rows))
    median = float(np.median(pct))
    lean = (
        "essential" if median < -0.15 else "advantageous" if median > 0.15 else "mixed"
    )
    block = {
        "n": n,
        "n_hits": n_hits,
        "hit_rate": round(n_hits / n, 4) if n else 0.0,
        "median": round(median, 4),
        "mean": round(float(np.mean(pct)), 4),
        "p25": round(float(np.percentile(pct, 25)), 4),
        "p75": round(float(np.percentile(pct, 75)), 4),
        "min": round(float(pct.min()), 4),
        "max": round(float(pct.max()), 4),
        "lean": lean,
    }
    if full:
        counts, edges = np.histogram(pct, bins=HIST_BINS, range=(-1.0, 1.0))
        ordered = sorted(rows, key=lambda r: r["pct"])
        block["hist"] = {
            "edges": [round(e, 4) for e in edges.tolist()],
            "counts": counts.tolist(),
        }
        block["rug"] = [round(float(x), 3) for x in pct.tolist()]
        block["most_essential"] = [_pack(r) for r in ordered[:10]]
        block["most_advantageous"] = [_pack(r) for r in reversed(ordered[-10:])]
        # per-screen rows (with the specific pressure) so the UI can re-slice by condition
        block["screens"] = [
            {
                "p": round(float(r["pct"]), 3),
                "cc": (r["cc"] or "other"),
                "cn": (r["cn"] or ""),
                "h": int(r["is_hit"]),
            }
            for r in rows
        ]
    return block


def stress_ledger(rows: list) -> list:
    """Per-condition fact ledger for stress screens (replaces the pooled axis).

    Direction is NOT pooled across conditions — it is resolved per specific
    condition_name from the already-calibrated HARMONIZED_SCORE sign, and we
    report how many independent screens of the *same* condition agree. Only
    author-called hits (IS_HIT) become facts. The cross-condition magnitude is
    never compared — the only number here is a count of concordant screens.
    """
    groups: dict = defaultdict(list)
    for r in rows:
        if not int(r["is_hit"]):
            continue
        cn = (r["cn"] or "unspecified condition").strip() or "unspecified condition"
        groups[(cn, r["cc"] or "other")].append(r)

    def _sign(r: dict) -> str:
        v = r["harm"]
        if v is None or v == 0:
            v = r["z"] or 0
        return "pos" if v >= 0 else "neg"

    ledger = []
    for (cn, cc), rs in groups.items():
        # reproducibility is counted by PAPER (distinct PMID), not by screen —
        # several 'screens' are replicates/time-points of one study, so counting
        # screens overstates independent confirmation. Direction is decided per
        # paper (its screens' majority), then tallied across papers.
        papers: dict = defaultdict(list)
        for r in rs:
            pid = (str(r["pmid"]).strip() if r["pmid"] else "") or f"screen:{r['SCREEN_ID']}"
            papers[pid].append(r)
        p_pos = p_neg = 0
        facts = []
        for prs in papers.values():
            npos = sum(1 for r in prs if _sign(r) == "pos")
            pdir = "pos" if npos >= len(prs) - npos else "neg"
            p_pos += pdir == "pos"
            p_neg += pdir == "neg"
            for r in prs:
                facts.append(
                    {
                        "screen_id": r["SCREEN_ID"],
                        "author": r["author"] or "—",
                        "pmid": r["pmid"] or "",
                        "cell_line": r["CELL_LINE"] or "—",
                        "sign": _sign(r),
                    }
                )
        net = p_pos - p_neg
        ledger.append(
            {
                "condition": cn,
                "class": cc,
                "direction": "resist" if net > 0 else "sensitise" if net < 0 else "mixed",
                "net": net,
                "n_papers": len(papers),
                "n_screens": len(rs),
                "n_agree": max(p_pos, p_neg),
                "facts": sorted(facts, key=lambda f: f["sign"]),
            }
        )
    ledger.sort(key=lambda x: (-x["n_papers"], -x["n_screens"], -abs(x["net"]), x["condition"]))
    return ledger


_CTRL_RE = re.compile(
    r"^(ntc|non[-_ ]?targeting|control[_-]|control$|safe[-_ ]?harbor|neg(ative)?[-_ ]?control"
    r"|no[-_ ]?site|lacz|e?gfp|luciferase|luc$|sgnt|sgcontrol|scramble)",
    re.I,
)


def is_control(sym: str) -> bool:
    """True for non-targeting / safe-harbor / reporter controls (not real genes)."""
    return bool(_CTRL_RE.match((sym or "").strip()))


def _norm_process(rationale: str, phenotype: str) -> str:
    """A reporter screen's rationale names the process it reads out
    (e.g. 'Negative regulators of NFkB signaling') — strip the screen's design
    framing down to the bare process, falling back to the GO-style phenotype."""
    s = (rationale or "").strip()
    s = re.sub(r"^(positive|negative)\s+regulators?\s+of\s+", "", s, flags=re.I)
    s = re.sub(r"^regulators?\s+of\s+", "", s, flags=re.I)
    s = re.sub(r"^genes?\s+(involved\s+in|for|regulating)\s+", "", s, flags=re.I)
    return (s or phenotype or "unspecified process").strip()


def reporter_ledger(rows: list) -> list:
    """Per-process fact ledger for reporter/marker screens.

    Reporter screens read a MARKER, not survival — so the fact is
    'gene REGULATES {process}', the process taken from the screen rationale.
    Direction (raises/lowers the marker) is gate-dependent and unreliable, so it
    is not surfaced; the gene<->process association is the payload. Only author-
    called hits count, and non-targeting controls are dropped.
    """
    groups: dict = defaultdict(list)
    for r in rows:
        if not int(r["is_hit"]) or is_control(r["GENE_SYMBOL"]):
            continue
        groups[_norm_process(r["SCREEN_RATIONALE"], r["PHENOTYPE"])].append(r)

    ledger = []
    for proc, rs in groups.items():
        seen: set = set()
        facts = []
        for r in rs:
            sid = r["SCREEN_ID"]
            if sid in seen:
                continue
            seen.add(sid)
            facts.append(
                {
                    "screen_id": sid,
                    "author": r["author"] or "—",
                    "pmid": r["pmid"] or "",
                    "cell_line": r["CELL_LINE"] or "—",
                    "phenotype": r["PHENOTYPE"] or "",
                }
            )
        pids = {
            (f["pmid"].strip() if f["pmid"] else "") or f"screen:{f['screen_id']}"
            for f in facts
        }
        ledger.append(
            {
                "process": proc,
                "n_papers": len(pids),
                "n_screens": len(facts),
                "facts": facts,
                "screens": [f["screen_id"] for f in facts],
            }
        )
    ledger.sort(key=lambda x: (-x["n_papers"], -x["n_screens"], x["process"].lower()))
    return ledger


async def get_gene_payload(symbol: str) -> dict | None:
    """Build the full Explorer payload for one gene symbol, or None if unknown."""
    variants = resolve_symbol_variants(symbol)
    ph = ",".join("?" * len(variants))
    rows = db_fetchall(
        f"""SELECT h.SCREEN_ID, h.GENE_SYMBOL, h.PERCENTILE_SCORE AS pct,
                   h.IS_HIT AS is_hit, h.HARMONIZED_SCORE AS harm,
                   h.ROBUST_Z_SCORE AS z,
                   m.CELL_LINE, m.SCREEN_TYPE, m.ANALYSIS, m.PHENOTYPE,
                   m.SCREEN_RATIONALE, m.ORGANISM_OFFICIAL AS org, m.AUTHOR AS author,
                   COALESCE(c.assay_domain, 'other') AS domain,
                   c.condition_class AS cc, c.condition_name AS cn, c.pmid AS pmid
            FROM harmonized_scores h
            JOIN screen_metadata m ON h.SCREEN_ID = m.SCREEN_ID
            LEFT JOIN screen_metadata_curated c ON h.SCREEN_ID = c.screen_id
            WHERE h.GENE_SYMBOL IN ({ph})
              AND h.PERCENTILE_SCORE IS NOT NULL
            ORDER BY h.SCREEN_ID, h.GENE_SYMBOL, h.PERCENTILE_SCORE,
                     c.condition_name""",
        tuple(variants),
    )
    if not rows:
        return None

    # If the symbol exists in >1 organism, keep the better-represented one.
    by_org: dict = {}
    for r in rows:
        by_org.setdefault(r["org"], []).append(r)
    org = max(by_org, key=lambda o: len(by_org[o]))
    rows = by_org[org]

    buckets: dict = {"fitness": [], "stress": [], "reporter": [], "other": []}
    for r in rows:
        buckets.get(r["domain"], buckets["other"]).append(r)
    # fold "other" into reporter for display (both are excluded from the axes)
    buckets["reporter"] += buckets.pop("other")

    fitness = domain_block(buckets["fitness"]) if buckets["fitness"] else None
    # stress: no pooled axis — a per-condition fact ledger instead (keep n / n_hits)
    stress = None
    if buckets["stress"]:
        stress = domain_block(buckets["stress"], full=False)
        stress["ledger"] = stress_ledger(buckets["stress"])

    # reporter: no axis — a per-process regulator ledger (gene -> regulates X)
    if buckets["reporter"]:
        led = reporter_ledger(buckets["reporter"])
        reporter = {
            "n": len(buckets["reporter"]),
            "n_hits": sum(
                1
                for r in buckets["reporter"]
                if int(r["is_hit"]) and not is_control(r["GENE_SYMBOL"])
            ),
            "ledger": led,
        }
    else:
        reporter = {"n": 0, "n_hits": 0, "ledger": []}

    primary = "fitness" if fitness else ("stress" if stress else "reporter")
    return {
        "symbol": rows[0]["GENE_SYMBOL"],
        "query": symbol,
        "organism": org,
        "n_total": len(rows),
        "primary": primary,
        "fitness": fitness,
        "stress": stress,
        "reporter": reporter,
    }
