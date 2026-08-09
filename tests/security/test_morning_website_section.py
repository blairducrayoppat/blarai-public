"""
#1346 — the morning report NAMES the website, or says out loud why it cannot.
=============================================================================

#1343 ended a website battery run by writing a double-click launcher into
``state/battery``. It landed BESIDE ``MORNING-REPORT.md``, not IN it — and the operator
reads the report and nothing else, so the launcher still had to be noticed. These tests
lock the half that closes it, and the locks are almost entirely about HONESTY rather than
about content:

1. **A night with no website card renders NOTHING** — no heading, not one byte. An empty
   "Websites built last night" heading is a claim ("we checked, there were none") and the
   truth behind an empty section may be that the step never ran. Silence commits to
   neither; a failed LOOK gets its own loud paragraph instead.
2. **A run whose presentation failed is reported as UNPRESENTED, never omitted.** A site
   that exists and cannot be opened is the fact worth surfacing. Dropping it produces a
   morning that looks exactly like a morning when nothing was built.
3. **No verdict is never rendered as a pass.** On 2026-08-08 this project traced a defect
   (#1342) where an instrument reported a clean pass beside its own field saying the check
   had never run. The reader must not commit the same shape.
4. **The older concern survives.** This script's first job is the #1327 validation
   exercise, whose exit-2 contract promises NOTHING on stdout. A website on disk must not
   be able to break that, and a fault in the website half must not cost the exercise half.

Deterministic and GPU-free: no AO, no model, no dispatch, no network. Every path is under
tmp_path, and the record + launcher under test are produced by the REAL writer
(``present_website_builds`` / ``build_record`` / ``render_launcher``) rather than by a
hand-rolled fixture — a reader tested against a fixture only proves the fixture.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tools.dispatch_harness import website_presentation as wp
from tools.dispatch_harness.scorecard import Scorecard

REPO_ROOT = Path(__file__).resolve().parents[2]
_SPEC_DIR = REPO_ROOT / "evals" / "battery"
_CONFIG = REPO_ROOT / "services" / "assistant_orchestrator" / "config" / "default.toml"

#: A night stamp in the launcher's own format. Two of them, because "the newest one" is
#: how the reader decides which night just ran.
_NIGHT = "night-20260808-230003"
_OLDER_NIGHT = "night-20260807-230001"
_RUN_ID = "20260808-230417-bd"

#: The real skip #1342 exposed: an explicit operator requirement, dropped by the
#: already-satisfied pre-check and graded GREEN by four gates.
_REAL_SKIP_ID = "create-piece-detail-page"


def _load(script_name: str):
    """Load a ``scripts/`` entry point by path — it is not an importable package."""
    path = REPO_ROOT / "scripts" / script_name
    name = script_name.removesuffix(".py")
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


renderer = _load("render_morning_validation.py")


# ==========================================================================
# Fixtures — the real night layout, built by the real writer
# ==========================================================================


class _Tree:
    """The directories ``run-battery-night.ps1`` actually creates, under tmp_path.

    ``out_dir`` is ``<night>\\scorecards`` because that is what the launcher passes as
    ``--out``; ``battery`` is where MORNING-REPORT.md and the visible launcher live."""

    def __init__(self, tmp_path: Path, night: str = _NIGHT) -> None:
        self.agentic = tmp_path / "agentic"
        self.runs_dir = self.agentic / "state" / "fleet-runs"
        self.projects_dir = tmp_path / "projects"
        self.battery = self.agentic / "state" / "battery"
        self.night = self.battery / night
        self.out_dir = self.night / "scorecards"
        for path in (self.runs_dir, self.projects_dir, self.out_dir):
            path.mkdir(parents=True, exist_ok=True)

    @property
    def visible_launcher(self) -> Path:
        return self.battery / wp.launcher_name_for("B9")

    @property
    def record(self) -> Path:
        return self.out_dir / wp.REVIEW_SUBDIR / f"B9{wp.RECORD_SUFFIX}"


def _card() -> dict:
    """The REAL B9 card. A hand-rolled one would test the fixture, not the spec."""
    return json.loads((_SPEC_DIR / "B9.json").read_text(encoding="utf-8"))


def _driver_scorecard(tree: _Tree, *, tasks: bool = True) -> None:
    """The dispatch's own record, which is where the claims (and the SKIPPED list) come
    from. ``tasks=False`` is the dry-run fake's real shape: a valid record with no task
    list at all, which must never render as "nothing was skipped"."""
    run_dir = tree.runs_dir / _RUN_ID
    run_dir.mkdir(parents=True, exist_ok=True)
    driver: dict = {
        "schema": "battery-scorecard/v1", "job_id": "(driver)", "verdict": "GREEN",
        "attribution": "", "wall_clock_s": 0.0, "samples_consumed": 1, "packs_consumed": 0,
        "interventions": 0, "goal": "a proper little website for my pottery studio",
        "evidence": {"oracle_status": "passed"}, "versions": {"emitter": "test"},
    }
    if tasks:
        driver["tasks"] = [
            {"id": "create-home-page", "status": "merged", "detail": "RESULT: MERGED"},
            {"id": "create-piece-list-page", "status": "merged", "detail": "RESULT: MERGED"},
            {"id": _REAL_SKIP_ID, "status": "skipped",
             "detail": "skipped: already satisfied before wave 2"},
        ]
    (run_dir / "scorecard.json").write_text(json.dumps(driver, indent=2), encoding="utf-8")


def _present(tree: _Tree, *, verdict: str = "GREEN", tasks: bool = True) -> list[Path]:
    """Run the REAL presentation step over the REAL card, into the real night layout."""
    _driver_scorecard(tree, tasks=tasks)
    card = _card()
    sc = Scorecard(job_id="B9", verdict=verdict,
                   attribution="" if verdict == "GREEN" else "BUILD", run_id=_RUN_ID)
    (tree.projects_dir / str(card["repo"])).mkdir(parents=True, exist_ok=True)
    return wp.present_website_builds(
        [card], {"B9": sc}, out_dir=tree.out_dir, runs_dir=tree.runs_dir,
        projects_dir=tree.projects_dir, dry_run=False, log=lambda _m: None,
    )


def _section(tree: _Tree) -> str:
    """The websites section exactly as the script produces it for this tree."""
    return renderer.website_section(tree.battery, _CONFIG)


def _flat(text: str) -> str:
    """*text* with its line breaks collapsed.

    The section wraps its prose to a readable column, so a phrase the report must contain
    is routinely split across two lines. Asserting against the flattened form tests what he
    READS rather than where the wrapper happened to break; paths get their own unwrapped
    line and are asserted against the raw output."""
    return " ".join(text.split())


# ==========================================================================
# (1) A night WITH a website card: named, graded, and openable
# ==========================================================================


def test_a_night_with_a_website_card_names_it_with_its_launcher(tmp_path):
    """The headline lock. The one document he reads must name the site, say whether the
    run graded it clean, and give him something to double-click — in words that need no
    technical knowledge."""
    tree = _Tree(tmp_path)
    _present(tree)
    assert tree.record.is_file() and tree.visible_launcher.is_file()

    out = _section(tree)
    flat = _flat(out)

    assert "## The website it built for you" in out
    assert "**B9**" in out, "the card must be named"
    assert "it graded this one clean" in flat, "the verdict must be in plain words"
    assert "double-click" in flat
    assert str(tree.visible_launcher) in out, "he must be given the file, not a directory"
    # The launcher he is sent to is THIS run's, not a well-known name that drifts.
    assert _RUN_ID in tree.visible_launcher.read_text(encoding="utf-8")


def test_the_card_is_described_in_his_own_words_not_the_engineering_title(tmp_path):
    """The card's title is shorthand for the people who wrote the exam -- "node-web, 9
    units, MULTI-PAGE: shared layout + routing". His goal is the sentence HE wrote, and it
    is the one the review tool already hands back to him. A description he does not
    recognise is one more thing between him and opening the site."""
    tree = _Tree(tmp_path)
    _present(tree)
    card = _card()

    out = _section(tree)
    flat = _flat(out)

    opening = str(card["goal"]).split(". ")[0] + "."
    assert opening in flat, "his own opening sentence must name the site"
    assert "node-web" not in flat and "MULTI-PAGE" not in flat, (
        "the exam's own shorthand must not reach the one page he reads"
    )
    # His brief runs past 600 characters and the review tool walks him through all of it.
    # Here it only has to identify the site, so the rest is not re-read back at him.
    assert str(card["goal"]) not in flat
    assert len(opening) <= 160
    # Plain language throughout. Backticked spans are exempt -- a path is an address he
    # double-clicks or pastes, not prose he has to read.
    prose = re.sub(r"`[^`]*`", "", flat)
    for jargon in ("GREEN", "scorecard", "stdout", "JSON", "repo ", "commit", "git "):
        assert jargon not in prose, f"developer vocabulary leaked into his report: {jargon!r}"


def test_the_skipped_half_reaches_the_report(tmp_path):
    """#1342's finding came from a task the run dropped silently. A report that names the
    site and hides what it left out hands him the same reassurance the exam gave."""
    tree = _Tree(tmp_path)
    _present(tree)
    flat = _flat(_section(tree))
    assert "**skipped 1**" in flat
    assert "worth more of your attention" in flat, "the skipped one must be flagged"
    assert str(tree.record) in flat, "he must be told where the reasons are written down"


def test_a_run_that_recorded_no_task_list_says_unknown_not_none(tmp_path):
    """A record that parses but lists no tasks knows NOTHING about what was skipped.
    Rendering that as "skipped none" manufactures the reassurance the record withheld."""
    tree = _Tree(tmp_path)
    _present(tree, tasks=False)
    flat = _flat(_section(tree))
    assert "Treat that as unknown, not as none." in flat
    assert "skipped" not in flat.lower(), "no skip count may be claimed over a record with none"
    assert "left none out" not in flat, "'nothing was skipped' is exactly the false comfort"


# ==========================================================================
# (2) A night with NO website card: NOTHING, not an empty heading
# ==========================================================================


def test_a_night_with_no_website_card_adds_nothing_at_all(tmp_path):
    """An empty heading reads as "we checked and there were none". The truth may be that
    the step never ran, and those are different facts — so the section is absent, not
    empty."""
    tree = _Tree(tmp_path)
    (tree.out_dir / "B1.scorecard.json").write_text("{}", encoding="utf-8")  # a real night

    out = _section(tree)

    assert out == "", f"a night with no website card must render nothing, got {out!r}"
    # Named explicitly, because "no heading" is the property, not "short output".
    for heading in ("## The website", "## The websites", "Websites built", "website"):
        assert heading not in out


def test_an_older_nights_record_is_never_reported_as_tonights(tmp_path):
    """The reader takes the NEWEST night and never falls back. A site built last week
    reported as one built last night is a stale result wearing a fresh stamp."""
    older = _Tree(tmp_path, night=_OLDER_NIGHT)
    _present(older)
    tonight = _Tree(tmp_path, night=_NIGHT)          # same battery dir, no website card
    assert tonight.battery == older.battery

    assert _section(tonight) == "", "last night's record must not be reported as tonight's"


# ==========================================================================
# (3) Presentation FAILED: unpresented, never omitted
# ==========================================================================


def test_a_record_whose_presentation_failed_is_reported_as_unpresented(tmp_path):
    """The site exists and there is nothing to open it with. Silently omitting it is the
    exact failure this class of ticket exists to prevent."""
    tree = _Tree(tmp_path)
    _present(tree)
    # Exactly what a failed launcher write leaves behind: the record, and no launcher.
    for launcher in (tree.visible_launcher, tree.record.parent / wp.launcher_name_for("B9")):
        launcher.unlink()

    out = _section(tree)
    flat = _flat(out)

    assert "**B9**" in out, "an unpresentable site must still be NAMED, never dropped"
    assert "nothing was left for you to open it with" in flat
    assert "NOT ready for you to review" in flat
    assert "fault in the machinery, not a verdict on the site" in flat
    assert str(tree.record) in flat, "he must still be told where the run's own account is"
    assert "double-click this file" not in flat, "nothing may be offered that does not exist"


def test_a_leftover_launcher_is_not_offered_as_tonights(tmp_path):
    """The visible launcher sits at a well-known name and is overwritten per run, so one
    from an earlier night survives a night whose own write failed. Offering it would show
    him a different night's site under tonight's heading."""
    tree = _Tree(tmp_path)
    _present(tree)
    beside_record = tree.record.parent / wp.launcher_name_for("B9")
    # A GENUINELY earlier launcher, from the real writer: same card, same well-known name,
    # a different run and a different written-at stamp.
    earlier = wp.build_record(
        _card(), Scorecard(job_id="B9", verdict="GREEN", run_id="20260101-000000-old"), {},
        sandbox=None, out_dir=tree.out_dir, dry_run=False,
        now=datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
    )
    tree.visible_launcher.write_text(
        wp.render_launcher(earlier, review_launcher=None), encoding="utf-8")

    out = _section(tree)

    offered = out.split("- To look at it, double-click this file:\n")[1].splitlines()[0]
    assert offered.strip() == f"`{beside_record}`", (
        "the copy inside tonight's own folder is the only one that cannot be another run's"
    )
    assert "an EARLIER run of the same card" in _flat(out)
    assert str(tree.visible_launcher) in out, (
        "the leftover must be NAMED as the one to ignore -- it is sitting beside the report "
        "under a name that reads like tonight's, so silence about it is the trap"
    )


def test_an_unreadable_record_is_named_rather_than_dropped(tmp_path):
    """A card that ran and cannot be described is a different fact from a card that never
    ran. Both render as nothing unless this one is caught."""
    tree = _Tree(tmp_path)
    _present(tree)
    tree.record.write_text("{ this is not json", encoding="utf-8")

    flat = _flat(_section(tree))

    assert "**B9**" in flat
    assert "the note describing it cannot be read" in flat
    assert "None of that is a judgement about the site itself." in flat
    assert "Review Website.cmd" in flat, "he must still have a way in by hand"


# ==========================================================================
# (4) A verdict the record does not carry is NEVER rendered as one
# ==========================================================================


def test_a_record_with_no_verdict_renders_not_recorded_never_clean(tmp_path):
    """#1342 in miniature: an absent grade reported as a pass. The record is written by a
    fail-soft step over whatever the night did, so no verdict is an ordinary outcome."""
    tree = _Tree(tmp_path)
    _present(tree, verdict="")
    assert json.loads(tree.record.read_text(encoding="utf-8"))["run"]["verdict"] == ""

    flat = _flat(_section(tree))

    assert "not recorded" in flat
    assert "clean" not in flat, "an ungraded run must never read as a clean one"
    assert "Your own eyes are the only reading there is." in flat


@pytest.mark.parametrize("verdict,expected", [
    ("GREEN", "it graded this one clean"),
    ("PARKED-HONEST", "not a pass"),
    ("FALSE-DONE", "not a pass"),
    ("STALLED", "not a pass"),
    ("RECOVERED", "not a pass"),
    ("", "not recorded"),
    ("SOMETHING-NEW", "does not know that word"),
])
def test_only_green_is_ever_called_clean(verdict, expected):
    """The word "clean" means exactly one thing in his report. Every other verdict — and
    every verdict this reader has never heard of — renders as something he cannot mistake
    for a pass."""
    words = wp.verdict_in_plain_words(verdict)
    assert expected in words
    assert ("clean" in words) is (verdict == "GREEN")


def test_the_blame_is_reported_in_plain_words_and_only_with_a_verdict():
    words = wp.verdict_in_plain_words("PARKED-HONEST", "BUILD")
    assert "it blamed the coder itself" in words
    assert "blamed" not in wp.verdict_in_plain_words("GREEN", "")


# ==========================================================================
# (5) The LOOK failing is loud — it is never allowed to look like a quiet night
# ==========================================================================


def test_no_night_folder_at_all_is_loud_not_silent(tmp_path):
    """"There is nowhere to look" and "there was nothing built" are different facts, and
    only one of them is safe to render as an empty space."""
    empty = tmp_path / "battery"
    empty.mkdir()

    out = renderer.website_section(empty, _CONFIG)

    assert "## !! The websites could not be checked" in out
    assert "Read that as unknown" in out
    assert "there are no night folders under" in out


def test_a_fault_in_the_websites_half_never_costs_the_exercise_half(tmp_path, monkeypatch):
    """The websites concern is bolted onto a script that already owed him the #1327
    exercise. A fault here degrades to a loud paragraph, never to an exception or a
    non-zero exit."""
    tree = _Tree(tmp_path)
    _present(tree)

    def _boom(*_a, **_k):
        raise RuntimeError("the state directory went away")

    monkeypatch.setattr(wp, "read_night_websites", _boom)

    out = _section(tree)

    assert "## !! The websites could not be checked" in out
    assert "RuntimeError: the state directory went away" in out


# ==========================================================================
# (6) The #1327 contract, driven through the real entry point
# ==========================================================================


def test_a_malformed_exercise_still_prints_NOTHING_even_with_a_website_on_disk(
    tmp_path, capsys
):
    """#1327's loudest promise: exit 2, and not one byte on stdout. Adding a second
    concern to this script must not be able to smuggle output past it."""
    tree = _Tree(tmp_path)
    _present(tree)
    bad = tmp_path / "exercises"
    bad.mkdir()
    (bad / "broken.json").write_text("{ not json", encoding="utf-8")

    rc = renderer.main(["--exercises", str(bad), "--battery-dir", str(tree.battery)])

    captured = capsys.readouterr()
    assert rc == 2
    assert captured.out == "", "exit 2 promises nothing on stdout, websites included"
    assert "malformed" in captured.err


def test_both_sections_render_together_through_main(tmp_path, capsys):
    """The seam, end to end: the real exercises on disk, the real config, and a real
    night's record — the shape the battery's postlude actually produces."""
    tree = _Tree(tmp_path)
    _present(tree)

    rc = renderer.main(["--battery-dir", str(tree.battery)])

    out = capsys.readouterr().out
    assert rc == 0
    assert "## Your validation exercise" in out, "the #1327 section must survive"
    assert "## The website it built for you" in out
    assert out.index("## Your validation exercise") < out.index("## The website it built"), (
        "the websites render LAST — the exercise's exit-2 contract depends on it"
    )


def test_the_battery_dir_resolves_from_the_launchers_own_environment(tmp_path, monkeypatch):
    """Unnamed, the directory is resolved the way the battery itself resolves it: the
    launcher's exported state root first, because the running night has already stated
    where tonight is kept."""
    tree = _Tree(tmp_path)
    monkeypatch.setenv(renderer.BATTERY_STATE_ROOT_ENV, str(tree.agentic))

    assert renderer.resolve_battery_dir(_CONFIG) == tree.battery


def test_an_unset_environment_falls_back_to_the_writers_own_resolver(monkeypatch):
    """No override -> the same function the presentation step used to place the launcher,
    fed by the same fleet-root resolution every other harness reader uses. The writer and
    the reader agree because they call the same code."""
    monkeypatch.delenv(renderer.BATTERY_STATE_ROOT_ENV, raising=False)
    monkeypatch.setenv("BLARAI_FLEET_AGENTIC_SETUP_DIR", r"C:\some\agentic")

    resolved = renderer.resolve_battery_dir(_CONFIG)

    assert resolved == Path(r"C:\some\agentic") / "state" / "battery"
    assert resolved == wp.resolve_visible_dir(Path(r"C:\some\agentic") / "state" / "fleet-runs")
