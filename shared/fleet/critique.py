"""VLM-based visual design critique for the headless-coding dispatch loop (Phase 3).

**Dormancy:** This module is DORMANT — it is not wired into any live caller. It
exists to be imported by the future fleet PowerShell loop once the VLM design
loop is activated. No behavior change to any existing live code path.

**Loop-signal rule (NON-NEGOTIABLE):** The VLM critique is a LOOP SIGNAL only —
it drives whether the coder does another FIX iteration. It is NEVER the verdict.
The visual acceptance tier remains ``STATUS_EYEBALL``; a ``VlmCritique`` must
never be used to mark a criterion ``verified`` or ``done``. See
``shared/fleet/acceptance.py :: criterion_status`` — visual criteria always return
``STATUS_EYEBALL`` regardless of any critique result.

**Fail-soft contract:** Any failure (VLM unavailable, model missing, screenshot
missing, ``describe`` returns None, ``describe`` raises, parse failure) produces
a ``VlmCritique(ok=False, needs_work=False, ...)`` so the loop simply stops
iterating rather than hanging, crashing, or looping forever on an unparseable
response. No failure ever propagates as an exception out of
``critique_screenshot``.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

_THINK_TAG_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


@dataclass(frozen=True)
class VlmCritique:
    """Structured result of one VLM critique pass.

    Attributes:
        ok: False when the critique itself is unavailable or failed (fail-soft
            sentinel). When ``ok`` is False, ``needs_work`` is always False so
            the loop stops without looping forever.
        needs_work: True when the VLM determined the screenshot needs another
            FIX iteration. Only meaningful when ``ok`` is True.
        feedback: Actionable design feedback to feed the coder on the next
            iteration. Empty string when ``ok`` is False or the VLM found no
            issues.
        raw: The unmodified VLM text response (think-tags stripped), for
            logging / debugging. Empty string when the VLM was unavailable.
    """

    ok: bool
    needs_work: bool
    feedback: str
    raw: str


# ---------------------------------------------------------------------------
# Perspective-diverse lenses (Lever C)
# ---------------------------------------------------------------------------
#
# A small VLM is LENIENT — a single blanket "does it look ok?" pass false-passed a
# visibly broken grid. Instead we run several FOCUSED critiques and take the SKEPTICAL
# union: if ANY lens flags a problem the loop iterates. Diverse lenses catch failure
# modes a single redundant pass misses (the project's "multi-lens review > single pass"
# lesson). This stays a LOOP SIGNAL only — it never marks the visual acceptance tier done.
LENSES: dict[str, str] = {
    "layout": (
        "Judge ONLY geometric layout: are controls aligned in a clean grid, evenly "
        "spaced, and consistently sized? Do ANY controls overlap, get cut off, or leave "
        "awkward gaps or uneven margins? Be strict — a single misaligned, overlapping, or "
        "unevenly-spaced control is NEEDS_WORK."
    ),
    "hierarchy": (
        "Judge ONLY visual hierarchy and readability: is the most important element (e.g. "
        "the result/display) prominent and clearly legible, is text readable against its "
        "background, and is the order to read and use the controls obvious?"
    ),
    "theme": (
        "Judge ONLY whether the look matches the requested style and appears intentional "
        "and finished — not an unstyled default, an obvious placeholder, or a garish, "
        "clashing mess."
    ),
}
DEFAULT_LENSES: tuple[str, ...] = ("layout", "hierarchy", "theme")


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

_PROMPT_TEMPLATE = """\
You are a STRICT visual design reviewer for a desktop application screenshot. Your job is
to CATCH design problems the developer missed, not to reassure them. When in doubt, prefer
NEEDS_WORK.

Goal: {goal}
{lens_block}
Visual criteria to judge against — assess EACH one specifically against the image:
{criteria_block}
{layout_block}
For EACH criterion, decide whether it is CLEARLY met, citing a specific observation from
the screenshot (not a generic restatement of the criterion).

Respond in EXACTLY this format (the VERDICT line first, nothing before it):
VERDICT: PASS
FEEDBACK: <one short note, or "All criteria met." if nothing needs fixing>

OR:

VERDICT: NEEDS_WORK
FEEDBACK: <specific, actionable issues to fix, one per line — name the control and what is wrong>

Rules:
- VERDICT: PASS only when EVERY criterion is clearly and substantially met.
- VERDICT: NEEDS_WORK if ANY criterion has a clear, correctable gap — especially any
  misalignment, overlap, uneven spacing, inconsistent sizing, cut-off content, or
  unreadable text.
- FEEDBACK must be concrete (what to fix and where), not just "it looks wrong".
- Keep feedback under 300 words. Do NOT invent criteria beyond those listed.
"""


def build_critique_prompt(
    goal: str,
    visual_criteria: list[str],
    *,
    lens_focus: str | None = None,
    layout_findings: list[str] | None = None,
) -> str:
    """Build the VLM critique prompt for a screenshot review. Pure — no I/O, no model.

    Args:
        goal: The plain-English product goal for this dispatch.
        visual_criteria: The ``text`` strings of every visual-tier criterion to judge.
        lens_focus: Optional focus instruction for a perspective-diverse pass (see
            ``LENSES``). When None the prompt is a general all-round critique.
        layout_findings: Optional concrete issues a DETERMINISTIC layout check already
            found (Lever A). Injected so the VLM must confirm each is fixed — turning the
            soft critic into a checker of hard findings.

    Returns:
        A prompt string ready to pass to ``describe_image``.
    """
    if visual_criteria:
        criteria_block = "\n".join(
            f"  {i + 1}. {c}" for i, c in enumerate(visual_criteria)
        )
    else:
        criteria_block = "  (no explicit visual criteria — assess general usability and correctness)"

    lens_block = f"\nReview focus for THIS pass: {lens_focus}\n" if lens_focus else ""

    if layout_findings:
        joined = "\n".join(f"  - {m}" for m in layout_findings)
        layout_block = (
            "\nA deterministic layout check ALREADY found these concrete issues — confirm "
            "EACH is fixed in the screenshot; if any remains, respond NEEDS_WORK and include "
            f"it in your feedback:\n{joined}\n"
        )
    else:
        layout_block = ""

    return _PROMPT_TEMPLATE.format(
        goal=goal, criteria_block=criteria_block, lens_block=lens_block, layout_block=layout_block
    )


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------

_VERDICT_PASS_RE = re.compile(r"^VERDICT\s*:\s*PASS\b", re.IGNORECASE | re.MULTILINE)
_VERDICT_NEEDS_RE = re.compile(r"^VERDICT\s*:\s*NEEDS[_\s-]*WORK\b", re.IGNORECASE | re.MULTILINE)
_FEEDBACK_RE = re.compile(r"^FEEDBACK\s*:\s*(.+)", re.IGNORECASE | re.MULTILINE | re.DOTALL)


def _strip_think_tags(text: str) -> str:
    """Remove ``<think>…</think>`` blocks (Qwen3 reasoning tokens) from text."""
    return _THINK_TAG_RE.sub("", text).strip()


def parse_critique(raw: str) -> tuple[bool, str]:
    """Parse the VLM's raw response into ``(needs_work, feedback)``.

    Pure function — no I/O, no model calls. Robust to casing, whitespace, and
    missing markers. Defaults to ``needs_work=False`` when the verdict cannot
    be found (fail-soft: prevents infinite iteration on an unparseable response).

    Args:
        raw: The raw text from the VLM (think-tags already stripped by the
            caller, but this function strips them again for safety).

    Returns:
        A ``(needs_work, feedback)`` pair. ``feedback`` is the extracted
        ``FEEDBACK:`` line, or an empty string if the marker is absent.
    """
    text = _strip_think_tags(raw or "")

    # Extract feedback regardless of verdict (used for both outcomes).
    feedback_match = _FEEDBACK_RE.search(text)
    if feedback_match:
        # Take everything after "FEEDBACK:" up to the next blank line or end.
        raw_feedback = feedback_match.group(1).strip()
        # Trim to just the first paragraph (stop at a blank line separating sections).
        feedback = raw_feedback.split("\n\n")[0].strip()
    else:
        feedback = ""

    # Determine verdict. NEEDS_WORK takes precedence if both somehow appear.
    if _VERDICT_NEEDS_RE.search(text):
        return True, feedback
    if _VERDICT_PASS_RE.search(text):
        return False, feedback

    # Unparseable: fail-soft default → do NOT keep iterating.
    logger.warning(
        "VLM critique response had no parseable VERDICT — defaulting to needs_work=False "
        "(fail-soft; raw length=%d)", len(text)
    )
    return False, feedback


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

def critique_screenshot(
    screenshot_path,
    goal: str,
    visual_criteria: list[str],
    *,
    lens_focus: str | None = None,
    layout_findings: list[str] | None = None,
    describe: Callable | None = None,
    max_new_tokens: int = 512,
) -> VlmCritique:
    """Run one VLM critique pass on a screenshot and return a structured result.

    This is the adapter between the loop and the VLM inference layer. The
    ``describe`` callable defaults to ``shared.inference.vlm.describe_image``
    and is INJECTABLE for tests (no real model load required).

    Fail-soft: any failure (missing file, ``describe`` returns None, ``describe``
    raises) returns ``VlmCritique(ok=False, needs_work=False, feedback="", raw="")``
    so the caller's loop stops gracefully. No exception ever propagates out.

    Args:
        screenshot_path: Path to the PNG/screenshot file.
        goal: The plain-English product goal.
        visual_criteria: Text of each visual-tier criterion to judge.
        describe: Override for ``shared.inference.vlm.describe_image``. When
            None, the real VLM adapter is imported lazily (fail-soft if
            unavailable).
        max_new_tokens: Generation cap passed to the VLM.

    Returns:
        A ``VlmCritique`` — always, even on error (fail-soft contract).
    """
    _FAIL = VlmCritique(ok=False, needs_work=False, feedback="", raw="")

    # Resolve the describe callable.
    if describe is None:
        try:
            from shared.inference.vlm import describe_image  # type: ignore[import]
            describe = describe_image
        except Exception as exc:  # noqa: BLE001 — fail-soft if vlm not importable
            logger.error("critique_screenshot: could not import vlm.describe_image: %s", exc)
            return _FAIL

    # Validate the screenshot file exists before calling the VLM.
    try:
        path = Path(screenshot_path)
        if not path.is_file():
            logger.warning("critique_screenshot: screenshot not found: %s", screenshot_path)
            return _FAIL
    except Exception as exc:  # noqa: BLE001 — e.g. invalid path type
        logger.error("critique_screenshot: path validation error: %s", exc)
        return _FAIL

    # Build the prompt.
    prompt = build_critique_prompt(
        goal, visual_criteria, lens_focus=lens_focus, layout_findings=layout_findings
    )

    # Call the VLM — fail-soft on None return or any exception.
    try:
        raw = describe(path, prompt=prompt, max_new_tokens=max_new_tokens)
    except Exception as exc:  # noqa: BLE001 — fail-soft on any describe error
        logger.error("critique_screenshot: describe_image raised: %s", exc)
        return _FAIL

    if raw is None:
        logger.warning("critique_screenshot: describe_image returned None (VLM unavailable)")
        return _FAIL

    # Strip think-tags before storing / parsing (Qwen3 reasoning tokens).
    cleaned = _strip_think_tags(raw)

    # Parse the verdict.
    try:
        needs_work, feedback = parse_critique(cleaned)
    except Exception as exc:  # noqa: BLE001 — paranoid fail-soft; parse_critique never raises
        logger.error("critique_screenshot: parse_critique raised unexpectedly: %s", exc)
        return _FAIL

    return VlmCritique(ok=True, needs_work=needs_work, feedback=feedback, raw=cleaned)


def critique_screenshot_multivote(
    screenshot_path,
    goal: str,
    visual_criteria: list[str],
    *,
    lenses: tuple[str, ...] = DEFAULT_LENSES,
    layout_findings: list[str] | None = None,
    describe: Callable | None = None,
    max_new_tokens: int = 512,
) -> VlmCritique:
    """Run several perspective-diverse critique passes and take the SKEPTICAL union.

    For each lens in ``lenses`` (keys of ``LENSES``) runs one ``critique_screenshot`` with
    that focus, then aggregates: ``needs_work`` is True if ANY usable lens flagged work — a
    single lens catching a real problem is enough (the demanding-critic posture that fixes
    the false-pass). The VLM loads once and is reused across the lens calls (same process).

    Fail-soft: if EVERY lens is unavailable (ok=False) the result is the fail sentinel
    (ok=False, needs_work=False) so the loop stops on the VLM dimension. The deterministic
    layout gate (combined by the caller) still drives a FIX on a hard finding.
    """
    lens_names: list[str | None] = [ln for ln in lenses if ln in LENSES] or [None]
    results: list[tuple[str | None, VlmCritique]] = []
    for ln in lens_names:
        focus = LENSES[ln] if ln in LENSES else None
        c = critique_screenshot(
            screenshot_path,
            goal,
            visual_criteria,
            lens_focus=focus,
            layout_findings=layout_findings,
            describe=describe,
            max_new_tokens=max_new_tokens,
        )
        results.append((ln, c))

    usable = [(ln, c) for ln, c in results if c.ok]
    if not usable:
        return VlmCritique(ok=False, needs_work=False, feedback="", raw="")

    needs_work = any(c.needs_work for _, c in usable)
    if needs_work:
        parts = [
            f"[{ln or 'general'}] {c.feedback}".strip()
            for ln, c in usable
            if c.needs_work and c.feedback
        ]
        feedback = "\n".join(parts) if parts else "One or more design lenses flagged issues."
    else:
        feedback = "All criteria met."
    raw = "\n\n".join(f"=== lens: {ln or 'general'} ===\n{c.raw}" for ln, c in usable)
    return VlmCritique(ok=True, needs_work=needs_work, feedback=feedback, raw=raw)


# ---------------------------------------------------------------------------
# Loop-signal decision
# ---------------------------------------------------------------------------

def should_iterate(
    critique: VlmCritique,
    *,
    iteration: int,
    max_iterations: int,
) -> bool:
    """Decide whether the coder loop should do another FIX iteration.

    This is the ONLY place the loop-continue decision lives. Pure function —
    no I/O, no side effects.

    Returns True iff ALL three hold:
      1. ``critique.ok`` is True (the VLM produced a usable result),
      2. ``critique.needs_work`` is True (the VLM found issues), AND
      3. ``iteration < max_iterations`` (the iteration budget is not exhausted).

    This is a LOOP SIGNAL, not a verdict. A True return triggers one more FIX
    pass; it never marks a visual criterion as accepted.

    Args:
        critique: The result of the most recent ``critique_screenshot`` call.
        iteration: 0-based index of the iteration just completed.
        max_iterations: Hard cap on total FIX iterations (exclusive: when
            ``iteration == max_iterations - 1`` the next would be at the cap).
    """
    return critique.ok and critique.needs_work and iteration < max_iterations


# ---------------------------------------------------------------------------
# __main__ CLI  (the fleet PowerShell bridge)
# ---------------------------------------------------------------------------
#
# Usage:
#   python -m shared.fleet.critique \
#       --screenshot <path-to-png> \
#       --goal <goal-string> \
#       --criteria-json '["criterion 1", "criterion 2"]' \
#       [--layout-findings-json '["issue 1","issue 2"]']  (deterministic findings to confirm)
#       [--lenses layout,hierarchy,theme]  (perspective-diverse multi-vote; 'single' = 1 pass)
#       [--max-iter N]       (default 3)
#       [--iteration K]      (default 0; 0-based index of iteration just done)
#       [--max-tokens M]     (default 512)
#
# Stdout: a single JSON object on one line:
#   {"ok": bool, "needs_work": bool, "feedback": str, "should_iterate": bool}
#
# Exit codes:
#   0 — always (even on fail-soft; the JSON carries the state)
#   1 — only for a usage error (bad args, unparseable JSON)
#
# The VLM verdict is a LOOP SIGNAL only. The fleet PowerShell loop reads "should_iterate"
# (and OR-combines it with the deterministic layout gate's HARD signal) to decide whether
# to run another FIX pass. After the critique the VLM is unloaded to free its ~5 GB.

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m shared.fleet.critique",
        description="Run a perspective-diverse VLM design critique and print JSON to stdout.",
    )
    parser.add_argument("--screenshot", required=True, help="Path to the screenshot PNG.")
    parser.add_argument("--goal", required=True, help="The plain-English product goal.")
    parser.add_argument(
        "--criteria-json",
        required=True,
        help='JSON array of visual criterion text strings, e.g. \'["A sidebar is visible"]\'. '
             "Use [] for no explicit criteria.",
    )
    parser.add_argument(
        "--layout-findings-json",
        default="[]",
        help='JSON array of deterministic layout-issue messages (Lever A) the VLM must '
             'confirm are fixed. Default "[]".',
    )
    parser.add_argument(
        "--lenses",
        default=",".join(DEFAULT_LENSES),
        help="Comma-separated perspective lenses for the multi-vote (default "
             f"'{','.join(DEFAULT_LENSES)}'). Use 'single' or 'none' for one general pass.",
    )
    parser.add_argument("--max-iter", type=int, default=3, help="Hard cap on total FIX iterations (default 3).")
    parser.add_argument("--iteration", type=int, default=0, help="0-based index of the iteration just completed (default 0).")
    parser.add_argument("--max-tokens", type=int, default=512, help="VLM max_new_tokens (default 512).")
    args = parser.parse_args()

    def _parse_json_list(raw: str, label: str) -> list[str]:
        try:
            val = json.loads(raw)
            if not isinstance(val, list):
                raise ValueError(f"{label} must be a JSON array")
            return [str(c) for c in val]
        except (json.JSONDecodeError, ValueError) as exc:
            print(f"ERROR: --{label} is not a valid JSON array: {exc}", file=sys.stderr)
            sys.exit(1)

    criteria = _parse_json_list(args.criteria_json, "criteria-json")
    layout_findings = _parse_json_list(args.layout_findings_json, "layout-findings-json")

    lenses_arg = (args.lenses or "").strip().lower()
    if lenses_arg in ("", "single", "none"):
        result = critique_screenshot(
            args.screenshot, args.goal, criteria,
            layout_findings=layout_findings, max_new_tokens=args.max_tokens,
        )
    else:
        lenses = tuple(x.strip() for x in lenses_arg.split(",") if x.strip())
        result = critique_screenshot_multivote(
            args.screenshot, args.goal, criteria,
            lenses=lenses, layout_findings=layout_findings, max_new_tokens=args.max_tokens,
        )

    # Free the VLM weights now (~5 GB) rather than only at process exit (fail-soft).
    try:
        from shared.inference.vlm import unload as _vlm_unload
        _vlm_unload()
    except Exception:  # noqa: BLE001 — never let cleanup affect the result
        pass

    iterate = should_iterate(result, iteration=args.iteration, max_iterations=args.max_iter)

    output = {
        "ok": result.ok,
        "needs_work": result.needs_work,
        "feedback": result.feedback,
        "should_iterate": iterate,
    }
    print(json.dumps(output))
    sys.exit(0)
