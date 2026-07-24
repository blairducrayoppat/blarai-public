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
        surface="ui_gateway → Policy Agent (Boot-Phase-3, ALL transport modes since #808)",
        incident="design; scope widened at #808 — production attempts previously rode PROMPT_RESPONSE_TIMEOUT_S (180 s) per socket op, so one mute-but-accepting server could stall the whole boot inside a single attempt",
        rationale="'Is anyone there?' — bounds ONE probe; the PA_HANDSHAKE_BUDGET_S row owns the patience (the L221 window/budget pair: per-attempt 5 s x 16 attempts rides INSIDE the 180 s aggregate, never over it).",
        review="Shrinkable if handshake latency is ever measured; retire only with the retry loop.",
    ),
    TimeoutEntry(
        name="PA handshake aggregate backoff budget (Boot-Phase-3)",
        module="services.ui_gateway.src.constants",
        attribute="PA_HANDSHAKE_BUDGET_S",
        seconds=180.0,
        surface="ui_gateway → Policy Agent (check_pa_status retry loop; launcher step 6a + TUI boot banner both ride it)",
        incident="#808 (System Qualities Audit, Resilience #2) — the ~15-18 s aggregate (3 attempts x 5 s + 1+2 s backoff; ~3 s when the socket refuses instantly) latched StartupState.FAILED while the same codebase documents a cold 14B load exceeding 2 minutes — a cold/slow PA became a hard outage needing a manual relaunch",
        rationale="Matches the documented cold-load ceiling the system already grants the same physical event (real_backend_ready / AoReensurer.boot_wait_s, both 180 s); schedule 1,2,4,8 then 15 s-capped keeps the healthy path instant and the tail probing; config absence (no port / no certs) still fails immediately.",
        review="Shrink in lockstep with real_backend_ready(timeout_s) once cold 14B handshake-availability is measured across boots; retire if the PA ever emits a readiness event (an event beats a deadline).",
    ),
    TimeoutEntry(
        name="PA handshake backoff cap (tail probe interval)",
        module="services.ui_gateway.src.constants",
        attribute="PA_HANDSHAKE_BACKOFF_CAP_S",
        seconds=15.0,
        surface="ui_gateway → Policy Agent (check_pa_status backoff schedule)",
        incident="design (#808) — uncapped doubling inside the new 180 s budget would sleep 64+ s between tail attempts, leaving up to a minute of blindness to an already-ready PA",
        rationale="Worst-case staleness after the PA becomes ready: a cold boot is detected within one cap anywhere inside the budget; small enough to stay responsive, large enough not to hammer a loading service.",
        review="Tune with the budget row (the schedule derives from base/cap/budget together); retires with the polling loop if a readiness event lands.",
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
        name="Import-contract probe (#822 layout gate)",
        module="shared.fleet.swap_ops",
        attribute="IMPORT_PROBE_TIMEOUT_S",
        seconds=120.0,
        surface="swap driver finish-line layout gate → import_probe.py / node ESM probe over the integrated tree",
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
        incident="design (#830 — the B7 park class: a Node/web job merged working code but had NO behavioral floor, so a missing module at boot surfaced as an opaque wave-final failure; the floor RUNS the entrypoint, whose import-time / arg-parse code could hang, e.g. an import-time server-start or a while-True)",
        rationale="A boot is seconds; the bound is the abort ceiling on an entrypoint with an import-time side effect. Mirrors the import probe's 120 s and sits well under the 600 s job-oracle grade it precedes — the boot failure is the cheaper signal, run first. The python import check is hang-safe (it never runs __main__), so a bite here is a genuine import-time hang worth surfacing; the --help liveness check rides a smaller local 45 s sub-bound.",
        review="Shrink toward measured boot latency once live exec-smoke runs record it; retire only if a language's boot ever becomes provable without running the entrypoint.",
    ),
    TimeoutEntry(
        name="Static pre-gate (#831 error-level lint)",
        module="shared.fleet.swap_ops",
        attribute="STATIC_PREGATE_TIMEOUT_S",
        seconds=120.0,
        surface="swap driver per-task static pre-gate → ruff (uv --with) + node --check over the merged task's created source",
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
        name="Teardown barrier: prior-AO port-quiet wait (post tree-kill)",
        module="tools.dispatch_harness.battery",
        attribute="TEARDOWN_BARRIER_PORT_FREE_TIMEOUT_S",
        seconds=15.0,
        surface="battery boot_launcher_detached -> a tree-killed prior AO's port (#863 Option A teardown barrier)",
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
        incident="#740 B3 re-grain — a card may declare its own run_budget_s (B3: 6 h vs the 3 h default); this clamps ANY card's request so a card cannot ask for an unbounded run",
        rationale="8 h covers the longest measured card (B3 ~6.5 h) with margin; a request above it is a typo or a runaway, not a real grain.",
        review="Shrink toward the longest real card as more grains are measured; retire if per-card budgets ever move into a schema with its own bound. #927 (2026-07-17) is the first use of this mechanism as a COHERENCE lever: per-card run_budget_s on the multi-wave cards clears the coherence lock's C2 floor (the 14400 s 2-wave/best-of-2 minimum the 10800 s default failed) while every per-card value stays below this 28800 s clamp and the active-campaign sum stays below the PT16H ceiling (the EXTERNAL Task-Scheduler backlog row's C3 pair).",
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
    TimeoutEntry(
        name="ACP driver semantic idle bound (no session/update = wedged)",
        module="tools.dispatch_harness.acp_coder",
        attribute="ACP_IDLE_TIMEOUT_S",
        seconds=600.0,
        surface="ACP coder driver (#775) → the persistent opencode-acp session watchdog (dormant behind driver=acp)",
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
        incident="design (#845 C3 dead-man limb, 2026-07-14; never bitten) — the registered constant is the SLACK, not a computed threshold: the stamp declares its own deadline, so battery/overnight cadence stretching can never false-alarm (the design-review MAJOR that killed the fixed K×interval threshold)",
        rationale="Must absorb one cycle's own runtime (compose + loopback Vikunja reads = seconds; a worst-case bounded draft = tens of seconds) plus thread-scheduling jitter, while still surfacing a genuinely wedged heartbeat within ~2 minutes of its self-declared deadline. Staleness-detection latency is an operator-notice quality, not a correctness bound — nothing kills on this value.",
        review="Tune from #855 shadow-cycle telemetry (measured cycle durations); shrink only if the drafting cap shrinks at the heartbeat ceremony (the c.1894 decision point). Poll grain (DEADMAN_POLL_S 30.0) is below-registry per convention — see BACKLOG.",
    ),
    TimeoutEntry(
        name="Driver-integrated doom window (stop-doomed-fast no-progress grace)",
        module="shared.fleet.doom_check",
        attribute="DOOM_STALL_GRACE_S",
        seconds=240.0,
        surface="detached swap driver → the #844 C2 DoomWatchdog (DORMANT behind [coordinator].swap_doom_checks_enabled; armed only while a run-fleet child is registered)",
        incident="design (#844 C2 swap-path limb, 2026-07-13; never bitten at THIS vantage) — the SAME measured quantity as the harness monitor's RunMonitor.stall_grace_s, whose night-20260709 B4 false-doom set 240 s: the [3/5] verify gate's checks write nothing to the watched logs until they finish and its uv/ruff workers had escaped the CPU heuristic",
        rationale="Must exceed the longest legitimately log-quiet, CPU-quiet gap INSIDE a healthy step while still dooming a truly dead run in minutes; the overall run budget is the backstop. The driver vantage adds the structural child-registered arming condition, so driver-side phases (gates/critic/design/teardown) can never be doomed regardless of this window.",
        review="Change in LOCKSTEP with RunMonitor.stall_grace_s (one physical quantity, two vantages). Shrinkable only with a per-step progress artifact from verify-project.ps1; retire the CPU-name heuristic entirely if that lands.",
    ),
    TimeoutEntry(
        name="Box-state capture: PowerShell Get-VM probe",
        module="shared.perf_env_capture",
        attribute="PS_PROBE_TIMEOUT_S",
        seconds=25.0,
        surface="perf-evidence box-state stamp (#816 Part 2) → Hyper-V VM enumeration subprocess",
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
        incident="design (#821 — the advisory collectability confirmation; py_compile is in-process, this bounds the isolated collect-only subprocess)",
        rationale="A collect-only never executes a test — it imports + collects the single oracle file against inert stubs; 60 s covers a cold `uv` wheel-resolve behind the pinned pytest/hypothesis and matches the guest-provisioning wheel-fetch class. On expiry the stamp is 'unconfirmed' (fail-soft, never a false-park) — the sound HARD collectability gate is the in-process py_compile.",
        review="Shrink toward the measured warm collect-only latency once #821 runs live on the Arc 140V; retire if the collectability confirmation folds into #822's grade-time import probe.",
    ),
    TimeoutEntry(
        name="Oracle-QA FAIL-TO-PASS baseline (oracle vs pre-wave skeleton)",
        module="shared.fleet.oracle_qa",
        attribute="ORACLE_QA_F2P_TIMEOUT_S",
        seconds=120.0,
        surface="oracle-QA seed gate → pytest over the raw oracle against the pre-implementation tree (#821)",
        incident="design (#821 — the discrimination dual: every acceptance assertion must FAIL on the unimplemented skeleton; a passing test is vacuous and refuses the seed)",
        rationale="Runs the oracle ONCE against a tree whose implementation does not exist yet, so most tests fail fast on import — 120 s covers a cold `uv` resolve plus a slow property test with margin, and stays well under grade-time's 600 s. On expiry the f2p stamp is 'not-run' (fail-soft — a machinery miss never blocks a dispatch, only a CONFIRMED vacuous pass refuses).",
        review="Shrink toward measured F2P latency from the first live #821 seed gates; must stay below the grade-time oracle bound (the seed baseline can never legitimately run longer than the graded run).",
    ),
    # ---- #828 (QUALITY-10) oracle mutation-audit budget (2026-07-11) -------------
    TimeoutEntry(
        name="Oracle mutation-audit overall budget (one GREEN job)",
        module="shared.fleet.oracle_mutation",
        attribute="ORACLE_MUTATION_BUDGET_S",
        seconds=300.0,
        surface="oracle mutation audit → all deterministic operator-mutants of one passing job's feature code (#828, offline / GREEN-only)",
        incident="design (#828 — the discrimination dual of #821; bounds the WHOLE bounded (N≤20) audit, not one mutant — the per-mutant subprocess reuses #821's registered ORACLE_QA_F2P_TIMEOUT_S)",
        rationale="An oracle grades in seconds and the audit runs ≤20 mutants, so 5 minutes covers a full worst-case pass (incl. a cold `uv` resolve on the first mutant) with margin; the audit is offline and GREEN-only (~1/night), off the dispatch critical path, so a generous abort bound costs nothing on the common night. On expiry the audit stamps `partial-budget`/`skipped-budget` honestly — it never fakes a full score.",
        review="Shrink toward the measured full-audit wall-clock once #828 runs live on the Arc 140V; retire the fixed bound if the audit ever moves to a per-mutant event/heartbeat model.",
    ),
    # ---- #829 (QUALITY-11) flake differential — hermetic re-run bound (2026-07-11) --
    TimeoutEntry(
        name="Job-oracle flake differential (hermetic re-run on a parking failure)",
        module="shared.fleet.swap_ops",
        attribute="JOB_ORACLE_FLAKE_RERUN_TIMEOUT_S",
        seconds=600.0,
        surface="swap_ops flake differential → one hermetic pytest/node re-run of the job oracle on a FAILED grade (#829)",
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
        incident="#812 / AUDIT-13 (Standards Conformance + System Qualities, 12-Factor IX disposability) — the child-wait was a single unconditional WaitForSingleObject(_INFINITE), so launcher liveness was hostage to a wedged WinUI child handle with no supervisory wake",
        rationale="A POLL CADENCE, not an abort budget: the launcher's main-thread child-wait now loops in chunks of this length rather than one un-woken INFINITE syscall, so it re-checks each lap and can never sit forever on a stuck handle. With timeout=None (the launcher's call) the wait still blocks until the child exits — 5 s bounds liveness loss on a wedged handle yet never busy-spins the main thread.",
        review="Retire if the child-wait ever consumes a real stop/exit event instead of polling (an event beats a poll); shrink only if launcher-responsiveness telemetry ever demands a tighter wake.",
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
