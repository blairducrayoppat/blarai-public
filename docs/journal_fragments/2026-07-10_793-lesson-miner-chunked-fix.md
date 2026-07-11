### 2026-07-10 — The gate was green and the real pass still 400'd

*Plain summary: the #793 lesson-miner's first real 14B pass failed with an HTTP 400
because the whole ~113-run evidence corpus (~223k tokens) went to the model in one
message and overflowed its context; fixed with chunked mining — batch to fit, one call
per batch, and MERGE candidates across batches before the ruler so recurrence counts
across the whole corpus (agentic-setup `feat/793-lesson-miner-chunked`, `db2b017`).*

The golden gate passed 11/11. Seventeen unit tests passed. The dry pass ingested 113
real runs cleanly. And the first real pass — the coordinator pointing the miner at the
live 14B — returned `HTTP Error 400: Bad Request`. This is the mock-passes-but-prod-
crashes class, and it earned its entry: everything I could test offline was green,
because the thing that broke was the one thing the fake model layer by definition could
not exercise — the real context ceiling. My `RecordedModelClient` returns candidates for
any bundle, of any size. The real OVMS server does not.

The lead diagnosed it before handing it back, and the diagnosis is worth keeping because
it is the failure mode of every consolidator that reads "the whole history": I built the
evidence bundle as *one user message carrying all 113 runs*. Measured after the fact,
that is ~223,000 tokens — an order of magnitude past any 14B context. The miner was
architecturally a single-shot summarizer of an unbounded, growing corpus, and that shape
does not survive contact with a fixed context window. It only ever ran clean in tests
because the corpus was tiny there.

The fix is chunked mining, and the interesting half is not the chunking — it is what
chunking does to the ruler. Split the corpus into batches that fit and call the model
per batch, and a failure shape that recurs four times across the corpus is now proposed
*twice in batch 1 and twice in batch 3*, each proposal citing only the two runs its batch
saw. If the deterministic ruler counts recurrence per proposal, both see recurrence 2,
both fall under the ≥3 gate, and a genuinely four-times-recurring lesson is **silently
killed by the very act of batching**. That is the trap, and it is exactly the silent-cap
class this miner is built to refuse. So the correctness heart of the fix is the merge:
candidates from all batches are grouped by failure shape and their evidence *unioned*
before the ruler runs even once — recurrence and diversity are computed across the whole
corpus, never per batch. I unit-tested it both ways: the merged shape survives at
recurrence 4, and each half alone is dropped at recurrence — so the test would fail loudly
the day someone "optimizes" the merge away.

Three smaller judgments came with it. The batch budget is derived from a *probe* of the
served context when the model is up, and a deliberately *low* default (16k, not the
model's true 40k+) when it is not — because guessing the ceiling too high is precisely
what caused the 400, so the safe direction for the fallback is to guess low and make more,
smaller batches. A single run whose evidence somehow exceeds a whole batch is truncated to
a prefix *with a logged note*, never dropped — and because the kept text is a prefix of the
real source, any quote the model draws from it still byte-matches, so the anti-drift
guarantee is untouched. And I made the OVMS client read the HTTP error *body* into its
exception: urllib swallows it in `str(exc)`, and the lead had to reproduce the call by hand
to see that the body said "context length" — a swallowed error body cost a debugging
round-trip, so now the real cause rides out in the message.

The real pass is still the coordinator's, in the next 14B window (OVMS is swapped away
today; the miner is dormant, so nothing waits on it). At the conservative no-probe budget
the 113-run corpus now chunks into 26 batches, largest ~10,376 tokens, zero truncations —
no single message will 400. Golden gate 11/11, 23 unit tests green.

**Proposed lesson (new class):** *a component that consumes "the whole history" has an
unbounded input the moment the history grows — design the batching and the cross-batch
aggregation in from the start, and test the aggregation with a fake that returns DIFFERENT
output per batch, because a fake that ignores its input hides both the overflow and the
per-batch-undercount at once.* The corollary is the one this entry lives by: a green
offline gate over a small fixture says nothing about the real substrate's limits; the
first real run is its own gate, and it is the coordinator's to run.

**Next:** coordinator runs `python tools/lesson_miner/lesson_miner.py --real` in the next
14B window — it probes the context, prints the batch count, and (if a batch still 400s)
surfaces the OVMS body so the budget can be lowered with `--batch-tokens N`. Then read the
candidates file and, only if the golden gate is judged acceptable, flip `surfacing_dormant`.
