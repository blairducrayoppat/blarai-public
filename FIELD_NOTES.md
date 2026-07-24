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
- **`except <Subclass>` is narrower than the base class it derives from**
  *(lesson 118; 2026-07-19)*. `except ParseChannelError` (a `ValueError`
  subclass) under a framer that raises plain `ValueError` silently drops the
  hostile frame and kills the listener. The catch must be at least as wide as
  the raise surface it guards; a `# pragma: no cover` claiming a branch
  unreachable is a claim to price adversarially, not a coverage exemption.

- **File-path `importlib` loading breaks `@dataclass` under
  `from __future__ import annotations` unless the module is registered first**
  *(2026-07-17, #929)*. The dataclass machinery resolves string annotations via
  `sys.modules[cls.__module__].__dict__`; a module loaded by file path but never
  registered yields `'NoneType' object has no attribute '__dict__'` at
  class-creation time (observed under Python 3.14). Register the module in
  `sys.modules` BEFORE `exec_module`.

## Windows / process & privilege boundaries

- **UAC elevation relaunch starts with a fresh environment** *(lessons 11,
  28)*. An env var set un-elevated does not exist in the elevated process;
  carry boundary-crossing settings as command-line flags (forwarded in
  `sys.argv`) or code constants.
- **Side effects placed before the elevation fork run twice** *(lesson 58)*.
  The un-elevated parent returns 0 and an elevated child continues; disk
  writes must sit after the last point the process can fork-and-exit.
- **`powershell.exe` mangles a BOM-less UTF-8 `.ps1` into fake syntax errors**
  *(2026-07-22)*. Windows PowerShell 5.1 reads a BOM-less script as ANSI, so
  every non-ASCII character (em dashes, arrows) becomes mojibake — and a
  stray `"` byte in the mojibake terminates a string, producing a cascade of
  bogus parse errors (`Unexpected token 'night' in expression or statement`)
  that look exactly like a corrupted file. **The file is fine.** Confirm with
  `python -c "open(p,'rb').read().decode('utf-8')"` before alarming, then
  re-run under `pwsh.exe`. Scheduled tasks here already invoke `pwsh`, so
  this bites hand-launches only — which is precisely when you are least sure
  whether you broke something. Cost a failed battery launch and a moment of
  believing the nightly wrapper was corrupt.
- **A dot-sourced library's `Set-StrictMode` leaks into the caller and turns
  every optional-key read into a throw** *(2026-07-22; #1045)*.
  `$obj.absent_key` on a `ConvertFrom-Json` object returns `$null` normally but
  raises `The property 'X' cannot be found on this object` under
  `Set-StrictMode -Version Latest` — and dot-sourcing (`. lib.ps1`) runs in the
  **caller's** scope, so one library's StrictMode governs every line after it.
  In `run-battery-night.ps1`, `ao-ownership-lib.ps1` (dot-sourced at `:59`) sets
  it at `:62`, so the `end_date` check ~170 lines later throws on the very
  optional key the script's own comment says may be omitted. **The PowerShell
  edition is irrelevant** — measured all four cells, 5.1 and 7.6.4 both
  null-and-continue with StrictMode off and both throw with it on; blaming the
  edition (as the first version of this note did) sends you to the wrong fix.
  Guard optional keys with `$obj.PSObject.Properties.Name -contains 'key'`, and
  when a script dot-sources anything, treat every later bare property read as
  StrictMode-exposed.
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
- **A daemon thread cannot tear down its own process — signal the main thread**
  *(lesson 157; 2026-07-19)*. A backend exiting to free a resource can't tear
  down from the daemon thread it serves on (it would self-join its own serve
  loop): use `_thread.interrupt_main()` → `KeyboardInterrupt` → `atexit`. Send
  and FLUSH the final operator reply before teardown — the window dies with the
  process, so reply-then-exit ordering is correctness, not politeness.
- **A gate's verdict is its summary line plus its OWN exit code — never a
  pipe's** *(lesson 209; 2026-07-19)*. `pytest | tail` reads back `tail`'s exit
  (0) — a run that died mid-suite reports green. Use bash `${PIPESTATUS[0]}` or
  capture-then-check the producer's exit; write the evidence artifact BEFORE
  the no-errors assert; and a production `os._exit(1)` reachable from inside a
  test kills pytest from within — isolate that path at the test boundary.
- **"Bound an unbounded wait" means WAKE it, not deadline it** *(lesson 256;
  2026-07-19)*. A `WaitForSingleObject(INFINITE)` child-wait that legitimately
  blocks for hours must not get a finite timeout (that fail-KILLS a healthy
  wait); replace the un-wakeable syscall with a bounded-chunk poll loop (wake
  every ~5 s, re-check, `timeout=None` preserves semantics). A poll cadence is
  a cadence, not an abort budget — register it as such.
- **A chained `<read gate> && <act>` lets the READ's exit code control the
  action** *(lesson 268; 2026-07-19)*. `tail gate.log && git merge` merged a
  red gate: `tail` printed "10 failed" and exited 0. Never chain a verdict read
  with the action it gates; never pipe gate output through `tail`/`head` at
  capture time; and a gate whose wall-time ~doubles is reporting a contended,
  invalid environment — not a result.

## WinUI / GUI automation

- **A WinUI element is in the UIA tree only when THREE conditions hold**
  *(lesson 83)*: the window is foreground with a render pass run; the element
  is a Control with an AutomationPeer (`Grid`/`StackPanel`/`Border` have
  none); and the projection is non-empty/visible. When an element is missing,
  dump the AutomationId-bearing descendants — don't theorize. Anchor assertions
  on a Control or on child text (a `TextBlock` surfaces its text as the UIA
  `Name`); anchoring on a peer-less container (`RootGrid`, `Grid`/`StackPanel`/
  `Border`) is the same no-peer bug, relocated *(enriched from lesson 83,
  2026-07-19)*.
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
- **A visibility toggle that swaps an edit buffer for a render field shows the
  STALE copy** *(lesson 129; 2026-07-19)*. When one content lives in two
  fields, flipping which is visible does not refresh it — sync on the
  transition. Headless-green plus a valid audit chain can both pass while the
  screen the human approves against shows the stale field; the `@winui`
  live-verify on such a feature is load-bearing.

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
- **`Get-VM | ConvertTo-Json` serializes `State` as the raw enum INTEGER**
  *(2026-07-11, #816; lesson 243)*. The `State` property JSON-serializes as the
  raw enum number (2, 3, …), not `"Off"`/`"Running"`, and a one-element `Get-VM`
  pipeline emits a bare object where a list is expected — two traps in one idiom.
  Emit tab-separated lines with `"$($_.Name)`t$($_.State)"` to stringify the enum
  and get a uniform line-per-VM shape at zero parse cost. And `Get-VM` with NO
  name filter is how a sealed guest stops being invisible to a box-state sweep.

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
- **A prefix allow/deny check on an un-canonicalized path is bypassable by
  `../`** *(lesson 34; 2026-07-19)*. `startswith` on the raw string admits
  `/home/user/../../etc/passwd`. Canonicalize with `posixpath`, NOT `os.path` —
  on this Windows host `os.path` rewrites `/`→`\` and breaks the very check it
  hardens (Canonical Action Requests carry POSIX paths regardless of host OS).
  Test both the raw and normalized forms; mind `normpath`'s trailing-slash and
  leading-`//` quirks.

## Toolchain / runbooks

- **Pin the exact interpreter in every operator-facing runbook command**
  *(lesson 144)*. A bare `python` on a box with 3.11 (venv) and 3.14 (system)
  lets an early dependency-light step succeed and mask the trap until a later
  step dies on a missing module.
- **Never pip-install conversion toolchains (torch/diffusers/optimum) into
  the runtime venv** *(lesson 15; memory 2026-06-16)*. A diffusers install
  broke the numpy/transformers pins under the working inference stack — use a
  throwaway venv and route around broken exporters not on the runtime path.
- **Fusing a strong style LoRA into a base you intend to prompt silences text
  conditioning** *(lesson 202; 2026-07-19)*. Fusion algebraically overwrites
  the cross-attention weights that carry the prompt (INT8 data-free
  quantization compounds it) — confident output that ignores the input. Apply
  the adapter at RUNTIME instead; prove weights-vs-harness by running a
  known-good model through the IDENTICAL convert→quantize→generate harness.
- **A hash-pinned lock with multiple digests per version is satisfied by pip
  on ANY match** *(lesson 277; 2026-07-19)*. Mutating ONE recorded hash still
  installs (looks fail-open in a tamper test). A real fail-closed proof breaks
  EVERY recorded hash of the distribution pip actually selects; don't narrow
  to a single hash (that breaks cross-platform portability) — document the
  any-match semantics in the gate test.

- **Never use backticks in a `git commit -m` message from the bash tool**
  *(2026-07-20; #987)*. Bash command-substitutes `` `like this` `` inside the
  double-quoted `-m` argument, so any code fragment you quote that way is
  **silently deleted from the commit message** — the commit still succeeds and
  looks fine until you read it back. Cost two fragments out of `12c6c14`
  (`` `while (-not (Test-NightAdmission))` `` and `` `if (-not $Now)` ``). Amending
  is forbidden here, so the only remedy is a follow-up commit or a ticket note —
  i.e. it is unfixable in place. Use a heredoc (`git commit -F -  <<'EOF'`) or
  plain quotes for any message containing code. Same hazard in PowerShell, where
  the backtick is the escape character.

- **Take BlarAI DOWN before a battery night** *(2026-07-19; #790 —
  **materially corrected 2026-07-20, #987**)*. The mechanism below is right, but
  the consequence stated in the original note ("the night silently skips") was
  **never true when it was written**: `Write-Log` used `Write-Output`, so a log
  call inside `Test-NightAdmission` was captured into its return value, which
  became a 2-element array, which coerces TRUE — so `while (-not
  (Test-NightAdmission))` never entered and the retry/skip loop was unreachable
  dead code. An app left up therefore made the night run **starved**, not skip,
  which is worse (plausible-looking data instead of a visible gap). It is also
  why no night dir in the archive has ever logged a memory number. The gate
  became real for the first time at `12c6c14`; the consequence below applies
  **from 2026-07-20 onward**. The original note was inferred from reading code
  that never executed — documentation is not evidence, including our own.
  The 23:00 admission gate
  (`agentic-setup/scripts/run-battery-night.ps1:257-347`) computes
  `Projected = Available + 8.0` when the AO is up — crediting the 14B's return
  at unload — and admits on `Projected >= 20.5`; but the #784 fallback probe
  tests **raw `Available >= 15.0`**. An app holding the 14B fails BOTH: too
  little raw memory to probe, too little projection for the fast path. The
  night then rejoins a 30-min retry loop until 04:00 and `exit 0`s. **Silent:
  not an error, not a burned attempt, and the morning report merely looks
  empty rather than wrong.** The `+8.0` credit is fast-path-only, so app-up is
  strictly the worse position under memory pressure despite appearing to gain
  headroom. Measured 2026-07-19: app up = 7.2 GiB available (would have
  skipped); launcher stopped = 18.9 GiB (probe floor cleared). Stopping the
  launcher also reproduces the AO-down topology the preflight boots for
  itself, so an A/B night's two sides stay comparable — check the prior
  night's dir for `ao-boot.log` to see which topology it ran under.

- **Run the BlarAI standing gate from the bash tool shell (or any TERM-bearing
  console with no `PYTHONIOENCODING` override)** *(lesson 77 ↺; 2026-07-18,
  #853)*. The PowerShell tool shell exports
  `PYTHONIOENCODING=utf-8:surrogateescape` and carries no `TERM`, false-failing
  `test_spawn_detached_driver_gives_the_child_real_std_handles`,
  `test_restart_launcher_gives_the_child_real_std_handles`, and
  `test_baseline_streaming_snapshot`. The tests are right (production wires the
  encoding explicitly; the snapshot needs a terminal); the shell is wrong — run
  the gate from bash, do not loosen the asserts.

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
- **A draft-wired OpenVINO GenAI pipeline needs `num_assistant_tokens` XOR
  `assistant_confidence_threshold` on every request** *(lesson 222; 2026-07-10,
  #778)*. On the OpenVINO GenAI 2026.2.1 substrate there is no per-request
  draft-OFF: a pipeline constructed with a draft model demands exactly one of
  those two generation-config knobs on every call, so spec-decode ON and OFF are
  two distinct pipeline constructions — the OFF arm is a true autoregressive
  baseline, not the same pipeline with a flag flipped. This is why a fair
  spec-decode A/B builds two pipelines (standing harness
  `scripts/benchmark_spec_decode_ab.py`).
- **The per-process view hides the movable memory — hunt the unlabeled places**
  *(lesson 270; 2026-07-19)*. On this box the reclaimable mass hid in: ~3.0 GB
  of Edge private memory across ~149 background preload processes (Edge "not
  open"); the resident 14B's ~9.7 GB in GPU-shared memory attributed to no
  working set (adapter-level only); a 776 MB `vmmemCmZygote` holding 0 MB
  physical. The OS labels the immovable plainly and hides the movable;
  `In-Use = Total − Available` remains the only honest accounting.

## Documentation

- **`git mv` a doc into a subdirectory silently BREAKS its relative links** *(2026-07-16, #14)*. A credential-lifecycle doc authored for `docs/` (links `adrs/ADR-…`, `governance/weight-integrity.md`) was moved to `docs/governance/` for convention-consistency — every relative link then resolved a level too shallow (`docs/governance/adrs/…`, `docs/governance/governance/…`, both nonexistent) and shipped broken; a fleet peer caught it post-merge. `tools/doc_lint` checks frontmatter, NOT link resolution, so it did not catch this. Control: after ANY `git mv` of a `.md`, re-grep its `](relative/` links and fix depth (`adrs/`→`../adrs/`, drop the now-current-dir prefix), and `ls` each target to confirm it resolves before merging. Better: author the doc at its FINAL path, or check links as part of the move commit.

## Git on Windows

- **A compound `cd <worktree> && git …` leaves the shell cwd IN the worktree —
  the NEXT git command runs there, not in the primary checkout** *(2026-07-16,
  #907/#911/#913 cluster)*. The Bash tool's cwd persists across calls. After
  `cd .../worktrees/911 && git commit`, a following `git merge fix/907` (meant
  for main) ran in the 911 worktree and merged #907 INTO fix/911 — non-fatal
  (main untouched; recovered by merging the clean #911 tip SHA into main and
  preserving the errant branch for audit), but a real wrong-branch merge.
  Controls: after any `cd` into a worktree, `cd /c/Users/mrbla/BlarAI` before a
  primary-checkout git op, OR use `git -C <path>` with an explicit path and
  never rely on cwd; and the git_discipline rule already says *verify
  `git branch --show-current` == your intent before every merge/commit* — the
  merge command that slipped had that check inline and it printed `fix/911`,
  which should have stopped the merge (read the check's output, don't just run it).
- **`git checkout <branch> -- <file>` to un-revert a fix restores the branch's
  COMMITTED copy — if the fix isn't committed yet, it restores the UN-fixed
  version** *(2026-07-16, #907)*. Discrimination-checking a regression lock
  (revert source → watch tests fail → restore source) with
  `git checkout <branch> -- src.py` silently reverted the still-uncommitted fix,
  and the commit then shipped tests-WITHOUT-source (the branch gate caught it).
  Controls: `git stash` the uncommitted fix instead of `checkout`ing it back, OR
  commit the fix FIRST then check discrimination; and after committing a fix,
  `git show HEAD:<src>` (or grep the committed blob) to confirm the SOURCE change
  — not just the tests — is actually in the commit.
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
- **New process spawns route through the blessed `shared.procspawn` helper — a gate
  enforces it** *(2026-07-17, #774 sub-task 4)* — all five spawn scars above (venv
  shim / pythonw / `CREATE_NO_WINDOW` / cp1252 stderr / undrained-PIPE + tree-kill)
  are encoded once in `shared/procspawn.py` (`detached_no_console` / `hidden_console`
  / `run_captured` / `terminate_process_tree`). Do NOT hand-roll a raw
  `subprocess.Popen`/`.run`/`os.system`/`os.spawn*` in `shared/`, `services/` or
  `launcher/` production code: `tests/integration/test_no_new_raw_spawn_sites.py`
  AST-scans that surface against a documented allowlist and FAILS LOUD naming any
  NEW raw site. A site that genuinely must stay raw is ADDED to that allowlist with
  a justifying comment (a deliberate reviewer act), never slipped in silently. And
  the doctrine line the helper serves: prefer typed protocols / files / sockets over
  parsed console streams — a child whose stdout you never have to interpret is a
  child this whole class can't bite.
- **A manual out-of-band patch to a `public` mirror desyncs the automated
  snapshot chain, and the weekly task fails silently** *(found + fixed
  2026-07-14)*. `agentic-setup/scripts/publish-public-snapshot.ps1` chains each
  weekly snapshot onto the LOCAL `refs/public-snapshots/main` bookkeeping ref,
  not onto whatever the remote's `main` actually is. If a session hand-patches
  the public mirror directly (the documented worktree-off-`public/main`
  pattern for a small text fix) without also advancing that local ref to the
  new remote tip, the next scheduled run builds a snapshot whose parent is the
  STALE bookkeeping commit — `git push public ...:refs/heads/main` then
  rejects non-fast-forward, and the task's only externally-visible symptom is
  `LastTaskResult: 1` on "BlarAI Public Snapshot" (Task Scheduler), with no
  alert. Fix: `git fetch public main`, `git update-ref
  refs/public-snapshots/main <actual remote tip>` in the affected repo, then
  re-run the script (`-Only <repo>`) to catch up. After ANY manual patch to a
  `public` remote, always realign the local bookkeeping ref to match before
  the next scheduled run — or better, avoid hand-patching `public` at all and
  let the script own it exclusively.
- **`Path.resolve()` does not dereference NTFS hardlinks — and `st_nlink` IS
  populated on Windows** *(2026-07-12, #848 governed-core boundary)* — a hardlink
  is a second directory entry for the *same inode*, so realpath/junction
  canonicalization returns the link's own (innocent-looking) path; identity checks
  on the governed-core surface must also compare `os.stat().st_ino`/`st_dev`,
  both Windows-correct on NTFS. Despite its reputation, `st_nlink` is reliably
  populated for real files on this NTFS host (fresh file = 1; after `os.link`
  both entries = 2 — verified on the metal; Python fills it from the handle's
  `nNumberOfLinks`). Treat an undeterminable count (0) as "not multiply-linked"
  so the link-count layer never false-denies and never substitutes for the other
  identity layers.
- **`git worktree add` populates only tracked files** *(2026-07-16, #267 doc lint)* —
  a fresh worktree has none of the gitignored `node_modules`/model trees the primary
  checkout carries (e.g. the ~19,200 files under `docs/security/**/_validate/` that
  balloon any recursive `docs/` walk ~20x), so "it didn't crash on node_modules in
  the worktree" is not evidence a skip guard works. Prove that class of guard with a
  synthetic fixture in a unit test, never a live worktree run.
- **Memory-reclaim instrumentation: carry process RSS alongside system In-Use in
  every sample** *(2026-07-16, #900)* — the lockstep/divergence of the pair IS the
  retention verdict (retention's signature: RSS falls while In-Use doesn't), and it
  rides free once you're sampling. Related accounting trap: reclaimed magnitudes
  reflect each pipeline's private+GPU footprint, not the on-disk model size —
  OpenVINO memory-maps weights and file-backed pages never count in In-Use, so an
  SDXL "3.3 GB model" evicting ~1.35 GB is not a partial free; it's accounting.
- **`git -C <dir>` on a repo-less directory walks UP to a parent repo** *(2026-07-23,
  #1058)* — any probe that runs git against a directory to read "its" history will
  silently report an enclosing repository's history if the directory has no `.git`
  at its root. Anchor first (check `<dir>/.git` exists) or set
  `GIT_CEILING_DIRECTORIES`; otherwise a wrong-subject read can look like a pass.
- **A verification harness that never prints the commit it ran against produces
  anchorless figures** *(2026-07-23, #1044)* — "0 of 29 survived, restore verified" is a
  true sentence about an *unnamed tree*, and reconstructing which tree requires someone
  to remember correctly. A dirty-tree guard does not close this: a checkout at the WRONG
  commit is perfectly clean relative to its own `HEAD`, so the guard stays silent, the run
  completes, and the report reads healthy while measuring the wrong subject. This put a
  verdict at risk three times in one evening, once because a stale worktree was handed to
  a reviewer as ready. Any mutation/probe/verification harness must emit `git rev-parse
  HEAD` and its resolved root path at the top of every run, so each figure carries its own
  subject and a stale anchor is visible IN THE ARTIFACT rather than depending on operator
  recall. Same move as counting `ANCHOR MISSING` as a survivor: vigilance becomes evidence.
  Recorded here rather than fixed in place because that harness was scratchpad tooling that
  dies with the session — the lesson outlives the script.
- **A control is not verified until you have made it FAIL on demand and STAY QUIET on
  demand** *(2026-07-23, #1044/#1054)* — the second half is the one everybody skips. Three
  instances in one evening, one per agent: a guard that decoded a git blob with `text=True`
  and so refused EVERY run including clean ones; a probe loaded with `exec_module` that
  never reached the function under test and so could only report a miss; a spec (mine) for
  a lock asserting an absence that the measured code contradicts, which could only be
  vacuous or false. All three look correct — a control that is loudly wrong is
  indistinguishable from a control that is working, until you run the case that should be
  boring.
- **`git diff main..branch` (two dots) renders main's newer commits as YOUR branch's
  deletions** *(2026-07-23, #1075/#1079)* — two-dot diffs the two TIPS, so everything
  merged into main since the branch was cut appears as a removal attributed to the
  branch. Measured on `feat/1075-deliver-not-exit` (cut at `ec787787`, main at
  `231374d5`): **37 files two-dot vs 6 three-dot** — 31 fabricated, including
  `CLAUDE.md` at `3/3`, which renders the 8868→8919 gate-baseline sync as though the
  branch were REVERTING it, plus apparent deletions of four journal fragments and
  three disposition records. It reads as a real conflict and it is entirely an
  artifact of the divergent base. Always `main...branch` (three dots, merge-base) to
  see what a branch ACTUALLY changed, and test-merge (`git merge-tree`) before
  believing any conflict story. Bit twice in one night, on two different tickets, in
  both directions (a phantom removal read as a real one, and a real conflict read as
  phantom).
- **`git log --format=%s` errors on an unborn HEAD; `--all` exits 0 with empty
  output** *(2026-07-23, #1058)* — a freshly-`git init`ed repo with zero commits
  fails plain `git log` (exit 128, "does not have any commits yet") but succeeds
  silently under `--all`. Use `--all` when "no history yet" is a legitimate state
  you must distinguish from "cannot read history" — and it also reads unmerged
  branch refs, which HEAD-only probes miss (a PARKED battery run's work lives there).
