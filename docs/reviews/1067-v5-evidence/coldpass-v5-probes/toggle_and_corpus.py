import sys, json, importlib.util
sys.path.insert(0, r"C:/Users/mrbla/AppData/Local/Temp/claude/C--Users-mrbla-BlarAI/82d57925-c6b8-46fc-be83-77fd7033bee2/scratchpad")
from harness import v5, main, TRUTH_V5, PREFIX

G009 = ("INCOMPLETE: The run 20260721-111715-bd is marked as incomplete. The bill-splitter "
        "and acceptance-tests components were merged, but the overall run did not complete successfully.")

print("=== 3. TOGGLE HONESTY ===")
print("  constructor toggle ON  :", v5.ProseGuard().validate_run_summary(TRUTH_V5, G009).action)
print("  constructor toggle OFF :", v5.ProseGuard(negation_carve_out=False).validate_run_summary(TRUTH_V5, G009).action)
print("  annotation toggle ON   :", v5.ProseGuard().validate_annotation(G009[len('INCOMPLETE: '):]).action)
print("  annotation toggle OFF  :", v5.ProseGuard(negation_carve_out=False).validate_annotation(G009[len('INCOMPLETE: '):]).action)

# module-global patch (the principle-12 shape the tests claim to use)
_orig = v5._claim_is_excused
v5._claim_is_excused = lambda *a, **k: False
print("  global patched to False:", v5.ProseGuard().validate_run_summary(TRUTH_V5, G009).action)
v5._claim_is_excused = lambda *a, **k: True
print("  global patched to True :", v5.ProseGuard().validate_run_summary(TRUTH_V5, "INCOMPLETE: The run completed successfully.").action)
v5._claim_is_excused = _orig
print("  global restored        :", v5.ProseGuard().validate_run_summary(TRUTH_V5, G009).action)

print("\n=== 5a. 49-CASE CORPUS re-run against the V5 guard ===")
rows = [json.loads(l) for l in open(r"C:/Users/mrbla/wt-1067-v5/docs/reviews/1067-v5-evidence/corpus49.jsonl", encoding="utf-8") if l.strip()]
print(f"  rows: {len(rows)}")
accepted = []
echo_bad = []
for r in rows:
    text = r["text"]
    t = v5.RunTruth(**r["run"]) if "run" in r else TRUTH_V5
    d = v5.ProseGuard().validate_run_summary(t, text)
    if d.action.startswith("rejected:echo"):
        echo_bad.append((r.get("id"), d.action, text))
    if d.accepted:
        accepted.append((r.get("id"), text))
print(f"  ECHO-layer rejections (probe never reached the screen): {len(echo_bad)}")
for e in echo_bad[:10]:
    print("    ", e[0], e[1], ascii(e[2])[:90])
print(f"  ACCEPTED by v5 (must be 0): {len(accepted)}")
for a in accepted:
    print("    ", a[0], ascii(a[1])[:110])

print("\n=== 5b. GOLDEN prose_guard cases re-run against the V5 guard ===")
for line in open(r"C:/Users/mrbla/wt-1067-v5/evals/golden/coordinator.jsonl", encoding="utf-8"):
    line = line.strip()
    if not line:
        continue
    c = json.loads(line)
    if c.get("kind") != "prose_guard":
        continue
    t = v5.RunTruth(**c["run"])
    d = v5.ProseGuard().validate_run_summary(t, c["text"])
    exp = c["expected"]
    ok = d.accepted == exp["accepted"] and d.action.startswith(exp["action_prefix"])
    print(f"  {c['id']}  verdict={t.verdict():<10} got={d.action:<42} expect={exp['accepted']}/{exp['action_prefix']:<34} {'OK' if ok else 'MISMATCH'}")
