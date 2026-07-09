"""
External knowledge sources (NCBI / PubMed / GO / STRING) — ported from
prototype/script/external_sources.py.

One place the API talks to public biology APIs, with caching + polite rate
limiting so the Explorer can enrich any gene on demand (plus a darkness rating).

Faithful port of the prototype module. Two changes for the server context:
  - config comes from the process environment (os.getenv), not a hand-parsed
    .env file — the API already loads .env via python-dotenv.
  - the 30-day cache lives in the shared database (reticle.external_cache table)
    instead of a container-local SQLite file, which would be ephemeral on
    Fargate and unshared across tasks. Caching is best-effort: if the DB write
    fails the lookup still returns live data.

Everything fails soft (returns None/[]) and never raises into the web layer.
Transport is stdlib urllib — no third-party HTTP dependency.
"""

import json
import os
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from math import log10
from typing import Any

from services import db_service

CACHE_TTL = 30 * 86400  # 30 days

NCBI = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
MYGENE = "https://mygene.info/v3"
STRING = "https://string-db.org/api"
TAXID = {"Homo sapiens": 9606, "Mus musculus": 10090}

# darkness formula references (a gene at/above these is "fully studied" on that axis)
PUB_REF = 1000  # >= 1000 PubMed papers -> publication-darkness 0
GO_REF = 50  # >= 50 specific GO terms -> annotation-darkness 0
W_PUB, W_GO = 0.6, 0.4


# --------------------------------------------------------------------------
# config / cache / transport
# --------------------------------------------------------------------------

NCBI_KEY = os.getenv("NCBI_API_KEY", "")
_RATE = 0.11 if NCBI_KEY else 0.34  # seconds between NCBI calls (10/s vs 3/s)
_last_ncbi = [0.0]

_MISS = object()  # sentinel distinguishing "cache miss" from a cached null
_CACHE_READY = [False]


def _ensure_cache() -> None:
    """Create the shared cache table once per process (best-effort)."""
    if _CACHE_READY[0]:
        return
    try:
        db_service.db_execute(
            "CREATE TABLE IF NOT EXISTS external_cache "
            "(k TEXT PRIMARY KEY, v TEXT, ts DOUBLE PRECISION)"
        )
        _CACHE_READY[0] = True
    except Exception:
        pass


def _cache_get(key: str) -> Any:
    try:
        _ensure_cache()
        rows = db_service.db_fetchall("SELECT v, ts FROM external_cache WHERE k=?", (key,))
        if rows and (time.time() - float(rows[0]["ts"])) < CACHE_TTL:
            return json.loads(rows[0]["v"])
    except Exception:
        pass
    return _MISS


def _cache_put(key: str, val: Any) -> None:
    try:
        _ensure_cache()
        payload = json.dumps(val)
        if db_service.USE_PG:
            db_service.db_execute(
                "INSERT INTO external_cache (k, v, ts) VALUES (?, ?, ?) "
                "ON CONFLICT (k) DO UPDATE SET v = EXCLUDED.v, ts = EXCLUDED.ts",
                (key, payload, time.time()),
            )
        else:
            db_service.db_execute(
                "INSERT OR REPLACE INTO external_cache (k, v, ts) VALUES (?, ?, ?)",
                (key, payload, time.time()),
            )
    except Exception:
        pass


def _cached(key: str, fetch: Any) -> Any:
    hit = _cache_get(key)
    if hit is not _MISS:
        return hit
    try:
        val = fetch()
    except Exception:
        val = None
    if val is not None:
        _cache_put(key, val)
    return val


def _get(url: str, ncbi: bool = False) -> bytes:
    if ncbi:
        wait = _RATE - (time.time() - _last_ncbi[0])
        if wait > 0:
            time.sleep(wait)
        _last_ncbi[0] = time.time()
    req = urllib.request.Request(url, headers={"User-Agent": "RETICLE/1.0 (research)"})
    with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310 (fixed https hosts)
        return bytes(r.read())


def _ncbi_suffix() -> str:
    return f"&api_key={NCBI_KEY}" if NCBI_KEY else ""


# --------------------------------------------------------------------------
# sources
# --------------------------------------------------------------------------

def gene_annotation(symbol: str, taxid: int) -> Any:
    """MyGene.info → {entrez, name, summary, go_total, go_bp/mf/cc}."""
    species = "human" if taxid == 9606 else "mouse"
    key = f"mygene:{species}:{symbol}"

    def fetch() -> Any:
        url = (
            f"{MYGENE}/query?q=symbol:{urllib.parse.quote(symbol)}"
            f"&species={species}&fields=entrezgene,name,summary,go&size=1"
        )
        hits = json.loads(_get(url)).get("hits", [])
        if not hits:
            return None
        h = hits[0]
        go = h.get("go", {}) or {}

        def n(branch: str) -> int:
            b = go.get(branch, [])
            return len(b) if isinstance(b, list) else (1 if b else 0)

        go_bp, go_mf, go_cc = n("BP"), n("MF"), n("CC")
        return {
            "entrez": h.get("entrezgene"),
            "name": h.get("name", ""),
            "summary": h.get("summary", ""),
            "go_bp": go_bp,
            "go_mf": go_mf,
            "go_cc": go_cc,
            "go_total": go_bp + go_mf + go_cc,
        }

    return _cached(key, fetch)


def _orgn(taxid: int) -> str:
    # PubMed indexes by organism common name, NOT txid.
    return "human" if taxid == 9606 else "mouse"


def pubmed_count(symbol: str, taxid: int) -> Any:
    """NCBI esearch → number of PubMed papers for this gene."""
    key = f"pmcount:{taxid}:{symbol}"

    def fetch() -> Any:
        term = urllib.parse.quote(f"{symbol}[gene] AND {_orgn(taxid)}[orgn]")
        url = f"{NCBI}/esearch.fcgi?db=pubmed&term={term}&retmode=json{_ncbi_suffix()}"
        return int(json.loads(_get(url, ncbi=True))["esearchresult"]["count"])

    return _cached(key, fetch)


def pubmed_pmids(symbol: str, taxid: int, n: int = 6) -> Any:
    key = f"pmids:{taxid}:{symbol}:{n}"

    def fetch() -> Any:
        term = urllib.parse.quote(f"{symbol}[gene] AND {_orgn(taxid)}[orgn]")
        url = (
            f"{NCBI}/esearch.fcgi?db=pubmed&term={term}&retmax={n}"
            f"&sort=relevance&retmode=json{_ncbi_suffix()}"
        )
        return json.loads(_get(url, ncbi=True))["esearchresult"]["idlist"]

    return _cached(key, fetch) or []


def pubmed_abstracts(pmids: list) -> Any:
    """efetch → [{pmid, title, abstract}] for the given PMIDs (for RAG)."""
    if not pmids:
        return []
    key = "abs:" + ",".join(sorted(pmids))

    def fetch() -> Any:
        ids = ",".join(pmids)
        url = f"{NCBI}/efetch.fcgi?db=pubmed&id={ids}&retmode=xml{_ncbi_suffix()}"
        root = ET.fromstring(_get(url, ncbi=True))  # noqa: S314 (trusted NCBI source)
        out = []
        for art in root.findall(".//PubmedArticle"):
            pmid = art.findtext(".//PMID") or ""
            title_el = art.find(".//ArticleTitle")
            title = "".join(title_el.itertext()) if title_el is not None else ""
            abst = " ".join(
                "".join(a.itertext()) for a in art.findall(".//Abstract/AbstractText")
            )
            if abst:
                out.append({"pmid": pmid, "title": title.strip(), "abstract": abst.strip()})
        return out

    return _cached(key, fetch) or []


def string_partners(symbol: str, taxid: int, limit: int = 8) -> Any:
    """STRING → top functional partners [{partner, score}]."""
    key = f"string:{taxid}:{symbol}:{limit}"

    def fetch() -> Any:
        url = (
            f"{STRING}/json/interaction_partners?identifiers={urllib.parse.quote(symbol)}"
            f"&species={taxid}&limit={limit}"
        )
        data = json.loads(_get(url))
        return [
            {"partner": d["preferredName_B"], "score": round(float(d["score"]), 3)}
            for d in data
        ]

    return _cached(key, fetch) or []


# STRING scores each interaction per evidence CHANNEL (sub-score field -> label).
STRING_CHANNELS = {
    "escore": "experiments",
    "dscore": "databases",
    "tscore": "text-mining",
    "ascore": "co-expression",
    "nscore": "gene neighborhood",
    "fscore": "gene fusion",
    "pscore": "co-occurrence",
}


def string_network(symbol: str, taxid: int, add: int = 10) -> Any:
    """STRING subnetwork: the gene + `add` top interactors + ALL edges among them,
    each edge annotated with STRING's per-evidence-channel sub-scores.
    Returns {nodes: [name...], edges: [{a, b, score, channels:{label: subscore}}]}."""
    key = f"stringnet:{taxid}:{symbol}:{add}"

    def fetch() -> Any:
        url = (
            f"{STRING}/json/network?identifiers={urllib.parse.quote(symbol)}"
            f"&species={taxid}&add_nodes={add}"
        )
        data = json.loads(_get(url))
        edges = []
        for d in data:
            channels = {
                label: round(float(d[k]), 3)
                for k, label in STRING_CHANNELS.items()
                if k in d and float(d[k]) > 0
            }
            edges.append(
                {
                    "a": d["preferredName_A"],
                    "b": d["preferredName_B"],
                    "score": round(float(d["score"]), 3),
                    "channels": channels,
                }
            )
        nodes = sorted({n for e in edges for n in (e["a"], e["b"])})
        return {"nodes": nodes, "edges": edges}

    return _cached(key, fetch) or {"nodes": [], "edges": []}


# --------------------------------------------------------------------------
# darkness rating
# --------------------------------------------------------------------------

def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def darkness(symbol: str, taxid: int, ann: Any = None) -> Any:
    """0 (well-studied) … 10 (dark matter). Combines PubMed paper count and GO
    annotation density, both on a log scale (these are heavy-tailed)."""
    pubs = pubmed_count(symbol, taxid)
    if ann is None:
        ann = gene_annotation(symbol, taxid)
    go = (ann or {}).get("go_total", 0)
    if pubs is None:
        return None
    dark_pub = _clamp01(1 - log10(pubs + 1) / log10(PUB_REF))
    dark_go = _clamp01(1 - log10(go + 1) / log10(GO_REF))
    score = round(10 * (W_PUB * dark_pub + W_GO * dark_go), 1)
    return {
        "score": score,
        "pubmed_count": pubs,
        "go_total": go,
        "dark_pub": round(dark_pub, 2),
        "dark_go": round(dark_go, 2),
        "band": ("dark" if score >= 6.5 else "grey" if score >= 3.5 else "bright"),
    }


def enrich(symbol: str, taxid: int) -> dict:
    """Everything the gene page needs from external sources, in one bundle."""
    ann = gene_annotation(symbol, taxid)
    return {
        "symbol": symbol,
        "annotation": ann,
        "darkness": darkness(symbol, taxid, ann=ann),
        "string_partners": string_partners(symbol, taxid),
    }
