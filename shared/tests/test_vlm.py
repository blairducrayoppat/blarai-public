"""Tests for the VLM module's memory-eviction path (#561).

The heavy Qwen3-VL model is never loaded here — these tests manipulate the
module globals directly to verify ``unload()``'s contract: it clears the cached
pipeline, resets the fail flag so a later image can re-load cleanly, and is
idempotent. (The eviction is what stops the ~5 GB VLM lingering co-resident with
the always-resident 14B on shared system RAM and freezing the host.)
"""

from __future__ import annotations

import pytest

import shared.inference.vlm as vlm


def test_unload_clears_cached_pipe_and_resets_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Simulate a loaded pipe AND a prior fail flag set.
    monkeypatch.setattr(vlm, "_pipe", object())
    monkeypatch.setattr(vlm, "_load_failed", True)

    vlm.unload()

    assert vlm._pipe is None
    # _load_failed MUST reset, or _get_pipe() would stay in the failed state
    # and never reload the next image.
    assert vlm._load_failed is False


def test_unload_is_idempotent_when_nothing_loaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(vlm, "_pipe", None)
    monkeypatch.setattr(vlm, "_load_failed", False)

    vlm.unload()  # must not raise when nothing is loaded
    vlm.unload()  # idempotent

    assert vlm._pipe is None
    assert vlm._load_failed is False
