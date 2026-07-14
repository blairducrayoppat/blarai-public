"""Tests for decompose — the increment-2 14B decomposer + deterministic ruler.

The model call is mocked; the ruler (the trust boundary) is exercised directly.
"""

from __future__ import annotations

import json

from shared.fleet import decompose as dc


def _projects(tmp_path):
    proj = tmp_path / "projects"
    (proj / "myapp" / ".git").mkdir(parents=True)
    return proj


def _gen(payload):
    """A fake generate_fn returning a fixed string."""
    return lambda _prompt: payload


# ---- happy path: model proposes, ruler disposes ---------------------------


def test_valid_json_array_parsed_and_slugged(tmp_path):
    # Feeds a TWO-element model array (exercises multi-item JSON parse + slugify). The
    # second item ("Add tests") is a STRUCTURAL test split of the feature sibling, so the
    # right-sizing ruler collapses it: decompose emits ONLY the feature task and the test
    # task is added downstream by the acceptance layer. (This asserted len==2 before the
    # over-decomposition fix — that count encoded the bug; the parse + slugify coverage on
    # the surviving feature task is retained, and collapsed_test_intent is now asserted.)
    proj = _projects(tmp_path)
    payload = json.dumps([
        {"task": "Add Health Check", "prompt": "Add a /health endpoint returning 200."},
        {"task": "Add tests", "prompt": "Add a test for /health."},
    ])
    res = dc.decompose_request("add health stuff", "myapp", generate_fn=_gen(payload),
                               projects_dir=proj)
    assert res.ok and not res.fell_back and len(res.tasks) == 1  # add-tests collapsed
    assert res.tasks[0]["task"] == "add-health-check"      # parsed + slugged (kept)
    assert res.tasks[0]["repo"].endswith("myapp")
    assert res.tasks[0]["prompt"].startswith("Add a /health")
    assert res.collapsed_test_intent is True   # the structural test split was dropped


def test_json_wrapped_in_prose_is_extracted(tmp_path):
    proj = _projects(tmp_path)
    payload = 'Sure! Here you go:\n```json\n[{"task":"x","prompt":"do x"}]\n```\nDone.'
    res = dc.decompose_request("idea", "myapp", generate_fn=_gen(payload), projects_dir=proj)
    assert res.ok and not res.fell_back and len(res.tasks) == 1
    assert res.tasks[0]["task"] == "x" and res.tasks[0]["prompt"] == "do x"


def test_cap_at_max_tasks(tmp_path):
    proj = _projects(tmp_path)
    payload = json.dumps([{"task": f"t{i}", "prompt": f"p{i}"} for i in range(20)])
    res = dc.decompose_request("idea", "myapp", generate_fn=_gen(payload),
                               projects_dir=proj, max_tasks=3)
    assert res.ok and len(res.tasks) == 3


def test_duplicate_slugs_deduped(tmp_path):
    proj = _projects(tmp_path)
    payload = json.dumps([
        {"task": "Add Health", "prompt": "a"},
        {"task": "add  health", "prompt": "b"},   # slugs to the same thing
    ])
    res = dc.decompose_request("idea", "myapp", generate_fn=_gen(payload), projects_dir=proj)
    assert len(res.tasks) == 1


def test_items_missing_fields_skipped(tmp_path):
    proj = _projects(tmp_path)
    payload = json.dumps([
        {"task": "ok", "prompt": "go"},
        {"task": "", "prompt": "no slug"},
        {"prompt": "no task"},
        {"task": "no prompt"},
        "not a dict",
    ])
    res = dc.decompose_request("idea", "myapp", generate_fn=_gen(payload), projects_dir=proj)
    assert len(res.tasks) == 1 and res.tasks[0]["task"] == "ok"


# ---- fallback: model output unusable → single task ------------------------


def test_garbage_output_falls_back_to_single_task(tmp_path):
    proj = _projects(tmp_path)
    res = dc.decompose_request("make it faster", "myapp", generate_fn=_gen("lol no json"),
                               projects_dir=proj)
    assert res.ok and res.fell_back and len(res.tasks) == 1
    assert res.tasks[0]["prompt"] == "make it faster"
    assert res.tasks[0]["task"] == "make-it-faster"


def test_empty_array_falls_back(tmp_path):
    proj = _projects(tmp_path)
    res = dc.decompose_request("idea", "myapp", generate_fn=_gen("[]"), projects_dir=proj)
    assert res.ok and res.fell_back and len(res.tasks) == 1


def test_model_exception_falls_back_with_note(tmp_path):
    proj = _projects(tmp_path)

    def boom(_p):
        raise RuntimeError("gpu oom")

    res = dc.decompose_request("idea", "myapp", generate_fn=boom, projects_dir=proj)
    assert res.ok and res.fell_back and len(res.tasks) == 1
    assert "gpu oom" in res.message


# ---- fail-closed: bad repo / empty idea -----------------------------------


def test_invalid_repo_rejected_before_model(tmp_path):
    proj = _projects(tmp_path)
    called = {"n": 0}

    def gen(_p):
        called["n"] += 1
        return "[]"

    res = dc.decompose_request("idea", "does-not-exist", generate_fn=gen, projects_dir=proj)
    assert not res.ok and not res.tasks
    assert called["n"] == 0   # repo validated BEFORE the model is consulted


def test_empty_idea_rejected(tmp_path):
    proj = _projects(tmp_path)
    res = dc.decompose_request("   ", "myapp", generate_fn=_gen("[]"), projects_dir=proj)
    assert not res.ok and not res.tasks


# ---- leaf-goal stop-condition (the SDD recursion foundation) ---------------


def test_is_leaf_goal_predicate():
    # The recursion STOP-CONDITION a future recursive decompose will call. It is built +
    # locked here but deliberately NOT used as a single-pass feature-dropping cap (that
    # false-collapses multi-feature goals — see decompose._is_leaf_goal). Conservative:
    # a short request naming ONE concrete artifact with no multi-deliverable markers.
    assert dc._is_leaf_goal("write an is_leap_year function")
    assert dc._is_leaf_goal("implement a /health-check endpoint")
    assert dc._is_leaf_goal("add a slugify helper")
    # NOT leaves: enumerated / multi-unit / broad goals.
    assert not dc._is_leaf_goal("a CLI todo app: add, list, and done")
    assert not dc._is_leaf_goal("build an ecommerce site")
    assert not dc._is_leaf_goal("add a login form and a dashboard")
    assert not dc._is_leaf_goal("")


def test_unit_tests_slug_collapsed_f5():
    # #688 F5: a planner that splits "unit-tests-<feature>" off as its own task (the leading
    # unit/integration filler hides the test marker from the verb taxonomy, which reads verb
    # "unit") must not explode the queue. The live C dispatch decomposed a moderate CSV->JSON
    # CLI into 7 tasks, 3 of them test slugs; they collapse to the feature survivors (the
    # acceptance layer owns testing).
    assert dc._classify("unit-tests-csv-reader") == "test"
    assert dc._classify("unit-tests-type-checker") == "test"
    assert dc._classify("integration-tests-foo") == "test"
    slugs = ["csv-to-json-converter", "input-validation", "error-reporting", "file-handling",
             "unit-tests-csv-reader", "unit-tests-type-checker", "acceptance-tests"]
    survivors, collapsed = dc._collapse([{"task": s, "prompt": "x"} for s in slugs])
    assert [c["task"] for c in survivors] == [
        "csv-to-json-converter", "input-validation", "error-reporting", "file-handling"]
    assert collapsed is True


def test_unit_tests_tool_deliverable_not_collapsed_f5():
    # #688 F5 safety: a test-TOOL you SHIP (a runner / harness / generator) is a FEATURE, never
    # collapsed -- the never-false-collapse-a-real-feature direction. A real validation feature
    # led by no test marker is likewise untouched.
    assert dc._classify("unit-tests-runner") == "feature"
    assert dc._classify("integration-test-harness") == "feature"
    assert dc._classify("test-data-generator") == "feature"
    assert dc._classify("input-validation") == "feature"


# ---- #691 envelope upper-bound: split an under-split oversize task ----------


def _router(*, decompose, split, on_split=None):
    """A fake generate_fn routing the first-pass decompose vs the 'go finer' split by the
    split template's unique phrase. ``on_split`` (optional) captures the split prompt."""
    def gen(prompt):
        if "TOO LARGE to build and verify in one short" in prompt:
            if on_split is not None:
                on_split(prompt)
            return split
        return decompose
    return gen


def test_unit_marker_count():
    assert dc._unit_marker_count("a calculator that adds and subtracts") == 1
    assert dc._unit_marker_count("a todo app with add, list, and delete commands") == 3
    assert dc._unit_marker_count("a todo app") == 0
    assert dc._unit_marker_count("add / list / done") == 2
    assert dc._unit_marker_count("") == 0


def test_envelope_splits_an_under_split_oversize_goal(tmp_path):
    # A clearly-multi-unit goal the 14B lumped into ONE task is offered to the recursive
    # splitter, which replaces it with the per-command gated steps (the upper bound).
    proj = _projects(tmp_path)
    decompose = json.dumps([{"task": "todo-app",
                             "prompt": "Build a todo app with add, list, and delete commands."}])
    split = json.dumps([
        {"task": "add-command", "prompt": "Add the add command."},
        {"task": "list-command", "prompt": "Add the list command."},
        {"task": "delete-command", "prompt": "Add the delete command."},
    ])
    res = dc.decompose_request(
        "a todo app with add, list, and delete commands", "myapp",
        generate_fn=_router(decompose=decompose, split=split), projects_dir=proj,
    )
    assert res.ok and res.split_oversize is True
    assert [t["task"] for t in res.tasks] == ["add-command", "list-command", "delete-command"]
    assert "envelope" in res.message.lower()


def test_envelope_failsafe_keeps_coherent_single_app(tmp_path):
    # [kill] the splitter returns ONE task (the 14B judged it a single coherent step) -> the
    # strict-improvement fail-safe keeps the ORIGINAL lump; never a forced split.
    proj = _projects(tmp_path)
    goal = "a calculator that adds, subtracts, and multiplies"
    res = dc.decompose_request(
        goal, "myapp",
        generate_fn=_router(
            decompose=json.dumps([{"task": "calc", "prompt": goal}]),
            split=json.dumps([{"task": "calc", "prompt": goal}]),  # 14B: it's one coherent step
        ),
        projects_dir=proj,
    )
    assert res.ok and res.split_oversize is False
    assert len(res.tasks) == 1 and res.tasks[0]["task"] == "calc"


def test_envelope_no_split_below_marker_threshold(tmp_path):
    # [kill] a 2-aspect small app ("adds and subtracts" -> 1 marker) is BELOW the threshold, so
    # the splitter is never offered the task. The split payload (5 tasks) would change the result
    # if wrongly used -> assert it did not.
    proj = _projects(tmp_path)
    res = dc.decompose_request(
        "a calculator that adds and subtracts", "myapp",
        generate_fn=_router(
            decompose=json.dumps([{"task": "calc", "prompt": "a calculator that adds and subtracts"}]),
            split=json.dumps([{"task": f"s{i}", "prompt": f"p{i}"} for i in range(5)]),
        ),
        projects_dir=proj,
    )
    assert res.split_oversize is False and len(res.tasks) == 1


def test_envelope_no_split_when_already_multi_task(tmp_path):
    # First pass already produced >=2 tasks -> the upper-bound split is not offered (len != 1).
    proj = _projects(tmp_path)
    res = dc.decompose_request(
        "a login page and a dashboard page", "myapp",
        generate_fn=_router(
            decompose=json.dumps([
                {"task": "login-page", "prompt": "Build the login page."},
                {"task": "dashboard-page", "prompt": "Build the dashboard page."},
            ]),
            split=json.dumps([{"task": f"s{i}", "prompt": f"p{i}"} for i in range(5)]),
        ),
        projects_dir=proj,
    )
    assert res.split_oversize is False and len(res.tasks) == 2


def test_envelope_split_children_are_right_sized(tmp_path):
    # The split children run through the SAME _collapse ruler: a structural 'add-tests' step the
    # splitter emits is dropped, and the >=2 strict-improvement is measured on the FEATURE survivors.
    proj = _projects(tmp_path)
    goal = "a notes app with create, edit, and delete notes"
    res = dc.decompose_request(
        goal, "myapp",
        generate_fn=_router(
            decompose=json.dumps([{"task": "notes-app", "prompt": goal}]),
            split=json.dumps([
                {"task": "create-note", "prompt": "Add create-note."},
                {"task": "edit-note", "prompt": "Add edit-note."},
                {"task": "delete-note", "prompt": "Add delete-note."},
                {"task": "add-tests", "prompt": "Add tests for the notes app."},  # collapsed
            ]),
        ),
        projects_dir=proj,
    )
    assert res.split_oversize is True
    assert [t["task"] for t in res.tasks] == ["create-note", "edit-note", "delete-note"]


def test_envelope_split_disabled_at_max_depth_1(tmp_path):
    # max_depth<=1 disables the upper-bound split (today's single-pass behavior), even when the
    # trigger conditions hold.
    proj = _projects(tmp_path)
    res = dc.decompose_request(
        "a todo app with add, list, and delete", "myapp",
        generate_fn=_router(
            decompose=json.dumps([{"task": "todo-app", "prompt": "a todo app with add, list, and delete"}]),
            split=json.dumps([{"task": "a", "prompt": "x"}, {"task": "b", "prompt": "y"}]),
        ),
        projects_dir=proj, max_depth=1,
    )
    assert res.split_oversize is False and len(res.tasks) == 1


def test_envelope_split_model_error_is_non_fatal(tmp_path):
    # A split-gen failure must not crash the plan -> keep the original lump (fail-closed).
    proj = _projects(tmp_path)
    decompose = json.dumps([{"task": "todo-app", "prompt": "a todo app with add, list, and delete"}])

    def gen(prompt):
        if "TOO LARGE to build and verify in one short" in prompt:
            raise RuntimeError("gpu oom during split")
        return decompose

    res = dc.decompose_request(
        "a todo app with add, list, and delete", "myapp", generate_fn=gen, projects_dir=proj,
    )
    assert res.ok and res.split_oversize is False and len(res.tasks) == 1


def test_envelope_split_prompt_carries_the_task(tmp_path):
    # The split call receives the SPLIT template (not the decompose one) carrying the lumped
    # task's prompt -- so the 14B re-splits the ACTUAL work, not the original goal text.
    proj = _projects(tmp_path)
    captured = {}
    res = dc.decompose_request(
        "a todo app with add, list, and delete commands", "myapp",
        generate_fn=_router(
            decompose=json.dumps([{"task": "todo-app",
                                   "prompt": "Build a todo app with add, list, and delete commands."}]),
            split=json.dumps([{"task": "a", "prompt": "x"}, {"task": "b", "prompt": "y"}]),
            on_split=lambda p: captured.__setitem__("p", p),
        ),
        projects_dir=proj,
    )
    assert res.split_oversize is True
    assert "TOO LARGE to build and verify in one short" in captured["p"]
    assert "Build a todo app with add, list, and delete commands." in captured["p"]


def test_decompose_template_carries_envelope_framing():
    # Doc-lock: the strengthened decompose prompt sets the UPPER bound (whole-app = multiple
    # tasks, each buildable in one short run) alongside the existing anti-over-split rules.
    assert "envelope" in dc._DECOMPOSE_TEMPLATE.lower()
    assert "one short automated run" in dc._DECOMPOSE_TEMPLATE.lower()


def test_multipart_pipeline_response_survives_as_multiple_tasks(tmp_path):
    # M2 under-decomposition (B2) plumbing lock: when the 14B DOES emit the distinct-output
    # pipeline as several feature tasks (tokenize -> {word-freq, bigram-freq} -> report), the
    # deterministic path (parse -> _collapse -> ruler) must keep ALL of them, never re-collapse
    # a genuine multi-stage pipeline to one. The LIVE fix (the 14B emitting >=2 for the 'little
    # toolkit' phrasing) is the prompt lever + a GPU re-test; THIS locks that a correct
    # multi-task response is not wrongly re-collapsed, and that four distinct outputs are 4.
    proj = _projects(tmp_path)
    goal = ("a little toolkit that reads text, breaks it into words, counts how often each word "
            "appears and which neighbouring pairs occur most, then writes one tidy report")
    payload = json.dumps([
        {"task": "tokenize-text", "prompt": "Break the input text into a list of words."},
        {"task": "count-word-frequencies", "prompt": "Count how often each word appears."},
        {"task": "count-bigram-frequencies", "prompt": "Count neighbouring word pairs."},
        {"task": "compose-combined-report", "prompt": "Combine both counts into one report."},
    ])
    res = dc.decompose_request(goal, "myapp", generate_fn=_gen(payload), projects_dir=proj)
    assert res.ok and not res.fell_back
    slugs = [t["task"] for t in res.tasks]
    assert slugs == ["tokenize-text", "count-word-frequencies",
                     "count-bigram-frequencies", "compose-combined-report"], slugs


def test_decompose_templates_carry_distinct_output_pipeline_guidance():
    # Doc-lock (M2 #740 under-decomposition fix): both emission prompts must teach that a
    # distinct-output PIPELINE is several tasks and that diminutive words ('little'/'tidy')
    # describe tone, not count — the prompt lever against the B2 'little toolkit' under-scope.
    dt = dc._DECOMPOSE_TEMPLATE.lower()
    assert "distinct output" in dt                      # the pipeline rule
    assert "little" in dt and "tidy" in dt              # the diminutive-framing counter
    assert "tokenize-text" in dc._DECOMPOSE_TEMPLATE    # the pipeline few-shot survives edits
    st = dc._SPLIT_TEMPLATE.lower()
    assert "distinct" in st and "adjectives" in st      # the split backstop carries it too


# ---------------------------------------------------------------------------
# #824 — duplicate-``task``-key collapse recovery + retry-with-guidance + diagnostics
# ---------------------------------------------------------------------------
# The live root cause of B1/B5 going FLAT (state/decompose-debug-20260710.log:5947, :6342): the
# 14B emitted a well-formed MULTI-task plan but OMITTED the ``},{`` object separators, so every
# task's key-group landed in ONE object with a repeated ``"task"`` key -> json.loads keeps only
# the last -> cands=1 -> flat mode. It is VALID json, so ``_repair_json_array`` never fires.


def _collapsed_raw(tasks: list[dict]) -> str:
    """Reproduce the #824 malformation: N task objects MERGED into one (missing ``},{``
    separators), exactly the shape the live 14B emitted for B1/B5. ``json.loads`` keeps only
    the LAST ``"task"`` — so the array parses to a single candidate."""
    inner = ", ".join(
        ", ".join(f"{json.dumps(k)}: {json.dumps(v)}" for k, v in t.items())
        for t in tasks
    )
    return "[{" + inner + "}]"


# B1 (expense-cli) and B5 (habit-web) goal cards — evals/battery/B{1,5}.json — with the REAL
# collapsed decompose shape the log captured. These are the offline decompose golden cases.
_B1_GOAL = ("I want a little program I can run from a command window to keep track of what I "
            "spend. First it needs somewhere to save my expenses. Then I want to type in an "
            "expense — amount, category, and date. And I want a list of everything I have spent, "
            "newest first.")
_B1_TASKS = [
    {"task": "setup-data-storage", "prompt": "Persist expenses between runs.", "depends_on": [],
     "contract": {"creates": ["storage.py"], "exports": ["save_expense", "load_expenses"],
                  "notes": "list of dicts"}},
    {"task": "input-expense-data", "prompt": "Capture amount, category, and date from the CLI.",
     "depends_on": ["setup-data-storage"],
     "contract": {"creates": ["main.py"], "exports": ["capture_expense"], "notes": "prompts"}},
    {"task": "retrieve-expense-list", "prompt": "List all expenses sorted by date, newest first.",
     "depends_on": ["setup-data-storage"],
     "contract": {"creates": ["main.py"], "exports": ["list_expenses"], "notes": "descending"}},
]
_B5_GOAL = ("I want a page in my web browser to track daily habits — set them up, tick each one "
            "off with everything remembered between visits, work out streaks and success rates, "
            "a chart over time, and one main page bringing the tick-list and the chart together.")
_B5_TASKS = [
    {"task": "create-habit-tracking-ui", "prompt": "UI to set up and tick daily habits."},
    {"task": "implement-habit-storage", "prompt": "Persist habit ticks between visits."},
    {"task": "calculate-habit-stats", "prompt": "Compute streaks and success rates."},
    {"task": "generate-visual-chart", "prompt": "Render a chart of habit progress over time."},
    {"task": "combine-ui-and-chart", "prompt": "Bring the tick-list and chart onto one page."},
]


def test_collapsed_raw_helper_reproduces_the_live_bug():
    # Documents the failure the recovery targets: a merged multi-task object parses to ONE task.
    raw = _collapsed_raw(_B1_TASKS)
    assert len(json.loads(raw)) == 1                    # the silent duplicate-key collapse
    assert len(dc._TASK_KEY_RE.findall(raw)) == 3       # ...but the INTENT was 3 tasks


def test_b1_expense_card_recovers_to_plan_graph(tmp_path):
    proj = _projects(tmp_path)
    res = dc.decompose_request(_B1_GOAL, "myapp",
                               generate_fn=_gen(_collapsed_raw(_B1_TASKS)), projects_dir=proj)
    assert res.ok and not res.fell_back and len(res.tasks) >= 2     # graphs instead of flat
    assert res.diagnostics["repair"] == "duplicate-key-split"
    assert res.diagnostics["outcome"] == "plan-graph"
    assert res.diagnostics["task_key_occurrences"] == 3


def test_b5_habit_card_recovers_to_plan_graph(tmp_path):
    proj = _projects(tmp_path)
    res = dc.decompose_request(_B5_GOAL, "myapp",
                               generate_fn=_gen(_collapsed_raw(_B5_TASKS)), projects_dir=proj)
    assert res.ok and not res.fell_back and len(res.tasks) >= 2
    assert res.diagnostics["repair"] == "duplicate-key-split"
    assert res.diagnostics["outcome"] == "plan-graph"
    slugs = [t["task"] for t in res.tasks]
    assert "combine-ui-and-chart" in slugs and "calculate-habit-stats" in slugs


def test_recovery_preserves_graph_fields_at_parse(tmp_path):
    # Recovery carries depends_on + contract through the parse (not just task/prompt). Asserted at
    # the parse level: the downstream ruler legitimately strips a depends_on ref to a task the
    # right-sizing collapse removed, so this locks the RECOVERY, not the (separate) ruler re-map.
    cands = dc._parse_candidates(_collapsed_raw(_B1_TASKS), max_tasks=32)
    assert [c["task"] for c in cands] == [
        "setup-data-storage", "input-expense-data", "retrieve-expense-list"]
    retr = cands[2]
    assert retr["depends_on"] == ["setup-data-storage"]
    assert retr["contract"]["exports"] == ["list_expenses"]


def test_healthy_multitask_array_untouched_by_recovery(tmp_path):
    # A well-formed [{},{},{}] must be byte-identical to today — recovery NEVER fires (repair="").
    proj = _projects(tmp_path)
    payload = json.dumps([
        {"task": "tokenize-text", "prompt": "Break text into words."},
        {"task": "count-word-frequencies", "prompt": "Count each word."},
        {"task": "compose-report", "prompt": "Combine into one report."},
    ])
    res = dc.decompose_request("a text toolkit: tokenize, count, and report", "myapp",
                               generate_fn=_gen(payload), projects_dir=proj)
    assert len(res.tasks) == 3 and res.diagnostics["repair"] == ""


def test_single_task_goal_not_recovered_or_retried(tmp_path):
    # One legitimately-single task (task_key_hits==1) is NOT a collapse — no recovery, no retry.
    proj = _projects(tmp_path)
    calls = {"n": 0}

    def gen(_p):
        calls["n"] += 1
        return json.dumps([{"task": "add-endpoint", "prompt": "Add a /health endpoint."}])

    res = dc.decompose_request("add a /health endpoint", "myapp", generate_fn=gen, projects_dir=proj)
    assert len(res.tasks) == 1 and res.diagnostics["repair"] == ""
    assert res.diagnostics["retry_attempted"] is False and calls["n"] == 1   # no second call
    assert res.diagnostics["flat_reason"] in ("leaf-goal", "single-task")


def test_retry_with_guidance_lifts_unrecoverable_collapse(tmp_path):
    # A malformed multi-INTENT output the deterministic recovery cannot salvage (duplicate task
    # keys but NO prompts -> every recovered object dropped) triggers ONE guided retry; the
    # corrected array is adopted -> plan-graph.
    proj = _projects(tmp_path)
    bad = '[{"task": "one", "task": "two", "task": "three"}]'          # 3 task keys, no prompts
    good = json.dumps([
        {"task": "storage", "prompt": "Persist the data."},
        {"task": "add-command", "prompt": "Add an item from the CLI."},
    ])

    def gen(prompt):
        return good if "collapsed into a SINGLE task" in prompt else bad

    res = dc.decompose_request("save, add, and list items from a command line", "myapp",
                               generate_fn=gen, projects_dir=proj)
    assert res.ok and not res.fell_back and len(res.tasks) >= 2
    assert res.diagnostics["retry_attempted"] is True and res.diagnostics["retry_used"] is True


def test_retry_is_fail_soft_and_never_blocks_dispatch(tmp_path):
    # A retry that RAISES must not crash the dispatch — attempt 1 stands (single-task fallback),
    # ok=True. A failed retry NEVER blocks a dispatch (the honest floor is unchanged).
    proj = _projects(tmp_path)
    bad = '[{"task": "one", "task": "two"}]'

    def gen(prompt):
        if "collapsed into a SINGLE task" in prompt:
            raise RuntimeError("gpu oom on retry")
        return bad

    res = dc.decompose_request("save and list items from a command line", "myapp",
                               generate_fn=gen, projects_dir=proj)
    assert res.ok and res.diagnostics["retry_attempted"] is True
    assert res.diagnostics["retry_used"] is False


def test_grammar_usable_emission_does_not_retry(tmp_path):
    # A grammar-produced emission is well-formed by construction — it must never trigger the
    # malformed-collapse retry, and the free-text path must not be consulted at all.
    proj = _projects(tmp_path)
    calls = {"free": 0}

    def free(_p):
        calls["free"] += 1
        return "lol no json"

    def structured(_p, _schema):
        return json.dumps([{"task": "add-endpoint", "prompt": "Add a /health endpoint."}])

    res = dc.decompose_request("add a /health endpoint", "myapp", generate_fn=free,
                               structured_generate_fn=structured, projects_dir=proj)
    assert res.ok and res.used_grammar is True
    assert res.diagnostics["retry_attempted"] is False and calls["free"] == 0


def test_fallback_carries_diagnostics(tmp_path):
    proj = _projects(tmp_path)
    res = dc.decompose_request("make it faster", "myapp", generate_fn=_gen("lol no json"),
                               projects_dir=proj)
    assert res.fell_back and res.diagnostics["outcome"] == "fallback"
    assert res.diagnostics["flat_reason"] in ("no-array", "empty-or-unparseable")


def test_debug_dump_writes_structured_diagnostics(tmp_path, monkeypatch):
    # BLARAI_DECOMPOSE_DEBUG capture is now classifier-ready: a JSON diagnostics record per call.
    proj = _projects(tmp_path)
    dump = tmp_path / "decompose.jsonl"
    monkeypatch.setenv("BLARAI_DECOMPOSE_DEBUG", str(dump))
    dc.decompose_request(_B5_GOAL, "myapp",
                         generate_fn=_gen(_collapsed_raw(_B5_TASKS)), projects_dir=proj)
    text = dump.read_text(encoding="utf-8")
    assert "=== decompose diagnostics ===" in text
    line = next(ln for ln in text.splitlines() if ln.startswith("=== decompose diagnostics ==="))
    payload = json.loads(line.split("=== decompose diagnostics ===", 1)[1])
    assert payload["schema"] == "decompose-diagnostics/v1"
    assert payload["repair"] == "duplicate-key-split" and payload["outcome"] == "plan-graph"
