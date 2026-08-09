"""Requirements-clarification stage for headless-coding dispatch (#819).

A non-technical operator's one-line desire ("build me a habit tracker") goes straight
to decompose today; ambiguity at the top compounds through plan -> oracle -> coder ->
verify, and nothing asks the operator what they actually meant. This module is the
CLARIFY stage that sits BETWEEN the dispatch request and decompose: given the raw goal,
the 14B proposes a FEW targeted, plain-language questions about the decision axes that
most change the build (where it runs, whether data is saved, the one must-work feature,
how it looks, how big a first version), the operator answers in their own words, and the
answers compose into a compact ENRICHED REQUIREMENTS block that rides decompose + the
acceptance oracle + every task context.

Discipline (mirrors :mod:`shared.fleet.acceptance` — the model PROPOSES, a deterministic
ruler DISPOSES):

  * **Sufficiency check FIRST.** A goal that already carries the axes yields an empty
    question list — ZERO questions, no quiz, byte-identical to today's direct decompose.
  * **Small-model discipline (#740 c.1721).** Short, single-focus prompt; grammar-first
    structured emission via the #743 hook with a transparent fail-soft to free-text; the
    ruler caps + dedupes so a sloppy emission can never put a wall of questions in front
    of a novice.
  * **Fail-soft is absolute.** Any failure (no hook, hook raises, empty/garbage output)
    degrades to ``()`` — the dispatch flows exactly as today (direct decompose), logged.
  * **"Just decide for me"** self-answers with per-axis defaults, RECORDED as assumptions
    so the operator SEES what was chosen for them on the plan card.

This module is PURE + GPU-free (the model call is injected, mirroring
:func:`shared.fleet.acceptance.generate_plan`), so the whole stage is unit-testable
without hardware.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Callable

# ---------------------------------------------------------------------------
# Decision axes — the coarse product-level decisions that most change a build
# ---------------------------------------------------------------------------
#
# Deliberately SMALL (the rubber-stamp-quiz guard, mirroring acceptance.py's clarifying
# decision-map scope discipline): a novice quizzed per-detail rubber-stamps — worse than
# not asking. Each axis is (a) a decision that materially forks WHAT gets built, (b) one
# the 14B genuinely cannot assume from a bare product line, and (c) answerable in product
# terms by a non-developer. NO technical axis (language / framework / versions) — those are
# supplied by the system (AGENTS.md), never asked of the operator.

AXIS_SURFACE = "surface"          # where it runs (this computer / a browser / a phone)
AXIS_PERSISTENCE = "persistence"  # whether the operator's data is saved between uses
AXIS_FEATURE = "feature"          # the ONE thing it must do well
AXIS_VISUAL = "visual"            # how it should look / feel
AXIS_SCOPE = "scope"              # how big a first version

# #1031 S2 — the three INTAKE-ONLY axes, askable only through the fuller interview the
# operator explicitly requests (the `advanced` token). Same admission bar as the five above:
# product-level, forks WHAT gets built, unanswerable-by-assumption, answerable by a
# non-developer. `content` exists because its absence let a build invent placeholder
# projects and present them as real; `edge` because the operator's own awkward cases never
# reached a spec; `nongoal` because the scope fence was always inferred, never authored.
AXIS_CONTENT = "content"          # what real text/items/data it should contain
AXIS_EDGE = "edge"                # what should happen on odd or wrong input
AXIS_NONGOAL = "nongoal"          # what the first version deliberately does NOT include

#: The closed axis vocabulary — the ONLY values a question may be tagged with (the grammar
#: enum + the ruler both pin to this). An unknown axis coerces to ``feature`` (the safe,
#: always-relevant default) rather than dropping the question.
CLARIFY_AXES: frozenset[str] = frozenset(
    {AXIS_SURFACE, AXIS_PERSISTENCE, AXIS_FEATURE, AXIS_VISUAL, AXIS_SCOPE}
)
_AXIS_FALLBACK = AXIS_FEATURE

#: #1165 M1 — the CANONICAL ORDER of the intake interview's decision areas: the live
#: template's area sequence, pinned. Byte-determinism authority for the template builder
#: (:func:`intake_template_for`): the rendered area lines and the axis enum in the JSON
#: instruction both iterate THIS tuple, never a frozenset (set iteration order would make
#: template bytes nondeterministic). The intake frozenset vocabulary derives from it.
INTAKE_AXES_ORDER: tuple[str, ...] = (
    AXIS_SURFACE, AXIS_PERSISTENCE, AXIS_FEATURE, AXIS_VISUAL, AXIS_SCOPE,
    AXIS_CONTENT, AXIS_EDGE, AXIS_NONGOAL,
)

#: #1031 S2 — the intake interview's WIDER closed vocabulary: the five quick-path axes plus
#: the three intake-only ones. A second allowlist, not a loosened one — an axis outside
#: whichever set is active still coerces to ``feature``, in both modes. Derived from
#: :data:`INTAKE_AXES_ORDER` (#1165 M1) so the set and the template can never disagree
#: about the vocabulary.
INTAKE_AXES: frozenset[str] = frozenset(INTAKE_AXES_ORDER)

#: Hard cap on questions asked from one goal (the "a few, not a quiz" rule). 5 == one per
#: axis at most; the ruler dedupes by axis so the operator is never asked the same axis twice.
DEFAULT_MAX_QUESTIONS = 5

#: #1031 S2 — the intake interview's cap: one per axis, so the bound is STRUCTURAL (the
#: ruler's one-question-per-axis dedupe makes an over-emitting model top out at the axis
#: count) rather than aspirational. Rendered, 8 questions is still one screenful.
INTAKE_MAX_QUESTIONS = 8

#: A question shorter than this (after strip) is vacuous and dropped.
_MIN_QUESTION_LEN = 8

#: Per-axis product-level defaults used when the operator says "just decide for me" — each
#: is something a non-developer can read and understand, RECORDED as an assumption on the
#: plan card (never a technical choice). Sized to the coarsest sensible first version.
DEFAULT_AXIS_ANSWERS: dict[str, str] = {
    AXIS_SURFACE: "a simple app that runs on this computer",
    AXIS_PERSISTENCE: "your information is saved, so it is still there next time you open it",
    AXIS_FEATURE: "the main thing you described works reliably",
    AXIS_VISUAL: "a clean, simple, easy-to-read look",
    AXIS_SCOPE: "a small, focused first version covering the essentials",
    # #1031 S2 — the intake-only axes' defaults. Unreachable on the quick path (the
    # five-axis coercion never produces these keys there). The `content` default bakes the
    # invented-placeholder lesson into the escape hatch itself: even an operator who
    # answers nothing gets labelled-example posture, never silent invention.
    AXIS_CONTENT: (
        "starts with clearly-labelled example content for you to replace — nothing "
        "invented that pretends to be real"
    ),
    AXIS_EDGE: (
        "unusual or wrong input gets a clear message instead of a crash or a silent guess"
    ),
    AXIS_NONGOAL: (
        "nothing beyond what you described — no extra features added on speculation"
    ),
}

#: #1161 — the SURFACE default "just decide for me" uses when the target project is an
#: EMPTY/NEW shell. The stock surface default above reads as an app ("a simple app that
#: runs on this computer"), which the build-signal model classifies desktop — and
#: desktop-from-nothing is the fleet's weakest, exam-blind path (the 2026-07-29 run
#: burned ~103 fleet-minutes on exactly that default). On an empty project the honest
#: default is the stack every check can sight; this text says so in the operator's card
#: language AND classifies cleanly as ``command-line`` when the model reads it back.
#: The coordinator passes it via ``decide_defaults(axis_defaults=...)`` ONLY for an
#: empty/new repo — an existing project keeps the stock default byte-for-byte.
EMPTY_PROJECT_SURFACE_ANSWER = (
    "a simple command-line tool that runs on this computer — the kind whose behavior "
    "can be fully checked automatically"
)


@dataclass(frozen=True)
class ClarifyQuestion:
    """One plain-language clarifying question, tagged by the decision axis it probes."""

    axis: str
    question: str

    def to_dict(self) -> dict:
        return {"axis": self.axis, "question": self.question}


# ---------------------------------------------------------------------------
# Question generation (the 14B proposes; the ruler disposes)
# ---------------------------------------------------------------------------

_CLARIFY_TEMPLATE = (
    "A non-technical person asked for a software build. Before it is built, ask ONLY the "
    "few questions whose answers would most change WHAT gets built AND that the request has "
    "NOT already made clear. Consider at most these decision areas, and SKIP any the request "
    "already answers:\n"
    "- surface: where they will use it (on this computer, in a web browser, or on a phone)\n"
    "- persistence: whether their information should be saved between uses\n"
    "- feature: the ONE thing it must do well\n"
    "- visual: how it should look or feel\n"
    "- scope: how big a first version they want\n"
    "Write each as ONE short, plain-language question a non-developer can answer in a "
    "sentence — no jargon, no technology names, nothing about programming. Return ONLY a "
    "JSON array (no prose) of at most {max_questions} objects, each "
    '{{"axis": "<surface|persistence|feature|visual|scope>", '
    '"question": "<the plain question>"}}. If the request is already clear on everything '
    "that matters, return an empty array [].\n\nRequest:\n{idea}\n"
)

# #1165 M1 — the intake template's per-area guidance lines, keyed by axis. Two registers:
# the STOCK lines are the live S2 wording (the all-flags-off bytes, identity-locked), the
# VOICE overrides speak the approved novice-interview template's Part 1 table
# (docs/research/novice-interview-template-research-2026-07-29.md): questions about the
# person's life, never software; the visual area as paired opposites. `edge` and `nongoal`
# carry NO voice override — their Part 1 form is propose-and-veto, which is M3's flag, so
# the voice keeps their stock lines. GUARD (#1161, locked): no line may restate a
# DEFAULT_AXIS_ANSWERS value inline — every default rendering reads that dict alone, so a
# default fix propagates into the interview automatically.
_AXIS_LINES: dict[str, str] = {
    AXIS_SURFACE: (
        "- surface: where they will use it (on this computer, in a web browser, "
        "or on a phone)\n"
    ),
    AXIS_PERSISTENCE: "- persistence: whether their information should be saved between uses\n",
    AXIS_FEATURE: "- feature: the ONE thing it must do well\n",
    AXIS_VISUAL: "- visual: how it should look or feel\n",
    AXIS_SCOPE: "- scope: how big a first version they want\n",
    AXIS_CONTENT: "- content: what real text, items, or starting data it should contain\n",
    AXIS_EDGE: "- edge: what should happen when something odd or wrong is entered\n",
    AXIS_NONGOAL: "- nongoal: what this first version should deliberately NOT include\n",
}
_AXIS_LINES_VOICE: dict[str, str] = {
    AXIS_SURFACE: (
        "- surface: where they will be when they use it — at a computer, on their "
        "phone out and about, or both\n"
    ),
    AXIS_PERSISTENCE: (
        "- persistence: whether it should remember their information between uses, "
        "or start fresh each time\n"
    ),
    AXIS_FEATURE: (
        "- feature: of everything they described, the ONE thing it must do well, "
        "even if the rest waits\n"
    ),
    AXIS_VISUAL: (
        "- visual: how it should feel, offered as paired opposites to pick per pair — "
        "calm and professional or colorful and friendly? plain and dense with "
        "information or spacious and simple?\n"
    ),
    AXIS_SCOPE: (
        "- scope: for the first version, the smallest thing that solves the core "
        "problem, or closer to the full vision at once\n"
    ),
    AXIS_CONTENT: (
        "- content: what real things should be in it on day one — their actual items, "
        "text, or numbers — or clearly-labelled examples for them to replace\n"
    ),
}

#: The question-writing instruction, stock register — the live S2 sentence, byte for byte.
_QUESTION_RULES = (
    "Write each as ONE short, plain-language question a non-developer can answer in a "
    "sentence — no jargon, no technology names, nothing about programming. "
)

#: #1165 M1 — the question-writing instruction, voice register: the interviewer-mistake
#: rules the research found lift machine-written questions above human-written ones when
#: baked into the authoring prompt itself (arXiv 2507.02858; the template's seven rules).
_QUESTION_RULES_VOICE = (
    "Write each as ONE short, plain-language question about their life and their "
    "situation, never about software. Question-writing rules, all of them: one decision "
    "per question — never two fused into one; never leading — do not suggest the answer "
    "you expect; never hypothetical — anchor questions in their real, concrete "
    "situation; no jargon, no technology names, nothing about programming; concrete "
    "beats abstract — offer real choices instead of asking them to describe from a "
    "blank page. "
)


def intake_template_for(
    axes: "tuple[str, ...]" = INTAKE_AXES_ORDER, *, voice: bool = False
) -> str:
    """Build the FULLER interview's question-authoring template over *axes* (#1165 M1).

    A pure builder so the template can grow per-flag without forking constants:
    with every parameter at default the output is TODAY'S :data:`_INTAKE_TEMPLATE`
    BYTE FOR BYTE (identity-locked — the constant IS this function's all-off output).
    *voice* swaps the area lines for the approved novice-interview template's Part 1
    wordings where one exists and the question-writing sentence for the mistake-rule
    list; everything else — the sufficiency instruction, the JSON contract, the
    ``{max_questions}``/``{idea}`` placeholders — is identical in both registers.

    *axes* is the canonical ORDER (a tuple, never a frozenset — bytes must be
    deterministic); the JSON instruction's axis enum derives from it, so template and
    vocabulary cannot disagree. An axis without a registered line is a programming
    error and raises ``KeyError`` at build time — this function renders doctrine,
    it never sees operator input."""
    lines = "".join(
        _AXIS_LINES_VOICE.get(a, _AXIS_LINES[a]) if voice else _AXIS_LINES[a]
        for a in axes
    )
    rules = _QUESTION_RULES_VOICE if voice else _QUESTION_RULES
    return (
        "A non-technical person asked for a software build and requested the FULLER intake "
        "interview. Ask ONLY the questions whose answers would most change WHAT gets built AND "
        "that the request has NOT already made clear. Consider at most these decision areas, "
        "and SKIP any the request already answers:\n"
        + lines
        + rules
        + "Return ONLY a JSON array (no prose) of at most {max_questions} objects, each "
        '{{"axis": "<' + "|".join(axes) + '>", '
        '"question": "<the plain question>"}}. If the request is already clear on everything '
        "that matters, return an empty array [].\n\nRequest:\n{idea}\n"
    )


# #1031 S2 — the FULLER interview's template: the same register, contract and
# return-[]-when-clear sufficiency instruction as _CLARIFY_TEMPLATE, over the eight-axis
# vocabulary. Used only when the operator explicitly asked for the intake interview.
# #1165 M1: the all-off output of :func:`intake_template_for` (identity-locked against the
# pre-builder literal), so per-flag wording swaps and later area additions share one source.
_INTAKE_TEMPLATE = intake_template_for()

#: #1165 M1 — the Phase-0 "setting the table" preamble (the approved template's four
#: sentences, near-verbatim): the no-wrong-answers promise, the everyday-words promise,
#: the "you decide" hatch, and the read-back contract. Deterministic text; the gateway
#: prepends it to the INTAKE question render only, and only when the voice flag is on.
INTAKE_PREAMBLE = (
    "I'm going to ask you a short set of questions so I build the right thing. "
    "There are no wrong answers and no technical answers — everything is in everyday "
    "words. For any question you can answer in your own words, pick one of the options "
    "I offer, or just say 'you decide' and I'll choose something sensible and tell you "
    "what I chose. At the end I'll read my understanding back to you, and nothing is "
    "final until you've corrected it."
)

# Pull the first JSON array out of a model response (it may wrap it in prose/fences).
_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)


def clarify_questions_emission_json_schema(
    *, max_questions: int = DEFAULT_MAX_QUESTIONS,
    axes: "frozenset[str]" = CLARIFY_AXES,
) -> dict:
    """The JSON schema for a grammar-constrained CLARIFY emission — the same
    ``{axis, question}`` shape :func:`_parse_questions` expects, with ``axis`` pinned to
    *axes* (the quick path's :data:`CLARIFY_AXES` by default; the intake interview passes
    :data:`INTAKE_AXES` — #1031 S2) and the vacuous floor applied at the source. An empty
    array is a VALID constrained answer (the sufficient goal) — ``minItems`` is
    intentionally omitted so ``[]`` is accepted rather than forcing a needless question."""
    return {
        "type": "array",
        "maxItems": max_questions,
        "items": {
            "type": "object",
            "properties": {
                "axis": {"enum": sorted(axes)},
                "question": {"type": "string", "minLength": _MIN_QUESTION_LEN},
            },
            "required": ["axis", "question"],
            "additionalProperties": False,
        },
    }


def _is_json_array(text: str) -> bool:
    """True iff *text* carries a parseable JSON array — INCLUDING an empty one.

    An empty array is a MEANINGFUL clarify answer ("the goal is sufficient — ask nothing"),
    so a grammar-constrained ``[]`` is accepted rather than triggering a redundant free-text
    retry; garbage still falls back to the free-text path."""
    if not isinstance(text, str) or not text:
        return False
    match = _JSON_ARRAY_RE.search(text)
    if not match:
        return False
    try:
        return isinstance(json.loads(match.group(0)), list)
    except (ValueError, TypeError):
        return False


def _grammar_first(
    prompt: str,
    *,
    structured_generate_fn: "Callable[[str, str], str] | None",
    schema: dict,
) -> "str | None":
    """One OPTIONAL grammar-constrained emission (the W2/#718/#743 hook).

    Mirrors :func:`shared.fleet.acceptance._grammar_first` but self-contained (clarify has
    NO import from acceptance, so acceptance can import clarify without a cycle). Tries
    *structured_generate_fn* FIRST, called ``(prompt, json_schema_text)``; returns the raw
    text ONLY when the hook exists, did not raise, and produced a usable JSON array; ``None``
    in EVERY other case — the caller then runs the free-text path unchanged."""
    if structured_generate_fn is None:
        return None
    try:
        raw = structured_generate_fn(prompt, json.dumps(schema))
    except Exception:  # noqa: BLE001 — the hook must never add a failure mode
        return None
    if raw and _is_json_array(raw):
        return raw
    return None


def _parse_questions(
    text: str, *, max_questions: int, axes: "frozenset[str]" = CLARIFY_AXES
) -> tuple[ClarifyQuestion, ...]:
    """Best-effort parse of the model output into validated questions; ``()`` on failure.

    The model PROPOSES; this DISPOSES (mirrors the acceptance rulers): keep only
    ``{axis, question}`` objects whose question clears the vacuous floor; coerce an axis
    outside *axes* to :data:`_AXIS_FALLBACK` (the closed vocabulary holds in BOTH modes —
    the intake set is a wider allowlist, not an open one; #1031 S2); DEDUPE by axis (one
    question per axis — a novice is never asked the same decision twice); cap. Order
    preserved. An empty/garbage emission yields ``()`` (the sufficient goal — no questions
    asked). Never raises."""
    if not text:
        return ()
    match = _JSON_ARRAY_RE.search(text)
    if not match:
        return ()
    try:
        data = json.loads(match.group(0))
    except (ValueError, TypeError):
        return ()
    if not isinstance(data, list):
        return ()
    out: list[ClarifyQuestion] = []
    seen_axes: set[str] = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        question = str(item.get("question", "")).strip()
        if len(question) < _MIN_QUESTION_LEN:
            continue
        axis = str(item.get("axis", "")).strip().lower()
        if axis not in axes:
            axis = _AXIS_FALLBACK
        if axis in seen_axes:
            continue
        seen_axes.add(axis)
        out.append(ClarifyQuestion(axis=axis, question=question))
        if len(out) >= max_questions:
            break
    return tuple(out)


def generate_clarifying_questions(
    goal: str,
    *,
    generate_fn: Callable[[str], str],
    structured_generate_fn: "Callable[[str, str], str] | None" = None,
    max_questions: int = DEFAULT_MAX_QUESTIONS,
    axes: "frozenset[str]" = CLARIFY_AXES,
    template: str = _CLARIFY_TEMPLATE,
) -> tuple[ClarifyQuestion, ...]:
    """The 14B proposes clarifying questions for an underspecified goal; the ruler disposes.

    This IS the sufficiency check: a goal that already carries the decision axes yields ``()``
    (the model returns ``[]``), so the caller asks NOTHING and proceeds straight to decompose
    — never a mandatory quiz. #743: the emission is tried grammar-constrained FIRST (schema
    enum-pinned to *axes*) with a transparent fail-soft to the free-text path.

    #1031 S2: *axes*/*template*/*max_questions* select the interview breadth — the defaults
    are the quick path, byte for byte; the intake interview passes :data:`INTAKE_AXES`,
    :data:`_INTAKE_TEMPLATE` and :data:`INTAKE_MAX_QUESTIONS`. The sufficiency contract and
    the absolute fail-soft are identical in both modes.

    Fail-soft is absolute — ANY failure (blank goal, no hook, hook raises, model raises,
    empty/garbage output) returns ``()`` so the dispatch degrades to today's direct decompose.
    The model call is injected so this is fully testable without the GPU."""
    idea = (goal or "").strip()
    if not idea:
        return ()
    prompt = template.format(max_questions=max_questions, idea=idea)
    raw = _grammar_first(
        prompt,
        structured_generate_fn=structured_generate_fn,
        schema=clarify_questions_emission_json_schema(
            max_questions=max_questions, axes=axes
        ),
    )
    if raw is None:
        try:
            raw = generate_fn(prompt)
        except Exception:  # noqa: BLE001 — a clarify failure must degrade, never crash
            return ()
    return _parse_questions(raw, max_questions=max_questions, axes=axes)


# ---------------------------------------------------------------------------
# "Just decide for me" — the escape hatch that self-answers with recorded defaults
# ---------------------------------------------------------------------------

#: Normalised phrases that mean "stop asking, choose sensible defaults for me". Matched after
#: lower-casing + collapsing whitespace + stripping trailing punctuation, so "Just decide for
#: me!" / "you decide" / "decide" all resolve. Kept small + explicit (never a fuzzy match that
#: could swallow a real answer that merely contains the word "decide").
_DECIDE_PHRASES: frozenset[str] = frozenset(
    {
        "just decide",
        "just decide for me",
        "decide",
        "decide for me",
        "you decide",
        "you decide for me",
        "decide for me please",
        "just pick",
        "just choose",
        "pick for me",
        "choose for me",
        "whatever you think",
        "up to you",
    }
)


#: #1165 M1 — template rule 6: normalised WHOLE-reply phrases that mean "I don't know".
#: Admitted only through :func:`is_decide_for_me`'s ``dont_know`` keyword (the M1 voice
#: flag) — the same small-explicit-never-fuzzy discipline as :data:`_DECIDE_PHRASES`, so a
#: reply that merely CONTAINS these words ("I don't know about the colors") stays a real
#: answer. Apostrophe-less twins included: they are how the phrases actually get typed.
_DONT_KNOW_PHRASES: frozenset[str] = frozenset(
    {
        "i don't know",
        "i dont know",
        "don't know",
        "dont know",
        "no idea",
        "i have no idea",
        "not sure",
        "i'm not sure",
        "im not sure",
    }
)


def is_decide_for_me(text: str, *, dont_know: bool = False) -> bool:
    """True iff the operator's reply means "just decide for me" (the escape hatch).

    #1165 M1: *dont_know* additionally admits the small explicit I-don't-know phrase set
    (:data:`_DONT_KNOW_PHRASES` — template rule 6), whole-reply only, routing it to the
    SAME decide-defaults turn where the chosen defaults are recorded as assumptions the
    plan card shows. False (the default — the parser's verb site and every quick caller)
    keeps the live recognizer byte-identical: today a whole-reply "I don't know" records
    as a substantive answer, which is exactly the misread the flag retires."""
    norm = re.sub(r"\s+", " ", (text or "").strip().lower()).strip(" .!?,")
    if norm in _DECIDE_PHRASES:
        return True
    if not dont_know:
        return False
    # Curly apostrophes (U+2019) arrive from some input methods; mapping them to the
    # ASCII twin is orthography, not fuzzy matching — the phrase set stays closed.
    return norm.replace("’", "'") in _DONT_KNOW_PHRASES


def questions_from_dicts(
    raw: object, *, axes: "frozenset[str]" = CLARIFY_AXES
) -> tuple[ClarifyQuestion, ...]:
    """Reconstruct :class:`ClarifyQuestion` objects from ``{axis, question}`` dicts (the wire /
    stored shape). Fail-closed: skips non-dicts and blank questions, coerces an axis outside
    *axes* to :data:`_AXIS_FALLBACK`. ``()`` for a non-list. Never raises — the caller
    re-derives the per-axis defaults/answers from these, so a malformed record must never
    crash the answer.

    #1031 S2: a parked INTAKE question set reconstructs with ``axes=INTAKE_AXES`` (the hold
    state carries which mode parked it) — under the five-axis default a stored ``content``
    question would coerce to ``feature`` and self-answer with the wrong default."""
    if not isinstance(raw, list):
        return ()
    out: list[ClarifyQuestion] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        question = str(item.get("question", "")).strip()
        if not question:
            continue
        axis = str(item.get("axis", "")).strip().lower()
        if axis not in axes:
            axis = _AXIS_FALLBACK
        out.append(ClarifyQuestion(axis=axis, question=question))
    return tuple(out)


def decide_defaults(
    questions: "tuple[ClarifyQuestion, ...] | list[ClarifyQuestion]",
    *, record_axes: bool = False,
    axis_defaults: "dict[str, str] | None" = None,
) -> list[dict]:
    """Self-answer each asked question with its per-axis default (the "just decide" path).

    Returns a list of clarification dicts ``{question, answer, assumed}`` with
    ``assumed=True`` — so they render on the plan card as assumptions ("here's what I decided
    for you") and the operator can catch a wrong default and reject. Order preserved.

    #1031 S2: *record_axes* additionally tags each dict with its question's axis
    (``"axes": [<axis>]``) so the acceptance record shows which decision area a default
    covered. False (every quick-path caller) emits byte-identical dicts.

    #1161: *axis_defaults* overlays per-axis answer TEXT over :data:`DEFAULT_AXIS_ANSWERS`
    for THIS call only (the caller knows context this pure module cannot — e.g. the target
    repo is an empty/new shell, where the stock surface default steers the exam-blind
    desktop path). ``None`` (every pre-#1161 caller) is byte-identical."""
    defaults = DEFAULT_AXIS_ANSWERS
    if axis_defaults:
        defaults = {**DEFAULT_AXIS_ANSWERS, **axis_defaults}
    out: list[dict] = []
    for q in questions:
        default = defaults.get(q.axis, defaults[_AXIS_FALLBACK])
        entry: dict = {"question": q.question, "answer": default, "assumed": True}
        if record_axes:
            entry["axes"] = [q.axis]
        out.append(entry)
    return out


def answered_from_free_text(
    questions: "tuple[ClarifyQuestion, ...] | list[ClarifyQuestion]", answer_text: str,
    *, record_axes: bool = False,
) -> list[dict]:
    """Record the operator's free-text reply as a single answered clarification.

    The operator answers all the questions in their own words in ONE reply (the natural,
    novice-friendly shape — no per-question form to fill in); that whole reply becomes the
    enriched requirement. The asked questions are joined for context so the plan card shows
    what was asked alongside what the operator said. ``assumed=False``. A blank reply yields
    ``[]`` (the caller then treats it as "nothing added" and proceeds).

    #1031 S2: *record_axes* tags the one merged dict with the FULL asked-axes list — the
    one-reply-answers-all shape has no per-axis split to record, and manufacturing one from
    a free reply would be model guesswork presented as fact. False (every quick-path
    caller) emits the byte-identical dict."""
    answer = (answer_text or "").strip()
    if not answer:
        return []
    asked = " / ".join(q.question for q in questions).strip()
    entry: dict = {"question": asked, "answer": answer, "assumed": False}
    if record_axes and questions:
        entry["axes"] = [q.axis for q in questions]
    return [entry]


# ---------------------------------------------------------------------------
# Compose the enriched requirements block + carry it across the plan seam
# ---------------------------------------------------------------------------

#: Sentinel delimiting the clarified-requirements block appended to the goal on the
#: coordinator -> plan seam. The plan seam is ``plan_fn(repo, goal)`` (many injected fakes),
#: so rather than widen that signature the enriched block rides INSIDE the goal string and is
#: split back off AO-side (:func:`split_planning_goal`) before ``generate_plan`` — keeping
#: ``spec.goal`` clean. Chosen to be vanishingly unlikely in a real product goal.
REQUIREMENTS_SENTINEL = "\n\n[[BLARAI_CLARIFIED_REQUIREMENTS]]\n"

#: #1031 S2 — the ADVANCED-INTAKE mode marker on the same seam. The gateway appends it to
#: the goal HEAD (before any requirements sentinel) for a `/dispatch advanced …` request;
#: the AO's ``generate_plan`` detects and strips it ONLY when the interview stages are on
#: — with either flag off it is inert text riding the goal, which is the toggle-off bar.
#: Same trust posture as the sentinel above: typing it by hand invokes at most the
#: interview the `advanced` token invokes; it grants nothing else.
INTAKE_SENTINEL = "\n\n[[BLARAI_ADVANCED_INTAKE]]\n"

#: The marker's whitespace-free core. Detection and removal key on THIS, not the padded
#: sentinel: the goal is ``.strip()``-ed at several seams (the AO's first touch included),
#: which eats the sentinel's trailing newline — a full-constant membership test would go
#: quietly blind to exactly the marker the gateway just composed.
_INTAKE_MARKER_TOKEN = "[[BLARAI_ADVANCED_INTAKE]]"


def compose_intake_goal(goal: str) -> str:
    """Append the intake marker to *goal* (the gateway side of the mode signal). The
    caller composes requirements AFTER this, so the marker always rides the goal HEAD that
    :func:`split_planning_goal` returns. Pure + total."""
    return (goal or "").strip() + INTAKE_SENTINEL


def split_intake_goal(goal: str) -> "tuple[str, bool]":
    """Inverse of :func:`compose_intake_goal`: ``(clean_goal, was_marked)``. A goal
    without the marker returns ``(goal_stripped, False)`` — byte-identical to today's
    plain request, so callers may run this unconditionally. Keys on the marker's core
    token (see :data:`_INTAKE_MARKER_TOKEN`), and every occurrence is removed (defense
    against a hand-typed double marker). Pure + total (never raises)."""
    raw = goal or ""
    if _INTAKE_MARKER_TOKEN not in raw:
        return raw.strip(), False
    return raw.replace(_INTAKE_MARKER_TOKEN, "\n").strip(), True


#: The renderer's own boilerplate. Named constants because :func:`compose_requirements_block`
#: and :func:`operator_answers_from_block` MUST agree on them: the block mixes house prose
#: with the operator's words, and the extractor's whole job is telling them apart. Editing
#: the wording here without the extractor seeing it would silently reclassify house prose as
#: operator text (#1043 review F1).
_REQUIREMENTS_HEADER = "The person clarified these requirements — build to them:"
#: #1197 — the SECOND header, for answers the SYSTEM chose. The single header above used to
#: cover both, so a "just decide for me" run rendered five system defaults under the words
#: "The person clarified these requirements" (run ``20260729-164648-bd``, read by the
#: operator in the run log). The ``(assumed)`` tag was present and did not carry the
#: distinction: a parenthetical does not undo a sentence, least of all for the
#: non-technical reader this text is written for. Say plainly who chose, in the same
#: plain language the questions were asked in — no jargon, no parenthetical.
_ASSUMED_HEADER = (
    "The person did NOT ask for these — they said \"you decide\", so I picked them "
    "myself. Build to them, but they are my choices, not their requirements:"
)
#: Every line this module writes as its OWN prose. The extractors below MUST skip all of
#: them: the block mixes house prose with the operator's words, and telling them apart is
#: their whole job. Adding a header without adding it here would silently promote house
#: prose to operator text — exactly #1043 review F1, which grounded an oracle judge on
#: "person", "build", "requirements" and friends. One tuple, so that cannot drift.
#: #1237 added the THIRD header (:func:`compose_planning_steer`) for the same reason.
_STEER_HEADER = (
    "The person did NOT ask for this one — it is how I make sure what gets built can "
    "actually be checked. Plan the criteria and the exam so this holds:"
)
_BLOCK_HEADERS: tuple[str, ...] = (
    _REQUIREMENTS_HEADER, _ASSUMED_HEADER, _STEER_HEADER,
)
_ANSWER_BULLET = "- "
_ASSUMED_TAG = "(assumed) "


def compose_requirements_block(clarifications: "list[dict] | tuple[dict, ...]") -> str:
    """Render the clarifications into a COMPACT block for the planning prompts (the coder
    builds to these, the oracle checks them). Token-budget disciplined (P4/P9): one short
    line per clarification. ``""`` when there is nothing to add (a fully-specified goal /
    an empty reply) — the plan is then byte-identical to today. Never raises.

    #1197: answers the OPERATOR gave and answers the SYSTEM chose are rendered under
    SEPARATE headers, never one. Attribution is the point — a system default printed under
    "The person clarified these requirements" is a false statement about the person, and it
    is the one the operator actually read. Operator-authored answers come first (they
    outrank a default), each group is omitted entirely when empty, and assumed lines keep
    their ``(assumed)`` tag so a line remains self-describing wherever it is quoted alone.

    The output is PROMPT text: house prose plus the operator's words. Anything that needs
    only the operator's words (a grounding corpus, where house prose would grant authority
    to language the operator never used) must go through
    :func:`operator_answers_from_block`, never this string."""
    authored: list[str] = []
    assumed: list[str] = []
    for c in clarifications or ():
        if not isinstance(c, dict):
            continue
        answer = str(c.get("answer", "")).strip()
        if not answer:
            continue
        if c.get("assumed"):
            assumed.append(_ANSWER_BULLET + _ASSUMED_TAG + answer)
        else:
            authored.append(_ANSWER_BULLET + answer)
    sections: list[str] = []
    if authored:
        sections.append(_REQUIREMENTS_HEADER + "\n" + "\n".join(authored))
    if assumed:
        sections.append(_ASSUMED_HEADER + "\n" + "\n".join(assumed))
    return "\n\n".join(sections)


#: #1237 — the PLANNER-facing gradeability steer, keyed by the real surface a menu answer
#: maps to. The surface vocabulary is owned by ``shared.fleet.acceptance.SURFACE_VALUES``;
#: that module imports THIS one, so the keys are literals rather than a back-import.
#:
#: Why this exists at all. What reaches the planning seed after a surface choice is the
#: menu LABEL — "In a web browser" — and a label is all the operator should ever be shown.
#: But on the quick path that label REPLACES :data:`EMPTY_PROJECT_SURFACE_ANSWER`, which
#: carried a second clause the label does not: "the kind whose behavior can be fully checked
#: automatically". That clause is what steers the planner toward criteria and an exam a
#: machine can run. Now that the criteria and the exam are AUTHORED from this seed, dropping
#: it would let an honestly-answered menu produce a LESS gradeable plan than declining to
#: answer it — the answer punishing the person who gave it.
#:
#: So the steer rides BESIDE the label, never inside it: the operator's words stay verbatim
#: in the record and on the card, and this text is addressed to the planner. It names no
#: platform — overriding his choice is the failure this whole arc is about — and it is
#: rendered as a system-chosen line, so the #1161 operator-words platform scan
#: (:func:`operator_authored_answers`) drops it instead of reading a platform out of it.
#:
#: "Names no platform" is a claim about words this module does not own, so it is GATE-LOCKED
#: rather than asserted: ``test_the_gradeability_steer_is_for_the_planner_and_names_no_platform``
#: drives every steer through :func:`~shared.fleet.acceptance.operator_platform_signal`. When
#: the weak-tier vocabulary widened to include bare "page" (#1161 F-A), that lock failed on
#: the web steer's own prose the same commit — which is the only reason this line reads
#: "view" today. Reword defensively when editing: the authority for what counts as a
#: platform word is ``acceptance.OPERATOR_WEB_VOCABULARY`` and the explicit-word patterns
#: beside it, never this comment.
SURFACE_GRADEABILITY_STEER: dict[str, str] = {
    "desktop-gui": (
        "the window is only the face — every rule and calculation it performs must live "
        "in plain importable code the automated checks can call directly, and the project "
        "must ship one test command that runs them without a person watching"
    ),
    "web": (
        # "view", not "page": bare "page" became a weak-tier WEB term in the operator
        # vocabulary (#1161 F-A), and this is system prose. The lock below caught it the
        # moment the vocabulary widened — see the note on naming no platform.
        "the view is only the face — every rule and calculation it performs must live in "
        "plain importable code the automated checks can call directly, and the project "
        "must ship one test command that runs them without a person watching"
    ),
    "mobile": (
        "the screen is only the face — every rule and calculation it performs must live "
        "in plain importable code the automated checks can call directly, and the project "
        "must ship one test command that runs them without a person watching"
    ),
}


def surface_gradeability_steer(surface: str) -> str:
    """The planner-facing gradeability steer for *surface*, or ``""`` when there is none to
    give (#1237) — see :data:`SURFACE_GRADEABILITY_STEER`.

    Pure + total: a blank, unknown or off-vocabulary surface yields ``""``, so a caller may
    run it unconditionally and a surface the platform menu cannot produce contributes
    nothing rather than a guess."""
    return SURFACE_GRADEABILITY_STEER.get((surface or "").strip().lower(), "")


def compose_planning_steer(requirements_block: str, steer: str) -> str:
    """Append the PLANNER-ONLY gradeability steer to a rendered requirements block (#1237).

    Deliberately NOT part of :func:`compose_requirements_block`. That block is the RECORD's
    rendering — its lines are the operator's answers plus this module's headers, and
    :func:`shared.fleet.acceptance.recompose_task_requirements` rebuilds it from the
    clarifications alone. The steer is neither an answer nor part of the record; it belongs
    to the ONE seed handed to the planner after a surface choice, so it is composed at that
    call site and nothing durable carries it.

    Rendered as an assumed line under its own header so both extractors classify it
    correctly: :func:`operator_authored_answers` drops it (a system line must never count
    as the operator having named something) while :func:`operator_answers_from_block` keeps
    it (it is requirement content the coder was given). A blank steer returns the block
    unchanged; a steer with an empty block still renders, because having nothing else to
    say does not make the constraint untrue. Pure + total."""
    text = (steer or "").strip()
    if not text:
        return requirements_block or ""
    section = _STEER_HEADER + "\n" + _ANSWER_BULLET + _ASSUMED_TAG + text
    base = (requirements_block or "").strip()
    return base + "\n\n" + section if base else section


def record_operator_surface_choice(
    clarifications: "list[dict] | tuple[dict, ...]", chosen_label: str,
    *, question: str = "",
) -> list[dict]:
    """Record the platform the operator just picked from the menu as an ANSWERED (
    ``assumed=False``) surface clarification (#1197) — rewriting the assumed surface entry
    when there is one, and APPENDING one when there is not (#1237).

    Without this the fix asks the question and then discards the answer. The clarifying
    turn refines ``build_plan.surface``, but the clarification LIST is carried forward
    untouched — so an operator who was asked "where will you mainly use this?", answered
    "In a web browser", and got ``build_plan.surface == "web"`` still had
    ``EMPTY_PROJECT_SURFACE_ANSWER`` ("a simple command-line tool …") riding into the
    coder's requirements block as a live requirement. The build signal and the written
    requirement contradicted each other, and the one the coder READS is the requirement.

    That was reachable before only on the opt-in intake path; making the gate fire on the
    default quick path is what puts every operator through it, so it is fixed here rather
    than left as the fix's own new lie.

    The REWRITE targets exactly what :func:`shared.fleet.acceptance.platform_was_assumed`
    targets — an ``assumed`` entry tagged with the surface axis — so the thing that RAISES
    the forced question and the thing that RECORDS its answer can never disagree about which
    entry is the surface.

    The APPEND is why a rewrite alone was not enough. The menu has two entry points, and the
    other one — the model-flagged ambiguous fork — fires REGARDLESS of clarifications, so the
    list it hands here is routinely empty and there is no entry to rewrite. Returning it
    unchanged made the operator's answer reach nothing: an empty list composes an empty
    requirements block, which composes the bare goal, which is the seed the pre-choice pass
    already ran on. The re-plan then discarded the plan the menu was raised about and
    authored a different one from the same platform-blind seed, under a note saying his
    choice had been applied (#1237). So when nothing was rewritten, the answer is APPENDED as
    an authored surface-axis entry: one shape reaches the seed on both paths, and
    :func:`compose_requirements_block` renders it identically either way.

    An existing authored entry is never overwritten — a free-text reply carries the operator's
    words for EVERY axis it answered in one entry, so rewriting it to a platform label would
    destroy the rest of what he said. Such a path records a second, more specific surface
    answer beside the prose rather than replacing it.

    *question* is the question the operator was actually shown; it labels the appended entry
    and is unused on the rewrite path (the existing entry keeps the question it was asked
    under). Pure: returns a new list, never mutates its input. A blank label records nothing
    and returns the entries unchanged."""
    label = (chosen_label or "").strip()
    entries = [dict(c) for c in (clarifications or ()) if isinstance(c, dict)]
    if not label:
        return entries
    rewrote = False
    for entry in entries:
        if not entry.get("assumed"):
            continue
        axes = entry.get("axes")
        if isinstance(axes, (list, tuple)) and AXIS_SURFACE in axes:
            entry["answer"] = label
            entry["assumed"] = False
            rewrote = True
    if not rewrote:
        entries.append({
            "question": (question or "").strip(),
            "answer": label,
            "assumed": False,
            "axes": [AXIS_SURFACE],
        })
    return entries


def operator_answers_from_block(block: str) -> tuple[str, ...]:
    """The OPERATOR-SUPPLIED text carried by a rendered requirements block, with this
    module's own boilerplate stripped — the inverse of :func:`compose_requirements_block`
    for the answer content (the questions are never rendered into the block at all).

    Exists because the rendered block is prompt text: it opens with a fixed house header
    and tags assumed answers, so a consumer that must not confer authority on words the
    operator never used (:func:`shared.fleet.oracle_qa._spec_corpus`) cannot use the blob.
    Feeding it the header instead grounds the judge on "person", "build", "requirements"
    and friends — words no operator uttered (#1043 review F1).

    Conservative in the safe direction: the ONLY things removed are this module's own
    header lines (:data:`_BLOCK_HEADERS` — #1197 added the assumed-answers header, and it
    is dropped here for the same reason the first one is) and the bullet/``(assumed)``
    markers it wrote. Every other line survives verbatim, so a multi-line operator answer
    keeps its continuation lines. Pure + total — an empty/blank/header-less string yields
    ``()``, and it never raises."""
    out: list[str] = []
    for raw in (block or "").splitlines():
        line = raw.strip()
        if not line or line in _BLOCK_HEADERS:
            continue
        if line.startswith(_ANSWER_BULLET):
            line = line[len(_ANSWER_BULLET):].lstrip()
            if line.startswith(_ASSUMED_TAG):
                line = line[len(_ASSUMED_TAG):].lstrip()
        if line:
            out.append(line)
    return tuple(out)


def operator_authored_answers(block: str) -> tuple[str, ...]:
    """Like :func:`operator_answers_from_block`, but ONLY the answers the operator actually
    AUTHORED — every ``(assumed)``-tagged line (a system-chosen default from "just decide
    for me") is dropped entirely, not merely unwrapped.

    Exists for #1161's platform scan: whether the operator NAMED a platform must be read
    from the operator's own words, and an assumed default that mentions a device ("a simple
    app that runs on this computer") must never count as the operator having answered the
    platform question — that inversion is precisely the silent-default failure the scan
    guards. Same conservative shape as its sibling: only this module's own header, bullet
    and tag markers are interpreted; continuation lines of a kept answer survive verbatim.
    Known limit, safe direction: a continuation line of an ASSUMED answer is not
    distinguishable from a kept answer's and would survive — today's assumed defaults are
    single-line constants, and a false KEEP here can only suppress a default, never force
    one. Pure + total; ``()`` for empty/blank input, never raises."""
    out: list[str] = []
    for raw in (block or "").splitlines():
        line = raw.strip()
        if not line or line in _BLOCK_HEADERS:
            continue
        if line.startswith(_ANSWER_BULLET):
            line = line[len(_ANSWER_BULLET):].lstrip()
            if line.startswith(_ASSUMED_TAG):
                continue
        if line:
            out.append(line)
    return tuple(out)


def compose_planning_goal(goal: str, requirements_block: str) -> str:
    """Append the requirements block to the goal across the plan seam, sentinel-delimited.
    Returns the plain goal unchanged when the block is empty (byte-identical to today)."""
    base = (goal or "").strip()
    block = (requirements_block or "").strip()
    if not block:
        return base
    return base + REQUIREMENTS_SENTINEL + block


def split_planning_goal(goal: str) -> tuple[str, str]:
    """Inverse of :func:`compose_planning_goal`: split an enriched goal into
    ``(clean_goal, requirements_block)``. A goal without the sentinel returns
    ``(goal_stripped, "")`` — so a plain PLAN request is byte-identical to today. Pure +
    total (never raises); the block is whatever followed the FIRST sentinel."""
    raw = goal or ""
    if REQUIREMENTS_SENTINEL not in raw:
        return raw.strip(), ""
    head, _, tail = raw.partition(REQUIREMENTS_SENTINEL)
    return head.strip(), tail.strip()


# ---------------------------------------------------------------------------
# Token-cost measurement (the enriched block's budget — reported per #819)
# ---------------------------------------------------------------------------


def estimate_tokens(text: str) -> int:
    """A deterministic, dependency-free ESTIMATE of a text's token cost.

    Not the model's exact tokeniser (the Qwen3 BPE is only available on the GPU substrate) —
    a portable heuristic for the token-budget discipline (#819): the larger of the whitespace
    word count and ``ceil(chars / 4)`` (the common ~4-chars-per-token English rule of thumb),
    which brackets a short English requirements block within a token or two. Reported, not
    gated. ``0`` for empty."""
    s = (text or "").strip()
    if not s:
        return 0
    words = len(s.split())
    chars = math.ceil(len(s) / 4)
    return max(words, chars)
