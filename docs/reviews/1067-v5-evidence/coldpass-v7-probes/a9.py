"""A9: final confirmation of the exact probes cited in the review."""
import sys
sys.path.insert(0, r"C:/Users/mrbla/wt-1067-v7")
sys.path.insert(0, r"C:/Users/mrbla/AppData/Local/Temp/claude/C--Users-mrbla-BlarAI/82d57925-c6b8-46fc-be83-77fd7033bee2/scratchpad/v7cold/mainmod")
from shared.coordinator import prose_guard as pg
import main_guard as mg

# Run 20260721-111715-bd: oracle FAILED, tasks bill-splitter + acceptance-tests
# BOTH PARKED -> nothing merged, no test passed.  verdict = INCOMPLETE
T = pg.RunTruth(run_id="20260721-111715-bd", oracle_passed=False, merged=False, parked=False)
M = mg.RunTruth(run_id="20260721-111715-bd", oracle_passed=False, merged=False, parked=False)
NAMES = ("bill-splitter", "acceptance-tests")
print("verdict:", T.verdict(), "| main verdict:", M.verdict())

CITED = [
    "INCOMPLETE: only 999 out of 1000 unit tests passed.",
    "INCOMPLETE: only 8 of 9 acceptance tests passed.",
    "INCOMPLETE: The run did not complete successfully, but only 8 of 9 acceptance tests passed.",
    "INCOMPLETE: The run did not complete successfully and the bill-splitter and acceptance-tests components were merged.",
]
for t in CITED:
    d = pg.ProseGuard().validate_run_summary(T, t, task_names=NAMES)
    m = mg.ProseGuard().validate_run_summary(M, t)
    assert d.action != "rejected:echo-missing", t
    assert not d.action.startswith("rejected:echo-mismatch"), t
    print(f"  v7 accepted={d.accepted} action={d.action!r} | main={m.accepted}/{m.action!r}")
    print(f"     {t}")

print("\n### quantifier task name ###")
d = pg.ProseGuard().validate_run_summary(
    T, "INCOMPLETE: The run did not complete successfully but all tasks were merged.",
    task_names=("all", "bill-splitter"))
print("  names=('all','bill-splitter') ->", d.accepted, d.action)
print("  _usable_terms quantifiers:", sorted(pg._usable_terms(
    frozenset({"all", "every", "everything", "both", "each", "entire"}))))

print("\n### annotation door: does the live wiring give it the run vocabulary? ###")
s = "The run did not complete successfully and the bill-splitter and acceptance-tests components were merged."
print("  annotation, no names   :", pg.ProseGuard().validate_annotation(s))
print("  annotation, WITH names :", pg.ProseGuard().validate_annotation(s, task_names=NAMES))

print("\n### heartbeat: is Sequence imported? ###")
import shared.coordinator.heartbeat_cycle as hc
print("  'Sequence' in module globals:", "Sequence" in vars(hc))
