"""Privacy gate (stdlib port of ai/privacy.py).

Every LLM payload is tagged ``public`` or ``project_private``; a project-private
payload only reaches an external model with explicit consent. Dossier content
(BioGRID ORCS + PubMed/PMC + NCBI Gene) is entirely PUBLIC, so the gate opens for
insight synthesis once ``external_llm_allowed`` is set — but the chokepoint is kept
here identically so the same policy holds if private data is ever mixed in.
"""
from __future__ import annotations

from enum import Enum


class DataSensitivity(str, Enum):
    PUBLIC = "public"
    PROJECT_PRIVATE = "project_private"


class PrivacyError(RuntimeError):
    """Raised when a payload would violate the data-egress policy."""


class PrivacyGate:
    def __init__(self, external_llm_allowed: bool = False) -> None:
        self.external_llm_allowed = external_llm_allowed

    def check(self, sensitivity: DataSensitivity, *, external: bool) -> None:
        if (
            external
            and sensitivity == DataSensitivity.PROJECT_PRIVATE
            and not self.external_llm_allowed
        ):
            raise PrivacyError(
                "project-private data may not be sent to an external model "
                "(external_llm consent is off)"
            )

    def allows(self, sensitivity: DataSensitivity, *, external: bool) -> bool:
        try:
            self.check(sensitivity, external=external)
            return True
        except PrivacyError:
            return False
