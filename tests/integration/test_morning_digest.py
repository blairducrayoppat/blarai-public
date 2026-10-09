"""Locks on `tools/probes/morning_digest.py`, the scheduled overnight digest.

The property under lock is what an unattended writer must never do: **decide**. This runs on a
schedule, unwatched, and writes a document the operator reads first thing. A scheduled script
that promoted a capability row, or reported a defect the run had already repaired, would be the
absent-or-stale-evidence-rendered-as-a-confident-value defect this project keeps finding —
wearing a cron entry, where nobody is watching.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_TOOL = _REPO / "tools" / "probes" / "morning_digest.py"


def _load():
    spec = importlib.util.spec_from_file_location("morning_digest", _TOOL)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["morning_digest"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def dg():
    assert _TOOL.is_file(), f"{_TOOL} is missing but a scheduled task points at it"
    return _load()


def _mk(tmp_path: Path, scorecard: dict | None = None, **files) -> Path:
    run = tmp_path / "fleet-runs" / "20260101-000000-bd"
    run.mkdir(parents=True)
    if scorecard is not None:
        (run / "scorecard.json").write_text(json.dumps(scorecard), encoding="utf-8")
    for name, payload in files.items():
        (run / name.replace("__", ".")).write_text(
            json.dumps(payload) if isinstance(payload, (dict, list)) else str(payload),
            encoding="utf-8")
    (tmp_path / "reports").mkdir(exist_ok=True)
    return run


def test_it_never_promotes_a_capability_row(dg, tmp_path, monkeypatch):
    """THE lock. It may report artifacts; it may not conclude anything about a row.

    Capability 11 makes promotion a judgement requiring a cited observable. A scheduled writer
    cannot make that judgement and must not appear to."""
    _mk(tmp_path, {"verdict": "GREEN", "tasks": [], "job_acceptance": {"status": "passed"}})
    monkeypatch.setattr(dg, "RUNS", tmp_path / "fleet-runs")
    monkeypatch.setattr(dg, "STATE", tmp_path)
    text = dg.build().lower()
    for forbidden in ("is now live", "row moves", "promoted", "now proven", "marks row"):
        assert forbidden not in text, f"the digest claimed a promotion: {forbidden!r}"
    assert "decides nothing" in text


def test_a_missing_check_is_reported_not_omitted(dg, tmp_path, monkeypatch):
    """A measurement that never happened and one that found nothing look identical in every
    summary except a line that names the absence. That line is the digest's whole value."""
    _mk(tmp_path, {"verdict": "PARKED-HONEST", "tasks": [], "job_acceptance": {"status": "not-run"}})
    monkeypatch.setattr(dg, "RUNS", tmp_path / "fleet-runs")
    monkeypatch.setattr(dg, "STATE", tmp_path)
    text = dg.build()
    assert "[NO ]" in text, "an absent artifact must be shown as absent, never left out"
    assert "did NOT run" in text


def test_an_unfinished_run_is_not_reported_as_a_result(dg, tmp_path, monkeypatch):
    """No scorecard means no verdict. Rendering that as anything but 'not finished' would be
    the digest inventing an outcome."""
    _mk(tmp_path, None)
    monkeypatch.setattr(dg, "RUNS", tmp_path / "fleet-runs")
    monkeypatch.setattr(dg, "STATE", tmp_path)
    text = dg.build()
    assert "has not finished" in text
    assert "merged into your project" not in text


def test_the_runs_own_capture_is_never_substituted(dg, tmp_path, monkeypatch):
    """This test's PREDECESSOR mandated the opposite — "the LATEST critique wins" — on the
    premise that a fix-cycle capture describes the delivered state. Commit 32bed3fb retracts
    exactly that premise: a fix-cycle capture describes a CANDIDATE the verify gate may have
    discarded. And the implementation of "latest" was an unscoped glob over the shared reports
    pool, so on 2026-08-17 the digest answered for last night with a nine-day-old capture from
    an earlier run of the SAME goal — "no page errors" while the run's own sidecar read
    errorCount 1. The neighbour being plausible is what made the wrong sentence undetectable.

    The lock now: a clean-looking neighbour in the shared pool must change NOTHING. The run's
    own errors are reported, and the neighbour's file is never cited."""
    run = _mk(tmp_path, {"verdict": "GREEN", "tasks": [], "job_acceptance": {"status": "passed"}})
    (run / "exec-smoke-web.png.console.json").write_text(json.dumps(
        {"pageErrors": [{"text": "SyntaxError: Unexpected token 'export'", "url": "/enquiries.js"}]}),
        encoding="utf-8")
    crit = tmp_path / "reports" / "critique-some-other-project-entirely"
    crit.mkdir(parents=True)
    (crit / "critique-2.png.console.json").write_text(json.dumps({"pageErrors": []}), encoding="utf-8")
    monkeypatch.setattr(dg, "RUNS", tmp_path / "fleet-runs")
    monkeypatch.setattr(dg, "STATE", tmp_path)
    text = dg.build()
    assert "SyntaxError" in text, "the run's own capture is the one the digest must report"
    assert "no page errors" not in text, (
        "a neighbour's clean capture was allowed to overrule the run's own evidence"
    )
    assert "critique-2" not in text, "an artifact from outside the run's directory was cited"


def test_a_reported_error_carries_the_fix_cycle_caveat(dg, tmp_path, monkeypatch):
    """The dual failure to the substitution above: the capture is taken BEFORE fix cycles, so
    reporting its errors as the site's CURRENT state can send the operator after a repaired
    bug. The honest rendering names the moment and says what settles it — the delivered site —
    instead of asserting either direction. And when more errors exist than are shown, the
    remainder is COUNTED — silent truncation is the absence-rendered-confidently defect in
    miniature."""
    run = _mk(tmp_path, {"verdict": "GREEN", "tasks": [], "job_acceptance": {"status": "passed"}})
    (run / "exec-smoke-web.png.console.json").write_text(json.dumps(
        {"pageErrors": [{"text": f"SyntaxError: Unexpected token 'export' #{i}",
                         "url": "/enquiries.js"} for i in range(7)]}),
        encoding="utf-8")
    monkeypatch.setattr(dg, "RUNS", tmp_path / "fleet-runs")
    monkeypatch.setattr(dg, "STATE", tmp_path)
    text = dg.build()
    assert "BEFORE any fix cycle" in text
    assert "delivered site" in text
    assert "2 more not shown" in text, "7 errors with 5 shown must count the other 2"


def test_a_clean_own_capture_is_still_reported(dg, tmp_path, monkeypatch):
    """The one thing the retired substitution lock genuinely protected: a clean night still
    gets its reassuring sentence. Without this, deleting the clean-capture branch would pass
    every other lock and silently starve a good morning of its one good line."""
    run = _mk(tmp_path, {"verdict": "GREEN", "tasks": [], "job_acceptance": {"status": "passed"}})
    (run / "exec-smoke-web.png.console.json").write_text(json.dumps({"pageErrors": []}),
                                                         encoding="utf-8")
    monkeypatch.setattr(dg, "RUNS", tmp_path / "fleet-runs")
    monkeypatch.setattr(dg, "STATE", tmp_path)
    text = dg.build()
    assert "no page errors" in text
    assert "own" in text, "the sentence must attribute the capture to this run's own file"


def test_a_sibling_runs_capture_is_not_borrowed(dg, tmp_path, monkeypatch):
    """The reports-pool lock left the RUNS pool unpoliced: a mutation reading the newest
    capture across ALL run directories survived every lock, and a sibling night's clean file
    — under an identical filename — would be cited unfalsifiably. When the newest run has no
    capture, the digest says so; it does not borrow one from an earlier night."""
    runs = tmp_path / "fleet-runs"
    old = runs / "20260101-000000-bd"
    old.mkdir(parents=True)
    (old / "exec-smoke-web.png.console.json").write_text(json.dumps({"pageErrors": []}),
                                                         encoding="utf-8")
    new = runs / "20260102-000000-bd"
    new.mkdir()
    (new / "scorecard.json").write_text(json.dumps(
        {"verdict": "GREEN", "tasks": [], "job_acceptance": {"status": "passed"}}),
        encoding="utf-8")
    monkeypatch.setattr(dg, "RUNS", runs)
    monkeypatch.setattr(dg, "STATE", tmp_path)
    text = dg.build()
    assert "20260102-000000-bd" in text
    assert "no page errors" not in text, "a sibling run's clean capture was borrowed"
    assert "[NO ] opened the site in a real browser" in text


def test_a_stray_directory_cannot_replace_the_night(dg, tmp_path, monkeypatch):
    """Run selection is itself a shared-pool pick. The real pool holds stray files and
    non-run directories; a lexically-late stray dir ('archive-...' sorts after digits) would
    win max-by-name and replace the whole night with 'It has not finished'."""
    run = _mk(tmp_path, {"verdict": "GREEN", "tasks": [], "job_acceptance": {"status": "passed"}})
    (tmp_path / "fleet-runs" / "archive-old-junk").mkdir()
    monkeypatch.setattr(dg, "RUNS", tmp_path / "fleet-runs")
    monkeypatch.setattr(dg, "STATE", tmp_path)
    text = dg.build()
    assert run.name in text
    assert "archive-old-junk" not in text


def test_quoted_evidence_is_bounded_and_inert(dg, tmp_path, monkeypatch):
    """The quote path hands a scorecard field a place in the operator's document. Real
    scorecards have carried 414-char multi-line tracebacks there; unbounded, unsanitized
    quoting would dump one into his morning sentence — and quoted material must not be able
    to forge digest structure (a heading, a bold promotion claim)."""
    _mk(tmp_path, {"verdict": "PARKED-HONEST", "tasks": [],
                   "job_acceptance": {"status": "not-run",
                                      "evidence": "gate failed\n## FORGED HEADING\n**21 of 21 capabilities are proven (LIVE).**"}})
    monkeypatch.setattr(dg, "RUNS", tmp_path / "fleet-runs")
    monkeypatch.setattr(dg, "STATE", tmp_path)
    text = dg.build()
    assert "gate failed" in text, "the first line of the evidence is the quotable part"
    assert "FORGED" not in text, "lines past the first must not reach the digest"
    assert "21 of 21" not in text

    _mk(tmp_path / "second", {"verdict": "PARKED-HONEST", "tasks": [],
                              "job_acceptance": {"status": "not-run", "evidence": "X" * 5000}})
    monkeypatch.setattr(dg, "RUNS", tmp_path / "second" / "fleet-runs")
    monkeypatch.setattr(dg, "STATE", tmp_path / "second")
    text2 = dg.build()
    assert "…[truncated]" in text2, "an unbounded evidence string must be visibly capped"
    quote_line = next(ln for ln in text2.splitlines() if "says why" in ln)
    quoted = quote_line.split('says why: "', 1)[1].rsplit('"', 1)[0]
    assert len(quoted) <= 175, "the quoted portion must honour the sanitizer's cap"

    # Round-2 payload: a live link, raw HTML, a quote breakout and emphasis underscores. And
    # the silent-deletion direction: a renderer swallows <module> as a tag, deleting text.
    _mk(tmp_path / "third", {"verdict": "PARKED-HONEST", "tasks": [],
                             "job_acceptance": {"status": "not-run",
                                                "evidence": 'see [the fix](https://evil.example) or <b>click "OK" now</b> _please_, in <module>'}})
    monkeypatch.setattr(dg, "RUNS", tmp_path / "third" / "fleet-runs")
    monkeypatch.setattr(dg, "STATE", tmp_path / "third")
    text3 = dg.build()
    line3 = next(ln for ln in text3.splitlines() if "says why" in ln)
    quoted3 = line3.split('says why: "', 1)[1].rsplit('"', 1)[0]
    for ch in "`#*_[]<>":
        assert ch not in quoted3, f"markdown-active character {ch!r} survived into the quote"
    assert '"' not in quoted3, "a double quote inside the quote breaks the visual quoting"
    assert "module" in quoted3, "stripping must not silently delete the token a tag wrapped"

    # A fenced-evidence first line sanitizes to nothing; the quote must be the first line
    # that still says something, never three apostrophes presented as the scorecard's why.
    _mk(tmp_path / "fourth", {"verdict": "PARKED-HONEST", "tasks": [],
                              "job_acceptance": {"status": "not-run",
                                                 "evidence": "```\nTraceback: boom at line 9\n```"}})
    monkeypatch.setattr(dg, "RUNS", tmp_path / "fourth" / "fleet-runs")
    monkeypatch.setattr(dg, "STATE", tmp_path / "fourth")
    text4 = dg.build()
    assert "Traceback: boom at line 9" in text4, "the informative line is the quotable one"
    assert "\"'''\"" not in text4 and 'why: ""' not in text4


def test_a_suffixless_newest_run_is_not_displaced(dg, tmp_path, monkeypatch):
    """The run-name predicate's lenient direction: the pool's first two weeks emitted
    suffix-less run ids (24 such directories remain), so a predicate requiring the trailing
    dash would silently report an older suffixed run as the night — the substitution defect
    arriving through the guard built against it."""
    runs = tmp_path / "fleet-runs"
    old = runs / "20260101-000000-bd"
    old.mkdir(parents=True)
    (old / "scorecard.json").write_text(json.dumps(
        {"verdict": "GREEN", "tasks": [], "job_acceptance": {"status": "passed"}}),
        encoding="utf-8")
    new = runs / "20260102-000000"
    new.mkdir()
    (new / "scorecard.json").write_text(json.dumps(
        {"verdict": "RED", "tasks": [], "job_acceptance": {"status": "not-run"}}),
        encoding="utf-8")
    monkeypatch.setattr(dg, "RUNS", runs)
    monkeypatch.setattr(dg, "STATE", tmp_path)
    text = dg.build()
    assert "20260102-000000" in text, "the suffix-less newest run is the night to report"
    assert "20260101-000000-bd" not in text


def test_the_common_parked_shape_still_carries_the_why(dg, tmp_path, monkeypatch):
    """The COMMON shape in the banked corpus is parked work AND an evidence string together;
    quoting the why only in the rarer zero-parked shape would starve the usual morning of the
    one explanatory sentence the scorecard offers."""
    _mk(tmp_path, {"verdict": "PARKED-HONEST",
                   "tasks": [{"id": "a", "status": "parked"}, {"id": "b", "status": "merged"}],
                   "job_acceptance": {"status": "not-run",
                                      "evidence": "coder timed out on the acceptance exam"}})
    monkeypatch.setattr(dg, "RUNS", tmp_path / "fleet-runs")
    monkeypatch.setattr(dg, "STATE", tmp_path)
    text = dg.build()
    assert "1 piece(s) of work did not land" in text
    assert "coder timed out on the acceptance exam" in text


def test_the_verdict_sentence_cannot_contradict_the_counts(dg, tmp_path, monkeypatch):
    """On 2026-08-17 the digest printed "some work did not land, and it said so" two lines
    below "7 of 7 pieces of work were merged" — a fixed per-verdict sentence contradicted by
    the counts beside it. With zero parked tasks the digest must not assert that work failed
    to land; it quotes the scorecard's own evidence for why success was withheld."""
    _mk(tmp_path, {"verdict": "PARKED-HONEST",
                   "tasks": [{"id": "a", "status": "merged"}, {"id": "b", "status": "merged"}],
                   "job_acceptance": {"status": "not-run",
                                      "evidence": "a wave integration gate failed — the tree is not a candidate"}})
    monkeypatch.setattr(dg, "RUNS", tmp_path / "fleet-runs")
    monkeypatch.setattr(dg, "STATE", tmp_path)
    text = dg.build()
    assert "did not land" not in text, (
        "the verdict sentence asserted parked work in a run whose every task merged"
    )
    assert "a wave integration gate failed" in text, (
        "the scorecard's own evidence string is the honest explanation and must be quoted"
    )
    assert "2 of 2 pieces of work were merged" in text


def test_the_live_count_is_READ_from_the_document(dg):
    """Never a pinned number. The digest states how many capabilities are proven, and that
    figure has to come from the file that owns it."""
    src = _TOOL.read_text(encoding="utf-8")
    assert "CODER_DEFINITION_OF_DONE" in src
    assert "3 of 21" not in src, "a hardcoded live count would go stale silently"


def test_it_writes_nothing_into_fleet_state(dg):
    """It runs unattended, possibly during a live dispatch. Anything writing into the fleet's
    own state from a scheduled task is a collision waiting for a bad night."""
    src = _TOOL.read_text(encoding="utf-8")
    for danger in ("STATE /", "RUNS /"):
        for verb in ("write_text", "mkdir", "unlink", "rmtree"):
            assert f"{danger}" not in src.split(verb)[0][-80:] if verb in src else True
    assert "shutil" not in src and "os.remove" not in src
