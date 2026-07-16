#!/usr/bin/env python3
"""Convert a gene dossier's .jsonl companions into GatewayAI-uploadable Markdown.

GatewayAI does not accept .jsonl. This emits one .md per .jsonl, each rendered for how a
RAG reads it:
  <GENE>_screens.md        one section per screen (metadata + Gm3558's scores)
  <GENE>_publications.md   one section per paper (metadata + abstract + PMC OA full text)
  <GENE>_relatedness.md    the relatedness edges as a Markdown table (top rows; full set noted)

Usage: python3 jsonl_to_md.py [GENE_DIR]
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

FULLTEXT_CAP = 120_000
REL_TABLE_CAP = 400


def load(path: Path):
    with path.open(encoding="utf-8") as f:
        return [json.loads(ln) for ln in f if ln.strip()]


def cell(v) -> str:
    if isinstance(v, (list, dict)):
        v = " / ".join(str(x) for x in v) if isinstance(v, list) else \
            "; ".join(f"{k}({x})" for k, x in v.items())
    return str(v).replace("|", " / ").replace("\n", " ").strip()


def _hdr(gene, title, src_file, n, generated_at):
    return [f"# {gene} — {title}",
            f"Converted from {src_file} ({n} records). BioGRID ORCS v2.0.18 + NCBI. "
            f"Generated {generated_at}.", ""]


def render_screens(gene, recs, generated_at) -> str:
    L = _hdr(gene, "CRISPR screen records", f"{gene}_screens.jsonl", len(recs), generated_at)
    for r in sorted(recs, key=lambda x: int(x["screen_id"])):
        status = "SIGNIFICANT HIT" if r["hit"] else "assayed, not a hit"
        cl = r.get("cell_line") or "n/a"
        ct = f" ({r['cell_type']})" if r.get("cell_type") else ""
        L.append(f"## Screen {r['screen_id']} — {r.get('phenotype') or 'unspecified'} "
                 f"in {cl}{ct} — {status}")
        L.append(f"- Coverage: {r.get('coverage')} | Organism: {r.get('organism')} "
                 f"(taxid {r.get('organism_id')})")
        L.append(f"- Screen type: {r.get('screen_type') or 'n/a'} | Library: "
                 f"{r.get('library_type') or 'n/a'}/{r.get('library_methodology') or 'n/a'} "
                 f"{r.get('enzyme') or ''}".rstrip())
        cond = r.get("condition") or "none"
        if r.get("condition_dosage"):
            cond += f" @ {r['condition_dosage']}"
        L.append(f"- Condition: {cond}")
        L.append(f"- Significance criteria: {r.get('significance_criteria') or 'not stated'}")
        src = f"PMID {r['pmid']}" if r.get("pmid") else "custom source"
        L.append(f"- Source: {src}"
                 + (f" — {r['author']}" if r.get("author") else "")
                 + (f" — https://pubmed.ncbi.nlm.nih.gov/{r['pmid']}/" if r.get("pmid") else ""))
        scores = r.get("scores") or {}
        L.append(f"- {gene} scores: " + ("; ".join(f"{k}={v}" for k, v in scores.items()) or "n/a"))
        L.append("")
    return "\n".join(L)


def render_publications(gene, recs, generated_at) -> str:
    L = _hdr(gene, "source publications (abstracts + PMC open-access full text)",
             f"{gene}_publications.jsonl", len(recs), generated_at)
    for r in recs:
        L.append(f"## PMID {r['pmid']} — {r.get('title') or '(title unavailable)'}")
        jy = r.get("journal", "") or ""
        if r.get("year"):
            jy = (jy + f" ({r['year']})").strip()
        meta = " · ".join(x for x in (r.get("author"), jy, r.get("url")) if x)
        L.append(f"- {meta}")
        backs = ", ".join(f"{b['screen_id']}{'(HIT)' if b['hit'] else ''}"
                          for b in r.get("backs_screens", []))
        L.append(f"- Backs {gene} screens: {backs}")
        L.append(f"- Full text: {r.get('fulltext_source') or 'abstract only (not PMC open-access)'}")
        L.append("")
        L.append(f"**Abstract:** {r.get('abstract') or 'unavailable'}")
        L.append("")
        ft = r.get("fulltext") or ""
        if ft:
            L.append("**Full text (PMC open access):**")
            L.append("")
            L.append(ft[:FULLTEXT_CAP] + ("\n[... truncated ...]" if len(ft) > FULLTEXT_CAP else ""))
            L.append("")
        L.append("---")
        L.append("")
    return "\n".join(L)


def render_relatedness(gene, recs, generated_at) -> str:
    cols = ["gene", "tier", "specificity_class", "channels", "n_cohit", "n_cohit_pubs",
            "odds_ratio", "cohit_q", "spec_enrichment", "spec_q", "rho", "n_coess", "coess_q",
            "n_shared_pubs", "contexts", "hit_freq_all", "is_core_essential", "strength"]
    rank = {"Strong": 3, "Moderate": 2, "Weak": 1}
    recs = sorted(recs, key=lambda r: (-rank.get(r.get("tier"), 0), -(r.get("strength") or 0)))
    shown = recs[:REL_TABLE_CAP]
    L = _hdr(gene, "candidate gene relatedness (edge table)", f"{gene}_relatedness.jsonl",
             len(recs), generated_at)
    L.append(f"Showing the top {len(shown)} of {len(recs)} edges (Strong/Moderate first, then by "
             f"strength). Columns: co-hit (Fisher within {gene}'s FULL screens), specificity "
             "(binomial vs the gene's genome-wide hit rate), co-essentiality (rho), co-citation, "
             "contextual. `specificity_class` = specific vs common-essential neighborhood.")
    L.append("")
    L.append("| " + " | ".join(cols) + " |")
    L.append("| " + " | ".join("---" for _ in cols) + " |")
    for r in shown:
        L.append("| " + " | ".join(cell(r.get(c, "")) for c in cols) + " |")
    L.append("")
    return "\n".join(L)


def main() -> int:
    gene_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        Path(__file__).resolve().parent / "gene_dossiers" / "Gm3558")
    gene = gene_dir.name
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    jobs = [
        (f"{gene}_screens.jsonl", render_screens, f"{gene}_screens.md"),
        (f"{gene}_publications.jsonl", render_publications, f"{gene}_publications.md"),
        (f"{gene}_relatedness.jsonl", render_relatedness, f"{gene}_relatedness.md"),
    ]
    made = 0
    for src, renderer, out in jobs:
        p = gene_dir / src
        if not p.exists():
            print(f"skip (missing): {src}")
            continue
        recs = load(p)
        (gene_dir / out).write_text(renderer(gene, recs, generated_at), encoding="utf-8")
        print(f"wrote {gene_dir / out}  ({(gene_dir / out).stat().st_size:,} bytes, {len(recs)} records)")
        made += 1
    return 0 if made else 1


if __name__ == "__main__":
    sys.exit(main())
