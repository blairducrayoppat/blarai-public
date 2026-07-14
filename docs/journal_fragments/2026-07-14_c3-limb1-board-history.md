### 2026-07-14 — The age a board never recorded: observing entered-Ready instead of trusting created

*Plain summary: C3 limb 1 shipped — the bucket-transition record that gives work-item "age" its settled entered-Ready meaning, plus the composer switch that computes ages on the observed basis; dormant, review-hardened, gate-green.*

The first C3 build limb landed the mechanism behind the checkpoint's age decision:
`shared/fleet/coord_board_history.py`, a pure snapshot-diff over each cycle's board read
into a plaintext, owner-DACL, atomically-written record (the stall seen-set posture —
task ids, bucket titles, timestamps, no content), with episode semantics borrowed from the
stall monitor: same bucket keeps its `first_seen`, a move re-stamps, a departure prunes, a
return is a fresh episode. The composer (`work_state.py`) gained an optional
`board_history` input that injects the observed timestamp as a synthetic field and lets
`flow_metrics`/`detect_stalls` compute on it unchanged — C1's `age_basis_field` seam,
built a week earlier for exactly this move, paid off in full: the metrics module needed
zero edits.

The judgment worth recording came from the independent review (MERGE-READY-WITH-NITS, one
major). The major was a contract gap, not a code bug: `observe_board` prunes whatever is
absent from the membership it is given, and an UNREACHABLE board read that degraded to an
empty bucket list is indistinguishable, at that layer, from a genuinely empty board — so a
cycle that observed through a failed read would silently wipe a project's age history and
re-stamp everything as brand new the next cycle. The pure function cannot defend itself;
the defense is a caller precondition (observe only on OK reads, skip the project
otherwise), which is now stated on both functions so limb 3 inherits it as a contract
rather than rediscovering it as an incident. The same reviewer forced two honest
downgrades: the record's size-boundedness claim now names the de-configured-project
residue instead of overclaiming, and tampered entry keys are dropped by anchored
validation at read. Trade-off kept from the design: the created fallback for unobserved
cards was chosen over omission because a card with no age silently vanishes from the age
population — under-reporting aging work is worse than an honestly-labeled created-basis
age. Tests 23 new; targeted suites 111 green; standing gate 7937/0 with the 7 known
live-app port-5001 skips (app confirmed up on 5001, PID-verified).

**Next:** limb 2 (cadence/mode policy — built, under review), then the cycle engine that
wires read-inject-before-compose / diff-write-after in the order the review just locked.
