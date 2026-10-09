"""The boot prompt-flow preflight must ASSERT its round-trip, not merely survive it.

**The incident, measured 2026-08-09 14:09:22 PT on run ``20260809-140620-bd``** — found
while scoring the #1353 fix, in the log of the very run that proved it::

    14:09:22,144 ERROR: send_prompt: connect failed for request=9bb0c03c… — Fail-Closed
    14:09:22,144 WARNING: stream_tokens: receive returned None — stream ended
    14:09:22,144 INFO: get_pgov_result: request=9bb0c03c… — not in cache (default deny)
    14:09:22,155 INFO: Startup: Minimal prompt-flow preflight passed ✓

Eleven milliseconds. The connect failed, nothing came back, the governance lookup
default-denied, and the launcher declared the preflight **passed**.

The cause is one missing assertion. ``gateway.send_prompt`` does not raise when the
connect fails — it logs ``Fail-Closed`` and returns the ``request_id`` anyway, which is
deliberate and right for the interactive path, where the UI renders the empty stream.
``_run_uat2_prompt_flow_preflight`` wrapped the round-trip in ``try/except`` and returned
``True`` for anything that did not raise. Zero tokens, an empty response and a denied
PGOV result raise nothing, so they scored ``PASS``.

**Why that is worse than a missing check.** This preflight's stated purpose, in its own
comment, is to be *"the gate that would have caught the host-mode PROMPT_REQUEST misroute
at boot instead of at the user's first prompt"*. A misroute produces exactly the signature
above. The gate could never have caught the defect it was built for, and reported ✓ every
boot while unable to.

**What this module locks.** Two properties, and neither is sufficient alone:

1. **ASSERT** — a round-trip that returns nothing FAILS. Toggle-proved below against the
   exact 2026-08-09 shape, so a green suite here is not merely a test that cannot reach
   the control (security_by_design principle 12).
2. **RETRY** — asserting without retrying would convert every busy box into a boot
   failure, which is #1353's failure shape (a startup deadline tearing down a live
   assistant) arriving from a new direction. The retry is also what makes the assertion
   *diagnostic*: a misroute stays broken across attempts, contention clears, and a single
   attempt cannot tell them apart because both return zero tokens.

**Honest limit.** These are fakes at the function's own seam, not a live AO. They prove
the preflight's verdict logic given what the gateway hands it; they do not prove the
gateway reports contention faithfully. The live evidence for that is the run cited above.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import AsyncIterator

import pytest

from launcher.__main__ import (
    PROMPT_FLOW_EVIDENCE_PATH_ENV,
    _run_uat2_prompt_flow_preflight,
)
from shared.runtime_config import DeploymentMode


class _Token:
    """Minimal stand-in for the gateway's StreamToken (only ``.token`` is read)."""

    def __init__(self, token: str) -> None:
        self.token = token


class _PGOVResult:
    def __init__(self, *, approved: bool, sanitized_text: str = "") -> None:
        self.approved = approved
        self.reason_codes: list[str] = [] if approved else ["DEFAULT_DENY"]
        self.sanitized_text = sanitized_text


class _FakeGateway:
    """A gateway whose round-trip outcome is scripted per attempt.

    ``outcomes`` is one entry per attempt: a list of token strings (possibly empty).
    The last entry repeats once exhausted, so an always-broken path is expressible.
    """

    def __init__(
        self,
        outcomes: list[list[str]],
        *,
        sanitized_text: str = "",
        raise_on_send: bool = False,
    ) -> None:
        self._outcomes = outcomes
        self._sanitized_text = sanitized_text
        self._raise_on_send = raise_on_send
        self.attempts = 0

    def _current(self) -> list[str]:
        index = min(self.attempts - 1, len(self._outcomes) - 1)
        return self._outcomes[index]

    async def send_prompt(self, session_id: str, prompt: str) -> str:
        self.attempts += 1
        if self._raise_on_send:
            raise ConnectionError("transport exploded")
        # NOTE: the real send_prompt does NOT raise on a failed connect. It logs
        # Fail-Closed and returns the request_id anyway. That is the whole defect.
        return f"req-{self.attempts}"

    async def stream_tokens(self, session_id: str) -> AsyncIterator[_Token]:
        for token in self._current():
            yield _Token(token)

    def get_pgov_result(self, request_id: str) -> _PGOVResult:
        tokens = self._current()
        if tokens:
            return _PGOVResult(approved=True)
        return _PGOVResult(approved=False, sanitized_text=self._sanitized_text)


class _FakeSessionStore:
    def __init__(self) -> None:
        self.created: list[str] = []
        self.deleted: list[str] = []
        self.turns: list[dict[str, object]] = []

    def create_session(self, *, title: str) -> str:
        session_id = f"sess-{len(self.created) + 1}"
        self.created.append(session_id)
        return session_id

    def add_turn(self, **kwargs: object) -> None:
        self.turns.append(kwargs)

    def delete_session(self, session_id: str) -> None:
        self.deleted.append(session_id)


@pytest.fixture
def evidence_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the preflight's evidence file into the test's own tmp dir."""
    path = tmp_path / "prompt-flow-evidence.json"
    monkeypatch.setenv(PROMPT_FLOW_EVIDENCE_PATH_ENV, str(path))
    return path


@pytest.fixture
def fast_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """Shrink the retry budget so the tests exercise the loop without waiting on it."""
    monkeypatch.setattr("launcher.__main__.PROMPT_FLOW_PREFLIGHT_BUDGET_S", 0.30)
    monkeypatch.setattr("launcher.__main__.PROMPT_FLOW_PREFLIGHT_BACKOFF_S", 0.01)


def _run(gateway: _FakeGateway, store: _FakeSessionStore) -> bool:
    return _run_uat2_prompt_flow_preflight(
        gateway=gateway,  # type: ignore[arg-type]
        session_store=store,  # type: ignore[arg-type]
        runtime_mode=DeploymentMode.HOST,
    )


# ---------------------------------------------------------------------------
# 1. The toggle proof: the exact shape that shipped a false ✓
# ---------------------------------------------------------------------------


def test_a_roundtrip_that_returns_nothing_is_not_a_pass(
    evidence_path: Path, fast_budget: None
) -> None:
    """THE INCIDENT. Zero tokens, default-denied PGOV, no exception — must FAIL.

    Before #1355 this returned True, and the launcher printed "passed ✓". If this test
    ever goes green-by-passing again, the assertion has been removed and the gate is
    once more incapable of catching the misroute it exists for.
    """
    gateway = _FakeGateway([[]])  # every attempt yields nothing, nothing raises
    store = _FakeSessionStore()

    assert _run(gateway, store) is False, (
        "a round-trip that returned 0 tokens and an empty response scored PASS — this is "
        "the 2026-08-09 fail-open (#1355) back in the tree"
    )


def test_the_failure_is_recorded_as_an_empty_response_not_a_generic_error(
    evidence_path: Path, fast_budget: None
) -> None:
    """The evidence must name what actually happened — an instrument-honesty property.

    "something threw" and "it came back empty" are different defects with different
    fixes. A record that cannot tell them apart is why #1353 cost eight hypotheses.
    """
    gateway = _FakeGateway([[]])
    _run(gateway, _FakeSessionStore())

    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert payload["disposition"] == "FAIL"
    assert payload["failure"]["code"] == "UAT2_PROMPT_FLOW_EMPTY_RESPONSE"
    assert payload["failure"]["fail_closed"] == "true"
    assert payload["token_count"] == 0
    # The count of attempts spent is itself evidence: one attempt means the budget
    # never engaged, which would be a different defect than a genuinely broken path.
    assert payload["attempts"] >= 1
    assert "attempt(s) over" in payload["failure"]["message"]


# ---------------------------------------------------------------------------
# 2. The control does not over-fire
# ---------------------------------------------------------------------------


def test_a_real_roundtrip_passes(evidence_path: Path, fast_budget: None) -> None:
    """Tokens came back — that is what a working prompt path looks like."""
    gateway = _FakeGateway([["Hel", "lo"]])
    store = _FakeSessionStore()

    assert _run(gateway, store) is True
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert payload["disposition"] == "PASS"
    assert payload["token_count"] == 2
    assert payload["attempts"] == 1


def test_a_sanitized_response_with_no_streamed_tokens_still_passes(
    evidence_path: Path, fast_budget: None
) -> None:
    """A PGOV-sanitized answer is a real answer.

    The preflight's success condition is "something came back", not "tokens streamed" —
    a governed response that arrives only via ``sanitized_text`` is a working prompt
    path, and failing it would be the false-positive class that gets a gate muted.
    """
    gateway = _FakeGateway([[]], sanitized_text="[sanitized answer]")
    assert _run(gateway, _FakeSessionStore()) is True


def test_an_exception_fails_closed_immediately_without_retrying(
    evidence_path: Path, fast_budget: None
) -> None:
    """A RAISED exception is not the contention signature, so it is not retried.

    Contention is silent by construction — ``send_prompt`` swallows the failed connect,
    so a busy box arrives as an EMPTY result, never as an exception. Something that
    actually raised broke in a way the transport did not handle. Retrying that would
    spend the entire budget on every genuine breakage before reporting it, and the
    pre-#1355 behaviour (fail fast) is right for exactly this path.

    Locked because the retry loop makes the opposite mistake cheap to introduce: a
    single `except` moved above the `return` would silently convert every hard failure
    into a ten-minute boot hang. ``launcher/tests/test_launcher.py`` caught precisely
    that while this fix was being written.
    """
    gateway = _FakeGateway([[]], raise_on_send=True)
    assert _run(gateway, _FakeSessionStore()) is False
    assert gateway.attempts == 1, (
        f"a raising round-trip was retried {gateway.attempts} times — an exception must "
        "fail fast, or every genuine breakage costs a full budget of boot time"
    )

    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert payload["failure"]["code"] == "UAT2_PROMPT_FLOW_FAILED"
    assert "transport exploded" in payload["failure"]["message"]
    assert payload["attempts"] == 1


# ---------------------------------------------------------------------------
# 3. The retry — asserting alone would boot-fail a busy box
# ---------------------------------------------------------------------------


def test_a_busy_box_clears_on_retry_instead_of_failing_the_boot(
    evidence_path: Path, fast_budget: None
) -> None:
    """Two empty round-trips then a real one — the boot must succeed.

    This is the property that keeps the fix from re-creating #1353 from the other
    direction: dispatch-asset generation saturates the GPU for a bounded interval
    (measured 303 s for 8 assets on run 20260809-140620-bd), and a boot that fails
    closed on the first timeout would tear down the assistant mid-dispatch again.
    """
    gateway = _FakeGateway([[], [], ["ok"]])
    assert _run(gateway, _FakeSessionStore()) is True
    assert gateway.attempts == 3, "the preflight gave up before the box cleared"

    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert payload["disposition"] == "PASS"
    assert payload["attempts"] == 3


def test_the_budget_bounds_a_permanently_broken_path(
    evidence_path: Path, fast_budget: None
) -> None:
    """A misroute never clears, so the loop must terminate rather than hang the boot."""
    gateway = _FakeGateway([[]])
    assert _run(gateway, _FakeSessionStore()) is False
    assert gateway.attempts >= 2, (
        "the budget expired without a second attempt — retry and assertion must ship "
        "together, or the assertion alone boot-fails a merely-busy box"
    )


def test_every_attempt_discards_its_ephemeral_session(
    evidence_path: Path, fast_budget: None
) -> None:
    """Retrying must not leave health-check sessions in the operator's session list.

    A pre-#1355 single-shot preflight deleted one session; a retry loop that forgets
    this litters one per attempt on every boot of a busy machine.
    """
    gateway = _FakeGateway([[], [], ["ok"]])
    store = _FakeSessionStore()
    _run(gateway, store)

    assert store.created, "the preflight created no session at all"
    assert sorted(set(store.deleted)) == sorted(set(store.created)), (
        f"sessions leaked: created={store.created} deleted={store.deleted}"
    )
    # Exactly once each, not once-per-code-path. The first draft of this fix discarded
    # on the success branch AND in the `finally`, double-deleting every passing boot's
    # session; launcher/tests/test_launcher.py's assert_called_once_with caught it.
    assert len(store.deleted) == len(set(store.deleted)), (
        f"a session was deleted more than once: {store.deleted}"
    )
