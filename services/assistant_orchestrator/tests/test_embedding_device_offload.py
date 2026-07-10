"""Embedding device offload (#720) — knob, fail-soft fallback, plumbing.

Covers the ``[embeddings].device`` knob end to end WITHOUT the real model:

  * construction defaults + device-string normalisation;
  * the fail-SOFT fallback (an OpenVINO compile failure logs the
    deterministic ``EMBED_OFFLOAD_FALLBACK`` fingerprint and lands on the
    ONNX Runtime CPU path — never a refused start);
  * static-window selection + batch-of-one inference on the OpenVINO path;
  * config validation (fail-closed on a device typo) + resolution;
  * the ``_get_detector(device=...)`` singleton plumbing and both entrypoint
    build sites passing the resolved device through.

The real NPU/GPU round-trip (real model, real silicon) is ``@hardware`` at
the bottom — deselected from the standing gate.
"""

from __future__ import annotations

import logging
import sys
import tomllib
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from services.assistant_orchestrator.src import pgov
from services.assistant_orchestrator.src.entrypoint import (
    AssistantOrchestratorService,
)
from services.assistant_orchestrator.src.pgov import LeakageDetector
from services.assistant_orchestrator.tests.test_entrypoint import (
    _write_minimal_config,
)
from shared.runtime_config import ConfigResolutionError

_REPO_ROOT = Path(__file__).resolve().parents[3]


# ─────────────────────────── fakes ────────────────────────────────────


class _RecordingTokenizer:
    """Tokenizer fake recording padding/max_length; emits fixed-shape arrays."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        texts: list[str],
        padding: Any,
        truncation: bool,
        max_length: int,
        return_tensors: str,
    ) -> dict[str, Any]:
        self.calls.append({"padding": padding, "max_length": max_length})
        n = len(texts)
        seq = max_length if padding == "max_length" else 7
        return {
            "input_ids": np.ones((n, seq), dtype=np.int64),
            "attention_mask": np.ones((n, seq), dtype=np.int64),
        }


class _FakeRequest:
    """Static-window infer request fake — records per-call batch shapes."""

    def __init__(self, window: int, log: list[tuple[int, int]]) -> None:
        self._window = window
        self._log = log

    def infer(self, feed: dict[str, Any]) -> dict[str, Any]:
        shape = feed["input_ids"].shape
        self._log.append((int(shape[0]), int(shape[1])))
        return {"out": np.random.default_rng(0).normal(
            size=(shape[0], shape[1], 384)
        ).astype(np.float32)}


class _FakeStaticCompiled:
    """A static-shape compiled model for one token window."""

    def __init__(self, window: int) -> None:
        self.window = window
        self.infer_log: list[tuple[int, int]] = []

    def create_infer_request(self) -> _FakeRequest:
        return _FakeRequest(self.window, self.infer_log)


def _offload_detector(
    windows: dict[int, Any], tokenizer: _RecordingTokenizer
) -> LeakageDetector:
    det = LeakageDetector(model_path="unused/model.onnx", device="NPU")
    det._tokenizer = tokenizer
    det._ov_compiled = windows
    det._ov_input_names = ["input_ids", "attention_mask"]
    det._backend = "openvino"
    det._active_device = "NPU"
    det._loaded = True
    return det


# ─────────────────────── construction + knob ──────────────────────────


class TestDeviceKnobConstruction:
    def test_default_is_cpu_ort(self) -> None:
        det = LeakageDetector(model_path="unused/model.onnx")
        assert det._device == "CPU"
        assert det.backend == "ort-cpu"
        assert det.active_device == "CPU"

    @pytest.mark.parametrize("raw", ["npu", " NPU ", "Npu"])
    def test_device_string_normalised(self, raw: str) -> None:
        det = LeakageDetector(model_path="unused/model.onnx", device=raw)
        assert det._device == "NPU"

    @pytest.mark.parametrize("raw", ["", "   ", None])
    def test_empty_device_falls_back_to_cpu(self, raw: str | None) -> None:
        det = LeakageDetector(model_path="unused/model.onnx", device=raw)  # type: ignore[arg-type]
        assert det._device == "CPU"

    def test_offload_windows_cover_leakage_and_document_paths(self) -> None:
        # 128 = the calibrated PGOV Stage-5 window; 512 = the document window.
        assert LeakageDetector._OFFLOAD_WINDOWS == (128, 512)


# ─────────────────────── singleton plumbing ───────────────────────────


@pytest.fixture()
def _fresh_singleton() -> Any:
    saved = pgov._detector
    pgov._detector = None
    yield
    pgov._detector = saved


class TestGetDetectorDevice:
    def test_creates_singleton_with_device(self, _fresh_singleton: Any) -> None:
        det = pgov._get_detector(device="NPU")
        assert det._device == "NPU"

    def test_none_device_keeps_cpu_default(self, _fresh_singleton: Any) -> None:
        det = pgov._get_detector(device=None)
        assert det._device == "CPU"

    def test_existing_singleton_device_is_fixed(self, _fresh_singleton: Any) -> None:
        first = pgov._get_detector(device="NPU")
        second = pgov._get_detector(device="GPU")
        assert second is first
        assert second._device == "NPU"


# ─────────────────────── fail-soft fallback ───────────────────────────


class _FakeOrtInput:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeOrtSession:
    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        pass

    def get_inputs(self) -> list[_FakeOrtInput]:
        return [_FakeOrtInput("input_ids"), _FakeOrtInput("attention_mask")]

    def run(self, _outputs: Any, feed: dict[str, Any]) -> list[Any]:
        n, seq = feed["input_ids"].shape
        return [np.ones((n, seq, 384), dtype=np.float32)]


class TestFailSoftFallback:
    def _patch_ort_layer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import onnxruntime as ort
        import transformers

        monkeypatch.setattr(ort, "InferenceSession", _FakeOrtSession)
        monkeypatch.setattr(
            transformers.AutoTokenizer,
            "from_pretrained",
            # **_kwargs absorbs the #633 hardening kwargs (local_files_only,
            # trust_remote_code) the LeakageDetector now passes.
            classmethod(lambda _cls, _dir, **_kwargs: _RecordingTokenizer()),
        )

    def test_openvino_failure_falls_back_to_ort_cpu(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """The load-bearing #720 posture: offload failure NEVER refuses to
        start — the detector lands loaded on the ONNX Runtime CPU path."""
        self._patch_ort_layer(monkeypatch)
        det = LeakageDetector(model_path="unused/model.onnx", device="NPU")
        monkeypatch.setattr(det, "_try_load_openvino", lambda _dev: False)

        with caplog.at_level(logging.WARNING):
            assert det.load_model() is True

        assert det.loaded
        assert det.backend == "ort-cpu"
        assert det.active_device == "CPU"
        assert any("EMBED_OFFLOAD_FALLBACK" in r.message for r in caplog.records)

    def test_openvino_import_failure_returns_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(sys.modules, "openvino", None)
        det = LeakageDetector(model_path="unused/model.onnx", device="NPU")
        assert det._try_load_openvino("NPU") is False
        assert det._ov_compiled == {}

    def test_compile_failure_logs_deterministic_fingerprint(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        fake_ov = types.ModuleType("openvino")

        class _ExplodingCore:
            def set_property(self, _props: dict[str, str]) -> None:
                pass

            def read_model(self, _path: str) -> Any:
                raise RuntimeError("NPU plugin exploded")

        fake_ov.Core = _ExplodingCore  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "openvino", fake_ov)

        det = LeakageDetector(model_path="unused/model.onnx", device="NPU")
        with caplog.at_level(logging.WARNING):
            assert det._try_load_openvino("NPU") is False
        fingerprints = [
            r.message for r in caplog.records if "EMBED_OFFLOAD_FALLBACK" in r.message
        ]
        assert fingerprints, "deterministic fallback fingerprint missing"
        assert "device=NPU" in fingerprints[0]
        assert "RuntimeError" in fingerprints[0]

    def test_cpu_device_never_touches_openvino(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """device=CPU must remain the byte-identical pre-#720 ORT path."""
        self._patch_ort_layer(monkeypatch)
        det = LeakageDetector(model_path="unused/model.onnx", device="CPU")

        def _boom(_dev: str) -> bool:
            raise AssertionError("OpenVINO path must not engage for CPU")

        monkeypatch.setattr(det, "_try_load_openvino", _boom)
        assert det.load_model() is True
        assert det.backend == "ort-cpu"


# ─────────────────── OpenVINO embed path (no model) ───────────────────


class TestStaticWindowSelection:
    def test_exact_window_used(self) -> None:
        tok = _RecordingTokenizer()
        w128, w512 = _FakeStaticCompiled(128), _FakeStaticCompiled(512)
        det = _offload_detector({128: w128, 512: w512}, tok)

        out = det._embed_at(["a", "b"], 128)
        assert out.shape == (2, 384)
        assert w128.infer_log and not w512.infer_log
        assert tok.calls[-1] == {"padding": "max_length", "max_length": 128}

    def test_intermediate_length_selects_covering_window(self) -> None:
        tok = _RecordingTokenizer()
        w128, w512 = _FakeStaticCompiled(128), _FakeStaticCompiled(512)
        det = _offload_detector({128: w128, 512: w512}, tok)

        det._embed_at(["a"], 300)
        assert w512.infer_log and not w128.infer_log
        assert tok.calls[-1]["max_length"] == 512

    def test_oversized_request_clamps_to_largest_window(self) -> None:
        tok = _RecordingTokenizer()
        w128, w512 = _FakeStaticCompiled(128), _FakeStaticCompiled(512)
        det = _offload_detector({128: w128, 512: w512}, tok)

        det._embed_at(["a"], 4096)
        assert w512.infer_log
        assert tok.calls[-1]["max_length"] == 512

    def test_batch_runs_one_text_per_infer(self) -> None:
        """The NPU compile is batch-1 static: 3 texts = 3 infer calls."""
        tok = _RecordingTokenizer()
        w128 = _FakeStaticCompiled(128)
        det = _offload_detector({128: w128, 512: _FakeStaticCompiled(512)}, tok)

        out = det._embed_at(["a", "b", "c"], 128)
        assert out.shape == (3, 384)
        assert w128.infer_log == [(1, 128), (1, 128), (1, 128)]

    def test_embeddings_are_l2_normalised(self) -> None:
        tok = _RecordingTokenizer()
        det = _offload_detector(
            {128: _FakeStaticCompiled(128), 512: _FakeStaticCompiled(512)}, tok
        )
        out = det._embed_at(["a", "b"], 128)
        assert np.allclose(np.linalg.norm(out, axis=1), 1.0, atol=1e-5)

    def test_not_loaded_raises(self) -> None:
        det = LeakageDetector(model_path="unused/model.onnx", device="NPU")
        det._backend = "openvino"
        det._ov_compiled = {128: _FakeStaticCompiled(128)}
        det._tokenizer = None
        with pytest.raises(RuntimeError, match="not loaded"):
            det._embed_ov(["a"], 128)


class _FakeDynamicCompiled:
    """A dynamic-shape compiled model (GPU path) — one batched call."""

    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []
        self._key = "out"

    def output(self, _index: int) -> str:
        return self._key

    def __call__(self, feed: dict[str, Any]) -> dict[str, Any]:
        n, seq = feed["input_ids"].shape
        self.calls.append((n, seq))
        return {self._key: np.ones((n, seq, 384), dtype=np.float32)}


class TestDynamicPath:
    def test_dynamic_compile_batches_in_one_call(self) -> None:
        tok = _RecordingTokenizer()
        dyn = _FakeDynamicCompiled()
        det = _offload_detector({0: dyn}, tok)

        out = det._embed_at(["a", "b", "c"], 128)
        assert out.shape == (3, 384)
        assert dyn.calls == [(3, 7)]  # one batched call, natural padding
        assert tok.calls[-1]["padding"] is True


class TestUnloadClearsOffloadState:
    def test_unload_resets_backend(self) -> None:
        det = _offload_detector(
            {128: _FakeStaticCompiled(128)}, _RecordingTokenizer()
        )
        det.unload()
        assert det._ov_compiled == {}
        assert det._ov_input_names == []
        assert det.backend == "ort-cpu"
        assert det.active_device == "CPU"
        assert not det.loaded


# ───────────────────── config validation + resolution ─────────────────


def _service_and_data(
    tmp_path: Path, extra_toml: str = ""
) -> tuple[AssistantOrchestratorService, dict[str, Any], Path]:
    config_path = (
        tmp_path / "services" / "assistant_orchestrator" / "config" / "default.toml"
    )
    _write_minimal_config(config_path)
    if extra_toml:
        config_path.write_text(
            config_path.read_text(encoding="utf-8") + "\n" + extra_toml,
            encoding="utf-8",
        )
    with open(config_path, "rb") as fh:
        data = tomllib.load(fh)
    return AssistantOrchestratorService(config_path), data, config_path


class TestEmbeddingsConfigValidation:
    def test_absent_section_is_valid(self, tmp_path: Path) -> None:
        service, data, path = _service_and_data(tmp_path)
        service._validate_config_data(data, path)  # must not raise

    def test_valid_devices_accepted_case_insensitive(self, tmp_path: Path) -> None:
        for dev in ("CPU", "GPU", "NPU", "npu", "gpu"):
            service, data, path = _service_and_data(
                tmp_path, f'[embeddings]\ndevice = "{dev}"'
            )
            service._validate_config_data(data, path)

    def test_unknown_device_rejected_fail_closed(self, tmp_path: Path) -> None:
        service, data, path = _service_and_data(
            tmp_path, '[embeddings]\ndevice = "TPU"'
        )
        with pytest.raises(ConfigResolutionError) as exc:
            service._validate_config_data(data, path)
        assert exc.value.code == "AO_CFG_EMBEDDINGS_DEVICE_INVALID"

    def test_non_string_device_rejected(self, tmp_path: Path) -> None:
        service, data, path = _service_and_data(
            tmp_path, "[embeddings]\ndevice = 42"
        )
        with pytest.raises(ConfigResolutionError) as exc:
            service._validate_config_data(data, path)
        assert exc.value.code == "AO_CFG_EMBEDDINGS_DEVICE_INVALID"

    def test_non_table_section_rejected(self, tmp_path: Path) -> None:
        service, data, path = _service_and_data(tmp_path)
        data["embeddings"] = "NPU"
        with pytest.raises(ConfigResolutionError) as exc:
            service._validate_config_data(data, path)
        assert exc.value.code == "AO_CFG_EMBEDDINGS_SECTION_INVALID"

    def test_empty_table_is_valid(self, tmp_path: Path) -> None:
        service, data, path = _service_and_data(tmp_path, "[embeddings]")
        service._validate_config_data(data, path)


class TestEmbeddingsDeviceResolution:
    def test_absent_section_resolves_cpu(self, tmp_path: Path) -> None:
        service, _data, _path = _service_and_data(tmp_path)
        resolved = service._load_entrypoint_config()
        assert resolved.embeddings_device == "CPU"

    def test_device_resolved_and_normalised(self, tmp_path: Path) -> None:
        service, _data, _path = _service_and_data(
            tmp_path, '[embeddings]\ndevice = "npu"'
        )
        resolved = service._load_entrypoint_config()
        assert resolved.embeddings_device == "NPU"

    def test_shipped_default_toml_sets_npu(self) -> None:
        """Lock the shipped production default to the measured decision
        (2026-07-02 on-box benchmark — see PERFORMANCE_LOG.md)."""
        shipped = (
            _REPO_ROOT
            / "services"
            / "assistant_orchestrator"
            / "config"
            / "default.toml"
        )
        with open(shipped, "rb") as fh:
            data = tomllib.load(fh)
        assert data["embeddings"]["device"] == "NPU"


# ─────────────────── entrypoint build-site plumbing ────────────────────


class _RecordingUnloadedDetector:
    """Detector fake that refuses to load — trips the early-return in both
    build sites right AFTER the device has been passed through."""

    loaded = False

    def load_model(self) -> bool:
        return False


class TestBuildSitesPassDevice:
    def _recording_get_detector(
        self, monkeypatch: pytest.MonkeyPatch, seen: list[Any]
    ) -> None:
        def _fake_get_detector(device: str | None = None) -> Any:
            seen.append(device)
            return _RecordingUnloadedDetector()

        monkeypatch.setattr(pgov, "_get_detector", _fake_get_detector)

    def test_build_substrate_passes_resolved_device(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[Any] = []
        self._recording_get_detector(monkeypatch, seen)
        service = AssistantOrchestratorService("dummy.toml")
        service._resolved_config = SimpleNamespace(
            dev_mode=True, embeddings_device="NPU", embed_cache_idle_unload_s=900
        )
        assert service._build_substrate() is None  # detector refused → disabled
        assert seen == ["NPU"]

    def test_build_knowledge_bank_passes_resolved_device(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[Any] = []
        self._recording_get_detector(monkeypatch, seen)
        service = AssistantOrchestratorService("dummy.toml")
        service._resolved_config = SimpleNamespace(
            dev_mode=True,
            embeddings_device="NPU",
            knowledge_enabled=True,
        )
        assert service._build_knowledge_bank() is None
        assert seen == ["NPU"]


# ─────────────────────── @hardware round-trip ──────────────────────────


def _real_model_path() -> Path:
    return _REPO_ROOT / "models" / "bge-small-en-v1.5" / "onnx-fp16" / "model.onnx"


def _npu_available() -> bool:
    try:
        import openvino as ov

        return "NPU" in ov.Core().available_devices
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.hardware
class TestRealNpuOffload:
    """Real-model, real-silicon round-trip (deselected from the standing gate)."""

    def test_npu_load_and_parity_vs_cpu(self) -> None:
        model = _real_model_path()
        if not model.is_file():
            pytest.skip("bge-small model not present (gitignored)")
        if not _npu_available():
            pytest.skip("no NPU on this box")

        cpu = LeakageDetector(model_path=str(model), device="CPU")
        npu = LeakageDetector(model_path=str(model), device="NPU")
        assert cpu.load_model() is True
        assert npu.load_model() is True
        assert npu.backend == "openvino"
        assert npu.active_device == "NPU"

        texts = ["the quick brown fox", "local inference on lunar lake"]
        for max_len in (128, 512):
            a = cpu.embed_documents(texts, max_length=max_len)
            b = npu.embed_documents(texts, max_length=max_len)
            cosines = np.sum(a * b, axis=1)
            assert float(np.min(cosines)) >= 0.999, (
                f"NPU/CPU embedding divergence at window {max_len}: {cosines}"
            )
        cpu.unload()
        npu.unload()
