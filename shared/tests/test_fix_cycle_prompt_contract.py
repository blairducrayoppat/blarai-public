"""#1075 collateral — a fix-cycle prompt must agree with the import form it interpolates.

The layout and executability fix cycles are the driver's two "re-run the owning task with
the exact problem named" repairs. Both hardcoded a FLAT-module contract — *"provide these
EXACT importable names at the TOP-LEVEL module path the oracle imports (do NOT nest them
inside an app/ or src/ package)"* — while interpolating whatever the probe actually found.
When the job's oracle imports a PACKAGE (``from app.card_entry import add_card`` — the
shape ``canonical_package_from_contract`` derives and the scaffold seeder builds), the
prompt told the coder to do the opposite of the contract the very same prompt was quoting.

That contradiction had never reached a coder, because run-fleet's dedup guard refused every
repair re-dispatch first (#1075). Fixing the guard exposes it immediately, so both land
together and both are locked here: the prompt must state the contract, never fight it.

The existing #822/#830 gate tests all use a flat contract (``from cli_interface import
run_cli``), which is exactly why the package case stayed invisible — these drive the REAL
driver through the REAL gate with a PACKAGE contract instead.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from shared.fleet import plan_graph as pg
from shared.fleet import swap_driver as sd
from shared.fleet.context_pack import canonical_package_from_contract
from shared.fleet.dispatch import TaskOutcome

#: B4's real shape: the oracle imports through the `app` package the seeder created.
PACKAGE_CONTRACT = ["from app.card_entry import add_card"]
PACKAGE_UNRESOLVED = [{
    "raw": "from app.card_entry import add_card",
    "module": "app.card_entry",
    "name": "add_card",
    "reason": "module 'app.card_entry' does not resolve from the repo root",
}]

#: Phrasings that FORBID the package layout a dotted contract requires. Absence is the lock.
#:
#: These are DIRECTIVES, matched case-INSENSITIVELY — not a substring blocklist of the words
#: themselves (#1075 F5). Two reasons, both worth stating because the first version got both
#: wrong:
#:   * a case-sensitive list is not a lock at all — a lowercase reintroduction sails through it;
#:   * blocklisting the bare noun "top-level module" collides with the prompt's own legitimate
#:     description of the FLAT case ("an undotted path names a top-level module"), which the
#:     non-regression test below asserts IS present. Those two assertions coexisted only by
#:     letter case, so whoever normalised the prompt's capitalisation would have tripped one or
#:     silently disarmed the other. Ban the INSTRUCTION, never the noun.
#:
#: LIMIT — do not read the toggle-off rows below as completeness. This is a blocklist of KNOWN
#: phrasings, and a novel one ("keep everything flat at the repo root") escapes all five. The
#: durable protection is the POSITIVE assertion each test also makes — that the prompt states
#: the dotted-path package rule — because that cannot be evaded by rewording a prohibition.
PACKAGE_PROHIBITIONS = (
    r"do\s*n[o']?t\s+nest",
    r"never\s+nest",
    r"(?:app|src)/\s*or\s*(?:app|src)/",
    r"must\s+be\s+importable\s+as\s+a\s+top-level\s+module",
    r"at\s+the\s+top-level\s+(?:module\s+)?path\s+the\s+\w+\s+imports",
)


def _assert_no_package_prohibition(prompt: str, what: str) -> None:
    for pattern in PACKAGE_PROHIBITIONS:
        found = re.search(pattern, prompt, re.IGNORECASE)
        assert found is None, (
            f"the {what} prompt still forbids the package layout — pattern {pattern!r} matched "
            f"{found.group(0)!r} — while interpolating a package import, so the coder would be "
            "steered off the very contract the prompt is quoting"
        )


def _mk_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "proj"
    (repo / ".git").mkdir(parents=True, exist_ok=True)
    return repo


def _tasks(repo: Path) -> list[dict]:
    """2-task chain whose `cards` task OWNS app/card_entry.py — the fix target."""
    return [
        {"repo": str(repo), "task": "core", "prompt": "build core", "depends_on": [],
         "contract": {"creates": ["app/core.py"], "exports": ["helper()"]}},
        {"repo": str(repo), "task": "cards", "prompt": "build the card entry",
         "depends_on": ["core"],
         "contract": {"creates": ["app/card_entry.py"], "exports": ["add_card()"]}},
    ]


def _plan(tmp_path: Path, tasks: list[dict]) -> pg.JobPlan:
    raw = pg.build_plan_raw(
        plan_id="R1", goal="a flashcard app", repo=str(tasks[0]["repo"]), tasks=tasks,
        criteria=["adds a card", "lists cards"],
    )
    result = pg.validate_plan(raw, projects_dir=tmp_path)
    assert result.ok and result.plan is not None
    return result.plan


def _ops(calls, **overrides):
    def _merged(t):
        return TaskOutcome(task=t["task"], outcome="processed", result="MERGED",
                           detail="RESULT: MERGED to main")

    base = dict(
        available_gb=lambda: 26.0,
        backend_alive=lambda: False,
        load_30b=lambda: True,
        wait_ready=lambda: True,
        run_task=lambda t: (calls.append(("task", t["task"], t["prompt"])), _merged(t))[1],
        cancel_requested=lambda: False,
        disarm_watchdog=lambda: None,
        stop_ovms=lambda: None,
        write_report=lambda rid, outs: None,
        restart_launcher=lambda: None,
        backend_ready=lambda: True,
        signal_failure=lambda msg: None,
        run_wave_gate=lambda repo: {"ok": True, "evidence": "verify=pass; tests=pass"},
        run_job_oracle=lambda repo, rel: {"status": "passed", "evidence": "exit 0"},
        write_scorecard=lambda sc: calls.append(("scorecard", sc)),
        write_job_summary=lambda text: None,
        log_pack=lambda tid, pack: None,
    )
    base.update(overrides)
    return sd.SwapOps(**base)


def _driver(tmp_path, ops, tasks, plan):
    store = pg.PlanStore(tmp_path / "plan.json", projects_dir=tmp_path)
    return sd.SwapDriver(
        run_id="R1", session_id="s1", tasks=tasks,
        swap_state_path=tmp_path / "swap.json", ops=ops,
        gate_gb=21.0, sleep=lambda _s: None,
        plan=store.write(plan), plan_store=store,
    )


def _fix_prompt(calls, marker: str) -> str:
    hits = [c[2] for c in calls
            if isinstance(c, tuple) and c[0] == "task" and marker in c[2]]
    assert hits, f"no {marker} fix cycle reached the coder seam"
    return hits[0]


# ---------------------------------------------------------------------------


@pytest.mark.parametrize("reintroduction", [
    "do NOT nest them inside an app/ or src/ package",
    "do not nest them inside an app/ or src/ package",          # lowercase — the F5 escape
    "Do Not Nest them inside an App/ or Src/ package",          # title case
    "don't nest it under a src/ or app/ package",
    "provide it at the top-level path the entrypoint imports",  # lowercase directive
    "A module you built under a package must be importable as a top-level module",
])
def test_the_prohibition_matcher_is_case_insensitive(reintroduction):
    """The lock, tested OFF. A case-SENSITIVE blocklist was the original form, and every
    lowercase row here would have sailed through it — which is the whole of F5. Each must be
    caught, or the checks above are decoration."""
    with pytest.raises(AssertionError, match="still forbids the package layout"):
        _assert_no_package_prohibition(f"LAYOUT FIX …\n{reintroduction}\n", "probe")


def test_the_matcher_does_not_fire_on_the_flat_case_description():
    """…and it must NOT fire on the prompt's legitimate description of the flat case. This is
    the collision that previously existed only by letter case: the package check banned
    "TOP-LEVEL module" while the flat non-regression check asserted "top-level module"."""
    _assert_no_package_prohibition(
        "An undotted path names a top-level module: `thing` must live at thing.py in the "
        "repo root.", "probe")


def test_the_contract_under_test_really_is_a_package_contract():
    """Guards the premise: if this contract stopped resolving to a package root, the two
    locks below would pass for the wrong reason."""
    assert canonical_package_from_contract(PACKAGE_CONTRACT) == "app"


def test_layout_fix_cycle_prompt_agrees_with_the_package_it_interpolates(tmp_path):
    repo = _mk_repo(tmp_path)
    tasks = _tasks(repo)
    calls: list = []
    ops = _ops(calls, job_oracle_contract=lambda: PACKAGE_CONTRACT,
               run_import_probe=lambda r, p: {"ok": False, "unresolved": PACKAGE_UNRESOLVED,
                                              "evidence": "unresolved"})
    _driver(tmp_path, ops, tasks, _plan(tmp_path, tasks)).run()
    prompt = _fix_prompt(calls, "LAYOUT FIX")

    # It still says what is broken, precisely.
    assert "from app.card_entry import add_card" in prompt
    # …and it no longer tells the coder to defeat the very package it just quoted.
    _assert_no_package_prohibition(prompt, "layout fix")
    # …and it states the package rule positively, so the coder knows where the file goes.
    assert "__init__.py" in prompt and "repo root" in prompt


def test_executability_fix_cycle_prompt_agrees_with_the_package_it_interpolates(tmp_path):
    """The boot-failure sibling carried the identical flat-module instruction, and the same
    guard fix exposes it on the same first repair."""
    repo = _mk_repo(tmp_path)
    tasks = _tasks(repo)
    calls: list = []
    ops = _ops(
        calls, job_oracle_contract=lambda: PACKAGE_CONTRACT,
        run_import_probe=lambda r, p: {"ok": True, "unresolved": [], "evidence": "resolved"},
        run_exec_smoke=lambda r, p: {
            "ok": False, "unresolved": PACKAGE_UNRESOLVED, "fingerprint": "f1",
            "evidence": "ModuleNotFoundError: No module named 'app.card_entry'"},
    )
    _driver(tmp_path, ops, tasks, _plan(tmp_path, tasks)).run()
    prompt = _fix_prompt(calls, "EXECUTABILITY FIX")

    assert "app.card_entry" in prompt
    _assert_no_package_prohibition(prompt, "executability fix")
    assert "__init__.py" in prompt and "repo root" in prompt


def test_a_flat_contract_still_gets_a_top_level_instruction(tmp_path):
    """NON-REGRESSION (passes before and after the rewrite, by design): the FLAT case the
    prompt was originally written for must keep working — an undotted contract is still
    told to place the module at the repo root as a top-level module."""
    flat_unresolved = [{"raw": "from cli_interface import run_cli", "module": "cli_interface",
                        "name": "run_cli", "reason": "does not resolve from the repo root"}]
    repo = _mk_repo(tmp_path)
    tasks = [
        {"repo": str(repo), "task": "core", "prompt": "build core", "depends_on": [],
         "contract": {"creates": ["core.py"], "exports": ["helper()"]}},
        {"repo": str(repo), "task": "cli", "prompt": "build cli", "depends_on": ["core"],
         "contract": {"creates": ["cli_interface.py"], "exports": ["run_cli()"]}},
    ]
    calls: list = []
    ops = _ops(calls, job_oracle_contract=lambda: ["from cli_interface import run_cli"],
               run_import_probe=lambda r, p: {"ok": False, "unresolved": flat_unresolved,
                                              "evidence": "unresolved"})
    _driver(tmp_path, ops, tasks, _plan(tmp_path, tasks)).run()
    prompt = _fix_prompt(calls, "LAYOUT FIX")
    assert "from cli_interface import run_cli" in prompt
    low = prompt.lower()
    assert "top-level module" in low and "repo root" in low
