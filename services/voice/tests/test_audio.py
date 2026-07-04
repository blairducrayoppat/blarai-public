"""Tests for the voice audio codec helpers (ADR-017) — pure, no models."""

from __future__ import annotations

import base64

import numpy as np
import pytest

from services.voice.src.audio import (
    PCM_S16LE,
    WHISPER_SAMPLE_RATE,
    decode_b64_pcm,
    encode_b64_pcm,
    float_to_pcm16,
    pcm16_to_float,
    prepare_for_stt,
    resample_linear,
)


def test_pcm16_float_roundtrip_is_near_lossless() -> None:
    original = np.array([0.0, 0.5, -0.5, 1.0, -1.0], dtype=np.float32)
    restored = pcm16_to_float(float_to_pcm16(original))
    assert np.allclose(original, restored, atol=1e-4)


def test_float_to_pcm16_clips_out_of_range() -> None:
    hot = np.array([2.0, -2.0], dtype=np.float32)
    restored = pcm16_to_float(float_to_pcm16(hot))
    # Clipped to the int16 rail, not wrapped around into noise.
    assert np.all(restored <= 1.0) and np.all(restored >= -1.0)
    assert restored[0] > 0.99 and restored[1] < -0.99


def test_b64_pcm_roundtrip() -> None:
    samples = np.linspace(-1.0, 1.0, 200, dtype=np.float32)
    encoded = encode_b64_pcm(samples)
    # It is valid base64 and decodes back to the same shape/values.
    base64.b64decode(encoded)  # raises if not valid base64
    restored = decode_b64_pcm(encoded)
    assert restored.shape == samples.shape
    assert np.allclose(samples, restored, atol=1e-4)


def test_resample_identity_when_rates_match() -> None:
    x = np.array([0.1, 0.2, 0.3], dtype=np.float32)
    out = resample_linear(x, 16000, 16000)
    assert np.array_equal(x, out)


def test_resample_changes_length_proportionally() -> None:
    x = np.zeros(2400, dtype=np.float32)  # 0.1 s at 24 kHz
    out = resample_linear(x, 24000, 16000)
    assert out.size == 1600  # 0.1 s at 16 kHz


def test_resample_empty_is_safe() -> None:
    assert resample_linear(np.array([], dtype=np.float32), 24000, 16000).size == 0


def test_resample_rejects_nonpositive_rate() -> None:
    # A malformed client (e.g. unparsed WAV header -> sr=0) must not divide by zero.
    with pytest.raises(ValueError):
        resample_linear(np.zeros(8, dtype=np.float32), 0, 16000)


def test_decode_downmixes_stereo_to_mono() -> None:
    # Two interleaved frames, L/R = (1.0, 0.0) and (0.0, 1.0) -> mono 0.5, 0.5.
    stereo = np.array([1.0, 0.0, 0.0, 1.0], dtype=np.float32)
    b64 = base64.b64encode(float_to_pcm16(stereo)).decode("ascii")
    mono = decode_b64_pcm(b64, channels=2)
    assert mono.size == 2
    assert np.allclose(mono, [0.5, 0.5], atol=1e-3)


def test_prepare_for_stt_yields_16k_mono() -> None:
    samples = np.zeros(2400, dtype=np.float32)  # 0.1 s @ 24 kHz
    b64 = encode_b64_pcm(samples)
    out = prepare_for_stt(b64, sample_rate=24000, fmt=PCM_S16LE, channels=1)
    assert out.dtype == np.float32
    assert out.size == int(round(2400 * WHISPER_SAMPLE_RATE / 24000))


def test_prepare_for_stt_rejects_unknown_format() -> None:
    with pytest.raises(ValueError):
        prepare_for_stt(encode_b64_pcm(np.zeros(8, dtype=np.float32)), 16000, fmt="opus")
