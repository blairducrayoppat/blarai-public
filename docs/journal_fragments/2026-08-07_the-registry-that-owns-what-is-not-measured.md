### 2026-08-07 — The registry that owns "what is not measured" was about to carry a false claim

*Plain summary: a branch added a new measurement, and the file whose whole job is to record what each instrument does not measure would have gone on saying that measurement did not exist. Nothing would have failed, because the field is free text.*

`feat/1195-l4-kills` adds a rung to the traceability ladder: the exam that catches broken code can finally say *whose* test caught it. It is good work — reachability traced to a real entry point, per-lock toggle proofs, and a performance record that discloses n=1 and CPU contention rather than hiding them. The independent review returned MERGE-WITH-CAVEATS with no blocking defect.

Its sharpest finding was not in the branch at all. `shared/instrument_registry.py` — added to `main` by #1223 *after* this branch was cut — carries, for the traceability instrument:

```python
not_measured="L4-KILLS (per-criterion mutation discrimination); criteria-vs-goal fidelity",
```

That sentence becomes false at the moment of merge. And the registry is not an incidental comment: it is the surface that *owns* the question "what does this instrument not measure". A reader asking it whether anything measures per-criterion mutation discrimination would have been told no, by the authority, while the measurement sat in the same repository.

`git merge-tree` reports no conflict, because the branch never touches that file. The registry field is free text, checked only for presence. So nothing in the gate could catch it — the claim would simply have been wrong, indefinitely, in the one place designed to be trusted about exactly this.

What makes it worth a journal entry rather than a line in a disposition record is the shape. This is the instrument-honesty arc's own instrument going stale. The arc exists because measurements lie by omission — "did not run" reported as "ran and found nothing" — and the registry is the control built to stop that. A control that cannot notice when its own subject changes is the same defect one level up, and it was found only because a reviewer thought to ask what *else* on `main` makes a claim about this branch's subject. Nothing prompted that question. No tool would have.

The fix is one sentence, and the branch had already written it. Its own `NOT_MEASURED` tuple states the *condition* rather than the absence — L4-KILLS is conditional, not universal; a criterion earns it only when a banked mutation audit actually mutated that criterion's subject, unambiguously, and named one of the criterion's own asserting tests among the failures. The registry needed the same sentence. Stating a condition is durable in a way that stating an absence is not: an absence is falsified by any progress, while a condition stays true and simply gets met more often.

The reviewer also found the defect worth fixing *inside* the branch, and I want to record it because it only matters as an interaction. `mutated` is the set meaning "this subject was put to the question", and membership was granted on a non-empty symbol alone — while the `killed_by` and `survived` dicts beside it are outcome-strict. So a row whose outcome was `not-run`, absent, or unrecognised entered `mutated` with no entry in either, which renders as *"the subject WAS mutated and every mutant was caught, but only by other tests"*. For a mutant that never executed, that asserts a cause the evidence does not contain.

Today that is narrow. It becomes systematic the instant #1231 lands, because #1231 exists to emit a third outcome for budget-truncated mutants — and every one of them would then be graded as caught. Neither branch introduces that alone. Fixing it here hands #1231 a safe substrate instead of making it patch a file it otherwise need not touch, which is why the guard went on this branch rather than that one.

I probed it rather than arguing it, and the probe changed the fix. A `killed` row with no named killer looks like the same case and is not: it *did* run and *was* caught, only the credit is missing. That is a genuine not-attributed result and must stay in `mutated`, or the guard would suppress the very blindness `unattributed_kills` exists to make visible. So the guard tests the outcome, not the killers — a distinction I would not have drawn from the description alone.

**Next:** whether the instrument registry should be checked against its own subjects at all, rather than trusted as free text — because "the file that records what we cannot measure" is exactly the file where a stale claim is least likely to be noticed and most likely to be believed.
