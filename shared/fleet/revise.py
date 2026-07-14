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
