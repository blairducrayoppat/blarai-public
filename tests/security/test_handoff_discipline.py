# enforces-rule: critical_rules.watch-the-context-gauge -- landing card form, not the gauge timing
# enforces-rule: context_handoff.the-landing-card-template
# enforces-rule: context_handoff.location
"""Handoff-discipline gate (#1144, LA-ratified 2026-07-28).

The 2026-07-28 audit measured the world-report brief era: 137 briefs /
~2.1 MB of continuity prose, median ~22 KB, authored at the moment of
maximum fatigue — every handoff failure answered by adding MORE brief while
the durable substrate (board, journal, registers) was the right home for
the weight. These tests are the structural control for the replacement
practice: facts bank in their durable homes at event time
(``CLAUDE.md <event_time_banking>``) and the brief that remains is a
landing card too small by construction to carry a rebuilt world.

Three surfaces are pinned:
  1. The template + ops-surface doc pair — the ops block must LIVE in the
     one tracked doc and be CITED (never pasted) by the template, and the
     template must declare the machine-enforced landing-card contract.
  2. The verifier's landing-card gates — size, structure, forbidden
     world-report sentinels, the legacy cutover, and the fail-closed
     undated case; each control proven to FIRE and proven to PASS
     compliant input (security_by_design principle 12).
  3. The assembler — its draft must itself satisfy the gates it feeds,
     and it must refuse to overwrite (docs/handoffs/ is gitignored, so an
     overwrite there is unrecoverable).

Scope: doctrine files + two dev scripts. No live system contact, no model.
"""
from __future__ import annotations

import importlib.util
import os
import re
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "docs" / "governance" / "handoff-brief-template.md"
OPS_SURFACE = REPO_ROOT / "docs" / "governance" / "session-ops-surface.md"
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"


def _load(script_name: str):
    path = REPO_ROOT / "scripts" / script_name
    name = script_name.removesuffix(".py")
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    # Registered BEFORE exec: dataclasses resolve string annotations through
    # sys.modules[cls.__module__]; an unregistered module breaks that lookup.
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


verifier = _load("verify_handoff_brief.py")
assembler = _load("author_landing_card.py")


# ---------------------------------------------------------------------------
# 1. Template + ops-surface pins
# ---------------------------------------------------------------------------


def test_template_declares_the_landing_card_contract() -> None:
    """The template names the version key, both budgets, and every section."""
    text = TEMPLATE.read_text(encoding="utf-8")
    assert "template: landing-card-v1" in text
    assert "150 lines" in text and "8 KB" in text
    for section in verifier._LANDING_REQUIRED_SECTIONS:
        assert section in text, f"template lost required section {section!r}"


def test_template_cites_ops_surface_and_never_pastes_it() -> None:
    """Citation, not duplication: the 137-pasted-copies era stays retired."""
    text = TEMPLATE.read_text(encoding="utf-8")
    assert "session-ops-surface.md" in text
    assert "Start-Process" not in text, (
        "the template embeds ops commands again - cite docs/governance/"
        "session-ops-surface.md instead (the pasted copies drifted; #1144)"
    )


def test_ops_surface_carries_the_moved_block() -> None:
    """The extraction was a MOVE, not a deletion - the one copy is complete."""
    assert OPS_SURFACE.exists(), "session-ops-surface.md missing - briefs now cite it"
    text = OPS_SURFACE.read_text(encoding="utf-8")
    for needle in ("STANDING AUTHORIZATION", "Start-Process -FilePath", "swap_ops", "kill -0"):
        assert needle in text, f"ops surface lost {needle!r} - the move is incomplete"


def test_claude_md_wires_the_discipline() -> None:
    """Doctrine names the banking section, the tools, and the new verbs."""
    text = CLAUDE_MD.read_text(encoding="utf-8")
    assert "<event_time_banking" in text
    # The landing-card mechanics live in the path-scoped handoff rules (#1700), delivered
    # when a session reads or writes the card, its template or these scripts.
    rules = (REPO_ROOT / ".claude" / "rules" / "handoff.md").read_text(encoding="utf-8")
    assert "author_landing_card.py" in rules and "verify_handoff_brief.py" in rules
    assert "handoff.md" in text, "CLAUDE.md <rules_index> lost the handoff rules entry"
    assert "UNBLOCKS" in text, "critical rule 5 lost the unblock-sweep verb"
    assert "DELTA-GATE" in text, "comprehension_gate lost the continuation tier"


# The gate point itself (MONITORING) is pinned on all four gate surfaces, in list
# position, by test_doctrine_freshness.GATE_SURFACES. This pins the SECOND requirement
# a list lock cannot see: the continuation tier must carry its own monitoring line,
# or a delta-gate of a long program plans no watch (#1668).
_DELTA_GATE_SURFACES = (
    (CLAUDE_MD, "DELTA-GATE (#1144)"),
    (TEMPLATE, "**delta-gate**"),
)


def _delta_gate_clause(text: str, needle: str) -> str:
    """The SENTENCE that states the delta-gate, whatever its word order.

    Scoped to the sentence on purpose. The full gate on the same surface names
    MONITORING too, so a whole-file search passes with the delta-gate's line deleted;
    and a window that stops at a fixed phrase misses the line in a legitimate reorder.
    """
    text = text.replace("\r\n", "\n")
    at = text.find(needle)
    if at < 0:
        return ""
    before = list(re.finditer(r"\.\s", text[:at]))
    start = before[-1].end() if before else 0
    end = re.search(r"\.(?=\s|$)", text[at:])
    stop = at + end.end() if end else len(text)
    return text[start:stop]


def _delta_gate_names_monitoring(text: str, needle: str) -> bool:
    return "MONITORING" in _delta_gate_clause(text, needle).upper()


def test_delta_gate_carries_a_monitoring_line_on_both_surfaces() -> None:
    for path, needle in _DELTA_GATE_SURFACES:
        text = path.read_text(encoding="utf-8")
        assert _delta_gate_clause(text, needle), f"{path.name}: the delta-gate clause moved or vanished"
        assert _delta_gate_names_monitoring(text, needle), (
            f"{path.name}: the delta-gate lost its MONITORING line (#1668)"
        )


def test_delta_gate_monitoring_probe_fails_when_the_line_is_removed() -> None:
    """Principle 12: the probe must be able to FAIL, including when MONITORING is
    still present elsewhere on the surface (the full gate's point 7)."""
    for path, needle in _DELTA_GATE_SURFACES:
        text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        clause = _delta_gate_clause(text, needle)
        assert "MONITORING" in clause.upper(), f"{path.name}: nothing to remove"
        stripped = re.sub("MONITORING", "", clause, flags=re.IGNORECASE)
        mutated = text.replace(clause, stripped)
        assert "MONITORING" in mutated.upper(), "mutation must leave MONITORING elsewhere"
        assert not _delta_gate_names_monitoring(mutated, needle), (
            f"{path.name}: probe passed with the delta-gate's monitoring line removed"
        )


def test_delta_gate_lock_accepts_the_line_in_any_word_order() -> None:
    """A legitimate reorder must not trip the lock: the line moved to the end of the
    sentence, past 'before substantive action', still counts; the same sentence with
    the line gone does not."""
    for path, needle in _DELTA_GATE_SURFACES:
        text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        clause = _delta_gate_clause(text, needle)
        assert clause.endswith("."), f"{path.name}: unexpected clause shape {clause[-20:]!r}"
        body = re.sub("MONITORING", "watch", clause[:-1], flags=re.IGNORECASE)
        reordered = text.replace(clause, body + ", with a MONITORING line.")
        assert _delta_gate_names_monitoring(reordered, needle), (
            f"{path.name}: a reordered delta-gate line tripped the lock"
        )
        assert not _delta_gate_names_monitoring(text.replace(clause, body + "."), needle)

# ---------------------------------------------------------------------------
# 2. Verifier landing-card gates (drive verify_brief through real tmp files)
# ---------------------------------------------------------------------------

_SECTIONS_BODY = "\n\n".join(
    f"{section}\n\ncontent" for section in verifier._LANDING_REQUIRED_SECTIONS
)


def _card(
    *,
    date: str = "2026-08-01",
    template_key: bool = True,
    body: str | None = None,
    extra: str = "",
) -> str:
    fm = ["---", "artifact_type: handoff-brief"]
    if template_key:
        fm.append("template: landing-card-v1")
    if date:
        fm.append(f"date: {date}")
    fm.append("---")
    body = _SECTIONS_BODY if body is None else body
    anchors = "```anchors\nticket   | #1 | topic ticket\n```"
    return "\n".join([*fm, "", "# Landing card — t", "", body, extra, "", anchors, ""])


def _verify(tmp_path: Path, text: str, *, mtime: float | None = None, name: str = "t-landing-20260801.md"):
    brief = tmp_path / name
    brief.write_text(text, encoding="utf-8")
    if mtime is not None:
        os.utime(brief, (mtime, mtime))
    return verifier.verify_brief(brief, tmp_path)


def _struct_fails(report) -> list[str]:
    return [detail for status, detail in report.structure if status == "FAIL"]


def test_wellformed_landing_card_passes(tmp_path: Path) -> None:
    report = _verify(tmp_path, _card())
    assert report.ok, f"compliant card failed: {verifier.render_report(report)}"
    assert _struct_fails(report) == []


def test_missing_template_key_fails(tmp_path: Path) -> None:
    report = _verify(tmp_path, _card(template_key=False))
    assert not report.ok
    assert any("template: landing-card-v1" in d for d in _struct_fails(report))


def test_oversize_card_fails(tmp_path: Path) -> None:
    padding = "\n".join(f"line {i}" for i in range(160))
    report = _verify(tmp_path, _card(extra=padding))
    assert not report.ok
    assert any("budget" in d for d in _struct_fails(report))


def test_missing_section_fails(tmp_path: Path) -> None:
    body = "\n\n".join(
        f"{s}\n\ncontent"
        for s in verifier._LANDING_REQUIRED_SECTIONS
        if s != "## Machine state"
    )
    report = _verify(tmp_path, _card(body=body))
    assert not report.ok
    assert any("## Machine state" in d for d in _struct_fails(report))


def test_world_report_queue_table_fails(tmp_path: Path) -> None:
    report = _verify(tmp_path, _card(extra="## Work queue\n\n| # | State |"))
    assert not report.ok
    assert any("board is the SSOT" in d for d in _struct_fails(report))


def test_pasted_ops_block_fails(tmp_path: Path) -> None:
    report = _verify(
        tmp_path, _card(extra="**STANDING AUTHORIZATION (User-Operator):** ...")
    )
    assert not report.ok
    assert any("session-ops-surface.md" in d for d in _struct_fails(report))


def test_legacy_brief_warns_not_fails(tmp_path: Path) -> None:
    """History is never retroactively failed - pre-cutover briefs keep the
    anchors-only contract and gain exactly one legacy WARN."""
    legacy = "\n".join(
        [
            "---",
            "artifact_type: handoff-brief",
            "date: 2026-07-20",
            "---",
            "",
            "# Handoff brief — old world",
            "",
            "## Work queue",
            "",
            "| a | b |",
            "",
            "```anchors",
            "ticket   | #1 | topic ticket",
            "```",
            "",
        ]
    )
    report = _verify(tmp_path, legacy, name="old-world-handoff-20260720.md")
    assert report.ok, f"legacy brief must not fail: {verifier.render_report(report)}"
    assert any(status == "WARN" and "legacy" in detail for status, detail in report.structure)


def test_copied_legacy_date_in_new_filename_fails(tmp_path: Path) -> None:
    """MIN4 cross-check: a post-cutover FILENAME carrying a pre-cutover
    frontmatter date (the copied-old-brief path) is denied the exemption."""
    report = _verify(tmp_path, _card(date="2026-07-20"), name="t-landing-20260801.md")
    assert not report.ok
    assert any("cannot claim" in d for d in _struct_fails(report))


def test_byte_budget_arm_fires(tmp_path: Path) -> None:
    """Principle-12 fires-proof for the BYTE arm: few lines, many bytes."""
    report = _verify(tmp_path, _card(extra="x" * 9000))
    assert not report.ok
    assert any("budget" in d for d in _struct_fails(report))


def test_pasted_start_process_sentinel_fires(tmp_path: Path) -> None:
    report = _verify(tmp_path, _card(extra='Start-Process -FilePath "C:/x.exe"'))
    assert not report.ok
    assert any("session-ops-surface.md" in d for d in _struct_fails(report))


def test_missing_stamp_warns(tmp_path: Path) -> None:
    report = _verify(tmp_path, _card())
    assert report.ok
    assert any(s == "WARN" and "stamp missing" in d for s, d in report.structure)


def test_unparseable_stamp_warns(tmp_path: Path) -> None:
    stamped = _card(extra="<!-- machine-state generated NOT-A-DATE by author_landing_card.py -->")
    report = _verify(tmp_path, stamped, mtime=time.time())
    assert report.ok
    assert any(s == "WARN" and "unparseable" in d for s, d in report.structure)


def test_undated_brief_cannot_claim_legacy(tmp_path: Path) -> None:
    """Fail-closed: no date means the landing-card rules apply."""
    report = _verify(tmp_path, _card(date=""))
    assert not report.ok
    assert any("legacy exemption" in d for d in _struct_fails(report))


def test_stale_stamp_warns_not_fails(tmp_path: Path) -> None:
    """A stale machine-state stamp degrades to a warning - a broken probe
    must never block grounding - but the warning must actually fire."""
    stamped = _card(extra="<!-- machine-state generated 2026-08-01T00:00:00 by author_landing_card.py -->")
    stale_mtime = time.mktime((2026, 8, 1, 6, 0, 0, 0, 0, -1))
    report = _verify(tmp_path, stamped, mtime=stale_mtime)
    assert report.ok
    assert any(
        status == "WARN" and "regenerate" in detail for status, detail in report.structure
    )


# ---------------------------------------------------------------------------
# 3. Assembler: its draft satisfies the gates it feeds; overwrite refused
# ---------------------------------------------------------------------------


def _stub_probes(monkeypatch) -> None:
    """Live process/task probes are machine-state-dependent (and spawn
    PowerShell); the gate stays deterministic on stubbed probes while the
    real probes remain live-verified at authoring time."""
    monkeypatch.setattr(
        assembler, "_process_lines",
        lambda: ["- live processes: none matching app/dispatch/battery"],
    )
    monkeypatch.setattr(
        assembler, "_scheduled_task_lines",
        lambda: ["- scheduled task: BlarAI-M2-Battery-Nightly [Ready]"],
    )


def test_assembler_draft_passes_the_structure_gates(monkeypatch) -> None:
    """The generated draft must be a compliant landing card on arrival."""
    import datetime as dt

    _stub_probes(monkeypatch)
    card = assembler.build_card("gate-selftest", REPO_ROOT, dt.datetime.now())
    assert len(card.splitlines()) <= verifier._LANDING_MAX_LINES
    results = verifier.check_structure(card, mtime=time.time())
    fails = [d for s, d in results if s == "FAIL"]
    assert fails == [], f"assembler draft violates the gates: {fails}"
    # cp1252-encodable skeleton: a --stdout draft must survive a default
    # Windows console (regression lock for the live-caught U+2264 crash).
    card.encode("cp1252", errors="strict")


def test_assembler_refuses_overwrite(tmp_path: Path, monkeypatch) -> None:
    """docs/handoffs/ is gitignored - an overwrite is unrecoverable, so the
    assembler must refuse a second write to the same path."""
    _stub_probes(monkeypatch)
    argv = ["--topic", "twice", "--repo", str(tmp_path)]
    assert assembler.main(argv) == 0
    assert assembler.main(argv) == 2


def test_assembler_rejects_bad_slug(tmp_path: Path) -> None:
    assert assembler.main(["--topic", "Bad Slug!!", "--repo", str(tmp_path), "--stdout"]) == 2
