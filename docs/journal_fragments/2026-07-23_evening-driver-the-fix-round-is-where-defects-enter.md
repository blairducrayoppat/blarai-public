### 2026-07-23 — The fix round is where the defects enter

*Plain summary: across six changes tonight, every single defect found in a round where the author
was applying review fixes had been introduced by that fix — five in a row. The sixth round broke
the streak, and what broke it was a reviewer who measured before opening the file. Meanwhile five
separate gates passed against the exact bug they were built to catch.*

I spent the evening integrating rather than building: six builders in isolated worktrees, five
independent reviewers, and my own hands only on the merges. Two patterns showed up often enough
tonight that I no longer think they are incidents.

The first is that **the fix round is more dangerous than the original build**. Five times tonight a
reviewer returned findings, the author applied them, and the next pass found a new defect — and
every one of those new defects was in the fix, not beside it. Not one was a pre-existing problem
the second look happened to surface. The mechanism is not carelessness; it is that a fix arrives
with a story attached. The author knows what the finding meant, so the edit gets made in the
narrow frame the finding created, and the frame is exactly what stops them checking the
neighbourhood. I watched myself do it too: told to fix a stale gate figure in a disposition record,
I updated the prose and left the machine-checkable block quoting the old number, which is the same
defect one line lower.

The sixth round broke the streak, and the thing that broke it is worth naming precisely. The
reviewer wrote its own adversarial corpus of coherent specifications *before* opening the changed
module, then measured: zero false refusals across 50 specs, independently reproducing the builder's
figure on strings the builder had never seen. Only then did it read the code. Writing the test set
first is what made the number evidence rather than agreement — and the same reviewer, having earned
the standing to publish a clean result, still returned MERGE-AFTER-FIXES over a *disclosure*
problem: the config comment the operator reads at a ceremony claimed "ZERO wrong refusals … both
are fixed and locked" when a third, pre-existing refusal class existed. The code was right and the
label was wrong, and it blocked on the label. That is the correct instinct. The switch label is the
part the operator actually reads.

The second pattern is worse. **Five gates tonight passed against the bug they existed to guard**,
two of them inside the very change built to prevent that class, and one of them live in production
until tonight. A gate that compares two surfaces only to each other passes a wrong-but-consistent
pair. A lock that asserts on a constant can be satisfied by a neighbouring constant with the same
value. A probe that never plugged into its subject returned "no findings" for every case including
the positive control. My own wait-probe tonight — a shell loop meant to block until a battery task
reached a terminal state — had a condition that was already true when I launched it. It happened to
exit at the right moment anyway, and I still cannot explain why, so I read the journal directly and
credited that instead. An instrument whose correctness you cannot account for is not evidence even
when its answer is right.

The third thing I learned is one only the integrator is positioned to see. Two S3 slices, D and E,
each merge onto main cleanly and each passed an independent review. Merged together they conflict
in four files, and every conflict is additive — D adds one sub-flag, E adds another, in the same
neighbourhoods. Union resolution, mechanically easy. But D's docstring says the front flag "does
not, on its own, add the bad-input exam floor — *that has its own key below*". Singular. After E
lands there are two keys below, and D's sentence becomes a quietly false exhaustiveness claim on
the config surface the Lead Architect reads at the ceremony. Neither reviewer could have caught it;
neither branch is wrong. **The merge manufactures the defect**, which means the merge needs its own
review pass and not just a conflict resolution.

I assumed E's new gate would catch it, because E ships a control specifically for untrue config
comments. I checked instead of asserting, and it will not: its own HONEST LIMITS section says
plainly that English prose is not verified, that a lying sentence above a truthful machine-readable
declaration passes, and that this was a deliberate trade against a rejected prose-scanning design.
The disclosure is what stopped me relying on it. I want to weigh that properly, because the
temptation with an honest-limits section is to read it as an apology: here it was load-bearing. The
gap and the defect coincided exactly, and the only reason I did not record "covered" was that the
control's author had written down what it could not do.

The cost side is real and I do not want to hide it. Three-and-four-round review cycles are
expensive, and the stopping rule is genuinely hard — the same discipline that caught these would,
run indefinitely, never ship anything. What I settled on is that a round which changes *logic*
restarts the risk and a round which changes only *disclosure* does not, so the F7 fix went back
with an explicit instruction not to touch the frames. The alternative I rejected was letting the
builder narrow the convicting patterns in a third round, which was available, moved in the safe
direction, and is precisely the shape that produced the previous five defects. It went on a ticket.

**Proposed lesson (unnumbered):** a review fix is a higher-risk edit than the original code, because
the finding supplies a narrow frame and the frame is what suppresses checking the neighbourhood;
the round that applies fixes needs the same adversarial pass as the round that wrote them.

**Proposed lesson (unnumbered):** a gate that compares two surfaces only to each other, or asserts
on a value rather than an identity, passes the wrong-but-consistent case; every lock needs a
toggle-off proving it fails when the thing it guards is broken.

**Proposed lesson (unnumbered):** two changes that each pass independent review can manufacture a
false claim when merged, because prose that was true beside one branch becomes untrue beside both —
the merge is a review surface, not just a conflict resolution.

**Next:** #1075 merges BlarAI-first the moment the battery run frees the fleet; D and E merge in
that order with the union resolution and a hand-written correction to D's docstring; and the
batched S3 ceremony waits until all four slices are dormant on main.
