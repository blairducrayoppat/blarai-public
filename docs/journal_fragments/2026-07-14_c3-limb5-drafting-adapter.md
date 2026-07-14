### 2026-07-14 — A lock is not a residency claim, and only the lock's owner can say either safely: the drafting adapter

*Plain summary: C3 limb 5 shipped — `coordinator_draft()` on the AO service object, the heartbeat's one bounded way to reach the 14B: non-blocking try-acquire on the shared single-flight inference lock, positive residency via the image-gen eviction bookkeeping, exactly one deterministic model call, #743 grammar fail-soft; dormant, no production caller.*

The design checkpoint had already fixed this limb's central fact (§3.4, one of the review's
majors): acquiring the shared generation lock is NOT evidence the 14B is resident — the
UC-010 image-generation path evicts the model and releases the lock with it absent. What
the build added was the mechanism discovery: you cannot implement that contract THROUGH
the wrapper's own `generate()`. That method both blocks on a non-reentrant
`threading.Lock` (a wall-4 violation by construction) and lazily RELOADS an evicted 14B
(the never-initiate-a-load violation, silently, as a feature). So the seam went to the
lock's owner instead: `SharedInferencePipeline.try_run_exclusive()` try-acquires
non-blocking, checks `_pipeline is None` UNDER the held lock (race-free, because
`unload()` serialises on the same lock — the residency answer cannot go stale while the
draft runs), and hands the caller the RAW pipeline handle so the AO's existing
compose/strip/fail-closed path (`_generate_from_prompt`, one additive `pipeline_override`
kwarg) runs without re-entering the lock. The residency accessor pinned, as the limb's
named first task: the wrapper's `is_loaded` bookkeeping — the same bits
`entrypoint.py`'s image-gen big jobs flip via `unload()`.

Two paths I rejected are worth the record. Swapping the wrapper's `Lock` for an `RLock`
would have made re-entrant drafting trivial — and changed the concurrency primitive under
every PA classification and AO chat turn to save one seam method; a live-path semantic
change for a dormant feature is exactly backwards. Releasing the try-acquired lock and
then calling `generate_text()` looked simpler still, but the gap between release and
re-acquire re-opens both holes at once (a chat turn slips in → the draft BLOCKS behind
it; an eviction slips in → the draft RELOADS the 14B). The third rejection was a fourth
result status: a generation-layer failure after both defer checks pass is neither busy
nor not-resident, and the temptation to mint `failed` was real — but §3.4's tri-state is
the cycle engine's contract, so failure travels IN-BAND as a `drafted` result with empty
text and the cause in `reason`, with `has_text` as the prose-availability check and the
vocabulary gate-locked (design §2 step 9 already guarantees a deterministic fallback
rendering, so an empty draft degrades prose, never correctness). The same discipline
resolved the grammar question: "fail-soft" must not mean retry — a json-schema constraint
that cannot be BUILT degrades to the plain generation before the lock is ever taken, and
a constrained generation that CRASHES (#725's shape) is the in-band failure; either way
exactly one model call, never two under a held lock.

Locks shipped with the change: busy-defers (lock held → `busy`, zero model calls),
not_resident-defers (real `unload()` eviction → `not_resident`, rebuild closure — THE
load path — never consulted), drafted (exactly one greedy bounded call, persona + cap
asserted on the wire), grammar fail-soft (degradation named in `reason`, no raise, no
retry), lock-always-released (every status path plus two exception shapes), tri-state
vocabulary, dormancy (source scan: no production `.coordinator_draft(` caller), and
bare-import safety. 43 new locks; the AO suite + cadence canary ran 1652 green and the
other shared-pipeline consumers (launcher, PA, prefix-cache A/B) 226 green, LOCALAPPDATA
redirected throughout. One citation drift for the record: the design points at
`gpu_inference.py:689` for the single-flight lock — that line is the AO's attach-time
comment ABOUT the lock; the lock itself lives in `shared/inference/shared_pipeline.py`
(built at `build_shared_pipeline`, held per-generate).

**Next:** limb 6 (the launcher timer) wires this seam into the already-merged cycle
engine's `CycleEnv.draft` — mapping `has_text` into the cycle's draft vocabulary (an
empty `drafted` reports as a degradation, never as prose; review finding 2) — with the
step-9 call already mode-gated by limb 2's ladder before the try-acquire is even
reached; limb 7 adds the dead-man around the whole heartbeat.
