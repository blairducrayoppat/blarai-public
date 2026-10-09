"""Gate: moving files inside the operator's data directory cannot escape it,
cannot overwrite, and moves exactly what was planned (#1568).

Driven through a REAL temporary file system, never the operator's own
directory. Path escape is the entire threat model here — this is the
assistant's first file surface — so most of this file is attempts to get out.

Each lock ships with a toggle proving it fails when the control is off.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

from shared.governance.userdata_move import (
    USERDATA_MAX_MOVES,
    MoveError,
    apply_moves,
    plan_moves,
    resolve_within,
)


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    """A data directory with three loose files and an 'archive' folder."""
    (tmp_path / "archive").mkdir()
    for name in ("notes-a.txt", "notes-b.txt", "other.md"):
        (tmp_path / name).write_text(name, encoding="utf-8")
    return tmp_path


def _names(root: Path) -> set[str]:
    return {p.name for p in root.rglob("*") if p.is_file()}


# ---------------------------------------------------------------------------
# Containment — the threat model.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "escape",
    ["../outside.txt", "../../etc/passwd", "archive/../../out.txt", ".."],
)
def test_traversal_out_of_the_directory_is_refused(root: Path, escape: str) -> None:
    with pytest.raises(MoveError, match="outside your data folder"):
        resolve_within(root, escape)


def test_a_path_inside_is_allowed(root: Path) -> None:
    """Toggle: the refusals above are containment, not a function that always
    raises."""
    assert resolve_within(root, "archive") == (root / "archive").resolve()
    assert resolve_within(root, "notes-a.txt") == (root / "notes-a.txt").resolve()


# A SYMLINK TEST WAS REMOVED HERE, deliberately, and this note is its record.
#
# It created a symlink out of the data directory and required the refusal. On
# this machine `os.symlink` raises WinError 1314 -- the privilege is granted to
# the Administrators group but not ENABLED in the token, and Python does not
# enable it -- so it skipped on every run, elevated or not. The standing gate's
# bar is ZERO skipped, and a permanent skip in a zero-skip gate is a defect
# however well explained.
#
# Nothing is lost. The property it claimed is covered three ways, two of them
# stronger:
#
#   * `test_containment_compares_the_RESOLVED_path_not_the_name` below asserts
#     the half that is THIS code rather than the operating system -- that the
#     check compares the resolved location, not the name.
#   * `test_apply_moves_RE_VERIFIES_containment_it_does_not_trust_the_plan`
#     covers the case that actually matters: a directory swapped underneath
#     between the plan and the move.
#   * The verification review built the REAL attack on this machine -- plan two
#     moves, remove the destination, `mklink /J` it to an outside folder, call
#     `apply_moves` -- and it was REFUSED with both files still inside. An NTFS
#     junction needs no privilege, so the escape a symlink would have tested is
#     reachable here by another route, and that route is blocked.


def test_containment_compares_the_RESOLVED_path_not_the_name(root: Path, monkeypatch) -> None:
    """The half of the symlink case that is MY code rather than the OS.

    A link whose target is outside is caught only if the check resolves first
    and compares the real location. Whether this machine can create a symlink
    is not something this file can control; whether `resolve_within` compares
    the resolved path is, so that is what is asserted -- by making resolution
    report an outside location and requiring the refusal.
    """
    outside = (root.parent / "somewhere_else").resolve()
    real_resolve = Path.resolve

    def _resolve(self, *a, **kw):
        # Only the candidate lies; the root must still resolve truthfully, or
        # the test would pass by breaking the comparison rather than the path.
        if self.name == "looks_inside":
            return outside
        return real_resolve(self, *a, **kw)

    monkeypatch.setattr(Path, "resolve", _resolve)
    with pytest.raises(MoveError, match="outside your data folder"):
        resolve_within(root, "looks_inside")


def test_that_containment_check_can_PASS_when_resolution_stays_inside(root: Path) -> None:
    """Toggle for the test above: without it, a `resolve_within` that always
    raised would satisfy every refusal assertion in this file."""
    assert resolve_within(root, "archive").name == "archive"


def test_a_destination_outside_is_refused_BEFORE_matching(root: Path) -> None:
    """The destination is checked first, so a request aimed outside is refused
    without the pattern ever being evaluated."""
    with pytest.raises(MoveError, match="outside your data folder"):
        plan_moves(root, "*.txt", "../elsewhere")


def test_an_absolute_pattern_is_refused(root: Path) -> None:
    with pytest.raises(MoveError, match="must stay inside"):
        plan_moves(root, os.path.abspath(os.sep + "tmp") + os.sep + "*", "archive")


def test_a_climbing_pattern_is_refused(root: Path) -> None:
    with pytest.raises(MoveError, match="must stay inside"):
        plan_moves(root, "../*.txt", "archive")


# ---------------------------------------------------------------------------
# The plan.
# ---------------------------------------------------------------------------


def test_an_empty_pattern_matches_NOTHING_not_everything(root: Path) -> None:
    with pytest.raises(MoveError, match="matches nothing, never everything"):
        plan_moves(root, "", "archive")
    with pytest.raises(MoveError, match="no destination"):
        plan_moves(root, "*.txt", "")


def test_the_plan_is_deterministic_and_sorted(root: Path) -> None:
    first = plan_moves(root, "*.txt", "archive")
    second = plan_moves(root, "*.txt", "archive")

    assert first == second, "the same pattern gave two different plans"
    assert [m.source.name for m in first] == ["notes-a.txt", "notes-b.txt"]


def test_planning_moves_nothing(root: Path) -> None:
    before = _names(root)
    plan_moves(root, "*.txt", "archive")
    assert _names(root) == before, "planning is not a dry run if it moves files"


def test_the_toggle_would_SEE_a_move(root: Path) -> None:
    """Without this, `_names` could be measuring something that never changes."""
    before = _names(root)
    apply_moves(plan_moves(root, "*.txt", "archive"), root)
    assert _names(root) == before, "names are unchanged by a move; only paths move"
    assert (root / "archive" / "notes-a.txt").is_file()
    assert not (root / "notes-a.txt").exists()


def test_directories_and_symlinks_are_not_moved(root: Path) -> None:
    """Only regular files. Anything whose move means something other than 'this
    file is now there' is skipped rather than guessed at."""
    (root / "a-folder").mkdir()
    plan = plan_moves(root, "*", "archive")
    assert all(m.source.is_file() for m in plan)
    assert "a-folder" not in {m.source.name for m in plan}


def test_a_file_already_in_the_destination_is_not_re_moved(root: Path) -> None:
    (root / "archive" / "already.txt").write_text("x", encoding="utf-8")
    plan = plan_moves(root, "**/*.txt", "archive")
    assert "already.txt" not in {m.source.name for m in plan}


# ---------------------------------------------------------------------------
# Collisions — refused, never renamed, never overwritten.
# ---------------------------------------------------------------------------


def test_a_destination_collision_REFUSES_the_whole_plan(root: Path) -> None:
    (root / "archive" / "notes-a.txt").write_text("PRECIOUS", encoding="utf-8")

    with pytest.raises(MoveError, match="already exists"):
        plan_moves(root, "*.txt", "archive")

    assert (root / "archive" / "notes-a.txt").read_text(encoding="utf-8") == "PRECIOUS"
    assert (root / "notes-b.txt").is_file(), "an unrelated file was moved anyway"


def test_two_sources_that_would_COLLIDE_WITH_EACH_OTHER_refuse(root: Path) -> None:
    """Not a pre-existing file — two matches whose basenames are the same."""
    (root / "sub").mkdir()
    (root / "sub" / "notes-a.txt").write_text("other one", encoding="utf-8")

    with pytest.raises(MoveError, match="would both become"):
        plan_moves(root, "**/notes-a.txt", "archive")


def test_without_a_collision_the_plan_succeeds(root: Path) -> None:
    """Toggle for both collision checks."""
    assert len(plan_moves(root, "*.txt", "archive")) == 2


def test_a_collision_appearing_AFTER_the_plan_refuses_mid_flight(root: Path) -> None:
    """The window between planning and moving is small but real."""
    plan = plan_moves(root, "*.txt", "archive")
    (root / "archive" / "notes-b.txt").write_text("PRECIOUS", encoding="utf-8")

    with pytest.raises(MoveError, match="appeared in the destination"):
        apply_moves(plan, root)

    assert (root / "archive" / "notes-b.txt").read_text(encoding="utf-8") == "PRECIOUS"
    assert (root / "archive" / "notes-a.txt").is_file(), (
        "the first move should have completed; a half-finished set is "
        "recoverable and is reported"
    )


def test_a_source_that_VANISHED_refuses(root: Path) -> None:
    plan = plan_moves(root, "*.txt", "archive")
    (root / "notes-a.txt").unlink()

    with pytest.raises(MoveError, match="no longer there"):
        apply_moves(plan, root)


# ---------------------------------------------------------------------------
# The cap.
# ---------------------------------------------------------------------------


def test_a_plan_over_the_cap_REFUSES_and_is_never_truncated(root: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "shared.governance.userdata_move.USERDATA_MAX_MOVES", 1
    )
    with pytest.raises(MoveError, match="over the"):
        plan_moves(root, "*.txt", "archive")


def test_under_the_cap_still_plans(root: Path) -> None:
    """Toggle for the cap."""
    assert USERDATA_MAX_MOVES >= 2
    assert len(plan_moves(root, "*.txt", "archive")) == 2


# ---------------------------------------------------------------------------
# Moves only — structurally.
# ---------------------------------------------------------------------------


#: Every name that can destroy or overwrite a file, whatever it is called
#: through. The first version listed nine and matched only ``ast.Attribute``
#: calls, so 13 of 14 destructive mutations passed it -- including
#: ``p.replace(dst)``, a ONE-TOKEN edit from ``rename`` that silently destroys
#: the destination on Windows, and every bare-name form
#: (``from os import remove; remove(p)``).
_DESTRUCTIVE_NAMES: frozenset[str] = frozenset({
    "unlink", "rmdir", "rmtree", "remove", "removedirs", "truncate",
    "replace",          # silently overwrites the destination on Windows
    "write_text", "write_bytes", "open",
    "copy", "copy2", "copyfile", "copytree", "move",
    # Directory creation was removed as an undeclared capability; without these
    # the gate does not lock the thing the removal achieved.
    "mkdir", "makedirs", "symlink_to", "hardlink_to", "touch",
    "system", "popen", "run", "call", "check_call", "check_output",
})

#: Modules whose import into this file would be a capability change.
_DESTRUCTIVE_MODULES: frozenset[str] = frozenset({
    "shutil", "subprocess", "os",
})


def _called_names(tree: ast.AST) -> set[str]:
    """Every name this module CALLS, however it is spelled.

    Both `obj.method()` and a bare `method()`, so an aliased or
    `from`-imported destructive function cannot hide behind the call form.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            names.add(func.attr)
        elif isinstance(func, ast.Name):
            names.add(func.id)
    return names


def test_the_module_contains_no_way_to_DELETE_or_OVERWRITE_a_file() -> None:
    """Deleting is a separate capability decision and is absent, not disabled.

    Checked against the syntax tree with both call forms and the imports,
    because the previous version matched a short list of attribute spellings
    and let through `replace`, `shutil.move`, `os.system('del ...')`, every
    bare-name import, and `getattr(p, 'unl'+'ink')()`.

    It cannot catch a fully dynamic `getattr` with a computed name. That is
    stated rather than papered over: this gate makes a destructive capability
    impossible to add ACCIDENTALLY, which is what it is for. A deliberate
    obfuscated one is a different problem and review is its control.
    """
    import inspect

    import shared.governance.userdata_move as mod

    tree = ast.parse(inspect.getsource(mod))
    called = _called_names(tree)

    found = sorted(called & _DESTRUCTIVE_NAMES)
    assert not found, (
        f"userdata_move calls {found}. It moves files and does nothing else; "
        "a delete or an overwrite here is a capability nobody approved."
    )

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
            # `from os import remove` — the NAME matters, not just the module.
            found_from = sorted(
                {a.name for a in node.names} & _DESTRUCTIVE_NAMES
            )
            assert not found_from, (
                f"userdata_move imports {found_from}; a destructive function "
                "imported by name is one call away from being used"
            )
    leaked = sorted(imported & _DESTRUCTIVE_MODULES)
    assert not leaked, (
        f"userdata_move imports {leaked}. Moving files needs pathlib and "
        "nothing else; these modules carry delete and overwrite."
    )

    assert "rename" in called, (
        "the module no longer renames anything, so the checks above are "
        "passing against a module that does nothing"
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "    p.replace(q)",
        "    from os import remove",
        "    import shutil",
        "    import subprocess",
        "    p.unlink()",
        "    p.write_text('')",
    ],
)
def test_the_destructive_gate_FAILS_on_each_mutation(mutation: str) -> None:
    """Toggle, on a COPY of the source. The previous gate passed 13 of 14 of
    these, which is why it is worth proving each one red."""
    import inspect

    import shared.governance.userdata_move as mod

    source = inspect.getsource(mod)
    anchor = "    moved = 0\n"
    mutated = source.replace(anchor, anchor + mutation + "\n", 1)
    assert mutated != source, "the mutation anchor is gone; this proves nothing"
    tree = ast.parse(mutated)

    called = _called_names(tree)
    imported: set[str] = set()
    from_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
            from_names.update(a.name for a in node.names)

    caught = bool(
        (called & _DESTRUCTIVE_NAMES)
        or (imported & _DESTRUCTIVE_MODULES)
        or (from_names & _DESTRUCTIVE_NAMES)
    )
    assert caught, f"the gate does not catch {mutation.strip()!r}"


# ---------------------------------------------------------------------------
# The tool layer — dormancy, validation, and the tier.
# ---------------------------------------------------------------------------


def test_the_tool_is_dormant_until_a_runner_is_registered() -> None:
    """With no runner the registry body resolves no path at all."""
    from services.assistant_orchestrator.src import tools

    tools.clear_organise_userdata_runner()
    assert tools.execute(
        "organise_userdata", '{"pattern": "*.txt", "destination": "archive"}'
    ) == tools.ORGANISE_USERDATA_UNAVAILABLE_NOTICE


def test_the_shipped_config_has_organising_disabled() -> None:
    import tomllib

    repo = Path(__file__).resolve().parents[2]
    cfg = tomllib.loads(
        (repo / "services" / "assistant_orchestrator" / "config" / "default.toml")
        .read_text(encoding="utf-8")
    )
    assert cfg["organise_userdata"]["enabled"] is False, (
        "organise_userdata is LIVE in the shipped config. It is the assistant's "
        "first file surface — flipping it is an LA-present ceremony."
    )


@pytest.mark.parametrize(
    "bad",
    ['{"pattern": "", "destination": "archive"}',
     '{"pattern": "*.txt", "destination": ""}',
     '{"pattern": "*.txt"}',
     "not json",
     "[]"],
)
def test_a_malformed_request_is_refused_before_any_path_is_resolved(bad: str) -> None:
    from services.assistant_orchestrator.src import tools

    assert tools.parse_organise_args(bad) == {}


@pytest.mark.parametrize(
    "value",
    [["a", "b"], {"k": 1}, True, 123, 1.5, None],
)
def test_a_non_STRING_argument_is_refused_not_COERCED(value) -> None:
    """`str(...)` turned any JSON type into a Python repr and handed it to
    glob(): a list became "['a', 'b']", True became "True". That is coercion
    where `security_by_design` 7 asks for validation."""
    import json as _json

    from services.assistant_orchestrator.src import tools

    args = _json.dumps({"pattern": value, "destination": "archive"})
    assert tools.parse_organise_args(args) == {}


def test_an_over_LONG_path_is_refused_at_the_boundary() -> None:
    """It could be PLANNED and never moved, so the operator was asked to
    approve a move that could not physically happen — and the failure then
    surfaced as a wrong message."""
    import json as _json

    from services.assistant_orchestrator.src import tools

    args = _json.dumps({"pattern": "x" * 300, "destination": "archive"})
    assert tools.parse_organise_args(args) == {}


def test_a_NUL_in_a_path_is_refused_at_the_boundary() -> None:
    import json as _json

    from services.assistant_orchestrator.src import tools

    args = _json.dumps({"pattern": "a" + chr(0) + "b", "destination": "archive"})
    assert tools.parse_organise_args(args) == {}


def test_a_well_formed_request_IS_accepted() -> None:
    """Toggle for every refusal above."""
    from services.assistant_orchestrator.src import tools

    assert tools.parse_organise_args(
        '{"pattern": "*.txt", "destination": "archive"}'
    ) == {"pattern": "*.txt", "destination": "archive"}


def test_organise_userdata_is_DANGEROUS_by_declaration() -> None:
    from services.assistant_orchestrator.src import tools

    assert "organise_userdata" in tools._TOOL_RISK_TIER
    assert tools.risk_tier("organise_userdata") is tools.RiskTier.DANGEROUS


def test_a_destination_that_does_not_exist_is_REFUSED_not_created(root: Path) -> None:
    """Creating directory trees is a capability nobody declared — not in the
    tool schema, the capability text, or the config comment."""
    with pytest.raises(MoveError, match="does not exist"):
        plan_moves(root, "*.txt", "new/deep/tree")


def test_an_existing_destination_still_plans(root: Path) -> None:
    """Toggle for the refusal above."""
    assert len(plan_moves(root, "*.txt", "archive")) == 2


def test_apply_moves_RE_VERIFIES_containment_it_does_not_trust_the_plan(
    root: Path, monkeypatch
) -> None:
    """The whole threat model used to rest on ONE lock inside plan_moves, and a
    directory junction swapped over the destination between the plan and the
    approval escaped it. A junction needs no privilege to create.
    """
    plan = plan_moves(root, "*.txt", "archive")
    outside = (root.parent / "escaped_target").resolve()
    outside.mkdir(exist_ok=True)

    real_resolve = Path.resolve

    def _resolve(self, *a, **kw):
        # Stand in for the reparse point: the destination now really lives
        # outside, exactly as a swapped junction would make it.
        if self.name == "archive" or self.parent.name == "archive":
            return outside / self.name
        return real_resolve(self, *a, **kw)

    monkeypatch.setattr(Path, "resolve", _resolve)
    with pytest.raises(MoveError, match="changed underneath"):
        apply_moves(plan, root)


def test_an_os_failure_is_a_MoveError_that_says_how_many_moved(
    root: Path, monkeypatch
) -> None:
    """A bare OSError escaped to a caller catching only MoveError, so an
    ordinary locked file reported "Nothing was moved" AFTER one had moved."""
    plan = plan_moves(root, "*.txt", "archive")
    calls = {"n": 0}
    real_rename = Path.rename

    def _rename(self, target):
        calls["n"] += 1
        if calls["n"] == 2:
            raise PermissionError(32, "The process cannot access the file")
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", _rename)
    with pytest.raises(MoveError, match="stopped after moving 1 of 2"):
        apply_moves(plan, root)
