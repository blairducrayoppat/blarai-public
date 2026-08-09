"""#1341 — the battery scorecard must record what it OBSERVED, at the instant it
claims to describe.

Three defects, all measured on two consecutive real battery nights, all of the same
shape: a partial observation banked as a whole one.

1. ``evidence.summary`` was a PATH to a file the scored run keeps rewriting. The
   STALLED card for ``20260808-160538-bd`` cited a ``SUMMARY.txt`` that had, by the
   time anyone read the card, been rewritten to ``RESULT: MERGED`` — the card's own
   evidence contradicting its verdict.
2. ``sandbox_commit_count`` was sampled by the PRE-DISPATCH freshness gate. Both
   nights banked ``"1"``: ``night-20260807-195325`` for a GREEN run that ended at 14
   commits, ``night-20260808-160336`` for a run that reached 11. Wrong on a success
   and on a failure, in the same direction — it measured the seed, not the run.
3. A terminal ``STALLED`` was asserted while the dispatch's driving process was still
   alive (``pwsh`` 5364), and the run went on to merge four tasks. The harness
   measured its own patience running out and named that a failure of the run.

Every test below drives the REAL surfaces — the real writer, the real validator, the
real ``run_battery`` loop — because each defect lived precisely in what reached disk.
Deterministic and GPU-free: no AO, no model, no dispatch. In the standing gate
(tests/integration is in scope). asyncio_mode=auto.
"""

from __future__ import annotations

import json
import subprocess
from hashlib import sha256
from pathlib import Path

import pytest

from tools.dispatch_harness import battery as bat
from tools.dispatch_harness import live_dispatch as ld
from tools.dispatch_harness import scorecard as sc
from tools.dispatch_harness.scorecard import Scorecard

_SPEC_DIR = Path(__file__).resolve().parents[2] / "evals" / "battery"


# ===========================================================================
# Fixtures — the same shapes test_battery_runner.py drives, plus a harness
# that BUILDS (the whole point: the sandbox must change under the runner)
# ===========================================================================


def _git(repo, *args):
    cp = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@local", "-c", "user.name=t",
         "-c", "commit.gpgsign=false", *args],
        capture_output=True, text=True,
    )
    assert cp.returncode == 0, f"git {' '.join(args)} failed: {cp.stderr}"


def _make_sandbox(projects_dir, name, subjects):
    repo = Path(projects_dir) / name
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")
    for subject in subjects:
        _git(repo, "commit", "-q", "--allow-empty", "-m", subject)
    return repo


def _card(repo_name):
    """The REAL B1 card retargeted at a fixture sandbox — only the evidence axis
    is under test, so the card itself stays production."""
    card = dict(bat.load_cards(_SPEC_DIR)["B1"])
    card["repo"] = repo_name
    return card


def _live_cfg(tmp_path):
    from shared.fleet.dispatch import FleetDispatchConfig

    return FleetDispatchConfig(
        scripts_dir=tmp_path / "s", queue_path=tmp_path / "state" / "q.json",
        runs_dir=tmp_path / "state" / "runs",
        projects_dir=tmp_path / "projects")


class _BuildingHarness:
    """A harness whose ``run_job`` does what a real dispatch does to the record: it
    ADDS COMMITS to the sandbox and writes a ``SUMMARY.txt``.

    This is the instrument the seed-vs-run defect needs. A harness that leaves the
    sandbox untouched cannot tell a pre-dispatch count from a post-dispatch one — the
    two are equal — so it would pass against the defective code and prove nothing."""

    def __init__(self, cfg, *, build_commits=3, summary_text="RESULT: STALLED\nnothing yet\n",
                 run_id="20260808-160538-bd", repo_dir=None):
        self.config = cfg
        self.overall_timeout_s = 0.0
        self.dispatched: list[str] = []
        self._build_commits = build_commits
        self._summary_text = summary_text
        self._run_id = run_id
        self._repo_dir = repo_dir

    async def run_job(self, job):
        from tools.dispatch_harness.report import JobReport

        self.dispatched.append(job.repo)
        repo = self._repo_dir or (Path(self.config.projects_dir) / job.repo)
        for i in range(self._build_commits):
            _git(repo, "commit", "-q", "--allow-empty", "-m", f"agent: built page {i}")
        run_dir = Path(self.config.runs_dir) / self._run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "SUMMARY.txt").write_text(self._summary_text, encoding="utf-8")
        # No driver scorecard on disk -> synthesize_scorecard -> the STALLED path that
        # banked the false record on 2026-08-08.
        return JobReport(repo=job.repo, goal=job.goal, verdict="COMPLETE",
                         outcome="MERGED", run_id=self._run_id)


# ===========================================================================
# (c) THE INTERVAL WITNESS — tools/dispatch_harness/live_dispatch.py
#
# Driven through an INJECTED process table so the control can be proved to FIRE
# and, on the same code, proved to go quiet (principle 12: a lock ships with the
# test that shows it blocking AND the toggle that shows the probe failing when
# the lock is off). Every row is (pid, image, cmdline).
# ===========================================================================


@pytest.mark.parametrize("image,cmdline,expect_label", [
    ("pwsh.exe", r"pwsh -NoProfile -File C:\Users\x\scripts\run-fleet.ps1 -Queue q.json",
     "run-fleet.ps1"),
    ("powershell.exe", r"powershell -File .\run-fleet.ps1", "run-fleet.ps1"),
    ("pythonw.exe", "pythonw.exe -m shared.fleet.swap_ops --spec spec.json",
     "shared.fleet.swap_ops"),
    ("python.exe", "python -m tools.dispatch_harness.acp_coder --model coder-30b",
     "tools.dispatch_harness.acp_coder"),
])
def test_every_driver_form_is_detected_as_a_live_interval(image, cmdline, expect_label):
    got = ld.probe_live_dispatch([(4242, image, cmdline)], self_pid=1)
    assert got.state == ld.LIVE and got.is_live
    assert got.pids == (4242,)
    assert expect_label in got.detail  # the record NAMES who, not just that


def test_an_empty_table_reads_absent_the_toggle_that_makes_live_meaningful():
    """The other half of the pair above. Without this the LIVE assertions could pass
    against a function that returns LIVE unconditionally."""
    got = ld.probe_live_dispatch([], self_pid=1)
    assert got.state == ld.ABSENT and not got.is_live
    assert got.pids == () and got.detail == ""


def test_the_battery_runner_never_matches_itself():
    """The self-match trap. The PowerShell twin matches ``-m tools.dispatch_harness.``
    as a bare prefix and is safe only because it is the runner's PARENT; this module
    is called FROM the runner, so that prefix would report a live dispatch on an idle
    box for every card ever scored. Both the calling process AND a peer battery must
    read ABSENT."""
    battery_cmd = "python -m tools.dispatch_harness.battery --jobs B9"
    assert ld.probe_live_dispatch([(99, "python.exe", battery_cmd)],
                                  self_pid=99).state == ld.ABSENT   # excluded by pid
    assert ld.probe_live_dispatch([(1234, "python.exe", battery_cmd)],
                                  self_pid=99).state == ld.ABSENT   # and by name


def test_the_form_must_match_its_own_image_not_merely_be_mentioned():
    """The twin's S3 trap: ``-m shared.fleet.swap_ops`` appears verbatim inside any
    shell that MENTIONS it, so argument-text matching lets a diagnostic one-liner, a
    grep — or this very test file — pin the guard as though a dispatch were live."""
    decoy = r"""pwsh -Command "Get-CimInstance Win32_Process | ? { $_.CommandLine -match '-m shared.fleet.swap_ops' }" """
    assert ld.probe_live_dispatch([(7, "pwsh.exe", decoy)], self_pid=1).state == ld.ABSENT
    # ...and a python process that merely names run-fleet.ps1 is not a shell running it.
    assert ld.probe_live_dispatch(
        [(8, "python.exe", "python analyze.py --script run-fleet.ps1")],
        self_pid=1).state == ld.ABSENT


def test_an_unreadable_command_line_is_unknown_never_absent():
    """The elevation blind spot. A non-elevated caller cannot read an elevated
    process's command line, so a driver-capable image hiding one means "I cannot
    tell" — and reporting that as an idle box is fail-OPEN in the one direction that
    lets a live run be scored dead."""
    got = ld.probe_live_dispatch([(555, "pwsh.exe", None)], self_pid=1)
    assert got.state == ld.UNKNOWN and not got.is_live
    assert got.pids == (555,)
    assert "blind spot" in got.detail


def test_an_unreadable_process_table_is_unknown_never_absent():
    def _explode():
        raise OSError("process table unavailable")
        yield  # pragma: no cover — generator shape only

    got = ld.probe_live_dispatch(_explode(), self_pid=1)
    assert got.state == ld.UNKNOWN
    assert "could not read the process table" in got.detail


def test_a_live_driver_outranks_a_blind_spot_in_the_same_table():
    """A positive observation is stronger evidence than an unreadable one, and the
    record should name the driver rather than shrug."""
    got = ld.probe_live_dispatch(
        [(1, "python.exe", None),
         (2, "pythonw.exe", "pythonw -m shared.fleet.swap_ops --spec s.json")],
        self_pid=99)
    assert got.state == ld.LIVE and got.pids == (2,)


# ===========================================================================
# (a) EVIDENCE CAPTURED, NOT REFERENCED
# ===========================================================================


def test_capture_freezes_content_that_the_run_later_rewrites(tmp_path):
    """THE 2026-08-08 defect, reproduced. The scorecard cited SUMMARY.txt as proof of
    a stall; the run then rewrote it to ``RESULT: MERGED``. After this change the card
    still holds what it actually read, and the hash proves the file has since moved."""
    summary = tmp_path / "SUMMARY.txt"
    summary.write_text("RESULT: STALLED\njob could not run\n", encoding="utf-8")
    frozen = bat.capture_evidence_pointers({"summary": str(summary)})

    assert "RESULT: STALLED" in frozen["summary_excerpt"]
    assert frozen["summary"] == str(summary)          # the pointer is KEPT, not replaced
    assert frozen["summary_sha256"] == sha256(summary.read_bytes()).hexdigest()
    assert frozen["evidence_captured_utc"]

    summary.write_text("RESULT: MERGED\n4 tasks delivered\n", encoding="utf-8")
    assert "RESULT: STALLED" in frozen["summary_excerpt"]   # the evidence did not drift
    assert "MERGED" not in frozen["summary_excerpt"]
    # ...and the drift is DETECTABLE, which is what "re-derivable" buys:
    assert frozen["summary_sha256"] != sha256(summary.read_bytes()).hexdigest()


def test_capture_is_multi_line_safe_and_survives_the_fail_closed_writer(tmp_path):
    """The #1324 shape aimed at this change: a value composed here must survive the
    seam it is written through. SUMMARY.txt is a multi-line log far longer than the
    evidence ceiling, and ``write_scorecard`` REFUSES newlines and >1000-char values —
    so the composer is checked at the writer, not only in isolation."""
    summary = tmp_path / "SUMMARY.txt"
    summary.write_text("\n".join(f"line {i}: " + "x" * 60 for i in range(200)),
                       encoding="utf-8")
    card = Scorecard(
        job_id="B9", verdict=sc.VERDICT_STALLED, attribution=sc.ATTRIBUTION_HARNESS,
        evidence=bat.capture_evidence_pointers({"oracle_status": "unknown",
                                                "summary": str(summary)}),
    )
    assert sc.validate(card) == []
    out = tmp_path / "B9.scorecard.json"
    sc.write_scorecard(card, out)
    written = sc.read_scorecard(out)
    excerpt = written.evidence["summary_excerpt"]
    assert 0 < len(excerpt) <= bat.EVIDENCE_EXCERPT_MAX_CHARS
    assert "\n" not in excerpt and "\r" not in excerpt
    assert excerpt.endswith("…")                       # bounded, and SAYS it is bounded
    assert written.evidence["summary_bytes"] == str(summary.stat().st_size)


def test_an_uncapturable_pointer_is_named_never_silent(tmp_path):
    """Fail-loud (principle 11): a capture that could not happen is recorded as a
    named failure, never as a missing key that reads like 'nothing to see'."""
    got = bat.capture_evidence_pointers({"summary": str(tmp_path / "gone" / "SUMMARY.txt")})
    assert "summary_capture_error" in got
    assert "summary_excerpt" not in got and "summary_sha256" not in got

    # A directory, and anything else that is not a regular file, is refused rather
    # than opened — a pointer is a string from a driver-emitted card, and on Windows
    # a device name or named pipe opens fine and can block forever.
    got = bat.capture_evidence_pointers({"summary": str(tmp_path)})
    assert "not a regular file" in got["summary_capture_error"]


def test_a_file_past_the_ceiling_is_refused_not_partially_hashed(tmp_path, monkeypatch):
    """A digest of the first N bytes offered as the file's identity would be a partial
    measurement wearing a whole one's name — this ticket's own defect, one layer down.
    The capture records its refusal instead."""
    monkeypatch.setattr(bat, "EVIDENCE_CAPTURE_MAX_BYTES", 32)
    big = tmp_path / "SUMMARY.txt"
    big.write_text("x" * 4096, encoding="utf-8")
    got = bat.capture_evidence_pointers({"summary": str(big)})
    assert "capture ceiling" in got["summary_capture_error"]
    assert "summary_sha256" not in got


def test_capture_touches_only_declared_pointers(tmp_path):
    """A short status is not a path, and must not be opened as one."""
    got = bat.capture_evidence_pointers({"oracle_status": "unknown", "mode": "plan-graph"})
    assert got == {"oracle_status": "unknown", "mode": "plan-graph"}
    assert "evidence_captured_utc" not in got   # nothing was captured, so nothing is stamped


# ===========================================================================
# (b) THE COMMIT COUNT IS RE-DERIVED AT WRITE TIME
# ===========================================================================


def test_the_count_is_re_read_after_the_build(tmp_path):
    repo = _make_sandbox(tmp_path, "battery-count", ["init battery sandbox"])
    seed = bat.probe_sandbox_freshness(repo)
    assert seed.commit_count == 1
    for i in range(3):
        _git(repo, "commit", "-q", "--allow-empty", "-m", f"agent: page {i}")

    block = bat.sandbox_build_evidence(seed.commit_count, bat.count_sandbox_commits(repo))
    assert block["sandbox_commit_count_at_write"] == "4"
    assert block["sandbox_commits_added"] == "3"


def test_an_unreadable_history_yields_an_error_and_no_number(tmp_path):
    """Never a fabricated count, and never a silent fallback to the seed."""
    block = bat.sandbox_build_evidence(1, bat.count_sandbox_commits(tmp_path / "nowhere"))
    assert "sandbox_commit_count_error" in block
    assert "sandbox_commit_count_at_write" not in block
    assert "sandbox_commits_added" not in block


def test_the_delta_is_omitted_when_its_operands_are_not_both_published(tmp_path):
    """Arithmetic verified by nothing outside itself is the failure class this ticket
    belongs to (#1231, #1324, #1341). A delta whose baseline was never recorded is
    exactly that, so it is not emitted."""
    repo = _make_sandbox(tmp_path, "battery-nodelta", ["init battery sandbox"])
    block = bat.sandbox_build_evidence(None, bat.count_sandbox_commits(repo))
    assert block["sandbox_commit_count_at_write"] == "1"
    assert "sandbox_commits_added" not in block


def test_the_seed_count_is_named_as_the_seed():
    """The retired name must not come back under new semantics: an archive where
    ``sandbox_commit_count`` means "seed" before some date and "delivered" after it is
    unreadable, which is the drift this whole ticket is about."""
    block = bat.sandbox_evidence(bat.SandboxFreshness(bat.SANDBOX_FRESH, commit_count=1),
                                 opted_out=False)
    assert block["sandbox_seed_commit_count"] == "1"
    assert "sandbox_commit_count" not in block


# ===========================================================================
# THE SEAM — the real run_battery loop, the real writer, the real disk artifact
# ===========================================================================


async def test_the_written_card_records_the_build_not_the_seed(tmp_path, monkeypatch):
    """The headline regression lock. A sandbox seeded at 1 commit, a dispatch that
    builds 3 more, and the card that lands on disk must say so — the exact record both
    real nights got wrong."""
    monkeypatch.setattr(bat, "probe_live_dispatch",
                        lambda *_a, **_k: ld.LiveDispatch(ld.ABSENT))
    cfg = _live_cfg(tmp_path)
    _make_sandbox(cfg.projects_dir, "battery-seedtest", ["init battery sandbox"])
    harness = _BuildingHarness(cfg, build_commits=3)

    await bat.run_battery(harness, [_card("battery-seedtest")], out_dir=tmp_path / "out",
                          dry_run=False, log=lambda *_: None)

    written = sc.read_scorecard(tmp_path / "out" / "B1.scorecard.json")
    assert written.evidence["sandbox_seed_commit_count"] == "1"
    assert written.evidence["sandbox_commit_count_at_write"] == "4"
    assert written.evidence["sandbox_commits_added"] == "3"
    # The ambiguous name is gone from the record entirely, so no reader can take a
    # post-#1341 card's count for a pre-#1341 one.
    assert "sandbox_commit_count" not in written.evidence


async def test_the_cited_summary_is_captured_before_the_run_can_rewrite_it(
        tmp_path, monkeypatch):
    """End to end: the card that lands on disk carries what SUMMARY.txt SAID, and the
    run rewriting it afterwards cannot change the record."""
    monkeypatch.setattr(bat, "probe_live_dispatch",
                        lambda *_a, **_k: ld.LiveDispatch(ld.ABSENT))
    cfg = _live_cfg(tmp_path)
    _make_sandbox(cfg.projects_dir, "battery-captest", ["init battery sandbox"])
    harness = _BuildingHarness(cfg, summary_text="RESULT: nothing yet\nstill planning\n")

    await bat.run_battery(harness, [_card("battery-captest")], out_dir=tmp_path / "out",
                          dry_run=False, log=lambda *_: None)

    written = sc.read_scorecard(tmp_path / "out" / "B1.scorecard.json")
    assert "nothing yet" in written.evidence["summary_excerpt"]
    banked_hash = written.evidence["summary_sha256"]

    summary_file = Path(cfg.runs_dir) / "20260808-160538-bd" / "SUMMARY.txt"
    summary_file.write_text("RESULT: MERGED\n", encoding="utf-8")
    on_disk = json.loads((tmp_path / "out" / "B1.scorecard.json").read_text(encoding="utf-8"))
    assert "nothing yet" in on_disk["evidence"]["summary_excerpt"]
    assert banked_hash != sha256(summary_file.read_bytes()).hexdigest()


async def test_a_stalled_verdict_over_a_live_driver_says_so_on_the_card(
        tmp_path, monkeypatch):
    """The 2026-08-08 record, rewritten honestly. The harness gives up; the driver is
    still running; the card must not claim the run failed without qualification."""
    monkeypatch.setattr(bat, "probe_live_dispatch", lambda *_a, **_k: ld.LiveDispatch(
        ld.LIVE, detail="pid 5364 (pwsh.exe) is run-fleet.ps1 (outer dispatch driver)",
        pids=(5364, 2416)))
    cfg = _live_cfg(tmp_path)
    _make_sandbox(cfg.projects_dir, "battery-livetest", ["init battery sandbox"])
    loglines: list[str] = []

    await bat.run_battery(_BuildingHarness(cfg), [_card("battery-livetest")],
                          out_dir=tmp_path / "out", dry_run=False, log=loglines.append)

    written = sc.read_scorecard(tmp_path / "out" / "B1.scorecard.json")
    assert written.verdict == sc.VERDICT_STALLED          # the verdict is unchanged...
    assert written.evidence[bat.DRIVER_LIVE_KEY] == ld.LIVE
    assert written.evidence["driver_live_pids"] == "5364,2416"
    assert "5364" in written.evidence["driver_live_detail"]
    # ...but it no longer stands as an unqualified claim about the run, and the loud
    # half is FIRST so the 500-char note clip can never eat it.
    assert written.notes.startswith("OBSERVATION STOPPED OVER A LIVE INTERVAL")
    assert "#1341" in written.notes
    assert any("WHILE A DISPATCH DRIVER IS LIVE" in ln for ln in loglines)


async def test_toggle_the_same_card_with_no_live_driver_carries_no_marker(
        tmp_path, monkeypatch):
    """The toggle-off half (principle 12). SAME card, SAME STALLED verdict, detector
    reporting an idle box: the marker must be absent — so the assertion above is
    proving the detector FIRED, not that the string is always there."""
    monkeypatch.setattr(bat, "probe_live_dispatch",
                        lambda *_a, **_k: ld.LiveDispatch(ld.ABSENT))
    cfg = _live_cfg(tmp_path)
    _make_sandbox(cfg.projects_dir, "battery-livetest", ["init battery sandbox"])
    loglines: list[str] = []

    await bat.run_battery(_BuildingHarness(cfg), [_card("battery-livetest")],
                          out_dir=tmp_path / "out", dry_run=False, log=loglines.append)

    written = sc.read_scorecard(tmp_path / "out" / "B1.scorecard.json")
    assert written.verdict == sc.VERDICT_STALLED
    assert written.evidence[bat.DRIVER_LIVE_KEY] == ld.ABSENT
    assert "OBSERVATION STOPPED" not in written.notes
    assert written.notes.startswith("run completed")     # the emitter's own note, intact
    assert not any("WHILE A DISPATCH DRIVER IS LIVE" in ln for ln in loglines)


async def test_an_unknown_liveness_is_recorded_but_does_not_rewrite_the_note(
        tmp_path, monkeypatch):
    """UNKNOWN rides the evidence, where a reader checking a verdict's standing looks.
    It does NOT amend the note: on a non-elevated box the blind spot is the common
    case, and a marker that fires on every card is a marker nobody reads."""
    monkeypatch.setattr(bat, "probe_live_dispatch", lambda *_a, **_k: ld.LiveDispatch(
        ld.UNKNOWN, detail="2 driver-capable process(es) hide their command line"))
    cfg = _live_cfg(tmp_path)
    _make_sandbox(cfg.projects_dir, "battery-unknowntest", ["init battery sandbox"])
    loglines: list[str] = []

    await bat.run_battery(_BuildingHarness(cfg), [_card("battery-unknowntest")],
                          out_dir=tmp_path / "out", dry_run=False, log=loglines.append)

    written = sc.read_scorecard(tmp_path / "out" / "B1.scorecard.json")
    assert written.evidence[bat.DRIVER_LIVE_KEY] == ld.UNKNOWN
    assert "OBSERVATION STOPPED" not in written.notes
    assert any("liveness UNKNOWN at write time" in ln for ln in loglines)


async def test_a_refused_card_makes_no_liveness_claim_at_all(tmp_path, monkeypatch):
    """A card refused by the #1058 gate never started an interval, so a driver running
    on the box at that moment belongs to somebody ELSE's work. Stamping it here would
    be the same over-claim this ticket exists to remove — the key's ABSENCE means 'this
    job was never dispatched'."""
    fired: list[int] = []
    monkeypatch.setattr(bat, "probe_live_dispatch",
                        lambda *_a, **_k: (fired.append(1) or ld.LiveDispatch(ld.LIVE)))
    cfg = _live_cfg(tmp_path)
    _make_sandbox(cfg.projects_dir, "battery-refused",
                  ["init battery sandbox", "agent: prior run work"])
    harness = _BuildingHarness(cfg)

    await bat.run_battery(harness, [_card("battery-refused")], out_dir=tmp_path / "out",
                          dry_run=False, log=lambda *_: None)

    assert harness.dispatched == []          # refused before any spend, as #1058 requires
    assert fired == []                       # ...and the liveness probe was never asked
    written = sc.read_scorecard(tmp_path / "out" / "B1.scorecard.json")
    assert bat.DRIVER_LIVE_KEY not in written.evidence
    # The sandbox record is still complete: nothing was built, and the card says so.
    assert written.evidence["sandbox_seed_commit_count"] == "2"
    assert written.evidence["sandbox_commit_count_at_write"] == "2"
    assert written.evidence["sandbox_commits_added"] == "0"


async def test_a_dry_run_makes_no_claim_about_a_box_it_never_touched(tmp_path, monkeypatch):
    """--dry-run drives a fake AO over a fixture projects dir. A sandbox count or a
    process sweep there would describe the developer's box, not a run."""
    probed: list[int] = []
    monkeypatch.setattr(bat, "probe_live_dispatch",
                        lambda *_a, **_k: (probed.append(1) or ld.LiveDispatch(ld.LIVE)))
    harness = _BuildingHarness(_live_cfg(tmp_path))
    Path(harness.config.projects_dir).mkdir(parents=True, exist_ok=True)
    _make_sandbox(harness.config.projects_dir, "battery-dry", ["init battery sandbox"])

    await bat.run_battery(harness, [_card("battery-dry")], out_dir=tmp_path / "out",
                          dry_run=True, log=lambda *_: None)

    written = sc.read_scorecard(tmp_path / "out" / "B1.scorecard.json")
    assert probed == []
    assert bat.DRIVER_LIVE_KEY not in written.evidence
    assert "sandbox_commit_count_at_write" not in written.evidence


async def test_a_write_time_probe_fault_never_costs_the_record(tmp_path, monkeypatch):
    """Recording a fact must not be able to destroy the record the fact belongs to.
    Both write-time reads are made to explode; the card still lands, still validates,
    and still carries everything the run did produce."""
    def _boom(*_a, **_k):
        raise RuntimeError("git vanished mid-night")

    monkeypatch.setattr(bat, "count_sandbox_commits", _boom)
    monkeypatch.setattr(bat, "probe_live_dispatch", _boom)
    cfg = _live_cfg(tmp_path)
    _make_sandbox(cfg.projects_dir, "battery-faulty", ["init battery sandbox"])

    await bat.run_battery(_BuildingHarness(cfg), [_card("battery-faulty")],
                          out_dir=tmp_path / "out", dry_run=False, log=lambda *_: None)

    written = sc.read_scorecard(tmp_path / "out" / "B1.scorecard.json")   # it exists + validates
    assert written.verdict == sc.VERDICT_STALLED
    assert written.evidence["sandbox_seed_commit_count"] == "1"
    assert "sandbox_commit_count_at_write" not in written.evidence   # honestly absent
    # The liveness probe raising is itself an honest UNKNOWN, never a quiet 'absent'.
    assert written.evidence[bat.DRIVER_LIVE_KEY] == ld.UNKNOWN
    # ...and the THIRD fact survived both faults: one instrument failing must not
    # silently erase another instrument's reading.
    assert "summary_sha256" in written.evidence
