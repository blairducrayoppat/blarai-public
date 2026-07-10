"""Tests for decompose v3 (M2 W2, #740) — graph-field elicitation on the SAME decompose
call, the ruler's depends_on re-mapping, the optional grammar-constrained emission hook
(fail-soft to today's free-text path), and the gold-plan calibration scorer.

Model calls are faked throughout (offline — the live 14B grammar check is the W8
residency's job).
"""

from __future__ import annotations

import json
from pathlib import Path

from evals import plan_calibration as cal
from shared.fleet import decompose as dc
from shared.fleet import plan_graph as pg


def _projects(tmp_path):
    proj = tmp_path / "projects"
    (proj / "myapp" / ".git").mkdir(parents=True, exist_ok=True)
    return proj


def _gen(payload):
    return lambda _prompt: payload


def _decompose(tmp_path, payload, **kwargs):
    proj = _projects(tmp_path)
    return dc.decompose_request(
        "a budget tracker app: storage, add, list", "myapp",
        generate_fn=_gen(payload), projects_dir=proj, **kwargs,
    )


_GRAPH_PAYLOAD = json.dumps([
    {"task": "storage-module", "prompt": "Build the storage module.", "depends_on": [],
     "contract": {"creates": ["src/storage.py"],
                  "exports": ["add_expense(expense)"],
                  "notes": "expense = {amount, category, date_iso}"}},
    {"task": "add-command", "prompt": "Build the add command.",
     "depends_on": ["storage-module"],
     "contract": {"creates": ["src/cli_add.py"], "exports": ["cmd_add(argv)"],
                  "notes": "argparse"}},
])


# ---------------------------------------------------------------------------
# Field elicitation — parse + carry-through
# ---------------------------------------------------------------------------


def test_graph_fields_carried_through(tmp_path):
    res = _decompose(tmp_path, _GRAPH_PAYLOAD)
    assert res.ok and len(res.tasks) == 2
    assert res.tasks[0]["depends_on"] == []          # explicit independent root kept
    assert res.tasks[1]["depends_on"] == ["storage-module"]
    assert res.tasks[1]["contract"]["creates"] == ["src/cli_add.py"]
    assert res.tasks[0]["contract"]["notes"].startswith("expense =")


def test_legacy_payload_keeps_exact_two_key_shape(tmp_path):
    # No graph fields from the model ⇒ the pre-W2 task shape, byte-identical — every
    # existing caller and the graph-unaware chain fallback depend on this.
    payload = json.dumps([{"task": "add-health-check", "prompt": "Add /health."}])
    res = _decompose(tmp_path, payload)
    assert res.ok and set(res.tasks[0].keys()) == {"repo", "task", "prompt"}
    assert res.used_grammar is False


def test_garbage_depends_on_omitted(tmp_path):
    payload = json.dumps([
        {"task": "a-feature", "prompt": "p", "depends_on": "not-a-list"},
        {"task": "b-feature", "prompt": "p", "depends_on": {"x": 1}},
        {"task": "c-feature", "prompt": "p", "depends_on": 42},
    ])
    res = _decompose(tmp_path, payload)
    assert res.ok and all("depends_on" not in t for t in res.tasks)


def test_garbage_contract_omitted(tmp_path):
    payload = json.dumps([
        {"task": "a-feature", "prompt": "p", "contract": "nope"},
        {"task": "b-feature", "prompt": "p", "contract": [1, 2]},
        {"task": "c-feature", "prompt": "p",
         "contract": {"creates": [], "exports": [], "notes": ""}},  # all-empty ⇒ omitted
    ])
    res = _decompose(tmp_path, payload)
    assert res.ok and all("contract" not in t for t in res.tasks)


def test_depends_on_entries_cleaned_slugified_deduped(tmp_path):
    payload = json.dumps([
        {"task": "Storage Module", "prompt": "p", "depends_on": []},
        {"task": "add-cmd", "prompt": "p",
         "depends_on": ["Storage Module", "storage-module", 42, None, "!!!"]},
    ])
    res = _decompose(tmp_path, payload)
    # refs slugified + deduped; non-strings and no-alphanumeric refs dropped (the
    # slugify "task" fallback must never invent a phantom ref).
    assert res.tasks[1]["depends_on"] == ["storage-module"]


def test_contract_notes_capped_and_control_chars_stripped(tmp_path):
    payload = json.dumps([
        {"task": "a-feature", "prompt": "p",
         "contract": {"creates": ["src/a.py"], "exports": [],
                      "notes": "line1\nline2\x00" + "x" * 500}},
    ])
    res = _decompose(tmp_path, payload)
    notes = res.tasks[0]["contract"]["notes"]
    assert len(notes) <= dc.CONTRACT_NOTES_MAX
    assert "\n" not in notes and "\x00" not in notes


def test_contract_lists_capped_and_cleaned(tmp_path):
    payload = json.dumps([
        {"task": "a-feature", "prompt": "p",
         "contract": {"creates": [f"f{i}.py" for i in range(100)] + [7, ""],
                      "exports": "not-a-list", "notes": 42}},
    ])
    res = _decompose(tmp_path, payload)
    contract = res.tasks[0]["contract"]
    assert len(contract["creates"]) == dc.CONTRACT_LIST_MAX
    assert contract["exports"] == [] and contract["notes"] == ""


def test_templates_elicit_graph_fields():
    # Both emission templates carry the graph elicitation; the pinned routing phrase
    # and the /no_think suppression survive the extension.
    for template in (dc._DECOMPOSE_TEMPLATE, dc._SPLIT_TEMPLATE):
        assert '"depends_on"' in template and '"contract"' in template
    assert "TOO LARGE to build and verify in one short" in dc._SPLIT_TEMPLATE
    assert dc._SPLIT_TEMPLATE.rstrip().endswith("/no_think")


def test_clean_contract_parity_with_plan_graph_ruler():
    # decompose's parse-side cleaning and plan_graph's load-side ruler share ONE
    # implementation — the caps can never drift (§10 S2).
    nasty = {"creates": ["ok.py", 3, "x" * 999], "exports": None,
             "notes": "a\x01b\n" + "y" * 400}
    fields = dc.clean_contract_fields(nasty)
    assert pg.clean_contract(nasty) == pg.TaskContract(**fields)


# ---------------------------------------------------------------------------
# Ruler re-mapping (collapse / dedupe / cap ⇒ refs scrubbed)
# ---------------------------------------------------------------------------


def test_ref_to_collapsed_scaffold_removed(tmp_path):
    payload = json.dumps([
        {"task": "setup-project", "prompt": "scaffold it", "depends_on": []},
        {"task": "add-todo-command", "prompt": "p", "depends_on": ["setup-project"]},
    ])
    res = _decompose(tmp_path, payload)
    assert [t["task"] for t in res.tasks] == ["add-todo-command"]  # scaffold collapsed
    assert res.tasks[0]["depends_on"] == []  # the dangling ref was scrubbed, key kept


def test_ref_to_collapsed_test_task_removed(tmp_path):
    payload = json.dumps([
        {"task": "implement-add-todo", "prompt": "p", "depends_on": []},
        {"task": "acceptance-tests", "prompt": "p", "depends_on": ["implement-add-todo"]},
        {"task": "list-todos", "prompt": "p", "depends_on": ["acceptance-tests"]},
    ])
    res = _decompose(tmp_path, payload)
    slugs = [t["task"] for t in res.tasks]
    assert "acceptance-tests" not in slugs
    by = {t["task"]: t for t in res.tasks}
    assert by["list-todos"]["depends_on"] == []  # ref to the dropped test task gone
    assert res.collapsed_test_intent is True


def test_ref_to_capped_away_task_removed(tmp_path):
    payload = json.dumps([
        {"task": "feature-a", "prompt": "p", "depends_on": []},
        {"task": "feature-b", "prompt": "p", "depends_on": ["feature-a", "feature-c"]},
        {"task": "feature-c", "prompt": "p", "depends_on": []},
    ])
    res = _decompose(tmp_path, payload, max_tasks=2)
    assert [t["task"] for t in res.tasks] == ["feature-a", "feature-b"]
    assert res.tasks[1]["depends_on"] == ["feature-a"]


def test_self_ref_removed_cross_ref_kept(tmp_path):
    payload = json.dumps([
        {"task": "feature-a", "prompt": "p", "depends_on": ["feature-a"]},
        {"task": "feature-b", "prompt": "p", "depends_on": ["feature-a"]},
    ])
    res = _decompose(tmp_path, payload)
    assert res.tasks[0]["depends_on"] == []
    assert res.tasks[1]["depends_on"] == ["feature-a"]


def test_dedupe_keeps_refs_resolving_to_survivor(tmp_path):
    payload = json.dumps([
        {"task": "Add Health", "prompt": "first", "depends_on": []},
        {"task": "add  health", "prompt": "dup", "depends_on": []},
        {"task": "status-page", "prompt": "p", "depends_on": ["Add Health"]},
    ])
    res = _decompose(tmp_path, payload)
    assert [t["task"] for t in res.tasks] == ["add-health", "status-page"]
    assert res.tasks[1]["depends_on"] == ["add-health"]


def test_split_children_graph_fields_survive(tmp_path):
    # The #691 oversize split runs the SAME parse+ruler, so child graphs carry too.
    proj = _projects(tmp_path)
    lump = json.dumps([{"task": "todo-app", "prompt": "build the whole todo app"}])
    children = json.dumps([
        {"task": "add-command", "prompt": "p", "depends_on": [],
         "contract": {"creates": ["src/add.py"], "exports": [], "notes": ""}},
        {"task": "list-command", "prompt": "p", "depends_on": ["add-command"]},
        {"task": "done-command", "prompt": "p", "depends_on": ["ghost-task"]},
    ])

    def gen(prompt):
        return children if "TOO LARGE to build and verify in one short" in prompt else lump

    res = dc.decompose_request(
        "a CLI todo app: add, list, and done commands", "myapp",
        generate_fn=gen, projects_dir=proj,
    )
    assert res.ok and res.split_oversize
    by = {t["task"]: t for t in res.tasks}
    assert by["list-command"]["depends_on"] == ["add-command"]
    assert by["done-command"]["depends_on"] == []  # unknown child ref scrubbed
    assert by["add-command"]["contract"]["creates"] == ["src/add.py"]


def test_graph_tasks_feed_plan_builder_waves(tmp_path):
    # End-to-end offline: decompose graph output -> build_plan_raw -> validate ->
    # waves. The W1/W2 seam actually composes.
    proj = _projects(tmp_path)
    res = _decompose(tmp_path, _GRAPH_PAYLOAD)
    raw = pg.build_plan_raw(plan_id="p1", goal="g", repo=str(proj / "myapp"),
                            tasks=res.tasks)
    validated = pg.validate_plan(raw, projects_dir=proj)
    assert validated.ok and not validated.degraded
    waves = pg.compile_waves(validated.plan)
    assert [[t.id for t in w] for w in waves] == [["storage-module"], ["add-command"]]
    assert validated.plan.tasks[0].contract.creates == ["src/storage.py"]


# ---------------------------------------------------------------------------
# Grammar hook — schema + transparent fail-soft fallback
# ---------------------------------------------------------------------------


def test_structured_fn_used_when_it_yields_parseable_json(tmp_path):
    calls = {"structured": 0, "free": 0}

    def structured(prompt, schema_text):
        calls["structured"] += 1
        schema = json.loads(schema_text)          # the hook hands a real JSON schema
        assert schema["type"] == "array" and schema["maxItems"] == dc.DEFAULT_MAX_TASKS
        assert "depends_on" in schema["items"]["properties"]
        return _GRAPH_PAYLOAD

    def free(prompt):
        calls["free"] += 1
        return "[]"

    proj = _projects(tmp_path)
    res = dc.decompose_request(
        "a budget tracker app: storage, add, list", "myapp",
        generate_fn=free, projects_dir=proj, structured_generate_fn=structured,
    )
    assert res.ok and res.used_grammar is True
    assert calls == {"structured": 1, "free": 0}  # the free path never fired
    assert res.tasks[1]["depends_on"] == ["storage-module"]


def test_structured_exception_falls_back_transparently(tmp_path):
    def structured(_prompt, _schema):
        raise RuntimeError("no StructuredOutputConfig on this build")

    res = _decompose(tmp_path, _GRAPH_PAYLOAD.replace("storage-module", "storage-mod"),
                     structured_generate_fn=structured)
    assert res.ok and not res.fell_back and res.used_grammar is False


def test_structured_empty_and_garbage_fall_back(tmp_path):
    for bad in ("", "   ", "not json at all"):
        res = _decompose(tmp_path, _GRAPH_PAYLOAD,
                         structured_generate_fn=lambda _p, _s, bad=bad: bad)
        assert res.ok and res.used_grammar is False and len(res.tasks) == 2


def test_both_paths_unusable_still_single_task_fallback(tmp_path):
    # The hook must never create a NEW failure mode: structured garbage + free-text
    # garbage still ends at the increment-1 single-task fallback, ok=True.
    res = _decompose(tmp_path, "lol no json",
                     structured_generate_fn=lambda _p, _s: "also no json")
    assert res.ok and res.fell_back and len(res.tasks) == 1 and not res.used_grammar


def test_no_hook_is_todays_path(tmp_path):
    res = _decompose(tmp_path, _GRAPH_PAYLOAD)
    assert res.ok and res.used_grammar is False


def test_plan_emission_schema_caps_mirror_cleaning():
    schema = dc.plan_emission_json_schema(max_tasks=5)
    assert schema["maxItems"] == 5
    item = schema["items"]
    assert item["required"] == ["task", "prompt"]
    assert item["additionalProperties"] is False
    contract = item["properties"]["contract"]["properties"]
    assert contract["notes"]["maxLength"] == dc.CONTRACT_NOTES_MAX
    assert contract["creates"]["maxItems"] == dc.CONTRACT_LIST_MAX
    assert contract["creates"]["items"]["maxLength"] == dc.CONTRACT_ITEM_MAX


# ---------------------------------------------------------------------------
# Calibration scorer (evals/plan_calibration.py)
# ---------------------------------------------------------------------------

# The W9 (Lane V) real B1 gold plan — superseded the Lane A provisional one at merge
# (#740 supersede-don't-extend). Same JobPlan v1 shape the scorer reads (tasks + deps +
# contract), so the calibration scorer tests point here.
_GOLD_PATH = (Path(__file__).resolve().parents[2] / "evals" / "battery" / "gold" /
              "gold-b1.json")


def _gold() -> dict:
    return json.loads(_GOLD_PATH.read_text(encoding="utf-8"))


def test_provisional_gold_scores_perfect_against_itself():
    gold = _gold()
    score = cal.score_plan(gold, gold, gold_name="self")
    assert score.task_count_match
    assert score.edge_f1 == 1.0 and score.edge_precision == 1.0 and score.edge_recall == 1.0
    assert score.contract_file_jaccard == 1.0


def test_disjoint_candidate_scores_zero():
    gold = _gold()
    candidate = [
        {"repo": "r", "task": "alpha", "prompt": "p", "depends_on": []},
        {"repo": "r", "task": "beta", "prompt": "p", "depends_on": ["alpha"]},
    ]
    score = cal.score_plan(candidate, gold)
    assert not score.task_count_match
    assert score.edge_f1 == 0.0 and score.contract_file_jaccard == 0.0


def test_partial_edge_f1_known_value():
    gold = {"tasks": [
        {"id": "a", "depends_on": []},
        {"id": "b", "depends_on": ["a"]},
        {"id": "c", "depends_on": ["b"]},
    ]}
    candidate = {"tasks": [
        {"id": "a", "depends_on": []},
        {"id": "b", "depends_on": ["a"]},
        {"id": "c", "depends_on": ["a"]},   # one right edge, one wrong edge
    ]}
    score = cal.score_plan(candidate, gold)
    assert score.edge_precision == 0.5 and score.edge_recall == 0.5 and score.edge_f1 == 0.5


def test_alignment_tolerates_renamed_slugs():
    gold = {"tasks": [
        {"id": "storage-module", "depends_on": []},
        {"id": "add-command", "depends_on": ["storage-module"]},
    ]}
    candidate = {"tasks": [
        {"id": "expense-storage-module", "depends_on": []},
        {"id": "add-expense-command", "depends_on": ["expense-storage-module"]},
    ]}
    score = cal.score_plan(candidate, gold)
    assert dict(score.alignment) == {
        "expense-storage-module": "storage-module",
        "add-expense-command": "add-command",
    }
    assert score.edge_f1 == 1.0  # the edge survives through the alignment


def test_scorer_tolerates_decompose_task_list_shape(tmp_path):
    gold = _gold()
    res = _decompose(tmp_path, _GRAPH_PAYLOAD)
    score = cal.score_plan(res.tasks, gold)
    # gold_task_count derived from the gold (not a magic number) so the test survives a
    # gold edit; candidate is the fixed 2-task _GRAPH_PAYLOAD decompose output.
    assert score.candidate_task_count == 2
    assert score.gold_task_count == len(gold["tasks"])
    assert 0.0 <= score.edge_f1 <= 1.0


def test_no_edge_conventions():
    empty_gold = {"tasks": [{"id": "a"}, {"id": "b"}]}
    empty_cand = {"tasks": [{"id": "a"}, {"id": "b"}]}
    assert cal.score_plan(empty_cand, empty_gold).edge_f1 == 1.0  # both edgeless ⇒ 1.0
    chained = {"tasks": [{"id": "a"}, {"id": "b", "depends_on": ["a"]}]}
    assert cal.score_plan(empty_cand, chained).edge_f1 == 0.0     # missed real edges


def test_markdown_report_carries_metrics():
    gold = _gold()
    n = len(gold["tasks"])  # gold scored against itself ⇒ a perfect n/n task match
    report = cal.render_markdown(
        [cal.score_plan(gold, gold, gold_name="gold-b1")], candidate_name="self.json")
    assert "gold-b1" in report and f"| {n}/{n} " in report and "1.00" in report
    assert "Edge F1" in report and "alignment:" in report


def test_cli_scores_and_writes_report(tmp_path, capsys):
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(_GOLD_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    report_path = tmp_path / "report.md"
    rc = cal.main(["--candidate", str(candidate_path),
                   "--gold", str(_GOLD_PATH), "--report", str(report_path)])
    assert rc == 0
    assert "calibration report" in report_path.read_text(encoding="utf-8")
    assert "1.00" in capsys.readouterr().out


def test_cli_fails_loud_on_unreadable_input(tmp_path):
    assert cal.main(["--candidate", str(tmp_path / "absent.json"),
                     "--gold", str(_GOLD_PATH)]) == 2
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    good = tmp_path / "cand.json"
    good.write_text("[]", encoding="utf-8")
    assert cal.main(["--candidate", str(good), "--gold", str(bad)]) == 2


# ---------------------------------------------------------------------------
# #748 — deterministic JSON repair (the live-verify tail-defect class)
# ---------------------------------------------------------------------------

# The EXACT live failure shape (2026-07-05 run 3, abridged): a valid 8-task graph
# whose FINAL task object is closed with ']]' instead of '}]' — json.loads fails,
# and pre-repair the whole graph collapsed to the minimal single-task fallback.
_LIVE_TAIL_DEFECT = (
    '[{"task": "create-storage-module", "prompt": "Implement a storage module.",'
    ' "depends_on": [], "contract": {"creates": ["storage.py"],'
    ' "exports": ["save_expenses"], "notes": "JSON ops"}},'
    ' {"task": "implement-add-command", "prompt": "Implement the add command.",'
    ' "depends_on": ["create-storage-module"], "contract": {"creates": ["add.py"],'
    ' "exports": ["add_expense"], "notes": "CLI add"}},'
    ' {"task": "implement-list-command", "prompt": "Implement the list command.",'
    ' "depends_on": ["create-storage-module"], "contract": {"creates": ["list.py"],'
    ' "exports": ["list_expenses"], "notes": "CLI list"}]]'
)


def test_repair_salvages_the_live_tail_defect():
    cands = dc._parse_candidates(_LIVE_TAIL_DEFECT, max_tasks=8)
    assert [c["task"] for c in cands] == [
        "create-storage-module", "implement-add-command", "implement-list-command",
    ]
    # The graph fields survive the repair intact.
    assert cands[1]["depends_on"] == ["create-storage-module"]
    assert cands[2]["contract"]["exports"] == ["list_expenses"]


def test_repair_closes_unterminated_tail():
    # Budget-truncation shape: the array just stops mid-object.
    truncated = ('[{"task": "a", "prompt": "build a"},'
                 ' {"task": "b", "prompt": "build b", "depends_on": ["a"')
    cands = dc._parse_candidates(truncated, max_tasks=8)
    # Task a is fully salvaged; b's unterminated depends_on closes cleanly.
    assert cands and cands[0]["task"] == "a"


def test_repair_drops_dangling_comma_before_inserted_closer():
    dangling = '[{"task": "a", "prompt": "build a"},'
    cands = dc._parse_candidates(dangling, max_tasks=8)
    assert [c["task"] for c in cands] == ["a"]


def test_repair_never_touches_valid_json():
    # Bracket/brace characters INSIDE strings must not confuse the walk, and a
    # valid payload must parse identically with the repair path never invoked.
    payload = ('[{"task": "a", "prompt": "use data[0] and {curly} literals"},'
               ' {"task": "b", "prompt": "plain"}]')
    cands = dc._parse_candidates(payload, max_tasks=8)
    assert [c["task"] for c in cands] == ["a", "b"]
    assert cands[0]["prompt"] == "use data[0] and {curly} literals"


def test_repair_gives_up_honestly_on_garbage():
    # Repair must not invent a plan out of noise — today's [] fallback holds.
    assert dc._parse_candidates("[[[[{{{{,,,,", max_tasks=8) == []
    assert dc._parse_candidates('["just", "strings"]', max_tasks=8) == []
