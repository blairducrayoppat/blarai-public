"""Gateway-side locks for #1031 S2 — the intake interview through the real coordinator.

The clarify-side machinery is locked in ``shared/tests/test_intake_interview.py``. THIS
file drives the REAL parser and DispatchCoordinator with injected fakes and locks the
gateway seams, including the three design-review-mandated shapes:

* **F1** — the `advanced` token attaches ONLY on create or piped run; a pipe-less
  run-shaped remainder re-parses the ORIGINAL text, so a pending requirements answer that
  begins with the word "advanced" reaches the corridor VERBATIM (the eats-operator-text
  class stays dead);
* **F2** — a quick-path park's payload is byte-identical (the `intake` key is emitted
  only when True);
* **F3** — the no-questions notice rides only the direct card path; when the Inc-4
  platform question interposes, the notice is suppressed.

Plus: the marker composed on the goal HEAD (before requirements), the hint line's exact
gating, intake parks answering with the eight-axis vocabulary and axis-tagged records,
and full dormancy with the flag off.
"""

from __future__ import annotations

import pytest

from services.ui_gateway.src.dispatch_coordinator import (
    DispatchCommand,
    DispatchCoordinator,
    _requirements_to_payload,
    parse_dispatch_command,
)
from shared.fleet import dispatch as fleet
from shared.fleet.acceptance import (
    AcceptanceCriterion,
    AcceptanceSpec,
    PlanResult,
)
from shared.fleet.clarify import (
    AXIS_CONTENT,
    INTAKE_SENTINEL,
)

_MARKER = INTAKE_SENTINEL.strip()

# ---------------------------------------------------------------------------
# The parser — the token gate and the F1 carve-out
# ---------------------------------------------------------------------------


def test_token_off_is_todays_parse_byte_for_byte():
    c = parse_dispatch_command("/dispatch advanced calc | a calculator")
    assert c.kind == "run" and c.repo == "advanced calc" and c.advanced is False


def test_token_attaches_on_piped_run_and_create():
    c = parse_dispatch_command("/dispatch advanced calc | a calculator",
                               intake_token=True)
    assert c.kind == "run" and c.repo == "calc" and c.goal == "a calculator"
    assert c.advanced is True
    n = parse_dispatch_command("/dispatch advanced new kid-calc | a kid calculator",
                               intake_token=True)
    assert n.kind == "create" and n.repo == "kid-calc" and n.advanced is True


def test_token_never_attaches_to_other_verbs_and_never_strips_them():
    """The amended F1 rule in full: a non-attaching remainder re-parses the ORIGINAL
    rest — so `advanced approve` is NOT an approve (an approval must be typed plainly,
    never reached through a stripped token) and the text survives verbatim for the
    keep-your-words nag."""
    c = parse_dispatch_command("/dispatch advanced approve", intake_token=True)
    assert c.kind == "run" and c.repo == ""
    assert c.goal == "advanced approve" and c.advanced is False


def test_F1_pipeless_text_starting_with_advanced_stays_verbatim():
    """THE review-F1 lock: a pipe-less remainder is exactly the shape of a pending
    requirements ANSWER — it must parse as run-with-empty-repo carrying the WHOLE text,
    the word "advanced" included."""
    c = parse_dispatch_command("/dispatch advanced look with dark mode",
                               intake_token=True)
    assert c.kind == "run" and c.repo == ""
    assert c.goal == "advanced look with dark mode", "the first word was eaten"
    assert c.advanced is False


def test_F2_pipeless_CREATE_shape_stays_verbatim_too():
    """Code-review F2: `new <text>` parses as create even without a pipe, so an answer
    beginning "advanced new …" would have been consumed as a create attempt with its
    head eaten. The flag attaches only on create WITH a goal (the piped form); the
    pipe-less shape re-parses the ORIGINAL text."""
    c = parse_dispatch_command("/dispatch advanced new look with dark mode",
                               intake_token=True)
    assert c.kind == "run" and c.repo == ""
    assert c.goal == "advanced new look with dark mode", "the head was eaten"
    assert c.advanced is False
    # The piped create form still attaches.
    n = parse_dispatch_command("/dispatch advanced new kid-calc | a kid calculator",
                               intake_token=True)
    assert n.kind == "create" and n.repo == "kid-calc" and n.advanced is True


def test_F3_the_piped_repo_named_advanced_is_still_reachable():
    """Code-review F3: the natural piped form for a repo literally named `advanced`
    parses unchanged even with the token on — the remainder `| goal` attaches nothing."""
    c = parse_dispatch_command("/dispatch advanced | fix the login bug",
                               intake_token=True)
    assert c.kind == "run" and c.repo == "advanced" and c.goal == "fix the login bug"
    assert c.advanced is False


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


def _cfg(tmp_path):
    return fleet.FleetDispatchConfig(
        scripts_dir=tmp_path / "scripts",
        queue_path=tmp_path / "q.json",
        runs_dir=tmp_path / "runs",
        projects_dir=tmp_path / "projects",
    )


def _spec(build_plan=None):
    return AcceptanceSpec(
        "a recipe box",
        (AcceptanceCriterion("c1", "it stores a recipe", "behavior", "run it"),),
        build_plan=build_plan,
    )


_CONTENT_QUESTION = {"axis": AXIS_CONTENT,
                     "question": "What recipes should it start with?"}


class _PlanFn:
    """Records every goal; scripts the first-pass reply and answers any re-plan (a goal
    carrying the requirements block) with a full plan.

    *replan_build_plan* is what the re-plan's spec carries (#1237). A test that drives the
    platform menu must set it: ``generate_plan`` attaches a build_plan to every plan it can
    classify, so a re-plan spec carrying NONE is the unparseable-output shape, on which the
    card omits the platform line and the reply says so honestly. Leaving the default there
    makes a menu test assert the happy path against the degraded one."""

    def __init__(self, tmp_path, first: PlanResult, replan_build_plan=None):
        self.tmp_path = tmp_path
        self.first = first
        self.replan_build_plan = replan_build_plan
        self.goals: list[str] = []

    async def __call__(self, repo, goal):
        self.goals.append(goal)
        if "[[BLARAI_CLARIFIED_REQUIREMENTS]]" in goal:
            repo_path = str(self.tmp_path / "projects" / repo)
            return PlanResult(
                ok=True,
                tasks=[{"repo": repo_path, "task": "build-it", "prompt": "Build."}],
                spec=_spec(self.replan_build_plan), message="planned",
            )
        return self.first


def _questions_first() -> PlanResult:
    return PlanResult(ok=True, questions=[dict(_CONTENT_QUESTION)], message="asking")


def _plan_first(build_plan=None) -> PlanResult:
    return PlanResult(
        ok=True, tasks=[{"repo": "r", "task": "build-it", "prompt": "Build."}],
        spec=_spec(build_plan), message="planned",
    )


def _coord(tmp_path, plan_fn, *, intake=True, playback=False):
    return DispatchCoordinator(
        config=_cfg(tmp_path), enabled=True,
        plan_fn=plan_fn, execute_fn=None, mint_run_id=lambda: "RID-DET",
        advanced_intake_interview_enabled=intake,
        advanced_intake_interview_playback_enabled=playback,
    )


def _advanced_run(goal="a recipe box for my grandmother's recipes"):
    return DispatchCommand(kind="run", repo="recipes", goal=goal, advanced=True)


# ---------------------------------------------------------------------------
# The marker on the wire, the intake park, and the eight-axis answer turn
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_advanced_dispatch_marks_the_goal_and_parks_intake(tmp_path):
    plan_fn = _PlanFn(tmp_path, _questions_first())
    coord = _coord(tmp_path, plan_fn)
    reply = await coord.handle_command("s", _advanced_run())
    assert "What recipes should it start with?" in reply
    assert _MARKER in plan_fn.goals[0], "the marker must ride the plan seam"
    parked = coord.pending_requirements_for("s")
    assert parked is not None and parked.intake is True
    assert _MARKER not in parked.goal, "the parked goal is the operator's clean goal"


@pytest.mark.asyncio
async def test_intake_answer_carries_axis_tags_and_no_second_marker(tmp_path):
    plan_fn = _PlanFn(tmp_path, _questions_first())
    coord = _coord(tmp_path, plan_fn)
    await coord.handle_command("s", _advanced_run())
    reply = await coord.handle_command(
        "s", DispatchCommand(kind="run", repo="",
                             goal="start with her lasagna and soup cards"))
    assert "Here's what I'll treat as DONE" in reply
    # The re-plan goal carries requirements but the marker is NOT re-composed —
    # requirements alone suppress the clarify stage AO-side.
    assert "[[BLARAI_CLARIFIED_REQUIREMENTS]]" in plan_fn.goals[1]
    assert _MARKER not in plan_fn.goals[1]
    pending = coord.pending_for("s")
    tagged = [c for c in pending.spec.clarifications if c.get("axes")]
    assert tagged and tagged[0]["axes"] == [AXIS_CONTENT], \
        "the recorded answer must carry the asked-axes tags"


@pytest.mark.asyncio
async def test_F1_end_to_end_an_answer_starting_with_advanced_is_never_mutated(tmp_path):
    """The corridor half of review F1: with the token gate ON, a pending-question answer
    beginning with 'advanced' is consumed VERBATIM as the answer."""
    plan_fn = _PlanFn(tmp_path, _questions_first())
    coord = _coord(tmp_path, plan_fn)
    await coord.handle_command("s", _advanced_run())
    answer_text = "advanced look with dark mode and big fonts"
    cmd = parse_dispatch_command("/dispatch " + answer_text, intake_token=True)
    reply = await coord.handle_command("s", cmd)
    assert "Here's what I'll treat as DONE" in reply
    pending = coord.pending_for("s")
    answers = [c.get("answer") for c in pending.spec.clarifications]
    assert answer_text in answers, f"the answer was mutated: {answers}"


# ---------------------------------------------------------------------------
# F2 — the park payload discipline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_F2_quick_park_payload_is_byte_identical(tmp_path):
    plan_fn = _PlanFn(tmp_path, _questions_first())
    coord = _coord(tmp_path, plan_fn, intake=False)
    await coord.handle_command(
        "s", DispatchCommand(kind="run", repo="recipes", goal="a recipe box"))
    parked = coord.pending_requirements_for("s")
    payload = _requirements_to_payload(parked)
    assert "intake" not in payload, "a quick park must not gain the key (review F2)"
    assert set(payload) == {"run_id", "repo", "goal", "questions", "submitted_at"}


@pytest.mark.asyncio
async def test_intake_park_payload_carries_true_and_restores(tmp_path):
    from services.ui_gateway.src.dispatch_coordinator import (
        _requirements_from_payload,
    )

    plan_fn = _PlanFn(tmp_path, _questions_first())
    coord = _coord(tmp_path, plan_fn)
    await coord.handle_command("s", _advanced_run())
    payload = _requirements_to_payload(coord.pending_requirements_for("s"))
    assert payload["intake"] is True
    assert _requirements_from_payload(payload).intake is True
    legacy = dict(payload)
    legacy.pop("intake")
    assert _requirements_from_payload(legacy).intake is False


# ---------------------------------------------------------------------------
# The hint line — exact gating
# ---------------------------------------------------------------------------

_LONG_GOAL = " ".join(f"word{i}" for i in range(40))
_HINT = "Bigger build?"


@pytest.mark.asyncio
async def test_hint_only_when_flag_on_and_goal_is_big(tmp_path):
    for intake, goal, expect in (
        (True, _LONG_GOAL, True),
        (True, "a short goal", False),
        (False, _LONG_GOAL, False),
    ):
        plan_fn = _PlanFn(tmp_path, _questions_first())
        coord = _coord(tmp_path, plan_fn, intake=intake)
        reply = await coord.handle_command(
            "s", DispatchCommand(kind="run", repo="recipes", goal=goal))
        assert (_HINT in reply) is expect, (intake, goal[:20], reply[-120:])


@pytest.mark.asyncio
async def test_no_hint_on_the_advanced_path_itself(tmp_path):
    plan_fn = _PlanFn(tmp_path, _questions_first())
    coord = _coord(tmp_path, plan_fn)
    reply = await coord.handle_command("s", _advanced_run(goal=_LONG_GOAL))
    assert _HINT not in reply, "the operator already chose the fuller interview"


# ---------------------------------------------------------------------------
# The no-questions notice — F3's two paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_advanced_zero_questions_gets_the_honest_notice(tmp_path):
    plan_fn = _PlanFn(tmp_path, _plan_first())
    coord = _coord(tmp_path, plan_fn)
    reply = await coord.handle_command("s", _advanced_run())
    assert reply.startswith("No further questions — planning directly.")
    assert "Here's what I'll treat as DONE" in reply


@pytest.mark.asyncio
async def test_quick_zero_questions_render_is_untouched(tmp_path):
    plan_fn = _PlanFn(tmp_path, _plan_first())
    coord = _coord(tmp_path, plan_fn)
    reply = await coord.handle_command(
        "s", DispatchCommand(kind="run", repo="recipes", goal="a recipe box"))
    assert "No further questions" not in reply


@pytest.mark.asyncio
async def test_F3_inc4_question_suppresses_the_notice(tmp_path):
    """When the platform question interposes, a question DID appear — the notice must
    not ride the clarifying hold, and _choose's own note keeps its seam."""
    ambiguous = {"surface": "ambiguous", "language_hint": None,
                 "complexity": "moderate", "components": [],
                 "candidates": ["desktop-gui", "web", "mobile"]}
    # #1237: the re-plan carries a real classified build_plan, as generate_plan's does —
    # the note below is DERIVED from it, so a build_plan-less fixture would assert the
    # happy-path wording against the degraded path.
    plan_fn = _PlanFn(tmp_path, _plan_first(build_plan=ambiguous),
                      replan_build_plan={"surface": "web", "language_hint": None,
                                         "complexity": "moderate", "components": []})
    coord = _coord(tmp_path, plan_fn)
    reply = await coord.handle_command("s", _advanced_run())
    assert "one quick question" in reply
    assert "No further questions" not in reply
    final = await coord.handle_command("s", DispatchCommand(kind="choose", choice="2"))
    assert "Got it — building it for" in final
    assert "No further questions" not in final


# ---------------------------------------------------------------------------
# Full dormancy — command.advanced ignored when the gate is off
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_F2_corridor_answer_starting_advanced_new_is_never_mutated(tmp_path):
    """Code-review F2, corridor half: with a question pending, an answer beginning
    "advanced new" reaches the corridor VERBATIM — never a create attempt, never a
    dropped head."""
    plan_fn = _PlanFn(tmp_path, _questions_first())
    coord = _coord(tmp_path, plan_fn)
    await coord.handle_command("s", _advanced_run())
    answer_text = "advanced new look with big fonts please"
    cmd = parse_dispatch_command("/dispatch " + answer_text, intake_token=True)
    reply = await coord.handle_command("s", cmd)
    assert "Here's what I'll treat as DONE" in reply
    pending = coord.pending_for("s")
    assert answer_text in [c.get("answer") for c in pending.spec.clarifications]


@pytest.mark.asyncio
async def test_F1_intake_park_and_tagged_answers_survive_the_real_store(tmp_path):
    """Code-review F1: the end-to-end locks the design committed to — (a) an intake park
    survives the REAL born-encrypted store and restores with intake=True; (b) an
    axes-tagged answer banked by project memory replays through the real store with its
    tags intact (the F6 design-review interaction, pinned not discovered)."""
    from services.ui_gateway.src.dispatch_state_store import (
        build_dispatch_state_store,
    )
    from shared.fleet.clarify import AXIS_CONTENT as _AX

    store = build_dispatch_state_store(str(tmp_path / "dispatch_state.db"),
                                       dev_mode=True)
    plan_fn = _PlanFn(tmp_path, _questions_first())
    coord = DispatchCoordinator(
        config=_cfg(tmp_path), enabled=True, plan_fn=plan_fn, execute_fn=None,
        mint_run_id=lambda: "RID-DET", state_store=store,
        project_memory_enabled=True, advanced_intake_interview_enabled=True,
    )
    await coord.handle_command("s", _advanced_run())
    coord._remember("recipes", [{"question": "asked", "answer": "real recipes",
                                 "assumed": False, "axes": [_AX]}])

    reopened = build_dispatch_state_store(str(tmp_path / "dispatch_state.db"),
                                          dev_mode=True)
    coord2 = DispatchCoordinator(
        config=_cfg(tmp_path), enabled=True,
        plan_fn=_PlanFn(tmp_path, _questions_first()), execute_fn=None,
        mint_run_id=lambda: "RID-DET", state_store=reopened,
        project_memory_enabled=True, advanced_intake_interview_enabled=True,
    )
    coord2.restore_at_boot()
    parked = coord2.pending_requirements_for("s")
    assert parked is not None and parked.intake is True, \
        "an intake park must restore as an intake park through the real store"
    recalled = coord2._recall("recipes")
    assert recalled and recalled[0].get("axes") == [_AX], \
        "banked axis tags must replay intact through the real store"


@pytest.mark.asyncio
async def test_memory_defer_notice_renders_on_a_remembered_advanced_dispatch(tmp_path):
    """The §6 recommended behaviour, rendered: memory enabled + banked answers ⇒ an
    `advanced` dispatch defers to memory and says so, naming the forget escape."""
    from services.ui_gateway.src.dispatch_state_store import (
        build_dispatch_state_store,
    )

    plan_fn = _PlanFn(tmp_path, _plan_first())
    coord = DispatchCoordinator(
        config=_cfg(tmp_path), enabled=True, plan_fn=plan_fn, execute_fn=None,
        mint_run_id=lambda: "RID-DET",
        state_store=build_dispatch_state_store(
            str(tmp_path / "dispatch_state.db"), dev_mode=True),
        project_memory_enabled=True, advanced_intake_interview_enabled=True,
    )
    coord._remember("recipes", [{"question": "asked", "answer": "real recipes",
                                 "assumed": False}])
    reply = await coord.handle_command("s", _advanced_run())
    assert reply.startswith("Using what you've already told me about this project")
    assert "/dispatch forget recipes" in reply
    assert "No further questions" not in reply, "the memory notice supersedes it"


@pytest.mark.asyncio
async def test_flag_off_ignores_a_forged_advanced_command(tmp_path):
    """Defense in depth: even a hand-constructed advanced command changes nothing when
    the coordinator's gate is off — no marker, no intake park, no notice."""
    plan_fn = _PlanFn(tmp_path, _questions_first())
    coord = _coord(tmp_path, plan_fn, intake=False)
    await coord.handle_command("s", _advanced_run())
    assert _MARKER not in plan_fn.goals[0]
    assert coord.pending_requirements_for("s").intake is False


# ---------------------------------------------------------------------------
# #1160 d2 — the reserved-verb notice covers the S2 interview answer path too
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_S2_interview_revise_answer_consumed_with_notice(tmp_path):
    """The collision surface S2 widened (#1160 c.2634): the eight-axis interview runs
    through the SAME answer function, so a `revise …` reply at an INTAKE question gets
    the identical honest notice — consumed as answers, axis tags intact, one line."""
    plan_fn = _PlanFn(tmp_path, _questions_first())
    coord = _coord(tmp_path, plan_fn)
    await coord.handle_command("s", _advanced_run())
    assert coord.pending_requirements_for("s").intake is True
    reply = await coord.handle_command(
        "s", DispatchCommand(kind="revise",
                             feedback="change the criteria: friendly, not preachy"))
    assert reply.startswith("Heads-up: there was no plan yet to revise")
    assert "Here's what I'll treat as DONE" in reply
    # the words were consumed as the INTAKE answer, tags and all
    pending = coord.pending_for("s")
    answers = [c.get("answer") for c in pending.spec.clarifications]
    assert "change the criteria: friendly, not preachy" in answers
    tagged = [c for c in pending.spec.clarifications if c.get("axes")]
    assert tagged and tagged[0]["axes"] == [AXIS_CONTENT]


# ===========================================================================
# #1165 M4 — the playback turn: invitation, re-route, carrier, toggle bars
# ===========================================================================

from shared.fleet import revise as _rev  # noqa: E402

from services.ui_gateway.src.dispatch_coordinator import (  # noqa: E402
    PendingClarification,
    PendingDispatch,
    _clarifying_from_payload,
    _clarifying_to_payload,
    _keep_operator_text,
    _pending_from_payload,
    _pending_to_payload,
    _playback_invitation,
)

_INVITE_HEAD = "Did I get anything wrong?"
#: The #1116 usage line, verbatim — the M4 toggle bar is THIS reply, never a nag.
_USAGE_LINE = ("Usage: /dispatch <repo> | <goal>  —  e.g. "
               "/dispatch calc | a calculator an 8-year-old can use")


class _PlaybackPlanFn:
    """First pass: the scripted *first* result; a #820 revise goal: one usable add op
    (a FRESH slug each round, so the shared budget can be walked to its cap); a
    requirements re-plan: a full plan. Enough corridor for every M4 seam.
    ``revision_ops`` overrides the revise reply (e.g. a keep-only no-op);
    ``criteria_response`` scripts the S3-G criteria-revise seam;
    ``replan_build_plan`` is what the re-plan's spec classifies to — see :class:`_PlanFn`,
    which carries the same knob for the same reason (#1237)."""

    def __init__(self, tmp_path, first: PlanResult, revision_ops=None,
                 criteria_response=None, replan_build_plan=None):
        self.tmp_path = tmp_path
        self.first = first
        self.revision_ops = revision_ops
        self.criteria_response = criteria_response
        self.replan_build_plan = replan_build_plan
        self.goals: list[str] = []

    async def __call__(self, repo, goal):
        self.goals.append(goal)
        if _rev.CRITERIA_REVISE_SENTINEL in goal:
            return self.criteria_response or PlanResult(
                ok=False, message="Criteria revision is turned off (Fail-Closed).")
        if _rev.REVISE_SENTINEL in goal:
            if self.revision_ops is not None:
                return PlanResult(
                    ok=True, revision=[dict(o) for o in self.revision_ops])
            n = sum(1 for g in self.goals if _rev.REVISE_SENTINEL in g)
            return PlanResult(ok=True, revision=[
                {"op": "add", "task": f"bigger-buttons-{n}",
                 "prompt": "make the buttons bigger"},
            ])
        if "[[BLARAI_CLARIFIED_REQUIREMENTS]]" in goal:
            repo_path = str(self.tmp_path / "projects" / repo)
            return PlanResult(
                ok=True,
                tasks=[{"repo": repo_path, "task": "build-it", "prompt": "Build."}],
                spec=_spec(self.replan_build_plan), message="planned",
            )
        return self.first


def _playback_coord(tmp_path, *, first=None, intake=True, playback=True,
                    revision_ops=None, criteria_response=None,
                    replan_build_plan=None):
    plan_fn = _PlaybackPlanFn(tmp_path, first or _plan_first(),
                              revision_ops=revision_ops,
                              criteria_response=criteria_response,
                              replan_build_plan=replan_build_plan)
    return _coord(tmp_path, plan_fn, intake=intake, playback=playback), plan_fn


def _free_text(text="the recipes should be my grandmother's, not samples"):
    """The pipe-less approval-turn reply, exactly as the parser produces it."""
    cmd = parse_dispatch_command("/dispatch " + text, intake_token=True)
    assert cmd.kind == "run" and cmd.repo == "" and cmd.goal == text
    return cmd


# ---- the invitation: renders only intake AND flag, and is the whole delta ----


@pytest.mark.asyncio
async def test_M4_invitation_only_on_intake_cards_with_the_flag_on(tmp_path):
    for intake, playback, advanced, expect in (
        (True, True, True, True),     # intake card, flag on -> invited
        (True, False, True, False),   # flag off -> today's card
        (True, True, False, False),   # quick card, flag on -> never invited
        (False, False, False, False), # the pre-S2 world
    ):
        coord, _ = _playback_coord(tmp_path, intake=intake, playback=playback)
        cmd = _advanced_run() if advanced else DispatchCommand(
            kind="run", repo="recipes", goal="a recipe box")
        reply = await coord.handle_command("s", cmd)
        assert (_INVITE_HEAD in reply) is expect, (intake, playback, advanced)


@pytest.mark.asyncio
async def test_M4_toggle_bar_card_delta_is_exactly_the_invitation(tmp_path):
    """Flag-off byte-identity at the card seam: the flag's ONLY effect on a fresh
    intake card is the appended invitation — everything before it is byte-identical."""
    replies = {}
    for playback in (False, True):
        coord, _ = _playback_coord(tmp_path, playback=playback)
        replies[playback] = await coord.handle_command("s", _advanced_run())
    assert replies[True] == replies[False] + "\n\n" + _playback_invitation(0)


@pytest.mark.asyncio
async def test_M4_carrier_stamped_on_both_finalize_paths(tmp_path):
    # No-question path: advanced_active stamps the bit.
    coord, _ = _playback_coord(tmp_path)
    await coord.handle_command("s", _advanced_run())
    assert coord.pending_for("s").intake is True
    # Replan path: pending_req.intake stamps the bit after the answer turn.
    coord2, _ = _playback_coord(tmp_path, first=_questions_first())
    await coord2.handle_command("s", _advanced_run())
    reply = await coord2.handle_command("s", _free_text("start with her lasagna"))
    assert coord2.pending_for("s").intake is True
    assert _INVITE_HEAD in reply
    # Quick path: never stamped.
    coord3, _ = _playback_coord(tmp_path)
    await coord3.handle_command(
        "s", DispatchCommand(kind="run", repo="recipes", goal="a recipe box"))
    assert coord3.pending_for("s").intake is False


# ---- the re-route: pipe-less free text at the approval turn ----------------


@pytest.mark.asyncio
async def test_M4_pipeless_free_text_at_approval_routes_to_revise(tmp_path):
    coord, plan_fn = _playback_coord(tmp_path)
    await coord.handle_command("s", _advanced_run())
    text = "make the buttons bigger please"
    reply = await coord.handle_command("s", _free_text(text))
    # The EXISTING bounded revise served it: delta card, feedback recorded,
    # budget consumed, run_id stable — and the re-render still invites.
    assert "I revised the plan" in reply
    assert _INVITE_HEAD in reply
    pending = coord.pending_for("s")
    assert pending.revision_count == 1 and pending.run_id == "RID-DET"
    assert pending.intake is True, "a playback revise keeps the carrier"
    answers = [c.get("answer") for c in pending.spec.clarifications]
    assert text in answers, "the feedback must ride the spec block (#820)"
    assert _rev.REVISE_SENTINEL in plan_fn.goals[-1], "the revise seam served it"


@pytest.mark.asyncio
async def test_M4_reroute_flag_off_keeps_usage_keep_text_verbatim(tmp_path):
    """THE F1-corrected toggle bar: flag off, the pipe-less reply gets the #1116
    usage/keep-text answer BYTE-IDENTICALLY — never the nag, never a revise."""
    coord, plan_fn = _playback_coord(tmp_path, playback=False)
    await coord.handle_command("s", _advanced_run())
    text = "make the buttons bigger please"
    n_calls = len(plan_fn.goals)
    reply = await coord.handle_command("s", _free_text(text))
    assert reply == _keep_operator_text(_USAGE_LINE, text)
    assert len(plan_fn.goals) == n_calls, "no model call on the flag-off path"
    assert coord.pending_for("s").revision_count == 0, "no revision consumed"


@pytest.mark.asyncio
async def test_M4_reroute_never_fires_for_a_quick_card_even_flag_on(tmp_path):
    coord, plan_fn = _playback_coord(tmp_path)
    await coord.handle_command(
        "s", DispatchCommand(kind="run", repo="recipes", goal="a recipe box"))
    text = "make the buttons bigger please"
    n_calls = len(plan_fn.goals)
    reply = await coord.handle_command("s", _free_text(text))
    assert reply == _keep_operator_text(_USAGE_LINE, text)
    assert len(plan_fn.goals) == n_calls
    assert coord.pending_for("s").revision_count == 0


@pytest.mark.asyncio
async def test_M4_reroute_with_no_card_keeps_the_usage_reply(tmp_path):
    """Flag on, intake on, but nothing pending — the pipe-less shape keeps today's
    answer (there is no card whose invitation the text could be answering)."""
    coord, _ = _playback_coord(tmp_path)
    text = "make the buttons bigger please"
    reply = await coord.handle_command("s", _free_text(text))
    assert reply == _keep_operator_text(_USAGE_LINE, text)


@pytest.mark.asyncio
async def test_M4_piped_shape_still_nags_on_every_path(tmp_path):
    """An attempted SECOND dispatch (the piped shape) is never a playback reply —
    the 'already waiting' nag answers it on the intake+flag path exactly as on
    every other, and the model is not re-run."""
    for intake, playback, advanced in (
        (True, True, True), (True, False, True), (True, True, False),
    ):
        coord, plan_fn = _playback_coord(tmp_path, intake=intake, playback=playback)
        cmd = _advanced_run() if advanced else DispatchCommand(
            kind="run", repo="recipes", goal="a recipe box")
        await coord.handle_command("s", cmd)
        n_calls = len(plan_fn.goals)
        reply = await coord.handle_command(
            "s", DispatchCommand(kind="run", repo="other", goal="a second build"))
        assert "already waiting" in reply.lower(), (intake, playback, advanced)
        assert len(plan_fn.goals) == n_calls
        assert coord.pending_for("s").revision_count == 0


@pytest.mark.asyncio
async def test_M4_reserved_verbs_win_at_the_approval_turn(tmp_path):
    """Extending the #1160 locks to the approval turn: with an intake card waiting and
    the playback flag on, every reserved verb still routes as ITSELF — never consumed
    as playback feedback."""
    # approve -> the approve path (wiring notice with execute_fn unset), card kept.
    coord, _ = _playback_coord(tmp_path)
    await coord.handle_command("s", _advanced_run())
    reply = await coord.handle_command(
        "s", parse_dispatch_command("/dispatch approve", intake_token=True))
    assert "isn't connected yet" in reply
    assert coord.pending_for("s").revision_count == 0
    # revise <text> -> the revise VERB (one consumption, not a double route).
    reply = await coord.handle_command(
        "s", parse_dispatch_command("/dispatch revise make the buttons bigger",
                                    intake_token=True))
    assert "I revised the plan" in reply
    assert coord.pending_for("s").revision_count == 1
    # status -> the status report, card untouched.
    reply = await coord.handle_command(
        "s", parse_dispatch_command("/dispatch status", intake_token=True))
    assert reply.startswith("No dispatches yet")
    assert coord.pending_for("s").revision_count == 1
    # reject -> cancels the dispatch, never a revision.
    reply = await coord.handle_command(
        "s", parse_dispatch_command("/dispatch reject", intake_token=True))
    assert reply.startswith("Cancelled the pending dispatch")
    assert coord.pending_for("s") is None


# ---- the carrier: codecs, the real store, and the Inc-4 hold ---------------


def test_M4_carrier_roundtrip_pre_M4_restore_and_quick_byte_identity():
    p = PendingDispatch(run_id="R", repo="r", goal="g", intake=True)
    assert _pending_from_payload(_pending_to_payload(p)).intake is True
    legacy = _pending_to_payload(p)
    legacy.pop("intake")
    assert _pending_from_payload(legacy).intake is False, "a pre-M4 row restores False"
    assert "intake" not in _pending_to_payload(
        PendingDispatch(run_id="R", repo="r", goal="g")
    ), "a quick-path park must not gain the key"

    c = PendingClarification(run_id="R", repo="r", goal="g", intake=True)
    assert _clarifying_from_payload(_clarifying_to_payload(c)).intake is True
    legacy_c = _clarifying_to_payload(c)
    legacy_c.pop("intake")
    assert _clarifying_from_payload(legacy_c).intake is False
    assert "intake" not in _clarifying_to_payload(
        PendingClarification(run_id="R", repo="r", goal="g")
    )


@pytest.mark.asyncio
async def test_M4_intake_card_survives_the_real_store_and_still_invites(tmp_path):
    """End to end through the born-encrypted store: an intake CARD parked by one
    process restores in the next with the carrier intact, so the invitation's
    promise (free text -> revise) still holds after a restart."""
    from services.ui_gateway.src.dispatch_state_store import (
        build_dispatch_state_store,
    )

    store = build_dispatch_state_store(str(tmp_path / "dispatch_state.db"),
                                       dev_mode=True)
    plan_fn = _PlaybackPlanFn(tmp_path, _plan_first())
    coord = DispatchCoordinator(
        config=_cfg(tmp_path), enabled=True, plan_fn=plan_fn, execute_fn=None,
        mint_run_id=lambda: "RID-DET", state_store=store,
        advanced_intake_interview_enabled=True,
        advanced_intake_interview_playback_enabled=True,
    )
    await coord.handle_command("s", _advanced_run())
    assert coord.pending_for("s").intake is True

    reopened = build_dispatch_state_store(str(tmp_path / "dispatch_state.db"),
                                          dev_mode=True)
    coord2 = DispatchCoordinator(
        config=_cfg(tmp_path), enabled=True,
        plan_fn=_PlaybackPlanFn(tmp_path, _plan_first()), execute_fn=None,
        mint_run_id=lambda: "RID-DET", state_store=reopened,
        advanced_intake_interview_enabled=True,
        advanced_intake_interview_playback_enabled=True,
    )
    coord2.restore_at_boot()
    assert coord2.pending_for("s").intake is True
    text = "make the buttons bigger please"
    reply = await coord2.handle_command("s", _free_text(text))
    assert "I revised the plan" in reply and _INVITE_HEAD in reply


@pytest.mark.asyncio
async def test_M4_inc4_interposed_intake_keeps_its_invitation_after_choose(tmp_path):
    """The Inc-4 platform hold must not launder the bit away: the hold carries it and
    `_choose` re-stamps it onto the finalized card — on the answered path AND the
    malformed-answer fallback."""
    ambiguous = {"surface": "ambiguous", "language_hint": None,
                 "complexity": "moderate", "components": [],
                 "candidates": ["desktop-gui", "web", "mobile"]}
    for choice, note in (("2", "Got it — building it for"),
                         ("nonsense", "I didn't catch which option")):
        # #1237: a real classified build_plan on the re-plan, as generate_plan returns —
        # the answered path's note is derived from it, not asserted alongside it.
        coord, _ = _playback_coord(
            tmp_path, first=_plan_first(build_plan=ambiguous),
            replan_build_plan={"surface": "web", "language_hint": None,
                               "complexity": "moderate", "components": []})
        await coord.handle_command("s", _advanced_run())
        held = coord.pending_clarification_for("s")
        assert held is not None and held.intake is True, \
            "the Inc-4 hold must carry the carrier"
        final = await coord.handle_command(
            "s", DispatchCommand(kind="choose", choice=choice))
        assert note in final
        assert _INVITE_HEAD in final, f"the {choice!r} path dropped the invitation"
        assert coord.pending_for("s").intake is True


# ---- the budget: shared, honest at the cap ---------------------------------


@pytest.mark.asyncio
async def test_M4_budget_shared_and_cap_card_tells_the_truth(tmp_path):
    coord, _ = _playback_coord(tmp_path)
    await coord.handle_command("s", _advanced_run())
    # Spend the WHOLE shared #820 budget through the playback route.
    for i in range(1, _rev.DEFAULT_MAX_REVISIONS + 1):
        reply = await coord.handle_command(
            "s", _free_text(f"round {i}: make the buttons bigger"))
        assert coord.pending_for("s").revision_count == i
    # The capped card still asks the two questions but stops promising a fix.
    assert _INVITE_HEAD in reply
    assert "I'll fix the plan" not in reply, \
        "the capped card must not promise a fix revise would refuse"
    assert f"used its {_rev.DEFAULT_MAX_REVISIONS} revisions" in reply
    # One more free-text reply: the existing bounded-revise cap answer, honest.
    over = await coord.handle_command("s", _free_text("one more change"))
    assert f"refined this plan {_rev.DEFAULT_MAX_REVISIONS} times" in over
    assert coord.pending_for("s").revision_count == _rev.DEFAULT_MAX_REVISIONS


# ---- fail-soft re-renders keep the invitation ------------------------------


@pytest.mark.asyncio
async def test_M4_failsoft_rerender_still_carries_the_invitation(tmp_path):
    """A no-op revision re-renders the ORIGINAL card fail-soft (#820) — on an intake
    card that render still closes with the invitation, budget unconsumed."""
    coord, _ = _playback_coord(
        tmp_path, revision_ops=[{"op": "keep", "ref": 1}])
    await coord.handle_command("s", _advanced_run())
    reply = await coord.handle_command("s", _free_text("do nothing differently"))
    assert "I couldn't turn that into a change" in reply
    assert _INVITE_HEAD in reply
    assert coord.pending_for("s").revision_count == 0, "fail-soft consumes no budget"


@pytest.mark.asyncio
async def test_M4_wall_only_criteria_report_still_carries_the_invitation(tmp_path):
    """The fourth render site (S3-G review-F2 wall report): playback feedback aimed
    only at a protected machine row re-renders the untouched card with the protected
    report — and the intake card still closes with the invitation."""
    coord, _ = _playback_coord(
        tmp_path,
        criteria_response=PlanResult(ok=True, criteria_revision=[
            {"op": "rescope", "ref": 1, "text": "stores a recipe eventually"},
        ]),
    )
    await coord.handle_command("s", _advanced_run())
    reply = await coord.handle_command(
        "s", _free_text("loosen the criteria a little"))
    assert "Protected" in reply
    assert _INVITE_HEAD in reply
    assert coord.pending_for("s").revision_count == 0, "wall-only consumes no budget"


@pytest.mark.asyncio
async def test_M4_criteria_revision_success_keeps_carrier_and_invitation(tmp_path):
    """A playback correction served by the CRITERIA path (S3-G): the judged row
    changes, the shared budget is consumed, and the re-rendered card keeps both the
    carrier and the invitation."""
    from shared.fleet.acceptance import TIER_HUMAN

    spec = AcceptanceSpec("a recipe box", (
        AcceptanceCriterion("c1", "it stores a recipe", "behavior", "run it"),
        AcceptanceCriterion("c2", "feels friendly", TIER_HUMAN, ""),
    ))
    first = PlanResult(
        ok=True, tasks=[{"repo": "r", "task": "build-it", "prompt": "Build."}],
        spec=spec, message="planned",
    )
    coord, _ = _playback_coord(
        tmp_path, first=first,
        criteria_response=PlanResult(ok=True, criteria_revision=[
            {"op": "keep", "ref": 1},
            {"op": "rescope", "ref": 2, "text": "feels warm, never preachy"},
        ]),
    )
    await coord.handle_command("s", _advanced_run())
    reply = await coord.handle_command(
        "s", _free_text("the criteria should ask for warm, not preachy"))
    assert "I updated what the build will be judged on" in reply
    assert _INVITE_HEAD in reply
    pending = coord.pending_for("s")
    assert pending.intake is True and pending.revision_count == 1
    assert "feels warm, never preachy" in [c.text for c in pending.spec.criteria]


# ---------------------------------------------------------------------------
# #1165 M4 fix round (review F1) — the invitation agrees with the S3-F block
# ---------------------------------------------------------------------------

from shared.fleet import acceptance as _acc  # noqa: E402

_STD_BLOCKED = _acc._coverage_blocked_message(
    "the exam imports a module no task builds")
_ORPHAN_BLOCKED = _acc._coverage_blocked_message_orphan_only(
    "the exam imports a module no task builds")


def _blocked_first(marker):
    return PlanResult(
        ok=True, tasks=[{"repo": "r", "task": "build-it", "prompt": "Build."}],
        spec=_spec(), message="planned", coverage_blocked=marker,
    )


def test_M4_orphan_predicate_tracks_the_builders():
    """The drift-proof pair: the predicate keys on the signature sentence the orphan
    builder embeds — same constant, same file — and rejects the standard variant."""
    assert _acc.coverage_blocked_is_orphan_only(_ORPHAN_BLOCKED) is True
    assert _acc.coverage_blocked_is_orphan_only(_STD_BLOCKED) is False
    assert _acc.coverage_blocked_is_orphan_only("") is False


@pytest.mark.asyncio
async def test_M4_blocked_card_keeps_promise_but_drops_the_approve_tail(tmp_path):
    """Review F1(a): while blocked, approve is the one verb the marker refuses, so the
    invitation must not offer it. Revise IS the unblock path, so the fixing promise
    stays."""
    coord, _ = _playback_coord(tmp_path, first=_blocked_first(_STD_BLOCKED))
    reply = await coord.handle_command("s", _advanced_run())
    assert _INVITE_HEAD in reply
    # #1406: the promise now names the prefix. "Tell me in plain words" alone was true
    # about the words and false about the routing — a reply without `/dispatch` reaches
    # ordinary chat, not the revise path this sentence offers.
    assert "Tell me in plain words with `/dispatch <your words>` and I'll fix the plan." in reply
    assert "when it reads right" not in reply, "the approve tail is false while blocked"
    assert reply.endswith(_playback_invitation(0, _STD_BLOCKED))
    # The refusal the invitation now agrees with:
    over = await coord.handle_command(
        "s", parse_dispatch_command("/dispatch approve", intake_token=True))
    assert over.startswith("Not starting this one")


@pytest.mark.asyncio
async def test_M4_orphan_blocked_card_drops_the_fixing_promise(tmp_path):
    """Review F1(b): on the orphan-only block a plan revision cannot clear the gap —
    the footer says so in as many words — so the invitation keeps the two questions
    and promises nothing."""
    coord, _ = _playback_coord(tmp_path, first=_blocked_first(_ORPHAN_BLOCKED))
    reply = await coord.handle_command("s", _advanced_run())
    assert _INVITE_HEAD in reply
    assert "I'll fix the plan" not in reply, \
        "the fixing promise contradicts the orphan footer directly above it"
    assert "when it reads right" not in reply
    assert reply.endswith(_playback_invitation(0, _ORPHAN_BLOCKED))


@pytest.mark.asyncio
async def test_M4_blocked_cap_card_offers_reject_only(tmp_path):
    """Review F1(c): at a BLOCKED cap both refusals hold — the card's closing must
    mirror the revise cap refusal for blocked plans (reject only, never approve)."""
    coord, _ = _playback_coord(tmp_path, first=_blocked_first(_STD_BLOCKED))
    await coord.handle_command("s", _advanced_run())
    # Walk the shared budget to its cap; the fake tasks carry no oracle, so the
    # re-evaluation cannot measure and the ORIGINAL marker carries (S3-F shape).
    for i in range(1, _rev.DEFAULT_MAX_REVISIONS + 1):
        reply = await coord.handle_command(
            "s", _free_text(f"round {i}: make the buttons bigger"))
        assert coord.pending_for("s").revision_count == i
        assert coord.pending_for("s").coverage_blocked == _STD_BLOCKED
    assert _INVITE_HEAD in reply
    assert "the coverage gap above is still open" in reply
    assert "reply /dispatch reject and start a new dispatch" in reply
    assert "approve" not in _playback_invitation(
        _rev.DEFAULT_MAX_REVISIONS, _STD_BLOCKED)
    assert reply.endswith(
        _playback_invitation(_rev.DEFAULT_MAX_REVISIONS, _STD_BLOCKED))
    # One more free-text reply hits the existing blocked-cap refusal, which the
    # capped invitation now mirrors instead of contradicting.
    over = await coord.handle_command("s", _free_text("one more change"))
    assert "its exam still can't cover it" in over
    assert "/dispatch reject" in over and "approve" not in over


@pytest.mark.asyncio
async def test_M4_blocked_toggle_off_delta_is_exactly_the_blocked_invitation(tmp_path):
    """Toggle-off byte-identity on the blocked shape: the flag's only effect on a
    blocked intake card is the blocked-aware invitation."""
    replies = {}
    for playback in (False, True):
        coord, _ = _playback_coord(
            tmp_path, first=_blocked_first(_STD_BLOCKED), playback=playback)
        replies[playback] = await coord.handle_command("s", _advanced_run())
    assert _INVITE_HEAD not in replies[False]
    assert replies[True] == (
        replies[False] + "\n\n" + _playback_invitation(0, _STD_BLOCKED))
