"""X2: MUTATION-TEST the seam test. Rewrite run_wake_cycle's derivation in a
loaded copy of heartbeat_cycle and see whether the test goes RED."""
import sys, types, tempfile, pathlib

WT = r"C:/Users/mrbla/wt-1067-v7"
sys.path.insert(0, WT)
HC_PATH = pathlib.Path(WT) / "shared/coordinator/heartbeat_cycle.py"
SRC = HC_PATH.read_text(encoding="utf-8")

ORIGINAL = "tuple((o.task, o.result) for o in _lr.value[1])"
assert ORIGINAL in SRC, "derivation line not found - update the probe"

MUTATIONS = {
    "control (unmutated)": ORIGINAL,
    "M1 bare names (v1 regression)": "tuple(o.task for o in _lr.value[1])",
    "M2 merged-only (v2 regression)":
        "tuple((o.task, o.result) for o in _lr.value[1] if o.result == RESULT_MERGED)",
    "M3 drop the record entirely": "()",
    "M4 swap task/result": "tuple((o.result, o.task) for o in _lr.value[1])",
    "M5 truncate to first outcome": "tuple((o.task, o.result) for o in _lr.value[1][:1])",
}

TESTNAME = "test_run_wake_cycle_hands_the_guard_the_harvested_record"


def run_with(mutated_src):
    for m in [k for k in sys.modules if k.startswith("shared")]:
        del sys.modules[m]
    mod = types.ModuleType("shared.coordinator.heartbeat_cycle")
    mod.__file__ = str(HC_PATH)
    mod.__package__ = "shared.coordinator"
    sys.modules["shared.coordinator.heartbeat_cycle"] = mod
    exec(compile(mutated_src, str(HC_PATH), "exec"), mod.__dict__)
    import shared.tests.test_coordinator_prose_guard as T
    fn = getattr(T, TESTNAME)
    with tempfile.TemporaryDirectory() as td:
        fn(pathlib.Path(td))


for label, repl in MUTATIONS.items():
    src = SRC.replace(ORIGINAL, repl)
    try:
        run_with(src)
        verdict = "GREEN  <-- test did NOT catch it" if label != "control (unmutated)" else "GREEN (expected)"
    except AssertionError as e:
        verdict = "RED    (test caught it)"
    except Exception as e:
        verdict = f"ERROR {type(e).__name__}: {str(e)[:70]}"
    print(f"  {label:34s} -> {verdict}")
