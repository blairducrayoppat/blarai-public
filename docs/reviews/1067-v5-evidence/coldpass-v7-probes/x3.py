"""X3: harder mutations - the fail-closed branch, the forward, the other door."""
import sys, types, tempfile, pathlib
WT = r"C:/Users/mrbla/wt-1067-v7"
sys.path.insert(0, WT)
HC = pathlib.Path(WT) / "shared/coordinator/heartbeat_cycle.py"
SRC = HC.read_text(encoding="utf-8")
TESTNAME = "test_run_wake_cycle_hands_the_guard_the_harvested_record"

MUTS = [
    ("control", SRC),
    ("M6 fail-closed branch WIDENED (drop the OK-status check)",
     SRC.replace("if _lr.status is vb.ReadStatus.OK and _lr.value is not None\n        else ()",
                 "if _lr.value is not None\n        else ()")),
    ("M7 _guard_prose forwards nothing to run summary",
     SRC.replace("run_truth, outcome.text, task_results=run_task_results",
                 "run_truth, outcome.text, task_results=()")),
    ("M8 _guard_prose forwards nothing to ANNOTATION door",
     SRC.replace("outcome.text, task_results=run_task_results\n                )",
                 "outcome.text, task_results=()\n                )")),
]

def run_with(src):
    for m in [k for k in sys.modules if k.startswith("shared")]:
        del sys.modules[m]
    mod = types.ModuleType("shared.coordinator.heartbeat_cycle")
    mod.__file__ = str(HC); mod.__package__ = "shared.coordinator"
    sys.modules["shared.coordinator.heartbeat_cycle"] = mod
    exec(compile(src, str(HC), "exec"), mod.__dict__)
    import shared.tests.test_coordinator_prose_guard as T
    with tempfile.TemporaryDirectory() as td:
        getattr(T, TESTNAME)(pathlib.Path(td))

for label, src in MUTS:
    changed = (src != SRC) or label == "control"
    if not changed:
        print(f"  {label:56s} -> MUTATION DID NOT APPLY (pattern miss)"); continue
    try:
        run_with(src); v = "GREEN  <-- NOT caught"
    except AssertionError: v = "RED    (caught)"
    except Exception as e: v = f"ERROR {type(e).__name__}: {str(e)[:60]}"
    print(f"  {label:56s} -> {v}")
