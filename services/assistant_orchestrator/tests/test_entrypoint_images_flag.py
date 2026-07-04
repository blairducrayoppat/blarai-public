"""The AO ``knowledge_images_enabled`` accessor (UC-003 Workstream B #1).

The single source of truth the launcher threads into the gateway so the
gateway-side image FETCH gate honors the same ``[knowledge].images_enabled``
weld-lock the AO storage gate reads.  Fail-closed: ``False`` before ``start()``
resolves the config (``_resolved_config is None``), and the resolved value
(default ``False``, dormant) thereafter — never a second TOML parse.
"""

from __future__ import annotations

from types import SimpleNamespace

from services.assistant_orchestrator.src.entrypoint import (
    AssistantOrchestratorService,
)


def test_unresolved_config_is_fail_closed_false() -> None:
    # Before start() resolves the config, the weld-lock reads False (dormant).
    service = AssistantOrchestratorService("dummy.toml")
    assert service._resolved_config is None
    assert service.knowledge_images_enabled is False


def test_resolved_true_is_surfaced() -> None:
    service = AssistantOrchestratorService("dummy.toml")
    service._resolved_config = SimpleNamespace(knowledge_images_enabled=True)
    assert service.knowledge_images_enabled is True


def test_resolved_false_is_surfaced() -> None:
    service = AssistantOrchestratorService("dummy.toml")
    service._resolved_config = SimpleNamespace(knowledge_images_enabled=False)
    assert service.knowledge_images_enabled is False


def test_missing_attribute_defaults_false() -> None:
    # Defensive: a resolved config lacking the attribute reads False, never raises.
    service = AssistantOrchestratorService("dummy.toml")
    service._resolved_config = SimpleNamespace()
    assert service.knowledge_images_enabled is False


def test_accessor_binds_to_real_config_field() -> None:
    """Bind the accessor to the REAL AssistantOrchestratorEntrypointConfig field
    (not a SimpleNamespace), so a future rename of the dataclass field can't
    silently slip past the getattr key (adversarial review, 2026-06-15)."""
    from services.assistant_orchestrator.tests.test_knowledge_bank_wiring import (
        _make_resolved_config,
    )

    service = AssistantOrchestratorService("dummy.toml")
    service._resolved_config = _make_resolved_config(knowledge_images_enabled=True)
    assert service.knowledge_images_enabled is True
    service._resolved_config = _make_resolved_config(knowledge_images_enabled=False)
    assert service.knowledge_images_enabled is False
