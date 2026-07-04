"""
Tests for services.ui_shell.src.pgov_display (P1.12).

Tests the PGOVPanel logic without running Textual. Verifies
display_denial(), hide(), and the is_visible property.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from services.ui_gateway.src.transport import GatewayPGOVResult
from services.ui_shell.src.pgov_display import PGOVPanel
from services.ui_shell.src.constants import (
    PGOV_DENIAL_TITLE,
    PGOV_REASON_LABELS,
)


def _make_denial(
    reasons: list[str] | None = None,
    text: str = "redacted",
) -> GatewayPGOVResult:
    return GatewayPGOVResult(
        approved=False,
        sanitized_text=text,
        reason_codes=reasons or ["PII_DETECTED"],
        request_id="req-1",
    )


class TestPGOVPanelConstants:
    """Verify PGOV constants."""

    def test_denial_title(self) -> None:
        assert PGOV_DENIAL_TITLE == "Policy Denial"

    def test_all_reason_labels_present(self) -> None:
        expected_keys = {
            "TOKEN_BUDGET_EXCEEDED",
            "PII_DETECTED",
            "DELIMITER_ECHO",
            "TOOL_CALL_VIOLATION",
            "LEAKAGE_DETECTED",
            "VALIDATION_ERROR",
        }
        assert set(PGOV_REASON_LABELS.keys()) == expected_keys

    def test_reason_labels_are_human_readable(self) -> None:
        for key, label in PGOV_REASON_LABELS.items():
            assert isinstance(label, str)
            assert len(label) > 5  # not blank/stub


class TestPGOVPanelLogic:
    """Test PGOVPanel behavior with mocked Textual base."""

    @pytest.fixture()
    def panel(self) -> PGOVPanel:
        """Create a PGOVPanel with mocked __init__."""
        with patch.object(PGOVPanel, "__init__", lambda self, **kw: None):
            p = PGOVPanel.__new__(PGOVPanel)
            p._current_result = None
            # Mock Textual methods
            p.update = MagicMock()  # type: ignore[assignment]
            p.styles = MagicMock()
            return p

    def test_not_visible_initially(self, panel: PGOVPanel) -> None:
        assert panel.is_visible is False

    def test_display_denial_makes_visible(self, panel: PGOVPanel) -> None:
        panel.display_denial(_make_denial())
        assert panel.is_visible is True

    def test_display_denial_calls_update(self, panel: PGOVPanel) -> None:
        panel.display_denial(_make_denial(reasons=["PII_DETECTED"]))
        panel.update.assert_called_once()
        rendered = panel.update.call_args[0][0]
        assert PGOV_DENIAL_TITLE in rendered
        assert "PII detected and redacted" in rendered  # from PGOV_REASON_LABELS

    def test_display_denial_shows_sanitized_text(self, panel: PGOVPanel) -> None:
        panel.display_denial(_make_denial(text="safe output"))
        rendered = panel.update.call_args[0][0]
        assert "safe output" in rendered

    def test_display_denial_truncates_long_text(self, panel: PGOVPanel) -> None:
        long_text = "X" * 500
        panel.display_denial(_make_denial(text=long_text))
        rendered = panel.update.call_args[0][0]
        # Text should be truncated to 200 chars
        assert len(long_text) > 200
        assert "X" * 200 in rendered

    def test_display_denial_multiple_reasons(self, panel: PGOVPanel) -> None:
        reasons = ["PII_DETECTED", "LEAKAGE_DETECTED", "TOKEN_BUDGET_EXCEEDED"]
        panel.display_denial(_make_denial(reasons=reasons))
        rendered = panel.update.call_args[0][0]
        assert "PII detected and redacted" in rendered
        assert "Data leakage detected" in rendered
        assert "Token budget exceeded" in rendered

    def test_display_denial_unknown_reason_shows_raw(self, panel: PGOVPanel) -> None:
        panel.display_denial(_make_denial(reasons=["UNKNOWN_CODE"]))
        rendered = panel.update.call_args[0][0]
        # Unknown code falls back to raw string
        assert "UNKNOWN_CODE" in rendered

    def test_hide_clears_result(self, panel: PGOVPanel) -> None:
        panel.display_denial(_make_denial())
        panel.hide()
        assert panel.is_visible is False
        assert panel._current_result is None

    def test_hide_sets_display_none(self, panel: PGOVPanel) -> None:
        panel.display_denial(_make_denial())
        panel.hide()
        assert panel.styles.display == "none"

    def test_display_denial_sets_block_display(self, panel: PGOVPanel) -> None:
        panel.display_denial(_make_denial())
        # styles.display should be set to "block"
        assert panel.styles.display == "block"


# ---------------------------------------------------------------------------
# Relocated from tests/integration/test_p114_ui_end_to_end.py per P5_TASK8_EA5 WI-4.
# `slow` marker stripped (3F.3): these are unit-scope service tests.
# ---------------------------------------------------------------------------


class TestP114Relocated:
    """Relocated non-cross-service P114 tests (formerly under tests/integration/)."""

    def _capture_panel_text(self, panel: PGOVPanel) -> dict[str, str]:
        captured = {"text": ""}

        def _update(text: str) -> None:
            captured["text"] = text

        panel.update = _update  # type: ignore[method-assign]
        return captured

    def test_reason_code_labels_render_for_three_codes(self) -> None:
        panel = PGOVPanel()
        captured = self._capture_panel_text(panel)
        result = GatewayPGOVResult(
            approved=False,
            sanitized_text="redacted",
            reason_codes=["PII_DETECTED", "DELIMITER_ECHO", "LEAKAGE_DETECTED"],
            request_id="req-e1",
        )
        panel.display_denial(result)
        rendered = captured["text"]
        assert PGOV_REASON_LABELS["PII_DETECTED"] in rendered
        assert PGOV_REASON_LABELS["DELIMITER_ECHO"] in rendered
        assert PGOV_REASON_LABELS["LEAKAGE_DETECTED"] in rendered


    def test_multiple_reason_codes_render_all_labels(self) -> None:
        panel = PGOVPanel()
        captured = self._capture_panel_text(panel)
        result = GatewayPGOVResult(
            approved=False,
            sanitized_text="blocked",
            reason_codes=["TOKEN_BUDGET_EXCEEDED", "TOOL_CALL_VIOLATION", "VALIDATION_ERROR"],
            request_id="req-e2",
        )
        panel.display_denial(result)
        rendered = captured["text"]
        for code in result.reason_codes:
            assert PGOV_REASON_LABELS[code] in rendered


    def test_sanitized_text_truncated_at_200_chars(self) -> None:
        panel = PGOVPanel()
        captured = self._capture_panel_text(panel)
        long_text = "x" * 250
        result = GatewayPGOVResult(
            approved=False,
            sanitized_text=long_text,
            reason_codes=["VALIDATION_ERROR"],
            request_id="req-e3",
        )
        panel.display_denial(result)
        rendered = captured["text"]
        assert "x" * 200 in rendered
        assert "x" * 201 not in rendered


    def test_pgov_panel_hide_clears_display(self) -> None:
        panel = PGOVPanel()
        captured = self._capture_panel_text(panel)
        panel.display_denial(
            GatewayPGOVResult(
                approved=False,
                sanitized_text="blocked",
                reason_codes=["VALIDATION_ERROR"],
                request_id="req-e4",
            )
        )
        assert panel.is_visible is True
        panel.hide()
        assert panel.is_visible is False
        assert captured["text"] == ""


    def test_unknown_reason_code_renders_fallback_label(self) -> None:
        panel = PGOVPanel()
        captured = self._capture_panel_text(panel)
        result = GatewayPGOVResult(
            approved=False,
            sanitized_text="blocked",
            reason_codes=["UNKNOWN_CODE"],
            request_id="req-e6",
        )
        panel.display_denial(result)
        rendered = captured["text"]
        assert "UNKNOWN_CODE" in rendered


