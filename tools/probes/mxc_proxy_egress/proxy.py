"""Forwarding HTTP proxy and logging TCP listeners for the MXC loopback-proxy egress probe.

What this measures: nothing by itself. It supplies the host-side instruments the probe judges from:
  ForwardingProxy  a real forwarding HTTP proxy (stdlib): accepts absolute-form requests on 127.0.0.1,
                   forwards them to an allowlisted loopback target, logs every request it sees.
  ProbeListener    a throwaway TCP/HTTP listener that logs every connection (peer, request line, marker header).
Both bind 127.0.0.1 only, exclusively (SO_EXCLUSIVEADDRUSE on Windows, so a port already held, even by a
SO_REUSEADDR socket, refuses the bind).

How to run: imported by run_probe.py. Standalone smoke: `python -I proxy.py --port 18110 --allow 18111`.
What it writes: nothing to disk; log entries are returned to the caller as dicts in memory.
The proxy binds 127.0.0.1 only and forwards only to 127.0.0.1 on an explicit port allowlist (an empty
allowlist forwards nothing); it is never an open relay.

NOT MEASURED (the probe as a whole): any build other than the one(s) run; the WFP filter count under a standard token (unreadable); behaviour on a host
whose --probe reports host-loopback ingress unsupported (the earlier 26200.9457 condition); an identity-scoped proxy (allowedProxyPeer); the session-isolation backend; UDP, ICMP or DNS egress under the
proxy policy; host-to-container ingress; anything about other sandboxes or projects. This module
additionally does not implement CONNECT (no HTTPS tunnelling through the proxy).
"""

from __future__ import annotations

import argparse
import http.client
import socket
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

Entry = dict[str, object]


def exclusive_socket() -> socket.socket:
    """TCP socket that refuses to share its port (SO_EXCLUSIVEADDRUSE where the platform has it)."""
    s = socket.socket()
    opt = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
    if opt is not None:
        s.setsockopt(socket.SOL_SOCKET, opt, 1)
    return s


class ExclusiveHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self) -> None:
        opt = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if opt is not None:
            self.socket.setsockopt(socket.SOL_SOCKET, opt, 1)
        super().server_bind()


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def marker_of(lines: list[str]) -> str:
    """Value of the X-Probe-Marker header among raw header lines, or ''."""
    return next((ln.split(":", 1)[1].strip() for ln in lines if ln.lower().startswith("x-probe-marker:")), "")


class ProbeListener:
    """Logs every connection (timestamp, peer, request line, marker header) and answers 200."""

    def __init__(self, name: str, host: str, port: int, log: list[Entry], lock: threading.Lock) -> None:
        self.name, self.host, self.port, self.log, self.lock = name, host, port, log, lock
        if host != "127.0.0.1":
            raise ValueError("probe listeners bind 127.0.0.1 only")
        self.sock = exclusive_socket()
        self.sock.bind((host, port))
        self.sock.listen(16)
        self.alive = True
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self) -> None:
        while self.alive:
            try:
                conn, peer = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn, peer), daemon=True).start()

    def _handle(self, conn: socket.socket, peer: tuple[str, int]) -> None:
        ts = now_iso()
        data = b""
        conn.settimeout(2.0)
        try:
            while b"\r\n\r\n" not in data and len(data) < 4096:
                chunk = conn.recv(1024)
                if not chunk:
                    break
                data += chunk
        except OSError:
            pass
        lines = data.decode("latin-1", "replace").split("\r\n")
        entry: Entry = {"ts": ts, "listener": self.name, "bind": f"{self.host}:{self.port}",
                        "peer": f"{peer[0]}:{peer[1]}", "request_line": lines[0][:200],
                        "marker": marker_of(lines), "bytes": len(data)}
        with self.lock:
            self.log.append(entry)
        try:
            body = f"listener-{self.name}-ok".encode()
            conn.sendall(b"HTTP/1.0 200 OK\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % len(body) + body)
        except OSError:
            pass
        conn.close()

    def close(self) -> None:
        self.alive = False
        self.sock.close()


class ForwardingProxy:
    """Forwarding HTTP proxy on 127.0.0.1. One log entry per request, recorded before the reply is sent."""

    def __init__(self, port: int, allowed_ports: set[int], log: list[Entry], lock: threading.Lock,
                 host: str = "127.0.0.1") -> None:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *args: object) -> None:  # noqa: D401 - silence stderr access log
                return

            def _forward(self) -> None:
                outer._forward(self)

            do_GET = do_POST = do_HEAD = do_PUT = do_DELETE = do_OPTIONS = _forward

            def do_CONNECT(self) -> None:  # noqa: N802
                outer._record(self, "refused-connect", None)
                self.send_error(405, "CONNECT not implemented")

        self.log, self.lock, self.allowed_ports = log, lock, set(allowed_ports)
        self.host, self.port = host, port
        if host != "127.0.0.1":
            raise ValueError("the proxy binds 127.0.0.1 only")
        self.server = ExclusiveHTTPServer((host, port), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def _record(self, h: BaseHTTPRequestHandler, outcome: str, status: int | None) -> None:
        lines = [f"{k}: {v}" for k, v in h.headers.items()]
        entry: Entry = {"ts": now_iso(), "listener": "proxy", "bind": f"{self.host}:{self.port}",
                        "peer": f"{h.client_address[0]}:{h.client_address[1]}", "method": h.command,
                        "target": h.path[:300], "marker": marker_of(lines), "outcome": outcome, "status": status}
        with self.lock:
            self.log.append(entry)

    def _forward(self, h: BaseHTTPRequestHandler) -> None:
        parts = urlsplit(h.path)
        if parts.scheme != "http" or parts.hostname != "127.0.0.1" or (parts.port or 80) not in self.allowed_ports:
            self._record(h, "refused-target", None)
            h.send_error(403, "target not allowlisted")
            return
        length = int(h.headers.get("Content-Length") or 0)
        body = h.rfile.read(length) if length else None
        fwd = {k: v for k, v in h.headers.items() if k.lower() not in ("proxy-connection", "connection")}
        try:
            conn = http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=5)
            conn.request(h.command, (parts.path or "/") + (f"?{parts.query}" if parts.query else ""), body, fwd)
            resp = conn.getresponse()
            payload = resp.read()
        except OSError as exc:
            self._record(h, f"upstream-error:{type(exc).__name__}", None)
            h.send_error(502, "upstream failure")
            return
        self._record(h, "forwarded", resp.status)
        h.send_response(resp.status)
        h.send_header("Content-Length", str(len(payload)))
        h.send_header("Connection", "close")
        h.end_headers()
        if h.command != "HEAD":
            h.wfile.write(payload)
        conn.close()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def main() -> int:
    ap = argparse.ArgumentParser(description="Standalone smoke run of the forwarding proxy.")
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--allow", type=int, action="append", default=[], help="allowlisted loopback target port")
    ap.add_argument("--seconds", type=float, default=30.0)
    a = ap.parse_args()
    log: list[Entry] = []
    px = ForwardingProxy(a.port, set(a.allow), log, threading.Lock())
    time.sleep(a.seconds)
    px.close()
    for e in log:
        print(e)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
