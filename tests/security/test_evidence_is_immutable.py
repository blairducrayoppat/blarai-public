"""DoD capability 16's wider class — a test may not pin evidence to a tree the fleet rewrites.

**The incident this exists for, and it is twelve hours old.** On 2026-08-08 three tests were
written asserting exact figures against `C:/Users/mrbla/projects/battery-b9-pottery-site` —
the real delivered pottery site, which was the obvious subject because it was the tree in front
of the author. They passed. At 04:56 the next morning they were red on `main`, with nothing
about the code under test changed: the overnight battery had rebuilt that directory.

`~/projects/` is the coder fleet's WORKING AREA. Every dispatch archives what is there and
creates a fresh sandbox (`launcher.log`: *"archived previous battery-b9-pottery-site"*,
*"fresh sandbox: battery-b9-pottery-site"*). A figure measured there is true until the next run
and then silently is not — evidence by reference, where the reference moves.

That is capability 16 (#1318, *"every recorded measurement is reproducible"*) committed by
tests written to enforce it. The existing control
(`tests/security/test_measurement_subjects.py`) covers the known class — recorded probes naming
image subjects never committed. This covers the other direction: a test whose subject is a live
working directory.

**The immutable alternative already exists and costs nothing.** Every battery night archives its
delivered repositories to `state/battery/night-<stamp>/repos-archived/<repo>` — dated, written
once, never rewritten. That is what `repos-archived` is FOR. The three broken tests were fixed by
retargeting to `night-20260808-230002/repos-archived/battery-b9-pottery-site`, whose findings are
byte-identical to what the live tree held at the moment they were authored.

**The rule this enforces:** assert exact numbers only against artifacts nothing rewrites. A live
working directory is fine to explore, and useless to pin.

**Honest limit.** This is a source-level check for one specific mutable root on one machine. It
cannot see a test that reaches a mutable tree by a path it computes at runtime, and it says
nothing about mutable state reached through an environment variable. It is a ratchet against the
next instance of a defect that has now happened once, not a proof that evidence is immutable
everywhere.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]

#: Directories whose contents the coder fleet rewrites. A dispatch archives whatever is here
#: and creates a fresh sandbox, so anything measured here expires at the next run.
_MUTABLE_ROOTS = ("users/mrbla/projects", "users\\mrbla\\projects")

#: Where the test suites live. Production code may legitimately compute paths into the working
#: area — that is its job. Only TESTS are forbidden from pinning evidence there.
_TEST_DIRS = (_REPO / "tests", _REPO / "shared" / "tests", _REPO / "services", _REPO / "launcher")

#: Calls that turn a string into a filesystem READ. A bare literal handed to a pure function
#: (`_is_card_driven("C:/Users/mrbla/projects/x", None)`) never touches disk and is not a
#: subject — flagging it would be the false-positive class that gets a gate muted.
_PATH_CONSTRUCTORS = frozenset({"Path", "PurePath", "PosixPath", "WindowsPath", "open"})

#: Tests exempted, each with the REASON. Deny-by-default: anything not here must not construct
#: a path into a mutable root. An entry is an argument somebody made in writing.
_ALLOWLIST: dict[str, str] = {}


def _literal_is_mutable(value: str) -> bool:
    lowered = value.replace("\\", "/").lower()
    return any(root.replace("\\", "/") in lowered for root in _MUTABLE_ROOTS)


def _offending_sites(tree: ast.AST) -> list[int]:
    """Line numbers where a mutable-root literal is handed to a path constructor."""
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = getattr(func, "id", None) or getattr(func, "attr", None)
        if name not in _PATH_CONSTRUCTORS:
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                if _literal_is_mutable(arg.value):
                    lines.append(node.lineno)
    return lines


def _module_constant_sites(tree: ast.AST) -> list[int]:
    """MODULE-LEVEL constants assigned a mutable-root literal.

    `_LIVE_SITE = Path("C:/Users/mrbla/projects/…")` is the exact shape that broke, and a
    constant reads as settled fact at the top of a file, so it earns its own check.

    MODULE LEVEL ONLY — `tree.body`, never `ast.walk`. A path string inside a function is test
    DATA, not a subject: `test_battery_runner.py` builds `{"repo": "C:/Users/mrbla/projects/
    real-repo"}` precisely to assert that such a repo is REJECTED, and flagging that would be
    the false-positive class this module's own docstring warns about. Caught on the first run
    of this gate, against those very tests.
    """
    lines: list[int] = []
    for node in getattr(tree, "body", []):
        if not isinstance(node, ast.Assign):
            continue
        for value in ast.walk(node.value):
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                if _literal_is_mutable(value.value):
                    lines.append(node.lineno)
    return lines


def _scan() -> tuple[dict[str, list[int]], list[str]]:
    offenders: dict[str, list[int]] = {}
    parse_errors: list[str] = []
    for base in _TEST_DIRS:
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("test_*.py")):
            if "__pycache__" in path.parts:
                continue
            rel = path.relative_to(_REPO).as_posix()
            # This file names the mutable root in its own constants and toggle-proof, so it
            # matches itself. The same self-match cost a false battery-launch confirmation
            # earlier the same night: a detector's own text is not evidence of the thing.
            if path.resolve() == Path(__file__).resolve():
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except (OSError, SyntaxError) as exc:
                parse_errors.append(f"{rel}: {exc}")
                continue
            hits = sorted(set(_offending_sites(tree)) | set(_module_constant_sites(tree)))
            if hits:
                offenders[rel] = hits
    return offenders, parse_errors


def test_no_test_pins_evidence_to_a_tree_the_fleet_rewrites() -> None:
    """A test may not construct a path into `~/projects/` — that tree is rewritten nightly.

    If this fails on a test you just wrote: retarget it to the archived snapshot under
    `state/battery/night-<stamp>/repos-archived/<repo>`, which is dated and never rewritten.
    `shared/tests/test_image_placement.py` is the worked example — it was the offender, and its
    `_LIVE_SITE` constant now carries the reasoning in its own docstring.
    """
    offenders, parse_errors = _scan()
    assert not parse_errors, f"test surface failed to parse: {parse_errors}"

    unexplained = {f: lines for f, lines in offenders.items() if f not in _ALLOWLIST}
    assert unexplained == {}, (
        "these tests pin evidence to the fleet's working area, which is rewritten on every "
        "dispatch — the figures they assert expire at the next run (DoD capability 16, "
        "#1318):\n  "
        + "\n  ".join(f"{f}: line(s) {lines}" for f, lines in sorted(unexplained.items()))
        + "\n\nRetarget to state/battery/night-*/repos-archived/, or add an _ALLOWLIST entry "
        "with a written reason."
    )


def test_the_allowlist_does_not_go_stale() -> None:
    """An exemption outliving its cause is an exemption nobody argued for."""
    offenders, _ = _scan()
    stale = [f for f in _ALLOWLIST if f not in offenders]
    assert stale == [], f"allowlisted tests that no longer offend — remove them: {stale}"


def test_the_gate_catches_the_shape_that_actually_broke() -> None:
    """Toggle proof against the REAL 2026-08-08 line, not an invented one.

    A green suite here is worthless unless the detector fires on the artifact that caused the
    incident. This is the constant as it was written, verbatim.
    """
    broke = ast.parse('_LIVE_SITE = Path("C:/Users/mrbla/projects/battery-b9-pottery-site")\n')
    assert _module_constant_sites(broke), "the gate cannot see the line that actually broke"

    fixed = ast.parse(
        '_LIVE_SITE = Path("C:/Users/mrbla/agentic-setup/state/battery/'
        'night-20260808-230002/repos-archived/battery-b9-pottery-site")\n'
    )
    assert not _module_constant_sites(fixed), "the archived path must not be flagged"


def test_a_bare_literal_to_a_pure_function_is_not_flagged() -> None:
    """Precision: a path STRING handed to a pure function never touches disk.

    `test_advanced_intake.py` passes exactly such a literal to `_is_card_driven`. Flagging it
    would be the false-positive class that gets a gate muted, and a muted gate is worse than
    none.
    """
    pure = ast.parse('_is_card_driven("C:/Users/mrbla/projects/battery-b5-habit-web", None)\n')
    assert not _offending_sites(pure)


def test_every_allowlist_entry_gives_a_reason() -> None:
    empty = [f for f, reason in _ALLOWLIST.items() if len(reason.strip()) < 20]
    assert empty == [], f"allowlist entries with no real reason: {empty}"


# ---------------------------------------------------------------------------
# THE BEHAVIOURAL HALF (#1355 follow-up, 2026-08-14, DoD row 16)
# ---------------------------------------------------------------------------
# Everything above scans SOURCE for path literals. That is the right control for the shape that
# broke on 2026-08-09, and it is blind to the shape that broke on 08-14: agentic-setup's
# verify-website-review-loop.ps1 reached the live sandbox through a helper call, with no such
# path anywhere in its text. Row 16 named that half — "mutable state reached by a computed path
# or an environment variable" — as uncontrolled.
#
# The root conftest now watches the PROCESS instead of the code: a CPython audit hook sees every
# `open`, whatever expression produced the path. These tests drive its predicate directly,
# because a control that cannot be exercised cannot be shown to block (principle 12).


def _predicate():
    """The conftest's extracted predicate, imported the way a reader would find it."""
    import conftest  # the repo-root conftest, on sys.path during a pytest run

    return conftest.is_fleet_working_tree_path


def test_the_audit_predicate_catches_the_fleet_working_tree() -> None:
    """Every spelling of the mutable root, including one no source-scan could see."""
    hit = _predicate()
    assert hit(r"C:\Users\mrbla\projects\battery-b9-pottery-site\public\index.html")
    assert hit("C:/Users/mrbla/projects/battery-b9-pottery-site/public/index.html")
    assert hit("c:/users/MRBLA/Projects/whatever.txt"), "case must not matter"
    # The 08-14 shape: assembled at runtime, no literal in any source file.
    assert hit("C:/Users/mrbla/" + "pro" + "jects" + "/x/y.html")


def test_the_audit_predicate_does_not_fire_on_the_archive_or_the_repo() -> None:
    """The toggle. A predicate that says yes to everything blocks nothing and proves nothing."""
    miss = _predicate()
    assert not miss(
        "C:/Users/mrbla/agentic-setup/state/battery/night-20260810-123008/"
        "repos-archived/battery-b9-pottery-site/public/index.html"
    ), "an ARCHIVED snapshot is immutable and is the correct subject — it must not be flagged"
    assert not miss("C:/Users/mrbla/BlarAI/shared/fleet/oracle_qa.py")
    assert not miss("C:/Users/mrbla/agentic-setup/scripts/fleet-lib.ps1")
    assert not miss(r"C:\Temp\pytest-of-mrbla\test_thing0\public\index.html")
    assert not miss(None), "a non-str audit argument must not raise inside the hook"
    assert not miss(b"C:/Users/mrbla/projects/x"), "bytes are not matched, and must not raise"
