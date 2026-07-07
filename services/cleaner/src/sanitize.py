"""
Adversarial sanitization — Cleaner stage 3 (UC-003, ADR-030 §5).
================================================================
Layer 1 of the mandatory three-layer defense against indirect prompt
injection — probabilistic, never load-bearing alone. Residual risk is
delegated by design to Layer 2 (per-load datamarking + delimiter
neutralization at grounding, ``ContextManager.add_grounded_context``) and
Layer 3 (the action-lock on untrusted content + PGOV output validation),
which fire on every retrieval of this content forever (ADR-031 L4). A miss
here is a degraded-quality event, not a compromise (ADR-023; BUILD_JOURNAL
lesson 13).

REUSE, NOT REINVENTION (the do-not-duplicate-pattern-tables rule):

* The heuristic injection-phrase scan is the gateway document loader's
  ``scan_for_injection`` — the single Layer-2 pattern table in the repo
  (``services/ui_gateway/src/document_loader.py``, ADR-013). One table,
  three consumers (document load, /external paste, ingest clean); a pattern
  added there strengthens all three at once.
* The deterministic forged-delimiter strip is the AO context manager's
  ``_neutralize_delimiters`` — the single Layer-1 implementation
  (``services/assistant_orchestrator/src/context_manager.py``). It is a
  module-private name imported across a service boundary on purpose: the
  alternative (a copied delimiter list) is exactly the drift this repo's
  reuse rule forbids. The regression lock in
  ``services/cleaner/tests/test_clean_text.py`` fails loudly if the AO ever
  renames it.

ORDER MATTERS (and is locked by tests): the scan runs on normalized text
BEFORE the delimiter strip, so the verdict reflects what the document
actually carried — stripping first would hide a forged
``<|GROUNDED_CONTEXT_BEGIN|>`` from the scan and launder the quarantine
verdict. Normalization runs before both, because zero-width characters
inside a trigger phrase are a scanner-evasion vector
(``services/cleaner/src/normalize.py``).
"""

from __future__ import annotations

from dataclasses import dataclass

# Cross-service imports of the canonical primitives (see module docstring).
from services.assistant_orchestrator.src.context_manager import (
    _neutralize_delimiters,
)
from services.ui_gateway.src.document_loader import scan_for_injection


@dataclass(frozen=True)
class SanitizationResult:
    """Outcome of the sanitization stage.

    ``text`` is the delimiter-neutralized content; ``injection_findings``
    are the human-readable descriptions from ``scan_for_injection`` for the
    content AS SUBMITTED (pre-strip), in the scanner's stable order.
    """

    text: str
    injection_findings: tuple[str, ...]


def sanitize_text(normalized_text: str) -> SanitizationResult:
    """Scan *normalized_text* for injection patterns, then strip forged
    delimiters. Deterministic and total; never raises on any string input.
    """
    findings = tuple(scan_for_injection(normalized_text))
    cleaned = _neutralize_delimiters(normalized_text)
    return SanitizationResult(text=cleaned, injection_findings=findings)
