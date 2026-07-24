"""CLI for the coordinator graduation grader (#1079).

    python -m shared.grading --journal <path> --runs-dir <path> [--since-seq N]

Reads. Reports. Writes nothing but the report file it is asked for.

The journal is opened through the sanctioned
:func:`~shared.coordinator.shadow_journal.build_shadow_journal` factory, so a
production journal needs the real ``BLARAI_DEK_KEYSTORE`` in the environment —
the same one-DEK envelope the store was written under. There is no plaintext
path; a missing keystore refuses to start rather than reporting an empty window.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from shared.grading.corpus import CorpusUnavailableError, load_corpus
from shared.grading.coordinator_graduation import (
    GradingReport,
    Provenance,
    grade_window,
)
from shared.grading.run_facts import file_scorecard_reader


def _default_journal_path() -> Path:
    """The production shadow journal, mirroring the heartbeat factory's own
    resolution (``LOCALAPPDATA/BlarAI/coordinator/shadow-journal.db``)."""
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    root = Path(local_app_data) / "BlarAI" if local_app_data else Path("BlarAI")
    return root / "coordinator" / "shadow-journal.db"


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {k: _jsonable(v) for k, v in asdict(value).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    return value


def render_text(report: GradingReport) -> str:
    """The operator-legible rendering — every figure the criteria are stated in."""
    d, w = report.decisions, report.words
    decisions_met, decisions_unmet = d.meets_criteria()
    words_met, words_unmet = w.meets_criteria()
    lines: list[str] = [
        "Coordinator graduation grading - measurement only, nothing flipped.",
        "",
    ]
    p = report.provenance
    if p is not None:
        lines += [
            "SOURCE",
            f"  journal    {p.journal_path}",
            f"  runs-dir   {p.runs_dir}",
            f"  window     since-seq {p.since_seq}"
            + (f" | since {p.since}" if p.since else ""),
            "  journal opened with the DEV sealer - NOT the live store"
            if p.dev_mode
            else "  journal opened via the production factory (live store)",
            "",
        ]
    lines += [
        f"Window: seq {report.window_first_seq}-{report.window_last_seq} "
        f"({report.window_first_at} -> {report.window_last_at})",
        f"Entries graded: {report.journal_entries} "
        + " | ".join(f"{k} {v}" for k, v in report.kind_counts.items()),
        "",
        "DECISIONS LAYER (criteria section 2)",
        f"  decisions observed      {d.distinct_decisions}",
        f"  VERIFIED (the N bar)    {d.graded_decisions}"
        f"  [{d.distinct_decisions - d.graded_decisions} not re-derivable"
        " - not trials]",
        f"  verified correct        {d.correct_decisions}",
        "  precision               "
        + ("n/a" if d.precision is None else f"{d.precision:.4f}"),
        f"  types exercised         {', '.join(d.types_seen) or 'none'}",
        f"  types never exercised   {', '.join(d.types_missing) or 'none'}",
        f"  dominant type (graded)  {d.dominant_type} ({d.dominant_type_count})",
        f"  VERDICT                 {'MET' if decisions_met else 'NOT MET'}",
    ]
    lines += [f"    unmet: {u}" for u in decisions_unmet]
    if d.ungradable:
        lines.append(f"  ungradable ({len(d.ungradable)}):")
        lines += [f"    {g.key} - {g.reason}" for g in d.ungradable]
    incorrect = [g for g in d.grades if g.correct is False]
    if incorrect:
        lines.append("  INCORRECT:")
        lines += [
            f"    {g.key}: journaled {g.observed!r}, re-derived {g.expected!r}"
            for g in incorrect
        ]

    lines += [
        "",
        "WORDS LAYER (criteria section 3)",
        f"  guarded cycles          {w.guarded_cycles}",
        f"  distinct statements     {w.distinct_statements}",
        f"  live false / caught     {w.live_false_statements} / {w.live_false_caught}",
        f"  adversarial / caught    {w.adversarial_cases} / {w.adversarial_caught}",
        "  catch rate (combined)   "
        + ("n/a" if w.catch_rate is None else f"{w.catch_rate:.4f}")
        + f"  over {w.combined_false_instances} false instances",
        f"  false suppressions      {w.false_suppressions} of {w.guarded_cycles} cycles",
        "  false-suppression rate  "
        + (
            "n/a"
            if w.false_suppression_rate is None
            else f"{w.false_suppression_rate:.4f}"
        ),
        f"  undetermined statements {w.undetermined_statements} "
        f"(refused: {w.undetermined_suppressions})",
        f"  guard fingerprint       {w.guard_fingerprint}",
        f"  corpus                  {w.corpus_path} (sha256 {w.corpus_sha256[:16]})",
        f"  VERDICT                 {'MET' if words_met else 'NOT MET'}",
    ]
    lines += [f"    unmet: {u}" for u in words_unmet]
    if w.journaled_action_divergences:
        lines.append(
            "  guard re-run DIVERGES from the journaled action - the window was "
            "drafted under a different guard:"
        )
        lines += [f"    {x}" for x in w.journaled_action_divergences]
    if w.ungradable_statements:
        lines.append(f"  ungradable statements ({len(w.ungradable_statements)}):")
        lines += [f"    {x}" for x in w.ungradable_statements]
    if report.ungradable_runs:
        lines.append(f"  runs without usable scorecards: {', '.join(report.ungradable_runs)}")
    if report.notes:
        lines.append("")
        lines.append("READ THESE FIGURES WITH")
        for note in report.notes:
            lines.append(f"  - {note}")
    return "\n".join(lines)


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m shared.grading",
        description="Grade a coordinator shadow-journal window against the "
        "ratified graduation criteria. Reports only; flips nothing.",
    )
    parser.add_argument(
        "--journal", type=Path, default=None, help="shadow-journal.db path"
    )
    parser.add_argument(
        "--runs-dir",
        type=Path,
        required=True,
        help="fleet-runs directory holding <run_id>/scorecard.json",
    )
    parser.add_argument(
        "--since-seq", type=int, default=0, help="first journal seq in the window"
    )
    parser.add_argument("--since", default=None, help="ISO-8601 window start")
    parser.add_argument(
        "--corpus", type=Path, default=None, help="adversarial corpus JSONL"
    )
    parser.add_argument("--json", type=Path, default=None, help="write JSON here")
    parser.add_argument(
        "--dev-mode",
        action="store_true",
        help="open the journal with the dev SoftwareSealer (test journals only)",
    )
    args = parser.parse_args(argv)

    from shared.coordinator.shadow_journal import build_shadow_journal

    journal_path = args.journal or _default_journal_path()
    try:
        corpus = load_corpus(args.corpus)
    except CorpusUnavailableError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    provenance = Provenance(
        journal_path=str(journal_path),
        runs_dir=str(args.runs_dir),
        since_seq=args.since_seq,
        since=str(args.since or ""),
        dev_mode=bool(args.dev_mode),
    )

    journal = build_shadow_journal(str(journal_path), dev_mode=args.dev_mode)
    try:
        report = grade_window(
            journal,
            read_scorecard=file_scorecard_reader(args.runs_dir),
            corpus=corpus,
            since_seq=args.since_seq,
            since=args.since,
            provenance=provenance,
        )
    finally:
        journal.close()

    print(render_text(report))
    if args.json:
        # The wall-clock instant lives in the ENVELOPE, never inside the report:
        # a timestamp in the report would break the same-window-same-numbers
        # contract the determinism lock asserts.
        envelope = {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "tool": "shared.grading.coordinator_graduation",
            "report": _jsonable(report),
        }
        args.json.write_text(
            json.dumps(envelope, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"\nJSON written: {args.json}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
