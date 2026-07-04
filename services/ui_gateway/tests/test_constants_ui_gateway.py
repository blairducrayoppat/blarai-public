"""
UI Gateway Constants — Direct Wiring Assertions (WI-12, P1.11).

Pins every constant in services/ui_gateway/src/constants.py to its
authoritative value. Catches accidental drift.
"""

from __future__ import annotations

import os

from services.ui_gateway.src import constants as gw_constants


class TestUiGatewayConstants:
    """WI-12: Exact-value assertions for every UI Gateway constant."""

    # ── Session Database ──────────────────────────────────────────

    def test_session_db_filename(self) -> None:
        assert gw_constants.SESSION_DB_FILENAME == "sessions.db"

    def test_session_db_path_ends_with_filename(self) -> None:
        if gw_constants.SESSION_DB_PATH:
            assert gw_constants.SESSION_DB_PATH.endswith(
                gw_constants.SESSION_DB_FILENAME
            )

    def test_session_db_dir_is_absolute_when_set(self) -> None:
        if gw_constants.SESSION_DB_DIR:
            assert os.path.isabs(gw_constants.SESSION_DB_DIR)

    def test_session_db_dir_ends_with_blarai_when_set(self) -> None:
        if gw_constants.SESSION_DB_DIR:
            assert gw_constants.SESSION_DB_DIR.endswith("BlarAI")

    def test_session_db_path_derived_from_dir_and_filename(self) -> None:
        if gw_constants.SESSION_DB_DIR:
            expected = os.path.join(
                gw_constants.SESSION_DB_DIR, gw_constants.SESSION_DB_FILENAME
            )
            assert gw_constants.SESSION_DB_PATH == expected

    # ── Boot-Phase-3 Handshake ────────────────────────────────────

    def test_pa_handshake_max_retries(self) -> None:
        assert gw_constants.PA_HANDSHAKE_MAX_RETRIES == 3

    def test_pa_handshake_backoff_base_s(self) -> None:
        assert gw_constants.PA_HANDSHAKE_BACKOFF_BASE_S == 1.0

    def test_pa_handshake_timeout_s(self) -> None:
        assert gw_constants.PA_HANDSHAKE_TIMEOUT_S == 5.0

    def test_prompt_response_timeout_s(self) -> None:
        # Raised 120 -> 180 (#561): headroom for a vision turn (VLM load +
        # describe + up to two 14B generations) so it is not false-denied.
        assert gw_constants.PROMPT_RESPONSE_TIMEOUT_S == 180.0

    # ── Streaming ─────────────────────────────────────────────────

    def test_stream_token_buffer_limit(self) -> None:
        assert gw_constants.STREAM_TOKEN_BUFFER_LIMIT == 4_096

    def test_tool_call_buffer_max_tokens(self) -> None:
        assert gw_constants.TOOL_CALL_BUFFER_MAX_TOKENS == 512

    # ── Session Limits ────────────────────────────────────────────

    def test_session_title_max_chars(self) -> None:
        assert gw_constants.SESSION_TITLE_MAX_CHARS == 80

    # ── Type checks ───────────────────────────────────────────────

    def test_pa_handshake_max_retries_is_int(self) -> None:
        assert isinstance(gw_constants.PA_HANDSHAKE_MAX_RETRIES, int)

    def test_pa_handshake_backoff_base_s_is_float(self) -> None:
        assert isinstance(gw_constants.PA_HANDSHAKE_BACKOFF_BASE_S, float)

    def test_stream_token_buffer_limit_is_int(self) -> None:
        assert isinstance(gw_constants.STREAM_TOKEN_BUFFER_LIMIT, int)

    def test_tool_call_buffer_max_tokens_is_int(self) -> None:
        assert isinstance(gw_constants.TOOL_CALL_BUFFER_MAX_TOKENS, int)
