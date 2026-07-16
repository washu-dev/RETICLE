#!/usr/bin/env bash
# Build a gene dossier + AI insight brief and render the PDF.
#   ./make_insight_brief.sh <GENE> <mouse|human> [claims.json]
# With a claims file, the insights are the curated (external LLM) + verified set;
# without one, the deterministic layer is used. Stdlib Python; Chrome for the PDF.
set -euo pipefail
GENE="${1:-Gm3558}"
ORG="${2:-mouse}"
CLAIMS="${3:-}"
WD="$(cd "$(dirname "$0")" && pwd)"
OUT="$WD/gene_dossiers/$GENE"

if [ -n "$CLAIMS" ]; then
  python3 "$WD/build_gene_dossier.py" "$GENE" "$ORG" --insights-claims="$CLAIMS"
else
  python3 "$WD/build_gene_dossier.py" "$GENE" "$ORG"
fi

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
if [ -x "$CHROME" ] && [ -f "$OUT/${GENE}_insights_print.html" ]; then
  "$CHROME" --headless --disable-gpu --no-pdf-header-footer \
    --print-to-pdf="$OUT/${GENE}_Insight_Brief.pdf" \
    "file://$OUT/${GENE}_insights_print.html"
  echo "PDF: $OUT/${GENE}_Insight_Brief.pdf"
else
  echo "Chrome not found or no print HTML; skipped PDF (Markdown/HTML still produced)."
fi
