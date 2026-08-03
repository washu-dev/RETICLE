"""
fetch_pubmed_abstracts.py — targeted PubMed corpus for the gene KB.
====================================================================
Instead of mirroring all of PubMed (~40 GB, 99% irrelevant), fetch ONLY the
abstracts for papers linked to our genes: read gene2pubmed.gz, take the union
of PMIDs for the requested taxids, and efetch their title + abstract into a
local SQLite table (kb_document).

Resumable: re-running skips PMIDs already stored, so a Slurm time-out or a
dropped connection just means "run it again" — it picks up where it left off.

  python3 fetch_pubmed_abstracts.py \
      --gene2pubmed /storage3/fs1/aorvedahl-RETICLE/Active/data/ncbi/gene2pubmed.gz \
      --out         /storage3/fs1/aorvedahl-RETICLE/Active/data/kb/kb.db \
      --taxids 9606,10090

Set NCBI_API_KEY (env or ../.env) to go from 3 -> 10 requests/s.
"""
import argparse
import gzip
import os
import sqlite3
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
SNAPSHOT = os.environ.get("KB_SNAPSHOT", "2026-07")


def load_env():
    """Pull NCBI_API_KEY etc. from ../.env if present (same format as the rest)."""
    env = Path(__file__).resolve().parent.parent / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def collect_pmids(gene2pubmed, taxids):
    """Union of PubMed IDs linked to any gene of the requested taxids.
    gene2pubmed columns: #tax_id  GeneID  PubMed_ID (tab-separated)."""
    want = set(taxids)
    pmids = set()
    op = gzip.open if str(gene2pubmed).endswith(".gz") else open
    with op(gene2pubmed, "rt") as f:
        for line in f:
            if line.startswith("#"):
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 3 and parts[0] in want:
                pmids.add(parts[2])
    return pmids


def open_db(path):
    con = sqlite3.connect(path, timeout=120)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("""CREATE TABLE IF NOT EXISTS kb_document (
        pmid     TEXT PRIMARY KEY,
        title    TEXT,
        abstract TEXT,
        journal  TEXT,
        year     TEXT,
        source   TEXT,
        snapshot TEXT)""")
    con.commit()
    return con


def efetch(ids, key):
    """POST efetch (POST avoids URL-length limits for a batch of ids)."""
    params = {"db": "pubmed", "id": ",".join(ids), "retmode": "xml"}
    if key:
        params["api_key"] = key
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(
        EFETCH, data=data, headers={"User-Agent": "RETICLE-KB/1.0 (research)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def parse(xml_bytes):
    root = ET.fromstring(xml_bytes)
    out = []
    for art in root.findall(".//PubmedArticle"):
        pmid = art.findtext(".//MedlineCitation/PMID") or art.findtext(".//PMID") or ""
        te = art.find(".//ArticleTitle")
        title = "".join(te.itertext()).strip() if te is not None else ""
        # structured abstracts have several <AbstractText> sections — join them
        abst = " ".join("".join(a.itertext())
                        for a in art.findall(".//Abstract/AbstractText")).strip()
        journal = (art.findtext(".//Journal/ISOAbbreviation")
                   or art.findtext(".//Journal/Title") or "")
        year = (art.findtext(".//JournalIssue/PubDate/Year")
                or art.findtext(".//JournalIssue/PubDate/MedlineDate") or "")
        if pmid:
            out.append((pmid, title, abst, journal, year))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gene2pubmed", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--taxids", default="9606,10090")
    ap.add_argument("--batch", type=int, default=200)
    args = ap.parse_args()

    load_env()
    key = os.environ.get("NCBI_API_KEY", "")
    rate = 0.11 if key else 0.34          # min seconds between calls: 10/s vs 3/s
    print(f"NCBI key: {'set (10/s)' if key else 'NONE (3/s)'}", flush=True)

    taxids = [t.strip() for t in args.taxids.split(",") if t.strip()]
    print(f"collecting PMIDs from {args.gene2pubmed} for taxids {taxids} ...", flush=True)
    pmids = collect_pmids(args.gene2pubmed, taxids)
    print(f"  {len(pmids):,} unique PMIDs linked to those genes", flush=True)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    con = open_db(args.out)
    have = {r[0] for r in con.execute("SELECT pmid FROM kb_document")}
    todo = sorted(pmids - have, key=int)
    print(f"  already stored: {len(have):,} | to fetch: {len(todo):,}", flush=True)

    last, requested = 0.0, 0
    for i in range(0, len(todo), args.batch):
        batch = todo[i:i + args.batch]
        wait = rate - (time.time() - last)
        if wait > 0:
            time.sleep(wait)
        rows = []
        for attempt in range(4):                       # retry with backoff
            try:
                rows = parse(efetch(batch, key))
                last = time.time()
                break
            except Exception as e:
                if attempt == 3:
                    print(f"  ! batch @ {i} failed after retries: {e}", flush=True)
                else:
                    time.sleep(2 ** attempt)
        con.executemany(
            "INSERT OR REPLACE INTO kb_document VALUES (?,?,?,?,?,?,?)",
            [(p, t, a, j, y, "pubmed", SNAPSHOT) for (p, t, a, j, y) in rows])
        con.commit()
        requested += len(batch)
        if i % (args.batch * 25) == 0:
            got = con.execute("SELECT COUNT(*) FROM kb_document").fetchone()[0]
            print(f"  {requested:,}/{len(todo):,} requested | {got:,} docs stored", flush=True)

    total = con.execute("SELECT COUNT(*) FROM kb_document").fetchone()[0]
    withabs = con.execute("SELECT COUNT(*) FROM kb_document WHERE abstract != ''").fetchone()[0]
    con.close()
    print(f"DONE — {total:,} docs ({withabs:,} with a non-empty abstract)", flush=True)


if __name__ == "__main__":
    main()
