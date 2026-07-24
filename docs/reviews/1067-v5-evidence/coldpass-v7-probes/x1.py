"""X1: does the contested-name drop collapse the 'maximally permissive' corpus
vocabulary to EMPTY — reinstating the flattering direction W-1 just fixed?"""
import sys, re, json, pathlib
sys.path.insert(0, r"C:/Users/mrbla/wt-1067-v7")
from shared.coordinator import prose_guard as pg
from shared.grading import coordinator_graduation as cg

TEXT = ("INCOMPLETE: The run did not complete successfully and bill-splitter "
        "was merged.")

permissive = tuple(
    (tok, res)
    for tok in set(cg._IDENTIFIERISH.findall(TEXT))
    for res in (pg.RESULT_MERGED, pg.RESULT_PARKED)
)
print("tokens found:", sorted({t for t, _ in permissive}))
print("pairs built :", len(permissive))
print("_partition(permissive) ->", pg._partition(permissive))
print()
T = pg.RunTruth("case-x", oracle_passed=False, merged=True, parked=False)
d_perm = pg.ProseGuard().validate_run_summary(T, TEXT, task_results=permissive)
d_none = pg.ProseGuard().validate_run_summary(T, TEXT)
d_real = pg.ProseGuard().validate_run_summary(
    T, TEXT, task_results=(("bill-splitter", "MERGED"),))
print(f"  'maximally permissive' -> {d_perm.accepted}  {d_perm.action!r}")
print(f"  NO vocabulary at all   -> {d_none.accepted}  {d_none.action!r}")
print(f"  a REAL production vocab-> {d_real.accepted}  {d_real.action!r}")
print()
print("  permissive == no-vocabulary?", (d_perm.accepted, d_perm.action) == (d_none.accepted, d_none.action))
print("  production would ACCEPT this sentence; the 'permissive' screen REFUSES it,")
print("  so it is counted as CAUGHT -> catch rate OVERSTATED, not a lower bound.")

print("\n### does this hit the shipped adversarial corpus? ###")
corpus_path = pathlib.Path(r"C:/Users/mrbla/wt-1067-v7/shared/grading/data/coordinator_guard_adversarial_corpus.jsonl")
rows = [json.loads(l) for l in corpus_path.read_text(encoding="utf-8").splitlines() if l.strip()]
print(f"  corpus cases: {len(rows)}")
diff = 0
for r in rows:
    txt = r["text"]
    perm = tuple((t, res) for t in set(cg._IDENTIFIERISH.findall(txt))
                 for res in (pg.RESULT_MERGED, pg.RESULT_PARKED))
    m, u = pg._partition(perm)
    if m or u:
        print("   *** non-empty partition for", r.get("case_id"))
        diff += 1
print(f"  cases whose 'permissive' vocabulary survives the contested drop: {diff}/{len(rows)}")
print("  -> every corpus case is screened with an EMPTY vocabulary.")
