"""Tests for tools.perf_contrib.schema — deterministic, no I/O, no GPU."""
from __future__ import annotations

import copy
import pytest

from tools.perf_contrib.schema import validate, validate_strict, ValidationResult
from tools.perf_contrib.tests.fixtures import (
    minimal_valid,
    harness_chat_record,
    invalid_missing_name,
    invalid_empty_name,
    invalid_missing_timestamp,
    invalid_bad_timestamp,
    invalid_missing_model,
    invalid_missing_precision,
    invalid_methodology_too_short,
    invalid_missing_methodology,
    invalid_missing_environment,
    invalid_environment_not_dict,
    invalid_missing_cpu,
    invalid_missing_not_measured,
    invalid_empty_not_measured,
    invalid_not_measured_not_list,
    invalid_missing_measurements,
    invalid_empty_measurements,
    invalid_measurements_not_dict,
)


# ---- valid records -----------------------------------------------------------

class TestValidRecords:
    def test_minimal_valid_passes(self) -> None:
        result = validate(minimal_valid())
        assert result.valid, f"Expected PASS, got errors: {result.errors}"

    def test_harness_chat_passes(self) -> None:
        """A real harness record shape should pass."""
        result = validate(harness_chat_record())
        assert result.valid, f"Expected PASS, got errors: {result.errors}"

    def test_valid_returns_validation_result(self) -> None:
        result = validate(minimal_valid())
        assert isinstance(result, ValidationResult)

    def test_valid_has_no_errors(self) -> None:
        result = validate(minimal_valid())
        assert result.errors == []

    def test_validate_strict_does_not_raise_on_valid(self) -> None:
        validate_strict(minimal_valid())  # must not raise

    def test_str_representation_valid(self) -> None:
        result = validate(minimal_valid())
        assert "VALID" in str(result)

    def test_extra_top_level_fields_allowed(self) -> None:
        """Harness may add extra keys (source, _internal, etc.) — should be ignored."""
        rec = minimal_valid()
        rec["extra_field"] = "some value"
        rec["source"] = "tests/harness"
        result = validate(rec)
        assert result.valid

    def test_notes_empty_string_allowed(self) -> None:
        rec = minimal_valid()
        rec["notes"] = ""
        result = validate(rec)
        assert result.valid

    def test_notes_non_empty_string_no_warning(self) -> None:
        """A populated notes field should not produce a notes warning."""
        rec = minimal_valid()
        rec["notes"] = "Measured on AC power; GPU was warm from prior run."
        result = validate(rec)
        assert result.valid
        notes_warnings = [w for w in result.warnings if "notes" in w.lower()]
        assert notes_warnings == []


# ---- invalid: top-level required fields -------------------------------------

class TestInvalidTopLevel:
    @pytest.mark.parametrize("factory,expected_fragment", [
        (invalid_missing_name, "'name'"),
        (invalid_empty_name, "'name'"),
        (invalid_missing_timestamp, "'timestamp'"),
        (invalid_bad_timestamp, "'timestamp'"),
        (invalid_missing_model, "'model'"),
        (invalid_missing_precision, "'precision'"),
        (invalid_methodology_too_short, "'methodology'"),
        (invalid_missing_methodology, "'methodology'"),
        (invalid_missing_environment, "'environment'"),
        (invalid_missing_measurements, "'measurements'"),
        (invalid_empty_measurements, "'measurements'"),
        (invalid_measurements_not_dict, "'measurements'"),
    ])
    def test_invalid_returns_false(self, factory, expected_fragment) -> None:
        result = validate(factory())
        assert not result.valid
        assert any(expected_fragment in err for err in result.errors), (
            f"Expected error containing {expected_fragment!r}; got: {result.errors}"
        )

    def test_validate_strict_raises_on_invalid(self) -> None:
        with pytest.raises(ValueError, match="schema validation"):
            validate_strict(invalid_missing_name())

    def test_str_representation_invalid(self) -> None:
        result = validate(invalid_missing_name())
        assert "INVALID" in str(result)


# ---- invalid: environment sub-dict ------------------------------------------

class TestInvalidEnvironment:
    def test_environment_not_dict(self) -> None:
        result = validate(invalid_environment_not_dict())
        assert not result.valid
        assert any("environment" in e for e in result.errors)

    def test_missing_cpu(self) -> None:
        result = validate(invalid_missing_cpu())
        assert not result.valid
        assert any("cpu" in e for e in result.errors)

    def test_missing_not_measured(self) -> None:
        """The most important community-grade check: not_measured must be present."""
        result = validate(invalid_missing_not_measured())
        assert not result.valid
        assert any("not_measured" in e for e in result.errors)

    def test_empty_not_measured(self) -> None:
        """Empty not_measured implies false full coverage — must be rejected."""
        result = validate(invalid_empty_not_measured())
        assert not result.valid
        assert any("not_measured" in e for e in result.errors)

    def test_not_measured_not_list(self) -> None:
        result = validate(invalid_not_measured_not_list())
        assert not result.valid
        assert any("not_measured" in e for e in result.errors)

    def test_multiple_environment_errors_collected(self) -> None:
        """All environment errors should be reported, not just the first."""
        rec = copy.deepcopy(minimal_valid())
        del rec["environment"]["cpu"]
        del rec["environment"]["not_measured"]
        result = validate(rec)
        assert not result.valid
        assert len(result.errors) >= 2

    def test_missing_gpu_produces_warning_not_error(self) -> None:
        """GPU is recommended but not required — should warn, not fail."""
        rec = copy.deepcopy(minimal_valid())
        del rec["environment"]["gpu"]
        result = validate(rec)
        assert result.valid, f"Expected PASS (gpu is optional), got: {result.errors}"
        assert any("gpu" in w.lower() for w in result.warnings)

    def test_unavailable_openvino_version_produces_warning(self) -> None:
        rec = copy.deepcopy(minimal_valid())
        rec["environment"]["openvino_version"] = "unavailable"
        result = validate(rec)
        assert result.valid
        assert any("openvino_version" in w for w in result.warnings)

    def test_absent_openvino_version_produces_warning(self) -> None:
        rec = copy.deepcopy(minimal_valid())
        del rec["environment"]["openvino_version"]
        result = validate(rec)
        assert result.valid
        assert any("openvino_version" in w for w in result.warnings)


# ---- methodology length boundary --------------------------------------------

class TestMethodologyLength:
    def test_exactly_20_chars_passes(self) -> None:
        rec = minimal_valid()
        rec["methodology"] = "A" * 20  # exactly at the threshold
        result = validate(rec)
        assert result.valid

    def test_19_chars_fails(self) -> None:
        rec = minimal_valid()
        rec["methodology"] = "A" * 19
        result = validate(rec)
        assert not result.valid
        assert any("methodology" in e for e in result.errors)

    def test_whitespace_only_methodology_fails(self) -> None:
        rec = minimal_valid()
        rec["methodology"] = "   " * 10  # many whitespace chars but no content
        result = validate(rec)
        assert not result.valid


# ---- timestamp format -------------------------------------------------------

class TestTimestampFormat:
    @pytest.mark.parametrize("ts", [
        "2026-06-04T17:20:28.995057+00:00",
        "2026-06-04T17:20:28Z",
        "2026-06-04 17:20:28",
        "2026-01-01T00:00:00",
    ])
    def test_valid_timestamps(self, ts: str) -> None:
        rec = minimal_valid()
        rec["timestamp"] = ts
        result = validate(rec)
        assert result.valid

    @pytest.mark.parametrize("ts", [
        "not-a-date",
        "06/04/2026",
        "2026-06-04",          # date-only — no T or space separator
        "",
        "2026",
    ])
    def test_invalid_timestamps(self, ts: str) -> None:
        rec = minimal_valid()
        rec["timestamp"] = ts
        result = validate(rec)
        assert not result.valid
