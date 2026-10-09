"""Gate: the auditability card cannot disagree with the code it describes.

`test_auditability_screen_reads_the_card.py` binds the SCREEN to the CARD, link
by link, so the app cannot show something the card does not say. That gate held
perfectly and was no help at all, because the card itself went false.

The card merged at ``bdb0f11b`` (2026-09-18 03:08). #1542 merged at ``dc0b8623``
the same morning at 05:16 and put verdict receipts at both live doors. Nothing
re-opened the card, so for two days it told the operator that the tool-dispatch
door and the egress door wrote no durable record, while both wrote one. #1583
then put that document on a screen. The screen was correct about the card; the
card was wrong about the system; and the chain of gates between them could not
see it, because every link asserted agreement with the document rather than with
the code.

So this file asserts the other half, and it asserts it BOTH WAYS:

  * every ``source_door`` a production call site writes must appear in a card row
    that says Yes -- a door that starts recording and is not disclosed is
    under-claiming, which is the honest direction and still wrong
  * every door the card claims in a Yes row must exist as a production literal --
    the dishonest direction, a disclosure of coverage that is not there

Both directions matter and they fail for opposite reasons, so neither is a proxy
for the other.

The card is prose, and prose is the point: it carries the asymmetries a table
cannot (an allow that cannot be recorded REFUSES; a refusal that cannot be
recorded stands and logs). This gate does not try to check the prose. It checks
the one thing that is mechanically checkable and that went wrong: which doors
write, and which intervention points they write at.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_CARD = _REPO / "docs" / "governance" / "auditability-card.md"

# The receipt-writing helper. Its keyword is the door identity that lands in the
# record, so the literals passed to it ARE the set of recording doors.
_DOOR_KEYWORD = "source_door"
_POINT_KEYWORD = "intervention_point"


def _tracked_python_files() -> list[Path]:
    """Production Python, from git rather than from a directory walk.

    The primary checkout holds other sessions' worktrees under
    ``.claude/worktrees/``, each a full copy of this repo. A ``rglob`` from the
    repo root finds their call sites too and turns this gate into a statement
    about whatever else happens to be checked out (#1581, ``ae5292c4``).
    """
    out = subprocess.run(
        ["git", "ls-files", "*.py"],
        cwd=_REPO, capture_output=True, text=True, check=True,
    ).stdout.split("\n")
    return [
        _REPO / line for line in out
        if line
        and (line.startswith("services/") or line.startswith("shared/"))
        and "test" not in Path(line).name
        and "/tests/" not in line
    ]


def _string_literals_for(keyword: str) -> set[str]:
    """Every string literal passed as ``keyword=`` or defaulted to it.

    Defaults count: ``_audit_verdict``'s ``intervention_point`` defaults to
    ``pre_tool_call`` and no caller overrides it, so a call-site-only scan would
    report that BlarAI emits at zero points -- which is exactly the false claim
    the card carried.
    """
    found: set[str] = set()
    for path in _tracked_python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - a parse failure is another gate's
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg == keyword and isinstance(kw.value, ast.Constant):
                        if isinstance(kw.value.value, str):
                            found.add(kw.value.value)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = node.args
                names = [a.arg for a in args.args + args.kwonlyargs]
                defaults = list(args.defaults) + [
                    d for d in args.kw_defaults if d is not None
                ]
                for name, default in zip(names[-len(defaults):] if defaults else [],
                                         defaults):
                    if name == keyword and isinstance(default, ast.Constant):
                        if isinstance(default.value, str):
                            found.add(default.value)
    return found


def _section_one_rows(card_text: str) -> list[tuple[str, str]]:
    """(surface cell, writes-to-the-chain cell) for every row of the §1 table."""
    lines = card_text.split("\n")
    start = next(
        i for i, line in enumerate(lines)
        if line.startswith("## 1. Which actions are recorded?")
    )
    rows: list[tuple[str, str]] = []
    for line in lines[start:]:
        if line.startswith("## ") and not line.startswith("## 1."):
            break
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 3:
            continue
        if cells[0].startswith("---") or cells[0] == "**Surface**":
            continue
        if cells[0] == "Surface":
            continue
        rows.append((cells[0], cells[2]))
    return rows


def _says_yes(writes_cell: str) -> bool:
    return writes_cell.lstrip().startswith("**Yes")


@pytest.fixture(scope="module")
def card() -> str:
    return _CARD.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def rows(card: str) -> list[tuple[str, str]]:
    parsed = _section_one_rows(card)
    assert len(parsed) >= 5, (
        f"parsed only {len(parsed)} rows from the card's section 1 -- the table "
        "shape changed and this gate is now measuring nothing"
    )
    return parsed


# ---------------------------------------------------------------------------
# The two directions.
# ---------------------------------------------------------------------------


def test_every_recording_door_in_the_code_is_disclosed_as_recording(rows) -> None:
    """A door that starts writing receipts and is not disclosed.

    Under-claiming is the honest direction and still a defect: the card is how
    the operator learns what is covered, and coverage he is not told about is
    coverage he cannot rely on.
    """
    in_code = _string_literals_for(_DOOR_KEYWORD)
    assert in_code, (
        f"no {_DOOR_KEYWORD}= literal found in production -- either receipts "
        "were removed or this gate's extraction broke; both need looking at"
    )

    disclosed = " ".join(cell for _, cell in rows if _says_yes(cell))
    missing = sorted(door for door in in_code if door not in disclosed)
    assert not missing, (
        "production writes verdict receipts from doors the card does not "
        f"disclose as recording: {missing}. The card is the operator's "
        "coverage statement; a door recording in silence is undisclosed "
        "coverage.\nIn code: " + str(sorted(in_code))
    )


def test_every_door_the_card_claims_exists_in_the_code(rows) -> None:
    """The dishonest direction: disclosed coverage that is not there.

    This is the one that makes the card a false assurance rather than an
    incomplete one, and #1583 put the card on a screen.
    """
    in_code = _string_literals_for(_DOOR_KEYWORD)
    claimed: set[str] = set()
    for _, cell in rows:
        if _says_yes(cell):
            claimed.update(re.findall(rf'{_DOOR_KEYWORD}="([a-z_]+)"', cell))

    assert claimed, (
        "no Yes row in the card names a source_door. Either every door stopped "
        "recording, or the rows stopped citing the identifier this gate reads -- "
        "and a gate that silently matches nothing is the failure it exists to "
        "prevent. State the door in the cell as `source_door=\"name\"`."
    )
    phantom = sorted(door for door in claimed if door not in in_code)
    assert not phantom, (
        f"the card discloses coverage from doors that do not exist in "
        f"production: {phantom}. This is a false assurance on an operator-"
        "facing screen.\nIn code: " + str(sorted(in_code))
    )


def test_the_card_does_not_say_a_recording_door_writes_nothing(rows) -> None:
    """The precise shape of the two-day defect.

    The AO tool loop and the egress door each had a row reading 'No', naming
    #1542 as the gap that would close it, after #1542 had closed it.
    """
    in_code = _string_literals_for(_DOOR_KEYWORD)
    for surface, writes in rows:
        if _says_yes(writes):
            continue
        named = re.findall(rf'{_DOOR_KEYWORD}="([a-z_]+)"', surface + writes)
        contradicted = [door for door in named if door in in_code]
        assert not contradicted, (
            f"card row {surface[:60]!r} says it writes no record, but "
            f"{contradicted} is a live recording door in production"
        )


# ---------------------------------------------------------------------------
# Section 2 -- the count that read ZERO for two days.
# ---------------------------------------------------------------------------


def test_the_intervention_point_count_matches_the_code(card: str) -> None:
    """§2 states a count of points BlarAI emits at. It said ZERO after #1542.

    The default counts: nothing overrides ``intervention_point``, so a scan of
    call-site keywords alone would agree with the false claim.
    """
    points = _string_literals_for(_POINT_KEYWORD)
    live = {p for p in points if not p.endswith("_unknown")}
    assert live, "no intervention_point literal in production -- extraction broke"

    section = card.split("## 2.")[1].split("\n## ")[0]
    for point in sorted(live):
        assert f"`{point}`" in section, (
            f"production emits at {point!r} and the card's section 2 does not "
            f"name it. Section 2 reads:\n{section[:400]}"
        )

    words = {1: "ONE", 2: "TWO", 3: "THREE", 4: "FOUR"}
    expected = words.get(len(live))
    if expected is not None:
        assert f"at {expected} of the eight" in section, (
            f"production emits at {len(live)} intervention point(s) "
            f"({sorted(live)}), so section 2 should say 'at {expected} of the "
            "eight'. It does not. This is the sentence that said ZERO for two "
            "days after #1542 made it one."
        )


# ---------------------------------------------------------------------------
# Toggle: prove the gate FAILS when the card is wrong (security_by_design 12).
# ---------------------------------------------------------------------------


def test_the_gate_fails_on_a_card_that_hides_a_recording_door(card: str) -> None:
    """Without this, a passing gate is indistinguishable from an unreachable one."""
    in_code = sorted(_string_literals_for(_DOOR_KEYWORD))
    victim = in_code[0]
    broken = card.replace(f'{_DOOR_KEYWORD}="{victim}"', "")
    rows = _section_one_rows(broken)

    disclosed = " ".join(cell for _, cell in rows if _says_yes(cell))
    assert victim not in disclosed, (
        f"the toggle did not actually remove {victim} from the disclosed set, "
        "so it proves nothing"
    )


def test_the_gate_fails_on_a_card_claiming_a_door_that_does_not_exist(card: str) -> None:
    """The other direction's toggle."""
    in_code = _string_literals_for(_DOOR_KEYWORD)
    broken = card.replace(
        f'{_DOOR_KEYWORD}="', f'{_DOOR_KEYWORD}="ghost_door_not_in_code_', 1
    )
    rows = _section_one_rows(broken)
    claimed: set[str] = set()
    for _, cell in rows:
        if _says_yes(cell):
            claimed.update(re.findall(rf'{_DOOR_KEYWORD}="([a-z_]+)"', cell))

    phantom = [door for door in claimed if door not in in_code]
    assert phantom, (
        "the toggle did not produce a phantom door, so the phantom check is "
        "not reaching the card's cells"
    )


def test_the_extraction_is_not_vacuous() -> None:
    """The gate reads real files and finds real call sites.

    A ``git ls-files`` filter that stopped matching would make every assertion
    above pass against an empty set.
    """
    files = _tracked_python_files()
    assert len(files) > 50, f"only {len(files)} production Python files matched"
    assert any(
        f.name == "entrypoint.py" and "assistant_orchestrator" in str(f)
        for f in files
    ), "the AO entrypoint -- which holds every recording call site -- was not scanned"
