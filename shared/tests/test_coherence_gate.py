"""Tests for #1054 (S3 slice E) — coherence by single authorship.

Two halves, and they are tested as two different KINDS of thing:

* **single-pass authoring** is a quality change — the criteria and the assumptions come from
  ONE model call, so the model cannot rule a capability out in one block and require it in
  the other. Tested by counting which prompts the model actually received.
* **the deterministic coherence gate** is a control — it REFUSES a plan whose two halves
  disagree, so the retirement survives a model regression. Tested to BLOCK when engaged and,
  per security_by_design principle 12, to let the identical defect through when the flag is
  off. Without that second half you cannot tell "the gate blocks" from "the test cannot reach
  the gate".

The gate's contract is narrow and this file is written to keep it honest: it reports only
ESTABLISHED contradictions, and a large part of what follows pins what it deliberately does
NOT catch. Independent review found the first version refusing 5 of 30 coherent specs, so the
corpus below is adversarial against this design — punctuation-split clauses, pronoun
negation, manner adverbials, qualified negation — rather than examples chosen to agree with
it. A corpus that can only agree with its author measures nothing.

Both halves are behind ``coherence_gate``, which additionally requires ``advanced_intake``.
The flag-off spec must be byte-identical, which is the standing bar for every intake slice.

Model calls are faked throughout (offline, no GPU).
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from shared.fleet import acceptance
from shared.fleet.acceptance import (
    _ASSUMPTIONS_TEMPLATE,
    _COAUTHORED_TEMPLATE,
    _CRITERIA_TEMPLATE,
    DecompositionOverride,
    coauthored_emission_json_schema,
    generate_plan,
)
from shared.fleet.coherence import (
    KIND_CONTRADICTION,
    check_coherence,
    content_tokens,
    extract_exclusions,
    refusal_message,
)

# ---------------------------------------------------------------------------
# The measured defect, verbatim (#1054, live water-tracker dispatch 2026-07-22)
# ---------------------------------------------------------------------------

_LIVE_ASSUMPTION = "Assumed a reset button is not needed."
_LIVE_CRITERION = (
    "The web page includes a reset button to reset the daily water intake counter to zero."
)


# ===========================================================================
# PART 1 — the gate as a decision procedure
# ===========================================================================


def test_the_live_1054_contradiction_is_caught():
    """The exact pair a real dispatch produced. If this ever goes green while the gate is
    broken, nothing else in this file matters."""
    findings = check_coherence([_LIVE_ASSUMPTION], [_LIVE_CRITERION])
    assert len(findings) == 1, findings
    f = findings[0]
    assert f.kind == KIND_CONTRADICTION
    assert f.subject == "reset button"       # the subject really was EXTRACTED, not implied
    assert f.excluded_by == _LIVE_ASSUMPTION
    assert f.required_by == _LIVE_CRITERION


def test_the_contradiction_survives_being_buried_in_a_real_criteria_list():
    """The live plan had four criteria and the contradiction was the fourth. A gate that only
    looks at the first one would pass this."""
    findings = check_coherence(
        [_LIVE_ASSUMPTION, "Assumed the totals reset at midnight."],
        [
            "The web page has a button that adds one glass to today's total.",
            "The running total of glasses is displayed on the page.",
            "The served page loads and displays its main content.",
            _LIVE_CRITERION,
        ],
    )
    assert [f.subject for f in findings] == ["reset button"], findings


def test_the_reverse_direction_is_checked_too():
    """A criterion that EXCLUDES what an assumption REQUIRES is the same defect wearing the
    other hat. Disagreement has no privileged side."""
    findings = check_coherence(
        ["Assumed a dark mode toggle is provided."],
        ["The page does not include a dark mode toggle."],
    )
    assert len(findings) == 1
    assert findings[0].kind == KIND_CONTRADICTION
    assert findings[0].subject == "dark mode toggle"


@pytest.mark.parametrize(
    "criterion",
    [
        "The page does not include a reset button.",
        "The page never shows a reset button.",
        "There is no reset button.",
        "The page works without a reset button.",
    ],
)
def test_agreement_is_not_a_contradiction(criterion):
    """Both sides ruling the SAME capability out is the outcome this gate protects, not one it
    reports. ``not``/``no`` are function words the tokeniser drops, so without the negation
    frames a negated criterion still CONTAINS the excluded phrase and would be convicted of
    requiring it — this pins the frames actually seeing through it.

    The ``without`` case is load-bearing for the two-set design: that frame may not CONVICT
    (see F2 below) but must still be read HERE, or removing it would convict this criterion of
    requiring the very thing it rules out."""
    assert check_coherence([_LIVE_ASSUMPTION], [criterion]) == ()


# ---------------------------------------------------------------------------
# REGRESSION LOCKS for the two blocking findings of the 2026-07-23 review.
# Both were FALSE REFUSALS — the gate declining coherent plans — which is the
# failure direction that makes a control unshippable rather than merely leaky.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "assumption",
    [
        # F1: the capability is named in one clause and negated by pronoun in the next.
        "Assumed a reset button would be useful, but it is not needed for a first version.",
        "Assumed a search box might help; it is not required for now.",
        "Assumed a reset button would be useful - but it is not needed yet.",
        # and the genuinely vague form, which is ALSO no longer a refusal
        "Assumed it is not needed.",
        "Assumed this is not required.",
    ],
)
def test_F1_a_span_the_regex_could_not_reach_is_never_a_refusal(assumption):
    """REVIEW FINDING F1. The first version refused here, reporting an ``undecidable``
    exclusion — and its real trigger was PUNCTUATION, not vagueness: the subject pattern
    cannot span a comma or semicolon, so the earliest possible match started at the pronoun
    and normalised to nothing. The same sentence with a dash passed. A parse failure was
    being surfaced as a semantic verdict, on the REFUSE side.

    The arm is gone, because it could never have caught anything: an unnamed subject cannot be
    matched against any criterion, so it could only ever produce a blanket refusal. Note the
    last two cases — genuinely vague statements now pass too, which is the honest consequence
    and is stated in the module's contract rather than papered over."""
    assert check_coherence([assumption], ["The page shows the daily total."]) == ()
    # and the same sentence on the criteria side, since _cross runs both directions
    assert check_coherence(["Assumed the page shows a total."], [assumption]) == ()


@pytest.mark.parametrize(
    ("assumption", "criterion"),
    [
        ("Assumed a clear error message is shown for invalid input.",
         "The app launches without an error message."),
        ("Assumed the page refresh keeps the running total.",
         "The total updates without a page refresh."),
        ("Assumed the page refresh keeps the running total.",
         "The total updates with no page refresh."),
        # the shipped _CRITERIA_TEMPLATE primes the model with this exact phrasing
        ("Assumed a crash report screen is not needed.",
         "The app launches without crashing."),
    ],
)
def test_F2_manner_adverbials_are_not_exclusions(assumption, criterion):
    """REVIEW FINDING F2. ``without X`` and a bare clause-final ``no X`` are manner adverbials
    at least as often as they are exclusions, and in those the FRAME supplies the judgement
    rather than locating a subject the statement supplies — the author-written-English class
    ``_check_names_a_mechanism`` was withdrawn for. The phrase match cannot rescue it, because
    the captured subject is genuine statement vocabulary.

    Both frames are now SEE-THROUGH ONLY: they may suppress a conviction, never cause one."""
    assert check_coherence([assumption], [criterion]) == ()


def test_F1_an_empty_span_is_dropped_at_EXTRACTION_not_merely_at_conviction():
    """Defence in depth for F1 — and it needed its own assertion, which is how it got one.

    A mutant re-admitting empty spans to extraction survived the ENTIRE suite, because the
    conviction path discards an empty subject anyway (zero tokens is below the two-token
    floor). The drop was therefore an accident of the floor rather than a property of
    extraction, and a future change to that floor would silently restore the F1 arm.

    Pinned at the layer that actually does it. Both forms are covered: the genuinely vague
    statement, and the two-clause sentence whose span the pattern could not reach past the
    punctuation."""
    from shared.fleet.coherence import _SEE_THROUGH_FRAMES, _extract

    for statement in (
        "Assumed it is not needed.",
        "Assumed a reset button would be useful, but it is not needed for a first version.",
        "Assumed a search box might help; it is not required for now.",
    ):
        assert extract_exclusions(statement) == (), statement
        assert _extract(statement, _SEE_THROUGH_FRAMES) == (), statement


def test_the_two_frame_sets_are_genuinely_different():
    """Anti-vacuity for the split: had the demoted frames been left in the convicting set — or
    dropped from the see-through set entirely — half this file would still pass. Pin both
    directions of the asymmetry on the SAME phrase."""
    from shared.fleet.coherence import (
        _CONVICTING_FRAMES,
        _SEE_THROUGH_FRAMES,
        _SEE_THROUGH_ONLY_FRAMES,
    )

    assert _SEE_THROUGH_ONLY_FRAMES, "the split collapsed — nothing was demoted"
    assert len(_SEE_THROUGH_FRAMES) == len(_CONVICTING_FRAMES) + len(
        _SEE_THROUGH_ONLY_FRAMES
    )
    # `without X` does NOT convict ...
    assert extract_exclusions("Assumed the page works without a backend server.") == ()
    # ... but IS read as agreement, which is the only reason it is still read at all.
    assert check_coherence(
        ["Assumed a backend server is not needed."],
        ["The page works without a backend server."],
    ) == ()


def test_single_token_subjects_are_not_convicted():
    """THE MEASURED TRADE, pinned so it cannot be mistaken for an oversight.

    At a one-token floor the gate convicted "Assumed the data is not stored between sessions"
    against "The app displays a chart of today's data points" — a common-noun collision, not a
    requirement for stored data. So a one-word subject is acquitted, and the price is recall.

    The second half is what makes the first meaningful: the SAME sentence shape with a
    two-word subject IS convicted, so the floor is measuring token count rather than the gate
    being broken for this whole class."""
    assert check_coherence(
        ["Assumed the data is not stored between sessions."],
        ["The app displays a chart of today's data points."],
    ) == ()
    convicted = check_coherence(
        ["Assumed the session data is not stored between sessions."],
        ["The app displays a chart of today's session data points."],
    )
    assert [f.subject for f in convicted] == ["session data"], convicted


def test_F4_the_size_of_the_one_word_escape_is_pinned_not_merely_disclosed():
    """REVIEW FINDING F4. The limit was disclosed; its SIZE was not. Measured: every one of
    the ten commonest single-noun capabilities escapes. That is most of a small application's
    feature vocabulary, not an edge, and a reader deciding whether this gate is worth flipping
    on is entitled to know it.

    Pinned as a count so that if a future change starts catching these, this test fails and
    forces the module docstring — and the operator-facing config comment — to be corrected in
    the same change."""
    escaping = [
        word
        for word in (
            "history", "search", "undo", "login", "pagination",
            "notifications", "autosave", "printing", "charts", "sorting",
        )
        if not check_coherence(
            [f"Assumed no {word} is needed."], [f"The {word} is shown on the main screen."]
        )
    ]
    assert len(escaping) == 10, f"the measured escape set changed: {escaping}"


@pytest.mark.parametrize(
    ("assumption", "criterion", "subject"),
    [
        ("Assumed the user data stays in the browser.",
         "The user data is not stored on a server.", "user data"),
        ("Assumed the running total updates immediately.",
         "The running total is not saved to disk.", "running total"),
        ("Assumed a reset button is available.",
         "The reset button is not shown on the print view.", "reset button"),
    ],
)
def test_F7_a_negation_scoping_over_a_qualifier_still_convicts(
    assumption, criterion, subject
):
    """REVIEW FINDING F7 — **THIS TEST ASSERTS A DEFECT**, queued as #1096.

    Read the assertion as "this is what the gate wrongly does today", never as intended
    behaviour. Every pair below is entirely compatible, and the gate REFUSES the plan.

    The convicting frames capture a subject and convict on it regardless of what the negation
    actually scopes over. "The user data is not stored ON A SERVER" negates the *qualifier*,
    not the capability — the user data is still required — but the frame reads it as an
    exclusion. The re-pass measured 8 reproductions across four of the six convicting frames.
    Same failure direction as F1 and F2, which is why #1096 sits above #1095 in priority.

    PRE-EXISTING: verified byte-identical against ``ffc0dae1``, the original slice-E build,
    so neither that build nor the F1/F2 round (``257e0ac7``) introduced it.

    NOT FIXED HERE, deliberately and on instruction. The available fix narrows the convicting
    set, and every defect found on this tree on 2026-07-23 inside an author-applied fix round
    was introduced BY the fix — five instances — with the F1/F2 round the first to introduce
    nothing. A logic change in a third consecutive round is how that restarts. #1096 carries
    the direction and the definition of done.

    WHY BOTH CORPORA READ ZERO, which is the part worth keeping: this shape is absent from all
    50 naturally-written coherent specs across two independently authored corpora. Nobody
    writes "not stored on a server" while inventing examples of *coherent specs*; you write it
    while inventing examples of *products*. ``test_zero_false_refusals_on_the_adversarial_corpus``
    is not wrong to report 0/30 — the shape is simply not in it. That is the sharpest instance
    yet of the standing lesson that a measurement is only as adversarial as whoever wrote the
    inputs, and it is why #1096 forbids its closer from being the sole author of its corpus."""
    findings = check_coherence([assumption], [criterion])
    assert [f.subject for f in findings] == [subject], (
        "F7 changed behaviour. If it was fixed deliberately, invert this test and close "
        "#1096 (checking its other two conditions first); if it changed by accident, that "
        "is a regression whichever way it moved."
    )


def test_F3_a_qualified_negation_on_the_requiring_side_is_excused():
    """REVIEW FINDING F3 — a KNOWN limit, pinned here and QUEUED as #1095.

    This test is the durable record; #1095 is the queue placement, and neither substitutes for
    the other — a failing-by-design test nobody is scheduled to pick up is a dropped finding
    wearing an assertion. #1095 carries the observable definition of done: invert this test
    WHILE ``test_zero_false_refusals_on_the_adversarial_corpus`` stays at zero.

    "The reset button is not shown until an entry exists" REQUIRES a reset button, but it
    carries an exclusion frame over that subject, so the agreement check suppresses — #1054's
    own defect shape landing in the excused bucket.

    Not patched here, deliberately. Every candidate fix NARROWS the agreement check, which
    pushes toward MORE convictions — the exact failure direction that made the first version
    unshippable (5 false refusals in 30) and the one this round exists to correct. Shipping a
    conviction-widening change inside a conviction-narrowing fix round is how a fix round
    introduces its own defect. Closing it needs a different technique, not a longer pattern.

    Asserted rather than described, so it cannot be mistaken for an oversight and a future fix
    has a test to flip."""
    assert check_coherence(
        [_LIVE_ASSUMPTION], ["The reset button is not shown until an entry exists."]
    ) == ()
    assert check_coherence(
        ["Assumed no calculation history is kept."],
        ["The calculation history is not stored between sessions, "
         "but it appears during a session."],
    ) == ()


def test_matching_is_contiguous_not_bag_of_words():
    """A bag-of-words test would convict this: both "reset" and "button" appear."""
    assert check_coherence(
        [_LIVE_ASSUMPTION], ["Reset the totals; the button clears the form."]
    ) == ()


def test_matching_is_over_TOKENS_not_substrings():
    """The collision class that killed ``_check_names_a_mechanism``'s allowlist — ``log``
    inside "logo", ``import`` inside "important". Tokenising makes it unreachable."""
    assert check_coherence(
        ["Assumed no login form is required."],
        ["The logo form factor is important on the landing page."],
    ) == ()


# ---------------------------------------------------------------------------
# The adversarial corpus, written AGAINST this design rather than to agree with
# it. The first version scored 5 false refusals here; the bar is zero, with the
# catches kept.
# ---------------------------------------------------------------------------

_COHERENT_CORPUS: tuple[tuple[list[str], list[str]], ...] = (
    (["Assumed no calculation history is kept.", "Assumed decimals are supported."],
     ["The calculator shows 5 for 2 + 3.", "Dividing by zero shows an error message."]),
    (["Assumed a reset button would be useful, but it is not needed for a first version."],
     ["The page shows the daily total."]),
    (["Assumed a search box might help; it is not required for now."],
     ["The list shows every entry."]),
    (["Assumed a clear error message is shown for invalid input."],
     ["The app launches without an error message.",
      "Entering letters shows an error message."]),
    (["Assumed the page refresh keeps the running total."],
     ["The total updates without a page refresh."]),
    (["Assumed the page refresh keeps the running total."],
     ["The total updates with no page refresh."]),
    (["Assumed the totals update live."],
     ["The counter increments without a full reload."]),
    (["Assumed a normal resizable window.", "Assumed no login is required."],
     ["The logo is displayed in the header.", "The window can be resized."]),
    (["Assumed page numbers are not needed."],
     ["The running total shows the number of glasses drunk today."]),
    (["Assumed the data is not stored between sessions."],
     ["The total resets when the page is reloaded.",
      "The app displays a chart of today's data points."]),
    (["Assumed no export is provided."],
     ["The report is displayed on screen.", "The totals are correct."]),
    (["Assumed the app does not include user accounts."],
     ["The user can add a glass by clicking the button.",
      "Accounts payable is shown in the ledger."]),
    ([], ["The project builds without errors."]),
    (["Assumed a plain, unstyled page is acceptable."],
     ["The page shows a running total."]),
    (["Assumed no sound effects are needed.", "Assumed a light colour scheme."],
     ["The page has no scroll bars.", "The effects of a bad entry are shown as an error."]),
    (["Assumed the timer does not run in the background."],
     ["The timer counts down from 25 minutes.", "The background is a soft grey."]),
    (["Assumed no keyboard shortcuts are provided."],
     ["The keyboard can be used to type into the entry box."]),
    (["Assumed printing is out of scope."],
     ["The print quality of the font is legible on one screen."]),
    (["Assumed the list does not support drag and drop."],
     ["Items can be reordered with the up and down buttons."]),
    (["Assumed there is no offline mode."],
     ["The page shows an error when the network is unavailable."]),
    (["Assumed a single page with no navigation menu."],
     ["Navigation between days uses arrows."]),
    (["Assumed no undo is required."], ["A required field shows a warning when empty."]),
    (["Assumed the totals are not rounded."],
     ["The totals are shown to two decimal places."]),
    (["Assumed images are not needed."],
     ["The page shows text only.", "The image of the logo is not displayed."]),
    (["Assumed a crash report screen is not needed."],
     ["The app launches without crashing.", "2 + 3 shows 5."]),
    (["Assumed it launches straight to the main screen."],
     ["The project builds without errors.",
      "The served page loads and displays its main content."]),
    ([_LIVE_ASSUMPTION], ["The page does not include a reset button."]),
    ([_LIVE_ASSUMPTION], ["The page never shows a reset button."]),
    ([_LIVE_ASSUMPTION], ["There is no reset button."]),
    ([_LIVE_ASSUMPTION], ["The page works without a reset button."]),
)

_CONTRADICTION_CORPUS: tuple[tuple[list[str], list[str]], ...] = (
    ([_LIVE_ASSUMPTION], [_LIVE_CRITERION]),
    (["Assumed no calculation history is kept."],
     ["The calculation history is listed under the keypad."]),
    (["Assumed the app does not include user accounts."],
     ["A user account can be created from the sign-up form."]),
    (["Assumed there is no dark mode."],
     ["A dark mode switch is shown in the settings panel."]),
    (["Assumed no keyboard shortcuts are provided."],
     ["Keyboard shortcuts jump to the next field."]),
    (["Assumed a progress bar is not required."],
     ["A progress bar fills as the daily goal is approached."]),
    (["Assumed no sound effects are needed."],
     ["A sound effect plays when a glass is added."]),
    (["Assumed the export button is out of scope."],
     ["The export button writes the totals to a file."]),
    (["Assumed no navigation menu is provided."],
     ["The navigation menu lists every day of the week."]),
    (["Assumed a dark mode toggle is provided."],
     ["The page does not include a dark mode toggle."]),
    (["Assumed the app does not show a weekly chart."],
     ["The weekly chart plots the last seven days."]),
    (["Assumed no goal setting is needed."],
     ["The goal setting screen stores a daily target."]),
    (["Assumed a print button is not needed."],
     ["The print button opens the browser print dialog."]),
    (["Assumed offline mode is omitted."],
     ["Offline mode keeps the last totals visible."]),
)


def test_zero_false_refusals_on_the_adversarial_corpus():
    """The precision half, and the one that decides whether this gate is shippable: refusing
    an ordinary plan is a worse failure than missing an unusual contradiction. Independent
    review measured 5 refusals here before the F1/F2 fixes."""
    refused = [
        (a, c, check_coherence(a, c)) for a, c in _COHERENT_CORPUS if check_coherence(a, c)
    ]
    assert not refused, f"the gate refused {len(refused)} coherent spec(s): {refused}"


def test_the_corpus_still_catches_what_it_should():
    """The recall half, so the test above cannot be satisfied by a gate that does nothing."""
    missed = [(a, c) for a, c in _CONTRADICTION_CORPUS if not check_coherence(a, c)]
    assert not missed, f"missed {len(missed)} planted contradiction(s): {missed}"


def test_the_coherent_corpus_test_is_not_vacuous():
    """Guard the guard: a gate that always returned () would pass the corpus test in perfect
    silence. Plant the live contradiction into every entry and require EVERY one to fire."""
    missed = [
        (a, c)
        for a, c in _COHERENT_CORPUS
        if not check_coherence([*a, _LIVE_ASSUMPTION], [*c, _LIVE_CRITERION])
    ]
    assert not missed, f"planted contradiction missed in {len(missed)} corpus entries"


def test_empty_and_blank_inputs_are_coherent_not_crashes():
    assert check_coherence([], []) == ()
    assert check_coherence(["  ", ""], ["   "]) == ()
    assert check_coherence([_LIVE_ASSUMPTION], []) == ()


def test_findings_are_deduplicated():
    """The overlapping frames must not report one disagreement three times — the operator
    reads this list."""
    findings = check_coherence([_LIVE_ASSUMPTION, _LIVE_ASSUMPTION], [_LIVE_CRITERION])
    assert len(findings) == 1, findings


def test_extraction_really_extracts():
    """Anti-vacuity for the frames themselves: a pattern that interpolated to something
    unmatchable would leave every test above green via the empty path."""
    assert extract_exclusions(_LIVE_ASSUMPTION) == (("reset", "button"),)
    assert extract_exclusions("Assumed decimals are supported.") == ()
    assert content_tokens("The reset button is here") == ("reset", "button")


def test_a_finding_cannot_be_built_without_naming_both_sides():
    """Structural rather than conventional: the dataclass has no defaults, so there is no way
    to construct a refusal reason that fails to name the two statements it refuses over. The
    first version allowed one (the undecidable arm) and that was the arm that had to go."""
    from dataclasses import MISSING, fields

    from shared.fleet.coherence import CoherenceFinding

    for f in fields(CoherenceFinding):
        assert f.default is MISSING and f.default_factory is MISSING, f.name


def test_refusal_message_is_plain_language_and_names_both_statements():
    """The operator reads this. It must quote the two sentences that disagree and carry no
    identifiers, tier names, or ticket numbers — none of which a non-developer can act on."""
    msg = refusal_message(check_coherence([_LIVE_ASSUMPTION], [_LIVE_CRITERION]))
    assert _LIVE_ASSUMPTION in msg and _LIVE_CRITERION in msg
    assert "reset button" in msg
    for jargon in ("tier", "behavior", "#1054", "criterion", "AcceptanceSpec", "None"):
        assert jargon not in msg, f"refusal text leaked {jargon!r}: {msg}"


# ===========================================================================
# PART 2 — through the real generate_plan
# ===========================================================================

_MARKER_COAUTHORED = "ONE document containing BOTH"
_MARKER_CRITERIA = "You are defining ACCEPTANCE CRITERIA"
_MARKER_ASSUMPTIONS = "A non-technical person asked for"
_MARKER_BUILD_PLAN = "Classify what KIND of software"
_MARKER_DECOMPOSE = "decomposing a software change request"

_ONE_TASK_JSON = json.dumps([{"task": "build-it", "prompt": "Build the thing."}])

_CONTRADICTING_CRITERIA = [
    {"text": "The page has a button that adds one glass to today's total.",
     "tier": "behavior", "check": "assert add_glass() increments the total"},
    {"text": _LIVE_CRITERION,
     "tier": "behavior", "check": "assert reset() sets the total to zero"},
]
_COHERENT_CRITERIA = [
    {"text": "The page has a button that adds one glass to today's total.",
     "tier": "behavior", "check": "assert add_glass() increments the total"},
    {"text": "The running total of glasses is displayed on the page.",
     "tier": "behavior", "check": "assert render() shows the total"},
]


def test_prompt_markers_are_real():
    """These markers route the fake below. A template edit that broke one would silently send
    every prompt down the fallback arm and quietly pass the flag tests."""
    for marker, template in (
        (_MARKER_COAUTHORED, _COAUTHORED_TEMPLATE),
        (_MARKER_CRITERIA, _CRITERIA_TEMPLATE),
        (_MARKER_ASSUMPTIONS, _ASSUMPTIONS_TEMPLATE),
    ):
        assert marker in template, marker
    # and the co-authored template must NOT be caught by the criteria marker, or the fake
    # would answer the one-pass prompt with the two-pass answer.
    assert _MARKER_CRITERIA not in _COAUTHORED_TEMPLATE


def _repo(tmp_path, name="myapp"):
    proj = tmp_path / "projects"
    (proj / name / ".git").mkdir(parents=True, exist_ok=True)
    return proj, name


class _Model:
    """A fake 14B that answers the SAME spec down either authoring path.

    That symmetry is the whole point: the only difference between the flag-on and flag-off
    runs below is the flag, so a difference in outcome cannot come from the fixture."""

    def __init__(self, criteria: list[dict], assumptions: list[str], *, surface="web",
                 coauthored: "str | None" = None):
        self.criteria = criteria
        self.assumptions = assumptions
        self.surface = surface
        self._coauthored_override = coauthored
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if _MARKER_COAUTHORED in prompt:
            if self._coauthored_override is not None:
                return self._coauthored_override
            return json.dumps({"assumptions": self.assumptions, "criteria": self.criteria})
        if _MARKER_CRITERIA in prompt:
            return json.dumps(self.criteria)
        if _MARKER_ASSUMPTIONS in prompt:
            return json.dumps(self.assumptions)
        if _MARKER_BUILD_PLAN in prompt:
            return json.dumps({"surface": self.surface, "candidates": [],
                               "language_hint": None, "complexity": "simple",
                               "components": []})
        if _MARKER_DECOMPOSE in prompt:
            return _ONE_TASK_JSON
        return "[]"

    def saw(self, marker: str) -> bool:
        return any(marker in p for p in self.prompts)


_GOAL = "a web page to track daily water intake, with a button to add a glass"


def test_gate_REFUSES_a_contradicting_plan_through_generate_plan(tmp_path):
    """The control, engaged. The plan is declined, nothing is compiled, and the operator is
    told which two sentences disagree."""
    proj, repo = _repo(tmp_path)
    model = _Model(_CONTRADICTING_CRITERIA, [_LIVE_ASSUMPTION])
    plan = generate_plan(_GOAL, repo, generate_fn=model, projects_dir=proj,
                         advanced_intake=True, coherence_gate=True)
    assert plan.ok is False
    assert plan.tasks == []
    assert _LIVE_ASSUMPTION in plan.message and _LIVE_CRITERION in plan.message


def test_the_IDENTICAL_defect_sails_through_when_the_sub_flag_is_off(tmp_path):
    """PRINCIPLE 12 — the toggle-off proof. Same goal, same fake, same model output; only the
    sub-flag differs. With it off the self-contradicting plan is offered exactly as it was on
    2026-07-22, which is what proves the refusal above comes from the gate and not from the
    fixture being unbuildable."""
    proj, repo = _repo(tmp_path)
    model = _Model(_CONTRADICTING_CRITERIA, [_LIVE_ASSUMPTION])
    plan = generate_plan(_GOAL, repo, generate_fn=model, projects_dir=proj,
                         advanced_intake=True, coherence_gate=False)
    assert plan.ok is True
    assert plan.tasks, "the plan compiled no tasks — the probe is measuring the wrong thing"
    assert _LIVE_ASSUMPTION in plan.spec.assumptions
    assert any(c.text == _LIVE_CRITERION for c in plan.spec.criteria), (
        "the contradicting criterion is absent with the flag off — this probe would go green "
        "against a gate that does nothing"
    )


def test_the_sub_flag_alone_engages_nothing(tmp_path):
    """A sub-flag may not open a capability inside a front that is itself off."""
    proj, repo = _repo(tmp_path)
    model = _Model(_CONTRADICTING_CRITERIA, [_LIVE_ASSUMPTION])
    plan = generate_plan(_GOAL, repo, generate_fn=model, projects_dir=proj,
                         advanced_intake=False, coherence_gate=True)
    assert plan.ok is True
    assert not model.saw(_MARKER_COAUTHORED), "single-pass authoring ran with the front off"


def test_toggle_off_is_byte_identical(tmp_path):
    """The standing bar. ``coherence_gate=False`` must leave the WHOLE spec — criteria,
    tiers, checks, assumptions, build signal, asset specs — identical to not passing the
    argument at all, in both flag states of the front above it."""
    proj, repo = _repo(tmp_path)
    for front in (True, False):
        off = generate_plan(_GOAL, repo,
                            generate_fn=_Model(_COHERENT_CRITERIA, ["Assumed no login."]),
                            projects_dir=proj, advanced_intake=front, coherence_gate=False)
        default = generate_plan(_GOAL, repo,
                                generate_fn=_Model(_COHERENT_CRITERIA, ["Assumed no login."]),
                                projects_dir=proj, advanced_intake=front)
        assert off.spec.to_dict() == default.spec.to_dict(), f"drift with front={front}"
        assert off.ok is default.ok is True


def test_single_pass_authoring_replaces_BOTH_calls_when_on(tmp_path):
    """The quality half, measured on the prompts the model actually received: one co-authored
    call, and neither of the two it replaces."""
    proj, repo = _repo(tmp_path)
    model = _Model(_COHERENT_CRITERIA, ["Assumed no login is required."])
    plan = generate_plan(_GOAL, repo, generate_fn=model, projects_dir=proj,
                         advanced_intake=True, coherence_gate=True)
    assert plan.ok is True
    assert model.saw(_MARKER_COAUTHORED)
    assert not model.saw(_MARKER_CRITERIA), "the separate criteria call still ran"
    assert not model.saw(_MARKER_ASSUMPTIONS), "the separate assumptions call still ran"
    # and the assumptions on the spec came from that ONE emission
    assert plan.spec.assumptions == ("Assumed no login is required.",)


def test_flag_off_still_makes_the_two_separate_calls(tmp_path):
    """The other direction of the same measurement — otherwise "no criteria call" above could
    mean the fake never routed anything."""
    proj, repo = _repo(tmp_path)
    model = _Model(_COHERENT_CRITERIA, ["Assumed no login is required."])
    generate_plan(_GOAL, repo, generate_fn=model, projects_dir=proj,
                  advanced_intake=True, coherence_gate=False)
    assert model.saw(_MARKER_CRITERIA) and model.saw(_MARKER_ASSUMPTIONS)
    assert not model.saw(_MARKER_COAUTHORED)


def test_an_unusable_coauthored_emission_falls_back_to_the_two_call_path(tmp_path):
    """Fail-SOFT on authoring (not fail-closed — no capability is being gated here): a junk
    single-pass emission must degrade to today's two calls, never to a thinner spec. The gate
    still runs afterwards, over whichever pair was produced."""
    proj, repo = _repo(tmp_path)
    model = _Model(_COHERENT_CRITERIA, ["Assumed no login is required."],
                   coauthored="I'm afraid I can't do that.")
    plan = generate_plan(_GOAL, repo, generate_fn=model, projects_dir=proj,
                         advanced_intake=True, coherence_gate=True)
    assert plan.ok is True
    assert model.saw(_MARKER_COAUTHORED)
    assert model.saw(_MARKER_CRITERIA) and model.saw(_MARKER_ASSUMPTIONS)
    assert [c.text for c in plan.spec.criteria][:2] == [c["text"] for c in _COHERENT_CRITERIA]
    assert plan.spec.assumptions == ("Assumed no login is required.",)


def test_the_gate_still_guards_the_fallback_path(tmp_path):
    """The guarantee may not depend on which authoring path ran: a contradiction produced by
    the TWO-call fallback is refused just the same."""
    proj, repo = _repo(tmp_path)
    model = _Model(_CONTRADICTING_CRITERIA, [_LIVE_ASSUMPTION], coauthored="not json")
    plan = generate_plan(_GOAL, repo, generate_fn=model, projects_dir=proj,
                         advanced_intake=True, coherence_gate=True)
    assert plan.ok is False
    assert _LIVE_CRITERION in plan.message


def test_a_card_driven_dispatch_is_NEVER_refused(tmp_path):
    """A battery card IS the spec, frozen so nights stay comparable. Refusing one would break
    a campaign rather than a plan the operator can re-issue — so the whole slice suppresses
    itself, exactly as S1's floors do. Both card signals are covered: the repo prefix here,
    and the override below."""
    proj, repo = _repo(tmp_path, "battery-b5-habit-web")
    model = _Model(_CONTRADICTING_CRITERIA, [_LIVE_ASSUMPTION])
    plan = generate_plan(_GOAL, repo, generate_fn=model, projects_dir=proj,
                         advanced_intake=True, coherence_gate=True)
    assert plan.ok is True, "the coherence gate refused a frozen battery card"
    assert not model.saw(_MARKER_COAUTHORED), "a frozen card's criteria were re-authored"


def test_a_card_with_an_override_is_also_suppressed(tmp_path):
    proj, repo = _repo(tmp_path)
    override = DecompositionOverride(
        tasks=[{"task": "build-page", "prompt": "build the page",
                "contract": {"creates": ["app/page.py"], "exports": []}}],
    )
    model = _Model(_CONTRADICTING_CRITERIA, [_LIVE_ASSUMPTION])
    plan = generate_plan(_GOAL, repo, generate_fn=model, projects_dir=proj,
                         advanced_intake=True, coherence_gate=True,
                         decomposition_override=override)
    assert plan.ok is True
    assert not model.saw(_MARKER_COAUTHORED)


def test_a_gate_that_CANNOT_RUN_refuses(tmp_path, monkeypatch):
    """Fail-closed in the other direction, and the ONLY refusal this slice makes that is not
    an established contradiction. A control that cannot verify its precondition blocks; it
    never renders a plan it could not check as though it had been checked."""
    proj, repo = _repo(tmp_path)

    def boom(*_a, **_k):
        raise RuntimeError("gate exploded")

    monkeypatch.setattr(acceptance._coherence, "check_coherence", boom)
    plan = generate_plan(_GOAL, repo,
                         generate_fn=_Model(_COHERENT_CRITERIA, ["Assumed no login."]),
                         projects_dir=proj, advanced_intake=True, coherence_gate=True)
    assert plan.ok is False
    assert plan.tasks == []
    assert "RuntimeError" in plan.message


def test_a_broken_gate_does_NOT_block_when_the_flag_is_off(tmp_path, monkeypatch):
    """Toggle-off sibling of the test above: the same explosive gate is unreachable with the
    sub-flag off, which is what makes "structurally absent when off" a checkable claim rather
    than a description."""
    proj, repo = _repo(tmp_path)

    def boom(*_a, **_k):
        raise RuntimeError("gate exploded")

    monkeypatch.setattr(acceptance._coherence, "check_coherence", boom)
    plan = generate_plan(_GOAL, repo,
                         generate_fn=_Model(_COHERENT_CRITERIA, ["Assumed no login."]),
                         projects_dir=proj, advanced_intake=True, coherence_gate=False)
    assert plan.ok is True


# ---------------------------------------------------------------------------
# The grammar-constrained path (#743's hook). Review noted the fakes above drive
# only the free-text arm, so nothing exercised the constrained one.
# ---------------------------------------------------------------------------


def test_the_grammar_constrained_path_authors_the_pair(tmp_path):
    """The #718/#743 hook, driven for real: when the structured emitter answers, the free-text
    co-authored call is never made and the spec still carries both halves from one emission."""
    proj, repo = _repo(tmp_path)
    model = _Model(_COHERENT_CRITERIA, ["Assumed no login is required."])
    schemas: list[str] = []

    def structured(prompt: str, schema_text: str) -> str:
        schemas.append(schema_text)
        if _MARKER_COAUTHORED in prompt:
            return json.dumps({"assumptions": ["Assumed no login is required."],
                               "criteria": _COHERENT_CRITERIA})
        return ""

    plan = generate_plan(_GOAL, repo, generate_fn=model, projects_dir=proj,
                         structured_generate_fn=structured,
                         advanced_intake=True, coherence_gate=True)
    assert plan.ok is True
    assert plan.spec.assumptions == ("Assumed no login is required.",)
    assert not model.saw(_MARKER_COAUTHORED), (
        "the free-text co-authored call ran even though the grammar path succeeded"
    )
    assert any('"assumptions"' in s and '"criteria"' in s for s in schemas), (
        "the composed co-authored schema never reached the structured hook"
    )


def test_the_grammar_path_refuses_a_contradiction_it_produced(tmp_path):
    """The gate must not care which emitter wrote the pair."""
    proj, repo = _repo(tmp_path)

    def structured(prompt: str, _schema: str) -> str:
        if _MARKER_COAUTHORED in prompt:
            return json.dumps({"assumptions": [_LIVE_ASSUMPTION],
                               "criteria": _CONTRADICTING_CRITERIA})
        return ""

    plan = generate_plan(_GOAL, repo,
                         generate_fn=_Model(_COHERENT_CRITERIA, ["Assumed no login."]),
                         projects_dir=proj, structured_generate_fn=structured,
                         advanced_intake=True, coherence_gate=True)
    assert plan.ok is False
    assert _LIVE_CRITERION in plan.message


def test_good_assumptions_with_junk_criteria_lose_the_coauthored_pass(tmp_path):
    """A KNOWN consequence of ``_grammar_first``'s usability predicate, pinned rather than left
    to be discovered: the co-authored emission is judged usable by its CRITERIA half, so an
    emission with fine assumptions and unparseable criteria falls back to the two-call path and
    the assumptions are re-asked. It costs no quality — but the single-context guarantee is
    lost for that plan, which is worth knowing at the ceremony and worth a test so that a
    future change to the predicate is a deliberate one."""
    proj, repo = _repo(tmp_path)
    model = _Model(_COHERENT_CRITERIA, ["Assumed no login is required."],
                   coauthored=json.dumps(
                       {"assumptions": ["Assumed no login is required."],
                        "criteria": "junk"}))
    plan = generate_plan(_GOAL, repo, generate_fn=model, projects_dir=proj,
                         advanced_intake=True, coherence_gate=True)
    assert plan.ok is True
    assert model.saw(_MARKER_ASSUMPTIONS), (
        "the assumptions were NOT re-asked — the documented fallback did not happen"
    )


def test_the_coauthored_schema_composes_both_halves():
    """The grammar-constrained shape and the free-text shape must be the same shape."""
    schema = coauthored_emission_json_schema(max_criteria=3, max_assumptions=2)
    assert schema["required"] == ["assumptions", "criteria"]
    assert schema["properties"]["criteria"]["maxItems"] == 3
    assert schema["properties"]["assumptions"]["maxItems"] == 2
    assert schema["additionalProperties"] is False


# ===========================================================================
# PART 3 — reachability: the control has one door
# ===========================================================================


def _runtime_py_files() -> list[Path]:
    repo = Path(__file__).resolve().parents[2]
    out: list[Path] = []
    for root in ("shared", "services", "launcher"):
        for f in (repo / root).rglob("*.py"):
            parts = set(f.parts)
            if parts & {"tests", "test", "__pycache__"}:
                continue
            if f.name.startswith("test_") or f.name == "conftest.py":
                continue
            out.append(f)
    return out


def test_the_gate_has_no_UNALIASED_second_call_site():
    """The structural claim, made checkable — and scoped honestly.

    "Dormant behind a flag" is worth exactly as many doors as the guarded code has, so a
    second call site would engage the refusal with the flag off and nothing else here would
    notice. This enumerates them from the AST of the whole runtime tree rather than asserting
    it.

    WHAT IT DOES NOT COVER (review finding F6): a call reached through an aliased import
    (``from ... import check_coherence as _cc``) or dynamic dispatch (``getattr``) is invisible
    to a name match. The claim is therefore "no un-aliased second call site", not "exactly one
    door" — written here rather than left as an overstatement in a report."""
    call_sites: list[tuple[str, str]] = []
    for path in _runtime_py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        enclosing: dict[int, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for child in ast.walk(node):
                    enclosing.setdefault(id(child), node.name)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if name == "check_coherence":
                call_sites.append((path.name, enclosing.get(id(node), "<module>")))
    assert call_sites == [("acceptance.py", "generate_plan")], (
        f"the coherence gate is reachable from {len(call_sites)} un-aliased runtime call "
        f"site(s): {call_sites} — every one of them must be behind the flag conjunction"
    )
