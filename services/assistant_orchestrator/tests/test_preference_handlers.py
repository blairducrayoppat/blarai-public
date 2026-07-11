"""
AO preference handlers (#770 M1) — the write door + the pinned-block wiring.
=============================================================================
Drives the REAL ``AssistantOrchestratorService`` handler methods over a real
in-memory ``EncryptedKnowledgeBank`` (the test_knowledge_bank_wiring pattern):
PREFERENCE_WRITE (remember/edit/delete — P4/P5/P8 semantics), PREFERENCE_LIST,
and the ``_effective_system_prompt`` / cache lifecycle (P9).
"""

from __future__ import annotations

import numpy as np
import pytest

from services.assistant_orchestrator.src.entrypoint import (
    AssistantOrchestratorService,
)
from services.assistant_orchestrator.src.gpu_inference import (
    _DEFAULT_SYSTEM_PROMPT,
)
from services.assistant_orchestrator.src.knowledge_bank import (
    EMBED_DIM,
    EncryptedKnowledgeBank,
)
from shared.ipc.protocol import MessageFramer, MessageType
from shared.preference_budgets import PREFERENCE_BODY_MAX_CHARS
from shared.security.dek_envelope import DekEnvelope, generate_recovery_key
from shared.security.field_cipher import FieldCipher, derive_subkeys
from shared.security.tpm_sealer import SoftwareSealer


class _FakeTransport:
    """Minimal stand-in that captures outbound frames."""

    def __init__(self) -> None:
        self.sent: list[bytes] = []

    def send(self, data: bytes) -> bool:
        self.sent.append(data)
        return True


def _fake_embed(texts: list[str]) -> np.ndarray:
    out = np.zeros((len(texts), EMBED_DIM), dtype=np.float32)
    out[:, 0] = 1.0
    return out


def _make_cipher() -> FieldCipher:
    env = DekEnvelope.create(
        sealer=SoftwareSealer(), recovery_key=generate_recovery_key()
    )
    return FieldCipher(derive_subkeys(env.unseal_dek()))


_framer = MessageFramer()


@pytest.fixture()
def service() -> AssistantOrchestratorService:
    svc = AssistantOrchestratorService("dummy.toml")
    svc._knowledge = EncryptedKnowledgeBank(
        db_path=":memory:", embed_fn=_fake_embed, cipher=_make_cipher()
    )
    yield svc
    svc._knowledge.close()


def _write(
    service, op: str, body: str = "", pref_id: str = "", token: str = "",
    expires: str = "",
) -> dict:
    transport = _FakeTransport()
    # Drive the handler with a raw payload (op validation is the handler's).
    ok = service._handle_preference_write_request(
        transport, "req-1",
        {"op": op, "body": body, "pref_id": pref_id, "token": token,
         "expires": expires},
    )
    assert ok
    return _framer.decode_preference_write_result(transport.sent[-1])


def _listing(service) -> dict:
    transport = _FakeTransport()
    assert service._handle_preference_list_request(transport, "req-2", {})
    return _framer.decode_preference_list_response(transport.sent[-1])


# ---------------------------------------------------------------------------
# remember
# ---------------------------------------------------------------------------


class TestRemember:
    def test_stores_verbatim_and_reports_stored(self, service) -> None:
        result = _write(service, "remember", body="Always call me Blair")
        assert result["ok"] and result["status"] == "stored"
        listing = _listing(service)
        assert listing["total"] == 1
        assert listing["preferences"][0]["body"] == "Always call me Blair"

    def test_near_duplicate_requires_confirmation_and_stores_nothing(
        self, service
    ) -> None:
        _write(service, "remember", body="always use metric units")
        result = _write(service, "remember", body="always use metric units please")
        assert result["status"] == "requires_confirmation"
        assert result["conflict"]["body"] == "always use metric units"
        assert _listing(service)["total"] == 1  # NOTHING was stored (P5 stub)

    def test_near_duplicate_stages_a_one_step_replace_confirm(self, service) -> None:
        # #770 M2 W2 — the near-dup returns a staged REPLACE token; confirming it
        # supersedes in place (one step, no /preferences edit hop).
        _write(service, "remember", body="always use imperial units")
        result = _write(service, "remember", body="always use imperial units please")
        assert result["status"] == "requires_confirmation"
        token = result["token"]
        assert token and service._proposal_staging.count() == 1
        confirmed = _write(service, "confirm", token=token)
        assert confirmed["status"] == "updated"
        listing = _listing(service)
        assert listing["total"] == 1
        assert listing["preferences"][0]["body"] == "always use imperial units please"

    def test_store_cap_refusals_surface_stable_codes(self, service) -> None:
        result = _write(
            service, "remember", body="x" * (PREFERENCE_BODY_MAX_CHARS + 1)
        )
        assert not result["ok"]
        assert result["status"] == "refused"
        assert result["error_code"] == "PREFERENCE_BODY_TOO_LONG"

    def test_token_cap_pre_check_refuses_before_the_store(self, service) -> None:
        # Fill with DISSIMILAR max-length bodies until the block cap binds.
        # Vocabularies are disjoint so the P5 similarity probe never fires.
        refused = None
        for i in range(64):
            words = [f"tok{i}w{j}" for j in range(60)]
            body = (" ".join(words))[:PREFERENCE_BODY_MAX_CHARS]
            result = _write(service, "remember", body=body)
            if result["status"] == "refused":
                refused = result
                break
        assert refused is not None, "the token cap never bound — cap dead?"
        assert refused["error_code"] == "PREFERENCE_TOKEN_CAP"
        # Everything actually stored still fits the budget-checked render.
        from services.assistant_orchestrator.src.preference_block import (
            block_fits_budget,
        )

        assert block_fits_budget(service._knowledge.list_preferences())

    def test_empty_body_refused(self, service) -> None:
        result = _write(service, "remember", body="   ")
        assert result["status"] == "refused"
        assert result["error_code"] == "PREFERENCE_EMPTY"

    def test_remember_threads_expires_to_the_store(self, service) -> None:
        # #770 M2 W2 — the operator-stated expiry rides the write door to the store.
        result = _write(
            service, "remember", body="answer in French", expires="2026-07-15"
        )
        assert result["status"] == "stored"
        (row,) = service._knowledge.list_preferences()
        assert row.expires == "2026-07-15"


# ---------------------------------------------------------------------------
# edit / delete
# ---------------------------------------------------------------------------


class TestEditDelete:
    def test_edit_updates_last_writer_wins(self, service) -> None:
        _write(service, "remember", body="call me Bob")
        pref_id = _listing(service)["preferences"][0]["pref_id"]
        result = _write(service, "edit", body="call me Blair", pref_id=pref_id)
        assert result["ok"] and result["status"] == "updated"
        assert _listing(service)["preferences"][0]["body"] == "call me Blair"

    def test_malformed_id_gated_before_the_store(self, service) -> None:
        for bad in ("42", "DEADBEEF", "a" * 31, "a" * 33, "../../etc", ""):
            result = _write(service, "edit", body="x", pref_id=bad)
            assert result["status"] == "refused"
            assert result["error_code"] == "INVALID_PREF_ID"

    def test_unknown_id_refused(self, service) -> None:
        result = _write(service, "edit", body="x", pref_id="f" * 32)
        assert result["error_code"] == "UNKNOWN_ID"

    def test_delete_removes_from_listing(self, service) -> None:
        _write(service, "remember", body="temporary rule")
        pref_id = _listing(service)["preferences"][0]["pref_id"]
        result = _write(service, "delete", pref_id=pref_id)
        assert result["ok"] and result["status"] == "deleted"
        assert _listing(service)["total"] == 0
        # Idempotence boundary: a second delete refuses with UNKNOWN_ID.
        assert _write(service, "delete", pref_id=pref_id)["error_code"] == "UNKNOWN_ID"

    def test_invalid_op_fail_closed(self, service) -> None:
        result = _write(service, "obliterate")
        assert result["status"] == "refused"
        assert result["error_code"] == "INVALID_OP"

    def test_no_store_refuses_writes_but_list_is_empty_ok(self) -> None:
        svc = AssistantOrchestratorService("dummy.toml")  # _knowledge is None
        result = _write(svc, "remember", body="anything")
        assert result["error_code"] == "NO_STORE"
        assert _listing(svc) == {"preferences": [], "total": 0}


# ---------------------------------------------------------------------------
# The pinned block + cache lifecycle (P3/P9)
# ---------------------------------------------------------------------------


class TestPinnedBlockWiring:
    def test_zero_preferences_keeps_default_system_prompt(self, service) -> None:
        # None => generate_text falls through to _DEFAULT_SYSTEM_PROMPT
        # byte-identically (the pre-#770 regression lock).
        assert service._effective_system_prompt() is None

    def test_no_bank_keeps_default_system_prompt(self) -> None:
        svc = AssistantOrchestratorService("dummy.toml")
        assert svc._effective_system_prompt() is None

    def test_block_composes_after_static_persona(self, service) -> None:
        _write(service, "remember", body="Always call me Blair")
        composed = service._effective_system_prompt()
        assert composed is not None
        assert composed.startswith(_DEFAULT_SYSTEM_PROMPT)
        assert "Always call me Blair" in composed
        assert "OPERATOR PREFERENCES" in composed

    def test_block_bytes_stable_across_turns(self, service) -> None:
        _write(service, "remember", body="Always call me Blair")
        first = service._effective_system_prompt()
        second = service._effective_system_prompt()
        assert first == second  # cached — the same bytes, the same KV prefix

    def test_write_invalidates_cache_exactly_once(self, service) -> None:
        _write(service, "remember", body="Always call me Blair")
        before = service._effective_system_prompt()
        _write(service, "remember", body="respond in French on Fridays")
        after = service._effective_system_prompt()
        assert after != before
        assert after.startswith(before)  # append-minimal growth (P9)

    def test_failed_write_does_not_invalidate_cache(self, service) -> None:
        _write(service, "remember", body="Always call me Blair")
        before = service._effective_system_prompt()
        _write(service, "edit", body="x", pref_id="f" * 32)  # UNKNOWN_ID
        assert service._pref_block_cache is not None  # cache untouched
        assert service._effective_system_prompt() == before

    def test_broken_store_fails_soft_to_default_prompt(self, service) -> None:
        service._knowledge.close()  # a dead bank must not kill conversation
        service._pref_block_cache = None
        assert service._effective_system_prompt() is None


# ---------------------------------------------------------------------------
# Routing — the new verbs reach their handlers via _handle_connection
# ---------------------------------------------------------------------------


class TestRouting:
    def test_write_and_list_verbs_routed(self, service) -> None:
        class _Conn:
            def __init__(self, inbound: bytes) -> None:
                self._inbound = inbound
                self.sent: list[bytes] = []

            def receive(self) -> bytes:
                return self._inbound

            def send(self, data: bytes) -> bool:
                self.sent.append(data)
                return True

        write_frame = _framer.encode_preference_write_request(
            op="remember", body="routed preference", request_id="r-1"
        )
        conn = _Conn(write_frame)
        assert service._handle_connection(conn)
        decoded = _framer.decode_preference_write_result(conn.sent[-1])
        assert decoded["status"] == "stored"

        list_frame = _framer.encode_preference_list_request(request_id="r-2")
        conn2 = _Conn(list_frame)
        assert service._handle_connection(conn2)
        listing = _framer.decode_preference_list_response(conn2.sent[-1])
        assert listing["total"] == 1
        assert listing["preferences"][0]["body"] == "routed preference"

    def test_message_types_exist(self) -> None:
        assert MessageType.PREFERENCE_WRITE_REQUEST.value == "PREFERENCE_WRITE_REQUEST"
        assert MessageType.PREFERENCE_WRITE_RESULT.value == "PREFERENCE_WRITE_RESULT"
        assert MessageType.PREFERENCE_LIST_REQUEST.value == "PREFERENCE_LIST_REQUEST"
        assert MessageType.PREFERENCE_LIST_RESPONSE.value == "PREFERENCE_LIST_RESPONSE"
