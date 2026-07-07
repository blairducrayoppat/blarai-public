"""Tests for ``shared.fleet.critique`` and the regression lock on the visual tier
in ``shared.fleet.acceptance``.

All tests use a FAKE ``describe`` callable — the real Qwen3-VL model is never
loaded. This mirrors the accepted pattern in the fleet tests: inject the model
call, test everything else deterministically.

Coverage:
  - ``parse_critique``: PASS verdict, NEEDS_WORK verdict, unparseable (fail-soft).
  - ``build_critique_prompt``: smoke (pure function, no model).
  - ``critique_screenshot``: fake describe returning NEEDS_WORK text (ok+needs);
    describe returns None (ok=False); describe raises (ok=False, never propagates);
    missing screenshot file (ok=False).
  - ``should_iterate``: True only when ok+needs_work+under-budget; False at cap;
    False when ok=False; False when needs_work=False.
  - CLI ``__main__``: JSON output shape + ``should_iterate`` field, via subprocess.
  - Acceptance regression lock: ``criterion_status`` for a visual criterion is
    ALWAYS ``STATUS_EYEBALL`` — no VLM result changes that.
  - ``visual_criteria_texts``: returns text of visual criteria only.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from shared.fleet.critique import (
    DEFAULT_LENSES,
    LENSES,
    VlmCritique,
    build_critique_prompt,
    critique_screenshot,
    critique_screenshot_multivote,
    parse_critique,
    should_iterate,
)
from shared.fleet.acceptance import (
    AcceptanceCriterion,
    AcceptanceSpec,
    TaskReport,
    STATUS_EYEBALL,
    STATUS_VERIFIED,
    TIER_VISUAL,
    criterion_status,
    visual_criteria_texts,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_describe_returning(text: str):
    """Return a ``describe_image``-compatible callable that returns ``text``."""
    def describe(path, *, prompt=None, max_new_tokens=512):
        return text
    return describe


def _fake_describe_returning_none():
    def describe(path, *, prompt=None, max_new_tokens=512):
        return None
    return describe


def _fake_describe_raising(exc_type=RuntimeError, msg="deliberate test error"):
    def describe(path, *, prompt=None, max_new_tokens=512):
        raise exc_type(msg)
    return describe


def _fake_describe_recording():
    """A describe that records every prompt it was given (for prompt-content assertions)."""
    calls = {"prompts": []}
    def describe(path, *, prompt=None, max_new_tokens=512):
        calls["prompts"].append(prompt or "")
        return "VERDICT: PASS\nFEEDBACK: All criteria met."
    describe.calls = calls
    return describe


def _fake_describe_lens_aware():
    """A describe that flags NEEDS_WORK only for the 'layout' lens (its prompt contains the
    layout-lens focus text), PASS otherwise — exercises the skeptical multi-vote union."""
    def describe(path, *, prompt=None, max_new_tokens=512):
        if "geometric layout" in (prompt or ""):
            return "VERDICT: NEEDS_WORK\nFEEDBACK: Buttons overlap in the top row."
        return "VERDICT: PASS\nFEEDBACK: All criteria met."
    return describe


# ---------------------------------------------------------------------------
# parse_critique
# ---------------------------------------------------------------------------


class TestParseCritique:
    def test_pass_verdict_no_feedback(self):
        raw = "VERDICT: PASS\nFEEDBACK: All criteria met."
        needs_work, feedback = parse_critique(raw)
        assert needs_work is False
        assert "All criteria met" in feedback

    def test_pass_verdict_case_insensitive(self):
        raw = "verdict: pass\nfeedback: looks good"
        needs_work, _ = parse_critique(raw)
        assert needs_work is False

    def test_needs_work_verdict(self):
        raw = "VERDICT: NEEDS_WORK\nFEEDBACK: The sidebar is missing a title."
        needs_work, feedback = parse_critique(raw)
        assert needs_work is True
        assert "sidebar" in feedback

    def test_needs_work_with_space_variant(self):
        raw = "VERDICT: NEEDS WORK\nFEEDBACK: Button labels are too small."
        needs_work, feedback = parse_critique(raw)
        assert needs_work is True
        assert "Button" in feedback

    def test_unparseable_defaults_to_no_iterate(self):
        """Fail-soft: unrecognised text → needs_work=False, no exception."""
        raw = "I have no opinion on this screenshot."
        needs_work, feedback = parse_critique(raw)
        assert needs_work is False

    def test_empty_string_defaults_to_no_iterate(self):
        needs_work, feedback = parse_critique("")
        assert needs_work is False
        assert feedback == ""

    def test_think_tags_stripped_before_parse(self):
        raw = "<think>some hidden reasoning</think>\nVERDICT: NEEDS_WORK\nFEEDBACK: Fix the layout."
        needs_work, feedback = parse_critique(raw)
        assert needs_work is True
        assert "Fix the layout" in feedback

    def test_needs_work_takes_precedence_if_both_present(self):
        """If somehow both PASS and NEEDS_WORK appear, NEEDS_WORK wins (conservative)."""
        raw = "VERDICT: PASS\nVERDICT: NEEDS_WORK\nFEEDBACK: There is an issue."
        needs_work, _ = parse_critique(raw)
        assert needs_work is True

    def test_feedback_multiline_trimmed_at_blank_line(self):
        raw = textwrap.dedent("""\
            VERDICT: NEEDS_WORK
            FEEDBACK: Line one of feedback.
            Line two of feedback.

            Extra section after blank line.
        """)
        needs_work, feedback = parse_critique(raw)
        assert needs_work is True
        assert "Line one" in feedback
        assert "Extra section" not in feedback


# ---------------------------------------------------------------------------
# build_critique_prompt
# ---------------------------------------------------------------------------


class TestBuildCritiquePrompt:
    def test_contains_goal_and_criteria(self):
        prompt = build_critique_prompt("a calculator app", ["Big buttons", "Dark theme"])
        assert "calculator app" in prompt
        assert "Big buttons" in prompt
        assert "Dark theme" in prompt

    def test_empty_criteria_uses_fallback(self):
        prompt = build_critique_prompt("some goal", [])
        assert "no explicit visual criteria" in prompt

    def test_contains_verdict_instruction(self):
        prompt = build_critique_prompt("goal", ["criterion"])
        assert "VERDICT: PASS" in prompt
        assert "VERDICT: NEEDS_WORK" in prompt

    def test_criteria_numbered(self):
        prompt = build_critique_prompt("goal", ["First", "Second"])
        assert "1." in prompt
        assert "2." in prompt


# ---------------------------------------------------------------------------
# critique_screenshot
# ---------------------------------------------------------------------------


class TestCritiqueScreenshot:
    def test_pass_verdict_gives_ok_no_needs_work(self, tmp_path):
        png = tmp_path / "screen.png"
        png.write_bytes(b"\x89PNG")
        result = critique_screenshot(
            png,
            "a calculator",
            ["Big buttons"],
            describe=_fake_describe_returning("VERDICT: PASS\nFEEDBACK: All good."),
        )
        assert result.ok is True
        assert result.needs_work is False
        assert result.raw != ""

    def test_needs_work_gives_ok_and_needs(self, tmp_path):
        png = tmp_path / "screen.png"
        png.write_bytes(b"\x89PNG")
        text = "VERDICT: NEEDS_WORK\nFEEDBACK: The buttons are too small."
        result = critique_screenshot(
            png,
            "a calculator",
            ["Big buttons"],
            describe=_fake_describe_returning(text),
        )
        assert result.ok is True
        assert result.needs_work is True
        assert "buttons" in result.feedback

    def test_describe_returns_none_gives_fail_soft(self, tmp_path):
        png = tmp_path / "screen.png"
        png.write_bytes(b"\x89PNG")
        result = critique_screenshot(
            png,
            "a calculator",
            [],
            describe=_fake_describe_returning_none(),
        )
        assert result.ok is False
        assert result.needs_work is False
        assert result.feedback == ""
        assert result.raw == ""

    def test_describe_raises_gives_fail_soft(self, tmp_path):
        png = tmp_path / "screen.png"
        png.write_bytes(b"\x89PNG")
        # Must NOT propagate the exception.
        result = critique_screenshot(
            png,
            "a calculator",
            [],
            describe=_fake_describe_raising(),
        )
        assert result.ok is False
        assert result.needs_work is False

    def test_missing_screenshot_gives_fail_soft(self, tmp_path):
        missing = tmp_path / "does_not_exist.png"
        result = critique_screenshot(
            missing,
            "a calculator",
            [],
            describe=_fake_describe_returning("VERDICT: PASS\nFEEDBACK: Fine."),
        )
        assert result.ok is False
        assert result.needs_work is False

    def test_think_tags_stripped_from_raw(self, tmp_path):
        png = tmp_path / "screen.png"
        png.write_bytes(b"\x89PNG")
        raw_with_think = "<think>reasoning</think>\nVERDICT: PASS\nFEEDBACK: Good."
        result = critique_screenshot(
            png,
            "goal",
            [],
            describe=_fake_describe_returning(raw_with_think),
        )
        assert result.ok is True
        assert "<think>" not in result.raw


# ---------------------------------------------------------------------------
# should_iterate
# ---------------------------------------------------------------------------


class TestShouldIterate:
    def _ok_needs(self) -> VlmCritique:
        return VlmCritique(ok=True, needs_work=True, feedback="fix it", raw="raw")

    def _ok_no_needs(self) -> VlmCritique:
        return VlmCritique(ok=True, needs_work=False, feedback="", raw="raw")

    def _fail(self) -> VlmCritique:
        return VlmCritique(ok=False, needs_work=False, feedback="", raw="")

    def test_true_when_ok_and_needs_and_under_budget(self):
        assert should_iterate(self._ok_needs(), iteration=0, max_iterations=3) is True

    def test_false_at_iteration_cap(self):
        # iteration=2 with max_iterations=3 means the NEXT would be iteration 3 == cap.
        # But iteration < max_iterations: 2 < 3 is True → should still iterate.
        # At iteration=3 (== max_iterations) → False.
        assert should_iterate(self._ok_needs(), iteration=3, max_iterations=3) is False

    def test_false_when_iteration_equals_max(self):
        assert should_iterate(self._ok_needs(), iteration=5, max_iterations=5) is False

    def test_false_when_ok_false(self):
        assert should_iterate(self._fail(), iteration=0, max_iterations=3) is False

    def test_false_when_needs_work_false(self):
        assert should_iterate(self._ok_no_needs(), iteration=0, max_iterations=3) is False

    def test_false_when_max_iterations_zero(self):
        """Max iterations of 0 means the loop never runs."""
        assert should_iterate(self._ok_needs(), iteration=0, max_iterations=0) is False

    def test_last_valid_iteration(self):
        """iteration=2, max=3: 2 < 3 → True (one more iteration allowed)."""
        assert should_iterate(self._ok_needs(), iteration=2, max_iterations=3) is True


# ---------------------------------------------------------------------------
# CLI __main__
# ---------------------------------------------------------------------------


class TestCritiqueCLI:
    """Invoke the CLI as a subprocess and validate the JSON output shape."""

    def _run_cli(self, args: list[str], extra_env: dict | None = None) -> dict:
        """Run ``python -m shared.fleet.critique`` and parse stdout JSON."""
        import os
        env = os.environ.copy()
        if extra_env:
            env.update(extra_env)
        proc = subprocess.run(
            [sys.executable, "-m", "shared.fleet.critique"] + args,
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parents[2],
            env=env,
        )
        return proc

    def test_missing_screenshot_gives_ok_false_json(self, tmp_path):
        """A missing screenshot → fail-soft → ok=false, exit 0, valid JSON."""
        proc = self._run_cli([
            "--screenshot", str(tmp_path / "missing.png"),
            "--goal", "a test app",
            "--criteria-json", "[]",
        ])
        assert proc.returncode == 0, proc.stderr
        data = json.loads(proc.stdout.strip())
        assert "ok" in data
        assert "needs_work" in data
        assert "feedback" in data
        assert "should_iterate" in data
        assert data["ok"] is False
        assert data["should_iterate"] is False

    def test_json_output_shape_on_real_png(self, tmp_path, monkeypatch):
        """Create a minimal PNG and drive the CLI with a stub describe path.

        We use a real file but the VLM is unavailable in CI, so the fail-soft
        path fires (ok=False) — we test shape correctness, not VLM output.
        The important invariant: exit 0, valid JSON, all four keys present.
        """
        png = tmp_path / "screen.png"
        # Minimal 1x1 PNG bytes (valid PNG header so Path.is_file() passes)
        png.write_bytes(bytes([
            0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a,  # PNG signature
        ]))
        proc = self._run_cli([
            "--screenshot", str(png),
            "--goal", "a test app",
            "--criteria-json", '["The app has a title bar"]',
            "--max-iter", "2",
            "--iteration", "0",
        ])
        assert proc.returncode == 0, proc.stderr
        data = json.loads(proc.stdout.strip())
        for key in ("ok", "needs_work", "feedback", "should_iterate"):
            assert key in data, f"missing key: {key}"
        assert isinstance(data["ok"], bool)
        assert isinstance(data["needs_work"], bool)
        assert isinstance(data["feedback"], str)
        assert isinstance(data["should_iterate"], bool)

    def test_bad_criteria_json_exits_1(self, tmp_path):
        """Malformed --criteria-json is a usage error → exit 1."""
        proc = self._run_cli([
            "--screenshot", str(tmp_path / "s.png"),
            "--goal", "app",
            "--criteria-json", "not-json",
        ])
        assert proc.returncode == 1

    def test_criteria_json_not_array_exits_1(self, tmp_path):
        """--criteria-json must be a JSON array (not object, not string) → exit 1."""
        proc = self._run_cli([
            "--screenshot", str(tmp_path / "s.png"),
            "--goal", "app",
            "--criteria-json", '{"a": 1}',
        ])
        assert proc.returncode == 1

    def test_should_iterate_false_when_ok_false(self, tmp_path):
        """Even with max-iter > iteration, should_iterate is False when ok=False."""
        proc = self._run_cli([
            "--screenshot", str(tmp_path / "missing.png"),
            "--goal", "app",
            "--criteria-json", '["criterion"]',
            "--max-iter", "5",
            "--iteration", "0",
        ])
        data = json.loads(proc.stdout.strip())
        assert data["ok"] is False
        assert data["should_iterate"] is False


# ---------------------------------------------------------------------------
# Acceptance regression lock: visual tier is always STATUS_EYEBALL
# ---------------------------------------------------------------------------


class TestVisualTierAlwaysEyeball:
    """Structural proof that the VLM-as-signal rule is enforced:

    criterion_status for a visual criterion ALWAYS returns STATUS_EYEBALL,
    regardless of any TaskReport values. There is no code path from a VLM
    critique to STATUS_VERIFIED for a visual criterion.
    """

    _VISUAL_C = AcceptanceCriterion(
        id="c1", text="The app looks professional", tier=TIER_VISUAL, check=""
    )

    def test_visual_criterion_with_no_report_is_eyeball(self):
        assert criterion_status(self._VISUAL_C, None) == STATUS_EYEBALL

    def test_visual_criterion_with_pass_report_is_still_eyeball(self):
        report = TaskReport(tests="pass", verify="pass", review="MERGE", result="")
        assert criterion_status(self._VISUAL_C, report) == STATUS_EYEBALL

    def test_visual_criterion_with_fail_report_is_still_eyeball(self):
        report = TaskReport(tests="fail", verify="fail", review="FIX FIRST", result="")
        assert criterion_status(self._VISUAL_C, report) == STATUS_EYEBALL

    def test_visual_criterion_never_returns_verified(self):
        """No TaskReport value can cause criterion_status to return STATUS_VERIFIED
        for a visual criterion. This is the hard structural guarantee."""
        for tests in ("pass", "fail", "none"):
            for verify in ("pass", "fail", "none"):
                report = TaskReport(tests=tests, verify=verify)
                status = criterion_status(self._VISUAL_C, report)
                assert status != STATUS_VERIFIED, (
                    f"visual criterion returned STATUS_VERIFIED for tests={tests!r}, "
                    f"verify={verify!r} — this violates the VLM-as-signal rule"
                )

    def test_eyeball_does_not_equal_verified(self):
        assert STATUS_EYEBALL != STATUS_VERIFIED


# ---------------------------------------------------------------------------
# visual_criteria_texts helper
# ---------------------------------------------------------------------------


class TestVisualCriteriaTexts:
    def test_returns_text_of_visual_criteria_only(self):
        spec = AcceptanceSpec(
            goal="test",
            criteria=(
                AcceptanceCriterion("c1", "it builds", "build", ""),
                AcceptanceCriterion("c2", "it looks professional", "visual", ""),
                AcceptanceCriterion("c3", "operator signs off", "human", ""),
                AcceptanceCriterion("c4", "dark theme applied", "visual", ""),
            ),
        )
        texts = visual_criteria_texts(spec)
        assert texts == ["it looks professional", "dark theme applied"]

    def test_returns_empty_when_no_visual_criteria(self):
        spec = AcceptanceSpec(
            goal="test",
            criteria=(
                AcceptanceCriterion("c1", "it builds", "build", ""),
                AcceptanceCriterion("c2", "operator signs off", "human", ""),
            ),
        )
        assert visual_criteria_texts(spec) == []

    def test_human_tier_excluded(self):
        spec = AcceptanceSpec(
            goal="test",
            criteria=(
                AcceptanceCriterion("c1", "human judgment", "human", ""),
            ),
        )
        assert visual_criteria_texts(spec) == []

    def test_empty_spec_returns_empty(self):
        spec = AcceptanceSpec(goal="test", criteria=())
        assert visual_criteria_texts(spec) == []


# ---------------------------------------------------------------------------
# Lever C — VLM hardening: stricter prompt, lenses, layout-findings ingestion
# ---------------------------------------------------------------------------


class TestLeverCPromptHardening:
    def test_prompt_is_stricter(self):
        prompt = build_critique_prompt("goal", ["c"])
        assert "STRICT" in prompt
        assert "CATCH design problems" in prompt

    def test_backcompat_two_positional_args(self):
        # The original 2-arg call site must keep working unchanged.
        prompt = build_critique_prompt("a calc", ["Big buttons"])
        assert "a calc" in prompt and "Big buttons" in prompt
        assert "VERDICT: PASS" in prompt and "VERDICT: NEEDS_WORK" in prompt

    def test_lens_focus_injected(self):
        prompt = build_critique_prompt("goal", ["c"], lens_focus=LENSES["layout"])
        assert "Review focus for THIS pass" in prompt
        assert "geometric layout" in prompt

    def test_no_lens_focus_omits_focus_block(self):
        assert "Review focus for THIS pass" not in build_critique_prompt("goal", ["c"])

    def test_layout_findings_injected(self):
        findings = ["'Zero' has a fixed Width inside a '*' column.", "Display and Keypad overlap."]
        prompt = build_critique_prompt("goal", ["c"], layout_findings=findings)
        assert "deterministic layout check ALREADY found" in prompt
        assert "fixed Width" in prompt and "overlap" in prompt

    def test_no_layout_findings_omits_block(self):
        assert "deterministic layout check" not in build_critique_prompt("goal", ["c"])


class TestMultiVote:
    def _png(self, tmp_path):
        png = tmp_path / "s.png"
        png.write_bytes(b"\x89PNG")
        return png

    def test_skeptical_union_any_lens_flags(self, tmp_path):
        # The layout lens flags NEEDS_WORK; hierarchy/theme PASS -> aggregate needs_work True.
        result = critique_screenshot_multivote(
            self._png(tmp_path), "a calculator", ["Clean grid"],
            describe=_fake_describe_lens_aware(),
        )
        assert result.ok is True
        assert result.needs_work is True
        assert "layout" in result.feedback  # the flagging lens is labelled
        assert "overlap" in result.feedback

    def test_all_pass_gives_no_needs_work(self, tmp_path):
        result = critique_screenshot_multivote(
            self._png(tmp_path), "goal", ["c"],
            describe=_fake_describe_returning("VERDICT: PASS\nFEEDBACK: All criteria met."),
        )
        assert result.ok is True and result.needs_work is False

    def test_all_unavailable_is_fail_soft(self, tmp_path):
        result = critique_screenshot_multivote(
            self._png(tmp_path), "goal", ["c"],
            describe=_fake_describe_returning_none(),
        )
        assert result.ok is False and result.needs_work is False

    def test_runs_one_pass_per_lens(self, tmp_path):
        rec = _fake_describe_recording()
        critique_screenshot_multivote(
            self._png(tmp_path), "goal", ["c"], lenses=DEFAULT_LENSES, describe=rec,
        )
        assert len(rec.calls["prompts"]) == len(DEFAULT_LENSES) == 3

    def test_layout_findings_reach_every_lens_prompt(self, tmp_path):
        rec = _fake_describe_recording()
        critique_screenshot_multivote(
            self._png(tmp_path), "goal", ["c"],
            lenses=("layout", "theme"),
            layout_findings=["Display and Keypad overlap."],
            describe=rec,
        )
        assert len(rec.calls["prompts"]) == 2
        assert all("Display and Keypad overlap" in p for p in rec.calls["prompts"])

    def test_unknown_lenses_fall_back_to_single_general_pass(self, tmp_path):
        rec = _fake_describe_recording()
        critique_screenshot_multivote(
            self._png(tmp_path), "goal", ["c"], lenses=("bogus",), describe=rec,
        )
        # No valid lens -> exactly one general pass (lens=None, no focus block).
        assert len(rec.calls["prompts"]) == 1
        assert "Review focus for THIS pass" not in rec.calls["prompts"][0]


class TestCLILeverC:
    """The CLI accepts the new --lenses / --layout-findings-json args (subprocess)."""

    def _run_cli(self, args: list[str]):
        return subprocess.run(
            [sys.executable, "-m", "shared.fleet.critique"] + args,
            capture_output=True, text=True, cwd=Path(__file__).resolve().parents[2],
        )

    def test_cli_accepts_lenses_and_layout_findings(self, tmp_path):
        proc = self._run_cli([
            "--screenshot", str(tmp_path / "missing.png"),
            "--goal", "app", "--criteria-json", "[]",
            "--layout-findings-json", '["overlap detected"]',
            "--lenses", "single",
        ])
        assert proc.returncode == 0, proc.stderr
        data = json.loads(proc.stdout.strip())
        assert data["ok"] is False  # no VLM available in CI -> fail-soft
        assert set(data) >= {"ok", "needs_work", "feedback", "should_iterate"}

    def test_cli_bad_layout_findings_json_exits_1(self, tmp_path):
        proc = self._run_cli([
            "--screenshot", str(tmp_path / "s.png"),
            "--goal", "app", "--criteria-json", "[]",
            "--layout-findings-json", "not-json",
        ])
        assert proc.returncode == 1
