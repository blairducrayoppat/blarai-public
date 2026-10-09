### 2026-09-18 — A test that reads source code cannot tell a call from a comment

*Plain summary: BlarAI's two security checkpoints made decisions and kept no permanent record of
them — a refusal, the thing you most want evidence of, left nothing but a log line. I built the
record. Then I wrote tests to prove the record was actually being written, and those tests read the
program's text rather than running it. Someone else replaced the real code with a piece of text that
merely looked right, and every test still passed.*

The ticket was the last of the trust-spine gaps: the tool-dispatch door and the egress door
adjudicate every risky action, and neither wrote anything a later reader could verify. The signed,
hash-chained audit log already existed and was live for knowledge ingestion. It just was not
connected to either door.

The hard part was supposed to be the migration. Adding fields to a record changes the bytes that get
hashed, and every record already on disk was hashed without them — so a naive addition breaks the
whole chain, and a broken chain means the Policy Agent refuses to start. I measured it rather than
reasoning about it: unconditional addition breaks all 33 records in a test chain, versioned
canonicalisation breaks none. A record with no receipt hashes to exactly the bytes it always did. The
reviewer later verified this the way I should have thought to: it built a chain using the *parent
commit's code*, then verified it with mine. Byte-identical, not merely equivalent.

Two things I got wrong during the build and caught by running a control instead of believing what I
had just written. The first: the function that normalises a receipt for hashing filtered it down to
the thirteen known fields, and I wrote in its docstring that this made a forged extra key detectable.
It does the exact opposite — filtering makes the extra key invisible to the hash, so a receipt
carrying `"smuggled": "payload"` verified clean. The second: I made an absent receipt sink deny, and
broke 102 tests, which is what it would look like in production if egress and every tool call stopped
whenever the durable chain was not up.

**And then the review, which found four more, two of them the same defect I had shipped that morning
in #1548 — in the file that cites #1548 as its reason for care.**

I had written two tests to prove the dispatch door was wired. Both were `str.find` scans over
`entrypoint.py`. The reviewer replaced the real receipt call with a **string literal** containing the
bytes I was searching for, and with an inert `dict(...)` carrying the same keyword arguments. The
full suite stayed at 2937 passed while every allowed tool dispatch went unrecorded. The ticket's own
first named regression lock — *a real tool dispatch yields a record whose identity equals the CAR
hash* — I had not delivered at all: every assertion compared against a fixture constant, never
against a hash recomputed from a real action.

The second finding is the same disease one layer out. `register_receipt_sink` — the seam that makes
the egress door's receipts durable — had **zero production callers**. The door ran on an in-memory
chain forever, and three separate docstrings said that registering a sink was what made it durable,
including one that named a test file as the lock. There was no such test.

The pattern is legible now in a way it was not this morning. **Every lock I wrote that drove real
code survived review. Every lock that read source text was defeated in a single edit.** And I reached
for the source scan precisely where driving the real thing was inconvenient — the tool loop needs a
transport, a framer and a mocked model to run. The inconvenience is the signal, not the excuse: the
place the harness is awkward is the place nothing is really being tested.

The replacements drive the real `_handle_connection` loop and read the real chain. The identity is
recomputed independently and compared. I re-ran the reviewer's own two mutations against them; both
now fail.

The other finding worth recording is an ordering mistake with a nasty shape. My ALLOW receipt sat
above the simulate-first gate — a gate that can still refuse — while its own comment claimed it was
below every gate. So a refused action left a signed record saying it was allowed. That is worse than
no record: it is the chain confidently attesting to something that never happened. It now sits below
every gate, and the six refusal paths that recorded nothing at all now record through one helper,
with a test that counts the `break` statements so the next one added fails loudly. The first version
of that counter split on the bare substring `break` and reported the phrase *"breaking loop"* as an
unrecorded refusal path, which is its own small lesson about scanning text.

One thing I did not do. The ticket points at `DeterministicPolicyChecker.check` for the dispatch
door's verdict, and at the egress door it specifies the identity as the Canonical Action
Representation hash. `guarded_fetch` is a shared module with no access to the session a CAR is built
from, so there is nothing there to hash. Rather than invent a CAR, the egress identity is a fetch
identity over `(purpose, url)` and both docstrings now say plainly that the two share a shape, are
not interchangeable, and that `source_door` is what tells a reader which one they are holding. A
deviation stated is a deviation someone can act on; a deviation hidden behind a matching format is a
trap for whoever tries to correlate the two doors.

**Next:** the sprint's ten tickets are closed. The residual worth watching is that both doors fall
back to an in-memory chain when the durable one is unavailable — verdicts still hashed, chained and
signed, but lost on restart — and the thing that makes that safe is a warning and two tests, not a
structural guarantee.

---

**Proposed lesson (unnumbered per the fragment convention):** *A test that reads source text cannot
distinguish a call from a comment; if driving the real path is inconvenient, that is where the lock
is needed most.* Six locks shipped in this change. The three that executed real code all survived an
adversarial review that was explicitly hunting for this failure. The two that scanned source were
defeated in one edit each, and the one that counted call sites was defeated by the word "break"
inside a log message. Source scanning has exactly one honest use — counting call sites so a
*missing* one is caught — and it must say so in its own docstring, because the next reader will
otherwise take its green as evidence that something ran.
