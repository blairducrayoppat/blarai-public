"""TUI Shell constants (P1.12, ADR-009)."""

from __future__ import annotations

# ── Layout ────────────────────────────────────────────────────────
SESSION_PANEL_WIDTH_PCT: int = 25          # sidebar percentage
PROMPT_MAX_CHARS: int = 4_096              # hard limit on user input
RESPONSE_SCROLL_BACK_LINES: int = 10_000   # history buffer
TITLE_PLACEHOLDER: str = "New session"

# ── Keyboard shortcuts ────────────────────────────────────────────
# Keybinding IDs are registered at compose-time in app.py
KEY_SUBMIT: str = "enter"
KEY_RETRY: str = "ctrl+r"
KEY_NEW_SESSION: str = "ctrl+n"
KEY_DELETE_SESSION: str = "ctrl+d"
KEY_PASTE: str = "ctrl+v"
KEY_QUIT: str = "ctrl+q"

# ── Streaming ─────────────────────────────────────────────────────
STREAM_REFRESH_INTERVAL_MS: int = 50       # display tick
CURSOR_BLINK_INTERVAL_MS: int = 500

# ── PGOV Display ──────────────────────────────────────────────────
PGOV_PANEL_BORDER_STYLE: str = "heavy"     # textual border style
PGOV_DENIAL_TITLE: str = "Policy Denial"
PGOV_REASON_LABELS: dict[str, str] = {
    "TOKEN_BUDGET_EXCEEDED": "Token budget exceeded",
    "PII_DETECTED": "PII detected and redacted",
    "DELIMITER_ECHO": "Delimiter echo blocked",
    "TOOL_CALL_VIOLATION": "Unauthorized tool call",
    "LEAKAGE_DETECTED": "Data leakage detected",
    "VALIDATION_ERROR": "Request validation error",
}

# ── Boot-Phase-3 Gating ──────────────────────────────────────────
BOOT_STATUS_POLL_INTERVAL_S: float = 1.0   # startup polling
BOOT_BANNER_TEXT: str = "BlarAI is starting…"
BOOT_FAILED_TEXT: str = "System failed to start. Press Ctrl+Q to exit."
