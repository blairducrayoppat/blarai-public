"""#1076 — the fix-cycle re-dispatch must not destroy the evidence of what it retries.

Measured defect (run ``20260723-001147-bd``): the layout fix cycle re-dispatched
``add-card`` inside the SAME run, onto the SAME
``<runs_dir>/<run_id>/run-fleet-add-card.log``, opened ``mode="w"``. The surviving file
was 9 lines of the refused re-run; the original 00:33-01:05 attempt's console output —
the only place git's error from the #1074 swallow ever existed — was overwritten at
01:05. #1066 records the root cause as NOT ESTABLISHED and names this as the reason.

Evidence destruction on the repair path is the worst possible time to lose a log: the
repair only runs because something already went wrong, so the truncated content is
always the record of a failure.

These locks drive REAL child processes through the REAL entry points. Only the child's
argv is substituted (pwsh is not what is under test), so the file open, the handle
inheritance and the writes are the shipped ones.
"""

from __future__ import annotations

import functools
import subprocess
import sys

from shared.fleet import doom_check
from shared.fleet import swap_ops as so


def _echoing_popen(marker: str):
    """A ``popen`` for ``_run_to_logfile_tree``'s injection seam that runs a REAL child
    writing *marker* to the inherited handle — the genuine write path, with only the
    argv swapped for one that does not need pwsh."""

    def _popen(_cmd, **kw):
        return subprocess.Popen(
            [sys.executable, "-c", f"import sys; sys.stdout.write({marker!r})"], **kw)

    return _popen


def _echoing_run(text: str):
    """The same, for ``_run_to_logfile_at``'s ``run`` seam (a bounded child)."""

    def _run(_cmd, **kw):
        return subprocess.run(
            [sys.executable, "-c", f"import sys; sys.stdout.write({text!r})"], **kw)

    return _run


def _dispatch_task_twice(tmp_path, monkeypatch, markers=("ATTEMPT-ONE", "ATTEMPT-TWO")):
    """Drive the REAL ``real_run_task`` twice for the SAME task in the SAME run — the
    fix-cycle shape. ``_run_to_logfile_tree`` is the code under test and runs unmodified;
    only its documented ``popen`` seam is bound, to a child we can identify."""
    cfg = so.build_default_config(str(tmp_path / "agentic"), str(tmp_path / "projects"))
    (cfg.runs_dir / "RID").mkdir(parents=True, exist_ok=True)
    (cfg.runs_dir / "RID" / "SUMMARY.txt").write_text(
        "- add-card: processed\n  RESULT: MERGED into your project\n", encoding="utf-8")
    real_tree = so._run_to_logfile_tree
    for marker in markers:
        monkeypatch.setattr(
            so, "_run_to_logfile_tree",
            functools.partial(real_tree, popen=_echoing_popen(marker)))
        so.real_run_task(cfg, "RID", {"repo": "X", "task": "add-card", "prompt": "p"})
    return cfg.runs_dir / "RID" / "run-fleet-add-card.log"


def test_re_dispatch_preserves_the_first_attempts_log(tmp_path, monkeypatch):
    # THE LOCK: attempt N's record survives attempt N+1.
    log = _dispatch_task_twice(tmp_path, monkeypatch)
    text = log.read_text(encoding="utf-8", errors="replace")
    assert "ATTEMPT-ONE" in text, (
        "the re-dispatch destroyed the first attempt's log — the #1076 defect: the "
        "repair path erased the record of the failure it exists to repair")
    assert "ATTEMPT-TWO" in text
    assert text.index("ATTEMPT-ONE") < text.index("ATTEMPT-TWO")  # chronological


def test_re_dispatch_keeps_one_file_and_separates_the_attempts(tmp_path, monkeypatch):
    # Append, NOT a suffixed sibling. Precision matters here, because the fixed-path
    # liveness argument does NOT apply to this file: EVERY consumer of run-fleet-*.log
    # globs (doom_check.py:159, monitor.py:327, watch.py:108, failure_taxonomy.py:215,
    # swap_driver.py:675), so a suffixed sibling would be seen by all of them. The
    # exact-path argument stands on design-critique.log alone — locked separately in
    # test_design_critique_log_keeps_its_fixed_path_for_the_doom_check. What this case
    # locks is the weaker but still real property: one file per task keeps the record
    # chronological and keeps the count-bounded readers from spending their file budget
    # on attempt siblings. The banner lets a human tell the attempts apart.
    log = _dispatch_task_twice(tmp_path, monkeypatch)
    siblings = sorted(p.name for p in log.parent.glob("run-fleet-*"))
    assert siblings == ["run-fleet-add-card.log"], (
        f"the attempts split across files {siblings} — the count-bounded readers cap how "
        "many run-fleet-*.log files they open, so attempt siblings crowd out real tasks")
    text = log.read_text(encoding="utf-8", errors="replace")
    assert "a further attempt at this step begins here" in text
    # The banner must not be mistakable for anything the log readers classify on.
    assert "VERDICT" not in text and "Best-of-N" not in text


def test_toggle_off_truncating_open_destroys_the_first_attempt(tmp_path, monkeypatch):
    # TOGGLE-OFF — the control tested with the lock disengaged: restore the historical
    # truncating open and the SAME probe must go RED. Without this, the lock above could
    # be passing for a reason unrelated to the fix.
    def _legacy_truncating_open(log_path):
        log_path.parent.mkdir(parents=True, exist_ok=True)
        return open(log_path, "w", encoding="utf-8", errors="replace"), 0

    monkeypatch.setattr(so, "_open_append_log", _legacy_truncating_open)
    log = _dispatch_task_twice(tmp_path, monkeypatch)
    text = log.read_text(encoding="utf-8", errors="replace")
    assert "ATTEMPT-TWO" in text                 # the re-run is there ...
    assert "ATTEMPT-ONE" not in text, (
        "the probe cannot see the defect: with mode='w' restored the first attempt's "
        "content must be GONE, otherwise the lock above proves nothing")


def test_run_to_logfile_at_offset_scopes_the_read_to_this_attempt(tmp_path):
    # Appending is only safe for the PARSING callers because the read is offset-scoped.
    # A whole-file read after an append would let a lap that produced no verdict inherit
    # the previous lap's — a silently wrong result, which is worse than a lost log.
    log = tmp_path / "runs" / "RID" / "critic-run.log"
    ok1, off1 = so._run_to_logfile_at(
        ["x"], log_path=log, timeout_s=30.0, run=_echoing_run("VERDICT: FIX FIRST\n"))
    ok2, off2 = so._run_to_logfile_at(
        ["x"], log_path=log, timeout_s=30.0, run=_echoing_run("no verdict this lap\n"))
    assert ok1 is True and ok2 is True
    assert off1 == 0 and off2 > 0
    whole = log.read_text(encoding="utf-8", errors="replace")
    assert "VERDICT: FIX FIRST" in whole            # attempt 1 preserved on disk ...
    slice_2 = so._read_log_from(log, off2)
    assert "VERDICT" not in slice_2                 # ... but invisible to attempt 2's parse
    assert "no verdict this lap" in slice_2


def test_critic_lap_never_inherits_the_previous_laps_verdict(tmp_path, monkeypatch):
    # The composed seam through the real real_run_critic: lap 1 returns a verdict, lap 2
    # produces none. Lap 2 must answer with the fallback, never lap 1's stale verdict.
    monkeypatch.setattr(so, "real_load_14b", lambda *a, **k: True)
    monkeypatch.setattr(so, "real_wait_ready", lambda *a, **k: True)
    cfg = so.build_default_config(str(tmp_path / "agentic"), str(tmp_path / "projects"))
    real_at = so._run_to_logfile_at

    monkeypatch.setattr(so, "_run_to_logfile_at", functools.partial(
        real_at, run=_echoing_run("VERDICT: FIX FIRST\n1. rename the widget\n")))
    lap1 = so.real_run_critic(cfg, "RID", "C:/app", "main")
    assert lap1.get("verdict") == "FIX FIRST" and lap1.get("should_iterate") is True

    monkeypatch.setattr(so, "_run_to_logfile_at", functools.partial(
        real_at, run=_echoing_run("the critic crashed before saying anything\n")))
    lap2 = so.real_run_critic(cfg, "RID", "C:/app", "main")
    assert lap2 == dict(so._CRITIC_FALLBACK), (
        "lap 2 inherited lap 1's verdict from the appended log — the offset-scoped read "
        "is what makes appending safe for the parsing callers (#1076)")
    # ... and lap 1's evidence is still on disk, which is the point of the change.
    text = (cfg.runs_dir / "RID" / "critic-run.log").read_text(encoding="utf-8")
    assert "rename the widget" in text and "crashed before saying anything" in text


def test_design_critique_log_keeps_its_fixed_path_for_the_doom_check(tmp_path, monkeypatch):
    # The seam the append decision protects: doom_check reads <run>/design-critique.log by
    # EXACT path as a run-is-alive signal. Two design laps must both advance THAT file, or
    # a healthy multi-lap design phase reads as stalled to the doom check.
    cfg = so.build_default_config(str(tmp_path / "agentic"), str(tmp_path / "projects"))
    real_at = so._run_to_logfile_at
    for marker in ("LAP-ONE", "LAP-TWO"):
        payload = '{"ShouldIterate":true,"Feedback":"' + marker + '"}\n'
        monkeypatch.setattr(so, "_run_to_logfile_at",
                            functools.partial(real_at, run=_echoing_run(payload)))
        result = so.real_run_design_loop(cfg, "RID", "C:/app", "goal", "[]")
        assert result.get("feedback") == marker    # this lap's own critique, not the last
    watched = cfg.runs_dir / "RID" / "design-critique.log"
    text = watched.read_text(encoding="utf-8", errors="replace")
    assert "LAP-ONE" in text and "LAP-TWO" in text
    assert doom_check.newest_progress_mtime(cfg, "RID") is not None, (
        "the design phase's liveness signal went blind — doom_check watches this exact "
        "path, so lap 2 must not land on a different filename")


def _truncating_log_writes(source: str) -> list[str]:
    """Every truncating write to a log-ish path in *source*, by AST (#1076 F6).

    The first version of this lock grepped for the literal ``open(log_path, "w"``, which
    only sees a site that names its variable ``log_path`` AND calls ``open`` positionally
    — a new site using ``logfile`` or ``Path.write_text`` walked straight past it. Shared
    by the lock and its toggle so the two cannot drift apart."""
    import ast

    def _mentions_log(node) -> bool:
        return "log" in ast.dump(node).lower()

    offenders: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        fname = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if fname == "open":
            # Two spellings, with the path in DIFFERENT places. `open(path, "w")` carries
            # the path first and the mode second; `path.open("w")` carries the path on the
            # attribute and the mode FIRST. Treating them alike made the Path form SILENT:
            # it read "w" as the path, found no "log" in it, and passed. swap_ops is
            # Path-centric — every log path here is a Path — so that was the likeliest
            # future regression of the very class this lock exists to catch.
            if isinstance(node.func, ast.Attribute):
                target, mode_args = node.func.value, list(node.args)
            elif node.args:
                target, mode_args = node.args[0], list(node.args[1:])
            else:
                continue
            mode_args += [kw.value for kw in node.keywords if kw.arg == "mode"]
            mode = next((a.value for a in mode_args
                         if isinstance(a, ast.Constant) and isinstance(a.value, str)), "r")
            if mode.startswith("w") and _mentions_log(target):
                offenders.append(f"line {node.lineno}: open(..., {mode!r})")
        elif fname in ("write_text", "write_bytes") and isinstance(node.func, ast.Attribute):
            if _mentions_log(node.func.value):
                offenders.append(f"line {node.lineno}: .{fname}() on a log path")
    return offenders


def test_swap_ops_opens_no_run_logfile_in_truncating_mode():
    # The structural lock: no call site may reintroduce a TRUNCATING write to a per-run
    # log. Every one of these paths is re-entered by a fix cycle, and the truncated
    # content is always a failure record.
    import inspect

    offenders = _truncating_log_writes(inspect.getsource(so))
    assert not offenders, (
        "a truncating write to a per-run logfile is back — attempt N+1 would erase "
        f"attempt N's record (#1076): {offenders}")


def test_the_truncation_lock_sees_every_truncating_spelling():
    # Toggle for the lock above: it is a source scan, so it must be shown to FIRE — on
    # every spelling that reaches the same defect, not only the one its author happened to
    # write. Two shapes defeated the literal grep (a differently named variable,
    # write_text); two more defeated the FIRST AST version, which read the Path form's
    # mode as its path (`path.open("w")`, write_bytes). The append and read cases must
    # stay silent, or the lock would fire on correct code and get disabled.
    offenders = _truncating_log_writes(
        'def a(logfile):\n'
        '    with open(logfile, "w", encoding="utf-8") as fh:\n'    # renamed variable
        '        fh.write("x")\n'
        'def b(task_log):\n'
        '    task_log.write_text("x")\n'                            # write_text
        'def c(run_log):\n'
        '    return run_log.open("w")\n'                            # Path.open — was SILENT
        'def d(the_log):\n'
        '    the_log.write_bytes(b"x")\n'                           # write_bytes
        'def e(logfile):\n'
        '    return open(logfile, mode="wb")\n'                     # keyword mode, binary
        'def ok1(log_path):\n'
        '    return open(log_path, "a")\n'                          # append: not an offence
        'def ok2(log_path):\n'
        '    return log_path.open("r")\n'                           # read: not an offence
        'def ok3(payload):\n'
        '    return open(payload, "w")\n'                           # not a log: out of scope
    )
    assert len(offenders) == 5, (
        f"the lock misses a truncating spelling (found {offenders})")


def test_oversized_log_rolls_aside_instead_of_growing_without_bound(tmp_path, monkeypatch):
    # F4: one caller (tools/dispatch_harness/probe.py, run_id="") writes OUTSIDE any run
    # dir, so appending there accumulates forever with nothing to prune it. Growth is
    # bounded by rolling ONE generation aside — and the rolled name must stay invisible to
    # the glob and exact-path readers, or it would be double-counted.
    monkeypatch.setattr(so, "_LOG_ROLL_BYTES", 64)
    log = tmp_path / "runs" / "run-fleet-t.log"
    log.parent.mkdir(parents=True)
    log.write_bytes(b"old evidence " + b"x" * 100)      # over the ceiling
    fh, offset = so._open_append_log(log)
    with fh:
        fh.write("fresh attempt\n")
    assert offset == 0                                   # a rolled log starts a new file
    assert log.read_text(encoding="utf-8") == "fresh attempt\n"
    assert b"old evidence" in log.with_name(log.name + ".prev").read_bytes()  # not deleted
    # The rolled generation must not be picked up by the aggregating/liveness readers.
    assert sorted(p.name for p in log.parent.glob("run-fleet-*.log")) == ["run-fleet-t.log"]


def test_under_ceiling_logs_are_never_rolled(tmp_path, monkeypatch):
    # The other direction for F4: below the ceiling nothing moves, so the roll can never
    # become the reason an attempt's record went missing. The real ceiling is 8 MiB, far
    # above any single run's output, so this is the case that holds in production.
    monkeypatch.setattr(so, "_LOG_ROLL_BYTES", 8 * 1024 * 1024)
    log = tmp_path / "runs" / "critic-run.log"
    log.parent.mkdir(parents=True)
    log.write_text("attempt one\n", encoding="utf-8")
    fh, offset = so._open_append_log(log)
    with fh:
        fh.write("attempt two\n")
    assert not log.with_name(log.name + ".prev").exists()
    assert offset > 0
    text = log.read_text(encoding="utf-8")
    assert "attempt one" in text and "attempt two" in text
