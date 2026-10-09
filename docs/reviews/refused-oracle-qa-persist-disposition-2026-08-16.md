# Disposition — #1418, the refused oracle that banked nothing, 2026-08-16

**Why this pass happened.** Roadmap rank 1, promoted the moment #1416 shipped. #1410 made
website exams reachable by plan-time QA with a bounded repair loop; #1418 is that fix's
verdict being unobservable in exactly the case it was built for. Running the loop again
without this produces nothing anyone can read.

**The ticket understated its own defect, and that was found by reading the surface that owns
it rather than the sentence describing it** — the same move that produced three findings on
#1416 earlier the same day.

```disposition
# finding | status | evidence-or-predicate
`_oracle_qa_seed_gate` is the ONLY writer of <run>/oracle-qa.json and sits below THREE returns in real_seed_job_oracle, not the one this ticket names -- an ungenerated oracle (:1574), an unpinned path (:1576), and a pinned path with no designed guard (:1587) | FIXED | 2cb33d8a - `_refused_before_qa` + `_persist_oracle_qa`, extracted so every pre-gate refusal banks the plan-time evidence. The two extra paths are CONTAINMENT refusals -- what a tampered plan or an undesigned extension look like from outside -- which is precisely when a human wants a record. Mutation-proved: restoring the pre-fix return fails two locks
a refusal record must not be mistakable for a QA verdict on an oracle nobody examined | FIXED | 2cb33d8a - the record carries `seed_refused_before_qa` with the reason, and `f2p_baseline`/`collectability` stamped `not-run`. Asserted in test_every_pre_gate_refusal_BANKS_its_evidence. Writing a bare evidence blob would have been the absence-as-a-confident-value defect one layer over -- the exact class this arc exists to close
the plan-time evidence must survive the refusal rather than being replaced by it | FIXED | 2cb33d8a - `adequacy_floor: 2` asserted present on the banked record alongside the refusal reason
the operator-facing seed-failure message appended "it still grades the final tree" to EVERY failure -- true for a mechanical failure, FALSE when no oracle was authored, because real_run_job_oracle returns not-run at its first statement and never touches the tree | FIXED | 2cb33d8a - swap_driver.py now branches on whether an oracle exists and says the non-grade is an honest not-run rather than a failure. Locked as a STRING in test_the_seed_failure_MESSAGE_does_not_promise_a_grade_that_cannot_happen, deliberately: the string IS the defect, it cost real investigation time by sending someone hunting an ecosystem-detection bug that did not exist, and pinning the code path without the sentence would miss what actually misled a human
two docstrings in swap_ops.py asserted the evidence is "always" written while three returns sat above the only writer | FIXED | 2cb33d8a - both corrected in the same change, each naming what it used to claim. THIRD instance of this shape today: #1416's scope.reason claimed "every python test file" while reading node, and the gaming limit named green_audit as an owner it is not
a persistence miss must never block a seed | REJECTED | not a defect and deliberately preserved. `_persist_oracle_qa` swallows OSError exactly as the code it was extracted from did; the seed posture is fail-soft everywhere and this change does not tighten it
an empty evidence blob writes no file | REJECTED | deliberate, and locked in test_a_refusal_record_is_not_written_when_there_is_nothing_to_say. There is a difference between "the run had nothing to say" and "the run refused and said why"; a file that always appears carries no information. Mutation-proved -- making the writer unconditional fails that lock
malformed plan-time JSON must not lose the refusal record | FIXED | 2cb33d8a - `_parse_qa_evidence` returns {} on anything unparseable and the refusal still banks. Locked in test_malformed_plan_time_evidence_never_blocks_a_refusal_record
hoisting the QA gate above the containment checks would close this more simply | REJECTED | and it would be wrong. The f2p baseline EXECUTES the oracle, so it must not run before `rel_path` is confirmed pinned -- the containment order is a security property, not an ordering convenience. Recorded because it is the obvious first idea and the ticket's own suggested shape
```

## What this pass did NOT do

**It did not run the coder.** Every check is over planted fixtures and the existing
containment tests. That is the right loop for this change — the refusal is reproducible from
a plan whose oracle is empty, no GPU required — but it means **the fix has never been
exercised by a live dispatch.** The observable in the ticket's own DONE section is a run whose
exam was refused carrying an `oracle-qa.json`; `state/fleet-runs/20260815-161349-bd/` still
has none, because that run predates this.

It also does not make #1410's repair loop *work* — it makes the loop's verdict readable. Those
are different claims and only the second is made here.

## The pattern, third instance today

**A docstring that describes a path the function returns before reaching.** `scope.reason`
claiming "every python test file" while reading node; the gaming limit naming `green_audit`
as an owner it is not; and *"the merged evidence is always written"* sitting above three
returns that skip the writer. Each was true when written and each outlived the code beneath
it. The instrument-honesty arc keeps finding the same thing at successively smaller scales —
the sentence is the artifact that rots, because nothing executes it.
