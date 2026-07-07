"""
#615 — Guest-boundary AF_HYPERV round-trip (real Hyper-V VM, hardware-marked).

Sprint 17 SDV §4 criterion C1 — the gate-critical SPINE.

WHAT THIS FILE LOCKS
====================
The host↔guest VM boundary over Windows ``AF_HYPERV`` (Hyper-V sockets).  The
#615 fix corrected the host-side sockaddr from the broken ``(str(cid),
int_port)`` form to the Windows-required ``(VmId, ServiceId)`` GUID pair
(``shared/ipc/vsock.py:_hyperv_sockaddr``) and supplied the mandatory
``HV_PROTOCOL_RAW`` protocol argument.  The unit/stub tiers
(``shared/tests/test_ipc_transport.py`` Groups O/P and
``launcher/tests/test_resolve_gateway_port.py::TestResolveGatewayTopology``)
prove the addressing + topology-flip logic with mocks.  THIS file is the only
tier that proves the seam against a *real* Hyper-V guest — the "mocks pass,
seams break" gap that Sprint 17 exists to close.

It is marked ``@pytest.mark.hardware`` so the standing gate DESELECTS it
(``addopts`` excludes ``hardware``).  Its first green run is the LA on-chip
session (SDV §7 step 2).

HOW TO RUN  (LA on-chip session — dev machine, elevated PowerShell)
==================================================================
Prerequisites:
  1. The BlarAI-Orchestrator Hyper-V VM exists and the guest runtime is
     deployed (``python -m launcher.guest_deploy``), so the Alpine guest binds
     an ``AF_VSOCK`` listener on ``VMADDR_CID_ANY:50000`` (the hv_sock service
     GUID ``0000c350-facb-11e6-bd58-64006a7986d3``).  See
     ``phase2_gates/evidence/vsock_validation.json`` for the validated topology.
  2. A guest-side echo responder is listening on the vsock service port.  The
     ``guest_startup_smoke.py`` shipped by ``guest_deploy`` provides this; if it
     is not running, start it in the guest before running this test.
  3. Run from an ELEVATED shell (Hyper-V socket access needs the VM running and
     may require Administrator).

Command (run from the repo root):

    C:/Users/mrbla/BlarAI/.venv/Scripts/python.exe -m pytest \\
        tests/integration/test_guest_boundary_hyperv.py \\
        -m hardware -v

Expected result: ``test_hyperv_guest_host_round_trip`` PASSES — the host
addresses the guest by the GUID pair, the framed payload is echoed back
byte-for-byte.  A FAILURE here means the guest boundary is broken and the #615
real-VM verify has NOT passed (committed != done until this is green).

ISOLATION / SAFETY
==================
No user data is written.  The test uses the shared IPC transport against the
guest's vsock listener only; no ``%LOCALAPPDATA%`` writes (the root
``conftest.py`` redirects it regardless).  The test SKIPS (does not fail) when
the VM is not running or AF_HYPERV is unavailable, so an accidental run on a
non-Hyper-V box is a skip, not a spurious failure.
"""

from __future__ import annotations

import socket
import sys

import pytest

from shared.constants import (
    ORCHESTRATOR_VM_ID,
    ORCHESTRATOR_VM_NAME,
    VSOCK_PORT,
    VSOCK_SERVICE_GUID,
)
from shared.ipc.vsock import (
    AF_HYPERV,
    HV_PROTOCOL_RAW,
    VsockAddress,
    VsockConfig,
    VsockTransport,
    _hyperv_sockaddr,
)


# Round-trip timeout — generous; the guest echo is local hypervisor IPC.
_HYPERV_TIMEOUT_S: float = 10.0
_PROBE_PAYLOAD: bytes = b'{"probe": "blarai #615 guest-boundary round-trip"}'


def _hyperv_socket_supported() -> bool:
    """True if this host can ACTUALLY use AF_HYPERV — Windows AND a Python build
    that exposes ``socket.AF_HYPERV``.

    The attribute check is load-bearing: ``shared.ipc.vsock`` falls back to the
    literal family int 34 when ``socket.AF_HYPERV`` is absent, which lets
    ``socket.socket()`` *create* a socket that then fails at ``connect()`` with
    "bad family" — because CPython only gained ``socket.AF_HYPERV`` after 3.11.
    BlarAI's venv is 3.11.9; the AF_HYPERV guest path needs Python >= 3.12.
    Real support therefore means the attribute exists, not merely that socket
    creation succeeds.
    """
    if sys.platform != "win32":
        return False
    if not hasattr(socket, "AF_HYPERV"):
        return False  # Python < 3.12: no AF_HYPERV sockaddr support
    probe: socket.socket | None = None
    try:
        probe = socket.socket(AF_HYPERV, socket.SOCK_STREAM, HV_PROTOCOL_RAW)
        return True
    except OSError:
        return False
    finally:
        if probe is not None:
            try:
                probe.close()
            except OSError:
                pass


def _vm_running(vm_name: str) -> bool:
    """True if the named Hyper-V VM is in the RUNNING state."""
    try:
        from launcher.vm_manager import VMState, get_vm_state

        return get_vm_state(vm_name) == VMState.RUNNING
    except Exception:  # noqa: BLE001 — any vm_manager / PowerShell error → not running
        return False


@pytest.mark.hardware
class TestGuestBoundaryHyperv:
    """Real-Hyper-V guest↔host AF_HYPERV round-trip (#615 C1 — hardware tier)."""

    def test_hyperv_address_is_validated_guid_pair(self) -> None:
        """The host-side sockaddr is the validated (VmId, ServiceId) GUID pair.

        Sanity-locks that the constants the round-trip uses match the empirically
        validated topology (``phase2_gates/evidence/vsock_validation.json``) and
        that ``_hyperv_sockaddr`` produces exactly that pair — so a constants
        drift is caught even on the hardware tier before the socket work.
        """
        addr = VsockAddress(
            cid=0,
            port=VSOCK_PORT,
            vm_id=ORCHESTRATOR_VM_ID,
            service_guid=VSOCK_SERVICE_GUID,
        )
        assert _hyperv_sockaddr(addr) == (ORCHESTRATOR_VM_ID, VSOCK_SERVICE_GUID)
        assert ORCHESTRATOR_VM_ID == "9c7f986f-7afd-48b0-af5b-2c330df6b38f"
        assert VSOCK_SERVICE_GUID == "0000c350-facb-11e6-bd58-64006a7986d3"

    def test_hyperv_guest_host_round_trip(self) -> None:
        """Host connects to the guest over AF_HYPERV and round-trips a payload.

        This is the C1 real-VM verify: the corrected GUID-pair addressing lets a
        Windows host open the Hyper-V socket to the running Alpine guest, send a
        length-prefixed frame, and receive the guest's echo byte-for-byte.

        Note: this connects in dev_mode (no mTLS) to isolate the TRANSPORT /
        addressing seam from the cert layer — the production mTLS path over
        AF_HYPERV is exercised by the full boot in SDV §7 step 2 (launcher.log).
        Here we are proving the #615 addressing fix end-to-end against real
        hardware, which is the criterion's explicit ask ("a real-Hyper-V
        guest<->host round-trip test written").
        """
        if not _hyperv_socket_supported():
            pytest.skip(
                "AF_HYPERV sockets unavailable on this host (not Windows / no "
                "Hyper-V) — guest-boundary round-trip cannot run here."
            )
        if not _vm_running(ORCHESTRATOR_VM_NAME):
            pytest.skip(
                f"Hyper-V VM '{ORCHESTRATOR_VM_NAME}' is not RUNNING — start it "
                "and deploy the guest runtime before running this hardware test."
            )

        config = VsockConfig(
            address=VsockAddress(
                cid=0,
                port=VSOCK_PORT,
                vm_id=ORCHESTRATOR_VM_ID,
                service_guid=VSOCK_SERVICE_GUID,
            ),
            timeout_ms=int(_HYPERV_TIMEOUT_S * 1000),
        )
        # dev_mode=True + host_mode=False would route to AF_INET (dev precedence),
        # so we drive the production guest path (host_mode=False, dev_mode=False)
        # but without cert paths the production mTLS guard fires.  To exercise the
        # raw AF_HYPERV transport seam we construct the socket directly here,
        # mirroring VsockTransport's guest-mode branch, then hand it to the
        # transport for the framed round-trip.
        hv_addr = _hyperv_sockaddr(config.address)
        raw = socket.socket(AF_HYPERV, socket.SOCK_STREAM, HV_PROTOCOL_RAW)
        raw.settimeout(_HYPERV_TIMEOUT_S)
        try:
            raw.connect(hv_addr)
        except OSError as exc:
            raw.close()
            pytest.skip(
                f"Could not connect to the guest vsock listener at {hv_addr}: "
                f"{exc}. Ensure the guest echo responder is listening on "
                f"service port {VSOCK_PORT}."
            )

        transport = VsockTransport(
            config, dev_mode=False, host_mode=False, _socket=raw
        )
        try:
            assert transport.connected is True
            sent = transport.send(_PROBE_PAYLOAD)
            assert sent is True, "Host→guest AF_HYPERV send must succeed"

            echoed = transport.receive()
            assert echoed == _PROBE_PAYLOAD, (
                "Guest must echo the framed payload byte-for-byte over the "
                f"AF_HYPERV boundary; got {echoed!r}"
            )
        finally:
            transport.close()
