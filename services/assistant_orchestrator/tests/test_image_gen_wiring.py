"""
Wiring + dormancy locks for UC-010 image generation (ADR-033).

Covers the AO-side seams that make the capability real-but-dormant:
  * the IMAGE_GEN_REQUEST / IMAGE_GEN_RESULT IPC round-trip + the encode-time
    mode validation (fail-closed at encode).
  * ``generate_image`` is in tools._REGISTRY, mirrors the PGOV allowlist, and is
    declared RiskTier.GUARDED.
  * the in-loop ``generate_image`` shim never raises and returns the dormant
    "unavailable" notice when image generation is off (the shipped default).
  * the Policy Agent ALLOWs a local ``tool:generate_image`` dispatch with NO
    adjudication-logic change (the deterministic checker returns None=ALLOW).
  * the [image_generation] config resolves dormant by default + is validated.

No diffusion model is loaded.
"""

from __future__ import annotations

import pytest

from shared.ipc.protocol import MessageFramer, MessageType


# ---------------------------------------------------------------------------
# IPC protocol round-trip
# ---------------------------------------------------------------------------


def test_image_gen_request_round_trip():
    f = MessageFramer()
    msg = f.encode_image_gen_request(
        session_id="s1", mode="text2image", prompt="a red cube",
        width=512, height=512, request_id="r1",
    )
    mt, rid, payload = f.decode(msg)
    assert mt == MessageType.IMAGE_GEN_REQUEST
    assert rid == "r1"
    assert payload["mode"] == "text2image"
    assert payload["prompt"] == "a red cube"
    assert payload["width"] == 512


def test_image_gen_request_invalid_mode_refused_at_encode():
    f = MessageFramer()
    with pytest.raises(ValueError):
        f.encode_image_gen_request(session_id="s1", mode="evil", prompt="x")


def test_image_gen_request_style_in_payload():
    """#703: the style rides the IMAGE_GEN_REQUEST payload; omitting it defaults
    to photoreal (back-compat with the pre-#703 frame)."""
    f = MessageFramer()
    _mt, _rid, payload = f.decode(
        f.encode_image_gen_request(
            session_id="s1", mode="text2image", prompt="x",
            style=MessageFramer.IMAGE_GEN_STYLE_CARTOON,
        )
    )
    assert payload["style"] == "cartoon"
    _m2, _r2, p2 = f.decode(
        f.encode_image_gen_request(session_id="s1", mode="text2image", prompt="x")
    )
    assert p2["style"] == MessageFramer.IMAGE_GEN_STYLE_PHOTOREAL


def test_image_gen_request_invalid_style_refused_at_encode():
    """#703: an unknown style is rejected fail-closed at encode (never crosses IPC)."""
    f = MessageFramer()
    with pytest.raises(ValueError):
        f.encode_image_gen_request(
            session_id="s1", mode="text2image", prompt="x", style="evil",
        )


def test_image_gen_result_round_trip():
    f = MessageFramer()
    msg = f.encode_image_gen_result(
        ok=True, image_ref="blarai-img://" + "a" * 32, mime="image/png",
        request_id="r1",
    )
    d = f.decode_image_gen_result(msg)
    assert d["ok"] is True
    assert d["image_ref"] == "blarai-img://" + "a" * 32
    assert d["mime"] == "image/png"


def test_image_gen_result_failure_carries_labels_only():
    f = MessageFramer()
    msg = f.encode_image_gen_result(
        ok=False, error_code="IMAGE_GEN_UNAVAILABLE",
        message="Image generation is unavailable.",
    )
    d = f.decode_image_gen_result(msg)
    assert d["ok"] is False
    assert d["error_code"] == "IMAGE_GEN_UNAVAILABLE"
    assert d["image_ref"] == ""


# ---------------------------------------------------------------------------
# Generated-image management IPC round-trip (UC-010 Phase 1, #667)
# ---------------------------------------------------------------------------


def test_image_list_request_round_trip():
    f = MessageFramer()
    msg = f.encode_image_list_request(session_id="s1", request_id="r1")
    mt, rid, payload = f.decode(msg)
    assert mt == MessageType.IMAGE_LIST_REQUEST
    assert rid == "r1"
    assert payload["session_id"] == "s1"


def test_image_list_response_metadata_only_round_trip():
    f = MessageFramer()
    rec = {
        "image_id": "a" * 32, "session_id": "s1", "mime": "image/png",
        "byte_size": 1234, "saved": True, "created_at": "2026-06-17T01:02:03+00:00",
    }
    msg = f.encode_image_list_response(images=[rec], total=5, truncated=True, request_id="r1")
    d = f.decode_image_list_response(msg)
    assert d["total"] == 5
    assert d["truncated"] is True
    assert len(d["images"]) == 1
    got = d["images"][0]
    assert got["image_id"] == "a" * 32
    assert got["byte_size"] == 1234
    assert got["saved"] is True
    # METADATA ONLY: the wire record carries EXACTLY the pinned keys — no prompt,
    # no data could ever ride this frame (encode normalises to the key set).
    assert set(got.keys()) == set(MessageFramer.IMAGE_LIST_KEYS)


def test_image_list_response_drops_stray_content_keys():
    """An accidental prompt/data key on a list record is DROPPED at encode — the
    list frame cannot carry decrypted content by construction."""
    f = MessageFramer()
    rec = {
        "image_id": "b" * 32, "session_id": "s", "mime": "image/png",
        "byte_size": 1, "saved": False, "created_at": "t",
        "prompt": "SECRET-PROMPT", "data": "SECRET-BYTES",  # must NOT survive
    }
    msg = f.encode_image_list_response(images=[rec], total=1, request_id="r")
    # The encoded envelope bytes must not contain the smuggled content.
    assert b"SECRET-PROMPT" not in msg
    assert b"SECRET-BYTES" not in msg
    d = f.decode_image_list_response(msg)
    assert "prompt" not in d["images"][0]
    assert "data" not in d["images"][0]


def test_image_manage_request_round_trip():
    f = MessageFramer()
    for action in ("delete", "mark_saved"):
        msg = f.encode_image_manage_request(action=action, image_id="c" * 32, request_id="r2")
        mt, rid, payload = f.decode(msg)
        assert mt == MessageType.IMAGE_MANAGE_REQUEST
        assert payload["action"] == action
        assert payload["image_id"] == "c" * 32


def test_image_manage_request_invalid_action_refused_at_encode():
    f = MessageFramer()
    with pytest.raises(ValueError):
        f.encode_image_manage_request(action="wipe_everything", image_id="x")


def test_image_manage_result_round_trip():
    f = MessageFramer()
    msg = f.encode_image_manage_result(
        ok=True, action="delete", image_id="d" * 32, found=True, request_id="r3",
    )
    d = f.decode_image_manage_result(msg)
    assert d["ok"] is True
    assert d["action"] == "delete"
    assert d["image_id"] == "d" * 32
    assert d["found"] is True


def test_image_manage_result_unknown_id_is_ok_not_found():
    """A delete/mark of an unknown id is ok=True, found=false (idempotent no-op)."""
    f = MessageFramer()
    msg = f.encode_image_manage_result(
        ok=True, action="delete", image_id="e" * 32, found=False,
    )
    d = f.decode_image_manage_result(msg)
    assert d["ok"] is True
    assert d["found"] is False
    assert d["error_code"] == ""


# ---------------------------------------------------------------------------
# Tool registration (GUARDED; registry == allowlist; PA allows)
# ---------------------------------------------------------------------------


def test_generate_image_registered_and_allowlisted():
    from services.assistant_orchestrator.src import tools
    from services.assistant_orchestrator.src.pgov import TOOL_CALL_ALLOWLIST

    assert "generate_image" in tools._REGISTRY
    assert "generate_image" in TOOL_CALL_ALLOWLIST
    # The audit Domain-5 invariant: the allowlist mirrors the registry exactly.
    assert set(tools._REGISTRY) == set(TOOL_CALL_ALLOWLIST)


def test_generate_image_is_guarded_tier():
    from services.assistant_orchestrator.src import tools

    assert tools.risk_tier("generate_image") == tools.RiskTier.GUARDED


def test_generate_image_shim_never_raises_and_is_dormant():
    """The in-loop shim returns the dormant notice (image gen off by default)
    and never raises (the _calculate contract)."""
    from services.assistant_orchestrator.src import tools

    out = tools.execute("generate_image", "a red cube")
    assert isinstance(out, str)
    assert "unavailable" in out.lower()


def test_policy_agent_allows_local_generate_image_dispatch():
    """A local tool:generate_image CAR matches no deny rule → ALLOW (None),
    proving NO PA adjudication-logic change is needed."""
    from services.policy_agent.src.car import build_car
    from services.policy_agent.src.gpu_inference import DeterministicPolicyChecker
    from shared.schemas.car import ActionVerb, Sensitivity

    car = build_car(
        source_agent="assistant_orchestrator",
        destination_service="assistant_orchestrator",
        verb=ActionVerb.EXECUTE,
        resource="tool:generate_image",
        sensitivity=Sensitivity.INTERNAL,
        parameters_schema={},
        session_id="s1",
    )
    assert DeterministicPolicyChecker.check(car) is None  # None == ALLOW


# ---------------------------------------------------------------------------
# Config dormancy
# ---------------------------------------------------------------------------


def test_image_gen_config_live_with_signed_manifest_required():
    """Post go-live (#666): the shipped default.toml resolves [image_generation]
    enabled=TRUE — the capability is LIVE — while require_signed_manifest stays
    TRUE, so the diffusion model still refuses to load without a valid TPM-signed
    weight manifest (the at-load weight-integrity gate that survives go-live).

    Pre-go-live this asserted enabled=False/dormant; the operator ran the go-live
    ceremony (staged + TPM-signed the SDXL manifest, recorded the one-time content
    attestation, verified live on the Arc 140V), so enabled=true is now the
    intended committed posture (ADR-033 §dormancy/go-live)."""
    import tomllib
    from pathlib import Path

    from services.assistant_orchestrator.src.entrypoint import (
        AssistantOrchestratorService,
    )

    svc = AssistantOrchestratorService.from_default_config()
    cfgpath = Path("services/assistant_orchestrator/config/default.toml")
    data = tomllib.loads(cfgpath.read_text(encoding="utf-8"))
    # Validation accepts the section (no raise).
    svc._validate_config_data(data, cfgpath)
    assert data["image_generation"]["enabled"] is True
    assert data["image_generation"]["require_signed_manifest"] is True


def test_image_gen_config_rejects_non_bool_enabled():
    import copy
    import tomllib
    from pathlib import Path

    from services.assistant_orchestrator.src.entrypoint import (
        AssistantOrchestratorService,
    )
    from shared.runtime_config import ConfigResolutionError

    svc = AssistantOrchestratorService.from_default_config()
    cfgpath = Path("services/assistant_orchestrator/config/default.toml")
    data = tomllib.loads(cfgpath.read_text(encoding="utf-8"))
    bad = copy.deepcopy(data)
    bad["image_generation"]["enabled"] = "yes"
    with pytest.raises(ConfigResolutionError):
        svc._validate_config_data(bad, cfgpath)


def test_image_gen_config_rejects_non_bool_require_signed_manifest():
    """A non-bool [image_generation].require_signed_manifest is rejected at
    validation with the dedicated AO_CFG_IMAGE_GEN_REQUIRE_SIGNED_INVALID code
    (mirrors the non-bool-enabled lock; FUT-04 parity, UC-010 WS1)."""
    import copy
    import tomllib
    from pathlib import Path

    from services.assistant_orchestrator.src.entrypoint import (
        AssistantOrchestratorService,
    )
    from shared.runtime_config import ConfigResolutionError

    svc = AssistantOrchestratorService.from_default_config()
    cfgpath = Path("services/assistant_orchestrator/config/default.toml")
    data = tomllib.loads(cfgpath.read_text(encoding="utf-8"))
    bad = copy.deepcopy(data)
    bad["image_generation"]["require_signed_manifest"] = "yes"
    with pytest.raises(ConfigResolutionError) as excinfo:
        svc._validate_config_data(bad, cfgpath)
    assert excinfo.value.code == "AO_CFG_IMAGE_GEN_REQUIRE_SIGNED_INVALID"


def test_image_gen_require_signed_resolves_and_threads_to_module():
    """[image_generation].require_signed_manifest=true resolves through the AO
    config and threads into the image_gen module via configure() — so the
    module's load-time gate reads the SAME launcher-resolved flag.

    Mirrors test_image_gen_config_dormant_by_default (resolve the TOML key), then
    drives the real configure()/current_config() seam exactly as start() does
    (resolve the [image_generation] flag -> ImageGenConfig -> configure). The
    image_gen module global is reset afterward so no cross-test bleed."""
    import tomllib
    from pathlib import Path

    import shared.inference.image_gen as ig

    cfgpath = Path("services/assistant_orchestrator/config/default.toml")
    data = tomllib.loads(cfgpath.read_text(encoding="utf-8"))
    # The shipped default.toml sets require_signed_manifest = true (go-live parity
    # with the signed 14B); confirm the resolution source value first.
    resolved_flag = bool(
        data["image_generation"].get("require_signed_manifest", False)
    )
    assert resolved_flag is True, (
        "default.toml must ship [image_generation].require_signed_manifest=true"
    )

    saved = ig.current_config()
    try:
        # The same threading start() performs (entrypoint §UC-010).
        ig.configure(ig.ImageGenConfig(require_signed_manifest=resolved_flag))
        assert ig.current_config().require_signed_manifest is True
    finally:
        ig.configure(saved)


def test_image_gen_quality_knobs_resolve_from_default_toml():
    """[image_generation].scheduler/guidance_scale/negative_prompt resolve from
    the shipped default.toml and thread into the image_gen module via configure()
    (UC-010 quality tuning, #666)."""
    import tomllib
    from pathlib import Path

    import shared.inference.image_gen as ig

    cfgpath = Path("services/assistant_orchestrator/config/default.toml")
    data = tomllib.loads(cfgpath.read_text(encoding="utf-8"))
    igsec = data["image_generation"]
    sched = str(igsec.get("scheduler", "EULER_ANCESTRAL_DISCRETE"))
    gs = float(igsec.get("guidance_scale", 7.0))
    neg = str(igsec.get("negative_prompt", ig.DEFAULT_NEGATIVE_PROMPT))
    # The shipped config opts into the better scheduler + a sane CFG + a non-empty
    # quality negative.
    assert sched and gs > 0 and neg

    saved = ig.current_config()
    try:
        ig.configure(
            ig.ImageGenConfig(
                scheduler=sched, guidance_scale=gs, negative_prompt=neg
            )
        )
        c = ig.current_config()
        assert c.scheduler == sched
        assert c.guidance_scale == gs
        assert c.negative_prompt == neg
    finally:
        ig.configure(saved)


# ---------------------------------------------------------------------------
# Model variant (UC-010 illustration support, Phase 2a)
# ---------------------------------------------------------------------------


def test_image_gen_config_default_variant_is_photoreal_from_toml():
    """The shipped default.toml selects the LIVE photoreal SDXL variant (the
    dormant illustration model is opt-in only), and validation accepts it."""
    import tomllib
    from pathlib import Path

    from services.assistant_orchestrator.src.entrypoint import (
        AssistantOrchestratorService,
    )
    import shared.inference.image_gen as ig

    svc = AssistantOrchestratorService.from_default_config()
    cfgpath = Path("services/assistant_orchestrator/config/default.toml")
    data = tomllib.loads(cfgpath.read_text(encoding="utf-8"))
    svc._validate_config_data(data, cfgpath)  # no raise
    assert (
        data["image_generation"]["model_variant"] == ig.VARIANT_PHOTOREAL_SDXL
    )


def test_image_gen_config_rejects_unknown_variant():
    """An unknown [image_generation].model_variant is rejected fail-closed with
    the dedicated AO_CFG_IMAGE_GEN_VARIANT_INVALID code — a typo cannot silently
    fall back to the wrong model."""
    import copy
    import tomllib
    from pathlib import Path

    from services.assistant_orchestrator.src.entrypoint import (
        AssistantOrchestratorService,
    )
    from shared.runtime_config import ConfigResolutionError

    svc = AssistantOrchestratorService.from_default_config()
    cfgpath = Path("services/assistant_orchestrator/config/default.toml")
    data = tomllib.loads(cfgpath.read_text(encoding="utf-8"))
    bad = copy.deepcopy(data)
    bad["image_generation"]["model_variant"] = "evil-model"
    with pytest.raises(ConfigResolutionError) as excinfo:
        svc._validate_config_data(bad, cfgpath)
    assert excinfo.value.code == "AO_CFG_IMAGE_GEN_VARIANT_INVALID"


def _fake_resolved_image_gen():
    """A SimpleNamespace carrying every image_gen_* field _image_gen_config_for_style
    reads (#703) — explicit so the style→model+adapter mapping is tested in
    isolation from the full config-resolution path."""
    from types import SimpleNamespace

    return SimpleNamespace(
        image_gen_enabled=True,
        image_gen_model_dir="models/sdxl-uncensored/openvino-int8-gpu",
        image_gen_weight_manifest="models/sdxl-uncensored/openvino-int8-gpu/manifest.json",
        image_gen_illustration_model_dir="models/sdxl-illustration/openvino-int8-gpu",
        image_gen_illustration_weight_manifest="models/sdxl-illustration/openvino-int8-gpu/manifest.json",
        image_gen_illustration_lora_path="models/sdxl-illustration/lora/DD-vector-v2.safetensors",
        image_gen_illustration_lora_alpha=0.8,
        image_gen_illustration_lora_sha256="b4c8132f85ab7d75f5789eaf0054153a6011b505719f1253fb7d8837a498fe89",
        image_gen_device="GPU",
        image_gen_steps=30,
        image_gen_scheduler="EULER_ANCESTRAL_DISCRETE",
        image_gen_guidance_scale=7.0,
        image_gen_negative_prompt="",
        image_gen_hires_enabled=True,
        image_gen_hires_factor=1.5,
        image_gen_hires_strength=0.4,
        image_gen_hires_max_edge=1536,
        image_gen_max_width=1024,
        image_gen_max_height=1024,
        image_gen_idle_unload_s=60,
        image_gen_require_signed_manifest=True,
    )


def _ends(path, rel):
    return str(path).replace("\\", "/").endswith(rel)


def test_image_gen_config_for_style_photoreal():
    """#703: photoreal -> RealVisXL, NO adapter, hires-fix ON (it is photoreal-only)."""
    from services.assistant_orchestrator.src.entrypoint import (
        AssistantOrchestratorService,
    )
    import shared.inference.image_gen as ig

    svc = AssistantOrchestratorService.from_default_config()
    cfg = svc._image_gen_config_for_style(
        _fake_resolved_image_gen(), MessageFramer.IMAGE_GEN_STYLE_PHOTOREAL
    )
    assert cfg.model_variant == ig.VARIANT_PHOTOREAL_SDXL
    assert _ends(cfg.model_dir, "models/sdxl-uncensored/openvino-int8-gpu")
    assert cfg.lora_adapter_path is None
    assert cfg.hires_enabled is True


def test_image_gen_config_for_style_illustration_base_sdxl_no_adapter():
    """#703: illustration -> base SDXL, NO adapter (flat-vector via prompt only),
    hires-fix OFF (flat art has no small-face problem)."""
    from services.assistant_orchestrator.src.entrypoint import (
        AssistantOrchestratorService,
    )
    import shared.inference.image_gen as ig

    svc = AssistantOrchestratorService.from_default_config()
    cfg = svc._image_gen_config_for_style(
        _fake_resolved_image_gen(), MessageFramer.IMAGE_GEN_STYLE_ILLUSTRATION
    )
    assert cfg.model_variant == ig.VARIANT_ILLUSTRATION
    assert _ends(cfg.model_dir, "models/sdxl-illustration/openvino-int8-gpu")
    assert cfg.lora_adapter_path is None
    assert cfg.hires_enabled is False


def test_image_gen_config_for_style_cartoon_adds_runtime_lora():
    """#703: cartoon -> the SAME base SDXL + the DD-vector LoRA at RUNTIME (the
    adapter path is set; the model is NOT a fused variant)."""
    from services.assistant_orchestrator.src.entrypoint import (
        AssistantOrchestratorService,
    )
    import shared.inference.image_gen as ig

    svc = AssistantOrchestratorService.from_default_config()
    cfg = svc._image_gen_config_for_style(
        _fake_resolved_image_gen(), MessageFramer.IMAGE_GEN_STYLE_CARTOON
    )
    assert cfg.model_variant == ig.VARIANT_ILLUSTRATION_CARTOON
    assert _ends(cfg.model_dir, "models/sdxl-illustration/openvino-int8-gpu")
    assert cfg.lora_adapter_path is not None
    assert _ends(cfg.lora_adapter_path, "models/sdxl-illustration/lora/DD-vector-v2.safetensors")
    assert cfg.lora_adapter_alpha == 0.8
    assert cfg.hires_enabled is False
    # #703 hardening (review MINOR #3): the real shipped SHA-256 pin threads from
    # config -> ImageGenConfig.lora_adapter_sha256, so the integrity pin actually
    # reaches _build_adapter_config at pipeline-build time.
    assert cfg.lora_adapter_sha256 == (
        "b4c8132f85ab7d75f5789eaf0054153a6011b505719f1253fb7d8837a498fe89"
    )
    assert cfg.require_signed_manifest is True


def test_image_gen_config_for_style_unknown_falls_back_to_photoreal():
    """#703 hardening (review MINOR #2): an out-of-set / forged style value
    normalizes to photoreal (the default-enabled model) — never a crash nor a
    mis-route to a wrong-but-enabled model."""
    from services.assistant_orchestrator.src.entrypoint import (
        AssistantOrchestratorService,
    )
    import shared.inference.image_gen as ig

    svc = AssistantOrchestratorService.from_default_config()
    cfg = svc._image_gen_config_for_style(
        _fake_resolved_image_gen(), "totally-bogus-style"
    )
    assert cfg.model_variant == ig.VARIANT_PHOTOREAL_SDXL
    assert cfg.lora_adapter_path is None


def test_handle_image_gen_request_threads_cartoon_style_to_configure(monkeypatch):
    """#703 hardening (review MINOR #3): the production JOIN — the AO handler reads
    payload['style'] and reconfigures image_gen with the matching per-style config
    BEFORE the availability gate. Drive the handler with style=cartoon and assert
    configure() received a cartoon config carrying the threaded SHA pin; is_available
    is stubbed False so the handler returns right after configure()."""
    from services.assistant_orchestrator.src.entrypoint import (
        AssistantOrchestratorService,
    )
    import shared.inference.image_gen as ig

    svc = AssistantOrchestratorService.from_default_config()
    svc._resolved_config = _fake_resolved_image_gen()

    captured = {}
    monkeypatch.setattr(ig, "configure", lambda cfg: captured.update(cfg=cfg))
    monkeypatch.setattr(ig, "is_available", lambda: False)

    class _FakeTransport:
        def send(self, _frame):
            return True

    ok = svc._handle_image_gen_request(
        _FakeTransport(),
        "req-1",
        {
            "style": MessageFramer.IMAGE_GEN_STYLE_CARTOON,
            "prompt": "a coffee cup",
            "session_id": "s1",
        },
    )
    assert ok is True  # handler replied (IMAGE_GEN_UNAVAILABLE) without crashing
    cfg = captured.get("cfg")
    assert cfg is not None
    assert cfg.model_variant == ig.VARIANT_ILLUSTRATION_CARTOON
    assert cfg.lora_adapter_path is not None
    assert cfg.lora_adapter_sha256 == (
        "b4c8132f85ab7d75f5789eaf0054153a6011b505719f1253fb7d8837a498fe89"
    )


def test_image_gen_model_variant_resolves_and_threads_to_module():
    """[image_generation].model_variant resolves through the AO config and threads
    into the image_gen module via configure() — so the module's resident-swap key
    reads the SAME launcher-resolved variant."""
    import tomllib
    from pathlib import Path

    import shared.inference.image_gen as ig

    cfgpath = Path("services/assistant_orchestrator/config/default.toml")
    data = tomllib.loads(cfgpath.read_text(encoding="utf-8"))
    variant = str(
        data["image_generation"].get(
            "model_variant", ig.VARIANT_PHOTOREAL_SDXL
        )
    )
    assert variant in ig.KNOWN_VARIANTS

    saved = ig.current_config()
    try:
        ig.configure(ig.ImageGenConfig(model_variant=variant))
        assert ig.current_config().model_variant == variant
    finally:
        ig.configure(saved)


def test_image_gen_config_rejects_out_of_range_guidance_scale():
    """A guidance_scale outside [0, 30] is rejected at validation with the
    dedicated AO_CFG_IMAGE_GEN_GUIDANCE_INVALID code (UC-010 quality, #666)."""
    import copy
    import tomllib
    from pathlib import Path

    from services.assistant_orchestrator.src.entrypoint import (
        AssistantOrchestratorService,
    )
    from shared.runtime_config import ConfigResolutionError

    svc = AssistantOrchestratorService.from_default_config()
    cfgpath = Path("services/assistant_orchestrator/config/default.toml")
    data = tomllib.loads(cfgpath.read_text(encoding="utf-8"))
    bad = copy.deepcopy(data)
    bad["image_generation"]["guidance_scale"] = 999.0
    with pytest.raises(ConfigResolutionError) as excinfo:
        svc._validate_config_data(bad, cfgpath)
    assert excinfo.value.code == "AO_CFG_IMAGE_GEN_GUIDANCE_INVALID"


def test_image_gen_hires_knobs_resolve_from_default_toml():
    """[image_generation].hires_* resolve from the shipped default.toml and
    thread into the image_gen module via configure() (UC-010 hires-fix, #666)."""
    import tomllib
    from pathlib import Path

    import shared.inference.image_gen as ig

    cfgpath = Path("services/assistant_orchestrator/config/default.toml")
    data = tomllib.loads(cfgpath.read_text(encoding="utf-8"))
    igsec = data["image_generation"]
    enabled = bool(igsec.get("hires_enabled", False))
    factor = float(igsec.get("hires_factor", 1.5))
    strength = float(igsec.get("hires_strength", 0.4))
    max_edge = int(igsec.get("hires_max_edge", 1536))

    saved = ig.current_config()
    try:
        ig.configure(
            ig.ImageGenConfig(
                hires_enabled=enabled, hires_factor=factor,
                hires_strength=strength, hires_max_edge=max_edge,
            )
        )
        c = ig.current_config()
        assert c.hires_enabled == enabled
        assert c.hires_factor == factor
        assert c.hires_strength == strength
        assert c.hires_max_edge == max_edge
    finally:
        ig.configure(saved)


def test_image_gen_config_rejects_out_of_range_hires_factor():
    """A hires_factor outside [1.0, 4.0] is rejected at validation with the
    dedicated AO_CFG_IMAGE_GEN_HIRES_FACTOR_INVALID code (UC-010 #666)."""
    import copy
    import tomllib
    from pathlib import Path

    from services.assistant_orchestrator.src.entrypoint import (
        AssistantOrchestratorService,
    )
    from shared.runtime_config import ConfigResolutionError

    svc = AssistantOrchestratorService.from_default_config()
    cfgpath = Path("services/assistant_orchestrator/config/default.toml")
    data = tomllib.loads(cfgpath.read_text(encoding="utf-8"))
    bad = copy.deepcopy(data)
    bad["image_generation"]["hires_factor"] = 9.0
    with pytest.raises(ConfigResolutionError) as excinfo:
        svc._validate_config_data(bad, cfgpath)
    assert excinfo.value.code == "AO_CFG_IMAGE_GEN_HIRES_FACTOR_INVALID"
