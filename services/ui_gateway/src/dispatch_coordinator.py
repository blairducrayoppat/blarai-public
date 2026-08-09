"""Gateway-side coordinator for ``/dispatch`` — the headless-coding dispatch surface.

ONE flow, always confirmed (the command-surface ruling). Every ``/dispatch`` goes
through the Acceptance Layer: the 14B turns the goal into a task plan + plain-English
acceptance criteria (PLAN), the operator approves the criteria (the MANDATORY,
non-skippable confirm), and only then does the work fire (EXECUTE). There is NO
unconfirmed fast-path — the increment-1 "enqueue + run immediately" entry was removed.
"Skip the model swap when the 30B is already loaded" is an INTERNAL branch of EXECUTE
(still confirmed), never a separate surface.

Commands:
  ``/dispatch <repo> | <goal>``   PLAN: decompose + acceptance criteria, then show the
                                  criteria and WAIT (no work fires yet).
  ``/dispatch new <name> | <goal>``  CREATE a new git project under the projects dir
                                  (git init + first commit) THEN PLAN it — the one-motion
                                  "start a new project" flow (#712).
  ``/dispatch <n>``               answer a CLARIFYING question (increment 4) — when the 14B
                                  flagged a genuinely ambiguous platform fork, the SYSTEM asks
                                  ONE curated question BEFORE the preview; the operator replies
                                  with the option number (also ``/dispatch use <n>``). A clear
                                  surface never asks — the flow is byte-identical to today.
  ``/dispatch approve``           EXECUTE the pending plan (the only path that fires work).
  ``/dispatch revise <feedback>`` (#820) refine the PENDING plan from free-text feedback — the
                                  14B revises the EXISTING breakdown (tasks added/removed/
                                  reordered/re-scoped, every untouched task preserved byte-for-
                                  byte), re-rendered with a CHANGED-vs-KEPT delta. Bounded (3
                                  revisions); an incoherent revision re-renders the ORIGINAL
                                  card untouched. Operator-only (a battery run never revises).
  ``/dispatch reject``            discard the PENDING plan or pending question (nothing fires).
  ``/dispatch stop``              abort an APPROVED, EXECUTING run — trips the driver's cancel
                                  sentinel so the coder halts and the 14B is restored cleanly
                                  (partial work parks on its branch). Distinct from reject.
  ``/dispatch status [<RunId>]``  the honest per-criterion report (or the raw summary if a
                                  run predates the acceptance layer); latest if no RunId.

The 14B PLAN call (``plan_fn``) and the swap/EXECUTE call (``execute_fn``) are injected —
the real wiring is an AO IPC round-trip and is the deferred on-hardware go-live step; with
them unset (the shipped dormant posture) the coordinator says so and fires nothing. Gated
by ``[fleet_dispatch].enabled`` (default False): disabled returns a clear notice and never
calls plan/execute.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable, Final

from shared.fleet import acceptance as acc
from shared.fleet import clarify as _clarify
from shared.fleet import dispatch as fleet
from shared.fleet import revise as _revise
from shared.fleet.acceptance import AcceptanceSpec, PlanResult
from shared.ttl_dict import TtlDict

from services.ui_gateway.src import dispatch_state_store as _state

logger = logging.getLogger(__name__)

#: Vocabulary that signals the operator is trying to change the plan's CRITERIA
#: or SCOPE — which ``/dispatch revise`` structurally CANNOT touch (#1055). Revise
#: edits the TASK list only; acceptance criteria are set by the goal and are
#: immutable across a revision. When a no-op revise carried this vocabulary, the
#: honest answer is "criteria are set by the goal — reject + re-dispatch to change
#: scope", NOT "try describing the change differently" (which loops forever,
#: because no rephrasing lets revise edit a criterion).
#:
#: DELIBERATELY NARROW, and the narrowing is the point (pre-merge review F1/F2):
#: revise DOES add/remove/reorder/re-scope TASKS, so "feature", "features",
#: "check", "checks" and bare "acceptance" are TASK words — matching them told an
#: operator dropping a task to reject the whole plan, which is false. The only
#: terms kept are ones that rarely mean a task: ``criteria``/``criterion``,
#: ``requirement(s)``, ``scope``, and the ``drop/remove … the goal`` construction
#: (the LA's live phrasing, "drop the goal-setting …", fires via ``goal``). A MISS
#: just yields the generic message (harmless); a false positive misdiagnoses a
#: real task edit (the dangerous direction here), so this errs toward missing.
#:
#: ROUTER ROLE (criteria-first fix): a match now routes to the criteria path
#: BEFORE the task editor, not merely into its fall-back — so a false positive
#: no longer just re-words a failure message, it pays a criteria round trip and,
#: if the criteria model invents usable ops, lands a criteria revision where a
#: task edit was meant. The narrowness above is what keeps that bounded; widen
#: this vocabulary only with a live-dispatch probe of the task-word overlap.
_CRITERIA_SCOPE_SIGNALS = re.compile(
    r"\b(?:criteri(?:a|on)|requirements?|scope|"
    r"(?:drop|remove|delete|cut|get\s+rid\s+of)\s+(?:the\s+)?goal)\b",
    re.IGNORECASE,
)


def _feedback_targets_criteria(feedback: str) -> bool:
    """True when revise feedback reads as a criteria/scope change, not a task edit."""
    return bool(_CRITERIA_SCOPE_SIGNALS.search(feedback or ""))


#: #1116 — THE STANDING RULE FOR THIS SURFACE: no dispatch reply may discard what the
#: operator typed. The corridor is conversational, so a reply can always arrive in a
#: state that cannot consume it (the question was rejected, the idle sweep reaped it,
#: a corrupt parked row was dropped fail-closed). Before this, every such path returned
#: a usage nag and the words were gone — the WinUI input box has already cleared by
#: then, so the operator's only copy was destroyed by the error message.
#:
#: This is the second instance of that failure class in one day: the New Project dialog
#: discards both typed fields on a validation failure, which cost the operator a
#: ~2,200-character project description on 2026-07-27 (recovered only from a full-memory
#: dump of the live process). Typed text is the one thing the system cannot regenerate.
def _keep_operator_text(message: str, text: str) -> str:
    """*message*, followed by *text* echoed back verbatim so it is never lost.

    Returns *message* unchanged for empty/whitespace text — there is nothing to keep,
    and an empty quote block would be noise on the paths that legitimately have none.
    """
    kept = (text or "").strip()
    if not kept:
        return message
    return (
        f"{message}\n\n"
        "Nothing you wrote is lost — here it is exactly as you typed it, ready to copy:\n\n"
        f"```\n{kept}\n```"
    )


#: #1031 S2 — the quick-path discoverability hint's size threshold, in whitespace words.
#: A named judgment constant: below it the hint is noise, above it the fuller interview
#: plausibly pays for itself. The hint is one line and never a mode entry.
_INTAKE_HINT_MIN_WORDS = 40


#: The honest no-state message. It names the two things that ACTUALLY end a pending
#: question (cancelled, or reaped by the idle sweep) instead of the pre-#1116 line,
#: which read as though the operator had invented the question — the opposite of the
#: truth when the transcript above is still displaying it.
_NO_QUESTION_WAITING: Final[str] = (
    "I don't have that question open any more — it was cancelled, or it timed out "
    "while waiting for an answer. Start again with `/dispatch <project> | <what to "
    "build>` and I'll ask it fresh."
)


def _no_question_waiting(text: str = "") -> str:
    """The no-pending-question reply, keeping whatever the operator typed."""
    return _keep_operator_text(_NO_QUESTION_WAITING, text)


#: #1161: the honest MOBILE refusal for an empty/new project. Building phone apps is not
#: a fleet capability; before this, a phone ask on an empty repo was silently rebuilt as
#: desktop-from-nothing — the weakest stack, wearing the operator's words. The refusal
#: names the real limit AND the workable alternative (a phone's browser runs a web page).
_MOBILE_REFUSAL: Final[str] = (
    "I have to be straight with you: building PHONE apps isn't something the coder fleet "
    "can do yet, so I'm not starting this one — it would quietly turn into a desktop "
    "build, which isn't what you asked for. A web page works fine in a phone's browser, "
    "though: say \"web page\" in the goal or your answer and I'll build that instead."
)


def _verb_taken_as_answer_notice(verb: str) -> str:
    """#1160 d2: the one honest notice line when a reserved-verb reply was consumed as
    ANSWERS to the pending requirements questions.

    The consumption itself is the accidentally-good behavior the ticket preserves (#1116:
    typed text is never discarded) — but silently briefing a `/dispatch revise …` line as
    requirements is how the morning run built to feedback meant for a plan that did not
    exist. One line, leading the very next reply, says what actually happened; where the
    verb also had a REAL job that did NOT run (forget / new), the notice says that too,
    because "taken as answers" alone would hide that nothing was forgotten/created.
    Unknown verbs return ``""`` (no notice — defensive, never a wrong claim)."""
    if verb == "revise":
        return (
            "Heads-up: there was no plan yet to revise — I've taken what you wrote as "
            "your answers to the questions."
        )
    if verb == "approve":
        return (
            "Heads-up: there was no plan to approve yet — I've taken what you wrote as "
            "your answers to the questions."
        )
    if verb == "forget":
        return (
            "Heads-up: I've taken that as your answers to the questions — nothing was "
            "forgotten. To clear a project's memory, finish or cancel this dispatch "
            "first, then `/dispatch forget <project>`."
        )
    if verb == "new":
        return (
            "Heads-up: I've taken that as your answers to the questions — no new "
            "project was created. To start a different project, `/dispatch reject` "
            "first, then `/dispatch new <name> | <goal>`."
        )
    return ""


def _no_plan_yet_lead(verb: str) -> str:
    """#1160 d2 (review F5): the honest state-correction lead when a reserved verb
    arrives at the question stage with NO text at all (bare ``/dispatch approve`` /
    ``revise`` / ``forget`` / ``new``). Nothing is consumed on that path — but the
    generic "I didn't catch an answer" alone leaves the operator's misbelief (that a
    plan exists to act on) standing, which is the exact #1160 class. One lead line,
    then the unchanged re-ask. ``""`` for a plain empty answer (no verb — the generic
    nag alone remains byte-identical)."""
    if verb == "approve":
        return "There's no plan to approve yet — the questions above come first.\n\n"
    if verb == "revise":
        return "There's no plan to revise yet — the questions above come first.\n\n"
    if verb == "forget":
        return (
            "Nothing was forgotten — to clear a project's memory, finish or cancel "
            "this dispatch first. The questions above come first.\n\n"
        )
    if verb == "new":
        return (
            "No new project was created — finish or cancel this dispatch first. "
            "The questions above come first.\n\n"
        )
    return ""


def _playback_invitation(revision_count: int, coverage_blocked: str = "") -> str:
    """#1165 M4: the intake-mode plan card's closing playback turn — the interview
    template's two questions, inviting a plain-words correction at the approval turn.

    Rendered ONLY on an intake-mode card with the playback gate on (both checked by the
    caller); the promise it makes is kept by ``_plan``'s pipe-less free-text re-route
    into the existing bounded revise. Every action this text offers is derived from the
    SAME state that gates the action (fix-round review F1 — a card's promise must
    survive every state it renders in):

    * at the shared #820 revision cap the fixing promise would be false (revise
      refuses), so the cap variants keep the questions and name the true exits;
    * while ``coverage_blocked`` is set, approve is the one verb the marker refuses
      (S3-F), so no blocked variant offers it;
    * on the ORPHAN-ONLY block (classified from the carried marker itself,
      :func:`shared.fleet.acceptance.coverage_blocked_is_orphan_only`) a plan revision
      cannot clear the gap, so the fixing promise is dropped — the blocked footer
      directly above owns the reject route;
    * at a BLOCKED cap both refusals hold: reject is the only exit, mirroring the
      revise cap refusal for blocked plans."""
    questions = (
        "Did I get anything wrong? Is there anything I should have asked you about "
        "that I didn't?"
    )
    at_cap = revision_count >= _revise.DEFAULT_MAX_REVISIONS
    if coverage_blocked and at_cap:
        return (
            f"{questions} This plan has used its "
            f"{_revise.DEFAULT_MAX_REVISIONS} revisions and the coverage gap above "
            "is still open — reply /dispatch reject and start a new dispatch with "
            "a tighter goal."
        )
    if coverage_blocked and acc.coverage_blocked_is_orphan_only(coverage_blocked):
        return questions
    if coverage_blocked:
        return f"{questions} Tell me in plain words and I'll fix the plan."
    if at_cap:
        return (
            f"{questions} This plan has used its "
            f"{_revise.DEFAULT_MAX_REVISIONS} revisions, so I can't change it "
            "further — reply /dispatch approve to build it as shown, or "
            "/dispatch reject to start fresh."
        )
    return (
        f"{questions} Tell me in plain words and I'll fix the plan — or "
        "/dispatch approve when it reads right."
    )


def _consumed_verb(command: "DispatchCommand") -> str:
    """The reserved verb a requirements-state reply arrived wearing, or ``""`` (a plain
    answer). Enumerated from the REAL parser's verb set (#1160): the kinds whose text the
    requirements state consumes as answers are ``revise`` (feedback), ``forget`` (repo),
    ``create`` (``new …``, repo/goal) and ``approve`` (text-less — the empty-answer path
    carries its own honest line); a ``run`` whose first word is approve-shaped
    ("approved …" parses as a plain goal) is the approve-adjacent form. ``choose`` (a
    bare number / ``use N``) is DELIBERATELY excluded: a lone digit is a perfectly
    plausible real answer ("how many habits?" — "5"), and a wrong heads-up would be its
    own small lie. ``status``/``stop``/``reject``/``decide`` route as verbs and never
    reach the consumer; ``answer`` and a plain ``run`` are the DESIGNED answer shapes."""
    if command.kind in ("revise", "forget", "approve"):
        return command.kind
    if command.kind == "create":
        return "new"
    if command.kind == "run":
        first = (command.goal or "").split(None, 1)[0].lower().strip(".,!?:;") if (
            command.goal or "").strip() else ""
        if first in ("approve", "approved"):
            return "approve"
    return ""


_PREFIX = "/dispatch"

#: ``plan_fn(repo, goal) -> PlanResult`` — runs the 14B PLAN (decompose + criteria +
#: ruler) AO-side. Injected; the real wiring is an AO IPC round-trip (deferred go-live).
PlanFn = Callable[[str, str], Awaitable[PlanResult]]
#: ``execute_fn(session_id, run_id, repo, tasks, spec) -> DispatchResult`` — fires EXECUTE
#: (enqueue + swap-or-direct-run + step-aside). Injected; real wiring deferred to go-live.
ExecuteFn = Callable[[str, str, str, list, AcceptanceSpec], Awaitable[fleet.DispatchResult]]


@dataclass(frozen=True)
class DispatchCommand:
    kind: str  # run|create|approve|reject|status|stop|choose|answer|decide|revise|forget
    repo: str = ""
    goal: str = ""
    run_id: str = ""
    choice: str = ""  # the operator's answer to a clarifying question (a 1-based option number)
    answer: str = ""  # #819: the operator's free-text answer to the requirements questions
    feedback: str = ""  # #820: the operator's free-text plan-revision feedback
    #: #1031 S2: the operator explicitly asked for the FULLER intake interview (the
    #: `advanced` token). Set only by the parser's token gate; never persisted.
    advanced: bool = False


@dataclass(frozen=True)
class PendingDispatch:
    """The session's single pending (planned, not-yet-approved) dispatch."""

    run_id: str
    repo: str
    goal: str
    tasks: list = field(default_factory=list)  # compiled {repo,task,prompt}
    spec: AcceptanceSpec = field(default_factory=lambda: AcceptanceSpec(goal=""))
    ecosystem: str = "unknown"
    #: #888: the scaffold's behaviour-GATED ecosystem (``node``/``python``, else ``""``) when the
    #: run will scaffold a fresh repo — drives the plan card's honest coverage disclosure across
    #: re-renders (revise / revise-failed). Empty preserves the pre-#888 warning byte-for-byte.
    scaffold_ecosystem: str = ""
    submitted_at: str = ""
    #: #820: how many times this pending plan has been REVISED by operator feedback. Each
    #: successful revision REPLACES this slot (the old plan is tombstoned) with the count
    #: incremented; at :data:`shared.fleet.revise.DEFAULT_MAX_REVISIONS` the ``revise`` verb is
    #: refused honestly (accept or reject only). Carried through revisions with a stable run_id.
    revision_count: int = 0
    #: #1069 S3-F: the intake coverage-gate blocking marker, carried from
    #: :attr:`PlanResult.coverage_blocked`. Non-empty ⇒ ``/dispatch approve`` is refused
    #: with the gap named, every re-render shows the blocked card, and ``_revise``
    #: RE-EVALUATES it after a successful revision (the operator's unblock path).
    #: ``""`` == approvable; byte-identical pre-S3F behaviour.
    coverage_blocked: str = ""
    #: #1161 d2: this plan will scaffold a FRESH repo (``repo_will_scaffold`` at plan
    #: time). Carried so every re-render (revise / revise-failed / criteria paths) keeps
    #: the card's build-risk disclosure without re-probing the disk. False == the
    #: pre-#1161 card byte-for-byte (and what every pre-#1161 parked row restores to).
    will_scaffold: bool = False
    #: #1165 M4: this plan came through the FULLER intake interview — the approval-turn
    #: carrier the playback needs. :attr:`PendingRequirements.intake` dies with the
    #: question turn, and deriving the bit from the spec's clarification tags would
    #: misfire: banked tagged answers replay onto QUICK dispatches of remembered
    #: projects (the S2 F6 pin). Drives the card's closing playback invitation and the
    #: pipe-less free-text re-route, both additionally gated on the playback flag.
    #: False == the pre-M4 card and corridor byte-for-byte (and what every pre-M4
    #: parked row restores to).
    intake: bool = False


@dataclass(frozen=True)
class PendingClarification:
    """The session's single pending CLARIFYING question (increment 4, #677).

    A bounded interactive sub-state that sits BEFORE the normal PLAN preview: when the 14B
    flagged a genuinely ambiguous platform fork, the coordinator asks ONE curated question
    (the system's, never the model's) and holds the rest of the planned dispatch here until
    the operator answers. On a valid answer the chosen surface is threaded into the plan and
    the flow proceeds to the SAME approval preview it would have shown directly for a clear
    surface; a malformed / out-of-range answer falls back to proceeding with the un-refined
    plan (never a hang/loop). At most ONE clarifying turn per dispatch — once answered (or
    fallen back), this slot clears and a PendingDispatch (approval) takes over.

    It carries everything needed to finalize the plan after the answer WITHOUT re-running the
    14B: the compiled ``tasks`` (already carry the test block), the validated ``spec``, the
    ``question`` shown, and the ``ecosystem`` for the preview caveat.
    """

    run_id: str
    repo: str
    goal: str
    tasks: list = field(default_factory=list)  # compiled {repo,task,prompt}
    spec: AcceptanceSpec = field(default_factory=lambda: AcceptanceSpec(goal=""))
    question: dict = field(default_factory=dict)  # {question, options:[{label, surface}]}
    ecosystem: str = "unknown"
    #: #888: the scaffold's behaviour-GATED ecosystem, carried so the post-answer preview shows
    #: the honest coverage disclosure (see :class:`PendingDispatch`). Empty == today's warning.
    scaffold_ecosystem: str = ""
    fell_back: bool = False
    submitted_at: str = ""
    #: #1069 S3-F: the coverage-gate blocking marker, carried through the platform-question
    #: hold so the block survives the Inc-4 sub-state (see :class:`PendingDispatch`).
    coverage_blocked: str = ""
    #: #1161 d2: the fresh-scaffold marker, carried through the platform-question hold so
    #: the post-answer preview (a desktop pick from nothing is the measured case) renders
    #: the build-risk disclosure (see :class:`PendingDispatch`).
    will_scaffold: bool = False
    #: #1165 M4: the intake-mode bit, carried through the platform-question hold so the
    #: Inc-4 sub-state cannot launder it away — ``_choose`` re-stamps it onto the
    #: :class:`PendingDispatch` it finalizes (see that class's field for what it drives).
    intake: bool = False


@dataclass(frozen=True)
class PendingRequirements:
    """The session's single pending REQUIREMENTS-CLARIFICATION question set (#819).

    A bounded interactive sub-state that sits BEFORE the PLAN preview (and before the Inc-4
    platform question): when the 14B judged the raw goal underspecified, it proposed a FEW
    targeted questions and the coordinator holds the dispatch here until the operator answers
    in their own words (or replies "just decide for me", or rejects). On an answer the goal is
    re-planned with the answers threaded through the requirements, and the flow proceeds to the
    SAME approval preview it would have shown a fully-specified goal. At most ONE requirements
    turn per dispatch — answering (or deciding) clears this slot and a PendingDispatch or a
    PendingClarification takes over.

    Carries ONLY what is needed to re-plan after the answer: the ``run_id`` (minted once,
    carried through), the ``repo``, the raw ``goal``, and the ``questions`` shown (a list of
    ``{axis, question}`` dicts). No spec/tasks yet — those come from the RE-PLAN with the
    answers threaded in (the first pass returned questions, not a plan)."""

    run_id: str
    repo: str
    goal: str
    questions: list = field(default_factory=list)  # [{axis, question}]
    submitted_at: str = ""
    #: #1031 S2: this question set came from the FULLER intake interview. Load-bearing at
    #: the answer/decide turn: a parked intake question must reconstruct with the
    #: eight-axis vocabulary, or a stored `content` question would coerce to `feature`
    #: and self-answer with the wrong default (the design's §1 item 3 defect).
    intake: bool = False


# ── parked-state serialization (#1116) ────────────────────────────────────
# The three pending slots cross a born-encrypted store as plain JSON dicts so a
# half-finished dispatch survives a restart (see :mod:`dispatch_state_store` for
# WHY). ``AcceptanceSpec.to_dict``/``from_dict`` is the SAME round-trip the spec
# already makes across the gateway IPC and into the acceptance record — this adds
# no new serialization contract, it reuses the proven one.
#
# from_payload is TOTAL over well-formed input and RAISES on anything else: the
# store's fail-closed read turns that raise into "drop the row, report it". A
# partially-reconstructed plan must never reach an operator's /dispatch approve.


def _requirements_to_payload(p: PendingRequirements) -> dict:
    payload = {
        "run_id": p.run_id, "repo": p.repo, "goal": p.goal,
        "questions": [dict(q) for q in p.questions], "submitted_at": p.submitted_at,
    }
    # #1031 S2 (design review F2): the key is emitted ONLY when True — a flag-off
    # quick-path park stays byte-identical at the store seam, the same discipline the
    # record's axes carry keeps.
    if p.intake:
        payload["intake"] = True
    return payload


def _requirements_from_payload(d: dict) -> PendingRequirements:
    return PendingRequirements(
        run_id=str(d["run_id"]), repo=str(d["repo"]), goal=str(d["goal"]),
        questions=[dict(q) for q in d.get("questions", [])],
        submitted_at=str(d.get("submitted_at", "")),
        # #1031 S2 additive: every pre-S2 parked row restores as a quick-path question
        # set, which is what it is.
        intake=bool(d.get("intake", False)),
    )


def _clarifying_to_payload(p: PendingClarification) -> dict:
    payload = {
        "run_id": p.run_id, "repo": p.repo, "goal": p.goal,
        "tasks": [dict(t) for t in p.tasks], "spec": p.spec.to_dict(),
        "question": dict(p.question), "ecosystem": p.ecosystem,
        "scaffold_ecosystem": p.scaffold_ecosystem, "fell_back": bool(p.fell_back),
        "submitted_at": p.submitted_at,
        "coverage_blocked": p.coverage_blocked,
        "will_scaffold": bool(p.will_scaffold),
    }
    # #1165 M4: emitted ONLY when True — a quick-path park stays byte-identical at the
    # store seam, the discipline the requirements codec above established (S2 review F2).
    if p.intake:
        payload["intake"] = True
    return payload


def _clarifying_from_payload(d: dict) -> PendingClarification:
    return PendingClarification(
        run_id=str(d["run_id"]), repo=str(d["repo"]), goal=str(d["goal"]),
        tasks=[dict(t) for t in d.get("tasks", [])],
        spec=AcceptanceSpec.from_dict(d.get("spec", {})),
        question=dict(d.get("question", {})),
        ecosystem=str(d.get("ecosystem", "unknown")),
        scaffold_ecosystem=str(d.get("scaffold_ecosystem", "")),
        fell_back=bool(d.get("fell_back", False)),
        submitted_at=str(d.get("submitted_at", "")),
        # #1069 S3-F additive: a pre-S3F row restores to "" (approvable), same tolerant
        # shape as scaffold_ecosystem above.
        coverage_blocked=str(d.get("coverage_blocked", "")),
        # #1161 additive: a pre-#1161 row restores to False (no build-risk line — what
        # its card showed when parked).
        will_scaffold=bool(d.get("will_scaffold", False)),
        # #1165 M4 additive: a pre-M4 row restores as a quick-path hold, which is what
        # its card claimed when parked.
        intake=bool(d.get("intake", False)),
    )


def _pending_to_payload(p: PendingDispatch) -> dict:
    payload = {
        "run_id": p.run_id, "repo": p.repo, "goal": p.goal,
        "tasks": [dict(t) for t in p.tasks], "spec": p.spec.to_dict(),
        "ecosystem": p.ecosystem, "scaffold_ecosystem": p.scaffold_ecosystem,
        "submitted_at": p.submitted_at, "revision_count": int(p.revision_count),
        "coverage_blocked": p.coverage_blocked,
        "will_scaffold": bool(p.will_scaffold),
    }
    # #1165 M4: same conditional-emit discipline as the clarifying codec above.
    if p.intake:
        payload["intake"] = True
    return payload


def _pending_from_payload(d: dict) -> PendingDispatch:
    return PendingDispatch(
        run_id=str(d["run_id"]), repo=str(d["repo"]), goal=str(d["goal"]),
        tasks=[dict(t) for t in d.get("tasks", [])],
        spec=AcceptanceSpec.from_dict(d.get("spec", {})),
        ecosystem=str(d.get("ecosystem", "unknown")),
        scaffold_ecosystem=str(d.get("scaffold_ecosystem", "")),
        submitted_at=str(d.get("submitted_at", "")),
        revision_count=int(d.get("revision_count", 0)),
        # #1069 S3-F additive: a pre-S3F row restores to "" (approvable). A BLOCKED plan
        # parked before a restart comes back still blocked — the marker is state, not a
        # transient banner.
        coverage_blocked=str(d.get("coverage_blocked", "")),
        # #1161 additive: a pre-#1161 row restores to False (see the clarifying codec).
        will_scaffold=bool(d.get("will_scaffold", False)),
        # #1165 M4 additive: a pre-M4 row restores to False (see the clarifying codec).
        intake=bool(d.get("intake", False)),
    )


def _merge_clarifications(remembered: list, fresh: "list | tuple") -> list[dict]:
    """Combine a project's REMEMBERED answers with the ones just given (#1120).

    A fresh answer SUPERSEDES a remembered one for the same question — the operator's most
    recent word wins, always. Everything that survives from memory is tagged
    ``remembered=True`` so the plan card can show it under its own heading: an answer given
    three dispatches ago must not masquerade as something said in this turn, or the operator
    cannot tell what BlarAI is assuming on their behalf.

    Order is remembered-first then fresh, so the card reads chronologically. Pure; never
    mutates its inputs.
    """
    fresh_list = [dict(c) for c in fresh]
    fresh_questions = {str(c.get("question", "")).strip().lower() for c in fresh_list}
    out: list[dict] = []
    for c in remembered:
        question = str(c.get("question", "")).strip()
        if question.lower() in fresh_questions:
            continue  # superseded by what they just said
        entry = dict(c)
        entry["remembered"] = True
        out.append(entry)
    for c in fresh_list:
        entry = dict(c)
        entry["remembered"] = False
        out.append(entry)
    return out


def _riding_job_oracle(tasks: list) -> tuple[str, str]:
    """READ (never pop) the job exam riding the task dicts: ``(rel_path, code)`` or
    ``("", "")``. The #1069 S3-F post-revision re-evaluation needs the exam the plan
    actually carries; the blobs stay on the tasks — only the swap driver pops them, at
    approve time (:func:`shared.fleet.acceptance.extract_job_oracle`)."""
    for t in tasks:
        if not isinstance(t, dict):
            continue
        code = str(t.get(acc.JOB_ORACLE_CODE_KEY, "") or "")
        path = str(t.get(acc.JOB_ORACLE_PATH_KEY, "") or "")
        if code and path:
            return (path, code)
    return ("", "")


#: slot name -> (to_payload, from_payload). The single place the three slots are
#: mapped to their wire form; the coordinator's park/restore both read it, so a new
#: slot cannot be persisted without also being restorable.
_SLOT_CODECS: dict = {
    _state.SLOT_REQUIREMENTS: (_requirements_to_payload, _requirements_from_payload),
    _state.SLOT_CLARIFYING: (_clarifying_to_payload, _clarifying_from_payload),
    _state.SLOT_PENDING: (_pending_to_payload, _pending_from_payload),
}


def parse_dispatch_command(
    text: str, *, intake_token: bool = False
) -> DispatchCommand | None:
    """Parse a ``/dispatch …`` line, or return ``None`` for a normal prompt.

    Increment 4: a bare-number line (``/dispatch 2``) or ``/dispatch use 2`` / ``choose 2`` is
    parsed as a ``choose`` command (the answer to a clarifying question). A bare integer is
    unambiguous — it is never a real repo|goal — so it is safe to special-case; it is only
    ACTED ON when a clarification is actually pending for the session (handled in
    :meth:`DispatchCoordinator.handle_command`), otherwise it reports there's nothing to answer.
    """
    s = text.strip()
    # #1126: ANY whitespace after the verb, not just a space. The operator pasted a
    # numbered multi-line answer as "/dispatch\n1. In a web browser..." — the most
    # ordinary way to format one — and `startswith("/dispatch ")` was False, so the
    # parser returned None and the whole message went to the ORDINARY CHAT PATH.
    # No error, no usage line: the assistant burbled about /imagine while a
    # requirements question sat waiting for exactly that text. His answer survived
    # only because the chat path persists turns; #1116's keep-the-text guarantee
    # never applied, because the handler that implements it was never called.
    if s.lower() != _PREFIX and not (
        s.lower().startswith(_PREFIX) and len(s) > len(_PREFIX) and s[len(_PREFIX)].isspace()
    ):
        return None
    rest = s[len(_PREFIX):].strip()
    # #1031 S2 — the `advanced` mode token, recognised ONLY when *intake_token* is True
    # (False — every pre-S2 call site — is today's parse, byte for byte). The token is
    # stripped and the remainder re-parsed; the `advanced` flag then attaches ONLY when
    # that remainder parses to the PIPED forms — `run` with a NON-EMPTY repo, or `create`
    # with a NON-EMPTY goal (`new <name> | <goal>`). For ANY other remainder the ORIGINAL
    # rest is parsed exactly as today, nothing stripped. The pipe-less carve-outs are
    # load-bearing (design review F1 + code review F2): a pipe-less remainder parses as
    # run-with-empty-repo — and `new <text>` as create-with-empty-goal — and BOTH are
    # shapes a pending requirements ANSWER can arrive in ("advanced look…",
    # "advanced new look…"); an answer must reach the corridor verbatim, never with its
    # head eaten (the #1116/#1126 eats-operator-text class). The one true ambiguity is a
    # repo literally NAMED "advanced" used in the pipe-less run form; the natural piped
    # form (`/dispatch advanced | <goal>`) still parses to repo="advanced" unchanged
    # (the remainder "| <goal>" attaches nothing), so the trade-off is the same
    # one-ambiguous-case class as "new"/"revise"/"forget" below, and milder.
    if intake_token:
        low_rest = rest.lower()
        if low_rest.startswith("advanced") and len(rest) > 8 and rest[8].isspace():
            remainder = rest[8:].strip()
            inner = parse_dispatch_command(_PREFIX + " " + remainder)
            if inner is not None and (
                (inner.kind == "create" and inner.goal)
                or (inner.kind == "run" and inner.repo)
            ):
                return replace(inner, advanced=True)
    low = rest.lower()
    if low == "approve" or low.startswith("approve "):
        return DispatchCommand(kind="approve")
    if low == "reject" or low.startswith("reject "):
        return DispatchCommand(kind="reject")
    if low == "stop" or low.startswith("stop "):
        return DispatchCommand(kind="stop")
    if low == "status" or low.startswith("status "):
        return DispatchCommand(kind="status", run_id=rest[len("status"):].strip())
    # Create a NEW project: "new <name> | <goal>" — create the git repo, then PLAN.
    # Checked before the |-split because the create form contains a pipe. A repo
    # literally named "new" is the one ambiguous case (rare — use a path or another
    # name); "newsapp" etc. fall through to the normal run path below.
    if low == "new" or (
        low.startswith("new") and len(rest) > 3 and rest[3] in (" ", "|")
    ):
        after = rest[3:].strip()
        if "|" in after:
            nm, gl = after.split("|", 1)
            return DispatchCommand(kind="create", repo=nm.strip(), goal=gl.strip())
        return DispatchCommand(kind="create", repo=after.strip(), goal="")
    # #820 plan-revision feedback: "revise <free text>" refines a PENDING plan card. Parsed as a
    # distinct verb (only ACTED ON when a plan awaits approval — handle_command); a bare
    # "/dispatch revise ..." in any other state reports there's nothing to revise. Checked before
    # the |-split / run fall-through so the whole feedback remainder is captured verbatim. A repo
    # literally named "revise" is the one ambiguous case (rare — same tradeoff as "new").
    if low == "revise" or low.startswith("revise "):
        return DispatchCommand(kind="revise", feedback=rest[len("revise"):].strip())
    # #1120 "forget <project>": clear what the operator has told us about a project. Checked
    # before the |-split / run fall-through so the remainder is the repo name verbatim. A repo
    # literally named "forget" is the one ambiguous case (rare — same tradeoff as "new").
    if low == "forget" or low.startswith("forget "):
        return DispatchCommand(kind="forget", repo=rest[len("forget"):].strip())
    # #819 requirements-clarification answer forms. "just decide for me" (and short variants)
    # is the escape hatch -> kind="decide"; an explicit "answer <text>" captures the whole
    # free-text remainder. Both are only ACTED ON when a requirements question is pending
    # (handled in handle_command); otherwise they report there's nothing to answer. The
    # decide-phrase check runs BEFORE "answer"/run so "decide" is never mistaken for a goal.
    if _clarify.is_decide_for_me(rest):
        return DispatchCommand(kind="decide")
    if low == "answer" or low.startswith("answer "):
        return DispatchCommand(kind="answer", answer=rest[len("answer"):].strip())
    # Clarifying-answer forms: "use 2" / "choose 2" / a bare "2".
    if low.startswith("use ") or low.startswith("choose "):
        return DispatchCommand(kind="choose", choice=rest.split(None, 1)[1].strip())
    if rest.isdigit():
        return DispatchCommand(kind="choose", choice=rest)
    if "|" in rest:
        repo, goal = rest.split("|", 1)
        return DispatchCommand(kind="run", repo=repo.strip(), goal=goal.strip())
    return DispatchCommand(kind="run", repo="", goal=rest.strip())


class DispatchCoordinator:
    """Turns a parsed ``/dispatch`` command into a fleet action + a reply string.

    Never raises for operator failures — every path returns a clear message. The plan/
    execute collaborators are injected for testability; the real wiring is the deferred
    AO IPC round-trip (go-live).
    """

    def __init__(
        self,
        *,
        config: fleet.FleetDispatchConfig,
        enabled: bool,
        plan_fn: PlanFn | None = None,
        execute_fn: ExecuteFn | None = None,
        mint_run_id: Callable[[], str] = fleet.new_run_id,
        state_store: "_state.DispatchStateStore | None" = None,
        project_memory_enabled: bool = False,
        advanced_intake_interview_enabled: bool = False,
        advanced_intake_assets_pipeline_enabled: bool = False,
        advanced_intake_interview_playback_enabled: bool = False,
        advanced_intake_interview_voice_enabled: bool = False,
    ) -> None:
        self._config = config
        self._enabled = bool(enabled)
        self._plan_fn = plan_fn
        self._execute_fn = execute_fn
        self._mint_run_id = mint_run_id
        #: #1116 durability: the born-encrypted mirror of the three pending slots
        #: below, so a half-finished dispatch survives an app restart. ``None`` ==
        #: no persistence, and every path degrades to exactly the pre-#1116
        #: in-memory-only behaviour (the dev/test default; production wires it).
        self._state_store = state_store
        #: #1124 PROJECT-MEMORY GATE — dormant by default. False is FULL dormancy, not
        #: a degraded mode: `_recall` returns nothing and `_remember` writes nothing, so
        #: no row is ever created and the corridor behaves EXACTLY as it did pre-#1120.
        #: Deliberately a SEPARATE flag from `state_store`: #1116 durability (a parked
        #: question surviving a restart) carries no retention decision and must keep
        #: working while retention is off.
        self._project_memory_enabled = bool(project_memory_enabled)
        #: #1031 S2 — the intake-interview gate, gateway side (the caller passes the
        #: AO-resolved conjunction of the front flag AND the interview sub-flag). False
        #: is FULL dormancy: the hint line never renders, the sentinel is never
        #: composed, and `command.advanced` — which the parser can only set when its own
        #: token gate saw the same conjunction — is ignored defensively anyway.
        self._intake_enabled = bool(advanced_intake_interview_enabled)
        #: #1165 M5 — the assets-pipeline gate, gateway side (the caller passes the
        #: AO-resolved conjunction of the front flag AND the assets-pipeline sub-flag;
        #: interview-independent by design). The gateway's ONLY use is create_project
        #: seeding — the manifest/floors/card engagement lives AO-side in
        #: generate_plan behind the same two flags. False keeps every created project
        #: byte-identical to the pre-M5 scaffold.
        self._assets_pipeline_enabled = bool(advanced_intake_assets_pipeline_enabled)
        #: #1165 M4 — the playback gate, gateway side (the caller passes the AO-resolved
        #: conjunction of the front flag AND the interview sub-flag AND the playback
        #: sub-flag). False is FULL dormancy at every operator-visible seam: no card
        #: renders the invitation and a pipe-less reply keeps the #1116 usage/keep-text
        #: answer byte-identically. The ``intake`` carrier bit is stamped regardless —
        #: it records what the dispatch WAS (an interview-mode fact), never an
        #: engagement of this gate.
        self._playback_enabled = bool(advanced_intake_interview_playback_enabled)
        #: #1165 M1 — the interview-VOICE gate, gateway side (the caller passes the
        #: AO-resolved conjunction of the front, the interview, AND the voice sub-flag).
        #: False is FULL dormancy: the question render carries no preamble and the
        #: decide recognizer never admits the I-don't-know set — byte-identical to the
        #: S2 corridor.
        self._voice_enabled = bool(advanced_intake_interview_voice_enabled)
        # ONE pending dispatch per session (mirrors the ingest one-slot model).
        # TtlDict (#801): a plan the operator never decides would otherwise sit
        # until restart; reap_expired (called from the gateway's turn-start
        # sweep) drops entries past the TTL — an implicit reject, nothing fires.
        self._pending: TtlDict[PendingDispatch] = TtlDict()
        # ONE pending clarifying question per session (increment 4) — a session is in AT MOST
        # one of these two states at a time (clarification precedes approval; resolving it
        # clears this slot and populates _pending).
        self._clarifying: TtlDict[PendingClarification] = TtlDict()
        # ONE pending REQUIREMENTS-clarification question set per session (#819) — sits BEFORE
        # both the Inc-4 platform question and the approval preview. Answering (or deciding)
        # clears this slot and re-plans; at most one of _requirements / _clarifying / _pending
        # is populated at a time. TtlDict: an unanswered question set is reaped by the idle
        # sweep (implicit reject — nothing fires), same as the other two.
        self._requirements: TtlDict[PendingRequirements] = TtlDict()
        # One-shot per-session UI-action signal (#712): set to "dispatch_plan" when
        # a plan preview is rendered (the only reply that carries Approve/Reject
        # buttons), popped by the gateway to attach the buttons to that reply frame.
        # TtlDict (#801): pop-on-read normally clears it; the sweep bounds the
        # orphans a never-rendered reply leaves behind.
        self._last_action: TtlDict[str] = TtlDict()

    def pending_for(self, session_id: str) -> PendingDispatch | None:
        """The session's pending dispatch, or None (tests / inspection)."""
        return self._pending.get(session_id)

    def pending_clarification_for(self, session_id: str) -> PendingClarification | None:
        """The session's pending clarifying question, or None (tests / inspection)."""
        return self._clarifying.get(session_id)

    def pending_requirements_for(self, session_id: str) -> PendingRequirements | None:
        """The session's pending requirements-clarification question set, or None (#819)."""
        return self._requirements.get(session_id)

    # ── durable parking of the three slots (#1116) ────────────────────────

    def _park(self, session_id: str, slot: str, value: object) -> None:
        """Mirror a just-populated pending slot into the encrypted store.

        FAIL-LOUD BUT NON-BLOCKING: persistence is a durability aid, not a security
        control. A write failure is logged at ERROR and the turn CONTINUES on the
        in-memory slot — degrading to exactly the pre-#1116 behaviour rather than
        failing the operator's live turn. Session ids only are logged; goal text and
        plan content never are.
        """
        if self._state_store is None:
            return
        to_payload, _ = _SLOT_CODECS[slot]
        try:
            self._state_store.save(
                session_id,
                slot=slot,
                payload=to_payload(value),
                run_id=str(getattr(value, "run_id", "")),
            )
        except Exception as exc:  # noqa: BLE001 — durability must never break a turn
            logger.error(
                "Dispatch state: could not park the %s slot for session=%s (%s). The "
                "dispatch still works in this process, but will NOT survive a restart.",
                slot, session_id, exc,
            )
            # #1125: a failed RE-park would otherwise leave the SUPERSEDED row on disk.
            # The revise path re-parks over a live row without unparking first, so a
            # failure there resurrects the plan the operator already replaced — they
            # would approve v1 while the transcript shows v2. An absent row is honest
            # (the turn degrades to pre-#1116); a stale one is a lie with a signature.
            self._unpark(session_id)

    def _unpark(self, session_id: str) -> None:
        """Forget *session_id*'s parked dispatch — the store mirror of a slot pop.

        Called wherever a slot is cleared (answered, chosen, approved, rejected,
        reaped), so a resolved dispatch can never be resurrected by a later boot.
        Same non-blocking error posture as :meth:`_park`."""
        if self._state_store is None:
            return
        try:
            self._state_store.clear(session_id)
        except Exception as exc:  # noqa: BLE001 — durability must never break a turn
            logger.error(
                "Dispatch state: could not clear the parked slot for session=%s (%s). "
                "A stale slot may be restored at the next boot.",
                session_id, exc,
            )

    # ── project memory: what the operator has already told us (#1120) ─────

    def _recall(self, repo: str) -> list[dict]:
        """What the operator has already told us about *repo* (``[]`` when nothing/no store).

        Non-blocking on error — an unreadable memory degrades to "ask again", never to a
        failed turn."""
        if not self._project_memory_enabled or self._state_store is None or not repo:
            return []
        try:
            return self._state_store.recall_answers(repo)
        except Exception as exc:  # noqa: BLE001 — memory must never break a turn
            logger.error("Dispatch memory: could not recall answers for repo=%s (%s).", repo, exc)
            return []

    def _remember(self, repo: str, answers: list) -> None:
        """Record the FULL merged answer set for *repo*. Non-blocking on error."""
        if not self._project_memory_enabled or self._state_store is None or not repo:
            return
        try:
            self._state_store.remember_answers(repo, answers)
        except Exception as exc:  # noqa: BLE001 — memory must never break a turn
            logger.error(
                "Dispatch memory: could not remember answers for repo=%s (%s). The operator "
                "will be asked again on the next dispatch.", repo, exc,
            )

    def _forget(self, repo: str) -> str:
        """``/dispatch forget`` — clear a project's remembered answers (#1120).

        REQUIRED for correctness, not a convenience: without it a single wrong remembered
        answer would shape every future dispatch for that project forever, which is a worse
        trap than the amnesia this feature fixes."""
        if not repo:
            return (
                "Tell me which project to forget, e.g. `/dispatch forget my-site` — "
                "that clears what you've told me about it, nothing else."
            )
        if self._state_store is None:
            return "There's nothing remembered — this build isn't storing project answers."
        # #1123: clear BOTH the typed form and its slug. `/dispatch new My Site | …`
        # creates the project as the SLUG (`create_project` -> `project_slug`) and
        # `_create_and_plan` then plans on `result.name`, so the memory is keyed
        # `my-site` — while the operator types `My Site` here. Matching only the raw
        # string made the eraser silently no-op for every project whose name is not
        # already lower-kebab, which is worse than having no eraser: it REPORTS
        # success-shaped output ("wasn't remembering anything") while the memory it
        # was asked to clear survives and keeps shaping plans.
        keys = [repo]
        slug = fleet.project_slug(repo)
        if slug and slug != repo:
            keys.append(slug)
        try:
            # Deliberately NOT any(...): that short-circuits and would leave the
            # second key's row behind the moment the first matched.
            cleared = any([self._state_store.forget_answers(k) for k in keys])
        except Exception as exc:  # noqa: BLE001
            logger.error("Dispatch memory: could not forget repo=%s (%s).", repo, exc)
            return f"I couldn't clear what I remember about “{repo}” ({exc})."
        if not cleared:
            return f"I wasn't remembering anything about “{repo}”."
        return (
            f"Forgotten — I've cleared what you'd told me about “{repo}”. The next dispatch "
            "starts fresh and will ask again if it needs to."
        )

    def forget_session(self, session_id: str) -> bool:
        """Erase everything parked for *session_id* — memory AND disk (#1136).

        Called when the operator DELETES A CHAT. Until this existed, deleting a
        conversation removed the transcript from ``sessions.db`` and left the parked
        dispatch — goal text, typed answers, the whole plan — in ``dispatch_state.db``,
        where ``restore_at_boot`` faithfully reloaded it at the next boot for a session
        that no longer exists. `PRAGMA secure_delete=ON` only zeroes pages once something
        issues a DELETE, and nothing did.

        "Delete this chat" is the operator's erasure gesture. It has to mean it.

        Returns True if anything was actually removed (tests / callers may report it)."""
        had = (
            self._requirements.pop(session_id, None) is not None
            or self._clarifying.pop(session_id, None) is not None
            or self._pending.pop(session_id, None) is not None
        )
        self._last_action.pop(session_id, None)
        self._unpark(session_id)
        return had

    def restore_at_boot(self) -> dict[str, int]:
        """Repopulate the pending slots from the encrypted store (call once at boot).

        Idempotent and additive-only: an in-memory slot already populated for a
        session WINS and the stored row is left alone — a live process's own state is
        never overwritten by a restore. Rows the store could not authenticate or parse
        were already dropped, loudly, by ``load_all`` (fail-closed).

        The restored entries are stamped with a FRESH idle age, so the #801 sweep
        gives the operator a full idle window after a restart rather than reaping a
        just-restored question they never got a chance to answer.

        Returns:
            ``{slot: count}`` restored, for observability/tests.
        """
        counts: dict[str, int] = {s: 0 for s in _SLOT_CODECS}
        if self._state_store is None:
            return counts
        slots: dict[str, TtlDict] = {
            _state.SLOT_REQUIREMENTS: self._requirements,
            _state.SLOT_CLARIFYING: self._clarifying,
            _state.SLOT_PENDING: self._pending,
        }
        for row in self._state_store.load_all():
            target = slots[row.slot]
            if (
                row.session_id in self._requirements
                or row.session_id in self._clarifying
                or row.session_id in self._pending
            ):
                continue  # a live slot beats a stored one
            _, from_payload = _SLOT_CODECS[row.slot]
            try:
                target[row.session_id] = from_payload(row.payload)
            except Exception as exc:  # noqa: BLE001 — one bad row never blocks the rest
                logger.error(
                    "Dispatch state: session=%s parked %s row could not be rebuilt (%s) "
                    "— dropping it (fail-closed).",
                    row.session_id, row.slot, exc,
                )
                self._unpark(row.session_id)
                continue
            counts[row.slot] += 1
        total = sum(counts.values())
        if total:
            logger.info(
                "Dispatch state: restored %d parked dispatch(es) across a restart "
                "(%s) — pending questions and plan cards are answerable again.",
                total,
                ", ".join(f"{k}={v}" for k, v in counts.items() if v),
            )
        return counts

    def pop_action_kind(self, session_id: str) -> str:
        """Pop the one-shot UI-action kind for *session_id* (#712).

        Returns ``"dispatch_plan"`` exactly once after a plan preview was just
        rendered (so the gateway attaches Approve/Reject buttons to that reply),
        else ``""``. One-shot, mirroring the imagine/ingest meta signals."""
        return self._last_action.pop(session_id, "")

    def reap_expired(self, ttl_s: float) -> dict[str, list[str]]:
        """Drop pending plans/clarifications/action-signals idle past *ttl_s*
        (the #801 idle backstop; called from the gateway's turn-start sweep).

        Dropping a pending plan or clarification is an implicit reject —
        nothing was approved, so nothing ever fires; a later ``/dispatch
        approve`` gets the standard "nothing pending" notice. Deliberately
        NOT a freshness policy (a plan does not go un-approvable after N
        hours by design — that would be an LA semantics decision); this only
        bounds abandoned state. ``ttl_s <= 0`` disables the sweep.

        Returns:
            ``{dict_name: [session_ids dropped]}`` for observability/tests.
        """
        reaped: dict[str, list[str]] = {
            "pending": self._pending.sweep(ttl_s),
            "clarifying": self._clarifying.sweep(ttl_s),
            "requirements": self._requirements.sweep(ttl_s),
            "last_action": self._last_action.sweep(ttl_s),
        }
        # #1116: an implicit reject must be DURABLE. Without this, a swept slot would
        # be restored at the next boot and the operator would be answering a question
        # the running process had already abandoned — the same UI-vs-engine divergence
        # persistence exists to end, merely inverted.
        for name in ("pending", "clarifying", "requirements"):
            for session_id in reaped[name]:
                self._unpark(session_id)
        for name, sessions in reaped.items():
            if sessions:
                # Eviction events are LOGGED (LA condition, #801 c.1666) —
                # session ids only, never goals/plan content.
                logger.info(
                    "Dispatch reaper: dropped %d expired %s entry(ies) for "
                    "session(s): %s (ttl=%.0fs; implicit reject — nothing "
                    "fires).",
                    len(sessions),
                    name,
                    ", ".join(sessions),
                    ttl_s,
                )
        return reaped

    async def handle_command(self, session_id: str, command: DispatchCommand) -> str:
        if not self._enabled:
            return (
                "Coding dispatch is off. It's dormant by default — enable it with "
                "[fleet_dispatch].enabled = true in the orchestrator config."
            )
        try:
            # #819: while requirements-clarification questions are pending, the operator's
            # reply ANSWERS them. reject/status/stop keep their normal meaning; a decide reply
            # takes the defaults; any other text (an explicit "answer <text>", a bare
            # "/dispatch <words>", or a stray option number) is the free-text answer. This is
            # what makes the corridor a single interactive turn, mirroring the Inc-4 sub-state.
            if self._requirements.get(session_id) is not None:
                if command.kind == "reject":
                    return self._reject(session_id)
                if command.kind == "status":
                    return await self._status(command.run_id)
                if command.kind == "stop":
                    return await asyncio.to_thread(self._stop, session_id)
                if command.kind == "decide":
                    return await self._decide_requirements(session_id)
                # #820: a "revise …" while a question is pending is nonsensical (no plan yet) —
                # treat its text as the free-text answer rather than dropping it silently.
                # #1126: ``repo`` is in this chain for the same reason. The parser matches
                # "forget <rest>" as a verb BEFORE the free-text fall-through, so an answer
                # that happens to begin "forget about the phone, just the browser…" parses
                # as kind="forget" with the operator's words in ``repo``. Omitting it here
                # blanked the answer and re-asked the question — the eats-operator-text
                # class, in the very file that exists to end it.
                # #1160 d2: the consumption is kept (accidentally-good — the words survive)
                # but no longer SILENT: a reserved-verb reply earns one honest notice line
                # on the very next reply, so "revise the criteria" typed at the question
                # stage can never again become a briefed requirement without the operator
                # being told. Routing above is untouched (reject/status/stop/decide).
                text = (
                    command.answer or command.goal or command.choice
                    or command.feedback or command.repo
                )
                return await self._answer_requirements(
                    session_id, text, consumed_verb=_consumed_verb(command)
                )
            if command.kind in ("answer", "decide"):
                # #1116: an explicit answer that lands with nothing to answer. The
                # words are kept (a "decide" carries none — the helper no-ops).
                return _no_question_waiting(command.answer or command.goal)
            if command.kind == "status":
                return await self._status(command.run_id)
            if command.kind == "forget":
                return self._forget(command.repo)
            if command.kind == "approve":
                return await self._approve(session_id)
            if command.kind == "revise":
                return await self._revise(session_id, command.feedback)
            if command.kind == "reject":
                return self._reject(session_id)
            if command.kind == "stop":
                return await asyncio.to_thread(self._stop, session_id)
            if command.kind == "choose":
                return await self._choose(session_id, command.choice)
            if command.kind == "create":
                return await self._create_and_plan(
                    session_id, command.repo, command.goal,
                    advanced=command.advanced,
                )
            return await self._plan(
                session_id, command.repo, command.goal, advanced=command.advanced
            )
        except Exception as exc:  # noqa: BLE001 — surface, never crash the turn
            logger.error("Dispatch command %r failed for session=%s: %s",
                         command.kind, session_id, exc, exc_info=True)
            return f"Dispatch failed (Fail-Closed): {exc}"

    # ── PLAN: /dispatch <repo> | <goal> ───────────────────────────────────

    async def _plan(
        self, session_id: str, repo: str, goal: str, *, advanced: bool = False
    ) -> str:
        # #1031 S2: the operator's explicit request for the fuller interview, honoured
        # only when the gateway-side gate is on (defense in depth — the parser's token
        # gate already required the same conjunction to set the flag at all).
        advanced_active = bool(advanced) and self._intake_enabled
        if not repo or not goal:
            # #1165 M4: a pipe-less free-text reply while an INTAKE plan card awaits
            # approval is the playback answer that card invited — route it to the
            # EXISTING bounded revise as feedback (a playback correction IS a revision:
            # same budget, same delta card, same fail-soft). Reserved verbs never reach
            # here — approve/reject/revise/status parse first, exactly as today — and
            # the PIPED shape never enters this branch, so its "already waiting" nag
            # below stays the right answer to an attempted second dispatch. Everything
            # else — flag off, quick-path card, no card at all, empty text, a piped
            # shape missing only its goal — keeps the #1116 reply below byte-identically.
            if not repo and goal:
                playback_card = self._pending.get(session_id)
                if (
                    self._playback_enabled
                    and playback_card is not None
                    and playback_card.intake
                ):
                    return await self._revise(session_id, goal)
            # #1116: a pipe-less reply parses as goal-with-no-repo — which is the EXACT
            # shape of an answer to a question this process no longer holds. Whatever
            # the operator typed comes back to them verbatim; the pre-#1116 code
            # returned the usage line and dropped the text on the floor.
            return _keep_operator_text(
                "Usage: /dispatch <repo> | <goal>  —  e.g. "
                "/dispatch calc | a calculator an 8-year-old can use",
                goal or repo,
            )
        # #819 requirements clarification is answered via handle_command's routing, so this
        # nag is defensive (e.g. _create_and_plan reaching here): don't start a fresh plan on
        # top of an unanswered question set.
        req_pending = self._requirements.get(session_id)
        if req_pending is not None:
            return (
                f"I'm still waiting on your answer for “{req_pending.goal}”. Reply in your own "
                "words, or /dispatch just decide for me, or /dispatch reject to cancel."
            )
        clarifying = self._clarifying.get(session_id)
        if clarifying is not None:
            return (
                f"I'm waiting on one question first for “{clarifying.goal}”: "
                f"{clarifying.question.get('question', '')} "
                "Reply with the option number, or /dispatch reject to cancel."
            )
        pending = self._pending.get(session_id)
        if pending is not None:
            return (
                f"A dispatch is already waiting for your approval: “{pending.goal}”. "
                "Reply /dispatch approve, /dispatch reject, or /dispatch revise <what to "
                "change> before starting another."
            )
        if self._plan_fn is None:
            return self._wiring_notice()

        # FIRST pass. #1120: thread in whatever the operator has ALREADY told us about this
        # project, so a rejected plan does not throw away their answers. The planning goal is
        # enriched exactly the way a fresh answer enriches it (`compose_planning_goal`) — one
        # code path, so a remembered answer and a just-given one reach the 14B identically.
        # Nothing remembered (or no store) leaves the call byte-identical to before.
        remembered = self._recall(repo)
        # #1161: the honest MOBILE refusal, before any model time is spent. Scope: an
        # EMPTY/NEW project whose operator words (goal + remembered non-assumed answers)
        # name a phone — the case the fleet cannot build and used to rebuild silently as
        # desktop-from-nothing. An existing project keeps today's behavior byte-for-byte.
        if acc.is_empty_new_project(self._repo_path(repo)):
            operator_words = "\n".join(
                [goal]
                + [
                    str(c.get("answer", ""))
                    for c in remembered
                    if isinstance(c, dict) and not c.get("assumed")
                ]
            )
            if acc.operator_platform_signal(operator_words) == "mobile":
                return _keep_operator_text(
                    _MOBILE_REFUSAL + " Nothing was planned.", goal
                )
        # #1031 S2: the intake marker rides the goal HEAD — composed BEFORE any
        # requirements block, so the AO-side split leaves it on the clean goal head.
        planning_goal = (
            _clarify.compose_intake_goal(goal) if advanced_active else goal
        )
        if remembered:
            planning_goal = _clarify.compose_planning_goal(
                planning_goal, _clarify.compose_requirements_block(remembered)
            )
        # The AO may return requirements-clarification QUESTIONS (#819) instead of a plan when
        # the goal is underspecified and the stage is enabled; a sufficient goal (or a battery
        # card / clarify off) returns a plan directly.
        plan = await self._plan_fn(repo, planning_goal)
        if not plan.ok:
            return plan.message
        if plan.questions:
            run_id = self._mint_run_id()
            parked = PendingRequirements(
                run_id=run_id,
                repo=repo,
                goal=goal,
                questions=list(plan.questions),
                submitted_at=datetime.now(timezone.utc).isoformat(),
                intake=advanced_active,
            )
            self._requirements[session_id] = parked
            # #1116: the question we are about to render is durably stored, so the
            # instruction "reply /dispatch <your answers>" stays TRUE across a restart.
            self._park(session_id, _state.SLOT_REQUIREMENTS, parked)
            # #1031 S2: the discoverability hint — one deterministic line on the QUICK
            # path's questions when the interview exists and the ask is big. Never a
            # mode entry; the operator always chooses.
            return self._render_requirements_questions(
                goal, plan.questions,
                intake_hint=(
                    (not advanced_active)
                    and self._intake_enabled
                    and len(goal.split()) >= _INTAKE_HINT_MIN_WORDS
                ),
                # #1165 M1: the Phase-0 setting-the-table preamble — INTAKE renders
                # only, and only with the voice flag live.
                preamble=advanced_active and self._voice_enabled,
            )

        # #1031 S2 (design §3.7 + §6): an `advanced` dispatch that yields zero questions
        # owes the operator one honest line. With remembered answers the reason is
        # memory (and the escape hatch is named); otherwise the goal was sufficient or
        # the interview failed soft — deliberately indistinguishable, and the wording is
        # true for both.
        note = ""
        if advanced_active and remembered:
            note = (
                "Using what you've already told me about this project — reply "
                f"`/dispatch forget {repo}` first if you want the full interview fresh."
            )
        elif advanced_active:
            note = "No further questions — planning directly."

        # #1120: remembered answers ride onto the spec so the card SHOWS what BlarAI is
        # carrying from earlier turns — an invisible memory is worse than none.
        return self._finalize_plan(
            session_id, repo=repo, goal=goal, plan=plan,
            clarifications=_merge_clarifications(remembered, ()),
            clarified_note=note,
            intake=advanced_active,
        )

    # ── the requirements-clarification answer (#819) ──────────────────────

    async def _answer_requirements(
        self, session_id: str, text: str, *, consumed_verb: str = ""
    ) -> str:
        """Consume the operator's free-text answer to the requirements questions, then re-plan
        with those answers threaded in. A "just decide for me" reply routes to the defaults; a
        blank reply re-asks (never a silent proceed). At most ONE requirements turn per dispatch
        ON SUCCESS — the slot clears only once the re-plan actually returns a plan (#1152): a
        Fail-Closed transport/timeout error leaves the SAME question parked so the operator's
        answer is never thrown away, and replying again just retries the re-plan with it.

        #1160 d2: *consumed_verb* names the reserved verb this reply arrived wearing
        (:func:`_consumed_verb`); non-empty, the next reply LEADS with the one honest
        notice line — the words were taken as answers, and the verb's own job did not run.
        ``""`` (every plain answer) is byte-identical."""
        pending_req = self._requirements.get(session_id)
        if pending_req is None:
            return _no_question_waiting(text)
        answer = (text or "").strip()
        if not answer:
            # #1160 d2 (+ review F5): a BARE reserved verb at the question stage —
            # approve (whose parser drops trailing words), revise, forget, or new with
            # nothing after it — carries no text, so nothing is consumed; but the nag
            # alone read as if the operator had failed to answer, when what actually
            # happened is they thought a plan existed to act on. Lead with the honest
            # state per verb, then the unchanged re-ask. A plain empty answer (no verb)
            # keeps the bare nag byte-identically.
            return _no_plan_yet_lead(consumed_verb) + (
                "I didn't catch an answer — tell me in your own words with "
                "/dispatch <your answer>, or reply /dispatch just decide for me."
            )
        # #1165 M1: with the voice flag live AND the parked set an INTAKE one, a
        # WHOLE-reply "I don't know" is the same escape hatch as "you decide" — safe
        # defaults chosen and RECORDED as assumptions the card shows (the preamble's
        # promise made true, exactly where the preamble was made). The intake term is
        # the design §0 contract (review F2): a normal /dispatch stays byte-for-byte
        # today's behaviour even after the ceremony flips the flag, so a QUICK park
        # keeps recording such a reply as a substantive answer — as does flag-off
        # everywhere, and the parser's own decide site, which never passes the keyword.
        if _clarify.is_decide_for_me(
            answer, dont_know=self._voice_enabled and pending_req.intake
        ):
            return await self._decide_requirements(session_id)
        # #1031 S2: a parked INTAKE question set reconstructs with the eight-axis
        # vocabulary (else a stored `content` question would coerce to `feature`), and
        # its recorded answer carries the asked-axes tags for the acceptance record.
        questions = _clarify.questions_from_dicts(
            pending_req.questions,
            axes=_clarify.INTAKE_AXES if pending_req.intake else _clarify.CLARIFY_AXES,
        )
        # #1197: axes are recorded on BOTH paths now. They were opt-in (`pending_req.intake`)
        # because #1031 S2 shipped dormant and owed a byte-identical flag-off record; that
        # ceremony has run. Leaving them opt-in made `platform_was_assumed` — the #1174 gate —
        # inert on the DEFAULT quick path, which is the path the operator was actually on.
        clarifications = _clarify.answered_from_free_text(
            questions, answer, record_axes=True
        )
        reply = await self._replan_with_requirements(
            session_id, pending_req, clarifications
        )
        notice = _verb_taken_as_answer_notice(consumed_verb) if consumed_verb else ""
        if notice:
            # Prepended to WHATEVER came back — the approval card, the Inc-4 platform
            # question, or the answer-kept failure message — so the notice can never be
            # dropped by a downstream branch (#1160 d2: "the next card carries it").
            reply = notice + "\n\n" + reply
        return reply

    async def _decide_requirements(self, session_id: str) -> str:
        """The "just decide for me" escape hatch: self-answer every asked question with its
        per-axis default and re-plan. The defaults are RECORDED as assumptions on the plan card
        (``assumed=True``), so the operator sees what was chosen and can reject a wrong one."""
        pending_req = self._requirements.get(session_id)
        if pending_req is None:
            return _no_question_waiting()
        # #1031 S2: same axes selection as the free-text path — the "just decide"
        # defaults for content/edge/nongoal exist only when the reconstruction knows the
        # question was an intake one.
        questions = _clarify.questions_from_dicts(
            pending_req.questions,
            axes=_clarify.INTAKE_AXES if pending_req.intake else _clarify.CLARIFY_AXES,
        )
        # #1161: on an EMPTY/NEW project the surface default is the gradeable stack, in
        # the assumed answer's OWN text — so the card's "you asked me to decide" line and
        # the plan's resolved platform agree, instead of an "app on this computer"
        # assumption riding a command-line build. An existing project keeps the stock
        # default byte-for-byte; the deterministic refiner in generate_plan is the
        # backstop either way.
        axis_defaults = None
        if acc.is_empty_new_project(self._repo_path(pending_req.repo)):
            axis_defaults = {
                _clarify.AXIS_SURFACE: _clarify.EMPTY_PROJECT_SURFACE_ANSWER
            }
        # #1197: record_axes=True unconditionally — see the note on the free-text path above.
        # This is the entry that matters: it is the "just decide for me" answer, so it carries
        # assumed=True, and without an axis tag `platform_was_assumed` could not tell a
        # system-chosen SURFACE from a system-chosen colour scheme and defaulted to silence.
        clarifications = _clarify.decide_defaults(
            questions, record_axes=True, axis_defaults=axis_defaults
        )
        return await self._replan_with_requirements(session_id, pending_req, clarifications)

    async def _replan_with_requirements(
        self, session_id: str, pending_req: PendingRequirements, clarifications: list
    ) -> str:
        """Re-run PLAN with the clarified requirements threaded into the goal, then finalize the
        approval preview (attaching the clarifications to the spec for the plan card + record).
        The ``run_id`` minted for the question set is carried through so status/reports line up.

        #1152: the requirements slot clears ONLY on a successful plan (moved from the two
        callers above). A Fail-Closed transport error here (the AO outran the PLAN budget —
        #766/#1152 is exactly this: the answer-enriched re-plan runs the FULL ~6-7 chained 14B
        call sequence, unlike the single sufficiency-check generation the first PLAN pass ran)
        used to pop the slot BEFORE this call, silently discarding a multi-paragraph operator
        answer on every such failure. Now it stays parked so a bare retry re-plans with the
        SAME answer instead of forcing the operator to retype it."""
        if self._plan_fn is None:
            return self._wiring_notice()
        # #1120: the operator's answers are cumulative across dispatches for a project — merge
        # what they just said over what they told us before (fresh wins per question), plan
        # with the whole set, and PERSIST it so rejecting this plan does not erase any of it.
        merged = _merge_clarifications(self._recall(pending_req.repo), clarifications)
        # #1161: the honest MOBILE refusal, checked over the operator's OWN words (goal +
        # every non-assumed answer, remembered included — never the system's defaults)
        # BEFORE the re-plan spends a full 14B chain. Empty/new projects only — an
        # existing project keeps today's behavior. The slot stays PARKED (#1152 shape):
        # the answers are kept, and answering again with a workable platform (web wins
        # over a phone mention by the scan's precedence) retries with them.
        if acc.is_empty_new_project(self._repo_path(pending_req.repo)):
            operator_words = "\n".join(
                [pending_req.goal]
                + [
                    str(c.get("answer", ""))
                    for c in merged
                    if isinstance(c, dict) and not c.get("assumed")
                ]
            )
            if acc.operator_platform_signal(operator_words) == "mobile":
                fresh_text = "\n".join(
                    str(c.get("answer", ""))
                    for c in clarifications
                    if isinstance(c, dict) and not c.get("assumed")
                ).strip()
                return _keep_operator_text(
                    _MOBILE_REFUSAL
                    + " Answer again with where it should run, "
                    f"`/dispatch forget {pending_req.repo}` if an earlier answer "
                    "mentioned a phone, or `/dispatch reject` to cancel.",
                    fresh_text,
                )
        block = _clarify.compose_requirements_block(merged)
        enriched_goal = _clarify.compose_planning_goal(pending_req.goal, block)
        plan = await self._plan_fn(pending_req.repo, enriched_goal)
        if not plan.ok:
            return (
                f"{plan.message}\n\nYour answer wasn't lost — reply the same way again "
                "and I'll retry the plan with it, or /dispatch reject to cancel."
            )
        # The slot clears — and the merged answers bank — only now that the AO actually
        # returned a plan; it stays parked before this line (#1152).
        self._requirements.pop(session_id, None)
        self._unpark(session_id)
        # Remember only after a SUCCESSFUL plan: a transport/knob failure must not bank a set
        # the operator never saw rendered.
        self._remember(pending_req.repo, merged)
        # The re-plan carries requirements, so the AO suppresses clarify — but never loop even
        # if it somehow returned questions again: _finalize_plan ignores them and proceeds.
        return self._finalize_plan(
            session_id, repo=pending_req.repo, goal=pending_req.goal, plan=plan,
            clarifications=merged, run_id=pending_req.run_id,
            intake=pending_req.intake,
        )

    def _render_requirements_questions(
        self, goal: str, questions: list, *, intake_hint: bool = False,
        preamble: bool = False,
    ) -> str:
        """The operator-facing CLARIFY turn (#819): the goal + a short numbered list of the
        plain-language questions + how to answer. Novice-friendly — one free-text reply, or the
        one-tap "just decide for me" escape. The system asks; the operator answers in words.

        #1031 S2: *intake_hint* appends the one-line `advanced` discoverability nudge —
        honest about the mechanics (reject, then re-dispatch with the token; no
        in-corridor switch exists). False (every quick render below the size threshold,
        and every flag-off render) is byte-identical to today.

        #1165 M1: *preamble* opens the render with the Phase-0 setting-the-table
        sentences (:data:`shared.fleet.clarify.INTAKE_PREAMBLE` — the no-wrong-answers
        promise). The caller passes it only for an INTAKE render with the voice flag
        live; False (every quick render and every flag-off render) is byte-identical."""
        lines: list[str] = []
        if preamble:
            lines += [_clarify.INTAKE_PREAMBLE, ""]
        lines += [f"Before I build “{goal}”, a few quick questions so I get it right:", ""]
        for i, q in enumerate(questions, start=1):
            text = q.get("question", "") if isinstance(q, dict) else str(q)
            lines.append(f"  {i}. {text}")
        lines += [
            "",
            "Answer in your own words — reply `/dispatch <your answers>` (one message is fine).",
            "Or reply `/dispatch just decide for me` and I'll choose sensible defaults.",
            "Or `/dispatch reject` to cancel.",
        ]
        if intake_hint:
            lines += [
                "",
                "Bigger build? `/dispatch reject`, then `/dispatch advanced <project> | "
                "<the same goal>` for a fuller interview.",
            ]
        return "\n".join(lines)

    def _finalize_plan(
        self, session_id: str, *, repo: str, goal: str, plan: PlanResult,
        clarifications: "list | tuple" = (), run_id: str | None = None,
        clarified_note: str = "", intake: bool = False,
    ) -> str:
        """Shared PLAN-to-preview tail: detect ecosystem, run the Inc-4 platform question if the
        14B flagged an ambiguous fork, else render the approval preview. Attaches any #819
        requirements clarifications to the spec first (display + record) — this is the single
        place both the no-question path and the post-requirements re-plan converge.

        ``intake`` (#1165 M4) is the interview-mode bit from the two callers —
        ``advanced_active`` on the no-question path, ``pending_req.intake`` on the
        re-plan path — stamped onto WHICHEVER hold this parks (the Inc-4 clarifying
        hold or the approval slot), so the approval turn still knows the dispatch's
        mode after the question turn is gone."""
        repo_path = self._repo_path(repo)
        ecosystem = acc.detect_ecosystem(repo_path)
        rid = run_id or self._mint_run_id()
        spec = plan.spec
        if clarifications:
            spec = replace(spec, clarifications=tuple(clarifications))

        # #888: a New-Project repo is an empty README shell at PLAN time, so ecosystem sniffs
        # ``unknown`` and the card would wrongly warn "I couldn't tell the language" — yet the
        # run's OWN scaffold pins the language minutes later and the behaviour checks DO run.
        # When the repo will actually be scaffolded (no project markers yet) AND the build signal
        # maps to a behaviour-GATED scaffold (node/python), resolve that ecosystem so the preview
        # states the run's truth. Existing repos and non-gated surfaces yield "" -> honest warning
        # preserved. This is a disclosure fix — it NEVER widens a real coverage claim.
        # #1161 d2: the fresh-scaffold bit is computed ONCE here and CARRIED on both parked
        # shapes — it also drives the card's build-risk disclosure, incl. on re-renders.
        will_scaffold = ecosystem == "unknown" and acc.repo_will_scaffold(repo_path)
        scaffold_ecosystem = ""
        if will_scaffold:
            scaffold_ecosystem = acc.scaffold_gated_ecosystem(spec.build_plan)

        # Increment 4 — the confidence-gated clarifying question. If (and ONLY if) the 14B
        # flagged a genuinely ambiguous platform fork, the SYSTEM (never the model) asks ONE
        # curated question BEFORE the normal approval preview. resolve_clarifying_question is
        # the single gate: it returns None for a clear / unknown / absent surface (or an
        # unmapped fork), in which case the flow is EXACTLY today's — no extra turn.
        question = acc.resolve_clarifying_question(spec.build_plan)
        # #1174 (LA-decided 2026-07-29): increment 4 asks only when the MODEL was unsure.
        # It stays silent in the case that actually bit the operator — when the model was
        # perfectly sure because the SYSTEM had just told it what to think. On a fresh repo
        # taking the decide-for-me path, the surface default resolves to a command-line
        # tool and the plan proceeds with a confidently-classified surface the operator
        # never chose. They asked for a kitchen helper and got a command-line probe.
        #
        # So also ask when the surface was ASSUMED on a repo we are about to scaffold. The
        # operator can answer every other axis with "you decide" and still own the one
        # choice they are best placed to make and least able to recover from. Narrow by
        # construction: an operator who answered in their own words records assumed=False
        # and never sees this; an existing repo never reaches it; and if the model already
        # raised the fork, increment 4 owns the turn and this adds nothing.
        if question is None and will_scaffold and acc.platform_was_assumed(spec.clarifications):
            question = acc.platform_question_for_assumed_surface()
        # #1161 review F3: on an EMPTY/NEW repo the menu must not offer "On a phone" —
        # a phone choice would mint an approvable plan for a build the corridor's own
        # refusal says cannot exist (structural absence beats offer-then-refuse).
        # Filtered ONCE, before parking, so the parked question — and its restore across
        # a restart — carries exactly the menu the operator saw. A menu left with no
        # options degrades to no-question (the unmapped-fork path, today's flow).
        if question is not None and will_scaffold:
            question = acc.suppress_phone_option_for_fresh_repo(question)
        if question is not None:
            parked = PendingClarification(
                run_id=rid,
                repo=repo,
                goal=goal,
                tasks=plan.tasks,
                spec=spec,
                question=question,
                ecosystem=ecosystem,
                scaffold_ecosystem=scaffold_ecosystem,
                fell_back=plan.fell_back,
                submitted_at=datetime.now(timezone.utc).isoformat(),
                coverage_blocked=plan.coverage_blocked,
                will_scaffold=will_scaffold,
                intake=intake,
            )
            self._clarifying[session_id] = parked
            self._park(session_id, _state.SLOT_CLARIFYING, parked)
            return self._render_clarifying_question(goal, question)

        # #1031 S2 (design review F3): the passthrough note rides ONLY this direct tail
        # call. When the Inc-4 question interposed above, it was deliberately dropped —
        # a question DID appear, so no "no questions" explanation is owed, and _choose's
        # own note keeps its seam uncollided.
        return self._finalize_pending(
            session_id, run_id=rid, repo=repo, goal=goal,
            tasks=plan.tasks, spec=spec, ecosystem=ecosystem,
            scaffold_ecosystem=scaffold_ecosystem, fell_back=plan.fell_back,
            coverage_blocked=plan.coverage_blocked,
            clarified_note=clarified_note,
            will_scaffold=will_scaffold,
            intake=intake,
        )

    # ── CREATE + PLAN: /dispatch new <name> | <goal>  (#712) ──────────────

    async def _create_and_plan(
        self, session_id: str, name: str, goal: str, *, advanced: bool = False
    ) -> str:
        """Create a new git project, then run the normal PLAN on it (one motion).

        The "start a new project" flow for a non-git operator: ``create_project``
        does the git plumbing (init + scaffold + first commit on ``main``), then
        we delegate to :meth:`_plan` on the freshly-created slug — which now finds
        ``.git`` and proceeds straight to the criteria preview / approval (the
        not-found offer is skipped). Fail-Closed: a creation failure surfaces the
        clear message and nothing is planned.
        """
        if not name or not goal:
            # #1116: the missing-name case is the one that burned the operator on
            # 2026-07-27 — a long project description typed with the name left blank.
            # The description comes back verbatim; only the name is actually missing.
            return _keep_operator_text(
                "I need a short project name as well as the description. "
                "Usage: /dispatch new <name> | <goal>  —  e.g. "
                "/dispatch new kid-calc | a calculator a kid can use",
                goal or name,
            )
        # Don't start a new project on top of an unresolved dispatch.
        if (
            self._requirements.get(session_id) is not None
            or self._clarifying.get(session_id) is not None
            or self._pending.get(session_id) is not None
        ):
            return (
                "Finish the dispatch that's already waiting first "
                "(/dispatch approve or /dispatch reject), then start a new project."
            )
        result = await asyncio.to_thread(
            fleet.create_project, name, config=self._config, goal=goal,
            # #1165 M5: seed the assets/ folder contract only when the AO-resolved
            # pipeline conjunction is on — off keeps the scaffold byte-identical.
            seed_assets=self._assets_pipeline_enabled,
        )
        if not result.ok:
            return result.message
        # Created — PLAN on the fresh repo (slug as actually created).
        plan_reply = await self._plan(session_id, result.name, goal, advanced=advanced)
        return f"{result.message}\n\n{plan_reply}"

    def _render_clarifying_question(self, goal: str, question: dict) -> str:
        """The operator-facing clarifying turn: the one curated question + the numbered
        options. Novice-friendly — the operator answers with the option number (e.g. ``2``)
        or ``/dispatch use 2``. No platform is guessed; the system asks, the operator decides."""
        lines = [
            f"Before I plan “{goal}”, one quick question:",
            "",
            question.get("question", ""),
        ]
        for i, opt in enumerate(question.get("options", []), start=1):
            lines.append(f"  {i}. {opt.get('label', '')}")
        lines += [
            "",
            "Reply with the number (e.g. `2`), or `/dispatch reject` to cancel.",
        ]
        return "\n".join(lines)

    def _revise_hint(self, revision_count: int) -> str:
        """The plan-card footer hint that offers the free-text revise verb (#820), honest about
        the remaining count. Empty at :data:`shared.fleet.revise.DEFAULT_MAX_REVISIONS` (no
        refine offered — only approve/reject), which also renders the pre-#820 footer."""
        left = _revise.DEFAULT_MAX_REVISIONS - revision_count
        if left <= 0:
            return ""
        if revision_count <= 0:
            return "`/dispatch revise <what to change>` to change the plan."
        return f"`/dispatch revise <what to change>` to refine it again ({left} more)."

    def _close_card(
        self, preview: str, *, intake: bool, revision_count: int,
        coverage_blocked: str = "",
    ) -> str:
        """#1165 M4: append the playback invitation to an INTAKE card, else return
        *preview* untouched — the ONE place the invitation's double gate (the dispatch
        was interview-mode AND the playback flag is on) is applied, shared by every
        render of the card (finalize, criteria-revise wall report, revise fail-soft).
        ``coverage_blocked`` is the card's own carried marker, threaded so the
        invitation's offered actions agree with the S3-F gate that rules on them
        (fix-round review F1)."""
        if not (intake and self._playback_enabled):
            return preview
        return preview + "\n\n" + _playback_invitation(
            revision_count, coverage_blocked
        )

    def _finalize_pending(
        self, session_id: str, *, run_id: str, repo: str, goal: str,
        tasks: list, spec: AcceptanceSpec, ecosystem: str, fell_back: bool,
        scaffold_ecosystem: str = "", clarified_note: str = "", revision_count: int = 0,
        coverage_blocked: str = "", will_scaffold: bool = False, intake: bool = False,
    ) -> str:
        """Store the approval-pending dispatch + render the normal PLAN preview.

        Shared by the no-question path (today's flow, unchanged), the post-clarification path
        (after the operator's answer threaded a real surface into the plan), and the #820 revise
        path. The optional ``clarified_note`` leads the preview when we got here via a clarifying
        answer or a revision (so the operator sees what was resolved / the CHANGED-vs-KEPT delta).
        ``revision_count`` (#820) rides onto the stored plan and drives the revise-hint footer;
        a fresh plan is 0 (offers the verb) — a plan at the cap renders approve/reject only.
        ``intake`` (#1165 M4) rides onto the stored plan and, with the playback gate on,
        closes the card with the playback invitation."""
        parked = PendingDispatch(
            run_id=run_id,
            repo=repo,
            goal=goal,
            tasks=tasks,
            spec=spec,
            ecosystem=ecosystem,
            scaffold_ecosystem=scaffold_ecosystem,
            submitted_at=datetime.now(timezone.utc).isoformat(),
            revision_count=revision_count,
            coverage_blocked=coverage_blocked,
            will_scaffold=will_scaffold,
            intake=intake,
        )
        self._pending[session_id] = parked
        # #1116: the plan card is durably stored, so /dispatch approve and /dispatch
        # revise <changes> still mean something after a restart.
        self._park(session_id, _state.SLOT_PENDING, parked)
        # Signal the gateway to attach Approve/Reject buttons to this preview (#712).
        self._last_action[session_id] = "dispatch_plan"
        preview = acc.render_criteria_preview(
            spec, ecosystem=ecosystem, tasks=tasks, revise_hint=self._revise_hint(revision_count),
            scaffold_ecosystem=scaffold_ecosystem,
            coverage_blocked=coverage_blocked,
            will_scaffold=will_scaffold,
        )
        # #1165 M4: the intake card CLOSES with the playback turn — appended before the
        # lead notes below so the invitation is the card's last word on every path that
        # renders one (fresh plan, post-clarification, revise re-render).
        preview = self._close_card(
            preview, intake=intake, revision_count=revision_count,
            coverage_blocked=coverage_blocked,
        )
        if fell_back:
            # Honesty: the 14B couldn't fully parse the goal, so the plan is a thin
            # fallback. Surface that plainly — silent degradation is the exact thing
            # the acceptance layer exists to prevent (a non-dev would otherwise see a
            # minimal build-only plan with no sign anything went wrong).
            preview = (
                "Heads up: I couldn't fully parse that goal, so I fell back to a "
                "MINIMAL plan — if the criteria below look too thin, reply "
                "/dispatch reject and rephrase the goal.\n\n"
            ) + preview
        if clarified_note:
            preview = clarified_note + "\n\n" + preview
        return preview

    # ── the clarifying answer: /dispatch <n>  (increment 4) ───────────────

    async def _choose(self, session_id: str, choice: str) -> str:
        """Answer the pending clarifying question: map the chosen option to a surface, thread
        it into the plan, and proceed to the normal approval preview.

        Bounded by construction — at most ONE clarifying turn per dispatch:
          * No clarification pending -> a clear message (nothing to answer).
          * A valid in-range option -> apply_clarification + re-thread the goal-level build
            fields onto the compiled tasks (only ``surface`` changed; the test block is
            untouched), update spec.build_plan, clear the clarification slot, and finalize the
            approval-pending preview.
          * A malformed / out-of-range answer -> FALL BACK: proceed with the UN-REFINED plan
            (surface stays ambiguous -> the fleet threading coerces it to unknown == today's
            no-seed path), never a hang/loop. The operator can still /dispatch reject.
        """
        clarifying = self._clarifying.get(session_id)
        if clarifying is None:
            # The operator's reply here is a bare option number, not prose — there is
            # no substantive text to keep, so this path carries none.
            return _no_question_waiting()

        options = clarifying.question.get("options", [])
        idx = self._parse_choice(choice, len(options))
        # #1224: the slot is NOT cleared here any more. The answered branch below now runs a
        # RE-PLAN, and a transport failure there must not swallow the choice he just made —
        # the #1152 shape: clear only once a plan actually came back. The fell-back branch
        # clears immediately, exactly as before, because it consumes nothing.
        if idx is None:
            self._clarifying.pop(session_id, None)
            self._unpark(session_id)
            # Out-of-range / non-numeric: fall back to the un-refined (still-ambiguous) plan.
            # Re-stamp the goal-level build fields onto the tasks so the unresolved ambiguous
            # surface is coerced to ``unknown`` (today's no-seed path) before it could reach the
            # fleet — never the bare ``ambiguous`` sentinel. We tell the operator plainly.
            fallback_tasks = acc._thread_build_fields(
                [dict(t) for t in clarifying.tasks], clarifying.spec
            )
            note = (
                "I didn't catch which option you meant, so I'll plan it without that choice "
                "(you can /dispatch reject and start over to pick a platform)."
            )
            return self._finalize_pending(
                session_id, run_id=clarifying.run_id, repo=clarifying.repo,
                goal=clarifying.goal, tasks=fallback_tasks, spec=clarifying.spec,
                ecosystem=clarifying.ecosystem, fell_back=clarifying.fell_back,
                scaffold_ecosystem=clarifying.scaffold_ecosystem, clarified_note=note,
                coverage_blocked=clarifying.coverage_blocked,
                will_scaffold=clarifying.will_scaffold,
                intake=clarifying.intake,
            )

        chosen = options[idx]
        chosen_surface = str(chosen.get("surface", ""))
        chosen_label = str(chosen.get("label", ""))

        # Thread the chosen surface into the plan: refine the build_plan (validated against
        # its own candidates by apply_clarification) and re-stamp the goal-level fields onto
        # the already-compiled tasks. Only ``surface`` changed; _thread_build_fields just
        # .update()s each task's surface/complexity/language_hint + the loop fields
        # (goal/visual_criteria_json) — it does NOT touch the folded test block, so re-stamping
        # is safe (unlike re-running compile_prompts). Passing ``refined_spec`` (not the bare
        # plan) carries the loop fields through clarification too.
        # #1220 carrier A: validate against the menu the operator was ACTUALLY SHOWN, not
        # the model's fork list. `_parse_build_plan` attaches `candidates` only to an
        # `ambiguous` surface, and the #1174/#1197 forced question fires only when the
        # surface is NON-ambiguous — so on that path `candidates` was absent by
        # construction and this call could never change anything. He picked a platform and
        # the build ignored him, every time. Still a real allowlist (intersected with the
        # real surfaces), still deny-by-default; increment 4's own fork keeps its
        # candidates-based check because that IS its offered set.
        offered_surfaces = [
            str(o.get("surface", "")) for o in options if isinstance(o, dict)
        ]
        # Only ``build_plan`` changes; ``replace`` carries every other spec field forward —
        # assumptions AND the #819 clarifications AND the UC-010 asset_specs (a fresh
        # AcceptanceSpec(...) here previously DROPPED asset_specs/clarifications when the Inc-4
        # platform question followed a requirements clarification).
        # #1197: the operator just ANSWERED the surface question, so the clarification
        # record must say so. Refining build_plan alone left the assumed default text
        # ("a simple command-line tool …") riding into the coder's requirements block as a
        # live requirement while build_plan said `web` — and the requirement is the one the
        # coder reads. Asking a question and then discarding the answer would be a worse
        # failure than the one #1197 fixes, so the answer lands on both carriers at once.
        # #1237: pass the question he was SHOWN. On the model-flagged fork there is no
        # assumed entry to rewrite, so the answer is APPENDED as a new record — and an
        # appended answer with no question beside it is an assertion about him with no
        # provenance.
        corrected = _clarify.record_operator_surface_choice(
            clarifying.spec.clarifications, chosen_label,
            question=str(clarifying.question.get("question", "")),
        )

        # #1224 — RE-PLAN, do not relabel. The criteria, the task name, the task body AND
        # the graded exam command were all authored by `generate_plan` from the goal
        # enriched with the ASSUMED command-line default, because the platform question is
        # asked after that pass. Correcting only the requirements block left the coder with
        # four signals, three of them saying command-line — and the GRADED one among the
        # three. It is not merely at risk of following stale prose; it is REWARDED for
        # ignoring his answer, because a browser app fails `pytest test_cli.py`, and with
        # the scaffold now node a python CLI fails the build criterion too. He picks the
        # browser and gets a broken build, which is worse than the wrong app.
        #
        # So spend one more model pass with his real choice in the seed and regenerate all
        # of it. He is on a turn where he has just answered a question and is waiting
        # anyway. Relabelling was rejected as a design (LA-level call, escalated and
        # confirmed): it ships a question whose answer produces a broken build.
        replanned, refusal = await self._replan_after_surface_choice(
            clarifying, corrected, chosen_surface=chosen_surface, option_number=idx + 1,
        )
        if replanned is None:
            # Fail-closed, #1152 shape: the slot is STILL parked, so his choice is not
            # lost. Never fall back to the relabelled plan, which is precisely the
            # broken-build outcome this re-plan exists to prevent. #1237: the refusal text
            # is the callee's, because only it knows WHICH of its three exits ran — one
            # retry hint fitted to all three told him to retry a wiring gap for ever.
            return refusal
        plan_tasks, plan_spec, plan_fell_back, plan_coverage = replanned

        # The slot clears only now that a plan actually came back.
        self._clarifying.pop(session_id, None)
        self._unpark(session_id)

        # His answer wins over the fresh classification too. The re-seeded pass should
        # already resolve to the chosen surface, but deriving it from his words a second
        # time is inference; applying his ACTUAL answer is not. Same validated allowlist.
        # No `or <the pre-choice plan>` fallback here. An earlier draft kept one, and it was
        # a fallback to STALE state: after a re-plan the old build_plan describes a plan that
        # no longer exists, so falling back to it would assert a classification this plan
        # does not have. `apply_clarification` returns None only for a build_plan-less spec,
        # and None is the honest "unclassified" value — `_friendly_surface` then omits the
        # platform line rather than inventing one. (A mutation run found the dead call: it
        # could be broken with nothing going red, which is how vestigial code announces
        # itself.)
        refined_plan = acc.apply_clarification(
            plan_spec.build_plan, chosen_surface, offered=offered_surfaces
        )
        refined_spec = replace(
            plan_spec, build_plan=refined_plan, clarifications=tuple(corrected)
        )
        self._remember(clarifying.repo, corrected)
        refined_tasks = acc._thread_build_fields(
            [dict(t) for t in plan_tasks], refined_spec
        )
        # #1220 carrier B: _thread_build_fields stamps the task DICT's build-signal fields
        # and never touches prompt TEXT — the requirements block was baked in at re-plan
        # time and froze there. So the card re-rendered from the spec and showed his
        # choice, while the prompt the coder actually reads still carried the system's
        # assumed "a simple command-line tool …". Only the card was visible to him.
        # Re-derive that ONE section from the corrected clarifications.
        refined_tasks = acc.recompose_task_requirements(
            refined_tasks, refined_spec.clarifications
        )
        # #888: the fork just resolved ambiguous -> a real device surface, so RE-derive the
        # scaffold's gated ecosystem for the RESOLVED surface (a resolves-to-web fresh repo now
        # earns the honest "checks will run" disclosure instead of the blind warning). Only when
        # detection was blind AND a scaffold will run; else "" keeps today's warning.
        # #1161: the carried will_scaffold bit IS that predicate (computed at plan time
        # from the identical pair), so it replaces the second disk walk here.
        scaffold_eco = ""
        if clarifying.will_scaffold:
            scaffold_eco = acc.scaffold_gated_ecosystem(refined_plan)
        # #1237: the note is DERIVED from the build signal, never asserted alongside it.
        # "Got it — building it for: X" was emitted unconditionally, including when
        # `apply_clarification` returned None because the re-plan produced no parseable
        # build_plan — in which case the card omits the platform line, the scaffold reads
        # nothing, and the sentence above it still said the choice had been applied. A
        # control that reports a pass it did not measure is the defect class this whole arc
        # is about, and it does not get an exemption for being the fix. His answer still
        # reached the seed and the coder's requirements, so the honest note says exactly
        # that much and no more.
        if isinstance(refined_plan, dict) and refined_plan.get("surface") == chosen_surface:
            note = f"Got it — building it for: {chosen_label}."
        else:
            note = (
                f"Got it — I've written “{chosen_label}” into the build instructions. I "
                "couldn't work out a platform for the plan itself this time, so the card "
                "below won't name one — reject it and say where it should run if that "
                "looks wrong."
            )
        return self._finalize_pending(
            session_id, run_id=clarifying.run_id, repo=clarifying.repo,
            goal=clarifying.goal, tasks=refined_tasks, spec=refined_spec,
            ecosystem=clarifying.ecosystem, fell_back=plan_fell_back,
            scaffold_ecosystem=scaffold_eco, clarified_note=note,
            # #1224: the NEW plan's coverage measurement, not the pre-choice hold's. The
            # plan the old marker measured no longer exists.
            coverage_blocked=plan_coverage,
            will_scaffold=clarifying.will_scaffold,
            intake=clarifying.intake,
        )

    async def _replan_after_surface_choice(
        self, clarifying: "PendingClarification", corrected: list,
        *, chosen_surface: str = "", option_number: int = 0,
    ) -> "tuple[tuple[list, AcceptanceSpec, bool, str] | None, str]":
        """Re-run PLAN with the operator's chosen platform in the seed (#1224).

        Returns ``((tasks, spec, fell_back, coverage_blocked), "")``, or
        ``(None, <what to tell him>)`` when the plan did not come back — the caller then
        keeps the clarifying slot parked so his choice survives, and prints that text.

        The refusal text belongs HERE because only this function knows which exit ran, and
        the three are not the same event (#1237). An unwired ``plan_fn`` is not a transient
        failure: telling him to reply the same number again offered an unbounded retry loop
        whose only exit was `/dispatch reject`, so it reports the wiring gap the way every
        other site in this class does. A plan that came back NOT ok has a ``message`` saying
        why, and withholding it left him a fixed sentence while the real reason went only to
        the log — its sibling `_replan_with_requirements` has always surfaced it. A plan that
        came back ``ok`` with no tasks is neither: nothing failed, the pass simply produced
        nothing to build, and since planning is deterministic an identical retry is the same
        loop, so that exit says so and points at the two moves that change something.

        ``coverage_blocked`` comes from the NEW plan, never the pre-choice hold: it is a
        MEASUREMENT of whether this plan's behaviour checks can run, and the plan it measured
        no longer exists. Carrying the old marker forward could block approval on a finding
        about a discarded plan, or — worse — clear a block the regenerated plan warrants.

        WHY a whole extra model pass on this turn. `generate_plan` authors the criteria, the
        task name, the task body and the graded exam command from the goal it is given, and
        on this path that goal carried the system's ASSUMED surface — the platform question
        is raised after that pass, not before. Rewriting the requirements block alone
        therefore left three command-line signals against one browser signal, with the
        GRADED one on the wrong side. Re-seeding is the only way his answer becomes the
        thing the coder is built and measured against rather than an annotation beside it.

        Composed exactly like the #819 requirements re-plan: the corrected clarifications
        render through the same `compose_requirements_block` and ride the same sentinel, so
        the AO sees one goal shape, not two.

        #1237 adds ONE thing to that seed: the gradeability steer for *chosen_surface*
        (:func:`shared.fleet.clarify.compose_planning_steer`). His answer arrives here as a
        menu LABEL, and the answer it displaces on the quick path carried a clause the label
        does not — that the build's behaviour must be checkable automatically. With the
        criteria and the exam now authored from this seed, losing that clause would let an
        answered menu produce a less gradeable plan than an unanswered one. The steer rides
        beside his label rather than inside it, so nothing he is shown changes.

        Fail-closed: every failing exit returns ``None`` and NOTHING is mutated."""
        if self._plan_fn is None:
            return None, self._wiring_notice()
        block = _clarify.compose_requirements_block(corrected)
        block = _clarify.compose_planning_steer(
            block, _clarify.surface_gradeability_steer(chosen_surface)
        )
        enriched_goal = _clarify.compose_planning_goal(clarifying.goal, block)
        plan = await self._plan_fn(clarifying.repo, enriched_goal)
        retry = (
            f"Your choice wasn't lost — reply `/dispatch {option_number}` again to retry, "
            "or `/dispatch reject` to cancel."
        )
        if not plan.ok:
            logger.error(
                "Dispatch: re-plan after the platform choice failed for repo=%s "
                "(message=%s) — keeping the question parked so the answer survives.",
                clarifying.repo, plan.message,
            )
            return None, f"{plan.message}\n\n{retry}"
        if not plan.tasks or plan.spec is None:
            logger.error(
                "Dispatch: re-plan after the platform choice returned ok with nothing to "
                "build for repo=%s (tasks=%d, spec=%s) — keeping the question parked.",
                clarifying.repo, len(plan.tasks or []), plan.spec is not None,
            )
            return None, (
                "I re-planned it for that platform and got nothing back I could build "
                "from — no tasks. Replying the same number will most likely land here "
                "again, so either `/dispatch reject` and describe the build in a bit more "
                "detail, or pick the other option."
            )
        return (
            (list(plan.tasks), plan.spec, bool(plan.fell_back), plan.coverage_blocked),
            "",
        )

    @staticmethod
    def _parse_choice(choice: str, n_options: int) -> int | None:
        """Map the operator's answer (a 1-based option number as a string) to a 0-based index
        in ``[0, n_options)``, or ``None`` if it isn't a valid in-range number. Pure + total —
        never raises (a non-numeric / out-of-range / empty answer -> None -> the fallback)."""
        s = (choice or "").strip()
        if not s.isdigit():
            return None
        i = int(s)
        if 1 <= i <= n_options:
            return i - 1
        return None

    # ── EXECUTE: /dispatch approve ────────────────────────────────────────

    async def _approve(self, session_id: str) -> str:
        pending = self._pending.get(session_id)
        if pending is None:
            return "Nothing to approve — start one with  /dispatch <repo> | <goal>."
        # #1125 DEFENSE-IN-DEPTH: never fire an EMPTY plan. A plan with no tasks is not
        # something the operator can have read and approved — a plan card always renders
        # at least one step — so reaching here means the slot was corrupted rather than
        # planned. Independent review reached exactly this state by tampering with the
        # store's (then-unauthenticated) slot column; the AAD fix closes that door, and
        # this closes the room. Two independent locks, per principle 3: an approve gate
        # that trusts its input entirely is one mistake away from firing work nobody saw.
        if not pending.tasks:
            logger.error(
                "Dispatch: refusing to approve run_id=%s for session=%s — the pending "
                "plan has NO tasks, so it cannot be a plan the operator read. Discarding "
                "it (fail-closed).",
                pending.run_id, session_id,
            )
            self._pending.pop(session_id, None)
            self._unpark(session_id)
            return (
                "Something is wrong with that plan — it has no steps in it, so I won't "
                "run it. Nothing was sent to the coder. Start again with "
                "`/dispatch <project> | <what to build>`."
            )
        # #1069 S3-F: the intake coverage gate's refusal — deny-by-default at the last
        # door. The marker is set only by the intake-mode plan path (the quick path never
        # sets it) and cleared only by a revision the re-evaluation measured clean. An
        # approve while it is set would fire a build whose exam cannot verify it — the
        # GREEN that run produced would enter the record meaning nothing (the #989/#1008
        # class). Touch keeps an actively-engaged blocked plan from being reaped.
        if pending.coverage_blocked:
            self._pending.touch(session_id)
            return "Not starting this one — " + pending.coverage_blocked
        if self._execute_fn is None:
            return self._wiring_notice()

        # Persist the criteria (run-id-keyed) BEFORE firing, so the post-run report
        # survives the model-swap restart regardless of how EXECUTE goes.
        repo_path = self._repo_path(pending.repo)
        await asyncio.to_thread(
            fleet.write_acceptance_record,
            self._config, pending.run_id,
            spec_dict=pending.spec.to_dict(), repo=str(repo_path),
        )
        result = await self._execute_fn(
            session_id, pending.run_id, pending.repo, pending.tasks, pending.spec
        )
        if result.ok:
            self._pending.pop(session_id, None)  # launched — slot clears
            self._unpark(session_id)
        # On failure the slot is kept so the operator can retry /dispatch approve
        # (parked, so the retry survives a restart too).
        return result.message

    # ── REVISE: /dispatch revise <feedback>  (#820) ───────────────────────

    async def _revise(self, session_id: str, feedback: str) -> str:
        """Revise the PENDING plan from the operator's free-text *feedback* (#820).

        Only a plan AWAITING APPROVAL can be revised — a pending question is ANSWERED (not
        revised) and an executing run is STOPPED (not revised). The 14B proposes edit ops over
        the current FEATURE tasks (the dedicated acceptance-tests task is preserved verbatim and
        never offered for editing, so a revision can never drop the tests); the ruler + apply
        preserve every untouched task BYTE-FOR-BYTE (never a fresh decompose). Bounded by
        :data:`shared.fleet.revise.DEFAULT_MAX_REVISIONS`. Fail-soft: an empty/incoherent/no-op
        revision re-renders the ORIGINAL card untouched — never a lost plan, never a silent
        accept, and the revision count is NOT consumed."""
        # A question in flight takes precedence — you answer it, you don't revise it.
        if self._requirements.get(session_id) is not None:
            return (
                "Answer the question first (in your own words, or /dispatch just decide for "
                "me), then you can refine the plan."
            )
        if self._clarifying.get(session_id) is not None:
            return (
                "Answer the one question first (reply with the option number), then you can "
                "refine the plan."
            )
        pending = self._pending.get(session_id)
        if pending is None:
            # #1116: the operator's change request is prose they may have spent real
            # effort on — keep it. This is the "respond with changes" path the operator
            # hit on 2026-07-27, where the plan card had not survived a restart.
            return _keep_operator_text(
                "There's no plan waiting to change — it was built, cancelled, or timed "
                "out. Start again with `/dispatch <project> | <what to build>`.",
                feedback,
            )
        feedback = (feedback or "").strip()
        if not feedback:
            return (
                "Tell me what to change, e.g. /dispatch revise do the export first and skip "
                "the login."
            )
        if pending.revision_count >= _revise.DEFAULT_MAX_REVISIONS:
            # #1069 S3-F (review F3): a BLOCKED plan at the cap must not be told to
            # approve — approve is the one verb the marker refuses. The honest exit is
            # reject; the generic message stays byte-identical for unblocked plans.
            if pending.coverage_blocked:
                return (
                    f"You've refined this plan {pending.revision_count} times already "
                    "and its exam still can't cover it — reply /dispatch reject and "
                    "start a new dispatch with a tighter goal."
                )
            return (
                f"You've refined this plan {pending.revision_count} times already — reply "
                "/dispatch approve to build it, or /dispatch reject to start over."
            )
        if self._plan_fn is None:
            return self._wiring_notice()

        # #1069 S3-G routing: criteria/scope-flavoured feedback gets the criteria path
        # FIRST. Task-editor-first proved wrong live: the task model, handed criteria
        # feedback, can invent task ops (it deleted a real build task), and the
        # criteria path on the no-op fall-through then never ran. Fail-Closed is
        # unchanged — with the stage off, _try_criteria_revision returns None (an
        # AO-side refusal) and the task path below runs byte-identically to pre-G;
        # a None with the stage ON (no usable criteria ops) falls through the same way.
        if _feedback_targets_criteria(feedback):
            criteria_reply = await self._try_criteria_revision(
                session_id, pending, feedback
            )
            if criteria_reply is not None:
                return criteria_reply

        # Split the current plan: the revise model only sees FEATURE tasks (numbered 1..N for the
        # ops to reference); the dedicated acceptance-tests task is preserved verbatim + re-
        # attached last, so a revision can never drop the tests.
        feature_tasks = [t for t in pending.tasks if t.get("task") != acc.ACCEPTANCE_TASK_SLUG]
        test_tasks = [t for t in pending.tasks if t.get("task") == acc.ACCEPTANCE_TASK_SLUG]
        if not feature_tasks:
            return self._revise_failed(session_id, pending, "there are no editable steps", feedback)
        titles = [acc._humanize_task_name(t) for t in feature_tasks]

        # The revise request rides the goal (feedback + current titles) over the SAME plan seam
        # #819 uses; the AO runs the revise model call and returns edit ops in plan.revision.
        revise_goal = _revise.compose_revision_goal(pending.goal, feedback, titles)
        plan = await self._plan_fn(pending.repo, revise_goal)
        if not plan.ok:
            # Knob off (Fail-Closed) / transport error — surface the honest message; the pending
            # plan is left completely intact (revise never mutates until it fully succeeds).
            return plan.message
        ops = _revise.ops_from_dicts(plan.revision)
        # Task dicts carry the plan-time RESOLVED repo path (decompose_request mints
        # ``str(projects_dir / repo)``) — a minted add/revise task must match, or the
        # execute-time forbidden-root guard refuses the bare name resolved against the
        # AO process cwd (~/BlarAI).
        outcome = _revise.apply_revision_ops(
            feature_tasks, ops, repo=str(self._repo_path(pending.repo))
        )
        if outcome is None or not outcome.changed:
            # Criteria-flavoured feedback already had its shot above (criteria-first
            # routing); every remaining fall-through renders the honest pre-G failure
            # message, which is the slice's dormant-default bar.
            return self._revise_failed(session_id, pending, None, feedback)

        # Thread build fields onto the revised feature tasks (idempotent for the kept ones — the
        # spec is unchanged), then re-attach the preserved acceptance-tests task LAST.
        revised_features = acc._thread_build_fields(
            [dict(t) for t in outcome.tasks], pending.spec
        )
        revised_tasks = revised_features + [dict(t) for t in test_tasks]

        # #1069 S3-F: a revision is the operator's UNBLOCK path, so the coverage marker is
        # RE-EVALUATED against the revised plan — a blocked card whose block could never
        # clear would be a dead end wearing an open door. Recomputed ONLY when the plan
        # arrived blocked (the quick path never sets the marker, so it never pays this):
        # the same deterministic #989 measurement, run gateway-side over the revised
        # feature tasks and the exam still riding the preserved acceptance task. An exam
        # that cannot be found keeps the block — absence must never read as coverage.
        coverage_blocked = pending.coverage_blocked
        unblocked_note = ""
        if pending.coverage_blocked:
            oracle_rel, oracle_code = _riding_job_oracle(revised_tasks)
            if oracle_rel and oracle_code:
                # Unblock requires MEASURED-CLEAN (review F1/F2): the warning helper's
                # "" also means not-computable and derivation-crash, and clearing the
                # marker on an UNMEASURED result would print a false affirmative on the
                # exact control this seam exists to hold. Unmeasurable ⇒ the ORIGINAL
                # marker stands (there is no new gap text to name, and absence must
                # never read as coverage).
                if acc._coverage_measured_clean(
                    revised_features, oracle_rel, oracle_code
                ):
                    coverage_blocked = ""
                    unblocked_note = (
                        "That change closed the coverage gap — the exam now covers every "
                        "step of the plan, and `/dispatch approve` is available."
                    )
                else:
                    warning = acc._plan_contract_coverage_warning(
                        revised_features, oracle_rel, oracle_code
                    )
                    if warning:
                        coverage_blocked = (
                            acc._coverage_blocked_message_orphan_only(warning)
                            if acc._coverage_orphan_only(
                                revised_features, oracle_rel, oracle_code)
                            else acc._coverage_blocked_message(warning)
                        )

        # The feedback rides the spec block (#820 point 3): recorded as a clarification so it
        # shows on the card + persists in the acceptance record (available to the report),
        # assumed=False (the operator volunteered it). Cumulative across revisions.
        fb_clar = {"question": "(your change request)", "answer": feedback,
                   "assumed": False, "remembered": False}
        new_spec = replace(
            pending.spec, clarifications=tuple(pending.spec.clarifications) + (fb_clar,)
        )

        # Each successful revision is a NEW pending plan (the old one tombstoned — _finalize_
        # pending rewrites the single slot with a fresh TTL and the incremented count) with the
        # SAME run_id so status/reports line up. The delta LEADS the re-rendered card.
        delta = _revise.render_revision_delta(outcome, feedback)
        if unblocked_note:
            delta = f"{unblocked_note}\n\n{delta}"
        return self._finalize_pending(
            session_id, run_id=pending.run_id, repo=pending.repo, goal=pending.goal,
            tasks=revised_tasks, spec=new_spec, ecosystem=pending.ecosystem, fell_back=False,
            scaffold_ecosystem=pending.scaffold_ecosystem,
            clarified_note=delta, revision_count=pending.revision_count + 1,
            coverage_blocked=coverage_blocked,
            will_scaffold=pending.will_scaffold,
            intake=pending.intake,
        )

    async def _try_criteria_revision(
        self, session_id: str, pending: PendingDispatch, feedback: str
    ) -> "str | None":
        """#1069 S3-G: the REAL path behind the honest #1055 message — when task-revision
        yielded nothing and the feedback reads as a criteria/scope change, ask the AO for
        criteria edit ops (over the existing plan seam, behind the criteria-revise
        sentinel) and apply them to the pending spec. Returns the rendered reply on
        success, ``None`` to fall through to the honest message — the stage off is an
        AO-side Fail-Closed refusal, so the dormant default's operator-visible behaviour
        is byte-identical to pre-G.

        What CANNOT change through here, by construction: the compiled task prompts and
        the riding exam (the folded test block consumes machine tiers only, and those are
        keep-only in the shared ruler — :func:`shared.fleet.revise.apply_criteria_revision_ops`);
        the coverage marker (contracts and exam untouched ⇒ the measurement could not
        move, so it carries verbatim); and the revision budget (shared with task
        revisions — the caller already enforced the cap)."""
        if self._plan_fn is None:
            return None
        rows = [
            {"id": c.id, "text": c.text, "tier": c.tier, "check": c.check}
            for c in pending.spec.criteria
        ]
        if not rows:
            return None
        goal = _revise.compose_criteria_revision_goal(pending.goal, feedback, rows)
        plan = await self._plan_fn(pending.repo, goal)
        if not plan.ok or not getattr(plan, "criteria_revision", None):
            return None
        ops = _revise.criteria_ops_from_dicts(plan.criteria_revision)
        outcome = _revise.apply_criteria_revision_ops(rows, ops)
        if outcome is None or not outcome.changed:
            # Review F2: the WALL-ONLY case — the stage is provably ON (ops came back)
            # and the operator's feedback aimed only at protected machine rows. The
            # generic "criteria can't be edited" message would be FALSE here; the honest
            # reply is the protected report itself, budget unconsumed, plan untouched.
            # Every other fall-through (stage off, no usable ops) stays None, so the
            # dormant world's reply is byte-identical.
            if outcome is not None and outcome.protected_titles:
                self._pending.touch(session_id)
                self._last_action[session_id] = "dispatch_plan"
                note = _revise.render_criteria_revision_delta(outcome, feedback)
                preview = acc.render_criteria_preview(
                    pending.spec, ecosystem=pending.ecosystem, tasks=pending.tasks,
                    revise_hint=self._revise_hint(pending.revision_count),
                    scaffold_ecosystem=pending.scaffold_ecosystem,
                    coverage_blocked=pending.coverage_blocked,
                    will_scaffold=pending.will_scaffold,
                )
                preview = self._close_card(
                    preview, intake=pending.intake,
                    revision_count=pending.revision_count,
                    coverage_blocked=pending.coverage_blocked,
                )
                return note + "\n" + preview
            return None
        new_criteria = tuple(
            acc.AcceptanceCriterion(
                id=str(r.get("id", "")), text=str(r.get("text", "")),
                tier=str(r.get("tier", "")), check=str(r.get("check", "")),
            )
            for r in outcome.criteria
        )
        new_spec = replace(pending.spec, criteria=new_criteria)
        # Floors re-injected + realism guard re-applied — deterministic, idempotent, the
        # second half of the safety asymmetry: a criteria revision cannot strip a
        # deterministic floor (the machine wall auto-kept it already; this is the
        # independent second lock), and a reworded claim naming no check cannot hold a
        # machine tier. Reaching this line required the AO's intake gates to be on, so
        # applying the S1 rulers here is flag-correct.
        new_spec = acc._ensure_delivery_floor(new_spec)
        new_spec = acc._apply_realism_guard(new_spec)
        # #1165 M5: the operator-assets MACHINE floor re-injects with its siblings —
        # the second independent lock behind the keep-only wall. It derives from the
        # pending spec's own manifest (replace() carried it through the revision), so
        # a manifest-less plan is a no-op and no flag needs re-checking here. The
        # VISUAL asset criterion is deliberately NOT re-injected: operator-tier
        # judgment stays droppable (the S3-G posture, design review F8).
        new_spec = acc._ensure_operator_assets_floor(new_spec)
        # The feedback rides the spec block exactly as a task-revision's does (#820 point
        # 3): shown on the card, persisted in the acceptance record at approve.
        fb_clar = {"question": "(your criteria change request)", "answer": feedback,
                   "assumed": False, "remembered": False}
        new_spec = replace(
            new_spec, clarifications=tuple(new_spec.clarifications) + (fb_clar,)
        )
        delta = _revise.render_criteria_revision_delta(outcome, feedback)
        # Review F1: RE-THREAD the build fields onto the stored tasks with the REVISED
        # spec — tasks carry visual_criteria_json, and the VLM design loop critiques
        # against it, so a rescoped visual criterion must reach the build or the
        # operator approves one checklist while the loop optimises another. Safe by the
        # clarification path's own precedent: _thread_build_fields .update()s the
        # visual/goal/build-signal stamps and never touches the folded test block, so
        # the machine-tier freeze is unaffected.
        rethreaded_tasks = acc._thread_build_fields(
            [dict(t) for t in pending.tasks], new_spec
        )
        return self._finalize_pending(
            session_id, run_id=pending.run_id, repo=pending.repo, goal=pending.goal,
            tasks=rethreaded_tasks, spec=new_spec,
            ecosystem=pending.ecosystem, fell_back=False,
            scaffold_ecosystem=pending.scaffold_ecosystem,
            clarified_note=delta, revision_count=pending.revision_count + 1,
            coverage_blocked=pending.coverage_blocked,
            will_scaffold=pending.will_scaffold,
            intake=pending.intake,
        )

    def _revise_failed(
        self,
        session_id: str,
        pending: PendingDispatch,
        reason: "str | None",
        feedback: str = "",
    ) -> str:
        """Fail-soft (#820): re-render the ORIGINAL plan card with an honest "couldn't apply
        that" note. The pending plan is UNCHANGED — not tombstoned, revision count not consumed —
        so the operator can rephrase, approve, or reject. Touches the slot so an actively-engaged
        plan isn't reaped mid-refine.

        #1055: when the no-op is because the feedback asked to change CRITERIA or SCOPE — which
        revise structurally cannot do (it edits tasks, never the goal-set criteria) — say so
        plainly and route to reject + re-dispatch, instead of "describe it differently", which
        for a criteria change can never succeed no matter the wording."""
        self._pending.touch(session_id)
        self._last_action[session_id] = "dispatch_plan"
        # Only the genuine no-op path (reason is None) gets the criteria message.
        # A structural reason like "there are no editable steps" is accurate and
        # kept — the criteria branch must not discard it (pre-merge review F3).
        if reason is None and _feedback_targets_criteria(feedback):
            note = (
                "I couldn't change that through revise — revise edits the plan's STEPS, but that "
                "reads like a change to the acceptance criteria or scope (what the build is "
                "checked against), which are set by the goal and can't be edited on a pending "
                "plan. To change the scope or criteria, reply /dispatch reject and start a new "
                "dispatch with a tighter goal. Or /dispatch approve to build the plan as shown."
            )
            preview = acc.render_criteria_preview(
                pending.spec, ecosystem=pending.ecosystem, tasks=pending.tasks,
                revise_hint=self._revise_hint(pending.revision_count),
                scaffold_ecosystem=pending.scaffold_ecosystem,
                coverage_blocked=pending.coverage_blocked,
                will_scaffold=pending.will_scaffold,
            )
            preview = self._close_card(
                preview, intake=pending.intake, revision_count=pending.revision_count,
                coverage_blocked=pending.coverage_blocked,
            )
            return note + "\n\n" + preview
        note = (
            "I couldn't turn that into a change to the plan"
            + (f" ({reason})" if reason else "")
            + " — the plan is unchanged. Try describing the change differently, or reply "
            "/dispatch approve or /dispatch reject."
        )
        preview = acc.render_criteria_preview(
            pending.spec, ecosystem=pending.ecosystem, tasks=pending.tasks,
            revise_hint=self._revise_hint(pending.revision_count),
            scaffold_ecosystem=pending.scaffold_ecosystem,
            coverage_blocked=pending.coverage_blocked,
            will_scaffold=pending.will_scaffold,
        )
        preview = self._close_card(
            preview, intake=pending.intake, revision_count=pending.revision_count,
            coverage_blocked=pending.coverage_blocked,
        )
        return note + "\n\n" + preview

    # ── /dispatch reject ──────────────────────────────────────────────────

    def _reject(self, session_id: str) -> str:
        # Reject cancels the whole dispatch at ANY pre-execute phase: an awaiting-answer
        # requirements clarification (#819), an awaiting-answer platform clarification
        # (increment 4), OR an awaiting-approval plan. Clear all three slots.
        requirements = self._requirements.pop(session_id, None)
        clarifying = self._clarifying.pop(session_id, None)
        pending = self._pending.pop(session_id, None)
        self._unpark(session_id)
        if pending is None and clarifying is None and requirements is None:
            return "Nothing to reject — there's no dispatch waiting."
        if pending is not None:
            goal = pending.goal
        elif clarifying is not None:
            goal = clarifying.goal
        else:
            goal = requirements.goal
        return (
            f"Cancelled the pending dispatch (“{goal}”). Nothing was sent to "
            "the coder."
        )

    # ── /dispatch stop ────────────────────────────────────────────────────

    def _stop(self, session_id: str) -> str:
        """Abort an APPROVED, EXECUTING run by tripping the driver's cancel sentinel.

        The cross-process stop MECHANISM already exists: the detached swap driver's CODE
        loop checks ``cancel_requested`` (``cancel_path(config).exists()``) at each task
        boundary and, when set, breaks into its clean NEVER-ZERO teardown — the 30B is
        unloaded, the 14B is restored, and the in-progress task PARKS on its ``agent/<slug>``
        branch (the worktree sweep is force-FREE, so committed-but-unmerged work survives —
        non-destructive). This handler is the missing TRIGGER: it writes that sentinel.

        ``stop`` is distinct from ``reject``: ``reject`` discards a PENDING (planned, not-yet-
        approved) plan that never reached the coder, so it is NOT conflated here — a stop with
        only a pending slot and no live run reports "nothing running" and writes nothing. We
        gate on the swap-state phase: a run is ACTIVE iff a non-terminal swap-state record
        exists (``is_in_flight`` — the SAME gate the boot reconciler uses; terminal =
        ``PHASE_IDLE`` / ``PHASE_RECOVERED``). With no in-flight run we must write nothing, so
        a stale sentinel can never poison the NEXT dispatch.

        Sentinel cleanup is NOT this handler's job and needs no new code: the driver does not
        remove the sentinel after honoring it, but ``prepare_and_launch_swap`` clears it
        (``_rm(cancel_path(config))``) at the START of every EXECUTE ("a prior run's cancel
        must not abort this one"). So even the boundary case — a run finishes on its own
        between our in-flight read and our write — is self-correcting: the orphaned sentinel
        is wiped before the next run's CODE loop ever reads it. We reuse that existing cleanup
        rather than inventing a second one.
        """
        from shared.fleet import swap_state as ss
        from shared.fleet.swap_ops import cancel_path, swap_state_path

        state = ss.read_swap_state(swap_state_path(self._config))
        if not ss.is_in_flight(state):
            return "Nothing is running to stop."

        path = cancel_path(self._config)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("stop\n", encoding="utf-8")
        return (
            "Stopping the run — halting the coder and restoring the 14B; any partial work "
            "stays parked on its branch. This can take a moment to take effect."
        )

    # ── /dispatch status [run_id] ─────────────────────────────────────────

    async def _status(self, run_id: str) -> str:
        rid = run_id.strip()
        if not rid:
            rid = await asyncio.to_thread(fleet.latest_run_id, config=self._config) or ""
        if not rid:
            return "No dispatches yet. Start one with  /dispatch <repo> | <goal>."
        return await asyncio.to_thread(self._assemble_status, rid)

    def _assemble_status(self, rid: str) -> str:
        """The honest report, PREFIXED with the swap-progress trail (#670) when present.
        The operator is blind during the swap (the WinUI closes when the launcher steps
        aside), so /dispatch status is where they read what happened after the box returns:
        stepping aside -> 30B loading -> gate pass/abort -> fleet running -> swapping back ->
        14B restored. Runs in a thread (file reads)."""
        from shared.fleet.swap_ops import read_swap_progress

        body = self._assemble_status_body(rid)
        progress = read_swap_progress(self._config, rid)
        if progress.strip():
            return "What happened during the swap:\n" + progress.rstrip() + "\n\n" + body
        return body

    def _assemble_status_body(self, rid: str) -> str:
        """The acceptance report (when a record exists) or the raw summary fallback."""
        record = fleet.read_acceptance_record(self._config, rid)
        if record is None:
            # A run with no acceptance record (predates the layer / wiring) — fall back
            # to the deterministic summary report.
            return fleet.read_summary(config=self._config, run_id=rid).message

        spec = AcceptanceSpec.from_dict(record.get("spec", {}))
        repo = str(record.get("repo", ""))
        summary_path = self._config.runs_dir / rid / "SUMMARY.txt"
        try:
            summary_text = summary_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return (
                f"Run {rid} is approved and queued, but has no results yet — it's still "
                "running, or the coder model hasn't started. Check back with "
                f"/dispatch status {rid}."
            )

        task_reports = []
        for path in fleet.summary_report_paths(summary_text):
            try:
                task_reports.append(
                    acc.parse_task_report(Path(path).read_text(encoding="utf-8", errors="replace"))
                )
            except OSError:
                pass  # a missing per-task report -> that task contributes no signal
        repo_path = Path(repo) if repo else self._config.runs_dir / rid
        return acc.render_acceptance_report(
            spec, task_reports=task_reports, repo=repo_path
        )

    # ── helpers ───────────────────────────────────────────────────────────

    def _repo_path(self, repo: str) -> Path:
        rp = Path(repo)
        return rp if rp.is_absolute() else (self._config.projects_dir / repo)

    def _wiring_notice(self) -> str:
        return (
            "Coding dispatch is enabled, but the plan/execute wiring to the assistant "
            "isn't connected yet — that's the on-hardware go-live step. Nothing was run."
        )
