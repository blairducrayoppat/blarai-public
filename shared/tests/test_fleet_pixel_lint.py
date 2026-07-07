"""Mutation-resistant tests for the deterministic pixel-level visual linter.

Each rule has a POSITIVE fixture (the defect fires) and a NEGATIVE fixture (a correct
render does NOT fire), plus the precision guards that keep HARD findings rare:
  blank-render        flat/transparent fires; a 2-colour image does NOT.
  named-colour-absent a missing named colour fires; a present one (even a PALE shade) does NOT.
  content-collapsed   a tiny cornered blob fires; a centred blob and a spread blob do NOT.
A code mutation that drops a guard, widens a band, or moves a threshold flips at least one
assertion here. The colour-space + geometry helpers are exercised directly so the maths is
pinned independently of the find/merge plumbing.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from shared.fleet.pixel_lint import (
    _CONTENT_DELTA,
    SEVERITY_HIGH,
    analyze,
    color_presence,
    compare_to_golden,
    extract_named_colors,
    lint_screenshot,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]

# Reference colours (chromatic ones sit well inside their HSV bands).
WHITE = (245, 245, 245)
BLACK = (10, 10, 10)
GRAY = (128, 128, 128)
BLUE = (40, 70, 200)
PALE_BLUE = (180, 200, 240)   # low-saturation "soft" blue — must still read as PRESENT
RED = (210, 30, 30)
GREEN = (30, 170, 60)


def _solid(rgb, h=128, w=128) -> np.ndarray:
    a = np.zeros((h, w, 3), dtype=np.uint8)
    a[:] = rgb
    return a


def _bg_with_blob(bg, blob, y0, y1, x0, x1, h=128, w=128) -> np.ndarray:
    a = _solid(bg, h, w)
    a[y0:y1, x0:x1] = blob
    return a


def _rules(findings) -> set[str]:
    return {f.rule for f in findings}


# ---------------------------------------------------------------------------
# Clean render: the negative for EVERYTHING (silence, not a PASS).
# A blue background with a large centred white card, criteria naming blue + white.
# ---------------------------------------------------------------------------
def test_clean_render_is_silent():
    arr = _bg_with_blob(BLUE, WHITE, 30, 98, 30, 98)
    findings = analyze(arr, "a blue background with a white card")
    assert findings == [], f"clean render should be silent, got {[f.rule for f in findings]}"


# ---------------------------------------------------------------------------
# blank-render
# ---------------------------------------------------------------------------
def test_blank_render_solid_colour_fires():
    findings = analyze(_solid(BLUE), "a blue background")
    assert _rules(findings) == {"blank-render"}
    assert findings[0].severity == SEVERITY_HIGH


def test_blank_render_solid_white_fires():
    assert _rules(analyze(_solid(WHITE), "")) == {"blank-render"}


def test_blank_render_transparent_fires():
    # The pixel content is irrelevant when the source alpha was fully zero.
    findings = analyze(_solid(BLUE), "a blue background", fully_transparent=True)
    assert _rules(findings) == {"blank-render"}


def test_blank_render_two_colour_does_not_fire():
    # 50/50 split -> top colour ~50% << 98.5% blank threshold -> NOT blank.
    arr = _solid(WHITE)
    arr[:, 64:] = BLUE
    assert "blank-render" not in _rules(analyze(arr, ""))


# ---------------------------------------------------------------------------
# named-colour-absent
# ---------------------------------------------------------------------------
def test_named_colour_absent_fires_when_colour_missing():
    # White canvas + a big black square (not blank); criteria call for blue -> blue absent.
    arr = _bg_with_blob(WHITE, BLACK, 20, 108, 20, 108)
    findings = analyze(arr, "a soft blue background")
    absent = [f for f in findings if f.rule == "named-colour-absent"]
    assert len(absent) == 1
    assert absent[0].element == "blue"
    assert absent[0].severity == SEVERITY_HIGH


def test_named_colour_present_does_not_fire():
    arr = _bg_with_blob(WHITE, BLUE, 20, 108, 20, 108)
    assert "named-colour-absent" not in _rules(analyze(arr, "a blue panel"))


def test_named_colour_pale_shade_counts_as_present():
    # Precision guard: a low-saturation "soft" blue must NOT be reported absent.
    arr = _bg_with_blob(WHITE, PALE_BLUE, 20, 108, 20, 108)
    assert "named-colour-absent" not in _rules(analyze(arr, "a soft blue background"))


def test_named_colour_absent_only_flags_the_missing_one():
    # Red present, green absent -> exactly one finding, for green.
    arr = _bg_with_blob(WHITE, RED, 20, 108, 20, 108)
    absent = [f for f in analyze(arr, "red and green cards") if f.rule == "named-colour-absent"]
    assert [f.element for f in absent] == ["green"]


def test_no_colour_named_means_no_colour_check():
    arr = _bg_with_blob(WHITE, BLACK, 20, 108, 20, 108)
    assert "named-colour-absent" not in _rules(analyze(arr, "a clean modern layout"))


# ---------------------------------------------------------------------------
# content-collapsed
# ---------------------------------------------------------------------------
def test_content_collapsed_tiny_corner_blob_fires():
    # ~2.4% content, jammed in the top-left quadrant, on an otherwise-white canvas.
    arr = _bg_with_blob(WHITE, BLACK, 4, 24, 4, 24)
    findings = analyze(arr, "")
    assert "content-collapsed" in _rules(findings)
    assert all(f.severity == SEVERITY_HIGH for f in findings)


def test_content_collapsed_centred_blob_does_not_fire():
    # Same tiny size, but centred (bbox crosses the middle) -> NOT cornered -> no finding.
    arr = _bg_with_blob(WHITE, BLACK, 54, 74, 54, 74)
    assert "content-collapsed" not in _rules(analyze(arr, ""))


def test_content_collapsed_spread_content_does_not_fire():
    # Cornered (bbox stays in the top-left quadrant) but LARGE (~19% content) -> the
    # tiny-content guard rejects it. Isolates the fraction guard: under a mutant that drops
    # the <4% bound this fixture would falsely collapse (a 76x76 blob would instead cross the
    # midline and be rejected by the cornered guard, masking the fraction mutant).
    arr = _bg_with_blob(WHITE, BLACK, 4, 60, 4, 60)
    assert "content-collapsed" not in _rules(analyze(arr, ""))


# ---------------------------------------------------------------------------
# Colour-space + extraction helpers (pin the maths independently)
# ---------------------------------------------------------------------------
def test_color_presence_pure_colours():
    assert color_presence(_solid(RED), "red") > 0.9
    assert color_presence(_solid(RED), "blue") < 0.01
    assert color_presence(_solid(BLUE), "blue") > 0.9
    assert color_presence(_solid(BLUE), "green") < 0.05


def test_extract_named_colors_synonyms_and_dedup():
    assert extract_named_colors("a navy blue sky") == ["blue"]
    assert extract_named_colors("crimson and teal accents") == ["red", "cyan"]
    assert extract_named_colors("RED, Green") == ["red", "green"]


def test_extract_named_colors_word_boundary():
    # 'blue' inside 'blueberry' must NOT match (a false colour claim).
    assert extract_named_colors("blueberry muffin") == []
    assert extract_named_colors("") == []


def test_content_delta_constant_is_sane():
    # A guard against an accidental 0/1 mutation that would make the geometry rule trivial.
    assert 0.0 < _CONTENT_DELTA < 1.0


# ---------------------------------------------------------------------------
# lint_screenshot — file I/O + fail-soft + the JSON contract
# ---------------------------------------------------------------------------
def _save(arr, path) -> str:
    from PIL import Image
    Image.fromarray(arr, "RGB").save(path)
    return str(path)


def test_lint_screenshot_missing_file_is_failsoft():
    res = lint_screenshot("C:/no/such/file.png", "blue")
    assert res == {"findings": [], "hard": False, "image": "file.png"}


def test_lint_screenshot_garbage_file_is_failsoft(tmp_path):
    p = tmp_path / "bad.png"
    p.write_bytes(b"this is not a png")
    res = lint_screenshot(str(p), "blue")
    assert res["findings"] == [] and res["hard"] is False


def test_lint_screenshot_blank_png(tmp_path):
    png = _save(_solid(BLUE), tmp_path / "blank.png")
    res = lint_screenshot(png, "a blue background")
    assert res["hard"] is True
    assert {f["rule"] for f in res["findings"]} == {"blank-render"}


def test_lint_screenshot_named_colour_absent_png(tmp_path):
    png = _save(_bg_with_blob(WHITE, BLACK, 20, 108, 20, 108), tmp_path / "noblue.png")
    res = lint_screenshot(png, "a soft blue background")
    assert res["hard"] is True
    assert any(f["rule"] == "named-colour-absent" and f["element"] == "blue"
               for f in res["findings"])


def test_lint_screenshot_clean_png_is_silent(tmp_path):
    png = _save(_bg_with_blob(BLUE, WHITE, 30, 98, 30, 98), tmp_path / "clean.png")
    res = lint_screenshot(png, "a blue background with a white card")
    assert res == {"findings": [], "hard": False, "image": "clean.png"}


# ---------------------------------------------------------------------------
# INERT golden seam
# ---------------------------------------------------------------------------
def test_compare_to_golden_is_inert():
    assert compare_to_golden("a.png") == []
    assert compare_to_golden("a.png", "golden.png", "blue and red") == []


# ---------------------------------------------------------------------------
# CLI bridge (subprocess — the fleet PowerShell calls it exactly this way)
# ---------------------------------------------------------------------------
def test_cli_emits_json_and_exits_zero(tmp_path):
    png = _save(_solid(BLUE), tmp_path / "cli.png")
    proc = subprocess.run(
        [sys.executable, "-m", "shared.fleet.pixel_lint",
         "--screenshot", png, "--criteria-json", '["a blue background"]'],
        capture_output=True, text=True, cwd=str(_REPO_ROOT),
    )
    assert proc.returncode == 0, proc.stderr
    obj = json.loads(proc.stdout.strip().splitlines()[-1])
    assert obj["hard"] is True
    assert {f["rule"] for f in obj["findings"]} == {"blank-render"}


def test_cli_usage_error_exits_two():
    proc = subprocess.run(
        [sys.executable, "-m", "shared.fleet.pixel_lint", "--criteria-json", "[]"],
        capture_output=True, text=True, cwd=str(_REPO_ROOT),
    )
    assert proc.returncode == 2
