"""Reuse-safe process-tree kill for the model-swap driver (#670 Problem 2).

The swap driver runs ONE task at a time by launching ``run-fleet.ps1`` (a long-lived
``pwsh -> opencode -> playwright-msedge`` subtree). Two paths must tree-kill that
subtree without ever killing the wrong process: the per-task TIMEOUT in
``_run_to_logfile_tree`` (the primary wedge defense) and the out-of-band BUDGET abort.
Both hold the child's ``subprocess.Popen``.

WHY NOT the harness twin (``tests/harness/process_tree.py``): that helper takes a bare
PID and falls back to ``taskkill /T /F /PID``. A bare PID is a PID-reuse hazard — on
Windows ``proc_kill`` re-opens the PID by integer with no held handle, so a recycled PID
gets a stranger killed. This module is the production twin EXTENDED to defeat reuse:

  * the DIRECT child is killed via the held ``Popen`` OS handle (``proc.kill()`` while
    ``poll() is None``) — Windows keeps the PID reserved while a handle is open, so this
    is the ONLY truly reuse-proof kill;
  * DESCENDANTS (the grandchildren we did NOT spawn, so we hold no handle) are killed via
    psutil with a per-process ``create_time`` identity re-check immediately before each
    kill, and gated on ``create_time() > child_create_time`` (T0) so a reused descendant
    PID whose new owner is OLDER than our child is rejected;
  * there is NO blind ``taskkill`` fallback — when psutil is unavailable we kill ONLY the
    direct child via the handle and skip descendant reaping. Failure to PROVE a
    descendant's identity fails CLOSED to do-not-kill, never to a blind kill.

RESIDUAL (documented, not hidden): PID-keyed DESCENDANT kills retain an irreducibly
non-zero reuse window — we cannot hold an OS handle for a grandchild we did not spawn.
The ``create_time`` gate shrinks it to near-zero; ``reconcile_at_boot`` + ``real_stop_ovms``
(the next-boot 30B stop) are the named backstop. A re-parented grandchild that outlives the
root kill is a bounded leak until the next boot reconcile.

Never raises — safe to call from a ``finally`` or a watchdog thread.
"""

from __future__ import annotations


def terminate_process_tree(proc, *, child_create_time: "float | None" = None) -> None:
    """Tree-kill the run-fleet child held in *proc* (a ``subprocess.Popen``) and its
    descendants, reuse-safe and best-effort. NEVER raises.

    Parameters
    ----------
    proc:
        The ``Popen`` of the direct child. Its OS handle pins the PID while ``poll() is
        None``, making the direct-child kill truly reuse-proof. ``None`` / a bad pid -> no-op.
    child_create_time:
        The direct child's psutil ``create_time`` captured at spawn (the abort path passes
        it). Used to (a) refuse to enumerate from a reused ROOT pid and (b) gate descendants
        on ``create_time() > T0``. ``None`` falls back to the held-handle + per-descendant
        identity match (sufficient for the fresh-handle timeout path).
    """
    if proc is None:
        return
    pid = getattr(proc, "pid", None)
    if not isinstance(pid, int) or pid <= 0:   # cleared/never-set holder must not root a kill
        return

    # Enumerate descendants FIRST (while the parent still anchors the tree), capturing each
    # one's create_time so we can re-verify identity right before its kill.
    descendants = []  # list[(psutil.Process, create_time)]
    try:
        import psutil

        try:
            root = psutil.Process(pid)
        except Exception:  # noqa: BLE001 — NoSuchProcess/AccessDenied: nothing to enumerate
            root = None
        if root is not None:
            try:
                ok_root = child_create_time is None or root.create_time() == child_create_time
            except Exception:  # noqa: BLE001 — can't read identity -> trust only the held handle
                ok_root = child_create_time is None
            if ok_root:
                try:
                    for child in root.children(recursive=True):
                        try:
                            descendants.append((child, child.create_time()))
                        except Exception:  # noqa: BLE001
                            pass
                except Exception:  # noqa: BLE001
                    pass
    except Exception:  # noqa: BLE001 — psutil absent: direct-handle kill only, NO blind taskkill
        descendants = []

    # 1) DIRECT child — kill via the held OS handle (reuse-proof; needs no psutil).
    try:
        if proc.poll() is None:
            proc.kill()
    except Exception:  # noqa: BLE001
        pass

    # 2) DESCENDANTS — leaves first; re-verify identity (same create_time) AND that the
    #    process is younger than our child, immediately before each kill.
    terminated = []
    for child, ct in reversed(descendants):
        try:
            if not child.is_running():
                continue
            cur = child.create_time()
            if cur != ct:
                continue  # PID reused since enumeration — NOT our descendant
            if child_create_time is not None and cur <= child_create_time:
                continue  # older than our child — cannot be our descendant
            child.terminate()  # Windows: TerminateProcess (forceful)
            terminated.append(child)
        except Exception:  # noqa: BLE001
            pass

    # 3) reap the ones we actually terminated (best-effort; bounded).
    try:
        import psutil

        psutil.wait_procs(terminated, timeout=3.0)
    except Exception:  # noqa: BLE001
        pass
