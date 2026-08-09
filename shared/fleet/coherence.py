"""Deterministic coherence gate over an authored (assumptions, criteria) pair (#1054).

WHY THIS EXISTS — the plan that contradicted itself.
----------------------------------------------------
A live dispatch produced a spec whose assumptions said *"Assumed a reset button is not
needed"* while its acceptance criteria said *"The web page includes a reset button to reset
the daily water intake counter to zero."* One document told the coder both that a capability
was out of scope and that it was a graded requirement. The two statements came from two
separate model calls that never saw each other's output.

The authoring fix (one pass carrying both jobs, :data:`~shared.fleet.acceptance.
_COAUTHORED_TEMPLATE`) is the quality half. **This module is the guarantee half**: a
deterministic check that refuses the plan when the two halves disagree, so a future model
regression cannot re-open the defect. A prompt is vigilance; this is the control.

THE CONTRACT — one finding, and the refusals it does NOT make.
--------------------------------------------------------------
This gate produces exactly one kind of finding: :data:`KIND_CONTRADICTION`, an established
disagreement between the two sides. **Everything it cannot establish, it passes**, and the
plan proceeds exactly as it would if this module did not exist.

That is narrower than the first shipped version, which also refused when a statement matched
an exclusion frame but named nothing checkable ("Assumed it is not needed"). That arm was
REMOVED, for a structural reason and a measured one:

* **Structurally it could never catch anything.** If the excluded subject is unnamed there is
  nothing to match against any criterion, so the arm could only ever produce a blanket
  refusal — never a contradiction. It was not a verification failure detector; it was a
  refusal with no evidence behind it.
* **Its real trigger turned out to be punctuation, not vagueness.** :data:`_SUBJ` cannot span
  a comma or semicolon, so an ordinary two-clause assumption — *"Assumed a reset button would
  be useful, but it is not needed for a first version."* — forced the earliest match to start
  at the pronoun, yielding an empty subject and refusing a perfectly coherent plan. The same
  sentence with a dash instead of a comma passed. A parse artefact was being surfaced as a
  semantic verdict, on the REFUSE side, and the gate could not tell that case apart from a
  genuinely vague one because the distinguishing words were outside the span by construction.

The correction to the reasoning matters more than the code change. "Refuse when you cannot
decide" is sound; the mistake was calling a failure to PARSE a failure to VERIFY. The line
that actually holds:

* the gate cannot RUN  ⇒ the caller refuses (``acceptance.generate_plan``'s ``except`` arm);
* the gate runs and ESTABLISHES a contradiction  ⇒ refuse;
* everything else ⇒ proceed, and the honest name for it is a RECALL LIMIT, not a
  verification success. The limits below are that list, and they are not small.

HOW A CONTRADICTION IS DECIDED — three steps, and the middle one is the discriminator.
--------------------------------------------------------------------------------------
1. **Does a statement EXCLUDE something, and WHAT?** :data:`_CONVICTING_FRAMES` are negation
   frames that each *capture a subject span* ("no X is needed", "X is not required", "does
   not include X", "X is out of scope", "there is no X", "never shows X"). A statement
   matching no frame makes no exclusion claim and constrains nothing.
2. **Does the other side REQUIRE that subject?** The captured subject is normalised to
   content tokens and must appear as a **contiguous token subsequence** of the other
   statement. This is the precision surface: a finding needs BOTH an exclusion frame AND the
   excluded phrase appearing, in order, on the other side.
3. **Does the other side exclude it too?** If so the two AGREE and nothing is reported. This
   step reads the WIDER :data:`_SEE_THROUGH_FRAMES` — see below.

Cross-side only: assumption-excludes × criterion-requires, and the reverse. Two criteria
disagreeing with each other is a different defect class and is deliberately not decided here.

WHY THERE ARE TWO FRAME SETS — the same words, opposite failure directions.
---------------------------------------------------------------------------
An earlier version used ONE set for both jobs and convicted on manner adverbials: *"The app
launches without an error message"* against *"Assumed a clear error message is shown for
invalid input"* — two compatible statements, one refused plan. (This file's own
``_CRITERIA_TEMPLATE`` primes the model with "smoke = it launches without crashing", so that
phrasing is not an edge case; it is house style.)

The diagnosis is that ``without X`` and a bare clause-final ``no X`` do not merely LOCATE a
subject — the frame itself supplies the judgement "X is excluded", and that judgement is an
author-written assumption about English, which is precisely the class
``_check_names_a_mechanism`` was withdrawn for. The phrase match cannot rescue it, because
the captured subject is genuine statement vocabulary.

So the sets are split by what a false positive COSTS:

* **Convicting** (step 1): a false positive REFUSES a coherent plan. Conservative — only
  frames where the negation attaches unambiguously to the noun as a capability exclusion.
* **See-through** (step 3): a false positive merely SUPPRESSES a conviction, i.e. misses a
  catch, which is today's behaviour. Generous — it keeps ``without X`` and bare ``no X``, so
  *"The page works without a reset button"* is still recognised as AGREEING with an
  assumption that excluded one, rather than being convicted of requiring it.

Where an author-written judgement about English remains, it now lives only where being wrong
is safe. That is the property the one-set version claimed and did not have.

HONEST LIMITS — measured, and the list is not short. The FIRST one is a false refusal.
---------------------------------------------------------------------------------------
* **A negation that scopes over a QUALIFIER convicts on the subject anyway** — QUEUED AS
  #1096, and unlike everything below it this is a FALSE REFUSAL, not a miss. *"The user data
  is not stored ON A SERVER"* negates the qualifier, not the capability, but the frame
  captures ``user data`` and convicts it against an assumption that the user data stays in
  the browser. Two compatible statements, one refused plan; 8 reproductions across four of
  the six convicting frames. PRE-EXISTING — byte-identical in ``ffc0dae1``, the original
  build — and disclosed rather than fixed, because the available repair narrows
  :data:`_CONVICTING_FRAMES`, and a logic change stacked into a third consecutive fix round
  is how this tree has been growing new defects. #1096 carries the direction and a definition
  of done that forbids buying the fix by refusing more elsewhere.

  Read this one together with the corpus figure at the bottom: the shape is **absent from all
  50 naturally-written coherent specs across both independently authored corpora**, which is
  why that figure reads zero and is not wrong to. Nobody writes "not stored on a server" while
  inventing examples of coherent *specs* — you write it while inventing examples of
  *products*. It is the sharpest instance in this module of the rule that a measurement is
  only as adversarial as whoever wrote the inputs.
* **Reach is the convicting frame set.** An exclusion phrased outside it — including
  ``without X`` and a bare ``no X``, both demoted to see-through above — is invisible.
* **One-word capabilities are never convicted** (:data:`_MIN_SUBJECT_TOKENS`), and this is
  bigger than it sounds: all ten of the commonest single-noun capabilities measured escape
  (history, search, undo, login, pagination, notifications, autosave, printing, charts,
  sorting). That is most of a small application's feature vocabulary, not an edge.
* **A QUALIFIED negation on the requiring side excuses the contradiction** — QUEUED AS #1095.
  *"The reset button is not shown until an entry exists"* REQUIRES a reset button, but it
  carries an exclusion frame over that subject, so step 3 suppresses. This is #1054's own
  shape landing in the excused bucket. It is left rather than patched deliberately: every
  candidate fix narrows step 3, which pushes toward MORE convictions — the failure direction
  that made the first version unshippable. Closing it needs a different technique, not a
  longer pattern, and #1095 requires the corpus figure below to still hold when it closes.
* **Only the criterion's ``text`` is read**, not its ``check``.
* **Same-side disagreement is out of scope** (criterion vs criterion, assumption vs
  assumption), per the #1054 defect shape.
* **Open-ended spans over-capture**: "There is no undo button anywhere in the app" yields the
  subject ``undo button anywhere app``, which matches nothing.
* **Plural folding is crude** (a trailing ``s`` is dropped); "entries" and "entry" do not
  match each other.
* It decides CONTRADICTION, never CORRECTNESS. Two statements that agree with each other and
  are both wrong about the goal pass cleanly — scope anchoring is the prompt's job.

Measured over a 30-spec adversarial corpus written against this design (punctuation-split
clauses, pronoun negation, manner adverbials, qualified negation, and the agreement forms):
**0 false refusals, 14 of 16 planted contradictions caught.** The same corpus refused 5
coherent specs before the two fixes above.

Across BOTH corpora — that one and the independently authored review corpus — recall is
**22 of 36, about 61%**. Quote that figure, not the 14/16: a single corpus read 88% and the
two-corpus number is the honest one. And neither corpus contains the #1096 shape, so the
zero above is bounded by what two authors thought to write, not by what the gate can do.

This module is deliberately dependency-free (plain strings in, findings out) so it can be
driven directly in tests and cannot participate in an import cycle with ``acceptance``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

#: A criterion requires a capability an assumption explicitly excluded (or the reverse).
#: The ONLY finding this gate produces — see the module docstring's contract section.
KIND_CONTRADICTION = "contradiction"

#: The smallest subject phrase this gate will CONVICT on, in content tokens.
#:
#: MEASURED, not chosen (see ``test_single_token_subjects_are_not_convicted``): at one token
#: the gate over-fired on 1 of 10 realistic non-contradicting specs — "Assumed the data is
#: not stored between sessions" yields the subject ``data``, and a criterion reading "displays
#: a chart of today's data points" was convicted of requiring stored data. A bare common noun
#: appearing in a sentence is not evidence that the same CAPABILITY is required; two tokens is
#: the shortest phrase that names one distinctly ("reset button", "dark mode", "user
#: accounts", "calculation history" — every true positive in that corpus survives the floor).
#:
#: A one-token subject is therefore DECIDED COHERENT: the statement named what it excludes,
#: the gate looked, and a common-noun collision is not proof of a requirement. The cost is
#: RECALL, and it is large — see the module docstring's measured list of what escapes.
_MIN_SUBJECT_TOKENS = 2


@dataclass(frozen=True)
class CoherenceFinding:
    """One established disagreement: a capability one side ruled out and the other demands.

    ``subject`` is the normalised capability phrase; ``excluded_by`` is the statement that
    ruled it out and ``required_by`` the statement that demands it. All four fields are
    REQUIRED — a finding is a PAIR by construction, so there is no way to build one that
    refuses a plan without naming both sides of the disagreement it refuses over."""

    kind: str
    subject: str
    excluded_by: str
    required_by: str


# ---------------------------------------------------------------------------
# Tokenisation — the precision surface
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"[a-z0-9]+")

#: Function words carried by both sides of every comparison. Dropped from BOTH the subject
#: and the statement it is matched against, so "a reset button" matches "the reset button"
#: without the match itself ever depending on articles.
_STOPWORDS: frozenset[str] = frozenset(
    {
        "a", "an", "the", "any", "some", "this", "that", "these", "those", "its", "their",
        "his", "her", "our", "your", "my", "of", "for", "to", "in", "on", "at", "by", "with",
        "from", "as", "is", "are", "was", "were", "be", "been", "being", "will", "would",
        "shall", "should", "must", "can", "could", "may", "might", "do", "does", "did", "it",
        "they", "we", "you", "and", "or", "but", "if", "then", "than", "so", "there", "here",
        "not", "no", "into", "over", "per", "up", "out", "each", "when", "while", "which",
    }
)

#: Words that lead an assumption sentence without being part of its subject. Stripped from
#: the FRONT of a captured span only — "Assumed a reset button is not needed" must yield
#: ``reset button``, not ``assumed reset button``, or the phrase would never match a
#: criterion. Never applied mid-phrase, where these words carry meaning.
#:
#: DELIBERATELY NARROW — sentence-framing verbs and adverbs only. An earlier version also
#: stripped head nouns ("app", "page", "user", "system"), which BROADENS the subject and so
#: LOOSENS the phrase match: "page numbers are not needed" became the subject ``numbers``,
#: which any criterion mentioning a number would have contradicted. Every word added here
#: makes a false refusal more likely, so the list stays at the words that are never part of
#: a capability's name.
_LEAD_NOISE: frozenset[str] = frozenset(
    {
        "assumed", "assume", "assuming", "assumption", "also", "just", "only",
        "therefore", "however", "additionally", "further", "currently",
    }
)


def _fold(token: str) -> str:
    """Crude singular folding: drop ONE trailing ``s``. Guarded against the endings where
    that is usually wrong (``glass``, ``bus``, ``analysis``) and against short words, where
    it changes the word entirely. Named as a limit in the module docstring rather than
    dressed up as stemming — a real stemmer is a dependency this gate does not need."""
    if len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def content_tokens(text: str) -> tuple[str, ...]:
    """The comparable token sequence of a statement: lowercased words, stopwords dropped,
    singulars folded. Applied identically to both sides of every comparison, which is what
    lets a contiguous match survive the articles and auxiliaries English scatters through a
    sentence."""
    return tuple(
        _fold(w) for w in _WORD_RE.findall((text or "").lower()) if w not in _STOPWORDS
    )


def _subject_tokens(raw: str) -> tuple[str, ...]:
    """Normalise a captured exclusion span into its subject tokens.

    Leading noise/function words are stripped (see :data:`_LEAD_NOISE`); the remainder is the
    capability the statement rules out.

    An EMPTY result means the span held nothing but function words. That is USUALLY a span
    the regex could not reach past a comma rather than a genuinely vague statement, and the
    two are indistinguishable from here — so it is dropped, not refused on. See the module
    docstring's contract section for why that arm was removed."""
    tokens = list(content_tokens(raw))
    while tokens and tokens[0] in _LEAD_NOISE:
        tokens.pop(0)
    return tuple(tokens)


# ---------------------------------------------------------------------------
# Exclusion frames — TWO sets, split by what a false positive costs
# ---------------------------------------------------------------------------

#: The subject span a frame captures. Bounded at 58 characters: a capability name, not a
#: clause. Commas are excluded so a span cannot swallow the next clause.
_SUBJ = r"(?P<subj>[A-Za-z0-9][A-Za-z0-9 '\-]{0,58}?)"

#: Verbs that, under negation, state that something is ABSENT.
_ABSENT = (
    r"(?:needed|required|provided|included|kept|stored|saved|supported|shown|displayed"
    r"|offered|available|implemented|added|tracked|persisted)"
)

#: Verbs of possession — "does not <verb> X".
_HAS = (
    r"(?:include|includes|have|has|support|supports|show|shows|display|displays|keep|keeps"
    r"|store|stores|save|saves|provide|provides|offer|offers|track|tracks|contain|contains)"
)

#: Where an open-ended subject span ends: punctuation, a conjunction, or the string end.
#: Without this a trailing-span frame swallows the rest of a compound sentence and yields a
#: junk subject that matches nothing (harmless, but noise in the findings).
_CLAUSE_END = r"(?=[.,;:!?]|\s+(?:and|or|but|which|that|so|while|although)\b|$)"

#: CONVICTING frames — a match here can REFUSE a plan, so the bar is that the negation
#: attaches unambiguously to the noun as an exclusion of the capability. Ordered
#: most-specific first. Each MUST capture ``subj``; a frame that cannot name what it excludes
#: has no place here, because the subject is the entire basis of the decision.
_CONVICTING_FRAMES: tuple[re.Pattern[str], ...] = (
    # "no reset button is needed" / "no calculation history is kept"
    re.compile(
        r"\bno\s+" + _SUBJ + r"\s+(?:is|are|was|were|will\s+be)\s+" + _ABSENT + r"\b",
        re.IGNORECASE,
    ),
    # "a reset button is not needed"  <- the #1054 live case
    re.compile(
        r"\b" + _SUBJ + r"\s+(?:is|are|was|were|will)\s+not\s+(?:be\s+)?" + _ABSENT + r"\b",
        re.IGNORECASE,
    ),
    # "a reset button is excluded / omitted / out of scope"
    re.compile(
        r"\b" + _SUBJ + r"\s+(?:is|are)\s+(?:excluded|omitted|out\s+of\s+scope"
        r"|not\s+in\s+scope)\b",
        re.IGNORECASE,
    ),
    # "there is no reset button"
    re.compile(
        r"\bthere\s+(?:is|are|will\s+be)\s+no\s+" + _SUBJ + _CLAUSE_END, re.IGNORECASE
    ),
    # "does not include a reset button"
    re.compile(
        r"\b(?:does|do|will|shall|should)\s+not\s+" + _HAS + r"\s+" + _SUBJ + _CLAUSE_END,
        re.IGNORECASE,
    ),
    # "never shows a reset button" — the adverbial negation. Present because ``never`` is a
    # CONTENT token that survives tokenisation, so without this frame a negated criterion
    # still contains the excluded phrase and would be convicted of requiring it. The
    # agreement check in :func:`_cross` needs a frame to see the negation through.
    re.compile(r"\bnever\s+" + _HAS + r"\s+" + _SUBJ + _CLAUSE_END, re.IGNORECASE),
)

#: SEE-THROUGH-ONLY frames — used ONLY to recognise that the other side ALSO negates a
#: subject, never to convict. A false positive here suppresses a conviction, i.e. misses a
#: catch, which is today's behaviour; the same false positive in the convicting set refuses a
#: coherent plan. Opposite costs, so these two live in different sets.
#:
#: Both entries earned their demotion by measurement. ``without X`` and a bare clause-final
#: ``no X`` are MANNER ADVERBIALS at least as often as they are exclusions — "The app
#: launches without an error message", "The total updates with no page refresh" — and in
#: those the frame, not the statement, supplies the judgement that X is excluded. They stay
#: here because they still read correctly in the other direction: "The page works without a
#: reset button" genuinely AGREES with an assumption that ruled a reset button out, and
#: dropping them entirely would convict that criterion of requiring one.
_SEE_THROUGH_ONLY_FRAMES: tuple[re.Pattern[str], ...] = (
    # "without a reset button"
    re.compile(r"\bwithout\s+" + _SUBJ + _CLAUSE_END, re.IGNORECASE),
    # "no reset button." — the bare, clause-final form; the loosest frame here.
    re.compile(r"\bno\s+" + _SUBJ + _CLAUSE_END, re.IGNORECASE),
)

#: The wider set step 3 reads: everything that can convict, plus the demoted frames.
_SEE_THROUGH_FRAMES: tuple[re.Pattern[str], ...] = (
    _CONVICTING_FRAMES + _SEE_THROUGH_ONLY_FRAMES
)


def _extract(statement: str, frames: tuple[re.Pattern[str], ...]) -> tuple[tuple[str, ...], ...]:
    """The subject-token tuples *frames* find in *statement*, deduplicated.

    Spans that normalise to nothing are DROPPED (see :func:`_subject_tokens`) — they name no
    capability, so they can neither be convicted on nor agreed with."""
    found: list[tuple[str, ...]] = []
    seen: set[tuple[str, ...]] = set()
    text = (statement or "").strip()
    if not text:
        return ()
    for pattern in frames:
        for match in pattern.finditer(text):
            tokens = _subject_tokens((match.group("subj") or "").strip())
            if not tokens or tokens in seen:
                continue
            seen.add(tokens)
            found.append(tokens)
    return tuple(found)


def extract_exclusions(statement: str) -> tuple[tuple[str, ...], ...]:
    """The capability phrases a statement rules out, as subject-token tuples — the CONVICTING
    reading. Public because the tests pin extraction directly: a frame that silently stopped
    matching would leave every behaviour test green via the empty path."""
    return _extract(statement, _CONVICTING_FRAMES)


def _contains_phrase(haystack: tuple[str, ...], needle: tuple[str, ...]) -> bool:
    """True when *needle* appears in *haystack* as a CONTIGUOUS run.

    Contiguity, not set membership: a bag-of-words test would convict "Reset the totals; the
    button clears the form" of requiring a "reset button"."""
    if not needle or len(needle) > len(haystack):
        return False
    return any(
        haystack[i : i + len(needle)] == needle
        for i in range(len(haystack) - len(needle) + 1)
    )


def _cross(excluding: Sequence[str], requiring: Sequence[str]) -> list[CoherenceFinding]:
    """One direction of the check: every exclusion in *excluding* against every statement in
    *requiring*. Called twice (both directions) by :func:`check_coherence`."""
    out: list[CoherenceFinding] = []
    for stmt in excluding:
        for subject in _extract(stmt, _CONVICTING_FRAMES):
            if len(subject) < _MIN_SUBJECT_TOKENS:
                continue  # named, checked, acquitted — see _MIN_SUBJECT_TOKENS
            for other in requiring:
                if not _contains_phrase(content_tokens(other), subject):
                    continue
                # The other side may rule the SAME capability out — then the two agree, and
                # agreement is the outcome this gate exists to protect, not to report. Read
                # with the WIDER frame set: a false agreement costs a catch, a false
                # conviction costs a coherent plan.
                if subject in _extract(other, _SEE_THROUGH_FRAMES):
                    continue
                out.append(
                    CoherenceFinding(
                        kind=KIND_CONTRADICTION,
                        subject=" ".join(subject),
                        excluded_by=stmt,
                        required_by=other,
                    )
                )
    return out


def check_coherence(
    assumptions: Sequence[str], criteria: Sequence[str]
) -> tuple[CoherenceFinding, ...]:
    """The gate. Returns every ESTABLISHED disagreement; EMPTY means none was established.

    Read that second clause literally — empty is not a certificate of coherence, and the
    module docstring lists what it provably misses. Both directions are checked, because the
    defect is disagreement and disagreement has no privileged side.

    The caller REFUSES on any non-empty result. This function never decides what to do about
    a finding and never mutates the spec: reconciling a contradiction means choosing which
    half of the plan was wrong, which is a judgement, not a rule."""
    left = [str(a).strip() for a in assumptions if str(a).strip()]
    right = [str(c).strip() for c in criteria if str(c).strip()]
    findings = _cross(left, right) + _cross(right, left)

    unique: list[CoherenceFinding] = []
    seen: set[tuple[str, str, str, str]] = set()
    for f in findings:
        key = (f.kind, f.subject, f.excluded_by, f.required_by)
        if key in seen:
            continue
        seen.add(key)
        unique.append(f)
    return tuple(unique)


# ---------------------------------------------------------------------------
# Operator-facing refusal text
# ---------------------------------------------------------------------------
#
# The operator reads these words on the plan card, so they name the disagreement in the
# model's OWN sentences and say what to do next. No identifiers, no tier names, no ticket
# numbers — the person reading this cannot act on any of those.


def _quote(text: str, *, limit: int = 160) -> str:
    flat = " ".join((text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def refusal_message(findings: Sequence[CoherenceFinding]) -> str:
    """Plain-language refusal naming the disagreement the gate found."""
    lines = [
        f'- "{_quote(f.excluded_by)}" says {f.subject} is not part of this, '
        f'but "{_quote(f.required_by)}" requires it.'
        for f in findings
    ]
    return (
        "This plan disagrees with itself, so it was not offered:\n"
        + "\n".join(lines)
        + "\nSay in the goal whether you want it, and dispatch again."
    )


def refusal_message_for_error(exc: BaseException) -> str:
    """Refusal used when the check itself could not run. Fail-closed: a gate that cannot
    verify the plan blocks it rather than letting an unchecked plan render as checked."""
    return (
        "This plan could not be checked for disagreeing with itself, so it was not "
        f"offered ({type(exc).__name__}). Dispatch again."
    )
