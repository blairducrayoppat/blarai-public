"""Tests for #1165 M1 — the interview voice (template builder + I-don't-know hatch).

The slice's contract, tested from both directions per the standing intake bar:

* VOICE ON (inside an engaged interview): the question-authoring prompt speaks the
  approved novice-interview template — the Part 1 area wordings (life-not-software; the
  visual area as paired opposites) plus the question-writing mistake rules — and the
  small explicit I-don't-know phrase set routes to the same decide-defaults turn as
  "you decide", whole-reply only.
* EVERYWHERE ELSE: byte-identical to today — the builder's all-off output IS the S2
  template constant (identity-locked against the pre-builder literal below), the quick
  path never sees any of it, and the decide recognizer without the keyword is untouched.
* THE #1161 GUARD: no template output — either register — and not the preamble may
  restate a DEFAULT_AXIS_ANSWERS value inline; defaults render from that dict alone.

Model calls are faked throughout (offline, GPU-free).
"""

from __future__ import annotations

import json

from shared.fleet.clarify import (
    AXIS_CONTENT,
    AXIS_EDGE,
    AXIS_FEATURE,
    AXIS_NONGOAL,
    AXIS_PERSISTENCE,
    AXIS_SCOPE,
    AXIS_SURFACE,
    AXIS_VISUAL,
    CLARIFY_AXES,
    DEFAULT_AXIS_ANSWERS,
    EMPTY_PROJECT_SURFACE_ANSWER,
    INTAKE_AXES,
    INTAKE_AXES_ORDER,
    INTAKE_MAX_QUESTIONS,
    INTAKE_PREAMBLE,
    INTAKE_SENTINEL,
    _CLARIFY_TEMPLATE,
    _DECIDE_PHRASES,
    _INTAKE_TEMPLATE,
    compose_intake_goal,
    generate_clarifying_questions,
    intake_template_for,
    is_decide_for_me,
)

# The S2 intake template EXACTLY as it shipped as a literal (pre-#1165-M1 clarify.py,
# main 0c7ddffd). The builder's whole warrant is that its all-off output IS this text —
# pinned here as bytes so a wording drift in the builder cannot hide behind the constant
# being redefined in terms of the builder itself.
_S2_TEMPLATE_PINNED = (
    "A non-technical person asked for a software build and requested the FULLER intake "
    "interview. Ask ONLY the questions whose answers would most change WHAT gets built AND "
    "that the request has NOT already made clear. Consider at most these decision areas, "
    "and SKIP any the request already answers:\n"
    "- surface: where they will use it (on this computer, in a web browser, or on a phone)\n"
    "- persistence: whether their information should be saved between uses\n"
    "- feature: the ONE thing it must do well\n"
    "- visual: how it should look or feel\n"
    "- scope: how big a first version they want\n"
    "- content: what real text, items, or starting data it should contain\n"
    "- edge: what should happen when something odd or wrong is entered\n"
    "- nongoal: what this first version should deliberately NOT include\n"
    "Write each as ONE short, plain-language question a non-developer can answer in a "
    "sentence — no jargon, no technology names, nothing about programming. Return ONLY a "
    "JSON array (no prose) of at most {max_questions} objects, each "
    '{{"axis": "<surface|persistence|feature|visual|scope|content|edge|nongoal>", '
    '"question": "<the plain question>"}}. If the request is already clear on everything '
    "that matters, return an empty array [].\n\nRequest:\n{idea}\n"
)


# ---------------------------------------------------------------------------
# M1a — the builder: identity, order-determinism, the voice register
# ---------------------------------------------------------------------------


def test_all_off_builder_output_is_the_s2_template_byte_for_byte():
    assert intake_template_for() == _S2_TEMPLATE_PINNED
    assert _INTAKE_TEMPLATE == _S2_TEMPLATE_PINNED, \
        "the module constant must BE the builder's all-off output"


def test_intake_axes_order_pins_the_live_sequence_and_the_set_derives():
    assert INTAKE_AXES_ORDER == (
        AXIS_SURFACE, AXIS_PERSISTENCE, AXIS_FEATURE, AXIS_VISUAL, AXIS_SCOPE,
        AXIS_CONTENT, AXIS_EDGE, AXIS_NONGOAL,
    )
    assert INTAKE_AXES == frozenset(INTAKE_AXES_ORDER)
    # The S2 relations hold unchanged through the derivation.
    assert CLARIFY_AXES < INTAKE_AXES
    assert INTAKE_MAX_QUESTIONS == len(INTAKE_AXES) == len(INTAKE_AXES_ORDER) == 8


def test_builder_iterates_the_tuple_never_the_set():
    """Byte-determinism comes from the ORDER tuple (review F11a): reordering the tuple
    reorders both the area lines and the JSON instruction's axis enum."""
    reordered = (AXIS_NONGOAL, AXIS_SURFACE)
    out = intake_template_for(reordered)
    assert out.index("- nongoal:") < out.index("- surface:")
    assert '"<nongoal|surface>"' in out


def test_voice_prompt_carries_the_mistake_rules_and_paired_opposites():
    voice = intake_template_for(voice=True)
    # The mistake-rule list (arXiv 2507.02858 — the guidance that lifts machine-written
    # questions above human-written ones) is IN the authoring prompt.
    assert "one decision per question" in voice
    assert "never leading" in voice and "never hypothetical" in voice
    assert "concrete beats abstract" in voice
    # The Part 1 wordings: paired-opposite visual choices; life-not-software phrasing.
    assert "calm and professional or colorful and friendly" in voice
    assert "plain and dense with information or spacious and simple" in voice
    assert "on their phone out and about" in voice
    # The load-bearing S2 contract survives the register swap byte-relevant parts intact:
    # the sufficiency instruction, the JSON contract, and both format placeholders.
    assert "return an empty array []" in voice
    assert '"axis": "<surface|persistence|feature|visual|scope|content|edge|nongoal>"' \
        in voice.replace("{{", "{").replace("}}", "}")
    for template in (voice, intake_template_for()):
        rendered = template.format(max_questions=8, idea="a recipe box")
        assert "a recipe box" in rendered and "8" in rendered


def test_voice_keeps_edge_and_nongoal_in_the_stock_register():
    """Part 1 defers those two areas to propose-and-veto — M3's flag, not M1's. The voice
    register must leave their stock lines untouched so M3 composes instead of colliding."""
    voice = intake_template_for(voice=True)
    assert "- edge: what should happen when something odd or wrong is entered\n" in voice
    assert (
        "- nongoal: what this first version should deliberately NOT include\n" in voice
    )


def test_no_default_axis_answer_is_ever_re_pinned_inline():
    """The #1161 guard, locked: template wording (either register) and the preamble never
    restate a "you decide" default — every default rendering reads DEFAULT_AXIS_ANSWERS,
    so whatever #1161-class fix lands there is automatically what the interview speaks."""
    outputs = (
        intake_template_for(),
        intake_template_for(voice=True),
        INTAKE_PREAMBLE,
    )
    for value in list(DEFAULT_AXIS_ANSWERS.values()) + [EMPTY_PROJECT_SURFACE_ANSWER]:
        for out in outputs:
            assert value not in out, f"a default is re-pinned inline: {value[:50]!r}"


def test_the_preamble_is_the_four_phase0_promises():
    assert "no wrong answers" in INTAKE_PREAMBLE
    assert "you decide" in INTAKE_PREAMBLE
    assert "nothing is final until you've corrected it" in INTAKE_PREAMBLE
    assert "{" not in INTAKE_PREAMBLE, "deterministic text — no format placeholders"


# ---------------------------------------------------------------------------
# M1b — the I-don't-know hatch: keyword-gated, whole-reply only
# ---------------------------------------------------------------------------


def test_flag_off_recognizer_is_byte_identical():
    for phrase in _DECIDE_PHRASES:
        assert is_decide_for_me(phrase) is True
        assert is_decide_for_me(phrase.upper() + "!") is True
    for miss in ("i don't know", "no idea", "not sure", "i dont know"):
        assert is_decide_for_me(miss) is False, \
            "without the keyword the live recognizer must not widen"


def test_flag_on_admits_the_phrase_set_whole_reply_only():
    hits = (
        "i don't know", "I don't know.", "  No Idea!  ", "not sure", "Not sure,",
        "i dont know", "don't know", "I'm not sure", "im not sure", "I have no idea",
        "I don’t know",  # curly apostrophe — orthography, not fuzz
    )
    for reply in hits:
        assert is_decide_for_me(reply, dont_know=True) is True, reply
    # A reply that merely CONTAINS the words stays a substantive answer.
    partials = (
        "i don't know about the colors",
        "not sure about saving, but yes to the browser",
        "no idea for the name — call it recipes",
    )
    for reply in partials:
        assert is_decide_for_me(reply, dont_know=True) is False, reply
    # The decide phrases keep working with the keyword on.
    assert is_decide_for_me("just decide for me", dont_know=True) is True


# ---------------------------------------------------------------------------
# M1c — through generate_plan: the voice reaches ONLY the engaged interview
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


def test_voice_on_swaps_the_engaged_interview_prompt(tmp_path):
    from shared.fleet.acceptance import generate_plan

    proj, repo = _repo(tmp_path)
    gen = _Gen(questions_json=_CONTENT_Q)
    plan = generate_plan(compose_intake_goal("a recipe box"), repo, generate_fn=gen,
                         projects_dir=proj, clarify=True,
                         advanced_intake=True, interview=True, interview_voice=True)
    assert plan.ok and plan.questions, "the voiced interview must still ask"
    prompt = gen.clarify_prompts()[0]
    assert "one decision per question" in prompt
    assert "calm and professional or colorful and friendly" in prompt
    assert INTAKE_SENTINEL.strip() not in prompt


def test_voice_off_is_the_s2_prompt_and_voice_alone_engages_nothing(tmp_path):
    from shared.fleet.acceptance import generate_plan

    proj, repo = _repo(tmp_path)
    # Engaged interview, voice OFF: the prompt is the S2 template's bytes exactly.
    gen_off = _Gen(questions_json=_CONTENT_Q)
    generate_plan(compose_intake_goal("a recipe box"), repo, generate_fn=gen_off,
                  projects_dir=proj, clarify=True,
                  advanced_intake=True, interview=True)
    assert gen_off.clarify_prompts() == [
        _S2_TEMPLATE_PINNED.format(max_questions=8, idea="a recipe box")
    ]
    # No marker (a plain quick dispatch): the voice flag alone reads nothing — the
    # prompts are byte-identical to a run that never knew the flag existed.
    base, flagged = _Gen(), _Gen()
    generate_plan("a recipe box", repo, generate_fn=base,
                  projects_dir=proj, clarify=True)
    generate_plan("a recipe box", repo, generate_fn=flagged,
                  projects_dir=proj, clarify=True,
                  advanced_intake=True, interview=True, interview_voice=True)
    assert flagged.prompts == base.prompts
    assert _CLARIFY_TEMPLATE.format(max_questions=5, idea="a recipe box") \
        in base.prompts
