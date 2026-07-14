"""Shared config-validation suite — behavior + drift locks (Vikunja #809 / AUDIT-10).

Two independent locks guard the DRY extraction of the hand-rolled config-field
validators out of the two service entrypoints into ``shared/config_validation.py``:

  1. **Byte-identical error emission per service per failure shape.** The five
     shared helpers raise :class:`ConfigResolutionError` with the EXACT ``code``
     they are handed (service-prefix-agnostic — the caller owns the prefix) and
     an EXACT, literal message for every failure shape. The emission tests are
     parametrized across BOTH live prefixes (``PA_CFG_*`` and ``AO_CFG_*``) to
     prove the single shared implementation preserves each service's distinct
     contract codes — the load-bearing constraint of the extraction.

  2. **Drift.** An AST check that both entrypoints IMPORT the shared suite and
     that neither re-introduces a local ``_require_*`` definition — so the
     duplicated suite cannot silently creep back.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from shared import config_validation
from shared.runtime_config import ConfigResolutionError

REPO_ROOT = Path(__file__).resolve().parents[2]
PA_ENTRYPOINT = REPO_ROOT / "services" / "policy_agent" / "src" / "entrypoint.py"
AO_ENTRYPOINT = REPO_ROOT / "services" / "assistant_orchestrator" / "src" / "entrypoint.py"

# The five helpers of the extracted suite. A local ``def`` of any of these in an
# entrypoint is exactly the DRY regression this ticket removed.
SUITE_NAMES = frozenset(
    {
        "_require_section_dict",
        "_require_non_empty_str",
        "_require_bool",
        "_require_int_range",
        "_require_float_range",
    }
)

# Both service error-code prefixes the live callers use. Parametrizing the
# emission tests across these proves each service keeps its EXACT codes through
# one shared implementation.
PREFIXES = ["PA_CFG", "AO_CFG"]


# ---------------------------------------------------------------------------
# 1. Byte-identical error emission — per helper, per failure shape, per prefix.
# ---------------------------------------------------------------------------
class TestRequireSectionDict:
    @pytest.mark.parametrize("prefix", PREFIXES)
    def test_missing_key_raises_exact(self, prefix: str) -> None:
        code = f"{prefix}_RUNTIME_SECTION_MISSING"
        with pytest.raises(ConfigResolutionError) as exc:
            config_validation.require_section_dict({}, "runtime", code=code)
        assert exc.value.code == code
        assert exc.value.message == "Missing or invalid section [runtime]."

    @pytest.mark.parametrize("prefix", PREFIXES)
    def test_non_dict_value_raises_exact(self, prefix: str) -> None:
        code = f"{prefix}_RUNTIME_SECTION_MISSING"
        with pytest.raises(ConfigResolutionError) as exc:
            config_validation.require_section_dict({"runtime": "nope"}, "runtime", code=code)
        assert exc.value.code == code
        assert exc.value.message == "Missing or invalid section [runtime]."

    def test_valid_returns_same_section(self) -> None:
        section = {"mode": "host"}
        assert (
            config_validation.require_section_dict({"runtime": section}, "runtime", code="X")
            is section
        )


class TestRequireNonEmptyStr:
    @pytest.mark.parametrize("prefix", PREFIXES)
    @pytest.mark.parametrize("value", [None, "", "   ", 42, {"a": 1}])
    def test_missing_or_blank_or_mistyped_raises_exact(self, prefix: str, value: object) -> None:
        code = f"{prefix}_DEVICE_MISSING"
        with pytest.raises(ConfigResolutionError) as exc:
            config_validation.require_non_empty_str({"device": value}, "device", code=code)
        assert exc.value.code == code
        assert exc.value.message == "Missing or invalid 'device' value."

    def test_valid_returns_stripped(self) -> None:
        assert (
            config_validation.require_non_empty_str({"device": "  GPU  "}, "device", code="X")
            == "GPU"
        )


class TestRequireBool:
    @pytest.mark.parametrize("prefix", PREFIXES)
    @pytest.mark.parametrize("value", [None, "true", 1, 0, "false"])
    def test_non_bool_raises_exact(self, prefix: str, value: object) -> None:
        code = f"{prefix}_DEV_MODE_INVALID"
        with pytest.raises(ConfigResolutionError) as exc:
            config_validation.require_bool({"dev_mode": value}, "dev_mode", code=code)
        assert exc.value.code == code
        assert exc.value.message == "'dev_mode' must be a boolean."

    @pytest.mark.parametrize("value", [True, False])
    def test_valid_returns_bool(self, value: bool) -> None:
        assert config_validation.require_bool({"dev_mode": value}, "dev_mode", code="X") is value


class TestRequireIntRange:
    @pytest.mark.parametrize("prefix", PREFIXES)
    @pytest.mark.parametrize("value", [None, "5", 3.5, [1]])
    def test_non_int_raises_exact(self, prefix: str, value: object) -> None:
        code = f"{prefix}_VSOCK_PORT_INVALID"
        with pytest.raises(ConfigResolutionError) as exc:
            config_validation.require_int_range(
                {"vsock_port": value}, "vsock_port", minimum=1, maximum=65535, code=code
            )
        assert exc.value.code == code
        assert exc.value.message == "'vsock_port' must be an integer."

    @pytest.mark.parametrize("prefix", PREFIXES)
    @pytest.mark.parametrize("value", [0, 65536, -1])
    def test_out_of_range_raises_exact(self, prefix: str, value: int) -> None:
        code = f"{prefix}_VSOCK_PORT_INVALID"
        with pytest.raises(ConfigResolutionError) as exc:
            config_validation.require_int_range(
                {"vsock_port": value}, "vsock_port", minimum=1, maximum=65535, code=code
            )
        assert exc.value.code == code
        assert exc.value.message == f"'vsock_port' out of range: {value}. Expected 1..65535."

    def test_valid_returns_int(self) -> None:
        assert (
            config_validation.require_int_range(
                {"vsock_port": 5001}, "vsock_port", minimum=1, maximum=65535, code="X"
            )
            == 5001
        )


class TestRequireFloatRange:
    @pytest.mark.parametrize("prefix", PREFIXES)
    @pytest.mark.parametrize("value", [None, "0.5", [1.0], {"a": 1}])
    def test_non_number_raises_exact(self, prefix: str, value: object) -> None:
        code = f"{prefix}_TEMPERATURE_INVALID"
        with pytest.raises(ConfigResolutionError) as exc:
            config_validation.require_float_range(
                {"temperature": value}, "temperature", minimum=0.0, maximum=2.0, code=code
            )
        assert exc.value.code == code
        assert exc.value.message == "'temperature' must be a number."

    @pytest.mark.parametrize("prefix", PREFIXES)
    @pytest.mark.parametrize("value", [-0.1, 2.5])
    def test_out_of_range_raises_exact(self, prefix: str, value: float) -> None:
        code = f"{prefix}_TEMPERATURE_INVALID"
        with pytest.raises(ConfigResolutionError) as exc:
            config_validation.require_float_range(
                {"temperature": value}, "temperature", minimum=0.0, maximum=2.0, code=code
            )
        assert exc.value.code == code
        parsed = float(value)
        assert exc.value.message == f"'temperature' out of range: {parsed}. Expected 0.0..2.0."

    def test_valid_returns_float(self) -> None:
        result = config_validation.require_float_range(
            {"temperature": 1}, "temperature", minimum=0.0, maximum=2.0, code="X"
        )
        assert result == 1.0
        assert isinstance(result, float)


class TestCrossPrefixByteIdentical:
    """The single shared function, same input, only the code differs between
    services — the message and raise type are byte-identical; only the
    caller-owned code carries the service prefix."""

    def test_only_code_differs_across_services(self) -> None:
        section = {"vsock_port": 0}
        with pytest.raises(ConfigResolutionError) as pa_exc:
            config_validation.require_int_range(
                section, "vsock_port", minimum=1, maximum=65535, code="PA_CFG_VSOCK_PORT_INVALID"
            )
        with pytest.raises(ConfigResolutionError) as ao_exc:
            config_validation.require_int_range(
                section, "vsock_port", minimum=1, maximum=65535, code="AO_CFG_VSOCK_PORT_INVALID"
            )
        # Same failure shape → identical message + type; only the code prefix differs.
        assert pa_exc.value.message == ao_exc.value.message
        assert type(pa_exc.value) is type(ao_exc.value) is ConfigResolutionError
        assert pa_exc.value.code == "PA_CFG_VSOCK_PORT_INVALID"
        assert ao_exc.value.code == "AO_CFG_VSOCK_PORT_INVALID"


# ---------------------------------------------------------------------------
# 2. Drift lock — the extracted suite must not re-duplicate into the entrypoints.
# ---------------------------------------------------------------------------
def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imports_shared_config_validation(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            # from shared import config_validation
            if node.module == "shared" and any(a.name == "config_validation" for a in node.names):
                return True
            # from shared.config_validation import require_...
            if node.module == "shared.config_validation":
                return True
    return False


def _local_require_defs(tree: ast.Module) -> set[str]:
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in SUITE_NAMES
    }


@pytest.mark.parametrize(
    "entrypoint",
    [PA_ENTRYPOINT, AO_ENTRYPOINT],
    ids=["policy_agent", "assistant_orchestrator"],
)
def test_entrypoint_imports_shared_suite(entrypoint: Path) -> None:
    assert entrypoint.exists(), f"entrypoint not found: {entrypoint}"
    assert _imports_shared_config_validation(_parse(entrypoint)), (
        f"{entrypoint.name} must import the shared config_validation suite "
        "(Vikunja #809 — the extracted config-field validators)"
    )


@pytest.mark.parametrize(
    "entrypoint",
    [PA_ENTRYPOINT, AO_ENTRYPOINT],
    ids=["policy_agent", "assistant_orchestrator"],
)
def test_entrypoint_has_no_local_require_defs(entrypoint: Path) -> None:
    leaked = _local_require_defs(_parse(entrypoint))
    assert not leaked, (
        f"{entrypoint.name} re-introduced local config-validation helper(s): "
        f"{sorted(leaked)} — consume shared.config_validation instead (Vikunja #809)"
    )
