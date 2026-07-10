"""JobPlan v1 — the M2 plan-graph schema, deterministic ruler, and wave compiler (W1, #740).

The 14B proposes a big job as a DEPENDENCY-ORDERED plan (tasks + ``depends_on`` edges +
interface contracts); this module is the DETERMINISTIC side of that bargain — the model
never self-certifies a graph any more than it self-certifies a task list:

  * ``validate_plan`` is the ruler. It enforces every structural invariant (schema shape,
    slugged ids, repo containment via the SAME ``validate_repo`` a dispatch target passes,
    the ``DEFAULT_MAX_TASKS`` cap, acyclicity, contract well-formedness) and DEGRADES
    safely instead of inventing failure modes: unknown ``depends_on`` refs are dropped
    with a logged warning; a missing/malformed contract becomes an EMPTY contract (a
    contract improves a dependent's prompt — its absence must never block a task); a
    CYCLE is structural degeneracy, so ALL edges are replaced with a linear chain in the
    original task order — exactly today's serial semantics — and the degradation is
    LOGGED, never hidden. Only genuinely unrunnable input refuses: a non-plan payload, a
    repo outside the projects dir (path traversal — plan §10 S1/N7), or zero usable tasks.
  * ``compile_waves`` is the scheduler's topology: waves of all-ready tasks, stable
    original order within a wave. It only accepts what the ruler validated and FAILS LOUD
    on a cycle (never silently reorders).
  * Status transitions are EVIDENCE-GATED: a task reaches ``merged``/``parked``/``blocked``
    only with a non-empty evidence ref (the fleet RESULT line, gate output — plan §4.3
    "nothing is marked done without its verification pass" as a state-machine property),
    and a parked/blocked task SKIPS its dependents transitively (fail loud — dependents
    must never build on missing foundations, plan §2.3 gap 4).
  * ``PlanStore`` persists the plan with a ``plan_hash`` (sha256 over the canonical
    IMMUTABLE-IDENTITY serialization — goal, repo, the job-oracle path + criteria, the
    re-decompose budget LIMITS, each integration wave index, and per task id/prompt/
    depends_on/contract) and ``load()`` RE-VALIDATES + re-checks repo containment +
    verifies the hash. The hash covers what a run may NEVER silently change between write
    and read (plan §10 S1): a tampered oracle_path, repo, budget ceiling, or task body is
    caught and refused. It deliberately EXCLUDES the mutable runtime state — task
    ``status``, ``redecompose_budget.spent``, ``integration_nodes[].status``,
    ``job_acceptance.status`` — because those change on every legitimate scheduler write;
    a status transition is not a tamper. So the on-disk STATUS is ADVISORY, NOT
    integrity-covered: a driver must RE-DERIVE done-ness from a fresh oracle run (Lane A2),
    never trust the persisted status as proof of completion. Defense-in-depth over the
    identity, not an integrity guarantee for status (§10.3): a tamperer who edits an
    identity field is caught; one who only flips a status rides through — which is exactly
    why done-ness is re-derived, and why the driver ALSO pins the write-time identity hash
    in swap state (Lane A2 wiring).

INTEGRITY CONTRACT (Lane A2 depends on this): ``plan_hash`` = an immutable-identity seal,
NOT a whole-artifact seal. Tamper of goal/repo/oracle_path/criteria/budget-limits/wave-
index/task-body ⇒ load refuses. A status field read from disk is ADVISORY — the source of
truth for "is this task done?" is a fresh oracle run, never the stored status.

Pure module: no model calls, no subprocesses; the only I/O is ``PlanStore``'s two file
operations (mirroring ``swap_state``'s atomic-write pattern). DORMANT until the
``[fleet_dispatch].plan_graph`` knob is consumed by the swap driver (Lane A2) — with the
knob false nothing imports a plan and today's flat queue is byte-identical.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable

from shared.fleet.decompose import (
    CONTRACT_ITEM_MAX,
    DEFAULT_MAX_TASKS,
    _CTRL_RE,
    clean_contract_fields,
    clean_str_list,
)
from shared.fleet.dispatch import slugify_task, validate_repo

logger = logging.getLogger(__name__)

#: The one schema string this module reads/writes. An unknown schema REFUSES (fail loud
#: — a future jobplan/v2 must be migrated deliberately, never half-parsed).
PLAN_SCHEMA = "jobplan/v1"

#: Task statuses (the pinned jobplan/v1 contract). ``pending`` -> ``ready`` ->
#: ``building`` -> one of the terminal outcomes; ``skipped`` is set ONLY by parked/
#: blocked propagation, never directly by a model or a caller.
STATUS_PENDING = "pending"
STATUS_READY = "ready"
STATUS_BUILDING = "building"
STATUS_MERGED = "merged"
STATUS_PARKED = "parked"
STATUS_BLOCKED = "blocked"
STATUS_SKIPPED = "skipped"
TASK_STATUSES = frozenset({
    STATUS_PENDING, STATUS_READY, STATUS_BUILDING, STATUS_MERGED,
    STATUS_PARKED, STATUS_BLOCKED, STATUS_SKIPPED,
})
#: Terminal task statuses — no transition leads out of these (fail loud on attempt).
TERMINAL_STATUSES = frozenset({STATUS_MERGED, STATUS_PARKED, STATUS_BLOCKED, STATUS_SKIPPED})

INTEGRATION_STATUSES = frozenset({"pending", "passed", "failed"})
JOB_ACCEPTANCE_STATUSES = frozenset({"pending", "passed", "failed", "not-run"})
#: The pinned default job-oracle path (jobplan/v1 contract).
DEFAULT_ORACLE_PATH = "tests/test_job_acceptance.py"

#: Defensive upper bounds on the free-text plan fields (§10 S2 parity with the
#: contract caps): a legitimate goal/prompt/oracle_path is FAR under these — an
#: oversized value is a malformed/hostile input (an unbounded-context / log-flood
#: surface), capped like contract text. ``oracle_path`` reuses the contract SSOT
#: item cap (a path is short by nature); goal/prompt get generous bounds no real
#: emission approaches, so VALID inputs are byte-identical.
GOAL_MAX = 4000
PROMPT_MAX = 8000
ORACLE_PATH_MAX = CONTRACT_ITEM_MAX


def _clean_text(value: object, *, max_len: int) -> str:
    """Strip control chars (the SSOT ``decompose._CTRL_RE`` — an escape-evasion
    surface once composed into prompts/logs) and cap length. Mirrors the contract-
    ``notes`` treatment (control chars -> space, then strip). VALID text (no control
    chars, under *max_len*) passes through byte-identical."""
    text = value if isinstance(value, str) else str(value or "")
    return _CTRL_RE.sub(" ", text).strip()[:max_len]

# Contract bounds + string cleaning are the SSOT constants/helpers in ``decompose``
# (CONTRACT_NOTES_MAX / clean_str_list / clean_contract_fields) — elicitation,
# grammar schema, and this ruler can never drift apart (§10 S2: contract text is
# the ONLY plan-sourced human language a context pack may carry).


# ---------------------------------------------------------------------------
# Schema dataclasses (frozen — transitions return new plans, mirroring SwapState)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TaskContract:
    """A task's declared interface: what it creates and exports, for context packs."""

    creates: list[str] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)
    notes: str = ""

    def to_raw(self) -> dict:
        return {"creates": list(self.creates), "exports": list(self.exports), "notes": self.notes}


@dataclass(frozen=True)
class PlanTask:
    """One validated plan node. ``id`` is a ``slugify_task`` slug; ``depends_on`` holds
    ids of OTHER tasks in the same plan (validated: known, non-self, acyclic)."""

    id: str
    prompt: str
    depends_on: list[str] = field(default_factory=list)
    contract: TaskContract = field(default_factory=TaskContract)
    status: str = STATUS_PENDING

    def to_raw(self) -> dict:
        return {
            "id": self.id,
            "prompt": self.prompt,
            "depends_on": list(self.depends_on),
            "contract": self.contract.to_raw(),
            "status": self.status,
        }


@dataclass(frozen=True)
class IntegrationNode:
    """A per-wave integration gate record (gate-on-main after the wave's merges)."""

    after_wave: int
    status: str = "pending"

    def to_raw(self) -> dict:
        return {"after_wave": self.after_wave, "status": self.status}


@dataclass(frozen=True)
class JobAcceptance:
    """The job-level finish line: criteria + the protected job-oracle path."""

    criteria: list[str] = field(default_factory=list)
    oracle_path: str = DEFAULT_ORACLE_PATH
    status: str = "pending"

    def to_raw(self) -> dict:
        return {
            "criteria": list(self.criteria),
            "oracle_path": self.oracle_path,
            "status": self.status,
        }


@dataclass(frozen=True)
class RedecomposeBudget:
    """W5's bounded re-decomposition budget (spent counters persist in the plan)."""

    per_task: int = 1
    per_job: int = 2
    spent: int = 0

    def to_raw(self) -> dict:
        return {"per_task": self.per_task, "per_job": self.per_job, "spent": self.spent}


@dataclass(frozen=True)
class JobPlan:
    """A validated jobplan/v1. Frozen — every mutation returns a NEW plan."""

    plan_id: str
    goal: str
    repo: str
    tasks: list[PlanTask] = field(default_factory=list)
    integration_nodes: list[IntegrationNode] = field(default_factory=list)
    job_acceptance: JobAcceptance = field(default_factory=JobAcceptance)
    redecompose_budget: RedecomposeBudget = field(default_factory=RedecomposeBudget)
    plan_hash: str = ""
    schema: str = PLAN_SCHEMA

    def to_raw(self) -> dict:
        return {
            "schema": self.schema,
            "plan_id": self.plan_id,
            "goal": self.goal,
            "repo": self.repo,
            "tasks": [t.to_raw() for t in self.tasks],
            "integration_nodes": [n.to_raw() for n in self.integration_nodes],
            "job_acceptance": self.job_acceptance.to_raw(),
            "redecompose_budget": self.redecompose_budget.to_raw(),
            "plan_hash": self.plan_hash,
        }

    def task(self, task_id: str) -> PlanTask:
        """The task with *task_id*, or ``ValueError`` (fail loud, never a silent miss)."""
        for t in self.tasks:
            if t.id == task_id:
                return t
        raise ValueError(f"unknown task id: {task_id!r}")


@dataclass(frozen=True)
class PlanValidation:
    """Outcome of :func:`validate_plan` / :meth:`PlanStore.load`.

    ``ok=False`` is a REFUSAL (unrunnable input — reason says why); ``ok=True`` with
    ``degraded=True`` means the plan runs but its graph fell back to the linear chain
    (today's serial semantics). ``warnings`` records every dropped/normalized element —
    degradation is logged, never hidden."""

    ok: bool
    plan: JobPlan | None = None
    degraded: bool = False
    warnings: list[str] = field(default_factory=list)
    reason: str = ""


# ---------------------------------------------------------------------------
# The deterministic ruler
# ---------------------------------------------------------------------------


def _has_alnum(text: str) -> bool:
    return any(ch.isalnum() for ch in text)


def clean_contract(raw: object) -> TaskContract:
    """Normalize a raw contract. Missing/malformed ⇒ EMPTY contract — a contract
    improves a dependent's prompt; its absence must never block a task (pinned
    invariant). Delegates to ``decompose.clean_contract_fields`` (the SSOT for the
    control-char strip and the ``notes`` <= 280 / list / item-length caps)."""
    return TaskContract(**clean_contract_fields(raw))


def _find_cycle(ids: list[str], edges: dict[str, list[str]]) -> bool:
    """True iff the dependency graph has a cycle (iterative DFS, deterministic)."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {i: WHITE for i in ids}
    for root in ids:
        if color[root] != WHITE:
            continue
        stack: list[tuple[str, int]] = [(root, 0)]
        color[root] = GRAY
        while stack:
            node, idx = stack[-1]
            deps = edges.get(node, [])
            if idx < len(deps):
                stack[-1] = (node, idx + 1)
                nxt = deps[idx]
                if color.get(nxt, BLACK) == GRAY:
                    return True
                if color.get(nxt, BLACK) == WHITE:
                    color[nxt] = GRAY
                    stack.append((nxt, 0))
            else:
                color[node] = BLACK
                stack.pop()
    return False


def _linear_chain_edges(ids: list[str]) -> dict[str, list[str]]:
    """Original-order linear chain: task[i] depends on task[i-1] — today's serial
    semantics, the degeneracy fallback."""
    return {tid: ([ids[i - 1]] if i > 0 else []) for i, tid in enumerate(ids)}


def validate_plan(
    raw: dict,
    *,
    projects_dir: Path,
    max_tasks: int = DEFAULT_MAX_TASKS,
) -> PlanValidation:
    """The deterministic plan ruler — every invariant of the pinned jobplan/v1 contract.

    REFUSES (``ok=False``) only genuinely unrunnable input: a non-dict payload, an
    unknown ``schema``, a repo that fails :func:`validate_repo` containment (outside
    *projects_dir* / forbidden root / not a git repo — the §10 S1 path-traversal net),
    or zero usable tasks. Everything else DEGRADES safely with a logged warning:

      * task ids are slugged via ``slugify_task`` (shell metacharacters neutralized —
        no plan field ever reaches a shell un-slugified); id-less/prompt-less tasks and
        duplicate ids are dropped; the list is capped at *max_tasks*;
      * ``depends_on`` refs are slugged; unknown/self refs are dropped (warned);
      * a CYCLE degrades the WHOLE graph to the original-order linear chain
        (``degraded=True`` — exactly today's serial semantics, plan §4.2);
      * missing/malformed contracts become empty contracts; unknown statuses reset to
        ``pending``; integration/acceptance/budget blocks are normalized to defaults.

    Pure and deterministic — no I/O beyond ``validate_repo``'s path resolution.
    """
    warnings: list[str] = []

    def warn(msg: str) -> None:
        warnings.append(msg)
        logger.warning("plan_graph: %s", msg)

    if not isinstance(raw, dict):
        return PlanValidation(ok=False, reason="plan is not a JSON object")
    schema = raw.get("schema")
    if schema != PLAN_SCHEMA:
        return PlanValidation(ok=False, reason=f"unknown plan schema: {schema!r} (want {PLAN_SCHEMA!r})")

    repo = str(raw.get("repo", "") or "")
    if not repo:
        return PlanValidation(ok=False, reason="plan has no repo")
    err = validate_repo(Path(repo), projects_dir)
    if err is not None:
        return PlanValidation(ok=False, reason=f"plan repo refused — {err}")

    raw_tasks = raw.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        return PlanValidation(ok=False, reason="plan has no tasks")

    # ---- task-level cleaning: slug, prompt-required, dedupe, cap -----------------
    ids: list[str] = []
    cleaned: list[dict] = []
    seen: set[str] = set()
    # H6: a slug two-or-more raw ids collapse to (id truncation/normalization
    # collision) is AMBIGUOUS — a ``depends_on`` ref to it could mean the survivor OR
    # a dropped duplicate. Track every colliding slug so an edge to one is dropped as
    # unknown rather than silently retargeted to whichever task won dedup.
    slug_counts: dict[str, int] = {}
    for item in raw_tasks:
        if not isinstance(item, dict):
            warn("dropped a non-object task entry")
            continue
        raw_id = str(item.get("id", "") or "").strip()
        prompt = _clean_text(item.get("prompt"), max_len=PROMPT_MAX)
        if not raw_id or not _has_alnum(raw_id) or not prompt:
            warn(f"dropped a task with no usable id/prompt (id={raw_id!r})")
            continue
        slug = slugify_task(raw_id)
        slug_counts[slug] = slug_counts.get(slug, 0) + 1
        if slug in seen:
            warn(f"dropped duplicate task id {slug!r} (first occurrence kept)")
            continue
        if len(cleaned) >= max_tasks:
            warn(f"plan capped at {max_tasks} tasks — dropped {slug!r}")
            continue
        seen.add(slug)
        ids.append(slug)
        status = str(item.get("status", STATUS_PENDING) or STATUS_PENDING)
        if status not in TASK_STATUSES:
            warn(f"task {slug!r}: unknown status {status!r} reset to pending")
            status = STATUS_PENDING
        cleaned.append({
            "id": slug,
            "prompt": prompt,
            "raw_depends_on": item.get("depends_on"),
            "contract": clean_contract(item.get("contract")),
            "status": status,
        })
    if not cleaned:
        return PlanValidation(ok=False, reason="plan has no usable tasks")

    # ---- edge cleaning: slug refs, drop unknown/self ------------------------------
    id_set = set(ids)
    # H6: slugs that >=2 raw ids collided on — a ref to one is dropped, never retargeted.
    collapsed_slugs = {s for s, c in slug_counts.items() if c > 1}
    edges: dict[str, list[str]] = {}
    for entry in cleaned:
        refs: list[str] = []
        raw_deps = entry.pop("raw_depends_on")
        if raw_deps is not None and not isinstance(raw_deps, list):
            warn(f"task {entry['id']!r}: malformed depends_on ignored")
            raw_deps = None
        for ref in raw_deps or []:
            if not isinstance(ref, str) or not _has_alnum(ref):
                warn(f"task {entry['id']!r}: dropped a non-slug depends_on ref")
                continue
            ref_slug = slugify_task(ref)
            if ref_slug == entry["id"]:
                warn(f"task {entry['id']!r}: dropped a self depends_on ref")
                continue
            if ref_slug in collapsed_slugs:
                # Ambiguous: a slug collision collapsed a duplicate under this slug, so
                # the ref cannot be trusted to mean the survivor. Drop (degrade safe),
                # never retarget to whichever task won dedup (H6).
                warn(f"task {entry['id']!r}: dropped ambiguous depends_on ref {ref_slug!r} "
                     "(slug collision collapsed a duplicate — not retargeted to the survivor)")
                continue
            if ref_slug not in id_set:
                warn(f"task {entry['id']!r}: dropped unknown depends_on ref {ref_slug!r}")
                continue
            if ref_slug not in refs:
                refs.append(ref_slug)
        edges[entry["id"]] = refs

    # ---- acyclicity: a cycle is structural degeneracy ⇒ linear chain (today) ------
    degraded = False
    if _find_cycle(ids, edges):
        degraded = True
        warn("dependency cycle detected — degraded to the original-order linear chain")
        edges = _linear_chain_edges(ids)

    tasks = [
        PlanTask(
            id=entry["id"],
            prompt=entry["prompt"],
            depends_on=edges[entry["id"]],
            contract=entry["contract"],
            status=entry["status"],
        )
        for entry in cleaned
    ]

    # ---- integration nodes / job acceptance / budget (normalize-to-default) -------
    nodes: list[IntegrationNode] = []
    raw_nodes = raw.get("integration_nodes")
    if raw_nodes is not None and not isinstance(raw_nodes, list):
        warn("malformed integration_nodes ignored")
        raw_nodes = None
    for n in raw_nodes or []:
        # H5: exclude bool — ``isinstance(True, int)`` is True, so a JSON ``true``
        # would otherwise pass as after_wave==1 (mirrors the _budget_int bool guard).
        if (not isinstance(n, dict) or isinstance(n.get("after_wave"), bool)
                or not isinstance(n.get("after_wave"), int) or n["after_wave"] < 1):
            warn("dropped a malformed integration node")
            continue
        status = str(n.get("status", "pending") or "pending")
        if status not in INTEGRATION_STATUSES:
            warn(f"integration node after_wave={n['after_wave']}: unknown status reset to pending")
            status = "pending"
        nodes.append(IntegrationNode(after_wave=n["after_wave"], status=status))

    raw_acc = raw.get("job_acceptance")
    if not isinstance(raw_acc, dict):
        if raw_acc is not None:
            warn("malformed job_acceptance reset to defaults")
        raw_acc = {}
    acc_status = str(raw_acc.get("status", "pending") or "pending")
    if acc_status not in JOB_ACCEPTANCE_STATUSES:
        warn(f"job_acceptance: unknown status {acc_status!r} reset to pending")
        acc_status = "pending"
    # H5: control-strip + cap the oracle_path (a hashed identity field composed into
    # a shell/log surface) — empty after cleaning falls back to the pinned default.
    oracle_path = _clean_text(raw_acc.get("oracle_path"), max_len=ORACLE_PATH_MAX) or DEFAULT_ORACLE_PATH
    acceptance = JobAcceptance(
        criteria=clean_str_list(raw_acc.get("criteria"), max_items=64, max_len=512),
        oracle_path=oracle_path,
        status=acc_status,
    )

    raw_budget = raw.get("redecompose_budget")
    if not isinstance(raw_budget, dict):
        if raw_budget is not None:
            warn("malformed redecompose_budget reset to defaults")
        raw_budget = {}

    def _budget_int(key: str, default: int) -> int:
        val = raw_budget.get(key, default)
        if isinstance(val, bool) or not isinstance(val, int) or val < 0:
            warn(f"redecompose_budget.{key}: malformed value reset to {default}")
            return default
        return val

    budget = RedecomposeBudget(
        per_task=_budget_int("per_task", 1),
        per_job=_budget_int("per_job", 2),
        spent=_budget_int("spent", 0),
    )

    plan = JobPlan(
        plan_id=str(raw.get("plan_id", "") or ""),
        goal=_clean_text(raw.get("goal"), max_len=GOAL_MAX),  # H5: control-strip + cap
        repo=repo,
        tasks=tasks,
        integration_nodes=nodes,
        job_acceptance=acceptance,
        redecompose_budget=budget,
        plan_hash=str(raw.get("plan_hash", "") or ""),
    )
    return PlanValidation(ok=True, plan=plan, degraded=degraded, warnings=warnings)


def build_plan_raw(
    *,
    plan_id: str,
    goal: str,
    repo: str,
    tasks: list[dict],
    criteria: list[str] | None = None,
    oracle_path: str = DEFAULT_ORACLE_PATH,
) -> dict:
    """Build a raw jobplan/v1 dict from decompose-style task dicts (``{repo, task,
    prompt[, depends_on][, contract]}``) — the bridge the driver (Lane A2) feeds to
    :func:`validate_plan`.

    Graph-unaware output degrades to TODAY: if NO task carries a ``depends_on`` key
    (the model never emitted the field — a legacy/old-shape emission), the edges are
    synthesized as the original-order linear chain, today's implicit serial ordering.
    If ANY task carries the key, the emission is graph-aware and a missing key on an
    individual task means "independent" (an explicit ``[]`` root) — that distinction
    is why decompose only attaches ``depends_on`` when the model actually provided it.

    SEAM NOTE (W4 / Lane A2): ``acceptance.compile_prompts`` appends its dedicated
    final ``acceptance-tests`` task WITHOUT graph keys, so under a graph-aware plan
    this rule would place it as an independent wave-1 root — wrong for a task that
    must run after every feature merges. The driver/W4 must stamp that task's
    ``depends_on`` (all feature slugs) before building the plan, or schedule the job
    oracle outside the plan; this helper deliberately does not guess.
    """
    graph_aware = any("depends_on" in t for t in tasks)
    ids = [slugify_task(str(t.get("task", "") or t.get("id", ""))) for t in tasks]
    chain = _linear_chain_edges(ids)
    out_tasks: list[dict] = []
    for i, t in enumerate(tasks):
        deps = list(t.get("depends_on", []) or []) if graph_aware else chain[ids[i]]
        contract = t.get("contract")
        out_tasks.append({
            "id": ids[i],
            "prompt": str(t.get("prompt", "") or ""),
            "depends_on": deps,
            "contract": contract if isinstance(contract, dict) else {},
            "status": STATUS_PENDING,
        })
    return {
        "schema": PLAN_SCHEMA,
        "plan_id": plan_id,
        "goal": goal,
        "repo": repo,
        "tasks": out_tasks,
        "integration_nodes": [],
        "job_acceptance": {
            "criteria": list(criteria or []),
            "oracle_path": oracle_path,
            "status": "pending",
        },
        "redecompose_budget": {"per_task": 1, "per_job": 2, "spent": 0},
        "plan_hash": "",
    }


def stamp_acceptance_task_deps(tasks: list[dict]) -> list[dict]:
    """Seam note (a), Lane A2: ``acceptance.compile_prompts`` appends its dedicated final
    ``acceptance-tests`` task WITHOUT graph keys, so under a graph-aware emission
    :func:`build_plan_raw` would place it as an independent wave-1 root — wrong for a
    task that must run after every feature merges. Stamp its ``depends_on`` with ALL
    feature slugs (deterministic, driver-side, before the plan is built).

    Graph-UNAWARE input (no task carries ``depends_on``) is returned as fresh copies
    unchanged — ``build_plan_raw``'s linear-chain fallback already runs the appended
    acceptance task LAST, today's exact ordering. A task that already carries the key
    is never overwritten (the model's/driver's explicit graph wins)."""
    from shared.fleet.acceptance import ACCEPTANCE_TASK_SLUG

    out = [dict(t) for t in tasks]
    if not any("depends_on" in t for t in out):
        return out
    feature_slugs = [
        slugify_task(str(t.get("task", "") or t.get("id", "")))
        for t in out
        if str(t.get("task", "") or t.get("id", "")) != ACCEPTANCE_TASK_SLUG
    ]
    for t in out:
        if (
            str(t.get("task", "") or t.get("id", "")) == ACCEPTANCE_TASK_SLUG
            and "depends_on" not in t
        ):
            t["depends_on"] = list(feature_slugs)
    return out


#: W5 bound: a re-decompose replaces ONE failed task with at most this many children
#: (plan §4.6 — "2-3 smaller replacement tasks"; more is re-planning drift).
REDECOMPOSE_MAX_CHILDREN = 3


def replace_task_with_children(plan: JobPlan, task_id: str, children: list[dict]) -> "JobPlan | None":
    """W5 — replace a consistently-failing task with 2..:data:`REDECOMPOSE_MAX_CHILDREN`
    smaller children (the evidence-fed re-decompose), preserving graph integrity.

    Deterministic rewiring:

      * child ids are slugged; a child colliding with ANY existing plan id (or a
        duplicate sibling) REFUSES the whole replace (``None`` — the caller parks);
      * child ``depends_on`` may reference SIBLING children only (unknown refs
        dropped); a child left with no sibling deps (a root) INHERITS the replaced
        task's ``depends_on`` — the children collectively sit where the parent sat;
      * every task that depended on the replaced task now depends on ALL children
        (conservative — dependents run only after the whole replacement subtree);
      * the result must stay acyclic (defensive — sibling-only refs + inheritance
        cannot introduce a cycle, but a cycle among the children themselves can) and
        every child starts ``pending``.

    Returns the NEW plan, or ``None`` when the replacement is unusable (fewer than 2
    usable children, id collisions, or a cycle) — the caller then parks the original
    task instead (fail loud, never a broken graph). Statuses of every other task are
    preserved; the budget spend is the CALLER's transition (:func:`spend_redecompose`)."""
    try:
        parent = plan.task(task_id)
    except ValueError:
        return None
    if parent.status in TERMINAL_STATUSES:
        return None

    existing_ids = {t.id for t in plan.tasks if t.id != task_id}
    cleaned: list[dict] = []
    seen: set[str] = set()
    for item in children or []:
        if not isinstance(item, dict):
            continue
        raw_id = str(item.get("task", "") or item.get("id", "")).strip()
        prompt = str(item.get("prompt", "") or "").strip()
        if not raw_id or not _has_alnum(raw_id) or not prompt:
            continue
        slug = slugify_task(raw_id)
        if slug in existing_ids or slug in seen or slug == task_id:
            return None  # collision — refuse the whole replace (caller parks)
        seen.add(slug)
        cleaned.append({
            "id": slug,
            "prompt": prompt,
            "raw_depends_on": item.get("depends_on"),
            "contract": clean_contract(item.get("contract")),
        })
        if len(cleaned) > REDECOMPOSE_MAX_CHILDREN:
            return None  # oversized replacement — re-planning drift, refuse
    if len(cleaned) < 2:
        return None  # not a strict improvement — keep/park the original

    child_ids = {c["id"] for c in cleaned}
    new_children: list[PlanTask] = []
    for c in cleaned:
        refs: list[str] = []
        raw_deps = c.pop("raw_depends_on")
        for ref in raw_deps if isinstance(raw_deps, list) else []:
            if not isinstance(ref, str) or not _has_alnum(ref):
                continue
            ref_slug = slugify_task(ref)
            if ref_slug in child_ids and ref_slug != c["id"] and ref_slug not in refs:
                refs.append(ref_slug)
        deps = refs if refs else list(parent.depends_on)
        new_children.append(PlanTask(
            id=c["id"], prompt=c["prompt"], depends_on=deps,
            contract=c["contract"], status=STATUS_PENDING,
        ))

    new_tasks: list[PlanTask] = []
    for t in plan.tasks:
        if t.id == task_id:
            new_tasks.extend(new_children)
        elif task_id in t.depends_on:
            rewired = [d for d in t.depends_on if d != task_id]
            rewired += [c.id for c in new_children if c.id not in rewired]
            new_tasks.append(replace(t, depends_on=rewired))
        else:
            new_tasks.append(t)

    ids = [t.id for t in new_tasks]
    edges = {t.id: list(t.depends_on) for t in new_tasks}
    if _find_cycle(ids, edges):
        return None  # a cycle among the children — refuse (caller parks)
    logger.info(
        "plan_graph: task %s re-decomposed into %s",
        task_id, [c.id for c in new_children],
    )
    return replace(plan, tasks=new_tasks)


# ---------------------------------------------------------------------------
# Wave compiler
# ---------------------------------------------------------------------------


def compile_waves(plan: JobPlan) -> list[list[PlanTask]]:
    """Topological waves: each wave holds every task whose dependencies are ALL in
    earlier waves; order WITHIN a wave is the original task order (stable, so a plan
    with no edges compiles to one wave in emission order and a chain compiles to one
    task per wave — today's serial cadence).

    Accepts only ruler-validated plans; a cycle here means the caller bypassed
    :func:`validate_plan`, so it FAILS LOUD (``ValueError``) rather than silently
    reordering."""
    remaining = {t.id: t for t in plan.tasks}
    order = [t.id for t in plan.tasks]
    placed: set[str] = set()
    waves: list[list[PlanTask]] = []
    while remaining:
        wave = [remaining[tid] for tid in order
                if tid in remaining and all(d in placed for d in remaining[tid].depends_on)]
        if not wave:
            raise ValueError(
                "compile_waves: unresolvable dependencies (cycle or unknown ref) — "
                "plans must pass validate_plan first"
            )
        for t in wave:
            placed.add(t.id)
            del remaining[t.id]
        waves.append(wave)
    return waves


# ---------------------------------------------------------------------------
# Evidence-gated status transitions (frozen — each returns a NEW plan)
# ---------------------------------------------------------------------------


def _replace_task(plan: JobPlan, task_id: str, **changes) -> JobPlan:
    tasks = [replace(t, **changes) if t.id == task_id else t for t in plan.tasks]
    return replace(plan, tasks=tasks)


def _require_evidence(evidence: str, what: str) -> None:
    if not (evidence or "").strip():
        raise ValueError(f"{what} requires a non-empty evidence ref — nothing is marked without its verification pass")


def _require_not_terminal(task: PlanTask, target: str) -> None:
    if task.status in TERMINAL_STATUSES:
        raise ValueError(
            f"task {task.id!r} is terminal ({task.status}) — cannot transition to {target}"
        )


def mark_ready(plan: JobPlan, task_id: str) -> JobPlan:
    """``pending`` -> ``ready``, ONLY when every dependency is ``merged`` (the
    state-machine property the §9.2 simulator proves)."""
    task = plan.task(task_id)
    _require_not_terminal(task, STATUS_READY)
    if task.status != STATUS_PENDING:
        raise ValueError(f"task {task_id!r}: ready requires pending (is {task.status})")
    by_id = {t.id: t for t in plan.tasks}
    unmerged = [d for d in task.depends_on if by_id[d].status != STATUS_MERGED]
    if unmerged:
        raise ValueError(f"task {task_id!r}: dependencies not merged: {unmerged}")
    return _replace_task(plan, task_id, status=STATUS_READY)


def mark_building(plan: JobPlan, task_id: str) -> JobPlan:
    """``ready`` -> ``building`` (the driver handed it to the fleet)."""
    task = plan.task(task_id)
    _require_not_terminal(task, STATUS_BUILDING)
    if task.status != STATUS_READY:
        raise ValueError(f"task {task_id!r}: building requires ready (is {task.status})")
    return _replace_task(plan, task_id, status=STATUS_BUILDING)


def mark_merged(plan: JobPlan, task_id: str, evidence: str) -> JobPlan:
    """-> ``merged``, ONLY with non-empty evidence (the fleet's RESULT line ref) AND
    from ``ready``/``building``. H1: without the source-state gate a raw pending ->
    merged would SKIP the deps-merged invariant that lives in ``mark_ready`` — a
    FALSE-DONE surface (a task marked done whose foundations never merged). The
    strictness now matches ``mark_ready``/``mark_building`` (a linear
    pending->ready->building->merged march)."""
    _require_evidence(evidence, "mark_merged")
    task = plan.task(task_id)
    _require_not_terminal(task, STATUS_MERGED)
    if task.status not in (STATUS_READY, STATUS_BUILDING):
        raise ValueError(
            f"task {task_id!r}: merged requires ready or building (is {task.status}) — "
            "a pending task must pass mark_ready's deps-merged gate first"
        )
    logger.info("plan_graph: task %s merged (evidence: %s)", task_id, evidence)
    return _replace_task(plan, task_id, status=STATUS_MERGED)


def _skip_dependents(plan: JobPlan, root_id: str) -> JobPlan:
    """Transitively mark every dependent of *root_id* ``skipped`` (fail loud — a
    dependent must never build on a missing foundation). Already-terminal dependents
    are left as they are (their outcome is already recorded)."""
    dependents: dict[str, list[str]] = {t.id: [] for t in plan.tasks}
    for t in plan.tasks:
        for d in t.depends_on:
            dependents[d].append(t.id)
    to_skip: set[str] = set()
    frontier = [root_id]
    while frontier:
        nxt = frontier.pop()
        for child in dependents.get(nxt, []):
            if child not in to_skip:
                to_skip.add(child)
                frontier.append(child)
    new_tasks = [
        replace(t, status=STATUS_SKIPPED)
        if (t.id in to_skip and t.status not in TERMINAL_STATUSES)
        else t
        for t in plan.tasks
    ]
    skipped = sorted(t.id for t in new_tasks if t.id in to_skip and t.status == STATUS_SKIPPED)
    if skipped:
        logger.warning("plan_graph: task %s failed — skipped dependents: %s", root_id, skipped)
    return replace(plan, tasks=new_tasks)


def mark_parked(plan: JobPlan, task_id: str, evidence: str) -> JobPlan:
    """-> ``parked`` with evidence; dependents become ``skipped`` transitively."""
    _require_evidence(evidence, "mark_parked")
    task = plan.task(task_id)
    _require_not_terminal(task, STATUS_PARKED)
    logger.warning("plan_graph: task %s parked (evidence: %s)", task_id, evidence)
    return _skip_dependents(_replace_task(plan, task_id, status=STATUS_PARKED), task_id)


def mark_blocked(plan: JobPlan, task_id: str, evidence: str) -> JobPlan:
    """-> ``blocked`` (e.g. the secret-scan fail-closed stop) with evidence; a blocked
    task did not merge, so its dependents lack their foundation and are ``skipped``
    transitively — the same fail-loud propagation as ``parked``."""
    _require_evidence(evidence, "mark_blocked")
    task = plan.task(task_id)
    _require_not_terminal(task, STATUS_BLOCKED)
    logger.warning("plan_graph: task %s BLOCKED (evidence: %s)", task_id, evidence)
    return _skip_dependents(_replace_task(plan, task_id, status=STATUS_BLOCKED), task_id)


def mark_integration(plan: JobPlan, after_wave: int, *, passed: bool, evidence: str) -> JobPlan:
    """Record a wave-gate outcome — evidence-gated (the gate's exit/output ref). The
    node is appended if not present (the driver may gate waves it didn't pre-declare)."""
    _require_evidence(evidence, "mark_integration")
    status = "passed" if passed else "failed"
    nodes = list(plan.integration_nodes)
    for i, n in enumerate(nodes):
        if n.after_wave == after_wave:
            nodes[i] = replace(n, status=status)
            break
    else:
        nodes.append(IntegrationNode(after_wave=after_wave, status=status))
    logger.info("plan_graph: wave %d integration %s (evidence: %s)", after_wave, status, evidence)
    return replace(plan, integration_nodes=nodes)


def mark_job_acceptance(plan: JobPlan, status: str, evidence: str) -> JobPlan:
    """Record the job-oracle outcome (``passed``/``failed``/``not-run``) — evidence-
    gated for ALL outcomes: even an honest ``not-run`` names why (fail loud, never an
    implied success).

    H2 FALSE-DONE guard: a ``passed`` outcome REQUIRES every task to be terminal
    (merged/parked/blocked/skipped). A job cannot be "done" while a task is still
    pending/ready/building — that is precisely the FALSE-DONE the §9 zero-tolerance
    invariant forbids. ``failed``/``not-run`` stay unrestricted (a job legitimately
    fails or is not run mid-flight). The GREEN-vs-PARKED verdict nuance over which
    terminal states count as success lives in the §9.4 verdict logic, NOT here; this
    guard only forbids passed-while-incomplete."""
    _require_evidence(evidence, "mark_job_acceptance")
    if status not in JOB_ACCEPTANCE_STATUSES or status == "pending":
        raise ValueError(f"mark_job_acceptance: invalid outcome status {status!r}")
    if status == "passed":
        incomplete = [t.id for t in plan.tasks if t.status not in TERMINAL_STATUSES]
        if incomplete:
            raise ValueError(
                f"mark_job_acceptance: cannot pass with non-terminal tasks {incomplete} "
                "(FALSE-DONE guard — every task must reach a terminal state before the "
                "job is marked passed)"
            )
    logger.info("plan_graph: job acceptance %s (evidence: %s)", status, evidence)
    return replace(plan, job_acceptance=replace(plan.job_acceptance, status=status))


def spend_redecompose(plan: JobPlan) -> JobPlan:
    """Spend one unit of the re-decomposition budget; ``ValueError`` when exhausted
    (the bounded-by-design W5 rule — never an unbounded re-planning loop)."""
    budget = plan.redecompose_budget
    if budget.spent >= budget.per_job:
        raise ValueError(f"re-decompose budget exhausted ({budget.spent}/{budget.per_job})")
    return replace(plan, redecompose_budget=replace(budget, spent=budget.spent + 1))


# ---------------------------------------------------------------------------
# PlanStore — persisted plan + hash; load() never trusts the artifact (§10 S1)
# ---------------------------------------------------------------------------


def _plan_identity(raw: dict) -> dict:
    """The IMMUTABLE-IDENTITY projection of a raw jobplan/v1 dict — everything a run
    may never silently change between write and read, and NOTHING that legitimately
    changes on a scheduler write.

    INCLUDED (hashed): ``goal``, ``repo``, ``job_acceptance.oracle_path`` +
    ``.criteria``, ``redecompose_budget.per_task`` + ``.per_job``, each
    ``integration_nodes[].after_wave``, and per task ``id``/``prompt``/``depends_on``/
    ``contract``. EXCLUDED (mutable runtime state, advisory-from-disk): task
    ``status``, ``redecompose_budget.spent``, ``integration_nodes[].status``,
    ``job_acceptance.status``. See the module INTEGRITY CONTRACT note."""
    ja = raw.get("job_acceptance")
    ja = ja if isinstance(ja, dict) else {}
    budget = raw.get("redecompose_budget")
    budget = budget if isinstance(budget, dict) else {}
    nodes = raw.get("integration_nodes")
    nodes = nodes if isinstance(nodes, list) else []
    tasks = raw.get("tasks")
    tasks = tasks if isinstance(tasks, list) else []
    return {
        "goal": raw.get("goal", ""),
        "repo": raw.get("repo", ""),
        "job_acceptance": {
            "oracle_path": ja.get("oracle_path", ""),
            "criteria": ja.get("criteria", []),
        },
        "redecompose_budget": {
            "per_task": budget.get("per_task", 0),
            "per_job": budget.get("per_job", 0),
        },
        "integration_nodes": [
            {"after_wave": n.get("after_wave")} if isinstance(n, dict) else {"after_wave": None}
            for n in nodes
        ],
        "tasks": [
            {
                "id": t.get("id", ""),
                "prompt": t.get("prompt", ""),
                "depends_on": t.get("depends_on", []),
                "contract": t.get("contract", {}),
            }
            if isinstance(t, dict) else {}
            for t in tasks
        ],
    }


def compute_plan_hash(plan: "JobPlan | dict") -> str:
    """sha256 over the canonical IMMUTABLE-IDENTITY JSON of the FULL plan (sorted keys,
    compact separators, UTF-8) — the jobplan/v1 ``plan_hash`` definition (H3, #740).

    Accepts either a validated :class:`JobPlan` (serialized via ``to_raw()`` first) or
    a raw dict — write() passes the dataclass, load() passes the on-disk raw, and both
    yield IDENTICAL bytes because write persists exactly that ``to_raw()`` shape.

    The hash seals the plan's IMMUTABLE IDENTITY: ``goal``, ``repo``, the job-oracle
    path + criteria, the re-decompose budget LIMITS, each integration wave index, and
    per task id/prompt/depends_on/contract. It deliberately DROPS the mutable runtime
    state (task ``status``, ``budget.spent``, ``integration_nodes[].status``,
    ``job_acceptance.status``) — those change on every legitimate scheduler write, so a
    status-covering hash would be a moving target that self-invalidates mid-run and
    would fire the §10 S1 tamper check on the system's OWN writes. Tamper of any hashed
    field (an oracle_path redirect — a FALSE-DONE surface — a repo retarget, a budget-
    ceiling bump, a task-body edit) IS caught; a status transition is not a tamper.
    (Reconciled byte-for-byte with the W9 battery ``reference_plan_hash``, #740.)"""
    raw = plan.to_raw() if isinstance(plan, JobPlan) else plan
    canonical = json.dumps(
        _plan_identity(raw),
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _atomic_write(path: Path, data: str) -> None:
    """Atomic write (temp + ``os.replace``) — mirrors ``swap_state._atomic_write``;
    never a torn half plan on disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(data, encoding="utf-8")
    os.replace(tmp, path)


class PlanStore:
    """Write/load the persisted JobPlan artifact.

    ``write`` stamps ``plan_hash`` (recomputed on EVERY persist) and writes atomically.
    ``load`` RE-VALIDATES from scratch: it verifies the immutable-identity hash against
    the on-disk content, then runs the full ruler (:func:`validate_plan`) including repo
    containment. The hash covers the plan's IMMUTABLE IDENTITY (goal, repo, oracle_path,
    criteria, budget LIMITS, wave indices, task bodies) — a tamper of any of those is
    caught and REFUSED (fail loud; the caller parks the run). The mutable STATUS fields
    are NOT integrity-covered — they ride from disk as ADVISORY, and a driver re-derives
    done-ness from a fresh oracle run (the module INTEGRITY CONTRACT note; Lane A2).
    ``load`` also degrades on ANY read/parse failure (bad UTF-8, unparseable or
    pathologically nested JSON) rather than crashing (H4)."""

    def __init__(self, path: Path, *, projects_dir: Path, max_tasks: int = DEFAULT_MAX_TASKS) -> None:
        self._path = path
        self._projects_dir = projects_dir
        self._max_tasks = max_tasks

    @property
    def path(self) -> Path:
        return self._path

    def write(self, plan: JobPlan) -> JobPlan:
        """Persist *plan* with a freshly computed ``plan_hash``; returns the hashed plan."""
        hashed = replace(plan, plan_hash=compute_plan_hash(plan))
        _atomic_write(self._path, json.dumps(hashed.to_raw(), indent=2))
        return hashed

    def load(self) -> PlanValidation:
        """Read + hash-verify + re-validate the persisted plan (never trusted).

        Degrades to a clean REFUSAL on any read/parse/verify failure (H4): an
        undecodable byte stream, unparseable or pathologically deep JSON, or a hash
        mismatch all return ``ok=False`` — never an exception out of ``load``."""
        try:
            raw_text = self._path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return PlanValidation(ok=False, reason=f"plan artifact unreadable: {exc}")
        try:
            raw = json.loads(raw_text)
            if not isinstance(raw, dict):
                return PlanValidation(ok=False, reason="plan artifact is not a JSON object")
            stored_hash = str(raw.get("plan_hash", "") or "")
            raw_tasks = raw.get("tasks")
            if not stored_hash or not isinstance(raw_tasks, list):
                return PlanValidation(ok=False, reason="plan artifact carries no verifiable plan_hash")
            computed = compute_plan_hash(raw)
        except Exception as exc:  # noqa: BLE001 — any parse/decode/compute failure refuses, never crashes
            return PlanValidation(ok=False, reason=f"plan artifact could not be parsed/verified: {exc}")

        if stored_hash != computed:
            logger.warning("plan_graph: plan_hash mismatch on load — refusing (tamper?)")
            return PlanValidation(
                ok=False,
                reason="plan_hash mismatch — the on-disk plan does not match its hash (refusing; tampered?)",
            )

        result = validate_plan(raw, projects_dir=self._projects_dir, max_tasks=self._max_tasks)
        if result.ok and result.plan is not None:
            return replace(result, plan=replace(result.plan, plan_hash=stored_hash))
        return result


# ---------------------------------------------------------------------------
# L1 orchestration simulator seam (W9 / #740) — simulate_job_plan
# ---------------------------------------------------------------------------
# The model-free / GPU-free path through the REAL swap-driver decision loop
# (plan §9.2). This is NOT a parallel reimplementation: it constructs a real
# ``SwapDriver`` with a scripted ``SwapOps`` and drives the real
# ``_run_plan_waves`` + ``_run_job_acceptance``, then the real ``build_scorecard``
# / ``compute_job_verdict`` / ``render_job_summary``. Every status transition is
# the real ``mark_ready``/``mark_building``/``mark_merged``/``mark_parked``/
# ``mark_blocked``/``_skip_dependents``/``_skip_all_pending``/``mark_integration``/
# ``mark_job_acceptance``; every re-decompose is the real
# ``replace_task_with_children`` + ``spend_redecompose`` driven by the real
# ``decompose.split_failed_task``; every wave is the real ``compile_waves``
# topology (and ``_next_wave``'s dynamic frontier, regression-locked to it). A bug
# in that orchestration surfaces HERE and in the live driver by construction — they
# are the same code (the anti-parallel-impl guard test proves it).
#
# Steering the declared runner signature cannot carry (Lane A2 flagged this
# explicitly): two ENVIRONMENT conditions — a wave integration gate breaking, and a
# boot-side crash-then-recover — have no per-task outcome channel, so the scenario
# encodes them in ``plan_id`` and the simulator scripts the matching injected
# ``SwapOps`` effect (``run_wave_gate`` returns ok=False at the target wave; the
# verdict is overridden to RECOVERED). The ORCHESTRATION REACTION to them
# (skip-all-pending short-circuit, the verdict taxonomy) is the REAL driver.
# Task-level steering (park / block / a wedged HANG / re-decompose-then-succeed)
# rides the fleet RESULT code the scenario scripts in ``fleet_results`` — the rig's
# ``_scripted_run_task`` carries that code verbatim in the outcome detail, and the
# scripted 14B (``generate_fn``) is triggered through the rig's re-decompose marker.


@dataclass(frozen=True)
class JobPlanSimResult:
    """The simulator's result object — the shape ``test_job_pipeline_e2e`` asserts on."""

    task_status: dict          # task-id -> terminal jobplan/v1 status
    waves: list                # topological waves (ids, sorted within a wave)
    job_verdict: str           # GREEN | PARKED-HONEST | STALLED | RECOVERED (never FALSE-DONE)
    summary: str               # the human JOB_SUMMARY render + honest simulator notes
    attribution: str = ""      # the §9.4 failure-attribution tag (PLAN/BUILD/VERIFY/HARNESS; '' for GREEN)


class _SimulatedWatchdogKill(Exception):
    """Raised by the scripted run_task for a task scripted to HANG — models the
    out-of-band budget watchdog tree-killing a wedged run, leaving the task frozen
    ``building`` and the job honestly STALLED (a harness fault, never a capability
    datum; resumable by design)."""


_SIM_SANDBOX: "tuple[Path, Path] | None" = None


def _sim_sandbox() -> "tuple[Path, Path]":
    """A throwaway git-shaped sandbox so the REAL ``validate_plan`` repo-containment
    gate (``validate_repo`` — exists + under projects_dir + has ``.git`` + not a
    forbidden root) passes for the synthetic simulator plans. The repo string never
    touches the state machine (run_task / gate / oracle are scripted and the git
    seams are no-ops) — it only satisfies the ruler so the same ruler that runs live
    validates the plan here too."""
    global _SIM_SANDBOX
    if _SIM_SANDBOX is None:
        import tempfile

        base = Path(tempfile.mkdtemp(prefix="fleetsim-"))
        repo = base / "battery-sim"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        _SIM_SANDBOX = (base, repo)
    return _SIM_SANDBOX


def _sim_fallback_plan(goal: str, projects_dir: Path, repo: Path) -> "JobPlan":
    """The deterministic junk-degrade: ONE validated task (the goal as its prompt) —
    never zero work, never a crash (plan §4.1 degrade-to-today). The pinned single-
    task id is ``build-it`` (the degenerate/junk scenarios' convention). Built through
    the REAL ruler so it is well-formed by construction."""
    text = (goal or "the requested work").strip() or "the requested work"
    raw = {
        "schema": PLAN_SCHEMA,
        "plan_id": "sim-fallback",
        "goal": text[:GOAL_MAX],
        "repo": str(repo),
        "tasks": [{
            "id": "build-it", "prompt": text[:PROMPT_MAX],
            "depends_on": [], "contract": {}, "status": STATUS_PENDING,
        }],
        "integration_nodes": [],
        "job_acceptance": {"criteria": [], "oracle_path": DEFAULT_ORACLE_PATH, "status": "pending"},
        "redecompose_budget": {"per_task": 1, "per_job": 2, "spent": 0},
        "plan_hash": "",
    }
    validation = validate_plan(raw, projects_dir=projects_dir)
    assert validation.ok and validation.plan is not None  # well-formed by construction
    return validation.plan


def simulate_job_plan(
    plan: object,
    *,
    run_task,
    generate_fn,
    oracle_status: str = "passed",
    plan_graph_enabled: bool = True,
    rigs: "list[str] | None" = None,
    rig_oracle: "Callable[[str, str], dict] | None" = None,
) -> JobPlanSimResult:
    """Drive ONE JobPlan through the REAL swap-driver wave loop with a scripted fleet
    (``run_task``), a scripted 14B (``generate_fn`` for re-decompose splits), and a
    scripted job oracle (``oracle_status``) — no GPU, no model, milliseconds. The
    §9.2 state-machine property ("nothing is marked done without its verification
    pass") is proven here against the SAME code the live driver runs. See the module
    header for the seam contract + the steering-channel rationale.

    B8 rig-injection seam (W9 §9.3/§9.4 — TEST-ONLY). ``rigs`` and ``rig_oracle`` are
    ``None`` for EVERY existing caller and for every real operator dispatch (the real
    path is ``SwapDriver.run`` via ``build_swap_ops``, which NEVER calls this
    simulator), so with them unset the run is BYTE-IDENTICAL to the un-rigged
    simulator. When a rig-carrying battery card (B8) arms a negative, the matching
    sabotage is installed at the REAL net so the honest outcome is a caught negative —
    PARKED-HONEST — and a GREEN is impossible by construction (and, if ever emitted,
    is rewritten FALSE-DONE by the runner's cross-check):

      * **N1** — a mid-chain task silently renames the export its dependent's contract
        imports. Each task's OWN unit tests still pass (it merges), but the WAVE
        INTEGRATION gate on the merged tree goes RED, so the driver short-circuits and
        SKIPS the dependent subtree (``rigs=["N1"]`` fails the first post-merge gate).
      * **N2** — an implementation passes its OWN unit tests (the task merges) but
        violates a JOB-oracle criterion: ``rigs=["N2"]`` forces the job oracle to FAIL
        on the integrated tree (unit-green distinguished from job-red).
      * **N3** — a task edits the protected oracle file. ``rig_oracle`` injects the
        REAL restore-before-grade (``swap_ops.real_run_job_oracle``): it overwrites the
        tamper with the plan bytes BEFORE grading, so the ORIGINAL oracle runs and the
        tree is restored exactly. The rig knowledge (payloads, real-oracle wiring)
        lives in ``tests/fixtures/m2_rigs/rig_injection.py``, not here."""
    from shared.fleet.decompose import split_failed_task
    from shared.fleet.swap_driver import (
        VERDICT_GREEN,
        VERDICT_RECOVERED,
        SwapDriver,
        SwapOps,
        build_scorecard,
        render_job_summary,
    )

    projects_dir, repo = _sim_sandbox()

    # ---- 1. Build the JobPlan via the REAL ruler (junk -> single-task degrade) -----
    junk = False
    degraded = False
    warnings: list[str] = []
    if not isinstance(plan, dict):
        junk = True
        jobplan = _sim_fallback_plan(str(plan or ""), projects_dir, repo)
    else:
        raw = dict(plan)
        raw["repo"] = str(repo)  # rewrite to the sandbox so validate_repo passes
        validation = validate_plan(raw, projects_dir=projects_dir)
        if not validation.ok or validation.plan is None:
            junk = True
            jobplan = _sim_fallback_plan(str(raw.get("goal", "")), projects_dir, repo)
        else:
            jobplan = validation.plan
            degraded = bool(validation.degraded)
            warnings = list(validation.warnings)
    # A cyclic graph degrades to the linear chain (degraded=True); a self-dependency is
    # dropped as a self-ref (a warning, not the cycle path) — both are the same "graph
    # reduced to today's serial fallback" the cycle scenarios assert, so surface either.
    graph_reduced = degraded or any(
        ("cycle" in w.lower() or "self depends_on" in w.lower()) for w in warnings
    )

    pid = jobplan.plan_id
    original_ids = {t.id for t in jobplan.tasks}
    # result.waves == the reference wave compiler: the REAL compile_waves topology
    # with ids SORTED within a wave (matches tools.dispatch_harness.battery.compute_waves,
    # which the table's meta-test checks the declared waves against).
    try:
        waves = [sorted(t.id for t in w) for w in compile_waves(jobplan)]
    except ValueError:
        waves = []  # cyclic degrade / degenerate — the scenario declares no waves

    # ---- 2. Scenario steering the base signature cannot carry (§9.2 rig grammar) ---
    fail_wave = None
    if pid.startswith("intred"):
        fail_wave = 1 if pid.endswith("w1") else 2  # intred-w1 / intred-wn (chain-3)
    recovered_signal = "recovered" in pid

    # ---- 2b. B8 rig-injection (§9.3/§9.4 — TEST-ONLY negative carrier) --------------
    # `armed` is empty for every existing caller / real dispatch -> the block is inert
    # and the run is byte-identical below. See the docstring for each rig's net.
    armed = [str(r).strip().upper() for r in (rigs or []) if str(r).strip()]
    rig_wave_fail_evidence: "str | None" = None
    if "N1" in armed:
        # The wave INTEGRATION gate catches the cross-task contract break the per-task
        # gates cannot see (each task's own tests pass). Fail the first post-merge gate.
        if fail_wave is None:
            fail_wave = 1
        rig_wave_fail_evidence = (
            "integration gate RED on the merged tree — N1: a task renamed the export its "
            "dependent's contract imports (ImportError on the integrated tree)"
        )
    if "N2" in armed and rig_oracle is None:
        # The overfit patch passes its OWN unit tests (the task merges) but violates a
        # JOB-oracle criterion -> force the job oracle to FAIL on the integrated tree.
        oracle_status = "failed"

    outcomes: list = []
    killed = {"hit": False}
    gate_calls = {"n": 0}

    def _sim_run_task(task: dict):
        outcome = run_task(task)
        if "code=HANG" in str(getattr(outcome, "detail", "") or ""):
            killed["hit"] = True
            raise _SimulatedWatchdogKill(str(task.get("task", "")))
        return outcome

    def _sim_redecompose(fleet_task: dict, evidence: str):
        # Fire the REAL evidence-fed split ONLY for a task the scenario scripts to
        # re-decompose-then-succeed (its RESULT code rides the failing evidence). The
        # rig marker triggers the scripted 14B; split_failed_task is the real W5 helper
        # (_SPLIT_TEMPLATE -> _parse_candidates -> _collapse -> _ruler, strict-improve).
        if "PARKED-THEN-CHILDREN-MERGE" not in str(evidence or ""):
            return None
        tid = str(fleet_task.get("task", ""))
        marked = dict(fleet_task, prompt=f"{fleet_task.get('prompt', '')}\n[[redecompose:{tid}]]")
        return split_failed_task(marked, evidence, generate_fn=generate_fn)

    def _sim_wave_gate(_repo: str) -> dict:
        gate_calls["n"] += 1
        n = gate_calls["n"]
        if fail_wave is not None and n == fail_wave:
            ev = rig_wave_fail_evidence or f"integration gate FAILED on the merged tree at wave {n}"
            return {"ok": False, "evidence": ev}
        return {"ok": True, "evidence": f"integration gate passed at wave {n}"}

    def _sim_job_oracle(_repo: str, _rel: str) -> dict:
        return {"status": oracle_status, "evidence": f"scripted job oracle: {oracle_status}"}

    ops = SwapOps(
        available_gb=lambda: 100.0,
        backend_alive=lambda: False,
        load_30b=lambda: True,
        wait_ready=lambda: True,
        run_task=_sim_run_task,
        cancel_requested=lambda: False,
        disarm_watchdog=lambda: None,
        stop_ovms=lambda: None,
        write_report=lambda _rid, _outs: None,
        restart_launcher=lambda: None,
        backend_ready=lambda: True,
        signal_failure=lambda _msg: None,
        stop_requested=lambda: False,
        repo_head=lambda _repo: "",
        dep_delta=lambda *_a: {},
        log_pack=lambda *_a: None,
        run_wave_gate=_sim_wave_gate,
        # N3 (§9.3): the injected REAL restore-before-grade replaces the scripted oracle,
        # so the tamper is graded against the plan bytes on the SAME driver path.
        run_job_oracle=(rig_oracle if rig_oracle is not None else _sim_job_oracle),
        redecompose=_sim_redecompose,
    )

    tasks = [{"repo": str(repo), "task": t.id, "prompt": t.prompt} for t in jobplan.tasks]
    driver = SwapDriver(
        run_id="sim", session_id="sim", tasks=tasks,
        swap_state_path=projects_dir / "swap-state.json", ops=ops,
        plan=jobplan, plan_store=None, plan_degraded=degraded,
    )

    # ---- 3. Drive the REAL wave loop (+ per-wave gate + job oracle + verdict) ------
    try:
        driver._run_plan_waves(outcomes)
    except _SimulatedWatchdogKill:
        pass  # the run 'died' around the wedged task — it stays frozen 'building'

    final_plan = driver._plan
    stopped = killed["hit"] or driver._plan_stopped
    cancelled = driver._plan_cancelled

    scorecard = build_scorecard(
        final_plan, run_id="sim", outcomes=outcomes, wave_gates=driver._wave_gates,
        job_evidence=driver._job_evidence, cancelled=cancelled, stopped=stopped,
        degraded=degraded, packs_consumed=driver._packs_consumed, wall_clock_s=0.0,
    )
    verdict = scorecard["verdict"]
    if recovered_signal and verdict == VERDICT_GREEN:
        # The work is GREEN-quality but the swap-back crash path fired and recovery
        # worked — a first-class verdict the boot side assigns, overlaid here.
        verdict = VERDICT_RECOVERED
        scorecard["verdict"] = VERDICT_RECOVERED
        scorecard["attribution"] = ""

    # ---- 4. task_status: real statuses + re-decomposed-parent subtree aggregation --
    final_status = {t.id: t.status for t in final_plan.tasks}
    new_ids = set(final_status) - original_ids
    for rid in original_ids - set(final_status):  # a parent the REAL re-decompose replaced
        kids = [final_status[c] for c in new_ids]
        if kids and all(s == STATUS_MERGED for s in kids):
            final_status[rid] = STATUS_MERGED          # the whole replacement subtree completed
        elif any(s == STATUS_BLOCKED for s in kids):
            final_status[rid] = STATUS_BLOCKED
        elif any(s == STATUS_PARKED for s in kids):
            final_status[rid] = STATUS_PARKED
        else:
            final_status[rid] = STATUS_SKIPPED

    # ---- 5. Honest report render: the real JOB_SUMMARY + derived-fact notes --------
    notes: list[str] = []
    if not plan_graph_enabled:
        notes.append("plan_graph OFF — the flat serial queue reproduces this run identically (§4.1.5 knob).")
    if graph_reduced:
        notes.append("the dependency graph was reduced to the original-order LINEAR chain / single-task FALLBACK — a self/cyclic dependency dropped (logged, not hidden).")
    if junk:
        notes.append("junk/unparseable plan — degraded to a SINGLE validated FALLBACK task (never zero work).")
    if any(s in (STATUS_PARKED, STATUS_BLOCKED) for s in final_status.values()) \
            or final_plan.redecompose_budget.spent:
        b = final_plan.redecompose_budget
        notes.append(f"evidence-fed re-decompose considered (bounded by the per_job budget {b.per_job}); spent {b.spent}.")
    if driver._packs_consumed > 0:
        edges = [f"{t.id} (from {', '.join(t.depends_on)})" for t in jobplan.tasks if t.depends_on]
        notes.append("context pack(s) consumed by dependent task(s): " + "; ".join(edges) + ".")
    acc = final_plan.job_acceptance.status
    if acc in ("passed", "failed"):
        notes.append(
            f"job oracle graded on the RESTORE-before-grade integrated tree: {acc}"
            + (" — the job is NOT done (unit-green is not job-green)." if acc == "failed" else ".")
        )
    if any(g.get("status") == "failed" for g in driver._wave_gates):
        notes.append("a wave INTEGRATION gate failed on the merged tree — later waves were SKIPPED (short-circuit).")
    if killed["hit"]:
        notes.append("the out-of-band budget WATCHDOG tree-killed a wedged task — STALLED (a harness fault, resumable).")
    if recovered_signal:
        notes.append("the model swap-back crash path fired and RECOVERED — the work is not lost.")

    # B8 rig-caught notes — appended ONLY when a rig was armed AND its net actually fired,
    # so the report names the net that CAUGHT the sabotage (a combined B8 run names the one
    # that fired first, never a rig that stayed latent). Honest by construction.
    if armed:
        gate_failed = any(g.get("status") == "failed" for g in driver._wave_gates)
        all_merged_final = bool(final_status) and all(
            s == STATUS_MERGED for s in final_status.values())
        if "N1" in armed and gate_failed:
            notes.append("rig N1 CAUGHT: a renamed contract export broke the dependent's import; "
                         "the wave INTEGRATION gate went RED and the dependent subtree was SKIPPED.")
        if acc == "failed" and all_merged_final:
            if rig_oracle is not None and "N3" in armed:
                notes.append("rig N3 CAUGHT: the tampered oracle was overwritten by the plan bytes "
                             "BEFORE grading (restore-before-grade); the ORIGINAL oracle graded and "
                             "the tree was restored exactly.")
            elif "N2" in armed:
                notes.append("rig N2 CAUGHT: unit tests green but the JOB oracle failed on the "
                             "integrated tree — the job is NOT done (unit-green is not job-green).")

    summary = render_job_summary(scorecard)
    if notes:
        summary += "\nSimulator notes:\n" + "\n".join(f"  - {n}" for n in notes)

    return JobPlanSimResult(
        task_status=final_status, waves=waves, job_verdict=verdict, summary=summary,
        attribution=scorecard.get("attribution", ""),
    )
