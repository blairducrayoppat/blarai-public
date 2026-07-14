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
#: The environment / runner / budget was the terminal cause — a timeout kill, a
#: tree-kill, a harness crash, an unadoptable/could-not-run card (HARNESS attribution).
CLASS_HARNESS_BUDGET = "HARNESS-BUDGET"
#: The honest residue — no known fingerprint matched. A RISING unclassified rate is the
#: instrument telling us the taxonomy needs a human pass (a NEW leak class). Never silent.
CLASS_UNCLASSIFIED = "UNCLASSIFIED"

#: Every failure class, in a stable order (so the count map always carries the full
#: taxonomy — even the classes that did not fire tonight — for a stable summary shape).
FAILURE_CLASSES: tuple[str, ...] = (
    CLASS_ORACLE_DEFECT,
    CLASS_INTEGRATION_SEAM,
    CLASS_BLIND_FIX_LOOP,
    CLASS_DECOMPOSE_DOWNGRADE,
    CLASS_HARNESS_BUDGET,
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

#: HARNESS-BUDGET: a terminal environment/budget fault. Deliberately does NOT include the
#: coder idle circuit-breaker — an idle coder is a BUILD/capability event, not a harness
#: fault (the hand-analysis is explicit that B4/B6's idle tasks were not the terminal
#: cause), so it must fall through to the honest residue rather than mislabel as HARNESS.
_HARNESS_LOG: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bTIMEOUT\b"), "TIMEOUT (budget kill)"),
    (re.compile(r"tree[- ]kill"), "tree-kill"),
    (re.compile(r"harness exception"), "harness exception"),
    (re.compile(r"run[_ ]budget|swap_run_budget"), "run-budget kill"),
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

    __slots__ = ("oracle_qa", "decompose", "import_probe", "logs", "green_audit")

    def __init__(
        self,
        *,
        oracle_qa: Optional[dict] = None,
        decompose: Optional[dict] = None,
        import_probe: Optional[dict] = None,
        green_audit: Optional[dict] = None,
        logs: str = "",
    ) -> None:
        self.oracle_qa = oracle_qa
        self.decompose = decompose
        self.import_probe = import_probe
        self.green_audit = green_audit
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


def _rule_harness_budget(ev: dict, attribution: str, ctx: _Context) -> Optional[str]:
    """A terminal environment/runner/budget fault — the HARNESS attribution, or a
    timeout/tree-kill/crash log marker. NOT a coder idle circuit-breaker (a BUILD event)."""
    if attribution == ATTRIBUTION_HARNESS:
        return "attribution=HARNESS (environment/runner/budget fault)"
    return _first_log_match(ctx.logs, _HARNESS_LOG)


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
        (CLASS_HARNESS_BUDGET, lambda: _rule_harness_budget(ev, attribution, ctx)),
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


def load_history(out_dir: "str | Path | None", *, limit: int = 14) -> list[dict]:
    """Best-effort prior-night history for the trend: the ``failure_taxonomy`` aggregate
    of each sibling ``battery-summary.json`` under ``out_dir``'s parent (the dated-stamp
    run roots sort chronologically), the CURRENT ``out_dir`` excluded, newest last, capped
    at *limit* nights. Fail-soft -> ``[]`` (the trend then shows an honest first-night
    baseline)."""
    if not out_dir:
        return []
    try:
        here = Path(out_dir).resolve()
        parent = here.parent
        if not parent.is_dir():
            return []
        summaries = sorted(parent.glob("*/battery-summary.json"))
    except OSError:
        return []
    out: list[dict] = []
    for path in summaries:
        try:
            if path.parent.resolve() == here:
                continue  # the current night is not its own history
        except OSError:
            continue
        data = _read_json(path)
        if not data:
            continue
        tax = data.get("failure_taxonomy")
        if not isinstance(tax, dict):
            continue
        fc = tax.get("failure_classes")
        if not isinstance(fc, dict):
            continue
        out.append({"label": path.parent.name, "failure_classes": fc})
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
