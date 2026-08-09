"""
Render the morning report's validation section (#1327) and the night's websites (#1346).

Called by the battery launcher after it writes MORNING-REPORT.md. Prints the sections to
stdout as UTF-8 and exits 0 even when there is nothing to render -- an empty section is a
normal day, and a launcher must never lose its report because this had nothing to say.

Exit codes:
  0  section printed (possibly empty)
  2  an exercise on disk is malformed -- printed to stderr, NOTHING to stdout

Exit 2 is deliberately loud. A malformed exercise must not degrade into a silently missing
section: "no validation today" and "the validation is broken" are different facts, and the
whole point of this feature is that the operator can tell them apart.

TWO CONCERNS, AND THE SECOND MUST NEVER COST THE FIRST (#1346)
==============================================================
The websites section is here because MORNING-REPORT.md is the only thing the operator
reads. #1343 landed a double-click launcher BESIDE the report, which still asks him to
notice a second file in a directory; naming it INSIDE the report is what finishes that.

It renders LAST and behind a full guard, both deliberately. The exercise section is the
older, working concern and its exit-2 contract promises NOTHING on stdout, so the websites
work happens only after that decision has been taken. And any fault in it degrades to a
loud paragraph naming the fault, never to a non-zero exit that would cost him the exercise
as well -- and never to silence, because an absent section must mean "no website card left
a record" and must never be able to mean "the look failed".

Usage:
    python scripts/render_morning_validation.py [--config PATH] [--exercises DIR]
                                                [--battery-dir DIR]
"""

from __future__ import annotations

import argparse
import os
import sys
import textwrap
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.validation.exercise import (  # noqa: E402
    EXERCISE_DIR,
    ExerciseError,
    live_flags,
    load_exercises,
    render_section,
    unvalidated_live_capabilities,
)

#: Kept in step with tests/security/test_validation_exercises.py WATCHED_FLAGS. A flag here
#: with no exercise renders the LOUD "live with no way to check it" block.
WATCHED_FLAGS = ("advanced_intake_interview",)

#: How the battery names the agentic-setup checkout whose ``state\battery`` holds the night
#: directories and MORNING-REPORT.md. Set by ``battery-bootstrap.ps1``, read back by
#: ``run-battery-night.ps1`` and joined with ``state\battery`` by
#: ``verify-battery-driver-pinning.ps1`` -- so it is an established convention, not a new
#: one, and it is exported into the process environment the night's postlude runs this
#: script in. The running night's OWN answer to "where is tonight kept" outranks anything
#: derived here, which is why it is consulted first.
BATTERY_STATE_ROOT_ENV = "BLARAI_BATTERY_AGENTIC_STATE_ROOT"

_DEFAULT_CONFIG = (
    _REPO_ROOT / "services" / "assistant_orchestrator" / "config" / "default.toml"
)


def resolve_battery_dir(config_path: Path) -> Path | None:
    """``<agentic-setup>/state/battery`` -- the night directories and MORNING-REPORT.md.

    Nothing is invented here; both steps follow a convention already on disk. First the
    launcher's own environment variable, because the running night has already STATED where
    its state lives and a derivation that disagreed with it would read a different tree's
    nights. Failing that, the AO config resolves the fleet's agentic-setup root exactly as
    every other harness reader does (env override -> ``[fleet_dispatch]`` -> the compiled-in
    default for this box), and
    :func:`~tools.dispatch_harness.website_presentation.resolve_visible_dir` -- the same
    function the presentation step used to decide where to PUT the launcher -- names the
    directory from it. The writer and the reader agree because they call the same code, not
    because two places happen to spell the same path.
    """
    from shared.fleet.dispatch import build_default_config
    from tools.dispatch_harness.config import load_harness_config
    from tools.dispatch_harness.website_presentation import resolve_visible_dir

    stated = os.environ.get(BATTERY_STATE_ROOT_ENV, "").strip()
    if stated:
        candidate = Path(stated) / "state" / "battery"
        if candidate.is_dir():
            return candidate
    cfg = load_harness_config(config_path)
    fleet = build_default_config(cfg.agentic_setup_dir or None, cfg.projects_dir or None)
    return resolve_visible_dir(fleet.runs_dir)


def _look_failed(detail: str) -> str:
    """A websites section stating that the LOOK failed.

    Emphatically not an empty section. An empty one reads as "we checked and there were
    none" -- which is a claim, and the wrong one when the truth is that the checking never
    happened. This says which of the two it is, in the one place he reads."""
    return "\n".join([
        "## !! The websites could not be checked",
        "",
        "Something went wrong while looking for what the coder built for you, so this report",
        "CANNOT say whether a website was built or not. Read that as unknown, rather than as",
        "none: an empty space here would have looked exactly like a quiet night.",
        "",
        *textwrap.wrap(" ".join(detail.split()), width=88, initial_indent="- ",
                       subsequent_indent="  ", break_long_words=False,
                       break_on_hyphens=False),
        "",
    ])


def website_section(battery_dir: Path | None, config_path: Path) -> str:
    """What the night built him, and how he opens it. ``""`` when no website card ran.

    Guarded whole (see the module header): every fault becomes a loud paragraph rather than
    an exception, so the validation section this script already owed him survives anything
    that goes wrong here."""
    try:
        from tools.dispatch_harness.website_presentation import (
            latest_night_dir,
            read_night_websites,
            render_morning_website_section,
        )

        target = battery_dir if battery_dir is not None else resolve_battery_dir(config_path)
        if target is None:
            return _look_failed(
                "this report could not work out where the night's results are kept."
            )
        night = latest_night_dir(target)
        if night is None:
            return _look_failed(
                f"there are no night folders under {target}, so there was nothing to read. "
                "Either the coder has never run there, or it did not get as far as making one."
            )
        return render_morning_website_section(read_night_websites(night, visible_dir=target))
    except Exception as exc:  # noqa: BLE001 -- module header: never cost the exercise section
        return _look_failed(f"the check itself failed with {type(exc).__name__}: {exc}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=_DEFAULT_CONFIG)
    parser.add_argument("--exercises", type=Path, default=EXERCISE_DIR)
    parser.add_argument(
        "--battery-dir", type=Path, default=None,
        help="<agentic-setup>/state/battery. Unset resolves it the way the battery itself "
             "does -- see resolve_battery_dir.",
    )
    args = parser.parse_args(argv)

    try:
        exercises = load_exercises(args.exercises)
    except ExerciseError as exc:
        print(f"validation exercises are malformed and NOTHING was rendered: {exc}",
              file=sys.stderr)
        return 2

    try:
        config_text = args.config.read_text(encoding="utf-8")
    except OSError as exc:
        # Cannot read the config -> cannot answer "what is live", so cannot answer "what is
        # live and unchecked". Say that; do not render a coverage claim we did not compute.
        print(f"could not read {args.config} ({exc}); coverage NOT checked", file=sys.stderr)
        config_text = ""

    unvalidated = (
        unvalidated_live_capabilities(exercises, live_flags(config_text), WATCHED_FLAGS)
        if config_text else []
    )

    section = render_section(exercises, unvalidated)
    if section:
        sys.stdout.buffer.write(section.encode("utf-8"))
        sys.stdout.buffer.write(b"\n")

    # LAST, and only now: the exit-2 path above promises nothing on stdout, so the websites
    # concern must not be able to have written anything before that decision was taken.
    websites = website_section(args.battery_dir, args.config)
    if websites:
        sys.stdout.buffer.write(websites.encode("utf-8"))
        sys.stdout.buffer.write(b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
