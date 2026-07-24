"""Deterministic, three-valued truth oracle for drafted coordinator prose (#1079).

The words layer's ground truth. The ratified criteria
(``docs/governance/coordinator_graduation_criteria_2026-07-23.md`` §3) define it
exactly: *a statement is false iff the scorecard contradicts it*. This module is
that definition made mechanical — it extracts the CLAIMS a statement makes, gives
each a polarity, and compares them to :class:`~shared.grading.run_facts.RunFacts`.

WHY IT IS NOT THE GUARD, AND MUST NOT BE
----------------------------------------
:mod:`shared.coordinator.prose_guard` and this module read similar English and
would be trivially confusable — but they answer different questions in opposite
failure directions, and collapsing them would make the measured catch rate a
tautology (a guard graded by its own lexicon catches 100% by construction).

* The GUARD decides *may this text be published*. It must fail CLOSED: when the
  negation structure is ambiguous it REFUSES. That bias is priced and deliberate.
* This ORACLE decides *is this text true*. It fails to :attr:`TruthValue.UNDETERMINED`:
  when the structure is ambiguous it ABSTAINS, and the abstention is reported as a
  residual rather than resolved by guessing.

Abstention is what makes the instrument honest. The #1067 guard revisions (v1
clause-position, v2 governing-negation, v3 negator-counting) each failed on a
litotes class the next reviewer found, because a guard has no third answer. The
oracle does, so it never has to bluff: a statement it cannot deterministically
adjudicate is excluded from BOTH the catch-rate and false-suppression numerators
and surfaced by count, so a reader can see how much of the window was machine-
decidable.

WHAT IT DELIBERATELY DOES NOT JUDGE
-----------------------------------
Only the three predicates below are decidable from a scorecard. Prose can be
*wrong about mechanism* while contradicting no scorecard field — the 07-22 window
holds one such case ("did not complete all planned tasks" on a run where all six
tasks merged and the acceptance exam failed). That is a quality defect, not a
falsehood under the ratified definition, and this module reports it as neither.
Widening the definition is a criteria change, not a code change.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Final

from shared.coordinator.prose_guard import VERDICTS
from shared.grading.run_facts import RunFacts

__all__ = [
    "ClaimAtom",
    "OracleVerdict",
    "Predicate",
    "TruthValue",
    "adjudicate",
]


class TruthValue(Enum):
    """A statement's truth against the scorecard."""

    TRUE = "true"
    """Every claim extracted is consistent with the scorecard (at least one claim
    was extracted — a statement making NO decidable claim is UNDETERMINED, not
    vacuously true)."""

    FALSE = "false"
    """At least one extracted claim is contradicted by the scorecard."""

    UNDETERMINED = "undetermined"
    """No decidable claim was found, or a claim's polarity could not be resolved
    deterministically. Excluded from every rate's numerator; reported by count."""


class Predicate(Enum):
    """The facts a scorecard can settle, and therefore the only ones a statement
    can be adjudicated against."""

    ORACLE_PASSED = "oracle_passed"
    """The job-level acceptance oracle passed (``evidence.oracle_status``)."""

    ALL_MERGED = "all_merged"
    """EVERY task in the run merged. Distinct from the ruler's ``merged`` flag,
    which is ``any``: prose overwhelmingly makes the universal claim."""

    RUN_SUCCEEDED = "run_succeeded"
    """The run as a whole succeeded — oracle passed AND something merged, the
    same conjunction :meth:`~shared.coordinator.prose_guard.RunTruth.verdict`
    requires for ``SUCCEEDED``."""


@dataclass(frozen=True)
class ClaimAtom:
    """One claim a statement makes: a predicate, the polarity asserted, and the
    text that carried it."""

    predicate: Predicate
    label: str
    asserted: bool
    """``True`` = the statement asserts the predicate holds; ``False`` = it asserts
    the predicate does NOT hold (a governing verb-negation was resolved)."""
    span: str


@dataclass(frozen=True)
class OracleVerdict:
    """The adjudication of one statement against one run's facts."""

    truth: TruthValue
    atoms: tuple[ClaimAtom, ...] = ()
    contradictions: tuple[str, ...] = ()
    """Human-legible ``<predicate>: asserted X, scorecard says Y`` lines — the
    evidence for a :attr:`TruthValue.FALSE`, so a verdict is never a bare label."""
    reason: str = ""
    """Why an UNDETERMINED was returned (``no-decidable-claim`` /
    ``ambiguous-negation``); empty otherwise."""


# ---------------------------------------------------------------------------
# Clause segmentation
#
# A negation binds within its clause. Splitting on sentence punctuation, commas,
# and the subordinating/contrastive conjunctions below keeps "the pipeline never
# stalled" from laundering "so the run finished successfully" — the exact
# laundering the #1067 review corpus was built to expose. Coordinating "and" is
# NOT a boundary: "merged and tested" is one predicate list, and splitting it
# would drop claims.
# ---------------------------------------------------------------------------

_CLAUSE_BOUNDARY: Final[re.Pattern[str]] = re.compile(
    r"[.;:]|,|\s+(?:but|however|although|though|whereas|while|yet|so|therefore|"
    r"thus|because|since|despite|hence)\s+",
    re.IGNORECASE,
)

#: Sentence boundaries only. Clause splitting is what lets a negator stop
#: laundering a neighbouring claim — but it can also SEVER a governing negator
#: from its claim across a parenthetical ("the run did not, despite the earlier
#: concern, fail to complete successfully" puts "not" and "fail to" in different
#: comma-clauses, leaving the inner negator looking single and the claim reading
#: as an honest negative). Polarity is therefore cross-checked at sentence scope,
#: where a parenthetical cannot hide the outer negator.
_SENTENCE_BOUNDARY: Final[re.Pattern[str]] = re.compile(r"[.;:]")

# ---------------------------------------------------------------------------
# Negation
#
# VERB-negators only, and only when they PRECEDE the claim span inside its
# clause. Determiner negation of a NOUN ("with no errors", "without issues",
# "no regressions remained") does not negate a success verb — treating it as
# though it did is precisely the v1 defect the review corpus locked, and here it
# would invert true statements into reported falsehoods.
# ---------------------------------------------------------------------------

_VERB_NEGATOR: Final[re.Pattern[str]] = re.compile(
    r"\b(?:not|never|cannot)\b|\w+n[’']t\b|\b(?:un(?:able|successful)|"
    r"fail(?:s|ed|ing)?)\s+to\b",
    re.IGNORECASE,
)

#: Claim patterns, per predicate. Each is anchored on the assertion's VERB, so a
#: noun phrase alone never mints a claim. Add-only; every addition ships a case in
#: the module's test.
_CLAIM_PATTERNS: Final[tuple[tuple[Predicate, str, re.Pattern[str]], ...]] = tuple(
    (predicate, label, re.compile(pattern, re.IGNORECASE))
    for predicate, label, pattern in (
        (
            Predicate.RUN_SUCCEEDED,
            "completed-successfully",
            r"\b(?:complet\w*|finish\w*|ran|run)\s+successfully\b",
        ),
        (
            Predicate.RUN_SUCCEEDED,
            "run-successful",
            r"\brun\s+(?:was\s+|is\s+)?(?:successful|a\s+success)\b"
            r"|\bsuccessful\s+run\b|\brun\s+succeeded\b",
        ),
        (Predicate.RUN_SUCCEEDED, "fully-functional", r"\bfully\s+functional\b"),
        (Predicate.RUN_SUCCEEDED, "ready-for-use", r"\bready\s+(?:for|to)\s+use\b"),
        (
            Predicate.ORACLE_PASSED,
            "tests-passed",
            r"\b(?:acceptance\s+|unit\s+|all\s+|the\s+)*tests?\s+"
            r"(?:(?:have|had|were|are|is|all)\s+)*pass(?:e[sd]|ing)?\b",
        ),
        (
            Predicate.ORACLE_PASSED,
            "passed-tests",
            r"\bpass(?:e[sd]|ing)?\s+(?:all\s+)?(?:the\s+)?"
            r"(?:acceptance\s+|unit\s+)?tests?\b",
        ),
        (
            Predicate.ORACLE_PASSED,
            "oracle-green",
            r"\b(?:acceptance\s+)?oracle\s+(?:was\s+|is\s+)?green\b",
        ),
        (
            Predicate.ALL_MERGED,
            "all-merged",
            r"\b(?:all|every|each)\s+(?:\w+[\s,]+){0,5}?merged\b",
        ),
        (
            Predicate.ALL_MERGED,
            "everything-merged",
            r"\beverything\s+(?:\w+\s+){0,3}?merged\b",
        ),
    )
)


def _clause_spans(sentence: str) -> list[tuple[int, str]]:
    """*sentence* split at :data:`_CLAUSE_BOUNDARY` into ``(offset, clause)``.

    Offsets are carried rather than recovered with ``str.find``: a sentence that
    repeats a clause would otherwise resolve the second occurrence to the first
    one's position and evaluate its polarity against the wrong preceding text."""
    spans: list[tuple[int, str]] = []
    cursor = 0
    for boundary in _CLAUSE_BOUNDARY.finditer(sentence):
        clause = sentence[cursor : boundary.start()]
        if clause.strip():
            spans.append((cursor, clause))
        cursor = boundary.end()
    trailing = sentence[cursor:]
    if trailing.strip():
        spans.append((cursor, trailing))
    return spans


def _polarity(clause_preceding: str, sentence_preceding: str) -> bool | None:
    """The polarity asserted for a claim, from the text preceding it.

    ``True`` = asserted; ``False`` = negated; ``None`` = ambiguous, abstain.

    TWO OR MORE governing verb-negators anywhere before the claim IN ITS SENTENCE
    is the litotes parity trap ("did not fail to complete successfully" is a
    POSITIVE claim wearing two negators) that defeated three guard revisions in a
    row. The oracle refuses to guess its parity and abstains. The sentence scope
    is what makes that refusal robust: counting inside the comma-clause alone lets
    a parenthetical hide the outer negator and the claim reads as a plain
    negative.

    Below that, exactly one negator in the claim's own CLAUSE is a plain negation,
    and none is a plain assertion — clause scope here, because a negator in a
    neighbouring clause ("the pipeline never stalled so the run finished
    successfully") governs its own verb, not this claim's."""
    if len(_VERB_NEGATOR.findall(sentence_preceding)) >= 2:
        return None
    return not _VERB_NEGATOR.search(clause_preceding)


def _extract(text: str) -> tuple[list[ClaimAtom], bool]:
    """Claim atoms in *text*, plus whether any claim was dropped as ambiguous."""
    atoms: list[ClaimAtom] = []
    ambiguous = False
    for sentence in _SENTENCE_BOUNDARY.split(text):
        for clause_at, clause in _clause_spans(sentence):
            for predicate, label, pattern in _CLAIM_PATTERNS:
                for match in pattern.finditer(clause):
                    asserted = _polarity(
                        clause[: match.start()],
                        sentence[: clause_at + match.start()],
                    )
                    if asserted is None:
                        ambiguous = True
                        continue
                    atoms.append(
                        ClaimAtom(
                            predicate=predicate,
                            label=label,
                            asserted=asserted,
                            span=match.group(0).strip(),
                        )
                    )
    return atoms, ambiguous


def _fact(predicate: Predicate, facts: RunFacts) -> bool:
    if predicate is Predicate.ORACLE_PASSED:
        return facts.oracle_passed
    if predicate is Predicate.ALL_MERGED:
        return facts.all_merged
    return facts.oracle_passed and facts.any_merged


def strip_verdict_echo(text: str) -> str:
    """*text* without its leading ``"<VERDICT>: "`` echo.

    The echo is deterministic scaffolding the drafting contract requires, not a
    model claim; screening it would let the token ``PARKED`` read as a statement
    about the run. Mirrors the equivalent strip in
    :meth:`shared.coordinator.prose_guard.ProseGuard._screen`."""
    stripped = text.strip()
    for token in VERDICTS:
        prefix = f"{token}:"
        if stripped.startswith(prefix):
            return stripped[len(prefix):].strip()
    return stripped


def adjudicate(text: str, facts: RunFacts) -> OracleVerdict:
    """Adjudicate *text* against *facts* — the criteria §3 ground-truth function.

    FALSE the moment any extracted claim contradicts the scorecard; TRUE when at
    least one claim was extracted and none contradicts; UNDETERMINED when nothing
    decidable was said or a polarity was ambiguous. A contradiction always wins
    over an abstention elsewhere in the same statement: one false clause makes the
    statement false regardless of how much true material surrounds it."""
    body = strip_verdict_echo(text)
    atoms, ambiguous = _extract(body)

    contradictions = [
        f"{atom.predicate.value}: statement asserts "
        f"{'TRUE' if atom.asserted else 'FALSE'} via {atom.span!r}, "
        f"scorecard says {_fact(atom.predicate, facts)}"
        for atom in atoms
        if atom.asserted is not _fact(atom.predicate, facts)
    ]
    if contradictions:
        return OracleVerdict(
            TruthValue.FALSE, tuple(atoms), tuple(contradictions)
        )
    if ambiguous:
        return OracleVerdict(
            TruthValue.UNDETERMINED, tuple(atoms), reason="ambiguous-negation"
        )
    if not atoms:
        return OracleVerdict(
            TruthValue.UNDETERMINED, reason="no-decidable-claim"
        )
    return OracleVerdict(TruthValue.TRUE, tuple(atoms))
