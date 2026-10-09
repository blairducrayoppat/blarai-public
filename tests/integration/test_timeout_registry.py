# enforces-rule: testing.standing_gate.every-fix-ships-its -- timeout-registration arm only, not the regression-lock arm
"""
Timeout Registry — Standing-Gate Locks (LA-directed 2026-07-07)
================================================================
Three teeth keep the taxonomy from rotting into documentation-fiction:

  A. DRIFT — every registered entry's ``seconds`` must equal the LIVE constant
     it names (resolved by import, never copied). Changing a timeout without
     updating its registry row fails the gate; so does the reverse.
  B. DISCOVERY — a scan over the production surfaces for timeout-shaped
     module-level constants: each hit must be REGISTERED or on the explicit
     BACKLOG. This is the "monitor for new entry needs" control — a new
     timeout cannot land invisibly.
  C. QUALITY — every registered row carries a non-empty incident, rationale,
     and review trigger (a number without its story is exactly what the
     registry exists to prevent).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from shared.timeout_registry import BACKLOG, REGISTRY, ROLES, live_value, registry_names

_REPO = Path(__file__).resolve().parents[2]

#: Production files the discovery scan walks for module-level timeout constants.
#: (Call-site literals and dataclass-field defaults are BACKLOG-tracked by hand
#: until promoted — the scan targets the greppable module-constant class first.)
_SCAN_FILES: tuple[str, ...] = (
    "services/ui_gateway/src/constants.py",
    "shared/fleet/swap_ops.py",
    "shared/fleet/swap_driver.py",
    "shared/fleet/dispatch.py",
    "shared/fleet/oracle_qa.py",
    "shared/fleet/oracle_mutation.py",
    "shared/fleet/vikunja_bridge.py",
    "tools/dispatch_harness/config.py",
    "tools/dispatch_harness/green_quality/mutation.py",
    "services/assistant_orchestrator/src/websearch/live_adapter.py",
)

#: Module-level constant shape: NAME_TIMEOUT_S = <number> / NAME_BUDGET_S = <number>.
_CONST_RE = re.compile(
    r"^(?P<name>_?[A-Z][A-Z0-9_]*(?:TIMEOUT|BUDGET)_S)\s*(?::[^=]+)?=\s*[0-9]", re.M
)

_MODULE_FOR_FILE = {
    "services/ui_gateway/src/constants.py": "services.ui_gateway.src.constants",
    "shared/fleet/swap_ops.py": "shared.fleet.swap_ops",
    "shared/fleet/swap_driver.py": "shared.fleet.swap_driver",
    "shared/fleet/dispatch.py": "shared.fleet.dispatch",
    "shared/fleet/oracle_qa.py": "shared.fleet.oracle_qa",
    "shared/fleet/oracle_mutation.py": "shared.fleet.oracle_mutation",
    "shared/fleet/vikunja_bridge.py": "shared.fleet.vikunja_bridge",
    "tools/dispatch_harness/config.py": "tools.dispatch_harness.config",
    "tools/dispatch_harness/green_quality/mutation.py":
        "tools.dispatch_harness.green_quality.mutation",
    "services/assistant_orchestrator/src/websearch/live_adapter.py":
        "services.assistant_orchestrator.src.websearch.live_adapter",
}


# ---------------------------------------------------------------------------
# A. Drift
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("entry", REGISTRY, ids=lambda e: e.attribute)
def test_registered_value_matches_live_constant(entry):
    assert live_value(entry) == entry.seconds, (
        f"{entry.module}.{entry.attribute} is {live_value(entry)} but the registry "
        f"says {entry.seconds} — update BOTH sides in the same change (the row's "
        f"incident/rationale/review must reflect the new number)."
    )


# ---------------------------------------------------------------------------
# B. Discovery (the monitor for new entry needs)
# ---------------------------------------------------------------------------


def test_every_scanned_timeout_constant_is_registered_or_backlogged():
    registered = registry_names()
    backlog_text = " ".join(f"{m} {d}" for m, d in BACKLOG)
    unaccounted: list[str] = []
    for rel in _SCAN_FILES:
        text = (_REPO / rel).read_text(encoding="utf-8")
        module = _MODULE_FOR_FILE[rel]
        for m in _CONST_RE.finditer(text):
            name = m.group("name")
            key = f"{module}:{name}"
            if key in registered:
                continue
            if name in backlog_text or rel in backlog_text:
                continue
            unaccounted.append(f"{rel}: {name}")
    assert not unaccounted, (
        "Timeout constant(s) found that are neither REGISTERED nor BACKLOGGED — "
        "add a registry row (with the incident that justifies the number) or an "
        f"explicit backlog line: {unaccounted}"
    )


# ---------------------------------------------------------------------------
# C. Quality
# ---------------------------------------------------------------------------


def test_every_entry_carries_its_story():
    for e in REGISTRY:
        assert e.incident.strip(), f"{e.attribute}: empty incident"
        assert e.rationale.strip(), f"{e.attribute}: empty rationale"
        assert e.review.strip(), f"{e.attribute}: empty review trigger"
        assert e.seconds > 0, f"{e.attribute}: non-positive budget"


def test_registry_has_no_duplicate_targets():
    keys = [f"{e.module}:{e.attribute}" for e in REGISTRY]
    assert len(keys) == len(set(keys)), "duplicate registry rows"


def test_plan_budget_dominates_prompt_budget():
    # The one cross-entry relation that is load-bearing today (#766): the PLAN
    # budget exists BECAUSE it must exceed the per-prompt default.
    by_attr = {e.attribute: e.seconds for e in REGISTRY}
    assert by_attr["PLAN_RESPONSE_TIMEOUT_S"] > by_attr["PROMPT_RESPONSE_TIMEOUT_S"]


def test_oracle_transport_budget_dominates_guest_execution_bound():
    # #744: the transport round-trip must outlast the guest's own pytest bound,
    # or the transport gives up on a still-legitimate guest run and reports an
    # unreachable guest that was merely busy.
    by_attr = {e.attribute: e.seconds for e in REGISTRY}
    assert (
        by_attr["ORACLE_TRANSPORT_TIMEOUT_S_DEFAULT"]
        > by_attr["execute_snapshot(timeout_s)"]
    )


def test_monitor_default_reconciled_to_the_757_family():
    # The registry's first catch (#767 item 1, reconciled 2026-07-08): the
    # monitor's dormant default must agree with the harness + config family.
    by_attr = {e.attribute: e.seconds for e in REGISTRY}
    assert (
        by_attr["RunMonitor.overall_timeout_s"]
        == by_attr["DispatchHarness.overall_timeout_s"]
        == by_attr["_DEFAULT_RUN_BUDGET_S"]
    )


def test_handshake_budget_covers_the_cold_load_ceiling():
    # #808: the Boot-Phase-3 handshake budget exists BECAUSE the old ~15-18 s
    # aggregate contradicted the system's own documented cold-14B ceiling
    # (real_backend_ready / AoReensurer.boot_wait_s = 180 s). The budget must
    # never fall below that ceiling again — the L221 pair, gate-locked.
    by_attr = {e.attribute: e.seconds for e in REGISTRY}
    assert (
        by_attr["PA_HANDSHAKE_BUDGET_S"]
        >= by_attr["real_backend_ready(timeout_s)"]
    )
    assert by_attr["PA_HANDSHAKE_BUDGET_S"] >= by_attr["AoReensurer.boot_wait_s"]


def test_handshake_per_attempt_rides_inside_the_budget():
    # #808: the per-attempt probe and the backoff cap must both be small
    # relative to the aggregate budget, or the schedule degenerates into a
    # handful of monster attempts (the shape the widen exists to prevent).
    by_attr = {e.attribute: e.seconds for e in REGISTRY}
    assert by_attr["PA_HANDSHAKE_TIMEOUT_S"] < by_attr["PA_HANDSHAKE_BUDGET_S"]
    assert by_attr["PA_HANDSHAKE_BACKOFF_CAP_S"] < by_attr["PA_HANDSHAKE_BUDGET_S"]


def test_handshake_schedule_sums_to_the_registered_budget():
    # #808: the executable schedule (the thing check_pa_status actually runs
    # and the TUI banner mirrors) must sum EXACTLY to the registered budget —
    # otherwise the registry row is documentation-fiction (the C14 class).
    from services.ui_gateway.src.constants import pa_handshake_backoff_schedule

    by_attr = {e.attribute: e.seconds for e in REGISTRY}
    schedule = pa_handshake_backoff_schedule()
    assert sum(schedule) == by_attr["PA_HANDSHAKE_BUDGET_S"]
    assert max(schedule) == by_attr["PA_HANDSHAKE_BACKOFF_CAP_S"]


def test_session_ttl_family_reconciled():
    # #801: the AO's [context].session_idle_ttl_s default and the gateway's
    # SESSION_STATE_TTL_S constant are ONE knob (the launcher threads the AO
    # value over the gateway default) — a drifted pair would silently give the
    # two processes different idle semantics on direct construction.
    by_attr = {e.attribute: e.seconds for e in REGISTRY}
    assert (
        by_attr["AssistantOrchestratorEntrypointConfig.session_idle_ttl_s"]
        == by_attr["SESSION_STATE_TTL_S"]
    )


def test_live_value_resolver_fails_loud_on_broken_rows():
    # A row that cannot resolve must FAIL the gate, never skip: a broken row is
    # documentation-fiction with a green checkmark (the C14 class).
    from shared.timeout_registry import TimeoutEntry

    broken = [
        TimeoutEntry(  # missing module attribute
            name="x", module="shared.fleet.dispatch", attribute="NOT_A_CONST",
            seconds=1.0, surface="s", role="probe", incident="i", rationale="r", review="v"),
        TimeoutEntry(  # dataclass field with no such name
            name="x", module="shared.fleet.dispatch",
            attribute="FleetDispatchConfig.not_a_field",
            seconds=1.0, surface="s", role="probe", incident="i", rationale="r", review="v"),
        TimeoutEntry(  # function param with no default
            name="x", module="shared.fleet.guest_oracle",
            attribute="execute_snapshot(snapshot_zip)",
            seconds=1.0, surface="s", role="probe", incident="i", rationale="r", review="v"),
    ]
    for entry in broken:
        with pytest.raises((AttributeError, KeyError, TypeError)):
            live_value(entry)


# ---------------------------------------------------------------------------
# #927 — the per-card run-budget (window, budget) pair (LA-approved 2026-07-17).
# The EXTERNAL Task-Scheduler ceiling row owns this pair; its BlarAI-side lever
# is the per-card run_budget_s clamp registered above (CARD_RUN_BUDGET_MAX_S).
# The full C2/C3 arithmetic lock lives in test_battery_execution_limit.py (the
# (window,budget) pair's derivation owner); here we lock the registry-internal
# half: the registered clamp must dominate the C2 floor, or the lever the
# EXTERNAL row documents is unusable, and the pair's documentation must survive.
# ---------------------------------------------------------------------------

# The coherence lock's C2 floor: a 2-wave/best-of-2 job's minimum per-job budget
# (2 x 2 x 3600 s), the value the 10800 s swap_run_budget_s default fails.
_C2_FLOOR_S = 14400.0


def test_927_per_card_clamp_dominates_the_c2_floor():
    # A card must be able to clear the C2 floor WITHOUT hitting the per-card
    # clamp; if a future shrink of CARD_RUN_BUDGET_MAX_S dropped below the floor,
    # the per-card lever (the #927 fix for the multi-wave starvation) would be
    # unusable — every provisioned budget would clamp back below coherence.
    by_attr = {e.attribute: e.seconds for e in REGISTRY}
    assert by_attr["CARD_RUN_BUDGET_MAX_S"] > _C2_FLOOR_S


def test_927_external_ceiling_row_names_the_coherence_pair():
    # The EXTERNAL Task-Scheduler ceiling row (un-importable, BACKLOG-named) must
    # keep documenting its (window,budget) coherence pair after #927 — the
    # quarterly review walks it here, not in an importable constant.
    external = " ".join(
        desc for name, desc in BACKLOG if name.startswith("EXTERNAL: Task Scheduler")
    )
    assert external, "the EXTERNAL Task-Scheduler ceiling BACKLOG row is missing"
    for token in ("verify-battery-budget-coherence", "C2", "PT16H", "per-card"):
        assert token in external, (
            f"the EXTERNAL ceiling row no longer documents '{token}' — the #927 "
            f"(window,budget) coherence pair must stay named for the quarterly review"
        )


# ---------------------------------------------------------------------------
# D. RELATIONS (#1366) — a duration's ROLE and the durations it must outlast.
#
# Before this block, teeth A–C could tell you every number and its story and
# could not answer the question that kept costing runs: *is this window longer
# than the thing it observes?* Three inversions surfaced on 2026-08-09 alone —
# #1353 (a 5 s probe against a measured 16.35 s negotiation), #1359 (a 300 s
# freshness window against a 431 s gap, discarding an 8-hour envelope on every
# run B9 had ever done), and #1366 (a 240 s doom watchdog inside the coder's own
# 600 s idle judge, making #740/W7's idle-retry permanently unreachable).
#
# All three were derivable by arithmetic from values this table already held.
# The ordering assertions that DID exist were hand-written, one function per
# pair, spread across three files — tests/security/test_timeout_ordering.py,
# tests/security/test_watchdog_windows_nest.py, and this one — roughly thirteen
# of them. The pair that cost the run was in none of the three, because a
# hand-written test only exists where somebody thought of the pair.
#
# So the relation moves into DATA: `must_exceed` on the row, one generated
# assertion per declared pair. Adding a relation is now a one-line edit to the
# registry rather than a new test function nobody remembers to write.
#
# HONEST LIMIT, and it is the same one #1366 names: this checks the pairs
# somebody declared. An undeclared pair is still an unchecked pair, and the
# 240/600 inversion was undeclared — DOOM_STALL_GRACE_S's row did not contain
# the strings "acp" or "idle" anywhere. `role` exists to make the sweep for the
# rest tractable (only outer roles over inner roles can produce the failure);
# that sweep is #1366 item 3 and is NOT done here.
# ---------------------------------------------------------------------------

_BY_ATTR = {e.attribute: e for e in REGISTRY}

#: (outer, inner) pairs flattened from the table, for parametrisation.
_RELATIONS: tuple[tuple[str, str], ...] = tuple(
    (entry.attribute, target) for entry in REGISTRY for target in entry.must_exceed
)

#: Roles that observe a phase from OUTSIDE it, and roles that own a phase from within.
#: Used by the undeclared-pair sweep (#1366 item 3) to collapse the pair space; NOT a
#: constraint on who may declare a relation — see the deleted test below for why.
_OUTER_ROLES = frozenset({"watchdog", "budget"})
_INNER_ROLES = frozenset({"judge", "probe", "backoff", "grain"})


def test_every_entry_declares_a_role_from_the_closed_vocabulary():
    """A row without a role cannot be swept for undeclared nestings (#1366 item 3)."""
    unknown = [(e.attribute, e.role) for e in REGISTRY if e.role not in ROLES]
    assert not unknown, (
        f"rows carry a role outside the vocabulary {sorted(ROLES)}: {unknown}. "
        "The role is chosen by what the duration DOES, never by its magnitude."
    )


def test_the_role_vocabulary_covers_both_sides_of_every_nesting():
    """The taxonomy is only useful if every role is classifiable as outer or inner."""
    assert _OUTER_ROLES | _INNER_ROLES == set(ROLES), (
        "a role exists that is neither an outer window nor an inner phase — the "
        "undeclared-pair sweep cannot reason about it"
    )


@pytest.mark.parametrize("outer,inner", _RELATIONS, ids=[f"{o}>{i}" for o, i in _RELATIONS])
def test_a_declared_relation_holds(outer: str, inner: str):
    """The outer duration must STRICTLY exceed the inner one it wraps or observes.

    Equality is a failure, not a pass: two windows that expire together race, and
    which one is observed first is not something this system decides.
    """
    assert inner in _BY_ATTR, (
        f"{outer}.must_exceed names '{inner}', which is not a registered attribute. "
        "A relation pointing at nothing is worse than no relation — it reads as checked."
    )
    o, i = _BY_ATTR[outer], _BY_ATTR[inner]
    assert o.seconds > i.seconds, (
        f"{outer} = {o.seconds:g}s does NOT exceed {inner} = {i.seconds:g}s.\n"
        f"  outer role={o.role} on {o.surface}\n"
        f"  inner role={i.role} on {i.surface}\n"
        "  Lesson 221: the shorter window silently wins and the longer one is fiction."
    )


# A test asserting "only a `budget`/`watchdog` may declare must_exceed" was written here
# and DELETED the same hour, because the data refuted it within a minute of running:
#
#   PLAN_RESPONSE_TIMEOUT_S (judge) > PROMPT_RESPONSE_TIMEOUT_S (judge)
#       — a family ordering, not a nesting: PLAN is the long-running variant of the same
#         per-message deadline, and neither wraps the other.
#   PENDING_RUN_BUDGET_FRESH_S (grain) > PLAN_RESPONSE_TIMEOUT_S (judge)
#       — a freshness window that must SPAN a phase without owning it (#1359).
#
# So `must_exceed` means exactly what it says — this number must be larger than that one —
# and the role does NOT constrain who may declare it. The role's job is to make the sweep
# for UNDECLARED pairs tractable (#1366 item 3), not to police declarations. Recording the
# refutation rather than quietly deleting it: the model was plausible, it was wrong, and a
# test that encodes a model I cannot defend is worse than no test at all.


def test_no_entry_declares_a_relation_against_itself():
    """A self-relation can never hold and would fail confusingly rather than loudly."""
    self_refs = [o for o, i in _RELATIONS if o == i]
    assert not self_refs, f"rows declare must_exceed against themselves: {self_refs}"


def test_at_least_the_three_inversions_of_20260809_are_now_declared():
    """The relations that cost runs must be DATA, not prose — the whole point of #1366.

    Each of these was findable by arithmetic the day it shipped and was found by
    accident instead. If a future edit drops the declaration, this fails loudly
    rather than quietly returning the pair to the undeclared pool.
    """
    required = {
        ("PA_HANDSHAKE_BUDGET_S", "PA_HANDSHAKE_TIMEOUT_S"),          # #1353
        ("PENDING_RUN_BUDGET_FRESH_S", "PLAN_RESPONSE_TIMEOUT_S"),    # #1359
        ("DOOM_STALL_GRACE_S", "ACP_IDLE_TIMEOUT_S"),                 # #1366
    }
    missing = required - set(_RELATIONS)
    assert not missing, f"the 2026-08-09 inversions are no longer declared: {missing}"


def test_the_generated_check_catches_the_inversion_that_actually_happened():
    """TOGGLE PROOF against the REAL pre-#1366 values, not invented ones.

    A green suite here is worth nothing unless the mechanism fires on the pair that
    cost the run. 240 vs 600 is what shipped and what this block exists to make
    impossible; the assertion below is the same comparison the parametrised test
    performs, run against the historical numbers.
    """
    doom_before, idle = 240.0, 600.0
    assert not (doom_before > idle), (
        "the pre-#1366 doom window (240s) must NOT satisfy the relation against the "
        "coder's 600s idle judge — if this passes, the comparison has been inverted"
    )
    assert _BY_ATTR["DOOM_STALL_GRACE_S"].seconds > _BY_ATTR["ACP_IDLE_TIMEOUT_S"].seconds, (
        "and the CURRENT registered values must satisfy it — otherwise the fix regressed"
    )


def test_capture_sweep_budget_fits_exec_smoke():
    """#1394 items 1-2. The multi-page capture's ceiling must fit inside the timeout that
    KILLS it, and that reconciliation has to be a test rather than arithmetic in a comment.

    The two bounds were set by different changes in different repositories with nothing
    checking one against the other: the capture's per-page waits live in
    ``agentic-setup/scripts/capture-web-cdp.mjs`` and the containing budget in this repo.
    At the capture's 12-page cap the worst case reached ~144 s against a 120 s budget.

    Being KILLED is the failure, not being slow: the caller's timeout takes the whole capture,
    so the per-page error text the sweep exists to collect dies with it — and on 2026-08-15
    that text was where the real defect lived while the published finding was a favicon 404.
    """
    from shared.fleet import swap_ops

    ENTRY_WAIT_S = 20.0   # capture-web-cdp.mjs: Math.min(timeoutMs, 20000)
    SETTLE_S = 1.2        # capture-web-cdp.mjs: settleMs default

    worst_case = ENTRY_WAIT_S + SETTLE_S + swap_ops.WEB_CAPTURE_SWEEP_BUDGET_S
    assert worst_case <= swap_ops.EXEC_SMOKE_TIMEOUT_S, (
        f"the capture can run {worst_case:.1f}s against a "
        f"{swap_ops.EXEC_SMOKE_TIMEOUT_S:.1f}s caller budget. Raise EXEC_SMOKE_TIMEOUT_S or "
        f"lower WEB_CAPTURE_SWEEP_BUDGET_S — deliberately, once, with the trade-off written "
        f"into the registry row, never by letting the sweep be killed mid-walk."
    )
    assert swap_ops.WEB_CAPTURE_SWEEP_BUDGET_S >= 60.0, (
        "a sweep budget under 60s cannot reach B9's six pages at their measured pace"
    )


def test_the_sweep_budget_is_PASSED_to_the_capture_not_duplicated_there():
    """The owner is this repo's registered constant, and it has to actually travel.

    A registry row nothing reads is a number with two homes wearing one label — which is the
    defect #1394 filed, not the fix for it. This asserts the invocation carries it.
    """
    import inspect

    from shared.fleet import swap_ops

    src = inspect.getsource(swap_ops.real_web_console_capture)
    assert "-SweepBudgetMs" in src, (
        "the capture invocation no longer passes the sweep budget, so the registered "
        "constant is decorative and the capture is back on its own private default"
    )
    assert "WEB_CAPTURE_SWEEP_BUDGET_S" in src, (
        "the invocation passes a sweep budget that is not the registered one"
    )
