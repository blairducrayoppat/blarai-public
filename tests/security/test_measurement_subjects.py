"""
A committed script may not read a repo file that is not in the repo (#1318).
============================================================================

A recorded measurement whose subject is missing cannot be re-run, and a result
that cannot be re-run is indistinguishable from a fabricated one at any later
date. On 2026-08-07 three probes were in exactly that state: the 35B-A3B
multimodal quality probe (gate B evidence for the consolidation decision) named
two images at the repo root, and the gemma4 vision probe's ground truth was
rendered from a third -- all three untracked, for weeks, while two handoff cards
noted them and classified them as somebody else's working set.

The rule is deny-by-default: a media path anchored to the repository, named by a
committed script, must resolve to a TRACKED file. A file the script *generates*
is the only exception, and it must be declared in ``GENERATED`` with a reason --
so a new unlisted input fails loudly instead of rotting silently.

Anchored means the path chain is rooted at ``Path(__file__)``, directly or via a
module-level constant derived from it, reached by ``.parent`` / ``.parents[N]``
and joined with ``/`` onto string literals. Paths rooted anywhere else
(``tmp_path`` in a fixture, ``config.runs_dir`` at runtime) are not repo contents
and are not this test's business.

BOUNDED, ON PURPOSE -- the scanner is static and resolves only that idiom. It does
NOT see: f-string filenames, ``os.path.join``, ``.joinpath()``, a filename held in
a variable, a bare relative literal with no ``/`` join, tuple-unpacked assignment,
or module constants bound inside ``if``/``try`` blocks. Those are gaps in COVERAGE,
not holes that let a caught case escape; a subject reached that way simply gets no
protection here. The exclusion is written down because an undocumented blind spot
in a control reads as coverage, which is worse than no control -- and this file
exists because of exactly that pattern.
"""

from __future__ import annotations

import ast
import subprocess
import warnings
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

_MEDIA_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg", ".ico",
     ".html", ".wav", ".mp3", ".mp4", ".pdf"}
)

# Repo-anchored media paths a script WRITES rather than reads. Deny-by-default
# means every entry here is an argued exception, not a convenience.
GENERATED: dict[str, str] = {
    "docs/performance/_coresident_vlm_probe.png":
        "written by _make_test_image() in scripts/benchmark_coresident.py before the "
        "VLM partner runs; the underscore prefix marks it as generated scratch",
    "scripts/live_proof/grading_health_dashboard.html":
        "DEFAULT_OUT of scripts/live_proof/generate_dashboard.py -- rendered output, "
        "and gitignored at scripts/live_proof/.gitignore:4",
}


def _tracked_files() -> set[str]:
    out = subprocess.run(
        ["git", "-C", str(_REPO_ROOT), "ls-files"],
        capture_output=True, text=True, check=False,
    )
    assert out.returncode == 0, f"git ls-files failed: {out.stderr}"
    return {line.strip() for line in out.stdout.splitlines() if line.strip()}


def _eval_path(node: ast.AST, module_path: Path, symbols: dict[str, Path]) -> Path | None:
    """Resolve an AST expression to a filesystem path, or None if not repo-anchored.

    Handles the idioms actually used here: ``Path(__file__)``, ``.resolve()``,
    ``.parent`` chains, module-level constants built from those, and ``/`` joins
    onto string literals. Anything else resolves to None and is ignored.
    """
    if isinstance(node, ast.Name):
        return symbols.get(node.id)

    if isinstance(node, ast.Call):
        func = node.func
        is_path_call = (
            (isinstance(func, ast.Name) and func.id == "Path")
            or (isinstance(func, ast.Attribute) and func.attr == "Path")
        )
        if is_path_call and len(node.args) == 1:
            arg = node.args[0]
            if isinstance(arg, ast.Name) and arg.id == "__file__":
                return module_path
            return None
        # ``.resolve()`` / ``.absolute()`` are identity for our purposes.
        if isinstance(func, ast.Attribute) and func.attr in {"resolve", "absolute"}:
            return _eval_path(func.value, module_path, symbols)
        return None

    if isinstance(node, ast.Attribute) and node.attr == "parent":
        inner = _eval_path(node.value, module_path, symbols)
        return inner.parent if inner is not None else None

    # ``Path(__file__).resolve().parents[1]`` -- an ast.Subscript, and by far the
    # most common anchoring idiom in this repo (20+ tracked modules). Handling only
    # ``.parent`` would leave the scanner blind to the majority of real anchors
    # while its docstring claimed coverage.
    if isinstance(node, ast.Subscript):
        value = node.value
        if not (isinstance(value, ast.Attribute) and value.attr == "parents"):
            return None
        index = node.slice
        if not (isinstance(index, ast.Constant) and isinstance(index.value, int)):
            return None  # a slice or computed index: not statically resolvable
        inner = _eval_path(value.value, module_path, symbols)
        if inner is None:
            return None
        try:
            return inner.parents[index.value]
        except IndexError:
            return None

    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left = _eval_path(node.left, module_path, symbols)
        if left is None:
            return None
        right = node.right
        if isinstance(right, ast.Constant) and isinstance(right.value, str):
            return left / right.value
        return None

    return None


def _module_symbols(tree: ast.Module, module_path: Path) -> dict[str, Path]:
    """Module-level names bound to repo-anchored paths, resolved in source order."""
    symbols: dict[str, Path] = {}
    for stmt in tree.body:
        # AnnAssign as well as Assign: ``ROOT: Path = Path(__file__).parent`` is the
        # form this codebase's own strict-type-hints standard pushes authors toward,
        # so missing it would blind the scanner to exactly the well-written modules.
        if isinstance(stmt, ast.Assign):
            if len(stmt.targets) != 1:
                continue  # tuple unpacking: not resolved, see module docstring
            target, value = stmt.targets[0], stmt.value
        elif isinstance(stmt, ast.AnnAssign):
            if stmt.value is None:
                continue  # a bare annotation binds nothing
            target, value = stmt.target, stmt.value
        else:
            continue

        if not isinstance(target, ast.Name):
            continue
        resolved = _eval_path(value, module_path, symbols)
        if resolved is not None:
            symbols[target.id] = resolved
        else:
            # Rebinding to something unresolvable (``ROOT = Path(sys.argv[1])``)
            # must not leave the earlier repo-anchored value in place, or later
            # joins get attributed to a path this module no longer uses.
            symbols.pop(target.id, None)
    return symbols


def _anchored_media_references(py_files: list[str]) -> list[tuple[str, int, Path]]:
    """(source file, line, resolved path) for every repo-anchored media literal."""
    found: list[tuple[str, int, Path]] = []
    for rel in py_files:
        abs_path = _REPO_ROOT / rel
        try:
            source = abs_path.read_text(encoding="utf-8", errors="replace")
            # Parsing every tracked module surfaces other files' escape-sequence
            # warnings as this test's output. They are real, they belong to those
            # files, and reporting them here would just make the gate noisier
            # without telling anyone where to look.
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                tree = ast.parse(source)
        except (OSError, SyntaxError):
            continue
        symbols = _module_symbols(tree, abs_path)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)):
                continue
            right = node.right
            if not (isinstance(right, ast.Constant) and isinstance(right.value, str)):
                continue
            if Path(right.value).suffix.lower() not in _MEDIA_SUFFIXES:
                continue
            resolved = _eval_path(node, abs_path, symbols)
            if resolved is not None:
                found.append((rel, node.lineno, resolved))
    return found


def _missing_subjects(
    references: list[tuple[str, int, Path]],
    tracked: set[str],
    generated: dict[str, str],
    root: Path = _REPO_ROOT,
) -> list[str]:
    """The check itself, as a pure function so a toggle test can drive it on a
    synthetic corpus. A lock that can only be run against the real repo cannot be
    proven to fail, and an unfalsifiable lock is decoration.

    ``root`` is a parameter rather than the module constant so the toggle tests
    below can anchor their fixtures somewhere else entirely -- otherwise this
    scanner reads its own fixtures as real findings, and the alternative fix
    (exempting this file from the scan) would be a permanent hole in the check.
    """
    missing: list[str] = []
    for rel, lineno, path in references:
        try:
            repo_rel = str(path.relative_to(root)).replace("\\", "/")
        except ValueError:
            continue  # resolved outside the repo; not repo contents
        if repo_rel in generated or repo_rel in tracked:
            continue
        missing.append(f"{rel}:{lineno} reads {repo_rel}, which is not tracked")
    return missing


@pytest.fixture(scope="module")
def tracked() -> set[str]:
    return _tracked_files()


@pytest.fixture(scope="module")
def references(tracked: set[str]) -> list[tuple[str, int, Path]]:
    py_files = sorted(f for f in tracked if f.endswith(".py"))
    return _anchored_media_references(py_files)


def test_the_scanner_finds_the_known_probe_subjects(references):
    """Guard the scanner itself: if it silently stops resolving, everything below
    passes vacuously. These three are known repo-anchored reads."""
    resolved = {
        str(path.relative_to(_REPO_ROOT)).replace("\\", "/")
        for _, _, path in references
        if _REPO_ROOT in path.parents or path.parent == _REPO_ROOT
    }
    for expected in (
        "docs/performance/subjects/blarai_lighthouse3.png",
        "docs/performance/subjects/hand2.png",
        "branding/blair_glow.png",
        # The canary for the ``parents[N]`` idiom (scripts/measure_guest_parser_memory.py):
        # the scanner was blind to it at first review and nothing failed, because a
        # blind spot costs coverage silently rather than turning anything red.
        "services/cleaner/tests/fixtures/news_quantum.html",
    ):
        assert expected in resolved, (
            f"the scanner no longer resolves {expected}; it has stopped seeing the "
            "idiom it exists to check, and every other assertion here is now vacuous"
        )


def test_every_repo_anchored_media_read_is_tracked(references, tracked):
    missing = _missing_subjects(references, tracked, GENERATED)
    assert not missing, (
        "a committed script names a repo file that is not in the repo, so it cannot "
        "run from a clean clone and any measurement it recorded cannot be re-derived:\n  "
        + "\n  ".join(missing)
        + "\n\nCommit the subject (docs/performance/subjects/ is its home), or if the "
          "script GENERATES it, declare it in GENERATED with a reason."
    )


def test_the_generated_allowlist_has_not_rotted(references):
    """An exception nobody uses is an exception nobody re-argues. Every entry must
    still correspond to a live reference."""
    referenced = set()
    for _, _, path in references:
        try:
            referenced.add(str(path.relative_to(_REPO_ROOT)).replace("\\", "/"))
        except ValueError:
            continue
    stale = sorted(set(GENERATED) - referenced)
    assert not stale, (
        "GENERATED lists paths no committed script references any more; drop them "
        f"rather than carrying a standing exception for nothing: {stale}"
    )


def test_the_lock_FIRES_when_a_subject_is_untracked():
    """Principle 12: prove the probe FAILS when the lock is off.

    Drives the real check with one tracked reference and one untracked one, and
    demands it catch exactly the second. A scanner that quietly stopped resolving
    anything would keep the suite green forever -- which is #1318's failure mode
    wearing a passing test.
    """
    fake_root = Path("/fake-repo")
    tracked = {"docs/performance/subjects/hand2.png"}
    references = [
        ("scripts/probe.py", 10, fake_root / "docs" / "performance" / "subjects" / "hand2.png"),
        ("scripts/probe.py", 11, fake_root / "not_committed.png"),
    ]

    missing = _missing_subjects(references, tracked, generated={}, root=fake_root)

    assert len(missing) == 1, f"expected exactly the untracked subject, got {missing}"
    assert "not_committed.png" in missing[0]
    assert "scripts/probe.py:11" in missing[0]
    assert "hand2.png" not in missing[0], "the tracked subject must not be flagged"


def test_the_generated_exception_suppresses_and_only_that():
    """The allowlist must excuse the path it names and nothing adjacent to it."""
    fake_root = Path("/fake-repo")
    references = [
        ("scripts/bench.py", 5, fake_root / "docs" / "performance" / "_probe.png"),
        ("scripts/bench.py", 6, fake_root / "docs" / "performance" / "_other.png"),
    ]
    generated = {"docs/performance/_probe.png": "written by the benchmark"}

    missing = _missing_subjects(
        references, tracked=set(), generated=generated, root=fake_root
    )

    assert len(missing) == 1 and "_other.png" in missing[0], (
        f"the allowlist must excuse only its own entry, got {missing}"
    )


def test_the_scanner_resolves_the_parents_index_idiom(tmp_path):
    """``parents[N]`` is the repo's dominant anchoring idiom; the first version of
    this scanner could not see it, and nothing failed -- it just quietly covered
    less than its docstring claimed."""
    module = tmp_path / "pkg" / "probe.py"
    module.parent.mkdir(parents=True)
    module.write_text(
        "from pathlib import Path\n"
        "REPO = Path(__file__).resolve().parents[1]\n"
        "SUBJECT = REPO / 'docs' / 'shot.png'\n",
        encoding="utf-8",
    )
    symbols = _module_symbols(ast.parse(module.read_text(encoding="utf-8")), module)
    assert symbols["REPO"] == tmp_path
    assert symbols["SUBJECT"] == tmp_path / "docs" / "shot.png"


def test_the_scanner_resolves_annotated_module_constants(tmp_path):
    """``ROOT: Path = ...`` is what strict type hints produce. Missing it would
    blind the scanner to precisely the best-written modules."""
    module = tmp_path / "probe.py"
    module.write_text(
        "from pathlib import Path\n"
        "ROOT: Path = Path(__file__).resolve().parent\n"
        "SUBJECT: Path = ROOT / 'shot.png'\n",
        encoding="utf-8",
    )
    symbols = _module_symbols(ast.parse(module.read_text(encoding="utf-8")), module)
    assert symbols["SUBJECT"] == tmp_path / "shot.png"


def test_rebinding_a_root_to_something_unresolvable_clears_it(tmp_path):
    """Otherwise a later join is attributed to a path the module stopped using,
    and the scanner reports a finding against a file nobody reads."""
    module = tmp_path / "probe.py"
    module.write_text(
        "import sys\n"
        "from pathlib import Path\n"
        "ROOT = Path(__file__).resolve().parent\n"
        "ROOT = Path(sys.argv[1])\n"
        "SUBJECT = ROOT / 'shot.png'\n",
        encoding="utf-8",
    )
    symbols = _module_symbols(ast.parse(module.read_text(encoding="utf-8")), module)
    assert "ROOT" not in symbols, "the stale repo-anchored binding survived a rebind"
    assert "SUBJECT" not in symbols


def test_paths_outside_the_repo_are_not_this_tests_business():
    """tmp_path fixtures and runtime dirs are not repo contents; flagging them
    would make the lock noisy and it would get disabled."""
    references = [("shared/tests/test_x.py", 3, Path("/tmp/pytest-of-x/cat.png"))]
    assert _missing_subjects(
        references, tracked=set(), generated={}, root=Path("/fake-repo")
    ) == []
