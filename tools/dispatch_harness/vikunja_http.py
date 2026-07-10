"""The real urllib-to-loopback transport for the dispatch→Vikunja bridge (#749).

This is the ONE place the bridge opens a socket. It lives under ``tools/`` — the
sanctioned dev-side tier, deliberately outside the air-gap import scan
(``tests/security/test_no_external_egress.py`` scopes itself to the RUNTIME roots
``services/.../src``, ``shared/``, ``launcher/`` — never ``tools/``). Keeping the
raw ``urllib.request`` here is what lets ``shared/fleet/vikunja_bridge.py`` import
only ``urllib.parse`` and stay air-gap-clean: the sealed runtime never grows a
network client, and this dev-tooling module talks to the LOCAL Vikunja only.

Defense in depth: it re-asserts the loopback pin itself, so even the
socket-opening code refuses a non-loopback URL independently of the caller.
"""

from __future__ import annotations

import ipaddress
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Mapping


def _is_loopback(host: str | None) -> bool:
    if not host:
        return False
    h = host.strip().lower().strip("[]")
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return h == "localhost"


def urlopen_transport(
    method: str,
    url: str,
    body: Mapping[str, Any] | None,
    headers: Mapping[str, str],
    timeout_s: float,
) -> tuple[int, Any]:
    """Issue one bounded HTTP request to a LOOPBACK Vikunja and return
    ``(status_code, parsed_json | None)``.

    A non-2xx response comes back as its status code (the bridge client raises on
    ``>= 400``); connection/timeout errors propagate for the bridge's fail-soft to
    swallow. No retries — the 2 s cap is per call.
    """
    host = urllib.parse.urlparse(url).hostname
    if not _is_loopback(host):
        raise ValueError(
            f"vikunja_http refuses a non-loopback host {host!r} (loopback-pinned)."
        )

    data = json.dumps(dict(body)).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    for key, value in headers.items():
        req.add_header(key, value)

    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310 — loopback-pinned above
            raw = resp.read()
            status = int(resp.getcode() or 0)
    except urllib.error.HTTPError as exc:  # 4xx/5xx: hand back the status, let the client raise
        raw = exc.read()
        status = int(exc.code)

    parsed = json.loads(raw.decode("utf-8")) if raw else None
    return status, parsed
