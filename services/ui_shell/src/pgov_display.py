"""
PGOV Denial Display Widget (P1.12, ADR-009)
============================================
Renders Policy Governance (PGOV) denial results as a styled panel
beneath the response area. Shows the denial reasons with human-readable
labels and the sanitized text (if any).

Display format:
  ┌─ Policy Denial ───────────────────────┐
  │ ⚠ PII detected and redacted           │
  │ ⚠ Token budget exceeded               │
  │                                        │
  │ Sanitized: [redacted text here]        │
  └────────────────────────────────────────┘
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.widgets import Static

from .constants import (
    PGOV_DENIAL_TITLE,
    PGOV_PANEL_BORDER_STYLE,
    PGOV_REASON_LABELS,
)

if TYPE_CHECKING:
    from services.ui_gateway.src.transport import GatewayPGOVResult


class PGOVPanel(Static):
    """Displays PGOV denial information.

    Fail-Closed default: panel is hidden until a denial result
    is explicitly provided via ``display_denial()``.
    """

    DEFAULT_CSS = """
    PGOVPanel {
        dock: bottom;
        height: auto;
        max-height: 30%;
        display: none;
        border: heavy $error;
        padding: 1 2;
        margin: 0 0 1 0;
        background: $surface;
    }
    """

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._current_result: GatewayPGOVResult | None = None

    # ── Public API ────────────────────────────────────────────────

    def display_denial(self, result: GatewayPGOVResult) -> None:
        """Render a PGOV denial result.

        Parameters
        ----------
        result : GatewayPGOVResult
            The denial result from the Transport Gateway.
        """
        self._current_result = result

        lines: list[str] = [f"[bold red]{PGOV_DENIAL_TITLE}[/bold red]", ""]

        for code in result.reason_codes:
            label = PGOV_REASON_LABELS.get(code, code)
            lines.append(f"  [yellow]⚠[/yellow] {label}")

        if result.sanitized_text:
            lines.append("")
            lines.append(
                f"  [dim]Sanitized:[/dim] {result.sanitized_text[:200]}"
            )

        self.update("\n".join(lines))
        self.styles.display = "block"

    def hide(self) -> None:
        """Hide the PGOV panel."""
        self.styles.display = "none"
        self._current_result = None
        self.update("")

    @property
    def is_visible(self) -> bool:
        """Whether the panel is currently showing a denial."""
        return self._current_result is not None
