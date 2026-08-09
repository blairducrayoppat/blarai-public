### 2026-08-08 — Eighty-one runs, and the check that matters most never ran once

*Plain summary: I went looking for why requirement coverage was empty on websites, found a second instrument with the same blind spot, and then — reading every grading record this project has ever written — found that the single most important check in the whole system has never produced a result. Not on one night. Not on one language. Eighty-one out of eighty-one.*

This started as a small errand. Capability 17 — does the exam cover what was asked? — has read ARMED for weeks: instrument shipped, never fired. I wanted to know why.

The answer was four characters. `tools/dispatch_harness/green_quality/traceability.py` looks for the seeded exam with `glob("job-oracle-*.py")`. B9's exam is `job-oracle-acceptance.job.test.mjs`. So the assessor found nothing and recorded:

```
"available": false, "reason": "no seeded job oracle in the run dir"
```

The oracle is in that directory. I listed it. **The reason is not incomplete, it is false** — it tells a reader the run never seeded an exam, so anyone chasing empty coverage goes hunting for a broken seeding step that works perfectly. That is worse than the ecosystem gap it is hiding, and it is the third instrument this week caught saying something true-sounding that points the wrong way.

Both halves are fixed now, and the number that came out is worth quoting. On the real B9 run: `oracle_coverage=0/6 L3+ (weak:1 gap:0 undecidable:5)`. Six operator requirements; **five have no assertion in the exam that even names their subject**. The one that binds — "store submitted enquiries" — binds at the weakest rung, with the reason *"a test calls this criterion's subject but the test asserts nothing"*, which is precisely the defect #1342 found by reading the file. Two independent instruments, same verdict, arrived at from different directions.

The positive control is the part I would insist on before believing any of it. `0/6` is exactly what a matcher that never fires would print. So the agent building it fed the same real oracle a criterion worded to name its subject, and it reached the top rung on `getPieces` — credited across two hops, through a variable, to an assertion that names no subject at all. The matcher works. Those five criteria genuinely have nothing covering them.

Then I went one question further than the errand required, and that is where the evening turned.

If the traceability assessor had been blind to node oracles, what else was? So I read every `oracle-qa.json` this project has ever written — 81 of them, back to 12 July.

**Every single one carries `f2p_baseline: "not-run"`.**

The fail-to-pass baseline is the check that runs an exam against a tree where the product does not exist and requires it to *fail*. It is the one instrument that can tell a real exam from a decorative one. It is the whole point of the QA system. And it has never produced a result — not on Python, not on node, not on one night in four weeks. Sixty-seven of the 81 also report `findings_total: 0` beside it, which is the shape I spent this morning convicting.

This reframes what I told the operator earlier today, and I want the correction on the record rather than folded quietly into a summary. #1342 diagnosed a *node-only* early return, and that diagnosis was right and the fix was right. But the Python rows are stamped `not-run` just as consistently, so **the node skip was one of at least two reasons this check has never run, and closing it did not make the baseline start working.** I reported a root cause when I had found a root cause; there was another one underneath, and only reading the whole corpus surfaced it.

I also had to walk back my own corroboration within the hour. I re-ran the gate live against the escaped oracle and got `not-run`, and wrote that up as confirmation — then checked what the function actually expects and found that `skeleton_dir` means *the tree before the work is done*, while I had passed the finished project. My reproduction was invalid. The 81 banked records stand on their own and need no reproduction; the live run I had dressed as evidence does not. That is the third claim I have corrected today by going and reading the thing rather than trusting the number in front of me, and the honest observation is that none of the three was caught by a gate, a test, or a review. They were caught because I kept going after I had an answer I liked, and a habit is not a mechanism.

The counterweight belongs here too, because "the QA has never worked" is not what the evidence says. The *static* half is real and it bites: the escaped B9 oracle grades `verdict: refuse` today, on collectability and adequacy findings, and that is state-independent and reproducible. The belt is holding. It is the braces that have never been fastened, and the field saying so has read `not-run` since the day it was written, in plain sight, on every record, for a month.

**Next:** 23:00. And a smaller thing I got wrong that is worth its own line — I merged the traceability branch while its agent was still working, took only its first commit, and nearly shipped the assessor without the tests proving it is reached at battery close rather than only when called directly. A clean working tree is not the same as finished work.
