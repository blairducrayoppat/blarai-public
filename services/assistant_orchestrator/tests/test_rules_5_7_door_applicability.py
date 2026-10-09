"""#1685 - RULE 5 / RULE 7 applicability to the AO tool-dispatch door and the URL door.

``DeterministicPolicyChecker`` RULE 5 (``ESCALATE_CROSS_AGENT_OWNERSHIP``) reads the
top-level ``parameters_schema["target_owner"]``; RULE 7 (``ESCALATE_LARGE_WRITE``) reads
top-level ``size_bytes`` / ``estimated_size_bytes`` / ``estimated_total_bytes`` on a
``verb == WRITE`` CAR.  The AO builds every argument-bearing CAR as
``{"args": "<json string>"}`` with ``verb=EXECUTE``, so those rules cannot see AO
arguments.  Decision (b): no AO tool has an argument those rules are meant to judge, so
the rules are NOT APPLICABLE to this door - a stated, locked non-applicability.

These tests drive the REAL ``_build_dispatch_car`` into the REAL checker.  The lock
(``test_no_tool_schema_declares_a_rule_5_or_7_argument``) fails the day a tool gains an
argument named for either rule; the toggle test proves the lock can fail.
"""

from __future__ import annotations

import copy
import json

import pytest

from services.assistant_orchestrator.src import tools
from services.assistant_orchestrator.src.entrypoint import (
    _action_identity,
    _build_dispatch_car,
)
from services.policy_agent.src.car import build_car
from services.policy_agent.src.gpu_inference import DeterministicPolicyChecker
from services.ui_gateway.src.url_adjudicator import build_url_car
from shared.schemas.car import ActionVerb, Sensitivity

_RULE_5_7_VERDICTS = {
    ("ESCALATE", "ESCALATE_CROSS_AGENT_OWNERSHIP"),
    ("ESCALATE", "ESCALATE_LARGE_WRITE"),
}
_RULE_5_7_KEYS = frozenset(
    {"target_owner", "size_bytes", "estimated_size_bytes", "estimated_total_bytes"}
)

# Normal argument shapes per real tool (every property of every schema appears).
_NORMAL_ARGS: dict[str, list[dict[str, object]]] = {
    "get_current_time": [{}],
    "get_current_date": [{}],
    "get_day_of_week": [{}],
    "calculate": [{"expression": "2*(3+4)"}],
    "generate_image": [{"prompt": "a lighthouse at dusk"}],
    "search_knowledge": [{"query": "tax receipts"}, {"query": "tax", "max_results": 8}],
    "search_reference": [{"query": "battle of hastings"}, {"query": "photosynthesis", "max_results": 8}],
    "curate_knowledge": [
        {"action": "delete", "source_ref": "https://example.com/a"},
        {"action": "mark_saved", "source_type": "file",
         "created_before": "2026-01-01", "created_after": "2025-01-01"},
    ],
    "organise_userdata": [{"pattern": "*.pdf", "destination": "receipts"}],
    "web_search": [{"query": "openvino release notes"}],
    "propose_preference": [
        {"text": "Always use metric units"},
        {"text": "Call me Blair", "type_tag": "address-form", "intent": "save"},
    ],
}


_SUSPECT_NAME_FRAGMENTS = ("owner", "size", "bytes")


def _walk_property_names(node: object):
    """Yield EVERY dict key and every ``required`` entry anywhere in a schema, recursing
    generically through all dict and list values (nested ``properties``,
    ``patternProperties``, ``items`` as dict or list, ``prefixItems``,
    ``additionalProperties``, ``anyOf``/``oneOf``/``allOf``, ``if``/``then``/``else``,
    ``not``, ``dependentSchemas``, ``$defs``). Over-inclusive on purpose: a key that
    merely looks like a rule input is a reason to look, not to skip."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield str(key)
            if key in ("required", "dependentRequired") and isinstance(value, (list, dict)):
                values = value.values() if isinstance(value, dict) else [value]
                for names in values:
                    yield from (str(n) for n in names if isinstance(n, str))
            yield from _walk_property_names(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_property_names(item)


def _rule_key_collisions(schemas: dict[str, dict[str, object]]) -> list[tuple[str, str]]:
    """(tool, property) pairs, at any depth, whose name could carry what RULE 5 / RULE 7
    judge: contains 'owner', 'size' or 'bytes' (case-insensitive, so targetOwner,
    file_size, max_bytes and exact rule keys are all caught)."""
    hits: list[tuple[str, str]] = []
    for name, spec in schemas.items():
        for prop in _walk_property_names(spec["function"]["parameters"]):  # type: ignore[index]
            if any(f in prop.lower() for f in _SUSPECT_NAME_FRAGMENTS):
                hits.append((name, prop))
    return hits


def test_normal_args_cover_every_real_tool_and_property() -> None:
    assert set(_NORMAL_ARGS) == set(tools.TOOL_SCHEMAS)
    for name, shapes in _NORMAL_ARGS.items():
        props = set(tools.TOOL_SCHEMAS[name]["function"]["parameters"]["properties"])  # type: ignore[index]
        used = {k for shape in shapes for k in shape}
        assert used == props, f"{name}: example shapes must exercise every property"


def test_no_tool_schema_declares_a_rule_5_or_7_argument() -> None:
    """Non-applicability lock: a tool argument that RULE 5/7 would judge must be projected."""
    assert _rule_key_collisions(tools.TOOL_SCHEMAS) == [], (
        "A tool now declares an argument whose name contains owner/size/bytes. Add a "
        "typed, validated, size-capped projection of that field to the top-level CAR key "
        "in _build_dispatch_car, add a drive-through test, and update the rule table in "
        "the DeterministicPolicyChecker docstring - do not leave the rule silently dead (#1685)."
    )


def test_lock_toggle_detects_nested_and_aliased_names() -> None:
    """Toggle: nested object, array items, anyOf and camelCase/alias names are all caught."""
    schemas = copy.deepcopy(tools.TOOL_SCHEMAS)
    params = schemas["web_search"]["function"]["parameters"]  # type: ignore[index]
    params["properties"]["opts"] = {
        "type": "object",
        "properties": {"targetOwner": {"type": "string"}},
    }
    params["properties"]["files"] = {
        "type": "array",
        "items": {"type": "object", "properties": {"file_size": {"type": "integer"}}},
    }
    params["properties"]["either"] = {
        "anyOf": [{"type": "object", "properties": {"MAX_BYTES": {"type": "integer"}}}]
    }
    assert {p for _, p in _rule_key_collisions(schemas)} == {
        "targetOwner", "file_size", "MAX_BYTES",
    }


@pytest.mark.parametrize(
    "form",
    [
        {"type": "array", "items": [{"type": "object", "properties": {"target_owner": {}}}]},
        {"type": "object", "patternProperties": {"^owner_.*$": {"type": "string"}}},
        {"type": "object", "additionalProperties": {"type": "object", "properties": {"size_bytes": {}}}},
        {"type": "array", "prefixItems": [{"type": "object", "properties": {"fileSize": {}}}]},
        {"if": {"properties": {"x": {}}}, "then": {"properties": {"owner_agent": {}}}},
        {"if": {"properties": {"x": {}}}, "else": {"properties": {"max_bytes": {}}}},
        {"not": {"properties": {"targetOwner": {}}}},
        {"dependentSchemas": {"a": {"properties": {"estimated_size_bytes": {}}}}},
        {"type": "object", "required": ["target_owner"]},
        {"$defs": {"d": {"properties": {"Owner": {}}}}, "type": "object"},
    ],
)
def test_lock_toggle_detects_every_nesting_form(form: dict[str, object]) -> None:
    """Toggle: a rule-shaped name planted in any JSON-schema nesting form is caught."""
    schemas = copy.deepcopy(tools.TOOL_SCHEMAS)
    schemas["web_search"]["function"]["parameters"]["properties"]["planted"] = form  # type: ignore[index]
    assert _rule_key_collisions(schemas), form


def test_lock_toggle_detects_an_injected_rule_5_7_argument() -> None:
    """Toggle test: the lock FAILS when a tool gains such an argument."""
    schemas = copy.deepcopy(tools.TOOL_SCHEMAS)
    for key in sorted(_RULE_5_7_KEYS):
        schemas["calculate"]["function"]["parameters"]["properties"][key] = {"type": "string"}  # type: ignore[index]
    assert {p for _, p in _rule_key_collisions(schemas)} == set(_RULE_5_7_KEYS)


@pytest.mark.parametrize("tool", sorted(_NORMAL_ARGS))
def test_real_builder_cars_never_reach_rule_5_or_7(tool: str) -> None:
    """Every normal call: REAL builder -> REAL checker; shape is {'args'} + EXECUTE and
    neither RULE 5 nor RULE 7 fires (no benign call is newly denied or escalated)."""
    for shape in _NORMAL_ARGS[tool]:
        args = json.dumps(shape, sort_keys=True) if shape else ""
        car = _build_dispatch_car(tool, args, "s1")
        assert set(car.parameters_schema) <= {"args"}
        assert car.verb is ActionVerb.EXECUTE
        verdict = DeterministicPolicyChecker.check(car)
        assert verdict not in _RULE_5_7_VERDICTS
        # Pins today's verdict for a benign call: nothing in rules 1-10 fires.
        assert verdict is None, f"{tool} {shape} -> {verdict}"


@pytest.mark.parametrize("tool", sorted(_NORMAL_ARGS))
def test_rule_keys_inside_args_text_stay_inert(tool: str) -> None:
    """Free text is never lifted into a trusted key: rule-keyed JSON inside ``args``
    does not trigger RULE 5/7 (the 'projection from free text' design is rejected)."""
    args = json.dumps({"query": "x", "target_owner": "coder", "size_bytes": 999_999_999})
    car = _build_dispatch_car(tool, args, "s1")
    assert set(car.parameters_schema) == {"args"}
    assert DeterministicPolicyChecker.check(car) not in _RULE_5_7_VERDICTS


def test_url_door_car_cannot_reach_rule_5_or_7() -> None:
    car = build_url_car("https://example.com/page", "ingest")
    assert set(car.parameters_schema) == {"purpose", "method"}
    assert car.verb is ActionVerb.EGRESS
    assert DeterministicPolicyChecker.check(car) not in _RULE_5_7_VERDICTS


def _top_level_car(verb: ActionVerb, params: dict[str, object]):
    return build_car(
        source_agent="assistant_orchestrator",
        destination_service="assistant_orchestrator",
        verb=verb,
        resource="tool:x",
        sensitivity=Sensitivity.INTERNAL,
        parameters_schema=params,
        session_id="s1",
    )


def test_checker_rules_still_fire_on_top_level_keys_negative_control() -> None:
    """Control: the rules are live for CARs that DO carry the typed keys (other doors),
    so the AO-door results above are about shape, not a broken checker."""
    assert DeterministicPolicyChecker.check(
        _top_level_car(ActionVerb.EXECUTE, {"target_owner": "coder"})
    ) == ("ESCALATE", "ESCALATE_CROSS_AGENT_OWNERSHIP")
    assert DeterministicPolicyChecker.check(
        _top_level_car(ActionVerb.WRITE, {"size_bytes": 200_000_000})
    ) == ("ESCALATE", "ESCALATE_LARGE_WRITE")
    # RULE 7 is WRITE-only: the AO's EXECUTE verb alone keeps it from firing.
    assert DeterministicPolicyChecker.check(
        _top_level_car(ActionVerb.EXECUTE, {"size_bytes": 200_000_000})
    ) is None
    # Same-owner is benign for RULE 5.
    assert DeterministicPolicyChecker.check(
        _top_level_car(ActionVerb.EXECUTE, {"target_owner": "assistant_orchestrator"})
    ) is None


def test_action_identity_is_untouched_by_this_decision() -> None:
    """No CAR-shape change: identity is deterministic for identical inputs and equals the
    hash of the CAR the builder produces (pinned value from main before this change)."""
    a = _action_identity("calculate", '{"expression":"1+1"}', "s1")
    assert a == _action_identity("calculate", '{"expression":"1+1"}', "s1")
    assert a == "sha256:4daa72db3669f3778a67dd9ed5e83a4b8ef77338ab9bbc6912ad2697f356a767"


def _internal_car(verb: ActionVerb):
    return build_car(
        source_agent="assistant_orchestrator",
        destination_service="assistant_orchestrator",
        verb=verb,
        resource="/internal/config/x",
        sensitivity=Sensitivity.INTERNAL,
        parameters_schema={},
        session_id="s1",
    )


def test_verb_gated_rules_and_door_verbs() -> None:
    """RULE 6 and RULE 7 need verb == WRITE; the AO door is EXECUTE for every tool
    (delete and move included) and the URL door is EGRESS, so both rules are off there."""
    for tool in sorted(tools.TOOL_SCHEMAS):
        assert _build_dispatch_car(tool, "", "s1").verb is ActionVerb.EXECUTE, tool
    assert build_url_car("https://example.com/", "ingest").verb is ActionVerb.EGRESS
    # RULE 6 fires only on WRITE (control), and not on the doors' verbs.
    assert DeterministicPolicyChecker.check(_internal_car(ActionVerb.WRITE)) == (
        "ESCALATE", "ESCALATE_INFRA_CONFIG_WRITE"
    )
    assert DeterministicPolicyChecker.check(_internal_car(ActionVerb.EXECUTE)) is None
    assert DeterministicPolicyChecker.check(_internal_car(ActionVerb.EGRESS)) is None
    # RULE 7 likewise (WRITE-only), shown in the control test above.
    assert DeterministicPolicyChecker.check(
        _top_level_car(ActionVerb.EGRESS, {"size_bytes": 200_000_000})
    ) is None
