"""Tests for #1031 S2 — the elicitation interview (clarify.py vocabulary + AO engagement).

The slice's contract, tested from both directions per the standing intake bar:

* IN INTAKE MODE (the marker + BOTH knobs): the clarify stage runs the eight-axis
  vocabulary, the intake template, and the structural one-per-axis cap; the three new
  axes carry recorded "just decide" defaults; the marker is stripped before anything
  downstream can see it.
* EVERYWHERE ELSE: byte-identical to today — the quick path's five axes and cap via
  default arguments (not a restoring branch), the marker as INERT TEXT when either knob
  is off (including an operator who typed it by hand), and battery cards never
  interviewed (the clarify gate's own suppression, inherited and locked anyway).

Model calls are faked throughout (offline, GPU-free).
"""

from __future__ import annotations

import json

from shared.fleet.acceptance import (
    AcceptanceSpec,
    _coerce_clarifications,
    generate_plan,
)
from shared.fleet.clarify import (
    AXIS_CONTENT,
    AXIS_EDGE,
    AXIS_NONGOAL,
    CLARIFY_AXES,
    DEFAULT_AXIS_ANSWERS,
    DEFAULT_MAX_QUESTIONS,
    INTAKE_AXES,
    INTAKE_MAX_QUESTIONS,
    INTAKE_SENTINEL,
    _CLARIFY_TEMPLATE,
    _INTAKE_TEMPLATE,
    ClarifyQuestion,
    answered_from_free_text,
    clarify_questions_emission_json_schema,
    compose_intake_goal,
    decide_defaults,
    generate_clarifying_questions,
    questions_from_dicts,
    split_intake_goal,
)

# ---------------------------------------------------------------------------
# S2a — vocabulary, defaults, cap, sentinel
# ---------------------------------------------------------------------------


def test_intake_axes_is_a_strict_superset_and_cap_matches():
    assert CLARIFY_AXES < INTAKE_AXES
    assert INTAKE_AXES - CLARIFY_AXES == {AXIS_CONTENT, AXIS_EDGE, AXIS_NONGOAL}
    assert INTAKE_MAX_QUESTIONS == len(INTAKE_AXES) == 8
    assert DEFAULT_MAX_QUESTIONS == 5  # untouched


def test_each_new_axis_self_answers_to_its_recorded_assumption():
    qs = [
        ClarifyQuestion(axis=AXIS_CONTENT, question="What should it contain?"),
        ClarifyQuestion(axis=AXIS_EDGE, question="What about odd input?"),
        ClarifyQuestion(axis=AXIS_NONGOAL, question="What should it NOT do?"),
    ]
    answers = [c["answer"] for c in decide_defaults(qs)]
    assert answers[0] == DEFAULT_AXIS_ANSWERS[AXIS_CONTENT]
    assert "invented" in answers[0], "the content default must bake the placeholder lesson"
    assert "clear message" in answers[1]
    assert "no extra features" in answers[2]


def test_cap_is_structural_one_question_per_axis():
    """A 20-item emission over all eight axes (with duplicates) rules to at most 8, one
    per axis — the bound comes from the dedupe, not from hoping the model counts."""
    emission = json.dumps(
        [{"axis": a, "question": f"Question about {a} number {i}?"}
         for i in range(3) for a in sorted(INTAKE_AXES)]
    )
    out = generate_clarifying_questions(
        "a vague thing", generate_fn=lambda p: emission,
        max_questions=INTAKE_MAX_QUESTIONS, axes=INTAKE_AXES,
        template=_INTAKE_TEMPLATE,
    )
    assert len(out) == 8
    assert len({q.axis for q in out}) == 8


def test_quick_path_defaults_are_byte_identical():
    """The OFF state is the old code path via default arguments: same prompt bytes, same
    schema bytes, same parse — driven with the same fake emission."""
    prompts: list[str] = []

    def gen(prompt: str) -> str:
        prompts.append(prompt)
        return json.dumps([{"axis": "surface", "question": "Where will you use it?"}])

    out = generate_clarifying_questions("a habit tracker", generate_fn=gen)
    assert prompts == [_CLARIFY_TEMPLATE.format(max_questions=5, idea="a habit tracker")]
    assert [q.axis for q in out] == ["surface"]
    # Schema bytes: the default schema pins exactly the five-axis enum, as before.
    schema = clarify_questions_emission_json_schema()
    assert schema["items"]["properties"]["axis"]["enum"] == sorted(CLARIFY_AXES)
    assert schema["maxItems"] == 5


def test_intake_axes_coerce_to_feature_on_the_quick_path():
    """The wider vocabulary is UNREACHABLE without the axes parameter — a content-tagged
    emission on the quick path coerces to feature, exactly as any unknown axis does."""
    emission = json.dumps([{"axis": AXIS_CONTENT, "question": "What content goes in?"}])
    out = generate_clarifying_questions("x app", generate_fn=lambda p: emission)
    assert [q.axis for q in out] == ["feature"]


def test_parked_intake_questions_reconstruct_with_the_right_axes():
    """The design's §1 item 3 defect, locked: a stored content question mislabels as
    feature under the five-axis default and keeps its axis under INTAKE_AXES."""
    stored = [{"axis": AXIS_CONTENT, "question": "What content should it hold?"}]
    assert [q.axis for q in questions_from_dicts(stored)] == ["feature"]
    assert [q.axis for q in questions_from_dicts(stored, axes=INTAKE_AXES)] == [
        AXIS_CONTENT
    ]


def test_record_axes_tags_and_flag_off_byte_identity():
    qs = [
        ClarifyQuestion(axis=AXIS_CONTENT, question="Content?"),
        ClarifyQuestion(axis="surface", question="Where?"),
    ]
    plain = decide_defaults(qs)
    assert all("axes" not in c for c in plain), "quick-path dicts must gain nothing"
    tagged = decide_defaults(qs, record_axes=True)
    assert [c["axes"] for c in tagged] == [[AXIS_CONTENT], ["surface"]]

    free_plain = answered_from_free_text(qs, "real recipes; fail politely")
    assert "axes" not in free_plain[0]
    free_tagged = answered_from_free_text(qs, "real recipes", record_axes=True)
    assert free_tagged[0]["axes"] == [AXIS_CONTENT, "surface"], \
        "the one merged reply carries the FULL asked-axes list"


def test_intake_sentinel_roundtrip_and_double_marker():
    marked = compose_intake_goal("a recipe box")
    assert marked.endswith(INTAKE_SENTINEL.rstrip("\n")) or INTAKE_SENTINEL in marked
    clean, was_marked = split_intake_goal(marked)
    assert (clean, was_marked) == ("a recipe box", True)
    assert split_intake_goal("a recipe box") == ("a recipe box", False)
    # A hand-typed double marker is fully removed — defense in depth.
    doubled = marked + INTAKE_SENTINEL
    clean2, _ = split_intake_goal(doubled)
    assert INTAKE_SENTINEL.strip() not in clean2


# ---------------------------------------------------------------------------
# S2b — through generate_plan: engagement, hygiene, toggle-off, card suppression
# ---------------------------------------------------------------------------


def _repo(tmp_path, name="recipes"):
    proj = tmp_path / "projects"
    (proj / name / ".git").mkdir(parents=True, exist_ok=True)
    return proj, name


class _Gen:
    """Records prompts; answers the clarify stage per the scripted emission and
    everything downstream with a one-task plan."""

    def __init__(self, questions_json: str = "[]"):
        self.questions_json = questions_json
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if "decision areas" in prompt:
            return self.questions_json
        if "decomposing a software change request" in prompt:
            return json.dumps([{"task": "build-it", "prompt": "Build the thing."}])
        if "ACCEPTANCE CRITERIA" in prompt:
            return json.dumps([{"text": "it works", "tier": "behavior",
                                "check": "run it"}])
        if "Classify what KIND of software" in prompt:
            return json.dumps({"surface": "command-line", "candidates": [],
                               "language_hint": "python", "complexity": "simple",
                               "components": []})
        return "[]"

    def clarify_prompts(self) -> list[str]:
        return [p for p in self.prompts if "decision areas" in p]


_CONTENT_Q = json.dumps([{"axis": AXIS_CONTENT,
                          "question": "What recipes should it start with?"}])


def test_marker_plus_both_knobs_runs_the_intake_interview(tmp_path):
    proj, repo = _repo(tmp_path)
    gen = _Gen(questions_json=_CONTENT_Q)
    plan = generate_plan(compose_intake_goal("a recipe box"), repo, generate_fn=gen,
                         projects_dir=proj, clarify=True,
                         advanced_intake=True, interview=True)
    assert plan.ok and plan.questions, "the intake interview must ask"
    assert plan.questions[0]["axis"] == AXIS_CONTENT
    clarify_prompt = gen.clarify_prompts()[0]
    assert "- content:" in clarify_prompt and "- nongoal:" in clarify_prompt, \
        "the INTAKE template must drive the interview"
    assert INTAKE_SENTINEL.strip() not in clarify_prompt, \
        "the marker never reaches a prompt"


def test_marker_hygiene_nothing_downstream_sees_it(tmp_path):
    """Engaged marker + a sufficient goal (zero questions): the sentinel must be absent
    from spec.goal, every compiled prompt, and the plan message."""
    proj, repo = _repo(tmp_path)
    gen = _Gen(questions_json="[]")
    plan = generate_plan(compose_intake_goal("a recipe box"), repo, generate_fn=gen,
                         projects_dir=proj, clarify=True,
                         advanced_intake=True, interview=True)
    assert plan.ok and plan.tasks and not plan.questions
    assert INTAKE_SENTINEL.strip() not in plan.spec.goal
    assert plan.spec.goal == "a recipe box"
    assert all(INTAKE_SENTINEL.strip() not in t.get("prompt", "") for t in plan.tasks)
    assert all(INTAKE_SENTINEL.strip() not in p for p in gen.prompts)


def test_either_knob_off_leaves_the_marker_inert_and_planning_byte_identical(tmp_path):
    """The toggle-off bar, on the adversarial input: a marker-CARRYING goal. With the
    interview off the marker is inert text — the same bytes ride the goal everywhere a
    plain goal's bytes would, identically to a run that never knew the flag existed."""
    proj, repo = _repo(tmp_path)
    marked = compose_intake_goal("a recipe box")
    runs = {}
    for name, knobs in {
        "default": {},
        "front_only": {"advanced_intake": True},
        "interview_only": {"interview": True},
    }.items():
        gen = _Gen(questions_json="[]")
        runs[name] = (
            generate_plan(marked, repo, generate_fn=gen, projects_dir=proj,
                          clarify=True, **knobs),
            gen,
        )
    base_plan, base_gen = runs["default"]
    # The inert marker rides INTO the clarify prompt and spec.goal — untouched.
    assert INTAKE_SENTINEL.strip() in base_gen.clarify_prompts()[0]
    assert INTAKE_SENTINEL.strip() in base_plan.spec.goal
    for name in ("front_only", "interview_only"):
        plan, gen = runs[name]
        assert gen.prompts == base_gen.prompts, f"{name}: prompts diverged"
        assert plan.spec.to_dict() == base_plan.spec.to_dict(), f"{name}: spec diverged"
        assert plan.message == base_plan.message, f"{name}: message diverged"
    # The five-axis template ran in all three (never the intake one).
    assert "- nongoal:" not in base_gen.clarify_prompts()[0]


def test_battery_card_never_interviews_even_fully_engaged(tmp_path):
    """Inherited suppression, locked anyway: a decomposition_override dispatch cannot
    reach the interview — the clarify gate's own predicate suppresses it."""
    from shared.fleet.acceptance import DecompositionOverride

    proj, repo = _repo(tmp_path, name="battery-b4-flashcards-cli")
    gen = _Gen(questions_json=_CONTENT_Q)
    plan = generate_plan(
        compose_intake_goal("a flashcards quiz"), repo, generate_fn=gen,
        projects_dir=proj, clarify=True, advanced_intake=True, interview=True,
        decomposition_override=DecompositionOverride(
            tasks=[{"task": "build-it", "prompt": "Build it."}]),
    )
    assert plan.ok and not plan.questions
    assert gen.clarify_prompts() == [], "a card dispatch must never be interviewed"


# ---------------------------------------------------------------------------
# S2d — the record's axes carry (the whitelist, extended not assumed)
# ---------------------------------------------------------------------------


def test_coerce_clarifications_carries_vocabulary_members_only():
    """Review F5: the carry is MEMBERSHIP-validated against the closed intake vocabulary
    — junk labels ("7", blanks) are dropped, never propagated onto the record."""
    coerced = _coerce_clarifications([
        {"question": "q1", "answer": "real recipes", "assumed": False,
         "axes": [AXIS_CONTENT, "  ", 7, "surface"]},
        {"question": "q2", "answer": "saved", "assumed": True},
        {"question": "q3", "answer": "quick", "assumed": False, "axes": "content"},
        {"question": "q4", "answer": "fast", "assumed": False, "axes": ["ghost"]},
    ])
    assert coerced[0]["axes"] == [AXIS_CONTENT, "surface"], \
        "only closed-vocabulary members survive"
    assert "axes" not in coerced[1], "a dict without the key must never gain it"
    assert "axes" not in coerced[2], "a non-list axes value is dropped fail-closed"
    assert "axes" not in coerced[3], "an all-junk list must not mint an empty key"


def test_free_text_with_no_questions_never_mints_empty_axes():
    assert "axes" not in answered_from_free_text((), "words", record_axes=True)[0]


def test_axes_survive_the_spec_roundtrip_and_quick_dicts_gain_nothing():
    spec = AcceptanceSpec(
        goal="a recipe box",
        clarifications=(
            {"question": "asked", "answer": "real recipes", "assumed": False,
             "axes": [AXIS_CONTENT]},
            {"question": "asked2", "answer": "saved", "assumed": True},
        ),
    )
    restored = AcceptanceSpec.from_dict(spec.to_dict())
    assert restored.clarifications[0].get("axes") == [AXIS_CONTENT]
    assert "axes" not in restored.clarifications[1]


def test_axes_survive_the_DISK_record_roundtrip(tmp_path):
    """Review F1 (code review): the design-committed END-TO-END lock — spec → to_dict →
    write_acceptance_record → disk → read_acceptance_record → from_dict, tags intact for
    the intake dict and NOTHING minted for the quick dict."""
    from shared.fleet import dispatch as fleet

    config = fleet.FleetDispatchConfig(
        scripts_dir=tmp_path / "scripts", queue_path=tmp_path / "q.json",
        runs_dir=tmp_path / "runs", projects_dir=tmp_path / "projects",
    )
    spec = AcceptanceSpec(
        goal="a recipe box",
        clarifications=(
            {"question": "asked", "answer": "real recipes", "assumed": False,
             "axes": [AXIS_CONTENT]},
            {"question": "asked2", "answer": "saved", "assumed": True},
        ),
    )
    fleet.write_acceptance_record(config, "RID-AX", spec_dict=spec.to_dict(),
                                  repo=str(tmp_path / "projects" / "recipes"))
    record = fleet.read_acceptance_record(config, "RID-AX")
    assert record is not None
    restored = AcceptanceSpec.from_dict(record["spec"])
    assert restored.clarifications[0].get("axes") == [AXIS_CONTENT], \
        "the tags must survive the DISK record round-trip"
    assert "axes" not in restored.clarifications[1], \
        "a quick dict must gain nothing through the disk round-trip"
