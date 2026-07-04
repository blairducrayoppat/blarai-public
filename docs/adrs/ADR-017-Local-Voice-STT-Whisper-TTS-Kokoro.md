# ADR-017: Local Voice — Whisper-small STT + Kokoro-82M TTS over the Named-Pipe Bridge

**Status:** ACCEPTED — 2026-06-02
**Author:** Lead Architect (Blair) + Claude Opus 4.7
**Related:** ADR-014 (the named-pipe bridge this rides on), ADR-011 (all LLM
inference on GPU), ADR-012 (Qwen3-14B chat path the transcribed text flows
through), ADR-016 (Substrate — the fail-soft posture this mirrors).

---

## 1. Context

The WinUI 3 surface (ADR-014) reached and exceeded TUI parity across Phases
1–6. The next capability the User-Operator wants is **spoken interaction**:
speak to BlarAI and have it speak back — a microphone in the chat input, an
assistant voice-output toggle in settings, and a per-message play button on
assistant replies, shaped like Google Gemini's voice affordances.

The whole system is local, offline, and hardware-rooted (Intel Core Ultra 7
258V / Arc 140V). Voice must hold that line: no cloud speech API, no network
call, models on disk, inference on local silicon. Two model choices and one
transport choice are load-bearing.

A feasibility probe (2026-06-02, recorded on Vikunja #539) verified every
load-bearing unknown on the actual hardware before this ADR was written:
`openvino_genai.WhisperPipeline` exists and transcribes on the Arc GPU (load
5.87 s one-time, transcribe 0.53 s, exact TTS→STT round-trip); `kokoro-onnx`
synthesizes at real-time-factor 0.30 on CPU (3.0 s of audio in 0.90 s). The
numbers below are measured, not assumed.

## 2. Decision

**Speech-to-text is Whisper-small via OpenVINO GenAI's `WhisperPipeline` on the
Arc GPU. Text-to-speech is Kokoro-82M via `kokoro-onnx` on CPU. Audio crosses
the existing ADR-014 named pipe as base64-encoded PCM inside the existing JSON
frames — no new channel, no new socket. The voice models are constructed once
and injected into the `RpcDispatcher`, and the whole feature is fail-soft: if a
model cannot load, the mic/voice affordances disable and text chat is
unaffected.**

### 2.1 Why Whisper-small (STT)

Whisper-small (~240 M params) is the sweet spot for short conversational
utterances: it converts to OpenVINO IR and runs on the same OpenVINO/GPU stack
the 14B already uses (ADR-011), so STT adds no new runtime — just another
pipeline on the device already in play. The probe measured 0.53 s to transcribe
a 2.7 s utterance on the Arc 140V with exact accuracy. It is local, offline, and
MIT-licensed. Larger Whisper variants buy accuracy that short commands do not
need at a latency and memory cost that hurts the <3 s target.

**Model acquisition: pre-converted IR, not local export.** The model is obtained
as a pre-converted OpenVINO IR (`OpenVINO/whisper-small-fp16-ov` via
`huggingface_hub`) rather than converted in-tree with `optimum-cli export
openvino`. The local `optimum` / `optimum-intel` / `transformers 5.3.0` triad in
this venv breaks the optimum OpenVINO exporter (`_CAN_RECORD_REGISTRY` import
failure — tracked as Vikunja #541). The BlarAI runtime never imports optimum, so
that break does not touch the running system; pulling a pinned, pre-converted IR
is both a clean route around the broken exporter and a more reproducible
acquisition path than a local conversion step. Should #541 be serviced later, a
local export becomes an *option*, not a requirement.

### 2.2 Why Kokoro-82M (TTS) — and why not Piper

**Kokoro-82M from the first ship, not Piper.** This is a mature-not-minimal call
(BUILD_JOURNAL Lesson #4) made explicitly by the User-Operator. Piper is smaller
and would also run locally, but it sounds robotic enough to kill the "wow" of a
daily-driver assistant; the portfolio value of this surface is in it feeling
alive. Kokoro-82M is the considered-and-chosen alternative at +275 MB over
Piper — nothing against the ~10 GB headroom the shared-pipeline merge banked.

**The trade-off taken, named: voice quality and portfolio aesthetics over
model size.** Piper is the rejected path, on the record.

`kokoro-onnx` (Apache-2.0, pure-Python ONNX wrapper) supports streaming
generation and exposes multiple voices from a single voices file. Voice
selection is therefore an affordance from the first ship — exposed in settings,
swappable without restart — defaulting to a non-robotic voice (`af_heart`).

### 2.3 Why Kokoro runs on CPU (and why that is fine)

The probe found this venv's `onnxruntime` is CPU-only (`AzureExecutionProvider`,
`CPUExecutionProvider` — no DirectML or OpenVINO execution provider), so
`kokoro-onnx` synthesizes on CPU. The alternative — installing
`onnxruntime-directml` or `onnxruntime-openvino` to push Kokoro onto the Arc GPU
— was **rejected for the first ship**: it means swapping the onnxruntime package
the working stack depends on, a real blast radius for a model that is already
fast enough. Measured CPU real-time-factor is **0.30** (3.3× faster than
real-time); streaming first-chunk latency ~1.4 s. The `ONNX_PROVIDER`
environment variable is honored by `kokoro-onnx`, so a future GPU execution
provider is a one-line override, noted here as a deferred optimization, not a
prerequisite.

### 2.4 Why audio-over-the-existing-pipe as base64 JSON (not a new binary channel)

Audio rides the ADR-014 pipe as base64-encoded PCM inside the existing
length-prefixed JSON frames. This reuses the entire codec on both sides — the
C# `System.Text.Json` client and the Python `json` path — with zero new
transport, no second pipe, and no binary framing to get wrong across the
language boundary. A short utterance or a single TTS sentence-chunk is small:
30 s of 16 kHz mono `s16le` is ~960 KB raw → ~1.28 MB base64, inside the
existing `MAX_FRAME_BYTES = 4 MB` cap. Longer captures are chunked rather than
sent whole.

A type-tagged raw-binary frame (1-byte discriminator + length-prefixed bytes
alongside JSON) would shave the ~33 % base64 overhead and is the obvious later
optimization. It is **deliberately not built first**: the base64 path is correct,
symmetric, and reuses tested code; the binary path is a performance refinement
to take only if frame size or throughput becomes a measured problem.

### 2.5 Wire methods

Two methods are added to the dispatcher, mirroring the existing shapes:

- **`transcribe`** (request/response, like `load_document`):
  `params {audio_b64, sample_rate, format:"pcm_s16le", channels:1}` →
  `result {text}`. The backend decodes the PCM, resamples to 16 kHz,
  runs `WhisperPipeline.generate`, returns the text. The front end then drives
  the existing `prompt` path with that text — STT does not bypass PGOV or any
  governance; it only produces the prompt string.
- **`synthesize`** (streaming, like `prompt`):
  `params {text, voice}` → a sequence of
  `{stream:"audio", value:{audio_b64, sample_rate, index}}` frames, then
  `{stream:"end"}`. The backend segments the text by sentence and streams each
  Kokoro chunk as it generates, so the C# side begins playback before the whole
  reply is synthesized.
- **`voice_status`** (request/response): `result {stt, tts, voices}` so the
  front end can disable mic/voice affordances when a model failed to load.

### 2.6 Where the models live

The voice models are built **once** — in the launcher's `_run_winui_surface`,
alongside the gateway — and injected into the `RpcDispatcher` (the gateway is
injected the same way today). They are not constructed per call. The `--no-model`
/ stub path supplies a deterministic stub voice engine so the UI and the pipe
can be exercised headlessly without the models. This mirrors ADR-016's Substrate
wiring exactly.

## 3. Consequences

### Positive
- Spoken I/O with zero new network surface and zero new transport — it rides the
  ADR-014 pipe, which already rejects remote clients at the OS level.
- STT reuses the OpenVINO/GPU stack the 14B already runs on; no new inference
  runtime.
- Voice selection is a first-class settings affordance from day one.
- Fail-soft: a model that will not load degrades to text-only chat, never a
  crash — same posture as the Substrate.
- Measured first-spoken-token budget ≈ 2.6 s (Whisper 0.53 + Qwen3 TTFT ~0.7 +
  Kokoro first-chunk ~1.4), inside the <3 s target, on real hardware.

### Negative / accepted trade-offs
- **Kokoro on CPU**, not GPU, for the first ship — accepted because measured RTF
  0.30 meets the budget and a GPU execution-provider swap would disturb the
  working onnxruntime. Deferred behind `ONNX_PROVIDER` (§2.3).
- **base64 over the pipe** carries ~33 % overhead vs raw binary — accepted for
  codec reuse and symmetry; binary framing deferred (§2.4).
- **+~525 MB** resident for the two model stacks (whisper-small + Kokoro-82M) —
  accepted against the banked headroom; quality-over-size is the named trade-off
  (§2.2).
- The C# audio path (mic capture, incremental playback) cannot be driven
  headlessly; it is verified live by the User-Operator per the ADR-014 GUI-layer
  relaxation. The Python voice engine, audio codec, and dispatcher methods stay
  under automated coverage.

### Security / privacy notes
- No external network: both models load from local disk; inference is local.
  Voice holds the same absolute no-network mandate as the rest of the runtime.
- Transcribed audio becomes a normal prompt and flows through PGOV and the full
  governance path unchanged — STT does not widen what the model can do, and the
  mic is not a model-invokable tool. Layer 3 (ADR-013) remains paused; voice does
  not change the tool blast radius that would require un-pausing it.
- Microphone capture runs inside the (elevated, for Hyper-V) WinUI process
  itself; it is not the cross-integrity-level window-message path that UIPI
  blocks for drag-drop, so de-elevation is not a prerequisite. Capture uses
  `AudioGraph` (works in an unpackaged desktop app). On-hardware mic-consent
  behavior is a live-verify point; if it is blocked in practice, the
  de-elevation refactor is the fallback.

## 4. Implementation

- `services/voice/src/engine.py` — `VoiceEngine`: holds the optional Whisper
  pipeline + Kokoro instance; `transcribe`, `synthesize_stream`,
  `available_voices`; fail-soft `load(...)` classmethod; `stt_available` /
  `tts_available` flags.
- `services/voice/src/audio.py` — pure PCM/base64/resample helpers
  (int16↔float32, 24 kHz→16 kHz), unit-testable with no models.
- `services/ui_backend/src/dispatcher.py` — `_m_transcribe`, `_m_synthesize`,
  `_m_voice_status`; a `voice` engine injected like the gateway (default `None`
  → methods report unavailable).
- `services/ui_backend/src/_stub.py` — deterministic stub voice engine.
- `launcher/__main__.py` `_run_winui_surface` — build the models fail-soft,
  inject into the dispatcher.
- WinUI: `AudioGraph` mic capture + incremental playback; mic button in the
  composer; settings flyout (wire the gear) with voice toggle + voice combo;
  per-message play button calling `synthesize` on the reply text;
  `UserPrefs.VoiceOutput` / `UserPrefs.Voice`.
- Models on disk under the gitignored `models/whisper-small/openvino/` and
  `models/kokoro/` (weights are not committed, by design).

## 5. Deferred

- Voice-activity detection (VAD) for hands-free turn-taking — first ship is
  push-to-talk.
- GPU execution provider for Kokoro behind `ONNX_PROVIDER` (§2.3).
- Type-tagged raw-binary audio frames to drop the base64 overhead (§2.4).
- Servicing the broken optimum exporter (Vikunja #541) to re-enable in-tree
  model conversion.
