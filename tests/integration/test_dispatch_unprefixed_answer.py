"""#1406 — an answer typed without the ``/dispatch`` prefix must not vanish.

THE INCIDENT, because these tests only make sense against it. On 2026-08-15 at 10:14 EDT
the operator ran the intake interview on his own machine. It asked eight plain-language
questions and he answered three of them, formatted the way anyone would::

    1. mostly on computer
    2. fresh
    3. I don't know

with no prefix. :func:`parse_dispatch_command` returns ``None`` for that, ``None`` means
"not a command", and the message went to the ORDINARY CHAT PATH — where the model, handed
three bare answers with no question in front of it, called ``generate_image`` three times
and emitted no prose. He got an empty bubble. His verdict was one word: "failure."

THE DECISION THAT SHAPES THESE TESTS. Asked whether a bare reply should simply be taken as
the answer, he said: *"no. a bare reply should not simply be the answer."* The prefix stays
required — absorbing bare text would make ordinary chat modal for as long as any question
sat parked, trading a visible failure for an invisible one. So the whole remedy is that
silence becomes a sentence, and the tests below are shaped to that: they assert what is
SAID, and they assert just as hard that nothing is stolen.

The seam-level half of this lock — that the real dispatcher reaches the notice, and that
it cannot swallow ``/coord`` or ``/remember`` on the way — lives in
``services/ui_backend/tests/test_dispatcher_unanswered_question.py``. The instruction-text
half is ``tests/security/test_operator_instructions_parse.py``.
"""

from __future__ import annotations

import pytest

from services.ui_gateway.src.dispatch_coordinator import (
    DispatchCoordinator,
    parse_dispatch_command,
)
from shared.fleet import dispatch as fleet
from shared.fleet.acceptance import AcceptanceCriterion, AcceptanceSpec, PlanResult

#: What he actually typed, byte for byte (launcher.log 10:14:16, ``len=46``).
HIS_REPLY = "1. mostly on computer\n2. fresh\n3. I don't know"


def _cfg(tmp_path):
    return fleet.FleetDispatchConfig(
        scripts_dir=tmp_path / "scripts",
        queue_path=tmp_path / "q.json",
        runs_dir=tmp_path / "runs",
        projects_dir=tmp_path / "projects",
    )


def _questioning_plan():
    """A plan_fn that parks the #819 requirements question set, as the real 14B does for
    an underspecified goal."""
    async def plan_fn(repo, goal):
        return PlanResult(ok=True, questions=[
            {"axis": "surface", "question": "Where will you use this?"},
            {"axis": "content", "question": "Start fresh or reuse what you have?"},
        ], message="need a little more")
    return plan_fn


def _approving_plan():
    """A plan_fn that returns a real plan, so the session parks an APPROVAL card rather
    than a question — the state that must NOT be intercepted."""
    async def plan_fn(repo, goal):
        return PlanResult(
            ok=True,
            spec=AcceptanceSpec("a calculator", (
                AcceptanceCriterion("c1", "the project builds", "build", ""),
            )),
            tasks=[{"repo": repo, "task": "t1", "prompt": "build it"}],
            message="planned",
        )
    return plan_fn


def _coord(tmp_path, *, enabled=True, plan_fn=None):
    return DispatchCoordinator(
        config=_cfg(tmp_path), enabled=enabled, plan_fn=plan_fn,
        mint_run_id=lambda: "RID-DET",
    )


async def _send(coord, sess, text):
    return await coord.handle_command(sess, parse_dispatch_command(text))


def _command_blocks(notice: str) -> "list[str]":
    """Every fenced block in *notice* that is offered as a COMMAND to send.

    Both the ready-to-send block and ``_keep_operator_text``'s verbatim echo use a code
    fence, and telling them apart matters: the echo is the operator's own words handed back
    (#1116) and is not claimed to be sendable, while a ``/dispatch``-leading block IS. An
    earlier version of this test read fence-1 unconditionally and convicted the echo, which
    would have argued for deleting the #1116 guarantee to make a test pass.
    """
    parts = notice.split("```")
    return [
        b.strip() for i, b in enumerate(parts)
        if i % 2 == 1 and b.strip().lower().startswith("/dispatch")
    ]


# ── the defect itself ──────────────────────────────────────────────────────


def test_his_actual_reply_is_still_not_a_command():
    """The premise, asserted rather than assumed. If this ever goes green the routing has
    changed underneath the fix and the rest of this file is measuring nothing."""
    assert parse_dispatch_command(HIS_REPLY) is None


@pytest.mark.asyncio
async def test_the_unprefixed_answer_gets_a_reply_instead_of_silence(tmp_path):
    """THE REGRESSION LOCK. Drive the real coordinator into the real state he was in, hand
    it the real text, and require a reply that names what to type."""
    coord = _coord(tmp_path, plan_fn=_questioning_plan())
    await _send(coord, "s", "/dispatch pottery | a website for my pottery studio")
    assert coord.pending_requirements_for("s") is not None, "setup: question must be parked"

    notice = coord.unanswered_question_notice("s", HIS_REPLY)

    assert notice, "an unprefixed reply produced no notice — this is the empty bubble"
    assert "/dispatch" in notice, "the notice must name the prefix"
    assert HIS_REPLY in notice, (
        "the operator's words must come back verbatim — #1116's standing rule for this "
        "surface, and the reason he can recover in one copy instead of retyping"
    )
    assert f"/dispatch {HIS_REPLY}" in notice, (
        "the ready-to-send block must carry the prefix already applied"
    )


@pytest.mark.asyncio
async def test_the_ready_to_send_block_actually_parses(tmp_path):
    """The notice's whole value is that following it WORKS. Extract what it tells him to
    send and drive it through the real parser and the real handler — not a mock of either.

    This is the test that would have caught the shipped "reply with the number (e.g. `2`)"
    instruction, which told him to type something the parser refuses."""
    coord = _coord(tmp_path, plan_fn=_questioning_plan())
    await _send(coord, "s", "/dispatch pottery | a website for my pottery studio")
    notice = coord.unanswered_question_notice("s", HIS_REPLY)

    blocks = _command_blocks(notice)
    assert blocks, "no ready-to-send block for the measured input"
    command = parse_dispatch_command(blocks[0])
    assert command is not None, "the notice printed a command the parser rejects"
    assert HIS_REPLY in (command.goal or ""), (
        "his words must survive the round trip into the command, not just into the text"
    )
    # And the behavioural half: sending it actually ANSWERS, clearing the question.
    await _send(coord, "s", blocks[0])
    assert coord.pending_requirements_for("s") is None, (
        "sending the printed block left the question pending — the notice promised it would "
        "pick up where we were"
    )


@pytest.mark.asyncio
async def test_no_block_is_offered_for_an_answer_that_would_be_eaten(tmp_path):
    """The notice must not instruct him into a line that destroys or truncates his answer.

    Two shapes do that, and both are ordinary things to type (#1409):

    * a first word that is a reserved verb — "Reject anything bigger than 10 MB" parses as
      ``kind="reject"`` and CANCELS the whole dispatch;
    * a pipe anywhere — "mostly on computer | but phone would be nice" splits on the pipe and
      the consumer keeps only the half after it.

    Both mechanisms predate this ticket. What does not is a message telling him to send that
    exact line: a defect he might have stumbled into becomes one the product walked him into,
    on the surface built to make this honest. So no block is offered — his words still come
    back verbatim, and nothing false is promised about them."""
    coord = _coord(tmp_path, plan_fn=_questioning_plan())
    await _send(coord, "s", "/dispatch pottery | a website for my pottery studio")

    # STILL EATEN, and therefore still blocked: these three lose their first word to the
    # parser's verb match, and `requirements_answer_text` reports the shortened text, so
    # `_ready_to_send` refuses to print a line that would deliver less than he typed. (#1160
    # gives them an honest heads-up when they ARE sent; that is a different guarantee.)
    for typed in (
        "revise the header to be smaller",
        "forget about the blog for now",
        "new pages for each piece",
    ):
        notice = coord.unanswered_question_notice("s", typed)
        assert notice and typed in notice, f"his words must survive for {typed!r}"
        assert not _command_blocks(notice), (
            f"the notice told him to send /dispatch {typed!r}, which delivers less than he "
            f"typed — the first word is eaten by the parser's verb match"
        )

    # NO LONGER EATEN (#1409), so a block is now correct for exactly these. This assertion
    # inverted the day #1409 landed, and that is the point: the notice and the corridor read
    # ONE rule (`requirements_answer_text`), so fixing what the corridor consumes changed what
    # the notice offers, with no second edit and no chance of the two disagreeing.
    for typed in (
        "Reject anything bigger than 10 MB",
        "Status updates should be on the home page",
        "Stop showing prices until I say so",
        "mostly on computer | but phone would be nice",
    ):
        notice = coord.unanswered_question_notice("s", typed)
        assert notice and typed in notice, f"his words must survive for {typed!r}"
        blocks = _command_blocks(notice)
        assert blocks == [f"/dispatch {typed}"], (
            f"{typed!r} now reaches the answer path intact (#1409), so the notice should "
            f"offer it — got {blocks!r}"
        )


@pytest.mark.asyncio
async def test_a_partial_answer_is_handled_without_promising_it_is_free(tmp_path):
    """He answered three of eight. The notice must work for that — and must NOT tell him
    partial answers are cost-free.

    A partial free-text reply is recorded by ``answered_from_free_text`` against EVERY
    outstanding axis with ``assumed=False``, so the axes he skipped read as answered
    rather than assumed and the #1174 surface gate never fires. "You don't have to answer
    them all" would be an invitation into that blind spot. The honest line states what
    sending does and points at ``just decide for me``, whose defaults ride the plan card
    as assumptions he can see and reject."""
    coord = _coord(tmp_path, plan_fn=_questioning_plan())
    await _send(coord, "s", "/dispatch pottery | a website for my pottery studio")
    notice = coord.unanswered_question_notice("s", HIS_REPLY)

    assert "taken as your answers" in notice, (
        "the notice must say what sending will do with a partial reply"
    )
    assert "/dispatch just decide for me" in notice
    low = notice.lower()
    assert "don't have to answer" not in low and "do not have to answer" not in low, (
        "that phrasing invites the #1174 blind spot — see the docstring"
    )


@pytest.mark.asyncio
async def test_the_notice_does_not_assert_the_message_was_an_answer(tmp_path):
    """A mid-interview aside — "what do you mean by fresh?" — must not be handed back with
    an unconditional "copy this and send it". Sent, it is banked as the answer to every
    outstanding axis. The copy block is offered CONDITIONALLY and the non-answer exit is
    named, or the remedy becomes a one-click funnel into a fabricated requirement."""
    coord = _coord(tmp_path, plan_fn=_questioning_plan())
    await _send(coord, "s", "/dispatch pottery | a website for my pottery studio")
    aside = "what do you mean by fresh?"
    notice = coord.unanswered_question_notice("s", aside)

    assert "If that was your answer" in notice, (
        "the copy block must be conditional — the notice cannot tell an answer from an aside"
    )
    assert "/dispatch reject" in notice, "the non-answer exit must be named"


# ── precision: what must NOT be intercepted ────────────────────────────────


@pytest.mark.asyncio
async def test_a_parked_PLAN_does_not_intercept_ordinary_chat(tmp_path):
    """THE PRECISION LOCK, and the one that catches the naive fix.

    Seven plans were parked on his machine the morning this was found. Intercepting on a
    parked plan would make ordinary chat modal for as long as any of them sat unapproved —
    the precise trade his decision refused. A plan awaiting approval is not a question."""
    coord = _coord(tmp_path, plan_fn=_approving_plan())
    await _send(coord, "s", "/dispatch calc | a calculator")
    assert coord.pending_for("s") is not None, "setup: a plan card must be parked"
    assert coord.pending_requirements_for("s") is None
    assert coord.pending_clarification_for("s") is None

    assert coord.unanswered_question_notice("s", "what's the weather like?") is None, (
        "ordinary chat was stolen while a plan sat waiting for approval"
    )


@pytest.mark.asyncio
async def test_a_clean_session_is_untouched(tmp_path):
    """No pending anything: the ordinary chat path stays byte-identical."""
    coord = _coord(tmp_path, plan_fn=_questioning_plan())
    assert coord.unanswered_question_notice("s", "hello there") is None


@pytest.mark.asyncio
async def test_another_session_is_untouched(tmp_path):
    """The state is per-session. A question parked in one chat must not intercept another."""
    coord = _coord(tmp_path, plan_fn=_questioning_plan())
    await _send(coord, "s1", "/dispatch pottery | a website for my pottery studio")
    assert coord.unanswered_question_notice("s1", HIS_REPLY) is not None
    assert coord.unanswered_question_notice("s2", HIS_REPLY) is None


@pytest.mark.asyncio
async def test_empty_text_is_untouched(tmp_path):
    coord = _coord(tmp_path, plan_fn=_questioning_plan())
    await _send(coord, "s", "/dispatch pottery | a website for my pottery studio")
    assert coord.unanswered_question_notice("s", "   ") is None


@pytest.mark.asyncio
async def test_dormant_dispatch_intercepts_nothing(tmp_path):
    """DORMANT-safe. ``handle_dispatch_command`` carries no enablement check of its own —
    it lives in ``handle_command`` — so without the guard a disabled dispatch would start
    intercepting chat."""
    coord = _coord(tmp_path, enabled=False, plan_fn=_questioning_plan())
    coord._requirements["s"] = object()  # a slot that could only exist by restore
    assert coord.unanswered_question_notice("s", HIS_REPLY) is None


# ── the aged-out question ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_aged_out_question_is_EVICTED_not_re_offered(tmp_path):
    """The deadlock lock.

    ``reap_expired`` has exactly one caller, inside ``send_prompt`` — and an intercepted
    turn never reaches ``send_prompt``. So a slot that has aged out can never be swept
    while it is still being intercepted: without this branch the notice would answer every
    subsequent message in the session, forever, and the operator's only escape would be a
    command he has just been told is not needed.

    On an expired slot the state is evicted here (the reaper's own implicit-reject
    semantics) and the honest "it timed out" reply is returned instead."""
    coord = _coord(tmp_path, plan_fn=_questioning_plan())
    await _send(coord, "s", "/dispatch pottery | a website for my pottery studio")
    assert coord.pending_requirements_for("s") is not None

    # Age the slot by an hour. Backdating the stamp is what a real hour does, and it is
    # deterministic — a tiny ttl_s is NOT, because time.monotonic() has ~15 ms resolution
    # on this host and a fast test reads an age of exactly 0.0.
    coord._requirements._stamps["s"] -= 3_600.0

    notice = coord.unanswered_question_notice("s", HIS_REPLY, ttl_s=1_800.0)

    assert notice is not None, "an expired question must still get an honest reply"
    assert "timed out" in notice, "the reply must say what happened"
    assert HIS_REPLY in notice, "his words survive even on the expiry path (#1116)"
    assert coord.pending_requirements_for("s") is None, (
        "the expired slot was NOT evicted — the session is now permanently intercepted"
    )
    # And the session self-heals: the very next message reaches ordinary chat.
    assert coord.unanswered_question_notice("s", "hello again", ttl_s=1_800.0) is None


@pytest.mark.asyncio
async def test_a_live_question_is_not_evicted_by_the_ttl_branch(tmp_path):
    """Precision for the branch above: a question inside its window is answered normally
    and the slot is left alone."""
    coord = _coord(tmp_path, plan_fn=_questioning_plan())
    await _send(coord, "s", "/dispatch pottery | a website for my pottery studio")
    notice = coord.unanswered_question_notice("s", HIS_REPLY, ttl_s=1_800.0)
    assert notice and "timed out" not in notice
    assert coord.pending_requirements_for("s") is not None


@pytest.mark.asyncio
async def test_ttl_zero_disables_expiry(tmp_path):
    """Matching TtlDict's own convention, so this and the reaper cannot disagree."""
    coord = _coord(tmp_path, plan_fn=_questioning_plan())
    await _send(coord, "s", "/dispatch pottery | a website for my pottery studio")
    notice = coord.unanswered_question_notice("s", HIS_REPLY, ttl_s=0.0)
    assert notice and "timed out" not in notice


# ── the slash-prefixed near miss ───────────────────────────────────────────


# ── the CLARIFYING slot, which answers differently ─────────────────────────


#: The clarifying trigger, copied from the shape the real coordinator tests use
#: (``tests/integration/test_dispatch_coordinator.py``): an AMBIGUOUS ``build_plan`` is what
#: makes the 14B's plan park a platform question rather than go straight to the preview.
_AMBIGUOUS_BUILD_PLAN = {
    "surface": "ambiguous", "language_hint": None, "complexity": "moderate",
    "components": [], "candidates": ["desktop-gui", "web", "mobile"],
}


def _ambiguous_plan():
    """A plan_fn that parks the increment-4 PLATFORM question (#677) — the slot whose only
    answer shape is an option NUMBER."""
    async def plan_fn(repo, goal):
        return PlanResult(
            ok=True,
            spec=AcceptanceSpec(
                "an app with buttons",
                (
                    AcceptanceCriterion("c1", "the project builds", "build", ""),
                    AcceptanceCriterion("c2", "the buttons work", "behavior", ""),
                ),
                build_plan=dict(_AMBIGUOUS_BUILD_PLAN),
            ),
            tasks=[{"repo": repo, "task": "build-app", "prompt": "build it",
                    "surface": "ambiguous", "complexity": "moderate",
                    "language_hint": None}],
            message="planned",
        )
    return plan_fn


@pytest.mark.asyncio
async def test_the_clarifying_notice_never_prints_a_line_the_corridor_refuses(tmp_path):
    """The pre-merge finding, locked.

    The clarifying slot is consumed by exactly ONE command kind — ``choose`` (a bare digit,
    ``use N``, ``choose N``). Free text falls past that routing into ``_plan``, whose
    empty-repo branch returns the usage line and leaves the question pending. So prefixing
    whatever the operator typed — correct for the requirements slot — printed a
    ready-to-send block that does not work, which is the #1116/#1126/#1406 class authored
    inside the fix for it.

    Whatever this notice offers as a thing to send must be accepted by the REAL parser as a
    command the clarifying slot can consume. Nothing weaker: "it parses" is what let the
    bad version through."""
    coord = _coord(tmp_path, plan_fn=_ambiguous_plan())
    await _send(coord, "s", "/dispatch calc | a calculator")
    if coord.pending_clarification_for("s") is None:
        pytest.skip("this build does not park a platform question for this plan shape")

    for typed in ("in a web browser please", "the second one", "mostly on computer",
                  "use two", "3", "99", "2 please", "two"):
        notice = coord.unanswered_question_notice("s", typed)
        assert notice, f"no notice for {typed!r}"
        assert typed in notice, "the operator's words must come back (#1116)"
        assert not _command_blocks(notice), (
            f"the notice offered a ready-to-send block for {typed!r}. None of these reach "
            f"the question: free text returns the usage line, and `use two` / `3` / `99` "
            f"parse as a CHOICE the resolver cannot place, which drops the question and "
            f"plans without his platform"
        )


@pytest.mark.asyncio
async def test_the_clarifying_notice_does_not_promise_free_text_is_taken(tmp_path):
    """The other half of the same finding: the consequence sentence was copied by analogy
    from the requirements slot, where it is true. Here it is not."""
    coord = _coord(tmp_path, plan_fn=_ambiguous_plan())
    await _send(coord, "s", "/dispatch calc | a calculator")
    if coord.pending_clarification_for("s") is None:
        pytest.skip("this build does not park a platform question for this plan shape")

    notice = coord.unanswered_question_notice("s", "in a web browser please")
    assert "taken as your answers" not in notice, (
        "that sentence is true of the requirements set and false here"
    )
    assert "/dispatch 2" in notice, "the form that DOES work must be named"


@pytest.mark.asyncio
async def test_a_real_option_number_still_gets_a_working_block(tmp_path):
    """Precision: when the operator DID type something the slot can consume, the
    ready-to-send block must still appear. A notice that never offers one is safe and
    useless."""
    coord = _coord(tmp_path, plan_fn=_ambiguous_plan())
    await _send(coord, "s", "/dispatch calc | a calculator")
    if coord.pending_clarification_for("s") is None:
        pytest.skip("this build does not park a platform question for this plan shape")

    notice = coord.unanswered_question_notice("s", "2")
    blocks = _command_blocks(notice)
    assert blocks, "a bare option number is exactly what this slot wants — offer the block"

    # THE BEHAVIOURAL ORACLE. An earlier version of this test asserted that the block parses
    # to kind="choose" — which is the implementation's own accept condition restated, so it
    # could not fail for any input the implementation would print. A lock whose assertion is
    # the code's own predicate is not a lock. Send the line instead and require the QUESTION
    # to be answered.
    reply = await _send(coord, "s", blocks[0])
    assert coord.pending_clarification_for("s") is None, (
        "sending the block the notice printed did not resolve the question"
    )
    assert "didn't catch which option" not in reply, (
        "the block took the FALL-BACK branch — the question was dropped and the plan built "
        "without his platform, which is worse than the silence this fix replaced"
    )


@pytest.mark.asyncio
async def test_a_slash_prefixed_message_still_gets_the_notice_without_a_bad_block(tmp_path):
    """A message beginning with ``/`` reaches this fallback only when no command family
    claimed it — a typo, or a verb that does not exist. It still deserves the notice, but
    prefixing it would print ``/dispatch /dispath …``, so the copy block is withheld and
    the plain verbatim echo carries the words instead."""
    coord = _coord(tmp_path, plan_fn=_questioning_plan())
    await _send(coord, "s", "/dispatch pottery | a website for my pottery studio")
    typo = "/dispath 1. mostly on computer"
    notice = coord.unanswered_question_notice("s", typo)

    assert notice and typo in notice, "his words must still come back"
    assert f"/dispatch {typo}" not in notice, (
        "a double-prefixed command was printed as the thing to send"
    )
