"""Gateway-side locks for #1165 M1 — the interview voice through the real coordinator.

The clarify-side machinery is locked in ``shared/tests/test_interview_voice.py``. THIS
file drives the REAL parser and DispatchCoordinator with injected fakes and locks the
gateway seams:

* the Phase-0 preamble renders ONLY on an intake render with the voice flag live —
  quick renders and every flag-off render stay byte-identical to the S2 corridor
  (locked by driving a voice-off coordinator and a keyword-less coordinator through the
  same commands and asserting EQUAL replies);
* a WHOLE-reply "I don't know" at the answer turn routes to decide-defaults (recorded
  assumptions) only with the flag live AND on an INTAKE park — a QUICK park keeps it a
  substantive verbatim answer even fully flagged (the design §0 contract: a normal
  /dispatch stays byte-for-byte, review F2); partial replies stay substantive in both
  states; the decide phrases are untouched in both states;
* the parser's own decide site never gains the hatch — ``/dispatch i don't know``
  parses as a run-shaped reply (the corridor consumes it as answer text), never as
  ``kind="decide"``, in every flag state.
"""

from __future__ import annotations

import pytest

from services.ui_gateway.src.dispatch_coordinator import (
    DispatchCommand,
    DispatchCoordinator,
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
    DEFAULT_AXIS_ANSWERS,
    INTAKE_PREAMBLE,
)

# ---------------------------------------------------------------------------
# Harness (the S2 suite's idiom)
# ---------------------------------------------------------------------------


def _cfg(tmp_path):
    return fleet.FleetDispatchConfig(
        scripts_dir=tmp_path / "scripts",
        queue_path=tmp_path / "q.json",
        runs_dir=tmp_path / "runs",
        projects_dir=tmp_path / "projects",
    )


def _spec():
    return AcceptanceSpec(
        "a recipe box",
        (AcceptanceCriterion("c1", "it stores a recipe", "behavior", "run it"),),
    )


_CONTENT_QUESTION = {"axis": AXIS_CONTENT,
                     "question": "What recipes should it start with?"}


class _PlanFn:
    """Records every goal; scripts the first-pass reply and answers any re-plan (a goal
    carrying the requirements block) with a full plan."""

    def __init__(self, tmp_path, first: PlanResult):
        self.tmp_path = tmp_path
        self.first = first
        self.goals: list[str] = []

    async def __call__(self, repo, goal):
        self.goals.append(goal)
        if "[[BLARAI_CLARIFIED_REQUIREMENTS]]" in goal:
            repo_path = str(self.tmp_path / "projects" / repo)
            return PlanResult(
                ok=True,
                tasks=[{"repo": repo_path, "task": "build-it", "prompt": "Build."}],
                spec=_spec(), message="planned",
            )
        return self.first


def _questions_first() -> PlanResult:
    return PlanResult(ok=True, questions=[dict(_CONTENT_QUESTION)], message="asking")


def _coord(tmp_path, plan_fn, *, intake=True, voice=False):
    return DispatchCoordinator(
        config=_cfg(tmp_path), enabled=True,
        plan_fn=plan_fn, execute_fn=None, mint_run_id=lambda: "RID-DET",
        advanced_intake_interview_enabled=intake,
        advanced_intake_interview_voice_enabled=voice,
    )


def _legacy_coord(tmp_path, plan_fn, *, intake=True):
    """A coordinator built WITHOUT the M1 keyword at all — the pre-M1 construction the
    voice-off byte-identity locks compare against."""
    return DispatchCoordinator(
        config=_cfg(tmp_path), enabled=True,
        plan_fn=plan_fn, execute_fn=None, mint_run_id=lambda: "RID-DET",
        advanced_intake_interview_enabled=intake,
    )


def _advanced_run(goal="a recipe box for my grandmother's recipes"):
    return DispatchCommand(kind="run", repo="recipes", goal=goal, advanced=True)


def _reply(text):
    return DispatchCommand(kind="run", repo="", goal=text)


# ---------------------------------------------------------------------------
# The Phase-0 preamble — exact gating
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preamble_opens_the_intake_render_with_the_flag_live(tmp_path):
    coord = _coord(tmp_path, _PlanFn(tmp_path, _questions_first()), voice=True)
    reply = await coord.handle_command("s", _advanced_run())
    assert reply.startswith(INTAKE_PREAMBLE), "the preamble must OPEN the render"
    assert "What recipes should it start with?" in reply
    assert "Before I build" in reply, "the S2 render follows the preamble unchanged"


@pytest.mark.asyncio
async def test_quick_render_never_carries_the_preamble_even_with_the_flag(tmp_path):
    coord = _coord(tmp_path, _PlanFn(tmp_path, _questions_first()), voice=True)
    reply = await coord.handle_command(
        "s", DispatchCommand(kind="run", repo="recipes", goal="a recipe box"))
    assert INTAKE_PREAMBLE not in reply, "the preamble is INTAKE-only"


@pytest.mark.asyncio
async def test_voice_off_intake_render_is_byte_identical_to_pre_m1(tmp_path):
    off = _coord(tmp_path, _PlanFn(tmp_path, _questions_first()), voice=False)
    legacy = _legacy_coord(tmp_path, _PlanFn(tmp_path, _questions_first()))
    assert await off.handle_command("s", _advanced_run()) == \
        await legacy.handle_command("s", _advanced_run())


# ---------------------------------------------------------------------------
# The I-don't-know hatch at the answer turn
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dont_know_routes_to_decide_defaults_with_the_flag_live(tmp_path):
    plan_fn = _PlanFn(tmp_path, _questions_first())
    coord = _coord(tmp_path, plan_fn, voice=True)
    await coord.handle_command("s", _advanced_run())
    reply = await coord.handle_command("s", _reply("I don't know"))
    assert "Here's what I'll treat as DONE" in reply
    pending = coord.pending_for("s")
    assert pending is not None
    assert all(c.get("assumed") for c in pending.spec.clarifications), \
        "an I-don't-know reply must record ASSUMED defaults, never a substantive answer"
    answers = [c.get("answer") for c in pending.spec.clarifications]
    assert DEFAULT_AXIS_ANSWERS[AXIS_CONTENT] in answers
    assert "(assumed)" in plan_fn.goals[1], \
        "the re-plan goal must carry the defaults as assumptions"


@pytest.mark.asyncio
async def test_dont_know_variants_route_and_partials_stay_substantive(tmp_path):
    for text, routes in (
        ("no idea", True),
        ("Not sure.", True),
        ("i dont know", True),
        ("I don't know about the colors — calm ones I guess", False),
    ):
        plan_fn = _PlanFn(tmp_path, _questions_first())
        coord = _coord(tmp_path, plan_fn, voice=True)
        await coord.handle_command("s", _advanced_run())
        await coord.handle_command("s", _reply(text))
        pending = coord.pending_for("s")
        assert pending is not None, text
        assumed = [bool(c.get("assumed")) for c in pending.spec.clarifications]
        if routes:
            assert all(assumed), f"{text!r} must take the decide-defaults turn"
        else:
            assert not all(assumed), f"{text!r} must stay a substantive answer"
            assert text in [c.get("answer") for c in pending.spec.clarifications], \
                "the partial reply must survive verbatim as the answer"


@pytest.mark.asyncio
async def test_quick_park_dont_know_stays_substantive_even_fully_flagged(tmp_path):
    """Review F2's discriminating lock: the hatch is INTAKE-only. Voice fully live, a
    QUICK-path park answered with a whole-reply "I don't know" keeps today's behaviour —
    the words recorded verbatim as a substantive answer, byte-identical to a keyword-less
    coordinator — because the design §0 contract promises a normal /dispatch stays
    byte-for-byte even after the ceremony flips the flag."""
    plan_fn = _PlanFn(tmp_path, _questions_first())
    coord = _coord(tmp_path, plan_fn, voice=True)
    quick = DispatchCommand(kind="run", repo="recipes", goal="a recipe box")
    await coord.handle_command("s", quick)
    parked = coord.pending_requirements_for("s")
    assert parked is not None and parked.intake is False, "precondition: a QUICK park"
    voiced_reply = await coord.handle_command("s", _reply("I don't know"))
    pending = coord.pending_for("s")
    assert [c.get("answer") for c in pending.spec.clarifications] == ["I don't know"], \
        "a quick park must keep the reply as a verbatim substantive answer"
    assert not any(c.get("assumed") for c in pending.spec.clarifications)

    legacy_fn = _PlanFn(tmp_path, _questions_first())
    legacy = _legacy_coord(tmp_path, legacy_fn)
    await legacy.handle_command("s", quick)
    assert await legacy.handle_command("s", _reply("I don't know")) == voiced_reply
    assert legacy_fn.goals == plan_fn.goals, \
        "the quick corridor must be byte-identical with the flag fully live"


@pytest.mark.asyncio
async def test_flag_off_dont_know_stays_a_substantive_answer(tmp_path):
    """The toggle bar on the adversarial input: with the voice off, a whole-reply
    "I don't know" records exactly as today — a real answer, assumed=False — and the
    whole exchange is byte-identical to a keyword-less coordinator's."""
    plan_fn = _PlanFn(tmp_path, _questions_first())
    off = _coord(tmp_path, plan_fn, voice=False)
    await off.handle_command("s", _advanced_run())
    off_reply = await off.handle_command("s", _reply("I don't know"))
    pending = off.pending_for("s")
    assert [c.get("answer") for c in pending.spec.clarifications] == ["I don't know"]
    assert not any(c.get("assumed") for c in pending.spec.clarifications)

    legacy_fn = _PlanFn(tmp_path, _questions_first())
    legacy = _legacy_coord(tmp_path, legacy_fn)
    await legacy.handle_command("s", _advanced_run())
    assert await legacy.handle_command("s", _reply("I don't know")) == off_reply
    assert legacy_fn.goals == plan_fn.goals, "the plan seam must carry identical bytes"


@pytest.mark.asyncio
async def test_decide_phrases_route_in_both_voice_states(tmp_path):
    for voice in (False, True):
        coord = _coord(tmp_path, _PlanFn(tmp_path, _questions_first()), voice=voice)
        await coord.handle_command("s", _advanced_run())
        await coord.handle_command("s", _reply("just decide for me"))
        pending = coord.pending_for("s")
        assert pending is not None and all(
            c.get("assumed") for c in pending.spec.clarifications
        ), f"voice={voice}: the decide hatch regressed"


# ---------------------------------------------------------------------------
# The parser site — never the hatch's carrier
# ---------------------------------------------------------------------------


def test_the_parser_never_gains_the_hatch():
    """The :func:`parse_dispatch_command` decide site does not pass the keyword: an
    I-don't-know reply parses as a run-shaped remainder (the corridor then consumes it
    as answer TEXT under the flag), never as ``kind="decide"`` — in every flag state."""
    for kwargs in ({}, {"intake_token": True}):
        c = parse_dispatch_command("/dispatch i don't know", **kwargs)
        assert c.kind == "run" and c.goal == "i don't know"
        d = parse_dispatch_command("/dispatch just decide for me", **kwargs)
        assert d.kind == "decide", "the live decide parse must be untouched"
