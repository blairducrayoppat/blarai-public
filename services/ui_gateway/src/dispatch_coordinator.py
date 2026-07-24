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
from typing import Awaitable, Callable

from shared.fleet import acceptance as acc
from shared.fleet import clarify as _clarify
from shared.fleet import dispatch as fleet
from shared.fleet import revise as _revise
from shared.fleet.acceptance import AcceptanceSpec, PlanResult
from shared.ttl_dict import TtlDict

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
_CRITERIA_SCOPE_SIGNALS = re.compile(
    r"\b(?:criteri(?:a|on)|requirements?|scope|"
    r"(?:drop|remove|delete|cut|get\s+rid\s+of)\s+(?:the\s+)?goal)\b",
    re.IGNORECASE,
)


def _feedback_targets_criteria(feedback: str) -> bool:
    """True when revise feedback reads as a criteria/scope change, not a task edit."""
    return bool(_CRITERIA_SCOPE_SIGNALS.search(feedback or ""))

_PREFIX = "/dispatch"

#: ``plan_fn(repo, goal) -> PlanResult`` — runs the 14B PLAN (decompose + criteria +
#: ruler) AO-side. Injected; the real wiring is an AO IPC round-trip (deferred go-live).
PlanFn = Callable[[str, str], Awaitable[PlanResult]]
#: ``execute_fn(session_id, run_id, repo, tasks, spec) -> DispatchResult`` — fires EXECUTE
#: (enqueue + swap-or-direct-run + step-aside). Injected; real wiring deferred to go-live.
ExecuteFn = Callable[[str, str, str, list, AcceptanceSpec], Awaitable[fleet.DispatchResult]]


@dataclass(frozen=True)
class DispatchCommand:
    kind: str  # "run"|"create"|"approve"|"reject"|"status"|"stop"|"choose"|"answer"|"decide"|"revise"
    repo: str = ""
    goal: str = ""
    run_id: str = ""
    choice: str = ""  # the operator's answer to a clarifying question (a 1-based option number)
    answer: str = ""  # #819: the operator's free-text answer to the requirements questions
    feedback: str = ""  # #820: the operator's free-text plan-revision feedback


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


def parse_dispatch_command(text: str) -> DispatchCommand | None:
    """Parse a ``/dispatch …`` line, or return ``None`` for a normal prompt.

    Increment 4: a bare-number line (``/dispatch 2``) or ``/dispatch use 2`` / ``choose 2`` is
    parsed as a ``choose`` command (the answer to a clarifying question). A bare integer is
    unambiguous — it is never a real repo|goal — so it is safe to special-case; it is only
    ACTED ON when a clarification is actually pending for the session (handled in
    :meth:`DispatchCoordinator.handle_command`), otherwise it reports there's nothing to answer.
    """
    s = text.strip()
    if s.lower() != _PREFIX and not s.lower().startswith(_PREFIX + " "):
        return None
    rest = s[len(_PREFIX):].strip()
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
    ) -> None:
        self._config = config
        self._enabled = bool(enabled)
        self._plan_fn = plan_fn
        self._execute_fn = execute_fn
        self._mint_run_id = mint_run_id
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
                text = command.answer or command.goal or command.choice or command.feedback
                return await self._answer_requirements(session_id, text)
            if command.kind in ("answer", "decide"):
                return (
                    "There's no question waiting. Start a dispatch with "
                    "/dispatch <repo> | <goal>."
                )
            if command.kind == "status":
                return await self._status(command.run_id)
            if command.kind == "approve":
                return await self._approve(session_id)
            if command.kind == "revise":
                return await self._revise(session_id, command.feedback)
            if command.kind == "reject":
                return self._reject(session_id)
            if command.kind == "stop":
                return await asyncio.to_thread(self._stop, session_id)
            if command.kind == "choose":
                return self._choose(session_id, command.choice)
            if command.kind == "create":
                return await self._create_and_plan(
                    session_id, command.repo, command.goal
                )
            return await self._plan(session_id, command.repo, command.goal)
        except Exception as exc:  # noqa: BLE001 — surface, never crash the turn
            logger.error("Dispatch command %r failed for session=%s: %s",
                         command.kind, session_id, exc, exc_info=True)
            return f"Dispatch failed (Fail-Closed): {exc}"

    # ── PLAN: /dispatch <repo> | <goal> ───────────────────────────────────

    async def _plan(self, session_id: str, repo: str, goal: str) -> str:
        if not repo or not goal:
            return (
                "Usage: /dispatch <repo> | <goal>  —  e.g. "
                "/dispatch calc | a calculator an 8-year-old can use"
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

        # FIRST pass — the plain goal (no requirements yet). The AO may return requirements-
        # clarification QUESTIONS (#819) instead of a plan when the goal is underspecified and
        # the stage is enabled; a sufficient goal (or a battery card / clarify off) returns a
        # plan directly and the flow is byte-identical to before.
        plan = await self._plan_fn(repo, goal)
        if not plan.ok:
            return plan.message
        if plan.questions:
            run_id = self._mint_run_id()
            self._requirements[session_id] = PendingRequirements(
                run_id=run_id,
                repo=repo,
                goal=goal,
                questions=list(plan.questions),
                submitted_at=datetime.now(timezone.utc).isoformat(),
            )
            return self._render_requirements_questions(goal, plan.questions)

        return self._finalize_plan(session_id, repo=repo, goal=goal, plan=plan)

    # ── the requirements-clarification answer (#819) ──────────────────────

    async def _answer_requirements(self, session_id: str, text: str) -> str:
        """Consume the operator's free-text answer to the requirements questions, then re-plan
        with those answers threaded in. A "just decide for me" reply routes to the defaults; a
        blank reply re-asks (never a silent proceed). Bounded — this slot clears before the
        re-plan, so there is at most ONE requirements turn per dispatch."""
        pending_req = self._requirements.get(session_id)
        if pending_req is None:
            return (
                "There's no question waiting. Start a dispatch with "
                "/dispatch <repo> | <goal>."
            )
        answer = (text or "").strip()
        if not answer:
            return (
                "I didn't catch an answer — tell me in your own words with "
                "/dispatch <your answer>, or reply /dispatch just decide for me."
            )
        if _clarify.is_decide_for_me(answer):
            return await self._decide_requirements(session_id)
        questions = _clarify.questions_from_dicts(pending_req.questions)
        clarifications = _clarify.answered_from_free_text(questions, answer)
        self._requirements.pop(session_id, None)  # leave the sub-state (bounded to one turn)
        return await self._replan_with_requirements(session_id, pending_req, clarifications)

    async def _decide_requirements(self, session_id: str) -> str:
        """The "just decide for me" escape hatch: self-answer every asked question with its
        per-axis default and re-plan. The defaults are RECORDED as assumptions on the plan card
        (``assumed=True``), so the operator sees what was chosen and can reject a wrong one."""
        pending_req = self._requirements.get(session_id)
        if pending_req is None:
            return (
                "There's no question waiting. Start a dispatch with "
                "/dispatch <repo> | <goal>."
            )
        questions = _clarify.questions_from_dicts(pending_req.questions)
        clarifications = _clarify.decide_defaults(questions)
        self._requirements.pop(session_id, None)
        return await self._replan_with_requirements(session_id, pending_req, clarifications)

    async def _replan_with_requirements(
        self, session_id: str, pending_req: PendingRequirements, clarifications: list
    ) -> str:
        """Re-run PLAN with the clarified requirements threaded into the goal, then finalize the
        approval preview (attaching the clarifications to the spec for the plan card + record).
        The ``run_id`` minted for the question set is carried through so status/reports line up."""
        if self._plan_fn is None:
            return self._wiring_notice()
        block = _clarify.compose_requirements_block(clarifications)
        enriched_goal = _clarify.compose_planning_goal(pending_req.goal, block)
        plan = await self._plan_fn(pending_req.repo, enriched_goal)
        if not plan.ok:
            return plan.message
        # The re-plan carries requirements, so the AO suppresses clarify — but never loop even
        # if it somehow returned questions again: _finalize_plan ignores them and proceeds.
        return self._finalize_plan(
            session_id, repo=pending_req.repo, goal=pending_req.goal, plan=plan,
            clarifications=clarifications, run_id=pending_req.run_id,
        )

    def _render_requirements_questions(self, goal: str, questions: list) -> str:
        """The operator-facing CLARIFY turn (#819): the goal + a short numbered list of the
        plain-language questions + how to answer. Novice-friendly — one free-text reply, or the
        one-tap "just decide for me" escape. The system asks; the operator answers in words."""
        lines = [f"Before I build “{goal}”, a few quick questions so I get it right:", ""]
        for i, q in enumerate(questions, start=1):
            text = q.get("question", "") if isinstance(q, dict) else str(q)
            lines.append(f"  {i}. {text}")
        lines += [
            "",
            "Answer in your own words — reply `/dispatch <your answers>` (one message is fine).",
            "Or reply `/dispatch just decide for me` and I'll choose sensible defaults.",
            "Or `/dispatch reject` to cancel.",
        ]
        return "\n".join(lines)

    def _finalize_plan(
        self, session_id: str, *, repo: str, goal: str, plan: PlanResult,
        clarifications: "list | tuple" = (), run_id: str | None = None,
    ) -> str:
        """Shared PLAN-to-preview tail: detect ecosystem, run the Inc-4 platform question if the
        14B flagged an ambiguous fork, else render the approval preview. Attaches any #819
        requirements clarifications to the spec first (display + record) — this is the single
        place both the no-question path and the post-requirements re-plan converge."""
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
        scaffold_ecosystem = ""
        if ecosystem == "unknown" and acc.repo_will_scaffold(repo_path):
            scaffold_ecosystem = acc.scaffold_gated_ecosystem(spec.build_plan)

        # Increment 4 — the confidence-gated clarifying question. If (and ONLY if) the 14B
        # flagged a genuinely ambiguous platform fork, the SYSTEM (never the model) asks ONE
        # curated question BEFORE the normal approval preview. resolve_clarifying_question is
        # the single gate: it returns None for a clear / unknown / absent surface (or an
        # unmapped fork), in which case the flow is EXACTLY today's — no extra turn.
        question = acc.resolve_clarifying_question(spec.build_plan)
        if question is not None:
            self._clarifying[session_id] = PendingClarification(
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
            )
            return self._render_clarifying_question(goal, question)

        return self._finalize_pending(
            session_id, run_id=rid, repo=repo, goal=goal,
            tasks=plan.tasks, spec=spec, ecosystem=ecosystem,
            scaffold_ecosystem=scaffold_ecosystem, fell_back=plan.fell_back,
        )

    # ── CREATE + PLAN: /dispatch new <name> | <goal>  (#712) ──────────────

    async def _create_and_plan(self, session_id: str, name: str, goal: str) -> str:
        """Create a new git project, then run the normal PLAN on it (one motion).

        The "start a new project" flow for a non-git operator: ``create_project``
        does the git plumbing (init + scaffold + first commit on ``main``), then
        we delegate to :meth:`_plan` on the freshly-created slug — which now finds
        ``.git`` and proceeds straight to the criteria preview / approval (the
        not-found offer is skipped). Fail-Closed: a creation failure surfaces the
        clear message and nothing is planned.
        """
        if not name or not goal:
            return (
                "Usage: /dispatch new <name> | <goal>  —  e.g. "
                "/dispatch new kid-calc | a calculator a kid can use"
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
            fleet.create_project, name, config=self._config, goal=goal
        )
        if not result.ok:
            return result.message
        # Created — PLAN on the fresh repo (slug as actually created).
        plan_reply = await self._plan(session_id, result.name, goal)
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

    def _finalize_pending(
        self, session_id: str, *, run_id: str, repo: str, goal: str,
        tasks: list, spec: AcceptanceSpec, ecosystem: str, fell_back: bool,
        scaffold_ecosystem: str = "", clarified_note: str = "", revision_count: int = 0,
    ) -> str:
        """Store the approval-pending dispatch + render the normal PLAN preview.

        Shared by the no-question path (today's flow, unchanged), the post-clarification path
        (after the operator's answer threaded a real surface into the plan), and the #820 revise
        path. The optional ``clarified_note`` leads the preview when we got here via a clarifying
        answer or a revision (so the operator sees what was resolved / the CHANGED-vs-KEPT delta).
        ``revision_count`` (#820) rides onto the stored plan and drives the revise-hint footer;
        a fresh plan is 0 (offers the verb) — a plan at the cap renders approve/reject only."""
        self._pending[session_id] = PendingDispatch(
            run_id=run_id,
            repo=repo,
            goal=goal,
            tasks=tasks,
            spec=spec,
            ecosystem=ecosystem,
            scaffold_ecosystem=scaffold_ecosystem,
            submitted_at=datetime.now(timezone.utc).isoformat(),
            revision_count=revision_count,
        )
        # Signal the gateway to attach Approve/Reject buttons to this preview (#712).
        self._last_action[session_id] = "dispatch_plan"
        preview = acc.render_criteria_preview(
            spec, ecosystem=ecosystem, tasks=tasks, revise_hint=self._revise_hint(revision_count),
            scaffold_ecosystem=scaffold_ecosystem,
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

    def _choose(self, session_id: str, choice: str) -> str:
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
            return (
                "There's no question waiting. Start a dispatch with "
                "/dispatch <repo> | <goal>."
            )

        options = clarifying.question.get("options", [])
        idx = self._parse_choice(choice, len(options))
        # Clear the clarification slot now — either way we leave this sub-state (answered or
        # fell back); this is what bounds it to a single turn.
        self._clarifying.pop(session_id, None)

        if idx is None:
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
        refined_plan = acc.apply_clarification(clarifying.spec.build_plan, chosen_surface)
        # Only ``build_plan`` changes; ``replace`` carries every other spec field forward —
        # assumptions AND the #819 clarifications AND the UC-010 asset_specs (a fresh
        # AcceptanceSpec(...) here previously DROPPED asset_specs/clarifications when the Inc-4
        # platform question followed a requirements clarification).
        refined_spec = replace(clarifying.spec, build_plan=refined_plan)
        refined_tasks = acc._thread_build_fields(
            [dict(t) for t in clarifying.tasks], refined_spec
        )
        # #888: the fork just resolved ambiguous -> a real device surface, so RE-derive the
        # scaffold's gated ecosystem for the RESOLVED surface (a resolves-to-web fresh repo now
        # earns the honest "checks will run" disclosure instead of the blind warning). Only when
        # detection was blind AND a scaffold will run; else "" keeps today's warning.
        scaffold_eco = ""
        if clarifying.ecosystem == "unknown" and acc.repo_will_scaffold(
            self._repo_path(clarifying.repo)
        ):
            scaffold_eco = acc.scaffold_gated_ecosystem(refined_plan)
        note = f"Got it — building it for: {chosen_label}."
        return self._finalize_pending(
            session_id, run_id=clarifying.run_id, repo=clarifying.repo,
            goal=clarifying.goal, tasks=refined_tasks, spec=refined_spec,
            ecosystem=clarifying.ecosystem, fell_back=clarifying.fell_back,
            scaffold_ecosystem=scaffold_eco, clarified_note=note,
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
        # On failure the slot is kept so the operator can retry /dispatch approve.
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
            return "Nothing to revise yet — start one with  /dispatch <repo> | <goal>."
        feedback = (feedback or "").strip()
        if not feedback:
            return (
                "Tell me what to change, e.g. /dispatch revise do the export first and skip "
                "the login."
            )
        if pending.revision_count >= _revise.DEFAULT_MAX_REVISIONS:
            return (
                f"You've refined this plan {pending.revision_count} times already — reply "
                "/dispatch approve to build it, or /dispatch reject to start over."
            )
        if self._plan_fn is None:
            return self._wiring_notice()

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
            return self._revise_failed(session_id, pending, None, feedback)

        # Thread build fields onto the revised feature tasks (idempotent for the kept ones — the
        # spec is unchanged), then re-attach the preserved acceptance-tests task LAST.
        revised_features = acc._thread_build_fields(
            [dict(t) for t in outcome.tasks], pending.spec
        )
        revised_tasks = revised_features + [dict(t) for t in test_tasks]

        # The feedback rides the spec block (#820 point 3): recorded as a clarification so it
        # shows on the card + persists in the acceptance record (available to the report),
        # assumed=False (the operator volunteered it). Cumulative across revisions.
        fb_clar = {"question": "(your change request)", "answer": feedback, "assumed": False}
        new_spec = replace(
            pending.spec, clarifications=tuple(pending.spec.clarifications) + (fb_clar,)
        )

        # Each successful revision is a NEW pending plan (the old one tombstoned — _finalize_
        # pending rewrites the single slot with a fresh TTL and the incremented count) with the
        # SAME run_id so status/reports line up. The delta LEADS the re-rendered card.
        delta = _revise.render_revision_delta(outcome, feedback)
        return self._finalize_pending(
            session_id, run_id=pending.run_id, repo=pending.repo, goal=pending.goal,
            tasks=revised_tasks, spec=new_spec, ecosystem=pending.ecosystem, fell_back=False,
            scaffold_ecosystem=pending.scaffold_ecosystem,
            clarified_note=delta, revision_count=pending.revision_count + 1,
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
