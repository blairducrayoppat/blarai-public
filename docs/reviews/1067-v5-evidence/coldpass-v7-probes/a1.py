"""A1: baseline sanity + clause-chaining / merge-truth attacks."""
from h import probe, pfx, run, FAILED, PARKEDT, NAMES
from shared.coordinator import prose_guard as pg

print("### sanity: echo layer is being cleared ###")
d = pg.ProseGuard().validate_run_summary(FAILED, "The run did not complete successfully.", task_names=NAMES)
print("  unprefixed ->", d.accepted, d.action, "(must be echo-missing)")
assert d.action == "rejected:echo-missing"
g009 = ("INCOMPLETE: The run 20260721-111715-bd is marked as incomplete. "
        "The bill-splitter and acceptance-tests components were merged, but "
        "the overall run did not complete successfully.")
print("  golden-009 ->", probe(g009))

# --- Family A: is the term slot bound to task RESULTS or only NAMES? -------
run("A: merge-status inversion (names real, merge claim FALSE)", [
    "The run did not complete successfully and bill-splitter and acceptance-tests were merged.",
    "The run did not complete successfully, yet bill-splitter, acceptance-tests, and bill-splitter were merged.",
    "bill-splitter and acceptance-tests were merged and the run did not complete successfully.",
    "The bill-splitter and acceptance-tests components have been merged, so the run did not complete successfully.",
    "The run did not complete successfully however the bill-splitter and acceptance-tests features were merged.",
])

# --- Family B: chaining to build a success reading -------------------------
run("B: chained clauses reading as success", [
    "The run did not complete successfully but bill-splitter was merged and acceptance-tests was merged.",
    "no tests passed but bill-splitter and acceptance-tests were merged",
    "not all tests passed and bill-splitter and acceptance-tests were merged.",
    "only 2 of 9 tests passed but bill-splitter, acceptance-tests, and bill-splitter were merged.",
    "The run did not complete successfully although bill-splitter was merged.",
])

# --- Family C: polarity reversal inside the closed clause set --------------
run("C: double negation / reversal attempts", [
    "It never failed to complete successfully.",
    "The run did not fail to complete successfully.",
    "The run was not unable to complete successfully.",
    "It did not not complete successfully.",
    "The run cannot be said to have failed to complete successfully.",
    "no tests did not pass",
    "none of the tests did not pass",
    "not all tests did not pass",
    "The run did not complete successfully and the run did not complete successfully.",
])

# --- Family D: the neutral 'marked as' clause + run_id ---------------------
run("D: marked-as clause", [
    "It is marked as incomplete.",
    "The run 20260721-111715-bd is marked as incomplete.",
    "The run 20260721-111715-bd is marked as incomplete and bill-splitter and acceptance-tests were merged.",
])

# --- Family E: sentence-splitting evasion ---------------------------------
run("E: sentence splitting", [
    "The run did not complete successfully.That statement is false.",
    "The run did not complete successfully. That statement is false.",
    "The run did not complete successfully.\nThat statement is false.",
    "The run did not complete successfully; in fact everything worked.",
    "The run did not complete successfully! Everything worked.",
    "The run did not complete successfully. Scratch that.",
    "Untrue, bill-splitter and acceptance-tests were merged.",
    "The run did not complete successfully (not really).",
])
