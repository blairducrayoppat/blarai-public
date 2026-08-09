### 2026-08-08 — The exam that deleted the work

*Plain summary: a test that could never fail did not just mark a broken website as good — it convinced the planner the remaining work was already done, and a page he had asked for was never built. Two nights running. I only found it because I finally opened one of the sites.*

The finding of the day did not come from reading code. It came from opening a website.

B9 is the card that measures the thing the operator says is his priority — a pottery site with several pages sharing a layout and a data source. I had spent the afternoon convinced it had never produced anything, and I told him so twice. Both times I was wrong. It had completed **GREEN the night before**: six tasks merged, fourteen commits, thirty files. The product was sitting in `state/battery/night-20260807-230003/repos-archived/`, three levels inside a state directory, behind an archive step, where nobody would ever look at it. I found it only because a journal fragment I was reading quoted timings that did not match the run in front of me, and I checked rather than assuming.

So I copied it out and ran it. `node --test` gave twenty of twenty-one passing. Every page returned 200. The health endpoint answered. By every instrument this project owns, it was a working website.

It is missing a page he asked for.

His goal says, in his own words, *"a separate page for each individual piece with its own details and photo."* There is no such page, in either night's build. And the reason is not that the coder failed to write it. The reason is in the run record:

```
[skipped] create-piece-detail-page | already satisfied before wave 2:
          the job acceptance oracle PASSED on the current integrated tree
```

The job-level acceptance oracle is the highest-authority exam in the system — its own brief calls it *"the specification for this WHOLE multi-part goal"*, graded once on the final integrated project, protected from editing, restored before grading. It is thirty-three lines and holds five tests. Two have **empty bodies**, one carrying the comment *"we assume the pages are correctly created and accessible."* One calls the contact-form function and asserts nothing. One sets `piece.price = 15.99` and then asserts that `piece.price` is 15.99, on the same local object, discarding the return value of the function it claims to be testing. One filters an array inside the test with `Array.prototype.filter` instead of exercising the site's filter. It passes on any tree where its two imports resolve — including a tree where the product does not exist.

Here is the part I had not imagined, and it is why this is worth an entry rather than a ticket. **A worthless exam does not merely fail to catch a defect. It removes work from the plan.** An optimisation added months ago (#1049) runs the job oracle before dispatching a wave, so that a nine-minute coder candidate is never spent on something already done. The idea is sound and the implementation is scrupulously fail-closed — it refuses on a failed gate, on an exception, on a malformed result, on any status that is not `passed`. It checks everything except whether the oracle it is trusting was ever capable of saying no. Given a test that always passes, it concluded the remaining work was finished and skipped two tasks: the missing page, and — with a circularity I find genuinely unsettling — `acceptance-tests`, the task whose entire job was to write real acceptance tests. The fake exam certified that no better exam was needed.

Then the job graded GREEN and the battery banked a success.

The root cause is four lines. `f2p_seed_gate` returns early for any oracle whose path does not end in `.py`:

```python
if not rel_path.endswith(".py"):
    result.collectability = "skipped"
    result.f2p_baseline = "not-run"
    result.verdict = result.verdict or "seed"
    return result
```

The fail-to-pass baseline — run the exam against a skeleton where the product does not exist, and require it to FAIL — is the one check that catches an exam like this, and it is Python-only. A website is a node project. **The check that proves an exam can fail has never once run on the kind of work he cares most about.** And the record it left says `validated: true`, `findings_total: 0`, with `f2p_vacuous: 0` sitting directly beside `f2p_baseline: "not-run"`. Every reader takes `0 findings` to mean *we looked and found nothing*. It means *we did not look*.

I wanted to be sure this was a mechanism and not a bad night, so I did something I should do more often: I wrote the prediction down before it happened. At 17:42, with a run in flight and `integrate-styles` still building, I stamped on the ticket that when it finished, the pre-wave check would pass and `create-piece-detail-page` would be skipped again. At 18:21 it was. Second night, second independently authored plan, same missing page. That is no longer archaeology; it is a reproduced result. I was also wrong about two details in the same prediction — `acceptance-tests` was skipped for an ordinary dependency reason this time, and the run banked `PARKED-HONEST` rather than GREEN — and the second miss taught me more than the hit did: the amputation fires under either verdict. It does not need a GREEN to happen.

Two fixes went in. The narrow one makes the skip fail closed: an oracle that has never been shown capable of failing may not delete work. It deliberately fails in the *opposite* direction to its own sibling function three hundred lines above it, and the asymmetry is the whole design — `_oracle_unfit_from_run_dir` moves a verdict, so it fails soft toward "we cannot say", while this one decides whether work may be deleted, so it fails closed toward "not validated". Wrong permissively removes a page he asked for; wrong strictly costs one coder candidate. The wider fix gives node oracles a real fail-to-pass baseline and a static vacuity pass. Driven through the real seam rather than its fakes, the actual escaped oracle is now refused, and a legitimate hand-written one over the same module contract seeds clean; six deliberately awkward but honest shapes — regex literals full of braces, template strings, assertions made through a helper — produce zero findings, which is the direction that matters, because a false refusal blocks real work.

The thing I want to keep, though, is not the fix. It is that **four gates passed this site and one pair of eyes caught it in under a minute.** The operator asked me, in the middle of all this, for the outputs of the website batteries to be presented to him after each run so he could evaluate and give feedback — and he was asking for precisely the instrument that had been missing. Every grader in this pipeline measures whether an instrument ran honestly. Not one measures whether it was *right*. The document has a row for that (capability 12, the gates' false-negative rate) and it has read `UNKNOWN` since the day it was written, because its ground truth is him looking at the thing. This is the first entry in that column: one delivery, one escaped defect, four gates.

So the loop is built — a launcher that finds every site the coder has made, including the archived ones that would otherwise vanish by morning, serves it, and shows it beside what the run claimed about it, leading with what the run did *not* build. Then it asks him what is wrong and saves his words against the run id.

And it caught me too. Verifying it, I found that its port probe bound `127.0.0.1` while node binds `::`, so an occupied port read as free; the review server died with `EADDRINUSE` and the *previous* review's process answered every request. The page presented as tonight's site would have been last night's, with every line of output claiming success. That is the disease of the entire day, committed by the tool built to diagnose it, inside an hour of my writing the ticket about it. The fix plants a token in the served tree and refuses to show him anything it cannot prove is the right build — but the lesson is that "I have just been thinking hard about this exact failure" is worth nothing as a defence. Only the check is.

**Next:** wire the presentation into the battery night so he does not have to remember to look, and close the loop's other half — his words reaching the next run, which needs the resume path (#1321).
