"""Config-time validation helpers — shared across service entrypoints.

A small hand-rolled suite of TOML-config field validators used by every
service entrypoint's ``_resolve_and_validate`` path (Policy Agent + Assistant
Orchestrator today). Each helper reads a raw config value, checks its type and
range, and on failure raises a :class:`~shared.runtime_config.ConfigResolutionError`
carrying a caller-supplied deterministic error ``code``. That code feeds the
deterministic failure-fingerprint stream (``build_failure_fingerprint``), so the
CALLER owns the service-specific prefix: the Policy Agent passes ``PA_CFG_*``
codes and the Assistant Orchestrator passes ``AO_CFG_*`` codes to the very same
functions. The helpers are prefix-agnostic — they echo whatever ``code`` they
are given — which is exactly how each service keeps its own exact contract codes
while sharing one implementation (Vikunja #809 / AUDIT-10, the DRY #4 fix).

Boundary — this is the CONFIG-TIME layer, deliberately kept separate from the
IPC-DECODE-TIME typed guards in ``shared/ipc/protocol.py`` (``require_int`` /
``require_str`` / ``require_bool`` / ``require_dict`` …, #803):

  * ``shared.config_validation`` (here): validates operator-authored TOML at
    service boot; failures raise ``ConfigResolutionError`` with a governance
    error code and refuse-to-start semantics.
  * ``shared.ipc.protocol`` guards: validate untrusted wire frames at message
    decode; failures raise ``ValueError`` (``_mistyped``) and drop/reject the
    frame.

The two suites share a family resemblance (and even a ``require_bool`` name) but
answer different questions at different trust boundaries — do NOT merge them.
Preserving each service's exact ``*_CFG_*`` codes is the load-bearing constraint;
a pydantic-backed rewrite is an explicitly declined follow-up (#809).
"""

from __future__ import annotations

from shared.runtime_config import ConfigResolutionError

__all__ = [
    "require_section_dict",
    "require_non_empty_str",
    "require_bool",
    "require_int_range",
    "require_float_range",
]


def require_section_dict(config_data: dict[str, object], key: str, *, code: str) -> dict[str, object]:
    value = config_data.get(key)
    if not isinstance(value, dict):
        raise ConfigResolutionError(code=code, message=f"Missing or invalid section [{key}].")
    return value


def require_non_empty_str(section: dict[str, object], key: str, *, code: str) -> str:
    value = section.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigResolutionError(code=code, message=f"Missing or invalid '{key}' value.")
    return value.strip()


def require_bool(section: dict[str, object], key: str, *, code: str) -> bool:
    value = section.get(key)
    if not isinstance(value, bool):
        raise ConfigResolutionError(code=code, message=f"'{key}' must be a boolean.")
    return value


def require_int_range(
    section: dict[str, object],
    key: str,
    *,
    minimum: int,
    maximum: int,
    code: str,
) -> int:
    value = section.get(key)
    if not isinstance(value, int):
        raise ConfigResolutionError(code=code, message=f"'{key}' must be an integer.")
    if value < minimum or value > maximum:
        raise ConfigResolutionError(
            code=code,
            message=(
                f"'{key}' out of range: {value}. Expected {minimum}..{maximum}."
            ),
        )
    return value


def require_float_range(
    section: dict[str, object],
    key: str,
    *,
    minimum: float,
    maximum: float,
    code: str,
) -> float:
    value = section.get(key)
    if not isinstance(value, (float, int)):
        raise ConfigResolutionError(code=code, message=f"'{key}' must be a number.")
    parsed = float(value)
    if parsed < minimum or parsed > maximum:
        raise ConfigResolutionError(
            code=code,
            message=(
                f"'{key}' out of range: {parsed}. Expected {minimum}..{maximum}."
            ),
        )
    return parsed
