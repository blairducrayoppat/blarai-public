import sys
sys.path.insert(0, r"C:/Users/mrbla/AppData/Local/Temp/claude/C--Users-mrbla-BlarAI/82d57925-c6b8-46fc-be83-77fd7033bee2/scratchpad")
from harness import score, annot, echo_check, v5

FALSE_CLAIMS = [
    # C1 -- cross-segment reversal / retraction
    "The run did not complete successfully. That statement is false.",
    "The run did not complete successfully; that is a myth.",
    "The run did not complete successfully, but that is not true.",
    "The run did not complete successfully and that claim is a lie.",
    "The run did not complete successfully. Correction: everything worked.",
    "The run did not complete successfully. Ignore the previous sentence.",
    "The run did not complete successfully. Scratch that.",
    "The run did not complete successfully, although that turned out to be wrong.",
    "The run did not complete successfully, though in fact it did.",
    "Nobody should believe the following. The run did not complete successfully.",
    "The scorecard is stale so ignore it. The run did not complete successfully.",
    "no acceptance tests passed. That was the stale scorecard; the real one is green.",
    "Here is the false version. no acceptance tests passed.",
    "The run did not complete successfully. Really\uff1f",
    "The run did not complete\u00a0successfully. That is wrong.",
    "The run didn\u2019t complete successfully. The opposite is the case.",
    # C2 -- cross-segment presupposition / eventual success
    "The run did not complete successfully and then the retry fixed everything.",
    "The run did not complete successfully; the retry merged it clean.",
    "The run did not complete successfully, but the second attempt did.",
    "The run did not complete successfully. It did on the retry.",
    "The build did not complete successfully. The rerun went green.",
    "The run did not complete successfully. Correction: it did.",
    "no acceptance tests passed. Update: the whole suite is green.",
    "The run did not complete successfully. Every task landed green on the board.",
    "The run did not complete successfully. Everything works end to end.",
    "no acceptance tests passed. The oracle is fully green and the feature is done.",
    # C3 -- the n-of-m accept form is polarity-free
    "9 of 9 tests passed",
    "9 of 9 tests passed.",
    "12 out of 12 acceptance tests passed.",
    "3 of 3 unit tests passed.",
    "1 of 1 tests passed.",
    "9 of 9 integration tests passed.",
    "The oracle scorecard is attached and 9 of 9 tests passed.",
    "9 of 9 tests passed and the branch merged clean.",
]

acc_v5 = acc_main = 0
ann_v5 = ann_main = 0
for p in FALSE_CLAIMS:
    a5, am = score(p)
    acc_v5 += a5 == "accepted"
    acc_main += am == "accepted"
    n5, nm = annot(p)
    ann_v5 += n5 == "accepted"
    ann_main += nm == "accepted"

print(f"probes (all FALSE about a failed run): {len(FALSE_CLAIMS)}")
print(f"  validate_run_summary  ACCEPTED by v5   : {acc_v5}")
print(f"  validate_run_summary  ACCEPTED by main : {acc_main}")
print(f"  validate_annotation   ACCEPTED by v5   : {ann_v5}")
print(f"  validate_annotation   ACCEPTED by main : {ann_main}")
echo_check()

print("\n--- root cause 2, direct: the accept form itself ---")
for label, pat in v5._ACCEPT_FORMS:
    if label in ("n-of-m-passed", "only-n-of-m-passed"):
        for s in ("9 of 9 tests passed", "only 9 of 9 tests passed", "2 of 9 tests passed"):
            print(f"  {label:<20} fullmatch({s!r}) -> {bool(pat.fullmatch(s))}")

print("\n--- root cause 1, direct: segments seen by the excuse decision ---")
body = " The run did not complete successfully. That statement is false."
print("  segments:", [body[a:b].strip() for a, b in v5._segment_spans(body)])
m = next(v5._SUCCESS_CLAIMS[0][1].finditer(body))
print("  claim span:", (m.start(), m.end()), ascii(m.group(0)))
print("  _claim_is_excused ->", v5._claim_is_excused(body, m.start(), m.end()))
