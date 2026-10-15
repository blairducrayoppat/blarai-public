"""In-container payload for the MXC PR #1406 loopback-proxy probe (#1746 item a).

Runs INSIDE the MXC process container. Opens TCP connections to a set of targets, sends a
marker request line to each, and also issues proxied HTTP requests through the stack-level
proxy paths (urllib via the environment, curl.exe, WinHTTP via ctypes). Writes one JSON file.
Success is judged by the host-side listener log, never by this file; this file supplies the
error codes for the destinations that cannot log on the host.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import socket
import subprocess
import time
import urllib.request
from ctypes import wintypes
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000


def _t() -> float:
    return time.perf_counter()


def tcp_probe(host: str, port: int, marker: str, timeout: float = 5.0) -> dict[str, object]:
    t0 = _t()
    rec: dict[str, object] = {"target": f"{host}:{port}"}
    try:
        with socket.create_connection((host, port), timeout=timeout) as s:
            rec["connected"] = True
            s.settimeout(timeout)
            s.sendall(f"GET /{marker} HTTP/1.0\r\nHost: {host}\r\nX-Probe-Marker: {marker}\r\n\r\n".encode())
            try:
                rec["reply"] = s.recv(512).decode("latin-1", "replace")
            except OSError as exc:
                rec["reply_error"] = repr(exc)
    except OSError as exc:
        rec.update(connected=False, error=type(exc).__name__, winerror=getattr(exc, "winerror", None),
                   detail=str(exc)[:120])
    rec["secs"] = round(_t() - t0, 3)
    return rec


def dns_probe(name: str) -> dict[str, object]:
    t0 = _t()
    try:
        return {"name": name, "resolved": sorted({a[4][0] for a in socket.getaddrinfo(name, 443, socket.AF_INET)}),
                "secs": round(_t() - t0, 3)}
    except OSError as exc:
        return {"name": name, "resolved": None, "error": type(exc).__name__, "winerror": getattr(exc, "winerror", None),
                "secs": round(_t() - t0, 3)}


def urllib_probe(url: str, timeout: float = 8.0) -> dict[str, object]:
    t0 = _t()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return {"url": url, "status": r.status, "body": r.read(200).decode("latin-1", "replace"),
                    "secs": round(_t() - t0, 3)}
    except Exception as exc:  # noqa: BLE001 - recorded
        return {"url": url, "error": type(exc).__name__, "detail": str(exc)[:160], "secs": round(_t() - t0, 3)}


def curl_probe(url: str) -> dict[str, object]:
    exe = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/curl.exe"
    t0 = _t()
    if not exe.exists():
        return {"url": url, "skipped": "curl.exe absent"}
    try:
        cp = subprocess.run([str(exe), "-sS", "-m", "8", "-i", url], capture_output=True, text=True, timeout=20,
                            creationflags=CREATE_NO_WINDOW, check=False)
        return {"url": url, "rc": cp.returncode, "out": cp.stdout[:300], "err": cp.stderr[:200],
                "secs": round(_t() - t0, 3)}
    except Exception as exc:  # noqa: BLE001 - recorded
        return {"url": url, "error": repr(exc)[:200], "secs": round(_t() - t0, 3)}


def winhttp_probe(host: str, path: str, access_type: int) -> dict[str, object]:
    """One GET through WinHTTP; access_type 0 = default (machine) proxy, 4 = automatic proxy."""
    t0 = _t()
    rec: dict[str, object] = {"host": host, "path": path, "access_type": access_type}
    try:
        wh = ctypes.WinDLL("winhttp", use_last_error=True)
        vp = ctypes.c_void_p
        wh.WinHttpOpen.restype = vp
        wh.WinHttpOpen.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
        wh.WinHttpConnect.restype = vp
        wh.WinHttpConnect.argtypes = [vp, wintypes.LPCWSTR, wintypes.WORD, wintypes.DWORD]
        wh.WinHttpOpenRequest.restype = vp
        wh.WinHttpOpenRequest.argtypes = [vp, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                          vp, wintypes.DWORD]
        wh.WinHttpSendRequest.argtypes = [vp, wintypes.LPCWSTR, wintypes.DWORD, vp, wintypes.DWORD, wintypes.DWORD, vp]
        wh.WinHttpReceiveResponse.argtypes = [vp, vp]
        wh.WinHttpQueryHeaders.argtypes = [vp, wintypes.DWORD, wintypes.LPCWSTR, vp, ctypes.POINTER(wintypes.DWORD), vp]
        wh.WinHttpSetTimeouts.argtypes = [vp, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        wh.WinHttpCloseHandle.argtypes = [vp]
        ses = wh.WinHttpOpen("mxc1406-probe", access_type, None, None, 0)
        if not ses:
            rec["error"] = f"WinHttpOpen {ctypes.get_last_error()}"
            return rec
        wh.WinHttpSetTimeouts(ses, 5000, 5000, 5000, 5000)
        con = wh.WinHttpConnect(ses, host, 80, 0)
        req = wh.WinHttpOpenRequest(con, "GET", path, None, None, None, 0) if con else None
        if not req:
            rec["error"] = f"connect/openrequest {ctypes.get_last_error()}"
        elif not wh.WinHttpSendRequest(req, None, 0, None, 0, 0, None):
            rec["error"] = f"WinHttpSendRequest {ctypes.get_last_error()}"
        elif not wh.WinHttpReceiveResponse(req, None):
            rec["error"] = f"WinHttpReceiveResponse {ctypes.get_last_error()}"
        else:
            buf = ctypes.create_unicode_buffer(32)
            sz = wintypes.DWORD(ctypes.sizeof(buf))
            ok = wh.WinHttpQueryHeaders(req, 19, None, buf, ctypes.byref(sz), None)  # STATUS_CODE
            rec["status"] = buf.value if ok else f"query-failed {ctypes.get_last_error()}"
    except Exception as exc:  # noqa: BLE001 - recorded
        rec["error"] = repr(exc)[:200]
    rec["secs"] = round(_t() - t0, 3)
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--lan-ip", required=True)
    ap.add_argument("--port", type=int, default=18099)
    ap.add_argument("--other-port", type=int, default=18100)
    a = ap.parse_args()
    t0 = _t()
    env = {k: v for k, v in os.environ.items() if k.lower() in ("http_proxy", "https_proxy", "no_proxy", "all_proxy")}
    res: dict[str, object] = {"tag": a.tag, "env_proxy": env}
    res["tcp"] = [
        tcp_probe("127.0.0.1", a.port, f"{a.tag}-direct-loop{a.port}"),
        tcp_probe("127.0.0.1", a.other_port, f"{a.tag}-direct-loop{a.other_port}"),
        tcp_probe(a.lan_ip, a.port, f"{a.tag}-direct-lan{a.port}"),
        tcp_probe("1.1.1.1", 443, f"{a.tag}-direct-1.1.1.1"),
    ]
    res["dns"] = dns_probe("example.com")
    res["tcp"].append(tcp_probe("example.com", 443, f"{a.tag}-direct-example"))  # type: ignore[union-attr]
    base = "mxc-proxy-probe.invalid"
    res["urllib_env_proxy"] = urllib_probe(f"http://{base}/{a.tag}-urllib")
    res["curl"] = curl_probe(f"http://{base}/{a.tag}-curl")
    res["winhttp_default"] = winhttp_probe(base, f"/{a.tag}-winhttp0", 0)
    res["winhttp_automatic"] = winhttp_probe(base, f"/{a.tag}-winhttp4", 4)
    res["total_secs"] = round(_t() - t0, 3)
    a.out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps({"tag": a.tag, "tcp": [(r["target"], r.get("connected"), r.get("error")) for r in res["tcp"]]}))  # type: ignore[union-attr]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
