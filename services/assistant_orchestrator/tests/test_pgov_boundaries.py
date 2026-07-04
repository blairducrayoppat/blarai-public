"""
PGOV Boundary Tests — Assistant Orchestrator
=============================================
Exact-threshold boundary tests for the PGOV leakage detector. Asserts that
``leakage_score == cosine_threshold`` produces denial (inclusive ``>=``),
closing the one-value coverage gap left by adjacent over/under tests.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from services.assistant_orchestrator.src.pgov import (
    LeakageDetector,
    set_leakage_detector,
    validate_output,
)


class TestPGOVLeakageThresholdBoundary:
    """Exact-threshold behavior for embedding-based leakage rejection."""

    def test_leakage_cosine_similarity_at_threshold_rejects(self) -> None:
        mock_detector = MagicMock(spec=LeakageDetector)
        mock_detector.check_leakage.return_value = 0.85
        set_leakage_detector(mock_detector)
        try:
            result = validate_output(
                generated_text="Verbatim copied text at threshold.",
                token_count=10,
                max_tokens=4096,
                retrieved_chunks=["Verbatim copied text at threshold."],
                cosine_threshold=0.85,
            )
            assert result.approved is False
            assert result.leakage_score == 0.85
            assert any("Leakage" in v for v in result.violations)
        finally:
            set_leakage_detector(None)  # type: ignore[arg-type]

    def test_leakage_cosine_similarity_just_below_threshold_passes(self) -> None:
        mock_detector = MagicMock(spec=LeakageDetector)
        mock_detector.check_leakage.return_value = 0.8499
        set_leakage_detector(mock_detector)
        try:
            result = validate_output(
                generated_text="Just-below text.",
                token_count=10,
                max_tokens=4096,
                retrieved_chunks=["Original source text."],
                cosine_threshold=0.85,
            )
            assert result.approved is True
            assert result.leakage_score == 0.8499
            assert not any("Leakage" in v for v in result.violations)
        finally:
            set_leakage_detector(None)  # type: ignore[arg-type]
