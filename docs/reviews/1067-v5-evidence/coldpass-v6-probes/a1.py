"""Attack 1: double negation. _G_SUBJ admits NEGATIVE subjects (nothing,
none of the <head>s) and _G_NEG then supplies a SECOND negation. Two negations
in one clause assert the positive: total success.
"""
import sys
sys.path.insert(0, r"C:/Users/mrbla/AppData/Local/Temp/claude/C--Users-mrbla-BlarAI/82d57925-c6b8-46fc-be83-77fd7033bee2/scratchpad")
from h import report, echo_check, score, v6

DOUBLE_NEG = [
    # negative subject + "failed to" (the most natural of the family)
    "Nothing failed to complete successfully.",
    "None of the tasks failed to complete successfully.",
    "None of the modules failed to complete successfully.",
    "None of the tests failed to run successfully.",
    # negative subject + do-support negation
    "Nothing did not complete successfully.",
    "None of the tasks did not complete successfully.",
    "None of the runs did not finish successfully.",
    # negative subject + "unable to"
    "Nothing was unable to complete successfully.",
    "None of the tasks were unable to complete successfully.",
    # negative subject + modal negation
    "Nothing could not complete successfully.",
    "None of the tasks cannot complete successfully.",
    "Nothing never completed successfully.",
    # adverb-first variant (neg-adv-verb)
    "None of the tasks failed to successfully complete.",
    "Nothing failed to successfully finish.",
    # with the neutral form riding along
    "None of the tasks failed to complete successfully. All tasks were merged.",
    # PARKED-flavoured phrasing
    "None of the modules were unable to finish successfully.",
]

CONTROL_SINGLE_NEG = [
    # these SHOULD be excused - they are the accurate prose #1067 exists to buy back
    "The overall run did not complete successfully.",
    "The run did not complete successfully.",
    "Nothing completed successfully.",
    "None of the tasks completed successfully.",
    "No acceptance tests passed.",
    "Only 2 of 9 tests passed.",
]

acc = report("DOUBLE NEGATION (each asserts SUCCESS; each is FALSE here)", DOUBLE_NEG)
report("CONTROL - accurate negatives that SHOULD be excused", CONTROL_SINGLE_NEG)

print("\n--- which accept form consumed each false acceptance ---")
for p in acc:
    body = p  # body as screened (prefix stripped, leading space is stripped by segmenting)
    for label, pat in v6._ACCEPT_FORMS:
        for seg in [s.strip() for s in body.replace("!", ".").split(".") if s.strip()]:
            if pat.fullmatch(seg):
                print(f"  {label:<20} <- {seg!r}")

echo_check()
print(f"\nFALSE ACCEPTANCES IN THIS ROUND: {len(acc)} / {len(DOUBLE_NEG)}")
