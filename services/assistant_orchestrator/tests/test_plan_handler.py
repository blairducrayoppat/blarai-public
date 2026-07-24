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

    def __init__(self, fake_gen, projects_root, *, enabled=True, clarify=True, revise=True,
                 advanced_intake=False) -> None:
        self._framer = MessageFramer()
        self._fake_gen = fake_gen
        self._resolved_config = SimpleNamespace(
            fleet_dispatch_enabled=enabled,
            fleet_dispatch_clarify_enabled=clarify,
            fleet_dispatch_revise_enabled=revise,
            # #1031: dormant default here too — the harness must mirror production's
            # fail-closed posture, or a wiring regression would pass unnoticed.
            fleet_dispatch_advanced_intake_enabled=advanced_intake,
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
    fleet_dispatch_advanced_intake_enabled = (
        AssistantOrchestratorService.fleet_dispatch_advanced_intake_enabled
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
