"""Tests for #743 — grammar-constrained emission for the REMAINING plan-time 14B calls.

W2 (#740) grammar-constrained the decompose/plan JSON via the injected
``structured_generate_fn(prompt, json_schema_text)`` hook (the #718 xgrammar
``StructuredOutputConfig`` adapter seam). #743 extends the SAME hook — not a second
grammar pathway — to the other four structured calls in the PLAN sequence: acceptance
criteria, product assumptions, the build-signal (incl. the ambiguous-platform fork),
and image-asset specs.

Two contracts are locked here, per call:

  * GRAMMAR-FIRST: a working hook serves the emission and the free-text path never
    fires for that prompt.
  * NEVER-A-NEW-FAILURE-MODE: hook absent / raising / empty / unusable ⇒ the free-text
    parse + fallback path runs UNCHANGED (results identical to the pre-#743 behavior).

Model calls are faked throughout (offline — the live 14B grammar proof rides the next
live dispatch)."""

from __future__ import annotations

import json

from shared.fleet import acceptance as acc
from shared.fleet import decompose as dc


# ---------------------------------------------------------------------------
# Fixtures — prompt-routing fakes (mirror tests/integration/test_acceptance.py)
# ---------------------------------------------------------------------------

#: Each PLAN prompt's unique routing marker (asserted against the real templates below).
_MARKER_DECOMPOSE = "decomposing a software change request"
_MARKER_CRITERIA = "ACCEPTANCE CRITERIA"
_MARKER_ASSUMPTIONS = "PRODUCT assumptions"
_MARKER_BUILD_PLAN = "Classify what KIND of software"
_MARKER_ASSETS = "image assets this product should DISPLAY"

_TASKS_JSON = json.dumps([
    {"task": "storage-module", "prompt": "Build the storage module."},
    {"task": "add-command", "prompt": "Build the add command."},
])
_ONE_TASK_JSON = json.dumps([{"task": "build-page", "prompt": "Build the page."}])
_CRITERIA_JSON = json.dumps([
    {"text": "the project builds", "tier": "build", "check": ""},
    {"text": "2 + 3 shows 5", "tier": "behavior", "check": "assert add(2,3)==5"},
])
_ASSUMPTIONS_JSON = json.dumps(["Assumed decimals are supported"])
_WEB_BUILD_PLAN_JSON = json.dumps({
    "surface": "web", "candidates": [], "language_hint": None,
    "complexity": "simple", "components": [],
})
_AMBIGUOUS_BUILD_PLAN_JSON = json.dumps({
    "surface": "ambiguous", "candidates": ["desktop-gui", "web", "mobile"],
    "language_hint": None, "complexity": "simple", "components": [],
})
_ASSETS_JSON = json.dumps([
    {"name": "hero", "subject": "a warm bakery storefront", "style": "illustration"},
])


def _repo(tmp_path):
    proj = tmp_path / "projects"
    (proj / "myapp" / ".git").mkdir(parents=True, exist_ok=True)
    return proj, "myapp"


def _route(prompt: str, table: dict) -> str:
    if _MARKER_CRITERIA in prompt:
        return table["criteria"]
    if _MARKER_ASSUMPTIONS in prompt:
        return table["assumptions"]
    if _MARKER_BUILD_PLAN in prompt:
        return table["build_plan"]
    if _MARKER_ASSETS in prompt:
        return table["assets"]
    return table["tasks"]


def _free_gen(calls: list, **overrides):
    """A recording free-text generate_fn with junk defaults (so any leak of a call the
    grammar should have served is VISIBLE in the plan result)."""
    table = {"tasks": _TASKS_JSON, "criteria": _CRITERIA_JSON,
             "assumptions": "[]", "build_plan": "", "assets": "[]"}
    table.update(overrides)

    def gen(prompt: str) -> str:
        calls.append(prompt)
        return _route(prompt, table)

    return gen


def _structured_gen(calls: list, **overrides):
    """A recording structured hook serving every PLAN emission grammar-constrained."""
    table = {"tasks": _TASKS_JSON, "criteria": _CRITERIA_JSON,
             "assumptions": _ASSUMPTIONS_JSON, "build_plan": _WEB_BUILD_PLAN_JSON,
             "assets": _ASSETS_JSON}
    table.update(overrides)

    def gen(prompt: str, schema_text: str) -> str:
        # The hook contract: the second argument is real JSON-schema TEXT.
        schema = json.loads(schema_text)
        assert isinstance(schema, dict) and "type" in schema
        calls.append((prompt, schema))
        return _route(prompt, table)

    return gen


# ---------------------------------------------------------------------------
# Routing markers — pinned to the REAL templates (a template rewrite that breaks
# the fakes' routing must fail loudly here, not silently mis-route the tests)
# ---------------------------------------------------------------------------


def test_routing_markers_match_the_real_templates():
    assert _MARKER_DECOMPOSE in dc._DECOMPOSE_TEMPLATE
    assert _MARKER_CRITERIA in acc._CRITERIA_TEMPLATE
    assert _MARKER_ASSUMPTIONS in acc._ASSUMPTIONS_TEMPLATE
    assert _MARKER_BUILD_PLAN in acc._BUILD_PLAN_TEMPLATE
    assert _MARKER_ASSETS in acc._ASSET_SPECS_TEMPLATE


# ---------------------------------------------------------------------------
# Schema shape — each schema is derived from the SAME constants its parser
# validates against (the SSOT lock: constraint and disposal can never drift)
# ---------------------------------------------------------------------------


def test_criteria_schema_mirrors_parser_contract():
    schema = acc.criteria_emission_json_schema(max_criteria=6)
    assert schema["type"] == "array"
    assert schema["minItems"] == 1 and schema["maxItems"] == 6
    items = schema["items"]
    assert items["additionalProperties"] is False
    assert set(items["required"]) == {"text", "tier"}
    assert items["properties"]["tier"]["enum"] == sorted(acc.ALL_TIERS)
    assert items["properties"]["text"]["minLength"] == acc._MIN_CRITERION_LEN
    json.dumps(schema)  # the hook hands schema TEXT — must serialize


def test_assumptions_schema_mirrors_parser_contract():
    schema = acc.assumptions_emission_json_schema(max_assumptions=3)
    assert schema["type"] == "array" and schema["maxItems"] == 3
    assert schema["items"]["type"] == "string"
    assert schema["items"]["minLength"] == acc._MIN_ASSUMPTION_LEN
    json.dumps(schema)


def test_build_plan_schema_mirrors_parser_enums():
    schema = acc.build_plan_emission_json_schema()
    props = schema["properties"]
    # surface: the FULL enum incl. the unknown + ambiguous sentinels (the model may flag).
    assert props["surface"]["enum"] == sorted(acc.SURFACE_VALUES)
    assert "ambiguous" in props["surface"]["enum"]
    # candidates: REAL buildable surfaces only — never the sentinels.
    cand_enum = props["candidates"]["items"]["enum"]
    assert cand_enum == sorted(acc._REAL_SURFACES)
    assert "unknown" not in cand_enum and "ambiguous" not in cand_enum
    assert props["candidates"]["maxItems"] == acc.DEFAULT_MAX_CANDIDATES
    # language_hint: the enum PLUS null (the "no explicit language" answer).
    assert None in props["language_hint"]["enum"]
    assert set(props["language_hint"]["enum"]) - {None} == set(acc.LANGUAGE_HINT_VALUES)
    assert props["complexity"]["enum"] == sorted(acc.COMPLEXITY_VALUES)
    comp_items = props["components"]["items"]
    assert comp_items["properties"]["kind"]["enum"] == sorted(acc.KIND_VALUES)
    assert schema["required"] == ["surface"]
    assert schema["additionalProperties"] is False
    json.dumps(schema)


def test_asset_specs_schema_mirrors_parser_contract():
    schema = acc.asset_specs_emission_json_schema(max_assets=2)
    assert schema["type"] == "array" and schema["maxItems"] == 2
    items = schema["items"]
    assert set(items["required"]) == {"name", "subject", "style"}
    assert items["properties"]["style"]["enum"] == sorted(acc.ASSET_STYLE_VALUES)
    assert items["properties"]["subject"]["minLength"] == acc._MIN_ASSET_SUBJECT_LEN
    # The name cap and the slug truncation share one constant — assert the coupling.
    assert items["properties"]["name"]["maxLength"] == acc._ASSET_SLUG_MAX
    assert len(acc._asset_slug("x" * 200)) <= items["properties"]["name"]["maxLength"]
    json.dumps(schema)


# ---------------------------------------------------------------------------
# Grammar-first — a working hook serves EVERY structured emission; the free
# path never fires (0 free-text calls across the whole PLAN sequence)
# ---------------------------------------------------------------------------


def test_full_plan_sequence_runs_grammar_constrained(tmp_path):
    proj, repo = _repo(tmp_path)
    s_calls: list = []
    f_calls: list = []
    res = acc.generate_plan(
        "a landing page for my bakery", repo,
        generate_fn=_free_gen(f_calls, tasks="[]"),  # free junk everywhere — must not be used
        projects_dir=proj,
        structured_generate_fn=_structured_gen(s_calls),
    )
    assert res.ok
    # decompose + criteria + assumptions + build-signal + assets == 5 grammar calls.
    assert len(s_calls) == 5 and f_calls == []
    # The grammar decompose payload (2 feature tasks), not the free "[]"; compile_prompts
    # appends the dedicated acceptance-tests task for a multi-task plan with test criteria.
    assert [t["task"] for t in res.tasks] == [
        "storage-module", "add-command", acc.ACCEPTANCE_TASK_SLUG,
    ]
    assert any(c.text == "2 + 3 shows 5" for c in res.spec.criteria)
    assert res.spec.assumptions == ("Assumed decimals are supported",)
    assert res.spec.build_plan is not None and res.spec.build_plan["surface"] == "web"
    assert len(res.spec.asset_specs) == 1
    assert res.spec.asset_specs[0]["target_rel_path"] == "public/assets/hero.png"
    assert res.spec.asset_specs[0]["style"] == "illustration"


def test_each_call_receives_its_own_schema(tmp_path):
    proj, repo = _repo(tmp_path)
    s_calls: list = []
    acc.generate_plan(
        "a landing page for my bakery", repo,
        generate_fn=_free_gen([]),
        projects_dir=proj,
        structured_generate_fn=_structured_gen(s_calls),
    )
    by_marker = {}
    for prompt, schema in s_calls:
        if _MARKER_CRITERIA in prompt:
            by_marker["criteria"] = schema
        elif _MARKER_ASSUMPTIONS in prompt:
            by_marker["assumptions"] = schema
        elif _MARKER_BUILD_PLAN in prompt:
            by_marker["build_plan"] = schema
        elif _MARKER_ASSETS in prompt:
            by_marker["assets"] = schema
        elif _MARKER_DECOMPOSE in prompt:
            by_marker["decompose"] = schema
    assert set(by_marker) == {"criteria", "assumptions", "build_plan", "assets", "decompose"}
    assert by_marker["criteria"] == acc.criteria_emission_json_schema()
    assert by_marker["assumptions"] == acc.assumptions_emission_json_schema()
    assert by_marker["build_plan"] == acc.build_plan_emission_json_schema()
    assert by_marker["assets"] == acc.asset_specs_emission_json_schema()
    assert by_marker["decompose"] == dc.plan_emission_json_schema()


def test_generate_plan_threads_hook_into_decompose(tmp_path):
    # The live PLAN entry point is generate_plan — before #743 it never passed the W2
    # hook to decompose_request, so the decompose grammar could not fire on a real
    # /dispatch plan. Lock the threading: the grammar decompose emission wins.
    proj, repo = _repo(tmp_path)
    s_calls: list = []

    def structured(prompt: str, schema_text: str) -> str:
        s_calls.append(prompt)
        if _MARKER_DECOMPOSE in prompt:
            assert json.loads(schema_text) == dc.plan_emission_json_schema()
            return _TASKS_JSON
        return ""  # every other call falls back to free text

    res = acc.generate_plan(
        "an idea", repo,
        generate_fn=_free_gen([], tasks="[]"),
        projects_dir=proj,
        structured_generate_fn=structured,
    )
    assert res.ok and not res.fell_back
    # The grammar decompose payload won (the free path returned "[]"); the trailing
    # acceptance-tests task is compile_prompts' standard multi-task appendix.
    assert {"storage-module", "add-command"} <= {t["task"] for t in res.tasks}
    assert not res.fell_back


def test_grammar_empty_assumptions_array_is_accepted_not_retried(tmp_path):
    # ``[]`` is a MEANINGFUL constrained answer (the fully-specified goal). It must be
    # accepted — the free path (which would invent an assumption here) must not fire.
    proj, repo = _repo(tmp_path)
    f_calls: list = []
    res = acc.generate_plan(
        "a fully specified thing", repo,
        generate_fn=_free_gen(f_calls, assumptions=_ASSUMPTIONS_JSON),
        projects_dir=proj,
        structured_generate_fn=_structured_gen([], assumptions="[]"),
    )
    assert res.ok
    assert res.spec.assumptions == ()  # the grammar's [] stood; no free-text retry
    assert not any(_MARKER_ASSUMPTIONS in p for p in f_calls)


def test_grammar_ambiguous_platform_fork_flows_to_clarifying_question(tmp_path):
    # The ambiguous-platform fork is part of the build-signal call (#743 names it):
    # a grammar-constrained ambiguous emission must flow through _parse_build_plan
    # into the curated clarifying-question seam exactly like a free-text one.
    proj, repo = _repo(tmp_path)
    res = acc.generate_plan(
        "a todo app", repo,
        generate_fn=_free_gen([]),
        projects_dir=proj,
        structured_generate_fn=_structured_gen(
            [], build_plan=_AMBIGUOUS_BUILD_PLAN_JSON, assets="[]"
        ),
    )
    assert res.ok
    bp = res.spec.build_plan
    assert bp is not None and bp["surface"] == acc.SURFACE_AMBIGUOUS
    assert bp["candidates"] == ["desktop-gui", "web", "mobile"]
    q = acc.resolve_clarifying_question(bp)
    assert q is not None and q["question"] == "Where will you mainly use this?"


# ---------------------------------------------------------------------------
# Fail-soft — the grammar leg may NEVER introduce a new failure mode: hook
# off / raising / empty / unusable ⇒ byte-identical legacy behavior
# ---------------------------------------------------------------------------


def _plan_fingerprint(res: acc.PlanResult) -> tuple:
    return (res.ok, res.fell_back, res.message, res.tasks, res.spec.to_dict())


def test_no_hook_is_todays_path_exactly(tmp_path):
    proj, repo = _repo(tmp_path)
    table = dict(criteria=_CRITERIA_JSON, assumptions=_ASSUMPTIONS_JSON,
                 build_plan=_WEB_BUILD_PLAN_JSON, assets=_ASSETS_JSON)
    a_calls: list = []
    b_calls: list = []
    res_absent = acc.generate_plan(
        "a landing page", repo, generate_fn=_free_gen(a_calls, **table), projects_dir=proj
    )
    res_none = acc.generate_plan(
        "a landing page", repo, generate_fn=_free_gen(b_calls, **table), projects_dir=proj,
        structured_generate_fn=None,
    )
    assert _plan_fingerprint(res_absent) == _plan_fingerprint(res_none)
    assert a_calls == b_calls  # same prompts, same order


def test_hook_raising_everywhere_is_byte_identical_to_legacy(tmp_path):
    proj, repo = _repo(tmp_path)
    table = dict(criteria=_CRITERIA_JSON, assumptions=_ASSUMPTIONS_JSON,
                 build_plan=_WEB_BUILD_PLAN_JSON, assets=_ASSETS_JSON)
    legacy_calls: list = []
    hooked_calls: list = []
    res_legacy = acc.generate_plan(
        "a landing page", repo, generate_fn=_free_gen(legacy_calls, **table),
        projects_dir=proj,
    )

    def broken(_prompt: str, _schema: str) -> str:
        raise RuntimeError("no StructuredOutputConfig on this build")

    res_hooked = acc.generate_plan(
        "a landing page", repo, generate_fn=_free_gen(hooked_calls, **table),
        projects_dir=proj, structured_generate_fn=broken,
    )
    assert _plan_fingerprint(res_legacy) == _plan_fingerprint(res_hooked)
    assert legacy_calls == hooked_calls  # the free path ran identically, same order


def test_hook_empty_and_garbage_fall_back_per_call(tmp_path):
    proj, repo = _repo(tmp_path)
    for bad in ("", "   ", "not json at all"):
        f_calls: list = []
        res = acc.generate_plan(
            "a landing page", repo,
            generate_fn=_free_gen(
                f_calls, criteria=_CRITERIA_JSON, assumptions=_ASSUMPTIONS_JSON,
                build_plan=_WEB_BUILD_PLAN_JSON, assets=_ASSETS_JSON,
            ),
            projects_dir=proj,
            structured_generate_fn=lambda _p, _s, bad=bad: bad,
        )
        assert res.ok
        # Every emission fell back to the free path — its values are what landed.
        assert any(c.text == "2 + 3 shows 5" for c in res.spec.criteria)
        assert res.spec.assumptions == ("Assumed decimals are supported",)
        assert res.spec.build_plan is not None and res.spec.build_plan["surface"] == "web"
        assert len(res.spec.asset_specs) == 1
        # All five structured prompts hit the free path.
        assert any(_MARKER_CRITERIA in p for p in f_calls)
        assert any(_MARKER_ASSUMPTIONS in p for p in f_calls)
        assert any(_MARKER_BUILD_PLAN in p for p in f_calls)
        assert any(_MARKER_ASSETS in p for p in f_calls)


def test_criteria_grammar_unusable_falls_back_to_free_criteria(tmp_path):
    # A hook that answers the criteria prompt with an EMPTY array (unparseable into
    # criteria) must fall back — minItems:1 documents the intent; the runtime check
    # is _parse_criteria yielding nothing.
    proj, repo = _repo(tmp_path)

    def structured(prompt: str, _schema: str) -> str:
        if _MARKER_CRITERIA in prompt:
            return "[]"
        raise RuntimeError("only criteria served")

    res = acc.generate_plan(
        "a thing", repo,
        generate_fn=_free_gen([], criteria=_CRITERIA_JSON),
        projects_dir=proj, structured_generate_fn=structured,
    )
    assert res.ok
    assert any(c.text == "2 + 3 shows 5" for c in res.spec.criteria)


def test_grammar_down_and_free_raising_keeps_todays_fallbacks(tmp_path):
    # BOTH legs failing on every sub-call still ends at today's designed degradation:
    # build-floor criteria, no assumptions, no build signal, no assets — never a raise.
    proj, repo = _repo(tmp_path)

    def free(prompt: str) -> str:
        if _MARKER_DECOMPOSE in prompt:
            return _ONE_TASK_JSON
        raise RuntimeError("model unavailable")

    res = acc.generate_plan(
        "a thing", repo, generate_fn=free, projects_dir=proj,
        structured_generate_fn=lambda _p, _s: (_ for _ in ()).throw(RuntimeError("down")),
    )
    assert res.ok
    assert len(res.spec.criteria) == 1  # the injected default BUILD criterion
    assert res.spec.criteria[0].tier == acc.TIER_BUILD
    assert res.spec.assumptions == ()
    assert res.spec.build_plan is None
    assert res.spec.asset_specs == ()


def test_asset_specs_grammar_never_fires_for_non_visual_surface(tmp_path):
    # The visual-surface gate runs BEFORE either generation leg: a CLI product makes
    # no asset call at all — grammar or free (the SEAM A dormancy is unchanged).
    proj, repo = _repo(tmp_path)
    s_calls: list = []
    f_calls: list = []
    cli_plan = json.dumps({"surface": "command-line", "candidates": [],
                           "language_hint": None, "complexity": "simple", "components": []})
    res = acc.generate_plan(
        "a renamer script", repo,
        generate_fn=_free_gen(f_calls),
        projects_dir=proj,
        structured_generate_fn=_structured_gen(s_calls, build_plan=cli_plan),
    )
    assert res.ok and res.spec.asset_specs == ()
    assert not any(_MARKER_ASSETS in p for p, _ in s_calls)
    assert not any(_MARKER_ASSETS in p for p in f_calls)


def test_grammar_first_helper_contract():
    # The seam itself: None hook / raise / empty / unusable ⇒ None; usable ⇒ the raw.
    schema = {"type": "array"}
    assert acc._grammar_first("p", structured_generate_fn=None, schema=schema,
                              usable=lambda _t: True) is None

    def boom(_p: str, _s: str) -> str:
        raise RuntimeError("x")

    assert acc._grammar_first("p", structured_generate_fn=boom, schema=schema,
                              usable=lambda _t: True) is None
    assert acc._grammar_first("p", structured_generate_fn=lambda _p, _s: "", schema=schema,
                              usable=lambda _t: True) is None
    assert acc._grammar_first("p", structured_generate_fn=lambda _p, _s: "raw", schema=schema,
                              usable=lambda _t: False) is None
    assert acc._grammar_first("p", structured_generate_fn=lambda _p, _s: "[1]", schema=schema,
                              usable=lambda _t: True) == "[1]"


def test_is_json_array_emission():
    assert acc._is_json_array_emission("[]") is True
    assert acc._is_json_array_emission('["a", "b"]') is True
    assert acc._is_json_array_emission('prose then ["a"] trailing') is True
    assert acc._is_json_array_emission("") is False
    assert acc._is_json_array_emission("not json") is False
    assert acc._is_json_array_emission('{"a": 1}') is False
    assert acc._is_json_array_emission("[broken") is False
