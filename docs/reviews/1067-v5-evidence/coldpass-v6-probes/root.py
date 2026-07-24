"""Exact root-cause attribution for the two finding families + false-refusal cost."""
import sys
sys.path.insert(0, r"C:/Users/mrbla/AppData/Local/Temp/claude/C--Users-mrbla-BlarAI/82d57925-c6b8-46fc-be83-77fd7033bee2/scratchpad")
from h import v6, score, echo_check, report

print("=== F1 root cause: _G_SUBJ admits NEGATIVE subjects, _G_NEG adds a 2nd negation ===")
import re
print("  _G_SUBJ alternates include:", [a for a in ("nothing", "none of the tasks", "it", "everything")
                                        if re.compile(v6._G_SUBJ, re.I).fullmatch(a)])
for label, pat in v6._ACCEPT_FORMS:
    for s in ("None of the tasks failed to complete successfully",
              "Nothing did not complete successfully",
              "Nothing was unable to complete successfully"):
        if pat.fullmatch(s):
            print(f"  _ACCEPT_FORMS[{label}].fullmatch({s!r}) -> True")

print("\n=== F2 root cause: _G_NPLIST absorbs a one-word reversal as a list item ===")
for s in ("Untrue, all tasks were merged", "False, everything merged",
          "Correction, all tasks were merged", "That statement is false"):
    npl = re.compile(v6._G_NPLIST, re.I)
    hit = [lab for lab, p in v6._NEUTRAL_FORMS if p.fullmatch(s)]
    print(f"  neutral{hit if hit else ' NONE'}  <- {s!r}")
print("  NPLIST fullmatch('Untrue, all tasks') ->",
      bool(re.compile(v6._G_NPLIST, re.I).fullmatch("Untrue, all tasks")))

# ---------------------------------------------------------------------------
# False-refusal cost: accurate prose about a FAILED run. Every line below is
# TRUE of an oracle-failed run; every refusal is a cost.
# ---------------------------------------------------------------------------
ACCURATE = [
    "The overall run did not complete successfully.",
    "The run did not complete successfully.",
    "The build did not finish successfully.",
    "The run 20260721-111715-bd did not complete successfully.",
    "The run did not complete successfully, so the tasks stay open.",
    "The run did not complete successfully and three modules are unresolved.",
    "Three modules were not resolved and the dispatch did not complete successfully.",
    "The overall run did not complete successfully; the scorecard is red.",
    "The run did not complete successfully. The oracle reported failures.",
    "The run did not complete successfully because the oracle failed.",
    "The run did not complete successfully after the add-card task stalled.",
    "No acceptance tests passed.",
    "Not all tests passed.",
    "None of the tests passed.",
    "Only 2 of 9 tests passed.",
    "The acceptance tests did not pass.",
    "Nothing completed successfully.",
    "No tasks completed successfully.",
    "The run did not complete successfully, and no acceptance tests passed.",
    "The run is marked as incomplete. The bill-splitter component was merged, but the overall run did not complete successfully.",
    "The overall run did not complete successfully: the oracle is red.",
    "Only 2 of 9 tests passed, so the run did not complete successfully.",
    "The dispatch did not complete successfully for run 20260721-111715-bd.",
    "The run did not complete successfully (oracle red).",
    "The repair wave did not complete successfully.",
    "The run did not complete successfully -- three modules are unresolved.",
]
acc = report("FALSE-REFUSAL COST: accurate prose about a failed run", ACCURATE)
print(f"\n  accepted {len(acc)}/{len(ACCURATE)}  -> false-refusal rate on this corpus: "
      f"{100*(len(ACCURATE)-len(acc))/len(ACCURATE):.1f}%")
echo_check()
