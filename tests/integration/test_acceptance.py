"""Tests for the Acceptance Layer (increment 3a) — the pure spec/ruler/report core.

The model is injected (``generate_fn``), so the whole layer is exercised without a GPU.
The load-bearing tests are the anti-rubber-stamp ones: an objective check that never ran
is UNVERIFIED, NEVER a pass (the .NET / pytest-absent false-pass this layer prevents).
"""

from __future__ import annotations

import json

import pytest

from shared.fleet import acceptance as acc
from shared.fleet.acceptance import (
    AcceptanceCriterion,
    AcceptanceSpec,
    TaskReport,
)


# ---- fixtures -------------------------------------------------------------


def _git_repo(projects_dir, name="myapp"):
    (projects_dir / name / ".git").mkdir(parents=True)
    return name


def _fake_model(
    *,
    tasks_json: str,
    criteria_json: str,
    assumptions_json: str = "[]",
    build_plan_json: str = "",
    oracle_py: str = "",
    oracle_node: str = "",
    asset_specs_json: str = "[]",
):
    """A generate_fn that answers the decompose / criteria / assumptions / build-plan / oracle /
    asset-spec prompts.

    The PLAN step makes up to SIX model calls (decompose, criteria, product assumptions,
    build-signal, acceptance-test oracle, image-asset specs); this routes each by a phrase unique
    to its prompt. ``assumptions_json`` defaults to ``"[]"`` (no assumptions — the fully-specified-goal
    posture). ``build_plan_json`` defaults to ``""`` so a test that does not care about the
    build-signal gets none parseable -> ``build_plan is None`` (the no-signal == today's
    behavior). ``oracle_py``/``oracle_node`` default to ``""`` so a test that does not exercise the
    #690/#697 oracle gets none (the model returns no code -> the oracle is '' -> today's
    fold-the-tests-in path); the python oracle prompt says "pytest test file" and the node one
    "node:test", so the two route apart. ``asset_specs_json`` defaults to ``"[]"`` (no image assets
    — and the asset call fires ONLY for a visual surface, so a test with no/non-visual build_plan
    never reaches it -> SEAM A dormant).
    """

    def gen(prompt: str) -> str:
        if "ACCEPTANCE CRITERIA" in prompt:
            return criteria_json
        if "PRODUCT assumptions" in prompt:
            return assumptions_json
        if "Classify what KIND of software" in prompt:
            return build_plan_json
        if "pytest test file" in prompt:
            return oracle_py
        if "node:test" in prompt:
            return oracle_node
        if "image assets this product should DISPLAY" in prompt:
            return asset_specs_json
        return tasks_json

    return gen


#: A small, valid pytest oracle the fake model can emit (ast-parses + defines test functions).
#: No trailing newline — :func:`_extract_python_code` strips surrounding whitespace, so the
#: round-trip is exact (the strip normalizes a model's optional trailing newline).
_ORACLE_PY = (
    "from calendar_math import add_days\n"
    "\n\n"
    "def test_leap_day_crossing():\n"
    "    assert add_days(2024, 2, 28, 1) == (2024, 3, 1)\n"
    "\n\n"
    "def test_year_boundary():\n"
    "    assert add_days(2023, 12, 31, 1) == (2024, 1, 1)"
)

#: A python build-signal (surface=command-line, language_hint=python) so the #690 oracle fires.
_PY_BUILD_PLAN = json.dumps(
    {"surface": "command-line", "candidates": [], "language_hint": "python",
     "complexity": "simple", "components": []}
)

#: A small, valid node:test oracle the fake model can emit (#697): the node_oracle_valid shape
#: check needs a ``node:test`` import + at least one ``test(``/``it(`` block, and the coder's
#: import contract is surfaced from the ``../src`` import. No trailing newline (the JS extractor
#: strips surrounding whitespace, so the round-trip is exact).
_ORACLE_NODE = (
    "import test from 'node:test';\n"
    "import assert from 'node:assert';\n"
    "import { addDays } from '../src/calendar.mjs';\n"
    "\n"
    "test('leap day crossing', () => {\n"
    "  assert.deepStrictEqual(addDays(2024, 2, 28, 1), [2024, 3, 1]);\n"
    "});\n"
    "\n"
    "test('year boundary', () => {\n"
    "  assert.deepStrictEqual(addDays(2023, 12, 31, 1), [2024, 1, 1]);\n"
    "});"
)

#: A node build-signal (surface=web, language_hint=node) so the #697 per-task oracle fires.
_NODE_BUILD_PLAN = json.dumps(
    {"surface": "web", "candidates": [], "language_hint": "node",
     "complexity": "simple", "components": []}
)


# ---- dataclasses + serialization -----------------------------------------


def test_criterion_roundtrip():
    c = AcceptanceCriterion(id="c1", text="2 + 3 shows 5", tier="behavior", check="assert add(2,3)==5")
    assert AcceptanceCriterion.from_dict(c.to_dict()) == c


def test_spec_roundtrip_and_filters():
    spec = AcceptanceSpec(
        goal="a calculator",
        criteria=(
            AcceptanceCriterion("c1", "it builds", "build", ""),
            AcceptanceCriterion("c2", "2 + 3 shows 5", "behavior", ""),
            AcceptanceCriterion("c3", "big friendly buttons", "visual", ""),
        ),
    )
    restored = AcceptanceSpec.from_dict(spec.to_dict())
    assert restored == spec
    assert {c.id for c in spec.objective} == {"c1", "c2"}
    assert {c.id for c in spec.human} == {"c3"}


def test_spec_roundtrips_assumptions():
    # The product assumptions ride the spec across to_dict/from_dict (so they cross the
    # gateway IPC, which reconstructs the spec via from_dict, with no transport change).
    spec = AcceptanceSpec(
        goal="a calculator",
        criteria=(AcceptanceCriterion("c1", "it builds", "build", ""),),
        assumptions=("Assumed decimals are supported", "Assumed no calculation history"),
    )
    d = spec.to_dict()
    assert d["assumptions"] == [
        "Assumed decimals are supported",
        "Assumed no calculation history",
    ]
    restored = AcceptanceSpec.from_dict(d)
    assert restored == spec
    assert restored.assumptions == (
        "Assumed decimals are supported",
        "Assumed no calculation history",
    )


def test_spec_from_dict_without_assumptions_defaults_empty():
    # Backward-compat: an older wire payload / hand-built dict with NO assumptions key
    # reconstructs with an empty assumptions tuple (never raises, never None).
    restored = AcceptanceSpec.from_dict(
        {"goal": "g", "criteria": [{"id": "c1", "text": "it builds", "tier": "build", "check": ""}]}
    )
    assert restored.assumptions == ()


def test_spec_from_dict_assumptions_drops_blank_and_non_str():
    # Defensive reconstruction: blanks and non-string items are dropped, survivors stripped.
    restored = AcceptanceSpec.from_dict(
        {"goal": "g", "criteria": [], "assumptions": ["  Assumed decimals  ", "", "   ", 42, None]}
    )
    assert restored.assumptions == ("Assumed decimals",)


# ---- _parse_criteria ------------------------------------------------------


def test_parse_criteria_plain_array():
    raw = json.dumps([{"text": "it builds", "tier": "BUILD", "check": "compiles"}])
    got = acc._parse_criteria(raw, max_criteria=8)
    assert got == [{"text": "it builds", "tier": "build", "check": "compiles"}]  # tier lowercased


def test_parse_criteria_extracts_from_prose():
    raw = "Sure! Here you go:\n```json\n[{\"text\": \"it launches\", \"tier\": \"smoke\"}]\n```\n"
    got = acc._parse_criteria(raw, max_criteria=8)
    assert got == [{"text": "it launches", "tier": "smoke", "check": ""}]


def test_parse_criteria_garbage_is_empty():
    assert acc._parse_criteria("not json at all", max_criteria=8) == []
    assert acc._parse_criteria("", max_criteria=8) == []
    assert acc._parse_criteria('{"text": "obj not array"}', max_criteria=8) == []


# ---- _parse_assumptions ---------------------------------------------------


def test_parse_assumptions_plain_array():
    raw = json.dumps(["Assumed decimals are supported", "Assumed a resizable window"])
    got = acc._parse_assumptions(raw, max_assumptions=4)
    assert got == ("Assumed decimals are supported", "Assumed a resizable window")


def test_parse_assumptions_extracts_from_prose_and_fences():
    raw = 'Here are my assumptions:\n```json\n["Assumed no login is required"]\n```\n'
    assert acc._parse_assumptions(raw, max_assumptions=4) == ("Assumed no login is required",)


def test_parse_assumptions_empty_array_is_empty_tuple():
    # The fully-specified-goal case: the model returns [] -> no assumptions -> no section.
    assert acc._parse_assumptions("[]", max_assumptions=4) == ()


def test_parse_assumptions_garbage_is_empty():
    assert acc._parse_assumptions("not json at all", max_assumptions=4) == ()
    assert acc._parse_assumptions("", max_assumptions=4) == ()
    assert acc._parse_assumptions('{"a": "object not array"}', max_assumptions=4) == ()


def test_parse_assumptions_drops_blanks_non_str_and_dedupes():
    raw = json.dumps([
        "Assumed decimals are supported",
        "ok",                               # too short -> drop
        "",                                 # blank -> drop
        {"text": "an object"},              # non-str -> drop
        "Assumed   decimals   are SUPPORTED",  # dup after normalize -> drop
    ])
    assert acc._parse_assumptions(raw, max_assumptions=4) == ("Assumed decimals are supported",)


def test_parse_assumptions_caps_at_max():
    raw = json.dumps([f"Assumed product behaviour number {i}" for i in range(10)])
    got = acc._parse_assumptions(raw, max_assumptions=3)
    assert len(got) == 3
    assert got[0] == "Assumed product behaviour number 0"


# ---- rule_spec (the deterministic disposal) -------------------------------


def test_rule_spec_keeps_valid_and_assigns_contiguous_ids():
    cands = [
        {"text": "the project builds", "tier": "build", "check": ""},
        {"text": "2 + 3 shows 5", "tier": "behavior", "check": "assert add(2,3)==5"},
        {"text": "big friendly buttons", "tier": "visual", "check": ""},
    ]
    spec = acc.rule_spec("a calc", cands)
    assert [c.id for c in spec.criteria] == ["c1", "c2", "c3"]
    assert spec.goal == "a calc"
    assert len(spec.objective) == 2  # build + behavior, no injection needed


def test_rule_spec_drops_vacuous_and_malformed():
    cands = [
        {"text": "ok", "tier": "behavior", "check": ""},          # too short -> drop
        {"text": "", "tier": "build", "check": ""},               # empty -> drop
        {"text": "valid behavior here", "tier": "nonsense", "check": ""},  # bad tier -> drop
        {"text": "2 + 3 shows 5", "tier": "behavior", "check": ""},  # kept
    ]
    spec = acc.rule_spec("g", cands)
    texts = [c.text for c in spec.criteria]
    assert "2 + 3 shows 5" in texts
    assert "ok" not in texts and "" not in texts and "valid behavior here" not in texts


def test_rule_spec_dedupes_by_normalized_text():
    cands = [
        {"text": "2 + 3 shows 5", "tier": "behavior", "check": ""},
        {"text": "2 + 3   SHOWS 5", "tier": "behavior", "check": ""},  # same after normalize -> drop
    ]
    spec = acc.rule_spec("g", cands)
    assert len([c for c in spec.criteria if "2 + 3" in c.text.lower()]) == 1


def test_rule_spec_caps_at_max_criteria():
    cands = [{"text": f"behavior number {i}", "tier": "behavior", "check": ""} for i in range(20)]
    spec = acc.rule_spec("g", cands, max_criteria=3)
    assert len(spec.criteria) == 3


def test_rule_spec_injects_build_floor_when_no_objective():
    # Only human/visual criteria survive -> a default BUILD criterion is injected so a
    # dispatch is never gated by nothing.
    cands = [
        {"text": "looks delightful", "tier": "visual", "check": ""},
        {"text": "fun for an 8-year-old", "tier": "human", "check": ""},
    ]
    spec = acc.rule_spec("g", cands)
    assert spec.criteria[0].tier == "build"            # injected at the front
    assert spec.criteria[0].id == "c1"                 # ids re-numbered after injection
    assert len(spec.objective) == 1


def test_rule_spec_empty_candidates_still_has_build_floor():
    spec = acc.rule_spec("g", [])
    assert len(spec.criteria) == 1 and spec.criteria[0].tier == "build"


# ---- compile_prompts ------------------------------------------------------


def test_compile_prompts_appends_one_dedicated_acceptance_task():
    # Behavior/smoke criteria route to ONE final task (NOT baked into every task), so
    # multi-task dispatches never write duplicate/conflicting test files across the
    # per-task auto-merges.
    tasks = [{"repo": "R", "task": "t1", "prompt": "do the thing"},
             {"repo": "R", "task": "t2", "prompt": "do another"}]
    spec = AcceptanceSpec("g", (
        AcceptanceCriterion("c1", "it builds", "build", ""),         # NOT a test task
        AcceptanceCriterion("c2", "2 + 3 shows 5", "behavior", "assert add(2,3)==5"),
        AcceptanceCriterion("c3", "it launches", "smoke", ""),
        AcceptanceCriterion("c4", "pretty", "visual", ""),          # never sent to the coder
    ))
    out = acc.compile_prompts(tasks, spec)
    assert len(out) == 3                                   # 2 feature + 1 acceptance task
    # feature tasks unchanged
    assert out[0]["prompt"] == "do the thing" and out[1]["prompt"] == "do another"
    # the dedicated final task carries the behavior+smoke criteria, not build/visual
    final = out[-1]
    assert final["task"] == acc.ACCEPTANCE_TASK_SLUG and final["repo"] == "R"
    assert "2 + 3 shows 5" in final["prompt"] and "it launches" in final["prompt"]
    assert "[behavior]" in final["prompt"] and "[smoke]" in final["prompt"]
    assert "pretty" not in final["prompt"] and "it builds" not in final["prompt"]
    # Enhancement-1 (go-live hardening): the prompt tells the coder to assert the
    # criterion's REQUIRED behavior, not whatever the code currently does.
    assert "REQUIRED behavior" in final["prompt"]
    # inputs not mutated
    assert len(tasks) == 2 and tasks[0]["prompt"] == "do the thing"


def test_compile_prompts_threads_visual_criteria_and_goal_for_loop():
    """Every compiled task carries goal + visual_criteria_json (a JSON array of the visual-tier
    criterion texts) so the fleet's DORMANT VLM design loop CAN read them — without changing the
    bare {repo,task,prompt} queue schema (#666/#670 Phase 3). The visual tier is NEVER sent to
    the coder (it stays the operator's eyeball); these fields only feed the post-merge critique
    signal. Human-tier criteria are excluded (not screenshot-assessable)."""
    import json
    tasks = [{"repo": "R", "task": "t1", "prompt": "p1"},
             {"repo": "R", "task": "t2", "prompt": "p2"}]
    spec = AcceptanceSpec("a tidy calculator", (
        AcceptanceCriterion("c1", "2 + 3 shows 5", "behavior", ""),
        AcceptanceCriterion("c2", "clean, uncluttered layout", "visual", ""),
        AcceptanceCriterion("c3", "tasteful colours", "visual", ""),
        AcceptanceCriterion("c4", "the operator likes it", "human", ""),
    ))
    out = acc.compile_prompts(tasks, spec)
    assert len(out) == 3  # 2 feature + 1 dedicated acceptance task; ALL carry the loop fields
    for t in out:
        assert t["goal"] == "a tidy calculator"
        assert json.loads(t["visual_criteria_json"]) == [
            "clean, uncluttered layout", "tasteful colours",
        ]


def test_compile_prompts_no_visual_criteria_threads_empty_json():
    """No visual criteria -> visual_criteria_json is '[]' (the fleet then skips the critique)."""
    import json
    tasks = [{"repo": "R", "task": "only", "prompt": "p"}]
    spec = AcceptanceSpec("g", (AcceptanceCriterion("c1", "2 + 3 shows 5", "behavior", ""),))
    out = acc.compile_prompts(tasks, spec)
    assert json.loads(out[0]["visual_criteria_json"]) == []
    assert out[0]["goal"] == "g"


def test_compile_prompts_no_test_criteria_returns_tasks_unchanged():
    tasks = [{"repo": "R", "task": "t1", "prompt": "do the thing"}]
    spec = AcceptanceSpec("g", (AcceptanceCriterion("c1", "it builds", "build", ""),))
    out = acc.compile_prompts(tasks, spec)
    assert len(out) == 1 and out[0]["prompt"] == "do the thing"  # no acceptance task added
    assert out is not tasks  # still a fresh list


def test_compile_prompts_single_feature_folds_tests_in():
    # BEHAVIOR CHANGE (#670 Problem 3 — was test_compile_prompts_single_task_still_gets_
    # separate_acceptance_task): a single feature task no longer spawns a SEPARATE
    # acceptance-tests task (that spun a doomed second worktree without the impl in it) —
    # the test criteria FOLD into the one task's prompt.
    tasks = [{"repo": "R", "task": "only", "prompt": "build the calc"}]
    spec = AcceptanceSpec("g", (
        AcceptanceCriterion("c1", "2 + 3 shows 5", "behavior", "assert add(2,3)==5"),
        AcceptanceCriterion("c2", "it launches", "smoke", ""),
        AcceptanceCriterion("c3", "it builds", "build", ""),     # NOT a test tier
    ))
    out = acc.compile_prompts(tasks, spec)
    assert len(out) == 1                                          # ONE task, no separate test task
    assert out[0]["task"] == "only" and out[0]["repo"] == "R"
    assert not any(t["task"] == acc.ACCEPTANCE_TASK_SLUG for t in out)
    prompt = out[0]["prompt"]
    assert prompt.startswith("build the calc")                   # the feature instruction is kept
    assert "--- Acceptance tests ---" in prompt                  # a clearly-delimited section
    assert "2 + 3 shows 5" in prompt and "it launches" in prompt # behavior + smoke folded in
    assert "[behavior]" in prompt and "[smoke]" in prompt
    assert "it builds" not in prompt                             # build/visual never sent to coder
    # The anti-mirror header SURVIVES the fold (LA adjustment #2) — the coverage guard that
    # stops the coder writing happy-path tests mirroring its own fresh code.
    assert "REQUIRED behavior" in prompt
    assert len(tasks) == 1 and tasks[0]["prompt"] == "build the calc"  # inputs not mutated


def test_compile_prompts_multi_feature_keeps_dedicated_task():
    # >=2 feature tasks: the dedicated final acceptance-tests task is RETAINED (writes the
    # tests once, against the complete merged code — no duplicate test files across merges).
    tasks = [{"repo": "R", "task": "f1", "prompt": "p1"},
             {"repo": "R", "task": "f2", "prompt": "p2"}]
    spec = AcceptanceSpec("g", (AcceptanceCriterion("c1", "2 + 3 shows 5", "behavior", ""),))
    out = acc.compile_prompts(tasks, spec)
    assert len(out) == 3                                          # 2 feature + 1 dedicated test task
    assert out[0]["prompt"] == "p1" and out[1]["prompt"] == "p2"  # feature tasks unchanged
    assert out[-1]["task"] == acc.ACCEPTANCE_TASK_SLUG
    assert "2 + 3 shows 5" in out[-1]["prompt"] and "REQUIRED behavior" in out[-1]["prompt"]


def test_compile_prompts_requests_property_based_tests():
    # #687 (task 4) spec-blind: the test prompt asks for Hypothesis PROPERTY-BASED tests of a
    # criterion's invariant -- a property is derived from the SPEC, so it cannot mirror the coder's
    # own fresh implementation (the 2409.09464 happy-path-self-test risk) and it finds edge cases an
    # example test misses. The anti-mirror header is preserved alongside it.
    tasks = [{"repo": "R", "task": "only", "prompt": "build the calc"}]
    spec = AcceptanceSpec("g", (AcceptanceCriterion("c1", "2 + 3 shows 5", "behavior", ""),))
    prompt = acc.compile_prompts(tasks, spec)[0]["prompt"]
    assert "REQUIRED behavior" in prompt                          # anti-mirror still present
    assert "property-based" in prompt.lower() and "hypothesis" in prompt.lower()
    assert "from hypothesis import given" in prompt               # concrete, copy-pasteable guidance


def test_compile_prompts_skips_test_block_for_buildonly_dotnet():
    # #687 #8: a build-only ecosystem (.NET) has no offline test runner, so the "write automated
    # tests" instruction is OMITTED -- mandating tests there made the C# coder spawn a test project
    # that broke the bare `dotnet build` gate (the review-probe park). Build + review are the gate.
    tasks = [{"repo": "R", "task": "only", "prompt": "build the C# app"}]
    spec = AcceptanceSpec(
        goal="a C# console app",
        criteria=(AcceptanceCriterion("c1", "prints 20 fibonacci numbers", "behavior", ""),),
        build_plan={"surface": "cli", "language_hint": "dotnet", "complexity": "simple", "components": []},
    )
    out = acc.compile_prompts(tasks, spec)
    assert len(out) == 1
    assert out[0]["prompt"] == "build the C# app"                  # unchanged -- no test block folded in
    assert "--- Acceptance tests ---" not in out[0]["prompt"]
    assert "hypothesis" not in out[0]["prompt"].lower()


def test_compile_prompts_keeps_test_block_for_node():
    # node IS behavior-gated (its tests RUN in the gate) -> the test block IS added. The gate is
    # behavior-gated, not python-only (a mutant that gates to python-only would flip this).
    tasks = [{"repo": "R", "task": "only", "prompt": "build the web app"}]
    spec = AcceptanceSpec(
        goal="a web app",
        criteria=(AcceptanceCriterion("c1", "the API returns 200", "behavior", ""),),
        build_plan={"surface": "web", "language_hint": "node", "complexity": "simple", "components": []},
    )
    prompt = acc.compile_prompts(tasks, spec)[0]["prompt"]
    assert "--- Acceptance tests ---" in prompt and "the API returns 200" in prompt


def test_compile_prompts_keeps_test_block_for_unknown_language():
    # An UNKNOWN language (language_hint None) keeps the python/node default -> backward-compatible
    # (a mutant that skips the block for None would flip this and silently drop tests everywhere).
    tasks = [{"repo": "R", "task": "only", "prompt": "build it"}]
    spec = AcceptanceSpec(
        goal="build it",
        criteria=(AcceptanceCriterion("c1", "2 + 3 shows 5", "behavior", ""),),
        build_plan={"surface": "cli", "language_hint": None, "complexity": "simple", "components": []},
    )
    prompt = acc.compile_prompts(tasks, spec)[0]["prompt"]
    assert "--- Acceptance tests ---" in prompt


# ---- compile_prompts + the #690 shared oracle -----------------------------


def test_compile_prompts_with_oracle_codes_against_seeded_file():
    # #690: when an oracle is supplied (python single feature), the coder is told to CODE
    # AGAINST the seeded, protected file -- NOT to write its own tests -- and the task carries
    # the oracle code + path so the fleet can seed + restore it for every best-of-N candidate.
    tasks = [{"repo": "R", "task": "only", "prompt": "build add_days"}]
    spec = AcceptanceSpec(
        goal="calendar math",
        criteria=(AcceptanceCriterion("c1", "Feb 28 + 1 day is Mar 1 in 2024", "behavior", ""),),
        build_plan={"surface": "command-line", "language_hint": "python",
                    "complexity": "simple", "components": []},
    )
    out = acc.compile_prompts(tasks, spec, oracle_code=_ORACLE_PY)
    assert len(out) == 1                                               # single feature, no extra task
    prompt = out[0]["prompt"]
    assert prompt.startswith("build add_days")                        # feature instruction kept
    assert "DO NOT EDIT" in prompt and acc.ACCEPTANCE_ORACLE_PATH in prompt
    # the coder is pointed at the seeded oracle, NOT told to write its own tests
    assert "Write automated tests" not in prompt
    # the oracle rides the task so the fleet can seed it into every candidate + restore it
    assert out[0]["acceptance_test_code"] == _ORACLE_PY
    assert out[0]["acceptance_test_path"] == acc.ACCEPTANCE_ORACLE_PATH


def test_compile_prompts_python_contract_asserts_neutral_seed_not_core():
    # #1036/#1048 companion: the seeded python skeleton is NEUTRAL — app/__init__.py plus
    # smoke tests; app/core.py no longer exists. Neither the coder contract line nor the
    # oracle-authoring template may assert the retired starter module as a live premise (a
    # prompt premised on a file that is not on disk misdirects the coder AND the oracle).
    oracle = (
        "from app.days import add_days\n"
        "\n\n"
        "def test_leap_day_crossing():\n"
        "    assert add_days(2024, 2, 28, 1) == (2024, 3, 1)"
    )
    tasks = [{"repo": "R", "task": "only", "prompt": "build add_days"}]
    spec = AcceptanceSpec(
        goal="calendar math",
        criteria=(AcceptanceCriterion("c1", "Feb 28 + 1 day is Mar 1 in 2024", "behavior", ""),),
        build_plan={"surface": "command-line", "language_hint": "python",
                    "complexity": "simple", "components": []},
    )
    out = acc.compile_prompts(tasks, spec, oracle_code=oracle)
    prompt = out[0]["prompt"]
    # the all-under-app contract branch DID fire (this is the string under test) ...
    assert "`app.days.add_days`" in prompt and "EXISTING `app` package" in prompt
    # ... and it states the truthful premise: the coder AUTHORS app/<name>.py submodules.
    assert "`app/<name>.py` submodule" in prompt and "no starter module" in prompt.replace("\n", " ")
    # [kill] the retired starter module is never asserted as a live premise — not by the
    # contract line, and not by the oracle-authoring template.
    assert "app/core.py" not in prompt and "app.core" not in prompt
    assert "app.core" not in acc._ORACLE_TEMPLATE and "app/core.py" not in acc._ORACLE_TEMPLATE


def test_compile_prompts_node_oracle_codes_against_seeded_mjs():
    # #697: a NODE single feature + an oracle -> the coder codes against the seeded .mjs file (NOT
    # its own tests), the task carries the node code + the .mjs path, and the concrete ../src
    # import is surfaced as the module contract (the node mirror of the #752 F3 plumbing loop).
    tasks = [{"repo": "R", "task": "only", "prompt": "build addDays"}]
    spec = AcceptanceSpec(
        goal="calendar math",
        criteria=(AcceptanceCriterion("c1", "Feb 28 + 1 day is Mar 1 in 2024", "behavior", ""),),
        build_plan={"surface": "web", "language_hint": "node",
                    "complexity": "simple", "components": []},
    )
    out = acc.compile_prompts(tasks, spec, oracle_code=_ORACLE_NODE)
    assert len(out) == 1                                               # single feature, no extra task
    prompt = out[0]["prompt"]
    assert prompt.startswith("build addDays")                         # feature instruction kept
    assert "DO NOT EDIT" in prompt and acc.ACCEPTANCE_ORACLE_PATH_NODE in prompt
    assert "node --test" in prompt                                    # node runner, not pytest
    assert "../src/calendar.mjs" in prompt                            # import contract surfaced
    assert "Write automated tests" not in prompt                     # codes against the oracle
    # the oracle rides the task at the .mjs path so the fleet seeds/restores it per candidate
    assert out[0]["acceptance_test_code"] == _ORACLE_NODE
    assert out[0]["acceptance_test_path"] == acc.ACCEPTANCE_ORACLE_PATH_NODE
    # #697 guard: the python pytest path is NEVER stamped on a node task (a mutant seeding the .py
    # path would make the fleet run the .mjs oracle under pytest and always fail on collection).
    assert out[0]["acceptance_test_path"] != acc.ACCEPTANCE_ORACLE_PATH


def test_compile_prompts_without_oracle_has_no_oracle_fields():
    # [kill] absent oracle -> today's fold-the-tests-in behavior, and NO acceptance_test_* keys
    # leak onto the task (a mutant that always-stamps them would ship an empty oracle to seed).
    tasks = [{"repo": "R", "task": "only", "prompt": "build the calc"}]
    spec = AcceptanceSpec("g", (AcceptanceCriterion("c1", "2 + 3 shows 5", "behavior", ""),))
    out = acc.compile_prompts(tasks, spec)                            # oracle_code="" (default)
    assert "Write automated tests" in out[0]["prompt"]               # today's behavior
    assert "acceptance_test_code" not in out[0]
    assert "acceptance_test_path" not in out[0]


def test_compile_prompts_oracle_ignored_for_multi_feature():
    # [kill] the oracle is the SINGLE-feature MVP. With >=2 feature tasks the dedicated
    # acceptance-tests task is retained and the oracle is NOT stamped (a mutant that stamped it
    # onto a multi-feature plan would seed one file the per-task merges then fight over).
    tasks = [{"repo": "R", "task": "f1", "prompt": "p1"},
             {"repo": "R", "task": "f2", "prompt": "p2"}]
    spec = AcceptanceSpec(
        goal="g",
        criteria=(AcceptanceCriterion("c1", "2 + 3 shows 5", "behavior", ""),),
        build_plan={"surface": "command-line", "language_hint": "python",
                    "complexity": "moderate", "components": []},
    )
    out = acc.compile_prompts(tasks, spec, oracle_code=_ORACLE_PY)
    assert len(out) == 3 and out[-1]["task"] == acc.ACCEPTANCE_TASK_SLUG  # dedicated task kept
    assert all("acceptance_test_code" not in t for t in out)             # oracle not stamped


# ---- generate_acceptance_oracle (the 14B writes the spec-blind scorecard) --


def test_generate_acceptance_oracle_python_happy():
    spec = AcceptanceSpec(
        goal="calendar math",
        criteria=(AcceptanceCriterion("c1", "Feb 28 + 1 is Mar 1 in 2024", "behavior", ""),),
        build_plan={"surface": "command-line", "language_hint": "python",
                    "complexity": "simple", "components": []},
    )
    tasks = [{"repo": "R", "task": "only", "prompt": "build add_days"}]
    gen = (lambda p: _ORACLE_PY)
    code = acc.generate_acceptance_oracle("calendar math", spec, tasks, generate_fn=gen)
    assert code == _ORACLE_PY
    import ast as _ast
    _ast.parse(code)                                                  # it is valid python


def test_generate_acceptance_oracle_strips_markdown_fences():
    # A small model often wraps code in ```python fences despite the instruction; we strip them.
    spec = AcceptanceSpec(
        goal="g", criteria=(AcceptanceCriterion("c1", "x is y", "behavior", ""),),
        build_plan={"surface": "library", "language_hint": "python",
                    "complexity": "simple", "components": []},
    )
    fenced = "Here you go:\n```python\n" + _ORACLE_PY + "```\n"
    code = acc.generate_acceptance_oracle("g", spec, [{"prompt": "p"}], generate_fn=lambda p: fenced)
    assert code.startswith("from calendar_math import add_days")
    assert "```" not in code and "Here you go" not in code


def test_generate_acceptance_oracle_handles_UNCLOSED_fence():
    # REGRESSION (#690 live verify): the real 14B opened a ```python fence and never closed it
    # (small models omit the close, or the generation truncates). The closed-fence regex misses,
    # so the stray ```python line would reach ast.parse and reject a perfectly good oracle. The
    # opener must be stripped and the body kept.
    spec = AcceptanceSpec(
        goal="g", criteria=(AcceptanceCriterion("c1", "x is y", "behavior", ""),),
        build_plan={"surface": "library", "language_hint": "python",
                    "complexity": "simple", "components": []},
    )
    unclosed = "\n\n```python\n" + _ORACLE_PY + "\n"   # opening fence, NO closing ```
    code = acc.generate_acceptance_oracle("g", spec, [{"prompt": "p"}], generate_fn=lambda p: unclosed)
    assert code.startswith("from calendar_math import add_days")   # extracted despite no close
    assert "```" not in code                                       # the stray opener is gone
    import ast as _ast
    _ast.parse(code)                                               # and it is valid python now


def test_generate_acceptance_oracle_build_only_ecosystem_is_empty():
    # [kill] the per-task oracle fires only for a gate-RUN ecosystem (python pytest / node:test).
    # A build-only ecosystem (dotnet/cpp/powershell) returns '' (today's fold-the-tests-in
    # behavior), never seeds a test file a foreign gate cannot run. #697 adds node but must NOT
    # widen the door to a build-only hint (a mutant that returned an oracle here would flip this).
    for hint in ("dotnet", "cpp", "powershell"):
        spec = AcceptanceSpec(
            goal="g", criteria=(AcceptanceCriterion("c1", "x is y", "behavior", ""),),
            build_plan={"surface": "desktop-gui", "language_hint": hint,
                        "complexity": "simple", "components": []},
        )
        assert acc.generate_acceptance_oracle(
            "g", spec, [{"prompt": "p"}], generate_fn=lambda p: _ORACLE_PY
        ) == ""


def test_generate_acceptance_oracle_unclassified_non_web_is_empty():
    # [kill] an UNCLASSIFIED language (hint None) with a NON-web surface stays fail-closed to '' —
    # only a web surface (the node:http/node:test scaffold) routes a hintless goal to node (#697).
    # A command-line goal with no language hint gets NO oracle, byte-identical to pre-#697.
    spec = AcceptanceSpec(
        goal="g", criteria=(AcceptanceCriterion("c1", "x is y", "behavior", ""),),
        build_plan={"surface": "command-line", "language_hint": None,
                    "complexity": "simple", "components": []},
    )
    assert acc.generate_acceptance_oracle(
        "g", spec, [{"prompt": "p"}], generate_fn=lambda p: _ORACLE_NODE
    ) == ""


def test_generate_acceptance_oracle_node_happy():
    # #697: an explicit node hint yields the node:test oracle (the .mjs analogue of the python
    # scorecard). The node structural gate needs a node:test import + a test/it block.
    spec = AcceptanceSpec(
        goal="calendar math",
        criteria=(AcceptanceCriterion("c1", "Feb 28 + 1 is Mar 1 in 2024", "behavior", ""),),
        build_plan={"surface": "web", "language_hint": "node",
                    "complexity": "simple", "components": []},
    )
    tasks = [{"repo": "R", "task": "only", "prompt": "build addDays"}]
    code = acc.generate_acceptance_oracle("calendar math", spec, tasks,
                                          generate_fn=lambda p: _ORACLE_NODE)
    assert code == _ORACLE_NODE
    assert "node:test" in code and "test(" in code                    # a real, runnable oracle


def test_generate_acceptance_oracle_node_web_surface_no_hint():
    # #697: a WEB surface with NO language hint routes to node — the fleet's web scaffold is the
    # node:http + node:test seed, so the integrated tree is node-testable (matches the job oracle's
    # decision exactly; this is the case that used to fall back / go python-shaped).
    spec = AcceptanceSpec(
        goal="a web app",
        criteria=(AcceptanceCriterion("c1", "the API returns 200", "behavior", ""),),
        build_plan={"surface": "web", "language_hint": None,
                    "complexity": "simple", "components": []},
    )
    code = acc.generate_acceptance_oracle("a web app", spec, [{"prompt": "p"}],
                                          generate_fn=lambda p: _ORACLE_NODE)
    assert code == _ORACLE_NODE


def test_generate_acceptance_oracle_node_prompt_uses_node_template():
    # #697: the node oracle prompt must ask for a node:test file (NOT a pytest one) — otherwise the
    # model writes python and the .mjs seed is garbage. Capture the prompt the generate_fn sees.
    seen = {}

    def gen(prompt: str) -> str:
        seen["prompt"] = prompt
        return _ORACLE_NODE

    spec = AcceptanceSpec(
        goal="g", criteria=(AcceptanceCriterion("c1", "adds two numbers", "behavior", ""),),
        build_plan={"surface": "web", "language_hint": "node",
                    "complexity": "simple", "components": []},
    )
    acc.generate_acceptance_oracle("g", spec, [{"prompt": "build add"}], generate_fn=gen)
    p = seen["prompt"]
    assert "node:test" in p and "../src/" in p                        # node scaffold pinned
    assert "pytest" not in p                                          # never the python template
    assert "adds two numbers" in p and "build add" in p               # criteria + task carried


def test_generate_acceptance_oracle_node_strips_markdown_fences():
    # A small model wraps node code in ```javascript fences despite the instruction; strip them.
    spec = AcceptanceSpec(
        goal="g", criteria=(AcceptanceCriterion("c1", "x is y", "behavior", ""),),
        build_plan={"surface": "web", "language_hint": "node",
                    "complexity": "simple", "components": []},
    )
    fenced = "Here you go:\n```javascript\n" + _ORACLE_NODE + "\n```\n"
    code = acc.generate_acceptance_oracle("g", spec, [{"prompt": "p"}], generate_fn=lambda p: fenced)
    assert code.startswith("import test from 'node:test'")
    assert "```" not in code and "Here you go" not in code


def test_generate_acceptance_oracle_node_junk_is_empty():
    # [kill] node output that lacks the node:test import (or any test block) would 'pass' vacuously
    # -> rejected fail-closed to '' (never seed a scorecard that asserts nothing).
    spec = AcceptanceSpec(
        goal="g", criteria=(AcceptanceCriterion("c1", "x is y", "behavior", ""),),
        build_plan={"surface": "web", "language_hint": "node",
                    "complexity": "simple", "components": []},
    )
    for junk in ("console.log('hi');", "import assert from 'node:assert';\n// no tests here"):
        assert acc.generate_acceptance_oracle(
            "g", spec, [{"prompt": "p"}], generate_fn=lambda p, j=junk: j
        ) == ""


def test_oracle_ecosystem_decision_table():
    # #697: the SINGLE ecosystem resolver shared by the per-task and job oracles — lock the table
    # so the two can never disagree on what a project's tests are written in.
    def eco(**bp):
        return acc._oracle_ecosystem(AcceptanceSpec("g", (), build_plan=bp))

    assert eco(language_hint="python", surface="command-line") == "python"
    assert eco(language_hint="python", surface="web") == "python"          # explicit python wins
    assert eco(language_hint="node", surface="web") == "node"
    assert eco(language_hint="node", surface="command-line") == "node"     # explicit node, any surface
    assert eco(language_hint=None, surface="web") == "node"                 # web scaffold == node
    # #886 seam (NIT-1): web-static is NOT web — the match is exact `== "web"`, never startswith.
    # A hintless static-web goal has NO node test runner, so it must resolve to None (no oracle),
    # not node. Locks the seam so a `surface.startswith("web")` mutant fails here.
    assert eco(language_hint=None, surface="web-static") is None
    assert eco(language_hint="node", surface="web-static") == "node"        # explicit node hint still wins (OBS-1)
    assert eco(language_hint=None, surface="command-line") is None         # hintless non-web: fail-closed
    assert eco(language_hint="dotnet", surface="desktop-gui") is None      # build-only
    assert eco(language_hint="cpp", surface="cli") is None
    assert eco() is None                                                    # empty build_plan
    # build_plan absent entirely (None) -> None, never raises
    assert acc._oracle_ecosystem(AcceptanceSpec("g", ())) is None


def test_generate_acceptance_oracle_no_build_plan_is_empty():
    # build_plan None (the 14B couldn't classify) -> no oracle (language unknown == fail-closed).
    spec = AcceptanceSpec("g", (AcceptanceCriterion("c1", "x is y", "behavior", ""),))
    assert acc.generate_acceptance_oracle(
        "g", spec, [{"prompt": "p"}], generate_fn=lambda p: _ORACLE_PY
    ) == ""


def test_generate_acceptance_oracle_no_test_criteria_is_empty():
    # Only a build criterion -> nothing for an oracle to assert over the build gate -> ''.
    spec = AcceptanceSpec(
        goal="g", criteria=(AcceptanceCriterion("c1", "it builds", "build", ""),),
        build_plan={"surface": "library", "language_hint": "python",
                    "complexity": "simple", "components": []},
    )
    assert acc.generate_acceptance_oracle(
        "g", spec, [{"prompt": "p"}], generate_fn=lambda p: _ORACLE_PY
    ) == ""


def test_generate_acceptance_oracle_unparseable_is_empty():
    # [kill] junk that is not valid python -> '' (fail-closed, never seed a broken test file).
    spec = AcceptanceSpec(
        goal="g", criteria=(AcceptanceCriterion("c1", "x is y", "behavior", ""),),
        build_plan={"surface": "library", "language_hint": "python",
                    "complexity": "simple", "components": []},
    )
    junk = "def test_x(:\n    this is not python !!!"
    assert acc.generate_acceptance_oracle(
        "g", spec, [{"prompt": "p"}], generate_fn=lambda p: junk
    ) == ""


def test_generate_acceptance_oracle_no_test_function_is_empty():
    # [kill] valid python but NO test function -> '' (a file pytest collects nothing from would
    # "pass" vacuously and let every candidate merge unchecked).
    spec = AcceptanceSpec(
        goal="g", criteria=(AcceptanceCriterion("c1", "x is y", "behavior", ""),),
        build_plan={"surface": "library", "language_hint": "python",
                    "complexity": "simple", "components": []},
    )
    no_tests = "import math\n\ndef helper():\n    return 42\n"
    assert acc.generate_acceptance_oracle(
        "g", spec, [{"prompt": "p"}], generate_fn=lambda p: no_tests
    ) == ""


def test_generate_acceptance_oracle_model_error_is_empty():
    # A model failure must not crash the plan -> '' (non-blocking, fail-closed).
    spec = AcceptanceSpec(
        goal="g", criteria=(AcceptanceCriterion("c1", "x is y", "behavior", ""),),
        build_plan={"surface": "library", "language_hint": "python",
                    "complexity": "simple", "components": []},
    )

    def boom(prompt: str) -> str:
        raise RuntimeError("model blew up writing the oracle")

    assert acc.generate_acceptance_oracle("g", spec, [{"prompt": "p"}], generate_fn=boom) == ""


def test_generate_acceptance_oracle_empty_tasks_is_empty():
    spec = AcceptanceSpec(
        goal="g", criteria=(AcceptanceCriterion("c1", "x is y", "behavior", ""),),
        build_plan={"surface": "library", "language_hint": "python",
                    "complexity": "simple", "components": []},
    )
    assert acc.generate_acceptance_oracle("g", spec, [], generate_fn=lambda p: _ORACLE_PY) == ""


def test_generate_acceptance_oracle_prompt_carries_criteria_and_task():
    # The oracle prompt must feed the 14B BOTH the criteria (what to assert) and the feature
    # task prompt (so its import names align with what the coder is told to build).
    captured = {}

    def gen(prompt: str) -> str:
        captured["p"] = prompt
        return _ORACLE_PY

    spec = AcceptanceSpec(
        goal="calendar math",
        criteria=(AcceptanceCriterion("c1", "Feb 28 + 1 is Mar 1 in 2024", "behavior", ""),),
        build_plan={"surface": "command-line", "language_hint": "python",
                    "complexity": "simple", "components": []},
    )
    acc.generate_acceptance_oracle(
        "calendar math", spec, [{"prompt": "Implement add_days(year, month, day, n)"}], generate_fn=gen
    )
    assert "Feb 28 + 1 is Mar 1 in 2024" in captured["p"]            # the criterion to assert
    assert "Implement add_days(year, month, day, n)" in captured["p"]  # the impl to align names with
    # spec-blind routing guard: the oracle prompt must NOT collide with the criteria prompt's
    # routing phrase (else a fake/real router mis-handles it).
    assert "ACCEPTANCE CRITERIA" not in captured["p"]


# ---- _repair_hypothesis_strategy_kwargs (the B1 collectability fix) --------
#
# The 14B routinely emits `st.text(min_length=1)` — but Hypothesis strategies bound length
# with min_size/max_size, so the strategy call raises TypeError at COLLECTION and the whole
# oracle file is un-collectable. No coder candidate can EVER pass it, yet the job is blamed on
# the coder (battery job B1, deterministic since 2026-07-07). ast.parse does NOT catch it (the
# call is syntactically valid), so the repair must run BEFORE structural validation.

#: A B1-shaped BROKEN oracle: three `min_length=` kwargs on one @given line + a nested
#: `st.text(min_length=1)` inside `st.lists(..., max_length=3)`.
_BROKEN_HYP_ORACLE = (
    "from hypothesis import given\n"
    "from hypothesis import strategies as st\n"
    "from expense_cli import add_expense, list_expenses\n"
    "\n\n"
    "@given(st.text(min_length=1), st.floats(allow_nan=False), st.text(min_length=1))\n"
    "def test_add_expense_roundtrip(name, amount, note):\n"
    "    assert add_expense(name, amount, note) is not None\n"
    "\n\n"
    "@given(st.lists(st.text(min_length=1), max_length=3))\n"
    "def test_list_expenses(items):\n"
    "    assert isinstance(list_expenses(items), list)\n"
)

#: The same oracle already CORRECT — the repair must leave it byte-identical.
_CLEAN_HYP_ORACLE = (
    "from hypothesis import given\n"
    "from hypothesis import strategies as st\n"
    "from expense_cli import add_expense\n"
    "\n\n"
    "@given(st.text(min_size=1), st.floats(allow_nan=False))\n"
    "def test_add(name, amount):\n"
    "    assert add_expense(name, amount) is not None\n"
)


def _install_fake_hypothesis(monkeypatch):
    """Register a FAITHFUL hypothesis stub in sys.modules (the runtime venv has no hypothesis —
    the fleet gate runs it via ephemeral `uv run --with hypothesis`). The stub's strategies
    accept ONLY min_size/max_size (like the real library) and raise the SAME TypeError on
    min_length/max_length, so exec'ing an oracle against it reproduces collection exactly:
    the broken form raises, the repaired form runs clean."""
    import sys
    import types

    strat = types.ModuleType("hypothesis.strategies")

    def text(*, min_size=0, max_size=None, alphabet=None):
        return ("text", min_size, max_size)

    def lists(elements=None, *, min_size=0, max_size=None):
        return ("lists", min_size, max_size)

    def integers(*, min_value=None, max_value=None):
        return ("integers",)

    def floats(*, allow_nan=True, allow_infinity=True):
        return ("floats",)

    strat.text = text
    strat.lists = lists
    strat.integers = integers
    strat.floats = floats

    hyp = types.ModuleType("hypothesis")

    def given(*args, **kwargs):
        def deco(fn):
            return fn

        return deco

    hyp.given = given
    hyp.strategies = strat
    monkeypatch.setitem(sys.modules, "hypothesis", hyp)
    monkeypatch.setitem(sys.modules, "hypothesis.strategies", strat)


def test_repair_rewrites_min_and_max_length_to_size():
    out = acc._repair_hypothesis_strategy_kwargs(_BROKEN_HYP_ORACLE)
    assert "min_length" not in out and "max_length" not in out       # every kwarg rewritten
    assert out.count("min_size=1") == 3                              # all three on the @given line
    assert "max_size=3" in out                                       # the st.lists bound
    import ast as _ast
    _ast.parse(out)                                                  # still valid python


def test_repair_broken_oracle_is_collectable_repaired_and_not_before(monkeypatch):
    # [kill] the load-bearing proof: against a faithful hypothesis stub the BROKEN oracle raises
    # TypeError at exec (== pytest collection), the REPAIRED oracle exec's clean (collects).
    # Self-contained (no app import) so the ONLY thing that can raise is the strategy call.
    exec_broken = (
        "from hypothesis import given\n"
        "from hypothesis import strategies as st\n"
        "\n\n"
        "@given(st.text(min_length=1), st.lists(st.integers(), max_length=3))\n"
        "def test_x(s, xs):\n"
        "    assert True\n"
    )
    _install_fake_hypothesis(monkeypatch)
    with pytest.raises(TypeError):
        exec(compile(exec_broken, "<broken-oracle>", "exec"), {})
    repaired = acc._repair_hypothesis_strategy_kwargs(exec_broken)
    assert "min_size=1" in repaired and "max_size=3" in repaired
    exec(compile(repaired, "<repaired-oracle>", "exec"), {})        # no exception -> collectable


def test_repair_clean_oracle_is_byte_identical():
    # No target kwargs -> byte-identical (the repair must never touch a correct oracle).
    assert acc._repair_hypothesis_strategy_kwargs(_CLEAN_HYP_ORACLE) == _CLEAN_HYP_ORACLE


def test_repair_noop_without_hypothesis_import_is_byte_identical():
    # Scope guard: no `hypothesis` reference -> min_length/max_length cannot be a strategy kwarg,
    # so the code is returned unchanged even though it contains those kwarg forms.
    no_hyp = (
        "from wtforms.validators import Length\n"
        "def build(min_length=1):\n"
        "    return Length(min_length=min_length, max_length=8)\n"
    )
    assert acc._repair_hypothesis_strategy_kwargs(no_hyp) == no_hyp


def test_repair_leaves_comments_and_strings_untouched():
    # AST-scoped to call-site kwargs: min_length inside a COMMENT or a STRING literal survives;
    # only the actual strategy keyword argument is rewritten. (Documents the boundary.)
    mixed = (
        "from hypothesis import given\n"
        "from hypothesis import strategies as st\n"
        "\n"
        "# min_length=1 is the documented constraint\n"
        "DOC = 'other validators use min_length=1 too'\n"
        "\n\n"
        "@given(st.text(min_length=1))\n"
        "def test_x(s):\n"
        "    assert s\n"
    )
    out = acc._repair_hypothesis_strategy_kwargs(mixed)
    assert "# min_length=1 is the documented constraint" in out      # comment untouched
    assert "'other validators use min_length=1 too'" in out         # string literal untouched
    assert "st.text(min_size=1)" in out                             # only the kwarg renamed


def test_repair_leaves_def_params_and_assignments_untouched():
    # AST-scoping means def-parameter DEFAULTS and plain assignments are NOT ast.keyword nodes
    # and are never rewritten — only the call-site strategy kwarg is.
    scoped = (
        "from hypothesis import given\n"
        "from hypothesis import strategies as st\n"
        "\n"
        "def helper(min_length=2):\n"
        "    return min_length\n"
        "\n"
        "max_length = 9\n"
        "\n\n"
        "@given(st.text(min_length=1))\n"
        "def test_x(s):\n"
        "    assert helper() and max_length and s\n"
    )
    out = acc._repair_hypothesis_strategy_kwargs(scoped)
    assert "def helper(min_length=2):" in out                        # def-param default preserved
    assert "return min_length" in out                                # body reference preserved
    assert "max_length = 9" in out                                   # assignment preserved
    assert "st.text(min_size=1)" in out                              # only the call-site kwarg


def test_repair_is_idempotent_and_empty_safe():
    once = acc._repair_hypothesis_strategy_kwargs(_BROKEN_HYP_ORACLE)
    assert acc._repair_hypothesis_strategy_kwargs(once) == once      # second pass is a no-op
    assert acc._repair_hypothesis_strategy_kwargs("") == ""          # empty input is safe


def test_generate_acceptance_oracle_repairs_hypothesis_kwargs():
    # End-to-end through the per-task (#690) generator: a broken hypothesis oracle now SEEDS
    # repaired (before the fix it seeded broken and failed every candidate at collection).
    spec = AcceptanceSpec(
        goal="expense cli",
        criteria=(AcceptanceCriterion("c1", "adds an expense", "behavior", ""),),
        build_plan={"surface": "command-line", "language_hint": "python",
                    "complexity": "simple", "components": []},
    )
    code = acc.generate_acceptance_oracle(
        "expense cli", spec, [{"prompt": "build add_expense"}],
        generate_fn=lambda p: _BROKEN_HYP_ORACLE,
    )
    assert code                                                      # seeds (not fail-closed to '')
    assert "min_length" not in code and "max_length" not in code
    assert "min_size=1" in code
    import ast as _ast
    _ast.parse(code)


# ---- parse_task_report ----------------------------------------------------


def test_parse_task_report_full():
    text = (
        "TASK: add-calc  (myapp)\n"
        "BUILD: completed\n"
        "CHANGES: yes\n"
        "TESTS: pass\n"
        "VERIFY: pass\n"
        "SECRETS: clean\n"
        "REVIEW VERDICT: MERGE\n"
        "RESULT: MERGED into your project - just open the app and try it.\n"
    )
    r = acc.parse_task_report(text)
    assert r.tests == "pass" and r.verify == "pass"
    assert r.review == "MERGE"
    assert "MERGED" in r.result


def test_parse_task_report_missing_lines_default_none():
    r = acc.parse_task_report("TASK: x\nBUILD: completed\n")
    assert r.tests == "none" and r.verify == "none"  # fail-closed: absent != pass
    assert r.review == "" and r.result == ""


# ---- criterion_status (THE anti-rubber-stamp core) ------------------------


def test_status_build_verify_pass_is_verified():
    c = AcceptanceCriterion("c1", "it builds", "build", "")
    assert acc.criterion_status(c, TaskReport(verify="pass")) == acc.STATUS_VERIFIED


def test_status_build_verify_none_is_unverified():
    c = AcceptanceCriterion("c1", "it builds", "build", "")
    assert acc.criterion_status(c, TaskReport(verify="none")) == acc.STATUS_UNVERIFIED


def test_status_behavior_tests_pass_is_verified():
    c = AcceptanceCriterion("c2", "2 + 3 shows 5", "behavior", "")
    assert acc.criterion_status(c, TaskReport(tests="pass")) == acc.STATUS_VERIFIED


def test_status_behavior_tests_fail_is_failed():
    c = AcceptanceCriterion("c2", "2 + 3 shows 5", "behavior", "")
    assert acc.criterion_status(c, TaskReport(tests="fail")) == acc.STATUS_FAILED


def test_status_behavior_tests_none_is_UNVERIFIED_not_pass():
    # The .NET case: dotnet has no `dotnet test`, so a C# behavior test never runs ->
    # TESTS: none. It MUST come back UNVERIFIED, never verified. This is the whole point.
    c = AcceptanceCriterion("c2", "2 + 3 shows 5", "behavior", "")
    status = acc.criterion_status(c, TaskReport(tests="none", verify="pass"))
    assert status == acc.STATUS_UNVERIFIED
    assert status != acc.STATUS_VERIFIED


def test_status_smoke_tests_skip_is_unverified():
    # pytest-not-importable / dotnet -> 'skip'/'none' -> unverified, never a pass.
    c = AcceptanceCriterion("c3", "it launches", "smoke", "")
    assert acc.criterion_status(c, TaskReport(tests="skip")) == acc.STATUS_UNVERIFIED


def test_status_human_is_eyeball_regardless_of_report():
    c = AcceptanceCriterion("c4", "fun for a kid", "human", "")
    assert acc.criterion_status(c, TaskReport(tests="pass", verify="pass")) == acc.STATUS_EYEBALL


def test_status_no_report_objective_is_unverified():
    c = AcceptanceCriterion("c1", "it builds", "build", "")
    assert acc.criterion_status(c, None) == acc.STATUS_UNVERIFIED


# ---- detect_ecosystem / detect_run_command --------------------------------


def test_detect_ecosystem_node(tmp_path):
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    assert acc.detect_ecosystem(tmp_path) == "node"


def test_detect_ecosystem_python(tmp_path):
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    assert acc.detect_ecosystem(tmp_path) == "python"


def test_detect_ecosystem_dotnet(tmp_path):
    (tmp_path / "App.csproj").write_text("<Project/>", encoding="utf-8")
    assert acc.detect_ecosystem(tmp_path) == "dotnet"


def test_detect_ecosystem_unknown(tmp_path):
    assert acc.detect_ecosystem(tmp_path) == "unknown"


def test_detect_run_command_node_start(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"start": "node ."}}), encoding="utf-8")
    assert acc.detect_run_command(tmp_path) == "npm start"


def test_detect_run_command_dotnet(tmp_path):
    (tmp_path / "App.csproj").write_text("<Project/>", encoding="utf-8")
    assert acc.detect_run_command(tmp_path) == "dotnet run"


def test_detect_run_command_python_entry(tmp_path):
    (tmp_path / "main.py").write_text("print('hi')", encoding="utf-8")
    assert acc.detect_run_command(tmp_path) == "python main.py"


def test_detect_run_command_unknown_fallback(tmp_path):
    cmd = acc.detect_run_command(tmp_path)
    assert "open the folder" in cmd and str(tmp_path) in cmd


# ---- render_criteria_preview ----------------------------------------------


def test_preview_lists_criteria_and_approve_line():
    spec = AcceptanceSpec("a calculator", (
        AcceptanceCriterion("c1", "2 + 3 shows 5", "behavior", ""),
        AcceptanceCriterion("c2", "big friendly buttons", "visual", ""),
    ))
    out = acc.render_criteria_preview(spec, ecosystem="python")
    assert "a calculator" in out
    assert "2 + 3 shows 5" in out and "big friendly buttons" in out
    assert "/dispatch approve" in out and "/dispatch reject" in out


def test_preview_dotnet_caveat_is_up_front():
    spec = AcceptanceSpec("a C# calc", (AcceptanceCriterion("c1", "2 + 3 shows 5", "behavior", ""),))
    out = acc.render_criteria_preview(spec, ecosystem="dotnet")
    assert "C#/.NET" in out and "does not run .NET tests" in out


def test_preview_unknown_caveat():
    spec = AcceptanceSpec("a thing", (AcceptanceCriterion("c1", "it builds", "build", ""),))
    out = acc.render_criteria_preview(spec, ecosystem="unknown")
    assert "couldn't tell this project's language" in out


def test_preview_with_tasks_shows_humanized_build_plan():
    # The operator must see HOW the goal is built (the decomposition) — not only what
    # counts as DONE. Mutation-resistant: assert the actual humanized slug substrings
    # ('Add calc', 'Acceptance tests') appear, not just the section header.
    spec = AcceptanceSpec("a calculator", (
        AcceptanceCriterion("c1", "2 + 3 shows 5", "behavior", ""),
    ))
    tasks = [
        {"repo": "calc", "task": "add-calc", "prompt": "build a calc (DO NOT SHOW THIS)"},
        {"repo": "calc", "task": "acceptance_tests", "prompt": "write tests (DO NOT SHOW THIS)"},
    ]
    out = acc.render_criteria_preview(spec, ecosystem="python", tasks=tasks)
    assert "Here's how I'll build it (2 task(s)):" in out
    assert "Add calc" in out          # humanized slug: hyphen -> space, capitalized
    assert "Acceptance tests" in out  # humanized slug: underscore -> space, capitalized
    # the full task prompt is NOT dumped — only the name/shape
    assert "DO NOT SHOW THIS" not in out
    # the build plan sits ABOVE the acceptance criteria (operator reads shape first)
    assert out.index("Here's how I'll build it") < out.index("2 + 3 shows 5")


def test_preview_without_tasks_has_no_build_plan_section():
    # Backward-compat: every existing caller passes no tasks — the output must be
    # byte-identical with tasks omitted vs tasks=None, and must NOT add a build-plan section.
    spec = AcceptanceSpec("a calculator", (
        AcceptanceCriterion("c1", "2 + 3 shows 5", "behavior", ""),
        AcceptanceCriterion("c2", "big friendly buttons", "visual", ""),
    ))
    out_omitted = acc.render_criteria_preview(spec, ecosystem="python")
    out_none = acc.render_criteria_preview(spec, ecosystem="python", tasks=None)
    assert out_omitted == out_none
    assert "Here's how I'll build it" not in out_omitted
    # an empty task list is treated the same as None (no section)
    assert acc.render_criteria_preview(spec, ecosystem="python", tasks=[]) == out_omitted


def test_preview_with_assumptions_surfaces_them_under_the_header():
    # The operator gives detailed PRODUCT intent but no tech direction, so the preview
    # confirms the 14B's product-level reads of the underspecified parts before he approves
    # a long build. Mutation-resistant: assert the ACTUAL assumption strings appear (not
    # just the header), each on its own line, under the plain-English header.
    spec = AcceptanceSpec(
        "a calculator",
        (AcceptanceCriterion("c1", "2 + 3 shows 5", "behavior", ""),),
        assumptions=(
            "Assumed decimals are supported",
            "Assumed no calculation history is kept",
            "Assumed a normal resizable window",
        ),
    )
    out = acc.render_criteria_preview(spec, ecosystem="python")
    assert "Here's how I read the parts you didn't spell out" in out
    assert "reject and add detail if I got one wrong" in out
    assert "Assumed decimals are supported" in out
    assert "Assumed no calculation history is kept" in out
    assert "Assumed a normal resizable window" in out
    # each assumption is its own bulleted line
    assert "  - Assumed decimals are supported" in out
    # the assumptions sit ABOVE the acceptance criteria (operator reads the read-back first)
    assert out.index("Here's how I read the parts") < out.index("2 + 3 shows 5")
    # still ends with the approve/reject affordance
    assert "/dispatch approve" in out and "/dispatch reject" in out


def test_preview_without_assumptions_has_no_assumptions_section():
    # Backward-compat: a spec with no assumptions (the default, every existing caller)
    # renders byte-identically to before and adds NO read-back section.
    spec_no = AcceptanceSpec(
        "a calculator",
        (
            AcceptanceCriterion("c1", "2 + 3 shows 5", "behavior", ""),
            AcceptanceCriterion("c2", "big friendly buttons", "visual", ""),
        ),
    )
    out_no = acc.render_criteria_preview(spec_no, ecosystem="python")
    assert "Here's how I read the parts you didn't spell out" not in out_no
    # adding assumptions is purely ADDITIVE — the no-assumptions output is a substring-free
    # baseline; the with-assumptions render only INSERTS the section, leaving the rest.
    spec_yes = AcceptanceSpec(
        spec_no.goal, spec_no.criteria, assumptions=("Assumed decimals are supported",)
    )
    out_yes = acc.render_criteria_preview(spec_yes, ecosystem="python")
    assert "Here's how I read the parts you didn't spell out" in out_yes
    # the criteria + caveat + approve lines that existed without assumptions are all still
    # present unchanged when assumptions are added (nothing was displaced or dropped).
    for fragment in (
        "2 + 3 shows 5",
        "big friendly buttons",
        "/dispatch approve",
        "/dispatch reject",
    ):
        assert fragment in out_no and fragment in out_yes


# ---- render_acceptance_report ---------------------------------------------


def test_report_unverified_is_never_rendered_as_pass(tmp_path):
    # A behavior criterion whose test never ran (dotnet) must render NOT AUTO-CHECKED,
    # and the report must not claim PASS for it.
    (tmp_path / "App.csproj").write_text("<Project/>", encoding="utf-8")
    spec = AcceptanceSpec("a C# calc", (
        AcceptanceCriterion("c1", "the project builds", "build", ""),
        AcceptanceCriterion("c2", "2 + 3 shows 5", "behavior", ""),
    ))
    reports = [acc.parse_task_report("VERIFY: pass\nTESTS: none\nRESULT: MERGED\n")]
    out = acc.render_acceptance_report(spec, task_reports=reports, repo=tmp_path)
    # build verified; behavior NOT auto-checked
    assert "[PASS]  the project builds" in out
    assert "NOT AUTO-CHECKED" in out
    # the behavior line is NOT marked PASS
    behavior_line = next(ln for ln in out.splitlines() if "2 + 3 shows 5" in ln)
    assert "PASS" not in behavior_line


def test_report_includes_eyeball_and_open_command(tmp_path):
    (tmp_path / "main.py").write_text("", encoding="utf-8")
    spec = AcceptanceSpec("g", (
        AcceptanceCriterion("c1", "2 + 3 shows 5", "behavior", ""),
        AcceptanceCriterion("c2", "looks delightful", "visual", ""),
    ))
    reports = [acc.parse_task_report("VERIFY: pass\nTESTS: pass\n")]
    out = acc.render_acceptance_report(spec, task_reports=reports, repo=tmp_path)
    assert "[PASS]  2 + 3 shows 5" in out
    assert "looks delightful" in out and "Please check by eye" in out
    assert "python main.py" in out


def test_report_aggregation_fail_dominates(tmp_path):
    spec = AcceptanceSpec("g", (AcceptanceCriterion("c1", "2 + 3 shows 5", "behavior", ""),))
    reports = [acc.parse_task_report("TESTS: pass\n"), acc.parse_task_report("TESTS: fail\n")]
    out = acc.render_acceptance_report(spec, task_reports=reports, repo=tmp_path)
    line = next(ln for ln in out.splitlines() if "2 + 3 shows 5" in ln)
    assert "[FAIL]" in line  # a failure anywhere is not hidden behind a pass


# ---- generate_plan (decompose + criteria + ruler + compile) ---------------


def test_generate_plan_happy(tmp_path):
    projects = tmp_path / "projects"
    repo = _git_repo(projects)
    gen = _fake_model(
        tasks_json=json.dumps([{"task": "add-calc", "prompt": "build a calculator"}]),
        criteria_json=json.dumps([
            {"text": "the project builds", "tier": "build", "check": ""},
            {"text": "2 + 3 shows 5", "tier": "behavior", "check": "assert add(2,3)==5"},
            {"text": "big friendly buttons", "tier": "visual", "check": ""},
        ]),
    )
    res = acc.generate_plan("a calculator for a kid", repo, generate_fn=gen, projects_dir=projects)
    assert res.ok
    # BEHAVIOR CHANGE (#670 Problem 3): a SINGLE feature task folds the behavior criterion
    # into its own prompt — no separate acceptance-tests task (was len == 2).
    assert len(res.tasks) == 1
    assert not any(t["task"] == acc.ACCEPTANCE_TASK_SLUG for t in res.tasks)
    assert "2 + 3 shows 5" in res.tasks[0]["prompt"]            # behavior criterion folded in
    assert "REQUIRED behavior" in res.tasks[0]["prompt"]        # anti-mirror header preserved
    assert len(res.spec.criteria) == 3                          # the spec is unchanged by the fold
    assert len(res.spec.objective) == 2 and len(res.spec.human) == 1


def test_generate_plan_populates_assumptions_from_model(tmp_path):
    # The PLAN step's SECOND model call surfaces product assumptions onto the spec, so the
    # confirm preview can confirm the 14B's read of the underspecified goal. Mutation-
    # resistant: assert the exact assumption strings land on res.spec.assumptions AND that
    # render_criteria_preview surfaces them — the end-to-end PLAN -> preview path.
    projects = tmp_path / "projects"
    repo = _git_repo(projects)
    gen = _fake_model(
        tasks_json=json.dumps([{"task": "add-calc", "prompt": "build a calculator"}]),
        criteria_json=json.dumps([
            {"text": "the project builds", "tier": "build", "check": ""},
            {"text": "2 + 3 shows 5", "tier": "behavior", "check": "assert add(2,3)==5"},
        ]),
        assumptions_json=json.dumps([
            "Assumed decimals are supported",
            "Assumed no calculation history is kept",
        ]),
    )
    res = acc.generate_plan("a calculator", repo, generate_fn=gen, projects_dir=projects)
    assert res.ok
    assert res.spec.assumptions == (
        "Assumed decimals are supported",
        "Assumed no calculation history is kept",
    )
    preview = acc.render_criteria_preview(res.spec, ecosystem="python", tasks=res.tasks)
    assert "Here's how I read the parts you didn't spell out" in preview
    assert "Assumed decimals are supported" in preview
    assert "Assumed no calculation history is kept" in preview


def test_generate_plan_fully_specified_goal_emits_no_assumptions(tmp_path):
    # When the model returns [] for assumptions (the goal was fully specified), the spec
    # carries none and the preview has no read-back section — backward-compatible.
    projects = tmp_path / "projects"
    repo = _git_repo(projects)
    gen = _fake_model(
        tasks_json=json.dumps([{"task": "add-calc", "prompt": "build a calculator"}]),
        criteria_json=json.dumps([{"text": "2 + 3 shows 5", "tier": "behavior", "check": ""}]),
        assumptions_json="[]",  # fully specified -> the model assumed nothing
    )
    res = acc.generate_plan("a calculator", repo, generate_fn=gen, projects_dir=projects)
    assert res.ok
    assert res.spec.assumptions == ()
    preview = acc.render_criteria_preview(res.spec, ecosystem="python", tasks=res.tasks)
    assert "Here's how I read the parts you didn't spell out" not in preview


def test_generate_plan_assumptions_model_error_is_non_fatal(tmp_path):
    # A failure in the assumptions call must not crash the plan — it proceeds with no
    # assumptions (the criteria + tasks are unaffected). Fail-closed AND non-blocking.
    projects = tmp_path / "projects"
    repo = _git_repo(projects)

    def gen(prompt: str) -> str:
        if "PRODUCT assumptions" in prompt:
            raise RuntimeError("model blew up generating assumptions")
        if "ACCEPTANCE CRITERIA" in prompt:
            return json.dumps([{"text": "2 + 3 shows 5", "tier": "behavior", "check": ""}])
        return json.dumps([{"task": "add-calc", "prompt": "build a calculator"}])

    res = acc.generate_plan("a calculator", repo, generate_fn=gen, projects_dir=projects)
    assert res.ok
    assert res.spec.assumptions == ()
    assert any("2 + 3 shows 5" in t["prompt"] for t in res.tasks)  # plan still produced


def test_generate_plan_assumptions_survive_the_smoke_floor(tmp_path):
    # The collapsed-test-intent smoke floor rebuilds the spec; the product assumptions must
    # survive that copy (otherwise a goal that triggers the floor would silently lose its
    # read-back). Drives both the floor AND the assumptions in one plan.
    projects = tmp_path / "projects"
    repo = _git_repo(projects)
    gen = _fake_model(
        tasks_json=json.dumps([
            {"task": "implement-thing", "prompt": "build the thing"},
            {"task": "test-thing", "prompt": "test the thing"},   # collapsed -> test intent
        ]),
        criteria_json=json.dumps([{"text": "the project builds", "tier": "build", "check": ""}]),
        assumptions_json=json.dumps(["Assumed a normal resizable window"]),
    )
    res = acc.generate_plan("build a thing", repo, generate_fn=gen, projects_dir=projects)
    assert res.ok
    assert any(c.tier == acc.TIER_SMOKE for c in res.spec.criteria)   # the floor fired ...
    assert res.spec.assumptions == ("Assumed a normal resizable window",)  # ... and survived


def test_generate_plan_bad_repo_rejected(tmp_path):
    projects = tmp_path / "projects"
    projects.mkdir()
    gen = _fake_model(tasks_json="[]", criteria_json="[]")
    res = acc.generate_plan("idea", "does-not-exist", generate_fn=gen, projects_dir=projects)
    assert not res.ok and not res.tasks


def test_generate_plan_criteria_model_error_still_ok_with_build_floor(tmp_path):
    projects = tmp_path / "projects"
    repo = _git_repo(projects)

    def gen(prompt: str) -> str:
        if "ACCEPTANCE CRITERIA" in prompt:
            raise RuntimeError("model blew up generating criteria")
        return json.dumps([{"task": "do-it", "prompt": "do it"}])

    res = acc.generate_plan("an idea here", repo, generate_fn=gen, projects_dir=projects)
    assert res.ok
    # criteria-gen failed -> ruler injects the build floor; plan still proceeds
    assert len(res.spec.criteria) == 1 and res.spec.criteria[0].tier == "build"


def test_generate_plan_only_human_criteria_gets_build_floor(tmp_path):
    projects = tmp_path / "projects"
    repo = _git_repo(projects)
    gen = _fake_model(
        tasks_json=json.dumps([{"task": "t", "prompt": "p"}]),
        criteria_json=json.dumps([{"text": "fun for an 8-year-old", "tier": "human", "check": ""}]),
    )
    res = acc.generate_plan("make it fun", repo, generate_fn=gen, projects_dir=projects)
    assert res.ok
    assert any(c.tier == "build" for c in res.spec.objective)  # floor injected


def test_generate_plan_task_fallback_flag(tmp_path):
    projects = tmp_path / "projects"
    repo = _git_repo(projects)
    gen = _fake_model(
        tasks_json="garbage not json",  # decompose falls back to a single task
        criteria_json=json.dumps([{"text": "the project builds", "tier": "build", "check": ""}]),
    )
    res = acc.generate_plan("just do this one thing", repo, generate_fn=gen, projects_dir=projects)
    assert res.ok and res.fell_back and len(res.tasks) == 1


# ---- never end at zero tests (the right-sizing safety floor) ---------------


def test_generate_plan_collapsed_test_intent_gets_a_smoke_floor(tmp_path):
    # The decomposer drops the model's structural test task (the test task is added
    # downstream). If criteria-gen then yields NO behavior/smoke criterion, the goal would
    # otherwise reach the fleet with ZERO tests. The collapsed_test_intent floor injects a
    # SMOKE criterion so compile_prompts still appends the acceptance-test task.
    projects = tmp_path / "projects"
    repo = _git_repo(projects)
    gen = _fake_model(
        # implement-thing (feature) + test-thing (structural test -> collapsed) ...
        tasks_json=json.dumps([
            {"task": "implement-thing", "prompt": "build the thing"},
            {"task": "test-thing", "prompt": "test the thing"},
        ]),
        # ... and criteria-gen produces ONLY a build criterion (no behavior/smoke).
        criteria_json=json.dumps([{"text": "the project builds", "tier": "build", "check": ""}]),
    )
    res = acc.generate_plan("build a thing", repo, generate_fn=gen, projects_dir=projects)
    assert res.ok
    # the smoke floor fired -> a smoke criterion exists ...
    assert any(c.tier == acc.TIER_SMOKE for c in res.spec.criteria), res.spec.criteria
    # ... and (BEHAVIOR CHANGE #670 Problem 3) since the decomposition right-sized to ONE
    # feature task, the smoke criterion FOLDS into that task's prompt (never zero tests) —
    # no separate acceptance-tests task is spun.
    assert len(res.tasks) == 1, [t["task"] for t in res.tasks]
    assert not any(t["task"] == acc.ACCEPTANCE_TASK_SLUG for t in res.tasks)
    assert "[smoke]" in res.tasks[0]["prompt"]


def test_generate_plan_no_test_intent_keeps_honest_no_test_posture(tmp_path):
    # The floor is GATED on collapsed_test_intent: a goal whose decomposition dropped NO
    # test task (the model proposed only a feature) and whose criteria are build-only must
    # NOT get a fabricated smoke criterion — the honest "nothing testable here" posture is
    # preserved (mirrors the .NET / visual-only report behavior).
    projects = tmp_path / "projects"
    repo = _git_repo(projects)
    gen = _fake_model(
        tasks_json=json.dumps([{"task": "implement-thing", "prompt": "build the thing"}]),
        criteria_json=json.dumps([{"text": "the project builds", "tier": "build", "check": ""}]),
    )
    res = acc.generate_plan("build a thing", repo, generate_fn=gen, projects_dir=projects)
    assert res.ok
    assert not any(c.tier == acc.TIER_SMOKE for c in res.spec.criteria)
    assert not any(t["task"] == acc.ACCEPTANCE_TASK_SLUG for t in res.tasks)


# ===========================================================================
# Build-signal (the 14B's coarse product->platform classification) — #674
# ===========================================================================
#
# The plumbing is verified with an injected fake generate_fn (no GPU): a valid build_plan
# lands on spec.build_plan, threads onto EVERY queue task object, and renders the preview
# line; malformed / absent / bad-enum input fails closed to unknown/None with no crash and
# today's path byte-identical. Each assertion is paired with a mutation that drives it RED
# (the BlarAI mutation-resistance bar) — see test_acceptance_build_plan_mutation_guards.py.

_GOOD_BUILD_PLAN = json.dumps({
    "surface": "desktop-gui",
    "language_hint": None,
    "complexity": "complex",
    "components": [
        {"name": "calculator-core", "kind": "testable-logic"},
        {"name": "ui-shell", "kind": "gui-shell"},
    ],
})


# ---- _parse_build_plan (the validator: model PROPOSES, this DISPOSES) ------


def test_parse_build_plan_valid_object():
    got = acc._parse_build_plan(_GOOD_BUILD_PLAN)
    assert got == {
        "surface": "desktop-gui",
        "language_hint": None,
        "complexity": "complex",
        "components": [
            {"name": "calculator-core", "kind": "testable-logic"},
            {"name": "ui-shell", "kind": "gui-shell"},
        ],
    }


def test_parse_build_plan_extracts_from_prose_and_fences():
    raw = 'Sure:\n```json\n{"surface": "web", "complexity": "simple"}\n```\n'
    got = acc._parse_build_plan(raw)
    assert got["surface"] == "web" and got["complexity"] == "simple"
    assert got["language_hint"] is None and got["components"] == []


def test_parse_build_plan_no_object_is_none():
    # No parseable JSON object at all -> None (so the spec carries no build_plan and the
    # dispatch is byte-identical to today). Empty string, prose, and a bare ARRAY all -> None
    # only when there is no {...} substring; an array-with-objects is handled separately below.
    assert acc._parse_build_plan("") is None
    assert acc._parse_build_plan("no json here at all") is None


def test_parse_build_plan_bad_surface_enum_coerced_to_unknown():
    # A surface the model invented (not in the enum) -> unknown (fail-closed: no scaffold).
    got = acc._parse_build_plan(json.dumps({"surface": "quantum-hologram", "complexity": "moderate"}))
    assert got["surface"] == "unknown"


def test_parse_build_plan_missing_surface_defaults_unknown():
    got = acc._parse_build_plan(json.dumps({"complexity": "simple"}))
    assert got["surface"] == "unknown"


def test_parse_build_plan_bad_language_hint_becomes_none():
    # An unknown language, or a literal "null"/"none" string, both -> None (never guessed).
    assert acc._parse_build_plan(json.dumps({"surface": "library", "language_hint": "cobol"}))["language_hint"] is None
    assert acc._parse_build_plan(json.dumps({"surface": "library", "language_hint": "null"}))["language_hint"] is None
    assert acc._parse_build_plan(json.dumps({"surface": "library", "language_hint": "python"}))["language_hint"] == "python"


def test_parse_build_plan_bad_complexity_defaults_moderate():
    got = acc._parse_build_plan(json.dumps({"surface": "web", "complexity": "trivial"}))
    assert got["complexity"] == "moderate"  # must match the fleet's ValidateSet default


def test_parse_build_plan_components_validated_and_capped():
    raw = json.dumps({
        "surface": "desktop-gui",
        "components": [
            {"name": "core", "kind": "testable-logic"},   # kept
            {"name": "shell", "kind": "bogus-kind"},        # kind coerced -> other
            {"name": "", "kind": "data"},                   # blank name -> dropped
            {"kind": "data"},                               # no name -> dropped
            "not-a-dict",                                   # non-dict -> dropped
        ],
    })
    got = acc._parse_build_plan(raw)
    assert got["components"] == [
        {"name": "core", "kind": "testable-logic"},
        {"name": "shell", "kind": "other"},
    ]


def test_parse_build_plan_components_non_list_is_empty():
    got = acc._parse_build_plan(json.dumps({"surface": "web", "components": "nope"}))
    assert got["components"] == []


def test_parse_build_plan_never_raises_on_garbage_types():
    # Defensive: even a wildly wrong shape inside a {...} must not raise — fail closed.
    for raw in ('{"surface": 42, "language_hint": [1,2], "complexity": {"x": 1}, "components": 7}',
                '{"surface": null}', '{}'):
        got = acc._parse_build_plan(raw)
        assert got is not None and got["surface"] == "unknown"


# ---- AcceptanceSpec round-trips build_plan --------------------------------


def test_spec_roundtrips_build_plan():
    bp = {"surface": "web", "language_hint": "node", "complexity": "moderate", "components": []}
    spec = AcceptanceSpec(
        goal="a thing",
        criteria=(AcceptanceCriterion("c1", "it builds", "build", ""),),
        build_plan=bp,
    )
    d = spec.to_dict()
    assert d["build_plan"] == bp
    restored = AcceptanceSpec.from_dict(d)
    assert restored == spec and restored.build_plan == bp


def test_spec_from_dict_without_build_plan_defaults_none():
    # Backward-compat: an older wire payload with NO build_plan key reconstructs as None
    # (never raises) — exactly today's behavior.
    restored = AcceptanceSpec.from_dict(
        {"goal": "g", "criteria": [{"id": "c1", "text": "it builds", "tier": "build", "check": ""}]}
    )
    assert restored.build_plan is None


def test_spec_from_dict_non_dict_build_plan_becomes_none():
    # Defensive reconstruction: a forged non-dict build_plan (list/str/number) -> None.
    for bad in ([1, 2], "desktop-gui", 42):
        restored = AcceptanceSpec.from_dict({"goal": "g", "criteria": [], "build_plan": bad})
        assert restored.build_plan is None


def test_ensure_test_floor_preserves_build_plan():
    # _ensure_test_floor is a general spec-copy helper; it must preserve build_plan the same
    # way it preserves assumptions (a TIGHT guard on the carry — the end-to-end plan test is
    # satisfied by the later attach, so this direct test is what fails if the carry is dropped).
    bp = {"surface": "library", "language_hint": "python", "complexity": "simple", "components": []}
    spec = AcceptanceSpec(
        "g", (AcceptanceCriterion("c1", "it builds", "build", ""),),
        assumptions=("Assumed X",), build_plan=bp,
    )
    floored = acc._ensure_test_floor(spec)
    assert floored.build_plan == bp           # build_plan carried across the copy
    assert floored.assumptions == ("Assumed X",)  # (alongside the assumptions it already carried)
    assert any(c.tier == acc.TIER_SMOKE for c in floored.criteria)  # the floor still fired


# ---- threading the per-task fields onto the queue task objects ------------


def test_compile_prompts_threads_build_fields_onto_single_task():
    spec = AcceptanceSpec(
        "g",
        (AcceptanceCriterion("c1", "2 + 3 shows 5", "behavior", ""),),
        build_plan={"surface": "desktop-gui", "language_hint": "dotnet", "complexity": "complex", "components": []},
    )
    out = acc.compile_prompts([{"repo": "R", "task": "only", "prompt": "build it"}], spec)
    assert len(out) == 1
    assert out[0]["surface"] == "desktop-gui"
    assert out[0]["complexity"] == "complex"
    assert out[0]["language_hint"] == "dotnet"
    # the existing fields are untouched
    assert out[0]["task"] == "only" and out[0]["repo"] == "R"


def test_compile_prompts_threads_build_fields_onto_every_task_multi():
    # >=2 features -> a dedicated acceptance task is appended; ALL of them (features + the
    # acceptance task) must carry the goal-level signal.
    spec = AcceptanceSpec(
        "g",
        (AcceptanceCriterion("c1", "2 + 3 shows 5", "behavior", ""),),
        build_plan={"surface": "web", "language_hint": "node", "complexity": "moderate", "components": []},
    )
    tasks = [{"repo": "R", "task": "f1", "prompt": "p1"}, {"repo": "R", "task": "f2", "prompt": "p2"}]
    out = acc.compile_prompts(tasks, spec)
    assert len(out) == 3 and out[-1]["task"] == acc.ACCEPTANCE_TASK_SLUG
    for t in out:
        assert t["surface"] == "web" and t["complexity"] == "moderate" and t["language_hint"] == "node"


def test_compile_prompts_no_build_plan_threads_failclosed_defaults():
    # No build_plan (None) -> every task still carries the fail-closed defaults so the fleet
    # contract (surface/complexity/language_hint always present) holds; surface=unknown is
    # exactly today's no-seed path.
    spec = AcceptanceSpec("g", (AcceptanceCriterion("c1", "it builds", "build", ""),))  # build_plan defaults None
    out = acc.compile_prompts([{"repo": "R", "task": "only", "prompt": "p"}], spec)
    assert out[0]["surface"] == "unknown"
    assert out[0]["complexity"] == "moderate"
    assert out[0]["language_hint"] is None


def test_compile_prompts_tasks_do_not_alias_one_signal_dict():
    # Each task gets its OWN copy of the signal fields — mutating one must not bleed to another.
    spec = AcceptanceSpec(
        "g",
        (AcceptanceCriterion("c1", "2 + 3 shows 5", "behavior", ""),),
        build_plan={"surface": "web", "language_hint": None, "complexity": "simple", "components": []},
    )
    out = acc.compile_prompts(
        [{"repo": "R", "task": "f1", "prompt": "p1"}, {"repo": "R", "task": "f2", "prompt": "p2"}], spec
    )
    out[0]["surface"] = "MUTATED"
    assert out[1]["surface"] == "web"  # sibling untouched


# ---- the PLAN preview "Building this as:" line (display-only) --------------


def test_preview_shows_building_this_as_for_known_surface():
    spec = AcceptanceSpec(
        "a rocket calculator",
        (AcceptanceCriterion("c1", "2 + 3 shows 5", "behavior", ""),),
        build_plan={"surface": "desktop-gui", "language_hint": None, "complexity": "moderate", "components": []},
    )
    out = acc.render_criteria_preview(spec, ecosystem="dotnet")
    assert "Building this as: a Windows desktop app." in out
    # it sits near the top, above the acceptance criteria
    assert out.index("Building this as:") < out.index("2 + 3 shows 5")


def test_preview_building_this_as_maps_each_surface():
    cases = {
        "web": "a web app",
        "mobile": "an Android app",
        "command-line": "a command-line tool",
        "automation": "a system-automation script",
        "library": "a code library / script",
    }
    for surface, friendly in cases.items():
        spec = AcceptanceSpec(
            "g", (AcceptanceCriterion("c1", "it builds", "build", ""),),
            build_plan={"surface": surface, "language_hint": None, "complexity": "moderate", "components": []},
        )
        out = acc.render_criteria_preview(spec, ecosystem="python")
        assert f"Building this as: {friendly}." in out


def test_preview_omits_line_for_unknown_surface():
    spec = AcceptanceSpec(
        "a thing", (AcceptanceCriterion("c1", "it builds", "build", ""),),
        build_plan={"surface": "unknown", "language_hint": None, "complexity": "moderate", "components": []},
    )
    out = acc.render_criteria_preview(spec, ecosystem="python")
    assert "Building this as:" not in out


def test_preview_omits_line_when_no_build_plan():
    # No build_plan (None) -> no line (and the preview is byte-identical to the pre-#674 output
    # for a no-build_plan spec — every existing caller).
    spec = AcceptanceSpec("a thing", (AcceptanceCriterion("c1", "it builds", "build", ""),))
    out = acc.render_criteria_preview(spec, ecosystem="python")
    assert "Building this as:" not in out


# ---- generate_plan: the end-to-end PLAN -> spec + threading + preview ------


def test_generate_plan_emits_build_plan_threads_it_and_previews_it(tmp_path):
    # The whole increment-1 path with a fake 14B: surface lands on the spec, threads onto the
    # task object (single feature folds), and the preview shows the friendly line.
    projects = tmp_path / "projects"
    repo = _git_repo(projects)
    gen = _fake_model(
        tasks_json=json.dumps([{"task": "add-calc", "prompt": "build a calc"}]),
        criteria_json=json.dumps([{"text": "2 + 3 shows 5", "tier": "behavior", "check": ""}]),
        build_plan_json=_GOOD_BUILD_PLAN,
    )
    res = acc.generate_plan("a rocket calculator", repo, generate_fn=gen, projects_dir=projects)
    assert res.ok
    assert res.spec.build_plan["surface"] == "desktop-gui"
    assert res.spec.build_plan["complexity"] == "complex"
    # threaded onto the (single, folded) task object
    assert res.tasks[0]["surface"] == "desktop-gui"
    assert res.tasks[0]["complexity"] == "complex"
    assert res.tasks[0]["language_hint"] is None
    # surfaced in the preview
    preview = acc.render_criteria_preview(res.spec, ecosystem="dotnet", tasks=res.tasks)
    assert "Building this as: a Windows desktop app." in preview


def test_generate_plan_no_build_signal_is_byte_identical_to_today(tmp_path):
    # THE fail-closed regression: a 14B that emits no parseable build-signal object yields the
    # SAME PlanResult.tasks (modulo the always-present fail-closed signal fields) and the SAME
    # preview as before #674 — surface=unknown, no "Building this as" line, plan still succeeds.
    projects = tmp_path / "projects"
    repo = _git_repo(projects)
    gen = _fake_model(
        tasks_json=json.dumps([{"task": "add-calc", "prompt": "build a calc"}]),
        criteria_json=json.dumps([{"text": "2 + 3 shows 5", "tier": "behavior", "check": ""}]),
        build_plan_json="the model rambled and produced no JSON object",
    )
    res = acc.generate_plan("a calculator", repo, generate_fn=gen, projects_dir=projects)
    assert res.ok
    assert res.spec.build_plan is None              # no object -> None (not even an unknown-dict)
    assert res.tasks[0]["surface"] == "unknown"     # threaded fail-closed default
    assert res.tasks[0]["language_hint"] is None
    assert res.tasks[0]["complexity"] == "moderate"
    preview = acc.render_criteria_preview(res.spec, ecosystem="python", tasks=res.tasks)
    assert "Building this as:" not in preview        # no platform line for an unclassified goal


# ---- #886: static-web scaffold-fit (a static ask must NOT get the server seed) --------

_WEB_BUILD_PLAN = json.dumps(
    {"surface": "web", "candidates": [], "language_hint": None,
     "complexity": "simple", "components": []}
)


def test_refine_web_static_narrows_web_on_static_signals():
    # A ``web`` signal + any explicit static/no-backend/single-file phrasing -> ``web-static``
    # (so the fleet seeds a lone static page, not the full-stack skeleton whose fetch hangs).
    base = {"surface": "web", "language_hint": None, "complexity": "simple", "components": []}
    static_goals = [
        "a static site, no build step, one index.html, opens in a browser",
        "a single-file web page with no frameworks",
        "just plain HTML that opens in the browser",
        "a webpage with no server, client-side only",
        "one html file I can double-check — no build tools",
    ]
    for goal in static_goals:
        out = acc._refine_web_static(dict(base), goal)
        assert out["surface"] == "web-static", goal
        # a fresh copy — never mutates the input
        assert base["surface"] == "web"


def test_refine_web_static_leaves_ordinary_server_web_goal_alone():
    # A normal server/full-stack web ask (no static signal) STAYS ``web`` — no over-narrowing.
    base = {"surface": "web", "language_hint": None, "complexity": "moderate", "components": []}
    for goal in [
        "a web app to track expenses with user login and a database",
        "a REST API and a front-end that talks to it",
        "a website for my bakery with an order form",
    ]:
        assert acc._refine_web_static(dict(base), goal)["surface"] == "web", goal


def test_refine_web_static_ignores_server_static_and_serverless():
    # "static assets/files" describes a SERVER serving static content, and "serverless" is a
    # cloud-function backend — neither is a static SITE, so both STAY ``web`` (no mis-narrow).
    base = {"surface": "web", "language_hint": None, "complexity": "moderate", "components": []}
    for goal in [
        "a web app that serves static assets from a CDN",
        "a site that loads static files from the server",
        "a serverless web app on AWS Lambda",
    ]:
        assert acc._refine_web_static(dict(base), goal)["surface"] == "web", goal


def test_refine_web_static_only_touches_web_surface():
    # A static signal on a NON-web surface (or unknown/ambiguous/None) changes nothing.
    for surface in ("unknown", "ambiguous", "desktop-gui", "command-line", "mobile"):
        bp = {"surface": surface, "language_hint": None, "complexity": "simple", "components": []}
        assert acc._refine_web_static(dict(bp), "static, one file, opens in a browser")["surface"] == surface
    assert acc._refine_web_static(None, "static one file") is None


def test_generate_plan_static_web_goal_threads_web_static(tmp_path):
    # END-TO-END #886 regression: a 14B that classifies ``web`` + a goal with static signals ->
    # spec.build_plan surface ``web-static`` AND that value threaded onto the compiled task, so
    # the fleet seeds the static scaffold (no server/fetch) instead of the full-stack skeleton.
    projects = tmp_path / "projects"
    repo = _git_repo(projects)
    gen = _fake_model(
        tasks_json=json.dumps([{"task": "make-page", "prompt": "build the page"}]),
        criteria_json=json.dumps([{"text": "the page shows a greeting", "tier": "behavior", "check": ""}]),
        build_plan_json=_WEB_BUILD_PLAN,
    )
    res = acc.generate_plan(
        "a static one-page site, no build step, one index.html that opens in a browser",
        repo, generate_fn=gen, projects_dir=projects,
    )
    assert res.ok
    assert res.spec.build_plan["surface"] == "web-static"
    assert res.tasks[0]["surface"] == "web-static"      # the fleet reads $t.surface
    # the preview names it as a static page, not a full web app
    preview = acc.render_criteria_preview(res.spec, ecosystem="unknown", tasks=res.tasks)
    assert "single-page web page" in preview


def test_generate_plan_dynamic_web_goal_stays_web(tmp_path):
    # The control: an ordinary web goal (no static signal) still lands ``web`` end-to-end, so the
    # full-stack scaffold is unchanged for the common case (the refiner is opt-in, not a blanket).
    projects = tmp_path / "projects"
    repo = _git_repo(projects)
    gen = _fake_model(
        tasks_json=json.dumps([{"task": "make-app", "prompt": "build the app"}]),
        criteria_json=json.dumps([{"text": "it lists items", "tier": "behavior", "check": ""}]),
        build_plan_json=_WEB_BUILD_PLAN,
    )
    res = acc.generate_plan(
        "a web app to track my expenses with a login", repo, generate_fn=gen, projects_dir=projects,
    )
    assert res.spec.build_plan["surface"] == "web"
    assert res.tasks[0]["surface"] == "web"


def test_web_static_friendly_surface_and_task_threading():
    # web-static renders a distinct friendly line and threads through _task_build_fields intact
    # (it is a real, valid surface — never coerced to unknown like the ambiguous sentinel).
    spec = AcceptanceSpec(
        "g", (AcceptanceCriterion("c1", "it builds", "build", ""),),
        build_plan={"surface": "web-static", "language_hint": None, "complexity": "simple", "components": []},
    )
    out = acc.render_criteria_preview(spec, ecosystem="unknown")
    assert "Building this as: a single-page web page (opens straight in a browser)." in out
    threaded = acc.compile_prompts([{"repo": "R", "task": "only", "prompt": "p"}], spec)
    assert threaded[0]["surface"] == "web-static"


def test_build_plan_emission_schema_surface_enum_excludes_web_static():
    # The model's build-signal grammar enum stays the pre-#886 set — web-static is a deterministic
    # refiner output, never a model emission, so the schema (and its byte-identity) is unchanged.
    schema = acc.build_plan_emission_json_schema()
    surface_enum = schema["properties"]["surface"]["enum"]
    assert "web-static" not in surface_enum
    assert surface_enum == sorted(
        {"desktop-gui", "web", "mobile", "command-line", "automation", "library",
         "unknown", "ambiguous"}
    )
    # web-static is also never offered as a platform-fork candidate
    assert "web-static" not in schema["properties"]["candidates"]["items"]["enum"]


# ---- #888: honest coverage disclosure on New-Project (fresh-scaffold) dispatches -------


def test_scaffold_gated_ecosystem_maps_only_gated_scaffolds():
    def bp(surface, hint=None):
        return {"surface": surface, "language_hint": hint, "complexity": "simple", "components": []}
    assert acc.scaffold_gated_ecosystem(bp("web")) == "node"
    assert acc.scaffold_gated_ecosystem(bp("command-line")) == "python"       # house default
    assert acc.scaffold_gated_ecosystem(bp("command-line", "node")) == "node"
    assert acc.scaffold_gated_ecosystem(bp("library")) == "python"
    # non-gated scaffolds (or no signal) -> "" (the honest warning stands)
    for surface in ("desktop-gui", "mobile", "automation", "web-static", "unknown", "ambiguous"):
        assert acc.scaffold_gated_ecosystem(bp(surface)) == "", surface
    assert acc.scaffold_gated_ecosystem(bp("command-line", "dotnet")) == ""
    assert acc.scaffold_gated_ecosystem(None) == ""


def test_repo_will_scaffold_detects_fresh_vs_existing(tmp_path):
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    (fresh / "README.md").write_text("# hi", encoding="utf-8")
    assert acc.repo_will_scaffold(fresh) is True                  # README-only shell -> scaffolds
    (fresh / "package.json").write_text("{}", encoding="utf-8")
    assert acc.repo_will_scaffold(fresh) is False                 # a manifest -> no seed
    nested = tmp_path / "nested"
    (nested / "src").mkdir(parents=True)
    (nested / "src" / "App.csproj").write_text("<Project/>", encoding="utf-8")
    assert acc.repo_will_scaffold(nested) is False                # one-level-deep marker counts
    # MINOR-2 (reviewer-886-888): the fleet's $hasProj is -Recurse, so a marker buried >=2 dirs
    # deep with NO root manifest (a monorepo shape) ALSO makes the fleet skip seeding. A shallow
    # check would return True here and the card would over-claim "checks will run" for a scaffold
    # that never runs — so repo_will_scaffold must match $hasProj recursively.
    monorepo = tmp_path / "monorepo"
    (monorepo / "packages" / "app").mkdir(parents=True)
    (monorepo / "README.md").write_text("# monorepo", encoding="utf-8")
    (monorepo / "packages" / "app" / "package.json").write_text("{}", encoding="utf-8")
    assert acc.repo_will_scaffold(monorepo) is False              # deep marker, no root -> no seed
    # an existing repo whose contents defeat detection (cpp marker) -> NOT a scaffold target
    cpp = tmp_path / "cpp"
    cpp.mkdir()
    (cpp / "CMakeLists.txt").write_text("cmake_minimum_required(VERSION 3.10)", encoding="utf-8")
    assert acc.repo_will_scaffold(cpp) is False


def test_preview_unknown_ecosystem_with_gated_scaffold_states_the_truth():
    # #888: detection was blind (empty shell) but the run WILL scaffold a node/python project, so
    # the card states the checks WILL run — NOT the false "couldn't tell the language" warning.
    spec = AcceptanceSpec("a page", (AcceptanceCriterion("c1", "it builds", "build", ""),))
    out = acc.render_criteria_preview(spec, ecosystem="unknown", scaffold_ecosystem="node")
    assert "WILL run" in out
    assert "JavaScript (Node)" in out
    assert "couldn't tell this project's language" not in out
    py = acc.render_criteria_preview(spec, ecosystem="unknown", scaffold_ecosystem="python")
    assert "WILL run" in py and "Python" in py


def test_preview_unknown_ecosystem_without_scaffold_preserves_warning_byte_for_byte():
    # No scaffold ecosystem (unknown surface / existing repo / non-gated scaffold) -> the honest
    # warning is preserved EXACTLY (byte-for-byte with the pre-#888 default caller).
    spec = AcceptanceSpec("a thing", (AcceptanceCriterion("c1", "it builds", "build", ""),))
    default = acc.render_criteria_preview(spec, ecosystem="unknown")
    explicit_empty = acc.render_criteria_preview(spec, ecosystem="unknown", scaffold_ecosystem="")
    assert default == explicit_empty
    assert "couldn't tell this project's language" in default
    # a non-gated scaffold ecosystem (e.g. web-static resolves to "") also keeps the warning
    assert "WILL run" not in default


def test_preview_scaffold_ecosystem_ignored_when_detection_succeeded():
    # scaffold_ecosystem is a fallback for the BLIND (unknown) case ONLY; a repo whose ecosystem
    # detected as dotnet still gets the dotnet caveat, never the node/python "will run" line.
    spec = AcceptanceSpec("a C# app", (AcceptanceCriterion("c1", "2+3=5", "behavior", ""),))
    out = acc.render_criteria_preview(spec, ecosystem="dotnet", scaffold_ecosystem="node")
    assert "does not run .NET tests" in out
    assert "WILL run" not in out


def test_generate_plan_seeds_oracle_for_python_single_feature(tmp_path):
    # #690 end-to-end: a single PYTHON feature task + a valid 14B oracle -> the lone task is told
    # to code against the seeded, protected file (NOT to write its own tests) and carries the
    # oracle code + path so the fleet can seed it into every best-of-N candidate + restore it.
    projects = tmp_path / "projects"
    repo = _git_repo(projects)
    gen = _fake_model(
        tasks_json=json.dumps([{"task": "add-days", "prompt": "Implement add_days(y,m,d,n)"}]),
        criteria_json=json.dumps([{"text": "Feb 28 + 1 is Mar 1 in 2024", "tier": "behavior", "check": ""}]),
        build_plan_json=_PY_BUILD_PLAN,
        oracle_py=_ORACLE_PY,
    )
    res = acc.generate_plan("calendar math in python", repo, generate_fn=gen, projects_dir=projects)
    assert res.ok and len(res.tasks) == 1
    only = res.tasks[0]
    assert only["acceptance_test_code"] == _ORACLE_PY
    assert only["acceptance_test_path"] == acc.ACCEPTANCE_ORACLE_PATH
    assert "DO NOT EDIT" in only["prompt"]
    assert "Write automated tests" not in only["prompt"]            # codes against the oracle instead


def test_generate_plan_seeds_node_oracle_for_node_single_feature(tmp_path):
    # #697 end-to-end: a single NODE feature task + a valid 14B node:test oracle -> the lone task
    # codes against the seeded, protected .mjs file (NOT its own tests) and carries the node code
    # + the .mjs path so the fleet seeds it into every best-of-N candidate + restores it. The
    # per-task oracle only fires for len==1, so this exercises the single-task node shape.
    projects = tmp_path / "projects"
    repo = _git_repo(projects)
    gen = _fake_model(
        tasks_json=json.dumps([{"task": "add-days", "prompt": "Implement addDays(y,m,d,n)"}]),
        criteria_json=json.dumps([{"text": "Feb 28 + 1 is Mar 1 in 2024", "tier": "behavior", "check": ""}]),
        build_plan_json=_NODE_BUILD_PLAN,
        oracle_node=_ORACLE_NODE,
    )
    res = acc.generate_plan("calendar math in node", repo, generate_fn=gen, projects_dir=projects)
    assert res.ok and len(res.tasks) == 1
    only = res.tasks[0]
    assert only["acceptance_test_code"] == _ORACLE_NODE
    assert only["acceptance_test_path"] == acc.ACCEPTANCE_ORACLE_PATH_NODE
    assert only["language_hint"] == "node"                          # build-signal threaded through
    assert "DO NOT EDIT" in only["prompt"] and "node --test" in only["prompt"]
    assert "Write automated tests" not in only["prompt"]            # codes against the oracle instead


def test_generate_plan_node_oracle_junk_falls_back_to_folded_tests(tmp_path):
    # [kill] a node goal whose 14B oracle is JUNK (no node:test import) falls back to today's
    # fold-the-tests-in behavior — never seeds an empty/garbage .mjs oracle. node IS behavior-gated,
    # so the folded test block is still added (unlike a build-only ecosystem).
    projects = tmp_path / "projects"
    repo = _git_repo(projects)
    gen = _fake_model(
        tasks_json=json.dumps([{"task": "add-days", "prompt": "Implement addDays"}]),
        criteria_json=json.dumps([{"text": "Feb 28 + 1 is Mar 1 in 2024", "tier": "behavior", "check": ""}]),
        build_plan_json=_NODE_BUILD_PLAN,
        oracle_node="console.log('not a test at all')",             # junk -> '' -> fall back
    )
    res = acc.generate_plan("calendar math in node", repo, generate_fn=gen, projects_dir=projects)
    assert res.ok and len(res.tasks) == 1
    assert "acceptance_test_code" not in res.tasks[0]               # no oracle stamped
    assert "Write automated tests" in res.tasks[0]["prompt"]        # today's folded behavior
    assert "Feb 28 + 1 is Mar 1 in 2024" in res.tasks[0]["prompt"]


def test_generate_plan_oracle_junk_falls_back_to_folded_tests(tmp_path):
    # [kill] a python goal whose 14B oracle is JUNK (no test function) falls back to today's
    # fold-the-tests-in behavior, byte-for-byte — never seeds an empty/garbage oracle.
    projects = tmp_path / "projects"
    repo = _git_repo(projects)
    gen = _fake_model(
        tasks_json=json.dumps([{"task": "add-days", "prompt": "Implement add_days"}]),
        criteria_json=json.dumps([{"text": "Feb 28 + 1 is Mar 1 in 2024", "tier": "behavior", "check": ""}]),
        build_plan_json=_PY_BUILD_PLAN,
        oracle_py="not python at all (((",                          # junk -> '' -> fall back
    )
    res = acc.generate_plan("calendar math in python", repo, generate_fn=gen, projects_dir=projects)
    assert res.ok and len(res.tasks) == 1
    assert "acceptance_test_code" not in res.tasks[0]               # no oracle stamped
    assert "Write automated tests" in res.tasks[0]["prompt"]        # today's folded behavior
    assert "Feb 28 + 1 is Mar 1 in 2024" in res.tasks[0]["prompt"]


def test_generate_plan_no_oracle_for_non_python_single_feature(tmp_path):
    # A non-python single feature (here dotnet) never seeds an oracle; for a build-only ecosystem
    # the test block is also skipped (today's behavior) -> no acceptance_test_* keys, no test block.
    projects = tmp_path / "projects"
    repo = _git_repo(projects)
    dotnet_plan = json.dumps({"surface": "desktop-gui", "candidates": [], "language_hint": "dotnet",
                              "complexity": "simple", "components": []})
    gen = _fake_model(
        tasks_json=json.dumps([{"task": "app", "prompt": "build a C# app"}]),
        criteria_json=json.dumps([{"text": "prints 20 numbers", "tier": "behavior", "check": ""}]),
        build_plan_json=dotnet_plan,
        oracle_py=_ORACLE_PY,            # offered, but must be IGNORED for dotnet
    )
    res = acc.generate_plan("a C# app", repo, generate_fn=gen, projects_dir=projects)
    assert res.ok and len(res.tasks) == 1
    assert "acceptance_test_code" not in res.tasks[0]
    assert "DO NOT EDIT" not in res.tasks[0]["prompt"]


def test_generate_plan_build_signal_model_error_is_non_fatal(tmp_path):
    # A RAISING build-signal call must not crash the plan (fail-closed AND non-blocking) — the
    # tasks + criteria are unaffected and build_plan is None.
    projects = tmp_path / "projects"
    repo = _git_repo(projects)

    def gen(prompt: str) -> str:
        if "Classify what KIND of software" in prompt:
            raise RuntimeError("model blew up classifying the surface")
        if "ACCEPTANCE CRITERIA" in prompt:
            return json.dumps([{"text": "2 + 3 shows 5", "tier": "behavior", "check": ""}])
        return json.dumps([{"task": "add-calc", "prompt": "build a calc"}])

    res = acc.generate_plan("a calculator", repo, generate_fn=gen, projects_dir=projects)
    assert res.ok
    assert res.spec.build_plan is None
    assert any("2 + 3 shows 5" in t["prompt"] for t in res.tasks)     # plan still produced
    assert res.tasks[0]["surface"] == "unknown"                       # fail-closed default still threaded


def test_generate_plan_build_signal_survives_the_smoke_floor(tmp_path):
    # The collapsed-test-intent smoke floor rebuilds the spec; the build-signal must survive
    # that copy (otherwise a goal that triggers the floor would silently lose its signal).
    # Drives the floor AND the build-signal in one plan.
    projects = tmp_path / "projects"
    repo = _git_repo(projects)
    gen = _fake_model(
        tasks_json=json.dumps([
            {"task": "implement-thing", "prompt": "build the thing"},
            {"task": "test-thing", "prompt": "test the thing"},  # collapsed -> test intent
        ]),
        criteria_json=json.dumps([{"text": "the project builds", "tier": "build", "check": ""}]),
        build_plan_json=json.dumps({"surface": "library", "language_hint": "python", "complexity": "simple"}),
    )
    res = acc.generate_plan("build a thing", repo, generate_fn=gen, projects_dir=projects)
    assert res.ok
    assert any(c.tier == acc.TIER_SMOKE for c in res.spec.criteria)         # the floor fired ...
    assert res.spec.build_plan == {                                          # ... and the signal survived
        "surface": "library", "language_hint": "python", "complexity": "simple", "components": [],
    }
    assert res.tasks[0]["surface"] == "library"                             # threaded through the floor copy


def test_generate_plan_build_signal_survives_assumptions(tmp_path):
    # Both the assumptions rebuild AND the build-signal fire in one plan; the spec must carry
    # BOTH at the end (the assumptions rebuild must not clobber the signal, nor vice-versa).
    projects = tmp_path / "projects"
    repo = _git_repo(projects)
    gen = _fake_model(
        tasks_json=json.dumps([{"task": "add-calc", "prompt": "build a calc"}]),
        criteria_json=json.dumps([{"text": "2 + 3 shows 5", "tier": "behavior", "check": ""}]),
        assumptions_json=json.dumps(["Assumed a normal resizable window"]),
        build_plan_json=json.dumps({"surface": "desktop-gui", "complexity": "moderate"}),
    )
    res = acc.generate_plan("a calculator", repo, generate_fn=gen, projects_dir=projects)
    assert res.ok
    assert res.spec.assumptions == ("Assumed a normal resizable window",)
    assert res.spec.build_plan["surface"] == "desktop-gui"
    assert res.tasks[0]["surface"] == "desktop-gui"


# ===========================================================================
# Confidence-gated clarifying question (ask-when-ambiguous) — increment 4, #677
# ===========================================================================
#
# The 14B FLAGS ambiguity (surface=ambiguous + candidates); the SYSTEM owns the curated
# question via _CLARIFY_DECISION_MAP and maps each answer deterministically to a real
# surface. The load-bearing tests are the GATING kill-tests: a CLEAR surface asks NOTHING
# (resolve_clarifying_question is None) and the parsed plan is byte-identical to today, so a
# wrong/absent ambiguity signal can never change the existing flow. Every assertion is a
# behavioural one paired (in spirit) with a mutation that drives it RED.


# ---- _validate_candidates (the fail-closed real-surface filter) -----------


def test_validate_candidates_keeps_only_real_surfaces():
    # unknown/ambiguous sentinels + a garbage surface are dropped; real ones survive,
    # normalised + order-preserved.
    got = acc._validate_candidates(
        ["desktop-gui", "web", "unknown", "ambiguous", "quantum", "mobile"]
    )
    assert got == ["desktop-gui", "web", "mobile"]


def test_validate_candidates_normalises_and_dedupes():
    got = acc._validate_candidates([" Desktop-GUI ", "WEB", "web", "desktop-gui"])
    assert got == ["desktop-gui", "web"]


def test_validate_candidates_non_list_and_non_strings_are_empty_or_dropped():
    assert acc._validate_candidates("desktop-gui") == []   # a bare string is not a list
    assert acc._validate_candidates(None) == []
    assert acc._validate_candidates([1, {"x": 1}, None, "web"]) == ["web"]  # non-strings dropped


def test_validate_candidates_caps_small():
    # All 6 real surfaces offered, but the cap (DEFAULT_MAX_CANDIDATES=4) holds.
    raw = ["desktop-gui", "web", "mobile", "command-line", "automation", "library"]
    got = acc._validate_candidates(raw)
    assert len(got) == acc.DEFAULT_MAX_CANDIDATES == 4
    assert got == ["desktop-gui", "web", "mobile", "command-line"]


# ---- _parse_build_plan: candidates + the fail-closed coupling -------------


def test_parse_build_plan_ambiguous_with_candidates_kept():
    got = acc._parse_build_plan(json.dumps(
        {"surface": "ambiguous", "candidates": ["desktop-gui", "web", "mobile"]}
    ))
    assert got["surface"] == "ambiguous"
    assert got["candidates"] == ["desktop-gui", "web", "mobile"]


def test_parse_build_plan_ambiguous_under_two_candidates_coerces_to_unknown():
    # The fail-closed coupling: an ambiguous flag with <2 real candidates is a non-fork
    # (the model hedged) -> coerce surface to unknown and drop candidates -> today's behavior.
    one = acc._parse_build_plan(json.dumps({"surface": "ambiguous", "candidates": ["web"]}))
    assert one["surface"] == "unknown" and "candidates" not in one
    zero = acc._parse_build_plan(json.dumps({"surface": "ambiguous", "candidates": []}))
    assert zero["surface"] == "unknown" and "candidates" not in zero
    # candidates that all filter out (sentinels/garbage) -> also <2 -> unknown
    junk = acc._parse_build_plan(json.dumps(
        {"surface": "ambiguous", "candidates": ["unknown", "quantum", "ambiguous"]}
    ))
    assert junk["surface"] == "unknown" and "candidates" not in junk


def test_parse_build_plan_tolerates_stray_trailing_brace():
    # The 14B occasionally appends a stray closing brace (e.g. ``{...}}``); the balanced-brace
    # extractor (_first_json_object) must still recover the object -- the old greedy ``\{.*\}``
    # regex over-grabbed the extra brace into invalid JSON and lost the whole build-signal
    # (fail-closed, but a needless miss -- it cost the 'landing page' goal in the live probe).
    bp = acc._parse_build_plan('{"surface": "web", "candidates": []}}')
    assert bp is not None and bp["surface"] == "web"
    # nested components must not confuse the depth-aware extractor
    nested = acc._parse_build_plan(
        '{"surface": "desktop-gui", "complexity": "simple",'
        ' "components": [{"name": "core", "kind": "testable-logic"}]}}'
    )
    assert nested is not None and nested["surface"] == "desktop-gui"
    assert nested["components"] == [{"name": "core", "kind": "testable-logic"}]


def test_first_json_object_extracts_first_balanced_object():
    # String-aware + depth-aware: braces inside double-quoted strings are ignored; stop at the
    # first balanced close (so a stray trailing brace is excluded).
    assert acc._first_json_object('prefix {"a": "}{"} rest {"b": 2}') == '{"a": "}{"}'
    assert acc._first_json_object("no braces here") is None


def test_parse_build_plan_nonambiguous_surface_forces_no_candidates_key():
    # A CLEAR surface never carries a fork — candidates forced empty AND, to stay byte-
    # identical to today's 4-key output, the key is ABSENT (not present-as-[]). Even if the
    # model erroneously emitted candidates on a clear surface, they are dropped.
    got = acc._parse_build_plan(json.dumps(
        {"surface": "desktop-gui", "candidates": ["web", "mobile"]}
    ))
    assert got["surface"] == "desktop-gui"
    assert "candidates" not in got  # backward-compat shape: 4 keys exactly
    assert set(got.keys()) == {"surface", "language_hint", "complexity", "components"}


def test_parse_build_plan_ambiguous_candidates_capped_and_deduped():
    got = acc._parse_build_plan(json.dumps({
        "surface": "ambiguous",
        "candidates": ["web", "web", "desktop-gui", "mobile", "command-line", "library"],
    }))
    # deduped, capped at 4, order preserved
    assert got["candidates"] == ["web", "desktop-gui", "mobile", "command-line"]


# ---- the decision-map mapping (each candidate-set -> the right question/options) ---


def test_decision_map_three_way_platform():
    bp = {"surface": "ambiguous", "candidates": ["desktop-gui", "web", "mobile"]}
    q = acc.resolve_clarifying_question(bp)
    assert q is not None
    assert q["question"] == "Where will you mainly use this?"
    assert q["options"] == [
        {"label": "On this computer", "surface": "desktop-gui"},
        {"label": "In a web browser", "surface": "web"},
        {"label": "On a phone", "surface": "mobile"},
    ]


@pytest.mark.parametrize("candidates, expected", [
    (["desktop-gui", "web"], [("On this computer", "desktop-gui"), ("In a web browser", "web")]),
    (["desktop-gui", "mobile"], [("On this computer", "desktop-gui"), ("On a phone", "mobile")]),
    (["web", "mobile"], [("In a web browser", "web"), ("On a phone", "mobile")]),
])
def test_decision_map_two_way_platform_subsets(candidates, expected):
    # Each 2-way subset offers exactly its two options, in the canonical order, and never a
    # platform the 14B did not flag.
    bp = {"surface": "ambiguous", "candidates": candidates}
    q = acc.resolve_clarifying_question(bp)
    assert q is not None
    assert [(o["label"], o["surface"]) for o in q["options"]] == expected


def test_decision_map_is_order_independent():
    # The candidate-set is keyed on a frozenset, so the 14B may list the platforms in any
    # order — the question + options are the same.
    a = acc.resolve_clarifying_question({"surface": "ambiguous", "candidates": ["mobile", "web", "desktop-gui"]})
    b = acc.resolve_clarifying_question({"surface": "ambiguous", "candidates": ["desktop-gui", "web", "mobile"]})
    assert a == b


def test_resolve_returns_fresh_copy_not_the_module_map():
    # A caller must not be able to mutate the module-level curated map through the result.
    bp = {"surface": "ambiguous", "candidates": ["web", "mobile"]}
    q = acc.resolve_clarifying_question(bp)
    q["options"].append({"label": "HACKED", "surface": "desktop-gui"})
    q2 = acc.resolve_clarifying_question(bp)
    assert all(o["label"] != "HACKED" for o in q2["options"])  # map untouched


def test_resolve_unmapped_candidate_set_returns_none():
    # An ambiguous fork the curated map has no entry for (e.g. {command-line, library}) yields
    # NO question -> falls through to today's guess+confirm. The map stays SMALL on purpose.
    bp = acc._parse_build_plan(json.dumps(
        {"surface": "ambiguous", "candidates": ["command-line", "library"]}
    ))
    assert bp["surface"] == "ambiguous"  # parsed fine (2 valid candidates)
    assert acc.resolve_clarifying_question(bp) is None  # but no map entry -> no question


# ---- apply_clarification (chosen -> surface; off-list -> unchanged) --------


def test_apply_clarification_valid_choice_sets_surface_clears_candidates():
    bp = {"surface": "ambiguous", "language_hint": None, "complexity": "moderate",
          "components": [], "candidates": ["desktop-gui", "web", "mobile"]}
    refined = acc.apply_clarification(bp, "web")
    assert refined["surface"] == "web"
    assert refined["candidates"] == []
    # the rest is preserved
    assert refined["complexity"] == "moderate" and refined["components"] == []
    # and a resolved plan asks NOTHING further (it now flows like an ordinary clear surface)
    assert acc.resolve_clarifying_question(refined) is None


def test_apply_clarification_off_list_answer_leaves_plan_unchanged():
    # An answer that is not one of the plan's OWN candidates is ignored — the plan stays
    # ambiguous so the caller can re-ask / fall back, never a silent accept of an un-offered
    # surface.
    bp = {"surface": "ambiguous", "language_hint": None, "complexity": "moderate",
          "components": [], "candidates": ["desktop-gui", "web"]}
    for bad in ("mobile", "command-line", "library", "unknown", "ambiguous", "garbage", ""):
        refined = acc.apply_clarification(bp, bad)
        assert refined["surface"] == "ambiguous"
        assert refined["candidates"] == ["desktop-gui", "web"]


def test_apply_clarification_returns_a_copy_never_the_same_object():
    bp = {"surface": "ambiguous", "candidates": ["web", "mobile"]}
    refined = acc.apply_clarification(bp, "web")
    assert refined is not bp
    assert bp["surface"] == "ambiguous"  # input not mutated
    # even the off-list path returns a distinct object
    other = acc.apply_clarification(bp, "desktop-gui")
    assert other is not bp


def test_apply_clarification_none_plan_returns_none():
    assert acc.apply_clarification(None, "web") is None
    assert acc.apply_clarification("not-a-dict", "web") is None


# ---- the GATING kill-tests (a clear/absent surface asks NOTHING) ----------


def test_kill_clear_surface_resolves_to_no_question():
    # The headline gate: a CLEAR surface (desktop-gui) -> resolve_clarifying_question is None.
    # Reverting the surface==ambiguous guard in resolve_clarifying_question makes this fail.
    bp = acc._parse_build_plan(json.dumps({"surface": "desktop-gui", "complexity": "moderate"}))
    assert acc.resolve_clarifying_question(bp) is None


def test_kill_unknown_surface_resolves_to_no_question():
    bp = acc._parse_build_plan(json.dumps({"surface": "unknown"}))
    assert acc.resolve_clarifying_question(bp) is None


def test_kill_none_and_no_build_plan_resolve_to_no_question():
    assert acc.resolve_clarifying_question(None) is None
    assert acc.resolve_clarifying_question({}) is None
    assert acc.resolve_clarifying_question("not-a-dict") is None
    # an ambiguous dict with a non-list candidates field is malformed -> no question
    assert acc.resolve_clarifying_question({"surface": "ambiguous", "candidates": "web"}) is None


def test_kill_clear_surface_parse_is_byte_identical_to_today():
    # Backward-compat lock: a non-ambiguous surface parses to the EXACT pre-increment-4
    # 4-key dict (no candidates key) — byte-identical to today. This binds the "additive,
    # only-attach-candidates-when-ambiguous" decision; making candidates unconditional breaks it.
    got = acc._parse_build_plan(_GOOD_BUILD_PLAN)
    assert got == {
        "surface": "desktop-gui",
        "language_hint": None,
        "complexity": "complex",
        "components": [
            {"name": "calculator-core", "kind": "testable-logic"},
            {"name": "ui-shell", "kind": "gui-shell"},
        ],
    }
    assert "candidates" not in got


def test_kill_ambiguous_is_never_a_friendly_preview_line():
    # An ambiguous surface has no single platform to name, so the "Building this as" line is
    # OMITTED (the clarifying question resolves it to a real surface first). A real surface
    # still renders. Binds: ambiguous must NOT be in _SURFACE_FRIENDLY.
    amb = AcceptanceSpec("g", (), build_plan={"surface": "ambiguous", "candidates": ["web", "mobile"]})
    assert acc._friendly_surface(amb) is None
    clear = AcceptanceSpec("g", (), build_plan={"surface": "web"})
    assert acc._friendly_surface(clear) == "a web app"


# ---- the ambiguous signal rides the spec + threads fail-closed ------------


def test_spec_roundtrips_ambiguous_build_plan_with_candidates():
    bp = {"surface": "ambiguous", "language_hint": None, "complexity": "moderate",
          "components": [], "candidates": ["desktop-gui", "web", "mobile"]}
    spec = AcceptanceSpec("g", (AcceptanceCriterion("c1", "it builds", "build", ""),), build_plan=bp)
    restored = AcceptanceSpec.from_dict(spec.to_dict())
    assert restored.build_plan == bp
    assert restored.build_plan["candidates"] == ["desktop-gui", "web", "mobile"]


def test_compile_prompts_unresolved_ambiguous_threads_unknown_to_fleet():
    # Defence-in-depth: an UNRESOLVED ambiguous plan must NEVER send surface=ambiguous to the
    # fleet (it knows nothing about the sentinel). It is coerced to unknown (the safe no-seed
    # path == today's behavior). The normal flow resolves the fork first; this is the fallback.
    spec = AcceptanceSpec(
        "g", (AcceptanceCriterion("c1", "it builds", "build", ""),),
        build_plan={"surface": "ambiguous", "language_hint": None, "complexity": "moderate",
                    "components": [], "candidates": ["desktop-gui", "web"]},
    )
    out = acc.compile_prompts([{"repo": "R", "task": "only", "prompt": "p"}], spec)
    assert out[0]["surface"] == "unknown"  # never "ambiguous"
    assert out[0]["complexity"] == "moderate"


# ---- end-to-end: an ambiguous goal lands an ambiguous build_plan ----------


def test_generate_plan_ambiguous_build_plan_drives_a_question(tmp_path):
    # The PLAN step: the 14B emits an ambiguous build_plan + candidates; it rides spec.build_plan
    # and resolve_clarifying_question (the coordinator's hook) returns the curated question.
    projects = tmp_path / "projects"
    repo = _git_repo(projects)
    gen = _fake_model(
        tasks_json=json.dumps([{"task": "build-app", "prompt": "build it"}]),
        criteria_json=json.dumps([{"text": "the buttons work", "tier": "behavior", "check": ""}]),
        build_plan_json=json.dumps(
            {"surface": "ambiguous", "candidates": ["desktop-gui", "web", "mobile"], "complexity": "moderate"}
        ),
    )
    res = acc.generate_plan("an app with buttons", repo, generate_fn=gen, projects_dir=projects)
    assert res.ok
    assert res.spec.build_plan["surface"] == "ambiguous"
    assert res.spec.build_plan["candidates"] == ["desktop-gui", "web", "mobile"]
    q = acc.resolve_clarifying_question(res.spec.build_plan)
    assert q is not None and q["question"] == "Where will you mainly use this?"


def test_generate_plan_clear_surface_drives_no_question(tmp_path):
    # The gate, end-to-end: a clear-surface goal lands a clear build_plan and asks NOTHING
    # (today's guess+confirm flow is byte-identical).
    projects = tmp_path / "projects"
    repo = _git_repo(projects)
    gen = _fake_model(
        tasks_json=json.dumps([{"task": "build-app", "prompt": "build it"}]),
        criteria_json=json.dumps([{"text": "the buttons work", "tier": "behavior", "check": ""}]),
        build_plan_json=json.dumps({"surface": "desktop-gui", "complexity": "moderate"}),
    )
    res = acc.generate_plan("a desktop calculator with buttons", repo, generate_fn=gen, projects_dir=projects)
    assert res.ok
    assert res.spec.build_plan["surface"] == "desktop-gui"
    assert acc.resolve_clarifying_question(res.spec.build_plan) is None


# ---- image-asset specs (UC-010 dispatch, SEAM A) -------------------------
#
# The 14B proposes {name, subject, style}; the deterministic ruler owns the slug, the dims,
# the in-repo path, dedup, cap, and the visual-surface gate. Threaded onto every task as
# asset_specs_json ONLY when non-empty (so a no-image goal is byte-identical to today), and
# read back AO-side via decode_asset_specs. All validation is fail-closed (model PROPOSES,
# ruler DISPOSES) — these guards pin each rule so a mutation flips them red.


def test_is_safe_asset_rel_path_accepts_in_tree_png_rejects_escapes():
    assert acc.is_safe_asset_rel_path("public/assets/elephant.png")
    assert acc.is_safe_asset_rel_path("assets/logo.png")
    # rejects: traversal, absolute, drive, UNC, non-.png, empty segment
    assert not acc.is_safe_asset_rel_path("../secret.png")
    assert not acc.is_safe_asset_rel_path("assets/../../etc/x.png")
    assert not acc.is_safe_asset_rel_path("/etc/passwd.png")
    assert not acc.is_safe_asset_rel_path("C:/windows/x.png")
    assert not acc.is_safe_asset_rel_path("\\\\host\\share\\x.png")
    assert not acc.is_safe_asset_rel_path("assets/logo.svg")
    assert not acc.is_safe_asset_rel_path("")


def test_validate_asset_specs_web_elephant_sanitizes_and_places_under_public():
    specs = acc._validate_asset_specs(
        '[{"name":"Elephant!!","subject":"a friendly cartoon elephant waving hello","style":"cartoon"}]',
        surface="web", max_assets=2,
    )
    assert len(specs) == 1
    s = specs[0]
    assert s["name"] == "elephant"                              # sanitized slug
    assert s["target_rel_path"] == "public/assets/elephant.png"  # web -> served dir
    assert s["style"] == "cartoon"
    assert s["width"] == 1024 and s["height"] == 1024            # deterministic dims
    assert s["prompt"] == "a friendly cartoon elephant waving hello"  # prompt == subject


def test_validate_asset_specs_non_visual_surface_is_empty():
    # A CLI/library product never gets image assets (the deterministic gate).
    payload = '[{"name":"x","subject":"a nice picture","style":"cartoon"}]'
    assert acc._validate_asset_specs(payload, surface="command-line", max_assets=2) == ()
    assert acc._validate_asset_specs(payload, surface="library", max_assets=2) == ()
    assert acc._validate_asset_specs(payload, surface="unknown", max_assets=2) == ()


def test_validate_asset_specs_unknown_style_defaults_and_desktop_path():
    specs = acc._validate_asset_specs(
        '[{"name":"logo","subject":"a shield logo","style":"chartreuse-fresco"}]',
        surface="desktop-gui", max_assets=2,
    )
    assert specs[0]["style"] == acc.ASSET_STYLE_DEFAULT == "cartoon"
    assert specs[0]["target_rel_path"] == "assets/logo.png"      # non-web -> assets/


def test_validate_asset_specs_caps_and_dedups_by_target_path():
    big = json.dumps([{"name": f"n{i}", "subject": "a real subject", "style": "illustration"} for i in range(5)])
    assert len(acc._validate_asset_specs(big, surface="web", max_assets=2)) == 2   # cap
    dup = '[{"name":"hero","subject":"aaaa scene","style":"cartoon"},{"name":"hero","subject":"bbbb scene","style":"illustration"}]'
    assert len(acc._validate_asset_specs(dup, surface="web", max_assets=5)) == 1   # same slug -> same path -> one


def test_validate_asset_specs_garbage_is_failclosed():
    assert acc._validate_asset_specs("not json", surface="web", max_assets=2) == ()
    assert acc._validate_asset_specs('{"not":"a list"}', surface="web", max_assets=2) == ()
    assert acc._validate_asset_specs('[{"name":"","subject":"a picture","style":"cartoon"}]', surface="web", max_assets=2) == ()
    assert acc._validate_asset_specs('[{"name":"ok","subject":"ab","style":"cartoon"}]', surface="web", max_assets=2) == ()  # subject < 3 chars
    assert acc._validate_asset_specs('["a string, not an object"]', surface="web", max_assets=2) == ()


def test_coerce_asset_specs_drops_unsafe_path_and_clamps_dims():
    good = [{"name": "e", "prompt": "p", "style": "cartoon", "width": 1024, "height": 1024, "target_rel_path": "assets/e.png"}]
    assert acc._coerce_asset_specs(good) == tuple(good)
    # unsafe target path -> dropped
    assert acc._coerce_asset_specs([{**good[0], "target_rel_path": "../evil.png"}]) == ()
    # bad style -> dropped
    assert acc._coerce_asset_specs([{**good[0], "style": "nope"}]) == ()
    # oversized/undersized dims clamped into [256, 1024]
    clamped = acc._coerce_asset_specs([{**good[0], "width": 9999, "height": 4}])
    assert clamped[0]["width"] == 1024 and clamped[0]["height"] == 256
    assert acc._coerce_asset_specs("not a list") == ()


def test_asset_specs_round_trip_through_spec_to_from_dict():
    specs = acc._validate_asset_specs(
        '[{"name":"elephant","subject":"a friendly cartoon elephant","style":"cartoon"}]',
        surface="web", max_assets=2,
    )
    spec = AcceptanceSpec("g", asset_specs=specs)
    spec2 = AcceptanceSpec.from_dict(spec.to_dict())
    assert spec2.asset_specs == specs


def test_thread_and_decode_asset_specs_identical_across_tasks():
    specs = acc._validate_asset_specs(
        '[{"name":"elephant","subject":"a friendly cartoon elephant","style":"cartoon"}]',
        surface="web", max_assets=2,
    )
    spec = AcceptanceSpec(
        "g",
        (AcceptanceCriterion("c1", "the page loads", "behavior", ""),),
        build_plan={"surface": "web", "language_hint": "node", "complexity": "simple", "components": []},
        asset_specs=specs,
    )
    out = acc.compile_prompts(
        [{"repo": "R", "task": "f1", "prompt": "p1"}, {"repo": "R", "task": "f2", "prompt": "p2"}], spec,
    )
    assert all("asset_specs_json" in t for t in out)
    assert len({t["asset_specs_json"] for t in out}) == 1      # identical across tasks
    assert acc.decode_asset_specs(out) == list(specs)          # round-trips to the AO seam


def test_thread_no_assets_omits_key_byte_identical():
    # A goal with no image assets threads NO asset_specs_json key (today's task dict shape).
    spec = AcceptanceSpec("g", (AcceptanceCriterion("c1", "it builds", "behavior", ""),))  # asset_specs default ()
    out = acc.compile_prompts([{"repo": "R", "task": "only", "prompt": "p"}], spec)
    assert "asset_specs_json" not in out[0]
    assert acc.decode_asset_specs(out) == []


def test_decode_asset_specs_failclosed():
    assert acc.decode_asset_specs([{"repo": "R", "task": "t", "prompt": "p"}]) == []   # no key
    assert acc.decode_asset_specs([{"asset_specs_json": "not json"}]) == []            # bad json
    # an unsafe path in the wire payload is coerced out (defense-in-depth at the seam)
    poisoned = json.dumps([{"name": "e", "prompt": "p", "style": "cartoon", "target_rel_path": "../evil.png"}])
    assert acc.decode_asset_specs([{"asset_specs_json": poisoned}]) == []


def test_asset_specs_from_plan_gates_on_visual_surface():
    calls = []

    def gen(prompt: str) -> str:
        calls.append(prompt)
        return '[{"name":"elephant","subject":"a friendly cartoon elephant","style":"cartoon"}]'

    # web (visual) -> the model is asked, one asset returned
    got = acc._asset_specs_from_plan("goal", {"surface": "web"}, generate_fn=gen, max_assets=2)
    assert len(got) == 1 and calls                            # generate_fn WAS called
    # non-visual / None -> the model is NOT asked (no wasted GPU call), no assets
    calls.clear()
    assert acc._asset_specs_from_plan("goal", {"surface": "library"}, generate_fn=gen, max_assets=2) == ()
    assert acc._asset_specs_from_plan("goal", None, generate_fn=gen, max_assets=2) == ()
    assert not calls


def test_generate_plan_emits_and_threads_asset_specs_for_web(tmp_path):
    projects = tmp_path / "projects"
    repo = _git_repo(projects)
    gen = _fake_model(
        tasks_json=json.dumps([{"task": "build-page", "prompt": "build the page"}]),
        criteria_json=json.dumps([{"text": "the page shows the elephant", "tier": "behavior", "check": ""}]),
        build_plan_json=json.dumps({"surface": "web", "complexity": "simple"}),
        asset_specs_json=json.dumps([{"name": "elephant", "subject": "a friendly cartoon elephant waving hello", "style": "cartoon"}]),
    )
    res = acc.generate_plan("a webpage with a cartoon elephant saying hello", repo, generate_fn=gen, projects_dir=projects)
    assert res.ok
    assert len(res.spec.asset_specs) == 1
    assert res.spec.asset_specs[0]["target_rel_path"] == "public/assets/elephant.png"
    # threaded onto the (single, folded) task, and decodable at the AO seam
    assert "asset_specs_json" in res.tasks[0]
    decoded = acc.decode_asset_specs(res.tasks)
    assert decoded[0]["name"] == "elephant" and decoded[0]["style"] == "cartoon"


def test_generate_plan_no_assets_for_non_visual_surface_is_byte_identical(tmp_path):
    # A library goal never reaches the asset call -> no asset_specs, no asset_specs_json key.
    projects = tmp_path / "projects"
    repo = _git_repo(projects)
    gen = _fake_model(
        tasks_json=json.dumps([{"task": "build-lib", "prompt": "build the lib"}]),
        criteria_json=json.dumps([{"text": "it imports", "tier": "behavior", "check": ""}]),
        build_plan_json=json.dumps({"surface": "library", "complexity": "simple"}),
        asset_specs_json=json.dumps([{"name": "x", "subject": "should never be used", "style": "cartoon"}]),
    )
    res = acc.generate_plan("a python date library", repo, generate_fn=gen, projects_dir=projects)
    assert res.ok
    assert res.spec.asset_specs == ()
    assert "asset_specs_json" not in res.tasks[0]


def test_generate_plan_asset_spec_model_error_is_non_fatal(tmp_path):
    # The asset-spec call raising must not crash the plan (fail-closed, non-blocking).
    projects = tmp_path / "projects"
    repo = _git_repo(projects)

    def gen(prompt: str) -> str:
        if "image assets this product should DISPLAY" in prompt:
            raise RuntimeError("model blew up on the asset call")
        if "ACCEPTANCE CRITERIA" in prompt:
            return json.dumps([{"text": "the page loads", "tier": "behavior", "check": ""}])
        if "Classify what KIND of software" in prompt:
            return json.dumps({"surface": "web", "complexity": "simple"})
        if "PRODUCT assumptions" in prompt or "pytest test file" in prompt:
            return "[]"
        return json.dumps([{"task": "build-page", "prompt": "build it"}])

    res = acc.generate_plan("a webpage with a picture", repo, generate_fn=gen, projects_dir=projects)
    assert res.ok
    assert res.spec.asset_specs == ()
    assert "asset_specs_json" not in res.tasks[0]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
