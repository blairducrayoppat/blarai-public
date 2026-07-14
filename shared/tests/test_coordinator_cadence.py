"""Locks for the heartbeat cadence + cycle-mode policy (#845 C3, ADR-039 §2.12.12).

Pins the design-review-hardened directions: swap-read-UNREACHABLE is never
clearance to draft (F1); power-UNKNOWN restricts while probe-``None`` (no
battery device) is AC-with-a-note (F9); a malformed overnight window degrades
to no-window WITH a note (never silent, never an accidental permanent mute);
battery stretches the interval; SKIP outranks everything; and the config
extension resolves fail-closed."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from shared.coordinator import cadence as cd
from shared.coordinator.config import CoordinatorConfig


def _local(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 7, 14, hour, minute, 0)


# ---------------------------------------------------------------------------
# read_power_probe — the §8.3 three-outcome split (F9)
# ---------------------------------------------------------------------------


def test_probe_plugged_is_ac_no_note():
    probe = cd.read_power_probe(lambda: SimpleNamespace(power_plugged=True))
    assert probe == cd.PowerProbe(cd.PowerState.AC)


def test_probe_discharging_is_battery():
    probe = cd.read_power_probe(lambda: SimpleNamespace(power_plugged=False))
    assert probe.state is cd.PowerState.BATTERY


def test_probe_none_is_ac_with_surfaced_note():
    """psutil's documented 'no battery device' — a desktop must not be
    perpetually throttled, but the anomaly stays visible (review F9)."""
    probe = cd.read_power_probe(lambda: None)
    assert probe.state is cd.PowerState.AC
    assert "no battery device" in probe.note


def test_probe_exception_is_unknown_never_ac():
    def boom():
        raise OSError("driver went away")

    probe = cd.read_power_probe(boom)
    assert probe.state is cd.PowerState.UNKNOWN
    assert "failed" in probe.note


def test_probe_unrecognized_shape_is_unknown():
    probe = cd.read_power_probe(lambda: SimpleNamespace())
    assert probe.state is cd.PowerState.UNKNOWN


def test_restricts_direction():
    assert not cd.PowerState.AC.restricts
    assert cd.PowerState.BATTERY.restricts
    assert cd.PowerState.UNKNOWN.restricts  # §2.14.4 — unknown never reads as AC


# ---------------------------------------------------------------------------
# overnight window — parse + contains
# ---------------------------------------------------------------------------


def test_window_parse_valid():
    window, note = cd.parse_overnight_window("23:00-09:00")
    assert note == ""
    assert window == cd.OvernightWindow(start_minute=23 * 60, end_minute=9 * 60)


def test_window_empty_string_is_deliberate_no_window():
    assert cd.parse_overnight_window("") == (None, "")
    assert cd.parse_overnight_window("   ") == (None, "")


@pytest.mark.parametrize(
    "bad", ["23:00", "23-09", "25:00-09:00", "23:00-09:61", "a-b", "23:00-09:00-01:00"]
)
def test_window_malformed_degrades_with_note_never_silent(bad):
    window, note = cd.parse_overnight_window(bad)
    assert window is None
    assert "malformed" in note and bad.strip() in note


def test_window_contains_wraps_midnight():
    window, _ = cd.parse_overnight_window("23:00-09:00")
    assert window is not None
    assert window.contains(_local(23, 30))
    assert window.contains(_local(3, 0))
    assert not window.contains(_local(12, 0))
    assert window.contains(_local(23, 0))       # start inclusive
    assert not window.contains(_local(9, 0))    # end exclusive
    assert window.contains(_local(23, 59))      # minutes boundary


def test_window_contains_rejects_aware_datetime():
    """Review finding 3 lock: the window is LOCAL wall-clock; an aware/UTC
    datetime would silently shift it by the UTC offset — fail-loud instead."""
    from datetime import timezone

    window, _ = cd.parse_overnight_window("23:00-09:00")
    assert window is not None
    with pytest.raises(ValueError, match="NAIVE local"):
        window.contains(datetime(2026, 7, 14, 2, 0, tzinfo=timezone.utc))


def test_window_non_wrapping_and_empty():
    window, _ = cd.parse_overnight_window("01:00-05:00")
    assert window is not None
    assert window.contains(_local(3, 0))
    assert not window.contains(_local(23, 0))
    empty = cd.OvernightWindow(start_minute=540, end_minute=540)
    assert not empty.contains(_local(9, 0))  # start==end -> always False, never always-on


# ---------------------------------------------------------------------------
# resolve_cycle_mode — the ladder (design §1)
# ---------------------------------------------------------------------------

_AC = cd.PowerProbe(cd.PowerState.AC)


def _resolve(**overrides):
    kwargs = dict(
        teardown_started=False,
        previous_cycle_running=False,
        swap_read_ok=True,
        swap_in_flight=False,
        power=_AC,
        in_overnight_window=False,
    )
    kwargs.update(overrides)
    return cd.resolve_cycle_mode(**kwargs)


def test_full_mode_on_the_happy_path():
    decision = _resolve()
    assert decision.mode is cd.CycleMode.FULL
    assert decision.next_interval_s == cd.DEFAULT_HEARTBEAT_INTERVAL_S
    assert decision.reasons == ()


def test_unreachable_swap_read_is_never_clearance_to_draft():
    """The design-review F1 lock: unknown ≠ idle."""
    decision = _resolve(swap_read_ok=False)
    assert decision.mode is cd.CycleMode.DETERMINISTIC_ONLY
    assert any("unreadable" in r for r in decision.reasons)


def test_swap_in_flight_is_deterministic_only():
    decision = _resolve(swap_in_flight=True)
    assert decision.mode is cd.CycleMode.DETERMINISTIC_ONLY
    assert any("swap in flight" in r for r in decision.reasons)


@pytest.mark.parametrize("state", [cd.PowerState.BATTERY, cd.PowerState.UNKNOWN])
def test_battery_and_unknown_power_restrict_and_stretch(state):
    decision = _resolve(power=cd.PowerProbe(state))
    assert decision.mode is cd.CycleMode.DETERMINISTIC_ONLY
    assert decision.next_interval_s == pytest.approx(
        cd.DEFAULT_HEARTBEAT_INTERVAL_S * cd.DEFAULT_BATTERY_MULTIPLIER
    )
    assert any("no model drafting" in r for r in decision.reasons)


def test_overnight_window_is_deterministic_only():
    decision = _resolve(in_overnight_window=True)
    assert decision.mode is cd.CycleMode.DETERMINISTIC_ONLY
    assert any("overnight" in r for r in decision.reasons)


def test_skip_outranks_everything_and_keeps_stretched_interval():
    decision = _resolve(
        teardown_started=True, power=cd.PowerProbe(cd.PowerState.BATTERY)
    )
    assert decision.mode is cd.CycleMode.SKIP
    assert decision.next_interval_s == pytest.approx(
        cd.DEFAULT_HEARTBEAT_INTERVAL_S * cd.DEFAULT_BATTERY_MULTIPLIER
    )


def test_skip_records_every_restriction_reason():
    """Review finding 4 lock: a SKIP's telemetry says the WHOLE why."""
    decision = _resolve(
        teardown_started=True, swap_read_ok=False, in_overnight_window=True
    )
    assert decision.mode is cd.CycleMode.SKIP
    joined = " | ".join(decision.reasons)
    assert "unreadable" in joined
    assert "overnight" in joined
    assert "teardown" in joined


def test_custom_interval_and_multiplier_flow_through():
    """The config→stretch wiring path (review finding 5): non-default args."""
    decision = _resolve(
        power=cd.PowerProbe(cd.PowerState.BATTERY),
        interval_s=600.0,
        battery_multiplier=2.0,
    )
    assert decision.next_interval_s == pytest.approx(1200.0)


def test_previous_cycle_running_skips():
    decision = _resolve(previous_cycle_running=True)
    assert decision.mode is cd.CycleMode.SKIP
    assert any("previous cycle" in r for r in decision.reasons)


def test_probe_note_always_surfaces_in_reasons():
    decision = _resolve(power=cd.PowerProbe(cd.PowerState.AC, note="no battery device"))
    assert decision.mode is cd.CycleMode.FULL  # probe-None AC does NOT restrict
    assert "no battery device" in decision.reasons


# ---------------------------------------------------------------------------
# CoordinatorConfig extension — fail-closed resolution
# ---------------------------------------------------------------------------


def test_config_defaults_match_cadence_constants():
    cfg = CoordinatorConfig()
    assert cfg.heartbeat_interval_s == cd.DEFAULT_HEARTBEAT_INTERVAL_S
    assert cfg.heartbeat_battery_multiplier == cd.DEFAULT_BATTERY_MULTIPLIER
    assert cfg.heartbeat_boot_grace_s == cd.DEFAULT_BOOT_GRACE_S
    assert cfg.overnight_window == cd.DEFAULT_OVERNIGHT_WINDOW
    assert cfg.operator_absent is False


def test_from_toml_resolves_valid_cadence_keys():
    cfg = CoordinatorConfig.from_toml(
        {
            "heartbeat_interval_s": 600,
            "heartbeat_battery_multiplier": 2,
            "heartbeat_boot_grace_s": 120,
            "overnight_window": "22:00-08:00",
            "operator_absent": True,
        }
    )
    assert cfg.heartbeat_interval_s == 600.0
    assert cfg.heartbeat_battery_multiplier == 2.0
    assert cfg.heartbeat_boot_grace_s == 120.0
    assert cfg.overnight_window == "22:00-08:00"
    assert cfg.operator_absent is True


@pytest.mark.parametrize(
    ("key", "bad", "expected_attr", "expected"),
    [
        ("heartbeat_interval_s", "fast", "heartbeat_interval_s", 900.0),
        ("heartbeat_interval_s", 10, "heartbeat_interval_s", 900.0),  # < 60 s floor
        ("heartbeat_interval_s", True, "heartbeat_interval_s", 900.0),  # bool is not a number
        ("heartbeat_battery_multiplier", 0.5, "heartbeat_battery_multiplier", 4.0),  # <1 speeds up on battery — wrong direction
        ("heartbeat_battery_multiplier", True, "heartbeat_battery_multiplier", 4.0),  # bool→1.0 would mean NO battery stretch
        ("heartbeat_boot_grace_s", -5, "heartbeat_boot_grace_s", 300.0),
        ("heartbeat_boot_grace_s", True, "heartbeat_boot_grace_s", 300.0),  # bool→1.0 would gut the boot grace
        ("overnight_window", 2300, "overnight_window", "23:00-09:00"),
    ],
)
def test_from_toml_malformed_cadence_values_fail_closed(key, bad, expected_attr, expected):
    cfg = CoordinatorConfig.from_toml({key: bad})
    assert getattr(cfg, expected_attr) == expected


def test_from_toml_interval_floor_boundary():
    assert CoordinatorConfig.from_toml({"heartbeat_interval_s": 59}).heartbeat_interval_s == 900.0
    assert CoordinatorConfig.from_toml({"heartbeat_interval_s": 60}).heartbeat_interval_s == 60.0


def test_from_toml_empty_equals_default_construction():
    """Review finding 1 lock: the two construction paths can never drift —
    an absent section resolves to exactly the default-constructed config."""
    assert CoordinatorConfig.from_toml({}) == CoordinatorConfig()
    assert CoordinatorConfig.from_toml(None) == CoordinatorConfig()


def test_fresh_install_still_fully_off_with_cadence_defaults():
    cfg = CoordinatorConfig.fresh_install()
    assert cfg.enabled is False and cfg.heartbeat_enabled is False
    assert cfg.autonomy_all_off()
    assert cfg.operator_absent is False
