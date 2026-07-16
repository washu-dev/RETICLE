"""Claim-verification guardrail (stdlib dataclass port of ai/guardrail.py).

Every insight is checked against its cited evidence before it is written:
  - no resolvable citation on a strong (fact-asserting) label -> downgrade to hypothesis
  - support >= 0.7        -> keep (verified)
  - 0.4 <= support < 0.7  -> soften (downgrade label + lower confidence)
  - support < 0.4         -> remove (unsupported)
  - contradiction >= 0.6  -> flag contradiction (surfaced, never dropped silently)

``withheld`` records (explicit refusals mirroring the directionality engine's
"no interpretation without metadata") bypass NLI and are always kept + surfaced.

The NLI scorer is the deterministic lexical estimator ported verbatim; a model-based
verifier can be injected via ``nli=`` when an LLM provider is available. Thresholds
and the decision ladder are identical to the API guardrail so behaviour matches.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

# Labels that assert evidence-backed fact and therefore REQUIRE a citation.
STRONG_LABELS = {
    "direct_evidence",
    "indirect_evidence",
    "inference",
    "literature_supported_inference",
    "computational_result",
}

# The 5-tier public label scheme (ordered weakest-last for downgrade capping).
TIER_ORDER = ["speculation", "hypothesis", "inference", "indirect_evidence", "direct_evidence"]

_STOP = {
    "the", "a", "an", "of", "to", "in", "is", "are", "and", "or", "this", "that",
    "by", "with", "for", "on", "as", "be", "may", "appears", "gene", "genes",
}
_NEG = {"no", "not", "without", "fails", "cannot", "unchanged", "independent",
        "contrary", "contradicts", "contradict", "unaffected", "neither"}


@dataclass
class Claim:
    """A candidate insight before verification (templated or LLM-produced)."""
    text: str
    label: str                       # one of the 5 tiers (see TIER_ORDER)
    evidence_ids: list[str] = field(default_factory=list)
    confidence: float = 0.5
    uncertainty: str = "none"
    layer: int = 0                   # 0 explicit / 1 implicit / 2 hypothesis / 3 validation
    category: str = ""               # A..H, H1..H3, V1.. (taxonomy tag)
    withheld: bool = False           # explicit refusal record
    withheld_reason: str = ""
    trusted: bool = False            # generated deterministically FROM its cited evidence
    #                                  (provenance guaranteed -> low lexical overlap softens,
    #                                  never removes; untrusted LLM claims keep the full gate)


@dataclass
class VerifiedClaim:
    text: str
    label: str
    confidence: float
    evidence_ids: list[str]
    verification_status: str         # verified|partially_supported|unsupported|contradicted|requires_human_review|withheld
    decision: str                    # keep|soften|remove|flag_contradiction|downgraded_no_citation|labeled_unverified|withheld
    support: float
    contradiction: float
    uncertainty: str
    layer: int = 0
    category: str = ""
    withheld: bool = False
    withheld_reason: str = ""


def _content(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in _STOP and len(w) > 2}


def nli_lexical(claim_text: str, evidence_text: str) -> dict[str, float]:
    """Deterministic lexical entailment/contradiction estimate in [0,1].

    Contradiction fires only on a POLARITY MISMATCH — the claim and its evidence overlap
    strongly but disagree in negation (one negated, the other not). When both share the same
    polarity (e.g. a claim that "X is NOT a hit" citing evidence that "X is NOT a hit"), that is
    agreement, not contradiction — a distinction the API guardrail's literature-tuned scorer did
    not need but the screen text here does.
    """
    c = _content(claim_text)
    if not c:
        return {"entailment": 0.0, "contradiction": 0.0, "neutral": 1.0}
    e = _content(evidence_text)
    overlap = len(c & e) / len(c)
    # Polarity check is only reliable on short, focused evidence (a screen/relative/summary
    # snippet). A long abstract almost always contains some negation, so bag-of-words polarity
    # is meaningless there — skip it and score by overlap (the model-based verifier handles
    # contradiction against full text on the LLM path).
    neg_e = bool(_NEG & set(re.findall(r"[a-z']+", evidence_text.lower())))
    neg_c = bool(_NEG & set(re.findall(r"[a-z']+", claim_text.lower())))
    if len(evidence_text) <= 400 and overlap >= 0.5 and (neg_e != neg_c):
        return {"entailment": 0.1, "contradiction": min(1.0, overlap), "neutral": 0.0}
    return {"entailment": round(overlap, 4), "contradiction": 0.0,
            "neutral": round(1 - overlap, 4)}


NliFn = Callable[[str, str], dict[str, float]]


def _carry(claim: Claim) -> dict:
    """Fields carried unchanged from the candidate onto the verified record."""
    return {"layer": claim.layer, "category": claim.category,
            "withheld": claim.withheld, "withheld_reason": claim.withheld_reason}


def verify_claim(
    claim: Claim,
    evidence_by_id: dict[str, str],
    nli: NliFn = nli_lexical,
) -> VerifiedClaim:
    # Explicit refusals are kept + surfaced, not scored.
    if claim.withheld:
        return VerifiedClaim(
            text=claim.text, label=claim.label or "direct_evidence",
            confidence=claim.confidence, evidence_ids=claim.evidence_ids,
            verification_status="withheld", decision="withheld", support=0.0,
            contradiction=0.0, uncertainty=claim.uncertainty, **_carry(claim),
        )

    cited = [evidence_by_id[i] for i in claim.evidence_ids if i in evidence_by_id]

    # Hard gate: a strong (fact-asserting) claim without any resolvable citation is downgraded.
    if claim.label in STRONG_LABELS and not cited:
        return VerifiedClaim(
            text=claim.text, label="hypothesis", confidence=min(claim.confidence, 0.3),
            evidence_ids=claim.evidence_ids, verification_status="unsupported",
            decision="downgraded_no_citation", support=0.0, contradiction=0.0,
            uncertainty="high", **_carry(claim),
        )

    # Hypotheses/speculation may stand without citations but are flagged for review.
    if not cited:
        return VerifiedClaim(
            text=claim.text, label=claim.label, confidence=min(claim.confidence, 0.4),
            evidence_ids=claim.evidence_ids, verification_status="requires_human_review",
            decision="labeled_unverified", support=0.0, contradiction=0.0,
            uncertainty="elevated", **_carry(claim),
        )

    per_item = [nli(claim.text, ev) for ev in cited]
    contradiction = max(s["contradiction"] for s in per_item)
    # Entailment is scored against the UNION of the cited evidence as well as the single best
    # snippet: a synthesis claim that legitimately draws on several sources (e.g. "a hit across
    # screens 345, 1483, 2411 and 2477") should be credited for all of them jointly, not just its
    # best-matching one. Fabrication is still caught — citing real ids while asserting unrelated
    # content overlaps neither the union nor any item.
    support = max(max(s["entailment"] for s in per_item),
                  nli(claim.text, " ".join(cited))["entailment"])

    if contradiction >= 0.6:
        return VerifiedClaim(
            text=claim.text, label="contradiction", confidence=round(contradiction, 4),
            evidence_ids=claim.evidence_ids, verification_status="contradicted",
            decision="flag_contradiction", support=round(support, 4),
            contradiction=round(contradiction, 4), uncertainty="high", **_carry(claim),
        )
    # Trusted (deterministically-derived) claims keep their honest author-assigned label — the
    # NLI is a sanity check, not a re-labeler, because provenance to the cited evidence is
    # guaranteed. Only untrusted (LLM) claims run the keep/soften/remove ladder below.
    if claim.trusted:
        return VerifiedClaim(
            text=claim.text, label=claim.label, confidence=claim.confidence,
            evidence_ids=claim.evidence_ids,
            verification_status="verified" if support >= 0.7 else "provenance_verified",
            decision="keep" if support >= 0.7 else "keep_provenance",
            support=round(support, 4), contradiction=0.0, uncertainty=claim.uncertainty,
            **_carry(claim),
        )
    # Hypotheses / speculation are PROPOSALS, not assertions: their citations mark what motivates
    # them, not what entails them. They are never removed for low lexical entailment (a mechanistic
    # hypothesis legitimately draws on external gene-function knowledge absent from the dossier
    # text); support only tempers confidence, and a genuine contradiction was already flagged above.
    if claim.label in ("hypothesis", "speculation"):
        return VerifiedClaim(
            text=claim.text, label=claim.label,
            confidence=min(claim.confidence, 0.5 if support < 0.4 else claim.confidence),
            evidence_ids=claim.evidence_ids,
            verification_status="hypothesis" if support < 0.4 else "hypothesis_supported",
            decision="keep", support=round(support, 4), contradiction=0.0,
            uncertainty=claim.uncertainty or "elevated", **_carry(claim),
        )
    if support >= 0.7:
        return VerifiedClaim(
            text=claim.text, label=claim.label, confidence=claim.confidence,
            evidence_ids=claim.evidence_ids, verification_status="verified",
            decision="keep", support=round(support, 4), contradiction=0.0,
            uncertainty=claim.uncertainty, **_carry(claim),
        )
    if support >= 0.4:
        return VerifiedClaim(
            text=claim.text, label="literature_supported_inference",
            confidence=round(claim.confidence * 0.7, 4), evidence_ids=claim.evidence_ids,
            verification_status="partially_supported", decision="soften",
            support=round(support, 4), contradiction=0.0, uncertainty="elevated",
            **_carry(claim),
        )
    # Low lexical overlap. A trusted (deterministically-derived) claim is kept on provenance —
    # it was generated FROM the cited evidence, so it cannot be a fabrication; the low overlap
    # only reflects paraphrase. An untrusted (LLM) claim is removed as unsupported.
    if claim.trusted:
        return VerifiedClaim(
            text=claim.text, label=claim.label, confidence=round(claim.confidence * 0.85, 4),
            evidence_ids=claim.evidence_ids, verification_status="provenance_verified",
            decision="keep_provenance", support=round(support, 4), contradiction=0.0,
            uncertainty=claim.uncertainty, **_carry(claim),
        )
    return VerifiedClaim(
        text=claim.text, label="unknown", confidence=0.1, evidence_ids=claim.evidence_ids,
        verification_status="unsupported", decision="remove",
        support=round(support, 4), contradiction=0.0, uncertainty="high", **_carry(claim),
    )
