"""
RETICLE Gene Explorer — local web app
=====================================
Type a gene → see where its knockout sits across BioGRID screens, split by
assay domain (fitness / stress / reporter), with stats, visualizations, and an
LLM reading of its functional role.

  python3 web/app.py            # then open http://localhost:8000

Domain matters: essentiality only means something in FITNESS screens. STRESS
screens measure conditional (under-pressure) survival; REPORTER/marker screens
are excluded from the quantitative axes (each marker is its own axis) and kept
only for the per-gene functional read-out.

Zero third-party web deps (stdlib http.server). Reuses paths.py + llm_client.py.
The 2.1 GB DB and the gateway secret stay server-side.
"""

import json
import re
import sqlite3
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import numpy as np

HERE = Path(__file__).resolve().parent
SCRIPT_DIR = HERE.parent / "script"
sys.path.insert(0, str(SCRIPT_DIR))
import paths  # noqa: E402
import external_sources as ex  # noqa: E402  (NCBI / PubMed / GO / STRING + darkness)

PORT = 8000
DB = str(paths.DB)
INDEX_HTML = HERE / "index.html"
ORG2TAX = {"Homo sapiens": 9606, "Mus musculus": 10090}

# The "advanced / more expensive" model for the AI reading.
INTERPRET_MODEL = "gpt-5"


def _gen_kwargs(model):
    """gpt-5 / o-series are reasoning models: they reject `max_tokens` and a custom
    temperature, and need headroom for reasoning tokens (else the visible answer is
    empty). Everything else uses the classic params."""
    if model.startswith(("gpt-5", "o1", "o3", "o4")):
        return {"max_completion_tokens": 3000}
    return {"temperature": 0.3, "max_tokens": 600}

HIST_BINS = 26  # over [-1, 1]


# ---------------------------------------------------------------------------
# Database backend — local SQLite  OR  the team's AWS RDS (PostgreSQL).
# If AWS_DB_HOST is set in .env, queries hit Postgres (schema `reticle`);
# otherwise the local SQLite file. Same SQL works for both.
# ---------------------------------------------------------------------------

def _load_env():
    cfg, p = {}, HERE.parent / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    return cfg


_ENV = _load_env()
USE_PG = bool(_ENV.get("AWS_DB_HOST"))
_PG_PARAMS = (dict(host=_ENV.get("AWS_DB_HOST"), port=_ENV.get("AWS_DB_PORT", "5432"),
                   user=_ENV.get("AWS_DB_USER"), password=_ENV.get("AWS_DB_PASSWORD"),
                   dbname=_ENV.get("AWS_DB_NAME"), connect_timeout=15) if USE_PG else None)


class _Row(dict):
    """Case-insensitive row access (Postgres returns lowercase column names while
    the SQL mixes cases, like sqlite3.Row does natively)."""
    def __getitem__(self, k):
        try:
            return dict.__getitem__(self, k)
        except KeyError:
            return dict.__getitem__(self, k.lower())


def db_fetchall(sql, params=()):
    """Run a SELECT against the configured backend; rows allow case-insensitive
    dict access (`?` placeholders work for both — translated to %s for Postgres)."""
    if USE_PG:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        con = psycopg2.connect(**_PG_PARAMS)
        try:
            cur = con.cursor(cursor_factory=RealDictCursor)
            cur.execute("SET search_path TO reticle, public")
            cur.execute(sql.replace("?", "%s"), params)
            return [_Row(r) for r in cur.fetchall()]
        finally:
            con.close()
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    try:
        return con.execute(sql, params).fetchall()
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def resolve_symbol_variants(s: str):
    """Index-friendly set of casings (human TP53 / mouse Trp53 etc.)."""
    s = s.strip()
    return list(dict.fromkeys([s, s.upper(), s.lower(), s.capitalize()]))


def _pack(r):
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


def domain_block(rows, full=True):
    """Summary stats (+ optional hist/rug/top-lists) for one set of screen rows."""
    pct = np.array([r["pct"] for r in rows], dtype=float)
    n = len(pct)
    n_hits = int(sum(r["is_hit"] for r in rows))
    median = float(np.median(pct))
    lean = ("essential" if median < -0.15
            else "advantageous" if median > 0.15 else "mixed")
    block = {
        "n": n, "n_hits": n_hits,
        "hit_rate": round(n_hits / n, 4) if n else 0.0,
        "median": round(median, 4), "mean": round(float(np.mean(pct)), 4),
        "p25": round(float(np.percentile(pct, 25)), 4),
        "p75": round(float(np.percentile(pct, 75)), 4),
        "min": round(float(pct.min()), 4), "max": round(float(pct.max()), 4),
        "lean": lean,
    }
    if full:
        counts, edges = np.histogram(pct, bins=HIST_BINS, range=(-1.0, 1.0))
        ordered = sorted(rows, key=lambda r: r["pct"])
        block["hist"] = {"edges": [round(e, 4) for e in edges.tolist()],
                         "counts": counts.tolist()}
        block["rug"] = [round(float(x), 3) for x in pct.tolist()]
        block["most_essential"] = [_pack(r) for r in ordered[:10]]
        block["most_advantageous"] = [_pack(r) for r in reversed(ordered[-10:])]
        # per-screen rows (with the specific pressure) so the UI can re-slice by condition
        block["screens"] = [{"p": round(float(r["pct"]), 3),
                             "cc": (r["cc"] or "other"), "cn": (r["cn"] or ""),
                             "h": int(r["is_hit"])} for r in rows]
    return block


def stress_ledger(rows):
    """Per-condition fact ledger for stress screens (replaces the pooled axis).

    Direction is NOT pooled across conditions — it is resolved per specific
    condition_name from the already-calibrated HARMONIZED_SCORE sign, and we
    report how many independent screens of the *same* condition agree.  Only
    author-called hits (IS_HIT) become facts.  The cross-condition magnitude is
    never compared — the only number here is a count of concordant screens.
    """
    from collections import defaultdict
    groups = defaultdict(list)
    for r in rows:
        if not int(r["is_hit"]):
            continue
        cn = (r["cn"] or "unspecified condition").strip() or "unspecified condition"
        groups[(cn, r["cc"] or "other")].append(r)

    def _sign(r):
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
        papers = defaultdict(list)
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
                facts.append({"screen_id": r["SCREEN_ID"], "author": r["author"] or "—",
                              "pmid": r["pmid"] or "", "cell_line": r["CELL_LINE"] or "—",
                              "sign": _sign(r)})
        net = p_pos - p_neg
        ledger.append({
            "condition": cn, "class": cc,
            "direction": "resist" if net > 0 else "sensitise" if net < 0 else "mixed",
            "net": net, "n_papers": len(papers), "n_screens": len(rs),
            "n_agree": max(p_pos, p_neg),
            "facts": sorted(facts, key=lambda f: f["sign"]),
        })
    ledger.sort(key=lambda x: (-x["n_papers"], -x["n_screens"], -abs(x["net"]), x["condition"]))
    return ledger


_CTRL_RE = re.compile(
    r'^(ntc|non[-_ ]?targeting|control[_-]|control$|safe[-_ ]?harbor|neg(ative)?[-_ ]?control'
    r'|no[-_ ]?site|lacz|e?gfp|luciferase|luc$|sgnt|sgcontrol|scramble)', re.I)


def is_control(sym):
    """True for non-targeting / safe-harbor / reporter controls (not real genes)."""
    return bool(_CTRL_RE.match((sym or "").strip()))


def _norm_process(rationale, phenotype):
    """A reporter screen's rationale names the process it reads out
    (e.g. 'Negative regulators of NFkB signaling') — strip the screen's design
    framing down to the bare process, falling back to the GO-style phenotype."""
    s = (rationale or "").strip()
    s = re.sub(r'^(positive|negative)\s+regulators?\s+of\s+', '', s, flags=re.I)
    s = re.sub(r'^regulators?\s+of\s+', '', s, flags=re.I)
    s = re.sub(r'^genes?\s+(involved\s+in|for|regulating)\s+', '', s, flags=re.I)
    return (s or phenotype or "unspecified process").strip()


def reporter_ledger(rows):
    """Per-process fact ledger for reporter/marker screens.

    Reporter screens read a MARKER, not survival — so the fact is
    'gene REGULATES {process}', the process taken from the screen rationale.
    Direction (raises/lowers the marker) is gate-dependent and unreliable, so it
    is not surfaced; the gene<->process association is the payload.  Only author-
    called hits count, and non-targeting controls are dropped.
    """
    from collections import defaultdict
    groups = defaultdict(list)
    for r in rows:
        if not int(r["is_hit"]) or is_control(r["GENE_SYMBOL"]):
            continue
        groups[_norm_process(r["SCREEN_RATIONALE"], r["PHENOTYPE"])].append(r)

    ledger = []
    for proc, rs in groups.items():
        seen, facts = set(), []
        for r in rs:
            sid = r["SCREEN_ID"]
            if sid in seen:
                continue
            seen.add(sid)
            facts.append({"screen_id": sid, "author": r["author"] or "—",
                          "pmid": r["pmid"] or "", "cell_line": r["CELL_LINE"] or "—",
                          "phenotype": r["PHENOTYPE"] or ""})
        pids = {(f["pmid"].strip() if f["pmid"] else "") or f"screen:{f['screen_id']}"
                for f in facts}
        ledger.append({"process": proc, "n_papers": len(pids), "n_screens": len(facts),
                       "facts": facts, "screens": [f["screen_id"] for f in facts]})
    ledger.sort(key=lambda x: (-x["n_papers"], -x["n_screens"], x["process"].lower()))
    return ledger


def gene_payload(symbol: str):
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
              AND h.PERCENTILE_SCORE IS NOT NULL""",
        variants,
    )
    if not rows:
        return None

    # If the symbol exists in >1 organism, keep the better-represented one.
    by_org = {}
    for r in rows:
        by_org.setdefault(r["org"], []).append(r)
    org = max(by_org, key=lambda o: len(by_org[o]))
    rows = by_org[org]

    buckets = {"fitness": [], "stress": [], "reporter": [], "other": []}
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
            "n_hits": sum(1 for r in buckets["reporter"]
                          if int(r["is_hit"]) and not is_control(r["GENE_SYMBOL"])),
            "ledger": led,
        }
    else:
        reporter = {"n": 0, "n_hits": 0, "ledger": []}

    primary = "fitness" if fitness else ("stress" if stress else "reporter")
    return {
        "symbol": rows[0]["GENE_SYMBOL"], "query": symbol, "organism": org,
        "n_total": len(rows), "primary": primary,
        "fitness": fitness, "stress": stress, "reporter": reporter,
    }


def network_payload(symbol, taxid):
    """STRING subnetwork with each node colored by its RETICLE fitness behavior."""
    net = ex.string_network(symbol, taxid)
    nodes = net.get("nodes", [])
    if not nodes:
        return None
    ph = ",".join("?" * len(nodes))
    rows = db_fetchall(
        f"""SELECT h.GENE_SYMBOL g, AVG(h.PERCENTILE_SCORE) m
            FROM harmonized_scores h
            JOIN screen_metadata_curated c ON h.SCREEN_ID = c.screen_id
            WHERE h.GENE_SYMBOL IN ({ph}) AND c.assay_domain = 'fitness'
              AND h.PERCENTILE_SCORE IS NOT NULL
            GROUP BY h.GENE_SYMBOL""", nodes)
    med = {r["g"]: float(r["m"]) for r in rows if r["m"] is not None}

    def lean(m):
        if m is None:
            return None
        return "essential" if m < -0.15 else "advantageous" if m > 0.15 else "mixed"

    focus = next((n for n in nodes if n.upper() == symbol.upper()), symbol)
    out = [{"name": n, "median": round(med[n], 3) if n in med else None,
            "lean": lean(med.get(n)), "focus": (n == focus)} for n in nodes]
    return {"focus": focus, "nodes": out, "edges": net.get("edges", [])}


# ---------------------------------------------------------------------------
# LLM interpretation (domain-aware)
# ---------------------------------------------------------------------------

SYS_PROMPT = """You are a functional-genomics analyst. You are given a gene's behavior across pooled \
CRISPR screens (RETICLE's own harmonized data), its "darkness" rating, its known function and \
partners, and a few PubMed abstracts. Synthesize them into one grounded reading.

RETICLE axis: percentile -1 = knockout DELETERIOUS / gene essential; +1 = knockout ADVANTAGEOUS / \
loss promotes selection; 0 = no effect. Three assay domains:
- FITNESS  : baseline growth/viability — where ESSENTIALITY is read.
- STRESS   : survival under an applied pressure (drug/virus) — conditional; can diverge from fitness.
- REPORTER : marker (FACS) screens — specific functional probes (e.g. "regulators of mitophagy"),
             used to name the PROCESS the gene acts in, not essentiality.

Write 140-200 words, plain active prose, no headers/bullets:
(1) the FITNESS verdict grounded in the median/spread; (2) any STRESS divergence; (3) the functional
process suggested by REPORTER probes; (4) reconcile with KNOWN FUNCTION and the PubMed abstracts —
cite supporting papers as (PMID xx…).
DARK-MATTER PAYOFF: if the gene is poorly studied (high darkness) yet behaves like its known/known-
pathway partners in the screens, say so explicitly and frame it as a de-orphanization candidate with
a concrete, testable prediction. If the abstracts are sparse because the gene is dark, say that plainly
rather than inventing literature. Never fabricate a PMID — only cite ones provided."""


# ---------------------------------------------------------------------------
# Co-essentiality network — data-driven gene-gene graph from CRISPR profiles
# (complements STRING: works even for dark genes with no literature edges)
# ---------------------------------------------------------------------------
_COESS = {}


def _lean_label(v):
    return "essential" if v < -0.15 else "advantageous" if v > 0.15 else "mixed"


def _load_coess(taxid):
    if taxid in _COESS:
        return _COESS[taxid]
    p = paths.PROCESSED_DATA / f"coess_{taxid}.npz"
    if not p.exists():
        _COESS[taxid] = None
        return None
    z = np.load(p, allow_pickle=True)
    genes = [str(g) for g in z["genes"]]
    _COESS[taxid] = {"R": z["R"].astype(np.float32), "genes": genes,
                     "gidx": {g.lower(): i for i, g in enumerate(genes)},
                     "lean": z["lean"], "n_screens": int(z["R"].shape[1])}
    return _COESS[taxid]


def coessential_network(symbol, taxid, top=14, r_min=0.25):
    d = _load_coess(taxid)
    if d is None:
        return None
    qi = d["gidx"].get(symbol.strip().lower())
    if qi is None:
        return None
    R, genes, lean = d["R"], d["genes"], d["lean"]
    r = R @ R[qi]                    # rows are centred+normalised → cosine == Pearson
    r[qi] = -2.0
    cand = [int(j) for j in np.argsort(-r) if r[j] >= r_min][:top]
    members = [qi] + cand
    nodes = [{"name": genes[j], "lean": _lean_label(float(lean[j])),
              "focus": j == qi} for j in members]
    edges = [{"a": genes[qi], "b": genes[j], "r": round(float(r[j]), 3),
              "score": round(float(r[j]), 3)} for j in cand]
    # partner-partner edges so it reads as a graph, not a star
    for a in range(len(cand)):
        for b in range(a + 1, len(cand)):
            rv = float(R[cand[a]] @ R[cand[b]])
            if rv >= max(r_min, 0.3):
                edges.append({"a": genes[cand[a]], "b": genes[cand[b]],
                              "r": round(rv, 3), "score": round(rv, 3)})
    return {"symbol": genes[qi], "nodes": nodes, "edges": edges,
            "n_screens": d["n_screens"]}


# ---------------------------------------------------------------------------
# Screen-vs-screen similarity — Homo sapiens · fitness · genome-wide (FULL).
# Correlation is WEIGHTED by each screen's extremeness so the informative tail
# genes dominate and the ~random middle is down-weighted (see the math doc).
# Computed on demand for one query screen vs all others — no giant pair table.
# ---------------------------------------------------------------------------
_SCRMAT = None


def _load_screen_matrix():
    global _SCRMAT
    if _SCRMAT is not None:
        return _SCRMAT
    p = paths.PROCESSED_DATA / "screens_9606_fitness_full.npz"
    if not p.exists():
        _SCRMAT = False
        return False
    z = np.load(p, allow_pickle=True)
    screens = [str(s) for s in z["screens"]]
    _SCRMAT = {"M": z["M"].astype(np.float32), "genes": [str(g) for g in z["genes"]],
               "screens": screens, "sidx": {s: i for i, s in enumerate(screens)},
               "meta": z["meta"]}
    return _SCRMAT


def _screen_label(meta_row, sid):
    author, cell, pmid, ngenes = meta_row
    return {"author": str(author) or "—", "cell_line": str(cell) or "—",
            "pmid": str(pmid) or "", "n_genes": int(ngenes) if str(ngenes).isdigit() else None}


def screen_similar(screen_id, limit=50, offset=0, min_overlap=200):
    d = _load_screen_matrix()
    if not d:
        return None
    qi = d["sidx"].get(str(screen_id).strip())
    if qi is None:
        return None
    M, screens, meta = d["M"], d["screens"], d["meta"]
    q = M[:, qi]
    qmask = ~np.isnan(q)

    rows = []
    for j in range(M.shape[1]):
        if j == qi:
            continue
        b = M[:, j]
        m = qmask & ~np.isnan(b)
        n = int(m.sum())
        if n < min_overlap:
            continue
        a, c = q[m], b[m]
        # plain Pearson on percentile
        am, cm = a.mean(), c.mean()
        va = ((a - am) ** 2).mean(); vc = ((c - cm) ** 2).mean()
        plain = float(((a - am) * (c - cm)).mean() / np.sqrt(va * vc)) if va > 0 and vc > 0 else None
        # weighted Pearson — weight = |a|*|b| (both extreme -> high weight)
        w = np.abs(a) * np.abs(c)
        sw = w.sum()
        if sw > 0:
            aw = np.average(a, weights=w); cw = np.average(c, weights=w)
            cov = np.average((a - aw) * (c - cw), weights=w)
            vaw = np.average((a - aw) ** 2, weights=w); vcw = np.average((c - cw) ** 2, weights=w)
            weighted = float(cov / np.sqrt(vaw * vcw)) if vaw > 0 and vcw > 0 else None
        else:
            weighted = None
        if weighted is None:
            continue
        lab = _screen_label(meta[j], screens[j])
        rows.append({"screen_id": screens[j], "weighted": round(weighted, 3),
                     "plain": round(plain, 3) if plain is not None else None,
                     "overlap": n, **lab})
    rows.sort(key=lambda r: -r["weighted"])
    offset = max(0, int(offset)); limit = max(1, int(limit))
    return {"query": {"screen_id": screens[qi], **_screen_label(meta[qi], screens[qi])},
            "n_pool": M.shape[1], "n_total": len(rows), "offset": offset,
            "results": rows[offset:offset + limit]}


def _signal_lines(p):
    def blk(name, b):
        if not b:
            return f"{name}: (no screens)"
        return (f"{name}: n={b['n']}, hits={b['n_hits']}, median={b['median']:+.3f}, "
                f"IQR=[{b['p25']:+.3f},{b['p75']:+.3f}], lean={b['lean']}")
    def ctx(items):
        return "; ".join(f"{i['cell_line']} ({i['screen_type'] or 'screen'}, {i['percentile']:+.2f})"
                         for i in items[:5])
    out = [blk("FITNESS", p["fitness"])]
    # STRESS: per-condition facts, never a pooled median (magnitudes aren't comparable)
    st = p["stress"]
    if not st:
        out.append("STRESS: (no screens)")
    else:
        out.append(f"STRESS: n={st['n']}, author-called hits={st['n_hits']} "
                   f"— direction is per specific condition, NOT pooled")
        for r in (st.get("ledger") or [])[:6]:
            out.append(f"  {r['condition']} [{r['class']}] -> {r['direction']} "
                       f"({r['n_agree']}/{r['n_screens']} screens agree)")
    if p["fitness"]:
        out.append(f"  fitness most-essential: {ctx(p['fitness']['most_essential'])}")
        out.append(f"  fitness most-advantageous: {ctx(p['fitness']['most_advantageous'])}")
    rep = p["reporter"]
    if rep["n"]:
        procs = "; ".join(f"{r['process']} ({r['n_screens']} screen"
                          f"{'s' if r['n_screens'] > 1 else ''})"
                          for r in rep.get("ledger", [])[:8])
        out.append(f"REPORTER: n={rep['n']} marker screens — gene regulates: {procs or '(no called hits)'}")
    return out


def build_rag_prompt(p, ext, abstracts):
    sym, org = p["symbol"], p["organism"]
    ann = (ext or {}).get("annotation") or {}
    dk = (ext or {}).get("darkness") or {}
    partners = [x["partner"] for x in (ext or {}).get("string_partners", [])]
    lines = [f"GENE: {sym}  ({org})"]
    if dk:
        lines.append(f"DARKNESS: {dk['score']}/10 ({dk['band']}) — {dk['pubmed_count']} PubMed papers, "
                     f"{dk['go_total']} GO terms")
    lines.append("KNOWN FUNCTION: " + (ann.get("summary") or "(no curated summary — poorly characterized)"))
    if partners:
        lines.append("KNOWN PARTNERS (STRING): " + ", ".join(partners))
    lines.append("\nRETICLE SCREEN SIGNAL")
    lines += _signal_lines(p)
    lines.append("\nPUBMED ABSTRACTS (evidence — cite by PMID):")
    if abstracts:
        for a in abstracts:
            lines.append(f"[PMID {a['pmid']}] {a['title']}\n{a['abstract'][:600]}")
    else:
        lines.append("(none retrieved — consistent with a poorly studied gene)")
    return "\n".join(lines)


def interpret(p):
    from llm_client import WashULLMClient
    sym = p["symbol"]
    taxid = ORG2TAX.get(p.get("organism"), 9606)
    ext = ex.enrich(sym, taxid)                      # darkness + annotation + STRING (cached)
    abstracts = ex.pubmed_abstracts(ex.pubmed_pmids(sym, taxid, 5))   # RAG retrieval
    client = WashULLMClient(model=INTERPRET_MODEL)
    text = client.chat(
        [{"role": "system", "content": SYS_PROMPT},
         {"role": "user", "content": build_rag_prompt(p, ext, abstracts)}],
        **_gen_kwargs(client.model),
    )
    return {"model": client.model, "text": text.strip(),
            "sources": [{"pmid": a["pmid"], "title": a["title"]} for a in abstracts]}


# --- per-reporter-row AI synthesis (extract-only, grounded in the screen's paper) ---
_REXPLAIN_CACHE = {}

REXPLAIN_SYS = (
    "You write 1-2 substantive sentences on whether a gene's KNOWN function connects to a specific "
    "cellular process it scored in — for a functional-genomics UI. Ground every functional claim "
    "ONLY in the provided KNOWN FUNCTION summary, known partners, or cited abstracts — never in "
    "outside knowledge of the gene. Give the reader a real takeaway; never pad with boilerplate like "
    "'the abstract does not mention X'."
)


def _reporter_explain_prompt(symbol, process, screen_rows, abstracts, ann, dk, partners):
    summary = (ann or {}).get("summary") or ""
    L = [f"GENE: {symbol}", f"PROCESS (reporter read-out): {process}", "",
         "KNOWN FUNCTION (curated summary — your MAIN grounding): "
         + (summary or "(none on record — this gene is poorly characterized)")]
    if dk:
        L.append(f"DARKNESS: {dk.get('score', '?')}/10 ({dk.get('band', '?')}) — "
                 f"{dk.get('pubmed_count', '?')} PubMed papers")
    if partners:
        L.append("KNOWN PARTNERS (STRING): " + ", ".join(partners[:8]))
    L += ["", "ESTABLISHED SCREEN FACT (from the data — you MAY state it):"]
    for r in screen_rows:
        cite = f"PMID {r['pmid']}" if r["pmid"] else "unpublished"
        L.append(f"  • In {r['author'] or 'a'} ({cite}), knockout of {symbol} was an author-called "
                 f"hit in this '{process}' reporter screen.")
    if abstracts:
        L += ["", "SCREEN PAPER ABSTRACT(S) (extra source; cite by PMID):"]
        for a in abstracts:
            L.append(f"[PMID {a['pmid']}] {a['title']}\n{(a['abstract'] or '')[:900]}")
    L += ["",
          f"Write 1-2 substantive sentences on {symbol} and {process}:",
          f"- If the KNOWN FUNCTION / partners / abstracts clearly relate to {process}: explain HOW they "
          f"connect and note the screen hit is consistent with it (ground it, e.g. 'per its curated function').",
          f"- If {symbol} is poorly characterized (dark / no summary): frame this screen hit as the PRIMARY "
          f"evidence that it regulates {process} — a de-orphanization lead.",
          f"- If {symbol} is well-studied but its known roles do NOT involve {process}: say briefly this is "
          f"an association its established function does not explain (an uncharacterized link) — invent NO mechanism.",
          "RULES: base every functional claim ONLY on the material above, never on outside knowledge; cite "
          "abstracts as (PMID xxxxx). Mention only the aspect of the gene's function relevant to THIS "
          "process (or that none is) — do NOT recite its whole function list. No boilerplate, no hedging "
          "padding — give the actual takeaway."]
    return "\n".join(L)


def reporter_explain(symbol, screen_ids):
    """Grounded 2-3 sentence synthesis of a gene's role in a reporter's process,
    read ONLY from that screen's PubMed abstract(s). Extraction, not generation."""
    from llm_client import WashULLMClient
    key = (symbol.lower(), tuple(sorted(screen_ids)))
    if key in _REXPLAIN_CACHE:
        return _REXPLAIN_CACHE[key]
    ph = ",".join("?" * len(screen_ids))
    rows = db_fetchall(
        f"""SELECT c.screen_id, c.pmid, m.AUTHOR AS author,
                   m.SCREEN_RATIONALE AS rat, m.PHENOTYPE AS phen,
                   m.ORGANISM_OFFICIAL AS org
            FROM screen_metadata_curated c JOIN screen_metadata m ON m.SCREEN_ID = c.screen_id
            WHERE c.screen_id IN ({ph})""", list(screen_ids))
    if not rows:
        return {"text": "", "sources": [], "process": ""}
    process = _norm_process(rows[0]["rat"], rows[0]["phen"])
    taxid = ORG2TAX.get(rows[0]["org"], 9606)
    try:
        ext = ex.enrich(symbol, taxid)        # curated summary + darkness + partners (cached)
    except Exception:
        ext = {}
    ann = (ext or {}).get("annotation") or {}
    dk = (ext or {}).get("darkness") or {}
    partners = [x["partner"] for x in (ext or {}).get("string_partners", [])]
    pmids = [d for d in (re.sub(r"\D", "", str(r["pmid"] or "")) for r in rows) if d]
    abstracts = ex.pubmed_abstracts(pmids) if pmids else []
    client = WashULLMClient(model=INTERPRET_MODEL)
    text = client.chat(
        [{"role": "system", "content": REXPLAIN_SYS},
         {"role": "user", "content": _reporter_explain_prompt(symbol, process, rows, abstracts, ann, dk, partners)}],
        **_gen_kwargs(client.model))
    out = {"text": text.strip(), "process": process, "darkness": dk.get("score"),
           "sources": [{"pmid": a["pmid"], "title": a["title"]} for a in abstracts]}
    _REXPLAIN_CACHE[key] = out
    return out


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            return self._send(200, INDEX_HTML.read_bytes(), "text/html; charset=utf-8")
        if u.path == "/api/gene":
            sym = (parse_qs(u.query).get("symbol", [""])[0]).strip()
            if not sym:
                return self._send(400, {"error": "Enter a gene symbol."})
            try:
                p = gene_payload(sym)
            except Exception as e:
                return self._send(500, {"error": f"Lookup failed: {e}"})
            if p is None:
                return self._send(404, {"error": f"No screens found for “{sym}”."})
            return self._send(200, p)
        if u.path == "/api/context":
            q = parse_qs(u.query)
            sym = (q.get("symbol", [""])[0]).strip()
            taxid = ORG2TAX.get(q.get("org", ["Homo sapiens"])[0], 9606)
            if not sym:
                return self._send(400, {"error": "Missing symbol."})
            try:
                return self._send(200, ex.enrich(sym, taxid))
            except Exception as e:
                return self._send(502, {"error": f"External lookup failed: {e}"})
        if u.path == "/api/network":
            q = parse_qs(u.query)
            sym = (q.get("symbol", [""])[0]).strip()
            taxid = ORG2TAX.get(q.get("org", ["Homo sapiens"])[0], 9606)
            if not sym:
                return self._send(400, {"error": "Missing symbol."})
            try:
                p = network_payload(sym, taxid)
            except Exception as e:
                return self._send(502, {"error": f"Network lookup failed: {e}"})
            if p is None:
                return self._send(404, {"error": "No STRING network."})
            return self._send(200, p)
        if u.path == "/api/coessential":
            q = parse_qs(u.query)
            sym = (q.get("symbol", [""])[0]).strip()
            taxid = ORG2TAX.get(q.get("org", ["Homo sapiens"])[0], 9606)
            if not sym:
                return self._send(400, {"error": "Missing symbol."})
            try:
                p = coessential_network(sym, taxid)
            except Exception as e:
                return self._send(500, {"error": f"Co-essentiality failed: {e}"})
            if p is None:
                return self._send(404, {"error": "No co-essentiality profile."})
            return self._send(200, p)
        if u.path == "/api/screen_similar":
            q = parse_qs(u.query)
            sid = (q.get("screen", [""])[0]).strip()
            if not sid:
                return self._send(400, {"error": "Missing screen id."})
            try:
                limit = min(200, max(1, int(q.get("limit", ["50"])[0])))
                offset = max(0, int(q.get("offset", ["0"])[0]))
                p = screen_similar(sid, limit=limit, offset=offset)
            except Exception as e:
                return self._send(500, {"error": f"Screen similarity failed: {e}"})
            if p is None:
                return self._send(404, {"error": f"Screen {sid} not in the human · fitness · genome-wide pool."})
            return self._send(200, p)
        if u.path == "/api/reporter_explain":
            q = parse_qs(u.query)
            sym = (q.get("symbol", [""])[0]).strip()
            screens = [s.strip() for s in (q.get("screens", [""])[0]).split(",") if s.strip()]
            if not sym or not screens:
                return self._send(400, {"error": "Missing symbol/screens."})
            try:
                return self._send(200, reporter_explain(sym, screens[:6]))
            except Exception as e:
                msg = str(e)
                hint = ("  Connect the WashU network (gateway is WashU-only) and retry."
                        if "403" in msg or "Forbidden" in msg else "")
                return self._send(502, {"error": f"Explanation unavailable: {msg}{hint}"})
        self._send(404, {"error": "Not found"})

    def do_POST(self):
        u = urlparse(self.path)
        if u.path == "/api/interpret":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length) or b"{}")
                return self._send(200, interpret(payload))
            except Exception as e:
                msg = str(e)
                hint = ("  Connect the WashU VPN (gateway is WashU-only) and retry."
                        if "403" in msg or "Forbidden" in msg else "")
                return self._send(502, {"error": f"Interpretation unavailable: {msg}{hint}"})
        self._send(404, {"error": "Not found"})


def main():
    print(f"RETICLE Gene Explorer  →  http://localhost:{PORT}")
    print(f"  DB: {DB}")
    print(f"  interpretation model: {INTERPRET_MODEL}\n")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
