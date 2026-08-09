"""#746 — the coder-facing doc-lookup CLI (``tools/search_docs.py``) at its seam.

The consumer is a Node wrapper that runs

    <python> tools/search_docs.py --json -k <k> "<query>"

and does ``JSON.parse(stdout.trim())``. So the tests that matter are the ones
that drive THAT command line for real (``_run_cli``) and the ones that drive
the REAL retrieval ladder against a REAL built index. Nothing here mocks
``exact_lookup``/``search_docs``/``load_index`` to make an assertion pass —
where retrieval behaviour is asserted, a genuine SQLite index built from a
genuine (small) corpus is behind it, because a mock of this ladder would agree
with whatever shape the test expected and prove nothing.

Two rigs, both real:

  * ``fixture_index`` — the mini corpus from ``shared/tests/
    test_research_substrate.py`` (reused, not re-implemented), built through
    ``docset_index.build_index`` into ``tmp_path``. Retrieval assertions run
    against this in-process, with the module's default index/corpus dirs
    redirected at it, so the CLI's own ``load_index()`` call is exercised.
  * ``_run_cli`` — a real subprocess on the real argument vector, for the
    contract properties the wrapper actually depends on (stdout is one JSON
    object, exit status, determinism, flag handling). These need no corpus and
    so run everywhere.

The single end-to-end test against the REAL staged corpus is skipped when the
gitignored ``models/docsets/`` is absent — the same documented, bounded
environment delta the research substrate's own real-corpus test carries.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from shared.research import docset_index as di
from shared.research import lookup as lk

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CLI_PATH = _REPO_ROOT / "tools" / "search_docs.py"
_REAL_CORPUS = _REPO_ROOT / "models" / "docsets"
_SUBSTRATE_TESTS = _REPO_ROOT / "shared" / "tests" / "test_research_substrate.py"


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cli = _load_module("blarai_search_docs_cli", _CLI_PATH)


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Never touch the operator's real research-usage log, and never inherit an
    ambient ``BLARAI_RESEARCH_DOCS`` — the dormancy tests depend on the flag's
    value being exactly what the test set."""
    monkeypatch.setenv("BLARAI_RESEARCH_USAGE_LOG", str(tmp_path / "usage.jsonl"))
    monkeypatch.delenv("BLARAI_RESEARCH_DOCS", raising=False)


@pytest.fixture(scope="module")
def fixture_index(tmp_path_factory: pytest.TempPathFactory):
    """A REAL index over the shared mini corpus (module-scoped, read-only)."""
    substrate = _load_module("blarai_research_substrate_tests", _SUBSTRATE_TESTS)
    root = tmp_path_factory.mktemp("search_docs_cli")
    corpus = substrate._stage_mini_corpus(root)
    index_dir = root / "index"
    di.build_index(corpus_dir=corpus, index_dir=index_dir)
    yield corpus, index_dir
    lk.reset_default_index()


@pytest.fixture
def live(fixture_index, monkeypatch: pytest.MonkeyPatch):
    """Capability ON, defaults pointed at the fixture index — so the CLI's own
    ``load_index()`` (no arguments, exactly as in production) finds it."""
    corpus, index_dir = fixture_index
    monkeypatch.setenv("BLARAI_RESEARCH_DOCS", "1")
    monkeypatch.setattr(di, "DEFAULT_CORPUS_DIR", corpus)
    monkeypatch.setattr(di, "DEFAULT_INDEX_DIR", index_dir)
    return corpus, index_dir


def _run_cli(
    args: list[str], env_overrides: dict[str, str] | None = None, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    """Drive the REAL command line in a real subprocess."""
    env = dict(os.environ)
    env.pop("BLARAI_RESEARCH_DOCS", None)
    env["BLARAI_RESEARCH_USAGE_LOG"] = str(
        Path(env.get("TEMP", ".")) / "blarai-search-docs-cli-test-usage.jsonl"
    )
    env.update(env_overrides or {})
    return subprocess.run(
        [sys.executable, str(_CLI_PATH), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        env=env,
        cwd=str(cwd) if cwd else None,
        check=False,  # the exit STATUS is under test; never raise on it
    )


def _parse_stdout(proc: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    """The wrapper's own move: ``JSON.parse(stdout.trim())``. Failing here is
    exactly the failure that makes the coder's tool report 'tool_error'."""
    text = proc.stdout.strip()
    assert text, f"stdout was EMPTY (stderr={proc.stderr!r})"
    return json.loads(text)


# ---------------------------------------------------------------------------
# The wrapper's contract: stdout is always one parseable JSON object
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("args", "expected_reason"),
    [
        (["--json", "-k", "4", "json.dumps"], "dormant"),
        (["--json", "-k", "abc", "json.dumps"], "bad_usage"),
        (["--json", "-k"], "bad_usage"),
        (["--json", "-k", "4", ""], "dormant"),
        (["--json", "-k", "4"], "dormant"),
        (["--json", "-h"], "usage"),
    ],
)
def test_every_argv_yields_one_json_object_and_exit_zero(
    args: list[str], expected_reason: str
) -> None:
    """No argument vector produces a stack trace, empty stdout or a crash."""
    proc = _run_cli(args)
    assert proc.returncode == 0, f"non-zero exit {proc.returncode}: {proc.stderr!r}"
    result = _parse_stdout(proc)
    assert result["reason"] == expected_reason
    assert result["available"] is False
    assert result["hits_found"] is False
    assert "Traceback" not in proc.stderr


def test_stdout_is_a_single_json_object_not_a_stream() -> None:
    proc = _run_cli(["--json", "-k", "2", "json.dumps"])
    assert proc.stdout.strip().count("\n") == 0
    assert isinstance(_parse_stdout(proc), dict)


def test_result_carries_every_field_the_wrapper_reads() -> None:
    """``render()`` reads available/reason/message/hits_found/exact/search and
    per-hit score/source/title/path/excerpt. A missing key renders as
    ``undefined`` in the model's context."""
    result = _parse_stdout(_run_cli(["--json", "-k", "2", "json.dumps"]))
    assert set(result) == {
        "available", "reason", "message", "hits_found", "exact", "search",
    }
    assert isinstance(result["message"], str) and result["message"]
    assert isinstance(result["exact"], list) and isinstance(result["search"], list)


def test_query_beginning_with_a_dash_is_not_eaten_as_a_flag() -> None:
    """A pasted error line can start with punctuation; the first non-flag token
    starts the query and everything after it is verbatim."""
    query = "--fatal: ValueError raised in json.loads"
    proc = _run_cli(["--json", "-k", "2", query])
    result = _parse_stdout(proc)
    assert result["reason"] == "dormant"  # parsed as a query, not as a flag
    assert proc.returncode == 0


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["--json", "-k", "2", "json.dumps"], "json.dumps"),
        (["--json", "-k", "2", "how", "do", "I", "parse", "iso", "8601"],
         "how do I parse iso 8601"),
        (["--json", "-k", "2", "--weird", "--json", "tail"], "--weird --json tail"),
        (["json.loads", "--json"], "json.loads --json"),
    ],
)
def test_every_token_after_the_first_query_token_is_kept(
    argv: list[str], expected: str
) -> None:
    """The whole query survives parsing, verbatim.

    Asserted on the parsed VALUE, not on a downstream reason code: a parser
    that kept only the first token would still produce a well-formed dormant
    result, so a result-level assertion cannot see this.
    """
    query, _k, _json_mode, _help = cli.parse_argv(argv)
    assert query == expected


def test_bad_usage_message_names_the_problem_and_the_usage() -> None:
    result = _parse_stdout(_run_cli(["--json", "-k", "seven", "x"]))
    assert "-k expects an integer" in result["message"]
    assert "usage: search_docs.py" in result["message"]


def test_human_help_without_json_prints_usage_not_json() -> None:
    proc = _run_cli(["-h"])
    assert proc.returncode == 0
    assert proc.stdout.startswith("usage: search_docs.py")


def test_results_are_json_with_or_without_the_json_flag() -> None:
    """The usage text claims results are always JSON; this is that claim.

    Documentation that describes behaviour the program does not have is the
    same defect class as an untested control, so the sentence and the code are
    pinned to each other here.
    """
    with_flag = _parse_stdout(_run_cli(["--json", "-k", "2", "json.dumps"]))
    without_flag = _parse_stdout(_run_cli(["-k", "2", "json.dumps"]))
    assert with_flag == without_flag
    assert without_flag["reason"] == "dormant"
    assert "results are ALWAYS one" in cli._USAGE


def test_subprocess_output_is_byte_identical_across_runs() -> None:
    """Determinism at the process boundary, asserted on the actual bytes."""
    first = _run_cli(["--json", "-k", "3", "json.dumps"])
    second = _run_cli(["--json", "-k", "3", "json.dumps"])
    assert first.stdout == second.stdout
    assert first.returncode == second.returncode == 0


def test_output_is_pure_ascii_so_console_encoding_cannot_break_it(live) -> None:
    """Real doc pages carry em-dashes and pilcrows; a cp1252 stdout would raise
    on them. ``ensure_ascii`` keeps the payload byte-stable everywhere."""
    payload = json.dumps(cli.build_result("json.dumps", 3), sort_keys=True)
    payload.encode("ascii")  # raises if a raw non-ASCII byte ever slips in


# ---------------------------------------------------------------------------
# The deterministic-first ladder, against a REAL index
# ---------------------------------------------------------------------------


def test_exact_tier_leads_and_is_scored_above_the_search_tier(live) -> None:
    result = cli.build_result("json.dumps", 4)
    assert result["available"] is True and result["hits_found"] is True
    assert result["exact"], "the exact rung found nothing for a known symbol"
    assert result["exact"][0]["score"] == 1.0
    assert result["exact"][0]["path"].startswith("library/json")
    assert all(
        hit["score"] <= result["exact"][0]["score"] for hit in result["search"]
    )


def test_error_line_resolves_through_the_exact_token_rung(live) -> None:
    """The wrapper tells the model to paste an error line whole; the exception
    name inside it must resolve deterministically."""
    result = cli.build_result("json.dumps(obj) raised a ValueError somewhere", 4)
    assert result["hits_found"] is True
    assert result["exact"], "no exact hit from the identifiers in an error line"


def test_relevance_floor_stop_returns_no_hits_and_says_so(live) -> None:
    """Nothing above the floor => empty result set, NOT padded weak matches."""
    result = cli.build_result("qqxjz wvvbnq zzptk frobnicate", 4)
    assert result["available"] is True
    assert result["hits_found"] is False
    assert result["exact"] == [] and result["search"] == []
    # The full phrase, not a prefix: "proceed without it" is the actionable
    # half, and it is what the wrapper's own tool description promises.
    assert result["message"] == "no high-value match — proceed without it."


def test_floor_is_load_bearing_not_incidental(live, monkeypatch) -> None:
    """Toggle: a query that DOES clear the default floor stops returning hits
    when the floor is raised. Without this, the previous test could pass merely
    because the query was junk."""
    query = "pytest fixture scope teardown"
    assert cli.build_result(query, 4)["hits_found"] is True
    monkeypatch.setattr(lk, "RELEVANCE_FLOOR", 1.01)  # nothing can clear > 1.0
    dropped = cli.build_result(query, 4)
    assert dropped["hits_found"] is False
    assert dropped["search"] == []


def test_search_tier_never_repeats_a_page_the_exact_tier_returned(live) -> None:
    result = cli.build_result("json.dumps", 4)
    exact_pages = {(h["source"], h["path"].partition("#")[0]) for h in result["exact"]}
    search_pages = {(h["source"], h["path"]) for h in result["search"]}
    assert not (exact_pages & search_pages)


def test_k_caps_each_tier(live, fixture_index) -> None:
    """The cap, asserted where it can FAIL.

    ``len(hits) <= k`` is vacuously true for a query the corpus barely answers,
    so this first drives the RAW ladder to establish that more than *k* hits
    exist, then asserts the CLI truncated to exactly *k*. The precondition is
    an assertion of its own: if the fixture stops producing multiple exact
    hits, this test goes red rather than quietly proving nothing.
    """
    _corpus, index_dir = fixture_index
    query = "json.dumps and ValueError and json.loads"
    with di.load_index(index_dir=index_dir) as index:
        raw_exact = lk.exact_lookup(query, index=index)
    assert len(raw_exact) >= 2, "precondition lost: fixture no longer multi-hit"

    result = cli.build_result(query, 1)
    assert len(result["exact"]) == 1
    assert len(result["search"]) <= 1


@pytest.mark.parametrize(("raw", "expected"), [("0", 1), ("-5", 1), ("999", 20)])
def test_k_is_clamped_to_a_usable_range(raw: str, expected: int) -> None:
    _query, k, _json_mode, _help = cli.parse_argv(["--json", "-k", raw, "q"])
    assert k == expected


def test_identical_calls_produce_identical_results(live) -> None:
    """Determinism asserted by repeat invocation, not by comment.

    The sleep is load-bearing: without a real gap between the two calls, a
    wall-clock field smuggled into the payload could hold the same value twice
    and this test would pass on a stopwatch technicality.
    """
    first = json.dumps(cli.build_result("json serialization", 4), sort_keys=True)
    time.sleep(0.05)
    second = json.dumps(cli.build_result("json serialization", 4), sort_keys=True)
    assert first == second


@pytest.mark.parametrize("query", ["json.dumps", "qqxjz wvvbnq zzptk frobnicate"])
def test_available_results_carry_exactly_the_contract_keys(live, query: str) -> None:
    """Structural determinism lock, on the RETRIEVING path (hits and no-hits).

    The subprocess contract test covers the unavailable shape; this covers the
    other constructor. Any extra field — a timestamp, a duration, a debug blob
    — breaks byte-stability and lands in the model's context, so the key set is
    pinned rather than merely spot-checked.
    """
    result = cli.build_result(query, 4)
    assert result["available"] is True
    assert set(result) == {
        "available", "reason", "message", "hits_found", "exact", "search",
    }
    for hit in result["exact"] + result["search"]:
        assert set(hit) == {"source", "title", "path", "score", "excerpt"}


def test_excerpts_are_prompt_safe(live) -> None:
    """Excerpt hygiene is ``lookup``'s (control-stripped, single-line) — the
    CLI adds no second cleaning pass, so this asserts the property survives
    the trip through ``_hit_json`` on real page text."""
    result = cli.build_result("json serialization of python objects", 4)
    hits = result["exact"] + result["search"]
    assert hits
    for hit in hits:
        assert len(hit["excerpt"]) <= cli.CLI_EXCERPT_MAX_CHARS
        assert "\n" not in hit["excerpt"] and "\r" not in hit["excerpt"]
        assert not any(ord(ch) < 0x20 for ch in hit["excerpt"])


def test_excerpt_cap_actually_truncates_an_over_long_excerpt() -> None:
    """The cap, asserted where it can FAIL.

    The mini-corpus pages strip to well under the budget, so asserting
    ``len(excerpt) <= CAP`` on them is vacuously true — it passed with the cap
    deleted. This drives the real ``_hit_json`` with a real ``DocHit`` whose
    excerpt exceeds the budget, which is the only shape that can detect the
    truncation being removed.
    """
    long_excerpt = "x" * (cli.CLI_EXCERPT_MAX_CHARS + 500)
    hit = lk.DocHit(
        source="python~3.11", title="t", path="p", score=1.0, excerpt=long_excerpt
    )
    assert len(cli._hit_json(hit)["excerpt"]) == cli.CLI_EXCERPT_MAX_CHARS


def test_usage_log_records_the_call(live, tmp_path: Path) -> None:
    """Observability: every invocation is bankable evidence, in the same JSONL
    stream and schema plan_grounding writes, tagged by caller."""
    log = tmp_path / "usage.jsonl"
    cli.build_result("json.dumps", 2)
    records = [json.loads(line) for line in log.read_text("utf-8").splitlines()]
    assert records and records[-1]["caller"] == "search_docs_cli"
    assert records[-1]["outcome"] == "hits" and records[-1]["hits"] > 0


# ---------------------------------------------------------------------------
# Never raises — every failure becomes a structured result
# ---------------------------------------------------------------------------


def test_absent_index_reports_cleanly_and_names_the_fix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BLARAI_RESEARCH_DOCS", "1")
    monkeypatch.setattr(di, "DEFAULT_CORPUS_DIR", tmp_path / "absent")
    monkeypatch.setattr(di, "DEFAULT_INDEX_DIR", tmp_path / "absent" / "index")
    result = cli.build_result("json.dumps", 4)
    assert result["available"] is False
    assert result["reason"] in {"corpus_missing", "index_unavailable"}
    assert "stage_docsets.py" in result["message"] or "ensure_index" in result["message"]


def test_a_raising_retrieval_layer_becomes_a_result_not_a_crash(
    live, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ladder is the one thing that must never propagate. Patched at the
    SOURCE module, so the CLI's real import path hits the raising function."""

    def _boom(*_args: object, **_kwargs: object) -> list[Any]:
        raise RuntimeError("index corrupted mid-query")

    monkeypatch.setattr(lk, "exact_lookup", _boom)
    result = cli.build_result("json.dumps", 4)  # must not raise
    assert result["available"] is False
    assert result["reason"] == "lookup_error"
    assert "index corrupted mid-query" in result["message"]


def test_the_raising_layer_probe_is_not_vacuous(live, monkeypatch) -> None:
    """Toggle for the test above: the planted failure really does reach the
    ladder — unpatched, the same query succeeds. Without this, a typo in the
    patch target would leave the previous test asserting nothing."""
    assert cli.build_result("json.dumps", 4)["hits_found"] is True

    def _boom(*_args: object, **_kwargs: object) -> list[Any]:
        raise RuntimeError("planted")

    monkeypatch.setattr(lk, "exact_lookup", _boom)
    assert cli.build_result("json.dumps", 4)["reason"] == "lookup_error"


def test_main_returns_zero_even_when_the_lookup_fails(
    live, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def _boom(*_args: object, **_kwargs: object) -> list[Any]:
        raise RuntimeError("planted")

    monkeypatch.setattr(lk, "exact_lookup", _boom)
    assert cli.main(["--json", "-k", "2", "json.dumps"]) == 0
    assert json.loads(capsys.readouterr().out.strip())["reason"] == "lookup_error"


# ---------------------------------------------------------------------------
# The real corpus, end to end on the real command line
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not (_REAL_CORPUS / "index" / di.INDEX_FILENAME).is_file(),
    reason="staged docset index absent (gitignored; provision via scripts/stage_docsets.py)",
)
def test_real_corpus_end_to_end_through_the_wrapper_command_line() -> None:
    """The whole contract at once, on the real 13.8k-page index: the exact
    command line the Node wrapper builds, parsed the way it parses it."""
    proc = _run_cli(["--json", "-k", "3", "json.dumps"], {"BLARAI_RESEARCH_DOCS": "1"})
    result = _parse_stdout(proc)
    assert proc.returncode == 0
    assert result["available"] is True and result["hits_found"] is True
    assert result["exact"][0]["score"] == 1.0
    assert result["exact"][0]["source"] == "python~3.11"
    assert result["exact"][0]["path"] == "library/json#json.dumps"
    # Real doc pages overrun the budget where the mini corpus never does, so
    # the cap is observably biting here, on production-shaped input.
    assert max(
        len(hit["excerpt"]) for hit in result["exact"] + result["search"]
    ) == cli.CLI_EXCERPT_MAX_CHARS

    junk = _parse_stdout(
        _run_cli(
            ["--json", "-k", "4", "purple elephant birthday cake recipe"],
            {"BLARAI_RESEARCH_DOCS": "1"},
        )
    )
    assert junk["available"] is True and junk["hits_found"] is False
    assert junk["exact"] == [] and junk["search"] == []


@pytest.mark.skipif(
    not (_REAL_CORPUS / "index" / di.INDEX_FILENAME).is_file(),
    reason="staged docset index absent (gitignored; provision via scripts/stage_docsets.py)",
)
def test_real_pasted_error_line_resolves_deterministically() -> None:
    """#746's flagship path on the real corpus: paste a traceback line whole,
    and the exception name inside it resolves with no fuzzy matching.

    Scope note — this passes for the BUILT-IN exception spellings a traceback
    prints (``ValueError:``, ``AttributeError:``). It does NOT yet pass for the
    module-qualified form of a re-exported exception
    (``json.decoder.JSONDecodeError``, which the docset indexes as
    ``json.JSONDecodeError``); that gap lives in
    ``shared/research/lookup.py::exact_lookup``'s token rung, not here, and is
    reported rather than locked in by this test.
    """
    result = _parse_stdout(
        _run_cli(
            ["--json", "-k", "2", "ValueError: invalid literal for int() with base 10"],
            {"BLARAI_RESEARCH_DOCS": "1"},
        )
    )
    assert result["hits_found"] is True
    assert result["exact"], "the exception name in a real traceback did not resolve"
    assert result["exact"][0]["path"] == "library/exceptions#ValueError"
    assert result["exact"][0]["score"] >= 0.9
