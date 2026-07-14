"""Truth-in-packaging lock (#810, 12-Factor II).

Before #810, ``pyproject.toml`` declared exactly 2 runtime dependencies while
the runtime imported ~18 third-party distributions — the manifest and the
import graph had diverged silently, and ``pip install .`` yielded a
non-runnable install. The fix declared the real surface; THIS test is the
control that keeps it true: every top-level third-party import in the runtime
source (non-test code under ``shared/``, ``services/``, ``launcher/``) must
resolve to a distribution declared in ``[project] dependencies``, and every
declared distribution must be genuinely imported by runtime code. A future PR
that adds an undeclared import — or a dead declaration — fails the standing
gate loudly, naming the module and the files.

The three properties locked here:

1. **Forward truth** — runtime imports ⊆ declared dependencies (no undeclared
   dependency can land silently).
2. **Reverse truth** — declared dependencies ⊆ runtime imports (the manifest
   never claims a dependency the code does not have; dead declarations are
   the same lie in the other direction).
3. **Manifest↔lock consistency** — every declared distribution appears in the
   reproducibility SSOT lock file (``requirements.2026.2.1.lock.txt``) at a
   version satisfying the declared specifier. The lock is the exact
   reproduction recipe (the runtime venv is built from it, not from
   ``pip install .``); the manifest's bounds must never contradict it.

**Scope honesty:** this is a static AST scan of ``import`` / ``from … import``
statements (any nesting depth — function-local lazy imports count). It does
not see ``importlib.import_module("name")`` with a dynamic string, and it
classifies "runtime" by path convention (test files excluded by the same
convention the repo uses everywhere: ``tests``/``test`` path parts,
``test_*.py``, ``conftest.py``). Distribution names are resolved via PEP 503
normalization plus an explicit table for the irregulars (``PIL`` → pillow,
``jwt`` → PyJWT, the pywin32 module family) — a NEW irregular import fails
loudly with instructions rather than passing silently.
"""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.version import Version

_REPO = Path(__file__).resolve().parents[2]

# The runtime source roots (the packaging surface #810 declares). Dev/build
# tooling — tools/, tests/, evals/, docs/ — is NOT packaged and not scanned.
_RUNTIME_ROOTS = ("shared", "services", "launcher")

# The reproducibility SSOT: the exact resolved set the runtime venv is built
# from. pyproject declares truth; this file pins the reproduction.
_LOCK_FILE = "requirements.2026.2.1.lock.txt"

# First-party top-level packages (never a PyPI distribution). ``tools`` is
# repo-local dev tooling: the ONE runtime-root reference to it is
# shared/fleet/vikunja_bridge.py's lazily-imported dev-tier transport
# (``tools.dispatch_harness.vikunja_http`` inside ``_default_transport``) —
# the fleet dispatch harness is dev-side, and the import resolves to the
# repo directory via pythonpath, not to any PyPI distribution. ``tests``
# and ``evals`` are deliberately NOT listed: runtime code importing them
# is a defect this test should surface loudly.
_FIRST_PARTY = frozenset({"shared", "services", "launcher", "tools"})

# Import name -> PyPI distribution name, for the packages whose import name
# does not PEP 503-normalize to their distribution name. The pywin32 family
# is one distribution exposing many top-level modules; the listed set covers
# the modules imported today plus its most common siblings so the next
# win32* import maps correctly instead of failing as "undeclared win32event".
# A genuinely new irregular import fails the forward test loudly — extend
# this table in the same change that adds the import.
_MODULE_TO_DIST: dict[str, str] = {
    "PIL": "pillow",
    "jwt": "PyJWT",
    "ntsecuritycon": "pywin32",
    "pywintypes": "pywin32",
    "servicemanager": "pywin32",
    "win32api": "pywin32",
    "win32com": "pywin32",
    "win32comext": "pywin32",
    "win32con": "pywin32",
    "win32crypt": "pywin32",
    "win32event": "pywin32",
    "win32file": "pywin32",
    "win32gui": "pywin32",
    "win32pipe": "pywin32",
    "win32process": "pywin32",
    "win32security": "pywin32",
    "winerror": "pywin32",
}

# Declared dependencies that legitimately have no direct runtime import.
# EMPTY today — every declared distribution is directly imported. If a
# plugin-style dependency (needed but never imported) is ever added, record
# it here explicitly with a comment saying why; never widen silently.
_DECLARED_WITHOUT_RUNTIME_IMPORT: frozenset[str] = frozenset()


def _normalize(name: str) -> str:
    """PEP 503 distribution-name normalization."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _runtime_files() -> list[Path]:
    files: list[Path] = []
    for root in _RUNTIME_ROOTS:
        base = _REPO / root
        for f in base.rglob("*.py"):
            parts = set(f.parts)
            if parts & {"tests", "test", "__pycache__"}:
                continue
            if f.name.startswith("test_") or f.name == "conftest.py":
                continue
            files.append(f)
    return files


def _top_level_imports(path: Path) -> set[str]:
    """Top-level module of every absolute import, at any nesting depth."""
    mods: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:  # relative imports are first-party
                mods.add(node.module.split(".", 1)[0])
    return mods


def _third_party_runtime_imports() -> dict[str, set[str]]:
    """module -> set of repo-relative files importing it (stdlib/first-party excluded)."""
    stdlib = set(sys.stdlib_module_names)
    importers: dict[str, set[str]] = {}
    for f in _runtime_files():
        rel = f.relative_to(_REPO).as_posix()
        for mod in _top_level_imports(f):
            if mod in stdlib or mod in _FIRST_PARTY:
                continue
            importers.setdefault(mod, set()).add(rel)
    return importers


def _declared_requirements() -> list[Requirement]:
    with (_REPO / "pyproject.toml").open("rb") as fh:
        pyproject = tomllib.load(fh)
    deps = pyproject.get("project", {}).get("dependencies", [])
    assert deps, "pyproject.toml [project] dependencies is empty — manifest drifted?"
    return [Requirement(d) for d in deps]


def _lock_versions() -> dict[str, Version]:
    """name (normalized) -> exact version, from `name==version` lock lines.

    Editable (`-e`) and VCS (`@ git+`) lines carry no `==` pin and are skipped
    — none of the runtime's declared dependencies may ride on one (property 3
    fails if a declared name has no `==` line).
    """
    versions: dict[str, Version] = {}
    for line in (_REPO / _LOCK_FILE).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-")):
            continue
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9.!+*]+)$", line)
        if m:
            versions[_normalize(m.group(1))] = Version(m.group(2))
    assert len(versions) >= 100, (
        f"lock file parse yielded suspiciously few pins ({len(versions)}) — "
        f"format drifted? ({_LOCK_FILE})"
    )
    return versions


def test_every_runtime_import_is_a_declared_dependency() -> None:
    """Forward truth: no runtime module imports an undeclared third-party
    distribution. This is the lock that ends the pre-#810 silent divergence
    (2 declared vs ~18 imported)."""
    declared = {_normalize(r.name) for r in _declared_requirements()}
    violations: list[str] = []
    for mod, files in sorted(_third_party_runtime_imports().items()):
        dist = _normalize(_MODULE_TO_DIST.get(mod, mod))
        if dist not in declared:
            examples = ", ".join(sorted(files)[:3])
            violations.append(f"import {mod!r} (-> dist {dist!r}) in: {examples}")
    assert not violations, (
        "Runtime code imports third-party packages NOT declared in "
        "pyproject.toml [project] dependencies — the manifest is lying about "
        "the import graph (#810 truth-in-packaging). Fix: declare the "
        "distribution with a lower bound matching its resolved version in "
        f"{_LOCK_FILE}; if the import name differs from the distribution "
        "name, extend _MODULE_TO_DIST in this test. Undeclared:\n  "
        + "\n  ".join(violations)
    )


def test_every_declared_dependency_is_actually_imported() -> None:
    """Reverse truth: no dead declarations. A declared dependency nothing
    imports is the same manifest lie in the other direction (and a stale
    supply-chain surface). Legitimate import-less dependencies must be
    recorded in _DECLARED_WITHOUT_RUNTIME_IMPORT with a reason."""
    imported_dists = {
        _normalize(_MODULE_TO_DIST.get(mod, mod))
        for mod in _third_party_runtime_imports()
    }
    dead = [
        r.name
        for r in _declared_requirements()
        if _normalize(r.name) not in imported_dists
        and _normalize(r.name) not in {_normalize(n) for n in _DECLARED_WITHOUT_RUNTIME_IMPORT}
    ]
    assert not dead, (
        "pyproject.toml declares dependencies no runtime module imports — "
        "remove them or record them in _DECLARED_WITHOUT_RUNTIME_IMPORT with "
        f"a reason: {sorted(dead)}"
    )


def test_declared_bounds_are_consistent_with_the_lock() -> None:
    """Manifest<->lock consistency: every declared distribution is pinned in
    the reproducibility SSOT lock file at a version satisfying the declared
    specifier. Catches a manifest bound raised past (or ranged off) the lock,
    and a declaration the lock never resolved — either way the two files
    would be telling different stories about the same venv."""
    lock = _lock_versions()
    problems: list[str] = []
    for req in _declared_requirements():
        name = _normalize(req.name)
        if name not in lock:
            problems.append(f"{req.name}: declared but not pinned in {_LOCK_FILE}")
            continue
        if not req.specifier.contains(str(lock[name]), prereleases=True):
            problems.append(
                f"{req.name}: lock pins {lock[name]} which does NOT satisfy "
                f"declared specifier '{req.specifier}'"
            )
    assert not problems, (
        "pyproject.toml [project] dependencies disagree with the lock file "
        f"({_LOCK_FILE} is the reproducibility SSOT):\n  " + "\n  ".join(problems)
    )


def test_dependency_truth_scans_a_meaningful_surface() -> None:
    """Guard the guard: if the roots drift or the walker stops seeing nested
    imports, the truth tests above would vacuously pass. Assert the scan
    covers the real runtime and sees function-local lazy imports."""
    files = _runtime_files()
    scanned = {f.relative_to(_REPO).as_posix() for f in files}
    assert len(files) >= 120, (
        f"dependency-truth scan surface suspiciously small: {len(files)} files"
    )
    assert any("assistant_orchestrator/src/entrypoint.py" in p for p in scanned), (
        "scan is not covering the AO entrypoint — roots drifted"
    )
    assert any(p.startswith("launcher/") for p in scanned), (
        "scan is not covering the launcher — roots drifted"
    )
    imports = _third_party_runtime_imports()
    assert "numpy" in imports, "scan no longer sees numpy — walker broken?"
    # openvino_genai's import sites include function-local lazy imports
    # (shared/inference/image_gen.py) — seeing it proves nested-import visibility.
    assert "openvino_genai" in imports, (
        "scan no longer sees openvino_genai's lazy imports — nested-import "
        "visibility broken?"
    )
