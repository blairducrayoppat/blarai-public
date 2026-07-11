"""
Operator-stated preference expiry (#770 M2 W2, D-4).
=====================================================
"Answer in French until Friday" is a real preference shape.  An optional,
operator-authored ``expires`` bound drops the row from the PINNED RENDER on/after
its date (P6-safe: the SYSTEM never decides to forget — only the operator's
stated bound, and nothing is auto-deleted; ``/preferences`` still lists it,
flagged expired).  These lock the render filter, the store round-trip + idempotent
migration, and the gateway ``--until`` / natural-phrase parsing.
"""

from __future__ import annotations

import datetime
from types import SimpleNamespace

import numpy as np

from services.assistant_orchestrator.src.knowledge_bank import (
    EMBED_DIM,
    EncryptedKnowledgeBank,
)
from services.assistant_orchestrator.src.preference_block import (
    preference_is_expired,
    render_preference_block,
)
from services.ui_gateway.src.preferences_coordinator import (
    _extract_expiry,
    _resolve_date_phrase,
    parse_preference_command,
)
from shared.security.dek_envelope import DekEnvelope, generate_recovery_key
from shared.security.field_cipher import FieldCipher, derive_subkeys
from shared.security.tpm_sealer import SoftwareSealer

_MARK = "<|PREF-e0a10001|>"


def _pref(body: str, expires: str = "", pref_id: str = "a" * 32) -> SimpleNamespace:
    return SimpleNamespace(
        pref_id=pref_id, type_tag="standing-rule", body=body, expires=expires
    )


# ---------------------------------------------------------------------------
# render filter (inclusive of the expiry date)
# ---------------------------------------------------------------------------


class TestRenderFilter:
    def test_expired_preference_dropped_from_render(self) -> None:
        prefs = [_pref("answer in French", expires="2026-07-09", pref_id="a" * 32)]
        block = render_preference_block(prefs, marker=_MARK, today="2026-07-10")
        assert block == ""  # expired yesterday → nothing renders

    def test_renders_through_the_expiry_date_inclusive(self) -> None:
        prefs = [_pref("answer in French", expires="2026-07-10", pref_id="a" * 32)]
        # ON the expiry date it still applies…
        assert "answer in French" in render_preference_block(
            prefs, marker=_MARK, today="2026-07-10"
        )
        # …and drops the day AFTER.
        assert render_preference_block(prefs, marker=_MARK, today="2026-07-11") == ""

    def test_no_expiry_always_renders(self) -> None:
        prefs = [_pref("call me Blair", expires="", pref_id="a" * 32)]
        assert "call me Blair" in render_preference_block(
            prefs, marker=_MARK, today="2030-01-01"
        )

    def test_mixed_only_live_rows_render(self) -> None:
        prefs = [
            _pref("live rule", expires="", pref_id="a" * 32),
            _pref("stale rule", expires="2026-07-01", pref_id="b" * 32),
        ]
        block = render_preference_block(prefs, marker=_MARK, today="2026-07-10")
        assert "live rule" in block and "stale rule" not in block

    def test_is_expired_helper(self) -> None:
        assert preference_is_expired(_pref("x", expires="2026-07-09"), "2026-07-10")
        assert not preference_is_expired(_pref("x", expires="2026-07-10"), "2026-07-10")
        assert not preference_is_expired(_pref("x", expires=""), "2030-01-01")


# ---------------------------------------------------------------------------
# store round-trip + idempotent migration
# ---------------------------------------------------------------------------


def _bank() -> EncryptedKnowledgeBank:
    def embed(texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), EMBED_DIM), dtype=np.float32)
        out[:, 0] = 1.0
        return out

    env = DekEnvelope.create(
        sealer=SoftwareSealer(), recovery_key=generate_recovery_key()
    )
    cipher = FieldCipher(derive_subkeys(env.unseal_dek()))
    return EncryptedKnowledgeBank(db_path=":memory:", embed_fn=embed, cipher=cipher)


class TestStore:
    def test_store_and_list_round_trips_expires(self) -> None:
        bank = _bank()
        try:
            bank.store_preference("answer in French", expires="2026-07-15")
            bank.store_preference("call me Blair")  # no expiry
            listed = bank.list_preferences()
            assert listed[0].expires == "2026-07-15"
            assert listed[1].expires == ""
        finally:
            bank.close()

    def test_edit_preserves_expires(self) -> None:
        bank = _bank()
        try:
            stored = bank.store_preference("answer in French", expires="2026-07-15")
            bank.update_preference(stored.pref_id, "respond in French")
            (row,) = bank.list_preferences()
            assert row.body == "respond in French"
            assert row.expires == "2026-07-15"  # the operator's bound survives an edit
        finally:
            bank.close()

    def test_migration_is_idempotent(self) -> None:
        # Re-running the migration on an already-migrated store is a no-op.
        bank = _bank()
        try:
            bank._migrate_schema()
            bank._migrate_schema()
            bank.store_preference("x", expires="2030-01-01")
            assert bank.list_preferences()[0].expires == "2030-01-01"
        finally:
            bank.close()


# ---------------------------------------------------------------------------
# gateway parsing — --until flag + natural phrasing
# ---------------------------------------------------------------------------

_TODAY = datetime.date(2026, 7, 10)  # a Friday


class TestParse:
    def test_until_flag_iso(self) -> None:
        body, expires = _extract_expiry("answer in French --until 2026-07-15", _TODAY)
        assert body == "answer in French" and expires == "2026-07-15"

    def test_trailing_until_iso(self) -> None:
        body, expires = _extract_expiry("answer in French until 2026-07-15", _TODAY)
        assert body == "answer in French" and expires == "2026-07-15"

    def test_natural_weekday_next_occurrence(self) -> None:
        # 2026-07-10 is a Friday; "until Monday" -> the coming Monday 2026-07-13.
        body, expires = _extract_expiry("answer in French until Monday", _TODAY)
        assert body == "answer in French" and expires == "2026-07-13"

    def test_weekday_today_is_inclusive(self) -> None:
        # "until Friday" on a Friday resolves to that same Friday (through today).
        assert _resolve_date_phrase("Friday", _TODAY) == "2026-07-10"

    def test_tomorrow(self) -> None:
        assert _resolve_date_phrase("tomorrow", _TODAY) == "2026-07-11"

    def test_past_iso_is_rejected(self) -> None:
        # An expiry must be in the future; a past ISO date does not bind.
        assert _resolve_date_phrase("2026-07-01", _TODAY) == ""

    def test_unparseable_until_keeps_body_verbatim(self) -> None:
        # "wait until I say so" is NOT an expiry — the body is preserved (P2).
        body, expires = _extract_expiry("wait until I say so", _TODAY)
        assert body == "wait until I say so" and expires == ""

    def test_command_parse_lifts_expiry(self) -> None:
        cmd = parse_preference_command(
            "/remember answer in French until 2026-07-15", today=_TODAY
        )
        assert cmd.kind == "remember"
        assert cmd.body == "answer in French"
        assert cmd.expires == "2026-07-15"

    def test_command_parse_no_expiry(self) -> None:
        cmd = parse_preference_command("/remember call me Blair", today=_TODAY)
        assert cmd.body == "call me Blair" and cmd.expires == ""
