r"""The L188 third-instance structural control — external-contract probe gate.

Vikunja #739. Lesson 188 (adapters consuming an EXTERNAL contract break when
reality diverges from doc-derived assumptions — Kagi v0->v1 401, EAGLE-3
exporter, Chrome/Edge 149 console) reached its third instance, and the
LESSONS.md SOP requires the third instance to ship an *enforced* control. This is
that enforcement. It is deterministic and network-free.

Two teeth:

  (a) **Probe liveness** — every entry in
      :data:`shared.security.external_probes.REGISTERED_PROBES` names a probe
      entrypoint that EXISTS, is importable, and is callable + argparse-shaped
      WITHOUT any network I/O at import time. Import-time network-freeness is
      proven by importing the entrypoint in a subprocess whose ``socket`` has
      been monkeypatched to explode on any use.

  (b) **Registry completeness (the structural sweep)** — any module under
      ``services/`` or ``shared/`` that reaches the ONE egress door's
      ``fetch_external`` / ``fetch_external_binary`` entrypoint MUST be enrolled
      in the registry (as an adapter or its probe) or named in the justified-
      exclusion set below with a documented reason. A new external adapter that
      reaches the door without a probe fails this gate — the teeth.

No test here invokes the real probe (no network, no credential use).
"""

from __future__ import annotations

import ast
import importlib
import inspect
import subprocess
import sys
import textwrap
from pathlib import Path

from shared.security.external_probes import (
    REGISTERED_PROBES,
    registered_adapter_modules,
    registered_probe_modules,
)

_REPO = Path(__file__).resolve().parents[2]

# The one sanctioned egress door — it DEFINES the fetch entrypoints, so it is
# definitionally exempt from the "who reaches the door" sweep.
_EGRESS_DOOR_REL = "shared/security/guarded_fetch.py"

# The two fetch entrypoints of the egress door. A runtime module that imports or
# attribute-accesses either is "reaching the door" for the sweep's purposes.
_DOOR_FETCH_NAMES = frozenset({"fetch_external", "fetch_external_binary"})

# Roots swept for door-reaching modules ("any module under services/ or shared/").
_SWEEP_ROOTS = ("services", "shared")

# JUSTIFIED non-adapter door consumers — reached the door on purpose, but NOT a
# fixed external-contract adapter, so a contract probe does not apply. Each entry
# is a dotted module path -> the documented reason it is exempt from a probe.
# This set is deliberately tiny and every member carries its justification (the
# ticket's "register or justify each"); adding a member is a reviewable act.
_JUSTIFIED_NON_ADAPTERS: dict[str, str] = {
    "services.ui_gateway.src.ingest_coordinator": (
        "UC-003 /ingest fetches ARBITRARY user-supplied URLs, not a fixed vendor "
        "API contract — there is no stable endpoint / auth / response schema to "
        "probe. Egress is adjudicated per-fetch by the PA door + guest parser, "
        "not by a doc-derived contract assumption. Covered by the egress door's "
        "own gate tests (tests/security/test_guarded_fetch*.py)."
    ),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _module_dotted_path(path: Path) -> str:
    """Repo-relative ``.py`` file -> dotted import path."""
    rel = path.relative_to(_REPO).with_suffix("")
    return ".".join(rel.parts)


def _sweep_files() -> list[Path]:
    """Every runtime ``.py`` under the sweep roots (skip tests / __pycache__ / door)."""
    files: list[Path] = []
    for root in _SWEEP_ROOTS:
        base = _REPO / root
        if not base.exists():
            continue
        for f in base.rglob("*.py"):
            parts = set(f.parts)
            if "tests" in parts or "__pycache__" in parts or f.name.startswith("test_"):
                continue
            if f.relative_to(_REPO).as_posix() == _EGRESS_DOOR_REL:
                continue  # the door defines the entrypoints; not a consumer
            files.append(f)
    return files


def _reaches_egress_door(path: Path) -> bool:
    """True iff *path* imports or attribute-accesses a door fetch entrypoint.

    Catches both call shapes without false-positiving on docstring mentions
    (strings are not AST Import/Attribute nodes):
      * ``from shared.security.guarded_fetch import fetch_external`` / ``_binary``
      * ``guarded_fetch.fetch_external(...)`` (module-import + attribute access)
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod.endswith("guarded_fetch"):
                for alias in node.names:
                    if alias.name in _DOOR_FETCH_NAMES:
                        return True
        elif isinstance(node, ast.Attribute):
            if node.attr in _DOOR_FETCH_NAMES:
                return True
    return False


def _door_reaching_modules() -> dict[str, str]:
    """Map dotted-module-path -> repo-relative path for every door-reaching file."""
    found: dict[str, str] = {}
    for f in _sweep_files():
        if _reaches_egress_door(f):
            found[_module_dotted_path(f)] = f.relative_to(_REPO).as_posix()
    return found


# ---------------------------------------------------------------------------
# Registry shape
# ---------------------------------------------------------------------------


def test_registry_is_non_empty_and_well_formed() -> None:
    """Every registered probe carries the four required, non-empty fields and a
    ``module:callable`` entrypoint."""
    assert REGISTERED_PROBES, "the external-probe registry is empty — the L188 control has no adapters"
    seen: set[str] = set()
    for probe in REGISTERED_PROBES:
        assert probe.name and probe.name not in seen, f"duplicate/empty probe name: {probe.name!r}"
        seen.add(probe.name)
        assert probe.adapter_module, f"{probe.name}: empty adapter_module"
        assert ":" in probe.probe_entrypoint, (
            f"{probe.name}: probe_entrypoint must be 'module:callable', got "
            f"{probe.probe_entrypoint!r}"
        )
        assert probe.probe_module and probe.probe_callable, (
            f"{probe.name}: probe_entrypoint must name both a module and a callable"
        )
        assert len(probe.contract_notes) >= 40, (
            f"{probe.name}: contract_notes must describe the real contract axes "
            "(endpoint / auth / response schema)"
        )


def test_registered_adapter_and_probe_modules_import() -> None:
    """Each registered adapter module and probe module actually exists (catches a
    typo'd dotted path in the registry)."""
    for dotted in sorted(registered_adapter_modules() | registered_probe_modules()):
        try:
            importlib.import_module(dotted)
        except Exception as exc:  # noqa: BLE001 — surface the import failure
            raise AssertionError(f"registered module {dotted!r} failed to import: {exc!r}")


# ---------------------------------------------------------------------------
# (a) Probe liveness — importable, callable, argparse-shaped, network-free import
# ---------------------------------------------------------------------------


def test_probe_entrypoints_are_callable_and_argparse_shaped() -> None:
    """Every probe entrypoint resolves to a callable that accepts an ``argv``
    argument (the argparse CLI hook shape)."""
    for probe in REGISTERED_PROBES:
        module = importlib.import_module(probe.probe_module)
        assert hasattr(module, probe.probe_callable), (
            f"{probe.name}: probe module {probe.probe_module!r} has no attribute "
            f"{probe.probe_callable!r}"
        )
        fn = getattr(module, probe.probe_callable)
        assert callable(fn), f"{probe.name}: probe entrypoint is not callable"
        params = inspect.signature(fn).parameters
        assert "argv" in params, (
            f"{probe.name}: probe entrypoint {probe.probe_callable!r} must accept an "
            "'argv' parameter (the argparse CLI hook shape)"
        )


def test_probe_entrypoints_import_without_touching_the_network() -> None:
    """Importing each probe entrypoint performs NO network I/O.

    Proven hermetically: a fresh subprocess replaces ``socket.socket`` /
    ``socket.create_connection`` / ``socket.getaddrinfo`` with stubs that explode
    on any use BEFORE importing the probe module, then imports it and resolves the
    callable. Any import-time socket construction or DNS lookup fails loudly."""
    for probe in REGISTERED_PROBES:
        script = textwrap.dedent(
            f"""
            import socket as _socket

            class _NoSocket(_socket.socket):
                def __init__(self, *a, **k):
                    raise AssertionError("socket constructed during probe import")

            def _boom(*a, **k):
                raise AssertionError("network call attempted during probe import")

            _socket.socket = _NoSocket
            _socket.create_connection = _boom
            _socket.getaddrinfo = _boom

            import importlib
            mod = importlib.import_module({probe.probe_module!r})
            fn = getattr(mod, {probe.probe_callable!r})
            assert callable(fn)
            print("PROBE_IMPORT_OK")
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            cwd=str(_REPO),
            timeout=180,
        )
        assert result.returncode == 0, (
            f"{probe.name}: probe import attempted network activity or failed:\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "PROBE_IMPORT_OK" in result.stdout, (
            f"{probe.name}: probe import did not complete cleanly:\n{result.stdout}"
        )


# ---------------------------------------------------------------------------
# (b) The structural sweep — the teeth
# ---------------------------------------------------------------------------


def test_sweep_finds_a_meaningful_surface() -> None:
    """Guard the guard: the sweep must actually detect the known door consumers,
    or a silently-broken detector would make the completeness test vacuous."""
    found = _door_reaching_modules()
    assert "services.assistant_orchestrator.src.websearch.live_adapter" in found, (
        "sweep did not detect the Kagi adapter reaching the egress door — the "
        "detection logic drifted"
    )
    assert "services.ui_gateway.src.ingest_coordinator" in found, (
        "sweep did not detect the UC-003 ingest coordinator reaching the egress "
        "door — the detection logic drifted"
    )
    assert len(found) >= 2, f"sweep surface suspiciously small: {sorted(found)}"


def test_every_egress_door_consumer_is_registered_or_justified() -> None:
    """THE TEETH: every module reaching the egress door's fetch entrypoint is
    enrolled in the probe registry (adapter or probe) or named in the justified-
    exclusion set. A new external adapter without a probe fails here."""
    allowed = (
        registered_adapter_modules()
        | registered_probe_modules()
        | set(_JUSTIFIED_NON_ADAPTERS)
    )
    found = _door_reaching_modules()
    unaccounted = {mod: rel for mod, rel in found.items() if mod not in allowed}
    assert not unaccounted, (
        "module(s) reach the one egress door's fetch entrypoint without a "
        "registered external-contract probe (Vikunja #739 / L188 control). Either "
        "register a probe in shared/security/external_probes.py, or add a "
        "justified exclusion (with a documented reason) to "
        "_JUSTIFIED_NON_ADAPTERS in this test:\n  "
        + "\n  ".join(f"{mod}  ({rel})" for mod, rel in sorted(unaccounted.items()))
    )


def test_justified_exclusions_are_documented_and_live() -> None:
    """Each justified exclusion must carry a real reason AND still reach the door
    (a stale exclusion for a module that no longer touches the door is removed)."""
    found = _door_reaching_modules()
    for mod, reason in _JUSTIFIED_NON_ADAPTERS.items():
        assert len(reason) >= 40, f"justified exclusion {mod!r} lacks a real reason"
        assert mod in found, (
            f"justified exclusion {mod!r} no longer reaches the egress door — "
            "remove the stale exclusion"
        )


def test_registered_adapters_actually_reach_the_door() -> None:
    """Each registered adapter module really does reach the door (a registry entry
    for a module that does not touch the door is stale/miscategorised)."""
    found = _door_reaching_modules()
    for adapter_module in sorted(registered_adapter_modules()):
        assert adapter_module in found, (
            f"registered adapter {adapter_module!r} does not reach the egress door "
            "— stale or miscategorised registry entry"
        )
