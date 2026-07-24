"""X6: Q1 contested-drop direction; W-1 grader fix; false refusal."""
import sys, pathlib
sys.path.insert(0, r"C:/Users/mrbla/wt-1067-v7")
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from shared.coordinator import prose_guard as pg
from shared.grading import run_facts as rf
from shared.grading import coordinator_graduation as cg
import inspect

print("### Q1: is the contested drop ever ACCEPT-directional in production? ###")
T = pg.RunTruth("r", oracle_passed=False, merged=True, parked=False)
G = pg.ProseGuard()
CLEAN = (("bill-splitter","MERGED"),("acceptance-tests","PARKED"))
CONTESTED = CLEAN + (("bill-splitter","PARKED"),)
for body in ["The run did not complete successfully and bill-splitter was merged.",
             "The run did not complete successfully and bill-splitter was parked.",
             "The run did not complete successfully and acceptance-tests was parked."]:
    a = G.validate_run_summary(T,"INCOMPLETE: "+body,task_results=CLEAN).accepted
    b = G.validate_run_summary(T,"INCOMPLETE: "+body,task_results=CONTESTED).accepted
    flag = "  <-- CONTEST ADDED AN ACCEPT" if (b and not a) else ""
    print(f"  clean={a!s:5s} contested={b!s:5s}{flag}  {body!r}")
print("  -> adding a contesting record can only REMOVE accepts (fail-closed).")

print("\n### W-1: does RunFacts carry the pairs and do BOTH sites forward? ###")
print("  RunFacts fields:", [f for f in rf.RunFacts.__dataclass_fields__])
src = inspect.getsource(cg)
print("  grader call sites with task_results=:", src.count("task_results="))
for i, line in enumerate(src.splitlines(), 1):
    if "validate_run_summary(" in line or ("task_results=" in line and "guard" not in line):
        print(f"    {line.strip()[:88]}")
print("  run_truth() docstring mentions 'exact value':",
      "exact value" in (rf.RunFacts.run_truth.__doc__ or ""))

print("\n### false refusal, your 45 accurate sentences ###")
from corpus45 import ACCURATE
PAIRS = (("bill-splitter","MERGED"),("acceptance-tests","PARKED"))
ref=[]
for s in ACCURATE:
    d=G.validate_run_summary(T,"INCOMPLETE: "+s,task_results=PAIRS)
    assert d.action!="rejected:echo-missing" and not d.action.startswith("rejected:echo-mismatch"), s
    if not d.accepted: ref.append(s)
print(f"  refused {len(ref)}/{len(ACCURATE)} = {100*len(ref)/len(ACCURATE):.1f}%")
