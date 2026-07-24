"""
Eval Harness — Baseline Storage and Regression Comparison
==========================================================
A baseline is a committed JSON snapshot of per-case statuses for one suite.
Comparison semantics (fail-closed):

  REGRESSION (exit nonzero):
    * a case that PASSED in the baseline now fails or errors;
    * a case failing/erroring now that is ABSENT from the baseline (a new
      case must either pass or be consciously baselined as a known-fail);
    * a failing case whose baseline value is anything OTHER than a recorded
      ``fail``/``error`` — ``skipped_hardware`` (never measured), a
      hand-edited typo, a status that does not exist yet, or a value that
      is not a string at all (#1010).  Only a recorded failure earns
      silence (#1000);
    * a case present in the baseline that is missing from the run (a golden
      case was removed without refreshing the baseline);
    * a baseline whose ``cases`` block is not an object at all — nothing
      can be compared, which is reported as a regression rather than as
      silence or a crash (#1010).

  NOT a regression:
    * a case that failed in the baseline and still fails (a *known* model
      deficiency being tracked — e.g. ISS-3 classification misses);
    * a case that failed in the baseline and now passes (an IMPROVEMENT —
      reported so the operator can refresh the baseline);
    * a case SKIPPED IN THIS RUN for want of hardware (not scored, so not
      compared — this is about the RUN's status, never the baseline's).

``known_failures`` means "a deficiency somebody consciously recorded as
failing".  That meaning is only earned by an actual recorded fail status;
it must never be reached by falling through from an unmeasured case.

``tool_call`` transitions (#1006/#1023 — every one involving it is LOUD
except the recorded steady state):
    * run tool_call + baseline tool_call  → ``known_tool_calls`` (recorded
      steady state — the one silent-exit-code path, still listed);
    * run tool_call + any other baseline  → REGRESSION (behaviour changed,
      or a first measurement discovered a tool case — record deliberately
      or redesign the case; never silence by default);
    * run PASS + baseline tool_call       → IMPROVEMENT (now answers
      directly and correctly);
    * run FAIL + baseline tool_call       → REGRESSION via the allowlist
      (``tool_call`` is not in ``_RECORDED_FAILING``, so it can never
      absorb a real failure into ``known_failures``).
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.types import CaseStatus, SuiteReport

BASELINE_DIR: Path = Path(__file__).parent / "baselines"

_FAILING = {CaseStatus.FAIL, CaseStatus.ERROR}

#: The ONLY baseline values that may absorb a failing case into
#: ``known_failures`` (#1000).  An allowlist, deliberately: any value not
#: named here — including one added by a future ``CaseStatus`` member — is a
#: regression, so a new status cannot inherit silence by default.
_RECORDED_FAILING = frozenset(
    {CaseStatus.FAIL.value, CaseStatus.ERROR.value}
)

#: Sentinel distinguishing "case absent from the baseline" from "case
#: present with a null (or otherwise malformed) value" (#1010).
#: ``dict.get``'s None default conflates the two, and they earn different
#: regression messages.
_ABSENT = object()


class BaselineError(Exception):
    """A baseline file is missing or malformed (harness error, exit 2)."""


@dataclass
class Comparison:
    """Result of comparing a suite run against its committed baseline."""

    suite: str
    regressions: list[str] = field(default_factory=list)
    improvements: list[str] = field(default_factory=list)
    known_failures: list[str] = field(default_factory=list)
    known_tool_calls: list[str] = field(default_factory=list)

    @property
    def has_regressions(self) -> bool:
        return bool(self.regressions)

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite": self.suite,
            "has_regressions": self.has_regressions,
            "regressions": list(self.regressions),
            "improvements": list(self.improvements),
            "known_failures": list(self.known_failures),
            "known_tool_calls": list(self.known_tool_calls),
        }


def _resolve_git_sha() -> str:
    """Best-effort short git SHA for baseline provenance."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
            cwd=Path(__file__).parent,
        ).strip()
    except Exception:  # noqa: BLE001 — provenance only, never load-bearing
        return "unknown"


def baseline_path(suite: str, baseline_dir: Path = BASELINE_DIR) -> Path:
    return baseline_dir / f"{suite}.json"


def write_baseline(
    report: SuiteReport, baseline_dir: Path = BASELINE_DIR
) -> Path:
    """Write (or refresh) the committed baseline for a suite.

    Hardware-skipped cases are stored with their skipped status so the
    baseline documents which cases are model-in-the-loop, but they are
    never compared.

    Returns:
        Path to the written baseline file.
    """
    baseline_dir.mkdir(parents=True, exist_ok=True)
    path = baseline_path(report.suite, baseline_dir)
    payload: dict[str, Any] = {
        "suite": report.suite,
        "git_sha": _resolve_git_sha(),
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "aggregates": report.aggregates(),
        "cases": report.case_statuses(),
    }
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


def load_baseline(
    suite: str, baseline_dir: Path = BASELINE_DIR
) -> dict[str, Any]:
    """Load and validate the committed baseline for a suite.

    Raises:
        BaselineError: If the baseline file is missing or malformed.
    """
    path = baseline_path(suite, baseline_dir)
    if not path.exists():
        raise BaselineError(
            f"No committed baseline for suite '{suite}' at {path}. "
            f"Generate one with: python -m evals.run --suite {suite} "
            f"--write-baseline"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BaselineError(f"Baseline {path} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict) or "cases" not in payload:
        raise BaselineError(f"Baseline {path} is missing the 'cases' block")
    cases = payload["cases"]
    if not isinstance(cases, dict):
        raise BaselineError(f"Baseline {path} 'cases' must be an object")
    # #1000: every status must be a scalar string.  A malformed baseline is a
    # HARNESS error (exit 2), never a regression (exit 1) — the two exit codes
    # mean different things and an operator acts on them differently.  Without
    # this, a hand-edit or a botched conflict resolution leaving a list/dict
    # value reaches ``compare``'s set-membership test and dies with an
    # unhandled TypeError, which the interpreter surfaces as exit 1 — a
    # malformed baseline wearing a regression's exit code.
    bad = sorted(
        case_id for case_id, status in cases.items()
        if not isinstance(status, str)
    )
    if bad:
        raise BaselineError(
            f"Baseline {path} has non-string case statuses for: "
            f"{', '.join(bad)} — each 'cases' value must be a status string"
        )
    return payload


def compare(
    report: SuiteReport, baseline: dict[str, Any]
) -> Comparison:
    """Compare a suite run against its baseline (see module docstring).

    Validates its own inputs (#1010): ``compare`` takes a plain dict, so
    nothing obliges a caller to have come through ``load_baseline``.  A
    baseline whose ``cases`` block is not an object is one big unreadable
    claim — reported as a single regression, with nothing compared.  A
    non-string case status is malformed — a failing case with one becomes
    a regression, never a ``known_failures`` entry, never a raw
    ``TypeError``.  ``load_baseline`` still rejects both shapes in
    committed files as a harness error (exit 2) before they reach here.
    """
    comparison = Comparison(suite=report.suite)

    # #1010: structural validation before anything is compared.  A malformed
    # ``cases`` value used to raise an unhashable-type TypeError out of the
    # set-membership test below — a crash held closed only by every caller
    # happening to route through ``load_baseline``.  Fail the COMPARISON
    # loudly instead: silence against a baseline that cannot be read is
    # indistinguishable from "compared and found clean".
    cases_block = (
        baseline.get("cases", {}) if isinstance(baseline, dict) else baseline
    )
    if not isinstance(cases_block, dict):
        comparison.regressions.append(
            f"malformed baseline: no 'cases' object could be read "
            f"(got {type(cases_block).__name__}) — nothing was compared. "
            f"Regenerate the baseline with --write-baseline."
        )
        return comparison
    baseline_cases: dict[str, Any] = dict(cases_block)

    run_ids: set[str] = set()
    for result in report.results:
        run_ids.add(result.case_id)
        if result.status is CaseStatus.SKIPPED_HARDWARE:
            continue
        base_status = baseline_cases.get(result.case_id, _ABSENT)
        if result.status in _FAILING:
            # #1000: ALLOWLIST, not blocklist.  ``known_failures`` is reached
            # only from a baseline that RECORDED a failure; every other
            # baseline value — absent, pass, skipped_hardware, a hand-edit
            # typo, a CaseStatus member that does not exist yet, or a
            # non-string value (#1010) — is a regression.  The previous
            # "known regression shapes, else benign" form let a
            # skipped_hardware baseline absorb a real failure, which is how
            # 3 of 4 injection-resistance cases failed at exit 0 on
            # 2026-07-07; the same shape would have absorbed a mistyped
            # ``"passed"`` just as silently.
            if isinstance(base_status, str) and base_status in _RECORDED_FAILING:
                comparison.known_failures.append(result.case_id)
            elif base_status is _ABSENT:
                comparison.regressions.append(
                    f"new failing case not in baseline: {result.case_id} "
                    f"({result.status.value}: {result.detail or 'mismatch'})"
                )
            elif not isinstance(base_status, str):
                # #1010: present but not a status string (null, list, dict,
                # number …).  Distinct from absent — ``dict.get``'s None
                # default used to conflate ``{"case": null}`` with a
                # missing id.
                comparison.regressions.append(
                    f"malformed baseline value: {result.case_id} "
                    f"(baseline holds {base_status!r}, not a status string "
                    f"-> {result.status.value}: {result.detail or 'mismatch'}). "
                    f"Regenerate the baseline with --write-baseline."
                )
            elif base_status == CaseStatus.PASS.value:
                comparison.regressions.append(
                    f"regressed vs baseline: {result.case_id} "
                    f"(baseline pass -> {result.status.value}: "
                    f"{result.detail or 'mismatch'})"
                )
            else:
                comparison.regressions.append(
                    f"unbaselined failure: {result.case_id} "
                    f"(baseline recorded {base_status!r} — never measured as "
                    f"passing or failing — -> {result.status.value}: "
                    f"{result.detail or 'mismatch'}). If this is a real "
                    f"deficiency, record it deliberately; if the harness "
                    f"could not RUN the case, fix the wiring — do not "
                    f"baseline around it."
                )
        elif result.status is CaseStatus.TOOL_CALL:
            # #1006: a tool-call answer is reached-but-unscorable one-shot.
            # The ONLY silent path is the recorded steady state; every other
            # baseline value is loud — a new status must not inherit silence
            # (the same principle as _RECORDED_FAILING, applied symmetrically).
            if isinstance(base_status, str) and base_status == (
                CaseStatus.TOOL_CALL.value
            ):
                comparison.known_tool_calls.append(result.case_id)
            elif base_status is _ABSENT:
                comparison.regressions.append(
                    f"new tool-call case not in baseline: {result.case_id} "
                    f"({result.detail or 'tool-call answer'}). Record it "
                    f"deliberately with --write-baseline, or score it via "
                    f"the tool-following eval when that lands (#1023)."
                )
            else:
                comparison.regressions.append(
                    f"case now answers with a tool call: {result.case_id} "
                    f"(baseline {base_status!r} -> tool_call: "
                    f"{result.detail or 'tool-call answer'}). The one-shot "
                    f"harness cannot execute tools (#1023) — record it "
                    f"deliberately with --write-baseline, or redesign the "
                    f"case; do not let it pass silently."
                )
        elif result.status is CaseStatus.PASS and base_status in (
            CaseStatus.FAIL.value,
            CaseStatus.ERROR.value,
            CaseStatus.TOOL_CALL.value,
        ):
            comparison.improvements.append(result.case_id)

    # A baselined case that vanished from the run — the golden set shrank
    # (or an id was renamed) without a conscious baseline refresh.
    for case_id, base_status in baseline_cases.items():
        if case_id not in run_ids and base_status != (
            CaseStatus.SKIPPED_HARDWARE.value
        ):
            comparison.regressions.append(
                f"baselined case missing from run: {case_id}"
            )

    return comparison
