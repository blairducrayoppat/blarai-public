"""
Eval Harness — Continuous-Batching Engine Arms (#1663)
======================================================
Locks the ``--engine`` arms that serve a Qwen3.5 export (with its Multi-Token
Prediction head) through ``ContinuousBatchingPipeline`` and attach the REAL Policy
Agent / Assistant Orchestrator to it.

Coverage:
  A. resolve_model_target — every fail-closed branch of the engine contract.
  B. CBEnginePipeline construction — the three arms differ in exactly the
     variable named (draft model present iff MTP; prefix caching iff the
     prefix-cache arm), one request at a time, MTP knobs set per generation, and
     each generation records its witness row.
  C. assert_mtp_engaged — REFUSES a speed claim when no draft token was accepted
     (the toggle test: the same function passes when tokens were accepted).
  D. Suite threading — a CB-engine target is NOT skipped by the PA or preference
     suites (the multimodal skip covered only the VLMPipeline arm).
  E. Launcher controls — the pinned marker is accepted by production's own
     marker pattern, and the perturbations change the text as named.

The OpenVINO boundary is faked (no weights, no GPU): the real runs are the
hardware campaign, recorded in PERFORMANCE_LOG.md.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import Any

import pytest

# Imported BEFORE any test installs a fake openvino_genai: shared_pipeline binds
# ov_genai at import, so a first import inside a fake window would keep the fake.
import shared.inference.shared_pipeline  # noqa: F401
from evals import cb_pipeline
from evals.cb_pipeline import (
    CBEngineError,
    CBEnginePipeline,
    assert_mtp_engaged,
    engine_spec,
)
from evals.model_target import ModelTargetError, resolve_model_target


def _vlm_dir(root: Path, *, mtp: bool = True) -> Path:
    d = root / "qwen35"
    d.mkdir(parents=True, exist_ok=True)
    (d / "openvino_language_model.xml").write_text("<net/>", encoding="utf-8")
    if mtp:
        (d / "openvino_mtp_model.xml").write_text("<net/>", encoding="utf-8")
    return d


def _llm_dir(root: Path) -> Path:
    d = root / "qwen3"
    d.mkdir(parents=True, exist_ok=True)
    (d / "openvino_model.xml").write_text("<net/>", encoding="utf-8")
    return d


# ---------------------------------------------------------------------------
# A. resolve_model_target
# ---------------------------------------------------------------------------


class TestResolveEngine:
    def test_default_engine_is_not_a_cb_engine(self, tmp_path: Path) -> None:
        t = resolve_model_target(
            model_dir=_vlm_dir(tmp_path), capability="multimodal-vlm", env={}
        )
        assert t is not None and t.engine == "default" and not t.uses_cb_engine

    def test_mtp_on_resolves(self, tmp_path: Path) -> None:
        t = resolve_model_target(
            model_dir=_vlm_dir(tmp_path),
            capability="multimodal-vlm",
            engine="cb-mtp-on",
            env={},
        )
        assert t is not None and t.uses_cb_engine and t.engine == "cb-mtp-on"

    def test_mtp_on_without_head_fails_closed(self, tmp_path: Path) -> None:
        with pytest.raises(ModelTargetError, match="openvino_mtp_model.xml"):
            resolve_model_target(
                model_dir=_vlm_dir(tmp_path, mtp=False),
                capability="multimodal-vlm",
                engine="cb-mtp-on",
                env={},
            )

    def test_mtp_off_does_not_need_the_head(self, tmp_path: Path) -> None:
        t = resolve_model_target(
            model_dir=_vlm_dir(tmp_path, mtp=False),
            capability="multimodal-vlm",
            engine="cb-mtp-off",
            env={},
        )
        assert t is not None and t.engine == "cb-mtp-off"

    def test_engine_on_text_llm_fails_closed(self, tmp_path: Path) -> None:
        with pytest.raises(ModelTargetError, match="multimodal-vlm"):
            resolve_model_target(
                model_dir=_llm_dir(tmp_path),
                capability="text-llm",
                engine="cb-mtp-off",
                env={},
            )

    def test_unknown_engine_fails_closed(self, tmp_path: Path) -> None:
        with pytest.raises(ModelTargetError, match="unknown eval engine"):
            resolve_model_target(
                model_dir=_vlm_dir(tmp_path),
                capability="multimodal-vlm",
                engine="cb-turbo",
                env={},
            )

    def test_engine_without_dir_fails_loud(self) -> None:
        with pytest.raises(ModelTargetError, match="without --model-dir"):
            resolve_model_target(
                model_dir=None, capability=None, engine="cb-mtp-on", env={}
            )

    def test_env_fallback(self, tmp_path: Path) -> None:
        t = resolve_model_target(
            model_dir=_vlm_dir(tmp_path),
            capability="multimodal-vlm",
            env={"BLARAI_EVAL_ENGINE": "cb-prefix-cache"},
        )
        assert t is not None and t.engine == "cb-prefix-cache"


# ---------------------------------------------------------------------------
# B. CBEnginePipeline against a faked openvino_genai
# ---------------------------------------------------------------------------


class _FakeSched:
    cache_size = 0
    max_num_seqs = 0
    enable_prefix_caching = None


class _FakeCfg:
    num_assistant_tokens = 0
    assistant_confidence_threshold = -1.0


class _Mean:
    def __init__(self, v: float) -> None:
        self.mean = v


class _Perf:
    def get_num_generated_tokens(self) -> int:
        return 10

    def get_num_input_tokens(self) -> int:
        return 20

    def get_ttft(self) -> _Mean:
        return _Mean(50.0)

    def get_tpot(self) -> _Mean:
        return _Mean(20.0)


class _Ext:
    def __init__(self, accepted: int, drafted: int) -> None:
        self._a, self._d = accepted, drafted

    def get_num_draft_tokens(self) -> int:
        return self._d

    def get_num_accepted_tokens(self) -> int:
        return self._a

    def get_num_rejected_tokens(self) -> int:
        return self._d - self._a

    def get_draft_acceptance_rate(self) -> float:
        return self._a / self._d if self._d else 0.0


class _Result:
    def __init__(self, text: str, ext: _Ext | None) -> None:
        self.m_generation_ids = [text]
        self.perf_metrics = _Perf()
        self.extended_perf_metrics = ext


def _install_fake_genai(monkeypatch: pytest.MonkeyPatch, *, accepted: int) -> types.SimpleNamespace:
    seen = types.SimpleNamespace(
        sched=None, props=None, device=None, drafts=[], cfgs=[], pipeline_calls=0
    )

    class _Pipe:
        def __init__(self, path: str, sched: Any, device: str, props: dict[str, Any]) -> None:
            seen.sched, seen.props, seen.device = sched, props, device
            self._mtp = "draft_model" in props

        def generate(self, prompts: list[str], cfgs: list[Any], streamer: Any) -> list[_Result]:
            seen.pipeline_calls += 1
            seen.cfgs.append(cfgs[0])
            streamer("A")
            streamer("B")
            ext = _Ext(accepted, 6) if self._mtp else None
            return [_Result("AB", ext)]

        def get_tokenizer(self) -> str:
            return "tok"

    fake = types.SimpleNamespace(
        __version__="fake-1",
        SchedulerConfig=_FakeSched,
        GenerationConfig=_FakeCfg,
        ContinuousBatchingPipeline=_Pipe,
        StreamingStatus=types.SimpleNamespace(RUNNING="RUNNING"),
        draft_model=lambda path, device, **kw: ("draft", path, device),
    )
    monkeypatch.setitem(sys.modules, "openvino_genai", fake)
    return seen


class TestCBEnginePipeline:
    def test_arms_differ_only_in_the_named_variable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        d = _vlm_dir(tmp_path)
        seen = _install_fake_genai(monkeypatch, accepted=5)

        CBEnginePipeline(d, "cb-mtp-off")
        assert "draft_model" not in seen.props
        assert seen.sched.enable_prefix_caching is False

        CBEnginePipeline(d, "cb-mtp-on")
        assert "draft_model" in seen.props
        assert seen.sched.enable_prefix_caching is False

        CBEnginePipeline(d, "cb-prefix-cache")
        assert "draft_model" not in seen.props
        assert seen.sched.enable_prefix_caching is True

    def test_one_request_at_a_time_and_stamped_properties(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = _install_fake_genai(monkeypatch, accepted=5)
        p = CBEnginePipeline(_vlm_dir(tmp_path), "cb-mtp-off")
        assert seen.sched.max_num_seqs == 1
        assert seen.props["KV_CACHE_PRECISION"] == "f16"
        assert seen.props["DYNAMIC_QUANTIZATION_GROUP_SIZE"] == 0
        assert p.header["compile_properties"]["KV_CACHE_PRECISION"] == "f16"

    def test_mtp_arm_without_head_refuses_to_load(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_fake_genai(monkeypatch, accepted=5)
        with pytest.raises(CBEngineError, match="openvino_mtp_model.xml"):
            CBEnginePipeline(_vlm_dir(tmp_path, mtp=False), "cb-mtp-on")

    def test_generation_sets_mtp_knobs_and_records_witness(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = _install_fake_genai(monkeypatch, accepted=5)
        p = CBEnginePipeline(_vlm_dir(tmp_path), "cb-mtp-on")
        out = p.generate("hi", generation_config=_FakeCfg())
        assert str(out) == "AB"
        assert seen.cfgs[0].num_assistant_tokens == cb_pipeline.MTP_NUM_ASSISTANT_TOKENS
        assert seen.cfgs[0].assistant_confidence_threshold == 0.0
        row = out.stats
        assert row["first_chunk"] == "A" and row["n_stream_chunks"] == 2
        assert row["accepted_tokens"] == 5 and row["draft_tokens"] == 6
        assert p.generate_call_count == 1

    def test_plain_arm_does_not_touch_mtp_knobs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = _install_fake_genai(monkeypatch, accepted=5)
        p = CBEnginePipeline(_vlm_dir(tmp_path), "cb-mtp-off")
        p.generate("hi", generation_config=_FakeCfg())
        assert seen.cfgs[0].num_assistant_tokens == 0

    def test_streamer_is_forwarded_and_its_status_returned(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_fake_genai(monkeypatch, accepted=5)
        p = CBEnginePipeline(_vlm_dir(tmp_path), "cb-mtp-off")
        got: list[str] = []
        p.generate("hi", generation_config=_FakeCfg(), streamer=lambda c: got.append(c) or "RUNNING")
        assert got == ["A", "B"]

    def test_raw_handle_generates_without_reacquiring_the_lock(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_fake_genai(monkeypatch, accepted=5)
        p = CBEnginePipeline(_vlm_dir(tmp_path), "cb-mtp-off")
        status, value = p.try_run_exclusive(lambda raw: str(raw.generate("hi", _FakeCfg())))
        assert value == "AB"
        assert p.get_tokenizer() == "tok"

    def test_registry_keeps_one_resident_copy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_fake_genai(monkeypatch, accepted=5)
        d = _vlm_dir(tmp_path)
        monkeypatch.setattr(cb_pipeline, "_REGISTRY", {})
        a1 = cb_pipeline.get_engine_pipeline(d, "cb-mtp-off")
        a2 = cb_pipeline.get_engine_pipeline(d, "cb-mtp-off")
        assert a1 is a2
        b = cb_pipeline.get_engine_pipeline(d, "cb-mtp-on")
        assert len(cb_pipeline.registered_pipelines()) == 1 and b is not a1

    def test_unknown_engine_name_raises(self) -> None:
        with pytest.raises(CBEngineError):
            engine_spec("default")


# ---------------------------------------------------------------------------
# C. assert_mtp_engaged — tested ON and OFF
# ---------------------------------------------------------------------------


class TestAssertMtpEngaged:
    def test_refuses_zero_accepted_tokens(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_fake_genai(monkeypatch, accepted=0)
        p = CBEnginePipeline(_vlm_dir(tmp_path), "cb-mtp-on")
        p.generate("hi", generation_config=_FakeCfg())
        with pytest.raises(CBEngineError, match="did not engage"):
            assert_mtp_engaged(p)

    def test_passes_when_tokens_were_accepted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_fake_genai(monkeypatch, accepted=5)
        p = CBEnginePipeline(_vlm_dir(tmp_path), "cb-mtp-on")
        p.generate("hi", generation_config=_FakeCfg())
        summary = assert_mtp_engaged(p)
        assert summary["accepted_tokens"] == 5 and summary["acceptance_rate"] == round(5 / 6, 4)

    def test_does_not_apply_to_the_plain_arm(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_fake_genai(monkeypatch, accepted=0)
        p = CBEnginePipeline(_vlm_dir(tmp_path), "cb-mtp-off")
        p.generate("hi", generation_config=_FakeCfg())
        assert assert_mtp_engaged(p)["accepted_tokens"] == 0

    def test_think_first_chunk_is_counted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_fake_genai(monkeypatch, accepted=5)
        p = CBEnginePipeline(_vlm_dir(tmp_path), "cb-mtp-off")
        p.generate("hi", generation_config=_FakeCfg())
        p.stats[0]["first_chunk"] = "<think>"
        assert p.summary()["think_first_chunk_count"] == 1


# ---------------------------------------------------------------------------
# D. Suite threading — a CB target is not skipped
# ---------------------------------------------------------------------------


class TestSuiteThreading:
    def test_pa_cb_target_is_not_skipped(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from evals.suites import pa_classification as pa

        target = resolve_model_target(
            model_dir=_vlm_dir(tmp_path),
            capability="multimodal-vlm",
            engine="cb-mtp-on",
            env={},
        )
        built: dict[str, Any] = {}

        def fake_builder(model_dir: Path, **kw: Any):
            built.update(kw)
            return lambda car: ("ALLOW", None)

        monkeypatch.setattr(pa, "make_real_gpu_classifier", fake_builder)
        report = pa.run_suite(include_hardware=True, model_target=target)
        assert report.skipped_hardware == 0
        assert built.get("engine") == "cb-mtp-on"

    def test_pa_plain_vlm_target_is_still_skipped(self, tmp_path: Path) -> None:
        from evals.suites import pa_classification as pa

        target = resolve_model_target(
            model_dir=_vlm_dir(tmp_path), capability="multimodal-vlm", env={}
        )
        report = pa.run_suite(include_hardware=True, model_target=target)
        assert report.skipped_hardware > 0


# ---------------------------------------------------------------------------
# E. Launcher controls
# ---------------------------------------------------------------------------


def _load_launcher() -> Any:
    path = Path(__file__).resolve().parents[2] / "scripts" / "run_evals_instrumented.py"
    spec = importlib.util.spec_from_file_location("run_evals_instrumented", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestLauncherControls:
    def test_pinned_marker_matches_production_marker_pattern(self) -> None:
        from services.assistant_orchestrator.src.context_manager import _DATA_MARKER_PATTERN

        launcher = _load_launcher()
        assert _DATA_MARKER_PATTERN.fullmatch(launcher.PINNED_MARKER)

    def test_perturbations_change_text_as_named(self) -> None:
        launcher = _load_launcher()
        base = "One. Two. Three."
        assert launcher._perturb_text(base, "V0") == base
        assert launcher._perturb_text(base, "V1") == base + " "
        assert launcher._perturb_text(base, "V2") == "One.  Two.  Three."

    def test_pin_marker_makes_two_marks_identical(self) -> None:
        from services.assistant_orchestrator.src import context_manager as cm

        original = cm._generate_data_marker
        try:
            assert original() != original()  # production: fresh random token each time
            launcher = _load_launcher()
            launcher._pin_marker()
            assert cm._generate_data_marker() == cm._generate_data_marker() == launcher.PINNED_MARKER
        finally:
            cm._generate_data_marker = original
