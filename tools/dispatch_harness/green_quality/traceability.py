"""Requirement → oracle-assertion traceability (the coverage a GREEN actually PROVED).

Design SSOT: ``docs/design/oracle_coverage_traceability_DESIGN.md``. Read that first — it
records what was measured to justify this module's existence and what it deliberately does
NOT measure.

Every GREEN the battery has banked since 2026-07-22 carries
``green_class: GREEN-UNVERIFIED`` / ``oracle_coverage=unknown``. Two distinct defects hide
behind that one stamp, and only one of them is about a missing map:

* the incumbent #821 map (``oracle_qa.request_coverage_map``) asks the 14B for the
  ``{criterion_id: [test_name]}`` declaration and stamps ``unknown`` whenever the emission
  does not parse — a model-dependent stage that went silent while the scorecard reported
  nothing wrong;
* and its covered-predicate is *"the mapper named a test, and that test touches ANY
  first-party symbol"*, which a declaration mapping every criterion to every test saturates.
  Driven over the real 2026-07-29 B2/B4 oracles it returns 6/6 for both.

So a map alone cannot make ``GREEN-VERIFIED`` mean anything: repairing the model call would
have made the class reachable on a predicate that rewards a lazy mapper. This module supplies
the missing half — DETERMINISTIC evidence, graded by strength, computed from artifacts the run
already banked (``acceptance.json`` + the seeded ``job-oracle-*``), with no model in the
loop and no network.

The ladder (:data:`LEVELS`), weakest first::

    UNDECIDABLE  no subject could be derived and nothing declared one  -> not a number
    L0 GAP       a subject WAS derived; no test exercises it           -> a real hole
    L1 DECLARED  a mapper named a real test                            -> assertion, not evidence
    L2 BOUND     a test exercises the criterion's OWN subject          -> AST evidence
    L3 ASSERTED  that test ASSERTS on that subject                     -> AST evidence
    L4 KILLS     that test fails when the subject is mutated           -> MUTATION evidence

The headline counts **L3 and above**. L1 is reported but never counted as covered — the
distance between L1 and L3 is precisely the leniency this instrument exists to measure.

L4 is a REFINEMENT of L3, never a route to it. AST evidence establishes that an assertion
bears on the subject; only mutation can establish that the assertion would have caught the
subject being wrong, and that evidence comes from the run's banked ``oracle-mutation.json``
(#828), folded per-symbol by :func:`fold_mutation_attribution`. Because mutant selection is
capped and operator-diverse, most criteria's subjects are never mutated on a given night —
so L4 is CONDITIONAL by construction, and :data:`NOT_MEASURED` states the condition rather
than claiming the rung is now universal. ``L4 killed:2 survived:1 unmeasured:3`` and
``L4 not measured`` are both honest stamps; which one appears is a fact about the run.

Honesty invariants, all load-bearing and all enforced in code rather than merely documented:

* **Not-knowing never reads as passing.** A criterion whose subject cannot be derived is
  ``UNDECIDABLE`` — its own count, never folded into covered OR uncovered — and
  ``undecidable > 0`` makes :func:`TraceabilityResult.verified_class` unreachable. An
  instrument that goes blind must produce a WORSE class, never a clean one.
* **Errors flow toward "can't tell".** Subject derivation requires every significant token of
  a symbol to appear in the criterion (a subset rule, not an overlap score), so a vocabulary
  mismatch under-matches into ``UNDECIDABLE`` rather than over-matching into a false ``L3``.
  The heuristic can cost precision; it must never mint coverage.
* **A subject must belong to the deliverable, and that is RESOLVED rather than assumed.**
  First-party status comes from what the delivered tree actually provides
  (:class:`FirstPartyIndex`, built by :func:`resolve_first_party` from the run's own banked
  resolve-probe). Under the denylist this replaced, every root nobody had thought of was
  first-party by default, and an oracle importing ``mean`` from ``statistics`` handed a
  criterion a subject the deliverable never wrote. Unresolvable → ``available=False``.
* **An assertion counts only when it BEARS ON the subject.** L3 asks what the ``assert``
  actually constrains — the subject named in its subtree, or reached from it through a local
  read back from the subject (:func:`trace_test`) — never the weaker "this test calls the
  subject somewhere and asserts something somewhere", which ``assert True`` satisfies.
* **No ratio is ever emitted alone.** Every stamp carries the four-way split plus the
  run's own L4 disclosure, so the figure cannot be quoted without its exclusions. When
  attribution is missing the stamp says the rung was not measured AT ALL for that run —
  going blind must never render like measuring and finding nothing wrong.
* **ADVISORY / fail-soft**, the ``green_quality`` package contract: no verdict field, no
  exception escapes :func:`assess_run`, and an unusable input yields ``available=False`` with
  a reason — never a number.

ECOSYSTEMS (#1348). The oracle a run seeds is not always Python. A node job — a WEBSITE, the
surface the operator says he wants most — seeds ``job-oracle-<name>.mjs``, and until this was
fixed the discovery glob read ``job-oracle-*.py``, so every one of them was invisible. The
instrument then recorded ``no seeded job oracle in the run dir``: a sentence that is FALSE
(the oracle is right there, banked beside the sidecar) and that misdirects, sending anyone
chasing low coverage to hunt a seeding step that works fine. Requirement coverage had
therefore never once run on a website — a large part of why Definition-of-Done capability 17
still reads ARMED with no run ever stamped ``GREEN-VERIFIED``.

Both halves are fixed here, and the FLOOR is the more important of the two:

* discovery finds a seeded oracle of ANY ecosystem, and the three states an assessor can be
  in are three DIFFERENT sentences — no oracle exists / an oracle exists whose ecosystem this
  assessor cannot read (naming the ecosystem and the limit) / an oracle exists and could not
  be parsed. An instrument that cannot read something must say THAT, never report an absence;
* and node oracles are then actually assessed, on the same ladder, with the same
  precision-first rule (under-match into ``UNDECIDABLE``, never over-match into a false L3).

The JavaScript tokenising is REUSED, not rewritten: :mod:`shared.fleet.oracle_qa` grew one
for #1342's node vacuity pass and this module imports it. A second tokeniser would not be a
duplicate but a divergence — two instruments disagreeing about what a test body contains,
neither wrong on its own terms. What is NOT reused is that module's assertion regex as a
COVERAGE predicate: there a generous match withholds a refusal (forgiving), here it would
mint a level (over-crediting), so the asymmetry inverts and this module keeps its own
stricter assert-site rule. See :data:`_JS_ASSERT_SITE_RE`.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from shared.fleet.oracle_qa import (
    NODE_ASSERTION_RE,
    node_declared_name,
    node_import_bindings,
    node_mask,
    node_test_bodies,
)

TRACEABILITY_SCHEMA = "traceability/v1"

#: The advisory sidecar this module writes into a run dir. Distinct from #832's
#: ``green-audit.json`` (integrity) and #837's ``green-quality.json`` (band) — distinct
#: filename, distinct keys, distinct concern.
TRACEABILITY_SIDECAR_NAME = "traceability.json"

# ---------------------------------------------------------------------------
# The ladder
# ---------------------------------------------------------------------------

#: No subject could be derived for the criterion and no mapper declared one. NOT a coverage
#: gap and NOT coverage — we cannot say, and saying so is the whole point.
LEVEL_UNDECIDABLE = "UNDECIDABLE"
#: A subject WAS derived, and no test in the oracle exercises it. A real, nameable hole.
LEVEL_GAP = "L0-GAP"
#: A mapper (the 14B) named a real test for this criterion. The mapper's assertion is the
#: only evidence; retained for measurement, never counted as covered.
LEVEL_DECLARED = "L1-DECLARED"
#: Some test exercises the criterion's own derived subject (AST-verified).
LEVEL_BOUND = "L2-BOUND"
#: That test carries an ``assert`` whose subtree references the subject (AST-verified) — not
#: merely a no-raise call.
LEVEL_ASSERTED = "L3-ASSERTED"
#: The criterion's own asserting test demonstrably FAILS when the criterion's own subject is
#: mutated. Stamped only from banked mutation attribution (:class:`MutationAttribution`); a
#: criterion with no attributable mutant stays at :data:`LEVEL_ASSERTED` and says why.
LEVEL_KILLS = "L4-KILLS"

#: ---------------------------------------------------------------------------
#: Ecosystems
#: ---------------------------------------------------------------------------
#: The language an oracle is written in. Load-bearing for HONESTY before it is load-bearing
#: for coverage: the three states an assessor can be in — nothing was seeded, something was
#: seeded that this assessor cannot read, something was seeded and would not parse — are
#: three different facts about a run, and collapsing any two of them into one sentence is how
#: an instrument comes to report an absence that is not there.
ECOSYSTEM_PYTHON = "python"
ECOSYSTEM_NODE = "node"
#: A seeded oracle whose suffix names no ecosystem this module knows. Never silently skipped:
#: it produces its own reason, naming the file, so a reader can see WHAT was found.
ECOSYSTEM_UNKNOWN = "unknown"

#: Human names for the reason strings — the reader of an ``available=false`` sidecar is being
#: told what the instrument met, and "node" is a runtime while "JavaScript" is the language.
ECOSYSTEM_LABELS: "dict[str, str]" = {
    ECOSYSTEM_PYTHON: "Python",
    ECOSYSTEM_NODE: "JavaScript (node)",
    ECOSYSTEM_UNKNOWN: "of no ecosystem this assessor recognises",
}

#: Suffix → ecosystem. ``.ts`` is deliberately ABSENT: a TypeScript oracle would tokenise
#: almost-correctly here (type annotations are not JavaScript), and almost-correctly is the
#: one outcome this module must not produce. It falls to :data:`ECOSYSTEM_UNKNOWN` and says so.
ORACLE_SUFFIX_ECOSYSTEM: "dict[str, str]" = {
    ".py": ECOSYSTEM_PYTHON,
    ".mjs": ECOSYSTEM_NODE,
    ".cjs": ECOSYSTEM_NODE,
    ".js": ECOSYSTEM_NODE,
}

#: Every level, weakest → strongest (a stable order for the count map, so the block always
#: carries the full ladder including the levels that did not fire).
LEVELS: tuple[str, ...] = (
    LEVEL_UNDECIDABLE,
    LEVEL_GAP,
    LEVEL_DECLARED,
    LEVEL_BOUND,
    LEVEL_ASSERTED,
    LEVEL_KILLS,
)

#: The levels that COUNT as covered. L1 is deliberately absent: a mapper's say-so is not
#: evidence. Widening this set is the one edit that would lower the bar — the anti-tuning
#: regression lock in ``tests/integration/test_oracle_traceability.py`` fails if it grows.
COVERED_LEVELS: frozenset[str] = frozenset({LEVEL_ASSERTED, LEVEL_KILLS})

#: Named, in-band, on every emission: what this pass does not measure. The community-grade
#: "name what was NOT measured" discipline, aimed at an integrity instrument.
#:
#: The L4 entry states a CONDITION rather than an absence. The rung became reachable when
#: ``shared/fleet/oracle_mutation.py`` began banking per-mutant attribution, but reachable is
#: not the same as always measured: mutant selection is capped and operator-diverse, so most
#: criteria's subjects are never mutated on a given night. A run's own unmet condition is
#: named per-criterion in ``criteria[].l4`` and counted in ``l4.unmeasured``;
#: :meth:`TraceabilityResult.to_block` appends a run-specific line when attribution was
#: unavailable for the whole run.
NOT_MEASURED: tuple[str, ...] = (
    "L4-KILLS is CONDITIONAL, not universal: a criterion earns it only when a banked "
    "oracle-mutation.json actually mutated that criterion's own subject, unambiguously, and "
    "named one of the criterion's own asserting tests among the failures. Every criterion "
    "that condition does not hold for is graded at most L3 and counted in l4.unmeasured",
    "criteria-vs-goal fidelity (the criteria are themselves model-authored from the goal; "
    "this measures exam-vs-criteria only)",
)

#: Tiers excluded from the denominator by construction — no exam verifies "visually clear".
#: Mirrors ``shared.fleet.acceptance.TEST_TIERS`` ({behavior, smoke}) from the outside;
#: :func:`test_tier_criteria` is the single filter.
DENOMINATOR_EXCLUDES: tuple[str, ...] = ("build", "visual", "human")

#: The criterion tiers an executable oracle can verify. Mirrored as data rather than
#: imported, and the reason is the DIRECTION of drift, not an import ban (this module does
#: import the runtime's node tokeniser — see the header): a tier this set is missing costs a
#: criterion its place in the denominator, which under-counts. A tier it gains wrongly would
#: put a criterion no exam can verify INTO the denominator, where it can only ever be
#: UNDECIDABLE — and that is the safe direction too. Both ways round, a drift here refuses.
TEST_TIERS: frozenset[str] = frozenset({"behavior", "smoke"})

# ---------------------------------------------------------------------------
# Tokenisation (the deterministic subject-derivation substrate)
# ---------------------------------------------------------------------------

#: Prose words that carry no discriminating signal. Deliberately SMALL and closed: a large
#: stopword list is a tuning surface, and tuning is what this module exists to resist.
_STOPWORDS: frozenset[str] = frozenset({
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "should", "must",
    "be", "is", "are", "it", "its", "that", "this", "when", "then", "than", "so", "at", "by",
    "from", "as", "if", "not", "no", "into", "each", "any", "all", "can", "will", "does",
    "do", "run", "test", "tests", "check", "verify", "confirm", "ensure", "expected",
    "output", "input", "correct", "correctly", "program", "code", "user", "without", "given",
})

#: An identifier split into its parts: snake_case, camelCase, and digit boundaries.
_IDENT_SPLIT = re.compile(r"[^A-Za-z0-9]+|(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Za-z])(?=[0-9])")
#: A prose word.
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*")


def _fold(token: str) -> str:
    """A token folded to a comparison key — lowercase, light plural/verb-ending folding so
    ``frequencies``/``frequency`` and ``splits``/``split`` compare equal.

    Deliberately crude and CLOSED (no stemmer dependency, no configurable rules): every
    additional rule is a knob, and a knob on the evidence side of an integrity instrument is
    the thing that lets a future session tune coverage upward. Over-folding costs precision
    in the safe direction — it can only make two different words look alike, which yields a
    subject match that must still clear the AST stages to become coverage."""
    t = token.lower()
    for suffix, repl in (("ies", "y"), ("ing", ""), ("es", ""), ("ed", ""), ("s", "")):
        if len(t) > len(suffix) + 2 and t.endswith(suffix):
            t = t[: -len(suffix)] + repl
            break
    # A trailing bare "e" is stripped LAST and unconditionally, so an inflected form and its
    # stem land on the same key: "combined" -> "combin" and "combine" -> "combin". Without
    # this the two differ by one character, and the criterion "combine both counts" fails to
    # bind to the symbol `combined_report` that exists to satisfy it — a false UNDECIDABLE
    # that also lets the criterion be credited by whichever unrelated symbols DID bind.
    if len(t) > 3 and t.endswith("e"):
        t = t[:-1]
    return t


def identifier_tokens(name: str) -> frozenset[str]:
    """The folded, significant tokens of an identifier (``word_frequencies`` →
    ``{word, frequenc}``). Stopwords and 1-character fragments are dropped."""
    parts = [p for p in _IDENT_SPLIT.split(name or "") if p]
    out = {_fold(p) for p in parts}
    return frozenset(t for t in out if len(t) > 1 and t not in _STOPWORDS)


def prose_tokens(text: str) -> frozenset[str]:
    """The folded, significant tokens of a criterion's prose (``text`` + ``check``)."""
    out = {_fold(w) for w in _WORD.findall(text or "")}
    return frozenset(t for t in out if len(t) > 1 and t not in _STOPWORDS)


# ---------------------------------------------------------------------------
# First-party resolution (which imports name the DELIVERABLE, and which name the world)
# ---------------------------------------------------------------------------

#: The test-runner roots an oracle imports. Paired with :data:`sys.stdlib_module_names` (the
#: interpreter's own complete stdlib inventory) this is the NEGATIVE half of the question, and
#: a denylist is sound here in a way it is not on the positive half: it can only ever REMOVE a
#: candidate subject, and removing a candidate can only ever under-count. Mirrors
#: ``shared.fleet.context_pack._ORACLE_IMPORT_SKIP`` from the outside for that same
#: safe-direction reason, not because the surfaces may not be imported.
_TEST_RUNNER_ROOTS: frozenset[str] = frozenset({
    "pytest", "_pytest", "hypothesis", "unittest", "nose", "nose2", "mock", "freezegun",
})


def _never_first_party() -> frozenset[str]:
    """Roots no deliverable may claim: the running interpreter's stdlib inventory plus the
    test-runner surface. Read from :data:`sys.stdlib_module_names` rather than transcribed, so
    it cannot drift out of date the way a hand-kept list does."""
    return frozenset(getattr(sys, "stdlib_module_names", ())) | _TEST_RUNNER_ROOTS


@dataclass(frozen=True)
class FirstPartyIndex:
    """The module roots the assessed deliverable POSITIVELY provides.

    First-party status is resolved, never assumed. The distinction is load-bearing: under a
    denylist, every root not thought of is first-party by default, so an oracle importing
    ``mean`` from ``statistics`` or ``numpy`` hands a criterion a subject the deliverable never
    wrote and coverage it never proved. Here nothing is first-party until a delivered tree (or
    the harness's own resolve-probe against that tree) says it is.

    :attr:`resolved` is the fail-closed switch. An index that could not resolve anything holds
    no roots AND reports ``resolved=False``, and :func:`assess` refuses to emit a number from
    it — an instrument that cannot tell the deliverable from the world produces
    ``available=False``, never a score."""

    roots: frozenset[str] = frozenset()
    #: Human provenance, carried on the emitted block so a reader can see WHAT resolved this.
    source: str = "unresolved"
    resolved: bool = False

    @classmethod
    def unresolved(cls, detail: str = "") -> "FirstPartyIndex":
        """An index that positively resolved nothing. Never a synonym for "nothing is
        first-party" — it means "we cannot tell", and it denies a number."""
        return cls(frozenset(), f"unresolved: {detail}" if detail else "unresolved", False)

    @classmethod
    def from_roots(cls, roots: "set[str] | frozenset[str]", *, source: str) -> "FirstPartyIndex":
        """An index over roots observed in a delivered tree. Stdlib and test-runner roots are
        dropped even when the tree shadows one — a deliverable that ships its own ``json.py``
        loses that subject rather than gaining a contested one."""
        never = _never_first_party()
        return cls(frozenset(r for r in roots if r and r not in never), source, True)

    @classmethod
    def from_specifiers(cls, specs: "set[str] | frozenset[str]", *,
                        source: str) -> "FirstPartyIndex":
        """The node form: an index over ESM SPECIFIERS (``../src/pieces/data.js``) the
        deliverable was shown to provide, rather than over python module roots.

        The same question — *what belongs to the deliverable?* — answered in the units the
        ecosystem uses, so :attr:`resolved` keeps its fail-closed meaning across both.

        :func:`_never_first_party` is deliberately NOT applied. That denylist is the running
        interpreter's PYTHON stdlib inventory, and testing a filesystem-relative JavaScript
        specifier for membership in it is a category error: it can only ever match by
        coincidence, and a coincidental match would silently delete a real subject. The node
        side's negative half is carried by the specifier grammar instead — a bare specifier
        is a dependency and ``node:*`` is the platform, so neither ever reaches this set."""
        return cls(frozenset(s for s in specs if s), source, True)

    def __contains__(self, root: object) -> bool:
        return bool(self.resolved and isinstance(root, str) and root in self.roots)


# ---------------------------------------------------------------------------
# L4 — mutation attribution (what makes the top rung reachable)
# ---------------------------------------------------------------------------

#: The #828 mutation sidecar, read ONLY for its per-mutant attribution rows.
_MUTATION_SIDECAR_NAME = "oracle-mutation.json"

#: ``shared.fleet.oracle_mutation.MEASURED_STATUSES``, mirrored from the outside for the same
#: reason :data:`TEST_TIERS` is — this harness module runs at battery close against banked
#: JSON and keeps its no-runtime-import property. A drift here can only ever make a real audit
#: look unmeasured, which denies rungs rather than minting them.
_MUTATION_MEASURED_STATUSES: frozenset[str] = frozenset({"run", "partial-budget"})

#: This criterion's own asserting test FAILED when this criterion's own subject was mutated.
#: The only state that earns :data:`LEVEL_KILLS`.
L4_KILLED = "killed"
#: A mutant of this criterion's subject SURVIVED the whole exam — the exam is provably blind
#: at that locus. Evidence of weakness, reported; it does not lower the level the criterion
#: already earned on its own terms.
L4_SURVIVED = "survived"
#: Mutants of this criterion's subject were all caught, but only by OTHER tests. Something was
#: measured; nothing is attributable to this criterion. Deliberately distinct from
#: :data:`L4_NOT_MEASURED` — "we looked and could not credit you" is not "we never looked".
L4_NOT_ATTRIBUTED = "not-attributed"
#: No mutant landed on this criterion's subject, the subject's attribution was ambiguous, or
#: the run banked no usable attribution at all. The default, and the value a criterion below
#: L3 always carries.
L4_NOT_MEASURED = "not-measured"

#: The states in which a per-criterion L4 determination was actually reached.
L4_DETERMINED: frozenset[str] = frozenset({L4_KILLED, L4_SURVIVED})


@dataclass(frozen=True)
class MutationAttribution:
    """Per-symbol mutation evidence, folded from one run's banked ``oracle-mutation.json``.

    The sidecar answers *"did the exam catch broken code?"* whole-file — killed/ran over every
    mutated module at once. That figure cannot reach the L4 rung, which asks the narrower
    question *"did THIS criterion's test fail when THIS criterion's subject was broken?"*, so
    the audit additionally banks one row per counted mutant naming the top-level symbol it hit
    and the tests that failed on it. This type is that fold, keyed by symbol.

    :attr:`available` is the fail-closed switch and follows the same rule as
    :class:`FirstPartyIndex`: an attribution that resolved nothing holds no symbols AND
    reports ``available=False``, and every criterion then grades at most L3 with
    ``l4=not-measured``. Not-knowing is never a rung."""

    available: bool = False
    reason: str = ""
    #: Human provenance, carried on the emitted block.
    source: str = ""
    #: symbol → the test names that FAILED on at least one mutant inside that symbol.
    killed_by: "dict[str, frozenset[str]]" = field(default_factory=dict)
    #: symbol → ``"operator file:line"`` loci of mutants inside it that the exam did NOT catch.
    survived: "dict[str, tuple[str, ...]]" = field(default_factory=dict)
    #: Symbols a counted mutant actually landed in — the surface that WAS measured. A subject
    #: outside this set was never put to the question, which is not the same as passing it.
    mutated: frozenset[str] = frozenset()
    #: Symbols whose name is defined in more than one mutated file. A mutant of ``helper`` in
    #: ``a.py`` cannot be credited to a criterion whose ``helper`` came from ``b.py``, and
    #: nothing in the banked evidence says which one the oracle imported — so both are refused.
    ambiguous: frozenset[str] = frozenset()
    #: Counted mutants that went RED without naming a single failing test. Reported so a run
    #: whose pytest config suppresses the summary reads as blind rather than as clean.
    unattributed_kills: int = 0

    @classmethod
    def unavailable(cls, reason: str, source: str = "") -> "MutationAttribution":
        """An attribution that resolved nothing. Never a synonym for "nothing was killed"."""
        return cls(available=False, reason=reason, source=source)

    def verdict_for(
        self, subjects: frozenset[str], asserting: "frozenset[str] | set[str]",
    ) -> "tuple[str, tuple[str, ...], tuple[str, ...]]":
        """The L4 state for one criterion, the evidence behind it, and — ALWAYS — the loci of
        mutants in its subjects that the exam did not catch.

        *asserting* is the set of tests that earned this criterion its L3 — the rung is about
        THOSE tests, not about whichever test in the exam happened to catch something.

        Precedence is killed → survived → not-attributed → not-measured, and every step
        refuses rather than reaches: a subject nothing mutated, or one whose name is ambiguous
        across mutated files, contributes nothing at all.

        Surviving loci are returned INDEPENDENTLY of the state, because earning the rung and
        having a blind spot are not mutually exclusive: a subject whose test killed four
        mutants and missed two is a real L4 and a real hole, and reporting only the state
        would erase the half that a reader most needs. This is not hypothetical — the first
        run this graded killed 17 of 19 and the two survivors sat inside a subject that had
        simultaneously earned the rung."""
        if not self.available:
            return L4_NOT_MEASURED, (), ()
        usable = {s for s in subjects if s in self.mutated and s not in self.ambiguous}
        if not usable:
            return L4_NOT_MEASURED, (), ()
        loci = tuple(sorted({loc for s in usable for loc in self.survived.get(s, ())}))
        killers = sorted({
            t for s in usable for t in (self.killed_by.get(s, frozenset()) & set(asserting))
        })
        if killers:
            return L4_KILLED, tuple(killers), loci
        if loci:
            return L4_SURVIVED, loci, loci
        return L4_NOT_ATTRIBUTED, (), ()

    def to_dict(self) -> dict:
        return {
            "available": self.available,
            "reason": self.reason,
            "source": self.source,
            "mutated_symbols": sorted(self.mutated),
            "ambiguous_symbols": sorted(self.ambiguous),
            "unattributed_kills": self.unattributed_kills,
        }


def fold_mutation_attribution(evidence: dict, oracle_code: str) -> MutationAttribution:
    """Fold a banked ``oracle-mutation.json`` into per-symbol attribution. Pure; no I/O.

    ``oracle_code`` is the exam THIS assessment is grading. Its digest must match the one the
    audit banked, because the two stages find their oracle independently: crediting one exam's
    kills to another exam's tests would look exactly like evidence, and a mismatch is
    cheap to detect and impossible to recover from afterwards.

    Every refusal path returns :meth:`MutationAttribution.unavailable` with a reason — an
    audit that never ran, one that ran before attribution existed, one whose digest disagrees,
    and one that counted mutants but attributed none are four different states, and each says
    which it is rather than collapsing into a shared silence."""
    if not isinstance(evidence, dict):
        return MutationAttribution.unavailable("no readable mutation sidecar")
    status = str(evidence.get("mutation_audit", "") or "")
    ran = int(evidence.get("ran", 0) or 0)
    if status not in _MUTATION_MEASURED_STATUSES or ran <= 0:
        return MutationAttribution.unavailable(
            f"the run's mutation audit did not discriminate (mutation_audit={status or 'absent'}, "
            f"ran={ran})")

    banked_digest = str(evidence.get("oracle_sha256", "") or "")
    if not banked_digest:
        return MutationAttribution.unavailable(
            "the banked mutation audit carries no oracle digest, so it cannot be shown to have "
            "audited the exam being graded here")
    if banked_digest != hashlib.sha256((oracle_code or "").encode("utf-8", "replace")).hexdigest():
        return MutationAttribution.unavailable(
            "the mutation audit ran against a DIFFERENT exam than the one assessed here "
            "(oracle digest mismatch)")

    rows = evidence.get("mutants")
    if not isinstance(rows, list) or not rows:
        return MutationAttribution.unavailable(
            "the mutation audit counted mutants but banked no per-mutant attribution")

    killed_by: "dict[str, set[str]]" = {}
    survived: "dict[str, list[str]]" = {}
    files_by_symbol: "dict[str, set[str]]" = {}
    mutated: set[str] = set()
    unattributed_kills = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol", "") or "")
        outcome = str(row.get("outcome", "") or "")
        killers = [str(t) for t in (row.get("killed_by") or []) if str(t)]
        if outcome == "killed" and not killers:
            # RED, but the run did not say who. Counted so the blindness is visible; never
            # credited, because "something failed" is not "this criterion's test failed".
            unattributed_kills += 1
        if not symbol:
            continue  # a module-level site names no subject; it can support no rung
        if outcome not in (L4_KILLED, L4_SURVIVED):
            # NOT RUN, or an outcome this parser does not recognise. ``mutated`` means "this
            # subject was PUT TO THE QUESTION", and a mutant that never executed was not.
            #
            # Admitting it here is the #1223 invariant inverted: the symbol would enter
            # ``mutated`` with no entry in ``killed_by`` or ``survived`` (both outcome-strict
            # below), which renders as L4_NOT_ATTRIBUTED — "the subject WAS mutated and every
            # mutant was caught, but only by other tests". That sentence asserts a cause the
            # evidence does not contain: nothing was caught, because nothing ran.
            #
            # Reachable from the shipped producer TODAY via a killed row whose killers the
            # run did not name (a deliverable carrying ``addopts = -rN --tb=no``), and it
            # becomes systematic the moment #1231 emits a third outcome for budget-truncated
            # mutants. Skipping here is what keeps that interaction safe, and it costs
            # nothing: ``unattributed_kills`` above already counts the blind kills at run
            # level, so the blindness stays VISIBLE without being explained wrongly.
            continue
        mutated.add(symbol)
        files_by_symbol.setdefault(symbol, set()).add(str(row.get("file", "") or ""))
        if outcome == L4_KILLED:
            killed_by.setdefault(symbol, set()).update(killers)
        else:
            survived.setdefault(symbol, []).append(
                f"{row.get('operator', '?')} {row.get('file', '?')}:{row.get('line', '?')}")

    return MutationAttribution(
        available=True,
        source=f"{_MUTATION_SIDECAR_NAME} ({evidence.get('oracle_mutation_score', '?')} mutants "
               f"killed, status={status})",
        killed_by={s: frozenset(t) for s, t in killed_by.items()},
        survived={s: tuple(sorted(set(v))) for s, v in survived.items()},
        mutated=frozenset(mutated),
        ambiguous=frozenset(s for s, files in files_by_symbol.items() if len(files) > 1),
        unattributed_kills=unattributed_kills,
    )


def load_mutation_attribution(run_dir: "str | Path", oracle_code: str) -> MutationAttribution:
    """Read a run's banked mutation sidecar and fold it (:func:`fold_mutation_attribution`).

    Fail-soft: a missing or unreadable sidecar is an unavailable attribution with a reason,
    never an exception and never an empty-but-available one."""
    try:
        evidence = _read_json(Path(run_dir) / _MUTATION_SIDECAR_NAME)
    except Exception as exc:  # noqa: BLE001 — advisory: never sink an assessment
        return MutationAttribution.unavailable(f"mutation sidecar unreadable: {type(exc).__name__}")
    if evidence is None:
        return MutationAttribution.unavailable(
            f"the run banked no {_MUTATION_SIDECAR_NAME}, so no mutant can be traced to a "
            f"criterion")
    return fold_mutation_attribution(evidence, oracle_code)


# ---------------------------------------------------------------------------
# Oracle AST reads (deterministic; no model, no subprocess)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OracleTest:
    """One ``def test*`` in the oracle, with the first-party symbols it touches."""

    name: str
    #: First-party symbols referenced anywhere in the test body.
    exercises: frozenset[str]
    #: First-party symbols an assertion in this test actually BEARS ON — the subject named
    #: inside the ``assert`` subtree, or reached from it through a local bound (directly or
    #: transitively) from an expression that named the subject. See :func:`trace_test`.
    asserts_on: frozenset[str]
    #: Whether the test makes ANY assertion at all, about anything. Reported so the L2 reason
    #: can distinguish "asserts nothing" from "asserts, but not about this subject" — and
    #: deliberately NOT part of the L3 predicate: ``assert True`` sets this flag.
    has_assertion: bool = False


def _root_name(node: ast.AST) -> str:
    """The root identifier of a Name/Attribute chain (``a.b.c`` → ``a``)."""
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else ""


def first_party_symbols(tree: ast.AST, index: FirstPartyIndex) -> frozenset[str]:
    """Bare names bound by an import whose root the deliverable provides — the
    ``from m import NAME`` names plus the top-level name of each ``import a.b``.

    Relative imports (a sibling module inside ``tests/``) are skipped: the oracle's own test
    package is not the deliverable's public surface.

    Known limit: an aliased import (``from app.x import word_frequencies as wf``) records the
    ORIGINAL name, which the body never mentions, so the criterion lands at ``L0-GAP`` rather
    than binding. That is a false accusation rather than false coverage — the safe direction —
    and it is not corrected here."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level or not node.module:
                continue
            if node.module.split(".", 1)[0] not in index:
                continue
            names.update(a.name for a in node.names if a.name != "*")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".", 1)[0]
                if top in index:
                    names.add(top)
    return frozenset(names)


def _expr_subjects(node: ast.AST, symbols: frozenset[str],
                   taint: "dict[str, frozenset[str]]") -> frozenset[str]:
    """The subjects an expression bears on: the first-party symbols it names outright, plus
    everything the locals it reads were derived from."""
    out: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, (ast.Name, ast.Attribute)):
            root = _root_name(sub)
            if root in symbols:
                out.add(root)
            elif root in taint:
                out |= taint[root]
    return frozenset(out)


def _is_raises_call(node: ast.AST) -> bool:
    """``pytest.raises(...)`` / ``raises(...)`` — an assertion that carries no ``assert``
    keyword. ``test_add_card_rejects_empty_input`` is entirely built from these, and reading
    it as assertion-free would be simply wrong."""
    if not isinstance(node, ast.Call):
        return False
    fn = node.func
    if isinstance(fn, ast.Attribute):
        return fn.attr == "raises"
    return isinstance(fn, ast.Name) and fn.id == "raises"


def trace_test(fn: "ast.FunctionDef | ast.AsyncFunctionDef",
               symbols: frozenset[str]) -> OracleTest:
    """One test function traced for what its assertions actually bear on.

    The naive read — "does an ``assert`` subtree name the subject?" — scores the commonest
    sound shape as assertion-free, because the assertion runs through a local::

        add_card(path, "q", "a")        # the subject under test
        loaded = load_cards(path)       # its effect, read back
        assert loaded[0].text == "q"    # names neither subject

    So this walks the body in statement order carrying a taint map (local name → the subjects
    its value was derived from) and treats an assertion as bearing on every subject reachable
    from it. Binding forms tracked: assignment, annotated assignment, augmented assignment,
    tuple/list unpacking (element-wise when both sides are literal sequences of equal length,
    broadcast otherwise), ``with ... as``, ``for ... in``, and the walrus operator. Passing a
    bare local INTO a subject's call taints that local too, which is how ``add_card(path, …)``
    above links to the later read of ``path``. Taint is transitive with no hop limit — the map
    accumulates as the walk proceeds.

    Deliberately NOT handled, and therefore under-counted rather than assumed:

    * mutation through anything but a bare-``Name`` argument (``add_card(deck["a"], …)``,
      ``export(inv, str(path))``, attribute and subscript targets);
    * bodies of nested ``def``/``class`` inside a test (fixtures, helper closures);
    * aliasing through containers (``bag = [make_card()]; assert bag[0]``) resolves, but
      ``bag.append(make_card())`` does not — a method call is not a binding form;
    * dataflow through the FILESYSTEM or any other implicit global. ``save_expense(12.50,
      …); loaded = load_expenses(); assert …`` verifies persistence with no variable linking
      the write to the read-back, so the criterion lands at ``L2-BOUND``. This is the
      costliest gap and the commonest sound shape it misses.

    Two NAMED CREDIT PATHS — cases that reach ``L3-ASSERTED`` on evidence weaker than the
    level claims. Both are retained deliberately and both are pinned by a regression test, so
    the over-credit is checkable rather than merely known. An undocumented credit path is how
    the predicate this replaced went wrong:

    * an INPUT-ONLY assertion. The argument-taint rule cannot distinguish an assertion about
      what the subject PRODUCED from one about what it was GIVEN, so ``data = ["a", "b"];
      word_frequencies(data); assert data == ["a", "b"]`` credits ``word_frequencies``
      although nothing about the frequency count is verified. Narrower than the predicate it
      replaced — it needs a bare local passed INTO the subject and an assertion on that same
      local — and it is the direct price of the genuine ``export_to_spreadsheet(inv,
      file_path); assert file_path.exists()`` shape, which is real in the banked corpus.
      Removing the rule closes this and reopens that.
    * an UNTAKEN BRANCH. Taint is never retracted, so ``if flag: out = word_frequencies(["a"])
      else: out = None`` followed by ``assert out is None`` credits ``word_frequencies`` from
      the arm that did not run. Path-sensitivity is the fix and it is not implemented here."""
    exercises: set[str] = set()
    asserts_on: set[str] = set()
    taint: "dict[str, frozenset[str]]" = {}
    has_assertion = False

    for sub in ast.walk(fn):
        if isinstance(sub, (ast.Name, ast.Attribute)) and _root_name(sub) in symbols:
            exercises.add(_root_name(sub))

    def bind(target: ast.AST, subjects: frozenset[str]) -> None:
        """Record a local as derived from ``subjects``. Only bare names are tracked; an
        attribute or subscript target is a mutation this pass does not model."""
        if isinstance(target, ast.Name):
            if subjects:
                taint[target.id] = taint.get(target.id, frozenset()) | subjects
        elif isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                bind(elt, subjects)
        elif isinstance(target, ast.Starred):
            bind(target.value, subjects)

    def bind_assign(target: ast.AST, value: ast.expr) -> None:
        """``a, b = f(), g()`` binds element-wise; ``a, b = split(x)`` broadcasts, because the
        one value is the source of both names."""
        if (isinstance(target, (ast.Tuple, ast.List))
                and isinstance(value, (ast.Tuple, ast.List))
                and len(target.elts) == len(value.elts)):
            for tgt, val in zip(target.elts, value.elts):
                bind_assign(tgt, val)
            return
        bind(target, _expr_subjects(value, symbols, taint))

    def pre(node: ast.AST) -> None:
        """Expression-level effects that apply wherever they appear: the walrus binding, the
        argument taint a subject's call spreads, and the call form of ``raises``."""
        nonlocal has_assertion
        for sub in ast.walk(node):
            if isinstance(sub, ast.NamedExpr):
                bind(sub.target, _expr_subjects(sub.value, symbols, taint))
            elif isinstance(sub, ast.Call):
                if _is_raises_call(sub):
                    has_assertion = True
                    asserts_on.update(_expr_subjects(sub, symbols, taint))
                    continue
                callee = _expr_subjects(sub.func, symbols, taint)
                if not callee:
                    continue
                # The output-parameter idiom: the subject was handed a local and may have
                # written through it, so a later read of that local is a read of the subject's
                # effect. Restricted to bare names — anything richer is a guess.
                for arg in list(sub.args) + [kw.value for kw in sub.keywords]:
                    if isinstance(arg, ast.Name):
                        bind(arg, callee)

    def visit(stmts: "list[ast.stmt]") -> None:
        nonlocal has_assertion
        for st in stmts:
            if isinstance(st, ast.Assert):
                pre(st.test)
                has_assertion = True
                # The message is narration, never evidence.
                asserts_on.update(_expr_subjects(st.test, symbols, taint))
            elif isinstance(st, ast.Assign):
                pre(st.value)
                for tgt in st.targets:
                    bind_assign(tgt, st.value)
            elif isinstance(st, ast.AnnAssign):
                if st.value is not None:
                    pre(st.value)
                    bind(st.target, _expr_subjects(st.value, symbols, taint))
            elif isinstance(st, ast.AugAssign):
                pre(st.value)
                bind(st.target, _expr_subjects(st.value, symbols, taint))
            elif isinstance(st, (ast.With, ast.AsyncWith)):
                raising = any(_is_raises_call(i.context_expr) for i in st.items)
                for item in st.items:
                    pre(item.context_expr)
                    if item.optional_vars is not None:
                        bind(item.optional_vars,
                             _expr_subjects(item.context_expr, symbols, taint))
                visit(st.body)
                if raising:
                    # ``with pytest.raises(V): add_card("", "x")`` — the BODY is the assertion.
                    has_assertion = True
                    for inner in st.body:
                        asserts_on.update(_expr_subjects(inner, symbols, taint))
            elif isinstance(st, (ast.For, ast.AsyncFor)):
                pre(st.iter)
                bind(st.target, _expr_subjects(st.iter, symbols, taint))
                visit(st.body)
                visit(st.orelse)
            elif isinstance(st, (ast.If, ast.While)):
                pre(st.test)
                visit(st.body)
                visit(st.orelse)
            elif isinstance(st, ast.Try):
                visit(st.body)
                for handler in st.handlers:
                    visit(handler.body)
                visit(st.orelse)
                visit(st.finalbody)
            elif isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue  # a nested definition is not this test's straight-line evidence
            else:
                # Everything else (a bare call, `return`, `raise`, `match`, …) still carries
                # the expression-level effects; only its binding forms go untracked, which
                # under-counts rather than credits.
                pre(st)

    visit(fn.body)
    return OracleTest(fn.name, frozenset(exercises), frozenset(asserts_on), has_assertion)


def oracle_tests(tree: ast.AST, symbols: frozenset[str]) -> list[OracleTest]:
    """Every ``def test*`` with the first-party symbols it exercises and asserts on.

    The exercise/assert split is the L2→L3 boundary: a bare no-raise call counts as
    exercising the symbol, but only an assertion that BEARS ON the symbol — directly or
    through the locals it was read back into (:func:`trace_test`) — counts as asserting on
    it."""
    return [
        trace_test(node, symbols)
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test")
    ]


# ---------------------------------------------------------------------------
# Node reads (the same ladder, no AST — #1348)
# ---------------------------------------------------------------------------
#
# There is no ``ast`` for JavaScript here, so this half answers the SAME three questions
# (what does the test touch / what does it assert on / does it assert at all) from the
# MASKED source: :func:`shared.fleet.oracle_qa.node_mask` blanks every comment and literal
# body while preserving offsets, so a scan below reads code and only code. That masker fails
# soft to ``None`` on any ambiguity, and this module inherits that: an unmaskable oracle is
# reported as unparseable, never assessed on a guess.
#
# The precision rule is the module's, unchanged and if anything sharper here, because a
# regex cannot see scope: every construct below either establishes a subject on evidence or
# declines to. The two directions are NOT symmetric — an under-match lands the criterion in
# UNDECIDABLE, which BLOCKS ``GREEN-VERIFIED``; an over-match MINTS coverage. Where the
# choice was live, this takes the under-match.

#: An identifier in JavaScript source (``$`` is an identifier character, so ``\b`` is wrong).
_JS_IDENT_RE = re.compile(r"[A-Za-z_$][\w$]*")

#: A real ASSERTION SITE — the predicate L3 is awarded from.
#:
#: NOT :data:`shared.fleet.oracle_qa.NODE_ASSERTION_RE`, and the difference is the whole
#: point. There, a generous match means "do not flag this test as vacuous", and a false
#: positive REFUSES a job — so breadth is the safe direction and that regex matches bare
#: words like ``should`` and ``throws`` anywhere in a body. Here a match AWARDS a level, so
#: breadth is the dangerous direction and the same word appearing in a variable name would
#: mint coverage. This form requires a CALL to an assertion entry point (or chai's ``.should``
#: chain), which is what an assertion actually is.
_JS_ASSERT_SITE_RE = re.compile(
    r"(?<![\w$])assert(?:\s*\.\s*[\w$]+)*\s*\("
    r"|(?<![\w$])expect\s*\("
    r"|\.\s*should\b"
    r"|(?<![\w$])(?:ok|fail|throws|rejects|doesNotThrow|doesNotReject|deepEqual"
    r"|strictEqual|notEqual|match|ifError)\s*\("
)

#: A binding: ``const x = …`` / ``let [a, b] = …`` / ``x = …``. The ``=`` must be a real
#: assignment, so ``==``/``===``/``=>`` are excluded; a compound (``+=``) never matches
#: because the character before ``=`` is then not part of the target identifier.
_JS_BINDING_RE = re.compile(
    r"(?:(?:const|let|var)\s+)?"
    r"(?P<target>[A-Za-z_$][\w$]*|\{[^{}]*\}|\[[^\[\]]*\])\s*=(?![=>])"
    r"(?P<value>[^;]*)"
)

#: The head of a call: a root identifier, its member chain, and the opening paren.
_JS_CALL_HEAD_RE = re.compile(
    r"(?<![\w$.])(?P<root>[A-Za-z_$][\w$]*)(?P<chain>(?:\s*\??\.\s*[A-Za-z_$][\w$]*)*)\s*\(")

#: A template-string interpolation. Blanked out of an ASSERTION's text before subjects are
#: read from it: ``assert.equal(a, b, `expected ${pieces.length}`)`` names ``pieces`` only in
#: its MESSAGE, and the python path's rule — "the message is narration, never evidence" —
#: has to hold here too. Only non-nested holes are recognised; a nested one is left alone,
#: which can over-credit exactly one shape and is named in :func:`node_trace_test`.
_JS_TEMPLATE_HOLE_RE = re.compile(r"\$\{[^{}]*\}")

#: Bracket characters that open / close a nesting level, for the statement splitter.
_JS_OPENERS = "([{"
_JS_CLOSERS = ")]}"


def node_symbols(code: str, index: FirstPartyIndex) -> frozenset[str]:
    """The local names an oracle binds from a first-party MODULE — the node analogue of
    :func:`first_party_symbols`.

    First-party status is RESOLVED, exactly as on the python side: a name counts only when
    the specifier it came from is one the index holds (built by :func:`resolve_first_party`
    from the run's own banked resolve-probe, or from the delivered tree). The ``./`` prefix
    alone is NOT the test here — that rule belongs to
    :func:`shared.fleet.oracle_qa.node_first_party_names`, whose job is to be forgiving; this
    one must be able to say a symbol belonged to the deliverable, and a specifier that failed
    to resolve is a symbol the deliverable did not provide.

    Known limit, the mirror of the python side's aliasing gap: ``import { getPieces as gp }``
    records ``gp`` (the LOCAL binding), which the body does mention — so node loses nothing
    there. What it loses instead is the ORIGINAL export name, so a criterion whose wording
    names ``getPieces`` will not bind to a local called ``gp``. That is a false UNDECIDABLE
    rather than false coverage — the safe direction — and it is not corrected here."""
    names: set[str] = set()
    for spec, bound in node_import_bindings(code):
        if spec in index:
            names |= bound
    return frozenset(names)


def _js_statements(body: str) -> "list[str]":
    """A masked test body split into top-level statements, in source order.

    Splits on ``;`` and newlines at nesting depth zero, so an arrow callback, an object
    literal or a multi-line argument list stays inside the one statement that contains it.
    A ``{ … }`` BLOCK likewise stays whole, which is why every scan below uses ``finditer``
    rather than a single anchored match: a binding inside an ``if`` block is still a binding
    that happened, and taint is never retracted here any more than it is on the python side."""
    out: "list[str]" = []
    buf: "list[str]" = []
    depth = 0
    for ch in body:
        if ch in _JS_OPENERS:
            depth += 1
        elif ch in _JS_CLOSERS:
            depth = max(0, depth - 1)
        elif depth == 0 and ch in ";\n":
            text = "".join(buf).strip()
            if text:
                out.append(text)
            buf = []
            continue
        buf.append(ch)
    text = "".join(buf).strip()
    if text:
        out.append(text)
    return out


def _js_expr_subjects(text: str, symbols: frozenset[str],
                      taint: "dict[str, frozenset[str]]") -> frozenset[str]:
    """The subjects an expression bears on: the first-party symbols it names outright, plus
    everything the locals it reads were derived from. The node twin of
    :func:`_expr_subjects`.

    Two identifiers are skipped, both standing in for what :func:`_root_name` does on the
    python side — take the ROOT of a chain, never a member of it:

    * one preceded by ``.`` or ``?.`` is a PROPERTY (``piece.price`` names ``piece``);
      a spread (``...piece``) is not, and is kept;
    * one followed by ``:`` is an object KEY (``{ name: value }``). This also drops the true
      branch of a ternary (``cond ? getPieces() : []`` keeps the call; ``cond ? pieces : []``
      loses ``pieces``), which under-counts — the safe direction, and not corrected."""
    out: set[str] = set()
    for m in _JS_IDENT_RE.finditer(text):
        before = text[:m.start()].rstrip()
        if before.endswith(".") and not before.endswith(".."):
            continue
        after = text[m.end():].lstrip()
        if after.startswith(":") and not after.startswith("::"):
            continue
        token = m.group(0)
        if token in symbols:
            out.add(token)
        elif token in taint:
            out |= taint[token]
    return frozenset(out)


def _js_split_top_level(text: str, sep: str = ",") -> "list[str]":
    """Split on ``sep`` at nesting depth zero (an argument list, or a destructuring target)."""
    out: "list[str]" = []
    buf: "list[str]" = []
    depth = 0
    for ch in text:
        if ch in _JS_OPENERS:
            depth += 1
        elif ch in _JS_CLOSERS:
            depth = max(0, depth - 1)
        elif depth == 0 and ch == sep:
            out.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    out.append("".join(buf))
    return out


def _js_balanced(text: str, open_at: int) -> str:
    """The contents of the bracket group opening at ``open_at``, or ``""`` if it never
    closes (fail-soft: the caller then learns nothing from it rather than guessing)."""
    depth = 0
    for k in range(open_at, len(text)):
        if text[k] in _JS_OPENERS:
            depth += 1
        elif text[k] in _JS_CLOSERS:
            depth -= 1
            if depth == 0:
                return text[open_at + 1:k]
    return ""


def _js_target_names(target: str) -> "list[str]":
    """The local names a binding target introduces — a bare name, or the names inside an
    object/array destructuring pattern (``{ a, b: c }`` binds ``a`` and ``c``)."""
    target = target.strip()
    if not target:
        return []
    if target[0] in "{[":
        names: list[str] = []
        for part in _js_split_top_level(target[1:-1]):
            part = part.strip().lstrip(".").strip()
            if not part:
                continue
            # `b: c` renames; `a = 1` defaults. The BOUND name is what survives both.
            part = part.split(":")[-1].split("=")[0].strip()
            m = _JS_IDENT_RE.fullmatch(part)
            if m:
                names.append(m.group(0))
        return names
    m = _JS_IDENT_RE.fullmatch(target)
    return [m.group(0)] if m else []


def node_trace_test(name: str, masked_body: str, symbols: frozenset[str]) -> OracleTest:
    """One node test traced for what its assertions actually bear on — the node twin of
    :func:`trace_test`, and it carries the same taint idea for the same reason: the commonest
    sound shape asserts through a local, and reading only the assertion's own text would
    score it as bearing on nothing::

        const pieces = await getPieces();   // the subject under test
        const piece = pieces[0];            // its result, read on
        assert.equal(piece.price, 15.99);   // names neither subject

    Binding forms tracked: ``const``/``let``/``var`` and bare assignment, object and array
    destructuring (broadcast, except when both sides are literal sequences of equal length,
    which binds element-wise so ``const [a, b] = [getPieces(), 5]`` cannot credit ``getPieces``
    for an assertion about ``b``). Passing a BARE identifier into a first-party call taints it,
    the output-parameter idiom the python side also models. Taint is transitive and never
    retracted.

    Deliberately NOT handled, and therefore under-counted rather than assumed:

    * scope. A regex cannot see a shadowing declaration inside a nested closure, so a local
      that shadows an imported name is read as the import. This can only affect ``exercises``
      (L2); reaching L3 additionally requires the assertion predicate below;
    * mutation through anything but a bare identifier argument (``store(payload.body)``),
      exactly as on the python side;
    * dataflow through the filesystem, a module-level variable, or a running server — the
      costliest gap in both ecosystems, and the reason a node oracle that boots a server and
      asserts over HTTP lands at ``L2-BOUND``;
    * ``require()`` — this reads ESM ``import`` only, which is what the seeded ``.mjs``
      oracles use. A CommonJS oracle yields no symbols and every criterion goes UNDECIDABLE,
      which is honest rather than wrong, and it is not silently patched over here.

    ONE NAMED CREDIT PATH, in the house form — a shape that reaches ``L3-ASSERTED`` on
    evidence weaker than the level claims, retained deliberately and pinned by a regression
    test, because an undocumented credit path is how a predicate goes quietly wrong:

    * a NESTED template interpolation inside an assertion message.
      ``assert.equal(a, b, `saw ${fmt({n: pieces.length})}`)`` names ``pieces`` only in the
      message, and the message is narration; :data:`_JS_TEMPLATE_HOLE_RE` blanks the simple
      case but not one containing braces of its own, so that subject is credited. The
      unnested form — the one that actually occurs — is blanked and does not credit."""
    exercises = {
        s for s in symbols
        if re.search(r"(?<![\w$.])" + re.escape(s) + r"(?![\w$])", masked_body)
    }
    asserts_on: set[str] = set()
    taint: "dict[str, frozenset[str]]" = {}
    has_assertion = bool(NODE_ASSERTION_RE.search(masked_body))

    def bind(local: str, subjects: frozenset[str]) -> None:
        if local and subjects:
            taint[local] = taint.get(local, frozenset()) | subjects

    for stmt in _js_statements(masked_body):
        # 1. Argument taint FIRST, matching the python path's `pre()`-before-record order:
        #    a subject handed a bare local may have written through it, so a later read of
        #    that local is a read of the subject's effect.
        for m in _JS_CALL_HEAD_RE.finditer(stmt):
            callee = _js_expr_subjects(m.group("root"), symbols, taint)
            if not callee:
                continue
            for arg in _js_split_top_level(_js_balanced(stmt, m.end() - 1)):
                ident = _JS_IDENT_RE.fullmatch(arg.strip())
                if ident:
                    bind(ident.group(0), callee)

        # 2. Bindings, in source order.
        for m in _JS_BINDING_RE.finditer(stmt):
            target, value = m.group("target"), m.group("value")
            names = _js_target_names(target)
            if not names:
                continue
            value_stripped = value.strip()
            elements = (_js_split_top_level(_js_balanced(value_stripped, 0))
                        if target.strip().startswith("[") and value_stripped.startswith("[")
                        else None)
            if elements is not None and len(elements) == len(names):
                for local, element in zip(names, elements):
                    bind(local, _js_expr_subjects(element, symbols, taint))
                continue
            subjects = _js_expr_subjects(value, symbols, taint)
            for local in names:
                bind(local, subjects)

        # 3. The assertion predicate. The whole statement is the assertion's expression (a
        #    JavaScript test statement asserts or binds, rarely both), minus its template
        #    interpolations — the message is narration, never evidence.
        if _JS_ASSERT_SITE_RE.search(stmt):
            asserts_on.update(_js_expr_subjects(
                _JS_TEMPLATE_HOLE_RE.sub(" ", stmt), symbols, taint))

    return OracleTest(name, frozenset(exercises), frozenset(asserts_on), has_assertion)


def node_oracle_tests(code: str, masked: str, symbols: frozenset[str]) -> "list[OracleTest]":
    """Every ``test(...)`` / ``it(...)`` declaration, traced. Names come from the RAW source
    (the masker blanked the literal holding them); a declaration whose body the tokeniser
    could not delimit is SKIPPED rather than guessed at, so it contributes no evidence in
    either direction."""
    return [
        node_trace_test(node_declared_name(code, offset) or f"test #{idx}", body, symbols)
        for idx, (offset, body) in enumerate(node_test_bodies(masked), start=1)
    ]


# ---------------------------------------------------------------------------
# Ecosystem readers (one seam, so the ladder below is ecosystem-blind)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OracleSurface:
    """What one ecosystem reader extracted from one oracle: the deliverable's symbols it
    binds, and the tests it declares.

    :attr:`reason` is the fail-closed switch and follows the same rule as every other
    "cannot tell" in this module — a non-empty reason means the oracle was NOT read, and the
    other two fields carry nothing a caller may use. There is no partially-read state."""

    symbols: frozenset[str] = frozenset()
    tests: "tuple[OracleTest, ...]" = ()
    reason: str = ""

    @property
    def readable(self) -> bool:
        return not self.reason


def read_python_oracle(code: str, index: FirstPartyIndex) -> OracleSurface:
    """Read a pytest oracle through the ``ast`` (:func:`first_party_symbols`,
    :func:`oracle_tests`)."""
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError) as exc:
        return OracleSurface(reason=f"oracle does not parse: {type(exc).__name__}")
    symbols = first_party_symbols(tree, index)
    return OracleSurface(symbols, tuple(oracle_tests(tree, symbols)))


def read_node_oracle(code: str, index: FirstPartyIndex) -> OracleSurface:
    """Read a ``node --test`` oracle through the masked source (:func:`node_symbols`,
    :func:`node_oracle_tests`).

    An oracle the tokeniser refuses is reported as UNPARSEABLE — a third distinct state, and
    distinct on purpose: it is neither "nothing was seeded" nor "this ecosystem is not read",
    and a reader chasing a missing number needs to know which of the three they are looking
    at. The tokeniser refuses only on genuine ambiguity (an unterminated literal, braces that
    do not unwind), so this is a real finding about the file, not a shrug."""
    masked = node_mask(code)
    if masked is None:
        return OracleSurface(
            reason="oracle does not parse: the JavaScript tokeniser could not delimit its "
                   "literals or braces, so nothing about it can be read safely")
    symbols = node_symbols(code, index)
    return OracleSurface(symbols, tuple(node_oracle_tests(code, masked, symbols)))


#: ecosystem → reader. The registry IS the supported set: :func:`assess` reports an oracle
#: whose ecosystem is absent here by NAME and states its own limit, so adding an ecosystem is
#: one entry and removing one degrades to an honest refusal rather than to a false absence.
ORACLE_READERS: "dict[str, Callable[[str, FirstPartyIndex], OracleSurface]]" = {
    ECOSYSTEM_PYTHON: read_python_oracle,
    ECOSYSTEM_NODE: read_node_oracle,
}


def unsupported_ecosystem_reason(ecosystem: str, oracle_name: str = "") -> str:
    """The reason an oracle this assessor cannot read produces — naming the ECOSYSTEM found
    and the limit, never an absence. The sentence this replaced ("no seeded job oracle in the
    run dir") was false and pointed a reader at a seeding step that worked fine."""
    found = ECOSYSTEM_LABELS.get(ecosystem, ecosystem or ECOSYSTEM_UNKNOWN)
    reads = " and ".join(ECOSYSTEM_LABELS[e] for e in sorted(ORACLE_READERS))
    named = f" {oracle_name}" if oracle_name else ""
    return (f"unsupported oracle ecosystem: the seeded oracle{named} is {found}; this "
            f"assessor reads {reads or 'no ecosystem at all'}")


# ---------------------------------------------------------------------------
# Subject derivation
# ---------------------------------------------------------------------------


def derive_subjects(criterion_text: str, symbols: frozenset[str]) -> frozenset[str]:
    """The first-party symbols this criterion is ABOUT, or an empty set when none can be
    derived (→ ``UNDECIDABLE``).

    The rule is a SUBSET test, not an overlap score: **every** significant token of the
    symbol must appear in the criterion's prose. ``word_frequencies`` ({word, frequenc})
    binds to "the word frequency count should accurately reflect…" and does NOT bind to
    "split the text into individual words" (no frequency token). A symbol whose tokens are
    all stopwords cannot bind at all.

    The asymmetry is deliberate. A subset rule under-matches on a vocabulary mismatch, and
    under-matching lands the criterion in ``UNDECIDABLE``, which BLOCKS ``GREEN-VERIFIED``.
    An overlap score would over-match and mint coverage. Precision is the acceptable loss;
    minting coverage is not."""
    prose = prose_tokens(criterion_text)
    if not prose:
        return frozenset()
    out = set()
    for sym in symbols:
        sym_tokens = identifier_tokens(sym)
        if sym_tokens and sym_tokens <= prose:
            out.add(sym)
    return frozenset(out)


# ---------------------------------------------------------------------------
# Assessment
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CriterionCoverage:
    """One criterion's earned evidence level and the evidence behind it."""

    criterion_id: str
    tier: str
    level: str
    subjects: tuple[str, ...] = ()
    #: The tests that supplied the level (AST-verified for L2/L3; declared-only for L1).
    tests: tuple[str, ...] = ()
    reason: str = ""
    #: The mutation-discrimination state behind (or withheld from) :data:`LEVEL_KILLS` — one
    #: of :data:`L4_KILLED`, :data:`L4_SURVIVED`, :data:`L4_NOT_ATTRIBUTED`,
    #: :data:`L4_NOT_MEASURED`. Always present, so a reader never has to infer from the level
    #: alone whether L4 was refused or never asked.
    l4: str = L4_NOT_MEASURED
    #: What the L4 state rests on: the killing test names, or the surviving mutant loci.
    l4_evidence: tuple[str, ...] = ()
    #: Mutants of THIS criterion's subject(s) the exam did not catch, whatever level was
    #: earned. Populated even at :data:`LEVEL_KILLS`: a subject can have a test that
    #: discriminates and a locus where it does not, and the rung must not swallow the hole.
    l4_survivors: tuple[str, ...] = ()

    @property
    def covered(self) -> bool:
        return self.level in COVERED_LEVELS

    def to_dict(self) -> dict:
        return {
            "id": self.criterion_id,
            "tier": self.tier,
            "level": self.level,
            "subjects": list(self.subjects),
            "tests": list(self.tests),
            "reason": self.reason,
            "l4": self.l4,
            "l4_evidence": list(self.l4_evidence),
            "l4_survivors": list(self.l4_survivors),
        }


@dataclass
class TraceabilityResult:
    """The traceability assessment of one job's oracle against its acceptance criteria."""

    available: bool = False
    reason: str = ""
    criteria: list[CriterionCoverage] = field(default_factory=list)
    oracle_test_count: int = 0
    symbol_count: int = 0
    #: How first-party status was established for this assessment — the provenance of
    #: :class:`FirstPartyIndex`, carried so a reader can see which tree (or which probe)
    #: decided that a symbol belonged to the deliverable rather than to the world.
    first_party_source: str = ""
    #: The mutation evidence L4 was graded from. Default is an unavailable one, so an
    #: assessment that was handed none reports L4 as unmeasured rather than as clean.
    attribution: MutationAttribution = field(default_factory=MutationAttribution)

    @property
    def denominator(self) -> int:
        return len(self.criteria)

    def count(self, level: str) -> int:
        return sum(1 for c in self.criteria if c.level == level)

    @property
    def verified(self) -> int:
        """Criteria at L3 or above — the only ones this instrument calls covered."""
        return sum(1 for c in self.criteria if c.covered)

    @property
    def weak(self) -> int:
        """Criteria with SOME binding that never reached an assertion (L1/L2)."""
        return sum(1 for c in self.criteria if c.level in (LEVEL_DECLARED, LEVEL_BOUND))

    @property
    def gap(self) -> int:
        """Criteria with a derived subject that no test exercises — real, nameable holes."""
        return self.count(LEVEL_GAP)

    @property
    def undecidable(self) -> int:
        """Criteria this instrument cannot judge. Never covered, never a gap."""
        return self.count(LEVEL_UNDECIDABLE)

    def l4_count(self, state: str) -> int:
        return sum(1 for c in self.criteria if c.l4 == state)

    @property
    def l4_measured(self) -> int:
        """Criteria for which a per-criterion discrimination verdict was actually reached —
        killed or survived. Everything else is unmeasured, however much whole-file mutation
        the night did."""
        return sum(1 for c in self.criteria if c.l4 in L4_DETERMINED)

    @property
    def l4_blind_spots(self) -> int:
        """Criteria with at least one uncaught mutant in their own subject — counted whatever
        level they earned, so an exam that discriminates in one place and not another cannot
        report only the half that flatters it."""
        return sum(1 for c in self.criteria if c.l4_survivors)

    @property
    def l4_unmeasured(self) -> int:
        """The complement, reported explicitly and even at zero. The headline L3+ figure is
        silent about discrimination, and this is the number that says how silent."""
        return self.denominator - self.l4_measured

    @property
    def verified_class(self) -> bool:
        """Whether this job may be stamped ``GREEN-VERIFIED``.

        Requires a real denominator AND nothing unresolved: every criterion at L3+, no gaps,
        no weak bindings, and — the load-bearing clause — nothing undecidable. Not-knowing can
        never present as passing."""
        return (
            self.available
            and self.denominator > 0
            and self.undecidable == 0
            and self.gap == 0
            and self.weak == 0
            and self.verified == self.denominator
        )

    def fingerprint(self) -> str:
        """The one-line coverage stamp. Never a bare ratio: the split and the discrimination
        state ride along so the figure cannot be quoted without its exclusions.

        The L4 clause is the run's own, not a constant. ``L4 not measured`` now means this run
        had no usable attribution — it is a fact about the run, where it used to be a fact
        about the module."""
        if not self.available:
            return f"oracle_coverage=unavailable ({self.reason or 'no reason recorded'})"
        l4 = (f"L4 killed:{self.count(LEVEL_KILLS)} "
              f"survived:{self.l4_count(L4_SURVIVED)} unmeasured:{self.l4_unmeasured}"
              if self.attribution.available else "L4 not measured")
        return (
            f"oracle_coverage={self.verified}/{self.denominator} L3+ "
            f"(weak:{self.weak} gap:{self.gap} undecidable:{self.undecidable}; {l4})"
        )

    def not_measured(self) -> list[str]:
        """:data:`NOT_MEASURED` plus this run's own unmet L4 condition, when there is one.

        The static entries state permanent conditions; this adds the run-specific reason a
        whole run reached no rung, so a reader of one block never has to go and find out why
        every criterion says ``not-measured``."""
        out = list(NOT_MEASURED)
        if not self.attribution.available:
            out.insert(0, f"L4-KILLS was not measured at all for this run: "
                          f"{self.attribution.reason or 'no attribution available'}")
        return out

    def to_block(self) -> dict:
        """The ``traceability/v1`` evidence block (stable shape, advisory, no verdict)."""
        return {
            "schema": TRACEABILITY_SCHEMA,
            "advisory": True,
            "available": self.available,
            "reason": self.reason,
            "denominator": self.denominator,
            "denominator_excludes": list(DENOMINATOR_EXCLUDES),
            "verified": self.verified,
            "weak": self.weak,
            "gap": self.gap,
            "undecidable": self.undecidable,
            "levels": {lvl: self.count(lvl) for lvl in LEVELS},
            "verified_class": self.verified_class,
            "oracle_tests": self.oracle_test_count,
            "first_party_symbols": self.symbol_count,
            "first_party_source": self.first_party_source,
            # The discrimination half, always emitted: a block that carried L4 counts only
            # when they were non-zero would let "nobody measured" and "measured, nothing
            # killed" render identically.
            "l4": {
                "killed": self.count(LEVEL_KILLS),
                "survived": self.l4_count(L4_SURVIVED),
                "not_attributed": self.l4_count(L4_NOT_ATTRIBUTED),
                "measured": self.l4_measured,
                "unmeasured": self.l4_unmeasured,
                "blind_spots": self.l4_blind_spots,
                "attribution": self.attribution.to_dict(),
            },
            "not_measured": self.not_measured(),
            "criteria": [c.to_dict() for c in self.criteria],
            "fingerprint": self.fingerprint(),
        }


def test_tier_criteria(criteria: "list[dict]") -> list[dict]:
    """The criteria a pytest oracle can verify (behavior + smoke). Everything else is
    excluded from the denominator by construction — see :data:`DENOMINATOR_EXCLUDES`."""
    return [c for c in criteria if str(c.get("tier", "")) in TEST_TIERS]


def _unavailable(reason: str) -> TraceabilityResult:
    return TraceabilityResult(available=False, reason=reason)


#: The L3 reason, per L4 state. Each names what WAS established and what was not, in the same
#: sentence — the figure and its exclusion are never separable.
_L4_REASONS: "dict[str, str]" = {
    L4_KILLED:
        "a test exercises this criterion's own subject(s), asserts an outcome, and that same "
        "test FAILED when the subject was deliberately broken (killed by: {evidence})",
    L4_SURVIVED:
        "a test exercises this criterion's own subject(s) and asserts an outcome, but a "
        "deliberately broken version of that subject SURVIVED the whole exam ({evidence}), so "
        "the assertion does not discriminate there",
    L4_NOT_ATTRIBUTED:
        "a test exercises this criterion's own subject(s) and asserts an outcome; the subject "
        "WAS mutated and every mutant was caught, but only by other tests, so no kill is "
        "attributable to this criterion",
    L4_NOT_MEASURED:
        "a test exercises this criterion's own subject(s) and asserts an outcome (whether "
        "that assertion would FAIL on wrong code is L4, not measured for this criterion)",
}


def assess(
    oracle_code: str,
    criteria: "list[dict]",
    *,
    ecosystem: str = ECOSYSTEM_PYTHON,
    first_party: "FirstPartyIndex | None" = None,
    declared_map: "dict[str, list[str]] | None" = None,
    attribution: "MutationAttribution | None" = None,
) -> TraceabilityResult:
    """Assess one oracle against one criteria list. Pure, deterministic, no model.

    ``ecosystem`` selects the reader (:data:`ORACLE_READERS`); everything downstream of the
    read — subject derivation, the ladder, the counts, the honesty invariants — is
    ecosystem-blind and shared. An ecosystem with no reader returns ``available=False``
    NAMING itself (:func:`unsupported_ecosystem_reason`); it never returns a number, and it
    never reports an absence.

    ``first_party`` is the resolved module surface of the deliverable under assessment (see
    :class:`FirstPartyIndex`, built for a banked run by :func:`resolve_first_party`). It is
    REQUIRED evidence, not a hint: without an index that positively resolved something, this
    returns ``available=False``. A criterion's subject must be a symbol the deliverable itself
    provides, and an instrument that cannot establish that has not measured coverage — it has
    only measured that some name was imported.

    ``declared_map`` is an OPTIONAL ``{criterion_id: [test_name]}`` declaration (the #821 14B
    emission, when one exists). It can only ever lift a criterion from ``UNDECIDABLE`` to
    ``L1-DECLARED`` — never to L2/L3, which require AST evidence. A mapper cannot promote
    itself past the evidence stages.

    ``attribution`` is the OPTIONAL per-symbol mutation evidence
    (:class:`MutationAttribution`) that makes ``L4-KILLS`` reachable. It can only ever lift a
    criterion that ALREADY reached L3 on AST evidence — mutation evidence answers "does this
    assertion discriminate", which presupposes an assertion; it can never supply one. Omitted
    or unavailable, every criterion grades exactly as it did before and reports L4 as
    unmeasured.

    Never raises: an unparseable oracle, an empty criteria set, or an unresolved first-party
    index yields ``available=False`` with a reason, never a number."""
    if not (oracle_code or "").strip():
        return _unavailable("no oracle code")
    reader = ORACLE_READERS.get(ecosystem)
    if reader is None:
        return _unavailable(unsupported_ecosystem_reason(ecosystem))

    index = first_party if first_party is not None else FirstPartyIndex.unresolved(
        "no first-party index supplied")
    surface = reader(oracle_code, index)
    if not surface.readable:
        return _unavailable(surface.reason)
    if not index.resolved:
        return _unavailable(
            f"first-party module surface not resolved, so no symbol can be attributed to the "
            f"deliverable ({index.source})")

    tier_criteria = test_tier_criteria(criteria or [])
    if not tier_criteria:
        return _unavailable("no test-tier (behavior/smoke) criteria")

    symbols = surface.symbols
    tests = list(surface.tests)
    declared = declared_map or {}
    attr = attribution if attribution is not None else MutationAttribution.unavailable(
        "no mutation attribution supplied to this assessment")

    rows: list[CriterionCoverage] = []
    for crit in tier_criteria:
        cid = str(crit.get("id", ""))
        tier = str(crit.get("tier", ""))
        text = f"{crit.get('text', '')} {crit.get('check', '')}"
        subjects = derive_subjects(text, symbols)

        if not subjects:
            # Nothing deterministic to stand on. A declaration may name a real test, which is
            # the mapper's assertion and nothing more — L1, never covered.
            named = [t for t in declared.get(cid, []) if any(x.name == t for x in tests)]
            if named:
                rows.append(CriterionCoverage(
                    cid, tier, LEVEL_DECLARED, (), tuple(named),
                    "a mapper named this test; no subject could be derived from the "
                    "criterion's own wording, so nothing verifies the claim",
                ))
            else:
                rows.append(CriterionCoverage(
                    cid, tier, LEVEL_UNDECIDABLE, (), (),
                    "no oracle symbol's name is contained in this criterion's wording; "
                    "coverage cannot be determined either way",
                ))
            continue

        subj = tuple(sorted(subjects))
        exercising = [t for t in tests if t.exercises & subjects]
        if not exercising:
            rows.append(CriterionCoverage(
                cid, tier, LEVEL_GAP, subj, (),
                "this criterion's subject exists in the oracle's imports but no test "
                "exercises it",
            ))
            continue

        # A criterion naming SEVERAL symbols ("the report should combine the word frequency
        # and neighbouring pair counts") is only covered when every one of them is actually
        # touched — otherwise the criterion banks on whichever subject happened to bind and
        # the one it is centrally about goes untested. Requiring all to be EXERCISED but only
        # one to be ASSERTED is the deliberate middle: it refuses the over-credit without
        # manufacturing a false GAP, which is a positive claim and can itself be wrong.
        touched = {s for t in exercising for s in (t.exercises & subjects)}
        unexercised = sorted(subjects - touched)
        # The predicate is the assertion BEARING ON this criterion's subject — never the mere
        # co-presence of a call and an unrelated `assert` in the same function. `assert True`
        # and an assertion about a different symbol both satisfy "the test asserts something",
        # and neither is evidence that THIS criterion was verified.
        asserting = [t.name for t in exercising if t.asserts_on & subjects]
        if asserting and not unexercised:
            # L4 is graded only from here: the rung asks whether THIS criterion's asserting
            # test discriminates, so it is a refinement of L3 and never a route to it.
            state, l4_evidence, l4_survivors = attr.verdict_for(subjects, set(asserting))
            reason = _L4_REASONS[state].format(evidence=", ".join(l4_evidence))
            if state == L4_KILLED and l4_survivors:
                # ASCII only, for the reason CorpusAggregate.render records: these strings are
                # read on a cp1252 console, where an em dash arrives as a replacement char.
                reason += (f"; but {len(l4_survivors)} other mutant(s) of the same subject "
                           f"SURVIVED the exam ({', '.join(l4_survivors)}), so the rung is "
                           f"earned and the subject is still partly unguarded")
            rows.append(CriterionCoverage(
                cid, tier,
                LEVEL_KILLS if state == L4_KILLED else LEVEL_ASSERTED,
                subj, tuple(sorted(asserting)), reason,
                l4=state, l4_evidence=l4_evidence, l4_survivors=l4_survivors,
            ))
            continue
        if unexercised:
            detail = f"subject(s) {', '.join(unexercised)} are never exercised"
        elif any(t.has_assertion for t in exercising):
            # The distinction the blanket "does this test assert anything" predicate erased:
            # a test CAN assert loudly and still assert nothing about the subject it called.
            detail = ("a test calls this criterion's subject and does assert, but no assertion "
                      "bears on the subject, directly or through a value read back from it")
        else:
            detail = "a test calls this criterion's subject but the test asserts nothing"
        rows.append(CriterionCoverage(
            cid, tier, LEVEL_BOUND, subj,
            tuple(sorted(t.name for t in exercising)), detail,
        ))

    return TraceabilityResult(
        available=True, criteria=rows,
        oracle_test_count=len(tests), symbol_count=len(symbols),
        first_party_source=index.source, attribution=attr,
    )


# ---------------------------------------------------------------------------
# Run-directory entry point (battery close reads what the run already banked)
# ---------------------------------------------------------------------------

#: The seeded job oracle, as the dispatch names it in the run dir — EVERY ecosystem, because
#: the glob is what decides whether an oracle is visible at all. It read ``job-oracle-*.py``
#: until #1348, so the 12 node oracles in the banked corpus were not merely unassessed, they
#: were reported ABSENT: the instrument said "no seeded job oracle in the run dir" while the
#: file sat beside the sidecar it was writing. A discovery filter that also decides what
#: EXISTS is the shape to watch for; here the two questions are now separate, and the
#: ecosystem is classified from the suffix afterwards.
_ORACLE_GLOB = "job-oracle-*"

#: Which ecosystem's oracle to grade when a run banked more than one. Python leads so a
#: corpus already assessed cannot shift under a re-run; the order is otherwise arbitrary and
#: the case does not arise in the banked corpus.
_ECOSYSTEM_PREFERENCE: tuple[str, ...] = (ECOSYSTEM_PYTHON, ECOSYSTEM_NODE)
#: The spec the plan approved, carrying the criteria.
_ACCEPTANCE_NAME = "acceptance.json"
#: The #821 sidecar — read ONLY for its optional declared map.
_ORACLE_QA_NAME = "oracle-qa.json"
#: The #822 resolve-probe pair: the oracle's import targets, and the verdict recording which
#: of them actually resolved against the DELIVERED tree. Together they are banked, run-time
#: proof of first-party status — evidence that cannot rot the way the tree itself can.
_IMPORT_PROBE_TARGETS_NAME = "import-probe-targets.json"
_IMPORT_PROBE_VERDICT_NAME = "import-probe-verdict.json"
#: The run's own scorecard, read ONLY for the repo path (the fallback tree to resolve against).
_SCORECARD_NAME = "scorecard.json"
#: Where a python deliverable puts its top-level modules. Bounded on purpose: a deep walk of
#: an arbitrary project tree is neither needed nor cheap, and a module this misses is a
#: subject that goes unattributed — the under-counting direction.
_SOURCE_LAYOUT_DIRS: tuple[str, ...] = ("", "src")
#: Directory entries never scanned for a module root.
_TREE_SCAN_SKIP: frozenset[str] = frozenset({"__pycache__", "node_modules"})


def _read_json(path: Path) -> Optional[dict]:
    data = _read_json_any(path)
    return data if isinstance(data, dict) else None


def _read_json_any(path: Path) -> "object | None":
    """Any JSON document (the probe targets file is a top-level list, not an object)."""
    try:
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _roots_from_import_probe(run_dir: Path) -> "FirstPartyIndex | None":
    """The strongest available evidence: the roots the run's own resolve-probe IMPORTED from
    the delivered tree. ``None`` when the run banked no probe, or when the probe resolved
    nothing — never an empty index, which would read as "the deliverable provides nothing"."""
    targets = _read_json_any(run_dir / _IMPORT_PROBE_TARGETS_NAME)
    verdict = _read_json(run_dir / _IMPORT_PROBE_VERDICT_NAME)
    if not isinstance(targets, list) or not targets or verdict is None:
        return None
    # An unresolved entry carrying a ``name`` means the MODULE resolved and one export was
    # missing; only a module-level failure disqualifies the root.
    failed = {
        str(e.get("module", "")).split(".", 1)[0]
        for e in (verdict.get("unresolved") or [])
        if isinstance(e, dict) and not e.get("name")
    }
    roots = {
        str(t.get("module", "")).split(".", 1)[0]
        for t in targets
        if isinstance(t, dict) and t.get("kind") == "py" and not int(t.get("level") or 0)
    }
    roots = {r for r in roots if r and r not in failed}
    if not roots:
        return None
    return FirstPartyIndex.from_roots(
        roots, source=f"{_IMPORT_PROBE_TARGETS_NAME} (resolved against the delivered tree)")


def _roots_from_tree(repo: Path) -> frozenset[str]:
    """The top-level python module roots a delivered tree provides — ``x.py``, ``x/`` holding
    any ``.py``, under the repo root and a ``src/`` layout."""
    roots: set[str] = set()
    for rel in _SOURCE_LAYOUT_DIRS:
        base = repo / rel if rel else repo
        try:
            entries = list(base.iterdir())
        except OSError:
            continue
        for entry in entries:
            name = entry.name
            if name.startswith(".") or name in _TREE_SCAN_SKIP:
                continue
            try:
                if entry.is_file():
                    if name.endswith(".py"):
                        roots.add(name[:-3])
                elif entry.is_dir() and any(c.suffix == ".py" for c in entry.iterdir()):
                    roots.add(name)
            except OSError:
                continue
    return frozenset(roots)


def _specs_from_import_probe(run_dir: Path) -> "FirstPartyIndex | None":
    """The node twin of :func:`_roots_from_import_probe`: the ESM specifiers the run's own
    resolve-probe actually IMPORTED from the delivered tree.

    The probe's unresolved rows follow the same convention in both ecosystems — an entry
    carrying a ``name`` means the module resolved and one export was missing or was not a
    function, so only a MODULE-level failure (no ``name``) disqualifies the specifier."""
    targets = _read_json_any(run_dir / _IMPORT_PROBE_TARGETS_NAME)
    verdict = _read_json(run_dir / _IMPORT_PROBE_VERDICT_NAME)
    if not isinstance(targets, list) or not targets or verdict is None:
        return None
    failed = {
        str(e.get("spec", ""))
        for e in (verdict.get("unresolved") or [])
        if isinstance(e, dict) and not e.get("name")
    }
    specs = {
        str(t.get("spec", ""))
        for t in targets
        if isinstance(t, dict) and t.get("kind") == ECOSYSTEM_NODE
    }
    specs = {s for s in specs if s and s not in failed}
    if not specs:
        return None
    return FirstPartyIndex.from_specifiers(
        specs, source=f"{_IMPORT_PROBE_TARGETS_NAME} (node specifiers resolved against the "
                      f"delivered tree)")


def _node_specs_from_tree(repo: Path, code: str) -> frozenset[str]:
    """The oracle's relative specifiers that name a file the delivered tree actually holds.

    The node twin of :func:`_roots_from_tree`, and POSITIVE in the same way: a specifier is
    first-party only once a file answers to it. The oracle lives one directory down from the
    root (``tests/acceptance.job.test.mjs``), so the leading ``./`` / ``../`` hops are
    stripped and the remainder is resolved from the repo root — which is where
    ``../src/pieces/data.js`` was always pointing.

    A specifier this cannot place contributes nothing; it never falls back to trusting the
    ``./`` prefix, because "the oracle says this is mine" is the assumption the whole
    first-party design exists to refuse."""
    out: set[str] = set()
    for spec, _names in node_import_bindings(code):
        if not spec.startswith("."):
            continue
        tail = spec
        while tail.startswith(("./", "../")):
            tail = tail.split("/", 1)[1] if "/" in tail else ""
        if not tail:
            continue
        try:
            if (repo / tail).is_file():
                out.add(spec)
        except OSError:
            continue
    return frozenset(out)


def resolve_first_party(run_dir: "str | Path", *,
                        ecosystem: str = ECOSYSTEM_PYTHON,
                        oracle_code: str = "") -> FirstPartyIndex:
    """Establish, from what a run banked, which modules the DELIVERABLE provides.

    Two sources, strongest first: the #822 resolve-probe pair (banked at run time, so it
    describes the tree as it was), then the tree named by ``scorecard.json``'s ``repo``. The
    second is weaker and says so in its provenance — a sandbox repo is rebuilt between battery
    nights, so a root read today may not be the root the oracle imported.

    ``ecosystem`` chooses the UNITS: python module roots, or node ESM specifiers
    (:meth:`FirstPartyIndex.from_specifiers`). ``oracle_code`` is needed only by the node
    tree fallback, which has no specifier list of its own to work from.

    Neither source available → :meth:`FirstPartyIndex.unresolved`, which denies a number
    rather than falling back to "everything imported is ours"."""
    try:
        d = Path(run_dir)
        node = ecosystem == ECOSYSTEM_NODE
        probed = _specs_from_import_probe(d) if node else _roots_from_import_probe(d)
        if probed is not None:
            return probed
        scorecard = _read_json(d / _SCORECARD_NAME) or {}
        repo = str(scorecard.get("repo") or "").strip()
        if not repo:
            return FirstPartyIndex.unresolved(
                f"no usable {_IMPORT_PROBE_TARGETS_NAME} and no repo in {_SCORECARD_NAME}")
        tree = Path(repo)
        if not tree.is_dir():
            return FirstPartyIndex.unresolved(f"delivered tree {tree.name} is no longer on disk")
        after = f"delivered tree {tree.name} (read after the run; may have moved on)"
        if node:
            specs = _node_specs_from_tree(tree, oracle_code)
            if not specs:
                return FirstPartyIndex.unresolved(
                    f"delivered tree {tree.name} holds none of the modules the oracle imports")
            return FirstPartyIndex.from_specifiers(specs, source=after)
        roots = _roots_from_tree(tree)
        if not roots:
            return FirstPartyIndex.unresolved(
                f"delivered tree {tree.name} provides no importable python module")
        return FirstPartyIndex.from_roots(roots, source=after)
    except Exception as exc:  # noqa: BLE001 — advisory: resolution never sinks an assessment
        return FirstPartyIndex.unresolved(f"resolution error: {type(exc).__name__}")


def _declared_from_oracle_qa(run_dir: Path) -> "dict[str, list[str]] | None":
    """The #821 declaration, if that stage produced one. ``covered`` is a bare id list (the
    test names are not persisted), so it can only mark a criterion DECLARED — which is
    exactly the strength a model assertion has."""
    qa = _read_json(run_dir / _ORACLE_QA_NAME)
    if not qa:
        return None
    covered = qa.get("covered")
    if not isinstance(covered, list) or not covered:
        return None
    return {str(c): [] for c in covered}


def discover_oracle(run_dir: "str | Path") -> "tuple[Optional[Path], str]":
    """The seeded oracle a run banked, and its ecosystem.

    Two questions, kept apart on purpose. DOES an oracle exist is answered by the glob over
    every suffix; WHICH ecosystem it is, by :data:`ORACLE_SUFFIX_ECOSYSTEM`. Collapsing them
    (a glob that only matches ``.py``) is what made a node oracle report as an absence.

    Returns ``(None, ECOSYSTEM_UNKNOWN)`` only when the run really banked nothing. A file
    this module cannot read still comes BACK, with the ecosystem it was classified as — so
    the caller can name it rather than deny it."""
    d = Path(run_dir)
    candidates = sorted(p for p in d.glob(_ORACLE_GLOB) if p.is_file())
    if not candidates:
        return None, ECOSYSTEM_UNKNOWN
    classified = [(p, ORACLE_SUFFIX_ECOSYSTEM.get(p.suffix.lower(), ECOSYSTEM_UNKNOWN))
                  for p in candidates]
    for ecosystem in _ECOSYSTEM_PREFERENCE:
        for path, found in classified:
            if found == ecosystem:
                return path, found
    return classified[0]


def assess_run(run_dir: "str | Path") -> TraceabilityResult:
    """Assess one dispatch run directory. Reads only artifacts the run already banked —
    ``acceptance.json`` for the criteria, ``job-oracle-*`` for the exam whatever ecosystem it
    is written in (:func:`discover_oracle`), the resolve-probe pair (or the scorecard's repo)
    for which symbols are the DELIVERABLE's (:func:`resolve_first_party`), and
    ``oracle-mutation.json`` for the per-criterion
    discrimination evidence L4 needs (:func:`load_mutation_attribution`) — so this can be
    computed at battery close, and retroactively over every night already recorded.

    A night banked before any of those artifacts existed still assesses; it simply reaches
    the rungs its evidence supports and says which it could not.

    Wholly fail-soft: any missing/unreadable input yields ``available=False`` with a reason."""
    try:
        d = Path(run_dir)
        if not d.is_dir():
            return _unavailable(f"run dir not found: {d}")
        acceptance = _read_json(d / _ACCEPTANCE_NAME)
        if not acceptance:
            return _unavailable(f"no readable {_ACCEPTANCE_NAME}")
        spec = acceptance.get("spec")
        criteria = (spec or {}).get("criteria") if isinstance(spec, dict) else None
        if not isinstance(criteria, list) or not criteria:
            return _unavailable("acceptance.json carries no criteria")
        oracle, ecosystem = discover_oracle(d)
        if oracle is None:
            return _unavailable("no seeded job oracle in the run dir")
        if ecosystem not in ORACLE_READERS:
            return _unavailable(unsupported_ecosystem_reason(ecosystem, oracle.name))
        code = oracle.read_text(encoding="utf-8", errors="replace")
        return assess(code, criteria, ecosystem=ecosystem,
                      first_party=resolve_first_party(d, ecosystem=ecosystem,
                                                      oracle_code=code),
                      declared_map=_declared_from_oracle_qa(d),
                      attribution=load_mutation_attribution(d, code))
    except Exception as exc:  # noqa: BLE001 — advisory: never sink a battery close
        return _unavailable(f"assessment error: {type(exc).__name__}")


def assess_and_persist(run_dir: "str | Path", *, write: bool = True) -> TraceabilityResult:
    """:func:`assess_run` plus the sidecar write — the battery-close motion in one call, so
    a caller cannot assess without banking the evidence it just computed."""
    result = assess_run(run_dir)
    if write:
        write_sidecar(run_dir, result)
    return result


def write_sidecar(run_dir: "str | Path", result: TraceabilityResult) -> str:
    """Persist the block as ``traceability.json`` in the run dir; returns the pointer or
    ``""``. Fail-soft — a persist miss is never fatal."""
    try:
        d = Path(run_dir)
        d.mkdir(parents=True, exist_ok=True)
        (d / TRACEABILITY_SIDECAR_NAME).write_text(
            json.dumps(result.to_block(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return f"{d.name}/{TRACEABILITY_SIDECAR_NAME}"
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# CLI — so the instrument can be RUN over banked nights, not merely wired
# ---------------------------------------------------------------------------


def _render(run_id: str, result: TraceabilityResult, *, verbose: bool) -> list[str]:
    """Human lines for one run: the stamp, then (verbose) the per-criterion ladder."""
    lines = [f"{run_id}: {result.fingerprint()}"]
    if verbose:
        if result.first_party_source:
            lines.append(f"    first-party: {result.first_party_source}")
        if result.attribution.source or result.attribution.reason:
            lines.append(f"    mutation: {result.attribution.source or result.attribution.reason}")
        for c in result.criteria:
            subj = ",".join(c.subjects) or "-"
            lines.append(f"    {c.criterion_id:4} [{c.tier:8}] {c.level:14} "
                         f"l4={c.l4:14} subj={subj}")
            lines.append(f"         {c.reason}")
    return lines


#: How much of an ``available=False`` reason survives into the aggregate bucket. The reasons
#: carry run-specific tails (a path, an exception type, a vanished tree's name); the bucket is
#: the part that classifies.
_REASON_BUCKET_CHARS = 62


def _reason_bucket(reason: str) -> str:
    """A reason string reduced to its CLASS, so a corpus of them can be counted.

    Split at the first ``: ``, `` (`` or ``,`` — every ``_unavailable`` reason in this module
    states its class first and puts the variable part (a path, an exception name, a tree that
    vanished) and any elaborating clause after one of those."""
    text = (reason or "unrecorded").strip()
    for sep in (": ", " (", ","):
        cut = text.find(sep)
        if cut > 0:
            text = text[:cut]
    return text[:_REASON_BUCKET_CHARS].rstrip()


@dataclass(frozen=True)
class CorpusAggregate:
    """Corpus-wide totals for an ``--all`` sweep, plus WHY the unassessed runs were skipped.

    This type exists because of a measured failure, not for tidiness. On 2026-07-30 three
    independent readers — the builder, the reviewer, and the lead — each ran the ``--all``
    sweep over 221 run dirs, read the last 25-40 lines of a 223-line output, and reported the
    sample as the corpus. The tool printed one line per run and nothing else, so nothing on
    screen distinguished "the whole result" from "the tail of it". Three people making the
    same mistake on the same afternoon is a property of the instrument, not of the readers.

    The control is that :meth:`render` goes LAST, so the truncation that caused the failure
    now amputates the per-run detail and leaves the conclusion — the most useful output rather
    than the most misleading."""

    runs: int
    assessable: int
    criteria: int
    verified: int
    weak: int
    gap: int
    undecidable: int
    verified_class: int
    #: ``(reason bucket, count)``, most frequent first — the number that explains why the
    #: headline denominator is smaller than the run count.
    unavailable: "tuple[tuple[str, int], ...]" = ()
    #: Criteria whose own asserting test provably failed on a broken subject.
    l4_killed: int = 0
    #: Criteria a mutant of whose subject the exam did not catch at all.
    l4_survived: int = 0
    #: Criteria for which no discrimination verdict was reached. Carried alongside the two
    #: above so the corpus can never quote a kill count without the silence around it.
    l4_unmeasured: int = 0
    #: Assessable runs that banked usable mutation attribution. Zero means the corpus's L4
    #: figures are the absence of measurement, not the absence of kills.
    l4_runs: int = 0

    @property
    def balances(self) -> bool:
        """Whether the four-way split accounts for every criterion. It must, by construction:
        the ladder's six levels partition into verified (L3/L4), weak (L1/L2), gap (L0) and
        undecidable. Checked rather than assumed, because a future arithmetic change that
        silently stopped adding up would produce a summary that still LOOKS authoritative."""
        return self.criteria == self.verified + self.weak + self.gap + self.undecidable

    @property
    def verified_pct(self) -> float:
        return (100.0 * self.verified / self.criteria) if self.criteria else 0.0

    def to_dict(self) -> dict:
        return {
            "runs": self.runs,
            "assessable": self.assessable,
            "criteria": self.criteria,
            "verified": self.verified,
            "verified_pct": round(self.verified_pct, 1),
            "weak": self.weak,
            "gap": self.gap,
            "undecidable": self.undecidable,
            "verified_class": self.verified_class,
            "balances": self.balances,
            "l4_killed": self.l4_killed,
            "l4_survived": self.l4_survived,
            "l4_unmeasured": self.l4_unmeasured,
            "l4_runs": self.l4_runs,
            "unavailable": [{"reason": r, "runs": n} for r, n in self.unavailable],
        }

    def render(self) -> list[str]:
        """The summary block. Emitted LAST so a truncating reader keeps the conclusion."""
        rule = "=" * 72
        check = (f"{self.criteria} = {self.verified} + {self.weak} + {self.gap} + "
                 f"{self.undecidable}")
        lines = [
            "",
            rule,
            # ASCII only: this block is read on a cp1252 console, where an em dash arrives as
            # a replacement character in the one output the reader is meant to trust.
            f"CORPUS SUMMARY - {self.assessable} of {self.runs} run dirs assessable",
            rule,
            f"  criteria           {self.criteria:>6}",
            f"  L3+ verified       {self.verified:>6}  ({self.verified_pct:.1f}%)",
            f"  weak (L1/L2)       {self.weak:>6}",
            f"  gap (L0)           {self.gap:>6}",
            f"  undecidable        {self.undecidable:>6}",
            f"  GREEN-VERIFIED     {self.verified_class:>6}  of {self.assessable} runs",
            f"  arithmetic         {check}"
            + ("  OK" if self.balances else "  ** DOES NOT BALANCE **"),
            f"  L4 killed          {self.l4_killed:>6}  (survived {self.l4_survived}, "
            f"unmeasured {self.l4_unmeasured})",
        ]
        if self.unavailable:
            lines.append(f"  not assessable     {self.runs - self.assessable:>6}:")
            lines.extend(f"      {n:>5}  {reason}" for reason, n in self.unavailable)
        # The L4 note is the RUN's, not the module's. A corpus where no run banked mutation
        # attribution must not read as one where the exams were asked and answered.
        lines.extend(["", (
            f"L4-KILLS measured on {self.l4_runs} of {self.assessable} assessable runs; "
            f"see each block's not_measured list."
            if self.l4_runs else
            "L4-KILLS is not measured on ANY run in this corpus; see the blocks' "
            "not_measured lists."
        ), rule])
        return lines


def aggregate(results: "list[tuple[str, TraceabilityResult]]") -> CorpusAggregate:
    """Fold a sweep's per-run results into the corpus totals. Pure; no I/O."""
    totals = {"criteria": 0, "verified": 0, "weak": 0, "gap": 0, "undecidable": 0}
    assessable = verified_class = 0
    l4_killed = l4_survived = l4_unmeasured = l4_runs = 0
    reasons: "dict[str, int]" = {}
    for _run_id, result in results:
        if not result.available:
            bucket = _reason_bucket(result.reason)
            reasons[bucket] = reasons.get(bucket, 0) + 1
            continue
        assessable += 1
        verified_class += 1 if result.verified_class else 0
        totals["criteria"] += result.denominator
        totals["verified"] += result.verified
        totals["weak"] += result.weak
        totals["gap"] += result.gap
        totals["undecidable"] += result.undecidable
        l4_killed += result.count(LEVEL_KILLS)
        l4_survived += result.l4_count(L4_SURVIVED)
        l4_unmeasured += result.l4_unmeasured
        l4_runs += 1 if result.attribution.available else 0
    ordered = tuple(sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0])))
    return CorpusAggregate(
        runs=len(results), assessable=assessable, verified_class=verified_class,
        unavailable=ordered, l4_killed=l4_killed, l4_survived=l4_survived,
        l4_unmeasured=l4_unmeasured, l4_runs=l4_runs, **totals,
    )


def main(argv: "list[str] | None" = None) -> int:
    """Assess one run dir, or every run under a root. ``--write`` banks the sidecar.

    Read-only by default: an integrity instrument that rewrites evidence as a side effect of
    being INSPECTED would make its own history unauditable.

    Under ``--all`` the corpus summary (:class:`CorpusAggregate`) is the LAST thing printed,
    which is deliberate and load-bearing — see that class for the failure it exists to prevent.
    Returns 2 if the summary's own arithmetic does not close."""
    import argparse

    p = argparse.ArgumentParser(
        prog="traceability",
        description="Requirement -> oracle-assertion coverage for a dispatch run.",
    )
    p.add_argument("path", help="a run dir, or a root holding many (with --all)")
    p.add_argument("--all", action="store_true",
                   help="treat PATH as a root and assess every run dir beneath it")
    p.add_argument("--write", action="store_true",
                   help="bank traceability.json into each run dir (default: read-only)")
    p.add_argument("-v", "--verbose", action="store_true", help="per-criterion detail")
    p.add_argument("--json", action="store_true", help="emit the raw block(s) as JSON")
    args = p.parse_args(argv)

    root = Path(args.path)
    runs = sorted(d for d in root.iterdir() if d.is_dir()) if args.all else [root]
    blocks: dict[str, dict] = {}
    results: "list[tuple[str, TraceabilityResult]]" = []
    lines: list[str] = []
    for run in runs:
        result = assess_and_persist(run, write=args.write) if args.write else assess_run(run)
        blocks[run.name] = result.to_block()
        results.append((run.name, result))
        lines.extend(_render(run.name, result, verbose=args.verbose))

    totals = aggregate(results) if args.all else None

    if args.json:
        # ``--all`` emits ``{"runs": {...}, "aggregate": {...}}`` so a machine reader gets the
        # corpus figures from the same document as the per-run blocks; a single run emits its
        # block unwrapped, unchanged.
        payload = ({"runs": blocks, "aggregate": totals.to_dict()} if totals is not None
                   else next(iter(blocks.values())))
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print("\n".join(lines))
        if totals is not None:
            print("\n".join(totals.render()))
    # A summary whose own arithmetic does not close is not a smaller problem than a failed
    # sweep — it is a figure that reads as authoritative and is not. Exit non-zero so a script
    # cannot consume it as if it were sound.
    return 0 if (totals is None or totals.balances) else 2


if __name__ == "__main__":  # pragma: no cover — CLI entry
    raise SystemExit(main())
