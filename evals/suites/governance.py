"""
Eval Suite — Deterministic Governance Verdicts
===============================================
Proves the security-governance decision surfaces produce the expected
verdicts, driving the REAL functions (not mocks) wherever they are
importable as functions:

  risk_tier                   — ``tools.risk_tier`` (ADR-023 Am.1): the four
                                shipped tools' declared tiers AND the
                                fail-closed default (unknown/undeclared tool
                                -> DANGEROUS).
  pa_prefilter                — ``DeterministicPolicyChecker.check`` over
                                golden CARs (RULE 1-10; live EMPTY egress
                                allowlist — the welded air-gap posture).
  tool_dispatch_adjudication  — ``entrypoint._adjudicate_tool_dispatch``
                                (#570 / ADR-023 §2.4): the AO->PA mediation
                                every tool dispatch passes through,
                                including injection-shaped args.
  escalation_consent_default  — ``request_escalation_consent`` with NO
                                verifier registered (#639 / ADR-024 §2.5):
                                the dormant default must DENY (fail-closed).
  layer3_lock                 — the ADR-023 privilege-separation predicate
                                (untrusted content locks non-SAFE tools;
                                /trust overrides GUARDED only; DANGEROUS has
                                NO override).
  leakage_feed                — the REAL ``ContextManager`` Stage-5 leakage-feed
                                carve-out (ADR-023 Am.2/Am.3): UNTRUSTED_WEB +
                                UNTRUSTED_KNOWLEDGE are leak-exempt (NOT fed) but
                                still action-locked; UNTRUSTED_EXTERNAL
                                (/external pasted content) IS screened.

HONESTY NOTE on layer3_lock: the Layer-3 predicate is written inline in the
AO tool loop (services/assistant_orchestrator/src/entrypoint.py, the
``_layer3_blocked`` gate in ``_handle_prompt``'s tool loop) and is not
importable as a standalone function. :func:`layer3_lock_decision` below is a
faithful MIRROR of that inline predicate — the tier input still comes from
the real ``tools.risk_tier`` — and the mirror's provenance is pinned by
comment cross-reference. If the inline predicate changes shape, this mirror
must be updated in the same change (the standing-gate integration test
exercises both this suite and the AO's own Layer-3 tests, which drive the
real loop).

Golden case schema (evals/golden/governance.jsonl) — ``kind`` selects the
surface; see the per-kind handlers below for the exact fields.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from evals.loader import GoldenDataError, golden_path, load_golden
from evals.types import CaseResult, CaseStatus, SuiteReport

SUITE_NAME: str = "governance"

_VALID_KINDS: frozenset[str] = frozenset(
    {
        "risk_tier",
        "pa_prefilter",
        "tool_dispatch_adjudication",
        "escalation_consent_default",
        "layer3_lock",
        "leakage_feed",
        "egress_consent",
        "generation_consent",
    }
)


# ---------------------------------------------------------------------------
# Layer-3 lock predicate (mirror — see HONESTY NOTE in the module docstring)
# ---------------------------------------------------------------------------


def layer3_lock_decision(
    *,
    block_tools_on_untrusted_content: bool,
    has_untrusted_content: bool,
    tool_name: str,
    trusted_for_tools: bool,
) -> bool:
    """Return True iff the Layer-3 action-lock refuses the tool call.

    MIRRORS services/assistant_orchestrator/src/entrypoint.py (the
    ``_layer3_blocked`` gate inside the tool loop — ADR-023 Amendment 1 +
    #593 capability-scoped locking + Amendment 4/#723 bounded-danger exemption):

        lock fires iff  block_tools_on_untrusted_content
                    AND has_untrusted_content(session)
                    AND tier != SAFE
                    AND NOT is_lock_exempt(tool)
                    AND NOT is_egress_tool(tool)
                    AND NOT (tier == GUARDED AND trusted_for_tools)

    The tier input is the REAL ``tools.risk_tier`` (fail-closed: unknown ->
    DANGEROUS), so an undeclared tool is locked with NO /trust override. The
    ``is_lock_exempt`` input is the REAL ``tools.is_lock_exempt`` (ADR-023
    Amendment 4, #723 rung 1) — a per-tool bounded-danger allowlist, so a
    non-exfiltratable local read (``search_knowledge``) is never locked. The
    ``is_egress_tool`` input is the REAL ``tools.is_egress_tool`` (ADR-023
    Amendment 4, #723 rung 3) — an OUTBOUND tool (``web_search``) is not gated by
    this lock at all; the turn-scoped Hello fingerprint envelope is its consent
    instead, so it never trips /trust here.
    """
    from services.assistant_orchestrator.src import tools

    tier = tools.risk_tier(tool_name)
    return (
        block_tools_on_untrusted_content
        and has_untrusted_content
        and tier is not tools.RiskTier.SAFE
        and not tools.is_lock_exempt(tool_name)
        and not tools.is_egress_tool(tool_name)
        and not (tier is tools.RiskTier.GUARDED and trusted_for_tools)
    )


# ---------------------------------------------------------------------------
# Per-kind evaluators — each returns (expected_repr, actual_repr, ok, detail)
# ---------------------------------------------------------------------------


def _eval_risk_tier(case: dict[str, Any]) -> tuple[Any, Any, bool]:
    from services.assistant_orchestrator.src import tools

    expected = str(case["expected_tier"])
    actual = tools.risk_tier(str(case["tool"])).value
    return expected, actual, actual == expected


def _eval_pa_prefilter(case: dict[str, Any]) -> tuple[Any, Any, bool]:
    import uuid

    from services.policy_agent.src.gpu_inference import DeterministicPolicyChecker
    from shared.schemas.car import (
        ActionVerb,
        CanonicalActionRepresentation,
        Sensitivity,
    )

    car_dict: dict[str, Any] = case["car"]
    car = CanonicalActionRepresentation(
        source_agent=car_dict.get("source_agent", ""),
        destination_service=car_dict.get("destination_service", ""),
        verb=ActionVerb(car_dict["verb"]) if car_dict.get("verb") else ActionVerb.READ,
        sensitivity=(
            Sensitivity(car_dict["sensitivity"])
            if car_dict.get("sensitivity")
            else Sensitivity.UNCLASSIFIED
        ),
        resource=car_dict.get("resource", ""),
        parameters_schema=car_dict.get("parameters_schema") or {},
        request_id=str(uuid.uuid4()),
        session_id=car_dict.get("session_id", ""),
    )
    verdict = DeterministicPolicyChecker.check(car)
    expected = case["expected"]  # null | {"decision": ..., "rule": ...}
    actual = (
        None if verdict is None else {"decision": verdict[0], "rule": verdict[1]}
    )
    return expected, actual, actual == expected


def _eval_tool_dispatch_adjudication(case: dict[str, Any]) -> tuple[Any, Any, bool]:
    # Real function: the AO's #570 dispatch-mediation seam. Importing the AO
    # entrypoint module is headless-safe (the standing gate does it in every
    # run); no model loads at import time.
    from services.assistant_orchestrator.src.entrypoint import (
        _adjudicate_tool_dispatch,
    )

    verdict = _adjudicate_tool_dispatch(
        str(case["tool"]), str(case.get("args", "")), "eval-harness-session"
    )
    expected = case["expected"]  # null | {"decision": ..., "rule": ...}
    actual = (
        None if verdict is None else {"decision": verdict[0], "rule": verdict[1]}
    )
    return expected, actual, actual == expected


def _eval_escalation_consent_default(case: dict[str, Any]) -> tuple[Any, Any, bool]:
    # Real function, hermetic: snapshot any registered verifier, clear to the
    # dormant default, exercise, restore. Uses only the module's public API.
    from shared.security.escalation_consent import (
        EscalationContext,
        active_verifier,
        clear_verifier,
        register_verifier,
        request_escalation_consent,
    )

    saved = active_verifier()
    clear_verifier()
    try:
        ctx = EscalationContext.from_pa_verdict(
            str(case.get("rule", "ESCALATE_CROSS_AGENT_OWNERSHIP")),
            tool_name=str(case.get("tool", "eval_probe_tool")),
            action_summary="eval-harness escalation-consent probe",
            source="policy_agent",
        )
        result = request_escalation_consent(ctx, timeout_s=1.0)
        expected = bool(case["expected_approved"])
        actual = bool(result.approved)
        return expected, actual, actual == expected
    finally:
        if saved is not None:
            register_verifier(saved)


def _eval_leakage_feed(case: dict[str, Any]) -> tuple[Any, Any, bool]:
    """Drive the REAL ContextManager: ground one chunk at the case's provenance
    tier and assert whether it reaches the Stage-5 cosine leakage feed
    (``get_untrusted_chunk_texts``). This is the ADR-023 Amendment 2/3 carve-out
    surface — UNTRUSTED_WEB / UNTRUSTED_KNOWLEDGE are leak-exempt (NOT in the
    feed) while UNTRUSTED_EXTERNAL (/external pasted content) IS screened. The
    action-lock (``has_untrusted_content``) is asserted in the same pass so a
    carve-out that also dropped the lock would fail here."""
    from services.assistant_orchestrator.src.context_manager import (
        ContextManager,
        Provenance,
    )

    prov = Provenance(str(case["provenance"]))
    cm = ContextManager()
    cm.create_session("eval-leak-session")
    cm.add_grounded_context(
        "eval-leak-session", ["public content the operator asked for"], provenance=prov
    )
    in_leak_feed = len(cm.get_untrusted_chunk_texts("eval-leak-session")) > 0
    action_locked = cm.has_untrusted_content("eval-leak-session")
    expected = {
        "in_leak_feed": bool(case["expected_in_leak_feed"]),
        "action_locked": bool(case["expected_action_locked"]),
    }
    actual = {"in_leak_feed": in_leak_feed, "action_locked": action_locked}
    return expected, actual, actual == expected


def _eval_layer3_lock(case: dict[str, Any]) -> tuple[Any, Any, bool]:
    expected = bool(case["expected_locked"])
    actual = layer3_lock_decision(
        block_tools_on_untrusted_content=bool(case["block_flag"]),
        has_untrusted_content=bool(case["has_untrusted"]),
        tool_name=str(case["tool"]),
        trusted_for_tools=bool(case.get("trust_override", False)),
    )
    return expected, actual, actual == expected


def _eval_egress_consent(case: dict[str, Any]) -> tuple[Any, Any, bool]:
    """Drive the REAL turn-scoped egress envelope (ADR-023 Am.4 #723 rung 3) with
    a scripted consent_fn: assert the allow-sequence and the number of Windows-
    Hello fingerprints across N queries in one turn. This is the committed
    governance evidence that (a) a denied/fail-closed fingerprint lets NOTHING
    egress and latches the turn, (b) one touch covers up to N searches, and (c)
    exceeding N re-fingerprints. The consent verdicts are scripted per fingerprint
    attempt (in order); an exhausted script is fail-closed (deny)."""
    from services.assistant_orchestrator.src.egress_envelope import (
        EgressEnvelopeManager,
    )

    verdicts = list(case.get("consent_verdicts", []))
    fp_calls = {"n": 0}

    def _consent_fn(query: str, n: int) -> bool:
        i = fp_calls["n"]
        fp_calls["n"] += 1
        return bool(verdicts[i]) if i < len(verdicts) else False  # exhausted → deny

    mgr = EgressEnvelopeManager()
    mgr.begin_turn("eval-egress", int(case["n"]))
    allowed = [
        bool(mgr.gate("eval-egress", f"q{k}", consent_fn=_consent_fn).allowed)
        for k in range(int(case["num_queries"]))
    ]
    actual = {"allowed": allowed, "fingerprints": fp_calls["n"]}
    expected = {
        "allowed": [bool(x) for x in case["expected_allowed"]],
        "fingerprints": int(case["expected_fingerprints"]),
    }
    return expected, actual, actual == expected


def _eval_generation_consent(case: dict[str, Any]) -> tuple[Any, Any, bool]:
    """Drive the REAL per-batch generation-approval seam (ADR-023 Am.4 #723 rung 2,
    DORMANT): assert the fail-closed default (no verifier → deny) and that only an
    explicit approval allows. Committed evidence that a dormant seam is fail-closed,
    NOT fail-open. Hermetic: snapshot/clear/restore the generation registry."""
    from shared.security.escalation_consent import ApprovalResult
    from shared.security.generation_consent import (
        active_generation_verifier,
        clear_generation_verifier,
        register_generation_verifier,
        request_generation_consent,
    )

    class _Stub:
        def __init__(self, approved: bool) -> None:
            self._a = approved

        def verify(self, ctx: Any) -> ApprovalResult:
            return (
                ApprovalResult.allow(verifier_identity="eval")
                if self._a
                else ApprovalResult.deny("no", verifier_identity="eval")
            )

    saved = active_generation_verifier()
    clear_generation_verifier()
    try:
        posture = str(case.get("verifier", "none"))
        if posture == "approve":
            register_generation_verifier(_Stub(True))
        elif posture == "deny":
            register_generation_verifier(_Stub(False))
        actual = request_generation_consent("eval prompt", 1, timeout_s=1.0)
        expected = bool(case["expected_approved"])
        return expected, actual, actual == expected
    finally:
        clear_generation_verifier()
        if saved is not None:
            register_generation_verifier(saved)


_KIND_EVALUATORS: dict[str, Callable[[dict[str, Any]], tuple[Any, Any, bool]]] = {
    "risk_tier": _eval_risk_tier,
    "pa_prefilter": _eval_pa_prefilter,
    "tool_dispatch_adjudication": _eval_tool_dispatch_adjudication,
    "escalation_consent_default": _eval_escalation_consent_default,
    "layer3_lock": _eval_layer3_lock,
    "leakage_feed": _eval_leakage_feed,
    "egress_consent": _eval_egress_consent,
    "generation_consent": _eval_generation_consent,
}

_KIND_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "risk_tier": ("tool", "expected_tier"),
    "pa_prefilter": ("car", "expected"),
    "tool_dispatch_adjudication": ("tool", "expected"),
    "escalation_consent_default": ("expected_approved",),
    "layer3_lock": ("block_flag", "has_untrusted", "tool", "expected_locked"),
    "leakage_feed": ("provenance", "expected_in_leak_feed", "expected_action_locked"),
    "egress_consent": (
        "n", "num_queries", "consent_verdicts",
        "expected_allowed", "expected_fingerprints",
    ),
    "generation_consent": ("expected_approved",),
}


def _validate_case(case: dict[str, Any]) -> str | None:
    kind = case.get("kind")
    if kind not in _VALID_KINDS:
        return f"invalid kind {kind!r} (must be one of {sorted(_VALID_KINDS)})"
    for required in _KIND_REQUIRED_FIELDS[kind]:
        if required not in case:
            return f"kind {kind!r} requires field '{required}'"
    return None


def run_suite(
    golden_file: Path | None = None,
    *,
    include_hardware: bool = False,  # noqa: ARG001 — suite is fully deterministic
) -> SuiteReport:
    """Run the governance suite (deterministic; no model, no GPU)."""
    path = golden_file or golden_path(SUITE_NAME)
    cases = load_golden(path)

    report = SuiteReport(suite=SUITE_NAME)
    for case in cases:
        problem = _validate_case(case)
        if problem is not None:
            raise GoldenDataError(f"{path.name} case {case.get('id')}: {problem}")
        case_id = str(case["id"])
        description = str(case.get("description", ""))
        evaluator = _KIND_EVALUATORS[str(case["kind"])]
        try:
            expected, actual, ok = evaluator(case)
        except Exception as exc:  # noqa: BLE001 — harness scoring must not abort the run
            report.results.append(
                CaseResult(
                    case_id=case_id,
                    status=CaseStatus.ERROR,
                    description=description,
                    detail=f"harness error: {exc}",
                )
            )
            continue
        report.results.append(
            CaseResult(
                case_id=case_id,
                status=CaseStatus.PASS if ok else CaseStatus.FAIL,
                description=description,
                expected=expected,
                actual=actual,
                detail=(
                    ""
                    if ok
                    else f"expected {expected!r}, got {actual!r} ({case['kind']})"
                ),
            )
        )
    return report
