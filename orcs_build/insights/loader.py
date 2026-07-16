"""Standalone-mode loader — rebuild a DossierView from an existing on-disk dossier.

Reads the canonical companions written by dossier_render (``<GENE>_screens.jsonl``,
``<GENE>_publications.jsonl``, ``<GENE>_relatedness.jsonl``, ``harmonization_report.csv``,
``_MANIFEST.txt``) and reconstructs the SAME ``DossierView`` the in-memory path builds —
so ``python3 -m insights <GENE>`` regenerates insights with zero re-extraction and no
BioGRID/NCBI network calls (identity is recovered from the local NCBI cache if present).
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from .evidence import DossierView, PubView, ScreenView, build_pack

WD = Path(__file__).resolve().parents[1]   # orcs_build/
_CACHE = WD.parent / ".reticle" / "cache" / "pubmed"


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def _read_harmonization(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    out: dict[str, dict] = {}
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            out[row["screen_id"]] = row
    return out


def _parse_manifest(path: Path) -> dict:
    info: dict = {"entrez": "", "thresholds": {}}
    if not path.exists():
        return info
    text = path.read_text(encoding="utf-8")
    m = re.search(r"Entrez Gene ID\s*:\s*(\S+)", text)
    if m and m.group(1) not in ("n/a",):
        info["entrez"] = m.group(1)
    m = re.search(r"Thresholds\s*:\s*(\{.*\})", text)
    if m:
        try:
            info["thresholds"] = json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    return info


def _identity(entrez: str) -> dict:
    """Recover NCBI Gene identity from the local cache (no network if cached)."""
    if not entrez:
        return {}
    try:
        import dossier_lib  # top-level orcs_build module
        return dossier_lib.fetch_gene_summary(entrez, _CACHE)
    except Exception:
        return {}


def view_from_disk(outdir: Path) -> DossierView:
    outdir = Path(outdir)
    gene = outdir.name
    screens_raw = _read_jsonl(outdir / f"{gene}_screens.jsonl")
    pubs_raw = _read_jsonl(outdir / f"{gene}_publications.jsonl")
    rel_raw = _read_jsonl(outdir / f"{gene}_relatedness.jsonl")
    harm = _read_harmonization(outdir / "harmonization_report.csv")
    manifest = _parse_manifest(outdir / "_MANIFEST.txt")

    if not screens_raw:
        raise FileNotFoundError(f"no {gene}_screens.jsonl in {outdir}; run build_gene_dossier first")

    organism = screens_raw[0].get("organism", "")
    organism_id = screens_raw[0].get("organism_id", "")

    screens: list[ScreenView] = []
    for r in screens_raw:
        sid = str(r.get("screen_id", ""))
        h = harm.get(sid, {})
        screens.append(ScreenView(
            screen_id=sid, hit=bool(r.get("hit")), coverage=r.get("coverage", "") or "",
            phenotype=r.get("phenotype", ""), cell_line=r.get("cell_line", ""),
            cell_type=r.get("cell_type", ""), condition=r.get("condition", ""),
            condition_dosage=r.get("condition_dosage", ""), screen_type=r.get("screen_type", ""),
            library_type=r.get("library_type", ""), library_methodology=r.get("library_methodology", ""),
            enzyme=r.get("enzyme", ""), significance_criteria=r.get("significance_criteria", ""),
            author=r.get("author", ""), pmid=r.get("pmid", ""), scores=r.get("scores", {}) or {},
            direction=h.get("direction", ""), gate=h.get("gate", ""),
            gate_detail=h.get("gate_detail", ""),
            hit_percentile_median=h.get("hit_percentile_median", ""),
        ))

    publications: list[PubView] = []
    for r in pubs_raw:
        backs = [(str(b.get("screen_id")), bool(b.get("hit"))) for b in r.get("backs_screens", [])]
        publications.append(PubView(
            pmid=str(r.get("pmid", "")), title=r.get("title", ""), abstract=r.get("abstract", ""),
            journal=r.get("journal", ""), year=r.get("year", ""), author=r.get("author", ""),
            fulltext_source=r.get("fulltext_source", ""),
            backs_screens=sorted(backs, key=lambda x: int(x[0]) if x[0].isdigit() else 0),
        ))

    relatives = [dict(r) for r in rel_raw]   # already carry specificity_class + tier

    # Reconstruct aggregate counts from the records themselves.
    spec = [r for r in relatives if r.get("specificity_class") == "specific"]
    nonspec = [r for r in relatives if r.get("specificity_class") != "specific"]
    validation = {
        "n_relatives": len(spec),
        "n_strong": sum(1 for r in spec if r.get("tier") == "Strong"),
        "n_moderate": sum(1 for r in spec if r.get("tier") == "Moderate"),
        "n_weak": sum(1 for r in spec if r.get("tier") == "Weak"),
        "n_nonspecific": len(nonspec),
        "string_mouse": {},   # not persisted to jsonl; unknown in standalone mode
    }
    n_full = sum(1 for s in screens if s.coverage == "FULL")

    entrez = manifest.get("entrez", "")
    return DossierView(
        gene=gene, organism=organism, organism_id=organism_id, entrez=entrez,
        identity=_identity(entrez), screens=screens, publications=publications, relatives=relatives,
        n_full_screens=n_full, thresholds=manifest.get("thresholds", {}), validation=validation,
    )


def build_evidence_pack_from_disk(outdir: Path):
    return build_pack(view_from_disk(outdir))
