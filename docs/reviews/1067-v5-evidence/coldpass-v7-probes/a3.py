"""A3: vocabulary parameter, toggles, prior-break families, task-name attacks."""
import sys
sys.path.insert(0, r"C:/Users/mrbla/wt-1067-v7")
from shared.coordinator import prose_guard as pg
from d import sweep, both, FAILED, NAMES

P = "INCOMPLETE: "
G = pg.ProseGuard()


def one(body, names=NAMES, guard=G):
    d = guard.validate_run_summary(FAILED, P + body, task_names=names)
    assert d.action != "rejected:echo-missing"
    return d.accepted, d.action


print("### 1. EMPTY / ABSENT VOCABULARY — fail-closed? ###")
live = "The run 20260721-111715-bd is marked as incomplete. The bill-splitter and acceptance-tests components were merged, but the overall run did not complete successfully."
for label, names in [("names given", NAMES), ("empty tuple", ()), ("omitted", None)]:
    if names is None:
        d = G.validate_run_summary(FAILED, P + live)
    else:
        d = G.validate_run_summary(FAILED, P + live, task_names=names)
    print(f"  {label:14s} -> {d.accepted} {d.action}")
print("  no-name sentence, empty vocab:", one("The run did not complete successfully.", names=()))
print("  no-name sentence, omitted    :",
      G.validate_run_summary(FAILED, P + "The run did not complete successfully.").action)

print("\n### 2. TOGGLES reach the live path? ###")
off = pg.ProseGuard(negation_carve_out=False)
print("  carve_out=False on golden-009 text:", off.validate_run_summary(FAILED, P + live, task_names=NAMES))
print("  carve_out=True  on golden-009 text:", one(live))
_orig = pg._claim_is_excused
try:
    pg._claim_is_excused = lambda body, terms, run_id: False
    print("  module-global patched to False   :", one(live))
    pg._claim_is_excused = lambda body, terms, run_id: True
    print("  module-global patched to True    :", one("Everything completed successfully."))
finally:
    pg._claim_is_excused = _orig
print("  restored                          :", one(live))

print("\n### 3. v5 / v6 break families (must stay REFUSED) ###")
sweep("v5/v6 regressions", [
    "The run did not complete successfully. That statement is false.",
    "None of the tasks failed to complete successfully.",
    "Nothing failed to complete successfully.",
    "Untrue, all tasks were merged.",
    "It is a myth that the run did not complete successfully.",
    "The run did not complete successfully until the retry.",
    "no tests failed to pass",
    "tests did not fail to pass",
    "The overall run did not complete successfully. Actually it did.",
])

print("\n### 4. TASK-NAME attacks (planner-chosen, attacker-adjacent) ###")
for names, bodies in [
    (("all",), ["The run did not complete successfully but all tasks were merged.",
                "The run did not complete successfully and all was merged."]),
    (("everything",), ["no tests passed but everything was merged."]),
    (("tests",), ["The run did not complete successfully and the tests were merged."]),
    (("successfully",), ["The run did not complete successfully and successfully was merged."]),
    (("not-merged", "no"), ["The run did not complete successfully and not-merged was merged."]),
    (("UNTRUE",), ["The run did not complete successfully and UNTRUE was merged."]),
    (("a.b", "x y", "réussi", "ok"),
     ["The run did not complete successfully and ok was merged."]),
]:
    print(f"  names={names}")
    for b in bodies:
        print(f"    {one(b, names=names)}  <- {b!r}")

print("\n### 5. _usable_terms filter behaviour ###")
for t in ["all", "no", "not", "untrue", "Untrue", "a", "ok", "a.b", "x y", "réussi",
          "not-merged", "no-failures", "tests", "run", ".*", "a|b", "9"]:
    print(f"    {t!r:15s} usable={sorted(pg._usable_terms(frozenset([t])))}")
