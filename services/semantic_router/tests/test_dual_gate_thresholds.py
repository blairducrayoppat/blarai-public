"""
Semantic Router — Dual-Gate Threshold Tests
=============================================
Deterministic tests that exercise the two confidence gates in
``SemanticRouter.classify`` with mock-controlled centroid vectors and a
stubbed ``_embed_raw``. Complements the integration coverage in
``test_router.py`` with exact-boundary assertions that require no ONNX
model on disk.

Gate 1 (absolute):  best_confidence < CONFIDENCE_THRESHOLD → OUT_OF_SCOPE
Gate 2 (margin):    margin < CONFIDENCE_MARGIN             → OUT_OF_SCOPE
Both strict ``<``, i.e. exact-boundary values are accepted.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pytest
from numpy.typing import NDArray

from services.semantic_router.src.router import Intent, SemanticRouter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _unit(x: float, y: float = 0.0) -> NDArray[np.float32]:
    norm = math.sqrt(x * x + y * y)
    return np.array([x / norm, y / norm], dtype=np.float32)


def _make_router_with_scores(scores: list[tuple[float, Intent, str | None]]) -> SemanticRouter:
    """Construct a SemanticRouter whose classify() will yield the supplied
    per-centroid cosine similarities against a fixed query vector [1, 0].

    Each entry = (similarity, intent, skill_target).
    """
    router = SemanticRouter(model_path="nonexistent.onnx")
    router._loaded = True  # bypass load_model
    router._embedding_dim = 2
    # Fixed query vector
    query_vec = np.array([1.0, 0.0], dtype=np.float32)

    def _stub_embed_raw(texts: list[str], _qv: NDArray[np.float32] = query_vec) -> NDArray[np.float32]:
        return np.tile(_qv, (len(texts), 1))

    router._embed_raw = _stub_embed_raw  # type: ignore[method-assign]

    centroids: list[tuple[Intent, str | None, NDArray[np.float32]]] = []
    # If query = [1, 0] and centroid = [cos θ, sin θ] (unit), dot = cos θ.
    # So centroid[0] = similarity, centroid[1] = sqrt(1 - sim²).
    for sim, intent, skill in scores:
        perp = math.sqrt(max(0.0, 1.0 - sim * sim))
        centroid = np.array([sim, perp], dtype=np.float32)
        centroids.append((intent, skill, centroid))
    router._centroids = centroids
    return router


# ---------------------------------------------------------------------------
# Gate 1 — Absolute confidence threshold (CONFIDENCE_THRESHOLD = 0.50)
# ---------------------------------------------------------------------------


class TestGate1AbsoluteThreshold:
    """Absolute cosine-similarity floor for any acceptance."""

    def test_below_threshold_returns_out_of_scope(self) -> None:
        router = _make_router_with_scores([
            (0.49, Intent.CONVERSATIONAL, None),
            (0.10, Intent.SKILL_DISPATCH, "skill_a"),
        ])
        result = router.classify("any query")
        assert result.intent == Intent.OUT_OF_SCOPE
        assert result.confidence == pytest.approx(0.49, abs=1e-5)
        assert result.error is None  # reject via threshold is not an error

    def test_at_exact_threshold_does_not_reject_on_gate1(self) -> None:
        """Operator is ``<``, so 0.50 exactly must PASS Gate 1 (margin
        decides the rest).  Picking a second score well below ensures the
        margin gate is also satisfied so we can see Gate 1 acceptance
        clearly."""
        router = _make_router_with_scores([
            (0.50, Intent.CONVERSATIONAL, None),
            (0.00, Intent.SKILL_DISPATCH, "skill_a"),
        ])
        result = router.classify("any query")
        assert result.intent == Intent.CONVERSATIONAL

    def test_just_above_threshold_with_strong_margin_passes(self) -> None:
        router = _make_router_with_scores([
            (0.60, Intent.SKILL_DISPATCH, "skill_a"),
            (0.20, Intent.CONVERSATIONAL, None),
        ])
        result = router.classify("any query")
        assert result.intent == Intent.SKILL_DISPATCH
        assert result.skill_target == "skill_a"


# ---------------------------------------------------------------------------
# Gate 2 — Margin between best and second-best (CONFIDENCE_MARGIN = 0.04)
# ---------------------------------------------------------------------------


class TestGate2Margin:
    """Confidence-margin gate — closes the ambiguity hole."""

    def test_margin_below_threshold_returns_out_of_scope(self) -> None:
        """Best=0.60, second=0.58 → margin 0.02 < 0.04 → reject."""
        router = _make_router_with_scores([
            (0.60, Intent.CONVERSATIONAL, None),
            (0.58, Intent.SKILL_DISPATCH, "skill_a"),
        ])
        result = router.classify("ambiguous query")
        assert result.intent == Intent.OUT_OF_SCOPE
        assert result.confidence == pytest.approx(0.60, abs=1e-5)

    def test_margin_at_exact_threshold_passes(self) -> None:
        """Best=0.60, second=0.56 → margin 0.04 exactly.  Strict ``<``
        means 0.04 passes."""
        router = _make_router_with_scores([
            (0.60, Intent.CONVERSATIONAL, None),
            (0.56, Intent.SKILL_DISPATCH, "skill_a"),
        ])
        result = router.classify("borderline query")
        assert result.intent == Intent.CONVERSATIONAL

    def test_margin_just_below_threshold_rejects(self) -> None:
        """Best=0.60, second≈0.5601 → margin≈0.0399 → reject."""
        router = _make_router_with_scores([
            (0.60, Intent.CONVERSATIONAL, None),
            (0.5601, Intent.SKILL_DISPATCH, "skill_a"),
        ])
        result = router.classify("narrow-miss query")
        assert result.intent == Intent.OUT_OF_SCOPE

    def test_single_centroid_has_maximum_margin(self) -> None:
        """With only one centroid, second_best = 0.0 → margin = best → always ≥ 0.04."""
        router = _make_router_with_scores([
            (0.80, Intent.CONVERSATIONAL, None),
        ])
        result = router.classify("solo query")
        assert result.intent == Intent.CONVERSATIONAL


# ---------------------------------------------------------------------------
# Custom injected thresholds
# ---------------------------------------------------------------------------


class TestCustomThresholdInjection:
    """Router-level thresholds override module defaults via __init__."""

    def test_custom_threshold_stricter_than_default_rejects(self) -> None:
        router = _make_router_with_scores([
            (0.60, Intent.CONVERSATIONAL, None),
            (0.00, Intent.SKILL_DISPATCH, "skill_a"),
        ])
        # override threshold after construction
        router._confidence_threshold = 0.75
        result = router.classify("query")
        assert result.intent == Intent.OUT_OF_SCOPE

    def test_custom_margin_looser_than_default_accepts(self) -> None:
        router = _make_router_with_scores([
            (0.60, Intent.CONVERSATIONAL, None),
            (0.58, Intent.SKILL_DISPATCH, "skill_a"),
        ])
        router._confidence_margin = 0.01  # looser than 0.04 default
        result = router.classify("query")
        assert result.intent == Intent.CONVERSATIONAL


# ---------------------------------------------------------------------------
# Dual-gate interaction — both must pass
# ---------------------------------------------------------------------------


class TestDualGateInteraction:
    """Both gates must hold for acceptance."""

    def test_gate1_fails_overrides_gate2_pass(self) -> None:
        router = _make_router_with_scores([
            (0.40, Intent.CONVERSATIONAL, None),
            (0.10, Intent.SKILL_DISPATCH, "skill_a"),
        ])
        # margin 0.30 is healthy but best < threshold → reject
        result = router.classify("query")
        assert result.intent == Intent.OUT_OF_SCOPE

    def test_both_gates_pass_returns_best_route(self) -> None:
        router = _make_router_with_scores([
            (0.85, Intent.SKILL_DISPATCH, "skill_a"),
            (0.60, Intent.CONVERSATIONAL, None),
        ])
        result = router.classify("query")
        assert result.intent == Intent.SKILL_DISPATCH
        assert result.skill_target == "skill_a"
        assert result.confidence == pytest.approx(0.85, abs=1e-5)


# ---------------------------------------------------------------------------
# Empty centroid list — fail-closed behavior
# ---------------------------------------------------------------------------


class TestEmptyCentroids:
    """Loaded but no centroids → classification must Fail-Closed."""

    def test_no_centroids_returns_out_of_scope(self) -> None:
        router = _make_router_with_scores([])
        result = router.classify("query")
        assert result.intent == Intent.OUT_OF_SCOPE
        assert result.confidence == 0.0
