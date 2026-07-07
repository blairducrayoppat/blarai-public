"""
Tests for the Qwen3 NATIVE JSON tool-call format migration (#718).

Covers:
  - parse_tool_call: native <tool_call>{"name": ..., "arguments": {...}}
    </tool_call> payloads — valid calls per tool, canonical-argument
    determinism, and the adversarial surface (malformed JSON, schema
    violations, unknown tools, nested/escaped content, non-object payloads,
    extra keys, first-block-only semantics).
  - Legacy NAME / NAME(ARGS) retirement locks (#718 D3): the retired forms
    fail closed to no-parse via the standard malformed-payload path.
  - execute(): typed-argument extraction from canonical JSON, bare-string
    pass-through for direct callers, each tool's own validation preserved.
  - TOOL_SCHEMAS coupling: registry / allowlist / schema SSOT lockstep.
  - render_tools_system_block + the system prompt carrying the native format.
  - tool_call_grammar_schema + the gpu_inference structured-output wiring
    (knob on/off, fail-soft on missing API).
  - pgov.check_tool_calls native-JSON detection incl. the reorder/broken-JSON
    evasion cases and the plain-prose-JSON non-false-positive.
  - GOVERNANCE REGRESSION: the real _handle_prompt_request tool loop driven
    with JSON-format emissions — Layer-3 untrusted lock, TOOL_CALL_ALLOWLIST,
    #570 PA adjudication (canonical-args wire), ESCALATE→DENY — firing
    identically to the legacy format.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from shared.ipc.protocol import MessageFramer
from services.assistant_orchestrator.src import tools
from services.assistant_orchestrator.src.tools import (
    canonical_arguments,
    execute,
    parse_tool_call,
)


def _call(name: str, arguments: dict[str, object] | None = None, **json_kwargs: Any) -> str:
    """Render a native-format tool call string."""
    payload: dict[str, object] = {"name": name}
    if arguments is not None:
        payload["arguments"] = arguments
    return f"<tool_call>{json.dumps(payload, **json_kwargs)}</tool_call>"


# ---------------------------------------------------------------------------
# parse_tool_call — native JSON format
# ---------------------------------------------------------------------------


class TestNativeJsonParse:
    """Valid native-format payloads for every registered tool."""

    def test_zero_arg_tool(self) -> None:
        assert parse_tool_call(_call("get_current_time", {})) == ("get_current_time", "")

    def test_zero_arg_tool_arguments_omitted(self) -> None:
        # Tolerant of an omitted arguments key (treated as {}).
        assert parse_tool_call(_call("get_current_date")) == ("get_current_date", "")

    def test_calculate_typed_args(self) -> None:
        result = parse_tool_call(_call("calculate", {"expression": "2*(3+4)"}))
        assert result == ("calculate", '{"expression":"2*(3+4)"}')

    def test_generate_image_typed_args(self) -> None:
        result = parse_tool_call(_call("generate_image", {"prompt": "a red bicycle"}))
        assert result == ("generate_image", '{"prompt":"a red bicycle"}')

    def test_all_registered_tools_parse(self) -> None:
        samples: dict[str, dict[str, object]] = {
            "get_current_time": {},
            "get_current_date": {},
            "get_day_of_week": {},
            "calculate": {"expression": "1+1"},
            "generate_image": {"prompt": "x"},
        }
        for name, args in samples.items():
            parsed = parse_tool_call(_call(name, args))
            assert parsed is not None and parsed[0] == name

    def test_canonical_args_deterministic_across_key_order(self) -> None:
        """The canonical string is identical regardless of emitted key order —
        the property the #570 PA adjudication wire depends on."""
        a = parse_tool_call(
            '<tool_call>{"name": "calculate", "arguments": {"expression": "1+1"}}</tool_call>'
        )
        b = parse_tool_call(
            '<tool_call>{"arguments": {"expression": "1+1"}, "name": "calculate"}</tool_call>'
        )
        assert a == b == ("calculate", '{"expression":"1+1"}')

    def test_multiline_and_spaced_json(self) -> None:
        text = (
            "<tool_call>\n{\n  \"name\": \"calculate\",\n"
            "  \"arguments\": {\n    \"expression\": \"6*7\"\n  }\n}\n</tool_call>"
        )
        assert parse_tool_call(text) == ("calculate", '{"expression":"6*7"}')

    def test_case_insensitive_tags(self) -> None:
        text = '<TOOL_CALL>{"name": "get_day_of_week", "arguments": {}}</TOOL_CALL>'
        assert parse_tool_call(text) == ("get_day_of_week", "")

    def test_embedded_in_longer_text(self) -> None:
        text = "Let me check. " + _call("get_current_time", {}) + " one moment."
        assert parse_tool_call(text) == ("get_current_time", "")

    def test_name_uppercase_lowercased(self) -> None:
        text = '<tool_call>{"name": "GET_CURRENT_TIME", "arguments": {}}</tool_call>'
        assert parse_tool_call(text) == ("get_current_time", "")

    def test_escaped_quotes_in_string_argument(self) -> None:
        result = parse_tool_call(
            '<tool_call>{"name": "generate_image", "arguments": '
            '{"prompt": "a sign saying \\"open\\""}}</tool_call>'
        )
        assert result == ("generate_image", '{"prompt":"a sign saying \\"open\\""}')

    def test_unicode_argument_preserved(self) -> None:
        result = parse_tool_call(_call("generate_image", {"prompt": "café ☕"}))
        assert result is not None
        assert json.loads(result[1]) == {"prompt": "café ☕"}

    def test_unknown_tool_with_valid_structure_is_returned(self) -> None:
        """Authorization is the allowlist/PGOV's job — the parser must surface
        an unknown tool name so those locks can fire on it (governance parity
        with the legacy parser)."""
        assert parse_tool_call(_call("smart_home_control", {})) == (
            "smart_home_control", "",
        )

    def test_unknown_tool_arguments_canonicalised_not_validated(self) -> None:
        result = parse_tool_call(_call("web_fetch", {"url": "http://x", "a": 1}))
        assert result == ("web_fetch", '{"a":1,"url":"http://x"}')


class TestNativeJsonParseAdversarial:
    """Malformed / hostile payloads fail closed to None (no tool call)."""

    def test_malformed_json_returns_none(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            assert parse_tool_call('<tool_call>{"name": "calculate", </tool_call>') is None
        assert "fingerprint=" in caplog.text

    def test_truncated_json_returns_none(self) -> None:
        assert parse_tool_call('<tool_call>{"name"</tool_call>') is None

    def test_non_object_json_returns_none(self) -> None:
        # A JSON object payload is required; scalars/arrays that start with
        # "{" cannot exist, so drive the dict-check via a nested trick.
        assert parse_tool_call("<tool_call>{}</tool_call>") is None  # no name

    def test_extra_top_level_keys_rejected(self) -> None:
        text = (
            '<tool_call>{"name": "calculate", "arguments": {"expression": "1"}, '
            '"id": "x"}</tool_call>'
        )
        assert parse_tool_call(text) is None

    def test_name_not_a_string_rejected(self) -> None:
        assert parse_tool_call('<tool_call>{"name": 42, "arguments": {}}</tool_call>') is None

    def test_name_not_identifier_shaped_rejected(self) -> None:
        text = '<tool_call>{"name": "evil tool; rm -rf", "arguments": {}}</tool_call>'
        assert parse_tool_call(text) is None

    def test_arguments_not_an_object_rejected(self) -> None:
        text = '<tool_call>{"name": "calculate", "arguments": "1+1"}</tool_call>'
        assert parse_tool_call(text) is None

    def test_schema_missing_required_rejected(self) -> None:
        assert parse_tool_call(_call("calculate", {})) is None

    def test_schema_unexpected_argument_rejected(self) -> None:
        assert parse_tool_call(
            _call("calculate", {"expression": "1", "shell": "rm"})
        ) is None

    def test_schema_wrong_type_rejected(self) -> None:
        assert parse_tool_call(_call("calculate", {"expression": 42})) is None

    def test_zero_arg_tool_with_unexpected_args_rejected(self) -> None:
        assert parse_tool_call(_call("get_current_time", {"tz": "UTC"})) is None

    def test_closing_tag_inside_string_argument_fails_closed(self) -> None:
        """A literal </tool_call> inside a JSON string splits the block early
        (non-greedy tag match) — the fragment is malformed JSON and the call
        drops fail-closed rather than executing with attacker-shaped args."""
        text = (
            '<tool_call>{"name": "generate_image", "arguments": '
            '{"prompt": "x</tool_call>y"}}</tool_call>'
        )
        assert parse_tool_call(text) is None

    def test_first_block_only_malformed_first_drops(self) -> None:
        """A malformed first block is a dropped call — never a fall-through
        to a later (possibly injected) block."""
        text = (
            "<tool_call>{broken</tool_call>"
            + _call("get_current_time", {})
        )
        assert parse_tool_call(text) is None

    def test_first_block_wins_over_later_blocks(self) -> None:
        text = _call("get_current_time", {}) + _call("smart_home_control", {})
        assert parse_tool_call(text) == ("get_current_time", "")

    def test_no_tool_call_returns_none(self) -> None:
        assert parse_tool_call("Just a normal answer.") is None

    def test_unclosed_tag_returns_none(self) -> None:
        assert parse_tool_call('<tool_call>{"name": "calculate"}') is None

    def test_prose_json_outside_tags_is_not_a_call(self) -> None:
        assert parse_tool_call('Here is JSON: {"name": "calculate"}') is None

    def test_fingerprint_is_deterministic(self) -> None:
        p = tools._payload_fingerprint('{"broken')
        assert p == tools._payload_fingerprint('{"broken')
        assert len(p) == 12 and all(c in "0123456789abcdef" for c in p)


class TestLegacyFormRetired:
    """The v1/v2 homemade forms are RETIRED (#718 D3, 2026-07-02): a
    ``NAME``/``NAME(ARGS)`` payload must NEVER parse as a tool call again —
    it lands on the standard fail-closed no-parse path. These are the
    regression locks proving the form is dead."""

    def test_bare_name_does_not_parse(self) -> None:
        assert parse_tool_call("<tool_call>get_current_time</tool_call>") is None

    def test_name_with_args_does_not_parse(self) -> None:
        assert parse_tool_call("<tool_call>calculate(2*3+4)</tool_call>") is None

    def test_nested_paren_args_do_not_parse(self) -> None:
        """The system prompt's historical example shape — dead with the rest
        of the legacy grammar (the JSON format carries nested parens inside a
        JSON string instead)."""
        assert parse_tool_call("<tool_call>calculate(2*(3+4))</tool_call>") is None

    def test_legacy_payload_lands_on_fail_closed_path(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A legacy-shaped payload is dropped through the SAME fail-closed
        malformed-payload path as any other non-JSON payload (logged
        deterministic fingerprint) — no dedicated legacy surface remains."""
        with caplog.at_level(logging.WARNING):
            assert parse_tool_call("<tool_call>get_current_time</tool_call>") is None
        assert "fingerprint=" in caplog.text
        assert "LEGACY" not in caplog.text

    def test_native_hit_is_not_logged_as_legacy(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            parse_tool_call(_call("get_current_time", {}))
        assert "LEGACY" not in caplog.text

    def test_garbage_payload_returns_none(self) -> None:
        assert parse_tool_call("<tool_call>not a tool!!!</tool_call>") is None


class TestCanonicalArguments:
    def test_empty_is_empty_string(self) -> None:
        assert canonical_arguments({}) == ""

    def test_compact_and_key_sorted(self) -> None:
        assert canonical_arguments({"b": 1, "a": "x"}) == '{"a":"x","b":1}'

    def test_unicode_not_escaped(self) -> None:
        assert canonical_arguments({"p": "café"}) == '{"p":"café"}'


# ---------------------------------------------------------------------------
# execute — typed arguments
# ---------------------------------------------------------------------------


class TestExecuteTypedArguments:
    def test_calculate_from_canonical_json(self) -> None:
        assert execute("calculate", '{"expression":"2*(3+4)"}') == "14"

    def test_calculate_bare_string_still_works(self) -> None:
        # Direct execute() callers may pass a bare expression string — this
        # is the execute() contract, independent of the retired parse form.
        assert execute("calculate", "2*3+4") == "10"

    def test_zero_arg_tool_ignores_canonical_json(self) -> None:
        # Even if a stray args string reaches a zero-param tool, it executes.
        result = execute("get_day_of_week", '{"whatever":1}')
        assert result in (
            "Monday", "Tuesday", "Wednesday", "Thursday",
            "Friday", "Saturday", "Sunday",
        )

    def test_generate_image_from_canonical_json_returns_string(self) -> None:
        # Dormant-safe: either the unavailable notice or the /imagine
        # directive — never an exception (the _generate_image contract).
        result = execute("generate_image", '{"prompt":"a red bicycle"}')
        assert isinstance(result, str) and result

    def test_calculate_own_validation_still_fires(self) -> None:
        # The tool's own AST validation is unchanged behind the typed path.
        result = execute("calculate", '{"expression":"__import__(\'os\')"}')
        assert result.startswith("calculate:")

    def test_round_trip_parse_then_execute(self) -> None:
        parsed = parse_tool_call(_call("calculate", {"expression": "10/4"}))
        assert parsed is not None
        assert execute(*parsed) == "2.5"

    def test_unknown_tool_raises_key_error(self) -> None:
        with pytest.raises(KeyError, match="Unknown tool"):
            execute("smart_home_control", "{}")

    def test_non_json_garbage_passes_through_to_tool_validation(self) -> None:
        result = execute("calculate", "{not json")
        assert result.startswith("calculate:")


# ---------------------------------------------------------------------------
# Schema SSOT coupling + prompt rendering + grammar schema
# ---------------------------------------------------------------------------


class TestSchemaCoupling:
    def test_schemas_mirror_registry_exactly(self) -> None:
        assert set(tools.TOOL_SCHEMAS) == set(tools._REGISTRY)

    def test_schemas_mirror_allowlist_exactly(self) -> None:
        from services.assistant_orchestrator.src.pgov import TOOL_CALL_ALLOWLIST

        assert set(tools.TOOL_SCHEMAS) == set(TOOL_CALL_ALLOWLIST)

    def test_every_schema_names_itself(self) -> None:
        for name, spec in tools.TOOL_SCHEMAS.items():
            function = spec["function"]
            assert isinstance(function, dict)
            assert function["name"] == name
            params = function["parameters"]
            assert isinstance(params, dict)
            assert params.get("additionalProperties") is False

    def test_primary_string_params_declared_in_schema(self) -> None:
        for name, param in tools._PRIMARY_STRING_PARAM.items():
            schema = tools.arguments_schema(name)
            assert schema is not None
            properties = schema["properties"]
            assert isinstance(properties, dict) and param in properties


class TestSystemPromptRendering:
    def test_tools_block_carries_every_tool(self) -> None:
        block = tools.render_tools_system_block()
        assert "<tools>" in block and "</tools>" in block
        for name in tools.TOOL_SCHEMAS:
            assert name in block

    def test_tools_block_teaches_native_format(self) -> None:
        block = tools.render_tools_system_block()
        assert '<tool_call>{"name": <function-name>' in block

    def test_system_prompt_embeds_rendered_block(self) -> None:
        from services.assistant_orchestrator.src.gpu_inference import (
            _DEFAULT_SYSTEM_PROMPT,
        )

        assert tools.render_tools_system_block() in _DEFAULT_SYSTEM_PROMPT
        # The legacy homemade examples must be gone from the prompt.
        assert "<tool_call>calculate(" not in _DEFAULT_SYSTEM_PROMPT
        assert "<tool_call>get_current_time</tool_call>" not in _DEFAULT_SYSTEM_PROMPT
        # ADR-012 §2.4 thinking directive untouched.
        assert _DEFAULT_SYSTEM_PROMPT.endswith("/no_think")


class TestGrammarSchema:
    def test_union_of_every_tool(self) -> None:
        schema = tools.tool_call_grammar_schema()
        branches = schema["anyOf"]
        assert isinstance(branches, list)
        assert len(branches) == len(tools.TOOL_SCHEMAS)
        pinned = set()
        for branch in branches:
            assert isinstance(branch, dict)
            assert branch["required"] == ["name", "arguments"]
            assert branch["additionalProperties"] is False
            properties = branch["properties"]
            assert isinstance(properties, dict)
            name_schema = properties["name"]
            assert isinstance(name_schema, dict)
            enum = name_schema["enum"]
            assert isinstance(enum, list) and len(enum) == 1
            pinned.add(enum[0])
        assert pinned == set(tools.TOOL_SCHEMAS)

    def test_grammar_schema_is_json_serialisable(self) -> None:
        json.dumps(tools.tool_call_grammar_schema())


# ---------------------------------------------------------------------------
# gpu_inference structured-output wiring
# ---------------------------------------------------------------------------


class TestStructuredOutputWiring:
    def test_generation_config_knob_defaults_on(self) -> None:
        from services.assistant_orchestrator.src.gpu_inference import GenerationConfig

        assert GenerationConfig().tool_call_grammar is True

    def test_builder_matches_installed_api(self) -> None:
        """With the installed GenAI exposing the structured-output API the
        builder returns a config; without it, fail-soft None. Deterministic
        either way — no skip."""
        from services.assistant_orchestrator.src import gpu_inference as gi

        built = gi._build_tool_call_structured_output()
        api_present = gi._OV_GENAI_AVAILABLE and all(
            hasattr(gi.ov_genai, n)
            for n in ("StructuredOutputConfig", "StructuralTagsConfig", "StructuralTagItem")
        )
        if api_present:
            assert built is not None
        else:
            assert built is None

    def test_missing_api_fail_softs_to_none(self) -> None:
        from services.assistant_orchestrator.src import gpu_inference as gi

        class _BareGenai:
            pass  # no StructuredOutputConfig et al.

        with patch.object(gi, "ov_genai", _BareGenai()), \
                patch.object(gi, "_OV_GENAI_AVAILABLE", True), \
                patch.object(gi, "_tool_grammar_unavailable_logged", False):
            assert gi._build_tool_call_structured_output() is None

    def test_build_generation_config_sets_grammar_when_enabled(self) -> None:
        from services.assistant_orchestrator.src import gpu_inference as gi

        engine = gi.OrchestratorGPUInference.__new__(gi.OrchestratorGPUInference)
        engine._speculative_decoding_enabled = False
        sentinel = object()
        with patch.object(gi, "ov_genai", MagicMock()), \
                patch.object(
                    gi, "_build_tool_call_structured_output", return_value=sentinel
                ):
            gen_config = engine._build_generation_config(
                max_new_tokens=64, config=gi.GenerationConfig(tool_call_grammar=True)
            )
            assert gen_config.structured_output_config is sentinel

    def test_build_generation_config_skips_grammar_when_disabled(self) -> None:
        from services.assistant_orchestrator.src import gpu_inference as gi

        engine = gi.OrchestratorGPUInference.__new__(gi.OrchestratorGPUInference)
        engine._speculative_decoding_enabled = False
        with patch.object(gi, "ov_genai", MagicMock()), \
                patch.object(gi, "_build_tool_call_structured_output") as mock_build:
            engine._build_generation_config(
                max_new_tokens=64, config=gi.GenerationConfig(tool_call_grammar=False)
            )
            mock_build.assert_not_called()

    def test_build_generation_config_none_grammar_leaves_config_unset(self) -> None:
        from services.assistant_orchestrator.src import gpu_inference as gi

        engine = gi.OrchestratorGPUInference.__new__(gi.OrchestratorGPUInference)
        engine._speculative_decoding_enabled = False
        mock_genai = MagicMock()
        # A fresh GenerationConfig whose structured_output_config starts None.
        mock_genai.GenerationConfig.return_value = SimpleNamespace(
            structured_output_config=None
        )
        with patch.object(gi, "ov_genai", mock_genai), \
                patch.object(
                    gi, "_build_tool_call_structured_output", return_value=None
                ):
            gen_config = engine._build_generation_config(
                max_new_tokens=64, config=gi.GenerationConfig(tool_call_grammar=True)
            )
            assert gen_config.structured_output_config is None


# ---------------------------------------------------------------------------
# pgov — native-JSON detection (Stage 4 governance parity)
# ---------------------------------------------------------------------------


class TestPgovNativeJsonDetection:
    def test_unknown_tool_in_native_form_is_flagged(self) -> None:
        from services.assistant_orchestrator.src.pgov import check_tool_calls

        text = '<tool_call>{"name": "smart_home_control", "arguments": {}}</tool_call>'
        assert check_tool_calls(text) == ["smart_home_control"]

    def test_allowlisted_tool_in_native_form_passes(self) -> None:
        from services.assistant_orchestrator.src.pgov import check_tool_calls

        assert check_tool_calls(_call("get_current_time", {})) == []

    def test_key_reorder_evasion_is_flagged(self) -> None:
        from services.assistant_orchestrator.src.pgov import check_tool_calls

        text = (
            '<tool_call>{"arguments": {"name": "get_current_time"}, '
            '"name": "exfiltrate"}</tool_call>'
        )
        assert "exfiltrate" in check_tool_calls(text)

    def test_broken_json_evasion_is_flagged(self) -> None:
        """Malforming the JSON is not an evasion — the fallback reference scan
        still surfaces the name (fail-closed detection)."""
        from services.assistant_orchestrator.src.pgov import check_tool_calls

        text = '<tool_call>{"name": "exfiltrate", broken</tool_call>'
        assert "exfiltrate" in check_tool_calls(text)

    def test_prose_json_never_false_positives(self) -> None:
        from services.assistant_orchestrator.src.pgov import check_tool_calls

        assert check_tool_calls('The record is {"name": "John", "age": 4}.') == []

    def test_legacy_form_detection_unchanged(self) -> None:
        from services.assistant_orchestrator.src.pgov import check_tool_calls

        assert check_tool_calls("<tool_call>evil_tool</tool_call>") == ["evil_tool"]
        assert check_tool_calls("<tool_call>get_current_time</tool_call>") == []

    def test_validate_output_flags_native_unknown_tool(self) -> None:
        """End-to-end Stage 4: the PGOV validator marks a native-format
        unknown-tool emission as a tool_call_violation."""
        from services.assistant_orchestrator.src.pgov import validate_output

        result = validate_output(
            generated_text=_call("smart_home_control", {}),
            token_count=10,
            max_tokens=64,
            retrieved_chunks=[],
        )
        assert result.tool_call_violation is True
        assert not result.approved


# ---------------------------------------------------------------------------
# GOVERNANCE REGRESSION — the real tool loop with JSON-format emissions
# ---------------------------------------------------------------------------
# Mirrors the TestToolCallLoop harness in test_tools.py: the same locks must
# fire on the same conditions when the model emits the NATIVE format.


class _FakeTransport:
    def __init__(self, inbound: bytes | None) -> None:
        self._inbound = inbound
        self.sent: list[bytes] = []

    def receive(self) -> bytes | None:
        return self._inbound

    def send(self, data: bytes) -> bool:
        self.sent.append(data)
        return True


def _make_resolved_config() -> Any:
    from shared.ipc.vsock import VsockAddress, VsockConfig
    from services.assistant_orchestrator.src.entrypoint import (
        AssistantOrchestratorEntrypointConfig,
    )

    return AssistantOrchestratorEntrypointConfig(
        model_dir=Path("models"),
        manifest_path=None,
        device="GPU",
        priority=1,
        draft_model_dir=None,
        speculative_decoding_enabled=False,
        max_new_tokens=64,
        generation_temperature=0.0,
        generation_top_k=50,
        generation_top_p=0.9,
        generation_repetition_penalty=1.1,
        generation_do_sample=False,
        response_depth_mode="standard",
        dev_mode=True,
        jwt_ca_cert_path=None,
        vsock_config=VsockConfig(address=VsockAddress(cid=0, port=0)),
        pgov_cosine_threshold=0.85,
        deployment_mode="host",  # type: ignore[arg-type]
    )


def _make_service() -> Any:
    from services.assistant_orchestrator.src.context_manager import ContextManager
    from services.assistant_orchestrator.src.entrypoint import (
        AssistantOrchestratorService,
    )

    service = AssistantOrchestratorService("dummy.toml")
    service._resolved_config = _make_resolved_config()
    service._context_manager = ContextManager()
    return service


def _seed_untrusted(service: Any, session_id: str,
                    text: str = "Pasted from an external web page.") -> None:
    from services.assistant_orchestrator.src.context_manager import Provenance

    if session_id not in service._context_manager.active_sessions:
        service._context_manager.create_session(session_id)
    service._context_manager.add_grounded_context(
        session_id, [text], provenance=Provenance.UNTRUSTED_EXTERNAL
    )


def _pgov_approved(generated_text: str, **_kwargs: Any) -> SimpleNamespace:
    return SimpleNamespace(approved=True, sanitized_text=generated_text)


class TestGovernanceRegressionJsonFormat:
    """Layer-3 / allowlist / #570 adjudication / ESCALATE fire identically for
    native-JSON tool calls."""

    @patch("services.assistant_orchestrator.src.entrypoint.validate_output")
    def test_json_tool_call_loop_two_iterations(
        self, mock_validate_output: MagicMock
    ) -> None:
        service = _make_service()
        service._inference = MagicMock()
        framer = MessageFramer()
        mock_validate_output.side_effect = _pgov_approved

        captured_contexts: list[str] = []
        responses = [
            SimpleNamespace(text=_call("get_current_time", {}), token_count=5, error=None),
            SimpleNamespace(text="It is 14:32.", token_count=6, error=None),
        ]

        def _generate(context_arg: str, **_kwargs: Any) -> SimpleNamespace:
            captured_contexts.append(context_arg)
            return responses.pop(0)

        service._inference.generate_text.side_effect = _generate
        service._handle_connection(_FakeTransport(framer.encode_prompt_request(
            session_id="json-loop", prompt="What time is it?", request_id="r1",
        )))

        assert service._inference.generate_text.call_count == 2
        assert "get_current_time" in captured_contexts[1]
        assert "Result:" in captured_contexts[1]

    @patch("services.assistant_orchestrator.src.entrypoint.validate_output")
    def test_layer3_lock_fires_for_json_call_under_untrusted_content(
        self, mock_validate_output: MagicMock
    ) -> None:
        """ADR-023 action-lock parity: a non-SAFE tool called in the NATIVE
        format is refused under untrusted content, exactly as the legacy form."""
        service = _make_service()
        service._inference = MagicMock()
        framer = MessageFramer()
        mock_validate_output.side_effect = _pgov_approved
        service._inference.generate_text.return_value = SimpleNamespace(
            text=_call("get_current_time", {}), token_count=5, error=None
        )
        _seed_untrusted(service, "json-untrusted")

        with patch.dict(
            tools._TOOL_RISK_TIER, {"get_current_time": tools.RiskTier.GUARDED}
        ):
            service._handle_connection(_FakeTransport(framer.encode_prompt_request(
                session_id="json-untrusted", prompt="Say the time.",
                request_id="r-l3",
            )))

        # Locked: exactly 1 generate, tool never executed.
        assert service._inference.generate_text.call_count == 1

    @patch("services.assistant_orchestrator.src.entrypoint.validate_output")
    def test_layer3_help_message_replaces_json_tool_call_text(
        self, mock_validate_output: MagicMock
    ) -> None:
        # ADR-023 Am.4: the three current GUARDED tools are all consent-exempt now
        # (search_knowledge/generate_image lock-exempt, web_search egress-gated), so
        # the Layer-3 help path is exercised with a DANGEROUS/unknown tool, which
        # still locks under untrusted content (the fail-closed backstop).
        service = _make_service()
        service._inference = MagicMock()
        framer = MessageFramer()
        mock_validate_output.side_effect = _pgov_approved
        service._inference.generate_text.return_value = SimpleNamespace(
            text=_call("send_email", {"to": "a@b.c"}), token_count=5, error=None
        )
        _seed_untrusted(service, "json-l3-msg")
        transport = _FakeTransport(framer.encode_prompt_request(
            session_id="json-l3-msg", prompt="Email it.", request_id="r-l3m",
        ))
        service._handle_connection(transport)

        assert service._inference.generate_text.call_count == 1
        joined = b"".join(transport.sent).decode("utf-8", errors="replace")
        assert "/trust" in joined and "send_email" in joined
        assert '"name"' not in joined  # the raw tool-call JSON never surfaces

    @patch("services.assistant_orchestrator.src.entrypoint.validate_output")
    def test_allowlist_breaks_loop_for_unknown_json_tool(
        self, mock_validate_output: MagicMock
    ) -> None:
        """An unknown tool in native format reaches the TOOL_CALL_ALLOWLIST
        check (the parser surfaces it) and breaks the loop unexecuted."""
        service = _make_service()
        service._inference = MagicMock()
        framer = MessageFramer()
        mock_validate_output.side_effect = _pgov_approved
        service._inference.generate_text.return_value = SimpleNamespace(
            text=_call("smart_home_control", {}), token_count=5, error=None
        )
        service._handle_connection(_FakeTransport(framer.encode_prompt_request(
            session_id="json-allowlist", prompt="Turn on the lights.",
            request_id="r-al",
        )))
        assert service._inference.generate_text.call_count == 1

    @patch("services.assistant_orchestrator.src.entrypoint._adjudicate_tool_dispatch")
    @patch("services.assistant_orchestrator.src.entrypoint.validate_output")
    def test_pa_adjudication_receives_canonical_args(
        self, mock_validate_output: MagicMock, mock_adjudicate: MagicMock
    ) -> None:
        """#570 wire contract: the PA adjudicator sees the CANONICAL compact
        key-sorted JSON args string, independent of the emitted key order."""
        service = _make_service()
        service._inference = MagicMock()
        framer = MessageFramer()
        mock_validate_output.side_effect = _pgov_approved
        mock_adjudicate.return_value = None  # PA allows
        responses = [
            SimpleNamespace(
                text='<tool_call>{"arguments": {"expression": "1+1"}, '
                     '"name": "calculate"}</tool_call>',
                token_count=5, error=None,
            ),
            SimpleNamespace(text="2.", token_count=2, error=None),
        ]
        service._inference.generate_text.side_effect = (
            lambda *_a, **_k: responses.pop(0)
        )
        service._handle_connection(_FakeTransport(framer.encode_prompt_request(
            session_id="json-pa-wire", prompt="1+1?", request_id="r-wire",
        )))
        mock_adjudicate.assert_called_once_with(
            "calculate", '{"expression":"1+1"}', "json-pa-wire"
        )
        assert service._inference.generate_text.call_count == 2

    @patch("services.assistant_orchestrator.src.entrypoint._adjudicate_tool_dispatch")
    @patch("services.assistant_orchestrator.src.entrypoint.validate_output")
    def test_pa_deny_refuses_json_tool_call(
        self, mock_validate_output: MagicMock, mock_adjudicate: MagicMock
    ) -> None:
        service = _make_service()
        service._inference = MagicMock()
        framer = MessageFramer()
        mock_validate_output.side_effect = _pgov_approved
        mock_adjudicate.return_value = ("DENY", "DENY_EXTERNAL_NETWORK")
        service._inference.generate_text.return_value = SimpleNamespace(
            text=_call("calculate", {"expression": "1"}), token_count=5, error=None
        )
        service._handle_connection(_FakeTransport(framer.encode_prompt_request(
            session_id="json-pa-deny", prompt="calc", request_id="r-deny",
        )))
        assert service._inference.generate_text.call_count == 1
        mock_adjudicate.assert_called_once()

    @patch("services.assistant_orchestrator.src.entrypoint._adjudicate_tool_dispatch")
    @patch("services.assistant_orchestrator.src.entrypoint.validate_output")
    def test_escalate_without_verifier_fail_closes_for_json_call(
        self, mock_validate_output: MagicMock, mock_adjudicate: MagicMock
    ) -> None:
        """#639 dormant posture: ESCALATE with no operator verifier registered
        collapses to DENY for a native-format call (fail-closed)."""
        from shared.security import escalation_consent as ec

        ec.clear_verifier()
        try:
            service = _make_service()
            service._inference = MagicMock()
            framer = MessageFramer()
            mock_validate_output.side_effect = _pgov_approved
            mock_adjudicate.return_value = ("ESCALATE", "ESCALATE_CRYPTO_MATERIAL")
            service._inference.generate_text.return_value = SimpleNamespace(
                text=_call("get_current_time", {}), token_count=5, error=None
            )
            service._handle_connection(_FakeTransport(framer.encode_prompt_request(
                session_id="json-escalate", prompt="time?", request_id="r-esc",
            )))
            assert service._inference.generate_text.call_count == 1
        finally:
            ec.clear_verifier()

    @patch("services.assistant_orchestrator.src.entrypoint.validate_output")
    def test_malformed_json_call_is_no_tool_call_single_iteration(
        self, mock_validate_output: MagicMock
    ) -> None:
        """A malformed native emission fail-closes to 'no tool call' — one
        generation, nothing executed, PGOV sees the raw text downstream."""
        service = _make_service()
        service._inference = MagicMock()
        framer = MessageFramer()
        mock_validate_output.side_effect = _pgov_approved
        service._inference.generate_text.return_value = SimpleNamespace(
            text='<tool_call>{"name": "calculate", "arguments": {broken</tool_call>',
            token_count=5, error=None,
        )
        service._handle_connection(_FakeTransport(framer.encode_prompt_request(
            session_id="json-malformed", prompt="calc", request_id="r-mal",
        )))
        assert service._inference.generate_text.call_count == 1

    def test_risk_tier_fail_closed_unchanged(self) -> None:
        """An undeclared tool is DANGEROUS — the fail-closed backstop the JSON
        migration must not loosen."""
        assert tools.risk_tier("brand_new_tool") is tools.RiskTier.DANGEROUS
