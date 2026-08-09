"""
The morning validation exercise: a live capability, rendered as something the operator can DO (#1327).
=====================================================================================================

The Lead Architect stopped being the gate on capability go-live on 2026-08-07. Capabilities
now ship live and the morning report hands him a runnable check instead of asking him to
approve one in advance. That trade is only honest if three things hold, and this module
exists to enforce them rather than hope for them:

1. **The exercise is DERIVED from the capability's own observable.** ``docs/design/
   CODER_DEFINITION_OF_DONE.md`` already states one per capability. An exercise that invents
   its own success criterion can drift from what the capability claims, which is exactly how
   capability 2 read ``LIVE`` for a week while its observable had never once been executed.
   :attr:`Exercise.observable` is required and must quote it.

2. **Every step says what he should SEE.** "Click X, type Y" is not a check. A non-technical
   reader cannot tell pass from fail without the expected result stated in plain language, so
   :attr:`Step.expect` is required on every step that can be observed.

3. **Every exercise carries a ONE-ACTION ROLLBACK.** A pre-commit gate buys certainty before;
   post-hoc validation buys it after — and that is only the better trade when reversal is
   cheap. An exercise without a rollback is a capability nobody can switch off, so
   :func:`load_exercise` refuses it. This is the reciprocal obligation of taking the go-live
   decision: if the session decides, the session owes him a way to undo it.

DENY-BY-DEFAULT: a capability whose flag is live and which has NO exercise is not silently
uncovered — :func:`unvalidated_live_capabilities` finds it and the report says so loudly.
Unvalidatable-and-live is the precise state this whole design exists to prevent.

This module renders; it never decides. It has no opinion about whether a capability should be
live, and it cannot flip a flag.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

#: Where exercise definitions live. One file per capability, named for the flag it validates.
EXERCISE_DIR: Path = _REPO_ROOT / "docs" / "validation" / "exercises"

#: The actions a step may ask the operator to take. Deliberately tiny: anything not expressible
#: as one of these is a step a non-technical reader cannot follow, and the answer is to rewrite
#: the step rather than widen the vocabulary.
ACTIONS: frozenset[str] = frozenset({"click", "type", "paste", "look", "wait", "open"})

#: Steps that produce no observable result and so are exempt from requiring ``expect``.
_NO_OBSERVATION: frozenset[str] = frozenset({"wait"})


class ExerciseError(ValueError):
    """A malformed exercise. Raised at LOAD time, never at render time.

    A broken exercise must fail where a developer sees it, not by rendering a subtly wrong
    instruction into the one document the operator trusts and acts on.
    """


@dataclass(frozen=True)
class Step:
    """One thing the operator does, and what he should see when he does it."""

    action: str
    target: str
    expect: str = ""
    #: Verbatim text to type or paste. Stored as DATA, never interpolated into prose, so it
    #: can be copied exactly and cannot drift from what the exercise claims to test.
    text: str = ""
    note: str = ""

    def render(self, index: int) -> list[str]:
        lines: list[str] = []
        # Read aloud before changing these. "Type the box" is not English; a non-technical
        # reader parses the instruction literally and the preposition is load-bearing.
        verb = {
            "click": "Click", "type": "Type into", "paste": "Paste into",
            "look": "Look at", "wait": "Wait", "open": "Open",
        }[self.action]
        lines.append(f"**{index}. {verb} {self.target}**")
        if self.text:
            lines.append("")
            lines.append("   Use exactly this text:")
            lines.append("")
            for line in self.text.splitlines() or [""]:
                lines.append(f"   > {line}")
        if self.expect:
            lines.append("")
            lines.append(f"   *You should see:* {self.expect}")
        if self.note:
            lines.append("")
            lines.append(f"   *Note:* {self.note}")
        lines.append("")
        return lines


@dataclass(frozen=True)
class Exercise:
    """One capability's validation exercise."""

    capability: str
    flag: str
    title: str
    #: Quoted from CODER_DEFINITION_OF_DONE.md. The exercise renders THIS, nothing else.
    observable: str
    why: str
    minutes: int
    steps: tuple[Step, ...]
    #: The single action that switches the capability off. Required, always printed.
    rollback: str
    #: What this exercise honestly cannot check. Printed, never omitted.
    cannot_check: tuple[str, ...] = field(default_factory=tuple)

    def render(self) -> list[str]:
        out: list[str] = [
            f"### {self.title}",
            "",
            f"*About {self.minutes} minute{'s' if self.minutes != 1 else ''}.*",
            "",
            f"**Why this matters:** {self.why}",
            "",
            f"**What it proves:** {self.observable}",
            "",
        ]
        for i, step in enumerate(self.steps, start=1):
            out.extend(step.render(i))

        out.append("**Did it work?** Reply with `worked`, `did not work`, or just say what was")
        out.append("wrong in your own words — whatever you write is kept and acted on.")
        out.append("")
        if self.cannot_check:
            out.append("**What this check does NOT cover** — so nobody reads a pass as more than it is:")
            out.append("")
            for item in self.cannot_check:
                out.append(f"- {item}")
            out.append("")
        out.append(f"**If it is wrong, this switches it off:** {self.rollback}")
        out.append("")
        return out


def _require(data: dict, key: str, source: Path) -> Any:
    if key not in data or data[key] in (None, "", [], ()):
        raise ExerciseError(f"{source.name}: missing required field '{key}'")
    return data[key]


def parse_exercise(data: dict, source: Path) -> Exercise:
    """Build an Exercise, refusing anything that would render a misleading instruction."""
    steps_raw = _require(data, "steps", source)
    if not isinstance(steps_raw, list):
        raise ExerciseError(f"{source.name}: 'steps' must be a list")

    steps: list[Step] = []
    for i, raw in enumerate(steps_raw, start=1):
        action = raw.get("action", "")
        if action not in ACTIONS:
            raise ExerciseError(
                f"{source.name}: step {i} has action '{action}'; allowed: {sorted(ACTIONS)}. "
                "A step a non-technical reader cannot follow should be rewritten, not admitted."
            )
        if not raw.get("target"):
            raise ExerciseError(f"{source.name}: step {i} has no 'target' (what to click/type into)")
        if action not in _NO_OBSERVATION and not raw.get("expect"):
            raise ExerciseError(
                f"{source.name}: step {i} ('{action} {raw.get('target')}') has no 'expect'. "
                "Every observable step must say what he should SEE -- without it he cannot "
                "tell pass from fail, and the exercise is decoration."
            )
        if action in {"type", "paste"} and not raw.get("text"):
            raise ExerciseError(
                f"{source.name}: step {i} is '{action}' but carries no verbatim 'text'. "
                "The exact words are the point; a paraphrase is a different test."
            )
        steps.append(Step(
            action=action, target=raw["target"], expect=raw.get("expect", ""),
            text=raw.get("text", ""), note=raw.get("note", ""),
        ))

    minutes = _require(data, "minutes", source)
    if not isinstance(minutes, int) or minutes <= 0:
        raise ExerciseError(f"{source.name}: 'minutes' must be a positive integer")

    return Exercise(
        capability=str(_require(data, "capability", source)),
        flag=str(_require(data, "flag", source)),
        title=str(_require(data, "title", source)),
        observable=str(_require(data, "observable", source)),
        why=str(_require(data, "why", source)),
        minutes=minutes,
        steps=tuple(steps),
        rollback=str(_require(data, "rollback", source)),
        cannot_check=tuple(data.get("cannot_check", ())),
    )


def load_exercises(directory: Path | None = None) -> list[Exercise]:
    """Every exercise on disk, sorted by capability. Raises on the first malformed one."""
    directory = directory or EXERCISE_DIR
    if not directory.is_dir():
        return []
    out: list[Exercise] = []
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ExerciseError(f"{path.name}: not valid JSON ({exc})") from exc
        out.append(parse_exercise(data, path))
    return out


def live_flags(config_text: str) -> set[str]:
    """Flag names assigned ``true`` in a TOML config, read as text.

    Text rather than a TOML parse on purpose: this must answer "what is live" for a config
    the caller may not be able to import, and it is used to CROSS-CHECK coverage, never to
    decide behaviour. A commented-out line is not live and must not read as live.
    """
    found: set[str] = set()
    for raw in config_text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*true\b", line)
        if m:
            found.add(m.group(1))
    return found


def unvalidated_live_capabilities(
    exercises: Iterable[Exercise], flags: Iterable[str], watched: Iterable[str]
) -> list[str]:
    """Watched flags that are LIVE but have no exercise. Deny-by-default.

    ``watched`` is the set this project has agreed to validate. A flag outside it is not
    silently excused -- it is simply not yet in scope, and adding it to ``watched`` without
    an exercise makes this function fail loudly, which is the intended pressure.
    """
    covered = {e.flag for e in exercises}
    live = set(flags)
    return sorted(f for f in watched if f in live and f not in covered)


def render_section(
    exercises: list[Exercise], unvalidated: list[str] | None = None
) -> str:
    """The morning report's validation section."""
    if not exercises and not unvalidated:
        return ""

    total = sum(e.minutes for e in exercises)
    out: list[str] = [
        "## Your validation exercise",
        "",
        "These are checks only a person can do. Nothing here needs any technical knowledge —",
        "every step says what to do and what you should see. If what you see does not match,",
        "that is a real finding and worth reporting exactly as you saw it.",
        "",
    ]
    if exercises:
        out.append(f"**Total time: about {total} minute{'s' if total != 1 else ''}.**")
        out.append("")
        for ex in exercises:
            out.extend(ex.render())

    if unvalidated:
        out.append("### !! LIVE WITH NO WAY TO CHECK IT")
        out.append("")
        out.append("These are switched on and have **no validation exercise**, so nobody can")
        out.append("confirm they work. That is a gap in the system, not something for you to do:")
        out.append("")
        for flag in unvalidated:
            out.append(f"- `{flag}`")
        out.append("")
    return "\n".join(out)
