"""
Router Tests — Semantic Router
=================================
Tests for intent classification, Fail-Closed defaults, and input guards.

Unit tests (TestFailClosedDefaults, TestInputGuards, TestIntentEnum) run
without the ONNX model. Integration tests (TestModelLoading,
TestClassification, TestLatency) require bge-small-en-v1.5 ONNX FP16
at models/bge-small-en-v1.5/onnx-fp16/model.onnx and are skipped if
the model is not available.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from services.semantic_router.src.intents import INTENT_ROUTES, IntentRoute
from services.semantic_router.src.router import ClassificationResult, Intent, SemanticRouter

# ---------------------------------------------------------------------------
# Model path resolution for integration tests
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_MODEL_PATH = _PROJECT_ROOT / "models" / "bge-small-en-v1.5" / "onnx-fp16" / "model.onnx"
_MODEL_AVAILABLE = _MODEL_PATH.exists()

requires_model = pytest.mark.skipif(
    not _MODEL_AVAILABLE,
    reason="bge-small-en-v1.5 ONNX FP16 model not available",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def loaded_router() -> SemanticRouter:
    """Module-scoped loaded router (one model load per test module)."""
    router = SemanticRouter(model_path=str(_MODEL_PATH))
    success = router.load_model()
    assert success, f"Failed to load model from {_MODEL_PATH}"
    return router


# ---------------------------------------------------------------------------
# Unit Tests — No model required
# ---------------------------------------------------------------------------


class TestFailClosedDefaults:
    """All stubs should return OUT_OF_SCOPE (Fail-Closed)."""

    def test_unloaded_model_returns_out_of_scope(self) -> None:
        router = SemanticRouter(model_path="nonexistent.onnx")
        result = router.classify("What's the weather?")
        assert result.intent == Intent.OUT_OF_SCOPE
        assert result.error is not None

    def test_unloaded_model_confidence_zero(self) -> None:
        router = SemanticRouter(model_path="nonexistent.onnx")
        result = router.classify("Hello")
        assert result.confidence == 0.0

    def test_load_model_nonexistent_returns_false(self) -> None:
        router = SemanticRouter(model_path="nonexistent.onnx")
        assert router.load_model() is False
        assert router.loaded is False


class TestInputGuards:
    """Input length enforcement."""

    def test_excessively_long_input_rejected(self) -> None:
        """Inputs exceeding the heuristic char limit should be rejected."""
        router = SemanticRouter(model_path="nonexistent.onnx", max_input_length=128)
        # Simulate loaded model to test the length guard
        router._loaded = True
        long_query = "a" * 2000
        result = router.classify(long_query)
        assert result.intent == Intent.OUT_OF_SCOPE
        assert "too long" in (result.error or "").lower()


class TestIntentEnum:
    """Intent enum values."""

    def test_all_intents_are_strings(self) -> None:
        for intent in Intent:
            assert isinstance(intent.value, str)

    def test_expected_intents_exist(self) -> None:
        assert Intent.CONVERSATIONAL.value == "CONVERSATIONAL"
        assert Intent.SKILL_DISPATCH.value == "SKILL_DISPATCH"
        assert Intent.OUT_OF_SCOPE.value == "OUT_OF_SCOPE"


class TestIntentRoutes:
    """Validate the default route definitions."""

    def test_routes_not_empty(self) -> None:
        assert len(INTENT_ROUTES) >= 3

    def test_all_routes_have_phrases(self) -> None:
        for route in INTENT_ROUTES:
            assert len(route.phrases) >= 5, (
                f"Route {route.intent}/{route.skill_target} has only "
                f"{len(route.phrases)} phrases — need at least 5."
            )

    def test_all_route_intents_are_valid(self) -> None:
        valid = {i.value for i in Intent if i != Intent.OUT_OF_SCOPE}
        for route in INTENT_ROUTES:
            assert route.intent in valid, (
                f"Route intent '{route.intent}' not in {valid}"
            )

    def test_skill_dispatch_routes_have_targets(self) -> None:
        for route in INTENT_ROUTES:
            if route.intent == "SKILL_DISPATCH":
                assert route.skill_target is not None, (
                    f"SKILL_DISPATCH route missing skill_target: {route.phrases[:2]}"
                )

    def test_conversational_routes_have_no_target(self) -> None:
        for route in INTENT_ROUTES:
            if route.intent == "CONVERSATIONAL":
                assert route.skill_target is None


# ---------------------------------------------------------------------------
# Integration Tests — Require model
# ---------------------------------------------------------------------------


@requires_model
class TestModelLoading:
    """Model loading, centroid computation, and unloading."""

    def test_load_model_succeeds(self, loaded_router: SemanticRouter) -> None:
        assert loaded_router.loaded is True

    def test_embedding_dim_384(self, loaded_router: SemanticRouter) -> None:
        assert loaded_router.embedding_dim == 384

    def test_centroids_computed(self, loaded_router: SemanticRouter) -> None:
        assert loaded_router.num_centroids >= 3

    def test_unload_clears_state(self) -> None:
        router = SemanticRouter(model_path=str(_MODEL_PATH))
        router.load_model()
        assert router.loaded
        router.unload()
        assert not router.loaded
        assert router.embedding_dim == 0
        assert router.num_centroids == 0

    def test_unload_then_classify_returns_fail_closed(self) -> None:
        router = SemanticRouter(model_path=str(_MODEL_PATH))
        router.load_model()
        router.unload()
        result = router.classify("Hello there")
        assert result.intent == Intent.OUT_OF_SCOPE
        assert result.error is not None
        assert "not loaded" in result.error.lower()


@requires_model
class TestClassification:
    """End-to-end classification with the loaded model."""

    def test_conversational_query(self, loaded_router: SemanticRouter) -> None:
        result = loaded_router.classify("Explain how photosynthesis works")
        assert result.intent == Intent.CONVERSATIONAL
        assert result.confidence >= 0.5

    def test_conversational_question(self, loaded_router: SemanticRouter) -> None:
        result = loaded_router.classify("What is machine learning?")
        assert result.intent == Intent.CONVERSATIONAL

    def test_code_skill_dispatch(self, loaded_router: SemanticRouter) -> None:
        result = loaded_router.classify("Write a Python function to reverse a string")
        assert result.intent == Intent.SKILL_DISPATCH
        assert result.skill_target == "code_agent"
        assert result.confidence >= 0.5

    def test_search_skill_dispatch(self, loaded_router: SemanticRouter) -> None:
        result = loaded_router.classify("Find all Python files in the src directory")
        assert result.intent == Intent.SKILL_DISPATCH
        assert result.skill_target == "search"

    def test_cleaner_skill_dispatch(self, loaded_router: SemanticRouter) -> None:
        result = loaded_router.classify("Import this PDF document into the knowledge base")
        assert result.intent == Intent.SKILL_DISPATCH
        assert result.skill_target == "cleaner"

    def test_gibberish_returns_out_of_scope(self, loaded_router: SemanticRouter) -> None:
        result = loaded_router.classify("xyzzy plugh foobar baz qux")
        assert result.intent == Intent.OUT_OF_SCOPE

    def test_confidence_is_bounded(self, loaded_router: SemanticRouter) -> None:
        """Confidence should always be in [0.0, 1.0] for normalized embeddings."""
        result = loaded_router.classify("Tell me something interesting")
        assert 0.0 <= result.confidence <= 1.0

    def test_latency_ms_is_positive(self, loaded_router: SemanticRouter) -> None:
        result = loaded_router.classify("What is the weather today?")
        assert result.latency_ms > 0.0

    def test_empty_query_classified(self, loaded_router: SemanticRouter) -> None:
        """Empty string should not crash — returns some classification."""
        result = loaded_router.classify("")
        assert result.intent in Intent


@requires_model
class TestConfidenceThresholdBehavior:
    """Verify the threshold gate works correctly."""

    def test_high_threshold_rejects_more(self) -> None:
        """With threshold=0.99, most queries should be OUT_OF_SCOPE."""
        router = SemanticRouter(
            model_path=str(_MODEL_PATH),
            confidence_threshold=0.99,
        )
        router.load_model()
        result = router.classify("Tell me about Python")
        assert result.intent == Intent.OUT_OF_SCOPE

    def test_low_threshold_accepts_more(self) -> None:
        """With threshold=0.01, most reasonable queries should match."""
        router = SemanticRouter(
            model_path=str(_MODEL_PATH),
            confidence_threshold=0.01,
        )
        router.load_model()
        result = router.classify("Tell me about Python")
        assert result.intent != Intent.OUT_OF_SCOPE

    def test_high_margin_rejects_ambiguous(self) -> None:
        """With margin=0.99, all queries should be OUT_OF_SCOPE (impossible margin)."""
        router = SemanticRouter(
            model_path=str(_MODEL_PATH),
            confidence_threshold=0.01,
            confidence_margin=0.99,
        )
        router.load_model()
        result = router.classify("Tell me about Python")
        assert result.intent == Intent.OUT_OF_SCOPE

    def test_zero_margin_allows_ambiguous(self) -> None:
        """With margin=0.0, even gibberish passes if above absolute threshold."""
        router = SemanticRouter(
            model_path=str(_MODEL_PATH),
            confidence_threshold=0.01,
            confidence_margin=0.0,
        )
        router.load_model()
        result = router.classify("xyzzy plugh foobar baz qux")
        # With no margin gate and near-zero threshold, gibberish gets routed
        assert result.intent != Intent.OUT_OF_SCOPE


@requires_model
class TestCustomRoutes:
    """Test that custom routes override defaults."""

    def test_custom_single_route(self) -> None:
        custom_routes = [
            IntentRoute(
                intent="CONVERSATIONAL",
                phrases=[
                    "Hello there",
                    "How are you",
                    "Good morning",
                    "Nice to meet you",
                    "Hey what's up",
                ],
            ),
        ]
        router = SemanticRouter(
            model_path=str(_MODEL_PATH),
            routes=custom_routes,
        )
        router.load_model()
        assert router.num_centroids == 1
        result = router.classify("Hi there, how are you doing?")
        assert result.intent == Intent.CONVERSATIONAL


@requires_model
class TestLatencyBudget:
    """Classification latency must meet the 80ms CPU budget."""

    def test_mean_latency_under_budget(self, loaded_router: SemanticRouter) -> None:
        """Average of 50 classifications should be under 80ms."""
        queries = [
            "What is machine learning?",
            "Write a Python function",
            "Find all test files",
            "Import this document",
            "Explain quantum computing",
        ] * 10  # 50 queries

        latencies = []
        for q in queries:
            result = loaded_router.classify(q)
            latencies.append(result.latency_ms)

        mean_ms = sum(latencies) / len(latencies)
        assert mean_ms < 80.0, (
            f"Mean latency {mean_ms:.1f}ms exceeds 80ms budget. "
            f"Min={min(latencies):.1f}ms, Max={max(latencies):.1f}ms"
        )
