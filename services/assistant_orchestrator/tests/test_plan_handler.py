"""Tests — AO PLAN handler + the deterministic single-shot generate_fn (#670).

``_handle_plan_request`` turns a ``/dispatch`` goal into tasks + a validated
AcceptanceSpec via the 14B's criteria generation + the deterministic ruler. These tests
bind the unbound methods to a minimal stand-in (no GPU, no listener, no started AO): a
FAKE generator stands in for the resident 14B (via an overridden ``_plan_generate_fn``)
— exactly the testability seam ``decompose`` already uses. The LIVE generate wrapper
(``_plan_generate_fn``: greedy GenerationConfig + think-strip) is tested separately with a
fake inference; the only thing left for hardware is the real 14B's output quality.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from services.assistant_orchestrator.src.entrypoint import (
    AssistantOrchestratorService,
)
from shared.ipc.protocol import MessageFramer


class _FakeTransport:
    def __init__(self) -> None:
        self.sent: list[bytes] = []

    def send(self, frame: bytes) -> bool:
        self.sent.append(frame)
        return True


def _git_repo(projects_dir, name="myapp"):
    (projects_dir / name / ".git").mkdir(parents=True)
    return name


def _good_gen(prompt: str) -> str:
    """A well-behaved 14B stand-in: tasks JSON for decompose, criteria JSON for criteria."""
    if "ACCEPTANCE CRITERIA" in prompt:
        return json.dumps([
            {"text": "the project builds", "tier": "build", "check": ""},
            {"text": "2 + 3 shows 5", "tier": "behavior", "check": "assert add(2,3)==5"},
        ])
    return json.dumps([{"task": "add-calc", "prompt": "build a calc"}])


class _PlanHarness:
    """Minimal stand-in carrying just what _handle_plan_request reads — no GPU.

    ``_plan_generate_fn`` is OVERRIDDEN to return the injected fake generator (the real
    one builds a GenerationConfig + calls the resident 14B); the fleet-root properties read
    a stub resolved-config.
    """

    def __init__(self, fake_gen, projects_root, *, enabled=True, clarify=True, revise=True) -> None:
        self._framer = MessageFramer()
        self._fake_gen = fake_gen
        self._resolved_config = SimpleNamespace(
            fleet_dispatch_enabled=enabled,
            fleet_dispatch_clarify_enabled=clarify,
            fleet_dispatch_revise_enabled=revise,
            fleet_dispatch_agentic_setup_dir="",
            fleet_dispatch_projects_dir=str(projects_root),
        )

    def _plan_generate_fn(self):
        return self._fake_gen

    _handle_plan_request = AssistantOrchestratorService._handle_plan_request
    _fleet_projects_dir = AssistantOrchestratorService._fleet_projects_dir
    fleet_dispatch_enabled = AssistantOrchestratorService.fleet_dispatch_enabled
    fleet_dispatch_clarify_enabled = (
        AssistantOrchestratorService.fleet_dispatch_clarify_enabled
    )
    fleet_dispatch_revise_enabled = (
        AssistantOrchestratorService.fleet_dispatch_revise_enabled
    )
    fleet_dispatch_agentic_setup_dir = (
        AssistantOrchestratorService.fleet_dispatch_agentic_setup_dir
    )
    fleet_dispatch_projects_dir = (
        AssistantOrchestratorService.fleet_dispatch_projects_dir
    )


def test_plan_handler_returns_tasks_and_criteria(tmp_path):
    projects = tmp_path / "projects"
    repo = _git_repo(projects)
    h = _PlanHarness(_good_gen, projects)
    t = _FakeTransport()
    assert h._handle_plan_request(t, "rid1", {"repo": repo, "goal": "a calculator"})
    payload = h._framer.decode_plan_result(t.sent[0])
    assert payload["ok"] is True
    # BEHAVIOR CHANGE (#670 Problem 3): the goal right-sizes to ONE feature task, so the
    # behavior criterion FOLDS into that task's prompt — no separate acceptance-tests task.
    assert len(payload["tasks"]) == 1
    assert not any(task["task"] == "acceptance-tests" for task in payload["tasks"])
    assert "2 + 3 shows 5" in payload["tasks"][0]["prompt"]
    assert payload["criteria"]["goal"] == "a calculator"
    tiers = {c["tier"] for c in payload["criteria"]["criteria"]}
    assert "behavior" in tiers and "build" in tiers


def test_plan_handler_garbage_generator_degrades_with_build_floor(tmp_path):
    # Invariant 3: a garbage/empty 14B response degrades gracefully — the ruler drops the
    # bad criteria + injects the BUILD floor; decompose falls back to one task. ok=True,
    # never a crash, never a false-pass.
    projects = tmp_path / "projects"
    repo = _git_repo(projects)
    h = _PlanHarness(lambda _prompt: "total garbage, not JSON at all", projects)
    t = _FakeTransport()
    assert h._handle_plan_request(t, "rid1", {"repo": repo, "goal": "make it fast"})
    payload = h._framer.decode_plan_result(t.sent[0])
    assert payload["ok"] is True and payload["fell_back"] is True
    crit = payload["criteria"]["criteria"]
    assert len(crit) == 1 and crit[0]["tier"] == "build"  # injected build floor


def test_plan_handler_bad_repo_returns_not_ok(tmp_path):
    projects = tmp_path / "projects"
    projects.mkdir()
    h = _PlanHarness(_good_gen, projects)
    t = _FakeTransport()
    assert h._handle_plan_request(t, "rid1", {"repo": "does-not-exist", "goal": "x"})
    payload = h._framer.decode_plan_result(t.sent[0])
    assert payload["ok"] is False  # generate_plan rejects the repo, never crashes


def test_plan_handler_raising_generator_never_crashes(tmp_path):
    # A raising generator must still produce a clean PLAN_RESULT (never crash the AO loop):
    # generate_plan swallows the generator exception -> fallback task + build floor.
    projects = tmp_path / "projects"
    repo = _git_repo(projects)

    def _raises(_prompt):
        raise RuntimeError("model exploded")

    h = _PlanHarness(_raises, projects)
    t = _FakeTransport()
    assert h._handle_plan_request(t, "rid1", {"repo": repo, "goal": "an idea here"})
    payload = h._framer.decode_plan_result(t.sent[0])
    assert payload["ok"] is True  # graceful, not a crash


def _clarify_gen(prompt: str) -> str:
    """A 14B stand-in that ASKS requirements questions for the clarify prompt (#819), else
    behaves like _good_gen (tasks/criteria)."""
    if "ask ONLY the few questions" in prompt:  # the #819 clarify prompt marker
        return json.dumps([
            {"axis": "surface", "question": "Where will you use this — computer or browser?"},
            {"axis": "persistence", "question": "Should your data be saved between uses?"},
        ])
    return _good_gen(prompt)


def test_plan_handler_clarify_returns_questions(tmp_path):
    # #819: an underspecified goal with the stage ON returns CLARIFY questions (no tasks yet).
    projects = tmp_path / "projects"
    repo = _git_repo(projects)
    h = _PlanHarness(_clarify_gen, projects, clarify=True)
    t = _FakeTransport()
    assert h._handle_plan_request(t, "rid1", {"repo": repo, "goal": "a todo app"})
    payload = h._framer.decode_plan_result(t.sent[0])
    assert payload["ok"] is True
    assert [q["axis"] for q in payload["questions"]] == ["surface", "persistence"]
    assert payload["tasks"] == []  # early-return: no decompose ran


def test_plan_handler_clarify_disabled_no_questions(tmp_path):
    # With the knob OFF, an underspecified goal goes straight to decompose (pre-#819).
    projects = tmp_path / "projects"
    repo = _git_repo(projects)
    h = _PlanHarness(_clarify_gen, projects, clarify=False)
    t = _FakeTransport()
    assert h._handle_plan_request(t, "rid1", {"repo": repo, "goal": "a todo app"})
    payload = h._framer.decode_plan_result(t.sent[0])
    assert payload["questions"] == [] and len(payload["tasks"]) >= 1


def test_plan_handler_requirements_thread_and_goal_stays_clean(tmp_path):
    # The re-plan: an enriched goal (goal + the requirements sentinel) suppresses clarify and
    # threads the requirements into the task context, while spec.goal stays the clean goal.
    from shared.fleet import clarify as _clarify

    projects = tmp_path / "projects"
    repo = _git_repo(projects)
    enriched = _clarify.compose_planning_goal(
        "a todo app",
        _clarify.compose_requirements_block(
            [{"question": "q", "answer": "on my computer", "assumed": False}]
        ),
    )
    h = _PlanHarness(_clarify_gen, projects, clarify=True)
    t = _FakeTransport()
    assert h._handle_plan_request(t, "rid1", {"repo": repo, "goal": enriched})
    payload = h._framer.decode_plan_result(t.sent[0])
    assert payload["questions"] == []                       # clarify suppressed on the re-plan
    assert payload["criteria"]["goal"] == "a todo app"      # spec.goal is the CLEAN goal
    assert any("on my computer" in tk["prompt"] for tk in payload["tasks"])


def test_plan_handler_disabled_fails_closed(tmp_path):
    # Uniform dormancy lock: a disabled AO refuses PLAN too (the gateway also gates it; this
    # keeps "the AO honors its own enabled flag" true for both verbs).
    projects = tmp_path / "projects"
    repo = _git_repo(projects)
    called = {"gen": False}

    def _gen_marker(prompt):
        called["gen"] = True
        return _good_gen(prompt)

    h = _PlanHarness(_gen_marker, projects, enabled=False)
    t = _FakeTransport()
    assert h._handle_plan_request(t, "rid1", {"repo": repo, "goal": "a calculator"})
    payload = h._framer.decode_plan_result(t.sent[0])
    assert payload["ok"] is False and "disabled" in payload["message"].lower()
    assert called["gen"] is False  # the 14B is never invoked while disabled


# ---- the LIVE generate_fn wrapper (greedy + think-strip; fake inference) ----


def test_plan_generate_fn_is_greedy_and_strips_hidden_blocks():
    captured = {}

    class _FakeInference:
        def generate_text(self, prompt, max_new_tokens=None, config=None, **_kw):
            captured["config"] = config
            captured["max_new_tokens"] = max_new_tokens
            captured["prompt"] = prompt
            return SimpleNamespace(text='<think>scheming</think>[{"task": "t"}]')

    stub = SimpleNamespace(_inference=_FakeInference())
    gen = AssistantOrchestratorService._plan_generate_fn(stub)
    out = gen("decompose this idea")
    assert out == '[{"task": "t"}]'                    # <think> block stripped
    assert captured["config"].do_sample is False       # greedy / temp-0 equivalent
    assert captured["max_new_tokens"] > 0


def test_plan_generate_fn_uses_minimal_plan_system_prompt():
    """#748 tool-bait lock: the PLAN call must ride the minimal no-tools planning
    system prompt, never the conversational persona — whose tool directive baited
    the live 14B into answering the decompose request with a <tool_call> (greedy,
    deterministic) that the strip reduced to '' → minimal single-task fallback."""
    from services.assistant_orchestrator.src.entrypoint import _PLAN_SYSTEM_PROMPT

    captured = {}

    class _FakeInference:
        def generate_text(self, prompt, max_new_tokens=None, config=None, **kw):
            captured.update(kw)
            return SimpleNamespace(text="[]")

    stub = SimpleNamespace(_inference=_FakeInference())
    AssistantOrchestratorService._plan_generate_fn(stub)("decompose this idea")
    assert captured.get("system_prompt") == _PLAN_SYSTEM_PROMPT
    assert "no tool calls" in _PLAN_SYSTEM_PROMPT
    assert "/no_think" in _PLAN_SYSTEM_PROMPT


def test_plan_generate_fn_raises_on_hidden_blocks_only_response():
    """#748: a response that is ENTIRELY hidden blocks (tool-call-only or
    all-<think>) must RAISE with the evidence, never silently return '' —
    the live failure shape was <tool_call>search_knowledge...</tool_call>
    as the model's whole answer to the decompose prompt."""
    import pytest

    class _FakeInference:
        def generate_text(self, prompt, max_new_tokens=None, config=None, **_kw):
            return SimpleNamespace(
                text='<tool_call>{"name": "search_knowledge", "arguments": {}}</tool_call>'
            )

    stub = SimpleNamespace(_inference=_FakeInference())
    gen = AssistantOrchestratorService._plan_generate_fn(stub)
    with pytest.raises(RuntimeError, match="no answer text"):
        gen("decompose this idea")


def test_plan_generate_fn_never_arms_tool_call_grammar():
    """#748 root-cause lock: the PLAN call's GenerationConfig must carry
    tool_call_grammar=False EXPLICITLY. The dataclass-default arming crashed the
    live plan generation on #725's xgrammar stop-token bug (grammar_matcher.cc:627)
    on every dispatch — the whole M2 plan-graph silently fell back to one task."""
    captured = {}

    class _FakeInference:
        def generate_text(self, prompt, max_new_tokens=None, config=None, **_kw):
            captured["config"] = config
            return SimpleNamespace(text="[]")

    stub = SimpleNamespace(_inference=_FakeInference())
    AssistantOrchestratorService._plan_generate_fn(stub)("decompose this idea")
    assert captured["config"].tool_call_grammar is False


def test_plan_generate_fn_raises_on_fail_closed_error():
    """#748 fail-loud lock: a generation-layer failure (fail-closed result with
    text='' and the cause only in .error) must RAISE, never return '' — the
    silent empty was indistinguishable from an empty model answer and collapsed
    every plan to the minimal single-task fallback with err='' in the logs.
    The raise routes into the consumers' designed degradation, e2e-proven by
    ``test_plan_handler_raising_generator_never_crashes`` above."""
    import pytest

    class _FakeInference:
        def generate_text(self, prompt, max_new_tokens=None, config=None, **_kw):
            return SimpleNamespace(
                text="", error="Generation error — Fail-Closed: xgrammar boom"
            )

    stub = SimpleNamespace(_inference=_FakeInference())
    gen = AssistantOrchestratorService._plan_generate_fn(stub)
    with pytest.raises(RuntimeError, match="PLAN generation failed"):
        gen("decompose this idea")


# ── #820 plan-revision branch ────────────────────────────────────────────


def _revise_gen(prompt: str) -> str:
    """A 14B stand-in that emits REVISE edit ops (the revise prompt asks for a JSON array of
    {op,ref,task,prompt}). Any non-revise prompt falls through to the good generator."""
    if "REVISE the plan" in prompt:
        return json.dumps([
            {"op": "keep", "ref": 1},
            {"op": "add", "task": "csv-export", "prompt": "add a CSV export button"},
        ])
    return _good_gen(prompt)


def test_plan_handler_revise_branch_returns_ops(tmp_path):
    from shared.fleet import revise as _revise
    projects = tmp_path / "projects"
    repo = _git_repo(projects)
    h = _PlanHarness(_revise_gen, projects)
    t = _FakeTransport()
    goal = _revise.compose_revision_goal("a todo app", "add a csv export", ["Build tracker"])
    assert h._handle_plan_request(t, "rid1", {"repo": repo, "goal": goal})
    payload = h._framer.decode_plan_result(t.sent[0])
    assert payload["ok"] is True
    # The revise early-return carries edit OPS, not tasks/criteria.
    assert payload["revision"] and payload["tasks"] == []
    ops = payload["revision"]
    assert ops[0]["op"] == "keep" and ops[1]["op"] == "add" and ops[1]["task"] == "csv-export"


def test_plan_handler_revise_disabled_fails_closed(tmp_path):
    from shared.fleet import revise as _revise
    projects = tmp_path / "projects"
    repo = _git_repo(projects)
    h = _PlanHarness(_revise_gen, projects, revise=False)
    t = _FakeTransport()
    goal = _revise.compose_revision_goal("a todo app", "add export", ["Build tracker"])
    assert h._handle_plan_request(t, "rid1", {"repo": repo, "goal": goal})
    payload = h._framer.decode_plan_result(t.sent[0])
    assert payload["ok"] is False and "turned off" in payload["message"]
    assert payload["revision"] == [] and payload["tasks"] == []


def test_plan_handler_normal_goal_has_no_revision(tmp_path):
    # A plain (non-revise) goal never populates the revision payload — byte-identical to today.
    projects = tmp_path / "projects"
    repo = _git_repo(projects)
    h = _PlanHarness(_good_gen, projects)
    t = _FakeTransport()
    assert h._handle_plan_request(t, "rid1", {"repo": repo, "goal": "a calculator"})
    payload = h._framer.decode_plan_result(t.sent[0])
    assert payload["ok"] is True and payload["revision"] == [] and payload["tasks"]
