#!/usr/bin/env python3
"""Render a single-gene ORCS dossier into GatewayAI upload files + structured companions.

Emits:
  Gm3558_ORCS_GatewayAI.txt          identity + 33 screens (hit/non-hit) + publication abstracts
  Gm3558_publications_fulltext.txt   PMC open-access full text (one section per article)
  Gm3558_relatives.txt               ranked candidate relatives + criteria/justification
  *.jsonl                            screens / publications / relatedness (semantic-vector ready)
  fact_*.csv, screen_classification.csv, harmonization_report.csv, _MANIFEST.txt
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from dossier_lib import clean

FULLTEXT_CAP = 120_000     # per-article char cap in the full-text file


# ---------------------------------------------------------------------------
# small accessors
# ---------------------------------------------------------------------------
def _row_by_screen(ex) -> dict:
    return {r.screen_id: r for r in ex.gene_rows}


def _author_for_pmid(ex, pmid: str) -> str:
    for r in ex.gene_rows:
        m = ex.screen_meta.get(r.screen_id, {})
        if clean(m.get("SOURCE_ID", "")) == pmid:
            return clean(m.get("AUTHOR", ""))
    return ""


def _screens_for_pmid(ex, pmid: str) -> list[tuple[str, bool]]:
    out = []
    for r in ex.gene_rows:
        m = ex.screen_meta.get(r.screen_id, {})
        if clean(m.get("SOURCE_ID", "")) == pmid:
            out.append((r.screen_id, r.hit))
    return sorted(out, key=lambda x: int(x[0]))


def _score_pairs(ex, row) -> list[str]:
    m = ex.screen_meta.get(row.screen_id, {})
    pairs = []
    for n in range(1, 6):
        st = clean(m.get(f"SCORE.{n}_TYPE", ""))
        sv = clean(row.scores[n - 1])
        if st and sv:
            pairs.append(f"{st}={sv}")
    return pairs


def _pub_ref(ex, sid) -> str:
    m = ex.screen_meta.get(sid, {})
    if clean(m.get("SOURCE_TYPE", "")).lower() == "pubmed":
        pid = clean(m.get("SOURCE_ID", ""))
        au = clean(m.get("AUTHOR", ""))
        return f"{au}, PMID {pid} (https://pubmed.ncbi.nlm.nih.gov/{pid}/)" if pid else au
    return f"custom source {clean(m.get('SOURCE_ID',''))}"


# ---------------------------------------------------------------------------
# Screen block (used in both C and D)
# ---------------------------------------------------------------------------
def _screen_block(ex, sid, screen_class) -> list[str]:
    m = ex.screen_meta.get(sid, {})
    row = _row_by_screen(ex)[sid]
    cls = screen_class.get(sid, {})
    pheno = clean(m.get("PHENOTYPE", "")) or "unspecified phenotype"
    cell = clean(m.get("CELL_LINE", ""))
    ctype = clean(m.get("CELL_TYPE", ""))
    cell_txt = cell + (f" ({ctype})" if ctype else "") if cell else (ctype or "n/a")
    lib = "/".join(x for x in (clean(m.get("LIBRARY_TYPE", "")),
                               clean(m.get("LIBRARY_METHODOLOGY", ""))) if x)
    enz = clean(m.get("ENZYME", ""))
    lib_txt = " ".join(x for x in (lib, enz) if x) or "n/a"
    cond = clean(m.get("CONDITION_NAME", ""))
    dosage = clean(m.get("CONDITION_DOSAGE", ""))
    cond_txt = (cond + (f" @ {dosage}" if dosage else "")) if cond else "none"
    scores = "; ".join(_score_pairs(ex, row)) or "n/a"
    sig = clean(m.get("SIGNIFICANCE_CRITERIA", "")) or "not stated"
    lines = [
        f"### Screen {sid} — {pheno} in {cell_txt}",
        f"- Publication: {_pub_ref(ex, sid)}",
        f"- Cell line: {cell_txt} | Phenotype: {pheno} | Screen type: "
        f"{clean(m.get('SCREEN_TYPE','')) or 'n/a'} | Coverage: {cls.get('coverage','?')}",
        f"- Library: {lib_txt} | Condition: {cond_txt} | "
        f"Enzyme: {enz or 'n/a'} | Throughput: {clean(m.get('THROUGHPUT','')) or 'n/a'}",
        f"- Significance criteria: {sig}",
        f"- Gm3558 in this screen: {'SIGNIFICANT HIT' if row.hit else 'assayed, not a hit'}; "
        f"scores: {scores}",
        "",
    ]
    return lines


# ---------------------------------------------------------------------------
# Main dossier .txt (sections A-E)
# ---------------------------------------------------------------------------
def render_dossier_txt(ex, pubs, screen_class, gene_info, generated_at) -> str:
    hit_ids = sorted(ex.hit_screen_ids, key=int)
    nonhit_ids = sorted(ex.nonhit_screen_ids, key=int)
    all_pmids = ex.pmids()
    hit_pmids = ex.pmids(hit_only=True)
    entrez = ex.gene_rows[0].entrez if ex.gene_rows else ""
    n_full = sum(1 for c in screen_class.values() if c["coverage"] == "FULL")

    L = []
    L.append(f"BioGRID ORCS dossier — {ex.target} ({ex.organism_label})")
    L.append(f"Source: BioGRID ORCS v{ex.source_version} (offline screen archive) + NCBI "
             f"PubMed/PMC + NCBI Gene. Generated {generated_at}.")
    L.append("Purpose: load {g}'s CRISPR-screen evidence and its source literature into the "
             "WashU GatewayAI knowledge base.".format(g=ex.target))
    L.append("=" * 80)
    L.append("")

    # A. identity
    L.append("## A. Gene identity")
    L.append(f"Gene symbol: {ex.target} | Entrez Gene ID: {entrez or 'n/a'} | "
             f"Organism: {ex.organism_label} (taxid {ex.organism_id})")
    if gene_info:
        if gene_info.get("description"):
            L.append(f"Official name (NCBI Gene): {gene_info['description']}")
        loc = gene_info.get("maplocation") or gene_info.get("chromosome")
        if loc:
            L.append(f"Locus: {loc}")
        if gene_info.get("aliases"):
            L.append(f"Aliases (NCBI): {gene_info['aliases']}")
        if gene_info.get("summary"):
            L.append(f"NCBI summary: {gene_info['summary']}")
    L.append("Note: Gm3558 is a predicted, under-characterized gene — a de-orphanization "
             "target; the evidence below is functional-genomic (CRISPR screens) + literature.")
    L.append("")

    # B. summary
    L.append("## B. Screen summary")
    L.append(f"{ex.target} was assayed in {len(ex.gene_rows)} BioGRID ORCS {ex.organism_label} "
             f"CRISPR screens and called a SIGNIFICANT HIT in {len(hit_ids)} "
             f"({len(hit_ids)/len(ex.gene_rows)*100:.0f}%). "
             f"The {len(ex.gene_rows)} screens derive from {len(all_pmids)} publications "
             f"(the {len(hit_ids)} hits from {len(hit_pmids)}). "
             f"Coverage: {n_full} genome-wide (FULL) screens, "
             f"{len(ex.gene_rows)-n_full} hit-only.")
    L.append("")

    # C. hit screens
    L.append(f"## C. Screens where {ex.target} IS a significant hit ({len(hit_ids)})")
    L.append("")
    for sid in hit_ids:
        L += _screen_block(ex, sid, screen_class)

    # D. non-hit screens
    L.append(f"## D. Screens where {ex.target} was assayed but NOT a hit ({len(nonhit_ids)})")
    L.append("")
    for sid in nonhit_ids:
        L += _screen_block(ex, sid, screen_class)

    # E. publications (abstracts)
    L.append(f"## E. Associated publications ({len(all_pmids)}) — abstracts")
    L.append("(Open-access full text for these is in Gm3558_publications_fulltext.txt.)")
    L.append("")
    for pmid in all_pmids:
        p = pubs.get(pmid)
        backs = _screens_for_pmid(ex, pmid)
        backs_txt = ", ".join(f"{s}{'(HIT)' if h else ''}" for s, h in backs)
        L.append(f"### PMID {pmid} — {p.title if p and p.title else '(title unavailable)'}")
        au = _author_for_pmid(ex, pmid)
        jr = f"{p.journal} ({p.year})" if p and (p.journal or p.year) else ""
        L.append(f"- {au} · {jr} · https://pubmed.ncbi.nlm.nih.gov/{pmid}/")
        L.append(f"- Backs {ex.target} screens: {backs_txt}")
        ft = " · PMC open-access full text available" if (p and p.fulltext) else ""
        L.append(f"- Abstract: {(p.abstract if p and p.abstract else 'unavailable')}{ft}")
        L.append("")
    return "\n".join(L)


def render_fulltext_txt(ex, pubs, generated_at) -> str:
    L = [f"BioGRID ORCS dossier — {ex.target}: source-publication FULL TEXT (PMC open access)",
         f"Generated {generated_at}. Non-open-access articles show abstract only in the main dossier.",
         "=" * 80, ""]
    for pmid in ex.pmids():
        p = pubs.get(pmid)
        if not p or not p.fulltext:
            continue
        L.append(f"### PMID {pmid} — {p.title}")
        L.append(f"{p.journal} ({p.year}) · https://pubmed.ncbi.nlm.nih.gov/{pmid}/")
        L.append("")
        body = p.fulltext[:FULLTEXT_CAP]
        if len(p.fulltext) > FULLTEXT_CAP:
            body += "\n[... full text truncated ...]"
        L.append(body)
        L.append("")
        L.append("-" * 80)
        L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# Relatives .txt
# ---------------------------------------------------------------------------
def _relative_line(r) -> str:
    bits = [f"- {r['gene']} [{r['tier']}]"]
    if r["n_cohit"]:
        bits.append(f"co-hit {r['n_cohit']} screens/{r['n_cohit_pubs']} pubs "
                    f"(OR {r['odds_ratio']}, FDR {r['cohit_q']:.1e}; "
                    f"specificity {r['spec_enrichment']}x background, spec-FDR "
                    f"{r['spec_q']:.1e})" if r['cohit_q'] is not None else "")
    if r["rho"] is not None:
        bits.append(f"co-essentiality rho {r['rho']} (FDR {r['coess_q']:.1e}, {r['n_coess']} screens)")
    if r["n_shared_pubs"]:
        bits.append(f"co-citation in {r['n_shared_pubs']} publications")
    if r["contexts"]:
        ctx = ", ".join(f"{k} ({v})" for k, v in r["contexts"].items())
        bits.append(f"contexts: {ctx}")
    bits.append(f"genome-wide hit-freq {r['hit_freq_all']:.2f}"
                + (" [core-essential]" if r["is_core_essential"] else ""))
    return "; ".join(b for b in bits if b)


def render_relatives_txt(ex, res, generated_at) -> str:
    v = res["validation"]
    L = [f"Candidate functional relatives of {ex.target} — BioGRID ORCS ({ex.organism_label})",
         f"Source: BioGRID ORCS v{ex.source_version}. Generated {generated_at}.",
         "=" * 80, ""]
    L.append("## Question")
    L.append(f"Across the {len(ex.hit_screen_ids)} screens where {ex.target} is a hit (and the "
             f"{res['n_full_screens']} genome-wide screens it was assayed in), which other genes "
             "can be considered 'relatives', and by what criterion?")
    L.append("")
    L.append("## Criteria used to call a gene a relative (and the justification)")
    L += [
        "1. Co-hit enrichment — called a hit together with the target more often than chance, "
        "tested by Fisher's exact test over the FULL-coverage screens that assayed BOTH genes "
        "(the tested set is known there), BH-FDR across all candidates co-hit in >=2 screens.",
        "2. Specificity vs promiscuity — because the target's hits concentrate in "
        "proliferation/fitness screens, pan-essential 'hub' genes co-hit with it for non-specific "
        "reasons. Each candidate is also tested (binomial) against ITS OWN genome-wide hit "
        "frequency across all mouse screens; only co-hit rates that EXCEED the gene's background "
        "(enrichment >=1.5x, spec-FDR) count as specific.",
        "3. Co-essentiality — Spearman correlation of hit-anchored within-screen percentile "
        "profiles across the shared FULL screens (support-gated: >=20 shared screens for a strong "
        "edge — a high rho over few screens is discounted, per the support dimension).",
        "4. Co-citation — reported as a hit in the same source publication(s) as the target.",
        "5. Contextual convergence — co-hit stratified by phenotype domain (proliferation / "
        "signal transduction / chemical response), so an edge can be read in context.",
        "Guardrails: mouse only (never cross organism); a pair's evidence counts only screens that "
        "measured both genes; single-screen co-hits are dropped (logged); tiers reflect how many "
        "independent channels agree, with co-essentiality as the discriminator.",
        "",
    ]
    L.append("## Result summary")
    L.append(f"- Genes co-hit with {ex.target} in >=2 FULL screens and enriched over background "
             f"(specific): {v['n_relatives']}")
    L.append(f"  - Strong (specific co-hit AND strong co-essentiality): {v['n_strong']}")
    L.append(f"  - Moderate: {v['n_moderate']}  |  Weak: {v['n_weak']}")
    L.append(f"- Common-essential neighborhood (co-hit real but explained by the gene's own "
             f"promiscuity — NOT specific): {v['n_nonspecific']}")
    L.append(f"- Single-screen co-hits dropped as insufficient support: {res['dropped_low_support']}")
    sm = res["validation"]["string_mouse"]
    L.append(f"- STRING (mouse) cross-check of top relatives: {sm.get('status')}"
             + (f", {sm.get('n_edges_among_top')} edges among top genes" if sm.get('status') == 'ok' else ""))
    L.append("")

    for tier in ("Strong", "Moderate", "Weak"):
        rows = [r for r in res["relatives"] if r["tier"] == tier]
        if not rows:
            continue
        show = rows if tier != "Weak" else rows[:60]
        L.append(f"## {tier} relatives ({len(rows)}"
                 + (f"; showing top {len(show)}" if len(show) < len(rows) else "") + ")")
        for r in show:
            L.append(_relative_line(r))
        L.append("")

    ns = res["nonspecific"][:30]
    if ns:
        L.append(f"## Common-essential neighborhood ({len(res['nonspecific'])}; showing {len(ns)})")
        L.append("These co-hit reproducibly with the target but are hits in a large fraction of ALL "
                 "screens, so the association is largely non-specific (listed for transparency).")
        for r in ns:
            L.append(_relative_line(r))
        L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# JSONL companions
# ---------------------------------------------------------------------------
def write_screens_jsonl(path: Path, ex, screen_class) -> None:
    rows = _row_by_screen(ex)
    with path.open("w", encoding="utf-8") as f:
        for sid in sorted(rows, key=int):
            m = ex.screen_meta.get(sid, {})
            row = rows[sid]
            rec = {
                "type": "screen", "gene": ex.target, "screen_id": sid,
                "hit": row.hit, "coverage": screen_class.get(sid, {}).get("coverage"),
                "organism": ex.organism_label, "organism_id": ex.organism_id,
                "cell_line": clean(m.get("CELL_LINE", "")), "cell_type": clean(m.get("CELL_TYPE", "")),
                "phenotype": clean(m.get("PHENOTYPE", "")), "condition": clean(m.get("CONDITION_NAME", "")),
                "condition_dosage": clean(m.get("CONDITION_DOSAGE", "")),
                "screen_type": clean(m.get("SCREEN_TYPE", "")),
                "library_type": clean(m.get("LIBRARY_TYPE", "")),
                "library_methodology": clean(m.get("LIBRARY_METHODOLOGY", "")),
                "enzyme": clean(m.get("ENZYME", "")),
                "significance_criteria": clean(m.get("SIGNIFICANCE_CRITERIA", "")),
                "author": clean(m.get("AUTHOR", "")),
                "pmid": clean(m.get("SOURCE_ID", "")) if clean(m.get("SOURCE_TYPE", "")).lower() == "pubmed" else "",
                "scores": {clean(m.get(f"SCORE.{n}_TYPE", "")): clean(row.scores[n - 1])
                           for n in range(1, 6) if clean(m.get(f"SCORE.{n}_TYPE", "")) and clean(row.scores[n - 1])},
            }
            f.write(json.dumps(rec) + "\n")


def write_publications_jsonl(path: Path, ex, pubs) -> None:
    with path.open("w", encoding="utf-8") as f:
        for pmid in ex.pmids():
            p = pubs.get(pmid)
            backs = [{"screen_id": s, "hit": h} for s, h in _screens_for_pmid(ex, pmid)]
            rec = {
                "type": "publication", "pmid": pmid,
                "title": p.title if p else "", "journal": p.journal if p else "",
                "year": p.year if p else "", "author": _author_for_pmid(ex, pmid),
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                "abstract": p.abstract if p else "",
                "fulltext": p.fulltext if p else "", "fulltext_source": p.fulltext_source if p else "",
                "backs_screens": backs,
            }
            f.write(json.dumps(rec) + "\n")


def write_relatedness_jsonl(path: Path, ex, res) -> None:
    with path.open("w", encoding="utf-8") as f:
        for bucket, tag in ((res["relatives"], "specific"), (res["nonspecific"], "non_specific")):
            for r in bucket:
                rec = dict(r)
                rec.update({"type": "relatedness", "target": ex.target, "specificity_class": tag})
                f.write(json.dumps(rec) + "\n")


# ---------------------------------------------------------------------------
# CSV fact tables
# ---------------------------------------------------------------------------
def _write_csv(path: Path, header, rows) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def write_fact_tables(outdir: Path, ex, res, screen_class) -> None:
    raw = res["channels_raw"]

    _write_csv(outdir / "screen_classification.csv",
               ["screen_id", "hit", "coverage", "n_genes", "n_hit", "scored_frac", "phenotype", "pmid"],
               [[sid, _row_by_screen(ex)[sid].hit, c["coverage"], c["n_genes"], c["n_hit"],
                 c["scored_frac"], clean(ex.screen_meta.get(sid, {}).get("PHENOTYPE", "")),
                 clean(ex.screen_meta.get(sid, {}).get("SOURCE_ID", ""))]
                for sid, c in sorted(screen_class.items(), key=lambda kv: int(kv[0]))])

    _write_csv(outdir / "harmonization_report.csv",
               ["screen_id", "direction", "hit_percentile_median", "score1_type", "phenotype", "gate", "gate_detail"],
               [[sid, h["direction"], h["hit_percentile_median"], clean(h["score1_type"]),
                 clean(h["phenotype"]), h["gate"], h["gate_detail"]]
                for sid, h in sorted(res["harmonization"].items(), key=lambda kv: int(kv[0]))])

    cohit = raw["cohit"]
    _write_csv(outdir / "fact_cohit.csv",
               ["gene", "n_cohit", "n_cohit_pubs", "n_shared_full", "target_hits", "cand_hits",
                "odds_ratio", "jaccard", "cohit_p", "hit_freq_all", "spec_p", "spec_enrichment"],
               [[g, d["n_cohit"], d["n_cohit_pubs"], d["n_shared_full"], d["target_hits"], d["cand_hits"],
                 d["odds_ratio"], d["jaccard"], f"{d['cohit_p']:.3e}", d["hit_freq_all"],
                 f"{d['spec_p']:.3e}", d["spec_enrichment"]]
                for g, d in sorted(cohit.items(), key=lambda kv: (-kv[1]["n_cohit"], kv[1]["cohit_p"]))
                if d["n_cohit"] >= 2])

    coess = raw["coess"]
    _write_csv(outdir / "fact_coessentiality.csv",
               ["gene", "rho", "n_coess", "coess_p", "hit_freq_all"],
               [[g, d["rho"], d["n_coess"], f"{d['coess_p']:.3e}", d["hit_freq_all"]]
                for g, d in sorted(coess.items(), key=lambda kv: -abs(kv[1]["rho"]))
                if abs(d["rho"]) >= 0.4 and d["n_coess"] >= 10])

    cocit = raw["cocit"]
    _write_csv(outdir / "fact_cocitation.csv",
               ["gene", "n_shared_pubs", "shared_pubs"],
               [[g, d["n_shared_pubs"], "|".join(d["shared_pubs"])]
                for g, d in sorted(cocit.items(), key=lambda kv: -kv[1]["n_shared_pubs"])
                if d["n_shared_pubs"] >= 2])

    ctx = raw["contextual"]
    _write_csv(outdir / "fact_contextual.csv",
               ["gene", "context", "n_cohit_in_context"],
               [[g, c, n] for g, cd in sorted(ctx.items()) for c, n in cd.items() if n >= 2])

    rel = res["relatives"] + res["nonspecific"]
    _write_csv(outdir / "fact_gene_relatedness.csv",
               ["gene", "tier", "specific", "channels", "n_cohit", "n_cohit_pubs", "odds_ratio",
                "cohit_q", "spec_enrichment", "spec_q", "rho", "n_coess", "coess_q", "n_shared_pubs",
                "hit_freq_all", "is_core_essential", "strength"],
               [[r["gene"], r["tier"], r in res["relatives"], "|".join(r["channels"]),
                 r["n_cohit"], r["n_cohit_pubs"], r["odds_ratio"],
                 f"{r['cohit_q']:.3e}" if r["cohit_q"] is not None else "",
                 r["spec_enrichment"], f"{r['spec_q']:.3e}" if r["spec_q"] is not None else "",
                 r["rho"], r["n_coess"], f"{r['coess_q']:.3e}" if r["coess_q"] is not None else "",
                 r["n_shared_pubs"], r["hit_freq_all"], r["is_core_essential"], r["strength"]]
                for r in rel])


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------
def write_manifest(path: Path, ex, res, pubs, files, generated_at, insight_summary=None) -> None:
    v = res["validation"]
    n_ft = sum(1 for p in pubs.values() if p.fulltext)
    lines = [
        f"BioGRID ORCS single-gene dossier — {ex.target} ({ex.organism_label}, taxid {ex.organism_id})",
        f"Generated       : {generated_at}",
        f"Data source     : BioGRID ORCS v{ex.source_version} (offline archive, {ex.n_archive_screens} "
        f"{ex.organism_label} screens) + NCBI PubMed/PMC + NCBI Gene",
        f"Entrez Gene ID  : {ex.gene_rows[0].entrez if ex.gene_rows else 'n/a'}",
        "",
        f"Screens assayed : {len(ex.gene_rows)}  (HIT {len(ex.hit_screen_ids)} / "
        f"non-hit {len(ex.nonhit_screen_ids)})",
        f"FULL screens    : {res['n_full_screens']}",
        f"Publications    : {len(ex.pmids())} unique PMIDs ({n_ft} with PMC open-access full text)",
        "",
        f"Relatives (specific) : {v['n_relatives']}  (Strong {v['n_strong']} / Moderate "
        f"{v['n_moderate']} / Weak {v['n_weak']})",
        f"Non-specific         : {v['n_nonspecific']}   Dropped (single-screen): {res['dropped_low_support']}",
        f"Thresholds           : {json.dumps(res['thresholds'])}",
    ]
    if insight_summary:
        lines += ["", insight_summary]
    lines += [
        "",
        "Files:",
    ]
    lines += [f"  - {f}" for f in files]
    lines += ["",
              "Upload the two .txt files to GatewayAI (Knowledge base -> Files). The .jsonl and "
              ".csv are the machine-readable substrate (semantic-vector ingestion / analysis)."]
    path.write_text("\n".join(lines), encoding="utf-8")
