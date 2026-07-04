"""Deterministic XAML layout linter for the headless-coding dispatch design loop.

**Why this exists (the load-bearing rationale).** The design loop's only judge used to
be a vision-language model (VLM) critiquing a screenshot. A small VLM is *lenient*: it
false-passed a visibly broken calculator grid ("neatly aligned in a clean grid" over a
grid that was not). The project's own master lesson — *never trust the model's
self-report; verify the artifact with an objective tool* — was being honored for code
(compile + tests + structural gates) but NOT for design. This module is the missing
deterministic gate: it parses the generated XAML and flags geometry defects with ZERO
model judgement, so a broken layout is caught even when the VLM says PASS.

It runs BEFORE the VLM in the loop and needs no screenshot (pure markup inspection), so
it also fires on the structural-only floor (no pixels). Its findings (a) force a coder
FIX on a HARD signal regardless of the VLM verdict, and (b) are fed into the VLM prompt
as "known issues to confirm fixed" (Lever C). The operator's eye remains the final
aesthetic judge — this gate catches GEOMETRY (overlap, mis-sizing, bad indices), not
taste (colour harmony, hierarchy).

**Scope of the rules** (precision-first — a false positive would nag the coder into
"fixing" correct layout, so each rule is guarded to fire only on a real defect):

  overlap                       Two non-spanning sibling children occupy the same Grid
                                cell (intersecting row x col regions) in a Grid that
                                declares Row/Column definitions. They render stacked.
                                (The rocket-calc display + keypad both on Grid.Row=1.)
  fixed-dim-in-flexible-cell    A child sets a fixed numeric Width in a '*'/'Auto' column
                                (or Height in a '*'/'Auto' row) without explicitly
                                aligning, so it cannot fill the cell -> gaps / misaligned
                                columns. (The rocket-calc '0' Width=130, '=' Height=130.)
  grid-index-out-of-range       Grid.Row/Column points past the declared definitions; WinUI
                                clamps it into the last cell -> unexpected overlap.
  grid-children-without-defs    A Grid has children with Grid.Row/Column >= 1 but declares
                                NO Row/Column definitions, so every child collapses to cell
                                (0,0) and stacks.

**Fail-soft contract:** any parse failure yields a single low-severity 'unparseable'
finding (never an exception) so the loop degrades gracefully — the build already compiled
the XAML, so this is belt-and-suspenders.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree as ET

SEVERITY_HIGH = "high"
SEVERITY_LOW = "low"

# A finding is HARD (forces a FIX iteration) iff its severity is HIGH.
_HARD_SEVERITIES = {SEVERITY_HIGH}


@dataclass(frozen=True)
class Finding:
    """One deterministic layout defect.

    Attributes:
        rule: stable rule id (overlap / fixed-dim-in-flexible-cell / ...).
        severity: ``high`` (a real geometry bug -> forces a FIX) or ``low`` (advisory).
        message: actionable, human/coder-readable description of what to fix.
        element: a short identifier for the offending element (x:Name or tag).
        file: source .xaml file the finding came from ("" for an inline lint).
    """

    rule: str
    severity: str
    message: str
    element: str
    file: str = ""


# ---------------------------------------------------------------------------
# XML helpers (WinUI XAML is XML; attached properties like Grid.Row are bare attrs)
# ---------------------------------------------------------------------------

def _local(tag: str) -> str:
    """Strip the ``{namespace}`` prefix ElementTree adds, leaving the local name."""
    if isinstance(tag, str) and "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _attr(elem: ET.Element, name: str, default: str | None = None) -> str | None:
    """Read a bare (non-namespaced) attribute, e.g. Grid.Row / Width / HorizontalAlignment."""
    return elem.attrib.get(name, default)


def _int_attr(elem: ET.Element, name: str, default: int) -> int:
    raw = _attr(elem, name)
    if raw is None:
        return default
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


def _element_id(elem: ET.Element) -> str:
    """Best-effort identifier: x:Name, else Content/Text, else the local tag."""
    for key, val in elem.attrib.items():
        if _local(key) == "Name" and val:
            return str(val)
    for k in ("Content", "Text"):
        v = _attr(elem, k)
        if v:
            return f"{_local(elem.tag)}('{v}')"
    return _local(elem.tag)


def _fixed_dim(value: str | None) -> float | None:
    """Return the numeric value of a FIXED Width/Height attr, or None.

    None when the dimension is not a fixed number: absent, 'Auto', a star size ('*',
    '2*'), or a markup-extension binding ('{...}'). Only a plain number is "fixed".
    """
    if value is None:
        return None
    v = str(value).strip()
    if not v or v.lower() == "auto" or v.startswith("{") or "*" in v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _classify_definition(size: str | None) -> str:
    """Classify a Row/ColumnDefinition size as 'auto' | 'star' | 'fixed'.

    A definition with NO size attribute defaults to star ('*') in WinUI.
    """
    if size is None:
        return "star"
    s = str(size).strip().lower()
    if s == "auto":
        return "auto"
    if s == "" or "*" in s:
        return "star"
    try:
        float(s)
        return "fixed"
    except ValueError:
        return "star"


def _definitions(grid: ET.Element, kind: str) -> list[str]:
    """Return the ordered size-classes ('auto'|'star'|'fixed') of a Grid's Row or
    Column definitions. ``kind`` is 'Row' or 'Column'. Empty list when none declared.
    """
    prop_tag = f"Grid.{kind}Definitions"
    def_tag = f"{kind}Definition"
    size_attr = "Height" if kind == "Row" else "Width"
    classes: list[str] = []
    for child in list(grid):
        if _local(child.tag) == prop_tag:
            for d in list(child):
                if _local(d.tag) == def_tag:
                    classes.append(_classify_definition(_attr(d, size_attr)))
    return classes


def _layout_children(grid: ET.Element) -> list[ET.Element]:
    """Direct cell-occupying children of a Grid.

    Skips property elements (local name contains a dot, e.g. Grid.RowDefinitions,
    Grid.Resources) — those are not laid out into cells.
    """
    return [c for c in list(grid) if "." not in _local(c.tag)]


def _ranges_overlap(a_start: int, a_span: int, b_start: int, b_span: int) -> bool:
    a_end = a_start + max(1, a_span)
    b_end = b_start + max(1, b_span)
    return a_start < b_end and b_start < a_end


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

def _check_grid(grid: ET.Element, source: str) -> list[Finding]:
    findings: list[Finding] = []
    rows = _definitions(grid, "Row")
    cols = _definitions(grid, "Column")
    has_defs = bool(rows) or bool(cols)
    children = _layout_children(grid)

    # Per-child cell placement.
    placed = []
    for ch in children:
        placed.append(
            {
                "elem": ch,
                "row": _int_attr(ch, "Grid.Row", 0),
                "col": _int_attr(ch, "Grid.Column", 0),
                "rowspan": _int_attr(ch, "Grid.RowSpan", 1),
                "colspan": _int_attr(ch, "Grid.ColumnSpan", 1),
            }
        )

    # Rule: overlap — only in a Grid with declared cells (a defs-less Grid is a single
    # cell where stacking/layering is normal and intentional).
    if has_defs:
        for i in range(len(placed)):
            for j in range(i + 1, len(placed)):
                a, b = placed[i], placed[j]
                if _ranges_overlap(a["row"], a["rowspan"], b["row"], b["rowspan"]) and \
                   _ranges_overlap(a["col"], a["colspan"], b["col"], b["colspan"]):
                    findings.append(
                        Finding(
                            rule="overlap",
                            severity=SEVERITY_HIGH,
                            message=(
                                f"'{_element_id(a['elem'])}' and '{_element_id(b['elem'])}' "
                                f"occupy the same Grid cell (row {a['row']}, col {a['col']}) — they "
                                f"render stacked on top of each other. Give each its own "
                                f"Grid.Row/Grid.Column (or an explicit RowSpan/ColumnSpan)."
                            ),
                            element=_element_id(a["elem"]),
                            file=source,
                        )
                    )

    # Rule: grid-children-without-defs.
    if not rows and any(p["row"] >= 1 for p in placed):
        findings.append(
            Finding(
                rule="grid-children-without-defs",
                severity=SEVERITY_HIGH,
                message=(
                    "Children set Grid.Row >= 1 but the Grid declares no "
                    "<Grid.RowDefinitions>, so every child collapses into row 0 and stacks. "
                    "Add the RowDefinitions the layout needs."
                ),
                element=_local(grid.tag),
                file=source,
            )
        )
    if not cols and any(p["col"] >= 1 for p in placed):
        findings.append(
            Finding(
                rule="grid-children-without-defs",
                severity=SEVERITY_HIGH,
                message=(
                    "Children set Grid.Column >= 1 but the Grid declares no "
                    "<Grid.ColumnDefinitions>, so every child collapses into column 0 and stacks. "
                    "Add the ColumnDefinitions the layout needs."
                ),
                element=_local(grid.tag),
                file=source,
            )
        )

    # Per-child rules: index-out-of-range and fixed-dim-in-flexible-cell.
    for p in placed:
        ch = p["elem"]
        eid = _element_id(ch)

        if rows and p["row"] >= len(rows):
            findings.append(
                Finding(
                    rule="grid-index-out-of-range",
                    severity=SEVERITY_HIGH,
                    message=(
                        f"'{eid}' sets Grid.Row={p['row']} but only {len(rows)} row(s) are "
                        f"defined (valid 0..{len(rows) - 1}); WinUI clamps it into the last "
                        f"row, causing overlap. Fix the row index or add rows."
                    ),
                    element=eid,
                    file=source,
                )
            )
        if cols and p["col"] >= len(cols):
            findings.append(
                Finding(
                    rule="grid-index-out-of-range",
                    severity=SEVERITY_HIGH,
                    message=(
                        f"'{eid}' sets Grid.Column={p['col']} but only {len(cols)} column(s) are "
                        f"defined (valid 0..{len(cols) - 1}); WinUI clamps it into the last "
                        f"column, causing overlap. Fix the column index or add columns."
                    ),
                    element=eid,
                    file=source,
                )
            )

        # fixed-dim-in-flexible-cell: a fixed Width in a '*'/'Auto' column (or Height in a
        # '*'/'Auto' row) that is NOT deliberately aligned. A child that explicitly aligns
        # (HorizontalAlignment != Stretch) is intentionally placed -> exempt (precision).
        w = _fixed_dim(_attr(ch, "Width"))
        if w is not None and p["col"] < len(cols) and cols[p["col"]] in ("star", "auto"):
            halign = (_attr(ch, "HorizontalAlignment") or "Stretch")
            if halign == "Stretch":
                findings.append(
                    Finding(
                        rule="fixed-dim-in-flexible-cell",
                        severity=SEVERITY_HIGH,
                        message=(
                            f"'{eid}' has a fixed Width={w:g} inside a "
                            f"'{cols[p['col']]}'-sized column. It cannot fill the cell, so the "
                            f"column mis-sizes and the grid misaligns. Use "
                            f"HorizontalAlignment=\"Stretch\" (drop the fixed Width), or align it "
                            f"deliberately."
                        ),
                        element=eid,
                        file=source,
                    )
                )
        h = _fixed_dim(_attr(ch, "Height"))
        if h is not None and p["row"] < len(rows) and rows[p["row"]] in ("star", "auto"):
            valign = (_attr(ch, "VerticalAlignment") or "Stretch")
            if valign == "Stretch":
                findings.append(
                    Finding(
                        rule="fixed-dim-in-flexible-cell",
                        severity=SEVERITY_HIGH,
                        message=(
                            f"'{eid}' has a fixed Height={h:g} inside a "
                            f"'{rows[p['row']]}'-sized row. It cannot fill the cell, so the row "
                            f"mis-sizes and the grid misaligns. Use VerticalAlignment=\"Stretch\" "
                            f"(drop the fixed Height), or align it deliberately."
                        ),
                        element=eid,
                        file=source,
                    )
                )

    return findings


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def lint_xaml(xaml_text: str, source: str = "") -> list[Finding]:
    """Lint one XAML document's geometry. Pure — no I/O, no model.

    Returns a (possibly empty) list of :class:`Finding`. On a parse error returns a
    single low-severity 'unparseable' finding (never raises).
    """
    try:
        root = ET.fromstring(xaml_text)
    except ET.ParseError as exc:
        return [
            Finding(
                rule="unparseable",
                severity=SEVERITY_LOW,
                message=f"Could not parse XAML for layout analysis: {exc}",
                element="",
                file=source,
            )
        ]

    findings: list[Finding] = []
    for elem in root.iter():
        if _local(elem.tag) == "Grid":
            findings.extend(_check_grid(elem, source))
    return findings


def has_hard_findings(findings: Iterable[Finding]) -> bool:
    """True iff any finding is HIGH severity (a real geometry defect -> force a FIX)."""
    return any(f.severity in _HARD_SEVERITIES for f in findings)


def _iter_xaml_files(app_dir: Path) -> list[Path]:
    skip = ("bin", "obj", ".git", ".worktrees", ".vs")
    out: list[Path] = []
    for p in app_dir.rglob("*.xaml"):
        parts = {part.lower() for part in p.parts}
        if parts & set(skip):
            continue
        out.append(p)
    return sorted(out)


def lint_app_dir(app_dir) -> dict:
    """Lint every .xaml file under ``app_dir`` (excluding bin/obj/.git). Fail-soft.

    Returns a JSON-serializable dict:
        {"findings": [<finding dict>...], "hard": bool, "files_scanned": int}
    ``hard`` is True iff any finding is HIGH severity. Always returns (never raises);
    an unreadable file contributes a low-severity finding, not an exception.
    """
    base = Path(app_dir)
    findings: list[Finding] = []
    files = _iter_xaml_files(base) if base.exists() else []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            findings.append(
                Finding(
                    rule="unreadable",
                    severity=SEVERITY_LOW,
                    message=f"Could not read {f.name}: {exc}",
                    element="",
                    file=str(f),
                )
            )
            continue
        findings.extend(lint_xaml(text, source=str(f.relative_to(base)) if f.is_relative_to(base) else f.name))

    return {
        "findings": [asdict(x) for x in findings],
        "hard": has_hard_findings(findings),
        "files_scanned": len(files),
    }


def format_findings(findings: Iterable[dict | Finding]) -> str:
    """Render findings as a compact, coder-facing bullet list (for FIX feedback)."""
    lines: list[str] = []
    for f in findings:
        d = asdict(f) if isinstance(f, Finding) else f
        loc = f" [{d['file']}]" if d.get("file") else ""
        lines.append(f"- ({d['severity']}/{d['rule']}){loc} {d['message']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# __main__ CLI — the fleet PowerShell bridge
# ---------------------------------------------------------------------------
#
# Usage:
#   python -m shared.fleet.layout_lint --app-dir <dir>
#   python -m shared.fleet.layout_lint --xaml-file <file.xaml>
#
# Stdout: a single JSON object on one line:
#   {"findings": [...], "hard": bool, "files_scanned": int}
#
# Exit codes:
#   0 — always (even with findings; the JSON carries the state — this is a SIGNAL, not a
#       gate that blocks; the loop decides what to do with `hard`).
#   2 — only for a usage error (no input given / unreadable single file).

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m shared.fleet.layout_lint",
        description="Deterministic XAML layout linter — prints JSON findings to stdout.",
    )
    parser.add_argument("--app-dir", help="Worktree/app directory to scan for .xaml files.")
    parser.add_argument("--xaml-file", help="A single .xaml file to lint (alternative to --app-dir).")
    args = parser.parse_args()

    if args.app_dir:
        result = lint_app_dir(args.app_dir)
    elif args.xaml_file:
        p = Path(args.xaml_file)
        if not p.is_file():
            print(f"ERROR: --xaml-file not found: {args.xaml_file}", file=sys.stderr)
            sys.exit(2)
        fnd = lint_xaml(p.read_text(encoding="utf-8", errors="replace"), source=p.name)
        result = {"findings": [asdict(x) for x in fnd], "hard": has_hard_findings(fnd), "files_scanned": 1}
    else:
        print("ERROR: provide --app-dir or --xaml-file", file=sys.stderr)
        sys.exit(2)

    print(json.dumps(result))
    sys.exit(0)
