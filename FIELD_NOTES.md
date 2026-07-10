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
- **PowerShell `Tee-Object` / captured stdout hangs a server-spawning launcher too**
  *(lesson 161; recurred 2026-06-28)*. The same grandchild-inherits-the-pipe
  deadlock hits `start-llm.ps1 | Tee-Object` (OVMS and the proxy never let the
  pipe reach EOF), so the wrapper never returns though the server is up. Redirect
  to a file or poll the readiness endpoint; never hold a server launcher's pipe.
- **`$?` after a pipeline reads the LAST segment's exit code** *(2026-07-03)*.
  `validator | tail` makes `$?` / `$LASTEXITCODE` report `tail`'s success and
  masks the validator's failure. Check the producing command's exit directly,
  not a post-pipe `$?`.
- **PowerShell 5.1 `[Parser]::ParseFile` reads a UTF-8-no-BOM `.ps1` as cp1252**
  *(2026-07-06)*. Em-dashes and `§` in comments/strings then produce spurious
  "unexpected token" parse errors that are NOT real. Validate UTF-8-no-BOM
  scripts with `pwsh` (PS7) — also what the scheduled task runs (`pwsh.exe -File`).

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

## Node / JavaScript

- **Static ESM `import`s are hoisted to module-link time** *(2026-07-06, #740)*.
  In a `.mjs` file, no top-of-file statement (`process.exit`, a conditional, a
  `throw`) runs before every static `import` has resolved — so an "exit early"
  guard above imports of not-yet-built modules still hard-fails with
  `ERR_MODULE_NOT_FOUND`. An inert seed/stub must contain no linkable specifier
  at all: comment the body out (line comments only — a `/* */` block dies on the
  first `*/` in a regex or glob string), or use dynamic `import()`. The trap is
  invisible on the happy path (once the modules exist, the naive guard "works").
  Proven live on node v24.13.0.

## Security / certs & runtime state

- **`provision_per_boot_certs(certs_dir=None)` writes into `<repo_root>/certs`**
  *(lesson 55; 2026-07-06)*. Called with `certs_dir=None` (or only `repo_root=`)
  it mints the nine per-boot PEMs into the REAL runtime cert dir — the
  `LOCALAPPDATA` redirect does not cover it. Any test or tool that calls it that
  way re-mints the live CA, so do NOT run the standing gate concurrently with a
  live AO serving jobs: the re-mint orphans the AO's in-memory CA and every
  subsequent mTLS turn fails `CERTIFICATE_VERIFY_FAILED`.

## Toolchain / runbooks

- **Pin the exact interpreter in every operator-facing runbook command**
  *(lesson 144)*. A bare `python` on a box with 3.11 (venv) and 3.14 (system)
  lets an early dependency-light step succeed and mask the trap until a later
  step dies on a missing module.
- **Never pip-install conversion toolchains (torch/diffusers/optimum) into
  the runtime venv** *(lesson 15; memory 2026-06-16)*. A diffusers install
  broke the numpy/transformers pins under the working inference stack — use a
  throwaway venv and route around broken exporters not on the runtime path.

## Telemetry / benchmarking

- **Intel UT ships two clocks and the level-zero one is unreliable** *(lesson 8;
  2026-06-28)*. socwatch (power/thermal) stamps Unix-epoch ns; the level-zero
  collector (GPU freq / busy / bandwidth) flags a "timestamp-units" issue and
  stamps a different clock (~27.7 h offset in one capture), yielding only a single
  whole-run blob. To segment level-zero by phase, anchor its sample range
  `[min,max]` linearly onto socwatch's Unix `[min,max]` window from the same
  `ut.exe` session — trust the level-zero clock's *linearity*, not its absolute
  value — and validate the remap physically (the GPU-busy spike must land on the
  power spike) before relying on it.
- **GPU allocations read out in `cl_mem` + `usm_host`, never `usm_device`, on this
  shared-LPDDR5X iGPU** *(lesson 8; #709)*. `usm_device` (the discrete-GPU field)
  stays ~4 MB forever; the reserved KV pool tracks `cache_size` in `cl_mem`, and
  weights plus buffers land in `usm_host`. Headlining `usm_device` reports a
  permanent zero.

## Git on Windows

- **A clone under a deep path can "succeed" with a silently failed checkout —
  and a scoped `git add` from that clone commits the rest of the tree as MASS
  DELETIONS** *(2026-07-06; journal "The trailer cut in the shadow of the
  battery")*. This repo tree carries filenames near the 260-char MAX_PATH
  (`docs/Degenerate_0-Channel_Shape_...`), so cloning it under a long base path
  (a session scratchpad) leaves a partial index; `git status` was never checked,
  three paths were staged, and the commit recorded 1,785 deletions — pushed to
  the PUBLIC repo before the stat line was read. Controls: `git config --global
  core.longpaths true` (now set); clone working repos to a SHORT base path;
  after any fresh clone, require `$LASTEXITCODE -eq 0` AND an empty
  `git status --porcelain`; and READ the commit's `--stat` line before pushing —
  a docs commit that says "1786 files changed" is the alarm, not a curiosity.
- **GitHub's blob viewer refuses to preview/play files over ~25 MB** *(2026-07-06,
  same publish arc)*. A README poster linked to `blob/main/media/<39MB>.mp4` lands
  on "we can't show files that are this big" — a dead end for viewers. Link big
  media through the repo's Pages player instead (the `demo.html`/`coder.html`
  pattern: a `<video>` tag over the raw file streams any size), or a release asset.
- **Windows venv `python.exe` is a launcher SHIM that spawns the base interpreter
  as a CHILD** *(2026-07-07/08, #761)* — `DETACHED_PROCESS` on the shim does NOT
  keep the child console-less: the console-subsystem child of a console-less
  parent gets a fresh VISIBLE console. Use the venv's `pythonw.exe` for
  console-less detached chains (its shim child is pythonw too). `CREATE_NO_WINDOW`
  = a HIDDEN console — crashes Textual ("Driver must be in application mode",
  2026-07-06); safe only for non-interactive console children (pwsh/git/tasklist).
  And the stdio trap: under pythonw a child spawned with NO explicit std handles
  may inherit a broken-but-present cp1252 stderr and CRASH on its first non-ASCII
  print (the #761 banner crash) — "prints are silent no-ops under pythonw" is only
  true when the handles are genuinely absent. Always wire detached python children
  with DEVNULL stdin + a UTF-8 append log for stdout/stderr + PYTHONIOENCODING=utf-8
  (the `boot_launcher_detached` pattern).
