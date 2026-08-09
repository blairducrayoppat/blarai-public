"""#827 QUALITY-9 — the standing failure-taxonomy classifier (DETERMINISTIC, advisory).

The 2026-07-11 hand-analysis (``docs/handoffs/failure-taxonomy-20260711.md``) ranked
where coding-outcome quality is actually lost across two overnight battery runs. That
was a one-off. This module makes it a STANDING instrument: at battery close it stamps
every scorecard with an ADVISORY ``failure_class`` (non-GREEN) or ``green_class``
(GREEN) plus the matched fingerprint, and the ``battery-summary`` carries the per-class
counts and the night-over-night trend (the program's KPI line —
``"oracle-defect parks: n2=3 -> n3=?"``).

Design invariants (all load-bearing):

* **DETERMINISTIC** — structured-fingerprint / regex match, NEVER a model in the loop
  (the small-model principle, c.1721). The taxonomy's big classes pattern-match on
  evidence the run already emits.
* **ADVISORY-LOCKED** — the classifier NEVER changes a verdict or attribution; it writes
  ONLY to the reserved evidence keys below. A classifier that fed banking would be a new
  FALSE-DONE vector (the b5class honesty discipline). :func:`classify_and_stamp` asserts
  the verdict/attribution are byte-identical before and after, and restores + flags if a
  future edit ever violates this.
* **POSITIVE CONTROL** — the 9 hand-classified job-instances are fixtures the classifier
  must reproduce (lesson 222: a verdict-issuing instrument needs a proven yes/known
  answer before its classes are believed). See ``test_failure_taxonomy.py``.
* **HONEST RESIDUE** — ``UNCLASSIFIED`` is a real class, and its rate is the instrument's
  own health metric: a rising UNCLASSIFIED share means a NEW leak class the taxonomy has
  not learned yet, surfaced in the summary, never silent.

Evidence consumed (every read is fail-soft — a missing/broken signal is skipped, never
fatal, and only ever downgrades a card toward ``UNCLASSIFIED``):

* the scorecard's own ``evidence`` — ``oracle_status`` / ``mode`` / ``design_review`` +
  ``attribution`` / ``notes``;
* ``<run>/oracle-qa.json``            (#821) — the validation-class finding counts,
  ``oracle_coverage`` k/n, covered/uncovered criteria, f2p baseline, regeneration;
* ``<run>/decompose-diagnostics.json`` (#824) — the why-flat fingerprint;
* ``<run>/import-probe-verdict.json`` + ``import-probe.log`` (#822) — the named
  unresolved import seam;
* bounded raw-log text (``JOB_SUMMARY.txt`` / ``swap-progress.log`` /
  ``run-fleet-*.log`` / ``design-critique.log``) — the fallback signature for FLAT runs
  that have no job-oracle sidecar (B1's per-task Hypothesis strategy defect lives ONLY
  here) and for robustness when structured evidence is absent.

The GREEN-side classification (the c.1735 amendment) consumes ``oracle_coverage`` +
covered/uncovered from #821 and the OPTIONAL #832 gaming fingerprint / #837 green-audit
band once those land — so the nightly trend also carries GREEN-quality drift (the
r4greens finding: a GREEN that banked partially-verified, measured degrading across three
flat-GREEN nights). Coverage-disclosure ownership is JOINT with #832.
"""

from __future__ import annotations

import json
import re
from math import isfinite
from pathlib import Path
from typing import Optional

from tools.dispatch_harness.scorecard import (
    ATTRIBUTION_HARNESS,
    Scorecard,
    VERDICT_GREEN,
)

# ---------------------------------------------------------------------------
# The taxonomy (the big classes from the hand-analysis + the honest residue)
# ---------------------------------------------------------------------------

#: The auto-generated job/task oracle is itself wrong or unpassable — a correct
#: implementation cannot pass it (B1 both nights, B4-n2). The largest, rising share.
CLASS_ORACLE_DEFECT = "ORACLE-DEFECT"
#: The import / module-layout contract between merged tasks and the oracle is unmet —
#: a ModuleNotFoundError / ERR_MODULE_NOT_FOUND on a contract entry (B4-n1, B6, B7-n1).
CLASS_INTEGRATION_SEAM = "INTEGRATION-SEAM"
#: The web design/verify loop is pixel-only and cannot see the runtime error — the
#: reviewer quotes the bug string and calls it cosmetic, the cap is hit (B5-n2).
CLASS_BLIND_FIX_LOOP = "BLIND-FIX-LOOP"
#: The plan under-decomposed to <2 tasks and dropped to flat mode, which skips the job
#: oracle entirely — structurally caps the job at "can never be GREEN" (B1, B5 flat).
CLASS_DECOMPOSE_DOWNGRADE = "DECOMPOSE-DOWNGRADE"
#: The run genuinely EXHAUSTED its time budget — measured, not inferred: elapsed reached
#: the card's ``run_budget_s``, or a kill marker (TIMEOUT / tree-kill) is in the log.
#:
#: #1324: this class used to fire on the HARNESS attribution ALONE, reading neither
#: elapsed nor budget, so every environment fault was filed as budget exhaustion. Measured
#: instances of the SAME label: 49% of budget, 102% of budget (PERFORMANCE_LOG.md:3167),
#: and 255.97 s of a 28,800 s budget — **nine-tenths of one percent** — on 2026-08-07,
#: where the real cause was the Assistant Orchestrator being shut down mid-run.
#:
#: The harm is the COUNTER, not the wording. ``failure-taxonomy: HARNESS-BUDGET n`` is
#: exactly the evidence a later session counts to argue that web cards are budget-starved,
#: so a mislabel does not sit still — it becomes someone else's premise.
CLASS_HARNESS_BUDGET = "HARNESS-BUDGET"
#: A terminal environment / runner fault that is NOT budget exhaustion — the service went
#: away, the GPU never initialised, the harness crashed. Same HARNESS attribution, entirely
#: different cure: WAIT and re-run helps a budget fault and does nothing for this one.
#: Deny-by-default applied to labelling: a HARNESS fault lands here unless there is
#: POSITIVE evidence of budget exhaustion.
CLASS_HARNESS_ENVIRONMENT = "HARNESS-ENVIRONMENT"
#: The honest residue — no known fingerprint matched. A RISING unclassified rate is the
#: instrument telling us the taxonomy needs a human pass (a NEW leak class). Never silent.
CLASS_UNCLASSIFIED = "UNCLASSIFIED"

#: Every failure class, in a stable order (so the count map always carries the full
#: taxonomy — even the classes that did not fire tonight — for a stable summary shape).
#: HARNESS-ENVIRONMENT is APPENDED after HARNESS-BUDGET rather than inserted, so the
#: historical column order of every prior report is unchanged.
FAILURE_CLASSES: tuple[str, ...] = (
    CLASS_ORACLE_DEFECT,
    CLASS_INTEGRATION_SEAM,
    CLASS_BLIND_FIX_LOOP,
    CLASS_DECOMPOSE_DOWNGRADE,
    CLASS_HARNESS_BUDGET,
    CLASS_HARNESS_ENVIRONMENT,
    CLASS_UNCLASSIFIED,
)

# ---------------------------------------------------------------------------
# The GREEN-side classes (c.1735 — nobody was measuring what a GREEN actually PROVED)
# ---------------------------------------------------------------------------

#: A GREEN whose oracle coverage is complete (k == n over the test-tier criteria) and
#: carries no gaming fingerprint — the honest, fully-proven win.
CLASS_GREEN_VERIFIED = "GREEN-VERIFIED"
#: A GREEN that banked with PARTIAL oracle coverage (k < n — some test-tier criteria have
#: no verified assertion). The r4greens leniency-drift class: it banks but says so.
CLASS_GREEN_PARTIAL = "GREEN-PARTIAL"
#: A GREEN with NO coverage disclosure (unknown/zero) — we cannot say what it proved
#: (the B2 "no-crash criterion banked unverified three times" shape). The most concerning.
CLASS_GREEN_UNVERIFIED = "GREEN-UNVERIFIED"
#: A GREEN a detector flagged as gamed (#832 fingerprint / #837 green-audit band). Wired
#: as an OPTIONAL hook — inert until those instruments land; never a false positive absent.
CLASS_GREEN_GAMED = "GREEN-GAMED"

GREEN_CLASSES: tuple[str, ...] = (
    CLASS_GREEN_VERIFIED,
    CLASS_GREEN_PARTIAL,
    CLASS_GREEN_UNVERIFIED,
    CLASS_GREEN_GAMED,
)

TAXONOMY_SCHEMA = "failure-taxonomy/v1"

#: Reserved evidence keys the classifier is the SOLE writer of (the advisory stamp). No
#: other producer writes these; the classifier writes nothing else.
EV_FAILURE_CLASS = "failure_class"
EV_FAILURE_FINGERPRINT = "failure_fingerprint"
EV_GREEN_CLASS = "green_class"
EV_GREEN_FINGERPRINT = "green_fingerprint"

#: A single fingerprint is a POINTER + short status (scorecard S6 discipline): one line,
#: capped well under the evidence 1000-char ceiling.
_FINGERPRINT_CAP = 300
#: Per-file and total raw-log read ceilings (bounded, fail-soft — a log scan must never
#: dominate battery close nor OOM on a pathological run dir).
_LOG_FILE_CAP_BYTES = 256 * 1024
_LOG_TOTAL_CAP_BYTES = 2 * 1024 * 1024
_MAX_RUN_FLEET_LOGS = 24

# ---------------------------------------------------------------------------
# Raw-log fingerprints (the FALLBACK layer — structured sidecars are matched first)
# ---------------------------------------------------------------------------

#: ORACLE-DEFECT: the oracle's OWN error (a strategy-authoring bug, an ill-posed property,
#: an interactive read under pytest) — deliberately TIGHT so it never fires on a coder's
#: honest RED. A missing-module error is NOT here (that is the integration seam).
_ORACLE_DEFECT_LOG: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"got an unexpected keyword argument '(?:min_length|max_length|min_size|max_size|alphabet)'"),
     "hypothesis strategy kwarg error (oracle authoring bug)"),
    (re.compile(r"Falsifying example"),
     "hypothesis falsifying example (ill-posed strategy feeds spec-invalid input)"),
    (re.compile(r"OSError: pytest: reading from stdin while output is captured"),
     "oracle drives interactive stdin under pytest (can never pass)"),
)

#: INTEGRATION-SEAM: a module the oracle imports is not where it was built (the exact
#: B4/B6/B7 park). The capture group names the unresolved entry for the fingerprint.
_SEAM_LOG: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"ModuleNotFoundError: No module named ['\"]([\w.]+)['\"]"),
     "ModuleNotFoundError"),
    (re.compile(r"ERR_MODULE_NOT_FOUND"), "ERR_MODULE_NOT_FOUND (node)"),
    (re.compile(r"Cannot find module ['\"]?([^'\"\n]+)"), "cannot find module (node)"),
)

#: POSITIVE evidence that a run was KILLED for time. Only these two markers qualify: both
#: describe an actual kill, not a mention of budgets.
#:
#: #1324: ``run[_ ]budget|swap_run_budget`` used to live here as "run-budget kill" and was
#: REMOVED, because the nightly launcher prints a routine budget-coherence block
#: (``default swap_run_budget_s = 10,800s``) on EVERY run. Any log carrying that ordinary
#: bookkeeping matched, so a healthy run that failed for an unrelated reason read as a
#: budget kill. A pattern that matches the log's own furniture is not evidence.
_HARNESS_KILL_LOG: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bTIMEOUT\b"), "TIMEOUT (budget kill)"),
    (re.compile(r"tree[- ]kill"), "tree-kill"),
)

#: A terminal harness fault with no claim about its cause. Deliberately does NOT include
#: the coder idle circuit-breaker — an idle coder is a BUILD/capability event, not a
#: harness fault (the hand-analysis is explicit that B4/B6's idle tasks were not the
#: terminal cause), so it must fall through to the honest residue rather than mislabel.
_HARNESS_LOG: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bTIMEOUT\b"), "TIMEOUT (budget kill)"),
    (re.compile(r"tree[- ]kill"), "tree-kill"),
    (re.compile(r"harness exception"), "harness exception"),
)

#: The oracle-QA finding classes (#821) that constitute an ORACLE-DEFECT. ``import_contract``
#: is deliberately EXCLUDED — an oracle importing beyond the declared contract is the
#: integration seam's authoring twin, routed to INTEGRATION-SEAM below. ``traceability_gap``
#: is a SOFT coverage disclosure (GREEN-side), not a hard oracle defect.
_ORACLE_DEFECT_FINDINGS: tuple[str, ...] = (
    "collectability",
    "strategy_illposed",
    "interactive_io",
    "invented_contract",
    "adequacy_floor",
    "f2p_vacuous",
    "regenerate_exhausted",
)


# ---------------------------------------------------------------------------
# Evidence loading (fail-soft; all optional)
# ---------------------------------------------------------------------------


def _read_json(path: Path) -> Optional[dict]:
    """A run-dir sidecar as a dict, or ``None`` (absent / unreadable / not-an-object).
    Never raises — an unreadable signal is simply skipped."""
    try:
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _read_logs(run_dir: Path) -> str:
    """Concatenated, BOUNDED raw-log text for the regex fallback. A fixed set of evidence
    files plus the per-task ``run-fleet-*.log`` (the only place a FLAT run's per-task
    oracle defect surfaces). Fail-soft and capped: never dominates battery close."""
    out: list[str] = []
    total = 0
    names = ["JOB_SUMMARY.txt", "swap-progress.log", "design-critique.log", "import-probe.log"]
    try:
        fleet_logs = sorted(run_dir.glob("run-fleet-*.log"))[:_MAX_RUN_FLEET_LOGS]
    except OSError:
        fleet_logs = []
    for path in [run_dir / n for n in names] + fleet_logs:
        if total >= _LOG_TOTAL_CAP_BYTES:
            break
        try:
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")[:_LOG_FILE_CAP_BYTES]
        except OSError:
            continue
        out.append(text)
        total += len(text)
    return "\n".join(out)


class _Context:
    """The evidence bundle for one scorecard — the structured sidecars + bounded log text.
    Constructed once per card at battery close; every field is optional/fail-soft."""

    __slots__ = ("oracle_qa", "decompose", "import_probe", "logs", "green_audit",
                 "traceability")

    def __init__(
        self,
        *,
        oracle_qa: Optional[dict] = None,
        decompose: Optional[dict] = None,
        import_probe: Optional[dict] = None,
        green_audit: Optional[dict] = None,
        traceability: Optional[dict] = None,
        logs: str = "",
    ) -> None:
        self.oracle_qa = oracle_qa
        self.decompose = decompose
        self.import_probe = import_probe
        self.green_audit = green_audit
        self.traceability = traceability
        self.logs = logs or ""


def load_context(runs_dir: "str | Path | None", run_id: str) -> _Context:
    """Load one card's evidence bundle from ``<runs_dir>/<run_id>/``. An empty bundle
    (no runs_dir / no run_id / a missing dir) is valid — classification then falls back
    to the scorecard's own evidence only (the dry-run / unit-test shape)."""
    if not runs_dir or not run_id:
        return _Context()
    run_dir = Path(runs_dir) / run_id
    if not run_dir.is_dir():
        return _Context()
    return _Context(
        oracle_qa=_read_json(run_dir / "oracle-qa.json"),
        decompose=_read_json(run_dir / "decompose-diagnostics.json"),
        import_probe=_read_json(run_dir / "import-probe-verdict.json"),
        # #832 / #837 seam: an OPTIONAL green-audit sidecar. Inert until those land.
        green_audit=_read_json(run_dir / "green-audit.json"),
        # The DETERMINISTIC requirement->assertion traceability block. Same optional-sidecar
        # pattern; absent means classify_green falls back to the #821 declaration exactly as
        # before.
        traceability=_read_json(run_dir / "traceability.json"),
        logs=_read_logs(run_dir),
    )


def _first_log_match(
    text: str, patterns: "tuple[tuple[re.Pattern[str], str], ...]"
) -> Optional[str]:
    """The fingerprint for the first pattern that matches *text*, or ``None``. A capture
    group (the named module) is appended so the fingerprint points at the exact entry."""
    for rx, label in patterns:
        m = rx.search(text)
        if m:
            captured = ""
            if m.groups():
                grabbed = next((g for g in m.groups() if g), "")
                captured = f" '{grabbed}'" if grabbed else ""
            return f"log: {label}{captured}"
    return None


# ---------------------------------------------------------------------------
# The rules (priority order — FIRST match wins; see classify_failure)
# ---------------------------------------------------------------------------


def _rule_oracle_defect(ev: dict, ctx: _Context) -> Optional[str]:
    """The oracle itself is wrong/unpassable. Structured (#821) first, then the tight
    log fallback (a FLAT run's per-task oracle defect has no job-oracle sidecar)."""
    qa = ctx.oracle_qa
    if qa:
        findings = qa.get("findings") or {}
        hits = [c for c in _ORACLE_DEFECT_FINDINGS if int(findings.get(c, 0) or 0) > 0]
        if str(qa.get("verdict")) == "refuse":
            return "oracle-qa verdict=refuse (" + (",".join(hits) or "hard residual") + ")"
        if (qa.get("regeneration") or {}).get("exhausted"):
            return "oracle-qa regeneration exhausted (chronically-defective oracle)"
        if str(qa.get("f2p_baseline") or "").startswith("vacuous"):
            return f"oracle-qa f2p_baseline={qa.get('f2p_baseline')} (passes on skeleton)"
        if hits:
            return "oracle-qa findings: " + ",".join(hits)
    return _first_log_match(ctx.logs, _ORACLE_DEFECT_LOG)


def _rule_integration_seam(ev: dict, ctx: _Context) -> Optional[str]:
    """A contract module is not where the oracle imports it. Structured (#822/#821)
    first, then the ModuleNotFoundError / ERR_MODULE_NOT_FOUND log fallback."""
    probe = ctx.import_probe
    if probe and probe.get("ok") is False:
        unresolved = probe.get("unresolved") or []
        names = ",".join(str(u.get("module", "")) for u in unresolved[:5] if isinstance(u, dict))
        return f"import-probe unresolved: {names or 'contract entry'}"
    qa = ctx.oracle_qa
    if qa and int((qa.get("findings") or {}).get("import_contract", 0) or 0) > 0:
        return "oracle-qa import_contract finding (oracle imports beyond the plan contract)"
    if "ok=False" in ctx.logs and "import-probe" in ctx.logs:
        return "import-probe.log: unresolved import contract"
    return _first_log_match(ctx.logs, _SEAM_LOG)


def _rule_blind_fix_loop(ev: dict, ctx: _Context) -> Optional[str]:
    """The pixel-only design/verify loop hit its cap while still unhappy. The scorecard's
    ``design_review == "cap-reached"`` stamp is the primary signal (#740). A design-loop
    console-error sidecar (#823) is consumed if present — inert until it lands."""
    if str(ev.get("design_review")) == "cap-reached":
        return "design-review cap-reached (reviewer still requesting changes)"
    # #823 seam (inert until it lands): a design-loop record that names a runtime/console
    # error the pixel-only critic missed. A ``console_errors`` count on the scorecard
    # evidence surfaces the blind-fix loop even when the design review ended "clean".
    if int(ev.get("design_console_errors", 0) or 0) > 0:  # pragma: no cover — #823 hook
        return "design-loop console error unaddressed (pixel critic blind to runtime)"
    return None


#: Elapsed/budget ratio at or above which a run is called EXHAUSTED. Not 1.0: a run killed
#: at its ceiling rarely records the last fraction of a second, and the two measured real
#: instances sit at 49% and 102% — nowhere near this boundary, which is the point. The
#: threshold exists to be unambiguous, not to adjudicate close calls.
_BUDGET_EXHAUSTED_FRACTION = 0.95


def _budget_reading(sc: Scorecard, ev: dict) -> tuple[Optional[float], float, Optional[float]]:
    """``(budget_s, elapsed_s, fraction)``. ``budget_s``/``fraction`` are ``None`` when the
    card's budget was not recorded on this scorecard — the honest state for every scorecard
    written before #1324, and the reason this returns a tri-state instead of defaulting."""
    elapsed = float(getattr(sc, "wall_clock_s", 0.0) or 0.0)
    raw = ev.get("run_budget_s")
    try:
        budget = float(raw) if raw is not None else 0.0
    except (TypeError, ValueError):
        budget = 0.0
    # `isfinite` and not just `> 0`: NaN fails EVERY comparison, so a bare `budget <= 0.0`
    # lets it through as a valid budget and it then renders as "of nans (nan%)" — a
    # number-shaped non-number in the fingerprint, which is the one place this ticket
    # cannot afford one. Non-finite is unmeasured, which is the truth about it.
    if not isfinite(budget) or budget <= 0.0:
        return (None, elapsed, None)
    return (budget, elapsed, elapsed / budget)


def _rule_harness_budget(sc: Scorecard, ev: dict, attribution: str, ctx: _Context) -> Optional[str]:
    """The run EXHAUSTED its time budget — claimed only on POSITIVE evidence.

    #1324. This used to return BUDGET on ``attribution == HARNESS`` alone, reading neither
    elapsed nor budget, so every environment fault was filed as budget exhaustion. It is
    now a measurement: the elapsed/budget ratio, or a kill marker that describes an actual
    kill. Absent both, the fault is real but its cause is NOT budget, and it belongs to
    HARNESS-ENVIRONMENT below.

    Deny-by-default, applied to labelling: an UNKNOWN budget is not a satisfied one. A
    scorecard with no ``run_budget_s`` cannot support this claim and does not get it.
    """
    kill = _first_log_match(ctx.logs, _HARNESS_KILL_LOG)
    if attribution != ATTRIBUTION_HARNESS and not kill:
        return None
    budget, elapsed, frac = _budget_reading(sc, ev)
    if frac is not None and frac >= _BUDGET_EXHAUSTED_FRACTION:
        return f"budget exhausted: elapsed {elapsed:.0f}s of {budget:.0f}s ({frac:.0%})"
    if kill:
        measured = (f"elapsed {elapsed:.0f}s of {budget:.0f}s ({frac:.0%})"
                    if frac is not None else f"elapsed {elapsed:.0f}s, budget unmeasured")
        return f"{kill}; {measured}"
    return None


def _rule_harness_environment(sc: Scorecard, ev: dict, attribution: str, ctx: _Context) -> Optional[str]:
    """A terminal environment/runner fault that is NOT budget exhaustion — the service went
    away, the GPU never initialised, the harness crashed. Ranked immediately below
    HARNESS-BUDGET so it takes everything the HARNESS ATTRIBUTION used to hand to it.

    COVERAGE, stated exactly rather than generously. For an ``attribution == HARNESS``
    card the two harness classes cover precisely what the single old class covered, and
    nothing moves to UNCLASSIFIED. For a NON-HARNESS card the old rule could still reach
    HARNESS-BUDGET through ``_HARNESS_LOG``, which then contained
    ``run[_ ]budget|swap_run_budget``; that pattern is deleted (it matched the launcher's
    routine budget-coherence block, i.e. the log's own furniture), so a non-HARNESS card
    whose log merely MENTIONS a budget now **falls through the harness rules** instead of
    being labelled a budget kill. Where it lands then depends on the rules below: ``flat``
    mode reaches DECOMPOSE-DOWNGRADE, otherwise UNCLASSIFIED. **That is a deliberate
    behaviour change, not an oversight**, and it is pinned by a test — a wrong class is
    worse than an honest "no fingerprint matched", and UNCLASSIFIED is designed to be the
    residue.

    Reachability is CONDITIONAL, deliberately not dated: this path opens only if that
    string enters a log the classifier actually scans, and a real kill prints ``TIMEOUT``,
    which ``_HARNESS_KILL_LOG`` catches. How many scanned logs contain it *today* is a
    measurement, and it lives on #1324 — a docstring that dates its own evidence rots into
    a false assertion the first time the world moves, and this one would have pointed at a
    path in another repository that a reader here cannot check.

    The fingerprint always carries the NUMBERS, so the label can be checked rather than
    believed — the whole point of #1324."""
    if attribution != ATTRIBUTION_HARNESS:
        return _first_log_match(ctx.logs, _HARNESS_LOG)
    budget, elapsed, frac = _budget_reading(sc, ev)
    if frac is not None:
        return (f"attribution=HARNESS; elapsed {elapsed:.0f}s of {budget:.0f}s ({frac:.0%}) "
                f"- NOT budget exhaustion")
    return (f"attribution=HARNESS; elapsed {elapsed:.0f}s, budget unmeasured "
            f"(no run_budget_s on this scorecard) - budget exhaustion NOT established")


def _rule_decompose_downgrade(ev: dict, ctx: _Context) -> Optional[str]:
    """The plan under-decomposed to <2 tasks and dropped to flat mode (no job oracle).
    Checked AFTER the more specific classes so a flat run with a broken oracle (B1) or a
    capped design loop (B5-n2) attributes to its terminal cause, not merely to the mode."""
    mode = str(ev.get("mode") or "")
    dc = ctx.decompose
    dc_mode = str(dc.get("mode") or "") if dc else ""
    if mode == "flat" or dc_mode == "flat":
        reason = str(dc.get("flat_reason") or "") if dc else ""
        return "mode=flat" + (f" (flat_reason={reason})" if reason else " (no job oracle)")
    return None


def classify_failure(sc: Scorecard, ctx: _Context) -> tuple[str, str]:
    """Classify one NON-GREEN scorecard: ``(failure_class, fingerprint)``. Priority order,
    first match wins — ORACLE-DEFECT and INTEGRATION-SEAM (the grading/integration
    machinery) rank above DECOMPOSE-DOWNGRADE (the mode) so a flat run with a broken
    oracle is scored on its terminal cause, exactly as the hand-analysis ranked B1/B5."""
    ev = sc.evidence or {}
    attribution = sc.attribution or ""
    for klass, rule in (
        (CLASS_ORACLE_DEFECT, lambda: _rule_oracle_defect(ev, ctx)),
        (CLASS_INTEGRATION_SEAM, lambda: _rule_integration_seam(ev, ctx)),
        (CLASS_BLIND_FIX_LOOP, lambda: _rule_blind_fix_loop(ev, ctx)),
        # #1324: BUDGET before ENVIRONMENT — the specific claim is tried first and must
        # earn itself on measured evidence; ENVIRONMENT then takes the rest of what the
        # HARNESS ATTRIBUTION used to hand to BUDGET unexamined. For an attribution=HARNESS
        # card the two together cover exactly the old class's ground. For a NON-HARNESS card
        # they do NOT — see _rule_harness_environment's docstring for the one shape that now
        # falls to UNCLASSIFIED, and why that is the right answer rather than a leak.
        (CLASS_HARNESS_BUDGET, lambda: _rule_harness_budget(sc, ev, attribution, ctx)),
        (CLASS_HARNESS_ENVIRONMENT, lambda: _rule_harness_environment(sc, ev, attribution, ctx)),
        (CLASS_DECOMPOSE_DOWNGRADE, lambda: _rule_decompose_downgrade(ev, ctx)),
    ):
        fingerprint = rule()
        if fingerprint:
            return (klass, fingerprint)
    return (CLASS_UNCLASSIFIED, "no known fingerprint matched (candidate new leak class)")


def _parse_fraction(text: str) -> tuple[Optional[int], Optional[int]]:
    """``"k/n"`` -> ``(k, n)``; anything else -> ``(None, None)``."""
    m = re.match(r"^\s*(\d+)\s*/\s*(\d+)\s*$", str(text))
    if not m:
        return (None, None)
    return (int(m.group(1)), int(m.group(2)))


def _gaming_signal(ev: dict, ctx: _Context) -> Optional[str]:
    """The OPTIONAL #832 gaming fingerprint / #837 green-audit band. Reads a ``gamed`` /
    ``suspect`` flag from an evidence key or the green-audit sidecar. Returns ``None``
    (never a false positive) until those instruments land — the documented wire-in seam."""
    for source in (ev, ctx.green_audit or {}):
        if not isinstance(source, dict):
            continue
        if source.get("gamed") is True or str(source.get("green_audit") or "") == "gamed":
            reason = str(source.get("gaming_reason") or source.get("reason") or "flagged")
            return f"green-audit: gamed ({reason})"
    return None


def classify_green(sc: Scorecard, ctx: _Context) -> tuple[str, str]:
    """Classify one GREEN scorecard by what it actually PROVED (c.1735): full coverage ->
    VERIFIED, partial -> PARTIAL (the leniency-drift class), unknown/zero -> UNVERIFIED,
    a gaming fingerprint -> GAMED. A GREEN with no #821 coverage stamp reads UNVERIFIED —
    we cannot say what it proved (the B2 'no-crash banked unverified' shape)."""
    ev = sc.evidence or {}
    gamed = _gaming_signal(ev, ctx)
    if gamed:
        return (CLASS_GREEN_GAMED, gamed)
    # The DETERMINISTIC traceability block WINS over the #821 declaration when present: the
    # latter is a 14B assertion that a test covers a criterion, the former is AST evidence
    # about the oracle itself. Its own rule decides VERIFIED (notably: anything undecidable
    # blocks it), so a coverage figure that cannot be determined can never read as a pass.
    trace = ctx.traceability
    if isinstance(trace, dict) and "verified_class" in trace:
        fingerprint = str(trace.get("fingerprint") or "oracle_coverage=unavailable")
        if not trace.get("available"):
            return (CLASS_GREEN_UNVERIFIED, fingerprint)
        if trace.get("verified_class"):
            return (CLASS_GREEN_VERIFIED, fingerprint)
        # PARTIAL means "some of it was proven". A block that verified NOTHING proved nothing,
        # whatever the reason — that is UNVERIFIED, the same rule the #821 branch applies to
        # a k of zero.
        if int(trace.get("verified", 0) or 0) <= 0:
            return (CLASS_GREEN_UNVERIFIED, fingerprint)
        return (CLASS_GREEN_PARTIAL, fingerprint)
    qa = ctx.oracle_qa
    if qa and "oracle_coverage" in qa:
        cov = str(qa.get("oracle_coverage") or "unknown")
        uncovered = qa.get("uncovered") or []
        if cov == "unknown":
            return (CLASS_GREEN_UNVERIFIED, "oracle_coverage=unknown (no traceability map)")
        k, n = _parse_fraction(cov)
        if k is None or n is None:
            return (CLASS_GREEN_UNVERIFIED, f"oracle_coverage={cov} (unparseable)")
        if n == 0 or k == 0:
            return (CLASS_GREEN_UNVERIFIED, f"oracle_coverage={cov} (zero criteria verified)")
        if k < n:
            unc = ",".join(str(u) for u in uncovered)[:120]
            return (CLASS_GREEN_PARTIAL,
                    f"oracle_coverage={cov} (partial; uncovered: {unc or 'unnamed'})")
        return (CLASS_GREEN_VERIFIED, f"oracle_coverage={cov} (all test-tier criteria verified)")
    status = str(ev.get("oracle_status") or "unknown")
    return (CLASS_GREEN_UNVERIFIED, f"no oracle-qa coverage stamp (oracle_status={status})")


def classify_scorecard(
    sc: Scorecard, *, runs_dir: "str | Path | None" = None, ctx: Optional[_Context] = None
) -> tuple[str, str]:
    """``(class, fingerprint)`` for one scorecard — the GREEN-side taxonomy for a GREEN
    verdict, the failure taxonomy otherwise. ``ctx`` may be supplied (tests / reuse); else
    it is loaded from ``<runs_dir>/<sc.run_id>/``."""
    context = ctx if ctx is not None else load_context(runs_dir, sc.run_id)
    if sc.verdict == VERDICT_GREEN:
        return classify_green(sc, context)
    # #832: a card the earned-GREEN integrity audit DOWNGRADED (GREEN -> PARKED-HONEST for a
    # grader-tampering fingerprint) still carries the gaming signal in its evidence / the
    # green-audit sidecar. Count it GREEN-GAMED regardless of the now-downgraded verdict, so
    # the nightly trend TALLIES integrity downgrades instead of dropping them into
    # UNCLASSIFIED (which would falsely inflate the new-leak-class health metric). A
    # STILL-GREEN advisory #837 band flag is caught by classify_green's own _gaming_signal
    # above — same class, no downgrade (the advisory-vs-integrity boundary, viewed here).
    gamed = _gaming_signal(sc.evidence or {}, context)
    if gamed:
        return (CLASS_GREEN_GAMED, gamed)
    return classify_failure(sc, context)


# ---------------------------------------------------------------------------
# Stamping (advisory) + aggregation + trend
# ---------------------------------------------------------------------------


def _clip_fingerprint(text: str) -> str:
    """One line, capped — the scorecard-evidence S6 discipline (no newline, bounded)."""
    flat = re.sub(r"\s+", " ", str(text)).strip()
    return flat[:_FINGERPRINT_CAP]


def stamp_scorecard(sc: Scorecard, klass: str, fingerprint: str) -> None:
    """Write the ADVISORY stamp into the scorecard's evidence IN PLACE. Writes ONLY the
    reserved keys — verdict/attribution are never touched here (the invariant is
    additionally asserted by :func:`classify_and_stamp`)."""
    evidence = dict(sc.evidence or {})
    fp = _clip_fingerprint(fingerprint)
    if klass in GREEN_CLASSES:
        evidence[EV_GREEN_CLASS] = klass
        evidence[EV_GREEN_FINGERPRINT] = fp
    else:
        evidence[EV_FAILURE_CLASS] = klass
        evidence[EV_FAILURE_FINGERPRINT] = fp
    sc.evidence = evidence


def aggregate(pairs: "list[tuple[Scorecard, str, str]]") -> dict:
    """The per-class count block. ``pairs`` is ``[(scorecard, class, fingerprint), ...]``.
    ``unclassified_rate`` is over the NON-GREEN cards (the instrument's health metric)."""
    fc = {c: 0 for c in FAILURE_CLASSES}
    gc = {c: 0 for c in GREEN_CLASSES}
    for _sc, klass, _fp in pairs:
        if klass in fc:
            fc[klass] += 1
        elif klass in gc:
            gc[klass] += 1
    nongreen_total = sum(fc.values())
    unclassified = fc[CLASS_UNCLASSIFIED]
    return {
        "failure_classes": fc,
        "green_classes": gc,
        "nongreen_total": nongreen_total,
        "green_total": sum(gc.values()),
        "unclassified": unclassified,
        "unclassified_rate": (f"{unclassified}/{nongreen_total}" if nongreen_total else "0/0"),
    }


def compute_trend(current_failure_classes: dict, history: "list[dict] | None") -> dict:
    """The night-over-night trend (the KPI line). ``history`` is prior nights' aggregate
    blocks, oldest-first (the CURRENT night excluded). Per class: current / previous /
    delta — ``previous``/``delta`` are ``None`` on the first night (an honest baseline,
    not a fabricated zero)."""
    hist = history or []
    prev = (hist[-1].get("failure_classes") or {}) if hist else {}
    by_class: dict[str, dict] = {}
    for c in FAILURE_CLASSES:
        cur = int(current_failure_classes.get(c, 0) or 0)
        if hist:
            pri = int(prev.get(c, 0) or 0)
            by_class[c] = {"current": cur, "previous": pri, "delta": cur - pri}
        else:
            by_class[c] = {"current": cur, "previous": None, "delta": None}
    return {
        "nights": len(hist) + 1,
        "previous_label": str(hist[-1].get("label", "")) if hist else "",
        "by_class": by_class,
    }


#: The trailing ``YYYYMMDD-HHMMSS`` stamp on a dated run-root name. Stripping it yields
#: the run's naming FAMILY (``night-20260716-230002`` -> ``night-``; a bare stamp -> ``""``)
#: so the night KPI never absorbs ``daytime-*`` / ad-hoc proof runs parked in the same root.
_RUN_STAMP_RE = re.compile(r"\d{8}-\d{6}$")


def _run_root(summary_path: Path) -> Path:
    """The dated run root that owns a ``battery-summary.json``: its parent, or its
    grandparent when the summary sits under a ``scorecards/`` subdir (the nightly
    runner's ``--out <night>/scorecards`` shape)."""
    parent = summary_path.parent
    return parent.parent if parent.name == "scorecards" else parent


def load_history(out_dir: "str | Path | None", *, limit: int = 14) -> list[dict]:
    """Best-effort prior-night history for the trend: the ``failure_taxonomy`` aggregate
    of each SAME-FAMILY sibling run's ``battery-summary.json`` under the battery root.

    ``out_dir`` is wherever the CURRENT summary lands — either the dated run root itself
    or its ``scorecards/`` subdir (the nightly runner's ``--out <night>/scorecards``
    shape) — so the battery root is the run root's parent, NOT ``out_dir``'s parent.
    Both summary depths are searched (``*/battery-summary.json`` and
    ``*/scorecards/battery-summary.json``); a run root carrying both counts once.
    Same-family = identical run-root name once the datetime stamp is stripped
    (:data:`_RUN_STAMP_RE`), so ``night-*`` history is never polluted by ``daytime-*``
    or ad-hoc proof runs. Dated names sort chronologically; the CURRENT run is excluded,
    newest last, capped at *limit* nights. Fail-soft -> ``[]`` (the trend then shows an
    honest first-night baseline)."""
    if not out_dir:
        return []
    try:
        here = Path(out_dir).resolve()
        run_root = here.parent if here.name == "scorecards" else here
        battery_root = run_root.parent
        if not battery_root.is_dir():
            return []
        summaries = sorted(
            set(battery_root.glob("*/battery-summary.json"))
            | set(battery_root.glob("*/scorecards/battery-summary.json")),
            key=lambda p: (_run_root(p).name, str(p)),  # chronological; deterministic tiebreak
        )
    except OSError:
        return []
    family = _RUN_STAMP_RE.sub("", run_root.name)
    out: list[dict] = []
    seen_roots: set[Path] = set()
    for path in summaries:
        try:
            root = _run_root(path).resolve()
        except OSError:
            continue
        if root == run_root:
            continue  # the current night is not its own history
        if _RUN_STAMP_RE.sub("", root.name) != family:
            continue  # ad-hoc / daytime families stay out of the night KPI
        if root in seen_roots:
            continue  # a run root carrying summaries at both depths counts once
        data = _read_json(path)
        if not data:
            continue
        tax = data.get("failure_taxonomy")
        if not isinstance(tax, dict):
            continue
        fc = tax.get("failure_classes")
        if not isinstance(fc, dict):
            continue
        seen_roots.add(root)
        out.append({"label": root.name, "failure_classes": fc})
    return out[-limit:]


def classify_and_stamp(
    scorecards: "list[Scorecard]",
    *,
    runs_dir: "str | Path | None" = None,
    out_dir: "str | Path | None" = None,
    history: "list[dict] | None" = None,
) -> dict:
    """The battery-close entry point. Classify every scorecard, stamp its evidence IN
    PLACE (advisory), and return the ``failure_taxonomy`` summary block (schema, the
    advisory flag, per-class counts, the unclassified rate, and the night-over-night
    trend). NEVER raises — a classifier fault must not sink the summary write — and NEVER
    changes a verdict or attribution (asserted per card; a violation is restored + flagged).

    ``history`` defaults to :func:`load_history` over ``out_dir`` when not supplied."""
    pairs: list[tuple[Scorecard, str, str]] = []
    for sc in scorecards:
        before = (sc.verdict, sc.attribution)
        try:
            klass, fingerprint = classify_scorecard(sc, runs_dir=runs_dir)
        except Exception as exc:  # noqa: BLE001 — a classify fault degrades ONE card, never the run
            klass, fingerprint = CLASS_UNCLASSIFIED, f"classifier error: {type(exc).__name__}"
        stamp_scorecard(sc, klass, fingerprint)
        # The advisory invariant, enforced (not merely documented): the stamp touches
        # evidence only. If a future edit ever mutates the verdict/attribution, restore it
        # and record the breach in the fingerprint rather than let a mislabel bank.
        if (sc.verdict, sc.attribution) != before:
            sc.verdict, sc.attribution = before
            fingerprint = _clip_fingerprint(f"ADVISORY-INVARIANT-RESTORED; {fingerprint}")
            stamp_scorecard(sc, klass, fingerprint)
        pairs.append((sc, klass, fingerprint))

    agg = aggregate(pairs)
    hist = history if history is not None else load_history(out_dir)
    block = {
        "schema": TAXONOMY_SCHEMA,
        "classifier_advisory": True,
        **agg,
        "trend": compute_trend(agg["failure_classes"], hist),
    }
    return block


def render_kpi(block: dict) -> list[str]:
    """The human KPI line(s) for the battery-summary render. The per-class trend
    (``ORACLE-DEFECT 3 (Δ+1)``) + the instrument-health line (the unclassified rate)."""
    if not block:
        return []
    fc = block.get("failure_classes") or {}
    trend = (block.get("trend") or {}).get("by_class") or {}
    parts: list[str] = []
    for c in FAILURE_CLASSES:
        n = int(fc.get(c, 0) or 0)
        delta = (trend.get(c) or {}).get("delta")
        tag = "" if delta is None else f" (Δ{'+' if delta >= 0 else ''}{delta})"
        parts.append(f"{c} {n}{tag}")
    gc = block.get("green_classes") or {}
    green_parts = [f"{c} {int(gc.get(c, 0) or 0)}" for c in GREEN_CLASSES if int(gc.get(c, 0) or 0)]
    lines = ["failure-taxonomy: " + ", ".join(parts)]
    if green_parts:
        lines.append("green-quality: " + ", ".join(green_parts))
    rate = block.get("unclassified_rate", "0/0")
    unclassified = int(block.get("unclassified", 0) or 0)
    health = "OK" if unclassified == 0 else "NEW-LEAK-CLASS? — human taxonomy pass due"
    lines.append(f"unclassified: {rate} [{health}]")
    return lines
