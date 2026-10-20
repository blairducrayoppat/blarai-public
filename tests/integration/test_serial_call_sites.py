"""Volume serial numbers at the publishing edge (#1786): the Hugging Face preflight, the community-export scrub and its verifier, and
the phase-1 dataset sanitiser each call identity_lock's serial rules, and each call site is toggled off to show its test depends on
it.

PYTEST_DONT_REWRITE

Assertion rewriting is off for this module on purpose: a failing assertion would otherwise print the planted text, which carries
this machine's serial. Every assertion is a plain condition with a fixed message. The serial is read at run time and never written
here; the foreign serial is made up.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import build_phase1_dataset as phase1  # noqa: E402
import hf_publish  # noqa: E402
import identity_lock as il  # noqa: E402
import scrub_community_export as export  # noqa: E402
import verify_community_scrub as verify  # noqa: E402

LF = chr(10)
_FIND = il.find_serial_hits  # the real function, kept clear of the monkeypatches below
FOREIGN_SERIAL = "1A2B-3C4D"  # made up; never this machine's
HEADER = f" Volume Serial Number is {FOREIGN_SERIAL}"


def _live_text() -> str:
    serials = il.live_volume_serials()
    assert serials, "no local fixed volume serial is readable on this machine; the lock cannot see its subject"
    n = sorted(serials)[0]
    assert f"{n:08X}" != FOREIGN_SERIAL.replace("-", ""), "the made-up foreign serial collides with a live one"
    return f"{n:08X}"[:4] + "-" + f"{n:08X}"[4:]


def _carries(text: str) -> set[str]:
    return _FIND(text.encode("utf-8"), il.serial_digests())


def _clean_dir(tmp_path: Path) -> Path:
    d = tmp_path / "ds"
    d.mkdir()
    (d / "speed_visits.csv").write_text("arm,decode_tps_mean\na,12.5\n", encoding="utf-8")
    return d


def _preflight(d: Path) -> list[str]:
    return hf_publish.preflight(d)


# ---- Hugging Face preflight ---------------------------------------------------------------------------------------------------------

def test_preflight_refuses_the_live_volume_serial_in_content(tmp_path):
    d = _clean_dir(tmp_path)
    (d / "notes.txt").write_text("vol " + _live_text(), encoding="utf-8")
    hit = any("notes.txt: content carries a volume serial number of this machine" in h for h in _preflight(d))
    assert hit, "the preflight accepted a live serial in file content"


def test_preflight_refuses_a_serial_header_from_any_machine(tmp_path):
    d = _clean_dir(tmp_path)
    (d / "notes.txt").write_text(HEADER + "\n", encoding="utf-8")
    hit = any("notes.txt: content carries a 'Volume Serial Number is' header" in h for h in _preflight(d))
    assert hit, "the preflight accepted a serial header in file content"


def test_preflight_refuses_a_serial_in_a_file_name(tmp_path):
    d = _clean_dir(tmp_path)
    (d / ("run-" + _live_text() + ".txt")).write_text("x", encoding="utf-8")
    hit = any("file name carries a volume serial number of this machine" in h for h in _preflight(d))
    assert hit, "the preflight accepted a live serial in a file name"


def test_preflight_findings_never_print_a_serial_a_file_name_carries(tmp_path, monkeypatch):
    d = _clean_dir(tmp_path)
    (d / ("run-" + _live_text() + ".txt")).write_text("vol " + _live_text(), encoding="utf-8")
    text = LF.join(_preflight(d))
    assert not _carries(text), "a preflight finding printed a serial carried by a file name"
    assert "XXXX-XXXX" in text, "the preflight finding did not show the redacted path"
    monkeypatch.setattr(hf_publish._il, "redact_serials", lambda t, digests: t)
    raw = LF.join(_preflight(d))
    assert "live" in _carries(raw), "with the redaction removed the finding should print the serial; the test above depends on it"


def test_preflight_serial_toggle_removing_the_call_makes_the_probe_pass_wrongly(tmp_path, monkeypatch):
    d = _clean_dir(tmp_path)
    (d / "notes.txt").write_text("vol " + _live_text() + HEADER, encoding="utf-8")
    (d / ("run-" + _live_text() + ".txt")).write_text("x", encoding="utf-8")
    seen = any("olume serial" in h or "Volume Serial" in h for h in _preflight(d))
    monkeypatch.setattr(hf_publish._il, "find_serial_hits", lambda data, digests: set())
    blind = any("olume serial" in h or "Volume Serial" in h for h in _preflight(d))
    assert seen and not blind, "the preflight serial probe does not depend on the find_serial_hits call"


def test_preflight_fails_closed_when_no_serial_is_readable(tmp_path, monkeypatch):
    d = _clean_dir(tmp_path)
    monkeypatch.setattr(hf_publish, "_serial_digests", lambda: frozenset())
    hit = any("volume serials are not readable" in h for h in _preflight(d))
    assert hit, "the preflight passed with no serial readable"


@pytest.mark.parametrize("rel", [
    "docs/performance/qwen35_small_2026-10-04",
    "docs/performance/qwen35_small_9b_2026-10-04",
    "docs/research/containment-evidence-2026-10-05/hf-export",
])
def test_published_datasets_still_preflight_clean(rel):
    root = ROOT / rel
    assert root.is_dir(), "a published dataset directory is missing"
    hits = hf_publish.preflight(root)
    assert hits == [], f"{len(hits)} preflight finding(s) on a published dataset; run the preflight on it to read them"


# ---- community export scrub + verifier ----------------------------------------------------------------------------------------------

def test_export_scrub_rewrites_live_serial_and_header_then_verifies_clean():
    src = f"dir said{HEADER}\nvol {_live_text()} and {_live_text().lower()}\nkeep 12345\n"
    before = _carries(src)
    out, n = export.apply_subs(src)
    after = _carries(out)
    fails, _ = verify.residual_scan(out)
    serial_fails = [f for f in fails if "olume serial" in f]
    assert before == {"live", "header"}, "the planted text did not carry both serial kinds"
    assert n >= 3 and after == set() and "XXXX-XXXX" in out and "keep 12345" in out, "the export scrub did not clear the serial or changed other text"
    assert not serial_fails, "the verifier reported a serial after the scrub"


def test_export_scrub_toggle_removing_the_call_leaves_the_serial(monkeypatch):
    src = f"vol {_live_text()}{HEADER}"
    monkeypatch.setattr(export._il, "rewrite_serials", lambda data, serials: (data, 0))
    out, _ = export.apply_subs(src)
    assert _carries(out) == {"live", "header"}, "with the call removed the serial should survive; the clearing test depends on the call"


def test_export_scrub_refuses_when_no_serial_is_readable(monkeypatch):
    monkeypatch.setattr(export._il, "live_volume_serials", lambda: frozenset())
    with pytest.raises(SystemExit):
        export.apply_subs("anything")


def test_verifier_apply_subs_clears_a_header_and_a_live_serial():
    """The verifier's known-scrub must predict the export scrub's serial rewrite, or every scrubbed file reads as an unexpected change."""
    out = verify.apply_subs(f"x {_live_text()}{HEADER}")
    assert _carries(out) == set(), "the verifier's known-scrub left a serial"


def test_verifier_apply_subs_toggle_removing_the_call_leaves_the_header(monkeypatch):
    monkeypatch.setattr(verify._il, "rewrite_serials", lambda data, serials: (data, 0))
    out = verify.apply_subs(f"x {_live_text()}{HEADER}")
    assert _carries(out) == {"live", "header"}, "with the call removed the known-scrub should keep the serial; the test above depends on the call"


def test_verifier_refuses_a_live_serial_and_a_header():
    live_fails, _ = verify.residual_scan(f"x {_live_text()} y")
    header_fails, _ = verify.residual_scan(HEADER)
    clean_fails, _ = verify.residual_scan(" Volume Serial Number is XXXX-XXXX")
    assert any("volume serial of this machine" in f for f in live_fails), "the verifier accepted a live serial"
    assert any("Volume Serial Number is" in f for f in header_fails), "the verifier accepted a serial header"
    assert clean_fails == [], "the verifier reported the placeholder header"


def test_verifier_toggle_removing_the_call_passes_wrongly(monkeypatch):
    monkeypatch.setattr(verify._il, "find_serial_hits", lambda data, digests: set())
    fails, _ = verify.residual_scan(f"x {_live_text()}{HEADER}")
    assert not [f for f in fails if "erial" in f], "with the call removed the verifier should miss the serial; the test above depends on the call"


def test_verifier_fails_closed_when_no_serial_is_readable(monkeypatch):
    monkeypatch.setattr(verify._il, "serial_digests", lambda *a: frozenset())
    fails, _ = verify.residual_scan("clean")
    assert any("not readable" in f for f in fails), "the verifier passed with no serial readable"


# ---- phase-1 dataset sanitiser ------------------------------------------------------------------------------------------------------

def test_phase1_sanitise_tree_rewrites_serials_and_toggles_off(tmp_path, monkeypatch):
    f = tmp_path / "out.txt"
    f.write_text(f"vol {_live_text()}{HEADER}", encoding="utf-8")
    changed = phase1.sanitise_tree(tmp_path)
    cleared = _carries(f.read_text(encoding="utf-8")) == set()
    assert changed >= 1 and cleared, "sanitise_tree did not clear the serial"
    f.write_text(f"vol {_live_text()}", encoding="utf-8")
    monkeypatch.setattr(phase1._il, "rewrite_serials", lambda data, serials: (data, 0))
    with pytest.raises(SystemExit):
        phase1.sanitise_tree(tmp_path)  # with the rewrite removed the post-check still refuses
    monkeypatch.setattr(phase1._il, "find_serial_hits", lambda data, digests: set())
    phase1.sanitise_tree(tmp_path)
    survived = _carries(f.read_text(encoding="utf-8")) == {"live"}
    assert survived, "with both calls removed the serial should be written out; the clearing half depends on them"


def test_phase1_sanitise_tree_refuses_when_no_serial_is_readable(tmp_path, monkeypatch):
    monkeypatch.setattr(phase1._il, "live_volume_serials", lambda: frozenset())
    with pytest.raises(SystemExit):
        phase1.sanitise_tree(tmp_path)
