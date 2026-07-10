"""Gold-plan calibration scorer (M2 W2, #740) — measure a decompose against a gold plan.

The W2 elicitation makes the 14B PROPOSE a dependency graph; this scorer is how the
proposal quality is MEASURED instead of felt (plan §9.1 — it is also the attribution
instrument: when a battery job fails, calibration data says whether planning or
building was at fault). It compares a candidate plan (a raw jobplan/v1 dict, or a bare
``decompose_request`` task list — both tolerated) against a hand-authored gold plan on
three axes:

  * **task-count match** — did the decomposition land the gold's granularity?
  * **dependency-edge F1** — candidate tasks are aligned to gold tasks by greedy
    slug-token Jaccard (deterministic: gold order, ties to the earliest candidate),
    then edges ``(task, depends_on)`` are compared through that alignment. Convention
    for empty sets: precision with zero predicted edges is 1.0 (no false positives),
    recall with zero gold edges is 1.0; F1 is 0 when P+R is 0 — so a no-edge candidate
    against a no-edge gold scores 1.0 and against a real graph scores 0.
  * **contract-file overlap** — Jaccard over the normalized union of
    ``contract.creates`` paths (case/backslash/leading-``./`` insensitive), global
    across tasks so file placement is scored independently of task alignment.

Deterministic, model-free, offline. Gold plans live at ``evals/battery/gold/*.json``
(Lane V authors the canonical three; ``gold-b1-expense-tracker.provisional.json`` is
Lane A's provisional stand-in for the scorer's own tests — supersede, don't extend).

CLI::

    python -m evals.plan_calibration --candidate plan.json \
        --gold evals/battery/gold [--report report.md]

Exit codes: 0 scored; 2 unreadable/malformed input (fail loud, never a silent skip).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from shared.fleet.dispatch import slugify_task


@dataclass(frozen=True)
class PlanScore:
    """One candidate-vs-gold measurement (all fields deterministic)."""

    gold_name: str
    gold_task_count: int
    candidate_task_count: int
    task_count_match: bool
    alignment: list[tuple[str, str]] = field(default_factory=list)  # (candidate, gold)
    edge_precision: float = 0.0
    edge_recall: float = 0.0
    edge_f1: float = 0.0
    contract_file_jaccard: float = 0.0


# ---------------------------------------------------------------------------
# Tolerant plan readers (jobplan/v1 dicts AND bare decompose task lists)
# ---------------------------------------------------------------------------


def plan_tasks(plan: object) -> list[dict]:
    """The task dicts of *plan*: a jobplan/v1 dict (``plan["tasks"]``) or a bare
    task list (``decompose_request(...).tasks``). Anything else ⇒ ``[]``."""
    if isinstance(plan, dict):
        tasks = plan.get("tasks")
        return [t for t in tasks if isinstance(t, dict)] if isinstance(tasks, list) else []
    if isinstance(plan, list):
        return [t for t in plan if isinstance(t, dict)]
    return []


def task_id(task: dict) -> str:
    """The slug identity of a task — ``id`` (jobplan) or ``task`` (decompose)."""
    raw = str(task.get("id") or task.get("task") or "").strip()
    return slugify_task(raw) if raw else ""


def _edges(tasks: list[dict]) -> set[tuple[str, str]]:
    """``(task, dep)`` edge set; refs slugified; unknown-shape deps ignored."""
    out: set[tuple[str, str]] = set()
    for t in tasks:
        tid = task_id(t)
        deps = t.get("depends_on")
        if not tid or not isinstance(deps, list):
            continue
        for d in deps:
            if isinstance(d, str) and d.strip():
                out.add((tid, slugify_task(d)))
    return out


def _contract_files(tasks: list[dict]) -> set[str]:
    """Normalized union of ``contract.creates`` paths across all tasks."""
    files: set[str] = set()
    for t in tasks:
        contract = t.get("contract")
        if not isinstance(contract, dict):
            continue
        creates = contract.get("creates")
        if not isinstance(creates, list):
            continue
        for path in creates:
            if isinstance(path, str) and path.strip():
                norm = path.strip().lower().replace("\\", "/")
                while norm.startswith("./"):
                    norm = norm[2:]
                files.add(norm)
    return files


# ---------------------------------------------------------------------------
# Alignment + scoring
# ---------------------------------------------------------------------------


def _tokens(slug: str) -> set[str]:
    return {t for t in slug.split("-") if t}


def align_tasks(candidate_ids: list[str], gold_ids: list[str]) -> list[tuple[str, str]]:
    """Greedy candidate→gold alignment by slug-token Jaccard.

    Deterministic: gold ids are taken in order; each takes the highest-Jaccard
    UNMATCHED candidate (ties → the earliest candidate); zero-overlap pairs never
    match. Imperfect alignment is the POINT — a decomposition whose task identities
    drift from the gold's scores lower, which is what calibration measures."""
    pairs: list[tuple[str, str]] = []
    taken: set[str] = set()
    for gid in gold_ids:
        gtok = _tokens(gid)
        best, best_score = "", 0.0
        for cid in candidate_ids:
            if cid in taken:
                continue
            ctok = _tokens(cid)
            union = gtok | ctok
            score = (len(gtok & ctok) / len(union)) if union else 0.0
            if score > best_score:
                best, best_score = cid, score
        if best and best_score > 0.0:
            taken.add(best)
            pairs.append((best, gid))
    return pairs


def _prf(predicted: set, gold: set) -> tuple[float, float, float]:
    """(precision, recall, F1) with the empty-set conventions from the module doc."""
    tp = len(predicted & gold)
    precision = (tp / len(predicted)) if predicted else 1.0
    recall = (tp / len(gold)) if gold else 1.0
    f1 = 0.0 if (precision + recall) == 0 else 2 * precision * recall / (precision + recall)
    return precision, recall, f1


def score_plan(candidate: object, gold: dict, *, gold_name: str = "") -> PlanScore:
    """Score *candidate* (jobplan dict or decompose task list) against *gold*."""
    cand_tasks = plan_tasks(candidate)
    gold_tasks = plan_tasks(gold)
    cand_ids = [task_id(t) for t in cand_tasks if task_id(t)]
    gold_ids = [task_id(t) for t in gold_tasks if task_id(t)]

    alignment = align_tasks(cand_ids, gold_ids)
    to_gold = dict(alignment)
    # Candidate edges mapped into gold identity space; an unaligned endpoint keeps
    # its own slug (it can never match a gold edge — the honest precision penalty).
    cand_edges = {(to_gold.get(a, a), to_gold.get(b, b)) for a, b in _edges(cand_tasks)}
    gold_edges = _edges(gold_tasks)
    precision, recall, f1 = _prf(cand_edges, gold_edges)

    cand_files = _contract_files(cand_tasks)
    gold_files = _contract_files(gold_tasks)
    union = cand_files | gold_files
    jaccard = (len(cand_files & gold_files) / len(union)) if union else 1.0

    return PlanScore(
        gold_name=gold_name,
        gold_task_count=len(gold_ids),
        candidate_task_count=len(cand_ids),
        task_count_match=len(cand_ids) == len(gold_ids),
        alignment=alignment,
        edge_precision=precision,
        edge_recall=recall,
        edge_f1=f1,
        contract_file_jaccard=jaccard,
    )


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------


def render_markdown(scores: list[PlanScore], *, candidate_name: str = "candidate") -> str:
    """A small, deterministic calibration report (one table row per gold)."""
    lines = [
        "# Plan-graph calibration report (M2 W2, #740)",
        "",
        f"Candidate: `{candidate_name}` — scored against {len(scores)} gold plan(s).",
        "",
        "| Gold | Tasks (gold/cand) | Count match | Edge P | Edge R | Edge F1 | Contract-file Jaccard |",
        "|---|---|---|---|---|---|---|",
    ]
    for s in scores:
        lines.append(
            f"| {s.gold_name} | {s.gold_task_count}/{s.candidate_task_count} "
            f"| {'yes' if s.task_count_match else 'NO'} "
            f"| {s.edge_precision:.2f} | {s.edge_recall:.2f} | {s.edge_f1:.2f} "
            f"| {s.contract_file_jaccard:.2f} |"
        )
    lines += [
        "",
        "Method: greedy slug-token-Jaccard task alignment (gold order, earliest-candidate",
        "ties); edges compared through the alignment; contract files compared as a global",
        "normalized set. Empty-set conventions: P=1.0 with no predicted edges, R=1.0 with",
        "no gold edges, Jaccard=1.0 when both file sets are empty.",
        "",
    ]
    for s in scores:
        if s.alignment:
            pairs = ", ".join(f"`{c}`->`{g}`" for c, g in s.alignment)
            lines.append(f"- {s.gold_name} alignment: {pairs}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _gold_paths(spec: str) -> list[Path]:
    p = Path(spec)
    if p.is_dir():
        return sorted(p.glob("*.json"))
    return [p]


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(
        description="Score a decompose/jobplan output against gold plans (M2 W2)."
    )
    parser.add_argument("--candidate", required=True, help="candidate plan JSON path")
    parser.add_argument(
        "--gold", required=True, nargs="+",
        help="gold plan JSON path(s) and/or director(y/ies) of *.json golds",
    )
    parser.add_argument("--report", default="", help="write the markdown report here")
    args = parser.parse_args(argv)

    try:
        candidate = _load_json(Path(args.candidate))
    except (OSError, ValueError) as exc:
        print(f"calibration: unreadable candidate {args.candidate}: {exc}", file=sys.stderr)
        return 2

    scores: list[PlanScore] = []
    for spec in args.gold:
        paths = _gold_paths(spec)
        if not paths:
            print(f"calibration: no gold plans at {spec}", file=sys.stderr)
            return 2
        for path in paths:
            try:
                gold = _load_json(path)
            except (OSError, ValueError) as exc:
                print(f"calibration: unreadable gold {path}: {exc}", file=sys.stderr)
                return 2
            if not isinstance(gold, dict) or not plan_tasks(gold):
                print(f"calibration: {path} is not a usable gold plan", file=sys.stderr)
                return 2
            scores.append(score_plan(candidate, gold, gold_name=path.stem))

    report = render_markdown(scores, candidate_name=Path(args.candidate).name)
    if args.report:
        Path(args.report).write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
