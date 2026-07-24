"""Tests for tools.doc_lint — deterministic, temp-fixture only, no real repo docs.

Covers the frontmatter parser, every rule in ``check_file``, the non-recursive
directory scan (node_modules-safety), and the CLI exit-code contract.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tools.doc_lint.cli import main
from tools.doc_lint.lint import (
    CANONICAL_STATUSES,
    check_file,
    check_paths,
    parse_frontmatter,
)

COMPLIANT = """\
---
title: A Living Doc
status: living
area: governance
---

# A Living Doc

Body.
"""


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _codes(report) -> set[str]:
    return {f.code for f in report.findings}


# --- frontmatter parser -----------------------------------------------------


def test_parse_returns_none_without_fence():
    assert parse_frontmatter("# No frontmatter\n\ntext") is None


def test_parse_returns_none_on_unterminated_fence():
    assert parse_frontmatter("---\ntitle: x\nno closing fence\n") is None


def test_parse_flat_scalars_with_crlf_quotes_and_inline_comment():
    text = "---\r\ntitle: \"Quoted Title\"\r\nstatus: living   # a comment\r\narea: governance\r\n---\r\n# Body\r\n"
    fields = parse_frontmatter(text)
    assert fields == {
        "title": "Quoted Title",
        "status": "living",
        "area": "governance",
    }


# --- check_file: the happy path ---------------------------------------------


def test_compliant_doc_has_no_findings(tmp_path):
    report = check_file(_write(tmp_path / "ok.md", COMPLIANT))
    assert report.ok
    assert report.findings == []


def test_active_alias_is_accepted_as_living(tmp_path):
    text = COMPLIANT.replace("status: living", "status: active")
    report = check_file(_write(tmp_path / "aliased.md", text))
    assert report.ok
    assert not report.findings


def test_all_canonical_statuses_parse_and_are_known():
    # Guard against a state being dropped from the vocabulary by accident.
    assert CANONICAL_STATUSES == {
        "living",
        "reference",
        "draft",
        "superseded",
        "archived",
    }


# --- check_file: the violation paths ----------------------------------------


def test_missing_frontmatter_is_flagged(tmp_path):
    report = check_file(_write(tmp_path / "bare.md", "# Just a heading\n\nText.\n"))
    assert not report.ok
    assert "MISSING_FRONTMATTER" in _codes(report)


def test_missing_required_field_is_flagged(tmp_path):
    text = "---\ntitle: No Area\nstatus: living\n---\n# x\n"
    report = check_file(_write(tmp_path / "no_area.md", text))
    assert not report.ok
    assert "MISSING_FIELD" in _codes(report)
    assert any("area" in f.message for f in report.violations)


def test_empty_required_field_is_flagged(tmp_path):
    text = "---\ntitle:\nstatus: living\narea: governance\n---\n# x\n"
    report = check_file(_write(tmp_path / "empty_title.md", text))
    assert not report.ok
    assert "MISSING_FIELD" in _codes(report)


def test_unknown_status_is_flagged(tmp_path):
    text = COMPLIANT.replace("status: living", "status: retired")
    report = check_file(_write(tmp_path / "bad_status.md", text))
    assert not report.ok
    assert "BAD_STATUS" in _codes(report)


def test_superseded_without_pointer_is_flagged(tmp_path):
    text = "---\ntitle: Old\nstatus: superseded\narea: governance\n---\n# x\n"
    report = check_file(_write(tmp_path / "superseded.md", text))
    assert not report.ok
    assert "MISSING_SUPERSEDED_BY" in _codes(report)


def test_superseded_by_on_non_superseded_is_flagged(tmp_path):
    text = (
        "---\ntitle: Misuse\nstatus: living\narea: governance\n"
        "superseded_by: other.md\n---\n# x\n"
    )
    report = check_file(_write(tmp_path / "misuse.md", text))
    assert not report.ok
    assert "SUPERSEDED_BY_MISUSE" in _codes(report)


def test_superseded_with_resolving_pointer_is_clean(tmp_path):
    _write(tmp_path / "new.md", COMPLIANT)
    text = (
        "---\ntitle: Old\nstatus: superseded\narea: governance\n"
        "superseded_by: new.md\n---\n# x\n"
    )
    report = check_file(_write(tmp_path / "old.md", text))
    assert report.ok
    assert not report.findings


def test_superseded_with_dangling_pointer_warns_but_does_not_fail(tmp_path):
    text = (
        "---\ntitle: Old\nstatus: superseded\narea: governance\n"
        "superseded_by: nowhere.md\n---\n# x\n"
    )
    report = check_file(_write(tmp_path / "dangling.md", text))
    assert report.ok  # a warning does not fail the file
    assert not report.violations
    assert "SUPERSEDED_TARGET_MISSING" in _codes(report)
    assert report.warnings


# --- directory scan: non-recursive by default (node_modules-safety) ---------


def test_directory_scan_is_non_recursive_by_default(tmp_path):
    _write(tmp_path / "top.md", COMPLIANT)
    nested = tmp_path / "node_modules"
    nested.mkdir()
    _write(nested / "buried.md", "# no frontmatter\n")

    report = check_paths([tmp_path])
    scanned = {fr.path.name for fr in report.files}
    assert scanned == {"top.md"}  # buried.md not reached
    assert report.ok


def test_recursive_scan_descends_but_skips_node_modules(tmp_path):
    _write(tmp_path / "top.md", COMPLIANT)
    sub = tmp_path / "sub"
    sub.mkdir()
    _write(sub / "child.md", COMPLIANT)
    nm = tmp_path / "node_modules"
    nm.mkdir()
    _write(nm / "dep.md", "# bad\n")

    report = check_paths([tmp_path], recursive=True)
    scanned = {fr.path.name for fr in report.files}
    assert scanned == {"top.md", "child.md"}  # node_modules skipped


# --- report aggregation + strict mode ---------------------------------------


def test_report_to_dict_and_counts(tmp_path):
    _write(tmp_path / "good.md", COMPLIANT)
    _write(tmp_path / "bad.md", "# no frontmatter\n")
    report = check_paths([tmp_path])
    payload = report.to_dict()
    assert payload["files_scanned"] == 2
    assert payload["compliant"] == 1
    assert payload["violation_count"] >= 1
    assert not report.ok


def test_strict_mode_fails_on_warnings_only(tmp_path):
    text = (
        "---\ntitle: Old\nstatus: superseded\narea: governance\n"
        "superseded_by: nowhere.md\n---\n# x\n"
    )
    _write(tmp_path / "warnonly.md", text)
    report = check_paths([tmp_path])
    assert report.passed(strict=False) is True   # warnings are advisory
    assert report.passed(strict=True) is False   # strict promotes them


# --- CLI exit-code contract -------------------------------------------------


def test_cli_returns_zero_on_compliant_dir(tmp_path, capsys):
    _write(tmp_path / "ok.md", COMPLIANT)
    rc = main([str(tmp_path)])
    assert rc == 0
    assert "PASS" in capsys.readouterr().out


def test_cli_returns_one_on_violation(tmp_path, capsys):
    _write(tmp_path / "bad.md", "# no frontmatter\n")
    rc = main([str(tmp_path)])
    assert rc == 1
    assert "FAIL" in capsys.readouterr().out


def test_cli_json_output_is_parseable(tmp_path, capsys):
    import json

    _write(tmp_path / "bad.md", "# no frontmatter\n")
    rc = main(["--json", str(tmp_path)])
    assert rc == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["passed"] is False
    assert payload["violation_count"] >= 1


def test_cli_strict_returns_one_on_warning_only(tmp_path, capsys):
    text = (
        "---\ntitle: Old\nstatus: superseded\narea: governance\n"
        "superseded_by: nowhere.md\n---\n# x\n"
    )
    _write(tmp_path / "warn.md", text)
    assert main([str(tmp_path)]) == 0          # advisory pass
    assert main(["--strict", str(tmp_path)]) == 1
    capsys.readouterr()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
