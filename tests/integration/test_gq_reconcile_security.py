"""#1231 — the RECONCILIATION LOCK over the security scan's published severity breakdown.

THE DEFECT CLASS THIS FILE EXISTS TO REFUSE. A grader publishes a rate or a count whose
DENOMINATOR is derived by summing its own buckets. An item that lands in NO bucket therefore
leaves the numerator and the denominator TOGETHER: the arithmetic stays perfectly
self-consistent while the published figure silently under-reports, and the number reads
CLEANER than the truth. Nothing in the run record contradicts it, because the run record only
ever carried the buckets.

WHERE THAT SHAPE LIVES HERE. :meth:`SecurityResult.summary` (``security.py:329-344``) is the
security instrument's shipping surface — ``evidence_stamp`` publishes it UNCONDITIONALLY as
``EV_SECURITY`` (``green_quality/__init__.py:287``), so this one string is what reaches the
scorecard's durable evidence dict, and :mod:`shared.instrument_registry` names it as the
instrument's rendering surface. On the findings branch that string is a severity breakdown —
"2 high, 1 medium, 1 info: <rules>" — and its counts are built by summing THREE HARD-CODED
buckets, one per rung of the ladder in :mod:`.constants`. ``len(self.findings)``, the true
population, is never published beside them. A finding at any severity outside those three
would leave the published line entirely, and ``worst_severity`` would not notice either
(``SEVERITY_ORDER.get(unknown, 0)`` is 0), so nothing reaching the operator would say the
finding existed.

WHY THIS IS A LOCK AND NOT A BUG REPORT. The grader is SOUND TODAY, proven by execution
through its real entry point: the severity vocabulary is closed by three constants, the
demotion map maps all three onto themselves, and no producer in the module can mint a fourth.
The buckets therefore partition the whole finding population, and the published denominator IS
the true one. That is a property of today's vocabulary, not of :meth:`summary`'s arithmetic —
so the day a rung is added to the ladder (a "critical", a "low"), the published figure starts
under-reporting silently unless these tests fail first. They are written to fail first.

Four locks and a toggle:

* the published breakdown accounts for every finding a REAL scan of a REAL tree produced,
  where that tree also contains population members that land in no bucket at all;
* the same reconciliation on the SURFACE THAT SHIPS — ``EV_SECURITY`` in the stamped
  scorecard, reconciled against the sidecar's own full findings list from the same run;
* every rung of the ladder gets its own bucket in the published line (the regression tooth);
* nothing in the module can rewrite a finding onto a rung the published line does not sum;
* and the toggle: the probe these locks use must FAIL when it is shown a line that
  under-reports, or "reconciles" and "cannot see a shortfall" are the same result.

SCOPE, stated so a later reader does not mistake silence for coverage: this file locks the
FINDING partition — the severity breakdown against ``len(findings)``. The scan's separate
FILE-coverage figure (``files_scanned``, and which bounds the published line does or does not
carry over from ``.status``) is a different figure with its own ticketed record, and no
assertion here speaks for it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from tools.dispatch_harness.green_quality import audit_greens, security as sec
from tools.dispatch_harness.green_quality.constants import (
    EVIDENCE_VALUE_CAP,
    EV_SECURITY,
    SEVERITY_HIGH,
    SEVERITY_INFO,
    SEVERITY_MEDIUM,
    SEVERITY_ORDER,
)
from tools.dispatch_harness.scorecard import Scorecard

# ---------------------------------------------------------------------------
# The probe — reading the published line the way an operator's downstream reader would
# ---------------------------------------------------------------------------

#: One "<n> <severity>" pair out of the published breakdown's head.
_COUNT_RE = re.compile(r"(\d+)\s+([A-Za-z][A-Za-z_-]*)")


def _published_counts(published: str) -> dict[str, int]:
    """The severity counts a reader can actually get OUT of the published line.

    Parsed from the string rather than from the result object on purpose: the object is not
    what ships. ``EV_SECURITY`` carries this text and nothing else, so whatever a count cannot
    be recovered from here is a count the run record does not have."""
    head = published.split(":", 1)[0]
    head = head.split("—")[-1]  # drop any "PARTIAL SCAN — " prefix
    return {severity: int(n) for n, severity in _COUNT_RE.findall(head)}


def _accounts_for(published: str, population: int) -> bool:
    """Does the published line account for a population of *population* findings?

    The single predicate every lock below spends, and the one the toggle proves has teeth.
    Satisfied when the published counts reach the true population — by the bucket sum today,
    or by any future rendering that publishes the total, which is the point of asking the
    QUESTION rather than asserting today's arithmetic."""
    return sum(_published_counts(published).values()) == population


# ---------------------------------------------------------------------------
# The fixture — a real tree carrying every rung of the ladder AND members that get no rung
#
# The population deliberately mixes three kinds of file: one that earns a finding at each
# severity, and two that are part of the delivered tree but reach no bucket at all — a
# dependency tree that is never opened, and an asset whose suffix is never read. A partition
# claim tested only over files that all produce findings is not tested at all.
# ---------------------------------------------------------------------------

#: HIGH — an AWS key in a provider's own format. Unambiguous, and not a heuristic.
_CONFIG_PY = 'AWS_ACCESS_KEY = "AKIAIOSFODNN7EXAMPLE"\n'

#: MEDIUM — a deserializer that rebuilds objects from a stream. Found twice (regex and AST)
#: and deduped to one finding, which is itself part of what the partition has to survive.
_STORE_PY = '''import pickle


def load(blob):
    return pickle.loads(blob)
'''

#: INFO — a coder deferring a value. Recorded for transparency, never band-moving.
_SETTINGS_PY = 'api_key = "your-key-here"\n'

#: NO BUCKET — a credential inside a dependency tree. The file is in the delivered tree and
#: carries a real-shaped key, and the scan never opens it: a population member that produces
#: no finding at any severity.
_VENDORED_JS = 'var k = "AKIAIOSFODNN7EXAMPLE";\n'

#: NO BUCKET — an asset whose suffix is not source. Read by nothing, graded by nothing.
_LOGO_SVG = '<svg xmlns="http://www.w3.org/2000/svg"><rect width="8" height="8"/></svg>\n'


def _plant_mixed_population(root: Path) -> Path:
    """A delivered tree whose findings span the WHOLE ladder, plus members that earn none."""
    (root / "app").mkdir(parents=True)
    (root / "node_modules" / "dep").mkdir(parents=True)
    (root / "assets").mkdir(parents=True)
    (root / "app" / "config.py").write_text(_CONFIG_PY, encoding="utf-8")
    (root / "app" / "store.py").write_text(_STORE_PY, encoding="utf-8")
    (root / "app" / "settings.py").write_text(_SETTINGS_PY, encoding="utf-8")
    (root / "node_modules" / "dep" / "leak.js").write_text(_VENDORED_JS, encoding="utf-8")
    (root / "assets" / "logo.svg").write_text(_LOGO_SVG, encoding="utf-8")
    return root


def _finding(severity: str, rule: str = sec.RULE_HARDCODED_SECRET, line: int = 1):
    """One real :class:`SecurityFinding` at *severity* — the real type the real
    :meth:`summary` reads, so the grader under test is never stubbed."""
    return sec.SecurityFinding(rule, severity, "app/config.py", line, "detail")


# ---------------------------------------------------------------------------
# LOCK 1 — the published breakdown against a real scan of a real tree
# ---------------------------------------------------------------------------


def test_the_published_breakdown_accounts_for_every_finding_a_real_scan_made(tmp_path):
    """The denominator of the published severity breakdown must be the TRUE finding
    population, not the sum of the buckets it happens to have.

    Delete this and the module's shipping figure is free to become self-consistent and wrong:
    a finding classified into no published bucket would leave the numerator and the
    denominator together, "1 high, 1 medium" would stay arithmetically perfect over a
    3-finding population, and nothing in the run record would disagree. The tree here is real
    and so is the entry point — ``scan_repo`` walks it — and it deliberately contains members
    that earn no rung, because a partition proved only over items that all land somewhere is
    not a partition proof."""
    repo = _plant_mixed_population(tmp_path / "delivered")

    result = sec.scan_repo(repo, "node-web")

    assert result.measured is True, f"precondition: the scan ran — {result.status}"
    # Precondition, not the claim: all three rungs really are exercised, so the reconciliation
    # below is over a population that spans the whole published vocabulary.
    severities = {f.severity for f in result.findings}
    assert severities == {SEVERITY_HIGH, SEVERITY_MEDIUM, SEVERITY_INFO}, (
        f"the fixture no longer spans the ladder: {sorted(severities)} — the partition claim "
        f"below would be vacuous over a narrower population"
    )
    published = result.summary()
    assert len(published) < EVIDENCE_VALUE_CAP, (
        f"precondition: the published line is not capped, so the parse sees all of it — "
        f"{published!r}"
    )

    # THE CLAIM. The published denominator equals the true population.
    assert _accounts_for(published, len(result.findings)), (
        f"the published breakdown lost a finding: {published!r} accounts for "
        f"{sum(_published_counts(published).values())} of {len(result.findings)} findings — "
        f"an item that reaches no bucket leaves the figure entirely and the arithmetic still "
        f"looks right"
    )

    # The population members that earned no rung are not silently absorbed either: the
    # dependency tree the scan never opened is NAMED, so "clean here" cannot be read as
    # "clean everywhere".
    assert "NOT scanned" in result.status and "node_modules" in result.status, (
        f"a tree carrying a real-shaped credential was skipped without saying so: "
        f"{result.status!r}"
    )


# ---------------------------------------------------------------------------
# LOCK 2 — the same reconciliation on the surface that actually SHIPS
#
# The lesson that makes this the load-bearing test of the file: a lock pointed at the internal
# result object can pass while the string the operator's run record carries still lies. The
# scorecard evidence and the sidecar are BOTH durable artifacts of the same run — one carries
# the published figure, the other the full finding list — so they can be reconciled against
# each other, which is exactly the check nothing downstream performs today.
# ---------------------------------------------------------------------------


def test_the_shipping_evidence_line_accounts_for_every_finding_the_run_recorded(tmp_path):
    """``EV_SECURITY`` — the string stamped into the scorecard's durable evidence — must
    account for every finding the same run wrote into its sidecar.

    Delete this and the only surviving reconciliation is over an object no operator ever sees.
    The audit is driven through ``audit_greens``, the real battery-close entry point: it walks
    the real tree, stamps the real scorecard and writes the real ``green-quality.json``. The
    sidecar's ``security.findings`` list is the run's own record of the TRUE population, so a
    published figure that disagrees with it is the instrument contradicting itself about one
    run — with the softer half being the one that ships."""
    out_dir = tmp_path / "battery" / "20260814-000001"
    _plant_mixed_population(out_dir / "repos-archived" / "battery-b3-budget-web")
    sc = Scorecard(job_id="B3", verdict="GREEN", attribution="",
                   repo="battery-b3-budget-web", run_id="R1",
                   evidence={"oracle_status": "passed"})

    audit_greens([sc], runs_dir=tmp_path / "runs", out_dir=out_dir,
                 job_surfaces={"B3": "node-web"})

    published = sc.evidence[EV_SECURITY]  # unconditional by design — always present
    sidecar = json.loads(
        (tmp_path / "runs" / "R1" / "green-quality.json").read_text(encoding="utf-8"))
    recorded = sidecar["security"]["findings"]

    assert sidecar["security"]["measured"] is True, "precondition: the audit's scan ran"
    assert len(recorded) == 3, (
        f"precondition: the run recorded the planted population — {recorded}"
    )

    # THE CLAIM, on the surface that reaches the operator's run record.
    assert _accounts_for(published, len(recorded)), (
        f"the shipped evidence line under-reports its own run: {published!r} accounts for "
        f"{sum(_published_counts(published).values())} of {len(recorded)} recorded findings"
    )
    # And per rung, so a bucket cannot be right in total while being wrong about which
    # severity carried it.
    for severity in SEVERITY_ORDER:
        expected = sum(1 for f in recorded if f["severity"] == severity)
        assert _published_counts(published).get(severity, 0) == expected, (
            f"the published line disagrees with the sidecar about {severity!r}: "
            f"{published!r} vs {expected} recorded"
        )


# ---------------------------------------------------------------------------
# LOCK 3 — the regression tooth: every rung of the ladder has a bucket
# ---------------------------------------------------------------------------


def test_every_severity_on_the_ladder_gets_its_own_bucket_in_the_published_line():
    """Every rung of the severity ladder must be counted by the published breakdown.

    Delete this and adding a rung to the ladder becomes a silent under-report rather than a
    failing test. ``summary`` sums three hard-coded buckets; the ladder is defined elsewhere
    (:mod:`.constants`). Nothing but this test holds the two together, and the day they drift
    a finding at the new rung leaves the operator's figure without leaving the findings list —
    the exact shape #1231 exists to catch. Real results, real findings, real ``summary`` — the
    population is constructed so that each rung can be isolated, the grader is not."""
    for severity in SEVERITY_ORDER:
        result = sec.SecurityResult(findings=(_finding(severity),), measured=True,
                                    status="scanned 1 file(s)", files_scanned=1)
        published = result.summary()
        assert _accounts_for(published, 1), (
            f"a lone {severity!r} finding vanished from the published line: {published!r} — "
            f"this rung is on the ladder but has no bucket in the figure that ships"
        )
        assert severity in published, (
            f"the published line counted the {severity!r} finding without naming the "
            f"severity: {published!r}"
        )


# ---------------------------------------------------------------------------
# LOCK 4 — the closure that makes lock 3's guarantee total
# ---------------------------------------------------------------------------


def test_nothing_in_the_module_rewrites_a_finding_onto_a_rung_with_no_bucket(tmp_path):
    """No producer or transform in the security module may put a finding at a severity the
    published breakdown does not sum.

    Delete this and lock 3's coverage stops being total: the demotion applied to findings in
    a test path is the one place the module REWRITES a severity, and a demotion map whose
    range escaped the ladder would mint an uncountable finding out of a countable one. The
    scan half is behavioural — a real walk over the planted tree, asserting that what it
    actually emitted stays inside the published vocabulary."""
    demoted = set(sec._DEMOTE) | set(sec._DEMOTE.values())
    assert demoted <= set(SEVERITY_ORDER), (
        f"the demotion map moves findings off the published ladder: {sorted(demoted)} vs "
        f"{sorted(SEVERITY_ORDER)}"
    )

    repo = _plant_mixed_population(tmp_path / "delivered")
    # The same tree again with its findings demoted — every file under a test path — so the
    # rewrite path is exercised rather than argued about.
    (repo / "tests").mkdir()
    (repo / "tests" / "test_fixture.py").write_text(_CONFIG_PY + _SETTINGS_PY, encoding="utf-8")

    result = sec.scan_repo(repo, "node-web")

    emitted = {f.severity for f in result.findings}
    assert emitted <= set(SEVERITY_ORDER), (
        f"a real scan emitted a severity with no bucket in the published line: "
        f"{sorted(emitted - set(SEVERITY_ORDER))}"
    )
    assert _accounts_for(result.summary(), len(result.findings)), (
        f"the demoted population is under-reported: {result.summary()!r} over "
        f"{len(result.findings)} findings"
    )


# ---------------------------------------------------------------------------
# THE TOGGLE — the probe must fail when it is shown a shortfall
# ---------------------------------------------------------------------------


def test_the_reconciliation_probe_fails_on_a_line_that_under_reports():
    """The probe the four locks spend must return False on a published line that loses a
    finding, and True only when the line reaches the true population.

    Delete this and every assertion above could be passing because the probe cannot see a
    shortfall at all — "reconciles" and "cannot tell" would be the same green. The lines here
    are the exact shape :meth:`summary` emits on its findings branch, including the
    "PARTIAL SCAN — " prefix, so the parse is proved against the real rendering rather than
    against a convenient one."""
    assert _accounts_for("2 high, 1 medium, 1 info: provider-credential", 4) is True
    assert _accounts_for("PARTIAL SCAN — 1 high: provider-credential", 1) is True

    # The failure this whole file exists to make loud: buckets that sum cleanly to LESS than
    # the population they claim to describe.
    assert _accounts_for("2 high, 1 medium, 1 info: provider-credential", 5) is False, (
        "the probe cannot see a missing finding — every lock in this file is vacuous"
    )
    # And the degenerate case: a population whose findings all landed off the ladder renders
    # a head with no counts in it at all.
    assert _accounts_for(": info-only", 2) is False
