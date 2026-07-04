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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable

from shared.fleet import acceptance as acc
from shared.fleet import dispatch as fleet
from shared.fleet.acceptance import AcceptanceSpec, PlanResult

logger = logging.getLogger(__name__)

_PREFIX = "/dispatch"

#: ``plan_fn(repo, goal) -> PlanResult`` — runs the 14B PLAN (decompose + criteria +
#: ruler) AO-side. Injected; the real wiring is an AO IPC round-trip (deferred go-live).
PlanFn = Callable[[str, str], Awaitable[PlanResult]]
#: ``execute_fn(session_id, run_id, repo, tasks, spec) -> DispatchResult`` — fires EXECUTE
#: (enqueue + swap-or-direct-run + step-aside). Injected; real wiring deferred to go-live.
ExecuteFn = Callable[[str, str, str, list, AcceptanceSpec], Awaitable[fleet.DispatchResult]]


@dataclass(frozen=True)
class DispatchCommand:
    kind: str  # "run" | "create" | "approve" | "reject" | "status" | "stop" | "choose"
    repo: str = ""
    goal: str = ""
    run_id: str = ""
    choice: str = ""  # the operator's answer to a clarifying question (a 1-based option number)


@dataclass(frozen=True)
class PendingDispatch:
    """The session's single pending (planned, not-yet-approved) dispatch."""

    run_id: str
    repo: str
    goal: str
    tasks: list = field(default_factory=list)  # compiled {repo,task,prompt}
    spec: AcceptanceSpec = field(default_factory=lambda: AcceptanceSpec(goal=""))
    ecosystem: str = "unknown"
    submitted_at: str = ""


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
    fell_back: bool = False
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
        self._pending: dict[str, PendingDispatch] = {}
        # ONE pending clarifying question per session (increment 4) — a session is in AT MOST
        # one of these two states at a time (clarification precedes approval; resolving it
        # clears this slot and populates _pending).
        self._clarifying: dict[str, PendingClarification] = {}
        # One-shot per-session UI-action signal (#712): set to "dispatch_plan" when
        # a plan preview is rendered (the only reply that carries Approve/Reject
        # buttons), popped by the gateway to attach the buttons to that reply frame.
        self._last_action: dict[str, str] = {}

    def pending_for(self, session_id: str) -> PendingDispatch | None:
        """The session's pending dispatch, or None (tests / inspection)."""
        return self._pending.get(session_id)

    def pending_clarification_for(self, session_id: str) -> PendingClarification | None:
        """The session's pending clarifying question, or None (tests / inspection)."""
        return self._clarifying.get(session_id)

    def pop_action_kind(self, session_id: str) -> str:
        """Pop the one-shot UI-action kind for *session_id* (#712).

        Returns ``"dispatch_plan"`` exactly once after a plan preview was just
        rendered (so the gateway attaches Approve/Reject buttons to that reply),
        else ``""``. One-shot, mirroring the imagine/ingest meta signals."""
        return self._last_action.pop(session_id, "")

    async def handle_command(self, session_id: str, command: DispatchCommand) -> str:
        if not self._enabled:
            return (
                "Coding dispatch is off. It's dormant by default — enable it with "
                "[fleet_dispatch].enabled = true in the orchestrator config."
            )
        try:
            if command.kind == "status":
                return await self._status(command.run_id)
            if command.kind == "approve":
                return await self._approve(session_id)
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
                "Reply /dispatch approve or /dispatch reject before starting another."
            )
        if self._plan_fn is None:
            return self._wiring_notice()

        plan = await self._plan_fn(repo, goal)
        if not plan.ok:
            return plan.message

        repo_path = self._repo_path(repo)
        ecosystem = acc.detect_ecosystem(repo_path)
        run_id = self._mint_run_id()

        # Increment 4 — the confidence-gated clarifying question. If (and ONLY if) the 14B
        # flagged a genuinely ambiguous platform fork, the SYSTEM (never the model) asks ONE
        # curated question BEFORE the normal approval preview. resolve_clarifying_question is
        # the single gate: it returns None for a clear / unknown / absent surface (or an
        # unmapped fork), in which case the flow is EXACTLY today's — no extra turn.
        question = acc.resolve_clarifying_question(plan.spec.build_plan)
        if question is not None:
            self._clarifying[session_id] = PendingClarification(
                run_id=run_id,
                repo=repo,
                goal=goal,
                tasks=plan.tasks,
                spec=plan.spec,
                question=question,
                ecosystem=ecosystem,
                fell_back=plan.fell_back,
                submitted_at=datetime.now(timezone.utc).isoformat(),
            )
            return self._render_clarifying_question(goal, question)

        return self._finalize_pending(
            session_id, run_id=run_id, repo=repo, goal=goal,
            tasks=plan.tasks, spec=plan.spec, ecosystem=ecosystem, fell_back=plan.fell_back,
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
            self._clarifying.get(session_id) is not None
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

    def _finalize_pending(
        self, session_id: str, *, run_id: str, repo: str, goal: str,
        tasks: list, spec: AcceptanceSpec, ecosystem: str, fell_back: bool,
        clarified_note: str = "",
    ) -> str:
        """Store the approval-pending dispatch + render the normal PLAN preview.

        Shared by the no-question path (today's flow, unchanged) and the post-clarification
        path (after the operator's answer threaded a real surface into the plan). The optional
        ``clarified_note`` leads the preview when we got here via a clarifying answer (so the
        operator sees what was resolved / that we fell back to an un-refined plan)."""
        self._pending[session_id] = PendingDispatch(
            run_id=run_id,
            repo=repo,
            goal=goal,
            tasks=tasks,
            spec=spec,
            ecosystem=ecosystem,
            submitted_at=datetime.now(timezone.utc).isoformat(),
        )
        # Signal the gateway to attach Approve/Reject buttons to this preview (#712).
        self._last_action[session_id] = "dispatch_plan"
        preview = acc.render_criteria_preview(spec, ecosystem=ecosystem, tasks=tasks)
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
                clarified_note=note,
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
        refined_spec = AcceptanceSpec(
            goal=clarifying.spec.goal,
            criteria=clarifying.spec.criteria,
            assumptions=clarifying.spec.assumptions,
            build_plan=refined_plan,
        )
        refined_tasks = acc._thread_build_fields(
            [dict(t) for t in clarifying.tasks], refined_spec
        )
        note = f"Got it — building it for: {chosen_label}."
        return self._finalize_pending(
            session_id, run_id=clarifying.run_id, repo=clarifying.repo,
            goal=clarifying.goal, tasks=refined_tasks, spec=refined_spec,
            ecosystem=clarifying.ecosystem, fell_back=clarifying.fell_back,
            clarified_note=note,
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

    # ── /dispatch reject ──────────────────────────────────────────────────

    def _reject(self, session_id: str) -> str:
        # Reject cancels the whole dispatch at EITHER pre-execute phase: an awaiting-answer
        # clarification (increment 4) OR an awaiting-approval plan. Clear both slots.
        clarifying = self._clarifying.pop(session_id, None)
        pending = self._pending.pop(session_id, None)
        if pending is None and clarifying is None:
            return "Nothing to reject — there's no dispatch waiting."
        goal = pending.goal if pending is not None else clarifying.goal
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
