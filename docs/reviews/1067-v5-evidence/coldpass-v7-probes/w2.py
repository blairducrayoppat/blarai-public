"""W2: false-refusal re-measure at 662e1a61 with the (task,result) API."""
import sys, pathlib
sys.path.insert(0, r"C:/Users/mrbla/wt-1067-v7")
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from shared.coordinator import prose_guard as pg
from corpus45 import ACCURATE

T = pg.RunTruth(run_id="20260721-111715-bd", oracle_passed=False, merged=True, parked=False)
PAIRS = (("bill-splitter", "MERGED"), ("acceptance-tests", "PARKED"))
G = pg.ProseGuard()

ref = []
for s in ACCURATE:
    d = G.validate_run_summary(T, "INCOMPLETE: " + s, task_results=PAIRS)
    assert d.action != "rejected:echo-missing", s
    assert not d.action.startswith("rejected:echo-mismatch"), s
    if not d.accepted:
        ref.append(s)
print(f"accurate probes: {len(ACCURATE)}")
print(f"REFUSED: {len(ref)} = {100*len(ref)/len(ACCURATE):.1f}%")
for s in ref:
    print("  DROP", repr(s))
