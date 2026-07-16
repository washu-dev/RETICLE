#!/usr/bin/env python3
"""Build a single-gene BioGRID ORCS dossier for the WashU GatewayAI RAG.

Pulls one gene's CRISPR-screen evidence (all screens, hit + non-hit) from the offline
ORCS archive, its source PubMed literature (abstracts + PMC open-access full text) and an
NCBI Gene identity block, computes Gm3558-anchored gene relatedness, and renders
GatewayAI-upload .txt files plus structured .jsonl/.csv companions.

Usage:
    python3 build_gene_dossier.py [GENE] [ORGANISM]
    (defaults: Gm3558 mouse)

Stdlib only; run with the system python3.
"""
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import dossier_lib as dl
import dossier_render as dr
from relatedness import pipeline as P

WD = Path(__file__).resolve().parent


def main() -> int:
    argv = [a for a in sys.argv[1:] if not a.startswith("-")]
    flags = {a for a in sys.argv[1:] if a.startswith("-")}
    gene = argv[0] if argv else "Gm3558"
    organism = argv[1] if len(argv) > 1 else "mouse"
    want_insights = "--no-insights" not in flags                 # default ON (deterministic)
    allow_llm = ("--insights-llm" in flags) or os.environ.get("RETICLE_INSIGHTS_LLM") == "1"
    claims_path = next((a.split("=", 1)[1] for a in sys.argv[1:]
                        if a.startswith("--insights-claims=")), None)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    outdir = WD / "gene_dossiers" / gene
    outdir.mkdir(parents=True, exist_ok=True)
    pubmed_cache = WD.parent / ".reticle" / "cache" / "pubmed"

    print(f"[1/5] Extracting {gene} from the {organism} ORCS archive ...", flush=True)
    ex = dl.extract_gene(gene, organism)
    print(f"      assayed in {len(ex.gene_rows)} screens; HIT in {len(ex.hit_screen_ids)}; "
          f"{len(ex.pmids())} source PMIDs; scanned {ex.n_archive_screens} archive screens.")

    print(f"[2/5] Fetching NCBI Gene summary + {len(ex.pmids())} PubMed abstracts ...", flush=True)
    entrez = ex.gene_rows[0].entrez if ex.gene_rows else ""
    gene_info = dl.fetch_gene_summary(entrez, pubmed_cache)
    pubs = dl.fetch_pubmed(ex.pmids(), pubmed_cache)
    print(f"      abstracts fetched: {sum(1 for p in pubs.values() if p.title)}/{len(pubs)}")

    print(f"[3/5] Fetching PMC open-access full text ...", flush=True)
    n_ft = 0
    for pmid in ex.pmids():
        ft, src = dl.fetch_pmc_fulltext(pmid, pubmed_cache)
        if ft:
            pubs[pmid].fulltext, pubs[pmid].fulltext_source = ft, src
            n_ft += 1
    print(f"      full text (PMC OA): {n_ft}/{len(pubs)} articles")

    print(f"[4/5] Computing {gene}-anchored relatedness (6-step pipeline) ...", flush=True)
    res = P.run_relatedness(ex, dl.classify_screen)
    screen_class = res["screen_class"]
    v = res["validation"]
    print(f"      specific relatives {v['n_relatives']} "
          f"(Strong {v['n_strong']}/Mod {v['n_moderate']}/Weak {v['n_weak']}); "
          f"non-specific {v['n_nonspecific']}; dropped {res['dropped_low_support']}")

    print(f"[5/5] Rendering dossier files -> {outdir} ...", flush=True)
    dossier = f"{gene}_ORCS_GatewayAI.txt"
    fulltext = f"{gene}_publications_fulltext.txt"
    relatives = f"{gene}_relatives.txt"
    (outdir / dossier).write_text(
        dr.render_dossier_txt(ex, pubs, screen_class, gene_info, generated_at), encoding="utf-8")
    (outdir / fulltext).write_text(
        dr.render_fulltext_txt(ex, pubs, generated_at), encoding="utf-8")
    (outdir / relatives).write_text(
        dr.render_relatives_txt(ex, res, generated_at), encoding="utf-8")
    dr.write_screens_jsonl(outdir / f"{gene}_screens.jsonl", ex, screen_class)
    dr.write_publications_jsonl(outdir / f"{gene}_publications.jsonl", ex, pubs)
    dr.write_relatedness_jsonl(outdir / f"{gene}_relatedness.jsonl", ex, res)
    dr.write_fact_tables(outdir, ex, res, screen_class)

    insight_summary = None
    if want_insights:
        from insights import pipeline as I
        mode = "curated" if claims_path else ("LLM" if allow_llm else "deterministic")
        print(f"[6/6] Generating cited AI insights ({mode}) ...", flush=True)
        ins = I.run_insights(ex, pubs, gene_info, res, allow_external_llm=allow_llm,
                             claims_path=claims_path, generated_at=generated_at)
        ins.write(outdir, gene, generated_at)   # <GENE>_insights.{jsonl,md,html} + figures
        insight_summary = ins.summary_line()
        print("      " + insight_summary)

    files = sorted(p.name for p in outdir.iterdir() if p.name != "_MANIFEST.txt")
    dr.write_manifest(outdir / "_MANIFEST.txt", ex, res, pubs, files, generated_at,
                      insight_summary=insight_summary)

    # ---- verification gate -------------------------------------------------
    print("\n=== VERIFICATION ===")
    ok = True

    def check(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}")

    check(f"assayed in 33 screens (got {len(ex.gene_rows)})", len(ex.gene_rows) == 33)
    check(f"HIT in 11 screens (got {len(ex.hit_screen_ids)})", len(ex.hit_screen_ids) == 11)
    check(f"22 non-hit screens (got {len(ex.nonhit_screen_ids)})", len(ex.nonhit_screen_ids) == 22)
    check(f"all abstracts fetched ({sum(1 for p in pubs.values() if p.title)}/{len(pubs)})",
          all(p.title for p in pubs.values()))
    check(f"some PMC full text ({n_ft} articles)", n_ft >= 1)
    gate_fitness = [h for h in res["harmonization"].values() if h["gate"] in ("PASS", "WARN")]
    n_pass = sum(1 for h in gate_fitness if h["gate"] == "PASS")
    check(f"core-essential gate ran on fitness screens ({n_pass} PASS / {len(gate_fitness)} scored)",
          len(gate_fitness) >= 1)
    check(f"top relatives not hub-dominated (promiscuous frac {v['top_promiscuous_fraction']})",
          not v["hub_contamination_warn"])
    check("relatives found", v["n_relatives"] > 0)

    print(f"\n{'ALL CHECKS PASSED' if ok else 'SOME CHECKS FAILED'} — files in {outdir}")
    for f in files + ["_MANIFEST.txt"]:
        print(f"  {(outdir / f).stat().st_size:>9,d}  {f}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
