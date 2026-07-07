"""
AO Constants — Direct Wiring Assertions
=========================================
Lightweight regression guard that pins key Assistant Orchestrator constants
to their authoritative upstream sources in ``shared.constants`` (ADR-011 /
ADR-012 baseline). Catches accidental drift when re-exports are modified.
"""

from __future__ import annotations

from shared import constants as shared_constants
from services.assistant_orchestrator.src import constants as ao_constants


class TestAOConstantsWiring:
    """Direct equality between AO re-exports and shared-hardware truth."""

    def test_pgov_cosine_threshold_matches_shared(self) -> None:
        assert (
            ao_constants.PGOV_COSINE_THRESHOLD
            == shared_constants.COSINE_SIMILARITY_THRESHOLD
        )

    def test_pgov_cosine_threshold_value_locked(self) -> None:
        assert ao_constants.PGOV_COSINE_THRESHOLD == 0.85

    def test_output_token_cap_matches_shared(self) -> None:
        assert ao_constants.OUTPUT_TOKEN_CAP == shared_constants.MAX_OUTPUT_TOKENS

    def test_output_token_cap_value_locked(self) -> None:
        assert ao_constants.OUTPUT_TOKEN_CAP == 4_096

    def test_tool_call_depth_cap_matches_shared(self) -> None:
        assert (
            ao_constants.TOOL_CALL_DEPTH_CAP == shared_constants.MAX_TOOL_CALL_DEPTH
        )

    def test_tool_call_depth_cap_value_locked(self) -> None:
        assert ao_constants.TOOL_CALL_DEPTH_CAP == 5

    def test_security_posture_fail_closed_matches_shared(self) -> None:
        assert (
            ao_constants.SECURITY_POSTURE_FAIL_CLOSED == shared_constants.FAIL_CLOSED
        )

    def test_security_posture_fail_closed_is_true(self) -> None:
        assert ao_constants.SECURITY_POSTURE_FAIL_CLOSED is True

    def test_model_dir_matches_target_path(self) -> None:
        assert ao_constants.MODEL_DIR == shared_constants.TARGET_MODEL_OV_PATH

    def test_draft_model_dir_matches_shared(self) -> None:
        assert ao_constants.DRAFT_MODEL_DIR == shared_constants.DRAFT_MODEL_OV_PATH

    def test_speculative_decoding_enabled(self) -> None:
        assert ao_constants.SPECULATIVE_DECODING is True
        assert (
            ao_constants.SPECULATIVE_DECODING
            == shared_constants.SPECULATIVE_DECODING_ENABLED
        )

    def test_assistant_tokens_matches_shared(self) -> None:
        assert ao_constants.ASSISTANT_TOKENS == shared_constants.NUM_ASSISTANT_TOKENS

    def test_first_token_warm_budget_matches_shared(self) -> None:
        assert (
            ao_constants.FIRST_TOKEN_WARM_MS == shared_constants.ORCH_FIRST_TOKEN_WARM_MS
        )

    def test_first_token_cold_budget_matches_shared(self) -> None:
        assert (
            ao_constants.FIRST_TOKEN_COLD_MS == shared_constants.ORCH_FIRST_TOKEN_COLD_MS
        )

    def test_resume_budget_matches_shared(self) -> None:
        assert ao_constants.RESUME_BUDGET_MS == shared_constants.ORCH_RESUME_BUDGET_MS


class TestAOGenerationDefaults:
    """Generation defaults mandated by USE-CASE-004 / P1.8."""

    def test_default_temperature(self) -> None:
        assert ao_constants.DEFAULT_TEMPERATURE == 0.7

    def test_default_top_k(self) -> None:
        assert ao_constants.DEFAULT_TOP_K == 50

    def test_default_top_p(self) -> None:
        assert ao_constants.DEFAULT_TOP_P == 0.9

    def test_default_repetition_penalty(self) -> None:
        assert ao_constants.DEFAULT_REPETITION_PENALTY == 1.1


class TestAOPreemptionConstants:
    """Preemption-detection constants (P1.8, ADR-008)."""

    def test_preemption_timing_multiplier(self) -> None:
        assert ao_constants.PREEMPTION_TIMING_MULTIPLIER == 5.0

    def test_min_preemption_samples(self) -> None:
        assert ao_constants.MIN_PREEMPTION_SAMPLES == 3


class TestAOPGOVFlagDefaults:
    """PGOV pipeline-stage feature flags. All stages enabled by default."""

    def test_pii_enabled(self) -> None:
        assert ao_constants.PGOV_PII_ENABLED is True

    def test_delimiter_echo_enabled(self) -> None:
        assert ao_constants.PGOV_DELIMITER_ECHO_ENABLED is True

    def test_tool_allowlist_enabled(self) -> None:
        assert ao_constants.PGOV_TOOL_ALLOWLIST_ENABLED is True

    def test_leakage_enabled(self) -> None:
        assert ao_constants.PGOV_LEAKAGE_ENABLED is True


class TestAOServiceMetadata:
    """Service-identification constants."""

    def test_service_name(self) -> None:
        assert ao_constants.SERVICE_NAME == "assistant_orchestrator"
