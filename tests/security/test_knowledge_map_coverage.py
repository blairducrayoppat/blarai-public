"""Lock for the knowledge-map coverage check (#1744).

Only ``test_real_repo_is_fully_covered`` touches the real tree.  Every other
test builds a small SYNTHETIC tree in tmp_path (its own ``git init``, because
discovery uses ``git ls-files``) and asserts the specific exit code AND message
it is about.  The toggle tests prove locks bite: a checker with one guard
removed must pass the violation the guard exists to catch.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "check_knowledge_map_coverage.py"
UNMAPPED = "knowledge_map_unmapped.yaml"
GOOD_REASON = "not yet mapped: batch 5 candidate"


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _run(root: Path, script: Path = SCRIPT) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-I", str(script), "--root", str(root)],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
    )


class Tree:
    def __init__(self, root: Path, git: bool = True) -> None:
        self.root = root
        self.r = root / "docs" / "research"
        self.r.mkdir(parents=True)
        self.git = git
        if git:
            _git(root, "init", "-q")

    def put(self, rel: str, text: str = "x\n", track: bool = True) -> None:
        p = self.r / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode("utf-8"))
        if self.git and track:
            _git(self.root, "add", "--", f"docs/research/{rel}")

    def map(self, text: str, name: str = "KNOWLEDGE_MAP.md") -> None:
        self.put(name, text)

    def unmapped(self, body: str = "unmapped: []\n") -> None:
        self.put(UNMAPPED, body)

    def run(self) -> subprocess.CompletedProcess:
        return _run(self.root)


@pytest.fixture()
def tree(tmp_path: Path) -> Tree:
    """study-a.md cited by the map; empty exceptions list; exit 0."""
    t = Tree(tmp_path)
    t.map("| `docs/research/study-a.md` | card |\n")
    t.put("study-a.md")
    t.unmapped()
    return t


def entry(path: str, reason: str = GOOD_REASON) -> str:
    return f"  - path: {path}\n    reason: {reason}\n"


# ---------------------------------------------------------------- real tree

def test_real_repo_is_fully_covered() -> None:
    r = _run(REPO)
    assert r.returncode == 0, r.stdout + r.stderr


# ----------------------------------------------------------------- baseline

def test_baseline_synthetic_tree_passes(tree: Tree) -> None:
    r = tree.run()
    assert r.returncode == 0, r.stdout
    assert "1 studies found" in r.stdout


def test_two_maps_do_not_count_as_studies(tree: Tree) -> None:
    tree.map("batch two\n", name="KNOWLEDGE_MAP_BATCH2.md")
    r = tree.run()
    assert r.returncode == 0, r.stdout
    assert "1 studies found" in r.stdout


def test_no_map_files_is_malformed(tree: Tree) -> None:
    _git(tree.root, "rm", "-q", "-f", "docs/research/KNOWLEDGE_MAP.md")
    r = tree.run()
    assert r.returncode == 3 and "no KNOWLEDGE_MAP*.md files found" in r.stdout


# ---------------------------------------------------- exit 1 / git discovery

def test_committed_uncited_study_exits_1_naming_it(tree: Tree) -> None:
    tree.put("study-b.md")
    r = tree.run()
    assert r.returncode == 1
    assert "  - study-b.md" in r.stdout and "  - study-a.md" not in r.stdout


def test_untracked_draft_is_ignored(tree: Tree) -> None:
    tree.put("draft-from-another-session.md", track=False)
    r = tree.run()
    assert r.returncode == 0, r.stdout
    assert "draft-from-another-session" not in r.stdout


def test_without_git_filesystem_is_scanned_and_says_so(tmp_path: Path) -> None:
    t = Tree(tmp_path, git=False)
    t.map("`study-a.md`\n")
    t.put("study-a.md")
    t.put("study-b.md")
    t.unmapped()
    r = t.run()
    assert r.returncode == 1
    assert "not a git repository" in r.stdout and "study-b.md" in r.stdout


def test_listed_study_passes_and_is_counted(tree: Tree) -> None:
    tree.put("study-b.md")
    tree.unmapped("unmapped:\n" + entry("study-b.md"))
    r = tree.run()
    assert r.returncode == 0, r.stdout
    assert "listed as unmapped (with reason): 1" in r.stdout


def test_listed_untracked_file_is_tolerated(tree: Tree) -> None:
    tree.put("study-b.md", track=False)
    tree.unmapped("unmapped:\n" + entry("study-b.md"))
    assert tree.run().returncode == 0


# --------------------------------------------------------------- unknown types

@pytest.mark.parametrize("name", ["notes.txt", "analysis.ipynb", "paper.pdf", "page.htm", "data.json"])
def test_unknown_file_types_are_studies(tree: Tree, name: str) -> None:
    tree.put(name)
    r = tree.run()
    assert r.returncode == 1 and name in r.stdout and "unrecognised file type" in r.stdout


def test_folder_ending_files_without_sibling_page_is_a_study(tree: Tree) -> None:
    tree.put("eval_files/a.png")
    r = tree.run()
    assert r.returncode == 1 and "  - eval_files" in r.stdout


def test_files_folder_with_sibling_page_is_excluded_but_the_page_is_a_study(tree: Tree) -> None:
    tree.put("eval_files/a.png")
    tree.put("eval.htm")
    r = tree.run()
    assert r.returncode == 1
    assert "eval.htm" in r.stdout and "eval_files" not in r.stdout


def test_documented_exclusions_need_no_citation(tree: Tree) -> None:
    tree.put("fixtures/a.json")
    tree.put("docset-manifest-2026-07.json")
    r = tree.run()
    assert r.returncode == 0, r.stdout
    assert "1 studies found" in r.stdout


def test_map_prefix_is_excluded_only_for_md_files(tree: Tree) -> None:
    """Only .md files are read as maps, so a KNOWLEDGE_MAP* html file or folder is a study like any other."""
    tree.put("KNOWLEDGE_MAP_draft.html")
    tree.put("KNOWLEDGE_MAP_extra/a.md")
    r = tree.run()
    assert r.returncode == 1, r.stdout
    assert "KNOWLEDGE_MAP_draft.html" in r.stdout and "KNOWLEDGE_MAP_extra" in r.stdout


def test_non_ascii_names_do_not_crash_the_report(tree: Tree) -> None:
    tree.unmapped("unmapped:\n" + entry("\u65e5-gone.md"))
    r = tree.run()
    assert r.returncode == 2, r.stdout
    assert "Traceback" not in r.stdout and "Traceback" not in (r.stderr or "")


def test_depth_below_one_belongs_to_the_folder(tree: Tree) -> None:
    tree.put("fold/sources/deep.md")
    tree.map("`docs/research/fold/`\n", name="KNOWLEDGE_MAP_B.md")
    r = tree.run()
    assert r.returncode == 0 and "2 studies found" in r.stdout


# ------------------------------------------------------------ exit 2 (stale)

def test_stale_entry_file_gone(tree: Tree) -> None:
    tree.unmapped("unmapped:\n" + entry("gone-2026.md"))
    r = tree.run()
    assert r.returncode == 2 and "gone-2026.md: the file or folder no longer exists" in r.stdout


def test_stale_entry_now_cited(tree: Tree) -> None:
    tree.unmapped("unmapped:\n" + entry("study-a.md"))
    r = tree.run()
    assert r.returncode == 2 and "study-a.md: now cited" in r.stdout


def test_stale_entry_excluded_by_rule(tree: Tree) -> None:
    tree.put("fixtures/a.json")
    tree.unmapped("unmapped:\n" + entry("fixtures"))
    r = tree.run()
    assert r.returncode == 2 and "fixtures: is tracked but excluded" in r.stdout


def test_exit_1_beats_exit_2(tree: Tree) -> None:
    tree.put("study-b.md")
    tree.unmapped("unmapped:\n" + entry("gone-2026.md"))
    r = tree.run()
    assert r.returncode == 1 and "gone-2026.md" in r.stdout


# ------------------------------------------------------------ exit 3 (input)

@pytest.mark.parametrize("body, message", [
    ("this is not yaml\n", "must begin with 'unmapped:'"),
    ("unmapped:\n  - path: a.md\n", "reason is missing or empty"),
    ("unmapped:\n  - path: a.md\n    reason: " + GOOD_REASON + "\n    bogus: 1\n", "unknown key 'bogus'"),
    ("unmapped:\n  - path: a.md\n    reason: \"" + GOOD_REASON + "\n", "bad double-quoted value"),
    ("unmapped:\n  - path: a.md\n    reason: 'oops\n", "bad single-quoted value"),
    ("unmapped:\n" + entry("a.md") + entry("A.md"), "listed twice"),
    ("unmapped:\n" + entry("a.md", "x"), "reason must be a real sentence"),
    ("unmapped:\n" + entry("a.md", "todo"), "reason must be a real sentence"),
    ("unmapped:\n" + entry("a.md", "too short"), "reason must be a real sentence"),
    ("unmapped:\n" + entry("a.md", "Not Applicable"), "reason must be a real sentence"),
    ("unmapped:\n" + entry("fold/child.md"), "not a path inside it"),
    ("unmapped: []\n" + entry("a.md"), "entries after 'unmapped: []'"),
    ("", "empty file"),
])
def test_malformed_yaml_exits_3_with_message(tree: Tree, body: str, message: str) -> None:
    tree.unmapped(body)
    r = tree.run()
    assert r.returncode == 3, r.stdout
    assert message in r.stdout


def test_missing_yaml_exits_3(tree: Tree) -> None:
    (tree.r / UNMAPPED).unlink()
    _git(tree.root, "rm", "-q", "--cached", f"docs/research/{UNMAPPED}")
    r = tree.run()
    assert r.returncode == 3 and "is missing" in r.stdout


@pytest.mark.parametrize("body", [
    "﻿unmapped:\n" + entry("study-b.md"),                                  # BOM
    "unmapped:\n- path: study-b.md\n  reason: " + GOOD_REASON + "\n",          # same indent
    "unmapped:\r\n" + entry("study-b.md").replace("\n", "\r\n"),               # CRLF
    "unmapped:\n  - path: study-b.md\n    reason: \"" + GOOD_REASON + "\"  # why\n",  # quoted + comment
    "unmapped:  # top comment\n" + entry("study-b.md") + "    ticket: '#1750'\n",
    "# lead comment\nunmapped:\n\n" + entry("study-b.md"),
])
def test_yaml_ordinary_shapes_are_accepted(tree: Tree, body: str) -> None:
    tree.put("study-b.md")
    tree.unmapped(body)
    r = tree.run()
    assert r.returncode == 0, r.stdout


# ------------------------------------------------- citations that must NOT count

def _uncited(tree: Tree, map_text: str) -> subprocess.CompletedProcess:
    tree.put("study-b.md")
    tree.map(map_text, name="KNOWLEDGE_MAP_B.md")
    return tree.run()


@pytest.mark.parametrize("text", [
    "```\ndocs/research/study-b.md\n```\n",
    "~~~\nstudy-b.md\n~~~\n",
    "````\n```\nstudy-b.md\n````\n",   # 3 does not close 4: the citation after it is still inside
    "```\n```bash\nstudy-b.md\n```\n",   # an info string makes it not a closing fence
    "```\nstudy-b.md\n",                                                      # unclosed runs to end
    "<!-- study-b.md -->\n",
    "<!--\nstudy-b.md\n-->\n",
    "[other](../design/study-b.md) and `docs/design/study-b.md`\n",          # same basename
    "docs/research/sub/study-b.md\n",
    "see study-b.md.bak and study-b.md-old and xstudy-b.md\n",                # boundaries
    "https://example.com/docs/research/study-b.md\n",
])
def test_non_citations_leave_the_study_uncovered(tree: Tree, text: str) -> None:
    r = _uncited(tree, text)
    assert r.returncode == 1, r.stdout
    assert "  - study-b.md" in r.stdout


def test_fence_closes_correctly_and_later_citation_counts(tree: Tree) -> None:
    r = _uncited(tree, "````\nx\n````\n\n`study-b.md`\n")
    assert r.returncode == 0, r.stdout


def test_indented_block_counts_as_a_citation_by_documented_choice(tree: Tree) -> None:
    r = _uncited(tree, "- item\n\n    `study-b.md`\n")
    assert r.returncode == 0, r.stdout


@pytest.mark.parametrize("text", [
    "`docs/research/study-b.md`", "`study-b.md`", "[x](./study-b.md)", "[x](../research/study-b.md)",
    "[x](/docs/research/study-b.md)", "[x](../../docs/research/study-b.md#sec)", "`STUDY-B.MD`",
    "docs\\research\\study-b.md", "see study-b.md.", "(study-b.md)",
])
def test_ordinary_citation_shapes_count(tree: Tree, text: str) -> None:
    r = _uncited(tree, text + "\n")
    assert r.returncode == 0, r.stdout


def test_encoded_and_escaped_names_count(tree: Tree) -> None:
    tree.put("My Study & Co.md")
    tree.map("[x](My%20Study%20&amp;%20Co.md)\n", name="KNOWLEDGE_MAP_B.md")
    assert tree.run().returncode == 0


# ------------------------------------------------------------- folder citations

def test_folder_cited_by_name_with_slash(tree: Tree) -> None:
    tree.put("fold/a.md")
    tree.map("`docs/research/fold/`\n", name="KNOWLEDGE_MAP_B.md")
    assert tree.run().returncode == 0


def test_citation_of_existing_child_covers_the_folder(tree: Tree) -> None:
    tree.put("fold/a.md")
    tree.map("`docs/research/fold/a.md`\n", name="KNOWLEDGE_MAP_B.md")
    assert tree.run().returncode == 0


def test_citation_of_nonexistent_child_does_not_cover_the_folder(tree: Tree) -> None:
    tree.put("fold/a.md")
    tree.map("`docs/research/fold/does-not-exist.md`\n", name="KNOWLEDGE_MAP_B.md")
    r = tree.run()
    assert r.returncode == 1 and "  - fold" in r.stdout


def _prefix_pair(tree: Tree) -> None:
    """Real-tree shape: folder X and file X-10.md; only the file is cited."""
    tree.put("wcc-2026-10/a.md")
    tree.put("wcc-2026-10-10.md")
    tree.map("`docs/research/wcc-2026-10-10.md`\n", name="KNOWLEDGE_MAP_B.md")


def test_folder_is_not_covered_by_citation_of_prefix_sharing_file(tree: Tree) -> None:
    _prefix_pair(tree)
    r = tree.run()
    assert r.returncode == 1
    assert "  - wcc-2026-10\n" in r.stdout and "wcc-2026-10-10.md" not in r.stdout


# ------------------------------------------------------------------ mutants

def _with_mutant(tree: Tree, tmp_path: Path, old: str, new: str) -> subprocess.CompletedProcess:
    src = SCRIPT.read_text(encoding="utf-8")
    assert src.count(old) == 1, "mutation site moved; update the toggle test"
    broken = tmp_path / "broken_checker.py"
    broken.write_text(src.replace(old, new), encoding="utf-8")
    return _run(tree.root, broken)


def test_toggle_uncovered_detection_off_passes_the_violation(tree: Tree, tmp_path: Path) -> None:
    tree.put("study-b.md")
    assert tree.run().returncode == 1
    r = _with_mutant(tree, tmp_path, "    uncovered = [u for u in studies\n",
                     "    uncovered = [u for u in studies if False\n")
    assert r.returncode == 0


def test_toggle_end_boundary_guard_off_covers_folder_wrongly(tree: Tree, tmp_path: Path) -> None:
    _prefix_pair(tree)
    assert tree.run().returncode == 1
    r = _with_mutant(tree, tmp_path, '+ r"(?![\\w-]|\\.\\w)")', '+ r"")')
    assert r.returncode == 0


def test_toggle_excluded_stale_branch_off_misses_it(tree: Tree, tmp_path: Path) -> None:
    tree.put("fixtures/a.json")
    tree.unmapped("unmapped:\n" + entry("fixtures"))
    assert tree.run().returncode == 2
    r = _with_mutant(tree, tmp_path, "        elif key in units and key not in study_keys:\n",
                     "        elif False:\n")
    assert r.returncode == 0


def test_toggle_map_exclusion_off_makes_maps_studies(tree: Tree, tmp_path: Path) -> None:
    assert tree.run().returncode == 0
    r = _with_mutant(tree, tmp_path,
                     '    if (not u.is_dir) and u.name.upper().startswith("KNOWLEDGE_MAP") and low.endswith(".md"):\n        return True\n', "")
    assert r.returncode == 1


def test_toggle_no_maps_check_off_goes_silent(tree: Tree, tmp_path: Path) -> None:
    _git(tree.root, "rm", "-q", "-f", "docs/research/KNOWLEDGE_MAP.md")
    assert tree.run().returncode == 3
    r = _with_mutant(tree, tmp_path, "        if not map_units:\n            raise Malformed",
                     "        if False:\n            raise Malformed")
    assert r.returncode != 3
