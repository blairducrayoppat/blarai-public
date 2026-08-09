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
* API SCOPE (N2): the gate covers the ``subprocess.*`` call family and the ``os``
  spawn/exec/system family ONLY.  Deliberately OUT of current scope — spawn paths this
  gate does NOT see — are ``ctypes`` Win32 ``CreateProcess``/``ShellExecute``,
  ``os.startfile``, and ``asyncio.create_subprocess_exec``/``_shell``.  None are used on
  the current surface; a future need for one is a deliberate extension of
  :data:`_SUBPROCESS_APIS` / :data:`_OS_APIS`, never a silent gap.
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
    # ---- GROUP A: shared/fleet/* — #774 sub-task 2 migration debt ----
    # 2026-07-17 (#774 sub-task 2): 10 of the 12 Group-A sites migrated onto
    # shared.procspawn (dispatch _safe_run/run_fleet, oracle_qa/static_pregate/
    # swap_ops _default_(hermetic_)run, swap_ops real_ovms_alive, restart_launcher x2,
    # _spawn_detached_driver, transport _interp_has_af_hyperv).  The two that REMAIN raw
    # cannot route through the blessed helper without a behavior change:
    "shared/fleet/guest_oracle.py::subprocess.run": 1,  # _default_pytest_run — this module
    #   SHIPS to the NIC-less Alpine guest and runs the coder snapshot's pytest INSIDE the
    #   isolated VM; it is stdlib-only at module scope by design (see its in-file note), so
    #   it cannot take a shared.procspawn dependency without expanding the guest's trusted
    #   surface across the vsock isolation boundary.
    "shared/fleet/guest_oracle_transport.py::subprocess.run": 1,  # GuestOracleBridge._run —
    #   a BINARY vsock frame protocol: bytes stdin (json line + length-prefixed frames) and
    #   bytes stdout parsed as frames.  Every procspawn helper decodes stdout to UTF-8 text
    #   (errors='replace'), which would corrupt the frames, and none accepts bytes input.
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
# The scanner — a TWO-PASS alias-aware AST walk (N1), isolated so the self-tests can
# drive it with synthetic source (security_by_design principle 12: control tested ON
# and OFF).  Pass 1 collects import aliases across the WHOLE module; pass 2 detects
# calls against the complete maps — so a spawn call SYNTACTICALLY ABOVE its import
# (e.g. a helper defined before a bottom-of-file ``import subprocess``) is still
# resolved.  A single-pass in-source-order walk resolved a call against the aliases
# seen SO FAR and silently missed any spawn above its import.
# ---------------------------------------------------------------------------
class _AliasCollector(ast.NodeVisitor):
    """Pass 1 — collect module + symbol aliases across the whole module, order-independent."""

    def __init__(self) -> None:
        self.mod_alias: dict[str, str] = {}   # local name -> "subprocess" | "os"
        self.sym_alias: dict[str, str] = {}   # local name -> "subprocess.run" etc.

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name in ("subprocess", "os"):
                self.mod_alias[alias.asname or alias.name] = alias.name
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module in ("subprocess", "os"):
            for alias in node.names:
                self.sym_alias[alias.asname or alias.name] = f"{node.module}.{alias.name}"
        self.generic_visit(node)


class _SpawnCallFinder(ast.NodeVisitor):
    """Pass 2 — with the complete alias maps, collect ``(api, qualname, lineno)`` for
    every raw-spawn CALL in one module."""

    def __init__(self, mod_alias: dict[str, str], sym_alias: dict[str, str]) -> None:
        self._mod_alias = mod_alias
        self._sym_alias = sym_alias
        self._scope: list[str] = []
        self.hits: list[tuple[str, str, int]] = []

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
    """Raw-spawn hits in a single module's *source* (used by the self-tests).

    Two-pass (N1): aliases are collected across the WHOLE module first, THEN calls are
    resolved — so the result is independent of whether a spawn call sits above or below
    its import statement.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)  # scanned code may carry stray escapes
        tree = ast.parse(source)
    aliases = _AliasCollector()
    aliases.visit(tree)
    finder = _SpawnCallFinder(aliases.mod_alias, aliases.sym_alias)
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
        except (SyntaxError, ValueError, UnicodeDecodeError) as exc:  # noqa: PERF203 — one report per bad file
            # N3 (fail-closed): SyntaxError won't parse; ValueError == null bytes in the
            # source (ast.parse rejects them); UnicodeDecodeError == the file is not valid
            # UTF-8.  An unscannable file cannot be vouched for, so it FAILS the gate via
            # the clean parse_errors message rather than crashing the whole run.
            parse_errors.append(f"{rel}: {type(exc).__name__}: {exc}")
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


def test_scanner_resolves_call_above_its_import() -> None:
    """N1 (order-independence): a spawn call SYNTACTICALLY ABOVE its import is still
    detected.  A single-pass in-source-order walk resolved each call against the aliases
    seen SO FAR and silently missed a spawn whose ``import subprocess`` sat below it — a
    real blind spot (a helper defined before a bottom-of-file import).  The two-pass
    scanner collects aliases across the whole module first, so order does not matter."""
    call_above_import = (
        "def _spawn():\n"
        "    subprocess.Popen(['x'])\n"   # the CALL …
        "import subprocess\n"             # … appears ABOVE this import
    )
    hits = _scan_source(call_above_import)
    assert [api for api, _, _ in hits] == ["subprocess.Popen"], (
        f"two-pass scanner must catch a spawn above its import (N1) -> {hits}"
    )
    # And the from-import symbol form, likewise resolved from below the call.
    from_import_below = (
        "def _spawn():\n"
        "    Popen(['x'])\n"
        "from subprocess import Popen\n"
    )
    assert [api for api, _, _ in _scan_source(from_import_below)] == ["subprocess.Popen"]


def test_scan_surface_fails_closed_on_unparseable_bytes(tmp_path, monkeypatch) -> None:
    """N3 (fail-closed): a file with NULL BYTES (ast.parse -> ValueError) or NON-UTF-8
    bytes (read_text -> UnicodeDecodeError) is reported as a parse_error and FAILS the
    gate cleanly — never a silent skip and never an uncaught crash."""
    import sys as _sys

    module = _sys.modules[__name__]
    nullbyte = tmp_path / "nullbyte.py"
    nullbyte.write_bytes(b"import subprocess\nsubprocess.Popen(['x'])\x00\n")  # ValueError
    badenc = tmp_path / "badenc.py"
    badenc.write_bytes(b"# not valid utf-8: \xff\xfe\n")                       # UnicodeDecodeError

    monkeypatch.setattr(module, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "_iter_surface_files", lambda: [nullbyte, badenc])

    sites, parse_errors = _scan_surface()
    assert sites == {}
    assert len(parse_errors) == 2
    # The non-UTF-8 file is the case the ORIGINAL bare ``except SyntaxError`` would have let
    # crash the whole gate (UnicodeDecodeError escapes it); N3's broadening turns it into a
    # clean, fail-closed parse_error instead.
    assert any("badenc.py: UnicodeDecodeError" in e for e in parse_errors)
    # The null-byte file is reported too — ast.parse raises SyntaxError for it on CPython
    # 3.12 (ValueError on some builds); either way it fails closed rather than crashing.
    assert any(e.startswith("nullbyte.py: ") for e in parse_errors)


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
