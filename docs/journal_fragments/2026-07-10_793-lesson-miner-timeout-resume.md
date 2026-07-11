### 2026-07-10 — Twenty-eight minutes of work, thrown away by one slow batch

*Plain summary: the #793 lesson-miner's second real pass ran the 26 chunked batches but
died at ~28 min on a urllib socket-read TimeoutError — a batch's generation on the
thermally-throttled Arc 140V 14B exceeded the client's 300 s timeout, and with no resume
every completed batch's work was lost. Fixed with a generous configurable timeout, a
lower per-batch max_tokens, batch-level resume (persist + skip completed batches), and a
progress line per batch (agentic-setup `feat/793-lesson-miner-timeout-resume`, `22ffa87`).*

This is the second time the real substrate taught the miner something the green offline
gate could not, and the two failures rhyme. The first was a 400 — the whole corpus in one
message overflowed the context. The fix, chunking, made the pass *long* instead of
*impossible*: 26 sequential batches, each a ~10k-token prefill plus grammar-constrained
generation on a 14B that is sharing a fanless Lunar Lake laptop's thermal envelope. The
client's timeout was still the 300 s I set when a "request" meant one small call. Under
throttling a single batch legitimately runs many minutes, one crossed 300 s, urllib raised
`TimeoutError`, and the pass fell over — having already spent twenty-eight minutes doing
real work it now threw entirely away, because nothing had been written down.

The timeout number is the least of it; I raised it to 1200 s and made it a flag. The
real lesson is the one the lead named: a long-running job over an unreliable substrate has
to be *resumable*, and that is a property you design in, not bolt on after it burns you.
The miner is now checkpointed — each batch's raw output is persisted to
`.work/<date>/batch-NN.json` the instant it completes, and a rerun skips every batch it
already has. A 26-batch pass that dies at batch 7 resumes at batch 7. I keyed each cache
file to a hash of its bundle, so a corpus that grew or a budget that changed between runs
invalidates the stale batch rather than merging yesterday's evidence into today's shapes —
the same class of quiet-corruption the byte-match rule exists to refuse, one layer up.

Two smaller judgments. I made a failed batch *isolated*, not *fatal*: a timeout or a parse
error on one batch is logged as a note and skipped, the pass continues over what
completed, and the failed batch — deliberately not cached — retries on the next run. One
bad batch stops being able to lose the other twenty-five. And I added a progress line per
batch, flushed, because the failure was *silent* for twenty-eight minutes: a supervisor
watching had no signal until the traceback. The no-silent-progress discipline is the same
instinct as no-silent-caps — if the system is doing something slow or dropping something,
say so as it happens. I also cut max_tokens from 4096 to 2048; candidates are small, and on
a throttled GPU every generated token is wall-clock, so most of that ceiling was pure cost.

Proven over the real 26-batch corpus with a fake model: run one writes 26 batch files and
prints 26 progress lines; the rerun makes zero model calls. The real pass is tomorrow
morning's 14B window — and this time a mid-pass death costs minutes, not the whole run.
Golden gate 11/11, 29 unit tests green.

**Proposed lesson (recurrence of the batching-unbounded-history class from the chunked-fix
fragment):** *the moment a job becomes multi-step over a substrate that can be slow or die
mid-run — a throttled local model, a flaky network, a long batch — checkpoint each step as
it completes and make rerun resume, before the first long run, not after it strands you.
A single generous timeout is necessary but not sufficient; the durable fix is that losing
step N does not cost steps 1..N-1.* The corollary that keeps holding: the first real run is
its own gate, and each one has found a limit the fixture-scale gate structurally cannot.

**Next:** coordinator runs `python tools/lesson_miner/lesson_miner.py --real` in the next
14B window. It prints a progress line per batch and caches each under
`.work/<date>/`; if it dies partway, the same command resumes from the last completed
batch. Knobs if a batch is still killed mid-generation: `--request-timeout S`,
`--batch-tokens N` (the OVMS error body is surfaced now), `--max-tokens N`. Then read the
candidates file and, only if the golden gate is judged acceptable, flip `surfacing_dormant`.
