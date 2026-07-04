"""Tests for the UC-010 local image-generation module (ADR-033 — DORMANT).

The heavy diffusion model is never loaded in the unit tier — these tests
manipulate the module globals + config directly to verify the contracts that
matter for a DORMANT ship:

  * ``is_available()`` is False by default (disabled) and stays False when the
    model is absent — the dormancy invariant.
  * ``generate_*`` returns None when unavailable, attempting NO load.
  * ``unload()`` clears the cached pipe + resets the fail flag + is idempotent.
  * a kind-swap unloads the prior pipeline (one diffusion pipeline resident).
  * dimension clamping is a real circuit breaker (over-cap clamps; degenerate
    floors; multiple-of-8 stride).
  * the nested-layout weight manifest verify is fail-closed.

The ``@pytest.mark.hardware`` tier (deselected from the standing gate) exercises
the REAL Arc 140V model at go-live; those tests are skipped without it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import shared.inference.image_gen as ig


@pytest.fixture(autouse=True)
def _reset_module_state():
    """Reset image_gen globals + config around every test (no cross-test bleed)."""
    ig.unload()
    saved = ig.current_config()
    ig.configure(ig.ImageGenConfig())  # DORMANT default
    yield
    ig.unload()
    ig.configure(saved)


# ---------------------------------------------------------------------------
# Dormancy invariant
# ---------------------------------------------------------------------------


def test_is_available_false_when_disabled():
    """The shipped default (enabled=False) ⇒ unavailable, regardless of model."""
    ig.configure(ig.ImageGenConfig(enabled=False))
    assert ig.is_available() is False


def test_is_available_false_when_model_absent(tmp_path: Path):
    """Even enabled, a missing model dir ⇒ unavailable (structural absence)."""
    ig.configure(ig.ImageGenConfig(enabled=True, model_dir=tmp_path / "nope"))
    assert ig.is_available() is False


def test_generate_text2image_returns_none_when_unavailable():
    """A disabled module never loads — generate returns None (Fail-Soft)."""
    ig.configure(ig.ImageGenConfig(enabled=False))
    assert ig.generate_text2image("a red cube") is None
    # And no pipeline was loaded.
    assert ig._pipe is None


def test_generate_image2image_returns_none_when_unavailable():
    ig.configure(ig.ImageGenConfig(enabled=False))
    assert ig.generate_image2image(b"\x89PNG\r\n\x1a\n", "make it blue") is None
    assert ig._pipe is None


def test_empty_prompt_returns_none_even_if_available(monkeypatch):
    """An empty prompt is a no-op (None) — never a wasted generate."""
    # Force is_available True without a real model by stubbing the gate.
    monkeypatch.setattr(ig, "is_available", lambda: True)
    assert ig.generate_text2image("   ") is None


# ---------------------------------------------------------------------------
# unload() contract (mirrors test_vlm)
# ---------------------------------------------------------------------------


def test_unload_clears_cached_pipe_and_resets_failed(monkeypatch):
    monkeypatch.setattr(ig, "_pipe", object())
    monkeypatch.setattr(ig, "_model_kind", ig.KIND_TEXT2IMAGE)
    monkeypatch.setattr(ig, "_load_failed", True)
    ig.unload()
    assert ig._pipe is None
    assert ig._model_kind is None
    assert ig._load_failed is False


def test_unload_is_idempotent_when_nothing_loaded(monkeypatch):
    monkeypatch.setattr(ig, "_pipe", None)
    monkeypatch.setattr(ig, "_load_failed", False)
    ig.unload()
    ig.unload()
    assert ig._pipe is None
    assert ig._load_failed is False


def test_kind_swap_unloads_prior_pipeline(monkeypatch):
    """Loading a different kind drops the resident pipeline first (one at a time).

    Stubs _verify_weights + a fake ov_genai so no real model loads; asserts the
    prior pipe object is replaced when the requested kind differs.
    """
    monkeypatch.setattr(ig, "is_available", lambda: True)
    monkeypatch.setattr(ig, "_verify_weights", lambda cfg: True)

    class _FakePipe:
        def __init__(self, kind):
            self.kind = kind

    class _FakeGenAI:
        @staticmethod
        def Text2ImagePipeline(path, device, **kw):
            return _FakePipe("t2i")

        @staticmethod
        def Image2ImagePipeline(path, device, **kw):
            return _FakePipe("i2i")

    import sys
    monkeypatch.setitem(sys.modules, "openvino_genai", _FakeGenAI)
    ig.configure(ig.ImageGenConfig(enabled=True, device="CPU"))

    p1 = ig._get_pipe(ig.KIND_TEXT2IMAGE)
    assert p1 is not None and p1.kind == "t2i"
    p2 = ig._get_pipe(ig.KIND_IMAGE2IMAGE)
    assert p2 is not None and p2.kind == "i2i"
    assert p2 is not p1  # the prior pipeline was swapped out


# ---------------------------------------------------------------------------
# Model variant (illustration support — one model resident across variants too)
# ---------------------------------------------------------------------------


def test_config_default_variant_is_photoreal_sdxl():
    """The dataclass default selects the LIVE photoreal SDXL — so a config-less /
    back-compat call is byte-identical to the pre-variant path (dormant illustration
    is opt-in only)."""
    assert ig.ImageGenConfig().model_variant == ig.VARIANT_PHOTOREAL_SDXL


def test_variant_swap_unloads_prior_model(monkeypatch):
    """Re-configuring to a DIFFERENT model variant (same kind) drops the resident
    pipeline first and reloads — one diffusion model resident at a time, across
    variants too (the brochure swap-sequence relies on this)."""
    monkeypatch.setattr(ig, "is_available", lambda: True)
    monkeypatch.setattr(ig, "_verify_weights", lambda cfg: True)

    class _FakePipe:
        def __init__(self):
            pass

    class _FakeGenAI:
        @staticmethod
        def Text2ImagePipeline(path, device, **kw):
            return _FakePipe()

        @staticmethod
        def Image2ImagePipeline(path, device, **kw):
            return _FakePipe()

    import sys
    monkeypatch.setitem(sys.modules, "openvino_genai", _FakeGenAI)

    # Load the photoreal variant (AUTO scheduler keeps _build_scheduler a no-op).
    ig.configure(
        ig.ImageGenConfig(
            enabled=True, device="CPU", scheduler="AUTO",
            model_variant=ig.VARIANT_PHOTOREAL_SDXL,
        )
    )
    p1 = ig._get_pipe(ig.KIND_TEXT2IMAGE)
    assert p1 is not None
    assert ig._model_variant == ig.VARIANT_PHOTOREAL_SDXL

    # Same kind, DIFFERENT variant ⇒ the resident pipe must be swapped out.
    ig.configure(
        ig.ImageGenConfig(
            enabled=True, device="CPU", scheduler="AUTO",
            model_variant=ig.VARIANT_ILLUSTRATION,
        )
    )
    p2 = ig._get_pipe(ig.KIND_TEXT2IMAGE)
    assert p2 is not None
    assert p2 is not p1  # reloaded for the new variant
    assert ig._model_variant == ig.VARIANT_ILLUSTRATION


def test_unload_clears_resident_variant(monkeypatch):
    """unload() resets the resident-variant marker (no stale variant blocks a
    later reload)."""
    monkeypatch.setattr(ig, "_pipe", object())
    monkeypatch.setattr(ig, "_model_kind", ig.KIND_TEXT2IMAGE)
    monkeypatch.setattr(ig, "_model_variant", ig.VARIANT_ILLUSTRATION)
    ig.unload()
    assert ig._model_variant is None


# ---------------------------------------------------------------------------
# Dimension clamping (circuit breaker)
# ---------------------------------------------------------------------------


def test_clamp_dims_caps_oversize():
    cfg = ig.ImageGenConfig(max_width=1024, max_height=1024)
    w, h = ig._clamp_dims(4096, 4096, cfg)
    assert w == 1024 and h == 1024


def test_clamp_dims_floors_degenerate():
    cfg = ig.ImageGenConfig(max_width=1024, max_height=1024)
    w, h = ig._clamp_dims(0, -5, cfg)
    assert w >= ig._MIN_DIM and h >= ig._MIN_DIM


def test_clamp_dims_multiple_of_8():
    cfg = ig.ImageGenConfig(max_width=1024, max_height=1024)
    w, h = ig._clamp_dims(999, 777, cfg)
    assert w % 8 == 0 and h % 8 == 0


# ---------------------------------------------------------------------------
# Weight manifest verify (fail-closed)
# ---------------------------------------------------------------------------


def test_verify_weights_skips_with_warning_when_no_manifest():
    """No manifest configured ⇒ SKIP (a provisioning gap), returns True+WARNING."""
    cfg = ig.ImageGenConfig(weight_manifest=None)
    assert ig._verify_weights(cfg) is True


def test_verify_weights_fails_closed_on_missing_manifest(tmp_path: Path):
    """A configured-but-missing manifest ⇒ fail-closed (False)."""
    cfg = ig.ImageGenConfig(
        model_dir=tmp_path, weight_manifest=tmp_path / "manifest.json"
    )
    assert ig._verify_weights(cfg) is False


def test_verify_weights_fails_closed_on_tampered_weight(tmp_path: Path):
    """A nested .bin whose digest does not match ⇒ fail-closed (False)."""
    import json

    (tmp_path / "unet").mkdir()
    binp = tmp_path / "unet" / "openvino_model.bin"
    binp.write_bytes(b"the real weights")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"version": "1", "digests": {"unet/openvino_model.bin": "0" * 64}}),
        encoding="utf-8",
    )
    cfg = ig.ImageGenConfig(model_dir=tmp_path, weight_manifest=manifest)
    assert ig._verify_weights(cfg) is False


def test_verify_weights_passes_on_matching_manifest(tmp_path: Path):
    import hashlib
    import json

    (tmp_path / "unet").mkdir()
    binp = tmp_path / "unet" / "openvino_model.bin"
    payload = b"the real weights"
    binp.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {"version": "1", "digests": {"unet/openvino_model.bin": digest}}
        ),
        encoding="utf-8",
    )
    cfg = ig.ImageGenConfig(model_dir=tmp_path, weight_manifest=manifest)
    assert ig._verify_weights(cfg) is True


def test_verify_weights_rejects_extra_unlisted_bin(tmp_path: Path):
    """An extra .bin not in the manifest ⇒ fail-closed (swap-and-drop defense)."""
    import hashlib
    import json

    (tmp_path / "unet").mkdir()
    binp = tmp_path / "unet" / "openvino_model.bin"
    payload = b"weights"
    binp.write_bytes(payload)
    # An attacker drops an unlisted sidecar.
    (tmp_path / "unet" / "evil.bin").write_bytes(b"evil")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "version": "1",
                "digests": {
                    "unet/openvino_model.bin": hashlib.sha256(payload).hexdigest()
                },
            }
        ),
        encoding="utf-8",
    )
    cfg = ig.ImageGenConfig(model_dir=tmp_path, weight_manifest=manifest)
    assert ig._verify_weights(cfg) is False


# ---------------------------------------------------------------------------
# Weight manifest verify — WS1 widening (.xml / model_index.json coverage)
# + the require_signed_manifest gate (FUT-04 parity with the 14B)
# ---------------------------------------------------------------------------


# Synthetic TPM-signing stub (no real TPM in CI) — mirrors test_manifest_signer.py.
def _stub_sign(key_name: str, data: bytes) -> bytes:
    import hashlib

    return hashlib.sha256(b"stub-imagegen-key:" + data).digest()


def _stub_verify(key_name: str, data: bytes, signature: bytes) -> bool:
    return signature == _stub_sign(key_name, data)


def _sign_manifest_stub(manifest: Path) -> None:
    import base64

    from shared.models.manifest_signer import MANIFEST_SIGNING_KEY_NAME

    raw = manifest.read_bytes()
    sig = _stub_sign(MANIFEST_SIGNING_KEY_NAME, raw)
    (manifest.parent / (manifest.name + ".sig")).write_bytes(
        base64.urlsafe_b64encode(sig)
    )


def _patch_tpm(monkeypatch) -> None:
    from shared.models import manifest_signer
    from shared.security import tpm_signer

    monkeypatch.setattr(tpm_signer, "verify", _stub_verify)
    monkeypatch.setattr(manifest_signer, "tpm_signer", tpm_signer)


def _stage_full_nested(tmp_path: Path) -> Path:
    """Stage a minimal nested SDXL-shaped model (.bin + .xml + model_index.json)
    with a matching manifest; return the manifest path."""
    import hashlib
    import json

    (tmp_path / "unet").mkdir()
    bin_payload = b"unet weights"
    xml_payload = b"<net>unet topology</net>"
    idx_payload = b'{"_class_name": "StableDiffusionXLPipeline"}'
    (tmp_path / "unet" / "openvino_model.bin").write_bytes(bin_payload)
    (tmp_path / "unet" / "openvino_model.xml").write_bytes(xml_payload)
    (tmp_path / "model_index.json").write_bytes(idx_payload)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "version": "1",
                "digests": {
                    "unet/openvino_model.bin": hashlib.sha256(bin_payload).hexdigest(),
                    "unet/openvino_model.xml": hashlib.sha256(xml_payload).hexdigest(),
                    "model_index.json": hashlib.sha256(idx_payload).hexdigest(),
                },
            }
        ),
        encoding="utf-8",
    )
    return manifest


def test_verify_weights_fails_closed_on_tampered_xml(tmp_path: Path):
    """A nested .xml whose on-disk bytes differ from its manifest digest
    ⇒ _verify_weights False (the compute graph cannot be swapped)."""
    manifest = _stage_full_nested(tmp_path)
    (tmp_path / "unet" / "openvino_model.xml").write_bytes(b"<net>SWAPPED</net>")
    cfg = ig.ImageGenConfig(model_dir=tmp_path, weight_manifest=manifest)
    assert ig._verify_weights(cfg) is False


def test_verify_weights_rejects_extra_unlisted_xml(tmp_path: Path):
    """An on-disk .xml not in the manifest ⇒ _verify_weights False (swap-and-drop
    defense extended to topology files)."""
    import hashlib
    import json

    (tmp_path / "unet").mkdir()
    payload = b"weights"
    (tmp_path / "unet" / "openvino_model.bin").write_bytes(payload)
    # An unlisted .xml the attacker drops in.
    (tmp_path / "unet" / "openvino_model.xml").write_bytes(b"<net>evil</net>")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "version": "1",
                "digests": {
                    "unet/openvino_model.bin": hashlib.sha256(payload).hexdigest()
                },
            }
        ),
        encoding="utf-8",
    )
    cfg = ig.ImageGenConfig(model_dir=tmp_path, weight_manifest=manifest)
    assert ig._verify_weights(cfg) is False


def test_verify_weights_passes_with_full_bin_xml_model_index_manifest(tmp_path: Path):
    """All three kinds listed + matching ⇒ _verify_weights True."""
    manifest = _stage_full_nested(tmp_path)
    cfg = ig.ImageGenConfig(model_dir=tmp_path, weight_manifest=manifest)
    assert ig._verify_weights(cfg) is True


def test_verify_weights_require_signed_refuses_unsigned(tmp_path: Path):
    """require_signed_manifest=True + a correct manifest with NO .sig
    ⇒ _verify_weights False (FAIL-CLOSED — load_manifest_verified short-circuits
    on the absent signature)."""
    manifest = _stage_full_nested(tmp_path)
    assert not (manifest.parent / (manifest.name + ".sig")).exists()
    cfg = ig.ImageGenConfig(
        model_dir=tmp_path, weight_manifest=manifest, require_signed_manifest=True
    )
    assert ig._verify_weights(cfg) is False


def test_verify_weights_require_signed_passes_with_stub_sig(
    tmp_path: Path, monkeypatch
):
    """require_signed_manifest=True + a correct manifest + a valid STUB .sig +
    monkeypatched TPM verify ⇒ _verify_weights True."""
    manifest = _stage_full_nested(tmp_path)
    _sign_manifest_stub(manifest)
    _patch_tpm(monkeypatch)
    cfg = ig.ImageGenConfig(
        model_dir=tmp_path, weight_manifest=manifest, require_signed_manifest=True
    )
    assert ig._verify_weights(cfg) is True


def test_verify_weights_require_signed_true_no_manifest_refuses():
    """require_signed_manifest=True + weight_manifest=None ⇒ _verify_weights
    False — the new fail-closed branch (you cannot sign-verify a manifest that
    does not exist; no SKIP-with-WARNING when signing is required)."""
    cfg = ig.ImageGenConfig(weight_manifest=None, require_signed_manifest=True)
    assert ig._verify_weights(cfg) is False


def test_verify_weights_default_unsigned_still_passes_clean_manifest(tmp_path: Path):
    """require_signed_manifest=False (default) + a correct manifest + no .sig
    ⇒ _verify_weights True — confirms the WS1 changes did not regress the
    dormant-dev unsigned-but-present-manifest path."""
    manifest = _stage_full_nested(tmp_path)
    assert not (manifest.parent / (manifest.name + ".sig")).exists()
    cfg = ig.ImageGenConfig(model_dir=tmp_path, weight_manifest=manifest)
    # Default require_signed_manifest is False.
    assert cfg.require_signed_manifest is False
    assert ig._verify_weights(cfg) is True


# ---------------------------------------------------------------------------
# Step resolution — the 0/None "unspecified" sentinel must use the configured
# default, never floor to a 1-step (noise) run (#666 go-live regression)
# ---------------------------------------------------------------------------


def test_resolve_steps_zero_uses_configured_default():
    """steps=0 (the gateway coordinator / IMAGE_GEN_REQUEST "unspecified"
    sentinel) resolves to the configured default — NOT a 1-step run. This is the
    #666 go-live defect: the request carried steps=0, the old `is not None`
    check honored it, and max(1, 0) floored every generation to ONE denoising
    step => pure noise regardless of [image_generation].steps."""
    cfg = ig.ImageGenConfig(steps=30)
    assert ig._resolve_steps(0, cfg) == 30
    assert ig._resolve_steps(None, cfg) == 30


def test_resolve_steps_positive_override_honored():
    """An explicit positive step count overrides the configured default."""
    assert ig._resolve_steps(8, ig.ImageGenConfig(steps=30)) == 8


def test_resolve_steps_negative_uses_configured_default():
    """A negative step count is treated as unspecified (defensive)."""
    assert ig._resolve_steps(-5, ig.ImageGenConfig(steps=25)) == 25


def test_resolve_steps_never_zero_floors_to_one():
    """Even a degenerate config of 0 floors to at least 1 (never a 0-step call)."""
    assert ig._resolve_steps(0, ig.ImageGenConfig(steps=0)) == 1
    assert ig._resolve_steps(None, ig.ImageGenConfig(steps=0)) == 1


# ---------------------------------------------------------------------------
# Quality knobs — scheduler / guidance_scale / negative prompt (UC-010 #666)
# ---------------------------------------------------------------------------


def test_quality_knob_defaults():
    """The resolved config carries the quality defaults (a better-than-DDIM
    scheduler, a sane CFG, and a QUALITY-only default negative prompt)."""
    cfg = ig.ImageGenConfig()
    assert cfg.scheduler == "EULER_ANCESTRAL_DISCRETE"
    assert cfg.guidance_scale == 7.0
    assert cfg.negative_prompt == ig.DEFAULT_NEGATIVE_PROMPT


def test_default_negative_prompt_is_quality_only_not_a_content_filter():
    """The default negative prompt must steer QUALITY only — it must carry no
    content/subject terms, or it would silently re-censor the deliberately
    uncensored model (ADR-033 §content-safety)."""
    low = ig.DEFAULT_NEGATIVE_PROMPT.lower()
    for banned in ("nsfw", "nude", "naked", "sex", "porn", "explicit", "censored"):
        assert banned not in low


def test_build_scheduler_auto_and_empty_use_model_default():
    """"AUTO"/empty keep the model's own scheduler (returns None, no build)."""
    assert ig._build_scheduler(ig.ImageGenConfig(scheduler="AUTO")) is None
    assert ig._build_scheduler(ig.ImageGenConfig(scheduler="")) is None


def test_build_scheduler_unknown_name_fails_soft(tmp_path: Path):
    """An unknown scheduler name never raises — it degrades to the model default."""
    cfg = ig.ImageGenConfig(scheduler="NOT_A_REAL_SCHEDULER", model_dir=tmp_path)
    assert ig._build_scheduler(cfg) is None


def test_build_scheduler_missing_config_fails_soft(tmp_path: Path):
    """A known type but no scheduler_config.json on disk -> model default (no raise)."""
    cfg = ig.ImageGenConfig(scheduler="EULER_DISCRETE", model_dir=tmp_path)
    assert ig._build_scheduler(cfg) is None


# --- pipeline construction: set_scheduler-before-compile + fail-soft retry ----


class _RecordingPipe:
    """Fake diffusion pipe recording how it was constructed/compiled."""

    def __init__(self, *args, **kwargs):
        self.ctor_args = args
        self.ctor_kwargs = kwargs
        self.scheduler_set = "UNSET"
        self.compiled = None

    def set_scheduler(self, scheduler):
        self.scheduler_set = scheduler

    def compile(self, device, **props):
        self.compiled = (device, props)


def test_construct_pipe_with_scheduler_sets_then_compiles():
    """A custom scheduler is installed via set_scheduler on an UNCOMPILED pipe,
    THEN compiled to the device — NEVER passed as a ctor property (#666: passing
    scheduler= to the ctor raised 'isn't supported for argument scheduler')."""
    cfg = ig.ImageGenConfig(model_dir=Path("M"), device="GPU")
    sentinel = object()
    pipe = ig._construct_pipe(
        _RecordingPipe, cfg, {"PERFORMANCE_HINT": "LATENCY"}, sentinel
    )
    assert pipe.ctor_args == ("M",)  # path-only construct (uncompiled)
    assert pipe.scheduler_set is sentinel  # scheduler installed before compile
    assert pipe.compiled == ("GPU", {"PERFORMANCE_HINT": "LATENCY"})


def test_construct_pipe_without_scheduler_uses_combined_ctor():
    """No scheduler -> the combined construct+compile ctor (path, device, **props)."""
    cfg = ig.ImageGenConfig(model_dir=Path("M"), device="GPU")
    pipe = ig._construct_pipe(_RecordingPipe, cfg, {"X": 1}, None)
    assert pipe.ctor_args == ("M", "GPU")
    assert pipe.ctor_kwargs == {"X": 1}
    assert pipe.scheduler_set == "UNSET"  # scheduler never touched


def test_construct_pipe_failure_returns_none():
    """Any construction error returns None (Fail-Soft) so the caller can degrade."""
    cfg = ig.ImageGenConfig(model_dir=Path("M"), device="GPU")

    def boom(*a, **k):
        raise RuntimeError("nope")

    assert ig._construct_pipe(boom, cfg, {}, None) is None


def test_build_adapter_config_none_without_path():
    """#703: no lora_adapter_path -> no adapter (flat-vector + photoreal styles)."""
    assert ig._build_adapter_config(ig.ImageGenConfig()) is None


def test_build_adapter_config_missing_file_fail_soft(tmp_path):
    """#703: a configured-but-ABSENT LoRA fail-softs to NO adapter (never crashes)."""
    cfg = ig.ImageGenConfig(lora_adapter_path=tmp_path / "nope.safetensors")
    assert ig._build_adapter_config(cfg) is None


def test_build_adapter_config_sha_mismatch_refuses(tmp_path):
    """#703: a SHA-256 integrity-pin mismatch REFUSES the adapter (fail-soft to
    None — a tampered style file is never applied)."""
    lora = tmp_path / "lora.safetensors"
    lora.write_bytes(b"not a real lora")
    cfg = ig.ImageGenConfig(lora_adapter_path=lora, lora_adapter_sha256="0" * 64)
    assert ig._build_adapter_config(cfg) is None


def test_build_adapter_config_unpinned_under_signed_manifest_refuses(tmp_path):
    """#703 hardening (review MINOR #1): under require_signed_manifest a LoRA path
    with NO sha256 pin is REFUSED (fail-soft to None). The adapter is the one weight
    outside signed-manifest coverage, so its pin is mandatory and cannot be silently
    switched off by leaving it empty."""
    lora = tmp_path / "lora.safetensors"
    lora.write_bytes(b"present but unpinned")
    cfg = ig.ImageGenConfig(
        lora_adapter_path=lora,
        lora_adapter_sha256="",
        require_signed_manifest=True,
    )
    assert ig._build_adapter_config(cfg) is None


def test_build_adapter_config_unpinned_without_signed_manifest_reaches_build(
    tmp_path, monkeypatch
):
    """#703 (review MINOR #1, inverse): with require_signed_manifest=False the
    mandatory-pin guard does NOT fire — an unpinned LoRA proceeds to the adapter
    build (proven by the openvino_genai import being attempted), then fail-softs to
    None only because ov_genai is unavailable in the test. Guards against the fix
    over-restricting the non-signed path."""
    import builtins

    lora = tmp_path / "lora.safetensors"
    lora.write_bytes(b"present but unpinned")
    cfg = ig.ImageGenConfig(
        lora_adapter_path=lora,
        lora_adapter_sha256="",
        require_signed_manifest=False,
    )
    reached = {"build": False}
    real_import = builtins.__import__

    def _spy(name, *a, **k):
        if name == "openvino_genai":
            reached["build"] = True
            raise RuntimeError("no ov_genai in test")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _spy)
    assert ig._build_adapter_config(cfg) is None  # fail-soft (no ov_genai)
    assert reached["build"] is True  # mandatory-pin guard did NOT short-circuit


def test_get_pipe_falls_back_to_default_scheduler_on_failure(monkeypatch):
    """A custom scheduler that breaks construction must NOT break generation —
    _get_pipe retries once with the model-default scheduler and still loads
    (#666: the Scheduler ctor-kwarg break left every generate fail-soft)."""
    pytest.importorskip("openvino_genai")
    ig.configure(ig.ImageGenConfig(enabled=True, scheduler="EULER_DISCRETE"))
    monkeypatch.setattr(ig, "is_available", lambda: True)
    monkeypatch.setattr(ig, "_verify_weights", lambda cfg: True)
    monkeypatch.setattr(ig, "_build_scheduler", lambda cfg: object())  # non-None
    calls = []
    sentinel_pipe = object()

    def fake_construct(ctor, cfg, props, scheduler, adapters=None):
        calls.append(scheduler)
        return None if scheduler is not None else sentinel_pipe

    monkeypatch.setattr(ig, "_construct_pipe", fake_construct)
    out = ig._get_pipe(ig.KIND_TEXT2IMAGE)
    assert out is sentinel_pipe
    assert len(calls) == 2  # first WITH the scheduler (fails), then default (ok)
    assert calls[0] is not None and calls[1] is None


class _FakeTensor:
    """Minimal stand-in for an OpenVINO image Tensor (carries a .data ndarray)."""

    def __init__(self, arr):
        self.data = arr


class _CapturePipe:
    """A stand-in diffusion pipe that records the generate kwargs and returns a
    tiny valid NHWC uint8 tensor (so _tensor_to_png_bytes yields real PNG bytes)."""

    def __init__(self):
        self.kwargs: dict | None = None

    def generate(self, prompt, **kwargs):
        import numpy as np

        self.kwargs = kwargs
        return _FakeTensor(np.zeros((1, 8, 8, 3), dtype=np.uint8))


def _install_fake_pipe(monkeypatch, kind: str) -> "_CapturePipe":
    pipe = _CapturePipe()
    monkeypatch.setattr(ig, "is_available", lambda: True)
    monkeypatch.setattr(ig, "_get_pipe", lambda k: pipe)
    ig._pipe = pipe
    ig._model_kind = kind
    return pipe


def test_text2image_passes_guidance_and_default_negative(monkeypatch):
    """generate_text2image forwards the configured guidance_scale and applies the
    configured default negative prompt when the caller passes none (#666)."""
    pytest.importorskip("openvino_genai")
    ig.configure(
        ig.ImageGenConfig(
            enabled=True, guidance_scale=6.5, steps=20,
            negative_prompt="ugly, blurry",
        )
    )
    pipe = _install_fake_pipe(monkeypatch, ig.KIND_TEXT2IMAGE)
    out = ig.generate_text2image("a cat", width=64, height=64)
    assert out is not None and out[:8] == b"\x89PNG\r\n\x1a\n"
    assert pipe.kwargs["guidance_scale"] == 6.5
    assert pipe.kwargs["negative_prompt"] == "ugly, blurry"
    assert pipe.kwargs["num_inference_steps"] == 20


def test_explicit_negative_prompt_overrides_config(monkeypatch):
    """An explicit per-call negative_prompt wins over the configured default."""
    pytest.importorskip("openvino_genai")
    ig.configure(ig.ImageGenConfig(enabled=True, negative_prompt="ugly"))
    pipe = _install_fake_pipe(monkeypatch, ig.KIND_TEXT2IMAGE)
    ig.generate_text2image(
        "a cat", width=64, height=64, negative_prompt="text, watermark"
    )
    assert pipe.kwargs["negative_prompt"] == "text, watermark"


# ---------------------------------------------------------------------------
# Hires-fix: upscale + low-strength img2img refine (UC-010 #666)
# ---------------------------------------------------------------------------


def _png_bytes(w: int, h: int) -> bytes:
    import io as _io

    from PIL import Image

    buf = _io.BytesIO()
    Image.new("RGB", (w, h), (128, 64, 32)).save(buf, format="PNG")
    return buf.getvalue()


def test_hires_defaults_off_with_sane_params():
    """Config-less default: hires OFF (safety), standard factor/strength, and a
    memory-bounded edge cap."""
    cfg = ig.ImageGenConfig()
    assert cfg.hires_enabled is False
    assert cfg.hires_factor == 1.5
    assert cfg.hires_strength == 0.4
    assert cfg.hires_max_edge == 1536


def test_clamp_dims_max_edge_override():
    """max_w/max_h override the config caps (the hires refine exceeds max_width)."""
    cfg = ig.ImageGenConfig(max_width=1024, max_height=1024)
    assert ig._clamp_dims(1536, 1536, cfg) == (1024, 1024)  # no override -> capped
    assert ig._clamp_dims(1536, 1536, cfg, max_w=1536, max_h=1536) == (1536, 1536)


def test_upscale_png_scales_to_factor_multiple_of_8():
    import io as _io

    from PIL import Image

    out = ig._upscale_png(_png_bytes(512, 512), factor=1.5, max_edge=1536)
    assert out is not None
    assert Image.open(_io.BytesIO(out)).size == (768, 768)  # 512*1.5, mult of 8


def test_upscale_png_respects_max_edge_cap():
    import io as _io

    from PIL import Image

    out = ig._upscale_png(_png_bytes(1024, 1024), factor=2.0, max_edge=1536)
    assert out is not None
    assert max(Image.open(_io.BytesIO(out)).size) <= 1536  # capped, not 2048


def test_upscale_png_bad_bytes_fails_soft():
    assert ig._upscale_png(b"not a png", factor=1.5, max_edge=1536) is None


def test_hires_refine_calls_i2i_with_raised_cap(monkeypatch):
    """_hires_refine upscales, then calls generate_image2image at the hires
    strength with the dimension cap raised to hires_max_edge."""
    captured: dict = {}

    def fake_i2i(
        image_bytes, prompt, *, strength, steps, seed, negative_prompt, max_edge
    ):
        captured.update(
            strength=strength, steps=steps, seed=seed,
            negative_prompt=negative_prompt, max_edge=max_edge,
        )
        return b"\x89PNG\r\n\x1a\nREFINED"

    monkeypatch.setattr(ig, "generate_image2image", fake_i2i)
    cfg = ig.ImageGenConfig(
        hires_factor=1.5, hires_strength=0.35, hires_max_edge=1536, steps=22
    )
    out = ig._hires_refine(_png_bytes(512, 512), "a cat", cfg, "neg", 7)
    assert out == b"\x89PNG\r\n\x1a\nREFINED"
    assert captured["strength"] == 0.35
    assert captured["steps"] == 22
    assert captured["seed"] == 7
    assert captured["negative_prompt"] == "neg"
    assert captured["max_edge"] == 1536


def test_hires_refine_upscale_failure_returns_none(monkeypatch):
    """An upscale failure returns None (the caller keeps the base image)."""
    monkeypatch.setattr(ig, "generate_image2image", lambda *a, **k: b"REFINED")
    assert ig._hires_refine(b"not a png", "p", ig.ImageGenConfig(), "", None) is None


def test_text2image_hires_enabled_returns_refined(monkeypatch):
    """With hires_enabled, generate_text2image returns the refined image."""
    pytest.importorskip("openvino_genai")
    ig.configure(ig.ImageGenConfig(enabled=True, hires_enabled=True))
    _install_fake_pipe(monkeypatch, ig.KIND_TEXT2IMAGE)
    monkeypatch.setattr(
        ig, "_hires_refine",
        lambda base, prompt, cfg, neg, seed: b"\x89PNG\r\n\x1a\nHIRES",
    )
    out = ig.generate_text2image("a cat", width=64, height=64)
    assert out == b"\x89PNG\r\n\x1a\nHIRES"


def test_text2image_hires_failure_falls_back_to_base(monkeypatch):
    """If the hires refine returns None, the BASE image is returned (fail-soft) —
    a hires problem (incl. GPU-OOM at higher res) never loses the generation."""
    pytest.importorskip("openvino_genai")
    ig.configure(ig.ImageGenConfig(enabled=True, hires_enabled=True))
    _install_fake_pipe(monkeypatch, ig.KIND_TEXT2IMAGE)
    monkeypatch.setattr(ig, "_hires_refine", lambda *a, **k: None)
    out = ig.generate_text2image("a cat", width=64, height=64)
    assert out is not None and out[:8] == b"\x89PNG\r\n\x1a\n"  # the base PNG


# ---------------------------------------------------------------------------
# Hardware tier (deselected from the standing gate; runs at go-live)
# ---------------------------------------------------------------------------


@pytest.mark.hardware
def test_text2image_produces_png():
    """REAL Arc 140V text→image produces decodable PNG bytes (go-live verify)."""
    md = Path(
        "C:/Users/mrbla/blarai/models/sdxl-uncensored/openvino-int8-gpu"
    )
    if not (md / "model_index.json").exists():
        pytest.skip("uncensored SDXL model not provisioned")
    ig.configure(
        ig.ImageGenConfig(
            enabled=True, model_dir=md, weight_manifest=md / "manifest.json",
            steps=6, max_width=1024, max_height=1024,
        )
    )
    assert ig.is_available()
    try:
        png = ig.generate_text2image("a red cube on a white table", width=768, height=768)
        assert png is not None and png[:8] == b"\x89PNG\r\n\x1a\n"
    finally:
        ig.unload()


@pytest.mark.hardware
def test_image2image_roundtrip():
    """REAL Arc 140V image+text→image conditions on a seed image (go-live verify)."""
    import io

    from PIL import Image

    md = Path(
        "C:/Users/mrbla/blarai/models/sdxl-uncensored/openvino-int8-gpu"
    )
    if not (md / "model_index.json").exists():
        pytest.skip("uncensored SDXL model not provisioned")
    ig.configure(
        ig.ImageGenConfig(
            enabled=True, model_dir=md, weight_manifest=md / "manifest.json",
            steps=6,
        )
    )
    buf = io.BytesIO()
    Image.new("RGB", (512, 512), (200, 50, 50)).save(buf, format="PNG")
    try:
        png = ig.generate_image2image(buf.getvalue(), "make it blue", strength=0.6)
        assert png is not None and png[:8] == b"\x89PNG\r\n\x1a\n"
    finally:
        ig.unload()
