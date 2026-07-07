"""
Gateway-specific constants for the UI Transport Gateway (P1.11).

All hardware/empirical constants are imported from shared.constants.
This module holds UI-gateway-specific defaults only.
"""

from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# Session Database
# ---------------------------------------------------------------------------

_LOCALAPPDATA: str = os.environ.get("LOCALAPPDATA", "")

SESSION_DB_DIR: str = os.path.join(_LOCALAPPDATA, "BlarAI") if _LOCALAPPDATA else ""
"""Directory for the SQLite session database. Empty if %LOCALAPPDATA% unset."""

SESSION_DB_FILENAME: str = "sessions.db"
"""SQLite database file name."""

SESSION_DB_PATH: str = (
    os.path.join(SESSION_DB_DIR, SESSION_DB_FILENAME) if SESSION_DB_DIR else ""
)
"""Full path to the session database. Empty if %LOCALAPPDATA% unset."""

# ---------------------------------------------------------------------------
# Boot-Phase-3 Handshake
# ---------------------------------------------------------------------------

PA_HANDSHAKE_MAX_RETRIES: int = 3
"""Maximum number of PA vsock handshake attempts before Fail-Closed."""

PA_HANDSHAKE_BACKOFF_BASE_S: float = 1.0
"""Base backoff duration (seconds). Doubles each retry: 1s, 2s, 4s."""

PA_HANDSHAKE_TIMEOUT_S: float = 5.0
"""Per-attempt connection timeout (seconds)."""

PROMPT_RESPONSE_TIMEOUT_S: float = 180.0
"""Per-prompt receive timeout (seconds) for real inference responses.

Raised 120 -> 180 (#561): a vision turn legitimately chains a VLM load
(~12-16 s), an image describe, and up to two 14B generations (the context-aware
query formulation + the answer). At 120 s a slow-but-valid vision turn tripped
the receive timeout, and the gateway default-denied (fail-closed) a response the
AO was in fact still producing — surfacing to the user as a spurious validation
error. The VLM-eviction memory fix keeps real turns well under this; the larger
budget is headroom so a legitimate vision turn is never mistaken for a hang."""

# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------

STREAM_TOKEN_BUFFER_LIMIT: int = 4_096
"""Maximum tokens to buffer before circuit-breaker cutoff."""

TOOL_CALL_BUFFER_MAX_TOKENS: int = 512
"""Maximum tokens to buffer for a single tool-call block."""

# ---------------------------------------------------------------------------
# Session Limits
# ---------------------------------------------------------------------------

SESSION_TITLE_MAX_CHARS: int = 80
"""Maximum characters for any session title (auto-generated or /rename)."""

SESSION_TITLE_PROMPT_CHARS: int = 15
"""Characters of the first user prompt used in an auto-generated title.
The auto-title format is ``<prompt fragment>… · <date>`` — this caps the
fragment. Tunable: raise it for more content context per sidebar entry."""
