"""Say, in the operator's own words, which of his requirements the exam actually checked.

Why this exists
---------------
`docs/design/CODER_DEFINITION_OF_DONE.md` row 17 asks for a requirements-to-assertions
coverage figure. `docs/ROADMAP.md` ranks the report as the cheapest real win on the
list, and it is: no graphics card, no coder run, no operator. The raw material has been
banked for weeks -- his requirement sentences in ``acceptance.json`` ``spec.criteria``,
the per-criterion coverage level in ``traceability.json`` ``criteria`` -- and nothing
had ever joined them.

The join is on ``id``, and it is complete: every run carrying a ``traceability.json``
also carries an ``acceptance.json`` with ``spec.criteria``.

What this refuses to do
-----------------------
**It will not shrink the denominator behind his back.** ``traceability.json`` publishes
``denominator_excludes`` -- typically ``["build", "visual", "human"]`` -- so on a job
where he stated eight requirements the instrument grades six and reports out of six.
Two of his sentences were dropped, and the drop is invisible in the headline figure.
This report names the excluded ones as excluded, in his wording, rather than letting
them vanish.

**It will not present UNDECIDABLE as coverage.** On websites the matcher asks whether an
oracle symbol's *name appears inside the operator's English sentence*, which works for
Python API goals and essentially never for web prose. The honest headline on a real web
run is therefore closer to "1 weakly checked, 5 cannot be determined, 2 never in scope"
than to any percentage -- and printing that is the point, because it convicts the matcher
in the same breath as it answers his question.

Usage
-----
    python tools/probes/requirement_coverage_report.py                  # newest with data
    python tools/probes/requirement_coverage_report.py <run-id>
    python tools/probes/requirement_coverage_report.py --all            # every banked run
    python tools/probes/requirement_coverage_report.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

DEFAULT_STATE_ROOT = Path(
    os.environ.get("BLARAI_FLEET_STATE_ROOT", r"C:/Users/mrbla/agentic-setup/state")
)

ABSENT = "ABSENT"

#: Plain-language gloss for each coverage level. The operator is non-technical and the
#: level names are internal jargon; a report he cannot read is not a report.
LEVEL_PLAIN = {
    "L4-KILLS": "checked, and the check was proven able to fail",
    "L3-ASSERTED": "checked by an assertion",
    "L2-BOUND": "weakly checked — the exam touches it but asserts nothing about it",
    "L1-DECLARED": "named by the exam but not exercised",
    "L0-GAP": "NOT checked at all",
    "UNDECIDABLE": "cannot be determined either way",
}


def _read_json(path: Path) -> Any:
    if not path.is_file():
        return ABSENT
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return ABSENT


def build_report(run_dir: Path) -> dict[str, Any]:
    """Join his sentences to their coverage levels. Never invents a level."""
    acc = _read_json(run_dir / "acceptance.json")
    trace = _read_json(run_dir / "traceability.json")

    out: dict[str, Any] = {
        "run": run_dir.name,
        "available": False,
        "reason": "",
        "criteria": [],
        "excluded_tiers": [],
        "graded_denominator": None,
        "operator_requirement_count": None,
    }

    # A MISSING acceptance.json must not render as "he stated 0 requirements". With a
    # traceability.json present that would print "He stated 0 requirement(s). The exam
    # graded 6 of them." -- the exact defect the sibling probe's headline lock forbids,
    # in the module that did not lock it. Latent today (33/33 banked runs carry both),
    # and latent is not the same as safe. Caught by an independent pre-merge reviewer.
    spec_criteria = []
    if acc is ABSENT:
        out["operator_requirement_count"] = ABSENT
    else:
        spec_criteria = (acc.get("spec") or {}).get("criteria") or []
        out["operator_requirement_count"] = len(spec_criteria)

    if trace is ABSENT:
        out["reason"] = "no traceability.json in this run — coverage was never computed"
        return out
    if not trace.get("available"):
        out["reason"] = str(trace.get("reason") or "traceability reported unavailable")
        return out

    out["available"] = True
    out["excluded_tiers"] = list(trace.get("denominator_excludes") or [])
    out["graded_denominator"] = trace.get("denominator")

    levels = {str(c.get("id")): c for c in (trace.get("criteria") or [])}

    for sc in spec_criteria:
        cid = str(sc.get("id"))
        tier = str(sc.get("tier", ""))
        graded = levels.get(cid)
        if graded is None:
            # HIS sentence, dropped from the denominator before grading began.
            out["criteria"].append(
                {
                    "id": cid,
                    "tier": tier,
                    "text": str(sc.get("text", "")),
                    "level": "NOT-IN-SCOPE",
                    "plain": (
                        f"never in this exam's scope — the '{tier}' tier is excluded "
                        "from grading"
                    ),
                    "reason": "excluded by denominator_excludes",
                }
            )
            continue
        level = str(graded.get("level", "UNKNOWN"))
        out["criteria"].append(
            {
                "id": cid,
                "tier": tier,
                "text": str(sc.get("text", "")),
                "level": level,
                "plain": LEVEL_PLAIN.get(level, level),
                "reason": str(graded.get("reason") or ""),
            }
        )
    return out


def render(rep: dict[str, Any]) -> str:
    lines = [f"RUN: {rep['run']}", ""]
    if not rep["available"]:
        lines.append(f"NO COVERAGE MEASUREMENT: {rep['reason']}")
        lines.append("")
        lines.append(
            "That is a real outcome, not a gap in this report: nothing graded his "
            "requirements on this run."
        )
        return "\n".join(lines)

    total = rep["operator_requirement_count"]
    if total == ABSENT:
        lines.append(
            "HIS REQUIREMENTS ARE UNREADABLE for this run — no acceptance.json. The exam's "
            f"own count of {rep['graded_denominator']} is reported below, but there is "
            "nothing to check it against, so it cannot be called complete or incomplete."
        )
    else:
        lines.append(f"He stated {total} requirement(s). The exam graded "
                     f"{rep['graded_denominator']} of them.")
    if rep["excluded_tiers"]:
        lines.append(
            f"Excluded from grading before it began: {', '.join(rep['excluded_tiers'])} "
            "— named here rather than dropped silently."
        )
    lines.append("")
    for c in rep["criteria"]:
        lines.append(f"  [{c['level']}] {c['text']}")
        lines.append(f"      -> {c['plain']}")
        if c["reason"] and c["level"] in ("UNDECIDABLE", "NOT-IN-SCOPE"):
            lines.append(f"      why: {c['reason']}")
        lines.append("")

    tally: dict[str, int] = {}
    for c in rep["criteria"]:
        tally[c["level"]] = tally.get(c["level"], 0) + 1
    lines.append("SUMMARY: " + ", ".join(f"{k} {v}" for k, v in sorted(tally.items())))
    undec = tally.get("UNDECIDABLE", 0)
    if undec and rep["graded_denominator"]:
        lines.append("")
        lines.append(
            f"NOTE: {undec} of {rep['graded_denominator']} graded requirements are "
            "UNDECIDABLE. That is a statement about the MATCHER, not about the coder — "
            "it tests whether an oracle symbol's name appears inside an English "
            "sentence, which rarely holds for website prose."
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("run_id", nargs="?")
    ap.add_argument("--all", action="store_true", help="every run that has a measurement")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--state-root", type=Path, default=DEFAULT_STATE_ROOT)
    args = ap.parse_args(argv)

    runs_dir = args.state_root / "fleet-runs"
    if not runs_dir.is_dir():
        print(f"no runs under {runs_dir}", file=sys.stderr)
        return 2

    if args.run_id:
        targets = [runs_dir / args.run_id]
    else:
        cands = sorted(d for d in runs_dir.iterdir() if d.is_dir())
        if args.all:
            targets = [d for d in cands if (d / "traceability.json").is_file()]
        else:
            targets = [
                next((d for d in reversed(cands) if (d / "traceability.json").is_file()), cands[-1])
            ]

    reports = [build_report(t) for t in targets if t.is_dir()]
    if args.json:
        print(json.dumps(reports, indent=2, default=str))
    else:
        print(("\n" + "=" * 72 + "\n").join(render(r) for r in reports))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
