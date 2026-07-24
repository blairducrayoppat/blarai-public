### 2026-07-23 — The grading tool that is allowed to say "I don't know"

*Plain summary: I built the committed instrument that grades the coordinator's graduation, and the hardest design decision was giving it a third answer — true, false, and "I cannot tell" — because the thing it replaces (a session reading the journal by hand) never had one.*

The ticket (#1079) came out of a finding I did not enjoy: on 2026-07-22 two careful
hand-graders read the same shadow window and came out *differently wrong*. Not one
right and one wrong — differently wrong. That is the fact that makes the ratified
criteria's phrase "deterministic ground truth" hollow no matter how conscientious
the grader is, and it is why #1068 made a committed tool a prerequisite for either
graduation layer. A tool cannot diverge from itself.

The decisions layer was the easy half and it still taught me something. I re-derive
every board move through `resolve_board_transition` against the run's
`scorecard.json` and compare it to what the coordinator journaled. My first pass
read each task's `result` field, which is the obvious field to read, and it told me
run 20260719-233631-bd had no parked task — which would have made the coordinator's
`Ready` move an error and dropped the window's precision from 7/7 to 6/7. It was my
bug. That scorecard's parked task carries `status: "parked"` with `result:
"NOTHING"`, and production's `_outcomes_from_scorecard` takes status first. I had
re-implemented a derivation instead of reusing it, and the re-implementation would
have reported a correct decision as a governance error in a document the Lead
Architect uses to decide whether to graduate the thing. So I promoted
`outcomes_from_scorecard` to a pure public function and the grader now calls the
same code the live harvest calls. The alternative I rejected was importing the
private name — cheaper, and it would have left the next person free to re-derive
again.

The words layer is where the real design sits. The tool has to establish whether a
drafted sentence is true, and then run it past the shipped `prose_guard` to see
whether the guard caught it. The trap is obvious once you see it: if my truth oracle
is the guard's lexicon wearing a different filename, the catch rate is 100% by
construction and the instrument measures nothing at all. They have to be genuinely
independent. But the guard's whole history — three revisions of #1067, each defeated
by a negation class the next reviewer found — says that deciding "is this sentence
negated?" is *hard*, and I was about to write a second implementation of exactly the
thing that had already failed three times.

What broke the deadlock is that the two components fail in opposite directions. The
guard must fail closed: it decides whether text may be published, so ambiguity has to
mean refusal. The oracle decides whether text is *true*, and nothing forces it to
answer. So it abstains. `UNDETERMINED` is a first-class verdict, excluded from every
numerator and reported by count, so a reader can see exactly how much of the window
was machine-decidable rather than being handed a confident number covering a guess.
On the real window that is 2 of 10 statements, both of them PARKED-frame prose that
asserts nothing a scorecard can settle. The hand report called those "quality notes,
neither a false success", which is the same judgment — but the tool now records it as
a measured residual instead of a grader's aside.

Then the corpus caught me. I had written a cheap consistency check — the oracle must
never adjudicate a known-false corpus case as TRUE — expecting it to pass. It failed
on `gap-08`: *"the run did not, despite the earlier stall concern raised, fail to
complete successfully."* My clause splitter broke on the commas, severed the outer
"did not" from the inner "fail to", counted one negator, and concluded the sentence
was an honest negative. It is the same parity trap that beat guard v2 and v3, and I
walked into it from the other side. The fix is to count governing negators at
*sentence* scope, where a parenthetical cannot hide one, and abstain at two or more —
clause scope still decides polarity below that, so a negator governing its own verb
in a neighbouring clause ("the pipeline never stalled so the run finished
successfully") still cannot launder the next clause's claim. The check found a second
bug the same run: two regexes used `\w+` where the shipped guard uses `\w*`, so bare
"finish successfully" and "tests pass" slipped through unmatched. A test I wrote
expecting green found two real defects; that is the second time this month a
consistency lock has been worth more than the feature it guarded.

Run against the real re-shadow window (seq 156–330), the tool reproduces every
figure of the hand report where the two should agree — 175 entries, 34 guarded
cycles, 10 distinct statements, 7 board decisions at 100%, one false suppression at
1/34 — and diverges in exactly two places, both of which are the instrument being
more honest than the hand pass. It counts 9 distinct decisions where the hand report
counted 7, because it refuses to score the stall and the tripwire: their correctness
is not re-derivable from the journal (a stall is an aging outlier relative to the
whole board at that instant, and the board at that instant is not journaled). The
hand grader verified the stall against the ticket's creation time by hand, which is
exactly the session labour this ticket exists to retire — so the honest machine
answer is "seen, not gradable", and that is now a named coverage gap rather than a
silent pass. And it reports the live false statement as *caught*, 1/1, where the hand
report said 0/1 — because the guard has since grown the `tests-passed` lexicon entry
in response to that very miss. Both numbers are right for their guard. The tool
records a guard fingerprint and names the divergence line by line, so a catch rate
can never again be quoted without the guard that produced it.

The trade-off I took deliberately: the tool re-runs today's guard rather than
replaying the journaled verdict. Replaying would faithfully reproduce history and be
useless for a decision about the future; re-running measures the guard that would
actually ship, at the cost that a window spanning a guard change is no longer one
measurement. The criteria already say a coordinator-surface change resets the window,
so I made that reset *visible* instead of pretending it did not happen.

The positive control is the part I would defend hardest. Its fixture window contains
a deliberately wrong board move and a deliberately missed false statement, so the
control proves the instrument can report a *failing* window. A grader that only ever
emits 100% is indistinguishable from one that cannot see, and this whole ticket
exists because two people who could not see each other's work both believed they
could.

**Proposed lesson (unnumbered):** when you build an instrument to replace human
judgment, give it permission to abstain. A grader forced to answer every question
launders its uncertainty into a confident number, and the number is what gets quoted
in the decision. Abstention is not weakness in a measuring instrument — it is the
difference between a measurement and an opinion. Corollary: check a new oracle
against a corpus you did not write, and expect the check to fail; mine found two
defects on its first run, one of them the identical negation-parity trap that had
already beaten three revisions of the component it was grading.

**Next:** independent review of the branch, then the decisions/words windows open
behind their own preconditions (#1067 v4 for words). #855's next precision report
should be produced BY this tool, not by hand — that is the ticket's observable
predicate, and it is not satisfied until a report is actually generated that way.
