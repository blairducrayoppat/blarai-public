"""Y5: what does the two-pass change COST in the grading numbers?"""
import sys, json, pathlib
sys.path.insert(0, r"C:/Users/mrbla/wt-1067-v7")
from shared.coordinator import prose_guard as pg
from shared.grading import coordinator_graduation as cg
G = pg.ProseGuard()
rows=[json.loads(l) for l in pathlib.Path(
 r"C:/Users/mrbla/wt-1067-v7/shared/grading/data/coordinator_guard_adversarial_corpus.jsonl"
).read_text(encoding="utf-8").splitlines() if l.strip()]

def caught_empty(text,t):
    return not G.validate_run_summary(t,text).accepted
def caught_twopass(text,t):
    toks=sorted(set(cg._IDENTIFIERISH.findall(text)))
    for r in (pg.RESULT_MERGED,pg.RESULT_PARKED):
        if G.validate_run_summary(t,text,task_results=tuple((k,r) for k in toks)).accepted:
            return False
    return True

e=tp=0
for r in rows:
    t=pg.RunTruth(r.get("case_id","c"),bool(r.get("oracle_passed")),
                  bool(r.get("merged")),bool(r.get("parked")))
    e+=caught_empty(r["text"],t); tp+=caught_twopass(r["text"],t)
print(f"corpus cases: {len(rows)}")
print(f"  caught, EMPTY vocabulary (the X-1 bug)   : {e}/{len(rows)} = {100*e/len(rows):.1f}%")
print(f"  caught, TWO-PASS (shipped at 9cff8f30)   : {tp}/{len(rows)} = {100*tp/len(rows):.1f}%")
print(f"  delta from fixing X-1                     : {tp-e:+d} cases")
