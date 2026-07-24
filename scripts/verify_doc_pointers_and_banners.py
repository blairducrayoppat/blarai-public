"""
BlarAI documentation pointer + ceremony-banner verifier (#994)
==============================================================
The structural control for the documentation-asserts-a-false-state class. In the
48 hours before this shipped, the SAME failure recurred at least six times: a
document claimed a state the disk or the config contradicted, and every instance
was caught only by a human reading it or an independent review.

  * #979 R1-R12 - fourteen runbook links pointing at files that no longer exist.
  * #990 / #979 - go-live runbooks reading as "a ceremony to perform" AFTER the
    ceremony had run and the flag had flipped (a bannerless, still-present-tense
    activation guide is a live instruction to re-run a one-shot event).

That is exactly the vigilance ``security_by_design`` ("structural absence over
configuration / prefer a mechanism to remembering") says to replace with a gate.
This is that gate - the mechanically-catchable half.

WHAT THIS ENFORCES
------------------
Check 1 - DEAD RELATIVE POINTERS (markdown links over living ``docs/``):
    Every markdown link ``[text](target)`` in a living doc must resolve on disk.
    This is the GATED check - it is the exact shape #979's fourteen dead pointers
    took, and building it caught more #979 missed (bare ``AUTONOMOUS_FLEET_
    OPERATIONS.md`` links after the file was archived; governance links to three
    since-RENAMED ADRs).

    The false-positive traps that decide whether this control is trusted or muted
    (a link checker that cries wolf is worse than none - it trains people to route
    around it):
      - links resolve relative to the FILE's own directory (and, as a fallback,
        the repo root), never the cwd;
      - targets are percent-decoded (``Use%20Cases_FINAL.md`` -> a real file),
        scheme URLs (``http(s)://``, ``mailto:``, ``javascript:``, ``data:``) and
        illustrative placeholders (``url``, ``{turns}``) are skipped;
      - a DELIBERATELY-struck dead pointer is documented remediation, not a
        defect. A link inside ``~~strikethrough~~`` or on a line flagged
        ``RETIRED (file absent)`` is skipped (the #979 R3 fix pattern). Re-
        flagging those would fight the correct fix;
      - the frozen ``docs/archive/`` tree and the gitignored ``docs/handoffs/``
        tree are OUT of the gate: an archive pointer describes a past state and
        must not be rewritten to please a lint.

    INLINE (backtick) path references are NOT gated. Measured over the whole
    corpus they yield 2,892 hits dominated by things that are not defects here -
    backup-directory layouts in the disaster-recovery runbook, retired-fleet-world
    paths, gitignored model-internal dirs (``unet/``), cross-repo agentic-setup
    refs. Gating that would be the cry-wolf failure this control exists to prevent.
    The capability is retained behind ``--inline`` for targeted audits; a bounded
    living-runbook inline audit is ticketed separately (see #994 disposition).

Check 2 - CEREMONY / GO-LIVE BANNER <-> FLAG AGREEMENT (over ``docs/runbooks/``):
    A ``*go_live*`` / ``*ceremony*`` runbook must self-declare, in a machine-
    readable line, the flag(s) that gate it:

        <!-- Gating-flag:  [web_search].enabled -->
        <!-- Gating-flags: [image_generation].enabled, [image_generation].require_signed_manifest -->
        <!-- Gating-state: keystore -->            (evidence lives outside default.toml)

    The checker cross-checks THAT declaration against
    ``services/assistant_orchestrator/config/default.toml``, BOTH directions:
      - every gating flag live (``= true``)  =>  an EXECUTED / ALREADY-PERFORMED
        banner is REQUIRED (else the runbook reads as a pending instruction to
        re-run a spent ceremony - the #990 defect);
      - any gating flag ``false`` (genuinely pending)  =>  a stale EXECUTED
        banner is REFUSED (it would claim done what is not).
    A ceremony runbook with NO declaration fails deny-by-default: the machine-
    readable contract is the point - a self-describing line that rots is
    impossible to keep, because the checker resolves it against live config
    every build. This is deliberately NOT a hardcoded runbook->flag map: a map
    maintained by hand is the exact rot this gate exists to catch.

HONEST LIMIT (stated because a control that overstates its coverage is the
precise defect class this repository keeps re-learning - see #978 probe 2):

    This catches DEAD POINTERS and MISSING/STALE CEREMONY BANNERS. It does NOT
    catch SEMANTIC falsehoods - a comment asserting a lock that isn't actually
    engaged, #979 R1's "disposable dev data" claim over live production stores,
    an "N independent locks" count. Those depend on runtime wiring and meaning,
    not on a resolvable path or a flag value; they stay with human / adversarial
    review or an executable boot-time posture check (#977). A green run here
    means "no dead pointer and every ceremony banner agrees with its flag" - it
    does NOT mean "every documented claim is true."

Exit code: 0 only when both checks pass; non-zero on any violation. Fails LOUD
(not silently green) if a scanned directory has vanished or matched zero files -
a checker that quietly matches nothing is the vacuous-pass shape (#970).

Usage (from repo root, or anywhere with ``--repo``):
  python scripts/verify_doc_pointers_and_banners.py
  python scripts/verify_doc_pointers_and_banners.py --repo C:/Users/mrbla/BlarAI
  python scripts/verify_doc_pointers_and_banners.py --scope docs/runbooks
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path
from urllib.parse import unquote

#: Trees excluded from the pointer GATE. ``archive`` is frozen history - its
#: pointers describe a past state and must never be rewritten to satisfy a lint
#: (re-pointing a historical record falsifies it). ``handoffs`` is a gitignored,
#: ephemeral working dir (successor briefs), not part of the tracked corpus.
EXCLUDE_DIR_PREFIXES = ("docs/archive/", "docs/handoffs/")

# --------------------------------------------------------------------------
# Check 1 - dead relative pointers
# --------------------------------------------------------------------------

#: Markdown link target: `[text](target)` or `[text](target "title")`, plus the
#: angle-bracket form `[text](<target>)`. Captures the raw target only.
_MD_LINK_RE = re.compile(r"\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")

#: Inline code span - a candidate path reference.
_INLINE_RE = re.compile(r"`([^`]+)`")

#: A struck span (`~~...~~`) is a documented dead pointer; excise it before scanning.
_STRUCK_RE = re.compile(r"~~.+?~~")

#: Reference-style link definition: `[label]: target` at line start (<=3 spaces).
_MD_REFDEF_RE = re.compile(r"^ {0,3}\[[^\]]+\]:\s*(\S+)")

#: A whole-document tombstone banner: a top heading whose TEXT says SUPERSEDED or
#: RETIRED. Such a doc is kept for historical reference only - its internal pointers
#: describe retired procedures and are DELIBERATELY left as-is (a documented
#: #945/#979 decision: "left as-is rather than repointed, because the procedures
#: they belong to are themselves retired"). Excluded from the pointer gate exactly
#: as docs/archive/ is - a tombstone is history that happens to live outside the
#: archive dir. Keyed on the WORD, never the ⛔ emoji alone:
#: at_rest_encryption_ceremony.md opens with "⛔ STOP - DO NOT DELETE ..." as a LIVE
#: safety warning and must stay gated. "⚠ PARTIALLY RETIRED" (LA_OPERATIONS_INDEX)
#: is a living index whose live links must still resolve - excluded below.
_TOMBSTONE_HEADING_RE = re.compile(
    r"^>?\s*#{1,3}\s[^\n]*\b(?:SUPERSEDED|RETIRED)\b", re.MULTILINE | re.IGNORECASE
)


def _is_tombstone(text: str) -> bool:
    """True if the doc opens with a whole-document SUPERSEDED / RETIRED banner.

    A historical tombstone (kept for reference; dead links deliberately left as-is)
    is excluded from the pointer gate like docs/archive/. A "PARTIALLY RETIRED"
    living index is NOT a tombstone - its live links must still resolve.
    """
    return any(
        "PARTIALLY RETIRED" not in m.group(0).upper()
        for m in _TOMBSTONE_HEADING_RE.finditer(text[:1500])
    )

#: External / non-filesystem link schemes - never a repo pointer.
_URL_RE = re.compile(r"^[a-z][a-z0-9+.\-]*://|^mailto:|^tel:", re.IGNORECASE)

#: ANY scheme-prefixed target (`http://`, `mailto:`, `javascript:`, `data:`, a
#: `C:\` drive path) - not a repo-relative pointer. Broader than _URL_RE because
#: `javascript:...` and `data:...` carry no `//` yet are still non-file targets.
_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")

#: Known doc/code extensions that make a non-resolving inline token a CONFIDENT path.
_PATH_EXTS = (
    ".md", ".py", ".ps1", ".psm1", ".toml", ".json", ".jsonl", ".yaml", ".yml",
    ".txt", ".sh", ".cfg", ".ini", ".cs", ".csproj", ".sln", ".xaml", ".sig",
    ".png", ".svg", ".ico", ".html", ".htm", ".csv", ".xml",
)

#: Documented cross-repo / external references that are NOT dead pointers in THIS
#: repo. Each entry is a reviewed act - a path that lives in a sibling repo or is
#: an illustrative template, keyed by the exact token as it appears in prose.
#: Adding to this set is how a legitimate non-resolving reference is signed off;
#: the quarterly doc pass prunes entries whose reference has been removed.
CROSSREPO_ALLOWLIST: frozenset[str] = frozenset(
    {
        # The headless-coding dispatch brief lives in the agentic-setup repo
        # (C:/Users/mrbla/agentic-setup), referenced from BlarAI runbooks/index.
        "docs/blarai-headless-coding-agent-brief.md",
    }
)


def _looks_like_repo_path(token: str) -> bool:
    """A conservative shape test: is this inline token plausibly an in-repo path?

    Deliberately strict to keep the inline scan from crying wolf. Requires a
    path separator and rejects anything that reads like code, a URL, an env var,
    or an absolute/foreign path.
    """
    t = token.strip()
    if "/" not in t:
        return False  # a bare filename or a `flag = value` snippet: too ambiguous
    if any(c in t for c in " \t=(){}|<>*?\"'`,;"):
        return False  # code / prose fragment, not a path
    if _URL_RE.search(t):
        return False
    if t.startswith(("%", "$", "~/")):
        return False  # env var / home-relative
    if re.match(r"^[A-Za-z]:[\\/]", t) or t.startswith("\\\\") or t.startswith("/"):
        return False  # absolute Windows / UNC / posix-absolute path (often foreign)
    return True


def _resolves(target: str, file_dir: Path, repo_root: Path) -> bool:
    """True if ``target`` resolves relative to the file's dir OR the repo root."""
    for base in (file_dir, repo_root):
        try:
            if (base / target).exists():
                return True
        except OSError:
            continue
    return False


def _clean_target(raw: str) -> str | None:
    """Normalise a markdown link target; return None for a non-filesystem target.

    Handles the real-world shapes the corpus contains: `<angle>` wrapping,
    percent-escapes (`Use%20Cases_FINAL.md` -> `Use Cases_FINAL.md`), anchors/
    queries, scheme URLs (`http://`, `javascript:`, `data:`), and illustrative
    placeholders (`url`, `{turns}`) that are examples, not pointers. Getting
    these right is what separates a trusted checker from one people mute.
    """
    target = raw.strip().strip("<>").strip()
    # A scheme-prefixed target is never a repo-relative pointer. Checked BEFORE
    # unquoting so `javascript:%2E` and friends are still caught.
    if _SCHEME_RE.match(target):
        return None
    # Drop a trailing anchor or query - the file part is what must exist.
    target = target.split("#", 1)[0].split("?", 1)[0].strip()
    if not target:
        return None  # was a pure anchor (#section) or empty
    # A placeholder, not a path: template braces, or a bare word carrying neither
    # a separator nor an extension (e.g. `url`). Checked BEFORE unquote so a real
    # spaced filename (post-decode) is not mistaken for a placeholder.
    if "{" in target or "}" in target:
        return None
    if "/" not in target and "." not in target:
        return None
    return unquote(target)


def dead_pointers_in_doc(text: str, *, file_dir: Path, repo_root: Path,
                         allowlist: frozenset[str] = CROSSREPO_ALLOWLIST,
                         include_inline: bool = False) -> list[str]:
    """Every dead-pointer violation in one document's text.

    Markdown links are the GATED check: an explicit "this file exists" navigation
    claim, mechanically unambiguous, and the exact shape #979's fourteen dead
    pointers took.

    Inline backtick references (``include_inline=True``) are an OPT-IN audit aid,
    not gated. Measured over the whole ``docs/`` corpus they produce a prohibitive
    false-positive rate (2,892 hits: backup-directory layouts, retired-fleet-world
    paths, gitignored model-internal dirs, cross-repo refs) - exactly the cry-wolf
    outcome this control exists to avoid. They are checked only under the
    conservative shape test AND a confident extension, and even then the scan
    deliberately under-flags.
    """
    violations: list[str] = []
    for lineno, raw_line in enumerate(text.splitlines(), 1):
        # Excise ~~struck~~ spans ONLY: a deliberately-struck pointer is documented
        # remediation (the #979 R3 pattern), not a defect. Scoping to the struck
        # span - not the whole line - keeps a LIVE link that merely shares a line
        # with an unrelated "(file absent)" note from slipping through un-gated.
        line = _STRUCK_RE.sub("", raw_line)

        for m in _MD_LINK_RE.finditer(line):
            target = _clean_target(m.group(1))
            if target is None or target in allowlist:
                continue
            if not _resolves(target, file_dir, repo_root):
                violations.append(f"L{lineno}: dead markdown link -> {target!r}")

        ref = _MD_REFDEF_RE.match(line)
        if ref:
            # `[label]: dest` is a link-reference definition, but the same shape is
            # also written for non-links (`[Peak RAM]: 25.6GB`). Hold reference
            # targets to the conservative path-shape test used for inline refs, so
            # a spec line is never mistaken for a dead pointer.
            target = _clean_target(ref.group(1))
            if (target is not None and target not in allowlist
                    and _looks_like_repo_path(target)
                    and (target.endswith(_PATH_EXTS) or target.endswith("/"))
                    and not _resolves(target, file_dir, repo_root)):
                violations.append(f"L{lineno}: dead reference-style link -> {target!r}")

        if not include_inline:
            continue
        for m in _INLINE_RE.finditer(line):
            token = m.group(1).strip()
            if token in allowlist or not _looks_like_repo_path(token):
                continue
            confident = token.endswith(_PATH_EXTS) or token.endswith("/")
            if confident and not _resolves(token, file_dir, repo_root):
                violations.append(f"L{lineno}: dead inline path -> {token!r}")
    return violations


def dead_pointer_violations(
    repo_root: Path, scope: Path,
    allowlist: frozenset[str] = CROSSREPO_ALLOWLIST,
    exclude_prefixes: tuple[str, ...] = EXCLUDE_DIR_PREFIXES,
    include_inline: bool = False,
) -> tuple[list[str], int, int]:
    """Scan every gated ``*.md`` under ``scope``. Returns (violations, files, links, tombstones).

    Files under ``exclude_prefixes`` (frozen archive, gitignored handoffs) and
    whole-document tombstones (SUPERSEDED / ⛔ RETIRED) are skipped; ``tombstones``
    counts the latter so the exclusion is surfaced, never silent. ``files`` and
    ``links`` let the caller fail LOUD on a vacuous match (a scope that resolves to
    zero files or zero links is a broken scan, not a clean tree - the #970 shape).
    """
    if not scope.is_dir():
        raise FileNotFoundError(f"pointer-scan scope is not a directory: {scope}")
    violations: list[str] = []
    n_files = 0
    n_links = 0
    n_tombstone = 0
    for path in sorted(scope.rglob("*.md")):
        rel = path.relative_to(repo_root).as_posix()
        if any(rel.startswith(p) for p in exclude_prefixes):
            continue
        text = path.read_text(encoding="utf-8")
        if _is_tombstone(text):
            n_tombstone += 1  # SUPERSEDED / ⛔ RETIRED historical doc - excluded like archive
            continue
        n_files += 1
        n_links += len(_MD_LINK_RE.findall(text))
        for v in dead_pointers_in_doc(
            text, file_dir=path.parent, repo_root=repo_root,
            allowlist=allowlist, include_inline=include_inline,
        ):
            violations.append(f"{rel} {v}")
    return violations, n_files, n_links, n_tombstone


# --------------------------------------------------------------------------
# Check 2 - ceremony / go-live banner <-> flag agreement
# --------------------------------------------------------------------------

#: A runbook is a ceremony/go-live doc if its filename carries one of these.
_CEREMONY_NAME_RE = re.compile(r"go[_-]?live|ceremony", re.IGNORECASE)

#: The self-declared gating line (bare, or wrapped in an HTML comment). Value is
#: captured non-greedily up to the comment close or line end, so trailing text
#: after `-->` does not defeat detection (that shape wrongly read as "no
#: declaration"). ALL such lines are honored via finditer, not just the first -
#: two separate `Gating-flag:` lines must BOTH be checked.
_GATING_DECL_RE = re.compile(
    r"Gating-(?P<kind>flags?|state)\s*:\s*(?P<value>.+?)\s*(?:-->|$)",
    re.IGNORECASE | re.MULTILINE,
)

#: A `[section].key` flag reference inside a declaration value.
_FLAG_REF_RE = re.compile(r"\[([A-Za-z_][A-Za-z0-9_]*)\]\.([A-Za-z_][A-Za-z0-9_]*)")

#: Accepted `Gating-state` labels (non-toml executed-evidence). A CLOSED set: a
#: new label is a reviewed act, so a ceremony cannot be quietly relabelled to a
#: bogus state to skip the config cross-check. `keystore` = DEK keystore-file
#: existence (at-rest encryption).
_VALID_GATING_STATES: frozenset[str] = frozenset({"keystore"})

#: The affirmative "this ceremony has run" banner. DELIBERATELY tight: a bare
#: "executed" in prose ("the scheduler executed prep steps") must NOT satisfy it,
#: or the #990 guarantee is defeated by an incidental word and its twin false
#: positive cries wolf on a pending runbook. Every one of the five shipped banner
#: forms is matched; incidental prose is not.
_EXECUTED_BANNER_RE = re.compile(
    r"STATUS:\s*[*✅\s]*EXECUTED"                   # "STATUS: EXECUTED", "STATUS: ✅ EXECUTED"
    r"|\*\*Status:\*\*[^\n]*\bEXECUTED\b"           # "**Status:** ✅ **EXECUTED — ..."
    r"|\bALREADY\s+(?:BEEN\s+)?PERFORMED\b"         # "HAS ALREADY BEEN PERFORMED"
    r"|\bEXECUTED\b\s*[—–-]\s*\d{4}-\d{2}-\d{2}",   # "EXECUTED — 2026-06-27"
    re.IGNORECASE,
)


def _flag_value(toml: dict, section: str, key: str) -> bool | None:
    """Live value of ``[section].key`` in the parsed toml, or None if absent."""
    node = toml.get(section)
    if not isinstance(node, dict) or key not in node:
        return None
    return bool(node[key])


def ceremony_banner_violations_in_doc(text: str, name: str, toml: dict) -> list[str]:
    """Banner<->flag violations for one ceremony runbook. Empty list == pass.

    Collects EVERY gating declaration line (not just the first), merges the flags
    they name, and cross-checks against config both directions.
    """
    violations: list[str] = []
    flags: list[tuple[str, str]] = []
    states: list[str] = []
    for decl in _GATING_DECL_RE.finditer(text):
        value = decl.group("value").strip()
        if decl.group("kind").lower() == "state":
            states.append(value)
        else:
            refs = _FLAG_REF_RE.findall(value)
            if not refs:
                violations.append(
                    f"{name}: Gating-flag declaration names no `[section].key` flag: {value!r}"
                )
            flags.extend(refs)

    if not flags and not states:
        return [
            f"{name}: ceremony/go-live runbook has no machine-readable gating "
            "declaration (add `<!-- Gating-flag: [section].key -->` or "
            "`<!-- Gating-state: <label> -->`) - the checker cannot verify banner "
            "<-> flag agreement without it (deny-by-default)"
        ]

    has_banner = _EXECUTED_BANNER_RE.search(text) is not None

    # A Gating-state must name a KNOWN label; a bogus one is a typo or an attempt
    # to skip the config cross-check by relabelling a flag-gated ceremony.
    unknown = [s for s in states if s not in _VALID_GATING_STATES]
    if unknown:
        violations.append(
            f"{name}: unknown Gating-state {unknown!r} (known: {sorted(_VALID_GATING_STATES)}) - "
            "a new state label bypasses the config cross-check and must be a reviewed act"
        )

    # Resolve every declared flag against config (rot guard on the declarations).
    values = {f"[{s}].{k}": _flag_value(toml, s, k) for s, k in flags}
    missing = [f for f, v in values.items() if v is None]
    if missing:
        violations.append(
            f"{name}: declared gating flag(s) not found in default.toml: "
            + ", ".join(missing)
            + " - the declaration must point at a real key (rot guard)"
        )
        return violations  # cannot judge banner agreement against a missing key

    live = [f for f, v in values.items() if v]
    dormant = [f for f, v in values.items() if not v]

    # A banner is required when the ceremony has run: every gating flag live, OR a
    # Gating-state was declared (run-once external evidence). A still-false flag
    # means genuinely pending - no banner is owed, and a stale one is refused.
    banner_required = (bool(flags) and not dormant) or bool(states)
    if banner_required and not has_banner:
        what = ("gating flag(s) " + ", ".join(live) + " LIVE") if live else (
            "Gating-state " + ", ".join(states))
        violations.append(
            f"{name}: {what} in default.toml but the runbook carries no EXECUTED / "
            "ALREADY-PERFORMED banner - it reads as a pending instruction to re-run "
            "a ceremony that already happened (#990)"
        )
    if dormant and has_banner:
        violations.append(
            f"{name}: runbook carries an EXECUTED banner but gating flag(s) "
            f"{', '.join(dormant)} are still false in default.toml - the banner "
            "claims a ceremony complete that its own flag says is pending"
        )
    return violations


def ceremony_banner_violations(
    repo_root: Path, runbooks_dir: Path, toml_path: Path
) -> tuple[list[str], int]:
    """Banner<->flag check over every ceremony/go-live runbook. Returns (violations, n)."""
    if not runbooks_dir.is_dir():
        raise FileNotFoundError(f"runbooks dir is not a directory: {runbooks_dir}")
    if not toml_path.is_file():
        raise FileNotFoundError(f"default.toml not found: {toml_path}")
    with toml_path.open("rb") as fh:
        toml = tomllib.load(fh)

    violations: list[str] = []
    n_ceremony = 0
    for path in sorted(runbooks_dir.glob("*.md")):
        if not _CEREMONY_NAME_RE.search(path.name):
            continue
        n_ceremony += 1
        violations.extend(
            ceremony_banner_violations_in_doc(
                path.read_text(encoding="utf-8"), path.name, toml
            )
        )
    return violations, n_ceremony


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

def verify(repo_root: Path, scope_rel: str = "docs",
           include_inline: bool = False) -> tuple[int, list[str]]:
    """Run both checks. Returns (exit_code, report_lines).

    ``include_inline`` runs the non-gated inline-path audit as well (off by
    default; the gate never sets it - see ``dead_pointers_in_doc``).
    """
    out: list[str] = [f"Doc pointer + ceremony-banner verification: {repo_root}", ""]
    scope = repo_root / scope_rel
    runbooks = repo_root / "docs" / "runbooks"
    toml_path = repo_root / "services" / "assistant_orchestrator" / "config" / "default.toml"

    try:
        ptr_violations, n_files, n_links, n_tombstone = dead_pointer_violations(
            repo_root, scope, include_inline=include_inline
        )
        banner_violations, n_ceremony = ceremony_banner_violations(repo_root, runbooks, toml_path)
    except FileNotFoundError as exc:
        return 2, out + [f"  [FAIL] scan target missing: {exc}",
                         "", "RESULT: FAIL - a scanned surface has vanished (fail-loud, not vacuous)"]

    # Fail LOUD on a vacuous match rather than reporting a false clean.
    if n_files == 0:
        return 2, out + [f"  [FAIL] pointer scope {scope_rel!r} matched ZERO .md files",
                         "", "RESULT: FAIL - vacuous scan (#970 shape)"]
    if n_ceremony == 0:
        return 2, out + ["  [FAIL] ZERO ceremony/go-live runbooks matched - the glob is broken",
                         "", "RESULT: FAIL - vacuous scan (#970 shape)"]

    inline_note = " + inline paths" if include_inline else " (markdown links; inline paths not gated)"
    out.append(f"  Check 1 - dead pointers{inline_note}: scanned {n_files} .md file(s), "
               f"{n_links} markdown link(s) under {scope_rel}/ "
               f"(archive + handoffs + {n_tombstone} tombstone doc(s) excluded)")
    if ptr_violations:
        out.extend(f"    [DEAD] {v}" for v in ptr_violations)
    else:
        out.append("    [PASS] every relative pointer resolves")

    out.append(f"  Check 2 - ceremony banners: {n_ceremony} go-live/ceremony runbook(s)")
    if banner_violations:
        out.extend(f"    [BANNER] {v}" for v in banner_violations)
    else:
        out.append("    [PASS] every ceremony banner agrees with its gating flag")

    n_fail = len(ptr_violations) + len(banner_violations)
    out.append("")
    if n_fail:
        out.append(
            f"RESULT: FAIL - {len(ptr_violations)} dead pointer(s), "
            f"{len(banner_violations)} banner violation(s). A dead pointer or a stale "
            "ceremony banner is a document asserting a state the repo contradicts."
        )
        return 1, out
    out.append("RESULT: PASS - no dead pointers; every ceremony banner matches its flag")
    return 0, out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Verify BlarAI doc pointers resolve and ceremony banners match their flags."
    )
    ap.add_argument("--repo", default=".", help="repo root (default: cwd)")
    ap.add_argument("--scope", default="docs",
                    help="repo-relative dir for the pointer scan (default: docs)")
    ap.add_argument("--inline", action="store_true",
                    help="also run the non-gated inline-path audit (noisy; for targeted use)")
    args = ap.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    code, report = verify(repo_root, args.scope, include_inline=args.inline)
    print("\n".join(report))
    return code


if __name__ == "__main__":
    sys.exit(main())
