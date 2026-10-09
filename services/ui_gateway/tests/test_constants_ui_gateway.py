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
        # #808: derived from the 180 s budgeted schedule (was a hand-pinned 3;
        # the ~15-18 s aggregate contradicted the documented cold-14B ceiling).
        assert gw_constants.PA_HANDSHAKE_MAX_RETRIES == 25

    def test_pa_handshake_backoff_base_s(self) -> None:
        assert gw_constants.PA_HANDSHAKE_BACKOFF_BASE_S == 1.0

    def test_pa_handshake_timeout_s(self) -> None:
        assert gw_constants.PA_HANDSHAKE_TIMEOUT_S == 30.0

    def test_pa_handshake_backoff_cap_s(self) -> None:
        # #808: tail probe interval — worst-case staleness after the PA
        # becomes ready inside the budget.
        assert gw_constants.PA_HANDSHAKE_BACKOFF_CAP_S == 30.0

    def test_pa_handshake_budget_s(self) -> None:
        # #808: aggregate planned backoff = the documented cold-14B-load
        # ceiling (real_backend_ready / AoReensurer.boot_wait_s = 180 s).
        assert gw_constants.PA_HANDSHAKE_BUDGET_S == 600.0

    def test_pa_handshake_schedule_shape(self) -> None:
        """#808: the schedule is the executable truth — pin its shape.

        Early attempts stay fast (the healthy path is unchanged; a quick
        recovery is caught in seconds), the tail probes at the cap, and the
        planned sleeps sum EXACTLY to the budget.
        """
        schedule = gw_constants.pa_handshake_backoff_schedule()
        cap = gw_constants.PA_HANDSHAKE_BACKOFF_CAP_S

        # The healthy path is the load-bearing half: a PA that comes up promptly is caught
        # in the first second regardless of how the tail is tuned.
        assert schedule[:4] == (1.0, 2.0, 4.0, 8.0)

        # DOUBLE UNTIL THE CAP, THEN HOLD. The earlier form asserted every step past index 4
        # equalled the cap, which was only true while the cap sat BELOW the next doubling
        # step. Raising it to 30 s (#1353) made 16 a legitimate doubling step and reddened a
        # test that was pinning an accident of the old value rather than the rule.
        for earlier, later in zip(schedule, schedule[1:]):
            assert later >= earlier or later == schedule[-1], (
                "sleeps must be non-decreasing until the trimmed final step"
            )
        assert all(0 < d <= cap for d in schedule), "no sleep may exceed the cap"
        assert max(schedule) == cap, "the tail must actually reach the cap"

        # The budget is the contract: planned sleeps sum EXACTLY to it, final step trimmed.
        assert sum(schedule) == gw_constants.PA_HANDSHAKE_BUDGET_S
        assert len(schedule) + 1 == gw_constants.PA_HANDSHAKE_MAX_RETRIES

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
