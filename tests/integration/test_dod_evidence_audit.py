"""Locks on `tools/probes/dod_evidence_audit.py`, the corpus-wide DoD evidence audit.

The property under lock is the one this probe exists to protect: **it reports whether an
ARTIFACT exists and must never be readable as a verdict that a row is LIVE.** Capability 11
asks whether a row's own observable was executed; artifact presence is necessary for that and
never sufficient, and the gap between the two is exactly where a row gets promoted on evidence
that does not support it.

The second locked property is that the row statuses are PARSED FROM THE DOCUMENT, never
pinned here. A hardcoded status list would be one more hand-maintained number, which is the
failure this probe was written to measure.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_TOOL = _REPO / "tools" / "probes" / "dod_evidence_audit.py"


def _load():
    spec = importlib.util.spec_from_file_location("dod_evidence_audit", _TOOL)
    assert spec is not None and spec.loader is not None, f"cannot load {_TOOL}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules["dod_evidence_audit"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def audit():
    assert _TOOL.is_file(), f"{_TOOL} is missing"
    return _load()


def test_row_statuses_are_parsed_from_the_document_not_pinned(audit):
    """If this probe carried its own copy of the statuses it would be one more number
    maintained by hand — the exact failure it was written to measure."""
    rows = audit.parse_rows()
    assert len(rows) >= 21, f"expected at least 21 DoD rows, parsed {len(rows)}"
    assert [r.number for r in rows] == sorted(r.number for r in rows), "rows out of order"
    assert all(r.status for r in rows), "a row parsed with no status at all"
    # The statuses must come from the file: change the file, change the answer.
    src = _TOOL.read_text(encoding="utf-8")
    assert '"LIVE", "PARTIAL"' not in src and "STATUSES = [" not in src, (
        "a pinned status list defeats the point of parsing"
    )


def test_a_row_with_NO_status_line_is_reported_not_skipped(audit, tmp_path, monkeypatch):
    """Silence about a malformed row would be the probe committing the defect it audits."""
    doc = tmp_path / "dod.md"
    doc.write_text(
        "### 1. It builds what was asked\n**Status: LIVE as of 2026-01-01**\n\n"
        "### 2. A row somebody forgot to stamp\nsome prose and no status marker\n",
        encoding="utf-8")
    monkeypatch.setattr(audit, "DOD", doc)
    rows = audit.parse_rows()
    assert [r.status for r in rows] == ["LIVE", "NO STATUS LINE"], (
        "a row with no status must be NAMED, never silently dropped or defaulted to something "
        "that reads like a real status"
    )


def test_presence_and_VALUE_checks_are_distinguishable(audit):
    """`kind` is the honesty field. A probe that merely found a file must not be read as
    having confirmed the row's observable — row 5 wants `hard >= 1`, not the existence of a
    coder-test-qa record, and those two live in the same file."""
    kinds = {p.kind for p in audit.PROBES}
    assert kinds <= {"presence", "value"}, f"unknown probe kind: {kinds}"
    assert "value" in kinds and "presence" in kinds, "both strengths must be represented"

    labelled = {p.label: p for p in audit.PROBES}
    ran = labelled["a WEBSITE exam was examined at all"]
    flagged = labelled["a delivered test was FLAGGED as unable to fail"]
    assert ran.kind == flagged.kind == "value"
    assert ran.test is not flagged.test, (
        "'the check ran' and 'the check flagged something' are DIFFERENT observables and must "
        "not share a predicate — conflating them is how row 4 gets promoted on a clean scan"
    )


def test_a_value_probe_actually_discriminates(audit, tmp_path, monkeypatch):
    """The load-bearing direction: a matching artifact counts, a non-matching one does not.
    A probe that returns True for everything would report every row as evidenced."""
    state = tmp_path
    (state / "reports").mkdir(parents=True)
    (state / "reports" / "a.coder-test-qa.json").write_text(
        json.dumps({"languages": {"python": 2, "node": 0}, "hard": 0}), encoding="utf-8")
    (state / "reports" / "b.coder-test-qa.json").write_text(
        json.dumps({"languages": {"python": 0, "node": 2}, "hard": 0}), encoding="utf-8")
    monkeypatch.setattr(audit, "STATE", state)

    ran = next(p for p in audit.PROBES if p.label == "a WEBSITE exam was examined at all")
    hits, examined, newest = audit.scan(ran)
    assert (hits, examined) == (1, 2), "only the node record may count as a website exam"
    assert newest.endswith("b.coder-test-qa.json")

    flagged = next(p for p in audit.PROBES
                   if p.label == "a delivered test was FLAGGED as unable to fail")
    hits, examined, _ = audit.scan(flagged)
    assert (hits, examined) == (0, 2), (
        "neither record has hard >= 1, so nothing was flagged — a clean website scan must NOT "
        "satisfy row 5's trigger"
    )


def test_a_malformed_artifact_is_not_counted_as_evidence(audit, tmp_path, monkeypatch):
    """Fail-closed. Unreadable JSON is an absence, and counting it would manufacture the
    evidence this probe exists to look for."""
    state = tmp_path
    (state / "reports").mkdir(parents=True)
    (state / "reports" / "broken.coder-test-qa.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(audit, "STATE", state)
    ran = next(p for p in audit.PROBES if p.label == "a WEBSITE exam was examined at all")
    hits, examined, _ = audit.scan(ran)
    assert (hits, examined) == (0, 1)


def test_the_report_refuses_to_read_as_a_verdict(audit, tmp_path, monkeypatch, capsys):
    """The whole point, at the surface a person reads. `NEVER` must be rendered for a probe
    with no hits, and the closing paragraph must say artifact presence is not sufficient."""
    monkeypatch.setattr(audit, "STATE", tmp_path)  # empty bank: nothing can be evidenced
    rc = audit.main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "NEVER" in out, "an unevidenced row must be marked, not omitted"
    assert "never\nsufficient" in out or "never sufficient" in out.replace("\n", " "), (
        "the report must state that evidence existing does not make a row LIVE"
    )
    assert "capability 11" in out


def test_it_runs_as_a_script_against_the_real_bank():
    """Reachability. A probe that only works under pytest is not an instrument anyone will
    use, and this one is named in the dod-witness agent as step one of its loop."""
    proc = subprocess.run([sys.executable, str(_TOOL), "--json"],
                          capture_output=True, text=True, timeout=180, cwd=str(_REPO))
    assert proc.returncode == 0, proc.stderr[-2000:]
    payload = json.loads(proc.stdout)
    assert len(payload["rows"]) >= 21
    assert payload["status_counts"], "no statuses parsed from the live document"
    assert payload["evidence"], "no evidence probes ran"
    for e in payload["evidence"]:
        assert e["kind"] in {"presence", "value"}
        assert e["rows"], "every probe must name the rows it serves"
