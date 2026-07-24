"""Rotate a dated append-log's tail into monthly archive volumes + a one-line index.

The standing instrument for the monthly retrospective's rotation step (#945 D1/D5,
LA-approved 2026-07-19). Byte-preserving: entries are moved verbatim, never rewritten.

An entry starts at a line matching '### YYYY-MM-DD'. Everything before the first entry
(the file's preamble) always stays in the hot file. Entries whose month is older than
--keep-month move, in original file order, into <archive-dir>/<YYYY-MM>.md; one index
line per moved entry is inserted into the index file. Entries with unparsable dates
stay hot (safe default, warned).

Usage:
  python tools/doc_hygiene/rotate_log.py --source BUILD_JOURNAL.md \
      --archive-dir docs/archive/journal --index docs/archive/journal/INDEX.md \
      --keep-month 2026-07 [--dry-run]
"""
from __future__ import annotations

import argparse
import io
import os
import re
import sys

ENTRY_RE = re.compile(r"^### (\d{4})-(\d{2})-(\d{2})\b")
SUMMARY_RE = re.compile(r"\*Plain summary:\s*(.+?)\*")

VOLUME_HEADER = """---
title: {title}
status: reference
area: portfolio
---

# {title}

*Archived volume — entries moved verbatim from the hot log by the monthly rotation
(tools/doc_hygiene/rotate_log.py). Never edited after rotation; tallies and corrections
happen in the hot log or as dated addenda there.*

"""

INDEX_HEADER = """---
title: {title}
status: living
area: portfolio
---

# {title}

*One line per archived entry: date | title | plain summary | volume. Newest rotation
batch first. Grep here, then open exactly one volume — never the whole history.*

"""


def parse_entries(text: str) -> tuple[str, list[dict]]:
    lines = text.splitlines(keepends=True)
    entries: list[dict] = []
    preamble_end = None
    current: dict | None = None
    for i, line in enumerate(lines):
        m = ENTRY_RE.match(line)
        if m:
            if preamble_end is None:
                preamble_end = i
            if current is not None:
                current["end"] = i
                entries.append(current)
            current = {
                "start": i,
                "date": f"{m.group(1)}-{m.group(2)}-{m.group(3)}",
                "month": f"{m.group(1)}-{m.group(2)}",
                "header": line.rstrip("\r\n"),
            }
    if current is not None:
        current["end"] = len(lines)
        entries.append(current)
    if preamble_end is None:
        preamble_end = len(lines)
    preamble = "".join(lines[:preamble_end])
    for e in entries:
        e["text"] = "".join(lines[e["start"]:e["end"]])
        title = e["header"][4:]
        title = re.sub(r"^\d{4}-\d{2}-\d{2}\s*[—-]\s*", "", title)
        e["title"] = title.strip()
        head = "".join(lines[e["start"]:min(e["end"], e["start"] + 8)])
        sm = SUMMARY_RE.search(head)
        e["summary"] = (sm.group(1).strip() if sm else "")[:120]
    return preamble, entries


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--archive-dir", required=True)
    ap.add_argument("--index", required=True)
    ap.add_argument("--keep-month", required=True, help="YYYY-MM; entries older than this move")
    ap.add_argument("--index-title", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with io.open(args.source, encoding="utf-8", newline="") as f:
        text = f.read()
    preamble, entries = parse_entries(text)

    hot = [e for e in entries if e["month"] >= args.keep_month]
    cold = [e for e in entries if e["month"] < args.keep_month]
    volumes: dict[str, list[dict]] = {}
    for e in cold:
        volumes.setdefault(e["month"], []).append(e)

    src_bytes = len(text.encode("utf-8"))
    moved_bytes = sum(len(e["text"].encode("utf-8")) for e in cold)
    print(f"source: {args.source}  entries={len(entries)}  bytes={src_bytes:,}")
    print(f"keep >= {args.keep_month}: hot={len(hot)}  cold={len(cold)} "
          f"({moved_bytes:,} bytes) across {len(volumes)} volume(s)")
    for month in sorted(volumes):
        v = volumes[month]
        print(f"  {month}.md  {len(v):4d} entries  first: {v[0]['date']} {v[0]['title'][:50]}")
        print(f"{'':14}  last:  {v[-1]['date']} {v[-1]['title'][:50]}")
    if args.dry_run:
        print("dry-run: no files written")
        return 0

    os.makedirs(args.archive_dir, exist_ok=True)
    for month in sorted(volumes):
        vpath = os.path.join(args.archive_dir, f"{month}.md")
        vtitle = f"{os.path.basename(args.source)} — archive volume {month}"
        exists = os.path.exists(vpath)
        with io.open(vpath, "a", encoding="utf-8", newline="") as f:
            if not exists:
                f.write(VOLUME_HEADER.format(title=vtitle).replace("\n", "\n"))
            for e in volumes[month]:
                f.write(e["text"])

    index_title = args.index_title or f"{os.path.basename(args.source)} — archive index"
    new_lines = "".join(
        f"{e['date']} | {e['title']} | {e['summary']} | {e['month']}.md\n"
        for e in cold
    )
    if os.path.exists(args.index):
        with io.open(args.index, encoding="utf-8", newline="") as f:
            old = f.read()
        parts = old.split("\n\n", 2)
        # insert the new batch after the index header block (frontmatter + intro)
        marker = "never the whole history.*\n\n"
        pos = old.find(marker)
        if pos >= 0:
            insert_at = pos + len(marker)
            merged = old[:insert_at] + new_lines + old[insert_at:]
        else:
            merged = old + "\n" + new_lines
        with io.open(args.index, "w", encoding="utf-8", newline="") as f:
            f.write(merged)
    else:
        with io.open(args.index, "w", encoding="utf-8", newline="") as f:
            f.write(INDEX_HEADER.format(title=index_title) + new_lines)

    hot_text = preamble + "".join(e["text"] for e in hot)
    with io.open(args.source, "w", encoding="utf-8", newline="") as f:
        f.write(hot_text)

    out_bytes = len(hot_text.encode("utf-8"))
    print(f"wrote hot file: {out_bytes:,} bytes ({len(hot)} entries)")
    check = out_bytes + moved_bytes - len(preamble.encode('utf-8')) * 0
    print(f"byte check: hot({out_bytes:,}) + moved({moved_bytes:,}) "
          f"= {out_bytes + moved_bytes:,} vs source {src_bytes:,} "
          f"({'OK' if out_bytes + moved_bytes == src_bytes else 'DIFFERS — investigate'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
