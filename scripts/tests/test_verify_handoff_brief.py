"""
Tests for scripts/verify_handoff_brief.py — the handoff-brief anchor verifier
(the structural control retiring LESSONS.md lesson 14, ticket #929).

Two layers:
  - Pure parsing/derivation helpers (no git needed).
  - End-to-end verification driven through a REAL throwaway git repo built in
    tmp_path — a valid brief PASSES; a stale (non-ancestor) SHA, a missing
    path, a drifted count, and a missing/malformed/placeholder ANCHORS block
    each FAIL. This drives the real objects through the real entry point
    (verify_brief / main), not mocks.

Also asserts the SHIPPED template carries a schema-valid ANCHORS block — the
control's guarantee that the template keeps its machine-checkable block.

scripts/ is not on the standing gate path (shared/ services/ launcher/
tests/integration/ tests/security/); run this file explicitly:
    python -m pytest scripts/tests/test_verify_handoff_brief.py -q
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

# Import the script directly by file path (scripts/ is not a package).
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "verify_handoff_brief.py"
_spec = importlib.util.spec_from_file_location("verify_handoff_brief", _SCRIPT)
assert _spec and _spec.loader
vhb = importlib.util.module_from_spec(_spec)
# Register before exec: @dataclass forward-ref resolution (PEP 563 string
# annotations under Python 3.14) reads sys.modules[cls.__module__].__dict__.
sys.modules[_spec.name] = vhb
_spec.loader.exec_module(vhb)

_TEMPLATE = _REPO_ROOT / "docs" / "governance" / "handoff-brief-template.md"


# ---------------------------------------------------------------------------
# Brief-file helper
# ---------------------------------------------------------------------------


def _brief(anchor_body: str) -> str:
    """Wrap anchor rows in a minimal brief with a ```anchors block."""
    return (
        "# Handoff brief — test\n\n"
        "## Reference SHAs + anchors\n\n"
        "```anchors\n"
        f"{anchor_body}\n"
        "```\n"
    )


def _write_brief(tmp_path: Path, anchor_body: str) -> Path:
    path = tmp_path / "brief.md"
    path.write_text(_brief(anchor_body), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# find_anchors_block / parse_anchors / parse_anchor_line (pure)
# ---------------------------------------------------------------------------


class TestFindAnchorsBlock:
    def test_finds_single_block(self) -> None:
        body, first = vhb.find_anchors_block(_brief("sha | abc1234 | x"))
        assert body.strip() == "sha | abc1234 | x"
        assert first == 6  # 1-based line of the first body line

    def test_missing_block_raises(self) -> None:
        with pytest.raises(vhb.AnchorsError, match="no ```anchors block"):
            vhb.find_anchors_block("# brief\n\nno anchors here\n")

    def test_duplicate_block_raises(self) -> None:
        text = _brief("sha | abc1234 | x") + "\n" + _brief("sha | def5678 | y")
        with pytest.raises(vhb.AnchorsError, match="2 ```anchors blocks"):
            vhb.find_anchors_block(text)

    def test_unterminated_block_raises(self) -> None:
        text = "```anchors\nsha | abc1234 | x\n"  # no closing fence
        with pytest.raises(vhb.AnchorsError, match="never closed"):
            vhb.find_anchors_block(text)


class TestParseAnchors:
    def test_skips_comments_and_blanks(self) -> None:
        body = "# header comment\n\nsha | abc1234 | main\n"
        anchors = vhb.parse_anchors(body, 1)
        assert len(anchors) == 1
        assert anchors[0].kind == "sha"
        assert anchors[0].value == "abc1234"
        assert anchors[0].label == "main"

    def test_empty_block_raises(self) -> None:
        with pytest.raises(vhb.AnchorsError, match="empty"):
            vhb.parse_anchors("# only a comment\n\n", 1)

    def test_unknown_type_raises(self) -> None:
        with pytest.raises(vhb.AnchorsError, match="unknown anchor type"):
            vhb.parse_anchors("branch | main | x", 1)

    def test_count_without_derivation_raises(self) -> None:
        with pytest.raises(vhb.AnchorsError, match="no derivation command"):
            vhb.parse_anchors("count | 5 | fragments", 1)

    def test_malformed_row_raises(self) -> None:
        with pytest.raises(vhb.AnchorsError, match="malformed anchor row"):
            vhb.parse_anchors("sha", 1)

    def test_count_derivation_preserves_internal_pipes(self) -> None:
        anchors = vhb.parse_anchors("count | 5 | frags | ls x | wc -l", 1)
        assert anchors[0].kind == "count"
        assert anchors[0].value == "5"
        assert anchors[0].derivation == "ls x | wc -l"


# ---------------------------------------------------------------------------
# run_derivation (shell)
# ---------------------------------------------------------------------------


class TestRunDerivation:
    def test_integer_output(self, tmp_path: Path) -> None:
        value, detail = vhb.run_derivation("echo 42", tmp_path)
        assert value == 42
        assert detail == ""

    def test_nonzero_exit_fails(self, tmp_path: Path) -> None:
        value, detail = vhb.run_derivation("false", tmp_path)
        assert value is None
        assert "exited" in detail

    def test_non_integer_output_fails(self, tmp_path: Path) -> None:
        value, detail = vhb.run_derivation("echo hello", tmp_path)
        assert value is None
        assert "single integer" in detail


# ---------------------------------------------------------------------------
# Real git fixture — drives verify_brief through actual git/disk
# ---------------------------------------------------------------------------


class _Repo:
    def __init__(self, path: Path, head: str, root: str, other: str, commits: int) -> None:
        self.path = path
        self.head = head          # ancestor of main (HEAD)
        self.root = root          # ancestor of main (first commit)
        self.other = other        # a real commit NOT on main (non-ancestor)
        self.commits = commits    # commit count on main


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> _Repo:
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(
        ["git", "init", "-b", "main", str(r)],
        capture_output=True,
        text=True,
        check=True,
    )
    _git(r, "config", "user.email", "t@example.com")
    _git(r, "config", "user.name", "Test")
    _git(r, "config", "commit.gpgsign", "false")

    (r / "README.md").write_text("v1", encoding="utf-8")
    _git(r, "add", "README.md")
    _git(r, "commit", "-m", "c1")
    root = _git(r, "rev-parse", "HEAD")

    frags = r / "docs" / "journal_fragments"
    frags.mkdir(parents=True)
    for i in range(3):
        (frags / f"frag{i}.md").write_text("x", encoding="utf-8")
    _git(r, "add", "docs")
    _git(r, "commit", "-m", "c2")
    head = _git(r, "rev-parse", "HEAD")

    # A real commit that exists but is NOT an ancestor of main.
    _git(r, "checkout", "-b", "other")
    (r / "OTHER.md").write_text("y", encoding="utf-8")
    _git(r, "add", "OTHER.md")
    _git(r, "commit", "-m", "divergent")
    other = _git(r, "rev-parse", "HEAD")
    _git(r, "checkout", "main")

    return _Repo(r, head=head, root=root, other=other, commits=2)


def _valid_body(repo: _Repo) -> str:
    return "\n".join(
        [
            f"sha    | {repo.head} | main HEAD",
            f"sha    | {repo.root} | first commit",
            "path   | README.md | tracked file",
            "path   | docs/journal_fragments | fragments dir",
            f"count  | {repo.commits} | commits on main | git rev-list --count HEAD",
            "count  | 3 | journal fragments | find docs/journal_fragments -name '*.md' | wc -l",
            "ticket | #929 | this build",
        ]
    )


class TestValidBrief:
    def test_valid_brief_passes(self, repo: _Repo, tmp_path: Path) -> None:
        brief = _write_brief(tmp_path, _valid_body(repo))
        report = vhb.verify_brief(brief, repo.path, "main")
        assert report.ok, vhb.render_report(report)
        assert report.counts()["FAIL"] == 0
        assert report.counts()["PASS"] == 7


class TestDriftFails:
    def test_stale_non_ancestor_sha_fails(self, repo: _Repo, tmp_path: Path) -> None:
        body = f"sha | {repo.other} | a commit not on main"
        report = vhb.verify_brief(_write_brief(tmp_path, body), repo.path, "main")
        assert not report.ok
        assert report.results[0].status == "FAIL"
        assert "NOT an ancestor" in report.results[0].detail

    def test_unresolvable_sha_fails(self, repo: _Repo, tmp_path: Path) -> None:
        body = "sha | deadbeef | never existed"
        report = vhb.verify_brief(_write_brief(tmp_path, body), repo.path, "main")
        assert not report.ok
        assert report.results[0].status == "FAIL"

    def test_missing_path_fails(self, repo: _Repo, tmp_path: Path) -> None:
        body = "path | docs/does_not_exist.md | gone"
        report = vhb.verify_brief(_write_brief(tmp_path, body), repo.path, "main")
        assert not report.ok
        assert "MISSING" in report.results[0].detail

    def test_absolute_path_rejected(self, repo: _Repo, tmp_path: Path) -> None:
        body = "path | C:/Windows/system32 | absolute"
        report = vhb.verify_brief(_write_brief(tmp_path, body), repo.path, "main")
        assert not report.ok
        assert "repo-relative" in report.results[0].detail

    def test_wrong_count_fails(self, repo: _Repo, tmp_path: Path) -> None:
        body = "count | 99 | commits on main | git rev-list --count HEAD"
        report = vhb.verify_brief(_write_brief(tmp_path, body), repo.path, "main")
        assert not report.ok
        assert "drifted" in report.results[0].detail
        assert f"derived {repo.commits}" in report.results[0].detail

    def test_correct_count_passes(self, repo: _Repo, tmp_path: Path) -> None:
        body = f"count | {repo.commits} | commits | git rev-list --count HEAD"
        report = vhb.verify_brief(_write_brief(tmp_path, body), repo.path, "main")
        assert report.ok

    def test_placeholder_value_fails(self, repo: _Repo, tmp_path: Path) -> None:
        body = "sha | <main HEAD sha> | placeholder left in"
        report = vhb.verify_brief(_write_brief(tmp_path, body), repo.path, "main")
        assert not report.ok
        assert "placeholder" in report.results[0].detail


class TestBlockFaultsFail:
    def test_missing_anchors_block_fails(self, repo: _Repo, tmp_path: Path) -> None:
        brief = tmp_path / "b.md"
        brief.write_text("# brief\n\nno anchors block at all\n", encoding="utf-8")
        report = vhb.verify_brief(brief, repo.path, "main")
        assert not report.ok
        assert report.fatal is not None
        assert "no ```anchors block" in report.fatal

    def test_malformed_block_fails(self, repo: _Repo, tmp_path: Path) -> None:
        body = "count | 5 | fragments"  # count with no derivation
        report = vhb.verify_brief(_write_brief(tmp_path, body), repo.path, "main")
        assert not report.ok
        assert report.fatal is not None
        assert "derivation" in report.fatal

    def test_empty_block_fails(self, repo: _Repo, tmp_path: Path) -> None:
        body = "# only a comment"
        report = vhb.verify_brief(_write_brief(tmp_path, body), repo.path, "main")
        assert not report.ok
        assert report.fatal is not None
        assert "empty" in report.fatal


# ---------------------------------------------------------------------------
# Ticket anchors + optional board resolver (degrade-cleanly contract)
# ---------------------------------------------------------------------------


class TestTicketAnchors:
    def test_wellformed_ticket_passes_without_board(self, repo: _Repo, tmp_path: Path) -> None:
        report = vhb.verify_brief(_write_brief(tmp_path, "ticket | #929 | x"), repo.path, "main")
        assert report.ok
        assert report.results[0].status == "PASS"

    def test_malformed_ticket_fails(self, repo: _Repo, tmp_path: Path) -> None:
        report = vhb.verify_brief(_write_brief(tmp_path, "ticket | 929 | x"), repo.path, "main")
        assert not report.ok
        assert "malformed ticket" in report.results[0].detail

    def test_board_exists_passes(self, repo: _Repo, tmp_path: Path) -> None:
        report = vhb.verify_brief(
            _write_brief(tmp_path, "ticket | #929 | x"), repo.path, "main",
            board_resolver=lambda n: True,
        )
        assert report.results[0].status == "PASS"
        assert "exists" in report.results[0].detail

    def test_board_missing_warns_not_fails(self, repo: _Repo, tmp_path: Path) -> None:
        report = vhb.verify_brief(
            _write_brief(tmp_path, "ticket | #929 | x"), repo.path, "main",
            board_resolver=lambda n: False,
        )
        assert report.ok  # a missing ticket must never FAIL grounding
        assert report.results[0].status == "WARN"

    def test_board_unreachable_warns_not_fails(self, repo: _Repo, tmp_path: Path) -> None:
        report = vhb.verify_brief(
            _write_brief(tmp_path, "ticket | #929 | x"), repo.path, "main",
            board_resolver=lambda n: None,
        )
        assert report.ok
        assert report.results[0].status == "WARN"

    def test_board_error_warns_not_fails(self, repo: _Repo, tmp_path: Path) -> None:
        def boom(_n: int) -> bool | None:
            raise RuntimeError("connection refused")

        report = vhb.verify_brief(
            _write_brief(tmp_path, "ticket | #929 | x"), repo.path, "main",
            board_resolver=boom,
        )
        assert report.ok
        assert report.results[0].status == "WARN"


# ---------------------------------------------------------------------------
# CLI entry point (main) — exit codes
# ---------------------------------------------------------------------------


class TestMain:
    def test_valid_brief_exit_zero(self, repo: _Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        brief = _write_brief(tmp_path, _valid_body(repo))
        rc = vhb.main([str(brief), "--repo", str(repo.path), "--main-ref", "main"])
        assert rc == 0
        assert "RESULT: PASS" in capsys.readouterr().out

    def test_drift_exit_one(self, repo: _Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        brief = _write_brief(tmp_path, "path | docs/missing.md | gone")
        rc = vhb.main([str(brief), "--repo", str(repo.path)])
        assert rc == 1
        assert "RESULT: FAIL" in capsys.readouterr().out

    def test_missing_brief_exit_two(self, tmp_path: Path) -> None:
        rc = vhb.main([str(tmp_path / "nope.md")])
        assert rc == 2

    def test_check_board_degrades_to_warning(self, repo: _Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        # --check-board with no network client → every ticket WARNs, never fails.
        brief = _write_brief(tmp_path, "ticket | #929 | x")
        rc = vhb.main([str(brief), "--repo", str(repo.path), "--check-board"])
        assert rc == 0
        assert "unreachable" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# The shipped template carries a schema-valid ANCHORS block (the control's
# guarantee that the template keeps its machine-checkable block).
# ---------------------------------------------------------------------------


class TestShippedTemplate:
    def test_template_has_wellformed_anchors_block(self) -> None:
        text = _TEMPLATE.read_text(encoding="utf-8")
        body, first = vhb.find_anchors_block(text)
        anchors = vhb.parse_anchors(body, first)
        kinds = {a.kind for a in anchors}
        assert {"sha", "path", "count", "ticket"} <= kinds
        # every count row carries a derivation command
        assert all(a.derivation for a in anchors if a.kind == "count")

    def test_template_placeholders_fail_verification(self, tmp_path: Path) -> None:
        """Running the verifier on the raw template FAILS — its anchors are
        placeholders. You verify a FILLED brief, never the template."""
        report = vhb.verify_brief(_TEMPLATE, tmp_path, "main")
        assert not report.ok
