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

from shared.timeout_registry import BACKLOG, REGISTRY, live_value, registry_names

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
            seconds=1.0, surface="s", incident="i", rationale="r", review="v"),
        TimeoutEntry(  # dataclass field with no such name
            name="x", module="shared.fleet.dispatch",
            attribute="FleetDispatchConfig.not_a_field",
            seconds=1.0, surface="s", incident="i", rationale="r", review="v"),
        TimeoutEntry(  # function param with no default
            name="x", module="shared.fleet.guest_oracle",
            attribute="execute_snapshot(snapshot_zip)",
            seconds=1.0, surface="s", incident="i", rationale="r", review="v"),
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
