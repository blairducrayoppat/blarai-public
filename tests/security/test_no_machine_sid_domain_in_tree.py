"""Gate lock: no tracked file carries this machine's Windows account-domain SID, in any text form.

WHAT FAILURE THIS EXISTS FOR
----------------------------
On 2026-10-13 (#1765) 87 tracked files carried the machine's real account domain (the three sub-authority numbers of
``S-1-5-21-a-b-c-<rid>``), 918 occurrences, and four of them had already reached the public mirror because the
publisher's leak gate did not hold. The domain was rewritten to a placeholder (``scripts/rewrite_sid_domain.py``). This
test keeps it out: every file ``git ls-files`` names is scanned for the bare digit form ``a-b-c``, which also covers the
prefixed form, so a SID written without ``S-1-5-21-`` is caught too.

The domain is never written here. Two sources name it, both must hold:
  * DIGESTS: sha256 of the known domain strings, so the lock holds on any machine and for a domain this box no longer has;
    SUB_AUTHORITY_DIGESTS: sha256 of each of the domain's three numbers on its own, so a truncated quotation
    (``...-<third number>-1001``) is caught too (one such fragment survived the 2026-10-13 rewrite in a review record).
  * The live machine: the current identity's account domain from .NET ``WindowsIdentity``. On Windows this MUST be readable;
    the test fails, never skips, when it is not (a lock that cannot see its subject is not a lock).
Only tracked files are scanned: untracked files are other sessions' work and are not this test's to judge; the lock fires on
the commit that tracks one.

How a file is read: every run of ASCII digits and dashes is one token; every window of three consecutive numbers in it is
checked against DIGESTS (so ``S-1-5-21-a-b-c-1001``, ``a-b-c``, ``5-a-b-c`` and an SDDL string all resolve to the same
window), and every number of SUB_AUTHORITY_MIN_DIGITS digits or more is checked against SUB_AUTHORITY_DIGESTS.

HONEST LIMIT: the scan sees the domain's numbers written as contiguous ASCII digits. The whole-domain check needs the three
numbers dash-joined; the per-number check catches each number wherever it stands alone (split across lines, spaced, dotted,
en-dashed). Neither sees a number glued to further digits (``...4125...9`` with extra digits on either side), a UTF-16 file,
or a number written in another base. Binary tracked files (containing a NUL byte) are scanned the same way as text; a match
in one fails the test. ``scripts/rewrite_sid_domain.py --check`` sees only the whole domain; this test is the wider net.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
# sha256 of the bare domain string "a-b-c" (ASCII) for every account domain this repository has carried. Append, never remove.
DIGESTS: frozenset[str] = frozenset({
    "e9e87c29ebaa208332b8cabdbdfe9d0b10100a083928886299aa05f55a076802",  # this machine, rewritten out 2026-10-13 (#1765)
})
# sha256 of each sub-authority number of the domains above, on its own (ASCII digits). Append with DIGESTS.
SUB_AUTHORITY_DIGESTS: frozenset[str] = frozenset({
    "b17e346ceadb8ee2b4ca994102b92421d883d2045f7f99ee456d5efd79f6d87c",  # first number of this machine's domain
    "0f263514479edf046129a838454ce1fef46d1b34c6a6002a8563caa80f7c2d14",  # second
    "be71661d8435452fb968bc8cb25cff4f153cfda1dd9c4a084f69b632a8ade40e",  # third
})
SUB_AUTHORITY_MIN_DIGITS = 8
TOKEN_RE = re.compile(rb"\d+(?:-\d+)*")
_LIVE_DOMAIN_CMD = "[System.Security.Principal.WindowsIdentity]::GetCurrent().User.AccountDomainSid.Value"


def tracked_files(root: Path) -> list[Path]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True).stdout
    return [root / p.decode("utf-8") for p in out.split(b"\0") if p]


def live_machine_domain() -> str | None:
    """The current identity's account domain as ``a-b-c``; None when no shell can read it."""
    for shell in ("pwsh", "powershell"):
        try:
            out = subprocess.run([shell, "-NoProfile", "-Command", _LIVE_DOMAIN_CMD], capture_output=True, text=True, timeout=60, check=False).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            continue
        m = re.fullmatch(r"S-1-5-21-(\d+-\d+-\d+)", out)
        if m:
            return m.group(1)
    return None


def count_hits(data: bytes, digests: frozenset[str], sub_digests: frozenset[str], live_domain: str | None) -> int:
    """Windows of three dash-joined numbers whose sha256 is in ``digests`` or which equal ``live_domain``, plus single numbers of
    SUB_AUTHORITY_MIN_DIGITS digits or more whose sha256 is in ``sub_digests``."""
    live = live_domain.encode("ascii") if live_domain else None
    live_parts = set(live.split(b"-")) if live else set()
    memo: dict[bytes, bool] = {}

    def known(tok: bytes, pool: frozenset[str], extra: object) -> bool:
        if tok not in memo:
            memo[tok] = tok == extra or (isinstance(extra, set) and tok in extra) or hashlib.sha256(tok).hexdigest() in pool
        return memo[tok]

    hits = 0
    for m in TOKEN_RE.finditer(data):
        parts = m.group(0).split(b"-")
        hits += sum(known(b"-".join(parts[i:i + 3]), digests, live) for i in range(len(parts) - 2))
        hits += sum(known(p, sub_digests, live_parts) for p in parts if len(p) >= SUB_AUTHORITY_MIN_DIGITS)
    return hits


def offending_files(files: list[Path], digests: frozenset[str], live_domain: str | None, sub_digests: frozenset[str] = frozenset()) -> list[str]:
    """``path: count`` for every file whose bytes hold the domain (by digest or live value) or one of its numbers (by digest)."""
    bad: list[str] = []
    for f in files:
        if not f.is_file():
            continue
        hits = count_hits(f.read_bytes(), digests, sub_digests, live_domain)
        if hits:
            bad.append(f"{f.as_posix()}: {hits}")
    return bad


def test_the_live_machine_domain_is_readable_on_windows() -> None:
    if sys.platform != "win32":
        pytest.skip("the live-domain source is Windows-only; the digest source still runs")
    assert live_machine_domain() is not None, "the machine's account domain could not be read from .NET WindowsIdentity; the lock cannot see its subject"


def test_no_tracked_file_carries_the_machine_sid_domain() -> None:
    assert DIGESTS and SUB_AUTHORITY_DIGESTS
    bad = offending_files(tracked_files(REPO_ROOT), DIGESTS, live_machine_domain(), SUB_AUTHORITY_DIGESTS)
    assert bad == [], (
        "tracked files carry the machine's account domain or one of its numbers; scripts/rewrite_sid_domain.py rewrites the whole domain, "
        "a lone number is rewritten by hand to the placeholder's matching number:\n" + "\n".join(bad)
    )


def test_toggle_the_scan_catches_a_planted_domain_in_every_form(tmp_path: Path) -> None:
    """A domain whose digest is pinned is caught with and without the S-1-5-21 prefix, with any relative id, glued to a leading number
    (``5-a-b-c``), and across a line of prose; one of its numbers alone is caught by the sub-authority digest; the placeholder, a fabricated
    domain, a near miss (one digit changed) and a short number are not caught. The live domain and its numbers are caught by themselves."""
    planted = "4000000001-2000000002-3000000003"
    digests = frozenset({hashlib.sha256(planted.encode()).hexdigest()})
    subs = frozenset(hashlib.sha256(p.encode()).hexdigest() for p in planted.split("-"))
    f = tmp_path / "x.json"
    for text, caught in (
        (f"S-1-5-21-{planted}-1001", 1),
        (f"the domain `{planted}` is this machine", 1),
        (f"5-{planted}-1001 and S-1-5-21-5-{planted}-1001", 2),
        (f"O:S-1-5-21-{planted}-1001G:S-1-5-21-{planted}-513D:(A;;FA;;;S-1-5-21-{planted}-1271)", 3),
        ("S-1-5-21-1000000001-1000000002-1000000003-1001", 0),
        ("S-1-5-21-1-2-3-1001 and S-1-5-21-1111111111-2222222222-3333333333-1001", 0),
    ):
        f.write_text(text, encoding="utf-8")
        got = offending_files([f], digests, None)
        assert got == ([f"{f.as_posix()}: {caught}"] if caught else []), (text, got)
    # a near miss (one digit changed) is not the domain, but its two unchanged numbers are caught by the per-number digests
    f.write_text(f"S-1-5-21-{planted[:-1]}4-1001", encoding="utf-8")
    assert offending_files([f], digests, None) == []
    assert offending_files([f], digests, None, subs) == [f"{f.as_posix()}: 2"]
    # a number glued to further digits is the declared miss
    f.write_text(f"9{planted.split('-')[0]}9", encoding="utf-8")
    assert offending_files([f], digests, None, subs) == []
    # one number alone: caught only through the sub-authority digests
    f.write_text("token SID ...-3000000003-1001 was returned", encoding="utf-8")
    assert offending_files([f], digests, None) == []
    assert offending_files([f], digests, None, subs) == [f"{f.as_posix()}: 1"]
    f.write_text("...-1001 and 20261013 and 4000000001", encoding="utf-8")
    assert offending_files([f], digests, None, subs) == [f"{f.as_posix()}: 1"]
    # the live domain, with no digest at all, is caught whole and by its numbers
    f.write_text("S-1-5-21-5000000005-6000000006-7000000007-1001", encoding="utf-8")
    assert offending_files([f], frozenset(), "5000000005-6000000006-7000000007") == [f"{f.as_posix()}: 4"]
    assert offending_files([f], frozenset(), None) == []


def test_toggle_only_listed_files_are_scanned(tmp_path: Path) -> None:
    planted = "4000000001-2000000002-3000000003"
    digests = frozenset({hashlib.sha256(planted.encode()).hexdigest()})
    (tmp_path / "tracked.txt").write_text("clean", encoding="utf-8")
    (tmp_path / "untracked.txt").write_text(f"S-1-5-21-{planted}-1001", encoding="utf-8")
    assert offending_files([tmp_path / "tracked.txt"], digests, None) == []
    assert offending_files([tmp_path / "tracked.txt", tmp_path / "untracked.txt"], digests, None) != []


def test_the_digest_lists_pin_the_rewritten_domain_and_not_the_placeholder() -> None:
    assert hashlib.sha256(b"1000000001-1000000002-1000000003").hexdigest() not in DIGESTS
    assert not {hashlib.sha256(p).hexdigest() for p in (b"1000000001", b"1000000002", b"1000000003")} & SUB_AUTHORITY_DIGESTS
    assert len(DIGESTS) >= 1 and all(re.fullmatch(r"[0-9a-f]{64}", d) for d in DIGESTS | SUB_AUTHORITY_DIGESTS)
    assert len(SUB_AUTHORITY_DIGESTS) >= 3 * len(DIGESTS)


def test_the_sub_authority_digests_are_those_of_the_live_domain_when_this_is_the_rewritten_machine() -> None:
    """On the machine whose domain is pinned, each of its three numbers hashes into SUB_AUTHORITY_DIGESTS; elsewhere this says nothing."""
    live = live_machine_domain()
    if live is None or hashlib.sha256(live.encode()).hexdigest() not in DIGESTS:
        pytest.skip("not the machine whose domain is pinned")
    assert {hashlib.sha256(p.encode()).hexdigest() for p in live.split("-")} <= SUB_AUTHORITY_DIGESTS
