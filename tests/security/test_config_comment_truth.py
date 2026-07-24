"""Ceremony-flag comment truth lock (#1060, lesson 47 sub-class).

WHY THIS GATE EXISTS — the switch label that lied.
--------------------------------------------------
``services/assistant_orchestrator/config/default.toml`` is the artifact the
Lead Architect reads AT a go-live ceremony, and CLAUDE.md names it the
authority for what is LIVE vs DORMANT.  On 2026-07-22 (#1031 S1) the
``advanced_intake`` flag's comment promised four capabilities (a wider
elicitation interview, co-authored acceptance criteria, a 1:1 oracle import
contract, BLOCKING coverage enforcement) while the branch shipped two
deterministic rulers — lesson 47's FOURTH instance, on the most expensive
surface the class has reached: dormant-merge is safe only because the ceremony
is an *informed* decision, and a wrong comment there converts the pattern into
theatre.  The third-instance control (``test_dependency_truth.py``) covers
manifests, not ceremony-read config comments, so the instance escaped it by
construction.

WHAT THIS GATE ENFORCES — a self-describing declaration, resolved against code.
-------------------------------------------------------------------------------
Rather than parsing English prose for capability claims (a naive keyword scan
is a false-confidence surface in its own right — the rejected design), every
ceremony/go-live flag must carry, in the comment block bound to its assignment
line, a machine-checkable declaration:

    # capabilities(<section>.<key>):
    #   <name> = <runtime-path>.py[::<symbol>]

and this gate resolves every entry against the real codebase:

1. MEMBERSHIP — a flag is in the ceremony set when any trigger fires:
   (a) inline ``GO-LIVE`` marker on the assignment line (the repo's existing
       flip convention); (b) past-tense ceremony narration in the bound block
       (``WENT LIVE`` / ``LIVE since`` / ``FLIPPED TRUE`` / ``FLIPPED ON``,
       case-sensitive); (c) a go-live runbook reference
       (``docs/runbooks/*go_live*``) — this one arms the PRE-ceremony,
       staged-dormant shape (#1031's exact shape: the lie existed while the
       flag was still false); (d) the word "ceremony" anywhere in the bound
       block, case-insensitive — the tense/case/polarity-proof net that
       catches future-tense dormant flags AND flip-to-FALSE ceremonies
       (e.g. a graduation ceremony), which no flip-vocabulary can;
       (e) a declaration already present (opt-in).
2. PRESENCE — every member carries a well-formed declaration; a malformed
   declaration fails loudly, never skips.
3. BINDING — the declaration's qualified name must equal the ``section.key``
   of the assignment it structurally precedes, so a key inserted between the
   comment and its flag (or a moved block) fails instead of silently
   re-binding — the flag→comment binding, not just comment content.
4. TRUTH — every declared capability must resolve: the path exists, lives
   under the runtime roots (``shared/``, ``services/``, ``launcher/`` — a
   capability "existing" only in a test file is not a shipped capability),
   and the named symbol is defined in that file's AST (def / async def /
   class at any depth; module-level Assign / AnnAssign targets).  A renamed
   or deleted capability fails the standing gate naming the flag, the claim,
   and the missing symbol.
5. CONSUMPTION — the flag's key literal (or, for the generic key ``enabled``,
   its section literal) appears in runtime source: a beautifully-declared
   flag that no runtime code reads is a lie of a different shape.

Same precedent shape as the WinUI passthrough allowlist gate
(``tests/integration/test_winui_passthrough_allowlist.py``): parse a
declarative surface, cross-check it against code, fail by name.

HONEST LIMITS — what this control provably MISSES (measured, not asserted):
---------------------------------------------------------------------------
* English prose is NOT verified.  A lying sentence above a truthful
  declaration passes; the declaration is the machine-checked claim surface
  and prose stays reviewer territory.  This is the deliberate trade against
  the rejected prose-scan design, which would have claimed coverage it could
  not deliver.
* Symbol existence is not reachability.  The gate proves a claimed capability
  EXISTS in runtime code and that the flag is consumed; it does NOT prove the
  flag's boolean actually gates that symbol's execution path — per-flag
  behavior tests own that seam (e.g. ``test_advanced_intake_flag_reaches_
  generate_plan``).
* Direction is claims ⊆ code only.  A flag enabling MORE than its comment
  declares is not caught; the code-side registry that could catch it was
  rejected as a hand-maintained map (lesson 293) — the map is the artifact
  that rots.
* Membership is trigger-based.  A ceremony flag whose block carries no
  GO-LIVE marker, no flip narration, no runbook reference, no declaration,
  and never says "ceremony" escapes (the toggle-off tests below PROVE the
  escape rather than hiding it).  Measured on the real corpus 2026-07-22:
  the trigger set nets every ceremony-class flag in both configs and zero
  non-ceremony flags (the flip vocabulary stays case-sensitive so lowercase
  "go-live" prose asides alone do not trigger; the ceremony-word net is
  case-insensitive and every flag it nets IS a ceremony surface).
* SCOPE: the gate reads the config files pinned in ``_CONFIGS`` — the AO
  config and the launcher's guest-parser config (the UC-003 weld surface).
  A ceremony surface living in any OTHER file (a future third config, a
  runbook, an env-var posture knob per the #657 idiom) is not read; adding
  a config means adding it to ``_CONFIGS`` in the same change.
* The line scanner assumes single-line TOML values (true of both files); it
  is cross-validated against ``tomllib``'s parse so a phantom flag invented
  from a future multi-line value fails loudly instead of misbinding.
"""

from __future__ import annotations

import ast
import functools
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_AO_CONFIG = _REPO / "services/assistant_orchestrator/config/default.toml"

# Every ceremony-bearing config surface the gate reads. A new config file
# carrying ceremony flags is added HERE in the change that creates it.
_CONFIGS: dict[str, Path] = {
    "ao": _AO_CONFIG,
    "launcher": _REPO / "launcher/config/default.toml",
}

# The runtime source roots (the same surface test_dependency_truth.py scans).
_RUNTIME_ROOTS = ("shared", "services", "launcher")

# Past-tense ceremony-flip narration.  CASE-SENSITIVE on purpose: the file's
# prose uses lowercase "go-live" ~6 times in non-flip contexts ("go-live
# attestation", "Pre-go-live", "until an LA go-live ceremony adds it here")
# and every actual flip is narrated in the uppercase forms below.
_CEREMONY_VOCAB = ("GO-LIVE", "WENT LIVE", "LIVE since", "FLIPPED TRUE", "FLIPPED ON")

# A go-live runbook reference — the staged-dormant pre-ceremony trigger.
_RUNBOOK_RE = re.compile(r"docs/runbooks/\S*go_live\S*")

# The tense/case/polarity-proof net: any mention of a ceremony in the bound
# block makes the flag a member. Case-insensitive on purpose — this is the
# trigger that catches a future-tense dormant flag ("separate LA go-live
# ceremony") and a flip-to-FALSE ceremony ("the #855 graduation ceremony"),
# both of which the past-tense flip vocabulary can never match.
_CEREMONY_WORD_RE = re.compile(r"ceremony", re.IGNORECASE)

_SECTION_RE = re.compile(r"^\[([A-Za-z0-9_.\-]+)\]\s*(?:#.*)?$")
_ASSIGN_RE = re.compile(r"^([A-Za-z0-9_\-]+)\s*=")

_DECL_HEADER_RE = re.compile(r"^#\s*capabilities\(([A-Za-z0-9_.]+)\):\s*$")
_DECL_ENTRY_RE = re.compile(
    r"^#\s{2,}([a-z0-9][a-z0-9-]*)\s*=\s*"
    r"([A-Za-z0-9_\-./]+\.py)(?:::([A-Za-z_][A-Za-z0-9_]*))?\s*$"
)
# Loose net for malformed attempts: anything that LOOKS like a declaration
# must parse as one — a typo'd declaration must fail, never silently vanish.
_DECL_LOOSE_RE = re.compile(r"capabilit(?:y|ies)\s*\(")

# Key names too generic to grep for; consumption falls back to the section.
_GENERIC_KEYS = frozenset({"enabled"})

# Anti-vacuity floors: the ceremony flags known to exist today, per config.
# FLOORS (superset assertions), never full maps — new ceremony flags extend
# the member set without touching these lists.
_KNOWN_CEREMONY_FLAGS: dict[str, frozenset[str]] = {
    "ao": frozenset(
        {
            "web_search.enabled",
            "image_generation.enabled",
            "image_generation.require_signed_manifest",
            "knowledge.images_enabled",
            "fleet_dispatch.enabled",
            "fleet_dispatch.advanced_intake",
            "fleet_dispatch.vikunja_bridge",
            "fleet_dispatch.guest_oracle_enabled",
            "coordinator.enabled",
            "coordinator.heartbeat_enabled",
            "coordinator.shadow_mode",
            "coordinator.swap_doom_checks_enabled",
            "coordinator.require_signed_policy",
            "coordinator.enabled_auto_classes",
            "security.jwt_ca_cert_path",
            "security.require_signed_manifest",
            "security.require_signed_draft_manifest",
        }
    ),
    "launcher": frozenset(
        {
            "guest_parser.enabled",
            "guest_parser.mtls_cert",
        }
    ),
}


@dataclass(frozen=True)
class Violation:
    flag: str
    kind: str  # missing-declaration | malformed-declaration | binding-mismatch
    #          # | missing-file | not-runtime | missing-symbol | unconsumed-flag
    detail: str

    def __str__(self) -> str:  # pragma: no cover - formatting only
        return f"[{self.kind}] {self.flag}: {self.detail}"


@dataclass
class _FlagRecord:
    section: str
    key: str
    line_no: int
    inline_comment: str
    block: list[str]  # full-line comments bound to (immediately above) the flag

    @property
    def qualified(self) -> str:
        return f"{self.section}.{self.key}"


def _split_inline_comment(line: str) -> tuple[str, str]:
    """Split a TOML line into (code, comment) at the first ``#`` outside quotes."""
    in_str: str | None = None
    for i, ch in enumerate(line):
        if in_str:
            if ch == in_str:
                in_str = None
        elif ch in ("'", '"'):
            in_str = ch
        elif ch == "#":
            return line[:i], line[i:]
    return line, ""


def _parse_flags(config_text: str) -> list[_FlagRecord]:
    """Line-scan the config into flag records with their BOUND comment blocks.

    Binding rule: a flag's block is the contiguous run of full-line comment
    lines immediately above its assignment; a blank line, a section header,
    or another assignment terminates it.  This is the structural half of the
    flag→comment binding — the declarative half (the qualified name inside
    the declaration) is checked in check_config_comment_truth().
    """
    flags: list[_FlagRecord] = []
    section = ""
    pending_comments: list[str] = []
    for line_no, raw in enumerate(config_text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped:
            pending_comments = []
            continue
        if stripped.startswith("#"):
            pending_comments.append(stripped)
            continue
        m = _SECTION_RE.match(stripped)
        if m:
            section = m.group(1)
            pending_comments = []
            continue
        m = _ASSIGN_RE.match(stripped)
        if m:
            _, comment = _split_inline_comment(raw)
            flags.append(
                _FlagRecord(
                    section=section,
                    key=m.group(1),
                    line_no=line_no,
                    inline_comment=comment,
                    block=pending_comments,
                )
            )
        # A non-comment, non-blank line of any shape ends the pending block.
        pending_comments = []
    return flags


def _cross_validate_against_tomllib(config_text: str, flags: list[_FlagRecord]) -> None:
    """Guard the parser: every line-scanned flag must exist in the real TOML
    parse.  A phantom flag (e.g. invented from a future multi-line value's
    interior) fails here loudly instead of mis-binding a comment block."""
    doc = tomllib.loads(config_text)
    for f in flags:
        node = doc
        for part in (*f.section.split("."), f.key) if f.section else (f.key,):
            assert isinstance(node, dict) and part in node, (
                f"line-scan found '{f.qualified}' (line {f.line_no}) which the "
                "tomllib parse does not contain — the scanner mis-parsed the "
                "file (multi-line value?). Fix _parse_flags before trusting "
                "any result from this gate."
            )
            node = node[part]


def _membership_triggers(flag: _FlagRecord) -> list[str]:
    triggers: list[str] = []
    if "GO-LIVE" in flag.inline_comment:
        triggers.append("inline GO-LIVE marker")
    text = "\n".join(flag.block) + "\n" + flag.inline_comment
    for vocab in _CEREMONY_VOCAB:
        if vocab in text:
            triggers.append(f'ceremony narration "{vocab}"')
            break
    if _RUNBOOK_RE.search(text):
        triggers.append("go-live runbook reference")
    if _CEREMONY_WORD_RE.search(text):
        triggers.append('the word "ceremony" in the bound comment')
    return triggers


def _parse_declaration(
    flag: _FlagRecord,
) -> tuple[str | None, list[tuple[str, str, str | None]], list[str]]:
    """Return (declared_qualified_name, entries, format_errors).

    entries: (capability-name, path, symbol-or-None).  A block that LOOKS
    like it attempts a declaration but does not parse yields format_errors —
    malformed never silently vanishes.
    """
    declared_qual: str | None = None
    entries: list[tuple[str, str, str | None]] = []
    errors: list[str] = []
    in_decl = False
    for line in flag.block:
        header = _DECL_HEADER_RE.match(line)
        if header:
            if declared_qual is not None:
                errors.append("duplicate capabilities(...) header in one block")
            declared_qual = header.group(1)
            in_decl = True
            continue
        entry = _DECL_ENTRY_RE.match(line)
        if entry:
            if in_decl:
                entries.append((entry.group(1), entry.group(2), entry.group(3)))
            else:
                # FAIL-LOUD, never skip: an entry-shaped line that is not part
                # of the contiguous run under a header (above the header, or
                # separated from it by a prose line) would otherwise be a
                # claim the gate silently never checks — the fail-open an
                # independent review caught in this parser's first version.
                errors.append(
                    "entry-shaped line outside a capabilities(...) declaration "
                    "(above the header, or separated from it by prose) — it "
                    f"would go unchecked: {line!r}"
                )
            continue
        in_decl = False  # a prose line ends the contiguous entry run
        if _DECL_LOOSE_RE.search(line):
            errors.append(
                f"line looks like a capability declaration but does not parse: {line!r}"
            )
    if declared_qual is not None and not entries and not errors:
        errors.append("capabilities(...) header with zero entries")
    return declared_qual, entries, errors


@functools.cache
def _defined_names(path: Path) -> set[str]:
    """Names defined in a Python file: def/async def/class at ANY depth,
    plus module-level Assign/AnnAssign targets (AnnAssign included — the
    annotated-assignment blind spot is a known miss shape in this repo)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


@functools.cache
def _runtime_source_blob(repo: Path) -> str:
    """Concatenated non-test runtime source, for the consumption check.
    Same path convention as test_dependency_truth.py."""
    chunks: list[str] = []
    for root in _RUNTIME_ROOTS:
        for f in (repo / root).rglob("*.py"):
            parts = set(f.parts)
            if parts & {"tests", "test", "__pycache__"}:
                continue
            if f.name.startswith("test_") or f.name == "conftest.py":
                continue
            chunks.append(f.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(chunks)


def _is_runtime_path(rel_path: str) -> bool:
    parts = rel_path.split("/")
    if parts[0] not in _RUNTIME_ROOTS:
        return False
    if {"tests", "test"} & set(parts):
        return False
    name = parts[-1]
    return not (name.startswith("test_") or name == "conftest.py")


def check_config_comment_truth(
    config_text: str, *, repo: Path = _REPO, runtime_blob: str | None = None
) -> tuple[list[Violation], set[str]]:
    """The checker: returns (violations, member-flag qualified names).

    Pure over ``config_text`` so planted-violation tests can drive it over a
    MUTATED copy of the real file; capability resolution always runs against
    the real repository on disk.
    """
    flags = _parse_flags(config_text)
    _cross_validate_against_tomllib(config_text, flags)
    blob = runtime_blob if runtime_blob is not None else _runtime_source_blob(repo)

    violations: list[Violation] = []
    members: set[str] = set()
    for flag in flags:
        triggers = _membership_triggers(flag)
        declared_qual, entries, errors = _parse_declaration(flag)
        if not triggers and declared_qual is None and not errors:
            continue  # an ordinary flag — the control does not fire
        members.add(flag.qualified)

        for err in errors:
            violations.append(Violation(flag.qualified, "malformed-declaration", err))
        if declared_qual is None:
            if not errors:
                violations.append(
                    Violation(
                        flag.qualified,
                        "missing-declaration",
                        f"ceremony flag (trigger: {'; '.join(triggers)}) has no "
                        "capabilities(...) declaration in its bound comment "
                        "block. Add, directly above the assignment:\n"
                        f"    # capabilities({flag.qualified}):\n"
                        "    #   <name> = <runtime-path>.py::<symbol>",
                    )
                )
            continue
        if declared_qual != flag.qualified:
            violations.append(
                Violation(
                    flag.qualified,
                    "binding-mismatch",
                    f"declaration is for '{declared_qual}' but binds to "
                    f"'{flag.qualified}' (line {flag.line_no}) — the comment "
                    "block and the flag have drifted apart.",
                )
            )
            continue

        for cap_name, rel_path, symbol in entries:
            if not _is_runtime_path(rel_path):
                violations.append(
                    Violation(
                        flag.qualified,
                        "not-runtime",
                        f"capability '{cap_name}' points at {rel_path}, which "
                        f"is not runtime code ({'/'.join(_RUNTIME_ROOTS)}, "
                        "non-test) — a capability living in a test or tool "
                        "file is not a shipped capability.",
                    )
                )
                continue
            target = repo / rel_path
            if not target.is_file():
                violations.append(
                    Violation(
                        flag.qualified,
                        "missing-file",
                        f"capability '{cap_name}' claims {rel_path}, which "
                        "does not exist — the comment promises code the "
                        "codebase does not contain.",
                    )
                )
                continue
            if symbol is not None and symbol not in _defined_names(target):
                violations.append(
                    Violation(
                        flag.qualified,
                        "missing-symbol",
                        f"capability '{cap_name}' claims {rel_path}::{symbol}, "
                        "and no such def/class/module-level assignment exists "
                        "in that file — the comment promises a capability the "
                        "code does not contain (lesson 47). Either the claim "
                        "is wrong or the capability was renamed/removed; make "
                        "the declaration true in the same change.",
                    )
                )

        needle = flag.key if flag.key not in _GENERIC_KEYS else flag.section
        if needle not in blob:
            violations.append(
                Violation(
                    flag.qualified,
                    "unconsumed-flag",
                    f"neither runtime root contains the literal '{needle}' — "
                    "a ceremony flag no runtime code reads is a dead switch "
                    "wearing a live label.",
                )
            )
    return violations, members


# ────────────────────────────────────────────────────────────────────────────
# The gate proper — driven over the REAL config files.
# ────────────────────────────────────────────────────────────────────────────


def _real_config_text(config: str = "ao") -> str:
    return _CONFIGS[config].read_text(encoding="utf-8")


@pytest.mark.parametrize("config", sorted(_CONFIGS))
def test_real_ceremony_flags_claim_nothing_the_code_lacks(config: str) -> None:
    """The lock: every ceremony flag's declaration resolves against the code.

    This is lesson 47's sub-class control (#1060): the comment the LA reads
    at a go-live ceremony must not claim capabilities the code does not
    contain."""
    violations, members = check_config_comment_truth(_real_config_text(config))
    assert not violations, (
        f"{_CONFIGS[config]} ceremony-flag comment truth violations (#1060, "
        "lesson 47): the go-live comment surface claims things the code does "
        "not back —\n  " + "\n  ".join(str(v) for v in violations)
    )
    assert members >= _KNOWN_CEREMONY_FLAGS[config], (
        "membership scan lost known ceremony flags (parser drift?): missing "
        f"{sorted(_KNOWN_CEREMONY_FLAGS[config] - members)}"
    )


def test_membership_and_extraction_are_not_vacuous() -> None:
    """Guard the guard (the WinUI gate's known-commands shape): the parser
    really reads the file and the AST walk really sees private symbols."""
    text = _real_config_text()
    flags = _parse_flags(text)
    assert len(flags) > 40, f"only {len(flags)} assignments parsed — scanner broken?"
    _, members = check_config_comment_truth(text)
    assert "fleet_dispatch.advanced_intake" in members
    # The declared realism-guard symbol is underscore-private and function-
    # scoped work exists near it; resolving it proves the AST surface is real.
    names = _defined_names(_REPO / "shared/fleet/acceptance.py")
    assert "_apply_realism_guard" in names and "_ensure_delivery_floor" in names
    # And the launcher surface really parses too (F3): the weld flag is seen.
    _, launcher_members = check_config_comment_truth(_real_config_text("launcher"))
    assert "guest_parser.enabled" in launcher_members


_PLANT_TEMPLATE = """
[synthetic_probe]
# Planted by test_config_comment_truth.py — never ships.
{extra_comment}# capabilities(synthetic_probe.{key}):
#   {cap_line}
{key} = true{inline}
"""


def _plant(
    *,
    key: str = "enabled",
    cap_line: str,
    inline: str = "   # GO-LIVE 2026-01-01 (#0): planted",
    extra_comment: str = "",
) -> str:
    return _real_config_text() + _PLANT_TEMPLATE.format(
        key=key, cap_line=cap_line, inline=inline, extra_comment=extra_comment
    )


def _violations_for(text: str, flag: str) -> list[Violation]:
    violations, _ = check_config_comment_truth(text)
    return [v for v in violations if v.flag == flag]


def test_planted_phantom_symbol_fails_by_name() -> None:
    """PLANTED VIOLATION over the real file: a go-live flag claiming a symbol
    the codebase does not contain must fail, naming flag + claim + symbol."""
    text = _plant(
        cap_line="phantom = shared/fleet/acceptance.py::_capability_that_does_not_exist"
    )
    hits = _violations_for(text, "synthetic_probe.enabled")
    assert any(
        v.kind == "missing-symbol" and "_capability_that_does_not_exist" in v.detail
        for v in hits
    ), f"phantom capability sailed through: {hits}"


def test_planted_phantom_file_fails_by_name() -> None:
    text = _plant(cap_line="phantom = shared/fleet/no_such_module.py::whatever")
    hits = _violations_for(text, "synthetic_probe.enabled")
    assert any(v.kind == "missing-file" for v in hits), hits


def test_planted_test_file_claim_fails() -> None:
    """A capability 'existing' in a test file is not a shipped capability."""
    text = _plant(
        cap_line="phantom = shared/tests/test_advanced_intake.py::test_advanced_intake_off_is_byte_identical"
    )
    hits = _violations_for(text, "synthetic_probe.enabled")
    assert any(v.kind == "not-runtime" for v in hits), hits


def test_planted_true_claim_passes_as_an_equal_partner() -> None:
    """The honest form passes with the same weight as the defect failing
    (lesson 293 both-directions): a planted flag claiming a REAL capability
    raises no truth violation — only the unconsumed-flag finding, because
    'synthetic_probe' is (correctly) read by no runtime code.  This pins
    that the failures above come from the CLAIMS being false, not from the
    plant merely existing."""
    text = _plant(cap_line="realism-guard = shared/fleet/acceptance.py::_apply_realism_guard")
    hits = _violations_for(text, "synthetic_probe.enabled")
    kinds = {v.kind for v in hits}
    assert "missing-symbol" not in kinds and "missing-file" not in kinds, hits
    assert kinds == {"unconsumed-flag"}, hits


def test_planted_ceremony_flag_without_declaration_fails() -> None:
    """A GO-LIVE flag with no declaration at all is itself a violation — the
    convention is deny-by-default for the ceremony set."""
    text = _real_config_text() + (
        "\n[synthetic_probe]\n"
        "# Planted — a ceremony flag with prose only, no declaration.\n"
        "enabled = true   # GO-LIVE 2026-01-01 (#0): planted\n"
    )
    hits = _violations_for(text, "synthetic_probe.enabled")
    assert any(v.kind == "missing-declaration" for v in hits), hits


def test_planted_runbook_reference_arms_the_pre_ceremony_shape() -> None:
    """The #1031 shape: a STAGED-DORMANT flag (false, no GO-LIVE marker yet)
    whose block cites its go-live runbook is already in the ceremony set —
    the comment must be true BEFORE the ceremony reads it."""
    text = _real_config_text() + (
        "\n[synthetic_probe]\n"
        "# Staged dormant; procedure: docs/runbooks/synthetic_probe_go_live.md\n"
        "enabled = false\n"
    )
    hits = _violations_for(text, "synthetic_probe.enabled")
    assert any(v.kind == "missing-declaration" for v in hits), hits


def test_planted_binding_mismatch_fails() -> None:
    """The drift-one-commit-later defect: a declaration that no longer names
    the flag it structurally binds to (block re-bound by an inserted key,
    or a copy-pasted declaration) fails instead of silently re-binding."""
    text = _real_config_text() + (
        "\n[synthetic_probe]\n"
        "# capabilities(synthetic_probe.enabled):\n"
        "#   realism-guard = shared/fleet/acceptance.py::_apply_realism_guard\n"
        "other_key = true   # GO-LIVE 2026-01-01 (#0): planted\n"
    )
    hits = _violations_for(text, "synthetic_probe.other_key")
    assert any(v.kind == "binding-mismatch" for v in hits), hits


def test_planted_malformed_declaration_fails_loud() -> None:
    """A typo'd declaration must FAIL, never silently vanish (fail-loud —
    a truth control that degrades silently is worse than none)."""
    text = _plant(
        extra_comment="# capabilities(synthetic_probe.enabled:  <- missing paren\n",
        cap_line="ok = shared/fleet/acceptance.py::_apply_realism_guard",
    )
    hits = _violations_for(text, "synthetic_probe.enabled")
    assert any(v.kind == "malformed-declaration" for v in hits), hits


def test_toggle_off_an_unmarked_flag_is_out_of_scope() -> None:
    """TOGGLE-OFF proof, and the honest limit stated as a test: the SAME
    planted lie with every membership trigger removed raises nothing — the
    control's reach is exactly its triggers, so a ceremony flag stripped of
    its marker/narration/runbook/declaration escapes.  This distinguishes
    'the gate blocks' from 'the gate can't reach the surface': the failure
    in test_planted_phantom_symbol_fails_by_name comes from the trigger,
    and removing the trigger provably disarms it."""
    lying_but_unmarked = _real_config_text() + (
        "\n[synthetic_probe]\n"
        "# An ordinary flag; prose may claim anything and nothing fires.\n"
        "enabled = true\n"
    )
    hits = _violations_for(lying_but_unmarked, "synthetic_probe.enabled")
    assert hits == [], f"control fired without any membership trigger: {hits}"

    # And the exact phantom plant, disarmed by dropping its GO-LIVE marker
    # AND its declaration — same lie, no trigger, no detection.
    disarmed = _real_config_text() + (
        "\n[synthetic_probe]\n"
        "# This flag totally enables the phantom capability, honest.\n"
        "enabled = true\n"
    )
    assert _violations_for(disarmed, "synthetic_probe.enabled") == []


def test_planted_lying_entry_after_a_prose_line_fails_loud() -> None:
    """Regression for the reviewed fail-open (F1): a prose line inside the
    entry list must NOT silently disarm the checker for the entry-shaped
    lines below it — the exact reviewer repro: header, one good entry, a
    prose line, then a LYING entry.  The first version of this parser passed
    this green."""
    text = _real_config_text() + (
        "\n[synthetic_probe]\n"
        "# capabilities(synthetic_probe.enabled):\n"
        "#   realism-guard = shared/fleet/acceptance.py::_apply_realism_guard\n"
        "# (a stray prose line interrupting the entry list)\n"
        "#   phantom = shared/fleet/acceptance.py::_capability_that_does_not_exist\n"
        "enabled = true   # GO-LIVE 2026-01-01 (#0): planted\n"
    )
    hits = _violations_for(text, "synthetic_probe.enabled")
    assert any(
        v.kind == "malformed-declaration"
        and "_capability_that_does_not_exist" in v.detail
        for v in hits
    ), f"lying entry after a prose line went unchecked (fail-open): {hits}"


def test_planted_entry_above_the_header_fails_loud() -> None:
    """Sibling shape of the same fail-open: an entry-shaped line ABOVE the
    capabilities(...) header is a claim outside the checked run — it must
    fail by name, never vanish."""
    text = _real_config_text() + (
        "\n[synthetic_probe]\n"
        "#   phantom = shared/fleet/acceptance.py::_capability_that_does_not_exist\n"
        "# capabilities(synthetic_probe.enabled):\n"
        "#   realism-guard = shared/fleet/acceptance.py::_apply_realism_guard\n"
        "enabled = true   # GO-LIVE 2026-01-01 (#0): planted\n"
    )
    hits = _violations_for(text, "synthetic_probe.enabled")
    assert any(
        v.kind == "malformed-declaration"
        and "_capability_that_does_not_exist" in v.detail
        for v in hits
    ), f"entry above the header went unchecked (fail-open): {hits}"


def test_planted_ceremony_word_arms_membership_regardless_of_tense_or_polarity() -> None:
    """The F2 escape shapes: a future-tense dormant ceremony flag and a
    flip-to-FALSE ceremony flag carry no past-tense flip vocabulary and no
    GO-LIVE marker — the case-insensitive ceremony-word net must make each a
    member, so a missing declaration fails."""
    future_tense = _real_config_text() + (
        "\n[synthetic_probe]\n"
        "# Dormant until this is flipped (separate LA go-live ceremony).\n"
        "enabled = false\n"
    )
    hits = _violations_for(future_tense, "synthetic_probe.enabled")
    assert any(v.kind == "missing-declaration" for v in hits), hits

    flip_to_false = _real_config_text() + (
        "\n[synthetic_probe]\n"
        "# Flipped to false ONLY at the #0 graduation ceremony.\n"
        "enabled = true\n"
    )
    hits = _violations_for(flip_to_false, "synthetic_probe.enabled")
    assert any(v.kind == "missing-declaration" for v in hits), hits


def test_planted_unconsumed_flag_fails() -> None:
    """CONSUMPTION teeth: a flag with a fully TRUE declaration still fails
    when no runtime code reads it — proven by pointing the consumption
    needle at a section name the runtime cannot contain."""
    text = _plant(
        key="zz_key_no_runtime_reads_zz",
        cap_line=(
            "realism-guard = shared/fleet/acceptance.py::_apply_realism_guard"
        ),
    )
    hits = _violations_for(text, "synthetic_probe.zz_key_no_runtime_reads_zz")
    assert any(v.kind == "unconsumed-flag" for v in hits), hits
