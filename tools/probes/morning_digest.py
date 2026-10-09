"""What happened overnight, in plain language, for a non-technical reader.

Why this exists
---------------
There is already a complete scheduled loop for run HEALTH — 23:00 starts the nightly, 23:30
asks whether it started, 03:00 asks whether it is alive, 09:00 asks whether it finished.
Nothing asks **what it produced**, and nothing says so in a sentence the operator can act on.

So every morning the answer to "did it work" has required a session to read half a dozen JSON
files. This writes that answer to disk instead, on a schedule, before anyone asks.

What it is NOT
--------------
**It does not judge, promote, decide or fix.** It reports artifacts and points at the work.
Deciding whether a capability row has been proven is a judgement under capability 11 and needs
a person or an agent session; a scheduled script that promoted rows would be exactly the
absent-evidence-rendered-as-a-confident-value defect this project keeps finding, wearing a
cron entry.

It is also deliberately read-only. It runs unattended, possibly while a dispatch is live, and
anything that writes into the fleet's state from a scheduled task is a collision waiting for a
bad night.

And it reads ONLY from the run's own directory plus the two governing documents, with the run
itself selected by a strict name-shape. Nothing is borrowed from shared pools: an artifact
selected by "latest" from a shared directory can belong to an EARLIER ATTEMPT AT THE SAME GOAL
— the most plausible possible substitute — and this script once cited one as the night's
browser result.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
STATE = Path(os.environ.get("BLARAI_FLEET_STATE_ROOT", r"C:/Users/mrbla/agentic-setup/state"))
RUNS = STATE / "fleet-runs"
DOD = REPO / "docs" / "design" / "CODER_DEFINITION_OF_DONE.md"
ROADMAP = REPO / "docs" / "ROADMAP.md"


# A run id with or without a harness suffix: the pool's first two weeks used the suffix-less
# form (24 such directories remain), so requiring the trailing dash would silently displace a
# suffix-less newest run with an older suffixed one — the substitution defect via the predicate.
_RUN_NAME = re.compile(r"^\d{8}-\d{6}(-|$)")

# Everything markdown could interpret, plus the quote character that would break out of the
# visual quoting. Stripped rather than escaped: the quote is for a human, and '<module>'
# surviving as 'module' is honest while '<module>' swallowed by a renderer is silent deletion.
_MD_ACTIVE = str.maketrans({c: None for c in "`#*_[]<>"} | {'"': "'"})


def _newest_run() -> "Path | None":
    """Only directories shaped like run ids compete. The pool is shared — stray logs and
    archive directories live beside real runs — and max-by-name over everything would let a
    lexically-late stray directory replace the whole night in the digest."""
    if not RUNS.is_dir():
        return None
    ds = [d for d in RUNS.iterdir() if d.is_dir() and _RUN_NAME.match(d.name)]
    return max(ds, key=lambda d: d.name, default=None)


def _quote_evidence(ev: str) -> str:
    """One line, bounded, markdown-inert. Real scorecards have carried 414-char multi-line
    tracebacks with quotes, caret art, links and HTML-shaped tokens in this field; quoting one
    raw into the operator's document would dump a traceback into his morning sentence, let the
    quoted material forge digest structure, or let a renderer silently swallow parts of it.
    The quoted line is the first line that still SAYS something after sanitizing — a fenced
    block's opening ``` sanitizes to nothing, and quoting three apostrophes as the scorecard's
    "why" would be an absence dressed as a value."""
    for raw in ev.splitlines():
        line = raw.translate(_MD_ACTIVE).strip()
        if re.search(r"[A-Za-z0-9]", line):
            if len(line) > 160:
                line = line[:160].rstrip() + "…[truncated]"
            return line
    return ""


def _load(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}


def _plain_verdict(v: str, sc: dict) -> str:
    """The run's own verdict, said the way a person would say it.

    Derived from the scorecard's own counts and its own evidence string — never a fixed
    sentence per verdict. On 2026-08-17 a fixed PARKED-HONEST sentence ("some work did not
    land, and it said so") printed two lines below "7 of 7 pieces of work were merged": the
    verdict names the run's honesty about the JOB, not necessarily about the tasks, and a
    summary that contradicts its own detail is the defect class this whole project fights.
    """
    if not v:
        return "The run left no verdict at all, which usually means it was killed before it finished."
    tasks = sc.get("tasks") or []
    parked = [t for t in tasks if t.get("status") == "parked"]
    ja = sc.get("job_acceptance") or {}
    job = str(ja.get("status", ""))
    table = {
        "GREEN": "It finished and everything it checked passed.",
        "PARKED-HONEST": "It finished and did NOT claim success.",
        "STALLED": "The run itself is not trustworthy: it could not be scored. This is not a judgement about the code.",
        "RED": "It finished and something it checked failed.",
    }
    line = table.get(v, f"Its verdict was {v!r}.")
    if v == "PARKED-HONEST":
        ev = _quote_evidence(str(ja.get("evidence", "")))
        if parked:
            # The COMMON shape (parked work AND an evidence string) gets the why too —
            # dropping it here while quoting it in the rarer no-parked shape would starve
            # the usual morning of the one explanatory sentence the scorecard offers.
            line += f" {len(parked)} piece(s) of work did not land, and it said so."
            if ev:
                line += f' Its own record says why: "{ev}".'
        elif ev:
            line += f' Its own record says why: "{ev}".'
        else:
            line += " No task was parked; the run withheld the claim of success rather than assert it."
    if job in ("not-run", "pending", ""):
        line += (" There is NO overall grade for the job — that is an honest blank, not a failure,"
                 " and it means nothing downstream can be scored from this run.")
    return line


def build() -> str:
    now = datetime.now().astimezone()
    out: list[str] = [
        f"# Overnight digest — {now:%A %d %B %Y, %H:%M}",
        "",
        "*Written automatically. It reports what is on disk; it decides nothing.*",
        "",
    ]

    run = _newest_run()
    if run is None:
        out += ["## No runs found at all", "",
                f"Nothing under `{RUNS}`. Either the machine has never run the coder, or the",
                "state directory moved.", ""]
        return "\n".join(out)

    sc = _load(run / "scorecard.json")
    finished = bool(sc)
    tasks = sc.get("tasks") or []
    merged = [t for t in tasks if t.get("status") == "merged"]
    parked = [t for t in tasks if t.get("status") == "parked"]
    skipped = [t for t in tasks if t.get("status") == "skipped"]

    out += [f"## The most recent run: `{run.name}`", ""]
    if not finished:
        out += ["**It has not finished.** There is no scorecard yet, so either it is still",
                "working or it stopped without writing one. The 3am and 9am checks cover that;",
                "this digest does not duplicate them.", ""]
    else:
        hours = float(sc.get("wall_clock_s") or 0) / 3600.0
        out += [
            f"**{len(merged)} of {len(tasks)} pieces of work were merged into your project.**",
            f"{len(parked)} parked (saved but not merged), {len(skipped)} skipped.",
            "",
            _plain_verdict(str(sc.get("verdict", "")), sc),
            "",
            f"It ran for about {hours:.1f} hours.",
            "",
        ]
        if parked:
            out += ["Parked work — saved on a branch, not lost:"]
            out += [f"  - {t.get('id')}" for t in parked]
            out += [""]

    # What evidence it banked. Presence only -- what it MEANS is a judgement.
    out += ["## What it measured", "",
            "Each line is an artifact that either exists or does not. Whether it proves anything",
            "is a judgement for a session, not for this script.", ""]
    checks = [
        ("link-lint.json", "checked the links on the built site"),
        ("exec-smoke-web.png", "opened the site in a real browser"),
        ("green-quality.json", "scanned the delivered code for quality and security"),
        ("oracle-qa.json", "graded the exam the coder was given"),
        ("decompose-diagnostics.json", "recorded how the job was broken into pieces"),
        ("scorecard.json", "wrote a final scorecard"),
    ]
    for fname, human in checks:
        mark = "yes" if (run / fname).exists() else "NO "
        out.append(f"  [{mark}] {human}")
    out.append("")

    # Anything the browser found is the one thing worth surfacing verbatim — from THIS run's
    # OWN capture, never from anywhere else. This section once preferred "the latest critique
    # capture" via an unscoped glob over the shared reports pool, and on 2026-08-17 that made
    # it answer for last night with a nine-day-old capture from an earlier run of the SAME
    # goal — "no page errors" while the run's own sidecar read errorCount: 1. And even a
    # correctly-scoped fix-cycle capture describes a CANDIDATE the verify gate may have
    # discarded: the delivered
    # tree is the only witness that a fix landed (commit 32bed3fb). So: the run's own capture,
    # labeled as the moment it is, with the caveat that decides what it can and cannot prove.
    console = run / "exec-smoke-web.png.console.json"
    if console.exists():
        c = _load(console)
        errs = c.get("pageErrors") or []
        if errs:
            out += ["### The browser saw problems when it opened the site", ""]
            shown = errs[:5]
            for e in shown:
                where = str(e.get("url", "")).rsplit("/", 1)[-1]
                out.append(f"  - {str(e.get('text',''))[:110]}  ({where})")
            if len(errs) > len(shown):
                out.append(f"  - …and {len(errs) - len(shown)} more not shown here")
            out += ["",
                    "*Seen at capture time, which is BEFORE any fix cycle. A later fix pass may",
                    "have repaired one of these — or been discarded by the verify gate. Only the",
                    "delivered site itself can tell those apart; a session can check it in minutes.*",
                    ""]
        else:
            out += [f"The browser opened the site and saw no page errors in this run's own "
                    f"capture (`{console.name}`).", ""]

    # Where the project stands, read from the documents rather than remembered.
    if DOD.is_file():
        text = DOD.read_text(encoding="utf-8", errors="replace")
        rows = re.findall(r"^### (\d+)\.", text, re.M)
        live = len(re.findall(r"^\*\*Status:\s*LIVE", text, re.M))
        out += ["## Where the project stands", "",
                f"**{live} of {len(rows)} capabilities are proven (LIVE).** That figure moves only",
                "when a run has executed a capability's own test and someone has cited it.", ""]

    if ROADMAP.is_file():
        block = re.search(r"```roadmap\n(.*?)\n```", ROADMAP.read_text(encoding="utf-8", errors="replace"), re.S)
        if block:
            first = [ln for ln in block.group(1).splitlines()
                     if ln.strip() and not ln.strip().startswith("#")]
            if first:
                parts = [p.strip() for p in first[0].split("|")]
                if len(parts) >= 5:
                    out += [f"**Next thing to work on: {parts[1]}** — {parts[4]}",
                            f"*(needs you: {parts[3]})*", ""]

    out += ["## What to do with this", "",
            "Start a session and say: *read the overnight digest, then follow the dod-witness agent.*",
            "",
            "If anything above says a check did NOT run, that is usually worth more attention than",
            "a check that ran and passed — a measurement that never happened and one that found",
            "nothing look identical in every summary except this line.", ""]
    return "\n".join(out)


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path,
                    default=REPO / "docs" / "handoffs" / "OVERNIGHT_DIGEST.md",
                    help="where to write it (default: docs/handoffs/OVERNIGHT_DIGEST.md)")
    ap.add_argument("--stdout", action="store_true", help="print instead of writing")
    args = ap.parse_args(argv)

    text = build()
    if args.stdout:
        print(text)
        return 0
    try:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote {args.out}")
    except OSError as exc:
        print(f"could not write the digest: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
