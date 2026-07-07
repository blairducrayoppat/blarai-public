"""
Eval Suite — AO Tool Calling
=============================
Measures the AO's tool-call behaviour over golden MODEL-OUTPUT strings:
parse fidelity (``tools.parse_tool_call``), allowlist enforcement
(``pgov.TOOL_CALL_ALLOWLIST``), and dispatch outcomes through the REAL
registry (``tools.execute``) — SAFE-tier tools only.

FORMAT-AGNOSTIC BY DESIGN: cases drive the public abstraction
(``parse_tool_call`` + ``execute``), never the regex/format internals. Each
case carries a ``format`` field: ``qwen3_json`` (the Qwen3-native JSON
form — the ONLY form the parser accepts since the #718 D3 legacy
retirement, 2026-07-02) or ``legacy_xml`` (the RETIRED
``<tool_call>NAME(args)</tool_call>`` grammar — every case that previously
parsed now expects no-parse, the regression locks proving the form stays
dead). Format-independent expectations (unknown-tool refusal, SAFE-only
dispatch, injection-shaped args never executing) apply to every format.

SAFETY GUARD (fail-closed): the harness only ever EXECUTES a tool that is
(a) present in the real registry AND (b) declared ``RiskTier.SAFE``. A
golden case asking to dispatch a non-SAFE tool is a harness ERROR, not an
execution. Unknown tools are dispatched only to observe the expected
``KeyError`` refusal (nothing runs).

Golden case schema (evals/golden/tool_calling.jsonl):
  {"id": "tcj-001", "description": "...", "format": "qwen3_json",
   "category": "parse" | "dispatch" | "adversarial",
   "model_output": "<tool_call>{\"name\": \"calculate\", \"arguments\":
                    {\"expression\": \"2+2\"}}</tool_call>",
   "expect_parse": {"name": "calculate", "args": "{\"expression\":\"2+2\"}"}
                   | null,
   "expect_allowlisted": true,                       # optional
   "dispatch": {"expect_kind": "exact" | "contains" | "regex" | "raises",
                "expect_value": "4"}}                # optional
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from evals.loader import GoldenDataError, golden_path, load_golden
from evals.types import CaseResult, CaseStatus, SuiteReport

SUITE_NAME: str = "tool_calling"

_VALID_CATEGORIES: frozenset[str] = frozenset({"parse", "dispatch", "adversarial"})
_VALID_DISPATCH_KINDS: frozenset[str] = frozenset(
    {"exact", "contains", "regex", "raises"}
)


def _validate_case(case: dict[str, Any]) -> str | None:
    """Return an error string if the golden case is malformed, else None."""
    if case.get("category") not in _VALID_CATEGORIES:
        return (
            f"invalid category {case.get('category')!r} "
            f"(must be one of {sorted(_VALID_CATEGORIES)})"
        )
    if not isinstance(case.get("model_output"), str):
        return "missing/invalid 'model_output' string"
    if "expect_parse" not in case:
        return "missing 'expect_parse' (object or null)"
    expect_parse = case["expect_parse"]
    if expect_parse is not None and (
        not isinstance(expect_parse, dict)
        or "name" not in expect_parse
        or "args" not in expect_parse
    ):
        return "'expect_parse' must be null or {name, args}"
    dispatch = case.get("dispatch")
    if dispatch is not None:
        if not isinstance(dispatch, dict):
            return "'dispatch' must be an object"
        if dispatch.get("expect_kind") not in _VALID_DISPATCH_KINDS:
            return (
                f"invalid dispatch.expect_kind {dispatch.get('expect_kind')!r} "
                f"(must be one of {sorted(_VALID_DISPATCH_KINDS)})"
            )
        if not isinstance(dispatch.get("expect_value"), str):
            return "dispatch.expect_value must be a string"
        if expect_parse is None:
            return "a case with 'dispatch' must expect a successful parse"
    return None


def _check_dispatch(
    tool_name: str, tool_args: str, dispatch: dict[str, Any]
) -> tuple[bool, str, Any]:
    """Execute the dispatch leg and score it.

    Returns:
        (ok, detail, actual) — ``ok`` False means the case FAILS;
        ``detail`` explains; ``actual`` is the observed outcome.
    """
    from services.assistant_orchestrator.src import tools

    expect_kind = dispatch["expect_kind"]
    expect_value = dispatch["expect_value"]

    if expect_kind == "raises":
        try:
            result = tools.execute(tool_name, tool_args)
        except Exception as exc:  # noqa: BLE001 — the expected outcome IS an exception
            actual = type(exc).__name__
            if actual == expect_value:
                return True, "", f"raised {actual}"
            return (
                False,
                f"expected {expect_value} but got {actual}: {exc}",
                f"raised {actual}",
            )
        return (
            False,
            f"expected {expect_value} but tool executed successfully",
            result,
        )

    # Executing path — fail-closed SAFE-only guard.
    if tool_name not in tools._REGISTRY:  # noqa: SLF001 — registry membership check
        return (
            False,
            f"tool {tool_name!r} not in registry — cannot dispatch",
            None,
        )
    tier = tools.risk_tier(tool_name)
    if tier is not tools.RiskTier.SAFE:
        raise GoldenDataError(
            f"golden case asks to EXECUTE non-SAFE tool {tool_name!r} "
            f"(tier {tier.value}) — the eval harness only dispatches "
            f"SAFE-tier tools (fail-closed guard)"
        )

    try:
        result = tools.execute(tool_name, tool_args)
    except Exception as exc:  # noqa: BLE001 — SAFE tools must not raise; scored as fail
        return (
            False,
            f"SAFE tool raised {type(exc).__name__}: {exc}",
            f"raised {type(exc).__name__}",
        )

    if expect_kind == "exact":
        ok = result == expect_value
    elif expect_kind == "contains":
        ok = expect_value in result
    else:  # regex
        ok = re.search(expect_value, result) is not None
    detail = (
        ""
        if ok
        else f"dispatch result {result!r} failed {expect_kind} check {expect_value!r}"
    )
    return ok, detail, result


def _evaluate_case(case: dict[str, Any]) -> CaseResult:
    """Score one golden case against the real parse/allowlist/dispatch path."""
    from services.assistant_orchestrator.src import tools
    from services.assistant_orchestrator.src.pgov import TOOL_CALL_ALLOWLIST

    case_id = str(case["id"])
    description = str(case.get("description", ""))
    expect_parse = case["expect_parse"]

    expected: dict[str, Any] = {"parse": expect_parse}
    actual: dict[str, Any] = {}

    parsed = tools.parse_tool_call(case["model_output"])
    actual["parse"] = (
        None if parsed is None else {"name": parsed[0], "args": parsed[1]}
    )

    # 1. Parse fidelity.
    if expect_parse is None:
        if parsed is not None:
            return CaseResult(
                case_id=case_id,
                status=CaseStatus.FAIL,
                description=description,
                expected=expected,
                actual=actual,
                detail=f"expected no parse, but parsed {actual['parse']}",
            )
        return CaseResult(
            case_id=case_id,
            status=CaseStatus.PASS,
            description=description,
            expected=expected,
            actual=actual,
        )
    if parsed is None:
        return CaseResult(
            case_id=case_id,
            status=CaseStatus.FAIL,
            description=description,
            expected=expected,
            actual=actual,
            detail="expected a parse, got None",
        )
    tool_name, tool_args = parsed
    if tool_name != expect_parse["name"] or tool_args != expect_parse["args"]:
        return CaseResult(
            case_id=case_id,
            status=CaseStatus.FAIL,
            description=description,
            expected=expected,
            actual=actual,
            detail=f"parse mismatch: expected {expect_parse}, got {actual['parse']}",
        )

    # 2. Allowlist expectation (optional).
    if "expect_allowlisted" in case:
        expected["allowlisted"] = bool(case["expect_allowlisted"])
        actual["allowlisted"] = tool_name in TOOL_CALL_ALLOWLIST
        if actual["allowlisted"] != expected["allowlisted"]:
            return CaseResult(
                case_id=case_id,
                status=CaseStatus.FAIL,
                description=description,
                expected=expected,
                actual=actual,
                detail=(
                    f"allowlist mismatch for {tool_name!r}: expected "
                    f"{expected['allowlisted']}, got {actual['allowlisted']}"
                ),
            )

    # 3. Dispatch expectation (optional).
    dispatch = case.get("dispatch")
    if dispatch is not None:
        expected["dispatch"] = {
            "kind": dispatch["expect_kind"],
            "value": dispatch["expect_value"],
        }
        ok, detail, dispatch_actual = _check_dispatch(
            tool_name, tool_args, dispatch
        )
        actual["dispatch"] = dispatch_actual
        if not ok:
            return CaseResult(
                case_id=case_id,
                status=CaseStatus.FAIL,
                description=description,
                expected=expected,
                actual=actual,
                detail=detail,
            )

    return CaseResult(
        case_id=case_id,
        status=CaseStatus.PASS,
        description=description,
        expected=expected,
        actual=actual,
    )


def run_suite(
    golden_file: Path | None = None,
    *,
    include_hardware: bool = False,  # noqa: ARG001 — suite is fully deterministic
) -> SuiteReport:
    """Run the tool-calling suite (deterministic; no model, no GPU)."""
    path = golden_file or golden_path(SUITE_NAME)
    cases = load_golden(path)

    report = SuiteReport(suite=SUITE_NAME)
    for case in cases:
        problem = _validate_case(case)
        if problem is not None:
            raise GoldenDataError(f"{path.name} case {case.get('id')}: {problem}")
        try:
            report.results.append(_evaluate_case(case))
        except GoldenDataError:
            raise
        except Exception as exc:  # noqa: BLE001 — harness scoring must not abort the run
            report.results.append(
                CaseResult(
                    case_id=str(case["id"]),
                    status=CaseStatus.ERROR,
                    description=str(case.get("description", "")),
                    detail=f"harness error: {exc}",
                )
            )
    return report
