"""Heartbeat cadence + cycle-mode policy — pure, probe-fed (#845 C3, ADR-039 §2.12.12).

The C3 design (`docs/research/c3-heartbeat-design-2026-07.md` §1/§8.3) resolves a
:class:`CycleMode` fresh at the top of every wake cycle from four inputs — swap
state, power state, the overnight window, and teardown — and this module is that
resolution, as PURE code over injected probes (no clock reads, no I/O in the
policy itself; the caller supplies everything). Recon verified the runtime has
ZERO power awareness today (battery detection exists only in offline bench
scripts) and no runtime-readable overnight window — the two probes here are the
new primitives the design names.

The ladder's conservative directions, each a review-hardened lock:

  * **Swap-read UNREACHABLE ⇒ DETERMINISTIC-ONLY** — unknown ≠ idle: an
    unreadable swap state is treated as a possible in-flight swap, never as
    clearance to draft on the model (the design-review F1 fail-open, closed).
  * **Power UNKNOWN ⇒ battery-equivalent restrictions** — a probe error never
    renders as "plugged in" (ADR-039 §2.14.4). But probe ``None`` — psutil's
    documented "no battery device" — is **AC with a surfaced note** (design
    §8.3/review F9): a battery-less desktop must not be perpetually throttled
    (multi-operator readiness, §2.2 control 5), while the note keeps a laptop
    driver anomaly visible.
  * **Overnight window ⇒ DETERMINISTIC-ONLY** — the GPU belongs to the fleet;
    a malformed window string degrades to NO window WITH a surfaced note (the
    genuine GPU-conflict safety is carried by the swap gate, which is
    independent of this hygiene window — a typo must not permanently mute
    drafting, and must not do anything silently either).
  * **Battery ⇒ DETERMINISTIC-ONLY + interval × multiplier** — §2.12.12: the
    heartbeat honors the device.
  * Thermal throttling has NO runtime signal on this box (verified); the
    battery/overnight/swap gates cover the practical envelope, and no fake
    thermal control is pretended here (design §8.3 names the residual).

REACHABILITY: pure functions + probes — no side effects beyond reading the power
state. The C3 heartbeat cycle (behind ``[coordinator].heartbeat_enabled``, dormant
default false) is the only consumer. Importing this module arms nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Callable

# The cadence SSOT constants live in :mod:`shared.coordinator.config` (the leaf
# module — it may not import from here) and are re-exported as this module's
# public API + the timeout registry's resolution target's siblings.
from shared.coordinator.config import (
    DEFAULT_BATTERY_MULTIPLIER,
    DEFAULT_BOOT_GRACE_S,
    DEFAULT_HEARTBEAT_INTERVAL_S,
    DEFAULT_OVERNIGHT_WINDOW,
)

__all__ = [
    "DEFAULT_BATTERY_MULTIPLIER",
    "DEFAULT_BOOT_GRACE_S",
    "DEFAULT_HEARTBEAT_INTERVAL_S",
    "DEFAULT_OVERNIGHT_WINDOW",
    "CycleDecision",
    "CycleMode",
    "OvernightWindow",
    "PowerProbe",
    "PowerState",
    "parse_overnight_window",
    "read_power_probe",
    "resolve_cycle_mode",
]


class PowerState(Enum):
    """The probe's resolved power posture (design §8.3 three-outcome split)."""

    AC = "AC"
    BATTERY = "BATTERY"
    UNKNOWN = "UNKNOWN"

    @property
    def restricts(self) -> bool:
        """True when this state forces battery-equivalent restrictions —
        BATTERY, and UNKNOWN by the §2.14.4 conservative direction."""
        return self is not PowerState.AC


@dataclass(frozen=True)
class PowerProbe:
    """One cycle's power reading: the state + an operator-legible note for the
    two surfaced anomalies (probe ``None`` treated as AC; probe failure)."""

    state: PowerState
    note: str = ""


def read_power_probe(
    sensors: "Callable[[], Any] | None" = None,
) -> PowerProbe:
    """Read the battery once, fail-soft, with the design's three outcomes.

    *sensors* is injectable for tests; the default is
    ``psutil.sensors_battery`` (psutil is a declared runtime dependency),
    imported lazily so importing this module costs nothing.
    """
    probe = sensors
    if probe is None:
        try:
            import psutil  # noqa: PLC0415 — lazy by design (import-cost hygiene)

            probe = psutil.sensors_battery
        except Exception as exc:  # noqa: BLE001 — conservative, surfaced
            return PowerProbe(PowerState.UNKNOWN, note=f"psutil unavailable: {exc}")
    try:
        reading = probe()
    except Exception as exc:  # noqa: BLE001 — probe error never reads as AC
        return PowerProbe(PowerState.UNKNOWN, note=f"battery probe failed: {exc}")
    if reading is None:
        # psutil's documented "no battery device" — a desktop's safest state.
        return PowerProbe(
            PowerState.AC, note="no battery device reported (probe None) — treating as AC"
        )
    plugged = getattr(reading, "power_plugged", None)
    if plugged is True:
        return PowerProbe(PowerState.AC)
    if plugged is False:
        return PowerProbe(PowerState.BATTERY)
    return PowerProbe(
        PowerState.UNKNOWN, note="battery probe returned an unrecognized shape"
    )


@dataclass(frozen=True)
class OvernightWindow:
    """A local-wall-clock quiet window, minutes-since-midnight, wrap-aware."""

    start_minute: int
    end_minute: int

    def contains(self, local_now: datetime) -> bool:
        """True when *local_now*'s wall time falls inside the window.

        *local_now* MUST be a NAIVE local datetime — the window is local
        wall-clock ("the fleet owns the night" is a local fact). An aware
        datetime raises (fail-loud, review finding 3): silently reading UTC
        hours would shift the whole quiet window by the UTC offset.

        A window whose start > end spans midnight (``23:00-09:00`` contains
        23:30 and 03:00, not 12:00). ``start == end`` is an EMPTY window —
        always False — never an always-on one (an accidental ``"09:00-09:00"``
        must not mute drafting around the clock)."""
        if local_now.tzinfo is not None:
            raise ValueError(
                "OvernightWindow.contains requires a NAIVE local datetime — "
                "an aware/UTC value would silently shift the quiet window"
            )
        minute = local_now.hour * 60 + local_now.minute
        if self.start_minute == self.end_minute:
            return False
        if self.start_minute < self.end_minute:
            return self.start_minute <= minute < self.end_minute
        return minute >= self.start_minute or minute < self.end_minute


def parse_overnight_window(text: str) -> "tuple[OvernightWindow | None, str]":
    """Parse ``"HH:MM-HH:MM"`` → ``(window, note)``.

    Malformed input degrades to NO window plus a surfaced note (never silently;
    never an always-restricting misread — the module docstring names why the
    open direction is safe here: the swap gate independently owns the real GPU
    conflict). An empty string is a deliberate "no window" and carries no note.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return None, ""
    parts = cleaned.split("-")
    if len(parts) != 2:
        return None, f"malformed overnight_window {cleaned!r} — no quiet window applied"
    minutes: list[int] = []
    for part in parts:
        bits = part.strip().split(":")
        if len(bits) != 2:
            break
        try:
            hour, minute = int(bits[0]), int(bits[1])
        except ValueError:
            break
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            break
        minutes.append(hour * 60 + minute)
    if len(minutes) != 2:
        return None, f"malformed overnight_window {cleaned!r} — no quiet window applied"
    return OvernightWindow(start_minute=minutes[0], end_minute=minutes[1]), ""


class CycleMode(Enum):
    """What a wake cycle is permitted to do (design §1)."""

    FULL = "FULL"
    DETERMINISTIC_ONLY = "DETERMINISTIC-ONLY"
    SKIP = "SKIP"


@dataclass(frozen=True)
class CycleDecision:
    """The resolved mode + the next tick's interval + the why (operator-legible,
    carried into cycle telemetry — a restricted cycle always says why)."""

    mode: CycleMode
    next_interval_s: float
    reasons: tuple[str, ...] = ()


def resolve_cycle_mode(
    *,
    teardown_started: bool,
    previous_cycle_running: bool,
    swap_read_ok: bool,
    swap_in_flight: bool,
    power: PowerProbe,
    in_overnight_window: bool,
    interval_s: float = DEFAULT_HEARTBEAT_INTERVAL_S,
    battery_multiplier: float = DEFAULT_BATTERY_MULTIPLIER,
) -> CycleDecision:
    """The mode ladder (design §1), pure. Precedence: SKIP > DETERMINISTIC-ONLY
    > FULL; every restriction contributes a reason; battery/unknown power also
    stretches the next interval (the stretched value rides into the liveness
    stamp's ``next_expected_by`` so the dead-man never false-alarms — §6.1)."""
    reasons: list[str] = []
    if power.note:
        reasons.append(power.note)

    interval = interval_s
    deterministic_only = False
    if power.state.restricts:
        interval = interval_s * battery_multiplier
        deterministic_only = True
        reasons.append(
            f"power={power.state.value} — interval ×{battery_multiplier:g}, no model drafting"
        )
    if not swap_read_ok:
        deterministic_only = True
        reasons.append("swap state unreadable (unknown ≠ idle) — no model drafting")
    elif swap_in_flight:
        deterministic_only = True
        reasons.append("model swap in flight — no model drafting")
    if in_overnight_window:
        deterministic_only = True
        reasons.append("inside the overnight quiet window — no model drafting")

    # SKIP outranks everything but records EVERY restriction reason (review
    # finding 4 — telemetry must say the whole why, not just the skip's).
    if teardown_started or previous_cycle_running:
        reasons.append(
            "teardown in progress" if teardown_started else "previous cycle still running"
        )
        return CycleDecision(
            mode=CycleMode.SKIP, next_interval_s=interval, reasons=tuple(reasons)
        )

    return CycleDecision(
        mode=CycleMode.DETERMINISTIC_ONLY if deterministic_only else CycleMode.FULL,
        next_interval_s=interval,
        reasons=tuple(reasons),
    )
