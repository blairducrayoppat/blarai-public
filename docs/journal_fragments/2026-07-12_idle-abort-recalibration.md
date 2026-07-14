### 2026-07-12 — The watchdog that mistook thinking for dying

*Plain summary: raised the ACP coder driver's semantic idle bound
`ACP_IDLE_TIMEOUT_S` from 120 s to 600 s (tools/dispatch_harness/acp_coder.py +
its shared/timeout_registry.py entry) after the first real coder battery under
driver=acp false-killed 18 of 24 candidates; corrected the falsified "heartbeats
keep it alive" docstrings and added #790 regression tests. Root-cause /
calibration entry; held on a branch for review, not merged.*

The autonomous coder fleet had been stuck at a chronic 0–1 of 6 GREEN, and the
code-quality read pointed at an idle circuit-breaker killing candidates that were
still working. It was right, and the mechanism turned out to be sharper — and
more embarrassing to our own prior measurement — than the symptom suggested.

First I had to reconcile a discrepancy the brief flagged honestly: the logs
mention a 240 s idle threshold, but the aborts fired at ~120 s. That is two
different drivers, not one confused timer. The fleet flipped `driver=acp` live on
2026-07-11; the ACP path enforces its OWN semantic bound, `ACP_IDLE_TIMEOUT_S =
120 s` ("no `session/update` for this long → wedged"), while the 240 s is the
older stdin transcript-idle default still quoted in comments and fallback params.
The 2026-07-12 battery ran ACP, so 120 s is the number that actually pulled the
trigger. Reconciled before touching anything.

Then the transcripts. The word-frequencies candidate the analysis named had, in
opencode's own folded stderr, started its main `build` generation stream at
08:25:01 — and then every channel went silent. No `session/update` reached the
Python client (it logged exactly two events all run: a startup
`available_commands_update` and a `usage_update` with `used=0`), and opencode
itself wrote not one stderr line for the full 120 s, until the driver sent
`cancel` at 08:27:01 and opencode logged `error=Aborted` mid-generation. A second
candidate showed the same shape after real work: it ran pytest, edited, then
entered one long generation burst and was killed inside it. Across the night, 18
of 24 candidates died this way — and because best-of-N draws all N candidates
through the same slow first generation, they die *together*, which is exactly how
a whole job collapses to zero GREEN.

The load-bearing fact is the one our #759 spike missed. The spike measured the
healthy 30B's max inter-event gap at 83 s and I — the design — enshrined 120 s as
"83 s plus margin, and it catches a hang faster than stdin's 240 s." But the
spike only ever measured the cold-prefill wait before the first token; it never
sampled a full generation burst. On the first real workload, generation windows
of 70 s survived and 120 s+ ones were killed, and during any of them opencode-acp
emits nothing on any channel we can observe — not the event stream, not stderr,
and (before the first edit lands) not the worktree either. So there is *no*
real-time signal that distinguishes "generating a long response" from "wedged."
The brief's suggested fix — reset the idle timer on stream tokens, not just
discrete steps — is already how the tracker works (it resets on every event,
including `agent_message_chunk`); the tokens simply never arrive as events during
the window. That correction matters: the bug was never in the reset logic, it was
in believing a spike number was a production default.

Given no signal exists, the only lever is how long to wait, and the cost is
asymmetric: false-killing a working candidate is catastrophic (and multiplies
across best-of-N), while waiting longer on a genuine hang is cheap — the 3600 s
ceiling still backstops, and at 600 s a true hang is still caught at one-sixth of
it. So I sized the bound to clear a full multi-minute generation with margin
rather than a cold-prefill gap: 600 s. I considered and rejected keeping 120 s
(proven to false-kill) and bolting on a disk- or stderr-liveness supplement (both
channels are provably dark during the exact window, so no such signal exists on
this path). The honest limit on my own number: the 120 s kills are
right-censored, so I do not know the true healthy tail — 600 s is deliberately
conservative, and the registry review note says to retighten only with real,
uncensored gap data once a battery runs at the higher bound.

One scope seam to be loud about: the value that actually governs the live battery
is `acp.idle_sec` in agentic-setup's `configs/fleet-driver.json` (it overrides
this default via `--idle-sec`). This change is blarai-side — the constant, its
registry entry, the corrected docstrings, the tests — and does not touch the
running battery. Bumping `acp.idle_sec` to match is the operator's go-live step,
the same LA/coordinator gesture that flips the driver flag, and I have left it for
the review + sign-off rather than editing a live config out from under a running
fleet.

**Next:** author≠verifier adversarial review of this branch, then the operator
bumps `acp.idle_sec` (300–600 s) and the next battery A/Bs the idle-abort rate
(baseline 18/24 ≈ 75%, target <10%) with job B2 / text-stats back to GREEN as the
proven canary; feed the real uncensored gap distribution back into the registry
to retighten.

*(commits `<this>` (branch `feat/790-idle-abort-fix`, held — never merged):
acp_coder.py 120→600 s + docstrings; timeout_registry.py entry; 3 new #790
regression tests + 2 updated; ACP + registry suites 92/92 green on the 3.11 gate.)*

**Proposed lesson:** *A threshold measured from a spike is not a production
default until the spike sampled the production distribution — and failure data
that is right-censored can only license moving a bound one way (up), never
fine-tuning it down.* The #759 spike's 83 s "max healthy gap" measured only
cold-prefill and became a hardcoded 120 s idle bound that the first real battery
proved false-kills 75% of candidates; the kills are censored at 120 s, so the
true healthy tail is still unknown and 600 s is deliberately conservative pending
real data. Neighbouring family: L145 ("measure the memory before you believe the
design") and L151 ("confirm the measurement and the ground-truth are about the
same scenario") — the integrator should judge whether this is a new number or a
recurrence tally on that measurement-representativeness class.
