"""Deterministic evidence pack — the cited, structured input the insight layer reasons over.

A ``DossierView`` is a normalized, source-agnostic snapshot of one gene's dossier
(identity + screens + publications + relatives + aggregates). Both the in-memory path
(``view_from_memory`` over the build_gene_dossier objects) and the standalone disk path
(``loader.view_from_disk``) produce the SAME ``DossierView``, so everything downstream
(pack, prompt, guardrail, render) is identical regardless of source.

``build_pack(view)`` turns it into an ``EvidencePack``: a list of ``EvidenceItem``s each
with a namespaced ``evidence_id`` that resolves to a real object. ``pack.by_id()`` is the
guardrail's evidence map — any claim citing an id NOT in it is auto-dropped, which is how
fabricated citations are caught. Every fact the model may use exists here, cited.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

# Phenotype words that mark a screen as a growth/fitness (negative-selection) readout —
# the regime where the proliferation-concentration confound lives.
FITNESS_KEYWORDS = (
    "proliferation", "viability", "fitness", "growth", "cell cycle", "survival",
    "competitive", "dropout", "depletion", "essential", "negative selection",
)


# ---------------------------------------------------------------------------
# Normalized dossier view (source-agnostic)
# ---------------------------------------------------------------------------
@dataclass
class ScreenView:
    screen_id: str
    hit: bool
    coverage: str
    phenotype: str
    cell_line: str
    cell_type: str
    condition: str
    condition_dosage: str
    screen_type: str
    library_type: str
    library_methodology: str
    enzyme: str
    significance_criteria: str
    author: str
    pmid: str
    scores: dict
    # QC (harmonization gate; absent for HIT_ONLY / non-fitness screens)
    direction: str = ""
    gate: str = ""
    gate_detail: str = ""
    hit_percentile_median: str = ""

    @property
    def is_fitness(self) -> bool:
        p = self.phenotype.lower()
        return any(k in p for k in FITNESS_KEYWORDS)

    @property
    def cell_txt(self) -> str:
        if self.cell_line:
            return self.cell_line + (f" ({self.cell_type})" if self.cell_type else "")
        return self.cell_type or "n/a"

    @property
    def cond_txt(self) -> str:
        if not self.condition:
            return "none"
        return self.condition + (f" @ {self.condition_dosage}" if self.condition_dosage else "")


@dataclass
class PubView:
    pmid: str
    title: str
    abstract: str
    journal: str
    year: str
    author: str
    fulltext_source: str
    backs_screens: list[tuple[str, bool]] = field(default_factory=list)

    @property
    def has_fulltext(self) -> bool:
        return bool(self.fulltext_source)


@dataclass
class DossierView:
    gene: str
    organism: str
    organism_id: str
    entrez: str
    identity: dict
    screens: list[ScreenView]
    publications: list[PubView]
    relatives: list[dict]          # specific + non-specific; each carries specificity_class + tier
    n_full_screens: int
    thresholds: dict
    validation: dict
    generated_at: str = ""

    @property
    def hit_screens(self) -> list[ScreenView]:
        return [s for s in self.screens if s.hit]

    @property
    def nonhit_screens(self) -> list[ScreenView]:
        return [s for s in self.screens if not s.hit]


# ---------------------------------------------------------------------------
# Evidence pack
# ---------------------------------------------------------------------------
@dataclass
class EvidenceItem:
    evidence_id: str     # SCR:<id> | PMID:<id> | REL:<gene> | GENE:<sym> | SUM:<facet> | CTX:<pheno> | HARM:<id>
    kind: str            # screen | publication | relative | identity | summary | context | harmonization
    text: str            # compact, self-contained, NLI-checkable
    ref: dict            # structured backref for rendering (screen_id / pmid / gene)
    link: str = ""       # human URL where applicable


@dataclass
class EvidencePack:
    gene: str
    organism: str
    generated_at: str
    items: list[EvidenceItem]
    view: DossierView

    def by_id(self) -> dict[str, str]:
        """evidence_id -> text (the guardrail's evidence map)."""
        return {it.evidence_id: it.text for it in self.items}

    def index(self) -> dict[str, EvidenceItem]:
        return {it.evidence_id: it for it in self.items}

    def for_prompt(self, *, max_chars: int = 700) -> list[tuple[str, str]]:
        return [(it.evidence_id, it.text[:max_chars]) for it in self.items]


# ---------------------------------------------------------------------------
# Text renderers for each evidence kind (kept factual + word-rich for NLI)
# ---------------------------------------------------------------------------
def _scores_txt(scores: dict) -> str:
    return "; ".join(f"{k}={v}" for k, v in scores.items()) or "n/a"


def _screen_text(s: ScreenView) -> str:
    status = "a SIGNIFICANT HIT" if s.hit else "assayed but NOT a hit"
    parts = [
        f"Screen {s.screen_id}: {s.gene_ref} is {status} in a screen for "
        f"'{s.phenotype or 'unspecified phenotype'}' in {s.cell_txt}.",
        f"Screen type {s.screen_type or 'n/a'}; coverage {s.coverage or '?'}; "
        f"condition {s.cond_txt}; library {s.library_type or 'n/a'}/"
        f"{s.library_methodology or 'n/a'}; enzyme {s.enzyme or 'n/a'}.",
        f"Significance criteria: {s.significance_criteria or 'not stated'}. "
        f"Scores: {_scores_txt(s.scores)}.",
    ]
    if s.pmid:
        parts.append(f"Publication {s.author or ''} PMID {s.pmid}.")
    return " ".join(parts)


def _harm_text(s: ScreenView) -> str:
    return (
        f"QC for screen {s.screen_id} ({s.phenotype}): score direction {s.direction or 'n/a'}, "
        f"hit-percentile median {s.hit_percentile_median or 'n/a'}, essentiality gate "
        f"{s.gate or 'N/A'} ({s.gate_detail or 'no detail'}). "
        + ("Fitness signal is LOW-TRUST (WARN)." if s.gate == "WARN"
           else "Fitness signal is trustworthy (PASS)." if s.gate == "PASS"
           else "Gate not applicable.")
    )


def _pub_text(p: PubView) -> str:
    backs = ", ".join(f"{sid}{'(HIT)' if hit else ''}" for sid, hit in p.backs_screens)
    ft = "PMC open-access full text available" if p.has_fulltext else "abstract only (open-access full text unavailable)"
    ab = (p.abstract or "abstract unavailable").replace("\n", " ")
    return (
        f"Publication PMID {p.pmid} ({p.author or 'n/a'}, {p.journal or 'n/a'} {p.year or ''}): "
        f"\"{p.title or '(title unavailable)'}\". This paper is the source of {p.gene_ref} screens "
        f"{backs or 'n/a'}; {ft}. Abstract: {ab}"
    )


def _rel_text(r: dict, gene: str) -> str:
    chans = ", ".join(r.get("channels", []) or [])
    spec = r.get("specificity_class", "")
    bits = [f"{r['gene']} is a {r.get('tier','?')}-tier {spec or ''} functional relative of {gene}"]
    if r.get("n_cohit"):
        bits.append(
            f"co-hit in {r['n_cohit']} screens across {r.get('n_cohit_pubs', 0)} publications "
            f"(odds ratio {r.get('odds_ratio')}, co-hit FDR {r.get('cohit_q')})"
        )
    if r.get("spec_enrichment"):
        bits.append(f"specificity {r.get('spec_enrichment')}x over its genome-wide background")
    if r.get("rho") is not None:
        bits.append(f"co-essential Spearman rho {r.get('rho')} over {r.get('n_coess', 0)} screens")
    if r.get("n_shared_pubs"):
        bits.append(f"co-cited in {r['n_shared_pubs']} publications")
    if chans:
        bits.append(f"evidence channels: {chans}")
    ctx = r.get("contexts") or {}
    if ctx:
        bits.append("contexts " + ", ".join(f"{k} ({v})" for k, v in ctx.items()))
    bits.append(
        f"genome-wide hit-frequency {r.get('hit_freq_all')}"
        + ("; flagged core-essential" if r.get("is_core_essential") else "; not core-essential")
    )
    return "; ".join(bits) + "."


def _identity_text(view: DossierView) -> str:
    idn = view.identity or {}
    desc = idn.get("description") or "predicted / uncharacterized gene"
    parts = [
        f"{view.gene} (Entrez Gene {view.entrez or 'n/a'}, {view.organism}, taxid {view.organism_id}): "
        f"official name '{desc}'."
    ]
    if idn.get("maplocation") or idn.get("chromosome"):
        parts.append(f"Locus {idn.get('maplocation') or idn.get('chromosome')}.")
    if idn.get("aliases"):
        parts.append(f"Aliases: {idn['aliases']}.")
    if idn.get("summary"):
        parts.append(f"NCBI summary: {idn['summary']}")
    else:
        parts.append(
            f"{view.gene} has no assigned molecular function in NCBI Gene; it is a predicted, "
            "under-characterized de-orphanization target, so all functional signal here is inferred "
            "from CRISPR-screen behaviour and literature co-occurrence, not direct annotation."
        )
    return " ".join(parts)


# Give the screen/pub renderers access to the gene symbol for readable text.
def _bind_gene(view: DossierView) -> None:
    for s in view.screens:
        s.gene_ref = view.gene  # type: ignore[attr-defined]
    for p in view.publications:
        p.gene_ref = view.gene  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Pack builder (shared by both sources)
# ---------------------------------------------------------------------------
def build_pack(view: DossierView, *, max_relatives: int = 25, max_nonhit: int = 22) -> EvidencePack:
    _bind_gene(view)
    items: list[EvidenceItem] = []
    g = view.gene

    # Identity
    items.append(EvidenceItem(f"GENE:{g}", "identity", _identity_text(view), {"gene": g}))

    # Aggregate summaries
    hits = view.hit_screens
    nonhits = view.nonhit_screens
    n = len(view.screens)
    n_hit = len(hits)
    n_fit_hit = sum(1 for s in hits if s.is_fitness)
    pmids = sorted({s.pmid for s in view.screens if s.pmid})
    items.append(EvidenceItem(
        "SUM:screens", "summary",
        f"{g} was assayed in {n} BioGRID ORCS {view.organism} CRISPR screens and called a "
        f"SIGNIFICANT HIT in {n_hit} ({(100*n_hit/n) if n else 0:.0f}%), across {len(pmids)} "
        f"source publications. It is a predicted, uncharacterized gene.",
        {"n_screens": n, "n_hit": n_hit},
    ))
    items.append(EvidenceItem(
        "SUM:coverage", "summary",
        f"Of {g}'s {n} screens, {view.n_full_screens} are genome-wide (FULL coverage) and the rest "
        f"are hit-only; FULL screens have a defined non-hit counterfactual, HIT_ONLY screens do not.",
        {"n_full": view.n_full_screens},
    ))
    items.append(EvidenceItem(
        "SUM:confound", "summary",
        f"{n_fit_hit} of {g}'s {n_hit} hits are growth/fitness (negative-selection) screens, so a "
        f"naive co-hit network would conflate functional partners with commonly-essential genes; the "
        f"relatedness analysis therefore applies a per-partner binomial specificity correction against "
        f"each candidate's own genome-wide hit rate.",
        {"n_fitness_hits": n_fit_hit, "n_hit": n_hit},
    ))
    v = view.validation or {}
    items.append(EvidenceItem(
        "SUM:relatives", "summary",
        f"After the specificity correction, {g} has {v.get('n_relatives', '?')} specific relatives "
        f"(Strong {v.get('n_strong', '?')} / Moderate {v.get('n_moderate', '?')} / "
        f"Weak {v.get('n_weak', '?')}) and {v.get('n_nonspecific', '?')} non-specific "
        f"(common-essential) neighbours. STRING mouse cross-check: "
        f"{(view.validation.get('string_mouse') or {}).get('status', 'n/a')}"
        f"{', ' + str((view.validation.get('string_mouse') or {}).get('n_edges_among_top')) + ' edges among top genes' if (view.validation.get('string_mouse') or {}).get('status') == 'ok' else ''}.",
        {},
    ))

    # Per-screen + QC
    for s in sorted(view.screens, key=lambda x: (not x.hit, int(x.screen_id) if x.screen_id.isdigit() else 0)):
        if not s.hit and len(nonhits) > max_nonhit and s.coverage != "FULL":
            # keep all hits + all FULL non-hits; cap noisy hit-only non-hits
            continue
        items.append(EvidenceItem(
            f"SCR:{s.screen_id}", "screen", _screen_text(s),
            {"screen_id": s.screen_id, "hit": s.hit, "pmid": s.pmid},
            link=f"https://pubmed.ncbi.nlm.nih.gov/{s.pmid}/" if s.pmid else "",
        ))
        if s.gate:
            items.append(EvidenceItem(
                f"HARM:{s.screen_id}", "harmonization", _harm_text(s), {"screen_id": s.screen_id}))

    # Contexts (phenotype domains where the gene is a hit)
    ctx_map: dict[str, list[str]] = {}
    for s in hits:
        ctx_map.setdefault(s.phenotype or "unspecified", []).append(s.screen_id)
    for pheno, sids in sorted(ctx_map.items(), key=lambda kv: -len(kv[1])):
        key = "CTX:" + pheno.lower().replace(" ", "_")[:40]
        items.append(EvidenceItem(
            key, "context",
            f"{g} is a hit in {len(sids)} screen(s) with phenotype '{pheno}': screens "
            f"{', '.join(sorted(sids, key=lambda x: int(x) if x.isdigit() else 0))}.",
            {"context": pheno, "screen_ids": sids},
        ))

    # Publications
    for p in view.publications:
        items.append(EvidenceItem(
            f"PMID:{p.pmid}", "publication", _pub_text(p),
            {"pmid": p.pmid}, link=f"https://pubmed.ncbi.nlm.nih.gov/{p.pmid}/"))

    # Relatives (specific first by strength, then a few non-specific for transparency)
    specific = [r for r in view.relatives if r.get("specificity_class") == "specific"]
    nonspec = [r for r in view.relatives if r.get("specificity_class") != "specific"]
    specific.sort(key=lambda r: -(r.get("strength") or 0))
    nonspec.sort(key=lambda r: -(r.get("strength") or 0))
    for r in specific[:max_relatives] + nonspec[:5]:
        items.append(EvidenceItem(
            f"REL:{r['gene']}", "relative", _rel_text(r, g),
            {"gene": r["gene"], "tier": r.get("tier"), "specificity_class": r.get("specificity_class")},
        ))

    return EvidencePack(gene=g, organism=view.organism,
                        generated_at=view.generated_at, items=items, view=view)


# ---------------------------------------------------------------------------
# In-memory source (build_gene_dossier objects)
# ---------------------------------------------------------------------------
def view_from_memory(ex, pubs, gene_info, res, generated_at: str = "") -> DossierView:
    from dossier_lib import clean  # top-level orcs_build module

    screen_class = res.get("screen_class", {})
    harm = res.get("harmonization", {})
    rows = {r.screen_id: r for r in ex.gene_rows}

    screens: list[ScreenView] = []
    for sid, row in rows.items():
        m = ex.screen_meta.get(sid, {})
        h = harm.get(sid, {})
        scores = {clean(m.get(f"SCORE.{k}_TYPE", "")): clean(row.scores[k - 1])
                  for k in range(1, 6)
                  if clean(m.get(f"SCORE.{k}_TYPE", "")) and clean(row.scores[k - 1])}
        screens.append(ScreenView(
            screen_id=sid, hit=row.hit,
            coverage=screen_class.get(sid, {}).get("coverage", ""),
            phenotype=clean(m.get("PHENOTYPE", "")), cell_line=clean(m.get("CELL_LINE", "")),
            cell_type=clean(m.get("CELL_TYPE", "")), condition=clean(m.get("CONDITION_NAME", "")),
            condition_dosage=clean(m.get("CONDITION_DOSAGE", "")),
            screen_type=clean(m.get("SCREEN_TYPE", "")), library_type=clean(m.get("LIBRARY_TYPE", "")),
            library_methodology=clean(m.get("LIBRARY_METHODOLOGY", "")), enzyme=clean(m.get("ENZYME", "")),
            significance_criteria=clean(m.get("SIGNIFICANCE_CRITERIA", "")),
            author=clean(m.get("AUTHOR", "")),
            pmid=clean(m.get("SOURCE_ID", "")) if clean(m.get("SOURCE_TYPE", "")).lower() == "pubmed" else "",
            scores=scores,
            direction=str(h.get("direction", "")), gate=str(h.get("gate", "")),
            gate_detail=str(h.get("gate_detail", "")),
            hit_percentile_median=str(h.get("hit_percentile_median", "")),
        ))

    publications: list[PubView] = []
    for pmid in ex.pmids():
        p = pubs.get(pmid)
        backs = []
        for r in ex.gene_rows:
            mm = ex.screen_meta.get(r.screen_id, {})
            if clean(mm.get("SOURCE_ID", "")) == pmid:
                backs.append((r.screen_id, r.hit))
        publications.append(PubView(
            pmid=pmid, title=p.title if p else "", abstract=p.abstract if p else "",
            journal=p.journal if p else "", year=p.year if p else "",
            author=next((clean(ex.screen_meta.get(r.screen_id, {}).get("AUTHOR", ""))
                         for r in ex.gene_rows
                         if clean(ex.screen_meta.get(r.screen_id, {}).get("SOURCE_ID", "")) == pmid), ""),
            fulltext_source=p.fulltext_source if p else "",
            backs_screens=sorted(backs, key=lambda x: int(x[0]) if x[0].isdigit() else 0),
        ))

    relatives = []
    for r in res.get("relatives", []):
        relatives.append({**r, "specificity_class": "specific"})
    for r in res.get("nonspecific", []):
        relatives.append({**r, "specificity_class": "non_specific"})

    entrez = ex.gene_rows[0].entrez if ex.gene_rows else ""
    return DossierView(
        gene=ex.target, organism=ex.organism_label, organism_id=ex.organism_id, entrez=entrez,
        identity=gene_info or {}, screens=screens, publications=publications, relatives=relatives,
        n_full_screens=res.get("n_full_screens", 0), thresholds=res.get("thresholds", {}),
        validation=res.get("validation", {}), generated_at=generated_at,
    )


def build_evidence_pack(ex, pubs, gene_info, res, generated_at: str = "") -> EvidencePack:
    """Evidence pack from the in-memory build_gene_dossier objects."""
    return build_pack(view_from_memory(ex, pubs, gene_info, res, generated_at))
