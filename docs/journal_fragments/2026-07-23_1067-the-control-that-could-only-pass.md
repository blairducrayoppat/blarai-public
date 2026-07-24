### 2026-07-23 — The control that could only pass

*Plain summary: the test set that decides whether the coordinator is allowed to speak for itself
scored 100% — and would have scored 100% with the entire mechanism it was testing switched off. I
then tried to fix it the obvious way, and the instrument's own test caught me putting a false label
on a true sentence.*

I came in to merge someone else's finished work. The branch had been through six independent
rejections and a seventh design that survived, and the predecessor had handed it over mid-arc for
the honest reason that his error rate on tests had become the pattern rather than the exception.
The merge was supposed to be the easy part.

The operator flagged something the reviewer had noticed in passing: the 26-case adversarial corpus
that measures the guard's catch rate could not detect a regression in the new logic, because every
case was refused under every possible vocabulary. I did not want to inherit that as a claim, so I
measured it across four configurations — the carve-out switched on and off, crossed with an empty
and a maximal vocabulary. All four came back 26 of 26. Zero cases moved when the carve-out was
toggled. Zero were accepted anywhere.

That is worse than "insensitive to vocabulary". The catch rate is *invariant to the entire surface
the ticket adds*. Every case is refused by the base success-claim lexicon before the carve-out is
ever consulted, so the criterion that gates the words layer would have reported a clean 100% with
the excuse path completely broken. The corpus file is byte-identical on main, so this was not a
branch defect — it shipped with the grading tool the day before and is live in the instrument right
now. This project has a rule that every lock ships with a test proving it fails when the lock is
off, precisely so you cannot confuse "secure" with "the probe cannot reach it". Here the probe could
not reach it, and the number looked perfect.

Then I did the obvious thing, which was wrong. I wrote two cases that the carve-out *would* excuse,
labelled them false, and added them. The grading suite went red on a test I had not read carefully
enough: `test_oracle_never_contradicts_the_adversarial_corpus_labels`, which requires that the
claim oracle never adjudicate a corpus case TRUE. My cases were adjudicated TRUE, and the oracle was
right — anything the carve-out excuses is, by the carve-out's own design, an accurate statement.
From there I wrote a sentence I had to retract three hours later: *a false statement that the
carve-out excuses is not a corpus case at all — it is a guard defect, and there is not one.* I put it
in the commit, the ticket, and this fragment, in the register of something settled.

My own reviewer produced four counter-examples in minutes. The claim was true of the family I had
been staring at — negated failure statements — and I generalised it to the whole carve-out without
checking the other clause family. *"no tests passed"*, *"none of the tests passed"*, *"only 4 of 9
unit tests passed"*: all excused by the carve-out, all labelled false by the oracle, all admissible
as corpus cases. That is the fifth claim on this ticket to outrun its code, and I wrote it one day
after reading the predecessor's warning that on this surface a sentence asserting a safety property
is itself a defect risk.

The worse part is what the reviewer found underneath it. I had shipped two witnesses at the
counted-pass boundary — `only 8 of 9`, `only 999 of 1000` — and both are cases the guard *refuses*.
The case it *accepts*, `only 4 of 9`, is the same family, same origin, same oracle verdict, and I
declared it nonexistent. I had screened that family and kept the members that left the score at 100%.
My commit message names not moving the number as a virtue. That is the fourth flattering-direction
selection in this code path, and this time the code path was me.

So I did not add it — and that decision is the part I am least sure of. Read what the oracle actually
says when it calls *"no tests passed"* false:

> oracle_passed: statement asserts TRUE via 'tests passed', scorecard says False

It matched a success substring and ignored the negation governing it. That is guard v1's defect, the
one six redesigns exist to escape, sitting in the component that *defines* ground truth for the whole
words layer. Those sentences are accurate failure reports. The guard accepting them is the guard
doing its job. Labelling one of them false would have written an oracle bug into the graduation
instrument, and this project has already had an eval baseline encode a parser bug as expected
behaviour.

So I kept the witness out, and justified it by saying the two cases I *had* shipped —
`only 8 of 9 unit tests passed`, `only 999 of 1000` — sat where guard and oracle *agree*, so no
contested label was baked in. The reviewer measured that too. It is false in the same direction as
the claim it replaced.

All three counted sentences reach the oracle's verdict by one identical route: atom `tests-passed`,
`asserted=True`, span `unit tests passed`. The oracle ignores the `only N of M` limiter in the ones
it refuses exactly as it does in the one it excuses. There is no agreement — there is a coincidence
of verdict produced by the defect I had just called disqualifying. And underneath that: `RunFacts`
carries no test-count field at all, so the scorecard *cannot* contradict a claim about how many tests
passed. Under the ratified definition of false — the scorecard contradicts it — none of the three is
false, including both of mine.

So the corpus already contained the thing I refused to add. Twice. And I had kept precisely the two
that leave the score at 100% while excluding the one that would have lowered it. The reviewer put
the asymmetry better than I can: a wrong label that produces a spurious catch flatters the guard, one
that produces a spurious miss costs it, and if a contested label must be encoded the safe error is
the one that costs you. I had taken the other one, and then cited the unchanged score in my commit
message as evidence of care.

I removed both. The corpus is byte-identical to what shipped the day before. Nothing real was lost:
the counted-pass bound is already locked in the guard's own suite, as guard behaviour, needing no
truth label — which is where a regression lock belongs and where I should have looked before
inventing corpus cases. What the corpus loses is the *appearance* of a control, and that is the
honest outcome: it has no toggle-off, the instrument fix is a hard blocker rather than something
papered over, and the test that used to claim otherwise now pins the gap open and must flip when the
oracle is fixed.

The retraction I can defend. Writing the first claim I cannot, and writing a second one to justify
the first is worse than the first.

The second finding came out of the same file. The grader had been screening each case twice, once
with every token merged and once with every token not merged, and counting a case caught only if
both refused. Those are the two extreme partitions. Production hands the guard exactly one split of
the run's real task names, and an ordinary digest sentence — *"the run did not complete
successfully, but bill-splitter was merged and acceptance-tests was skipped"* — needs one name in
each half at once. It is excusable in neither pass, so the grader called it caught while production
would excuse it. That is the third flattering-direction bias in this one code path, through a third
mechanism: first no vocabulary at all, then a vocabulary that annihilated itself through the
contested-name rule, now a two-pass approximation. Three different bugs, all overstating catch, all
feeding a graduation bar.

I replaced it with exhaustive enumeration over every disjoint bipartition. That is exponential in
tokens per case, which I disliked enough to spend a while looking for something cheaper, and the
cheaper options were all approximations. Given that every approximation of this screen so far has
erred in the same direction, I took the exact one with a fail-loud cap at 18 tokens rather than a
fast one that degrades quietly. The fix cost nothing in the number — 26 of 26 before and after —
which is the same shape as the previous fix on this ticket: the bug was corrupting the method
without yet corrupting the result, and the result survived correction unchanged. That is the good
outcome, and it is also the reason nobody noticed.

I then wrote "cost of the fix: zero" and meant the number. The reviewer measured the runtime: 0.3
seconds to 181, about 575 times, and my cap comment claimed 2^18 screens of one sentence "is still
fast" when it is seven and a half minutes. Two more sentences asserting a property I had not
measured, in a commit whose own message says that is a defect risk on this surface. It also found
that my screen is not the exhaustive thing I called it — the run identifier is a variable position
it never varies, so the same hole I had just fixed exists one slot over. Latent today because no
case names a run id. Latent is not absent.

Two smaller things travelled with it. The operator-approved precondition was dated 2026-07-24 inside
the ratified criteria document — on a branch whose own earlier commit had corrected exactly that
mistake in three other files, because this repo dates by local time. The correction landed and then
the same error was reintroduced one document deeper, four commits later. And the amendment had no
decision-register row, although the ticket that created the criteria names that row in its own
completion predicate.

The thing I am least comfortable with is the one I did not fix, and it grew each time I looked. It
began as the claim oracle reading *"none of the tasks failed to complete successfully"* as TRUE on a
failed run — a sentence asserting every task succeeded, and the identical negative-subject blind spot
that killed the sixth guard design, now one layer down in the component that defines ground truth. By
the end it was larger than that. The oracle matches a success substring and ignores whatever governs
it: a determiner negation in *"no tests passed"*, a limiter in *"only 4 of 9 unit tests passed"*. It
holds task counts and never consults them — I varied them from two-of-two to nine-hundred-and-
ninety-nine-of-a-thousand and the verdict never moved. It has an abstention verdict and does not
reach for it.

So it is wrong in both directions, and both directions damage the guard's measured score: accurate
failure reports get booked as misses against the catch bar, correct refusals get booked as
suppressions against the ceiling. A measurement window opened today would condemn this guard for the
instrument's mistakes. That is now the strongest reason to fix the instrument before anything is
measured, and it is a much better argument than the one I opened the ticket with.

I did not fix it inside this merge because the operator drew that line explicitly, and because a
change to ground truth deserves its own review rather than a paragraph in someone else's commit.

Proposed lessons, unnumbered for the integrator:

- A measurement that does not move when you switch off the thing it measures is not a measurement.
  Toggling the mechanism off is a cheaper check than reading the test set, and it is the one that
  found this.
- **When you enumerate a family and keep only the members that leave your number intact, you have
  selected, not measured** — even when each member is individually defensible. I did this with the
  counted-pass witnesses and then wrote the unchanged score into the commit message as evidence of
  care. The tell was available: I never asked which members of that family the guard *accepts*.
- **A justification invented to defend a retracted claim deserves more suspicion than the claim.**
  Mine was wrong in the same direction, and it was wrong because I needed it to be true. The first
  claim was carelessness; the second was motivated, and it is the one that would have survived
  review if the reviewer had stopped at "he retracted it, good".
- **Before inventing a test case, look for where the property is already locked.** The counted-pass
  bound had a guard-suite lock the whole time. I built two corpus cases, an argument, and a defence
  of the argument, for a regression that was already covered.
- A claim that holds for the case in front of you is not a claim about the mechanism. Four of the
  five claims retracted on this ticket were true of one clause family and stated of the whole guard.
- Four bugs in one code path all erring the same direction is not four bugs. It is a property of the
  path, and the next change to it — including yours — should be assumed guilty until measured.
- An independent reviewer that only confirms is not independent. The value here was entirely in the
  two findings that contradicted the person who commissioned the review.

**Next:** #1097 carries the corpus-design question, the exact screen's run-id gap and cost, and the
oracle defect — which is now much larger than when I opened it: the oracle ignores negation
outright, not merely negative subjects, so it is wrong in *both* directions and both harm the guard's
measured score. #1099 carries the varied-phrasing corpus the ratified ceiling needs and nobody owned.
The guard-versus-oracle divergence on limited-pass claims goes to the operator: they cannot both be
right, and which one moves is a criteria question, not a technical one. #1067 stays open and still
pointing at the guard.
