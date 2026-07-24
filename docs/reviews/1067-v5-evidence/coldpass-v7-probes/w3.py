"""W3: is the rewritten seam test as strong as its docstring says?"""
import sys
sys.path.insert(0, r"C:/Users/mrbla/wt-1067-v7")
from shared.coordinator import heartbeat_cycle as hc
from shared.tests import test_coordinator_prose_guard as T

NAME = "test_the_guard_receives_the_harvested_record_from_the_real_cycle"
fn = getattr(T, NAME)

def boom(*a, **k):
    raise AssertionError("CALLED")

for stub, label in [("run_wake_cycle", "run_wake_cycle (what the docstring claims)"),
                    ("_guard_prose", "_guard_prose (what it actually calls)")]:
    saved = getattr(hc, stub)
    try:
        setattr(hc, stub, boom)
        try:
            fn()
            print(f"  {label:45s} -> test PASSES (never calls it)")
        except AssertionError as e:
            print(f"  {label:45s} -> test RAISED '{e}' (does call it)")
    finally:
        setattr(hc, stub, saved)

print("\n  Does the test compute the derivation itself?")
import inspect
src = inspect.getsource(fn)
print("   'for o in' generator inside the test body:", "for o in" in src)
print("   calls hc.run_wake_cycle:", "run_wake_cycle(" in src)
print("   calls hc._guard_prose:", "_guard_prose(" in src)
