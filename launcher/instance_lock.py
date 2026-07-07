"""Single-instance launcher guard (#670 Phase-B run-1 fix A).

WHY. ``shared.security.cert_provisioning.provision_per_boot_certs`` mints a fresh
in-memory Certificate Authority on EVERY launcher boot and writes the nine per-boot
PEMs into the shared ``<repo_root>/certs`` dir, OVERWRITING the previous set. With
more than one launcher running (the run-1 shakedown had four), each boot stomps the
others' CA, so the gateway<->Policy-Agent mTLS handshake presents a leaf signed by
one boot's CA to a peer trusting a different boot's CA -> ``CERTIFICATE_VERIFY_FAILED``
-> Fail-Closed exit. There was no guard against concurrent launchers.

WHAT. A per-checkout PID-file lock acquired at boot BEFORE cert provisioning, so a
second instance refuses cleanly WITHOUT ever touching the shared certs dir. The lock
is keyed to the certs dir it protects (same ``repo_root`` scope), so launchers in
separate worktrees (separate certs dirs, no cross-stomp) never collide, while two
launchers on the SAME checkout are refused. A holder is confirmed to actually BE a
launcher (its cmdline runs ``-m launcher``) before a refusal, so a recycled pid after a
crash reclaims the lock rather than falsely refusing (#670 hardening).

SWAP-RELAUNCH ORDERING (the deadlock the LA flagged). The relaunch only acquires
AFTER the old instance is gone, two ways:
  * graceful swap -> the old launcher RELEASES the lock in ``_cleanup`` before it
    exits; the swap driver's settle waits on ``old_pid`` death; the relaunch then
    acquires the now-free lock.
  * wedged old (``interrupt_main`` not delivered) -> the step-aside watchdog forces
    ``os._exit``, which SKIPS ``_cleanup`` and leaves the lock holding a now-DEAD
    pid; the relaunch RECLAIMS it as stale.
Either way the relaunch never races a live old instance.

TESTABILITY. ``acquire`` / refuse-live-peer / reclaim-stale-pid / ``release`` are pure
over an injected liveness probe + lock path -- no real second process required. The
live parts (the actual concurrent boot, the forceful-exit handoff) are validated at
the on-hardware re-run.

Residual (accepted, single-user box): two launches reclaiming the SAME stale lock
within the same millisecond could both "acquire". That requires two boots racing
within ms of each other right after a crash; the common case -- a live peer -- is
refused correctly. Not worth an atomic compare-and-swap here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

# The lock lives in the certs dir it protects: same per-checkout scope, already the
# per-boot runtime-artifact directory. gitignored as certs/launcher.lock.
LOCK_FILE_NAME: str = "launcher.lock"


def lock_path_for_repo(repo_root: "str | Path") -> Path:
    """The single-instance lock path for a checkout (sibling to its per-boot certs)."""
    return Path(repo_root) / "certs" / LOCK_FILE_NAME


# A BlarAI launcher always runs as ``python -m launcher`` (the swap relaunch argv too), so
# a real holder's cmdline contains this marker. A bare pid-exists check is NOT enough: after
# a crash the OS can recycle the dead launcher's pid to an unrelated process, which a
# pid-only guard would mistake for a live BlarAI and falsely refuse (#670 hardening).
_LAUNCHER_CMDLINE_MARKER: str = "-m launcher"


def _is_live_launcher(pid: int) -> bool:
    """True ONLY if ``pid`` is a LIVE BlarAI launcher (its cmdline runs ``-m launcher``).

    Confirm the holder is actually our launcher before refusing; ANYTHING else -- a dead
    pid, a recycled pid now owned by an unrelated process, or an unreadable/absent probe
    -- is NOT our launcher, so the caller reclaims the lock as stale rather than falsely
    refusing. A real launcher runs as the operator (same user), so its cmdline is always
    readable; an unreadable process is therefore provably not ours.
    """
    if pid <= 0:
        return False
    try:
        import psutil

        proc = psutil.Process(pid)  # raises NoSuchProcess when the pid is dead
        return _LAUNCHER_CMDLINE_MARKER in " ".join(proc.cmdline())
    except Exception:  # noqa: BLE001 — dead / unreadable / psutil absent -> not our launcher
        return False


@dataclass(frozen=True)
class InstanceLockResult:
    """Outcome of an :func:`acquire_instance_lock` attempt."""

    acquired: bool
    holder_pid: int = 0  # the LIVE peer holding the lock when refused (else 0)
    reclaimed_stale: bool = False  # True when a DEAD holder's lock was reclaimed


def _read_holder_pid(lock_path: Path) -> "int | None":
    try:
        text = lock_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    try:
        return int(text)
    except ValueError:
        return None  # corrupt lock -> treat as no holder (reclaimable)


def acquire_instance_lock(
    lock_path: Path,
    *,
    pid: "int | None" = None,
    is_live_launcher: Callable[[int], bool] = _is_live_launcher,
) -> InstanceLockResult:
    """Acquire the single-instance lock, or refuse if a LIVE BlarAI launcher holds it.

    - no lock / corrupt lock -> acquire (write our pid);
    - lock held by a DEAD pid, OUR own pid, or a recycled pid that is NOT a launcher
      -> reclaim/refresh (acquire);
    - lock held by a DIFFERENT, LIVE BlarAI launcher -> refuse (``acquired=False`` +
      ``holder_pid``).

    The holder is confirmed to be an actual launcher (not merely an alive pid) before a
    refusal, so a recycled pid after a crash never falsely refuses (#670 hardening).
    Fail-closed on a write error (cannot record ownership -> do not proceed).
    """
    me = os.getpid() if pid is None else pid
    lock_path = Path(lock_path)

    holder = _read_holder_pid(lock_path)
    if holder is not None and holder != me and is_live_launcher(holder):
        return InstanceLockResult(acquired=False, holder_pid=holder)

    reclaimed = holder is not None and holder != me  # dead / recycled-non-launcher holder
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text(str(me), encoding="utf-8")
    except OSError:
        # Could not record ownership -> refuse to proceed (fail-closed). No specific
        # live holder, so holder_pid stays 0 and the caller aborts generically.
        return InstanceLockResult(acquired=False, holder_pid=0)

    return InstanceLockResult(acquired=True, reclaimed_stale=reclaimed)


def release_instance_lock(lock_path: Path, *, pid: "int | None" = None) -> bool:
    """Release the lock IFF this process holds it (never delete a peer's lock).

    Returns True if our lock file was removed. A graceful exit calls this; a forceful
    ``os._exit`` skips it, leaving a stale lock the next boot reclaims.
    """
    me = os.getpid() if pid is None else pid
    lock_path = Path(lock_path)
    if _read_holder_pid(lock_path) != me:
        return False
    try:
        lock_path.unlink()
        return True
    except OSError:
        return False


def refuse_message(holder_pid: int) -> str:
    """The novice-actionable refusal -- the operator's exact recurring trap, so the
    message IS the UX of the fix."""
    if holder_pid > 0:
        return f"BlarAI is already running (PID {holder_pid}) — close that one first."
    return (
        "BlarAI could not acquire its single-instance lock — another launcher may be "
        "running, or the certs/ dir is not writable. Close any open BlarAI and retry."
    )
