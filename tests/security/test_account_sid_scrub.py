"""Gate lock for Microsoft-account and Entra ID (Azure AD) account SIDs: ``S-1-11-96-<...>`` and ``S-1-12-1-<...>`` name one
person's cloud account. ``scripts/scrub_public_identifiers.py`` rewrites them to ``S-1-11-__ACCOUNT__`` / ``S-1-12-__ACCOUNT__``
in every tracked file and every file of a ``--dir`` run; ``check()``, the gate tree scan and the Hugging Face preflight fail while
one remains; a file NAME or a shape the rewrite cannot clear fails closed for a hand edit.

The toggles show the machine-SID rule (``S-1-5-21-*``) never saw this shape, and that each new arm is what makes its probe fire.
The SIDs below are made up and assembled at run time, so the shape itself never sits in this file for the tree scan to find.
"""

from __future__ import annotations

import bz2
import gzip
import io
import lzma
import json
import os
import re
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import hf_publish  # noqa: E402
import identity_lock as il  # noqa: E402
import scrub_public_identifiers as scrub  # noqa: E402

MSA_PREFIX = "-".join(("S", "1", "11", "96"))
ENTRA_PREFIX = "-".join(("S", "1", "12", "1"))
SUBAUTH = "4111222333"
MSA_SID = f"{MSA_PREFIX}-{SUBAUTH}-50111-60222-1357924680-2468013579-1234567890-3098765432-1112223334-4445556667-778899001"
ENTRA_SID = f"{ENTRA_PREFIX}-{SUBAUTH}-1209876543-2876543210-3765432109"
SIDS = {"msa": MSA_SID, "entra": ENTRA_SID}
OUTSIDE_EVERY_SCOPE = "docs/research/elsewhere/run-a.json"
NEVER = re.compile(rb"(?!)")


def _record(sid: str) -> bytes:
    doc = {"token": {"user_sid": sid, "integrity_sid": "S-1-16-8192", "groups": ["S-1-5-32-544", "S-1-5-11"]}, "owner": sid}
    return json.dumps(doc, indent=1).encode("utf-8")


SHAPES = {
    "plain": lambda s: _record(s),
    "lowercase": lambda s: _record(s.lower()),
    "utf16_bom": lambda s: _record(s).decode().encode("utf-16"),
    "utf16_be_no_bom": lambda s: _record(s).decode().encode("utf-16-be"),
    "gzip": lambda s: gzip.compress(_record(s)),
    "gzip_of_utf16": lambda s: gzip.compress(_record(s).decode().encode("utf-16")),
    "json_escaped_crlf": lambda s: json.dumps({"stdout": "User Name SID\r\n" + s}).encode(),
    "json_escaped_u0053": lambda s: ('{"sid": "\\u0053' + s[1:] + '"}').encode(),
    "json_escaped_x53": lambda s: ('{"sid": "\\x53' + s[1:] + '"}').encode(),
    "percent_before": lambda s: b"path=%5C" + s.encode(),
    "ansi_before": lambda s: b"\x1b[32m" + s.encode() + b"\x1b[0m",
    "json_doubly_encoded_crlf": lambda s: json.dumps({"message": json.dumps({"stdout": "SID\r\n" + s})}).encode(),
    "registry_key": lambda s: ("HKEY_USERS\\" + s + "_Classes").encode(),
    "sddl": lambda s: ("O:" + s + "D:(A;;FA;;;" + s + ")").encode(),
    # A percent-escape decoding to a letter glues to the SID in the decoded view; only the rewrite arm reads it.
    "percent_letter_before": lambda s: b"path=%41" + s.encode(),
    "gzip_percent_letter_before": lambda s: gzip.compress(b"path=%41" + s.encode()),
}
# Seen by the decoded views only: the rewrite does not clear them, the run fails closed for a hand edit.
FAIL_CLOSED_SHAPES = {
    "html_entity_first_letter": lambda s: ("&#83;" + s[1:]).encode(),
    "percent_whole": lambda s: b"p=" + b"".join(b"%%%02X" % c for c in s.encode()),
    "percent_whole_lowercase": lambda s: b"p=" + b"".join(b"%%%02X" % c for c in s.lower().encode()),
}
FAIL_CLOSED_CASES = [(kind, shape) for kind in sorted(SIDS) for shape in sorted(FAIL_CLOSED_SHAPES)]
CASES = [(kind, shape) for kind in sorted(SIDS) for shape in sorted(SHAPES)]


def _live() -> tuple[str, str]:
    host, user = il.live_names()
    assert host and user, "the host or user name is not readable on this machine"
    return host, user


def _scrub(data: bytes) -> tuple[bytes, dict[str, int]]:
    host, user = _live()
    return scrub.scrub_bytes(data, host=host, user=user, in_scope=False, sid_scope=False)


def _commit(root: Path, msg: str) -> None:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True, env=env, capture_output=True)  # a scratch repository of this test's own files
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", msg], check=True, env=env, capture_output=True)


def _repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True, capture_output=True)
    scrub.save_user_baseline(tmp_path, {})
    _commit(tmp_path, "baseline")
    return tmp_path


def _plant(root: Path, rel: str, data: bytes) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def _check(root: Path, files: list[Path]) -> list[str]:
    host, user = _live()
    return scrub.check(root, files, host, user, il.serial_digests())


def _dir(tmp_path: Path, *args: str) -> int:
    return scrub.main(["--dir", str(tmp_path / "run"), "--log", str(tmp_path / "scrub-log.md"), *args])


def _text(data: bytes) -> str:
    return " ".join(v.decode("utf-8", "ignore") for v in il.views(data))


# ---- the old rule never saw the shape ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("kind", sorted(SIDS))
def test_toggle_the_machine_sid_rule_alone_misses_a_cloud_account_sid(kind: str, monkeypatch: pytest.MonkeyPatch) -> None:
    data = _record(SIDS[kind])
    assert not il.find_sid_hits(data), "the machine-SID lock already sees the shape: the toggle does not discriminate"
    assert il.find_account_sid_hits(data), "the account-SID lock cannot see the shape"
    monkeypatch.setattr(il, "rewrite_account_sids", lambda d: (d, 0))  # the scrub as it was: machine rule only
    old, counts = scrub.scrub_bytes(data, host=None, user=None, in_scope=False, sid_scope=True)
    assert old == data and counts["sid"] == 0, "the machine-SID rewrite touched a cloud account SID"


# ---- the rewrite and the lock agree, per encoding ------------------------------------------------------------------------------

@pytest.mark.parametrize(("kind", "shape"), CASES)
def test_lock_fires_before_the_rewrite_and_is_silent_after(kind: str, shape: str) -> None:
    data = SHAPES[shape](SIDS[kind])
    assert il.find_account_sid_hits(data), f"the lock cannot see a {kind} SID written as {shape}"
    once, counts = _scrub(data)
    assert counts["account"] >= 1, f"the rewrite did not count the {kind} SID written as {shape}"
    assert not il.find_account_sid_hits(once), f"the rewrite left a {kind} SID written as {shape} that the lock still sees"
    assert SUBAUTH not in _text(once), f"a sub-authority survived the rewrite of {shape}"
    twice, counts2 = _scrub(once)
    assert twice == once and counts2["account"] == 0, f"the rewrite of {shape} is not idempotent"


@pytest.mark.parametrize("kind", sorted(SIDS))
def test_the_rewrite_keeps_the_prefix_writes_the_placeholder_and_leaves_generic_sids(kind: str) -> None:
    placeholder = "S-1-11-__ACCOUNT__" if kind == "msa" else "S-1-12-__ACCOUNT__"
    for wrap in ("plain", "utf16_bom", "gzip"):
        once, counts = _scrub(SHAPES[wrap](SIDS[kind]))
        assert counts["account"] == 2
        assert placeholder in _text(once) and MSA_PREFIX not in _text(once) and ENTRA_PREFIX not in _text(once)
    doc = json.loads(_scrub(_record(SIDS[kind]))[0])
    assert doc["token"]["integrity_sid"] == "S-1-16-8192" and doc["token"]["groups"] == ["S-1-5-32-544", "S-1-5-11"]


def test_lookalikes_are_not_account_sids() -> None:
    for text in (f"{ENTRA_PREFIX}0-5-6", f"{MSA_PREFIX}0-5", "S-1-5-21-1-2-3-1001", "S-1-11-__ACCOUNT__", "S-1-12-__ACCOUNT__",
                 f"{MSA_PREFIX}-__ACCOUNT__", f"{ENTRA_PREFIX}-__ACCOUNT__", "S-1-15-2-1-2-3", f"x{ENTRA_PREFIX}-1-2-3-4"):
        assert not il.find_account_sid_hits(text.encode()), f"{text!r} read as a cloud account SID"


def test_toggle_the_views_arm_and_the_rewrite_arm_each_carry_the_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    doubly = SHAPES["json_doubly_encoded_crlf"](MSA_SID)
    utf16 = SHAPES["utf16_be_no_bom"](MSA_SID)
    assert il.find_account_sid_hits(doubly) and il.find_account_sid_hits(utf16)
    monkeypatch.setattr(il, "ACCOUNT_SID_REWRITE_RE", NEVER)
    assert il.find_account_sid_hits(utf16), "with the rewrite arm off the views arm still reads UTF-16"
    monkeypatch.setattr(il, "ACCOUNT_SID_RE", NEVER)
    assert not il.find_account_sid_hits(doubly) and not il.find_account_sid_hits(utf16), "the probe fires with both arms off"


@pytest.mark.parametrize(("kind", "shape"), FAIL_CLOSED_CASES)
def test_a_shape_the_rewrite_cannot_clear_is_seen_and_fails_closed(kind: str, shape: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data = FAIL_CLOSED_SHAPES[shape](SIDS[kind])
    assert not il.account_sid_rewrite_would_change(data), f"the rewrite arm reads {shape}: the case does not isolate the views arm"
    assert il.find_account_sid_hits(data), f"the lock cannot see a {kind} SID written as {shape}"
    once, counts = _scrub(data)
    assert il.find_account_sid_hits(once) and counts["account"] == 0, f"the rewrite claims to clear {shape}"
    _plant(tmp_path / "run", "a.json", data)
    assert _dir(tmp_path, "--check") == 1
    assert _dir(tmp_path) == 1, "--dir exited 0 while an account SID the rewrite cannot clear remained"
    out = capsys.readouterr().out
    assert "does not clear" in out and SUBAUTH not in out


def test_inside_gzip_the_lock_reads_what_only_the_rewrite_reads() -> None:
    """The lock is never narrower than the rewrite, inside a gzip member too (the rewrite predicate recurses into gzip)."""
    data = SHAPES["gzip_percent_letter_before"](MSA_SID)
    assert not any(il.ACCOUNT_SID_RE.search(v) for v in il.views(data)), "the views see the SID: the case does not isolate the gzip arm"
    assert il.account_sid_rewrite_would_change(data) and il.find_account_sid_hits(data)
    assert _scrub(data)[1]["account"] == 1


# ---- tree mode: every tracked file, no scope -----------------------------------------------------------------------------------

def test_tree_mode_a_shape_the_rewrite_cannot_clear_exits_1_and_names_the_file(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    _plant(root, "docs/elsewhere/left.json", FAIL_CLOSED_SHAPES["percent_whole"](MSA_SID))
    _commit(root, "plant")
    log = tmp_path.parent / (tmp_path.name + "-residual-log.md")
    assert scrub.main(["--repo", str(root), "--log", str(log)]) == 1, "the scrub exited 0 leaving an account SID it cannot clear"
    text = log.read_text(encoding="utf-8")
    assert "does not clear (hand edit" in text and "docs/elsewhere/left.json" in text.split("does not clear (hand edit")[1]

def test_tree_mode_check_fires_outside_every_scope_then_the_scrub_clears_it(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    planted = {f"{kind}-{shape}": _plant(root, f"docs/elsewhere/{kind}-{shape}.json", SHAPES[shape](SIDS[kind])) for kind, shape in CASES}
    _commit(root, "plant")
    for r in planted.values():
        rel = r.relative_to(root).as_posix()
        assert not il.path_in_scope(rel, scrub.SID_SCOPE) and not il.path_in_scope(rel, scrub.USER_SCOPE)
    files = [*planted.values(), root / scrub.USER_BASELINE_PATH]
    problems = _check(root, files)
    for name, path in planted.items():
        assert any(path.name in p and "Entra ID account SID present" in p for p in problems), f"check() missed {name}"
    log = tmp_path.parent / (tmp_path.name + "-log.md")
    assert scrub.main(["--repo", str(root), "--log", str(log)]) == 0
    for name, path in planted.items():
        assert not il.find_account_sid_hits(path.read_bytes()), f"scrub.main left {name}"
    text = log.read_text(encoding="utf-8")
    assert SUBAUTH not in text and "cloud-account-SID occurrences" in text
    assert _check(root, files) == []


def test_toggle_check_is_blind_to_the_shape_with_the_account_rule_off(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _repo(tmp_path)
    p = _plant(root, OUTSIDE_EVERY_SCOPE, _record(ENTRA_SID))
    _commit(root, "plant")
    files = [p, root / scrub.USER_BASELINE_PATH]
    assert _check(root, files), "check() is silent on a cloud account SID"
    monkeypatch.setattr(il, "find_account_sid_hits", lambda data: False)
    assert _check(root, files) == [], "check() still fires with the account rule off: the probe does not isolate it"


def test_tree_mode_a_file_name_carrying_an_account_sid_fails_check_and_the_scrub(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _repo(tmp_path)
    p = _plant(root, f"docs/acl-{MSA_SID}.txt", b"clean")
    _commit(root, "plant")
    assert any("Entra ID account SID (rename it)" in x for x in _check(root, [p, root / scrub.USER_BASELINE_PATH]))
    log = tmp_path.parent / (tmp_path.name + "-name-log.md")
    assert scrub.main(["--repo", str(root), "--log", str(log)]) == 1
    assert SUBAUTH not in log.read_text(encoding="utf-8") and SUBAUTH not in capsys.readouterr().out


def test_tree_mode_a_binary_file_carrying_an_account_sid_is_reported_not_rewritten(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    data = b"\x00\x01bin " + MSA_SID.encode() + b" \x00\xff"
    p = _plant(root, "docs/blob.bin", data)
    _commit(root, "plant")
    log = tmp_path.parent / (tmp_path.name + "-bin-log.md")
    assert scrub.main(["--repo", str(root), "--log", str(log)]) == 1
    assert p.read_bytes() == data


# ---- --dir ---------------------------------------------------------------------------------------------------------------------

def test_dir_mode_rewrites_every_file_and_check_is_clean_after(tmp_path: Path) -> None:
    for kind, shape in CASES:
        _plant(tmp_path / "run", f"{kind}/{shape}.json", SHAPES[shape](SIDS[kind]))
    assert _dir(tmp_path, "--check") == 1
    assert _dir(tmp_path) == 0
    assert _dir(tmp_path, "--check") == 0
    assert all(not il.find_account_sid_hits(p.read_bytes()) for p in (tmp_path / "run").rglob("*") if p.is_file())


def test_dir_mode_fails_closed_on_a_name_and_on_a_zip_member(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _plant(tmp_path / "run", f"{ENTRA_SID}.txt", b"clean")
    assert _dir(tmp_path, "--check") == 1
    assert "NAME carries a Microsoft-account or Entra ID account SID" in capsys.readouterr().out
    (tmp_path / "run" / f"{ENTRA_SID}.txt").unlink()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("a.json", _record(MSA_SID))
    _plant(tmp_path / "run", "pack.zip", buf.getvalue())
    assert _dir(tmp_path, "--check") == 1
    assert SUBAUTH not in capsys.readouterr().out


# ---- the gate tree scan and the Hugging Face preflight ------------------------------------------------------------------------

def test_the_gate_tree_scan_names_an_account_sid_in_content_and_in_a_name(tmp_path: Path) -> None:
    sys.path.insert(0, str(REPO_ROOT / "tests" / "security"))
    import test_no_host_identity_in_tree as tree  # noqa: E402

    a = _plant(tmp_path, "a.json", _record(MSA_SID))
    b = _plant(tmp_path, f"{ENTRA_SID}.txt", b"clean")
    c = _plant(tmp_path, "c.json", _scrub(_record(MSA_SID))[0])
    hits = tree.scan(tmp_path, [a, b, c], frozenset(), frozenset(), ())
    assert hits["account_sid"] == ["a.json"] and hits["name"] == [f"{ENTRA_SID}.txt"]


@pytest.mark.parametrize("kind", sorted(SIDS))
def test_hf_preflight_refuses_an_account_sid_and_passes_the_placeholder(kind: str, tmp_path: Path) -> None:
    d = tmp_path / "ds"
    d.mkdir()
    (d / "t.json").write_bytes(_record(SIDS[kind]))
    assert any("Entra ID account SID" in h for h in hf_publish.preflight(d))
    (d / "t.json").write_bytes(_scrub(_record(SIDS[kind]))[0])
    assert not any("account SID" in h for h in hf_publish.preflight(d))


# ---- containers outside every scope --------------------------------------------------------------------------------------------

def _zip(member: str, body: bytes, compression: int = zipfile.ZIP_DEFLATED) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=compression) as z:
        z.writestr(member, body)
    return buf.getvalue()


def _tar(member: str, body: bytes) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        info = tarfile.TarInfo(member)
        info.size = len(body)
        t.addfile(info, io.BytesIO(body))
    return buf.getvalue()


def _gzip_n(body: bytes, n: int) -> bytes:
    for _ in range(n):
        body = gzip.compress(body, mtime=0)
    return body


CONTAINERS = {
    "zip_deflate.zip": lambda b: _zip("run/a.json", b),
    "zip_stored.zip": lambda b: _zip("run/a.json", b, zipfile.ZIP_STORED),
    "zip_in_zip.zip": lambda b: _zip("inner.zip", _zip("a.json", b)),
    "plain.bz2": lambda b: bz2.compress(b),
    "plain.xz": lambda b: lzma.compress(b),
    "gzip_x5.json.gz": lambda b: _gzip_n(b, 5),
    "gzip_x12.json.gz": lambda b: _gzip_n(b, 12),
    "archive.tar": lambda b: _tar("a.json", b),
    "archive.tgz": lambda b: gzip.compress(_tar("a.json", b)),
    "xz_of_zip.xz": lambda b: lzma.compress(_zip("a.json", b)),
}
UNREADABLE = {
    "truncated.bz2": lambda: bz2.compress(_record("none") * 50)[:-20],
    "damaged.zip": lambda: _zip("a.json", _record("none"))[:30] + b"\x00" * 40,
    "trailing.xz": lambda: lzma.compress(b"clean") + b"junk",
    "archive.7z": lambda: b"7z\xbc\xaf\x27\x1c" + b"\x00" * 32,
    "too_deep.json.gz": lambda: _gzip_n(b"clean", il.ACCOUNT_CONTAINER_MAX_DEPTH + 1),
}


@pytest.mark.parametrize("name", sorted(CONTAINERS))
def test_tree_check_and_the_gate_scan_open_every_container_outside_every_scope(name: str, tmp_path: Path) -> None:
    sys.path.insert(0, str(REPO_ROOT / "tests" / "security"))
    import test_no_host_identity_in_tree as tree  # noqa: E402

    root = _repo(tmp_path)
    dirty = _plant(root, f"docs/elsewhere/dirty-{name}", CONTAINERS[name](_record(MSA_SID)))
    clean = _plant(root, f"docs/elsewhere/clean-{name}", CONTAINERS[name](_record("S-1-5-32-544")))
    _commit(root, "plant")
    assert not il.path_in_scope(dirty.relative_to(root).as_posix(), scrub.SID_SCOPE)
    problems = _check(root, [dirty, clean, root / scrub.USER_BASELINE_PATH])
    assert any(dirty.name in p and "account SID present" in p for p in problems), f"check() did not open {name}"
    assert not any(clean.name in p for p in problems), f"check() flagged the clean twin of {name}"
    hits = tree.scan(root, [dirty, clean], frozenset(), frozenset(), ())
    assert hits["account_sid"] == [dirty.relative_to(root).as_posix()], f"the gate scan did not open {name}"
    log = tmp_path.parent / (tmp_path.name + "-container-log.md")
    assert scrub.main(["--repo", str(root), "--log", str(log)]) == 1, f"the tree scrub exited 0 with an account SID inside {name}"
    assert SUBAUTH not in log.read_text(encoding="utf-8")


@pytest.mark.parametrize("name", sorted(UNREADABLE))
def test_a_container_the_lock_cannot_read_fails_closed(name: str, tmp_path: Path) -> None:
    root = _repo(tmp_path)
    p = _plant(root, f"docs/elsewhere/{name}", UNREADABLE[name]())
    _commit(root, "plant")
    assert any("unreadable" in m for m in il.account_sid_container_problems(p.read_bytes(), name)), f"{name} read as clean"
    assert any(name in x and "unreadable" in x for x in _check(root, [p, root / scrub.USER_BASELINE_PATH]))


def test_toggle_check_is_blind_to_a_zipped_sid_with_the_container_reader_off(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _repo(tmp_path)
    p = _plant(root, "docs/elsewhere/pack.zip", _zip("a.json", _record(ENTRA_SID)))
    _commit(root, "plant")
    files = [p, root / scrub.USER_BASELINE_PATH]
    assert _check(root, files)
    monkeypatch.setattr(il, "account_sid_container_problems", lambda data, name="", _depth=0: [il.ACCOUNT_SID_PRESENT] if il.find_account_sid_hits(data) else [])
    assert _check(root, files) == [], "check() sees the zipped SID without the container reader: the probe does not isolate it"


# ---- the Hugging Face preflight: a file NAME carrying the SID --------------------------------------------------------------------

@pytest.mark.parametrize("kind", sorted(SIDS))
def test_hf_preflight_refuses_a_sid_named_file_and_never_prints_the_name(kind: str, tmp_path: Path) -> None:
    d = tmp_path / "ds"
    d.mkdir()
    (d / f"run-{SIDS[kind]}.json").write_bytes(b'{"arm": "a"}')
    hits = hf_publish.preflight(d)
    assert any("file name carries a Microsoft-account or Entra ID account SID" in h for h in hits), "the SID-named file passed"
    assert hits and all(h.startswith("file #0") for h in hits), f"a line does not show the name as file #0: {hits}"
    assert not any(SUBAUTH in h or SIDS[kind] in h for h in hits), "a FAIL line printed the SID"


# ---- no long part of the live account SID in the tree -----------------------------------------------------------------------------

LONG_SUBAUTHORITY_DIGITS = 8  # shorter sub-authorities collide with process IDs, ports and byte counts in evidence


def _account_subauthorities_from(whoami_groups_csv: str) -> list[str]:
    """The long (``LONG_SUBAUTHORITY_DIGITS`` or more digits) sub-authorities of each Microsoft-account / Entra ID SID in
    ``whoami /groups`` output."""
    sids = {m.group(0) for m in re.finditer(r"S-1-(?:11-96|12-1)(?:-[0-9]+)+", whoami_groups_csv)}
    return sorted({part for sid in sids for part in sid.split("-")[4:] if len(part) >= LONG_SUBAUTHORITY_DIGITS})


def _live_account_subauthorities() -> list[str]:
    """Read from the current token at test time; no value is written in the tree, and no digest of one (a hash of a ten-digit
    number is reversed by exhaustive search)."""
    out = subprocess.run(["whoami", "/groups", "/fo", "csv", "/nh"], capture_output=True, text=True, check=True,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    return _account_subauthorities_from(out)


def _subauthority_hits(root: Path, files: list[Path], parts: list[str]) -> list[str]:
    pat = re.compile(rb"(?<![0-9])(?:" + b"|".join(p.encode() for p in parts) + rb")(?![0-9])")
    return [f.relative_to(root).as_posix() for f in files if any(pat.search(v) for v in il.views(f.read_bytes()))]


def test_no_long_sub_authority_of_the_live_account_sid_is_in_any_tracked_file() -> None:
    """Runs and fails closed under an account whose token carries a Microsoft-account or Entra ID SID. Under a local account
    (the coder fleet's, a rebuilt machine) there is no subject to read: the test SKIPS with that reason, so the gap shows in
    the skip count, never as a pass."""
    parts = _live_account_subauthorities()
    if not parts:
        pytest.skip("no account SID in this token (no Microsoft-account or Entra ID group): the live sub-authority lock has no subject")
    files = [p for p in il.read_tracked(REPO_ROOT) if p.is_file()]
    assert files, "git ls-files returned nothing"
    hits = _subauthority_hits(REPO_ROOT, files, parts)
    assert not hits, ("tracked files carry a long sub-authority of the operator's account SID (the value is not printed). "
                      "If it is the identifier, scrub it with scripts/scrub_public_identifiers.py or by hand where the scrub "
                      "cannot reach it; if it is a coincidental number in a measurement record or other evidence, do not edit "
                      "the record: stop and report it.\n  " + "\n  ".join(hits))


WHOAMI_OPERATOR = ('"Everyone","Well-known group","S-1-1-0","Mandatory group"\n'
                   f'"MicrosoftAccount\\x","User","{MSA_SID}","Mandatory group"\n'
                   f'"AzureAD\\x","User","{ENTRA_SID}","Mandatory group"\n')
WHOAMI_LOCAL = ('"Everyone","Well-known group","S-1-1-0","Mandatory group"\n'
                '"BUILTIN\\Users","Alias","S-1-5-32-545","Mandatory group"\n'
                '"Mandatory Label\\Medium Mandatory Level","Label","S-1-16-8192",""\n')


def test_the_token_reader_keeps_only_long_sub_authorities_and_reads_nothing_from_a_local_account() -> None:
    parts = _account_subauthorities_from(WHOAMI_OPERATOR)
    assert SUBAUTH in parts and "50111" not in parts and "60222" not in parts, "a 5-digit sub-authority is matched"
    assert all(len(x) >= LONG_SUBAUTHORITY_DIGITS for x in parts) and len(parts) == 11  # 8 long in the MSA SID, 3 more in the Entra SID (the first is shared)
    assert _account_subauthorities_from(WHOAMI_LOCAL) == []


def test_under_a_local_account_the_lock_skips_with_its_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=WHOAMI_LOCAL, stderr=""))
    with pytest.raises(pytest.skip.Exception, match="no account SID in this token"):
        test_no_long_sub_authority_of_the_live_account_sid_is_in_any_tracked_file()


def test_toggle_the_sub_authority_scan_fires_on_a_planted_part_and_ignores_pids_and_ports(tmp_path: Path) -> None:
    parts = _account_subauthorities_from(WHOAMI_OPERATOR)
    dirty = _plant(tmp_path, "a.json", json.dumps({"n": parts[0]}).encode())
    glued = _plant(tmp_path, "b.txt", ("x" + parts[-1] + "-y").encode("utf-16"))
    clean = _plant(tmp_path, "c.txt", ("1" + parts[0] + "1").encode())
    pid = _plant(tmp_path, "d.json", json.dumps({"pid": 50111, "port": 60222}).encode())
    assert _subauthority_hits(tmp_path, [dirty, glued, clean, pid], parts) == ["a.json", "b.txt"]


# ---- container readers: names, magic or suffix alone, bounds, padding, scope -----------------------------------------------------

@pytest.mark.parametrize("kind", ["zip", "tar"])
def test_tree_mode_an_archive_member_named_after_the_sid_fails_check_the_gate_scan_and_the_scrub(kind: str, tmp_path: Path) -> None:
    sys.path.insert(0, str(REPO_ROOT / "tests" / "security"))
    import test_no_host_identity_in_tree as tree  # noqa: E402

    root = _repo(tmp_path)
    member = f"acl-{MSA_SID}.json"
    data = _zip(member, b"{}") if kind == "zip" else _tar(member, b"{}")
    p = _plant(root, f"docs/elsewhere/pack.{kind}", data)
    _commit(root, "plant")
    assert any("NAME carries a Microsoft-account or Entra ID account SID" in x for x in _check(root, [p, root / scrub.USER_BASELINE_PATH]))
    assert tree.scan(root, [p], frozenset(), frozenset(), ())["account_sid"] == [f"docs/elsewhere/pack.{kind}"]
    log = tmp_path.parent / (tmp_path.name + "-member-log.md")
    assert scrub.main(["--repo", str(root), "--log", str(log)]) == 1
    assert SUBAUTH not in log.read_text(encoding="utf-8")


DETECTION = {
    "bzip2 by magic, no suffix": ("run.dat", lambda b: bz2.compress(b)),
    "xz by magic, no suffix": ("run.dat", lambda b: lzma.compress(b)),
    "tar by magic, no suffix": ("run.dat", lambda b: _tar("a.json.gz", gzip.compress(b, mtime=0))),
    "zip by suffix, no magic": ("pack.zip", lambda b: b"JUNK" + _zip("a.json", b)),
}


@pytest.mark.parametrize("case", sorted(DETECTION))
def test_a_container_is_opened_by_its_magic_alone_and_by_its_suffix_alone(case: str) -> None:
    name, build = DETECTION[case]
    data = build(_record(MSA_SID))
    assert not il.find_account_sid_hits(data), f"{case}: the plain reading already sees the SID: the case does not isolate the reader"
    assert il.ACCOUNT_SID_PRESENT in " ".join(il.account_sid_container_problems(data, name)), f"{case}: not opened"


def test_the_size_bounds_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    body = _record("none") * 200
    monkeypatch.setattr(il, "ACCOUNT_CONTAINER_MAX_BYTES", len(body) - 1)
    assert any("over the size" in m for m in il.account_sid_container_problems(bz2.compress(body), "a.bz2"))
    assert any("over the size" in m for m in il.account_sid_container_problems(_zip("a.json", body), "a.zip"))
    assert any("over the size" in m for m in il.account_sid_container_problems(_tar("a.json", body), "a.tar"))
    monkeypatch.setattr(il, "ACCOUNT_CONTAINER_MAX_BYTES", len(body) + 1)
    assert il.account_sid_container_problems(bz2.compress(body), "a.bz2") == []


def test_undecodable_utf16_outside_every_scope_fails_closed(tmp_path: Path) -> None:
    data = (b"path=%41" + MSA_SID.encode()).decode().encode("utf-16") + b"\x00"  # only the rewrite reads this shape; the rewrite cannot decode it
    assert il.utf16_problem(data) and not any(il.ACCOUNT_SID_RE.search(v) for v in il.views(data))
    root = _repo(tmp_path)
    p = _plant(root, "docs/elsewhere/odd.txt", data)
    _commit(root, "plant")
    assert any("odd.txt" in x and "unreadable" in x for x in _check(root, [p, root / scrub.USER_BASELINE_PATH]))


def test_a_gzip_with_trailing_zero_padding_is_read_like_gzip_decompress(tmp_path: Path) -> None:
    clean = gzip.compress(b"clean", mtime=0) + b"\x00" * 512
    dirty = gzip.compress(_record(MSA_SID), mtime=0) + b"\x00" * 512
    assert gzip.decompress(clean) == b"clean"
    assert il.account_sid_container_problems(clean, "a.gz") == []
    assert il.account_sid_container_problems(dirty, "a.gz") == [il.ACCOUNT_SID_PRESENT]
    assert any("unreadable" in m for m in il.account_sid_container_problems(gzip.compress(b"x", mtime=0) + b"\x00junk", "a.gz"))


def test_inside_sid_scope_check_still_reports_an_account_sid_in_a_container(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    rel = scrub.SID_SCOPE[-1] + "/raw/run.json.bz2"
    p = _plant(root, rel, bz2.compress(_record(ENTRA_SID)))
    _commit(root, "plant")
    assert il.path_in_scope(rel, scrub.SID_SCOPE)
    assert any(rel in x and "account SID present" in x for x in _check(root, [p, root / scrub.USER_BASELINE_PATH]))
