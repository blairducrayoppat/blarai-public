"""Y4: is `assert seen == {}` green only for the RIGHT reason?
An assertion of ABSENCE passes whenever the cycle produces no prose at all."""
import sys, types, tempfile, pathlib
WT = r"C:/Users/mrbla/wt-1067-v7"
sys.path.insert(0, WT)
HC = pathlib.Path(WT) / "shared/coordinator/heartbeat_cycle.py"
SRC = HC.read_text(encoding="utf-8")

FAILCLOSED_TEST = "test_an_unreadable_harvest_leg_hands_the_guard_no_vocabulary"
POSITIVE_TEST   = "test_run_wake_cycle_hands_the_guard_the_harvested_record"

# A mutation with NOTHING to do with the unreadable leg: drafting goes dormant.
OLD = '        steps.append(StepOutcome("drafting", True, "no drafting seam wired (dormant)"))\n        return [], {}'
NEW = '        steps.append(StepOutcome("drafting", True, "no drafting seam wired (dormant)"))\n        return [], {}\n    return [], {}'

MUTS = [("control", SRC), ("drafting made dormant (unrelated to the leg)", SRC.replace(OLD, NEW))]

def run(src, testname):
    for m in [k for k in sys.modules if k.startswith("shared")]:
        del sys.modules[m]
    mod = types.ModuleType("shared.coordinator.heartbeat_cycle")
    mod.__file__ = str(HC); mod.__package__ = "shared.coordinator"
    sys.modules["shared.coordinator.heartbeat_cycle"] = mod
    exec(compile(src, str(HC), "exec"), mod.__dict__)
    import shared.tests.test_coordinator_prose_guard as T
    with tempfile.TemporaryDirectory() as td:
        getattr(T, testname)(pathlib.Path(td))

for label, src in MUTS:
    if label != "control":
        assert src != SRC, "mutation did not apply"
    line = f"  {label:44s}"
    for tn, short in ((FAILCLOSED_TEST, "fail-closed test"), (POSITIVE_TEST, "positive seam test")):
        try:
            run(src, tn); v = "GREEN"
        except AssertionError: v = "RED"
        except Exception as e: v = f"ERR:{type(e).__name__}"
        line += f"  {short}={v:6s}"
    print(line)
