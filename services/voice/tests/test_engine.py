"""Tests for the VoiceEngine surface (ADR-017) — with fakes, no real models."""

from __future__ import annotations

import numpy as np

from services.voice.src.engine import (
    DEFAULT_VOICE,
    VoiceEngine,
    extract_sentences,
    split_sentences,
)


class _FakeWhisper:
    def __init__(self, text: str = "hello world") -> None:
        self._text = text
        self.calls: list[int] = []

    def generate(self, samples: np.ndarray) -> str:
        self.calls.append(len(samples))
        return self._text


class _FakeKokoro:
    """Mimics kokoro_onnx.Kokoro.create: returns (samples, sample_rate)."""

    def __init__(self, voices: list[str]) -> None:
        self._voices = voices
        self.used_voice: str | None = None
        self.sentences: list[str] = []

    def get_voices(self) -> list[str]:
        return self._voices

    def create(self, text: str, voice: str, speed: float = 1.0, lang: str = "en-us"):
        self.used_voice = voice
        self.used_speed = speed
        self.sentences.append(text)
        return np.zeros(240, dtype=np.float32), 24000


# ── split_sentences ────────────────────────────────────────────────────


def test_split_sentences_segments_on_punctuation() -> None:
    assert split_sentences("Hello there. How are you? Fine!") == [
        "Hello there.",
        "How are you?",
        "Fine!",
    ]


def test_split_sentences_handles_no_terminal_punctuation() -> None:
    assert split_sentences("just one fragment") == ["just one fragment"]


def test_split_sentences_empty() -> None:
    assert split_sentences("   ") == []


# ── extract_sentences (streaming) ──────────────────────────────────────


def test_extract_sentences_keeps_incomplete_remainder() -> None:
    # "How are" is not yet terminated -> carried as remainder, not synthesized.
    sentences, remainder = extract_sentences("Hello there. How are")
    assert sentences == ["Hello there."]
    assert remainder == "How are"


def test_extract_sentences_multiple() -> None:
    sentences, remainder = extract_sentences("One. Two! Three? tail")
    assert sentences == ["One.", "Two!", "Three?"]
    assert remainder == "tail"


def test_extract_sentences_none_complete() -> None:
    # No terminal punctuation+space yet: nothing to speak, all carried.
    sentences, remainder = extract_sentences("a partial clause")
    assert sentences == []
    assert remainder == "a partial clause"


def test_extract_sentences_streaming_accumulation() -> None:
    # Simulate tokens arriving; remainder feeds back in until a sentence completes.
    buf = ""
    spoken: list[str] = []
    for tok in ["The ", "cat ", "sat. ", "It ", "purred. "]:
        buf += tok
        sents, buf = extract_sentences(buf)
        spoken.extend(sents)
    assert spoken == ["The cat sat.", "It purred."]


# ── availability / status ──────────────────────────────────────────────


def test_engine_reports_unavailable_when_empty() -> None:
    eng = VoiceEngine()
    assert eng.stt_available is False
    assert eng.tts_available is False
    assert eng.status() == {"stt": False, "tts": False, "voices": [], "default_voice": DEFAULT_VOICE}


def test_status_reports_voices() -> None:
    eng = VoiceEngine(kokoro=_FakeKokoro(["af_heart", "am_adam"]), voices=["af_heart", "am_adam"])
    status = eng.status()
    assert status["tts"] is True
    assert status["voices"] == ["af_heart", "am_adam"]


# ── transcribe ─────────────────────────────────────────────────────────


def test_transcribe_calls_whisper() -> None:
    fake = _FakeWhisper("the quick brown fox")
    eng = VoiceEngine(whisper=fake)
    text = eng.transcribe(np.zeros(16000, dtype=np.float32))
    assert text == "the quick brown fox"
    assert fake.calls == [16000]


# ── synthesize_stream ──────────────────────────────────────────────────


def test_synthesize_stream_yields_one_chunk_per_sentence() -> None:
    fake = _FakeKokoro(["af_heart"])
    eng = VoiceEngine(kokoro=fake, default_voice="af_heart", voices=["af_heart"])
    chunks = list(eng.synthesize_stream("One. Two. Three."))
    assert len(chunks) == 3
    samples, sr = chunks[0]
    assert sr == 24000 and samples.dtype == np.float32
    assert fake.sentences == ["One.", "Two.", "Three."]


def test_synthesize_falls_back_to_default_for_unknown_voice() -> None:
    fake = _FakeKokoro(["af_heart", "am_adam"])
    eng = VoiceEngine(kokoro=fake, default_voice="af_heart", voices=["af_heart", "am_adam"])
    list(eng.synthesize_stream("Hi.", voice="nonexistent"))
    assert fake.used_voice == "af_heart"


def test_synthesize_honors_known_voice() -> None:
    fake = _FakeKokoro(["af_heart", "am_adam"])
    eng = VoiceEngine(kokoro=fake, default_voice="af_heart", voices=["af_heart", "am_adam"])
    list(eng.synthesize_stream("Hi.", voice="am_adam"))
    assert fake.used_voice == "am_adam"


def test_synthesize_default_speed_is_faster_than_one() -> None:
    fake = _FakeKokoro(["af_heart"])
    eng = VoiceEngine(kokoro=fake, default_voice="af_heart", voices=["af_heart"])
    list(eng.synthesize_stream("Hi."))
    assert fake.used_speed > 1.0  # draggy-default avoidance (ADR-017 tuning)


def test_synthesize_honors_explicit_speed() -> None:
    fake = _FakeKokoro(["af_heart"])
    eng = VoiceEngine(kokoro=fake, default_voice="af_heart", voices=["af_heart"])
    list(eng.synthesize_stream("Hi.", speed=1.5))
    assert fake.used_speed == 1.5


# ── fail-soft load ─────────────────────────────────────────────────────


def test_load_with_no_paths_is_empty_not_raising() -> None:
    eng = VoiceEngine.load()
    assert eng.stt_available is False
    assert eng.tts_available is False


def test_load_with_bad_paths_disables_fail_soft() -> None:
    # Nonexistent files must disable each half, never raise.
    eng = VoiceEngine.load(
        whisper_dir="does/not/exist",
        kokoro_model="nope.onnx",
        kokoro_voices="nope.bin",
        device="CPU",
    )
    assert eng.stt_available is False
    assert eng.tts_available is False


# ── runtime load / unload (#660 — on-demand toggles, mirrors #611) ──────


def test_with_paths_builds_empty_engine_remembering_paths() -> None:
    # Always-off-at-boot: no model is touched, but the paths are remembered so a
    # later load_* can bring the half up on demand.
    eng = VoiceEngine.with_paths(
        whisper_dir="w", kokoro_model="k.onnx", kokoro_voices="v.bin"
    )
    assert eng.stt_available is False
    assert eng.tts_available is False
    assert eng._whisper_dir == "w"
    assert eng._kokoro_model == "k.onnx"
    assert eng._kokoro_voices == "v.bin"


def test_load_stt_loads_on_demand(monkeypatch) -> None:
    fake = _FakeWhisper("loaded")
    eng = VoiceEngine.with_paths(whisper_dir="w")
    monkeypatch.setattr(VoiceEngine, "_load_whisper", staticmethod(lambda d, dev: fake))
    assert eng.stt_available is False
    assert eng.load_stt() is True
    assert eng.stt_available is True
    # The loaded model is actually used by transcribe.
    assert eng.transcribe(np.zeros(16000, dtype=np.float32)) == "loaded"


def test_load_stt_idempotent(monkeypatch) -> None:
    calls = {"n": 0}

    def _load(d, dev):
        calls["n"] += 1
        return _FakeWhisper()

    eng = VoiceEngine.with_paths(whisper_dir="w")
    monkeypatch.setattr(VoiceEngine, "_load_whisper", staticmethod(_load))
    assert eng.load_stt() is True
    assert eng.load_stt() is True  # second call is a no-op
    assert calls["n"] == 1


def test_load_stt_no_path_is_failsoft_noop() -> None:
    # No remembered path -> the load is a fail-soft no-op (stays off, never raises).
    eng = VoiceEngine.with_paths()  # no whisper_dir
    assert eng.load_stt() is False
    assert eng.stt_available is False


def test_unload_stt_drops_model_and_runs_gc(monkeypatch) -> None:
    import services.voice.src.engine as engine_mod

    gc_calls = {"n": 0}
    monkeypatch.setattr(engine_mod.gc, "collect", lambda: gc_calls.__setitem__("n", gc_calls["n"] + 1))

    eng = VoiceEngine(whisper=_FakeWhisper())
    assert eng.stt_available is True
    assert eng.unload_stt() is True
    assert eng.stt_available is False
    assert eng._whisper is None          # the model attribute is genuinely dropped
    assert gc_calls["n"] == 1            # gc.collect() ran to finalize the model
    # Idempotent: a second unload is a no-op and does NOT gc again.
    assert eng.unload_stt() is False
    assert gc_calls["n"] == 1


def test_load_tts_loads_voices_on_demand(monkeypatch) -> None:
    fake = _FakeKokoro(["af_heart", "am_adam"])
    eng = VoiceEngine.with_paths(kokoro_model="k.onnx", kokoro_voices="v.bin")
    monkeypatch.setattr(
        VoiceEngine, "_load_kokoro",
        staticmethod(lambda m, v: (fake, ["af_heart", "am_adam"])),
    )
    assert eng.tts_available is False
    assert eng.load_tts() is True
    assert eng.tts_available is True
    assert eng.available_voices() == ["af_heart", "am_adam"]


def test_unload_tts_drops_model_clears_voices_and_runs_gc(monkeypatch) -> None:
    import services.voice.src.engine as engine_mod

    gc_calls = {"n": 0}
    monkeypatch.setattr(engine_mod.gc, "collect", lambda: gc_calls.__setitem__("n", gc_calls["n"] + 1))

    eng = VoiceEngine(kokoro=_FakeKokoro(["af_heart"]), voices=["af_heart"])
    assert eng.tts_available is True
    assert eng.unload_tts() is True
    assert eng.tts_available is False
    assert eng._kokoro is None
    assert eng.available_voices() == []  # the voice bank is cleared on unload
    assert gc_calls["n"] == 1
    assert eng.unload_tts() is False     # idempotent, no second gc
    assert gc_calls["n"] == 1


def test_load_then_unload_then_reload_cycle(monkeypatch) -> None:
    # The full toggle cycle: load -> available, unload -> gone, load -> back.
    eng = VoiceEngine.with_paths(whisper_dir="w")
    monkeypatch.setattr(
        VoiceEngine, "_load_whisper", staticmethod(lambda d, dev: _FakeWhisper())
    )
    assert eng.load_stt() is True and eng.stt_available is True
    assert eng.unload_stt() is True and eng.stt_available is False
    assert eng.load_stt() is True and eng.stt_available is True
