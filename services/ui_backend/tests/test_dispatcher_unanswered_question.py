"""#1406 at the SEAM: the real dispatcher must reach the notice, and must not swallow a
command to get there.

The coordinator half of this lock is ``tests/integration/test_dispatch_unprefixed_answer``.
This file exists because that half cannot see the thing that actually broke: ROUTING. The
defect was never a wrong string — it was a message arriving at ``send_prompt`` when it
should not have. So these tests drive :class:`RpcDispatcher` itself and assert on where
the message ENDED UP, using ``StubGateway._last_prompt`` as the observable for "reached
the assistant".

They also lock the placement. The obvious fix — hooking the notice into the dispatch
interception — would have been shorter and wrong: dispatch is intercepted BEFORE ``/coord``,
``/imagine`` and ``/remember``, so a notice hung there would eat all three for as long as a
question sat parked. Placing it after every family makes that impossible by construction,
and :func:`test_a_pending_question_does_not_swallow_other_command_families` is what keeps
it there.
"""

from __future__ import annotations

import asyncio
from typing import Any

from services.ui_backend.src._stub import StubGateway
from services.ui_backend.src.dispatcher import RpcDispatcher
from services.ui_gateway.src.session_store import SessionStore

#: What the operator actually typed on 2026-08-15 at 10:14 EDT.
HIS_REPLY = "1. mostly on computer\n2. fresh\n3. I don't know"

#: The reply he got instead of an empty bubble.
NOTICE = "I haven't taken that as your answer — send it again starting with `/dispatch`."


def _run(dispatcher: RpcDispatcher, prompt: str) -> "list[dict[str, Any]]":
    frames: list[dict[str, Any]] = []

    async def send(frame: dict[str, Any]) -> None:
        frames.append(frame)

    asyncio.run(dispatcher.handle(
        {"id": 1, "method": "prompt", "params": {"session_id": "s1", "prompt": prompt}},
        send,
    ))
    return frames


class QuestionPendingGateway(StubGateway):
    """StubGateway + the #1406 surface, plus the sibling command families so their
    ordering relative to it is exercised rather than assumed."""

    def __init__(self, *, notice: "str | None") -> None:
        super().__init__()
        self._notice = notice
        self.unanswered_calls: list[str] = []
        self.family_calls: list[tuple[str, str]] = []

    async def handle_unanswered_question(self, session_id: str, text: str) -> "str | None":
        self.unanswered_calls.append(text)
        return self._notice

    # The three families that sit ABOVE the fallback. Each claims its own verb and
    # declines everything else, exactly like the real handlers.
    async def handle_coord_command(self, session_id: str, text: str) -> "str | None":
        if text.startswith("/coord"):
            self.family_calls.append(("coord", text))
            return "Coordinator status: idle"
        return None

    async def handle_imagine_command(self, session_id: str, text: str) -> "str | None":
        if text.startswith("/imagine"):
            self.family_calls.append(("imagine", text))
            return "Generating..."
        return None

    async def handle_preferences_command(self, session_id: str, text: str) -> "str | None":
        if text.startswith(("/remember", "/preferences")):
            self.family_calls.append(("preferences", text))
            return "Noted."
        return None


def _dispatcher(gw: StubGateway) -> RpcDispatcher:
    return RpcDispatcher(gw, SessionStore(db_path=":memory:"))


# ── the regression lock ────────────────────────────────────────────────────


def test_the_unprefixed_answer_is_intercepted_and_never_reaches_the_model():
    """THE LOCK. The measured input, through the real dispatcher, must produce the notice
    as ONE informational frame pair — and ``send_prompt`` must never see it. That last
    clause is the whole defect: the empty bubble was a model call that produced no prose."""
    gw = QuestionPendingGateway(notice=NOTICE)
    frames = _run(_dispatcher(gw), HIS_REPLY)

    assert [f.get("stream") for f in frames] == ["token", "end"]
    assert frames[0]["value"]["token"] == NOTICE
    assert frames[0]["value"]["is_final"] is True
    assert frames[1]["value"]["informational"] is True
    assert gw.unanswered_calls == [HIS_REPLY]
    assert gw._last_prompt.get("s1") is None, (
        "the message reached send_prompt — this is the empty-bubble path, unfixed"
    )


# ── the toggle ─────────────────────────────────────────────────────────────


def test_WITHOUT_the_fix_the_same_message_reaches_the_model():
    """THE TOGGLE, and it is a real one: a gateway that does not carry the surface is the
    pre-#1406 system exactly (the dispatcher's getattr guard skips the block). The same
    input then lands in ``send_prompt`` — the defect, reproduced on demand.

    Without this, the lock above would pass on any dispatcher that happened to be quiet,
    and nobody would learn whether it can fail at all."""
    gw = StubGateway()  # no handle_unanswered_question — the fix is absent
    frames = _run(_dispatcher(gw), HIS_REPLY)

    assert gw._last_prompt.get("s1") == HIS_REPLY, (
        "expected the UNFIXED path to reach the model; if this fails the toggle is "
        "measuring something other than the fix"
    )
    assert frames, "the ordinary chat arc still ran to completion"


def test_the_fix_present_but_declining_also_reaches_the_model():
    """The second half of the toggle: prove the interception is driven by the notice and
    not by some other guard in the dispatcher propping the assertion up. Same gateway,
    same wiring, notice ``None``."""
    gw = QuestionPendingGateway(notice=None)
    _run(_dispatcher(gw), HIS_REPLY)

    assert gw.unanswered_calls == [HIS_REPLY], "the handler must still be consulted"
    assert gw._last_prompt.get("s1") == HIS_REPLY, (
        "a None notice must fall through to ordinary chat untouched"
    )


# ── the precision locks ────────────────────────────────────────────────────


def test_a_pending_question_does_not_swallow_other_command_families():
    """THE ANTI-HIJACK LOCK, and the reason the fallback is placed where it is.

    This gateway returns a notice for EVERYTHING — the worst case. Every command family
    must still reach its own handler, because each is intercepted before the fallback is
    ever consulted. Hook the notice into the dispatch interception instead and every
    assertion here fails: that block runs before coord, imagine and preferences."""
    gw = QuestionPendingGateway(notice=NOTICE)
    d = _dispatcher(gw)

    for prompt, family in (
        ("/coord status", "coord"),
        ("/imagine a cat", "imagine"),
        ("/remember I prefer dark mode", "preferences"),
    ):
        gw.family_calls.clear()
        gw.unanswered_calls.clear()
        frames = _run(d, prompt)
        assert gw.family_calls == [(family, prompt)], (
            f"{prompt!r} did not reach its own handler — the fallback swallowed it"
        )
        assert gw.unanswered_calls == [], (
            f"{prompt!r} reached the #1406 fallback, which means it was not claimed first"
        )
        assert frames[0]["value"]["token"] != NOTICE


def test_no_backend_command_verb_can_be_swallowed_however_it_is_routed():
    """THE LOCK THE FIRST VERSION OF THIS FILE DID NOT HAVE, and a pre-merge review found
    the gap by running the real parsers instead of reading the chain.

    The fallback's precision was argued from POSITION: it sits after ingest, dispatch,
    coord, imagine and preferences, therefore it cannot swallow a command. That reasoning
    was true and insufficient. ``/external``'s only parser lives INSIDE ``send_prompt`` —
    downstream of the whole dispatcher — so ``/external <pasted text>`` was honestly
    declined by all five families, reached the fallback, and got answered with "the message
    has to start with /dispatch" while a question was parked. The command was dead for the
    life of that question.

    Position tells you what already ran. Only the registry tells you what a message IS. So
    this drives every verb in the SHIPPED list — the same SSOT the WinUI uses to decide what
    to hand the backend — and a family added later is covered here the day it is registered,
    with no edit to this test.
    """
    import asyncio as _asyncio
    from types import SimpleNamespace

    from shared.ipc.slash_commands import BACKEND_PASSTHROUGH_SLASH_COMMANDS
    from services.ui_gateway.src.transport import TransportGateway

    assert "/external" in BACKEND_PASSTHROUGH_SLASH_COMMANDS, (
        "the verb that exposed this gap left the registry — re-derive this test's premise"
    )

    # The REAL gateway method, not a stub of it. A stub would carry whatever guard the test
    # author remembered to mirror, which is how the first version of this file passed while
    # /external was being eaten: its "families" were hand-written startswith fakes.
    # The method needs exactly two attributes, so a namespace is a faithful stand-in for the
    # gateway without constructing the model-loading real one.
    armed = SimpleNamespace(
        _dispatch_coordinator=SimpleNamespace(
            unanswered_question_notice=lambda session_id, text, ttl_s=0.0: NOTICE
        ),
        _session_state_ttl_s=1_800.0,
        _persist_informational_turn=lambda *a, **k: None,
    )
    call = TransportGateway.handle_unanswered_question

    for verb in BACKEND_PASSTHROUGH_SLASH_COMMANDS:
        prompt = f"{verb} some content the operator typed"
        assert _asyncio.run(call(armed, "s1", prompt)) is None, (
            f"{prompt!r} was claimed by the #1406 fallback. {verb} is a registered backend "
            f"command, so this answers a command with an instruction to prefix it with "
            f"/dispatch, and the command never runs."
        )

    # And the precision half: ordinary text with no registered verb IS still claimed, or the
    # guard above has been widened into switching the whole fix off.
    assert _asyncio.run(call(armed, "s1", HIS_REPLY)) == NOTICE


def test_ordinary_chat_is_untouched_when_nothing_is_pending():
    """With no question parked the coordinator returns None and the chat path is
    byte-identical — the property that keeps this fix from being modal."""
    gw = QuestionPendingGateway(notice=None)
    _run(_dispatcher(gw), "what's the weather like?")
    assert gw._last_prompt.get("s1") == "what's the weather like?"


def test_a_gateway_without_the_surface_does_not_crash():
    """The getattr guard, matching every sibling interceptor's contract: an older or
    alternate gateway shape keeps the unchanged prompt arc, no AttributeError."""
    gw = StubGateway()
    frames = _run(_dispatcher(gw), "/coord status")
    assert frames
