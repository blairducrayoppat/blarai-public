"""A4: ReDoS / catastrophic backtracking on the per-run compiled grammar."""
import sys, time
sys.path.insert(0, r"C:/Users/mrbla/wt-1067-v7")
from shared.coordinator import prose_guard as pg

FAILED = pg.RunTruth(run_id="r1", oracle_passed=False, merged=True, parked=False)
G = pg.ProseGuard()
P = "INCOMPLETE: "

print("### 'and' is ambiguous: term_list tail vs clause chain ###")
for n in range(4, 22, 2):
    body = "alpha " + "and alpha " * n + "were merged and the run did not complete successfullyX."
    t0 = time.perf_counter()
    d = G.validate_run_summary(FAILED, P + body, task_names=("alpha",))
    dt = time.perf_counter() - t0
    print(f"  n={n:2d} len={len(body):4d}  {dt:8.3f}s  {d.action}")
    if dt > 20:
        print("  *** ABORTING: superlinear blowup confirmed")
        break

print("\n### comma-list variant ###")
for n in range(4, 20, 2):
    body = "alpha" + ", alpha" * n + " and alpha were merged, so the run did not complete successfullyX."
    t0 = time.perf_counter()
    d = G.validate_run_summary(FAILED, P + body, task_names=("alpha",))
    dt = time.perf_counter() - t0
    print(f"  n={n:2d} len={len(body):4d}  {dt:8.3f}s  {d.action}")
    if dt > 20:
        print("  *** ABORTING")
        break
