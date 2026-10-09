"""Locks on `tools/probes/harvest_run_evidence.py`.

The property under lock is NOT "the tool reads JSON". It is the one thing that makes
the tool safe to promote a Definition-of-Done row against:

    **A missing artifact must never render as a measured zero.**

`docs/design/CODER_DEFINITION_OF_DONE.md` capability 7 defines the defect this guards:
*"every grader distinguishes 'did not run' from 'ran and found nothing'"*. Capability 11
then makes it load-bearing, because a row may only be promoted on an observable that was
actually executed. A harvest tool that silently reports 0 for an artifact that does not
exist would manufacture exactly the evidence a promotion needs.

That failure has real precedent in this project: `oracle-qa.json` once reported
`findings_total: 0` from a check that never ran, and a downstream gate read that pass and
deleted two tasks from the plan (#1342).

Each test below states which way it fails if the property is broken, so a future reader
can tell a real regression from a test that merely stopped reaching the code.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_TOOL = Path(__file__).resolve().parents[2] / "tools" / "probes" / "harvest_run_evidence.py"


def _load_module():
    """Import the probe by path -- `tools/` is not a package on the standard path."""
    spec = importlib.util.spec_from_file_location("harvest_run_evidence", _TOOL)
    assert spec is not None and spec.loader is not None, f"cannot load {_TOOL}"
    module = importlib.util.module_from_spec(spec)
    sys.modules["harvest_run_evidence"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def harvester():
    assert _TOOL.is_file(), (
        f"{_TOOL} is missing. If the probe was moved or renamed, move this lock with it "
        "rather than deleting it -- the honesty property is the point, not the path."
    )
    return _load_module()


@pytest.fixture()
def empty_run(tmp_path: Path) -> Path:
    """A run directory containing NOTHING. Every field must read ABSENT."""
    run_dir = tmp_path / "fleet-runs" / "20260815-000000-bd"
    run_dir.mkdir(parents=True)
    return run_dir


@pytest.fixture()
def populated_run(tmp_path: Path) -> Path:
    """A run directory with real-shaped artifacts, nesting verified against disk."""
    run_dir = tmp_path / "fleet-runs" / "20260815-111111-bd"
    run_dir.mkdir(parents=True)
    (run_dir / "oracle-qa.json").write_text(
        json.dumps(
            {
                "verdict": "seed",
                "f2p_baseline": "all-fail",
                "collectability": "confirmed",
                "findings_conclusive": True,
                "findings_total": 0,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "scorecard.json").write_text(
        json.dumps(
            {
                "verdict": "GREEN",
                "job_acceptance": {"status": "passed"},
                "attribution": "BUILD",
                "not_measured": [],
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "link-lint.json").write_text(
        json.dumps(
            {
                "checked": True,
                "references": 39,
                "counts": {"resolved": 35, "broken": 0},
            }
        ),
        encoding="utf-8",
    )
    return run_dir


def _by_label(items, label: str):
    for item in items:
        if item.label == label:
            return item
    raise AssertionError(f"no evidence field labelled {label!r}; labels: {[i.label for i in items]}")


def test_absent_artifacts_never_render_as_zero(harvester, empty_run):
    """THE lock. An empty run must produce ABSENT everywhere, never 0/False/''.

    Fails loudly if someone "tidies" the sentinel into a falsy default -- which reads as
    a cleaner API and silently converts "not measured" into "measured, found nothing".
    """
    result = harvester.harvest(empty_run, empty_run.parent.parent)
    assert result.items, "harvest returned no fields at all -- the probe is not reaching the run"

    for item in result.items:
        # `browser smoke captured` is a genuine file-existence question: False there
        # means "no screenshot", which IS the measurement, not a missing artifact.
        if item.label == "browser smoke captured":
            continue
        assert item.value == harvester.ABSENT, (
            f"{item.label!r} rendered {item.value!r} for a run directory containing no "
            f"artifacts at all. A missing artifact must read ABSENT so it cannot be "
            f"mistaken for a measurement. Source path: {item.source}"
        )
        assert not item.measured, f"{item.label!r} claims to be measured with no artifact present"


def test_present_artifact_with_a_missing_field_also_reads_absent(harvester, empty_run):
    """The likelier real failure: the file is THERE and has stopped carrying the field.

    Added 2026-08-15 because toggle-proving exposed a hole in the test above it. A run
    directory containing nothing short-circuits inside `_read_json` and never reaches the
    key-walking code, so a mutation to `_dig` -- the function that decides what a MISSING
    KEY renders as -- left the empty-run test passing. A writer quietly dropping a field
    from a file it still emits is exactly how a grader starts under-reporting, so this is
    the case worth locking hardest.
    """
    (empty_run / "oracle-qa.json").write_text(
        json.dumps({"verdict": "seed"}), encoding="utf-8"
    )
    result = harvester.harvest(empty_run, empty_run.parent.parent)

    assert _by_label(result.items, "exam quality verdict").value == "seed", (
        "the field that IS present must still be read -- this test must not pass by the "
        "probe failing to open the file at all"
    )
    for label in ("fail-to-pass baseline", "collectability", "findings total"):
        item = _by_label(result.items, label)
        assert item.value == harvester.ABSENT, (
            f"{label!r} rendered {item.value!r} when the artifact exists but the key does "
            "not. A dropped field must read ABSENT, never as a measured value."
        )
        assert not item.measured


def test_unreadable_artifact_is_distinguished_from_absent(harvester, empty_run):
    """A corrupt file is a THIRD state. Collapsing it into ABSENT hides a broken writer."""
    (empty_run / "oracle-qa.json").write_text("{not json at all", encoding="utf-8")
    result = harvester.harvest(empty_run, empty_run.parent.parent)
    verdict = _by_label(result.items, "exam quality verdict")
    assert verdict.value == harvester.UNREADABLE, (
        f"a corrupt oracle-qa.json rendered {verdict.value!r}. 'the file is missing' and "
        "'the file is there and broken' are different faults with different owners."
    )
    assert not verdict.measured


def test_real_values_are_read_from_the_verified_nesting(harvester, populated_run):
    """Guards the nesting corrections made 2026-08-15 against silent reversion.

    Every path below was wrong in the probe's first draft and was fixed only by reading a
    real record. If someone "simplifies" them back to top-level lookups, this fails.
    """
    result = harvester.harvest(populated_run, populated_run.parent.parent)

    assert _by_label(result.items, "job grade").value == "passed", (
        "job grade must come from scorecard.json:job_acceptance.status -- there is no "
        "top-level oracle_status field, and reading one yields a false ABSENT"
    )
    assert _by_label(result.items, "run verdict").value == "GREEN"
    assert _by_label(result.items, "failure attribution").value == "BUILD"
    assert _by_label(result.items, "broken links").value == 0, (
        "broken links must come from link-lint.json:counts.broken, not a top-level key"
    )
    assert _by_label(result.items, "links examined").value == 39
    assert _by_label(result.items, "link check ran").value is True


def test_a_measured_zero_is_still_reported_as_measured(harvester, populated_run):
    """The converse guard. Being cautious about zeros must not suppress REAL zeros.

    `broken links: 0` from a scan that ran is a genuine, valuable result. If a future
    change makes the probe treat every 0 as suspect, this catches the overcorrection.
    """
    result = harvester.harvest(populated_run, populated_run.parent.parent)
    broken = _by_label(result.items, "broken links")
    assert broken.value == 0
    assert broken.measured, (
        "a real 0 from a scan that ran was reported as unmeasured. Distinguishing "
        "'did not run' from 'found nothing' has to work in BOTH directions."
    )


GOAL = "build a pottery site"
GOAL_SHA = "e2f4a5d0e0a6f61e"  # replaced at import time below; see _goal_key


def _goal_key(harvester) -> str:
    import hashlib

    return hashlib.sha256(GOAL.encode("utf-8")).hexdigest()[:16]


def _mk_run(
    root: Path,
    name: str,
    scorecard: dict | None,
    *,
    goal: str | None = GOAL,
    journal: str | None = "repo=b9-pottery-site\n",
    reaped: bool = False,
    filler: int = 0,
) -> Path:
    run = root / "fleet-runs" / name
    run.mkdir(parents=True)
    if goal is not None:
        (run / "acceptance.json").write_text(
            json.dumps({"spec": {"goal": goal}}), encoding="utf-8"
        )
    if journal is not None:
        (run / "journal.log").write_text(journal, encoding="utf-8")
    if reaped:
        (run / "journal.log.reaped-20260811").write_text("reaped\n", encoding="utf-8")
    if scorecard is not None:
        (run / "scorecard.json").write_text(json.dumps(scorecard), encoding="utf-8")
    for i in range(filler):
        (run / f"run-fleet-task-{i}.log").write_text("x", encoding="utf-8")
    return run


def test_a_reaped_run_cannot_vanish_from_the_tally(harvester, tmp_path):
    """THE row-21 lock, and it exists because the first version of this probe failed it.

    The original grouping rule selected runs whose ``journal.log`` named the repo. An
    unclean shutdown makes the reaper RENAME that file to ``journal.log.reaped-<date>``
    -- so a full multi-task attempt that died near the end became invisible to the very
    tally counting instability. The selection was correlated with the outcome, and it
    under-counted the worst bucket 2 against 9 on real data.

    Keying on the GOAL fixes it, because the input cannot correlate with the outcome.
    """
    key = _goal_key(harvester)
    _mk_run(tmp_path, "20260101-000000-bd", {"verdict": "GREEN"}, filler=30)
    _mk_run(tmp_path, "20260102-000000-bd", None, journal=None, reaped=True, filler=30)
    _mk_run(tmp_path, "20260103-000000-bd", {"verdict": "GREEN"}, goal="a different goal")

    dist = harvester.verdict_distribution(tmp_path, key)

    assert dist["matched"] == 2, (
        f"expected exactly the two runs sharing the goal, got {dist['matched']}"
    )
    assert dist["fate_counts"].get("reaped") == 1, (
        "a REAPED run vanished from the tally. Its journal is renamed, so any rule keyed "
        f"on journal.log cannot see it; fates were {dist['fate_counts']}"
    )
    assert dist["verdict_counts"].get("NO-VERDICT:reaped") == 1


def test_died_at_launch_is_not_counted_against_a_grader(harvester, tmp_path):
    """The converse guard: not every verdict-less run is an instrument failure.

    Pooling a run that wrote two files at launch with one that ran to the end and was
    killed would overstate instability just as dropping the reaped run understated it.
    """
    key = _goal_key(harvester)
    _mk_run(tmp_path, "20260101-000000-bd", None, journal=None)  # 1 file: acceptance.json
    _mk_run(tmp_path, "20260102-000000-bd", None, journal=None, reaped=True, filler=30)

    dist = harvester.verdict_distribution(tmp_path, key)
    assert dist["fate_counts"].get("died-at-launch") == 1, (
        f"a launch failure was not distinguished from a real attempt; {dist['fate_counts']}"
    )
    assert dist["fate_counts"].get("reaped") == 1


def test_a_finished_run_with_no_verdict_is_not_called_in_flight(harvester, tmp_path):
    """The bucket this classifier originally LACKED, and its absence was the same
    defect the probe exists to catch.

    Without an end-of-run test, every verdict-less run fell through to
    "in-flight-or-unfinished" -- so a run that had FINISHED and produced nothing read
    as "not done yet, no conclusion available". That is a denominator quietly
    excluding its own worst failures, which is precisely what row 21 is about. Caught
    by an independent verifier hours after this probe shipped the fix for that shape.

    A finished run that produced no verdict is the WORST outcome available. A run
    still executing is not an outcome at all. They must never share a bucket.
    """
    key = _goal_key(harvester)
    # finished: journal carries RUN-END
    _mk_run(
        tmp_path,
        "20260101-000000-bd",
        None,
        journal="RUN-START x\nTASK-START y\nRUN-END | processed=1\n",
        filler=30,
    )
    # still executing: no RUN-END, no SUMMARY.txt
    _mk_run(
        tmp_path, "20260102-000000-bd", None, journal="RUN-START x\nTASK-START y\n", filler=30
    )

    dist = harvester.verdict_distribution(tmp_path, key)

    assert dist["fate_counts"].get("finished-no-verdict") == 1, (
        "a run carrying RUN-END and no scorecard was not classified as "
        f"finished-no-verdict; fates were {dist['fate_counts']}"
    )
    assert dist["fate_counts"].get("in-flight") == 1, (
        f"a run with no RUN-END was not left as in-flight; fates were {dist['fate_counts']}"
    )


def test_summary_txt_alone_also_marks_a_run_finished(harvester, tmp_path):
    """Two independent end-of-run markers, because one writer can fail.

    A run killed mid-task may never write its final RUN-END while still having
    produced a SUMMARY.txt, and vice versa. Requiring both would push real finished
    runs back into the in-flight bucket this file exists to keep clean.
    """
    key = _goal_key(harvester)
    run = _mk_run(
        tmp_path, "20260101-000000-bd", None, journal="RUN-START x\nTASK-START y\n", filler=30
    )
    (run / "SUMMARY.txt").write_text("done\n", encoding="utf-8")

    dist = harvester.verdict_distribution(tmp_path, key)
    assert dist["fate_counts"].get("finished-no-verdict") == 1, (
        "SUMMARY.txt alone did not mark the run finished; a single end-of-run marker "
        f"must be sufficient. fates were {dist['fate_counts']}"
    )


def test_the_grouping_rule_is_echoed_and_names_the_input(harvester, tmp_path):
    """Row 21's original defect was an UNSTATED selection; the second was a BIASED one.

    The rule must travel with the result AND say that it keys on the input, so a reader
    can tell it is not conditioned on the run having survived.
    """
    key = _goal_key(harvester)
    _mk_run(tmp_path, "20260101-000000-bd", {"verdict": "GREEN"})
    dist = harvester.verdict_distribution(tmp_path, key)
    assert key in dist["grouping_rule"]
    assert "INPUT" in dist["grouping_rule"], (
        "the rule does not state that it keys on the input, which is the property that "
        "makes the tally defensible against the obvious challenge"
    )
    assert dist["goal_sha256_16"] == key


def test_operator_assets_are_not_confused_with_system_invented_specs(harvester, tmp_path):
    """These two fields are near-opposites and were conflated in the probe's first draft.

    `asset_specs` holds prompts the SYSTEM invented. `operator_assets` holds the
    operator's OWN material. Reporting the first under the second's name turns the
    standing M2 gap (his 29 photographs consumed by nothing) into an apparent success.
    """
    run_dir = tmp_path / "fleet-runs" / "20260815-222222-bd"
    run_dir.mkdir(parents=True)
    (run_dir / "acceptance.json").write_text(
        json.dumps(
            {
                "repo": "x",
                "spec": {
                    "clarifications": [],
                    "asset_specs": [{"name": "hero"}, {"name": "mug"}],
                    # operator_assets deliberately absent -- its corpus-wide state
                },
            }
        ),
        encoding="utf-8",
    )
    result = harvester.harvest(run_dir, run_dir.parent.parent)

    assert _by_label(result.items, "system-invented asset specs").value == 2
    operator = _by_label(result.items, "OPERATOR's own assets used")
    assert operator.value == harvester.ABSENT, (
        "the operator's own assets read as present while only system-invented specs "
        "existed. These must never share a label or a source path."
    )
    assert not operator.measured


def test_an_old_shape_sidecar_reads_as_absent_not_as_zero_pages(harvester, tmp_path):
    """#1433. Every sidecar banked before 2026-08-16 has `formCount` and no `pagesChecked`.

    "This instrument predates the fix" and "this run checked no pages" are different
    facts and only the second is a defect in the run. The harvester must not collapse
    them, which is the same absence-as-a-confident-value shape the probe exists to
    refuse -- and it is the shape a compatibility shim would have introduced here.
    """
    run_dir = tmp_path / "fleet-runs" / "20260814-230237-bd"
    run_dir.mkdir(parents=True)
    (run_dir / "exec-smoke-web.png.console.json").write_text(
        json.dumps({"forms": {"measured": True, "formCount": 0, "findings": []}}),
        encoding="utf-8",
    )
    result = harvester.harvest(run_dir, run_dir.parent.parent)

    pages_checked = _by_label(result.items, "pages checked for forms")
    assert pages_checked.value == harvester.ABSENT
    assert not pages_checked.measured, (
        "an old-shape sidecar reported a page count it never had. A missing field must "
        "never render as zero pages checked."
    )
    # The entry-page count is still readable -- it just is not a site-wide fact.
    assert _by_label(result.items, "forms found").value == 0


def test_the_new_shape_banks_the_site_wide_forms_evidence(harvester, tmp_path):
    """#1433. The shape produced by the fixed capture, harvested by row.

    Mirrors the replay against run 20260816-134142-bd's delivery: five pages checked,
    the contact page's form found, and its submit path undecidable because a listener
    attached with addEventListener is invisible to the probe (#1434).
    """
    run_dir = tmp_path / "fleet-runs" / "20260816-134142-bd"
    run_dir.mkdir(parents=True)
    (run_dir / "exec-smoke-web.png.console.json").write_text(
        json.dumps(
            {
                "forms": {
                    "measured": True,
                    "pagesChecked": 5,
                    "pagesWithForms": 1,
                    "formCount": 1,
                    "findings": [],
                },
                "pages": [
                    {"url": "http://x/", "entry": True,
                     "forms": {"measured": True, "formCount": 0, "loseDataUndecidable": 0}},
                    {"url": "http://x/contact.html", "entry": False,
                     "forms": {"measured": True, "formCount": 1, "loseDataUndecidable": 1}},
                ],
            }
        ),
        encoding="utf-8",
    )
    result = harvester.harvest(run_dir, run_dir.parent.parent)

    assert _by_label(result.items, "forms check ran").value is True
    assert _by_label(result.items, "pages checked for forms").value == 5
    assert _by_label(result.items, "forms found").value == 1
    assert _by_label(result.items, "forms undecidable").value == 1


def test_nothing_undecidable_is_a_measured_zero_not_an_absence(harvester, tmp_path):
    """#1433. The best possible result must not render as "not measured".

    The first draft of this counter used an `and`/`or` chain, and a genuine zero is
    falsy -- so a run where every form's submit path was decidable would have been
    reported as unmeasured. That is the exact defect the probe exists to remove, and it
    very nearly shipped inside the fix for it.
    """
    run_dir = tmp_path / "fleet-runs" / "20260816-999999-bd"
    run_dir.mkdir(parents=True)
    (run_dir / "exec-smoke-web.png.console.json").write_text(
        json.dumps(
            {
                "forms": {"measured": True, "pagesChecked": 2, "formCount": 1, "findings": []},
                "pages": [
                    {"url": "http://x/", "entry": True,
                     "forms": {"measured": True, "formCount": 1, "loseDataUndecidable": 0}},
                ],
            }
        ),
        encoding="utf-8",
    )
    result = harvester.harvest(run_dir, run_dir.parent.parent)

    undecidable = _by_label(result.items, "forms undecidable")
    assert undecidable.value == 0
    assert undecidable.measured, "a measured zero was reported as an absence"
