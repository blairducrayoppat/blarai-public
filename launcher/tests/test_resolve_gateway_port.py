"""Wiring regression lock for the gateway transport-port selection.

WHY THIS FILE EXISTS
====================
Production host-mode boot rejected every user prompt with::

    stream_tokens: error from Orchestrator: {'error': 'Unsupported message type: PROMPT_REQUEST'}

Root cause: ``launcher/__main__.py`` selected the gateway's transport port
wrong in production host-mode.  The gateway uses a SINGLE port for BOTH its
PA-liveness handshake and its prompt connection
(``services/ui_gateway/src/transport.py`` ``self._port``).  The buggy code
pointed production host-mode at the Policy Agent's port (5000) instead of the
Assistant Orchestrator's (5001).  The PA answers ``HANDSHAKE_REQUEST`` (since
S15-EA-4f) so Boot-Phase-3 looked healthy, but the PA rejects
``PROMPT_REQUEST`` — so the misroute was invisible until a real prompt arrived.
Dev-mode worked because it always targeted the AO (5001).

These are fast, pure-function tests (no sockets) that lock the invariant
``gateway prompt port == AO listener port`` so a future divergence is caught in
CI rather than at a live boot.  The full gateway<->AO round-trip is covered by
``tests/integration/test_prompt_round_trip_host_mode.py``.
"""

from __future__ import annotations

from pathlib import Path

try:  # Python 3.11+ stdlib
    import tomllib as _toml
except ModuleNotFoundError:  # pragma: no cover - fallback for <3.11
    import tomli as _toml  # type: ignore[no-redef]

import pytest

from launcher.__main__ import (
    ORCHESTRATOR_HOST_LOOPBACK_PORT,
    PA_HOST_PRODUCTION_PORT,
    resolve_gateway_port,
    resolve_gateway_topology,
)
from shared.runtime_config import DeploymentMode


_REPO_ROOT = Path(__file__).resolve().parents[2]
_AO_DEFAULT_CONFIG = (
    _REPO_ROOT
    / "services"
    / "assistant_orchestrator"
    / "config"
    / "default.toml"
)


def _ao_config_vsock_port(config_path: Path) -> int:
    """Read [ipc].vsock_port from an AO TOML config (the AO listener port)."""
    with config_path.open("rb") as handle:
        data = _toml.load(handle)
    return int(data["ipc"]["vsock_port"])


class TestResolveGatewayPort:
    """The gateway prompt port must equal the AO listener port (the fix)."""

    def test_dev_mode_targets_ao_loopback_port(self) -> None:
        """Dev-mode resolves to the AO loopback port (this always worked)."""
        assert (
            resolve_gateway_port(dev_mode=True, host_mode=True)
            == ORCHESTRATOR_HOST_LOOPBACK_PORT
        )

    def test_dev_mode_ignores_host_mode_flag(self) -> None:
        """Dev is always loopback to the AO regardless of host_mode."""
        assert (
            resolve_gateway_port(dev_mode=True, host_mode=False)
            == ORCHESTRATOR_HOST_LOOPBACK_PORT
        )

    def test_production_host_mode_targets_ao_loopback_port(self) -> None:
        """REGRESSION: production host-mode must target the AO (5001), not the PA.

        This is the exact bug: production host-mode previously returned the PA
        port (5000), so PROMPT_REQUEST was rejected with "Unsupported message
        type".  The AO is the only service that handles PROMPT_REQUEST.
        """
        assert (
            resolve_gateway_port(dev_mode=False, host_mode=True)
            == ORCHESTRATOR_HOST_LOOPBACK_PORT
        )

    def test_production_host_mode_does_not_target_pa_port(self) -> None:
        """The gateway prompt port must NOT be the PA's port in production."""
        assert (
            resolve_gateway_port(dev_mode=False, host_mode=True)
            != PA_HOST_PRODUCTION_PORT
        )

    def test_dev_and_production_host_mode_resolve_to_same_port(self) -> None:
        """mTLS is the only prod/dev difference on this path — NOT the port."""
        assert resolve_gateway_port(
            dev_mode=True, host_mode=True
        ) == resolve_gateway_port(dev_mode=False, host_mode=True)

    def test_guest_mode_returns_zero(self) -> None:
        """Production guest-mode uses AF_HYPERV — TCP port is unused (0)."""
        assert resolve_gateway_port(dev_mode=False, host_mode=False) == 0


class TestGatewayPortMatchesAoListenerSingleSourceOfTruth:
    """Lock the invariant: gateway prompt port == AO config vsock_port.

    The launcher constant ``ORCHESTRATOR_HOST_LOOPBACK_PORT`` and the AO's own
    ``[ipc].vsock_port`` are two independent declarations of the same physical
    port.  If either drifts, the gateway would connect to a port the AO is not
    listening on (or vice versa).  These tests fail CI the moment they diverge,
    making the constant and the config a single, verified source of truth.
    """

    def test_resolved_host_mode_port_equals_ao_production_config_port(self) -> None:
        ao_listener_port = _ao_config_vsock_port(_AO_DEFAULT_CONFIG)
        assert (
            resolve_gateway_port(dev_mode=False, host_mode=True)
            == ao_listener_port
        )

    def test_resolved_dev_mode_port_equals_ao_production_config_port(self) -> None:
        ao_listener_port = _ao_config_vsock_port(_AO_DEFAULT_CONFIG)
        assert (
            resolve_gateway_port(dev_mode=True, host_mode=True)
            == ao_listener_port
        )

    def test_launcher_constant_equals_ao_production_config_port(self) -> None:
        assert ORCHESTRATOR_HOST_LOOPBACK_PORT == _ao_config_vsock_port(
            _AO_DEFAULT_CONFIG
        )


class TestResolveGatewayTopology:
    """The #615 guest-boundary topology flip — with a clean host-mode fallback.

    ``resolve_gateway_topology`` returns the gateway's effective ``host_mode``:

      - HOST  → True (loopback + mTLS) — BlarAI's DEFAULT, never overridden.
      - GUEST → False (AF_HYPERV boundary) ONLY when the host can serve
        AF_HYPERV; otherwise it FALLS BACK to host-mode (True) so a
        guest-requested boot on a host without Hyper-V socket support does
        not wedge the default boot path.

    The AF_HYPERV capability probe is platform-dependent, so these tests
    monkeypatch ``_hyperv_transport_available`` to lock BOTH branches
    deterministically on any OS / CI runner.
    """

    def test_host_mode_returns_true(self) -> None:
        """HOST deployment → host_mode=True (the default topology)."""
        assert resolve_gateway_topology(DeploymentMode.HOST, dev_mode=False) is True

    def test_host_mode_true_even_if_hyperv_available(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HOST never flips to the guest boundary even where AF_HYPERV exists.

        The guest path is an ADDED capability, not a replacement: a HOST-mode
        boot must stay host-mode regardless of platform AF_HYPERV support.
        """
        monkeypatch.setattr(
            "launcher.__main__._hyperv_transport_available", lambda: True
        )
        assert resolve_gateway_topology(DeploymentMode.HOST, dev_mode=False) is True

    def test_guest_dev_mode_returns_host_mode_true(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """GUEST + dev_mode → host_mode=True (dev is always loopback).

        The AF_HYPERV probe must NOT even be consulted in dev_mode — assert it
        is bypassed by making the probe raise if called.
        """
        def _boom() -> bool:
            raise AssertionError("AF_HYPERV probe must not run in dev_mode")

        monkeypatch.setattr(
            "launcher.__main__._hyperv_transport_available", _boom
        )
        assert resolve_gateway_topology(DeploymentMode.GUEST, dev_mode=True) is True

    def test_guest_production_with_hyperv_available_flips_to_guest(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """GUEST + production + AF_HYPERV available → host_mode=False (guest boundary).

        This is the topology FLIP: the new #615 capability engages.
        """
        monkeypatch.setattr(
            "launcher.__main__._hyperv_transport_available", lambda: True
        )
        assert (
            resolve_gateway_topology(DeploymentMode.GUEST, dev_mode=False) is False
        )

    def test_guest_production_without_hyperv_falls_back_to_host(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """GUEST + production + AF_HYPERV UNAVAILABLE → clean fallback to host-mode.

        This is the gate-critical safety property: a guest-requested boot on a
        host that cannot serve AF_HYPERV must degrade to host-mode (True), NOT
        fail the boot.  Host-mode is the always-available default.
        """
        monkeypatch.setattr(
            "launcher.__main__._hyperv_transport_available", lambda: False
        )
        assert (
            resolve_gateway_topology(DeploymentMode.GUEST, dev_mode=False) is True
        )

    def test_guest_production_topology_matches_resolve_gateway_port(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When the guest boundary engages, the gateway port must be 0 (AF_HYPERV).

        Locks the two sibling resolvers' agreement: if topology resolves to the
        guest boundary (host_mode=False), resolve_gateway_port for that host_mode
        returns 0 (AF_HYPERV uses no TCP port).
        """
        monkeypatch.setattr(
            "launcher.__main__._hyperv_transport_available", lambda: True
        )
        host_mode = resolve_gateway_topology(DeploymentMode.GUEST, dev_mode=False)
        assert host_mode is False
        assert resolve_gateway_port(dev_mode=False, host_mode=host_mode) == 0

    def test_fallback_topology_uses_host_loopback_port(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A fell-back GUEST boot resolves to the AO loopback port (host-mode).

        Confirms the fallback path is fully consistent: host_mode=True →
        resolve_gateway_port returns the AO loopback port, so the fell-back boot
        connects exactly like a native host-mode boot.
        """
        monkeypatch.setattr(
            "launcher.__main__._hyperv_transport_available", lambda: False
        )
        host_mode = resolve_gateway_topology(DeploymentMode.GUEST, dev_mode=False)
        assert host_mode is True
        assert (
            resolve_gateway_port(dev_mode=False, host_mode=host_mode)
            == ORCHESTRATOR_HOST_LOOPBACK_PORT
        )
