"""Air-gap egress control (Tier 3 / #787 GO/NO-GO criterion #2).

BlarAI's runtime mandate is **zero external network dependency, fail-closed**
(`CLAUDE.md` §Security Constraints). Today that holds by *absence* — there is no
network code. This test converts "air-gapped because nothing reaches out" into
"air-gapped because a control proves it": the BlarAI **runtime** must import NO
external-network client library. A future PR that adds `requests`/`httpx`/a cloud
SDK to a runtime module trips this test in the default suite — fail-closed, no
human required.

ALLOWED (not flagged): `socket` (vsock host↔guest + named-pipe are LOCAL IPC),
`ssl` (mTLS over local certs), `urllib.parse` (URL parsing, no I/O), `http`'s
non-client members (`HTTPStatus`). FORBIDDEN: high-level external-network clients
and cloud/LLM SDKs (below).

**The one sanctioned egress door** (#598 air-gap-removal decision, 2026-06-10):
`shared/security/guarded_fetch.py` is THE single runtime module permitted to import
`httpx` — it is the Policy-Agent-gated external-fetch seam every web feature must go
through (ADR-027 + ADR-020). It is exempted from the forbidden-`httpx` scan by exact
path (`_EGRESS_DOOR_EXEMPTION`), and a companion test asserts NOTHING ELSE in the
runtime imports a network client — so the carve-out is exactly one file wide and the
import control still fires for every other module. Widening this exemption is a
deliberate, reviewable change to BlarAI's foundational property.

**Scope honesty (what this does NOT cover):** it is a static *import* scan of the
runtime source. It catches the realistic egress vectors (a network library being
imported) but not a raw `socket.connect()` crafted to an external address — the
vsock/named-pipe code legitimately uses `socket` for LOCAL IPC, so a raw-socket
guard would need runtime address inspection. That runtime egress guard is a
follow-on; this import control is the first, deterministic layer. (See the
security roadmap, `docs/security/SECURITY_ROADMAP_air_gap_removal.md` §1/§5.)
"""

from __future__ import annotations

import ast
import subprocess
import sys
import textwrap
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]

# Runtime source roots that MUST be air-gap-clean. (Dev/build tooling — tools/,
# tests/, the vendored openvino/ tree, MCP servers — is the two-tier carve-out:
# Claude/dev sessions may reach the network; the RUNTIME may not.)
_RUNTIME_ROOTS = (
    "services/assistant_orchestrator/src",
    "services/policy_agent/src",
    "services/ui_gateway/src",
    "services/ui_backend/src",
    "services/semantic_router/src",
    "services/cleaner/src",
    "services/cleaner/guest",
    "shared",
    "launcher",
)

# Top-level modules that are unambiguously external-network clients or
# cloud/remote SDKs — no place in an air-gapped runtime.
_FORBIDDEN_TOP_LEVEL = frozenset({
    "requests", "httpx", "aiohttp", "urllib3",
    "ftplib", "smtplib", "poplib", "imaplib", "telnetlib", "nntplib",
    "websocket", "websockets", "paramiko",
    "boto3", "botocore", "openai", "anthropic", "cohere",
})
# Dotted modules forbidden specifically (their top-level package is benign:
# urllib.parse and http.HTTPStatus are fine; urllib.request and http.client are
# the network parts; google.protobuf is fine, google.cloud is the SDK).
_FORBIDDEN_DOTTED = frozenset({
    "urllib.request", "http.client", "google.cloud",
})

# THE ONE SANCTIONED EGRESS DOOR (#598 air-gap-removal, 2026-06-10). This is the
# ONLY runtime module permitted to import a network client (httpx): it is the
# Policy-Agent-gated one-door external-fetch seam (shared/security/guarded_fetch.py,
# ADR-027 + ADR-020) that every web feature fetches through. The exemption is by
# exact repo-relative path and exactly one file wide; the companion test
# (test_exactly_one_runtime_module_imports_a_network_client) asserts nothing else
# imports a forbidden client, so the import control still fires everywhere else.
_EGRESS_DOOR_EXEMPTION = frozenset({
    "shared/security/guarded_fetch.py",
})


def _runtime_files() -> list[Path]:
    files: list[Path] = []
    for root in _RUNTIME_ROOTS:
        base = _REPO / root
        if not base.exists():
            continue
        for f in base.rglob("*.py"):
            parts = set(f.parts)
            if "tests" in parts or "__pycache__" in parts or f.name.startswith("test_"):
                continue
            files.append(f)
    return files


def _imported_modules(path: Path) -> set[str]:
    """Every module name an `import` / `from … import …` statement references."""
    mods: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod:
                mods.add(mod)
                for alias in node.names:
                    mods.add(f"{mod}.{alias.name}")  # `from urllib import request`
    return mods


def test_runtime_imports_no_external_network_library() -> None:
    """The air-gap, proven not assumed: no runtime module imports an
    external-network client or cloud SDK. Fail-closed — a new egress import here
    is a deliberate, reviewable change to BlarAI's foundational property."""
    runtime_files = _runtime_files()
    assert runtime_files, "no runtime source files found — root paths drifted?"

    violations: list[str] = []
    for f in runtime_files:
        rel = f.relative_to(_REPO).as_posix()
        if rel in _EGRESS_DOOR_EXEMPTION:
            # The one sanctioned egress door — permitted to import httpx (and only
            # httpx). See _EGRESS_DOOR_EXEMPTION; the companion test below proves the
            # carve-out is exactly one file wide.
            continue
        for mod in _imported_modules(f):
            top = mod.split(".", 1)[0]
            if top in _FORBIDDEN_TOP_LEVEL or mod in _FORBIDDEN_DOTTED:
                violations.append(f"{rel} -> import {mod}")

    assert not violations, (
        "BlarAI runtime imports an external-network library — the air-gap is "
        "broken (CLAUDE.md §Security Constraints). Offending imports:\n  "
        + "\n  ".join(sorted(violations))
    )


def test_exactly_one_runtime_module_imports_a_network_client() -> None:
    """The egress-door carve-out is exactly one file wide — and that file imports
    ONLY ``httpx`` (no other network client).

    Guards the exemption: if a second runtime module ever imports a forbidden
    network client, or if the egress door starts importing something other than
    ``httpx``, this fails — so the single-door property is itself locked, not just
    asserted by the exemption set. Fail-closed on a widened door."""
    runtime_files = _runtime_files()
    assert runtime_files, "no runtime source files found — root paths drifted?"

    importers: dict[str, set[str]] = {}
    for f in runtime_files:
        rel = f.relative_to(_REPO).as_posix()
        for mod in _imported_modules(f):
            top = mod.split(".", 1)[0]
            if top in _FORBIDDEN_TOP_LEVEL or mod in _FORBIDDEN_DOTTED:
                importers.setdefault(rel, set()).add(top)

    # Exactly the egress door imports a network client, and that client is httpx.
    assert set(importers) == set(_EGRESS_DOOR_EXEMPTION), (
        "network-client imports must be confined to the one sanctioned egress door "
        f"({sorted(_EGRESS_DOOR_EXEMPTION)}); found importers: "
        f"{ {k: sorted(v) for k, v in importers.items()} }"
    )
    door = next(iter(_EGRESS_DOOR_EXEMPTION))
    assert importers.get(door) == {"httpx"}, (
        f"the egress door {door!r} must import ONLY httpx; found {sorted(importers.get(door, set()))}"
    )


def test_egress_control_scans_a_meaningful_surface() -> None:
    """Guard the guard: if the runtime roots ever drift to empty (a refactor moved
    everything), the egress test above would vacuously pass. Assert it is actually
    scanning the core runtime."""
    files = _runtime_files()
    scanned = {f.relative_to(_REPO).as_posix() for f in files}
    assert any("assistant_orchestrator/src/entrypoint.py" in p for p in scanned), (
        "egress scan is not covering the AO entrypoint — roots drifted"
    )
    assert any("policy_agent/src" in p for p in scanned), (
        "egress scan is not covering the Policy Agent — roots drifted"
    )
    assert any("cleaner/src/pipeline.py" in p for p in scanned), (
        "egress scan is not covering the Cleaner pipeline — roots drifted"
    )
    assert any("cleaner/guest/parser_service.py" in p for p in scanned), (
        "egress scan is not covering the guest parser service (UC-003 Stage C) "
        "— the trafilatura fetch lock and import scans must hold over the "
        "guest-resident code too"
    )
    assert len(files) >= 20, f"egress scan surface suspiciously small: {len(files)} files"


# ---------------------------------------------------------------------------
# trafilatura fetch lock (ADR-030 §4 — the extraction-only posture)
# ---------------------------------------------------------------------------
#
# trafilatura is approved for EXTRACTION ONLY: `extract()`/`bare_extraction()`
# over bytes the caller already holds. Its fetching convenience layer
# (`trafilatura.downloads` with `fetch_url`/`fetch_response`) would bypass the
# single PA-gated egress door (`guarded_fetch.fetch_external`), the exfil
# screen, and the kill-switch in one call — so referencing it anywhere in the
# runtime fails the standing gate. The top-level import scan above does not
# catch this (trafilatura itself is a sanctioned import); this scan closes the
# library-internal fetch hole specifically.
#
# Scope honesty: this is a static AST check on imports, attribute accesses,
# and bare names. A `getattr(trafilatura, "fetch" + "_url")` style dynamic
# lookup would evade it — the armed runtime egress guard (socket + DNS deny,
# auto-trip) is the layer that catches anything dynamic.

_TRAFILATURA_FETCH_NAMES = frozenset({"fetch_url", "fetch_response"})


def _trafilatura_fetch_violations(path: Path) -> list[str]:
    rel = path.relative_to(_REPO).as_posix()
    violations: list[str] = []
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "trafilatura.downloads" or alias.name.startswith(
                    "trafilatura.downloads."
                ):
                    violations.append(f"{rel}:{node.lineno} -> import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == "trafilatura.downloads" or mod.startswith("trafilatura.downloads."):
                violations.append(f"{rel}:{node.lineno} -> from {mod} import ...")
            elif mod.startswith("trafilatura"):
                for alias in node.names:
                    if alias.name in _TRAFILATURA_FETCH_NAMES or alias.name == "downloads":
                        violations.append(
                            f"{rel}:{node.lineno} -> from {mod} import {alias.name}"
                        )
        elif isinstance(node, ast.Attribute):
            # ANY `<expr>.fetch_url` / `<expr>.fetch_response` in runtime code
            # is forbidden — these names exist for exactly one purpose.
            if node.attr in _TRAFILATURA_FETCH_NAMES:
                violations.append(f"{rel}:{node.lineno} -> attribute .{node.attr}")
            elif node.attr == "downloads" and isinstance(node.value, ast.Name) and (
                node.value.id == "trafilatura"
            ):
                violations.append(f"{rel}:{node.lineno} -> trafilatura.downloads")
        elif isinstance(node, ast.Name) and node.id in _TRAFILATURA_FETCH_NAMES:
            # A bare `fetch_url(...)` reference (post from-import or alias) —
            # also forbids *defining* runtime functions with these names,
            # which is the point: the names are reserved for the forbidden
            # thing and must not appear in the runtime at all.
            violations.append(f"{rel}:{node.lineno} -> name {node.id}")
    return violations


def test_runtime_never_uses_trafilatura_fetch() -> None:
    """The ADR-030 §4 regression lock: no runtime module imports
    trafilatura.downloads or references fetch_url / fetch_response. The
    Cleaner consumes trafilatura for extraction only; the URL fetch belongs
    to guarded_fetch.fetch_external (the single egress door) and nothing
    else."""
    runtime_files = _runtime_files()
    assert runtime_files, "no runtime source files found — root paths drifted?"

    violations: list[str] = []
    for f in runtime_files:
        violations.extend(_trafilatura_fetch_violations(f))

    assert not violations, (
        "BlarAI runtime references trafilatura's fetch machinery — the "
        "extraction-only posture (ADR-030 §4) is broken. Fetching belongs to "
        "shared/security/guarded_fetch.fetch_external ONLY. Offenders:\n  "
        + "\n  ".join(sorted(violations))
    )


def test_cleaner_pipeline_import_opens_no_sockets() -> None:
    """Import-time egress lock for the Cleaner (ADR-030 §4).

    Importing the trafilatura package unavoidably *loads* its downloads
    module (verified 2026-06-10: even `trafilatura.core` imports it), so an
    import-graph assertion cannot hold. The meaningful, enforceable property
    is behavioral: importing `services.cleaner.src.pipeline` — trafilatura,
    lxml, urllib3 machinery and all — must construct NO socket and resolve
    NO hostname. A fresh subprocess gets socket.socket and socket.getaddrinfo
    replaced with raising stubs BEFORE the import; any module-level network
    activity fails the import loudly."""
    probe = textwrap.dedent(
        """
        import socket as _socket

        class _NoSocket(_socket.socket):
            def __init__(self, *args, **kwargs):
                raise AssertionError(
                    "socket constructed during cleaner pipeline import"
                )

        def _no_resolve(*args, **kwargs):
            raise AssertionError(
                "DNS resolution attempted during cleaner pipeline import"
            )

        _socket.socket = _NoSocket
        _socket.getaddrinfo = _no_resolve

        import services.cleaner.src.pipeline as pipeline

        assert pipeline.CLEANER_VERSION
        print("IMPORT_OK")
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        cwd=str(_REPO),
        timeout=180,
    )
    assert result.returncode == 0, (
        "cleaner pipeline import attempted network activity or failed:\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "IMPORT_OK" in result.stdout


def test_guest_parser_service_import_opens_no_sockets() -> None:
    """Import-time egress lock for the guest parser (UC-003 Stage C).

    Same behavioral property as the pipeline lock above, over the
    guest-resident module: importing
    ``services.cleaner.guest.parser_service`` — which pulls trafilatura via
    the shared extraction stage — must construct NO socket and resolve NO
    hostname.  The service only creates sockets in its ``__main__`` listener
    path, never at import."""
    probe = textwrap.dedent(
        """
        import socket as _socket

        class _NoSocket(_socket.socket):
            def __init__(self, *args, **kwargs):
                raise AssertionError(
                    "socket constructed during guest parser import"
                )

        def _no_resolve(*args, **kwargs):
            raise AssertionError(
                "DNS resolution attempted during guest parser import"
            )

        _socket.socket = _NoSocket
        _socket.getaddrinfo = _no_resolve

        import services.cleaner.guest.parser_service as parser_service

        assert parser_service.DEFAULT_PARSER_PORT
        print("IMPORT_OK")
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        cwd=str(_REPO),
        timeout=180,
    )
    assert result.returncode == 0, (
        "guest parser import attempted network activity or failed:\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "IMPORT_OK" in result.stdout
