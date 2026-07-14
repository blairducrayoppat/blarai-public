"""Drafting-adapter result contract — the heartbeat's model seam vocabulary (#845 C3, design §3.4).

The C3 design (`docs/research/c3-heartbeat-design-2026-07.md` §3.3 wall 4 / §3.4)
gives the heartbeat exactly one way to reach the 14B: a bounded
``coordinator_draft()`` entry on the Assistant Orchestrator (AO) service object,
which try-acquires the shared single-flight inference lock NON-BLOCKING and
checks POSITIVE 14B residency before generating. This module is that seam's
result vocabulary — pure data, importable from both sides of the seam (the AO
service that produces it and the launcher-side heartbeat cycle that consumes
it) without either importing the other's machinery.

The §3.4 contract, verbatim where it is load-bearing:

  * **Tri-state**: ``drafted`` / ``busy`` / ``not_resident`` — and nothing else.
    ``busy`` means the try-acquire failed (a chat turn or any other generation
    holds the lock): the heartbeat never waits on, never queues behind, and
    never preempts a chat generation — a blocking acquire is the design's
    wall-4 violation. ``not_resident`` means the AO could not POSITIVELY report
    the 14B resident (acquiring the lock is NOT evidence of residency — the
    UC-010 image-generation path can evict the 14B and release the lock with
    the model absent); the adapter **never initiates a load, a reload, an
    eviction, or a swap** — a non-resident 14B is a defer, exactly like a busy
    one. Both defers are NORMAL outcomes recorded in the cycle result, never
    errors.
  * **Structured failure, in-band**: the drafting model path may fail after the
    lock and residency checks pass (a #743-fail-softed grammar leg, a
    generation-layer error, an empty emission). That failure NEVER raises out
    of the seam and never mints a fourth status: it is a ``drafted`` result
    with EMPTY ``text`` and an operator-legible ``reason`` naming the cause.
    Callers must treat ``has_text`` — not the status alone — as "prose is
    available"; design §2 step 9 already requires every draft to have a
    deterministic fallback rendering (facts without prose), so an empty draft
    degrades the cycle's prose, never its correctness.

DORMANCY: pure enum + frozen dataclass with no I/O and no callers in any
production boot path. The AO's ``coordinator_draft()`` (this seam's producer)
is itself uncalled until the heartbeat cycle limb wires it behind
``[coordinator].heartbeat_enabled``. Importing this module arms nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

__all__ = [
    "CoordinatorDraftResult",
    "DraftStatus",
]


class DraftStatus(Enum):
    """The §3.4 tri-state — the complete status vocabulary, by design.

    A fourth status is a contract change, not an extension: the heartbeat's
    step-9 handling (defer vs. record) is written against exactly these three,
    and model-path failure travels in-band as an empty ``drafted`` (module
    docstring). The vocabulary is gate-locked in the seam's tests.
    """

    DRAFTED = "drafted"
    BUSY = "busy"
    NOT_RESIDENT = "not_resident"

    @property
    def deferred(self) -> bool:
        """True when the draft was deferred to a later cycle (busy or
        not-resident) — the two normal, non-error defer outcomes. A
        ``DRAFTED`` result — even an empty fail-softed one — is not a defer:
        the attempt ran and must not be retried this cycle."""
        return self is not DraftStatus.DRAFTED


@dataclass(frozen=True)
class CoordinatorDraftResult:
    """One ``coordinator_draft()`` outcome (#845 C3 limb 5, design §3.4)."""

    status: DraftStatus
    """The tri-state outcome — see :class:`DraftStatus`."""

    text: str
    """The drafted prose (hidden model blocks already stripped). Empty on both
    defer statuses and on an in-band model-path failure (module docstring)."""

    reason: str
    """Operator-legible account of the outcome: why a defer deferred, why an
    empty draft is empty, which fail-soft degradation (if any) applied. Never
    machine-parsed — targeting and gating never read this field."""

    @property
    def has_text(self) -> bool:
        """True iff usable drafted prose is present. THE prose-availability
        check (not ``status`` alone): a fail-softed generation failure is a
        ``DRAFTED`` result with empty text, and its caller renders the
        deterministic fallback instead (design §2 step 9)."""
        return bool(self.text.strip())
