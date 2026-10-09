"""Which DoD rows have their evidence BANKED, across the whole corpus?

Why this exists
---------------
``docs/design/CODER_DEFINITION_OF_DONE.md`` says 3 of 21 rows are LIVE. That figure is
maintained by hand, in prose, by whoever last edited a row — and every other number in this
project that was maintained that way turned out to be wrong when somebody finally measured
it. This measures it.

:mod:`tools.probes.harvest_run_evidence` answers *"what did THIS run witness"*. This answers
the question a session actually needs before choosing work:

    for each row, has its evidence EVER been produced, anywhere in the bank,
    and if not, is that because the instrument cannot produce it or because
    no run has exercised it?

**That distinction is the whole point.** On 2026-08-16 four graders were found to be
Python-only, which meant a website night had a CEILING: no number of runs could move those
rows, and the fix was an afternoon of offline work against banked artifacts. Sessions had
been waiting for nights instead. A row blocked on an instrument and a row blocked on a run
look identical in the DoD's prose and need opposite work.

What this does NOT do
---------------------
**It does not promote anything, and it is not a second opinion on the DoD's statuses.** It
reports whether an ARTIFACT exists, which is necessary for a row to be LIVE and never
sufficient: capability 11 asks whether the row's OWN observable was executed, and several
rows want a specific value in that artifact rather than its mere presence (row 5 wants
``hard >= 1``, not a coder-test-qa record). Where this script can check the value it does and
says so; where it can only check presence it says THAT, and the gap between the two is a
judgement a person still has to make.

A row whose evidence exists is a row worth LOOKING at. It is not a row that has moved.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DOD = REPO / "docs" / "design" / "CODER_DEFINITION_OF_DONE.md"
STATE = Path(os.environ.get("BLARAI_FLEET_STATE_ROOT", r"C:/Users/mrbla/agentic-setup/state"))

#: Statuses the DoD's grammar gate allows. Mirrored here rather than imported so this probe
#: keeps working if that gate moves; a drift between the two is itself worth seeing.
_STATUS_RE = re.compile(r"^\*\*Status:\s*([A-Z][A-Z -]*)", re.M)
_ROW_RE = re.compile(r"^### (\d+)\.\s+(.+?)\s*$", re.M)


@dataclass
class Probe:
    """How to look for one row's evidence in the bank.

    ``glob`` is relative to the fleet state root. ``test`` receives the parsed JSON and
    returns True when THIS artifact carries the row's evidence. ``kind`` says what a hit
    actually proves, because presence and value are different strengths of claim."""

    rows: tuple[int, ...]
    label: str
    glob: str
    test: object = None
    #: "value" = the test checks the row's actual observable.
    #: "presence" = the artifact merely exists and a human must still read it.
    kind: str = "presence"
    note: str = ""


def _nonzero(*keys: str):
    def _t(d: dict) -> bool:
        cur = d
        for k in keys:
            if not isinstance(cur, dict):
                return False
            cur = cur.get(k)
        try:
            return float(cur) > 0
        except (TypeError, ValueError):
            return False
    return _t


PROBES: "list[Probe]" = [
    Probe((4, 5), "a WEBSITE exam was examined at all",
          "reports/*.coder-test-qa.json", _nonzero("languages", "node"), "value",
          "languages.node > 0. Zero of 105 records before 2026-08-16; the grader was python-only."),
    Probe((4, 5), "a delivered test was FLAGGED as unable to fail",
          "reports/*.coder-test-qa.json", _nonzero("hard"), "value",
          "hard >= 1. THIS is row 4 bullet 1 and row 5's trigger -- not the row above it. "
          "A clean scan witnesses that the check RAN, which is a different claim."),
    Probe((4, 7, 12, 13), "the exam-quality verdict was recorded",
          "fleet-runs/*/oracle-qa.json", None, "presence",
          "Any oracle-qa.json. Until #1418 a refused exam banked none at all."),
    Probe((4, 12, 13), "a REPAIR round actually ran",
          "fleet-runs/*/oracle-qa.json", _nonzero("regeneration", "rounds"), "value",
          "regeneration.rounds > 0. Distinguishes 'the loop ran and failed' from 'never ran'."),
    Probe((3, 12), "delivered code was quality-scanned",
          "fleet-runs/*/green-quality.json", None, "presence"),
    Probe((12, 14, 17, 21), "a job-level GRADE was produced",
          "fleet-runs/*/scorecard.json",
          lambda d: str((d.get("job_acceptance") or {}).get("status", "")) in {"passed", "failed"},
          "value",
          "job_acceptance.status in {passed, failed}. 'pending'/'not-run' is an honest "
          "non-grade and is the denominator every end-of-run instrument divides by."),
    Probe((15,), "the built product was EXERCISED, not just inspected",
          "fleet-runs/*/link-lint.json", lambda d: bool(d.get("checked")), "value",
          "link-lint checked=true. If false, every count under it is a floor."),
    Probe((20,), "decomposition was graded",
          "fleet-runs/*/decompose-diagnostics.json", None, "presence"),
    Probe((2, 10, 18), "the OPERATOR's own assets were used",
          "fleet-runs/*/acceptance.json",
          lambda d: bool((d.get("spec") or {}).get("operator_assets")), "value",
          "spec.operator_assets non-empty. Measured 2026-08-15: absent from 225 records "
          "corpus-wide. This is the M2 gap -- 29 of his photographs nothing has ever read."),
    Probe((2, 17), "a CLARIFYING question was asked and answered",
          "fleet-runs/*/acceptance.json",
          lambda d: bool((d.get("spec") or {}).get("clarifications")), "value",
          "spec.clarifications non-empty. Presence of the key is the interview being "
          "POSSIBLE; a non-empty list is it happening."),
    Probe((13,), "a grader was itself graded (mutation audit)",
          "fleet-runs/*/oracle-mutation.json", None, "presence",
          "Python-only as of 2026-08-16 -- #1385 gap 2, the largest remaining bar."),
]


@dataclass
class RowState:
    number: int
    title: str
    status: str
    hits: dict = field(default_factory=dict)


def parse_rows() -> "list[RowState]":
    """The 21 rows and their CURRENT statuses, read from the document itself.

    Parsed rather than pinned so this probe can never disagree with the DoD about what a row
    claims -- a hardcoded status list would be one more number maintained by hand, which is
    the failure this script exists to measure."""
    text = DOD.read_text(encoding="utf-8", errors="replace")
    rows: "list[RowState]" = []
    marks = list(_ROW_RE.finditer(text))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        body = text[m.start():end]
        st = _STATUS_RE.search(body)
        rows.append(RowState(int(m.group(1)), m.group(2).strip(),
                             (st.group(1).strip() if st else "NO STATUS LINE")))
    return rows


def scan(probe: Probe) -> "tuple[int, int, str]":
    """``(hits, examined, newest_hit_path)`` for one probe across the whole bank."""
    hits = 0
    examined = 0
    newest = ""
    newest_mtime = -1.0
    for p in sorted(STATE.glob(probe.glob)):
        examined += 1
        if probe.test is None:
            ok = True
        else:
            try:
                ok = bool(probe.test(json.loads(p.read_text(encoding="utf-8", errors="replace"))))
            except (OSError, ValueError, TypeError):
                ok = False
        if ok:
            hits += 1
            try:
                mt = p.stat().st_mtime
            except OSError:
                mt = 0.0
            if mt > newest_mtime:
                newest_mtime, newest = mt, str(p)
    return hits, examined, newest


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if not DOD.is_file():
        print(f"the definition of done is not at {DOD} -- nothing to audit", file=sys.stderr)
        return 2

    rows = parse_rows()
    by_status: dict = {}
    for r in rows:
        by_status.setdefault(r.status, []).append(r.number)

    results = []
    for probe in PROBES:
        hits, examined, newest = scan(probe)
        results.append((probe, hits, examined, newest))

    if args.json:
        print(json.dumps({
            "rows": [{"n": r.number, "title": r.title, "status": r.status} for r in rows],
            "status_counts": {k: len(v) for k, v in by_status.items()},
            "evidence": [
                {"rows": list(p.rows), "label": p.label, "kind": p.kind,
                 "hits": h, "examined": e, "newest": n, "note": p.note}
                for p, h, e, n in results
            ],
        }, indent=2))
        return 0

    live = len(by_status.get("LIVE", []))
    print(f"# DoD evidence audit — {len(rows)} rows, {live} LIVE\n")
    print("STATUS AS THE DOCUMENT STATES IT (parsed, not pinned):")
    for st in sorted(by_status):
        nums = ", ".join(str(n) for n in sorted(by_status[st]))
        print(f"  {st.ljust(22)} {len(by_status[st]):>2}   rows {nums}")

    print("\nEVIDENCE IN THE BANK — has this ever been produced?\n")
    for probe, hits, examined, newest in results:
        mark = "YES" if hits else "NEVER"
        rows_s = ",".join(str(r) for r in probe.rows)
        print(f"  [{mark:5}] rows {rows_s.ljust(10)} {probe.label}")
        print(f"          {hits} of {examined} artifact(s) matched  ({probe.kind} check)")
        if newest:
            print(f"          newest: {Path(newest).name}")
        if probe.note:
            print(f"          -- {probe.note}")
        print()

    # PRODUCTION RATE. A row can be blocked by an instrument that never fires, and that is
    # invisible in the section above: "4 of 4 matched" reads like success and means the
    # instrument produced anything at all in 4 of 263 runs. The roadmap's STOP-DOING #8 names
    # this class ("stop building new end-of-run measurements until runs reach the end");
    # this quantifies it for every instrument at once instead of one anecdote at a time.
    runs = [d for d in (STATE / "fleet-runs").glob("*") if d.is_dir()]
    if runs:
        # SURFACE-AWARE DENOMINATOR. The first version of this table divided every
        # instrument by ALL runs, which reported link-lint at 1.5% when it is web-only and
        # correctly absent from every python run -- a six-fold understatement that went
        # straight into a ticket (#1431) before being caught by asking what the five runs
        # that DID produce it had in common. Dividing a surface-specific instrument by the
        # whole corpus is the same defect this file audits: a denominator that quietly
        # includes cases the measurement never applied to.
        web, classified = [], 0
        for d in runs:
            a = d / "acceptance.json"
            if not a.is_file():
                continue
            classified += 1
            try:
                surface = (json.loads(a.read_text(encoding="utf-8", errors="replace"))
                           .get("spec", {}).get("build_plan", {}).get("surface", ""))
            except (ValueError, TypeError, AttributeError):
                surface = ""
            if surface == "web":
                web.append(d)

        print("HOW OFTEN EACH END-OF-RUN INSTRUMENT PRODUCES ANYTHING AT ALL\n")
        print(f"  {len(runs)} run directories; {classified} carry an acceptance.json; "
              f"{len(web)} are surface=web.")
        print("  Web-only instruments are divided by WEB runs -- dividing them by the whole")
        print("  corpus understates them several-fold and is how #1431's first figures were wrong.\n")
        for artifact, rows_served, web_only in (
            ("scorecard.json", "12,14,17,21", False),
            ("decompose-diagnostics.json", "20", False),
            ("oracle-qa.json", "4,7,12,13", False),
            ("green-quality.json", "3,12", False),
            ("oracle-mutation.json", "13", False),
            ("exec-smoke-web.png", "15", True),
            ("link-lint.json", "15", True),
        ):
            pool = web if web_only else runs
            if not pool:
                continue
            n = sum(1 for d in pool if (d / artifact).exists())
            pct = 100.0 * n / len(pool)
            scope = "web runs" if web_only else "all runs"
            flag = "  <-- rarely fires: likely an INSTRUMENT gap, not a missing run" if pct < 20 else ""
            print(f"    {artifact.ljust(28)} {n:>4} of {len(pool):>4} {scope}  "
                  f"({pct:5.1f}%)  rows {rows_served}{flag}")
        print()
        if classified < len(runs):
            print(f"  CAVEAT: {len(runs) - classified} run(s) carry no acceptance.json and are")
            print("  unclassifiable, so even these figures are a floor. Stated rather than hidden.\n")

    never = [p for p, h, _, _ in results if not h]
    if never:
        print("NEVER PRODUCED — each is either an instrument that cannot emit it, or a run "
              "that has not happened.\nTelling those two apart is the work; they look "
              "identical here and need opposite fixes:\n")
        for p in never:
            print(f"  rows {','.join(str(r) for r in p.rows)}: {p.label}")
        print()

    print("This reports ARTIFACTS, not verdicts. Evidence existing is NECESSARY for a row to "
          "be LIVE and never\nsufficient — capability 11 asks whether the row's own observable "
          "was executed, and a person must still\nread the artifact and decide. A row whose "
          "evidence exists is a row worth looking at.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
