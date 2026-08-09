"""#1195 item 2 — the battery-close seam that RUNS the oracle mutation audit (#828).

``shared.fleet.oracle_mutation`` has been able to answer *"does this exam catch broken
code?"* since #828 and has never been asked: nothing outside its own tests called
:func:`~shared.fleet.oracle_mutation.run_oracle_mutation_audit`, so no run dir on this
machine carries an ``oracle-mutation.json``. Until this module existed, the battery could
report that an exam PASSED without ever establishing that the exam COULD fail — a
confident instrument measuring nothing, the defect family this stage closes.

Why battery close, and not the two nearer-looking seams
-------------------------------------------------------

* **Not beside #821's ``oracle_qa``.** That stage runs at oracle AUTHORSHIP time, inside
  ``acceptance.author_and_qa_job_oracle``, while the plan is still being decomposed. The
  audit mutates *the feature files the oracle imports* and requires a baseline in which the
  oracle PASSES — at authorship time the implementation does not exist yet, so every audit
  there would resolve zero targets and stamp ``skipped-no-targets`` forever. The two are
  duals in what they measure, not neighbours in when they can run.
* **Not inside per-job grading.** Grading runs on the dispatch critical path with the coder
  waiting inside the GPU window, and it runs BEFORE the verdict is known. The audit is
  GREEN-path-only by construction (it audits the grader of work that passed) and its own
  docstring places it off that path deliberately.
* **Battery close is where the inputs exist.** By then the run dir has banked the seeded
  ``job-oracle-*.py`` (the exam as graded) and the deliverable tree has been archived, the
  verdict is final so GREEN-only selection is possible, and the wall-clock is spent after
  the coder is done. This is the same reasoning that puts ``green_quality`` and
  ``traceability`` here, and this stage composes with them: it runs after the quality audit
  and BEFORE ``classify()``, so this sidecar is on disk by the time the traceability stage
  is reached. That ordering is LOAD-BEARING: ``traceability``'s ``L4-KILLS`` rung reads the
  per-mutant attribution this sidecar banks, and a stage ordered after it would leave that
  rung permanently unmeasured.

The audited tree is a COPY
--------------------------

The audit works by writing mutated source into the tree, running the oracle, and restoring.
At battery close the only trees available are the night's archived evidence copy and the
live sandbox project dir — and a hard kill between the write and the restore would leave a
mutant behind in one of them. So the resolved tree is copied to a temp dir and the copy is
audited; the operator's artifacts are never written to at all. Structural absence of the
risk, rather than a restore path that has to survive being killed.

Cost, measured
--------------

Measured on this host through this stage (2026-07-30, Core Ultra 7 258V): one pinned oracle
invocation (``uv run --no-project --with pytest==9.1.1 --with hypothesis==6.155.7``) costs
**5.67 s** — uv builds a fresh ephemeral environment per run, and the audit's per-run isolated
home means that cost is paid every mutant, not once. A full ``MAX_MUTANTS`` = 20 audit plus its
baseline is therefore ~2 minutes per GREEN, and a four-GREEN night ~8 minutes. (A bare
``uv run`` outside the audit's isolated home costs ~0.9 s; measuring THAT and calling it the
audit's cost would understate the stage six-fold, which is why the number here is measured
through this entry point.)

The per-job 300 s bound cannot bound that at battery scale — four GREENs each entitled to
300 s is 20 minutes. :data:`ORACLE_MUTATION_BATTERY_BUDGET_S` caps the STAGE, and GREENs past
the cap are stamped ``skipped-battery-budget`` — bounded, and never silently unaudited.
Not measured: cost against a real battery deliverable (bigger tree, more import targets, more
mutation sites) rather than the two-function fixture these numbers came from.

Invariants, enforced here rather than merely documented
-------------------------------------------------------

* **ADVISORY / never verdict-changing.** Only the reserved ``oracle_mutation_*`` evidence
  keys in :data:`RESERVED_EVIDENCE_KEYS` are written; ``(verdict, attribution)`` is
  snapshotted per card and restored on any mutation — the ``green_quality`` advisory lock,
  mirrored.
* **Fail-soft, never fail-open.** Every miss produces a sidecar and a stamp saying so. A
  score is rendered only when :func:`~shared.fleet.oracle_mutation.is_measured` holds, and
  the unmeasured count is reported even at zero — an audit nobody could run must never
  render like an audit that found nothing wrong.
* **It cannot sink the night.** The stage import lives inside the caller's guard and every
  per-job path is wrapped, so no fault here can prevent ``battery-summary.json`` being
  written.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import time
from pathlib import Path
from typing import Callable, Optional

from shared.fleet.acceptance import JOB_ORACLE_ALLOWED_PATHS
from shared.fleet.oracle_mutation import (
    ORACLE_MUTATION_BUDGET_S,
    ORACLE_MUTATION_SIDECAR_NAME,
    is_measured,
    not_measured_evidence,
    run_oracle_mutation_audit,
)
from tools.dispatch_harness.scorecard import Scorecard, VERDICT_GREEN

MUTATION_SCHEMA = "oracle-mutation-stage/v1"

#: Wall-clock cap for the WHOLE stage across every GREEN of one battery (registered in
#: ``shared/timeout_registry.py``). The per-job bound belongs to the audit itself; this one
#: exists because a night has more than one GREEN and an advisory instrument must never be
#: able to extend the night without a ceiling. On expiry the remaining GREENs are stamped
#: :data:`STATUS_BATTERY_BUDGET` — bounded, and visible as unaudited rather than absent.
ORACLE_MUTATION_BATTERY_BUDGET_S: float = 900.0

#: The stamp for a GREEN the stage never reached because the battery budget was spent.
STATUS_BATTERY_BUDGET = "skipped-battery-budget"

#: Trees this large are not a coder deliverable; copying one to audit it is not a cost the
#: night should pay. Bounded rather than unbounded, and stamped honestly when it trips.
_MAX_COPY_FILES: int = 5000

#: Never copied into the audit tree: version control, caches, and installed environments —
#: none of it is mutable feature code and all of it is expensive to copy.
_COPY_IGNORE = shutil.ignore_patterns(
    ".git", "__pycache__", "node_modules", ".venv", "venv", ".pytest_cache", ".mypy_cache",
)

#: How the dispatch names the banked oracle in a run dir. Deliberately EXTENSION-AGNOSTIC: a
#: node exam is banked as ``job-oracle-acceptance.job.test.mjs``, and a ``*.py`` glob would
#: report it as "no banked oracle" rather than as the honest "no host mutation runner for
#: this ecosystem". Both are not-measured, but only one of them is true.
_ORACLE_GLOB = "job-oracle-*"

#: One line, capped — the scorecard S6 evidence discipline (schema caps every value at 1000).
_EVIDENCE_VALUE_CAP = 300

# ---------------------------------------------------------------------------
# Reserved evidence keys — this stage is their SOLE writer, and it writes nothing else
# ---------------------------------------------------------------------------

#: The score, or an explicit not-measured string. ALWAYS stamped: a key present only on a
#: result would make silence ambiguous, and silence must never read as a clean exam.
EV_SCORE = "oracle_mutation_score"
#: The advisory coverage band (strong/adequate/weak/unknown) — never a verdict.
EV_COVERAGE = "oracle_mutation_coverage"
#: The raw ``mutation_audit`` stamp (``run`` / ``partial-budget`` / a ``skipped-*`` reason).
EV_STATUS = "oracle_mutation_status"
#: POINTER to the sidecar, never its content.
EV_FINDINGS = "oracle_mutation_findings"
#: Surviving mutants as ``operator file:line`` — WHERE the exam is blind (array, only when any).
EV_SURVIVORS = "oracle_mutation_survivors"

RESERVED_EVIDENCE_KEYS: frozenset[str] = frozenset({
    EV_SCORE, EV_COVERAGE, EV_STATUS, EV_FINDINGS, EV_SURVIVORS,
})


def _clip(text: object) -> str:
    return " ".join(str(text).split())[:_EVIDENCE_VALUE_CAP]


class _RunsDirConfig:
    """The minimal shape :func:`run_oracle_mutation_audit` persists through (it reads only
    ``config.runs_dir``). Passing this rather than the live dispatch config keeps the audit's
    write confined to the one directory this stage means it to touch."""

    __slots__ = ("runs_dir",)

    def __init__(self, runs_dir: Path) -> None:
        self.runs_dir = str(runs_dir)


def _oracle_rel_path(banked_name: str) -> Optional[str]:
    """The repo-relative path the banked ``job-oracle-<basename>`` was graded at, resolved
    against :data:`JOB_ORACLE_ALLOWED_PATHS` rather than reconstructed by string surgery.
    ``None`` when the name matches no allowed oracle path — the audit then has no place to
    write the exam and honestly declines."""
    for allowed in sorted(JOB_ORACLE_ALLOWED_PATHS):
        if banked_name == f"job-oracle-{Path(allowed).name}":
            return allowed
    return None


def _resolve_repo(repo_slug: str, out_dir: Optional[Path], projects_dir: Optional[Path]) -> Optional[Path]:
    """The GREEN's shipped tree: the night's archived copy if present, else the live sandbox
    project dir. ``None`` when neither exists. Deliberately the SAME resolution order
    ``green_quality`` uses, so the two advisory stages never disagree about which tree a
    given GREEN delivered."""
    if out_dir is not None:
        archived = out_dir / "repos-archived" / repo_slug
        if archived.is_dir():
            return archived
    if projects_dir is not None:
        live = projects_dir / repo_slug
        if live.is_dir():
            return live
    return None


def _copy_for_audit(src: Path, dest: Path) -> Optional[str]:
    """Copy *src* to *dest* for mutation. Returns ``None`` on success, else a skip reason.

    The audit mutates what it is pointed at; pointing it at a copy is what keeps the
    operator's archived evidence and live sandbox unwritten even if this process is killed
    between a mutant's write and its restore."""
    try:
        count = sum(1 for _ in src.rglob("*"))
    except OSError as exc:
        return f"skipped-tree-unreadable-{type(exc).__name__}"
    if count > _MAX_COPY_FILES:
        return "skipped-tree-too-large"
    try:
        shutil.copytree(src, dest, ignore=_COPY_IGNORE, dirs_exist_ok=True, symlinks=True)
    except (OSError, shutil.Error) as exc:
        return f"skipped-copy-failed-{type(exc).__name__}"
    return None


def _persist(run_dir: Path, evidence: dict) -> str:
    """Bank the evidence as ``oracle-mutation.json``; returns the pointer or ``""``.
    Used for the paths that never reach the audit (which persists its own)."""
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / ORACLE_MUTATION_SIDECAR_NAME).write_text(
            json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return f"{run_dir.name}/{ORACLE_MUTATION_SIDECAR_NAME}"
    except OSError:
        return ""


def evidence_stamp(evidence: dict, pointer: str) -> dict:
    """The reserved ``oracle_mutation_*`` stamp for one audit result.

    :data:`EV_SCORE` and :data:`EV_STATUS` are UNCONDITIONAL. When the audit did not
    actually discriminate, the score reads ``not-measured (<reason>)`` rather than the
    literal ``0/0`` the evidence dict carries — ``0/0`` is a number, and a number invites a
    reader to treat it as a result."""
    measured = is_measured(evidence)
    status = str(evidence.get("mutation_audit", "not-run"))
    stamp: dict = {
        EV_STATUS: _clip(status),
        EV_SCORE: (_clip(evidence.get("oracle_mutation_score", "0/0")) if measured
                   else _clip(f"not-measured ({status})")),
        EV_COVERAGE: _clip(evidence.get("oracle_mutation_coverage", "unknown")),
    }
    if pointer:
        stamp[EV_FINDINGS] = _clip(pointer)
    survivors = evidence.get("survivors") or []
    if measured and survivors:
        stamp[EV_SURVIVORS] = [
            _clip(f"{s.get('operator', '?')} {s.get('file', '?')}:{s.get('line', '?')}")
            for s in survivors if isinstance(s, dict)
        ]
    return stamp


#: The audit as this stage calls it: ``(config, run_id, repo, rel_path, oracle_code, *, budget_s)``.
Audit = Callable[..., dict]


def audit_one_green(
    sc: Scorecard,
    *,
    runs_dir: Path,
    out_dir: Optional[Path],
    projects_dir: Optional[Path],
    budget_s: float,
    audit: Audit = run_oracle_mutation_audit,
) -> dict:
    """Audit ONE GREEN's oracle and return the evidence dict (always a dict, never a raise).

    Resolves what the run banked, copies the delivered tree, and hands the audit the SAME
    oracle bytes the grade ran. Every unmet precondition returns an honest not-measured
    evidence dict instead of a score.

    ``audit`` is injected on the same pattern as ``green_quality``'s ``security_scan``, so a
    test can drive this stage's resolution/budget/stamping logic without spawning N pytest
    subprocesses per case. It does NOT substitute for exercising the real audit: the
    discrimination proof runs the real one through this same entry point."""
    run_id = str(sc.run_id or "")
    run_dir = runs_dir / run_id if run_id else None
    if run_dir is None or not run_dir.is_dir():
        return not_measured_evidence("", "skipped-no-run-dir", budget_s)

    oracles = sorted(p for p in run_dir.glob(_ORACLE_GLOB) if p.is_file())
    if not oracles:
        return not_measured_evidence("", "skipped-no-banked-oracle", budget_s)
    # Take the first banked file that names an ALLOWED oracle path; a run banks one, and
    # resolving rather than assuming keeps an unexpected sibling from being audited as the exam.
    resolved = [(p, _oracle_rel_path(p.name)) for p in oracles]
    match = next(((p, rel) for p, rel in resolved if rel is not None), None)
    if match is None:
        return not_measured_evidence("", "skipped-unrecognised-oracle-path", budget_s)
    oracle_file, rel_path = match
    try:
        oracle_code = oracle_file.read_text(encoding="utf-8")
    except OSError as exc:
        return not_measured_evidence(rel_path, f"skipped-oracle-unreadable-{type(exc).__name__}", budget_s)

    source_repo = _resolve_repo(str(sc.repo or ""), out_dir, projects_dir)
    if source_repo is None:
        return not_measured_evidence(rel_path, "skipped-no-delivered-tree", budget_s)

    with tempfile.TemporaryDirectory(prefix="oracle_mut_tree_") as tmp:
        audit_tree = Path(tmp) / "repo"
        reason = _copy_for_audit(source_repo, audit_tree)
        if reason is not None:
            return not_measured_evidence(rel_path, reason, budget_s)
        return audit(
            _RunsDirConfig(runs_dir), run_id, str(audit_tree), rel_path, oracle_code,
            budget_s=budget_s,
        )


def audit_green_oracles(
    scorecards: "list[Scorecard]",
    *,
    runs_dir: "str | Path | None" = None,
    out_dir: "str | Path | None" = None,
    projects_dir: "str | Path | None" = None,
    battery_budget_s: float = ORACLE_MUTATION_BATTERY_BUDGET_S,
    per_job_budget_s: float = ORACLE_MUTATION_BUDGET_S,
    clock: Callable[[], float] = time.monotonic,
    audit: Audit = run_oracle_mutation_audit,
    log: "Callable[[str], None] | None" = None,
) -> dict:
    """The battery-close entry point: run the mutation audit over every GREEN, bank each
    ``oracle-mutation.json``, stamp the reserved evidence keys, and return the summary block.

    NEVER raises and NEVER changes a verdict/attribution — snapshotted per card and restored
    on any mutation. Idempotent and re-run-safe: a GREEN whose run dir already carries a
    MEASURED sidecar is re-stamped from it rather than re-audited, so the combined-set second
    pass in ``__main__`` costs nothing instead of paying for the whole night twice."""
    if not runs_dir:
        return _block([], greens=sum(1 for s in scorecards if s.verdict == VERDICT_GREEN),
                      budget_s=battery_budget_s, exhausted=False,
                      reason="no runs_dir — the banked oracles could not be located")
    runs_path = Path(runs_dir)
    out_path = Path(out_dir) if out_dir else None
    projects_path = Path(projects_dir) if projects_dir else None
    deadline = clock() + float(battery_budget_s)

    results: list[dict] = []
    greens = 0
    exhausted = False
    # Deterministic order, so a budget squeeze truncates the SAME way on a re-run rather than
    # auditing a different subset each time.
    for sc in sorted(scorecards, key=lambda s: str(s.job_id or "")):
        if sc.verdict != VERDICT_GREEN:
            continue
        greens += 1
        before = (sc.verdict, sc.attribution)
        try:
            evidence = _reuse_banked(runs_path, sc)
            reused = evidence is not None
            if evidence is None:
                if clock() >= deadline:
                    exhausted = True
                    evidence = not_measured_evidence("", STATUS_BATTERY_BUDGET, per_job_budget_s)
                else:
                    evidence = audit_one_green(
                        sc, runs_dir=runs_path, out_dir=out_path, projects_dir=projects_path,
                        budget_s=min(float(per_job_budget_s), max(1.0, deadline - clock())),
                        audit=audit,
                    )
            pointer = _pointer_for(runs_path, sc, evidence, reused=reused)
            sc.evidence = {**(sc.evidence or {}), **evidence_stamp(evidence, pointer)}
            results.append(evidence)
            if log:
                log(f"[oracle-mutation] {sc.job_id}: {evidence.get('mutation_audit')} "
                    f"{evidence.get('oracle_mutation_score')}")
        except Exception as exc:  # noqa: BLE001 — one GREEN's audit fault never sinks the night
            if log:
                log(f"[oracle-mutation] {sc.job_id}: audit failed (fail-soft): {exc}")
            fault = not_measured_evidence("", f"skipped-stage-error-{type(exc).__name__}",
                                          per_job_budget_s)
            # Even a crashed audit is stamped: an unstamped GREEN would be the one state a
            # reader could mistake for "nothing to report".
            try:
                sc.evidence = {**(sc.evidence or {}), **evidence_stamp(fault, "")}
            except Exception:  # noqa: BLE001 — stamping is best-effort; never fatal
                pass
            results.append(fault)
        finally:
            # The advisory invariant, enforced: if a future edit ever moves a verdict from
            # here, put it back rather than let a mislabelled card bank.
            if (sc.verdict, sc.attribution) != before:
                sc.verdict, sc.attribution = before

    return _block(results, greens=greens, budget_s=battery_budget_s, exhausted=exhausted)


def _reuse_banked(runs_path: Path, sc: Scorecard) -> Optional[dict]:
    """A previously banked sidecar for this GREEN, but ONLY when it records a measured audit.
    An unmeasured sidecar is retried rather than reused — a miss caused by a tree that had not
    been archived yet must not freeze into a permanent not-measured stamp."""
    run_id = str(sc.run_id or "")
    if not run_id:
        return None
    try:
        path = runs_path / run_id / ORACLE_MUTATION_SIDECAR_NAME
        if not path.is_file():
            return None
        banked = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return banked if is_measured(banked) else None


def _pointer_for(runs_path: Path, sc: Scorecard, evidence: dict, *, reused: bool) -> str:
    """The sidecar pointer, banking *evidence* first unless it WAS the banked sidecar.

    A fresh attempt always overwrites: an earlier unmeasured sidecar (a tree that had not been
    archived yet, a budget squeeze) must not survive as the record of a later attempt that saw
    something different. Only a reuse leaves the file alone, because there the file IS the
    evidence."""
    run_id = str(sc.run_id or "")
    if not run_id:
        return ""
    run_dir = runs_path / run_id
    if reused:
        return f"{run_id}/{ORACLE_MUTATION_SIDECAR_NAME}"
    return _persist(run_dir, evidence)


def _block(results: "list[dict]", *, greens: int, budget_s: float, exhausted: bool,
           reason: str = "") -> dict:
    """The ``oracle_mutation`` summary block for ``battery-summary.json``."""
    measured = [r for r in results if is_measured(r)]
    bands = {b: sum(1 for r in measured if r.get("oracle_mutation_coverage") == b)
             for b in ("strong", "adequate", "weak")}
    return {
        "schema": MUTATION_SCHEMA,
        "advisory": True,
        "greens": greens,
        "audited": len(measured),
        # Reported SEPARATELY and rendered even at zero: a GREEN whose exam was proven sharp,
        # one whose exam was proven blind, and one nobody could audit are three different
        # states, and collapsing the third into either of the others is the fail-open here.
        "not_measured": greens - len(measured),
        "bands": bands,
        "killed": sum(int(r.get("killed", 0) or 0) for r in measured),
        "ran": sum(int(r.get("ran", 0) or 0) for r in measured),
        "survivors_total": sum(int(r.get("survived", 0) or 0) for r in measured),
        "budget_s": float(budget_s),
        "budget_exhausted": exhausted,
        "reason": reason,
    }


def render_kpi(block: dict) -> list[str]:
    """The human KPI lines for the battery-summary render. Unlike the other advisory stages
    this renders whenever there were GREENs at all — an entirely unaudited night is precisely
    the state that must not be invisible."""
    if not block or not int(block.get("greens", 0) or 0):
        return []
    bands = block.get("bands") or {}
    ran = int(block.get("ran", 0) or 0)
    killed = int(block.get("killed", 0) or 0)
    score = f"{killed}/{ran}" if ran else "no mutants counted"
    line = (f"oracle-mutation: audited {block.get('audited', 0)}/{block.get('greens', 0)} GREENs, "
            f"mutants killed {score}; bands strong {int(bands.get('strong', 0) or 0)}, "
            f"adequate {int(bands.get('adequate', 0) or 0)}, weak {int(bands.get('weak', 0) or 0)}")
    detail = (f"  not-measured={block.get('not_measured', 0)}, "
              f"surviving-mutants={block.get('survivors_total', 0)}, "
              f"budget-exhausted={bool(block.get('budget_exhausted'))}")
    return [line + " [ADVISORY — never changes a verdict]", detail]
