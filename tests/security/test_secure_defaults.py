"""Secure-by-default config regression guard (Tier 1 hardening).

ADR-023 §1 diagnosed the root failure that motivated Sprint 12: the Layer-3
action-lock had been **disabled in the shipped config** (`block_tools_when_documents_
loaded = false`) because the old on-any-document lock was too frictiony — so the
tool-privilege control was a no-op in production. Sprint 12 made the gate
provenance-scoped and returned it to secure-by-default. This test locks that
posture in CI: a PR that flips any ratified security flag back to its insecure
value breaks loudly in the default suite rather than silently shipping a no-op
control (the exact failure mode that hid the original gap).

Decision-free: these are the *settled* secure defaults, not policy choices still
open (e.g. `pii_mode` is a Tier-1 decision the roadmap leaves to the LA, so it is
deliberately NOT asserted here).
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_AO_CONFIG = _REPO / "services/assistant_orchestrator/config/default.toml"
_GUEST_CONFIG = _REPO / "services/assistant_orchestrator/config/guest_runtime.toml"
_PA_GUEST_CONFIG = _REPO / "services/policy_agent/config/guest_runtime.toml"

# The ratified secure-by-default posture (ADR-023 EA-3/EA-4 + the [security] block).
_SECURE_PGOV = {
    "block_tools_on_untrusted_content": True,  # gate secure-by-default (EA-3)
    "leakage_detection_enabled": True,         # Stage-5 leakage on, untrusted-only (EA-4)
    "tool_allowlist_enabled": True,            # tool dispatch allowlist on
}
_SECURE_SECURITY = {
    "fail_closed": True,                       # fail-closed everywhere
    "dev_mode": False,                         # production: dev loosening OFF
}


def _load(path: Path) -> dict:
    with path.open("rb") as f:
        return tomllib.load(f)


def test_ao_shipped_config_keeps_secure_defaults() -> None:
    """The shipped AO config keeps every ratified secure-by-default value. Flipping
    e.g. block_tools_on_untrusted_content back to false (the misconfiguration
    ADR-023 §1 diagnosed) trips this test."""
    assert _AO_CONFIG.exists(), f"shipped AO config missing: {_AO_CONFIG}"
    cfg = _load(_AO_CONFIG)

    pgov = cfg.get("pgov", {})
    for key, secure in _SECURE_PGOV.items():
        assert pgov.get(key) == secure, (
            f"[pgov] {key} must be {secure} (ratified secure default); got {pgov.get(key)!r}"
        )

    security = cfg.get("security", {})
    for key, secure in _SECURE_SECURITY.items():
        assert security.get(key) == secure, (
            f"[security] {key} must be {secure} (ratified secure default); got {security.get(key)!r}"
        )


def test_guest_runtime_config_gate_secure_if_present() -> None:
    """The guest-runtime config (EA-3 updated both) must also keep the gate secure
    where it ships the flag."""
    if not _GUEST_CONFIG.exists():
        pytest.skip("guest_runtime.toml absent")
    pgov = _load(_GUEST_CONFIG).get("pgov", {})
    if "block_tools_on_untrusted_content" in pgov:
        assert pgov["block_tools_on_untrusted_content"] is True, (
            "guest_runtime.toml [pgov] block_tools_on_untrusted_content must be true"
        )


def test_guest_runtime_configs_ship_dev_mode_off() -> None:
    """#641: both guest-runtime configs must ship dev_mode=false. The guest
    profile is dormant (production runs host-mode) and resolve_dev_mode(GUEST)
    already forces False — but the shipped file must MATCH that safe resolution
    rather than carrying an insecure dev_mode=true a future guest-boot path could
    honor. A flip back to true (the pre-#641 state) trips this test loudly, the
    same regression-guard purpose ADR-023 §1 established for the Layer-3 lock."""
    for path in (_GUEST_CONFIG, _PA_GUEST_CONFIG):
        if not path.exists():
            pytest.skip(f"{path.name} absent")
        security = _load(path).get("security", {})
        assert security.get("dev_mode") is False, (
            f"{path.parent.parent.name}/{path.name} [security] dev_mode must be "
            f"false (#641 secure default); got {security.get('dev_mode')!r}"
        )
        assert security.get("fail_closed") is True, (
            f"{path.parent.parent.name}/{path.name} [security] fail_closed must "
            f"be true; got {security.get('fail_closed')!r}"
        )
