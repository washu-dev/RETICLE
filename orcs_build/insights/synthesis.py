"""Insight synthesis — the cautious prompt, the structured schema, and a deterministic fallback.

Two ways to produce candidate claims from an ``EvidencePack``:
  - ``templated_insights(pack)``  : deterministic, no LLM — guarantees a useful, cited artifact.
  - ``synthesize_insights(pack)`` : LLM via the provider gateway (or an offline emit/ingest
                                    loop), returning [] when no provider is available.

Both return ``guardrail.Claim`` objects; the pipeline verifies every one against the pack's
real evidence ids before anything is written. The schema + system prompt mirror
``apps/api/reticle_api/ai/synthesis.py`` and extend it with the layer/category taxonomy.
"""
from __future__ import annotations

import json

from .evidence import EvidencePack
from .guardrail import Claim
from .privacy import DataSensitivity, PrivacyGate
from .provider import LLMProvider, get_provider

# 5-tier label scheme (weakest -> strongest evidence assertion).
TIERS = ["speculation", "hypothesis", "inference", "indirect_evidence", "direct_evidence"]

CLAIM_SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "layer": {"type": "integer"},          # 0 explicit / 1 implicit / 2 hypothesis / 3 validation
                    "category": {"type": "string"},         # A..H, H1..H3, V1..
                    "label": {"type": "string", "enum": TIERS},
                    "evidence_ids": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "number"},
                    "uncertainty": {"type": "string"},
                },
                "required": ["text", "layer", "category", "label", "evidence_ids"],
            },
        }
    },
    "required": ["claims"],
}

_SYSTEM = (
    "You are a cautious functional-genomics analyst writing an insight brief on an "
    "under-characterized gene for a principal investigator. You are a retrieval-and-attribution "
    "engine, NOT a knowledge engine: you may only assert what the supplied evidence licenses. "
    "Rules: (1) Every claim labeled direct_evidence / indirect_evidence / inference MUST cite the "
    "evidence_ids it relies on, using ONLY ids that appear in the evidence list below; never invent "
    "an id, a citation, a gene function, or a mechanism. (2) Use the 5-tier label scheme honestly: "
    "direct_evidence (restates one field/paper), indirect_evidence (a pattern across >=2 records of "
    "one type), inference (a connection across evidence TYPES), hypothesis (a novel testable "
    "mechanism), speculation (plausible but weak). Prefer weaker labels when unsure. (3) Assign each "
    "claim a layer: 0 explicit, 1 implicit (cross-source), 2 hypothesis, 3 validation experiment. "
    "(4) Handle the confounds explicitly: the gene's hits concentrate in proliferation/fitness "
    "screens, so present specificity-corrected relatedness only, and down-weight WARN-gate screens "
    "and HIT_ONLY non-hits. (5) When metadata is insufficient to interpret a screen (no significance "
    "criteria, HIT_ONLY coverage, ambiguous direction), do NOT assert involvement — say the "
    "interpretation is withheld. (6) Answer the three PI questions directly. Return ONLY JSON "
    "matching the schema."
)

_QUESTIONS = (
    "The three questions the PI needs answered:\n"
    "  Q1. Why is the gene a hit in the screens where it hits? (category B)\n"
    "  Q2. Why is it NOT a hit in the screens where it was assayed but did not score? (category C)\n"
    "  Q3. Which genes are its functional relatives, and by what criterion? (category E)\n"
)

_CATEGORIES = (
    "Insight categories to cover: A identity/de-orphanization; B hit-context pattern (Q1); "
    "C non-hit contrast (Q2); D literature synthesis; E relatedness/network (Q3); "
    "F cross-evidence mechanistic synthesis; G confounds/QC caveats; H confidence & limitations; "
    "H1..H3 testable hypotheses (layer 2); V1..Vn validation experiments (layer 3)."
)


def build_insight_prompt(pack: EvidencePack) -> str:
    lines = [
        _SYSTEM, "", _QUESTIONS, "", _CATEGORIES, "",
        f"Gene: {pack.gene} ({pack.organism}).",
        "",
        "EVIDENCE (cite by these ids only):",
    ]
    for eid, text in pack.for_prompt():
        lines.append(f"- {eid}: {text}")
    lines += [
        "",
        "Produce a thorough set of claims (aim for 25-45) spanning all layers and categories, each "
        "honestly labeled and cited to the ids above. Include >=3 layer-2 hypotheses and a matching "
        "layer-3 validation plan. Return JSON only, matching this schema:",
        json.dumps(CLAIM_SCHEMA),
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Deterministic fallback (no LLM) — guarantees a cited, useful ledger
# ---------------------------------------------------------------------------
def templated_insights(pack: EvidencePack) -> list[Claim]:
    view = pack.view
    g = view.gene
    ids = pack.index()
    out: list[Claim] = []

    def add(text, label, cat, layer, evidence, conf=0.6, unc="moderate",
            withheld=False, reason=""):
        out.append(Claim(text=text, label=label, category=cat, layer=layer,
                         evidence_ids=[e for e in evidence if e in ids or not e],
                         confidence=conf, uncertainty=unc, withheld=withheld,
                         withheld_reason=reason, trusted=True))

    # A. identity
    add(f"{g} is a predicted, under-characterized {view.organism} gene (Entrez {view.entrez or 'n/a'}) "
        f"with no assigned molecular function, so every functional signal below is inferred from "
        f"CRISPR-screen behaviour and literature co-occurrence rather than direct annotation.",
        "direct_evidence", "A", 0, [f"GENE:{g}"], conf=0.9, unc="low")

    # B. hit-context pattern (Q1)
    hits = view.hit_screens
    n, n_hit = len(view.screens), len(hits)
    add(f"{g} was assayed in {n} BioGRID ORCS {view.organism} CRISPR screens and is a significant hit "
        f"in {n_hit} of them ({(100*n_hit/n) if n else 0:.0f}%), spanning multiple cell lineages.",
        "direct_evidence", "B", 0, ["SUM:screens"], conf=0.9, unc="low")
    for it in pack.items:
        if it.kind == "context" and len(it.ref.get("screen_ids", [])) >= 2:
            add(f"{g}'s hits concentrate in the '{it.ref['context']}' context "
                f"({len(it.ref['screen_ids'])} screens).",
                "indirect_evidence", "B", 1, [it.evidence_id], conf=0.75)

    # C. non-hit contrast (Q2) — matched same-cell-line hit vs non-hit
    hit_by_cell: dict[str, list] = {}
    for s in hits:
        if s.cell_line:
            hit_by_cell.setdefault(s.cell_line, []).append(s)
    for s in view.nonhit_screens:
        if s.coverage == "FULL" and s.cell_line in hit_by_cell:
            partner = hit_by_cell[s.cell_line][0]
            add(f"In the same cell line ({s.cell_line}), {g} is a hit in screen {partner.screen_id} "
                f"('{partner.phenotype}', condition {partner.cond_txt}) but not in screen "
                f"{s.screen_id} ('{s.phenotype}', condition {s.cond_txt}), so its dependency is "
                f"condition- and readout-specific rather than constitutive.",
                "inference", "C", 1, [f"SCR:{partner.screen_id}", f"SCR:{s.screen_id}"], conf=0.7)
    add(f"Non-hit status is only interpretable for FULL-coverage screens ({view.n_full_screens} of "
        f"{n}); HIT_ONLY screens have no non-hit counterfactual for {g}.",
        "direct_evidence", "C", 0, ["SUM:coverage"], conf=0.85, unc="low")

    # D. literature
    for p in view.publications:
        add(f"Publication PMID {p.pmid} ({p.author or 'n/a'}, {p.journal or 'n/a'} {p.year or ''}) is a "
            f"source of {g} screens; {'full text available' if p.has_fulltext else 'abstract only'}.",
            "direct_evidence", "D", 0, [f"PMID:{p.pmid}"], conf=0.85, unc="low")

    # E. relatedness / network (Q3)
    add(f"After a per-partner specificity correction, {g}'s specific relatives number "
        f"{view.validation.get('n_relatives', '?')} "
        f"(Strong {view.validation.get('n_strong', '?')} / Moderate "
        f"{view.validation.get('n_moderate', '?')} / Weak {view.validation.get('n_weak', '?')}); "
        f"common-essential neighbours are reported separately as non-specific.",
        "indirect_evidence", "E", 1, ["SUM:relatives"], conf=0.8)
    strong = [it for it in pack.items if it.kind == "relative"
              and (it.ref.get("tier") in ("Strong", "Moderate"))
              and it.ref.get("specificity_class") == "specific"]
    for it in strong[:12]:
        add(it.text, "indirect_evidence", "E", 1, [it.evidence_id], conf=0.75)

    # G. confounds / QC
    add(pack.by_id().get("SUM:confound", ""), "direct_evidence", "G", 0, ["SUM:confound"],
        conf=0.85, unc="low")
    for s in view.screens:
        if s.gate == "WARN" and s.hit:
            add(f"The {g} hit in screen {s.screen_id} sits on a WARN-gate screen "
                f"({s.gate_detail}), so its fitness signal is low-confidence and should not anchor a "
                f"mechanistic claim on its own.",
                "direct_evidence", "G", 0, [f"HARM:{s.screen_id}", f"SCR:{s.screen_id}"], conf=0.8)

    # Withheld interpretations — HIT_ONLY non-hit counterfactual is undefined
    for s in view.screens:
        if s.coverage == "HIT_ONLY":
            add(f"Interpretation withheld for screen {s.screen_id}: coverage is HIT_ONLY, so absence "
                f"from its hit list does not mean {g} is uninvolved.",
                "direct_evidence", "G", 0, [f"SCR:{s.screen_id}"], conf=0.7,
                withheld=True, reason="HIT_ONLY coverage")

    # H. confidence / limitations
    n_abs = sum(1 for p in view.publications if not p.has_fulltext)
    add(f"Confidence in a guilt-by-association function call for {g} is moderate (multi-channel, "
        f"specificity-corrected); confidence in any specific mechanism is low: {g} is a predicted "
        f"gene, all evidence is {view.organism.lower()}, and {n_abs} of {len(view.publications)} "
        f"source papers are abstract-only.",
        "inference", "H", 0, ["GENE:" + g, "SUM:screens"], conf=0.6)

    # A modest layer-2 hypothesis even in the deterministic artifact (uncited -> flagged for review).
    add(f"Hypothesis: because {g} knockout costs proliferative fitness across unrelated lineages and "
        f"its specificity-corrected neighbours are the cell's growth machinery, {g} plausibly acts in "
        f"or adjacent to the translation/proteostasis axis that supports proliferation.",
        "hypothesis", "H1", 2, [], conf=0.4, unc="elevated")

    return out


# ---------------------------------------------------------------------------
# LLM path
# ---------------------------------------------------------------------------
def _parse_claims(raw: str) -> list[Claim]:
    if not raw or not raw.strip():
        return []
    txt = raw.strip()
    # tolerate ```json fences
    if txt.startswith("```"):
        txt = txt.split("```", 2)[1] if "```" in txt[3:] else txt.strip("`")
        txt = txt[4:] if txt.lower().startswith("json") else txt
    try:
        data = json.loads(txt)
    except json.JSONDecodeError:
        return []
    return claims_from_data(data)


def claims_from_data(data) -> list[Claim]:
    rows = data.get("claims", data) if isinstance(data, dict) else data
    out: list[Claim] = []
    for c in rows or []:
        if not isinstance(c, dict) or not c.get("text"):
            continue
        out.append(Claim(
            text=str(c["text"]), label=str(c.get("label", "hypothesis")),
            evidence_ids=[str(e) for e in c.get("evidence_ids", [])],
            confidence=float(c.get("confidence", 0.5)),
            uncertainty=str(c.get("uncertainty", "none")),
            layer=int(c.get("layer", 0)) if str(c.get("layer", "0")).isdigit() else 0,
            category=str(c.get("category", "")),
            withheld=bool(c.get("withheld", False)),
            withheld_reason=str(c.get("withheld_reason", "")),
        ))
    return out


def synthesize_insights(
    pack: EvidencePack,
    *,
    provider: LLMProvider | None = None,
    external_llm_allowed: bool = False,
    prefer: str | None = None,
    privacy_gate: PrivacyGate | None = None,
) -> list[Claim]:
    """Ask the configured provider for structured insights. Returns [] when the provider
    is the stub (no key) so the caller falls back to the templated path."""
    provider = provider or get_provider(allow_external=external_llm_allowed, prefer=prefer)
    if getattr(provider, "name", "stub") == "stub":
        return []
    # Dossier evidence is PUBLIC; the gate is enforced identically regardless.
    (privacy_gate or PrivacyGate(external_llm_allowed=external_llm_allowed)).check(
        DataSensitivity.PUBLIC, external=True)
    try:
        raw = provider.complete(build_insight_prompt(pack),
                                model="", json_schema=CLAIM_SCHEMA)
    except Exception:
        return []
    return _parse_claims(raw)
