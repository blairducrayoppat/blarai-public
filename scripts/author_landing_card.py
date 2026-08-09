"""
BlarAI landing-card assembler
=============================
Authoring aid for the landing-card handoff discipline (``CLAUDE.md``
``<context_handoff>`` / ``<event_time_banking>``, LA-ratified 2026-07-28,
#1144).

Generates a draft landing card with the volatile half filled in by machine:
dated ``landing-card-v1`` frontmatter, a stamped "Machine state" section
derived from the live repository and process table, and a pre-filled
```anchors block whose values are REAL (current main HEAD, existing paths,
an executed fragment count) rather than placeholders. The author writes the
judgment half — Objective, Deltas, Next step, Pointers, Retractions & dead
ends — and the card stays within the machine-enforced budget
(<=150 lines / <=8 KB, ``scripts/verify_handoff_brief.py``).

Fail-soft by design: a probe that cannot run (no PowerShell, no git) emits
an explicit "UNAVAILABLE - fill by hand" line rather than dying, because
authoring a card must never be blocked by a broken probe; the verifier's
staleness warning still surfaces a hand-edited or stale machine-state block.

The output path refuses to overwrite an existing card: ``docs/handoffs/`` is
gitignored, so an overwrite there is unrecoverable — the one place in this
repo where a clobber has no history to restore from.

Usage (from repo root, or anywhere with ``--repo``):
  python scripts/author_landing_card.py --topic dispatch-corridor
  python scripts/author_landing_card.py --topic t --stdout
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
import sys
from pathlib import Path

_PROBE_TIMEOUT_S = 20
_UNAVAILABLE = "UNAVAILABLE - fill by hand"

# Process command-lines that matter to a successor: the app, an in-flight
# dispatch/swap, a battery run. Anything else is noise (MCP servers etc.).
_PROCESS_PATTERN = "launcher|swap_ops|run.fleet|battery"


def _run(argv: list[str], cwd: Path | None = None) -> str | None:
    """Run a probe command; None on any failure (fail-soft, never raises)."""
    try:
        proc = subprocess.run(
            argv, cwd=str(cwd) if cwd else None, capture_output=True,
            text=True, errors="replace", timeout=_PROBE_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def _git(repo: Path, *args: str) -> str | None:
    return _run(["git", "-C", str(repo), *args])


def _process_lines() -> list[str]:
    """Live BlarAI-relevant processes via PowerShell; [] if none, or a
    single UNAVAILABLE line if the probe itself cannot run."""
    script = (
        "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe' or "
        "Name='python.exe'\" | Where-Object { $_.CommandLine -match "
        f"'{_PROCESS_PATTERN}' }} | ForEach-Object {{ \"$($_.ProcessId) "
        "$($_.CommandLine)\" }"
    )
    out = _run(["powershell", "-NoProfile", "-Command", script])
    if out is None:
        return [f"- live processes: {_UNAVAILABLE}"]
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    if not lines:
        return ["- live processes: none matching app/dispatch/battery"]
    shown = [f"- live process: {ln[:110]}" for ln in lines[:10]]
    if len(lines) > 10:
        shown.append(f"  ... and {len(lines) - 10} more")
    return shown


def _scheduled_task_lines() -> list[str]:
    script = (
        "Get-ScheduledTask | Where-Object { $_.TaskName -match 'blar|battery' } "
        "| ForEach-Object { \"$($_.TaskName) [$($_.State)]\" }"
    )
    out = _run(["powershell", "-NoProfile", "-Command", script])
    if out is None:
        return [f"- scheduled tasks: {_UNAVAILABLE}"]
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    if not lines:
        return ["- scheduled tasks: none matching blar|battery"]
    return [f"- scheduled task: {ln}" for ln in lines]


def _dirty_lines(repo: Path) -> list[str]:
    out = _git(repo, "status", "--porcelain")
    if out is None:
        return [f"- working tree: {_UNAVAILABLE}"]
    entries = [ln for ln in out.splitlines() if ln.strip()]
    tracked = [e for e in entries if not e.startswith("??")]
    untracked = len(entries) - len(tracked)
    lines = [f"- dirty tracked files ({len(tracked)}; whose? mark before merge):"]
    lines += [f"  {e.strip()[:100]}" for e in tracked[:8]]
    if len(tracked) > 8:
        lines.append(f"  ... and {len(tracked) - 8} more")
    lines.append(f"- untracked files: {untracked} (likely other sessions' work - do not stage)")
    return lines


def _fragment_count(repo: Path) -> str:
    frag_dir = repo / "docs" / "journal_fragments"
    try:
        n = sum(
            1 for p in frag_dir.glob("*.md") if p.name.lower() != "readme.md"
        )
    except OSError:
        return "0"
    return str(n)


def _slug_ok(topic: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,60}", topic))


def build_card(topic: str, repo: Path, now: dt.datetime) -> str:
    """Assemble the draft card text (pure given its probe results)."""
    date = now.date().isoformat()
    stamp = now.astimezone().replace(microsecond=0).isoformat()
    head = _git(repo, "rev-parse", "main") or _UNAVAILABLE
    branch = _git(repo, "branch", "--show-current") or _UNAVAILABLE
    frags = _fragment_count(repo)

    machine: list[str] = [
        f"<!-- machine-state generated {stamp} by author_landing_card.py -->",
        f"- branch: {branch} @ {(_git(repo, 'rev-parse', 'HEAD') or _UNAVAILABLE)[:12]}",
        f"- main HEAD: {head[:12]}",
        *_dirty_lines(repo),
        *_process_lines(),
        *_scheduled_task_lines(),
        "- unreviewed work (author!=verifier - successor must not self-certify): <EDIT: branches/commits authored this session still lacking independent review, or \"none\">",
        "- Claude-side agents (not OS-visible; kill or hand over deliberately): <EDIT: running/owed agents + what each owes, or \"none\">",
        "- external: nothing posted externally this session <EDIT if false>",
    ]

    return "\n".join(
        [
            "---",
            "artifact_type: handoff-brief",
            "template: landing-card-v1",
            "target_session: fresh Claude Code session, this repo",
            f"predecessor_session_anchor: {head[:12]}",
            "status: HANDOFF",
            f"date: {date}",
            "---",
            "",
            f"# Landing card - {topic}",
            "",
            "## SUCCESSOR: START HERE",
            "",
            "1. Read the Pointers below — ground on live disk/Vikunja, never on this card.",
            f"2. Verify: `python scripts/verify_handoff_brief.py docs/handoffs/{topic}-landing-{date.replace('-', '')}.md`",
            "3. Gate to the User-Operator (FULL for a new engagement / DELTA for a continuation) and WAIT.",
            "4. Ops surface: `docs/governance/session-ops-surface.md` — cite, never paste.",
            "",
            "## Objective   (<=3 lines)",
            "",
            "<EDIT: the arc + why the User-Operator wants it>",
            "",
            "## Deltas   (<=15 lines; one pointer-line each)",
            "",
            "<EDIT: merges (SHA + clause) · board moves incl. tickets your ship unblocked · flips DORMANT-vs-LIVE>",
            "",
            "## Machine state   (<=25 lines - autogenerated; verifier warns when stamp is >1 h older than the file)",
            "",
            *machine,
            "",
            "## Next step   (<=3 lines - singular and concrete)",
            "",
            "<EDIT: the one thing to do first, and how to know it worked>",
            "",
            "## Pointers   (<=10 lines)",
            "",
            "- Vikunja is the SSOT — run `project_summary`, read ticket DESCRIPTIONS, re-judge priorities.",
            "<EDIT: <=6 topic reads, each with why>",
            "",
            "## Retractions & dead ends   (pointer-form only; \"none\" is valid)",
            "",
            "<EDIT: banked at #NNN (comment, date) — or \"none\">",
            "",
            "## Reference SHAs + anchors",
            "",
            "```anchors",
            "# type   | value                                    | label                              | derivation (count rows only)",
            f"sha      | {head if head != _UNAVAILABLE else 'FILL'}     | predecessor_session_anchor",
            "path     | docs/governance/session-ops-surface.md   | ops surface (cite, never paste)",
            "path     | docs/TEST_GOVERNANCE.md                  | live gate SSOT",
            f"count    | {frags}                                        | journal fragments awaiting fold    | find docs/journal_fragments -maxdepth 1 -iname '*.md' ! -iname 'readme.md' | wc -l",
            "```",
            "",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Assemble a draft landing card with the machine-state half pre-filled."
    )
    parser.add_argument("--topic", required=True, help="kebab-case slug for the card")
    parser.add_argument("--repo", default=".", help="repo root (default: cwd)")
    parser.add_argument(
        "--stdout", action="store_true",
        help="print the draft instead of writing docs/handoffs/",
    )
    args = parser.parse_args(argv)

    if not _slug_ok(args.topic):
        print(f"error: topic must be kebab-case (got {args.topic!r})", file=sys.stderr)
        return 2
    repo = Path(args.repo).resolve()
    now = dt.datetime.now()
    card = build_card(args.topic, repo, now)

    if args.stdout:
        # Windows consoles default to cp1252; never let an encoding kill the
        # draft (live-caught 2026-07-28: U+2264 in the skeleton did exactly that).
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(errors="replace")
        print(card)
        return 0

    out_dir = repo / "docs" / "handoffs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{args.topic}-landing-{now.date().isoformat().replace('-', '')}.md"
    if out_path.exists():
        print(
            f"error: {out_path} already exists - this directory is gitignored, an "
            "overwrite is unrecoverable; pick a new topic slug",
            file=sys.stderr,
        )
        return 2
    out_path.write_text(card, encoding="utf-8")
    print(f"draft landing card written: {out_path}")
    print("fill every <EDIT> marker, then run the verifier before handing off")
    return 0


if __name__ == "__main__":
    sys.exit(main())
