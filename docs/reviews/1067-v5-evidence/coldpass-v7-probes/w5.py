"""W5: toggles still honest after the signature change; annotation-door ordering."""
import sys
sys.path.insert(0, r"C:/Users/mrbla/wt-1067-v7")
from shared.coordinator import prose_guard as pg

T = pg.RunTruth("20260721-111715-bd", False, True, False)
PAIRS = (("bill-splitter","MERGED"),("acceptance-tests","MERGED"))
G009 = ("INCOMPLETE: The run 20260721-111715-bd is marked as incomplete. The "
        "bill-splitter and acceptance-tests components were merged, but the "
        "overall run did not complete successfully.")

print("constructor toggle ON :", pg.ProseGuard().validate_run_summary(T,G009,task_results=PAIRS).action)
print("constructor toggle OFF:", pg.ProseGuard(negation_carve_out=False).validate_run_summary(T,G009,task_results=PAIRS).action)
orig = pg._claim_is_excused
try:
    pg._claim_is_excused = lambda body, merged, unmerged, run_id: False
    print("global patched False  :", pg.ProseGuard().validate_run_summary(T,G009,task_results=PAIRS).action)
    pg._claim_is_excused = lambda body, merged, unmerged, run_id: True
    print("global patched True   :", pg.ProseGuard().validate_run_summary(T,"INCOMPLETE: Everything completed successfully.",task_results=PAIRS).action)
finally:
    pg._claim_is_excused = orig
print("restored              :", pg.ProseGuard().validate_run_summary(T,G009,task_results=PAIRS).action)

print("\nannotation door partition ordering (merged vs unmerged must not swap):")
P2 = (("bill-splitter","MERGED"),("acceptance-tests","PARKED"))
for tail, why in [("bill-splitter was merged.","TRUE"),("bill-splitter was parked.","FALSE"),
                  ("acceptance-tests was parked.","TRUE"),("acceptance-tests was merged.","FALSE")]:
    s = "The run did not complete successfully and " + tail
    d = pg.ProseGuard().validate_annotation(s, task_results=P2)
    print(f"  {why:5s} {d.accepted}  {tail}")
