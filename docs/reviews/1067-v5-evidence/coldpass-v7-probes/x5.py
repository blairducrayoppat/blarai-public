"""X5: do M6/M8 survive the WHOLE guard suite, or only the seam test?"""
import sys, types, tempfile, pathlib, inspect
WT = r"C:/Users/mrbla/wt-1067-v7"
sys.path.insert(0, WT)
HC = pathlib.Path(WT) / "shared/coordinator/heartbeat_cycle.py"
SRC = HC.read_text(encoding="utf-8")

MUTS = [
 ("control", None, None),
 ("M6 fail-closed OK-status removed",
  "if _lr.status is vb.ReadStatus.OK and _lr.value is not None\n        else ()",
  "if _lr.value is not None\n        else ()"),
 ("M8 annotation forward -> ()",
  "validate_annotation(\n                outcome.text, task_results=run_task_results\n            )",
  "validate_annotation(\n                outcome.text, task_results=()\n            )"),
]

for name, old, new in MUTS:
    src = SRC if old is None else SRC.replace(old, new)
    if old is not None: assert src != SRC, name
    for m in [k for k in sys.modules if k.startswith("shared")]:
        del sys.modules[m]
    mod = types.ModuleType("shared.coordinator.heartbeat_cycle")
    mod.__file__ = str(HC); mod.__package__ = "shared.coordinator"
    sys.modules["shared.coordinator.heartbeat_cycle"] = mod
    exec(compile(src, str(HC), "exec"), mod.__dict__)
    import shared.tests.test_coordinator_prose_guard as T
    failed = []
    for fname, fn in sorted(vars(T).items()):
        if not fname.startswith("test_") or not callable(fn): continue
        sig = inspect.signature(fn)
        try:
            if "tmp_path" in sig.parameters:
                with tempfile.TemporaryDirectory() as td:
                    fn(pathlib.Path(td))
            elif sig.parameters:
                continue   # needs fixtures we can't supply here
            else:
                fn()
        except AssertionError:
            failed.append(fname)
        except Exception:
            pass
    print(f"  {name:36s} -> guard-suite failures: {len(failed)} {failed if failed else ''}")
