"""Locks for the launcher-side heartbeat wiring (#845 limb 6, review MINOR-5).

The Step-6c/_cleanup contract in the repo's most incident-prone file, tested
directly rather than ridden on regression-cleanliness: a raising factory leaves
boot proceeding with ``_heartbeat = None``; the dormant default starts nothing;
``_cleanup`` stops the heartbeat FIRST and is None-safe. The VM seams are
recorder-stubbed exactly as ``test_import_side_effects`` does (get_vm_state →
OFF), so no test can ever reach a real Stop-VM.
"""

from __future__ import annotations

from types import SimpleNamespace

import launcher.__main__ as m


class _HeartbeatRecorder:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def start(self) -> None:
        self.calls.append("start")

    def stop(self) -> None:
        self.calls.append("stop")


def _quiet_cleanup_world(monkeypatch) -> None:
    """Neutralize every other _cleanup leg.

    #836 restore discipline: ``get_vm_state``/``stop_vm`` are FIXTURE-OWNED
    (the launcher/tests autouse conftest already installs benign mocks and
    restores the genuine functions itself) — they are CONFIGURED here, never
    ``monkeypatch.setattr``-ed (a monkeypatch on those names strands the mock
    for the session; the root-conftest tripwire fails the run). The other
    module globals are not fixture-owned and use monkeypatch normally."""
    m.get_vm_state.return_value = m.VMState.OFF
    monkeypatch.setattr(m, "_guest_parser_manager", None)
    monkeypatch.setattr(m, "_policy_agent_service", None)
    monkeypatch.setattr(m, "_orchestrator_service", None)
    monkeypatch.setattr(m, "_session_store", None)
    monkeypatch.setattr(m, "_cleanup_started", False)


def test_cleanup_stops_the_heartbeat_first_and_flags_teardown(monkeypatch) -> None:
    _quiet_cleanup_world(monkeypatch)
    recorder = _HeartbeatRecorder()
    monkeypatch.setattr(m, "_heartbeat", recorder)
    m._cleanup()
    assert recorder.calls == ["stop"]
    assert m._cleanup_started is True  # the watchdog/loop signal flipped


def test_cleanup_is_none_safe_without_a_heartbeat(monkeypatch) -> None:
    """The dormant default on every boot today: _heartbeat is None."""
    _quiet_cleanup_world(monkeypatch)
    monkeypatch.setattr(m, "_heartbeat", None)
    m._cleanup()  # must not raise


def test_raising_factory_leaves_boot_proceeding(monkeypatch) -> None:
    """Review 8c18ed43 MINOR-5: the Step-6c wrap — a factory explosion is a
    log line, never a failed boot, and _heartbeat lands None."""
    import shared.coordinator.heartbeat as hb_module

    def exploding(*a, **kw):
        raise RuntimeError("keystore melted")

    monkeypatch.setattr(hb_module, "build_heartbeat", exploding)
    monkeypatch.setattr(m, "_heartbeat", SimpleNamespace())  # stale non-None
    m._build_and_start_heartbeat(SimpleNamespace(), dev_mode=True)  # no raise
    assert m._heartbeat is None


def test_dormant_factory_result_starts_nothing(monkeypatch) -> None:
    """The shipped default: heartbeat_enabled false ⇒ factory None ⇒ no thread."""
    monkeypatch.setattr(m, "_heartbeat", SimpleNamespace())
    service = SimpleNamespace(coordinator_heartbeat_enabled=False)
    m._build_and_start_heartbeat(service, dev_mode=True)
    assert m._heartbeat is None


def test_enabled_factory_result_is_started(monkeypatch) -> None:
    import shared.coordinator.heartbeat as hb_module

    recorder = _HeartbeatRecorder()
    monkeypatch.setattr(hb_module, "build_heartbeat", lambda *a, **kw: recorder)
    monkeypatch.setattr(m, "_heartbeat", None)
    m._build_and_start_heartbeat(SimpleNamespace(), dev_mode=False)
    assert m._heartbeat is recorder
    assert recorder.calls == ["start"]