"""HUNT A — false acceptance probes against the v4 guard."""
from __future__ import annotations

import sys
sys.path.insert(0, r"C:/Users/mrbla/AppData/Local/Temp/claude/C--Users-mrbla-BlarAI/a3ea2b99-dc32-471f-987a-cb94d1f4e064/scratchpad")
from probe_harness import run, GUARD_V4, TRUTH_V4, pg_v4  # noqa: E402

# Each entry: (text, why_it_is_a_false_success_claim)
ATTACKS = [
    # --- A1: POSTPOSED meta-negation. The veto lexicon scopes its polarity
    #         flippers as "<adj> that"; moving the adjective AFTER the clause
    #         walks straight past the boundary. Same words, different order.
    ("The claim that the run did not complete successfully is false.",
     "asserts the run DID complete"),
    ("The earlier report that the run did not complete successfully was incorrect.",
     "asserts the run DID complete"),
    ("The suggestion that the build did not finish successfully is untrue.",
     "asserts the build DID finish"),
    ("That the run did not complete successfully is simply wrong.",
     "asserts the run DID complete"),
    # --- A2: PRE-posed meta-negation using flippers NOT in the veto lexicon.
    ("It is a lie that the run did not complete successfully.",
     "asserts the run DID complete"),
    ("It is a myth that the run did not complete successfully.",
     "asserts the run DID complete"),
    ("It is a misconception that the build did not finish successfully.",
     "asserts the build DID finish"),
    ("It is nonsense that the run did not complete successfully.",
     "asserts the run DID complete"),
    ("It is misleading to say that the run did not complete successfully.",
     "asserts the run DID complete"),
    ("It is wrong to say the run did not complete successfully.",
     "'wrong' IS in the veto lexicon but only as 'wrong that'"),
    ("I dispute that the run did not complete successfully.",
     "asserts the run DID complete"),
    ("I disagree that the run did not complete successfully.",
     "asserts the run DID complete"),
    ("Nobody would claim that the run did not complete successfully.",
     "asserts the run DID complete"),
    ("No one can seriously argue the run did not complete successfully.",
     "asserts the run DID complete"),
    ("The suggestion that the build did not finish successfully has been refuted.",
     "asserts the build DID finish"),
    ("The idea that the run did not complete successfully is mistaken.",
     "asserts the run DID complete"),
    # --- A3: counterfactual / temporal presupposition — natural digest prose.
    ("Had the run not completed successfully, the board would show PARKED.",
     "counterfactual presupposes the run DID complete"),
    ("The build did not complete successfully until the retry, which merged cleanly.",
     "'not X until Y' presupposes X happened at Y"),
    ("The suite did not run successfully until the third attempt.",
     "presupposes it ran successfully on the third attempt"),
    ("The run did not complete successfully at first, but everything is green now.",
     "'at first' + 'green now' asserts eventual success"),
    # --- A4: government-chain probes on the AUX allowlist (to / able / been).
    ("The run did not have to be able to get tests passed.",
     "AUX chain 'have to be able to get' spans a full verb complex"),
    ("The fix was not able to be fully properly completed successfully.",
     "long AUX chain"),
    # --- A5: rhetorical question — the guard has no clause-type awareness.
    ("Did the run not complete successfully? The board says otherwise.",
     "interrogative, not an assertion of failure"),
]


def main() -> None:
    hits = []
    for text, why in ATTACKS:
        ma, mact, va, vact = run(text)
        status = "ACCEPTED" if va else "refused "
        if va:
            hits.append((text, why))
        print(f"v4={status}  main={'ACC' if ma else 'REJ'}  {text!r}")
        if va:
            print(f"        ^^^ FALSE ACCEPTANCE: {why}")
    print(f"\n--- {len(hits)} / {len(ATTACKS)} accepted by v4 ---")
    for t, w in hits:
        n = len(pg_v4._NEGATION_MARKER_RE.findall(t))
        print(f"  markers={n}  {t!r}")


if __name__ == "__main__":
    main()
