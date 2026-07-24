"""Cold adversarial harness for #1067 v7. Read-only."""
import sys
sys.path.insert(0, r"C:/Users/mrbla/wt-1067-v7")

from shared.coordinator import prose_guard as pg

# A failed run: oracle FAILED, some merged, not parked -> INCOMPLETE
FAILED = pg.RunTruth(run_id="20260721-111715-bd", oracle_passed=False,
                     merged=True, parked=False)
PARKEDT = pg.RunTruth(run_id="20260721-111715-bd", oracle_passed=False,
                      merged=False, parked=True)
NAMES = ("bill-splitter", "acceptance-tests")

ECHO_MISSING = "rejected:echo-missing"


def probe(text, truth=FAILED, names=NAMES, guard=None):
    """Returns (accepted, action). Hard-fails if the echo layer answered."""
    g = guard or pg.ProseGuard()
    d = g.validate_run_summary(truth, text, task_names=names)
    assert d.action != ECHO_MISSING, f"ECHO-MISSING (probe malformed): {text!r}"
    assert not d.action.startswith("rejected:echo-mismatch"), \
        f"ECHO-MISMATCH (probe malformed): {text!r}"
    return d.accepted, d.action


def pfx(truth=FAILED):
    return f"{truth.verdict()}: "


def run(name, bodies, truth=FAILED, names=NAMES):
    print(f"\n=== {name} ===")
    hits = []
    for b in bodies:
        text = pfx(truth) + b
        a, act = probe(text, truth=truth, names=names)
        if a:
            hits.append(b)
            print(f"  *** ACCEPT: {b!r}")
    print(f"  accepted {len(hits)}/{len(bodies)}")
    return hits
