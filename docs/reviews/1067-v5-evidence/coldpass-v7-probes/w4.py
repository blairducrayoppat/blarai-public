"""W4: corpus49 + goldens + harvested cold-pass sets at 662e1a61."""
import sys, ast, json, pathlib
sys.path.insert(0, r"C:/Users/mrbla/wt-1067-v7")
sys.path.insert(0, r"C:/Users/mrbla/AppData/Local/Temp/claude/C--Users-mrbla-BlarAI/82d57925-c6b8-46fc-be83-77fd7033bee2/scratchpad/v7cold/mainmod")
from shared.coordinator import prose_guard as pg
import main_guard as mg

ROOT = pathlib.Path(r"C:/Users/mrbla/wt-1067-v7")
EV = ROOT / "docs/reviews/1067-v5-evidence"
# generous vocabulary: every plausible name, both partitions populated
_N = ("bill-splitter","acceptance-tests","parser","runner","packager",
      "migration","auth","api","ui","router")
# split, NOT contested: half merged, half not — the contested drop would
# otherwise annihilate a both-partitions vocabulary (see x1.py).
WIDE = tuple((n,"MERGED") for n in _N[:5]) + tuple((n,"PARKED") for n in _N[5:])

print("### corpus49 ###")
rows=[json.loads(l) for l in (EV/"corpus49.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
bad=echo=0
for r in rows:
    t=pg.RunTruth(r.get("run_id","r"),bool(r["oracle_passed"]),bool(r["merged"]),bool(r["parked"]))
    d=pg.ProseGuard().validate_run_summary(t,r["text"],task_results=WIDE)
    if d.action.startswith("rejected:echo"): echo+=1
    if d.accepted: bad+=1; print("  *** ACCEPTED:",r["text"])
print(f"  rows={len(rows)} accepted={bad} echo-answered={echo}")

print("\n### goldens ###")
for l in (ROOT/"evals/golden/coordinator.jsonl").read_text(encoding="utf-8").splitlines():
    if not l.strip(): continue
    c=json.loads(l)
    if c.get("kind")!="prose_guard": continue
    r=c["run"]
    t=pg.RunTruth(r["run_id"],bool(r.get("oracle_passed")),bool(r.get("merged")),bool(r.get("parked")))
    tr=tuple((str(x[0]),str(x[1])) for x in r.get("tasks",()) if len(x)==2)
    d=pg.ProseGuard().validate_run_summary(t,c["text"],task_results=tr)
    e=c["expected"]
    ok=d.accepted==e["accepted"] and d.action.startswith(e["action_prefix"])
    print(f"  {c['id']}: tasks={tr} {d.accepted}/{d.action!r} -> {'OK' if ok else 'MISMATCH'}")

def harvest(d):
    out=[]
    for f in sorted(d.glob("*.py")):
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(n,ast.Constant) and isinstance(n.value,str):
                s=n.value.strip()
                if len(s)>12 and " " in s and not s.startswith(("=== ","  ","#")) \
                   and "sys.path" not in s and "%s" not in s and "\n" not in s:
                    out.append(s)
    return sorted(set(out))

def strip(s):
    for tok in ("INCOMPLETE:","PARKED:","SUCCEEDED:"):
        if s.upper().startswith(tok): return s[len(tok):].strip()
    return s

T=pg.RunTruth("20260721-111715-bd",False,True,False)
M=mg.RunTruth("20260721-111715-bd",False,True,False)
for name in ("coldpass-v5-probes","coldpass-v6-probes"):
    probes=harvest(EV/name)
    v7only=[];echo=0
    for p in probes:
        text="INCOMPLETE: "+strip(p)
        d=pg.ProseGuard().validate_run_summary(T,text,task_results=WIDE)
        if d.action.startswith("rejected:echo"): echo+=1; continue
        m=mg.ProseGuard().validate_run_summary(M,text)
        if d.accepted and not m.accepted: v7only.append(strip(p))
    print(f"\n### {name}: {len(probes)} harvested, echo-answered={echo} ###")
    print(f"  v7-only accepts = {len(v7only)}")
    for b in v7only: print("   ",repr(b))
