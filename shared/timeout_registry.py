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
    incident: str        # what paid for this number
    rationale: str       # why THIS number (the legitimate worst case)
    review: str          # what would let it shrink or be retired


#: The registered taxonomy. Ordered by surface, then by budget.
REGISTRY: tuple[TimeoutEntry, ...] = (
    TimeoutEntry(
        name="PA handshake (per connection attempt)",
        module="services.ui_gateway.src.constants",
        attribute="PA_HANDSHAKE_TIMEOUT_S",
        seconds=5.0,
        surface="ui_gateway → Policy Agent",
        incident="design (never bitten)",
        rationale="'Is anyone there?' — a bare connection attempt; retries with backoff own the patience.",
        review="Shrinkable if handshake latency is ever measured; retire only with the retry loop.",
    ),
    TimeoutEntry(
        name="Prompt/response (the default per-message receive)",
        module="services.ui_gateway.src.constants",
        attribute="PROMPT_RESPONSE_TIMEOUT_S",
        seconds=180.0,
        surface="ui_gateway → AO (every framed message unless overridden)",
        incident="#561 — a legitimate vision turn (VLM load + describe + two 14B generations) tripped the old 120 s and was fail-closed as a spurious validation error",
        rationale="Headroom over the slowest LEGITIMATE single turn (the vision chain).",
        review="Shrink if the VLM-eviction fix keeps real turns well under it across a measured sample; any shrink must re-run the vision-turn worst case.",
    ),
    TimeoutEntry(
        name="Dispatch PLAN (the plan-time 14B sequence)",
        module="services.ui_gateway.src.constants",
        attribute="PLAN_RESPONSE_TIMEOUT_S",
        seconds=480.0,
        surface="ui_gateway → AO (PLAN_REQUEST only)",
        incident="#766 — a PLAN (~6 chained generations) against a cold just-swapped-back AO legitimately exceeded 180 s; the gateway hung up mid-generation and B4/B6 STALLED [HARNESS] (2026-07-07, two instances)",
        rationale="Dominates the measured cold worst case; the per-job mTLS re-ensure is the fast liveness gate, so this only ever waits on a provably-alive AO.",
        review="Shrink once cold-boot PLAN latency is measured across campaign transitions; retire if the PLAN ever streams progress (an event beats a deadline).",
    ),
    TimeoutEntry(
        name="Fleet per-task ceiling (one run-fleet task)",
        module="shared.fleet.swap_ops",
        attribute="TASK_TIMEOUT_S",
        seconds=14400.0,
        surface="swap driver → run-fleet subtree",
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
        incident="design (#744 — dormant path, no live run yet)",
        rationale="Bounds a hostile/looping oracle inside the guest; a job oracle is seconds, not minutes — this is an abort bound with wide margin.",
        review="Re-measure from the first live guest-oracle.json runs; must stay under the transport round-trip budget (see the 630 s row).",
    ),
    TimeoutEntry(
        name="Guest oracle transport round-trip",
        module="shared.fleet.guest_oracle_transport",
        attribute="ORACLE_TRANSPORT_TIMEOUT_S_DEFAULT",
        seconds=630.0,
        surface="swap driver 3.11 → AF_HYPERV bridge → guest oracle service (DORMANT)",
        incident="design (#744 transport slice — sized as the guest execution bound + extract/transfer slack)",
        rationale="Must dominate the guest's own 600 s pytest bound so the transport never gives up on a still-legitimate guest run; the bridge subprocess adds its own 15 s spawn margin on top.",
        review="Shrink in lockstep with the guest execution bound after live-ceremony measurements; the dominance relation is gate-locked.",
    ),
    TimeoutEntry(
        name="Egress fingerprint answer (operator consent)",
        module="services.assistant_orchestrator.src.entrypoint",
        attribute="AssistantOrchestratorEntrypointConfig.egress_fingerprint_timeout_s",
        seconds=120.0,
        surface="AO → operator (fail-closed DENY on expiry)",
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
        incident="#757 family — RECONCILED 2026-07-08: the registry's own seeding inventory caught this default still at the pre-#757 5400 while every sibling had moved to 10800 (the registry's first catch, flagged on the BACKLOG the night it shipped)",
        rationale="A dormant default must agree with its family or the first un-overridden caller inherits the stale scar.",
        review="Same basis as the harness/config rows; consider deriving all three from one constant at the #767 consolidation pass.",
    ),
    TimeoutEntry(
        name="Run-monitor doom window (no-progress stall grace)",
        module="tools.dispatch_harness.monitor",
        attribute="RunMonitor.stall_grace_s",
        seconds=240.0,
        surface="battery monitor → one watched dispatch (the determined-doomed fast-stop)",
        incident="night-20260709 B4 — the 90 s window doomed a job INSIDE the [3/5] verify gate, whose own budget is 600 s and whose checks write nothing to the watched logs until they finish; the gate's uv/ruff workers also escaped _CODER_PROC_NAMES, so a (possibly) working verify read as a dead run and cost the pass its bank",
        rationale="Must exceed the longest legitimately log-quiet, CPU-quiet gap INSIDE a healthy step (verify checks hand off between native workers), while still dooming a truly dead run in minutes — the overall bound is the backstop.",
        review="Shrinkable only with a per-step progress artifact from verify-project.ps1 (the durable fix: the gate heartbeats, the window tightens); retire the CPU-name heuristic entirely if that lands.",
    ),
    TimeoutEntry(
        name="Battery AO re-boot wait (per-job re-ensure)",
        module="tools.dispatch_harness.battery",
        attribute="AoReensurer.boot_wait_s",
        seconds=180.0,
        surface="battery runner → AO boot before each job (#750 D1 lineage)",
        incident="#750 — the battery now re-ensures a HEALTHY (mTLS-handshake-complete) AO before every job; a cold 14B load can exceed 2 minutes, so the wait must outlast it",
        rationale="Matches the swap driver's relaunch-readiness bound — the same cold-boot worst case measured from the same launcher.",
        review="Shrink in lockstep with real_backend_ready(timeout_s) once cold-boot latency is measured; the two waits cover one physical event.",
    ),
    TimeoutEntry(
        name="Per-card run-budget clamp (battery)",
        module="shared.fleet.swap_ops",
        attribute="CARD_RUN_BUDGET_MAX_S",
        seconds=28800.0,
        surface="battery runner → AO driver watchdog (per-card override ceiling)",
        incident="#740 B3 re-grain — a card may declare its own run_budget_s (B3: 6 h vs the 3 h default); this clamps ANY card's request so a card cannot ask for an unbounded run",
        rationale="8 h covers the longest measured card (B3 ~6.5 h) with margin; a request above it is a typo or a runaway, not a real grain.",
        review="Shrink toward the longest real card as more grains are measured; retire if per-card budgets ever move into a schema with its own bound.",
    ),
    TimeoutEntry(
        name="Per-card budget freshness window (battery)",
        module="shared.fleet.swap_ops",
        attribute="PENDING_RUN_BUDGET_FRESH_S",
        seconds=300.0,
        surface="battery runner → AO (consume-once pending-budget staleness guard)",
        incident="#740 B3 re-grain — the runner stages the per-card budget moments before dispatch; a budget older than this window is ignored so a runner that wrote then never dispatched can't apply a stale budget to a later job (the era-rot class, L195)",
        rationale="5 min dwarfs the write→dispatch gap yet is far under a job's runtime, so a real override always lands and a stale one never does.",
        review="Tighten if the write→dispatch path is ever measured to be near-instant; retire with the file mechanism if per-card budgets move onto the live dispatch protocol.",
    ),
    TimeoutEntry(
        name="Imagine stream fail-safe (IPC)",
        module="services.ui_backend.src.dispatcher",
        attribute="_IMAGINE_STREAM_FAILSAFE_S",
        seconds=175.0,
        surface="ui_backend dispatcher → imagine coordinator stream",
        incident="UC-010 go-live — the original 90 s fail-safe was blown by a legitimate hires generate (14B eviction + upscale + refine); raised to 175 at the ADR-033 Am.2 rework",
        rationale="Headroom over the slowest legitimate hires generate measured at go-live; the fail-safe exists so a wedged generate can never park the IPC forever.",
        review="Re-measure if the image model, steps default, or hires ceiling changes (L195 era-rot class).",
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
        incident="#670 run-2 — a single-snapshot GPU check raced the 14B's release; the wait-verify replaced it",
        rationale="Gives the 14B's ~8.7 GB time to return to system RAM after the step-aside; on expiry the driver proceeds on the graceful unload rather than aborting.",
        review="Re-measure release latency if the model or GPU driver changes; retire if a real GPU budget probe ever lands on the iGPU.",
    ),
    TimeoutEntry(
        name="OVMS stop verify (teardown, first window)",
        module="shared.fleet.swap_driver",
        attribute="OVMS_STOP_TIMEOUT_S",
        seconds=60.0,
        surface="swap driver teardown → OVMS residency poll after stop_ovms",
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
        incident="design (#670 B2 sibling; never bitten)",
        rationale="A force-killed process should vanish fast — a short window keeps the teardown moving toward the unconditional 14B restore.",
        review="Tracks the first-window row; both retire together with an OVMS exit event.",
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
     "AoReensurer minor waits (ao_mtls_healthy probe 5.0, initial_grace_s 20.0, poll_s 3.0) — poll/grace "
     "grain below registry value; boot_wait_s 180.0 IS registered. Revisit at the item-5 scan widening."),
    ("tools/dispatch_harness/monitor.py",
     "RunMonitor poll_interval_s 5.0 / swapback_grace_s 180.0 / cpu_sample_s 1.5 — poll/grace grain; "
     "overall_timeout_s IS registered (reconciled to 10800, 2026-07-08) and stall_grace_s IS registered "
     "(raised 90→240 at the night-20260709 B4 false-doom, registered same change)."),
    ("services/ui_gateway/src/*",
     "streaming constants (chunk cadence / flush waits) — enumerate at the item-5 scan widening; the "
     "imagine 175 s fail-safe IS registered (it lives in services/ui_backend/src/dispatcher.py — the "
     "original backlog line's ui_gateway path was wrong)."),
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
