"""BlarAI Voice — local speech-to-text and text-to-speech (ADR-017).

Whisper-small (STT, OpenVINO/GPU) and Kokoro-82M (TTS, kokoro-onnx/CPU) behind a
small fail-soft engine injected into the UI-backend dispatcher. No external
network: both models load from local disk and inference is local. See ADR-017.
"""
