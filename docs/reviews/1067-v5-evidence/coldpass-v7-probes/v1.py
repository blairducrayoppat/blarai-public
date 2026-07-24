"""V1: is the new 'derivation' test a tautology? Proof by depriving it of every
production entry point. If it still passes, it never called production."""
import sys
sys.path.insert(0, r"C:/Users/mrbla/wt-1067-v7")
from shared.coordinator import heartbeat_cycle as hc
from shared.tests import test_coordinator_prose_guard as T


def boom(*a, **k):
    raise AssertionError("PRODUCTION CODE CALLED")


print("### author's test: test_only_merged_task_names_are_forwarded_to_the_guard ###")
saved = (hc.run_wake_cycle, hc._guard_prose, hc._PROSE_GUARD)
try:
    hc.run_wake_cycle = boom
    hc._guard_prose = boom
    hc._PROSE_GUARD = boom
    try:
        T.test_only_merged_task_names_are_forwarded_to_the_guard()
        print("  PASSES with run_wake_cycle, _guard_prose AND _PROSE_GUARD all")
        print("  replaced by a raising stub -> it calls NO production code.")
    except AssertionError as e:
        print("  failed:", e)
finally:
    hc.run_wake_cycle, hc._guard_prose, hc._PROSE_GUARD = saved

print("\n### control: the OTHER seam test, same treatment ###")
saved = (hc.run_wake_cycle, hc._guard_prose)
try:
    hc.run_wake_cycle = boom
    hc._guard_prose = boom
    try:
        T.test_task_names_reach_the_guard_from_the_real_entry_point()
        print("  PASSES -> also never reached _guard_prose")
    except AssertionError as e:
        print(f"  RAISED ({e}) -> it does reach _guard_prose")
finally:
    hc.run_wake_cycle, hc._guard_prose = saved

print("\n### what the new test actually asserts ###")
import inspect
src = inspect.getsource(T.test_only_merged_task_names_are_forwarded_to_the_guard)
body = [l for l in src.splitlines() if l.strip() and not l.strip().startswith(('"', "#"))]
for l in body[-12:]:
    print("   ", l)
