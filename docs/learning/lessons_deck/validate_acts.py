#!/usr/bin/env python
"""Mechanical validator for the lessons-deck act files.

Checks every acts/act<N>.json against the SCHEMA.md contract:
  - structural: required fields, types, per-act lesson assignment, ordering
  - anti-hallucination: every evidence pointer must resolve — a dated journal
    entry header for acts 1-7 (and any journal kinship), the source fragment
    file for act 8; every commit SHA cited must appear verbatim in the source
    it is cited from
  - vocabulary: aigp_domains / aigp_frameworks restricted to the verified
    aigp_vocabulary.md anchors
  - budgets: word-count ranges per beat (warn-level)

Exit 0 = no FAILs (warnings allowed). Also emits aigp_mapping_report.md — the
compact per-unit mapping table the integrator reviews by hand.
"""
import json
import pathlib
import re
import sys

D = pathlib.Path(__file__).resolve().parent
WT_ROOT = D.parents[2]  # worktree root
JOURNAL = WT_ROOT / "BUILD_JOURNAL.md"
FRAG_DIR = WT_ROOT / "docs" / "journal_fragments"
# The one untracked fragment lives only in the main checkout (read-only).
MAIN_FRAG_DIR = pathlib.Path(r"C:\Users\mrbla\BlarAI\docs\journal_fragments")

EXPECTED = {
    1: [2, 3, 6, 7, 8, 16, 21, 30, 32, 33, 37, 91, 96],
    2: [46, 55, 56, 65, 68, 70, 74, 77, 78, 79, 81, 87, 88, 90, 92, 114, 118, 119],
    3: [4, 5, 12, 15, 19, 20, 26, 28, 31, 40, 43, 102, 120, 122],
    4: [1, 17, 29, 38, 39, 45, 49, 66, 69, 72, 84, 85, 86, 99, 100, 103, 105, 107, 115],
    5: [13, 18, 22, 23, 34, 36, 44, 47, 50, 51, 53, 54, 57, 59, 60, 61, 62, 63, 67, 71,
        93, 94, 95, 97, 101, 104, 106, 109, 110, 111, 112, 121],
    6: [14, 24, 48, 82, 83],
    7: [9, 10, 11, 25, 27, 35, 41, 42, 52, 58, 64, 73, 75, 76, 80, 89, 98, 113, 116],
    8: None,  # June units, number=null (numbers assigned only at fold-in;
              # 13 folded units moved to their thematic acts 2026-07-03, #731)
}

DIAGRAM_FIRST_LINES = ("flowchart TD", "flowchart LR", "sequenceDiagram")
DIAGRAM_FORBIDDEN = ("classDef", "linkStyle", "%%{", "click ", "\nstyle ")
ALLOWED_FIELDS = set()  # filled after UNIT_FIELDS is defined

DOMAIN_ANCHORS = (
    "Domain I — Understanding the Foundations of AI Governance",
    "Domain II — Understanding How Laws, Standards and Frameworks Apply to AI",
    "Domain III — Understanding How to Govern AI Development",
    "Domain IV — Understanding How to Govern AI Deployment and Use",
)
FRAMEWORK_ANCHORS = (
    "NIST AI RMF",
    "ISO/IEC 42001",
    "ISO/IEC 42005",
    "OECD AI Principles",
    "EU AI Act",
    "TEVV",
)
UNIT_FIELDS = (
    "number", "title", "failure", "evidence", "lesson", "growth",
    "growth_question", "aigp_text", "aigp_domains", "aigp_frameworks",
    "aigp_takeaway",
)
ALLOWED_FIELDS = set(UNIT_FIELDS) | {"prologue", "fragment", "diagram", "stat"}
BUDGET = {  # field -> (min_words, max_words), warn-level
    "failure": (60, 200), "lesson": (25, 115), "growth": (60, 200),
    "aigp_text": (35, 135),
}

journal_text = JOURNAL.read_text(encoding="utf-8")
# 2026-07-03: the numbered lessons list moved to LESSONS.md (lesson 196);
# evidence pointers (SHAs, lesson text) must resolve against both surfaces.
_lessons_file = WT_ROOT / "LESSONS.md"
if _lessons_file.exists():
    journal_text += "\n" + _lessons_file.read_text(encoding="utf-8")
entry_headers = re.findall(r"^### (\d{4}-\d{2}-\d{2}) — (.+)$", journal_text, re.M)
header_by_date = {}
for d, t in entry_headers:
    header_by_date.setdefault(d, []).append(t.strip())

fails, warns = [], []
report_rows = []
total_units = 0
seen_unit_ids = set()
_core_file = D / "core_path.json"
CORE = set(json.loads(_core_file.read_text(encoding="utf-8"))["core"]) if _core_file.exists() else set()


def words(s):
    return len(re.findall(r"\S+", s or ""))


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def check_evidence(label, ev_list, act_no, fragment_name):
    """Every evidence pointer must resolve; every SHA must exist in its source.

    Returns the fragment text (if any) so callers can verify stat values."""
    if not ev_list:
        fails.append(f"{label}: empty evidence list")
        return ""
    frag_text = ""
    if fragment_name:
        fp = FRAG_DIR / fragment_name
        if not fp.exists():
            fp = MAIN_FRAG_DIR / fragment_name
        if not fp.exists():
            fails.append(f"{label}: fragment file not found: {fragment_name}")
        else:
            frag_text = fp.read_text(encoding="utf-8")
    for ev in ev_list:
        m = re.match(r"^(\d{4}-\d{2}-\d{2})\s*—\s*(.+)$", ev.strip())
        if m:
            d, t = m.group(1), m.group(2).strip()
            titles = header_by_date.get(d, [])
            frag_hit = fragment_name and (d in frag_text or norm(t)[:40] in norm(frag_text))
            if not any(norm(t)[:40] in norm(x) or norm(x)[:40] in norm(t) for x in titles) and not frag_hit:
                fails.append(f"{label}: evidence entry not found in journal: {ev!r}")
        for sha in re.findall(r"\b[0-9a-f]{7,10}\b", ev):
            if sha not in journal_text and sha not in frag_text:
                fails.append(f"{label}: cited SHA {sha} not present in source text")
    return frag_text


for n in range(1, 9):
    p = D / "acts" / f"act{n}.json"
    if not p.exists():
        fails.append(f"act{n}.json missing")
        continue
    try:
        act = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        fails.append(f"act{n}.json does not parse: {e}")
        continue
    if act.get("act") != n:
        fails.append(f"act{n}.json: act field is {act.get('act')}")
    for k in ("title", "subtitle", "aigp_intro", "aigp_domains", "lessons"):
        if not act.get(k):
            fails.append(f"act{n}.json: missing/empty {k}")
    lessons = act.get("lessons", [])
    nums = [u.get("number") for u in lessons]
    if EXPECTED[n] is not None:
        if sorted(x for x in nums if x is not None) != sorted(EXPECTED[n]):
            fails.append(f"act{n}.json: lesson numbers {nums} != expected {EXPECTED[n]}")
        body = [x for x in nums if x is not None]
        ordered = sorted(body) if n != 4 else [1] + sorted(x for x in body if x != 1)
        if body != ordered:
            fails.append(f"act{n}.json: lessons not in required order: {body}")
    else:
        if any(x is not None for x in nums):
            fails.append("act8.json: June units must have number=null")
        # fragment is optional: a unit whose source fragment has since been
        # folded into the journal anchors to the dated entry instead.
    for u in lessons:
        total_units += 1
        uid = f"act{n}/#{u.get('number')}" if u.get("number") else f"act{n}/{u.get('fragment')}"
        for f in UNIT_FIELDS:
            if f not in u or (u[f] in (None, "", []) and f != "number"):
                fails.append(f"{uid}: missing/empty field {f}")
        for f in u:
            if f not in ALLOWED_FIELDS:
                fails.append(f"{uid}: unknown field {f!r} (typo?)")
        diag = u.get("diagram")
        if diag:
            lines = diag.strip().splitlines()
            if lines[0].strip() not in DIAGRAM_FIRST_LINES:
                fails.append(f"{uid}: diagram first line {lines[0].strip()!r} not one of {DIAGRAM_FIRST_LINES}")
            for tok in DIAGRAM_FORBIDDEN:
                if tok in diag:
                    fails.append(f"{uid}: diagram contains forbidden token {tok.strip()!r}")
            if lines[0].strip() == "sequenceDiagram" and ";" in diag:
                fails.append(f"{uid}: ';' inside a sequenceDiagram acts as a statement "
                             "separator and breaks the parse — rephrase the text")
            if len(lines) > 24:
                warns.append(f"{uid}: diagram is {len(lines)} lines (keep mechanisms small)")
        stats = u.get("stat")
        if stats is not None:
            if not isinstance(stats, list) or not 1 <= len(stats) <= 3:
                fails.append(f"{uid}: stat must be a list of 1-3 entries")
                stats = []
            for s_i, s in enumerate(stats):
                keys = set(s)
                extra = keys - {"before", "after", "value", "label"}
                if extra:
                    fails.append(f"{uid}: stat[{s_i}] unknown keys {sorted(extra)}")
                if "label" not in keys or not (("value" in keys) ^ ("before" in keys and "after" in keys)):
                    fails.append(f"{uid}: stat[{s_i}] needs label + (value XOR before/after)")
        for f, (lo, hi) in BUDGET.items():
            w = words(u.get(f, ""))
            if not lo <= w <= hi:
                warns.append(f"{uid}: {f} is {w} words (budget {lo}-{hi})")
        if u.get("aigp_takeaway") and words(u["aigp_takeaway"]) > 30:
            warns.append(f"{uid}: takeaway {words(u['aigp_takeaway'])} words (>30)")
        gq = u.get("growth_question", "")
        if gq and not gq.rstrip().endswith("?"):
            warns.append(f"{uid}: growth_question does not end with '?'")
        for dom in u.get("aigp_domains", []):
            if not any(dom.startswith(a) for a in DOMAIN_ANCHORS):
                fails.append(f"{uid}: domain not in verified vocabulary: {dom!r}")
        for fw in u.get("aigp_frameworks", []):
            if not any(fw.startswith(a) for a in FRAMEWORK_ANCHORS):
                fails.append(f"{uid}: framework not in verified vocabulary: {fw!r}")
        frag_text = check_evidence(uid, u.get("evidence", []), n, u.get("fragment"))
        for s in (u.get("stat") or []):
            if not isinstance(s, dict):
                continue
            for k in ("before", "after", "value"):
                v = str(s.get(k, "")).strip()
                if v and v not in journal_text and v not in (frag_text or ""):
                    warns.append(f"{uid}: stat value {v!r} not found verbatim in its source (verify)")
        unit_uid = f"L{u['number']}" if u.get("number") is not None else None
        if unit_uid:
            seen_unit_ids.add(unit_uid)
        report_rows.append(
            (n, u.get("number"), (u.get("title") or "")[:58],
             "core" if (unit_uid and unit_uid in CORE) else "",
             "mech" if u.get("diagram") else "",
             "; ".join(x.split(" — ")[0] for x in u.get("aigp_domains", [])),
             "; ".join(u.get("aigp_frameworks", [])),
             u.get("aigp_takeaway", ""))
        )

# Core-path cross-checks (the curated default study track).
if not CORE:
    warns.append("core_path.json missing or empty — deck will fail to build")
else:
    missing_core = CORE - seen_unit_ids
    if missing_core:
        fails.append(f"core_path.json names units not present in any act: {sorted(missing_core)}")
    if not 20 <= len(CORE) <= 40:
        warns.append(f"core path has {len(CORE)} units (intended ~30)")

# Emit the integrator's review table.
rep = ["# AIGP mapping report (generated by validate_acts.py)", "",
       f"{total_units} units ({len(CORE)} on the core path). Review every row; "
       "fix misfit mappings in the act JSON, then re-run.", "",
       "| Act | # | Title | Core | Mech | Domain(s) | Framework anchor(s) | Takeaway |",
       "|---|---|---|---|---|---|---|---|"]
for r in report_rows:
    rep.append("| " + " | ".join(str(x if x is not None else "frag").replace("|", "/") for x in r) + " |")
(D / "aigp_mapping_report.md").write_text("\n".join(rep) + "\n", encoding="utf-8")

print(f"units={total_units}  FAILS={len(fails)}  warns={len(warns)}")
for f in fails:
    print("FAIL:", f)
for w in warns[:40]:
    print("warn:", w)
if len(warns) > 40:
    print(f"... +{len(warns) - 40} more warnings")
sys.exit(1 if fails else 0)
