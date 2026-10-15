"""Generate the rules corpus and the enforcement-gap list from the doctrine (#1690, #1700).

CLAUDE.md plus the path-scoped files in .claude/rules/ are the ONLY authored source of rule
text. Each rules file holds one section in CLAUDE.md's tag register; it is spliced in before
the closing root tag, so a rule keeps its id whichever file holds it, and each record names
its `source` file. This script parses the result into one record per atomic rule and writes
two GENERATED artifacts:

  docs/governance/rules-corpus.yaml  - one record per rule (schema in rules-corpus-README.md)
  docs/governance/rules-gaps.md      - rules with no machine enforcement (or reviewer-only)

Neither output is ever hand-edited; tests/security/test_rules_corpus.py fails when either
differs from a fresh extraction. Output is deterministic (no timestamps, stable order).

Fail-closed: any structural surprise (unbalanced or unknown tag, unclassified top-level tag,
unparseable line inside an included tag, duplicate id) raises RulesCorpusError and writes
nothing. A partial corpus is never emitted.

Enforcement is TRACE-MARKED, never inferred. A test, script or hook declares what it
enforces with a line `enforces-rule: <rule-id> [-- note]` in its docstring or a comment;
things that cannot carry a marker (the external user-level hook, reviewer agents) are
listed in docs/governance/rules-enforcement.yaml. The enforcement column is built ONLY from
those two sources. A marker or curated entry naming an unknown rule id, or a curated ref
that does not exist, raises: renaming or deleting a rule breaks loudly instead of moving
mappings. "Enforced" therefore means "a marker or curated entry exists", which the author
of the enforcing file asserted; it is not a coverage measurement.

Rule ids are derived from the rule's own NAME (its leading words), not its position, so
inserting an item moves no other id. Duplicate ids raise.

Usage:
  python scripts/extract_rules_corpus.py            # rewrite both outputs
  python scripts/extract_rules_corpus.py --check    # exit 1 if either output is stale
"""
from __future__ import annotations

import argparse
import hashlib
import os
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
RULES_DIR = REPO_ROOT / ".claude" / "rules"
sys.path.insert(0, str(REPO_ROOT / "scripts" / "hooks"))  # doctrine_rules: one parser for hook + extractor
EVIDENCE_MD = REPO_ROOT / "docs" / "governance" / "agent-doctrine-evidence.md"
CORPUS_OUT = REPO_ROOT / "docs" / "governance" / "rules-corpus.yaml"
GAPS_OUT = REPO_ROOT / "docs" / "governance" / "rules-gaps.md"

ROOT_TAG = "blarai_project_instructions"

# Top-level tags whose content is rules. Every top-level tag MUST be in exactly one of the
# two sets; an unclassified tag raises (a new section cannot silently escape the corpus).
RULE_TOP_TAGS = frozenset({
    "motto", "critical_rules", "session_start_protocol", "user_operator", "decision_boundary",
    "autonomy", "event_time_banking", "identity_split", "journal_discipline",
    "performance_capture", "vikunja", "testing", "security_by_design", "git_discipline",
    "coding_standards", "context_handoff", "maintenance", "identity_hygiene",
})
# State, facts and pointers: not rules. Listed so the exclusion is explicit and checkable.
FACT_TOP_TAGS = frozenset({
    "authority", "blarai_identity", "host_environment", "stack", "repo_constellation",
    "status_snapshot", "live_state_pointers", "rules_index",
})
# Sub-tags inside a rule section that hold facts, not rules.
FACT_SUBPATHS = frozenset({"user_operator/facts", "identity_split/facts"})
# Volatile dated state, replaced at every merge cluster: never parsed for rules.
VOLATILE_TOP_TAGS = frozenset({"status_snapshot"})
# Inside fact sections an item is a rule only if it carries an imperative/modal marker.
IMPERATIVE = re.compile(
    r"\bnever\b|\balways\b|\bmust\b|\bdo not\b|\bdon't\b|\bonly\b|\brequire[sd]?\b|\bforbidden\b|\bkeep\b|\bbefore ranking\b", re.I)
IMPERATIVE_CASE = re.compile(r"\bUSE\b")  # case-sensitive: "use" alone is not a marker

SCOPE_BY_TOP = {
    "git_discipline": ["git"], "journal_discipline": ["journal"],
    "performance_capture": ["perf"], "vikunja": ["vikunja"], "testing": ["tests"],
    "security_by_design": ["security"], "identity_hygiene": ["security"], "context_handoff": ["process"],
    "session_start_protocol": ["process"], "event_time_banking": ["process"],
}
SCOPE_KEYWORDS = (
    ("git", r"\bgit\b|\bmerge|\bbranch|worktree|\bcommit"),
    ("tests", r"pytest|\btests?\b|\bgate\b"),
    ("journal", r"journal|LESSONS"),
    ("vikunja", r"Vikunja|\bticket"),
    ("security", r"egress|security|fail-closed|fail closed|policy-gate"),
    ("perf", r"PERFORMANCE_LOG|performance|benchmark"),
)

_OPEN = re.compile(r"^<(\w+)((?:\s[^>]*)?)>$")
_INLINE = re.compile(r"^<(\w+)((?:\s[^>]*)?)>(.+)</\1>$")
_CLOSE = re.compile(r"^</(\w+)>$")
_NUMBERED = re.compile(r"^(\d+)\. (.+)$")
_BULLET = re.compile(r"^- (.+)$")


class RulesCorpusError(Exception):
    """CLAUDE.md could not be parsed into a complete corpus; nothing is emitted."""


def _name(text: str) -> str:
    """The rule's own NAME: its leading words up to the first ':', ' — ' or '. ' (at most
    seven words), else its first four words. Position never enters the id."""
    t = re.sub(r"[*`]", "", text)
    cut = len(t)
    for d in (":", " — ", ". "):
        i = t.find(d)
        if i > 0:
            cut = min(cut, i)
    pat = r"[a-z0-9]+(?:-[a-z0-9]+)*"
    words = re.findall(pat, t[:cut].lower())
    if not words or len(words) > 7:
        words = re.findall(pat, t.lower())[:4]
    return "-".join(words) or "rule"


def _is_rule_item(text: str) -> bool:
    return bool(IMPERATIVE.search(text) or IMPERATIVE_CASE.search(text))


def parse_claude_md(raw: str) -> list[dict[str, Any]]:
    """Parse CLAUDE.md text into ordered rule records (text fields only)."""
    return parse_claude_md_full(raw)[0]


def parse_claude_md_full(raw: str) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Records plus counts: facts excluded (non-imperative items in fact sections) and
    status_snapshot lines (volatile, never parsed)."""
    lines = raw.replace("\r\n", "\n").split("\n")
    stack: list[str] = []
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    sibling_counts: dict[str, int] = {}
    stats = {"facts_excluded": 0, "status_snapshot_lines": 0, "fact_items_included_as_rules": 0}
    root_closed = False

    def emit(path: list[str], text: str, number: int | None, lineno: int) -> None:
        if len(path) < 2:
            raise RulesCorpusError(f"line {lineno}: content outside any section: {text[:60]!r}")
        top = path[1]
        sub = "/".join(path[1:3])
        if top in VOLATILE_TOP_TAGS:
            stats["status_snapshot_lines"] += 1
            return
        if top in FACT_TOP_TAGS or sub in FACT_SUBPATHS:
            if not _is_rule_item(text):
                stats["facts_excluded"] += 1
                return
            stats["fact_items_included_as_rules"] += 1
        elif top not in RULE_TOP_TAGS:
            raise RulesCorpusError(f"line {lineno}: top-level tag <{top}> is not classified")
        tagpath = "/".join(path[1:])
        key = ".".join(path[1:])
        sibling_counts[tagpath] = sibling_counts.get(tagpath, 0) + 1
        ordinal = number if number is not None else sibling_counts[tagpath]
        rid = f"{key}.{_name(text)}"
        if rid in seen_ids:
            raise RulesCorpusError(f"line {lineno}: duplicate rule id {rid}")
        seen_ids.add(rid)
        records.append({
            "id": rid, "anchor": f"{tagpath}#{ordinal}", "text": text,
            "_top": top, "_sub": "/".join(path[1:3]), "_path": tagpath, "_line": lineno,
        })

    for i, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        if len(stack) >= 2 and stack[1] in VOLATILE_TOP_TAGS and not line.startswith("<"):
            stats["status_snapshot_lines"] += 1
            continue
        if line != line.rstrip() or line[0].isspace():
            raise RulesCorpusError(f"line {i}: leading/trailing whitespace is not a known shape")
        if root_closed:
            raise RulesCorpusError(f"line {i}: content after the closing root tag")
        if line.startswith("</"):
            m = _CLOSE.match(line)
            if not m:
                raise RulesCorpusError(f"line {i}: malformed closing tag {line[:40]!r}")
            if not stack or stack[-1] != m.group(1):
                raise RulesCorpusError(
                    f"line {i}: </{m.group(1)}> does not close the open <{stack[-1] if stack else None}>")
            stack.pop()
            if not stack:
                root_closed = True
            continue
        if line.startswith("<"):
            m = _INLINE.match(line)
            if m:
                if not stack:
                    raise RulesCorpusError(f"line {i}: inline tag before the root tag")
                emit(stack + [m.group(1)], m.group(3), None, i)
                continue
            m = _OPEN.match(line)
            if not m:
                raise RulesCorpusError(f"line {i}: malformed tag line {line[:60]!r}")
            if not stack and m.group(1) != ROOT_TAG:
                raise RulesCorpusError(f"line {i}: first tag must be <{ROOT_TAG}>")
            stack.append(m.group(1))
            if len(stack) == 2 and stack[1] not in RULE_TOP_TAGS | FACT_TOP_TAGS:
                raise RulesCorpusError(f"line {i}: top-level tag <{stack[1]}> is not classified")
            continue
        if not stack:
            raise RulesCorpusError(f"line {i}: text before the root tag")
        m = _NUMBERED.match(line)
        if m:
            emit(stack, m.group(2), int(m.group(1)), i)
            continue
        m = _BULLET.match(line)
        emit(stack, m.group(1) if m else line, None, i)
    if stack:
        raise RulesCorpusError(f"unclosed tag(s) at end of file: {stack}")
    if not root_closed:
        raise RulesCorpusError("no root tag found")
    return records, stats


def _evidence_titles() -> list[str]:
    """Bolded entry titles in the CLAUDE.md section of agent-doctrine-evidence.md."""
    if not EVIDENCE_MD.exists():
        return []
    txt = EVIDENCE_MD.read_text(encoding="utf-8").replace("\r\n", "\n")
    sec = txt.split("\n## CLAUDE.md\n", 1)
    if len(sec) < 2:
        return []
    body = sec[1].split("\n## ", 1)[0]
    return re.findall(r"^- \*\*(.+?)\*\*", body, flags=re.M)


# (evidence title, regex over rule text). The pointer is emitted only if the title exists.
WHY_MATCH = (
    ("THE CLOCK / elapsed time is measured", r"^0\. THE CLOCK"),
    ("Deferral momentum", r"MOMENTUM"),
    ("authority_first", r"NAME THE SURFACE THAT OWNS IT"),
    ("Never manufacture a stop", r"NEVER MANUFACTURE A STOP"),
    ("Documentation is not evidence", r"^Documentation is NOT evidence"),
    ("Gate kill shapes", r"The gate must not kill"),
    ("Snapshot byte-bloat", r"byte bloat|byte-bloat"),
    ("Never \"execute end to end\"", r"Never \"execute end to end\""),
)

H = "docs/governance/agent-doctrine-evidence.md"

ENFORCEMENT_YAML = REPO_ROOT / "docs" / "governance" / "rules-enforcement.yaml"
KINDS = ("test", "hook", "verifier", "reviewer", "gate")
MARKER = re.compile(r"^\s*(?:#\s*|//\s*)?enforces-rule:\s*(\S+)(?:\s+--\s+(.*?))?\s*$")
# Where markers are searched. The extractor and its own test mention the marker syntax.
MARKER_ROOTS = ("tests", "scripts", "services", "shared", "launcher", ".claude")
MARKER_SUFFIXES = (".py", ".ps1", ".sh")
MARKER_ROOT_FILES = ("conftest.py",)
MARKER_SELF = frozenset({"scripts/extract_rules_corpus.py", "tests/security/test_rules_corpus.py"})
# "worktrees": the app parks session worktrees under .claude/worktrees/; each is another checkout whose markers
# belong to its own branch, so walking into them double-counts refs under paths that imply no kind.
_SKIP_DIRS = frozenset({".git", ".venv", "venv", "__pycache__", "node_modules", "models", "userdata", "worktrees"})


def _kind_for_path(rel: str) -> str:
    if rel == "conftest.py" or rel.endswith("/conftest.py"):
        return "gate"
    if rel.startswith(("scripts/hooks/", ".claude/hooks/")):
        return "hook"
    if rel.startswith("tests/") or "/tests/" in rel:
        return "test"
    if rel.startswith("scripts/") and Path(rel).name.startswith("verify_"):
        return "verifier"
    raise RulesCorpusError(
        f"{rel}: carries an enforces-rule marker but its path implies no kind "
        "(tests, scripts/hooks, scripts/verify_*, conftest.py); list it in rules-enforcement.yaml")


def find_markers(root: Path) -> list[dict[str, str]]:
    """Every `enforces-rule:` marker under the marker roots: {rule, kind, ref, note}."""
    found: list[dict[str, str]] = []
    files: list[Path] = [root / f for f in MARKER_ROOT_FILES if (root / f).is_file()]
    for top in MARKER_ROOTS:
        base = root / top
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
            files += [Path(dirpath) / f for f in sorted(filenames) if f.endswith(MARKER_SUFFIXES)]
    for f in files:
        rel = f.relative_to(root).as_posix()
        if rel in MARKER_SELF:
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "enforces-rule:" not in text:
            continue
        for line in text.split("\n"):
            m = MARKER.match(line)
            if m:
                found.append({"rule": m.group(1), "kind": _kind_for_path(rel), "ref": rel,
                              "note": (m.group(2) or "").strip()})
    return found


def load_curated(root: Path) -> list[dict[str, str]]:
    """docs/governance/rules-enforcement.yaml: one `- {json}` entry per line."""
    p = root / "docs" / "governance" / "rules-enforcement.yaml"
    if not p.is_file():
        return []
    out = []
    for n, line in enumerate(p.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n"), 1):
        if not line.strip() or line.startswith("#"):
            continue
        if not line.startswith("- {"):
            raise RulesCorpusError(f"rules-enforcement.yaml line {n}: expected '- {{json}}'")
        try:
            e = json.loads(line[2:])
        except ValueError as exc:
            raise RulesCorpusError(f"rules-enforcement.yaml line {n}: {exc}") from exc
        if set(e) - {"rule", "kind", "ref", "note"} or not {"rule", "kind", "ref"} <= set(e):
            raise RulesCorpusError(f"rules-enforcement.yaml line {n}: keys must be rule, kind, ref, note?")
        if e["kind"] not in KINDS:
            raise RulesCorpusError(f"rules-enforcement.yaml line {n}: unknown kind {e['kind']!r}")
        if not e["ref"].startswith("external:") and not (root / e["ref"]).is_file():
            raise RulesCorpusError(f"rules-enforcement.yaml line {n}: ref {e['ref']} does not exist")
        out.append({"rule": e["rule"], "kind": e["kind"], "ref": e["ref"], "note": e.get("note", "")})
    return out


def enforcement_map(ids: set[str], root: Path) -> dict[str, list[dict[str, str]]]:
    """rule id -> enforcement items, from markers + curated entries ONLY. Unknown rule id
    in either source raises (a rename/delete must break loudly)."""
    by_rule: dict[str, list[dict[str, str]]] = {}
    unknown = []
    for e in find_markers(root) + load_curated(root):
        if e["rule"] not in ids:
            unknown.append(f"{e['rule']} (named by {e['ref']})")
            continue
        item = {"kind": e["kind"], "ref": e["ref"]}
        if e["note"]:
            item["note"] = e["note"]
        lst = by_rule.setdefault(e["rule"], [])
        if item not in lst:
            lst.append(item)
    if unknown:
        raise RulesCorpusError("enforcement names rule ids that do not exist in CLAUDE.md: "
                               + "; ".join(sorted(unknown)))
    return {k: sorted(v, key=lambda x: (x["kind"], x["ref"])) for k, v in by_rule.items()}


# Hand-written, specific suggestions only, keyed by rule id. Everything else reads
# "none proposed": a generic keyword-derived suggestion is noise.
SUGGESTIONS: dict[str, str] = {
    "critical_rules.gate-first-then-finish": "Pre-merge script reads the Vikunja ticket and requires a dated gate or CURRENT STATE comment; the in-chat gate itself is not machine-visible.",
    "critical_rules.every-ship-is-one-atomic-motion": "Merge-time verifier: a merge commit on main must carry a ticket id, a journal entry or docs/journal_fragments file, and at least one test file in its diff.",
    "critical_rules.record-every-performance-measurement": "Verifier: a commit touching scripts/benchmark_* or docs/performance/*.json must also touch PERFORMANCE_LOG.md.",
    "critical_rules.test-the-seams": "Reviewer-only; a partial proxy is a test-diff lint for new tests that import the unit under test only as a mock.",
}
DEFAULT_SUGGESTION = "none proposed"


def _scope(rec: dict[str, Any]) -> list[str]:
    scope = set(SCOPE_BY_TOP.get(rec["_top"], []))
    for name, pat in SCOPE_KEYWORDS:
        if re.search(pat, rec["text"]):
            scope.add(name)
    return sorted(scope)


def _severity(rec: dict[str, Any]) -> str:
    if rec["_top"] == "critical_rules" or rec["_sub"] == "git_discipline/absolute_rules":
        return "critical"
    if rec["_sub"] == "security_by_design/principles":
        return "high"
    return "normal"


def _owner(rec: dict[str, Any]) -> str:
    return "LA" if rec["_sub"] == "decision_boundary/his_decisions" else "session"


def doctrine_text(raw: str, rules_dir: Path) -> tuple[str, list[tuple[int, str]]]:
    """CLAUDE.md with every .claude/rules/ body spliced in, plus the line-to-source map."""
    from doctrine_rules import RulesFileError, load_rules, splice
    try:
        return splice(raw, load_rules(rules_dir))
    except RulesFileError as exc:
        raise RulesCorpusError(f"rules file: {exc}") from None


def build_records(raw: str, root: Path = REPO_ROOT, rules_dir: Path | None = None) -> list[dict[str, Any]]:
    from doctrine_rules import source_for
    titles = set(_evidence_titles())
    text, sources = doctrine_text(raw, rules_dir if rules_dir is not None else RULES_DIR)
    parsed = parse_claude_md(text)
    emap = enforcement_map({r["id"] for r in parsed}, root)
    out = []
    for rec in parsed:
        why = ""
        for title, pat in WHY_MATCH:
            if title in titles and re.search(pat, rec["text"]):
                why = f"{H}#{title}"
                break
        out.append({
            "id": rec["id"], "anchor": rec["anchor"], "source": source_for(rec["_line"], sources),
            "text": rec["text"],
            "text_sha256": hashlib.sha256(rec["text"].encode("utf-8")).hexdigest(),
            "why_pointer": why, "scope": _scope(rec),
            "enforcement": emap.get(rec["id"]) or [{"kind": "none", "ref": ""}],
            "severity": _severity(rec), "owner": _owner(rec),
        })
    return sorted(out, key=lambda r: r["id"])


_HEADER = (
    "# GENERATED by scripts/extract_rules_corpus.py from CLAUDE.md + .claude/rules/. Never hand-edit.\n"
    "# Regenerate: python scripts/extract_rules_corpus.py\n"
    "# Schema and usage: docs/governance/rules-corpus-README.md\n"
)


def _j(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False)


def render_corpus(records: list[dict[str, Any]]) -> str:
    """Block-style YAML; every scalar/flow value is JSON, which is valid YAML."""
    parts = [_HEADER]
    for r in records:
        parts.append(f"- id: {_j(r['id'])}\n")
        for k in ("anchor", "source", "text", "text_sha256", "why_pointer", "scope"):
            parts.append(f"  {k}: {_j(r[k])}\n")
        parts.append("  enforcement:\n")
        for e in r["enforcement"]:
            parts.append(f"  - {_j(e)}\n")
        parts.append(f"  severity: {_j(r['severity'])}\n")
        parts.append(f"  owner: {_j(r['owner'])}\n")
    return "".join(parts)


def parse_corpus(text: str) -> list[dict[str, Any]]:
    """Inverse of render_corpus (own rigid format; no YAML dependency)."""
    recs: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    for line in text.split("\n"):
        if not line or line.startswith("#"):
            continue
        if line.startswith("- id: "):
            cur = {"id": json.loads(line[6:]), "enforcement": []}
            recs.append(cur)
        elif cur is None:
            raise RulesCorpusError(f"corpus line before first record: {line[:40]!r}")
        elif line.startswith("  - {"):
            cur["enforcement"].append(json.loads(line[4:]))
        elif line == "  enforcement:":
            continue
        elif line.startswith("  "):
            k, _, v = line[2:].partition(": ")
            cur[k] = json.loads(v)
        else:
            raise RulesCorpusError(f"unparseable corpus line: {line[:40]!r}")
    return recs


def _suggest(r: dict[str, Any]) -> str:
    return SUGGESTIONS.get(r["id"], DEFAULT_SUGGESTION)


def render_gaps(records: list[dict[str, Any]]) -> str:
    order = {"critical": 0, "high": 1, "normal": 2}
    gaps = [r for r in records if all(e["kind"] in ("none", "reviewer") for e in r["enforcement"])]
    gaps.sort(key=lambda r: (order[r["severity"]], r["id"]))
    n_none = sum(1 for r in gaps if r["enforcement"][0]["kind"] == "none")
    lines = [
        "<!-- GENERATED by scripts/extract_rules_corpus.py from CLAUDE.md + .claude/rules/. Never hand-edit. -->",
        "# Rules with no machine enforcement",
        "",
        f"{len(gaps)} of {len(records)} rules have no test, hook, verifier or gate "
        f"({n_none} none, {len(gaps) - n_none} reviewer-only). Sorted by severity, then id.",
        "The 'Cheapest check' column is a SUGGESTION, not a decision.",
        "",
        "| Severity | Id | Enforcement | Rule (first 110 chars) | Cheapest check (suggestion) |",
        "|---|---|---|---|---|",
    ]
    for r in gaps:
        enf = "+".join(sorted({e["kind"] for e in r["enforcement"]}))
        txt = r["text"][:110].replace("|", "/").replace("\n", " ")
        lines.append(f"| {r['severity']} | {r['id']} | {enf} | {txt} | {_suggest(r)} |")
    return "\n".join(lines) + "\n"


def generate(claude_md: Path | None = None, root: Path | None = None) -> tuple[str, str]:
    records = build_records((claude_md or CLAUDE_MD).read_text(encoding="utf-8"), root or REPO_ROOT)
    return render_corpus(records), render_gaps(records)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if committed outputs are stale")
    args = ap.parse_args(argv)
    try:
        corpus, gaps = generate()
    except RulesCorpusError as exc:
        print(f"extract_rules_corpus: REFUSING to emit a partial corpus: {exc}", file=sys.stderr)
        return 2
    if args.check:
        stale = [p.name for p, new in ((CORPUS_OUT, corpus), (GAPS_OUT, gaps))
                 if not p.exists() or p.read_text(encoding="utf-8").replace("\r\n", "\n") != new]
        if stale:
            print(f"stale: {stale}; run python scripts/extract_rules_corpus.py", file=sys.stderr)
            return 1
        return 0
    for p, new in ((CORPUS_OUT, corpus), (GAPS_OUT, gaps)):
        p.write_text(new, encoding="utf-8", newline="\n")
    print(f"wrote {CORPUS_OUT.name} and {GAPS_OUT.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
