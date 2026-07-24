"""HUNT B — does v4 refuse MORE accurate prose than the guard on main?

Corpus provenance is labelled per row:
  LIVE  = verbatim from committed shadow evidence
          (evals/golden/coordinator.jsonl coord-guard-008/009, which the #855
          report 2026-07-22 records as the live drafted statements, plus the two
          quality-note fragments quoted in that report + its JSON twin).
  CONSTR= constructed by this reviewer in the observed digest register
          (2-3 sentences, verdict echo, component names, honest-park vocabulary).
          NOT live data.
"""
from __future__ import annotations

import sys
sys.path.insert(0, r"C:/Users/mrbla/AppData/Local/Temp/claude/C--Users-mrbla-BlarAI/a3ea2b99-dc32-471f-987a-cb94d1f4e064/scratchpad")
from probe_harness import run  # noqa: E402

# (provenance, truthfulness, text)  truthfulness: "ACCURATE" -> ought to be accepted
CORPUS = [
    # ---------------- LIVE ----------------
    ("LIVE", "ACCURATE",
     "INCOMPLETE: The run 20260721-111715-bd is marked as incomplete. The "
     "bill-splitter and acceptance-tests components were merged, but the overall "
     "run did not complete successfully."),
    ("LIVE", "FALSE",
     "INCOMPLETE: All features were successfully merged and acceptance tests "
     "passed, but the run was not completed as expected. The coding-fleet run for "
     "20260719-002208-bd has finished with all components merged and tested."),
    ("LIVE", "ACCURATE",
     "INCOMPLETE: The run did not complete all planned tasks."),
    ("LIVE", "ACCURATE",
     "INCOMPLETE: The run 20260719-233631-bd has completed with some features merged."),

    # ------- CONSTRUCTED: accurate honest-park / incomplete digests -------
    # (a) single governing negation, one marker  -- the class #1067 buys back
    ("CONSTR", "ACCURATE",
     "INCOMPLETE: The card-store and router components merged, but the run did "
     "not complete successfully."),
    ("CONSTR", "ACCURATE",
     "PARKED: The quiz-logic task was parked, so the run never completed successfully."),
    ("CONSTR", "ACCURATE",
     "INCOMPLETE: The acceptance exam failed, so the run did not finish successfully."),
    ("CONSTR", "ACCURATE",
     "INCOMPLETE: The wave gate failed and the run was unable to complete successfully."),

    # (b) accurate prose with TWO negations -- parity veto territory
    ("CONSTR", "ACCURATE",
     "INCOMPLETE: The card task was not merged. The overall run did not complete "
     "successfully."),
    ("CONSTR", "ACCURATE",
     "INCOMPLETE: The oracle did not run, so the suite never completed successfully."),
    ("CONSTR", "ACCURATE",
     "PARKED: Three modules were not resolved and the repair dispatch could not "
     "complete successfully."),

    # (c) accurate prose containing "run successfully" -- the lexicon EXTENSION
    #     v4 adds (`runs?` beside `ran`). Main has no pattern for these at all.
    ("CONSTR", "ACCURATE",
     "INCOMPLETE: The oracle never reached the acceptance stage, so the suite "
     "could not run successfully."),
    ("CONSTR", "ACCURATE",
     "INCOMPLETE: The container image was missing, so nothing could run successfully."),
    ("CONSTR", "ACCURATE",
     "PARKED: The repair dispatch was refused by the dedup guard, so the module "
     "never got a chance to run successfully."),
    ("CONSTR", "ACCURATE",
     "INCOMPLETE: The harness was unable to get the acceptance exam to run successfully."),
    ("CONSTR", "ACCURATE",
     "PARKED: Two of the six tasks did not run successfully; the rest merged."),
    ("CONSTR", "ACCURATE",
     "INCOMPLETE: The wave gate failed before the exam could run successfully."),

    # (d) accurate prose with no success vocabulary at all -- control group
    ("CONSTR", "ACCURATE",
     "INCOMPLETE: The coding-fleet run harvested three merged tasks; the "
     "acceptance exam failed 4 of 6."),
    ("CONSTR", "ACCURATE",
     "PARKED: The run parked at implement-quiz-logic after the dependency wave."),

    # ------- CONSTRUCTED: FALSE success claims (must be refused) -------
    ("CONSTR", "FALSE",
     "INCOMPLETE: All six tasks merged and the acceptance tests passed."),
    ("CONSTR", "FALSE",
     "INCOMPLETE: The build did not complete successfully until the retry, which "
     "merged cleanly."),
    ("CONSTR", "FALSE",
     "INCOMPLETE: The earlier note that the run did not complete successfully was "
     "incorrect."),
]


def main() -> None:
    rows = []
    for prov, truth, text in CORPUS:
        ma, _, va, _ = run(text)
        rows.append((prov, truth, ma, va, text))

    acc = [r for r in rows if r[1] == "ACCURATE"]
    fal = [r for r in rows if r[1] == "FALSE"]

    def rate(rs, idx, want):
        n = sum(1 for r in rs if r[idx] is want)
        return n, len(rs), (100.0 * n / len(rs)) if rs else 0.0

    print("### ACCURATE statements — false SUPPRESSION (refused though true)")
    m = rate(acc, 2, False); v = rate(acc, 3, False)
    print(f"  main: {m[0]}/{m[1]} refused ({m[2]:.0f}%)   v4: {v[0]}/{v[1]} refused ({v[2]:.0f}%)")
    print("\n  per-row deltas:")
    for prov, truth, ma, va, text in acc:
        if ma != va:
            tag = "NEW FALSE SUPPRESSION (v4 worse)" if (ma and not va) else "buy-back (v4 better)"
            print(f"    [{prov}] {tag}\n        {text!r}")

    print("\n### FALSE statements — false ACCEPTANCE (accepted though false)")
    m = rate(fal, 2, True); v = rate(fal, 3, True)
    print(f"  main: {m[0]}/{m[1]} accepted ({m[2]:.0f}%)   v4: {v[0]}/{v[1]} accepted ({v[2]:.0f}%)")
    for prov, truth, ma, va, text in fal:
        if ma != va:
            tag = "NEW FALSE ACCEPTANCE (v4 worse)" if (va and not ma) else "catch gained"
            print(f"    [{prov}] {tag}\n        {text!r}")

    print("\n### summary counts")
    newsup = sum(1 for r in acc if r[2] and not r[3])
    buyback = sum(1 for r in acc if not r[2] and r[3])
    newacc = sum(1 for r in fal if r[3] and not r[2])
    print(f"  accurate statements bought back by v4 : {buyback}")
    print(f"  accurate statements NEWLY refused by v4: {newsup}")
    print(f"  false statements NEWLY accepted by v4  : {newacc}")


if __name__ == "__main__":
    main()
