"""#1116 — a parked /dispatch survives a restart, and no reply path eats operator text.

THE INCIDENT THIS LOCKS. On 2026-07-27 the operator started a project, BlarAI's #819
CLARIFY stage asked four requirements questions and told him on screen to
``reply /dispatch <your answers>``, and he typed a long free-text answer. Between the
question and the answer the app was relaunched. The chat transcript is durably stored,
so the question was still on screen instructing him to answer it — but the parked
dispatch lived only in the coordinator's in-process TtlDict and was gone. His answer
parsed as a goal-with-no-repo, fell through to ``_plan``, and came back as
``Usage: /dispatch <repo> | <goal>`` with every word discarded.

Two properties are locked here, and they are independent:
  1. DURABILITY — the parked slot survives a new coordinator over the same store.
  2. THE TEXT IS KEPT — even when durability legitimately does not save it (rejected,
     reaped, corrupt row dropped fail-closed), the operator's words come back verbatim.

Property 1 is proven with a TOGGLE-OFF twin: the same scenario with no store must FAIL
to consume the answer. Without that twin a green durability test cannot be told apart
from a test that never reached the mechanism at all.

These drive REAL DispatchCoordinator objects through the REAL parse -> handle_command
entry point over a REAL born-encrypted store on disk (dev_mode -> SoftwareSealer, real
AES-256-GCM, real AAD binding) — no mocked store, because a mocked store cannot show
that a payload round-trips through actual encryption.
"""

from __future__ import annotations

import sqlite3
import time

import pytest

from services.ui_gateway.src.dispatch_coordinator import (
    DispatchCoordinator,
    _merge_clarifications,
    parse_dispatch_command,
)
from services.ui_gateway.src.dispatch_state_store import (
    SLOT_PENDING,
    SLOT_REQUIREMENTS,
    build_dispatch_state_store,
)
from shared.fleet import acceptance as acc
from shared.fleet import clarify as _clarify
from shared.fleet import dispatch as fleet
from shared.fleet.acceptance import AcceptanceCriterion, AcceptanceSpec, PlanResult

#: The operator's real shape of reply: multi-line free-text prose, no pipe.
OPERATOR_ANSWER = (
    "1. web browser\n"
    "2. yes, of course. the website is static for now.\n"
    "3. Red might be a good secondary accent color or something.\n"
    "4. Pretty big. You have a long time and full system resources."
)


def _cfg(tmp_path):
    return fleet.FleetDispatchConfig(
        scripts_dir=tmp_path / "scripts",
        queue_path=tmp_path / "q.json",
        runs_dir=tmp_path / "runs",
        projects_dir=tmp_path / "projects",
    )


def _spec():
    return AcceptanceSpec("an author website", (
        AcceptanceCriterion("c1", "the site builds", "build", ""),
        AcceptanceCriterion("c2", "four pages exist", "behavior", "assert pages()==4"),
    ))


def _questioning_plan():
    """CLARIFY questions on the first pass; a real plan once requirements are threaded."""
    async def plan_fn(repo, goal):
        if _clarify.REQUIREMENTS_SENTINEL not in goal:
            return PlanResult(ok=True, questions=[
                {"axis": "surface", "question": "Where will you use this?"},
                {"axis": "persistence", "question": "Should it save your data?"},
            ])
        return PlanResult(
            ok=True,
            tasks=[{"repo": repo, "task": "t", "prompt": "p"}],
            spec=_spec(),
            message="planned",
        )
    return plan_fn


def _plain_plan():
    async def plan_fn(repo, goal):
        return PlanResult(
            ok=True,
            tasks=[{"repo": repo, "task": "t", "prompt": "p"}],
            spec=_spec(),
            message="planned",
        )
    return plan_fn


def _store(tmp_path):
    """A REAL born-encrypted store on disk (dev_mode: SoftwareSealer + ephemeral keystore)."""
    return build_dispatch_state_store(str(tmp_path / "dispatch_state.db"), dev_mode=True)


def _coord(tmp_path, *, plan_fn=None, execute_fn=None, store=None, memory=False):
    """A coordinator. ``memory`` mirrors ``[fleet_dispatch].project_memory`` (#1124).

    Default False == the SHIPPED posture, so every test that does not explicitly opt in
    is exercising the dormant configuration the operator actually receives. #1116
    durability tests pass ``memory=False`` by omission on purpose: a parked question
    surviving a restart carries no retention decision and must keep working with
    retention off.
    """
    return DispatchCoordinator(
        config=_cfg(tmp_path), enabled=True, plan_fn=plan_fn, execute_fn=execute_fn,
        mint_run_id=lambda: "RID-DET", state_store=store, project_memory_enabled=memory,
    )


async def _send(coord, sess, text):
    return await coord.handle_command(sess, parse_dispatch_command(text))


# ---- 1. the incident: answer a question across a restart -------------------


@pytest.mark.asyncio
async def test_requirements_answer_survives_a_restart(tmp_path):
    """THE REGRESSION LOCK for the 2026-07-27 incident."""
    store = _store(tmp_path)
    before = _coord(tmp_path, plan_fn=_questioning_plan(), store=store)
    asked = await _send(before, "s1", "/dispatch site | a website for an author")
    assert "a few quick questions" in asked

    # --- the app restarts: a brand-new coordinator, same store, empty memory ---
    after = _coord(tmp_path, plan_fn=_questioning_plan(), store=store)
    assert after.pending_requirements_for("s1") is None, "memory must start empty"
    restored = after.restore_at_boot()
    assert restored[SLOT_REQUIREMENTS] == 1
    assert after.pending_requirements_for("s1") is not None

    reply = await _send(after, "s1", f"/dispatch {OPERATOR_ANSWER}")

    # The answer was CONSUMED (re-planned into a criteria preview), not nagged at.
    assert "Usage: /dispatch" not in reply
    assert "I don't have that question open" not in reply
    assert "the site builds" in reply, "the re-planned criteria preview should render"
    # The question is resolved, so nothing may be resurrected by a later boot.
    assert after.pending_requirements_for("s1") is None
    third = _coord(tmp_path, plan_fn=_questioning_plan(), store=store)
    third.restore_at_boot()
    assert third.pending_requirements_for("s1") is None


@pytest.mark.asyncio
async def test_toggle_off_without_the_store_the_answer_is_still_lost(tmp_path):
    """The toggle-off twin: with no store the SAME scenario must fail to consume.

    This is what distinguishes "durability works" from "the test never reached it".
    """
    before = _coord(tmp_path, plan_fn=_questioning_plan(), store=None)
    assert "a few quick questions" in await _send(
        before, "s1", "/dispatch site | a website for an author"
    )

    after = _coord(tmp_path, plan_fn=_questioning_plan(), store=None)
    assert after.restore_at_boot() == {
        SLOT_REQUIREMENTS: 0, "clarifying": 0, SLOT_PENDING: 0,
    }
    reply = await _send(after, "s1", f"/dispatch {OPERATOR_ANSWER}")
    assert "Usage: /dispatch" in reply, "no store -> the pre-#1116 outcome"
    # ...but even then, the words are NOT destroyed (property 2 is independent).
    assert OPERATOR_ANSWER in reply


# ---- 2. the plan card: "respond with changes" across a restart -------------


@pytest.mark.asyncio
async def test_pending_plan_and_revise_survive_a_restart(tmp_path):
    store = _store(tmp_path)
    before = _coord(tmp_path, plan_fn=_plain_plan(), store=store)
    assert "the site builds" in await _send(before, "s1", "/dispatch site | a website")

    after = _coord(tmp_path, plan_fn=_plain_plan(), store=store)
    assert after.restore_at_boot()[SLOT_PENDING] == 1
    revived = after.pending_for("s1")
    assert revived is not None
    assert revived.run_id == "RID-DET"
    assert revived.goal == "a website"
    assert [t["task"] for t in revived.tasks] == ["t"]
    # The spec round-tripped through encryption with its criteria intact.
    assert [c.id for c in revived.spec.criteria] == ["c1", "c2"]

    # The operator's change request now lands on a real plan instead of a dead end.
    reply = await _send(after, "s1", "/dispatch revise make the buttons bigger")
    assert "There's no plan waiting to change" not in reply


@pytest.mark.asyncio
async def test_approve_survives_a_restart_and_then_clears_the_store(tmp_path):
    store = _store(tmp_path)
    fired: list = []

    async def execute_fn(session_id, run_id, repo, tasks, spec):
        fired.append(run_id)
        return fleet.DispatchResult(ok=True, run_id=run_id, message="dispatched")

    before = _coord(tmp_path, plan_fn=_plain_plan(), store=store)
    await _send(before, "s1", "/dispatch site | a website")

    after = _coord(tmp_path, plan_fn=_plain_plan(), execute_fn=execute_fn, store=store)
    after.restore_at_boot()
    assert "dispatched" in await _send(after, "s1", "/dispatch approve")
    assert fired == ["RID-DET"], "the restored plan is the one that fired"

    third = _coord(tmp_path, plan_fn=_plain_plan(), store=store)
    third.restore_at_boot()
    assert third.pending_for("s1") is None, "an executed plan must never come back"


# ---- 3. resolutions clear the durable row (no resurrection) ----------------


@pytest.mark.asyncio
async def test_reject_clears_the_durable_row(tmp_path):
    store = _store(tmp_path)
    coord = _coord(tmp_path, plan_fn=_questioning_plan(), store=store)
    await _send(coord, "s1", "/dispatch site | a website for an author")
    assert "Cancelled" in await _send(coord, "s1", "/dispatch reject")

    after = _coord(tmp_path, plan_fn=_questioning_plan(), store=store)
    after.restore_at_boot()
    assert after.pending_requirements_for("s1") is None


@pytest.mark.asyncio
async def test_reaped_slot_does_not_come_back_at_the_next_boot(tmp_path):
    """An implicit reject must be durable too — the divergence inverted."""
    store = _store(tmp_path)
    coord = _coord(tmp_path, plan_fn=_questioning_plan(), store=store)
    await _send(coord, "s1", "/dispatch site | a website for an author")
    assert coord.pending_requirements_for("s1") is not None

    # Windows' time.monotonic() granularity is ~15 ms, so the entry must be aged past
    # a real tick before a sweep can see it — a sub-millisecond TTL would silently
    # reap nothing and this test would pass without ever exercising the mechanism.
    time.sleep(0.05)
    reaped = coord.reap_expired(0.01)
    assert "s1" in reaped["requirements"]

    after = _coord(tmp_path, plan_fn=_questioning_plan(), store=store)
    after.restore_at_boot()
    assert after.pending_requirements_for("s1") is None


# ---- 4. fail-closed reads --------------------------------------------------


def test_corrupt_payload_is_dropped_not_half_restored(tmp_path):
    store = _store(tmp_path)
    store.save("s1", slot=SLOT_REQUIREMENTS, payload={"run_id": "R", "repo": "x",
                                                     "goal": "g", "questions": []})
    assert len(store.load_all()) == 1

    # Corrupt the ciphertext in place — authentication must fail.
    conn = sqlite3.connect(str(tmp_path / "dispatch_state.db"))
    conn.execute("UPDATE dispatch_pending_state SET payload = ? WHERE session_id = ?",
                 (b"not-a-valid-ciphertext", "s1"))
    conn.commit()
    conn.close()

    reopened = build_dispatch_state_store(str(tmp_path / "dispatch_state.db"), dev_mode=True)
    assert reopened.load_all() == [], "a corrupt row is never partially restored"
    # ...and it is DELETED, so it cannot fail again at every future boot.
    assert reopened.load_all() == []
    conn = sqlite3.connect(str(tmp_path / "dispatch_state.db"))
    assert conn.execute("SELECT COUNT(*) FROM dispatch_pending_state").fetchone()[0] == 0
    conn.close()


def test_payload_is_aad_bound_to_its_session_row(tmp_path):
    """A blob relocated to another chat's row fails authentication (ADR-025 §2.4).

    Without AAD binding this would restore one conversation's plan into another's.
    """
    store = _store(tmp_path)
    store.save("victim", slot=SLOT_REQUIREMENTS,
               payload={"run_id": "R", "repo": "x", "goal": "secret goal", "questions": []})
    db = str(tmp_path / "dispatch_state.db")
    conn = sqlite3.connect(db)
    blob = conn.execute(
        "SELECT payload FROM dispatch_pending_state WHERE session_id = 'victim'"
    ).fetchone()[0]
    conn.execute(
        "INSERT OR REPLACE INTO dispatch_pending_state "
        "(session_id, slot, run_id, payload, written_at) VALUES (?,?,?,?,?)",
        ("attacker", SLOT_REQUIREMENTS, "R", blob, "2026-07-27T00:00:00Z"),
    )
    conn.commit()
    conn.close()

    restored = build_dispatch_state_store(db, dev_mode=True).load_all()
    assert [r.session_id for r in restored] == ["victim"]


def test_slot_flip_no_longer_yields_a_half_restored_plan(tmp_path):
    """#1125 — the slot discriminator is INSIDE the AAD.

    Independent review proved by execution that flipping the plaintext `slot` column
    SUCCEEDED in both directions: the three payload shapes are mutually substitutable
    (all three `from_payload` functions require only run_id/repo/goal and read every
    differing field with `.get(default)`). A `requirements` -> `pending` flip therefore
    produced a PendingDispatch with zero tasks and zero criteria sitting in the approve
    slot — exactly the "half-understood plan" this module's docstring promised was
    impossible. The promise was asserted, not implemented.

    THE TOGGLE-TEST THAT WAS MISSING: this is what a control-tested-off case on the AAD
    would have caught before merge.
    """
    db = str(tmp_path / "dispatch_state.db")
    store = build_dispatch_state_store(db, dev_mode=True)
    store.save("s1", slot=SLOT_PENDING, payload={
        "run_id": "R", "repo": "site", "goal": "an author website",
        "tasks": [{"task": "t"}], "spec": AcceptanceSpec("g").to_dict(),
    })
    conn = sqlite3.connect(db)
    conn.execute("UPDATE dispatch_pending_state SET slot='requirements' WHERE session_id='s1'")
    conn.commit()
    conn.close()

    # The payload no longer authenticates under the tampered slot -> dropped, not rebuilt.
    assert build_dispatch_state_store(db, dev_mode=True).load_all() == []
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM dispatch_pending_state").fetchone()[0] == 0
    conn.close()


@pytest.mark.asyncio
async def test_approve_refuses_a_plan_with_no_steps(tmp_path):
    """#1125 defense-in-depth: the room, not just the door.

    A plan card always renders at least one step, so a zero-task pending slot cannot be
    something the operator read and approved. Even with the AAD fix closing the tamper
    route, `_approve` must not trust its slot entirely — principle 3 wants two
    independent locks on a door that fires work.
    """
    fired: list = []

    async def execute_fn(session_id, run_id, repo, tasks, spec):
        fired.append(run_id)
        return fleet.DispatchResult(ok=True, run_id=run_id, message="dispatched")

    coord = _coord(tmp_path, plan_fn=_plain_plan(), execute_fn=execute_fn, store=None)
    await _send(coord, "s1", "/dispatch site | a website")
    # Simulate a corrupted/empty slot reaching approve by any route.
    from services.ui_gateway.src.dispatch_coordinator import PendingDispatch

    coord._pending["s1"] = PendingDispatch(run_id="R", repo="site", goal="g", tasks=[])
    reply = await _send(coord, "s1", "/dispatch approve")

    assert fired == [], "an empty plan must NEVER reach execute_fn"
    assert "no steps in it" in reply
    assert coord.pending_for("s1") is None, "the corrupt slot is discarded, not retried"


@pytest.mark.asyncio
async def test_a_failed_re_park_does_not_resurrect_the_superseded_plan(tmp_path):
    """#1125 — an absent row is honest; a stale one is a lie with a signature.

    The revise path re-parks over a LIVE row without unparking first, so a failing
    write used to leave the superseded plan on disk. The operator would then restart,
    approve, and fire v1 while the transcript above them showed v2.
    """
    store = _store(tmp_path)
    coord = _coord(tmp_path, plan_fn=_plain_plan(), store=store)
    await _send(coord, "s1", "/dispatch site | a website")
    assert store.load_all(), "v1 is parked"

    # Make the NEXT park fail, then drive a re-park through the real code path.
    def _boom(*args, **kwargs):
        raise RuntimeError("disk full")

    store.save = _boom  # type: ignore[method-assign]
    coord._park("s1", SLOT_PENDING, coord.pending_for("s1"))

    assert store.load_all() == [], (
        "a failed re-park must clear the superseded row, not leave it to be restored"
    )


def test_store_refuses_an_unknown_slot(tmp_path):
    with pytest.raises(ValueError, match="unknown dispatch slot"):
        _store(tmp_path).save("s1", slot="not-a-slot", payload={})


# ---- 5. the text is never eaten -------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("command", [
    "/dispatch {text}",                      # a pipe-less reply (the incident's shape)
    "/dispatch answer {text}",               # an explicit answer with nothing pending
    "/dispatch revise {text}",               # a change request with no plan waiting
])
async def test_no_state_reply_keeps_the_operator_text_verbatim(tmp_path, command):
    coord = _coord(tmp_path, plan_fn=_plain_plan(), store=None)
    reply = await _send(coord, "s1", command.format(text=OPERATOR_ANSWER))
    assert OPERATOR_ANSWER in reply, "every word the operator typed must come back"
    assert "ready to copy" in reply


@pytest.mark.asyncio
async def test_new_project_without_a_name_keeps_the_description(tmp_path):
    """The 2026-07-27 New Project shape: a long description, the name left blank."""
    coord = _coord(tmp_path, plan_fn=_plain_plan(), store=None)
    reply = await _send(coord, "s1", f"/dispatch new | {OPERATOR_ANSWER}")
    assert OPERATOR_ANSWER in reply
    assert "short project name" in reply


@pytest.mark.asyncio
async def test_empty_reply_gets_no_empty_quote_block(tmp_path):
    coord = _coord(tmp_path, plan_fn=_plain_plan(), store=None)
    reply = await _send(coord, "s1", "/dispatch just decide for me")
    assert "ready to copy" not in reply
    assert "I don't have that question open" in reply


# ---- 6. #1120: a reject must not erase what the operator told us -----------
#
# THE INCIDENT. On 2026-07-27 BlarAI asked the operator four questions. His answers
# carried three requirements that appear NOWHERE in his goal text: a landing-page image
# carousel, red as an accent colour, and "build it big". He then rejected that plan —
# because of the UNRELATED #1118 single-page defect. On the next dispatch every one of
# those requirements was gone and the build started without them.
#
# Reject means "not this plan". It does not mean "forget everything I told you".


@pytest.mark.asyncio
async def test_answers_survive_a_reject_and_shape_the_next_dispatch(tmp_path):
    """THE REGRESSION LOCK for the 2026-07-27 answer-loss incident."""
    store = _store(tmp_path)
    seen: list = []

    def _recording_plan():
        async def plan_fn(repo, goal):
            seen.append(goal)
            if _clarify.REQUIREMENTS_SENTINEL not in goal:
                return PlanResult(ok=True, questions=[
                    {"axis": "surface", "question": "Where will you use this?"},
                ])
            return PlanResult(ok=True, tasks=[{"repo": repo, "task": "t", "prompt": "p"}],
                              spec=_spec(), message="planned")
        return plan_fn

    coord = _coord(tmp_path, plan_fn=_recording_plan(), store=store, memory=True)
    await _send(coord, "s1", "/dispatch site | a website for an author")
    # The requirement that lives ONLY in the answer, never in the goal.
    await _send(coord, "s1", "/dispatch the landing page needs an image carousel")
    assert "Cancelled" in await _send(coord, "s1", "/dispatch reject")

    seen.clear()
    reply = await _send(coord, "s1", "/dispatch site | a website for an author")

    # The carousel reached the planner even though the GOAL never mentioned it...
    assert any("carousel" in g for g in seen), (
        "the remembered answer must be threaded into the next planning goal"
    )
    # ...and the card SAYS it is carrying it, so a stale answer is correctable.
    assert "told me about this project earlier" in reply
    assert "carousel" in reply


@pytest.mark.asyncio
async def test_toggle_off_without_the_store_the_answers_are_still_lost(tmp_path):
    """The toggle-off twin: no store -> the pre-#1120 amnesia, proving reachability."""
    seen: list = []

    def _recording_plan():
        async def plan_fn(repo, goal):
            seen.append(goal)
            if _clarify.REQUIREMENTS_SENTINEL not in goal:
                return PlanResult(ok=True, questions=[
                    {"axis": "surface", "question": "Where will you use this?"},
                ])
            return PlanResult(ok=True, tasks=[{"repo": repo, "task": "t", "prompt": "p"}],
                              spec=_spec(), message="planned")
        return plan_fn

    coord = _coord(tmp_path, plan_fn=_recording_plan(), store=None, memory=True)
    await _send(coord, "s1", "/dispatch site | a website")
    await _send(coord, "s1", "/dispatch the landing page needs an image carousel")
    await _send(coord, "s1", "/dispatch reject")

    seen.clear()
    await _send(coord, "s1", "/dispatch site | a website")
    assert not any("carousel" in g for g in seen)


@pytest.mark.asyncio
async def test_a_fresh_answer_supersedes_the_remembered_one(tmp_path):
    store = _store(tmp_path)
    store.remember_answers("site", [{"question": "What colour?", "answer": "blue",
                                     "assumed": False}])
    merged = _merge_clarifications(
        store.recall_answers("site"),
        [{"question": "What colour?", "answer": "red", "assumed": False}],
    )
    assert [c["answer"] for c in merged] == ["red"], "the operator's latest word wins"
    assert merged[0]["remembered"] is False


def test_project_memory_does_not_leak_between_projects(tmp_path):
    store = _store(tmp_path)
    store.remember_answers("site-a", [{"question": "q", "answer": "carousel please",
                                       "assumed": False}])
    assert store.recall_answers("site-b") == []
    assert [c["answer"] for c in store.recall_answers("site-a")] == ["carousel please"]


def test_project_memory_survives_a_restart(tmp_path):
    db = str(tmp_path / "dispatch_state.db")
    build_dispatch_state_store(db, dev_mode=True).remember_answers(
        "site", [{"question": "q", "answer": "red accent", "assumed": False}]
    )
    reopened = build_dispatch_state_store(db, dev_mode=True)
    assert [c["answer"] for c in reopened.recall_answers("site")] == ["red accent"]


def test_unreadable_project_memory_degrades_to_amnesia_not_to_invention(tmp_path):
    """Fail-closed: a corrupt memory must yield NOTHING, never a half-decrypted answer.

    Asking the operator again is annoying; putting words in their mouth on a plan card is
    worse, so the failure direction is deliberate.
    """
    db = str(tmp_path / "dispatch_state.db")
    store = build_dispatch_state_store(db, dev_mode=True)
    store.remember_answers("site", [{"question": "q", "answer": "red accent", "assumed": False}])
    conn = sqlite3.connect(db)
    conn.execute("UPDATE dispatch_project_memory SET answers = ? WHERE repo = 'site'",
                 (b"corrupt",))
    conn.commit()
    conn.close()

    reopened = build_dispatch_state_store(db, dev_mode=True)
    assert reopened.recall_answers("site") == []
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM dispatch_project_memory").fetchone()[0] == 0
    conn.close()


@pytest.mark.asyncio
async def test_forget_clears_a_project_and_says_so(tmp_path):
    """Without a way to clear, one wrong remembered answer would shape a project forever."""
    store = _store(tmp_path)
    store.remember_answers("site", [{"question": "q", "answer": "blue", "assumed": False}])
    coord = _coord(tmp_path, plan_fn=_plain_plan(), store=store, memory=True)

    assert "Forgotten" in await _send(coord, "s1", "/dispatch forget site")
    assert store.recall_answers("site") == []
    # Idempotent + honest when there was nothing to clear.
    assert "wasn't remembering anything" in await _send(coord, "s1", "/dispatch forget site")
    # A bare verb asks which project rather than silently clearing everything.
    assert "which project" in await _send(coord, "s1", "/dispatch forget")


# ---- 7. #1124: the project-memory flag is DORMANT by default ---------------
#
# #1120 shipped LIVE with no flag. Independent review (2026-07-27) called that a
# governance breach, not a defect: retaining the operator's typed goal text indefinitely
# and replaying it into a model prompt is a privacy-posture decision CLAUDE.md reserves
# to the LA, and every neighbouring [fleet_dispatch] capability carries its own gate.
# The LA chose "add the switch, default OFF" and flips it for a validation run.
#
# These lock FULL dormancy — not a degraded mode. With the flag off nothing is recalled,
# nothing is written, and no row is created.


@pytest.mark.asyncio
async def test_project_memory_is_dormant_by_default(tmp_path):
    """The SHIPPED posture: answers are not banked and not replayed."""
    store = _store(tmp_path)
    seen: list = []

    def _recording_plan():
        async def plan_fn(repo, goal):
            seen.append(goal)
            if _clarify.REQUIREMENTS_SENTINEL not in goal:
                return PlanResult(ok=True, questions=[
                    {"axis": "surface", "question": "Where will you use this?"},
                ])
            return PlanResult(ok=True, tasks=[{"repo": repo, "task": "t", "prompt": "p"}],
                              spec=_spec(), message="planned")
        return plan_fn

    # memory= omitted -> the default the operator actually receives.
    coord = _coord(tmp_path, plan_fn=_recording_plan(), store=store)
    await _send(coord, "s1", "/dispatch site | a website for an author")
    await _send(coord, "s1", "/dispatch the landing page needs an image carousel")
    await _send(coord, "s1", "/dispatch reject")

    # NOTHING was written — dormancy is structural, not just unread.
    assert store.recall_answers("site") == []
    conn = sqlite3.connect(str(tmp_path / "dispatch_state.db"))
    assert conn.execute("SELECT COUNT(*) FROM dispatch_project_memory").fetchone()[0] == 0
    conn.close()

    # ...and nothing is replayed: the next dispatch plans the bare goal and is
    # asked the questions again (the pre-#1120 behaviour, amnesia included).
    seen.clear()
    await _send(coord, "s1", "/dispatch site | a website for an author")
    assert not any("carousel" in g for g in seen)
    assert all(_clarify.REQUIREMENTS_SENTINEL not in g for g in seen), (
        "with memory off, no requirements block may be threaded into the first pass — "
        "that sentinel is what suppresses the clarify stage"
    )


@pytest.mark.asyncio
async def test_dormant_memory_does_not_disable_1116_durability(tmp_path):
    """The two features are separately gated ON PURPOSE.

    #1116 durability (a parked question surviving a restart) carries no retention
    decision, so switching retention off must not switch durability off with it. If
    these were one flag, the LA's privacy choice would silently re-open the
    lost-answer defect #1116 exists to fix.
    """
    store = _store(tmp_path)
    before = _coord(tmp_path, plan_fn=_questioning_plan(), store=store)  # memory OFF
    assert "a few quick questions" in await _send(
        before, "s1", "/dispatch site | a website for an author"
    )
    after = _coord(tmp_path, plan_fn=_questioning_plan(), store=store)
    assert after.restore_at_boot()[SLOT_REQUIREMENTS] == 1
    reply = await _send(after, "s1", f"/dispatch {OPERATOR_ANSWER}")
    assert "Usage: /dispatch" not in reply
    assert "the site builds" in reply


@pytest.mark.asyncio
async def test_forget_still_works_while_memory_is_dormant(tmp_path):
    """Turning retention OFF must not disable the eraser for what was already banked.

    Otherwise the operator's only route to deleting data would be to turn the feature
    back ON first, which is absurd.
    """
    store = _store(tmp_path)
    store.remember_answers("site", [{"question": "q", "answer": "blue", "assumed": False}])
    coord = _coord(tmp_path, plan_fn=_plain_plan(), store=store)  # memory OFF
    assert "Forgotten" in await _send(coord, "s1", "/dispatch forget site")
    assert store.recall_answers("site") == []


def test_config_default_ships_project_memory_dormant():
    """The TOML the operator receives must have the flag OFF (the ceremony gate).

    Reads the shipped config rather than a fixture: the value that matters is the one
    on disk, and a default flipped by an unrelated edit must fail loudly here.
    """
    import tomllib
    from pathlib import Path

    cfg = Path("services/assistant_orchestrator/config/default.toml")
    data = tomllib.loads(cfg.read_text(encoding="utf-8"))
    fleet_dispatch = data.get("fleet_dispatch", {})
    assert "project_memory" in fleet_dispatch, (
        "the project_memory gate must be present and documented in default.toml"
    )
    assert fleet_dispatch["project_memory"] is False, (
        "project_memory must ship DORMANT — flipping it is an LA-present ceremony "
        "(privacy posture: indefinite retention of operator goal text)"
    )


def test_missing_project_memory_key_resolves_dormant():
    """Fail-closed: an ABSENT key must mean off, never on."""
    import dataclasses

    from services.assistant_orchestrator.src.entrypoint import (
        AssistantOrchestratorEntrypointConfig,
        AssistantOrchestratorService,
    )

    # The dataclass DEFAULT (read without constructing — the class has 18 required args).
    field = next(
        f for f in dataclasses.fields(AssistantOrchestratorEntrypointConfig)
        if f.name == "fleet_dispatch_project_memory_enabled"
    )
    assert field.default is False

    # ...and the SERVICE property, which is the value the gateway actually receives,
    # resolves dormant before start() has resolved any config at all.
    svc = AssistantOrchestratorService.__new__(AssistantOrchestratorService)
    svc._resolved_config = None
    assert svc.fleet_dispatch_project_memory_enabled is False


def test_remembered_flag_survives_the_spec_round_trip():
    """The spec crosses the IPC and lands in the acceptance record via to_dict/from_dict.

    Dropping the flag there would silently re-label every carried-forward answer as
    something the operator said in the current turn — the exact confusion #1120 exists
    to prevent.
    """
    from shared.fleet.acceptance import AcceptanceSpec as Spec

    spec = Spec("g", clarifications=(
        {"question": "q1", "answer": "carousel", "assumed": False, "remembered": True},
        {"question": "q2", "answer": "red", "assumed": False, "remembered": False},
    ))
    back = Spec.from_dict(spec.to_dict())
    assert [c["remembered"] for c in back.clarifications] == [True, False]


# ---- 8. #1126: the parser must not eat a message it half-recognises ---------
#
# On 2026-07-27 the operator pasted a numbered multi-line answer formatted as
#   /dispatch
#   1. In a web browser on this computer.
#   ...
# `startswith("/dispatch ")` was False, the parser returned None, and the whole
# message went to the ORDINARY CHAT PATH — no error, no usage line. The assistant
# burbled about /imagine while a requirements question sat waiting for exactly that
# text. It survived only because the chat path persists turns: #1116's keep-the-text
# guarantee never applied, because the handler implementing it was never called.


@pytest.mark.parametrize("separator, label", [
    ("\n", "newline — the incident's exact shape"),
    ("\t", "tab"),
    ("  ", "several spaces"),
    (" ", "single space (the only form that used to work)"),
])
def test_any_whitespace_after_the_verb_parses(separator, label):
    cmd = parse_dispatch_command(f"/dispatch{separator}1. web browser\n2. no input")
    assert cmd is not None, f"{label}: a /dispatch message must never fall through to chat"
    assert cmd.goal.startswith("1. web browser"), label


@pytest.mark.parametrize("text", ["/dispatchfoo bar", "/dispatching things", "/dispatch-now x"])
def test_a_longer_word_starting_with_the_verb_is_not_a_command(text):
    """The widening must not swallow words that merely BEGIN with the verb."""
    assert parse_dispatch_command(text) is None, text


@pytest.mark.asyncio
async def test_an_answer_beginning_forget_is_not_swallowed(tmp_path):
    """#1126 — "forget" parses as a verb, so its text lands in `repo`, not `goal`.

    An answer opening "forget about the phone for now, just the browser" was parsed
    as kind="forget" and the fallback chain omitted `repo`, so the answer blanked and
    the question was re-asked. The operator's words were gone.
    """
    coord = _coord(tmp_path, plan_fn=_questioning_plan(), store=None)
    assert "a few quick questions" in await _send(
        coord, "s1", "/dispatch site | a website for an author"
    )
    answer = "forget about the phone for now, just the browser, and save my data"
    reply = await _send(coord, "s1", f"/dispatch {answer}")

    assert "I didn't catch an answer" not in reply, (
        "the answer was blanked — the operator's words were dropped (#1126)"
    )
    assert "wasn't remembering anything" not in reply, (
        "the answer was routed to /dispatch forget instead of consumed as an answer"
    )
    assert coord.pending_requirements_for("s1") is None, (
        "a real answer must resolve the pending question"
    )


# ---- 9. #1136: deleting a chat must delete its parked dispatch --------------
#
# "Delete this chat" is the operator's erasure gesture. Until this, it removed the
# transcript from sessions.db and left the parked dispatch — goal text, typed
# answers, the whole plan — in dispatch_state.db, where restore_at_boot faithfully
# reloaded it at the next boot for a session that no longer exists.
# PRAGMA secure_delete=ON only zeroes pages once something issues a DELETE.


@pytest.mark.asyncio
async def test_forget_session_erases_memory_and_disk(tmp_path):
    store = _store(tmp_path)
    coord = _coord(tmp_path, plan_fn=_questioning_plan(), store=store)
    await _send(coord, "s1", "/dispatch site | a website for an author")
    assert coord.pending_requirements_for("s1") is not None
    assert store.load_all(), "precondition: something is parked on disk"

    assert coord.forget_session("s1") is True

    assert coord.pending_requirements_for("s1") is None, "in-memory slot cleared"
    assert store.load_all() == [], "the DISK row is gone, not just the memory"

    # ...and a later boot must not resurrect it.
    after = _coord(tmp_path, plan_fn=_questioning_plan(), store=store)
    after.restore_at_boot()
    assert after.pending_requirements_for("s1") is None


@pytest.mark.asyncio
async def test_forget_session_is_idempotent_and_honest(tmp_path):
    """Returns False when there was nothing to erase — never claims work it didn't do."""
    coord = _coord(tmp_path, plan_fn=_plain_plan(), store=_store(tmp_path))
    assert coord.forget_session("never-existed") is False


@pytest.mark.asyncio
async def test_forget_session_does_not_touch_other_chats(tmp_path):
    """Deleting one conversation must not erase another's pending work."""
    store = _store(tmp_path)
    coord = _coord(tmp_path, plan_fn=_questioning_plan(), store=store)
    await _send(coord, "keep", "/dispatch site | a website for an author")
    await _send(coord, "drop", "/dispatch other | another website")

    coord.forget_session("drop")

    assert coord.pending_requirements_for("drop") is None
    assert coord.pending_requirements_for("keep") is not None
    assert [r.session_id for r in store.load_all()] == ["keep"]


def test_the_delete_handler_actually_calls_it(tmp_path):
    """Reachability, not just definition — the built-but-wired-into-nothing class.

    A correct erase method that no delete path invokes erases nothing. Read the
    handler's source, because that wiring is the whole defect.
    """
    import inspect

    from services.ui_backend.src.dispatcher import RpcDispatcher

    source = inspect.getsource(RpcDispatcher._m_delete_session)
    assert "forget_dispatch_state" in source, (
        "_m_delete_session must erase the parked dispatch (#1136) — deleting the "
        "transcript alone leaves the goal text and plan on disk"
    )
    assert "delete_session" in source


# ---- #1197: the platform gate survives a reboot ---------------------------
#
# The operator's durability bar: "many uses, device reboots, and for complex projects."
# #1197 made the coordinator ask before riding an assumed surface. That question, and the
# axis tag it keys off, cross the born-encrypted store on the way to a restart — so if
# either failed to round-trip, the fix would silently revert to the pre-#1197 behaviour
# for exactly the operator who was interrupted. These drive a REAL store on disk.


def _surface_plan():
    """Questions on the first pass; a CLASSIFIED plan on the re-plan — the shape that
    made the model sure because the system had just told it what to think.

    #1220 F4: the build_plan comes from the REAL parser and the prompt is composed the way
    generate_plan composes it. The previous fixture hand-wrote ``candidates`` onto a
    ``command-line`` surface, which ``_parse_build_plan`` forbids, and gave every task a
    bare ``"p"`` prompt — so it could observe neither carrier of #1220."""
    import json

    async def plan_fn(repo, goal):
        if _clarify.REQUIREMENTS_SENTINEL not in goal:
            return PlanResult(ok=True, questions=[
                {"axis": "surface", "question": "Where will you use this?"},
                {"axis": "scope", "question": "How big a first version?"},
            ])
        _, req_block = _clarify.split_planning_goal(goal)
        prompt = "Build the thing."
        if req_block:
            prompt += f"{acc.REQUIREMENTS_PROMPT_MARKER}\n{req_block}"
        return PlanResult(
            ok=True, tasks=[{"repo": repo, "task": "t", "prompt": prompt}],
            spec=AcceptanceSpec(
                "a todo app",
                (AcceptanceCriterion("c1", "the site builds", "build", ""),),
                build_plan=acc._parse_build_plan(json.dumps(
                    {"surface": "command-line", "complexity": "simple"})),
            ),
            message="planned")
    return plan_fn


@pytest.mark.asyncio
async def test_the_platform_question_is_still_asked_after_a_restart(tmp_path):
    """#1197 across a reboot: the operator is interrupted between the questions and
    "just decide for me". The restored dispatch must still refuse to ride an assumed
    surface — the gate cannot depend on the process that parked it."""
    store = _store(tmp_path)
    before = _coord(tmp_path, plan_fn=_surface_plan(), store=store)
    assert "a few quick questions" in await _send(
        before, "s1", "/dispatch todo | a todo app"
    )

    after = _coord(tmp_path, plan_fn=_surface_plan(), store=store)
    assert after.restore_at_boot()[SLOT_REQUIREMENTS] == 1
    reply = await _send(after, "s1", "/dispatch just decide for me")

    assert "Where will you mainly use this?" in reply, (
        "after a restart the surface was assumed without asking — the #1197 gate did "
        "not survive the store round trip"
    )
    assert "/dispatch approve" not in reply


@pytest.mark.asyncio
async def test_the_surface_axis_survives_the_encrypted_round_trip(tmp_path):
    """The tag the gate keys off rides inside spec.to_dict() through real AES-256-GCM.
    If _coerce_clarifications ever stopped carrying it, the gate would go quietly inert
    for every restored dispatch — the #1197 failure mode, restored from disk."""
    store = _store(tmp_path)
    before = _coord(tmp_path, plan_fn=_surface_plan(), store=store)
    await _send(before, "s1", "/dispatch todo | a todo app")
    await _send(before, "s1", "/dispatch just decide for me")
    await _send(before, "s1", "/dispatch 2")  # "In a web browser"
    assert before.pending_for("s1") is not None

    after = _coord(tmp_path, plan_fn=_surface_plan(), store=store)
    assert after.restore_at_boot()[SLOT_PENDING] == 1
    restored = after.pending_for("s1").spec.clarifications

    by_axis = {c["axes"][0]: c for c in restored if c.get("axes")}
    assert set(by_axis) == {"surface", "scope"}, \
        f"axis tags did not survive the encrypted round trip: {[c.get('axes') for c in restored]}"
    # And the operator's OWN answer came back as theirs, not as an assumption.
    assert by_axis["surface"]["answer"] == "In a web browser"
    assert by_axis["surface"]["assumed"] is False
    assert by_axis["scope"]["assumed"] is True


@pytest.mark.asyncio
async def test_a_parked_platform_question_can_be_answered_after_a_restart(tmp_path):
    """The interruption that lands squarely on the new turn #1197 introduced: the
    platform menu is on screen when the app dies. Answering it after the restart must
    work, or #1197 would have added a turn that a reboot turns into a dead end."""
    store = _store(tmp_path)
    before = _coord(tmp_path, plan_fn=_surface_plan(), store=store)
    await _send(before, "s1", "/dispatch todo | a todo app")
    assert "Where will you mainly use this?" in await _send(
        before, "s1", "/dispatch just decide for me"
    )

    after = _coord(tmp_path, plan_fn=_surface_plan(), store=store)
    assert after.restore_at_boot()["clarifying"] == 1
    reply = await _send(after, "s1", "/dispatch 2")

    assert "/dispatch approve" in reply
    spec = after.pending_for("s1").spec
    assert spec.build_plan["surface"] == "web"
    surface = [c for c in spec.clarifications if c.get("axes") == ["surface"]]
    assert surface and surface[0]["answer"] == "In a web browser"
    assert surface[0]["assumed"] is False
