# BlarAI — Field Notes

*Mechanical, environment-specific gotchas: things to grep BEFORE touching the
named surface. These are reference material, not judgment — the transferable
lessons live in `LESSONS.md` (which links here where an incident produced
both). Each note keeps its originating lesson number so the journal's evidence
trail still resolves. Add new notes at the bottom with the date and, where one
exists, the lesson or journal entry that paid for it.*

## Python / asyncio

- **Frozen-dataclass exceptions mask the real error** *(lesson 80)*. An
  exception class that is `@dataclass(frozen=True)` surfaces escaped raises as
  `FrozenInstanceError: cannot assign to field '__traceback__'`. When you see
  that signature, the real failure is an unexpected exception of a frozen
  type — read the wrapped value, don't chase the traceback assignment.
- **`asyncio.to_thread(async_fn)` returns an un-awaited coroutine** *(lesson
  150)*. Copying the sync-handler dispatch pattern onto an `async def` gateway
  leg silently breaks; a sync fake in tests will hide it. Test doubles must
  mirror sync/async-ness.
- **Python `bytes`/`str` cannot be zeroized** *(lessons 97, 106)*. Rebinding
  the name leaves the secret in the heap until GC. Only a mutable buffer
  (numpy array: `arr[:] = 0`) genuinely overwrites; for immutable secrets,
  write the honest weak-guarantee comment, never a "zeroized" claim.

## Windows / process & privilege boundaries

- **UAC elevation relaunch starts with a fresh environment** *(lessons 11,
  28)*. An env var set un-elevated does not exist in the elevated process;
  carry boundary-crossing settings as command-line flags (forwarded in
  `sys.argv`) or code constants.
- **Side effects placed before the elevation fork run twice** *(lesson 58)*.
  The un-elevated parent returns 0 and an elevated child continues; disk
  writes must sit after the last point the process can fork-and-exit.
- **`subprocess.run(capture_output=True)` deadlocks on long-lived
  grandchildren** *(lesson 161)*. Grandchildren inherit the pipe handle; EOF
  never comes, and even the timeout's cleanup blocks. For launchers that
  background daemons (OVMS, proxies): redirect to a file or DEVNULL.
- **OOM on Windows is a commit-limit event, not a physical-RAM event**
  *(lesson 169)*. A load exceeding physical RAM page-storms rather than
  raising; gate memory-risky loads on measured Available-RAM headroom, never
  on catching an allocation failure.
- **`socket.AF_HYPERV` needs CPython ≥3.12** *(lessons 82, 122)*. The 3.11
  inference venv lacks it; the version bridge runs the AF_HYPERV hop in a
  short-lived 3.14 subprocess. Don't diagnose "broken design" off `bad family`.

## WinUI / GUI automation

- **A WinUI element is in the UIA tree only when THREE conditions hold**
  *(lesson 83)*: the window is foreground with a render pass run; the element
  is a Control with an AutomationPeer (`Grid`/`StackPanel`/`Border` have
  none); and the projection is non-empty/visible. When an element is missing,
  dump the AutomationId-bearing descendants — don't theorize.
- **.NET regex `$` matches before a trailing `\n`** *(lesson 134)*. Use
  `\A…\z` absolute anchors for security gates; `^…$` semantics are per-engine
  and part of the sanitizer's contract with its consumer.
- **PowerShell 7 `Add-Type` referencing `System.Drawing` fails at runtime**
  *(lesson 174)*. The assembly forwards through a cascade that inline
  compilation can't resolve; a stubbed test can never see it — keep one
  un-stubbed test that really compiles on the target shell.
- **`.GetNewClosure()` rebinds function lookup to global scope** *(lesson
  175)*. Works one invocation level deep, breaks when the real caller runs in
  a nested (dot-sourced) scope. Test at the real invocation depth.

## Hyper-V / VM operations

- **Rewriting a file the hypervisor holds open creates a new object — ACLs do
  not follow the path** *(lesson 127)*. Re-grant the per-VM ACL after any
  in-place rebuild (e.g. a regenerated ISO), and disable automatic
  checkpoints on VMs whose state is updated out-of-band: a silent Revert is a
  success-shaped failure.
- **Cold busybox does not auto-detect iso9660** *(lesson 126)*: `mount -t
  iso9660`. A boundary runbook is a hypothesis until a real console has run
  every line.
- **Dynamic Memory reclaim is set by the floor, not the ceiling** *(lesson
  128)*, and a just-booted guest's balloon transient wears the face of a
  hardware-absent failure — measure past the warm-up window.

## Toolchain / runbooks

- **Pin the exact interpreter in every operator-facing runbook command**
  *(lesson 144)*. A bare `python` on a box with 3.11 (venv) and 3.14 (system)
  lets an early dependency-light step succeed and mask the trap until a later
  step dies on a missing module.
- **Never pip-install conversion toolchains (torch/diffusers/optimum) into
  the runtime venv** *(lesson 15; memory 2026-06-16)*. A diffusers install
  broke the numpy/transformers pins under the working inference stack — use a
  throwaway venv and route around broken exporters not on the runtime path.
