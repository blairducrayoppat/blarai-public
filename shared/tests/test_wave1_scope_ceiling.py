"""#989 — wave-1 over-production controls: the per-task SCOPE CEILING, the plan-time
CONTRACT-COVERAGE check, and the post-merge SCOPE-SPRAWL finding.

The measured defect (#989 c.2299): a wave-1 ROOT task frequently built the ENTIRE app.
Root cause was three-part — the context-pack instruction never composes for a task with
no ``depends_on`` (``context_pack.context_pack_for_task`` returns ``''``), the driver
hands EVERY task the whole app's oracle module interface, and no task was ever shown its
own ``contract.creates`` boundary. Coverage between the oracle's import surface and the
build tasks' contracts was the card-level predictor (clean cards are 1:1).

Locks here drive the REAL entry points — ``SwapDriver`` through injected ``SwapOps``
seams (the plan §4.3 requirement that makes the wave loop model-free testable) and
``generate_plan`` with an injected ``generate_fn`` — never mock shapes of them.
"""

from __future__ import annotations

import json
from pathlib import Path

from shared.fleet import plan_graph as pg
from shared.fleet import swap_driver as sd
from shared.fleet.acceptance import (
    DecompositionOverride,
    generate_plan,
)
from shared.fleet.context_pack import contract_coverage
from shared.fleet.dispatch import TaskOutcome

# ---------------------------------------------------------------------------
# Fixtures / helpers (the test_integration_gate harness idiom)
# ---------------------------------------------------------------------------


def _mk_repo(tmp_path: Path, name: str = "proj") -> Path:
    repo = tmp_path / name
    (repo / ".git").mkdir(parents=True, exist_ok=True)
    return repo


def _diamond_tasks(repo: Path) -> list[dict]:
    """A B2-shaped 4-arm diamond with 1:1 contracts under the ``app`` package."""
    return [
        {"repo": str(repo), "task": "tokenize", "prompt": "build tokenize",
         "depends_on": [],
         "contract": {"creates": ["app/__init__.py", "app/tokenize.py"],
                      "exports": ["tokenize(text)"], "notes": "token list"}},
        {"repo": str(repo), "task": "word-frequencies", "prompt": "build word freq",
         "depends_on": ["tokenize"],
         "contract": {"creates": ["app/word_frequencies.py"],
                      "exports": ["word_frequencies(tokens)"], "notes": ""}},
        {"repo": str(repo), "task": "report", "prompt": "build report",
         "depends_on": ["word-frequencies"],
         "contract": {"creates": ["app/report.py"],
                      "exports": ["combined_report(text)"], "notes": ""}},
    ]


_ORACLE_PY = """\
from app.tokenize import tokenize
from app.word_frequencies import word_frequencies
from app.report import combined_report


def test_join():
    assert "the" in combined_report("the cat the")
"""


def _build_plan(tmp_path: Path, tasks: list[dict], *, run_id: str = "R1") -> pg.JobPlan:
    raw = pg.build_plan_raw(
        plan_id=run_id, goal="a text stats toolkit", repo=str(tasks[0]["repo"]),
        tasks=tasks, criteria=["reports word stats"],
    )
    result = pg.validate_plan(raw, projects_dir=tmp_path)
    assert result.ok and result.plan is not None
    return result.plan


def _merged(task):
    return TaskOutcome(task=task["task"], outcome="processed", result="MERGED",
                       detail="RESULT: MERGED to main")


def _ops(calls, **overrides):
    base = dict(
        available_gb=lambda: 26.0,
        backend_alive=lambda: False,
        load_30b=lambda: (calls.append("load"), True)[1],
        wait_ready=lambda: True,
        run_task=lambda t: (calls.append(("task", t["task"], t["prompt"])), _merged(t))[1],
        cancel_requested=lambda: False,
        disarm_watchdog=lambda: calls.append("disarm"),
        stop_ovms=lambda: calls.append("stop"),
        write_report=lambda rid, outs: calls.append(("report", rid, len(outs))),
        restart_launcher=lambda: calls.append("restart"),
        backend_ready=lambda: True,
        signal_failure=lambda msg: calls.append(("signal", msg)),
        run_wave_gate=lambda repo: {"ok": True, "evidence": "verify=pass"},
        run_job_oracle=lambda repo, rel: {"status": "passed", "evidence": "exit 0"},
        write_scorecard=lambda sc: calls.append(("scorecard", sc)),
        write_job_summary=lambda text: calls.append(("job_summary", text)),
        log_pack=lambda tid, pack: calls.append(("pack", tid, pack)),
    )
    base.update(overrides)
    return sd.SwapOps(**base)


def _driver(tmp_path, ops, tasks, plan, **kw):
    store = pg.PlanStore(tmp_path / "plan.json", projects_dir=tmp_path)
    return sd.SwapDriver(
        run_id="R1", session_id="s1", tasks=tasks,
        swap_state_path=tmp_path / "swap.json", ops=ops,
        gate_gb=21.0, sleep=lambda _s: None,
        plan=store.write(plan), plan_store=store, **kw,
    )


def _scorecard(calls) -> dict:
    for c in calls:
        if isinstance(c, tuple) and c[0] == "scorecard":
            return c[1]
    raise AssertionError("no scorecard emitted")


def _ran_prompt(calls, task_id: str) -> str:
    for c in calls:
        if isinstance(c, tuple) and c[0] == "task" and c[1] == task_id:
            return c[2]
    raise AssertionError(f"task {task_id!r} never ran")


# ---------------------------------------------------------------------------
# (a) The SCOPE CEILING — every composed prompt states the task's own boundary
# ---------------------------------------------------------------------------


def test_root_task_prompt_carries_its_own_scope_ceiling(tmp_path):
    """THE defect lock: a ROOT task (no depends_on ⇒ no context pack ever composes)
    must still be told its own boundary — build ONLY its contracted deliverables."""
    repo = _mk_repo(tmp_path)
    tasks = _diamond_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []
    _driver(tmp_path, _ops(calls), tasks, plan).run()
    prompt = _ran_prompt(calls, "tokenize")
    assert "SCOPE — this task builds ONLY its own contracted deliverable(s)" in prompt
    assert "`app/tokenize.py`" in prompt
    # The sibling deliverables are named as NOT this task's to create.
    assert "NOT yours to create" in prompt
    assert "`app/word_frequencies.py`" in prompt
    assert "`app/report.py`" in prompt


def test_ceiling_reaches_root_even_with_oracle_interface_block(tmp_path):
    """The whole-app interface block (#790 rec-1) and the ceiling COEXIST: the task
    sees the final interface AND which slice of it is its own."""
    repo = _mk_repo(tmp_path)
    tasks = _diamond_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []
    ops = _ops(calls, job_oracle_contract=lambda: [
        "from app.tokenize import tokenize",
        "from app.word_frequencies import word_frequencies",
        "from app.report import combined_report",
    ])
    _driver(tmp_path, ops, tasks, plan).run()
    prompt = _ran_prompt(calls, "tokenize")
    assert "Provide these EXACT module paths" in prompt
    interface_at = prompt.index("Provide these EXACT module paths")
    ceiling_at = prompt.index("SCOPE — this task builds ONLY")
    assert ceiling_at > interface_at  # ceiling qualifies the interface, in that order


def test_dependent_task_gets_ceiling_too(tmp_path):
    repo = _mk_repo(tmp_path)
    tasks = _diamond_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []
    _driver(tmp_path, _ops(calls), tasks, plan).run()
    prompt = _ran_prompt(calls, "report")
    assert "`app/report.py`" in prompt
    assert "NOT yours to create" in prompt
    assert "`app/tokenize.py`" in prompt  # a sibling's deliverable, named off-limits


def test_no_ceiling_without_any_contract_creates(tmp_path):
    """No contracts anywhere ⇒ no boundary is derivable ⇒ prompts are unchanged
    (the plan-time coverage check is the surface that flags this plan shape)."""
    repo = _mk_repo(tmp_path)
    tasks = [
        {"repo": str(repo), "task": "a", "prompt": "pa", "depends_on": []},
        {"repo": str(repo), "task": "b", "prompt": "pb", "depends_on": ["a"]},
    ]
    plan = _build_plan(tmp_path, tasks)
    calls = []
    _driver(tmp_path, _ops(calls), tasks, plan).run()
    for tid in ("a", "b"):
        prompt = _ran_prompt(calls, tid)
        assert "SCOPE —" not in prompt
        assert "NOT yours to create" not in prompt


def test_single_task_plan_gets_no_ceiling(tmp_path):
    """A one-task plan legitimately owns everything — a ceiling would be nonsense.

    Exercised at the composition seam (``_fleet_task_for``) DIRECTLY because no wave
    loop can reach this shape today — ``build_job_plan`` declines <2-task plans into
    the flat queue — so the lock guards the derivation rule itself against any future
    caller composing a one-task plan through this seam."""
    repo = _mk_repo(tmp_path)
    tasks = [{"repo": str(repo), "task": "solo", "prompt": "build it all",
              "depends_on": [],
              "contract": {"creates": ["app/core.py"], "exports": [], "notes": ""}}]
    raw = pg.build_plan_raw(plan_id="R1", goal="g", repo=str(repo), tasks=tasks,
                            criteria=["works"])
    result = pg.validate_plan(raw, projects_dir=tmp_path)
    assert result.ok and result.plan is not None
    driver = _driver(tmp_path, _ops([]), tasks, result.plan)
    composed = driver._fleet_task_for(result.plan.tasks[0])
    assert "SCOPE —" not in composed["prompt"]


def test_empty_own_contract_still_gets_negative_ceiling(tmp_path):
    """A task the planner left contract-less is exactly the unanchored over-producer:
    it still gets the NEGATIVE boundary (siblings' files named off-limits)."""
    repo = _mk_repo(tmp_path)
    tasks = [
        {"repo": str(repo), "task": "loose", "prompt": "pl", "depends_on": []},
        {"repo": str(repo), "task": "storage", "prompt": "ps", "depends_on": [],
         "contract": {"creates": ["app/storage.py"], "exports": ["save(x)"],
                      "notes": ""}},
    ]
    plan = _build_plan(tmp_path, tasks)
    calls = []
    _driver(tmp_path, _ops(calls), tasks, plan).run()
    prompt = _ran_prompt(calls, "loose")
    assert "SCOPE — this task builds ONLY" not in prompt  # nothing to name positively
    assert "NOT yours to create" in prompt
    assert "`app/storage.py`" in prompt


# ---------------------------------------------------------------------------
# (b) Plan-time CONTRACT-COVERAGE — the pure check and the generate_plan surface
# ---------------------------------------------------------------------------


def test_contract_coverage_clean_one_to_one_card(tmp_path):
    repo = _mk_repo(tmp_path)
    coverage = contract_coverage(
        _diamond_tasks(repo), "tests/test_job_acceptance.py", _ORACLE_PY)
    assert coverage is not None
    assert coverage["tasks"] == 3 and coverage["targets"] == 3
    assert coverage["uncovered_tasks"] == []
    assert coverage["orphan_imports"] == []


def test_contract_coverage_names_the_unanchored_task(tmp_path):
    repo = _mk_repo(tmp_path)
    tasks = _diamond_tasks(repo)
    tasks[1]["contract"] = {"creates": [], "exports": [], "notes": ""}  # word-frequencies
    coverage = contract_coverage(tasks, "tests/test_job_acceptance.py", _ORACLE_PY)
    assert coverage is not None
    assert coverage["uncovered_tasks"] == ["word-frequencies"]
    # …and the import it should have owned is now an orphan, named verbatim.
    assert coverage["orphan_imports"] == [
        "from app.word_frequencies import word_frequencies"]


def test_contract_coverage_names_the_orphan_module_b4_shape(tmp_path):
    """The B4 shape: the oracle imports a module NO task's contract creates."""
    repo = _mk_repo(tmp_path)
    oracle = _ORACLE_PY + "\nfrom app.data_storage import load_cards\n"
    coverage = contract_coverage(
        _diamond_tasks(repo), "tests/test_job_acceptance.py", oracle)
    assert coverage is not None
    assert "from app.data_storage import load_cards" in coverage["orphan_imports"]


def test_contract_coverage_not_computable_without_oracle():
    assert contract_coverage([{"task": "a"}], "tests/test_job_acceptance.py", "") is None
    assert contract_coverage([{"task": "a"}], "", "") is None


def test_generate_plan_surfaces_coverage_warning_loudly(tmp_path, caplog):
    """Through the REAL plan entry point: a card whose oracle covers only one of two
    build tasks must surface the warning in the PlanResult message AND the log."""
    projects = tmp_path / "projects"
    repo = projects / "battery-demo"
    (repo / ".git").mkdir(parents=True)
    override = DecompositionOverride(
        tasks=[
            {"repo": str(repo), "task": "storage", "prompt": "build storage",
             "depends_on": [],
             "contract": {"creates": ["app/storage.py"], "exports": ["save(x)"],
                          "notes": ""}},
            {"repo": str(repo), "task": "reports", "prompt": "build reports",
             "depends_on": ["storage"],
             "contract": {"creates": ["app/reports.py"], "exports": [], "notes": ""}},
        ],
        job_oracle_code="from app.storage import save\n\n\ndef test_save():\n    assert save\n",
        job_oracle_path="tests/test_job_acceptance.py",
    )
    import logging as _logging

    with caplog.at_level(_logging.WARNING, logger="shared.fleet.acceptance"):
        result = generate_plan(
            "a demo app", "battery-demo", generate_fn=lambda p: "",
            projects_dir=projects, decomposition_override=override,
        )
    assert result.ok
    assert "CONTRACT-COVERAGE WARNING" in result.message
    assert "reports" in result.message  # the unanchored task, named
    assert any("CONTRACT-COVERAGE WARNING" in r.message for r in caplog.records)


def test_generate_plan_clean_coverage_message_unchanged(tmp_path):
    projects = tmp_path / "projects"
    repo = projects / "battery-demo"
    (repo / ".git").mkdir(parents=True)
    override = DecompositionOverride(
        tasks=[
            {"repo": str(repo), "task": "storage", "prompt": "build storage",
             "depends_on": [],
             "contract": {"creates": ["app/storage.py"], "exports": ["save(x)"],
                          "notes": ""}},
            {"repo": str(repo), "task": "reports", "prompt": "build reports",
             "depends_on": ["storage"],
             "contract": {"creates": ["app/reports.py"],
                          "exports": ["render()"], "notes": ""}},
        ],
        job_oracle_code=(
            "from app.storage import save\nfrom app.reports import render\n\n\n"
            "def test_both():\n    assert save and render\n"
        ),
        job_oracle_path="tests/test_job_acceptance.py",
    )
    result = generate_plan(
        "a demo app", "battery-demo", generate_fn=lambda p: "",
        projects_dir=projects, decomposition_override=override,
    )
    assert result.ok
    assert "CONTRACT-COVERAGE WARNING" not in result.message


# ---------------------------------------------------------------------------
# (c) The post-merge SCOPE-SPRAWL finding — named, recorded, never a verdict input
# ---------------------------------------------------------------------------


def _sprawl_ops(calls, added_by_task, *, files_by_task=None, **overrides):
    """Ops whose ``dep_delta`` returns the MOST RECENTLY merged task's delta —
    ``added`` (what the sprawl recorder keys on) and ``files`` (what packs read;
    defaults to ``added`` — a fresh-build merge creates what it changes)."""
    heads = iter([f"{i:040x}" for i in range(1, 20)])
    task_seen: list[str] = []

    def run_task(t):
        task_seen.append(t["task"])
        calls.append(("task", t["task"], t["prompt"]))
        return _merged(t)

    def dep_delta(_r, _b, _m):
        added = added_by_task.get(task_seen[-1], [])
        files = (files_by_task or added_by_task).get(task_seen[-1], [])
        return {"files": files, "added": added, "signatures": []}

    return _ops(calls, repo_head=lambda _r: next(heads, ""),
                run_task=run_task, dep_delta=dep_delta, **overrides)


def test_scope_sprawl_recorded_as_named_finding(tmp_path):
    """A merged root task that authored a SIBLING-contracted file gets a NAMED
    finding — progress trail + scorecard evidence — and the merge stands."""
    repo = _mk_repo(tmp_path)
    tasks = _diamond_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []
    progress: list[str] = []
    ops = _sprawl_ops(calls, {
        # tokenize (wave 1) also authored report's module — the #989 shape.
        "tokenize": ["app/tokenize.py", "app/report.py"],
        "word-frequencies": ["app/word_frequencies.py"],
        "report": ["app/report.py"],
    }, write_progress=lambda m: progress.append(m))
    _driver(tmp_path, ops, tasks, plan).run()
    sc = _scorecard(calls)
    assert sc["evidence"]["scope_sprawl"] == "tokenize: app/report.py (report)"
    assert "scope-sprawl finding(s)" in sc["notes"]
    assert any("Scope-sprawl finding [tokenize]" in m for m in progress)
    # A finding NEVER touches the verdict: everything merged + oracle passed = GREEN.
    assert sc["verdict"] == "GREEN"
    assert {t["id"]: t["status"] for t in sc["tasks"]} == {
        "tokenize": "merged", "word-frequencies": "merged", "report": "merged"}


def test_clean_merges_record_no_sprawl(tmp_path):
    repo = _mk_repo(tmp_path)
    tasks = _diamond_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []
    ops = _sprawl_ops(calls, {
        "tokenize": ["app/__init__.py", "app/tokenize.py", "tests/test_tokenize.py"],
        "word-frequencies": ["app/word_frequencies.py"],
        "report": ["app/report.py", "tests/test_report.py"],
    })
    _driver(tmp_path, ops, tasks, plan).run()
    sc = _scorecard(calls)
    assert "scope_sprawl" not in sc["evidence"]
    assert "scope-sprawl" not in sc["notes"]


def test_editing_a_sibling_owned_file_is_not_sprawl(tmp_path):
    """F3 lock: the finding keys on file CREATION (the delta's ``added`` list), so a
    task that legitimately EDITS a sibling-owned file (a re-export line added to a
    sibling's module — in ``files`` but not ``added``) records NO finding."""
    repo = _mk_repo(tmp_path)
    tasks = _diamond_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []
    ops = _sprawl_ops(
        calls,
        {  # added: each task creates only its own contracted modules
            "tokenize": ["app/__init__.py", "app/tokenize.py"],
            "word-frequencies": ["app/word_frequencies.py"],
            "report": [],
        },
        files_by_task={  # …but report also EDITED tokenize's module (integration)
            "tokenize": ["app/__init__.py", "app/tokenize.py"],
            "word-frequencies": ["app/word_frequencies.py"],
            "report": ["app/report.py", "app/tokenize.py"],
        },
    )
    _driver(tmp_path, ops, tasks, plan).run()
    sc = _scorecard(calls)
    assert "scope_sprawl" not in sc["evidence"]


def test_delta_without_added_key_records_nothing(tmp_path):
    """A seam that does not distinguish adds (no ``added`` key) is UNMEASURED — the
    recorder must not guess sprawl from the edit-inclusive ``files`` list."""
    repo = _mk_repo(tmp_path)
    tasks = _diamond_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []
    heads = iter([f"{i:040x}" for i in range(1, 20)])
    ops = _ops(calls, repo_head=lambda _r: next(heads, ""),
               dep_delta=lambda _r, _b, _m: {
                   "files": ["app/report.py"], "signatures": []})
    _driver(tmp_path, ops, tasks, plan).run()
    sc = _scorecard(calls)
    assert "scope_sprawl" not in sc["evidence"]


def test_real_dep_delta_added_excludes_edited_files(tmp_path):
    """The REAL seam contract (swap_ops.real_dep_delta): ``added`` carries only the
    files the range CREATED (--diff-filter=A); ``files`` carries edits too."""
    import subprocess

    from shared.fleet.swap_ops import real_dep_delta

    repo = tmp_path / "delta-repo"
    repo.mkdir()

    def _git(*args: str) -> str:
        cp = subprocess.run(
            # Hermetic fixture identity/signing config — a throwaway tmp repo, not
            # an operator repo (no global config leaks into the fixture commits).
            ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t",
             "-c", "commit.gpgsign=false", *args],
            capture_output=True, text=True,
        )
        assert cp.returncode == 0, cp.stderr
        return cp.stdout.strip()

    _git("init", "-q")
    (repo / "existing.py").write_text("def old():\n    pass\n", encoding="utf-8")
    _git("add", "existing.py")
    _git("commit", "-q", "-m", "base")
    base = _git("rev-parse", "HEAD")
    (repo / "existing.py").write_text("def old():\n    return 1\n", encoding="utf-8")
    (repo / "created.py").write_text("def fresh():\n    return 2\n", encoding="utf-8")
    _git("add", "existing.py", "created.py")
    _git("commit", "-q", "-m", "merge")
    merge = _git("rev-parse", "HEAD")

    delta = real_dep_delta(str(repo), base, merge)
    assert sorted(delta["files"]) == ["created.py", "existing.py"]
    assert delta["added"] == ["created.py"]


def test_sprawl_delta_failure_degrades_to_no_finding(tmp_path):
    """An evidence recorder, not a control path: a raising delta seam records
    nothing and the run completes exactly as before."""
    repo = _mk_repo(tmp_path)
    tasks = _diamond_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []

    def boom(_r, _b, _m):
        raise RuntimeError("git unavailable")

    heads = iter([f"{i:040x}" for i in range(1, 20)])
    ops = _ops(calls, repo_head=lambda _r: next(heads, ""), dep_delta=boom)
    result = _driver(tmp_path, ops, tasks, plan).run()
    assert result.outcome == "complete"
    sc = _scorecard(calls)
    assert "scope_sprawl" not in sc["evidence"]


def test_scorecard_scope_sprawl_evidence_is_single_line_and_bounded(tmp_path):
    """The adopter's validate demands single-line, bounded evidence values."""
    repo = _mk_repo(tmp_path)
    tasks = _diamond_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    sprawl = {"tokenize": [f"app/mod_{i}.py (report)" for i in range(60)]}
    sc = sd.build_scorecard(
        plan, run_id="R1", outcomes=[], wave_gates=[], job_evidence="",
        cancelled=False, stopped=False, degraded=False, packs_consumed=0,
        wall_clock_s=1.0, scope_sprawl=sprawl,
    )
    value = sc["evidence"]["scope_sprawl"]
    assert "\n" not in value and len(value) <= 498
    # JSON-serializable end to end (the scorecard is a machine artifact).
    json.dumps(sc)


def test_scorecard_scope_sprawl_evidence_strips_control_characters(tmp_path):
    """F5 lock: file names originate in git bytes, so the stamp site must enforce
    the adopter's single-line contract itself — control characters (newlines, BEL,
    NULs) are stripped to spaces, never passed through."""
    repo = _mk_repo(tmp_path)
    tasks = _diamond_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    sprawl = {"tokenize": ["evil\nfile\x07.py (report)", "app/x\x00\x1f.py (report)"]}
    sc = sd.build_scorecard(
        plan, run_id="R1", outcomes=[], wave_gates=[], job_evidence="",
        cancelled=False, stopped=False, degraded=False, packs_consumed=0,
        wall_clock_s=1.0, scope_sprawl=sprawl,
    )
    value = sc["evidence"]["scope_sprawl"]
    assert "\n" not in value and "\r" not in value
    assert not any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value)
    assert len(value) <= 498
    # The payload survives, control bytes replaced by spaces — still a named finding.
    assert "evil file .py (report)" in value
    assert value.startswith("tokenize: ")


def test_coverage_crash_is_logged_not_silent(monkeypatch, caplog):
    """F2 lock: a crashing coverage derivation fails SOFT ('' — the plan proceeds)
    but never SILENT — the crash lands on the acceptance logger, named UNMEASURED.

    Toggle-off teeth by construction: the pre-fix except body was bare (``return
    ''`` alone), under which the return-value assert still passes and ONLY the
    caplog assert fails — the log line IS what this lock pins."""
    import logging as _logging

    from shared.fleet import acceptance as acc

    def boom(_tasks, _rel, _code):
        raise RuntimeError("poisoned coverage")

    monkeypatch.setattr(acc, "contract_coverage", boom)
    with caplog.at_level(_logging.WARNING, logger="shared.fleet.acceptance"):
        out = acc._plan_contract_coverage_warning(
            [{"task": "a"}], "tests/test_job_acceptance.py", "import app\n")
    assert out == ""  # fail-soft: the plan request survives
    records = [r for r in caplog.records if "contract-coverage check crashed" in r.message]
    assert records, "the crash must land on the acceptance logger, not vanish"
    assert "UNMEASURED" in records[0].message
    assert "not a clean bill" in records[0].message
    assert "RuntimeError" in records[0].message
