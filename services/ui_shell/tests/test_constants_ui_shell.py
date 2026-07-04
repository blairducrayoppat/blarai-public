"""
UI Shell Constants — Direct Wiring Assertions (WI-13, P1.12).

Pins every constant in services/ui_shell/src/constants.py to its
authoritative value. Catches accidental drift.
"""

from __future__ import annotations

from services.ui_shell.src import constants as shell_constants


class TestUiShellConstants:
    """WI-13: Exact-value assertions for every UI Shell constant."""

    # ── Layout ────────────────────────────────────────────────────

    def test_session_panel_width_pct(self) -> None:
        assert shell_constants.SESSION_PANEL_WIDTH_PCT == 25

    def test_prompt_max_chars(self) -> None:
        assert shell_constants.PROMPT_MAX_CHARS == 4_096

    def test_response_scroll_back_lines(self) -> None:
        assert shell_constants.RESPONSE_SCROLL_BACK_LINES == 10_000

    def test_title_placeholder(self) -> None:
        assert shell_constants.TITLE_PLACEHOLDER == "New session"

    # ── Keyboard shortcuts ────────────────────────────────────────

    def test_key_submit(self) -> None:
        assert shell_constants.KEY_SUBMIT == "enter"

    def test_key_retry(self) -> None:
        assert shell_constants.KEY_RETRY == "ctrl+r"

    def test_key_new_session(self) -> None:
        assert shell_constants.KEY_NEW_SESSION == "ctrl+n"

    def test_key_delete_session(self) -> None:
        assert shell_constants.KEY_DELETE_SESSION == "ctrl+d"

    def test_key_quit(self) -> None:
        assert shell_constants.KEY_QUIT == "ctrl+q"

    # ── Streaming ─────────────────────────────────────────────────

    def test_stream_refresh_interval_ms(self) -> None:
        assert shell_constants.STREAM_REFRESH_INTERVAL_MS == 50

    def test_cursor_blink_interval_ms(self) -> None:
        assert shell_constants.CURSOR_BLINK_INTERVAL_MS == 500

    # ── PGOV Display ──────────────────────────────────────────────

    def test_pgov_panel_border_style(self) -> None:
        assert shell_constants.PGOV_PANEL_BORDER_STYLE == "heavy"

    def test_pgov_denial_title(self) -> None:
        assert shell_constants.PGOV_DENIAL_TITLE == "Policy Denial"

    def test_pgov_reason_labels_complete_mapping(self) -> None:
        """Every key and exact label value is pinned."""
        expected = {
            "TOKEN_BUDGET_EXCEEDED": "Token budget exceeded",
            "PII_DETECTED": "PII detected and redacted",
            "DELIMITER_ECHO": "Delimiter echo blocked",
            "TOOL_CALL_VIOLATION": "Unauthorized tool call",
            "LEAKAGE_DETECTED": "Data leakage detected",
            "VALIDATION_ERROR": "Request validation error",
        }
        assert shell_constants.PGOV_REASON_LABELS == expected

    def test_pgov_reason_labels_has_six_keys(self) -> None:
        assert len(shell_constants.PGOV_REASON_LABELS) == 6

    # ── Boot-Phase-3 Gating ──────────────────────────────────────

    def test_boot_status_poll_interval_s(self) -> None:
        assert shell_constants.BOOT_STATUS_POLL_INTERVAL_S == 1.0

    def test_boot_banner_text(self) -> None:
        assert shell_constants.BOOT_BANNER_TEXT == "BlarAI is starting\u2026"

    def test_boot_failed_text(self) -> None:
        assert shell_constants.BOOT_FAILED_TEXT == (
            "System failed to start. Press Ctrl+Q to exit."
        )

    # ── Type checks ───────────────────────────────────────────────

    def test_session_panel_width_pct_is_int(self) -> None:
        assert isinstance(shell_constants.SESSION_PANEL_WIDTH_PCT, int)

    def test_prompt_max_chars_is_int(self) -> None:
        assert isinstance(shell_constants.PROMPT_MAX_CHARS, int)

    def test_pgov_reason_labels_is_dict(self) -> None:
        assert isinstance(shell_constants.PGOV_REASON_LABELS, dict)

    def test_boot_status_poll_interval_s_is_float(self) -> None:
        assert isinstance(shell_constants.BOOT_STATUS_POLL_INTERVAL_S, float)
