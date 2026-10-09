"""Offline unit tests for the OVMS HTTP bench's AO-contention guard
(scripts/benchmark_ovms_http.py, #1477). No GPU, no OVMS, no model.

Why this lock exists. The 30B's decode collapses ~13x when the AO is resident,
because on this iGPU "GPU shared memory" IS system RAM and the coder's weights
spill. That collapse is byte-identical in shape to the ``--cache_size`` defect
#1477 fixed, so a contended reading sends the next reader after a server bug
that is not there. Guidance on a ticket does not survive; a harness that
refuses does.

What these lock:
  * ``port_held`` actually detects a listener (real socket, not a fake) and
    reports a free port as free -- the control tested BOTH ways, so a pass
    distinguishes "guard works" from "guard cannot see";
  * the refusal itself: exit 2 before any warmup burns time, and the paired
    toggle proving ``--allow-ao-resident`` is what lifts it (a guard that
    never fires and a guard with no off switch look identical from a green);
  * every emitted record stamps ``ao_resident`` whether contended or not, so
    a future reader never reconstructs the condition from process archaeology.
"""

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import benchmark_ovms_http as bench  # noqa: E402


@pytest.fixture()
def listening_port():
    """A real bound+listening loopback port, released on teardown."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    try:
        yield sock.getsockname()[1]
    finally:
        sock.close()


@pytest.fixture()
def free_port():
    """A port number nothing holds (bound to learn it, then released)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


# ---------------------------------------------------------------------------
# The probe itself — proven to see, and proven not to cry wolf
# ---------------------------------------------------------------------------

class TestPortHeld:
    def test_detects_a_real_listener(self, listening_port):
        assert bench.port_held(listening_port) is True

    def test_reports_a_free_port_as_free(self, free_port):
        assert bench.port_held(free_port) is False


class TestAoContentionReasons:
    def test_clear_when_nothing_holds_the_port(self):
        assert bench.ao_contention_reasons(port_probe=lambda _p: False) == []

    def test_one_named_reason_when_held(self):
        reasons = bench.ao_contention_reasons(
            ao_port=5001, port_probe=lambda _p: True)
        assert len(reasons) == 1
        assert "5001" in reasons[0]

    def test_real_socket_end_to_end(self, listening_port, free_port):
        """The default probe path, not the injected one — otherwise the tests
        above only prove the injection point works."""
        assert bench.ao_contention_reasons(ao_port=listening_port) != []
        assert bench.ao_contention_reasons(ao_port=free_port) == []

    def test_a_live_ovms_is_not_contention(self):
        """Polarity guard: this bench MEASURES the server, so an OVMS process
        must never be a refusal reason (the in-process harnesses refuse on it;
        copying that here would make the bench unrunnable by construction)."""
        assert bench.ao_contention_reasons(port_probe=lambda _p: False) == []


# ---------------------------------------------------------------------------
# The refusal — and the toggle proving the refusal is what stopped it
# ---------------------------------------------------------------------------

def _stub_measurements(monkeypatch, tmp_path):
    """Make main() run fully offline: OVMS reachable, no HTTP, output to tmp."""
    monkeypatch.setattr(bench, "served_model_ids", lambda *_a, **_k: ["coder-30b"])
    monkeypatch.setattr(
        bench, "measure_generation",
        lambda *_a, **_k: [bench.SingleRunMetrics(0, 128, 200.0, 3300.0, 38.8, None)])
    monkeypatch.setattr(
        bench, "measure_prefill",
        lambda *_a, **_k: [bench.PrefillRunMetrics(512, 1080.0, 474.1, None)])
    monkeypatch.setattr(bench, "_REPO_ROOT", tmp_path)


def _run_main(monkeypatch, argv: list[str]) -> int:
    monkeypatch.setattr(sys, "argv", ["benchmark_ovms_http.py", *argv])
    return bench.main()


class TestRefuseToStart:
    def test_refuses_with_exit_2_when_the_ao_is_resident(
            self, monkeypatch, tmp_path, capsys):
        _stub_measurements(monkeypatch, tmp_path)
        monkeypatch.setattr(bench, "port_held", lambda *_a, **_k: True)

        assert _run_main(monkeypatch, ["--warmup", "0", "--runs", "1"]) == 2

        out = capsys.readouterr().out
        assert "not in a measurable state" in out
        assert "--allow-ao-resident" in out

    def test_refuses_before_any_measurement_runs(self, monkeypatch, tmp_path):
        """The refusal must precede the work, or it saves nothing."""
        _stub_measurements(monkeypatch, tmp_path)
        monkeypatch.setattr(bench, "port_held", lambda *_a, **_k: True)

        def _never(*_a, **_k):
            raise AssertionError("measurement ran despite the refusal")

        monkeypatch.setattr(bench, "measure_generation", _never)
        monkeypatch.setattr(bench, "chat_stream", _never)

        assert _run_main(monkeypatch, ["--warmup", "2", "--runs", "1"]) == 2

    def test_toggle_off_the_lock_and_the_same_call_proceeds(
            self, monkeypatch, tmp_path):
        """CONTROL TESTED OFF (security_by_design 12): identical inputs, the
        override alone, and the run completes — so the exit-2 above is the
        guard firing and not the harness failing for some other reason."""
        _stub_measurements(monkeypatch, tmp_path)
        monkeypatch.setattr(bench, "port_held", lambda *_a, **_k: True)

        rc = _run_main(
            monkeypatch,
            ["--warmup", "0", "--runs", "1", "--allow-ao-resident"])

        assert rc != 2

    def test_proceeds_when_the_box_is_clean(self, monkeypatch, tmp_path):
        _stub_measurements(monkeypatch, tmp_path)
        monkeypatch.setattr(bench, "port_held", lambda *_a, **_k: False)

        assert _run_main(monkeypatch, ["--warmup", "0", "--runs", "1"]) != 2


# ---------------------------------------------------------------------------
# The stamp — every record says what condition produced it
# ---------------------------------------------------------------------------

def _emitted_stamp(tmp_path: Path) -> dict:
    records = sorted((tmp_path / "docs" / "performance").glob("benchmark_ovms_*.json"))
    assert records, "the bench emitted no JSON record"
    return json.loads(records[-1].read_text(encoding="utf-8"))["config_stamp"]


class TestConditionStamp:
    def test_clean_run_stamps_ao_resident_false(self, monkeypatch, tmp_path):
        _stub_measurements(monkeypatch, tmp_path)
        monkeypatch.setattr(bench, "port_held", lambda *_a, **_k: False)

        _run_main(monkeypatch, ["--warmup", "0", "--runs", "1"])

        stamp = _emitted_stamp(tmp_path)
        assert stamp["ao_resident"] is False
        assert stamp["ao_resident_override"] is False

    def test_overridden_run_incriminates_itself(self, monkeypatch, tmp_path):
        """A contended record is allowed to exist; it is not allowed to look
        clean. Both flags true is what stops it being banked as a baseline."""
        _stub_measurements(monkeypatch, tmp_path)
        monkeypatch.setattr(bench, "port_held", lambda *_a, **_k: True)

        _run_main(
            monkeypatch,
            ["--warmup", "0", "--runs", "1", "--allow-ao-resident"])

        stamp = _emitted_stamp(tmp_path)
        assert stamp["ao_resident"] is True
        assert stamp["ao_resident_override"] is True


# ---------------------------------------------------------------------------
# The condition must describe the MEASUREMENT WINDOW, not one instant in it
# ---------------------------------------------------------------------------

class TestConditionIsResampled:
    def test_an_ao_that_appears_mid_run_is_caught_by_the_end_sample(
            self, monkeypatch, tmp_path, capsys):
        """THE defect lock (review of c03f885a). Sampling only at pre-flight would
        stamp ao_resident=false on a contended measurement — the clean-looking
        contended number this guard exists to prevent, displaced one step."""
        _stub_measurements(monkeypatch, tmp_path)
        seen = {"n": 0}

        def _appears_after_preflight(*_a, **_k):
            seen["n"] += 1
            return seen["n"] > 1          # clean at pre-flight, resident afterwards

        monkeypatch.setattr(bench, "port_held", _appears_after_preflight)

        rc = _run_main(monkeypatch, ["--warmup", "0", "--runs", "1"])

        assert rc != 2, "pre-flight was clean, so the run must start"
        assert seen["n"] >= 2, "the condition was sampled only once"
        stamp = _emitted_stamp(tmp_path)
        assert stamp["ao_resident"] is True, "a mid-run AO was stamped as a clean run"
        assert stamp["ao_resident_at_start"] is False
        assert stamp["ao_resident_at_end"] is True
        assert "came up DURING the run" in capsys.readouterr().out

    def test_a_genuinely_clean_run_is_still_clean(self, monkeypatch, tmp_path):
        """CONTROL: the re-sample must not make every run look contended."""
        _stub_measurements(monkeypatch, tmp_path)
        monkeypatch.setattr(bench, "port_held", lambda *_a, **_k: False)

        _run_main(monkeypatch, ["--warmup", "0", "--runs", "1"])

        stamp = _emitted_stamp(tmp_path)
        assert stamp["ao_resident"] is False
        assert stamp["ao_resident_at_start"] is False
        assert stamp["ao_resident_at_end"] is False


class TestTheRecordDoesNotClaimMoreThanItSampled:
    def test_the_stamp_says_how_many_times_it_looked(self, monkeypatch, tmp_path):
        """Two booleans named at_start/at_end read as a CENSUS. Both false would
        otherwise be read as 'clean throughout', which is an absence rendering as
        a confident value — the same failure class the guard was built for."""
        _stub_measurements(monkeypatch, tmp_path)
        monkeypatch.setattr(bench, "port_held", lambda *_a, **_k: False)

        _run_main(monkeypatch, ["--warmup", "0", "--runs", "1"])

        stamp = _emitted_stamp(tmp_path)
        assert stamp["condition_samples"] == 2
        assert "unsampled" in stamp["condition_sampling"]

    def test_a_server_that_died_mid_run_is_recorded(self, monkeypatch, tmp_path, capsys):
        """Partial numbers must not read as complete ones."""
        _stub_measurements(monkeypatch, tmp_path)
        monkeypatch.setattr(bench, "port_held", lambda *_a, **_k: False)
        seen = {"n": 0}

        def _dies_after_preflight(*_a, **_k):
            seen["n"] += 1
            return ["coder-30b"] if seen["n"] == 1 else []

        monkeypatch.setattr(bench, "served_model_ids", _dies_after_preflight)

        _run_main(monkeypatch, ["--warmup", "0", "--runs", "1"])

        assert _emitted_stamp(tmp_path)["ovms_alive_at_end"] is False
        assert "NOT serving at the end" in capsys.readouterr().out


class TestTheRefusalMessageSaysWhatItChecked:
    def test_it_does_not_claim_a_model_is_resident(self):
        """The AO holds :5001 with the model UNLOADED (it loads lazily — observed
        at 0.00 GB working set). A message asserting residency teaches the
        operator the guard cries wolf, and habitual --allow-ao-resident poisons
        the stamp in both directions."""
        reason = bench.ao_contention_reasons(port_probe=lambda _p: True)[0]
        assert "with a model resident" not in reason
        assert "checks the PORT" in reason
        assert "PREDICTOR" in reason
