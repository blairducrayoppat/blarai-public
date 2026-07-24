"""X4: correctly-targeted annotation-door mutation + re-confirm M6."""
import sys, types, tempfile, pathlib
WT = r"C:/Users/mrbla/wt-1067-v7"
sys.path.insert(0, WT)
HC = pathlib.Path(WT) / "shared/coordinator/heartbeat_cycle.py"
SRC = HC.read_text(encoding="utf-8")
TESTNAME = "test_run_wake_cycle_hands_the_guard_the_harvested_record"

ANNOT = "validate_annotation(\n                outcome.text, task_results=run_task_results\n            )"
ANNOT_MUT = "validate_annotation(\n                outcome.text, task_results=()\n            )"
FAILCLOSED = "if _lr.status is vb.ReadStatus.OK and _lr.value is not None\n        else ()"
FAILCLOSED_MUT = "if _lr.value is not None\n        else ()"

for name, old, new in [
    ("M8 annotation-door forward -> ()", ANNOT, ANNOT_MUT),
    ("M6 fail-closed OK-status check removed", FAILCLOSED, FAILCLOSED_MUT),
]:
    assert old in SRC, f"pattern miss for {name}"
    src = SRC.replace(old, new)
    assert src != SRC
    for m in [k for k in sys.modules if k.startswith("shared")]:
        del sys.modules[m]
    mod = types.ModuleType("shared.coordinator.heartbeat_cycle")
    mod.__file__ = str(HC); mod.__package__ = "shared.coordinator"
    sys.modules["shared.coordinator.heartbeat_cycle"] = mod
    exec(compile(src, str(HC), "exec"), mod.__dict__)
    import shared.tests.test_coordinator_prose_guard as T
    try:
        with tempfile.TemporaryDirectory() as td:
            getattr(T, TESTNAME)(pathlib.Path(td))
        v = "GREEN  <-- NOT caught by the seam test"
    except AssertionError:
        v = "RED    (caught)"
    except Exception as e:
        v = f"ERROR {type(e).__name__}: {str(e)[:60]}"
    print(f"  {name:42s} -> {v}")

print("\n  (verifying the whole guard suite catches them, not just the seam test)")
