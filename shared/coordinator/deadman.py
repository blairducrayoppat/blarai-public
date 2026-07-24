"""C3 dead-man liveness watchdog + boot reconcile (#845 limb 7, design §6 / ADR-039 §2.14.1).

The §2.14.1 premise: every alarm the coordinator can raise is computed BY the wake
cycle, so a wedged or dead heartbeat silences its own alarm, and operator noticing
is vigilance — disallowed as a control. This module is the check OUTSIDE the
heartbeat: a second, independent daemon thread whose entire job is one comparison —
``now > next_expected_by + slack`` — over the liveness stamp the heartbeat writes.
Because the stamp carries its OWN deadline (the mode ladder's chosen interval rides
inside it, §6.1), this watchdog needs no knowledge of intervals or modes and cannot
false-alarm across battery/overnight cadence stretching. It shares no code with the
cycle beyond reading the stamp file; its reliability argument is its triviality.

Trip semantics (fail-loud, §6.2):
  * ``thread_dead=true`` in the stamp → trips IMMEDIATELY (the heartbeat's own
    wall-3 stamp; the watchdog is the megaphone).
  * a deadline passed by more than the registered slack → trips.
  * no stamp at all past the watchdog's boot expectation (its own start + the
    heartbeat's boot grace + one interval + slack) → trips ("no first beat").
  * one alert per stale EPISODE (keyed on the stamp identity that tripped) — a
    fresh stamp re-arms; the same stale stamp never re-alerts every poll
    (an alarm that fires forever retrains the operator to ignore it).
The alert callable is the OPERATOR surface — machinery health, NEVER shadow-gated
(§7.2; the limb-6 factory wires the router's ``route_health`` adapter, whose
default is the ERROR log).

Boot reconcile (§6.3): a fresh in-session watchdog cannot see "it was wedged
BEFORE the crash/shutdown," so :func:`reconcile_boot_stamp` inspects the PREVIOUS
session's stamp once at heartbeat construction: a recorded ``thread_dead`` — or a
stamp that is neither cleanly-stopped nor dead (the process ended while beats were
still due: a crash, or a wedge that outlived the session) — surfaces one boot-time
notice. The clean-stop marker is written by ``Heartbeat.stop()`` in the same
teardown motion the launcher already runs FIRST in ``_cleanup``; the marker is what
distinguishes "the app was off (no beat was due — silence is correct)" from "beats
were due and stopped coming" — without it, every ordinary overnight shutdown would
false-alarm at the next boot, the §2.14.1 retraining failure in boot-notice form.

Session identity (review 06a5b435 MAJOR 1): every stamp carries the ``session_id``
minted at factory build, and this watchdog treats a stamp whose identity is not its
own — a leftover from a crashed/killed prior session — exactly like NO stamp: the
boot-expectation grace governs, uniformly, for EVERY foreign shape (stale, dead,
malformed). Without this, a leftover crash stamp false-alarms a fresh boot as a
present-tense wedge within milliseconds — the §2.14.1 alarm-retraining failure —
while the boot reconcile is already voicing the same evidence in the past tense,
once, which is whose job it is.

Named residual (review 06a5b435 MINOR 4 — who watches the watchman): the
watchdog's own thread death is an ERROR log only; there is deliberately no third
thread watching the second. The §6.2 mitigation is triviality — one comparison,
no I/O beyond one file read, no substrate — and the §6 rejected-alternatives
record already declined an app-independent auditor as its own future decision.

REACHABILITY: built by the SAME factory gate as the heartbeat (§3.2) — no heartbeat,
no watchdog, structurally (`build_heartbeat` returns ``None`` and constructs
nothing while ``[coordinator].heartbeat_enabled`` is false). Importing this module
arms nothing.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Final, Mapping

logger = logging.getLogger(__name__)

#: The dead-man slack: how far past the stamp's OWN ``next_expected_by`` deadline
#: the watchdog waits before tripping. Registered in shared/timeout_registry.py
#: (#845 limb 7, same change). The registered constant is the SLACK, not a
#: computed threshold — cadence stretching travels inside the stamp (§6.2).
DEADMAN_SLACK_S: Final[float] = 120.0

#: Poll grain (below-registry-value per the registry's own convention; noted in
#: its BACKLOG list). Staleness detection latency is bounded by poll + slack.
DEADMAN_POLL_S: Final[float] = 30.0

#: The watchdog thread's name — greppable beside ``blarai-coord-heartbeat``.
DEADMAN_THREAD_NAME: Final[str] = "blarai-coord-deadman"

#: The alert sink: one operator-legible message per trip. Machinery health —
#: never shadow-gated (§7.2). Default wiring is the router's route_health
#: adapter; the bare fallback is the ERROR log.
AlertSink = Callable[[str], None]


def _default_alert(message: str) -> None:
    logger.error("COORDINATOR OPERATOR NOTICE: %s", message)


def _parse_iso(value: object) -> "datetime | None":
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


class DeadManWatchdog:
    """The one-comparison watchdog thread. Trivial by design (§6.2).

    *stamp_path* is the heartbeat's liveness stamp; *session_id* THIS boot's
    stamp identity (a stamp carrying any other identity is a prior session's
    leftover and reads as no-current-stamp — MAJOR-1's fix); *alert* the
    operator surface; *slack_s* the registered :data:`DEADMAN_SLACK_S`;
    *initial_grace_s* the boot expectation for the FIRST beat (boot grace +
    one interval + slack), anchored at the first check — before a
    current-session stamp exists, silence past that point is itself the
    alarm. Clocks injected."""

    def __init__(
        self,
        *,
        stamp_path: Path,
        session_id: str,
        alert: AlertSink | None = None,
        slack_s: float = DEADMAN_SLACK_S,
        poll_s: float = DEADMAN_POLL_S,
        initial_grace_s: "float | None" = None,
        clock: "Callable[[], datetime] | None" = None,
    ) -> None:
        self._stamp_path = stamp_path
        self._session_id = session_id
        self._alert = alert or _default_alert
        self._slack_s = float(slack_s)
        self._poll_s = float(poll_s)
        # Anchored at the FIRST check (which the thread runs immediately at
        # start), not at construction (review 06a5b435 NIT 9) — a slow gap
        # between factory build and start() must not eat into the grace.
        self._initial_grace_s = initial_grace_s
        self._initial_deadline: "datetime | None" = None
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._stop = threading.Event()
        self._thread: "threading.Thread | None" = None
        self._alerted_identity: "str | None" = None

    # -- lifecycle (mirrors the heartbeat's) ---------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name=DEADMAN_THREAD_NAME, daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                self.check_once(self._clock())
                if self._stop.wait(self._poll_s):
                    return
        except Exception as exc:  # noqa: BLE001 — even the megaphone fails loud
            logger.error("dead-man watchdog thread died: %s", exc, exc_info=True)

    # -- the one comparison ---------------------------------------------------

    def check_once(self, now: datetime) -> "str | None":
        """Run one staleness check; returns the alert message if one fired.

        Public + clock-injected so tests (and the thread loop) drive the SAME
        code path. The SESSION GATE comes first (review 06a5b435 MAJOR 1): a
        stamp whose ``session_id`` is not this boot's — absent, foreign, dead,
        malformed, whatever its shape — is a prior session's leftover and
        routes to the boot-expectation branch UNIFORMLY; the boot reconcile
        already voiced that evidence, past tense, once. Only a CURRENT-session
        stamp can raise the present-tense alarm. One alert per stale identity;
        a fresh stamp mints a new identity and re-arms; the identity is latched
        only AFTER the alert sink succeeds (review 06a5b435 MINOR 3 — a raising
        sink retries next poll instead of silently consuming the episode)."""
        from shared.coordinator.heartbeat import read_liveness_stamp

        if self._initial_deadline is None and self._initial_grace_s is not None:
            self._initial_deadline = now + timedelta(
                seconds=self._initial_grace_s
            )

        stamp = read_liveness_stamp(self._stamp_path)
        is_current = (
            stamp is not None and stamp.get("session_id") == self._session_id
        )
        message: "str | None" = None
        identity: "str | None" = None

        if not is_current:
            if (
                self._initial_deadline is not None
                and now > self._initial_deadline
            ):
                identity = f"no-first-beat:{self._initial_deadline.isoformat()}"
                message = (
                    "coordinator heartbeat has produced NO current-session "
                    "liveness stamp past its boot expectation "
                    f"({self._initial_deadline.isoformat()}) — the first beat "
                    "never landed (wedged before stamping, or the thread "
                    "failed silently)."
                )
        elif bool(stamp.get("thread_dead")):
            identity = f"thread-dead:{stamp.get('note', '')}"
            message = (
                "coordinator heartbeat thread DIED (its own wall-3 stamp): "
                f"{stamp.get('note', 'no detail recorded')}"
            )
        elif bool(stamp.get("stopped_cleanly")):
            identity = None  # a clean stop expects silence; nothing is due
        else:
            deadline = _parse_iso(stamp.get("next_expected_by"))
            if deadline is None:
                identity = "malformed-deadline"
                message = (
                    "coordinator heartbeat liveness stamp carries no parseable "
                    "next_expected_by — treating as WEDGED (unknown ≠ healthy)."
                )
            elif (now - deadline).total_seconds() > self._slack_s:
                identity = f"stale:{deadline.isoformat()}"
                message = (
                    "coordinator heartbeat is LATE: the stamp's own deadline "
                    f"({deadline.isoformat()}) passed more than "
                    f"{self._slack_s:.0f}s ago — wedged cycle, hung I/O, or a "
                    "silently-failed thread."
                )

        if message is None:
            self._alerted_identity = None  # healthy/quiet: re-arm
            return None
        if identity == self._alerted_identity:
            return None  # already alerted for THIS stale episode
        try:
            self._alert(message)
        except Exception as exc:  # noqa: BLE001 — the megaphone's megaphone
            logger.error(
                "dead-man alert sink raised (%s); NOT latching — the notice "
                "retries next poll; original: %s",
                exc,
                message,
            )
            return message
        self._alerted_identity = identity
        return message


# ---------------------------------------------------------------------------
# Boot reconcile (§6.3)
# ---------------------------------------------------------------------------


def reconcile_boot_stamp(
    stamp: "Mapping[str, object] | None",
) -> "str | None":
    """One boot-time notice over the PREVIOUS session's stamp, or ``None``.

    Pure over an already-read stamp mapping (the factory performs the read for
    this reconcile; the heartbeat thread's graduation reset performs its OWN
    read at start — two reads by design, one owner each). The three-way split,
    each direction argued in the module docstring: ``thread_dead`` → the wedge the in-session watchdog saw
    (repeated at boot so a crash right after cannot bury it); neither dead nor
    cleanly-stopped → beats were still due when the process ended (crash, or a
    wedge that outlived the session); cleanly-stopped or no stamp → silence
    (the app being off is not a heartbeat failure, §6's same-process limit)."""
    if stamp is None:
        return None
    if bool(stamp.get("thread_dead")):
        return (
            "previous session's coordinator heartbeat thread DIED before "
            f"shutdown: {stamp.get('note', 'no detail recorded')} (last stamp "
            f"{stamp.get('completed_at', 'unknown')})."
        )
    if not bool(stamp.get("stopped_cleanly")):
        return (
            "previous session ended WITHOUT a clean coordinator-heartbeat stop "
            f"— last beat completed {stamp.get('completed_at', 'unknown')}, "
            f"next was due by {stamp.get('next_expected_by', 'unknown')} "
            "(process crash, or a heartbeat wedge that outlived the session)."
        )
    return None
