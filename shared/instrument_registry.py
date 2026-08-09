"""
The Instrument Registry — every grader that reports a number, and how it says "I did not look".
===============================================================================================
On 2026-07-30 nine instruments were found, in one day, reporting a pass, a clean or a
number they had not measured (#1223 carries the evidence table). Every one was caught by a
person or an agent READING CODE; none was caught by a gate. Every one erred toward LOOKING
FINE — not one produced a false alarm — and an error distribution that one-sided is what
happens when the "cannot measure" path is written by someone thinking about the happy path.

The correct pattern was already in the tree, invented independently four times before anyone
wrote it down: ``SecurityResult.measured``, ``TraceabilityResult.available``,
``Invoke-CoderTestQa.Measured``, and the three-way NOT RUN / 0 measured / n findings render
in ``layer1.py``. Four independent inventions of one idea is the signal that it should be a
rule rather than a habit. This module is the rule.

WHAT AN INSTRUMENT IS. A function whose output reaches a scorecard, a band, a card, or an
operator-facing report — the surfaces a non-technical reader treats as fact. A grader nobody
renders is not an instrument for this registry's purposes; a grader whose empty result is
printed as "clean" is.

THE INVARIANT, in one line: **an instrument is born unmeasured**, and every renderer that
branches on what it found must first be able to tell "found nothing" from "did not look".
That is the deny-by-default principle (``CLAUDE.md`` security_by_design #2) aimed at
measurement rather than at access, and it is why :attr:`InstrumentEntry.unmeasured` must
equal the status field's DECLARED DEFAULT: a result assembled by a caller who forgot to run
the check must read as ignorance, never as a pass.

THIS IS A REGISTRY, NOT A CONFIG SOURCE — the same contract
:mod:`shared.timeout_registry` holds for durations. The live instruments stay where their
consumers live; the standing gate (``tests/security/test_instrument_registry.py``) resolves
every entry against the real module and fails by name when the table stops describing
reality. It is also a READ surface: before adding a grader, read the table to see the shape
the house already uses, and run ``python -m shared.instrument_registry`` to see which
instruments currently conform.

THREE STATUS SHAPES, because the population really has three and inventing a fourth would
force a rewrite of working code rather than describe it:

* :data:`STATUS_FIELD` — a named field on the result type (``measured``, ``available``,
  ``audited``, ``status``). The strongest shape: the honesty bit has a name a reader can ask
  about, and the renderer rule is simply "consult it".
* :data:`STATUS_SENTINEL` — the count field is itself ``Optional`` and ``None`` means "did
  not run" (``Layer1Result.ruff_findings``). The WEAKEST shape and the one that produced
  #1189, because ``None`` and ``0`` are both falsy: the renderer rule is therefore stricter
  here than anywhere else — an explicit ``is None`` test is required, not merely a mention.
* :data:`STATUS_PREDICATE` — the evidence is a plain ``dict`` and a module-level function
  answers whether it was measured (``oracle_mutation.is_measured``). Registered as a first-
  class shape because that instrument is already correct; a registry that could not express
  it would push the next dict-shaped grader into inventing its own convention.

NOISE IS THE FAILURE MODE OF THE FIX, and the schema carries three answers to it because
three agents independently raised it on 2026-07-30. Make eleven instruments loud, let ONE
speak on healthy runs, and the operator learns to skim the caveat block — at which point all
eleven are silent, including the honest ones, and the whole effort inverts. So:
:attr:`~InstrumentEntry.quiet_test` proves an instrument does not convict a correct
configuration; :attr:`~InstrumentEntry.disclosure_marker` keeps *I could not measure this*
distinguishable from *I measured this and it is wrong*, which are different facts with
different urgencies; and :attr:`~InstrumentEntry.disclosure_rate` makes "how often does this
speak?" a number in the table rather than a habit discovered later.

RECORD THE MEASURING, DO NOT MERELY CONSULT IT. A status field read only at render time
leaves the ARCHIVE mute — #1198's instrument could not say, across its own 36-day history,
whether the tool had been missing or had simply found nothing, because the record kept the
finding and discarded the fact of looking. A registered instrument's status belongs in what
it PERSISTS, not only in what a renderer asks it.

WHAT THIS REGISTRY CANNOT DO, stated here rather than only in the report, because a limit
named in code survives the session that found it. A gate checks the FORM of an instrument
that is REGISTERED. It cannot see an instrument nobody registered AND nobody renders through
a registered renderer; it cannot see a renderer nobody registered; and it can never judge
whether a ``measured=True`` is HONEST — an instrument that sets the bit and then measures
nothing passes every check here. That residue is a review-time responsibility.
:mod:`scripts.verify_disposition` carries the identical limit for disposition records, and
naming it is what keeps the gate from being mistaken for a proof.
"""

from __future__ import annotations

import ast
import importlib
import inspect
from dataclasses import MISSING, dataclass, fields as dataclass_fields, is_dataclass
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Status shapes
# ---------------------------------------------------------------------------

#: A named field on the result type carries the honesty bit.
STATUS_FIELD = "field"
#: The count field is ``Optional`` and ``None`` means "did not run".
STATUS_SENTINEL = "sentinel"
#: A module-level predicate answers "was this measured?" over a dict-shaped evidence blob.
STATUS_PREDICATE = "predicate"

STATUS_KINDS: frozenset[str] = frozenset({STATUS_FIELD, STATUS_SENTINEL, STATUS_PREDICATE})

#: The only permitted non-figure for :attr:`InstrumentEntry.disclosure_rate`. Spelled as a
#: constant so the gate can tell "nobody has measured this" from a number somebody typed:
#: an UNMEASURED disclosure rate in a registry about unmeasured claims is honest, a guessed
#: one is the defect this module exists to refuse, wearing the registry's own uniform.
RATE_UNMEASURED = "UNMEASURED (no corpus sweep run)"


@dataclass(frozen=True)
class InstrumentEntry:
    """One row of the taxonomy: a grader, its honesty bit, and where it is rendered.

    ``module``/``result_type``/``entrypoint`` locate the LIVE instrument — the gate imports
    and resolves all three, so an entry that stops matching reality fails the standing gate
    rather than rotting into documentation-fiction.

    ``status``/``status_kind``/``unmeasured`` are the honesty contract. For
    :data:`STATUS_FIELD` and :data:`STATUS_SENTINEL`, ``unmeasured`` must equal the field's
    DECLARED DEFAULT — the born-unmeasured rule. For :data:`STATUS_PREDICATE`, ``status``
    names a module-level callable and ``unmeasured`` is unused.

    ``counts`` are the fields whose value is meaningless without ``status``: a count, a
    collection, or a boolean CLAIM. These are the falsy-collapse targets — ``if result.x:``
    where ``None`` and ``0`` are both falsy and mean opposite things.

    ``guards`` are the attribute names a renderer may consult to disambiguate. Normally just
    ``status``; a result type that exposes a DERIVED property over its status field lists
    both, because consulting the property is consulting the status. Kept separate from
    ``status`` on purpose: only the FIELD can be born unmeasured, while either name is honest
    evidence that the renderer looked.

    ``receivers`` are the path tails through which this instrument's result is reached inside
    its renderers — ``layer1.dead_scaffold.flagged`` is reached through ``dead_scaffold``,
    ``reg.regressed`` through ``reg``. Without them a shared field name like ``flagged``
    would attribute every craft lint's read to every other craft lint; with them each read is
    charged to the instrument that owns it, and a read NO entry claims is itself a finding
    (see :func:`unclaimed_reads` — that is how the sweep sees a grader nobody registered).

    ``renderers`` are ``module:qualname`` sites that turn this result into something a reader
    treats as fact. They are the half that makes the registry real: a ``measured`` attribute
    no caller consults is the same defect wearing the fix's uniform.

    ``toggle_test``, ``seam_test`` and ``quiet_test`` are the THREE cases, named rather than
    assumed. Principle 12 asks for two; the third exists because three agents independently
    warned, on the same night, that this registry's real risk is noise:

    * ``toggle_test`` proves a RENDERER refuses to report clean when the status says
      unmeasured. It may build the result by hand — the renderer is what is under test.
    * ``seam_test`` proves the real ``entrypoint``, driven for real, RETURNS unmeasured when
      it cannot measure. It must CALL the entrypoint and must NOT construct ``result_type``,
      because this is the seam where mocks lie: a substituted producer proves the logic and
      never crosses the boundary, and a hand-built result is the author's belief about
      production rather than production. *"In both cases the test agrees with the AUTHOR
      instead of with PRODUCTION"* — the #1197 author, about its own 1,416-green suite.
    * ``quiet_test`` proves the instrument does NOT convict a healthy input. A fail-loud
      control that fires on correct configurations gets muted, and a muted control is worse
      than the silence it replaced — so "it stays quiet when nothing is wrong" is a property
      to prove, not to hope for. Without this field the schema can express "it fires" and
      "it fails when disabled" but not "it is not merely always-on".

    ``disclosure_marker`` is the substring a rendered DISCLOSURE carries ("NOT RUN",
    "could-not-determine", "not-audited"). A disclosure — *I could not measure this* — and a
    finding — *I measured this and it is wrong* — are different facts with different
    urgencies, and collapsing them is this module's own defect one level up. Declaring the
    marker is what lets a reader, and the toggle test, tell the two apart in one report.

    ``disclosure_rate`` is how often this instrument discloses across real runs. An
    instrument that discloses on 94% of them is technically honest and practically silent,
    and that number is worth KNOWING rather than discovering as a habit. It is a measured
    figure with provenance, or the literal :data:`RATE_UNMEASURED` — never a guess, because a
    fabricated number in a registry about fabricated numbers would be the joke writing
    itself.

    ``incident`` names what paid for the entry; ``not_measured`` names what this instrument
    does not measure, so the figure cannot be quoted without its exclusions.
    """

    name: str
    module: str
    result_type: str
    entrypoint: str
    status: str
    status_kind: str
    unmeasured: Any
    counts: tuple[str, ...]
    receivers: tuple[str, ...]
    renderers: tuple[str, ...]
    toggle_test: str
    seam_test: str
    quiet_test: str
    disclosure_marker: str
    incident: str
    not_measured: str
    disclosure_rate: str = RATE_UNMEASURED
    guards: tuple[str, ...] = ()

    @property
    def guard_names(self) -> tuple[str, ...]:
        """Every name that counts as consulting this instrument's status."""
        return self.guards or (self.status,)

    def claims(self, receiver_tail: str) -> bool:
        """Whether a read reached through *receiver_tail* belongs to this instrument."""
        return receiver_tail in self.receivers

    @property
    def conforms(self) -> bool:
        """Whether the live result type actually carries the declared status contract.

        Read by the CLI so the table can show what is broken without a pytest run; the gate
        asserts on the same resolution, so the two can never disagree."""
        return not status_defects(self)


# ---------------------------------------------------------------------------
# The registered instruments
# ---------------------------------------------------------------------------

#: Ordered by module, then by name. Every entry either conforms or is a NAMED live defect —
#: the registry records what is true, not what is tidy, so an instrument missing its honesty
#: bit is enrolled and fails loudly rather than being left out to keep the table green.
REGISTRY: tuple[InstrumentEntry, ...] = (
    InstrumentEntry(
        name="security scan (credentials, sinks, web injection)",
        module="tools.dispatch_harness.green_quality.security",
        result_type="SecurityResult",
        entrypoint="scan_repo",
        status="measured",
        status_kind=STATUS_FIELD,
        unmeasured=False,
        counts=("findings", "files_scanned"),
        receivers=("self", "security"),
        renderers=(
            "tools.dispatch_harness.green_quality.security:SecurityResult.summary",
            "tools.dispatch_harness.green_quality.security:SecurityResult.is_clean",
            "tools.dispatch_harness.green_quality.band:_security_reasons",
            "tools.dispatch_harness.green_quality.card:_caveat_from_security",
        ),
        toggle_test="tests/security/test_instrument_toggles.py::test_security_scan_unmeasured_never_renders_clean",
        seam_test="tests/security/test_instrument_toggles.py::test_security_scan_seam_returns_unmeasured_on_a_missing_tree",
        quiet_test="tests/security/test_instrument_toggles.py::test_security_scan_stays_quiet_on_a_healthy_tree",
        disclosure_marker="could-not-determine",
        incident="#1182 - the scan that could not run would have banded A and read 'Looks clean'",
        not_measured="a credential in no listed provider format under a renamed identifier; "
                     "reachability of any flagged construct",
    ),
    InstrumentEntry(
        name="placeholder prose in delivered pages",
        module="tools.dispatch_harness.green_quality.placeholder_prose",
        result_type="ProseResult",
        entrypoint="scan_repo",
        status="measured",
        status_kind=STATUS_FIELD,
        unmeasured=False,
        # `applicable` is registered as a COUNT rather than as a second status, and the
        # distinction is deliberate. Only ONE field can be born unmeasured — a scan that never
        # ran cannot know whether the tree had pages either — so `applicable` is a CLAIM whose
        # value is meaningless without `measured`, which is exactly what the count rule bites
        # on. The four-way collapse this instrument really has to survive is enforced by
        # `disposition()` being the read every consumer makes.
        counts=("findings", "pages_scanned", "applicable"),
        receivers=("self", "prose"),
        renderers=(
            "tools.dispatch_harness.green_quality.placeholder_prose:ProseResult.disposition",
            "tools.dispatch_harness.green_quality.placeholder_prose:ProseResult.summary",
            "tools.dispatch_harness.green_quality.band:_prose_reasons",
            "tools.dispatch_harness.green_quality.card:_caveat_from_prose",
        ),
        toggle_test="tests/security/test_instrument_toggles.py::test_prose_scan_unmeasured_never_renders_clean",
        seam_test="tests/security/test_instrument_toggles.py::test_prose_scan_seam_returns_unmeasured_on_a_missing_tree",
        quiet_test="tests/security/test_instrument_toggles.py::test_prose_scan_stays_quiet_on_a_written_site",
        disclosure_marker="could-not-determine",
        incident="#1281 - a website is mostly words and nothing planned, authored or graded "
                 "any, so a site of lorem ipsum banded A and read 'Looks clean'",
        not_measured="whether the prose is any GOOD (that is #1280, and the operator's); "
                     "bland-but-genuine copy, which is textually indistinguishable from good "
                     "copy; text held in a database or CMS payload; non-English filler; text "
                     "assembled at runtime rather than delivered in a file",
    ),
    InstrumentEntry(
        name="requirement -> oracle-assertion traceability",
        module="tools.dispatch_harness.green_quality.traceability",
        result_type="TraceabilityResult",
        entrypoint="assess",
        status="available",
        status_kind=STATUS_FIELD,
        unmeasured=False,
        counts=("criteria", "oracle_test_count", "symbol_count"),
        receivers=("self",),
        renderers=(
            "tools.dispatch_harness.green_quality.traceability:TraceabilityResult.fingerprint",
            "tools.dispatch_harness.green_quality.traceability:TraceabilityResult.to_block",
            "tools.dispatch_harness.green_quality.traceability:CorpusAggregate.render",
        ),
        toggle_test="tests/security/test_instrument_toggles.py::test_traceability_unmeasured_never_renders_a_ratio",
        seam_test="tests/security/test_instrument_toggles.py::test_traceability_seam_returns_unavailable_without_a_first_party_index",
        quiet_test="tests/security/test_instrument_toggles.py::test_traceability_stays_quiet_on_a_resolvable_oracle",
        disclosure_marker="unavailable",
        incident="#1184 - oracle_coverage stamped 'unknown' on every GREEN ever produced",
        # L4-KILLS became MEASURED on 2026-08-07 (#1195). This line said it was not, and
        # would have gone on saying so: the field is free text, checked only for presence,
        # and the branch predates this file so `git merge-tree` reported no conflict. The
        # registry is the surface that OWNS "what does this instrument not measure" — a
        # reader asking it would have been told no, by the authority, while the measurement
        # sat in the same repository. State the CONDITION, not the absence: an absence is
        # falsified by any progress, a condition stays true and simply gets met more often.
        not_measured="L4-KILLS is CONDITIONAL, not universal — a criterion earns it only when a "
                     "banked oracle-mutation audit mutated that criterion's own subject, "
                     "unambiguously, and named one of its own asserting tests among the failures; "
                     "every criterion that does not hold for is graded at most L3 and counted in "
                     "l4.unmeasured. Also not measured: criteria-vs-goal fidelity (the criteria are "
                     "themselves model-authored from the goal; this measures exam-vs-criteria only)",
    ),
    InstrumentEntry(
        name="archetype regression probe (behaviour vs the last GREEN)",
        module="tools.dispatch_harness.green_quality.layer1",
        result_type="RegressionFinding",
        entrypoint="archetype_regression",
        status="measured",
        status_kind=STATUS_FIELD,
        unmeasured=False,
        counts=("regressed", "changed"),
        receivers=("regression", "reg"),
        renderers=(
            "tools.dispatch_harness.green_quality.layer1:Layer1Result.findings",
            "tools.dispatch_harness.green_quality.band:band_reasons",
            "tools.dispatch_harness.green_quality.card:_caveat_from_layer1",
            "tools.dispatch_harness.green_quality:GreenAuditResult.evidence_stamp",
            "tools.dispatch_harness.green_quality:corpus_block",
        ),
        toggle_test="tests/security/test_instrument_toggles.py::test_regression_unmeasured_is_reported_not_silent",
        seam_test="tests/security/test_instrument_toggles.py::test_regression_seam_returns_unmeasured_without_a_reference_green",
        quiet_test="tests/security/test_instrument_toggles.py::test_regression_stays_quiet_on_a_measured_clean_probe",
        disclosure_marker="regression probe NOT RUN",
        incident="#1223 - an unmeasured probe returns regressed=False, which renders as silence",
        not_measured="any behaviour the job's probe-set does not exercise",
    ),
    InstrumentEntry(
        name="seed divergence (did the coder rewrite what it was told to)",
        module="tools.dispatch_harness.green_quality.layer1",
        result_type="SeedDivergenceFinding",
        entrypoint="lint_seed_divergence",
        status="status",
        status_kind=STATUS_FIELD,
        unmeasured="unknown",
        counts=("flagged", "identical", "diverged"),
        receivers=("seed_divergence", "seed"),
        guards=("status", "measured"),
        renderers=(
            "tools.dispatch_harness.green_quality.layer1:Layer1Result.findings",
            "tools.dispatch_harness.green_quality.band:band_reasons",
            "tools.dispatch_harness.green_quality.card:_caveat_from_layer1",
            "tools.dispatch_harness.green_quality:GreenAuditResult.evidence_stamp",
            "tools.dispatch_harness.green_quality.layer1:Layer1Result.any_craft_residue",
            "tools.dispatch_harness.green_quality:corpus_block",
        ),
        toggle_test="tests/security/test_instrument_toggles.py::test_seed_divergence_unknown_is_reported_not_silent",
        seam_test="tests/security/test_instrument_toggles.py::test_seed_divergence_seam_returns_unknown_without_a_seed_root",
        quiet_test="tests/security/test_instrument_toggles.py::test_seed_divergence_stays_quiet_on_a_diverged_delivery",
        disclosure_marker="seed divergence UNKNOWN",
        incident="#1183 - lint_stale_readme keyed on a marker string edited out of the seed",
        not_measured="files outside SEED_FILES; whether a rewritten file is any good",
    ),
    InstrumentEntry(
        name="advisory ruff lint",
        module="tools.dispatch_harness.green_quality.layer1",
        result_type="Layer1Result",
        entrypoint="run_ruff_advisory",
        status="ruff_findings",
        status_kind=STATUS_SENTINEL,
        unmeasured=None,
        counts=("ruff_findings",),
        receivers=("self", "layer1"),
        renderers=(
            "tools.dispatch_harness.green_quality.layer1:Layer1Result.findings",
            "tools.dispatch_harness.green_quality.band:band_reasons",
        ),
        toggle_test="tests/security/test_instrument_toggles.py::test_ruff_not_run_renders_as_not_run",
        seam_test="tests/security/test_instrument_toggles.py::test_ruff_seam_returns_none_when_the_binary_cannot_be_resolved",
        quiet_test="tests/security/test_instrument_toggles.py::test_ruff_stays_quiet_when_it_measured_zero",
        disclosure_marker="ruff: NOT RUN",
        incident="#1189 - bare `ruff` was unresolvable, so the lint read clean on every night",
        not_measured="anything ruff's default rule set does not carry",
    ),
    InstrumentEntry(
        name="craft lint: dead seed scaffold",
        module="tools.dispatch_harness.green_quality.layer1",
        result_type="CraftFinding",
        entrypoint="lint_dead_scaffold",
        status="measured",
        status_kind=STATUS_FIELD,
        unmeasured=False,
        counts=("flagged",),
        receivers=("dead_scaffold", "f"),
        renderers=(
            "tools.dispatch_harness.green_quality.layer1:Layer1Result.findings",
            "tools.dispatch_harness.green_quality.band:band_reasons",
            "tools.dispatch_harness.green_quality.card:_caveat_from_layer1",
            "tools.dispatch_harness.green_quality:GreenAuditResult.evidence_stamp",
            "tools.dispatch_harness.green_quality.layer1:Layer1Result.any_craft_residue",
            "tools.dispatch_harness.green_quality:corpus_block",
        ),
        toggle_test="tests/security/test_instrument_toggles.py::test_craft_lint_unreadable_repo_is_reported_not_silent",
        seam_test="tests/security/test_instrument_toggles.py::test_craft_lint_seam_returns_unmeasured_on_a_missing_tree",
        quiet_test="tests/security/test_instrument_toggles.py::test_craft_lints_stay_quiet_on_a_real_tree",
        disclosure_marker="dead scaffold lint NOT RUN",
        incident="#1223 - an unreadable tree yields flagged=False, identical to a clean pass",
        not_measured="placeholder text that does not match _SCAFFOLD_MARKERS",
    ),
    InstrumentEntry(
        name="craft lint: stale skeleton README",
        module="tools.dispatch_harness.green_quality.layer1",
        result_type="CraftFinding",
        entrypoint="lint_stale_readme",
        status="measured",
        status_kind=STATUS_FIELD,
        unmeasured=False,
        counts=("flagged",),
        receivers=("stale_readme", "f"),
        renderers=(
            "tools.dispatch_harness.green_quality.layer1:Layer1Result.findings",
            "tools.dispatch_harness.green_quality.band:band_reasons",
            "tools.dispatch_harness.green_quality.card:_caveat_from_layer1",
            "tools.dispatch_harness.green_quality.layer1:Layer1Result.any_craft_residue",
            "tools.dispatch_harness.green_quality:corpus_block",
        ),
        toggle_test="tests/security/test_instrument_toggles.py::test_craft_lint_unreadable_repo_is_reported_not_silent",
        seam_test="tests/security/test_instrument_toggles.py::test_craft_lint_seam_returns_unmeasured_on_a_missing_tree",
        quiet_test="tests/security/test_instrument_toggles.py::test_craft_lints_stay_quiet_on_a_real_tree",
        disclosure_marker="stale README lint NOT RUN",
        incident="#1183 - the marker vanished from the shipped copy and the lint went blind, silently, for a week",
        not_measured="a README rewritten badly; any README name outside the four probed",
    ),
    InstrumentEntry(
        name="craft lint: no runnable entry point",
        module="tools.dispatch_harness.green_quality.layer1",
        result_type="CraftFinding",
        entrypoint="lint_no_entry_point",
        status="measured",
        status_kind=STATUS_FIELD,
        unmeasured=False,
        counts=("flagged",),
        receivers=("no_entry_point", "f"),
        renderers=(
            "tools.dispatch_harness.green_quality.layer1:Layer1Result.findings",
            "tools.dispatch_harness.green_quality.band:band_reasons",
            "tools.dispatch_harness.green_quality.card:_caveat_from_layer1",
            "tools.dispatch_harness.green_quality.layer1:Layer1Result.any_craft_residue",
            "tools.dispatch_harness.green_quality:corpus_block",
        ),
        toggle_test="tests/security/test_instrument_toggles.py::test_craft_lint_unreadable_repo_is_reported_not_silent",
        seam_test="tests/security/test_instrument_toggles.py::test_craft_lint_seam_returns_unmeasured_on_a_missing_tree",
        quiet_test="tests/security/test_instrument_toggles.py::test_craft_lints_stay_quiet_on_a_real_tree",
        disclosure_marker="entry point lint NOT RUN",
        incident="#1223 - 'repo not found' and 'entry point present' are the same CraftFinding",
        not_measured="whether a present entry point actually runs",
    ),
    InstrumentEntry(
        name="coder-test QA (the exam that cannot fail)",
        module="shared.fleet.coder_test_qa",
        result_type="CoderTestQAResult",
        entrypoint="scan_paths",
        status="measured",
        status_kind=STATUS_FIELD,
        unmeasured=False,
        counts=("findings", "files_scanned"),
        receivers=("self",),
        renderers=(
            "shared.fleet.coder_test_qa:CoderTestQAResult.to_evidence",
            "shared.fleet.coder_test_qa:CoderTestQAResult.clean",
        ),
        toggle_test="tests/security/test_instrument_toggles.py::test_coder_test_qa_unmeasured_is_not_clean",
        seam_test="tests/security/test_instrument_toggles.py::test_coder_test_qa_seam_returns_unmeasured_on_no_test_files",
        quiet_test="tests/security/test_instrument_toggles.py::test_coder_test_qa_stays_quiet_on_a_real_suite",
        disclosure_marker="measured",
        incident="#1170/#1195 - the PowerShell wrapper carries .Measured; the Python result does not",
        not_measured="a test that is wrong rather than unable to fail",
    ),
    InstrumentEntry(
        name="green-audit gaming fingerprints",
        module="tools.dispatch_harness.green_audit",
        result_type="GreenAuditResult",
        entrypoint="scan_tree",
        status="audited",
        status_kind=STATUS_FIELD,
        unmeasured=False,
        counts=("findings", "allowlisted", "files_scanned"),
        receivers=("self",),
        renderers=(
            "tools.dispatch_harness.green_audit:GreenAuditResult.to_sidecar_dict",
            "tools.dispatch_harness.green_audit:GreenAuditResult.gamed",
            "tools.dispatch_harness.green_audit:GreenAuditResult.summary_line",
        ),
        toggle_test="tests/security/test_instrument_toggles.py::test_green_audit_unaudited_is_not_clean",
        seam_test="tests/security/test_instrument_toggles.py::test_green_audit_seam_returns_unaudited_on_a_missing_tree",
        quiet_test="tests/security/test_instrument_toggles.py::test_green_audit_stays_quiet_on_a_scanned_tree",
        disclosure_marker="not-audited",
        incident="#832 - an unaudited tree stamps green_audit='clean' for #827's gaming signal",
        not_measured="gaming shapes outside the seven fingerprint classes",
    ),
    InstrumentEntry(
        name="oracle mutation (does the exam kill a broken implementation)",
        module="shared.fleet.oracle_mutation",
        result_type="dict",
        entrypoint="not_measured_evidence",
        status="is_measured",
        status_kind=STATUS_PREDICATE,
        unmeasured=None,
        counts=("oracle_mutation_killed", "oracle_mutation_ran"),
        receivers=(),
        renderers=(
            "tools.dispatch_harness.green_quality.mutation:evidence_stamp",
        ),
        toggle_test="tests/security/test_instrument_toggles.py::test_oracle_mutation_unmeasured_stamps_not_measured",
        seam_test="tests/security/test_instrument_toggles.py::test_oracle_mutation_seam_builds_unmeasured_evidence",
        quiet_test="tests/security/test_instrument_toggles.py::test_oracle_mutation_stays_quiet_on_a_measured_audit",
        disclosure_marker="not-measured",
        incident="#1195 item 2 - a mutant that never ran was scored SURVIVED",
        not_measured="per-criterion attribution (the score is whole-file killed/ran)",
    ),
    InstrumentEntry(
        name="behaviour-smoke contract (did the capture exercise what the plan declared)",
        module="shared.fleet.swap_ops",
        result_type="dict",
        entrypoint="_coerce_design_loop_result",
        status="smoke_contract_is_measured",
        status_kind=STATUS_PREDICATE,
        unmeasured=None,
        counts=("smoke_declared", "smoke_measured"),
        receivers=(),
        renderers=(
            "shared.fleet.swap_ops:smoke_contract_disposition",
            "shared.fleet.swap_driver:SwapDriver._smoke_contract_note",
        ),
        toggle_test="tests/security/test_instrument_toggles.py::test_smoke_contract_unmeasured_never_renders_exercised",
        seam_test="tests/security/test_instrument_toggles.py::test_smoke_contract_seam_returns_unavailable_on_a_blind_capture",
        quiet_test="tests/security/test_instrument_toggles.py::test_smoke_contract_stays_quiet_where_no_contract_applies",
        disclosure_marker="could-not-determine",
        incident="#823/#1289 - the declared arm of the web capture had a reader and NO writer, so "
                 "every web build degraded to a heuristic guess whose failure rendered as a soft "
                 "note; the honesty channel that fixed that was then rendered only in PowerShell, "
                 "leaving a Python reader unable to tell a graded pass from a lucky guess",
        not_measured="whether the declared action is the RIGHT one for the product (the ruler pins "
                     "the hooks; the 14B supplies only the labels); whether a heuristic run that "
                     "declares no contract clicked anything meaningful",
    ),
)


# ---------------------------------------------------------------------------
# Resolution (the gate imports the live instrument through these)
# ---------------------------------------------------------------------------


def resolve_attr(dotted_module: str, qualname: str) -> Any:
    """Resolve ``module`` + ``A.b`` to the live object, or raise.

    Walks the qualname so a method on a result type resolves as readily as a module-level
    function — the renderer sites use both forms."""
    obj: Any = importlib.import_module(dotted_module)
    for part in qualname.split("."):
        obj = getattr(obj, part)
    return obj


def parse_site(site: str) -> tuple[str, str]:
    """``"pkg.mod:Class.method"`` -> ``("pkg.mod", "Class.method")``."""
    module, _, qualname = site.partition(":")
    return (module, qualname)


def field_default(result_type: type, name: str) -> Any:
    """The DECLARED default of a dataclass field, or :data:`MISSING`.

    A ``default_factory`` is called, because a factory is how a mutable unmeasured value is
    declared and its product is the born state a caller receives."""
    if not is_dataclass(result_type):
        return MISSING
    for f in dataclass_fields(result_type):
        if f.name != name:
            continue
        if f.default is not MISSING:
            return f.default
        if f.default_factory is not MISSING:  # type: ignore[misc]
            return f.default_factory()  # type: ignore[misc]
        return MISSING
    return MISSING


def status_defects(entry: InstrumentEntry) -> list[str]:
    """Every way *entry*'s live result type fails the born-unmeasured contract.

    Empty list == conforming. Returned as prose rather than a bool because a gate that says
    "something is wrong" costs a reader the same time the defect did."""
    defects: list[str] = []
    if entry.status_kind == STATUS_PREDICATE:
        try:
            fn = resolve_attr(entry.module, entry.status)
        except (ImportError, AttributeError) as exc:
            return [f"predicate {entry.module}:{entry.status} does not resolve ({exc})"]
        if not callable(fn):
            defects.append(f"predicate {entry.module}:{entry.status} is not callable")
        return defects

    try:
        result_type = resolve_attr(entry.module, entry.result_type)
    except (ImportError, AttributeError) as exc:
        return [f"result type {entry.module}:{entry.result_type} does not resolve ({exc})"]
    if not is_dataclass(result_type):
        return [f"{entry.result_type} is not a dataclass, so its fields cannot be resolved"]

    names = {f.name for f in dataclass_fields(result_type)}
    if entry.status not in names:
        defects.append(
            f"{entry.result_type} has NO field {entry.status!r} - it cannot tell "
            f"'ran and found nothing' from 'did not run'. Add the status field and make "
            f"every renderer consult it."
        )
    else:
        default = field_default(result_type, entry.status)
        if default is MISSING:
            defects.append(
                f"{entry.result_type}.{entry.status} has no declared default - an "
                f"instrument must be BORN unmeasured, so a result assembled without "
                f"running the check reads as ignorance rather than as a pass."
            )
        elif default != entry.unmeasured:
            defects.append(
                f"{entry.result_type}.{entry.status} defaults to {default!r}, not the "
                f"registered unmeasured value {entry.unmeasured!r}"
            )
    for count in entry.counts:
        if count not in names:
            defects.append(f"{entry.result_type} has no registered count field {count!r}")
    return defects


# ---------------------------------------------------------------------------
# The renderer analysis (part 2 — the half that makes the registry real)
# ---------------------------------------------------------------------------


def dotted(node: ast.AST) -> Optional[str]:
    """A pure ``Name``/``Attribute`` chain as a dotted string, else ``None``.

    ``self.regression.regressed`` -> ``"self.regression.regressed"``. Anything with a call,
    a subscript or an expression in the chain is not a stable path and is not tracked —
    under-matching, which costs a missed violation rather than a false one."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _dotted_paths(node: ast.AST) -> set[str]:
    """Every stable ``Name``/``Attribute`` chain inside one expression."""
    out: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, (ast.Name, ast.Attribute)):
            path = dotted(n)
            if path:
                out.add(path)
    return out


def _boolean_context_nodes(fn: ast.AST) -> set[int]:
    """Node ids sitting in a BOOLEAN position — where ``None`` and ``0`` collapse together.

    The recurring mechanic of instances 3, 4 and 5 is exactly this position: ``if result.x:``
    reads "did not run" and "ran and found nothing" as the same answer."""
    marked: set[int] = set()
    for node in ast.walk(fn):
        if isinstance(node, (ast.If, ast.While, ast.IfExp)):
            marked.add(id(node.test))
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            marked.add(id(node.operand))
        elif isinstance(node, ast.BoolOp):
            marked.update(id(v) for v in node.values)
        elif isinstance(node, ast.Assert):
            marked.add(id(node.test))
        elif isinstance(node, ast.comprehension):
            marked.update(id(c) for c in node.ifs)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == "bool" and node.args:
            marked.add(id(node.args[0]))
    return marked


def _none_tested_paths(fn: ast.AST) -> set[str]:
    """Dotted paths explicitly compared to ``None`` — the disambiguation a sentinel needs."""
    out: set[str] = set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.Compare):
            continue
        if not any(isinstance(op, (ast.Is, ast.IsNot)) for op in node.ops):
            continue
        operands = [node.left, *node.comparators]
        if not any(isinstance(o, ast.Constant) and o.value is None for o in operands):
            continue
        for operand in operands:
            path = dotted(operand)
            if path:
                out.add(path)
    return out


def _parent_map(fn: ast.AST) -> dict[int, ast.AST]:
    """Child node id -> parent node, so the analysis can walk UP from a read.

    Built once per renderer rather than per read: the scope question ("what actually decides
    whether this line runs?") can only be answered upward, and :func:`ast.walk` only goes
    down."""
    parents: dict[int, ast.AST] = {}
    for node in ast.walk(fn):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    return parents


def _statement_blocks(node: ast.AST) -> list[list[ast.stmt]]:
    """Every statement list hanging off *node* — body, orelse, finalbody, handler bodies."""
    blocks: list[list[ast.stmt]] = []
    for attr in ("body", "orelse", "finalbody"):
        block = getattr(node, attr, None)
        if isinstance(block, list) and all(isinstance(s, ast.stmt) for s in block):
            blocks.append(block)
    return blocks


def _leaves_the_block(body: list[ast.stmt]) -> bool:
    """Whether a block's last statement leaves the flow — the guard-clause shape.

    ``if not self.measured: return "could-not-determine"`` establishes the guard for every
    statement after it, which is how most renderers in this tree are actually written. An
    analysis that only understood ``and`` would convict all of them."""
    return bool(body) and isinstance(
        body[-1], (ast.Return, ast.Raise, ast.Continue, ast.Break))


def guarding_expressions(node: ast.AST, parents: dict[int, ast.AST]) -> list[ast.AST]:
    """The expressions that actually DECIDE whether *node* is reached.

    THE DIFFERENCE BETWEEN MENTIONING A GUARD AND USING ONE, and the reason this function
    exists rather than a set of every name in the body. Collecting the whole function's names
    made any appearance of ``self.measured`` — a dead assignment, a dict value, an unrelated
    branch — excuse EVERY collapsing read of that instrument in that function. It was
    exploitable on live code, not only on synthetics: adding ``_dead = reg.measured`` to
    ``card.py`` let both real guards be deleted with the gate still green, and dropping ONE of
    ``band.py``'s two regression guards was invisible because the other still mentioned it.
    The innocent shape passed too — a renderer emitting ``{"measured": self.measured,
    "status": "clean" if not self.findings else "dirty"}`` shipped the defect and was
    acquitted, with nobody gaming anything.

    Three arrangements count, because these are the three that genuinely short-circuit:

    * a sibling operand of an enclosing ``and`` (``if f.measured and f.flagged:``);
    * the test of an enclosing ``if`` / ``while`` / conditional expression, whichever branch
      the read sits in — both branches know the answer;
    * a PRECEDING guard clause in the same block that leaves the flow
      (``if not self.measured: return ...``), which dominates everything after it.

    ``or`` is deliberately NOT among them: ``if f.measured or f.flagged:`` reaches the read
    precisely when the guard was false, which is the opposite of guarding it.

    RESIDUE, named AND enforced rather than asserted: an ALIASED guard (``ok = f.measured``
    then ``if ok and f.flagged:``) reads as unguarded here, and convicting it would be a FALSE
    ACCUSATION out of a control whose whole product is certification. Tracing the alias would
    mean a dataflow analysis, and an analysis that guesses wrong in THIS direction acquits;
    so the alias is REFUSED instead, by :func:`guard_alias_reads`, which fails the standing
    gate the moment one appears in a registered renderer. Deny-by-default aimed at the
    analysis's own blind spot: the two honest responses are to inline the guard or to argue a
    :data:`JUSTIFIED_COLLAPSES` entry, never to widen this function back toward a mention
    check. An earlier draft of this docstring stated instead that no alias existed in the
    tree — a claim about the state of the world on one day, which a docstring cannot keep
    true and no reader can check."""
    out: list[ast.AST] = []
    child: ast.AST = node
    parent = parents.get(id(node))
    while parent is not None:
        if isinstance(parent, ast.BoolOp) and isinstance(parent.op, ast.And):
            out.extend(v for v in parent.values if v is not child)
        elif isinstance(parent, (ast.If, ast.While, ast.IfExp)) and child is not parent.test:
            out.append(parent.test)
        for block in _statement_blocks(parent):
            index = next((i for i, s in enumerate(block) if s is child), None)
            if index is None:
                continue
            out.extend(s.test for s in block[:index]
                       if isinstance(s, ast.If) and not s.orelse and _leaves_the_block(s.body))
        child = parent
        parent = parents.get(id(parent))
    return out


def guard_alias_reads(fn: ast.AST, entry: InstrumentEntry) -> list[str]:
    """Every place *entry*'s guard is bound to a LOCAL NAME inside one renderer.

    THE ANALYSIS'S OWN BLIND SPOT, refused rather than tolerated. :func:`guarding_expressions`
    matches a guard by its dotted PATH, so ``ok = f.measured`` followed by ``if ok and
    f.flagged:`` is a genuine guard the analysis cannot see — and the analysis would convict
    it. A false conviction is the one failure this gate must never produce: the whole product
    of an instrument-honesty control is that its verdicts can be believed, and a report
    carrying one accusation nobody can reproduce is a report that gets muted.

    Refusing rather than tracing is deliberate. Following the alias means dataflow — rebinding,
    branches, closures — and an approximation that errs in this direction ACQUITS, which is the
    original defect back in a subtler shape. Refusing errs toward a loud, specific, cheaply
    fixed complaint: inline the guard, or argue the collapse into
    :data:`JUSTIFIED_COLLAPSES`.

    Receiver aliases are untouched, and that distinction is the reason this is narrow enough to
    be usable: ``reg = layer1.regression`` binds an INSTRUMENT, and the analysis follows those
    fine because ``reg`` is a registered receiver. Only a binding of the STATUS itself is
    refused."""
    if entry.status_kind == STATUS_PREDICATE:
        return []
    out: list[str] = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)):
            targets = [node.target]
        else:
            continue
        value = getattr(node, "value", None)
        if value is None:
            continue
        path = dotted(value)
        if not path or "." not in path:
            continue
        if path.rsplit(".", 1)[-1] not in entry.guard_names:
            continue
        if not entry.claims(_receiver_tail(path)):
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                out.append(
                    f"line {node.lineno}: `{target.id} = {path}` binds this instrument's "
                    f"status to a local name. The guard analysis matches on the PATH, so a "
                    f"later `if {target.id} and ...` is invisible to it and the read would be "
                    f"falsely convicted. Consult `{path}` directly at the branch, or argue "
                    f"the collapse into JUSTIFIED_COLLAPSES."
                )
    return out


def _receiver_tail(path: str) -> str:
    """The last segment of the receiver of a dotted read.

    ``"layer1.seed_divergence.flagged"`` -> ``"seed_divergence"``; ``"self.findings"`` ->
    ``"self"``; a bare ``"findings"`` -> ``""``."""
    head = path.rsplit(".", 1)[0] if "." in path else ""
    return head.rsplit(".", 1)[-1] if head else ""


def count_reads_in_boolean_context(fn: ast.AST, counts: "frozenset[str] | set[str]") \
        -> list[tuple[ast.Attribute, str]]:
    """Every ``X.count`` read sitting in a boolean position, as ``(node, dotted path)``.

    The shared substrate of both halves of the sweep: :func:`falsy_collapse_defects` asks
    whether the read is GUARDED, :func:`unclaimed_reads` asks whether any entry OWNS it."""
    marked = _boolean_context_nodes(fn)
    out: list[tuple[ast.Attribute, str]] = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Attribute) or node.attr not in counts:
            continue
        if id(node) not in marked:
            continue
        path = dotted(node)
        if path is not None:
            out.append((node, path))
    return out


def falsy_collapse_defects(fn: ast.AST, entry: InstrumentEntry) -> list[str]:
    """Every falsy-collapse of *entry*'s counts in one renderer body, named by line.

    The guard is PATH-SCOPED, not name-scoped, and that is what makes the check sound: a
    function may render several instruments, so consulting ``self.seed_divergence.measured``
    says nothing about ``self.regression.regressed``. The guard for ``P.count`` is therefore
    one of ``P.<guard>`` on the same receiver path ``P``, never a bare mention of the word.
    The read is charged to this entry only when the receiver TAIL is one it claims, so a
    field name shared across sibling instruments (``flagged``) does not make every sibling
    answer for every read.

    A :data:`STATUS_SENTINEL` demands MORE: the status IS the count, so a mention of it is
    the collapsing read itself, and only an explicit ``is None`` / ``is not None`` test
    disambiguates. That is #1189's fix written down as a rule.

    The guard must GUARD, not merely appear: see :func:`guarding_expressions` for what counts
    and why a function-wide mention check was worse than no check at all.
    """
    if entry.status_kind == STATUS_PREDICATE:
        # A dict-shaped instrument has no attribute chain to trace; its contract is that the
        # renderer CALLS the predicate, which :func:`predicate_defects` checks instead.
        return []

    parents = _parent_map(fn)
    defects: list[str] = []

    for node, path in count_reads_in_boolean_context(fn, set(entry.counts)):
        if not entry.claims(_receiver_tail(path)):
            continue
        scope = guarding_expressions(node, parents)
        none_tested = {p for expr in scope for p in _none_tested_paths(expr)}
        if entry.status_kind == STATUS_SENTINEL:
            if path in none_tested:
                continue
            defects.append(
                f"line {node.lineno}: `{path}` is tested for truth with no `is None` "
                f"check deciding whether this line runs. It is an Optional sentinel: `None` "
                f"(did not run) and `0` (ran, found nothing) are both falsy and mean "
                f"opposite things."
            )
            continue
        receiver = path.rsplit(".", 1)[0] if "." in path else ""
        wanted = [f"{receiver}.{g}" if receiver else g for g in entry.guard_names]
        consulted = {p for expr in scope for p in _dotted_paths(expr)}
        if any(w in consulted for w in wanted) or path in none_tested:
            continue
        defects.append(
            f"line {node.lineno}: `{path}` is tested for truth without "
            f"{' or '.join('`' + w + '`' for w in wanted)} deciding whether this line runs "
            f"- an unmeasured instrument renders identically to a clean one. (Mentioning the "
            f"guard elsewhere in the function does not count: it must be an enclosing test, "
            f"a sibling of an `and`, or a preceding guard clause that returns.)"
        )
    return defects


def predicate_defects(fn: ast.AST, entry: InstrumentEntry) -> list[str]:
    """Whether a :data:`STATUS_PREDICATE` renderer actually calls the predicate.

    A dict-shaped instrument carries no attribute the AST can trace, so the only checkable
    contract is that the renderer ASKS. It is the weakest of the three checks and says so."""
    if entry.status_kind != STATUS_PREDICATE:
        return []
    called = {
        (n.func.id if isinstance(n.func, ast.Name) else
         n.func.attr if isinstance(n.func, ast.Attribute) else "")
        for n in ast.walk(fn) if isinstance(n, ast.Call)
    }
    if entry.status in called:
        return []
    return [(f"never calls `{entry.status}()`, so it cannot tell an unmeasured evidence "
             f"blob from a measured one")]


#: The minimum length of a justification. Short enough to write, long enough that "n/a",
#: "false positive" and "by design" cannot be it — each of those asserts rather than argues.
JUSTIFICATION_MIN_CHARS = 80

#: Falsy-collapses that are CORRECT, keyed ``"<renderer site>#<dotted path>"``.
#:
#: The escape hatch, and the thing most likely to hollow this gate out over time, so it is
#: built to resist that: every member must still correspond to a live collapse (a stale
#: justification is a defect the gate removes rather than a comment nobody re-reads), and a
#: reason shorter than :data:`JUSTIFICATION_MIN_CHARS` is refused. Adding a member is a
#: REVIEWABLE ACT — an argument someone can disagree with, not a suppression.
#:
#: The distinction that earns a place here: this class of defect is one-sided (all nine 2026-
#: 07-30 instances erred toward LOOKING FINE), so the rule targets renderers that could
#: render a false CLEAN. A renderer whose falsy branch produces an ACCUSATION fails in the
#: opposite direction, where an unmeasured guard would manufacture the false alarm.
JUSTIFIED_COLLAPSES: dict[str, str] = {
    "tools.dispatch_harness.green_audit:GreenAuditResult.gamed#self.findings": (
        "`gamed` is a downgrade TRIGGER, so its falsy branch is an absence of accusation, "
        "not a clean bill of health: gating it on `audited` would make an unaudited tree "
        "accuse the coder of gaming, which is the false-alarm mirror of this defect class. "
        "The clean-vs-unmeasured half of the same question lives in `to_sidecar_dict`, where "
        "`green_audit` renders three-way (gamed / clean / not-audited) and IS guarded."
    ),
}

#: Boolean-context reads inside a registered renderer that belong to no instrument, each with
#: the reason it is not one. A member is a REVIEWABLE ACT on the same terms as
#: :data:`JUSTIFIED_COLLAPSES`. Deliberately tiny — a long list means the sweep has been
#: talked out of its job.
JUSTIFIED_NON_INSTRUMENT_READS: dict[str, str] = {
    "card.caveat": (
        "the card's own rendered caveat, already derived FROM the registered instruments by "
        "_caveat_from_security / _caveat_from_layer1 - a second-order read of an instrument "
        "that was itself guarded, not an instrument"
    ),
}


def unclaimed_reads(fn: ast.AST) -> list[tuple[int, str]]:
    """Boolean-context reads of ANY registered count field that no entry claims.

    THE OTHER TEETH, and the reason the registry is not merely a table someone maintains: a
    new grader wired into a registered renderer — ``if layer1.new_lint.flagged:`` — is read
    by no entry's receivers and surfaces here BY NAME, so the choice becomes "register it or
    argue why it is not an instrument" rather than "nobody noticed".

    Bounded honestly: it can only see a read that reuses a count field name already in the
    table. A grader whose fields are all novel, or that is rendered somewhere no entry lists,
    is outside this sweep — which is why the module docstring names that residue."""
    all_counts = {c for e in REGISTRY for c in e.counts}
    out: list[tuple[int, str]] = []
    for node, path in count_reads_in_boolean_context(fn, all_counts):
        tail = _receiver_tail(path)
        if any(e.claims(tail) and node.attr in e.counts for e in REGISTRY):
            continue
        if path in JUSTIFIED_NON_INSTRUMENT_READS:
            continue
        out.append((node.lineno, path))
    return out


def renderer_source(site: str) -> tuple[Path, ast.AST]:
    """The source file and parsed body of a ``module:qualname`` renderer.

    Read from disk and parsed rather than introspected, so a decorator, a property or a
    ``functools`` wrapper cannot hide the body the gate is meant to read."""
    module_name, qualname = parse_site(site)
    module = importlib.import_module(module_name)
    path = Path(inspect.getsourcefile(module) or "")
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    target = qualname.split(".")[-1]
    owner = qualname.split(".")[0] if "." in qualname else None

    scopes: list[ast.AST] = [tree]
    if owner:
        scopes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == owner]
    for scope in scopes:
        for node in ast.walk(scope):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == target:
                return (path, node)
    raise LookupError(f"renderer {site} not found in {path}")


# ---------------------------------------------------------------------------
# CLI — so the registry can be READ and RUN, not merely written to
# ---------------------------------------------------------------------------


def collapse_key(site: str, path: str) -> str:
    """The :data:`JUSTIFIED_COLLAPSES` key for one collapse at one renderer site."""
    return f"{site}#{path}"


def renderer_defects(site: str, entry: InstrumentEntry) -> list[str]:
    """Every unjustified defect of *entry* at one renderer site, named by line.

    The single call the gate and the CLI both use, so the two can never disagree about what
    is broken. Justified collapses are filtered HERE rather than inside the analysis, which
    keeps :func:`falsy_collapse_defects` a pure statement of the rule and the suppression a
    separate, inspectable act."""
    _path, fn = renderer_source(site)
    out: list[str] = []
    for defect in falsy_collapse_defects(fn, entry):
        collapsed = _defect_path(defect)
        if collapsed and collapse_key(site, collapsed) in JUSTIFIED_COLLAPSES:
            continue
        out.append(defect)
    out.extend(predicate_defects(fn, entry))
    # Refused here rather than in the analysis: an aliased guard is not a dishonest renderer,
    # it is a renderer this analysis cannot read, and shipping a verdict it cannot support is
    # the one failure a certification control must not have.
    out.extend(guard_alias_reads(fn, entry))
    return out


def _defect_path(defect: str) -> str:
    """The dotted path a defect message names, for matching against a justification."""
    start = defect.find("`")
    end = defect.find("`", start + 1)
    return defect[start + 1:end] if 0 <= start < end else ""


def live_collapse_keys() -> set[str]:
    """Every collapse the analysis currently finds, justified or not.

    Lets the gate delete a justification whose defect is gone — a suppression that outlives
    its subject is how an exclusion list turns into a list of things nobody rechecks."""
    keys: set[str] = set()
    for entry in REGISTRY:
        for site in entry.renderers:
            try:
                _path, fn = renderer_source(site)
            except (ImportError, LookupError, OSError):
                continue
            for defect in falsy_collapse_defects(fn, entry):
                path = _defect_path(defect)
                if path:
                    keys.add(collapse_key(site, path))
    return keys


def audit(entries: "tuple[InstrumentEntry, ...] | list[InstrumentEntry] | None" = None) \
        -> list[tuple[InstrumentEntry, list[str]]]:
    """Every entry with its live defects — the whole table's current honesty, in one call.

    Covers both halves: the born-unmeasured contract on the result type, and every renderer
    that consumes it. A caller reading only the first half would see a registry of instruments
    that all carry a status bit nobody consults.

    THE ASSEMBLED PATH, and the reason it takes *entries* rather than closing over
    :data:`REGISTRY`. A control about controls fails most easily by being proved off in
    PIECES. On 2026-07-30 a brand-new structural gate for this very defect class convicted
    nothing: ``REMEDY_NAMES & {names} | {attrs}`` binds as ``(REMEDY_NAMES & {names}) |
    {attrs}``, ``{attrs}`` is non-empty for any real module, so the guard was permanently
    truthy — and its own proved-off test missed it because it drove ONE HELPER IN ISOLATION
    and never the composed guard. Taking the entry list here lets this gate's toggle drive
    THIS function — status resolution, renderer analysis and justification filtering
    together — over a deliberately broken instrument, which is the only arrangement that can
    catch the same mistake in this file."""
    out: list[tuple[InstrumentEntry, list[str]]] = []
    for entry in (REGISTRY if entries is None else tuple(entries)):
        defects = list(status_defects(entry))
        for site in entry.renderers:
            try:
                defects.extend(f"{site}: {d}" for d in renderer_defects(site, entry))
            except (ImportError, LookupError, OSError) as exc:
                defects.append(f"{site}: renderer does not resolve ({type(exc).__name__}: {exc})")
        out.append((entry, defects))
    return out


def main(argv: "list[str] | None" = None) -> int:
    """Print the registry with each entry's live conformance. Exit 1 if any entry is broken.

    Read-only. The gate asserts on the same resolution; this exists so the table can be
    consulted without a pytest run, which is what makes it a READ surface rather than a
    registration duty."""
    import argparse

    p = argparse.ArgumentParser(
        prog="instrument_registry",
        description="Which graders can tell 'found nothing' from 'did not look'.",
    )
    p.add_argument("-v", "--verbose", action="store_true", help="show renderers and exclusions")
    args = p.parse_args(argv)

    broken = 0
    for entry, defects in audit():
        mark = "OK  " if not defects else "FAIL"
        print(f"{mark} {entry.name}")
        print(f"       {entry.module}:{entry.result_type}  status={entry.status} "
              f"({entry.status_kind}, unmeasured={entry.unmeasured!r})")
        for d in defects:
            broken += 1
            print(f"       -> {d}")
        if args.verbose:
            for r in entry.renderers:
                print(f"       renders: {r}")
            print(f"       not measured: {entry.not_measured}")
    print(f"\n{len(REGISTRY)} instruments registered, {broken} live defect(s).")
    print("A gate checks the FORM of a REGISTERED instrument. It cannot see one nobody "
          "registered,\nnor judge whether a measured=True is honest.")
    return 0 if broken == 0 else 1


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
