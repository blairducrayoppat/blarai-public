"""Plan-feedback REVISION stage for headless-coding dispatch (#820).

The dispatch plan card is take-it-or-leave-it today: a non-technical operator who wants
*"that, but with the export feature first, and skip the login"* can only **reject** and
re-roll the whole decomposition from scratch — losing the good parts of the plan and any
clarification context. This module is the REVISE stage that sits AFTER the PLAN preview and
BEFORE approval: given the operator's free-text feedback and the current plan's task titles,
the 14B PROPOSES a small set of edit operations (keep / add / re-scope) over the EXISTING
plan; a DETERMINISTIC RULER DISPOSES; and the coordinator APPLIES them — copying a KEPT task
byte-for-byte (never a fresh decompose), inserting the adds, dropping the omissions.

Discipline (mirrors :mod:`shared.fleet.clarify` and :mod:`shared.fleet.acceptance` — the
model PROPOSES, a deterministic ruler DISPOSES):

  * **NOT a fresh decompose.** The model returns EDIT operations that reference the current
    tasks by number, so a task the feedback does not touch is preserved *byte-identically*
    (the ``keep`` op copies the original task dict verbatim). Only add / re-scope / remove /
    reorder change anything — everything else is preserved.
  * **Small-model discipline (#740 c.1721).** Short, single-focus prompt; grammar-first
    structured emission via the #743 hook with a transparent fail-soft to free-text; the
    ruler caps, validates every task reference against the real range, and dedupes so a
    sloppy emission can never corrupt the plan.
  * **Fail-soft is absolute.** Any failure (no hook, hook raises, empty/garbage output, a
    revision that references nothing real) yields ``()`` / ``None`` — the coordinator then
    re-renders the ORIGINAL plan with an honest "couldn't apply that feedback" note. Never a
    lost plan, never a silent accept.
  * **Bounded.** :data:`DEFAULT_MAX_REVISIONS` caps how many times one plan may be refined;
    the coordinator surfaces the remaining count honestly.

This module is PURE + GPU-free (the model call is injected, mirroring
:func:`shared.fleet.clarify.generate_clarifying_questions`) and has NO import from
:mod:`shared.fleet.acceptance` — so acceptance can import revise (for the ``generate_plan``
revise branch) without a cycle, exactly as it imports clarify. The build-field threading of
newly-added tasks is the coordinator's job (it owns the spec), keeping this engine
acceptance-free.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Hard cap on how many times a single pending plan may be refined before the operator must
#: accept or reject. Surfaced honestly on the card ("you can refine this N more time(s)").
#: 3 is generous for a novice narrowing a plan without turning the card into an endless loop.
DEFAULT_MAX_REVISIONS = 3

#: The three edit operations the model may propose over the current plan.
OP_KEEP = "keep"      # preserve an existing task unchanged (byte-identical copy)
OP_ADD = "add"        # introduce a brand-new task
OP_REVISE = "revise"  # replace/re-scope an existing task with a new title + description
_OPS: frozenset[str] = frozenset({OP_KEEP, OP_ADD, OP_REVISE})

#: Hard cap on the number of edit steps parsed from one emission — a small model can loop, and
#: a real plan is a handful of tasks plus a few adds. Bounds the wire + the applied task count.
_MAX_REVISION_STEPS = 12

#: An added/revised task description shorter than this (after strip) is vacuous and dropped.
_MIN_PROMPT_LEN = 5
#: Length cap on a generated task slug (keeps the fleet's ``task`` field sane).
_TASK_SLUG_MAX = 48

# Pull the first JSON array out of a model response (it may wrap it in prose/fences).
_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)


# ---------------------------------------------------------------------------
# Goal-seam embedding — carry the feedback + current task titles to the AO
# ---------------------------------------------------------------------------
#
# The coordinator -> AO plan seam is ``plan_fn(repo, goal)`` (many injected fakes). Rather
# than widen that signature (or mint a fresh IPC verb), the revise REQUEST rides INSIDE the
# goal string across that one hop, sentinel-delimited, and the AO splits it back off
# (:func:`split_revision_goal`) before running the revise model call — the EXACT pattern
# #819 used for clarified requirements. Chosen to be vanishingly unlikely in a real goal.

REVISE_SENTINEL = "\n\n[[BLARAI_PLAN_REVISION]]\n"


def compose_revision_goal(goal: str, feedback: str, task_titles: "list[str] | tuple[str, ...]") -> str:
    """Embed the operator's *feedback* + the current plan's *task_titles* into the goal for the
    ``plan_fn(repo, goal)`` hop. The AO splits it back off with :func:`split_revision_goal`.
    Pure + total (never raises)."""
    payload = json.dumps(
        {"feedback": (feedback or "").strip(), "tasks": [str(t) for t in (task_titles or ())]}
    )
    return (goal or "").strip() + REVISE_SENTINEL + payload


def split_revision_goal(goal: str) -> "tuple[str, str, list[str]]":
    """Inverse of :func:`compose_revision_goal`: split an embedded goal into
    ``(clean_goal, feedback, task_titles)``. A goal WITHOUT the sentinel returns
    ``(goal_stripped, "", [])`` (a plain plan request, byte-identical to today). Fail-soft: a
    malformed payload returns the clean head with empty feedback/titles. Never raises."""
    raw = goal or ""
    if REVISE_SENTINEL not in raw:
        return raw.strip(), "", []
    head, _, tail = raw.partition(REVISE_SENTINEL)
    try:
        data = json.loads(tail.strip())
    except (ValueError, TypeError):
        return head.strip(), "", []
    if not isinstance(data, dict):
        return head.strip(), "", []
    feedback = str(data.get("feedback", "")).strip()
    raw_tasks = data.get("tasks")
    titles = (
        [str(t).strip() for t in raw_tasks if str(t).strip()]
        if isinstance(raw_tasks, list)
        else []
    )
    return head.strip(), feedback, titles


# ---------------------------------------------------------------------------
# The revise operation (the 14B proposes; the ruler disposes)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReviseOp:
    """One validated edit operation over the current plan.

    ``keep``   -> preserve current feature-task number ``ref`` (1-based) unchanged.
    ``add``    -> a brand-new task with ``task`` (slug) + ``prompt`` (what to build).
    ``revise`` -> replace current task ``ref`` with the new ``task`` slug + ``prompt``.
    """

    op: str
    ref: int = 0
    task: str = ""
    prompt: str = ""

    def to_dict(self) -> dict:
        return {"op": self.op, "ref": self.ref, "task": self.task, "prompt": self.prompt}


def _slugify(name: str) -> str:
    """A safe lowercase fleet task slug — a strict ``[a-z0-9]`` allowlist (runs collapsed to
    ``-``, trimmed, length-capped). ``''`` (the op is then dropped fail-closed) if nothing
    usable remains. No dots/separators/traversal, mirroring the asset-slug discipline."""
    slug = re.sub(r"[^a-z0-9]+", "-", str(name).strip().lower()).strip("-")
    return slug[:_TASK_SLUG_MAX]


def _humanize_slug(slug: str) -> str:
    """Turn a task slug (``add-calc``) into a display name (``Add calc``) — hyphens/underscores
    to spaces, first letter capitalized. Matches ``acceptance._humanize_task_name`` so the delta
    reads the same as the plan card (replicated here to keep this module acceptance-free)."""
    s = str(slug or "").replace("-", " ").replace("_", " ").strip()
    return s[:1].upper() + s[1:] if s else s


_REVISE_TEMPLATE = (
    "A non-technical person reviewed this build plan and asked for changes. REVISE the plan to "
    "match their feedback — add, remove, reorder, or re-scope tasks as they ask — but KEEP every "
    "task the feedback does NOT touch exactly as it is (do not reword or re-split it). Return "
    "ONLY a JSON array (no prose) listing the tasks in the FINAL order the work should happen. "
    "Each item is exactly one of:\n"
    '  {{"op": "keep", "ref": <number of an existing task to keep unchanged>}}\n'
    '  {{"op": "add", "task": "<short-slug>", "prompt": "<plain description of what to build>"}}\n'
    '  {{"op": "revise", "ref": <number of an existing task to replace>, '
    '"task": "<short-slug>", "prompt": "<plain description of the new scope>"}}\n'
    "Only reference task numbers that appear below. To REMOVE a task, simply leave it out. The "
    "ORDER of your array is the order the tasks will run. Keep it to the few real changes the "
    "feedback asks for.\n\n"
    "The overall goal:\n{goal}\n\n"
    "The current plan:\n{plan}\n\n"
    "The person's feedback:\n{feedback}\n"
)


def revision_ops_emission_json_schema() -> dict:
    """The JSON schema for a grammar-constrained REVISE emission — the ``{op, ref, task, prompt}``
    shape :func:`_parse_revision_ops` expects, with ``op`` pinned to :data:`_OPS`. Per-op
    required-field coupling (``keep`` needs ``ref``; ``add`` needs ``task``+``prompt``) is not
    expressible in the flat item schema, so the grammar guarantees the enum + shape and the ruler
    still disposes. ``minItems: 1`` — an empty revision is never useful (it degrades to fail-soft
    re-rendering the original), so an empty emission falls back to the free-text path."""
    return {
        "type": "array",
        "minItems": 1,
        "maxItems": _MAX_REVISION_STEPS,
        "items": {
            "type": "object",
            "properties": {
                "op": {"enum": sorted(_OPS)},
                "ref": {"type": "integer"},
                "task": {"type": "string", "maxLength": _TASK_SLUG_MAX},
                "prompt": {"type": "string"},
            },
            "required": ["op"],
            "additionalProperties": False,
        },
    }


def _is_json_array(text: str) -> bool:
    """True iff *text* carries a parseable JSON array (used by the grammar-first gate)."""
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

    Self-contained (revise has NO import from acceptance, so acceptance can import revise
    without a cycle). Tries *structured_generate_fn* FIRST, called ``(prompt, json_schema_text)``;
    returns the raw text ONLY when the hook exists, did not raise, and produced a usable JSON
    array; ``None`` in EVERY other case — the caller then runs the free-text path unchanged."""
    if structured_generate_fn is None:
        return None
    try:
        raw = structured_generate_fn(prompt, json.dumps(schema))
    except Exception:  # noqa: BLE001 — the hook must never add a failure mode
        return None
    if raw and _is_json_array(raw):
        return raw
    return None


def _parse_revision_ops(text: str, *, n_tasks: int) -> tuple[ReviseOp, ...]:
    """Best-effort parse of the model output into validated edit ops; ``()`` on failure.

    The model PROPOSES; this DISPOSES (mirrors the clarify/acceptance rulers): keep only
    well-shaped items whose op is one of :data:`_OPS`; validate a ``keep``/``revise`` ``ref``
    against the REAL ``[1, n_tasks]`` range and DEDUPE it (a task can be referenced once —
    never kept twice, never kept-and-revised); require a non-blank slug + description on
    ``add``/``revise``; cap the total steps. Order preserved. An empty/garbage emission, or one
    that survives to zero ops, yields ``()`` (the caller then fails soft). Never raises."""
    if not text or n_tasks < 0:
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
    out: list[ReviseOp] = []
    used_refs: set[int] = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        op = str(item.get("op", "")).strip().lower()
        if op not in _OPS:
            continue
        if op == OP_ADD:
            slug = _slugify(item.get("task", ""))
            prompt = str(item.get("prompt", "")).strip()
            if not slug or len(prompt) < _MIN_PROMPT_LEN:
                continue
            out.append(ReviseOp(op=OP_ADD, task=slug, prompt=prompt))
        else:  # keep | revise — both reference an existing task by number
            ref = _coerce_ref(item.get("ref"))
            if ref is None or not (1 <= ref <= n_tasks) or ref in used_refs:
                continue
            if op == OP_KEEP:
                used_refs.add(ref)
                out.append(ReviseOp(op=OP_KEEP, ref=ref))
            else:  # OP_REVISE
                slug = _slugify(item.get("task", ""))
                prompt = str(item.get("prompt", "")).strip()
                if not slug or len(prompt) < _MIN_PROMPT_LEN:
                    continue
                used_refs.add(ref)
                out.append(ReviseOp(op=OP_REVISE, ref=ref, task=slug, prompt=prompt))
        if len(out) >= _MAX_REVISION_STEPS:
            break
    return tuple(out)


def _coerce_ref(raw: object) -> "int | None":
    """Coerce a model-supplied ``ref`` to an int (the small model may emit ``"2"`` or ``2.0``);
    ``None`` for anything non-integral. Never raises."""
    if isinstance(raw, bool):  # bool is an int subclass — reject it explicitly
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw) if raw.is_integer() else None
    if isinstance(raw, str) and raw.strip().lstrip("-").isdigit():
        return int(raw.strip())
    return None


def generate_revision_ops(
    goal: str,
    task_titles: "list[str] | tuple[str, ...]",
    feedback: str,
    *,
    generate_fn: Callable[[str], str],
    structured_generate_fn: "Callable[[str, str], str] | None" = None,
) -> tuple[ReviseOp, ...]:
    """The 14B proposes edit operations to revise the current plan per the operator's *feedback*;
    the ruler disposes. Runs AO-side (the model is resident) via :func:`generate_plan`'s revise
    branch. #743: the emission is tried grammar-constrained FIRST with a transparent fail-soft to
    the free-text path.

    Fail-soft is absolute — ANY failure (blank feedback, no tasks, no hook, hook raises, model
    raises, empty/garbage output) returns ``()`` so the coordinator re-renders the original plan
    untouched. The model call is injected so this is fully testable without the GPU."""
    fb = (feedback or "").strip()
    titles = [str(t).strip() for t in (task_titles or ()) if str(t).strip()]
    if not fb or not titles:
        return ()
    plan_block = "\n".join(f"{i}. {t}" for i, t in enumerate(titles, start=1))
    prompt = _REVISE_TEMPLATE.format(goal=(goal or "").strip(), plan=plan_block, feedback=fb)
    raw = _grammar_first(
        prompt,
        structured_generate_fn=structured_generate_fn,
        schema=revision_ops_emission_json_schema(),
    )
    if raw is None:
        try:
            raw = generate_fn(prompt)
        except Exception:  # noqa: BLE001 — a revise failure must degrade, never crash
            return ()
    return _parse_revision_ops(raw, n_tasks=len(titles))


def ops_from_dicts(raw: object) -> tuple[ReviseOp, ...]:
    """Reconstruct :class:`ReviseOp` objects from ``{op, ref, task, prompt}`` dicts (the wire
    shape carried by ``PlanResult.revision``). Fail-closed: skips non-dicts and unknown ops,
    coerces ``ref`` fail-soft. ``()`` for a non-list. Never raises — a malformed record must
    never crash the coordinator's apply step. NOTE: this does NOT re-validate ``ref`` against a
    task count (that is :func:`apply_revision_ops`'s job, which holds the real task list)."""
    if not isinstance(raw, list):
        return ()
    out: list[ReviseOp] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        op = str(item.get("op", "")).strip().lower()
        if op not in _OPS:
            continue
        ref = _coerce_ref(item.get("ref")) or 0
        out.append(
            ReviseOp(
                op=op,
                ref=ref,
                task=_slugify(item.get("task", "")) if op != OP_KEEP else "",
                prompt=str(item.get("prompt", "")).strip() if op != OP_KEEP else "",
            )
        )
    return tuple(out)


# ---------------------------------------------------------------------------
# Apply the ops to the current plan (coordinator-side; byte-stable keeps)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RevisionOutcome:
    """The result of applying edit ops to the current feature tasks.

    ``tasks`` are the revised feature-task dicts: a ``keep`` is a byte-identical COPY of the
    original dict (build fields and folded test block intact); an ``add``/``revise`` is a fresh
    ``{repo, task, prompt}`` dict the coordinator threads build fields onto. The ``*_titles``
    lists + ``reordered`` drive the plain-language CHANGED-vs-KEPT delta. ``changed`` is False
    only when the ops reproduce the current plan exactly (all-keep, same order) — the coordinator
    treats that as a no-op fail-soft rather than minting an identical "new" pending plan."""

    tasks: list[dict] = field(default_factory=list)
    kept_titles: list[str] = field(default_factory=list)
    added_titles: list[str] = field(default_factory=list)
    revised_titles: list[str] = field(default_factory=list)
    removed_titles: list[str] = field(default_factory=list)
    reordered: bool = False
    changed: bool = False


def _task_title(task: dict) -> str:
    """Display title for a compiled task dict (humanized ``task`` slug)."""
    return _humanize_slug(str(task.get("task", "")))


def apply_revision_ops(
    current_feature_tasks: "list[dict]", ops: "tuple[ReviseOp, ...] | list[ReviseOp]", *, repo: str
) -> "RevisionOutcome | None":
    """Apply validated edit *ops* to *current_feature_tasks*, byte-stable for kept tasks.

    Returns ``None`` (fail-soft — the coordinator re-renders the ORIGINAL plan) when there are no
    ops or the ops survive to an empty task list. A ``keep`` copies the original task dict
    verbatim (``dict(original)``) — the untouched-task-preserved-byte-stable guarantee; an
    ``add``/``revise`` produces a fresh ``{repo, task, prompt}`` dict (the coordinator threads
    build fields on ALL returned tasks — idempotent for the kept ones since the spec is
    unchanged). ``ref`` values are re-validated against the real range here too (defense in depth
    over the wire). Pure + total — never raises."""
    if not ops:
        return None
    n = len(current_feature_tasks)
    tasks: list[dict] = []
    kept_titles: list[str] = []
    added_titles: list[str] = []
    revised_titles: list[str] = []
    used_refs: set[int] = set()
    kept_orig_order: list[int] = []
    for op in ops:
        if op.op == OP_KEEP:
            idx = op.ref - 1
            if not (0 <= idx < n) or op.ref in used_refs:
                continue
            used_refs.add(op.ref)
            copy = dict(current_feature_tasks[idx])
            tasks.append(copy)
            kept_titles.append(_task_title(copy))
            kept_orig_order.append(idx)
        elif op.op == OP_REVISE:
            idx = op.ref - 1
            if not (0 <= idx < n) or op.ref in used_refs or not op.task or len(op.prompt) < _MIN_PROMPT_LEN:
                continue
            used_refs.add(op.ref)
            tasks.append({"repo": repo, "task": op.task, "prompt": op.prompt})
            revised_titles.append(_humanize_slug(op.task))
        elif op.op == OP_ADD:
            if not op.task or len(op.prompt) < _MIN_PROMPT_LEN:
                continue
            tasks.append({"repo": repo, "task": op.task, "prompt": op.prompt})
            added_titles.append(_humanize_slug(op.task))
    if not tasks:
        return None
    removed_titles = [
        _task_title(current_feature_tasks[i]) for i in range(n) if (i + 1) not in used_refs
    ]
    reordered = kept_orig_order != sorted(kept_orig_order)
    changed = bool(added_titles or revised_titles or removed_titles or reordered)
    return RevisionOutcome(
        tasks=tasks,
        kept_titles=kept_titles,
        added_titles=added_titles,
        revised_titles=revised_titles,
        removed_titles=removed_titles,
        reordered=reordered,
        changed=changed,
    )


def render_revision_delta(outcome: RevisionOutcome, feedback: str) -> str:
    """Render the plain-language CHANGED-vs-KEPT delta that LEADS the re-rendered plan card, so a
    non-technical operator SEES exactly what their feedback did before approving. The full new
    task list is shown by the criteria preview below; this section highlights only the change."""
    fb = (feedback or "").strip()
    lines = [f"I revised the plan from your feedback (“{fb}”):", ""]
    if outcome.added_titles:
        lines.append("  Added:")
        lines.extend(f"    + {t}" for t in outcome.added_titles)
    if outcome.revised_titles:
        lines.append("  Changed:")
        lines.extend(f"    ~ {t}" for t in outcome.revised_titles)
    if outcome.removed_titles:
        lines.append("  Removed:")
        lines.extend(f"    - {t}" for t in outcome.removed_titles)
    if outcome.reordered:
        lines.append("  (Reordered the remaining steps.)")
    if not (
        outcome.added_titles or outcome.revised_titles or outcome.removed_titles or outcome.reordered
    ):
        lines.append("  (No changes — the plan is the same.)")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CRITERIA revision (#1055 part 2 / #1069 S3 slice G)
# ---------------------------------------------------------------------------
#
# The #820 machinery above edits the TASK list; the #1055 dead-end was that criteria could
# not be edited at all — the honest message (slice A) routes the operator to reject +
# re-dispatch. This block is the real capability behind that message, with a HARD WALL the
# task machinery does not need:
#
#   MACHINE-GATED TIERS (build / behavior / smoke) ARE KEEP-ONLY. The folded test block in
#   the compiled task prompts and the riding job exam consume ONLY machine-tier criteria,
#   and both are frozen at plan time by the #820 safety asymmetry (a revision can never
#   weaken — or change — the machine gate). If a criteria revision could edit a machine
#   criterion, the card would show one assertion while the exam tested another: a
#   divergence trap wearing an edit box. Keeping them immutable here means NOTHING the
#   coder or the exam consumes can change through this path, so the card, the prompts and
#   the exam cannot disagree, by construction. The operator-judged tiers (visual / human)
#   are the operator's own checklist — those are fully editable, and an added criterion is
#   FORCED to the human tier for the same reason (a post-plan addition must never mint a
#   machine check nobody authored an exam for).
#
# Same discipline as everything above: the model proposes, a deterministic ruler disposes,
# fail-soft is absolute, and the request rides the goal string over the existing plan seam
# behind its own sentinel — no new IPC verb.

CRITERIA_REVISE_SENTINEL = "\n\n[[BLARAI_CRITERIA_REVISION]]\n"

#: The criteria tiers the machine gates consume — KEEP-ONLY through this path. Replicated
#: from acceptance's TEST_TIERS + build tier (this module stays acceptance-free; the
#: equality is pinned by test, the same pattern as the sandbox-prefix mirror).
MACHINE_TIERS: frozenset[str] = frozenset({"build", "behavior", "smoke"})
#: The operator-judged tiers — fully editable; the forced tier for an added criterion.
JUDGED_TIERS: frozenset[str] = frozenset({"visual", "human"})

_CRITERIA_OP_KEEP = "keep"
_CRITERIA_OP_RESCOPE = "rescope"
_CRITERIA_OP_ADD = "add"
_CRITERIA_OPS: frozenset[str] = frozenset(
    {_CRITERIA_OP_KEEP, _CRITERIA_OP_RESCOPE, _CRITERIA_OP_ADD}
)

#: Bounds for criteria ops — same rationale as the task caps above.
_MAX_CRITERIA_REVISION_STEPS = 16
_MIN_CRITERION_LEN = 5
_CRITERION_TEXT_MAX = 300


def compose_criteria_revision_goal(
    goal: str, feedback: str, criteria: "list[dict] | tuple[dict, ...]"
) -> str:
    """Embed the operator's *feedback* + the current criteria set into the goal for the
    ``plan_fn(repo, goal)`` hop, behind :data:`CRITERIA_REVISE_SENTINEL`. Each criterion
    rides as ``{id, text, tier, check}``. Pure + total (never raises)."""
    rows = [
        {"id": str(c.get("id", "")), "text": str(c.get("text", "")),
         "tier": str(c.get("tier", "")), "check": str(c.get("check", ""))}
        for c in (criteria or ()) if isinstance(c, dict)
    ]
    payload = json.dumps({"feedback": (feedback or "").strip(), "criteria": rows})
    return (goal or "").strip() + CRITERIA_REVISE_SENTINEL + payload


def split_criteria_revision_goal(goal: str) -> "tuple[str, str, list[dict]]":
    """Inverse of :func:`compose_criteria_revision_goal`:
    ``(clean_goal, feedback, criteria_rows)``. A goal WITHOUT the sentinel returns
    ``(goal_stripped, "", [])``. Fail-soft on a malformed payload. Never raises."""
    raw = goal or ""
    if CRITERIA_REVISE_SENTINEL not in raw:
        return raw.strip(), "", []
    head, _, tail = raw.partition(CRITERIA_REVISE_SENTINEL)
    try:
        data = json.loads(tail.strip())
    except (ValueError, TypeError):
        return head.strip(), "", []
    if not isinstance(data, dict):
        return head.strip(), "", []
    feedback = str(data.get("feedback", "")).strip()
    raw_rows = data.get("criteria")
    rows = [dict(r) for r in raw_rows if isinstance(r, dict)] if isinstance(raw_rows, list) else []
    return head.strip(), feedback, rows


@dataclass(frozen=True)
class CriteriaReviseOp:
    """One validated edit operation over the criteria set.

    ``keep``    -> preserve criterion number ``ref`` (1-based) unchanged.
    ``rescope`` -> replace criterion ``ref``'s wording (judged tiers only; the ruler
                   discards a rescope aimed at a machine tier and reports it protected).
    ``add``     -> a new operator-judged criterion (tier FORCED to ``human``).
    """

    op: str
    ref: int = 0
    text: str = ""
    check: str = ""

    def to_dict(self) -> dict:
        return {"op": self.op, "ref": self.ref, "text": self.text, "check": self.check}


_CRITERIA_REVISE_TEMPLATE = (
    "A non-technical person reviewed what their build will be judged on and asked for "
    "changes. REVISE the list of acceptance criteria to match their feedback — reword, "
    "remove, or add ONLY what the feedback asks; KEEP every criterion the feedback does "
    "not touch exactly as it is. Return ONLY a JSON array (no prose) listing the criteria "
    "in their final order. Each item is exactly one of:\n"
    '  {{"op": "keep", "ref": <number of an existing criterion to keep unchanged>}}\n'
    '  {{"op": "rescope", "ref": <number of an existing criterion to reword>, '
    '"text": "<the new wording>"}}\n'
    '  {{"op": "add", "text": "<a new thing the person will check by eye>"}}\n'
    "To REMOVE a criterion, simply leave it out. Criteria marked [protected] are the "
    "automatic machine checks — you MUST include a keep for each of them; they cannot be "
    "reworded or removed here.\n\n"
    "The overall goal:\n{goal}\n\n"
    "The current criteria:\n{criteria}\n\n"
    "The person's feedback:\n{feedback}\n"
)


def criteria_revision_ops_emission_json_schema() -> dict:
    """Schema for a grammar-constrained CRITERIA-revise emission (the #743 hook shape)."""
    return {
        "type": "array",
        "minItems": 1,
        "maxItems": _MAX_CRITERIA_REVISION_STEPS,
        "items": {
            "type": "object",
            "properties": {
                "op": {"enum": sorted(_CRITERIA_OPS)},
                "ref": {"type": "integer"},
                "text": {"type": "string", "maxLength": _CRITERION_TEXT_MAX},
            },
            "required": ["op"],
            "additionalProperties": False,
        },
    }


def generate_criteria_revision_ops(
    goal: str,
    criteria: "list[dict] | tuple[dict, ...]",
    feedback: str,
    *,
    generate_fn: Callable[[str], str],
    structured_generate_fn: "Callable[[str, str], str] | None" = None,
) -> tuple[CriteriaReviseOp, ...]:
    """The 14B proposes criteria edit ops; the ruler disposes. AO-side, via the criteria
    branch of ``generate_plan``. Machine-tier criteria are rendered ``[protected]`` in the
    prompt AND enforced by the ruler — the prompt is the quality half, the ruler the
    guarantee half, exactly the slice-E split. Fail-soft is absolute: ANY failure returns
    ``()`` and the coordinator re-renders the original card untouched."""
    fb = (feedback or "").strip()
    rows = [c for c in (criteria or ()) if isinstance(c, dict)]
    if not fb or not rows:
        return ()
    listing = "\n".join(
        f"{i}. {'[protected] ' if str(c.get('tier', '')) in MACHINE_TIERS else ''}"
        f"[{c.get('tier', '')}] {c.get('text', '')}"
        for i, c in enumerate(rows, start=1)
    )
    prompt = _CRITERIA_REVISE_TEMPLATE.format(
        goal=(goal or "").strip(), criteria=listing, feedback=fb
    )
    raw = _grammar_first(
        prompt,
        structured_generate_fn=structured_generate_fn,
        schema=criteria_revision_ops_emission_json_schema(),
    )
    if raw is None:
        try:
            raw = generate_fn(prompt)
        except Exception:  # noqa: BLE001 — a revise failure must degrade, never crash
            return ()
    return _parse_criteria_revision_ops(raw, n_criteria=len(rows))


def _parse_criteria_revision_ops(text: str, *, n_criteria: int) -> tuple[CriteriaReviseOp, ...]:
    """Best-effort parse into validated criteria ops; ``()`` on failure. Ref-range checks
    and dedupe as in :func:`_parse_revision_ops`; tier enforcement happens in
    :func:`apply_criteria_revision_ops`, which holds the real tiers. Never raises."""
    if not text or n_criteria < 0:
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
    out: list[CriteriaReviseOp] = []
    used_refs: set[int] = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        op = str(item.get("op", "")).strip().lower()
        if op not in _CRITERIA_OPS:
            continue
        if op == _CRITERIA_OP_ADD:
            text_val = str(item.get("text", "")).strip()[:_CRITERION_TEXT_MAX]
            if len(text_val) < _MIN_CRITERION_LEN:
                continue
            out.append(CriteriaReviseOp(op=op, text=text_val))
        else:  # keep | rescope — both reference an existing criterion
            ref = _coerce_ref(item.get("ref"))
            if ref is None or not (1 <= ref <= n_criteria) or ref in used_refs:
                continue
            if op == _CRITERIA_OP_KEEP:
                used_refs.add(ref)
                out.append(CriteriaReviseOp(op=op, ref=ref))
            else:
                text_val = str(item.get("text", "")).strip()[:_CRITERION_TEXT_MAX]
                if len(text_val) < _MIN_CRITERION_LEN:
                    continue
                used_refs.add(ref)
                out.append(CriteriaReviseOp(op=op, ref=ref, text=text_val))
        if len(out) >= _MAX_CRITERIA_REVISION_STEPS:
            break
    return tuple(out)


def criteria_ops_from_dicts(raw: object) -> tuple[CriteriaReviseOp, ...]:
    """Reconstruct :class:`CriteriaReviseOp` from the ``{op, ref, text, check}`` wire dicts
    (``PlanResult.criteria_revision``). Fail-closed, never raises; RANGE/tier validation is
    :func:`apply_criteria_revision_ops`'s job (it holds the real set), but the seam applies
    the same shape rules the AO-side parser applies (review F4 — wire parity): duplicate
    keep/rescope refs are dropped, an add/rescope below the text floor is dropped, and the
    step cap holds — so a hand-crafted wire payload cannot mint blank rows or
    double-report a protected title."""
    if not isinstance(raw, list):
        return ()
    out: list[CriteriaReviseOp] = []
    used_refs: set[int] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        op = str(item.get("op", "")).strip().lower()
        if op not in _CRITERIA_OPS:
            continue
        text = str(item.get("text", "")).strip()[:_CRITERION_TEXT_MAX]
        if op == _CRITERIA_OP_ADD:
            if len(text) < _MIN_CRITERION_LEN:
                continue
            out.append(CriteriaReviseOp(op=op, text=text))
        else:
            ref = _coerce_ref(item.get("ref")) or 0
            if ref in used_refs:
                continue
            if op == _CRITERIA_OP_RESCOPE and len(text) < _MIN_CRITERION_LEN:
                continue
            used_refs.add(ref)
            out.append(CriteriaReviseOp(
                op=op, ref=ref,
                text=text if op == _CRITERIA_OP_RESCOPE else "",
                check=str(item.get("check", "")).strip(),
            ))
        if len(out) >= _MAX_CRITERIA_REVISION_STEPS:
            break
    return tuple(out)


@dataclass(frozen=True)
class CriteriaRevisionOutcome:
    """The result of applying criteria ops.

    ``criteria`` are the revised rows (``{id, text, tier, check}`` dicts): a kept row is a
    byte-identical copy; a rescoped row keeps its id and tier with new wording and an
    EMPTIED check (the old check verified the old wording — carrying it forward would claim
    a verification nobody re-authored; the realism guard then re-tiers if needed); an added
    row is minted at the ``human`` tier with a fresh non-colliding id. ``protected_titles``
    are machine-tier criteria an op tried to touch (or omit) — auto-kept, and the card says
    so. ``changed`` False ⇒ fail-soft (the coordinator re-renders the original)."""

    criteria: list[dict] = field(default_factory=list)
    kept: int = 0
    rescoped_titles: list[str] = field(default_factory=list)
    added_titles: list[str] = field(default_factory=list)
    removed_titles: list[str] = field(default_factory=list)
    protected_titles: list[str] = field(default_factory=list)
    changed: bool = False


def apply_criteria_revision_ops(
    current: "list[dict] | tuple[dict, ...]",
    ops: "tuple[CriteriaReviseOp, ...] | list[CriteriaReviseOp]",
) -> "CriteriaRevisionOutcome | None":
    """Apply validated *ops* to the current criteria rows, enforcing the tier wall.

    THE WALL, restated where it is enforced: a machine-tier row (:data:`MACHINE_TIERS`) is
    immutable through this path — a ``rescope`` aimed at one is discarded (recorded in
    ``protected_titles``), and an OMITTED machine row is auto-kept in its original position
    rather than dropped. Judged-tier rows may be kept, reworded, dropped by omission, or
    added (added ⇒ ``human`` tier, empty check, fresh id). Returns ``None`` fail-soft for
    no ops or an all-invalid emission. Pure + total — never raises."""
    rows = [dict(c) for c in (current or ()) if isinstance(c, dict)]
    if not ops or not rows:
        return None
    n = len(rows)
    used_refs: set[int] = set()
    out: list[dict] = []
    rescoped_titles: list[str] = []
    added_titles: list[str] = []
    protected_titles: list[str] = []
    kept = 0
    existing_ids = {str(r.get("id", "")) for r in rows}

    def _mint_id() -> str:
        i = 1
        while f"op{i}" in existing_ids:
            i += 1
        existing_ids.add(f"op{i}")
        return f"op{i}"

    for op in ops:
        if op.op == _CRITERIA_OP_ADD:
            added_titles.append(op.text)
            out.append({"id": _mint_id(), "text": op.text, "tier": "human", "check": ""})
            continue
        idx = op.ref - 1
        if not (0 <= idx < n) or op.ref in used_refs:
            continue
        row = rows[idx]
        tier = str(row.get("tier", ""))
        if op.op == _CRITERIA_OP_KEEP:
            used_refs.add(op.ref)
            out.append(dict(row))
            kept += 1
        else:  # rescope
            if tier in MACHINE_TIERS:
                # The wall: recorded, auto-kept below via the omission sweep.
                protected_titles.append(str(row.get("text", "")))
                continue
            used_refs.add(op.ref)
            out.append({"id": str(row.get("id", "")), "text": op.text, "tier": tier,
                        "check": ""})
            rescoped_titles.append(op.text)

    # Omission sweep: an OMITTED machine-tier row is AUTO-KEPT (deny-by-default — dropping
    # a machine check requires reject + re-dispatch, never an omission here); an omitted
    # judged row is a deliberate removal. Auto-kept rows append in original relative order;
    # the card groups criteria by tier when it renders, so intra-tuple position is not an
    # operator-visible ordering.
    removed_titles: list[str] = []
    for i, row in enumerate(rows, start=1):
        if i in used_refs:
            continue
        if str(row.get("tier", "")) in MACHINE_TIERS:
            out.append(dict(row))
            if str(row.get("text", "")) not in protected_titles:
                protected_titles.append(str(row.get("text", "")))
            kept += 1
        else:
            removed_titles.append(str(row.get("text", "")))
    final = out
    if not final:
        return None
    changed = bool(rescoped_titles or added_titles or removed_titles)
    return CriteriaRevisionOutcome(
        criteria=final,
        kept=kept,
        rescoped_titles=rescoped_titles,
        added_titles=added_titles,
        removed_titles=removed_titles,
        protected_titles=protected_titles,
        changed=changed,
    )


def render_criteria_revision_delta(outcome: CriteriaRevisionOutcome, feedback: str) -> str:
    """The plain-language delta LEADING the re-rendered card after a criteria revision —
    what changed, what was added/removed, and which automatic checks were protected."""
    fb = (feedback or "").strip()
    lines = [f"I updated what the build will be judged on, from your feedback (“{fb}”):", ""]
    if outcome.rescoped_titles:
        lines.append("  Reworded:")
        lines.extend(f"    ~ {t}" for t in outcome.rescoped_titles)
    if outcome.added_titles:
        lines.append("  Added (you check these yourself):")
        lines.extend(f"    + {t}" for t in outcome.added_titles)
    if outcome.removed_titles:
        lines.append("  Removed:")
        lines.extend(f"    - {t}" for t in outcome.removed_titles)
    if outcome.protected_titles:
        lines.append(
            "  Protected (automatic checks are set by the goal and the exam — to change "
            "these, /dispatch reject and start a new dispatch):"
        )
        lines.extend(f"    = {t}" for t in outcome.protected_titles)
    if not (outcome.rescoped_titles or outcome.added_titles or outcome.removed_titles):
        lines.append("  (No changes — the criteria are the same.)")
    lines.append("")
    return "\n".join(lines)
