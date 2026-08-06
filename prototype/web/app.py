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
import os
import re
import sqlite3
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import numpy as np

HERE = Path(__file__).resolve().parent
SCRIPT_DIR = HERE.parent / "script"
sys.path.insert(0, str(SCRIPT_DIR))
import paths  # noqa: E402
import external_sources as ex  # noqa: E402  (NCBI / PubMed / GO / STRING + darkness)

PORT = int(os.environ.get("RETICLE_PORT", "8000"))  # override to run a second copy side by side
DB = str(paths.DB)
KB_DB = str(paths.PROCESSED_DATA / "kb.db")      # the gene-wiki knowledge base (6 sources)
NET_DB = str(paths.PROCESSED_DATA / "reticle_net.db")  # human co-essentiality network
NET_DB_MOUSE = str(paths.PROCESSED_DATA / "reticle_net_mouse.db")  # mouse network (separate db — 1,656 symbols collide with human)


def _net_db(organism):
    return NET_DB_MOUSE if organism == "mouse" else NET_DB
INDEX_HTML = HERE / "index.html"
GENE_HTML = HERE / "gene.html"          # unified Gene tab (gene-level query + wiki)
SCREEN_HTML = HERE / "screen.html"      # Screen tab (screen-wide similarity query)
NETWORK_HTML = HERE / "network.html"
ORG2TAX = {"Homo sapiens": 9606, "Mus musculus": 10090}

# Model for the grounded text syntheses (screen analysis, reporter explanation, the AI reading).
# The WashU gateway moved to Anthropic Messages in July 2026; gpt-4.1 and gpt-5 no longer exist
# there (404), and of the Claude models this API key can reach — opus-4-7 and haiku-4-5 — opus is
# the one chosen here. haiku is ~7x cheaper per token if the shared budget ever gets tight.
INTERPRET_MODEL = "claude-opus-4-7"

# The Network tab's function prediction reasons over a partner dossier rather than summarising, so
# it gets the strongest available model. Same name as INTERPRET_MODEL today; kept separate because
# the two have different quality/cost tradeoffs and are tuned independently.
NET_PREDICT_MODEL = "claude-opus-4-7"

# Bump whenever NET_PREDICT_SYS or _net_predict_prompt changes in a way that could change the
# answer. It is part of the prediction cache key, so a stale entry cannot outlive its prompt.
NET_PREDICT_PROMPT_VERSION = "netpred-v1"


def _gen_kwargs(model, max_tokens=600):
    """The Messages API REQUIRES max_tokens — omitting it is a 400, not a default.

    600 covers the ~200-word syntheses; net_predict passes more because its JSON payload of
    predictions plus rationales is longer, and a reply truncated at the limit comes back as
    unparseable JSON rather than as an error.

    No `temperature`: claude-opus-4-7 rejects it outright ("`temperature` is deprecated for this
    model", HTTP 400). The old gpt-5 branch here existed for the same class of reason.
    """
    return {"max_tokens": max_tokens}

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
# RETICLE_LOCAL=1 forces the SQLite mirrors even when .env carries RDS credentials.
# The shared RDS instance is 1 GiB serving ~53 GB and periodically stops answering for tens of
# minutes at a time; every table this app reads also exists as a local file under processed_data/.
# So a demo, or any work that must not depend on that instance being awake, runs with this set —
# without editing .env, which holds secrets and is the same file the cloud deploy reads from.
USE_PG = bool(_ENV.get("AWS_DB_HOST")) and os.environ.get("RETICLE_LOCAL", "") not in ("1", "true", "yes")
_PG_PARAMS = (dict(host=_ENV.get("AWS_DB_HOST"), port=_ENV.get("AWS_DB_PORT", "5432"),
                   user=_ENV.get("AWS_DB_USER"), password=_ENV.get("AWS_DB_PASSWORD"),
                   dbname=_ENV.get("AWS_DB_NAME"), connect_timeout=15,
                   # set search_path at connect time (via libpq options) so pooled connections
                   # need no per-checkout `SET` round-trip.
                   options="-c search_path=reticle,public") if USE_PG else None)


class _Row(dict):
    """Case-insensitive row access (Postgres returns lowercase column names while
    the SQL mixes cases, like sqlite3.Row does natively)."""
    def __getitem__(self, k):
        try:
            return dict.__getitem__(self, k)
        except KeyError:
            return dict.__getitem__(self, k.lower())


_pg_pool = None
_pg_pool_lock = threading.Lock()


def _pg_get_pool():
    """A process-wide connection pool shared across request threads.

    The server is a ThreadingHTTPServer, which spawns a FRESH thread per request and discards it
    — so a thread-local connection is never reused across requests and every request paid the full
    ~1.6s RDS connect (worse under I/O load). A shared ThreadedConnectionPool fixes that: 2 warm
    connections are opened up front and checked out/in per query, so the connect cost is paid once
    at startup, not once per request. minconn keeps the demo warm; maxconn caps fan-out so a burst
    can't exhaust RDS. search_path is baked into the connection via libpq `options`, so no per-query
    SET is needed. Pool getconn/putconn are internally locked and safe to call from many threads."""
    global _pg_pool
    if _pg_pool is None:
        with _pg_pool_lock:
            if _pg_pool is None:
                from psycopg2.pool import ThreadedConnectionPool
                # minconn=4 warm connections cover a realistic demo's concurrency (1-3 users) without
                # opening a fresh one mid-request; maxconn=12 caps fan-out so a burst can't overrun RDS.
                _pg_pool = ThreadedConnectionPool(4, 12, **_PG_PARAMS)
    return _pg_pool


def db_fetchall(sql, params=()):
    """Run a SELECT against the configured backend; rows allow case-insensitive
    dict access (`?` placeholders work for both — translated to %s for Postgres)."""
    if USE_PG:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        pool = _pg_get_pool()
        for attempt in (0, 1):                      # a pooled conn can go stale — discard & retry once
            con = pool.getconn()
            try:
                con.autocommit = True               # SELECT-only; never leave an idle transaction
                cur = con.cursor(cursor_factory=RealDictCursor)
                cur.execute(sql.replace("?", "%s"), params)
                rows = [_Row(r) for r in cur.fetchall()]
                cur.close()
                pool.putconn(con)                   # return healthy connection to the pool
                return rows
            except psycopg2.Error:
                try:
                    pool.putconn(con, close=True)   # drop the broken one; pool opens a fresh one next
                except Exception:
                    pass
                if attempt:
                    raise
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    try:
        return con.execute(sql, params).fetchall()
    finally:
        con.close()


def _db_fetchall_unpooled(sql, params=()):
    """(kept for reference — the original connect-per-query path)"""
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
    mean_pct = {r["g"]: float(r["m"]) for r in rows if r["m"] is not None}

    def lean(m):
        if m is None:
            return None
        return "essential" if m < -0.15 else "advantageous" if m > 0.15 else "mixed"

    focus = next((n for n in nodes if n.upper() == symbol.upper()), symbol)
    # field is `mean_percentile`, not `median` — the SQL above is AVG(). The old name said median.
    out = [{"name": n, "mean_percentile": round(mean_pct[n], 3) if n in mean_pct else None,
            "lean": lean(mean_pct.get(n)), "focus": (n == focus)} for n in nodes]
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
#
# The coess_<taxid>.npz cache that used to live here is gone: coessential_network() reads net_edge
# now, so nothing loads the dense matrix any more. The .npz files are still on disk and are still
# what compute_coessential.py writes — they are simply no longer in a request path.
# ---------------------------------------------------------------------------


def _lean_label(v):
    return "essential" if v < -0.15 else "advantageous" if v > 0.15 else "mixed"


def coessential_network(symbol, taxid, top=14):
    """The gene wiki's inline co-essentiality graph.

    NOW READS net_edge — the same source the Network page serves — where it used to load a dense
    coess_<taxid>.npz and compute `R @ R[query]` per request. That made the wiki show a materially
    WORSE network than the Network tab while both were labelled "co-essentiality", which is the
    kind of quiet disagreement that costs a tool its credibility:

      coess_<taxid>.npz (old)          net_edge (now)
      ------------------------------   --------------------------------------------------------
      dense cosine == Pearson          same Pearson, but with PC1 — the pan-essentiality axis,
                                       ~44.5% of variance — projected out first, which took CORUM
                                       same-complex precision from 42.8% to 59.1%
      fixed r >= 0.25 cutoff           per-context threshold calibrated against a within-screen
                                       shuffle null at FDR <= 0.05
      no support / reciprocity         carries co-measured support and a mutual-best flag
      no node gates                    nodes gated on hit count, coverage and hit rate, which
                                       suppresses the multi-mapping-sgRNA artifact cliques
      no evidence tiers                every edge graded on both channels

    The cloud made this same switch earlier (services/coessential_network_aaron.py); the prototype
    was the one still on the old file, so the two disagreed.

    PAYLOAD: the original shape is preserved — nodes[].name/lean/focus, edges[].a/b/r/score — so
    nothing downstream breaks. Two fields are ADDED: `tier` on every edge, and `direct`, true when
    the edge touches the focal gene. Partner-partner edges are still returned even though the wiki
    draws only the direct ones: they are what let the force simulation pull a complex together, so
    dropping them server-side would flatten the picture into a bare radial star.
    """
    organism = "mouse" if taxid == 10090 else "human"
    tbl = _net_edge_table(organism)
    context = "mouse" if organism == "mouse" else "all"

    g = symbol.strip()
    seed = None
    for v in dict.fromkeys([g, g.upper(), g.capitalize()]):
        if net_fetchall(f"SELECT 1 FROM {tbl} WHERE context=? AND (gene_a=? OR gene_b=?) LIMIT 1",
                        (context, v, v), organism=organism):
            seed = v
            break
    if seed is None:
        return None

    # Mutual-best first, widen only if the gene has none — the reciprocal view is markedly cleaner
    # (46.4% vs 4.9% CORUM precision between the top and bottom evidence tiers).
    def _partners(recip):
        rec = "AND reciprocal=1 " if recip else ""
        return net_fetchall(
            f"SELECT CASE WHEN gene_a=? THEN gene_b ELSE gene_a END nb, strength "
            f"FROM {tbl} WHERE context=? AND channel='coessential' AND (gene_a=? OR gene_b=?) {rec}"
            f"ORDER BY strength DESC LIMIT ?", (seed, context, seed, seed, top), organism=organism)

    rows = _partners(True)
    if not rows:
        rows = _partners(False)
    if not rows:
        return None

    members = [seed] + [r["nb"] for r in rows]
    mset = set(members)
    ph = ",".join("?" * len(members))
    erows = net_fetchall(
        f"SELECT gene_a, gene_b, strength, reciprocal FROM {tbl} "
        f"WHERE context=? AND channel='coessential' AND gene_a IN ({ph}) AND gene_b IN ({ph})",
        [context] + members + members, organism=organism)

    ch = _cohit_among(members, organism=organism)
    lean = _net_fitness_lean(members, organism=organism)
    nodes = [{"name": n, "lean": _lean_label(lean[n]) if n in lean else None, "focus": n == seed}
             for n in members]

    from collections import Counter
    edges, hist = [], Counter()
    for e in erows:
        a, b = e["gene_a"], e["gene_b"]
        if a not in mset or b not in mset or a == b:
            continue
        tier = _edge_tier(bool(e["reciprocal"]), ((a, b) if a <= b else (b, a)) in ch)
        direct = seed in (a, b)
        r = round(float(e["strength"]), 3)
        edges.append({"a": a, "b": b, "r": r, "score": r, "tier": tier, "direct": direct})
        if direct:
            hist[tier] += 1

    n_screens = None
    if organism != "mouse":
        try:
            n_screens = net_fetchall(
                "SELECT COUNT(*) c FROM net_screen WHERE coverage_type='FULL' AND n_genes >= 15000",
                organism=organism)[0]["c"]
        except Exception:
            pass
    return {"symbol": seed, "nodes": nodes, "edges": edges, "n_screens": n_screens,
            "context_label": NET_CTX_LABELS.get(context, context),
            "tiers": {str(t): hist.get(t, 0) for t in (1, 2, 3, 4)},
            "cohit_available": organism not in _COHIT_UNAVAILABLE}


# ---------------------------------------------------------------------------
# CONTEXT-RESOLVED co-essentiality network (reticle_net.db, built by
# script/compute_coessential.py). Pure BioGRID CRISPR, no STRING/literature.
# Nodes = hit-active genes; edges = within-context co-essentiality; each edge is
# tagged with its context and a `reciprocal` (mutual-best) flag. This is the
# flagship gene-gene network — the same pair can relate differently per context.
# ---------------------------------------------------------------------------
NET_CTX_LABELS = {
    "all": "All screens · pooled",
    "mouse": "All mouse screens · pooled",
    "domain:fitness": "Fitness · generic proliferation",
    "DDR·genotoxic": "DNA damage · genotoxic",
}


def _net_edge_table(organism):
    """Table name for the co-essentiality edges. Local sqlite keeps human/mouse in SEPARATE
    db files (same table name); RDS keeps both in one reticle schema, so mouse is suffixed."""
    return "net_edge_mouse" if (USE_PG and organism == "mouse") else "net_edge"


def net_fetchall(sql, params=(), organism="human"):
    # cloud (USE_PG): read the network from RDS reticle schema — same connection/search_path as
    # db_fetchall; the caller has already put the right table name (net_edge / net_edge_mouse)
    # into the SQL. local: read the organism-specific sqlite mirror. => not local-dependent.
    if USE_PG:
        return db_fetchall(sql, params)
    con = sqlite3.connect(_net_db(organism))
    con.row_factory = sqlite3.Row
    try:
        return con.execute(sql, params).fetchall()
    finally:
        con.close()


def net_contexts(organism="human"):
    """Available network contexts, edge counts, node counts."""
    tbl = _net_edge_table(organism)
    out = []
    for r in net_fetchall(
        f"SELECT context, COUNT(*) n, SUM(reciprocal) nr FROM {tbl} "
        f"WHERE channel='coessential' GROUP BY context ORDER BY n DESC", organism=organism):
        nodes = net_fetchall(
            f"SELECT COUNT(*) c FROM (SELECT gene_a FROM {tbl} WHERE context=? "
            f"UNION SELECT gene_b FROM {tbl} WHERE context=?)", (r["context"], r["context"]),
            organism=organism)[0]["c"]
        out.append({"value": r["context"], "label": NET_CTX_LABELS.get(r["context"], r["context"]),
                    "n_edges": r["n"], "n_reciprocal": int(r["nr"] or 0), "n_nodes": nodes})
    return out


def _net_fitness_lean(genes, organism="human"):
    """mean fitness percentile per gene → essential / mixed / advantageous node colouring.

    Served from the precomputed reticle.gene_fitness_lean (one row per gene x organism). This used
    to aggregate over harmonized_scores at request time: even with a MATERIALIZED CTE and a correct
    index-scan plan it pulls ~24k rows out of a 28M-row table, which measured 92s once the RDS
    buffer cache went cold (EXPLAIN: 22,423 block reads, 83.6s of shared-read I/O — the plan was
    optimal, the disk was the wall). It is a fixed aggregate over fixed data, so it belongs in a
    tiny lookup table, not in the request path. Falls back to the live aggregate on sqlite, where
    the local file makes it cheap and the precomputed table does not exist."""
    if not genes:
        return {}
    org = "Mus musculus" if organism == "mouse" else "Homo sapiens"
    ph = ",".join("?" * len(genes))
    try:
        if USE_PG:
            rows = db_fetchall(
                f"SELECT gene_symbol g, mean_percentile m FROM gene_fitness_lean "
                f"WHERE organism = ? AND gene_symbol IN ({ph})", [org] + list(genes))
        else:
            rows = db_fetchall(
                f"""SELECT h.GENE_SYMBOL g, AVG(h.PERCENTILE_SCORE) m FROM harmonized_scores h
                    JOIN screen_metadata_curated c ON h.SCREEN_ID = c.screen_id
                    JOIN screen_metadata sm ON sm.SCREEN_ID = h.SCREEN_ID
                    WHERE h.GENE_SYMBOL IN ({ph}) AND c.assay_domain='fitness'
                      AND sm.ORGANISM_OFFICIAL=? AND h.PERCENTILE_SCORE IS NOT NULL
                    GROUP BY h.GENE_SYMBOL""", list(genes) + [org])
    except Exception as e:
        # The lean only decides node COLOUR. Letting it fail takes the whole graph down with it,
        # which is the wrong trade — a grey graph is still the graph. This is not hypothetical:
        # the network lives in its own sqlite mirror (reticle_net.db) while the scores live in
        # reticle.db, so a checkout that has the first and not the second renders nothing at all
        # rather than an uncoloured network.
        print(f"  [net] fitness lean unavailable, nodes will be uncoloured: {e}")
        return {}
    return {r["g"]: float(r["m"]) for r in rows if r["m"] is not None}


# ---------------------------------------------------------------------------
# EVIDENCE TIERS — what actually separates a real edge from a coincidence.
#
# The graph used to draw every edge the same way, with thickness keyed on |r|. The database
# already holds three near-orthogonal statements about any pair and the request path read one:
#
#   channel 1  net_edge.strength / .reciprocal   percentile-profile correlation over ALL screens
#   channel 2  hit_only_connection               Fisher co-hit enrichment over ONLY the screens
#                                                where both genes were CALLED HITS — the cells
#                                                channel 1 dilutes away (compute_hit_only.py).
#                                                417,924 human rows, never read by any endpoint.
#   Jaccard    computed here from the edge list  do the two genes share third parties?
#
# script/exp_evidence_tiers.py measures all four against CORUM same-complex membership, over the
# 11,954 drawn edges whose BOTH endpoints are CORUM-annotated (baseline 0.615%):
#
#     reciprocal AND co-hit     862 edges   7.2%    46.4% precision    75x chance
#     reciprocal only         1,578        13.2%    22.4%              36x
#     co-hit only             1,062         8.9%    17.7%              29x
#     neither                 8,452        70.7%     4.9%               8x
#
# A 9.5x spread, and seven of every ten drawn edges are in the bottom cell. That is the whole
# argument for this block: those 8,452 edges and those 862 edges were the same line on screen.
#
# |r| is deliberately NOT part of the tier. It is the weakest dimension (AUROC 0.6361 vs 0.6991
# for reciprocal) and it is non-monotone where it matters most — the top |r| decile (0.322-0.720)
# scores 17.3% against the second decile's 20.9%. Thickest was not truest. r stays a number on
# the edge panel; the visual weight moves to the tier.
# ---------------------------------------------------------------------------
_TIER_LABEL = {1: "both channels", 2: "mutual-best", 3: "co-hit only", 4: "correlation only"}
_COHIT_UNAVAILABLE = set()      # organisms whose co-hit table is missing — warn once, then hush


def _cohit_table(organism):
    """Channel 2's table. Mirrors _net_edge_table: local sqlite keeps human and mouse in separate
    files under one name, RDS keeps both in one schema so mouse is suffixed."""
    return "hit_only_connection_mouse" if (USE_PG and organism == "mouse") else "hit_only_connection"


def _cohit_among(genes, organism="human"):
    """{(a,b) ordered a<=b: {co_hit, fold, q_value, concordance, support}} for the co-hit pairs
    among `genes`. Absent from the dict = no significant co-hit (the table is already BH-FDR
    filtered at build time, so presence IS significance).

    hit_only_connection stores ONE direction per pair — FANCA->FANCD2 is a row, the reverse is
    not — so callers must normalise the key or they silently miss half the table. Since both
    endpoints are inside `genes`, a symmetric IN/IN predicate catches whichever way it was stored.

    Returns {} rather than raising when the table does not exist: the cloud's RDS sync
    (script/migrate_net_to_rds.py) only carried net_edge until this feature needed channel 2, so a
    deploy can legitimately be missing it. A graph with tiers collapsed to 'channel 1 only' is
    still a graph; a 500 is not."""
    if not genes or organism in _COHIT_UNAVAILABLE:
        return {}
    tbl = _cohit_table(organism)
    ph = ",".join("?" * len(genes))
    try:
        rows = net_fetchall(
            f"SELECT gene_a, gene_b, co_hit, fold, q_value, concordance, support FROM {tbl} "
            f"WHERE gene_a IN ({ph}) AND gene_b IN ({ph})",
            list(genes) + list(genes), organism=organism)
    except Exception as e:
        _COHIT_UNAVAILABLE.add(organism)
        print(f"  [net] co-hit channel unavailable for {organism}, tiers fall back to "
              f"channel 1 only: {e}")
        return {}
    out = {}
    for r in rows:
        a, b = r["gene_a"], r["gene_b"]
        out[(a, b) if a <= b else (b, a)] = {
            "co_hit": int(r["co_hit"]), "fold": round(float(r["fold"]), 2),
            "q_value": float(r["q_value"]), "concordance": round(float(r["concordance"]), 3),
            "support": int(r["support"])}
    return out


def _neighbour_sets(genes, tbl, context, organism="human"):
    """gene -> set of its channel-1 partners in this context, over the WHOLE network.

    Deliberately not restricted to the displayed subgraph: Jaccard measured inside the subgraph
    would be circular (the nodes are there because they are the seed's partners, so they all share
    the seed). The measured lift comes from full-network neighbourhoods."""
    if not genes:
        return {}
    ph = ",".join("?" * len(genes))
    try:
        rows = net_fetchall(
            f"SELECT gene_a, gene_b FROM {tbl} WHERE context=? AND channel='coessential' "
            f"AND (gene_a IN ({ph}) OR gene_b IN ({ph}))",
            [context] + list(genes) + list(genes), organism=organism)
    except Exception as e:
        print(f"  [net] neighbourhood Jaccard unavailable: {e}")
        return {}
    want = set(genes)
    nb = {g: set() for g in genes}
    for r in rows:
        a, b = r["gene_a"], r["gene_b"]
        if a in want:
            nb[a].add(b)
        if b in want:
            nb[b].add(a)
    return nb


def _jaccard(nb, a, b):
    """|N(a) & N(b)| / |N(a) | N(b)|, excluding a and b themselves so a plain A-B edge cannot
    inflate their own coherence. None when either neighbourhood is unknown."""
    na, nbs = nb.get(a), nb.get(b)
    if na is None or nbs is None:
        return None
    na = na - {a, b}
    nbs = nbs - {a, b}
    union = na | nbs
    return round(len(na & nbs) / len(union), 3) if union else 0.0


def _edge_tier(reciprocal, has_cohit):
    """1 both channels · 2 mutual-best only · 3 co-hit only · 4 neither. Ordered by MEASURED
    CORUM precision (46.4 / 22.4 / 17.7 / 4.9%), which is why mutual-best-only outranks
    co-hit-only rather than the other way round."""
    if reciprocal and has_cohit:
        return 1
    if reciprocal:
        return 2
    return 3 if has_cohit else 4


def _annotate_edges(edges, context, organism, tbl):
    """Attach `cohit`, `jaccard` and `tier` to a list of {source,target,strength,reciprocal}.
    Mutates and returns the list, plus a tier histogram for the UI to disclose."""
    from collections import Counter
    genes = sorted({g for e in edges for g in (e["source"], e["target"])})
    ch = _cohit_among(genes, organism=organism)
    nb = _neighbour_sets(genes, tbl, context, organism=organism)
    hist = Counter()
    for e in edges:
        a, b = e["source"], e["target"]
        c = ch.get((a, b) if a <= b else (b, a))
        e["cohit"] = c
        e["jaccard"] = _jaccard(nb, a, b)
        e["tier"] = _edge_tier(bool(e["reciprocal"]), c is not None)
        e["tier_label"] = _TIER_LABEL[e["tier"]]
        hist[e["tier"]] += 1
    return edges, {str(t): hist.get(t, 0) for t in (1, 2, 3, 4)}


def screen_net(gene, context, reciprocal_only=True, top=18, organism="human"):
    """One gene's context neighborhood as a clustered graph: seed + its top partners
    + the partner-partner edges among them (so it reads as modules, not a star)."""
    from collections import Counter
    tbl = _net_edge_table(organism)
    g = gene.strip()
    seed = None
    for v in dict.fromkeys([g, g.upper(), g.capitalize()]):
        if net_fetchall(f"SELECT 1 FROM {tbl} WHERE context=? AND (gene_a=? OR gene_b=?) LIMIT 1",
                        (context, v, v), organism=organism):
            seed = v
            break
    if seed is None:
        return None
    # Mutual-best is the clean view but only 40% of genes HAVE a reciprocal partner — asking for
    # it first and silently returning nothing rendered an empty graph for 59.7% of the network.
    # Try reciprocal, fall back to one-directional, and tell the UI which view it actually got.
    def _partners(recip):
        rec = "AND reciprocal=1 " if recip else ""
        return rec, net_fetchall(
            f"SELECT CASE WHEN gene_a=? THEN gene_b ELSE gene_a END nb, strength "
            f"FROM {tbl} WHERE context=? AND channel='coessential' AND (gene_a=? OR gene_b=?) {rec}"
            f"ORDER BY strength DESC LIMIT ?", (seed, context, seed, seed, top), organism=organism)

    rec, rows = _partners(reciprocal_only)
    fellback = False
    if not rows and reciprocal_only:                 # no mutual-best partner → widen, don't blank
        rec, rows = _partners(False)
        fellback, reciprocal_only = True, False
    if not rows:
        return None
    nodeset = [seed] + [r["nb"] for r in rows]
    nsi = set(nodeset)
    ph = ",".join("?" * len(nodeset))
    erows = net_fetchall(
        f"SELECT gene_a, gene_b, strength, reciprocal FROM {tbl} "
        f"WHERE context=? AND channel='coessential' AND gene_a IN ({ph}) AND gene_b IN ({ph}) {rec}",
        [context] + nodeset + nodeset, organism=organism)
    lean = _net_fitness_lean(nodeset, organism=organism)

    def lab(m):
        return None if m is None else ("essential" if m < -0.15 else "advantageous" if m > 0.15 else "mixed")

    deg, edges = Counter(), []
    for e in erows:
        a, b = e["gene_a"], e["gene_b"]
        if a in nsi and b in nsi and a != b:
            edges.append({"source": a, "target": b, "strength": round(e["strength"], 3),
                          "reciprocal": int(e["reciprocal"])})
            deg[a] += 1; deg[b] += 1
    # Second channel + neighbourhood coherence. NB in the reciprocal view `erows` is already
    # filtered to reciprocal=1, so every edge lands in tier 1 or 2 and the tier only reports
    # whether channel 2 agrees. The full four-tier spread only appears once the user widens the
    # view — which is exactly where they most need to be told which of the ~29 new edges is worth
    # anything, since 70.7% of all drawn edges sit in the 4.9%-precision bottom tier.
    edges, tiers = _annotate_edges(edges, context, organism, tbl)
    # `mean_percentile`, not median: _net_fitness_lean averages (AVG / precomputed mean_percentile).
    nodes = [{"id": n, "label": n, "focus": (n == seed), "lean": lab(lean.get(n)),
              "mean_percentile": round(lean[n], 3) if n in lean else None, "degree": deg.get(n, 0)}
             for n in nodeset]
    # How many partners the WIDER view holds, so a sparse graph can name the number instead of
    # leaving the reader to guess whether one partner means "no signal" or "nothing loaded".
    # A count, not the edges: the panel only needs to decide whether widening is worth offering.
    n_wider = net_fetchall(
        f"SELECT COUNT(*) c FROM {tbl} WHERE context=? AND channel='coessential' "
        f"AND (gene_a=? OR gene_b=?)", (context, seed, seed), organism=organism)[0]["c"]
    return {"focus": seed, "context": context, "context_label": NET_CTX_LABELS.get(context, context),
            "reciprocal_only": reciprocal_only, "fellback": fellback,
            "nodes": nodes, "edges": edges, "tiers": tiers, "n_wider": int(n_wider),
            "cohit_available": organism not in _COHIT_UNAVAILABLE}


# ---------------------------------------------------------------------------
# Predict a gene's UNDISCOVERED function from RETICLE's OWN BioGRID co-essentiality
# network (net_edge) — distinct from predict_functions() above, which reasons over
# EXTERNAL STRING + DepMap co-essentiality. This is the one that answers "what does
# OUR network, that nobody else has, let us discover?" gpt-5 reasons over the focal
# gene's net_edge partners' real curated annotations (GO / Reactome / UniProt) and
# proposes a shared complex/pathway/process the focal gene is not yet annotated with.
# ---------------------------------------------------------------------------
_NET_PRED_CACHE = {}


def _net_predict_partners(seed, tbl, context, organism, top=18):
    """Partners for the prediction dossier: ALWAYS the union top-`top`, each graded by evidence
    tier against the seed.

    This deliberately no longer mirrors the graph's reciprocal-only toggle, and that is a reversal
    of the previous fix, so the reasoning is worth stating.

    The bug before that fix was that the dossier was assembled reciprocal-first no matter what was
    on screen — a user could widen the graph to 29 partners, press Predict, and the model would
    silently read 2. The fix made the dossier follow the toggle. That closed the honesty gap but
    kept the real damage: the toggle is a DISPLAY choice, and letting it decide what evidence the
    model reads means 812 of 5,269 human genes (15.4%) — the ones with exactly one reciprocal
    partner — trip the `n_annotated < 2` early return every single time and can NEVER produce a
    prediction, while ~29 one-directional partners sit unread. Median reciprocal degree is 2
    against a median union degree of 29; only 2.6% of genes have the 18 reciprocal partners this
    dossier is sized for, against 86.7% in the union.

    So: read the union always, grade every partner, and REPORT the difference rather than either
    hiding it (the old bug) or obeying it (the old fix). Two side effects, both wanted — the
    dossier is now reproducible across users regardless of their display state, which is why
    `view` no longer belongs in the cache key; and a partner arriving through the widened window
    is not treated as equal to a mutual-best one, because it carries its tier.
    """
    rows = net_fetchall(
        f"SELECT CASE WHEN gene_a=? THEN gene_b ELSE gene_a END nb, strength, reciprocal "
        f"FROM {tbl} WHERE context=? AND channel='coessential' AND (gene_a=? OR gene_b=?) "
        f"ORDER BY strength DESC LIMIT ?", (seed, context, seed, seed, top), organism=organism)
    if not rows:
        return [], {}
    ch = _cohit_among([seed] + [r["nb"] for r in rows], organism=organism)
    out = []
    for r in rows:
        nb = r["nb"]
        c = ch.get((seed, nb) if seed <= nb else (nb, seed))
        out.append({"nb": nb, "strength": r["strength"], "reciprocal": int(r["reciprocal"]),
                    "tier": _edge_tier(bool(r["reciprocal"]), c is not None),
                    "cohit_fold": c["fold"] if c else None})
    from collections import Counter
    hist = Counter(p["tier"] for p in out)
    return out, {str(t): hist.get(t, 0) for t in (1, 2, 3, 4)}


def _net_predict_go_bp(gene_ids, cap=8):
    """gene_id -> [GO biological-process name, ...] (non-obsolete), capped per gene."""
    if not gene_ids:
        return {}
    ph = ",".join("?" * len(gene_ids))
    out = {}
    for row in kb_fetchall(
        f"SELECT gg.gene_id gid, t.name name FROM kb_gene_go gg JOIN kb_go_term t ON t.go_id=gg.go_id "
        f"WHERE gg.gene_id IN ({ph}) AND t.namespace='biological_process' AND t.is_obsolete=0 "
        f"{_GO_POSITIVE} ORDER BY gg.gene_id", list(gene_ids)):
        lst = out.setdefault(row["gid"], [])
        if len(lst) < cap and row["name"] not in lst:
            lst.append(row["name"])
    return out


def _net_predict_pathways(gene_ids, cap=5):
    """gene_id -> [Reactome pathway name, ...], capped per gene."""
    if not gene_ids:
        return {}
    ph = ",".join("?" * len(gene_ids))
    out = {}
    for row in kb_fetchall(
        f"SELECT gene_id gid, name FROM kb_gene_pathway WHERE gene_id IN ({ph}) ORDER BY gene_id", list(gene_ids)):
        lst = out.setdefault(row["gid"], [])
        if len(lst) < cap and row["name"] not in lst:
            lst.append(row["name"])
    return out


def _net_predict_oneliner(gene_ids, cap_chars=220):
    """gene_id -> a short cleaned curated-function sentence (UniProt first, else NCBI description)."""
    if not gene_ids:
        return {}
    ph = ",".join("?" * len(gene_ids))
    out = {}
    for row in kb_fetchall(
        f"SELECT gene_id gid, uniprot_function, description FROM kb_gene WHERE gene_id IN ({ph})", list(gene_ids)):
        text, _ = _clean_uniprot(row["uniprot_function"])
        text = text or row["description"]
        if text:
            out[row["gid"]] = (text[:cap_chars] + "…") if len(text) > cap_chars else text
    return out


NET_PREDICT_SYS = """You are a functional-genomics analyst working inside RETICLE. A FOCAL gene was mapped in \
RETICLE's OWN CRISPR co-essentiality network — edges are correlations between genes' knockout-fitness profiles \
across pooled BioGRID screens. Genes whose knockout-fitness profiles correlate tend to act in the SAME protein \
complex, the SAME pathway, or the SAME biological process. That co-essentiality relationship is your ONLY \
inference license.

You are given (1) the focal gene's strongest co-essential PARTNERS, each with its real curated annotations — \
GO biological-process terms, Reactome pathways, a one-line curated function, and its own knockout-fitness lean \
— and (2) the focal gene's OWN known functions, listed separately.

TASK: Decide whether the partners CONVERGE on a specific, named protein complex, pathway, or biological process. \
If they do, predict the focal gene's membership or role in it.

STRICT RULES (a broken rule makes that prediction useless — omit it instead):
1. Ground every prediction ONLY in the partner annotations given below. Invent no gene, complex, pathway, or \
term that is not present in the partner evidence. Use NO outside knowledge about any gene, including the focal \
gene — reason only from what is written below.
2. NOVELTY IS THE POINT: never predict anything already listed in the focal gene's KNOWN FUNCTION block, or an \
obvious synonym of it. If a convergence merely restates something the focal gene is already annotated with, \
drop it.
3. Every prediction MUST name the partners that support it (exact symbols from the list below). Name ALL of them \
and ONLY the ones that genuinely carry the claim — a partner you list is a partner a human will check. Two or \
more is the normal case; ONE is acceptable only when that single partner's evidence tier is [T1]. Do not pad the \
list to reach a count, and do not compute a confidence score yourself.
3b. EVIDENCE TIERS are marked on each partner below and they are measured, not decorative. Against CORUM \
same-complex membership: [T1] 46.4% · [T2] 22.4% · [T3] 17.7% · [T4] 4.9%, where a random annotated pair is 0.6%. \
A claim carried by two [T1] partners is worth far more than one carried by four [T4] partners. Weigh them \
accordingly, and prefer convergences that the higher-tier partners agree on.
4. Prefer the single most specific, defensible claim: a named complex beats a named pathway beats a vague \
process. Return 0-5 predictions — a short list of strong claims, not a long list of speculative ones.
5. If the partners do NOT converge on anything coherent, return an empty predictions list and say so plainly in \
"summary". Do not manufacture a guess to fill the list.
6. Never assert directionality, sign, or epistasis (no "activates", "represses", "required for", "sensitizes") \
— co-essentiality is undirected. Say the focal gene "likely participates in" or "is a candidate component of" \
the shared process.

Return ONLY a single JSON object of this exact shape, no prose, no markdown fences:
{"converges": true|false,
 "predictions": [{"prediction": "<specific complex/pathway/process name>",
                   "type": "complex"|"pathway"|"process",
                   "supporting_partners": ["<SYMBOL>", "<SYMBOL>", ...],
                   "rationale": "<1-2 sentences, grounded only in the partner annotations above>"}],
 "summary": "<one sentence overall — or why nothing converged>"}"""


def _net_predict_prompt(sym, organism, context_label, view, own_bp, own_pw, own_fn, partners):
    """partners: list of dicts {sym, strength, reciprocal, lean, go, pw, fn} in strength-desc order."""
    def esc_join(xs):
        return "; ".join(xs) if xs else "(none on record)"
    lines = [
        f"FOCAL GENE: {sym} ({organism}) — co-essentiality context: {context_label} · view: {view}",
        "",
        f"KNOWN FUNCTION of {sym}  (do NOT predict any of these — this is the novelty-exclusion list):",
        f"  GO biological-process: {esc_join(own_bp)}",
        f"  Reactome pathways: {esc_join(own_pw)}",
        f"  Curated function: {own_fn or '(poorly characterized — no curated summary on record)'}",
        "",
        "CO-ESSENTIAL PARTNERS (your evidence — each is a REAL curated annotation set; "
        "r = knockout-fitness profile correlation, ⇄ = mutual-best, ×N = co-hit enrichment, "
        "[T1]-[T4] = measured evidence tier, T1 strongest):",
    ]
    any_annotated = False
    for p in partners:
        has_evidence = bool(p["go"] or p["pw"] or p["fn"])
        if not has_evidence:
            continue
        any_annotated = True
        tag = (f"[T{p['tier']}] r={p['strength']:.2f}{' ⇄' if p['reciprocal'] else ''}"
               + (f" co-hit {p['cohit_fold']}×" if p.get("cohit_fold") else ""))
        lean_txt = f", fitness: {p['lean']}" if p["lean"] else ""
        lines.append(f"### {p['sym']}  ({tag}{lean_txt})")
        lines.append(f"  GO biological-process: {esc_join(p['go'])}")
        lines.append(f"  Reactome pathways: {esc_join(p['pw'])}")
        lines.append(f"  Curated function: {p['fn'] or '(none)'}")
    if not any_annotated:
        lines.append("(no partner carries any curated annotation)")
    lines += ["", f"Now: identify the complex/pathway/process these partners converge on, and predict {sym}'s "
                  f"role in it — obeying the novelty rule. Return the JSON object now."]
    return "\n".join(lines)


def net_predict_functions(gene, context, organism="human", top=18, reciprocal_only=True):
    """Guilt-by-association from OUR OWN BioGRID net_edge network (not STRING/DepMap): the model
    reasons over the focal gene's co-essential partners' real curated functions and proposes a
    complex/pathway/process the focal gene likely shares but is not yet annotated with.

    `reciprocal_only` is the caller's DISPLAY state. It no longer selects the dossier — that is
    always the tier-graded union — and is used only to report `n_beyond_view`."""
    from llm_client import WashULLMClient
    taxid = 10090 if organism == "mouse" else 9606
    tbl = _net_edge_table(organism)
    g = gene.strip()
    seed = None
    for v in dict.fromkeys([g, g.upper(), g.capitalize()]):
        if net_fetchall(f"SELECT 1 FROM {tbl} WHERE context=? AND (gene_a=? OR gene_b=?) LIMIT 1",
                        (context, v, v), organism=organism):
            seed = v
            break
    if seed is None:
        return None

    prows, partner_tiers = _net_predict_partners(seed, tbl, context, organism, top=top)
    if not prows:
        return None
    partner_syms = [r["nb"] for r in prows]
    partner_meta = {r["nb"]: {"strength": round(r["strength"], 3),
                              "reciprocal": bool(r["reciprocal"]), "tier": r["tier"],
                              "cohit_fold": r["cohit_fold"]} for r in prows}
    # How much of this dossier the user could NOT see under their current graph filter. Reported,
    # never acted on: the model reads the union either way (see _net_predict_partners).
    n_beyond_view = sum(1 for r in prows if not r["reciprocal"]) if reciprocal_only else 0

    seed_r = _kb_resolve(seed, taxid)
    resolved = {}   # symbol -> gene_id, for partners that exist in the KB
    for sym in partner_syms:
        r = _kb_resolve(sym, taxid)
        if r:
            resolved[sym] = r["gene_id"]
    n_unresolved = len(partner_syms) - len(resolved)

    lean = _net_fitness_lean([seed] + partner_syms, organism=organism)

    def lean_label(m):
        return None if m is None else ("essential" if m < -0.15 else "advantageous" if m > 0.15 else "mixed")

    all_gids = list(resolved.values()) + ([seed_r["gene_id"]] if seed_r else [])
    go_by_gid = _net_predict_go_bp(all_gids)
    pw_by_gid = _net_predict_pathways(all_gids)
    fn_by_gid = _net_predict_oneliner(all_gids)

    own_bp, own_pw, own_fn = [], [], None
    if seed_r:
        own_bp = go_by_gid.get(seed_r["gene_id"], [])
        own_pw = pw_by_gid.get(seed_r["gene_id"], [])
        own_fn = fn_by_gid.get(seed_r["gene_id"])
    own_bp_norm = {t.strip().lower() for t in own_bp}
    own_pw_norm = {t.strip().lower() for t in own_pw}

    partners = []
    for sym in partner_syms:
        gid = resolved.get(sym)
        partners.append({
            "sym": sym, "strength": partner_meta[sym]["strength"], "reciprocal": partner_meta[sym]["reciprocal"],
            "tier": partner_meta[sym]["tier"], "cohit_fold": partner_meta[sym]["cohit_fold"],
            "lean": lean_label(lean.get(sym)),
            "go": go_by_gid.get(gid, []) if gid else [],
            "pw": pw_by_gid.get(gid, []) if gid else [],
            "fn": fn_by_gid.get(gid) if gid else None,
        })
    n_annotated = sum(1 for p in partners if p["go"] or p["pw"] or p["fn"])
    view = "union"     # always, now — see _net_predict_partners

    if n_annotated < 2:
        # Genuinely nothing to reason over. This is now a real annotation-coverage statement: the
        # dossier already read the full union, so the old "widen the view and it will improve"
        # advice would be a lie — there is no wider view left.
        return {"found": True, "symbol": seed, "organism": organism, "context": context,
                "context_label": NET_CTX_LABELS.get(context, context), "view": view,
                "n_partners": len(partner_syms), "n_annotated_partners": n_annotated,
                "n_unresolved": n_unresolved, "partner_tiers": partner_tiers,
                "model": None, "converges": False, "predictions": [], "no_call": True,
                "summary": (
                    f"Only {n_annotated} of this gene's {len(partner_syms)} co-essential partners "
                    "carries a curated function on record, so no prediction was attempted. This is "
                    "an annotation-coverage limit, not a filter — the dossier already reads every "
                    "partner, mutual-best or not.")}

    # Everything that changes the answer belongs in the key. It used to be (gene, organism,
    # context) only, so switching the model or editing NET_PREDICT_SYS let a warm process keep
    # serving the previous answer labelled with the new model's name — a reproducibility bug in
    # the one feature whose entire pitch is auditability. `view` used to be here too and no longer
    # needs to be: the dossier is the union regardless of the caller's display state, which is
    # itself the point — two users on the same gene now get the same answer.
    cache_key = (seed_r["gene_id"] if seed_r else seed, organism, context,
                 NET_PREDICT_MODEL, NET_PREDICT_PROMPT_VERSION)
    if cache_key in _NET_PRED_CACHE:
        return _NET_PRED_CACHE[cache_key]

    prompt = _net_predict_prompt(seed, organism, NET_CTX_LABELS.get(context, context), view,
                                  own_bp, own_pw, own_fn, partners)
    client = WashULLMClient(model=NET_PREDICT_MODEL)
    data = client.chat_json([{"role": "system", "content": NET_PREDICT_SYS},
                              {"role": "user", "content": prompt}], **_gen_kwargs(NET_PREDICT_MODEL, max_tokens=3000))

    # ---- server-side validation: every check runs at FULL strength, nothing is deleted ---------
    # This used to `continue` past any prediction that failed a check. The checks were right; the
    # deletion was not. Three things were wrong with dropping:
    #   * The anti-hallucination check is the product's whole claim to being auditable, and it fired
    #     in the dark. Nobody could show it had ever caught anything, which is indistinguishable
    #     from it not working.
    #   * `len(cited) < 2` COUNTS HEADS when it should WEIGH EVIDENCE. One [T1] supporter recovers
    #     a CORUM complex 46.4% of the time; two [T4] supporters do so 4.9% each. The old rule
    #     dropped the first and kept the second.
    #   * The professor's ask — let users see below the top confidence band — is unanswerable while
    #     the weaker material never leaves the server.
    # So: same checks, same thresholds, but they now produce a VERDICT that ships with the
    # prediction. The client decides what to show; the server decides what is true.
    #
    # One check got STRICTER rather than looser. partner_by_sym used to cover every partner,
    # including the unannotated ones _net_predict_prompt skips — so citing a partner the model was
    # never shown counted as support. It cannot: an unannotated partner contributes no annotation to
    # reason from, so a citation of one is a name produced without having read anything about it,
    # which is precisely what this check exists to catch. Restricting to the shown set is the honest
    # reading of "verifiable".
    partner_by_sym = {p["sym"]: p for p in partners if p["go"] or p["pw"] or p["fn"]}
    preds_out, n_ghost_citations = [], 0
    for pred in (data.get("predictions") or []):
        name = (pred.get("prediction") or "").strip()
        if not name:
            continue
        raw = list(dict.fromkeys(s for s in (pred.get("supporting_partners") or [])
                                 if isinstance(s, str) and s.strip()))
        cited = [s for s in raw if s in partner_by_sym]
        ghosts = [s for s in raw if s not in partner_by_sym]   # named a partner that is not there
        n_ghost_citations += len(ghosts)
        supporters = [{"symbol": s, "strength": partner_by_sym[s]["strength"],
                       "reciprocal": partner_by_sym[s]["reciprocal"],
                       "tier": partner_by_sym[s]["tier"],
                       "cohit_fold": partner_by_sym[s]["cohit_fold"]} for s in cited]
        supporters.sort(key=lambda x: (x["tier"], -x["strength"]))
        best_tier = min((s["tier"] for s in supporters), default=4)
        n_strong = sum(1 for s in supporters if s["tier"] <= 2)

        norm = name.lower().strip()
        if norm in own_bp_norm or norm in own_pw_norm:
            verdict = "rejected:not-novel"               # restates what the gene is already annotated with
        elif not supporters:
            verdict = "rejected:no-verifiable-support"   # every symbol it cited was invented
        elif len(supporters) == 1:
            # Weight, not headcount. A lone [T1] supporter is a stronger statement than a pair of
            # [T4]s, so it is promoted rather than demoted — this is the one place the old rule was
            # not merely blunt but backwards.
            verdict = "verified" if best_tier == 1 else "single-supporter"
        else:
            verdict = "verified"

        strengths = [s["strength"] for s in supporters]
        n_recip = sum(1 for s in supporters if s["reciprocal"])
        confidence = ("high" if n_strong >= 2 or (best_tier == 1 and len(supporters) >= 2)
                      else "moderate" if best_tier <= 3
                      else "low")
        convergence = ((f"{len(supporters)} partner{'' if len(supporters) == 1 else 's'} · "
                        f"r {min(strengths):.2f}–{max(strengths):.2f}"
                        + (f" · {n_recip} mutual-best" if n_recip else "")
                        + f" · best tier T{best_tier}") if supporters else "no verifiable support")
        preds_out.append({
            "prediction": name,
            "type": pred.get("type") if pred.get("type") in ("complex", "pathway", "process") else "process",
            "verdict": verdict, "evidence_tier": best_tier if supporters else None,
            "confidence": confidence, "convergence": convergence,
            "rationale": (pred.get("rationale") or "").strip(), "supporting_partners": supporters,
            "unverifiable_citations": ghosts,
        })

    tally = {"verified": 0, "single-supporter": 0,
             "rejected:not-novel": 0, "rejected:no-verifiable-support": 0}
    for p in preds_out:
        tally[p["verdict"]] = tally.get(p["verdict"], 0) + 1

    out = {"found": True, "symbol": seed, "organism": organism, "context": context,
           "context_label": NET_CTX_LABELS.get(context, context), "view": view,
           "n_partners": len(partner_syms), "n_annotated_partners": n_annotated,
           "n_unresolved": n_unresolved, "partner_tiers": partner_tiers,
           "n_beyond_view": n_beyond_view, "model": client.model,
           # `converges` stays the STRICT reading — it is what the headline renders from, and
           # loosening it would quietly restate a single-supporter hunch as a finding.
           "converges": any(p["verdict"] == "verified" for p in preds_out),
           "predictions": preds_out, "verdicts": tally,
           "n_unverifiable_citations": n_ghost_citations,
           "summary": (data.get("summary") or "").strip()}
    if preds_out:
        _NET_PRED_CACHE[cache_key] = out
    return out


# ---------------------------------------------------------------------------
# Per-gene in-screen score distribution — the focal gene's position vs the full
# distribution of every gene measured in the same screen, over its strongest
# FULL screens. Toggle among the 3 stored normalizations of the one native score.
# ---------------------------------------------------------------------------
_DIST_COL = {"native": "HARMONIZED_SCORE", "percentile": "PERCENTILE_SCORE", "robustz": "ROBUST_Z_SCORE"}


def _local_scores_fetch(sql, params=()):
    """The distribution/ranking queries do heavy per-screen scans (~20k rows) — served from
    the LOCAL sqlite mirror, ~50x faster than a remote RDS round-trip for this shape (0.3s vs
    15s). Falls back to db_fetchall only if the local file is absent (e.g. a pure-cloud deploy)."""
    import os
    if os.path.exists(DB):
        con = sqlite3.connect(DB)
        con.row_factory = sqlite3.Row
        try:
            return con.execute(sql, params).fetchall()
        finally:
            con.close()
    return db_fetchall(sql, params)


def _score_method_label(sb):
    """SCORE_BASIS like 'DIR_POS(Log2FC)' -> 'Log2FC' (strip provenance decoration)."""
    if not sb:
        return "native score"
    a, b = sb.find("("), sb.rfind(")")
    return sb[a + 1:b].strip() if (a != -1 and b > a) else sb.strip()


def _histogram(vals, focal, nbins=40, bounded=None):
    """Pure-python histogram; clip range to 1st–99th pct for readability (or fixed `bounded`)."""
    xs = sorted(vals)
    n = len(xs)
    if bounded:
        lo, hi = bounded
    else:
        lo, hi = xs[max(0, int(0.01 * n))], xs[min(n - 1, int(0.99 * n))]
    if hi <= lo:
        lo, hi = xs[0], xs[-1]
    if hi <= lo:
        hi = lo + 1.0
    width = (hi - lo) / nbins
    counts = [0] * nbins
    for v in xs:
        counts[min(nbins - 1, max(0, int((v - lo) / width)))] += 1
    fb = min(nbins - 1, max(0, int((focal - lo) / width)))
    return {"bins": [{"x0": round(lo + i * width, 4), "c": counts[i]} for i in range(nbins)],
            "lo": round(lo, 4), "hi": round(hi, 4), "width": round(width, 6), "focal_bin": fb, "nbins": nbins}


def gene_screen_distribution(gene, taxid=9606, screen=None, score="percentile", top=12):
    """A gene's position within a screen vs the full in-screen distribution of all genes,
    for the gene's strongest FULL screens. score in {native, percentile, robustz}."""
    org = "Mus musculus" if str(taxid) == "10090" else "Homo sapiens"
    variants = resolve_symbol_variants(gene)
    ph = ",".join("?" * len(variants))
    # Rank a gene's screens by ABSOLUTE effect, not by most-negative percentile. The old
    # `ORDER BY PERCENTILE_SCORE ASC` was a tautology — it picked the screen where the gene ranks
    # most depleted, so the panel always opened "1st percentile", and a gene's ENRICHED
    # (positive-selection) screens were structurally unreachable in the dropdown.
    trows = _local_scores_fetch(
        f"""SELECT h.SCREEN_ID sid, h.GENE_SYMBOL sym, h.HARMONIZED_SCORE harm,
                   h.PERCENTILE_SCORE pct, h.ROBUST_Z_SCORE rz, h.IS_HIT hit,
                   m.CELL_LINE cell, m.PHENOTYPE pheno, m.SCORE_BASIS basis
            FROM harmonized_scores h JOIN screen_metadata m ON m.SCREEN_ID = h.SCREEN_ID
            WHERE h.GENE_SYMBOL IN ({ph}) AND m.ORGANISM_OFFICIAL = ? AND m.COVERAGE_TYPE = 'FULL'
                  AND h.PERCENTILE_SCORE IS NOT NULL
            ORDER BY ABS(h.PERCENTILE_SCORE) DESC, h.IS_HIT DESC, ABS(h.ROBUST_Z_SCORE) DESC
            LIMIT ?""", variants + [org, top])
    if not trows:
        return None
    seed = trows[0]["sym"]
    screens = [{"sid": r["sid"],
                "label": (r["cell"] or "?") + ((" · " + r["pheno"]) if r["pheno"] else ""),
                "method": _score_method_label(r["basis"]),
                "pct": round(r["pct"], 3), "hit": int(r["hit"] or 0)} for r in trows]
    sids = {r["sid"] for r in trows}
    sid = screen if screen in sids else trows[0]["sid"]
    srow = next(r for r in trows if r["sid"] == sid)

    col = _DIST_COL.get(score, "PERCENTILE_SCORE")
    drows = _local_scores_fetch(
        f"SELECT {col} v FROM harmonized_scores WHERE SCREEN_ID = ? AND {col} IS NOT NULL", (sid,))
    vals = [r["v"] for r in drows]
    if len(vals) < 5:
        return None
    focal = srow["harm"] if score == "native" else srow["rz"] if score == "robustz" else srow["pct"]
    focal = 0.0 if focal is None else focal
    hist = _histogram(vals, focal, bounded=(-1.0, 1.0) if score == "percentile" else None)
    # MIDRANK for ties: strict `v < focal` reported 0 on the tie-saturated screens (p-value-clipped
    # ones where a third of the genome sits on the same floor value), making the caption false.
    # Ties count half, which is the standard fractional-rank definition.
    n_below = sum(1 for v in vals if v < focal)
    n_tied = sum(1 for v in vals if v == focal)
    below = n_below + 0.5 * n_tied
    return {
        "focus": seed, "taxid": taxid, "screen": sid, "score": score, "screens": screens,
        "screen_meta": {"label": next(s["label"] for s in screens if s["sid"] == sid),
                        "method": _score_method_label(srow["basis"]), "coverage": "FULL"},
        "dist": hist,
        "focal": {"value": round(focal, 4), "bin": hist["focal_bin"], "n_genes": len(vals),
                  "pct_in_screen": round(below / len(vals), 4), "n_tied": n_tied,
                  "direction": "depleted" if focal < 0 else "enriched" if focal > 0 else "neutral",
                  "is_hit": int(srow["hit"] or 0)},
    }


# ---------------------------------------------------------------------------
# Screen-vs-screen similarity — Homo sapiens · fitness · genome-wide (FULL).
# Pairwise-complete Pearson on PC1-removed percentiles, precomputed for all screen pairs
# and served as an indexed lookup. The old |a|*|b| weighting was removed: weighting by
# the values being correlated is selection on the outcome and inflated r by ~0.17.
# ---------------------------------------------------------------------------
# Served from reticle.screen_similarity (precomputed by script/migrate_screen_similarity.py).
# The former in-memory 57MB .npz + per-request SVD is gone: it made this the one feature that
# 404'd on a cloud deploy, and the matrix duplicated harmonized_scores, which is already on RDS.


def _screen_label(meta_row, sid):
    author, cell, pmid, ngenes = meta_row
    return {"author": str(author) or "—", "cell_line": str(cell) or "—",
            "pmid": str(pmid) or "", "n_genes": int(ngenes) if str(ngenes).isdigit() else None}


def screen_similar(screen_id, limit=50, offset=0, min_overlap=2000, exclude_same_study=False):
    """Screens whose gene-level fitness profile resembles the query's.

    Three deliberate choices, each measured on this matrix:
      * PLAIN pairwise-complete Pearson, on the PC1-removed values. The previous version ranked by
        a "weighted" Pearson with w = |a|*|b|. That weight is a function of the very values being
        correlated — selection on the outcome — and it inflated r by ~0.17 (0.695 -> 0.869 on a
        real pair) by up-weighting exactly the pan-essential genes every fitness screen shares.
      * Z AGAINST THIS QUERY'S OWN BACKGROUND. A raw r is unreadable here: any two human fitness
        screens correlate ~0.35 for free. z = (r - mean_r) / sd_r over the whole comparable pool
        answers the question the user actually has — "is this MORE alike than usual?".
      * min_overlap 2,000 (was 200): 200 shared genes out of ~19k is a noise-dominated estimate.

    KNOWN, UNFIXED — batch/study effect dominates and is NOT removed by any of the above: for a
    Behan-2019 query, 50/50 of the top hits were that same publication, and after excluding it the
    next 9/10 were a single other publication. Same study = same library, protocol, batch and
    analysis, which is a real technical similarity. `same_study` is therefore returned per row and
    `exclude_same_study` is offered, so the caller can see and control the confound rather than
    mistake it for biology. Even the best cross-study match sits only ~1.2 sd above background.
    """
    sid = str(screen_id).strip()
    # Served from reticle.screen_similarity on RDS — precomputed by script/migrate_screen_similarity.py
    # with the PC1 removal and pairwise-complete definition above. Replaces the old 57MB local .npz
    # (which made this the one feature that 404'd on a cloud deploy) and the per-request SVD.
    qm = db_fetchall("SELECT screen_id, author, cell_line, pmid, n_genes FROM screen_sim_meta "
                     "WHERE screen_id = ?", (sid,))
    if not qm:
        return None
    qrow = qm[0]
    qpmid = str(qrow["pmid"] or "")
    raw = db_fetchall(
        """SELECT s.screen_b sb, s.r, s.overlap, m.author, m.cell_line, m.pmid, m.n_genes
           FROM screen_similarity s JOIN screen_sim_meta m ON m.screen_id = s.screen_b
           WHERE s.screen_a = ? AND s.overlap >= ?""", (sid, int(min_overlap)))
    rows = []
    for x in raw:
        pm = str(x["pmid"] or "")
        rows.append({"screen_id": x["sb"], "r": round(float(x["r"]), 3), "overlap": int(x["overlap"]),
                     "same_study": bool(pm and pm == qpmid),
                     "author": str(x["author"] or "—"), "cell_line": str(x["cell_line"] or "—"),
                     "pmid": pm, "n_genes": int(x["n_genes"]) if x["n_genes"] is not None else None})

    # background = this query's correlation with the whole comparable pool
    if rows:
        allr = np.array([x["r"] for x in rows], dtype=np.float64)
        mu, sd = float(allr.mean()), float(allr.std())
        for x in rows:
            x["z"] = round((x["r"] - mu) / sd, 2) if sd > 0 else 0.0
    else:
        mu = sd = 0.0

    n_same = sum(1 for x in rows if x["same_study"])
    if exclude_same_study:
        rows = [x for x in rows if not x["same_study"]]
    rows.sort(key=lambda x: -x["r"])
    offset = max(0, int(offset)); limit = max(1, int(limit))
    return {"query": {"screen_id": sid, "author": str(qrow["author"] or "—"),
                      "cell_line": str(qrow["cell_line"] or "—"), "pmid": qpmid,
                      "n_genes": int(qrow["n_genes"]) if qrow["n_genes"] is not None else None},
            "n_pool": len(raw) + 1, "n_total": len(rows), "offset": offset,
            "background": {"mean_r": round(mu, 3), "sd_r": round(sd, 3)},
            "n_same_study": n_same, "exclude_same_study": bool(exclude_same_study),
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
# Gene wiki — read side over the local knowledge base (kb.db, 6 sources).
# Deterministic facts only; the AI synthesis is a separate grounded layer.
# ---------------------------------------------------------------------------

def _kb_on_pg():
    """True when the KB will be served from RDS (no local mirror). Callers that need
    dialect-specific SQL (e.g. GROUP_CONCAT vs STRING_AGG) must branch on this."""
    import os
    return USE_PG and not os.path.exists(KB_DB)


# GO annotations carry a qualifier; "NOT involved_in" / "NOT enables" mean the curator
# established the gene does NOT do this. Those rows must never be read as positive evidence
# (kb.db holds ~2.3k of them). Append this to any query that treats a GO row as "gene does X".
# The one place we deliberately do NOT filter is the novelty-exclusion set in predict_functions:
# there, a NOT annotation is a contraindication and should also suppress the prediction.
#
# substr() rather than `NOT LIKE 'NOT%'`: on the Postgres path db_fetchall hands the SQL to psycopg2
# with bound parameters, and psycopg2 %-formats the query — a LITERAL '%' is then read as a format
# specifier and raises "IndexError: tuple index out of range". kb reads normally hit the local
# sqlite mirror (where % is harmless), so this only bites a deploy with no local kb.db. Every
# negative qualifier is 'NOT <relation>' and no positive one starts with NOT, so this is exactly
# equivalent and %-free.
_GO_POSITIVE = "AND (gg.qualifier IS NULL OR substr(gg.qualifier, 1, 3) <> 'NOT')"


def kb_fetchall(sql, params=()):
    """Gene-wiki knowledge base. Prefers the local kb.db mirror (fast: no per-query network
    round-trip, and gene_wiki issues ~11 of these), falls back to the RDS reticle schema when
    the file is absent — so a cloud deploy with no local mirror still serves the wiki."""
    if _kb_on_pg():
        return db_fetchall(sql, params)
    con = sqlite3.connect(KB_DB)
    con.row_factory = sqlite3.Row
    try:
        return con.execute(sql, params).fetchall()
    finally:
        con.close()


_PUBMED_CLUSTER = re.compile(r"\s*\((?:PubMed:\d+)(?:,\s*PubMed:\d+)*\)")


def _clean_uniprot(text):
    """Collapse the dense inline (PubMed:...) citation clusters for DISPLAY. The
    raw text (with refs) stays in kb.db for provenance; here we surface readable
    prose plus the distinct citation count. Returns (clean_text, n_citations)."""
    if not text:
        return None, 0
    n = len(set(re.findall(r"PubMed:(\d+)", text)))
    clean = _PUBMED_CLUSTER.sub("", text)
    clean = re.sub(r"\bNote=", "", clean)          # UniProt structural marker, not prose
    clean = re.sub(r"\s{2,}", " ", clean).strip()
    return (clean or None), n


# ---------------------------------------------------------------------------
# TYPE-AHEAD for the search box. Two suggesters, one per mode.
# ---------------------------------------------------------------------------
class _SuggestUnavailable(Exception):
    """The index could not be read — distinct from "nothing matched", which is an empty list."""


def gene_suggest(q, taxid=9606, limit=8):
    """Ranked gene suggestions for a typed prefix.

    Reads gene_search, built by script/build_gene_search.py — see that file for why the ranking
    needed both a screen-hit count and a paper count rather than either alone (short version:
    hits alone put TP53RK above TP53, papers alone put PON1 above POLR2A).

    Two rules the ORDER BY encodes, both learned by getting them wrong first:

      canonical symbols BEFORE aliases. Ranked purely by score, "FANC" answered BRCA1, BRCA2,
      RAD51 — every one a legitimate alias hit (FANCS is BRCA1, FANCD1 is BRCA2) and every one
      wrong, because a person typing FANC wants the FANC genes. Aliases rescue a retired name;
      they are not a queue-jump for a famous gene.

      an exact match wins outright only if it is a CANONICAL symbol. Otherwise typing "PO" put
      PRB4 first, because some gene carries "PO" as a literal alias.

    De-duplicates by symbol: one gene with three matching aliases was filling three of eight slots
    with itself. Over-fetches to leave room for that.
    """
    q = (q or "").strip()
    if not q:
        return []
    term = q.upper()
    limit = max(1, min(int(limit), 25))
    try:
        rows = kb_fetchall(
            "SELECT symbol, term, is_alias, n_hits, name FROM gene_search "
            "WHERE taxid = ? AND term LIKE ? "
            "ORDER BY (term = ? AND is_alias = 0) DESC, is_alias, rank DESC, LENGTH(term), term "
            "LIMIT ?", (taxid, term + "%", term, limit * 5))
    except Exception as e:
        # NOT the same as "nothing matched" — see the route, which flags it. Returning [] here on
        # its own told a user that PO matches no genes while POLR2A sat in the table.
        print(f"  [suggest] gene_search unavailable: {e}")
        raise _SuggestUnavailable() from e
    out, seen = [], set()
    for r in rows:
        sym = r["symbol"]
        if sym in seen:
            continue
        seen.add(sym)
        out.append({"symbol": sym, "name": r["name"] or "",
                    "matched": r["term"] if r["is_alias"] else None,
                    "n_hits": r["n_hits"]})
        if len(out) >= limit:
            break
    return out


def screen_suggest(q, taxid=9606, limit=8):
    """Ranked screen suggestions. kb_screen is 2,157 rows, so this needs no precomputed table —
    a scan across the few fields a person would actually type is already sub-10ms.

    Matches what someone remembers a screen BY: the cell line, the condition, the phenotype, the
    first author, or the BioGRID id itself. Ranked by hit count as a stand-in for "a screen with
    something in it", since a screen with three hits is rarely the one being looked for.

    TWO THINGS THE RAW COLUMNS GET WRONG, both fixed here rather than in the data:

      BioGRID punctuates its cell lines — K-562, HL-60, A-375, HCT 116 — and nobody types them
      that way. "K562" matched zero of 1,952 human screens. Both sides are stripped of hyphens and
      spaces before comparing, which is doable in plain SQL and so works on sqlite and Postgres
      alike.

      number_of_hits is stored as TEXT, so ORDER BY put '5' above '1345'. Cast it.
    """
    q = (q or "").strip()
    if not q:
        return []
    like = f"%{q.lower()}%"
    squashed = f"%{''.join(c for c in q.lower() if c.isalnum())}%"
    limit = max(1, min(int(limit), 25))
    sq = "REPLACE(REPLACE(LOWER({}), '-', ''), ' ', '')"
    try:
        rows = kb_fetchall(
            "SELECT screen_id, cell_line, condition_name, phenotype, author, pmid, "
            "       screen_type, number_of_hits "
            "FROM kb_screen WHERE taxid = ? AND ("
            f"     {sq.format('cell_line')} LIKE ? OR LOWER(condition_name) LIKE ? "
            "  OR LOWER(phenotype) LIKE ? OR LOWER(author) LIKE ? "
            "  OR CAST(screen_id AS TEXT) LIKE ?) "
            "ORDER BY CAST(number_of_hits AS INTEGER) DESC LIMIT ?",
            (taxid, squashed, like, like, like, f"{q}%", limit))
    except Exception as e:
        print(f"  [suggest] screen search unavailable: {e}")
        raise _SuggestUnavailable() from e
    return [{"screen_id": str(r["screen_id"]),
             "cell_line": r["cell_line"] or "", "condition": r["condition_name"] or "",
             "phenotype": r["phenotype"] or "", "author": r["author"] or "",
             "pmid": r["pmid"], "n_hits": r["number_of_hits"]} for r in rows]


def _kb_resolve(gene, taxid):
    """symbol / alias / retired-id / GeneID  ->  (gene_id, symbol, taxid)."""
    if gene.isdigit():
        r = kb_fetchall("SELECT gene_id, symbol, taxid FROM kb_gene WHERE gene_id=?", (int(gene),))
        return r[0] if r else None
    # exact match first, then case-insensitive. LOWER() works on BOTH sqlite and Postgres —
    # the old `COLLATE NOCASE` is sqlite-only and hard-failed (HTTP 500) on a cloud deploy.
    for ci in (False, True):
        col, val = ("LOWER(a.alias)", gene.lower()) if ci else ("a.alias", gene)
        r = kb_fetchall(
            f"""SELECT g.gene_id, g.symbol, g.taxid FROM kb_gene_alias a
                JOIN kb_gene g ON g.gene_id = a.gene_id
                WHERE {col} = ? AND a.taxid = ?
                ORDER BY (a.alias_type='symbol') DESC LIMIT 1""", (val, taxid))
        if r:
            return r[0]
    return None


def gene_wiki(gene, taxid=9606):
    """Everything the KB knows about one gene, assembled from all 6 sources.
    Pure retrieval — no LLM, no interpretation, no directionality."""
    r = _kb_resolve(gene, taxid)
    if not r:
        return None
    gid, taxid = r["gene_id"], r["taxid"]

    g = kb_fetchall(
        """SELECT symbol, description, full_name, type_of_gene, chromosome, map_location,
                  ncbi_summary, uniprot_acc, uniprot_function, uniprot_location, uniprot_disease,
                  ensembl_gene_id, omim_id
           FROM kb_gene WHERE gene_id=?""", (gid,))[0]
    aliases = [a["alias"] for a in kb_fetchall(
        "SELECT DISTINCT alias FROM kb_gene_alias WHERE gene_id=? AND alias_type='synonym' LIMIT 14", (gid,))]
    orthologs = [{"species": "Homo sapiens" if o["ortholog_taxid"] == 9606 else "Mus musculus",
                  "symbol": o["ortholog_symbol"], "gene_id": o["ortholog_gene_id"],
                  "taxid": o["ortholog_taxid"]}
                 for o in kb_fetchall(
                     "SELECT ortholog_taxid, ortholog_gene_id, ortholog_symbol "
                     "FROM kb_gene_ortholog WHERE gene_id=? ORDER BY ortholog_taxid", (gid,))]
    func, n_cite = _clean_uniprot(g["uniprot_function"])
    loc, _ = _clean_uniprot(g["uniprot_location"])
    dis, _ = _clean_uniprot(g["uniprot_disease"])

    go = {}
    for ns in ("molecular_function", "biological_process", "cellular_component"):
        go[ns] = [x["name"] for x in kb_fetchall(
            f"""SELECT DISTINCT t.name FROM kb_gene_go gg JOIN kb_go_term t ON t.go_id=gg.go_id
               WHERE gg.gene_id=? AND t.namespace=? AND t.is_obsolete=0
               {_GO_POSITIVE} LIMIT 8""", (gid, ns))]

    part_rows = kb_fetchall(
        """SELECT g2.gene_id gid, g2.symbol sym, e.combined_score sc FROM kb_string_edge e
           JOIN kb_gene g2 ON g2.gene_id = CASE WHEN e.gene_id_a=? THEN e.gene_id_b ELSE e.gene_id_a END
           WHERE e.gene_id_a=? OR e.gene_id_b=? ORDER BY e.combined_score DESC LIMIT 12""",
        (gid, gid, gid))
    partners = [{"partner": r["sym"], "score": r["sc"]} for r in part_rows]
    # full sub-network: edges among {this gene} ∪ {its partners} — a real gene-gene graph
    node_ids = [gid] + [r["gid"] for r in part_rows]
    nidx = {n: i for i, n in enumerate(node_ids)}
    net_edges = []
    if len(node_ids) > 1:
        ph = ",".join("?" * len(node_ids))
        for e in kb_fetchall(
            f"SELECT gene_id_a a, gene_id_b b, combined_score s FROM kb_string_edge "
            f"WHERE gene_id_a IN ({ph}) AND gene_id_b IN ({ph})", node_ids + node_ids):
            if e["a"] in nidx and e["b"] in nidx:
                net_edges.append({"s": nidx[e["a"]], "t": nidx[e["b"]], "score": e["s"]})
    string_network = {"nodes": [g["symbol"]] + [r["sym"] for r in part_rows], "edges": net_edges}

    dep = None
    dr = kb_fetchall(
        """SELECT d.essential_class, d.mean_score, d.n_dependent, d.n_lines, d.min_score,
                  m.cell_line_name, m.lineage
           FROM kb_gene_dependency d LEFT JOIN kb_model m ON m.model_id = d.most_dependent_model
           WHERE d.gene_id=?""", (gid,))
    if dr:
        d = dr[0]
        dep = {"essential_class": d["essential_class"], "mean_score": d["mean_score"],
               "n_dependent": d["n_dependent"], "n_lines": d["n_lines"], "min_score": d["min_score"],
               "most_dependent_cell": d["cell_line_name"], "lineage": d["lineage"]}

    n_scr = kb_fetchall("SELECT COUNT(*) n FROM kb_screen_hit WHERE gene_id=?", (gid,))[0]["n"]
    by_phen = []
    # GROUP_CONCAT is sqlite-only; Postgres spells it STRING_AGG (explicit separator).
    _agg = ("STRING_AGG(DISTINCT s.condition_name, ',')" if _kb_on_pg()
            else "GROUP_CONCAT(DISTINCT s.condition_name)")
    for row in kb_fetchall(
        f"""SELECT s.phenotype, COUNT(*) c, {_agg} conds
           FROM kb_screen_hit h JOIN kb_screen s ON s.screen_id=h.screen_id
           WHERE h.gene_id=? GROUP BY s.phenotype ORDER BY c DESC""", (gid,)):
        conds = [x for x in (row["conds"] or "").split(",") if x and x != "None"]
        by_phen.append({"phenotype": row["phenotype"] or "unspecified",
                        "count": row["c"], "conditions": conds})

    n_pmid = kb_fetchall("SELECT COUNT(*) n FROM kb_gene_pubmed WHERE gene_id=?", (gid,))[0]["n"]

    pathways = [{"name": p["name"], "stable_id": p["stable_id"], "url": p["url"]}
                for p in kb_fetchall(
                    "SELECT name, stable_id, url FROM kb_gene_pathway WHERE gene_id=? ORDER BY name", (gid,))]

    return {
        "found": True,
        "identity": {
            "symbol": g["symbol"], "gene_id": gid, "taxid": taxid,
            "organism": "Homo sapiens" if taxid == 9606 else "Mus musculus",
            "description": g["description"], "full_name": g["full_name"],
            "type_of_gene": g["type_of_gene"], "chromosome": g["chromosome"],
            "map_location": g["map_location"], "aliases": aliases,
            "uniprot_acc": g["uniprot_acc"], "ensembl_gene_id": g["ensembl_gene_id"],
            "omim_id": g["omim_id"], "genecards_symbol": g["symbol"] if taxid == 9606 else None,
            "orthologs": orthologs,
        },
        "ncbi_summary": g["ncbi_summary"],
        "uniprot": {"acc": g["uniprot_acc"], "function": func, "n_citations": n_cite,
                    "location": loc, "disease": dis},
        "go": go,
        "pathways": pathways,
        "string": partners,
        "string_network": string_network,
        "depmap": dep,
        "screens": {"n_total": n_scr, "by_phenotype": by_phen},
        "literature": {"n_pmid": n_pmid},
    }


# --- CRISPR-screen analysis: the ONLY place the LLM is used. It reads ONLY the
# BioGRID screen hits for one gene (nothing else) and describes the pattern —
# which phenotype contexts the gene recurs in. Everything else on the page is
# deterministic. No directionality is ever asserted. ---
SCREEN_SYS = (
    "You are a functional-genomics analyst interpreting one gene's CRISPR-screen footprint, PHENOTYPE BY "
    "PHENOTYPE. For each phenotype you are given the specific perturbations/conditions (drugs, viruses, "
    "treatments) and cell contexts of the screens in which knockout of this gene was an author-called hit.\n"
    "For EACH phenotype, infer — in ONE tight, specific sentence (two only if truly needed) — what the gene's "
    "recurrence in those SPECIFIC screens suggests about its role IN THAT context, using your knowledge of what "
    "the named conditions are (a drug's target/class, a treatment's pathway, a stress type). Be mechanistic and "
    "concrete: name the shared drug class / pathway / stress you infer (e.g. 'these are topoisomerase poisons "
    "and PARP/ATR inhibitors → recurs in DNA-damage-response screens'). Do NOT just restate the screen count.\n"
    "Then give ONE overall takeaway sentence.\n"
    "Return ONLY a JSON object of this exact shape:\n"
    '{"by_phenotype":[{"phenotype":"<copy the phenotype label EXACTLY as given>","insight":"<1-2 sentences>"}],'
    '"overall":"<one sentence>"}\n'
    "Cover every phenotype given, in the same order. For a phenotype with no specific perturbation (plain "
    "fitness/proliferation screens) infer from that fact (e.g. a core-essential requirement). If a condition is "
    "unfamiliar, don't guess its mechanism.\n"
    "Boundaries: the screen hits are OUR ground-truth data — invent no screens. NEVER assert the DIRECTION of a "
    "screen (no 'sensitizes' / 'protects' / 'required for' / sign of an effect); say the gene 'recurs in' or is "
    "'repeatedly implicated in' the context."
)


def _screen_prompt(w):
    from collections import defaultdict, Counter
    idn, sc = w["identity"], w["screens"]
    per = defaultdict(lambda: {"conds": Counter(), "cells": Counter()})
    for r in kb_fetchall(
        "SELECT s.phenotype ph, s.condition_name cond, s.cell_type ct "
        "FROM kb_screen_hit h JOIN kb_screen s ON s.screen_id = h.screen_id WHERE h.gene_id=?",
        (idn["gene_id"],)):
        ph = r["ph"] or "unspecified"
        c = (r["cond"] or "").strip()
        if c and c != "-":
            per[ph]["conds"][c] += 1
        ct = (r["ct"] or "").strip()
        if ct and ct != "-":
            per[ph]["cells"][ct] += 1
    blocks = []
    for p in sc["by_phenotype"]:                       # display order (by screen count desc)
        d = per.get(p["phenotype"], {"conds": Counter(), "cells": Counter()})
        conds = "; ".join(f"{c}(×{n})" if n > 1 else c for c, n in d["conds"].most_common(20)) \
            or "no specific perturbation (plain fitness / proliferation screens)"
        cells = ", ".join(c for c, _ in d["cells"].most_common(6)) or "various"
        blocks.append(f"### {p['phenotype']} — {p['count']} screen(s)\n"
                      f"conditions: {conds}\ncell contexts: {cells}")
    return (f"GENE: {idn['symbol']} ({idn['organism']}) — hit in {sc['n_total']} pooled CRISPR screens.\n\n"
            + "\n\n".join(blocks)
            + "\n\nProduce the per-phenotype interpretation JSON now.")


_SYNTH_CACHE = {}


def screen_analysis(gene, taxid=9606):
    """Per-phenotype LLM interpretation of ONLY the gene's BioGRID CRISPR-screen hits
    (the sole AI text on the page). Returns a structured, phenotype-by-phenotype read."""
    from llm_client import WashULLMClient
    w = gene_wiki(gene, taxid)
    if not w:
        return {"found": False}
    sym = w["identity"]["symbol"]
    if not w["screens"]["n_total"]:
        return {"found": True, "symbol": sym, "n_screens": 0, "by_phenotype": [], "overall": ""}
    key = w["identity"]["gene_id"]
    if key in _SYNTH_CACHE:
        return _SYNTH_CACHE[key]
    client = WashULLMClient(model=INTERPRET_MODEL)
    data = client.chat_json(
        [{"role": "system", "content": SCREEN_SYS},
         {"role": "user", "content": _screen_prompt(w)}],
        # 4000, not the 1200 this prompt used against gpt-4.1: Claude writes longer
        # per-phenotype insights, and a JSON reply cut off at the limit is unparseable.
        max_tokens=4000)   # no temperature: claude-opus-4-7 rejects it (see _gen_kwargs)
    items = [{"phenotype": x.get("phenotype"), "insight": (x.get("insight") or "").strip()}
             for x in (data.get("by_phenotype") or []) if x.get("phenotype") and x.get("insight")]
    out = {"found": True, "symbol": sym, "model": client.model,
           "n_screens": w["screens"]["n_total"],
           "by_phenotype": items, "overall": (data.get("overall") or "").strip()}
    if items:
        _SYNTH_CACHE[key] = out
    return out


# --- 3D structure: resolve AlphaFold (version-proof, via API) + experimental PDB ---
# The structure FILE is a verbatim third-party artifact fetched at view time (like a
# web font), not AI content. We only resolve+cache the URLs here; the browser loads
# the .pdb into the 3Dmol viewer. AlphaFold model versions change (v4 already 404s),
# so never hardcode a filename — read pdbUrl from the prediction API.
import urllib.request as _urlreq  # noqa: E402

_STRUCT_CACHE = {}


def _kb_struct_table():
    kb_fetchall("""CREATE TABLE IF NOT EXISTS kb_gene_structure (
        uniprot_acc TEXT PRIMARY KEY, alphafold_pdb_url TEXT, alphafold_version TEXT,
        best_pdb_id TEXT, experimental_json TEXT)""")


def _http_json(url, timeout=12):
    req = _urlreq.Request(url, headers={"User-Agent": "RETICLE-KB/1.0 (research)"})
    with _urlreq.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def resolve_structures(uniprot_acc):
    """{alphafold_pdb_url, alphafold_version, experimental:[{pdb_id,method,resolution,chain,url}]}"""
    if uniprot_acc in _STRUCT_CACHE:
        return _STRUCT_CACHE[uniprot_acc]
    out = {"uniprot_acc": uniprot_acc, "alphafold_pdb_url": None,
           "alphafold_version": None, "experimental": []}
    # AlphaFold predicted model — pick the canonical AF-{ACC}-F1 entry, read its pdbUrl
    try:
        preds = _http_json(f"https://alphafold.ebi.ac.uk/api/prediction/{uniprot_acc}")
        af = next((p for p in preds if p.get("entryId", "").startswith(f"AF-{uniprot_acc}-F1")), preds[0])
        out["alphafold_pdb_url"] = af.get("pdbUrl")
        out["alphafold_version"] = str(af.get("latestVersion") or "")
    except Exception:
        pass
    # Experimental structures — PDBe best_structures (ranked by resolution+coverage)
    try:
        best = _http_json(f"https://www.ebi.ac.uk/pdbe/api/mappings/best_structures/{uniprot_acc}")
        for b in best.get(uniprot_acc, [])[:6]:
            out["experimental"].append({
                "pdb_id": b["pdb_id"], "method": b.get("experimental_method"),
                "resolution": b.get("resolution"), "chain": b.get("chain_id"),
                "url": f"https://files.rcsb.org/download/{b['pdb_id']}.pdb"})
    except Exception:
        pass
    _STRUCT_CACHE[uniprot_acc] = out
    return out


def gene_structure(gene, taxid=9606):
    r = _kb_resolve(gene, taxid)
    if not r:
        return {"available": False}
    row = kb_fetchall("SELECT uniprot_acc FROM kb_gene WHERE gene_id=?", (r["gene_id"],))
    acc = row[0]["uniprot_acc"] if row else None
    if not acc:
        return {"available": False, "reason": "no UniProt accession for this gene"}
    s = resolve_structures(acc)
    s["available"] = bool(s.get("alphafold_pdb_url") or s.get("experimental"))
    return s


# ---------------------------------------------------------------------------
# Function PREDICTION — guilt-by-association from two orthogonal, non-circular
# layers (clean-STRING = experimental+coexpression+genomic channels only;
# co-essentiality = precomputed DepMap dependency correlation). Neighbours vote
# on GO Biological-Process terms; we keep only terms the gene does NOT already
# have (= novel predictions), each with its evidence + confidence. NO LLM here —
# a prediction is a hypothesis, so we expose the raw evidence, not AI prose.
# Method validated by script/predict_backtest.py (documentation/prediction_backtest.html).
# ---------------------------------------------------------------------------
_BP_SIZE = None
_BP_NAME = None


def _bp_meta():
    global _BP_SIZE, _BP_NAME
    if _BP_SIZE is None:
        _BP_SIZE = {r["go_id"]: r["c"] for r in kb_fetchall(
            "SELECT gg.go_id, COUNT(*) c FROM kb_gene_go gg JOIN kb_go_term t ON t.go_id=gg.go_id "
            "WHERE t.namespace='biological_process' AND t.is_obsolete=0 "
            f"{_GO_POSITIVE} GROUP BY gg.go_id")}
        _BP_NAME = {r["go_id"]: r["name"] for r in kb_fetchall(
            "SELECT go_id, name FROM kb_go_term WHERE namespace='biological_process'")}
    return _BP_SIZE, _BP_NAME


def _string_clean_neighbours(gid, k=30):
    """STRING partners from annotation-INDEPENDENT channels only (no db/textmining)."""
    out = {}
    for r in kb_fetchall(
        "SELECT CASE WHEN gene_id_a=? THEN gene_id_b ELSE gene_id_a END nb, "
        "neighborhood, fusion, cooccurence, coexpression, experimental "
        "FROM kb_string_edge WHERE gene_id_a=? OR gene_id_b=?", (gid, gid, gid)):
        p = 1.0
        for c in (r["neighborhood"], r["fusion"], r["cooccurence"], r["coexpression"], r["experimental"]):
            p *= 1.0 - (c or 0) / 1000.0
        clean = 1.0 - p
        if clean > 0:
            out[r["nb"]] = clean
    return dict(sorted(out.items(), key=lambda x: -x[1])[:k])


def _coess_neighbours(gid, k=30):
    try:
        return {r["neighbor_gene_id"]: r["corr"] for r in kb_fetchall(
            "SELECT neighbor_gene_id, corr FROM kb_coessential WHERE gene_id=? "
            "ORDER BY corr DESC LIMIT ?", (gid, k))}
    except Exception:
        return {}                                    # table not built yet → STRING-only


def predict_functions(gene, taxid=9606, top=8):
    from collections import defaultdict
    r = _kb_resolve(gene, taxid)
    if not r:
        return {"found": False}
    gid, sym = r["gene_id"], r["symbol"]
    size, name = _bp_meta()

    def norm(d):                                     # scale each layer to its own max → comparable
        m = max(d.values()) if d else 1.0
        return {k: v / m for k, v in d.items()}
    strn, coess = norm(_string_clean_neighbours(gid)), norm(_coess_neighbours(gid))
    neigh = {}
    for nb, w in strn.items():
        neigh.setdefault(nb, {"w": 0.0, "layers": set()}); neigh[nb]["w"] += w; neigh[nb]["layers"].add("string")
    for nb, w in coess.items():
        neigh.setdefault(nb, {"w": 0.0, "layers": set()}); neigh[nb]["w"] += w; neigh[nb]["layers"].add("coess")
    if not neigh:
        return {"found": True, "symbol": sym, "n_neighbours": 0, "predictions": []}

    # Terms we will NOT predict. Deliberately NOT filtered by _GO_POSITIVE: a "NOT involved_in"
    # row is curated evidence AGAINST the gene doing this, so it should suppress the prediction
    # just as a positive annotation does. (Every other GO read in this file excludes NOT rows.)
    own = {row["go_id"] for row in kb_fetchall(
        "SELECT gg.go_id FROM kb_gene_go gg JOIN kb_go_term t ON t.go_id=gg.go_id "
        "WHERE gg.gene_id=? AND t.namespace='biological_process'", (gid,))}

    nb_ids = list(neigh.keys())
    ph = ",".join("?" * len(nb_ids))
    supporters = defaultdict(set)                     # set → one vote per gene (kb_gene_go repeats per evidence code)
    for row in kb_fetchall(
        f"SELECT gg.gene_id gid, gg.go_id term FROM kb_gene_go gg JOIN kb_go_term t ON t.go_id=gg.go_id "
        f"WHERE gg.gene_id IN ({ph}) AND t.namespace='biological_process' AND t.is_obsolete=0 "
        f"{_GO_POSITIVE}", nb_ids):
        supporters[row["term"]].add(row["gid"])

    cands = []
    for term, supp in supporters.items():
        if term in own or not (5 <= size.get(term, 0) <= 300) or len(supp) < 2:
            continue
        score = sum(neigh[nb]["w"] for nb in supp)
        layers = set().union(*[neigh[nb]["layers"] for nb in supp])
        cands.append((score, term, supp, layers))
    cands.sort(key=lambda x: -x[0])
    cands = cands[:top]

    all_supp = {nb for _, _, supp, _ in cands for nb in supp}
    sym_map = {}
    if all_supp:
        ph2 = ",".join("?" * len(all_supp))
        sym_map = {row["gene_id"]: row["symbol"] for row in kb_fetchall(
            f"SELECT gene_id, symbol FROM kb_gene WHERE gene_id IN ({ph2})", list(all_supp))}

    LAYER_DESC = {("coess", "string"): "co-essential CRISPR dependency and STRING functional interactions",
                  ("string",): "STRING functional interactions",
                  ("coess",): "co-essential CRISPR dependency"}
    preds = []
    for score, term, supp, layers in cands:
        supp_sorted = sorted(supp, key=lambda nb: -neigh[nb]["w"])
        syms = [sym_map.get(nb, str(nb)) for nb in supp_sorted[:5]]
        nl = len(layers)
        conf = ("high" if nl >= 2 and len(supp) >= 3
                else "moderate" if len(supp) >= 4 or nl >= 2 else "tentative")
        desc = LAYER_DESC[tuple(sorted(layers))]
        more = f" and {len(supp) - len(syms)} more" if len(supp) > len(syms) else ""
        preds.append({
            "function": name.get(term, term), "go_id": term, "confidence": conf,
            "n_support": len(supp), "layers": sorted(layers), "supporters": syms,
            "explanation": f"Shares {desc} with {', '.join(syms)}{more} — genes that act in this process — "
                           f"while {sym} itself carries no such annotation.",
        })
    return {"found": True, "symbol": sym, "n_neighbours": len(neigh),
            "n_known_bp": len(own), "predictions": preds}


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
        # Unified Gene tab is the landing page: gene-level phenotype query + gene wiki merged.
        if u.path in ("/", "/index.html", "/gene", "/gene.html", "/wiki"):
            return self._send(200, GENE_HTML.read_bytes(), "text/html; charset=utf-8")
        # Screen tab: the screen-wide similarity query, split out of the old Explore page.
        if u.path in ("/screen", "/screens", "/screen.html"):
            return self._send(200, SCREEN_HTML.read_bytes(), "text/html; charset=utf-8")
        if u.path in ("/network", "/network.html", "/net"):
            return self._send(200, NETWORK_HTML.read_bytes(), "text/html; charset=utf-8")
        # Type-ahead. Fires on every keystroke, so it never raises and never 404s — an empty list
        # is the correct answer to "nothing matches yet", and a failing suggester must not be able
        # to make the box itself feel broken.
        if u.path in ("/api/gene_suggest", "/api/screen_suggest"):
            q = parse_qs(u.query)
            term = (q.get("q", [""])[0]).strip()
            try:
                taxid = int(q.get("taxid", ["9606"])[0] or 9606)
            except ValueError:
                taxid = 9606
            if q.get("organism", [""])[0] == "mouse":
                taxid = 10090
            try:
                limit = int(q.get("limit", ["8"])[0] or 8)
            except ValueError:
                limit = 8
            fn = gene_suggest if u.path.endswith("gene_suggest") else screen_suggest
            ok = True
            try:
                items = fn(term, taxid, limit)
            except Exception as e:
                # Still 200 — a 5xx under a cursor makes the page feel broken over a transient —
                # but `ok` separates "nothing matched" from "could not read the index".
                print(f"  [suggest] {u.path} failed: {e}")
                items, ok = [], False
            return self._send(200, {"query": term, "taxid": taxid, "ok": ok, "items": items})

        if u.path == "/api/gene_wiki":
            q = parse_qs(u.query)
            gene = (q.get("gene", [""])[0]).strip()
            try:
                taxid = int(q.get("taxid", ["9606"])[0] or 9606)
            except ValueError:
                taxid = 9606
            if not gene:
                return self._send(400, {"error": "Enter a gene symbol."})
            try:
                p = gene_wiki(gene, taxid)
            except Exception as e:
                return self._send(500, {"error": f"Lookup failed: {e}"})
            if p is None:
                return self._send(404, {"error": f"No gene matching “{gene}” in {('human' if taxid==9606 else 'mouse')}."})
            return self._send(200, p)
        if u.path == "/api/gene_structure":
            q = parse_qs(u.query)
            gene = (q.get("gene", [""])[0]).strip()
            try:
                taxid = int(q.get("taxid", ["9606"])[0] or 9606)
            except ValueError:
                taxid = 9606
            if not gene:
                return self._send(400, {"error": "Missing gene."})
            try:
                return self._send(200, gene_structure(gene, taxid))
            except Exception as e:
                return self._send(502, {"error": f"Structure lookup failed: {e}"})
        if u.path == "/api/gene_screen_distribution":
            q = parse_qs(u.query)
            gene = (q.get("gene", [""])[0]).strip()
            try:
                taxid = int(q.get("taxid", ["9606"])[0] or 9606)
            except ValueError:
                taxid = 9606
            screen = (q.get("screen", [""])[0]).strip() or None
            score = (q.get("score", ["percentile"])[0]).strip()
            if score not in _DIST_COL:
                score = "percentile"
            if not gene:
                return self._send(400, {"error": "Missing gene."})
            try:
                p = gene_screen_distribution(gene, taxid, screen=screen, score=score)
            except Exception as e:
                return self._send(500, {"error": f"Distribution failed: {e}"})
            if p is None:
                return self._send(404, {"error": f"No FULL-screen distribution for “{gene}”."})
            return self._send(200, p)
        if u.path == "/api/gene_predictions":
            q = parse_qs(u.query)
            gene = (q.get("gene", [""])[0]).strip()
            try:
                taxid = int(q.get("taxid", ["9606"])[0] or 9606)
            except ValueError:
                taxid = 9606
            if not gene:
                return self._send(400, {"error": "Missing gene."})
            try:
                return self._send(200, predict_functions(gene, taxid))
            except Exception as e:
                return self._send(500, {"error": f"Prediction failed: {e}"})
        if u.path == "/api/screen_analysis":
            q = parse_qs(u.query)
            gene = (q.get("gene", [""])[0]).strip()
            try:
                taxid = int(q.get("taxid", ["9606"])[0] or 9606)
            except ValueError:
                taxid = 9606
            if not gene:
                return self._send(400, {"error": "Missing gene."})
            try:
                return self._send(200, screen_analysis(gene, taxid))
            except Exception as e:
                msg = str(e)
                hint = ("  Connect the WashU network (LLM gateway is WashU-only) and retry."
                        if "403" in msg or "Forbidden" in msg else "")
                return self._send(502, {"error": f"Screen analysis unavailable: {msg}{hint}"})
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
        if u.path in ("/api/coessential", "/api/coessential_aaron"):
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
        if u.path in ("/api/screen_similar", "/api/screen_similar_aaron"):
            q = parse_qs(u.query)
            sid = (q.get("screen", [""])[0]).strip()
            if not sid:
                return self._send(400, {"error": "Missing screen id."})
            try:
                limit = min(200, max(1, int(q.get("limit", ["50"])[0])))
                offset = max(0, int(q.get("offset", ["0"])[0]))
                excl = q.get("exclude_same_study", ["0"])[0] not in ("0", "", "false")
                p = screen_similar(sid, limit=limit, offset=offset, exclude_same_study=excl)
            except Exception as e:
                return self._send(500, {"error": f"Screen similarity failed: {e}"})
            if p is None:
                return self._send(404, {"error": f"Screen {sid} not in the human · fitness · genome-wide pool."})
            return self._send(200, p)
        if u.path in ("/api/reporter_explain", "/api/reporter_explain_aaron"):
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
        if u.path == "/api/net_contexts":
            q = parse_qs(u.query)
            organism = "mouse" if q.get("organism", ["human"])[0] == "mouse" else "human"
            try:
                return self._send(200, {"contexts": net_contexts(organism=organism)})
            except Exception as e:
                return self._send(500, {"error": f"Context list failed: {e}"})
        if u.path == "/api/screen_net":
            q = parse_qs(u.query)
            gene = (q.get("gene", [""])[0]).strip()
            organism = "mouse" if q.get("organism", ["human"])[0] == "mouse" else "human"
            context = (q.get("context", [""])[0]).strip() or ("mouse" if organism == "mouse" else "all")
            reciprocal = q.get("reciprocal", ["1"])[0] != "0"
            if not gene:
                return self._send(400, {"error": "Missing gene."})
            try:
                p = screen_net(gene, context, reciprocal_only=reciprocal, organism=organism)
            except Exception as e:
                return self._send(500, {"error": f"Network failed: {e}"})
            if p is None:
                return self._send(404, {"error": f"“{gene}” has no {'reciprocal ' if reciprocal else ''}"
                                                 f"edges in this context — it may not be hit-active here."})
            return self._send(200, p)
        if u.path == "/api/net_predict":
            q = parse_qs(u.query)
            gene = (q.get("gene", [""])[0]).strip()
            organism = "mouse" if q.get("organism", ["human"])[0] == "mouse" else "human"
            context = (q.get("context", [""])[0]).strip() or ("mouse" if organism == "mouse" else "all")
            # Same default and parsing as /api/screen_net, but it no longer SELECTS the dossier —
            # that is always the union now (see _net_predict_partners). All it does is let the
            # response report how many partners the model read that the caller's graph filter was
            # hiding, so the difference is visible instead of either silent or obeyed.
            reciprocal = q.get("reciprocal", ["1"])[0] != "0"
            if not gene:
                return self._send(400, {"error": "Missing gene."})
            try:
                p = net_predict_functions(gene, context, organism=organism,
                                          reciprocal_only=reciprocal)
            except Exception as e:
                msg = str(e)
                hint = ("  Connect the WashU network (LLM gateway is WashU-only) and retry."
                        if "403" in msg or "Forbidden" in msg else
                        "  The WashU LLM gateway has reached its spend limit — ask the team to top it up."
                        if "402" in msg or "spend amount" in msg else "")
                return self._send(502, {"error": f"Function prediction unavailable: {msg}{hint}"})
            if p is None:
                return self._send(404, {"error": f"“{gene}” has no co-essential partners in this "
                                                 f"context to reason from."})
            return self._send(200, p)
        self._send(404, {"error": "Not found"})

    def do_POST(self):
        u = urlparse(self.path)
        if u.path in ("/api/interpret", "/api/interpret_aaron"):
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
    if USE_PG:                                   # open the pool now so the first user request is warm
        try:
            db_fetchall("SELECT 1")
            print("  RDS pool warmed (4 connections)\n")
        except Exception as e:
            print(f"  (RDS warm-up skipped: {e})\n")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
