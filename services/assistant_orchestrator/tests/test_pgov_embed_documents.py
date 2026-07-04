"""
Tests for LeakageDetector.embed_documents (UC-002 knowledge embeddings, #655).

REGRESSION REQUIREMENT: the leakage path (``_embed``, 128-token default) must
stay byte-identical — PGOV Stage-5 thresholds are calibrated at 128 tokens.
These tests use a stub tokenizer + ONNX session (no model files needed) that
RECORD the max_length they were called with and produce deterministic outputs
that depend on the truncation window, so a silent window change would shift
the vectors and fail.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from services.assistant_orchestrator.src.pgov import LeakageDetector


# ---------------------------------------------------------------------------
# Stubs: tokenizer + ONNX session whose output depends on max_length
# ---------------------------------------------------------------------------


class _StubTokenizer:
    """Records max_length; emits one token per word, truncated at max_length."""

    def __init__(self) -> None:
        self.calls: list[int] = []

    def __call__(
        self,
        texts: list[str],
        *,
        padding: bool,
        truncation: bool,
        max_length: int,
        return_tensors: str,
    ) -> dict[str, np.ndarray]:
        assert padding is True and truncation is True and return_tensors == "np"
        self.calls.append(max_length)
        seqs = [t.split()[:max_length] for t in texts]
        width = max((len(s) for s in seqs), default=1) or 1
        input_ids = np.zeros((len(texts), width), dtype=np.int64)
        attention_mask = np.zeros((len(texts), width), dtype=np.int64)
        for i, seq in enumerate(seqs):
            for j, word in enumerate(seq):
                input_ids[i, j] = (hash(word) % 1000) + 1
                attention_mask[i, j] = 1
        return {"input_ids": input_ids, "attention_mask": attention_mask}


class _StubSession:
    """Deterministic 'hidden states' derived from the input ids."""

    def get_inputs(self) -> list[Any]:  # pragma: no cover - shape only
        return []

    def run(self, _outputs: None, feed: dict[str, np.ndarray]) -> list[np.ndarray]:
        ids = feed["input_ids"].astype(np.float32)  # (batch, seq)
        batch, seq = ids.shape
        dim = 384
        # hidden[b, s, d] = (ids[b, s] + d) % 13 — NON-separable in (token, dim)
        # so the mean-pooled direction genuinely depends on WHICH tokens are
        # present (a separable ids*scale stub cancels under L2 normalization).
        d_idx = np.arange(dim, dtype=np.float32)
        hidden = np.mod(
            ids[:, :, np.newaxis] + d_idx[np.newaxis, np.newaxis, :], 13.0
        ).astype(np.float32)
        return [hidden.reshape(batch, seq, dim)]


def _make_detector(max_input_length: int = 128) -> tuple[LeakageDetector, _StubTokenizer]:
    det = LeakageDetector(model_path="unused.onnx", max_input_length=max_input_length)
    tok = _StubTokenizer()
    det._tokenizer = tok
    det._session = _StubSession()
    det._input_names = ["input_ids", "attention_mask"]
    det._loaded = True
    return det, tok


# A fixed input long enough that 128- and 512-token truncation differ.
_LONG_TEXT = " ".join(f"tok{i}" for i in range(300))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLeakagePathRegression:
    def test_embed_uses_128_token_default(self) -> None:
        det, tok = _make_detector()
        det._embed([_LONG_TEXT])
        assert tok.calls == [128]

    def test_embed_vectors_unchanged_by_refactor(self) -> None:
        """The _embed output equals the reference mean-pool/L2 computation at
        the 128-token window — the byte-identical leakage-path lock."""
        det, _tok = _make_detector()
        got = det._embed([_LONG_TEXT, "short text"])

        # Independent reference computation at max_length=128.
        ref_tok = _StubTokenizer()
        tokens = ref_tok(
            [_LONG_TEXT, "short text"],
            padding=True, truncation=True, max_length=128, return_tensors="np",
        )
        hidden = _StubSession().run(
            None, {k: v.astype(np.int64) for k, v in tokens.items()}
        )[0]
        mask = tokens["attention_mask"][..., np.newaxis]
        summed = (hidden * mask).sum(axis=1)
        counts = mask.sum(axis=1).clip(min=1e-9)
        ref = summed / counts
        norms = np.linalg.norm(ref, axis=1, keepdims=True).clip(min=1e-9)
        ref = (ref / norms).astype(np.float32)

        np.testing.assert_array_equal(got, ref)

    def test_embed_respects_constructor_max_input_length(self) -> None:
        det, tok = _make_detector(max_input_length=64)
        det._embed(["a b c"])
        assert tok.calls == [64]


class TestEmbedDocuments:
    def test_embed_documents_uses_512_default(self) -> None:
        det, tok = _make_detector()
        det.embed_documents([_LONG_TEXT])
        assert tok.calls == [512]

    def test_embed_documents_custom_window(self) -> None:
        det, tok = _make_detector()
        det.embed_documents([_LONG_TEXT], max_length=256)
        assert tok.calls == [256]

    def test_embed_documents_does_not_mutate_leakage_default(self) -> None:
        """Interleaved calls: the leakage path stays at 128 after document
        embedding at 512 — no shared-state bleed."""
        det, tok = _make_detector()
        det.embed_documents([_LONG_TEXT])
        det._embed([_LONG_TEXT])
        det.embed_documents([_LONG_TEXT], max_length=512)
        det._embed(["another"])
        assert tok.calls == [512, 128, 512, 128]

    def test_wider_window_changes_long_text_vector(self) -> None:
        """At 512 tokens more of the text informs the vector — outputs differ
        from the 128-window embedding for long input (the whole point)."""
        det, _tok = _make_detector()
        v128 = det._embed([_LONG_TEXT])
        v512 = det.embed_documents([_LONG_TEXT])
        assert not np.allclose(v128, v512)

    def test_short_text_identical_across_windows(self) -> None:
        """Truncation windows only matter past the window — short inputs embed
        identically, confirming the shared implementation path."""
        det, _tok = _make_detector()
        v128 = det._embed(["short text only"])
        v512 = det.embed_documents(["short text only"])
        np.testing.assert_array_equal(v128, v512)

    def test_output_shape_and_l2_norm(self) -> None:
        det, _tok = _make_detector()
        out = det.embed_documents([_LONG_TEXT, "short"])
        assert out.shape == (2, 384)
        assert out.dtype == np.float32
        np.testing.assert_allclose(
            np.linalg.norm(out, axis=1), np.ones(2), rtol=1e-5
        )

    def test_not_loaded_raises(self) -> None:
        det = LeakageDetector(model_path="unused.onnx")
        with pytest.raises(RuntimeError):
            det.embed_documents(["text"])
