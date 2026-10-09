"""#1548: simulate-first as a fourth route outcome — reachable, unused, and barred where it matters.

Accepted by the LA 2026-09-17 against a recommendation to decline. It ships **dormant**
behind a config flag and goes live only at an LA-present ceremony.

Three independent locks, and the ticket is explicit that the bar is a test and not a
comment:

  1. The config flag is off in the shipped default.
  2. No tool declares a dry run at merge — deny-by-default, so the outcome is reachable
     and unused, which is the correct starting state under security_by_design principle 2.
     REACHABLE is load-bearing and was FALSE when this file was first committed
     (``d71fe7f0``): the helpers had no caller, the flag gated nothing, and the
     capabilities declaration passed only because the literal ``simulate_first``
     appeared in ``route_simulate_first``'s own ``def`` line — a self-certifying
     loop. ``TestTheOutcomeIsWiredIntoTheToolLoop`` is what makes the word true.
  3. `web_search` is BARRED outright, because a dry run of a search is either the query
     and host shown before sending — which the escalation prompt already does — or the
     search actually performed and its results shown before approval, **which commits the
     exact egress the gate exists to control**.

Each lock ships with a toggle proving the probe fails when the control is off. A lock that
can only ever pass is indistinguishable from a lock that cannot reach its subject.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from services.assistant_orchestrator.src import tools

_REPO = Path(__file__).resolve().parents[2]
_CONFIG = _REPO / "services" / "assistant_orchestrator" / "config" / "default.toml"


def _declare(monkeypatch: pytest.MonkeyPatch, *tool_names: str) -> None:
    """Make ``tool_names`` declare a dry run, the way production does.

    DECLARING IS REGISTERING A REHEARSAL (#1548 executor). These toggles used to
    write a name into ``tools._SIMULATE_FIRST_TOOLS``, a hand-maintained list
    that sat apart from any implementation — so they proved a tool could be
    routed while nothing behind it could actually rehearse, which is precisely
    the state the registry abolished. They register a real rehearsal now, so the
    toggle exercises the path production takes.

    The registry is process-global. The module's dict is swapped for a COPY of
    whatever it currently holds and the rehearsals go into the copy, so teardown
    restores the real one by identity — never by re-assigning a value this
    helper guessed. Restoring a hardcoded empty set instead of the saved one is
    how #1584's toggles silently killed the tripwire they were written to prove
    alive.
    """
    from shared.governance import dry_run as _dry_run

    monkeypatch.setattr(_dry_run, "_DRY_RUNS", dict(_dry_run._DRY_RUNS))
    for name in tool_names:
        _dry_run.register_dry_run(
            name,
            lambda args: _dry_run.DryRunResult(
                action="erase", unit="documents", affected_count=0
            ),
        )


class TestTheCapabilityIsDormant:
    """Lock 1: the shipped flag is off."""

    def test_shipped_config_has_simulate_first_disabled(self) -> None:
        cfg = tomllib.loads(_CONFIG.read_text(encoding="utf-8"))

        assert cfg["simulate_first"]["enabled"] is False, (
            "simulate-first is LIVE in the shipped config. It changes what the assistant "
            "can do and merges DORMANT — flipping it is an LA-present ceremony, not a "
            "commit."
        )

    def test_the_flag_actually_gates_the_route(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """TOGGLE for lock 1. Without this, a flag nothing reads would pass the test
        above while gating nothing."""
        _declare(monkeypatch, "probe_tool")
        assert tools.route_simulate_first("probe_tool", enabled=False) is None
        assert tools.route_simulate_first("probe_tool", enabled=True) == (
            tools.SIMULATE_FIRST
        )


class TestNoToolDeclaresADryRunAtMerge:
    """Lock 2: deny-by-default, and the declaring set is empty."""

    def test_nothing_is_declared_at_IMPORT(self) -> None:
        """Importing the tool module must register no rehearsal.

        Declaring is now REGISTERING one (#1548 executor), so this asks the
        registry rather than the retired frozenset. Production registers at
        service startup; if a rehearsal appears merely from importing, a bare
        interpreter would have a routable tool and the dormancy would be a
        property of what happened to be imported.
        """
        from shared.governance import dry_run as _dry_run

        assert _dry_run.registered_dry_runs() == frozenset(), (
            "a tool declares a dry run at import time. That is a capability "
            "change: confirm it satisfies the selector-not-target rule and that "
            "the LA has approved it."
        )

    def test_the_retired_frozenset_stays_empty(self) -> None:
        """`_SIMULATE_FIRST_TOOLS` is retired as a source of truth and nothing
        reads it. Writing to it again would recreate the two-lists-that-must-agree
        divergence the registry replaced, silently — so it is pinned empty."""
        assert tools._SIMULATE_FIRST_TOOLS == frozenset(), (
            "something is writing to the retired declaring set. Register a "
            "rehearsal with shared.governance.dry_run instead; a name there has "
            "nothing behind it."
        )

    @pytest.mark.parametrize("tool_name", sorted(tools._REGISTRY))
    def test_no_live_tool_is_routable(self, tool_name: str) -> None:
        """DERIVED from the registry, not a hand-written list.

        This was eight names typed out. `curate_knowledge` became the ninth
        live tool and would have been absent from the list, so the lock would
        have kept passing while no longer covering the tool most worth covering
        — the only irreversible one. A parametrisation that does not grow with
        its subject is a lock that quietly narrows.
        """
        assert tools.declares_dry_run(tool_name) is False
        assert tools.route_simulate_first(tool_name, enabled=True) is None

    def test_an_unknown_tool_is_not_routable(self) -> None:
        """A tool added next year is not routable until someone adds it deliberately."""
        assert tools.declares_dry_run("some_tool_invented_later") is False

    def test_a_declaring_tool_WOULD_be_routable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """TOGGLE for lock 2. Without this, a route function that always returned None
        would pass every test above while the outcome was unreachable rather than
        merely unused — and the ticket's 'reachable and unused' claim would be false."""
        _declare(monkeypatch, "probe_tool")
        assert tools.declares_dry_run("probe_tool") is True
        assert tools.route_simulate_first("probe_tool", enabled=True) == (
            tools.SIMULATE_FIRST
        )


class TestWebSearchIsBarredOutright:
    """Lock 3: the bar is a test, not a comment — the ticket says so explicitly."""

    def test_web_search_is_in_the_barred_set(self) -> None:
        assert "web_search" in tools._SIMULATE_FIRST_BARRED

    def test_web_search_is_not_routable_even_if_it_declares(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """THE LOCK. The bar must WIN over a declaration, or a later edit adding
        web_search to the declaring set would silently enable a dry run of the only
        tool that leaves the machine."""
        _declare(monkeypatch, "web_search")
        assert tools.declares_dry_run("web_search") is False, (
            "web_search became routable by declaring a dry run. A dry run of the "
            "only egress tool performs the egress it is meant to gate."
        )
        assert tools.route_simulate_first("web_search", enabled=True) is None

    def test_the_bar_is_reachable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """TOGGLE for lock 3. A non-barred tool with the same declaration IS routable,
        so the refusal above comes from the bar and not from the route being dead."""
        _declare(monkeypatch, "web_search", "probe_tool")
        assert tools.route_simulate_first("web_search", enabled=True) is None
        assert tools.route_simulate_first("probe_tool", enabled=True) == (
            tools.SIMULATE_FIRST
        )

    def test_every_egress_tool_is_barred(self) -> None:
        """The bar must cover the egress SET, not just today's single member — a second
        egress tool added later must not be routable by default."""
        for egress_tool in tools._EGRESS_TOOLS:
            assert egress_tool in tools._SIMULATE_FIRST_BARRED, (
                f"{egress_tool!r} is an egress tool and is NOT barred from "
                "simulate-first. A dry run of an egress tool performs the egress."
            )


class TestTheOutcomeIsDistinctFromTheOtherThree:
    """A consumer that does not know the fourth outcome must not mistake it for one of
    the three that exist."""

    def test_simulate_first_is_not_allow_deny_or_escalate(self) -> None:
        assert tools.SIMULATE_FIRST not in {"ALLOW", "DENY", "ESCALATE", None}

    def test_the_route_returns_None_rather_than_a_permissive_value(self) -> None:
        """The refusal shape the ticket specifies: a tool that does not declare is NOT
        routed here and is not thereby allowed. `None` means 'this outcome does not
        apply', leaving the caller's existing verdict untouched."""
        assert tools.route_simulate_first("calculate", enabled=True) is None


class TestTheOutcomeIsWiredIntoTheToolLoop:
    """The lock the first commit of this file did not have.

    Every test above drives ``tools`` directly, and all of them passed while the
    three helpers had ZERO production callers. A control nothing calls is not a
    control, and the dormancy claim it supports is not dormancy — it is absence
    wearing a flag. These tests drive the entrypoint instead.
    """

    def test_the_flag_resolves_off_the_real_config(self) -> None:
        """The go-live switch is a RESOLVED SETTING, not a TOML key nothing reads."""
        from services.assistant_orchestrator.src.entrypoint import (
            AssistantOrchestratorEntrypointConfig,
        )

        assert hasattr(AssistantOrchestratorEntrypointConfig, "simulate_first_enabled") or (
            "simulate_first_enabled" in AssistantOrchestratorEntrypointConfig.__annotations__
        ), (
            "[simulate_first].enabled resolves to no setting. Flipping it at a "
            "go-live ceremony would change nothing — a dead switch wearing a live "
            "label."
        )

    def test_the_route_is_consulted_before_tools_execute(self) -> None:
        """THE WIRING LOCK. The route must be called on the dispatch path, above
        ``tools.execute``. Asserted against the source because the tool loop is
        not independently constructible; a behavioural test here would need the
        whole gateway, and that cost is why the original commit shipped with no
        lock at all."""
        entry = (
            _REPO / "services" / "assistant_orchestrator" / "src" / "entrypoint.py"
        ).read_text(encoding="utf-8")

        call = entry.find("tools.route_simulate_first(")
        execute = entry.find("tool_result = tools.execute(")

        assert call != -1, (
            "route_simulate_first has no caller in the AO entrypoint. The outcome "
            "is unreachable, not merely unused, and the config flag gates nothing."
        )
        assert execute != -1, "the dispatch site moved; this lock needs re-aiming."
        assert call < execute, (
            "simulate-first is consulted AFTER the real execution. A dry run that "
            "runs the action first is not a dry run."
        )

    def test_reaching_the_outcome_rehearses_and_ASKS_before_executing(self) -> None:
        """SUPERSEDED BEHAVIOUR, deliberately (#1548 executor).

        This test used to assert ``simulate_first_unimplemented`` — the routed
        dispatch refusing because no dry-run executor existed. The executor
        exists now, so the branch rehearses, records the rehearsal, and asks the
        operator. What must remain true is the shape: a routed action reaches
        ``tools.execute`` ONLY through an explicit operator approval, and every
        other path out of the branch terminates the dispatch. A fall-through
        would report a simulation and perform the real call, which is the
        inversion this outcome exists to prevent.
        """
        entry = (
            _REPO / "services" / "assistant_orchestrator" / "src" / "entrypoint.py"
        ).read_text(encoding="utf-8")

        call = entry.find("tools.route_simulate_first(")
        execute = entry.find("tool_result = tools.execute(")
        between = entry[call:execute]

        assert "execute_dry_run(" in between, (
            "the branch does not rehearse; it must show the operator the effect "
            "before the real call"
        )
        assert "_escalation_approved_by_operator(" in between, (
            "the branch does not ask the operator. A rehearsal nobody is shown "
            "is a delay, not a control."
        )
        assert "DENY_SIMULATE_FIRST_REHEARSAL_FAILED" in between, (
            "a rehearsal that cannot run must REFUSE, not fall through"
        )
        assert "DENY_SIMULATE_FIRST_NOT_APPROVED" in between, (
            "a rehearsal that is not approved must REFUSE"
        )
        assert between.count("break") >= 2, (
            "both refusal paths must terminate the dispatch"
        )

    def test_only_consent_summary_crosses_to_the_operator_surface(self) -> None:
        """The rehearsal's ``detail`` holds the operator's own content (document
        titles). Only ``consent_summary`` — rendered from typed fields and
        incapable of carrying free text — may reach the OS consent dialog."""
        entry = (
            _REPO / "services" / "assistant_orchestrator" / "src" / "entrypoint.py"
        ).read_text(encoding="utf-8")
        call = entry.find("tools.route_simulate_first(")
        execute = entry.find("tool_result = tools.execute(")
        between = entry[call:execute]

        # CODE, not prose. A text scan of this region matches the explanatory
        # comment that names `_rehearsal.detail` as the thing which must NOT
        # cross, and fails for the wrong reason — which is what it did on its
        # first run.
        code = "\n".join(
            line for line in between.splitlines()
            if not line.strip().startswith("#")
        )

        assert "action_summary=_rehearsal.consent_summary" in between
        assert ".detail" not in code, (
            "the rehearsal's detail — which carries the operator's document "
            "titles — is referenced in the consent path"
        )
