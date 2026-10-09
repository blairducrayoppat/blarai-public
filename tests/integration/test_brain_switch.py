"""
The brain switch: layout detection, the draft contract, and fail-closed boot (#930)
===================================================================================
The resident brain was the Qwen3-14B and nothing else could load, for reasons
that had nothing to do with the trust spine: ``build_shared_pipeline`` demanded
``openvino_model.xml`` + ``.bin`` for BOTH target and draft. A natively
multimodal export (Qwen3.6-35B-A3B, Gemma 4) has neither of those filenames and
no compatible draft at all, so boot refused it before any security check ran.

These locks cover the three properties that make the switch safe to ship
DORMANT, and each is written to fail if the property is quietly dropped:

1. **The layout decides the pipeline class, and it is read from the FILES.**
   Config cannot talk the builder into the wrong class.
2. **The draft contract is enforced per layout, never defaulted.** A text brain
   without a draft is a REFUSAL (ADR-012 §3.1: autoregressive solo is ~2-3
   tok/s on the 14B) — never a silent 8x slowdown. A draft handed to a
   multimodal brain is IGNORED, and saying so out loud matters because an
   operator who believes speculative decoding is on is wrong about the speed
   contract.
3. **A set-but-missing override refuses to boot**, rather than falling back to
   the 14B. Falling back silently means an operator asked for a different brain
   and never learns it did not happen — the exact class of confusion this
   ticket exists to end.

No GPU and no weights: layout detection is a filesystem question, and the
builder's refusals all happen before any pipeline is constructed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shared.inference.shared_pipeline import (
    LLM_PRIMARY_BIN,
    LLM_PRIMARY_XML,
    VLM_PRIMARY_XML,
    BrainLayout,
    build_shared_pipeline,
    detect_brain_layout,
)


def _make_text_llm(root: Path, name: str = "qwen3-14b") -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / LLM_PRIMARY_XML).write_text("<net/>", encoding="utf-8")
    (d / LLM_PRIMARY_BIN).write_bytes(b"\x00" * 16)
    return d


def _make_multimodal(root: Path, name: str = "qwen3.6-35b-a3b") -> Path:
    """The real 35B shape: a language tower and NO ``openvino_model.*``."""
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / VLM_PRIMARY_XML).write_text("<net/>", encoding="utf-8")
    (d / "openvino_language_model.bin").write_bytes(b"\x00" * 16)
    (d / "openvino_vision_embeddings_model.bin").write_bytes(b"\x00" * 16)
    return d


class TestLayoutIsReadFromTheFiles:
    def test_text_llm_layout(self, tmp_path: Path) -> None:
        assert detect_brain_layout(_make_text_llm(tmp_path)) is BrainLayout.TEXT_LLM

    def test_multimodal_layout(self, tmp_path: Path) -> None:
        assert (
            detect_brain_layout(_make_multimodal(tmp_path))
            is BrainLayout.MULTIMODAL_VLM
        )

    def test_multimodal_wins_when_both_are_present(self, tmp_path: Path) -> None:
        """A directory carrying both names is multimodal: the language-tower
        file is the one VLMPipeline needs, and guessing the other way would
        hand a multimodal export to a pipeline class that cannot serve it."""
        d = _make_multimodal(tmp_path, "both")
        (d / LLM_PRIMARY_XML).write_text("<net/>", encoding="utf-8")
        (d / LLM_PRIMARY_BIN).write_bytes(b"\x00" * 16)
        assert detect_brain_layout(d) is BrainLayout.MULTIMODAL_VLM

    def test_unrecognised_returns_none_rather_than_guessing(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        assert detect_brain_layout(empty) is None
        assert detect_brain_layout(tmp_path / "does-not-exist") is None

    def test_xml_without_bin_is_not_a_text_llm(self, tmp_path: Path) -> None:
        """Half a text export is not a text export — the .bin is the weights."""
        d = tmp_path / "half"
        d.mkdir()
        (d / LLM_PRIMARY_XML).write_text("<net/>", encoding="utf-8")
        assert detect_brain_layout(d) is None


class TestTheDraftContractIsEnforcedPerLayout:
    def test_text_brain_without_a_draft_REFUSES(self, tmp_path: Path) -> None:
        """ADR-012 §3.1 — speculative decoding is mandatory on this path.
        A missing draft must be a refusal, never a silent 8x slowdown."""
        result = build_shared_pipeline(
            model_dir=_make_text_llm(tmp_path),
            draft_model_dir=None,
            enable_prefix_caching=True,
        )
        assert not result.ok
        assert result.pipeline is None
        assert "draft" in (result.error or "").lower()

    def test_text_brain_with_a_missing_draft_dir_refuses(self, tmp_path: Path) -> None:
        result = build_shared_pipeline(
            model_dir=_make_text_llm(tmp_path),
            draft_model_dir=tmp_path / "absent-draft",
            enable_prefix_caching=True,
        )
        assert not result.ok
        assert "Draft model files missing" in (result.error or "")

    def test_unrecognised_target_refuses_and_names_both_shapes(
        self, tmp_path: Path
    ) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        result = build_shared_pipeline(
            model_dir=empty,
            draft_model_dir=None,
            enable_prefix_caching=True,
        )
        assert not result.ok
        error = result.error or ""
        # The message must tell an operator WHICH filenames were looked for.
        assert LLM_PRIMARY_XML in error and VLM_PRIMARY_XML in error

    def test_multimodal_brain_needs_no_draft_to_get_past_the_gate(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The draft gate must not fire for a multimodal brain.

        The build still fails here — there are no real weights to compile — but
        it must fail at CONSTRUCTION, not at the draft check. Asserting on the
        error text is the point: a regression that reinstates the draft
        requirement would change it back.
        """
        result = build_shared_pipeline(
            model_dir=_make_multimodal(tmp_path),
            draft_model_dir=None,
            enable_prefix_caching=True,
        )
        assert not result.ok
        error = (result.error or "").lower()
        assert "draft" not in error, (
            "a multimodal brain must never be refused for lacking a draft; "
            f"got: {result.error}"
        )

    def test_a_draft_handed_to_a_multimodal_brain_is_reported_not_silent(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """VLMPipeline has no speculative decoding. Ignoring the draft quietly
        would leave an operator wrong about the system's speed contract."""
        with caplog.at_level("WARNING"):
            build_shared_pipeline(
                model_dir=_make_multimodal(tmp_path),
                draft_model_dir=_make_text_llm(tmp_path, "draft"),
                enable_prefix_caching=True,
            )
        assert any(
            "IGNORED" in rec.message or "ignored" in rec.message.lower()
            for rec in caplog.records
        ), "the ignored draft must be logged, not swallowed"


class TestTheSwitchIsDormantAndFailsClosed:
    def test_unset_override_returns_none(self) -> None:
        """Empty config = the compiled-in 14B = byte-identical boot."""
        import launcher.__main__ as launcher_main

        assert (
            launcher_main._resolve_brain_override(launcher_main.DeploymentMode.HOST)
            is None
        )

    def test_set_but_missing_directory_raises_rather_than_falling_back(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The one case that must NOT fail soft.

        Every other read error here falls back to the 14B on purpose, because a
        malformed optional knob must not brick boot. But a path the operator
        explicitly set and that does not exist is a deliberate action that did
        not take effect — and booting the wrong brain silently is the failure
        this whole ticket is about.
        """
        import launcher.__main__ as launcher_main

        config = tmp_path / "default.toml"
        config.write_text(
            '[gpu]\nbrain_model_dir = "models/does-not-exist-anywhere"\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(
            launcher_main, "resolve_service_root", lambda *_a, **_k: tmp_path
        )
        monkeypatch.setattr(
            launcher_main, "resolve_service_config_path", lambda *_a, **_k: config
        )
        with pytest.raises(FileNotFoundError, match="does not exist"):
            launcher_main._resolve_brain_override(launcher_main.DeploymentMode.HOST)

    def test_set_and_present_directory_is_returned_with_its_manifest(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import launcher.__main__ as launcher_main

        brain = _make_multimodal(tmp_path, "a-real-brain")
        config = tmp_path / "default.toml"
        config.write_text(
            f'[gpu]\nbrain_model_dir = "{brain.as_posix()}"\n', encoding="utf-8"
        )
        monkeypatch.setattr(
            launcher_main, "resolve_service_root", lambda *_a, **_k: tmp_path
        )
        monkeypatch.setattr(
            launcher_main, "resolve_service_config_path", lambda *_a, **_k: config
        )
        resolved = launcher_main._resolve_brain_override(
            launcher_main.DeploymentMode.HOST
        )
        assert resolved is not None
        model_dir, manifest = resolved
        assert model_dir == brain
        assert manifest == brain / "manifest.json"


class TestMultiFileIntegrityIsSignatureChecked:
    def test_flat_sweep_accepts_require_signed(self) -> None:
        """The multimodal brain's integrity rests on this sweep ALONE.

        Without a ``require_signed`` parameter it would be digest-checked but
        not signature-checked — quietly weaker than the single-file path beside
        it, which has taken that argument all along.
        """
        import inspect

        from shared.models.weight_integrity import verify_all_manifest_entries

        params = inspect.signature(verify_all_manifest_entries).parameters
        assert "require_signed" in params
        assert params["require_signed"].default is False, (
            "the default must stay False so every existing flat caller is "
            "byte-identical; the multimodal path passes True explicitly"
        )

    def test_missing_manifest_fails_closed_when_signed_is_required(
        self, tmp_path: Path
    ) -> None:
        from shared.models.weight_integrity import verify_all_manifest_entries

        d = _make_multimodal(tmp_path, "unsigned")
        result = verify_all_manifest_entries(
            d, d / "manifest.json", require_signed=True
        )
        assert result.all_verified is False
