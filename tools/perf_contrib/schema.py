"""Community-grade perf record schema validation.

A record is publishable only when it carries enough provenance for a third party
to reproduce or interpret the measurement without asking the author.

Required top-level fields
-------------------------
- name        : short scenario identifier (non-empty str)
- timestamp   : ISO-8601 string
- model       : model name + size (non-empty str)
- precision   : weight precision (non-empty str, e.g. "INT4")
- methodology : enough context to reproduce (non-empty str, >=20 chars)
- environment : dict — see _validate_environment()
- measurements: dict (non-empty)

The ``environment`` sub-dict must contain:
- cpu              : non-empty str
- not_measured     : non-empty list — REQUIRED so a reader never mistakes a
                     partial record for full coverage. At least one item.

Validation returns a ``ValidationResult`` dataclass; callers decide whether to
raise or log.  This keeps the module free of side-effects.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# ISO-8601 basic check: starts with 4-digit year, has T or space, not empty.
_ISO8601_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ].+")

# Minimum methodology length — a single word is not enough provenance.
_MIN_METHODOLOGY_CHARS = 20


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of validating a single perf record."""

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        if self.valid:
            return "VALID" + (f" ({len(self.warnings)} warnings)" if self.warnings else "")
        return f"INVALID: {'; '.join(self.errors)}"


def _validate_environment(env: Any) -> tuple[list[str], list[str]]:
    """Validate the ``environment`` sub-dict.

    Returns (errors, warnings).
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(env, dict):
        errors.append("environment must be a dict")
        return errors, warnings

    if not env.get("cpu"):
        errors.append("environment.cpu is required and must be a non-empty string")

    # not_measured is the key community-contribution guard: a record that names
    # what it DID NOT measure cannot accidentally imply full coverage.
    not_measured = env.get("not_measured")
    if not_measured is None:
        errors.append(
            "environment.not_measured is required (list of what this record does NOT cover). "
            "Omitting it implies false full-coverage to community readers."
        )
    elif not isinstance(not_measured, list):
        errors.append("environment.not_measured must be a list")
    elif len(not_measured) == 0:
        errors.append(
            "environment.not_measured must contain at least one entry. "
            "An empty list implies complete coverage, which is never true."
        )

    # Warn if GPU is absent — most records for this hardware should name the GPU.
    if not env.get("gpu"):
        warnings.append(
            "environment.gpu not present — add it if this record involved GPU-side work"
        )

    # Warn if OpenVINO version is absent or 'unavailable'.
    ov = env.get("openvino_version", "")
    if not ov or ov == "unavailable":
        warnings.append(
            "environment.openvino_version is absent or 'unavailable' — "
            "include it for reproducibility when OpenVINO is in use"
        )

    return errors, warnings


def validate(record: dict[str, Any]) -> ValidationResult:
    """Validate *record* against the community-grade perf schema.

    Args:
        record: Parsed JSON dict from a perf file.

    Returns:
        A :class:`ValidationResult`. ``valid`` is ``True`` only when there are
        zero errors. Warnings are informational and do not affect validity.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # --- top-level required string fields ---
    for field_name in ("name", "model", "precision"):
        val = record.get(field_name)
        if not val or not isinstance(val, str) or not val.strip():
            errors.append(f"'{field_name}' is required and must be a non-empty string")

    # --- timestamp ---
    ts = record.get("timestamp")
    if not ts or not isinstance(ts, str):
        errors.append("'timestamp' is required and must be an ISO-8601 string")
    elif not _ISO8601_RE.match(ts):
        errors.append(f"'timestamp' does not look like ISO-8601: {ts!r}")

    # --- methodology ---
    methodology = record.get("methodology")
    if not methodology or not isinstance(methodology, str):
        errors.append("'methodology' is required and must be a non-empty string")
    elif len(methodology.strip()) < _MIN_METHODOLOGY_CHARS:
        errors.append(
            f"'methodology' is too short ({len(methodology.strip())} chars, "
            f"minimum {_MIN_METHODOLOGY_CHARS}). "
            "It must describe the prompt set, run count, and config — enough to reproduce."
        )

    # --- environment ---
    env = record.get("environment")
    if env is None:
        errors.append("'environment' dict is required")
    else:
        env_errors, env_warnings = _validate_environment(env)
        errors.extend(env_errors)
        warnings.extend(env_warnings)

    # --- measurements ---
    measurements = record.get("measurements")
    if measurements is None:
        errors.append("'measurements' dict is required")
    elif not isinstance(measurements, dict):
        errors.append("'measurements' must be a dict")
    elif len(measurements) == 0:
        errors.append("'measurements' must contain at least one entry")

    # --- informational warnings for optional but useful fields ---
    if not record.get("notes") and not errors:
        # Not an error — notes is optional. But nudge if everything else is fine.
        warnings.append(
            "'notes' field is empty — consider adding caveats or context for community readers"
        )

    return ValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)


def validate_strict(record: dict[str, Any]) -> None:
    """Like :func:`validate` but raises ``ValueError`` on any failure."""
    result = validate(record)
    if not result.valid:
        raise ValueError(f"Perf record failed schema validation: {result}")
