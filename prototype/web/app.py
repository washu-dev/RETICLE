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
    return block


def gene_payload(symbol: str):
    variants = resolve_symbol_variants(symbol)
    ph = ",".join("?" * len(variants))
    rows = db_fetchall(
        f"""SELECT h.SCREEN_ID, h.GENE_SYMBOL, h.PERCENTILE_SCORE AS pct,
                   h.IS_HIT AS is_hit,
                   m.CELL_LINE, m.SCREEN_TYPE, m.ANALYSIS, m.PHENOTYPE,
                   m.SCREEN_RATIONALE, m.ORGANISM_OFFICIAL AS org,
                   COALESCE(c.assay_domain, 'other') AS domain
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
    stress  = domain_block(buckets["stress"])  if buckets["stress"]  else None

    # reporter: no axis; keep the most extreme |percentile| hits for the read-out
    rep_rows = sorted(buckets["reporter"], key=lambda r: -abs(r["pct"]))
    reporter = {
        "n": len(buckets["reporter"]),
        "hits": [_pack(r) for r in rep_rows[:8]],
    } if buckets["reporter"] else {"n": 0, "hits": []}

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


def _signal_lines(p):
    def blk(name, b):
        if not b:
            return f"{name}: (no screens)"
        return (f"{name}: n={b['n']}, hits={b['n_hits']}, median={b['median']:+.3f}, "
                f"IQR=[{b['p25']:+.3f},{b['p75']:+.3f}], lean={b['lean']}")
    def ctx(items):
        return "; ".join(f"{i['cell_line']} ({i['screen_type'] or 'screen'}, {i['percentile']:+.2f})"
                         for i in items[:5])
    out = [blk("FITNESS", p["fitness"]), blk("STRESS", p["stress"])]
    if p["fitness"]:
        out.append(f"  fitness most-essential: {ctx(p['fitness']['most_essential'])}")
        out.append(f"  fitness most-advantageous: {ctx(p['fitness']['most_advantageous'])}")
    rep = p["reporter"]
    if rep["n"]:
        probes = "; ".join(f"{h['rationale'] or h['phenotype']} ({h['percentile']:+.2f})"
                           for h in rep["hits"][:6])
        out.append(f"REPORTER: n={rep['n']} marker screens — functional probes hit: {probes}")
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
