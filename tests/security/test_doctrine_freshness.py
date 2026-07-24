"""Doctrine-freshness gate (#945 D8, LA-approved 2026-07-19).

The 2026-07-18 documentation audit found every frozen doctrine surface shared one root
cause: its stated maintainer was a retired role, so nothing ever updated it — while a
documented sync rule (TEST_GOVERNANCE "copilot baseline MUST stay in sync") sat
unenforced for six weeks and three surfaces pinned three different gate counts
(8518 / 8490 / 2212). These tests are the structural control: the always-loaded
doctrine surfaces must agree with each other, stay fresh relative to repository
activity, respect their size budgets, and never re-admit retired-world vocabulary.

Scope: doctrine FILES only — no live system contact, no network, no model.

#978 (2026-07-19) extends the gate with SECURITY-DOC INTEGRITY probes. A nine-instance
audit found documentation asserting a security posture the code contradicts, with ONE
root cause: accurate modules state timeless design claims ("with an empty allowlist,
every URL is denied"); every defective one states a TIME-ANCHORED CURRENT-WIRING claim
("empty this sprint", "no live consumer today", "stays welded") — and go-live
ceremonies flip config and runbooks while nobody reopens the docstrings that narrated
the pre-ceremony world. Three probes:

  1. Time-anchored-prose lint over the security/coordinator/PA prose surfaces.
     HONEST SCOPE: it catches the PHRASING CLASS at introduction, not truth — but the
     phrasing class IS the defect, because a docstring may state defaults and
     contracts and must never narrate current wiring.
  2. Posture pins (the LIVE_GATE_BASELINE pattern generalised to doc<->code): CLAUDE.md
     prose lock-claims resolve against the real code symbol and the real config. The
     code<->code leg already exists (test_egress_screen.py pins the allowlist exactly);
     this is the missing doc<->code leg.
  3. default.toml dormancy-comment lint: a DORMANT-vocabulary comment block over a key
     whose live value is `true` fails unless the value line carries a dated go-live
     annotation.

PROBE 4 DOES NOT EXIST, deliberately. Composite-semantics claims — "both layers read
the SAME allowlist" (D9/#977), and any "N independent locks" counting claim — are NOT
mechanically catchable by a lint: they depend on registration order and lock
independence. Only an executable boot-time posture check (#977) or human review covers
that class. A lint that claimed to cover it would itself be the control-that-claims-
coverage-it-lacks — the exact defect class this gate exists to stop.
"""
from __future__ import annotations

import datetime as _dt
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
TEST_GOVERNANCE = REPO_ROOT / "docs" / "TEST_GOVERNANCE.md"
COPILOT = REPO_ROOT / ".github" / "copilot-instructions.md"
ACTIVE_SPRINT = REPO_ROOT / "docs" / "sprints" / "ACTIVE_SPRINT.md"
LESSONS = REPO_ROOT / "LESSONS.md"
COMMANDS = sorted((REPO_ROOT / ".claude" / "commands").glob("sprint-*.md"))

SNAPSHOT_RE = re.compile(r"Standing gate:\s*([\d,]+)\s*/")
LIVE_LINE_RE = re.compile(r"LIVE_GATE_BASELINE:\s*([\d,]+)\s+passed")
REFRESH_RE = re.compile(r"\*\*Last refresh \((\d{4}-\d{2}-\d{2})\)\*\*")
PINNED_COUNT_RE = re.compile(r"\b\d{3,}\s+(?:passed|tests)\b")

# Retired-world vocabulary that must never re-enter an ALWAYS-LOADED surface.
# Archives, the journal, and history files are exempt by construction (not scanned).
RETIRED_TOKENS = (
    "SWAGR",
    "Strategic Design Vision",
    "Co-Lead",
    "DEC-15",
    "ea_queue",
    "EA Code",
)
RETIRED_WORD_RE = re.compile(r"\bSDO\b")
# (file-name, token) pairs deliberately tolerated; additions are a reviewed act.
LEXICON_ALLOWLIST: frozenset[tuple[str, str]] = frozenset()

# Hot-file size budgets in bytes (#945 D8). Breach = consolidate, never wave through.
SIZE_BUDGETS = {
    CLAUDE_MD: 48_000,
    TEST_GOVERNANCE: 40_000,
    ACTIVE_SPRINT: 4_000,
    COPILOT: 14_000,
    LESSONS: 125_000,
}


def _read(path: Path) -> str:
    assert path.exists(), f"always-loaded doctrine surface missing: {path}"
    return path.read_text(encoding="utf-8")


def test_gate_count_surfaces_agree() -> None:
    """CLAUDE.md's snapshot figure and TEST_GOVERNANCE §1's live line are one number."""
    snap = SNAPSHOT_RE.search(_read(CLAUDE_MD))
    live = LIVE_LINE_RE.search(_read(TEST_GOVERNANCE))
    assert snap, "CLAUDE.md <status_snapshot> lost its parseable 'Standing gate: N /' line"
    assert live, "TEST_GOVERNANCE §1 lost its parseable 'LIVE_GATE_BASELINE: N passed' line"
    snap_n = int(snap.group(1).replace(",", ""))
    live_n = int(live.group(1).replace(",", ""))
    assert snap_n == live_n, (
        f"gate-count drift: CLAUDE.md says {snap_n}, TEST_GOVERNANCE §1 says {live_n} — "
        "update BOTH in the same commit that changes test counts"
    )


def test_copilot_instructions_pin_no_count() -> None:
    """The non-Claude mirror POINTS at the live surfaces; it never pins a figure."""
    text = _read(COPILOT)
    pinned = PINNED_COUNT_RE.search(text)
    assert pinned is None, (
        f"copilot-instructions pins a test count ({pinned.group(0)!r}); it must point at "
        "TEST_GOVERNANCE §1 / CLAUDE.md <status_snapshot> instead — the last pinned "
        "figure there went 6,306 tests stale before anyone noticed"
    )
    assert "TEST_GOVERNANCE" in text, (
        "copilot-instructions must direct agents to docs/TEST_GOVERNANCE.md for the baseline"
    )


def test_active_sprint_pointer_tracks_repo_activity() -> None:
    """A force-read pointer whose refresh date trails main by >14 days is misinformation."""
    m = REFRESH_RE.search(_read(ACTIVE_SPRINT))
    assert m, "ACTIVE_SPRINT.md lost its '**Last refresh (YYYY-MM-DD)**' line"
    refreshed = _dt.date.fromisoformat(m.group(1))
    out = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "log", "-1", "--format=%ct"],
        capture_output=True, text=True, timeout=30, check=False,
    )
    if out.returncode != 0 or not out.stdout.strip():
        pytest.skip("git history unavailable in this environment")
    last_commit = _dt.datetime.fromtimestamp(int(out.stdout.strip()), _dt.timezone.utc).date()
    lag = (last_commit - refreshed).days
    assert lag <= 14, (
        f"ACTIVE_SPRINT.md refresh date {refreshed} trails the latest commit "
        f"{last_commit} by {lag} days (>14): the mandated session-start read has gone "
        "stale — refresh the pointer (its previous body froze for six weeks and fed "
        "every session a two-sprints-old world)"
    )


def test_hot_doctrine_files_respect_size_budgets() -> None:
    """Bloat regrows unless bounded: each always-loaded surface has a byte budget."""
    over = []
    for path, budget in SIZE_BUDGETS.items():
        size = path.stat().st_size if path.exists() else 0
        assert path.exists(), f"budgeted doctrine surface missing: {path}"
        if size > budget:
            over.append(f"{path.name}: {size:,} > {budget:,} bytes")
    assert not over, (
        "hot doctrine file(s) over budget — consolidate/rotate, never wave through: "
        + "; ".join(over)
    )


def test_no_retired_lexicon_in_always_loaded_surfaces() -> None:
    """Retired-world vocabulary must not re-enter the surfaces every session loads."""
    surfaces = [CLAUDE_MD, COPILOT, ACTIVE_SPRINT, *COMMANDS]
    hits: list[str] = []
    for path in surfaces:
        text = _read(path)
        for token in RETIRED_TOKENS:
            if token in text and (path.name, token) not in LEXICON_ALLOWLIST:
                hits.append(f"{path.name}: {token!r}")
        if RETIRED_WORD_RE.search(text) and (path.name, "SDO") not in LEXICON_ALLOWLIST:
            hits.append(f"{path.name}: 'SDO'")
    assert not hits, (
        "retired-world vocabulary re-entered always-loaded doctrine (add to the "
        "documented allowlist only as a deliberate reviewed act): " + "; ".join(hits)
    )


def test_rotate_log_tool_is_byte_preserving(tmp_path: Path) -> None:
    """The monthly rotation instrument must move entries verbatim and lose nothing."""
    src = tmp_path / "LOG.md"
    body = (
        "# Log\n\npreamble text\n\n"
        "### 2026-05-02 — first\n\n*Plain summary: one.*\n\nalpha\n\n"
        "### 2026-06-03 — second\n\nbeta gamma\n\n"
        "### 2026-07-04 — third\n\n*Plain summary: three.*\n\ndelta\n"
    )
    src.write_text(body, encoding="utf-8", newline="")
    tool = REPO_ROOT / "tools" / "doc_hygiene" / "rotate_log.py"
    out = subprocess.run(
        [sys.executable, str(tool), "--source", str(src),
         "--archive-dir", str(tmp_path / "arch"), "--index", str(tmp_path / "arch" / "INDEX.md"),
         "--keep-month", "2026-07"],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert out.returncode == 0, f"rotate_log failed: {out.stdout}\n{out.stderr}"
    hot = src.read_text(encoding="utf-8")
    may = (tmp_path / "arch" / "2026-05.md").read_text(encoding="utf-8")
    jun = (tmp_path / "arch" / "2026-06.md").read_text(encoding="utf-8")
    idx = (tmp_path / "arch" / "INDEX.md").read_text(encoding="utf-8")
    assert "### 2026-07-04 — third" in hot and "### 2026-05-02" not in hot
    assert "### 2026-05-02 — first" in may and "alpha" in may
    assert "### 2026-06-03 — second" in jun and "beta gamma" in jun
    assert "2026-05-02 | first | one. | 2026-05.md" in idx
    # byte preservation: every source byte is in exactly one of hot/volumes
    moved = may.split("*\n\n", 1)[-1]  # strip volume header
    assert "preamble text" in hot
    for chunk in ("alpha", "beta gamma", "delta", "*Plain summary: one.*"):
        assert chunk in hot + may + jun, f"lost content: {chunk}"


# --- Comprehension-gate section-list sync (#1022) ---------------------------
#
# The gate spec eroded twice by abbreviation: a from-memory doctrine rewrite
# dropped dimensions the authoritative (since-sunset) source required, then a
# tightening pass compressed a mirror to a shorthand — and the shorthand is the
# erosion vector, because it becomes the version the next rewrite copies from.
# No count or vocabulary probe can see a dropped section, so the section names
# themselves are pinned: every surface that states the gate list must name all
# of them. Case-insensitive — the mirrors legitimately differ in casing.
GATE_SECTIONS = (
    "ROLE & AUTHORITY",
    "CONTEXT",
    "GOAL",
    "TASK + PLAN",
    "SCOPE",
    "INHERITED CONSTRAINTS",
    "RISKS + DECISION POINTS",
    "ASSUMPTIONS & AMBIGUITIES",
    "OPEN QUESTIONS",
)
GATE_SURFACES = (
    CLAUDE_MD,
    REPO_ROOT / ".claude" / "commands" / "sprint-kickoff.md",
    REPO_ROOT / "docs" / "governance" / "handoff-brief-template.md",
    REPO_ROOT / "docs" / "runbooks" / "LA_SPRINT_KICKOFF_HOWTO.md",
)


def _gate_sections_missing(text: str) -> list[str]:
    upper = text.upper()
    return [section for section in GATE_SECTIONS if section not in upper]


def test_gate_section_list_complete_on_every_surface() -> None:
    """Each gate-stating surface names every comprehension-gate section."""
    missing: list[str] = []
    for path in GATE_SURFACES:
        missing.extend(f"{path.name}: {s}" for s in _gate_sections_missing(_read(path)))
    assert not missing, (
        "comprehension-gate section list eroded (#1022) — a surface abbreviated or "
        "dropped a section; restore the full list (or update GATE_SECTIONS in the "
        "same reviewed commit that deliberately changes the gate spec):\n  "
        + "\n  ".join(missing)
    )


def test_gate_section_pin_catches_dropped_section() -> None:
    """Toggle-off proof: a list missing one section is refused."""
    thinned = " / ".join(s for s in GATE_SECTIONS if s != "INHERITED CONSTRAINTS")
    assert _gate_sections_missing(thinned) == ["INHERITED CONSTRAINTS"]
    assert _gate_sections_missing(" ".join(GATE_SECTIONS).lower()) == []


# ---------------------------------------------------------------------------
# #978 — security-doc integrity probes (see module docstring for scope and for
# the deliberately-absent probe 4).
# ---------------------------------------------------------------------------

import ast as _ast
import io as _io
import tokenize as _tokenize
import tomllib as _tomllib

DEFAULT_TOML = (
    REPO_ROOT / "services" / "assistant_orchestrator" / "config" / "default.toml"
)
GPU_INFERENCE = REPO_ROOT / "services" / "policy_agent" / "src" / "gpu_inference.py"

# The prose surfaces the #978 audit covered: every trust-spine module whose
# docstrings/comments a session grounds on before touching egress or the
# coordinator. Test files are excluded — a test may legitimately narrate the
# scenario it constructs.
SECURITY_PROSE_DIRS = (
    REPO_ROOT / "shared" / "security",
    REPO_ROOT / "shared" / "coordinator",
    REPO_ROOT / "services" / "policy_agent" / "src",
)

# --- Probe 1: the time-anchored-prose lint -------------------------------
#
# HARD phrases fail wherever they appear in a comment/docstring line: each is a
# current-wiring narration with no evergreen reading.
_HARD_PROSE_PHRASES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("this sprint", re.compile(r"\bthis sprint\b", re.IGNORECASE)),
    ("no live consumer", re.compile(r"\bno live consumer\b", re.IGNORECASE)),
    ("never fires in production", re.compile(r"\bnever fires in production\b", re.IGNORECASE)),
    ("stays welded", re.compile(r"\bstays? welded\b", re.IGNORECASE)),
    ("STAGED/DORMANT status marker", re.compile(r"STAGED\s*/?\s*DORMANT")),
    ("dormancy status header", re.compile(r"\bDORMAN(?:T|CY)\b\s*(?:\([^)\n]{0,40}\))?\s*:")),
    (
        "time-anchored no-behavior-change claim",
        re.compile(r"changes\s+no[^.\n]{0,45}behaviou?r\b[^.\n]{0,30}\b(?:today|this sprint)\b", re.IGNORECASE),
    ),
)
# CONTEXT-tier: a bare time word is dangerous only when it anchors a claim about
# wiring/dormancy state on the same line — that co-occurrence is exactly the
# root-cause shape ("no production boot path constructs X today").
_CONTEXT_TIME_RE = re.compile(r"\b(?:today|currently|not\s+yet)\b", re.IGNORECASE)
_WIRING_VOCAB_RE = re.compile(
    r"dorman(?:t(?!-safe)|cy)|no (?:live|production)\b|production boot|boot path"
    r"|live code|\bconstructs?\b|wires (?:it|the)\b|\ballowlist\b|air.?gap"
    r"|\begress\b|\bexternal\b|\bweld",
    re.IGNORECASE,
)
# A docstring describing what a live-state READER returns ("Return the
# currently-registered verifier", "True iff ... currently installed") is
# evergreen by construction — it reports state at call time, it does not
# narrate build-time wiring. Excluded as an idiom, not per-file.
_STATE_READER_IDIOM_RE = re.compile(
    r"\b(?:Return(?:s)?|Number of|True iff|Whether)\b.{0,80}\bcurrently\b", re.IGNORECASE
)

# Reviewed per-file allowlist for genuinely evergreen uses the tiers still
# catch: {(relative posix path, phrase label): max allowed count}. Additions
# are a reviewed act and each entry carries its justification here. The
# quarterly consolidation pass prunes entries whose count has reached zero.
_PROSE_ALLOWLIST: dict[tuple[str, str], int] = {}


def _prose_lines(path: Path) -> list[tuple[int, str]]:
    """Every comment/docstring line of a Python file as (lineno, text).

    Code strings (log messages, CLI prompts, f-strings) are deliberately out of
    scope: the lint governs the prose a reader grounds on, not runtime output.
    Line-granular on purpose — a phrase split across a line break can evade the
    lint; the reviewer's diff is the second net, and the phrase CLASS is what
    is being outlawed at introduction time.
    """
    text = path.read_text(encoding="utf-8")
    lines: list[tuple[int, str]] = []
    for tok in _tokenize.generate_tokens(_io.StringIO(text).readline):
        if tok.type == _tokenize.COMMENT:
            lines.append((tok.start[0], tok.string))
    for node in _ast.walk(_ast.parse(text)):
        if isinstance(node, (_ast.Module, _ast.ClassDef, _ast.FunctionDef, _ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], _ast.Expr)
                and isinstance(body[0].value, _ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                start = body[0].lineno
                for offset, line in enumerate(body[0].value.value.splitlines()):
                    lines.append((start + offset, line))
    return lines


def _scan_time_anchored_prose(files: list[Path], root: Path) -> list[str]:
    """All time-anchored current-wiring prose violations across ``files``."""
    counts: dict[tuple[str, str], list[str]] = {}
    for path in files:
        rel = path.relative_to(root).as_posix()
        for lineno, line in _prose_lines(path):
            hits: list[str] = []
            for label, pattern in _HARD_PROSE_PHRASES:
                if pattern.search(line):
                    hits.append(label)
            if not hits and _CONTEXT_TIME_RE.search(line):
                if _WIRING_VOCAB_RE.search(line) and not _STATE_READER_IDIOM_RE.search(line):
                    hits.append("time-anchored wiring claim")
            for label in hits:
                counts.setdefault((rel, label), []).append(f"L{lineno}: {line.strip()[:100]}")
    violations: list[str] = []
    for (rel, label), sites in sorted(counts.items()):
        allowed = _PROSE_ALLOWLIST.get((rel, label), 0)
        if len(sites) > allowed:
            detail = "; ".join(sites[:4]) + ("; ..." if len(sites) > 4 else "")
            violations.append(f"{rel} [{label}] x{len(sites)} (allowed {allowed}): {detail}")
    return violations


def _security_prose_files() -> list[Path]:
    files: list[Path] = []
    for d in SECURITY_PROSE_DIRS:
        assert d.is_dir(), f"#978 prose surface missing: {d}"
        files.extend(
            p for p in sorted(d.rglob("*.py"))
            if not p.name.startswith("test_") and "tests" not in p.parts
        )
    return files


def test_security_prose_carries_no_time_anchored_wiring_claims() -> None:
    """No security/coordinator/PA docstring or comment narrates current wiring.

    The #978 root cause: a docstring may state defaults and contracts ("with an
    empty allowlist, every URL is denied" — evergreen); it must never narrate
    current wiring ("the allowlist is empty this sprint" — rots at the next
    go-live ceremony, and the ceremony never reopens the docstring).
    """
    violations = _scan_time_anchored_prose(_security_prose_files(), REPO_ROOT)
    assert not violations, (
        "time-anchored current-wiring prose in security surfaces (#978) — restate "
        "each as a timeless default/contract claim, or allowlist a genuinely "
        "evergreen use as a reviewed act:\n  " + "\n  ".join(violations)
    )


def test_prose_lint_catches_planted_violation(tmp_path: Path) -> None:
    """Toggle-off proof: every tier fires on a planted current-wiring claim."""
    planted = tmp_path / "planted.py"
    planted.write_text(
        '"""Module doc.\n\n'
        "The allowlist is empty this sprint, so nothing egresses.\n"
        '"""\n'
        "# DORMANT: no production boot path constructs a Frobnicator today.\n"
        "X = 1  # this branch never fires in production\n",
        encoding="utf-8",
    )
    violations = _scan_time_anchored_prose([planted], tmp_path)
    joined = "\n".join(violations)
    assert "this sprint" in joined, f"hard tier failed to fire: {violations}"
    assert "never fires in production" in joined, f"hard tier failed to fire: {violations}"
    assert "time-anchored wiring claim" in joined or "dormancy status header" in joined, (
        f"context tier failed to fire: {violations}"
    )


def test_prose_lint_passes_evergreen_prose(tmp_path: Path) -> None:
    """Negative control: timeless design claims and state-reader docstrings pass."""
    clean = tmp_path / "clean.py"
    clean.write_text(
        '"""With an empty allowlist, every URL is denied (deny-by-default).\n\n'
        "Registering a screener does not by itself enable egress; the guard\n"
        "only invokes it for external-allowlisted sockets.\n"
        '"""\n'
        "def n():\n"
        '    """Return the number of outbound screeners currently registered."""\n'
        "    return 0  # dormant-safe: with none registered, ESCALATE is DENIED\n",
        encoding="utf-8",
    )
    assert _scan_time_anchored_prose([clean], tmp_path) == []


# --- Probe 2: posture pins — CLAUDE.md lock-claims resolve against reality --
#
# The claim regexes are the greppable pin surface: each names a prose lock-claim
# that is FALSIFIABLE against the real code symbol / real config. A claim that
# is absent passes vacuously (the corrected doc simply stops making it); a claim
# that is present must be TRUE against the wiring it describes, so the stale
# sentence can never be reintroduced while the door is open — and if the door is
# ever re-welded (the documented re-weld procedure), the claims become true and
# pass again.
_WELDED_EGRESS_CLAIMS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("D1 trust-spine 'unregistered adjudicator'", re.compile(r"unregistered\s+adjudicator", re.IGNORECASE)),
    ("D2 'only egress stays welded'", re.compile(r"only\s+egress\s+stays\s+welded", re.IGNORECASE)),
    # Must match an assertion about the allowlist's CURRENT STATE ("the allowlist is
    # empty"), never the timeless deny-by-default statement ("an empty allowlist denies
    # everything"). The bare noun phrase `empty allowlist` cannot tell them apart, and
    # matching it flagged security_by_design principle 2 — a correct, timeless design
    # claim — as a false weld assertion. This module's own contract says accurate prose
    # "states timeless design claims" and only TIME-ANCHORED CURRENT-WIRING claims are
    # the defect; a probe that punishes the honest form would push doctrine to weaken a
    # true principle to satisfy a lint. Locked by
    # test_weld_pin_ignores_timeless_deny_by_default_statement.
    (
        "'allowlist is empty' weld claim",
        re.compile(r"\b(?:egress\s+)?allowlist\s+(?:is|stays|remains)\s+empty\b", re.IGNORECASE),
    ),
)
_ADJUDICATOR_CALL_RE = re.compile(r"register_url(?:_ingest)?_adjudicator\s*\(")


def _egress_allowlist_symbol() -> frozenset[str]:
    """The real shipped allowlist, from the code symbol (not a copy)."""
    from services.policy_agent.src.gpu_inference import DeterministicPolicyChecker

    return DeterministicPolicyChecker._EGRESS_ALLOWLIST


def _web_search_enabled() -> bool:
    with DEFAULT_TOML.open("rb") as fh:
        return bool(_tomllib.load(fh)["web_search"]["enabled"])


def _adjudicator_registration_sites() -> list[str]:
    """Production (non-test) call sites that register a URL adjudicator.

    A static-reachability proxy for "an adjudicator IS registered at live
    boot": the seam module itself and test files are excluded, `def` lines are
    not calls. Zero sites is what "unregistered adjudicator" would require.
    """
    sites: list[str] = []
    for root in (REPO_ROOT / "services", REPO_ROOT / "launcher", REPO_ROOT / "shared"):
        for path in sorted(root.rglob("*.py")):
            if path.name.startswith("test_") or "tests" in path.parts:
                continue
            if path == REPO_ROOT / "shared" / "security" / "guarded_fetch.py":
                continue  # the seam definition, not a consumer
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if _ADJUDICATOR_CALL_RE.search(line) and not line.lstrip().startswith(("def ", "#")):
                    sites.append(f"{path.relative_to(REPO_ROOT).as_posix()}:{lineno}")
    return sites


def _welded_egress_pin_violations(
    doc_text: str,
    *,
    allowlist: frozenset[str],
    web_search_enabled: bool,
    adjudicator_sites: list[str],
) -> list[str]:
    """Violations for every welded-egress claim ``doc_text`` makes that reality contradicts."""
    contradictions: list[str] = []
    if allowlist:
        contradictions.append(f"_EGRESS_ALLOWLIST is not empty: {sorted(allowlist)}")
    if web_search_enabled:
        contradictions.append("[web_search].enabled = true in default.toml")
    if adjudicator_sites:
        contradictions.append(
            "adjudicator registration call sites exist: " + ", ".join(adjudicator_sites[:4])
        )
    if not contradictions:
        return []
    return [
        f"{claim_id}: doc claims welded egress but {'; '.join(contradictions)}"
        for claim_id, claim_re in _WELDED_EGRESS_CLAIMS
        if claim_re.search(doc_text)
    ]


def test_claude_md_posture_claims_resolve_against_reality() -> None:
    """CLAUDE.md may only claim a welded egress posture the wiring actually has.

    The doc<->code leg the #978 audit found missing: the code<->code leg
    (test_egress_screen pinning the allowlist exactly) never checked what the
    authoritative doctrine TELLS a session about those locks.
    """
    violations = _welded_egress_pin_violations(
        _read(CLAUDE_MD),
        allowlist=_egress_allowlist_symbol(),
        web_search_enabled=_web_search_enabled(),
        adjudicator_sites=_adjudicator_registration_sites(),
    )
    assert not violations, (
        "CLAUDE.md asserts an egress posture the wiring contradicts (#978 D1/D2) — "
        "correct the doctrine sentence (or re-weld the door before claiming it):\n  "
        + "\n  ".join(violations)
    )


def test_posture_pin_fails_when_claim_contradicts_wiring() -> None:
    """Toggle-off proof: a welded claim against open wiring is refused."""
    violations = _welded_egress_pin_violations(
        "egress denied by deny-by-default allowlist + unregistered adjudicator",
        allowlist=frozenset({"kagi.com"}),
        web_search_enabled=True,
        adjudicator_sites=["services/assistant_orchestrator/src/entrypoint.py:5620"],
    )
    assert len(violations) == 1 and "unregistered adjudicator" in violations[0]


def test_weld_pin_ignores_timeless_deny_by_default_statement() -> None:
    """A timeless design claim is NOT a weld assertion, even against open wiring.

    Regression lock for a false positive this gate shipped with: the bare noun
    phrase ``empty allowlist`` matched ``security_by_design`` principle 2 — "An
    empty allowlist denies everything" — which states what deny-by-default MEANS
    and asserts nothing about the live allowlist. It fired on merged main with the
    corrections already in, so the pair could not go green together.

    The distinction is this module's whole thesis (see the header): a docstring may
    state defaults and contracts, and only a TIME-ANCHORED CURRENT-WIRING claim is
    the defect. Had the probe kept flagging the honest form, the cheap fix would
    have been to soften a true security principle to satisfy a lint — the tail
    wagging the doctrine. Both forms are pinned here so neither can drift.
    """
    open_wiring = {
        "allowlist": frozenset({"kagi.com"}),
        "web_search_enabled": True,
        "adjudicator_sites": ["services/assistant_orchestrator/src/entrypoint.py:5620"],
    }
    # Timeless / definitional — must NOT fire.
    assert (
        _welded_egress_pin_violations(
            "DENY-BY-DEFAULT: allowlists, never blocklists. An empty allowlist denies "
            "everything. New capability starts denied and is explicitly granted.",
            **open_wiring,
        )
        == []
    )
    # Current-state assertion — MUST fire (the probe still has teeth).
    for claim in (
        "the egress allowlist is empty, so every external URL is denied",
        "the allowlist stays empty until the ceremony",
        "the allowlist remains empty in production",
    ):
        violations = _welded_egress_pin_violations(claim, **open_wiring)
        assert len(violations) == 1 and "allowlist is empty" in violations[0], (
            f"weld pin failed to fire on a current-state claim: {claim!r}"
        )


def test_posture_pin_passes_when_wiring_is_actually_welded() -> None:
    """A welded claim over genuinely welded wiring is TRUE and passes."""
    assert (
        _welded_egress_pin_violations(
            "only egress stays welded until its ceremony",
            allowlist=frozenset(),
            web_search_enabled=False,
            adjudicator_sites=[],
        )
        == []
    )


def test_posture_pin_passes_on_corrected_doc_text() -> None:
    """The #978 fix pattern passes vacuously: accurate prose names no dead lock.

    Fixture mirrors the phrasing the audit graded VERIFIED CLEAN (the copilot
    mirror's egress paragraph): deny-by-default behind multiple independent
    locks, without naming a disproven one.
    """
    corrected = (
        "egress is deny-by-default behind multiple independent locks; each scope "
        "opens only through an LA-present ceremony (web_search LIVE 2026-07-02 via "
        "the kagi.com allowlist entry; remaining scopes welded per-scope)"
    )
    assert (
        _welded_egress_pin_violations(
            corrected,
            allowlist=frozenset({"kagi.com"}),
            web_search_enabled=True,
            adjudicator_sites=["services/assistant_orchestrator/src/entrypoint.py:5620"],
        )
        == []
    )


# --- Probe 3: default.toml dormancy-comment lint ----------------------------
#
# Narrow and regexable: a DORMANT-vocabulary comment block attached to a key
# whose live value is `true` fails unless the value line itself carries a dated
# go-live annotation (the [image_generation] pattern:
# `enabled = true   # GO-LIVE 2026-06-16 (#666): ...`).
_TOML_DORMANT_VOCAB_RE = re.compile(
    # DORMANT-SAFE is the evergreen conditional idiom ("verify fires only when
    # enabled=true") — excluded, mirroring the prose tier's dormant(?!-safe).
    r"\bDORMANT\b(?!-SAFE)|default\s*\(false\)|ships\s+enabled\s*=\s*false"
    r"|\b[Oo]ff by default\b|flip this to true"
)
_TOML_TRUE_KEY_RE = re.compile(r"^([A-Za-z0-9_]+)\s*=\s*true\b(.*)$")
_TOML_GO_LIVE_DATE_RE = re.compile(r"#[^\n]*\b\d{4}-\d{2}-\d{2}\b")


def _toml_dormancy_violations(text: str) -> list[str]:
    violations: list[str] = []
    block: list[str] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        stripped = raw.strip()
        if stripped.startswith("#"):
            block.append(stripped)
            continue
        key_match = _TOML_TRUE_KEY_RE.match(stripped)
        if key_match and block:
            block_text = " ".join(block)
            vocab = _TOML_DORMANT_VOCAB_RE.search(block_text)
            if vocab and not _TOML_GO_LIVE_DATE_RE.search(key_match.group(2)):
                violations.append(
                    f"L{lineno} {key_match.group(1)} = true under a dormancy comment "
                    f"({vocab.group(0)!r}) with no dated go-live annotation on the value line"
                )
        block = []  # any non-comment line (key, blank, section header) breaks attachment
    return violations


def test_default_toml_dormancy_comments_match_live_values() -> None:
    """No `key = true` in default.toml sits under a comment narrating dormancy.

    A flipped flag keeps its pre-ceremony comment forever unless something
    forces the pair to move together; the dated go-live annotation on the value
    line is that forcing function (#978 S2-S4).
    """
    violations = _toml_dormancy_violations(_read(DEFAULT_TOML))
    assert not violations, (
        "default.toml dormancy comments contradict live `true` values (#978) — rewrite "
        "the comment to the evergreen contract or date the go-live on the value line:\n  "
        + "\n  ".join(violations)
    )


def test_toml_dormancy_lint_catches_planted_violation() -> None:
    """Toggle-off proof: DORMANT block over `true` with no date is refused."""
    planted = (
        "[thing]\n"
        "# DORMANT: ships enabled=false until the ceremony.\n"
        "enabled = true\n"
    )
    violations = _toml_dormancy_violations(planted)
    assert len(violations) == 1 and "enabled = true" in violations[0]


def test_toml_dormancy_lint_accepts_dated_golive_and_false_values() -> None:
    """Negative controls: a dated go-live annotation, a false value, and an
    evergreen comment each pass; attachment breaks across blank lines."""
    assert (
        _toml_dormancy_violations(
            "# DORMANT: ships enabled=false until the ceremony.\n"
            "enabled = true   # GO-LIVE 2026-06-16 (#666): attestation recorded\n"
        )
        == []
    )
    assert _toml_dormancy_violations("# DORMANT: ships enabled=false.\nenabled = false\n") == []
    assert _toml_dormancy_violations("# fail-closed contract, deny-by-default.\nenabled = true\n") == []
    assert (
        _toml_dormancy_violations("# DORMANT: ships enabled=false.\n\nunrelated = true\n") == []
    )
