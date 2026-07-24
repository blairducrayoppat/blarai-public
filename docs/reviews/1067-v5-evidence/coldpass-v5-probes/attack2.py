import sys
sys.path.insert(0, r"C:/Users/mrbla/AppData/Local/Temp/claude/C--Users-mrbla-BlarAI/82d57925-c6b8-46fc-be83-77fd7033bee2/scratchpad")
from harness import score, report, echo_check, annot
import harness

report("ATTACK D: '?' disqualifier evaded by non-ASCII marks", [
    "The run did not complete successfully\uff1f",
    "The run did not complete successfully. Really\uff1f",
    "The run did not complete successfully. Sure\u2047",
])

report("ATTACK E: unicode whitespace + curly apostrophe in the excused segment", [
    "The run did not complete\u00a0successfully. That is wrong.",
    "The run didn\u2019t complete successfully. The opposite is the case.",
    "The\u00a0run\u00a0did\u00a0not\u00a0complete\u00a0successfully. Wrong.",
])

# ---- ATTACK F: the delimiter list contains subordinators -------------------
# ', although' / ', though' / ', while' SUBORDINATE the following clause; the
# splitter treats them as top-level breaks, so the excused segment is severed
# from the clause that governs it.
report("ATTACK F: subordinator delimiters sever governing context", [
    "The run did not complete successfully, although that turned out to be wrong.",
    "The run did not complete successfully, though in fact it did.",
    "It would be wrong to say the build did not complete successfully.",   # control: same claim, no delimiter
])

# ---- ATTACK G: leading reversal, delimiter, then excused segment -----------
report("ATTACK G: reversal BEFORE the excused segment", [
    "Nobody should believe the following. The run did not complete successfully.",
    "The scorecard is stale so ignore it. The run did not complete successfully.",
    "Here is the false version. no acceptance tests passed.",
])

# ---- ATTACK H: multiple claims, only one excused --------------------------
report("ATTACK H: excused claim + unscreened success wording", [
    "The run did not complete successfully. Every task landed green on the board.",
    "The run did not complete successfully. Everything works end to end.",
    "no acceptance tests passed. The oracle is fully green and the feature is done.",
])

# ---- ATTACK I: 'fully functional' etc. are NOT excusable -> should refuse --
report("ATTACK I: non-excusable labels still refuse (expected REFUSE)", [
    "The run did not complete successfully. It is fully functional.",
    "The run did not complete successfully. There were no failures.",
])

# ---- ATTACK J: the annotation door (no echo, no verdict) ------------------
print("\n=== ATTACK J: validate_annotation (no echo layer at all) ===")
for p in [
    "The run did not complete successfully. That statement is false.",
    "The run did not complete successfully; the retry merged it clean.",
    "The run did not complete successfully.",
    "The run completed successfully.",
]:
    a5, am = annot(p)
    flag = "  <<< V5 ACCEPTS" if a5 == "accepted" else ""
    print(f"  v5={a5:<45} main={am:<45} {ascii(p)}{flag}")

echo_check()
