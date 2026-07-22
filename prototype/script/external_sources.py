"""
RETICLE — External knowledge sources (NCBI / PubMed / GO / STRING)
==================================================================
One place the app talks to public biology APIs, with on-disk caching + polite
rate limiting so the website can enrich any gene on demand (and a darkness
rating per the proposal's Phase 4).

Sources (what needs a key):
  - NCBI E-utilities  (PubMed publication count + abstracts for RAG)
        OPTIONAL key: set NCBI_API_KEY in .env  → 10 req/s (vs 3 keyless).
  - MyGene.info       (gene name/summary + GO terms = the GO half of darkness)
        no key.  (Entrez/NCBI-sourced, aggregated.)
  - STRING            (known functional partners)        no key.

Everything is cached in processed_data/external_cache.db so repeated lookups are
instant and we never hammer the APIs. All functions fail soft (return None/[]),
never raise into the web layer.

  python3 script/external_sources.py TP53        # smoke test (prints enrichment)
"""

import json
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from math import log10
from pathlib import Path

_ENV = Path(__file__).resolve().parent.parent / ".env"
CACHE_DB = Path(__file__).resolve().parent.parent / "processed_data" / "external_cache.db"
CACHE_TTL = 30 * 86400  # 30 days

NCBI = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
MYGENE = "https://mygene.info/v3"
STRING = "https://string-db.org/api"
TAXID = {"Homo sapiens": 9606, "Mus musculus": 10090}

# darkness formula references (a gene at/above these is "fully studied" on that axis)
PUB_REF = 1000    # >= 1000 PubMed papers -> publication-darkness 0
GO_REF = 50       # >= 50 specific GO terms -> annotation-darkness 0
W_PUB, W_GO = 0.6, 0.4


# --------------------------------------------------------------------------
# config / cache / transport
# --------------------------------------------------------------------------

def _load_env():
    if not _ENV.exists():
        return {}
    out = {}
    for line in _ENV.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out

_CFG = _load_env()
NCBI_KEY = _CFG.get("NCBI_API_KEY", "")
_RATE = 0.11 if NCBI_KEY else 0.34   # seconds between NCBI calls (10/s vs 3/s)
_last_ncbi = [0.0]


def _cache():
    CACHE_DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(CACHE_DB))
    con.execute("CREATE TABLE IF NOT EXISTS cache (k TEXT PRIMARY KEY, v TEXT, ts REAL)")
    return con


def _cached(key, fetch):
    con = _cache()
    row = con.execute("SELECT v, ts FROM cache WHERE k=?", (key,)).fetchone()
    if row and (time.time() - row[1]) < CACHE_TTL:
        con.close()
        return json.loads(row[0])
    try:
        val = fetch()
    except Exception:
        val = None
    if val is not None:
        con.execute("INSERT OR REPLACE INTO cache VALUES (?,?,?)",
                    (key, json.dumps(val), time.time()))
        con.commit()
    con.close()
    return val


def _get(url, ncbi=False):
    if ncbi:
        wait = _RATE - (time.time() - _last_ncbi[0])
        if wait > 0:
            time.sleep(wait)
        _last_ncbi[0] = time.time()
    req = urllib.request.Request(url, headers={"User-Agent": "RETICLE/1.0 (research)"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def _ncbi_suffix():
    return f"&api_key={NCBI_KEY}" if NCBI_KEY else ""


# --------------------------------------------------------------------------
# sources
# --------------------------------------------------------------------------

def gene_annotation(symbol, taxid):
    """MyGene.info → {entrez, name, summary, go_total, go_bp/mf/cc}."""
    species = "human" if taxid == 9606 else "mouse"
    key = f"mygene:{species}:{symbol}"

    def fetch():
        url = (f"{MYGENE}/query?q=symbol:{urllib.parse.quote(symbol)}"
               f"&species={species}&fields=entrezgene,name,summary,go&size=1")
        hits = json.loads(_get(url)).get("hits", [])
        if not hits:
            return None
        h = hits[0]
        go = h.get("go", {}) or {}
        def n(branch):
            b = go.get(branch, [])
            return len(b) if isinstance(b, list) else (1 if b else 0)
        go_bp, go_mf, go_cc = n("BP"), n("MF"), n("CC")
        return {
            "entrez": h.get("entrezgene"), "name": h.get("name", ""),
            "summary": h.get("summary", ""),
            "go_bp": go_bp, "go_mf": go_mf, "go_cc": go_cc,
            "go_total": go_bp + go_mf + go_cc,
        }
    return _cached(key, fetch)


def _orgn(taxid):
    # PubMed indexes by organism common name, NOT txid.
    return "human" if taxid == 9606 else "mouse"


def pubmed_count(symbol, taxid):
    """NCBI esearch → number of PubMed papers for this gene."""
    key = f"pmcount:{taxid}:{symbol}"

    def fetch():
        term = urllib.parse.quote(f"{symbol}[gene] AND {_orgn(taxid)}[orgn]")
        url = f"{NCBI}/esearch.fcgi?db=pubmed&term={term}&retmode=json{_ncbi_suffix()}"
        return int(json.loads(_get(url, ncbi=True))["esearchresult"]["count"])
    return _cached(key, fetch)


def pubmed_pmids(symbol, taxid, n=6):
    key = f"pmids:{taxid}:{symbol}:{n}"

    def fetch():
        term = urllib.parse.quote(f"{symbol}[gene] AND {_orgn(taxid)}[orgn]")
        url = (f"{NCBI}/esearch.fcgi?db=pubmed&term={term}&retmax={n}"
               f"&sort=relevance&retmode=json{_ncbi_suffix()}")
        return json.loads(_get(url, ncbi=True))["esearchresult"]["idlist"]
    return _cached(key, fetch) or []


def pubmed_abstracts(pmids):
    """efetch → [{pmid, title, abstract}] for the given PMIDs (for RAG)."""
    if not pmids:
        return []
    key = "abs:" + ",".join(sorted(pmids))

    def fetch():
        ids = ",".join(pmids)
        url = f"{NCBI}/efetch.fcgi?db=pubmed&id={ids}&retmode=xml{_ncbi_suffix()}"
        root = ET.fromstring(_get(url, ncbi=True))
        out = []
        for art in root.findall(".//PubmedArticle"):
            pmid = art.findtext(".//PMID") or ""
            title = "".join(art.find(".//ArticleTitle").itertext()) if art.find(".//ArticleTitle") is not None else ""
            abst = " ".join("".join(a.itertext()) for a in art.findall(".//Abstract/AbstractText"))
            if abst:
                out.append({"pmid": pmid, "title": title.strip(), "abstract": abst.strip()})
        return out
    return _cached(key, fetch) or []


def string_partners(symbol, taxid, limit=8):
    """STRING → top functional partners [{partner, score}]."""
    key = f"string:{taxid}:{symbol}:{limit}"

    def fetch():
        url = (f"{STRING}/json/interaction_partners?identifiers={urllib.parse.quote(symbol)}"
               f"&species={taxid}&limit={limit}")
        data = json.loads(_get(url))
        return [{"partner": d["preferredName_B"], "score": round(float(d["score"]), 3)}
                for d in data]
    return _cached(key, fetch) or []


# STRING scores each interaction per evidence CHANNEL (sub-score field -> label).
# This is what STRING's coloured edges encode; we surface it so the UI can explain
# *why* two genes are linked.
STRING_CHANNELS = {
    "escore": "experiments", "dscore": "databases", "tscore": "text-mining",
    "ascore": "co-expression", "nscore": "gene neighborhood",
    "fscore": "gene fusion", "pscore": "co-occurrence",
}


def string_network(symbol, taxid, add=10):
    """STRING subnetwork: the gene + `add` top interactors + ALL edges among them,
    each edge annotated with STRING's per-evidence-channel sub-scores. `add=10`
    matches STRING's web default (1st shell = 10 interactors), so the node set is
    the same as string-db.org.
    Returns {nodes: [name...], edges: [{a, b, score, channels:{label: subscore}}]}."""
    key = f"stringnet:{taxid}:{symbol}:{add}"

    def fetch():
        url = (f"{STRING}/json/network?identifiers={urllib.parse.quote(symbol)}"
               f"&species={taxid}&add_nodes={add}")
        data = json.loads(_get(url))
        edges = []
        for d in data:
            channels = {label: round(float(d[k]), 3)
                        for k, label in STRING_CHANNELS.items()
                        if k in d and float(d[k]) > 0}
            edges.append({"a": d["preferredName_A"], "b": d["preferredName_B"],
                          "score": round(float(d["score"]), 3), "channels": channels})
        nodes = sorted({n for e in edges for n in (e["a"], e["b"])})
        return {"nodes": nodes, "edges": edges}
    return _cached(key, fetch) or {"nodes": [], "edges": []}


# --------------------------------------------------------------------------
# darkness rating  (proposal Phase 4)
# --------------------------------------------------------------------------

def _clamp01(x):
    return max(0.0, min(1.0, x))


def darkness(symbol, taxid, ann=None):
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
        "score": score, "pubmed_count": pubs, "go_total": go,
        "dark_pub": round(dark_pub, 2), "dark_go": round(dark_go, 2),
        "band": ("dark" if score >= 6.5 else "grey" if score >= 3.5 else "bright"),
    }


def enrich(symbol, taxid):
    """Everything the gene page needs from external sources, in one bundle."""
    ann = gene_annotation(symbol, taxid)
    return {
        "symbol": symbol,
        "annotation": ann,
        "darkness": darkness(symbol, taxid, ann=ann),
        "string_partners": string_partners(symbol, taxid),
    }


# --------------------------------------------------------------------------
if __name__ == "__main__":
    sym = sys.argv[1] if len(sys.argv) > 1 else "TP53"
    tax = int(sys.argv[2]) if len(sys.argv) > 2 else 9606
    print(f"key: {'set' if NCBI_KEY else 'NONE (3/s)'}\n")
    print(json.dumps(enrich(sym, tax), indent=2, ensure_ascii=False))
