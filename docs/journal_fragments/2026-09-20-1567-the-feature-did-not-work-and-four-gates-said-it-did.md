### 2026-09-20 — The feature did not work, and four gates said it did

*Plain summary: I built a tool that lets BlarAI erase saved documents, with a
rehearsal step so the Lead Architect sees what would go before agreeing. I
tested it thoroughly. Then an independent reviewer ran it the way he actually
would have, and it crashed before the approval box ever appeared. It had never
worked once. Three separate test suites were green.*

The defect is one line and the shape of it is worth more than the fix.

`_approved_identity` — the fingerprint of the action being put in front of him —
was assigned inside `if _pa_verdict is not None:`, the branch that runs when the
Policy Agent has something to say. The rehearsal branch below read it
unconditionally. **The Policy Agent returns nothing for this tool**: no rule
objects to erasing documents, so there is no verdict, so the name was never
bound, so every path where the rehearsal *succeeded* raised `UnboundLocalError`
and killed the connection handler.

Not a security hole. Nothing was erased — it could not get that far. What it
means is that at his go-live ceremony, the one he attends in person, the dialog
would not have appeared, the turn would have died with no answer, and I would
have been standing there saying it worked on my machine.

**Why four gates missed it, which is the part I want to remember.** The suite I
wrote for the tool drives a shim carrying the two attributes the methods touch —
a legitimate pattern, used deliberately, and it exercises the callee. The defect
was in the caller. The simulate-first suite asserts the *source text* of the
branch: that it calls the rehearsal, that it asks the operator, that both
refusal paths break. Every one of those assertions is true of code that cannot
run. And the one suite that does drive the real loop only drives the arm where
the rehearsal *fails* — which returns before touching the unbound name.

Three suites, none of them wrong, and the tool was inert. There was no test
anywhere that drove `curate_knowledge` through the door he comes in.

There is now, and it is mutation-proved: revert the fix and five tests go red
carrying the exact `UnboundLocalError`.

**The second fail-open was a shape check wearing a validity check's docstring.**
The date filter was `\d{4}-\d{2}-\d{2}`, and its docstring said anything else was
*"refused before the store is consulted rather than passed to SQL and hoped
about"*. `9999-99-99` matches that pattern. It is not a date, it sorts above
every real timestamp, and `created_before='9999-99-99'` selected **the entire
approved bank** — measured, five of five. On the only irreversible tool in the
set, through the one selector no test touched. It parses with
`fromisoformat` now.

**And the guarantee I rebuilt the whole design to obtain was false.** Earlier
the same day I threw away a character-allowlist because `Q3 Financials Acme
Corp.pdf` passes any character class, and replaced it with a summary *rendered*
from typed fields, writing that there was "no parameter through which free text
can reach" the string that crosses to the operating system's consent dialog. The
reviewer got a document title into it five ways — an `int` subclass with its own
`__str__` as the count, the same as a qualifier value, a `date` subclass
overriding `isoformat`, `object.__setattr__` straight past `frozen=True`, and a
subclass of the result type that `isinstance` waved through.

The thing that stings: **I had reasoned about exactly this hazard.** There is a
comment in that file explaining that `bool` is rejected because it is an `int`
subclass and would render as "True". I saw the class of problem, handled the one
instance of it I had thought of, and wrote the general claim anyway.

**Three controls had no lock at all**, and the reviewer proved it the only way
that counts: mutate the control, run the suite, see what turns red. Dropping the
comparison that refuses a swapped selector — 105 passed. Flipping the fail-closed
branch of the rehearsal predicate to fail-open — 105 passed. Deleting the
argument validation from the tool body entirely — 105 passed. The first of those
is the control whose refusal message speaks to him in plain language; the system
was prepared to say "BlarAI could not match this to the rehearsal you approved"
with nothing behind the sentence.

**A regression I introduced fixing all this, caught by an existing test.** Deriving
the identity unconditionally added a third call per loop iteration, and an older
#1541 test mocks that function with a fixed list of return values to simulate
drift. It raised `StopIteration`. The right fix was not to pad the list — it was
to notice that the Policy-Agent branch was now re-deriving something already in
hand, and delete the redundant call. The test was right and my first instinct
was to adjust it.

**Proposed lesson:** *A shim tests the callee; the bug lives in the caller.* Every
technique I used was sound for what it covered. The gap was that nothing entered
through the door the operator uses. For any capability that ships behind a
ceremony, there must be one test that starts where he starts and ends where he
ends, however expensive it is to write — the reviewer built one in about seventy
lines, which is what my confidence was worth.

**Proposed lesson:** *Asserting source text certifies that code was written, not
that it runs.* Three assertions about the branch's contents were all true while
the branch could not execute. Structural checks are good at "is the control
still there" and silent on "does the control work", and I used them for the
second question.

**Proposed lesson:** *When you name a hazard class in a comment, handle the class.*
The `bool` note proves I understood that an `int` subclass can render arbitrary
text. I fixed `bool` and shipped a claim about every parameter. A comment
explaining why one case is dangerous is evidence you owe the general fix, not
evidence you have paid it.

**Next:** the ceremony — three flags, and none of them flips without him.
