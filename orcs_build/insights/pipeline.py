"""Insight pipeline orchestrator (mirrors relatedness.pipeline.run_relatedness).

Assembles candidate claims (deterministic templated + optional LLM/ingested), verifies
every one against the pack's real evidence ids, drops the unsupported, and packages the
survivors as an ``InsightResult`` that can write the ledger + rendered views.

Provenance is constant across generation paths — the deterministic layer is always present,
so the artifact never regresses to "no insights"; the LLM/ingested layer only adds fluency
and deeper synthesis on top, and is subject to the identical guardrail.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .evidence import EvidencePack, build_evidence_pack
from .guardrail import VerifiedClaim, verify_claim
from .synthesis import claims_from_data, synthesize_insights, templated_insights


@dataclass
class InsightResult:
    pack: EvidencePack
    claims: list[VerifiedClaim]          # survivors (everything not removed)
    provider_name: str
    generated_at: str
    n_dropped: int = 0
    n_deduped: int = 0
    counts: dict = field(default_factory=dict)

    # convenience count accessors used by build_gene_dossier's summary line
    @property
    def n_kept(self) -> int:
        return self.counts.get("keep", 0) + self.counts.get("keep_provenance", 0)

    @property
    def n_softened(self) -> int:
        return self.counts.get("soften", 0)

    @property
    def n_flagged(self) -> int:
        return self.counts.get("flag_contradiction", 0)

    @property
    def n_withheld(self) -> int:
        return self.counts.get("withheld", 0)

    def summary_line(self) -> str:
        return (f"Insights      : {self.n_kept} kept / {self.n_softened} softened / "
                f"{self.n_dropped} dropped / {self.n_flagged} flagged / {self.n_withheld} withheld / "
                f"{self.n_deduped} deduped (source: {self.provider_name})")

    def write(self, outdir: Path, gene: str, generated_at: str) -> list[str]:
        from . import render
        return render.write_all(self, Path(outdir), gene, generated_at)


def _sig(text):
    import re
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 3}


def _dedup(claims):
    """Drop near-duplicate claims within a category (templated vs ingested often overlap),
    keeping the richer version (more citations, then longer text)."""
    kept: list = []
    sigs: list = []
    for c in claims:
        # Withheld (refusal) records are transparency statements about specific screens —
        # never fold them together even when their wording is nearly identical.
        if c.withheld:
            kept.append(c)
            sigs.append(_sig(c.text))
            continue
        cs = _sig(c.text)
        dup = None
        for i, k in enumerate(kept):
            if k.category != c.category or k.withheld != c.withheld or not cs or not sigs[i]:
                continue
            jac = len(cs & sigs[i]) / len(cs | sigs[i])
            if jac >= 0.6:
                dup = i
                break
        if dup is None:
            kept.append(c)
            sigs.append(cs)
        elif (len(c.evidence_ids), len(c.text)) > (len(kept[dup].evidence_ids), len(kept[dup].text)):
            kept[dup] = c
            sigs[dup] = cs
    return kept


def _run(pack: EvidencePack, *, allow_external_llm: bool, prefer, claims_path, generated_at):
    candidates = list(templated_insights(pack))
    provider_name = "deterministic"

    if claims_path:
        data = json.loads(Path(claims_path).read_text(encoding="utf-8"))
        ingested = claims_from_data(data)
        candidates += ingested
        provider_name = f"curated ({len(ingested)} claims)"
    elif allow_external_llm:
        from .provider import get_provider
        provider = get_provider(allow_external=True, prefer=prefer)
        llm = synthesize_insights(pack, provider=provider, external_llm_allowed=True, prefer=prefer)
        candidates += llm
        provider_name = getattr(provider, "name", "?")
        if not llm:
            provider_name += " -> deterministic (no LLM output)"

    evmap = pack.by_id()
    verified = [verify_claim(c, evmap) for c in candidates]

    n_dropped = sum(1 for v in verified if v.decision == "remove")
    non_removed = [v for v in verified if v.decision != "remove"]
    survivors = _dedup(non_removed)
    n_deduped = len(non_removed) - len(survivors)

    # counts reflect the FINAL ledger (post-dedup)
    counts: dict[str, int] = {}
    for v in survivors:
        counts[v.decision] = counts.get(v.decision, 0) + 1

    # stable ordering: by layer, then category, strongest evidence first
    from .guardrail import TIER_ORDER
    tier_rank = {t: i for i, t in enumerate(TIER_ORDER)}
    survivors.sort(key=lambda v: (v.layer, v.category, -tier_rank.get(v.label, 0)))

    return InsightResult(pack=pack, claims=survivors, provider_name=provider_name,
                         generated_at=generated_at, n_dropped=n_dropped, counts=counts,
                         n_deduped=n_deduped)


def run_insights(ex, pubs, gene_info, res, *, allow_external_llm=False, prefer=None,
                 claims_path=None, generated_at="") -> InsightResult:
    """Full pipeline from the in-memory build_gene_dossier objects."""
    pack = build_evidence_pack(ex, pubs, gene_info, res, generated_at)
    return _run(pack, allow_external_llm=allow_external_llm, prefer=prefer,
                claims_path=claims_path, generated_at=generated_at)


def run_insights_from_pack(pack: EvidencePack, *, allow_external_llm=False, prefer=None,
                           claims_path=None, generated_at="") -> InsightResult:
    """Pipeline from a prebuilt pack (standalone / disk mode)."""
    return _run(pack, allow_external_llm=allow_external_llm, prefer=prefer,
                claims_path=claims_path, generated_at=generated_at or pack.generated_at)
