"""Gate lock for the doc-rot structural control (#994).

WHAT FAILURE THIS EXISTS FOR
----------------------------
In the 48 hours before this shipped, the SAME failure recurred at least six
times: a document asserted a state the disk or the config contradicted, and a
human caught every instance by reading. #979 R1-R12 was fourteen runbook links
to files that no longer existed; #990 was a go-live runbook that read as a
ceremony to PERFORM after it had already run and its flag had flipped. That is
the vigilance ``security_by_design`` ("structural absence over configuration /
prefer a mechanism to remembering") says to replace with a gate. This is the
gate - the mechanically-catchable half.

WHAT IS LOCKED HERE
-------------------
1. The living ``docs/`` tree stays free of dead markdown pointers forever (rot
   guard), and the five ceremony runbooks keep declarations that resolve against
   the real config.
2. The verifier genuinely REFUSES each failure mode AND genuinely PASSES the
   honest form. Every check has a planted-violation twin and a both-directions
   pin (security_by_design principle 12): a correctly-STRUCK dead pointer must
   PASS, a bannerless LIVE ceremony must FAIL, a stale banner on a PENDING flag
   must FAIL. A validator nobody has watched pass the correct fix is as
   dangerous as one nobody has watched reject the defect - the whole point of
   this control is a LOW false-positive rate, so the negative controls carry as
   much weight as the toggle-offs.

HONEST LIMIT (mirrored from the verifier's own docstring): this locks DEAD
POINTERS and CEREMONY-BANNER agreement. It does NOT lock semantic truth - a
comment claiming a lock that isn't engaged, a "disposable dev data" line over a
live store. Those stay with human / adversarial review or an executable posture
check (#977). Inline path references are deliberately NOT gated (measured
prohibitive false-positive rate); the tests below pin that decision so it cannot
silently regress into a noisy gate.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFIER = REPO_ROOT / "scripts" / "verify_doc_pointers_and_banners.py"
DOCS = REPO_ROOT / "docs"
RUNBOOKS = DOCS / "runbooks"
DEFAULT_TOML = REPO_ROOT / "services" / "assistant_orchestrator" / "config" / "default.toml"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from verify_doc_pointers_and_banners import (  # noqa: E402
    CROSSREPO_ALLOWLIST,
    _FLAG_REF_RE,
    _GATING_DECL_RE,
    _is_tombstone,
    ceremony_banner_violations,
    ceremony_banner_violations_in_doc,
    dead_pointer_violations,
    dead_pointers_in_doc,
    verify,
)

_EXECUTED = "> ## STATUS: EXECUTED — 2026-07-02. Do not re-run."


def _dp(text: str, *, file_dir: Path = DOCS, include_inline: bool = False) -> list[str]:
    """Dead-pointer violations for a doc-text fixture, resolved against the real repo."""
    return dead_pointers_in_doc(
        text, file_dir=file_dir, repo_root=REPO_ROOT, include_inline=include_inline
    )


# ==========================================================================
# 1. Positive control - the real repository is clean and stays clean
# ==========================================================================

def test_real_docs_tree_has_no_dead_markdown_pointers() -> None:
    """Rot guard: every markdown link in the living docs tree resolves on disk."""
    violations, n_files, n_links, n_tombstone = dead_pointer_violations(REPO_ROOT, DOCS)
    assert n_files > 0 and n_links > 0, "vacuous scan - the docs tree matched nothing"
    assert not violations, (
        "dead markdown pointer(s) in the living docs tree - a link asserting a file "
        "that does not exist:\n  " + "\n  ".join(violations)
    )


def test_real_ceremony_runbooks_pass_banner_check() -> None:
    """Every go-live/ceremony runbook declares its gating flag and its banner agrees."""
    violations, n_ceremony = ceremony_banner_violations(REPO_ROOT, RUNBOOKS, DEFAULT_TOML)
    assert n_ceremony >= 5, f"expected >=5 ceremony runbooks, matched {n_ceremony}"
    assert not violations, "ceremony banner/flag disagreement:\n  " + "\n  ".join(violations)


def test_verify_passes_on_the_real_tree() -> None:
    """End to end: the shipped verifier exits 0 on the real repository."""
    code, report = verify(REPO_ROOT)
    assert code == 0, "\n".join(report)


def test_every_ceremony_runbook_declares_flags_that_resolve_in_default_toml() -> None:
    """Rot guard on the declarations THIS build added: each `[section].key` a
    ceremony runbook declares must be a real key in default.toml. If a config key
    is renamed, this fails loud instead of the declaration silently rotting."""
    with DEFAULT_TOML.open("rb") as fh:
        toml = tomllib.load(fh)
    checked = 0
    for path in sorted(RUNBOOKS.glob("*.md")):
        name = path.name.lower()
        if "go_live" not in name and "go-live" not in name and "ceremony" not in name:
            continue
        decl = _GATING_DECL_RE.search(path.read_text(encoding="utf-8"))
        assert decl is not None, f"{path.name} lost its Gating-flag/Gating-state declaration"
        if decl.group("kind").lower() == "state":
            continue  # non-toml evidence (keystore); nothing to resolve
        flags = _FLAG_REF_RE.findall(decl.group("value"))
        assert flags, f"{path.name} declares no [section].key flag"
        for section, key in flags:
            assert isinstance(toml.get(section), dict) and key in toml[section], (
                f"{path.name} declares [{section}].{key} which is absent from default.toml"
            )
        checked += 1
    assert checked >= 4, f"expected >=4 flag-gated ceremony runbooks, checked {checked}"


# ==========================================================================
# 2. Check 1 - dead pointers: toggle-offs AND both-directions negative controls
# ==========================================================================

def test_a_dead_markdown_link_is_caught() -> None:
    """The toggle-off: a link to a non-existent file must fail."""
    v = _dp("See [the plan](./does-not-exist-xyz.md) for details.")
    assert len(v) == 1 and "dead markdown link" in v[0], v


def test_a_correctly_struck_dead_pointer_passes() -> None:
    """Both-directions pin (the #979 R3 fix must not be re-flagged).

    A dead pointer that has been DELIBERATELY struck (`~~...~~`) or annotated
    ``RETIRED (file absent)`` is documented remediation, not a defect. Re-flagging
    it would fight the correct fix and train people to mute the gate - the exact
    cry-wolf outcome this whole control exists to avoid.
    """
    fixture = (
        "Historical, neutralised pointers:\n"
        "- ~~[fleet-hygiene.md](fleet-hygiene.md)~~ **RETIRED (file absent)** — gone with the fleet.\n"
        "- ~~[docs/DEC15_x.xml](../DEC15_x.xml)~~ retired proposal.\n"
        "- struck inline ~~`../governance/fleet-hygiene.md`~~ replacement named.\n"
        "| ~~old-runbook.md~~ RETIRED (file absent) | row |\n"
    )
    assert _dp(fixture) == []


def test_anchor_and_scheme_links_are_skipped() -> None:
    """Anchors and non-filesystem schemes are not repo pointers."""
    fixture = (
        "[section](#a-heading) [ext](https://example.com/x) [mail](mailto:x@y.z) "
        "[js](javascript:void%280%29) [data](data:text/plain,hi) [tel](tel:+15551234)"
    )
    assert _dp(fixture) == []


def test_percent_encoded_target_resolves_to_a_real_spaced_filename() -> None:
    """`Use%20Cases_FINAL.md` is a real file - percent-decoding is what makes it
    resolve. This false positive is why the gate could not go green before the
    decode was added; it is pinned so the decode cannot be dropped."""
    gov = DOCS / "governance"
    assert _dp("Anchor: [UCs](../../Use%20Cases_FINAL.md).", file_dir=gov) == []


def test_illustrative_placeholders_are_skipped() -> None:
    """A bare word or a template placeholder is an example, not a pointer."""
    fixture = "Rewrite `![alt](url)` and expand [{turns}](turns) at render time."
    assert _dp(fixture) == []


def test_resolution_is_file_relative_not_cwd(tmp_path: Path) -> None:
    """A link resolves against the FILE's own directory (and repo-root fallback),
    never the process cwd - the first of the three false-positive traps."""
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "sibling.md").write_text("x", encoding="utf-8")
    (tmp_path / "uncle.md").write_text("x", encoding="utf-8")
    doc = "[a](sibling.md) [b](../uncle.md) [c](../missing-cousin.md)"
    v = dead_pointers_in_doc(doc, file_dir=sub, repo_root=tmp_path)
    assert len(v) == 1 and "missing-cousin.md" in v[0], v


def test_crossrepo_allowlisted_link_passes() -> None:
    """A documented cross-repo reference (the agentic-setup brief) is not dead here."""
    assert CROSSREPO_ALLOWLIST, "allowlist unexpectedly empty"
    target = next(iter(CROSSREPO_ALLOWLIST))
    assert _dp(f"See the brief [here]({target}) in the sibling repo.") == []


def test_inline_path_checking_is_off_by_default_but_available() -> None:
    """Pins the measured scope decision BOTH ways: an inline dead path is silent
    by default (not gated), and surfaces only under the opt-in audit flag."""
    doc = "Config lives at `config/nonexistent-xyz.toml` in the tree."
    assert _dp(doc, include_inline=False) == []
    flagged = _dp(doc, include_inline=True)
    assert len(flagged) == 1 and "dead inline path" in flagged[0], flagged


# ==========================================================================
# 3. Check 2 - ceremony banner/flag agreement: toggle-offs + both directions
# ==========================================================================

def test_live_flag_without_banner_is_caught() -> None:
    """The #990 shape: a runbook gated by a LIVE flag but carrying no EXECUTED
    banner reads as a pending instruction to re-run a spent ceremony."""
    text = "# X Go-Live\n<!-- Gating-flag: [web_search].enabled -->\nWork the steps below.\n"
    v = ceremony_banner_violations_in_doc(text, "x_go_live.md", {"web_search": {"enabled": True}})
    assert len(v) == 1 and "LIVE" in v[0] and "no EXECUTED" in v[0], v


def test_live_flag_with_banner_passes() -> None:
    """Both-directions pin: the honest form (live flag + EXECUTED banner) passes."""
    text = f"# X Go-Live\n<!-- Gating-flag: [web_search].enabled -->\n{_EXECUTED}\n"
    assert ceremony_banner_violations_in_doc(text, "x.md", {"web_search": {"enabled": True}}) == []


def test_pending_flag_with_stale_banner_is_caught() -> None:
    """The reverse defect: an EXECUTED banner over a flag still false claims a
    ceremony complete that its own config says is pending."""
    text = f"# X Go-Live\n<!-- Gating-flag: [thing].enabled -->\n{_EXECUTED}\n"
    v = ceremony_banner_violations_in_doc(text, "x.md", {"thing": {"enabled": False}})
    assert len(v) == 1 and "still false" in v[0], v


def test_pending_flag_without_banner_passes() -> None:
    """Both-directions pin: a genuinely pending ceremony (false flag, no banner)
    is correct and must not be forced to carry an EXECUTED banner."""
    text = "# X Go-Live\n<!-- Gating-flag: [thing].enabled -->\nRun this when ready.\n"
    assert ceremony_banner_violations_in_doc(text, "x.md", {"thing": {"enabled": False}}) == []


def test_ceremony_without_a_declaration_is_caught() -> None:
    """Deny-by-default: a ceremony runbook with no machine-readable gating line
    cannot be verified, so it fails until it declares one."""
    text = f"# X Go-Live Runbook\n{_EXECUTED}\nNo declaration anywhere.\n"
    v = ceremony_banner_violations_in_doc(text, "x_go_live.md", {})
    assert len(v) == 1 and "no machine-readable gating declaration" in v[0], v


def test_multi_flag_all_live_requires_a_banner() -> None:
    """uc010 shape: two gating flags, both live => a banner is required."""
    toml = {"image_generation": {"enabled": True, "require_signed_manifest": True}}
    decl = "<!-- Gating-flags: [image_generation].enabled, [image_generation].require_signed_manifest -->"
    assert len(ceremony_banner_violations_in_doc(f"# G\n{decl}\nno banner\n", "u_go_live.md", toml)) == 1
    assert ceremony_banner_violations_in_doc(f"# G\n{decl}\n{_EXECUTED}\n", "u_go_live.md", toml) == []


def test_multi_flag_one_pending_without_banner_passes() -> None:
    """If any of several gating flags is still false, the ceremony is pending."""
    toml = {"image_generation": {"enabled": True, "require_signed_manifest": False}}
    decl = "<!-- Gating-flags: [image_generation].enabled, [image_generation].require_signed_manifest -->"
    assert ceremony_banner_violations_in_doc(f"# G\n{decl}\nno banner\n", "u_go_live.md", toml) == []


def test_gating_state_ceremony_requires_a_banner() -> None:
    """at_rest shape: executed-state evidenced outside toml still owes an EXECUTED
    banner (a run-once ceremony must state it has run)."""
    decl = "<!-- Gating-state: keystore -->"
    assert len(ceremony_banner_violations_in_doc(f"# C\n{decl}\nno banner\n", "at_rest_ceremony.md", {})) == 1
    assert ceremony_banner_violations_in_doc(f"# C\n{decl}\n{_EXECUTED}\n", "at_rest_ceremony.md", {}) == []


def test_declared_flag_absent_from_toml_is_caught() -> None:
    """Rot guard: a declaration pointing at a config key that does not exist fails
    loud (the key was renamed and the declaration was not updated)."""
    text = f"# X Go-Live\n<!-- Gating-flag: [ghost_section].enabled -->\n{_EXECUTED}\n"
    v = ceremony_banner_violations_in_doc(text, "x.md", {"web_search": {"enabled": True}})
    assert len(v) == 1 and "not found in default.toml" in v[0], v


# ==========================================================================
# 4. Vacuous-pass guards (the #970 shape) and reachability
# ==========================================================================

def _skeleton(tmp: Path) -> Path:
    """A minimal valid repo: docs/ with one clean doc, an empty runbooks/, a toml."""
    (tmp / "docs" / "runbooks").mkdir(parents=True)
    (tmp / "docs" / "foo.md").write_text("# Foo\n[self](foo.md)\n", encoding="utf-8")
    cfg = tmp / "services" / "assistant_orchestrator" / "config"
    cfg.mkdir(parents=True)
    (cfg / "default.toml").write_text("[web_search]\nenabled = true\n", encoding="utf-8")
    return tmp


def test_zero_ceremony_runbooks_fails_loud_not_vacuous(tmp_path: Path) -> None:
    """A run that matches no ceremony runbook is a broken glob, not a clean tree."""
    code, report = verify(_skeleton(tmp_path))
    assert code == 2 and "vacuous" in "\n".join(report).lower(), "\n".join(report)


def test_missing_scan_scope_raises(tmp_path: Path) -> None:
    """A vanished scan directory is fail-loud, never a silent pass."""
    with pytest.raises(FileNotFoundError):
        dead_pointer_violations(tmp_path, tmp_path / "docs")


def test_the_verifier_is_wired_and_executable() -> None:
    """Reachability, not just behaviour - the built-but-wired-into-nothing guard."""
    assert VERIFIER.exists(), f"missing {VERIFIER}"
    out = subprocess.run([sys.executable, str(VERIFIER), "--help"], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr


# ==========================================================================
# 5. Regression locks for defects an independent adversarial review found
#    (2026-07-20). Each is a hole the first draft shipped with; the negative
#    controls (the honest form must PASS) matter as much as the toggle-offs.
# ==========================================================================

def test_incidental_executed_word_is_not_a_banner() -> None:
    """Finding 1 (false NEGATIVE): a LIVE-flag runbook with the bare word 'executed'
    in prose but no real banner must still FAIL. The #990 guarantee cannot hinge on
    an incidental word appearing somewhere in the document."""
    text = ("# X Go-Live\n<!-- Gating-flag: [web_search].enabled -->\n"
            "The scheduler has executed the prep steps; now work the runbook below.\n")
    v = ceremony_banner_violations_in_doc(text, "x_go_live.md", {"web_search": {"enabled": True}})
    assert len(v) == 1 and "no EXECUTED" in v[0], v


def test_incidental_executed_word_does_not_falsely_flag_pending() -> None:
    """Finding 1 (false POSITIVE, the worst outcome): a PENDING runbook whose prose
    says 'once the ceremony is executed the flag flips' must PASS, not cry wolf."""
    text = ("# X Go-Live\n<!-- Gating-flag: [thing].enabled -->\n"
            "Once the ceremony is executed the flag flips to true.\n")
    assert ceremony_banner_violations_in_doc(text, "x_go_live.md", {"thing": {"enabled": False}}) == []


def test_all_real_banner_forms_are_recognised() -> None:
    """The tightened banner regex must still accept every shipped banner shape."""
    for banner in (
        "> ## STATUS: EXECUTED — 2026-06-27. Do not re-run.",
        "> ## ⚠ THIS CEREMONY HAS ALREADY BEEN PERFORMED — 2026-07-02 (#719)",
        "**Status:** ✅ **EXECUTED — this ceremony has already been run.**",
    ):
        text = f"# G\n<!-- Gating-flag: [web_search].enabled -->\n{banner}\n"
        got = ceremony_banner_violations_in_doc(text, "g_go_live.md", {"web_search": {"enabled": True}})
        assert got == [], f"banner not recognised: {banner!r} -> {got}"


def test_multiple_declaration_lines_are_all_checked() -> None:
    """Finding 3: two SEPARATE Gating-flag lines - the second must be checked too,
    not silently ignored because only the first was read."""
    text = ("# X Go-Live\n<!-- Gating-flag: [a].x -->\n<!-- Gating-flag: [b].y -->\n"
            f"{_EXECUTED}\n")
    toml = {"a": {"x": True}, "b": {"y": False}}  # second flag pending under a banner
    v = ceremony_banner_violations_in_doc(text, "x_go_live.md", toml)
    assert len(v) == 1 and "[b].y" in v[0] and "still false" in v[0], v


def test_trailing_text_after_comment_close_still_parses() -> None:
    """Finding 5: text after `-->` must not defeat declaration detection (which
    would wrongly report 'no declaration' - a deny-by-default false positive)."""
    text = ("# X Go-Live\n<!-- Gating-flag: [web_search].enabled --> (live 2026-07-02)\n"
            f"{_EXECUTED}\n")
    assert ceremony_banner_violations_in_doc(text, "x_go_live.md", {"web_search": {"enabled": True}}) == []


def test_unknown_gating_state_is_caught() -> None:
    """Finding 4: a bogus Gating-state label would bypass the config cross-check, so
    the label set is closed - an unknown one fails."""
    text = f"# C\n<!-- Gating-state: totally-made-up -->\n{_EXECUTED}\n"
    v = ceremony_banner_violations_in_doc(text, "c_ceremony.md", {})
    assert any("unknown Gating-state" in x for x in v), v


def test_dead_link_sharing_a_line_with_a_retired_note_is_still_caught() -> None:
    """Finding 2: a LIVE dead link must not be suppressed just because an unrelated
    '(file absent)' note appears elsewhere on the same line (the old whole-line
    skip hid exactly this)."""
    v = _dp("See [the live plan](./does-not-exist.md) — the old one is gone (file absent).")
    assert len(v) == 1 and "does-not-exist.md" in v[0], v


def test_reference_style_dead_link_caught_but_spec_lines_are_not() -> None:
    """Finding 6: a reference-style link to a missing file is caught; a same-shaped
    spec line (`[Peak RAM]: 25.6GB`) is not a pointer and must not be flagged."""
    assert len(_dp("[plan]: ./does-not-exist.md")) == 1
    assert _dp("[Peak RAM]: 25.6GB") == []
    assert _dp("[gov]: governance/README.md", file_dir=DOCS) == []  # resolves


def test_n_files_zero_fails_loud(tmp_path: Path) -> None:
    """The other vacuous branch: docs/ present but with zero .md files."""
    (tmp_path / "docs" / "runbooks").mkdir(parents=True)
    cfg = tmp_path / "services" / "assistant_orchestrator" / "config"
    cfg.mkdir(parents=True)
    (cfg / "default.toml").write_text("[x]\nenabled = true\n", encoding="utf-8")
    code, report = verify(tmp_path)
    assert code == 2 and "vacuous" in "\n".join(report).lower(), "\n".join(report)


def test_tombstone_docs_are_excluded_but_partially_retired_is_not(tmp_path: Path) -> None:
    """A whole-document SUPERSEDED / ⛔ RETIRED tombstone is historical (like archive):
    its deliberately-left dead links are not flagged. A ⚠ PARTIALLY RETIRED living index
    is NOT a tombstone - its live links must still resolve. (Learned at merge time: a
    prior session had deliberately left these dead links as-is; the checker must honor
    that structurally, not 'fix' links a human chose to leave.)"""
    assert _is_tombstone("> ## SUPERSEDED — read the command instead.\n")
    assert _is_tombstone("> # ⛔ RETIRED — the fleet no longer runs.\n")
    assert _is_tombstone("> ## RETIRED — describes a process that no longer exists.\n")
    assert not _is_tombstone("> ## ⚠ PARTIALLY RETIRED — some parts still live.\n")
    # Keyed on the WORD, never the ⛔ emoji: a live safety warning must stay gated.
    assert not _is_tombstone("> ## ⛔ STOP — DO NOT DELETE substrate.db OR sessions.db\n")

    docs = tmp_path / "docs"
    (docs / "runbooks").mkdir(parents=True)
    (docs / "tomb.md").write_text("> ## SUPERSEDED — gone.\n\n[x](./missing.md)\n", encoding="utf-8")
    (docs / "live.md").write_text("> ## ⚠ PARTIALLY RETIRED\n\n[y](./missing.md)\n", encoding="utf-8")
    violations, n_files, n_links, n_tombstone = dead_pointer_violations(tmp_path, docs)
    assert n_tombstone == 1, (n_tombstone, violations)
    assert any("live.md" in v and "missing.md" in v for v in violations), violations
    assert not any("tomb.md" in v for v in violations), violations
