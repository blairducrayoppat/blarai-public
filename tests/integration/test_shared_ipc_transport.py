"""
Live-socket (TCP loopback) integration tests for shared.ipc.vsock transport
(moved from shared/tests/test_ipc_transport.py per P5_TASK8_EA5 WI-3).

All tests use dev_mode=True so vsock.py falls back to TCP loopback
(127.0.0.1); AF_HYPERV is production-only. Per TEST_GOVERNANCE.md taxonomy
these live-socket tests belong under tests/integration/ with the slow
marker. Non-live-socket vsock tests (property checks, Fail-Closed guards,
mTLS production fallback) remain in the source file.
"""

from __future__ import annotations

import socket
import ssl
import struct
import threading
from pathlib import Path

import pytest

from shared.ipc.vsock import (
    VsockAddress,
    VsockConfig,
    VsockListener,
    VsockTransport,
    _HEADER_FORMAT,
    _HEADER_SIZE,
)

pytestmark = pytest.mark.slow


# Fixtures duplicated from shared/tests/test_ipc_transport.py
# (TestVsockMTLS::test_mtls_roundtrip requires test_certs fixture).


def _generate_test_certs(tmp_dir: Path) -> dict[str, Path]:
    """Generate a self-signed CA, server cert, and client cert.

    Uses the `cryptography` library (already installed from P1.5).
    Returns dict with paths: ca_cert, ca_key, server_cert, server_key,
    client_cert, client_key.
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    import datetime

    paths: dict[str, Path] = {}

    # --- CA ---
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "BlarAI Test CA"),
    ])
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(hours=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    paths["ca_cert"] = tmp_dir / "ca_cert.pem"
    paths["ca_key"] = tmp_dir / "ca_key.pem"
    paths["ca_cert"].write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    paths["ca_key"].write_bytes(
        ca_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )

    # --- Server cert (signed by CA) ---
    server_key = ec.generate_private_key(ec.SECP256R1())
    server_name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "BlarAI Test Server"),
    ])
    server_cert = (
        x509.CertificateBuilder()
        .subject_name(server_name)
        .issuer_name(ca_name)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(hours=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(
                # For vsock tests — not hostname-based.
                __import__("ipaddress").IPv4Address("127.0.0.1")
            )]),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    paths["server_cert"] = tmp_dir / "server_cert.pem"
    paths["server_key"] = tmp_dir / "server_key.pem"
    paths["server_cert"].write_bytes(
        server_cert.public_bytes(serialization.Encoding.PEM)
    )
    paths["server_key"].write_bytes(
        server_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )

    # --- Client cert (signed by CA) ---
    client_key = ec.generate_private_key(ec.SECP256R1())
    client_name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "BlarAI Test Client"),
    ])
    client_cert = (
        x509.CertificateBuilder()
        .subject_name(client_name)
        .issuer_name(ca_name)
        .public_key(client_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(hours=1))
        .sign(ca_key, hashes.SHA256())
    )
    paths["client_cert"] = tmp_dir / "client_cert.pem"
    paths["client_key"] = tmp_dir / "client_key.pem"
    paths["client_cert"].write_bytes(
        client_cert.public_bytes(serialization.Encoding.PEM)
    )
    paths["client_key"].write_bytes(
        client_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )

    return paths



def _ephemeral_config(*, port: int = 0) -> VsockConfig:
    """Create a VsockConfig with an ephemeral port for testing.

    Carried over from the original ``shared/tests/test_ipc_transport.py`` — the
    P5_TASK8_EA5 WI-3 move of the live-socket tests into ``tests/integration/``
    dropped this helper (and the ``VsockAddress`` import), leaving the migrated
    file referencing an undefined name.  Restored verbatim.
    """
    return VsockConfig(
        address=VsockAddress(cid=0, port=port),
        timeout_ms=2_000,
        max_message_bytes=65_536,
    )


@pytest.fixture(scope="module")
def test_certs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """Module-scoped self-signed CA + server + client certs."""
    tmp_dir = tmp_path_factory.mktemp("certs")
    return _generate_test_certs(tmp_dir)




class TestVsockTransportIO:
    """Live TCP round-trip tests over VsockTransport."""


    def test_send_receive_roundtrip(self) -> None:
        """Client sends, server echoes back — validates framing."""
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.bind(("127.0.0.1", 0))
        server_sock.listen(1)
        port = server_sock.getsockname()[1]

        received: list[bytes | None] = [None]

        def server_echo() -> None:
            conn, _ = server_sock.accept()
            conn.settimeout(2.0)
            # Manually read framed data (header + payload).
            hdr = conn.recv(4)
            (length,) = struct.unpack(_HEADER_FORMAT, hdr)
            payload = conn.recv(length)
            received[0] = payload
            # Echo it back with framing.
            conn.sendall(struct.pack(_HEADER_FORMAT, len(payload)) + payload)
            conn.close()
            server_sock.close()

        t = threading.Thread(target=server_echo, daemon=True)
        t.start()

        cfg = _ephemeral_config(port=port)
        transport = VsockTransport(cfg, dev_mode=True)
        assert transport.connect() is True

        test_data = b'{"type":"HEARTBEAT","request_id":"hb1","payload":{}}'
        assert transport.send(test_data) is True

        response = transport.receive()
        assert response == test_data
        assert received[0] == test_data

        transport.close()
        t.join(timeout=2.0)


    def test_send_empty_payload(self) -> None:
        """Sending an empty payload should frame correctly."""
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.bind(("127.0.0.1", 0))
        server_sock.listen(1)
        port = server_sock.getsockname()[1]

        received_length: list[int] = [0]

        def server_read() -> None:
            conn, _ = server_sock.accept()
            conn.settimeout(2.0)
            hdr = conn.recv(4)
            (length,) = struct.unpack(_HEADER_FORMAT, hdr)
            received_length[0] = length
            if length > 0:
                conn.recv(length)
            conn.close()
            server_sock.close()

        t = threading.Thread(target=server_read, daemon=True)
        t.start()

        cfg = _ephemeral_config(port=port)
        transport = VsockTransport(cfg, dev_mode=True)
        assert transport.connect() is True
        assert transport.send(b"") is True

        transport.close()
        t.join(timeout=2.0)
        assert received_length[0] == 0


class TestVsockListenerBasic:
    """Start/stop lifecycle binds a real TCP socket in dev_mode."""


    def test_start_stop_lifecycle(self) -> None:
        cfg = _ephemeral_config(port=0)
        listener = VsockListener(cfg, dev_mode=True)
        assert listener.start() is True
        assert listener.running is True
        assert listener.bound_port is not None
        assert listener.bound_port > 0

        listener.stop()
        assert listener.running is False
        assert listener.bound_port is None


    def test_double_stop_is_safe(self) -> None:
        cfg = _ephemeral_config(port=0)
        listener = VsockListener(cfg, dev_mode=True)
        assert listener.start() is True
        listener.stop()
        listener.stop()  # Second stop should not raise.
        assert listener.running is False



class TestVsockListenerAccept:
    """Accept flows over real TCP loopback."""


    def test_accept_returns_transport(self) -> None:
        """Listener accepts a connection and returns a VsockTransport."""
        cfg = _ephemeral_config(port=0)
        listener = VsockListener(cfg, dev_mode=True)
        assert listener.start() is True
        port = listener.bound_port
        assert port is not None

        accepted: list[VsockTransport | None] = [None]

        def do_accept() -> None:
            accepted[0] = listener.accept()

        t = threading.Thread(target=do_accept, daemon=True)
        t.start()

        # Client connects.
        client_cfg = _ephemeral_config(port=port)
        client = VsockTransport(client_cfg, dev_mode=True)
        assert client.connect() is True

        t.join(timeout=2.0)
        assert accepted[0] is not None
        assert accepted[0].connected is True

        # Cleanup.
        client.close()
        accepted[0].close()
        listener.stop()


    def test_accept_timeout_returns_none(self) -> None:
        """Accept with no client connecting should timeout and return None."""
        cfg = VsockConfig(
            address=VsockAddress(cid=0, port=0),
            timeout_ms=200,  # Short timeout.
        )
        listener = VsockListener(cfg, dev_mode=True)
        assert listener.start() is True
        result = listener.accept()
        assert result is None
        listener.stop()


    def test_end_to_end_transport_through_listener(self) -> None:
        """Full path: listener accepts → client sends → server receives."""
        cfg = _ephemeral_config(port=0)
        listener = VsockListener(cfg, dev_mode=True)
        assert listener.start() is True
        port = listener.bound_port
        assert port is not None

        server_received: list[bytes | None] = [None]
        server_transport: list[VsockTransport | None] = [None]

        def server_accept_and_read() -> None:
            st = listener.accept()
            if st is not None:
                server_transport[0] = st
                server_received[0] = st.receive()

        t = threading.Thread(target=server_accept_and_read, daemon=True)
        t.start()

        client_cfg = _ephemeral_config(port=port)
        client = VsockTransport(client_cfg, dev_mode=True)
        assert client.connect() is True

        test_msg = b'{"test":"data","num":42}'
        assert client.send(test_msg) is True

        t.join(timeout=2.0)
        assert server_received[0] == test_msg

        # Cleanup.
        client.close()
        if server_transport[0]:
            server_transport[0].close()
        listener.stop()


    def test_bidirectional_through_listener(self) -> None:
        """Client sends, server responds through accepted transport."""
        cfg = _ephemeral_config(port=0)
        listener = VsockListener(cfg, dev_mode=True)
        assert listener.start() is True
        port = listener.bound_port

        def server_echo_handler() -> None:
            st = listener.accept()
            if st is not None:
                data = st.receive()
                if data is not None:
                    st.send(data)
                st.close()

        t = threading.Thread(target=server_echo_handler, daemon=True)
        t.start()

        client_cfg = _ephemeral_config(port=port)
        client = VsockTransport(client_cfg, dev_mode=True)
        assert client.connect() is True

        original = b'{"ping":"pong"}'
        assert client.send(original) is True
        response = client.receive()
        assert response == original

        client.close()
        t.join(timeout=2.0)
        listener.stop()



class TestVsockMTLS:
    """Full mTLS over TCP loopback with self-signed certs."""


    def test_mtls_roundtrip(self, test_certs: dict[str, Path]) -> None:
        """Client and server communicate with mutual TLS."""
        server_cfg = VsockConfig(
            address=VsockAddress(cid=0, port=0),
            mtls_cert_path=str(test_certs["server_cert"]),
            mtls_key_path=str(test_certs["server_key"]),
            ca_cert_path=str(test_certs["ca_cert"]),
            timeout_ms=3_000,
        )
        listener = VsockListener(server_cfg, dev_mode=True)
        assert listener.start() is True
        port = listener.bound_port
        assert port is not None

        server_received: list[bytes | None] = [None]

        def server_handler() -> None:
            st = listener.accept()
            if st is not None:
                data = st.receive()
                server_received[0] = data
                if data is not None:
                    st.send(data)
                st.close()

        t = threading.Thread(target=server_handler, daemon=True)
        t.start()

        client_cfg = VsockConfig(
            address=VsockAddress(cid=0, port=port),
            mtls_cert_path=str(test_certs["client_cert"]),
            mtls_key_path=str(test_certs["client_key"]),
            ca_cert_path=str(test_certs["ca_cert"]),
            timeout_ms=3_000,
        )
        client = VsockTransport(client_cfg, dev_mode=True)
        assert client.connect() is True

        payload = b'{"secure":"yes"}'
        assert client.send(payload) is True
        response = client.receive()
        assert response == payload
        assert server_received[0] == payload

        client.close()
        t.join(timeout=3.0)
        listener.stop()



class TestVsockProductionFallback:
    """mTLS enforcement in non-dev mode (binds port)."""


    def test_listener_start_no_mtls_production_fails(self) -> None:
        """In production mode, listener start without mTLS must fail."""
        cfg = _ephemeral_config(port=0)
        listener = VsockListener(cfg, dev_mode=False)
        assert listener.start() is False
        assert listener.running is False


class TestVsockTransportPeerCN:
    """Peer CN extraction over live mTLS handshake."""


    def test_peer_cn_none_in_dev_mode_accept(self) -> None:
        """Listener accept() in dev_mode (no SSL) → peer_cn is None."""
        cfg = _ephemeral_config(port=0)
        listener = VsockListener(cfg, dev_mode=True)
        assert listener.start() is True
        port = listener.bound_port
        assert port is not None

        accepted: list[VsockTransport | None] = [None]

        def do_accept() -> None:
            accepted[0] = listener.accept()

        t = threading.Thread(target=do_accept, daemon=True)
        t.start()

        client_cfg = _ephemeral_config(port=port)
        client = VsockTransport(client_cfg, dev_mode=True)
        assert client.connect() is True
        t.join(timeout=2.0)

        assert accepted[0] is not None
        assert accepted[0].peer_cn is None

        client.close()
        accepted[0].close()
        listener.stop()


    def test_peer_cn_extracted_from_mtls_cert(
        self, test_certs: dict[str, Path]
    ) -> None:
        """Listener accept() over mTLS in dev_mode → peer_cn = client cert CN."""
        server_cfg = VsockConfig(
            address=VsockAddress(cid=0, port=0),
            mtls_cert_path=str(test_certs["server_cert"]),
            mtls_key_path=str(test_certs["server_key"]),
            ca_cert_path=str(test_certs["ca_cert"]),
            timeout_ms=3_000,
        )
        listener = VsockListener(server_cfg, dev_mode=True)
        assert listener.start() is True
        port = listener.bound_port
        assert port is not None

        accepted: list[VsockTransport | None] = [None]

        def do_accept() -> None:
            accepted[0] = listener.accept()

        t = threading.Thread(target=do_accept, daemon=True)
        t.start()

        client_cfg = VsockConfig(
            address=VsockAddress(cid=0, port=port),
            mtls_cert_path=str(test_certs["client_cert"]),
            mtls_key_path=str(test_certs["client_key"]),
            ca_cert_path=str(test_certs["ca_cert"]),
            timeout_ms=3_000,
        )
        client = VsockTransport(client_cfg, dev_mode=True)
        assert client.connect() is True
        t.join(timeout=3.0)

        assert accepted[0] is not None
        # Client cert was generated with CN="BlarAI Test Client".
        assert accepted[0].peer_cn == "BlarAI Test Client"

        client.close()
        accepted[0].close()
        listener.stop()


