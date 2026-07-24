"""
Verdict-integrity guard for coordinator model prose (#946, from the #855 grading)
=================================================================================

The #855 first shadow-precision grading (2026-07-18) measured one failure class
in the coordinator: the 14B's drafted digest prose put a SUCCESS headline on
three non-successes (a STALLED run, an externally ABORTED run, and a
PARKED-HONEST run described as "passed all acceptance tests… fully functional").
The deterministic layer never drifted. This module is the LA-directed guard
(mature, not minimal — #855 c.2208): it makes the false-headline channel
structurally impossible and screens what remains, fail-closed.

Five layers (ticket #946):

1. STRUCTURAL SEVERANCE — :func:`compose_run_headline` composes the
   verdict-bearing headline DETERMINISTICALLY from harvest truth. Model prose is
   demoted to annotation under that headline; no model output can ever be the
   digest's claim of record.
2. VERDICT-ECHO CONTRACT — the drafting prompt (composed in
   ``heartbeat_cycle._draft``) supplies the verdict token and requires the draft
   to open with exactly ``"<VERDICT>: "``. :meth:`ProseGuard.validate_run_summary`
   refuses a draft whose echo is missing or mismatched.
3. BIDIRECTIONAL CONSISTENCY SCREEN — success-class claims are refused unless
   the verdict is SUCCEEDED; failure-class claims are refused when it is.
   Defense-in-depth behind layers 1–2, never the only lock.
4. PROVENANCE — the digest record keeps deterministic and model-authored text in
   SEPARATE fields (``run_headline`` vs ``model_prose`` + the ``model_drafted``
   flag); any future live renderer MUST lead with the deterministic headline and
   label the model span as model prose (§7.4 provenance honesty).
5. ONE DOOR — every model-authored span passes this module (run summaries via
   :meth:`validate_run_summary`, verdict-less annotations via
   :meth:`validate_annotation`). Future surfaces (C4 briefings, stall comments,
   proposal rationales) inherit the same gate; no per-surface reimplementation.

Fail-closed disposition: a refused draft is DROPPED — the deterministic skeleton
(and headline) stand alone. There is no rewrite path (a guard that edits model
text would itself be an unreviewed author). Refusals are journaled with the raw
rejected text (``model_prose_rejected``) so the #855 re-shadow window can
measure BOTH catch rate and false-refusal rate before any graduation ceremony.

The screen is deliberately biased toward refusal: "completed successfully" is
refused on a non-SUCCEEDED verdict even when its grammatical subject is a task,
because the measured failure mode is exactly this phrase standing where a
verdict belongs. A dropped-but-true sentence costs one cycle's color; a
published-but-false one costs operator trust. The lexicons are add-only and grow
via golden eval cases (evals/golden/coordinator.jsonl, kind ``prose_guard``).

No runtime off-switch exists — the guard is integrity machinery, not a
capability, so the weakest-lock form (a config flag) is deliberately absent.
The constructor's ``screen_enabled`` / ``echo_required`` parameters exist ONLY
so tests can prove the probes fail when the locks are off (security principle
12: every control is tested off); production construction takes the defaults.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, Sequence

# The fleet-run result vocabulary. Defined here (not imported from
# heartbeat_cycle, which imports THIS module) — a drift-lock test in
# test_coordinator_prose_guard.py pins these equal to heartbeat_cycle's.
RESULT_MERGED: "Final[str]" = "MERGED"
RESULT_PARKED: "Final[str]" = "PARKED"

__all__ = [
    "GuardDecision",
    "ProseGuard",
    "RunTruth",
    "VERDICT_INCOMPLETE",
    "VERDICT_PARKED",
    "VERDICT_SUCCEEDED",
    "VERDICTS",
    "compose_run_headline",
]

#: The three verdict tokens the guard recognizes. They mirror
#: ``coord_lifecycle.resolve_board_transition``'s semantics (the forged-Done
#: lock): SUCCEEDED requires oracle GREEN **and** merged; PARKED is any honest
#: park; everything else — stalled, externally aborted, scorecard missing — is
#: INCOMPLETE. The mapping is deliberately coarse: these are the only claims a
#: two-sentence operator summary is entitled to make.
VERDICT_SUCCEEDED: Final[str] = "SUCCEEDED"
VERDICT_PARKED: Final[str] = "PARKED"
VERDICT_INCOMPLETE: Final[str] = "INCOMPLETE"

VERDICTS: Final[frozenset[str]] = frozenset(
    {VERDICT_SUCCEEDED, VERDICT_PARKED, VERDICT_INCOMPLETE}
)


@dataclass(frozen=True)
class RunTruth:
    """The harvest leg's deterministic facts about one finished run.

    Computed ONCE per cycle in ``heartbeat_cycle._harvest_and_move`` from the
    same sources the board-move ruler uses (``oracle_passed`` only ever from the
    scorecard) and passed to BOTH the ruler and this guard — one source of
    truth, two consumers, no re-derivation."""

    run_id: str
    oracle_passed: bool
    merged: bool
    parked: bool

    def verdict(self) -> str:
        """The verdict token this run's facts support (see ``VERDICTS``)."""
        if self.oracle_passed and self.merged:
            return VERDICT_SUCCEEDED
        if self.parked:
            return VERDICT_PARKED
        return VERDICT_INCOMPLETE


def compose_run_headline(
    truth: RunTruth, outcomes: Sequence[tuple[str, str]]
) -> str:
    """Layer 1: the deterministic verdict headline for a harvested run.

    *outcomes* is ``(task, result)`` pairs exactly as the snapshot's
    ``latest_run`` leg carries them. Pure string composition over already-ruled
    facts — no model, no clock, no I/O — so the headline is reproducible in
    fixtures to the byte."""
    total = len(outcomes)
    merged_n = sum(1 for _, result in outcomes if result == RESULT_MERGED)
    parked_tasks = [task for task, result in outcomes if result == RESULT_PARKED]
    verdict = truth.verdict()

    detail: str
    if verdict == VERDICT_SUCCEEDED:
        detail = f"{merged_n}/{total} tasks merged, acceptance oracle green"
    elif verdict == VERDICT_PARKED:
        parked_at = f" at {parked_tasks[0]}" if parked_tasks else ""
        detail = f"{merged_n}/{total} tasks merged, parked{parked_at}"
    else:
        detail = f"{merged_n}/{total} tasks merged, run did not complete"
    return f"Run {truth.run_id}: {verdict} — {detail}"


@dataclass(frozen=True)
class GuardDecision:
    """One validation outcome. ``action`` is the journaled label:
    ``"accepted"``, or ``"rejected:<reason>"`` where reason is one of
    ``empty`` / ``echo-missing`` / ``echo-mismatch:<token>`` /
    ``claim:<lexicon-label>``."""

    accepted: bool
    action: str


#: Layer-3 success-class lexicon: claims a summary may make ONLY of a SUCCEEDED
#: run. Add-only; every addition ships a golden eval case. The first three are
#: the #855-measured failures verbatim-class.
_SUCCESS_CLAIMS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = tuple(
    (label, re.compile(pattern, re.IGNORECASE))
    for label, pattern in (
        # BOTH word orders. The original required the verb BEFORE the adverb, so
        # "successfully completed" matched nothing at all — measured on the
        # shipped guard 2026-07-23 at 56/56 adverb-first inversions ACCEPTED on
        # an oracle-FAILED run, against 0/24 for the verb-first controls. A total
        # blind spot, not a partial one, in the exact thing this screen exists to
        # catch. It is the same word-order inversion as coord-guard-008's
        # 2026-07-22 live miss, reopened at a different pattern: that incident
        # was closed for the noun-before-verb form and its sibling was never
        # swept for.
        #
        # The verb set is held IDENTICAL on both sides of the adverb. Two verbs
        # are deliberately absent and each exclusion is load-bearing:
        #
        #   `merged` — merging tasks is compatible with a failed run, and golden
        #   coord-guard-005 pins task-level "successfully merged" as ACCEPTED.
        #   Mirroring it measures 44.12% false suppression over the live 34-cycle
        #   window against a ratified 5% ceiling, versus 2.94% without.
        #
        #   `run` (the infinitive, beside `ran`) — a real gap, and NOT fixed here.
        #   Adding it refuses accurate failure prose this guard accepts today
        #   ("the suite could not run successfully": 6/6 constructed accurate
        #   cases refused), and it also matches the NOUN "run" before the adverb,
        #   refusing accurate task-level lines like "the run successfully merged
        #   three tasks". It therefore depends on the #1067 negation carve-out
        #   landing first, and is held with it. See #1067.
        (
            "completed-successfully",
            r"\b(?:complet\w*|finish\w*|ran)\s+successfully\b"
            r"|\bsuccessfully\s+(?:complet\w*|finish\w*|ran)\b"
            # The infinitive `run`, added with #1067's carve-out and not before:
            # alone it refused accurate prose the guard accepts today, and only
            # the carve-out buys that back ("the suite could not run
            # successfully" is ACCEPTED again with it in place).
            #
            # The lookbehinds matter. "run successfully" also matches the NOUN
            # "run" followed by the adverb, which would refuse accurate
            # task-level lines like "the run successfully merged three tasks" —
            # true of a failed run, and the carve-out cannot rescue them because
            # they are not negated-failure statements at all. Excluding a
            # preceding determiner keeps the verb reading and drops the noun one.
            r"|(?<!\bthe\s)(?<!\ba\s)(?<!\bthis\s)(?<!\bthat\s)"
            r"\brun\s+successfully\b",
        ),
        ("passed-all-tests", r"\bpass\w*\s+(?:all\s+)?(?:the\s+)?(?:acceptance\s+)?tests\b"),
        # noun-before-verb inversion of the claim above — the 2026-07-22
        # re-shadow window's live miss ("… acceptance tests passed" on an
        # oracle-FAILED run, accepted x3 cycles; #855 report of that date).
        # Deliberately NO negation carve-out: a lookbehind covers only one
        # adjacency ("no tests …") while the qualified forms ("no acceptance
        # tests passed") re-anchor past it — a carve-out that protects the rare
        # form and misses the likely one is worse than none. Negated-but-true
        # phrasings are refused by the same priced bias as
        # completed-successfully (golden coord-guard-009); loosening is a
        # ceremony decision.
        ("tests-passed", r"\b(?:acceptance\s+|unit\s+|all\s+)?tests?\s+(?:(?:have|had|were|all|are|is)\s+)?pass\w*\b"),
        ("fully-functional", r"\bfully\s+functional\b"),
        ("ready-for-use", r"\bready\s+(?:for|to)\s+use\b"),
        ("run-successful", r"\brun\s+(?:was\s+|is\s+)?(?:successful|a\s+success)\b|\bsuccessful\s+run\b|\brun\s+succeeded\b"),
        ("no-failures", r"\bno\s+(?:failures?|errors?|issues?)\b"),
    )
)

# ---------------------------------------------------------------------------
# The negated-failure carve-out (#1067): vocabulary DERIVED FROM RUN TRUTH
# ---------------------------------------------------------------------------
#
# Six designs were rejected before this one (#1067 c.2452/c.2456/c.2480/c.2509).
# They fall into two groups and BOTH failure modes are recorded here, because
# each reads as obviously-wrong only after someone has broken it.
#
#   v1-v4 searched for a negation MARKER near the claim and excused it. That
#   leaves the accept side OPEN: any construction the marker list does not
#   anticipate is accepted by absence. Broken by open-class polarity flippers
#   ("it is a myth that...") and by presupposition ("...until the retry"),
#   neither of which is enumerable.
#
#   v5-v6 required the text to be CONSUMED IN FULL by a closed grammar. Better,
#   and still broken — because a template with an OPEN SLOT is not closed.
#   Component names are open-class, so both left a slot accepting "any word-like
#   thing", and the attacks walked in through it:
#     v5: a segment nobody examined  ("...successfully. That statement is false.")
#     v6: a slot admitting a one-word reversal ("Untrue, all tasks were merged"),
#         and a subject slot admitting a NEGATIVE subject, so "None of the tasks
#         failed to complete successfully" — two negations making a positive —
#         fullmatched an accept form.
#
# The lesson that produced THIS design: the hole was always the slot, and the
# slot existed because the guard was guessing at vocabulary it could not know.
# It does not have to guess. The harvest leg already knows which tasks this run
# contained — deterministic facts computed once per cycle and handed to the
# board ruler and to this guard from one source. So the only variable position
# is filled from THAT RUN'S OWN TASK NAMES and from nothing else.
#
# "Untrue" is not a task name. Neither is "False", "Actually" or "Correction".
# The slot stops being a slot.
#
# WHAT CAN HONESTLY BE CLAIMED. The excuse requires a positive full-body match
# against a closed grammar. The grammar has THREE kinds of variable position and
# they are constrained differently — say all of them, because the short version
# of this sentence was written here and was WRONG, and the first correction of
# it then MISSED a category (the run-id slot), which is the same failure one
# notch quieter:
#
#   (a) slots bound to deterministic run truth — the harvested task names
#       (partitioned by result, filtered by _usable_terms) AND this run's own
#       run_id in the marked-as-status form. A wrong run id refuses.
#   (b) the counted-pass numbers — NOT bound to run truth. The guard holds no
#       test counts: RunTruth carries oracle_passed/merged/parked, and the
#       harvested outcomes carry (task, result), never totals. They are bounded
#       instead by _asserts_no_majority, which is a checkable arithmetic
#       predicate, not a fact about this run.
#   (c) everything else — literal.
#
# RETRACTED, and left here as a marker rather than deleted: an earlier version of
# this paragraph asserted that "every variable position is bound to deterministic
# run truth, so there is no position where arbitrary text is accepted." That was
# FALSE. The counted-pass clause had two free integers, and an independent cold
# pass accepted "only 999 out of 1000 unit tests passed" on a run where nothing
# merged and no test passed — a full-pass claim wearing a limiter, in the very
# claim family whose live miss is golden coord-guard-008.
#
# This is the THIRD over-broad safety argument on this ticket (v4's parity proof,
# v6's over-split proof, this one), each written in a register that reads as
# settled and therefore suppresses the hunt that finds the defect. The recurrence
# is the finding: on this surface, a sentence claiming a safety property is
# itself a defect risk, and the fix is to enumerate what is NOT covered rather
# than to summarise what is.
#
# Absent run vocabulary the carve-out grants FEWER excuses, never more: an empty
# term set means no sentence naming a component can be consumed at all.
# Fail-closed by construction rather than by vigilance.
#
# Cost: deliberately narrow. It buys back the measured live shape and little
# else, which is what c.2480 asked for. It can never refuse MORE than the
# pre-#1067 guard, because a body carrying a success claim was refused outright
# before this existed.

#: Only these two claim families have accurate negated forms worth buying back.
#: Every other success claim is refused outright on a non-SUCCEEDED verdict, so
#: no excuse path exists for them and none can be walked.
_EXCUSABLE_CLAIM_LABELS: Final[frozenset[str]] = frozenset(
    {"completed-successfully", "tests-passed"}
)

#: Sentence splitter. SENTENCES, not clauses: every sentence of the body must be
#: consumed, so nothing is left unexamined beside an excused claim (the v5 hole).
_SENTENCE_SPLIT: Final[re.Pattern[str]] = re.compile(r"(?<=[.!?])\s+")

#: Punctuation that makes assertoric force uncertain anywhere in the body. A
#: colon can introduce quoted or corrective material; a question mark makes a
#: rhetorical reading available. Non-ASCII interrogatives included — restricting
#: this to "?" left a one-character bypass.
_UNCERTAIN_PUNCT: Final[re.Pattern[str]] = re.compile("[:?？：⁇⁈⁉¿]")

#: Subjects a negated-failure statement may take: a LITERAL closed list, and
#: deliberately free of NEGATIVE subjects ("nothing", "none of the tasks").
#: Pairing a negative subject with a negator asserts the POSITIVE, which is
#: exactly how v6 was broken. There is no separate negative-subject form either:
#: it bought only constructed cases, and its existence is what made the mistake
#: reachable. Removing the surface beats guarding it.
_SUBJECT: Final[str] = (
    r"(?:the\s+(?:overall\s+|entire\s+|whole\s+|full\s+|final\s+|coding-fleet\s+)?"
    r"(?:run|build|suite|pipeline|dispatch|job|execution)|it)"
)

#: Negators that may GRANT the excuse; each negates the success verb it precedes.
_NEGATOR: Final[str] = (
    r"(?:did\s+not|does\s+not|didn['’]t|doesn['’]t"
    r"|was\s+not|wasn['’]t|were\s+not|weren['’]t"
    r"|has\s+not|hasn['’]t|had\s+not|hadn['’]t"
    r"|could\s+not|couldn['’]t|cannot|can['’]t|will\s+not|won['’]t"
    r"|never|failed\s+to|(?:was|were)\s+unable\s+to)"
)

_SUCCESS_VERB: Final[str] = r"(?:complete[sd]?|finish(?:e[sd])?|run|runs|ran)"

_TEST_NP: Final[str] = (
    r"(?:(?:the|all)\s+)?(?:acceptance\s+|unit\s+|integration\s+)?tests?"
)


#: Tokens that can perform a REVERSAL on their own, with no verb, when they lead
#: a sentence ("Untrue, all tasks were merged" is how v6 was broken). Task names
#: are open-class and come from a planner over the operator's own project goals,
#: so a run COULD legitimately contain a task called "false" or "invalid" — and
#: that task name would carry its reversal power straight into the one variable
#: position this grammar has.
#:
#: This list SUBTRACTS from the accepted vocabulary and can never add to it, so
#: it is not the enumerate-the-attackers mistake that sank v1-v4: a word missing
#: from here costs closure only for a run that ALSO happens to contain a task of
#: that exact name, whereas a word missing from a marker lexicon cost closure
#: universally. The binding to run truth is the primary control; this is
#: defence-in-depth behind it.
_REVERSAL_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "untrue", "false", "wrong", "incorrect", "nonsense", "lie", "myth",
        "mistaken", "misleading", "correction", "corrected", "retracted",
        "reversed", "inverted", "disregard", "ignore", "scratch", "actually",
        "no", "not", "never", "however", "but", "though", "although",
        "conversely", "instead", "rather", "joking", "kidding", "oops",
        "invalid", "bogus", "untrustworthy", "denied", "denies", "deny",
        "refuted", "disputed", "wrongly", "falsely",
        # Universal quantifiers, added after a cold pass: a task named
        # "all" turns the neutral clause into a universal success claim
        # ("...but all tasks were merged"). Same class as the reversal
        # words above -- a name carrying semantic power into the slot --
        # and the original list covered reversals but not quantifiers.
        "all", "every", "everything", "each", "both", "entire", "whole",
        "any", "none", "nothing", "everyone",
    }
)


def _usable_terms(terms: frozenset[str]) -> frozenset[str]:
    """The subset of this run's task names admissible as carve-out vocabulary.

    Drops anything that could function as a standalone reversal, plus anything
    that is not a bare identifier-shaped token (whitespace or punctuation in a
    term would let a single "name" smuggle in structure). Narrowing only."""
    usable = set()
    for term in terms:
        cleaned = term.strip()
        if len(cleaned) < 2:
            continue
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_\-]*", cleaned):
            continue
        if cleaned.casefold() in _REVERSAL_TOKENS:
            continue
        usable.add(cleaned)
    return frozenset(usable)


def _partition(
    task_results: Sequence[tuple[str, str]],
) -> tuple[frozenset[str], frozenset[str]]:
    """Split harvested outcomes into (merged, not-merged) name sets.

    Done HERE rather than at the call site so the two halves cannot be
    mismatched by a caller — the defect an independent pass found when the
    caller owned the split."""
    merged, unmerged = set(), set()
    for entry in task_results:
        if isinstance(entry, str) or not isinstance(entry, (tuple, list)):
            continue          # a bare name is not a record; contributes nothing
        try:
            task, result = entry
        except (TypeError, ValueError):
            continue          # malformed record contributes no vocabulary
        (merged if result == RESULT_MERGED else unmerged).add(str(task))
    # A name in BOTH sets means the record reported it merged AND not merged —
    # a retry, or a malformed harvest. One of the two claims it would license
    # is false whichever way the task really ended, and nothing here can tell
    # which. Drop it from both: unusable vocabulary, refused rather than
    # guessed.
    contested = merged & unmerged
    return frozenset(merged - contested), frozenset(unmerged - contested)


def _term_alt(terms: frozenset[str]) -> str:
    """A regex alternation over this run's own task names, escaped.

    The ONLY variable position in the grammar. An empty set — no run vocabulary,
    or every name filtered out — yields a pattern that can never match, so any
    sentence naming a component fails to be consumed and the carve-out refuses.
    Absent vocabulary NARROWS; it never widens."""
    usable = _usable_terms(terms)
    if not usable:
        return r"(?!x)x"
    return "(?:" + "|".join(
        sorted((re.escape(t) for t in usable), key=len, reverse=True)
    ) + ")"


def _build_sentence_form(
    merged: frozenset[str], unmerged: frozenset[str], run_id: str
) -> re.Pattern[str]:
    """Compile the closed sentence grammar for ONE run.

    The vocabulary is PARTITIONED BY RESULT, and that partition is
    load-bearing. An earlier cut fed merged-only names to every clause, which
    inverted the not-merged clause completely: "bill-splitter was parked" was
    ACCEPTED when bill-splitter had MERGED, and REFUSED when it really had
    parked. Every instantiation that clause could form was false and every
    true one was refused — a pure regression for that clause, caught by an
    independent pass. A name may now only appear in a clause whose predicate
    is TRUE of it.

    Variable positions and their bindings: merged/unmerged task names and
    *run_id* are bound to deterministic harvest truth; the counted-pass
    numbers are bound only by :func:`_asserts_no_majority`; everything else
    is literal."""
    m_term = _term_alt(merged)
    u_term = _term_alt(unmerged)
    rid = re.escape(run_id) if run_id else r"(?!x)x"
    def _listify(term: str) -> str:
        return rf"(?:the\s+)?{term}(?:\s*,\s*{term})*(?:\s*,?\s*and\s+{term})?"
    merged_list = _listify(m_term)
    unmerged_list = _listify(u_term)
    noun = r"(?:\s+(?:components?|tasks?|modules?|features?))?"

    clauses = (
        # negated failure statements
        rf"{_SUBJECT}\s+{_NEGATOR}\s+{_SUCCESS_VERB}\s+successfully",
        rf"{_SUBJECT}\s+{_NEGATOR}\s+successfully\s+{_SUCCESS_VERB}",
        # the ticket's qualified forms
        rf"no\s+{_TEST_NP}\s+(?:were\s+|have\s+|had\s+)?passed?",
        rf"none\s+of\s+{_TEST_NP}\s+(?:were\s+|have\s+)?passed?",
        rf"not\s+all\s+{_TEST_NP}\s+(?:were\s+|have\s+)?passed?",
        rf"only\s+\d+\s+(?:out\s+)?of\s+\d+\s+{_TEST_NP}\s+passed?",
        rf"{_TEST_NP}\s+{_NEGATOR}\s+pass(?:ed)?",
        # neutral clauses — every open position bound to run truth
        rf"{_SUBJECT}(?:\s+{rid})?\s+is\s+marked\s+as\s+"
        r"(?:incomplete|parked|failed|stalled|blocked)",
        rf"{merged_list}{noun}\s+(?:(?:were|was|have\s+been)\s+)?merged",
        rf"{unmerged_list}{noun}\s+(?:were|was)\s+"
        r"(?:not\s+run|not\s+merged|skipped|paused|parked)",
    )
    clause = rf"(?:{'|'.join(clauses)})"
    sentence = (
        rf"{clause}"
        rf"(?:\s*(?:,\s*)?(?:but|and|so|yet|however|although|though|while|"
        rf"whereas)\s+{clause})*\.?"
    )
    return re.compile(sentence, re.IGNORECASE)


#: Counted-form scanner, applied to the sentence AFTER it matches. Kept separate
#: from the grammar because the clause pattern repeats for coordinated clauses,
#: and named groups cannot repeat inside one expression — an earlier cut used
#: them and failed to compile at all.
_COUNTED_PASS: Final[re.Pattern[str]] = re.compile(
    r"only\s+(\d+)\s+(?:out\s+)?of\s+(\d+)", re.IGNORECASE
)


def _asserts_no_majority(sentence: str) -> bool:
    """Every counted form in *sentence* must assert that NO MAJORITY passed.

    Named for what the arithmetic does. It was called ``_asserts_a_minority``
    while implementing ``num * 2 <= den``, which accepts exactly half — the
    docstring said "at most half" and the name said "minority", and on this
    surface names have been load-bearing. The behaviour is deliberate
    ("only 5 of 10 tests passed" is an accurate failure statement); the name
    was the wrong half of the mismatch.

    The guard cannot verify counts — it holds no test totals — so this is the one
    variable position not bound to run truth, and it needs a bound of its own.
    An earlier cut required only ``num < den``, which an independent cold pass
    broke immediately: "only 999 out of 1000 unit tests passed" satisfied it and
    was ACCEPTED on a run where nothing merged and no test passed. The limiter
    word does no work at that ratio; the sentence reads as 99.9% success.

    ``num * 2 <= den`` is the bound, and it is a judgement, not a measurement:
    a claim that at most half the tests passed cannot be read as a success
    claim, whichever half it is. The ticket's own example ("only 2 of 9 tests
    passed") clears it; "only 8 of 9" and "only 999 of 1000" do not. Harm is
    continuous in the ratio, so any line here is a choice — this one is stated
    rather than buried, and it errs toward refusal.

    Fail-closed on anything unparseable."""
    for num, den in _COUNTED_PASS.findall(sentence):
        try:
            if int(num) * 2 > int(den):
                return False
        except (TypeError, ValueError):
            return False
    return True


def _claim_is_excused(
    body: str,
    merged: frozenset[str],
    unmerged: frozenset[str],
    run_id: str,
) -> bool:
    """True only if EVERY sentence of *body* is consumed in full by the closed
    grammar built from this run's own facts.

    Resolved as a module global by :meth:`ProseGuard._screen` at CALL time, so a
    principle-12 toggle that patches this name reaches the live code path — a
    probe captured at import would be a no-op that passes against the bug."""
    if _UNCERTAIN_PUNCT.search(body):
        return False
    form = _build_sentence_form(merged, unmerged, run_id)
    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(body.strip()) if s.strip()]
    if not sentences:
        return False
    for sentence in sentences:
        if form.fullmatch(sentence) is None:
            return False
        if not _asserts_no_majority(sentence):
            return False
    return True


#: Layer-3 failure-class lexicon: claims refused when the verdict IS SUCCEEDED
#: (the pessimistic contradiction — unmeasured to date, screened symmetrically).
_FAILURE_CLAIMS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = tuple(
    (label, re.compile(pattern, re.IGNORECASE))
    for label, pattern in (
        ("failure-word", r"\b(?:parked|aborted|stalled|failed|failure)\b"),
        ("did-not-complete", r"\b(?:did\s+not|didn'?t|never)\s+(?:pass|merge|complete|finish)\b"),
        ("was-not-done", r"\b(?:was|were)\s*(?:not|n'?t)\s+(?:completed|merged|run|passed)\b"),
    )
)


class ProseGuard:
    """Layers 2 + 3: the fail-closed validator every model-authored span passes.

    Stateless and cheap — construct once per process (``heartbeat_cycle``
    holds a module-level default) or per test. The constructor parameters
    exist ONLY for principle-12 toggle tests; production uses the defaults."""

    def __init__(
        self,
        *,
        screen_enabled: bool = True,
        echo_required: bool = True,
        negation_carve_out: bool = True,
    ) -> None:
        self._screen_enabled = screen_enabled
        self._echo_required = echo_required
        self._negation_carve_out = negation_carve_out

    # ------------------------------------------------------------------
    # Run summaries (verdict context exists → echo + screen)
    # ------------------------------------------------------------------

    def validate_run_summary(
        self,
        truth: RunTruth,
        text: str,
        *,
        task_results: Sequence[tuple[str, str]] = (),
    ) -> GuardDecision:
        """Validate a drafted run summary against the run's deterministic truth.

        *task_results* are THIS run's harvested ``(task, result)`` pairs —
        exactly the shape ``compose_run_headline`` takes, from the one harvest
        computation. They are the ONLY vocabulary the #1067 carve-out accepts
        in a variable position, and the guard PARTITIONS them itself so a
        caller cannot mismatch the halves: merged names may only appear in a
        merged claim, non-merged names only in a not-run/skipped/parked one.
        Passing the pairs rather than two lists is deliberate — an earlier cut
        took bare names, and the caller supplied merged-only names to every
        clause, which inverted the not-merged clause entirely.

        Omitting them is safe in the fail-closed direction: the carve-out then
        cannot consume any sentence naming a component, so it excuses less."""
        stripped = text.strip()
        if not stripped:
            return GuardDecision(False, "rejected:empty")

        verdict = truth.verdict()
        if self._echo_required:
            if not stripped.startswith(f"{verdict}:"):
                for other in VERDICTS - {verdict}:
                    if stripped.startswith(f"{other}:"):
                        return GuardDecision(
                            False, f"rejected:echo-mismatch:{other}"
                        )
                return GuardDecision(False, "rejected:echo-missing")

        return self._screen(
            verdict, stripped, _partition(task_results), truth.run_id
        )

    # ------------------------------------------------------------------
    # Verdict-less annotations (proposal descriptions and future spans)
    # ------------------------------------------------------------------

    def validate_annotation(
        self, text: str, *, task_results: Sequence[tuple[str, str]] = ()
    ) -> GuardDecision:
        """Validate model prose that has NO run verdict of its own (today: the
        redispatch-proposal description — its subject is a PARKED task, so
        success-class claims are refused outright; failure words are its
        legitimate vocabulary).

        The #1067 carve-out applies here too, so the same sentence is not
        accepted at one door and refused at the other. That is sound because the
        carve-out never consults the verdict: it recognises a whole
        negated-failure statement, which is not a success claim under ANY
        verdict.

        There is no *run_id* here, so the run-id-bearing neutral form can never
        match at this door. It does NOT follow that this door excuses less in
        production: ``heartbeat_cycle`` passes the same harvested task names to
        both doors, so the vocabulary is identical. An earlier version of this
        docstring claimed a "strictly less" property on the strength of the
        parameter DEFAULT, which is a docstring describing wiring rather than
        contract — the exact rot coding_standards names."""
        stripped = text.strip()
        if not stripped:
            return GuardDecision(False, "rejected:empty")
        if self._screen_enabled:
            for label, pattern in _SUCCESS_CLAIMS:
                for match in pattern.finditer(stripped):
                    if (
                        self._negation_carve_out
                        and label in _EXCUSABLE_CLAIM_LABELS
                        and _claim_is_excused(
                            stripped, *_partition(task_results), ""
                        )
                    ):
                        continue
                    return GuardDecision(False, f"rejected:claim:{label}")
        return GuardDecision(True, "accepted")

    # ------------------------------------------------------------------

    def _screen(
        self,
        verdict: str,
        text: str,
        vocab: tuple[frozenset[str], frozenset[str]] = (frozenset(), frozenset()),
        run_id: str = "",
    ) -> GuardDecision:
        if not self._screen_enabled:
            return GuardDecision(True, "accepted")
        if verdict != VERDICT_SUCCEEDED:
            claims = _SUCCESS_CLAIMS
        else:
            claims = _FAILURE_CLAIMS
        # The echo prefix itself must not trip the screen (e.g. "PARKED: …"
        # contains a failure word by construction) — strip a verdict-token
        # prefix, and ONLY that, before screening.
        body = text
        for token in VERDICTS:
            prefix = f"{token}:"
            if text.startswith(prefix):
                body = text[len(prefix):]
                break
        for label, pattern in claims:
            for match in pattern.finditer(body):
                if (
                    self._negation_carve_out
                    and claims is _SUCCESS_CLAIMS
                    and label in _EXCUSABLE_CLAIM_LABELS
                    and _claim_is_excused(body, vocab[0], vocab[1], run_id)
                ):
                    continue
                return GuardDecision(False, f"rejected:claim:{label}")
        return GuardDecision(True, "accepted")
