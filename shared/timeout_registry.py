"""
The Timeout Registry — BlarAI's timeout taxonomy in one table (LA-directed 2026-07-07).
========================================================================================
Every timeout in this system was born as a scar: a budget carved out the day an
incident proved a message type's LEGITIMATE worst case diverged from the default
(the 120→180 s vision-turn raise #561; the 480 s dispatch-PLAN budget #766; the
5400→10800 s run budget and the 14400 s per-task ceiling #757). Until this file,
that taxonomy was invisible — discoverable only constant by constant, docstring
by docstring, and drift between siblings went unnoticed (the registry's own
seeding inventory caught ``monitor.py``'s stale 5400 default the same evening
the harness moved to 10800).

This module is the SINGLE TABLE: message/operation type → budget → the incident
that justified it → the review trigger. It is a REGISTRY, not a config source —
the live constants stay where their consumers live; the standing gate
(``tests/integration/test_timeout_registry.py``) cross-checks every entry
against its live value, so the table can never rot into documentation-fiction
(the C14 class). A production timeout that is neither REGISTERED nor on the
explicit BACKLOG fails the discovery lock — that is the "monitor for new entry
needs" control.

Governance (the LA-directed process, tracked on the registry ticket):
  * NEW/CHANGED timeout ⇒ register it in the same change (the gate enforces
    presence; the review enforces quality).
  * The QUARTERLY review (rides the LESSONS.md consolidation cadence) walks the
    table asking, per entry: is the incident still the binding rationale? can
    the budget SHRINK (measured, not guessed)? can the timeout be RETIRED
    (replaced by an event/health signal — the best timeout is one that no
    longer exists)? BACKLOG entries get promoted or consciously retired.
"""

from __future__ import annotations

import importlib
import inspect
from dataclasses import MISSING, dataclass, fields as dataclass_fields, is_dataclass
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class TimeoutEntry:
    """One row of the taxonomy.

    ``module``/``attribute`` locate the LIVE value (the gate resolves and
    compares — an entry that stops matching reality fails the standing gate);
    ``incident`` names what PAID for the number (a ticket, a journal entry, or
    "design" for a value that predates the registry and has never bitten);
    ``review`` states what would justify shrinking or retiring it.

    ``attribute`` forms (#767 backlog promotion, 2026-07-08 — the v1 registry
    resolved module constants only; most of the backlog lived in dataclass
    fields and function-signature defaults, so the resolver grew with them):
      * ``"CONST_NAME"``        — a module-level constant.
      * ``"ClassName.field"``   — a dataclass field's DEFAULT.
      * ``"func_name(param)"``  — a function parameter's DEFAULT.
    """

    name: str            # human name of the message/operation type
    module: str          # importable module holding the live constant
    attribute: str       # the constant's name in that module (see forms above)
    seconds: float       # the registered budget (the gate asserts == live)
    surface: str         # which subsystem waits on it
    role: str            # what the duration DOES (see ROLES) — required, no default
    incident: str        # what paid for this number
    rationale: str       # why THIS number (the legitimate worst case)
    review: str          # what would let it shrink or be retired
    #: Attributes of OTHER registered durations this one must strictly exceed.
    #: Empty means "no declared relation", which is a claim of independence, not
    #: an absence of thought — see the ROLES/relations note below.
    must_exceed: tuple[str, ...] = ()


#: What a duration DOES — the closed vocabulary for ``TimeoutEntry.role`` (#1366).
#:
#: Before this field the registry knew 64 numbers and could not answer the one question that
#: kept costing runs: *is this window longer than the thing it observes?* Three inversions were
#: found by accident on 2026-08-09 alone (#1353, #1359, #1366), all derivable by arithmetic from
#: values already in this table. The role is what makes a mechanical sweep for the REMAINING
#: undeclared pairs tractable: only an outer (``watchdog``/``budget``) sitting over an inner
#: (``judge``/``probe``) on the same surface can produce the failure, so the pair space collapses
#: from "every constant against every other" to a reviewable handful.
#:
#: Choose by FUNCTION, never by magnitude — a 15 s probe and a 15 s grace are different animals.
ROLES: frozenset[str] = frozenset(
    {
        # The authoritative verdict-maker for a phase. When THIS fires, the component that owns
        # the phase declares it failed, and downstream behaviour (a retry, a classification, an
        # error path) is gated on that verdict. Pre-empting a judge does not just end the phase
        # early — it makes everything conditioned on the verdict unreachable. That is #1366.
        "judge",
        # An AGGREGATE allowance spanning several attempts or phases: time granted to a run, a
        # task, a wave. It is SPENT, not raced, and it must always exceed one attempt.
        "budget",
        # A single "is anyone there / did it start" check. Bounds ONE attempt and expects to be
        # retried. #1353 is what happens when a probe is sized as if it were a judge.
        "probe",
        # A delay BETWEEN attempts — sleep, retry interval, poll cadence. It does not bound work;
        # it spaces it, and it is the one role that legitimately sits inside everything.
        "backoff",
        # A resolution / staleness / freshness threshold: how old a signal may be before it is
        # disbelieved. Not a deadline for work at all, which is exactly why #1359's 300 s
        # freshness window read as harmless while it silently discarded an 8-hour envelope.
        "grain",
        # An OUTER liveness window observing a phase it does NOT own, firing when a signal goes
        # quiet. The least-informed judge in the room. A watchdog must outlast every legitimately
        # silent phase beneath it, or the phase must emit a heartbeat (lesson 221's own remedy).
        "watchdog",
    }
)

#: The registered taxonomy. Ordered by surface, then by budget.
REGISTRY: tuple[TimeoutEntry, ...] = (
    TimeoutEntry(
        name="Standing-gate parallel group (one pytest process of the fast form)",
        module="scripts.run_standing_gate",
        attribute="GATE_TIMEOUT_S",
        seconds=7200.0,
        surface="scripts/run_standing_gate.py — developer tool, waits on each concurrent group; nothing at runtime waits on it",
        role="budget",
        incident="#1707 — the independent review found a hung group hung the whole gate forever with no signal; the slowest measured group is about 11 minutes",
        rationale="Ten times the slowest group measured in the parallel runs (668 s at 6 groups) and about five times the sequential gate (1448 s): generous because the only thing that ends a hang is this number, and a false kill costs a full re-run.",
        review="Shrink to about three times the slowest group once 20 or more instrument-grade parallel runs exist; retire it if the runner gains a per-group stall signal (a log silent for N minutes, as scripts/gate_timing_runner.py has).",
    ),
    TimeoutEntry(
        name="Audit chain verify-on-load (boot path, both production constructors)",
        module="shared.security.audit_log",
        attribute="AUDIT_BOOT_VERIFY_BUDGET_SECONDS",
        seconds=15.0,
        surface="PolicyAgentService._build_audit_log + AssistantOrchestrator._build_ingest_audit_log — the complete active-segment verification that refuses a tampered chain instead of extending it",
        role="budget",
        incident="#1543 / claim-register row 29 — AuditLog.verify() had no production caller, so _load_existing restored the chain head from the last record on disk without recomputing a hash or checking a signature. The chain was tamper-EVIDENT but not tamper-REFUSING. This budget is what makes running the check at boot affordable enough that nobody switches it off.",
        rationale="MEASURED, not chosen: 100 isolated tpm_signer.verify() calls on the Arc 140V host (2026-09-17) gave min 6.78 ms against a 447% spread, so 13 ms is the worst-case shoulder rather than the median (the median is polluted by scheduling outliers to 63 ms). The cost is chip-bound, not CPU-bound. This budget is NOT enforced as a deadline — a slow machine must not fail to boot. It is enforced structurally: PRODUCTION_MAX_ACTIVE_RECORDS (1,000) x AUDIT_VERIFY_WORST_CASE_SECONDS_PER_RECORD (0.013) = 13.0 s <= 15.0 s, asserted by tests/security/test_audit_verify_budget.py, so the record ceiling cannot be raised without re-measuring. CORRECTION (#1543 review finding 7): earlier text here claimed verify(full=True) runs at a ceremony; it does not -- no production caller exists, the exhaustive walk is unscheduled, and the coverage argument rests on the boot-time anchor check. Rejected alternative: keep ADR-029's 100,000 ceiling and verify only a bounded TAIL of the active segment — a check that skips records is a check an attacker appends past. Verification stays COMPLETE and the segment is bounded instead. Full conditions: docs/performance/audit_chain_verify_cost_2026-09-17_22-50-00.json.",
        review="RE-MEASURE before changing either side of the inequality; the per-record figure is hardware-bound and a TPM or firmware change moves it. The real chain held 33 records after thirteen months, so this budget has never been approached — but #1542 writes a receipt for EVERY verdict at both doors, which is the change that will make the chain grow fast, and this row should be re-read the day that lands. RETIRE only if per-record signature verification stops being the dominant cost (e.g. a batched or aggregate signature scheme), which would remove the reason the ceiling exists.",
    ),
    TimeoutEntry(
        name="PA handshake (per connection attempt)",
        module="services.ui_gateway.src.constants",
        attribute="PA_HANDSHAKE_TIMEOUT_S",
        seconds=30.0,
        surface="ui_gateway → Policy Agent (Boot-Phase-3, ALL transport modes since #808)",
        role="probe",
        incident="design; scope widened at #808 — production attempts previously rode PROMPT_RESPONSE_TIMEOUT_S (180 s) per socket op, so one mute-but-accepting server could stall the whole boot inside a single attempt",
        rationale="'Is anyone there?' - bounds ONE probe; the PA_HANDSHAKE_BUDGET_S row owns the patience (the L221 window/budget pair: per-attempt rides INSIDE the aggregate, never over it). RAISED 5 -> 30 (#1353), and THIS ROW IS THE FIX for the four lost battery nights - MEASURED, not argued: on the verifying run 20260809-140620-bd the winning handshake took 16.35 s of TLS negotiation, more than 3x the old 5 s ceiling, so no number of 5 s attempts could ever have completed it (the old config made sixteen and every one hit the same wall). The PA accept loop is SEQUENTIAL and does the mTLS handshake INLINE (shared/ipc/vsock.py::accept -> wrap_socket(server_side=True)), so one negotiation owns the only accept thread, and for roughly the first 90-110 s of a boot the PA is effectively unreachable.",
        review="DO NOT SHRINK BACK TO ~5 s - an earlier version of this row said to, on the theory that the ceiling was pure contention tolerance, and that theory is refuted: on the FAILED night-20260809-124052 the handshake had already failed nine times over 110 s BEFORE dispatch-asset generation started at 12:43:25. GPU contention extends the unreachable window; it does not open it. This is the original #808 cold-load class and the 30 s must survive #1341 direction 1. A shrink needs a MEASURED cold-boot negotiation time, not the absence of contention. Retire only with the retry loop.",
    ),
    TimeoutEntry(
        name="PA handshake aggregate backoff budget (Boot-Phase-3)",
        module="services.ui_gateway.src.constants",
        attribute="PA_HANDSHAKE_BUDGET_S",
        seconds=600.0,
        surface="ui_gateway → Policy Agent (check_pa_status retry loop; launcher step 6a + TUI boot banner both ride it)",
        role="budget",
        must_exceed=("PA_HANDSHAKE_TIMEOUT_S",),
        incident="#808 (System Qualities Audit, Resilience #2) — the ~15-18 s aggregate (3 attempts x 5 s + 1+2 s backoff; ~3 s when the socket refuses instantly) latched StartupState.FAILED while the same codebase documents a cold 14B load exceeding 2 minutes — a cold/slow PA became a hard outage needing a manual relaunch",
        rationale="RAISED 180 -> 600 (#1353) - and the verifying run says this raise was NOT the remedy. On 20260809-140620-bd the handshake succeeded 113 s in, comfortably inside the OLD 180 s budget; what unblocked it was the PA_HANDSHAKE_TIMEOUT_S row (5 -> 30), because the winning attempt needed 16.35 s. This budget was raised in the same change on an arithmetic argument about dispatch-asset generation sharing the window - an argument that is sound for EXECUTE_RESPONSE_TIMEOUT_S, which genuinely carries 303 s of generation inside one request, but that the handshake never needed. Kept as headroom against a boot slower than any yet measured. It is UNPROVEN headroom and must not be cited as the fix for the four lost nights; the schedule stays 1,2,4,8 then capped so the healthy path is still instant, and config absence still fails immediately.",
        review="A shrink back toward 180 s is defensible on the evidence (the measured need was 113 s) and costs nothing but headroom - do it only alongside a second cold-boot sample, and NEVER together with a PA_HANDSHAKE_TIMEOUT_S shrink, which is the row that actually holds this door open. RETIRE if the PA ever emits a readiness event: an event beats a deadline, and this whole class disappears with it.",
    ),
    TimeoutEntry(
        name="PA handshake backoff cap (tail probe interval)",
        module="services.ui_gateway.src.constants",
        attribute="PA_HANDSHAKE_BACKOFF_CAP_S",
        seconds=30.0,
        surface="ui_gateway → Policy Agent (check_pa_status backoff schedule)",
        role="backoff",
        incident="design (#808) — uncapped doubling inside the new 180 s budget would sleep 64+ s between tail attempts, leaving up to a minute of blindness to an already-ready PA",
        rationale="Worst-case staleness after the PA becomes ready: a cold boot is detected within one cap anywhere inside the budget; small enough to stay responsive, large enough not to hammer a loading service. RAISED 15 -> 30 (#1353) IN LOCKSTEP with the budget: cap and budget together fix the attempt count, and 600 s at a 15 s cap produced 44 attempts whose worst-case wall clock (per-attempt time rides ON TOP of the sleep budget) was ~22 minutes of boot. At 30 s the same budget is ~25 attempts.",
        review="Tune with the budget row (the schedule derives from base/cap/budget together); retires with the polling loop if a readiness event lands.",
    ),
    TimeoutEntry(
        name="Prompt/response (the default per-message receive)",
        module="services.ui_gateway.src.constants",
        attribute="PROMPT_RESPONSE_TIMEOUT_S",
        seconds=180.0,
        surface="ui_gateway → AO (every framed message unless overridden)",
        role="judge",
        incident="#561 — a legitimate vision turn (VLM load + describe + two 14B generations) tripped the old 120 s and was fail-closed as a spurious validation error",
        rationale="Headroom over the slowest LEGITIMATE single turn (the vision chain) — a claim now falsified for one path, see review.",
        review=(
            "MEASURED 2026-08-08 (#1341): the APPROVE turn rides this default and is NOT bounded by "
            "it. Approving a dispatch triggers synchronous dispatch-asset generation on the AO's own "
            "thread — measured on battery run 20260808-160538-bd: 12.0 s pipeline load + 25.6 s "
            "inference at 1024x1024/18 steps = ~38 s PER ASSET, and B9 declares 8, so ~420 s of "
            "continuous GPU work. A live mTLS probe during that window returns `timeout`: the service "
            "is BLOCKED, not absent. 420 s against a 180 s budget is a deterministic loss, not a race "
            "— B9 has never once completed and both prior investigations blamed AO lifecycle instead. "
            "Note the asymmetry this exposes: PLAN_RESPONSE_TIMEOUT_S is 720 s for a turn that "
            "generates NOTHING, while APPROVE — which generates every asset — inherits 180 s. "
            "DELIBERATELY NOT RAISED HERE: this constant bounds EVERY framed message, and widening it "
            "to fit one path's unbudgeted work would blunt failure detection everywhere to hide a "
            "defect that belongs off the request thread (#1341 direction 1). The measurement is "
            "recorded so the next actor decides on data rather than on the 2026-07-07 vision-turn "
            "rationale, which never anticipated this workload. Original review stands: shrink if the "
            "VLM-eviction fix keeps real turns well under it across a measured sample; any shrink must "
            "re-run the vision-turn worst case."
        ),
    ),
    TimeoutEntry(
        name="Dispatch EXECUTE (asset generation + the swap hand-off)",
        module="services.ui_gateway.src.constants",
        attribute="EXECUTE_RESPONSE_TIMEOUT_S",
        seconds=900.0,
        surface="ui_gateway -> AO (EXECUTE_REQUEST only)",
        role="judge",
        incident=(
            "#1353 - FOUR consecutive battery nights lost, and the asymmetry was already "
            "written down in this very file: 'PLAN_RESPONSE_TIMEOUT_S is 720 s for a turn "
            "that generates NOTHING, while APPROVE - which generates every asset - inherits "
            "180 s.' That entry deliberately did not raise the SHARED constant, correctly, "
            "because it bounds every framed message. This is the other move it pointed at: "
            "EXECUTE gets its own budget, exactly as #766 gave PLAN one. Measured across "
            "three nights, and it is a THRESHOLD rather than a break - nothing regressed, the "
            "asset plan grew: 2 images = 98 s fits 180 s and the night went GREEN "
            "(night-20260807-195325); 4 images = 142 s and 152 s plus the swap exceeded it "
            "and both STALLED [HARNESS] (night-20260808-230002, night-20260809-124052). The "
            "gateway stopped listening while the AO was still generating and reported 'No "
            "response from the Assistant Orchestrator', which reads as a dead assistant and "
            "is not one - it cost six wrong diagnoses before the arithmetic was checked."
        ),
        rationale=(
            "8 assets x 59.9 s measured per image on this hardware "
            "(docs/performance/uc010_dispatch_asset_gen_2026-06-30.json, 30 steps, Arc 140V) "
            "= 479 s of generation, plus the swap hand-off. 900 s carries B9's declared plan "
            "with real margin and stays far under the per-job run budget. NOT unbounded, and "
            "the limit is honest: a plan wanting materially more pictures crosses this too."
        ),
        review=(
            "SHRINK when dispatch-asset generation moves off the request thread (#1341 "
            "direction 1) - then EXECUTE is a hand-off again and belongs near the per-prompt "
            "default. RAISE only against a measured asset plan larger than 8. Raising this "
            "un-breaks the pipeline; it does not settle whether generation belongs inside a "
            "request-response window at all, and this entry should not be read as deciding "
            "that it does. Re-measure per-image cost at any image-model or step-count change."
        ),
    ),
    TimeoutEntry(
        name="Dispatch PLAN (the plan-time 14B sequence)",
        module="services.ui_gateway.src.constants",
        attribute="PLAN_RESPONSE_TIMEOUT_S",
        seconds=720.0,
        surface="ui_gateway → AO (PLAN_REQUEST only)",
        role="judge",
        must_exceed=("PROMPT_RESPONSE_TIMEOUT_S",),
        incident="#766 — a PLAN (~6 chained generations) against a cold just-swapped-back AO legitimately exceeded 180 s; the gateway hung up mid-generation and B4/B6 STALLED [HARNESS] (2026-07-07, two instances). #1152 (2026-07-29) — the SAME shape recurred on the requirements-answer re-plan (the first FULL-chain PLAN call; the initial pass with clarify on only runs one generation) against an AO that had booted minutes earlier — a fresh boot is the same cold-pipeline class, a different trigger than a swap-back. A live warm-state repro of the same goal+answer measured 170 s, well inside the old 480 s, so the failure was cold-boot headroom, not goal size. #1069 batched-S3 ceremony (2026-07-29) — the genuine fresh-boot timing this entry asked for arrived: cold worst-case PLAN INCLUDING an S3-F exam-repair round measured 195.5 s, 27% of budget (docs/performance/coverage_gate_cold_plan_timing_2026-07-29.json).",
        rationale="Dominates the measured cold worst case with real slack a warm measurement alone cannot rule out; the per-job mTLS re-ensure is the fast liveness gate, so this only ever waits on a provably-alive AO.",
        review="Cold-boot latency now has ONE direct measurement (195.5 s, worst shape with a repair round — n=1 by construction, one cold slot per boot). A 720→480 shrink (2.4× measured headroom) stays open pending a second cold sample and an 8-task-shape timing (#1152's original class); retire if the PLAN ever streams progress (an event beats a deadline).",
    ),
    TimeoutEntry(
        name="Boot prompt-flow preflight aggregate budget (Step 6b)",
        module="services.ui_gateway.src.constants",
        attribute="PROMPT_FLOW_PREFLIGHT_BUDGET_S",
        seconds=600.0,
        surface="launcher step 6b -> ui_gateway -> AO (_run_uat2_prompt_flow_preflight)",
        role="budget",
        must_exceed=("PROMPT_FLOW_PREFLIGHT_BACKOFF_S",),
        incident=(
            "#1355 - the preflight reported 'passed OK' 11 ms after 'send_prompt: connect "
            "failed - Fail-Closed', on run 20260809-140620-bd at 14:09:22. It wrapped the "
            "round-trip in try/except and asserted NOTHING about what came back: "
            "send_prompt does not raise on a failed connect (it logs and returns the "
            "request_id), so 0 tokens + a default-denied PGOV lookup + an empty response "
            "raised no exception and scored PASS. The gate whose stated purpose is catching "
            "a host-mode PROMPT_REQUEST misroute AT BOOT could not have caught one - a "
            "misroute produces that exact signature. Found while scoring the #1353 fix, in "
            "the log of the run that proved it."
        ),
        rationale=(
            "This budget exists because the ASSERTION needed a companion. Asserting the "
            "round-trip without retrying converts every busy box into a boot failure - "
            "#1353's failure shape (a startup deadline tearing down a live assistant) "
            "arriving from a new direction. Retrying is also what makes the assertion "
            "DIAGNOSTIC rather than merely strict: a misroute stays broken across attempts, "
            "contention clears, and one attempt cannot tell them apart because both return "
            "zero tokens. Sized on the collision that exposed it - the preflight prompt went "
            "out at 14:06:22 as an approved dispatch began generating, and generation ran to "
            "14:11:25: 303 s for 8 assets, 37.9 s each, a third independent confirmation of "
            "the 38 s/asset figure in the PROMPT_RESPONSE_TIMEOUT_S row. 600 s covers that "
            "with margin plus the cold-14B tail underneath. Each attempt still rides the "
            "180 s PROMPT_RESPONSE_TIMEOUT_S ceiling - this decides only how many attempts a "
            "boot will spend, and deliberately does NOT widen the interactive path."
        ),
        review=(
            "RETIRE the retry entirely once dispatch-asset generation moves off the request "
            "thread (#1341 direction 1) - with no contention one attempt suffices and this "
            "row goes with it. The ASSERTION must survive that retirement: it is the actual "
            "fix, and the budget is only tolerance for a symptom. Same shrink condition as "
            "PA_HANDSHAKE_BUDGET_S; if the two ever disagree about that condition, one of "
            "them has rotted."
        ),
    ),
    TimeoutEntry(
        name="Boot prompt-flow preflight inter-attempt sleep",
        module="services.ui_gateway.src.constants",
        attribute="PROMPT_FLOW_PREFLIGHT_BACKOFF_S",
        seconds=5.0,
        surface="launcher step 6b (_run_uat2_prompt_flow_preflight retry loop)",
        role="backoff",
        incident="design (#1355) - the companion to the budget row; no incident of its own.",
        rationale=(
            "Flat and short, NOT exponential, and the difference is deliberate. The PA "
            "handshake backs off exponentially because it probes a service that may be "
            "seconds or minutes from ready. This retries a GPU busy for a bounded, already-"
            "known interval, and each attempt ALREADY carries the 180 s per-prompt ceiling "
            "that does the real waiting - so exponential growth here would add dead time to "
            "a boot otherwise ready to proceed, and buy nothing."
        ),
        review=(
            "Retires with the retry loop (#1341 direction 1). Do not 'align' it with the "
            "handshake schedule: the shapes differ because the waits differ."
        ),
    ),
    TimeoutEntry(
        name="Fleet per-task ceiling (one run-fleet task)",
        module="shared.fleet.swap_ops",
        attribute="TASK_TIMEOUT_S",
        seconds=14400.0,
        surface="swap driver → run-fleet subtree",
        role="budget",
        incident="#757 — the old 3600 s EQUALLED one candidate's 60-min budget (zero headroom); the actual night-2 killer was the run budget, but the ceiling was rewritten to dominate the legitimate worst case",
        rationale="≥ 3 candidates × 60 min + reviews (~3.5 h); the backstop for the budget-disabled path — the run budget and run-fleet's idle-detection are the binding bounds.",
        review="Shrink if candidate counts or MaxRunMinutes shrink; retire in favor of the budget watchdog if budget-disabled runs are ever forbidden.",
    ),
    TimeoutEntry(
        name="Fleet overall-run budget (config default)",
        module="tools.dispatch_harness.config",
        attribute="_DEFAULT_RUN_BUDGET_S",
        seconds=10800.0,
        surface="battery harness monitoring default (mirrors [fleet_dispatch].swap_run_budget_s)",
        role="budget",
        incident="#757 — 5400 s was sized to pre-plan-graph runs (~50 min); a 5-task battery job's BUILDS alone measured 74-79 min, so the budget tree-killed the final acceptance task on B4+B6 (night-2)",
        rationale="Measured build phase + a full worst-case acceptance task; an abort bound, not a wait — healthy runs finish in 45-95 min.",
        review="Re-measure whenever plan shapes change (the lesson-195 era-rot class); the TOML is the SSOT — this default must track it.",
    ),
    TimeoutEntry(
        name="Vikunja bridge call",
        module="shared.fleet.vikunja_bridge",
        attribute="CALL_TIMEOUT_S",
        seconds=2.0,
        surface="fleet → local Vikunja HTTP",
        role="probe",
        incident="design (never bitten)",
        rationale="A localhost HTTP call to a lightweight server; anything slower is effectively down and the bridge is fail-soft.",
        review="Stable; retire with the bridge if ticket-posting ever moves in-process.",
    ),
    TimeoutEntry(
        name="Web search (Kagi, per request)",
        module="services.assistant_orchestrator.src.websearch.live_adapter",
        attribute="DEFAULT_SEARCH_TIMEOUT_S",
        seconds=20.0,
        surface="AO → the one governed egress door",
        role="judge",
        incident="design (egress dormant until the ADR-027 Am.1 ceremony)",
        rationale="A remote API call on the only network path; generous for search, tight enough that a dead endpoint fails a turn fast.",
        review="Re-measure at go-live against real Kagi latency; the go-live tripwire (gov-pf-007) already forces a reviewed baseline refresh.",
    ),
    # ---- promoted from the BACKLOG (#767 item 1, 2026-07-08) -----------------
    TimeoutEntry(
        name="Fleet queue write (one enqueue subprocess)",
        module="shared.fleet.dispatch",
        attribute="FleetDispatchConfig.enqueue_timeout_s",
        seconds=30.0,
        surface="AO dispatch → pwsh queue-write subprocess",
        role="judge",
        incident="design (#670 dispatch build; never bitten)",
        rationale="A local file write through a pwsh child; anything slower is a wedged shell, and the dispatch fails closed with the stderr.",
        review="Shrinkable if enqueue latency is ever measured; retire if the queue write moves in-process.",
    ),
    TimeoutEntry(
        name="OVMS model-up wait (post start-llm)",
        module="shared.fleet.swap_ops",
        attribute="real_wait_ready(timeout_s)",
        seconds=240.0,
        surface="swap driver → OVMS :8000 local socket",
        role="probe",
        incident="#747 — cold-cache 30B loads needed headroom over the original wait; start-llm -Force is the authoritative readiness gate, this is the belt",
        rationale="Covers a cold-cache 30B load behind the authoritative start-llm block; a socket probe, not the primary wait.",
        review="Shrink if start-llm's own exit-0 contract makes this belt redundant across a measured sample; retire with an OVMS readiness event.",
    ),
    TimeoutEntry(
        name="AO relaunch readiness (post swap-back)",
        module="shared.fleet.swap_ops",
        attribute="real_backend_ready(timeout_s)",
        seconds=180.0,
        surface="swap driver → AO :5001 (stable-accepts + process-alive health probe)",
        role="probe",
        incident="#750 fix 1 — a bare create_connection reported a bind-then-die launcher as up (liveness, not health) and a four-job cascade followed; the probe now requires several stable accepts + a live launcher process",
        rationale="A cold 14B load can exceed 2 minutes; the probe must outlast the legitimate cold boot, and the in-flight guard (#758/L213) owns respawn patience.",
        review="Shrink once cold 14B relaunch latency is measured across campaign swap-backs; the battery's per-job re-ensure is the second net.",
    ),
    TimeoutEntry(
        name="Guest oracle pytest run (guest-side bound)",
        module="shared.fleet.guest_oracle",
        attribute="execute_snapshot(timeout_s)",
        seconds=600.0,
        surface="guest executor → python -m pytest over the shipped snapshot (DORMANT until the #744 ceremony)",
        role="judge",
        incident="design (#744 — dormant path, no live run yet)",
        rationale="Bounds a hostile/looping oracle inside the guest; a job oracle is seconds, not minutes — this is an abort bound with wide margin.",
        review="Re-measure from the first live guest-oracle.json runs; must stay under the transport round-trip budget (see the 630 s row).",
    ),
    TimeoutEntry(
        name="Import-contract probe (#822 layout gate)",
        module="shared.fleet.swap_ops",
        attribute="IMPORT_PROBE_TIMEOUT_S",
        seconds=120.0,
        surface="swap driver finish-line layout gate → import_probe.py / node ESM probe over the integrated tree",
        role="probe",
        incident="design (#822 — the B4/B6/B7 import-contract park class; the probe IMPORTS the coder's first-party modules, whose import-time code could hang)",
        rationale="A probe imports a handful of tiny first-party modules — seconds normally; the bound is the abort ceiling on a coder module with an import-time side effect (a while-True / a blocking call). Strictly cheaper than the 600 s job-oracle grade it precedes, so a generous 120 s never bites a legitimate probe.",
        review="Shrink toward measured probe latency once live import-probe runs record it; retire only if the layout contract ever moves to a static (import-free) resolver.",
    ),
    TimeoutEntry(
        name="Executability floor (#830 G6 wave-final smoke)",
        module="shared.fleet.swap_ops",
        attribute="EXEC_SMOKE_TIMEOUT_S",
        seconds=120.0,
        surface="swap driver wave-final executability floor → boot the integrated app's declared entrypoint (python import + --help / node <entry> --help) after the layout gate, before the job oracle grades",
        role="judge",
        incident="design (#830 — the B7 park class: a Node/web job merged working code but had NO behavioral floor, so a missing module at boot surfaced as an opaque wave-final failure; the floor RUNS the entrypoint, whose import-time / arg-parse code could hang, e.g. an import-time server-start or a while-True)",
        rationale="A boot is seconds; the bound is the abort ceiling on an entrypoint with an import-time side effect. Mirrors the import probe's 120 s and sits well under the 600 s job-oracle grade it precedes — the boot failure is the cheaper signal, run first. The python import check is hang-safe (it never runs __main__), so a bite here is a genuine import-time hang worth surfacing; the --help liveness check rides a smaller local 45 s sub-bound.",
        review="Shrink toward measured boot latency once live exec-smoke runs record it; retire only if a language's boot ever becomes provable without running the entrypoint.",
    ),
    TimeoutEntry(
        name="Multi-page web capture sweep (#1394)",
        module="shared.fleet.swap_ops",
        attribute="WEB_CAPTURE_SWEEP_BUDGET_S",
        seconds=90.0,
        surface="swap driver web console capture → the extra-page loop in capture-web-cdp.mjs, which navigates every delivered page beside the entry point and collects per-page console errors",
        role="budget",
        incident="#1394 — the capture's own ceiling (12 pages x ~11.2 s each, on top of a 20 s entry wait) reaches ~144 s against the 120 s EXEC_SMOKE_TIMEOUT_S that contains it. The two bounds were set by different changes in different repositories with nothing reconciling them; latent at B9's six pages (~77 s) and reliably reachable past ~10.",
        rationale="Sized to FIT: 20 s entry wait + 1.2 s settle + 90 s sweep = 111.2 s, inside the 120 s EXEC_SMOKE_TIMEOUT_S. The failure this prevents is being KILLED rather than being slow — the caller's timeout takes the whole capture, so the per-page error text the sweep exists to collect dies with it, and on 2026-08-15 that text was where the real defect lived (a TypeError breaking contact.html, while the published finding was a favicon 404). A sweep that stops within its budget can name the pages it never reached; a sweep that is killed reports nothing about the pages it had already opened. Passed DOWN to the capture as --sweep-budget-ms rather than duplicated there, so this row is the single owner.",
        review="Raise only together with EXEC_SMOKE_TIMEOUT_S, and only with measured per-page navigation times from a real multi-page delivery — the reconciliation is asserted by test_capture_sweep_budget_fits_exec_smoke, which fails if either moves independently. Shrink once real sweeps record their wall-clock; B9 at 3 pages was nowhere near it.",
    ),
    TimeoutEntry(
        name="Static pre-gate (#831 error-level lint)",
        module="shared.fleet.swap_ops",
        attribute="STATIC_PREGATE_TIMEOUT_S",
        seconds=120.0,
        surface="swap driver per-task static pre-gate → ruff (uv --with) + node --check over the merged task's created source",
        role="judge",
        incident="design (#831 — the cheapest per-task gate; a cold `uv` ruff wheel-pull is seconds and each subprocess needs an abort ceiling)",
        rationale="Bounds the git diff + one ruff run + a handful of `node --check` calls — each cheap (warm ~ms, a cold uv ruff resolve seconds), so 120 s is generous over the cold pull yet an abort ceiling on a wedged tool. Strictly cheaper than the 600 s job-oracle grade / the 120 s import probe it runs before; a missing ruff degrades to skipped, it never waits the ceiling.",
        review="Shrink toward the measured warm cost once live static-pregate runs record it; retire if the gate ever moves in-process (a pure-python AST parse instead of the ruff subprocess).",
    ),
    TimeoutEntry(
        name="Dep-delta git diff (one as-built read; two sequential reads per call)",
        module="shared.fleet.swap_ops",
        attribute="DEP_DELTA_GIT_TIMEOUT_S",
        seconds=30.0,
        surface="swap driver → real_dep_delta git diff subprocess (context packs + the #989 scope-sprawl recorder)",
        role="judge",
        incident="design (#740 W3 as-built delta, a call-site 30 s literal since birth; NAMED + registered at #989, the change that ALTERED the budget — the added-only --diff-filter=A read doubled the call's worst wall to 2×30 s)",
        rationale="One git diff over a small fresh-build repo is milliseconds; 30 s is the abort ceiling on a wedged git. The call runs up to TWO sequential bounded reads (name-only, then added-only), so the worst wall per merged task is 60 s — wholly fail-soft ({} / no `added` key), riding inside the 14400 s per-task ceiling and never on a control path (packs degrade to contract-only; the sprawl recorder records nothing).",
        review="Shrink toward measured diff latency once live pack/sprawl runs record it; retire the second read if the two diffs ever collapse into one --name-status parse (must re-verify the files list stays byte-identical first).",
    ),
    TimeoutEntry(
        name="Guest oracle transport round-trip",
        module="shared.fleet.guest_oracle_transport",
        attribute="ORACLE_TRANSPORT_TIMEOUT_S_DEFAULT",
        seconds=630.0,
        surface="swap driver 3.11 → AF_HYPERV bridge → guest oracle service (DORMANT)",
        role="watchdog",
        must_exceed=("execute_snapshot(timeout_s)",),
        incident="design (#744 transport slice — sized as the guest execution bound + extract/transfer slack)",
        rationale="Must dominate the guest's own 600 s pytest bound so the transport never gives up on a still-legitimate guest run; the bridge subprocess adds its own 15 s spawn margin on top.",
        review="Shrink in lockstep with the guest execution bound after live-ceremony measurements; the dominance relation is gate-locked.",
    ),
    TimeoutEntry(
        name="Guest oracle service-readiness wait (cold guest boot)",
        module="shared.fleet.swap_ops",
        attribute="GUEST_ORACLE_READY_TIMEOUT_S",
        seconds=90.0,
        surface="swap driver teardown → guest oracle vsock listener (port 50002) after a cold ensure-start",
        role="probe",
        incident="night-20260711 — the c.1565 ensure-start reached hypervisor-Running in seconds but the blarai-oracle service needs the Alpine guest to BOOT (~30-60 s+); the transport probed immediately, hit connection-refused, and both jobs' certificates degraded to not-run(guest-unreachable) inside ~40 s VM-up windows",
        rationale="1.5x the observed 60 s upper boot estimate and >2x the proven-insufficient 40 s windows; worst wall ≈ budget + one 20 s probe overrun (110 s), which fits every teardown observer — the monitor's doom window exempts non-CODE phases (and the wait writes a progress line anyway), and the 10800 s run bound keeps ≥75 min headroom on measured 45-95 min runs.",
        review="Shrink toward measured boot-to-listener telemetry from live guest-oracle.json runs; retire if the phase-2 boot/unload overlap (#744 c.1566) hides the boot entirely.",
    ),
    TimeoutEntry(
        name="Guest oracle service-readiness grace (already-running guest)",
        module="shared.fleet.swap_ops",
        attribute="GUEST_ORACLE_READY_GRACE_S",
        seconds=15.0,
        surface="swap driver teardown → guest oracle vsock listener when the guest was ALREADY running",
        role="probe",
        incident="design (#744 night-20260711 sibling of the 90 s cold row; never bitten)",
        rationale="An already-up guest is presumed service-ready — the first probe fires immediately and usually settles it; the short grace only covers an externally started, still-booting guest without spending the full cold budget inside the teardown window.",
        review="Tracks the cold row; both retire with a positive service-readiness event from the guest supervisor.",
    ),
    TimeoutEntry(
        name="Egress fingerprint answer (operator consent)",
        module="services.assistant_orchestrator.src.entrypoint",
        attribute="AssistantOrchestratorEntrypointConfig.egress_fingerprint_timeout_s",
        seconds=120.0,
        surface="AO → operator (fail-closed DENY on expiry)",
        role="judge",
        incident="design (ADR-023 Am.4, #723 rung 3)",
        rationale="A human-answer wait: long enough to read and click, short enough that an absent operator denies the egress rather than parking a turn forever.",
        review="Tune against real operator response times once egress is live; retire only with the consent rung itself.",
    ),
    TimeoutEntry(
        name="Generation approval answer (operator consent, dormant seam)",
        module="services.assistant_orchestrator.src.entrypoint",
        attribute="AssistantOrchestratorEntrypointConfig.generation_approval_timeout_s",
        seconds=120.0,
        surface="AO → operator (fail-closed DENY on expiry; NO live generator tool exists yet)",
        role="judge",
        incident="design (ADR-023 Am.4, #723 rung 2 — dormant seam)",
        rationale="Sibling of the fingerprint wait; same human-scale bound, same fail-closed posture.",
        review="Revisit when a model-initiated generator tool first goes live.",
    ),
    TimeoutEntry(
        name="Battery harness overall-run bound (harness dataclass default)",
        module="tools.dispatch_harness.harness",
        attribute="DispatchHarness.overall_timeout_s",
        seconds=10800.0,
        surface="battery harness → one dispatched run (mirrors the config default row)",
        role="budget",
        incident="#757 — the 5400 s family tree-killed B4/B6's final acceptance task (night-2); the whole family moved to 10800 in the same sweep",
        rationale="Same measured basis as the config-default row: builds alone ran 74-79 min on a 5-task job; an abort bound, not a wait.",
        review="Track the TOML SSOT with the config-default row; re-measure on plan-shape changes (the L195 era-rot class).",
    ),
    TimeoutEntry(
        name="Run-monitor overall bound (monitor dataclass default)",
        module="tools.dispatch_harness.monitor",
        attribute="RunMonitor.overall_timeout_s",
        seconds=10800.0,
        surface="battery monitor → one watched dispatch (dormant default; production callers pass the config value)",
        role="budget",
        incident="#757 family — RECONCILED 2026-07-08: the registry's own seeding inventory caught this default still at the pre-#757 5400 while every sibling had moved to 10800 (the registry's first catch, flagged on the BACKLOG the night it shipped)",
        rationale="A dormant default must agree with its family or the first un-overridden caller inherits the stale scar.",
        review="Same basis as the harness/config rows; consider deriving all three from one constant at the #767 consolidation pass.",
    ),
    TimeoutEntry(
        name="Run-monitor doom window (no-progress stall grace)",
        module="tools.dispatch_harness.monitor",
        attribute="RunMonitor.stall_grace_s",
        seconds=900.0,
        surface="battery monitor → one watched dispatch (the determined-doomed fast-stop)",
        role="watchdog",
        must_exceed=("ACP_IDLE_TIMEOUT_S",),
        incident="night-20260709 B4 — the 90 s window doomed a job INSIDE the [3/5] verify gate, whose own budget is 600 s and whose checks write nothing to the watched logs until they finish; the gate's uv/ruff workers also escaped _CODER_PROC_NAMES, so a (possibly) working verify read as a dead run and cost the pass its bank",
        rationale="Must exceed the longest legitimately log-quiet, CPU-quiet gap INSIDE a healthy step (verify checks hand off between native workers), while still dooming a truly dead run in minutes — the overall bound is the backstop.",
        review="RAISED 240 -> 900 (#1366). THIS ENTRY'S OWN INCIDENT ALREADY GAVE THE ANSWER: it records the 2026-07-09 B4 job doomed inside a verify gate 'whose own budget is 600 s' — and the fix set the window to 240, still INSIDE it. Insufficient by its own stated reasoning, unnoticed for a month, and it recurred on night-20260809-230002 against a DIFFERENT 600 s inner judge (acp_coder.ACP_IDLE_TIMEOUT_S): doom fired at 23:17:06, the coder would have labelled the stall 'idle' at 23:23:06, and that label is the precondition for #740/W7's resample. So the retry was real, correctly wired and unreachable; only c1 ran on a card with attempts remaining and 8 h of budget unused. 900 = the 600 s inner judge plus margin. Now gate-locked in tests/security/test_watchdog_windows_nest.py, which asserts every declared outer window strictly exceeds the judge it sits above. Shrinkable only with a per-step progress artifact from verify-project.ps1 (the durable fix: the gate heartbeats, the window tightens); retire the CPU-name heuristic entirely if that lands.",
    ),
    TimeoutEntry(
        name="Battery harness doom window (the THIRD vantage of one quantity)",
        module="tools.dispatch_harness.harness",
        attribute="DispatchHarness.stall_grace_s",
        seconds=900.0,
        role="watchdog",
        must_exceed=("ACP_IDLE_TIMEOUT_S",),
        surface="battery harness → the dispatch it drives (the same physical window RunMonitor watches)",
        incident="#1366, found 2026-08-10 while giving the registry a `must_exceed` field: RunMonitor.stall_grace_s's own review line says 'change in LOCKSTEP with' its sibling and calls them 'one physical quantity, TWO vantages'. There are FIVE — this dataclass default, the from_env parameter default beside it, the monitor field, the battery CLI default, and DOOM_STALL_GRACE_S — and only two of the five were registered. A lockstep pair that miscounts itself is exactly how a lockstep pair rots.",
        rationale="Identical by construction to RunMonitor.stall_grace_s — the harness passes its own value down to the monitor it constructs, so a divergence here is invisible at the monitor's call site and produces two different doom windows depending on which entry point started the run. Registered so the drift tooth (A) sees it: the value is now checked against the live constant on every gate run rather than only by the hand-written lockstep test.",
        review="Moves ONLY in lockstep with RunMonitor.stall_grace_s and DOOM_STALL_GRACE_S — tests/security/test_watchdog_windows_nest.py asserts all three are equal, and this row's must_exceed asserts the nesting the equality is supposed to preserve. The two vantages still unregistered are dataclass/CLI defaults the module-constant discovery scan cannot see (BACKLOG-tracked below); promoting them needs the resolver to grow an argparse form, which is worth doing only if a fourth divergence appears.",
    ),
    TimeoutEntry(
        name="Battery AO re-boot wait (per-job re-ensure)",
        module="tools.dispatch_harness.battery",
        attribute="AoReensurer.boot_wait_s",
        seconds=180.0,
        surface="battery runner → AO boot before each job (#750 D1 lineage)",
        role="probe",
        incident="#750 — the battery now re-ensures a HEALTHY (mTLS-handshake-complete) AO before every job; a cold 14B load can exceed 2 minutes, so the wait must outlast it",
        rationale="Matches the swap driver's relaunch-readiness bound — the same cold-boot worst case measured from the same launcher.",
        review="Shrink in lockstep with real_backend_ready(timeout_s) once cold-boot latency is measured; the two waits cover one physical event.",
    ),
    TimeoutEntry(
        name="Teardown barrier: prior-AO port-quiet wait (post tree-kill)",
        module="tools.dispatch_harness.battery",
        attribute="TEARDOWN_BARRIER_PORT_FREE_TIMEOUT_S",
        seconds=15.0,
        surface="battery boot_launcher_detached -> a tree-killed prior AO's port (#863 Option A teardown barrier)",
        role="probe",
        incident="DRAFT_cert_remint_race_durable_fix.md Option A / #863 -- the reuse-window (#863, shipped) fixed CERT agreement between successive battery boots but left the OTHER failure shape the same AO-lifecycle overlap produces open: a still-live prior AO still holds the AO port when the new launcher tries to bind it (evidence: #863's own run log, PID 3128 'LEAKED on :5001 post-run')",
        rationale="terminate_process_tree's own escalation already bounds the KILL at ~3s (terminate() leaves-first then root, a bounded psutil.wait_procs(timeout=3.0) grace, then kill()); this row covers the REMAINING OS-level socket-teardown lag after the process is confirmed gone -- the ADR's own suggested 10-15s bound, taken at the top of that range for margin.",
        review="Shrink toward the measured kill-to-port-free lag once the barrier runs live on the Arc 140V; retire only if the AO ever exposes a graceful cross-process shutdown signal that makes a forced tree-kill unnecessary in the common case.",
    ),
    TimeoutEntry(
        name="Sandbox-freshness probe git bound (battery)",
        module="tools.dispatch_harness.battery",
        attribute="SANDBOX_PROBE_TIMEOUT_S",
        seconds=30.0,
        surface="battery runner → one sandbox git-history read before any per-card spend (#1058 gate)",
        role="probe",
        incident="#1058 / lesson 225 third instance — the 2026-07-21 17:19 direct-harness run launched onto a sandbox carrying four prior 'agent:' commits; the archive+re-init lives in the nightly WRAPPER, so direct invocations had no freshness guarantee and the baseline was confounded",
        rationale="A battery sandbox's full --all history is tens of commits, read in well under a second; 30 s dwarfs any healthy read on the busy overnight box while still bounding a wedged git so the probe can never stall a night. A timeout classifies UNDETERMINED and the card is refused fail-closed — the bound protects the runner, never the gate's strictness.",
        review="Shrink toward measured probe latency once the gate has run across a full campaign night; the value bounds a refusal path, so tightening is safe. Retire only if sandbox provisioning ever moves inside the runner (freshness by construction on every path).",
    ),
    TimeoutEntry(
        name="Per-card run-budget clamp (battery)",
        module="shared.fleet.swap_ops",
        attribute="CARD_RUN_BUDGET_MAX_S",
        seconds=28800.0,
        surface="battery runner → AO driver watchdog (per-card override ceiling)",
        role="budget",
        incident="#740 B3 re-grain — a card may declare its own run_budget_s (B3: 6 h vs the 3 h default); this clamps ANY card's request so a card cannot ask for an unbounded run",
        rationale="8 h covers the longest measured card (B3 ~6.5 h) with margin; a request above it is a typo or a runaway, not a real grain.",
        review="Shrink toward the longest real card as more grains are measured; retire if per-card budgets ever move into a schema with its own bound. #927 (2026-07-17) is the first use of this mechanism as a COHERENCE lever: per-card run_budget_s on the multi-wave cards clears the coherence lock's C2 floor (the 14400 s 2-wave/best-of-2 minimum the 10800 s default failed) while every per-card value stays below this 28800 s clamp and the active-campaign sum stays below the PT16H ceiling (the EXTERNAL Task-Scheduler backlog row's C3 pair).",
    ),
    TimeoutEntry(
        name="Per-card budget freshness window (battery)",
        module="shared.fleet.swap_ops",
        attribute="PENDING_RUN_BUDGET_FRESH_S",
        seconds=1800.0,
        surface="battery runner → AO (consume-once pending-budget staleness guard)",
        role="grain",
        must_exceed=("PLAN_RESPONSE_TIMEOUT_S",),
        incident="#740 B3 re-grain — the runner stages the per-card budget moments before dispatch; a budget older than this window is ignored so a runner that wrote then never dispatched can't apply a stale budget to a later job (the era-rot class, L195). #1359 (2026-08-09) — the 300 s value silently ate EVERY per-card budget an image-carrying card ever staged. B9 declares 28,800 s; measured on night-20260809-194335 the AO logged 'staged budget REJECTED as STALE: 28800s written 431s ago, freshness window 300s', one second after 'dispatch assets: 8/8 written'. B9 therefore ran on the 10,800 s default every night it has ever run and was killed hours early each time — run 20260809-154357-bd died at 10,901 s with wave 2 (the operator's individual-piece page) never started.",
        rationale="RAISED 300 -> 1800. The old rationale — '5 min dwarfs the write→dispatch gap' — was MEASURED FALSE, and the error was in the noun: the gap is write→EXECUTE, not write→dispatch, and EXECUTE is where the file is consumed, on the far side of the PLAN chain AND of dispatch-asset generation. Generating 8 assets alone is ~303 s at the measured 37.9 s each, so an image-carrying card could never keep its own budget. 1800 s covers the measured 431 s with margin and the theoretical worst case (PLAN's 720 s + asset generation) at ~1,023 s.",
        review="The guard still holds: the file is consume-once and deleted on read, and a default-budget card CLEARS it, so a staged-but-never-dispatched budget cannot reach a later job through this window. SHRINK back toward the original once dispatch-asset generation moves off the request thread (#1341 direction 1) — the same shrink condition as PA_HANDSHAKE_TIMEOUT_S and PROMPT_FLOW_PREFLIGHT_BUDGET_S; if those three ever disagree about it, one has rotted. RETIRE with the file mechanism if per-card budgets move onto the live dispatch protocol, which removes the staleness question entirely.",
    ),
    TimeoutEntry(
        name="Dispatch interception fail-safe (IPC backstop over the PLAN)",
        module="services.ui_backend.src.dispatcher",
        attribute="_DISPATCH_STREAM_FAILSAFE_S",
        seconds=780.0,
        surface="ui_backend dispatcher → gateway handle_dispatch_command (the whole /dispatch turn, incl. PLAN)",
        role="watchdog",
        must_exceed=("PLAN_RESPONSE_TIMEOUT_S",),
        incident="#1122 (2026-07-27, LA-blocking) — this interception was wrapped in the 175 s IMAGINE fail-safe while the PLAN it wraps is budgeted at 480 s, so the operator's plan was abandoned at 175 s and COMPLETED 28 s later (measured: timeout 18:20:18, generate_plan finished 18:20:46). #766 had raised the inner budget 180→480; nobody raised the wrapper, so that fix was unreachable from the UI. #1152 (2026-07-29) moved this in lockstep when PLAN_RESPONSE_TIMEOUT_S rose 480→720, so the dominance invariant kept holding.",
        rationale="MUST DOMINATE PLAN_RESPONSE_TIMEOUT_S (720) plus handler overhead — a wrapper shorter than what it wraps does not protect the inner budget, it deletes it. 780 leaves the same 60 s #1122 gave for project creation + IPC framing. A BACKSTOP, not the operating bound: the inner 720 fires first and reports honestly. Nothing downstream forces a shorter value (the WinUI pipe client sets a CONNECT timeout only).",
        review="Must move whenever PLAN_RESPONSE_TIMEOUT_S moves — the ORDERING is locked by tests/security/test_timeout_ordering.py, which asserts the relationship rather than the values, because a registry of values could not catch this class.",
    ),
    TimeoutEntry(
        name="Imagine stream fail-safe (IPC)",
        module="services.ui_backend.src.dispatcher",
        attribute="_IMAGINE_STREAM_FAILSAFE_S",
        seconds=175.0,
        surface="ui_backend dispatcher → imagine coordinator stream (IMAGINE ONLY since #1122)",
        role="watchdog",
        incident="UC-010 go-live — the original 90 s fail-safe was blown by a legitimate hires generate (14B eviction + upscale + refine); raised to 175 at the ADR-033 Am.2 rework. SCOPE CORRECTION (#1122, 2026-07-27): this constant ALSO bounded the /dispatch interception, capping a 480 s PLAN budget at 175 s; that consumer now has its own registered entry above.",
        rationale="Headroom over the slowest legitimate hires generate measured at go-live; the fail-safe exists so a wedged generate can never park the IPC forever. Sized for IMAGINE's inner work only — do not reuse it for a surface with a longer inner budget (that is the #1122 defect).",
        review="Re-measure if the image model, steps default, or hires ceiling changes (L195 era-rot class). Any NEW consumer of this constant must first prove its own inner budget is shorter than 175 s.",
    ),
    # ---- promoted from the BACKLOG (#767 item 2, 2026-07-09) — the call-site /
    # signature literals named as constants in their consumer modules (values
    # UNCHANGED; pure consolidation) ------------------------------------------------
    TimeoutEntry(
        name="start-llm load ceiling (30B load AND the 14B critic swap)",
        module="shared.fleet.swap_ops",
        attribute="START_LLM_TIMEOUT_S",
        seconds=480.0,
        surface="swap driver → start-llm.ps1 subprocess (both model loads)",
        role="judge",
        incident="#747 — a COLD compile-cache 30B load measured ~289 s live (compile + writing ~15 GB of .cl_cache); start-llm's own deadline moved to 480 and this ceiling moved with it",
        rationale="Headroom over the measured cold-cache worst case; a WARM load is ~12 s, so the ceiling only bites cold — and the never-zero teardown restores the 14B if a load truly hangs.",
        review="Shrink if cold-cache load latency re-measures lower (new GPU driver / OVMS); must track start-llm.ps1's own deadline — the two move together.",
    ),
    TimeoutEntry(
        name="Design critique pass (one capture+critique lap)",
        module="shared.fleet.swap_ops",
        attribute="DESIGN_LOOP_TIMEOUT_S",
        seconds=180.0,
        surface="swap driver → critique-loop.ps1 (headless capture + in-process VLM critique)",
        role="judge",
        incident="design (#688 Phase 3; never bitten)",
        rationale="Bounds one best-effort capture+critique lap; fail-soft — expiry degrades to the no-op fallback and can never block the driver's teardown.",
        review="Re-measure if the capture tier or VLM changes (L195 era-rot class); the design phase retires with the #688 loop itself.",
    ),
    TimeoutEntry(
        name="Cross-model critic pass (one 14B diff review)",
        module="shared.fleet.swap_ops",
        attribute="CRITIC_RUN_TIMEOUT_S",
        seconds=600.0,
        surface="swap driver → critic-run.ps1 (14B critic over the merged diff)",
        role="judge",
        incident="design (#687 task 2; never bitten)",
        rationale="A full-diff 14B review is minutes, not seconds; fail-soft — expiry returns the critic fallback and can NEVER block the teardown or the 14B restore.",
        review="Shrink once live critic-pass latency is measured across dispatches; must stay comfortably under the overall-run budget.",
    ),
    TimeoutEntry(
        name="Swap settle (old backend PID release, step 7)",
        module="shared.fleet.swap_driver",
        attribute="SETTLE_TIMEOUT_S",
        seconds=60.0,
        surface="swap driver → old AO process exit (design §2 step 7)",
        role="probe",
        incident="design (#670; never bitten)",
        rationale="Waits ONLY for the stepped-aside AO's PID to vanish; the headroom GATE (step 8) owns the 'released but still too loaded' case, so this bounds only a wedged old process.",
        review="Shrink if step-aside exit latency is ever measured; retire with an exit event from the step-aside handshake.",
    ),
    TimeoutEntry(
        name="GPU settle (14B allocation release before the 30B load)",
        module="shared.fleet.swap_driver",
        attribute="GPU_SETTLE_TIMEOUT_S",
        seconds=15.0,
        surface="swap driver → shared-RAM GPU-free wait-verify (#670 run-2)",
        role="probe",
        incident="#670 run-2 — a single-snapshot GPU check raced the 14B's release; the wait-verify replaced it",
        rationale="Gives the 14B's ~8.7 GB time to return to system RAM after the step-aside; on expiry the driver proceeds on the graceful unload rather than aborting.",
        review="Re-measure release latency if the model or GPU driver changes; retire if a real GPU budget probe ever lands on the iGPU.",
    ),
    TimeoutEntry(
        name="RAM gate wait-verify (system headroom clearing gate_gb before the 30B load, step 8)",
        module="shared.fleet.swap_driver",
        attribute="RAM_GATE_TIMEOUT_S",
        seconds=1800.0,
        surface="swap driver → system-RAM headroom wait-verify (#1128)",
        role="budget",
        must_exceed=("RAM_GATE_STALL_S",),
        incident="#1128 — battery night 2026-07-26: a single-snapshot RAM check gate-aborted BOTH scheduled jobs in ~100s each, on a night the wrapper's own real-load admission probe (#784's lower PROBE_FLOOR_GIB) had just succeeded and admitted; the OS had not finished reclaiming pages from that probe's 30B-unload + 14B reboot by the time the first job's own swap started.",
        rationale="Mirrors the GPU wait-verify's fix for the same class of race (a graceful release racing a single snapshot). 1800s matches the wrapper's own existing ~30-minute night-admission re-check cadence, spent here at per-job scope; each job's own run envelope is 15,000-16,200s, so even the full wait leaves the large majority of the budget for real coding work. Does NOT change gate_gb (the #777-measured 20 GiB safety floor) — only how patiently the driver waits for headroom to reach it.",
        review="Shrink if RAM-settling latency after a probe/reboot is ever measured directly; retire if the wrapper's admission probe and this gate are ever unified onto one consistent threshold instead of two independent checks.",
    ),
    TimeoutEntry(
        name="RAM gate no-progress cutoff (structural vs transient pressure, step 8)",
        module="shared.fleet.swap_driver",
        attribute="RAM_GATE_STALL_S",
        seconds=300.0,
        surface="swap driver → RAM wait-verify early exit when headroom is not clearing (#1274)",
        role="watchdog",
        incident="#1274 — manual battery run 2026-08-06 07:52: the lean preflight MEASURED 19.4 GiB against a 20.5 GiB fast-path gate, proceeded (the -Now path warns but never blocks, by design), and the swap then sat the FULL 1800 s RAM_GATE_TIMEOUT_S at 19.7 GiB before aborting. 30 minutes and a STALLED[HARNESS] scorecard spent re-reading a number that never moved, because the shortfall was resident processes (the dev tooling itself), not pages still being reclaimed.",
        rationale="RAM_GATE_TIMEOUT_S exists for pressure that is CLEARING (#1128's probe-unload race). When availability has not climbed by RAM_GATE_PROGRESS_GIB over the first reading after this window, nothing is being reclaimed and the rest of the wait is dead time charged to the job envelope. 300 s is 10 polls at the 30 s cadence — long enough that a genuinely settling system trips the progress test first (it climbs within a poll or two), short enough that a structural shortfall costs minutes rather than half an hour. Does NOT change gate_gb or the full window; only the case where waiting provably cannot help.",
        review="Raise if a real reclamation pattern is ever measured that climbs later than 300 s; retire if the admission probe and this gate are unified (same trigger as the row above).",
    ),
    TimeoutEntry(
        name="OVMS stop verify (teardown, first window)",
        module="shared.fleet.swap_driver",
        attribute="OVMS_STOP_TIMEOUT_S",
        seconds=60.0,
        surface="swap driver teardown → OVMS residency poll after stop_ovms",
        role="probe",
        incident="#670 B2 — a too-short verify window manufactured a phantom 'still alive' while a ~15 GB OVMS unload was legitimately finishing",
        rationale="Lets a large unload complete before the forced Stop-Process retry fires; crying wolf here costs a needless force-kill on the teardown path.",
        review="Shrink if OVMS unload latency measures lower; the post-force retry window (its 15 s sibling row) is the second net.",
    ),
    TimeoutEntry(
        name="OVMS stop verify (teardown, post-force retry window)",
        module="shared.fleet.swap_driver",
        attribute="OVMS_STOP_RETRY_TIMEOUT_S",
        seconds=15.0,
        surface="swap driver teardown → OVMS residency poll after the forced Stop-Process",
        role="probe",
        incident="design (#670 B2 sibling; never bitten)",
        rationale="A force-killed process should vanish fast — a short window keeps the teardown moving toward the unconditional 14B restore.",
        review="Tracks the first-window row; both retire together with an OVMS exit event.",
    ),
    TimeoutEntry(
        name="ACP driver semantic idle bound (no session/update = wedged)",
        module="tools.dispatch_harness.acp_coder",
        attribute="ACP_IDLE_TIMEOUT_S",
        seconds=600.0,
        surface="ACP coder driver (#775) → the persistent opencode-acp session watchdog (dormant behind driver=acp)",
        role="judge",
        incident="#790 first real coder battery under driver=acp (2026-07-12) — the 120 s bound derived from the #759 spike's 83 s 'max healthy gap' FALSE-KILLED 18 of 24 candidates (75%): the spike undersampled the long single-generation tail. During a model-generation window opencode-acp emits NO session/update AND writes NO stderr line (both channels verified dark for the full 120 s in the transcripts), and before the first edit nothing is on disk — so a healthy 30B generating its first/next response is INDISTINGUISHABLE from a wedged one on every observable channel. The 83 s figure only measured cold-prefill, not a full generation burst.",
        rationale="Because no real-time signal separates 'generating' from 'wedged', the bound is a coarse 'never coming back' catch and must clear a full multi-minute generation burst with margin. The cost is asymmetric: a false-kill is catastrophic (and collapses best-of-N — all N candidates die the same generation-time death, the #790 0-1/6-GREEN symptom), while waiting longer on a genuine hang is cheap. 600 s clears the observed >120 s generation windows and still catches a true hang at 1/6 of the 3600 s ceiling. LIVE per-run value is acp.idle_sec in agentic-setup configs/fleet-driver.json (overrides this default via --idle-sec); bumping it there is the operator go-live step. Dormant here: only fires when driver=acp.",
        review="Retighten with REAL (non-censored) inter-generation gap data once a battery runs at 600 s and the true healthy tail is observable — the 120 s kills were right-censored, so the true max generation window is still unknown; 600 s is deliberately conservative. Re-measure if the coder model, OVMS batching, or prefix-cache posture changes (L195 era-rot).",
    ),
    TimeoutEntry(
        name="ACP coordinator soft 'quiet run' surfacing threshold",
        module="shared.fleet.acp_progress",
        attribute="DEFAULT_ACP_QUIET_THRESHOLD_S",
        seconds=300.0,
        surface="coordinator /coord status (#844 C2) → the SOFT 'coder run is quiet' operational marker (dormant behind [coordinator].enabled)",
        role="grain",
        incident="design (#844 C2 ACP-monitoring limb, 2026-07-13; never bitten) — a DISPLAY threshold, not a kill budget",
        rationale="A cross-run OPERATIONAL visibility signal, NOT a kill: nothing dies at this bound; /coord status shows a run 'QUIET' so the operator SEES it go silent BEFORE the fleet's hard 600 s idle-cancel (acp_coder.ACP_IDLE_TIMEOUT_S) fires. Set to half the kill window for early visibility; the quiet flag additionally requires the run to be active (a finished run's stale last-event age is never 'quiet'). The coordinator observes; the fleet's own watchdog owns the kill (ADR-039 2.1 item 9).",
        review="Retighten alongside ACP_IDLE_TIMEOUT_S once real inter-generation gap data exists; a surfacing knob, so a slightly-off value is only display noise, never a false kill. Retire if the coordinator ever consumes a live event signal instead of the last-event age.",
    ),
    TimeoutEntry(
        name="Coordinator heartbeat AC-power cycle interval",
        module="shared.coordinator.config",
        attribute="DEFAULT_HEARTBEAT_INTERVAL_S",
        seconds=900.0,
        surface="C3 heartbeat wake cycle (#845) — the launcher-managed timer's AC-power tick (DORMANT behind [coordinator].heartbeat_enabled)",
        role="backoff",
        incident="design (#845 C3 cadence limb, 2026-07-14; never bitten) — a cadence, not a kill budget",
        rationale="15 min is coarse enough to be invisible on the box (each cycle is file reads + loopback HTTP + pure math; model drafting only when FULL mode permits) and fine enough for the hours-to-weeks operational timescale the coordinator owns (ADR-039 §2.13.6). On battery or an undeterminable power state the EFFECTIVE interval is this × [coordinator].heartbeat_battery_multiplier (default 4 → 60 min, ADR-039 §2.12.12) — the stretched value rides inside the liveness stamp's next_expected_by deadline, so the dead-man watchdog needs no interval knowledge and cannot false-alarm across cadence changes (design §6).",
        review="Tune only from measured cycle cost + operator experience after #855 shadow cycles produce real telemetry; a shorter interval buys stall-detection latency, not correctness (nothing kills at this bound). Live TOML override: [coordinator].heartbeat_interval_s.",
    ),
    TimeoutEntry(
        name="Coordinator heartbeat boot grace (first-cycle delay + tripwire idle-grace floor)",
        module="shared.coordinator.config",
        attribute="DEFAULT_BOOT_GRACE_S",
        seconds=300.0,
        surface="C3 heartbeat (#845) — first cycle after backend boot; also floors the quiet-queue tripwire's idle-grace (DORMANT behind [coordinator].heartbeat_enabled)",
        role="grain",
        incident="design (#845 C3 cadence limb, 2026-07-14; never bitten)",
        rationale="The heartbeat starts after the Step-6b prompt-flow preflight but must not compete with a boot's model compile/first-load tail, and the quiet-queue tripwire must not fire while the fleet/operator are still getting the morning started (false alarms retrain the operator to ignore the tripwire — the exact failure the schedule-aware design exists to prevent). 5 min clears every measured boot tail with margin.",
        review="Tune from shadow-mode telemetry (#855); a surfacing-cadence knob, never a kill. Live TOML override: [coordinator].heartbeat_boot_grace_s.",
    ),
    TimeoutEntry(
        name="Coordinator heartbeat dead-man slack (stamp-deadline grace)",
        module="shared.coordinator.deadman",
        attribute="DEADMAN_SLACK_S",
        seconds=120.0,
        surface="launcher dead-man watchdog (#845 C3 limb 7) — trips when now exceeds the liveness stamp's OWN next_expected_by by this slack (DORMANT behind [coordinator].heartbeat_enabled; no heartbeat, no watchdog)",
        role="grain",
        incident="design (#845 C3 dead-man limb, 2026-07-14; never bitten) — the registered constant is the SLACK, not a computed threshold: the stamp declares its own deadline, so battery/overnight cadence stretching can never false-alarm (the design-review MAJOR that killed the fixed K×interval threshold)",
        rationale="Must absorb one cycle's own runtime (compose + loopback Vikunja reads = seconds; a worst-case bounded draft = tens of seconds) plus thread-scheduling jitter, while still surfacing a genuinely wedged heartbeat within ~2 minutes of its self-declared deadline. Staleness-detection latency is an operator-notice quality, not a correctness bound — nothing kills on this value.",
        review="Tune from #855 shadow-cycle telemetry (measured cycle durations); shrink only if the drafting cap shrinks at the heartbeat ceremony (the c.1894 decision point). Poll grain (DEADMAN_POLL_S 30.0) is below-registry per convention — see BACKLOG.",
    ),
    TimeoutEntry(
        name="Driver-integrated doom window (stop-doomed-fast no-progress grace)",
        module="shared.fleet.doom_check",
        attribute="DOOM_STALL_GRACE_S",
        seconds=900.0,
        surface="detached swap driver → the #844 C2 DoomWatchdog (DORMANT behind [coordinator].swap_doom_checks_enabled; armed only while a run-fleet child is registered)",
        role="watchdog",
        must_exceed=("ACP_IDLE_TIMEOUT_S",),
        incident="design (#844 C2 swap-path limb, 2026-07-13; never bitten at THIS vantage) — the SAME measured quantity as the harness monitor's RunMonitor.stall_grace_s, whose night-20260709 B4 false-doom set 240 s: the [3/5] verify gate's checks write nothing to the watched logs until they finish and its uv/ruff workers had escaped the CPU heuristic",
        rationale="Must exceed the longest legitimately log-quiet, CPU-quiet gap INSIDE a healthy step while still dooming a truly dead run in minutes; the overall run budget is the backstop. The driver vantage adds the structural child-registered arming condition, so driver-side phases (gates/critic/design/teardown) can never be doomed regardless of this window.",
        review="RAISED 240 -> 900 (#1366), in lockstep. Change in LOCKSTEP with RunMonitor.stall_grace_s — and note there are in fact THREE vantages, not two: DispatchHarness.stall_grace_s is the third, which is exactly how a lockstep pair rots. All three are now asserted equal by tests/security/test_watchdog_windows_nest.py, along with the rule that broke: an outer window must strictly exceed the inner judge it observes (here acp_coder.ACP_IDLE_TIMEOUT_S = 600 s, the point at which the CODER declares its own generation wedged). Shrinkable only with a per-step progress artifact from verify-project.ps1; retire the CPU-name heuristic entirely if that lands.",
    ),
    TimeoutEntry(
        name="Box-state capture: PowerShell Get-VM probe",
        module="shared.perf_env_capture",
        attribute="PS_PROBE_TIMEOUT_S",
        seconds=25.0,
        surface="perf-evidence box-state stamp (#816 Part 2) → Hyper-V VM enumeration subprocess",
        role="probe",
        incident="#816 / the 2026-07-10 unnoticed-VM incident — perf evidence carried no box state, so the #769 addendum was human-reconstructed; the stamp's own probes need a bound so a wedged PowerShell cannot stall a bench run",
        rationale="A warm Get-VM answers in ~1-3 s; 25 s covers a cold PowerShell + Hyper-V module load and matches the harnesses' existing gpu_driver_version probe budget. On expiry the capture stamps vm_states='unknown' (fail-soft, honest) — the budget bounds the stall, never the honesty.",
        review="Shrink toward ~10 s if measured cold-start Get-VM stays low across driver/OS updates; retire only if the capture moves to a native Hyper-V API.",
    ),
    TimeoutEntry(
        name="Box-state capture: loopback port connect probe",
        module="shared.perf_env_capture",
        attribute="PORT_PROBE_TIMEOUT_S",
        seconds=1.0,
        surface="perf-evidence box-state stamp (#816 Part 2) → AO :5001 / OVMS :8000 liveness probes",
        role="probe",
        incident="#816 / the 2026-07-10 unnoticed-VM incident (same stamp; see the Get-VM row)",
        rationale="Loopback answers in milliseconds; 1 s is generous headroom that still bounds a capture on a wedged stack to ~2 s across both ports. Liveness-not-health is deliberate (the #750 create_connection lesson): for a box-state stamp, 'something holds the port' IS the fact.",
        review="Retire if the stamp ever consumes the launcher's richer health probe; no shrink pressure at 1 s.",
    ),
    TimeoutEntry(
        name="Session idle-reap TTL (AO in-RAM session state)",
        module="services.assistant_orchestrator.src.entrypoint",
        attribute="AssistantOrchestratorEntrypointConfig.session_idle_ttl_s",
        seconds=1800.0,
        surface="AO serve loop → ContextManager sessions + kv-warm/trust flags + egress envelopes",
        role="grain",
        incident="LA decision 2026-07-11 (#801 c.1713) — the System Qualities Audit found destroy_session had ZERO production callers (every session since boot stayed resident until restart, unbounded for a 'decades of use' process); the LA set the idle policy in-chat: a conversation idle 30 minutes releases its RAM, the durable transcript in the encrypted store is unaffected, resume reloads from disk",
        rationale="An LA-decided operator-workflow value, not a measured budget: 30 min of turn inactivity marks a conversation the operator has left; the false-reap cost is one cold KV prefill + substrate-recoverable grounding — never data loss (FUT-07 reseeds from the gateway store on the next prompt). Not a wait — an idleness threshold; <= 0 disables.",
        review="Shrink/retire path = operator-workflow telemetry (LA-directed at the decision): re-present to the LA if resume-after-break cold prefills are ever felt in real use, or if long-uptime RSS (AUDIT-15 owns the soak) shows the 30-min bound is looser than needed.",
    ),
    TimeoutEntry(
        name="Session idle-reap TTL (gateway coordinator dicts default)",
        module="services.ui_gateway.src.constants",
        attribute="SESSION_STATE_TTL_S",
        seconds=1800.0,
        surface="gateway turn-start sweep → pending documents / preview meta / pending ingests / pending dispatch plans",
        role="grain",
        incident="LA decision 2026-07-11 (#801 c.1713) family — the same audit finding: the gateway's session-keyed coordinator dicts are cleared only by their completion pop, so an abandoned session's entries (a /load never prompted, an undecided ingest preview, an unapproved dispatch plan) sat until restart",
        rationale="Must agree with the AO row above — the launcher threads the AO-resolved [context].session_idle_ttl_s over this default so ONE operator knob bounds both processes (the family test locks the two equal); this constant is the direct-construction (test/dev) fallback.",
        review="Moves in lockstep with the AO row at every review (operator-workflow telemetry, per the LA decision); retire if the gateway state ever moves into the session store.",
    ),
    # ---- #821 (QUALITY-3) oracle-QA subprocess bounds (2026-07-11) ---------------
    TimeoutEntry(
        name="Oracle-QA collectability confirmation (pytest --collect-only)",
        module="shared.fleet.oracle_qa",
        attribute="ORACLE_QA_COLLECT_TIMEOUT_S",
        seconds=60.0,
        surface="oracle-QA seed gate → pytest --collect-only over the synthesised stub skeleton (#821)",
        role="judge",
        incident="design (#821 — the advisory collectability confirmation; py_compile is in-process, this bounds the isolated collect-only subprocess)",
        rationale="A collect-only never executes a test — it imports + collects the single oracle file against inert stubs; 60 s covers a cold `uv` wheel-resolve behind the pinned pytest/hypothesis and matches the guest-provisioning wheel-fetch class. On expiry the stamp is 'not-run' (a timeout produces no pytest signal, so the probe reports that it never ran rather than passing a machinery miss off as a verdict on the oracle) — fail-soft, never a false-park; the sound HARD collectability gate is the in-process py_compile.",
        review="Shrink toward the measured warm collect-only latency once #821 runs live on the Arc 140V; retire if the collectability confirmation folds into #822's grade-time import probe.",
    ),
    TimeoutEntry(
        name="Oracle-QA FAIL-TO-PASS baseline (oracle vs pre-wave skeleton)",
        module="shared.fleet.oracle_qa",
        attribute="ORACLE_QA_F2P_TIMEOUT_S",
        seconds=120.0,
        surface="oracle-QA seed gate → pytest over the raw oracle against the pre-implementation tree (#821)",
        role="judge",
        incident="design (#821 — the discrimination dual: every acceptance assertion must FAIL on the unimplemented skeleton; a passing test is vacuous and refuses the seed)",
        rationale="Runs the oracle ONCE against a tree whose implementation does not exist yet, so most tests fail fast on import — 120 s covers a cold `uv` resolve plus a slow property test with margin, and stays well under grade-time's 600 s. On expiry the f2p stamp is 'not-run' (fail-soft — a machinery miss never blocks a dispatch, only a CONFIRMED vacuous pass refuses).",
        review="Shrink toward measured F2P latency from the first live #821 seed gates; must stay below the grade-time oracle bound (the seed baseline can never legitimately run longer than the graded run).",
    ),
    TimeoutEntry(
        name="Oracle-QA NODE FAIL-TO-PASS baseline (.mjs oracle vs pre-wave skeleton)",
        module="shared.fleet.oracle_qa",
        attribute="ORACLE_QA_NODE_F2P_TIMEOUT_S",
        seconds=60.0,
        surface="oracle-QA seed gate → `node --test --test-reporter=tap` over the raw .mjs oracle against the pre-implementation tree (#1342)",
        role="judge",
        incident="#1342 — B9's `20260807-195617-bd` banked GREEN missing an operator-required page: every non-python oracle skipped the execution stages outright, so the 33-line job oracle (two EMPTY test bodies) was never proven able to fail, and `already_satisfied` (#1049) read its pass as proof of completeness and deleted the task from the plan",
        rationale="The node dual of ORACLE_QA_F2P_TIMEOUT_S, deliberately its OWN bound rather than a reuse: node resolves no wheels and has no `uv` step, so the python row's 120 s is entirely resolve-shaped margin that would only delay an abort here. Measured on this host, the five-test escaped oracle runs in ~0.15 s, so 60 s is ~400x the observed cost and still covers a cold start plus a test that hangs on a real socket. On expiry the stamp is 'not-run' (fail-soft — a machinery miss never blocks a dispatch; only a CONFIRMED pre-implementation pass refuses).",
        review="Shrink toward measured node F2P latency once #1342 has run live across a full battery night; retire if the node and python baselines ever converge on one runner-agnostic bound.",
    ),
    # ---- #828 (QUALITY-10) oracle mutation-audit budget (2026-07-11) -------------
    TimeoutEntry(
        name="Oracle mutation-audit overall budget (one GREEN job)",
        module="shared.fleet.oracle_mutation",
        attribute="ORACLE_MUTATION_BUDGET_S",
        seconds=300.0,
        surface="oracle mutation audit → all deterministic operator-mutants of one passing job's feature code (#828, offline / GREEN-only)",
        role="budget",
        incident="design (#828 — the discrimination dual of #821; bounds the WHOLE bounded (N≤20) audit, not one mutant — the per-mutant subprocess reuses #821's registered ORACLE_QA_F2P_TIMEOUT_S)",
        rationale="An oracle grades in seconds and the audit runs ≤20 mutants, so 5 minutes covers a full worst-case pass (incl. a cold `uv` resolve on the first mutant) with margin; the audit is offline and GREEN-only (~1/night), off the dispatch critical path, so a generous abort bound costs nothing on the common night. On expiry the audit stamps `partial-budget`/`skipped-budget` honestly — it never fakes a full score.",
        review="Shrink toward the measured full-audit wall-clock once #828 runs live on the Arc 140V; retire the fixed bound if the audit ever moves to a per-mutant event/heartbeat model.",
    ),
    TimeoutEntry(
        name="Oracle mutation-audit STAGE budget (all GREENs of one battery)",
        module="tools.dispatch_harness.green_quality.mutation",
        attribute="ORACLE_MUTATION_BATTERY_BUDGET_S",
        seconds=900.0,
        surface="battery close → the advisory oracle-mutation stage across every GREEN of one night (#1195 item 2)",
        role="budget",
        must_exceed=("ORACLE_MUTATION_BUDGET_S",),
        incident="design (#1195 — #828's audit had no production caller; wiring it at battery close multiplies a PER-JOB bound by the night's GREEN count, so the stage needs a ceiling of its own)",
        rationale="MEASURED through the stage on this host 2026-07-30: one pinned oracle invocation costs 5.67 s (uv builds a fresh ephemeral env per run, and the audit's per-run isolated home pays that every mutant), so a full N=20 audit is ~2 min per GREEN and a 4-GREEN night ~8 min. 15 minutes covers that with margin while refusing the 20 min that 4 GREENs each entitled to the per-job 300 s would allow — a per-job bound cannot bound a stage. On expiry the unreached GREENs stamp `skipped-battery-budget` — visible as unaudited, never absent and never counted as a pass.",
        review="Re-measure against a real battery deliverable (the 5.67 s came from a two-function fixture; a wider tree has more mutation sites); revisit if the GREEN count per night rises materially or if per-criterion attribution (L4-KILLS) multiplies the mutant count.",
    ),
    # ---- #829 (QUALITY-11) flake differential — hermetic re-run bound (2026-07-11) --
    TimeoutEntry(
        name="Job-oracle flake differential (hermetic re-run on a parking failure)",
        module="shared.fleet.swap_ops",
        attribute="JOB_ORACLE_FLAKE_RERUN_TIMEOUT_S",
        seconds=600.0,
        surface="swap_ops flake differential → one hermetic pytest/node re-run of the job oracle on a FAILED grade (#829)",
        role="judge",
        incident="design (#829 — the flake differential: B1n2's `assert 689 == 1` was a nondeterministic grader; a fail->pass flip on a fresh hermetic re-run reroutes the park BUILD->VERIFY)",
        rationale="The re-run IS a job-oracle grade, so it legitimately gets the SAME bound as the grade-time run (600 s); it fires ONLY on an already-failed grade, on the park path, so the added wall-clock is at most one more grade and never touches the GREEN path. On expiry the re-run is fail-closed to a non-pass -> read as 'no flip' (the failure stands, attributed BUILD), never a spurious flake flag.",
        review="Shrink toward the measured warm grade latency once #829 runs live on the Arc 140V; must track the grade-time oracle bound (the two move together — a re-run can never legitimately run longer than the grade it re-runs).",
    ),
    # ---- #837 (QUALITY-17) GREEN-audit Layer-1 subprocess bounds (2026-07-11) -----
    TimeoutEntry(
        name="GREEN-audit archetype-regression probe (one probe invocation)",
        module="tools.dispatch_harness.green_quality.layer1",
        attribute="GREEN_QUALITY_PROBE_TIMEOUT_S",
        seconds=120.0,
        surface="GREEN-audit Layer 1 → run the deliverable's public surface on a stored real-input probe-set (offline, GREEN-only, over SANDBOX archived repos)",
        role="judge",
        incident="design (#837 — the archetype-regression probe imports the coder's first-party module and calls a public function, whose import-time code could hang; same class as #822's IMPORT_PROBE_TIMEOUT_S)",
        rationale="A probe calls a tiny first-party function on a handful of inputs — seconds normally; the bound is the abort ceiling on an import-time side effect (a while-True / a blocking call) in generated SANDBOX code. GREEN-only + offline (~1 GREEN/night), off the dispatch critical path, so a generous 120 s never bites a legitimate probe. On expiry the probe is 'could-not-run' (fail-soft, advisory) — never a false regression flag.",
        review="Shrink toward measured probe latency once the audit runs live over battery GREENs; retire if the regression probe ever moves to a static (execution-free) behaviour signature.",
    ),
    TimeoutEntry(
        name="GREEN-audit advisory ruff pass (one repo lint)",
        module="tools.dispatch_harness.green_quality.layer1",
        attribute="GREEN_QUALITY_RUFF_TIMEOUT_S",
        seconds=60.0,
        surface="GREEN-audit Layer 1 → advisory `ruff check` over one GREEN's shipped repo (soft band input)",
        role="judge",
        incident="design (#837 — the dossier's 'turn ruff on as advisory'; a SOFT signal, never a fail)",
        rationale="Ruff lints a small repo in well under a second; 60 s covers a cold process start on the busy overnight box. Missing ruff / a timeout → the lint is SKIPPED (the soft signal is simply absent), never a fail and never band-moving on its own — so the bound only prevents a wedged linter from stalling battery close.",
        review="Shrink toward measured ruff latency once the audit runs live; retire if the style signal ever moves to an in-process AST check with no subprocess.",
    ),
    # ---- #812 (AUDIT-13) launcher child-wait supervisory interval (2026-07-11) ---
    TimeoutEntry(
        name="WinUI child-wait supervisory interval (launcher liveness)",
        module="launcher.process_launch",
        attribute="_WAIT_SUPERVISORY_INTERVAL_S",
        seconds=5.0,
        surface="launcher main thread → WinUI child handle (_HandleProc.wait, the de-elevated launch path)",
        role="backoff",
        incident="#812 / AUDIT-13 (Standards Conformance + System Qualities, 12-Factor IX disposability) — the child-wait was a single unconditional WaitForSingleObject(_INFINITE), so launcher liveness was hostage to a wedged WinUI child handle with no supervisory wake",
        rationale="A POLL CADENCE, not an abort budget: the launcher's main-thread child-wait now loops in chunks of this length rather than one un-woken INFINITE syscall, so it re-checks each lap and can never sit forever on a stuck handle. With timeout=None (the launcher's call) the wait still blocks until the child exits — 5 s bounds liveness loss on a wedged handle yet never busy-spins the main thread.",
        review="Retire if the child-wait ever consumes a real stop/exit event instead of polling (an event beats a poll); shrink only if launcher-responsiveness telemetry ever demands a tighter wake.",
    ),
    # ---- #1201 coder-test-QA scope resolution (2026-07-30) ----------------------
    TimeoutEntry(
        name="Coder-test-QA scope resolution (one bounded git read; three sequential reads per call)",
        module="shared.fleet.coder_test_qa",
        attribute="CODER_TEST_SCOPE_GIT_TIMEOUT_S",
        seconds=30.0,
        surface="coder_test_qa CLI → git rev-parse/diff/ls-files over the candidate worktree, to learn which test files THIS task wrote",
        role="judge",
        incident="design (#1201 — the scan was whole-tree, so task N was charged for the exams of tasks 1..N-1 and any repo with history withdrew every review-skip forever; scoping the scan introduced these reads). Sized on the registered DEP_DELTA_GIT_TIMEOUT_S sibling, which bounds the same operation against the same kind of tree.",
        rationale="A rev-parse plus two name-only reads over one small candidate worktree are milliseconds; 30 s is the abort ceiling on a wedged git. The reads spawn through shared.procspawn.run_captured (#1239), so an EXPIRY IS NOT THE WHOLE COST: the helper then tree-kills (psutil.wait_procs, up to 3 s) and drains the dying child's pipes (up to 5 s), so a timed-out read costs up to ~38 s, and three sequential ones a ~114 s worst wall per scan — not the 90 s a bare abort ceiling implies. Still far inside the 14400 s per-task ceiling and never on a control path: an expiry yields an UNRESOLVED scope, which is reported as an absent measurement and forces nothing. Read the teardown bounds from shared/procspawn.py rather than restating them if they change.",
        review="Shrink toward measured resolution latency once live dispatch runs record it; retire if the harness ever hands the changed-file list to the scanner directly instead of the scanner deriving it.",
    ),
)


#: KNOWN timeouts not yet promoted into the registered table — visible on purpose.
#: Each is (module-path, identifier-or-description). The discovery lock in the
#: gate test accepts a production timeout ONLY if it is registered above or
#: listed here; this list is the registry's honest to-do, reviewed quarterly.
BACKLOG: tuple[tuple[str, str], ...] = (
    # Remaining after the #767 item-2 consolidation (2026-07-09): the swap_driver
    # __init__ defaults and the swap_ops _run_to_logfile call-site literals are now
    # NAMED module constants and REGISTERED above (values unchanged). What is left
    # is poll/grace grain and the surfaces deferred to the item-5 scan widening.
    ("tools/dispatch_harness/battery.py",
     "AoReensurer minor waits (ao_mtls_healthy probe 5.0, initial_grace_s 20.0, poll_s 3.0) and the #863 "
     "teardown barrier's poll cadence (TEARDOWN_BARRIER_POLL_S 0.5) — poll/grace grain below registry "
     "value; boot_wait_s 180.0 and TEARDOWN_BARRIER_PORT_FREE_TIMEOUT_S 15.0 ARE registered. Revisit at "
     "the item-5 scan widening."),
    ("tools/dispatch_harness/monitor.py",
     "RunMonitor poll_interval_s 5.0 / swapback_grace_s 180.0 / cpu_sample_s 1.5 — poll/grace grain; "
     "overall_timeout_s IS registered (reconciled to 10800, 2026-07-08) and stall_grace_s IS registered "
     "(raised 90→240 at the night-20260709 B4 false-doom, registered same change)."),
    ("shared/fleet/doom_check.py",
     "DOOM_POLL_INTERVAL_S 5.0 / DOOM_CPU_SAMPLE_S 1.5 — poll/sample grain below registry value "
     "(mirrors the harness monitor's identical grains); DOOM_STALL_GRACE_S IS registered (#844, "
     "lockstep with RunMonitor.stall_grace_s)."),
    ("tools/dispatch_harness/harness.py + battery.py — the doom window's REMAINING vantages",
     "One physical quantity (the no-progress doom window, 900.0 s) is declared in FIVE places: "
     "doom_check.DOOM_STALL_GRACE_S and RunMonitor.stall_grace_s and DispatchHarness.stall_grace_s "
     "are REGISTERED; still unregistered are harness.py:117 (the from_env parameter default beside "
     "the dataclass field) and battery.py:2885 (the --stall-grace-s argparse default). Neither is "
     "reachable by the module-constant discovery scan, and the resolver has no argparse form. "
     "NOT grain-class and NOT harmless: each is a full-strength copy of a watchdog window, and #1366 "
     "is the ticket for what happens when copies of one window disagree. Named here rather than "
     "silently omitted — the equality across all three registered vantages is gate-locked in "
     "tests/security/test_watchdog_windows_nest.py, and these two ride on the same 900.0 by "
     "convention only. Promote when the resolver grows an argparse form, or the FIRST time a "
     "divergence is observed, whichever comes first (#1366)."),
    ("shared/coordinator/deadman.py",
     "DEADMAN_POLL_S 30.0 — poll grain below registry value (staleness-detection latency = poll + "
     "slack; the quantity that matters, DEADMAN_SLACK_S, IS registered, #845 limb 7). Also "
     "shared/coordinator/heartbeat.py _STOP_JOIN_S 5.0 — teardown join bound, grain-class (the "
     "daemon flag is the real guarantee)."),
    ("services/ui_gateway/src/*",
     "streaming constants (chunk cadence / flush waits) — enumerate at the item-5 scan widening; the "
     "imagine 175 s fail-safe IS registered (it lives in services/ui_backend/src/dispatcher.py — the "
     "original backlog line's ui_gateway path was wrong)."),
    ("shared/fleet/swap_ops.py + shared/fleet/guest_oracle_transport.py",
     "guest-oracle readiness poll cadence (GUEST_ORACLE_READY_POLL_S 3.0) and per-attempt reachable-"
     "probe bound (ORACLE_REACHABLE_TIMEOUT_S_DEFAULT 5.0) — poll/attempt grain below registry value; "
     "the 90 s cold-boot budget and 15 s already-running grace ARE registered (night-20260711)."),
    ("services/assistant_orchestrator/src/entrypoint.py",
     "_SESSION_REAP_INTERVAL_S 60.0 — the idle-session reaper's serve-loop check cadence (#801); poll "
     "grain below registry value. The TTLs it enforces ARE registered (the session idle-reap TTL family)."),
    # ---- EXTERNAL window, un-importable — named permanently (#833, 2026-07-15) ----
    ("EXTERNAL: Task Scheduler \\BlarAI\\BlarAI-M2-Battery-Nightly ExecutionTimeLimit",
     "The nightly battery's OUTER wall-clock ceiling lives in Windows Task Scheduler, not a Python "
     "constant, so it can NEVER be a registered TimeoutEntry (live_value has nothing to import) — it is "
     "named here PERMANENTLY so the quarterly review walks its (window, budget) pair. The pair: this "
     "ExecutionTimeLimit must DOMINATE the runner's own inner budgets = sum over the active campaign jobs "
     "of each card's run_budget_s (default swap_run_budget_s 10800) + per-job re-ensure + fixed overhead. "
     "That derivation is OWNED by tools/dispatch_harness/battery_execution_limit.py (arithmetic-locked in "
     "tests/integration/test_battery_execution_limit.py) and enforced OUT-OF-BAND against the live task by "
     "agentic-setup/scripts/verify-battery-task-settings.ps1, which fails loud when the ceiling drifts "
     "below the derived floor. Incident: 2026-07-11 the then-PT10H ceiling tree-killed the runner 3 min "
     "before the last job finished (#740 c.1734) — the invisible-taxonomy member (L217) that silently "
     "overruled every registered inner budget (an unowned L221 window/budget pair). Finding (2026-07-15): "
     "the current 6-job campaign derives a 68400 s (19.0 h) floor while the live ceiling is PT16H "
     "(57600 s) — under by 3 h; the verify script reports this as a drift (a reliability/operator setting, "
     "not a code defect). Disposition (#833/#927, LA-approved 2026-07-17 c.2156): the ceiling STAYS "
     "PT16H; the lever is per-card run_budget_s on the multi-wave cards ONLY, never a global "
     "swap_run_budget_s bump (that derives a ~25 h floor at the 6-job scale). The baseline 6-job campaign "
     "is CLOSED (lean-trimmed to jobs=[B2,B4], #904); with B4 16200 s + B2 15000 s the lean campaign "
     "derives a ~33600 s (9.3 h) floor, back UNDER PT16H (T4 GREEN). The paired coherence lock "
     "agentic-setup/scripts/verify-battery-budget-coherence.ps1 (wired non-fatally into the nightly "
     "preflight) is the teeth for this pair: C1 per-candidate ceiling >= idle (600 s), C2 per-job budget "
     ">= the 14400 s 2-wave/best-of-2 floor (the 10800 s default's proven C2 FAIL), C3 the C2 fix still "
     "fits under this PT16H ceiling. Any future campaign re-widening past the lean set must re-derive this "
     "floor (verify-battery-task-settings.ps1 T4 fails loud below it) — per-card budgets provisioned across "
     "a full job set can re-cross PT16H, the exact shape the per-card (not global) lever exists to avoid."),
)


def live_value(entry: TimeoutEntry) -> Any:
    """Resolve an entry's LIVE value (the gate compares this to ``seconds``).

    Three attribute forms (#767): a module constant (``"CONST"``), a dataclass
    field default (``"ClassName.field"``), and a function parameter default
    (``"func_name(param)"``). Resolution failures raise loudly — an entry that
    cannot resolve is a broken row and must fail the gate, never skip.
    """
    module = importlib.import_module(entry.module)
    attr = entry.attribute
    if "(" in attr and attr.endswith(")"):
        func_name, param = attr[:-1].split("(", 1)
        func = getattr(module, func_name)
        parameter = inspect.signature(func).parameters[param]
        if parameter.default is inspect.Parameter.empty:
            raise AttributeError(
                f"{entry.module}.{func_name}({param}) has no default to register"
            )
        return parameter.default
    if "." in attr:
        class_name, field_name = attr.split(".", 1)
        owner = getattr(module, class_name)
        if not is_dataclass(owner):
            raise AttributeError(f"{entry.module}.{class_name} is not a dataclass")
        for f in dataclass_fields(owner):
            if f.name == field_name:
                if f.default is MISSING:
                    raise AttributeError(
                        f"{entry.module}.{attr} has no default to register"
                    )
                return f.default
        raise AttributeError(f"{entry.module}.{class_name} has no field {field_name}")
    return getattr(module, attr)


def registry_names() -> set[str]:
    """The registered (module, attribute) pairs — the discovery lock's allow-set."""
    return {f"{e.module}:{e.attribute}" for e in REGISTRY}
