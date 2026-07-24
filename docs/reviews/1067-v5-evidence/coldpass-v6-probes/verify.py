"""Independent re-verification of every claim the author made about v6."""
import json
import sys
sys.path.insert(0, r"C:/Users/mrbla/AppData/Local/Temp/claude/C--Users-mrbla-BlarAI/82d57925-c6b8-46fc-be83-77fd7033bee2/scratchpad")
from h import v6, mn

WT = r"C:/Users/mrbla/wt-1067-v5"

# ---------------------------------------------------------------- corpus49
print("=== corpus49.jsonl (author: all 49 REFUSED) ===")
rows = [json.loads(l) for l in open(WT + "/docs/reviews/1067-v5-evidence/corpus49.jsonl", encoding="utf-8") if l.strip()]
echo_bad = []
accepted = []
for r in rows:
    t = v6.RunTruth(run_id="r", oracle_passed=r["oracle_passed"], merged=r["merged"], parked=r["parked"])
    d = v6.ProseGuard().validate_run_summary(t, r["text"])
    if d.action.startswith("rejected:echo"):
        echo_bad.append((r["case_id"], d.action, r["text"]))
    if d.accepted:
        accepted.append((r["case_id"], r["text"]))
print(f"  rows={len(rows)}  refused={len(rows)-len(accepted)}  ACCEPTED={len(accepted)}")
print(f"  echo-layer rejections (would invalidate the row): {len(echo_bad)}")
for c in echo_bad:
    print("    ECHO:", c)
for c in accepted:
    print("    ACCEPTED:", c)

# --------------------------------------------------- 34 cold-pass v5 probes
print("\n=== the 34 v5 cold-pass probes (author: must now ALL refuse) ===")
sys.path.insert(0, WT + "/docs/reviews/1067-v5-evidence/coldpass-v5-probes")
import ast
src = open(WT + "/docs/reviews/1067-v5-evidence/coldpass-v5-probes/tally.py", encoding="utf-8").read()
tree = ast.parse(src)
PROBES = None
for node in tree.body:
    if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "FALSE_CLAIMS":
        PROBES = ast.literal_eval(node.value)
assert PROBES is not None
T = v6.RunTruth(run_id="20260721-111715-bd", oracle_passed=False, merged=True, parked=False)
TM = mn.RunTruth(run_id="20260721-111715-bd", oracle_passed=False, merged=True, parked=False)
still = []
echo_bad2 = []
ann_acc = []
for p in PROBES:
    text = "INCOMPLETE: " + p
    d = v6.ProseGuard().validate_run_summary(T, text)
    if d.action.startswith("rejected:echo"):
        echo_bad2.append((d.action, text))
    if d.accepted:
        still.append(p)
    da = v6.ProseGuard().validate_annotation(p)
    if da.accepted:
        ann_acc.append(p)
print(f"  probes={len(PROBES)}  run_summary ACCEPTED by v6={len(still)}  echo-rejections={len(echo_bad2)}")
for p in still:
    print("    STILL ACCEPTED:", ascii(p))
print(f"  validate_annotation ACCEPTED by v6={len(ann_acc)} (no verdict/echo at this door)")
for p in ann_acc:
    print("    ANNOT ACCEPTED:", ascii(p))

# ------------------------------------------------------------- golden cases
print("\n=== golden coord-guard-* replay ===")
for line in open(WT + "/evals/golden/coordinator.jsonl", encoding="utf-8"):
    if not line.strip():
        continue
    g = json.loads(line)
    if g.get("kind") != "prose_guard":
        continue
    run = g["run"]
    t = v6.RunTruth(run_id=run["run_id"], oracle_passed=run["oracle_passed"], merged=run["merged"], parked=run["parked"])
    d = v6.ProseGuard().validate_run_summary(t, g["text"])
    exp = g["expected"]
    ok = (d.accepted == exp["accepted"]) and d.action.startswith(exp["action_prefix"])
    dm = mn.ProseGuard().validate_run_summary(
        mn.RunTruth(run_id=run["run_id"], oracle_passed=run["oracle_passed"], merged=run["merged"], parked=run["parked"]),
        g["text"])
    drift = "" if d.action == dm.action else f"   [CHANGED vs main: main={dm.action}]"
    print(f"  {g['id']}: {'PASS' if ok else 'FAIL'}  v6={d.action}{drift}")

# --------------------------------------------------------- toggle honesty
print("\n=== principle-12 toggle honesty ===")
S = "INCOMPLETE: The overall run did not complete successfully."
print("  default                 :", v6.ProseGuard().validate_run_summary(T, S).action)
print("  negation_carve_out=False:", v6.ProseGuard(negation_carve_out=False).validate_run_summary(T, S).action)
print("  screen_enabled=False    :", v6.ProseGuard(screen_enabled=False).validate_run_summary(T, S).action)
print("  echo_required=False     :", v6.ProseGuard(echo_required=False).validate_run_summary(T, "no prefix at all").action)
orig = v6._claim_is_excused
v6._claim_is_excused = lambda *a, **k: False
print("  module-global patched   :", v6.ProseGuard().validate_run_summary(T, S).action)
v6._claim_is_excused = lambda *a, **k: True
print("  patched->True           :", v6.ProseGuard().validate_run_summary(T, S).action)
v6._claim_is_excused = orig
print("  restored                :", v6.ProseGuard().validate_run_summary(T, S).action)
