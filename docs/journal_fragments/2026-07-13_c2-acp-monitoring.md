### 2026-07-13 — The clock the coordinator couldn't see, and "mature, not minimal"

*Plain summary: shipped the C2-inc-2 ACP `session/update`-monitoring limb — a DURABLE
wall-clock coder-run progress artifact (`shared/fleet/acp_progress.py`) the fleet's
ACP driver writes per event and the coordinator reads for its cross-run operational
view, surfaced as a "Coder run:" line on `/coord status`. DORMANT. Carries a real
lesson about escalation discipline, not a technical failure.*

This limb started with me getting the escalation boundary wrong, and the correction is
the part worth keeping. Grounding the limb, I found what looked like a wall: the ACP
driver (`tools/dispatch_harness/acp_coder.py`) tracks a live coder run's progress —
steps, edits, tokens, last-event time — in a `time.monotonic()` clock that is
*process-local* to the driver's own run. The coordinator is a separate process; it
cannot see that clock. And the driver is the fleet's acting limb, which ADR-039 §2.1
item 9 severs from the coordinator. So I stopped and brought the Lead Architect a
three-option fork (build a durable feed by touching the driver; build a feed-less
ruler; defer), with a recommendation for the *lighter* option, because I was worried
about editing a recently-integrated, battery-adjacent driver.

The LA's answer reset my calibration: *these are technical HOW questions — own them;
mature, not minimal; durable beats non-durable; resolve the short-term concern and
build the best long-term solution.* Two things were wrong in my escalation. First, I
had miscast a HOW as a decision: where a progress artifact lives and which module
writes it is implementation, not a capability or governance-posture change — the class
of thing the LA (a non-technical operator directing agents) should never be asked to
adjudicate. Second, the "short-term concern" I'd let block the better design — that the
ACP driver was recently edited — is not a reason to pick a lesser architecture; it's a
reason to make the change *safe* (additive, fail-soft, fully tested) and then build the
durable thing. The severance worry was also just wrong: severance is a property of
BlarAI's *runtime*, and I am the human-governed dev channel, not the runtime — editing
`tools/` is exactly what this channel is for. I recorded the corrected boundary so I
don't relitigate it: own technical HOW; escalate only what changes what BlarAI can do,
lowers answer quality, drops a capability, or sets a security/governance posture.

The durable solution is the mature one, and it's clean. `acp_progress.py` is a *shared
contract* both sides import (`tools/` → `shared/` is an allowed direction), so the
snapshot shape can never drift between writer and reader. The driver's `AcpEventTracker`
gains a `_write_progress()` that, after folding each `session/update`, writes a small
wall-clock snapshot — `run_id`, counts, `last_event_at` in ISO UTC — additively and
fail-soft: the write is a fire-and-forget observability side effect that never checks a
return value and never raises into the run, and the in-run idle/kill logic
(`idle_exceeded`, the 600 s `ACP_IDLE_TIMEOUT_S`, the watchdog, the cancel/cap path) is
byte-for-byte untouched. The independent reviewer's first and hardest check was exactly
that — "is the kill path unchanged?" — and it confirmed the only driver deltas are three
defaulted tracker fields, the new method, one call to it, and the wiring. The one field
that matters most is `wall_clock`, kept *separate* from the monotonic `clock`: monotonic
is correct for measuring elapsed idle inside one process, and wrong for an age a
different process computes later — the durable stamp has to be wall-clock or the whole
bridge is meaningless.

The load-bearing distinction the design draws is *observe vs. kill*. The fleet's driver
owns the hard kill — no `session/update` for 600 s cancels a wedged coder, and that stays
the acting limb's job. The coordinator only *surfaces*: `assess_acp_progress` computes
the last-event age and a SOFT "quiet" marker at 300 s — deliberately half the kill window,
so an operator watching `/coord status` sees a run go silent well before the fleet cancels
it — and it never cancels anything. Two guards keep that signal honest: "quiet" requires
the run to still be *active* (derived from whether the run's `SUMMARY.txt` exists yet), so
a finished run's stale age is never misread as a stall; and an unparseable timestamp
yields no age and no alarm rather than a false one. Both thresholds are now registered
side by side in `timeout_registry.py` with the doctrine written into the row — "a display
threshold, not a kill; the fleet's watchdog owns the kill" — so a future reader can't
mistake the soft signal for a budget.

The read side is the C1 tri-state discipline again: `read_acp_run_progress` returns EMPTY
when there's no run or no artifact (a coder run under the default `stdin` driver writes
none — a benign "nothing to show", not a failure), UNREACHABLE only when an artifact
exists but won't parse, and OK otherwise — a corrupt or absent file never crashes
`/coord status`, and the rendered summary is neutralized against injection like every
other ticket-derived string on that surface. The honest seam I'm naming rather than
hiding: the driver writes the artifact next to its per-run log and the coordinator reads
it at `runs_dir/<latest_run_id>/acp-progress.json`, which align in the standard fleet
layout; if a non-standard layout ever broke that, the read fail-softs to EMPTY, and
pinning the exact path on the real box is a go-live step, exactly like the stall limb's
activation wiring.

Everything stays dormant: the write side only runs inside the ACP driver, which is itself
dormant unless `driver=acp`; the read side is behind `[coordinator].enabled=false`. An
independent `Explore` reviewer (author≠verifier — it did not write this) verified the
idle-kill integrity, the fail-soft write, the wall-clock/monotonic split, all four
branches of the quiet ruler, the tri-state read, dormancy, and no circular imports, and
returned MERGE-READY with no blocking findings.

**Next:** the last battery-safe framing is done; what remains on #844 is the swap-path
stop-doomed-fast limb — built DORMANT behind a `[coordinator]` flag so it automerges like
the rest (the battery only matters for whoever eventually flips those checks LIVE, a later
ceremony). Then #844 closes and C3 (the heartbeat) begins.

*(commit `77475060` — the C2 ACP-monitoring limb; new `shared/fleet/acp_progress.py`
(durable contract + pure `assess_acp_progress` ruler + the registered
`DEFAULT_ACP_QUIET_THRESHOLD_S`), the additive fail-soft `_write_progress` in
`tools/dispatch_harness/acp_coder.py`, `read_acp_run_progress` + a snapshot field in
`shared/fleet/work_state.py`, the "Coder run:" line in `shared/fleet/coord_render.py`,
the timeout-registry row; +30 tests across 4 files; independent author≠verifier review
MERGE-READY, no blocking findings; standing gate 7810 passed / 0 failed, elevated +
LOCALAPPDATA-redirected. DORMANT — the write side runs only under `driver=acp`, the read
side only behind `[coordinator].enabled`.)*
