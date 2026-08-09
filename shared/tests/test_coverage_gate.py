"""Tests for #1069 (S3 slice F) — coverage by construction + the blocking pre-render gate.

The capability under test is the one the operator ratified in his own words (#1069 c.2512):
"the system won't let you sign something it couldn't check." A multi-task plan whose job exam
does not cover the plan — a task owning no module the exam imports, or an exam import no task
owns — reports GREEN when it runs, and that GREEN enters the capability record meaning
nothing (the measured #989/#1008 class). Warn-loud is what the system did before this slice,
and the class happened anyway.

Three behaviours, three kinds of test:

* **coverage BY CONSTRUCTION** — in intake mode the exam author's prompt carries a
  deterministic 1:1 import pin derived from the task contracts. Tested by capturing the
  prompts the model actually received.
* **ONE bounded re-authoring** — a residual gap re-authors the exam once with the gap named;
  a repair is adopted ONLY when it measures clean, and an EMPTY repair is discarded (a gappy
  exam must never degrade into no exam, because an absent exam is approvable). Tested by
  counting authoring calls and by asserting which exam bytes survive.
* **the BLOCKING marker** — a surviving gap sets ``PlanResult.coverage_blocked``; the card
  renders blocked and never offers approve. Per security_by_design principle 12 the toggle-off
  is proven too: flag off ⇒ byte-identical plan, never a marker — otherwise "the gate blocks"
  cannot be told apart from "the test cannot reach the gate".

Both flags are required (``coverage_gate`` AND ``advanced_intake``) and a card-driven
dispatch self-suppresses, exactly like slices D and E. Model calls are faked throughout
(offline, GPU-free).
"""

from __future__ import annotations

import json

from shared.fleet.acceptance import (
    JOB_ORACLE_CODE_KEY,
    PlanResult,
    _coverage_blocked_message,
    _coverage_contract_block,
    generate_plan,
    render_criteria_preview,
)
from shared.ipc.protocol import MessageFramer, MessageType

# ---------------------------------------------------------------------------
# Fakes — the test_bad_input_floor harness idiom: a two-task decomposition with
# 1:1-able contracts, and a job exam whose import surface the test controls.
# ---------------------------------------------------------------------------

#: Imports ONLY app.quiz_engine — task "cli" owns no imported module ⇒ a coverage gap.
_GAPPED_ORACLE = (
    "```python\n"
    "from app.quiz_engine import run_quiz\n"
    "\n"
    "def test_scores_a_correct_answer():\n"
    "    cards = [{'question': 'q', 'answer': 'a'}]\n"
    "    assert run_quiz(cards, lambda q: 'a') == {'asked': 1, 'correct': 1}\n"
    "```\n"
)

#: Imports both contracted modules — clean 1:1 coverage.
_CLEAN_ORACLE = (
    "```python\n"
    "from app.quiz_engine import run_quiz\n"
    "from app.cli import main\n"
    "\n"
    "def test_scores_a_correct_answer():\n"
    "    cards = [{'question': 'q', 'answer': 'a'}]\n"
    "    assert run_quiz(cards, lambda q: 'a') == {'asked': 1, 'correct': 1}\n"
    "\n"
    "def test_cli_entrypoint_exists():\n"
    "    assert callable(main)\n"
    "```\n"
)

#: The repair-round marker generate_plan embeds in the re-authoring prompt.
_REPAIR_MARKER = "A previous attempt FAILED the mechanical coverage check"
#: The by-construction pin header _coverage_contract_block emits.
_PIN_MARKER = "IMPORT COVERAGE IS A HARD REQUIREMENT"


def _repo(tmp_path, name="flashcards"):
    proj = tmp_path / "projects"
    (proj / name / ".git").mkdir(parents=True, exist_ok=True)
    return proj, name


class _Gen:
    """A scripted generate_fn that records every prompt and answers by marker.

    ``oracle_first`` answers the first job-exam authoring; ``oracle_repair`` answers any
    authoring whose prompt carries the repair marker (the bounded re-authoring round).
    """

    def __init__(self, oracle_first: str, oracle_repair: str | None = None):
        self.oracle_first = oracle_first
        self.oracle_repair = oracle_repair if oracle_repair is not None else oracle_first
        self.prompts: list[str] = []

    def oracle_prompts(self) -> list[str]:
        return [p for p in self.prompts if "JOB-LEVEL ACCEPTANCE" in p]

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if "decomposing a software change request" in prompt:
            return json.dumps([
                {"task": "engine", "prompt": "build the quiz engine", "depends_on": [],
                 "contract": {"creates": ["app/quiz_engine.py"],
                              "exports": ["run_quiz(cards, answer_fn)"], "notes": ""}},
                {"task": "cli", "prompt": "build the cli", "depends_on": ["engine"],
                 "contract": {"creates": ["app/cli.py"], "exports": ["main()"],
                              "notes": ""}},
            ])
        if "ACCEPTANCE CRITERIA" in prompt:
            return json.dumps([{"text": "It scores a correct answer", "tier": "behavior",
                                "check": "run the quiz and check the tally"}])
        if "Classify what KIND of software" in prompt:
            return json.dumps({"surface": "command-line", "candidates": [],
                               "language_hint": "python", "complexity": "simple",
                               "components": []})
        if "JOB-LEVEL ACCEPTANCE" in prompt:
            if _REPAIR_MARKER in prompt:
                return self.oracle_repair
            return self.oracle_first
        return "[]"


def _job_exam(plan) -> str:
    return str(plan.tasks[-1].get(JOB_ORACLE_CODE_KEY, ""))


# ---------------------------------------------------------------------------
# The blocking marker — set, named, and honest about what stays open
# ---------------------------------------------------------------------------


def test_gate_on_a_surviving_gap_blocks_and_names_it(tmp_path):
    """THE defect lock: a stubborn model (gapped exam on both rounds) yields a REAL plan
    (ok, tasks, spec) that carries a non-empty blocking marker naming the gap."""
    proj, repo = _repo(tmp_path)
    gen = _Gen(_GAPPED_ORACLE)
    plan = generate_plan("a flashcards quiz", repo, generate_fn=gen, projects_dir=proj,
                         advanced_intake=True, coverage_gate=True)
    assert plan.ok and plan.tasks, "the blocked plan must still render — blocked, not refused"
    assert plan.coverage_blocked, "a surviving coverage gap must set the blocking marker"
    assert "cli" in plan.coverage_blocked, "the marker must NAME the uncovered task"
    # The operator is told what stays open — never a dead end.
    assert "revise" in plan.coverage_blocked
    assert "reject" in plan.coverage_blocked


def test_one_bounded_reauthoring_never_a_loop(tmp_path):
    """The gap triggers exactly ONE repair round: two authoring calls total, however
    stubborn the model."""
    proj, repo = _repo(tmp_path)
    gen = _Gen(_GAPPED_ORACLE)
    generate_plan("a flashcards quiz", repo, generate_fn=gen, projects_dir=proj,
                  advanced_intake=True, coverage_gate=True)
    assert len(gen.oracle_prompts()) == 2, "expected original + exactly one repair"
    assert _REPAIR_MARKER in gen.oracle_prompts()[1]
    assert _REPAIR_MARKER not in gen.oracle_prompts()[0]


def test_a_clean_repair_is_adopted_and_unblocks(tmp_path):
    proj, repo = _repo(tmp_path)
    gen = _Gen(_GAPPED_ORACLE, oracle_repair=_CLEAN_ORACLE)
    plan = generate_plan("a flashcards quiz", repo, generate_fn=gen, projects_dir=proj,
                         advanced_intake=True, coverage_gate=True)
    assert plan.coverage_blocked == ""
    assert "from app.cli import main" in _job_exam(plan), "the clean repair must be adopted"
    assert "CONTRACT-COVERAGE WARNING" not in plan.message


def test_an_empty_repair_is_discarded_and_the_original_exam_kept(tmp_path):
    """The escape hatch that must not exist: if the repair round fails to author, the plan
    must keep the ORIGINAL gapped exam AND stay blocked — trading a gappy exam for no exam
    would make the plan approvable through the exact hole the gate closes."""
    proj, repo = _repo(tmp_path)
    gen = _Gen(_GAPPED_ORACLE, oracle_repair="not code at all")
    plan = generate_plan("a flashcards quiz", repo, generate_fn=gen, projects_dir=proj,
                         advanced_intake=True, coverage_gate=True)
    assert plan.coverage_blocked, "an unrepaired gap must stay blocked"
    exam = _job_exam(plan)
    assert "from app.quiz_engine import run_quiz" in exam, \
        "the original exam must survive a failed repair — never dropped to ''"


def test_a_still_gapped_repair_keeps_the_original_exam(tmp_path):
    """A repair that authors fine but measures gapped is NOT adopted — the original exam
    (whose QA evidence chain is the one on record) rides, and the block stands."""
    proj, repo = _repo(tmp_path)
    still_gapped = _GAPPED_ORACLE.replace("test_scores_a_correct_answer",
                                          "test_scores_a_correct_answer_repaired")
    gen = _Gen(_GAPPED_ORACLE, oracle_repair=still_gapped)
    plan = generate_plan("a flashcards quiz", repo, generate_fn=gen, projects_dir=proj,
                         advanced_intake=True, coverage_gate=True)
    assert plan.coverage_blocked
    assert "test_scores_a_correct_answer_repaired" not in _job_exam(plan), \
        "a still-gapped repair must not replace the original exam"


def test_clean_first_authoring_never_reauthors(tmp_path):
    proj, repo = _repo(tmp_path)
    gen = _Gen(_CLEAN_ORACLE)
    plan = generate_plan("a flashcards quiz", repo, generate_fn=gen, projects_dir=proj,
                         advanced_intake=True, coverage_gate=True)
    assert plan.coverage_blocked == ""
    assert len(gen.oracle_prompts()) == 1, "a clean exam must not trigger a repair round"


# ---------------------------------------------------------------------------
# Coverage BY CONSTRUCTION — the pin in the authoring prompt
# ---------------------------------------------------------------------------


def test_pin_rides_the_authoring_prompt_in_intake_mode(tmp_path):
    proj, repo = _repo(tmp_path)
    gen = _Gen(_CLEAN_ORACLE)
    generate_plan("a flashcards quiz", repo, generate_fn=gen, projects_dir=proj,
                  advanced_intake=True, coverage_gate=True)
    first = gen.oracle_prompts()[0]
    assert _PIN_MARKER in first
    assert "app/quiz_engine.py" in first and "app/cli.py" in first, \
        "the pin must name every contracted module"


def test_pin_absent_when_the_gate_is_off(tmp_path):
    """Byte-identical prompt with the gate off — the pin is intake-mode behaviour, not a
    quick-path drive-by."""
    proj, repo = _repo(tmp_path)
    gen = _Gen(_GAPPED_ORACLE)
    generate_plan("a flashcards quiz", repo, generate_fn=gen, projects_dir=proj,
                  advanced_intake=True)
    assert all(_PIN_MARKER not in p for p in gen.oracle_prompts())


def test_coverage_contract_block_empty_without_any_contracts():
    assert _coverage_contract_block([{"task": "a"}, {"task": "b"}]) == ""


# ---------------------------------------------------------------------------
# The two-knob gate and the self-suppressions — who is NEVER gated
# ---------------------------------------------------------------------------


def test_coverage_gate_ALONE_does_not_engage(tmp_path):
    """``advanced_intake`` is already live in production, so if the gate rode the sub-flag
    alone it would go live at merge — a capability change with no ceremony (#1069 c.2512
    build constraint). BOTH knobs are required."""
    proj, repo = _repo(tmp_path)
    gen = _Gen(_GAPPED_ORACLE)
    plan = generate_plan("a flashcards quiz", repo, generate_fn=gen, projects_dir=proj,
                         coverage_gate=True)
    assert plan.coverage_blocked == ""
    assert all(_PIN_MARKER not in p for p in gen.oracle_prompts())


def test_battery_card_is_never_gated(tmp_path):
    """A ``battery-*`` sandbox dispatch self-suppresses even with both knobs on: the card IS
    the measuring instrument, and blocking a nightly campaign is not a plan an operator can
    revise. Same suppression shape as the S1 floors and slice E, same reason but sharper."""
    proj, repo = _repo(tmp_path, name="battery-b4-flashcards-cli")
    gen = _Gen(_GAPPED_ORACLE)
    plan = generate_plan("a flashcards quiz", repo, generate_fn=gen, projects_dir=proj,
                         advanced_intake=True, coverage_gate=True)
    assert plan.coverage_blocked == ""
    assert all(_PIN_MARKER not in p for p in gen.oracle_prompts())


def test_no_exam_shape_is_never_gated(tmp_path):
    """A plan that honestly authors NO exam (build-only ecosystem ⇒ no python/node target)
    is a DISCLOSED absence, not a coverage gap — blocking it would be a new refusal outside
    the ratified one, and would break .NET dispatches wholesale in intake mode."""
    proj, repo = _repo(tmp_path)
    gen = _Gen(_GAPPED_ORACLE)

    def dotnet_gen(prompt: str) -> str:
        if "Classify what KIND of software" in prompt:
            return json.dumps({"surface": "desktop", "candidates": [],
                               "language_hint": "dotnet", "complexity": "simple",
                               "components": []})
        return gen(prompt)

    plan = generate_plan("a flashcards quiz", repo, generate_fn=dotnet_gen,
                         projects_dir=proj, advanced_intake=True, coverage_gate=True)
    assert _job_exam(plan) == "", "harness self-check: this shape must author no exam"
    assert plan.coverage_blocked == ""


# ---------------------------------------------------------------------------
# Toggle-off — the standing byte-identical bar (principle 12's second half)
# ---------------------------------------------------------------------------


def test_gate_off_is_BYTE_IDENTICAL_through_generate_plan(tmp_path):
    """With the sub-flag off, the whole compiled plan — tasks, exam bytes, criteria,
    message, marker — is unchanged from today, even on a gapped exam. And the ON run
    differs, so the equality is measuring the flag rather than a harness that cannot
    reach the behaviour."""
    proj, repo = _repo(tmp_path)
    default = generate_plan("a flashcards quiz", repo, generate_fn=_Gen(_GAPPED_ORACLE),
                            projects_dir=proj, advanced_intake=True)
    explicit_off = generate_plan("a flashcards quiz", repo, generate_fn=_Gen(_GAPPED_ORACLE),
                                 projects_dir=proj, advanced_intake=True,
                                 coverage_gate=False)
    on = generate_plan("a flashcards quiz", repo, generate_fn=_Gen(_GAPPED_ORACLE),
                       projects_dir=proj, advanced_intake=True, coverage_gate=True)

    assert explicit_off.tasks == default.tasks
    assert explicit_off.message == default.message
    assert explicit_off.coverage_blocked == "" and default.coverage_blocked == ""
    assert [c.to_dict() for c in explicit_off.spec.criteria] == \
           [c.to_dict() for c in default.spec.criteria]
    # The quick path keeps its warn-loud disclosure — the warning text is UNCHANGED...
    assert "CONTRACT-COVERAGE WARNING" in default.message
    # ...and the ON run really blocks, so the off-equality is a reachable-gate proof.
    assert on.coverage_blocked != ""


def test_plan_result_default_is_unblocked():
    assert PlanResult(ok=True).coverage_blocked == ""


# ---------------------------------------------------------------------------
# The card — a blocked plan never offers approve
# ---------------------------------------------------------------------------


def test_render_preview_blocked_leads_with_it_and_never_offers_approve():
    plan_gen = _Gen(_GAPPED_ORACLE)  # only for the marker text builder below
    del plan_gen
    marker = _coverage_blocked_message("CONTRACT-COVERAGE WARNING: build task(s) cli ...")
    from shared.fleet.acceptance import AcceptanceCriterion, AcceptanceSpec
    spec = AcceptanceSpec(
        goal="a flashcards quiz",
        criteria=(AcceptanceCriterion(id="c1", text="scores", tier="behavior",
                                      check="run it"),),
    )
    blocked = render_criteria_preview(spec, ecosystem="python",
                                      revise_hint="`/dispatch revise ...` to change it.",
                                      coverage_blocked=marker)
    assert "APPROVAL IS BLOCKED FOR NOW" in blocked
    assert "Reply `/dispatch approve`" not in blocked, \
        "a blocked card must not offer a verb the coordinator will refuse"
    assert marker in blocked

    unblocked = render_criteria_preview(spec, ecosystem="python",
                                        revise_hint="`/dispatch revise ...` to change it.")
    assert "Reply `/dispatch approve`" in unblocked
    assert "APPROVAL IS BLOCKED" not in unblocked


# ---------------------------------------------------------------------------
# The IPC crossing — the marker survives the frame both ways (#1152's seam)
# ---------------------------------------------------------------------------


def test_marker_survives_the_plan_result_frame_roundtrip():
    framer = MessageFramer()
    frame = framer.encode_plan_result(
        ok=True, message="m", tasks=[{"repo": "r", "task": "t", "prompt": "p"}],
        criteria={"goal": "g", "criteria": []},
        coverage_blocked="I can't let this plan be approved yet: ...",
    )
    decoded = framer.decode_plan_result(frame)
    assert decoded["coverage_blocked"] == "I can't let this plan be approved yet: ..."


def test_F1_an_importless_repair_is_never_adopted(tmp_path):
    """Review F1: a repair that strips every first-party import measures NOT-COMPUTABLE
    (contract_coverage → None), not clean — adopting it would unblock a plan whose exam
    verifies nothing by import, through the gate's own repair door. Unmeasurable keeps
    the block and the ORIGINAL exam."""
    importless = "```python\ndef test_something():\n    assert True\n```\n"
    proj, repo = _repo(tmp_path)
    gen = _Gen(_GAPPED_ORACLE, oracle_repair=importless)
    plan = generate_plan("a flashcards quiz", repo, generate_fn=gen, projects_dir=proj,
                         advanced_intake=True, coverage_gate=True)
    assert plan.coverage_blocked, "an unmeasurable repair must keep the block"
    assert "from app.quiz_engine import run_quiz" in _job_exam(plan), \
        "the ORIGINAL exam must ride, never the unmeasurable repair"


def test_measured_clean_helper_refuses_none_and_crash(monkeypatch):
    """The release rule itself: True only on a MEASURED clean dict; None and a
    derivation crash are both NOT clean (deny-by-default inside the engaged gate)."""
    from shared.fleet import acceptance as acc

    tasks = [{"task": "engine",
              "contract": {"creates": ["app/quiz_engine.py"], "exports": []}}]
    clean = ("from app.quiz_engine import run_quiz\n\n"
             "def test_x():\n    assert run_quiz\n")
    assert acc._coverage_measured_clean(tasks, "tests/test_job_acceptance.py", clean)
    assert not acc._coverage_measured_clean(
        tasks, "tests/test_job_acceptance.py", "def test_x():\n    assert True\n"
    ), "None (no usable import target) must read NOT clean"

    def boom(*a, **k):
        raise RuntimeError("measurement down")

    monkeypatch.setattr(acc, "contract_coverage", boom)
    assert not acc._coverage_measured_clean(
        tasks, "tests/test_job_acceptance.py", clean
    ), "a derivation crash must read NOT clean, never fail-open"


def test_F4_orphan_only_gap_routes_to_reject_not_revise(tmp_path):
    """Review F4: every task covered, the gap is orphan imports only — no plan revision
    can clear it (revise mints contract-less tasks and never touches the exam), so the
    blocked message routes to reject instead of inviting a futile revise."""
    orphan_oracle = _CLEAN_ORACLE.replace(
        "from app.cli import main",
        "from app.cli import main\nfrom app.phantom import ghost",
    )
    proj, repo = _repo(tmp_path)
    gen = _Gen(orphan_oracle)
    plan = generate_plan("a flashcards quiz", repo, generate_fn=gen, projects_dir=proj,
                         advanced_intake=True, coverage_gate=True)
    assert plan.coverage_blocked
    assert "re-described" in plan.coverage_blocked
    assert "revise <what to change>" not in plan.coverage_blocked


def test_F3_blocked_card_without_a_revise_hint_supersedes_the_baked_offer():
    """Review F3: at the revision cap (the empty-hint render), the marker's baked revise
    offer is stale — the card must supersede it explicitly. With a live hint, no
    corrective line renders."""
    from shared.fleet.acceptance import AcceptanceCriterion, AcceptanceSpec

    spec = AcceptanceSpec(
        goal="q", criteria=(AcceptanceCriterion("c1", "x", "behavior", "y"),))
    marker = _coverage_blocked_message("CONTRACT-COVERAGE WARNING: build task(s) cli ...")
    capped = render_criteria_preview(spec, coverage_blocked=marker)
    assert "Refinements are used up" in capped
    live = render_criteria_preview(
        spec, coverage_blocked=marker,
        revise_hint="`/dispatch revise ...` to change it.")
    assert "Refinements are used up" not in live


def test_marker_absent_from_an_older_frame_decodes_to_empty():
    """A pre-S3F sender omits the key entirely — the decode must yield '' (approvable),
    never raise. The typed-guard still rejects a present non-str."""
    framer = MessageFramer()
    frame = framer.encode(  # hand-built payload WITHOUT the key, as an old peer would send
        MessageType.PLAN_RESULT,
        {"ok": True, "message": "m", "fell_back": False, "tasks": [], "criteria": {},
         "questions": [], "revision": []},
        "rid",
    )
    decoded = framer.decode_plan_result(frame)
    assert decoded["coverage_blocked"] == ""
