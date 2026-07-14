### 2026-07-14 — A fail-closed design can still write fail-open seams: the C3 checkpoint review

*Plain summary: the C3 heartbeat design doc was authored, adversarially reviewed (5 majors found and fixed), and approved by the LA at the checkpoint; the review caught fail-open defaults inside a document written explicitly around fail-closed doctrine.*

The Coordinator program reached its first design-before-code checkpoint today. C3 (#845) is
the first coordinator wiring into a live path — an in-process, launcher-managed timer — and
the LA had directed on 2026-07-13 that a design document precede any build. I authored
`docs/research/c3-heartbeat-design-2026-07.md` over three parallel read-only recon sweeps
(launcher boot/teardown seams, the C1/C2 API surface, and the swap/power/schedule
substrates), settling the ADR-039 §2.14.2 age definition — entered-Ready, operationalized
as first-observed-in-bucket via per-cycle snapshot-diffing, with `created` demoted to
tie-break and surfaced fallback; the rejected path (created as the standing basis) is on
the record in the doc's §4.2, rejected because backlog dwell is not queue wait and a
created basis falsifies both FIFO fairness and aging-WIP outlier detection.

The instructive part was the independent review. I wrote the document around ADR-039's
fail-closed discipline — and the adversarial verifier still found five majors, two of which
were exactly the defect class the doctrine names. My mode ladder computed "swap in flight"
from `swap_in_flight`, which is false when the swap-state read is UNREACHABLE — so an
unreadable swap state would have read as clearance to draft on the model: a fail-open,
inside a section that lectured about UNKNOWN-never-permissive. And my shadow-mode routing
table sent the dead-man watchdog's own alarms into the shadow journal — an alarm nobody
reads, which is §2.14.1's forbidden operator-vigilance dependence rebuilt one layer up. Both
took one-line fixes; neither would have been visible in a green test suite until go-live.
The lesson is not "review catches typos" — it is that fail-open regenerates at every new
seam unless each seam is individually interrogated, and that the author is the wrong person
to interrogate their own seams. The review also caught a conflation with teeth: holding the
shared-pipeline generation lock is not evidence the 14B is resident (image generation can
evict it and release the lock), so drafting now requires a positive residency signal and
may never trigger a load. Verdict was CHECKPOINT-READY-WITH-FIXES; all ten findings and
four nits were applied before the LA saw the document.

At the checkpoint the LA approved the design and the seven-limb build plan, and asked the
right operational question — isn't the heartbeat most needed while the fleet is running?
It is, and the design already says so: the deterministic organizing (harvest, board moves,
stall comments, redispatch staging) runs in every mode including overnight and mid-swap;
only model drafting and the quiet-queue alarm defer while the GPU belongs to the fleet.
That his reading of my chat summary suggested otherwise is a summarization lesson: the
compression "quiet overnight" traded away the load-bearing distinction (deterministic work
continues; only the model waits), and the operator caught it. Checkpoint outcome recorded
on #845; the build (seven dormant limbs, C2's flow) begins from this approval.

**Next:** C3 limb 1 (the bucket-transition record + observed age basis), then limbs 2–7 in
the doc's §11 order, each dormant, gate-green, author≠verifier reviewed.
