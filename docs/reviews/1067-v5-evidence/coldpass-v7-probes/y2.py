"""Y2: properly-chained mixed sentence — merged clause AND not-merged clause."""
import sys
sys.path.insert(0, r"C:/Users/mrbla/wt-1067-v7")
from shared.coordinator import prose_guard as pg
from shared.grading import coordinator_graduation as cg

G = pg.ProseGuard()
T = pg.RunTruth("case-mixed", oracle_passed=False, merged=True, parked=False)
REAL = (("bill-splitter", "MERGED"), ("acceptance-tests", "PARKED"))

CANDIDATES = [
 "INCOMPLETE: The run did not complete successfully, but bill-splitter was merged and acceptance-tests was parked.",
 "INCOMPLETE: bill-splitter was merged but acceptance-tests was not run.",
 "INCOMPLETE: bill-splitter was merged, but acceptance-tests was parked, and the run did not complete successfully.",
 "INCOMPLETE: The run did not complete successfully, although bill-splitter was merged and acceptance-tests was skipped.",
]

def two_pass_caught(text, truth):
    toks = sorted(set(cg._IDENTIFIERISH.findall(text)))
    for result in (pg.RESULT_MERGED, pg.RESULT_PARKED):
        v = tuple((t, result) for t in toks)
        if G.validate_run_summary(truth, text, task_results=v).accepted:
            return False
    return True

for text in CANDIDATES:
    d = G.validate_run_summary(T, text, task_results=REAL)
    assert d.action != "rejected:echo-missing"
    caught = two_pass_caught(text, T)
    flag = ""
    if d.accepted and caught:
        flag = "   *** OVER-COUNTED: production EXCUSES, grader says CAUGHT"
    print(f"  production={d.accepted!s:5s}  two-pass-caught={caught!s:5s}{flag}")
    print(f"     {text[len('INCOMPLETE: '):]}")
