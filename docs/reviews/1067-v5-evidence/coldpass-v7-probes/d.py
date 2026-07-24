"""Differential harness: v7 vs main. Reports only v7-ACCEPT / main-REFUSE."""
import sys
sys.path.insert(0, r"C:/Users/mrbla/wt-1067-v7")
sys.path.insert(0, r"C:/Users/mrbla/AppData/Local/Temp/claude/C--Users-mrbla-BlarAI/82d57925-c6b8-46fc-be83-77fd7033bee2/scratchpad/v7cold/mainmod")

from shared.coordinator import prose_guard as pg
import main_guard as mg

FAILED = pg.RunTruth(run_id="20260721-111715-bd", oracle_passed=False,
                     merged=True, parked=False)
M_FAILED = mg.RunTruth(run_id="20260721-111715-bd", oracle_passed=False,
                       merged=True, parked=False)
NAMES = ("bill-splitter", "acceptance-tests")


def both(body, names=NAMES):
    text = "INCOMPLETE: " + body
    d = pg.ProseGuard().validate_run_summary(FAILED, text, task_names=names)
    assert d.action != "rejected:echo-missing", f"echo-missing: {body!r}"
    assert not d.action.startswith("rejected:echo-mismatch"), f"mismatch: {body!r}"
    m = mg.ProseGuard().validate_run_summary(M_FAILED, text)
    assert m.action != "rejected:echo-missing", f"MAIN echo-missing: {body!r}"
    return d, m


def sweep(name, bodies, names=NAMES):
    print(f"\n=== {name} ===")
    new_accepts, both_accept = [], []
    for b in bodies:
        d, m = both(b, names)
        if d.accepted and not m.accepted:
            new_accepts.append((b, d.action, m.action))
        elif d.accepted and m.accepted:
            both_accept.append(b)
    for b, da, ma in new_accepts:
        print(f"  [V7-ONLY ACCEPT] {b!r}")
    if both_accept:
        print(f"  (also accepted by MAIN, not a v7 regression: {len(both_accept)})")
        for b in both_accept:
            print(f"      main-too: {b!r}")
    print(f"  v7-only accepts: {len(new_accepts)}/{len(bodies)}")
    return new_accepts
