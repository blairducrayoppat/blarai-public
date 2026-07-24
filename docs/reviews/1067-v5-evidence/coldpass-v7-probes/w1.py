"""W1: verify 662e1a61 — partition mismatch, malformed-record starvation,
grading-instrument vocabulary, false refusal."""
import sys, pathlib
sys.path.insert(0, r"C:/Users/mrbla/wt-1067-v7")
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from shared.coordinator import prose_guard as pg

# bill-splitter MERGED, acceptance-tests PARKED, oracle FAILED
T = pg.RunTruth(run_id="20260721-111715-bd", oracle_passed=False, merged=True, parked=False)
PAIRS = (("bill-splitter", "MERGED"), ("acceptance-tests", "PARKED"))
G = pg.ProseGuard()


def p(body, pairs=PAIRS, truth=T):
    d = G.validate_run_summary(truth, f"{truth.verdict()}: " + body, task_results=pairs)
    assert d.action != "rejected:echo-missing", body
    assert not d.action.startswith("rejected:echo-mismatch"), body
    return d.accepted, d.action


print("### V-2: partition correctness — a name may only appear where TRUE ###")
for b, why in [
    ("The run did not complete successfully and bill-splitter was merged.", "TRUE  -> expect ACCEPT"),
    ("The run did not complete successfully and acceptance-tests was parked.", "TRUE  -> expect ACCEPT"),
    ("The run did not complete successfully and bill-splitter was parked.", "FALSE -> expect REFUSE"),
    ("The run did not complete successfully and bill-splitter was not merged.", "FALSE -> expect REFUSE"),
    ("The run did not complete successfully and acceptance-tests was merged.", "FALSE -> expect REFUSE"),
    ("The run did not complete successfully and acceptance-tests was skipped.", "TRUE  -> expect ACCEPT"),
    ("The run did not complete successfully and bill-splitter and acceptance-tests were merged.", "FALSE -> expect REFUSE"),
]:
    print(f"  {str(p(b)):45s} {why:28s} {b!r}")

print("\n### Q1: can the two halves be mismatched now? ###")
print("  _partition order:", pg._partition(PAIRS))
print("  merged set must be arg1 of _build_sentence_form; verify by swapping:")
m, u = pg._partition(PAIRS)
f_ok = pg._build_sentence_form(m, u, T.run_id)
f_swapped = pg._build_sentence_form(u, m, T.run_id)
print("   correct order, 'bill-splitter was merged'      :",
      bool(f_ok.fullmatch("bill-splitter was merged")))
print("   swapped order, 'bill-splitter was merged'      :",
      bool(f_swapped.fullmatch("bill-splitter was merged")))
print("   -> the order IS load-bearing; only one call site builds it.")

print("\n### Q2: malformed records — starve toward ACCEPT or REFUSE? ###")
CASES = [
    ("bare names (the OLD api)", ("bill-splitter", "acceptance-tests")),
    ("2-char strings (unpackable!)", ("ab", "cd")),
    ("None entries", (None, None)),
    ("wrong arity", (("a", "b", "c"), ("x",))),
    ("empty", ()),
    ("dicts", ({"task": "bill-splitter", "result": "MERGED"},)),
    ("good + malformed mix", (("bill-splitter", "MERGED"), "junk", None)),
]
live = "The run did not complete successfully and bill-splitter was merged."
for label, tr in CASES:
    try:
        part = pg._partition(tr)
        d = G.validate_run_summary(T, "INCOMPLETE: " + live, task_results=tr)
        print(f"  {label:28s} partition={part}  -> {d.accepted} {d.action}")
    except Exception as e:
        print(f"  {label:28s} RAISED {type(e).__name__}: {e}")

print("\n### Q2b: same task name with TWO results (retry) ###")
dup = (("bill-splitter", "MERGED"), ("bill-splitter", "PARKED"))
print("  partition:", pg._partition(dup))
print("  'bill-splitter was merged':", p("The run did not complete successfully and bill-splitter was merged.", dup))
print("  'bill-splitter was parked':", p("The run did not complete successfully and bill-splitter was parked.", dup))

print("\n### Q3: the GRADING instrument calls the guard with NO vocabulary ###")
G009 = ("INCOMPLETE: The run 20260721-111715-bd is marked as incomplete. The "
        "bill-splitter and acceptance-tests components were merged, but the "
        "overall run did not complete successfully.")
G9PAIRS = (("bill-splitter", "MERGED"), ("acceptance-tests", "MERGED"))
d_prod = G.validate_run_summary(T, G009, task_results=G9PAIRS)
d_grade = G.validate_run_summary(T, G009)          # what coordinator_graduation.py:605 does
print(f"  production  (task_results passed) -> {d_prod.accepted} {d_prod.action!r}")
print(f"  grading tool(no task_results)     -> {d_grade.accepted} {d_grade.action!r}")
print("  ^ the live false-suppression statement #1067 exists to buy back is")
print("    scored as STILL SUPPRESSED by the graduation instrument.")

print("\n### false-refusal re-measure (45 accurate sentences, full pairs) ###")
from a8 import ACCURATE
ref = [s for s in ACCURATE if not p(s)[0]]
print(f"  refused {len(ref)}/{len(ACCURATE)} = {100*len(ref)/len(ACCURATE):.1f}%")
for s in ref:
    if "parked" in s or "acceptance-tests" in s:
        print("    still dropped:", repr(s))
