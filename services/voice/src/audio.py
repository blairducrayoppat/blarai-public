"""
Voice audio codec helpers (ADR-017 §2.4)
========================================
Pure, model-free conversions between the wire format the named-pipe bridge
carries — base64-encoded little-endian 16-bit PCM (``pcm_s16le``) — and the
float32 sample arrays the Whisper and Kokoro pipelines speak. Kept free of any
model or onnxruntime/openvino import so the codec is unit-testable on its own.

Wire shape (ADR-017 §2.5):
  - STT upload:   {audio_b64, sample_rate, format: "pcm_s16le", channels: 1}
  - TTS chunk:    {audio_b64, sample_rate, index}

Everything here is mono. Stereo is out of scope for a voice assistant; a
multi-channel payload is downmixed to mono on decode rather than rejected.
"""

from __future__ import annotations

import base64

import numpy as np

# Whisper expects 16 kHz mono float32; Kokoro emits 24 kHz.
WHISPER_SAMPLE_RATE: int = 16000
PCM_S16LE: str = "pcm_s16le"
_INT16_MAX: float = 32767.0


def pcm16_to_float(pcm: bytes) -> np.ndarray:
    """Decode little-endian int16 PCM bytes to float32 in [-1.0, 1.0]."""
    ints = np.frombuffer(pcm, dtype="<i2").astype(np.float32)
    return ints / _INT16_MAX


def float_to_pcm16(samples: np.ndarray) -> bytes:
    """Encode a float32 sample array to little-endian int16 PCM bytes.

    Samples are clipped to [-1.0, 1.0] before scaling so a hot synthesis frame
    cannot wrap around into noise.
    """
    arr = np.asarray(samples, dtype=np.float32)
    clipped = np.clip(arr, -1.0, 1.0)
    ints = np.round(clipped * _INT16_MAX).astype("<i2")
    return ints.tobytes()


def resample_linear(samples: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    """Linearly resample a mono float32 array from *src_sr* to *dst_sr*.

    Linear interpolation is deliberate: it is dependency-free (no scipy) and
    more than adequate for speech STT, which is robust to the modest aliasing it
    introduces. Returns the input unchanged when the rates already match.
    """
    arr = np.asarray(samples, dtype=np.float32)
    if src_sr <= 0 or dst_sr <= 0:
        raise ValueError(f"Invalid sample rate: src={src_sr}, dst={dst_sr}")
    if src_sr == dst_sr or arr.size == 0:
        return arr
    n_dst = int(round(arr.size * dst_sr / src_sr))
    if n_dst <= 1:
        return arr[:1].copy()
    src_idx = np.linspace(0, arr.size - 1, n_dst).astype(np.float32)
    return np.interp(src_idx, np.arange(arr.size, dtype=np.float32), arr).astype(np.float32)


def decode_b64_pcm(audio_b64: str, channels: int = 1) -> np.ndarray:
    """Decode a base64 ``pcm_s16le`` payload to float32, downmixing to mono."""
    raw = base64.b64decode(audio_b64)
    samples = pcm16_to_float(raw)
    if channels > 1 and samples.size:
        # Interleaved frames -> mean across channels (mono downmix).
        usable = (samples.size // channels) * channels
        samples = samples[:usable].reshape(-1, channels).mean(axis=1)
    return samples


def encode_b64_pcm(samples: np.ndarray) -> str:
    """Encode a float32 sample array to a base64 ``pcm_s16le`` string."""
    return base64.b64encode(float_to_pcm16(samples)).decode("ascii")


def prepare_for_stt(
    audio_b64: str,
    sample_rate: int,
    fmt: str = PCM_S16LE,
    channels: int = 1,
) -> np.ndarray:
    """Decode + downmix + resample a wire payload to 16 kHz mono float32.

    Raises:
        ValueError: If *fmt* is not the supported ``pcm_s16le``.
    """
    if fmt != PCM_S16LE:
        raise ValueError(f"Unsupported audio format {fmt!r}; expected {PCM_S16LE!r}")
    samples = decode_b64_pcm(audio_b64, channels=channels)
    return resample_linear(samples, sample_rate, WHISPER_SAMPLE_RATE)
