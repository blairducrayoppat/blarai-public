"""Card-driven plan overrides for the M2 capability battery (#752 F1/F2).

WHY THIS EXISTS. A battery card (``evals/battery/B*.json``) can DECLARE the plan shape it is
built to exercise — e.g. B2 declares a 4-unit ``diamond`` (tokenize -> {word-freq, n-grams} ->
report). But the live dispatch decomposes the card's natural-language goal with the 14B, whose
right-sizing ruler UNDER-decomposes a coherent-sounding goal to a single task (correct for a
genuinely simple app — false-splitting a real app is worse than a missed split — but wrong for
a carded pipeline). ``swap_ops.build_job_plan`` then declines the <2-task plan and degrades to
the flat queue, so B2 never runs as its diamond (the live failure, 2026-07-06).

THE SEAM (Vikunja #752 F1/F2, "Seam 2"). Rather than change the general 14B decomposer — which
would risk false-splits on genuinely-simple real fleet jobs — the CARD's declared shape
AUTHORIZES a pre-built decomposition + job oracle for BATTERY jobs ONLY. The AO's PLAN handler
consults :func:`resolve_plan_override` with the dispatched repo; for a sandbox ``battery-*`` repo
whose card declares a carded shape (``"diamond"``, ``"chain"``, or ``"mixed"``) with
``units >= 2`` it returns a
generic :class:`~shared.fleet.acceptance.DecompositionOverride` that ``generate_plan`` uses in
place of the 14B decompose + job-oracle generation. Every NON-battery repo returns ``None``
IMMEDIATELY (a name that does not start with ``battery-`` never even reads a card), so production
plan generation is byte-identical to today.

ALL battery coupling lives HERE. ``acceptance.generate_plan`` only gained a GENERIC
``decomposition_override`` param (it knows nothing of cards); the AO only DECIDES to call this
resolver and passes the result through. This module reads the battery card JSON directly (it
never imports ``tools.dispatch_harness`` — runtime code must not depend on the harness).

THE ``app`` PACKAGE CONVENTION. The plan arms live under the ``app`` package
(``app/tokenize.py``, ``app/storage.py``, ...) and the F2 job oracle imports from those exact
modules. This MUST match the sibling #752 F3 fix (per-task oracles pinned to ``app``); the two
are reconciled at merge. The task SLUG namespace is kebab-case (``word-frequencies``); the
importable MODULE namespace is underscore (``app.word_frequencies``) — deliberately distinct,
and both are asserted by tests.

WHY B1 NEEDS AN OVERRIDE (2026-07-13). B1 is a 3-task Python CLI chain. The 14B planner
consistently generates tasks without ``creates``/``exports`` contracts for this goal (the expense
tracker names are ambiguous — is storage in ``main.py``? ``expense_tracker.py``? ``app/core.py``?
— so the planner follows the «use empty values when unsure» instruction and the oracle-generation
gate skips the oracle). 14 consecutive nights: oracle_status=not-run, verdict PARKED-HONEST
[BUILD] (task failed) or STALLED [VERIFY] (all merged but oracle absent). The fix is the same
pattern as B2: a card-authorised explicit plan with known module paths so the oracle can import
deterministically. The chain is storage→add→list; the oracle tests only ``app.storage`` (the
stable public interface the other two tasks build on).

WHY B4 NEEDS AN OVERRIDE (2026-07-21, #1008). B4 is a 5-task Python CLI mixed graph. The 14B's
plan-time JOB-oracle generation is deterministically broken for this goal: the generated oracle
called ``data_storage.load_cards()``/``save_cards()`` without ever importing ``data_storage``
(NameError at grade time — "3 failed, 3 passed" for seven consecutive nights, byte-identical
through run 20260719-233631-bd and 20260720-235311-bd, the grader's own crash charged to the
coder), and the import contract the build tasks saw omitted that same wave-1 module, so no task
was ever told to own it (oracle import-contract coverage is the #989 c.2299 predictor of clean
wave distribution). The #965 oracle-QA layer cannot police this class: on the seventh night it
ran two regeneration rounds and re-emitted the broken exam unchanged, and its import-contract
checker scored the missing import clean (it validates imports-within-declared, never
used-but-never-bound). A deterministic oracle needs a deterministic import surface, and only an
authored plan pins the module layout the oracle imports — so B4 gets the same card-authorised
pattern as B1/B2: each build task owns exactly one ``app`` module and the job oracle imports
exactly those modules (a 1:1 import contract, ``data_storage`` included).
"""

from __future__ import annotations

import ast
import json
import logging
from pathlib import Path

from shared.fleet.acceptance import JOB_ORACLE_PATH_PYTHON, DecompositionOverride

logger = logging.getLogger(__name__)

# shared/fleet/battery_plans.py -> parents[2] == the blarai repo root (mirrors battery.py's
# _REPO_ROOT so the AO, which boots from the checkout, finds the committed cards on disk).
_REPO_ROOT = Path(__file__).resolve().parents[2]
_BATTERY_SPEC_DIR = _REPO_ROOT / "evals" / "battery"

#: Only a sandbox repo can carry a battery card (mirrors battery.py's S5 ``battery-<slug>`` pin).
#: The fast-path guard: a repo whose basename lacks this prefix is a production/operator repo and
#: never reads a card, so ``resolve_plan_override`` is a zero-I/O ``None`` for every real dispatch.
_SANDBOX_REPO_PREFIX = "battery-"


def build_text_stats_diamond(repo_target: str) -> list[dict]:
    """The B2 text-stats 4-arm DIAMOND decomposition (#752 F1).

    ``tokenize`` -> {``word-frequencies``, ``neighbor-pairs``} -> ``report`` — 4 dependency
    edges, 3 waves. Each arm is a decompose-shaped ``{repo, task, prompt, depends_on, contract}``
    dict; ``repo_target`` is the ABSOLUTE repo path (``projects_dir / <slug>`` — the same value
    ``decompose_request`` stamps) so the downstream ``validate_repo`` containment passes.

    Every arm's implementation lives under the ``app`` package (``app.tokenize`` etc.); the F2
    job oracle imports those exact modules, and the sibling F3 per-task oracles pin the same.
    """
    return [
        {
            "repo": repo_target,
            "task": "tokenize",
            "prompt": (
                "Build the tokenizer for a text-statistics toolkit in this repo: a Python module "
                "app/tokenize.py exporting tokenize(text) that breaks a piece of text into "
                "individual words — each lowercased with surrounding punctuation stripped — and "
                "returns them as a list in reading order. Make app/ an importable package (add "
                "app/__init__.py). Include pytest unit tests."
            ),
            "depends_on": [],
            "contract": {
                "creates": ["app/__init__.py", "app/tokenize.py"],
                "exports": ["tokenize(text)"],
                "notes": (
                    "tokenize(text) -> list[str]: lowercased, surrounding-punctuation-stripped "
                    "words in reading order; the shared input both count arms consume."
                ),
            },
        },
        {
            "repo": repo_target,
            "task": "word-frequencies",
            "prompt": (
                "Build the word-frequency count for the text-statistics toolkit: a Python module "
                "app/word_frequencies.py exporting word_frequencies(tokens) that takes the token "
                "list produced by app.tokenize.tokenize and returns a dict mapping each word to "
                "how many times it appears. Import the tokenizer from app.tokenize — never "
                "reimplement it. An empty token list returns {}. Include pytest unit tests."
            ),
            "depends_on": ["tokenize"],
            "contract": {
                "creates": ["app/word_frequencies.py"],
                "exports": ["word_frequencies(tokens)"],
                "notes": (
                    "word_frequencies(tokens) -> dict[str, int] over the app.tokenize output; "
                    "{} for an empty list."
                ),
            },
        },
        {
            "repo": repo_target,
            "task": "neighbor-pairs",
            "prompt": (
                "Build the neighbouring-word-pair count for the text-statistics toolkit: a Python "
                "module app/neighbor_pairs.py exporting neighbor_pairs(tokens) that takes the "
                "token list produced by app.tokenize.tokenize and returns a dict mapping each "
                "adjacent (word, next_word) tuple to how many times that ordered pair occurs. "
                "Import the tokenizer from app.tokenize — never reimplement it. Fewer than two "
                "tokens returns {}. Include pytest unit tests."
            ),
            "depends_on": ["tokenize"],
            "contract": {
                "creates": ["app/neighbor_pairs.py"],
                "exports": ["neighbor_pairs(tokens)"],
                "notes": (
                    "neighbor_pairs(tokens) -> dict[tuple[str, str], int] over adjacent tokens; "
                    "{} for fewer than two tokens."
                ),
            },
        },
        {
            "repo": repo_target,
            "task": "report",
            "prompt": (
                "Build the combined report for the text-statistics toolkit — the fan-in that "
                "pulls both counts together: a Python module app/report.py exporting "
                "combined_report(text) that tokenizes the text (app.tokenize.tokenize), computes "
                "BOTH the word frequencies (app.word_frequencies.word_frequencies) and the "
                "neighbouring-word-pair counts (app.neighbor_pairs.neighbor_pairs), and returns a "
                "single human-readable report string that presents both findings together in one "
                "place. Import all three modules — never reimplement them. Include pytest unit "
                "tests."
            ),
            "depends_on": ["word-frequencies", "neighbor-pairs"],
            "contract": {
                "creates": ["app/report.py"],
                "exports": ["combined_report(text)"],
                "notes": (
                    "Fan-in join: imports app.tokenize, app.word_frequencies, app.neighbor_pairs; "
                    "combined_report(text) -> str containing BOTH the frequency and the "
                    "neighbour-pair findings."
                ),
            },
        },
    ]


#: The B2 JOB-level acceptance oracle (#752 F2) — graded ONCE on the final integrated tree after
#: all four arms merge (``swap_ops.real_run_job_oracle`` runs it as ``python -m pytest`` with
#: cwd=repo, which puts the repo root on ``sys.path`` so ``from app.tokenize import ...`` resolves
#: against the built ``app`` package). It imports each arm's public interface and grades the JOIN
#: on a known sample. Authored here (not model-written) because the card AUTHORIZES the shape.
_TEXT_STATS_JOB_ORACLE_PY = '''\
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
'''


def build_expense_tracker_chain(repo_target: str) -> list[dict]:
    """The B1 expense-tracker 3-arm CHAIN decomposition.

    ``store-expenses`` -> ``add-expense`` -> ``list-expenses`` — 2 dependency
    edges, 2 waves. All arms live under the ``app`` package so the job oracle can
    import from known paths (``app.storage``) without guessing. Module name is
    underscore (``app.storage``); task slug is kebab-case (``store-expenses``).

    The explicit contracts are the key fix: the 14B planner consistently leaves
    contracts empty for this goal (ambiguous file naming) which prevents oracle
    generation. The override pins the module layout so the oracle is always generated
    and the job-acceptance gate always runs.
    """
    return [
        {
            "repo": repo_target,
            "task": "store-expenses",
            "prompt": (
                "Build the persistence layer for an expense-tracker command-line tool in this "
                "repo: a Python module app/storage.py that stores and retrieves expense records. "
                "Make app/ an importable package (add app/__init__.py). "
                "The module must export two functions: "
                "(1) save_expense(amount, category, date) — appends a new expense dict with keys "
                "'amount' (float), 'category' (str), and 'date' (str, ISO format YYYY-MM-DD) to "
                "the persistent store (a JSON file named expenses.json in the working directory); "
                "(2) load_expenses() -> list[dict] — reads all saved expenses from expenses.json "
                "and returns them as a list ordered newest-first (by 'date' descending; equal "
                "dates preserve insertion order). Return [] when the file is absent or empty. "
                "Include pytest unit tests in tests/test_storage.py."
            ),
            "depends_on": [],
            "contract": {
                "creates": ["app/__init__.py", "app/storage.py"],
                "exports": [
                    "save_expense(amount, category, date)",
                    "load_expenses() -> list[dict]",
                ],
                "notes": (
                    "expenses.json: list of {amount: float, category: str, date: str}. "
                    "load_expenses() returns newest-first by date."
                ),
            },
        },
        {
            "repo": repo_target,
            "task": "add-expense",
            "prompt": (
                "Build the expense-input command for the expense-tracker CLI: a Python module "
                "app/expense_input.py that handles user input for adding a new expense. "
                "Import save_expense from app.storage — never reimplement storage logic. "
                "The module must export add_expense(amount, category, date) which validates the "
                "inputs (amount must be a positive number; category and date must be non-empty "
                "strings) and calls save_expense to persist the record. Raise ValueError with a "
                "clear message for invalid inputs. "
                "Also add an 'add' subcommand to the CLI entry point cli.py (create it if absent) "
                "so the user can run: python cli.py add <amount> <category> <date>. "
                "Include pytest unit tests in tests/test_expense_input.py."
            ),
            "depends_on": ["store-expenses"],
            "contract": {
                "creates": ["app/expense_input.py", "cli.py"],
                "exports": ["add_expense(amount, category, date)"],
                "notes": (
                    "add_expense validates then delegates to app.storage.save_expense. "
                    "cli.py adds an 'add' subcommand."
                ),
            },
        },
        {
            "repo": repo_target,
            "task": "list-expenses",
            "prompt": (
                "Build the expense-listing command for the expense-tracker CLI: extend cli.py "
                "(created by the add-expense task) with a 'list' subcommand so the user can run: "
                "python cli.py list — which prints all saved expenses newest-first, one per line, "
                "in a readable format that shows the date, category, and amount. "
                "Import load_expenses from app.storage — never reimplement storage logic. "
                "The output must show at minimum the amount, category, and date of each expense. "
                "Include pytest unit tests in tests/test_expense_list.py."
            ),
            "depends_on": ["add-expense"],
            "contract": {
                "creates": [],
                "exports": [],
                "notes": (
                    "Extends cli.py with a 'list' subcommand that calls app.storage.load_expenses "
                    "and prints each expense newest-first."
                ),
            },
        },
    ]


#: The B1 JOB-level acceptance oracle — graded once on the final integrated tree after all
#: three arms merge. Tests only ``app.storage`` (the stable public interface); the add and
#: list commands build on it so a correct storage layer is necessary + largely sufficient.
#: Authored here (not model-written) because the card authorises the chain shape. The oracle
#: does NOT test interactive CLI behaviour (that is eyeball-tier per the card).
_EXPENSE_TRACKER_JOB_ORACLE_PY = '''\
"""Job-level acceptance oracle for B1 expense-tracker chain.

Graded once on the final integrated tree after all three arms merge. Tests
app.storage (the public persistence interface the add/list commands build on).
"""
import os


def _clear() -> None:
    """Remove persisted state before each test."""
    for name in ("expenses.json",):
        if os.path.exists(name):
            os.remove(name)


from app.storage import save_expense, load_expenses


def test_expense_persists_after_save() -> None:
    """The program must save expenses to a file so they persist after closing."""
    _clear()
    save_expense(12.50, "groceries", "2024-01-15")
    loaded = load_expenses()
    assert len(loaded) >= 1, "load_expenses must return the saved expense"
    amounts = [
        float(e.get("amount", e.get("cost", e.get("price", 0)))) for e in loaded
    ]
    assert any(abs(a - 12.50) < 0.01 for a in amounts), (
        f"Saved amount 12.50 not found in loaded expenses: {loaded}"
    )


def test_expense_stores_category_and_date() -> None:
    """Must allow adding an expense with amount, category, and date."""
    _clear()
    save_expense(5.99, "coffee", "2024-01-20")
    loaded = load_expenses()
    assert len(loaded) >= 1, "load_expenses must return the saved expense"
    e = loaded[0]
    # Accept any reasonable key name for category.
    cat = str(
        e.get("category") or e.get("type") or e.get("kind") or e.get("label") or ""
    ).lower()
    assert "coffee" in cat, f"Category 'coffee' not stored; expense dict: {e}"
    # Accept any reasonable key name for date.
    date_val = (
        e.get("date") or e.get("day") or e.get("when") or e.get("timestamp") or ""
    )
    assert date_val, f"Date not stored in expense; expense dict: {e}"


def test_list_expenses_newest_first() -> None:
    """Must display all expenses with newest first."""
    _clear()
    save_expense(10.00, "groceries", "2024-01-10")
    save_expense(20.00, "fuel",      "2024-01-15")
    save_expense(5.00,  "coffee",    "2024-01-12")
    loaded = load_expenses()
    assert len(loaded) >= 3, f"Expected >=3 expenses, got {len(loaded)}: {loaded}"
    # Extract dates and verify descending order.
    dates = []
    for e in loaded:
        d = str(
            e.get("date") or e.get("day") or e.get("when") or e.get("timestamp") or ""
        )
        if d:
            dates.append(d)
    if len(dates) >= 2:
        assert dates == sorted(dates, reverse=True), (
            f"Expenses must be listed newest-first; got date order: {dates}"
        )
'''


def build_flashcards_mixed(repo_target: str) -> list[dict]:
    """The B4 flashcards-study 5-arm MIXED decomposition (#1008).

    ``store-cards`` -> {``import-deck``, ``add-card``} -> ``quiz`` -> ``track-scores`` — 5
    dependency edges, 4 waves (the card's ``min_dependency_edges: 4`` / ``expects_waves_gte: 3``
    with margin). Storage feeds both card-entry commands; those two are PARALLEL siblings, so
    each owns ONLY its own module (two wave-2 worktrees must never collide on a shared file);
    the quiz fans IN from both entry doors (cards exist through either); the score tracker
    follows the quiz. The CLI face (``cli.py``) is created by the LAST arm, when every module
    it wires already exists.

    Every arm owns exactly ONE ``app`` module and the job oracle imports exactly those five —
    the 1:1 import contract that B4's model-generated plan lacked (#1008: the oracle called
    ``data_storage`` without importing it, and the contract never named it). Every
    state-bearing function takes an explicit optional path (``path``/``data_path``/
    ``scores_path``) so the oracle can grade against temp stores, and the quiz consumes a
    dependency-injected ``answer_fn`` so nothing reads interactive stdin under pytest.
    """
    return [
        {
            "repo": repo_target,
            "task": "store-cards",
            "prompt": (
                "Build the persistence layer for a flashcard study program in this repo: a "
                "Python module app/data_storage.py that keeps the cards saved between "
                "sessions. Make app/ an importable package (add app/__init__.py). The module "
                "must export two functions: (1) save_cards(cards, path=None) — writes the "
                "full list of card dicts (each {'question': str, 'answer': str}) to a JSON "
                "file; the file is cards.json in the working directory unless a non-None path "
                "names another file; (2) load_cards(path=None) -> list[dict] — reads the "
                "saved cards back from the same file and returns them in saved order; return "
                "[] when the file is absent or empty. Include pytest unit tests in "
                "tests/test_data_storage.py."
            ),
            "depends_on": [],
            "contract": {
                "creates": ["app/__init__.py", "app/data_storage.py"],
                "exports": [
                    "save_cards(cards, path=None)",
                    "load_cards(path=None) -> list[dict]",
                ],
                "notes": (
                    "cards.json (or the explicit path): a JSON list of "
                    "{question: str, answer: str}. load_cards() returns saved order; "
                    "[] when the file is absent or empty."
                ),
            },
        },
        {
            "repo": repo_target,
            "task": "import-deck",
            "prompt": (
                "Build the deck-import command for the flashcard study program: a Python "
                "module app/deck_import.py exporting import_deck(file_path, data_path=None) "
                "-> int that brings in a whole deck of cards at once from a plain-text file. "
                "Each non-empty line of the file is one card written as question|answer — "
                "split on the FIRST '|', strip surrounding whitespace from both parts, and "
                "skip lines with no '|'. Append the imported cards to the already-saved cards "
                "using load_cards/save_cards from app.data_storage — never reimplement "
                "storage — passing data_path through, and return how many cards were "
                "imported. Include pytest unit tests in tests/test_deck_import.py."
            ),
            "depends_on": ["store-cards"],
            "contract": {
                "creates": ["app/deck_import.py"],
                "exports": ["import_deck(file_path, data_path=None) -> int"],
                "notes": (
                    "One card per non-empty 'question|answer' line (first '|' splits; both "
                    "parts stripped; no-'|' lines skipped). Appends via app.data_storage and "
                    "returns the count imported."
                ),
            },
        },
        {
            "repo": repo_target,
            "task": "add-card",
            "prompt": (
                "Build the single-card entry command for the flashcard study program: a "
                "Python module app/card_entry.py exporting "
                "add_card(question, answer, data_path=None) that validates the inputs "
                "(question and answer must be non-empty strings — raise ValueError with a "
                "clear message otherwise) and appends {'question': question, 'answer': "
                "answer} to the saved cards using load_cards/save_cards from "
                "app.data_storage — never reimplement storage — passing data_path through. "
                "Include pytest unit tests in tests/test_card_entry.py."
            ),
            "depends_on": ["store-cards"],
            "contract": {
                "creates": ["app/card_entry.py"],
                "exports": ["add_card(question, answer, data_path=None)"],
                "notes": (
                    "Validates non-empty strings (ValueError otherwise), then appends the "
                    "card via app.data_storage."
                ),
            },
        },
        {
            "repo": repo_target,
            "task": "quiz",
            "prompt": (
                "Build the quiz engine for the flashcard study program: a Python module "
                "app/quiz_engine.py exporting run_quiz(answer_fn, data_path=None) -> dict "
                "that loads the saved cards via app.data_storage.load_cards (passing "
                "data_path through — never reimplement storage), asks each card by calling "
                "answer_fn(question) to obtain the user's answer, and checks it against the "
                "card's stored answer — a match ignores letter case and surrounding "
                "whitespace. Return {'asked': <number of cards asked>, 'correct': <number "
                "answered correctly>}. answer_fn is dependency-injected: the CLI passes "
                "input, tests pass a stub — never call input() inside this module. Include "
                "pytest unit tests in tests/test_quiz_engine.py."
            ),
            "depends_on": ["import-deck", "add-card"],
            "contract": {
                "creates": ["app/quiz_engine.py"],
                "exports": ["run_quiz(answer_fn, data_path=None) -> dict"],
                "notes": (
                    "Loads cards via app.data_storage; answer_fn(question) supplies each "
                    "answer (dependency-injected — no stdin); a match ignores case and "
                    "surrounding whitespace; returns {'asked': int, 'correct': int}."
                ),
            },
        },
        {
            "repo": repo_target,
            "task": "track-scores",
            "prompt": (
                "Build the score tracking and the command-line face for the flashcard study "
                "program. (1) A Python module app/score_tracker.py exporting "
                "record_score(correct, asked, scores_path=None) — appends {'correct': "
                "correct, 'asked': asked} to a JSON scores file (scores.json in the working "
                "directory unless a non-None scores_path names another file) — and "
                "load_scores(scores_path=None) -> list[dict] — returns every recorded score "
                "oldest-first so progress over time is visible; return [] when the file is "
                "absent or empty. (2) The CLI entry point cli.py wiring the whole program: "
                "python cli.py import <file> calls app.deck_import.import_deck; python "
                "cli.py add <question> <answer> calls app.card_entry.add_card; python cli.py "
                "quiz runs app.quiz_engine.run_quiz with the built-in input as answer_fn, "
                "prints the result, and records it via record_score; python cli.py scores "
                "prints each recorded score in order. Import everything from the app package "
                "— never reimplement it. Include pytest unit tests in "
                "tests/test_score_tracker.py (test the module functions; the interactive "
                "quiz command itself is not unit-tested)."
            ),
            "depends_on": ["quiz"],
            "contract": {
                "creates": ["app/score_tracker.py", "cli.py"],
                "exports": [
                    "record_score(correct, asked, scores_path=None)",
                    "load_scores(scores_path=None) -> list[dict]",
                ],
                "notes": (
                    "scores.json (or the explicit scores_path): a JSON list of "
                    "{correct: int, asked: int}, oldest-first. cli.py wires the "
                    "import/add/quiz/scores subcommands over the app package."
                ),
            },
        },
    ]


#: The B4 JOB-level acceptance oracle (#1008) — graded once on the final integrated tree after
#: all five arms merge. It imports EVERY module it calls (the defect this replaces: the
#: 14B-generated oracle called ``data_storage.load_cards()`` without importing ``data_storage``
#: — NameError at grade time, seven consecutive nights, the grader's own crash charged to the
#: coder). All state lives under pytest's ``tmp_path`` (never a repo-shared JSON store) and the
#: quiz consumes an injected ``answer_fn`` (pytest's captured stdin kills naive ``input()``
#: tests). Authored here (not model-written) because the card authorises the mixed shape.
_FLASHCARDS_JOB_ORACLE_PY = '''\
"""Job-level acceptance oracle for the B4 flashcards mixed graph (#1008).

Graded once on the final integrated tree after all five arms merge. Imports each arm's
public interface from the ``app`` package (the 1:1 import contract: every module this file
calls is imported, and each is created by exactly one build task) and asserts the
integrated study flow — persist -> import/add -> quiz -> score. All state lives under
pytest's ``tmp_path``; the quiz consumes an injected answer function, never stdin.
"""
import pytest

from app.data_storage import save_cards, load_cards
from app.deck_import import import_deck
from app.card_entry import add_card
from app.quiz_engine import run_quiz
from app.score_tracker import record_score, load_scores


def test_cards_persist_between_sessions(tmp_path):
    """Saved cards must still be there when loaded back (the between-sessions promise)."""
    data = str(tmp_path / "cards.json")
    save_cards([{"question": "What is 2+2?", "answer": "4"}], path=data)
    loaded = load_cards(path=data)
    assert len(loaded) == 1
    assert loaded[0]["question"] == "What is 2+2?"
    assert loaded[0]["answer"] == "4"


def test_load_cards_empty_store_is_empty_list(tmp_path):
    assert load_cards(path=str(tmp_path / "missing.json")) == []


def test_import_deck_brings_in_a_whole_file(tmp_path):
    deck = tmp_path / "deck.txt"
    deck.write_text("Q1|A1\\nQ2|A2\\n", encoding="utf-8")
    data = str(tmp_path / "cards.json")
    imported = import_deck(str(deck), data_path=data)
    assert imported == 2
    questions = [c["question"] for c in load_cards(path=data)]
    assert "Q1" in questions and "Q2" in questions


def test_add_card_appends_to_the_saved_cards(tmp_path):
    data = str(tmp_path / "cards.json")
    add_card("Capital of France?", "Paris", data_path=data)
    loaded = load_cards(path=data)
    assert len(loaded) == 1
    assert loaded[0]["question"] == "Capital of France?"
    assert loaded[0]["answer"] == "Paris"


def test_add_card_rejects_empty_input(tmp_path):
    data = str(tmp_path / "cards.json")
    with pytest.raises(ValueError):
        add_card("", "Paris", data_path=data)
    with pytest.raises(ValueError):
        add_card("Capital of France?", "", data_path=data)


def test_quiz_checks_answers_and_counts_correct(tmp_path):
    data = str(tmp_path / "cards.json")
    save_cards(
        [
            {"question": "What is 2+2?", "answer": "4"},
            {"question": "Capital of France?", "answer": "Paris"},
        ],
        path=data,
    )
    answers = {"What is 2+2?": "4", "Capital of France?": "London"}
    result = run_quiz(lambda question: answers[question], data_path=data)
    assert result["asked"] == 2
    assert result["correct"] == 1


def test_quiz_match_ignores_case_and_surrounding_whitespace(tmp_path):
    data = str(tmp_path / "cards.json")
    save_cards([{"question": "Capital of France?", "answer": "Paris"}], path=data)
    result = run_quiz(lambda question: "  paris ", data_path=data)
    assert result["correct"] == 1


def test_scores_kept_over_time_in_order(tmp_path):
    """Recorded scores accumulate oldest-first so progress over time is visible."""
    scores = str(tmp_path / "scores.json")
    record_score(1, 3, scores_path=scores)
    record_score(3, 3, scores_path=scores)
    loaded = load_scores(scores_path=scores)
    assert len(loaded) == 2
    assert [s["correct"] for s in loaded] == [1, 3]
    assert [s["asked"] for s in loaded] == [3, 3]
'''


#: Registry of carded plan builders, keyed by card id. A card WITHOUT a registered builder
#: resolves to ``None`` (fail-closed — never inject a shape we cannot author). Adding support
#: for a new card is a one-line addition here plus its own builder + oracle constant.
#: Covers diamond (B2), chain (B1), and mixed (B4) shapes; see :func:`resolve_plan_override`
#: for the accepted shape list.
_PLAN_BUILDERS = {
    "B1": (build_expense_tracker_chain, _EXPENSE_TRACKER_JOB_ORACLE_PY),
    "B2": (build_text_stats_diamond, _TEXT_STATS_JOB_ORACLE_PY),
    "B4": (build_flashcards_mixed, _FLASHCARDS_JOB_ORACLE_PY),
}

# Back-compat alias so tests / any import that still references _DIAMOND_BUILDERS keeps working.
_DIAMOND_BUILDERS = _PLAN_BUILDERS


def _load_cards(spec_dir: Path) -> list[dict]:
    """Every readable ``B*.json`` card under *spec_dir* as a raw dict (fail-soft: an unreadable
    or non-object file is skipped, never raised — a battery-spec problem must not sink a live
    plan request). Deliberately minimal: no schema validation (that is battery.py's job); this
    resolver only reads the three fields it gates on."""
    cards: list[dict] = []
    try:
        paths = sorted(spec_dir.glob("B*.json"))
    except OSError:
        return cards
    for path in paths:
        try:
            card = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(card, dict):
            cards.append(card)
    return cards


def _card_for_repo(repo: str, cards: list[dict]) -> "dict | None":
    """The card whose ``repo`` matches *repo* (the dispatched slug or a path ending in it), or
    ``None``. Tolerates both the bare slug (what the battery dispatches) and an absolute path."""
    name = Path(str(repo)).name
    for card in cards:
        card_repo = str(card.get("repo", ""))
        if card_repo and (card_repo == str(repo) or card_repo == name):
            return card
    return None


def resolve_plan_override(
    repo: str, *, projects_dir: "str | Path", spec_dir: "str | Path | None" = None
) -> "DecompositionOverride | None":
    """Return the card-authorised :class:`DecompositionOverride` for *repo*, or ``None``.

    Fires ONLY for a sandbox ``battery-*`` repo whose card declares a carded shape
    (``"diamond"``, ``"chain"``, or ``"mixed"``) with ``units >= 2`` AND has a registered arm
    builder
    (:data:`_PLAN_BUILDERS`). Every other repo — every production/operator dispatch — returns
    ``None``, and a name that does not start with ``battery-`` returns immediately WITHOUT reading
    any card (production plan generation is byte-identical + zero-cost). Wholly fail-soft: any
    error resolves to ``None`` (never inject a half-built override, never crash a plan request).

    ``projects_dir`` is the fleet projects root (the arms carry ``projects_dir / <slug>`` as their
    absolute repo, mirroring :func:`~shared.fleet.decompose.decompose_request`). ``spec_dir``
    overrides the battery card directory (tests)."""
    # Carded shapes that this resolver handles. A card with shape NOT in this set falls
    # through to the live 14B decompose path (the normal behaviour for "flat", "linear", etc.).
    _HANDLED_SHAPES = frozenset({"diamond", "chain", "mixed"})
    try:
        name = Path(str(repo)).name
        if not name.startswith(_SANDBOX_REPO_PREFIX):
            return None  # fast path: production repos never carry a battery card
        cards = _load_cards(Path(spec_dir) if spec_dir is not None else _BATTERY_SPEC_DIR)
        card = _card_for_repo(repo, cards)
        if card is None:
            return None
        shape = str(card.get("shape", "")).strip().lower()
        units = card.get("units")
        if shape not in _HANDLED_SHAPES or not isinstance(units, int) or units < 2:
            return None
        entry = _PLAN_BUILDERS.get(str(card.get("id", "")))
        if entry is None:
            logger.warning(
                "battery_plans: card %s declares shape=%s but no arm builder is registered "
                "— NOT overriding the decomposition (add one to _PLAN_BUILDERS).",
                card.get("id"), shape,
            )
            return None
        builder, oracle_code = entry
        card_repo = str(card.get("repo", "")) or name
        repo_target = str(Path(projects_dir) / card_repo)
        tasks = builder(repo_target)
        if len(tasks) < 2:
            return None  # a 1-task plan is not a multi-task plan — let the normal path run
        # Defence-in-depth: a malformed committed oracle must fail CLOSED to "no job oracle"
        # (the driver then records job-acceptance not-run — honest), never ride as junk.
        try:
            ast.parse(oracle_code)
        except (SyntaxError, ValueError):
            logger.error("battery_plans: card %s job oracle failed to parse — dropping it.",
                         card.get("id"))
            oracle_code = ""
        override = DecompositionOverride(
            tasks=tasks,
            job_oracle_code=oracle_code,
            job_oracle_path=JOB_ORACLE_PATH_PYTHON if oracle_code else "",
        )
        logger.info(
            "battery_plans: card %s (%s) authorises a %d-arm %s override for repo %r.",
            card.get("id"), shape, len(tasks), shape, repo,
        )
        return override
    except Exception as exc:  # noqa: BLE001 — a resolver failure must never sink a plan request
        logger.warning("battery_plans: override resolution failed (fail-soft -> None): %s", exc)
        return None
