"""#1409 — five ordinary English words must not be able to destroy an answer or a dispatch.

THE TWO DEFECTS, both on the PREFIXED path: the operator did everything right and his words
were still eaten.

**A leading reserved verb.** ``parse_dispatch_command`` matches ``reject <anything>``, so an
ordinary answer to *"what should it NOT do?"* —

    /dispatch Reject anything bigger than 10 MB

— parsed as ``kind="reject"`` and **cancelled the whole dispatch**. *"Status updates should be
on the home page"* ran a status report and dropped the words; *"Stop showing prices until I say
so"* likewise. None of the three even earned the #1160 heads-up line, because ``_consumed_verb``
excludes them by design — its docstring says so: *"status/stop/reject/decide route as verbs and
never reach the consumer."*

**A pipe anywhere.** The parser splits the remainder into ``repo | goal`` and the requirements
consumer took ``goal`` — so

    /dispatch mostly on computer | but phone would be nice

was briefed to the planner as *"but phone would be nice"*. Everything before the pipe was
dropped **silently, because the parse SUCCEEDED**. A pipe is not exotic in an answer; it is how
people write alternatives.

WHY IT WAS WORTH FIXING NOW. #1406 made the UNPREFIXED path fail loudly, and its notice hands
the operator a ready-to-send ``/dispatch <his words>`` block — which routes more raw prose
straight into both of these. Fixing the visible half while leaving the invisible half would have
increased the traffic through it.

THE SHAPE OF THE FIX. A verb is a verb only when it is ALONE. Bare stays a verb and keeps its
meaning; a verb followed by prose is prose. ``status`` additionally keeps its meaning when
followed by something run-id shaped, because "how is my other run doing" is a real thing to ask
mid-interview and is not an answer. And the decision is taken ONCE, in
``requirements_answer_text``, which the routing and the #1406 notice both read — so they cannot
disagree about what a message does, which is the drift that produced #1406's fourth review round.
"""

from __future__ import annotations

import pytest

from services.ui_gateway.src.dispatch_coordinator import (
    DispatchCoordinator,
    parse_dispatch_command,
    requirements_answer_text,
)
from shared.fleet import dispatch as fleet
from shared.fleet.acceptance import PlanResult


def _cfg(tmp_path):
    return fleet.FleetDispatchConfig(
        scripts_dir=tmp_path / "scripts",
        queue_path=tmp_path / "q.json",
        runs_dir=tmp_path / "runs",
        projects_dir=tmp_path / "projects",
    )


def _questioning_plan():
    async def plan_fn(repo, goal):
        return PlanResult(ok=True, questions=[
            {"axis": "surface", "question": "Where will you use this?"},
            {"axis": "nongoal", "question": "What should it deliberately NOT do?"},
        ], message="need more")
    return plan_fn


def _coord(tmp_path):
    return DispatchCoordinator(
        config=_cfg(tmp_path), enabled=True, plan_fn=_questioning_plan(),
        mint_run_id=lambda: "RID-DET",
    )


async def _send(coord, text):
    return await coord.handle_command("s", parse_dispatch_command(text))


async def _park_question(coord):
    await _send(coord, "/dispatch pottery | a website for my pottery studio")
    assert coord.pending_requirements_for("s") is not None, "setup: question must be parked"


# ── the consumption rule, case by case ─────────────────────────────────────


@pytest.mark.parametrize("typed", [
    "Reject anything bigger than 10 MB",
    "Status updates should be on the home page",
    "Stop showing prices until I say so",
    "reject the idea of a blog entirely",
    "stop at four pages",
])
def test_a_sentence_that_merely_STARTS_with_a_verb_is_an_answer(typed):
    """The destructive half. `reject …` cancelled the dispatch; the other two dropped the
    words with no notice at all."""
    command = parse_dispatch_command(f"/dispatch {typed}")
    assert requirements_answer_text(command) == typed, (
        f"{typed!r} was routed as the verb {command.kind!r} instead of being read as an "
        f"answer — which cancels the dispatch or silently drops the words"
    )


@pytest.mark.parametrize("typed", ["reject", "stop", "status", "just decide for me"])
def test_a_BARE_verb_still_means_the_verb(typed):
    """Precision, and the half that matters most: the fix must not disarm the cancel. A bare
    verb is unambiguous and keeps its meaning."""
    command = parse_dispatch_command(f"/dispatch {typed}")
    assert requirements_answer_text(command) is None, (
        f"a bare {typed!r} stopped routing as a verb — the operator can no longer cancel"
    )


def test_status_with_a_run_id_still_means_status():
    """'How is my other run doing' is a real thing to ask mid-interview, and it is not an
    answer. Whitespace decides it: a run id is one token, an answer is a sentence."""
    command = parse_dispatch_command("/dispatch status 20260814-230237-bd")
    assert requirements_answer_text(command) is None


def test_a_pipe_no_longer_halves_the_answer():
    """The silent half. The parse SUCCEEDED, so nothing reported the loss."""
    typed = "mostly on computer | but phone would be nice"
    command = parse_dispatch_command(f"/dispatch {typed}")
    assert command.kind == "run"
    assert requirements_answer_text(command) == typed, (
        "everything before the pipe was dropped — the planner would be briefed on half the "
        "answer with no notice"
    )


def test_the_measured_incident_text_is_unaffected():
    """The #1406 input still round-trips whole — this fix must not disturb the ordinary case."""
    typed = "1. mostly on computer\n2. fresh\n3. I don't know"
    command = parse_dispatch_command(f"/dispatch {typed}")
    assert requirements_answer_text(command) == typed


# ── the routing agrees, driven through the real coordinator ────────────────


@pytest.mark.asyncio
async def test_a_reject_SENTENCE_does_not_cancel_the_dispatch(tmp_path):
    """The end-to-end lock on the destructive case, through the real handler."""
    coord = _coord(tmp_path)
    await _park_question(coord)
    reply = await _send(coord, "/dispatch Reject anything bigger than 10 MB")
    assert "Cancelled the pending dispatch" not in reply, (
        "an answer to 'what should it NOT do?' cancelled the dispatch"
    )


@pytest.mark.asyncio
async def test_a_BARE_reject_still_cancels(tmp_path):
    """Precision through the real handler: the cancel must survive the fix."""
    coord = _coord(tmp_path)
    await _park_question(coord)
    reply = await _send(coord, "/dispatch reject")
    assert "Cancelled the pending dispatch" in reply
    assert coord.pending_requirements_for("s") is None


# ── the toggles ────────────────────────────────────────────────────────────


def test_WITHOUT_raw_the_verb_sentence_is_indistinguishable___the_toggle():
    """THE TOGGLE. The fix rests on `raw` — the verbatim remainder the parser now carries
    beside its interpretation. Without it there is nothing to tell 'reject' the verb from
    'Reject anything bigger than 10 MB' the answer: the parser discards the remainder for
    those kinds, so `kind` alone is all a pre-fix reader had, and it is the same for both.

    Asserted on the DATA rather than by reverting the code, so this fails if `raw` is ever
    dropped from the command."""
    verb = parse_dispatch_command("/dispatch reject")
    sentence = parse_dispatch_command("/dispatch Reject anything bigger than 10 MB")
    assert verb.kind == sentence.kind == "reject", (
        "the premise: both parse to the same kind, which is why kind cannot decide this"
    )
    assert verb.raw != sentence.raw, (
        "`raw` no longer distinguishes them — the fix has been disarmed and a sentence "
        "starting 'reject' will cancel the dispatch again"
    )


def test_WITHOUT_raw_the_pipe_still_halves_it___the_toggle():
    """The same, for the pipe: `goal` is what the pre-fix consumer read."""
    command = parse_dispatch_command("/dispatch mostly on computer | but phone would be nice")
    assert command.goal == "but phone would be nice", (
        "the premise: the parser's interpretation IS the truncated half"
    )
    assert command.raw != command.goal, "`raw` must carry what `goal` lost"


def test_every_answer_shaped_kind_carries_raw():
    """Guards the shape from the other direction: a parser branch added later without `raw`
    would silently reintroduce the class for its own kind."""
    for text in ("reject x", "stop x", "status x", "revise x", "forget x", "answer x",
                 "use 2", "2", "new p | g", "a | b", "plain words"):
        command = parse_dispatch_command(f"/dispatch {text}")
        assert command.raw, f"{text!r} parsed to {command.kind!r} with no raw"
