"""Standalone CLI — regenerate insights for an existing dossier (no re-extraction).

    python3 -m insights <GENE>                 deterministic insights from disk
    python3 -m insights <GENE> --llm [--prefer gemini]   generate via an LLM provider
    python3 -m insights <GENE> --emit-prompt   print the evidence-pack prompt (for offline LLM use)
    python3 -m insights <GENE> --claims f.json ingest produced claims, verify, and render

Run from the orcs_build/ directory (so the top-level dossier_lib/dossier_render import).
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

from .loader import build_evidence_pack_from_disk
from .pipeline import run_insights_from_pack
from .synthesis import build_insight_prompt

WD = Path(__file__).resolve().parents[1]


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("-")]
    flags = {a for a in argv if a.startswith("-")}
    gene = args[0] if args else "Gm3558"
    outdir = WD / "gene_dossiers" / gene
    if not outdir.exists():
        print(f"error: no dossier at {outdir} — run build_gene_dossier.py {gene} first", file=sys.stderr)
        return 2

    prefer = None
    for a in argv:
        if a.startswith("--prefer"):
            prefer = a.split("=", 1)[1] if "=" in a else (args[1] if len(args) > 1 else None)
    claims_path = None
    for i, a in enumerate(argv):
        if a == "--claims" and i + 1 < len(argv):
            claims_path = argv[i + 1]
        elif a.startswith("--claims="):
            claims_path = a.split("=", 1)[1]

    pack = build_evidence_pack_from_disk(outdir)

    if "--emit-prompt" in flags:
        print(build_insight_prompt(pack))
        return 0

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    res = run_insights_from_pack(
        pack,
        allow_external_llm=("--llm" in flags),
        prefer=prefer,
        claims_path=claims_path,
        generated_at=generated_at,
    )
    files = res.write(outdir, gene, generated_at)
    print(res.summary_line())
    for f in files:
        p = outdir / f
        print(f"  {p.stat().st_size:>9,d}  {f}" if p.exists() else f"  (missing) {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
