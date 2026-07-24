"""Mine Claude Code session transcripts for actual file-read patterns.

Parses every *.jsonl under the project transcript dir, extracts tool_use blocks,
and aggregates per-file: read counts (full vs partial), grep/glob/edit/write counts,
distinct sessions touching, first/last/recent timestamps. Stdlib only. Read-only.
"""
import json
import glob
import os
import re
import time
from collections import defaultdict

ROOT = "C:/Users/mrbla/.claude/projects/C--Users-mrbla-BlarAI"
SCRATCH = os.path.dirname(os.path.abspath(__file__))
OUT_JSON = os.path.join(SCRATCH, "transcript_read_patterns.json")
OUT_TXT = os.path.join(SCRATCH, "transcript_read_patterns.txt")
RECENT_CUTOFF = "2026-07-04"  # last 14 days

WORKTREE_RE = re.compile(r"^.*?/\.claude/worktrees/agent-[^/]+/")
WORKTREE2_RE = re.compile(r"^.*?/\.worktrees/[^/]+/")
REPO_PREFIX = "c:/users/mrbla/blarai/"


def norm(p):
    if not isinstance(p, str) or not p.strip():
        return None
    q = p.replace("\\", "/").strip().lower()
    q = WORKTREE_RE.sub("", q)
    q = WORKTREE2_RE.sub("", q)
    if q.startswith(REPO_PREFIX):
        q = q[len(REPO_PREFIX):]
    return q


def new_stat():
    return {
        "reads": 0, "full_reads": 0, "partial_reads": 0, "greps": 0,
        "globs": 0, "edits": 0, "writes": 0, "recent_reads": 0,
        "sessions": set(), "first": None, "last": None,
    }


def main():
    t0 = time.time()
    stats = defaultdict(new_stat)
    tool_totals = defaultdict(int)
    task_spawns = 0
    n_files = 0
    n_lines = 0
    n_bad = 0

    for fp in glob.glob(ROOT + "/**/*.jsonl", recursive=True):
        if "/memory/" in fp.replace("\\", "/"):
            continue
        sid = os.path.basename(fp)
        n_files += 1
        try:
            fh = open(fp, "r", encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                n_lines += 1
                if '"tool_use"' not in line:
                    continue
                try:
                    rec = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    n_bad += 1
                    continue
                msg = rec.get("message") or {}
                content = msg.get("content")
                ts = rec.get("timestamp") or ""
                if not isinstance(content, list):
                    continue
                for blk in content:
                    if not isinstance(blk, dict) or blk.get("type") != "tool_use":
                        continue
                    name = blk.get("name", "")
                    inp = blk.get("input") or {}
                    if not isinstance(inp, dict):
                        inp = {}
                    tool_totals[name] += 1
                    if name in ("Task", "Agent"):
                        task_spawns += 1
                    path = inp.get("file_path") or inp.get("path") or inp.get("notebook_path")
                    p = norm(path)
                    if not p:
                        continue
                    s = stats[p]
                    s["sessions"].add(sid)
                    if ts:
                        s["first"] = min(s["first"] or ts, ts)
                        s["last"] = max(s["last"] or ts, ts)
                    if name == "Read":
                        s["reads"] += 1
                        if inp.get("limit") or inp.get("offset"):
                            s["partial_reads"] += 1
                        else:
                            s["full_reads"] += 1
                        if ts and ts[:10] >= RECENT_CUTOFF:
                            s["recent_reads"] += 1
                    elif name == "Grep":
                        s["greps"] += 1
                    elif name == "Glob":
                        s["globs"] += 1
                    elif name in ("Edit", "MultiEdit", "NotebookEdit"):
                        s["edits"] += 1
                    elif name == "Write":
                        s["writes"] += 1

    # finalize
    out = {}
    for p, s in stats.items():
        d = dict(s)
        d["sessions"] = len(s["sessions"])
        out[p] = d

    elapsed = time.time() - t0
    named = [
        "claude.md", "build_journal.md", "lessons.md", "field_notes.md",
        "performance_log.md", "docs/test_governance.md", "docs/decision_register.md",
        "docs/implementation_plan.md", "use cases_final.md",
        "docs/sprints/active_sprint.md",
    ]

    def fmt_row(p, d):
        return (f"{d['reads']:5d} rd ({d['full_reads']:4d} full/{d['partial_reads']:4d} part) "
                f"{d['greps']:4d} gr {d['edits']:4d} ed {d['writes']:3d} wr "
                f"{d['sessions']:3d} sess {d['recent_reads']:4d} recent  {p}")

    lines = []
    lines.append(f"parsed {n_files} transcripts, {n_lines} lines, {n_bad} bad, {elapsed:.0f}s")
    lines.append(f"task/agent spawns: {task_spawns}")
    lines.append("")
    lines.append("== tool totals ==")
    for k, v in sorted(tool_totals.items(), key=lambda kv: -kv[1])[:20]:
        lines.append(f"  {v:6d}  {k}")
    lines.append("")
    lines.append("== doctrine-named files ==")
    for p in named:
        d = out.get(p)
        if d:
            lines.append(fmt_row(p, d))
        else:
            lines.append(f"  (no hits) {p}")
    lines.append("")
    lines.append("== top 40 by total reads ==")
    for p, d in sorted(out.items(), key=lambda kv: -kv[1]["reads"])[:40]:
        lines.append(fmt_row(p, d))
    lines.append("")
    lines.append("== top 25 by distinct sessions ==")
    for p, d in sorted(out.items(), key=lambda kv: -kv[1]["sessions"])[:25]:
        lines.append(fmt_row(p, d))
    lines.append("")
    lines.append("== external-path rollup (memory dir / agentic-setup / devplatform) ==")
    for p, d in sorted(out.items(), key=lambda kv: -kv[1]["reads"]):
        if ("/.claude/projects/" in p or "agentic-setup" in p or "devplatform" in p) and d["reads"] >= 3:
            lines.append(fmt_row(p, d))

    txt = "\n".join(lines)
    with open(OUT_TXT, "w", encoding="utf-8") as f:
        f.write(txt)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, sort_keys=True)
    print(txt[:6000])
    print(f"\nwrote {OUT_TXT} and {OUT_JSON}")


if __name__ == "__main__":
    main()
