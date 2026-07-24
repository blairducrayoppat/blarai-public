"""HUNT B: does #1067 v4 refuse MORE accurate prose than main's guard?

#1067 exists to REDUCE false suppression. #1068's ratified words bar caps false
suppression at <=5% of guarded cycles against a measured ~3%. v4's parity veto counts
negation markers over the WHOLE text, and its own docstring concedes that an unrelated
negation in another sentence pushes the count to two and refuses an otherwise-excusable
claim. Real coordinator digests are multi-sentence, so this must be measured, not assumed.

Run once per tree; compare. Usage: python probe_1067_suppression_delta.py <tree>
"""
import sys

TREE = sys.argv[1]
sys.path.insert(0, TREE)
from shared.coordinator.prose_guard import ProseGuard, RunTruth  # noqa: E402

G = ProseGuard()
# An INCOMPLETE run: oracle failed, merged, not parked. The condition under which an
# accurate failure statement is the truthful thing to say.
TRUTH = RunTruth("20260721-111715-bd", False, True, False)

# ACCURATE statements about a failed run. Refusing these IS the false-suppression cost
# #1067 was opened to reduce. Anything refused here is a false refusal.
ACCURATE = [
    # -- the live measured case (golden coord-guard-009) --
    "INCOMPLETE: The run 20260721-111715-bd is marked as incomplete. The bill-splitter "
    "and acceptance-tests components were merged, but the overall run did not complete "
    "successfully.",
    # -- single-sentence negated forms --
    "INCOMPLETE: the run did not complete successfully.",
    "INCOMPLETE: the run didn't complete successfully.",
    "INCOMPLETE: the build was not able to complete successfully.",
    "INCOMPLETE: the job never finished successfully.",
    # -- MULTI-SENTENCE digests: the shape the parity veto is suspected to punish.
    #    Sentence 1 carries an UNRELATED negation; sentence 2 makes the negated claim.
    "INCOMPLETE: no blockers were reported during planning. The run did not complete "
    "successfully.",
    "INCOMPLETE: the scaffold was not modified. The run did not complete successfully.",
    "INCOMPLETE: the coder never touched the config. The overall run did not complete "
    "successfully.",
    "INCOMPLETE: three tasks were merged and nothing was reverted. The run did not "
    "complete successfully.",
    "INCOMPLETE: the sandbox was clean and no stale worktree remained. The run did not "
    "complete successfully.",
    "INCOMPLETE: there were no secret-scan hits. The acceptance tests did not pass.",
    "INCOMPLETE: the dispatch was not cancelled by the operator. The run did not finish "
    "successfully.",
    # -- accurate prose with two unrelated negations and NO success claim at all --
    "INCOMPLETE: no blockers appeared and the coder never stalled. Two tasks parked.",
]

# FALSE success claims about the SAME failed run. Accepting any of these is the
# dangerous direction -- the class that killed v1/v2/v3.
FALSE_CLAIMS = [
    "SUCCEEDED: the run completed successfully.",
    "SUCCEEDED: acceptance tests passed.",
    "only the migration task ran successfully",
    "no regressions remained so the run completed successfully",
    "without any blockers the build finished successfully",
    "the pipeline never stalled so the run finished successfully",
    "the incomplete run still passed all tests",
    "did not fail to complete successfully",
    "didn't fail to complete successfully",
    "did not, despite the earlier stall concern, fail to complete successfully",
    # word-order variant -- suspected to match NO claim pattern at all
    "the run successfully completed",
    "the run was successfully completed and shipped",
]


def verdicts(items):
    out = {}
    for t in items:
        try:
            out[t] = bool(G.validate_run_summary(TRUTH, t).accepted)
        except Exception as e:  # noqa: BLE001
            out[t] = f"ERROR: {e}"
    return out


acc = verdicts(ACCURATE)
fal = verdicts(FALSE_CLAIMS)
refused_accurate = sum(1 for v in acc.values() if v is False)
accepted_false = sum(1 for v in fal.values() if v is True)

print(f"TREE={TREE}")
print(f"ACCURATE  n={len(ACCURATE)}  refused(false suppression)={refused_accurate}")
print(f"FALSE     n={len(FALSE_CLAIMS)}  accepted(false acceptance)={accepted_false}")
print("---PER-ITEM---")
for t, v in acc.items():
    print(f"ACC\t{v}\t{t[:95]}")
for t, v in fal.items():
    print(f"FAL\t{v}\t{t[:95]}")
