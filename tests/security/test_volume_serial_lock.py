"""Gate lock for volume serial numbers (#1786): the live fixed volumes' serials, read at run time, and the ``Volume Serial Number``
header from any machine, in tracked file content and file NAMES, in the rewrite, in ``scrub --check`` and ``scrub.main``, and in
the journal rotation's refusal.

PYTEST_DONT_REWRITE

Assertion rewriting is off for this module on purpose: with it on, a failing assertion prints the values it compared, and here
those values are the planted text, which carries this machine's serial. Every assertion below is a plain condition with a fixed
message. Planted files live under pytest's temp directory. The serial is read at run time and never written in this file; the
foreign serial is made up and asserted not to be a live one.
"""

from __future__ import annotations

import gzip
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import identity_lock as il  # noqa: E402
import scrub_public_identifiers as scrub  # noqa: E402

FOREIGN_SERIAL = "1A2B-3C4D"  # made up; never this machine's (asserted in _first_serial)
FOREIGN_HEX = FOREIGN_SERIAL.replace("-", "")
FOREIGN_INT = int(FOREIGN_HEX, 16)
LF = chr(10)


def _serials() -> frozenset[int]:
    serials = il.live_volume_serials()
    assert serials, "no local fixed volume serial is readable on this machine; the lock cannot see its subject"
    return serials


def _digests() -> frozenset[str]:
    return il.serial_digests(_serials())


def _first_serial() -> int:
    serial = sorted(_serials())[0]
    assert serial != FOREIGN_INT, "the made-up foreign serial collides with a live one: pick another"
    return serial


def _dashed(n: int, lower: bool = False) -> str:
    h = f"{n:08x}" if lower else f"{n:08X}"
    return h[:4] + "-" + h[4:]


def _live() -> tuple[str, str]:
    host, user = il.live_names()
    assert host and user, "the host or user name is not readable on this machine"
    return host, user


def _kinds(data: bytes) -> set[str]:
    return il.find_serial_hits(data, _digests())


def _plant(root: Path, rel: str, data: bytes) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def _scratch_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True, capture_output=True)
    return tmp_path


def _commit(root: Path, msg: str) -> None:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True, env=env, capture_output=True)  # a scratch repository of this test's own files
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", msg], check=True, env=env, capture_output=True)


def _check(root: Path, files: list[Path]) -> list[str]:
    host, user = _live()
    return scrub.check(root, files, host, user, _digests())


def _repo_with_baseline(tmp_path: Path) -> Path:
    root = _scratch_repo(tmp_path)
    scrub.save_user_baseline(root, {})
    _commit(root, "baseline lands on main")
    return root


# ---- the live serial, every form --------------------------------------------------------------------------------------------------

SERIAL_LIVE_SHAPES = {
    "dashed-upper": lambda n: "id " + _dashed(n),
    "dashed-lower": lambda n: "vol " + _dashed(n, lower=True),
    "bare-hex-upper": lambda n: f"serial={n:08X}",
    "bare-hex-lower": lambda n: f"serial {n:08x}.",
    "decimal": lambda n: f"serial {n}",
    "decimal-zero-padded": lambda n: f"serial 0{n}",
    "hex-0x-lower": lambda n: f"serial {n:#010x}",
    "hex-0X-upper": lambda n: f"serial 0X{n:08X}",
    "fsutil-colon": lambda n: f"Volume Serial Number : 0x{n:08x}",
    "json-newline": lambda n: json.dumps({"out": "x\n" + _dashed(n) + "\n"}),
}


@pytest.mark.parametrize("shape", sorted(SERIAL_LIVE_SHAPES))
def test_toggle_live_serial_shape_is_found_and_foreign_twin_is_not(shape: str) -> None:
    n = _first_serial()
    found = _kinds(SERIAL_LIVE_SHAPES[shape](n).encode())
    twin = _kinds(SERIAL_LIVE_SHAPES[shape](FOREIGN_INT).replace("Volume Serial Number", "Volume label").encode())
    assert found, f"the live serial was not seen in the {shape} shape"
    assert not twin, f"a foreign serial in the {shape} shape was reported"


def test_toggle_live_serial_in_utf16_and_gzip_views() -> None:
    text = "vol " + _dashed(_first_serial())
    assert _kinds(text.encode("utf-16")), "the live serial was not seen as UTF-16"
    assert _kinds(gzip.compress(text.encode())), "the live serial was not seen inside gzip"


@pytest.mark.parametrize("header", [
    f" Volume Serial Number is {FOREIGN_SERIAL}",
    f"volume  serial number IS {FOREIGN_SERIAL.lower()}",
    f"Volume Serial Number is {FOREIGN_HEX}",
    f"Volume Serial Number is 0x{FOREIGN_HEX.lower()}",
    f"Volume Serial Number : 0x{FOREIGN_HEX.lower()}",
    f"Volume Serial Number: {FOREIGN_SERIAL}",
    f"Volume Serial Number is\n {FOREIGN_SERIAL}",
    f"Volume Serial Number is {FOREIGN_SERIAL}",
    json.dumps({"stdout": f" Volume in drive C has no label.\r\n Volume Serial Number is {FOREIGN_SERIAL}\r\n"}),
])
def test_toggle_header_with_a_foreign_serial_is_found(header: str) -> None:
    kinds = _kinds(header.encode("utf-8"))
    assert "header" in kinds, "a serial header from another machine was not seen"


def test_header_with_the_placeholder_and_prose_about_it_are_clean() -> None:
    kinds = _kinds(b" Volume Serial Number is XXXX-XXXX\nthe Volume Serial Number is printed by dir\nVolume Serial Number : XXXX-XXXX\n")
    assert not kinds, "the placeholder or prose about the header was reported"


def test_removing_the_live_rule_blinds_the_live_probe() -> None:
    data = f"serial {_first_serial():08X}".encode()
    seen = il.find_serial_hits(data, _digests())
    blind = il.find_serial_hits(data, frozenset())
    assert seen == {"live"}, "the live rule did not fire on a planted live serial"
    assert blind == set(), "the live probe saw a serial with the rule's digests removed"


def test_removing_the_header_rule_blinds_the_header_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    data = f"Volume Serial Number is {FOREIGN_SERIAL}".encode()
    seen = il.find_serial_hits(data, _digests())
    monkeypatch.setattr(il, "SERIAL_HEADER_RE", re.compile(rb"(?!)"))
    blind = il.find_serial_hits(data, _digests())
    assert seen == {"header"}, "the header rule did not fire on a planted header"
    assert blind == set(), "the header probe saw a header with the rule removed"


def test_no_live_serial_is_written_in_the_lock_files() -> None:
    n = _first_serial()
    forms = {f"{n:08X}", f"{n:08x}", _dashed(n), _dashed(n, lower=True), str(n)}
    for path in (REPO_ROOT / "scripts/identity_lock.py", REPO_ROOT / "scripts/scrub_public_identifiers.py", Path(__file__)):
        text = path.read_text(encoding="utf-8")
        assert not [f for f in forms if len(f) >= 8 and f in text], f"{path.name} carries a live serial"


# ---- scrub --check and the rewrite ------------------------------------------------------------------------------------------------

def test_check_mode_reports_both_serial_rules_and_fails_when_unreadable(tmp_path: Path) -> None:
    host, user = _live()
    root = _repo_with_baseline(tmp_path)
    live = _plant(root, "docs/s/live.txt", f"serial {_first_serial():08X}".encode())
    header = _plant(root, "docs/s/header.txt", f"Volume Serial Number is {FOREIGN_SERIAL}".encode())
    baseline = root / scrub.USER_BASELINE_PATH
    problems = _check(root, [live, header, baseline])
    assert any("live.txt" in p and "a live fixed volume's" in p for p in problems), "check() missed the live serial"
    assert any("header.txt" in p and "Volume Serial Number is" in p for p in problems), "check() missed the header"
    clean = _plant(root, "docs/s/clean.txt", b"nothing here")
    assert _check(root, [clean, baseline]) == [], "check() reported a clean tree"
    unread = scrub.check(root, [clean, baseline], host, user, frozenset())
    assert any("no local fixed volume serial is readable" in p for p in unread), "check() passed with no serial readable"


def test_rewrite_replaces_every_serial_form_with_the_placeholder_and_is_idempotent() -> None:
    host, user = _live()
    n = _first_serial()
    serials = frozenset({n})
    body = (f" Volume Serial Number is {FOREIGN_SERIAL}\nlive {_dashed(n)}\nbare {n:08x} dec {n}\nhex {n:#010x} pad 0{n}\n"
            f"fsutil Volume Serial Number : 0x{FOREIGN_HEX.lower()}\nkeep 12345 and abcd-efgh\n").encode()
    for data in (body, body.decode().encode("utf-16"), gzip.compress(body)):
        once, counts = scrub.scrub_bytes(data, host=host, user=user, in_scope=False, serials=serials)
        assert counts["serial"] == 7, "the rewrite counted a different number of serials"
        assert not il.find_serial_hits(once, il.serial_digests(serials)), "the rewrite left a serial the lock still sees"
        twice, counts2 = scrub.scrub_bytes(once, host=host, user=user, in_scope=False, serials=serials)
        assert twice == once and counts2["serial"] == 0, "the rewrite is not idempotent"
    text = scrub.scrub_bytes(body, host=host, user=user, in_scope=False, serials=serials)[0].decode()
    placeholders = text.count(scrub.SERIAL_PLACEHOLDER.decode())
    assert placeholders == 7 and "12345" in text and "abcd-efgh" in text, "the rewrite changed text it should keep or missed a form"


def test_scrub_main_rewrites_a_planted_serial_and_header_and_logs_counts_only(tmp_path: Path) -> None:
    n = _first_serial()
    root = _repo_with_baseline(tmp_path / "repo")
    f1 = _plant(root, "docs/s/a.txt", f"dir: Volume Serial Number is {FOREIGN_SERIAL}\nlive {_dashed(n)} and {n:08x} and {n}\n".encode())
    f2 = _plant(root, "docs/s/b.txt", b"nothing to scrub\n")
    _commit(root, "plant")
    log = tmp_path / "run.md"
    code = scrub.main(["--repo", str(root), "--log", str(log)])
    after = f1.read_bytes()
    log_text = log.read_text(encoding="utf-8")
    assert code == 0, "scrub.main exited non-zero on a rewritable serial and header"
    assert not _kinds(after), "scrub.main left a serial or header in the file"
    assert after.count(b"XXXX-XXXX") == 4, "scrub.main wrote a different number of placeholders"
    assert f2.read_bytes() == b"nothing to scrub\n", "scrub.main changed a clean file"
    assert "docs/s/a.txt" in log_text and "| serial |" in log_text, "the log does not name the file and the serial column"
    assert not _kinds(log_text.encode("utf-8")), "the log carries a serial"
    assert scrub.main(["--check", "--repo", str(root)]) == 0, "--check failed after the rewrite"


def test_scrub_main_reports_a_serial_it_cannot_rewrite_and_a_serial_in_a_file_name(tmp_path: Path) -> None:
    n = _first_serial()
    root = _repo_with_baseline(tmp_path / "repo")
    encoded = "".join(f"%{ord(c):02X}" for c in f"{n:08X}")  # percent-encoded byte by byte: the lock reads it, the rewrite does not
    _plant(root, "docs/s/enc.txt", f"id {encoded}\n".encode())
    _plant(root, f"docs/s/run-{_dashed(n)}.txt", b"x\n")
    _commit(root, "plant")
    log = tmp_path / "run.md"
    code = scrub.main(["--repo", str(root), "--log", str(log)])
    log_text = log.read_text(encoding="utf-8")
    assert code == 1, "scrub.main exited 0 with a serial it cannot clear"
    assert "docs/s/enc.txt" in log_text and "shape the rewrite does not clear" in log_text, "the log does not list the unrewritable serial"
    assert "NOT renamed" in log_text, "the log does not list the file name carrying a serial"
    assert not _kinds(log_text.encode("utf-8")), "the log printed a serial carried by a file name"


def test_toggle_serial_in_a_tracked_file_name(tmp_path: Path) -> None:
    n = _first_serial()
    root = _repo_with_baseline(tmp_path / "repo")
    baseline = root / scrub.USER_BASELINE_PATH
    live_name = _plant(root, f"docs/s/run-{_dashed(n)}.txt", b"x")
    header_name = _plant(root, f"docs/s/Volume Serial Number is {FOREIGN_SERIAL}.txt", b"x")
    clean_name = _plant(root, f"docs/s/run-{FOREIGN_SERIAL}.txt", b"x")
    for planted in (live_name, header_name):
        assert any("file NAME carries a volume serial number" in p for p in _check(root, [planted, baseline])), "check() missed a serial in a file name"
    assert _check(root, [clean_name, baseline]) == [], "check() reported a clean file name"


def test_removing_the_name_rule_blinds_the_name_probe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _repo_with_baseline(tmp_path / "repo")
    planted = _plant(root, f"docs/s/run-{_dashed(_first_serial())}.txt", b"x")
    files = [planted, root / scrub.USER_BASELINE_PATH]
    seen = any("file NAME" in p for p in _check(root, files))
    monkeypatch.setattr(il, "find_serial_hits", lambda data, digests: set())
    blind = any("file NAME" in p for p in _check(root, files))
    assert seen and not blind, "the file-name probe does not depend on the serial rule"


# ---- the journal rotation ----------------------------------------------------------------------------------------------------------

def _rotation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str) -> tuple[int, Path, Path]:
    import importlib.util

    spec = importlib.util.spec_from_file_location("rotate_log", REPO_ROOT / "tools" / "doc_hygiene" / "rotate_log.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    src = tmp_path / "J.md"
    src.write_text(f"# J\n\n### 2026-08-02 — old\n*Plain summary: x*\n\n{body}\n\n### 2026-10-02 — new\n*Plain summary: y*\n\nclean\n", encoding="utf-8")
    idx = tmp_path / "INDEX.md"
    idx.write_text("# idx\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["rotate_log", "--source", str(src), "--archive-dir", str(tmp_path / "arch"), "--index", str(idx), "--keep-month", "2026-10"])
    return mod.main(), src, tmp_path / "arch"


@pytest.mark.parametrize("kind", ["live", "header"])
def test_rotation_refuses_to_move_an_entry_carrying_a_volume_serial(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], kind: str) -> None:
    body = f"dir said {_dashed(_first_serial())}" if kind == "live" else f"Volume Serial Number is {FOREIGN_SERIAL}"
    code, src, arch = _rotation(tmp_path, monkeypatch, body)
    refused = "REFUSED" in capsys.readouterr().out
    kept = bool(_kinds(src.read_bytes()))
    assert code == 2 and refused and not arch.exists(), "the rotation did not refuse an entry carrying a serial"
    assert kept, "the refused entry was removed from the hot file"


def test_rotation_toggle_removing_the_serial_rule_lets_the_entry_move(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(il, "find_serial_hits", lambda data, digests: set())
    code, _, arch = _rotation(tmp_path, monkeypatch, f"dir said {_dashed(_first_serial())}")
    assert code == 0 and arch.exists(), "with the rule removed the entry should archive; the refusal test depends on the rule"


def test_rotation_refuses_when_no_serial_is_readable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(il, "serial_digests", lambda *a: frozenset())
    code, _, arch = _rotation(tmp_path, monkeypatch, "clean entry")
    said = "no local fixed volume serial" in capsys.readouterr().out
    assert code == 2 and said and not arch.exists(), "the rotation ran with no serial readable"


# ---- reports never print a serial a file name carries -------------------------------------------------------------------------------

def test_redact_serials_replaces_every_live_form_and_a_header_and_falls_back_on_encoded_forms() -> None:
    n = _first_serial()
    digests = _digests()
    for text in (f"docs/run-{_dashed(n)}.txt", f"docs/run-{n:08x}.txt", f"docs/run-{n}.txt", f"docs/run-{n:#010x}.txt",
                 f"docs/Volume Serial Number is {FOREIGN_SERIAL}.txt"):
        shown = il.redact_serials(text, digests)
        assert not _kinds(shown.encode()), "redact_serials left a serial in the text"
        assert "XXXX-XXXX" in shown and shown.startswith("docs/"), "redact_serials did not keep the path around the placeholder"
    encoded = "".join(f"%{ord(c):02X}" for c in f"{n:08X}")
    fallback = il.redact_serials(f"docs/run-{encoded}.txt", digests)
    assert "redacted" in fallback and not _kinds(fallback.encode()), "an encoded serial was printed or not replaced"
    assert il.redact_serials("docs/plain.txt", digests) == "docs/plain.txt", "redact_serials changed text without a serial"


def test_check_output_never_prints_a_serial_a_file_name_carries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    n = _first_serial()
    root = _repo_with_baseline(tmp_path / "repo")
    baseline = root / scrub.USER_BASELINE_PATH
    named = _plant(root, f"docs/s/run-{_dashed(n)}.txt", f"Volume Serial Number is {FOREIGN_SERIAL}".encode())
    out = LF.join(_check(root, [baseline, named]))
    assert not _kinds(out.encode()), "check() printed a serial carried by a file name"
    assert "XXXX-XXXX" in out and "tracked file #1" in out, "check() did not report the redacted path with its index"
    monkeypatch.setattr(il, "redact_serials", lambda text, digests: text)
    raw = LF.join(_check(root, [baseline, named]))
    assert "live" in _kinds(raw.encode()), "with the redaction removed the name should print the serial; the test above depends on it"
