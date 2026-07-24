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

#: The closed axis vocabulary — the ONLY values a question may be tagged with (the grammar
#: enum + the ruler both pin to this). An unknown axis coerces to ``feature`` (the safe,
#: always-relevant default) rather than dropping the question.
CLARIFY_AXES: frozenset[str] = frozenset(
    {AXIS_SURFACE, AXIS_PERSISTENCE, AXIS_FEATURE, AXIS_VISUAL, AXIS_SCOPE}
)
_AXIS_FALLBACK = AXIS_FEATURE

#: Hard cap on questions asked from one goal (the "a few, not a quiz" rule). 5 == one per
#: axis at most; the ruler dedupes by axis so the operator is never asked the same axis twice.
DEFAULT_MAX_QUESTIONS = 5

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
}


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

# Pull the first JSON array out of a model response (it may wrap it in prose/fences).
_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)


def clarify_questions_emission_json_schema(
    *, max_questions: int = DEFAULT_MAX_QUESTIONS
) -> dict:
    """The JSON schema for a grammar-constrained CLARIFY emission — the same
    ``{axis, question}`` shape :func:`_parse_questions` expects, with ``axis`` pinned to
    :data:`CLARIFY_AXES` and the vacuous floor applied at the source. An empty array is a
    VALID constrained answer (the sufficient goal) — ``minItems`` is intentionally omitted
    so ``[]`` is accepted rather than forcing a needless question."""
    return {
        "type": "array",
        "maxItems": max_questions,
        "items": {
            "type": "object",
            "properties": {
                "axis": {"enum": sorted(CLARIFY_AXES)},
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


def _parse_questions(text: str, *, max_questions: int) -> tuple[ClarifyQuestion, ...]:
    """Best-effort parse of the model output into validated questions; ``()`` on failure.

    The model PROPOSES; this DISPOSES (mirrors the acceptance rulers): keep only
    ``{axis, question}`` objects whose question clears the vacuous floor; coerce an unknown
    axis to :data:`_AXIS_FALLBACK`; DEDUPE by axis (one question per axis — a novice is never
    asked the same decision twice); cap. Order preserved. An empty/garbage emission yields
    ``()`` (the sufficient goal — no questions asked). Never raises."""
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
        if axis not in CLARIFY_AXES:
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
) -> tuple[ClarifyQuestion, ...]:
    """The 14B proposes clarifying questions for an underspecified goal; the ruler disposes.

    This IS the sufficiency check: a goal that already carries the decision axes yields ``()``
    (the model returns ``[]``), so the caller asks NOTHING and proceeds straight to decompose
    — never a mandatory quiz. #743: the emission is tried grammar-constrained FIRST (schema
    enum-pinned to :data:`CLARIFY_AXES`) with a transparent fail-soft to the free-text path.

    Fail-soft is absolute — ANY failure (blank goal, no hook, hook raises, model raises,
    empty/garbage output) returns ``()`` so the dispatch degrades to today's direct decompose.
    The model call is injected so this is fully testable without the GPU."""
    idea = (goal or "").strip()
    if not idea:
        return ()
    prompt = _CLARIFY_TEMPLATE.format(max_questions=max_questions, idea=idea)
    raw = _grammar_first(
        prompt,
        structured_generate_fn=structured_generate_fn,
        schema=clarify_questions_emission_json_schema(max_questions=max_questions),
    )
    if raw is None:
        try:
            raw = generate_fn(prompt)
        except Exception:  # noqa: BLE001 — a clarify failure must degrade, never crash
            return ()
    return _parse_questions(raw, max_questions=max_questions)


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


def is_decide_for_me(text: str) -> bool:
    """True iff the operator's reply means "just decide for me" (the escape hatch)."""
    norm = re.sub(r"\s+", " ", (text or "").strip().lower()).strip(" .!?,")
    return norm in _DECIDE_PHRASES


def questions_from_dicts(raw: object) -> tuple[ClarifyQuestion, ...]:
    """Reconstruct :class:`ClarifyQuestion` objects from ``{axis, question}`` dicts (the wire /
    stored shape). Fail-closed: skips non-dicts and blank questions, coerces an unknown axis to
    :data:`_AXIS_FALLBACK`. ``()`` for a non-list. Never raises — the caller re-derives the
    per-axis defaults/answers from these, so a malformed record must never crash the answer."""
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
        if axis not in CLARIFY_AXES:
            axis = _AXIS_FALLBACK
        out.append(ClarifyQuestion(axis=axis, question=question))
    return tuple(out)


def decide_defaults(questions: "tuple[ClarifyQuestion, ...] | list[ClarifyQuestion]") -> list[dict]:
    """Self-answer each asked question with its per-axis default (the "just decide" path).

    Returns a list of clarification dicts ``{question, answer, assumed}`` with
    ``assumed=True`` — so they render on the plan card as assumptions ("here's what I decided
    for you") and the operator can catch a wrong default and reject. Order preserved."""
    out: list[dict] = []
    for q in questions:
        default = DEFAULT_AXIS_ANSWERS.get(q.axis, DEFAULT_AXIS_ANSWERS[_AXIS_FALLBACK])
        out.append({"question": q.question, "answer": default, "assumed": True})
    return out


def answered_from_free_text(
    questions: "tuple[ClarifyQuestion, ...] | list[ClarifyQuestion]", answer_text: str
) -> list[dict]:
    """Record the operator's free-text reply as a single answered clarification.

    The operator answers all the questions in their own words in ONE reply (the natural,
    novice-friendly shape — no per-question form to fill in); that whole reply becomes the
    enriched requirement. The asked questions are joined for context so the plan card shows
    what was asked alongside what the operator said. ``assumed=False``. A blank reply yields
    ``[]`` (the caller then treats it as "nothing added" and proceeds)."""
    answer = (answer_text or "").strip()
    if not answer:
        return []
    asked = " / ".join(q.question for q in questions).strip()
    return [{"question": asked, "answer": answer, "assumed": False}]


# ---------------------------------------------------------------------------
# Compose the enriched requirements block + carry it across the plan seam
# ---------------------------------------------------------------------------

#: Sentinel delimiting the clarified-requirements block appended to the goal on the
#: coordinator -> plan seam. The plan seam is ``plan_fn(repo, goal)`` (many injected fakes),
#: so rather than widen that signature the enriched block rides INSIDE the goal string and is
#: split back off AO-side (:func:`split_planning_goal`) before ``generate_plan`` — keeping
#: ``spec.goal`` clean. Chosen to be vanishingly unlikely in a real product goal.
REQUIREMENTS_SENTINEL = "\n\n[[BLARAI_CLARIFIED_REQUIREMENTS]]\n"


#: The renderer's own boilerplate. Named constants because :func:`compose_requirements_block`
#: and :func:`operator_answers_from_block` MUST agree on them: the block mixes house prose
#: with the operator's words, and the extractor's whole job is telling them apart. Editing
#: the wording here without the extractor seeing it would silently reclassify house prose as
#: operator text (#1043 review F1).
_REQUIREMENTS_HEADER = "The person clarified these requirements — build to them:"
_ANSWER_BULLET = "- "
_ASSUMED_TAG = "(assumed) "


def compose_requirements_block(clarifications: "list[dict] | tuple[dict, ...]") -> str:
    """Render the clarifications into a COMPACT block for the planning prompts (the coder
    builds to these, the oracle checks them). Token-budget disciplined (P4/P9): one short
    line per clarification, an ``(assumed)`` tag on defaults the operator asked us to pick.
    ``""`` when there is nothing to add (a fully-specified goal / an empty reply) — the plan
    is then byte-identical to today. Never raises.

    The output is PROMPT text: house prose plus the operator's words. Anything that needs
    only the operator's words (a grounding corpus, where house prose would grant authority
    to language the operator never used) must go through
    :func:`operator_answers_from_block`, never this string."""
    lines: list[str] = []
    for c in clarifications or ():
        if not isinstance(c, dict):
            continue
        answer = str(c.get("answer", "")).strip()
        if not answer:
            continue
        prefix = _ANSWER_BULLET + (_ASSUMED_TAG if c.get("assumed") else "")
        lines.append(prefix + answer)
    if not lines:
        return ""
    return _REQUIREMENTS_HEADER + "\n" + "\n".join(lines)


def operator_answers_from_block(block: str) -> tuple[str, ...]:
    """The OPERATOR-SUPPLIED text carried by a rendered requirements block, with this
    module's own boilerplate stripped — the inverse of :func:`compose_requirements_block`
    for the answer content (the questions are never rendered into the block at all).

    Exists because the rendered block is prompt text: it opens with a fixed house header
    and tags assumed answers, so a consumer that must not confer authority on words the
    operator never used (:func:`shared.fleet.oracle_qa._spec_corpus`) cannot use the blob.
    Feeding it the header instead grounds the judge on "person", "build", "requirements"
    and friends — words no operator uttered (#1043 review F1).

    Conservative in the safe direction: the ONLY things removed are the header line and the
    bullet/``(assumed)`` markers this module itself wrote. Every other line survives
    verbatim, so a multi-line operator answer keeps its continuation lines. Pure + total —
    an empty/blank/header-less string yields ``()``, and it never raises."""
    out: list[str] = []
    for raw in (block or "").splitlines():
        line = raw.strip()
        if not line or line == _REQUIREMENTS_HEADER:
            continue
        if line.startswith(_ANSWER_BULLET):
            line = line[len(_ANSWER_BULLET):].lstrip()
            if line.startswith(_ASSUMED_TAG):
                line = line[len(_ASSUMED_TAG):].lstrip()
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
