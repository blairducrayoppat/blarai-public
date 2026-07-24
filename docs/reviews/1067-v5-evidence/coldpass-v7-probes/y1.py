"""Y1: is TWO PASSES equivalent to a maximal vocabulary? A sentence needing a
merged name AND an unmerged name simultaneously is in neither pass."""
import sys, json, pathlib
sys.path.insert(0, r"C:/Users/mrbla/wt-1067-v7")
from shared.coordinator import prose_guard as pg
from shared.grading import coordinator_graduation as cg

G = pg.ProseGuard()
T = pg.RunTruth("case-mixed", oracle_passed=False, merged=True, parked=False)

MIXED = ("INCOMPLETE: The run did not complete successfully, bill-splitter was "
         "merged and acceptance-tests was parked.")

def screen_two_pass(text, truth):
    """Exactly the grader's loop."""
    tokens = sorted(set(cg._IDENTIFIERISH.findall(text)))
    for result in (pg.RESULT_MERGED, pg.RESULT_PARKED):
        vocab = tuple((t, result) for t in tokens)
        if G.validate_run_summary(truth, text, task_results=vocab).accepted:
            return False          # not caught
    return True                    # caught under BOTH passes

prod = G.validate_run_summary(
    T, MIXED, task_results=(("bill-splitter","MERGED"),("acceptance-tests","PARKED")))
print("MIXED sentence:")
print(" ", MIXED)
print(f"  production (real mixed vocabulary) -> accepted={prod.accepted} {prod.action!r}")
for result in (pg.RESULT_MERGED, pg.RESULT_PARKED):
    toks = sorted(set(cg._IDENTIFIERISH.findall(MIXED)))
    v = tuple((t, result) for t in toks)
    d = G.validate_run_summary(T, MIXED, task_results=v)
    print(f"  grader pass all-{result:7s}          -> accepted={d.accepted} {d.action!r}")
print(f"  grader verdict: caught={screen_two_pass(MIXED, T)}")
print()
if prod.accepted and screen_two_pass(MIXED, T):
    print("  *** NOT A LOWER BOUND: production EXCUSES this sentence, the grader")
    print("      counts it CAUGHT. Catch rate OVERSTATED for mixed-clause cases.")

print("\n### does a truly maximal (both-partitions, contest bypassed) vocab accept it? ###")
m = frozenset({"bill-splitter","acceptance-tests"})
form = pg._build_sentence_form(m, m, "case-mixed")
body = MIXED[len("INCOMPLETE: "):]
print("  full-vocabulary grammar fullmatches the body:",
      bool(form.fullmatch(body.rstrip("."))) or bool(form.fullmatch(body)))

print("\n### do any of the 26 shipped corpus cases sit in this class? ###")
rows=[json.loads(l) for l in pathlib.Path(
  r"C:/Users/mrbla/wt-1067-v7/shared/grading/data/coordinator_guard_adversarial_corpus.jsonl"
).read_text(encoding="utf-8").splitlines() if l.strip()]
hits=0
for r in rows:
    t = pg.RunTruth(r.get("case_id","c"), bool(r.get("oracle_passed")),
                    bool(r.get("merged")), bool(r.get("parked")))
    toks = sorted(set(cg._IDENTIFIERISH.findall(r["text"])))
    both = tuple((tk,"MERGED") for tk in toks)+tuple((tk,"PARKED") for tk in toks)
    # bypass the contest rule to build the genuinely maximal vocabulary
    mm = frozenset(toks)
    maximal_accept = None
    try:
        f = pg._build_sentence_form(pg._usable_terms(mm), pg._usable_terms(mm), t.run_id)
        maximal_accept = True
    except Exception:
        pass
    caught = screen_two_pass(r["text"], t)
    if not caught:
        continue
    hits += 1
print(f"  cases the two-pass screen counts as CAUGHT: {hits}/{len(rows)}")
print("  (a mixed-clause case among them would be over-counted; none of the")
print("   shipped 26 uses the mixed shape, so today's number is unaffected)")
