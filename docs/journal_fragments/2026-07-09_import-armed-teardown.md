### 2026-07-09 — The import that armed the teardown

*Plain summary: every standing-gate pytest run was force-stopping the live guest VM at
interpreter exit — `atexit.register(_cleanup)` sat at module scope in `launcher/__main__.py`, so
merely importing the module armed the full production teardown (including the policy=always real
`Stop-VM`) in every test process. Two-layer fix (#783): registration moved inside `main()` +
a root-conftest session-teardown disarm; locked by `launcher/tests/test_import_side_effects.py`
with a positive control. Worktree gate 5936/0 with the VM surviving.*

The guest VM died four times tonight before I understood why. First watch tick: VM Off, though
the handoff brief's close-state said Running. I restarted it, noted "attribution only unless it
recurs," and it recurred — at 20:27, fourteen minutes after my restart, and again at 21:07,
fourteen minutes after the next one. Tonight was the first night the VM was deliberately kept
Running (the first #744 guest-oracle certificates), which is exactly why a defect that had been
firing invisibly for weeks finally had a victim.

The hunt itself is the lesson in instrumentation. The production launcher's log showed nothing at
any stop time — the right conclusion (the stopper was not the production launcher) hiding inside
a misleading one (nothing logged anywhere). The Hyper-V event log gave the shape: host-initiated
force shutdowns, each ~9–15 minutes after a start. Three of the four stops lined up with the
ENDS of standing-gate runs — the daylight close-out gate, the M1 builder's gate, the M1
reviewer's gate — and the temp directories the test discipline creates (`blarai-pytest-userdata-*`)
held the fingerprint: zero-byte `launcher.log` files, created at import by the logging config,
stamped within minutes of each kill. A process that imported `launcher.__main__`, wrote nothing,
and stopped a real VM on its way out.

The mechanism: `atexit.register(_cleanup)` at module scope, plus the #657-era ratchet that made
`_cleanup_vm`'s default policy `always` — stop the VM whenever it is Running, even if this
process never started it. Correct and deliberate for a real launcher exit; lethal from a pytest
process that imported the module for a unit test. The fourth kill sharpened it further: my own
bisect run, on the ALREADY-FIXED worktree, still killed the VM — because tests that drive
`main()` legitimately arm the (now correctly-placed) registration, and at interpreter exit their
monkeypatches are long torn down, so the handler fires with REAL bindings. Import-time
registration was the visible half; main()-driving tests were the residual half. One defect class,
two entry doors.

So the fix is two-layer, deliberately mirroring the #758 reconcile-guard precedent: production-
side, the registration moves inside `main()` — importing the module is now side-effect-free, and
the instance-lock refusal path is unaffected (it hard-exits via `os._exit`, which skips atexit
entirely; dispatch tree-kills skip it too, which is precisely why the guest-oracle go-live
ceremony never tripped this). Test-side, a session-scoped autouse fixture in the root conftest
unregisters a leaked `_cleanup` at session teardown, while pytest still controls the process. The
lock (`test_import_side_effects.py`) runs child interpreters: a bare import must never reach the
VM seams, and — lesson 222 applied — a positive-control sibling that registers `_cleanup`
explicitly MUST trip the same recorder, so a silent pass is a proven absence, not a broken probe.
Honestly named: the conftest layer has no headless lock of its own (proving it requires a live
hypervisor mid-gate); its proof is tonight's empirical run — the exact three-file selection that
killed the VM, then the full standing gate (5936/0, 2:27), both with the VM Running throughout.

The trade-off worth recording: I did NOT merge tonight. The fix touches `launcher/__main__.py`,
and the battery re-boots the AO from main's checkout if a swap-back flakes mid-night — a live
surface I will not change hours before the first unguarded 23:00 launch. The VM-killer only fires
from pytest runs, and no gate runs happen overnight; the branch merges in the morning motion with
the M1 integration. Until then the defect is contained by scheduling, not by code — named,
bounded, and mine to carry to morning.

**Recurrence of lesson 224:** the parameterized-isolation lesson's exact shape, third door —
LOCALAPPDATA redirection scopes the DATA, but the hypervisor is shared state keyed to the code
path; a test run's isolation is only as complete as the side-effect enumeration, and `atexit`
handlers are side effects. (The alarm-clock incident scoped a scheduled task; #758 scoped the
fleet root; tonight scoped the hypervisor.)

**Next:** merge `fix/launcher-atexit-vm-stop` in the morning motion (gate on main, canonical
count); watch the first post-merge gate run with the VM up as the live confirm; sweep the other
repos' test suites for module-scope `atexit` registrations at the next quiet window (#783 tracks).

*(commits: blarai `fix/launcher-atexit-vm-stop` @ `<this>` — the two-layer fix + the import
side-effect lock + this fragment; evidence: Hyper-V Worker-Admin events 18504/18506 at 18:20 /
19:03 / 20:27 / 21:07 vs the gate-run windows; worktree gate 5936/0/122 in 2:27 with the VM
surviving; #740 c.1551 flagged the recurrence, #783 carries the class.)*
