"""V3: is the not-merged clause now dead? + rid slot + corpora + false refusal."""
import sys, json, pathlib
sys.path.insert(0, r"C:/Users/mrbla/wt-1067-v7")
from shared.coordinator import prose_guard as pg

ROOT = pathlib.Path(r"C:/Users/mrbla/wt-1067-v7")
T = pg.RunTruth(run_id="20260721-111715-bd", oracle_passed=False, merged=True, parked=False)
G = pg.ProseGuard()
MERGED_ONLY = ("bill-splitter",)


def p(body, names=MERGED_ONLY, truth=T):
    d = G.validate_run_summary(truth, f"{truth.verdict()}: " + body, task_names=names)
    assert d.action != "rejected:echo-missing", body
    assert not d.action.startswith("rejected:echo-mismatch"), body
    return d.accepted, d.action

print("### Is the not-merged/parked clause reachable by any TRUE sentence? ###")
print("  Vocabulary is merged-only, so every instantiation names a MERGED task.")
for b in ["The run did not complete successfully and bill-splitter was not merged.",
          "The run did not complete successfully and bill-splitter was parked.",
          "The run did not complete successfully and bill-splitter was skipped.",
          "The run did not complete successfully and bill-splitter was not run."]:
    print(f"  {p(b)}  <- {b!r}   (FALSE: bill-splitter merged)")
print("  ...and the TRUE version, naming the parked task:")
for b in ["The run did not complete successfully and acceptance-tests was parked.",
          "The run did not complete successfully and acceptance-tests was not merged."]:
    print(f"  {p(b)}  <- {b!r}   (TRUE)")

print("\n### rid: a 4th variable position? (claim present so the carve-out runs) ###")
for b, lab in [("The run 20260721-111715-bd is marked as incomplete, but the run did not complete successfully.", "correct rid"),
               ("The run 99999999-999999-zz is marked as incomplete, but the run did not complete successfully.", "WRONG rid")]:
    print(f"  {lab:12s} {p(b)}")

print("\n### corpus49 (generous vocab) ###")
rows = [json.loads(l) for l in (ROOT/"docs/reviews/1067-v5-evidence/corpus49.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
bad = echo = 0
for r in rows:
    t = pg.RunTruth(r.get("run_id","r"), bool(r["oracle_passed"]), bool(r["merged"]), bool(r["parked"]))
    d = pg.ProseGuard().validate_run_summary(t, r["text"], task_names=("bill-splitter","acceptance-tests"))
    if d.action.startswith("rejected:echo"): echo += 1
    if d.accepted: bad += 1; print("   *** ACCEPTED:", r["text"])
print(f"  rows={len(rows)} accepted={bad} echo-answered={echo}")

print("\n### goldens ###")
for l in (ROOT/"evals/golden/coordinator.jsonl").read_text(encoding="utf-8").splitlines():
    if not l.strip(): continue
    c = json.loads(l)
    if c.get("kind") != "prose_guard": continue
    r = c["run"]
    t = pg.RunTruth(r["run_id"], bool(r.get("oracle_passed")), bool(r.get("merged")), bool(r.get("parked")))
    d = pg.ProseGuard().validate_run_summary(t, c["text"], task_names=tuple(str(x) for x in r.get("tasks", ())))
    e = c["expected"]
    ok = d.accepted == e["accepted"] and d.action.startswith(e["action_prefix"])
    print(f"  {c['id']}: {d.accepted}/{d.action!r} -> {'OK' if ok else 'MISMATCH'}")

print("\n### false-refusal re-measure (45 accurate sentences, live merged-only vocab) ###")
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from a8 import ACCURATE
ref = [s for s in ACCURATE if not p(s)[0]]
print(f"  refused {len(ref)}/{len(ACCURATE)} = {100*len(ref)/len(ACCURATE):.1f}%")
newly = [s for s in ref if pg.ProseGuard().validate_run_summary(
    T, "INCOMPLETE: " + s, task_names=("bill-splitter","acceptance-tests")).accepted]
print(f"  of which NEWLY refused because the vocabulary shrank to merged-only: {len(newly)}")
for s in newly:
    print("    NEW DROP:", repr(s))
