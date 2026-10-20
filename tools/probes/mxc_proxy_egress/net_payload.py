"""In-container payload for the MXC loopback-proxy egress probe (also imported by the harness for the unfenced controls).

What this measures, from inside the container, in one run:
  B2  three HTTP requests THROUGH the configured proxy to a second loopback listener (instrument control).
  B3  one direct TCP connect to that second loopback listener, not through the proxy.
  B4  one connect-only attempt to a real LAN peer, the default gateway, on a port an unfenced connect reached
      (i), and one connect-only attempt to 1.1.1.1:443 (ii). Neither has a host-side listener.
The payload also records its own token (user SID, IsAppContainer, AppContainer SID, integrity SID, elevation) so the
record shows what the container ran as.
B2 and B3 requests carry the run tag in their path and in an X-Probe-Marker header, shaped `<tag>-<kind>-<n>`
with kind in b2, b3, b5a. Reach for B2 and B3 is judged from the HOST-SIDE listener logs; this file's JSON
supplies the error codes for B4(i) and B4(ii), which have no host-side listener. A gateway port of 0 means no
port was reachable unfenced: B4(i) is then skipped and recorded as such.

Hold point (variant 4, opt-in): with --hold-ready R --hold-release X the payload, after its probes, writes R (its pid,
the time and its token report) and then waits until the file X exists or --hold-max-secs pass, so the host can take a
WFP capture while this process is provably alive. The result records whether it was released or timed out.

How to run: launched by run_probe.py inside the container:
  python -I net_payload.py --tag T --out result.json --gateway-ip A.B.C.D --gateway-port R --proxy-port P --target-port Q
                           [--hold-ready R --hold-release X --hold-max-secs N]
What it writes: one JSON result file (--out) and a one-line JSON summary on stdout.

NOT MEASURED: any build other than the one(s) run; the WFP filter count under a standard token (unreadable);
behaviour on a host whose --probe reports host-loopback
ingress unsupported (the earlier 26200.9457 condition); an identity-scoped proxy
(allowedProxyPeer); the session-isolation backend; UDP, ICMP or DNS egress under the proxy policy;
host-to-container ingress (the doc's own open limitation); nono under MXC; anything about the fork or any
other sandbox. Also not measured here: IPv6, HTTPS or CONNECT through the proxy, other destination ports.
"""

from __future__ import annotations

import argparse
import ctypes
import http.client
import json
import os
import socket
import time
from ctypes import wintypes
from pathlib import Path

B2_REQUESTS = 3


def _t() -> float:
    return time.perf_counter()


def token_report() -> dict[str, object]:
    """The token this process runs as: user SID, IsAppContainer, AppContainer SID, integrity level SID, elevation.
    A field that cannot be read is None (never a default that looks like a pass); a failed read is carried in `error`."""
    out: dict[str, object] = {"user_sid": None, "is_appcontainer": None, "appcontainer_sid": None,
                              "integrity_sid": None, "elevated": None}
    try:
        adv = ctypes.WinDLL("advapi32", use_last_error=True)
        kern = ctypes.WinDLL("kernel32", use_last_error=True)
        kern.GetCurrentProcess.restype = ctypes.c_void_p
        kern.CloseHandle.argtypes = [ctypes.c_void_p]
        kern.LocalFree.argtypes = [ctypes.c_void_p]
        adv.OpenProcessToken.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
        adv.GetTokenInformation.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                            ctypes.POINTER(wintypes.DWORD)]
        adv.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
        token = ctypes.c_void_p()
        if not adv.OpenProcessToken(kern.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
            out["error"] = f"OpenProcessToken failed ({ctypes.get_last_error()})"
            return out

        def query(info_class: int, size: int = 1024) -> bytes | None:
            buf, got = ctypes.create_string_buffer(size), wintypes.DWORD(0)
            return buf.raw[:got.value] if adv.GetTokenInformation(token, info_class, buf, size, ctypes.byref(got)) else None

        def sid_text(info_class: int) -> str | None:
            """The SID a token-information structure points to; the buffer it points into stays alive here."""
            buf, got = ctypes.create_string_buffer(1024), wintypes.DWORD(0)
            if not adv.GetTokenInformation(token, info_class, buf, 1024, ctypes.byref(got)) or got.value < 8:
                return None
            text = wintypes.LPWSTR()
            if not adv.ConvertSidToStringSidW(ctypes.c_void_p(int.from_bytes(buf.raw[:8], "little")), ctypes.byref(text)):
                return None
            value = text.value
            kern.LocalFree(ctypes.cast(text, ctypes.c_void_p))
            return value

        try:
            out["user_sid"] = sid_text(1)                       # TokenUser
            ac = query(29, 4)                                          # TokenIsAppContainer
            out["is_appcontainer"] = bool(int.from_bytes(ac[:4], "little")) if ac and len(ac) >= 4 else None
            out["appcontainer_sid"] = sid_text(31) if out["is_appcontainer"] else None   # TokenAppContainerSid
            out["integrity_sid"] = sid_text(25)                 # TokenIntegrityLevel
            el = query(20, 4)                                          # TokenElevation
            out["elevated"] = bool(int.from_bytes(el[:4], "little")) if el and len(el) >= 4 else None
        finally:
            kern.CloseHandle(token)
    except (AttributeError, OSError) as exc:
        out["error"] = repr(exc)
    return out


def tcp_probe(host: str, port: int, marker: str | None, timeout: float = 5.0) -> dict[str, object]:
    """Connect; if `marker` is given, send a marked request. `marker=None` is connect-only."""
    t0 = _t()
    rec: dict[str, object] = {"target": f"{host}:{port}", "marker": marker}
    try:
        with socket.create_connection((host, port), timeout=timeout) as s:
            rec["connected"] = True
            if marker is not None:
                s.settimeout(timeout)
                s.sendall(f"GET /{marker} HTTP/1.0\r\nHost: {host}\r\nX-Probe-Marker: {marker}\r\n\r\n".encode())
                try:
                    rec["reply"] = s.recv(512).decode("latin-1", "replace")
                except OSError as exc:
                    rec["reply_error"] = repr(exc)
    except OSError as exc:
        rec.update(connected=False, error=type(exc).__name__, winerror=getattr(exc, "winerror", None),
                   errno=getattr(exc, "errno", None), detail=str(exc)[:120])
    rec["secs"] = round(_t() - t0, 3)
    return rec


def http_via_proxy(proxy_host: str, proxy_port: int, target_host: str, target_port: int, marker: str,
                   timeout: float = 8.0) -> dict[str, object]:
    """One GET sent to the proxy in absolute-form, the way an HTTP client configured with a proxy sends it."""
    t0 = _t()
    rec: dict[str, object] = {"proxy": f"{proxy_host}:{proxy_port}", "target": f"{target_host}:{target_port}",
                              "marker": marker}
    try:
        conn = http.client.HTTPConnection(proxy_host, proxy_port, timeout=timeout)
        conn.request("GET", f"http://{target_host}:{target_port}/{marker}",
                     headers={"Host": f"{target_host}:{target_port}", "X-Probe-Marker": marker})
        resp = conn.getresponse()
        rec.update(status=resp.status, body=resp.read(200).decode("latin-1", "replace"))
        conn.close()
    except OSError as exc:
        rec.update(error=type(exc).__name__, winerror=getattr(exc, "winerror", None), detail=str(exc)[:160])
    rec["secs"] = round(_t() - t0, 3)
    return rec


def run_states(tag: str, gateway_ip: str, gateway_port: int, proxy_port: int, target_port: int) -> dict[str, object]:
    res: dict[str, object] = {"tag": tag, "token": token_report()}
    res["b2"] = [http_via_proxy("127.0.0.1", proxy_port, "127.0.0.1", target_port, f"{tag}-b2-{i}")
                 for i in range(1, B2_REQUESTS + 1)]
    res["b3"] = tcp_probe("127.0.0.1", target_port, f"{tag}-b3-1")
    res["b4i"] = tcp_probe(gateway_ip, gateway_port, None) if gateway_port else {"skipped": "no gateway port"}
    res["b4ii"] = tcp_probe("1.1.1.1", 443, None)
    return res


def hold_for_release(ready: Path, release: Path, max_secs: float, res: dict[str, object]) -> None:
    """Write `ready` (pid, time, token), then wait for `release` to exist or `max_secs` to pass. Records the outcome
    in res['hold']; a ready file that cannot be written is recorded, never skipped silently."""
    info: dict[str, object] = {"pid": os.getpid(), "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                               "token": res.get("token")}
    t0 = _t()
    try:
        tmp = ready.with_suffix(".tmp")
        tmp.write_text(json.dumps(info), encoding="utf-8")
        tmp.replace(ready)
    except OSError as exc:
        res["hold"] = {"ready_written": False, "error": repr(exc)}
        return
    released = False
    while _t() - t0 < max_secs:
        if release.exists():
            released = True
            break
        time.sleep(0.2)
    res["hold"] = {"ready_written": True, "released": released, "held_secs": round(_t() - t0, 3), "pid": os.getpid()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--gateway-ip", required=True)
    ap.add_argument("--gateway-port", type=int, required=True)
    ap.add_argument("--proxy-port", type=int, required=True)
    ap.add_argument("--target-port", type=int, required=True)
    ap.add_argument("--hold-ready", type=Path, default=None)
    ap.add_argument("--hold-release", type=Path, default=None)
    ap.add_argument("--hold-max-secs", type=float, default=100.0)
    a = ap.parse_args()
    t0 = _t()
    res = run_states(a.tag, a.gateway_ip, a.gateway_port, a.proxy_port, a.target_port)
    res["env_proxy"] = {k: v for k, v in os.environ.items()
                        if k.lower() in ("http_proxy", "https_proxy", "no_proxy", "all_proxy")}
    res["total_secs"] = round(_t() - t0, 3)
    if a.hold_ready is not None and a.hold_release is not None:
        hold_for_release(a.hold_ready, a.hold_release, a.hold_max_secs, res)
    a.out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps({"tag": a.tag, "b2_status": [r.get("status") for r in res["b2"]],  # type: ignore[union-attr]
                      "b3": res["b3"].get("connected"), "b4i": res["b4i"].get("connected"),  # type: ignore[union-attr]
                      "b4ii": res["b4ii"].get("connected")}))  # type: ignore[union-attr]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
