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

DISPATCH_STATE_DB_FILENAME: str = "dispatch_state.db"
"""SQLite file for the born-encrypted /dispatch pending-state store (#1116)."""

DISPATCH_STATE_DB_PATH: str = (
    os.path.join(SESSION_DB_DIR, DISPATCH_STATE_DB_FILENAME) if SESSION_DB_DIR else ""
)
"""Full path to the dispatch pending-state store. Empty if %LOCALAPPDATA% unset.

Deliberately a SEPARATE file from ``sessions.db``: the transcript and the parked
dispatch have different lifetimes (a parked slot is transient and is cleared the
moment the operator answers), and keeping them apart means a durability store can
never put the operator's irreplaceable conversation history at risk.
"""

# ---------------------------------------------------------------------------
# Boot-Phase-3 Handshake
# ---------------------------------------------------------------------------

PA_HANDSHAKE_BACKOFF_BASE_S: float = 1.0
"""Base backoff duration (seconds). Doubles each retry (1s, 2s, 4s, 8s)
until it reaches ``PA_HANDSHAKE_BACKOFF_CAP_S``."""

PA_HANDSHAKE_TIMEOUT_S: float = 30.0
"""Per-attempt socket budget for the Boot-Phase-3 PA handshake.

RAISED 5.0 -> 30.0 (#1353). **This is the constant that fixed four lost battery nights**,
and it is measured: on the verifying run (20260809-140620-bd) the winning handshake took
**16.35 s** of TLS negotiation - more than 3x the old 5 s ceiling. No number of
five-second attempts could ever have completed it; the old config made sixteen and every
one hit the same wall.

The Policy Agent accept loop is SEQUENTIAL and performs the mTLS handshake INLINE
(shared/ipc/vsock.py::accept -> wrap_socket(server_side=True)), so one negotiation
occupies the only accept thread. For roughly the first 90-110 s of a boot the PA is
effectively unreachable, and five seconds does not complete a negotiation against it in
that state. Seen on four consecutive nights as `_ssl.c:989 handshake operation timed
out`, then `WinError 10061` once the backlog filled.

GPU contention EXTENDS that window but does not open it: on the failed
night-20260809-124052 the handshake had already failed nine times over 110 s BEFORE
dispatch-asset generation started at 12:43:25. This is the original #808 cold-load class
with a per-attempt ceiling too tight to clear it - not a new contention class.

Governs the handshake attempt in ALL transport modes (#808): the dev
loopback ``VsockConfig`` AND the production host-mode / guest-mode socket
timeouts. (Before #808 only the dev path used this; a production handshake
attempt rode ``PROMPT_RESPONSE_TIMEOUT_S`` = 180 s per socket op, so one
mute-but-accepting server could stall the whole boot on a single attempt.)
The retry schedule below owns the patience; this bounds one probe."""

PA_HANDSHAKE_BACKOFF_CAP_S: float = 30.0
"""RAISED 15 -> 30 (#1353), in lockstep with the budget.

The cap and the budget together decide the ATTEMPT COUNT. Raising the budget to 600 s
while leaving a 15 s cap produced 44 attempts, and the worst-case wall clock carries
per-attempt time ON TOP of the sleep budget - 44 x 30 s of hung probes is twenty-two
minutes of boot. A 30 s cap fills the same 600 s in ~21 attempts and bounds staleness
after the PA becomes ready to one cap, which is the property this constant exists for.
The healthy path is unchanged: 1, 2, 4, 8 then capped, so a ready PA is still detected
in the first second.

Ceiling for the exponential backoff between handshake attempts (#808). Uncapped
doubling would sleep 64+ s between tail attempts, leaving up to a minute of blindness
to a PA that became ready early in the gap. The cap means a cold-loading PA is caught
within at most one cap of becoming ready, anywhere inside the budget. Registered in
``shared/timeout_registry.py``."""

PA_HANDSHAKE_BUDGET_S: float = 600.0
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
``PA_HANDSHAKE_TIMEOUT_S``-scale probes.

RAISED 180 -> 600 (#1353), and honestly: **this raise is UNPROVEN headroom, not the fix.**
The verifying run (20260809-140620-bd) completed its handshake 113 s in - comfortably
inside the OLD 180 s budget. What actually unblocked it was ``PA_HANDSHAKE_TIMEOUT_S``
(5 -> 30), because the winning attempt needed 16.35 s and could never have fitted a 5 s
ceiling. This budget was raised alongside it on an arithmetic argument about
dispatch-asset generation sharing the window; that argument is sound for
``EXECUTE_RESPONSE_TIMEOUT_S``, which genuinely carries 303 s of generation, but the
handshake never needed the extra patience. Kept as headroom for a boot slower than any
yet measured - do not cite it as the remedy for the four lost nights.

Registered in ``shared/timeout_registry.py``; a registry relation lock binds it to the
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

EXECUTE_RESPONSE_TIMEOUT_S: float = 900.0
"""Receive timeout (seconds) for a dispatch EXECUTE specifically (#1353).

EXECUTE is not one message either. Before the model swap it generates the plan's
dispatch assets on the GPU with the 14B still resident (SEAM A), and only then hands
off and steps aside.

**The per-asset figure, measured on the dispatch path itself:** run
`20260809-140620-bd` generated 8 assets between 14:06:22 and 14:11:25 — **303 s total,
37.9 s each** at 1024x1024 / **18 steps**. Use this figure, not the 59.9 s in
`docs/performance/uc010_dispatch_asset_gen_2026-06-30.json`: that probe measured the
30-step interactive `/illustrate` path, and the dispatch path runs 18. Quoting the
30-step number here overstated this budget's requirement by 58%.

**Why this constant exists at all.** #766 raised the PLAN budget for exactly this
shape and EXECUTE was left on the 180 s per-prompt default, where it silently
became a threshold. Measured across three battery nights:

    2 images  ->  98 s  -> fits 180 s -> GREEN     (night-20260807-195325)
    4 images  -> 142 s  -> plus swap  -> STALLED   (night-20260808-230002)
    4 images  -> 152 s  -> plus swap  -> STALLED   (night-20260809-124052)

Four consecutive nights were lost to that crossing. Nothing regressed; the asset
plan grew. The gateway stopped listening while the AO was still generating and
reported "No response from the Assistant Orchestrator", which reads as a dead
assistant and is not one.

**The number.** B9 plans 8 assets: 8 x 37.9 s = 303 s of generation, plus the swap
hand-off — CONFIRMED end-to-end on 20260809-140620-bd, where the approve request stayed
open the whole time and the dispatch proceeded. The old 180 s default would have hung up
at ~14:09:22, mid-generation. 900 s carries this with real margin (~3x) and stays well
under the per-job run budget. It is NOT unbounded — a site whose plan wants materially
more pictures will cross this too, and that is the honest limit: a request-response
window is the wrong container for work that scales with the asset plan. Raising this
un-breaks the pipeline; it does not settle whether generation belongs inside EXECUTE
at all.
"""
PLAN_RESPONSE_TIMEOUT_S: float = 720.0
"""Receive timeout (seconds) for a dispatch PLAN_REQUEST specifically (#766, raised again #1152).

A PLAN is not one generation — it is the whole plan-time sequence on the 14B
(decompose + criteria + assumptions + build-signal + asset-specs + the job
oracle), ~6-7 chained model calls. Against a freshly swap-back-booted AO (cold
pipeline, empty prefix cache, first-generation warm-up) that legitimately
exceeds the per-prompt 180 s: the 2026-07-07 battery lost B4+B6 on attempt 1
and B6 on attempt 3 to exactly this — the gateway's receive gave up at 180 s
("No response from the Assistant Orchestrator") while the AO was still
generating, and the job STALLED [HARNESS]. #766 raised this to 480 s for that
case.

#1152 (2026-07-29): the requirements-answer re-plan (the operator's FREE-TEXT
answer to the #819 clarifying questions, re-threaded and PLANNED IN FULL) hit
the same "No response" shape against an AO that had booted minutes earlier —
a fresh launcher boot is the same cold-pipeline class #766 describes, just
via a different trigger than a mid-session swap-back. The FIRST PLAN pass
(with clarify on) only runs ONE generation (the sufficiency check), so it
looks fast and gives false confidence the AO is warm; the answer re-plan is
the first call that actually runs the full chain, on a large, image-heavy,
heavily-clarified goal. A live warm-state repro of the same goal+answer took
170 s — comfortably inside the OLD 480 s budget — so this is real cold-boot
headroom, not a goal-size ceiling; raised to 720 s to leave slack a warm
measurement alone cannot rule out. 720 s stays well under the #766-pinned
900 s test ceiling; a genuinely dead AO still fails fast at the per-job
mTLS-verified re-ensure — this budget only stretches the wait for an AO that
is provably alive and working."""

PROMPT_FLOW_PREFLIGHT_BUDGET_S: float = 600.0
"""Aggregate budget (seconds) for the Step-6b boot prompt-flow preflight (#1355).

The preflight sends one real prompt through ``send_prompt`` -> AO and requires a real
answer back. It needs a budget because ``send_prompt`` DOES NOT RAISE on a failed
connect (transport.py: it logs Fail-Closed and returns the request_id anyway), so a
single attempt cannot tell "the prompt path is broken" from "the box was busy" — both
produce zero tokens. Retrying separates them: a misroute stays broken, a saturated GPU
clears.

Sized against the contention that exposed the defect. On run ``20260809-140620-bd`` the
preflight prompt went out at 14:06:22, the same instant an approved dispatch began
generating its assets; generation ran to 14:11:25 — **303 s for 8 assets, 37.9 s each**.
600 s covers that window with margin and leaves room for the cold-14B tail underneath it.

NOT a widening of ``PROMPT_RESPONSE_TIMEOUT_S``. That constant bounds the INTERACTIVE
path, where 180 s is the right answer and a longer wait would be a hang the operator
sits through; ``tests/security/test_execute_budget.py`` locks it deliberately. Each
preflight attempt still rides that 180 s ceiling — this budget only decides how many
attempts a boot is willing to spend.

CONTENTION TOLERANCE, not a cure, and the same shrink condition as the Boot-Phase-3
handshake: retire the retry entirely once dispatch-asset generation moves off the
request thread (#1341 direction 1), after which one attempt suffices. Registered in
``shared/timeout_registry.py``."""

PROMPT_FLOW_PREFLIGHT_BACKOFF_S: float = 5.0
"""Sleep between prompt-flow preflight attempts (#1355).

Deliberately short and flat, not exponential. The failure this retries is a GPU busy
for a bounded, known interval, so there is nothing to back off FROM — the cost of
probing again is one connect attempt, and the attempt itself already carries the
180 s ceiling that does the real waiting. Exponential backoff here would only add
dead time to a boot that is otherwise ready to proceed."""

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
