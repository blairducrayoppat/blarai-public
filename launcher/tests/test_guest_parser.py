"""
Tests for the Guest Parser Lifecycle Manager (#655 Stage C)
============================================================
All Hyper-V / PowerShell interaction is mocked (the test_vm_manager.py
pattern); no VM, no VHDX, no real vsock socket is ever touched.  Covers:

  * config parsing (defaults, fail-closed validation, GUID/port lock)
  * the deploy → start → health → stop state machine
  * every fail-closed path (deploy failure, health timeout, unbound channel,
    probe failure/crash, service-crash detection)
  * the parser-channel seam registry
  * the launcher bring-up helper (_maybe_start_guest_parser)
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from launcher.guest_parser import (
    GuestParserConfig,
    GuestParserConfigError,
    GuestParserManager,
    GuestParserState,
    default_config_path,
    get_guest_parser_manager,
    guest_parser_available,
    hv_service_guid_for_port,
    load_guest_parser_config,
    set_guest_parser_manager,
)
from launcher.parser_channel_seam import (
    ParserEndpoint,
    clear_parser_channel_bindings,
    get_parser_health_probe,
    get_parser_stop_signal,
    register_parser_health_probe,
    register_parser_stop_signal,
)
from launcher.vm_manager import VMState


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_seam_and_singleton():
    """Every test starts from the fail-closed default: nothing bound/parked."""
    clear_parser_channel_bindings()
    set_guest_parser_manager(None)
    yield
    clear_parser_channel_bindings()
    set_guest_parser_manager(None)


def _config(**overrides) -> GuestParserConfig:
    base = dict(
        enabled=True,
        vm_name="TestVM",
        guest_root="/opt/blarai/parser",
        vsock_port=50001,
        service_guid=hv_service_guid_for_port(50001),
        service_source_dir="services/cleaner/guest",
        entry_module="blarai_guest_parser",
        deploy_timeout_s=30.0,
        health_timeout_s=5.0,
        health_poll_interval_s=0.01,
        bridge_python="",
    )
    base.update(overrides)
    return GuestParserConfig(**base)


def _manager(
    config: GuestParserConfig,
    repo_root: Path,
    *,
    transport_check=None,
) -> GuestParserManager:
    fake_clock = {"t": 0.0}

    def clock() -> float:
        return fake_clock["t"]

    def sleep(seconds: float) -> None:
        fake_clock["t"] += seconds

    return GuestParserManager(
        config,
        repo_root=repo_root,
        vm_id="9c7f986f-7afd-48b0-af5b-2c330df6b38f",
        transport_check=transport_check or (lambda endpoint: True),
        clock=clock,
        sleep=sleep,
    )


def _make_source(repo_root: Path, rel: str = "services/cleaner/guest") -> Path:
    source = repo_root / rel
    source.mkdir(parents=True, exist_ok=True)
    (source / "blarai_guest_parser.py").write_text(
        "# parser service placeholder\n", encoding="utf-8"
    )
    (source / "sub").mkdir(exist_ok=True)
    (source / "sub" / "helper.py").write_text("# helper\n", encoding="utf-8")
    return source


# ---------------------------------------------------------------------------
# hv_sock GUID helper
# ---------------------------------------------------------------------------


class TestHvServiceGuid:
    def test_port_50001_template(self) -> None:
        assert (
            hv_service_guid_for_port(50001)
            == "0000c351-facb-11e6-bd58-64006a7986d3"
        )

    def test_port_50000_matches_runtime_constant(self) -> None:
        from shared.constants import VSOCK_PORT, VSOCK_SERVICE_GUID

        assert hv_service_guid_for_port(VSOCK_PORT) == VSOCK_SERVICE_GUID


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


class TestLoadGuestParserConfig:
    def test_shipped_default_config_is_disabled(self) -> None:
        """The committed launcher config keeps the parser DORMANT by default."""
        config = load_guest_parser_config()
        assert config.enabled is False
        assert config.vm_name == "BlarAI-Orchestrator"
        assert config.vsock_port == 50001
        assert config.service_guid == hv_service_guid_for_port(50001)
        assert config.guest_root == "/opt/blarai/parser"

    def test_shipped_default_config_path_exists(self) -> None:
        assert default_config_path().is_file()

    def test_missing_file_fails_closed(self, tmp_path: Path) -> None:
        with pytest.raises(GuestParserConfigError) as exc_info:
            load_guest_parser_config(tmp_path / "nope.toml")
        assert exc_info.value.code == "GP_CONFIG_MISSING"

    def test_unparseable_toml_fails_closed(self, tmp_path: Path) -> None:
        bad = tmp_path / "default.toml"
        bad.write_text("[guest_parser\nenabled = ", encoding="utf-8")
        with pytest.raises(GuestParserConfigError) as exc_info:
            load_guest_parser_config(bad)
        assert exc_info.value.code == "GP_CONFIG_UNPARSEABLE"

    def test_empty_section_yields_safe_defaults(self, tmp_path: Path) -> None:
        cfg = tmp_path / "default.toml"
        cfg.write_text("[guest_parser]\n", encoding="utf-8")
        config = load_guest_parser_config(cfg)
        assert config.enabled is False  # dormant unless explicitly enabled
        assert config.vsock_port == 50001

    def test_enabled_true_parses(self, tmp_path: Path) -> None:
        cfg = tmp_path / "default.toml"
        cfg.write_text(
            "[guest_parser]\nenabled = true\n", encoding="utf-8"
        )
        assert load_guest_parser_config(cfg).enabled is True

    def test_shipped_default_is_resident(self) -> None:
        """The committed config uses the resident model (#655): Copy-VMFile is
        retired, so the launcher skips deploy() and goes straight to start()."""
        assert load_guest_parser_config().resident is True

    def test_resident_defaults_false_for_empty_section(self, tmp_path: Path) -> None:
        cfg = tmp_path / "default.toml"
        cfg.write_text("[guest_parser]\n", encoding="utf-8")
        assert load_guest_parser_config(cfg).resident is False

    def test_resident_explicit_false_parses(self, tmp_path: Path) -> None:
        cfg = tmp_path / "default.toml"
        cfg.write_text(
            "[guest_parser]\nresident = false\n", encoding="utf-8"
        )
        assert load_guest_parser_config(cfg).resident is False

    def test_env_override_enables_on_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """BLARAI_GUEST_PARSER_ENABLED is an ON-ONLY, reversible go-live override:
        it turns the disabled-by-default config ON, and never forces it off."""
        cfg = tmp_path / "default.toml"
        cfg.write_text("[guest_parser]\nenabled = false\n", encoding="utf-8")
        # No var -> committed default (disabled).
        monkeypatch.delenv("BLARAI_GUEST_PARSER_ENABLED", raising=False)
        assert load_guest_parser_config(cfg).enabled is False
        # Truthy override values flip it ON.
        for val in ("1", "true", "TRUE", "yes", "on"):
            monkeypatch.setenv("BLARAI_GUEST_PARSER_ENABLED", val)
            assert load_guest_parser_config(cfg).enabled is True, val
        # A non-truthy value does NOT enable (ON-only — never silently on).
        monkeypatch.setenv("BLARAI_GUEST_PARSER_ENABLED", "0")
        assert load_guest_parser_config(cfg).enabled is False

    def test_env_override_does_not_force_off(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The override only ever turns ON: a config that is enabled=true stays
        enabled even when the env var is a falsey value (it never disables)."""
        cfg = tmp_path / "default.toml"
        cfg.write_text("[guest_parser]\nenabled = true\n", encoding="utf-8")
        monkeypatch.setenv("BLARAI_GUEST_PARSER_ENABLED", "0")
        assert load_guest_parser_config(cfg).enabled is True

    def test_guid_port_mismatch_fails_closed(self, tmp_path: Path) -> None:
        """The #615 silent-divergence lock: GUID must match the port template."""
        cfg = tmp_path / "default.toml"
        cfg.write_text(
            "[guest_parser]\n"
            "vsock_port = 50001\n"
            'service_guid = "0000c350-facb-11e6-bd58-64006a7986d3"\n',
            encoding="utf-8",
        )
        with pytest.raises(GuestParserConfigError) as exc_info:
            load_guest_parser_config(cfg)
        assert exc_info.value.code == "GP_CONFIG_GUID_MISMATCH"

    def test_port_out_of_range_fails_closed(self, tmp_path: Path) -> None:
        cfg = tmp_path / "default.toml"
        cfg.write_text("[guest_parser]\nvsock_port = 0\n", encoding="utf-8")
        with pytest.raises(GuestParserConfigError) as exc_info:
            load_guest_parser_config(cfg)
        assert exc_info.value.code == "GP_CONFIG_PORT_INVALID"

    def test_non_bool_enabled_fails_closed(self, tmp_path: Path) -> None:
        cfg = tmp_path / "default.toml"
        cfg.write_text('[guest_parser]\nenabled = "yes"\n', encoding="utf-8")
        with pytest.raises(GuestParserConfigError) as exc_info:
            load_guest_parser_config(cfg)
        assert exc_info.value.code == "GP_CONFIG_TYPE_INVALID"

    def test_non_positive_timeout_fails_closed(self, tmp_path: Path) -> None:
        cfg = tmp_path / "default.toml"
        cfg.write_text(
            "[guest_parser]\nhealth_timeout_s = 0.0\n", encoding="utf-8"
        )
        with pytest.raises(GuestParserConfigError) as exc_info:
            load_guest_parser_config(cfg)
        assert exc_info.value.code == "GP_CONFIG_TIMEOUT_INVALID"


# ---------------------------------------------------------------------------
# Deploy state machine
# ---------------------------------------------------------------------------


class TestDeploy:
    @patch("launcher.guest_parser.copy_file_to_vm", return_value=True)
    @patch(
        "launcher.guest_parser.is_guest_service_interface_enabled",
        return_value=True,
    )
    @patch("launcher.guest_parser.get_vm_state", return_value=VMState.RUNNING)
    def test_deploy_success(
        self, _state, _gsi, mock_copy, tmp_path: Path
    ) -> None:
        _make_source(tmp_path)
        manager = _manager(_config(), tmp_path)

        assert manager.deploy() is True
        assert manager.state == GuestParserState.DEPLOYED
        assert manager.failure is None

        # Protocol order: bundle.zip, bundle.sha256, deploy.trigger LAST —
        # the trigger is the guest supervisor's commit point.
        destinations = [
            call.kwargs["destination_path"] for call in mock_copy.call_args_list
        ]
        assert destinations == [
            "/opt/blarai/parser/incoming/bundle.zip",
            "/opt/blarai/parser/incoming/bundle.sha256",
            "/opt/blarai/parser/incoming/deploy.trigger",
        ]

    @patch("launcher.guest_parser.copy_file_to_vm", return_value=True)
    @patch(
        "launcher.guest_parser.is_guest_service_interface_enabled",
        return_value=True,
    )
    @patch("launcher.guest_parser.get_vm_state", return_value=VMState.RUNNING)
    def test_bundle_contains_service_files_and_conf(
        self, _state, _gsi, mock_copy, tmp_path: Path
    ) -> None:
        _make_source(tmp_path)
        captured: dict[str, bytes] = {}

        def grab(*, source_path, destination_path, **_kwargs):
            captured[destination_path] = Path(source_path).read_bytes()
            return True

        mock_copy.side_effect = grab
        manager = _manager(_config(), tmp_path)
        assert manager.deploy() is True

        bundle = captured["/opt/blarai/parser/incoming/bundle.zip"]
        with zipfile.ZipFile(io.BytesIO(bundle)) as zip_obj:
            names = set(zip_obj.namelist())
            assert "blarai_guest_parser.py" in names
            assert "sub/helper.py" in names
            assert "service.conf" in names
            conf = zip_obj.read("service.conf").decode("utf-8")
            assert "ENTRY_MODULE=blarai_guest_parser" in conf
            assert "VSOCK_PORT=50001" in conf

        # The shipped hash file verifies the shipped bundle (sha256sum format).
        import hashlib

        hash_line = captured["/opt/blarai/parser/incoming/bundle.sha256"].decode(
            "utf-8"
        )
        expected = hashlib.sha256(bundle).hexdigest()
        assert hash_line == f"{expected}  bundle.zip\n"

        trigger = json.loads(
            captured["/opt/blarai/parser/incoming/deploy.trigger"]
        )
        assert trigger["bundle_sha256"] == expected

    def test_deploy_refused_when_disabled(self, tmp_path: Path) -> None:
        manager = _manager(_config(enabled=False), tmp_path)
        assert manager.deploy() is False
        assert manager.state == GuestParserState.FAILED
        assert manager.failure["code"] == "GP_DISABLED"

    @patch("launcher.guest_parser.get_vm_state", return_value=VMState.OFF)
    def test_deploy_fail_closed_vm_not_running(
        self, _state, tmp_path: Path
    ) -> None:
        _make_source(tmp_path)
        manager = _manager(_config(), tmp_path)
        assert manager.deploy() is False
        assert manager.state == GuestParserState.FAILED
        assert manager.failure["code"] == "GP_VM_NOT_RUNNING"
        assert manager.failure["fail_closed"] == "true"

    @patch(
        "launcher.guest_parser.is_guest_service_interface_enabled",
        return_value=False,
    )
    @patch("launcher.guest_parser.get_vm_state", return_value=VMState.RUNNING)
    def test_deploy_fail_closed_gsi_disabled(
        self, _state, _gsi, tmp_path: Path
    ) -> None:
        _make_source(tmp_path)
        manager = _manager(_config(), tmp_path)
        assert manager.deploy() is False
        assert manager.failure["code"] == "GP_GSI_DISABLED"

    @patch(
        "launcher.guest_parser.is_guest_service_interface_enabled",
        return_value=True,
    )
    @patch("launcher.guest_parser.get_vm_state", return_value=VMState.RUNNING)
    def test_deploy_fail_closed_source_missing(
        self, _state, _gsi, tmp_path: Path
    ) -> None:
        # tmp_path deliberately has no services/cleaner/guest dir — the
        # parallel branch's service is not present.
        manager = _manager(_config(), tmp_path)
        assert manager.deploy() is False
        assert manager.failure["code"] == "GP_SOURCE_MISSING"

    @patch("launcher.guest_parser.copy_file_to_vm", return_value=False)
    @patch(
        "launcher.guest_parser.is_guest_service_interface_enabled",
        return_value=True,
    )
    @patch("launcher.guest_parser.get_vm_state", return_value=VMState.RUNNING)
    def test_deploy_fail_closed_copy_failure(
        self, _state, _gsi, _copy, tmp_path: Path
    ) -> None:
        _make_source(tmp_path)
        manager = _manager(_config(), tmp_path)
        assert manager.deploy() is False
        assert manager.state == GuestParserState.FAILED
        assert manager.failure["code"] == "GP_COPY_FAILED"

    @patch(
        "launcher.guest_parser.is_guest_service_interface_enabled",
        return_value=True,
    )
    @patch("launcher.guest_parser.get_vm_state", return_value=VMState.RUNNING)
    def test_deploy_fail_closed_trigger_copy_failure(
        self, _state, _gsi, tmp_path: Path
    ) -> None:
        """A failed TRIGGER copy fails the deploy even after the bundle landed
        — the guest will never apply it (no commit point), and the host
        reports the truth."""
        _make_source(tmp_path)
        results = iter([True, True, False])
        with patch(
            "launcher.guest_parser.copy_file_to_vm",
            side_effect=lambda **_kwargs: next(results),
        ):
            manager = _manager(_config(), tmp_path)
            assert manager.deploy() is False
        assert manager.failure["code"] == "GP_COPY_FAILED"

    @patch("launcher.guest_parser.get_vm_state", return_value=VMState.RUNNING)
    def test_deploy_refused_from_ready_state(
        self, _state, tmp_path: Path
    ) -> None:
        _make_source(tmp_path)
        manager = _manager(_config(), tmp_path)
        manager._set_state(GuestParserState.READY)
        assert manager.deploy() is False
        assert manager.failure["code"] == "GP_STATE_INVALID"


# ---------------------------------------------------------------------------
# Start / health
# ---------------------------------------------------------------------------


class TestStart:
    def test_start_ready_with_bound_probe(self, tmp_path: Path) -> None:
        seen: list[ParserEndpoint] = []

        def probe(endpoint: ParserEndpoint) -> bool:
            seen.append(endpoint)
            return True

        register_parser_health_probe(probe)
        manager = _manager(_config(), tmp_path)
        assert manager.start() is True
        assert manager.state == GuestParserState.READY
        assert manager.is_available() is True
        assert seen[0].vsock_port == 50001
        assert seen[0].service_guid == hv_service_guid_for_port(50001)

    def test_start_fail_closed_unbound_channel(self, tmp_path: Path) -> None:
        """No probe bound (the parallel branch not yet integrated) → the
        parser can NEVER be reported READY — the load-bearing fail-closed."""
        manager = _manager(_config(), tmp_path)
        assert manager.start() is False
        assert manager.state == GuestParserState.FAILED
        assert manager.failure["code"] == "GP_CHANNEL_UNBOUND"
        assert manager.is_available() is False

    def test_start_fail_closed_probe_false(self, tmp_path: Path) -> None:
        register_parser_health_probe(lambda endpoint: False)
        manager = _manager(_config(), tmp_path)
        assert manager.start() is False
        assert manager.failure["code"] == "GP_HEALTH_FAILED"

    def test_start_fail_closed_probe_raises(self, tmp_path: Path) -> None:
        def probe(endpoint: ParserEndpoint) -> bool:
            raise RuntimeError("frame layer exploded")

        register_parser_health_probe(probe)
        manager = _manager(_config(), tmp_path)
        assert manager.start() is False
        assert manager.failure["code"] == "GP_HEALTH_PROBE_ERROR"

    def test_start_fail_closed_transport_timeout(self, tmp_path: Path) -> None:
        register_parser_health_probe(lambda endpoint: True)
        manager = _manager(
            _config(health_timeout_s=0.05, health_poll_interval_s=0.01),
            tmp_path,
            transport_check=lambda endpoint: False,
        )
        assert manager.start() is False
        assert manager.failure["code"] == "GP_HEALTH_TIMEOUT"

    def test_start_polls_transport_until_reachable(self, tmp_path: Path) -> None:
        register_parser_health_probe(lambda endpoint: True)
        attempts = {"n": 0}

        def flaky_transport(endpoint: ParserEndpoint) -> bool:
            attempts["n"] += 1
            return attempts["n"] >= 3

        manager = _manager(
            _config(health_timeout_s=5.0, health_poll_interval_s=0.01),
            tmp_path,
            transport_check=flaky_transport,
        )
        assert manager.start() is True
        assert attempts["n"] == 3

    def test_start_fail_closed_transport_check_raises(
        self, tmp_path: Path
    ) -> None:
        register_parser_health_probe(lambda endpoint: True)

        def exploding(endpoint: ParserEndpoint) -> bool:
            raise OSError("winsock says no")

        manager = _manager(
            _config(health_timeout_s=0.05, health_poll_interval_s=0.01),
            tmp_path,
            transport_check=exploding,
        )
        assert manager.start() is False
        assert manager.failure["code"] == "GP_HEALTH_TIMEOUT"

    def test_start_refused_when_disabled(self, tmp_path: Path) -> None:
        manager = _manager(_config(enabled=False), tmp_path)
        assert manager.start() is False
        assert manager.failure["code"] == "GP_DISABLED"

    def test_start_refused_from_failed_state(self, tmp_path: Path) -> None:
        register_parser_health_probe(lambda endpoint: True)
        manager = _manager(_config(), tmp_path)
        manager._set_state(GuestParserState.FAILED)
        assert manager.start() is False
        assert manager.failure["code"] == "GP_STATE_INVALID"


class TestSteadyStateHealth:
    def test_crash_detection_degrades_ready_to_failed(
        self, tmp_path: Path
    ) -> None:
        """Service-crash path: a READY parser that stops answering health
        checks is withdrawn fail-closed — availability flips False."""
        verdicts = iter([True, False])
        register_parser_health_probe(lambda endpoint: next(verdicts))
        manager = _manager(_config(), tmp_path)
        assert manager.start() is True
        assert manager.is_available() is True

        assert manager.check_health() is False
        assert manager.state == GuestParserState.FAILED
        assert manager.failure["code"] == "GP_HEALTH_LOST"
        assert manager.is_available() is False

    def test_healthy_recheck_stays_ready(self, tmp_path: Path) -> None:
        register_parser_health_probe(lambda endpoint: True)
        manager = _manager(_config(), tmp_path)
        assert manager.start() is True
        assert manager.check_health() is True
        assert manager.state == GuestParserState.READY

    def test_check_health_false_when_not_ready(self, tmp_path: Path) -> None:
        manager = _manager(_config(), tmp_path)
        assert manager.check_health() is False
        assert manager.state == GuestParserState.IDLE  # no spurious FAILED

    def test_probe_exception_degrades_fail_closed(self, tmp_path: Path) -> None:
        calls = {"n": 0}

        def probe(endpoint: ParserEndpoint) -> bool:
            calls["n"] += 1
            if calls["n"] == 1:
                return True
            raise OSError("guest gone")

        register_parser_health_probe(probe)
        manager = _manager(_config(), tmp_path)
        assert manager.start() is True
        assert manager.check_health() is False
        assert manager.state == GuestParserState.FAILED


# ---------------------------------------------------------------------------
# Stop (#657 integration)
# ---------------------------------------------------------------------------


class TestStop:
    def test_stop_from_ready_sends_bound_signal(self, tmp_path: Path) -> None:
        register_parser_health_probe(lambda endpoint: True)
        signalled: list[ParserEndpoint] = []
        register_parser_stop_signal(
            lambda endpoint: (signalled.append(endpoint), True)[1]
        )
        manager = _manager(_config(), tmp_path)
        assert manager.start() is True
        manager.stop()
        assert manager.state == GuestParserState.STOPPED
        assert len(signalled) == 1

    def test_stop_without_signal_still_stops(self, tmp_path: Path) -> None:
        register_parser_health_probe(lambda endpoint: True)
        manager = _manager(_config(), tmp_path)
        assert manager.start() is True
        manager.stop()  # no stop signal bound — VM stop-on-exit is the stop
        assert manager.state == GuestParserState.STOPPED

    def test_stop_signal_exception_is_swallowed(self, tmp_path: Path) -> None:
        register_parser_health_probe(lambda endpoint: True)

        def bad_signal(endpoint: ParserEndpoint) -> bool:
            raise RuntimeError("channel torn down already")

        register_parser_stop_signal(bad_signal)
        manager = _manager(_config(), tmp_path)
        assert manager.start() is True
        manager.stop()  # must never raise (atexit path)
        assert manager.state == GuestParserState.STOPPED

    def test_stop_from_idle_is_safe(self, tmp_path: Path) -> None:
        manager = _manager(_config(), tmp_path)
        manager.stop()
        assert manager.state == GuestParserState.STOPPED

    def test_is_available_only_in_ready(self, tmp_path: Path) -> None:
        register_parser_health_probe(lambda endpoint: True)
        manager = _manager(_config(), tmp_path)
        assert manager.is_available() is False  # IDLE
        assert manager.start() is True
        assert manager.is_available() is True  # READY
        manager.stop()
        assert manager.is_available() is False  # STOPPED


# ---------------------------------------------------------------------------
# Seam registry
# ---------------------------------------------------------------------------


class TestParserChannelSeam:
    def test_unbound_by_default(self) -> None:
        assert get_parser_health_probe() is None
        assert get_parser_stop_signal() is None

    def test_register_and_get_health_probe(self) -> None:
        probe = lambda endpoint: True  # noqa: E731
        register_parser_health_probe(probe)
        assert get_parser_health_probe() is probe

    def test_register_and_get_stop_signal(self) -> None:
        signal = lambda endpoint: True  # noqa: E731
        register_parser_stop_signal(signal)
        assert get_parser_stop_signal() is signal

    def test_clear_restores_fail_closed_default(self) -> None:
        register_parser_health_probe(lambda endpoint: True)
        register_parser_stop_signal(lambda endpoint: True)
        clear_parser_channel_bindings()
        assert get_parser_health_probe() is None
        assert get_parser_stop_signal() is None

    def test_last_registration_wins(self) -> None:
        first = lambda endpoint: True  # noqa: E731
        second = lambda endpoint: False  # noqa: E731
        register_parser_health_probe(first)
        register_parser_health_probe(second)
        assert get_parser_health_probe() is second


# ---------------------------------------------------------------------------
# Process-wide accessor + availability truth signal
# ---------------------------------------------------------------------------


class TestAvailabilitySignal:
    def test_unparked_means_unavailable(self) -> None:
        assert get_guest_parser_manager() is None
        assert guest_parser_available() is False

    def test_parked_but_not_ready_means_unavailable(
        self, tmp_path: Path
    ) -> None:
        manager = _manager(_config(), tmp_path)
        set_guest_parser_manager(manager)
        assert guest_parser_available() is False

    def test_ready_means_available(self, tmp_path: Path) -> None:
        register_parser_health_probe(lambda endpoint: True)
        manager = _manager(_config(), tmp_path)
        assert manager.start() is True
        set_guest_parser_manager(manager)
        assert guest_parser_available() is True


# ---------------------------------------------------------------------------
# Launcher bring-up helper (boot wiring)
# ---------------------------------------------------------------------------


class TestMaybeStartGuestParser:
    def test_disabled_config_is_noop(self) -> None:
        """The shipped default (enabled=false) must produce a clean no-op —
        no VM calls, None returned, capability unavailable."""
        from launcher.__main__ import _maybe_start_guest_parser

        with patch("launcher.guest_parser.get_vm_state") as mock_state:
            result = _maybe_start_guest_parser()
        assert result is None
        mock_state.assert_not_called()
        assert guest_parser_available() is False

    def test_config_error_is_fail_closed_not_fatal(self) -> None:
        from launcher.__main__ import _maybe_start_guest_parser

        with patch(
            "launcher.guest_parser.load_guest_parser_config",
            side_effect=GuestParserConfigError("GP_CONFIG_MISSING", "gone"),
        ):
            result = _maybe_start_guest_parser()
        assert result is None
        assert guest_parser_available() is False

    def test_enabled_deploy_failure_keeps_boot_alive(
        self, tmp_path: Path
    ) -> None:
        """Deploy failure → manager returned in FAILED, no exception (the
        boot continues; URL ingest refuses)."""
        from launcher.__main__ import _maybe_start_guest_parser

        with patch(
            "launcher.guest_parser.load_guest_parser_config",
            return_value=_config(),
        ), patch(
            "launcher.guest_parser.get_vm_state", return_value=VMState.OFF
        ):
            result = _maybe_start_guest_parser()
        assert result is not None
        assert result.state == GuestParserState.FAILED
        assert guest_parser_available() is False

    def test_enabled_full_green_path_reports_ready(
        self, tmp_path: Path
    ) -> None:
        """Full green path → READY.

        The launcher now OWNS probe-binding + the #655 AF_HYPERV bridge build
        (it registers ``make_health_probe()`` and resolves a 3.14 interpreter
        before deploy).  The test patches those two seams to a deterministic
        stub so the orchestration is exercised without a live guest/subprocess:
        a stub bridge build (no real ``py -3.14`` spawn) and a probe that
        passes.  The transport reachability check is stubbed True as before.
        """
        from launcher.__main__ import _maybe_start_guest_parser

        _make_source(tmp_path)
        config = _config()

        real_init = GuestParserManager.__init__

        def init_with_test_seams(self, cfg, **kwargs):
            kwargs.setdefault("repo_root", tmp_path)
            kwargs.setdefault("transport_check", lambda endpoint: True)
            real_init(self, cfg, **kwargs)

        from shared.security.guarded_fetch import (
            active_url_adjudicator,
            clear_url_adjudicator,
        )

        clear_url_adjudicator()
        try:
            with patch(
                "launcher.guest_parser.load_guest_parser_config",
                return_value=config,
            ), patch.object(
                GuestParserManager, "__init__", init_with_test_seams
            ), patch(
                "launcher.guest_parser.get_vm_state", return_value=VMState.RUNNING
            ), patch(
                "launcher.guest_parser.is_guest_service_interface_enabled",
                return_value=True,
            ), patch(
                "launcher.guest_parser.copy_file_to_vm", return_value=True
            ), patch(
                # The launcher builds the bridge before deploy; stub it so no real
                # 3.14 subprocess is spawned in the unit test.
                "launcher.guest_parser_invoker.bridge_required", return_value=False
            ), patch(
                # The launcher binds the real frame-level probe (imported locally
                # from its source module); stub it green at the source.
                "launcher.guest_parser_health.make_health_probe",
                return_value=(lambda endpoint: True),
            ):
                result = _maybe_start_guest_parser()

            assert result is not None
            assert result.state == GuestParserState.READY
            assert guest_parser_available() is True
            # READY is the door-opening act: the operator URL-ingest adjudicator
            # is now registered on the one egress door (TASK 4b).
            assert active_url_adjudicator() is not None
        finally:
            clear_url_adjudicator()

    def test_resident_skips_deploy_and_reaches_ready(self, tmp_path: Path) -> None:
        """Resident model (#655): the launcher SKIPS deploy() (copy_file_to_vm is
        never called) and goes straight to start(), still reaching READY and
        registering the operator URL-ingest adjudicator."""
        from launcher.__main__ import _maybe_start_guest_parser
        from shared.security.guarded_fetch import (
            active_url_adjudicator,
            clear_url_adjudicator,
        )

        config = _config(resident=True)

        real_init = GuestParserManager.__init__

        def init_with_test_seams(self, cfg, **kwargs):
            kwargs.setdefault("repo_root", tmp_path)
            kwargs.setdefault("transport_check", lambda endpoint: True)
            real_init(self, cfg, **kwargs)

        clear_url_adjudicator()
        try:
            with patch(
                "launcher.guest_parser.load_guest_parser_config",
                return_value=config,
            ), patch.object(
                GuestParserManager, "__init__", init_with_test_seams
            ), patch(
                "launcher.guest_parser.get_vm_state", return_value=VMState.RUNNING
            ), patch(
                "launcher.guest_parser.copy_file_to_vm"
            ) as mock_copy, patch(
                "launcher.guest_parser_invoker.bridge_required", return_value=False
            ), patch(
                "launcher.guest_parser_health.make_health_probe",
                return_value=(lambda endpoint: True),
            ):
                result = _maybe_start_guest_parser()

            assert result is not None
            assert result.state == GuestParserState.READY
            assert guest_parser_available() is True
            # The resident path must NEVER ship a deploy bundle.
            mock_copy.assert_not_called()
            # READY still opens the door (adjudicator registered).
            assert active_url_adjudicator() is not None
        finally:
            clear_url_adjudicator()
