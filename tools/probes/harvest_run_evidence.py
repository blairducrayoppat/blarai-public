"""Read one coder run's banked record and report what it can and cannot WITNESS.

Why this exists
---------------
``docs/design/CODER_DEFINITION_OF_DONE.md`` capability 11 makes a run the only thing
that moves a row: a capability is LIVE only when its own observable has been executed
end to end at least once, **with the run cited**. Code being written never counts.

So after every run somebody has to answer "which rows did this actually exercise?" --
and doing that by hand is how a row gets promoted on an observable the run never
touched. That mistake has a record here: capability 2 read LIVE for a week on the
strength of nine ``true`` flags while its observable had never once happened.

This script reads the banked artifacts and reports the fields the rows are defined
against. It deliberately does NOT decide whether a row moves. It reports evidence;
the promotion decision stays with a person who can weigh whether the observable was
genuinely executed.

What it refuses to do
---------------------
It never reports a zero it did not measure. Every field resolves to one of three
states -- a value, ``ABSENT`` (the artifact is not there), or ``UNREADABLE`` (it is
there and did not parse) -- because "the check ran and found nothing" and "the check
did not run" are different facts, and collapsing them is the exact defect capability 7
exists to prevent.

Usage
-----
    python tools/probes/harvest_run_evidence.py                  # newest run
    python tools/probes/harvest_run_evidence.py <run-id>         # a named run
    python tools/probes/harvest_run_evidence.py --json           # machine-readable
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# The fleet's banked state. Overridable so this can be pointed at an archive.
DEFAULT_STATE_ROOT = Path(
    os.environ.get("BLARAI_FLEET_STATE_ROOT", r"C:/Users/mrbla/agentic-setup/state")
)

ABSENT = "ABSENT"
UNREADABLE = "UNREADABLE"


@dataclass
class Evidence:
    """One observable field, and an honest account of whether it was measured."""

    label: str
    value: Any
    source: str
    rows: tuple[int, ...]
    note: str = ""

    @property
    def measured(self) -> bool:
        return self.value not in (ABSENT, UNREADABLE)


@dataclass
class Harvest:
    run_id: str
    run_dir: Path
    items: list[Evidence] = field(default_factory=list)

    def add(
        self,
        label: str,
        value: Any,
        source: str,
        rows: tuple[int, ...],
        note: str = "",
    ) -> None:
        self.items.append(Evidence(label, value, source, rows, note))


def _read_json(path: Path) -> Any:
    """Return parsed JSON, ABSENT if the file is not there, UNREADABLE if it will not parse.

    The three-way return is the whole point: a caller must not be able to confuse a
    missing artifact with an artifact recording nothing.
    """
    if not path.is_file():
        return ABSENT
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return UNREADABLE


def _dig(blob: Any, *keys: str) -> Any:
    """Walk nested dict keys, preserving ABSENT/UNREADABLE sentinels."""
    if blob in (ABSENT, UNREADABLE):
        return blob
    cur = blob
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return ABSENT
        cur = cur[key]
    return cur


def newest_run(state_root: Path) -> Path | None:
    runs = state_root / "fleet-runs"
    if not runs.is_dir():
        return None
    candidates = [
        d for d in runs.iterdir() if d.is_dir() and not d.name.endswith("-flakererun")
    ]
    return max(candidates, key=lambda d: d.name, default=None)


def harvest(run_dir: Path, state_root: Path) -> Harvest:
    out = Harvest(run_id=run_dir.name, run_dir=run_dir)

    # --- Row 4 / 7: can the exam fail, and does every grader say when it did not run?
    qa = _read_json(run_dir / "oracle-qa.json")
    out.add("exam quality verdict", _dig(qa, "verdict"), "oracle-qa.json", (4, 12, 13))
    out.add(
        "fail-to-pass baseline",
        _dig(qa, "f2p_baseline"),
        "oracle-qa.json",
        (4,),
        "'not-run' means the strongest check this row owns produced nothing.",
    )
    out.add("collectability", _dig(qa, "collectability"), "oracle-qa.json", (7,))
    out.add("findings conclusive", _dig(qa, "findings_conclusive"), "oracle-qa.json", (7, 13))
    out.add("findings total", _dig(qa, "findings_total"), "oracle-qa.json", (4, 13))

    # --- Row 3 / 13: was the delivery graded, and did the security scan actually run?
    # NOTE the filename is not guaranteed present: recent runs do not emit one at the
    # run root at all. That is reported as ABSENT rather than as a clean grade, which
    # is the distinction row 3 turns on.
    gq = _read_json(run_dir / "green-quality.json")
    out.add("quality band", _dig(gq, "band"), "green-quality.json", (3, 12))
    out.add("security clean", _dig(gq, "security", "clean"), "green-quality.json", (3,))
    out.add(
        "security worst severity",
        _dig(gq, "security", "worst_severity"),
        "green-quality.json",
        (3,),
    )

    # --- Row 2: did the operator's own words reach the record, and were assets consumed?
    # Field names verified against a real record 2026-08-15: acceptance.json has exactly
    # two top-level keys, `repo` and `spec`; the asset field is `asset_specs`. Reading
    # the wrong nesting level here has produced a wrong number in this project before,
    # which is why the paths below were confirmed against disk rather than assumed.
    acc = _read_json(run_dir / "acceptance.json")
    clarifications = _dig(acc, "spec", "clarifications")
    out.add(
        "clarifications recorded",
        len(clarifications) if isinstance(clarifications, list) else clarifications,
        "acceptance.json:spec.clarifications",
        (2, 17),
        "Presence is the interview being POSSIBLE; a non-empty list is it happening.",
    )
    # These two are NEAR-OPPOSITES and must never be conflated. `asset_specs` holds
    # image prompts the SYSTEM invented for the coder to generate ("a cozy pottery
    # studio with shelves of handmade ceramics"). `operator_assets` would hold the
    # operator's OWN supplied material. An earlier draft of this file reported the
    # former under the latter's label and would have shown 8 where the true answer for
    # his material is 0 -- turning the M2 gap into an apparent success.
    spec_assets = _dig(acc, "spec", "asset_specs")
    out.add(
        "system-invented asset specs",
        len(spec_assets) if isinstance(spec_assets, list) else spec_assets,
        "acceptance.json:spec.asset_specs",
        (10, 18),
        "Content the system decided the site should have. NOT the operator's material.",
    )
    operator_assets = _dig(acc, "spec", "operator_assets")
    out.add(
        "OPERATOR's own assets used",
        len(operator_assets) if isinstance(operator_assets, list) else operator_assets,
        "acceptance.json:spec.operator_assets",
        (2, 10, 18),
        "Measured 2026-08-15: the key appears in 0 of 225 acceptance records corpus-wide, "
        "so ABSENT here is the norm rather than a per-run miss. This is the M2 gap: 29 of "
        "his photographs sit in a project that nothing has ever read.",
    )

    # --- Row 20: was the plan silently truncated at the 8-task cap?
    dd = _read_json(run_dir / "decompose-diagnostics.json")
    out.add("tasks authored", _dig(dd, "cleaned_task_count"), "decompose-diagnostics.json", (20,))
    out.add(
        "plan degraded",
        _dig(dd, "degraded"),
        "decompose-diagnostics.json",
        (20,),
        "DEFAULT_MAX_TASKS=8 truncates silently above the cap (#1279).",
    )

    # --- Row 15: was the built product EXERCISED, not just inspected?
    # `checked` is read FIRST and deliberately: the counts below are meaningless if the
    # linter never ran, and a `broken: 0` from a scan that did not happen is precisely
    # the "count from an unrun check" defect row 7 names.
    ll = _read_json(run_dir / "link-lint.json")
    out.add(
        "link check ran",
        _dig(ll, "checked"),
        "link-lint.json:checked",
        (15,),
        "If this is not True, every count below it is a floor, not a result.",
    )
    out.add("broken links", _dig(ll, "counts", "broken"), "link-lint.json:counts.broken", (15,))
    out.add(
        "links resolved",
        _dig(ll, "counts", "resolved"),
        "link-lint.json:counts.resolved",
        (15,),
    )
    out.add("links examined", _dig(ll, "references"), "link-lint.json:references", (15,))
    out.add(
        "browser smoke captured",
        (run_dir / "exec-smoke-web.png").is_file(),
        "exec-smoke-web.png",
        (15,),
    )

    # --- Row 15, the "forms submit" clause (#1433).
    #
    # Until 2026-08-16 nothing in this repository parsed the web sidecar at all -- row 15's
    # browser evidence was banked as the line directly above, an existence check on a PNG. The
    # richest artifact a web run produces was being reported as "the file is there".
    #
    # PATHS VERIFIED AGAINST A REAL RECORD before this was written, per the wrong-nesting lesson
    # recorded further down this file: `forms` is a TOP-LEVEL key of
    # `exec-smoke-web.png.console.json`, not nested under `pages` or `smoke`.
    #
    # An old-shape sidecar -- every one banked before 2026-08-16 -- has `forms.formCount` but no
    # `pagesChecked`. That reads as `None` here, which `out.add` renders as NOT MEASURED. It must
    # never render as zero pages checked: "this instrument predates the fix" and "this run
    # checked nothing" are different facts, and only the second is a defect in the run.
    cs = _read_json(run_dir / "exec-smoke-web.png.console.json")
    out.add(
        "forms check ran",
        _dig(cs, "forms", "measured"),
        "exec-smoke-web.png.console.json:forms.measured",
        (15,),
        "If this is not True, the form counts below are absent, not zero.",
    )
    out.add(
        "pages checked for forms",
        _dig(cs, "forms", "pagesChecked"),
        "exec-smoke-web.png.console.json:forms.pagesChecked",
        (15,),
        "Absent on any run before 2026-08-16, when the check saw only the entry page (#1433).",
    )
    out.add(
        "forms found",
        _dig(cs, "forms", "formCount"),
        "exec-smoke-web.png.console.json:forms.formCount",
        (15,),
        "A site-wide total only where pagesChecked is present; an entry-page count before that.",
    )
    # Written as an explicit None-or-count rather than an `and`/`or` chain: a genuine zero is
    # falsy, so the compact form would have rendered "nothing was undecidable" -- the best
    # possible result -- as "not measured". That is the absence-as-a-value defect this whole
    # probe exists to refuse, and it very nearly shipped inside the fix for it.
    # ABSENT, not None: this file's own standing lock (test_absent_artifacts_never_render_as_zero)
    # requires every field to use the module sentinel so a missing artifact cannot be mistaken for
    # a measurement -- and it caught this field returning a bare None the first time it ran.
    undecidable: int | str = ABSENT
    pages = _dig(cs, "pages")
    if isinstance(pages, list):
        counted = [p for p in pages if isinstance((p or {}).get("forms"), dict)]
        if counted:
            undecidable = sum(
                int(p["forms"].get("loseDataUndecidable") or 0) for p in counted
            )
    out.add(
        "forms undecidable",
        undecidable,
        "exec-smoke-web.png.console.json:pages[].forms.loseDataUndecidable",
        (15,),
        "Forms whose submit path could not be decided: addEventListener is invisible to the probe.",
    )

    # --- Row 7 / 12 / 21: the run's own verdict, and whether it discloses what it skipped.
    # Paths verified against a real record 2026-08-15: there is no top-level
    # `oracle_status` or `failure_class`. The grade lives under `job_acceptance.status`
    # and the failure class under `attribution`. An earlier draft of this file read the
    # top level, found nothing, and would have reported the strongest available evidence
    # as ABSENT -- the same shape as the wrong-nesting error recorded on DoD row 2.
    sc = _read_json(run_dir / "scorecard.json")
    out.add("run verdict", _dig(sc, "verdict"), "scorecard.json:verdict", (12, 14, 21))
    out.add(
        "job grade",
        _dig(sc, "job_acceptance", "status"),
        "scorecard.json:job_acceptance.status",
        (4, 12, 14, 17, 21),
        "This is the denominator every end-of-run instrument divides by.",
    )
    out.add(
        "failure attribution",
        _dig(sc, "attribution"),
        "scorecard.json:attribution",
        (7, 21),
    )
    not_measured = _dig(sc, "not_measured")
    out.add(
        "declared not-measured",
        not_measured,
        "scorecard.json:not_measured",
        (7, 13),
        "The honest-disclosure field: what the run says it did NOT check.",
    )

    return out


def research_lookups(state_root: Path, run_id: str) -> Evidence:
    """Row 6's observable: a `search_docs_cli` record whose caller is a CODER.

    Armed and instructed since 2026-08-08 with zero coder lookups ever recorded, so
    the first one is a genuine state change rather than a number ticking up.
    """
    ledger = state_root / "research-usage.jsonl"
    if not ledger.is_file():
        return Evidence("coder doc lookups", ABSENT, "research-usage.jsonl", (6,))
    total = 0
    by_caller: dict[str, int] = {}
    try:
        with ledger.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                total += 1
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # Field name verified against the live ledger 2026-08-15: records carry
                # `caller`, e.g. "plan_grounding" or "search_docs_cli". An earlier draft
                # looked for `kind`/`tool` and reported a confident 0 over 1,990 records
                # that plainly contain matches -- a zero from a check that could not fire.
                caller = str(rec.get("caller", "unknown"))
                by_caller[caller] = by_caller.get(caller, 0) + 1
    except OSError:
        return Evidence("coder doc lookups", UNREADABLE, "research-usage.jsonl", (6,))
    return Evidence(
        "coder doc lookups",
        {"ledger_records": total, "by_caller": by_caller},
        "research-usage.jsonl:caller",
        (6,),
        "Baseline 2026-08-14: 1,990 records, of which 1,986 plan_grounding (stood down) "
        "and 4 search_docs_cli, ALL developer probes. Row 6's observable is a "
        "search_docs_cli record whose caller is a CODER inside a dispatch -- so a rise "
        "in the count is necessary but not sufficient; provenance still has to be checked.",
    )


def _goal_sha(run: Path) -> Any:
    """SHA-256 prefix of a run's goal text, or a sentinel. The GROUPING KEY."""
    acc = _read_json(run / "acceptance.json")
    goal = _dig(acc, "spec", "goal")
    if isinstance(goal, str) and goal:
        import hashlib

        return hashlib.sha256(goal.encode("utf-8")).hexdigest()[:16]
    return ABSENT


def _run_ended(run: Path) -> bool:
    """Did this run REACH ITS END? Two independent markers, either sufficient.

    Without this the classifier cannot tell a finished run that produced no verdict
    from one still executing -- and those are opposite facts. The first is the worst
    outcome a grader can have; the second is not an outcome at all.
    """
    if (run / "SUMMARY.txt").is_file():
        return True
    journal = run / "journal.log"
    if journal.is_file():
        try:
            return "RUN-END" in journal.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False
    return False


def _fate(run: Path) -> str:
    """Why a run has no verdict. These are OUTCOMES, not gaps in the data.

    ``reaped`` must never be silently dropped: an unclean shutdown leaves a full
    multi-task attempt whose journal the reaper RENAMES, so any rule keyed on
    ``journal.log`` cannot see it.

    ``finished-no-verdict`` is the bucket this classifier originally lacked, and its
    absence was the same defect the probe exists to catch. Without an end-of-run test
    every verdict-less run fell through to ``in-flight-or-unfinished`` -- so two runs
    that had FINISHED and produced nothing read as "not done yet, no conclusion
    available", which is a denominator quietly excluding its own worst failures.
    Caught by an independent verifier on 2026-08-15, hours after I shipped the fix
    for that exact shape.
    """
    if (run / "scorecard.json").is_file():
        return "verdict"
    if any(run.glob("journal.log.reaped-*")):
        return "reaped"
    # A run that died at launch writes essentially nothing. Threshold is generous:
    # the observed died-at-launch runs carry exactly 2 files, real attempts 30+.
    if len([p for p in run.iterdir() if p.is_file()]) <= 5:
        return "died-at-launch"
    if not (run / "journal.log").is_file():
        return "no-journal"
    if _run_ended(run):
        return "finished-no-verdict"
    return "in-flight"


def verdict_distribution(state_root: Path, goal_sha: str) -> dict[str, Any]:
    """Terminal-verdict distribution across every run of one GOAL.

    Serves DoD row 21 ("verdicts are stable"). That row previously declined to
    re-derive its own distribution on the grounds that "the verdict is not in
    acceptance.json" -- true, and incomplete: it is in ``scorecard.json``.

    THE GROUPING KEY IS THE GOAL, AND THAT IS THE WHOLE POINT.
    Row 21's predecessor reported "eight runs" without stating a selection, and two
    other counts fit the same words. The first fix keyed on ``journal.log`` naming
    the repo -- which is WORSE THAN UNSTATED, because it is biased in the direction
    of the thing being measured: an unclean shutdown makes the reaper RENAME
    ``journal.log`` to ``journal.log.reaped-<date>``, so a full seven-task attempt
    that died near the end becomes invisible to the very tally counting instability.
    Measured: that rule found 2 verdict-less runs where the goal-keyed rule finds 9.

    Keying on the goal conditions on the INPUT, which is fixed by construction and
    cannot be correlated with the outcome. Runs without a verdict are classified by
    FATE rather than pooled, so "died at launch" is not counted against a grader.
    """
    runs_dir = state_root / "fleet-runs"
    matched: list[dict[str, Any]] = []
    if not runs_dir.is_dir():
        return {"grouping_rule": goal_sha, "runs": [], "error": ABSENT}

    for run in sorted(d for d in runs_dir.iterdir() if d.is_dir()):
        if _goal_sha(run) != goal_sha:
            continue

        sc = _read_json(run / "scorecard.json")
        fate = _fate(run)
        if sc is UNREADABLE:
            verdict = UNREADABLE
        elif sc is ABSENT:
            verdict = f"NO-VERDICT:{fate}"
        else:
            verdict = _dig(sc, "verdict")

        journal = run / "journal.log"
        journal_state = "present" if journal.is_file() else fate

        matched.append(
            {
                "run": run.name,
                "verdict": verdict,
                "fate": fate,
                "job_grade": _dig(sc, "job_acceptance", "status"),
                "attribution": _dig(sc, "attribution"),
                "journal": journal_state,
                "files": len([p for p in run.iterdir() if p.is_file()]),
            }
        )

    counts: dict[str, int] = {}
    fates: dict[str, int] = {}
    for row in matched:
        key = str(row["verdict"])
        counts[key] = counts.get(key, 0) + 1
        fates[str(row["fate"])] = fates.get(str(row["fate"]), 0) + 1

    return {
        "grouping_rule": (
            f"every run whose acceptance.json spec.goal hashes to {goal_sha!r} "
            "(keyed on the INPUT, so selection cannot correlate with the outcome)"
        ),
        "goal_sha256_16": goal_sha,
        "matched": len(matched),
        "runs": matched,
        "verdict_counts": counts,
        "fate_counts": fates,
    }


def goals_seen(state_root: Path) -> dict[str, int]:
    """Every distinct goal hash on disk, so a caller can pick a grouping key."""
    runs_dir = state_root / "fleet-runs"
    out: dict[str, int] = {}
    if not runs_dir.is_dir():
        return out
    for run in sorted(d for d in runs_dir.iterdir() if d.is_dir()):
        key = str(_goal_sha(run))
        out[key] = out.get(key, 0) + 1
    return out


def render_distribution(dist: dict[str, Any]) -> str:
    lines = [f"GROUPING RULE: {dist['grouping_rule']}", f"RUNS MATCHED: {dist['matched']}", ""]
    if dist["runs"]:
        w = max(len(str(r["run"])) for r in dist["runs"])
        lines.append(
            f"{'run'.ljust(w)}  {'verdict'.ljust(28)}  {'job_grade'.ljust(10)}  "
            f"{'journal'.ljust(16)}  files"
        )
        for r in dist["runs"]:
            lines.append(
                f"{str(r['run']).ljust(w)}  {str(r['verdict']).ljust(28)}  "
                f"{str(r['job_grade']).ljust(10)}  {str(r['journal']).ljust(16)}  {r['files']}"
            )
    lines.append("")
    lines.append("VERDICT DISTRIBUTION:")
    for verdict, n in sorted(dist["verdict_counts"].items(), key=lambda kv: -kv[1]):
        lines.append(f"  {verdict:<30} {n}")
    lines.append("")
    lines.append("FATE OF EVERY MATCHED RUN:")
    for fate, n in sorted(dist["fate_counts"].items(), key=lambda kv: -kv[1]):
        lines.append(f"  {fate:<30} {n}")
    lines.append("")
    lines.append(
        "A run that produced NO VERDICT is a REAL outcome, not a gap in the data -- it is\n"
        "the most unstable result there is. Fates are separated so a run that died at\n"
        "launch is not counted against a grader, and so a REAPED run (unclean shutdown,\n"
        "journal renamed) cannot disappear from the tally the way a journal-keyed rule\n"
        "made it disappear."
    )
    return "\n".join(lines)


def render(h: Harvest, extra: list[Evidence]) -> str:
    lines: list[str] = []
    lines.append(f"RUN: {h.run_id}")
    lines.append(f"DIR: {h.run_dir}")
    lines.append("")
    items = h.items + extra
    measured = [e for e in items if e.measured]
    lines.append(
        f"{len(measured)} of {len(items)} observable fields were MEASURED. "
        f"{len(items) - len(measured)} were not, and are named below rather than shown as zero."
    )
    lines.append("")
    width = max(len(e.label) for e in items)
    for e in items:
        rows = ",".join(str(r) for r in e.rows)
        lines.append(f"  {e.label.ljust(width)}  {e.value!r}   [rows {rows}] ({e.source})")
        if e.note:
            lines.append(f"  {' ' * width}  -- {e.note}")
    lines.append("")
    unmeasured = [e for e in items if not e.measured]
    if unmeasured:
        lines.append("NOT MEASURED BY THIS RUN -- no row may be promoted on these:")
        for e in unmeasured:
            lines.append(f"  - {e.label} ({e.value}, expected in {e.source})")
        lines.append("")
    lines.append(
        "This reports EVIDENCE, not verdicts. Capability 11 requires a person to judge "
        "whether an observable was genuinely executed end to end before any row moves."
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("run_id", nargs="?", help="run directory name; default is the newest")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    ap.add_argument("--state-root", type=Path, default=DEFAULT_STATE_ROOT)
    ap.add_argument(
        "--across-runs",
        metavar="GOAL_SHA16",
        help=(
            "instead of one run, report the terminal-verdict distribution across every "
            "run whose goal hashes to GOAL_SHA16. Keyed on the INPUT deliberately: a "
            "rule keyed on what the run WROTE (e.g. journal.log naming the repo) is "
            "biased in favour of runs that survived, and silently drops reaped ones. "
            "Use --list-goals to see the available keys."
        ),
    )
    ap.add_argument(
        "--list-goals",
        action="store_true",
        help="list every distinct goal hash on disk, with run counts",
    )
    args = ap.parse_args(argv)

    state_root: Path = args.state_root

    if args.list_goals:
        seen = goals_seen(state_root)
        if args.json:
            print(json.dumps(seen, indent=2, default=str))
        else:
            for sha, n in sorted(seen.items(), key=lambda kv: -kv[1]):
                print(f"  {sha:<20} {n} run(s)")
        return 0

    if args.across_runs:
        dist = verdict_distribution(state_root, args.across_runs)
        print(json.dumps(dist, indent=2, default=str) if args.json else render_distribution(dist))
        return 0
    if args.run_id:
        run_dir = state_root / "fleet-runs" / args.run_id
        if not run_dir.is_dir():
            print(f"no such run directory: {run_dir}", file=sys.stderr)
            return 2
    else:
        found = newest_run(state_root)
        if found is None:
            print(f"no runs under {state_root / 'fleet-runs'}", file=sys.stderr)
            return 2
        run_dir = found

    h = harvest(run_dir, state_root)
    extra = [research_lookups(state_root, run_dir.name)]

    if args.json:
        payload = {
            "run_id": h.run_id,
            "run_dir": str(h.run_dir),
            "evidence": [
                {
                    "label": e.label,
                    "value": e.value,
                    "source": e.source,
                    "dod_rows": list(e.rows),
                    "measured": e.measured,
                    "note": e.note,
                }
                for e in h.items + extra
            ],
        }
        print(json.dumps(payload, indent=2, default=str))
    else:
        print(render(h, extra))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
