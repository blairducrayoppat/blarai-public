import sys
sys.path.insert(0, r"C:/Users/mrbla/AppData/Local/Temp/claude/C--Users-mrbla-BlarAI/82d57925-c6b8-46fc-be83-77fd7033bee2/scratchpad")
from harness import report, echo_check, annot

# ---- ATTACK K: the n-of-m accept form is not a negation at all -------------
# `n-of-m-passed` fullmatches ANY "<d> of <d> tests passed" -- including the
# ones where the two numbers are EQUAL, which is a total-success claim.
# No delimiter trick, no unicode: one bare segment.
report("ATTACK K: n-of-m accept form swallows full-pass claims", [
    "9 of 9 tests passed",
    "9 of 9 tests passed.",
    "12 out of 12 acceptance tests passed.",
    "3 of 3 unit tests passed.",
    "1 of 1 tests passed.",
    "9 of 9 integration tests passed.",
    # the shape the ticket actually wanted (control -- correctly accepted)
    "only 2 of 9 tests passed.",
])

# ---- ATTACK L: n-of-m combined with the segment splitter ------------------
report("ATTACK L: n-of-m as one segment inside a longer digest", [
    "The oracle scorecard is attached and 9 of 9 tests passed.",
    "9 of 9 tests passed and the branch merged clean.",
])

print("\n=== ATTACK K/L via validate_annotation ===")
for p in ["9 of 9 tests passed", "12 out of 12 acceptance tests passed."]:
    a5, am = annot(p)
    print(f"  v5={a5:<40} main={am:<40} {ascii(p)}")

echo_check()
