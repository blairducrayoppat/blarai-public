"""
vsock Transport — Shared IPC Primitives
=========================================
ADR-007: Software fallback posture (Hyper-V + vsock + mTLS).
USE-CASE-001, P1.6: Full transport implementation.
S15-EA-4d: Fidelity-2 host-mode production transport (loopback + mTLS).

Provides the low-level vsock socket abstraction used by all services
for inter-agent communication.  All connections are mTLS-authenticated
in production mode.  dev_mode substitutes TCP loopback (no mTLS) for
local development.

Deployment topology selector (production only, controlled by host_mode):

  host_mode=True  (default) — HOST topology: all services run on the
      same Windows host, nothing in the VM yet.  Production binding /
      connection uses AF_INET loopback (127.0.0.1) + mTLS (server:
      create_server_ssl_context, client: create_client_ssl_context,
      CERT_REQUIRED both ways, per-boot certs from the launcher).
      This is the "fidelity-2" path from the signed SDV criterion #4.
      Air-gap compliant — loopback traffic never leaves the machine.
      Egress guard permits loopback; no external network exposure.

  host_mode=False — GUEST topology: services run inside the Hyper-V
      VM; host and guest are on opposite sides of the VM boundary.
      Production uses AF_HYPERV + mTLS.  ACTIVATED in #615: the Windows
      AF_HYPERV sockaddr is the (VmId, ServiceId) GUID pair (see
      _hyperv_sockaddr), not the (cid, port) form the dormant path
      mis-used.  The launcher selects this topology in GUEST mode with a
      clean fallback to host-mode; the live guest↔host round-trip is
      exercised by the @hardware-marked round-trip test (real Hyper-V VM).

dev_mode=True always uses AF_INET loopback + no mTLS, regardless of
host_mode.  dev_mode takes full precedence over host_mode.

Plaintext-AF_HYPERV bring-up (#655): the family selector (AF_INET loopback
vs AF_HYPERV) was historically conflated with the mTLS selector (on vs off):
"no mTLS" implied "use AF_INET loopback".  That conflation is the #655 host
side gap — the smoke harness's ``dev_mode = not has_mtls`` heuristic sent the
host to AF_INET 127.0.0.1 (connection-refused) instead of the guest over
AF_HYPERV.  ``VsockConfig.allow_plaintext_hyperv`` decouples them: an EXPLICIT
opt-in that requests AF_HYPERV + SOCK_STREAM + HV_PROTOCOL_RAW with NO SSL
wrap, parallel to the guest service's ``--allow-plaintext`` flag.  It is a
bring-up affordance ONLY (mTLS on the parse channel remains the tracked
production residual, ADR-030 §3) — NEVER a default, and the path is logged
loudly when taken.  Production guest-mode with no opt-in STILL requires mTLS
and fails closed exactly as before.

Transport framing: 4-byte big-endian length prefix + payload bytes.
The JSON protocol layer (shared.ipc.protocol) sits above this.

Security:
  - Production host-mode: AF_INET loopback only — no external
    network exposure; egress-guard permits loopback.
  - mTLS enforced in all production modes: bare connections rejected
    fail-closed.  The SOLE exception is the EXPLICIT
    ``allow_plaintext_hyperv`` bring-up opt-in (#655) — never a default.
  - AF_HYPERV (guest-mode) activated (#615): GUID-pair sockaddr +
    HV_PROTOCOL_RAW; missing-GUID config fails closed.
  - Plaintext-AF_HYPERV bring-up (#655): AF_HYPERV + HV_PROTOCOL_RAW with
    NO SSL wrap, gated behind ``allow_plaintext_hyperv=True`` ONLY; logged
    loudly when taken; the guest boundary GUID-pair guard still fires.
  - dev_mode: TCP loopback for testing (mTLS optional).
  - Maximum message size enforced on send and receive.
  - Fail-Closed: connection/read/write failures return False/None.
  - No external network calls.
"""

from __future__ import annotations

import logging
import socket
import ssl
import struct
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Framing: 4-byte big-endian unsigned int header.
_HEADER_FORMAT = "!I"
_HEADER_SIZE = struct.calcsize(_HEADER_FORMAT)

# Windows AF_HYPERV address family constant.
AF_HYPERV = 34
# Windows Hyper-V socket protocol — REQUIRED when creating AF_HYPERV sockets.
# Omitting it (proto defaults to 0) causes WSAEPROTOTYPE / WinError 10041.
# Activated in guest-mode (#615) — see _hyperv_sockaddr().
HV_PROTOCOL_RAW = 1


def _hyperv_sockaddr(address: "VsockAddress") -> tuple[str, str]:
    """Build the Windows AF_HYPERV bind/connect address tuple.

    Windows Hyper-V sockets do NOT address by ``(cid, port)`` the way Linux
    ``AF_VSOCK`` does.  The Windows winsock AF_HYPERV sockaddr is a pair of
    **GUID strings** — ``(VmId, ServiceId)`` — where:

      - ``VmId`` is the Hyper-V virtual-machine GUID (the host targets a
        specific guest; the guest binds the well-known wildcard
        ``VMADDR_CID_ANY`` GUID to accept from any partition).
      - ``ServiceId`` is the registered hv_sock service GUID (the
        ``<port_hex>-facb-11e6-bd58-64006a7986d3`` template that maps the
        AF_VSOCK port the Linux guest listens on).

    This was the #615 addressing bug: the dormant path passed
    ``(str(cid), int_port)`` — a stringified integer CID and an integer
    port — which winsock cannot parse as an AF_HYPERV address, so the
    guest boundary was un-addressable on Windows.  The empirical topology
    (``phase2_gates/evidence/vsock_validation.json``, Windows 11 Build
    26200) confirms the GUID-pair form: ``vm_id`` +
    ``service_guid`` + ``HV_PROTOCOL_RAW``.

    Args:
        address: The ``VsockAddress`` whose ``vm_id`` / ``service_guid``
            GUID fields carry the Hyper-V identifiers.

    Returns:
        ``(vm_id_guid, service_guid)`` — the tuple winsock expects.

    Raises:
        ValueError: If either GUID is empty (Fail-Closed — never address
            a Hyper-V socket with a missing identifier).
    """
    vm_id = address.vm_id.strip()
    service_guid = address.service_guid.strip()
    if not vm_id or not service_guid:
        raise ValueError(
            "AF_HYPERV addressing requires both vm_id and service_guid GUIDs "
            f"(got vm_id={vm_id!r}, service_guid={service_guid!r}); the "
            "(cid, port) form is Linux AF_VSOCK and is not addressable on "
            "Windows AF_HYPERV (#615)."
        )
    return (vm_id, service_guid)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VsockAddress:
    """Hyper-V vsock endpoint address.

    Carries BOTH addressing schemes so a single config object describes the
    endpoint regardless of topology:

      - ``cid`` / ``port`` — the Linux ``AF_VSOCK`` numeric form, and the
        loopback port reused by host-mode (AF_INET 127.0.0.1).
      - ``vm_id`` / ``service_guid`` — the Windows ``AF_HYPERV`` GUID form
        (``(VmId, ServiceId)``), required for the guest boundary (#615).
        Empty by default; populated by the launcher in guest topology from
        ``shared.constants.ORCHESTRATOR_VM_ID`` / ``VSOCK_SERVICE_GUID``.
    """

    cid: int
    """Context Identifier — Linux AF_VSOCK numeric VM identifier."""

    port: int
    """Service port within the VM (also used as loopback port in host-mode)."""

    vm_id: str = ""
    """Windows AF_HYPERV VM GUID (``VmId``).  Empty unless guest topology."""

    service_guid: str = ""
    """Windows AF_HYPERV service GUID (``ServiceId``, hv_sock template)."""


@dataclass
class VsockConfig:
    """Configuration for a vsock listener or connector."""

    address: VsockAddress
    """Local bind address (listener) or remote target (connector)."""

    mtls_cert_path: str = ""
    """Path to the mTLS client/server certificate (PEM)."""

    mtls_key_path: str = ""
    """Path to the mTLS private key (PEM)."""

    ca_cert_path: str = ""
    """Path to the Policy Agent CA certificate for peer verification."""

    timeout_ms: int = 5_000
    """Connection/read timeout in milliseconds."""

    max_message_bytes: int = 65_536
    """Maximum message size (64KB default — prevents unbounded reads)."""

    allow_plaintext_hyperv: bool = False
    """EXPLICIT opt-in for the plaintext-AF_HYPERV bring-up path (#655).

    Default ``False`` — production guest-mode (``dev_mode=False,
    host_mode=False``) with no mTLS material STILL fails closed exactly as
    before.  When ``True`` AND no mTLS material is configured, the guest-mode
    transport/listener takes ``AF_HYPERV + SOCK_STREAM + HV_PROTOCOL_RAW`` with
    NO SSL wrap — the host-side parallel to the guest service's
    ``--allow-plaintext`` flag.  This is a bring-up affordance ONLY (mTLS on the
    parse channel remains the tracked production residual, ADR-030 §3); the path
    is logged loudly when taken.  It does NOT affect the AF_INET-loopback
    (dev_mode / host_mode) paths — only the guest-mode AF_HYPERV branch.  If mTLS
    material IS present it is honored regardless of this flag (mTLS wins)."""


# ---------------------------------------------------------------------------
# mTLS SSL context factories
# ---------------------------------------------------------------------------


def create_server_ssl_context(
    cert_path: str,
    key_path: str,
    ca_cert_path: str,
) -> ssl.SSLContext | None:
    """Create an mTLS server SSL context.

    Configures mutual TLS: the server presents its cert AND verifies the
    client cert against the CA.  TLS 1.2+ minimum.

    Returns:
        Configured SSLContext, or None on error (Fail-Closed).
    """
    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)
        ctx.load_verify_locations(cafile=ca_cert_path)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        return ctx
    except (ssl.SSLError, OSError, ValueError) as exc:
        logger.error("Failed to create server SSL context: %s", exc)
        return None


def create_client_ssl_context(
    cert_path: str,
    key_path: str,
    ca_cert_path: str,
) -> ssl.SSLContext | None:
    """Create an mTLS client SSL context.

    Configures mutual TLS: the client presents its cert AND verifies the
    server cert against the CA.  Hostname checking disabled (vsock uses
    CIDs / loopback addresses, not hostnames).

    Returns:
        Configured SSLContext, or None on error (Fail-Closed).
    """
    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)
        ctx.load_verify_locations(cafile=ca_cert_path)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.check_hostname = False  # vsock / loopback doesn't use hostnames.
        return ctx
    except (ssl.SSLError, OSError, ValueError) as exc:
        logger.error("Failed to create client SSL context: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------


def _extract_cn(cert_dict: dict[str, Any]) -> str | None:
    """Extract the Common Name from a getpeercert() dict.

    Args:
        cert_dict: The dictionary returned by SSLSocket.getpeercert().

    Returns:
        The CN string, or None if not present or malformed.
    """
    subject = cert_dict.get("subject", ())
    for rdn in subject:
        for attr_type, attr_value in rdn:
            if attr_type == "commonName":
                return str(attr_value)
    return None


class VsockTransport:
    """vsock transport with mTLS enforcement.

    Topology (production, dev_mode=False):
      host_mode=True  — AF_INET loopback (127.0.0.1) + mTLS.  DEFAULT.
                        Fidelity-2 path per SDV criterion #4.
      host_mode=False — AF_HYPERV + mTLS.  Guest boundary (#615 — active).

    dev_mode=True always uses AF_INET loopback without mTLS, regardless
    of host_mode.

    Framing protocol (handled internally):
      send(data) -> writes [4-byte length header][data] to the socket.
      receive()  -> reads 4-byte header, then reads exactly N payload bytes.

    Higher layers (MessageFramer) deal only with JSON bytes.
    """

    def __init__(
        self,
        config: VsockConfig,
        *,
        dev_mode: bool = False,
        host_mode: bool = True,
        _socket: socket.socket | ssl.SSLSocket | None = None,
        _peer_cn: str | None = None,
    ) -> None:
        self._config = config
        self._dev_mode = dev_mode
        self._host_mode = host_mode
        self._sock: socket.socket | ssl.SSLSocket | None = _socket
        self._connected: bool = _socket is not None
        self._peer_cn: str | None = _peer_cn

    @property
    def connected(self) -> bool:
        """Whether the transport has an active connection."""
        return self._connected

    @property
    def config(self) -> VsockConfig:
        """The transport configuration."""
        return self._config

    @property
    def dev_mode(self) -> bool:
        """Whether running in dev/test mode (TCP loopback, no mTLS)."""
        return self._dev_mode

    @property
    def host_mode(self) -> bool:
        """Whether in host topology (loopback + mTLS in production)."""
        return self._host_mode

    @property
    def peer_cn(self) -> str | None:
        """The mTLS peer certificate Common Name, or None in dev_mode."""
        return self._peer_cn

    def connect(self) -> bool:
        """Establish a connection with optional mTLS.

        Topology:
          dev_mode=True       -> AF_INET loopback, no mTLS.
          production host_mode=True  -> AF_INET loopback + mTLS (fidelity-2).
          production host_mode=False -> AF_HYPERV + mTLS (guest boundary, #615).
          production host_mode=False + allow_plaintext_hyperv + no mTLS
                                     -> AF_HYPERV + HV_PROTOCOL_RAW, NO SSL
                                        (explicit bring-up opt-in, #655).

        Returns:
            True if connected (and mTLS handshake succeeded if configured).

        Fail-Closed: returns False on any error. Never raises.
        """
        # Plaintext-AF_HYPERV bring-up gate (#655): an EXPLICIT opt-in for the
        # guest boundary WITHOUT mTLS material.  Computed before the socket so a
        # production guest-mode connection with neither mTLS nor the opt-in still
        # fails closed exactly as before.
        plaintext_hyperv = self._is_plaintext_hyperv()
        try:
            if self._dev_mode:
                # Dev path: plain loopback, no mTLS.
                raw: socket.socket = socket.socket(
                    socket.AF_INET, socket.SOCK_STREAM
                )
                raw.settimeout(self._config.timeout_ms / 1000.0)
                raw.connect(("127.0.0.1", self._config.address.port))
            elif self._host_mode:
                # Production host-mode: loopback + mTLS (fidelity-2 / SDV §4).
                raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                raw.settimeout(self._config.timeout_ms / 1000.0)
                raw.connect(("127.0.0.1", self._config.address.port))
            else:
                # Production guest-mode: AF_HYPERV (#615 — activated).  mTLS is
                # the default; the plaintext bring-up opt-in (#655) takes the
                # SAME family/proto but skips the SSL wrap below.  The address is
                # the (VmId, ServiceId) GUID pair, NOT (cid, port) — see
                # _hyperv_sockaddr().  Built before the socket so a missing-GUID
                # config fails closed without leaking a socket handle.
                if plaintext_hyperv:
                    logger.warning(
                        "vsock: connecting over PLAINTEXT AF_HYPERV (no mTLS) — "
                        "bring-up affordance (allow_plaintext_hyperv=True, #655); "
                        "mTLS on this channel is the tracked production residual"
                    )
                hv_addr = _hyperv_sockaddr(self._config.address)
                raw = socket.socket(AF_HYPERV, socket.SOCK_STREAM, HV_PROTOCOL_RAW)
                raw.settimeout(self._config.timeout_ms / 1000.0)
                raw.connect(hv_addr)

            # Wrap with mTLS if cert paths configured.
            if self._config.mtls_cert_path and self._config.ca_cert_path:
                ctx = create_client_ssl_context(
                    self._config.mtls_cert_path,
                    self._config.mtls_key_path,
                    self._config.ca_cert_path,
                )
                if ctx is None:
                    raw.close()
                    return False
                self._sock = ctx.wrap_socket(raw, server_side=False)
            else:
                if not self._dev_mode and not plaintext_hyperv:
                    # Production (any topology) requires mTLS — Fail-Closed.
                    # The ONLY no-mTLS production exception is the explicit
                    # plaintext-AF_HYPERV bring-up opt-in (#655), handled above.
                    raw.close()
                    logger.error("mTLS required in production mode")
                    return False
                self._sock = raw

            self._connected = True
            return True

        except (OSError, ssl.SSLError, ValueError) as exc:
            # ValueError covers a missing-GUID AF_HYPERV address
            # (_hyperv_sockaddr) — fail closed, never raise (contract above).
            logger.error("Connection failed: %s", exc)
            self._connected = False
            return False

    def _is_plaintext_hyperv(self) -> bool:
        """Whether this transport should take the plaintext-AF_HYPERV path (#655).

        True ONLY when ALL hold: production (not dev_mode), guest-mode (not
        host_mode), the explicit ``allow_plaintext_hyperv`` opt-in is set, AND no
        mTLS material is configured (mTLS material always wins — the flag never
        downgrades a cert-bearing config to plaintext).  Every other combination
        is False, so the mTLS-required fail-closed default is untouched.
        """
        has_mtls = bool(
            self._config.mtls_cert_path and self._config.ca_cert_path
        )
        return (
            not self._dev_mode
            and not self._host_mode
            and self._config.allow_plaintext_hyperv
            and not has_mtls
        )

    def send(self, data: bytes) -> bool:
        """Send length-prefixed data over the channel.

        Framing: [4-byte big-endian length][data]

        Args:
            data: Raw payload bytes (JSON from MessageFramer).

        Returns:
            True if sent successfully.

        Fail-Closed: returns False if not connected or send fails.
        """
        if not self._connected or self._sock is None:
            return False

        if len(data) > self._config.max_message_bytes:
            logger.error(
                "Message size %d exceeds limit %d",
                len(data),
                self._config.max_message_bytes,
            )
            return False

        try:
            header = struct.pack(_HEADER_FORMAT, len(data))
            self._sock.sendall(header + data)
            return True
        except (OSError, ssl.SSLError) as exc:
            logger.error("Send failed: %s", exc)
            self._connected = False
            return False

    def receive(self) -> bytes | None:
        """Receive a length-prefixed message from the channel.

        Reads: [4-byte header] -> [N payload bytes]

        Returns:
            Payload bytes (without header), or None on failure/timeout.

        Fail-Closed: returns None on any error.
        """
        if not self._connected or self._sock is None:
            return None

        try:
            header = self._recv_exact(_HEADER_SIZE)
            if header is None:
                return None

            (length,) = struct.unpack(_HEADER_FORMAT, header)

            if length > self._config.max_message_bytes:
                logger.error(
                    "Incoming message size %d exceeds limit %d",
                    length,
                    self._config.max_message_bytes,
                )
                return None

            if length == 0:
                return b""

            return self._recv_exact(length)

        except (OSError, ssl.SSLError, struct.error) as exc:
            logger.error("Receive failed: %s", exc)
            self._connected = False
            return None

    def close(self) -> None:
        """Close the connection and release resources."""
        self._connected = False
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def _recv_exact(self, num_bytes: int) -> bytes | None:
        """Read exactly num_bytes from the socket.

        Returns:
            The requested bytes, or None if the connection closed.
        """
        if self._sock is None:
            return None
        buf = bytearray()
        while len(buf) < num_bytes:
            chunk = self._sock.recv(num_bytes - len(buf))
            if not chunk:
                return None
            buf.extend(chunk)
        return bytes(buf)


# ---------------------------------------------------------------------------
# Listener (server-side)
# ---------------------------------------------------------------------------


class VsockListener:
    """Server-side vsock listener that accepts connections.

    Topology (production, dev_mode=False):
      host_mode=True  — AF_INET loopback (127.0.0.1) + mTLS.  DEFAULT.
                        Fidelity-2 path per SDV criterion #4.
      host_mode=False — AF_HYPERV + mTLS.  Guest boundary (#615 — active).

    dev_mode=True always listens on AF_INET loopback without mTLS,
    regardless of host_mode.

    Accepts one connection at a time (sequential — per architectural
    design in rule_engine.py and Use Cases_FINAL.md).
    """

    def __init__(
        self,
        config: VsockConfig,
        *,
        dev_mode: bool = False,
        host_mode: bool = True,
        backlog: int = 5,
    ) -> None:
        self._config = config
        self._dev_mode = dev_mode
        self._host_mode = host_mode
        self._backlog = backlog
        self._server_sock: socket.socket | None = None
        self._ssl_ctx: ssl.SSLContext | None = None
        self._running = False

    @property
    def running(self) -> bool:
        """Whether the listener is currently accepting connections."""
        return self._running

    @property
    def config(self) -> VsockConfig:
        """The listener configuration."""
        return self._config

    @property
    def bound_port(self) -> int | None:
        """Return the actual bound port (useful for ephemeral port 0)."""
        if self._server_sock is not None:
            try:
                addr = self._server_sock.getsockname()
                if isinstance(addr, tuple) and len(addr) >= 2:
                    return int(addr[1])
            except OSError:
                pass
        return None

    def start(self) -> bool:
        """Bind and listen for incoming connections.

        Topology:
          dev_mode=True              -> AF_INET loopback, no mTLS.
          production host_mode=True  -> AF_INET loopback + mTLS (fidelity-2).
          production host_mode=False -> AF_HYPERV + mTLS (guest boundary, #615).
          production host_mode=False + allow_plaintext_hyperv + no mTLS
                                     -> AF_HYPERV + HV_PROTOCOL_RAW, NO SSL
                                        (explicit bring-up opt-in, #655).

        Returns:
            True if the listener started successfully.

        Fail-Closed: returns False on any error.
        """
        # Plaintext-AF_HYPERV bring-up gate (#655): an EXPLICIT opt-in for the
        # guest boundary WITHOUT mTLS material.  Production guest-mode with
        # neither mTLS nor the opt-in still fails closed exactly as before.
        plaintext_hyperv = self._is_plaintext_hyperv()
        try:
            # Build mTLS context if configured.
            if self._config.mtls_cert_path and self._config.ca_cert_path:
                self._ssl_ctx = create_server_ssl_context(
                    self._config.mtls_cert_path,
                    self._config.mtls_key_path,
                    self._config.ca_cert_path,
                )
                if self._ssl_ctx is None:
                    return False
            elif not self._dev_mode and not plaintext_hyperv:
                # Production (any topology) requires mTLS — Fail-Closed.  The
                # ONLY no-mTLS production exception is the explicit
                # plaintext-AF_HYPERV bring-up opt-in (#655).
                logger.error("mTLS required in production mode")
                return False
            elif plaintext_hyperv:
                logger.warning(
                    "vsock: listening on PLAINTEXT AF_HYPERV (no mTLS) — bring-up "
                    "affordance (allow_plaintext_hyperv=True, #655); mTLS on this "
                    "channel is the tracked production residual"
                )

            if self._dev_mode:
                # Dev path: plain loopback, no mTLS.
                self._server_sock = socket.socket(
                    socket.AF_INET, socket.SOCK_STREAM
                )
                self._server_sock.setsockopt(
                    socket.SOL_SOCKET, socket.SO_REUSEADDR, 1
                )
                self._server_sock.bind(
                    ("127.0.0.1", self._config.address.port)
                )
            elif self._host_mode:
                # Production host-mode: loopback + mTLS (fidelity-2 / SDV §4).
                self._server_sock = socket.socket(
                    socket.AF_INET, socket.SOCK_STREAM
                )
                self._server_sock.setsockopt(
                    socket.SOL_SOCKET, socket.SO_REUSEADDR, 1
                )
                self._server_sock.bind(
                    ("127.0.0.1", self._config.address.port)
                )
            else:
                # Production guest-mode: AF_HYPERV + mTLS (#615 — activated).
                # Bind the (VmId, ServiceId) GUID pair, NOT (cid, port) —
                # see _hyperv_sockaddr().  Built before the socket so a
                # missing-GUID config fails closed without leaking a handle.
                hv_addr = _hyperv_sockaddr(self._config.address)
                self._server_sock = socket.socket(
                    AF_HYPERV, socket.SOCK_STREAM, HV_PROTOCOL_RAW
                )
                self._server_sock.bind(hv_addr)

            self._server_sock.settimeout(self._config.timeout_ms / 1000.0)
            self._server_sock.listen(self._backlog)
            self._running = True
            return True

        except (OSError, ssl.SSLError, ValueError) as exc:
            # ValueError covers a missing-GUID AF_HYPERV address
            # (_hyperv_sockaddr) — fail closed (start() never raises).
            logger.error("Listener start failed: %s", exc)
            self._running = False
            return False

    def _is_plaintext_hyperv(self) -> bool:
        """Whether this listener should bind the plaintext-AF_HYPERV path (#655).

        True ONLY when ALL hold: production (not dev_mode), guest-mode (not
        host_mode), the explicit ``allow_plaintext_hyperv`` opt-in is set, AND no
        mTLS material is configured (mTLS material always wins).  Every other
        combination is False, so the mTLS-required fail-closed default is
        untouched.  Mirrors ``VsockTransport._is_plaintext_hyperv``.
        """
        has_mtls = bool(
            self._config.mtls_cert_path and self._config.ca_cert_path
        )
        return (
            not self._dev_mode
            and not self._host_mode
            and self._config.allow_plaintext_hyperv
            and not has_mtls
        )

    def accept(self) -> VsockTransport | None:
        """Accept a single incoming connection.

        Returns:
            VsockTransport for the accepted connection, or None on
            timeout/error.
        """
        if not self._running or self._server_sock is None:
            return None

        try:
            client_sock, _addr = self._server_sock.accept()
            client_sock.settimeout(self._config.timeout_ms / 1000.0)

            # Wrap with mTLS if configured.
            peer_cn: str | None = None
            if self._ssl_ctx is not None:
                client_sock = self._ssl_ctx.wrap_socket(
                    client_sock, server_side=True
                )
                try:
                    cert = client_sock.getpeercert()  # type: ignore[union-attr]
                    if cert:
                        peer_cn = _extract_cn(cert)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Could not extract peer CN: %s", exc)

            return VsockTransport(
                self._config,
                dev_mode=self._dev_mode,
                host_mode=self._host_mode,
                _socket=client_sock,
                _peer_cn=peer_cn,
            )

        except socket.timeout:
            return None
        except (OSError, ssl.SSLError) as exc:
            logger.error("Accept failed: %s", exc)
            return None

    def stop(self) -> None:
        """Shutdown the listener and release resources."""
        self._running = False
        if self._server_sock is not None:
            try:
                self._server_sock.close()
            except OSError:
                pass
            self._server_sock = None
