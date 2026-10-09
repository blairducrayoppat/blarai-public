"""The installer asks git for hashes and blobs in ONE process each instead of one per file (#1699).

The batching must be the same control as the per-file calls it replaced, so every property is
proved against a real repository, and each fail-closed branch is shown to fire:

* a hash equals the per-file `git hash-object --no-filters` answer, including for binary content
  with line breaks and for several files at once;
* a request that git cannot answer in full yields "" for EVERY path, which no recorded hash
  equals, so the caller refuses exactly as it did for an unreadable file;
* a blob read returns the bytes verbatim (NUL, CR, LF, 200 KB) and None for a missing object, a
  non-blob (a tree) and an unparseable reply, never a truncated or shifted answer;
* a path containing a line break falls back to one call per file instead of being mis-split.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import install_git_hooks as ih  # noqa: E402
from _git_hook_helpers import git, make_repo  # noqa: E402

PAYLOADS = {
    "a.txt": b"hello\n",
    "bin.dat": bytes(range(256)) + b"\r\n\x00\n" * 50,
    "big.dat": b"x" * 200_000 + b"\n",
    "empty": b"",
}


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "r"
    r.mkdir()
    for args in (["init", "-q", "-b", "main"], ["config", "user.name", "t"], ["config", "user.email", "t@t"]):
        subprocess.run(["git", "-C", str(r), *args], check=True, capture_output=True)
    for name, data in PAYLOADS.items():
        (r / name).write_bytes(data)
    subprocess.run(["git", "-C", str(r), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(r), "commit", "-q", "-m", "x"], check=True, capture_output=True)
    return r


def _one(repo: Path, path: Path) -> str:
    return subprocess.run(["git", "-C", str(repo), "hash-object", "--no-filters", "--", str(path)],
                          capture_output=True, text=True, check=True).stdout.strip()


def _sha(repo: Path, name: str) -> str:
    return subprocess.run(["git", "-C", str(repo), "rev-parse", f"HEAD:{name}"],
                          capture_output=True, text=True, check=True).stdout.strip()


def test_batched_hashes_equal_the_per_file_answers(repo: Path) -> None:
    paths = [repo / n for n in PAYLOADS]
    assert ih._hashes(repo, paths) == [_one(repo, p) for p in paths]
    assert ih._hashes(repo, []) == []


def test_a_missing_file_makes_every_answer_empty_so_no_comparison_can_pass(repo: Path) -> None:
    paths = [repo / "a.txt", repo / "no-such-file", repo / "bin.dat"]
    assert ih._hashes(repo, paths) == ["", "", ""]


def test_a_path_with_a_line_break_falls_back_to_one_call_per_file(repo: Path) -> None:
    """The batch protocol is one path per line, so such a path must not ride it: the fallback answers
    the real file and fails only the unreadable one (a batch would have blanked both)."""
    paths = [repo / "a.txt", Path("no\nsuch")]
    assert ih._hashes(repo, paths) == [_one(repo, repo / "a.txt"), ""]


def test_blobs_come_back_byte_for_byte_in_request_order(repo: Path) -> None:
    names = ["big.dat", "a.txt", "empty", "bin.dat", "a.txt"]
    got = ih._blobs(repo, [_sha(repo, n) for n in names])
    assert got == [PAYLOADS[n] for n in names]
    assert ih._blobs(repo, []) == []


def test_a_missing_object_a_tree_and_junk_are_none_and_never_shift_the_others(repo: Path) -> None:
    tree = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD^{tree}"], capture_output=True, text=True,
                          check=True).stdout.strip()
    missing = "0" * 40
    got = ih._blobs(repo, [_sha(repo, "a.txt"), missing, tree, _sha(repo, "bin.dat")])
    assert got[0] == PAYLOADS["a.txt"] and got[1] is None and got[2] is None
    assert got[3] == PAYLOADS["bin.dat"], "an unanswerable entry must not displace the next one"
    assert ih._blobs(repo, ["not-a-sha"]) == [None]


def test_the_common_dir_is_resolved_once_per_repository(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ih._COMMON.clear()
    calls = []
    real = ih._git

    def counting(r, *a, **k):
        calls.append(a)
        return real(r, *a, **k)

    monkeypatch.setattr(ih, "_git", counting)
    first = ih._common(repo)
    assert ih._common(repo) == first == ih._common(repo)
    assert sum(1 for a in calls if "--git-common-dir" in a) == 1


# ---- the verifications the batching must not weaken, each shown to fire -------------------------

def _corrupt_loose_object(repo: Path, sha: str) -> None:
    obj = repo / ".git" / "objects" / sha[:2] / sha[2:]
    os.chmod(obj, 0o700)
    obj.write_bytes(b"not a zlib stream")


def test_a_corrupt_object_is_named_not_the_first_file(repo: Path, tmp_path: Path) -> None:
    """git dies mid-stream on the middle blob; the refusal must name THAT file (an operator
    inspecting the first file would find nothing)."""
    source = {"hooks/first.py": _sha(repo, "a.txt"), "hooks/middle.py": _sha(repo, "bin.dat"),
              "hooks/last.py": _sha(repo, "big.dat")}
    _corrupt_loose_object(repo, source["hooks/middle.py"])
    blobs = ih._blobs(repo, list(source.values()))
    assert blobs[0] == PAYLOADS["a.txt"], "the entry parsed intact before the failure keeps its bytes"
    assert blobs[1] is None
    out = tmp_path / "build"
    out.mkdir()
    with pytest.raises(SystemExit, match="cannot read blob .* for hooks/middle.py"):
        ih._build(repo, source, out)


def test_a_written_copy_that_differs_from_mains_blob_is_refused(repo: Path, tmp_path: Path,
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    source = {"hooks/a.py": _sha(repo, "a.txt")}
    real = ih._blobs
    monkeypatch.setattr(ih, "_blobs", lambda r, shas: [b + b"x" for b in real(r, shas)])
    out = tmp_path / "build"
    out.mkdir()
    with pytest.raises(SystemExit, match="written copy does not match"):
        ih._build(repo, source, out)


def _installed(tmp_path: Path) -> Path:
    repo = make_repo(tmp_path, "inst", install=False)
    assert ih.main(["--repo", str(repo)]) == 0
    return repo


def test_an_installed_copy_that_differs_after_the_swap_aborts_the_install(tmp_path: Path,
                                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    repo = make_repo(tmp_path, "inst", install=False)
    real = ih._hashes

    def lying(r, paths):
        got = real(r, paths)
        return ["0" * 40] * len(got) if paths and "blarai-hooks" in Path(paths[0]).parts else got

    monkeypatch.setattr(ih, "_hashes", lying)
    with pytest.raises(SystemExit, match="installed copy does not match main's blob after the swap"):
        ih.main(["--repo", str(repo)])


def test_drift_of_an_installed_file_is_reported_by_the_update_review(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    repo = _installed(tmp_path)
    target = repo / ".git" / "blarai-hooks" / "hooks" / "rules_common.py"
    target.write_bytes(target.read_bytes() + b"# tampered\n")
    drift = ih._drift(repo, ih.json.loads((repo / ".git" / "blarai-install.json").read_text(encoding="utf-8")))
    assert drift and [d[:2] for d in drift] == [("hooks/rules_common.py", "DRIFT")]


def test_a_path_outside_the_console_code_page_neither_crashes_nor_passes(repo: Path) -> None:
    paths = [repo / "a.txt", repo / "日本語.txt"]
    got = ih._hashes(repo, paths)
    assert got[1] == "" and (got[0] in ("", _one(repo, repo / "a.txt")))


# ---- the parsers against replies git can give when it fails (scripted, deterministic) -------------

def _fake_git(monkeypatch: pytest.MonkeyPatch, stdout: bytes, returncode: int = 0) -> None:
    monkeypatch.setattr(ih, "_git", lambda *a, **k: subprocess.CompletedProcess(a, returncode, stdout, b""))


SHA_A, SHA_B, SHA_C = "a" * 40, "b" * 40, "c" * 40


def test_entries_parsed_intact_before_git_died_keep_their_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_git(monkeypatch, f"{SHA_A} blob 5\nhello\n{SHA_B} blob 9\nhalf".encode(), returncode=128)
    assert ih._blobs(Path("."), [SHA_A, SHA_B, SHA_C]) == [b"hello", None, None]


def test_a_reply_for_another_object_is_not_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_git(monkeypatch, f"{SHA_B} blob 3\nabc\n".encode())
    assert ih._blobs(Path("."), [SHA_A]) == [None]


def test_a_body_shorter_than_its_header_says_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_git(monkeypatch, f"{SHA_A} blob 10\nabc".encode())
    assert ih._blobs(Path("."), [SHA_A]) == [None]


def test_hashes_with_the_wrong_count_or_a_failing_exit_are_all_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    paths = [Path("x"), Path("y")]
    _fake_git(monkeypatch, f"{SHA_A}\n".encode())
    assert ih._hashes(Path("."), paths) == ["", ""], "one answer for two paths"
    _fake_git(monkeypatch, f"{SHA_A}\n{SHA_B}\n".encode(), returncode=128)
    assert ih._hashes(Path("."), paths) == ["", ""], "git failed even though two answers arrived"
    _fake_git(monkeypatch, f"{SHA_A}\n{SHA_B}\n".encode())
    assert ih._hashes(Path("."), paths) == [SHA_A, SHA_B]


def test_hashes_are_of_the_raw_bytes_even_where_git_would_convert_line_endings(repo: Path) -> None:
    """--no-filters is part of the control: with core.autocrlf the filtered hash of a CRLF text file differs."""
    subprocess.run(["git", "-C", str(repo), "config", "core.autocrlf", "true"], check=True, capture_output=True)
    crlf = repo / "crlf.txt"
    crlf.write_bytes(b"one\r\ntwo\r\n")
    filtered = subprocess.run(["git", "-C", str(repo), "hash-object", "--", str(crlf)], capture_output=True,
                              text=True, check=True).stdout.strip()
    assert filtered != _one(repo, crlf), "precondition: this git converts the file when filters are on"
    assert ih._hashes(repo, [crlf]) == [_one(repo, crlf)]


def test_a_path_that_exists_only_in_utf8_not_in_the_console_code_page_gets_its_real_hash(repo: Path) -> None:
    odd = repo / "€œ.txt"      # in cp1252 but not in Latin-1, so a cp1252 stdin would name a different file
    odd.write_bytes(b"euro")
    assert ih._hashes(repo, [odd]) == [_one(repo, odd)]
