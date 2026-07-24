"""Committed grading instruments (#1079).

An INSTRUMENT namespace, deliberately outside the surface it grades. The
coordinator graduation grader measures ``shared/coordinator/`` and
``shared/fleet/coord_lifecycle.py``; living here rather than inside
``shared/coordinator/`` keeps two things honest:

* the graded surface gains no new code, so grading cannot be mistaken for a
  coordinator capability (ADR-039's advisory-only severance is about what the
  coordinator can DO — an instrument that only reads must not be filed under it);
* the criteria's two reset triggers stay distinguishable — "a change under
  ``shared/coordinator/``" and "a change to the grading harness" are separate
  clauses in ``docs/governance/coordinator_graduation_criteria_2026-07-23.md``
  §2, and separate directories make which one fired self-evident.

Everything here REPORTS. No module in this package writes config, flips a flag,
or mutates the store it reads.
"""

from shared.grading.claim_oracle import (
    ClaimAtom,
    OracleVerdict,
    Predicate,
    TruthValue,
    adjudicate,
)
from shared.grading.corpus import (
    AdversarialCase,
    CorpusUnavailableError,
    discover_corpus_path,
    load_corpus,
)
from shared.grading.run_facts import RunFacts, read_run_facts
from shared.grading.coordinator_graduation import (
    DecisionGrade,
    DecisionsLayerReport,
    GradingReport,
    StatementGrade,
    WordsLayerReport,
    grade_window,
)

__all__ = [
    "AdversarialCase",
    "ClaimAtom",
    "CorpusUnavailableError",
    "DecisionGrade",
    "DecisionsLayerReport",
    "GradingReport",
    "OracleVerdict",
    "Predicate",
    "RunFacts",
    "StatementGrade",
    "TruthValue",
    "WordsLayerReport",
    "adjudicate",
    "discover_corpus_path",
    "grade_window",
    "load_corpus",
    "read_run_facts",
]
