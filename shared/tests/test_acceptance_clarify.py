"""Tests for #819 — the requirements-clarification stage inside ``generate_plan``.

The CLARIFY stage sits BETWEEN the dispatch request and decompose: when the stage is on and
the goal is underspecified, ``generate_plan`` asks a few questions and RETURNS EARLY with them
(no tasks/spec); after the operator answers, the re-plan threads the compact requirements block
into decompose + criteria + assumptions + build-signal + both oracles + every task prompt while
``spec.goal`` stays clean. A battery/headless card dispatch NEVER clarifies. ``clarify=False``
(the default) is byte-identical to the pre-#819 plan.

Model calls are faked throughout (offline — the live 14B proof rides the next live dispatch).
"""

from __future__ import annotations

import json

from shared.fleet import acceptance as acc
from shared.fleet import clarify as clr
from shared.fleet import oracle_qa as oq
from shared.fleet.acceptance import (
    AcceptanceSpec,
    DecompositionOverride,
    generate_plan,
)

# The clarify prompt's unique routing marker — pinned to the real template so a rewrite that
# breaks the fakes' routing fails loudly here, not silently.
_MARKER_CLARIFY = "ask ONLY the few questions"
_MARKER_DECOMPOSE = "decomposing a software change request"
_MARKER_CRITERIA = "ACCEPTANCE CRITERIA"
_MARKER_BUILD_PLAN = "Classify what KIND of software"

_QUESTIONS_JSON = json.dumps([
    {"axis": "surface", "question": "Where will you use this — computer, browser, or phone?"},
    {"axis": "persistence", "question": "Should your information be saved between uses?"},
])
_ONE_TASK_JSON = json.dumps([{"task": "build-it", "prompt": "Build the thing."}])
_CRITERIA_JSON = json.dumps([{"text": "the project builds", "tier": "build", "check": ""}])

# #1032 — the multi-task shape, which is the ONLY one that reaches the job-oracle author.
# Pinned to the real template so a rewrite breaks this loudly instead of silently skipping.
_MARKER_JOB_ORACLE = "the executable JOB-LEVEL ACCEPTANCE"
# Two tasks, each declaring a contract: generate_job_acceptance_oracle fail-closes to ("", "")
# on <2 tasks OR when no task declares creates/exports, so both are load-bearing here.
_TWO_TASK_JSON = json.dumps([
    {"task": "store", "prompt": "Build the store.",
     "contract": {"creates": ["store.py"], "exports": ["add_item(text)"]}},
    {"task": "view", "prompt": "Build the view.",
     "contract": {"creates": ["view.py"], "exports": ["render(items)"]}},
])
# A behavior-tier criterion: the author also fail-closes when no criterion is in TEST_TIERS.
_TESTABLE_CRITERIA_JSON = json.dumps([
    {"text": "adding an entry shows it in the list", "tier": "behavior",
     "check": "pytest test_todo.py"},
])

# #1043 — an operator answer whose distinctive word ("Saved") appears NOWHERE in the goal or
# the criteria above, and the oracle that legitimately encodes it. The word reaches the exam
# only because the operator asked for it, so a finding against it is a false conviction.
_OPERATOR_ANSWER = "show the word Saved after each entry"
_GROUNDED_ORACLE = (
    "from store import add_item\n\n"
    "def test_adding_an_entry_confirms():\n"
    "    assert add_item('milk') == 'Saved'\n"
)


def _repo(tmp_path):
    proj = tmp_path / "projects"
    (proj / "myapp" / ".git").mkdir(parents=True, exist_ok=True)
    return proj, "myapp"


def _gen(calls: list, *, questions: str = _QUESTIONS_JSON):
    """A recording free-text generate_fn routing each PLAN prompt to a canned emission."""

    def gen(prompt: str) -> str:
        calls.append(prompt)
        if _MARKER_CLARIFY in prompt:
            return questions
        if _MARKER_CRITERIA in prompt:
            return _CRITERIA_JSON
        if _MARKER_BUILD_PLAN in prompt:
            return json.dumps({"surface": "desktop-gui", "candidates": [],
                               "language_hint": None, "complexity": "simple", "components": []})
        if _MARKER_DECOMPOSE in prompt:
            return _ONE_TASK_JSON
        return "[]"  # assumptions / assets

    return gen


def _gen_multitask(calls: list, *, questions: str = _QUESTIONS_JSON,
                   oracle: str = "def test_adds_an_entry():\n    assert True\n"):
    """#1032 — like :func:`_gen`, but decomposes to TWO contract-declaring tasks with a
    python language hint, so the job-oracle author is actually reached. The job-oracle
    emission itself returns a minimal valid pytest file (the author structurally validates
    it with ``ast.parse`` + a ``test`` function and fail-closes on anything else).

    ``questions="[]"`` models a SUFFICIENT goal — the clarify sufficiency check asks nothing
    and planning proceeds, which is the only way to reach the job-oracle author with clarify
    ON and no requirements. ``oracle`` overrides the emitted oracle so a caller can model a
    specific authored shape (#1043)."""

    def gen(prompt: str) -> str:
        calls.append(prompt)
        if _MARKER_CLARIFY in prompt:
            return questions
        if _MARKER_JOB_ORACLE in prompt:
            return oracle
        if _MARKER_CRITERIA in prompt:
            return _TESTABLE_CRITERIA_JSON
        if _MARKER_BUILD_PLAN in prompt:
            return json.dumps({"surface": "desktop-gui", "candidates": [],
                               "language_hint": "python", "complexity": "simple",
                               "components": []})
        if _MARKER_DECOMPOSE in prompt:
            return _TWO_TASK_JSON
        return "[]"  # assumptions / assets

    return gen


def test_marker_matches_template():
    assert _MARKER_CLARIFY in clr._CLARIFY_TEMPLATE
    # #1032: the job-oracle routing marker is pinned to the real template too — otherwise a
    # template rewrite would make the multi-task locks below silently stop reaching the
    # author, and a vacuous lock is worse than none.
    assert _MARKER_JOB_ORACLE in acc._JOB_ORACLE_TEMPLATE_PY


# ---- the CLARIFY early-return --------------------------------------------


def test_clarify_on_underspecified_returns_questions_and_no_plan(tmp_path):
    proj, repo = _repo(tmp_path)
    calls: list = []
    plan = generate_plan("a todo app", repo, generate_fn=_gen(calls),
                         projects_dir=proj, clarify=True)
    assert plan.ok
    assert [q["axis"] for q in plan.questions] == ["surface", "persistence"]
    assert plan.tasks == [] and plan.spec.criteria == ()   # no decompose/criteria ran
    # ONLY the clarify prompt was issued (the expensive sequence never fired).
    assert all(_MARKER_CLARIFY in p for p in calls)


def test_clarify_off_is_byte_identical_no_questions(tmp_path):
    proj, repo = _repo(tmp_path)
    calls: list = []
    plan = generate_plan("a todo app", repo, generate_fn=_gen(calls),
                         projects_dir=proj, clarify=False)
    assert plan.questions == [] and len(plan.tasks) >= 1
    assert not any(_MARKER_CLARIFY in p for p in calls)  # clarify prompt never issued


def test_sufficient_goal_proceeds_to_plan(tmp_path):
    proj, repo = _repo(tmp_path)
    calls: list = []
    # Model judges the goal sufficient (returns []) -> planning proceeds, no early return.
    plan = generate_plan("a todo app", repo, generate_fn=_gen(calls, questions="[]"),
                         projects_dir=proj, clarify=True)
    assert plan.questions == [] and len(plan.tasks) >= 1
    assert any(_MARKER_CLARIFY in p for p in calls)  # the sufficiency check DID run


def test_clarify_fail_soft_proceeds_to_plan(tmp_path):
    proj, repo = _repo(tmp_path)

    def gen(prompt: str) -> str:
        if _MARKER_CLARIFY in prompt:
            raise RuntimeError("clarify model crashed")
        if _MARKER_CRITERIA in prompt:
            return _CRITERIA_JSON
        if _MARKER_DECOMPOSE in prompt:
            return _ONE_TASK_JSON
        return "[]"

    plan = generate_plan("a todo app", repo, generate_fn=gen, projects_dir=proj, clarify=True)
    assert plan.questions == [] and len(plan.tasks) >= 1  # degraded to direct decompose


# ---- requirements threading (the re-plan) --------------------------------


def test_requirements_thread_into_prompts_and_tasks_and_spec_goal_stays_clean(tmp_path):
    proj, repo = _repo(tmp_path)
    calls: list = []
    req = clr.compose_requirements_block([
        {"question": "q", "answer": "on my computer", "assumed": False},
        {"question": "q2", "answer": "save my todos", "assumed": True},
    ])
    plan = generate_plan("a todo app", repo, generate_fn=_gen(calls),
                         projects_dir=proj, clarify=True, requirements=req)
    # clarify is SUPPRESSED on a re-plan (requirements present).
    assert plan.questions == [] and not any(_MARKER_CLARIFY in p for p in calls)
    # the requirements seeded the sub-generation prompts...
    assert any("on my computer" in p for p in calls)
    # ...and ride EVERY compiled task context, verbatim + delimited...
    assert plan.tasks and all(
        "Clarified requirements" in t["prompt"] and "on my computer" in t["prompt"]
        for t in plan.tasks
    )
    # ...while spec.goal stays the CLEAN original (no block in the preview header).
    assert plan.spec.goal == "a todo app"


def test_requirements_reach_the_MULTI_task_job_oracle_author(tmp_path):
    """#1032 — the job exam is authored FROM the operator's answers, not blind to them.

    The single-task oracle already received the enriched planning seed; the multi-task branch
    passed the clean goal, so on a >=2-task dispatch the job-level exam — the thing the whole
    job is graded against — never saw what the operator said. The two oracles must be authored
    from the same text the coder builds to.

    Drives the REAL ``generate_plan`` and captures the REAL job-oracle authoring prompt (the
    template's own marker, pinned below), rather than asserting on the argument: the argument
    is the mechanism, the prompt is the guarantee.
    """
    proj, repo = _repo(tmp_path)
    calls: list = []
    req = clr.compose_requirements_block([
        {"question": "where", "answer": "in a web browser", "assumed": False},
        {"question": "keep", "answer": "remember my entries between visits", "assumed": False},
    ])
    plan = generate_plan("a todo app", repo, generate_fn=_gen_multitask(calls),
                         projects_dir=proj, clarify=True, requirements=req)

    job_prompts = [p for p in calls if _MARKER_JOB_ORACLE in p]
    # Vacuity guard: a lock that passes because the branch never ran proves nothing.
    assert len(job_prompts) == 1, f"job-oracle author not reached ({len(job_prompts)} prompts)"
    assert len(plan.tasks) >= 2

    # The operator's ANSWERS are in the exam-authoring prompt, verbatim.
    assert "in a web browser" in job_prompts[0]
    assert "remember my entries between visits" in job_prompts[0]
    # The block's real header rides too. This is the POSITIVE half of the pair whose
    # negative half the byte-identity lock asserts — together they prove that string
    # discriminates, so neither assertion can be vacuous.
    assert "The person clarified these requirements" in job_prompts[0]
    # Same text the coder is told to build to — the two must not diverge.
    assert all("remember my entries between visits" in t["prompt"] for t in plan.tasks)


def test_no_requirements_leaves_the_job_oracle_prompt_byte_identical(tmp_path):
    """Clarify ON with a SUFFICIENT goal produces a byte-identical job-oracle prompt to
    clarify OFF — the sufficiency check costs a model call and must cost nothing else.

    Scope, stated precisely because an earlier draft of this docstring overclaimed it: this
    does NOT prove #1032's inertness. Both arms pass ``requirements=""``, so
    ``planning_seed`` IS ``goal`` in both by the one-line conditional at the mint site, and
    the equality therefore holds with or without the fix (the #1032 mutant leaves this test
    GREEN — deliberately; that is the correct discrimination). Inertness is proved by
    reading that conditional, which is stronger than any equality this test could assert.

    Both arms must actually reach the author, so the clarify arm models a sufficient goal.
    An empty ``requirements`` with clarify ON does NOT reach it — that combination is the
    clarify early-return, which is correct and is why the first draft of this lock failed.
    """
    proj, repo = _repo(tmp_path)
    off_calls: list = []
    generate_plan("a todo app", repo, generate_fn=_gen_multitask(off_calls),
                  projects_dir=proj, clarify=False)
    clarify_off = [p for p in off_calls if _MARKER_JOB_ORACLE in p]
    assert len(clarify_off) == 1

    on_calls: list = []
    generate_plan("a todo app", repo, generate_fn=_gen_multitask(on_calls, questions="[]"),
                  projects_dir=proj, clarify=True)
    sufficient_goal = [p for p in on_calls if _MARKER_JOB_ORACLE in p]
    assert len(sufficient_goal) == 1
    assert clarify_off[0] == sufficient_goal[0]
    # And neither carries a requirements block — the seed was the bare goal. Asserted on
    # compose_requirements_block's real HEADER, not on REQUIREMENTS_SENTINEL: generate_plan
    # builds the seed inline (`goal + "\n\n" + req`) and never calls compose_planning_goal,
    # so the sentinel is absent from this prompt under EVERY input and asserting its absence
    # would be vacuous.
    assert "The person clarified these requirements" not in clarify_off[0]


def test_operator_supplied_return_value_is_not_convicted_as_invented(tmp_path):
    """#1043 — the exam is JUDGED against the same text it was AUTHORED from.

    #1032 threaded the enriched planning seed into the job-oracle author, but the QA gate's
    grounding corpus still read ``spec.goal`` — the CLEAN goal, which by design never
    carries the operator's answers. So the invented-return scanner convicted the oracle for
    asserting exactly the value the operator asked for, and the single-focus regeneration
    would then STRIP it — a partial undo of #1032 on the narrow path.

    Drives the REAL ``generate_plan`` and reads the QA evidence that rides the REAL compiled
    task, so the assertion is on what a live dispatch would actually carry.
    """
    proj, repo = _repo(tmp_path)
    calls: list = []
    req = clr.compose_requirements_block([
        {"question": "confirm each entry?", "answer": _OPERATOR_ANSWER, "assumed": False},
    ])
    plan = generate_plan("a todo app", repo,
                         generate_fn=_gen_multitask(calls, oracle=_GROUNDED_ORACLE),
                         projects_dir=proj, clarify=True, requirements=req)

    # Vacuity guards: the author ran, and it really did see the operator's words.
    job_prompts = [p for p in calls if _MARKER_JOB_ORACLE in p]
    assert len(job_prompts) == 1, f"job-oracle author not reached ({len(job_prompts)})"
    assert _OPERATOR_ANSWER in job_prompts[0]

    qa = json.loads(
        next(t[acc.JOB_ORACLE_QA_KEY] for t in plan.tasks if acc.JOB_ORACLE_QA_KEY in t)
    )
    assert qa["findings"][oq.CLASS_INVENTED_RETURN] == 0
    assert qa["verdict"] == "seed"
    assert qa["regeneration"]["rounds"] == 0   # nothing to "fix" → no wasted GPU round

    # TOGGLE OFF, in-test: the SAME oracle judged against the PRE-FIX corpus (the spec
    # alone — and note spec.clarifications is EMPTY at plan time, which is why grounding on
    # that field instead would have been wired into nothing) still fires. Without this arm
    # the assertions above could pass on an oracle that was never a trap.
    assert plan.spec.clarifications == ()
    pre_fix_corpus = oq._spec_corpus(plan.spec)
    assert "saved" not in pre_fix_corpus
    assert len(oq.scan_invented_return_contracts(_GROUNDED_ORACLE, pre_fix_corpus)) == 1

    # And the corpus the gate ACTUALLY used carries no house prose (review F1), so this
    # dispatch cannot excuse an oracle asserting our own header words back at us.
    live_corpus = oq._spec_corpus(
        plan.spec, clr.operator_answers_from_block(req))
    for word in ("person", "clarified", "requirements"):
        assert word not in live_corpus


def test_battery_override_skips_clarify(tmp_path):
    proj, repo = _repo(tmp_path)
    calls: list = []
    override = DecompositionOverride(tasks=[{"repo": repo, "task": "t1", "prompt": "do"}])
    plan = generate_plan("a todo app", repo, generate_fn=_gen(calls), projects_dir=proj,
                         clarify=True, decomposition_override=override)
    # A carded (battery/headless) dispatch is never clarified — the card IS the spec.
    assert plan.questions == [] and len(plan.tasks) >= 1
    assert not any(_MARKER_CLARIFY in p for p in calls)


# ---- grammar-first for the clarify emission -------------------------------


def test_clarify_grammar_first(tmp_path):
    proj, repo = _repo(tmp_path)
    free_calls: list = []

    def structured(prompt: str, schema_text: str) -> str:
        if _MARKER_CLARIFY in prompt:
            schema = json.loads(schema_text)
            assert set(schema["items"]["properties"]["axis"]["enum"]) == set(clr.CLARIFY_AXES)
            return _QUESTIONS_JSON
        return ""  # force free-text for the rest (irrelevant — we early-return)

    plan = generate_plan("a todo app", repo, generate_fn=_gen(free_calls),
                         projects_dir=proj, clarify=True, structured_generate_fn=structured)
    assert [q["axis"] for q in plan.questions] == ["surface", "persistence"]
    # the grammar served the clarify emission — the free-text clarify prompt never fired.
    assert not any(_MARKER_CLARIFY in p for p in free_calls)


# ---- the spec.clarifications record (additive key) ------------------------


def test_spec_clarifications_roundtrip_and_render():
    spec = AcceptanceSpec(
        goal="a todo app",
        clarifications=(
            {"question": "where?", "answer": "on my computer", "assumed": False},
            {"question": "look?", "answer": "a clean simple look", "assumed": True},
        ),
    )
    back = AcceptanceSpec.from_dict(spec.to_dict())
    assert back.clarifications == spec.clarifications
    preview = acc.render_criteria_preview(back, ecosystem="python")
    assert "what you told me" in preview.lower()          # the answered one
    assert "on my computer" in preview
    assert "asked me to decide" in preview.lower()        # the assumed one
    assert "a clean simple look" in preview


def test_spec_clarifications_absent_key_is_empty():
    # An older payload with no key reconstructs unchanged (backward-compatible).
    assert AcceptanceSpec.from_dict({"goal": "g"}).clarifications == ()


def test_coerce_clarifications_fail_closed():
    assert acc._coerce_clarifications("not a list") == ()
    # blank / vacuous answers dropped; a real one survives with assumed coerced to bool.
    out = acc._coerce_clarifications([
        {"question": "q", "answer": "", "assumed": True},
        "junk",
        {"question": "q2", "answer": "on my computer", "assumed": 1},
    ])
    assert out == ({"question": "q2", "answer": "on my computer", "assumed": True},)


# ---------------------------------------------------------------------------
# Lesson 156, third instance (#1032) — the structural control.
#
# 156 is "when a value becomes config-driven, audit every consumer — a
# half-promoted config is worse than a hardcoded one." #1032 is its third
# expression: ``planning_seed`` (goal + clarified requirements) threads to eight
# sub-generation sites inside ``generate_plan`` and ONE of them — the multi-task
# job-oracle author — kept receiving the bare ``goal``. It survived for months
# because the missing site still produced plausible output: the requirements
# reached the exam indirectly through derived criteria, so the channel was leaky
# rather than severed, and nothing was ever visibly wrong.
#
# The two #1032 locks assert the FIXED site. Neither can see the NEXT site added
# to this function, which is the recurrence 156 keeps having. This test closes
# that: it reads the real source with the ``ast`` module and enumerates every
# call after the seed is minted that consumes the bare ``goal``.
#
# DENY-BY-DEFAULT: the allowlist below is the complete set of legitimate
# bare-``goal`` consumers. A new call site receiving ``goal`` after the mint
# fails HERE until someone justifies it in this list — the failure is the point.
# ---------------------------------------------------------------------------

# ``rule_spec`` builds the AcceptanceSpec, whose ``goal`` is deliberately the CLEAN
# goal: the operator's preview/report headers must never carry the requirements
# block. That is a contract stated at the mint site, not an oversight.
_LEGITIMATE_BARE_GOAL_CONSUMERS = {"rule_spec"}


def _generate_plan_ast():
    """Parse the real ``acceptance.py`` and return (generate_plan node, seed lineno)."""
    import ast
    import pathlib

    src = pathlib.Path(acc.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "generate_plan"
    )
    seed_line = None
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "planning_seed" for t in node.targets
        ):
            seed_line = node.lineno
    assert seed_line is not None, (
        "generate_plan no longer mints `planning_seed` — this control's premise is gone. "
        "If the seam was renamed, retarget this test; do not delete it (lesson 156)."
    )
    return fn, seed_line


def _bare_goal_consumers_after_seed():
    """Every call after the seed mint that passes the bare ``goal``, as {callee: [lines]}.

    Tracks simple LAUNDERING: a post-mint ``x = goal`` makes ``x`` an alias, and a call
    passing ``x`` counts as a bare-goal consumer. Without this, one intermediate assignment
    defeated the whole control — an independent reviewer demonstrated that
    ``x = goal; new_ninth_consumer(x)`` passed both locks, which is exactly the "ninth call
    site added tomorrow" case this control's docstring promises to catch.

    LIMITS, measured rather than assumed — an independent reviewer probed each of these
    against the shipped helper, and an earlier version of this docstring got two of them
    wrong, in both directions:

    * TRACKED: plain assignment (``x = goal``), annotated assignment (``x: str = goal``),
      multi-target (``p = q = goal``), and CHAINS (``a = goal; b = a; f(b)``). The chain
      case works because the alias set is grown to a fixed point, not one hop — an earlier
      docstring claimed one hop and under-claimed its own coverage.
    * NOT TRACKED: an attribute (``o.g = goal``), a container (``d['g'] = goal``), an
      f-string (``s = f'{goal}'``), a tuple unpack (``x, y = goal, other``), a walrus
      (``f(x := goal)``), and any alias assigned under a conditional branch.
    * NOT this control's job at all: a mis-COMPUTED seed (``planning_seed = goal``
      unconditionally). That is covered by the two pre-existing behavioural tests in this
      file, verified by mutation — the ast locks are blind to it by design.

    None of the untracked shapes is the observed failure mode: the real recurrence is
    someone adding a call site and passing the obviously-named variable in scope. But a
    named limit is a limit a successor can reason about; an unnamed one reads as coverage
    that does not exist, which is the exact defect this control guards against.
    """
    import ast
    from collections import defaultdict

    fn, seed_line = _generate_plan_ast()

    # Alias set grown to a FIXED POINT, so `a = goal; b = a` is tracked. Both plain and
    # annotated assignment count — `x: str = goal` was a demonstrated blind spot until an
    # independent reviewer probed for it.
    goal_aliases = {"goal"}
    changed = True
    while changed:
        changed = False
        for node in ast.walk(fn):
            if isinstance(node, ast.Assign):
                targets, value = node.targets, node.value
            elif isinstance(node, ast.AnnAssign):
                targets, value = ([node.target] if node.target else []), node.value
            else:
                continue
            if getattr(node, "lineno", 0) <= seed_line:
                continue
            if not (isinstance(value, ast.Name) and value.id in goal_aliases):
                continue
            for tgt in targets:
                if isinstance(tgt, ast.Name) and tgt.id not in goal_aliases:
                    goal_aliases.add(tgt.id)
                    changed = True

    found = defaultdict(list)
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call) or node.lineno <= seed_line:
            continue
        takes_goal = any(
            isinstance(a, ast.Name) and a.id in goal_aliases for a in node.args
        ) or any(
            isinstance(k.value, ast.Name) and k.value.id in goal_aliases
            for k in node.keywords
        )
        if not takes_goal:
            continue
        func = node.func
        name = (
            func.id if isinstance(func, ast.Name)
            else func.attr if isinstance(func, ast.Attribute)
            else "<unknown>"
        )
        found[name].append(node.lineno)
    return dict(found)


def test_every_post_seed_consumer_takes_the_planning_seed_not_the_bare_goal():
    """No sub-generation inside generate_plan may plan from the bare goal (#1032, lesson 156).

    This is the enumerating control, not a spot-check: it re-derives the consumer set from
    the source on every run, so a NINTH call site added tomorrow is caught the day it lands
    rather than the month someone notices the exam and the coder got different papers.
    """
    offenders = {
        name: lines
        for name, lines in _bare_goal_consumers_after_seed().items()
        if name not in _LEGITIMATE_BARE_GOAL_CONSUMERS
    }
    assert not offenders, (
        "These generate_plan call sites consume the bare `goal` after `planning_seed` is "
        f"minted: {offenders}. Every sub-generation must plan from `planning_seed` so the "
        "coder and the exam are built from the SAME text (#1032). If a new site genuinely "
        "needs the clean goal, add it to _LEGITIMATE_BARE_GOAL_CONSUMERS with the reason."
    )


def test_the_job_oracle_author_is_reached_by_the_seed_not_the_goal():
    """The #1032 site specifically — the one that was wrong — is pinned by name.

    The enumerating test above would pass if `author_and_qa_job_oracle` stopped being
    called at all. This one proves the seed actually reaches it, so the pair distinguishes
    "no offender" from "no consumer."
    """
    import ast

    fn, seed_line = _generate_plan_ast()
    seed_fed = {
        (node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", ""))
        for node in ast.walk(fn)
        if isinstance(node, ast.Call) and node.lineno > seed_line
        and (
            any(isinstance(a, ast.Name) and a.id == "planning_seed" for a in node.args)
            or any(
                isinstance(k.value, ast.Name) and k.value.id == "planning_seed"
                for k in node.keywords
            )
        )
    }
    for required in ("author_and_qa_job_oracle", "generate_acceptance_oracle", "decompose_request"):
        assert required in seed_fed, (
            f"`{required}` no longer receives `planning_seed` inside generate_plan — this is "
            "the #1032 defect returning (the exam authored blind to the operator's answers)."
        )


def _grounding_binding(enclosing: str, callee: str, source: str | None = None) -> "str | None":
    """What ``operator_answers=`` is bound to on the *callee* call inside *enclosing*,
    classified:

      * ``None``        — the argument is absent (grounding silently narrowed);
      * ``name:<id>``   — bound to a bare name;
      * ``call:<fn>``   — bound to a call, e.g. the answers extractor;
      * ``other``       — anything else.

    Raises if the call is gone entirely, so a vanished subject can never read as a pass.
    """
    import ast
    from pathlib import Path

    src = source if source is not None else Path(acc.__file__).read_text(encoding="utf-8")
    fn = next(
        (n for n in ast.walk(ast.parse(src))
         if isinstance(n, ast.FunctionDef) and n.name == enclosing),
        None,
    )
    assert fn is not None, f"{enclosing} is gone — this control's premise is."
    for node in ast.walk(fn):
        name = getattr(node, "func", None)
        if not isinstance(node, ast.Call) or (
            getattr(name, "attr", None) or getattr(name, "id", None)
        ) != callee:
            continue
        for k in node.keywords:
            if k.arg != "operator_answers":
                continue
            if isinstance(k.value, ast.Name):
                return f"name:{k.value.id}"
            if isinstance(k.value, ast.Call):
                return "call:" + str(
                    getattr(k.value.func, "attr", None) or getattr(k.value.func, "id", "?")
                )
            return "other"
        return None
    raise AssertionError(f"{enclosing} no longer calls {callee} — this control's subject is gone.")


def test_the_qa_gate_grounds_on_operator_answers_not_the_rendered_seed():
    """#1043's structural control, pinning the REVIEW-CORRECTED shape across BOTH links.

    Two distinct regressions must fail here:
      * dropping the argument — grounding narrows back to the clean goal, the original
        #1043 defect (the oracle convicted for asserting what the operator asked for);
      * binding it to ``goal``/``planning_seed`` at the plan site — that is the RENDERED
        requirements block, whose house header would ground the judge on
        "person"/"build"/"requirements", words no operator uttered (review F1).

    Checking only the inner link would miss the poisoning entirely, since
    ``author_and_qa_job_oracle`` merely forwards its own parameter — the source of the
    value is chosen one level up. The parameter stays optional (``()`` is correct for
    callers with no operator input), so the guarantee is structural, not a required arg.
    """
    # Link 1 — generate_plan derives the answers from the block, never passing the seed.
    assert _grounding_binding("generate_plan", "author_and_qa_job_oracle") == (
        "call:operator_answers_from_block"
    ), (
        "generate_plan no longer derives the grounding answers from the requirements block. "
        "If this now binds `planning_seed`/`goal`, the judge is grounded on our own house "
        "boilerplate and will excuse an oracle asserting it back at us (#1043 review F1)."
    )
    # Link 2 — the gate call actually forwards it.
    assert _grounding_binding("author_and_qa_job_oracle", "validate_authored_oracle") == (
        "name:operator_answers"
    ), "author_and_qa_job_oracle no longer forwards operator_answers to the QA gate (#1043)."


def test_the_grounding_control_can_see_planted_violations():
    """Toggle-off: the SHIPPED helper must fire on every regression shape it claims to
    catch. Drives the real helper against synthetic source rather than re-implementing its
    walk (lesson 3 aimed at a test's own subject)."""
    head = "def generate_plan(goal):\n    planning_seed = goal + req\n"
    call = "    a = author_and_qa_job_oracle(planning_seed, spec, tasks{})\n"

    # Argument dropped entirely — the original #1043 defect.
    assert _grounding_binding("generate_plan", "author_and_qa_job_oracle",
                             head + call.format("")) is None
    # Bound to the rendered seed — the review-F1 boilerplate-poisoning shape, verbatim.
    assert _grounding_binding("generate_plan", "author_and_qa_job_oracle",
                             head + call.format(", operator_answers=planning_seed")
                             ) == "name:planning_seed"
    assert _grounding_binding("generate_plan", "author_and_qa_job_oracle",
                             head + call.format(", operator_answers=goal")) == "name:goal"
    # The correct shape is recognised as such — else every arm above is vacuous.
    assert _grounding_binding(
        "generate_plan", "author_and_qa_job_oracle",
        head + call.format(", operator_answers=_clarify.operator_answers_from_block(req)")
    ) == "call:operator_answers_from_block"


def test_the_control_can_see_a_planted_violation(tmp_path, monkeypatch):
    """Toggle-off proof: the SHIPPED enumerator must fire on a planted bare-goal site.

    Lesson 1050, folded the same day: a control's first green run is not evidence it works.

    This drives the REAL helper rather than re-implementing its walk. An earlier version of
    this test rebuilt the ast logic inline over a planted source and asserted on that — which
    proves *a* detector fires, not that *the shipped* detector does, and lets the two drift
    apart while the toggle-off stays green. That is the mock-shape-divergence pattern (lesson
    3) aimed at a test's own subject, caught by an independent reviewer. The honest version
    points the helper's source at a synthetic module and asserts on its real output.
    """
    planted = tmp_path / "planted_acceptance.py"
    planted.write_text(
        "def generate_plan(goal):\n"
        "    planning_seed = goal + extra\n"
        "    a = decompose_request(planning_seed)\n"
        "    b = author_and_qa_job_oracle(goal)\n"      # the #1032 defect, verbatim shape
        "    laundered = goal\n"
        "    c = new_ninth_consumer(laundered)\n"       # reviewer's laundering case
        "    annotated: str = goal\n"
        "    d = tenth_consumer(annotated)\n"           # reviewer's AnnAssign blind spot
        "    chained = laundered\n"
        "    e = eleventh_consumer(chained)\n",         # two-hop chain
        encoding="utf-8",
    )
    monkeypatch.setattr(acc, "__file__", str(planted))

    offenders = _bare_goal_consumers_after_seed()

    assert "author_and_qa_job_oracle" in offenders, (
        "The SHIPPED enumerator did not see a planted bare-goal consumer — it would not have "
        "caught #1032 either, and every green run of this control is meaningless."
    )
    assert "new_ninth_consumer" in offenders, (
        "The shipped enumerator missed a goal laundered through one intermediate local "
        "(`x = goal; f(x)`). That is the ninth-call-site case this control exists to catch."
    )
    assert "tenth_consumer" in offenders, (
        "The shipped enumerator missed an ANNOTATED assignment (`x: str = goal; f(x)`) — a "
        "blind spot an independent reviewer demonstrated, and one a reader would reasonably "
        "assume covered because plain assignment is."
    )
    assert "eleventh_consumer" in offenders, (
        "The shipped enumerator missed a two-hop chain (`a = goal; b = a; f(b)`) — the alias "
        "set must be grown to a fixed point, not one hop."
    )
    # The honest form must NOT be flagged: a gate that refuses correct work teaches the next
    # author to route around it, and a gate people route around is worse than no gate.
    assert "decompose_request" not in offenders


def test_the_enumerator_does_not_flag_a_clean_function(tmp_path, monkeypatch):
    """Negative control: where every consumer takes the seed, the offender set is empty.

    Without this, the planted-violation test passing is compatible with an enumerator that
    flags everything unconditionally — the defect that makes a control look alive while
    measuring nothing.
    """
    clean = tmp_path / "clean_acceptance.py"
    clean.write_text(
        "def generate_plan(goal):\n"
        "    planning_seed = goal + extra\n"
        "    a = decompose_request(planning_seed)\n"
        "    b = author_and_qa_job_oracle(planning_seed)\n"
        "    spec = rule_spec(goal)\n",                 # the one allowlisted clean-goal use
        encoding="utf-8",
    )
    monkeypatch.setattr(acc, "__file__", str(clean))

    offenders = {
        name: lines
        for name, lines in _bare_goal_consumers_after_seed().items()
        if name not in _LEGITIMATE_BARE_GOAL_CONSUMERS
    }
    assert not offenders, f"enumerator flagged a clean function: {offenders}"
