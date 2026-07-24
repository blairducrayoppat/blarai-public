"""A6: mandated re-runs — corpus49, v5/v6 cold-pass probe corpora, goldens."""
import sys, json, re, pathlib
sys.path.insert(0, r"C:/Users/mrbla/wt-1067-v7")
from shared.coordinator import prose_guard as pg

ROOT = pathlib.Path(r"C:/Users/mrbla/wt-1067-v7")
EV = ROOT / "docs/reviews/1067-v5-evidence"

NAMES = ("bill-splitter", "acceptance-tests")


def truth_from(run):
    return pg.RunTruth(run_id=run.get("run_id", "r"),
                       oracle_passed=bool(run.get("oracle_passed", False)),
                       merged=bool(run.get("merged", False)),
                       parked=bool(run.get("parked", False)))


print("### corpus49 — all 49 rows must be REFUSED ###")
rows = [json.loads(l) for l in (EV / "corpus49.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
print(f"  rows: {len(rows)}")
bad, echo_answered = [], 0
for r in rows:
    run = r if "oracle_passed" in r else {"run_id": "20260721-111715-bd", "oracle_passed": False,
                           "merged": True, "parked": False}
    t = truth_from(run)
    text = r.get("text") or r.get("probe") or r.get("body") or ""
    names = tuple(r.get("tasks", NAMES))
    d = pg.ProseGuard().validate_run_summary(t, text, task_names=names)
    if d.action == "rejected:echo-missing" or d.action.startswith("rejected:echo-mismatch"):
        echo_answered += 1
    if d.accepted:
        bad.append((text, d.action))
print(f"  answered by ECHO layer (not the claim screen): {echo_answered}")
print(f"  ACCEPTED (must be 0): {len(bad)}")
for t, a in bad:
    print("    *** ", repr(t))

print("\n### goldens ###")
gold = [json.loads(l) for l in (ROOT / "evals/golden/coordinator.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
for c in gold:
    if c.get("kind") != "prose_guard":
        continue
    run = c["run"]
    t = truth_from(run)
    names = tuple(str(x) for x in run.get("tasks", ()))
    d = pg.ProseGuard().validate_run_summary(t, c["text"], task_names=names)
    exp = c["expected"]
    ok = d.accepted == exp["accepted"] and d.action.startswith(exp["action_prefix"])
    print(f"  {c['id']}: got accepted={d.accepted} action={d.action!r} "
          f"expected={exp['accepted']}/{exp['action_prefix']!r} -> {'OK' if ok else 'MISMATCH'}")
