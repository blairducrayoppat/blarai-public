"""
A live capability with no way to check it is the state this design exists to prevent (#1327).
==============================================================================================

The LA stopped being the pre-commit gate on capability go-live on 2026-08-07. The trade is
sound only while three obligations hold, and these are the locks on them:

  * every observable step tells him what he should SEE,
  * every exercise carries a one-action ROLLBACK,
  * a live watched flag with NO exercise fails LOUDLY rather than passing quietly.

The third is the deny-by-default one and the reason this file lives in tests/security/.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shared.validation.exercise import (
    ACTIONS,
    Exercise,
    ExerciseError,
    Step,
    live_flags,
    load_exercises,
    parse_exercise,
    render_section,
    unvalidated_live_capabilities,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_CONFIG = _REPO_ROOT / "services" / "assistant_orchestrator" / "config" / "default.toml"

#: The flags this project has agreed to hand the operator a check for. Adding a flag here
#: WITHOUT writing its exercise makes the coverage test fail -- that pressure is the point.
WATCHED_FLAGS: frozenset[str] = frozenset({"advanced_intake_interview"})


@pytest.fixture(scope="module")
def exercises() -> list[Exercise]:
    return load_exercises()


def _minimal(**over) -> dict:
    base = {
        "capability": "9. Example", "flag": "example_flag", "title": "T",
        "observable": "O", "why": "W", "minutes": 3,
        "rollback": "press [K]",
        "steps": [{"action": "click", "target": "the button", "expect": "a thing"}],
    }
    base.update(over)
    return base


# --------------------------------------------------------------------------------------
# The real exercises on disk
# --------------------------------------------------------------------------------------

def test_the_shipped_exercises_all_parse(exercises):
    """A malformed exercise must fail HERE, not by rendering a wrong instruction into the
    one document he trusts and acts on."""
    assert exercises, "no exercises found; the morning section would be empty"


def test_every_live_watched_capability_has_an_exercise(exercises):
    """DENY-BY-DEFAULT. Live-and-unvalidatable is the exact state this design prevents."""
    flags = live_flags(_CONFIG.read_text(encoding="utf-8"))
    missing = unvalidated_live_capabilities(exercises, flags, WATCHED_FLAGS)
    assert not missing, (
        "these flags are LIVE and have no validation exercise, so nobody can confirm they "
        f"work: {missing}. Write the exercise, or take the flag out of WATCHED_FLAGS and say "
        "why in the same change."
    )


def test_every_exercise_quotes_a_real_observable(exercises):
    """The exercise renders the capability's OWN observable. An exercise that invents its own
    success criterion drifts from the claim -- which is how capability 2 read LIVE for a week
    while its observable had never been executed."""
    dod = (_REPO_ROOT / "docs" / "design" / "CODER_DEFINITION_OF_DONE.md").read_text(encoding="utf-8")
    for ex in exercises:
        assert ex.observable.strip(), f"{ex.flag}: no observable"
        assert ex.capability.split(".")[0].strip() in dod, (
            f"{ex.flag}: capability '{ex.capability}' is not in the definition of done"
        )


def test_every_exercise_has_a_rollback(exercises):
    """The reciprocal obligation of taking the go-live decision: he gets a way to undo it."""
    for ex in exercises:
        assert ex.rollback.strip(), f"{ex.flag}: no rollback"


def test_typed_steps_carry_verbatim_text(exercises):
    """The exact words are the test. A paraphrase is a different test."""
    for ex in exercises:
        for step in ex.steps:
            if step.action in {"type", "paste"}:
                assert step.text.strip(), f"{ex.flag}: a '{step.action}' step has no verbatim text"


def test_no_exercise_uses_jargon_in_its_instructions(exercises):
    """Built for a non-technical reader. If an instruction needs a developer to decode it,
    it cannot be executed by the person it is written for."""
    banned = ("stdout", "stderr", "venv", "pytest", "commit", "SHA", "regex",
              "JSON", "API", "CLI", "repo ", "branch")
    for ex in exercises:
        for step in ex.steps:
            blob = f"{step.target} {step.expect} {step.note}"
            hits = [w for w in banned if w.lower() in blob.lower()]
            assert not hits, f"{ex.flag}: step text uses developer jargon {hits}: {blob[:90]!r}"


# --------------------------------------------------------------------------------------
# The loader refuses what would mislead him
# --------------------------------------------------------------------------------------

def test_a_step_with_no_expect_is_REFUSED():
    """Without 'you should see', he cannot tell pass from fail and the exercise is decoration."""
    bad = _minimal(steps=[{"action": "click", "target": "the button"}])
    with pytest.raises(ExerciseError, match="expect"):
        parse_exercise(bad, Path("bad.json"))


def test_a_typed_step_with_no_text_is_REFUSED():
    bad = _minimal(steps=[{"action": "type", "target": "the box", "expect": "a reply"}])
    with pytest.raises(ExerciseError, match="verbatim"):
        parse_exercise(bad, Path("bad.json"))


def test_an_exercise_with_no_rollback_is_REFUSED():
    """A capability nobody can switch off must not go live by default."""
    bad = _minimal()
    del bad["rollback"]
    with pytest.raises(ExerciseError, match="rollback"):
        parse_exercise(bad, Path("bad.json"))


def test_an_unfollowable_action_is_REFUSED():
    bad = _minimal(steps=[{"action": "reconfigure", "target": "x", "expect": "y"}])
    with pytest.raises(ExerciseError, match="allowed"):
        parse_exercise(bad, Path("bad.json"))


def test_a_wait_step_needs_no_expect():
    """The one exemption, and it is narrow: waiting produces nothing to observe."""
    ok = _minimal(steps=[{"action": "wait", "target": "about a minute"}])
    assert parse_exercise(ok, Path("ok.json")).steps[0].action == "wait"


# --------------------------------------------------------------------------------------
# live_flags reads what is ON, not what is mentioned
# --------------------------------------------------------------------------------------

def test_commented_out_flags_are_not_live():
    """A commented line naming a flag must never read as that flag being on."""
    text = "# advanced_intake_interview = true\nreal_flag = true\noff_flag = false\n"
    assert live_flags(text) == {"real_flag"}


def test_the_coverage_check_fires_when_a_live_flag_has_no_exercise():
    """Principle 12: prove the lock FAILS when the thing it guards is absent."""
    ex = [parse_exercise(_minimal(flag="covered_flag"), Path("a.json"))]
    missing = unvalidated_live_capabilities(ex, {"covered_flag", "naked_flag"},
                                            {"covered_flag", "naked_flag"})
    assert missing == ["naked_flag"], "a live watched flag with no exercise must be named"


def test_the_coverage_check_is_quiet_when_everything_is_covered():
    ex = [parse_exercise(_minimal(flag="covered_flag"), Path("a.json"))]
    assert unvalidated_live_capabilities(ex, {"covered_flag"}, {"covered_flag"}) == []


def test_a_watched_flag_that_is_NOT_live_needs_no_exercise():
    """Dormant is not a gap. Only live-and-unvalidatable is."""
    assert unvalidated_live_capabilities([], set(), {"dormant_flag"}) == []


# --------------------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------------------

def test_the_section_states_the_total_time_up_front(exercises):
    """His attention is a managed resource; he decides to start knowing the cost."""
    out = render_section(exercises)
    assert "Total time: about" in out


def test_the_section_prints_the_rollback_even_when_nothing_looks_wrong(exercises):
    out = render_section(exercises)
    for ex in exercises:
        assert ex.rollback.split(" — ")[0][:30] in out or ex.rollback[:30] in out


def test_verbatim_text_is_rendered_as_a_copyable_block():
    ex = parse_exercise(_minimal(
        steps=[{"action": "type", "target": "the box", "expect": "a reply", "text": "hello there"}]
    ), Path("a.json"))
    out = render_section([ex])
    assert "> hello there" in out
    assert "Use exactly this text" in out


def test_unvalidated_flags_render_LOUDLY():
    out = render_section([], ["naked_flag"])
    assert "LIVE WITH NO WAY TO CHECK IT" in out
    assert "naked_flag" in out


def test_an_empty_day_renders_nothing():
    """No exercises and no gaps means no section -- never a heading with nothing under it."""
    assert render_section([], []) == ""


def test_every_step_renders_its_expected_result(exercises):
    out = render_section(exercises)
    for ex in exercises:
        for step in ex.steps:
            if step.expect:
                assert step.expect[:40] in out, f"{ex.flag}: an expected result was not rendered"
