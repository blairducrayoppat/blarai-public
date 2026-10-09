# enforces-rule: critical_rules.you-are-not-blarai -- runtime imports no network or cloud client
# enforces-rule: identity_split.failure_modes.leaking-the-workshop-into-the-product -- runtime imports no network or cloud client
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

# Runtime source roots that MUST be air-gap-clean: the three runtime trees
# THEMSELVES, not an enumeration of directories inside them. (Dev/build tooling
# — tools/, tests/, the vendored openvino/ tree, MCP servers — is the two-tier
# carve-out: Claude/dev sessions may reach the network; the RUNTIME may not.)
#
# This was a list of nine specific directories (#1585). A list of what to LOOK
# AT is a blocklist of everything unlisted, which is backwards for a control:
# it missed services/ui_shell/src and services/voice/src — both shipped runtime
# — and any NEW service would have been invisible to it from the day it was
# created, silently, with the suite still green. Naming the trees instead means
# a new service is covered the moment it exists.
_RUNTIME_ROOTS = (
    "services",
    "shared",
    "launcher",
)

# Directory names excluded ANYWHERE under a runtime root. Test trees are the
# dev tier (a test may legitimately import httpx to prove the door works), and
# __pycache__ holds no source. Kept deliberately short: every name here is a
# hole in the scan, so a new one needs a reason in the same change.
_EXCLUDED_DIR_NAMES = frozenset({"tests", "__pycache__"})

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

#: The forbidden sets, pinned. Shrinking either one silently narrows the control
#: to whatever is left, and the existing cross-file drift lock asserts a SUBSET —
#: which passes on shrinkage (#1585 review, finding 3). Reducing the set to
#: ``{"httpx"}`` left the entire security tier green. Pinned by EQUALITY here so
#: a removal is a deliberate, reviewable edit in two places rather than one.
_EXPECTED_FORBIDDEN_TOP_LEVEL = frozenset({
    "requests", "httpx", "aiohttp", "urllib3",
    "ftplib", "smtplib", "poplib", "imaplib", "telnetlib", "nntplib",
    "websocket", "websockets", "paramiko",
    "boto3", "botocore", "openai", "anthropic", "cohere",
})
_EXPECTED_FORBIDDEN_DOTTED = frozenset({
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


def _runtime_files(repo: Path | None = None) -> list[Path]:
    """Every runtime source file under ``repo`` (default: this repository).

    ``repo`` is a parameter so the scan can be pointed at a SYNTHETIC tree and
    shown to fail (#1585). A control that has only ever been observed passing
    cannot be told apart from one that cannot reach its subject, which is
    security_by_design principle 12 applied to this file's own scan.

    The default resolves at CALL time rather than being bound to ``_REPO`` in
    the signature. A default argument is evaluated once at import, so the
    frozen form silently scanned the wrong tree — and returned zero files —
    whenever this module was loaded from anywhere but its real home. Zero files
    is the reading that must never be quietly wrong here.
    """
    repo = _REPO if repo is None else repo
    files: list[Path] = []
    for root in _RUNTIME_ROOTS:
        base = repo / root
        if not base.exists():
            continue
        for f in base.rglob("*.py"):
            # RELATIVE to the repo, not absolute: f.parts on an absolute path
            # includes every ancestor of the checkout, so a repository (or a git
            # worktree, which is where this one lives) sitting under a directory
            # named `tests` or `__pycache__` silently scanned ZERO files.
            if _EXCLUDED_DIR_NAMES & set(f.relative_to(repo).parts):
                continue
            if f.name.startswith("test_"):
                continue
            files.append(f)
    return files


def _network_client_importers(repo: Path | None = None) -> dict[str, set[str]]:
    """Map ``repo``-relative path -> the forbidden top-level modules it imports.

    The egress door exemption is NOT applied here. Both callers need the raw
    picture: one subtracts the door, the other asserts the door is the only
    entry. Baking the exemption in would make the second test tautological.
    """
    repo = _REPO if repo is None else repo
    importers: dict[str, set[str]] = {}
    for f in _runtime_files(repo):
        rel = f.relative_to(repo).as_posix()
        for mod in _imported_modules(f):
            top = mod.split(".", 1)[0]
            if top in _FORBIDDEN_TOP_LEVEL or mod in _FORBIDDEN_DOTTED:
                importers.setdefault(rel, set()).add(top)
    return importers


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


def _unexempted_violations(repo: Path | None = None) -> list[str]:
    """Every forbidden import under ``repo`` EXCEPT the sanctioned egress door.

    Extracted so the gate's primary test and its off-test run the SAME code. It
    used to be a loop inside the test, hardcoded to ``_REPO`` — which meant the
    one assertion the standing gate actually runs could not be pointed at a
    synthetic tree, and replacing its loop body with ``for f in []`` left the
    entire security tier green (#1585 review, finding 1). The extracted
    collector existed and the test that mattered did not call it: a correct
    mechanism with no consumer, in the file written to retire that defect.
    """
    repo = _REPO if repo is None else repo
    violations: list[str] = []
    for rel, mods in _network_client_importers(repo).items():
        if rel in _EGRESS_DOOR_EXEMPTION:
            # The one sanctioned egress door — permitted to import httpx (and
            # only httpx). The companion test proves the carve-out is exactly
            # one file wide, so excusing it here is not excusing a second.
            continue
        for mod in sorted(mods):
            violations.append(f"{rel} -> import {mod}")
    return sorted(violations)


def _violation_message(violations: list[str]) -> str:
    """The failure text an operator actually reads. A control that fails without
    naming what broke sends the next person hunting, so the message is part of
    the control and is asserted as such."""
    return (
        "BlarAI runtime imports an external-network library — the air-gap is "
        "broken (CLAUDE.md §Security Constraints). Offending imports:\n  "
        + "\n  ".join(violations)
    )


def test_runtime_imports_no_external_network_library() -> None:
    """The air-gap, proven not assumed: no runtime module imports an
    external-network client or cloud SDK. Fail-closed — a new egress import here
    is a deliberate, reviewable change to BlarAI's foundational property."""
    assert _runtime_files(), "no runtime source files found — root paths drifted?"
    violations = _unexempted_violations()
    assert not violations, _violation_message(violations)


def test_exactly_one_runtime_module_imports_a_network_client() -> None:
    """The egress-door carve-out is exactly one file wide — and that file imports
    ONLY ``httpx`` (no other network client).

    Guards the exemption: if a second runtime module ever imports a forbidden
    network client, or if the egress door starts importing something other than
    ``httpx``, this fails — so the single-door property is itself locked, not just
    asserted by the exemption set. Fail-closed on a widened door."""
    runtime_files = _runtime_files()
    assert runtime_files, "no runtime source files found — root paths drifted?"

    importers = _network_client_importers()

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
    # The two trees the enumerated root list silently omitted until #1585.
    # Named individually rather than counted, because a count rises on its own
    # and would have hidden exactly this omission.
    assert any("ui_shell/src" in p for p in scanned), (
        "egress scan is not covering the Textual UI shell — it was missing from "
        "the enumerated root list for the whole life of that list"
    )
    assert any("voice/src" in p for p in scanned), (
        "egress scan is not covering the voice service — same omission"
    )
    # ONE ANCHOR PER ROOT. Every assertion above names a path inside `services/`,
    # so deleting "launcher" or "shared" from _RUNTIME_ROOTS passed the whole
    # security tier (#1585 review, finding 2) — and launcher/__main__.py is where
    # the egress guard is ARMED and this very screen is WIRED. An unanchored root
    # is the same invisible-root defect this file was just rewritten to retire,
    # one level up.
    assert any(p == "launcher/__main__.py" for p in scanned), (
        "egress scan is not covering launcher/__main__.py — the module that arms "
        "the egress guard and wires the exfil screen. The `launcher` root has "
        "drifted out of _RUNTIME_ROOTS"
    )
    assert any(p == "shared/timeout_registry.py" for p in scanned), (
        "egress scan is not covering top-level shared/ modules — either the "
        "`shared` root drifted, or the glob stopped matching files directly "
        "under a root (rglob('*/*.py') rather than rglob('*.py') loses exactly "
        "these and nothing else complains)"
    )
    # A floor near the REAL surface, not a token one. 20 against an actual 240
    # permitted 92% of the scan to disappear silently. Deliberately not an exact
    # equality: files are added legitimately and a brittle count trains people to
    # bump numbers without reading. The gap is wide enough to absorb ordinary
    # growth and narrow enough that losing any ROOT trips it.
    assert len(files) >= 200, (
        f"egress scan surface collapsed to {len(files)} files (expected ~240) — "
        "a runtime root or a glob has drifted"
    )


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


# ---------------------------------------------------------------------------
# THE SCAN'S OWN OFF-TEST (#1585)
# ---------------------------------------------------------------------------
class TestTheScanIsTestedOff:
    """The scan above has only ever been observed passing.

    A green result is consistent with two worlds: the runtime is clean, or the
    scan cannot see a violation. Nothing in this file distinguished them. These
    tests plant a real second importer in a synthetic tree and require the scan
    to FAIL and to NAME it, with the same tree minus the plant as the control —
    one condition varied, which is what makes either result evidence.

    Synthetic, not the real tree: proving the control fires must not require
    committing an httpx import to the runtime.
    """

    #: Where the planted violators live, repo-relative. Named once so the
    #: assertions cannot drift from the fixture.
    VIOLATOR = "services/newly_added_service/src/worker.py"
    SECOND_VIOLATOR = "services/another_new_service/src/client.py"
    DOTTED_VIOLATOR = "services/another_new_service/src/fetcher.py"

    @staticmethod
    def _tree(root: Path, *, plant_violator: bool) -> None:
        """A minimal runtime tree in the shape the real repo uses.

        Includes the sanctioned door so the exemption is exercised too — a
        violator test against a tree with no door would not show that the door
        is what is being excused. The door path is DERIVED from
        ``_EGRESS_DOOR_EXEMPTION`` rather than written literally, so moving the
        door moves the fixture with it instead of breaking the ON control for a
        reason unrelated to what it measures.
        """
        door_rel = next(iter(_EGRESS_DOOR_EXEMPTION))
        door = root / door_rel
        door.parent.mkdir(parents=True, exist_ok=True)
        door.write_text("import httpx\n", encoding="utf-8")

        # A service that did not exist when the old root list was written.
        svc = root / "services" / "newly_added_service" / "src"
        svc.mkdir(parents=True)
        (svc / "worker.py").write_text(
            "import httpx\n" if plant_violator else "import json\n",
            encoding="utf-8",
        )

        # A SECOND violator, in a SECOND service, and a THIRD using a different
        # import FORM and a different forbidden set. One plant could not tell
        # "finds a violator" from "finds every violator", and a collector that
        # returned after its first hit left the security tier green. One plant of
        # `import httpx` also left the entire ast.ImportFrom branch and all of
        # _FORBIDDEN_DOTTED measured by nothing — and `from httpx import
        # AsyncClient` is the idiom a real developer writes.
        svc2 = root / "services" / "another_new_service" / "src"
        svc2.mkdir(parents=True)
        (svc2 / "client.py").write_text(
            "from httpx import AsyncClient\n" if plant_violator else "from json import loads\n",
            encoding="utf-8",
        )
        (svc2 / "fetcher.py").write_text(
            "from urllib import request\n" if plant_violator else "from urllib import parse\n",
            encoding="utf-8",
        )

        # TWO dev-tier plants, because there are TWO exclusion rules and each
        # needs a plant only IT can catch. A file named test_*.py inside tests/
        # is excluded twice over, so it proves neither rule works — the first
        # version of this fixture planted exactly that, and a mutant that
        # deleted the whole directory rule survived it.
        tests_dir = root / "services" / "newly_added_service" / "tests"
        tests_dir.mkdir(parents=True)
        # Caught ONLY by the directory-name rule (the filename is unremarkable).
        (tests_dir / "helpers.py").write_text("import httpx\n", encoding="utf-8")
        # Caught ONLY by the filename rule (it sits in the src tree).
        (svc / "test_worker.py").write_text("import httpx\n", encoding="utf-8")

    def test_a_planted_second_importer_is_FOUND_AND_NAMED(self, tmp_path: Path) -> None:
        """OFF-test: with a violator present, the scan must fail and name it."""
        self._tree(tmp_path, plant_violator=True)
        importers = _network_client_importers(tmp_path)

        assert self.VIOLATOR in importers, (
            "the scan did not see a planted httpx importer in a NEW service "
            f"directory — it found only {sorted(importers)}. The scan's roots "
            "do not cover where a real new module would live."
        )
        assert importers[self.VIOLATOR] == {"httpx"}

        # The exemption must not swallow it: subtracting the door still leaves
        # the violators behind.
        assert set(importers) - _EGRESS_DOOR_EXEMPTION == {
            self.VIOLATOR, self.SECOND_VIOLATOR, self.DOTTED_VIOLATOR
        }

    def test_EVERY_violator_is_found_not_merely_the_first(self, tmp_path: Path) -> None:
        """Three violators in two services, so "finds one" and "finds all" differ.

        With a single plant those two are the same observation, and a collector
        that returned after its first hit left the whole security tier green
        (#1585 review, finding 5).
        """
        self._tree(tmp_path, plant_violator=True)
        importers = _network_client_importers(tmp_path)
        found = set(importers) - _EGRESS_DOOR_EXEMPTION
        assert found == {self.VIOLATOR, self.SECOND_VIOLATOR, self.DOTTED_VIOLATOR}, (
            f"the scan reported {len(found)} of 3 planted violators: {sorted(found)}"
        )

    def test_the_from_import_FORM_is_caught_not_only_plain_import(
        self, tmp_path: Path
    ) -> None:
        """``from httpx import AsyncClient`` — an ast.ImportFrom, not an ast.Import.

        The fixture only ever planted `import httpx`, so the entire ImportFrom
        branch of `_imported_modules` was measured by nothing and could be made
        dead without a single failure. It is the idiom a real developer writes.
        """
        self._tree(tmp_path, plant_violator=True)
        importers = _network_client_importers(tmp_path)
        assert importers.get(self.SECOND_VIOLATOR) == {"httpx"}, (
            "a `from httpx import ...` was not detected — the ImportFrom branch "
            f"is not firing. Found: {sorted(importers)}"
        )

    def test_a_DOTTED_forbidden_module_is_caught(self, tmp_path: Path) -> None:
        """``from urllib import request`` — forbidden by DOTTED name only.

        `urllib` is benign (`urllib.parse` is pure parsing) and `urllib.request`
        is the network part, which is why the dotted set exists. Nothing exercised
        it: emptying `_FORBIDDEN_DOTTED` passed. The clean control plants
        `from urllib import parse` in the same file, so only the dotted rule can
        produce the difference.
        """
        self._tree(tmp_path, plant_violator=True)
        importers = _network_client_importers(tmp_path)
        assert self.DOTTED_VIOLATOR in importers, (
            "`from urllib import request` was not flagged — the dotted-module "
            f"rule is not firing. Found: {sorted(importers)}"
        )

    def test_the_OPERATOR_FACING_MESSAGE_names_the_violating_paths(
        self, tmp_path: Path
    ) -> None:
        """The message is part of the control, asserted on the REAL message.

        The first version of this rebuilt its own subject from the dict it had
        just asserted contained the violator, so it could not be false, and the
        message the gate actually prints was exercised by nothing (#1585 review,
        finding 6). This calls the production message builder.
        """
        self._tree(tmp_path, plant_violator=True)
        violations = _unexempted_violations(tmp_path)
        assert violations, "no violations to report — the fixture did not plant"
        message = _violation_message(violations)
        for path in (self.VIOLATOR, self.SECOND_VIOLATOR, self.DOTTED_VIOLATOR):
            assert path in message, (
                f"the failure an operator reads does not name {path}:\n{message}"
            )
        assert next(iter(_EGRESS_DOOR_EXEMPTION)) not in message, (
            "the sanctioned door was reported as a violation"
        )

    def test_the_PRIMARY_gate_assertion_fails_on_the_planted_tree(
        self, tmp_path: Path
    ) -> None:
        """THE off-test the ticket asked for, on the assertion the gate runs.

        `test_runtime_imports_no_external_network_library` is the check the
        standing gate executes, and it used to carry its own copy of the
        violation loop hardcoded to `_REPO` — so it could not be pointed at a
        synthetic tree, and `for f in []` left the whole tier green (#1585
        review, finding 1). It routes through `_unexempted_violations` now, and
        this drives that function against both trees.
        """
        self._tree(tmp_path, plant_violator=True)
        assert _unexempted_violations(tmp_path), (
            "the gate's own assertion would PASS on a tree containing three "
            "planted network-client importers"
        )

    def test_the_PRIMARY_gate_assertion_passes_on_the_clean_tree(
        self, tmp_path: Path
    ) -> None:
        """The control for the test above: same tree, plants replaced by benign
        imports, and the door still present so the exemption is exercised."""
        self._tree(tmp_path, plant_violator=False)
        assert _unexempted_violations(tmp_path) == [], (
            "a clean synthetic tree produced violations: "
            f"{_unexempted_violations(tmp_path)}"
        )

    def test_the_forbidden_sets_have_not_SHRUNK(self) -> None:
        """Pinned by equality, because shrinkage is the silent direction.

        Reducing `_FORBIDDEN_TOP_LEVEL` to `{"httpx"}` — dropping requests,
        aiohttp, paramiko, boto3, openai, anthropic and the rest — left the
        entire security tier green (#1585 review, finding 3). The existing
        cross-file drift lock asserts a SUBSET, which by construction passes on
        a removal. A deliberate removal now has to be made in two places.
        """
        assert _FORBIDDEN_TOP_LEVEL == _EXPECTED_FORBIDDEN_TOP_LEVEL, (
            "the forbidden top-level set changed; removed: "
            f"{sorted(_EXPECTED_FORBIDDEN_TOP_LEVEL - _FORBIDDEN_TOP_LEVEL)}, "
            f"added: {sorted(_FORBIDDEN_TOP_LEVEL - _EXPECTED_FORBIDDEN_TOP_LEVEL)}"
        )
        assert _FORBIDDEN_DOTTED == _EXPECTED_FORBIDDEN_DOTTED, (
            "the forbidden dotted set changed; removed: "
            f"{sorted(_EXPECTED_FORBIDDEN_DOTTED - _FORBIDDEN_DOTTED)}, "
            f"added: {sorted(_FORBIDDEN_DOTTED - _EXPECTED_FORBIDDEN_DOTTED)}"
        )

    def test_the_SAME_tree_without_the_plant_is_clean(self, tmp_path: Path) -> None:
        """ON control: identical tree, violator replaced by ``import json``.

        Only the planted import differs. Without this, the test above could pass
        because the scan flags something incidental about a synthetic tree.
        """
        self._tree(tmp_path, plant_violator=False)
        importers = _network_client_importers(tmp_path)

        assert set(importers) == _EGRESS_DOOR_EXEMPTION, (
            "a clean synthetic tree reported a violation other than the "
            f"sanctioned door: {sorted(importers)}"
        )

    def test_the_DIRECTORY_exclusion_carries_its_own_weight(self, tmp_path: Path) -> None:
        """``tests/helpers.py`` — a plain filename in an excluded directory.

        Only the directory-name rule can exclude this one. The first version of
        this fixture planted ``tests/test_worker.py``, which BOTH rules exclude,
        so deleting the directory rule outright left every assertion green. A
        plant that two rules cover measures neither.
        """
        self._tree(tmp_path, plant_violator=True)
        importers = _network_client_importers(tmp_path)
        assert "services/newly_added_service/tests/helpers.py" not in importers, (
            "a file inside a tests/ directory was flagged as a runtime "
            f"violation — the directory exclusion is not firing: {sorted(importers)}"
        )

    def test_the_FILENAME_exclusion_carries_its_own_weight(self, tmp_path: Path) -> None:
        """``src/test_worker.py`` — a test filename in a scanned directory.

        Only the ``test_`` filename rule can exclude this one, for the same
        reason in reverse.
        """
        self._tree(tmp_path, plant_violator=True)
        importers = _network_client_importers(tmp_path)
        assert "services/newly_added_service/src/test_worker.py" not in importers, (
            "a test_*.py file in a runtime directory was flagged as a runtime "
            f"violation — the filename exclusion is not firing: {sorted(importers)}"
        )

    def test_a_repo_UNDER_a_directory_named_tests_is_still_scanned(
        self, tmp_path: Path
    ) -> None:
        """The exclusion is relative to the repo, not to the filesystem root.

        ``f.parts`` on an ABSOLUTE path includes every ancestor of the checkout,
        so a repository — or a git worktree, which is where this one lives, under
        ``.claude/worktrees/`` — sitting beneath a directory named ``tests`` or
        ``__pycache__`` silently scanned ZERO files. It failed loud on the
        "root paths drifted?" assert rather than passing green, so it was
        robustness and not a fail-open, but "zero files is the reading that must
        never be quietly wrong here" is this file's own standard.

        Nothing caught it: the fix and the unfixed form behave identically unless
        the repo actually sits under such a directory, which no ordinary
        ``tmp_path`` does. This constructs that path deliberately — the one input
        that can tell the two forms apart.
        """
        for parent in ("tests", "__pycache__"):
            repo = tmp_path / parent / "checkout"
            self._tree(repo, plant_violator=True)
            files = _runtime_files(repo)
            assert files, (
                f"a repo checked out under a directory named {parent!r} scanned "
                "ZERO files — the exclusion is matching ancestors above the repo "
                "root, and the whole air-gap control silently covers nothing"
            )
            assert self.VIOLATOR in _network_client_importers(repo), (
                f"the planted violator was invisible under a {parent!r} ancestor"
            )

    def test_an_EMPTY_tree_does_not_read_as_clean(self, tmp_path: Path) -> None:
        """A scan that finds no files must not be mistaken for a clean scan.

        ``test_egress_control_scans_a_meaningful_surface`` guards this for the
        real repo. This proves the underlying collector really does return
        nothing for an empty tree, so that guard is protecting against a state
        that can actually occur rather than a hypothetical one.
        """
        assert _runtime_files(tmp_path) == []
        assert _network_client_importers(tmp_path) == {}
