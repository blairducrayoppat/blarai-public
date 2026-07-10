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
