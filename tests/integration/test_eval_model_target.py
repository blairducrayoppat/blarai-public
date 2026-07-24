"""
Eval Harness — Hardware Model-Target Override (#931)
====================================================
Locks the OPT-IN ``--model-dir`` / ``--capability`` override that lets the eval
harness target an arbitrary OpenVINO model directory (the concrete unblock for
the 35B-A3B quality-parity gate, #930) instead of the hardcoded Qwen3-14B.

Coverage:
  A. resolve_model_target — default (no override -> None), every fail-closed
     branch (nonexistent dir, missing/unknown capability, capability contract
     with no dir, directory/capability mismatch), text-llm + multimodal-vlm
     success, speculative-decode contract, and env-variable fallback.
  B. answer_quality generator selection — the DEFAULT path is byte-identical
     (no target -> LLMPipeline loader with ONLY model_dir, no speculative
     override), a text-llm override threads dir + speculative contract, and a
     multimodal-vlm override builds the VLMPipeline arm.
  C. hardware_pipeline VLM arm — greedy text generation with the production
     system prompt wrapped in ChatML; fail-closed when openvino_genai is
     absent or the directory is missing.
  D. Runner CLI (evals.run) — fail-closed exit codes (nonexistent dir, override
     without --include-hardware, unknown capability via env) and that a VALID
     override does not disturb a deterministic suite's clean baseline.
  E. Suite threading — PA + preference-memory SKIP (loud, explained) a
     multimodal-vlm target rather than mis-pipelining it; model_target=None
     runs the ordinary injected model path unchanged.

The loader boundary is stubbed throughout (no real weights, no GPU) — the real
35B run is a hardware ceremony, out of scope here.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from evals import run as run_mod
from evals.model_target import (
    ENV_CAPABILITY,
    ENV_MODEL_DIR,
    ENV_NO_SPECULATIVE,
    Capability,
    ModelTarget,
    ModelTargetError,
    parse_capability,
    resolve_model_target,
)


# ---------------------------------------------------------------------------
# Fixtures: fake model directories matching each capability's IR contract.
# ---------------------------------------------------------------------------


def _make_llm_dir(root: Path, name: str = "qwen3-14b") -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "openvino_model.xml").write_text("<net/>", encoding="utf-8")
    return d


def _make_vlm_dir(root: Path, name: str = "qwen3.5-35b-a3b") -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "openvino_language_model.xml").write_text("<net/>", encoding="utf-8")
    return d


# ---------------------------------------------------------------------------
# A. resolve_model_target
# ---------------------------------------------------------------------------


class TestResolveModelTarget:
    def test_no_override_resolves_to_none(self) -> None:
        assert (
            resolve_model_target(model_dir=None, capability=None, env={}) is None
        )

    def test_text_llm_success_defaults_speculative_on(self, tmp_path: Path) -> None:
        d = _make_llm_dir(tmp_path)
        target = resolve_model_target(
            model_dir=d, capability="text-llm", env={}
        )
        assert target is not None
        assert target.model_dir == d
        assert target.capability is Capability.TEXT_LLM
        assert target.speculative_decode is True
        assert target.uses_vlm_pipeline is False

    def test_text_llm_no_speculative(self, tmp_path: Path) -> None:
        d = _make_llm_dir(tmp_path)
        target = resolve_model_target(
            model_dir=d, capability="text-llm", no_speculative=True, env={}
        )
        assert target is not None
        assert target.speculative_decode is False

    def test_multimodal_vlm_success_spec_structurally_off(self, tmp_path: Path) -> None:
        d = _make_vlm_dir(tmp_path)
        # Even without --no-speculative, VLM has no draft-model spec decode.
        target = resolve_model_target(
            model_dir=d, capability="multimodal-vlm", env={}
        )
        assert target is not None
        assert target.capability is Capability.MULTIMODAL_VLM
        assert target.speculative_decode is False
        assert target.uses_vlm_pipeline is True

    def test_nonexistent_dir_fails_closed(self, tmp_path: Path) -> None:
        with pytest.raises(ModelTargetError, match="does not exist"):
            resolve_model_target(
                model_dir=tmp_path / "nope", capability="text-llm", env={}
            )

    def test_dir_without_capability_fails_closed(self, tmp_path: Path) -> None:
        d = _make_llm_dir(tmp_path)
        with pytest.raises(ModelTargetError, match="requires --capability"):
            resolve_model_target(model_dir=d, capability=None, env={})

    def test_capability_without_dir_fails_loud(self) -> None:
        with pytest.raises(ModelTargetError, match="without --model-dir"):
            resolve_model_target(model_dir=None, capability="text-llm", env={})

    def test_no_speculative_without_dir_fails_loud(self) -> None:
        with pytest.raises(ModelTargetError, match="without --model-dir"):
            resolve_model_target(
                model_dir=None, capability=None, no_speculative=True, env={}
            )

    def test_capability_directory_mismatch_fails_closed(self, tmp_path: Path) -> None:
        # A VLM directory declared as text-llm: the LLM IR file is absent.
        d = _make_vlm_dir(tmp_path)
        with pytest.raises(ModelTargetError, match="does not match the declared"):
            resolve_model_target(model_dir=d, capability="text-llm", env={})

    def test_text_llm_dir_declared_vlm_fails_closed(self, tmp_path: Path) -> None:
        d = _make_llm_dir(tmp_path)
        with pytest.raises(ModelTargetError, match="does not match the declared"):
            resolve_model_target(model_dir=d, capability="multimodal-vlm", env={})

    def test_file_path_is_not_a_directory(self, tmp_path: Path) -> None:
        f = tmp_path / "afile.xml"
        f.write_text("x", encoding="utf-8")
        with pytest.raises(ModelTargetError, match="not a directory"):
            resolve_model_target(model_dir=f, capability="text-llm", env={})

    def test_unknown_capability_via_env_fails_closed(self, tmp_path: Path) -> None:
        d = _make_llm_dir(tmp_path)
        env = {ENV_MODEL_DIR: str(d), ENV_CAPABILITY: "quantum-oracle"}
        with pytest.raises(ModelTargetError, match="unknown eval capability"):
            resolve_model_target(model_dir=None, capability=None, env=env)

    def test_env_fallback_resolves(self, tmp_path: Path) -> None:
        d = _make_vlm_dir(tmp_path)
        env = {ENV_MODEL_DIR: str(d), ENV_CAPABILITY: "multimodal-vlm"}
        target = resolve_model_target(model_dir=None, capability=None, env=env)
        assert target is not None
        assert target.capability is Capability.MULTIMODAL_VLM

    def test_cli_overrides_env(self, tmp_path: Path) -> None:
        cli_dir = _make_llm_dir(tmp_path, "cli")
        env_dir = _make_vlm_dir(tmp_path, "env")
        env = {ENV_MODEL_DIR: str(env_dir), ENV_CAPABILITY: "multimodal-vlm"}
        target = resolve_model_target(
            model_dir=cli_dir, capability="text-llm", env=env
        )
        assert target is not None
        assert target.model_dir == cli_dir
        assert target.capability is Capability.TEXT_LLM

    def test_env_no_speculative_flag(self, tmp_path: Path) -> None:
        d = _make_llm_dir(tmp_path)
        env = {
            ENV_MODEL_DIR: str(d),
            ENV_CAPABILITY: "text-llm",
            ENV_NO_SPECULATIVE: "true",
        }
        target = resolve_model_target(model_dir=None, capability=None, env=env)
        assert target is not None
        assert target.speculative_decode is False

    def test_parse_capability_unknown_raises(self) -> None:
        with pytest.raises(ModelTargetError, match="unknown eval capability"):
            parse_capability("not-a-capability")


# ---------------------------------------------------------------------------
# B. answer_quality generator selection (pipeline dispatch)
# ---------------------------------------------------------------------------


class _FakeInference:
    """Captures the OrchestratorGPUInference construction kwargs."""

    last_kwargs: dict[str, object] = {}

    def __init__(self, **kwargs: object) -> None:
        _FakeInference.last_kwargs = dict(kwargs)

    def load_model(self) -> bool:
        return True

    def generate_text(self, *args: object, **kwargs: object) -> object:  # pragma: no cover
        raise AssertionError("generate_text should not run in this unit test")


@pytest.fixture()
def patched_ao_loader(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Patch the LLM loader + default_model_dir so the generator builds without
    a real model. Returns the default dir it will resolve to."""
    from evals.suites import answer_quality as aq

    default_dir = _make_llm_dir(tmp_path, "default-14b")
    monkeypatch.setattr(aq, "default_model_dir", lambda: default_dir)
    monkeypatch.setattr(
        "services.assistant_orchestrator.src.gpu_inference.OrchestratorGPUInference",
        _FakeInference,
    )
    _FakeInference.last_kwargs = {}
    return default_dir


class TestAnswerQualityGeneratorSelection:
    def test_default_construction_is_byte_identical(
        self, patched_ao_loader: Path
    ) -> None:
        """No target => LLMPipeline loader built with ONLY model_dir=default
        (no speculative override) — byte-identical to the pre-#931 path."""
        from evals.suites import answer_quality as aq

        aq.make_real_ao_generator(target=None)
        assert _FakeInference.last_kwargs == {"model_dir": str(patched_ao_loader)}

    def test_text_llm_override_threads_dir_and_speculative(
        self, patched_ao_loader: Path, tmp_path: Path
    ) -> None:
        from evals.suites import answer_quality as aq

        override = _make_llm_dir(tmp_path, "other-dense")
        target = ModelTarget(
            model_dir=override,
            capability=Capability.TEXT_LLM,
            speculative_decode=False,
        )
        aq.make_real_ao_generator(target=target)
        assert _FakeInference.last_kwargs == {
            "model_dir": str(override),
            "speculative_decoding_enabled": False,
        }

    def test_multimodal_vlm_override_builds_vlm_arm(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from evals.suites import answer_quality as aq

        vlm_dir = _make_vlm_dir(tmp_path)
        sentinel = object()
        recorded: dict[str, object] = {}

        def fake_build(model_dir: Path, **kwargs: object) -> object:
            recorded["model_dir"] = model_dir
            recorded.update(kwargs)
            return sentinel

        monkeypatch.setattr(
            "evals.hardware_pipeline.build_vlm_composed_generator", fake_build
        )
        # _default_system_prompt() imports the real production prompt (SSOT).
        target = ModelTarget(
            model_dir=vlm_dir,
            capability=Capability.MULTIMODAL_VLM,
            speculative_decode=False,
        )
        gen = aq.make_real_ao_generator(target=target)
        assert gen is sentinel
        assert recorded["model_dir"] == vlm_dir
        assert isinstance(recorded["system_prompt"], str)
        assert recorded["system_prompt"]  # the real production system prompt


# ---------------------------------------------------------------------------
# C. hardware_pipeline — the VLMPipeline arm
# ---------------------------------------------------------------------------


class _FakeVLMPipeline:
    last_prompt: str = ""

    def __init__(self, model_dir: str, device: str) -> None:
        self.model_dir = model_dir
        self.device = device

    def generate(self, prompt: str, generation_config: object) -> str:
        _FakeVLMPipeline.last_prompt = prompt
        return "  a grounded answer  "


class _FakeGenConfig:
    def __init__(self) -> None:
        self.max_new_tokens = 0
        self.do_sample = True


def _install_fake_ov_genai(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = types.ModuleType("openvino_genai")
    fake.VLMPipeline = _FakeVLMPipeline  # type: ignore[attr-defined]
    fake.GenerationConfig = _FakeGenConfig  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openvino_genai", fake)


class TestHardwarePipelineVLM:
    def test_vlm_generator_greedy_and_chatml_wrapped(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from evals.hardware_pipeline import build_vlm_composed_generator

        _install_fake_ov_genai(monkeypatch)
        vlm_dir = _make_vlm_dir(tmp_path)
        gen = build_vlm_composed_generator(
            vlm_dir, max_new_tokens=64, system_prompt="SYSTEM-PROMPT"
        )
        out = gen("composed grounded context")
        # str(result) is returned verbatim (the suite strips/scoring is downstream).
        assert out == "  a grounded answer  "
        # System prompt + user content in Qwen ChatML; greedy decode.
        assert "<|im_start|>system\nSYSTEM-PROMPT<|im_end|>" in _FakeVLMPipeline.last_prompt
        assert "composed grounded context" in _FakeVLMPipeline.last_prompt

    def test_vlm_generator_missing_dir_fails_closed(self, tmp_path: Path) -> None:
        from evals.hardware_pipeline import build_vlm_composed_generator

        with pytest.raises(FileNotFoundError, match="VLM model directory not found"):
            build_vlm_composed_generator(
                tmp_path / "absent", max_new_tokens=64, system_prompt="s"
            )

    def test_vlm_generator_no_ov_genai_fails_closed(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from evals.hardware_pipeline import build_vlm_composed_generator

        # Force the import to fail even if openvino_genai is installed.
        monkeypatch.setitem(sys.modules, "openvino_genai", None)
        vlm_dir = _make_vlm_dir(tmp_path)
        with pytest.raises(RuntimeError, match="OpenVINO GenAI is not available"):
            build_vlm_composed_generator(
                vlm_dir, max_new_tokens=64, system_prompt="s"
            )


# ---------------------------------------------------------------------------
# D. Runner CLI (evals.run) — fail-closed exit codes + baseline untouched
# ---------------------------------------------------------------------------


class TestRunnerCliOverride:
    def test_nonexistent_dir_exits_harness_error(self, tmp_path: Path) -> None:
        code = run_mod.main(
            [
                "--suite", "governance",
                "--include-hardware",
                "--model-dir", str(tmp_path / "nope"),
                "--capability", "text-llm",
            ]
        )
        assert code == run_mod.EXIT_HARNESS_ERROR

    def test_override_without_include_hardware_exits_harness_error(
        self, tmp_path: Path
    ) -> None:
        d = _make_llm_dir(tmp_path)
        code = run_mod.main(
            ["--suite", "governance", "--model-dir", str(d), "--capability", "text-llm"]
        )
        assert code == run_mod.EXIT_HARNESS_ERROR

    def test_unknown_capability_via_env_exits_harness_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        d = _make_llm_dir(tmp_path)
        monkeypatch.setenv(ENV_MODEL_DIR, str(d))
        monkeypatch.setenv(ENV_CAPABILITY, "bogus-cap")
        code = run_mod.main(["--suite", "governance", "--include-hardware"])
        assert code == run_mod.EXIT_HARNESS_ERROR

    def test_valid_override_leaves_deterministic_suite_clean(
        self, tmp_path: Path
    ) -> None:
        """A valid override must not disturb a deterministic suite's baseline —
        governance ignores model_target and still compares clean (exit 0)."""
        d = _make_llm_dir(tmp_path)
        code = run_mod.main(
            [
                "--suite", "governance",
                "--include-hardware",
                "--model-dir", str(d),
                "--capability", "text-llm",
            ]
        )
        assert code == run_mod.EXIT_OK

    def test_default_run_still_clean(self) -> None:
        """No override => the standing governance gate is byte-identical clean."""
        assert run_mod.main(["--suite", "governance"]) == run_mod.EXIT_OK


# ---------------------------------------------------------------------------
# E. Suite threading — VLM skip (loud, explained) + default path unchanged
# ---------------------------------------------------------------------------


class TestSuiteThreadingVlmSkip:
    def test_pa_vlm_target_skips_model_cases_loudly(self, tmp_path: Path) -> None:
        from evals.suites import pa_classification as pa
        from evals.types import CaseStatus

        target = ModelTarget(
            model_dir=tmp_path / "vlm",
            capability=Capability.MULTIMODAL_VLM,
            speculative_decode=False,
        )
        report = pa.run_suite(include_hardware=True, model_target=target)
        model_skips = [
            r for r in report.results
            if r.status is CaseStatus.SKIPPED_HARDWARE
            and "multimodal-vlm" in r.detail
        ]
        assert model_skips, "PA model cases must skip (loud) under a VLM target"
        # No case ERRORED (the VLM target must not mis-pipeline the PA path).
        assert not [r for r in report.results if r.status is CaseStatus.ERROR]

    def test_preference_vlm_target_skips_model_cases_loudly(
        self, tmp_path: Path
    ) -> None:
        from evals.suites import preference_memory as pm
        from evals.types import CaseStatus

        target = ModelTarget(
            model_dir=tmp_path / "vlm",
            capability=Capability.MULTIMODAL_VLM,
            speculative_decode=False,
        )
        report = pm.run_suite(include_hardware=True, model_target=target)
        model_skips = [
            r for r in report.results
            if r.status is CaseStatus.SKIPPED_HARDWARE
            and "multimodal-vlm" in r.detail
        ]
        assert model_skips, "preference model cases must skip (loud) under VLM"
        assert not [r for r in report.results if r.status is CaseStatus.ERROR]

    def test_pa_default_none_runs_injected_model_path(self) -> None:
        """model_target=None => the ordinary injected model classifier runs the
        model cases (not skipped) — the default path is unchanged."""
        from evals.suites import pa_classification as pa
        from evals.types import CaseStatus

        def fake_classify(car: dict) -> tuple[str, None]:
            return "ALLOW", None

        report = pa.run_suite(
            include_hardware=True,
            hardware_classifier=fake_classify,
            model_target=None,
        )
        # No model case was hardware-skipped (the injected classifier ran them).
        vlm_skips = [
            r for r in report.results
            if r.status is CaseStatus.SKIPPED_HARDWARE and "multimodal-vlm" in r.detail
        ]
        assert not vlm_skips
