"""#1343 — a website battery run must END by leaving the operator something to open.

The coder fleet built a complete multi-page website on two consecutive nights and nobody
opened either one. The review loop existed by 2026-08-08 and worked; what was missing was
the TRIGGER — it had to be remembered. These tests lock the trigger.

Three properties, in order of how much they matter:

1. **The presentation cannot change the run.** A record written for his benefit must never
   be able to cost a night of GPU measurement or move a verdict. This is proved, not
   asserted: every artifact under ``out_dir`` is hashed before the step and after it, in
   the SAME run, and compared byte for byte — with each failure path in the step forced
   in turn.
2. **It fires on the declared product shape, not on card ids.** ``stack == node-web``,
   checked against the REAL spec so a web card added tomorrow cannot quietly miss out.
3. **It carries what was SKIPPED.** His most valuable finding came from a task the run
   dropped silently (#1342, ``create-piece-detail-page``). A record that renders "nothing
   skipped" and "I have no idea what was skipped" identically is the same defect aimed at
   the reader.

Deterministic and GPU-free: no AO, no model, no dispatch, and every path written under
tmp_path (the agentic roots are DERIVED from the harness's runs dir precisely so a test
can never reach his live state directory). In the standing gate. asyncio_mode=auto.
"""

from __future__ import annotations

import json
import subprocess
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest

from tools.dispatch_harness import battery as bat
from tools.dispatch_harness import live_dispatch as ld
from tools.dispatch_harness import website_presentation as wp
from tools.dispatch_harness.scorecard import Scorecard

_SPEC_DIR = Path(__file__).resolve().parents[2] / "evals" / "battery"

#: The real skip that #1342 exposed — an explicit operator requirement, dropped by the
#: already-satisfied pre-check and graded GREEN by four gates.
_REAL_SKIP_ID = "create-piece-detail-page"
_REAL_SKIP_DETAIL = (
    "skipped: already satisfied before wave 2: the job acceptance oracle PASSED on the "
    "current integrated tree (pre-dispatch check — no coder candidate spent; exit 0; "
    "\u2714 Verify all pages are accessible)"
)


# ===========================================================================
# Fixtures — the same shapes the sibling evidence-capture suite drives
# ===========================================================================


def _git(repo, *args):
    cp = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@local", "-c", "user.name=t",
         "-c", "commit.gpgsign=false", *args],
        capture_output=True, text=True,
    )
    assert cp.returncode == 0, f"git {' '.join(args)} failed: {cp.stderr}"


def _make_sandbox(projects_dir, name):
    repo = Path(projects_dir) / name
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "init battery sandbox")
    return repo


def _live_cfg(tmp_path):
    """A fleet config whose runs dir sits under tmp_path — which is what keeps the
    DERIVED agentic root (and therefore the visible launcher) inside the test."""
    from shared.fleet.dispatch import FleetDispatchConfig

    return FleetDispatchConfig(
        scripts_dir=tmp_path / "agentic" / "scripts",
        queue_path=tmp_path / "agentic" / "state" / "q.json",
        runs_dir=tmp_path / "agentic" / "state" / "fleet-runs",
        projects_dir=tmp_path / "projects")


def _card(card_id: str, repo: str | None = None) -> dict:
    """A REAL battery card, optionally retargeted at a fixture sandbox. Real cards on
    purpose: the trigger is the card's own declared stack, so a hand-rolled card would
    test the fixture rather than the spec."""
    card = dict(bat.load_cards(_SPEC_DIR)[card_id])
    if repo is not None:
        card["repo"] = repo
    return card


class _WebHarness:
    """A harness that behaves like a dispatch which built a website: it writes the
    driver ``scorecard.json`` the claims reader quotes back to the operator — including
    the SKIPPED rows, which are the half no other instrument reports."""

    RUN_ID = "20260807-195617-bd"

    def __init__(self, cfg, *, tasks=None, write_driver=True):
        """``tasks=None`` uses the default three-task shape; ``tasks="omit"`` writes a
        VALID driver scorecard with no task list at all (the dry-run fake's real shape);
        ``write_driver=False`` writes no driver record at all."""
        self.config = cfg
        self.overall_timeout_s = 0.0
        self._tasks = tasks
        self._write_driver = write_driver

    async def run_job(self, job):
        from tools.dispatch_harness.report import JobReport

        run_dir = Path(self.config.runs_dir) / self.RUN_ID
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "SUMMARY.txt").write_text(
            "RESULT: MERGED into your project\n", encoding="utf-8")
        if self._write_driver:
            tasks = self._tasks if self._tasks is not None else [
                {"id": "create-home-page", "status": "merged", "detail": "RESULT: MERGED"},
                {"id": "create-piece-list-page", "status": "merged", "detail": "RESULT: MERGED"},
                {"id": _REAL_SKIP_ID, "status": "skipped", "detail": _REAL_SKIP_DETAIL},
            ]
            driver = {
                "schema": "battery-scorecard/v1", "job_id": "(driver)",
                "verdict": "GREEN", "attribution": "", "wall_clock_s": 0.0,
                "samples_consumed": 1, "packs_consumed": 0, "interventions": 0,
                "goal": "a proper little website for my pottery studio",
                "evidence": {"summary": str(run_dir / "SUMMARY.txt"),
                             "oracle_status": "passed"},
                "versions": {"emitter": "test"},
            }
            if self._tasks != "omit":
                driver["tasks"] = tasks
            (run_dir / "scorecard.json").write_text(
                json.dumps(driver, indent=2) + "\n", encoding="utf-8")
        return JobReport(repo=job.repo, goal=job.goal, verdict="COMPLETE",
                         outcome="MERGED", run_id=self.RUN_ID)


def _snapshot(root: Path, *, exclude: str = wp.REVIEW_SUBDIR) -> dict[str, str]:
    """Every file under *root* as ``relpath -> sha256``, skipping the presentation
    subtree. This is the instrument for the byte-identity proof: hashing rather than
    comparing objects means a single changed byte anywhere in the run's output — a
    scorecard, the summary, a sidecar — fails the assertion."""
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if exclude in rel.parts:
            continue
        out[rel.as_posix()] = sha256(path.read_bytes()).hexdigest()
    return out


# ===========================================================================
# (1) THE TRIGGER — the declared stack, never a card id
# ===========================================================================


def test_the_real_spec_splits_exactly_on_node_web():
    """Driven against the REAL cards. B10 was added the day before this shipped and is
    node-web; a hand-rolled fixture would not have noticed it, and a card added tomorrow
    must not miss presentation either. B7 is the trap — ``node``, but a CLI."""
    cards = bat.load_cards(_SPEC_DIR)
    web = {cid for cid, card in cards.items() if wp.is_website_card(card)}
    assert web == {"B3", "B5", "B9", "B10"}
    assert all(cards[cid]["stack"] == "node-web" for cid in web)
    assert cards["B7"]["stack"] == "node" and "B7" not in web


@pytest.mark.parametrize("card,expected", [
    ({"id": "B9", "stack": "node-web"}, True),
    ({"id": "B9", "stack": "  NODE-WEB  "}, True),        # normalised like the goal augmenter
    ({"id": "B9", "stack": "python-cli"}, False),         # the ID says web; the STACK rules
    ({"id": "B1", "stack": "node"}, False),               # node, but not a browser product
    ({"id": "B1"}, False),                                # no stack at all -> opt-IN, so no
    ({"id": "B1", "stack": None}, False),
    ({}, False),
])
def test_the_predicate_reads_the_stack_and_nothing_else(card, expected):
    assert wp.is_website_card(card) is expected


# ===========================================================================
# (2) THE SEAM — the real run_battery loop, the real disk artifacts
# ===========================================================================


async def test_a_node_web_card_leaves_a_record_and_a_launcher(tmp_path, monkeypatch):
    """The headline lock: a website card ends its run with something he can act on
    WITHOUT knowing git — a record naming where the site is, and a double-click launcher
    that opens exactly this run's site."""
    monkeypatch.setattr(bat, "probe_live_dispatch",
                        lambda *_a, **_k: ld.LiveDispatch(ld.ABSENT))
    cfg = _live_cfg(tmp_path)
    _make_sandbox(cfg.projects_dir, "battery-b9-web")
    out = tmp_path / "out"

    await bat.run_battery(_WebHarness(cfg), [_card("B9", "battery-b9-web")],
                          out_dir=out, dry_run=False, log=lambda *_: None)

    record_path = out / wp.REVIEW_SUBDIR / "B9.website-review.json"
    launcher = out / wp.REVIEW_SUBDIR / "Review Website - B9.cmd"
    assert record_path.is_file() and launcher.is_file()

    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["schema"] == wp.WEBSITE_REVIEW_SCHEMA
    assert record["card"] == {**record["card"], "id": "B9", "stack": "node-web",
                              "repo": "battery-b9-web"}
    assert record["run"]["run_id"] == _WebHarness.RUN_ID
    assert record["run"]["verdict"] == "GREEN"
    assert record["site"]["sandbox_now"] == str(cfg.projects_dir / "battery-b9-web")
    assert record["site"]["sandbox_now_exists"] is True
    # The path it MOVES to is a glob, because the stamp belongs to a night that has not
    # run yet — the archive happens as the NEXT night starts, not as this one ends.
    assert record["site"]["archive_glob"].endswith(
        str(Path("night-*") / "repos-archived" / "battery-b9-web"))

    # ...and the visible launcher lands beside MORNING-REPORT.md, derived from the
    # harness's own runs dir (so it lands in the TEST's tree, never his).
    visible = tmp_path / "agentic" / "state" / "battery" / "Review Website - B9.cmd"
    assert visible.is_file()
    assert visible.read_text(encoding="utf-8") == launcher.read_text(encoding="utf-8")


async def test_a_non_web_card_leaves_neither(tmp_path, monkeypatch):
    """B1 is a python-cli. There is nothing to open, so there must be nothing to open —
    no record, no launcher, and no review directory at all."""
    monkeypatch.setattr(bat, "probe_live_dispatch",
                        lambda *_a, **_k: ld.LiveDispatch(ld.ABSENT))
    cfg = _live_cfg(tmp_path)
    _make_sandbox(cfg.projects_dir, "battery-b1-cli")
    out = tmp_path / "out"

    await bat.run_battery(_WebHarness(cfg), [_card("B1", "battery-b1-cli")],
                          out_dir=out, dry_run=False, log=lambda *_: None)

    assert (out / "B1.scorecard.json").is_file()          # the run itself ran
    assert not (out / wp.REVIEW_SUBDIR).exists()
    visible = tmp_path / "agentic" / "state" / "battery"
    assert not visible.exists() or not list(visible.glob("*.cmd"))


async def test_a_card_refused_before_dispatch_is_never_presented(tmp_path, monkeypatch):
    """A card the #1058 freshness gate refused built NOTHING this run, so its sandbox
    holds a previous night's site. Presenting it would hand him a stale build under
    tonight's name — the exact partial-presented-as-whole shape the review loop exists to
    catch."""
    monkeypatch.setattr(bat, "probe_live_dispatch",
                        lambda *_a, **_k: ld.LiveDispatch(ld.ABSENT))
    cfg = _live_cfg(tmp_path)
    repo = _make_sandbox(cfg.projects_dir, "battery-b9-stale")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "agent: last night's work")
    out = tmp_path / "out"

    await bat.run_battery(_WebHarness(cfg), [_card("B9", "battery-b9-stale")],
                          out_dir=out, dry_run=False, log=lambda *_: None)

    from tools.dispatch_harness import scorecard as sc_mod
    assert sc_mod.read_scorecard(out / "B9.scorecard.json").verdict == sc_mod.VERDICT_STALLED
    assert not (out / wp.REVIEW_SUBDIR).exists()


async def test_a_dry_run_records_but_never_reaches_the_live_state_dir(tmp_path, monkeypatch):
    """A rehearsal against a fake coder exercises the whole path — but must not drop a
    shortcut into his state directory claiming a site exists. Same rule the liveness
    stamp follows: a dry run describes the test box, not a night."""
    monkeypatch.setattr(bat, "probe_live_dispatch",
                        lambda *_a, **_k: ld.LiveDispatch(ld.ABSENT))
    cfg = _live_cfg(tmp_path)
    out = tmp_path / "out"

    await bat.run_battery(_WebHarness(cfg), [_card("B9", "battery-b9-dry")],
                          out_dir=out, dry_run=True, log=lambda *_: None)

    record = json.loads(
        (out / wp.REVIEW_SUBDIR / "B9.website-review.json").read_text(encoding="utf-8"))
    assert record["dry_run"] is True
    launcher = (out / wp.REVIEW_SUBDIR / "Review Website - B9.cmd").read_text(encoding="utf-8")
    assert "DRY RUN" in launcher       # it says so where he would read it
    assert not (tmp_path / "agentic" / "state" / "battery").exists()


# ===========================================================================
# (3) THE FAIL-SOFT PROOF — the property that matters most, PROVED
#
# Every failure path in the presentation step, driven over a REAL completed run,
# with the run's whole output hashed before and after. Presentation is the only
# place in this system where failing open is correct (it is not a lock — it makes
# an already-finished result visible), and this is what makes that safe.
# ===========================================================================


def _boom(*_a, **_k):
    raise RuntimeError("injected presentation fault")


def _boom_os(*_a, **_k):
    raise OSError(13, "injected: permission denied")


_FAILURE_MODES = {
    "claims_reader_raises": ("read_run_claims", _boom),
    "record_builder_raises": ("build_record", _boom),
    "launcher_renderer_raises": ("render_launcher", _boom),
    "every_write_fails": ("_write_text", _boom_os),
    "archive_scan_raises": ("find_archived_copies", _boom),
    "path_resolution_raises": ("resolve_visible_dir", _boom),
    "review_tool_resolution_raises": ("resolve_review_launcher", _boom),
}


@pytest.mark.parametrize("mode", sorted(_FAILURE_MODES))
async def test_every_presentation_failure_leaves_the_run_byte_identical(
        tmp_path, monkeypatch, mode):
    """THE proof. Run a real battery to completion, hash every byte it produced, then
    re-run the presentation step with one of its failure paths forced — and require the
    hashes, the summary and the exit code to be unchanged.

    Same run, same files, same process: nothing is normalised away, so this is byte
    identity rather than "identical apart from timestamps". A presentation fault may cost
    the shortcut; it may never cost the measurement."""
    monkeypatch.setattr(bat, "probe_live_dispatch",
                        lambda *_a, **_k: ld.LiveDispatch(ld.ABSENT))
    cfg = _live_cfg(tmp_path)
    _make_sandbox(cfg.projects_dir, "battery-b9-failsoft")
    out = tmp_path / "out"
    cards = [_card("B9", "battery-b9-failsoft")]

    summary = await bat.run_battery(_WebHarness(cfg), cards, out_dir=out,
                                    dry_run=False, log=lambda *_: None)

    before = _snapshot(out)
    before_summary = deepcopy(summary.to_dict())
    before_exit = summary.exit_code()
    assert before, "the run produced no output — the proof would be vacuous"

    name, fault = _FAILURE_MODES[mode]
    monkeypatch.setattr(wp, name, fault)
    logged: list[str] = []

    # Never raises — that is half the property; the caller's guard is belt, not braces.
    wp.present_website_builds(
        cards, {sc.job_id: sc for sc in summary.scorecards},
        out_dir=out, runs_dir=cfg.runs_dir, projects_dir=cfg.projects_dir,
        dry_run=False, log=logged.append,
    )

    assert _snapshot(out) == before                     # every measured byte, unchanged
    assert summary.to_dict() == before_summary          # no field of the run's outcome
    assert summary.exit_code() == before_exit           # and no exit code
    # FAIL-SOFT, NEVER FAIL-QUIET: a swallowed fault that says nothing is how a broken
    # instrument survives to the next night.
    assert any("fail-soft" in line for line in logged), logged


async def test_a_step_that_wrote_no_launcher_never_claims_it_did(tmp_path, monkeypatch):
    """The fail-soft path's own honesty. When every write fails there is nothing to
    double-click, and a closing line naming a launcher that does not exist would be the
    same comfortable half-truth this ticket exists to remove."""
    monkeypatch.setattr(bat, "probe_live_dispatch",
                        lambda *_a, **_k: ld.LiveDispatch(ld.ABSENT))
    monkeypatch.setattr(wp, "_write_text", _boom_os)
    cfg = _live_cfg(tmp_path)
    _make_sandbox(cfg.projects_dir, "battery-b9-nowrite")
    logged: list[str] = []

    await bat.run_battery(_WebHarness(cfg), [_card("B9", "battery-b9-nowrite")],
                          out_dir=tmp_path / "out", dry_run=False, log=logged.append)

    assert not any("double-clicking" in line for line in logged), logged
    assert any("NO review launcher could be written" in line for line in logged), logged


@pytest.mark.parametrize("mode", sorted(_FAILURE_MODES))
async def test_the_run_still_completes_end_to_end_under_every_failure(
        tmp_path, monkeypatch, mode):
    """The reachability half: the fault fires inside the REAL runner, not a direct call.
    The night must still bank its scorecards, write its summary, and return the same
    verdict and exit code it would have returned with no presentation at all."""
    monkeypatch.setattr(bat, "probe_live_dispatch",
                        lambda *_a, **_k: ld.LiveDispatch(ld.ABSENT))
    name, fault = _FAILURE_MODES[mode]
    monkeypatch.setattr(wp, name, fault)
    cfg = _live_cfg(tmp_path)
    _make_sandbox(cfg.projects_dir, "battery-b9-e2e")
    out = tmp_path / "out"

    summary = await bat.run_battery(_WebHarness(cfg), [_card("B9", "battery-b9-e2e")],
                                    out_dir=out, dry_run=False, log=lambda *_: None)

    from tools.dispatch_harness import scorecard as sc_mod
    assert sc_mod.read_scorecard(out / "B9.scorecard.json").verdict == sc_mod.VERDICT_GREEN
    assert json.loads((out / "battery-summary.json").read_text(encoding="utf-8"))
    assert summary.exit_code() == 0


async def test_a_presentation_that_raises_outright_never_escapes_the_runner(
        tmp_path, monkeypatch):
    """The belt. If the whole step raises — a defect this module does not anticipate —
    the runner's own guard must still return a completed summary."""
    monkeypatch.setattr(bat, "probe_live_dispatch",
                        lambda *_a, **_k: ld.LiveDispatch(ld.ABSENT))
    monkeypatch.setattr(bat, "present_website_builds", _boom)
    cfg = _live_cfg(tmp_path)
    _make_sandbox(cfg.projects_dir, "battery-b9-belt")
    out = tmp_path / "out"
    logged: list[str] = []

    summary = await bat.run_battery(_WebHarness(cfg), [_card("B9", "battery-b9-belt")],
                                    out_dir=out, dry_run=False, log=logged.append)

    assert summary.exit_code() == 0
    assert (out / "battery-summary.json").is_file()
    assert any("website presentation failed (fail-soft" in line for line in logged), logged


def test_the_step_writes_nothing_outside_its_own_subdirectory(tmp_path):
    """Containment, stated as a test rather than as a convention. The only paths this
    step may create are ``out_dir/website-review/`` and the visible launcher."""
    out = tmp_path / "out"
    out.mkdir()
    (out / "B9.scorecard.json").write_text("{}", encoding="utf-8")
    before = _snapshot(out)
    runs_dir = tmp_path / "agentic" / "state" / "fleet-runs"

    written = wp.present_website_builds(
        [_card("B9", "battery-b9-contain")],
        {"B9": Scorecard(job_id="B9", verdict="GREEN", run_id="r1")},
        out_dir=out, runs_dir=runs_dir, projects_dir=tmp_path / "projects",
        dry_run=False, log=lambda *_: None,
    )

    assert _snapshot(out) == before
    allowed = {out / wp.REVIEW_SUBDIR, tmp_path / "agentic" / "state" / "battery"}
    assert written and all(p.parent in allowed for p in written)


# ===========================================================================
# (4) THE SKIPPED HALF — the finding that made his eyes worth more than the gates
# ===========================================================================


async def test_the_record_and_the_launcher_both_carry_what_was_skipped(
        tmp_path, monkeypatch):
    """#1342 in a test. The run graded itself GREEN while dropping a page he had asked
    for in his own words; the reason was sitting in the run record the whole time. Both
    artifacts must carry it, with the REASON, not just a count."""
    monkeypatch.setattr(bat, "probe_live_dispatch",
                        lambda *_a, **_k: ld.LiveDispatch(ld.ABSENT))
    cfg = _live_cfg(tmp_path)
    _make_sandbox(cfg.projects_dir, "battery-b9-skips")
    out = tmp_path / "out"

    await bat.run_battery(_WebHarness(cfg), [_card("B9", "battery-b9-skips")],
                          out_dir=out, dry_run=False, log=lambda *_: None)

    claims = json.loads(
        (out / wp.REVIEW_SUBDIR / "B9.website-review.json").read_text(encoding="utf-8")
    )["claims"]
    assert claims["found"] is True and claims["planned"] == 3
    assert claims["merged"] == ["create-home-page", "create-piece-list-page"]
    assert [row["id"] for row in claims["skipped"]] == [_REAL_SKIP_ID]
    assert "already satisfied" in claims["skipped"][0]["detail"]

    launcher = (out / wp.REVIEW_SUBDIR / "Review Website - B9.cmd").read_text(encoding="utf-8")
    assert "2 merged, 1 SKIPPED" in launcher
    assert _REAL_SKIP_ID in launcher and "already satisfied" in launcher


async def test_a_run_with_no_record_reads_as_unknown_never_as_nothing_skipped(
        tmp_path, monkeypatch):
    """The same lesson pointed at the reader. "The run skipped nothing" and "I cannot
    tell you what the run skipped" are different facts; rendering them identically is how
    a partial result acquires the authority of a whole one."""
    monkeypatch.setattr(bat, "probe_live_dispatch",
                        lambda *_a, **_k: ld.LiveDispatch(ld.ABSENT))
    cfg = _live_cfg(tmp_path)
    _make_sandbox(cfg.projects_dir, "battery-b9-norec")
    out = tmp_path / "out"

    await bat.run_battery(_WebHarness(cfg, write_driver=False),
                          [_card("B9", "battery-b9-norec")],
                          out_dir=out, dry_run=False, log=lambda *_: None)

    claims = json.loads(
        (out / wp.REVIEW_SUBDIR / "B9.website-review.json").read_text(encoding="utf-8")
    )["claims"]
    assert claims["found"] is False and claims["tasks_recorded"] is False
    assert claims["skipped"] == [] and claims["why_not_found"]
    launcher = (out / wp.REVIEW_SUBDIR / "Review Website - B9.cmd").read_text(encoding="utf-8")
    assert "CANNOT" in launcher and "unknown, not none" in launcher
    assert "SKIPPED" not in launcher   # never a clean zero it did not observe


async def test_a_record_with_no_task_list_is_also_unknown_not_a_clean_zero(
        tmp_path, monkeypatch):
    """Found LIVE, on the first real ``--dry-run`` of this feature. The dry-run fake
    emits a driver scorecard with no ``tasks`` key at all — the record parses, so the
    first cut set "found" and printed "0 merged, 0 SKIPPED, 0 planned" over a run that
    had never reported a single task. There are two ways to know nothing, and only one of
    them is "nothing happened"."""
    monkeypatch.setattr(bat, "probe_live_dispatch",
                        lambda *_a, **_k: ld.LiveDispatch(ld.ABSENT))
    cfg = _live_cfg(tmp_path)
    _make_sandbox(cfg.projects_dir, "battery-b9-notasks")
    out = tmp_path / "out"

    # tasks=None -> the harness writes a VALID driver scorecard carrying no task list.
    await bat.run_battery(_WebHarness(cfg, tasks="omit"),
                          [_card("B9", "battery-b9-notasks")],
                          out_dir=out, dry_run=False, log=lambda *_: None)

    claims = json.loads(
        (out / wp.REVIEW_SUBDIR / "B9.website-review.json").read_text(encoding="utf-8")
    )["claims"]
    assert claims["found"] is True          # the record WAS read...
    assert claims["tasks_recorded"] is False  # ...and it said nothing about tasks
    assert claims["why_no_tasks"]
    launcher = (out / wp.REVIEW_SUBDIR / "Review Website - B9.cmd").read_text(encoding="utf-8")
    assert "CANNOT" in launcher and "SKIPPED" not in launcher


@pytest.mark.parametrize("payload,why", [
    (None, "no runs dir"),
    ("", "no run id"),
    ("not json at all", "unreadable"),
    ('["a list, not an object"]', "wrong shape"),
])
def test_the_claims_reader_never_raises_and_never_invents(tmp_path, payload, why):
    runs_dir = tmp_path / "runs"
    if payload not in (None, ""):
        (runs_dir / "r1").mkdir(parents=True)
        (runs_dir / "r1" / "scorecard.json").write_text(payload, encoding="utf-8")
    claims = wp.read_run_claims(None if payload is None else runs_dir,
                               "" if payload == "" else "r1")
    assert claims["found"] is False, why
    assert claims["planned"] == 0 and claims["skipped"] == []
    assert claims["why_not_found"]


# ===========================================================================
# (5) THE POINTER — a NAME, because the path moves at 23:00
# ===========================================================================


def test_the_launcher_points_by_name_so_it_survives_the_archive_step(tmp_path):
    """The archive runs at the START of the next night: ``run-battery-night.ps1``
    renames ~/projects/<repo> into the NEW night's repos-archived/ as that night begins.
    A launcher holding a path is correct for a few hours and wrong by morning, so it must
    hold the repo NAME and let the review tool resolve it."""
    review_cmd = tmp_path / "agentic" / wp.REVIEW_LAUNCHER_NAME
    record = wp.build_record(
        _card("B9", "battery-b9-name"), Scorecard(job_id="B9", verdict="GREEN", run_id="r1"),
        wp.read_run_claims(None, ""), sandbox=tmp_path / "projects" / "battery-b9-name",
        out_dir=tmp_path / "out", dry_run=False)
    text = wp.render_launcher(record, review_launcher=review_cmd)

    call = [line for line in text.splitlines() if line.startswith("call ")]
    assert call == [f'call "{review_cmd}" -Name "battery-b9-name"']
    assert "projects" not in call[0]           # not a path into the sandbox
    assert wp.REVIEW_LAUNCHER_NAME in call[0]  # the ONE review tool, not a second one


def test_an_archived_build_is_still_found_after_the_move(tmp_path):
    """The observed half of the record. Once a night has renamed the sandbox away, the
    copies that exist are under night dirs — newest first, so a reader takes the latest."""
    runs_dir = tmp_path / "agentic" / "state" / "fleet-runs"
    battery = tmp_path / "agentic" / "state" / "battery"
    for night in ("night-20260807-230003", "night-20260808-160336"):
        (battery / night / "repos-archived" / "battery-b9-moved").mkdir(parents=True)
    found = wp.find_archived_copies(runs_dir, "battery-b9-moved")
    assert [p.parent.parent.name for p in found] == [
        "night-20260808-160336", "night-20260807-230003"]
    assert wp.find_archived_copies(runs_dir, "battery-b9-never-built") == []


def test_a_missing_review_tool_leaves_a_launcher_that_says_so(tmp_path):
    """If the tooling is gone, the honest artifact is a shortcut that NAMES the problem —
    not a missing file, which reads identically to "no website was built"."""
    record = wp.build_record(
        _card("B9", "battery-b9-notool"), None, wp.read_run_claims(None, ""),
        sandbox=None, out_dir=tmp_path, dry_run=False)
    text = wp.render_launcher(record, review_launcher=None)
    assert "could not find the review tool" in text
    assert "call " not in text and text.rstrip().endswith("pause")


def test_the_launcher_checks_for_the_tool_at_double_click_time(tmp_path):
    """Write time is 03:00 and double-click time is 09:00. A tool that was missing when
    the night ended may have been repaired by morning, so the existence test belongs in
    the .cmd, not in the decision that wrote it."""
    text = wp.render_launcher(
        wp.build_record(_card("B9", "battery-b9-late"), None, wp.read_run_claims(None, ""),
                        sandbox=None, out_dir=tmp_path, dry_run=False),
        review_launcher=tmp_path / "agentic" / wp.REVIEW_LAUNCHER_NAME)
    assert 'if not exist "' in text and ":missing" in text


# ===========================================================================
# (6) THE LAUNCHER IS A BATCH FILE, AND HE DOUBLE-CLICKS IT
# ===========================================================================


def test_the_launcher_is_ascii_and_batch_safe_against_hostile_card_text():
    """cmd.exe reads a .cmd in the console's OEM codepage, not UTF-8, so a check mark out
    of a node oracle renders as mojibake in the one window he looks at. And an unescaped
    ``&`` in a title produces a syntax error at exactly the moment he double-clicks."""
    card = {
        "id": "B9", "stack": "node-web", "repo": "battery-b9-nasty",
        "title": "Tea & Pots 100% <off> | \u2714 done \u2014 now",
        "goal": "line one\nline two & echo PWNED\nline three",
    }
    record = wp.build_record(card, None, wp.read_run_claims(None, ""),
                             sandbox=None, out_dir=Path("out"), dry_run=False)
    text = wp.render_launcher(record, review_launcher=Path("C:/a/Review Website.cmd"))

    assert text.isascii()
    assert "\u2714" not in text and "ok done - now" in text     # folded, not mangled
    for line in text.splitlines():
        if not line.startswith("echo "):
            continue
        body = line[len("echo "):]
        assert "&" not in body.replace("^&", "")      # every separator escaped
        assert "%" not in body.replace("%%", "")      # every percent doubled
        assert "<" not in body.replace("^<", "")
    # The goal's embedded newline cannot become a second command.
    assert "echo PWNED" not in text


def test_cmd_exe_actually_runs_the_generated_launcher(tmp_path):
    """The seam, driven for real. Every other assertion here inspects TEXT; this one hands
    the file to cmd.exe — the program that will actually run it when he double-clicks —
    and checks that it parses, that hostile card text prints instead of executing, and
    that the review tool receives the repo name intact. A launcher that reads correctly
    and fails at the prompt is the mock-passes-but-prod-crashes shape.

    The review tool is a STAND-IN that records its arguments: the real one opens a
    browser and waits for him to type, which is his ceremony, not a test's."""
    stand_in = tmp_path / wp.REVIEW_LAUNCHER_NAME
    stand_in.write_text('@echo off\r\necho ARGS:[%*]> "%~dp0got.txt"\r\n', encoding="ascii")
    card = {"id": "B9", "stack": "node-web", "repo": "battery-b9-pottery-site",
            "title": "Tea & Pots 100% <off> | one — two",
            "goal": "line one\nline two & echo PWNED"}
    record = wp.build_record(card, None, wp.read_run_claims(None, ""),
                             sandbox=None, out_dir=tmp_path, dry_run=False)
    launcher = tmp_path / "Review Website - B9.cmd"
    launcher.write_text(wp.render_launcher(record, review_launcher=stand_in),
                        encoding="utf-8")

    cp = subprocess.run(["cmd", "/c", str(launcher)], capture_output=True, text=True,
                        timeout=60, stdin=subprocess.DEVNULL)

    assert cp.returncode == 0, cp.stderr
    assert (tmp_path / "got.txt").read_text().strip() == \
        'ARGS:[-Name "battery-b9-pottery-site"]'
    assert "Tea & Pots 100% <off> | one - two" in cp.stdout   # printed, not parsed
    assert "PWNED" not in cp.stdout                            # and never executed


def test_the_launcher_names_the_run_it_was_written_for(tmp_path):
    """A well-known launcher goes stale the moment a later night runs without this card,
    and ``-Name`` resolves to the NEWEST build. Naming the run and the moment is what
    stops a stale shortcut presenting a different night's site under this one's name."""
    record = wp.build_record(
        _card("B9", "battery-b9-stamp"),
        Scorecard(job_id="B9", verdict="PARKED-HONEST", attribution="VERIFY",
                  run_id="20260807-195617-bd"),
        wp.read_run_claims(None, ""), sandbox=None, out_dir=tmp_path, dry_run=False)
    text = wp.render_launcher(record, review_launcher=tmp_path / wp.REVIEW_LAUNCHER_NAME)
    assert "20260807-195617-bd" in text
    assert record["written_local_readable"] in text
    assert "PARKED-HONEST [VERIFY]" in text            # the verdict, not a summary of it
    assert "If a later run has rebuilt it" in text
