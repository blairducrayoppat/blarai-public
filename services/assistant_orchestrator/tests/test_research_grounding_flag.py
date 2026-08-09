"""#746 — [fleet_dispatch].research_grounding config resolution + resolver property.

Drives the REAL ``_load_entrypoint_config`` over a hand-written dev-mode TOML (the
same seam ``test_knowledge_bank_wiring`` uses) so the actual resolution expression
``bool(fleet_dispatch.get("research_grounding", False))`` runs unmocked. Fail-closed +
DORMANT: absent key resolves False; the resolver property is False before ``start()``
resolves the config.
"""

from __future__ import annotations

from pathlib import Path

from services.assistant_orchestrator.src.entrypoint import (
    AssistantOrchestratorService,
)

_SKELETON = (
    '[runtime]\ndeployment_mode = "host"\n\n'
    '[gpu]\ndevice = "GPU"\nmodel_dir = "models/x"\npriority = 1\n\n'
    '[generation]\nmax_new_tokens = 64\ntemperature = 0.0\ntop_k = 50\n'
    'top_p = 0.9\nrepetition_penalty = 1.1\ndo_sample = false\n\n'
    '[security]\ndev_mode = true\n\n'
    '[ipc]\nvsock_cid = 2\nvsock_port = 5001\ntimeout_ms = 5000\n'
    'max_message_bytes = 65536\n\n'
    '[pgov]\ncosine_similarity_threshold = 0.85\n'
)


def _load(tmp_path: Path, fleet_dispatch_lines: str):
    cfg_path = tmp_path / "default.toml"
    cfg_path.write_text(_SKELETON + fleet_dispatch_lines, encoding="utf-8")
    service = AssistantOrchestratorService(str(cfg_path), deployment_mode="host")
    service._resolve_config_path = lambda: cfg_path  # type: ignore[method-assign]
    return service._load_entrypoint_config()


def test_research_grounding_resolves_true_when_set(tmp_path: Path) -> None:
    cfg = _load(tmp_path, "\n[fleet_dispatch]\nresearch_grounding = true\n")
    assert cfg.fleet_dispatch_research_grounding is True


def test_research_grounding_defaults_false_when_key_absent(tmp_path: Path) -> None:
    # [fleet_dispatch] present but no research_grounding key -> dormant default.
    cfg = _load(tmp_path, "\n[fleet_dispatch]\nenabled = true\n")
    assert cfg.fleet_dispatch_research_grounding is False


def test_research_grounding_defaults_false_when_section_absent(tmp_path: Path) -> None:
    cfg = _load(tmp_path, "")  # no [fleet_dispatch] section at all
    assert cfg.fleet_dispatch_research_grounding is False


def test_resolver_property_is_false_before_start(tmp_path: Path) -> None:
    # Before start() resolves the config (_resolved_config is None) the property is
    # fail-closed False — the PLAN handler never grounds on an unresolved config.
    service = AssistantOrchestratorService("dummy.toml", deployment_mode="host")
    assert service._resolved_config is None
    assert service.fleet_dispatch_research_grounding is False


def test_resolver_property_reflects_resolved_config(tmp_path: Path) -> None:
    cfg = _load(tmp_path, "\n[fleet_dispatch]\nresearch_grounding = true\n")
    service = AssistantOrchestratorService("dummy.toml", deployment_mode="host")
    service._resolved_config = cfg  # simulate post-start()
    assert service.fleet_dispatch_research_grounding is True
