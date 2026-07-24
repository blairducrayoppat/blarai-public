"""Locks for the C3 heartbeat AO-property plumbing (#845 limb 6, design §3.2).

The launcher's ``build_heartbeat`` factory reads every ``[coordinator]`` heartbeat
value off the STARTED AO service (single source of truth — never a second TOML
parse, mirroring ``coordinator_enabled``). These locks pin the property surface's
fail-closed pre-``start()`` defaults and the resolved-config pass-through — the
seam the factory's four dormancy shapes stand on.
"""

from __future__ import annotations

from types import SimpleNamespace

from services.assistant_orchestrator.src.entrypoint import (
    AssistantOrchestratorService,
)


def _service_with(resolved) -> AssistantOrchestratorService:
    """A bare service instance with only the property substrate set — the
    properties read nothing but ``self._resolved_config``, so no boot/model
    machinery is touched (the same shape the launcher sees pre-``start()``)."""
    service = AssistantOrchestratorService.__new__(AssistantOrchestratorService)
    service._resolved_config = resolved  # noqa: SLF001 — the property substrate
    return service


class TestPreStartFailClosedDefaults:
    """Before start() resolves the config: flag OFF, registered cadence,
    shadow TRUE — the safe value for every key."""

    def setup_method(self) -> None:
        self.service = _service_with(None)

    def test_heartbeat_enabled_defaults_false(self) -> None:
        assert self.service.coordinator_heartbeat_enabled is False

    def test_cadence_defaults_match_the_registry(self) -> None:
        from shared.coordinator.config import (
            DEFAULT_BATTERY_MULTIPLIER,
            DEFAULT_BOOT_GRACE_S,
            DEFAULT_HEARTBEAT_INTERVAL_S,
            DEFAULT_OVERNIGHT_WINDOW,
        )

        assert (
            self.service.coordinator_heartbeat_interval_s
            == DEFAULT_HEARTBEAT_INTERVAL_S
        )
        assert (
            self.service.coordinator_heartbeat_battery_multiplier
            == DEFAULT_BATTERY_MULTIPLIER
        )
        assert (
            self.service.coordinator_heartbeat_boot_grace_s == DEFAULT_BOOT_GRACE_S
        )
        assert self.service.coordinator_overnight_window == DEFAULT_OVERNIGHT_WINDOW

    def test_operator_absent_defaults_false(self) -> None:
        assert self.service.coordinator_operator_absent is False

    def test_shadow_mode_defaults_true(self) -> None:
        """The inverted fail-closed direction: shadow TRUE is the safe value —
        an unresolved config must never read as live output."""
        assert self.service.coordinator_shadow_mode is True


class TestResolvedPassThrough:
    def test_resolved_values_thread_through(self) -> None:
        service = _service_with(
            SimpleNamespace(
                coordinator_heartbeat_enabled=True,
                coordinator_heartbeat_interval_s=1200.0,
                coordinator_heartbeat_battery_multiplier=6.0,
                coordinator_heartbeat_boot_grace_s=120.0,
                coordinator_overnight_window="22:00-08:00",
                coordinator_operator_absent=True,
                coordinator_shadow_mode=False,
            )
        )
        assert service.coordinator_heartbeat_enabled is True
        assert service.coordinator_heartbeat_interval_s == 1200.0
        assert service.coordinator_heartbeat_battery_multiplier == 6.0
        assert service.coordinator_heartbeat_boot_grace_s == 120.0
        assert service.coordinator_overnight_window == "22:00-08:00"
        assert service.coordinator_operator_absent is True
        assert service.coordinator_shadow_mode is False

    def test_missing_attributes_stay_fail_closed(self) -> None:
        """A resolved config predating these fields (attribute absent) resolves
        every key to its safe value — the same getattr-default discipline the
        sibling coordinator properties use."""
        service = _service_with(SimpleNamespace())
        assert service.coordinator_heartbeat_enabled is False
        assert service.coordinator_shadow_mode is True
        assert service.coordinator_heartbeat_interval_s == 900.0


class TestHousingDataclassDefaults:
    def test_dataclass_ships_dormant_defaults(self) -> None:
        """The declared field defaults (the housing dataclass has required
        core fields, so the DECLARED defaults are asserted via
        ``dataclasses.fields`` rather than a bare construction)."""
        import dataclasses

        from services.assistant_orchestrator.src.entrypoint import (
            AssistantOrchestratorEntrypointConfig,
        )

        defaults = {
            f.name: f.default
            for f in dataclasses.fields(AssistantOrchestratorEntrypointConfig)
        }
        assert defaults["coordinator_heartbeat_enabled"] is False
        assert defaults["coordinator_shadow_mode"] is True
        assert defaults["coordinator_heartbeat_interval_s"] == 900.0
        assert defaults["coordinator_heartbeat_battery_multiplier"] == 4.0
        assert defaults["coordinator_heartbeat_boot_grace_s"] == 300.0
        assert defaults["coordinator_overnight_window"] == "23:00-09:00"
        assert defaults["coordinator_operator_absent"] is False
