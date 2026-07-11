### 2026-07-10 — Waking the guest just long enough to sign the certificate

*Plain summary: #744 — `real_run_guest_oracle` (shared/fleet/swap_ops.py) now
ensure-starts the NIC-less orchestrator guest VM in the teardown RAM-free window,
runs the isolation-certificate probe, then stops the guest again; fail-soft stays
invariant. Recurrence of the side-effect-scoping lesson (224).*

The guest-certified oracle went live at the 2026-07-08 ceremony, but the nightly
battery's certificate never actually banked. The cause was a timing gap, not a
transport bug: the battery reboots the AO between jobs, every launcher-exit stops
the guest VM (stop-on-exit policy `always`), and the oracle probe fires later still
— in the swap machine's RAM-free teardown window, after the 30B is unloaded. By
then the guest is DOWN, so the probe reached the bridge, found nothing listening,
and recorded `not-run: guest-unreachable` every single night. The isolation
certificate the ceremony proved reachable was structurally never obtainable in the
one window it was designed to run in.

The fix is deliberately small and local to the oracle executor: before the probe,
ensure-start the guest; after the probe — pass, fail, or transport-unavailable —
stop it again. I reused the launcher's own `ensure_vm_running`/`stop_vm`
primitives rather than reimplementing any Hyper-V call; swap_ops just imports them
lazily and wraps them. The window is the correct place for this precisely because
it is RAM-free: the 14B and 30B are both unloaded, so a briefly-running guest never
competes with the 30B during a code phase. The parallelism optimisation the ticket
also floated — overlapping the VM boot with the 30B unload to hide the start
latency — I did NOT build; it is a separate follow-up (#744 c.1566) that only earns
its complexity once the sequential certificate is actually banking.

Two invariants shaped the shape of the code. First, fail-soft is load-bearing and
non-negotiable: an ensure-start that fails (or raises) degrades to an honest
`not-run`, never a blocked model restore and never a verdict change — an unreachable
guest must still leave a job's GREEN/PARKED verdict exactly as the host gate set it.
So the ensure-start sits in front of a `return {"status": "not-run", "reason":
"guest-unreachable"}` and the whole probe body lives under a `try/finally` whose
`finally` can never raise. Second — and this is where I leaned on the lesson the
ticket named explicitly — I am injecting shared-hypervisor start/stop side effects
into a path that previously had none. The trap lesson 224 warns about is a side
effect that is "fine today" because nothing else uses the resource, and leaks the
day something does. So the stop is scoped by *restore-to-prior-state*, not
unconditional: I record whether the guest was already running before I touched it,
and the `finally` stops it only if I was the one who started it. An already-running
guest (a future live-parser scenario, say) is left exactly as found. That costs one
extra `get_vm_state` read and buys the guarantee that this code can never leak a
running VM into another path nor stop a VM another path owns.

The build was offline, so the whole VM seam is injected in tests — three callables
(`guest_vm_running`, `ensure_guest_running`, `stop_guest`) with real
`launcher.vm_manager` defaults, keyword-only so the production wiring at
`build_swap_ops` is byte-unchanged. That injection is also the safety property: I
found two pre-existing tests that call the executor's real body positionally, and
had my defaults fired for real they'd have started and stopped the operator's actual
BlarAI-Orchestrator VM from inside pytest. I updated both to inject the seam, which
is the same gate-vs-live-fleet class that bit the transport go-live (a gate run once
reached the real guest). A dedicated lock proves the defaults delegate to the
launcher primitives with `vm_manager` monkeypatched, so no test ever touches real
Hyper-V.

**Next:** the certificate needs one supervised live battery night to confirm it
actually banks a `passed`/`failed` block instead of `guest-unreachable` — the probe
that proves the fix is on-hardware, not offline. If the sequential start latency
proves to hurt the swap-back budget, that is the trigger to build the #744 c.1566
parallel boot/unload overlap. Neither is in this commit.

**Recurrence of lesson 224** (side-effect scoping): adding VM start/stop into the
oracle path is a fresh instance of "when you add a write to shared state, scope it
explicitly or the isolation is a label, not a property." Here the scoping is the
restore-to-prior-state guard (stop only a guest we started) plus the `finally` that
guarantees no leaked running VM, and the local structural control is the regression
set — the already-running-guest-left-running lock and the stop-attempted-on-every-
exit-path locks in `tests/integration/test_swap_ops.py`. Prior tallies on the
class: the 2026-07-09 battery-unregister scoping (#740) and lessons 44/220.

*(commit `<this>` — shared/fleet/swap_ops.py ensure-start/stop + 8 new
regression tests + 2 existing tests hardened to inject the VM seam; 175 passed on
the swap_ops + guest-oracle-driver + guest-oracle-module selection, venv +
redirected LOCALAPPDATA. No live VM touched; the live battery-night bank awaits
on-hardware verify.)*
