"""Insight layer for the single-gene ORCS dossier.

Turns a dossier's assembled evidence (screens + publications + relatedness) into a
*cited insight ledger* — explicit findings, implicit cross-evidence connections,
testable hypotheses, and a validation plan — then renders it into PI-facing views
(a canonical JSONL ledger, a GatewayAI Markdown brief, and an interactive HTML
one-pager with figures).

Design mirrors the sibling ``relatedness/`` package: stdlib-only, one orchestrator
(``pipeline``) plus focused helpers. The scientific-rigor machinery (structured
claim schema + citation/NLI guardrail + privacy gate + provider gateway) is ported
from ``apps/api/reticle_api/ai/`` so the same non-negotiables apply here:

  - no strong claim without a resolvable citation (screen_id / PMID / relative),
  - no interpretation without metadata (refuse + surface, never silently omit),
  - every generated claim is verified against real evidence before it is written.

Public entry points:
  build_evidence_pack   — deterministic evidence pack from the in-memory dossier objects
  run_insights          — full pipeline from the in-memory objects (used by build_gene_dossier)
  run_insights_from_pack— pipeline from a prebuilt pack (used by the standalone CLI)
"""
from __future__ import annotations

from .evidence import EvidenceItem, EvidencePack, build_evidence_pack
from .pipeline import InsightResult, run_insights, run_insights_from_pack

__all__ = [
    "EvidenceItem",
    "EvidencePack",
    "build_evidence_pack",
    "InsightResult",
    "run_insights",
    "run_insights_from_pack",
]
