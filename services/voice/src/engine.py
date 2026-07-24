"""
Voice engine — Whisper-small STT + Kokoro-82M TTS (ADR-017)
===========================================================
Holds the two optional model handles and exposes a tiny, fail-soft surface the
UI-backend dispatcher injects exactly like the gateway. Either model may be
absent: if a load fails, that half disables (``stt_available`` /
``tts_available`` go ``False``) and text chat is untouched — the same posture
ADR-016's Substrate takes.

The engine is synchronous on purpose; the dispatcher offloads the blocking model
calls to a worker thread (``asyncio.to_thread``) so the pipe event loop stays
responsive. Synthesis is segmented by sentence so the front end can begin
playback on the first chunk rather than waiting for the whole reply (ADR-017
§2.5).
"""

from __future__ import annotations

import gc
import logging
import re
import threading
from typing import Any, Iterator

import numpy as np

logger = logging.getLogger(__name__)

# Kokoro emits 24 kHz; default to a non-robotic female voice (ADR-017 §2.2).
KOKORO_SAMPLE_RATE: int = 24000
DEFAULT_VOICE: str = "af_heart"
# The 2026-06-04 by-ear 1.5 measured ≈307 WPM on the #853 audition script —
# ~2× a natural pace. Measured sweep: 0.80→162, 0.90→189, 1.00→208 WPM against
# a ~150–180 comfort band; the User-Operator picked 0.90 ≈ 189 WPM by ear,
# deliberately a hair fast (2026-07-17, #853 c.2189).
# This constant IS the effective playback rate: the WinUI synthesize payload
# carries only {text, voice} (BackendClient.SynthesizeAsync), so the dispatcher
# passes speed=None and synthesize_stream falls back here — verified across the
# boundary, not assumed (lesson 6). Tunable by ear.
DEFAULT_SPEED: float = 0.90

# Split on sentence-final punctuation while keeping the delimiter, so each chunk
# is a natural prosodic unit. Falls back to the whole string if it has none.
_SENTENCE_RE = re.compile(r"[^.!?]+[.!?]+|\S[^.!?]*$")


def split_sentences(text: str) -> list[str]:
    """Segment *text* into sentence-ish chunks for streamed synthesis."""
    stripped = text.strip()
    if not stripped:
        return []
    chunks = [m.group().strip() for m in _SENTENCE_RE.finditer(stripped)]
    return [c for c in chunks if c]


# A complete sentence in a still-growing buffer ends in .!? FOLLOWED BY whitespace
# — the trailing-space requirement avoids cutting a sentence that is still being
# streamed (its final token may extend the last word). The remainder is carried.
_STREAM_SENTENCE_RE = re.compile(r"(.+?[.!?]+)\s", re.DOTALL)


def extract_sentences(buffer: str) -> tuple[list[str], str]:
    """Pull COMPLETE sentences from a streaming token buffer.

    Returns ``(sentences, remainder)`` where *remainder* is the trailing text not
    yet terminated by sentence-final punctuation — kept to prepend to the next
    tokens. Used to synthesize a reply sentence-by-sentence as it streams (ADR-017)
    so speech can start mid-reply rather than after it completes.
    """
    sentences: list[str] = []
    pos = 0
    for m in _STREAM_SENTENCE_RE.finditer(buffer):
        s = m.group(1).strip()
        if s:
            sentences.append(s)
        pos = m.end()
    return sentences, buffer[pos:]


class VoiceEngine:
    """Fail-soft holder for the STT and TTS model handles.

    Either half can be loaded and **unloaded at runtime** (#660): the WinUI voice
    toggles call :meth:`load_stt` / :meth:`unload_stt` (and the TTS pair) so a
    model occupies RAM/GPU only while the operator has its toggle on, then is
    released on toggle-off.  This mirrors the #611 embedding-cache idle-unload
    "load-on-demand / unload-to-reclaim" pattern: an unload drops the model
    attribute (the last Python reference held — the dispatcher reaches the model
    only through this engine, never caching it) and runs ``gc.collect()`` to
    finalize the object so the underlying framework (OpenVINO for Whisper, ONNX
    Runtime for Kokoro) can return its device memory.

    .. note::
       The Python-level drop is what these methods guarantee + test headlessly.
       Whether the C++/driver layer **promptly returns** RAM/GPU on finalization
       is hardware-measured separately (the #660 PERFORMANCE_LOG live-verify);
       there is, however, no lingering Python reference that would make the
       unload a structural no-op.

    The model *paths* are remembered (when the engine was built with
    :meth:`load` / :meth:`with_paths`) so an unloaded half can be reloaded on
    demand without the launcher re-supplying them.

    Args:
        whisper: An ``openvino_genai.WhisperPipeline`` (or ``None``).
        kokoro: A ``kokoro_onnx.Kokoro`` instance (or ``None``).
        default_voice: Voice id used when a synthesize call omits one.
        voices: The list of voice ids the TTS model exposes.
        whisper_dir: On-disk path the STT model loads from (for runtime reload).
        kokoro_model: On-disk Kokoro model path (for runtime reload).
        kokoro_voices: On-disk Kokoro voice-bank path (for runtime reload).
        device: Inference device for the STT model (default ``"GPU"``).
    """

    def __init__(
        self,
        whisper: Any | None = None,
        kokoro: Any | None = None,
        default_voice: str = DEFAULT_VOICE,
        voices: list[str] | None = None,
        whisper_dir: str | None = None,
        kokoro_model: str | None = None,
        kokoro_voices: str | None = None,
        device: str = "GPU",
    ) -> None:
        self._whisper = whisper
        self._kokoro = kokoro
        self._default_voice = default_voice
        self._voices = voices or []
        # Remembered for runtime reload (#660). None means "no path known" —
        # a runtime load of that half is then a fail-soft no-op (stays off).
        self._whisper_dir = whisper_dir
        self._kokoro_model = kokoro_model
        self._kokoro_voices = kokoro_voices
        self._device = device
        # Serialises runtime load/unload against each other and against the
        # blocking transcribe/synthesize calls the dispatcher offloads to worker
        # threads, so a toggle-off can never drop a model mid-inference.
        self._lock = threading.RLock()

    @property
    def stt_available(self) -> bool:
        return self._whisper is not None

    @property
    def tts_available(self) -> bool:
        return self._kokoro is not None

    @property
    def default_voice(self) -> str:
        return self._default_voice

    def available_voices(self) -> list[str]:
        return list(self._voices)

    def status(self) -> dict[str, Any]:
        """The ``voice_status`` payload the front end uses to gate affordances."""
        return {
            "stt": self.stt_available,
            "tts": self.tts_available,
            "voices": self.available_voices(),
            "default_voice": self._default_voice,
        }

    def transcribe(self, samples_16k: np.ndarray) -> str:
        """Transcribe a 16 kHz mono float32 array to text. Blocking.

        Snapshots the model handle under the lock so a concurrent
        :meth:`unload_stt` cannot drop the model mid-inference: the local
        reference keeps it alive until this call returns.
        """
        with self._lock:
            whisper = self._whisper
        if whisper is None:
            raise RuntimeError("Speech-to-text model is not loaded")
        result = whisper.generate(samples_16k)
        return str(result).strip()

    def synthesize_stream(
        self, text: str, voice: str | None = None, speed: float | None = None
    ) -> Iterator[tuple[np.ndarray, int]]:
        """Yield ``(float32_samples, sample_rate)`` per sentence. Blocking.

        Voice falls back to the default when *voice* is unknown or omitted, so a
        stale UI selection can never hard-fail synthesis. *speed* defaults to
        :data:`DEFAULT_SPEED` (the operator-audited ≈189 WPM pace, #853).

        Snapshots the Kokoro handle under the lock at entry so a concurrent
        :meth:`unload_tts` cannot drop the model partway through a multi-sentence
        synthesis: the local reference keeps it alive until the generator is
        exhausted.
        """
        with self._lock:
            kokoro = self._kokoro
            chosen = voice if voice in self._voices else self._default_voice
        if kokoro is None:
            raise RuntimeError("Text-to-speech model is not loaded")
        rate = speed if speed and speed > 0 else DEFAULT_SPEED
        for sentence in split_sentences(text):
            samples, sample_rate = kokoro.create(
                sentence, voice=chosen, speed=rate, lang="en-us"
            )
            yield np.asarray(samples, dtype=np.float32), int(sample_rate)

    @classmethod
    def load(
        cls,
        whisper_dir: str | None = None,
        kokoro_model: str | None = None,
        kokoro_voices: str | None = None,
        device: str = "GPU",
        default_voice: str = DEFAULT_VOICE,
    ) -> "VoiceEngine":
        """Construct the engine, loading whatever is available; never raises.

        Each model loads independently and fail-soft: an import error, a missing
        file, or a device failure disables that half and is logged, leaving the
        other half (and text chat) working.
        """
        whisper = cls._load_whisper(whisper_dir, device)
        kokoro, voices = cls._load_kokoro(kokoro_model, kokoro_voices)
        resolved_default = default_voice if default_voice in voices else (
            voices[0] if voices else default_voice
        )
        engine = cls(
            whisper, kokoro, resolved_default, voices,
            whisper_dir=whisper_dir, kokoro_model=kokoro_model,
            kokoro_voices=kokoro_voices, device=device,
        )
        logger.info(
            "VoiceEngine loaded: stt=%s tts=%s voices=%d",
            engine.stt_available, engine.tts_available, len(voices),
        )
        return engine

    @classmethod
    def with_paths(
        cls,
        whisper_dir: str | None = None,
        kokoro_model: str | None = None,
        kokoro_voices: str | None = None,
        device: str = "GPU",
        default_voice: str = DEFAULT_VOICE,
    ) -> "VoiceEngine":
        """Construct an EMPTY engine that REMEMBERS where to load from (#660).

        The always-off-at-boot posture (decision #3): the launcher builds this so
        no model occupies RAM at launch, but the engine knows the on-disk paths so
        the WinUI voice toggles can :meth:`load_stt` / :meth:`load_tts` on demand
        in-session and :meth:`unload_stt` / :meth:`unload_tts` to reclaim the RAM.
        Never raises (no model is touched here).
        """
        return cls(
            whisper=None, kokoro=None, default_voice=default_voice, voices=[],
            whisper_dir=whisper_dir, kokoro_model=kokoro_model,
            kokoro_voices=kokoro_voices, device=device,
        )

    # ── Runtime load / unload (#660 — mirrors #611 idle-unload) ───────────

    def load_stt(self) -> bool:
        """Load the Whisper STT model on demand. Returns the resulting availability.

        Idempotent: a no-op when STT is already loaded.  Fail-soft: a missing path
        or a load failure leaves STT off (returns ``False``) and never raises, so
        a toggle-on can never crash the surface.  Serialised by the engine lock.
        """
        with self._lock:
            if self._whisper is not None:
                return True
            self._whisper = self._load_whisper(self._whisper_dir, self._device)
            ok = self._whisper is not None
            logger.info("VoiceEngine.load_stt: stt_available=%s", ok)
            return ok

    def unload_stt(self) -> bool:
        """Release the Whisper STT model from RAM/GPU. Returns ``True`` if it unloaded.

        Drops the model attribute (the last Python reference — the dispatcher only
        ever reaches the model through this engine) and runs ``gc.collect()`` to
        finalize the OpenVINO pipeline so its device memory can be returned.
        Idempotent (returns ``False`` when STT is already unloaded).  Serialised by
        the engine lock against any in-flight transcribe (which snapshots its own
        handle, so this never drops a model mid-call).
        """
        with self._lock:
            if self._whisper is None:
                return False
            self._whisper = None
        # gc OUTSIDE the lock: finalization can be slow and needs no lock held
        # (the attribute is already cleared; any in-flight transcribe holds its
        # own local reference and finalization simply waits for that to drop).
        gc.collect()
        logger.info("VoiceEngine.unload_stt: STT released; gc.collect() ran")
        return True

    def load_tts(self) -> bool:
        """Load the Kokoro TTS model + voice bank on demand. Returns availability.

        Idempotent / fail-soft, same posture as :meth:`load_stt`.  Re-derives the
        voice list and the default voice from the freshly loaded bank.
        """
        with self._lock:
            if self._kokoro is not None:
                return True
            kokoro, voices = self._load_kokoro(
                self._kokoro_model, self._kokoro_voices
            )
            self._kokoro = kokoro
            self._voices = voices
            if voices and self._default_voice not in voices:
                self._default_voice = voices[0]
            ok = self._kokoro is not None
            logger.info(
                "VoiceEngine.load_tts: tts_available=%s voices=%d", ok, len(voices)
            )
            return ok

    def unload_tts(self) -> bool:
        """Release the Kokoro TTS model from RAM. Returns ``True`` if it unloaded.

        Drops the model + clears the voice list (the front end re-queries
        :meth:`status` after a toggle change), then ``gc.collect()``.  Idempotent;
        serialised by the engine lock against any in-flight synthesis (which
        snapshots its own handle).
        """
        with self._lock:
            if self._kokoro is None:
                return False
            self._kokoro = None
            self._voices = []
        gc.collect()
        logger.info("VoiceEngine.unload_tts: TTS released; gc.collect() ran")
        return True

    @staticmethod
    def _load_whisper(whisper_dir: str | None, device: str) -> Any | None:
        if not whisper_dir:
            return None
        try:
            import openvino_genai as og  # noqa: PLC0415 — optional, loaded on demand

            return og.WhisperPipeline(str(whisper_dir), device=device)
        except Exception as exc:  # noqa: BLE001 — fail-soft: STT just disables
            logger.warning("Whisper STT unavailable (%s): %s", device, exc)
            return None

    @staticmethod
    def _load_kokoro(
        kokoro_model: str | None, kokoro_voices: str | None
    ) -> tuple[Any | None, list[str]]:
        if not (kokoro_model and kokoro_voices):
            return None, []
        try:
            from kokoro_onnx import Kokoro  # noqa: PLC0415 — optional, on demand

            kokoro = Kokoro(str(kokoro_model), str(kokoro_voices))
            voices = sorted(kokoro.get_voices())
            return kokoro, voices
        except Exception as exc:  # noqa: BLE001 — fail-soft: TTS just disables
            logger.warning("Kokoro TTS unavailable: %s", exc)
            return None, []
