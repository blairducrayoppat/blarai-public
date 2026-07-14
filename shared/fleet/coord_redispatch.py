"""Coordinator redispatch staging — PARKED-HONEST → ONE approval-gated proposal (#844 C2).

The C2 lifecycle limb that turns a parked fleet job — the honest-shortfall outcome
class — into exactly ONE staged, approval-gated REDISPATCH PROPOSAL in the
born-encrypted coordinator proposal store (ADR-039 §2.10 C2 item 4; §2.12 items
4/5). Deterministic end to end: C2 is the event-driven, deterministic phase, so
the proposal here is COMPOSED BY CODE from structured run facts — no model drafts
anything in this module (the 14B drafting proposals is C3/C4 territory).

**The verdict bridge — which outcomes qualify.** A run's ``SUMMARY.txt`` parses
via :func:`shared.fleet.dispatch.parse_summary` into
:class:`~shared.fleet.dispatch.TaskOutcome` rows whose ``result`` is classified
by ``dispatch._classify_result``. The SUMMARY-level word for the honest-shortfall
class is ``PARKED`` ("not merged" — a VALID run whose work survives on a branch,
review pending); the battery scorecard taxonomy
(``tools/dispatch_harness/scorecard.py``) names the same class ``PARKED-HONEST``.
That is the one redispatch candidate: unfinished business that banks. The other
results are deliberately NOT candidates:

  * ``MERGED``  — done; nothing to redispatch.
  * ``NOTHING`` — no changes produced; a redispatch re-runs a no-op.
  * ``BLOCKED`` — possible secret, left uncommitted; a HUMAN decision, never an
    automated re-ask.
  * ``TIMEOUT`` — tree-killed (#757); the run-invalid (STALLED) family — its
    measurements can't be trusted, so any re-run wants a human look first.
  * ``UNKNOWN`` — unparseable evidence; proposing over evidence we cannot read
    is guesswork, not coordination.

:data:`RECOGNIZED_RESULTS` pins this contract. Keying on a cross-module string
literal is correct today and silently wrong after a rename — and a DORMANT limb's
silent wrongness would surface only at go-live — so the regression lock in
``shared/tests/test_coord_redispatch.py`` extracts ``_classify_result``'s return
literals from source and fails the moment the fleet's vocabulary drifts from the
eligible/excluded split declared here.

**The SG ruler (the CaMeL property, ADR-039 §2.2 control 1).** The proposal's
execution *target* is RE-DERIVED by deterministic code from the TRUSTED,
structured ``repo_id`` — :func:`shared.coordinator.governed_core.
derive_workspace_target` then :func:`~shared.coordinator.governed_core.
check_target` at ``phase="STAGING"`` — never from model free text and never from
run-report content. A governed-core or otherwise-invalid target refuses the whole
cycle FAIL-CLOSED before anything reaches the store (the same pattern
:func:`shared.fleet.coord_lifecycle.evaluate_dor` wires for the DoR gate).
Untrusted run text (task names, RESULT lines) may shape the proposal's *content*;
it can never select its *target*.

**Born-encrypted payload (ADR-039 §2.13 item 2).** The proposal payload is
content-bearing (goal text, task text, evidence pointers), so it rides the
store's existing AES-256-GCM one-DEK envelope — the OPPOSITE posture from the
stall limb's plaintext seen-set (non-content-bearing metadata). No new crypto is
introduced here; the store owns it all.

**The execution-time seam (ADR-039 §2.12 item 4 — TOCTOU closure).** Approval is
not freshness: :func:`revalidate_for_execution` re-derives the target from the
proposal's own structured payload and re-runs the SG ruler at
``phase="EXECUTION"``. The future approve→execute hook (C3/C5 wiring) MUST call
it and treat a DENY as refuse-with-comment — never "best-effort executed." It is
built and tested here as a pure function so the seam exists from day one; nothing
wires it to any execution path yet.

FAIL-SOFT cycle (mirrors :mod:`shared.fleet.coord_stall_monitor`): a store fault
on one outcome is recorded and the cycle proceeds — a coordinator failure must
never crash a dispatch/heartbeat cycle — and because no proposal was written, the
same evidence naturally retries next cycle. SG refusals, by contrast, are
FAIL-CLOSED and final for that evidence (re-checking next cycle refuses again,
idempotently).

DORMANCY: no production boot path calls :func:`stage_redispatch_proposals`
today. The C3 heartbeat / a C2 dispatch-event hook wires it later, dormant
behind ``[coordinator]``. Importing this module arms nothing.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final, Mapping, Sequence

from shared.coordinator.governed_core import (
    BoundaryDecision,
    GovernedCoreRoots,
    TargetVerdict,
    check_target,
    derive_workspace_target,
)
from shared.coordinator.proposal_store import (
    Proposal,
    ProposalLane,
    ProposalStore,
    proposal_fingerprint,
)
from shared.fleet.dispatch import TaskOutcome

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# The verdict contract (pinned by the source-introspection regression lock)
# ---------------------------------------------------------------------------

#: The proposal class this limb stages — part of every fingerprint, so the
#: literal is release-stable (a rename would orphan the dedup history). Locked by
#: test.
REDISPATCH_PROPOSAL_CLASS: Final[str] = "redispatch-parked"

#: ``TaskOutcome.result`` values that ARE redispatch candidates: exactly the
#: honest-shortfall class (SUMMARY word ``PARKED``; scorecard word
#: ``PARKED-HONEST``).
REDISPATCH_ELIGIBLE_RESULTS: Final[frozenset[str]] = frozenset({"PARKED"})

#: ``TaskOutcome.result`` values this limb RECOGNIZES and deliberately refuses to
#: stage for (each reason in the module docstring).
REDISPATCH_EXCLUDED_RESULTS: Final[frozenset[str]] = frozenset(
    {"MERGED", "BLOCKED", "NOTHING", "TIMEOUT", "UNKNOWN"}
)

#: The complete result vocabulary this limb has classified — MUST equal the set
#: of literals ``dispatch._classify_result`` can return (the regression lock
#: enforces it). A new fleet result word fails the lock until it is explicitly
#: placed in the eligible or excluded set above.
RECOGNIZED_RESULTS: Final[frozenset[str]] = (
    REDISPATCH_ELIGIBLE_RESULTS | REDISPATCH_EXCLUDED_RESULTS
)


# ---------------------------------------------------------------------------
# Evidence identity — the deliberate dedup grain
# ---------------------------------------------------------------------------


def redispatch_evidence_hash(*, run_id: str, task: str, result: str) -> str:
    """The evidence hash for one parked task — the run's STABLE identity, never a
    timestamp.

    **The deliberate dedup-grain decision (#844):** the hash covers
    ``run_id + task + result``, so the proposal fingerprint identifies *this
    parked run of this task*. Three behaviors fall out by construction:

    1. The SAME parked run re-read every cycle maps to the SAME fingerprint →
       the store's active-dedup returns the existing proposal (one ask,
       ADR-039 §2.12.5).
    2. After the operator DECIDES (APPROVED/REJECTED — terminal), the same
       evidence re-read is found in the store's history and NEVER re-asked
       (:func:`stage_redispatch_proposals` skips it as already-decided;
       re-staging an identical parked run after a rejection would be exactly
       the wall-of-stale-asks §2.12.5 exists to prevent).
    3. A NEW parked run — including an approved redispatch itself parking
       again — mints a NEW fingerprint and a FRESH proposal. The store's
       "a recurrence after a decision is new work" is deliberately read as
       NEW EVIDENCE, never as the old evidence re-read.

    The alternative grain (repo+task, no run id — "one ask per task, ever")
    was considered and rejected: it cannot distinguish a re-read of decided
    evidence from a genuinely new park, so it either nags after a rejection or
    silences a real new failure.

    NUL-separated SHA-256 over the structured fields (the same injection-safe
    joining :func:`~shared.coordinator.proposal_store.proposal_fingerprint`
    uses — NUL cannot appear in any field, so boundaries are unambiguous)."""
    material = f"{run_id}\x00{task}\x00{result}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


# ---------------------------------------------------------------------------
# Cycle result records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StagedRedispatch:
    """One task whose redispatch proposal exists after this cycle (staged fresh,
    or deduped to an already-active proposal)."""

    task: str
    proposal_id: str
    fingerprint: str


@dataclass(frozen=True)
class SkippedRedispatch:
    """One task the cycle did NOT stage for, with the operator-legible reason."""

    task: str
    reason: str


@dataclass(frozen=True)
class RedispatchCycleResult:
    """What one redispatch-staging cycle did — the operator surface + tests read
    this. Every eligible outcome lands in exactly one of ``staged`` / ``deduped``
    / ``already_decided`` / ``refused`` / ``errors``; every ineligible outcome in
    ``ineligible``."""

    staged: tuple[StagedRedispatch, ...] = ()
    """Fresh proposals staged (DRAFT) this cycle — one per new parked evidence."""

    deduped: tuple[StagedRedispatch, ...] = ()
    """Evidence whose ACTIVE proposal already existed — no duplicate staged
    (the anti-firehose invariant, §2.12.5)."""

    already_decided: tuple[SkippedRedispatch, ...] = ()
    """Evidence the operator already decided (APPROVED/REJECTED) — never
    re-asked. Only NEW evidence (a new run) may stage a fresh proposal."""

    refused: tuple[SkippedRedispatch, ...] = ()
    """Eligible outcomes refused FAIL-CLOSED by the SG ruler / malformed cycle
    input — nothing reached the store."""

    ineligible: tuple[SkippedRedispatch, ...] = ()
    """Outcomes whose result is not a redispatch candidate (MERGED/BLOCKED/
    NOTHING/TIMEOUT/UNKNOWN — reasons in the module docstring)."""

    errors: tuple[SkippedRedispatch, ...] = ()
    """Store faults (fail-soft): recorded, cycle continued; the same evidence
    naturally retries next cycle because no proposal was written."""


# ---------------------------------------------------------------------------
# Payload composition (deterministic — content-bearing, encrypted by the store)
# ---------------------------------------------------------------------------


def build_redispatch_payload(
    *,
    outcome: TaskOutcome,
    run_id: str,
    repo_id: str,
    resolved_target: str,
    runs_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Compose the proposal payload from structured run facts — code, not model.

    Content-bearing (goal text, task text, evidence pointers), so the store
    encrypts it at rest (ADR-039 §2.13 item 2). ``repo_id`` is carried as the
    STRUCTURED field :func:`revalidate_for_execution` re-derives the target from
    at execution time (§2.12.4); ``target`` is the staging-time resolution,
    informational only — execution never trusts it without re-derivation.
    ``task``/``detail`` are untrusted run text (ADR-039 §2.7): they shape this
    content and nothing else."""
    if runs_dir is not None:
        evidence_ref = str(Path(runs_dir) / run_id / "SUMMARY.txt")
    else:
        evidence_ref = f"run:{run_id}"
    return {
        "goal": (
            f"Redispatch parked task {outcome.task!r} in workspace repo "
            f"{repo_id!r} — run {run_id} banked an honest shortfall "
            "(PARKED: valid run, work on its branch, not merged)."
        ),
        "run_id": run_id,
        "repo_id": repo_id,
        "target": resolved_target,
        "task": outcome.task,
        "result": outcome.result,
        "detail": outcome.detail,
        "evidence": [evidence_ref],
    }


# ---------------------------------------------------------------------------
# The staging cycle
# ---------------------------------------------------------------------------


def stage_redispatch_proposals(
    outcomes: Sequence[TaskOutcome],
    *,
    run_id: str,
    repo_id: str,
    projects_dir: str | Path,
    roots: GovernedCoreRoots,
    store: ProposalStore,
    runs_dir: str | Path | None = None,
    now: datetime | None = None,
) -> RedispatchCycleResult:
    """Stage ONE approval-gated redispatch proposal per NEW parked evidence.

    *outcomes* is a run's parsed ``SUMMARY.txt``
    (:func:`shared.fleet.dispatch.parse_summary`, e.g. via
    ``work_state.read_latest_run_summary``); *run_id* and *repo_id* are TRUSTED
    STRUCTURED fields from the run/dispatch record — never model output, never
    run-report text (the caller owns that provenance; this module enforces the
    target side of it). *now* is supplied by deterministic callers/tests; the
    store defaults to the real clock when omitted.

    The SG ruler runs ONCE per cycle (one run targets one repo): the target is
    re-derived from *repo_id* and checked at ``phase="STAGING"``; any refusal
    fail-closes EVERY eligible outcome in this cycle with the verdict's reason,
    and nothing reaches the store. Per-outcome store faults are fail-soft
    (recorded in ``errors``; the cycle proceeds)."""
    ineligible: list[SkippedRedispatch] = []
    eligible: list[TaskOutcome] = []
    for outcome in outcomes:
        if outcome.result in REDISPATCH_ELIGIBLE_RESULTS:
            eligible.append(outcome)
        else:
            ineligible.append(
                SkippedRedispatch(
                    task=outcome.task,
                    reason=f"result {outcome.result} is not a redispatch candidate",
                )
            )

    # ── Cycle-level structured-input validation + the SG ruler (fail-closed). ──
    refusal_reason: str | None = None
    resolved_target = ""
    if not isinstance(run_id, str) or not run_id.strip():
        refusal_reason = "run_id is missing/blank — malformed cycle input (fail-closed)"
    else:
        derived = derive_workspace_target(repo_id, projects_dir=projects_dir)
        if derived is None:
            refusal_reason = (
                f"target repo id {repo_id!r} is not a plain workspace component "
                "(SG ruler, fail-closed)"
            )
        else:
            verdict = check_target(
                derived, roots=roots, projects_dir=projects_dir, phase="STAGING"
            )
            if verdict.denied:
                refusal_reason = f"target refused by SG ruler at staging: {verdict.reason}"
            else:
                resolved_target = verdict.resolved_target

    if refusal_reason is not None:
        if eligible:
            logger.warning(
                "coord_redispatch: refusing %d eligible outcome(s) fail-closed: %s",
                len(eligible),
                refusal_reason,
            )
        return RedispatchCycleResult(
            refused=tuple(
                SkippedRedispatch(task=o.task, reason=refusal_reason) for o in eligible
            ),
            ineligible=tuple(ineligible),
        )

    staged: list[StagedRedispatch] = []
    deduped: list[StagedRedispatch] = []
    already_decided: list[SkippedRedispatch] = []
    errors: list[SkippedRedispatch] = []

    for outcome in eligible:
        evidence = redispatch_evidence_hash(
            run_id=run_id, task=outcome.task, result=outcome.result
        )
        fingerprint = proposal_fingerprint(
            proposal_class=REDISPATCH_PROPOSAL_CLASS,
            target=resolved_target,
            evidence_hash=evidence,
        )
        try:
            history = store.find_by_fingerprint(fingerprint)
            active = [p for p in history if p.status.is_active]
            if active:
                # The anti-firehose invariant: the ask already stands; no dup.
                deduped.append(
                    StagedRedispatch(
                        task=outcome.task,
                        proposal_id=active[0].id,
                        fingerprint=fingerprint,
                    )
                )
                continue
            if history:
                # Terminal-only history: the operator already decided on THIS
                # evidence. Re-asking about the same parked run is a nag, not
                # news — only a NEW run (new fingerprint) stages fresh.
                latest = history[-1]
                already_decided.append(
                    SkippedRedispatch(
                        task=outcome.task,
                        reason=(
                            f"already decided: {latest.status.value} "
                            f"(proposal {latest.id})"
                        ),
                    )
                )
                continue
            payload = build_redispatch_payload(
                outcome=outcome,
                run_id=run_id,
                repo_id=repo_id,
                resolved_target=resolved_target,
                runs_dir=runs_dir,
            )
            proposal = store.add_draft(
                lane=ProposalLane.WORKSPACE,
                proposal_class=REDISPATCH_PROPOSAL_CLASS,
                fingerprint=fingerprint,
                payload=payload,
                now=now,
            )
            staged.append(
                StagedRedispatch(
                    task=outcome.task,
                    proposal_id=proposal.id,
                    fingerprint=fingerprint,
                )
            )
            logger.info(
                "coord_redispatch: staged redispatch proposal %s for parked task %r "
                "(run %s)",
                proposal.id,
                outcome.task,
                run_id,
            )
        except Exception as exc:  # noqa: BLE001 — a store fault must not crash the cycle
            logger.warning(
                "coord_redispatch: store fault for task %r (fail-soft, retried next "
                "cycle): %s",
                outcome.task,
                exc,
            )
            errors.append(
                SkippedRedispatch(
                    task=outcome.task,
                    reason=f"store fault (fail-soft, retried next cycle): {exc}",
                )
            )

    return RedispatchCycleResult(
        staged=tuple(staged),
        deduped=tuple(deduped),
        already_decided=tuple(already_decided),
        refused=(),
        ineligible=tuple(ineligible),
        errors=tuple(errors),
    )


# ---------------------------------------------------------------------------
# The execution-time re-validation seam (ADR-039 §2.12 item 4 — TOCTOU closure)
# ---------------------------------------------------------------------------


def revalidate_for_execution(
    proposal: Proposal,
    *,
    roots: GovernedCoreRoots,
    projects_dir: str | Path,
) -> TargetVerdict:
    """Re-run the SG ruler over an approved proposal at EXECUTION time.

    Approval is not freshness (ADR-039 §2.12.4): the world may have changed
    between staging and approval (repo moved, replaced by a junction into the
    governed core). The target is RE-DERIVED from the proposal's own structured
    ``repo_id`` payload field — written by :func:`build_redispatch_payload` at
    staging, at rest inside the AAD-bound encrypted payload of the sole-writer
    store — never from any free text, and the ruler re-resolves against the
    CURRENT filesystem. The execution-time verdict is authoritative.

    THE SEAM, not the hook: nothing calls this today. The future approve→execute
    wiring (C3/C5) MUST call it immediately before dispatch and treat a DENY as
    refuse-with-comment — a stale-invalid proposal is never "best-effort
    executed"."""
    payload: Mapping[str, Any] = proposal.payload
    repo_id = payload.get("repo_id")
    if not isinstance(repo_id, str) or not repo_id.strip():
        return TargetVerdict(
            BoundaryDecision.DENY,
            "proposal payload carries no structured repo_id — cannot re-derive the "
            "execution target (fail-closed)",
            phase="EXECUTION",
        )
    derived = derive_workspace_target(repo_id, projects_dir=projects_dir)
    if derived is None:
        return TargetVerdict(
            BoundaryDecision.DENY,
            f"target repo id {repo_id!r} is not a plain workspace component "
            "(SG ruler, fail-closed)",
            phase="EXECUTION",
        )
    return check_target(
        derived, roots=roots, projects_dir=projects_dir, phase="EXECUTION"
    )
