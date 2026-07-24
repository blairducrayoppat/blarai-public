"""V2: verify F-1/F-2/F-3 fixes; attack the new bound; find what broke."""
import sys
sys.path.insert(0, r"C:/Users/mrbla/wt-1067-v7")
from shared.coordinator import prose_guard as pg

T = pg.RunTruth(run_id="20260721-111715-bd", oracle_passed=False, merged=False, parked=False)
G = pg.ProseGuard()
# LIVE derivation now yields MERGED names only.
MERGED_ONLY = ("bill-splitter",)
BOTH = ("bill-splitter", "acceptance-tests")


def p(body, names=MERGED_ONLY):
    d = G.validate_run_summary(T, "INCOMPLETE: " + body, task_names=names)
    assert d.action != "rejected:echo-missing", body
    assert not d.action.startswith("rejected:echo-mismatch"), body
    return d.accepted, d.action


print("### F-1: the blocker probes must now REFUSE ###")
for b in ["only 999 out of 1000 unit tests passed.",
          "only 8 of 9 acceptance tests passed.",
          "The run did not complete successfully, but only 8 of 9 acceptance tests passed.",
          "only 5 of 9 tests passed.",
          "only 9 of 9 tests passed."]:
    print(f"  {p(b)}  <- {b!r}")
print("  ticket's own form:", p("only 2 of 9 tests passed."))
print("  boundary 4/9 (<=half):", p("only 4 of 9 tests passed."))
print("  boundary 5/10 (exactly half):", p("only 5 of 10 tests passed."))
print("  boundary 0/9:", p("only 0 of 9 tests passed."))

print("\n### F-1 evasion hunt on _asserts_a_minority ###")
EV = [
    "only 1 of 2 tests passed.",
    "only 500 of 1000 tests passed.",
    "only 8 of 9 tests passed and only 1 of 9 tests passed.",
    "only 1 of 9 tests passed and only 8 of 9 tests passed.",
    "only 08 of 9 tests passed.",
    "only 8 of 90 tests passed.",
    "only \u0668 of \u0669 tests passed.",       # arabic-indic 8 of 9
    "only \u0664 of \u0669 tests passed.",       # arabic-indic 4 of 9
    "only 000000004 of 9 tests passed.",
]
for b in EV:
    print(f"  {p(b)}  <- {b.encode('ascii','backslashreplace').decode()!r}")

print("\n### F-2: false merge claim with a PARKED name must now REFUSE ###")
b2 = "The run did not complete successfully and the bill-splitter and acceptance-tests components were merged."
print("  live vocab (merged-only):", p(b2, MERGED_ONLY))
print("  if BOTH were passed     :", p(b2, BOTH), " <- the eval harness still does this")
print("  merged name alone       :", p("The run did not complete successfully and bill-splitter was merged.", MERGED_ONLY))

print("\n### F-3: quantifier names ###")
print("  ('all','bill-splitter'):",
      p("The run did not complete successfully but all tasks were merged.", ("all", "bill-splitter")))
print("  _usable_terms quantifiers:",
      sorted(pg._usable_terms(frozenset({"all","every","everything","each","both","entire","whole","any","none","nothing","everyone"}))))

print("\n### REGRESSION HUNT: the not-merged clause can now only name MERGED tasks ###")
NEG = [
    "The run did not complete successfully and acceptance-tests was parked.",
    "The run did not complete successfully and the acceptance-tests component was not merged.",
    "The run did not complete successfully, but acceptance-tests was skipped.",
    "The run did not complete successfully and acceptance-tests was not run.",
]
for b in NEG:
    print(f"  live vocab {p(b, MERGED_ONLY)}   pre-fix vocab {p(b, BOTH)}   <- {b!r}")

print("\n### is run_id a 4th variable position the new enumeration omits? ###")
print("  rid form:", p("The run 20260721-111715-bd is marked as incomplete.", MERGED_ONLY))
print("  wrong rid:", p("The run 99999999-999999-zz is marked as incomplete.", MERGED_ONLY))
