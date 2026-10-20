"""Gate lock for machine / domain account SIDs in publishable run records: ``S-1-5-21-<a>-<b>-<c>[-<rid>]`` is rewritten to
``S-1-5-21-__MACHINE__[-<rid>]`` by ``scripts/scrub_public_identifiers.py`` (tracked files inside ``SID_SCOPE``, and every file of a
``--dir`` run), ``--check`` fails while one remains in that scope, and generic SIDs (BUILTIN groups, integrity levels, AppContainer
package SIDs, the local-system account) are untouched. The SIDs below are made up; none is this machine's.

Every encoding the lock claims to read is driven through the lock BEFORE the rewrite (it must fire) and after (it must be silent),
through ``check()``, tree-mode ``main()`` and ``--dir``; a lock that cannot read an encoding passes a silent-after assertion
trivially, so the fires-before assertion is the discriminating half. ``--dir`` fails closed on a SID in a name, an unreadable gzip
member and an archive.
"""

from __future__ import annotations

import gzip
import io
import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import identity_lock as il  # noqa: E402
import scrub_public_identifiers as scrub  # noqa: E402

ACCOUNT_SID = "S-1-5-21-4111222333-4222333444-4333444555-1001"
DOMAIN_ONLY = "S-1-5-21-4111222333-4222333444-4333444555"
PLACEHOLDER_ACCOUNT = "S-1-5-21-__MACHINE__-1001"
SUBAUTH = "4111222333"
GENERIC = ("S-1-5-32-544", "S-1-16-8192", "S-1-5-18", "S-1-5-114", "S-1-5-11",
           "S-1-15-2-969871995-3242822759-583047763-1618006129-3578262429-3647035748-2471858633")
IN_SCOPE = "docs/research/windows-containment-comparison-2026-10/mxc-1406-probe/raw/run-a.json"
OUT_OF_SCOPE = "docs/research/elsewhere/run-a.json"


def _record() -> bytes:
    doc = {"payload": {"token": {"user_sid": ACCOUNT_SID, "integrity_sid": "S-1-16-8192", "groups": list(GENERIC)}, "domain": DOMAIN_ONLY}}
    return json.dumps(doc, indent=1).encode("utf-8")


# Every encoding the lock claims to read, with the rewrite expected to clear it.
SHAPES = {
    "plain": lambda: _record(),
    "lowercase": lambda: _record().replace(b"S-1-5-21", b"s-1-5-21"),
    "utf16_bom": lambda: _record().decode().encode("utf-16"),
    "utf16_be_no_bom": lambda: _record().decode().encode("utf-16-be"),
    "gzip": lambda: gzip.compress(_record()),
    "gzip_of_utf16": lambda: gzip.compress(_record().decode().encode("utf-16")),
    "json_escaped_crlf": lambda: json.dumps({"stdout": "User Name SID\r\n" + ACCOUNT_SID}).encode(),
    "json_escaped_tab": lambda: json.dumps({"stdout": "x\t" + ACCOUNT_SID}).encode(),
    "json_escaped_u0053": lambda: ('{"sid": "\\u0053' + ACCOUNT_SID[1:] + '"}').encode(),
    "json_escaped_x53": lambda: ('{"sid": "\\x53' + ACCOUNT_SID[1:] + '"}').encode(),
    "percent_before": lambda: b"path=%5C" + ACCOUNT_SID.encode(),
    "ansi_before": lambda: b"\x1b[32m" + ACCOUNT_SID.encode() + b"\x1b[0m",
    "json_doubly_encoded_crlf": lambda: json.dumps({"event": "probe", "message": json.dumps({"stdout": "User Name SID\r\n" + ACCOUNT_SID})}).encode(),
    "percent_letter_before": lambda: b"path=%41" + ACCOUNT_SID.encode(),
    "sddl": lambda: ("O:" + ACCOUNT_SID + "G:" + DOMAIN_ONLY + "-513").encode(),
}
# Seen by the lock and not rewritten: the scrub reports them for a hand edit and exits 1.
FAIL_CLOSED_SHAPES = {
    "html_entity_first_letter": lambda: ("&#83;" + ACCOUNT_SID[1:]).encode(),
    "percent_digits_only": lambda: ("S-1-5-21-%34111222333-4222333444-4333444555-1001").encode(),
    "percent_whole": lambda: b"path=" + b"".join(b"%%%02X" % c for c in ACCOUNT_SID.encode()),
}


def _live() -> tuple[str, str]:
    host, user = il.live_names()
    assert host and user, "the host or user name is not readable on this machine"
    return host, user


def _scrub(data: bytes) -> tuple[bytes, dict[str, int]]:
    host, user = _live()
    return scrub.scrub_bytes(data, host=host, user=user, in_scope=False, sid_scope=True)


def _repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True, capture_output=True)
    scrub.save_user_baseline(tmp_path, {})
    _commit(tmp_path, "baseline")
    return tmp_path


def _commit(root: Path, msg: str) -> None:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True, env=env, capture_output=True)  # a scratch repository of this test's own files
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", msg], check=True, env=env, capture_output=True)


def _plant(root: Path, rel: str, data: bytes) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def _check(root: Path, files: list[Path]) -> list[str]:
    host, user = _live()
    return scrub.check(root, files, host, user, il.serial_digests())


def _dir(tmp_path: Path, *args: str) -> int:
    """Run ``--dir`` on ``tmp_path/run`` with the log kept outside the folder."""
    log = tmp_path / "scrub-log.md"
    return scrub.main(["--dir", str(tmp_path / "run"), "--log", str(log), *args])


# ---- the rewrite and the lock agree, per encoding ----------------------------------------------------------------------------

@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_lock_fires_before_the_rewrite_and_is_silent_after(shape: str) -> None:
    data = SHAPES[shape]()
    assert il.find_sid_hits(data), f"the lock cannot see a SID written as {shape}"
    once, counts = _scrub(data)
    assert counts["sid"] >= 1, f"the rewrite did not count the SID written as {shape}"
    assert not il.find_sid_hits(once), f"the rewrite left a SID written as {shape} that the lock still sees"
    twice, counts2 = _scrub(once)
    assert twice == once and counts2["sid"] == 0, f"the rewrite of {shape} is not idempotent"


def test_the_rewrite_keeps_the_relative_id_and_drops_every_sub_authority() -> None:
    for wrap in ("plain", "utf16_bom", "gzip"):
        once, counts = _scrub(SHAPES[wrap]())
        assert counts["sid"] == 2, "the rewrite counted a different number of account SIDs"
        text = " ".join(v.decode("utf-8", "ignore") for v in il.views(once))
        assert PLACEHOLDER_ACCOUNT in text and "S-1-5-21-__MACHINE__" in text, "the placeholder or the kept relative id is missing"
        assert SUBAUTH not in text, "a sub-authority survived"


@pytest.mark.parametrize("shape", sorted(FAIL_CLOSED_SHAPES))
def test_a_shape_the_rewrite_cannot_clear_is_seen_and_fails_closed(shape: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data = FAIL_CLOSED_SHAPES[shape]()
    assert il.find_sid_hits(data), f"the lock cannot see {shape}"
    once, counts = _scrub(data)
    assert il.find_sid_hits(once) and counts["sid"] == 0, f"the rewrite claims to clear {shape}"
    _plant(tmp_path / "run", "a.json", data)
    assert _dir(tmp_path, "--check") == 1
    assert _dir(tmp_path) == 1, "--dir exited 0 while a SID the rewrite cannot clear remained"
    out = capsys.readouterr().out
    assert "does not clear" in out and SUBAUTH not in out


def test_generic_sids_are_untouched() -> None:
    data = _record()
    once, _ = _scrub(data)
    doc = json.loads(once)
    assert doc["payload"]["token"]["integrity_sid"] == "S-1-16-8192"
    assert doc["payload"]["token"]["groups"] == list(GENERIC), "a generic SID was altered"
    assert not il.find_sid_hits(b" ".join(g.encode() for g in GENERIC)), "the lock flags a generic SID"


def test_a_sid_glued_after_a_letter_is_never_rewritten_into_a_wrong_value() -> None:
    """Current behaviour: ``userS-1-5-21-...`` is one token that is not a SID, so it is left as written. A later fix may flag or
    rewrite it; the one thing it may not do is leave a changed value that still carries the sub-authorities."""
    data = ("user" + ACCOUNT_SID).encode()
    out, counts = _scrub(data)
    assert out == data or (SUBAUTH.encode() not in out and counts["sid"] >= 1), "the glued SID was rewritten into a value that still carries it"


def _sid_rewrite(data: bytes) -> bytes:
    """The bytes ``--dir`` writes for ``data`` with only the SID rule on: the container dispatch itself, never a single arm of it."""
    return scrub.scrub_bytes(data, host=None, user=None, in_scope=False, sid_scope=True)[0]


CONTAINERS = {
    "identity": lambda b: b,
    "prefix": lambda b: b"x " + b,
    "json": lambda b: json.dumps({"m": b.decode("latin-1")}).encode(),
    "json_twice": lambda b: json.dumps({"m": json.dumps({"m": b.decode("latin-1")})}).encode(),
    "gzip": gzip.compress,
    "utf16_bom": lambda b: b.decode("latin-1").encode("utf-16"),
    "utf16_le_no_bom": lambda b: b.decode("latin-1").encode("utf-16-le"),
    "utf16_be_no_bom": lambda b: b.decode("latin-1").encode("utf-16-be"),
    "gzip_of_utf16": lambda b: gzip.compress(b.decode("latin-1").encode("utf-16")),
}
PROPERTY_SHAPES = {**SHAPES, "glued_json_n": lambda: b"a\\n" + ACCOUNT_SID.encode()}


@pytest.mark.parametrize("container", sorted(CONTAINERS))
@pytest.mark.parametrize("shape", sorted(PROPERTY_SHAPES))
def test_the_lock_is_never_narrower_than_the_rewrite(shape: str, container: str) -> None:
    """Invariant: when ``scrub_bytes`` (the rewrite ``--dir`` runs, container dispatch included) changes the bytes, the lock fires
    on them, for every shape inside every container; and the rewrite arm of the lock agrees with the rewrite in both directions."""
    data = CONTAINERS[container](PROPERTY_SHAPES[shape]())
    changed = _sid_rewrite(data) != data
    if changed:
        assert il.find_sid_hits(data), f"the rewrite changes {shape} in {container} but the lock is silent"
    assert il.sid_rewrite_would_change(data) == changed, f"the lock's rewrite arm disagrees with the rewrite on {shape} in {container}"


def test_the_rewrite_changes_something_in_every_container_the_property_walks() -> None:
    """The property is not vacuous: the plain shape is rewritten inside every container."""
    for container, wrap in sorted(CONTAINERS.items()):
        data = wrap(PROPERTY_SHAPES["json_doubly_encoded_crlf"]())
        assert _sid_rewrite(data) != data, f"the rewrite left the doubly encoded record untouched in {container}"


@pytest.mark.parametrize("container", ["gzip", "utf16_bom", "utf16_le_no_bom", "utf16_be_no_bom", "gzip_of_utf16"])
@pytest.mark.parametrize("shape", ["json_doubly_encoded_crlf", "percent_letter_before"])
def test_raw_bytes_only_lock_misses_what_the_rewrite_clears_inside_a_container(shape: str, container: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Toggle: the round-2 lock (the rewrite pattern on the raw bytes, plus the decoded views' plain SID scan) certifies these as
    clean while the rewrite changes them; the current lock fires. A property that cannot fail on the old lock proves nothing."""
    data = CONTAINERS[container](PROPERTY_SHAPES[shape]())
    assert _sid_rewrite(data) != data
    assert il.find_sid_hits(data), "the current lock is silent on a record the rewrite changes"
    monkeypatch.setattr(il, "sid_rewrite_would_change", lambda d, _depth=0: il.SID_REWRITE_RE.search(d) is not None)
    assert not il.find_sid_hits(data), f"the raw-bytes-only lock already sees {shape} in {container}: the toggle does not discriminate"


def _damaged_deflate() -> bytes:
    good = gzip.compress(b"abc")
    return good[:10] + b"\xff" * 20 + good[-8:]


# Input the rewrite cannot read; each used to raise somewhere on a check or rewrite path.
UNREADABLE = {
    "gzip_damaged_deflate": _damaged_deflate,
    "gzip_trailing_bytes": lambda: gzip.compress(b"x") + b"trailing",
    "nul_heavy_odd_length_binary": lambda: b"\0" * 20 + b"\x01",
    "utf16_lone_surrogate": lambda: b"\xff\xfe" + b"\x00\xd8" + b"a\0",
}


def _no_sid_label(lines: list[str]) -> bool:
    return not any("SID" in ln for ln in lines)


@pytest.mark.parametrize("name", sorted(UNREADABLE))
def test_unreadable_input_is_reported_as_unreadable_by_the_lock(name: str) -> None:
    data = UNREADABLE[name]()
    assert il.unreadable_reason(data), f"{name} is not named unreadable"
    assert not il.sid_rewrite_would_change(data), "an unreadable file is labelled a SID rewrite"
    il.find_sid_hits(data)  # never raises
    out, counts = _sid_rewrite(data), _scrub(data)[1]
    assert out == data and counts.get("unreadable") == 1, "scrub_bytes changed or mis-counted an unreadable input"


@pytest.mark.parametrize("name", sorted(UNREADABLE))
def test_dir_check_reports_unreadable_input_and_keeps_going(name: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _plant(tmp_path / "run", "a.txt", ACCOUNT_SID.encode())
    _plant(tmp_path / "run", "z.bin", UNREADABLE[name]())
    _plant(tmp_path / "run", "zz.txt", ACCOUNT_SID.encode())
    assert _dir(tmp_path, "--check") == 1
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("FAIL")]
    assert any("z.bin: unreadable" in ln for ln in lines), lines
    assert any("zz.txt" in ln for ln in lines), "the walk stopped at the unreadable file"
    assert not any("z.bin" in ln and "SID" in ln for ln in lines), "an unreadable file was labelled a SID"


@pytest.mark.parametrize("name", sorted(UNREADABLE))
def test_dir_rewrite_refuses_the_whole_run_before_writing_and_writes_the_log(name: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    a = _plant(tmp_path / "run", "a.txt", ACCOUNT_SID.encode())
    _plant(tmp_path / "run", "z.bin", UNREADABLE[name]())
    assert _dir(tmp_path) == 1
    assert a.read_bytes() == ACCOUNT_SID.encode(), "a file was rewritten in a run that could not finish"
    log = (tmp_path / "scrub-log.md").read_text(encoding="utf-8")
    assert "run refused" in log and "z.bin: unreadable" in log, "the refused run left no record"
    out = capsys.readouterr().out
    assert "run refused" in out and SUBAUTH not in out + log


def test_dir_rewrite_without_an_unreadable_file_still_rewrites(tmp_path: Path) -> None:
    a = _plant(tmp_path / "run", "a.txt", ACCOUNT_SID.encode())
    assert _dir(tmp_path) == 0 and SUBAUTH.encode() not in a.read_bytes()


def test_tree_mode_reports_unreadable_input_and_never_raises(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    for i, name in enumerate(sorted(UNREADABLE)):
        _plant(root, f"{IN_SCOPE.rsplit('/', 1)[0]}/u{i}.json", UNREADABLE[name]())
    _commit(root, "unreadable")
    files = [p for p in il.read_tracked(root) if p.is_file()]
    problems = _check(root, files)
    assert sum("unreadable" in p for p in problems) == len(UNREADABLE), problems
    assert scrub.main(["--repo", str(root), "--log", str(tmp_path / "t.md")]) == 1


# A SID the views arm cannot read (percent-escaped first letter), in UTF-16 with a trailing odd byte: only the fail-closed
# branch for unreadable UTF-16 stands between this file and a clean --check.
def _utf16_percent_sid_odd() -> bytes:
    return (b"path=%41" + ACCOUNT_SID.encode()).decode().encode("utf-16") + b"\x00"


def test_unreadable_utf16_with_a_hidden_sid_fails_closed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data = _utf16_percent_sid_odd()
    assert not any(il.MACHINE_SID_RE.search(v) for v in il.views(data)), "the views arm already sees the SID: the case does not isolate the branch"
    assert il.unreadable_reason(data)
    _plant(tmp_path / "run", "u.txt", data)
    assert _dir(tmp_path, "--check") == 1
    assert "u.txt: unreadable" in capsys.readouterr().out


def test_unreadable_utf16_toggle_without_the_branch_the_hidden_sid_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Toggle: with the unreadable-UTF-16 report removed, the same file passes ``--dir --check``."""
    _plant(tmp_path / "run", "u.txt", _utf16_percent_sid_odd())
    monkeypatch.setattr(il, "utf16_problem", lambda data: None)
    assert _dir(tmp_path, "--check") == 0, "the file is refused by something other than the unreadable-UTF-16 branch"


def test_find_sid_hits_fires_whenever_the_rewrite_would_change_the_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Toggle: with the rewrite arm removed from the lock, the doubly encoded record is certified clean."""
    data = SHAPES["json_doubly_encoded_crlf"]()
    assert il.find_sid_hits(data)
    monkeypatch.setattr(il, "SID_REWRITE_RE", re.compile(rb"(?!)"))
    assert not il.find_sid_hits(data), "the decoded views alone now see the doubly encoded record: the toggle proves nothing"


def test_dir_check_fires_on_a_shape_only_the_rewrite_reads_and_clears_after(tmp_path: Path) -> None:
    run = tmp_path / "run"
    _plant(run, "a.json", SHAPES["json_doubly_encoded_crlf"]())
    _plant(run, "b.txt", SHAPES["percent_letter_before"]())
    assert _dir(tmp_path, "--check") == 1
    assert _dir(tmp_path) == 0
    assert _dir(tmp_path, "--check") == 0


# ---- tree mode ---------------------------------------------------------------------------------------------------------------

def test_tree_mode_names_every_encoding_then_clears_it(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    clearable = sorted(SHAPES)
    planted = {name: _plant(root, f"docs/research/windows-containment-comparison-2026-10/mxc-1406-probe/raw/{name}.json", SHAPES[name]()) for name in clearable}
    outside = _plant(root, OUT_OF_SCOPE, _record())
    _commit(root, "plant")
    baseline = root / scrub.USER_BASELINE_PATH
    problems = _check(root, [*planted.values(), outside, baseline])
    for name, path in planted.items():
        assert any(path.name in p and "SID" in p for p in problems), f"check() missed the SID written as {name}"
    assert not any(OUT_OF_SCOPE in p for p in problems), "check() flagged a file outside SID_SCOPE"
    log = tmp_path.parent / (tmp_path.name + "-log.md")
    assert scrub.main(["--repo", str(root), "--log", str(log)]) == 0, "scrub.main exited non-zero on rewritable SIDs"
    for name, path in planted.items():
        assert not il.find_sid_hits(path.read_bytes()), f"scrub.main left the SID written as {name}"
    assert il.find_sid_hits(outside.read_bytes()), "scrub.main rewrote a file outside SID_SCOPE"
    assert SUBAUTH not in log.read_text(encoding="utf-8"), "the log carries a sub-authority"
    assert _check(root, [*planted.values(), outside, baseline]) == [], "check() still fails after the rewrite"


def test_tree_mode_file_name_carrying_a_sid_fails_check_and_the_scrub(tmp_path: Path) -> None:
    """The name rules apply to every tracked file, not only ``SID_SCOPE``: ``check()`` names it and the rewriting run exits 1."""
    root = _repo(tmp_path)
    named = _plant(root, f"docs/research/elsewhere/acl-{ACCOUNT_SID}.json", b"{}")
    _commit(root, "plant")
    baseline = root / scrub.USER_BASELINE_PATH
    assert any("file NAME carries a machine/domain account SID" in p for p in _check(root, [named, baseline])), "check() missed a SID in a file name"
    log = tmp_path.parent / (tmp_path.name + "-log.md")
    assert scrub.main(["--repo", str(root), "--log", str(log)]) == 1, "the rewriting run waved a SID-named file through"
    text = log.read_text(encoding="utf-8")
    assert "a file name carrying a SID" in text and SUBAUTH not in text, "the name was not reported, or it was printed"


def test_dir_without_log_outside_a_checkout_is_a_clean_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    run = tmp_path / "run"
    _plant(run, "a.json", b"{}")
    elsewhere = tmp_path / "not-a-checkout"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    assert scrub.main(["--dir", str(run)]) == 1
    assert "--log" in capsys.readouterr().err


def test_tree_mode_exits_1_on_an_opaque_binary_carrying_a_sid(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    blob = b"\0\0\0\0\x01\x02" + ACCOUNT_SID.encode() + b"\0\0\x03"
    inside = _plant(root, IN_SCOPE, blob)
    _commit(root, "plant")
    log = tmp_path.parent / (tmp_path.name + "-log.md")
    assert scrub.main(["--repo", str(root), "--log", str(log)]) == 1, "an opaque binary carrying a SID was waved through"
    assert inside.read_bytes() == blob, "an opaque binary was rewritten"
    assert "NOT rewritten" in log.read_text(encoding="utf-8")


def test_tree_mode_exits_1_on_a_sid_shape_the_rewrite_does_not_clear(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    _plant(root, IN_SCOPE, FAIL_CLOSED_SHAPES["html_entity_first_letter"]())
    _commit(root, "plant")
    log = tmp_path.parent / (tmp_path.name + "-log.md")
    assert scrub.main(["--repo", str(root), "--log", str(log)]) == 1, "a SID the rewrite cannot clear was waved through"
    assert "does not clear" in log.read_text(encoding="utf-8")


def test_removing_the_sid_rule_blinds_the_probe_and_the_rewrite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _repo(tmp_path)
    inside = _plant(root, IN_SCOPE, _record())
    baseline = root / scrub.USER_BASELINE_PATH
    assert any("SID" in p for p in _check(root, [inside, baseline])), "control: the probe must fail with the rule engaged"
    never = __import__("re").compile(rb"(?!x)x")
    monkeypatch.setattr(il, "MACHINE_SID_RE", never)
    monkeypatch.setattr(il, "SID_REWRITE_RE", never)
    assert not any("SID" in p for p in _check(root, [inside, baseline])), "toggle: with the rule off the probe still fails"
    assert _scrub(_record())[0] == _record(), "toggle: with the rule off the rewrite still changed bytes"


def test_sid_scope_names_tracked_files() -> None:
    """A scope entry that matches nothing is a lock that watches nothing."""
    tracked = [p.relative_to(REPO_ROOT).as_posix() for p in il.read_tracked(REPO_ROOT)]
    for entry in scrub.SID_SCOPE:
        assert any(il.path_in_scope(t, (entry,)) for t in tracked), f"SID_SCOPE entry {entry!r} matches no tracked file"
    assert il.path_in_scope("docs/performance/mxc_proxy_egress_2026-10-15.json", scrub.SID_SCOPE)
    assert il.path_in_scope("docs/performance/mxc_proxy_egress_2026-11-01.json", scrub.SID_SCOPE), "a later dated record is outside the scope"
    assert il.path_in_scope("docs/research/windows-containment-comparison-2026-10/mxc-1406-probe/raw/batch-header.json", scrub.SID_SCOPE)
    assert not il.path_in_scope("docs/performance/other.json", scrub.SID_SCOPE)


# ---- --dir -------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_dir_check_fires_before_and_is_silent_after(shape: str, tmp_path: Path) -> None:
    _plant(tmp_path / "run", "a.bin" if shape.startswith(("gzip", "utf16")) else "a.json", SHAPES[shape]())
    assert _dir(tmp_path, "--check") == 1, f"--dir --check passed with a SID written as {shape}"
    assert _dir(tmp_path) == 0, f"--dir exited non-zero on a SID written as {shape}"
    assert _dir(tmp_path, "--check") == 0, f"--dir --check failed after the rewrite of {shape}"


def test_dir_mode_rewrites_a_tree_and_keeps_generic_sids(tmp_path: Path) -> None:
    run = tmp_path / "run"
    _plant(run, "run-a.json", _record())
    _plant(run, "staging/run-b.json", _record())
    assert _dir(tmp_path, "--check") == 1
    assert _dir(tmp_path) == 0
    assert _dir(tmp_path, "--check") == 0
    for f in run.rglob("*.json"):
        raw = f.read_bytes()
        assert SUBAUTH.encode() not in raw and b"S-1-16-8192" in raw and b"S-1-5-32-544" in raw


def test_dir_mode_fails_closed_on_a_sid_in_a_file_or_folder_name(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run = tmp_path / "run"
    _plant(run, f"{ACCOUNT_SID}/ntuser.txt", b"clean")
    _plant(run, f"acl-{ACCOUNT_SID}.json", b"{}")
    assert _dir(tmp_path, "--check") == 1, "--dir --check passed with a SID in a name"
    assert _dir(tmp_path) == 1, "--dir exited 0 with a SID in a name it cannot rewrite"
    out = capsys.readouterr().out
    assert "NAME carries a machine/domain account SID" in out and SUBAUTH not in out, "the name was not reported, or it was printed"


def test_dir_mode_fails_closed_on_a_gzip_member_with_trailing_bytes(tmp_path: Path) -> None:
    _plant(tmp_path / "run", "a.gz", gzip.compress(_record()) + b"trailing")
    assert _dir(tmp_path, "--check") == 1, "an unreadable gzip member passed --dir --check"
    assert _dir(tmp_path) == 1, "an unreadable gzip member passed --dir"


def test_dir_mode_passes_a_clean_gzip_with_a_second_member(tmp_path: Path) -> None:
    clean = b'{"k": "v"}'
    _plant(tmp_path / "run", "a.gz", gzip.compress(clean) + gzip.compress(clean))
    assert _dir(tmp_path, "--check") == 0


def _zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, body in members.items():
            z.writestr(name, body)
    return buf.getvalue()


def test_dir_mode_scans_a_zip_and_never_rewrites_it(tmp_path: Path) -> None:
    blob = _zip({"inner/a.json": _record()})
    _plant(tmp_path / "run", "bundle.zip", blob)
    assert _dir(tmp_path, "--check") == 1, "a SID inside a zip member passed --dir --check"
    assert _dir(tmp_path) == 1, "--dir exited 0 while a zip member still carried a SID"
    assert (tmp_path / "run" / "bundle.zip").read_bytes() == blob, "a zip was rewritten in place"


def test_dir_mode_flags_a_zip_member_name_and_passes_a_clean_zip(tmp_path: Path) -> None:
    _plant(tmp_path / "run", "named.zip", _zip({f"acl-{ACCOUNT_SID}.json": b"{}"}))
    assert _dir(tmp_path, "--check") == 1, "a SID in a zip member NAME passed"
    clean = tmp_path / "clean"
    _plant(clean, "ok.zip", _zip({"a.json": b'{"k": "v"}'}))
    assert scrub.main(["--dir", str(clean), "--check"]) == 0, "a clean zip failed"


@pytest.mark.parametrize("name,body", [
    ("damaged.zip", b"PK\x03\x04 not really a zip"),
    ("bundle.7z", b"7z\xbc\xaf\x27\x1c" + b"\x01" * 40),
    ("bundle.rar", b"Rar!\x1a\x07\x00" + b"\x01" * 40),
    ("bundle.xz", b"\xfd7zXZ\x00" + b"\x01" * 40),
])
def test_dir_mode_fails_closed_on_an_archive_it_cannot_read(name: str, body: bytes, tmp_path: Path) -> None:
    _plant(tmp_path / "run", name, body)
    assert _dir(tmp_path, "--check") == 1, f"{name}: an unreadable archive passed --dir --check"
    assert _dir(tmp_path) == 1, f"{name}: an unreadable archive passed --dir"


def test_dir_mode_fails_closed_on_a_tar_gz(tmp_path: Path) -> None:
    buf = io.BytesIO()
    import tarfile
    with tarfile.open(fileobj=buf, mode="w") as t:
        info = tarfile.TarInfo("a.json")
        info.size = len(_record())
        t.addfile(info, io.BytesIO(_record()))
    _plant(tmp_path / "run", "bundle.tar.gz", gzip.compress(buf.getvalue()))
    assert _dir(tmp_path, "--check") == 1, "a tar.gz passed --dir --check"
    assert _dir(tmp_path) == 1, "a tar.gz passed --dir"


def test_dir_mode_writes_a_log_without_names_or_sub_authorities(tmp_path: Path) -> None:
    run = tmp_path / "run"
    _plant(run, "secret-looking-name.json", _record())
    log = tmp_path / "log.md"
    assert scrub.main(["--dir", str(run), "--log", str(log)]) == 0
    text = log.read_text(encoding="utf-8")
    assert "secret-looking-name" not in text and SUBAUTH not in text, "the log carries a name or a sub-authority"
    assert "| 0 |" in text and text.count("sha256 before") == 1, "the log has no row for the rewritten file"


def test_dir_mode_refuses_a_log_inside_the_folder(tmp_path: Path) -> None:
    run = tmp_path / "run"
    _plant(run, "a.json", _record())
    with pytest.raises(SystemExit):
        scrub.main(["--dir", str(run), "--log", str(run / "log.md")])
    assert il.find_sid_hits((run / "a.json").read_bytes()), "the folder was rewritten before the refusal"


def test_tree_mode_fails_closed_on_an_unreadable_gzip_and_an_archive_in_scope(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    base = "docs/research/windows-containment-comparison-2026-10/mxc-1406-probe/raw"
    clean = b'{"k": "v"}'
    bad = _plant(root, f"{base}/trailing.json.gz", gzip.compress(clean) + b"trailing")
    arch = _plant(root, f"{base}/bundle.zip", _zip({"a.json": clean}))
    _commit(root, "plant")
    problems = _check(root, [bad, arch, root / scrub.USER_BASELINE_PATH])
    assert any("trailing.json.gz" in p and "gzip member that cannot be read" in p for p in problems), "check() passed an unreadable gzip in scope"
    log = tmp_path.parent / (tmp_path.name + "-log.md")
    assert scrub.main(["--repo", str(root), "--log", str(log)]) == 1, "scrub.main passed an unreadable gzip or an archive in SID_SCOPE"
    text = log.read_text(encoding="utf-8")
    assert "trailing.json.gz" in text and "bundle.zip" in text, "the log does not name the files for a hand edit"
    assert arch.read_bytes() == _zip({"a.json": clean}) or zipfile.is_zipfile(arch), "a tracked archive was rewritten"


# ---- round 5: a rewriting --dir either rewrites everything or nothing, and always writes its log ------------------------------

import contextlib  # noqa: E402
import stat  # noqa: E402


@contextlib.contextmanager
def _read_only(path: Path):
    path.chmod(stat.S_IREAD)
    try:
        yield
    finally:
        path.chmod(stat.S_IREAD | stat.S_IWRITE)


@contextlib.contextmanager
def _read_denied(path: Path):
    who = os.environ.get("USERNAME") or il.live_names()[1]
    subprocess.run(["icacls", str(path), "/deny", f"{who}:(R)"], check=True, capture_output=True)
    try:
        yield
    finally:
        subprocess.run(["icacls", str(path), "/remove:d", who], check=True, capture_output=True)


def _assert_refused_before_writing(tmp_path: Path, a: Path, out: str, what: str) -> None:
    assert a.read_bytes() == ACCOUNT_SID.encode(), f"{what}: a file was rewritten in a run that could not finish"
    log = (tmp_path / "scrub-log.md").read_text(encoding="utf-8")
    assert "run refused" in out and "run refused" in log, f"{what}: the refused run left no record"
    assert SUBAUTH not in out + log


def test_dir_rewrite_refuses_a_read_only_file_before_writing_anything(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    a = _plant(tmp_path / "run", "a.txt", ACCOUNT_SID.encode())
    z = _plant(tmp_path / "run", "z.txt", ACCOUNT_SID.encode())
    with _read_only(z):
        assert _dir(tmp_path, "--check") == 1
        capsys.readouterr()
        assert _dir(tmp_path) == 1
    out = capsys.readouterr().out
    _assert_refused_before_writing(tmp_path, a, out, "read-only file")
    assert "cannot be written" in out


def test_dir_rewrite_refuses_a_read_denied_file_before_writing_anything(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    a = _plant(tmp_path / "run", "a.txt", ACCOUNT_SID.encode())
    z = _plant(tmp_path / "run", "z.txt", b"x")
    with _read_denied(z):
        assert _dir(tmp_path, "--check") == 1, "--dir --check passed or crashed on a file it cannot read"
        capsys.readouterr()
        assert _dir(tmp_path) == 1
    out = capsys.readouterr().out
    _assert_refused_before_writing(tmp_path, a, out, "read-denied file")
    assert "cannot be read" in out


def test_dir_rewrite_refuses_a_file_name_that_cannot_be_encoded(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    a = _plant(tmp_path / "run", "a.txt", ACCOUNT_SID.encode())
    _plant(tmp_path / "run", "z\udc80.txt", b"x")
    assert _dir(tmp_path, "--check") == 1, "--dir --check passed or crashed on a name it cannot encode"
    capsys.readouterr()
    assert _dir(tmp_path) == 1
    out = capsys.readouterr().out
    _assert_refused_before_writing(tmp_path, a, out, "unencodable name")
    assert "cannot be encoded" in out and "file #" in out


def test_dir_rewrite_restores_the_files_it_wrote_when_a_later_write_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    a = _plant(tmp_path / "run", "a.txt", ACCOUNT_SID.encode())
    b = _plant(tmp_path / "run", "b.txt", ACCOUNT_SID.encode())
    real = Path.write_bytes

    def flaky(self: Path, data: bytes) -> int:
        if self.name == "b.txt" and data != ACCOUNT_SID.encode():
            raise PermissionError("denied after the pre-pass")
        return real(self, data)

    monkeypatch.setattr(Path, "write_bytes", flaky)
    assert _dir(tmp_path) == 1
    out = capsys.readouterr().out
    assert a.read_bytes() == b.read_bytes() == ACCOUNT_SID.encode(), "a half-finished run left a rewritten file behind"
    assert "write failed" in out and "restored" in out
    assert "run refused" in (tmp_path / "scrub-log.md").read_text(encoding="utf-8")


def test_the_staged_run_toggle_without_the_writability_proof_the_rollback_still_holds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Toggle: with the pre-pass writability probe made to succeed, the read-only file fails at write time instead, so the message
    changes from 'cannot be written' to 'write failed' (the probe is what the test above reads) and the rollback keeps the folder whole."""
    a = _plant(tmp_path / "run", "a.txt", ACCOUNT_SID.encode())
    z = _plant(tmp_path / "run", "z.txt", ACCOUNT_SID.encode())
    real_open = open

    def open_ok(file, mode="r", *args, **kw):
        return real_open(file, "rb") if mode == "r+b" else real_open(file, mode, *args, **kw)

    monkeypatch.setattr("builtins.open", open_ok)
    with _read_only(z):
        assert _dir(tmp_path) == 1
    out = capsys.readouterr().out
    assert "write failed" in out and "cannot be written" not in out
    assert a.read_bytes() == ACCOUNT_SID.encode(), "the rollback left a rewritten file behind"


def test_a_sid_named_unreadable_file_is_shown_as_file_number_in_a_rewriting_run(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    _plant(tmp_path / "run", "a.txt", ACCOUNT_SID.encode())
    _plant(tmp_path / "run", f"acl-{ACCOUNT_SID}.bin", _damaged_deflate())
    assert _dir(tmp_path) == 1
    out = capsys.readouterr().out
    assert "unreadable" in out and "file #1" in out and SUBAUTH not in out, out
    # Toggle: with the name rule removed the same run prints the sub-authorities, so the assertion above reads the redaction.
    monkeypatch.setattr(il, "find_sid_hits", lambda data: False)
    assert _dir(tmp_path) == 1
    assert SUBAUTH in capsys.readouterr().out


def _gzip_n(data: bytes, n: int) -> bytes:
    for _ in range(n):
        data = gzip.compress(data)
    return data


def test_a_sid_free_gzip_nested_past_the_cap_is_unreadable_not_a_sid(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data = _gzip_n(b"hello world\n", 5)
    assert "nesting depth" in (il.unreadable_reason(data) or "")
    assert not il.sid_rewrite_would_change(data) and not il.find_sid_hits(data)
    assert scrub.scrub_bytes(data, host=None, user=None, in_scope=False, sid_scope=True) == (data, {"host": 0, "user": 0, "serial": 0, "sid": 0, "account": 0, "unreadable": 1})
    _plant(tmp_path / "run", "z.gz", data)
    assert _dir(tmp_path, "--check") == 1
    out = capsys.readouterr().out
    assert "z.gz: unreadable (nesting depth)" in out and "identifier present" not in out and "SID" not in out


def test_a_gzip_nested_to_the_cap_is_still_read_and_cleared(tmp_path: Path) -> None:
    data = _gzip_n(ACCOUNT_SID.encode(), 4)
    assert il.unreadable_reason(data) is None and il.find_sid_hits(data)
    _plant(tmp_path / "run", "z.gz", data)
    assert _dir(tmp_path) == 0 and _dir(tmp_path, "--check") == 0


def test_gzip_depth_toggle_without_the_cap_the_deep_member_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Toggle: with the depth cap lifted, the five-deep gzip is read as clean and ``--dir --check`` exits 0."""
    _plant(tmp_path / "run", "z.gz", _gzip_n(b"hello world\n", 5))
    monkeypatch.setattr(il, "GZIP_MAX_DEPTH", 99)
    assert _dir(tmp_path, "--check") == 0


def test_a_dir_run_counts_one_unreadable_file_once(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _plant(tmp_path / "run", "z.gz", _damaged_deflate())
    assert _dir(tmp_path) == 1
    out = capsys.readouterr().out
    fails = [ln for ln in out.splitlines() if ln.startswith("FAIL")]
    assert len(fails) == len(set(fails)) and sum("unreadable" in ln for ln in fails) == 1, fails
    assert f"{len(fails)} finding(s)" in out


# ---- round 5: UTF-32 text, with and without a byte-order mark, is read by the lock and the rewrite ----------------------------

def _wide_text() -> str:
    host, _ = _live()
    return f"computer {host} sid {ACCOUNT_SID} end " * 3


UTF32 = {
    "utf32_le_no_bom": lambda t: t.encode("utf-32-le"),
    "utf32_be_no_bom": lambda t: t.encode("utf-32-be"),
    "utf32_le_bom": lambda t: t.encode("utf-32"),
    "utf32_be_bom": lambda t: b"\x00\x00\xfe\xff" + t.encode("utf-32-be"),
}


@pytest.mark.parametrize("name", sorted(UTF32))
def test_utf32_text_is_read_by_the_lock_and_cleared_by_the_rewrite(name: str, tmp_path: Path) -> None:
    host, _ = _live()
    data = UTF32[name](_wide_text())
    assert il.find_sid_hits(data), f"the SID lock cannot read {name}"
    assert il.find_hits(data, il.digests_with_live(host, None)[0], frozenset())[0], f"the host lock cannot read {name}"
    assert il.unreadable_reason(data) is None
    _plant(tmp_path / "run", "w.txt", data)
    assert _dir(tmp_path, "--check") == 1, f"--dir --check passed {name}"
    assert _dir(tmp_path) == 0
    after = (tmp_path / "run" / "w.txt").read_bytes()
    assert il.looks_utf16(after) == il.looks_utf16(data), "the rewrite changed the encoding"
    assert not il.find_sid_hits(after) and not il.find_hits(after, il.digests_with_live(host, None)[0], frozenset())[0]
    assert _dir(tmp_path, "--check") == 0


@pytest.mark.parametrize("name", ["utf32_le_no_bom", "utf32_be_no_bom"])
def test_utf32_toggle_with_the_old_detection_the_sid_passes(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Toggle: with the round-4 detection (UTF-16 only), ASCII in UTF-32 is read as UTF-16, the SID is not seen, and the lock passes."""
    data = UTF32[name](_wide_text())

    def utf16_only(d: bytes) -> str | None:
        sample = d[:4096]
        if len(sample) >= 8 and sample.count(b"\0") * 2 >= len(sample) * 0.8:
            return "utf-16-le" if sample[1:2] == b"\0" else "utf-16-be"
        return None

    assert il.find_sid_hits(data)
    monkeypatch.setattr(il, "looks_utf16", utf16_only)
    assert not il.find_sid_hits(data), "the old detection already sees the SID: the toggle does not discriminate"
