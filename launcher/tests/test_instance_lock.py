"""Tests — single-instance launcher guard (#670 Phase-B run-1 fix A).

Pure over an injected launcher-confirm probe + a tmp lock path: acquire / refuse-live-
launcher / reclaim-stale-pid / reclaim-recycled-pid / release, with no real second
process. The live concurrent boot + the forceful-exit handoff are validated at the
on-hardware re-run (live-only).
"""

from __future__ import annotations

import os

from launcher.instance_lock import (
    _is_live_launcher,
    acquire_instance_lock,
    lock_path_for_repo,
    refuse_message,
    release_instance_lock,
)


def _launcher(*pids: int):
    """Models a probe where the given pids ARE live BlarAI launchers (everything else
    -- dead, or a recycled pid owned by some other process -- is not)."""
    live = set(pids)
    return lambda pid: pid in live


def test_acquire_on_empty(tmp_path):
    lock = tmp_path / "launcher.lock"
    r = acquire_instance_lock(lock, pid=111, is_live_launcher=_launcher())
    assert r.acquired and not r.reclaimed_stale and r.holder_pid == 0
    assert lock.read_text().strip() == "111"


def test_refuse_live_launcher(tmp_path):
    lock = tmp_path / "launcher.lock"
    lock.write_text("222")  # a peer launcher holds it
    r = acquire_instance_lock(lock, pid=111, is_live_launcher=_launcher(222))  # 222 a live launcher
    assert not r.acquired and r.holder_pid == 222
    assert lock.read_text().strip() == "222"  # peer's lock untouched


def test_reclaim_stale_pid(tmp_path):
    lock = tmp_path / "launcher.lock"
    lock.write_text("222")  # a DEAD holder
    r = acquire_instance_lock(lock, pid=111, is_live_launcher=_launcher())  # 222 not a live launcher
    assert r.acquired and r.reclaimed_stale
    assert lock.read_text().strip() == "111"


def test_reclaim_recycled_pid_not_a_launcher(tmp_path):
    # The holder pid is ALIVE but belongs to a non-launcher process (the OS recycled the
    # crashed launcher's pid). The probe says "not a live launcher" -> reclaim, NOT a false
    # refuse (#670 hardening — the crash-relaunch false-positive this closes).
    lock = tmp_path / "launcher.lock"
    lock.write_text("222")
    r = acquire_instance_lock(lock, pid=111, is_live_launcher=lambda _pid: False)
    assert r.acquired and r.reclaimed_stale
    assert lock.read_text().strip() == "111"


def test_idempotent_for_own_pid(tmp_path):
    lock = tmp_path / "launcher.lock"
    lock.write_text("111")
    r = acquire_instance_lock(lock, pid=111, is_live_launcher=_launcher(111))
    assert r.acquired and not r.reclaimed_stale  # our own lock -> refresh, not a reclaim


def test_corrupt_lock_is_reclaimable(tmp_path):
    lock = tmp_path / "launcher.lock"
    lock.write_text("not-a-pid")
    r = acquire_instance_lock(lock, pid=111, is_live_launcher=lambda _pid: True)
    assert r.acquired
    assert lock.read_text().strip() == "111"


def test_acquire_creates_parent_dir(tmp_path):
    lock = tmp_path / "certs" / "launcher.lock"  # parent absent
    r = acquire_instance_lock(lock, pid=111, is_live_launcher=_launcher())
    assert r.acquired and lock.exists()


def test_release_removes_own_lock(tmp_path):
    lock = tmp_path / "launcher.lock"
    acquire_instance_lock(lock, pid=111, is_live_launcher=_launcher())
    assert release_instance_lock(lock, pid=111) is True
    assert not lock.exists()


def test_release_does_not_remove_peer_lock(tmp_path):
    lock = tmp_path / "launcher.lock"
    lock.write_text("222")  # peer's lock
    assert release_instance_lock(lock, pid=111) is False
    assert lock.read_text().strip() == "222"


def test_release_when_absent_is_false(tmp_path):
    assert release_instance_lock(tmp_path / "nope.lock", pid=111) is False


def test_lock_path_for_repo_is_under_certs(tmp_path):
    assert lock_path_for_repo(tmp_path) == tmp_path / "certs" / "launcher.lock"


def test_refuse_message_is_novice_actionable():
    msg = refuse_message(1234)
    assert "PID 1234" in msg and "close that one first" in msg.lower()


def test_refuse_message_generic_when_no_pid():
    assert "single-instance lock" in refuse_message(0).lower()


def test_default_probe_rejects_non_launcher_and_invalid():
    # The real psutil-backed probe: the pytest process IS alive but is NOT a BlarAI
    # launcher (its cmdline has no "-m launcher"), so it must NOT be treated as one; an
    # invalid pid is likewise not a launcher. (This is what makes the recycled-pid guard work.)
    assert _is_live_launcher(os.getpid()) is False
    assert _is_live_launcher(-1) is False
