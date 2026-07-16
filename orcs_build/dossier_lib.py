#!/usr/bin/env python3
"""Extraction + literature + rendering helpers for a single-gene BioGRID ORCS dossier.

Streams the offline BioGRID ORCS mouse/human `.tar.gz` archives (no disk extraction,
stdlib only), pulls out one gene's screens with full experimental context, retains the
full gene tables for that gene's screens (needed by the relatedness pipeline), and
fetches the source PubMed literature (abstract + PMC open-access full text).

Stdlib-only by design (like build_gene_docs.py) so it runs under the system python with
no extra environment.
"""
from __future__ import annotations

import io
import json
import hashlib
import tarfile
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Archive locations / constants
# ---------------------------------------------------------------------------
WD = Path(__file__).resolve().parent
RAW = WD / "raw"
ARCHIVES = {
    "mouse": ("mouse.tar.gz", "Mus musculus", "10090"),
    "human": ("human.tar.gz", "Homo sapiens", "9606"),
}
PUBMED_URL = "https://pubmed.ncbi.nlm.nih.gov/{}/"
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
BIOC_PMC = "https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi/BioC_json/{}/unicode"
USER_AGENT = "RETICLE-dossier/1.0 (https://github.com/washu-dev/RETICLE)"

SCORE_COLS = [f"SCORE.{n}" for n in range(1, 6)]


def read_header(line: str) -> list[str]:
    return [c.lstrip("#").strip() for c in line.rstrip("\n").split("\t")]


def clean(v: str | None) -> str:
    if v is None:
        return ""
    v = v.strip()
    return "" if v in ("-", "", "N/A") else v


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class GeneScreenRow:
    """One (target gene, screen) measurement."""
    screen_id: str
    hit: bool
    scores: list[str]           # raw SCORE.1..5 strings
    entrez: str
    aliases: str
    organism_id: str


@dataclass
class ScreenTableRow:
    """One (gene, screen) measurement inside a retained full screen table."""
    symbol: str
    entrez: str
    scores: list[str]
    hit: bool


@dataclass
class Extraction:
    target: str
    organism_label: str
    organism_id: str
    source_version: str
    gene_rows: list[GeneScreenRow] = field(default_factory=list)          # 1 per screen the gene is in
    screen_meta: dict[str, dict] = field(default_factory=dict)            # screen_id -> index metadata
    screen_tables: dict[str, list[ScreenTableRow]] = field(default_factory=dict)  # screen_id -> full gene table
    global_hit: dict[str, int] = field(default_factory=dict)              # symbol -> # screens hit (all screens)
    global_tested: dict[str, int] = field(default_factory=dict)          # symbol -> # screens tested (all screens)
    n_archive_screens: int = 0                                            # total screens scanned in the archive

    def hit_frequency(self, symbol: str) -> float:
        t = self.global_tested.get(symbol, 0)
        return (self.global_hit.get(symbol, 0) / t) if t else 0.0

    @property
    def hit_screen_ids(self) -> list[str]:
        return [r.screen_id for r in self.gene_rows if r.hit]

    @property
    def nonhit_screen_ids(self) -> list[str]:
        return [r.screen_id for r in self.gene_rows if not r.hit]

    def pmids(self, hit_only: bool = False) -> list[str]:
        """Unique source PubMed IDs across the gene's screens, in first-seen order."""
        out: list[str] = []
        rows = [r for r in self.gene_rows if (r.hit or not hit_only)]
        for r in rows:
            m = self.screen_meta.get(r.screen_id, {})
            if clean(m.get("SOURCE_TYPE", "")).lower() == "pubmed":
                pid = clean(m.get("SOURCE_ID", ""))
                if pid and pid not in out:
                    out.append(pid)
        return out


# ---------------------------------------------------------------------------
# Extraction — single pass over the archive
# ---------------------------------------------------------------------------
def extract_gene(target: str, organism: str = "mouse") -> Extraction:
    tar_name, org_label, org_id = ARCHIVES[organism]
    tar_path = RAW / tar_name
    if not tar_path.exists():
        raise FileNotFoundError(f"ORCS archive not found: {tar_path}")

    # version is embedded in the file names, e.g. ...-2.0.18.index.tab.txt
    version = "unknown"
    ex = Extraction(target=target, organism_label=org_label, organism_id=org_id,
                    source_version=version)

    with tarfile.open(tar_path, "r:gz") as t:
        for m in t:
            if not m.isfile():
                continue
            f = t.extractfile(m)
            if f is None:
                continue
            if m.name.endswith("index.tab.txt"):
                if "-" in m.name and ".index" in m.name:
                    ex.source_version = m.name.split("-")[-1].replace(".index.tab.txt", "")
                _parse_index_stream(f, ex.screen_meta)
            elif m.name.endswith(".screen.tab.txt"):
                ex.n_archive_screens += 1
                _scan_screen_stream(f, target, ex)

    # Keep only the metadata for screens the target appears in.
    keep = {r.screen_id for r in ex.gene_rows}
    ex.screen_meta = {sid: meta for sid, meta in ex.screen_meta.items() if sid in keep}
    return ex


def _parse_index_stream(fobj, meta_out: dict[str, dict]) -> None:
    txt = io.TextIOWrapper(fobj, encoding="utf-8", errors="replace")
    cols = read_header(txt.readline())
    ci = {c: i for i, c in enumerate(cols)}
    sidx = ci.get("SCREEN_ID")
    if sidx is None:
        return
    for line in txt:
        p = line.rstrip("\n").split("\t")
        if len(p) < len(cols):
            continue
        meta_out[p[sidx]] = {c: p[ci[c]] for c in cols}


def _scan_screen_stream(fobj, target: str, ex: Extraction) -> None:
    """Buffer a screen's rows; if the target gene is present, retain the full table."""
    txt = io.TextIOWrapper(fobj, encoding="utf-8", errors="replace")
    header = txt.readline()
    if not header.startswith("#"):
        return
    cols = read_header(header)
    ci = {c: i for i, c in enumerate(cols)}
    need = ["SCREEN_ID", "IDENTIFIER_ID", "OFFICIAL_SYMBOL", "ALIASES", "ORGANISM_ID", "HIT"]
    if any(c not in ci for c in need):
        return
    sc_idx = [ci[c] for c in SCORE_COLS]

    screen_id = None
    table: list[ScreenTableRow] = []
    target_row: GeneScreenRow | None = None
    for line in txt:
        p = line.rstrip("\n").split("\t")
        if len(p) < len(cols):
            continue
        if screen_id is None:
            screen_id = p[ci["SCREEN_ID"]].strip()
        sym = p[ci["OFFICIAL_SYMBOL"]].strip()
        entrez = p[ci["IDENTIFIER_ID"]].strip()
        scores = [p[i].strip() for i in sc_idx]
        hit = p[ci["HIT"]].strip().upper() == "YES"
        table.append(ScreenTableRow(symbol=sym, entrez=entrez, scores=scores, hit=hit))
        if sym and not sym.startswith("ENTREZ:"):
            ex.global_tested[sym] = ex.global_tested.get(sym, 0) + 1
            if hit:
                ex.global_hit[sym] = ex.global_hit.get(sym, 0) + 1
        if sym == target:
            target_row = GeneScreenRow(
                screen_id=screen_id, hit=hit, scores=scores, entrez=entrez,
                aliases=p[ci["ALIASES"]].strip(), organism_id=p[ci["ORGANISM_ID"]].strip(),
            )

    if target_row is not None and screen_id is not None:
        ex.gene_rows.append(target_row)
        ex.screen_tables[screen_id] = table


# ---------------------------------------------------------------------------
# Screen coverage classification (relatedness step 1 primitive)
# ---------------------------------------------------------------------------
def classify_screen(rows: list[ScreenTableRow]) -> dict:
    n = len(rows)
    n_hit = sum(1 for r in rows if r.hit)
    n_scored = sum(1 for r in rows if clean(r.scores[0]))
    # FULL: reports (near) the whole library with a continuous primary score and both
    # hit/non-hit calls. HIT_ONLY: essentially just the significant hits.
    genome_wide = n >= 2000
    has_nonhits = n_hit < 0.95 * n if n else False
    scored_frac = (n_scored / n) if n else 0.0
    full = bool(genome_wide or (has_nonhits and scored_frac >= 0.5))
    return {
        "n_genes": n, "n_hit": n_hit, "n_scored": n_scored,
        "scored_frac": round(scored_frac, 3), "coverage": "FULL" if full else "HIT_ONLY",
    }


# ---------------------------------------------------------------------------
# Literature: PubMed abstract (efetch) + PMC OA full text (BioC)
# ---------------------------------------------------------------------------
@dataclass
class Publication:
    pmid: str
    title: str = ""
    abstract: str = ""
    journal: str = ""
    year: str = ""
    fulltext: str = ""
    fulltext_source: str = ""     # "pmc_oa" | "" (abstract-only)


def _http_get(url: str, cache_dir: Path, tag: str, params: dict | None = None,
              sleep: float = 0.34) -> str:
    cache_dir.mkdir(parents=True, exist_ok=True)
    full = url + ("?" + urllib.parse.urlencode(params) if params else "")
    key = tag + "_" + hashlib.sha256(full.encode("utf-8")).hexdigest()[:16] + ".cache"
    cache = cache_dir / key
    if cache.exists():
        return cache.read_text(encoding="utf-8")
    req = urllib.request.Request(full, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read().decode("utf-8", errors="replace")
    cache.write_text(data, encoding="utf-8")
    time.sleep(sleep)   # be polite to NCBI (keyless ~3 req/s)
    return data


def fetch_pubmed(pmids: list[str], cache_dir: Path) -> dict[str, Publication]:
    """Batch efetch abstracts for a list of PMIDs (title/abstract/journal/year)."""
    out: dict[str, Publication] = {p: Publication(pmid=p) for p in pmids}
    if not pmids:
        return out
    xml = _http_get(f"{EUTILS}/efetch.fcgi", cache_dir, "efetch",
                    {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml",
                     "rettype": "abstract"})
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return out
    for art in root.findall(".//PubmedArticle"):
        pmid_el = art.find(".//MedlineCitation/PMID")
        if pmid_el is None or not (pmid_el.text or "").strip():
            continue
        pmid = pmid_el.text.strip()
        title_el = art.find(".//Article/ArticleTitle")
        title = "".join(title_el.itertext()).strip() if title_el is not None else ""
        chunks = []
        for ab in art.findall(".//Abstract/AbstractText"):
            txt = "".join(ab.itertext()).strip()
            if not txt:
                continue
            label = ab.get("Label")
            chunks.append(f"{label}: {txt}" if label else txt)
        journal_el = art.find(".//Journal/Title")
        year_el = art.find(".//JournalIssue/PubDate/Year")
        out[pmid] = Publication(
            pmid=pmid, title=title, abstract="\n".join(chunks),
            journal=journal_el.text.strip() if journal_el is not None and journal_el.text else "",
            year=year_el.text.strip() if year_el is not None and year_el.text else "",
        )
    return out


def fetch_gene_summary(entrez_id: str, cache_dir: Path) -> dict:
    """NCBI Gene esummary for one Entrez ID: official name, aliases, summary, locus."""
    if not entrez_id:
        return {}
    try:
        raw = _http_get(f"{EUTILS}/esummary.fcgi", cache_dir, "gene",
                        {"db": "gene", "id": entrez_id, "retmode": "json"})
        data = json.loads(raw)
    except Exception:
        return {}
    rec = (data.get("result", {}) or {}).get(str(entrez_id), {})
    if not rec:
        return {}
    return {
        "name": rec.get("name", ""),
        "description": rec.get("description", ""),
        "aliases": rec.get("otheraliases", ""),
        "summary": rec.get("summary", ""),
        "maplocation": rec.get("maplocation", ""),
        "chromosome": rec.get("chromosome", ""),
    }


def fetch_pmc_fulltext(pmid: str, cache_dir: Path) -> tuple[str, str]:
    """Return (fulltext, source). Empty text if the article is not in the PMC OA subset."""
    try:
        raw = _http_get(BIOC_PMC.format(pmid), cache_dir, "bioc")
    except Exception:
        return "", ""
    raw = raw.strip()
    if not raw or raw[0] not in "[{":
        return "", ""     # non-OA -> API returns an error string, not JSON
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError:
        return "", ""
    # BioC JSON: [{documents:[{passages:[{text, infons:{section_type,type}}]}]}]
    collection = doc[0] if isinstance(doc, list) else doc
    parts: list[str] = []
    for d in collection.get("documents", []):
        for pas in d.get("passages", []):
            txt = (pas.get("text") or "").strip()
            if not txt:
                continue
            sect = (pas.get("infons", {}) or {}).get("section_type", "")
            typ = (pas.get("infons", {}) or {}).get("type", "")
            if typ == "ref" or sect == "REF":
                continue    # skip the reference list
            parts.append(txt)
    body = "\n".join(parts).strip()
    return (body, "pmc_oa") if body else ("", "")
