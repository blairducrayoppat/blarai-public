"""Job-level acceptance oracle for the B2 text-stats diamond (#752 F2).

Graded once on the final integrated tree after all four arms merge. Imports each arm's public
interface from the ``app`` package (matching the F1 decomposition and the sibling F3 per-task
oracles) and asserts the JOINED behaviour on a known sample.
"""
import re

from app.tokenize import tokenize
from app.word_frequencies import word_frequencies
from app.neighbor_pairs import neighbor_pairs
from app.report import combined_report

SAMPLE = "The cat sat on the mat. The cat ran."
EXPECTED_TOKENS = ["the", "cat", "sat", "on", "the", "mat", "the", "cat", "ran"]
EXPECTED_FREQUENCIES = {"the": 3, "cat": 2, "sat": 1, "on": 1, "mat": 1, "ran": 1}
EXPECTED_PAIRS = {
    ("the", "cat"): 2,
    ("cat", "sat"): 1,
    ("sat", "on"): 1,
    ("on", "the"): 1,
    ("the", "mat"): 1,
    ("mat", "the"): 1,
    ("cat", "ran"): 1,
}


def test_tokenize_splits_into_lowercased_punctuation_stripped_words():
    assert tokenize(SAMPLE) == EXPECTED_TOKENS


def test_word_frequencies_counts_each_word():
    assert word_frequencies(tokenize(SAMPLE)) == EXPECTED_FREQUENCIES


def test_neighbor_pairs_counts_each_adjacent_pair():
    assert neighbor_pairs(tokenize(SAMPLE)) == EXPECTED_PAIRS


def test_combined_report_presents_both_findings_together():
    report = combined_report(SAMPLE)
    assert isinstance(report, str) and report.strip(), "combined_report must return a non-empty string"
    normalized = re.sub(r"[^a-z0-9]+", " ", report.lower())
    # The neighbouring-pair finding: the top pair "the cat" (count 2) survives normalisation of
    # any reasonable rendering ("the cat", "('the', 'cat')", "the -> cat: 2"). A frequency-only
    # report never contains the two words adjacent, so this discriminates the JOIN.
    assert "the cat" in normalized, "combined report is missing the neighbouring-pair findings"
    # The word-frequency finding: only the frequency view carries the count 3 (the=3) — the
    # neighbouring pairs top out at 2 — so a "3" in the report proves the frequencies are present.
    assert "3" in report, "combined report is missing the word-frequency findings"
