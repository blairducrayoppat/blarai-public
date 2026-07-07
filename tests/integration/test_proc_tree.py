"""Tests for proc_tree.terminate_process_tree — the reuse-safe tree-kill (#670 Problem 2).

Proves LA obligation B: the DIRECT child is killed via the held Popen handle; DESCENDANTS are
identity-checked (create_time) before each kill so a reused PID is never killed; there is NO
blind taskkill; and a bad/zero pid is a no-op. Never raises.
"""

from __future__ import annotations

import pytest

from shared.fleet.proc_tree import terminate_process_tree


class _Proc:
    """A subprocess.Popen stand-in (holds the direct child)."""

    def __init__(self, pid=4321, alive=True):
        self.pid = pid
        self._alive = alive
        self.killed = False

    def poll(self):
        return None if self._alive else 0

    def kill(self):
        self.killed = True
        self._alive = False


class _Desc:
    """A psutil.Process descendant stand-in with a controllable create_time identity."""

    def __init__(self, create_times):
        # create_times: iterable of values returned by successive create_time() calls (to model a
        # PID reused BETWEEN enumeration and the kill check).
        self._cts = list(create_times)
        self._i = 0
        self.terminated = False

    def create_time(self):
        v = self._cts[min(self._i, len(self._cts) - 1)]
        self._i += 1
        return v

    def is_running(self):
        return True

    def terminate(self):
        self.terminated = True


def _patch_psutil(monkeypatch, *, root_create_time, descendants):
    import psutil

    class _Root:
        def create_time(self):
            return root_create_time

        def children(self, recursive=True):
            return list(descendants)

    monkeypatch.setattr(psutil, "Process", lambda pid: _Root())
    monkeypatch.setattr(psutil, "wait_procs", lambda procs, timeout=None: ([], []))


def test_floor_on_bad_pid():
    # None / 0 / negative / non-int pid -> no-op (a cleared holder must not root a kill at PID 0).
    terminate_process_tree(None)
    for bad in (0, -1):
        p = _Proc(pid=bad)
        terminate_process_tree(p)
        assert p.killed is False
    p = _Proc(pid="nope")  # type: ignore[arg-type]
    terminate_process_tree(p)
    assert p.killed is False


def test_kills_direct_child_via_handle_when_no_descendants(monkeypatch):
    import psutil

    # NoSuchProcess for the enumeration -> descendants=[]; the DIRECT child is STILL killed via
    # the held handle (reuse-proof, needs no psutil) and nothing raises.
    monkeypatch.setattr(
        psutil, "Process",
        lambda pid: (_ for _ in ()).throw(psutil.NoSuchProcess(pid)),
    )
    p = _Proc(pid=4321)
    terminate_process_tree(p, child_create_time=1000.0)
    assert p.killed is True


def test_kills_valid_younger_descendant(monkeypatch):
    desc = _Desc(create_times=[1500.0])          # spawned AFTER the child -> a real descendant
    _patch_psutil(monkeypatch, root_create_time=1000.0, descendants=[desc])
    p = _Proc(pid=4321)
    terminate_process_tree(p, child_create_time=1000.0)
    assert desc.terminated is True               # younger + identity-matched -> killed
    assert p.killed is True                       # direct child killed via the handle


def test_skips_descendant_older_than_child(monkeypatch):
    # A "descendant" OLDER than our child is an impossible descendant -> a reused PID -> NOT killed.
    desc = _Desc(create_times=[500.0])
    _patch_psutil(monkeypatch, root_create_time=1000.0, descendants=[desc])
    terminate_process_tree(_Proc(pid=4321), child_create_time=1000.0)
    assert desc.terminated is False              # obligation B: reuse defeated


def test_skips_descendant_whose_pid_was_reused_since_enumeration(monkeypatch):
    # create_time CHANGES between enumeration (1500) and the pre-kill re-check (9999) -> the PID
    # was reused since we snapshotted it -> NOT our descendant -> NOT killed.
    desc = _Desc(create_times=[1500.0, 9999.0])
    _patch_psutil(monkeypatch, root_create_time=1000.0, descendants=[desc])
    terminate_process_tree(_Proc(pid=4321), child_create_time=1000.0)
    assert desc.terminated is False


def test_skips_all_when_root_create_time_mismatches(monkeypatch):
    # If the ROOT pid no longer matches the expected child create_time (root reused), we refuse to
    # enumerate from a stranger -> no descendant is touched (the direct handle kill is still safe).
    desc = _Desc(create_times=[1500.0])
    _patch_psutil(monkeypatch, root_create_time=7777.0, descendants=[desc])   # != expected 1000
    p = _Proc(pid=4321)
    terminate_process_tree(p, child_create_time=1000.0)
    assert desc.terminated is False
    assert p.killed is True                       # still kill OUR direct child via the handle


def test_never_raises_when_psutil_absent(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def no_psutil(name, *a, **k):
        if name == "psutil":
            raise ImportError("no psutil for this test")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_psutil)
    p = _Proc(pid=4321)
    terminate_process_tree(p, child_create_time=1000.0)   # must NOT raise; direct kill only
    assert p.killed is True
