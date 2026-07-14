### 2026-07-14 — Where a constant lives is a design decision: the cadence limb and the leaf-module rule

*Plain summary: C3 limb 2 shipped — the pure mode ladder (FULL / DETERMINISTIC-ONLY / SKIP), the runtime's first battery probe, the runtime-readable overnight window, and the cadence config keys + registry rows; dormant, review-hardened.*

Limb 2 gave the heartbeat its judgment about *when it is allowed to think*:
`shared/coordinator/cadence.py` resolves a cycle mode from four probes — swap state, power,
the overnight window, teardown — as pure code, with the two review-hardened conservative
directions from the design checkpoint locked in tests: an unreadable swap state is never
clearance to draft (unknown ≠ idle), and a failed power probe restricts while psutil's
documented "no battery device" reads as AC with a surfaced note, so a future battery-less
desktop is not perpetually throttled. The battery probe and the runtime-readable overnight
window are the first of their kind in the runtime — recon had verified power awareness
existed only in offline bench scripts.

Two judgments worth the journal. First, the reviewer caught my `from_toml` defaults as a
second, unlocked copy of the cadence constants — the drift would have been invisible until
someone tuned a constant and the two construction paths silently diverged. The fix forced a
better question: where is the constants' single source of truth allowed to live? My first
instinct (config imports cadence) broke `config.py`'s own declared invariant — it is the
package's leaf module and imports nothing from `shared.coordinator`. So the constants moved
INTO config (they are config defaults; that is their natural home), cadence re-exports
them, and a `from_toml({}) == CoordinatorConfig()` lock makes the two paths provably
identical forever. Second, the reviewer's local-time trap: the overnight window is a local
wall-clock fact, but `contains()` would happily read hours off a UTC datetime and shift
the whole quiet window by the offset — now it raises on an aware datetime (fail-loud),
handing limb 3 a contract instead of a latent bug. Also folded: bool-as-number TOML values
(`True` would have silently gutted the battery multiplier to 1.0 — no stretch), and SKIP
telemetry now records every restriction reason, not just the skip's own.

Verdict was MERGE-READY-WITH-NITS, no majors; findings 1–5 applied, finding 6 (adding the
module to the registry discovery scan) deliberately left — the scan's regex would match
nothing there today, and speculative gate-test edits are their own defect class.
Targeted suites 118 green; the combined-tree standing gate measured 7974/0 pre-fix, full
re-measure at the merge.

**Next:** limb 3 — the cycle engine, wiring the mode ladder over the composed snapshot in
the read-inject-before-compose / diff-write-after order limbs 1–2 just locked.
