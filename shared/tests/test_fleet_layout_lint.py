"""Mutation-resistant tests for the deterministic XAML layout linter (Lever A).

Each rule has a POSITIVE fixture (the defect fires) and a NEGATIVE fixture (a correct
layout does NOT fire), plus the precision guards (alignment-exempt, fixed-column-exempt,
overlap-requires-definitions, spanning-no-false-positive). A code mutation that drops a
guard or a rule flips at least one assertion here.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from shared.fleet.layout_lint import (
    Finding,
    SEVERITY_HIGH,
    SEVERITY_LOW,
    _fixed_dim,
    format_findings,
    has_hard_findings,
    lint_app_dir,
    lint_xaml,
)

NS = 'xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"'


def _rules(findings) -> set[str]:
    return {f.rule for f in findings}


# ---------------------------------------------------------------------------
# A clean, correct layout produces NO findings (the negative for everything).
# Mirrors the hand-fixed rocket calc: distinct rows, a star-column keypad whose
# buttons Stretch (no fixed dims), a row-spanning '=' that does not overlap.
# ---------------------------------------------------------------------------
CLEAN = f"""<Grid {NS}>
  <Grid.RowDefinitions>
    <RowDefinition Height="Auto"/>
    <RowDefinition Height="Auto"/>
    <RowDefinition Height="*"/>
  </Grid.RowDefinitions>
  <StackPanel Grid.Row="0"/>
  <Border x:Name="Display" Grid.Row="1"/>
  <Grid x:Name="Keypad" Grid.Row="2">
    <Grid.RowDefinitions>
      <RowDefinition Height="66"/><RowDefinition Height="66"/><RowDefinition Height="66"/>
    </Grid.RowDefinitions>
    <Grid.ColumnDefinitions>
      <ColumnDefinition Width="*"/><ColumnDefinition Width="*"/>
    </Grid.ColumnDefinitions>
    <Button x:Name="Seven" Grid.Row="0" Grid.Column="0" HorizontalAlignment="Stretch" VerticalAlignment="Stretch"/>
    <Button x:Name="Eq" Grid.Row="0" Grid.Column="1" Grid.RowSpan="3" HorizontalAlignment="Stretch" VerticalAlignment="Stretch"/>
    <Button x:Name="Zero" Grid.Row="1" Grid.Column="0" HorizontalAlignment="Stretch" VerticalAlignment="Stretch"/>
    <Button x:Name="One" Grid.Row="2" Grid.Column="0" HorizontalAlignment="Stretch" VerticalAlignment="Stretch"/>
  </Grid>
</Grid>"""


def test_clean_layout_has_no_findings():
    findings = lint_xaml(CLEAN)
    assert findings == [], f"clean layout should be silent, got: {[f.rule for f in findings]}"
    assert has_hard_findings(findings) is False


# ---------------------------------------------------------------------------
# Rule: overlap
# ---------------------------------------------------------------------------
OVERLAP = f"""<Grid {NS}>
  <Grid.RowDefinitions><RowDefinition Height="Auto"/><RowDefinition Height="*"/></Grid.RowDefinitions>
  <Border x:Name="Display" Grid.Row="1"/>
  <Grid x:Name="Keypad" Grid.Row="1"/>
</Grid>"""


def test_overlap_same_cell_flagged():
    findings = lint_xaml(OVERLAP)
    assert "overlap" in _rules(findings)
    overlap = [f for f in findings if f.rule == "overlap"][0]
    assert overlap.severity == SEVERITY_HIGH
    # The message names BOTH colliding elements (so the coder knows what to separate).
    assert "Display" in overlap.message and "Keypad" in overlap.message


def test_overlap_requires_definitions():
    # Two children both default to cell (0,0) but the Grid declares NO definitions ->
    # a single-cell Grid where layering is normal; overlap must NOT fire.
    xaml = f"""<Grid {NS}><TextBlock x:Name="A"/><TextBlock x:Name="B"/></Grid>"""
    assert "overlap" not in _rules(lint_xaml(xaml))


def test_overlap_spanning_sibling_no_false_positive():
    # '=' spans rows 0-2 in column 1; the digits sit in column 0. Different columns ->
    # NO overlap. Guards against a span/region mutation that would over-report.
    assert "overlap" not in _rules(lint_xaml(CLEAN))


def test_distinct_cells_no_overlap():
    xaml = f"""<Grid {NS}>
      <Grid.ColumnDefinitions><ColumnDefinition Width="*"/><ColumnDefinition Width="*"/></Grid.ColumnDefinitions>
      <Button Grid.Column="0"/><Button Grid.Column="1"/>
    </Grid>"""
    assert "overlap" not in _rules(lint_xaml(xaml))


# ---------------------------------------------------------------------------
# Rule: fixed-dim-in-flexible-cell
# ---------------------------------------------------------------------------
def test_fixed_width_in_star_column_flagged():
    xaml = f"""<Grid {NS}>
      <Grid.ColumnDefinitions><ColumnDefinition Width="*"/></Grid.ColumnDefinitions>
      <Button x:Name="Zero" Width="130"/>
    </Grid>"""
    findings = lint_xaml(xaml)
    assert "fixed-dim-in-flexible-cell" in _rules(findings)
    assert [f for f in findings if f.rule == "fixed-dim-in-flexible-cell"][0].severity == SEVERITY_HIGH


def test_fixed_width_in_auto_column_flagged():
    # The exact rocket-calc bug: a fixed Width in an Auto column distorts the grid.
    xaml = f"""<Grid {NS}>
      <Grid.ColumnDefinitions><ColumnDefinition Width="Auto"/></Grid.ColumnDefinitions>
      <Button x:Name="Zero" Width="130"/>
    </Grid>"""
    assert "fixed-dim-in-flexible-cell" in _rules(lint_xaml(xaml))


def test_fixed_height_in_star_row_flagged():
    xaml = f"""<Grid {NS}>
      <Grid.RowDefinitions><RowDefinition Height="*"/></Grid.RowDefinitions>
      <Button x:Name="Eq" Height="130"/>
    </Grid>"""
    assert "fixed-dim-in-flexible-cell" in _rules(lint_xaml(xaml))


def test_fixed_width_with_explicit_alignment_exempt():
    # A deliberately-centered fixed-width control is intentional placement -> NOT a defect.
    xaml = f"""<Grid {NS}>
      <Grid.ColumnDefinitions><ColumnDefinition Width="*"/></Grid.ColumnDefinitions>
      <Button x:Name="Logo" Width="130" HorizontalAlignment="Center"/>
    </Grid>"""
    assert "fixed-dim-in-flexible-cell" not in _rules(lint_xaml(xaml))


def test_fixed_width_in_fixed_column_not_flagged():
    # A fixed Width inside a fixed-width column is consistent -> no finding.
    xaml = f"""<Grid {NS}>
      <Grid.ColumnDefinitions><ColumnDefinition Width="200"/></Grid.ColumnDefinitions>
      <Button x:Name="Side" Width="130"/>
    </Grid>"""
    assert "fixed-dim-in-flexible-cell" not in _rules(lint_xaml(xaml))


def test_stretch_button_in_star_column_clean():
    xaml = f"""<Grid {NS}>
      <Grid.ColumnDefinitions><ColumnDefinition Width="*"/></Grid.ColumnDefinitions>
      <Button x:Name="B" HorizontalAlignment="Stretch"/>
    </Grid>"""
    assert lint_xaml(xaml) == []


# ---------------------------------------------------------------------------
# Rule: grid-index-out-of-range
# ---------------------------------------------------------------------------
def test_index_out_of_range_flagged():
    xaml = f"""<Grid {NS}>
      <Grid.RowDefinitions><RowDefinition/><RowDefinition/><RowDefinition/></Grid.RowDefinitions>
      <Button x:Name="Stray" Grid.Row="5"/>
    </Grid>"""
    findings = lint_xaml(xaml)
    assert "grid-index-out-of-range" in _rules(findings)
    assert [f for f in findings if f.rule == "grid-index-out-of-range"][0].severity == SEVERITY_HIGH


def test_index_in_range_not_flagged():
    xaml = f"""<Grid {NS}>
      <Grid.RowDefinitions><RowDefinition/><RowDefinition/><RowDefinition/></Grid.RowDefinitions>
      <Button Grid.Row="2"/>
    </Grid>"""
    assert "grid-index-out-of-range" not in _rules(lint_xaml(xaml))


# ---------------------------------------------------------------------------
# Rule: grid-children-without-defs
# ---------------------------------------------------------------------------
def test_grid_children_without_defs_flagged():
    xaml = f"""<Grid {NS}><Button x:Name="B" Grid.Row="2"/></Grid>"""
    findings = lint_xaml(xaml)
    assert "grid-children-without-defs" in _rules(findings)
    assert [f for f in findings if f.rule == "grid-children-without-defs"][0].severity == SEVERITY_HIGH


def test_grid_no_defs_all_default_cell_not_flagged():
    # A defs-less Grid whose children never set Grid.Row/Column is a normal single cell.
    xaml = f"""<Grid {NS}><StackPanel><Button/><Button/></StackPanel></Grid>"""
    assert lint_xaml(xaml) == []


# ---------------------------------------------------------------------------
# The real failure: the broken rocket calc trips overlap AND fixed-dim, and is HARD.
# ---------------------------------------------------------------------------
BROKEN_ROCKET = f"""<Grid {NS}>
  <Grid.RowDefinitions><RowDefinition Height="Auto"/><RowDefinition Height="*"/></Grid.RowDefinitions>
  <Border x:Name="Display" Grid.Row="1"/>
  <Grid x:Name="Keypad" Grid.Row="1">
    <Grid.ColumnDefinitions>
      <ColumnDefinition Width="Auto"/><ColumnDefinition Width="Auto"/>
    </Grid.ColumnDefinitions>
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/><RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>
    <Button x:Name="Zero" Grid.Row="0" Grid.Column="0" Width="130"/>
    <Button x:Name="Eq" Grid.Row="0" Grid.Column="1" Height="130"/>
  </Grid>
</Grid>"""


def test_broken_rocket_flags_overlap_and_fixed_dim():
    findings = lint_xaml(BROKEN_ROCKET, source="MainWindow.xaml")
    rules = _rules(findings)
    assert "overlap" in rules, "the Display/Keypad both-on-Row-1 collision must be caught"
    assert "fixed-dim-in-flexible-cell" in rules, "the oversized 0/= in Auto cells must be caught"
    assert has_hard_findings(findings) is True
    # The source file is threaded onto every finding.
    assert all(f.file == "MainWindow.xaml" for f in findings)


# ---------------------------------------------------------------------------
# Fail-soft + helpers
# ---------------------------------------------------------------------------
def test_unparseable_xaml_fail_soft():
    findings = lint_xaml("<Grid><Button></Grid>")  # malformed: unclosed Button
    assert len(findings) == 1
    assert findings[0].rule == "unparseable"
    assert findings[0].severity == SEVERITY_LOW
    assert has_hard_findings(findings) is False  # advisory only, never forces a FIX


def test_has_hard_findings_logic():
    assert has_hard_findings([Finding("r", SEVERITY_HIGH, "m", "e")]) is True
    assert has_hard_findings([Finding("r", SEVERITY_LOW, "m", "e")]) is False
    assert has_hard_findings([]) is False


@pytest.mark.parametrize(
    "value,expected",
    [
        ("130", 130.0),
        ("66.5", 66.5),
        ("Auto", None),
        ("auto", None),
        ("*", None),
        ("2*", None),
        ("{Binding W}", None),
        ("", None),
        (None, None),
        ("NaNlike", None),
    ],
)
def test_fixed_dim_helper(value, expected):
    assert _fixed_dim(value) == expected


def test_format_findings_renders_rule_and_severity():
    out = format_findings([Finding("overlap", SEVERITY_HIGH, "stacked", "Display", "MainWindow.xaml")])
    assert "overlap" in out and "high" in out and "MainWindow.xaml" in out and "stacked" in out


# ---------------------------------------------------------------------------
# lint_app_dir: aggregation, hard flag, bin/obj exclusion
# ---------------------------------------------------------------------------
def test_lint_app_dir_aggregates_and_excludes_build_output(tmp_path):
    (tmp_path / "MainWindow.xaml").write_text(BROKEN_ROCKET, encoding="utf-8")
    (tmp_path / "App.xaml").write_text(CLEAN, encoding="utf-8")
    # A broken file under bin/ MUST be ignored (build output, not source).
    bin_dir = tmp_path / "bin" / "x64"
    bin_dir.mkdir(parents=True)
    (bin_dir / "Generated.xaml").write_text(OVERLAP, encoding="utf-8")

    result = lint_app_dir(str(tmp_path))
    assert result["files_scanned"] == 2, "bin/ output must be excluded from the scan"
    assert result["hard"] is True
    found_rules = {f["rule"] for f in result["findings"]}
    assert "overlap" in found_rules and "fixed-dim-in-flexible-cell" in found_rules
    # JSON-serializable (it crosses the PowerShell bridge).
    json.dumps(result)


def test_lint_app_dir_clean_tree_is_not_hard(tmp_path):
    (tmp_path / "MainWindow.xaml").write_text(CLEAN, encoding="utf-8")
    result = lint_app_dir(str(tmp_path))
    assert result["files_scanned"] == 1
    assert result["hard"] is False
    assert result["findings"] == []


def test_lint_app_dir_missing_dir_is_safe():
    result = lint_app_dir("Z:/no/such/dir/anywhere")
    assert result == {"findings": [], "hard": False, "files_scanned": 0}


# ---------------------------------------------------------------------------
# CLI bridge (the PowerShell loop invokes this) — one JSON line, exit 0.
# ---------------------------------------------------------------------------
def test_cli_emits_one_json_line(tmp_path):
    xaml = tmp_path / "MainWindow.xaml"
    xaml.write_text(BROKEN_ROCKET, encoding="utf-8")
    repo_root = Path(__file__).resolve().parents[2]
    proc = subprocess.run(
        [sys.executable, "-m", "shared.fleet.layout_lint", "--xaml-file", str(xaml)],
        capture_output=True, text=True, cwd=str(repo_root),
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout.strip())
    assert payload["hard"] is True
    assert {f["rule"] for f in payload["findings"]} >= {"overlap", "fixed-dim-in-flexible-cell"}
