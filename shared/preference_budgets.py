"""
Operator-preference budget registry — the P4 caps, measured not guessed (#770 M1).
===================================================================================
The pinned operator-preference block (Learning Loops Loop 1, ADR pending at M2)
is injected into EVERY conversational turn's system prompt.  Unbounded memory
injection is self-DoS (OWASP LLM10), so the block carries three hard caps —
count, per-memory chars, and total rendered tokens — all registered here and
gate-locked (``shared/tests/test_preference_budgets.py``), the timeout-registry
pattern applied to token budgets.

THE NUMBERS ARE MEASURED (P9): the #711 prefix-caching A/B S8 scenario
(``docs/performance/prefix_caching_ab_ov2026_2_1_0_2026-07-09_18-02-15.json``,
Arc 140V, OpenVINO GenAI 2026.2.1.0, production shared-pipeline seam) measured
the pinned-block cost curve with prefix caching ON:

  actual tokens   warm-hit TTFT (median)   one-line-edit re-prefill   cold TTFT
       579              421.9 ms                 2790.4 ms             4741.3 ms
      1158              490.8 ms                 4739.1 ms            10302.6 ms
      2382              365.9 ms                10511.4 ms            19837.4 ms
      4764              800.3 ms                21298.2 ms            40957.3 ms

Warm-hit cost is FLAT (~0.4-0.8 s) regardless of block size — the block's
prefill is paid once per session, not per turn.  The binding costs scale
linearly (~4.4 ms/token): the one-line-EDIT re-prefill and the session-cold
first turn.  The cap is chosen where those stay operator-tolerable:

  * 1024 tokens  -> edit ~4.2 s (interpolated), cold ~9 s   <- CHOSEN
  * 2048+ tokens -> edit >9 s, cold >18 s                    (operator-hostile)
  * 512 tokens   -> needlessly tight for a decades-scale preference tier

DETERMINISTIC OFFLINE ESTIMATOR: the budget lock must be testable with no
tokenizer loaded, so the cap is asserted against a documented CONSERVATIVE
estimate — ``ceil(chars / 3.0)``.  English Qwen3 text measures ~3.5-4.2
chars/token (the S8 blocks measured ~4.1), so chars/3.0 OVER-estimates the
token count: a block passing the estimated cap is comfortably under the real
one.  The estimator itself is pinned by test so it cannot drift silently
(coordinator requirement, 2026-07-09).

Governance: NEW/CHANGED budget => update the registry entry + the gate test in
the same change.  Reviewed at the LESSONS quarterly pass alongside the timeout
registry.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

#: Evidence artifact the caps were set from (P9 — measured, not guessed).
S8_EVIDENCE: str = (
    "docs/performance/prefix_caching_ab_ov2026_2_1_0_2026-07-09_18-02-15.json"
    " (results angle S8)"
)

#: Hard cap on the ESTIMATED token count of the fully rendered pinned block
#: (header + every active preference line).  Enforced at the single operator
#: write door (the AO PREFERENCE_WRITE handler refuses a write that would
#: exceed it) and backstopped by deterministic truncation in the renderer.
PINNED_BLOCK_TOKEN_CAP: int = 1024

#: Hard cap on one preference's verbatim body, in characters.  ~500 chars
#: estimates to ~167 tokens — dozens of typical preferences ("call me Blair",
#: "always use metric") fit the block cap with headroom.
PREFERENCE_BODY_MAX_CHARS: int = 500

#: Hard cap on ACTIVE preference rows in the store.  Bounds the store and the
#: /preferences listing independently of the token cap (which remains the
#: binding limit for max-length bodies).
PREFERENCE_MAX_COUNT: int = 64

#: The documented conservative chars-per-token divisor (see module docstring).
TOKEN_ESTIMATE_CHARS_PER_TOKEN: float = 3.0


def estimate_tokens(text: str) -> int:
    """Conservative deterministic token estimate: ``ceil(len(text) / 3.0)``.

    Offline-testable stand-in for the real tokenizer (which is not cheaply
    available in the budget lock's context).  OVER-estimates for English text
    (measured ~3.5-4.2 chars/token on the S8 blocks), so enforcing the cap on
    the estimate keeps the real token count strictly under the cap.  Empty
    text estimates to 0.  Pinned by ``test_preference_budgets.py`` — any
    change to this function must update that lock in the same change.
    """
    if not text:
        return 0
    return math.ceil(len(text) / TOKEN_ESTIMATE_CHARS_PER_TOKEN)


@dataclass(frozen=True)
class BudgetEntry:
    """One registered budget row (mirrors ``shared.timeout_registry.TimeoutEntry``)."""

    name: str        # human name of the budget
    attribute: str   # the constant's name in THIS module (gate cross-checks)
    value: float     # the registered value (the gate asserts == live)
    unit: str        # "tokens" / "chars" / "count"
    surface: str     # which subsystem the budget bounds
    evidence: str    # what the number was set FROM (measured, not guessed)
    rationale: str   # why THIS number
    review: str      # what would let it change


#: The registered preference-budget taxonomy.
REGISTRY: tuple[BudgetEntry, ...] = (
    BudgetEntry(
        name="Pinned preference block token cap (estimated)",
        attribute="PINNED_BLOCK_TOKEN_CAP",
        value=1024,
        unit="tokens",
        surface="AO system-prompt injection (every conversational turn)",
        evidence=S8_EVIDENCE,
        rationale=(
            "S8 ON-curve: warm-hit flat ~0.4-0.8 s at every size; edit "
            "re-prefill ~4.4 ms/token -> ~4.2 s at 1024, >9 s at 2048; "
            "session-cold ~9 s at 1024, >18 s at 2048. 1024 keeps the rare "
            "edit and the once-per-session cold cost operator-tolerable "
            "inside the design's <=1-2k target."
        ),
        review=(
            "Re-measure at the next OpenVINO GenAI upgrade or if the "
            "persistent-KV-cache feature request lands (cold cost would drop "
            "to once-per-boot, loosening the binding constraint)."
        ),
    ),
    BudgetEntry(
        name="Per-preference verbatim body char cap",
        attribute="PREFERENCE_BODY_MAX_CHARS",
        value=500,
        unit="chars",
        surface="knowledge-bank operator_preferences write path",
        evidence=S8_EVIDENCE,
        rationale=(
            "~167 estimated tokens per max-length body: 6 max-length rows or "
            "dozens of typical short preferences fit the 1024-token block cap."
        ),
        review="Raise only with a matching block-cap re-measurement.",
    ),
    BudgetEntry(
        name="Active preference count cap",
        attribute="PREFERENCE_MAX_COUNT",
        value=64,
        unit="count",
        surface="knowledge-bank operator_preferences write path + /preferences listing",
        evidence="frame-size arithmetic: 64 rows x ~600 B ≈ 38 KB < the 64 KB IPC envelope",
        rationale=(
            "Bounds the store and the one-frame PREFERENCE_LIST_RESPONSE "
            "independently of the token cap; the token cap stays the binding "
            "limit for long bodies."
        ),
        review="Raise alongside a chunked listing if the tier ever legitimately outgrows it.",
    ),
)


def registry_attributes() -> set[str]:
    """Names of all registered budget attributes (gate-test helper)."""
    return {entry.attribute for entry in REGISTRY}


__all__ = [
    "S8_EVIDENCE",
    "PINNED_BLOCK_TOKEN_CAP",
    "PREFERENCE_BODY_MAX_CHARS",
    "PREFERENCE_MAX_COUNT",
    "TOKEN_ESTIMATE_CHARS_PER_TOKEN",
    "estimate_tokens",
    "BudgetEntry",
    "REGISTRY",
    "registry_attributes",
]
