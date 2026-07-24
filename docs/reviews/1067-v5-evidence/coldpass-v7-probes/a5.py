"""A5: ReDoS, corrected — the body MUST carry a real claim so the carve-out
fullmatch actually runs, and the sentence must FAIL to fullmatch to force
backtracking."""
import sys, time
sys.path.insert(0, r"C:/Users/mrbla/wt-1067-v7")
from shared.coordinator import prose_guard as pg

FAILED = pg.RunTruth(run_id="r1", oracle_passed=False, merged=True, parked=False)
G = pg.ProseGuard()
P = "INCOMPLETE: "


def timed(body, names):
    t0 = time.perf_counter()
    d = G.validate_run_summary(FAILED, P + body, task_names=names)
    return time.perf_counter() - t0, d


print("### claim present + unmatchable tail -> forced backtracking ###")
for n in range(2, 26, 2):
    # real claim 'complete successfully' present; trailing 'zz' breaks fullmatch
    body = ("the run did not complete successfully and alpha "
            + "and alpha " * n + "were merged zz.")
    dt, d = timed(body, ("alpha",))
    print(f"  n={n:2d} len={len(body):5d}  {dt:9.4f}s  {d.action}")
    if dt > 30:
        print("  *** ABORT: catastrophic backtracking")
        break

print("\n### comma variant ###")
for n in range(2, 26, 2):
    body = ("the run did not complete successfully and alpha"
            + ", alpha" * n + " and alpha were merged zz.")
    dt, d = timed(body, ("alpha",))
    print(f"  n={n:2d} len={len(body):5d}  {dt:9.4f}s  {d.action}")
    if dt > 30:
        print("  *** ABORT: catastrophic backtracking")
        break

print("\n### many distinct task names (alternation width) ###")
names = tuple(f"task{i:03d}" for i in range(300))
for n in (5, 10, 20, 40):
    body = ("the run did not complete successfully and "
            + " and ".join(names[:n]) + " were merged zz.")
    dt, d = timed(body, names)
    print(f"  n={n:2d} names=300 len={len(body):5d}  {dt:9.4f}s  {d.action}")
    if dt > 30:
        break

print("\n### clause-chain repetition (outer quantifier) ###")
for n in range(2, 20, 2):
    body = ("the run did not complete successfully"
            + " and it did not complete successfully" * n + " zz.")
    dt, d = timed(body, ("alpha",))
    print(f"  n={n:2d} len={len(body):5d}  {dt:9.4f}s  {d.action}")
    if dt > 30:
        print("  *** ABORT")
        break
