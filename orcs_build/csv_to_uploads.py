#!/usr/bin/env python3
"""Convert a gene dossier's fact-table CSVs into GatewayAI-uploadable formats.

GatewayAI does not accept .csv. This emits:
  <GENE>_fact_tables.md    — RAG-friendly (each table as Markdown; large tables show the
                             most meaningful top rows, full data noted)
  <GENE>_fact_tables.xlsx  — faithful workbook, one sheet per CSV, ALL rows (needs openpyxl;
                             run via `uv run --no-project --with openpyxl python csv_to_uploads.py`)

Usage: python3 csv_to_uploads.py [GENE_DIR]
"""
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

# csv filename -> (human description, md row cap, sort-by column index for md top-N or None)
TABLES = {
    "fact_gene_relatedness.csv": ("Headline gene-relatedness edge table (merged channels, tier, "
                                  "specificity, BH-FDR).", 400, None),
    "fact_cohit.csv": ("Co-hit enrichment per candidate gene (Fisher's exact within Gm3558's FULL "
                       "screens + specificity vs the gene's own genome-wide hit rate).", 200, None),
    "fact_coessentiality.csv": ("Co-essentiality: Spearman correlation of hit-anchored screen "
                                "profiles vs Gm3558 (support = shared screens).", 200, None),
    "fact_cocitation.csv": ("Co-citation: genes hit in the same source publications as Gm3558.", 200, None),
    "fact_contextual.csv": ("Contextual convergence: co-hit with Gm3558 stratified by phenotype.",
                            200, 2),
    "screen_classification.csv": ("Per-screen coverage bucket (FULL vs HIT_ONLY) for Gm3558's screens.",
                                  10_000, None),
    "harmonization_report.csv": ("Per-FULL-screen score direction + core-essential validation gate.",
                                 10_000, None),
}


def read_csv(path: Path):
    with path.open(encoding="utf-8") as f:
        rows = list(csv.reader(f))
    return rows[0], rows[1:]


def md_cell(v: str) -> str:
    return v.replace("|", " / ").replace("\n", " ").strip()


def build_md(gene: str, csvs: dict, generated_at: str) -> str:
    L = [f"# {gene} — BioGRID ORCS relatedness fact tables",
         f"Source: BioGRID ORCS v2.0.18 (mouse), Gm3558-anchored relatedness pipeline. "
         f"Generated {generated_at}.",
         "Each section is one fact table. Large tables show the most meaningful top rows; the "
         f"complete data for every table is in {gene}_fact_tables.xlsx.", ""]
    for fn, (desc, cap, sort_idx) in TABLES.items():
        if fn not in csvs:
            continue
        header, rows = csvs[fn]
        total = len(rows)
        shown = rows
        if sort_idx is not None:
            def _num(x):
                try:
                    return -float(x)
                except ValueError:
                    return 0.0
            shown = sorted(rows, key=lambda r: _num(r[sort_idx]) if sort_idx < len(r) else 0.0)
        shown = shown[:cap]
        note = f" — showing top {len(shown)} of {total} rows" if total > len(shown) else f" ({total} rows)"
        L.append(f"## {fn[:-4]}{note}")
        L.append(desc)
        L.append("")
        L.append("| " + " | ".join(header) + " |")
        L.append("| " + " | ".join("---" for _ in header) + " |")
        for r in shown:
            L.append("| " + " | ".join(md_cell(c) for c in r) + " |")
        L.append("")
    return "\n".join(L)


def build_xlsx(path: Path, csvs: dict) -> bool:
    try:
        from openpyxl import Workbook
    except ImportError:
        return False
    wb = Workbook()
    wb.remove(wb.active)
    for fn, (header, rows) in csvs.items():
        ws = wb.create_sheet(title=fn[:-4][:31])
        ws.append(header)
        for r in rows:
            # coerce numeric-looking cells to numbers so Excel treats them as data
            out = []
            for c in r:
                try:
                    out.append(int(c))
                except ValueError:
                    try:
                        out.append(float(c))
                    except ValueError:
                        out.append(c)
            ws.append(out)
        ws.freeze_panes = "A2"
    wb.save(path)
    return True


def main() -> int:
    gene_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        Path(__file__).resolve().parent / "gene_dossiers" / "Gm3558")
    gene = gene_dir.name
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    csvs = {}
    for fn in TABLES:
        p = gene_dir / fn
        if p.exists():
            csvs[fn] = read_csv(p)
    if not csvs:
        print(f"No fact-table CSVs found in {gene_dir}")
        return 1

    md_path = gene_dir / f"{gene}_fact_tables.md"
    md_path.write_text(build_md(gene, csvs, generated_at), encoding="utf-8")
    print(f"wrote {md_path}  ({md_path.stat().st_size:,} bytes)")

    xlsx_path = gene_dir / f"{gene}_fact_tables.xlsx"
    if build_xlsx(xlsx_path, csvs):
        print(f"wrote {xlsx_path}  ({xlsx_path.stat().st_size:,} bytes)")
    else:
        print("openpyxl not available -> skipped .xlsx (re-run: "
              "uv run --no-project --with openpyxl python csv_to_uploads.py)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
