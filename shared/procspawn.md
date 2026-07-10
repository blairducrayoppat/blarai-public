# The Windows process-spawn seam (#774)

Five paid incidents from spawning child processes on Windows used to live as
scattered local fixes, each carrying its lesson only in a docstring at the fix
site. This seam is the single blessed surface — the learned rules encoded once,
each carrying the incident that justified it, each proven by a conformance test
that asserts the **observable end property** on a real child process (lesson 219:
verify the property the control exists for, never the flag at the spawn site).

Two twins, deliberately parallel:

| Language   | Library                          | Conformance (positive control)          |
|------------|----------------------------------|-----------------------------------------|
| Python     | `blarai/shared/procspawn.py`     | `blarai/shared/tests/test_procspawn.py` |
| PowerShell | `agentic-setup/scripts/spawn-lib.ps1` | `agentic-setup/scripts/verify-spawn-lib.ps1` |

Nothing is wired into a live script yet — existing spawn sites migrate later,
deliberately. This ships the seam and its positive control.

## Rule → incident → test

| Rule | What it says | Incident it was paid for | Python test | PowerShell test |
|------|--------------|--------------------------|-------------|-----------------|
| **R1** | A console-less DETACHED python child must run via the interpreter's `pythonw.exe`, not the venv `python.exe` shim (the shim re-spawns the base console-subsystem interpreter as a child, so the detach is defeated one hop down and the child gets a fresh visible console). | #761 / lesson 219 — "The flag that worked, one process too early." The operator screenshotted a closable console despite `DETACHED_PROCESS` verified at every spawn site. | `test_r1_pythonw_sibling_resolves_venv_shim`, `test_r1_detached_child_has_no_console` (child self-reports `GetConsoleWindow()==NULL`) | R1 block: `Resolve-PythonwSibling`, detached child `CONSOLE_HWND=NULL` |
| **R2** | Never hide the console of an interactive / Textual python child — a hidden console (`CREATE_NO_WINDOW`) crashed Textual ("Driver must be in application mode"). Hiding is safe only for non-interactive console children (git/tasklist/cmd). | #761 / 2026-07-06 Textual crash. | `test_r2_hidden_console_runs_and_captures` | R4/R5 blocks use `NoNewWindow` on captured, non-interactive children only |
| **R3** | A console-less child with inherited-but-broken cp1252 stdio crashes on its first non-ASCII print. Pin `PYTHONUTF8=1` + `PYTHONIOENCODING=utf-8` and redirect stdio to a file. | #761 second half — the banner-print crash on the first live swap-back once the visible console (the bug) that had been silently providing working stdio was removed. | `test_r3_unicode_round_trip_stdout_and_stderr` (emoji + cp1252-hostile chars on both streams) | R3 block: emoji + euro round-trip on STDOUT and STDERR |
| **R4** | A child reading an inherited non-TTY stdin that never EOFs blocks forever; a parent holding a captured PIPE a grandchild inherits deadlocks. Feed an empty/DEVNULL stdin (instant EOF) and drain stdout/stderr to files, never a parent-held pipe. | opencode-run init stall (fleet-lib `Invoke-AgentRun`, 2026-06-18); the `Tee-Object` server-launcher hang (FIELD_NOTES lesson 161); the #759 ACP-spike undrained-PIPE dodge. | `test_r4_captures_full_output_and_honest_exit`, `test_r4_devnull_stdin_does_not_hang`, `test_r4_supplied_stdin_is_delivered` | R4 block: full capture + honest exit; stdin-reading child does not hang |
| **R5** | On timeout, kill the whole process TREE, not just the launched process — a launcher's grandchildren (OVMS, backends, workers) outlive a parent-only kill and hold ports / bleed the budget. | #630 — a bare `terminate()` orphaned the Python backend holding port 5001, silently degrading the gate `2342/0 → ~2333/9`. | `test_r5_terminate_process_tree_kills_grandchild`, `test_r5_run_captured_timeout_tree_kills` | R5 block: parent-with-grandchild, both dead after tree-kill |

## Caveat (documented, not an API method)

A process's **exit code is not proof its side effect completed**. `msedge
--screenshot` hands the write to a detached worker and the launcher exits 0 ~4s
before the PNG lands, and `--screenshot` silently no-ops on flag order
(capture-app.ps1, pinned 2026-06-26). When a spawn's real deliverable is a side
effect, **poll for the end property** — do not trust process exit. `run_captured`
/ `Invoke-CapturedRun` report the launched process's own exit honestly; they
cannot vouch for a detached worker they never see.

## Running the controls

```bash
# Python (from the blarai repo root, with the test data dir redirected)
python -m pytest shared/tests/test_procspawn.py -q
```
```powershell
# PowerShell (PS7 / pwsh — also what the scheduled task runs)
pwsh -NoProfile -File agentic-setup/scripts/verify-spawn-lib.ps1
```

Both are offline, need no GPU, and finish in a few seconds. The window/console
checks are Windows-only and skip cleanly elsewhere.
