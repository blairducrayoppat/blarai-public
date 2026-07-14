"""
Gateway-specific constants for the UI Transport Gateway (P1.11).

All hardware/empirical constants are imported from shared.constants.
This module holds UI-gateway-specific defaults only.
"""

from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# Session Database
# ---------------------------------------------------------------------------

_LOCALAPPDATA: str = os.environ.get("LOCALAPPDATA", "")

SESSION_DB_DIR: str = os.path.join(_LOCALAPPDATA, "BlarAI") if _LOCALAPPDATA else ""
"""Directory for the SQLite session database. Empty if %LOCALAPPDATA% unset."""

SESSION_DB_FILENAME: str = "sessions.db"
"""SQLite database file name."""

SESSION_DB_PATH: str = (
    os.path.join(SESSION_DB_DIR, SESSION_DB_FILENAME) if SESSION_DB_DIR else ""
)
"""Full path to the session database. Empty if %LOCALAPPDATA% unset."""

# ---------------------------------------------------------------------------
# Boot-Phase-3 Handshake
# ---------------------------------------------------------------------------

PA_HANDSHAKE_BACKOFF_BASE_S: float = 1.0
"""Base backoff duration (seconds). Doubles each retry (1s, 2s, 4s, 8s)
until it reaches ``PA_HANDSHAKE_BACKOFF_CAP_S``."""

PA_HANDSHAKE_TIMEOUT_S: float = 5.0
"""Per-attempt connection timeout (seconds).

Governs the handshake attempt in ALL transport modes (#808): the dev
loopback ``VsockConfig`` AND the production host-mode / guest-mode socket
timeouts. (Before #808 only the dev path used this; a production handshake
attempt rode ``PROMPT_RESPONSE_TIMEOUT_S`` = 180 s per socket op, so one
mute-but-accepting server could stall the whole boot on a single attempt.)
The retry schedule below owns the patience; this bounds one probe."""

PA_HANDSHAKE_BACKOFF_CAP_S: float = 15.0
"""Ceiling for the exponential backoff between handshake attempts (#808).

Uncapped doubling would sleep 64+ s between tail attempts, leaving up to a
minute of blindness to a PA that became ready early in the gap. Capping at
15 s means a cold-loading PA is caught within at most 15 s of becoming
ready, anywhere inside the budget. Registered in
``shared/timeout_registry.py``."""

PA_HANDSHAKE_BUDGET_S: float = 180.0
"""Aggregate planned-backoff budget (seconds) for the Boot-Phase-3 PA
handshake before Fail-Closed (#808, System Qualities Audit Resilience #2).

Matches the documented cold-load ceiling the rest of the system already
grants the same physical event — a cold Qwen3-14B load can exceed 2 minutes
(``shared.fleet.swap_ops.real_backend_ready(timeout_s)`` = 180 s;
``AoReensurer.boot_wait_s`` = 180 s). The prior aggregate was ~15-18 s
(3 attempts x 5 s + 1+2 s backoff; ~3 s when the socket refuses instantly),
which converted a legitimately cold/slow PA into a hard boot outage needing
a manual relaunch. The wall-clock worst case additionally carries per-attempt
time on top of this budget, bounded by ``PA_HANDSHAKE_MAX_RETRIES`` x
``PA_HANDSHAKE_TIMEOUT_S``-scale probes. Registered in
``shared/timeout_registry.py``; a registry relation lock binds it to the
``real_backend_ready`` ceiling."""


def pa_handshake_backoff_schedule() -> tuple[float, ...]:
    """The planned sleeps between Boot-Phase-3 handshake attempts (#808).

    Exponential from ``PA_HANDSHAKE_BACKOFF_BASE_S`` (doubling), capped at
    ``PA_HANDSHAKE_BACKOFF_CAP_S``, extended until the cumulative sleep
    reaches exactly ``PA_HANDSHAKE_BUDGET_S`` (the final step is trimmed if
    the values ever stop dividing evenly). With the shipped values:
    ``(1, 2, 4, 8, 15 x 11)`` — 15 sleeps summing to 180.0 s, i.e. 16
    attempts.

    Single source of truth for the retry loop
    (``TransportGateway.check_pa_status``) AND the TUI boot banner's
    attempt markers (``BlarAIApp._poll_boot_status``) — the two surfaces
    must never disagree about the schedule (lesson 221: the pair, not the
    values, is what rots).
    """
    delays: list[float] = []
    total = 0.0
    step = PA_HANDSHAKE_BACKOFF_BASE_S
    while total < PA_HANDSHAKE_BUDGET_S:
        delay = min(step, PA_HANDSHAKE_BACKOFF_CAP_S, PA_HANDSHAKE_BUDGET_S - total)
        delays.append(delay)
        total += delay
        step = min(step * 2.0, PA_HANDSHAKE_BACKOFF_CAP_S)
    return tuple(delays)


PA_HANDSHAKE_MAX_RETRIES: int = len(pa_handshake_backoff_schedule()) + 1
"""Total PA handshake attempts before Fail-Closed (derived: one more than
the backoff schedule has sleeps). #808 raised the aggregate budget — this
moved 3 → 16 as a consequence of the 180 s schedule, not as a tuned value;
change the budget/cap/base constants, never this."""

PROMPT_RESPONSE_TIMEOUT_S: float = 180.0
"""Per-prompt receive timeout (seconds) for real inference responses.

Raised 120 -> 180 (#561): a vision turn legitimately chains a VLM load
(~12-16 s), an image describe, and up to two 14B generations (the context-aware
query formulation + the answer). At 120 s a slow-but-valid vision turn tripped
the receive timeout, and the gateway default-denied (fail-closed) a response the
AO was in fact still producing — surfacing to the user as a spurious validation
error. The VLM-eviction memory fix keeps real turns well under this; the larger
budget is headroom so a legitimate vision turn is never mistaken for a hang."""

PLAN_RESPONSE_TIMEOUT_S: float = 480.0
"""Receive timeout (seconds) for a dispatch PLAN_REQUEST specifically (#766).

A PLAN is not one generation — it is the whole plan-time sequence on the 14B
(decompose + criteria + assumptions + build-signal + asset-specs + the job
oracle), ~6 chained model calls. Against a freshly swap-back-booted AO (cold
pipeline, empty prefix cache, first-generation warm-up) that legitimately
exceeds the per-prompt 180 s: the 2026-07-07 battery lost B4+B6 on attempt 1
and B6 on attempt 3 to exactly this — the gateway's receive gave up at 180 s
("No response from the Assistant Orchestrator") while the AO was still
generating, and the job STALLED [HARNESS]. 480 s dominates the measured cold
worst case with headroom; a genuinely dead AO still fails fast at the per-job
mTLS-verified re-ensure — this budget only stretches the wait for an AO that
is provably alive and working."""

# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------

STREAM_TOKEN_BUFFER_LIMIT: int = 4_096
"""Maximum tokens to buffer before circuit-breaker cutoff."""

TOOL_CALL_BUFFER_MAX_TOKENS: int = 512
"""Maximum tokens to buffer for a single tool-call block."""

# ---------------------------------------------------------------------------
# Session Limits
# ---------------------------------------------------------------------------

SESSION_STATE_TTL_S: float = 1_800.0
"""Idle TTL (seconds) for the gateway's session-keyed coordinator state (#801).

1800 s (30 min) is the **LA-DECIDED** idle TTL (2026-07-11, #801 c.1713 —
not a tunable design default). The default for
``TransportGateway(session_state_ttl_s=...)``; in production the launcher
threads the AO-resolved ``[context].session_idle_ttl_s`` over it so ONE
operator-visible knob bounds session-keyed state in both processes (a gate
test locks the two defaults equal). Bounds the entries that are otherwise
cleared only by their completion pop — pending documents awaiting a prompt,
one-shot preview metadata, pending ingest previews, pending dispatch plans —
so an abandoned session cannot hold them until process restart. Swept
opportunistically at each turn start (``send_prompt``): growth requires
activity, so activity-driven sweeping bounds it. ``<= 0`` disables the
reaper (pre-#801 behaviour). Registered in shared/timeout_registry.py."""

SESSION_TITLE_MAX_CHARS: int = 80
"""Maximum characters for any session title (auto-generated or /rename)."""

SESSION_TITLE_PROMPT_CHARS: int = 15
"""Characters of the first user prompt used in an auto-generated title.
The auto-title format is ``<prompt fragment>… · <date>`` — this caps the
fragment. Tunable: raise it for more content context per sidebar entry."""
