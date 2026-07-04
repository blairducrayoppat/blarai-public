"""
Intent Router — Semantic Router Core Logic
=============================================
USE-CASE-004, P1.7: CPU-based bge-small-en-v1.5 intent classifier.

Classifies user queries into intent categories:
  - CONVERSATIONAL: Route to Orchestrator for generation.
  - SKILL_DISPATCH: Route to a specific skill agent.
  - OUT_OF_SCOPE: Reject with a safe fallback message.

The router is STATELESS — no session or conversation context.
Each classification is independent.

Architecture:
  1. Tokenize input query (bge-small-en-v1.5 WordPiece tokenizer).
  2. Run ONNX Runtime inference on CPU (FP16, ~128MB).
  3. Mean-pool hidden states → L2-normalize → 384-dim embedding.
  4. Compute cosine similarity against pre-computed intent centroids.
  5. Return top intent if confidence ≥ threshold, else OUT_OF_SCOPE.

Security:
  - Fail-Closed: classification errors return OUT_OF_SCOPE.
  - No external network calls.
  - Input length capped to prevent DoS via long queries.
  - Model loaded from local ONNX file only.
  - All exceptions caught and converted to OUT_OF_SCOPE.

Performance (Lunar Lake P-cores):
  - Latency target: sub-80ms per classification.
  - Model: BAAI/bge-small-en-v1.5 ONNX FP16 (127.8 MB measured).
  - Embedding dim: 384.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from services.semantic_router.src.constants import (
    CONFIDENCE_MARGIN,
    CONFIDENCE_THRESHOLD,
    DEFAULT_INTENT,
    INFERENCE_DEVICE,
    LATENCY_TARGET_MS,
)
from services.semantic_router.src.intents import INTENT_ROUTES, IntentRoute

logger = logging.getLogger(__name__)


class Intent(str, Enum):
    """Supported intent categories."""

    CONVERSATIONAL = "CONVERSATIONAL"
    SKILL_DISPATCH = "SKILL_DISPATCH"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


@dataclass(frozen=True)
class ClassificationResult:
    """Result of intent classification."""

    intent: Intent
    """Predicted intent."""

    confidence: float
    """Model confidence in [0.0, 1.0]."""

    latency_ms: float
    """Inference latency in milliseconds."""

    skill_target: str | None = None
    """Target skill name if intent is SKILL_DISPATCH."""

    error: str | None = None
    """Error message if classification failed."""


# Type alias for centroid tuples: (intent, skill_target, centroid_vector)
_CentroidEntry = tuple[Intent, str | None, NDArray[np.float32]]


class SemanticRouter:
    """CPU-based bge-small-en-v1.5 intent classifier.

    Lifecycle:
      1. __init__: Configure model path, inference parameters, and routes.
      2. load_model(): Load ONNX model + tokenizer, pre-compute centroids.
      3. classify(): Embed query, cosine-similarity match against centroids.
      4. unload(): Release model resources.

    Routes define the semantic space for each intent. Each route has a set
    of representative phrases; their mean embedding becomes the centroid.
    At classify time, the query embedding is compared against all centroids
    and the highest-scoring route above the confidence threshold wins.
    """

    def __init__(
        self,
        model_path: str,
        max_input_length: int = 128,
        confidence_threshold: float = CONFIDENCE_THRESHOLD,
        confidence_margin: float = CONFIDENCE_MARGIN,
        routes: list[IntentRoute] | None = None,
    ) -> None:
        self._model_path = model_path
        self._max_input_length = max_input_length
        self._confidence_threshold = confidence_threshold
        self._confidence_margin = confidence_margin
        self._routes = routes if routes is not None else INTENT_ROUTES
        self._session: Any = None  # onnxruntime.InferenceSession
        self._tokenizer: Any = None  # transformers.PreTrainedTokenizer
        self._input_names: list[str] = []
        self._centroids: list[_CentroidEntry] = []
        self._embedding_dim: int = 0
        self._loaded = False

    @property
    def loaded(self) -> bool:
        """Whether the model is loaded and centroids are computed."""
        return self._loaded

    @property
    def embedding_dim(self) -> int:
        """Dimensionality of the embedding space (0 if not loaded)."""
        return self._embedding_dim

    @property
    def num_routes(self) -> int:
        """Number of configured intent routes."""
        return len(self._routes)

    @property
    def num_centroids(self) -> int:
        """Number of computed centroids (0 if not loaded)."""
        return len(self._centroids)

    def load_model(self) -> bool:
        """Load the ONNX model, tokenizer, and pre-compute intent centroids.

        Loads bge-small-en-v1.5 via ONNX Runtime (CPUExecutionProvider) and
        the associated WordPiece tokenizer from the model directory. Then
        embeds all route phrases and computes mean centroid vectors.

        Returns:
            True if the model was loaded and centroids computed successfully.
            False on any error (Fail-Closed).
        """
        try:
            import onnxruntime as ort
            from transformers import AutoTokenizer

            model_dir = str(Path(self._model_path).parent)

            # Load tokenizer from model directory (tokenizer.json + vocab.txt)
            self._tokenizer = AutoTokenizer.from_pretrained(model_dir)

            # Load ONNX model with CPU-only execution
            sess_options = ort.SessionOptions()
            sess_options.inter_op_num_threads = 1
            sess_options.intra_op_num_threads = 4
            sess_options.graph_optimization_level = (
                ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            )

            self._session = ort.InferenceSession(
                self._model_path,
                sess_options=sess_options,
                providers=["CPUExecutionProvider"],
            )
            self._input_names = [inp.name for inp in self._session.get_inputs()]

            # Determine embedding dimensionality from a probe inference
            probe = self._embed_raw(["probe"])
            self._embedding_dim = probe.shape[1]

            # Pre-compute route centroid embeddings
            self._centroids = []
            for route in self._routes:
                if not route.phrases:
                    logger.warning(
                        "Route %s/%s has no phrases — skipped.",
                        route.intent,
                        route.skill_target,
                    )
                    continue

                embeddings = self._embed_raw(route.phrases)
                centroid = embeddings.mean(axis=0)
                norm = float(np.linalg.norm(centroid))
                if norm > 1e-9:
                    centroid = centroid / norm

                intent = Intent(route.intent)
                self._centroids.append((intent, route.skill_target, centroid))

            self._loaded = True
            logger.info(
                "SemanticRouter loaded: model=%s, dim=%d, routes=%d, centroids=%d",
                Path(self._model_path).name,
                self._embedding_dim,
                len(self._routes),
                len(self._centroids),
            )
            return True

        except Exception as exc:
            logger.error("SemanticRouter load_model failed (Fail-Closed): %s", exc)
            self._loaded = False
            return False

    def _embed_raw(self, texts: list[str]) -> NDArray[np.float32]:
        """Embed a batch of texts into L2-normalized 384-dim vectors.

        Uses mean pooling over the last hidden state with attention mask
        weighting, followed by L2 normalization. This produces unit-length
        embeddings suitable for cosine similarity via dot product.

        Args:
            texts: List of input strings.

        Returns:
            Array of shape (len(texts), embedding_dim) with L2-normalized rows.

        Raises:
            RuntimeError: If session or tokenizer is not initialized.
        """
        if self._tokenizer is None or self._session is None:
            msg = "Cannot embed: model not loaded."
            raise RuntimeError(msg)

        tokens = self._tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=self._max_input_length,
            return_tensors="np",
        )

        # Only feed inputs the ONNX model expects (handles token_type_ids presence)
        # Cast to int64 — transformers may return int32 but ONNX expects int64
        feed = {
            k: v.astype(np.int64) for k, v in tokens.items() if k in self._input_names
        }
        outputs = self._session.run(None, feed)

        # Mean pooling: weight hidden states by attention mask
        last_hidden: NDArray[np.float32] = outputs[0]  # (batch, seq_len, dim)
        mask: NDArray[np.float32] = tokens["attention_mask"][..., np.newaxis]
        summed = (last_hidden * mask).sum(axis=1)
        counts = mask.sum(axis=1).clip(min=1e-9)
        embeddings = summed / counts

        # L2 normalize — enables cosine similarity via dot product
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True).clip(min=1e-9)
        return (embeddings / norms).astype(np.float32)

    def classify(self, query: str) -> ClassificationResult:
        """Classify a user query into an intent category.

        Embeds the query via bge-small-en-v1.5, computes cosine similarity
        against all pre-computed route centroids, and returns the best match
        if it exceeds the confidence threshold.

        Args:
            query: Raw user query text.

        Returns:
            ClassificationResult. On any error, returns OUT_OF_SCOPE (Fail-Closed).
        """
        start = time.perf_counter()

        if not self._loaded:
            elapsed = (time.perf_counter() - start) * 1_000
            return ClassificationResult(
                intent=Intent.OUT_OF_SCOPE,
                confidence=0.0,
                latency_ms=elapsed,
                error="Model not loaded — Fail-Closed.",
            )

        # Input length guard (~10 chars per WordPiece token heuristic)
        if len(query) > self._max_input_length * 10:
            elapsed = (time.perf_counter() - start) * 1_000
            return ClassificationResult(
                intent=Intent.OUT_OF_SCOPE,
                confidence=0.0,
                latency_ms=elapsed,
                error=f"Input too long ({len(query)} chars) — truncation required.",
            )

        try:
            # Embed query → 384-dim unit vector
            query_vec = self._embed_raw([query])[0]

            # Cosine similarity against all centroids (dot product of unit vectors)
            scores: list[tuple[float, Intent, str | None]] = []
            for intent, skill_target, centroid in self._centroids:
                similarity = float(np.dot(query_vec, centroid))
                scores.append((similarity, intent, skill_target))

            # Sort descending by similarity
            scores.sort(key=lambda x: x[0], reverse=True)

            best_confidence = scores[0][0] if scores else 0.0
            best_intent = scores[0][1] if scores else Intent.OUT_OF_SCOPE
            best_skill = scores[0][2] if scores else None
            second_best = scores[1][0] if len(scores) > 1 else 0.0
            margin = best_confidence - second_best

            elapsed = (time.perf_counter() - start) * 1_000

            # Dual-gate: absolute threshold + margin threshold
            # Gate 1: Absolute minimum cosine similarity
            if best_confidence < self._confidence_threshold:
                return ClassificationResult(
                    intent=Intent.OUT_OF_SCOPE,
                    confidence=best_confidence,
                    latency_ms=elapsed,
                )

            # Gate 2: Margin between best and second-best
            # Low margin = ambiguous/OOD input where no route dominates
            if margin < self._confidence_margin:
                return ClassificationResult(
                    intent=Intent.OUT_OF_SCOPE,
                    confidence=best_confidence,
                    latency_ms=elapsed,
                )

            return ClassificationResult(
                intent=best_intent,
                confidence=best_confidence,
                latency_ms=elapsed,
                skill_target=best_skill,
            )

        except Exception as exc:
            elapsed = (time.perf_counter() - start) * 1_000
            logger.error("Classification failed (Fail-Closed): %s", exc)
            return ClassificationResult(
                intent=Intent.OUT_OF_SCOPE,
                confidence=0.0,
                latency_ms=elapsed,
                error=f"Classification error — Fail-Closed: {exc}",
            )

    def unload(self) -> None:
        """Release ONNX Runtime session, tokenizer, and centroid state."""
        self._session = None
        self._tokenizer = None
        self._input_names = []
        self._centroids = []
        self._embedding_dim = 0
        self._loaded = False
