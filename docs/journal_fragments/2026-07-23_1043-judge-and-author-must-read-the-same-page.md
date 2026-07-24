### 2026-07-23 — The examiner and the exam-writer have to read the same page

*Plain summary: our automatic exam-checker was marking the exam wrong for containing the very answer the person had asked for, because the checker was handed a shorter version of the request than the exam-writer got.*

When someone dispatches a build, the system asks a few clarifying questions first,
then writes an exam the finished work is graded against. Ticket #1032 fixed one
half of a split: the exam is now written from the *enriched* text — the goal plus
the person's answers. What nobody chased at the time was the other half. The
quality gate that inspects that exam for invented requirements was still reading
`spec.goal`, which is deliberately kept clean so the plan card doesn't render a
wall of Q&A back at the operator. Two surfaces, one deliberately narrower than the
other, and the narrower one was judging the wider one.

The concrete failure: the operator says "show the word Saved after each entry",
the 14B dutifully writes `assert add_item("milk") == "Saved"`, and the scanner
reports an invented return contract — because "saved" appears nowhere in the goal
or the derived criteria. I reproduced it end to end through the real
`generate_plan` before touching anything: `invented_return_contract: 1`, verdict
`seed-partial`. Then the regeneration arm fires and rewrites the assertion away.
The system was deleting the operator's requirement from the exam and calling it a
quality improvement. It never blocked anything — the class is SOFT — which is
exactly why it could sit there quietly undoing #1032 on one path.

The interesting part was the fix I did *not* take. Both the S3 design doc and the
ticket named grounding on `spec.clarifications` as the cleanest option, since the
spec already carries that field from #819 and it needs no new parameter. I went to
verify that before building it, and it does not work: `spec.clarifications` is
empty at the moment the gate runs. `generate_plan` builds the spec through
`rule_spec`, the gateway coordinator attaches the clarifications afterwards at
`dispatch_coordinator.py:546`, and the only production call into the QA gate sits
*inside* `generate_plan` at `acceptance.py:3000`. So the recommended fix would
have been a real code change, a green test suite, and a field that is `()` every
single time on the live path — the built-but-wired-into-nothing shape this project
keeps re-learning. My probe asserts `plan.spec.clarifications == ()` on a real plan
run, and that one line is what killed the plan of record.

So I threaded the text the oracle was authored from into the gate instead. The
pleasant surprise was the cost: `author_and_qa_job_oracle` already receives the
planning seed as its first argument, so it was one keyword at one call site —
cheaper than the option the design doc had rejected as "touches the QA gate's
signature". I also unioned the clarification record where a spec carries one, since
a spec reconstructed via `from_dict` keeps it.

That version closed #1043 and I was ready to hand it over. It also, as two rounds of
independent review then established, opened two holes of its own. The rest of this
entry is that, because it is the part worth keeping.

The trade-off I had accepted going in: widening the corpus makes the scanner strictly
more permissive. Its own docstring argues that direction is correct ("a false flag
here convicts a VALID oracle — worse than the miss"), so I built a lock proving a
value named by neither the spec nor the operator is still convicted — and, as it
turned out, built that lock badly enough that it missed the very thing it was for. I
also checked the ticket's suspicion about the single-task oracle: it is authored from
the planning seed but never reaches the QA gate at all, so the defect cannot manifest
there today. That is an argument for fixing `_spec_corpus` rather than a call site —
if the gate is ever extended to that path, the corpus is already right.

On the original defect the numbers held throughout: 1 finding and `seed-partial`
before, 0 findings and `seed` after, zero regeneration rounds, and the operator's
"Saved" surviving into the exam.

Then the independent review found that I had opened a hole while closing one, and
this is the part worth keeping. I had unioned *both* fields of the clarification
record into the corpus — `question` and `answer` — reasoning that both were "what
the requirements state". But the operator does not write the question. The model
does. And clarify questions routinely name a candidate value, because that is what
a useful clarifying question looks like: "Should add_item return the string Saved?"
So:

```
clarifications = ({"question": "Should add_item return the string Saved?",
                   "answer":   "no, return None"},)
oracle asserts  add_item(...) == "Saved"
scan_invented_return_contracts -> 0 findings
```

The operator said **no**, and the assertion was excused anyway — because the
model's own question had put the word into the corpus that decides whether the
model's own assertion is legitimate. The model launders its invention through its
own question and grades itself clean. I had been thinking of the corpus as a
convenience blob of relevant text. It is not. Grounding *is* authority: appearing
in that corpus is precisely what makes an assertion legitimate, and this project
has a standing rule that model-generated content never gains instruction
authority. I apply that rule to prompts and to tool output without thinking, and I
did not recognise a grounding corpus as the same kind of surface.

The first fix was to ground on `answer` only. I checked rather than assumed that
`answer` is clean: `answered_from_free_text` carries the operator's literal reply,
and `decide_defaults` carries a fixed per-axis constant out of `clarify.py` — code,
not generation.

I then checked whether `authored_from` had the same exposure and told the reviewer it
did not, because `compose_requirements_block` renders answers rather than questions.
**That was the wrong question, and my confident answer to it was worthless.** The
block does exclude the model's questions — and it opens with a fixed line of *our
own* prose:

> The person clarified these requirements — build to them:

`authored_from` was that entire rendered block. So on every dispatch carrying any
clarification, the words *person, build, clarified, requirements, them, these* became
grounded, and an oracle asserting `classify('Bob Smith') == 'person'` went from
correctly convicted to silently excused. I had measured the "before" of my own change
and never asked what else the "after" now contained. The reviewer measured it:

```
PRE-#1043  -> invented_return 1, verdict 'seed-partial'
POST-#1043 -> invented_return 0, verdict 'seed'
```

My change forgave a genuinely-bad oracle, which is precisely the thing this slice
promised it could not do. I had swept the channel for one contaminant and pronounced
it clean; the honest check is to enumerate everything in the text and name who wrote
each part.

The real fix is that the grounding input is now the operator's answers as **data** —
a tuple of answer strings — never rendered prompt text. `clarify.py` gained an
extractor that inverts its own renderer, and the two share named constants for the
header and the markers so a reword cannot quietly reclassify house prose as operator
words. Passing data instead of a blob dissolves three findings at once: no
boilerplate, no model-question channel, and an absent argument now honestly means
"the operator supplied nothing" rather than "old broken behaviour".

The reviewer also caught *why* my suite missed it, and this is the sharpest part. My
negative test hand-wrote its fixture and even hand-approximated the phrase "the person
clarified" — close enough to look right, different enough to miss. A mutant deleting
the whole question-union survived my tests untouched. So every grounding fixture now
runs through the real composer, and a round-trip test pins composer against extractor.
A fixture that merely *resembles* production is how a defect survives the very test
written to catch it.

The reviewer also flagged that the grounding test is an unanchored substring match,
so a literal `"ok"` is excused by an incidental `"broken"` or `"token"`. That one I
deliberately did not fix here. It predates this work, it changes the verdict for
every oracle on every dispatch, and it pushes toward *more* convictions — the exact
direction the scanner's own docstring calls worse than the miss. It went to #1082
with its measurement and its reasoning, rather than riding along inside a no-flag
defect fix where nobody reviewed it for that.

Worth recording plainly: the review caught two defects across two rounds, and both
were mine, in a change whose whole purpose was to make a judgement more accurate. The
gate that finally holds is not a smarter check — it is eight mutants, each of which
now fails a lock, including the two review findings reproduced verbatim as mutants.
One of those (deleting the model-question union) survived my original suite entirely.

**Proposed lessons — two, and the second is the one I would keep:**

First: when a design doc recommends a fix, the recommendation is a hypothesis about
code that may have moved since. Verify the field is *populated at the moment your
code reads it*, not merely that it exists. "The spec already carries this field" was
true and still made the fix inert; the authority for when a value is populated is
the call ordering, not the dataclass.

Second: **a grounding corpus is an authority surface, so provenance rules apply to
it — and "text" is the wrong unit to reason about.** When you widen the set of text
that decides whether something is legitimate, you must enumerate every *part* of what
you admitted and name who wrote each one. I asked "does this channel carry model
questions?", got a true answer, and shipped anyway, because the contaminant was our
own boilerplate riding in the same string. The durable form of the fix was not a
better filter but a better unit: pass the operator's answers as structured data, so
house prose has no way in at all. Prefer data over rendered text at any boundary where
presence confers authority — a filter forgets, a type cannot.

**Next:** hand the branch back for independent re-review; #1082 carries the
unanchored-match defect; the gate baseline bump belongs to the merge motion,
re-measured on merged main.
