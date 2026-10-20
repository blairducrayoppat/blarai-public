"""Gate lock: no file in the research scope carries a tracker reference, a fixture name embedding one, a session token, or a file or
folder name embedding a tracker number; files banked before the lock are frozen per file and may only fall (the ratchet).

WHAT FAILURE THIS EXISTS FOR
----------------------------
Research records (probe directories, performance JSON, marked performance-log entries, marked journal fragments and the pre-flight
checklist) are published as measurement records. A tracker reference, a fixture named after one or a session token ties a public
record to a private work queue and was found in banked records by review. ``scripts/research_tracker_lock.py`` is the single
recognition and ratchet; this file drives it on scratch git repositories, each pattern and each reading with a planted finding
beside a clean twin, so a control that stops seeing fails here before it fails in public.

WHAT IS LOCKED
--------------
* each content pattern (reference, fixture prefix, session token) fires on a planted finding and stays quiet on its clean twin,
  including a number glued to a word, a letter or an underscore (findings) and the sanctioned names (clean);
* the readings hide nothing: JSON escapes, HTML numeric entities, percent-encoding, gzip, UTF-16 and a colour code;
* the upstream exemption passes the allowlisted repository forms and refuses a bare number and a slug outside the allowlist;
* the name rule: a case table for dates, plain years, versions (the five benchmark harnesses' own name formats, read from their source, pass; a tracker
  number in the same position fails) and month-day stamps;
* the scope: a probe directory, a performance JSON, a marked log entry, a marked fragment and a front-matter opt-in are scanned;
  unmarked entries, unmarked fragments, top-level probe files and nested performance files are not;
* opt-in parsing: tolerated spellings parse, a key-shaped line that does not parse is a finding, prose and fenced mentions are not;
* log entry boundaries: a heading inside a fenced block does not end an entry; a fence closes on its own character and length;
* the index is the subject: an unstaged edit changes neither a finding nor a clean result, and the baseline is read from the index;
* the ratchet: a count above the baseline fails, a count below it fails until lowered, a new file fails, a gone file fails;
  ``--write-baseline`` refuses to raise, and ``--add-existing-names`` takes only main's tip or the merge base as its base;
* the reference control: a grown baseline passes alone and fails against the reference; on a branch the reference is the merge
  base, on the main line it is the minimum of the baseline history; an unresolvable ref exits 2;
* the landing shape: two intermediate baseline versions on the first-parent line (a fast-forward) fail, a no-ff landing passes, and the
  doctrine line names the lock's two files;
* a name entry written by ``--add-existing-names`` for an already-tracked path passes the reference, a new path is refused;
* a shallow clone and an empty index exit 2;
* output names the pattern and never the matched digits, and masks every run of four or more digits that is not a date;
* a missing git fails; it never skips;
* the real repository index passes ``--check`` against main.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import research_tracker_lock as rtl  # noqa: E402

H = "#"  # kept out of literals so no number follows it in this file
MARK = "<!-- research-scope: tracker-free -->"
FM = "---\nresearch-scope: tracker-free\n---\n"
ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
                   cwd=root, check=True, capture_output=True, env=ENV)


def make_repo(tmp_path: Path, files: dict[str, str | bytes], commit: bool = True, name: str = "repo") -> Path:
    root = tmp_path / name
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    put(root, files)
    git(root, "add", "--", *files)
    if commit:
        git(root, "commit", "-q", "-m", "x")
    return root


def put(root: Path, files: dict[str, str | bytes]) -> None:
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))


def run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "research_tracker_lock.py"), "--root", str(root), *args],
                          capture_output=True, text=True, env=ENV)


def results(root: Path) -> dict[str, rtl.FileResult]:
    return rtl.scan_index(root)


def counts(root: Path, path: str) -> dict[str, int]:
    return results(root)[path].counts


PROBE = "tools/probes/alpha/run.py"
PERF = "docs/performance/rec_2026-10-15.json"


# ---- patterns -------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,pattern", [
    (f"see {H}1406 for it", "tracker-ref"),
    (f"({H}123)", "tracker-ref"),
    (f"{H}99999 end", "tracker-ref"),
    ("fixture p1406-a here", "fixture-prefix"),
    ("fixture P1406_b here", "fixture-prefix"),
    ("fixture p12345-a here", "fixture-prefix"),
    ("token S1406-x here", "session-token"),
    ("token S12345-x here", "session-token"),
])
def test_each_pattern_fires(tmp_path: Path, text: str, pattern: str) -> None:
    root = make_repo(tmp_path, {PROBE: text + "\n"})
    assert counts(root, PROBE)[pattern] == 1
    assert rtl.violations(results(root), {"counts": {}, "names": []})


@pytest.mark.parametrize("text", [
    f"colour &{H}1406; entity",           # numeric entity marker, not a reference
    f"{H}12 and {H}1234567 and {H}abc",   # too short, too long, not digits
    f"{H}{H}1406",                        # doubled marker
    "fx-a run-20261015-1 feat/topic",     # the sanctioned names
    "xp1406-a and ap1406_b",              # prefix glued to a letter
    "S-1-5-21-0-0-0-500",                 # a SID is not a session token
    "AS1406- glued",                      # token glued to a letter
    "p123-a and p123456",                 # too few digits, no separator
])
def test_clean_twins_pass(tmp_path: Path, text: str) -> None:
    root = make_repo(tmp_path, {PROBE: text + "\n"})
    assert not any(counts(root, PROBE)[p] for p in rtl.CONTENT_PATTERNS)
    assert rtl.violations(results(root), {"counts": {}, "names": []}) == []


def test_session_token_is_case_sensitive_and_fixture_prefix_is_not(tmp_path: Path) -> None:
    root = make_repo(tmp_path, {PROBE: "s1406-x and P1406-y\n"})
    c = counts(root, PROBE)
    assert c["session-token"] == 0 and c["fixture-prefix"] == 1


# ---- readings -------------------------------------------------------------------------------------------------------------------

def test_json_unicode_escape_is_seen(tmp_path: Path) -> None:
    root = make_repo(tmp_path, {PERF: '{"note": "see \\u00231406"}\n'})
    assert counts(root, PERF)["tracker-ref"] == 1


def test_json_escaped_prefix_is_seen(tmp_path: Path) -> None:
    root = make_repo(tmp_path, {PERF: '{"fx": "\\u00701406-a"}\n'})
    assert counts(root, PERF)["fixture-prefix"] == 1


def test_html_numeric_entities_are_seen(tmp_path: Path) -> None:
    root = make_repo(tmp_path, {PROBE: "<p>&#35;1406 and &#x23;1407</p>\n"})
    assert counts(root, PROBE)["tracker-ref"] == 2


def test_percent_encoded_marker_is_seen(tmp_path: Path) -> None:
    root = make_repo(tmp_path, {PROBE: "link%20%231406\n"})
    assert counts(root, PROBE)["tracker-ref"] == 1


# ---- upstream exemption ---------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    f"microsoft/mxc{H}1485",
    f"microsoft/mxc {H}1406",
    f"microsoft/mxc PR {H}1406",
    f"microsoft/mxc issue {H}1406",
    f"anthropics/sandbox-runtime{H}723",
    f"nolabs-ai/nono{H}2125",
    f"openvinotoolkit/openvino{H}4139",
    f"openvinotoolkit/openvino.genai{H}4139",
    f"huggingface/optimum-intel{H}77",
    f"Microsoft/MXC {H}1406",
    f"see (microsoft/mxc PR {H}1406) upstream",
    "github.com/microsoft/mxc/pull/1485 and github.com/nolabs-ai/nono/issues/2125",
])
def test_upstream_forms_pass(tmp_path: Path, text: str) -> None:
    root = make_repo(tmp_path, {PROBE: text + "\n"})
    assert counts(root, PROBE)["tracker-ref"] == 0


@pytest.mark.parametrize("text", [
    f"{H}1406",
    f"PR {H}1406",
    f"microsoft/other{H}1406",
    f"evil-microsoft/mxc{H}1406",
    f"notmicrosoft/mxc {H}1406",
    f"someone/else PR {H}1406",
    f"microsoft/mxc and {H}1406",
    f"microsoft/mxc{H}1485 then {H}1406",
    f"microsoft/mxc/{H}1406",
    f"see BlarAI{H}1786 here",
    f"ticket{H}1786",
    f"fixed in issue{H}1786",
    f"PR{H}1786",
    f"x_{H}1786",
    f"{H}1786a",
    f"{H}1786_fix",
    f"{H}17860",
])
def test_bare_and_foreign_forms_are_findings(tmp_path: Path, text: str) -> None:
    root = make_repo(tmp_path, {PROBE: text + "\n"})
    assert counts(root, PROBE)["tracker-ref"] >= 1


def test_upstream_form_split_across_lines_is_not_exempt(tmp_path: Path) -> None:
    root = make_repo(tmp_path, {PROBE: f"microsoft/mxc\n{H}1406\n"})
    assert counts(root, PROBE)["tracker-ref"] == 1


# ---- name-number: case table ----------------------------------------------------------------------------------------------------

NAME_TABLE = [
    ("tools/probes/mxc_1406/run.py", True),
    ("tools/probes/alpha/probe_1406.py", True),
    ("tools/probes/alpha/sub/1406/x.py", True),
    ("tools/probes/alpha/run.py", False),
    ("tools/probes/alpha/run_2026-10-15.json", False),
    ("tools/probes/alpha/run_20261015.json", False),
    ("tools/probes/alpha/run_20261015_1.json", False),
    ("tools/probes/alpha/run-2026.py", True),
    ("tools/probes/alpha/run_2001.py", True),
    ("tools/probes/2050_probe/x.py", True),
    ("tools/probes/alpha/ov2026_1.py", False),
    ("tools/probes/alpha/ov_2026.4.0.json", False),
    ("tools/probes/alpha/ov1406_2_1_0.py", True),
    ("tools/probes/alpha/run2026_2_1_0.py", True),
    ("tools/probes/alpha/x_2026_2.py", True),
    ("tools/probes/alpha/ov2026.py", True),
    ("tools/probes/alpha/xov2026_2.py", True),
    ("tools/probes/alpha/OpenVINO2026_2_1.py", False),
    ("tools/probes/alpha/ov2026-2.py", True),
    ("tools/probes/alpha/x_2026-13-01.py", True),
    ("tools/probes/alpha/x_2026-10.py", False),
    ("tools/probes/alpha/x_2026_10_05.py", False),
    ("tools/probes/alpha/x_2026.10.05.py", False),
    ("tools/probes/alpha/x_2026-1005.py", True),
    ("tools/probes/alpha/run_17860.py", False),
    ("tools/probes/alpha/run_1999-10-15.py", False),
    ("tools/probes/alpha/run_1999.py", True),
    ("tools/probes/alpha/run_1906_2026-10-15.py", True),
    ("tools/probes/alpha/run_1015.py", True),
    ("tools/probes/alpha/run_14060.py", False),
    ("tools/probes/alpha/run_140.py", False),
    ("tools/probes/alpha/run_1406x.py", True),
    ("tools/probes/alpha/benchmark_2026-05-22_15-55-48.json", False),
    ("docs/performance/probe_pr1406_2026-07-16_21-10-31.json", True),
    ("docs/performance/rec_2026-10-15.json", False),
    ("docs/performance/rec_1406.json", True),
    ("docs/performance/sub/rec_1406.json", False),
    ("tools/probes/solo_1406.py", False),
]


@pytest.mark.parametrize("path,expected", NAME_TABLE)
def test_name_number_case_table(tmp_path: Path, path: str, expected: bool) -> None:
    root = make_repo(tmp_path, {path: "x = 1\n"})
    got = results(root)
    if path in got:
        assert bool(got[path].counts[rtl.NAME_PATTERN]) is expected
    else:
        assert expected is False


def test_name_number_ignores_directories_above_the_scope(tmp_path: Path) -> None:
    path = "docs/journal_fragments/2026-10-15-topic.md"
    root = make_repo(tmp_path, {path: FM + "ok\n"})
    assert counts(root, path)[rtl.NAME_PATTERN] == 0
    path2 = "docs/journal_fragments/frag_1406.md"
    root2 = make_repo(tmp_path, {path2: FM + "ok\n"}, name="b")
    assert counts(root2, path2)[rtl.NAME_PATTERN] == 1


def test_masked_path_hides_the_number() -> None:
    assert rtl.mask_numbers("tools/probes/mxc_1406/run_2026-10-15.py") == "tools/probes/mxc_NNNN/run_2026-10-15.py"


# ---- scope ----------------------------------------------------------------------------------------------------------------------

def test_probe_directory_scanned_top_level_probe_not(tmp_path: Path) -> None:
    root = make_repo(tmp_path, {"tools/probes/alpha/a.py": f"{H}1406\n", "tools/probes/solo.py": f"{H}1406\n"})
    got = results(root)
    assert "tools/probes/alpha/a.py" in got and "tools/probes/solo.py" not in got


def test_performance_json_top_level_only(tmp_path: Path) -> None:
    root = make_repo(tmp_path, {PERF: f"{H}1406", "docs/performance/sub/x.json": f"{H}1406", "docs/performance/x.md": f"{H}1406"})
    assert set(results(root)) == {PERF}


def test_marked_log_entry_scanned_unmarked_not(tmp_path: Path) -> None:
    log = (f"# Log\n\n## Old entry\nold {H}1406 text\n\n{MARK}\n## New entry\nclean text\n\n## Next entry\nafter {H}1406\n")
    root = make_repo(tmp_path, {"PERFORMANCE_LOG.md": log})
    assert counts(root, "PERFORMANCE_LOG.md")["tracker-ref"] == 0
    bad = log.replace("clean text", f"dirty {H}1406 text")
    root2 = make_repo(tmp_path, {"PERFORMANCE_LOG.md": bad}, name="b")
    r = results(root2)["PERFORMANCE_LOG.md"]
    assert r.counts["tracker-ref"] == 1 and r.lines["tracker-ref"] == [8]


def test_marked_log_entry_to_end_of_file_and_marker_before_heading(tmp_path: Path) -> None:
    text = f"{MARK}\n## Only entry\nlast {H}1406\n"
    root = make_repo(tmp_path, {"PERFORMANCE_LOG.md": text})
    assert counts(root, "PERFORMANCE_LOG.md")["tracker-ref"] == 1
    spans = rtl.marked_entries([MARK.encode(), b"", b"## A", b"x", b"## B", MARK.encode(), b"## C", b"y"])
    assert spans == [(0, 4), (5, 8)]
    assert rtl.marked_entries([MARK.encode(), b"text", MARK.encode(), b"## C"]) == [(0, 2), (2, 4)]
    assert rtl.marked_entries([b"x " + MARK.encode(), b"## A"]) == []


def test_log_without_marker_is_out_of_scope(tmp_path: Path) -> None:
    root = make_repo(tmp_path, {"PERFORMANCE_LOG.md": f"## A\n{H}1406\n"})
    assert "PERFORMANCE_LOG.md" not in results(root)


def test_marked_fragment_scanned_unmarked_not(tmp_path: Path) -> None:
    root = make_repo(tmp_path, {
        "docs/journal_fragments/a.md": FM + f"body {H}1406\n",
        "docs/journal_fragments/b.md": f"---\ntitle: x\n---\nbody {H}1406\n",
        "docs/journal_fragments/c.md": f"body {H}1406\n---\nresearch-scope: tracker-free\n---\n",
    })
    got = results(root)
    assert set(got) == {"docs/journal_fragments/a.md", "docs/journal_fragments/c.md"}
    assert got["docs/journal_fragments/a.md"].counts["tracker-ref"] == 1
    assert got["docs/journal_fragments/c.md"].counts["malformed-opt-in"] == 1  # the key is named but not in a front matter


def test_front_matter_opt_in_anywhere(tmp_path: Path) -> None:
    root = make_repo(tmp_path, {"docs/research/new.md": FM + f"{H}1406\n", "docs/research/plain.md": f"{H}1406\n"})
    assert set(results(root)) == {"docs/research/new.md"}


def test_preflight_file_is_in_scope(tmp_path: Path) -> None:
    root = make_repo(tmp_path, {rtl.PREFLIGHT: f"checklist {H}1406\n"})
    assert counts(root, rtl.PREFLIGHT)["tracker-ref"] == 1


# ---- the index is the subject ---------------------------------------------------------------------------------------------------

def test_unstaged_edit_does_not_hide_a_finding(tmp_path: Path) -> None:
    root = make_repo(tmp_path, {PROBE: f"{H}1406\n"})
    put(root, {PROBE: "clean now\n"})  # working copy cleaned, index still dirty
    assert counts(root, PROBE)["tracker-ref"] == 1
    assert run(root, "--check").returncode == 1


def test_unstaged_edit_does_not_create_a_finding(tmp_path: Path) -> None:
    root = make_repo(tmp_path, {PROBE: "clean\n"})
    put(root, {PROBE: f"{H}1406\n"})
    assert counts(root, PROBE)["tracker-ref"] == 0
    assert run(root, "--check").returncode == 0


def test_staged_but_uncommitted_file_is_seen(tmp_path: Path) -> None:
    root = make_repo(tmp_path, {PROBE: f"{H}1406\n"}, commit=False)
    assert counts(root, PROBE)["tracker-ref"] == 1


def test_missing_git_fails_not_skips(tmp_path: Path) -> None:
    root = make_repo(tmp_path, {PROBE: "clean\n"})
    env = {**ENV, "PATH": str(tmp_path / "nowhere")}
    p = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "research_tracker_lock.py"), "--root", str(root), "--check"],
                       capture_output=True, text=True, env=env)
    assert p.returncode == 2 and "cannot run" in p.stdout


def test_not_a_repository_fails(tmp_path: Path) -> None:
    (tmp_path / "plain").mkdir()
    assert run(tmp_path / "plain", "--check").returncode == 2


# ---- ratchet --------------------------------------------------------------------------------------------------------------------

def base_for(root: Path) -> dict:
    return rtl.current_baseline_shape(results(root))


def test_ratchet_equal_passes_up_fails_down_fails(tmp_path: Path) -> None:
    root = make_repo(tmp_path, {PROBE: f"{H}1406 and {H}1407\n"})
    base = base_for(root)
    assert base["counts"][PROBE] == {"tracker-ref": 2}
    assert rtl.violations(results(root), base) == []
    higher = {"counts": {PROBE: {"tracker-ref": 3}}, "names": []}
    assert any("below the baseline" in v for v in rtl.violations(results(root), higher))
    lower = {"counts": {PROBE: {"tracker-ref": 1}}, "names": []}
    assert any("exceeds" in v for v in rtl.violations(results(root), lower))


def test_ratchet_new_file_fails_and_gone_file_fails(tmp_path: Path) -> None:
    root = make_repo(tmp_path, {PROBE: "clean\n"})
    assert rtl.violations(results(root), {"counts": {}, "names": []}) == []
    put(root, {"tools/probes/alpha/new.py": f"{H}1406\n"})
    git(root, "add", "--", "tools/probes/alpha/new.py")
    assert rtl.violations(results(root), {"counts": {}, "names": []})
    ghost = {"counts": {"tools/probes/alpha/gone.py": {"tracker-ref": 1}}, "names": []}
    assert any("gone or no longer in scope" in v for v in rtl.violations(results(root), ghost))
    outside = {"counts": {"README.md": {"tracker-ref": 1}}, "names": []}
    assert any("no longer in scope" in v for v in rtl.violations(results(root), outside))


def test_ratchet_name_entries(tmp_path: Path) -> None:
    path = "tools/probes/mxc_1406/run.py"
    root = make_repo(tmp_path, {path: "ok\n"})
    assert any("own name" in v for v in rtl.violations(results(root), {"counts": {}, "names": []}))
    assert rtl.violations(results(root), {"counts": {}, "names": [path]}) == []
    root2 = make_repo(tmp_path, {"tools/probes/alpha/run.py": "ok\n"}, name="b")
    assert any("gone" in v for v in rtl.violations(results(root2), {"counts": {}, "names": ["tools/probes/alpha/run.py"]}))


def test_marked_files_are_never_baselined(tmp_path: Path) -> None:
    path = "docs/journal_fragments/a.md"
    root = make_repo(tmp_path, {path: FM + f"{H}1406\n"})
    listed = {"counts": {path: {"tracker-ref": 1}}, "names": []}
    v = rtl.violations(results(root), listed)
    assert any("never baselined" in x for x in v) and any("exceeds the allowed 0" in x for x in v)


def test_reference_refuses_a_grown_baseline() -> None:
    ref = {"counts": {"a": {"tracker-ref": 2}}, "names": ["n"]}
    assert rtl.reference_violations({"counts": {"a": {"tracker-ref": 2}}, "names": ["n"]}, ref) == []
    assert rtl.reference_violations({"counts": {"a": {"tracker-ref": 1}}, "names": []}, ref) == []
    assert rtl.reference_violations({"counts": {"a": {"tracker-ref": 3}}, "names": ["n"]}, ref)
    assert rtl.reference_violations({"counts": {"b": {"tracker-ref": 1}}, "names": ["n"]}, ref)
    assert rtl.reference_violations({"counts": {}, "names": ["n", "m"]}, ref)


def commit_all(root: Path, *paths: str) -> None:
    git(root, "add", "--", *paths)
    git(root, "commit", "-q", "-m", "y")


def test_write_baseline_creates_lowers_and_refuses_to_raise(tmp_path: Path) -> None:
    root = make_repo(tmp_path, {PROBE: f"{H}1406 {H}1407\n"})
    p = run(root, "--write-baseline", "--base-ref", "HEAD")
    assert p.returncode == 0
    path = root / rtl.BASELINE_PATH
    assert json.loads(path.read_text())["counts"][PROBE] == {"tracker-ref": 2}
    assert "1406" not in path.read_text()
    commit_all(root, rtl.BASELINE_PATH)
    put(root, {PROBE: f"{H}1406\n"})
    git(root, "add", "--", PROBE)
    assert run(root, "--write-baseline", "--base-ref", "HEAD").returncode == 0
    assert json.loads(path.read_text())["counts"][PROBE] == {"tracker-ref": 1}
    commit_all(root, PROBE, rtl.BASELINE_PATH)
    put(root, {PROBE: f"{H}1406 {H}1407 {H}1408\n"})
    git(root, "add", "--", PROBE)
    before = path.read_text()
    p = run(root, "--write-baseline", "--base-ref", "HEAD")
    assert p.returncode == 1 and path.read_text() == before


def test_write_baseline_refuses_new_file_and_marked_findings(tmp_path: Path) -> None:
    root = make_repo(tmp_path, {PROBE: "clean\n"})
    put(root, {"tools/probes/alpha/new.py": f"{H}1406\n"})
    git(root, "add", "--", "tools/probes/alpha/new.py")
    p = run(root, "--write-baseline", "--base-ref", "HEAD")
    assert p.returncode == 1 and not (root / rtl.BASELINE_PATH).exists()
    root2 = make_repo(tmp_path, {"docs/journal_fragments/a.md": FM + f"{H}1406\n"}, name="b")
    assert run(root2, "--write-baseline", "--base-ref", "HEAD").returncode == 1


def test_write_baseline_names_need_the_flag_once_a_baseline_exists(tmp_path: Path) -> None:
    root = make_repo(tmp_path, {PROBE: "clean\n"})
    assert run(root, "--write-baseline", "--base-ref", "HEAD").returncode == 0
    commit_all(root, rtl.BASELINE_PATH)
    put(root, {"tools/probes/alpha/run_2001.py": "ok\n"})
    commit_all(root, "tools/probes/alpha/run_2001.py")  # banked before the rule that catches it
    assert run(root, "--write-baseline", "--base-ref", "HEAD").returncode == 1
    p = run(root, "--write-baseline", "--base-ref", "HEAD", "--add-existing-names")
    assert p.returncode == 0
    assert json.loads((root / rtl.BASELINE_PATH).read_text())["names"] == ["tools/probes/alpha/run_2001.py"]


def test_write_baseline_unresolvable_base_ref_fails(tmp_path: Path) -> None:
    root = make_repo(tmp_path, {PROBE: "clean\n"})
    assert run(root, "--write-baseline", "--base-ref", "no-such-ref").returncode == 2


# ---- the reference control ------------------------------------------------------------------------------------------------------

def test_grown_baseline_passes_without_reference_and_fails_with_it(tmp_path: Path) -> None:
    root = make_repo(tmp_path, {PROBE: f"{H}1406\n"})
    assert run(root, "--write-baseline", "--base-ref", "HEAD").returncode == 0
    commit_all(root, rtl.BASELINE_PATH)
    # grow: one more finding in the listed file, one new file with a finding, and the baseline edited by hand to allow both
    put(root, {PROBE: f"{H}1406 {H}1407\n", "docs/performance/new_rec.json": f"{H}1408\n"})
    put(root, {rtl.BASELINE_PATH: json.dumps({"counts": {PROBE: {"tracker-ref": 2},
                                                          "docs/performance/new_rec.json": {"tracker-ref": 1}}, "names": []})})
    commit_all(root, PROBE, "docs/performance/new_rec.json", rtl.BASELINE_PATH)
    assert run(root, "--check").returncode == 0, "toggle: without the reference the grown baseline certifies itself"
    p = run(root, "--check", "--reference-ref", "HEAD~1")
    assert p.returncode == 1 and p.stdout.count("rose against the reference") == 2
    assert "1407" not in p.stdout and "1408" not in p.stdout


def test_unresolvable_reference_ref_fails_closed(tmp_path: Path) -> None:
    root = make_repo(tmp_path, {PROBE: "clean\n"})
    p = run(root, "--check", "--reference-ref", "no-such-ref")
    assert p.returncode == 2 and "cannot run" in p.stdout


def test_reference_where_baseline_is_absent_counts_as_new(tmp_path: Path) -> None:
    root = make_repo(tmp_path, {PROBE: f"{H}1406\n"})
    assert run(root, "--write-baseline", "--base-ref", "HEAD").returncode == 0
    commit_all(root, rtl.BASELINE_PATH)
    assert run(root, "--check", "--reference-ref", "HEAD~1").returncode == 0


def test_unstaged_or_untracked_baseline_has_no_effect(tmp_path: Path) -> None:
    root = make_repo(tmp_path, {PROBE: f"{H}1406\n"})
    put(root, {rtl.BASELINE_PATH: json.dumps({"counts": {PROBE: {"tracker-ref": 1}}, "names": []})})
    assert run(root, "--check").returncode == 1  # untracked baseline allows nothing
    git(root, "add", "--", rtl.BASELINE_PATH)
    assert run(root, "--check").returncode == 0
    put(root, {rtl.BASELINE_PATH: json.dumps({"counts": {}, "names": []})})  # unstaged edit away from the index version
    assert run(root, "--check").returncode == 0


# ---- output ---------------------------------------------------------------------------------------------------------------------

def test_check_output_names_pattern_never_digits(tmp_path: Path) -> None:
    path = "tools/probes/mxc_1406/run.py"
    root = make_repo(tmp_path, {path: f"line one\n{H}1406 p1407-a S1408-b\n"})
    p = run(root, "--check")
    assert p.returncode == 1
    out = p.stdout
    for pat in ("tracker-ref", "fixture-prefix", "session-token", "name-number"):
        assert pat in out
    assert "line(s) [2]" in out
    for digits in ("1406", "1407", "1408"):
        assert digits not in out
    assert "mxc_NNNN" in out


def test_clean_check_exits_zero(tmp_path: Path) -> None:
    root = make_repo(tmp_path, {PROBE: "clean\n", PERF: "{}\n"})
    p = run(root, "--check")
    assert p.returncode == 0 and "ok" in p.stdout


# ---- the real repository --------------------------------------------------------------------------------------------------------

def test_real_index_passes_check_against_main() -> None:
    p = run(REPO_ROOT, "--check", "--reference-ref", "main")
    assert p.returncode == 0, p.stdout


def test_real_index_passes_check_without_reference() -> None:
    p = run(REPO_ROOT, "--check")
    assert p.returncode == 0, p.stdout


def test_real_scope_is_not_empty() -> None:
    got = rtl.scan_index(REPO_ROOT)
    kinds = {r.kind for r in got.values()}
    assert {"probe", "perf", "preflight"} <= kinds, "the lock watches nothing in a scope entry: a moved directory is a silent lock"
    assert rtl.PREFLIGHT in got


def test_real_baseline_lists_only_existing_files() -> None:
    base = rtl.load_baseline(REPO_ROOT)
    got = rtl.scan_index(REPO_ROOT)
    assert set(base["counts"]) | set(base["names"]) <= set(got)


# ---- readings that are claimed ----------------------------------------------------------------------------------------------------

def test_gzip_reading_is_seen(tmp_path: Path) -> None:
    import gzip
    root = make_repo(tmp_path, {PROBE: gzip.compress(f"see {H}1406\n".encode())})
    assert counts(root, PROBE)["tracker-ref"] == 1


def test_utf16_readings_are_seen(tmp_path: Path) -> None:
    text = f"see {H}1406\n" * 4
    root = make_repo(tmp_path, {PROBE: b"\xff\xfe" + text.encode("utf-16-le"), "tools/probes/alpha/be.py": text.encode("utf-16-be")})
    assert counts(root, PROBE)["tracker-ref"] == 4
    assert counts(root, "tools/probes/alpha/be.py")["tracker-ref"] == 4


def test_ansi_reading_is_seen(tmp_path: Path) -> None:
    esc = chr(27)
    # the colour code touches the prefix letter, so only the reading with the code replaced by a separator sees it
    root = make_repo(tmp_path, {PROBE: f"x{esc}[0mp1407-a"})
    assert counts(root, PROBE)["fixture-prefix"] == 1


# ---- opt-in parsing -------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("front", [
    "---\nresearch-scope: tracker-free\n---\n",
    "---   \nresearch-scope: tracker-free   \n---\n",
    "---\r\nresearch-scope: tracker-free\r\n---\r\n",
    "\ufeff---\nresearch-scope: tracker-free\n---\n",
    "\n\n---\nresearch-scope: tracker-free\n---\n",
    "---\nRESEARCH-SCOPE: Tracker-Free\n---\n",
    "---\n  research-scope:   tracker-free  # why\n---\n",
    "---\nresearch-scope: \"tracker-free\"\n---\n",
    "---\ntitle: x\nresearch-scope: 'tracker-free'\n...\n",
])
def test_opt_in_forms_that_parse(tmp_path: Path, front: str) -> None:
    path = "docs/research/new.md"
    root = make_repo(tmp_path, {path: front + f"body {H}1406\n"})
    r = results(root)[path]
    assert r.kind == "marked-file" and r.counts["tracker-ref"] == 1 and r.counts["malformed-opt-in"] == 0


@pytest.mark.parametrize("key", ["research-scope", "research_scope", "research scope", "researchscope", "Research-Scope"])
def test_key_spellings_between_the_words_all_parse(tmp_path: Path, key: str) -> None:
    path = "docs/research/new.md"
    root = make_repo(tmp_path, {path: f"---\n{key}: tracker-free\n---\nbody {H}1406\n"})
    r = results(root)[path]
    assert r.kind == "marked-file" and r.counts["tracker-ref"] == 1 and r.counts["malformed-opt-in"] == 0


@pytest.mark.parametrize("text", [
    f"body {H}1406\nresearch-scope: tracker-free\n",                      # key outside a front matter
    "---\nresearch-scope: tracker_free\n---\n",                           # typo in the value
    "---\nresearch-scope tracker-free\n---\n",                           # missing colon inside the front matter block
    "---\ntitle: x\n---\ntext\nresearch-scope: tracker-free\n",          # key after the closing line
    "intro\n---\nresearch-scope: tracker-free\n---\n",                   # front matter not first
    "text\n  research_scope : tracker-free\n",                             # indented, underscore, space before the colon
])
def test_malformed_opt_in_fails_closed(tmp_path: Path, text: str) -> None:
    path = "docs/research/new.md"
    root = make_repo(tmp_path, {path: text})
    got = results(root).get(path)
    assert got is not None and got.counts["malformed-opt-in"] >= 1
    assert any("opt-in did not parse" in v for v in rtl.violations(results(root), {"counts": {}, "names": []}))


@pytest.mark.parametrize("text", [
    "The research-scope key opts a file in.\n",
    "Add `research-scope: tracker-free` to the front matter.\n",
    "- research-scope: tracker-free is the line to add\n",
    "See the research scope rules.\n",
    "```yaml\nresearch-scope: tracker-free\n```\n",
    "~~~\n<!-- research-scope: tracker-free -->\n~~~\n",
    "The marker <!-- research-scope: tracker-free --> goes above the heading.\n",
])
def test_prose_and_fenced_mentions_are_not_malformed(tmp_path: Path, text: str) -> None:
    path = "docs/research/notes.md"
    root = make_repo(tmp_path, {path: text})
    assert path not in results(root)
    assert rtl.violations(results(root), {"counts": {}, "names": []}) == []


def test_log_prose_mention_passes_and_key_shaped_line_fails(tmp_path: Path) -> None:
    prose = "## A\nEntries opened with the research-scope marker are locked, as in `<!-- research-scope: tracker-free -->`.\n"
    root = make_repo(tmp_path, {"PERFORMANCE_LOG.md": prose})
    assert "PERFORMANCE_LOG.md" not in results(root)
    root2 = make_repo(tmp_path, {"PERFORMANCE_LOG.md": "## A\n<!-- research-scope: tracker-fre -->\n"}, name="b")
    assert counts(root2, "PERFORMANCE_LOG.md")["malformed-opt-in"] == 1


def test_malformed_log_line_fails_closed_and_valid_marker_forms_parse(tmp_path: Path) -> None:
    ok = f"  <!-- Research-Scope : tracker-free -->  \r\n## E\r\nbody {H}1406\r\n"
    root = make_repo(tmp_path, {"PERFORMANCE_LOG.md": ok})
    assert counts(root, "PERFORMANCE_LOG.md")["tracker-ref"] == 1
    bad = f"<!-- research-scope: tracker-free --> \n## E\nbody\n<!-- research-scope: tracker_free -->\n"
    root2 = make_repo(tmp_path, {"PERFORMANCE_LOG.md": bad.replace("--> \n", "-->\n", 1)}, name="b")
    assert counts(root2, "PERFORMANCE_LOG.md")["malformed-opt-in"] == 1


def test_scope_word_inside_a_probe_directory_file_is_not_malformed(tmp_path: Path) -> None:
    root = make_repo(tmp_path, {"tools/probes/alpha/README.md": "notes on research-scope handling\n"})
    assert results(root)["tools/probes/alpha/README.md"].counts["malformed-opt-in"] == 0


# ---- log entry boundaries with fences -------------------------------------------------------------------------------------------

def test_heading_inside_a_fence_does_not_end_the_entry(tmp_path: Path) -> None:
    log = f"{MARK}\n## Entry\n```bash\n## build step\nmake\n```\nafter fence {H}1406\n\n## Next\nnot scanned {H}1407\n"
    root = make_repo(tmp_path, {"PERFORMANCE_LOG.md": log})
    r = results(root)["PERFORMANCE_LOG.md"]
    assert r.counts["tracker-ref"] == 1 and r.lines["tracker-ref"] == [7]
    tilde = log.replace("```", "~~~")
    root2 = make_repo(tmp_path, {"PERFORMANCE_LOG.md": tilde}, name="b")
    assert counts(root2, "PERFORMANCE_LOG.md")["tracker-ref"] == 1
    assert rtl.marked_entries([MARK.encode(), b"## A", b"```", b"## in", b"```", b"x", b"## B"]) == [(0, 6)]


def _mk(*lines: str) -> list[bytes]:
    return [x.encode() for x in lines]


def _legacy_marked_entries(lines: list[bytes]) -> list[tuple[int, int]]:
    """The superseded rule (second-level headings only), kept to prove the new tests can fail."""
    out: list[tuple[int, int]] = []
    flags = rtl.fence_flags(lines)
    covered = 0
    for i, line in enumerate(lines):
        if i < covered or not rtl._MARKER_RE.match(line):
            continue
        heading, end = None, len(lines)
        for j in range(i + 1, len(lines)):
            if heading is None and rtl._MARKER_RE.match(lines[j]):
                end = j
                break
            if flags[j]:
                continue
            if heading is None:
                if lines[j].startswith(b"## "):
                    heading = j
            elif lines[j].startswith(b"## "):
                end = j
                break
        out.append((i, end))
        covered = end
    return out


def test_marker_before_third_level_entry_ends_at_next_heading_of_same_or_higher_level(tmp_path: Path) -> None:
    m = MARK.encode()
    lines = [m, b"### A", b"x", b"### B", b"y", b"## C", b"z"]
    assert rtl.marked_entries(lines) == [(0, 3)]
    assert _legacy_marked_entries(lines) == [(0, 7)]  # toggle: the old rule spills over the following ### entry
    log = "\n".join(["## Old", f"old {H}1406", "", MARK, "### New", "clean", "", "### Next", f"after {H}1406", "", "## Top", f"more {H}1407", ""])
    root = make_repo(tmp_path, {"PERFORMANCE_LOG.md": log})
    assert counts(root, "PERFORMANCE_LOG.md")["tracker-ref"] == 0
    root2 = make_repo(tmp_path, {"PERFORMANCE_LOG.md": log.replace("clean", f"dirty {H}1406")}, name="b")
    assert results(root2)["PERFORMANCE_LOG.md"].lines["tracker-ref"] == [6]


def test_sub_headings_stay_inside_a_second_level_entry() -> None:
    m = MARK.encode()
    assert rtl.marked_entries([m, b"## A", b"### sub", b"#### deeper", b"x", b"## B", b"y"]) == [(0, 5)]
    assert rtl.marked_entries([m, b"### A", b"#### sub", b"x"]) == [(0, 4)]
    assert rtl.marked_entries([m, b"### A", b"# Top", b"x"]) == [(0, 2)]


def test_heading_shapes_for_entry_boundaries() -> None:
    m = MARK.encode()
    assert rtl.marked_entries([m, b"#### A", b"#hashtag", b"####### seven", b"x", b"#### B"]) == [(0, 5)]
    assert rtl.marked_entries([m, b"### A\r", b"###\r", b"x"]) == [(0, 2)]


def test_fenced_headings_of_any_level_do_not_bound_the_entry() -> None:
    m = MARK.encode()
    assert rtl.marked_entries(_mk(MARK, "### A", "```", "### in", "## in2", "```", "x", "### B")) == [(0, 7)]
    assert rtl.marked_entries(_mk(MARK, "```", "### in", "```", "### A", "x", "### B")) == [(0, 6)]
    assert m


# ---- printed paths --------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("path,masked", [
    ("tools/probes/y_17860/b.py", "tools/probes/y_NNNN/b.py"),
    ("tools/probes/y_2026.4/b.py", "tools/probes/y_2026.4/b.py"),
    ("tools/probes/y_2026_2/b.py", "tools/probes/y_NNNN_2/b.py"),
    ("tools/probes/y_2026-10-15/b.py", "tools/probes/y_2026-10-15/b.py"),
    ("tools/probes/run-20261015-1.json", "tools/probes/run-20261015-1.json"),
    ("tools/probes/run-1015.json", "tools/probes/run-NNNN.json"),
    ("tools/probes/mxc_1406/x.py", "tools/probes/mxc_NNNN/x.py"),
])
def test_masked_paths(path: str, masked: str) -> None:
    assert rtl.mask_numbers(path) == masked


def test_check_output_masks_every_long_run(tmp_path: Path) -> None:
    root = make_repo(tmp_path, {"tools/probes/y_17860/b.py": f"{H}1406\n", "tools/probes/z_2026_2/c.py": f"{H}1407\n"})
    out = run(root, "--check").stdout
    for digits in ("17860", "2026_2", "1406", "1407"):
        assert digits not in out


# ---- fence closing ----------------------------------------------------------------------------------------------------------------

def test_fence_closes_only_on_its_own_character_and_length() -> None:
    lines = [b"~~~markdown", b"```", b"## step", b"~~~", b"## out"]
    assert rtl.fence_flags(lines) == [True, True, True, True, False]
    lines2 = [b"````", b"```", b"## in", b"````", b"## out"]
    assert rtl.fence_flags(lines2) == [True, True, True, True, False]
    assert rtl.fence_flags([b"```", b"~~~", b"## in", b"```"]) == [True, True, True, True]
    mixed = f"{MARK}\n## Entry\n~~~markdown\n```\n## step\n~~~\nleak {H}1406\n\n## Next\n"
    # without the fix the inner backtick line closed the tilde fence and the heading ended the entry
    root_lines = mixed.encode().split(b"\n")
    spans = rtl.marked_entries(root_lines)
    assert spans[0][1] == 8


# ---- version names written by the benchmark harnesses ---------------------------------------------------------------------------

HARNESS_SCRIPTS = [
    "benchmark_kv_cache_sweep.py",
    "benchmark_prefill.py",
    "benchmark_prefix_caching_ab.py",
    "benchmark_spec_decode_ab.py",
    "vlm_perf.py",
]
_OUTPATH_RE = re.compile(r'outpath\s*=\s*[^\n]*?f"([^"\n]*ov\{safe_ov\}_\{ts\}\.json)"')


def writer_name_format(script: str) -> str:
    """The record-name f-string the writer script itself contains, read from its source; fails when it is not found."""
    src = (REPO_ROOT / "scripts" / script).read_text(encoding="utf-8")
    m = _OUTPATH_RE.search(src)
    assert m, f"{script}: no outpath f-string ending in ov{{safe_ov}}_{{ts}}.json; the lock's version rule no longer matches the writer"
    assert 'replace(".", "_")' in src, f"{script}: the version is no longer written with dots as underscores"
    fmt = m.group(1)
    h = re.search(r'^HARNESS_NAME\s*=\s*"([^"]+)"', src, re.MULTILINE)
    fmt = fmt.replace("{HARNESS_NAME}", h.group(1) if h else "{HARNESS_NAME}").replace("{args.model_name}", "14b")
    left = set(re.findall(r"\{([^}]*)\}", fmt)) - {"safe_ov", "ts"}
    assert not left, f"{script}: unexpected placeholders {sorted(left)} in the record name"
    return fmt


@pytest.mark.parametrize("script", HARNESS_SCRIPTS)
def test_each_harness_name_format_passes_and_a_tracker_in_its_place_fails(tmp_path: Path, script: str) -> None:
    fmt = writer_name_format(script)
    ts = "2026-10-15_12-00-00"
    good = "docs/performance/" + fmt.replace("{safe_ov}", "2026_2_1_0").replace("{ts}", ts)
    root = make_repo(tmp_path, {good: "{}\n"})
    assert results(root)[good].counts["name-number"] == 0
    for bad_v in ("1406_2_1_0", "1406"):
        bad = "docs/performance/" + fmt.replace("{safe_ov}", bad_v).replace("{ts}", ts)
        root2 = make_repo(tmp_path, {bad: "{}\n"}, name="b" + bad_v)
        assert results(root2)[bad].counts["name-number"] >= 1, bad


# ---- reference: merge base and main history ---------------------------------------------------------------------------------------

def _repo_with_baseline(tmp_path: Path, counts: int) -> Path:
    root = make_repo(tmp_path, {PROBE: " ".join(f"{H}{1400 + i}" for i in range(counts)) + "\n"})
    assert run(root, "--write-baseline", "--base-ref", "HEAD").returncode == 0
    commit_all(root, rtl.BASELINE_PATH)
    return root


def test_stale_branch_compares_against_the_merge_base_not_main_tip(tmp_path: Path) -> None:
    root = _repo_with_baseline(tmp_path, 2)
    git(root, "switch", "-q", "-c", "topic")
    git(root, "switch", "-q", "main")
    put(root, {PROBE: f"{H}1400\n"})
    git(root, "add", "--", PROBE)
    assert run(root, "--write-baseline", "--base-ref", "HEAD").returncode == 0
    commit_all(root, PROBE, rtl.BASELINE_PATH)  # main lowers the baseline after the fork
    git(root, "switch", "-q", "topic")
    assert run(root, "--check", "--reference-ref", "main").returncode == 0, "the fork point is the reference, not main's tip"
    put(root, {PROBE: f"{H}1400 {H}1401 {H}1402\n"})
    put(root, {rtl.BASELINE_PATH: json.dumps({"counts": {PROBE: {"tracker-ref": 3}}, "names": []})})
    commit_all(root, PROBE, rtl.BASELINE_PATH)
    assert run(root, "--check", "--reference-ref", "main").returncode == 1


def test_growth_that_reached_main_is_seen_through_the_baseline_history(tmp_path: Path) -> None:
    root = _repo_with_baseline(tmp_path, 1)
    put(root, {PROBE: f"{H}1400 {H}1401\n"})
    put(root, {rtl.BASELINE_PATH: json.dumps({"counts": {PROBE: {"tracker-ref": 2}}, "names": []})})
    commit_all(root, PROBE, rtl.BASELINE_PATH)  # landed on main without a gate run
    assert run(root, "--check").returncode == 0
    p = run(root, "--check", "--reference-ref", "main")
    assert p.returncode == 1 and "rose against the reference" in p.stdout


def test_main_history_reference_ignores_a_first_landing_and_honest_lowering(tmp_path: Path) -> None:
    root = _repo_with_baseline(tmp_path, 2)
    assert run(root, "--check", "--reference-ref", "main").returncode == 0
    put(root, {PROBE: f"{H}1400\n"})
    git(root, "add", "--", PROBE)
    assert run(root, "--write-baseline", "--base-ref", "HEAD").returncode == 0
    commit_all(root, PROBE, rtl.BASELINE_PATH)
    assert run(root, "--check", "--reference-ref", "main").returncode == 0


def test_unresolved_reference_names_the_ref(tmp_path: Path) -> None:
    root = make_repo(tmp_path, {PROBE: "clean\n"})
    p = run(root, "--check", "--reference-ref", "origin/nowhere")
    assert p.returncode == 2 and "origin/nowhere" in p.stdout


# ---- --add-existing-names base ------------------------------------------------------------------------------------------------

def test_add_existing_names_refuses_a_moved_base_ref(tmp_path: Path) -> None:
    root = make_repo(tmp_path, {PROBE: "clean\n"})
    assert run(root, "--write-baseline", "--base-ref", "HEAD").returncode == 0
    commit_all(root, rtl.BASELINE_PATH)
    git(root, "switch", "-q", "-c", "topic")
    put(root, {"tools/probes/alpha/run_2001.py": "ok\n"})
    commit_all(root, "tools/probes/alpha/run_2001.py")
    p = run(root, "--write-baseline", "--base-ref", "HEAD", "--add-existing-names")
    assert p.returncode == 1 and "main's tip or the merge base" in p.stdout
    p2 = run(root, "--write-baseline", "--base-ref", "main", "--add-existing-names")
    assert p2.returncode == 1 and "not tracked at main" in p2.stdout


# ---- landing shape ----------------------------------------------------------------------------------------------------------------

def _two_version_branch(tmp_path: Path, name: str) -> Path:
    root = make_repo(tmp_path, {PROBE: f"{H}1400\n"}, name=name)
    git(root, "switch", "-q", "-c", "topic")
    put(root, {rtl.BASELINE_PATH: json.dumps({"counts": {PROBE: {"tracker-ref": 1}}, "names": []})})
    commit_all(root, rtl.BASELINE_PATH)  # first baseline version: one finding
    put(root, {PROBE: f"{H}1400 {H}1401\n", rtl.BASELINE_PATH: json.dumps({"counts": {PROBE: {"tracker-ref": 2}}, "names": []})})
    commit_all(root, PROBE, rtl.BASELINE_PATH)  # second version on the same branch: the count rose while the file was new
    git(root, "switch", "-q", "main")
    return root


def test_fast_forward_landing_fails_and_no_ff_landing_passes(tmp_path: Path) -> None:
    ff = _two_version_branch(tmp_path, "ff")
    git(ff, "merge", "-q", "--ff-only", "topic")
    p = run(ff, "--check", "--reference-ref", "main")
    assert p.returncode == 1 and "rose against the reference" in p.stdout, "two intermediate versions on the first-parent line"
    merged = _two_version_branch(tmp_path, "noff")
    git(merged, "merge", "-q", "--no-ff", "-m", "land", "topic")
    assert run(merged, "--check", "--reference-ref", "main").returncode == 0
    doctrine = (REPO_ROOT / ".claude" / "rules" / "identity.md").read_text(encoding="utf-8")
    line = next(x for x in doctrine.splitlines() if "git merge --no-ff" in x)
    assert "scripts/research_tracker_baseline.json" in line and "scripts/research_tracker_lock.py" in line


# ---- names added by --add-existing-names -------------------------------------------------------------------------------------------

NEWLY_CAUGHT = "tools/probes/alpha/run_2001.py"


def _banked_name_repo(tmp_path: Path, name: str) -> Path:
    root = make_repo(tmp_path, {NEWLY_CAUGHT: "ok\n", rtl.BASELINE_PATH: json.dumps({"counts": {}, "names": []})}, name=name)
    git(root, "switch", "-q", "-c", "topic")
    p = run(root, "--write-baseline", "--base-ref", "main", "--add-existing-names")
    assert p.returncode == 0, p.stdout
    commit_all(root, rtl.BASELINE_PATH)
    return root


def test_add_existing_names_output_passes_the_reference_on_branch_and_on_no_ff_main(tmp_path: Path) -> None:
    root = _banked_name_repo(tmp_path, "r")
    assert json.loads((root / rtl.BASELINE_PATH).read_text())["names"] == [NEWLY_CAUGHT]
    assert run(root, "--check", "--reference-ref", "main").returncode == 0
    git(root, "switch", "-q", "main")
    git(root, "merge", "-q", "--no-ff", "-m", "land", "topic")
    assert run(root, "--check", "--reference-ref", "main").returncode == 0


def test_a_genuinely_new_name_entry_is_still_refused(tmp_path: Path) -> None:
    root = _banked_name_repo(tmp_path, "r2")
    new = "tools/probes/alpha/run_2002.py"
    put(root, {new: "ok\n", rtl.BASELINE_PATH: json.dumps({"counts": {}, "names": [NEWLY_CAUGHT, new]})})
    commit_all(root, new, rtl.BASELINE_PATH)
    p = run(root, "--check", "--reference-ref", "main")
    assert p.returncode == 1 and "gained a name entry" in p.stdout


# ---- shallow and empty ----------------------------------------------------------------------------------------------------------

def test_shallow_clone_fails_closed_for_the_reference(tmp_path: Path) -> None:
    root = _repo_with_baseline(tmp_path, 1)
    put(root, {PROBE: f"{H}1400\n "})
    commit_all(root, PROBE)
    clone = tmp_path / "shallow"
    subprocess.run(["git", "clone", "-q", "--depth", "1", root.as_uri(), str(clone)], check=True, capture_output=True, env=ENV)
    assert run(clone, "--check").returncode == 0
    p = run(clone, "--check", "--reference-ref", "main")
    assert p.returncode == 2 and "shallow" in p.stdout


def test_empty_index_fails_instead_of_reporting_ok(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    git(empty, "init", "-q", "-b", "main")
    p = run(empty, "--check")
    assert p.returncode == 2 and "sees nothing" in p.stdout
    only_docs = make_repo(tmp_path, {"README.md": "hello\n"}, name="docs")
    assert run(only_docs, "--check").returncode == 2
