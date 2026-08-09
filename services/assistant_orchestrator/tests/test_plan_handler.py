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

import pytest

from services.assistant_orchestrator.src.entrypoint import (
    AssistantOrchestratorService,
)
from shared.ipc.protocol import DEFAULT_MAX_MESSAGE_BYTES, MessageFramer


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

    def __init__(self, fake_gen, projects_root, *, enabled=True, clarify=True, revise=True,
                 advanced_intake=False, bad_input_floor=False, coherence_gate=False,
                 coverage_gate=False, criteria_revise=False, interview=False,
                 assets_pipeline=False,
                 interview_voice=False) -> None:
        self._framer = MessageFramer()
        self._fake_gen = fake_gen
        self._resolved_config = SimpleNamespace(
            fleet_dispatch_enabled=enabled,
            fleet_dispatch_clarify_enabled=clarify,
            fleet_dispatch_revise_enabled=revise,
            # #1031: dormant default here too — the harness must mirror production's
            # fail-closed posture, or a wiring regression would pass unnoticed.
            fleet_dispatch_advanced_intake_enabled=advanced_intake,
            # #1044: same discipline for the bad-input floor's own sub-gate.
            fleet_dispatch_bad_input_floor_enabled=bad_input_floor,
            # #1054: same, for the slice-E sub-gate.
            fleet_dispatch_advanced_intake_coherence_gate_enabled=coherence_gate,
            # #1069 S3-F: same, for the coverage-gate sub-gate.
            fleet_dispatch_advanced_intake_coverage_gate_enabled=coverage_gate,
            # #1069 S3-G: same, for the criteria-revise sub-gate.
            fleet_dispatch_advanced_intake_criteria_revise_enabled=criteria_revise,
            # #1031 S2: same, for the interview sub-gate.
            fleet_dispatch_advanced_intake_interview_enabled=interview,
            # #1165 M5: same, for the assets-pipeline sub-gate.
            fleet_dispatch_advanced_intake_assets_pipeline_enabled=assets_pipeline,
            # #1165 M1: same, for the interview-voice sub-gate.
            fleet_dispatch_advanced_intake_interview_voice_enabled=interview_voice,
            fleet_dispatch_agentic_setup_dir="",
            fleet_dispatch_projects_dir=str(projects_root),
            # #746: dormant by default in the harness — the PLAN handler threads it
            # into generate_plan, and OFF keeps the decompose prompt byte-identical.
            fleet_dispatch_research_grounding=False,
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
    fleet_dispatch_advanced_intake_enabled = (
        AssistantOrchestratorService.fleet_dispatch_advanced_intake_enabled
    )
    fleet_dispatch_bad_input_floor_enabled = (
        AssistantOrchestratorService.fleet_dispatch_bad_input_floor_enabled
    )
    fleet_dispatch_advanced_intake_coherence_gate_enabled = (
        AssistantOrchestratorService.fleet_dispatch_advanced_intake_coherence_gate_enabled
    )
    fleet_dispatch_advanced_intake_coverage_gate_enabled = (
        AssistantOrchestratorService.fleet_dispatch_advanced_intake_coverage_gate_enabled
    )
    fleet_dispatch_advanced_intake_criteria_revise_enabled = (
        AssistantOrchestratorService.fleet_dispatch_advanced_intake_criteria_revise_enabled
    )
    fleet_dispatch_advanced_intake_interview_enabled = (
        AssistantOrchestratorService.fleet_dispatch_advanced_intake_interview_enabled
    )
    fleet_dispatch_advanced_intake_assets_pipeline_enabled = (
        AssistantOrchestratorService.fleet_dispatch_advanced_intake_assets_pipeline_enabled
    )
    fleet_dispatch_advanced_intake_interview_voice_enabled = (
        AssistantOrchestratorService
        .fleet_dispatch_advanced_intake_interview_voice_enabled
    )
    fleet_dispatch_research_grounding = (
        AssistantOrchestratorService.fleet_dispatch_research_grounding
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


# ---------------------------------------------------------------------------
# #1031 S1 — the advanced-intake flag's REACHABILITY through the real handler.
#
# The spec-floor behaviour itself is unit-tested in shared/tests/test_advanced_intake.py.
# What these two pin is the thing unit tests structurally cannot: that the config flag
# actually ARRIVES at generate_plan. A flag defined, parsed, and resolved but never threaded
# is the built-but-wired-into-nothing class — it would leave every behaviour test green while
# the operator-facing feature did nothing at all.
# ---------------------------------------------------------------------------


def _web_gen(prompt: str) -> str:
    """A 14B stand-in for a WEB product — the surface the delivery floor keys on.

    Deliberately emits a criterion CLAIMING build tier with an EMPTY check, so both S1
    rulers have something to act on: the realism guard should demote it, and the delivery
    floor should then add a real machine-gated delivery criterion."""
    if "ACCEPTANCE CRITERIA" in prompt:
        return json.dumps([{"text": "the project builds", "tier": "build", "check": ""}])
    if "Classify what KIND of software" in prompt:
        return json.dumps({"surface": "web", "candidates": [], "language_hint": None,
                           "complexity": "simple", "components": []})
    return json.dumps([{"task": "build-page", "prompt": "build the page"}])


def _criteria_of(payload):
    return payload["criteria"]["criteria"]


def test_advanced_intake_flag_reaches_generate_plan(tmp_path):
    """Flag ON at the CONFIG layer ⇒ the spec that comes back out of the handler carries
    the delivery floor. This is the wiring proof, not a behaviour proof."""
    projects = tmp_path / "projects"
    repo = _git_repo(projects)
    h = _PlanHarness(_web_gen, projects, advanced_intake=True)
    t = _FakeTransport()
    assert h._handle_plan_request(t, "rid-ai-on", {"repo": repo, "goal": "a habit tracker page"})
    payload = h._framer.decode_plan_result(t.sent[0])
    assert payload["ok"] is True
    criteria = _criteria_of(payload)
    assert any(c["tier"] == "smoke" and "loads" in c["text"].lower() for c in criteria), \
        "advanced_intake=True did not reach generate_plan — the delivery floor never fired"
    assert not any(c["tier"] == "build" for c in criteria), \
        "the empty-check build criterion should have been demoted by the realism guard"


def test_advanced_intake_defaults_off_through_the_handler(tmp_path):
    """The toggle-off half, at the wiring layer: the harness's DEFAULT is dormant (mirroring
    production), and the spec is then today's — no floor, and the weak criterion keeps its
    claimed build tier. Without this, the test above could pass on unconditional behaviour."""
    projects = tmp_path / "projects"
    repo = _git_repo(projects)
    h = _PlanHarness(_web_gen, projects)  # no advanced_intake= ⇒ dormant, as in production
    t = _FakeTransport()
    assert h._handle_plan_request(t, "rid-ai-off", {"repo": repo, "goal": "a habit tracker page"})
    payload = h._framer.decode_plan_result(t.sent[0])
    criteria = _criteria_of(payload)
    assert any(c["tier"] == "build" for c in criteria)
    assert not any(c["tier"] == "smoke" and "loads" in c["text"].lower() for c in criteria)


# ---------------------------------------------------------------------------
# #1042 — the DORMANCY locks. The pre-merge review found all three "fail-closed
# default sites" unlocked: mutants flipping the dataclass default, the TOML parse
# default, and both resolved-property fallbacks each turned the capability ON and
# the whole 39-test suite stayed green. `_PlanHarness` cannot reach them — it builds
# a SimpleNamespace where the attribute is always present and `_resolved_config` is
# never None, so the test above pins the HARNESS's Python default argument, not any
# production default. It is a real WIRING lock; it was never a DORMANCY lock.
#
# For a branch whose entire justification for merging now is "it ships DORMANT behind
# a config flag", the dormancy IS the control — and `<security_by_design>` 12 requires
# every control ship with a proof it fails when disengaged.
# ---------------------------------------------------------------------------


def _config_tree(tmp_path, *, advanced_intake_line: "str | None"):
    """A real shipped default.toml copied into the nesting `_load_entrypoint_config`
    expects (`<root>/services/assistant_orchestrator/config/default.toml`), with the
    advanced_intake line REPLACED or REMOVED. Driving the real loader over a real file
    is the point: a stub would reproduce exactly the blind spot this closes."""
    import re
    from pathlib import Path

    real = Path(__file__).resolve().parents[1] / "config" / "default.toml"
    text = real.read_text(encoding="utf-8")
    pattern = re.compile(r"^advanced_intake\s*=.*$", re.M)
    assert pattern.search(text), "advanced_intake key missing from the shipped config"
    text = pattern.sub("", text) if advanced_intake_line is None else pattern.sub(
        advanced_intake_line, text)

    cfg_dir = tmp_path / "services" / "assistant_orchestrator" / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    dest = cfg_dir / "default.toml"
    dest.write_text(text, encoding="utf-8")
    return dest


def _resolve_advanced_intake(tmp_path, advanced_intake_line):
    """Run the REAL `_load_entrypoint_config` over that tree and return the resolved flag."""
    from shared.runtime_config import resolve_deployment_mode

    cfg_path = _config_tree(tmp_path, advanced_intake_line=advanced_intake_line)
    # A minimal stand-in carrying exactly the attributes _load_entrypoint_config reads —
    # the same unbound-method binding the rest of this file uses. Everything security- or
    # path-related is bound to the REAL methods so nothing about the parse is faked; only
    # the config PATH is redirected.
    svc = SimpleNamespace(
        _deployment_mode=resolve_deployment_mode("host"),
        _dev_mode_override=None,
    )
    svc._resolve_config_path = lambda: cfg_path
    svc._validate_config_data = (
        lambda data, path: AssistantOrchestratorService._validate_config_data(svc, data, path))
    svc._resolve_path = AssistantOrchestratorService._resolve_path  # staticmethod
    svc._validate_security_material = lambda *a, **k: None  # cert/key material is not under test
    loaded = AssistantOrchestratorService._load_entrypoint_config(svc)
    return loaded.fleet_dispatch_advanced_intake_enabled


def test_dormancy_dataclass_default_is_false():
    """Site 1 of 3 — the dataclass field default. Mutant M26 flipped this to True and the
    whole suite stayed green."""
    from services.assistant_orchestrator.src.entrypoint import (
        AssistantOrchestratorEntrypointConfig,
    )

    field = AssistantOrchestratorEntrypointConfig.__dataclass_fields__[
        "fleet_dispatch_advanced_intake_enabled"]
    assert field.default is False


def test_dormancy_toml_parse_resolves_false_for_absent_and_for_garbage(tmp_path):
    """Sites 2 — the TOML parse, driven through the REAL loader over a REAL shipped config.

    The absent-key half is what the branch always claimed. The garbage half is the defect
    the review found: `bool()` COERCES, `_validate_config_data` type-checks zero
    [fleet_dispatch] keys, so `advanced_intake = "false"` — the shape a hand-edited rollback
    takes — resolved TRUE and silently engaged a ceremony-gated capability."""
    assert _resolve_advanced_intake(tmp_path, None) is False              # key absent
    assert _resolve_advanced_intake(tmp_path, "advanced_intake = false") is False  # shipped
    assert _resolve_advanced_intake(tmp_path, "advanced_intake = true") is True    # the only ON

    # Every one of these resolved TRUE before #1042. None may engage the front.
    for line in (
        'advanced_intake = "false"',
        'advanced_intake = "0"',
        'advanced_intake = "off"',
        'advanced_intake = "no"',
        "advanced_intake = 1",
        "advanced_intake = [false]",
        'advanced_intake = "true"',   # even the truthy-LOOKING string is not a boolean
    ):
        assert _resolve_advanced_intake(tmp_path, line) is False, f"FAIL-OPEN on: {line}"


def test_dormancy_resolved_property_fallbacks_are_false():
    """Site 3 — both resolved-property fallbacks. Mutant M24 flipped them to True and
    survived. Covers: no resolved config at all (a pre-start() read), and a resolved config
    that lacks the attribute entirely."""
    prop = AssistantOrchestratorService.fleet_dispatch_advanced_intake_enabled.fget

    svc = SimpleNamespace(_resolved_config=None)
    assert prop(svc) is False                                   # pre-start()

    svc = SimpleNamespace(_resolved_config=SimpleNamespace())
    assert prop(svc) is False                                   # attribute absent

    # And the property validates rather than coerces, like the parse site.
    svc = SimpleNamespace(_resolved_config=SimpleNamespace(
        fleet_dispatch_advanced_intake_enabled="false"))
    assert prop(svc) is False
    svc = SimpleNamespace(_resolved_config=SimpleNamespace(
        fleet_dispatch_advanced_intake_enabled=True))
    assert prop(svc) is True


# ---------------------------------------------------------------------------
# #1044 — the bad-input exam floor's own sub-gate, at the WIRING layer.
#
# The floor rides advanced-intake mode but must NOT go live with it: `advanced_intake` is
# already true in the shipped config, so a floor that resolved from that key alone would have
# changed what a build is graded on the moment this merged, with no ceremony. Every test below
# exists to make that collapse fail loudly rather than silently.
# ---------------------------------------------------------------------------


_BIF_MARKER = "blarai-bad-input-floor-v1"


def _python_job_gen(prompt):
    """A python, multi-task goal with a job-level exam — the shape the floor acts on.
    (``_web_gen`` above resolves to the NODE ecosystem and a single task, so it can never
    exercise this path.)"""
    if "decomposing a software change request" in prompt:
        return json.dumps([
            {"task": "engine", "prompt": "build the quiz engine", "depends_on": [],
             "contract": {"creates": ["app/quiz_engine.py"],
                          "exports": ["run_quiz(cards, answer_fn)"], "notes": ""}},
            {"task": "cli", "prompt": "build the cli", "depends_on": ["engine"],
             "contract": {"creates": ["app/cli.py"], "exports": ["main()"], "notes": ""}},
        ])
    if "ACCEPTANCE CRITERIA" in prompt:
        return json.dumps([{"text": "It scores a correct answer", "tier": "behavior",
                            "check": "run the quiz and check the tally"}])
    if "Classify what KIND of software" in prompt:
        return json.dumps({"surface": "command-line", "candidates": [],
                           "language_hint": "python", "complexity": "simple",
                           "components": []})
    if "JOB-LEVEL ACCEPTANCE" in prompt:
        return ("```python\n"
                "from app.quiz_engine import run_quiz\n"
                "\n"
                "def test_scores():\n"
                "    assert run_quiz([{'question': 'q', 'answer': 'a'}], lambda q: 'a')\n"
                "```\n")
    return "[]"


def _job_exam_of(payload):
    from shared.fleet.acceptance import JOB_ORACLE_CODE_KEY

    return str((payload.get("tasks") or [{}])[-1].get(JOB_ORACLE_CODE_KEY, ""))


def _plan_with(tmp_path, **flags):
    projects = tmp_path / "projects"
    repo = _git_repo(projects)
    h = _PlanHarness(_python_job_gen, projects, **flags)
    t = _FakeTransport()
    assert h._handle_plan_request(t, "rid-bif", {"repo": repo, "goal": "a flashcards quiz"})
    payload = h._framer.decode_plan_result(t.sent[0])
    assert payload["ok"] is True
    return payload


def test_bad_input_floor_flag_reaches_generate_plan(tmp_path):
    """Both flags ON at the CONFIG layer ⇒ the exam that comes back out of the handler carries
    the floor. The wiring proof — built-but-wired-into-nothing is the recurring failure this
    catches, and nothing else in the suite drives this flag through the real handler."""
    payload = _plan_with(tmp_path, advanced_intake=True, bad_input_floor=True)
    assert _BIF_MARKER in _job_exam_of(payload), \
        "bad_input_floor=True did not reach generate_plan — the exam floor never fired"


def test_the_LIVE_advanced_intake_flag_alone_does_not_engage_the_floor(tmp_path):
    """The load-bearing one. ``advanced_intake`` is true in the shipped config, so if the floor
    ever resolves from it alone, merging becomes a silent capability change."""
    payload = _plan_with(tmp_path, advanced_intake=True)
    assert _BIF_MARKER not in _job_exam_of(payload)


def test_bad_input_floor_defaults_off_through_the_handler(tmp_path):
    """The harness default mirrors production's dormant posture; without this, the test above
    could be passing on behaviour that is simply unreachable."""
    payload = _plan_with(tmp_path)
    assert _BIF_MARKER not in _job_exam_of(payload)


def _resolve_bad_input_floor(tmp_path, line):
    """Resolve ``[fleet_dispatch].advanced_intake_bad_input_floor`` through the REAL loader over
    a REAL copy of the shipped config, with that key's line replaced or removed."""
    import re
    from pathlib import Path

    from shared.runtime_config import resolve_deployment_mode

    real = Path(__file__).resolve().parents[1] / "config" / "default.toml"
    text = real.read_text(encoding="utf-8")
    pattern = re.compile(r"^advanced_intake_bad_input_floor\s*=.*$", re.M)
    assert pattern.search(text), \
        "advanced_intake_bad_input_floor key missing from the shipped config"
    text = pattern.sub("", text) if line is None else pattern.sub(line, text)

    cfg_dir = tmp_path / "services" / "assistant_orchestrator" / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    dest = cfg_dir / "default.toml"
    dest.write_text(text, encoding="utf-8")

    svc = SimpleNamespace(_deployment_mode=resolve_deployment_mode("host"),
                          _dev_mode_override=None)
    svc._resolve_config_path = lambda: dest
    svc._validate_config_data = (
        lambda data, path: AssistantOrchestratorService._validate_config_data(svc, data, path))
    svc._resolve_path = AssistantOrchestratorService._resolve_path
    svc._validate_security_material = lambda *a, **k: None
    return AssistantOrchestratorService._load_entrypoint_config(
        svc).fleet_dispatch_bad_input_floor_enabled


def test_the_shipped_config_ships_the_floor_LIVE(tmp_path):
    """The switch label the Lead Architect reads at a ceremony must match the switch. Read from
    the real file, not asserted from memory."""
    assert _resolve_bad_input_floor(
        tmp_path, "advanced_intake_bad_input_floor = false") is False
    assert _resolve_bad_input_floor(
        tmp_path, "advanced_intake_bad_input_floor = true") is True
    assert _resolve_bad_input_floor(tmp_path, None) is False   # key absent ⇒ dormant

    import tomllib
    from pathlib import Path

    real = Path(__file__).resolve().parents[1] / "config" / "default.toml"
    with real.open("rb") as fh:
        data = tomllib.load(fh)
    assert data["fleet_dispatch"]["advanced_intake_bad_input_floor"] is True, (
        "the SHIPPED value regressed from LIVE — reversal is an LA decision "
        "(batched S3 ceremony 2026-07-29, docs/DECISION_REGISTER.md)")


@pytest.mark.parametrize("line", [
    'advanced_intake_bad_input_floor = "false"',
    'advanced_intake_bad_input_floor = "true"',
    'advanced_intake_bad_input_floor = "0"',
    "advanced_intake_bad_input_floor = 1",
    "advanced_intake_bad_input_floor = [false]",
])
def test_only_an_explicit_boolean_true_engages_the_floor(line, tmp_path):
    """#1042's validate-don't-coerce rule, applied to the new key: a quoted "false" — the shape
    a hand-edited rollback takes — must not resolve TRUE, and neither may any other truthy
    non-boolean."""
    assert _resolve_bad_input_floor(tmp_path, line) is False, f"FAIL-OPEN on: {line}"


def test_bad_input_floor_resolved_property_fallbacks_are_false():
    """The three dormancy sites for the new key: no resolved config (a pre-``start()`` read), a
    resolved config missing the attribute, and a non-boolean attribute value."""
    prop = AssistantOrchestratorService.fleet_dispatch_bad_input_floor_enabled.fget

    assert prop(SimpleNamespace(_resolved_config=None)) is False
    assert prop(SimpleNamespace(_resolved_config=SimpleNamespace())) is False
    assert prop(SimpleNamespace(_resolved_config=SimpleNamespace(
        fleet_dispatch_bad_input_floor_enabled="false"))) is False
    assert prop(SimpleNamespace(_resolved_config=SimpleNamespace(
        fleet_dispatch_bad_input_floor_enabled=True))) is True


def test_bad_input_floor_dataclass_default_is_false():
    """The third dormancy site: the dataclass field default itself. Its sibling above records
    that mutant M26 flipped exactly this and the whole suite stayed green."""
    from services.assistant_orchestrator.src.entrypoint import (
        AssistantOrchestratorEntrypointConfig,
    )

    assert AssistantOrchestratorEntrypointConfig.__dataclass_fields__[
        "fleet_dispatch_bad_input_floor_enabled"].default is False


# ---------------------------------------------------------------------------
# #1054 S3 slice E — the coherence sub-gate's REACHABILITY and its DORMANCY.
#
# Same two-layer shape as #1031/#1042 above, for the same two reasons. The gate's own
# behaviour is unit-tested in shared/tests/test_coherence_gate.py; what these pin is that
# the config key ARRIVES at generate_plan (a flag parsed but never threaded is the
# built-but-wired-into-nothing class), and that every fail-closed default site really is
# closed — for a slice whose entire justification for merging now is that it ships dormant,
# the dormancy IS the control.
# ---------------------------------------------------------------------------

_CONTRADICTING_ASSUMPTION = "Assumed a reset button is not needed."
_CONTRADICTING_CRITERION = (
    "The web page includes a reset button to reset the daily water intake counter to zero."
)


def _contradicting_gen(prompt: str) -> str:
    """A 14B stand-in that emits the #1054 live defect down EITHER authoring path, so the
    only difference between the two tests below is the flag."""
    criteria = [
        {"text": "The page has a button that adds one glass to the running total.",
         "tier": "behavior", "check": "assert add_glass() increments the total"},
        {"text": _CONTRADICTING_CRITERION,
         "tier": "behavior", "check": "assert reset() sets the total to zero"},
    ]
    if "ONE document containing BOTH" in prompt:          # the co-authored (one-pass) call
        return json.dumps({"assumptions": [_CONTRADICTING_ASSUMPTION], "criteria": criteria})
    if "You are defining ACCEPTANCE CRITERIA" in prompt:
        return json.dumps(criteria)
    if "A non-technical person asked for" in prompt:
        return json.dumps([_CONTRADICTING_ASSUMPTION])
    if "Classify what KIND of software" in prompt:
        return json.dumps({"surface": "web", "candidates": [], "language_hint": None,
                           "complexity": "simple", "components": []})
    return json.dumps([{"task": "build-page", "prompt": "build the page"}])


def test_coherence_gate_flag_reaches_generate_plan(tmp_path):
    """Both flags ON at the CONFIG layer ⇒ the self-contradicting plan is REFUSED by the
    handler, with the two disagreeing sentences named. The wiring proof."""
    projects = tmp_path / "projects"
    repo = _git_repo(projects)
    h = _PlanHarness(_contradicting_gen, projects, advanced_intake=True, coherence_gate=True)
    t = _FakeTransport()
    assert h._handle_plan_request(
        t, "rid-cg-on", {"repo": repo, "goal": "a water tracker page"})
    payload = h._framer.decode_plan_result(t.sent[0])
    assert payload["ok"] is False, \
        "coherence_gate=True did not reach generate_plan — the contradiction was offered"
    assert _CONTRADICTING_ASSUMPTION in payload["message"]
    assert _CONTRADICTING_CRITERION in payload["message"]


def test_coherence_gate_defaults_off_through_the_handler(tmp_path):
    """The toggle-off half at the wiring layer: the harness default is dormant (mirroring
    production), so the IDENTICAL contradicting spec is offered exactly as it was live on
    2026-07-22. Without this the test above could pass on unconditional behaviour."""
    projects = tmp_path / "projects"
    repo = _git_repo(projects)
    h = _PlanHarness(_contradicting_gen, projects, advanced_intake=True)  # gate dormant
    t = _FakeTransport()
    assert h._handle_plan_request(
        t, "rid-cg-off", {"repo": repo, "goal": "a water tracker page"})
    payload = h._framer.decode_plan_result(t.sent[0])
    assert payload["ok"] is True
    assert any(c["text"] == _CONTRADICTING_CRITERION for c in _criteria_of(payload)), \
        "the contradicting criterion is absent with the gate off — the probe is vacuous"


def _gapped_exam_gen(prompt: str) -> str:
    """A two-task decomposition with 1:1-able contracts whose job exam imports only ONE of
    them — the #1069 S3-F trigger shape, stubborn across the repair round."""
    if "decomposing a software change request" in prompt:
        return json.dumps([
            {"task": "engine", "prompt": "build the quiz engine", "depends_on": [],
             "contract": {"creates": ["app/quiz_engine.py"],
                          "exports": ["run_quiz(cards, answer_fn)"], "notes": ""}},
            {"task": "cli", "prompt": "build the cli", "depends_on": ["engine"],
             "contract": {"creates": ["app/cli.py"], "exports": ["main()"], "notes": ""}},
        ])
    if "ACCEPTANCE CRITERIA" in prompt:
        return json.dumps([{"text": "It scores a correct answer", "tier": "behavior",
                            "check": "run the quiz and check the tally"}])
    if "Classify what KIND of software" in prompt:
        return json.dumps({"surface": "command-line", "candidates": [],
                           "language_hint": "python", "complexity": "simple",
                           "components": []})
    if "JOB-LEVEL ACCEPTANCE" in prompt:
        return (
            "```python\n"
            "from app.quiz_engine import run_quiz\n"
            "\n"
            "def test_scores():\n"
            "    assert run_quiz([{'question': 'q', 'answer': 'a'}], lambda q: 'a')"
            " == {'asked': 1, 'correct': 1}\n"
            "```\n"
        )
    return "[]"


def test_coverage_gate_flag_reaches_generate_plan(tmp_path):
    """Both flags ON at the CONFIG layer ⇒ the surviving gap rides OUT of the handler as a
    non-empty ``coverage_blocked`` in the PLAN_RESULT frame — the wiring proof AND the
    field's crossing of the real framer (the #1152-class seam)."""
    projects = tmp_path / "projects"
    repo = _git_repo(projects)
    h = _PlanHarness(_gapped_exam_gen, projects, advanced_intake=True, coverage_gate=True)
    t = _FakeTransport()
    assert h._handle_plan_request(
        t, "rid-cov-on", {"repo": repo, "goal": "a flashcards quiz"})
    payload = h._framer.decode_plan_result(t.sent[0])
    assert payload["ok"] is True, "a blocked plan still renders — blocked, never refused"
    assert payload["coverage_blocked"], \
        "coverage_gate=True did not reach generate_plan — no blocking marker came back"
    assert "cli" in payload["coverage_blocked"], "the marker must name the uncovered task"


def test_coverage_gate_defaults_off_through_the_handler(tmp_path):
    """The toggle-off half at the wiring layer: with the harness's dormant default, the
    IDENTICAL gapped exam yields an approvable plan with an empty marker — the
    warn-loud quick-path behaviour."""
    projects = tmp_path / "projects"
    repo = _git_repo(projects)
    h = _PlanHarness(_gapped_exam_gen, projects, advanced_intake=True)  # gate dormant
    t = _FakeTransport()
    assert h._handle_plan_request(
        t, "rid-cov-off", {"repo": repo, "goal": "a flashcards quiz"})
    payload = h._framer.decode_plan_result(t.sent[0])
    assert payload["ok"] is True
    assert payload["coverage_blocked"] == ""
    assert "CONTRACT-COVERAGE WARNING" in payload["message"], \
        "the quick path's warn-loud disclosure disappeared — the probe is vacuous"


def _criteria_revise_gen(prompt: str) -> str:
    """Answers a criteria-revise authoring prompt with one keep + one judged add."""
    if "The current criteria:" in prompt and "The person's feedback:" in prompt:
        return json.dumps([{"op": "keep", "ref": 1},
                           {"op": "add", "text": "it looks tidy on a phone"}])
    return "[]"


def test_criteria_revise_flag_reaches_generate_plan(tmp_path):
    """Both flags ON ⇒ a criteria-revise sentinel goal comes back as edit ops in the
    PLAN_RESULT's ``criteria_revision`` — the wiring proof AND the field's crossing of the
    real framer."""
    from shared.fleet import revise as _revise

    projects = tmp_path / "projects"
    repo = _git_repo(projects)
    goal = _revise.compose_criteria_revision_goal(
        "a flashcards quiz", "also check it looks tidy on a phone",
        [{"id": "c1", "text": "it scores", "tier": "behavior", "check": "run it"}],
    )
    h = _PlanHarness(_criteria_revise_gen, projects,
                     advanced_intake=True, criteria_revise=True)
    t = _FakeTransport()
    assert h._handle_plan_request(t, "rid-cr-on", {"repo": repo, "goal": goal})
    payload = h._framer.decode_plan_result(t.sent[0])
    assert payload["ok"] is True
    assert payload["criteria_revision"], \
        "criteria_revise=True did not reach generate_plan — no ops came back"
    assert payload["criteria_revision"][0]["op"] == "keep"


def test_the_shipped_config_ships_the_coverage_gate_LIVE():
    """The shipped posture itself, read from the file the LA flips at the ceremony."""
    import tomllib
    from pathlib import Path

    real = Path(__file__).resolve().parents[1] / "config" / "default.toml"
    with real.open("rb") as fh:
        data = tomllib.load(fh)
    assert data["fleet_dispatch"]["advanced_intake_coverage_gate"] is True, (
        "the SHIPPED value regressed from LIVE — reversal is an LA decision "
        "(batched S3 ceremony 2026-07-29, docs/DECISION_REGISTER.md)")


def test_the_shipped_config_ships_criteria_revise_LIVE():
    """The shipped posture itself, read from the file the LA flips at the ceremony."""
    import tomllib
    from pathlib import Path

    real = Path(__file__).resolve().parents[1] / "config" / "default.toml"
    with real.open("rb") as fh:
        data = tomllib.load(fh)
    assert data["fleet_dispatch"]["advanced_intake_criteria_revise"] is True, (
        "the SHIPPED value regressed from LIVE — reversal is an LA decision "
        "(batched S3 ceremony 2026-07-29, docs/DECISION_REGISTER.md)")


def test_the_shipped_config_ships_the_interview_LIVE():
    """The shipped posture itself, read from the file the LA flips at the ceremony."""
    import tomllib
    from pathlib import Path

    real = Path(__file__).resolve().parents[1] / "config" / "default.toml"
    with real.open("rb") as fh:
        data = tomllib.load(fh)
    assert data["fleet_dispatch"]["advanced_intake_interview"] is True, (
        "the SHIPPED value regressed from LIVE — reversal is an LA decision "
        "(S2 interview ceremony 2026-07-29, docs/DECISION_REGISTER.md)")


def test_the_shipped_config_ships_the_assets_pipeline_DORMANT():
    """#1165 M5 merges DORMANT: the shipped key is an explicit boolean ``false`` until
    the maturation program's LA-present ceremony flips it. A missing key would also
    resolve False, but the EXPLICIT false is the register the ceremony flips."""
    import tomllib
    from pathlib import Path

    real = Path(__file__).resolve().parents[1] / "config" / "default.toml"
    with real.open("rb") as fh:
        data = tomllib.load(fh)
    assert data["fleet_dispatch"]["advanced_intake_assets_pipeline"] is True, (
        "the assets pipeline is LIVE since the 2026-07-29 LA-present ceremony "
        "(#1165 M5); a silent revert to dormant would drop the capability")


def test_plan_handler_threads_assets_pipeline_both_ways(tmp_path):
    """#1165 M5 wiring lock: the handler's ``assets_pipeline=`` kwarg reaches
    generate_plan — ON (with the front) a file-bearing ``assets/`` folder lands the
    manifest + the acknowledgment; OFF (sub-gate dormant, front still on) the same
    folder changes nothing (byte-identical criteria payload, no manifest)."""
    projects = tmp_path / "projects"
    repo = _git_repo(projects)
    assets = projects / repo / "assets"
    assets.mkdir()
    (assets / "logo.svg").write_bytes(b"x" * 10)

    on = _PlanHarness(_good_gen, projects, advanced_intake=True, assets_pipeline=True)
    t_on = _FakeTransport()
    assert on._handle_plan_request(t_on, "rid-ap-on", {"repo": repo, "goal": "a page"})
    payload_on = on._framer.decode_plan_result(t_on.sent[0])
    assert payload_on["ok"] is True
    manifest = payload_on["criteria"].get("operator_assets")
    assert manifest and [f["name"] for f in manifest["files"]] == ["logo.svg"]

    off = _PlanHarness(_good_gen, projects, advanced_intake=True)  # sub-gate dormant
    t_off = _FakeTransport()
    assert off._handle_plan_request(
        t_off, "rid-ap-off", {"repo": repo, "goal": "a page"})
    payload_off = off._framer.decode_plan_result(t_off.sent[0])
    assert payload_off["ok"] is True
    assert "operator_assets" not in payload_off["criteria"], (
        "the dormant sub-gate leaked the manifest into the plan payload")


def test_criteria_revise_defaults_off_through_the_handler(tmp_path):
    """Dormant default: the identical sentinel goal is refused Fail-Closed — ok=False with
    the honest off message, and no ops payload."""
    from shared.fleet import revise as _revise

    projects = tmp_path / "projects"
    repo = _git_repo(projects)
    goal = _revise.compose_criteria_revision_goal(
        "a flashcards quiz", "also check it looks tidy on a phone",
        [{"id": "c1", "text": "it scores", "tier": "behavior", "check": "run it"}],
    )
    h = _PlanHarness(_criteria_revise_gen, projects, advanced_intake=True)  # sub-gate dormant
    t = _FakeTransport()
    assert h._handle_plan_request(t, "rid-cr-off", {"repo": repo, "goal": goal})
    payload = h._framer.decode_plan_result(t.sent[0])
    assert payload["ok"] is False
    assert "turned off" in payload["message"]
    assert payload["criteria_revision"] == []


def _coherence_config_tree(tmp_path, line: "str | None"):
    """The shipped default.toml with the coherence-gate line REPLACED or REMOVED. Its own
    helper rather than a parameter on ``_config_tree``: the two keys must be substitutable
    independently, and that helper's pattern deliberately does not match this longer key."""
    import re
    from pathlib import Path

    real = Path(__file__).resolve().parents[1] / "config" / "default.toml"
    text = real.read_text(encoding="utf-8")
    pattern = re.compile(r"^advanced_intake_coherence_gate\s*=.*$", re.M)
    assert pattern.search(text), "advanced_intake_coherence_gate missing from shipped config"
    text = pattern.sub("", text) if line is None else pattern.sub(line, text)

    cfg_dir = tmp_path / "services" / "assistant_orchestrator" / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    dest = cfg_dir / "default.toml"
    dest.write_text(text, encoding="utf-8")
    return dest


def _resolve_coherence_gate(tmp_path, line):
    """Run the REAL ``_load_entrypoint_config`` over that tree and return the resolved flag."""
    from shared.runtime_config import resolve_deployment_mode

    cfg_path = _coherence_config_tree(tmp_path, line)
    svc = SimpleNamespace(
        _deployment_mode=resolve_deployment_mode("host"),
        _dev_mode_override=None,
    )
    svc._resolve_config_path = lambda: cfg_path
    svc._validate_config_data = (
        lambda data, path: AssistantOrchestratorService._validate_config_data(svc, data, path))
    svc._resolve_path = AssistantOrchestratorService._resolve_path
    svc._validate_security_material = lambda *a, **k: None
    loaded = AssistantOrchestratorService._load_entrypoint_config(svc)
    return loaded.fleet_dispatch_advanced_intake_coherence_gate_enabled


def test_coherence_gate_dormancy_dataclass_default_is_false():
    from services.assistant_orchestrator.src.entrypoint import (
        AssistantOrchestratorEntrypointConfig,
    )

    field = AssistantOrchestratorEntrypointConfig.__dataclass_fields__[
        "fleet_dispatch_advanced_intake_coherence_gate_enabled"]
    assert field.default is False


def test_coherence_gate_dormancy_toml_parse_validates_rather_than_coerces(tmp_path):
    """The #1042 rule, applied to the new key on the day it exists rather than after a
    review finds it: only an explicit TOML boolean ``true`` may engage a ceremony-gated
    capability (the shipped value itself is owned by the live-pin test)."""
    assert _resolve_coherence_gate(tmp_path, None) is False
    assert _resolve_coherence_gate(
        tmp_path, "advanced_intake_coherence_gate = false") is False
    assert _resolve_coherence_gate(
        tmp_path, "advanced_intake_coherence_gate = true") is True
    for line in (
        'advanced_intake_coherence_gate = "false"',
        'advanced_intake_coherence_gate = "true"',
        'advanced_intake_coherence_gate = "off"',
        "advanced_intake_coherence_gate = 1",
        "advanced_intake_coherence_gate = [false]",
    ):
        assert _resolve_coherence_gate(tmp_path, line) is False, f"FAIL-OPEN on: {line}"


def test_coherence_gate_ships_live_in_the_real_config():
    """The shipped posture itself, read from the file the LA flips at the ceremony."""
    import tomllib
    from pathlib import Path

    real = Path(__file__).resolve().parents[1] / "config" / "default.toml"
    with real.open("rb") as fh:
        data = tomllib.load(fh)
    assert data["fleet_dispatch"]["advanced_intake_coherence_gate"] is True, (
        "the SHIPPED value regressed from LIVE — reversal is an LA decision "
        "(batched S3 ceremony 2026-07-29, docs/DECISION_REGISTER.md)")


def test_coherence_gate_resolved_property_fallbacks_are_false():
    prop = (AssistantOrchestratorService
            .fleet_dispatch_advanced_intake_coherence_gate_enabled.fget)

    assert prop(SimpleNamespace(_resolved_config=None)) is False        # pre-start()
    assert prop(SimpleNamespace(_resolved_config=SimpleNamespace())) is False  # absent
    assert prop(SimpleNamespace(_resolved_config=SimpleNamespace(
        fleet_dispatch_advanced_intake_coherence_gate_enabled="false"))) is False
    assert prop(SimpleNamespace(_resolved_config=SimpleNamespace(
        fleet_dispatch_advanced_intake_coherence_gate_enabled=True))) is True


# ---------------------------------------------------------------------------
# #1165 M4 — the playback sub-key resolves fail-closed, ships dormant
# ---------------------------------------------------------------------------


def _playback_config_tree(tmp_path, line: "str | None"):
    """The shipped default.toml with the playback line REPLACED or REMOVED — the
    same substitution shape as the coherence helper above, on its own key."""
    import re
    from pathlib import Path

    real = Path(__file__).resolve().parents[1] / "config" / "default.toml"
    text = real.read_text(encoding="utf-8")
    pattern = re.compile(r"^advanced_intake_interview_playback\s*=.*$", re.M)
    assert pattern.search(text), \
        "advanced_intake_interview_playback missing from shipped config"
    text = pattern.sub("", text) if line is None else pattern.sub(line, text)

    cfg_dir = tmp_path / "services" / "assistant_orchestrator" / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    dest = cfg_dir / "default.toml"
    dest.write_text(text, encoding="utf-8")
    return dest


def _resolve_playback(tmp_path, line):
    """Run the REAL ``_load_entrypoint_config`` over that tree and return the resolved flag."""
    from shared.runtime_config import resolve_deployment_mode

    cfg_path = _playback_config_tree(tmp_path, line)
    svc = SimpleNamespace(
        _deployment_mode=resolve_deployment_mode("host"),
        _dev_mode_override=None,
    )
    svc._resolve_config_path = lambda: cfg_path
    svc._validate_config_data = (
        lambda data, path: AssistantOrchestratorService._validate_config_data(svc, data, path))
    svc._resolve_path = AssistantOrchestratorService._resolve_path
    svc._validate_security_material = lambda *a, **k: None
    loaded = AssistantOrchestratorService._load_entrypoint_config(svc)
    return loaded.fleet_dispatch_advanced_intake_interview_playback_enabled


def test_playback_dormancy_dataclass_default_is_false():
    from services.assistant_orchestrator.src.entrypoint import (
        AssistantOrchestratorEntrypointConfig,
    )

    field = AssistantOrchestratorEntrypointConfig.__dataclass_fields__[
        "fleet_dispatch_advanced_intake_interview_playback_enabled"]
    assert field.default is False


def test_playback_dormancy_toml_parse_validates_rather_than_coerces(tmp_path):
    """The #1042 rule, applied to the new key on the day it exists: only an explicit
    TOML boolean ``true`` may engage a ceremony-gated capability (the shipped value
    itself is owned by the dormant-pin test below)."""
    assert _resolve_playback(tmp_path, None) is False
    assert _resolve_playback(
        tmp_path, "advanced_intake_interview_playback = false") is False
    assert _resolve_playback(
        tmp_path, "advanced_intake_interview_playback = true") is True
    for line in (
        'advanced_intake_interview_playback = "false"',
        'advanced_intake_interview_playback = "true"',
        'advanced_intake_interview_playback = "off"',
        "advanced_intake_interview_playback = 1",
        "advanced_intake_interview_playback = [false]",
    ):
        assert _resolve_playback(tmp_path, line) is False, f"FAIL-OPEN on: {line}"


def test_playback_ships_dormant_in_the_real_config():
    """The shipped posture itself: DORMANT until the LA-present interview-maturation
    ceremony flips it (design §7; the flip is never a build-time decision)."""
    import tomllib
    from pathlib import Path

    real = Path(__file__).resolve().parents[1] / "config" / "default.toml"
    with real.open("rb") as fh:
        data = tomllib.load(fh)
    assert data["fleet_dispatch"]["advanced_intake_interview_playback"] is True, (
        "the playback turn is LIVE since the 2026-07-29 LA-present ceremony "
        "(#1165 M4, docs/runbooks/advanced_intake_maturation_batched_ceremony.md)")


def test_playback_resolved_property_fallbacks_are_false():
    prop = (AssistantOrchestratorService
            .fleet_dispatch_advanced_intake_interview_playback_enabled.fget)

    assert prop(SimpleNamespace(_resolved_config=None)) is False        # pre-start()
    assert prop(SimpleNamespace(_resolved_config=SimpleNamespace())) is False  # absent
    assert prop(SimpleNamespace(_resolved_config=SimpleNamespace(
        fleet_dispatch_advanced_intake_interview_playback_enabled="false"))) is False
    assert prop(SimpleNamespace(_resolved_config=SimpleNamespace(
        fleet_dispatch_advanced_intake_interview_playback_enabled=True))) is True


# ---------------------------------------------------------------------------
# #1165 M1 — the interview-voice sub-flag: the four dormancy locks + the wiring
# ---------------------------------------------------------------------------


def _voice_config_tree(tmp_path, line: "str | None"):
    """The shipped default.toml with the interview-voice line REPLACED or REMOVED (the
    coherence helper's pattern — its own regex, so the two keys stay independently
    substitutable)."""
    import re
    from pathlib import Path

    real = Path(__file__).resolve().parents[1] / "config" / "default.toml"
    text = real.read_text(encoding="utf-8")
    pattern = re.compile(r"^advanced_intake_interview_voice\s*=.*$", re.M)
    assert pattern.search(text), \
        "advanced_intake_interview_voice missing from shipped config"
    text = pattern.sub("", text) if line is None else pattern.sub(line, text)

    cfg_dir = tmp_path / "services" / "assistant_orchestrator" / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    dest = cfg_dir / "default.toml"
    dest.write_text(text, encoding="utf-8")
    return dest


def _resolve_voice(tmp_path, line):
    """Run the REAL ``_load_entrypoint_config`` over that tree and return the resolved flag."""
    from shared.runtime_config import resolve_deployment_mode

    cfg_path = _voice_config_tree(tmp_path, line)
    svc = SimpleNamespace(
        _deployment_mode=resolve_deployment_mode("host"),
        _dev_mode_override=None,
    )
    svc._resolve_config_path = lambda: cfg_path
    svc._validate_config_data = (
        lambda data, path: AssistantOrchestratorService._validate_config_data(svc, data, path))
    svc._resolve_path = AssistantOrchestratorService._resolve_path
    svc._validate_security_material = lambda *a, **k: None
    loaded = AssistantOrchestratorService._load_entrypoint_config(svc)
    return loaded.fleet_dispatch_advanced_intake_interview_voice_enabled


def test_interview_voice_dormancy_dataclass_default_is_false():
    from services.assistant_orchestrator.src.entrypoint import (
        AssistantOrchestratorEntrypointConfig,
    )

    field = AssistantOrchestratorEntrypointConfig.__dataclass_fields__[
        "fleet_dispatch_advanced_intake_interview_voice_enabled"]
    assert field.default is False


def test_interview_voice_toml_parse_validates_rather_than_coerces(tmp_path):
    """The #1042 rule, applied to the new key on the day it exists: only an explicit
    TOML boolean ``true`` may engage a ceremony-gated capability."""
    assert _resolve_voice(tmp_path, None) is False
    assert _resolve_voice(
        tmp_path, "advanced_intake_interview_voice = false") is False
    assert _resolve_voice(
        tmp_path, "advanced_intake_interview_voice = true") is True
    for line in (
        'advanced_intake_interview_voice = "false"',
        'advanced_intake_interview_voice = "true"',
        'advanced_intake_interview_voice = "off"',
        "advanced_intake_interview_voice = 1",
        "advanced_intake_interview_voice = [false]",
    ):
        assert _resolve_voice(tmp_path, line) is False, f"FAIL-OPEN on: {line}"


def test_interview_voice_ships_dormant_in_the_real_config():
    """The shipped posture itself: DORMANT until the #1165 M1-M6 batched LA ceremony."""
    import tomllib
    from pathlib import Path

    real = Path(__file__).resolve().parents[1] / "config" / "default.toml"
    with real.open("rb") as fh:
        data = tomllib.load(fh)
    assert data["fleet_dispatch"]["advanced_intake_interview_voice"] is True, (
        "the interview voice is LIVE since the 2026-07-29 LA-present ceremony "
        "(#1165 M1); a silent revert to dormant would drop the capability")


def test_interview_voice_resolved_property_fallbacks_are_false():
    prop = (AssistantOrchestratorService
            .fleet_dispatch_advanced_intake_interview_voice_enabled.fget)

    assert prop(SimpleNamespace(_resolved_config=None)) is False        # pre-start()
    assert prop(SimpleNamespace(_resolved_config=SimpleNamespace())) is False  # absent
    assert prop(SimpleNamespace(_resolved_config=SimpleNamespace(
        fleet_dispatch_advanced_intake_interview_voice_enabled="false"))) is False
    assert prop(SimpleNamespace(_resolved_config=SimpleNamespace(
        fleet_dispatch_advanced_intake_interview_voice_enabled=True))) is True


class _RecordingGen:
    """Records prompts; asks one intake question at the clarify stage."""

    def __init__(self):
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if "decision areas" in prompt:
            return json.dumps([{"axis": "content",
                                "question": "What should it start with?"}])
        return "[]"


def test_interview_voice_flag_reaches_generate_plan(tmp_path):
    """The wiring proof through the REAL handler: voice on ⇒ the engaged interview's
    authoring prompt carries the mistake rules; voice off ⇒ the S2 template's bytes."""
    from shared.fleet.clarify import _INTAKE_TEMPLATE, compose_intake_goal

    projects = tmp_path / "projects"
    repo = _git_repo(projects)
    goal = compose_intake_goal("a recipe box")
    on, off = _RecordingGen(), _RecordingGen()
    h_on = _PlanHarness(on, projects, advanced_intake=True, interview=True,
                        interview_voice=True)
    h_off = _PlanHarness(off, projects, advanced_intake=True, interview=True)
    assert h_on._handle_plan_request(_FakeTransport(), "rid-v-on",
                                     {"repo": repo, "goal": goal})
    assert h_off._handle_plan_request(_FakeTransport(), "rid-v-off",
                                      {"repo": repo, "goal": goal})
    prompt_on = next(p for p in on.prompts if "decision areas" in p)
    prompt_off = next(p for p in off.prompts if "decision areas" in p)
    assert "one decision per question" in prompt_on, \
        "interview_voice=True did not reach generate_plan"
    assert prompt_off == _INTAKE_TEMPLATE.format(max_questions=8, idea="a recipe box")


# ---------------------------------------------------------------------------
# #1152 — an over-cap PLAN result must FAIL LOUD, not vanish
# ---------------------------------------------------------------------------
# THE INCIDENT (2026-07-28): the plan SUCCEEDED and its result frame exceeded the IPC
# cap (65891 and 66938 bytes against the then-64 KB cap on two live operator runs).
# `encode` raised, the exception unwound to the serve loop, the connection was dropped,
# and the operator saw "No response from the Assistant Orchestrator" — a message that
# says the AO went SILENT when it had in fact finished the work and could not deliver
# it. It cost a full diagnostic arc and one merged fix aimed at the wrong cause.
#
# The cap was then raised 64 KB -> 256 KB, but a bigger number is not the control: the
# payload grows O(n_tasks x (goal + requirements)), so headroom can always be consumed
# again. The CONTROL is that exceeding it reports honestly. These tests pin that, and
# they use a deliberately tiny cap rather than building a 66 KB payload — the defect is
# about the RELATION between payload and cap, not about any particular size.


def test_over_cap_plan_result_returns_an_honest_refusal(tmp_path):
    """The load-bearing lock: over-cap must SEND a refusal, never unwind."""
    projects = tmp_path / "projects"
    repo = _git_repo(projects)
    h = _PlanHarness(_good_gen, projects)
    # Small enough that a real plan (tasks + prompts + criteria) cannot fit, large
    # enough that the metadata-only refusal can — the refusal must always fit.
    h._framer = MessageFramer(700)
    t = _FakeTransport()

    # It RETURNS (send succeeded) rather than raising: no unwind to the serve loop,
    # so the connection is never dropped and the gateway never sees a dead socket.
    assert h._handle_plan_request(t, "rid-oversize", {"repo": repo, "goal": "a calculator"})
    assert len(t.sent) == 1, "exactly one frame — the refusal"

    payload = h._framer.decode_plan_result(t.sent[0])
    assert payload["ok"] is False
    # Nothing is half-delivered: a refusal carries no partial plan.
    assert payload["tasks"] == []
    assert payload["criteria"] == {}
    # The operator-facing text must say the work was DONE but undeliverable, and must
    # NOT imply silence/timeouts (the exact misdirection that cost the arc).
    msg = payload["message"].lower()
    assert "too large" in msg
    assert "nothing was started" in msg
    assert "no response" not in msg


def test_the_same_plan_fits_under_a_normal_cap(tmp_path):
    """Toggle-proof (principle 12): the refusal above is the CAP, not a broken plan.

    Without this, a plan that failed for any other reason would satisfy the test above
    and the lock would prove nothing.
    """
    projects = tmp_path / "projects"
    repo = _git_repo(projects)
    h = _PlanHarness(_good_gen, projects)
    h._framer = MessageFramer(DEFAULT_MAX_MESSAGE_BYTES)
    t = _FakeTransport()

    assert h._handle_plan_request(t, "rid-ok", {"repo": repo, "goal": "a calculator"})
    payload = h._framer.decode_plan_result(t.sent[0])
    assert payload["ok"] is True
    assert payload["tasks"], "the identical goal plans fine when the cap is not the issue"
