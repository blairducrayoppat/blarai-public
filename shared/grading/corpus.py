"""The adversarial corpus of known-false statements (#1079, criteria §3).

WHY A CORPUS AT ALL. The criteria bar the guard's catch rate at ≥90% over ≥20
real false-statement instances. False statements are rare — the 34-cycle 07-22
window produced exactly one — so a raw window cannot reach 20 in any reasonable
time. The ratified route is adversarial grading (ADR-039 §2.16 induced-proposal
susceptibility): a committed set of statements whose falsehood is KNOWN because
it was constructed, fed to the guard alongside the live instances.

WHY THE CASES CARRY LABELS RATHER THAN BEING ADJUDICATED. A corpus case is
labelled false by construction, so :mod:`shared.grading.claim_oracle` is not
consulted for it. That is deliberate: the corpus exists to exercise guard
classes the oracle abstains on (the litotes parity trap), and running them
through the oracle would silently drop exactly the cases the corpus was built to
cover. The oracle is still held to the labels — a test asserts it never
adjudicates a corpus case TRUE, so the two can disagree by abstention but never
by contradiction.

LOCATION IS A PARAMETER, NOT A CONSTANT. The corpus is resolved by ORDERED
DISCOVERY over :data:`CORPUS_SEARCH_PATH`, overridable explicitly, and the
resolved path plus a content fingerprint are recorded in every report. A figure
therefore always states which case set produced it, and moving the canonical
corpus is a search-path edit rather than a re-derivation of past numbers.
Discovery is fail-LOUD: no corpus raises :class:`CorpusUnavailableError` rather
than grading zero adversarial cases, which would report a vacuous 0/0 catch rate
as though it were a measurement.

The corpus is ADD-ONLY, and its SIZE is a measurement input rather than a
constant: the criteria bar the catch rate over >= 20 false instances, so a larger
set is a stronger measurement. Compare two catch rates only when their
:attr:`LoadedCorpus.sha256` match.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final

__all__ = [
    "AdversarialCase",
    "CORPUS_SEARCH_PATH",
    "CorpusUnavailableError",
    "LoadedCorpus",
    "discover_corpus_path",
    "load_corpus",
]

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]

#: Candidate corpus locations, most-specific first. The packaged copy is last so a
#: relocated canonical corpus wins without this file changing.
CORPUS_SEARCH_PATH: Final[tuple[Path, ...]] = (
    _REPO_ROOT / "docs" / "governance" / "coordinator_guard_adversarial_corpus.jsonl",
    _REPO_ROOT / "evals" / "golden" / "coordinator_guard_adversarial_corpus.jsonl",
    Path(__file__).resolve().parent
    / "data"
    / "coordinator_guard_adversarial_corpus.jsonl",
)


class CorpusUnavailableError(RuntimeError):
    """No adversarial corpus could be resolved, or the resolved one is unusable.

    Fail-loud by design: an empty or missing corpus would otherwise yield a 0/0
    catch rate that reads like a passing measurement."""


@dataclass(frozen=True)
class AdversarialCase:
    """One known-false statement plus the run facts it is false ABOUT.

    The facts matter: "the run completed successfully" is false only against a
    run that did not. Each case therefore carries the ``oracle_passed`` /
    ``merged`` / ``parked`` triple the guard is handed, so the case exercises the
    guard through its real
    :class:`~shared.coordinator.prose_guard.RunTruth` input."""

    case_id: str
    text: str
    oracle_passed: bool
    merged: bool
    parked: bool
    expected_false: bool
    origin: str


@dataclass(frozen=True)
class LoadedCorpus:
    """A resolved corpus: its cases, where they came from, and their fingerprint."""

    cases: tuple[AdversarialCase, ...]
    path: Path
    sha256: str
    """SHA-256 of the corpus file's bytes. Recorded in every report so a catch
    rate can be tied to the exact case set that produced it."""


def discover_corpus_path(
    explicit: Path | None = None,
    *,
    search_path: tuple[Path, ...] = CORPUS_SEARCH_PATH,
) -> Path:
    """The corpus to use: *explicit* if given, else the first existing
    :data:`CORPUS_SEARCH_PATH` entry.

    Raises:
        CorpusUnavailableError: an explicit path that does not exist, or no
            candidate found — never a silent fallback to zero cases."""
    if explicit is not None:
        if not explicit.is_file():
            raise CorpusUnavailableError(
                f"adversarial corpus {explicit} does not exist (explicitly requested)"
            )
        return explicit
    for candidate in search_path:
        if candidate.is_file():
            return candidate
    searched = "; ".join(str(p) for p in search_path)
    raise CorpusUnavailableError(
        "no adversarial corpus found — the words-layer catch rate cannot be "
        f"measured without one (searched: {searched})"
    )


def load_corpus(
    explicit: Path | None = None,
    *,
    search_path: tuple[Path, ...] = CORPUS_SEARCH_PATH,
) -> LoadedCorpus:
    """Load and fingerprint the adversarial corpus.

    Every record must carry the full case shape; a malformed or duplicate-id
    record raises rather than being skipped, so a truncated corpus can never
    quietly shrink a catch-rate denominator."""
    path = discover_corpus_path(explicit, search_path=search_path)
    raw = path.read_bytes()
    cases: list[AdversarialCase] = []
    seen: set[str] = set()
    for lineno, line in enumerate(raw.decode("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError as exc:
            raise CorpusUnavailableError(
                f"{path}:{lineno}: not valid JSON — {exc}"
            ) from exc
        try:
            case = AdversarialCase(
                case_id=str(record["case_id"]),
                text=str(record["text"]),
                oracle_passed=bool(record["oracle_passed"]),
                merged=bool(record["merged"]),
                parked=bool(record["parked"]),
                expected_false=bool(record["expected_false"]),
                origin=str(record.get("origin", "")),
            )
        except (KeyError, TypeError) as exc:
            raise CorpusUnavailableError(
                f"{path}:{lineno}: malformed corpus record — {exc}"
            ) from exc
        if case.case_id in seen:
            raise CorpusUnavailableError(
                f"{path}:{lineno}: duplicate case_id {case.case_id!r}"
            )
        seen.add(case.case_id)
        cases.append(case)
    if not cases:
        raise CorpusUnavailableError(f"{path}: corpus is empty")
    return LoadedCorpus(
        cases=tuple(cases), path=path, sha256=hashlib.sha256(raw).hexdigest()
    )
