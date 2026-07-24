"""Unit locks for the #946 verdict-integrity prose guard.

The first three rejection cases are the REAL #855-measured failures
(2026-07-18 grading, #855 c.2200/2201) — kept verbatim-class so the guard can
never regress below the incident that created it. The toggle tests satisfy
security principle 12: every probe is proven to FAIL when its lock is off, so
"guard holds" is distinguishable from "test can't reach the guard"."""

from __future__ import annotations

import pytest
from pathlib import Path

from shared.coordinator.prose_guard import (
    GuardDecision,
    VERDICT_INCOMPLETE,
    VERDICT_PARKED,
    VERDICT_SUCCEEDED,
    ProseGuard,
    RunTruth,
    compose_run_headline,
)

_GUARD = ProseGuard()


# ── verdict classification (mirrors the forged-Done lock's semantics) ──────

def test_verdict_succeeded_requires_oracle_and_merge() -> None:
    assert RunTruth("r", True, True, False).verdict() == VERDICT_SUCCEEDED


def test_verdict_oracle_without_merge_is_not_success() -> None:
    assert RunTruth("r", True, False, False).verdict() == VERDICT_INCOMPLETE


def test_verdict_parked() -> None:
    assert RunTruth("r", False, True, True).verdict() == VERDICT_PARKED


def test_verdict_incomplete_when_nothing_supports_more() -> None:
    assert RunTruth("r", False, True, False).verdict() == VERDICT_INCOMPLETE


# ── the three REAL #855-measured failures (regression locks) ───────────────

#: 20260716-001549-bd: verdict PARKED-HONEST; the 14B claimed a full pass.
_WHOLLY_FALSE = (
    "The run passed all acceptance tests, confirming that the system is fully "
    "functional and ready for use."
)

#: 20260714-191219-bd: verdict STALLED (validate-html parked); right details,
#: false success headline.
_STALLED_HEADLINE = (
    "The run completed successfully, merging the header, about section, and "
    "projects list. However, the HTML validation timed out and wasn't completed."
)

#: 20260715-081634-bd: externally ABORTED mid-run; the merged-task fact was
#: true, the completion headline was not.
_ABORTED_HEADLINE = (
    "The coding-fleet run completed successfully on July 15, 2026, at "
    "08:16:34. The handle-zero-bill task was merged as part of the run's "
    "outcomes."
)


@pytest.mark.parametrize(
    ("truth", "text"),
    [
        (RunTruth("20260716-001549-bd", False, True, False), _WHOLLY_FALSE),
        (RunTruth("20260714-191219-bd", False, True, True), _STALLED_HEADLINE),
        (RunTruth("20260715-081634-bd", False, True, False), _ABORTED_HEADLINE),
    ],
    ids=["wholly-false-parked", "stalled-headline", "aborted-headline"],
)
def test_measured_855_failures_are_refused(truth: RunTruth, text: str) -> None:
    """As drafted live the texts carried no echo, so the echo layer refuses
    them FIRST — asserted precisely (reviewer-946 obs 1). The claim-screen
    layer for the same texts is proven separately by
    test_measured_failures_refused_even_with_a_compliant_echo + guard-004."""
    decision = _GUARD.validate_run_summary(truth, text)
    assert not decision.accepted
    assert decision.action == "rejected:echo-missing"


def test_measured_failures_refused_even_with_a_compliant_echo() -> None:
    """Defense-in-depth: were the model to learn the echo but keep lying in the
    body, the layer-3 screen still refuses (the echo alone never launders a
    contradicting claim)."""
    truth = RunTruth("20260716-001549-bd", False, True, False)
    decision = _GUARD.validate_run_summary(
        truth, f"{VERDICT_INCOMPLETE}: {_WHOLLY_FALSE}"
    )
    assert not decision.accepted
    assert decision.action.startswith("rejected:claim:")


#: 20260719-002208-bd (re-shadow window, 2026-07-22 report): oracle FAILED 4/6,
#: yet the draft claimed the tests passed — in the noun-before-verb order the
#: original lexicon missed. Accepted live on 3 cycles; locked here verbatim.
_INVERTED_TESTS_PASSED = (
    "INCOMPLETE: All features were successfully merged and acceptance tests "
    "passed, but the run was not completed as expected. The coding-fleet run "
    "for 20260719-002208-bd has finished with all components merged and tested."
)


def test_measured_inverted_tests_passed_claim_is_refused() -> None:
    """The 2026-07-22 re-shadow miss: an evidence-field success claim in
    noun-before-verb order ('tests passed'), behind a compliant echo, must die
    on the claim screen."""
    truth = RunTruth("20260719-002208-bd", False, True, False)
    decision = _GUARD.validate_run_summary(truth, _INVERTED_TESTS_PASSED)
    assert not decision.accepted
    assert decision.action == "rejected:claim:tests-passed"


def test_tests_passed_wording_is_legitimate_on_a_succeeded_run() -> None:
    """The same wording over a SUCCEEDED verdict is a true claim and must pass
    (success-claim screening applies only to non-SUCCEEDED verdicts)."""
    truth = RunTruth("r-green", True, True, False)
    decision = _GUARD.validate_run_summary(
        truth, "SUCCEEDED: All eight tasks merged and the acceptance tests passed."
    )
    assert decision.accepted


def test_negated_tests_passed_is_refused_by_the_priced_bias() -> None:
    """Negated-but-accurate 'tests passed' phrasings are REFUSED — the same
    deliberately priced refusal bias that pins 'did not complete successfully'
    (golden coord-guard-009). A partial negation carve-out was tried and
    rejected: it protected only the exact 'no tests' adjacency while the
    qualified forms re-anchored past it. Uniform bias, uniformly priced;
    loosening is a ceremony decision."""
    truth = RunTruth("r-parked", False, True, True)
    for text in (
        "PARKED: no tests passed for the parked wave, and the exam was skipped.",
        "PARKED: no acceptance tests passed after the wave gate failure.",
        "PARKED: only 2 of 9 tests passed on the integrated tree.",
    ):
        decision = _GUARD.validate_run_summary(truth, text)
        assert not decision.accepted, text
        assert decision.action == "rejected:claim:tests-passed"


def test_present_progressive_tests_passing_is_refused() -> None:
    """'tests are passing' is the present-progressive false-success shape —
    a success claim on a non-SUCCEEDED verdict, refused like its past-tense
    sibling."""
    truth = RunTruth("r-incomplete", False, True, False)
    decision = _GUARD.validate_run_summary(
        truth, "INCOMPLETE: the tests are passing and the modules look ready."
    )
    assert not decision.accepted
    assert decision.action == "rejected:claim:tests-passed"


def test_toggle_off_screen_accepts_the_inverted_tests_passed_text() -> None:
    """Principle 12 for the new lexicon entry: with the screen off, the same
    probe text is accepted — 'guard holds' stays distinguishable from 'test
    cannot reach the guard'."""
    guard = ProseGuard(screen_enabled=False)
    truth = RunTruth("20260719-002208-bd", False, True, False)
    assert guard.validate_run_summary(truth, _INVERTED_TESTS_PASSED).accepted


# ── what a compliant draft looks like (the guard gates, never silences) ────

def test_accurate_parked_summary_with_echo_is_accepted() -> None:
    """The one fully-accurate #855 statement, echo-prefixed, passes — including
    its task-level 'successfully merged' wording (task facts are not run
    claims) and its failure-vocabulary (legitimate for a PARKED verdict)."""
    truth = RunTruth("20260716-234039-bd", False, True, True)
    text = (
        "PARKED: All main features were successfully merged. The command "
        "interface was paused, and acceptance tests were not run."
    )
    decision = _GUARD.validate_run_summary(truth, text)
    assert decision.accepted and decision.action == "accepted"


def test_succeeded_summary_with_echo_is_accepted() -> None:
    truth = RunTruth("r-green", True, True, False)
    decision = _GUARD.validate_run_summary(
        truth, "SUCCEEDED: All five tasks merged and the acceptance oracle is green."
    )
    assert decision.accepted


# ── bidirectional screen: the pessimistic contradiction is refused too ─────

def test_failure_claim_on_succeeded_run_is_refused() -> None:
    truth = RunTruth("r-green", True, True, False)
    decision = _GUARD.validate_run_summary(
        truth, "SUCCEEDED: The build failed and nothing merged."
    )
    assert not decision.accepted
    assert decision.action.startswith("rejected:claim:")


def test_parked_echo_word_itself_never_trips_the_screen() -> None:
    """The mandated echo token contains a failure word by construction — the
    screen must strip exactly the echo, and only the echo, before matching."""
    truth = RunTruth("r-parked", False, True, True)
    decision = _GUARD.validate_run_summary(truth, "PARKED: One task remains.")
    assert decision.accepted


# ── annotations (no verdict context): success claims refused outright ──────

def test_annotation_success_claim_refused() -> None:
    decision = _GUARD.validate_annotation(
        "The parked task passed all tests and is ready for use."
    )
    assert not decision.accepted


def test_annotation_plain_description_accepted() -> None:
    decision = _GUARD.validate_annotation(
        "Proposes re-running the parked command-interface task with a sharper card."
    )
    assert decision.accepted


# ── empty / degenerate input is refused, never passed ──────────────────────

def test_empty_draft_is_refused() -> None:
    truth = RunTruth("r", False, True, False)
    assert not _GUARD.validate_run_summary(truth, "   ").accepted
    assert not _GUARD.validate_annotation("").accepted


# ── principle 12: every lock proven OFF (the probes depend on the locks) ───

def test_toggle_off_screen_and_echo_accepts_the_wholly_false_text() -> None:
    """With BOTH locks disabled (test-only construction — production has no
    off-switch), the #855 wholly-false text PASSES: proof the rejection tests
    above exercise the locks, not some other refusal path."""
    permissive = ProseGuard(screen_enabled=False, echo_required=False)
    truth = RunTruth("20260716-001549-bd", False, True, False)
    assert permissive.validate_run_summary(truth, _WHOLLY_FALSE).accepted


def test_toggle_off_screen_alone_still_refuses_on_echo() -> None:
    """Independence of the locks: the echo layer refuses even with the screen
    off — two locks, separately provable (defense-in-depth, not one mechanism
    wearing two names)."""
    echo_only = ProseGuard(screen_enabled=False, echo_required=True)
    truth = RunTruth("20260716-001549-bd", False, True, False)
    decision = echo_only.validate_run_summary(truth, _WHOLLY_FALSE)
    assert not decision.accepted and decision.action == "rejected:echo-missing"


# ── constant drift-lock (prose_guard cannot import heartbeat_cycle) ────────

def test_result_vocabulary_matches_heartbeat_cycle() -> None:
    from shared.coordinator import heartbeat_cycle as hc
    from shared.coordinator import prose_guard as pg

    assert pg.RESULT_MERGED == hc.RESULT_MERGED
    assert pg.RESULT_PARKED == hc.RESULT_PARKED


def test_draft_kinds_are_exhaustive() -> None:
    """Reviewer-946 obs 2: every kind ``_draft`` can tag must be in the tuple
    ``_guard_prose`` iterates — a kind outside it would be silently un-guarded
    AND un-digested. Locks the tuple to the tags the source actually uses."""
    import inspect

    from shared.coordinator import heartbeat_cycle as hc

    source = inspect.getsource(hc._draft)
    for kind in ("DRAFT_KIND_RUN_SUMMARY", "DRAFT_KIND_PROPOSAL"):
        assert kind in source, f"_draft no longer tags {kind}"
    tagged = {
        name for name in ("DRAFT_KIND_RUN_SUMMARY", "DRAFT_KIND_PROPOSAL")
        if name in source
    }
    assert {getattr(hc, name) for name in tagged} == set(hc.DRAFT_KINDS)


# ── the deterministic headline (layer 1) ───────────────────────────────────

def test_headline_parked_names_the_parked_task() -> None:
    truth = RunTruth("20260717-233441-bd", False, True, True)
    outcomes = [
        ("implement-data-storage", "MERGED"),
        ("implement-card-management", "MERGED"),
        ("implement-command-interface", "PARKED"),
    ]
    headline = compose_run_headline(truth, outcomes)
    assert headline == (
        "Run 20260717-233441-bd: PARKED — 2/3 tasks merged, "
        "parked at implement-command-interface"
    )


def test_headline_succeeded() -> None:
    truth = RunTruth("r-green", True, True, False)
    headline = compose_run_headline(truth, [("a", "MERGED"), ("b", "MERGED")])
    assert headline == "Run r-green: SUCCEEDED — 2/2 tasks merged, acceptance oracle green"


def test_headline_incomplete() -> None:
    truth = RunTruth("r-cut", False, True, False)
    headline = compose_run_headline(truth, [("a", "MERGED"), ("b", "processed")])
    assert headline == "Run r-cut: INCOMPLETE — 1/2 tasks merged, run did not complete"


# ── #1067 partial landing: the adverb-before-verb inversion ───────────────
#
# A false-ACCEPTANCE class that was live in shipped code, and the direction this
# guard exists to prevent. The claim pattern required the verb BEFORE the adverb,
# so "successfully completed" matched nothing: measured 2026-07-23 at 56/56
# adverb-first inversions ACCEPTED on an oracle-FAILED run against 0/24
# verb-first controls.
#
# It is the SAME word-order inversion as coord-guard-008 — the miss measured live
# on 2026-07-22 and golden-locked. That fix closed the noun-before-verb form and
# nobody swept the pattern for its siblings, so the identical shape sat open in
# the neighbouring alternation for another day. The lesson is in the sweep, not
# in the word.
#
# This lands SEPARATELY from #1067's false-suppression carve-out, and #1067 stays
# open behind it: widening the catch surface only ever makes the guard refuse
# more, which is the safe direction, whereas the carve-out grants excuses and has
# been rejected twice.

_ADVERB_FIRST_FALSE_CLAIMS: tuple[str, ...] = (
    "The run successfully completed.",
    "The build successfully completed all six tasks.",
    "The suite successfully ran.",
    "Everything successfully completed.",
    "The pipeline successfully finished.",
    "The run successfully finished and merged.",
)


@pytest.mark.parametrize("text", _ADVERB_FIRST_FALSE_CLAIMS)
def test_adverb_before_verb_inversion_is_refused(text: str) -> None:
    """Each of these was ACCEPTED by the shipped guard on a failed run."""
    truth = RunTruth("20260719-002208-bd", False, True, False)
    decision = _GUARD.validate_run_summary(truth, f"INCOMPLETE: {text}")
    assert not decision.accepted, f"FALSE ACCEPTANCE: {text}"
    assert decision.action == "rejected:claim:completed-successfully"


def test_verb_first_controls_still_refuse() -> None:
    """The original word order must keep working — this change ADDS an
    alternation, it does not replace one."""
    truth = RunTruth("r-incomplete", False, True, False)
    for text in (
        "The run completed successfully.",
        "The build finished successfully.",
        "The suite ran successfully.",
    ):
        decision = _GUARD.validate_run_summary(truth, f"INCOMPLETE: {text}")
        assert not decision.accepted, text


_TASK_LEVEL_ACCURATE: tuple[str, ...] = (
    "All main features were successfully merged. The command interface was "
    "paused, and acceptance tests were not run.",
    "All features were successfully merged into the main codebase, but the run "
    "did not complete all planned tasks.",
    "All features were merged successfully, but the run did not complete as "
    "expected.",
    "The run successfully merged three tasks.",
    "The run successfully parked at implement-quiz-logic.",
)


@pytest.mark.parametrize("text", _TASK_LEVEL_ACCURATE)
def test_task_level_accurate_prose_is_not_newly_suppressed(text: str) -> None:
    """The exclusions that make this affordable, locked as behaviour.

    `merged` is absent from BOTH alternations because merging tasks is
    compatible with a failed run — this is the coord-guard-005 class, and
    mirroring `merged` measures 44.12% false suppression over the live 34-cycle
    window against a ratified 5% ceiling.

    The last two rows additionally pin why the infinitive `run` is NOT in this
    change: adding it makes the pattern match the NOUN "run" before the adverb,
    which refuses both of these accurate lines."""
    for truth in (
        RunTruth("r-parked", False, True, True),
        RunTruth("r-incomplete", False, True, False),
    ):
        verdict = truth.verdict()
        decision = _GUARD.validate_run_summary(truth, f"{verdict}: {text}")
        assert decision.accepted, f"[{verdict}] {text} -> {decision.action}"


def test_run_infinitive_gap_is_now_closed() -> None:
    """FLIPPED, on the instruction its own predecessor carried.

    This was a characterisation lock asserting the infinitive `run` gap was
    still OPEN, with the note that it "must FLIP to a refusal assertion in the
    same change that lands the carve-out". That change is this one, and the test
    went red on its own terms rather than being remembered — which is the point
    of writing a gap down as an executable assertion instead of a comment.

    The gap was held rather than fixed because closing it ALONE refused accurate
    prose the guard accepted (6/6 constructed cases). With the carve-out in
    place "the suite could not run successfully" is accepted again, so the fix
    no longer costs what it used to."""
    truth = RunTruth("r-incomplete", False, True, False)
    for text in (
        "it did not fail to run successfully.",
        "the suite is not unable to run successfully.",
    ):
        decision = _GUARD.validate_run_summary(truth, f"INCOMPLETE: {text}")
        assert not decision.accepted, f"FALSE ACCEPTANCE: {text}"

    accurate = _GUARD.validate_run_summary(
        truth, "INCOMPLETE: the suite could not run successfully"
    )
    assert accurate.accepted, "the buy-back that makes the fix affordable"


def test_toggle_off_screen_accepts_the_adverb_first_text() -> None:
    """Principle 12 for the new alternation: with the screen off the same probe
    is accepted, so "guard holds" stays distinguishable from "the test cannot
    reach the guard"."""
    guard = ProseGuard(screen_enabled=False)
    truth = RunTruth("20260719-002208-bd", False, True, False)
    assert guard.validate_run_summary(
        truth, "INCOMPLETE: The run successfully completed."
    ).accepted


# ══════════════════════════════════════════════════════════════════════════
# #1067 — the negated-failure carve-out, vocabulary DERIVED FROM RUN TRUTH
#
# Six designs were rejected by independent review before this one. Their break
# corpora are permanent bars here, because each defect reads as obvious only
# after someone has found it:
#   v1-v4  excused on the PRESENCE of a negation marker  -> open-class flippers
#          and presupposition defeat any marker list
#   v5     examined only the claim's own segment          -> a reversing segment
#          beside it carried no claim, so nothing ever read it
#   v6     left an OPEN token slot                        -> a one-word reversal
#          ("Untrue, all tasks were merged") and a NEGATIVE subject ("None of
#          the tasks failed to complete successfully") both walked in
#
# The slot existed because the guard was guessing at vocabulary it could not
# know. It no longer guesses: the one variable position is bound to THIS RUN'S
# harvested task names.
# ══════════════════════════════════════════════════════════════════════════

import json as _json
from pathlib import Path as _Path

_CORPUS49_PATH = (
    _Path(__file__).resolve().parents[2]
    / "docs" / "reviews" / "1067-v5-evidence" / "corpus49.jsonl"
)
_CORPUS49 = [
    _json.loads(line)
    for line in _CORPUS49_PATH.read_text(encoding="utf-8").splitlines()
    if line.strip()
]

#: A WIDE task list for bar probes. Deliberately generous — including terms that
#: overlap the grammar's own function words — so the bars are proven to refuse
#: even when the run's vocabulary is broad.
_WIDE_TASKS = tuple(
    (name, "MERGED")
    for name in (
        "bill-splitter", "acceptance-tests", "store-cards", "add-card", "quiz",
        "track-scores", "migration", "router", "card-store", "scaffold",
        "deploy", "build", "run", "suite", "tests", "all", "everything",
    )
)


def test_inherited_corpus_is_the_expected_size() -> None:
    """If this number moves, the bar moved — say so out loud rather than letting
    a shrunken corpus report a clean run."""
    assert len(_CORPUS49) == 49
    by_origin: dict[str, int] = {}
    for row in _CORPUS49:
        by_origin[row["origin"]] = by_origin.get(row["origin"], 0) + 1
    assert by_origin == {
        "_REVIEW_FALSE_ACCEPTANCE_CORPUS": 18,
        "_CONTRACTION_AND_PADDING_CORPUS": 8,
        "_V4_HUNT_CORPUS": 23,
    }, by_origin


@pytest.mark.parametrize("case", _CORPUS49, ids=[r["case_id"] for r in _CORPUS49])
def test_no_false_success_claim_survives_the_carve_out(case: dict) -> None:
    truth = RunTruth(
        "r-incomplete", case["oracle_passed"], case["merged"], case["parked"]
    )
    decision = _GUARD.validate_run_summary(
        truth, case["text"], task_results=_WIDE_TASKS
    )
    assert not decision.accepted, f"FALSE ACCEPTANCE: {case['text']}"


#: The fifth design's cold pass: a segment that REVERSES the excused claim, and
#: which no per-segment analysis ever examines.
_V5_COLD_PASS: tuple[str, ...] = (
    "9 of 9 tests passed",
    "12 out of 12 acceptance tests passed.",
    "only 9 of 9 tests passed.",
    "The oracle scorecard is attached and 9 of 9 tests passed.",
    "The run did not complete successfully. That statement is false.",
    "The run did not complete successfully; that is a myth.",
    "The run did not complete successfully, but that is not true.",
    "The run did not complete successfully and that claim is a lie.",
    "The run did not complete successfully, though in fact it did.",
    "The run did not complete successfully. Ignore the previous sentence.",
    "Nobody should believe the following. The run did not complete successfully.",
    "no acceptance tests passed. That was the stale scorecard; the real one is green.",
    "The run did not complete successfully. It did on the retry.",
    "The build did not complete successfully. The rerun went green.",
    "The run did not complete successfully. Everything works end to end.",
    "no acceptance tests passed. The oracle is fully green and the feature is done.",
    "The run did not complete successfully. Correction: it did.",
    "no acceptance tests passed. Update: the whole suite is green.",
    "The run did not complete successfully. Really？",
    "The run did not complete successfully. That is wrong.",
    "The run didn’t complete successfully. The opposite is the case.",
)


@pytest.mark.parametrize("text", _V5_COLD_PASS)
def test_v5_cold_pass_stays_refused(text: str) -> None:
    truth = RunTruth("20260719-002208-bd", False, True, False)
    decision = _GUARD.validate_run_summary(
        truth, f"INCOMPLETE: {text}", task_results=_WIDE_TASKS
    )
    assert not decision.accepted, f"FALSE ACCEPTANCE: {text}"


#: The sixth design's cold pass. F1 is DOUBLE NEGATION — a negative subject plus
#: a negator asserts the positive. F2 is a one-word reversal laundered through an
#: open token slot. Both are false claims about a failed run.
_V6_COLD_PASS: tuple[str, ...] = (
    "None of the tasks failed to complete successfully.",
    "Nothing failed to complete successfully.",
    "None of the modules failed to complete successfully.",
    "Nothing did not complete successfully.",
    "None of the tasks did not complete successfully.",
    "Nothing was unable to complete successfully.",
    "None of the tasks were unable to complete successfully.",
    "Nothing could not complete successfully.",
    "Nothing never completed successfully.",
    "None of the tasks failed to successfully complete.",
    "None of the tasks failed to complete successfully. All tasks were merged.",
    "Nothing failed to complete successfully; everything merged.",
    "The run did not complete successfully. Untrue, all tasks were merged.",
    "The run did not complete successfully. False, everything merged.",
    "The run did not complete successfully. Correction, all tasks were merged.",
    "The run did not complete successfully. Nonsense, everything merged.",
    "The run did not complete successfully. Retracted, all tasks were merged.",
    "The run did not complete successfully. Wrong, everything merged.",
    "The run did not complete successfully. Disregard, all tasks were merged.",
    "The run did not complete successfully. Actually, all tasks were merged.",
    "The run did not complete successfully. No, everything merged.",
)


@pytest.mark.parametrize("text", _V6_COLD_PASS)
def test_v6_cold_pass_stays_refused(text: str) -> None:
    truth = RunTruth("20260719-002208-bd", False, True, False)
    decision = _GUARD.validate_run_summary(
        truth, f"INCOMPLETE: {text}", task_results=_WIDE_TASKS
    )
    assert not decision.accepted, f"FALSE ACCEPTANCE: {text}"


# ── the vocabulary binding itself ─────────────────────────────────────────

_LIVE_FALSE_SUPPRESSION_1067 = (
    "INCOMPLETE: The run 20260721-111715-bd is marked as incomplete. The "
    "bill-splitter and acceptance-tests components were merged, but the overall "
    "run did not complete successfully."
)
_LIVE_TASKS = (("bill-splitter", "MERGED"), ("acceptance-tests", "MERGED"))


def test_absent_vocabulary_refuses() -> None:
    """The fail-closed direction, and the whole reason an unreadable harvest leg
    is safe: with no task names the grammar's one variable position can never
    match, so a body naming a component is not consumed and no excuse is given.
    Absent data NARROWS the carve-out."""
    truth = RunTruth("20260721-111715-bd", False, True, False)
    with_names = _GUARD.validate_run_summary(
        truth, _LIVE_FALSE_SUPPRESSION_1067, task_results=_LIVE_TASKS
    )
    without = _GUARD.validate_run_summary(truth, _LIVE_FALSE_SUPPRESSION_1067)
    assert with_names.accepted
    assert not without.accepted
    assert without.action == "rejected:claim:completed-successfully"


def test_a_task_named_like_a_reversal_cannot_launder_one() -> None:
    """The attack the operator asked about: task names are open-class and come
    from a planner over the operator's own goals, so a run COULD contain a task
    called "untrue" — which would carry reversal power straight into the one
    variable position. Such names are filtered out before use."""
    truth = RunTruth("r-incomplete", False, True, False)
    attack = (
        "INCOMPLETE: The run did not complete successfully. Untrue, all tasks "
        "were merged."
    )
    for tasks in (
        (),
        (("untrue", "MERGED"), ("all", "MERGED")),
        (("false", "MERGED"), ("all", "MERGED")),
        (("Untrue", "MERGED"), ("all", "MERGED")),
    ):
        decision = _GUARD.validate_run_summary(truth, attack, task_results=tasks)
        assert not decision.accepted, f"laundered via task names {tasks!r}"


def test_unusable_task_names_are_filtered() -> None:
    from shared.coordinator.prose_guard import _usable_terms

    usable = _usable_terms(
        frozenset({"untrue", "FALSE", "bill-splitter", "a", "has space", "quiz"})
    )
    assert usable == frozenset({"bill-splitter", "quiz"})


# ── the SEAM: the names must actually reach the guard ─────────────────────

def test_run_wake_cycle_hands_the_guard_the_harvested_record(tmp_path) -> None:
    """Drives the REAL ``run_wake_cycle`` and captures what the guard is handed.

    Third attempt at this test, and the first that can fail on the line that has
    actually broken twice. The history is the point:

      1st  re-implemented the derivation in its own body and asserted its own
           comprehension — passed with every production entry point stubbed to
           raise. A pure tautology.
      2nd  called ``_guard_prose``, so it caught a broken FORWARD but still
           recomputed the derivation inline. Its docstring claimed it "drives
           run_wake_cycle" and "never computes it"; both were false, which an
           independent pass caught. That was a claim outrunning the code for the
           fourth time on this ticket — in a TEST docstring, where the retraction
           paragraph's warning applies just as well.
      3rd  this one. It computes nothing. ``run_wake_cycle`` derives the record
           from the snapshot, and the assertion is on what arrives at the guard,
           so changing that derivation — back to bare names, to merged-only, to
           dropping the record — turns this RED.
    """
    from shared.fleet import vikunja_bridge as vb
    from shared.fleet.dispatch import TaskOutcome
    from shared.tests.test_heartbeat_cycle import (
        LOCAL_DAY,
        NOW,
        _DraftSpy,
        _env,
        _snapshot,
        _tri,
    )
    from shared.coordinator.proposal_store import build_proposal_store
    from shared.coordinator import heartbeat_cycle as hc

    seen: dict[str, object] = {}

    class _Spy:
        def validate_run_summary(self, truth, text, *, task_results=()):
            seen["summary"] = tuple(task_results)
            return GuardDecision(True, "accepted")

        def validate_annotation(self, text, *, task_results=()):
            return GuardDecision(True, "accepted")

    outcomes = (
        TaskOutcome("bill-splitter", "processed", "MERGED", "RESULT: MERGED"),
        TaskOutcome("acceptance-tests", "processed", "PARKED", "RESULT: PARKED"),
    )
    snap = _snapshot(
        latest_run=_tri(vb.ReadStatus.OK, ("20260721-111715-bd", outcomes))
    )
    draft = _DraftSpy(
        hc.DraftOutcome(
            status="drafted",
            text="INCOMPLETE: The run did not complete successfully.",
        )
    )

    original = hc._PROSE_GUARD
    try:
        hc._PROSE_GUARD = _Spy()
        store = build_proposal_store(":memory:")
        try:
            env = _env(
                tmp_path,
                store,
                snap,
                draft=draft,
                read_scorecard=lambda rid: {"oracle": {"status": "FAILED"}},
            )
            hc.run_wake_cycle(env, now=NOW, local_now=LOCAL_DAY)
        finally:
            store.close()
    finally:
        hc._PROSE_GUARD = original

    assert seen.get("summary") == (
        ("bill-splitter", "MERGED"),
        ("acceptance-tests", "PARKED"),
    ), (
        "the harvested (task, result) record did not reach the guard intact — "
        "the carve-out would run on a vocabulary the cycle never derived"
    )


def test_an_unreadable_harvest_leg_hands_the_guard_no_vocabulary(tmp_path) -> None:
    """An unreadable harvest leg guards NO prose at all — a stronger property
    than the empty vocabulary the code comment claims.

    THIS TEST IS SELF-CONTAINED, and it took three attempts to get there.

    Attempt 1 asserted that both doors receive ``()``, which was VACUOUS: with an
    unreadable leg the guard is never called, so the loop ran over an empty dict
    and passed under the very mutation it was written to catch.

    Attempt 2 asserted non-vacuity — and was still not self-contained. Asserting
    an ABSENCE is green whenever the cycle produces no prose FOR ANY REASON: an
    independent pass proved it by making drafting dormant, an unrelated mutation
    that left this test GREEN while its positive sibling went RED. The pair was
    sound; this test was leaning on a sibling it never named, so deleting,
    skipping or drifting that sibling would have left this one passing forever.

    What is locked now, in ONE test so the contrast cannot be separated from the
    claim: the identical environment is run TWICE with only the harvest leg's
    ReadStatus flipped. OK => the guard IS called (so the absence below means
    something). UNREACHABLE => the guard is NOT called, so no draft is produced
    without harvest truth and stale vocabulary from a previous run has nothing
    to excuse.

    HONEST LIMIT — this does NOT cover the vocabulary derivation itself. A
    mutation removing the ``ReadStatus.OK`` check survives this test and the
    whole suite, because on this path it is INERT: the branch it weakens is
    unreachable while no draft exists. That is a reachability argument, not a
    lock, and it stops holding the moment a surface drafts prose without a
    readable latest-run leg."""
    from shared.fleet import vikunja_bridge as vb
    from shared.fleet.dispatch import TaskOutcome
    from shared.tests.test_heartbeat_cycle import (
        LOCAL_DAY,
        NOW,
        _DraftSpy,
        _env,
        _snapshot,
        _tri,
    )
    from shared.coordinator import heartbeat_cycle as hc
    from shared.coordinator.proposal_store import build_proposal_store

    stale = (
        TaskOutcome("from-another-run", "processed", "MERGED", "RESULT: MERGED"),
    )

    def _run_with(status) -> dict[str, object]:
        """One wake cycle, identical in every respect but the leg's status."""
        seen: dict[str, object] = {}

        class _Spy:
            def validate_run_summary(self, truth, text, *, task_results=()):
                seen["summary"] = tuple(task_results)
                return GuardDecision(True, "accepted")

            def validate_annotation(self, text, *, task_results=()):
                seen["annotation"] = tuple(task_results)
                return GuardDecision(True, "accepted")

        snap = _snapshot(latest_run=_tri(status, ("20260101-000000-zz", stale)))
        draft = _DraftSpy(
            hc.DraftOutcome(
                status="drafted",
                text="INCOMPLETE: The run did not complete successfully.",
            )
        )
        original = hc._PROSE_GUARD
        try:
            hc._PROSE_GUARD = _Spy()
            store = build_proposal_store(":memory:")
            try:
                env = _env(
                    tmp_path,
                    store,
                    snap,
                    draft=draft,
                    read_scorecard=lambda rid: {"oracle": {"status": "FAILED"}},
                )
                hc.run_wake_cycle(env, now=NOW, local_now=LOCAL_DAY)
            finally:
                store.close()
        finally:
            hc._PROSE_GUARD = original
        return seen

    # The PRESENCE half. Without this, the absence below proves nothing: any
    # change that stops the cycle drafting at all would satisfy it silently.
    readable = _run_with(vb.ReadStatus.OK)
    assert readable, (
        "the positive control produced no guarded prose, so this test cannot "
        "distinguish 'an unreadable leg guards nothing' from 'nothing is "
        "guarded here at all'. Fix the control before trusting the assertion "
        "below — an absence is only evidence next to a presence."
    )

    # The ABSENCE half, now meaningful.
    unreadable = _run_with(vb.ReadStatus.UNREACHABLE)
    assert unreadable == {}, (
        f"prose was guarded from an UNREADABLE harvest leg: {unreadable!r}. "
        "Either a draft is now produced without harvest truth — in which case "
        "the vocabulary derivation needs its own lock, since stale names from "
        "another run would license excuses this cycle never earned — or the "
        "spy is observing a door this test did not expect."
    )


def test_merge_claims_are_bound_to_results_not_just_names() -> None:
    """A name may only appear in a clause whose predicate is TRUE of it.

    Feeding merged-only names to every clause inverted the not-merged clause
    completely: "bill-splitter was parked" was ACCEPTED when it had MERGED and
    REFUSED when it truly had parked — every instantiation false, every true one
    dropped. Caught by an independent pass; locked here in both directions."""
    truth = RunTruth("r-incomplete", False, True, False)
    results = (("bill-splitter", "MERGED"), ("acceptance-tests", "PARKED"))

    def judge(tail: str) -> bool:
        return _GUARD.validate_run_summary(
            truth,
            f"INCOMPLETE: The run did not complete successfully and {tail}",
            task_results=results,
        ).accepted

    # FALSE of the record — must refuse
    assert not judge("bill-splitter was not merged.")
    assert not judge("bill-splitter was parked.")
    # TRUE of the record — must be accepted
    assert judge("acceptance-tests was parked.")
    assert judge("bill-splitter was merged.")


def test_a_full_pass_wearing_a_limiter_is_refused_at_any_ratio() -> None:
    """The cold pass's blocker: an earlier cut required only numerator <
    denominator, so "only 999 out of 1000 unit tests passed" was ACCEPTED on a
    run where nothing merged and no test passed. The limiter word does no work
    at that ratio. The bound is now a MINORITY claim."""
    truth = RunTruth("r-parked", False, False, True)
    for text in (
        "only 999 out of 1000 unit tests passed.",
        "only 8 of 9 acceptance tests passed.",
        "only 5 of 9 tests passed.",
        "only 9 of 9 tests passed.",
        "The run did not complete successfully, but only 8 of 9 acceptance "
        "tests passed.",
    ):
        decision = _GUARD.validate_run_summary(truth, f"PARKED: {text}")
        assert not decision.accepted, f"FALSE ACCEPTANCE: {text}"

    # the ticket's own example still clears the bound
    assert _GUARD.validate_run_summary(
        truth, "PARKED: only 2 of 9 tests passed."
    ).accepted


def test_quantifier_task_names_cannot_assert_universal_success() -> None:
    """A task named "all" would turn the neutral clause into a universal success
    claim. Same class as the reversal-word filter, which covered reversals but
    not quantifiers until a cold pass pointed it out."""
    truth = RunTruth("r-incomplete", False, True, False)
    decision = _GUARD.validate_run_summary(
        truth,
        "INCOMPLETE: The run did not complete successfully but all tasks were "
        "merged.",
        task_results=(("all", "MERGED"), ("bill-splitter", "MERGED")),
    )
    assert not decision.accepted


# ── the discriminator pair, asserted together ─────────────────────────────

_LIVE_MISS_1067 = (
    "INCOMPLETE: All features were successfully merged and acceptance tests "
    "passed, but the run was not completed as expected. The coding-fleet run "
    "for 20260719-002208-bd has finished with all components merged and tested."
)


def test_the_discriminator_pair() -> None:
    """009 must be ACCEPTED and 008 must stay REFUSED. They are adversarial to
    each other, so a design that cannot tell them apart is wrong by
    construction. One test, so a change cannot fix one and regress the other."""
    d009 = _GUARD.validate_run_summary(
        RunTruth("20260721-111715-bd", False, True, False),
        _LIVE_FALSE_SUPPRESSION_1067,
        task_results=_LIVE_TASKS,
    )
    assert d009.accepted, f"009 must be accepted: {d009.action}"

    d008 = _GUARD.validate_run_summary(
        RunTruth("20260719-002208-bd", False, True, False),
        _LIVE_MISS_1067,
        task_results=_WIDE_TASKS,
    )
    assert not d008.accepted
    assert d008.action == "rejected:claim:tests-passed"


def test_qualified_negation_forms_are_accepted() -> None:
    """#1067's DESCRIPTION names these two and its predicate says
    "qualified-negation cases green"."""
    truth = RunTruth("r-parked", False, True, True)
    for text in (
        "PARKED: no acceptance tests passed.",
        "PARKED: only 2 of 9 tests passed.",
        "PARKED: none of the acceptance tests passed.",
        "PARKED: not all tests passed.",
    ):
        decision = _GUARD.validate_run_summary(truth, text)
        assert decision.accepted, f"{text} -> {decision.action}"


def test_a_full_pass_wearing_a_limiter_is_refused() -> None:
    """"only 9 of 9 tests passed" is a total-success claim. There is no bare
    "<n> of <m>" form at all — one was written and an independent pass rejected
    it, because nothing bound the numerator below the denominator."""
    truth = RunTruth("r-incomplete", False, True, False)
    for text in ("only 9 of 9 tests passed.", "9 of 9 tests passed.",
                 "only 10 of 9 tests passed."):
        decision = _GUARD.validate_run_summary(truth, f"INCOMPLETE: {text}")
        assert not decision.accepted, text


def test_run_infinitive_claims_are_refused_and_the_noun_is_not_matched() -> None:
    """The infinitive `run` lands WITH the carve-out, never before it: alone it
    refused accurate prose the guard accepts today. The lookbehinds keep the
    verb reading and drop the noun one — "the run successfully merged three
    tasks" is TRUE of a failed run and must survive."""
    truth = RunTruth("r-incomplete", False, True, False)
    for text in (
        "it did not fail to run successfully.",
        "it could not fail to run successfully.",
        "the suite is not unable to run successfully.",
        "The suite did not run successfully until the third attempt.",
    ):
        assert not _GUARD.validate_run_summary(
            truth, f"INCOMPLETE: {text}", task_results=_WIDE_TASKS
        ).accepted, text

    for text in (
        "The run successfully merged three tasks.",
        "The run successfully parked at implement-quiz-logic.",
    ):
        assert _GUARD.validate_run_summary(
            truth, f"INCOMPLETE: {text}", task_results=_WIDE_TASKS
        ).accepted, text


def test_the_bought_back_class_is_accepted() -> None:
    truth = RunTruth("r-incomplete", False, True, False)
    for text, tasks in (
        ("the run did not complete successfully", ()),
        ("the suite could not run successfully", ()),
        ("The card-store and router components merged, but the run did not "
         "complete successfully.",
         (("card-store", "MERGED"), ("router", "MERGED"))),
    ):
        decision = _GUARD.validate_run_summary(
            truth, f"INCOMPLETE: {text}", task_results=tasks
        )
        assert decision.accepted, f"{text} -> {decision.action}"


def test_both_doors_agree() -> None:
    """Before #1067 the identical sentence was accepted at one door and refused
    at the other. The carve-out never consults the verdict, so honouring it at
    both is sound."""
    sentence = "the overall run did not complete successfully"
    truth = RunTruth("r-incomplete", False, True, False)
    summary = _GUARD.validate_run_summary(truth, f"INCOMPLETE: {sentence}.")
    annotation = _GUARD.validate_annotation(f"{sentence}.")
    assert summary.accepted is annotation.accepted is True


def test_annotation_door_still_refuses_bare_success_claims() -> None:
    for text in (
        "the run completed successfully",
        "the run successfully completed",
        "all acceptance tests passed",
        "None of the tasks failed to complete successfully.",
    ):
        assert not _GUARD.validate_annotation(text).accepted, text


# ── principle 12: every control proven to FAIL when switched off ──────────

def test_toggle_off_carve_out_refuses_the_accurate_sentence_again() -> None:
    guard = ProseGuard(negation_carve_out=False)
    decision = guard.validate_run_summary(
        RunTruth("20260721-111715-bd", False, True, False),
        _LIVE_FALSE_SUPPRESSION_1067,
        task_results=_LIVE_TASKS,
    )
    assert not decision.accepted
    assert decision.action == "rejected:claim:completed-successfully"


def test_carve_out_probe_reaches_the_live_code_path() -> None:
    """The toggle must patch the real thing. ``_claim_is_excused`` is resolved as
    a module global at CALL time; a probe captured at import would be a no-op
    that passes against the bug."""
    from shared.coordinator import prose_guard as pg

    truth = RunTruth("20260721-111715-bd", False, True, False)
    original = pg._claim_is_excused
    try:
        pg._claim_is_excused = lambda body, merged, unmerged, run_id: False
        assert not _GUARD.validate_run_summary(
            truth, _LIVE_FALSE_SUPPRESSION_1067, task_results=_LIVE_TASKS
        ).accepted
    finally:
        pg._claim_is_excused = original
    assert _GUARD.validate_run_summary(
        truth, _LIVE_FALSE_SUPPRESSION_1067, task_results=_LIVE_TASKS
    ).accepted
