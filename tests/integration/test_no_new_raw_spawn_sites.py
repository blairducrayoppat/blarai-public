"""Gate: no NEW raw process-spawn site may bypass the blessed ``shared.procspawn``.

WHY THIS GATE EXISTS — the lesson-219 scar family, and the missing weld.
----------------------------------------------------------------------
Spawning child processes on Windows has cost this project at least five separate
paid incidents (the venv ``python.exe`` shim defeating ``DETACHED_PROCESS`` one hop
down; the cp1252 stderr that killed a banner print; Textual's "Driver must be in
application mode" from a hidden console; ``msedge --screenshot`` silently no-op'ing;
the undrained-PIPE / non-EOF-stdin deadlock) — #761 / lesson 219 and its family.
The learned rules were consolidated into ONE blessed surface, ``shared/procspawn.py``
(``detached_no_console`` / ``hidden_console`` / ``run_captured`` /
``terminate_process_tree``), merged 2026-07-09 (#774), each rule carrying its
incident citation.

But merging the helper welded NOTHING SHUT.  Nothing structural stopped a NEW raw
``subprocess.Popen`` / ``subprocess.run`` / ``os.system`` / ``os.spawn*`` call from
landing in fleet or service code and re-learning the whole scar class one hop at a
time.  A disabled-by-vigilance rule is the weakest form of dormancy
(security_by_design principle 4); this gate replaces vigilance with a structural
ratchet (#774 sub-task 4).

WHAT THIS GATE DOES — a deny-by-default ratchet on the raw-spawn surface.
------------------------------------------------------------------------
It AST-parses every production (non-test) Python file under ``shared/``,
``services/`` and ``launcher/`` and finds every real CALL to a raw process-spawn
API (``subprocess.*`` and the ``os`` spawn/exec/system family), resolving import
aliases (``import subprocess as sp``, ``from subprocess import Popen``,
``import os as _os``).  AST — not a regex — so a spawn MENTIONED in a docstring or a
default-argument assignment (``popen=subprocess.Popen``) is never miscounted; only
an actual call site is.

Each currently-known call site is enumerated in :data:`KNOWN_RAW_SPAWN_SITES`
below, keyed ``"<relpath>::<api>"`` -> count.  The gate FAILS LOUDLY, naming the
file + API, if the live surface contains ANY site the allowlist does not
(security_by_design principles 2 deny-by-default + 11 fail-loud): a new raw spawn
must either route through ``shared.procspawn`` or be added to the allowlist here
with a comment justifying why it stays raw — a reviewer's deliberate act, never a
silent slip.

The allowlist is a RATCHET, not a floor: the ``shared/fleet/*`` entries are #774
sub-task 2's migration debt (tracked, to be routed through ``shared.procspawn``),
and :func:`test_allowlist_not_stale` fails if a site is migrated away without the
allowlist shrinking in the same change — so the known-debt count can only go DOWN.

SCOPE (documented environmental deltas — benign only because bounded).
----------------------------------------------------------------------
* Test files are EXCLUDED.  Tests legitimately drive REAL children through real
  entry points to assert the observable END property (the seams doctrine; the
  ``shared/tests/test_procspawn.py`` conformance suite itself spawns).  The scar
  class this gate guards is the SHIPPED runtime spawn surface, not gate scaffolding.
* ``shared/procspawn.py`` is EXCLUDED — it is the blessed wrapper and legitimately
  calls the low-level ``subprocess`` API; that is its whole job.
"""

from __future__ import annotations

import ast
import warnings
from pathlib import Path

import pytest

# This file lives at <repo_root>/tests/integration/<this>.py, so parents[2] is the
# repo root regardless of where the checkout / worktree is on disk.
_REPO_ROOT = Path(__file__).resolve().parents[2]

# The production surface the gate scans.  Test trees and procspawn.py are excluded
# (see the module docstring SCOPE note).
_SURFACE_DIRS = ("shared", "services", "launcher")
_EXCLUDED_FILES = frozenset({"shared/procspawn.py"})

# ---------------------------------------------------------------------------
# The raw-spawn APIs.  A CALL to any of these (module-qualified or via a resolved
# alias) is a raw spawn site.
# ---------------------------------------------------------------------------
_SUBPROCESS_APIS = frozenset(
    {"Popen", "run", "call", "check_call", "check_output", "getoutput", "getstatusoutput"}
)
_OS_APIS = frozenset(
    {
        "system", "popen",
        "spawnl", "spawnle", "spawnlp", "spawnlpe",
        "spawnv", "spawnve", "spawnvp", "spawnvpe",
        "posix_spawn", "posix_spawnp",
        "execl", "execle", "execlp", "execlpe",
        "execv", "execve", "execvp", "execvpe",
    }
)

# ===========================================================================
# THE ALLOWLIST — every raw process-spawn call site currently on the production
# surface, keyed "<relpath>::<api>" -> count.  Deny-by-default: anything NOT here
# fails the gate.  Regenerate the exact current set any time by running this file
# as a script (``python tests/integration/test_no_new_raw_spawn_sites.py``).
#
# GROUP A — #774 sub-task 2 migration debt (shared/fleet/*): these raw sites are
# scheduled to be routed through shared.procspawn one at a time.  As each migrates,
# DECREMENT/REMOVE its entry here in the SAME change (test_allowlist_not_stale
# enforces the coupling).  The known-debt count only goes down.
#
# GROUP B — other current known sites (launcher / services / shared).  These may be
# legitimately-raw (e.g. launcher process primitives, a security verifier reading an
# exit code, a perf-env capture).  They are baselined so a NEW raw spawn beside them
# is still caught; migrate opportunistically where a blessed shape fits.
# ===========================================================================
KNOWN_RAW_SPAWN_SITES: dict[str, int] = {
    # ---- GROUP A: shared/fleet/* — #774 sub-task 2 migration targets ----
    "shared/fleet/dispatch.py::subprocess.Popen": 1,   # run_fleet — detached fleet child
    "shared/fleet/dispatch.py::subprocess.run": 1,     # _safe_run — captured helper
    "shared/fleet/guest_oracle.py::subprocess.run": 1,  # _default_pytest_run
    "shared/fleet/guest_oracle_transport.py::subprocess.run": 2,  # _interp_has_af_hyperv; GuestOracleBridge._run
    "shared/fleet/oracle_qa.py::subprocess.run": 1,    # _default_run
    "shared/fleet/static_pregate.py::subprocess.run": 1,  # _default_run
    "shared/fleet/swap_ops.py::subprocess.Popen": 3,   # restart_launcher (x2); _spawn_detached_driver
    "shared/fleet/swap_ops.py::subprocess.run": 2,     # real_ovms_alive; _default_hermetic_run
    # ---- GROUP B: other current known sites (launcher / services / shared) ----
    "launcher/guest_parser_invoker.py::subprocess.run": 2,  # _interp_has_af_hyperv; GuestParserBridge._run
    "launcher/process_launch.py::subprocess.Popen": 1,  # launch_winui — WinUI process primitive
    "launcher/vm_manager.py::subprocess.run": 1,       # _run_ps — Hyper-V control (#817-tripwired)
    "services/assistant_orchestrator/src/entrypoint.py::subprocess.run": 1,  # _commit_dispatch_assets._git
    "shared/perf_env_capture.py::subprocess.run": 1,   # _run_ps — perf-env capture
    "shared/security/hello_verifier.py::subprocess.run": 2,  # verify; _probe_available — exit-code verifier
}

_REMEDIATION = (
    "Route it through the blessed helper shared.procspawn "
    "(detached_no_console / hidden_console / run_captured / terminate_process_tree) "
    "so the learned Windows spawn rules (pythonw shim-hop, UTF-8 pinning, hidden-vs-"
    "detached console, EOF stdin + drain, tree-kill) apply — see shared/procspawn.py "
    "and lesson 219. If the site genuinely must stay raw, add it to "
    "KNOWN_RAW_SPAWN_SITES in tests/integration/test_no_new_raw_spawn_sites.py with a "
    "comment justifying why (a deliberate reviewer act, never a silent slip)."
)


# ---------------------------------------------------------------------------
# The scanner — alias-aware AST walk, isolated so the self-tests can drive it with
# synthetic source (security_by_design principle 12: control tested ON and OFF).
# ---------------------------------------------------------------------------
class _SpawnCallFinder(ast.NodeVisitor):
    """Collect ``(api, qualname, lineno)`` for every raw-spawn CALL in one module."""

    def __init__(self) -> None:
        self._mod_alias: dict[str, str] = {}   # local name -> "subprocess" | "os"
        self._sym_alias: dict[str, str] = {}    # local name -> "subprocess.run" etc.
        self._scope: list[str] = []
        self.hits: list[tuple[str, str, int]] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name in ("subprocess", "os"):
                self._mod_alias[alias.asname or alias.name] = alias.name
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module in ("subprocess", "os"):
            for alias in node.names:
                self._sym_alias[alias.asname or alias.name] = f"{node.module}.{alias.name}"
        self.generic_visit(node)

    def _visit_scoped(self, name: str, node: ast.AST) -> None:
        self._scope.append(name)
        self.generic_visit(node)
        self._scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_scoped(node.name, node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_scoped(node.name, node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._visit_scoped(node.name, node)

    def visit_Call(self, node: ast.Call) -> None:
        api = self._resolve(node.func)
        if api is not None:
            self.hits.append((api, ".".join(self._scope) or "<module>", node.lineno))
        self.generic_visit(node)

    def _resolve(self, func: ast.expr) -> str | None:
        # module-qualified: subprocess.run(...) / sp.run(...) / os.system(...) / _os.execv(...)
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            module = self._mod_alias.get(func.value.id)
            if module == "subprocess" and func.attr in _SUBPROCESS_APIS:
                return f"subprocess.{func.attr}"
            if module == "os" and func.attr in _OS_APIS:
                return f"os.{func.attr}"
        # from-import: `from subprocess import Popen; Popen(...)`
        if isinstance(func, ast.Name):
            return self._sym_alias.get(func.id)
        return None


def _scan_source(source: str) -> list[tuple[str, str, int]]:
    """Raw-spawn hits in a single module's *source* (used by the self-tests)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)  # scanned code may carry stray escapes
        tree = ast.parse(source)
    finder = _SpawnCallFinder()
    finder.visit(tree)
    return finder.hits


def _iter_surface_files() -> list[Path]:
    files: list[Path] = []
    for top in _SURFACE_DIRS:
        for py in sorted((_REPO_ROOT / top).rglob("*.py")):
            rel = py.relative_to(_REPO_ROOT).as_posix()
            if rel in _EXCLUDED_FILES:
                continue
            if _is_test_path(py):
                continue
            files.append(py)
    return files


def _is_test_path(path: Path) -> bool:
    parts = {p.lower() for p in path.parts}
    if "tests" in parts or "test" in parts:
        return True
    name = path.name.lower()
    return name.startswith("test_") or name == "conftest.py"


def _scan_surface() -> tuple[dict[str, list[str]], list[str]]:
    """Scan the whole production surface.

    Returns ``(sites, parse_errors)`` where *sites* maps ``"<relpath>::<api>"`` to a
    list of ``"L<lineno> <qualname>"`` diagnostics, and *parse_errors* names any file
    that would not parse (fail-closed: an unscannable file cannot be vouched for).
    """
    sites: dict[str, list[str]] = {}
    parse_errors: list[str] = []
    for py in _iter_surface_files():
        rel = py.relative_to(_REPO_ROOT).as_posix()
        try:
            hits = _scan_source(py.read_text(encoding="utf-8"))
        except SyntaxError as exc:  # noqa: PERF203 — one report per bad file
            parse_errors.append(f"{rel}: {exc}")
            continue
        for api, qual, lineno in hits:
            sites.setdefault(f"{rel}::{api}", []).append(f"L{lineno} {qual}")
    return sites, parse_errors


# ---------------------------------------------------------------------------
# THE GATE
# ---------------------------------------------------------------------------
def test_no_new_raw_spawn_sites() -> None:
    """FAIL LOUD, naming it, if any raw spawn site is not in the allowlist."""
    sites, parse_errors = _scan_surface()

    assert not parse_errors, (
        "Raw-spawn gate could not parse these production files, so it cannot verify "
        "them (fail-closed):\n  " + "\n  ".join(parse_errors)
    )

    offenders: list[str] = []
    for key, diagnostics in sorted(sites.items()):
        allowed = KNOWN_RAW_SPAWN_SITES.get(key, 0)
        if len(diagnostics) > allowed:
            relpath, api = key.split("::", 1)
            extra = len(diagnostics) - allowed
            offenders.append(
                f"  {relpath}: {extra} un-allowlisted `{api}` call site(s) "
                f"(found {len(diagnostics)}, allowlisted {allowed}) at {diagnostics}"
            )

    assert not offenders, (
        "NEW raw process-spawn site(s) detected that bypass the blessed "
        "shared.procspawn helper:\n"
        + "\n".join(offenders)
        + "\n\n"
        + _REMEDIATION
    )


def test_allowlist_not_stale() -> None:
    """FAIL if an allowlisted site is gone — the ratchet only shrinks.

    When #774 sub-task 2 migrates a raw spawn onto shared.procspawn, the site
    disappears from the live surface; this test then fails until the allowlist is
    decremented in the SAME change (mirrors how the WinUI passthrough gate forces
    the C# mirror to be updated with the constant).  Deny-by-default stays honest:
    the known-debt count can never silently drift upward by leaving stale slack.
    """
    sites, parse_errors = _scan_surface()
    assert not parse_errors, "see test_no_new_raw_spawn_sites for parse errors"

    stale: list[str] = []
    for key, allowed in sorted(KNOWN_RAW_SPAWN_SITES.items()):
        found = len(sites.get(key, []))
        if allowed > found:
            stale.append(f"  {key}: allowlist says {allowed}, surface has {found}")

    assert not stale, (
        "STALE allowlist entries — these raw spawn sites were removed/migrated but "
        "KNOWN_RAW_SPAWN_SITES still counts them:\n"
        + "\n".join(stale)
        + "\n\nDecrement/remove them in tests/integration/test_no_new_raw_spawn_sites.py "
        "in the same change that migrated the site, so the ratchet reflects reality."
    )


def test_allowlist_matches_live_surface_exactly() -> None:
    """Sanity: the baked allowlist EQUALS the current surface (guards drift both ways
    and proves the scanner really found the known sites — not a vacuous pass)."""
    sites, parse_errors = _scan_surface()
    assert not parse_errors
    current_counts = {key: len(v) for key, v in sites.items()}
    assert current_counts == KNOWN_RAW_SPAWN_SITES, (
        "The raw-spawn allowlist has drifted from the live surface. "
        f"only-on-surface={sorted(set(current_counts) - set(KNOWN_RAW_SPAWN_SITES))}, "
        f"only-in-allowlist={sorted(set(KNOWN_RAW_SPAWN_SITES) - set(current_counts))}, "
        "count-mismatches="
        + str({k: (current_counts.get(k), KNOWN_RAW_SPAWN_SITES.get(k))
               for k in set(current_counts) | set(KNOWN_RAW_SPAWN_SITES)
               if current_counts.get(k) != KNOWN_RAW_SPAWN_SITES.get(k)})
    )


# ---------------------------------------------------------------------------
# CONTROL TESTED ON *AND* OFF (security_by_design principle 12) — prove the scanner
# FIRES on a synthetic new spawn, and does NOT fire on non-spawn / excluded code.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "source, expected_api",
    [
        ("import subprocess\ndef f():\n    subprocess.Popen(['x'])\n", "subprocess.Popen"),
        ("import subprocess\ndef f():\n    subprocess.run(['x'])\n", "subprocess.run"),
        ("import subprocess as sp\ndef f():\n    sp.check_output(['x'])\n", "subprocess.check_output"),
        ("from subprocess import Popen\ndef f():\n    Popen(['x'])\n", "subprocess.Popen"),
        ("import os\ndef f():\n    os.system('x')\n", "os.system"),
        ("import os as _os\ndef f():\n    _os.execv('x', [])\n", "os.execv"),
        ("from os import spawnv\ndef f():\n    spawnv(0, 'x', [])\n", "os.spawnv"),
    ],
)
def test_scanner_fires_on_synthetic_new_spawn(source: str, expected_api: str) -> None:
    """The lock BLOCKS when engaged: every raw-spawn form (aliased, from-imported,
    subprocess + os families) is detected as a call site."""
    hits = _scan_source(source)
    assert [api for api, _, _ in hits] == [expected_api], (
        f"scanner missed a raw spawn it must catch: {source!r} -> {hits}"
    )


def test_gate_logic_fails_on_an_injected_new_site() -> None:
    """End-to-end proof the GATE (not just the scanner) goes red: inject a synthetic
    site the allowlist does not name and assert the offender-diff reports it."""
    injected = "services/fake/new_tool.py::subprocess.Popen"
    current = {**{k: [f"L1 {k}"] * v for k, v in KNOWN_RAW_SPAWN_SITES.items()},
               injected: ["L42 fake.run"]}
    offenders = [
        key for key, diags in current.items()
        if len(diags) > KNOWN_RAW_SPAWN_SITES.get(key, 0)
    ]
    assert offenders == [injected], (
        "gate logic failed to flag an injected un-allowlisted spawn site "
        f"(control-ON check) -> {offenders}"
    )


def test_scanner_ignores_nonspawn_and_mentions() -> None:
    """The lock does NOT false-fire: references, default-arg assignments, docstring
    mentions and non-spawn attributes are NOT call sites (distinguishes a real weld
    from an over-broad probe)."""
    source = (
        "import subprocess\n"
        "import os\n"
        '"""A docstring mentioning subprocess.Popen and os.system."""\n'
        "SINK = subprocess.DEVNULL\n"           # attribute reference, not a call
        "PIPE = subprocess.PIPE\n"
        "def make(popen=subprocess.Popen):\n"    # default-arg assignment, not a call
        "    path = os.path.join('a', 'b')\n"    # os.path.join is not a spawn
        "    env = os.environ.copy()\n"          # os.environ is not a spawn
        "    return popen\n"
    )
    assert _scan_source(source) == []


# ---------------------------------------------------------------------------
# Regenerate the allowlist: `python tests/integration/test_no_new_raw_spawn_sites.py`
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    live, errs = _scan_surface()
    for e in errs:
        print(f"!! PARSE ERROR {e}")
    print("KNOWN_RAW_SPAWN_SITES: dict[str, int] = {")
    for k in sorted(live):
        print(f'    "{k}": {len(live[k])},   # {"; ".join(live[k])}')
    print("}")
    print(f"# {sum(len(v) for v in live.values())} sites across {len(live)} (file,api) keys")
