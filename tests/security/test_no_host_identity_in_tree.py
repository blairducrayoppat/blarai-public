"""Gate lock: no tracked file carries this machine's host name in any reading of its bytes; no file in the containment
studies' and performance records' scope carries the operator's account name; no credential-store row keeps the name in its
path; no tracked file NAME carries either name; and outside the scope the account name's footprint never grows (the ratchet).

WHAT FAILURE THIS EXISTS FOR
----------------------------
The public mirror is a whole-tree snapshot of main. On 2026-10-14 (#1741 review, #1765, #1767) the Windows containment study
records carried the machine's computer name, the operator's account name and, in five effective-access records, rows naming the
operator's credential stores with their access lists; eleven gzip gate logs carried both names in pytest test IDs; the study's
report and its performance copy carried the credential table. ``scripts/scrub_public_identifiers.py`` rewrote them; this test
keeps them out so the scrub is a standing control and never a question put to the operator. The ratchet is the operator's
instruction the same day ("i don't want it to get worse"): what already carries the name is frozen per file, anything new fails.

Recognition lives in ``scripts/identity_lock.py`` and is shared with the scrub, the Hugging Face preflight and the community
scrub tools. The tree test, the scrub's ``check()`` and its ``ratchet_violations()`` are each driven here on scratch trees with
planted findings beside clean twins, so a control that stops seeing fails here before it fails in public. Names are never written
here; the digests and the live machine both must hold, and the test fails, never skips, when the machine's names cannot be read.
"""

from __future__ import annotations

import functools
import gzip
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import identity_lock as il  # noqa: E402
import scrub_public_identifiers as scrub  # noqa: E402

BS = chr(92)


# ---- the scan both the tree test and the toggles use ----------------------------------------------------------------------------

def scan(root: Path, files: list[Path], host_digests: frozenset[str], user_digests: frozenset[str], scope: tuple[str, ...]) -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {"host": [], "user": [], "credential": [], "name": []}
    for p in files:
        r = p.relative_to(root).as_posix()
        if il.name_in_path(r, host_digests, user_digests):
            hits["name"].append(r)
        data = p.read_bytes()
        hosts, users = il.find_hits(data, host_digests, user_digests)
        if hosts:
            hits["host"].append(r)
        if users and il.path_in_scope(r, scope):
            hits["user"].append(r)
        if p.suffix.lower() in (".json", ".gz") and scrub.secret_rows_carrying_the_name(data, user_digests):
            hits["credential"].append(r)
    return hits


def _live() -> tuple[str, str]:
    host, user = il.live_names()
    assert host, "the host name is not readable on this machine; the lock cannot see its subject"
    assert user, "the user name is not readable on this machine; the lock cannot see its subject"
    return host, user


def _tracked() -> list[Path]:
    files = [p for p in il.read_tracked(REPO_ROOT) if p.is_file()]
    assert files, "git ls-files returned nothing; the lock cannot see the tree"
    return files


@functools.lru_cache(maxsize=1)
def _tree_scan() -> dict[str, list[str]]:
    """One pass over the tree per test session; the tests below read their own key."""
    host, user = _live()
    hd, ud = il.digests_with_live(host, user)
    return scan(REPO_ROOT, _tracked(), hd, ud, scrub.USER_SCOPE)


# ---- the tree -------------------------------------------------------------------------------------------------------------------

def test_digest_sets_cover_this_machine() -> None:
    """A renamed host or account is appended to the digests, never silently unlocked."""
    host, user = _live()
    assert il.digest(host) in il.HOST_DIGESTS, "this machine's host name is not in identity_lock.HOST_DIGESTS: append its digest"
    assert il.digest(user) in il.USER_DIGESTS, "this machine's operator name is not in identity_lock.USER_DIGESTS: append its digest"
    assert len(host) in il.HOST_LENGTHS and len(user) in il.USER_LENGTHS, "append the name lengths beside the digests"
    assert il.live_names_are_pinned() == (True, True)


def test_scope_exists_and_is_scanned() -> None:
    """The account-name scope names real paths with files in them; a moved study is a lock that watches nothing."""
    files = _tracked()
    for entry in scrub.USER_SCOPE:
        inside = [p for p in files if il.path_in_scope(p.relative_to(REPO_ROOT).as_posix(), (entry,))]
        assert inside, f"USER_SCOPE entry {entry!r} matches no tracked file"


def test_tree_is_clean() -> None:
    hits = _tree_scan()
    msg = "run scripts/scrub_public_identifiers.py (a file NAME needs a rename by hand)"
    assert not hits["host"], f"tracked files name the host; {msg}:\n  " + "\n  ".join(hits["host"])
    assert not hits["user"], f"files in USER_SCOPE name the operator; {msg}:\n  " + "\n  ".join(hits["user"])
    assert not hits["credential"], f"records carry credential-store rows naming the operator; {msg}:\n  " + "\n  ".join(hits["credential"])
    assert not hits["name"], f"tracked file names carry an identifier; {msg}:\n  " + "\n  ".join(hits["name"])


def test_ratchet_holds_on_the_tree() -> None:
    """Outside USER_SCOPE the account name's footprint is what the baseline says, no more, and never grew on this branch."""
    host, user = _live()
    _, ud = il.digests_with_live(host, user)
    baseline = scrub.load_user_baseline(REPO_ROOT)
    assert baseline, f"{scrub.USER_BASELINE_PATH} is missing or empty"
    reference, reason = scrub.reference_baseline(REPO_ROOT)
    problems = scrub.ratchet_violations(REPO_ROOT, _tracked(), ud, baseline, reference, reason)
    assert not problems, "the operator name's footprint grew (new content uses %USERPROFILE% or __USER__; the baseline only shrinks):\n  " + "\n  ".join(problems)


def test_check_mode_is_clean_on_the_tree() -> None:
    """The scrub's --check is the gate form named by the doctrine rule; on a clean tree it finds nothing."""
    host, user = _live()
    assert scrub.check(REPO_ROOT, _tracked(), host, user) == []


# ---- toggles: each shape planted in a scratch tree; the same functions must see it; the clean twin must not --------------------------

SCOPE_DIR = scrub.USER_SCOPE[0]


def _plant(root: Path, rel: str, data: bytes) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def _scan_one(root: Path, p: Path, host: str, user: str) -> dict[str, list[str]]:
    hd, ud = il.digests_with_live(host, user)
    return scan(root, [p], hd, ud, scrub.USER_SCOPE)


HOST_SHAPES = {
    "prose-lower": lambda h: f"run on {h.lower()}.".encode(),
    "prose-upper-unc": lambda h: f"{BS}{BS}{h.upper()}{BS}share".encode(),
    "json-newline-escape": lambda h: json.dumps({"out": f"line1\n{h}{BS}x"}).encode(),
    "json-tab-escape": lambda h: json.dumps({"out": f"a\t{h}"}).encode(),
    "glue-letter": lambda h: f"{h}x_trace".encode(),
    "glue-digit": lambda h: f"{h}1".encode(),
    "percent-unc": lambda h: f"%5C%5C{h}%5Cshare".encode(),
    "x00-escape": lambda h: json.dumps({"out": f"\x00{h}"}).encode(),
    "utf16le": lambda h: f"host={h}".encode("utf-16"),
    "utf16-fragment-in-ascii": lambda h: b"ascii log line\n" + h.encode("utf-16-le") + b"\nmore ascii",
    "ansi-colour": lambda h: f"\x1b[32m{h}\x1b[0m".encode(),
}


@pytest.mark.parametrize("shape", sorted(HOST_SHAPES))
def test_toggle_host_shape_is_found_and_clean_twin_is_not(tmp_path: Path, shape: str) -> None:
    host, user = _live()
    planted = _plant(tmp_path, f"docs/x/{shape}.txt", HOST_SHAPES[shape](host))
    clean = _plant(tmp_path, f"docs/x/{shape}-clean.txt", HOST_SHAPES[shape]("somehostname"))
    assert _scan_one(tmp_path, planted, host, user)["host"] == [f"docs/x/{shape}.txt"]
    assert _scan_one(tmp_path, clean, host, user)["host"] == []


def test_toggle_host_inside_gzip_log(tmp_path: Path) -> None:
    host, user = _live()
    planted = _plant(tmp_path, "docs/performance/x/run.log.gz", gzip.compress(f"PASSED test[run on {host}]\n".encode()))
    clean = _plant(tmp_path, "docs/performance/x/clean.log.gz", gzip.compress(b"PASSED test[run on somehostname]\n"))
    assert _scan_one(tmp_path, planted, host, user)["host"] == ["docs/performance/x/run.log.gz"]
    assert _scan_one(tmp_path, clean, host, user)["host"] == []


def test_toggle_host_in_file_name(tmp_path: Path) -> None:
    host, user = _live()
    planted = _plant(tmp_path, f"docs/x/{host.lower()}-trace.log", b"nothing inside")
    assert _scan_one(tmp_path, planted, host, user)["name"] == [f"docs/x/{host.lower()}-trace.log"]


USER_SHAPES = {
    "windows-path": lambda u: f"C:{BS}Users{BS}{u}{BS}x".encode(),
    "json-escaped-path": lambda u: json.dumps({"path": f"C:{BS}Users{BS}{u}{BS}.ssh"}).encode(),
    "json-newline-escape": lambda u: json.dumps({"out": f"whoami\n{u}"}).encode(),
    "digit-glue-after": lambda u: f"{u}1".encode(),
    "digit-glue-before": lambda u: f"1{u}".encode(),
    "upper": lambda u: u.upper().encode(),
    "utf16le": lambda u: f"user {u}".encode("utf-16"),
    "gzip": lambda u: gzip.compress(f"by {u}".encode()),
    "ansi-prompt": lambda u: f"\x1b[32m{u}@box\x1b[0m $ ".encode(),
}


@pytest.mark.parametrize("shape", sorted(USER_SHAPES))
def test_toggle_user_shape_is_found_in_scope_and_not_outside(tmp_path: Path, shape: str) -> None:
    """The operator name counts inside USER_SCOPE; the same bytes outside the scope are the ratchet's business, not this scan's."""
    host, user = _live()
    inside = _plant(tmp_path, f"{SCOPE_DIR}/{shape}.json", USER_SHAPES[shape](user))
    outside = _plant(tmp_path, f"docs/elsewhere/{shape}.json", USER_SHAPES[shape](user))
    clean = _plant(tmp_path, f"{SCOPE_DIR}/{shape}-clean.json", USER_SHAPES[shape]("someone"))
    assert _scan_one(tmp_path, inside, host, user)["user"] == [f"{SCOPE_DIR}/{shape}.json"]
    assert _scan_one(tmp_path, outside, host, user)["user"] == []
    assert _scan_one(tmp_path, clean, host, user)["user"] == []


def test_toggle_credential_row_naming_the_operator_found_anywhere(tmp_path: Path) -> None:
    host, user = _live()
    real = _plant(tmp_path, "docs/anywhere/ea.json", json.dumps({"rows": [{"kind": "secret", "path": f"C:{BS}Users{BS}{user}{BS}.ssh"}]}).encode())
    nested_gz = _plant(tmp_path, "docs/anywhere/ea.json.gz", gzip.compress(json.dumps({"a": [{"inner": {"kind": "secret", "path": f"C:{BS}Users{BS}{user}{BS}.aws"}}]}).encode()))
    redacted = _plant(tmp_path, "docs/anywhere/ok.json", json.dumps({"rows": [{"kind": "secret", "path": f"C:{BS}Users{BS}__USER__{BS}.ssh"}, {"kind": "dir", "path": f"C:{BS}x"}]}).encode())
    assert _scan_one(tmp_path, real, host, user)["credential"] == ["docs/anywhere/ea.json"]
    assert _scan_one(tmp_path, nested_gz, host, user)["credential"] == ["docs/anywhere/ea.json.gz"]
    assert _scan_one(tmp_path, redacted, host, user)["credential"] == []


def test_pinned_digests_recognise_the_live_names_without_the_environment() -> None:
    """The pinned digests alone, with no live names passed, recognise this machine's names: a control run as another account
    still protects the operator. (Full account independence is shown by the preflight and community-pair tests.)"""
    host, user = _live()
    hosts, users = il.find_hits(f"by {user} on {host}".encode(), il.HOST_DIGESTS, il.USER_DIGESTS)
    assert hosts == {host.lower().encode()} and users == {user.lower().encode()}


# ---- the scrub's check() and ratchet, toggled on scratch git repositories ------------------------------------------------------------

def _scratch_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True)
    return tmp_path


def test_toggle_check_mode_reports_every_class(tmp_path: Path) -> None:
    """``check()`` is the gate form; planted findings of each class must come back, and a clean tree must come back empty."""
    host, user = _live()
    root = _scratch_repo(tmp_path)
    scrub.save_user_baseline(root, {})
    _commit(root, "baseline lands on main")  # an unborn HEAD is a ratchet finding (R4-2)
    files = [
        _plant(root, "docs/a/host.txt", f"on {host}".encode()),
        _plant(root, f"{SCOPE_DIR}/user.md", f"by {user}".encode()),
        _plant(root, "docs/a/ea.json", json.dumps({"rows": [{"kind": "secret", "path": f"C:{BS}Users{BS}{user}{BS}.ssh"}]}).encode()),
        _plant(root, "docs/a/new-outside.md", f"path C:{BS}Users{BS}{user}{BS}x".encode()),
        _plant(root, f"docs/a/{host.lower()}.log", b"x"),
        root / scrub.USER_BASELINE_PATH,
    ]
    problems = scrub.check(root, files, host, user)
    kinds = {"host name present", "operator user name present", "credential-store row", "outside the baseline", "file NAME"}
    assert all(any(k in p for p in problems) for k in kinds), problems
    clean = [_plant(root, "docs/b/clean.txt", b"nothing here"), root / scrub.USER_BASELINE_PATH]
    assert scrub.check(root, clean, host, user) == []


def test_toggle_ratchet_every_way_the_footprint_could_grow(tmp_path: Path) -> None:
    host, user = _live()
    _, ud = il.digests_with_live(host, user)
    root = _scratch_repo(tmp_path)
    listed = _plant(root, "docs/listed.md", f"a {user} b {user}".encode())
    baseline = {"docs/listed.md": 2}
    main_copy = {"docs/listed.md": 2}
    ok = scrub.ratchet_violations(root, [listed], ud, baseline, main_copy)
    assert ok == []
    # 1. a listed file gains an occurrence
    listed.write_bytes(f"a {user} b {user} c {user}".encode())
    assert any("baseline allows 2" in p for p in scrub.ratchet_violations(root, [listed], ud, baseline, main_copy))
    listed.write_bytes(f"a {user} b {user}".encode())
    # 2. a new file outside the scope carries the name
    new = _plant(root, "docs/new.md", f"{user}".encode())
    assert any("outside the baseline" in p for p in scrub.ratchet_violations(root, [listed, new], ud, baseline, main_copy))
    # 3. swap: list the new file and drop the cleaned one (count stays equal) -- refused against main's copy
    listed.write_bytes(b"clean now")
    swapped = {"docs/new.md": 1}
    out = scrub.ratchet_violations(root, [listed, new], ud, swapped, main_copy)
    assert any("added to the baseline on this branch" in p for p in out)
    # 4. a cleaned file left listed
    out = scrub.ratchet_violations(root, [listed], ud, baseline, main_copy)
    assert any("carries the name no more" in p for p in out)
    # 5. count raised in the list together with the content
    listed.write_bytes(f"a {user} b {user} c {user}".encode())
    out = scrub.ratchet_violations(root, [listed], ud, {"docs/listed.md": 3}, main_copy)
    assert any("baseline count raised on this branch" in p for p in out)
    # 6. a listed file that is no longer tracked
    out = scrub.ratchet_violations(root, [], ud, baseline, main_copy)
    assert any("not tracked" in p for p in out)
    # 7. the scope is exempt: the same bytes inside USER_SCOPE are the scrub's job, not the ratchet's
    inside = _plant(root, f"{SCOPE_DIR}/x.md", f"{user}".encode())
    assert scrub.ratchet_violations(root, [inside], ud, {}, {}) == []
    # 8. the name reaches a new file only in a shape the raw bytes do not show: the ratchet reads the views the lock reads
    hidden = [
        ("docs/pct.txt", f"C:%5CUsers%5C{user}%5C.ssh".encode()),
        ("docs/wide.txt", f"user={user}".encode("utf-16")),
        ("docs/log.gz", gzip.compress(f"by {user}".encode())),
        ("docs/ansi.txt", f"[32m{user}[0m".encode()),
    ]
    for name, data in hidden:
        f = _plant(root, name, data)
        assert any("outside the baseline" in p for p in scrub.ratchet_violations(root, [f], ud, {}, {})), name
    # 9. and a listed file that gains one of those shapes is over its count; the plain-text count itself is unchanged
    listed.write_bytes(f"a {user} b {user}".encode() + f" c %5C{user}%5C".encode())
    assert any("baseline allows 2" in p for p in scrub.ratchet_violations(root, [listed], ud, baseline, main_copy))
    assert il.count_user_hits(f"a {user} b {user}".encode(), ud) == 2


# ---- the scrub itself ------------------------------------------------------------------------------------------------------------

def test_scrub_rewrites_every_shape_and_is_idempotent() -> None:
    host, user = _live()
    samples = [
        (f"run on {host.upper()} and {host.lower()}x".encode(), False),
        (json.dumps({"out": f"whoami\n{user}", "path": f"C:{BS}Users{BS}{user}{BS}.ssh", "n": 3}).encode(), True),
        (f"%5C%5C{host}%5C{user}%5Cshare".encode(), True),
        (gzip.compress(f"PASSED t[run on {host}] by {user}".encode()), True),
        (f"host={host} user={user}".encode("utf-16"), True),
        (f"\x1b[32m{user}@{host}\x1b[0m $".encode(), True),
        (f"1{user} and {user}2".encode(), True),
    ]
    hd, ud = il.digests_with_live(host, user)
    for data, in_scope in samples:
        once, counts = scrub.scrub_bytes(data, host=host, user=user, in_scope=in_scope)
        assert sum(counts.values()) > 0, data
        hosts, users = il.find_hits(once, hd, ud)
        assert hosts == set(), data
        if in_scope:
            assert users == set(), data
        twice, counts2 = scrub.scrub_bytes(once, host=host, user=user, in_scope=in_scope)
        assert twice == once and sum(counts2.values()) == 0
    before = json.loads(samples[1][0])
    after = json.loads(scrub.scrub_bytes(samples[1][0], host=host, user=user, in_scope=True)[0])
    assert after["n"] == before["n"] and set(after) == set(before) and after["path"] == f"C:{BS}Users{BS}__USER__{BS}.ssh"


def test_gzip_bytes_have_a_fixed_header_and_round_trip() -> None:
    """The header is fixed; the deflate body is this zlib build's (the log records the build), so only the header and the
    round trip are asserted, never byte identity across interpreters."""
    out = scrub.gzip_bytes(b"hello " * 100)
    assert out[:10] == b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\xff"
    assert gzip.decompress(out) == b"hello " * 100
    assert scrub.gzip_bytes(b"hello " * 100) == out


def test_rewrite_refuses_when_the_live_names_are_not_pinned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run as another account the scrub must not rewrite that account's name into the operator's placeholder."""
    root = _scratch_repo(tmp_path)
    _plant(root, "docs/x.md", b"text")
    subprocess.run(["git", "-C", str(root), "add", "docs/x.md"], check=True)
    monkeypatch.setenv("USERNAME", "blarai-coder")
    monkeypatch.setenv("COMPUTERNAME", "SOMEOTHERBOX1")
    with pytest.raises(SystemExit) as e:
        scrub.main(["--repo", str(root), "--log", str(tmp_path / "log.md")])
    assert e.value.code == 2
    assert not (tmp_path / "log.md").exists()


def test_short_or_missing_names_are_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _scratch_repo(tmp_path)
    monkeypatch.setenv("USERNAME", "ab")
    monkeypatch.setenv("COMPUTERNAME", "PC")
    with pytest.raises(SystemExit) as e:
        scrub.main(["--check", "--repo", str(root)])
    assert e.value.code == 2


# ---- round 3 ---------------------------------------------------------------------------------------------------------------------

def _commit(root: Path, msg: str) -> None:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True, env=env)  # a scratch repository of this test's own files
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", msg], check=True, env=env)


def test_toggle_escaped_and_encoded_shapes_are_seen_and_reported(tmp_path: Path) -> None:
    """Round 3 R3-2: a name after a JSON-escaped or percent-encoded colour code, with a JSON-escaped letter, or as HTML entities is
    seen by the lock and counted by the ratchet; the rewrite does not clear those shapes and the scrub run says so (exit 1)."""
    host, user = _live()
    hd, ud = il.digests_with_live(host, user)
    u1, urest = user[0], user[1:]
    h1, hrest = host[0], host[1:]
    shapes = {
        "json-escaped ansi": json.dumps({"out": f"\x1b[32m{user}\x1b[0m"}).encode(),
        "json-escaped letter (user)": ('{"u": "\\u%04x%s"}' % (ord(u1), urest)).encode(),
        "json-escaped letter (host)": ('{"h": "\\u%04x%s"}' % (ord(h1), hrest)).encode(),
        "percent-encoded ansi": f"%1B%5B32m{user}%1B%5B0m".encode(),
        "html entities": "".join(f"&#{ord(c)};" for c in user).encode(),
        "html hex entity first letter": f"&#x{ord(u1):x};{urest}".encode(),
    }
    for name, data in shapes.items():
        hosts, users = il.find_hits(data, hd, ud)
        assert hosts or users, name
        if "host" not in name:
            assert il.count_user_hits(data, ud) >= 1, name
    # the gate form flags them in scope and the ratchet flags them outside; the rewrite reports what it cannot clear
    root = _scratch_repo(tmp_path)
    scrub.save_user_baseline(root, {})
    inside = _plant(root, f"{SCOPE_DIR}/a.json", shapes["json-escaped ansi"])
    outside = _plant(root, "docs/b.txt", shapes["percent-encoded ansi"])
    problems = scrub.check(root, [inside, outside, root / scrub.USER_BASELINE_PATH], host, user)
    assert any("operator user name present" in p for p in problems) and any("outside the baseline" in p for p in problems), problems
    _commit(root, "plant")
    log = tmp_path / "run.md"
    code = scrub.main(["--repo", str(root), "--log", str(log)])
    assert code == 1
    text = log.read_text(encoding="utf-8")
    assert "shape the rewrite does not clear" in text and f"{SCOPE_DIR}/a.json" in text, text


def test_toggle_branch_comparison_reads_the_reference_and_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Round 3 R3-3: ``check()`` reads main's baseline through git on a branch and the previous commit's on main; a reference
    that does not resolve is a finding, not a silent skip; only the baseline's first landing is exempt (and says so)."""
    host, user = _live()
    root = _scratch_repo(tmp_path / "repo")
    listed = _plant(root, "docs/l.md", f"a {user} b {user}".encode())
    scrub.save_user_baseline(root, {"docs/l.md": 2})
    files = lambda: [p for p in il.read_tracked(root) if p.is_file()]  # noqa: E731
    _commit(root, "baseline lands on main")
    # first landing on main: the reference is the landing itself, so nothing is skipped and nothing else fails
    assert scrub.reference_baseline(root) == ({"docs/l.md": 2}, "")
    assert scrub.check(root, files(), host, user) == []
    # a branch that raises the count together with the content: caught through main's copy, read by git
    subprocess.run(["git", "-C", str(root), "checkout", "-q", "-b", "feat"], check=True)
    listed.write_bytes(f"a {user} b {user} c {user}".encode())
    scrub.save_user_baseline(root, {"docs/l.md": 3})
    _commit(root, "raise")
    assert scrub.reference_baseline(root)[0] == {"docs/l.md": 2}
    assert any("baseline count raised on this branch" in p for p in scrub.check(root, files(), host, user))
    # toggle: pretend the reference is a first landing, and the same tree passes; the git read is on the path
    monkeypatch.setattr(scrub, "reference_baseline", lambda r: (None, scrub.FIRST_LANDING))
    assert not any("raised on this branch" in p for p in scrub.check(root, files(), host, user))
    monkeypatch.undo()
    # a clone that has no main at all: the comparison cannot run and says so
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", "--single-branch", "-b", "feat", str(root), str(clone)], check=True)
    ref, reason = scrub.reference_baseline(clone)
    assert ref is None and "does not resolve" in reason
    cfiles = [p for p in il.read_tracked(clone) if p.is_file()]
    assert any("branch comparison did not run" in p for p in scrub.check(clone, cfiles, host, user))
    # on main the reference is the window of main's own baseline versions: a raise committed straight to main is caught by the gate on main
    subprocess.run(["git", "-C", str(root), "checkout", "-q", "main"], check=True)
    listed.write_bytes(f"a {user} b {user} c {user}".encode())
    scrub.save_user_baseline(root, {"docs/l.md": 3})
    _commit(root, "raise on main")
    assert scrub.reference_baseline(root)[0] == {"docs/l.md": 2}
    assert any("baseline count raised on this branch" in p for p in scrub.check(root, files(), host, user))


def test_scrub_reports_a_gzip_member_it_cannot_rewrite(tmp_path: Path) -> None:
    """Round 3 R3-8: a gzip member with trailing bytes carrying an identifier is logged and fails the run, never kept silently."""
    host, user = _live()
    root = _scratch_repo(tmp_path)
    scrub.save_user_baseline(root, {})
    _plant(root, f"{SCOPE_DIR}/log.gz", gzip.compress(b"clean") + f"trailing {user}".encode())
    _commit(root, "plant")
    log = tmp_path / "run.md"
    assert scrub.main(["--repo", str(root), "--log", str(log)]) == 1
    assert "gzip member with trailing bytes" in log.read_text(encoding="utf-8")


def test_publisher_refuses_a_file_name_carrying_the_identity_under_any_account(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Round 3 R3-4: the Hugging Face preflight checks file names by digest, so another account cannot upload a file named after
    the operator or the host."""
    import hf_publish

    host, user = _live()
    d = tmp_path / "ds"
    d.mkdir()
    (d / f"run-{user}.csv").write_text("n\n1\n", encoding="utf-8")
    (d / f"{host}-notes.csv").write_text("n\n1\n", encoding="utf-8")
    monkeypatch.setenv("USERNAME", "blarai-coder")
    monkeypatch.setenv("COMPUTERNAME", "SOMEOTHERBOX1")
    hits = hf_publish.preflight(d)
    assert sum("digest match" in h for h in hits) == 2, hits


def test_rotation_refuses_to_move_an_entry_carrying_the_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Round 3 R3-6: the journal rotation would write a new archive volume outside the baseline; it refuses before writing."""
    import importlib.util

    host, user = _live()
    spec = importlib.util.spec_from_file_location("rotate_log", REPO_ROOT / "tools" / "doc_hygiene" / "rotate_log.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    src = tmp_path / "J.md"
    src.write_text(f"# J\n\n### 2026-08-02 — old\n*Plain summary: x*\n\nby {user}\n\n### 2026-10-02 — new\n*Plain summary: y*\n\nclean\n", encoding="utf-8")
    idx = tmp_path / "INDEX.md"
    idx.write_text("# idx\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["rotate_log", "--source", str(src), "--archive-dir", str(tmp_path / "arch"), "--index", str(idx), "--keep-month", "2026-10"])
    assert mod.main() == 2
    assert "REFUSED" in capsys.readouterr().out
    assert not (tmp_path / "arch").exists()
    assert f"by {user}" in src.read_text(encoding="utf-8")


# ---- round 4 ---------------------------------------------------------------------------------------------------------------------

_GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def _g(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, env={**os.environ, **_GIT_ENV})


def _tracked_in(root: Path) -> list[Path]:
    return [p for p in il.read_tracked(root) if p.is_file()]


def _listed_repo(tmp: Path, user: str, count: int = 2) -> tuple[Path, Path]:
    """main with one listed file carrying ``count`` occurrences and the baseline that says so."""
    root = _scratch_repo(tmp)
    listed = _plant(root, "docs/l.md", " ".join(f"a {user}" for _ in range(count)).encode())
    scrub.save_user_baseline(root, {"docs/l.md": count})
    _commit(root, "baseline lands on main")
    return root, listed


def _raise_to(root: Path, listed: Path, user: str, n: int, msg: str) -> None:
    listed.write_bytes(" ".join(f"a {user}" for _ in range(n)).encode())
    scrub.save_user_baseline(root, {"docs/l.md": n})
    _commit(root, msg)


def _raised(problems: list[str]) -> bool:
    return any("baseline count raised on this branch" in p for p in problems)


def test_toggle_main_reference_catches_growth_that_merged_without_a_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R4-1: the reference on main is a window of baseline versions, not the previous commit: a raise that merged with no gate
    run at its merge commit is still a finding after later commits, and a delete-then-re-add does not read as a first landing."""
    host, user = _live()
    root, listed = _listed_repo(tmp_path / "repo", user)
    _g(root, "checkout", "-q", "-b", "feat")
    _raise_to(root, listed, user, 3, "raise on a branch")
    _g(root, "checkout", "-q", "main")
    _g(root, "merge", "--no-ff", "-q", "feat", "-m", "merge the raise, no gate run here")
    assert _raised(scrub.check(root, _tracked_in(root), host, user)), "at the merge commit"
    _plant(root, "docs/unrelated.md", b"nothing")
    _commit(root, "an unrelated docs commit, gate skipped again")
    _plant(root, "docs/unrelated2.md", b"nothing")
    _commit(root, "and another")
    assert _raised(scrub.check(root, _tracked_in(root), host, user)), "growth must not become the reference one commit later"
    # toggle: a one-version window is the old previous-commit reference, and the same tree reads clean
    monkeypatch.setattr(scrub, "WINDOW", 1)
    assert not _raised(scrub.check(root, _tracked_in(root), host, user))
    monkeypatch.undo()
    # the reviewer's last row: delete the baseline, re-add it raised; the reference is not a first landing
    root2, listed2 = _listed_repo(tmp_path / "repo2", user)
    _g(root2, "rm", "-q", scrub.USER_BASELINE_PATH)
    _g(root2, "commit", "-q", "-m", "delete the baseline")
    _raise_to(root2, listed2, user, 3, "re-add it raised")
    assert scrub.reference_baseline(root2)[0] == {"docs/l.md": 2}
    assert _raised(scrub.check(root2, _tracked_in(root2), host, user))


def test_branch_cut_before_the_baseline_reached_main_is_still_a_first_landing(tmp_path: Path) -> None:
    host, user = _live()
    root = _scratch_repo(tmp_path / "repo")
    _plant(root, "docs/x.md", b"x")
    _commit(root, "main without a baseline")
    _g(root, "checkout", "-q", "-b", "feat")
    _plant(root, "docs/l.md", f"a {user}".encode())
    scrub.save_user_baseline(root, {"docs/l.md": 1})
    _commit(root, "baseline lands on a branch")
    assert scrub.reference_baseline(root) == (None, scrub.FIRST_LANDING)
    assert scrub.check(root, _tracked_in(root), host, user) == []


def test_toggle_unreadable_histories_fail_closed_with_a_named_message(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R4-2: a detached HEAD at main's tip is read as main (a raise is found), a shallow clone and an unborn HEAD are findings
    that name themselves; none of the three passes silently."""
    host, user = _live()
    root, listed = _listed_repo(tmp_path / "repo", user)
    _raise_to(root, listed, user, 3, "raise committed straight to main")
    assert _raised(scrub.check(root, _tracked_in(root), host, user)), "on the branch main"
    _g(root, "checkout", "-q", "--detach")
    assert _raised(scrub.check(root, _tracked_in(root), host, user)), "detached at main's tip"
    # shallow: the history the comparison reads is missing
    shallow = tmp_path / "shallow"
    subprocess.run(["git", "clone", "-q", "--depth", "1", "-b", "main", root.as_uri(), str(shallow)], check=True, capture_output=True)
    ref, reason = scrub.reference_baseline(shallow)
    assert ref is None and "shallow clone" in reason, (ref, reason)
    assert any("shallow clone" in p for p in scrub.check(shallow, _tracked_in(shallow), host, user))
    # unborn HEAD
    fresh = _scratch_repo(tmp_path / "fresh")
    _plant(fresh, "docs/a.md", b"x")
    scrub.save_user_baseline(fresh, {})
    ref, reason = scrub.reference_baseline(fresh)
    assert ref is None and "no commit yet" in reason, (ref, reason)
    assert any("no commit yet" in p for p in scrub.check(fresh, _tracked_in(fresh), host, user))
    # toggle: the old behaviour (an unresolvable state read as a first landing) would make all three pass
    monkeypatch.setattr(scrub, "reference_baseline", lambda r: (None, scrub.FIRST_LANDING))
    assert scrub.check(fresh, _tracked_in(fresh), host, user) == []
    assert not any("shallow clone" in p for p in scrub.check(shallow, _tracked_in(shallow), host, user))


def test_toggle_a_listed_count_follows_the_file_down(tmp_path: Path) -> None:
    """R4-3: a listed count above the file's is a finding, so headroom cannot be refilled by a later branch."""
    host, user = _live()
    _, ud = il.digests_with_live(host, user)
    root, listed = _listed_repo(tmp_path / "repo", user, count=3)
    ok = scrub.ratchet_violations(root, [listed], ud, {"docs/l.md": 3}, {"docs/l.md": 3})
    assert ok == []
    listed.write_bytes(f"a {user} b %USERPROFILE% c %USERPROFILE%".encode())  # one of three left
    out = scrub.ratchet_violations(root, [listed], ud, {"docs/l.md": 3}, {"docs/l.md": 3})
    assert any("lower the listed count to 1" in p for p in out), out
    assert scrub.ratchet_violations(root, [listed], ud, {"docs/l.md": 1}, {"docs/l.md": 3}) == []
    assert any("lower the listed count to 1" in p for p in scrub.check(root, [listed, root / scrub.USER_BASELINE_PATH], host, user))


def test_toggle_main_shrinking_behind_a_branch_is_named_as_mains_change(tmp_path: Path) -> None:
    """R4-5: a branch that changed nothing related is told to merge main, not blamed for growth."""
    host, user = _live()
    root = _scratch_repo(tmp_path / "repo")
    l = _plant(root, "docs/l.md", f"a {user} b {user}".encode())
    m = _plant(root, "docs/m.md", f"a {user}".encode())
    scrub.save_user_baseline(root, {"docs/l.md": 2, "docs/m.md": 1})
    _commit(root, "baseline lands on main")
    _g(root, "checkout", "-q", "-b", "feat")
    _plant(root, "docs/unrelated.md", b"nothing")
    _commit(root, "the branch changes nothing related")
    _g(root, "checkout", "-q", "main")
    m.write_bytes(b"cleaned")
    l.write_bytes(f"a {user} b %USERPROFILE%".encode())
    scrub.save_user_baseline(root, {"docs/l.md": 1})
    _commit(root, "main cleans m and lowers l")
    _g(root, "checkout", "-q", "feat")
    problems = scrub.check(root, _tracked_in(root), host, user)
    assert any("main dropped this file from the baseline" in p for p in problems), problems
    assert any("main lowered this count to 1" in p for p in problems), problems
    assert not any("added to the baseline on this branch" in p or "raised on this branch" in p for p in problems), problems
    # a real growth on the same branch is still named as the branch's
    l.write_bytes(f"a {user} b {user} c {user}".encode())
    scrub.save_user_baseline(root, {"docs/l.md": 3, "docs/m.md": 1})
    _commit(root, "a real raise")
    assert _raised(scrub.check(root, _tracked_in(root), host, user))


def test_toggle_main_dropped_message_does_not_absolve_a_raise(tmp_path: Path) -> None:
    """R5-3: an entry main dropped, which the branch also raised (3 -> 5), is the branch's raise, not main's change."""
    host, user = _live()
    _, ud = il.digests_with_live(host, user)
    root, listed = _listed_repo(tmp_path / "repo", user, count=5)
    problems = scrub.ratchet_violations(root, [listed], ud, {"docs/l.md": 5}, {}, "", {"docs/l.md": 3})
    assert not any("main dropped this file" in p for p in problems), problems
    assert any("added to the baseline on this branch" in p for p in problems), problems
    # the reviewer's twin: the branch did not raise (fork 5, now 5), so main's drop is named as main's
    problems = scrub.ratchet_violations(root, [listed], ud, {"docs/l.md": 5}, {}, "", {"docs/l.md": 5})
    assert any("main dropped this file" in p for p in problems), problems


def test_toggle_legacy_list_baseline_in_history_is_no_version_not_unreadable(tmp_path: Path) -> None:
    """R5-1: a history fast-forwarded through a list-shape baseline reads its dict versions; an unreadable version stays a finding."""
    host, user = _live()
    root = _scratch_repo(tmp_path / "repo")
    listed = _plant(root, "docs/l.md", f"a {user} b {user}".encode())
    (root / scrub.USER_BASELINE_PATH).parent.mkdir(parents=True, exist_ok=True)
    (root / scrub.USER_BASELINE_PATH).write_text(json.dumps({"files": ["docs/l.md"]}), encoding="utf-8")
    _commit(root, "legacy list-shape baseline")
    scrub.save_user_baseline(root, {"docs/l.md": 2})
    _commit(root, "dict-shape baseline")
    ref, reason = scrub.reference_baseline(root)
    assert ref == {"docs/l.md": 2} and reason == "", (ref, reason)
    assert scrub.check(root, _tracked_in(root), host, user) == []
    # any other unreadable version still fails closed
    (root / scrub.USER_BASELINE_PATH).write_text("not json", encoding="utf-8")
    _commit(root, "garbage baseline")
    scrub.save_user_baseline(root, {"docs/l.md": 2})
    _commit(root, "dict again")
    ref, reason = scrub.reference_baseline(root)
    assert ref is None and "not a readable baseline" in reason, (ref, reason)


def test_toggle_list_shape_never_reaches_first_landing_and_odd_shapes_are_unreadable(tmp_path: Path) -> None:
    """R1-1: main holding only a list-shape baseline, then a branch that deletes and re-adds a grown one, is a finding, not
    FIRST_LANDING; a list that is not all strings is unreadable, not legacy. R1-4: a top-level list or null is unreadable."""
    host, user = _live()
    root = _scratch_repo(tmp_path / "repo")
    base = root / scrub.USER_BASELINE_PATH
    base.parent.mkdir(parents=True, exist_ok=True)
    base.write_text(json.dumps({"files": []}), encoding="utf-8")
    _commit(root, "main carries a list-shape baseline only")
    _g(root, "checkout", "-q", "-b", "feat")
    _g(root, "rm", "-q", scrub.USER_BASELINE_PATH)
    _g(root, "commit", "-q", "-m", "delete the baseline")
    _plant(root, "docs/new.md", f"a {user}".encode())
    scrub.save_user_baseline(root, {"docs/new.md": 9})
    _commit(root, "re-add it grown")
    ref, reason = scrub.reference_baseline(root)
    assert ref is None and reason != scrub.FIRST_LANDING and "legacy list-shape" in reason, (ref, reason)
    assert any("comparison did not run" in p for p in scrub.check(root, _tracked_in(root), host, user))
    for shape in ('{"files": [{"a": 1}]}', '["a"]', "null"):
        r2 = _scratch_repo(tmp_path / f"odd{abs(hash(shape))}")
        (r2 / scrub.USER_BASELINE_PATH).parent.mkdir(parents=True, exist_ok=True)
        (r2 / scrub.USER_BASELINE_PATH).write_text(shape, encoding="utf-8")
        _commit(r2, "odd baseline")
        ref, reason = scrub.reference_baseline(r2)
        assert ref is None and "not a readable baseline" in reason, (shape, ref, reason)
