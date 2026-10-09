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

- **Hostile invisible codepoints in test SOURCE survive review invisibly** *(2026-07-30,
  #1165 M5)*. A test that feeds bidi-override, zero-width or over-length filenames must
  carry the literals as `\uXXXX` escapes a reviewer can actually see, decoded to genuinely
  hostile bytes at runtime. Pasting the raw codepoints makes the fixture correct and the
  diff unreadable — and an unreadable adversarial fixture is one nobody can check.
- **A toggle test must restore the SAVED original of a module-level global, never a literal** *(lesson 30; 2026-09-17, #1548)*. A `finally` that resets the global to a hardcoded value (here `frozenset()`) is correct for the first test and wrong for every later one: under a whole-file run the first toggle blanks the global and every later reader sees the blank, so a tripwire written to fire on a change to that set cannot fire. Measured: a reviewer added a tool to the set and the file reported 19 passed. Save before mutating, restore the saved object, and run the mutation under the whole-file selection the gate runs, not the single test.

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
- **An empty file parses to `$null` WITHOUT throwing, so the `try` around
  `ConvertFrom-Json` never fires** *(2026-07-30, #1180; lesson 329's entry)*. Under
  `Set-StrictMode -Version Latest` the failure surfaces one line later, on the first
  member read of the `$null` result, and a `try` narrowed to wrap only the parse lets it
  escape to the caller. Guard the member reads, not just the parse — and fixture a
  zero-byte file plus a valid-but-incomplete object whenever you tighten a JSON guard.
- **A file another thread rewrites atomically is briefly UNOPENABLE on Windows: a tight poll that reads it RAISES, it does not time out** *(lesson 160 tally, 2026-09-19; #1597)*. `test_graduation_reset_stamps_current_mode_immediately` polled the heartbeat's `heartbeat-liveness.json` with `sleep(0.01)` while the heartbeat thread replaced the file; a read that landed inside the replace window raised `PermissionError: [Errno 13]`, which no deadline can catch, so two deadline widenings (5 s to 30 s) fixed nothing. Retry a transient read failure and keep the deadline for a genuine hang. Machine load widens the window, which is why the failure correlated with a busy box. The traceback was invisible for two months because the gate script piped pytest through `tail`.

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

- **A dispatched review agent's report does NOT arrive on its own — "idle" is
  not "delivered"** *(2026-07-30, #1237/#1239)*. A subagent spawned with the
  Agent tool signals completion as an `idle_notification` carrying no content;
  its final text reaches the lead only via an explicit `SendMessage` asking for
  it. Observed on two independent reviewers in one session, so it is the harness
  and not the agent. The hazard is not the extra round-trip: a lead that reads
  "idle" as "came back with nothing" can merge a branch believing the review
  found no findings, when the review found several and was never asked for them
  — silence and a clean verdict are indistinguishable, which is the same
  unmeasured-instrument shape this arc keeps finding. **Never treat an absent
  report as a clean one. Pull it, and if the agent says it did not finish, take
  that over a complete-looking summary.**
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


- **A stray control character inside a doc line makes `str.splitlines()` see two lines where
  `split("\n")` sees one — and any per-line checker goes blind to everything after it.**
  `LESSONS_ARCHIVE.md` carried a Windows path written as `WindowsPowerShell\v1.0` in some
  earlier script, where `\v` had been interpreted as a vertical tab (`\x0b`). Nothing
  rendered wrong. But `check_lesson_tallies.py` counts `*(recurred: …)*` markers PER LINE via
  `splitlines()`, which treats U+000B as a line boundary — so lesson 46's eighth recurrence sat
  in the file, invisible to the tool, and the index flag `↺8` looked like drift against a
  counted 7. The instrument was right that something was wrong and wrong about what.
  **When a per-line doc checker disagrees with your own reading, compare `splitlines()` against
  `split("\n")` before adjudicating the content** — `splitlines()` also breaks on
  `\x0c`, `\x1c`-`\x1e`, `\x85`, U+2028 and U+2029.
- **OVMS refuses `--cache_dir` and `--plugin_config` together, and dies with an EMPTY
  stderr** *(2026-08-31, #1477)*. On the continuous-batching LLM servable OVMS folds
  `--cache_dir` INTO the plugin config as `CACHE_DIR` (#747), so supplying both yields
  `Failed to create plugin config: Plugin config is in wrong format`, the server shuts
  down during load, and the `.err` file is **zero bytes** — it looks exactly like a model
  or memory failure. Put the cache directory INSIDE the JSON
  (`{"CACHE_DIR":"B:/...","OFFLOAD_RATIO":"30"}`) and drop `--cache_dir`. Forward slashes
  remain mandatory (a backslash makes the folded JSON invalid — that is #747's original
  finding). Killed two measurement arms before being understood.
- **PowerShell `Start-Process -ArgumentList` does not escape embedded double quotes**
  *(2026-08-31, #1477)*. A JSON argument written the obvious way arrives at the child
  process as `{OFFLOAD_RATIO:30}` — quotes stripped, invalid JSON, same fatal error as
  above and equally silent. Write the escapes literally in the PowerShell string
  (`'{\"OFFLOAD_RATIO\":\"30\"}'`) so the child receives real quotes, and **verify by
  reading the launched command line back out of `Win32_Process`** rather than trusting the
  script's own echo — the echo prints the array join and looks identical either way. Bash
  quoting on the same box is predictable and was used to isolate the cause.
- **This machine's decode rate falls monotonically under sustained GPU load, and it
  outweighs configuration** *(2026-08-31, #1487)*. One unchanged config measured 16.55,
  11.82 then 9.59 tok/s across a single hour on an idle box (first run of the session
  16.82, last 8.07) with GPU-shared memory flat throughout, so it is not the #1477 memory
  mechanism. Consequence for method: **never A/B two configurations by running them in
  sequence here** — the second arm is penalised by elapsed session time, and the effect
  (~40%) is bigger than any config difference measured so far (~12%). Interleave
  (A,B,A,B) or randomise, and record run-index and elapsed-session-time in the stamp.
- **The only readable ACPI thermal zone on this box is a fixed trip point, not a sensor**
  *(2026-08-31, #1477)*. It reports a constant 91.1 °C idle AND loaded. Do not cite it as
  evidence of thermal behaviour in either direction; there is currently no usable
  temperature reading on this hardware, which is why #1487's leading hypothesis cannot be
  confirmed or excluded.

## Documentation

- **`git mv` a doc into a subdirectory silently BREAKS its relative links** *(2026-07-16, #14)*. A credential-lifecycle doc authored for `docs/` (links `adrs/ADR-…`, `governance/weight-integrity.md`) was moved to `docs/governance/` for convention-consistency — every relative link then resolved a level too shallow (`docs/governance/adrs/…`, `docs/governance/governance/…`, both nonexistent) and shipped broken; a fleet peer caught it post-merge. `tools/doc_lint` checks frontmatter, NOT link resolution, so it did not catch this. Control: after ANY `git mv` of a `.md`, re-grep its `](relative/` links and fix depth (`adrs/`→`../adrs/`, drop the now-current-dir prefix), and `ls` each target to confirm it resolves before merging. Better: author the doc at its FINAL path, or check links as part of the move commit.


- **A commit message written with `git commit -m "…"` in bash loses every backticked
  identifier.** Backticks inside double quotes are command substitution, so a message full of
  `symbol` references arrives with holes where the symbols were — and bash prints
  `symbol: command not found` for each one, which is easy to read as noise while the commit
  succeeds. It cost the #1237 merge commit its gate figure: the body now reads `absent: .`
  where a measured result line belonged. History is not rewritten here, so the record went to
  the ticket instead. **Always `git commit -F <file>` (or a quoted heredoc into `-F -`) for
  any message containing backticks.** Note `git merge` does NOT accept `-F -` — it wants a
  real path.
- **A backslash escape written into a `python - <<'PY'` heredoc can arrive collapsed.** Writing
  a replacement of `\\v` reached Python as `\v`, i.e. a vertical tab —
  so a script replacing a vertical tab with a literal backslash-v silently replaced it with
  itself and reported success. Build such literals with `chr(92)` instead of escapes when the
  payload is itself a backslash sequence.
## Searching Python for call sites

- **A bare `name(` grep MISSES call sites passed as callables — `asyncio.to_thread(self.store.add_turn, ...)`
  never matches `add_turn(`** *(2026-09-17, #1547)*. Tracing every writer to the encrypted session
  store, a `add_turn(` grep found the WinUI dispatcher and missed the Textual shell entirely, because
  `ui_shell` hands the method to `asyncio.to_thread` as a bare reference. An entire persistence surface
  was invisible to the search, and a trace that concluded from it would have been confidently wrong about
  which UIs write what. Grep the bare NAME (no paren) when enumerating call sites for a security trace,
  then filter; the noise is cheaper than a missing surface.

## Git on Windows

- **A mutation-testing reviewer edits the working tree LIVE. Never commit while one is
  running, and re-check `git status` immediately before every commit, not merely before the
  batch** *(2026-09-17, #1543)*. An adversarial reviewer asked to prove a control's tests are
  real does it by NEUTERING the control and confirming the tests fail — so for a few seconds
  at a time the working tree holds a security control with its check removed. A `git status`
  taken during that window shows a modified file; seconds later the reviewer restores it and
  the diff is empty. Both readings are correct and neither is the whole picture. The failure
  this guards against is the worst shape available: `git add` landing mid-mutation would
  commit a **disabled control together with the tests that certify it works**, and the gate
  would pass, because the tests were written against the working version. The reviewer is not
  misbehaving — restoring after each probe is exactly right. The hazard is concurrency with a
  commit, not the reviewer.

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
- **A point-in-time inventory of a LIVE mutation harness is indistinguishable from a
  stranded mutation** *(2026-07-23, #1044)* — both show one dirty source file with
  mutated content and no obvious runner process. A mutation harness spends most of its
  wall time with a file deliberately broken, and it spawns `python.exe -m pytest`, not a
  `pytest` image, so a process check by name finds nothing; there is also a sub-second
  window between the subprocess exiting and the restore write where the file is mutated
  and truly nothing is running. Worked example, and it is the lead's: inventorying
  `wt-mut-verify` during mutation **29 of 29** produced a confident, well-argued,
  written-down finding that a run had died and stranded broken source. The run completed
  normally seconds later — `restore verified`, `0 of 29`. The observation was a race; the
  reasoning on top of it was sound and entirely wrong. **The guard shares the blind spot,
  and that is the part worth writing down:** `_refuse_poisoned_baseline` aimed at a tree
  with a run in flight refuses correctly *by accident*, while stating the wrong reason
  ("poisoned baseline" for what is actually "busy"). A control that reaches the right
  outcome through the wrong diagnosis will be trusted for the wrong reason the next time
  it fires — and the fix is not the outcome, it is making the two states distinguishable
  (a run-marker file, deferred as a named follow-up on the harness's review). Sixth ring
  of the same family in one evening: manifest checker → ceremony-read config comments →
  docstrings → stranded mutation → stale anchor → in-flight vs stranded.

### A backtick in a bash heredoc commit message is COMMAND SUBSTITUTION, and it eats the word silently

Writing a commit message with `git commit -F - <<'EOF'` protects `$` and backticks — the quoted
`'EOF'` makes the heredoc literal. Writing one with `git merge -m "..."` in the same bash call
does NOT: the message is an ordinary double-quoted shell argument, so `` `raw` `` is executed as
a command and replaced by its (empty) output.

Measured 2026-08-15: a merge message reading *"DispatchCommand gains `raw`, carried beside the
parser's interpretation"* landed as *"DispatchCommand gains , carried beside…"*, with
`bash: line 1: raw: command not found` printed above the successful merge — easy to read as
noise from the merge itself rather than as damage to the message.

**Practice:** use the quoted heredoc form (`-F - <<'EOF'`) for ANY message containing backticks,
including merges. If one slips through, do NOT `--amend` to fix prose — that is a history
rewrite for a typo, and this repo forbids rewrites outright. Record the correction where it will
be read (the ticket, the journal) and leave the commit alone.

## Fleet dispatch / coder harness

- **The coder runs on Windows but its shell commands execute under bash, and the model
  does not reliably know which shell it is addressing** *(2026-07-23, #1073)* — a cmd.exe
  redirect to a reserved device name (`nul`, `con`, `prn`, `aux`, `com1`–`9`, `lpt1`–`9`,
  e.g. `del /q test_cards.json 2>nul`) run under bash creates a literal file with that
  name, because bash has no `nul` special-case and `del` doesn't exist so the shell
  writes the error text into a file called `nul` instead. Git cannot remove it: two
  `git clean -fd` passes and four `git worktree remove --force` calls all leave it in
  place, and it poisons the worktree for every later run. Plain `rm nul` from bash
  removes it instantly — the capability was always there, the harness's own cleanup
  just never took a path that could see the reserved name.

- **`repos-archived/` inside a battery night directory holds the PREVIOUS night, not
  that night** *(2026-07-30, #1180; lesson 328's entry)* — `run-battery-night.ps1:662-673`
  renames the outgoing tree into place at 23:00 as the new run begins. A morning
  inspection that opens `night-<date>/repos-archived/` is reading the night before, and
  the mistake is invisible whenever two consecutive nights produce structurally identical
  deliveries — which is the normal case for a frozen exam card. Name the night you mean
  and check a scorecard timestamp before drawing a conclusion from a delivered tree.

- **A pinned worktree is DETACHED by design, so any `-eq 'main'` freshness test is
  `$false` forever** *(2026-07-30, #1181a; lesson 332's entry)* — git refuses to check
  out `main` in a second worktree, so the detachment is forced rather than incidental.
  Freshness must be tested by resolving the commit (ancestry against `main`), never by
  comparing a branch name; a name test makes a correctly-pinned night indistinguishable
  from a broken one and prints the alarm banner every single night.
- **A mutation harness that counts a crashed run as KILLED reports a kill rate it cannot lose** *(2026-10-05, #1691, round one of the fused-leg review)* — the harness copied three files into each mutant sandbox, the suite read a fourth, every mutant copy errored on the missing file, and an error was counted as a kill. A reviewer added a mutant known to survive and the harness still reported "22 of 22 killed"; the builder's reported kills were real, the harness simply could not report a survivor. Run an UNMUTATED control through the same harness and require it to pass, and define "killed" as a named failing check, never as a non-zero exit. (Sibling of the 2026-07-30 PYTHONPATH/conftest note, which fails the other way: every mutant SURVIVED. cf. lessons 222, 215.)

## Vikunja API

- **Vikunja v2.3.0 answers `GET /users?s=<no match>` with JSON `null`, not `[]`**
  *(2026-07-23, #1034)* — any code walking that endpoint through a shared page-walker
  that wraps a non-list first page receives `[None]`: a truthy, one-row list whose row
  is `None`, which defeats an `or []` guard downstream and raises `AttributeError` on
  the first attribute access. Separately, `GET /tasks/{id}/assignees` returns HTTP 500
  on every task in this server version, with or without paging parameters — a
  pre-existing, unrelated defect (#1072), not a pagination issue.

- **Public-mirror publisher: two desync signatures from one script** *(2026-07-24, #1104)*
  — the publisher aborts at the leak-gate BEFORE `update-ref`, so a leak-gate block leaves
  `refs/public-snapshots/main` untouched (stuck at the last good snapshot), whereas a PUSH
  failure leaves the ref one commit AHEAD of the remote. Same script, two different desync
  fingerprints; diagnose accordingly before touching either ref.

- **Piped stdout on this host is cp1252, so a non-ASCII byte kills a fleet tool**
  *(2026-07-30, #746)* — `python -c "sys.stdout.write('α')" | cat` raises
  `UnicodeEncodeError`, and Node's `execFile` spawns the opencode tool wrappers exactly
  that way. `agentic-setup/tools/search_docs.py` is safe only because `json.dump`'s
  `ensure_ascii` defaults to True; "improving" that to `ensure_ascii=False` makes one
  Greek letter in an MDN excerpt surface to the coder as `tool_error` while the corpus
  holds the answer. Any new stdout-emitting tool on the fleet path needs a regression
  lock driven through a real subprocess pipe with a non-ASCII payload — an in-process
  test cannot see this.

- **A stale 0-byte `.git/index.lock` blocks every commit and reports nothing useful**
  *(2026-07-30)* — one left at 12:19 by an interrupted operation silently failed every
  `git add`/`git commit` in the primary checkout for three hours, which is how a day's
  work accumulates uncommitted while each session assumes the previous one chose not to
  bank it. Diagnose with three checks before removing: zero length, age far beyond any
  real operation, and no `git` process running. All three, or leave it alone.

- **A pytest plugin injected via PYTHONPATH loads; a `conftest.py` there does not**
  *(2026-07-30, #1204)* — conftest is collected only from the rootdir's own tree, so a
  mutation harness that parks a `conftest.py` on `PYTHONPATH` runs entirely unmutated
  code and reports every mutant as SURVIVED. Use `-p <module>` instead, and make the
  harness assert it actually injected — a mutation run that cannot prove it mutated
  anything is an instrument reporting confidently while measuring nothing.

- **TWO `-m launcher` processes at the same start time is the HEALTHY shape, not a leak**
  *(2026-07-31)* — a boot produces a venv `pythonw.exe -m launcher` supervisor holding
  ~0.01 GB, which spawns a CHILD running the SYSTEM `Python311\pythonw.exe -m launcher`
  that holds the resident 14B (~12.6 GB) and owns the `:5001` listener. Same
  `StartTime` to the second, child's `ParentProcessId` == the supervisor. Two facts make
  this read like an incident when it is not: the child runs a DIFFERENT interpreter from
  the one that launched it, and agents running `services/ui_gateway/` suites also run
  system Python, so a process list shows the same exe on both a test run and the live
  app. Confirm with `ParentProcessId` and `StartTime` before concluding anything —
  a documented prior incident is a leaked AO on 5001 turning gate failures into silent
  skips, so the instinct to reap is right and the target here is wrong. Reaping the
  child evicts the model; reaping the supervisor orphans it.

- **`:5001` does not serve HTTP — a failed health probe is not evidence of a wedged app**
  *(2026-07-31)* — `Invoke-WebRequest http://127.0.0.1:5001/` fails with a transport
  error against a perfectly healthy assistant, because that port carries the IPC
  protocol rather than HTTP. Liveness comes from the listener existing plus
  `Get-Process -Id <pid>` reporting `Responding=True`, never from an HTTP status. An
  overnight stall-detector keyed on an HTTP probe would kill a healthy app on its first
  pass — measure the process, not a protocol it never spoke.

### The LOCALAPPDATA safety redirect invalidates any measurement of environment-derived paths

The standing rule redirects `LOCALAPPDATA` before every pytest run, because an unredirected run
once corrupted the operator's live `sessions.db`. That redirect is correct and must stay.

It also silently breaks any diagnostic that reads a path DERIVED from `LOCALAPPDATA`.

2026-08-08, chasing #1350: `grade_env.uv_dir_overlay` appeared to pin only uv's interpreter
directory and not its wheel cache — which looked like the cause of a month of `not-run` stamps.
It was an artifact. The diagnostic ran under the safety redirect, so the overlay computed
`%LOCALAPPDATA%\uv\cache` against the temporary directory, found nothing there, and correctly
omitted it. Run with a clean environment the overlay pins both, against a real 26 GB cache.

**When measuring anything derived from `LOCALAPPDATA`, `APPDATA` or `HOME` — uv/pip caches,
managed interpreters, per-user tool state — run the probe WITHOUT the redirect.** The redirect
protects writes; it falsifies reads. Both facts are true at once and only the first is
documented anywhere else.

Symptom to recognise: a path-resolution function that returns fewer entries than its docstring
promises, with no error. It is omitting what it cannot find, exactly as designed.

### The battery scheduled task lives in `\BlarAI\`, not the task-scheduler root

`Start-ScheduledTask -TaskName 'BlarAI-M2-Battery-Nightly'` fails with *"The system cannot find
the file specified"*. So does `Get-ScheduledTaskInfo -TaskName …`. The task is registered under
the **`\BlarAI\` folder**, so every by-name cmdlet needs `-TaskPath '\BlarAI\'`.

`Get-ScheduledTask -TaskName …` finds it WITHOUT the path, which is what makes this confusing:
one cmdlet resolves the bare name and its siblings do not. Piping the object
(`$t | Get-ScheduledTaskInfo`) always works, because the object carries its own path.

Only `BlarAI Public Snapshot` and `BlarAI System Backup` sit at the root. Everything else —
`BlarAI-M2-Battery-Nightly`, `BlarAI-Coder-Leg`, the one-shots — is under `\BlarAI\`.

**Never confirm a battery launch from a process-table match alone.** The obvious pattern
(`CommandLine -match 'battery-bootstrap|run-battery-night'`) matches THE SAMPLING COMMAND
ITSELF, so a failed trigger looks like a successful one. 2026-08-09: a `pwsh.exe` that appeared
to be the battery was the query that went looking for it. Confirm with three independent
witnesses — the task reporting `Running`, `CommandLine -like '*battery-bootstrap.ps1*'` on a
process that is not `$PID`, and a NEW `night-*` directory on disk.

**The anchored form, because the three-witness rule above did not stop the recurrence.**
2026-08-11 the same class bit both watchdogs, two days after this note was written: their
liveness probes used the bare substring match and counted the authoring session's own tool
shell. Match the INVOCATION FORM bound to the image that can host it, never the text alone:

```powershell
$_.Name -match '^(pwsh|powershell)\.exe$' -and
  $_.CommandLine -match '-File\s+"?[^"]*[\\/](battery-bootstrap|run-battery-night)\.ps1'
$_.Name -match '^pythonw?\.exe$' -and $_.CommandLine -match '-m\s+tools\.dispatch_harness\.battery'
```

Reference implementation: `agentic-setup/scripts/run-battery-night.ps1`, `Get-LiveDispatch`.
Note which DIRECTION each failure runs, because they are opposite bugs: in a watchdog looking
for a DEAD night a self-match is a false negative (the watch goes quiet, and quiet is
indistinguishable from healthy); in an archive guard looking for a LIVE dispatch it is a false
positive that stands the night down forever. A control that can be silenced by writing its own
name is not a control.

**And a directory is not an event.** `night-<today>-*` existing does not mean tonight's trigger
fired — Windows' missed-task catch-up can create one at any hour (measured 2026-08-14: a 13:28
catch-up attempt satisfied a 23:30 trigger-miss check). Parse the stamp's TIME and compare it
against the trigger's own hour, not just its date.

### Battery logs contain verdict strings inside CONFIG PROSE — anchor your patterns

`launcher.log` records why each card was excluded, and those exclusion reasons quote past
verdicts verbatim. B3's reads: *"…STALLED [HARNESS] on the budget kill (night-20260707-230002)
and no pass containing B3 at this grain can bank…"*

A monitor grepping `STALLED \[[A-Z-]+\]` fires **90 seconds into a perfectly healthy run**, on
prose describing a different card on a different night a month earlier.

A real verdict always carries its card prefix:

```
[battery B9] STALLED [HARNESS] -> …\scorecards\B9.scorecard.json
[battery B9] dispatching battery-b9-pottery-site …
```

So anchor on `\[battery [A-Za-z0-9]+\] (STALLED|GREEN|PARKED-HONEST|RECOVERED)`, never the bare
verdict word. Same rule for anything reading these logs programmatically — the file is part
narration, part record, and only the prefixed lines are the record.

A watchdog that cries wolf gets muted, which is strictly worse than having none: the false
alarm trains you to skim exactly the channel you built to be believed.

### `night-*/ao-boot.log` is TRUNCATED — it records the failed first boot, never the one that works

The battery's preflight boot fail-closes on a Policy Agent handshake after roughly four
minutes, logs `entrypoint stopped` and `Cleanup: closing session store`, and the file ends.
**Something else then brings the assistant up and does the entire night's work, writing nothing
into the night directory.**

Proof, from the 2026-08-07 GREEN run (`20260807-195617-bd`):

```
ao-boot.log last line   19:58:05   "Cleanup: closing session store"
oracle-qa.json mtime    19:58:41   <- after the "shutdown"
run-fleet-*.log mtimes  20:38 … 21:55   five coder tasks dispatched and merged
scorecard wall_clock_s  11119 s (3 h 5 min), verdict GREEN
```

**Consequence: you cannot diagnose a battery night from `ao-boot.log`.** It looks IDENTICAL on
a night that works and a night that stalls, because on both it contains only the first boot's
death. On 2026-08-09 that file produced three separate confident wrong diagnoses in one
session — an AttributeError, an interactive Textual UI, and a fail-closed PA handshake — every
one of which turned out to be present on the successful night too.

**When a log and the filesystem disagree, believe the filesystem.** File modification times in
`state/fleet-runs/<run-id>/` are a side effect of doing the work; a log line is a claim about
it. Comparing mtimes against the log's last line is what broke this open, after four hours of
comparing logs to each other.

Corollary for any battery diagnosis: establish what the run ACTUALLY did (run-dir mtimes,
scorecard `wall_clock_s`, merged commits) before reading a word of any log.

### A restored file can still run MUTATED — CPython's `.pyc` staleness check is second-granular

Any mutation harness on this tree (edit production code → run → confirm red → restore) can get
a **false green on the restore**, and the source will look perfectly correct while it happens.

CPython validates cached bytecode on `(int(mtime_seconds), size)`. A same-SIZE edit reverted
inside the same wall-clock second leaves the `.pyc` looking valid, so the interpreter keeps
running the mutated bytecode against a restored source file.

Found 2026-08-09 while toggle-proving the instrument registry: the mutation was
`REPEAT_THRESHOLD = 3` → `= 1`, which is byte-identical in length. Everything else that day
changed size and never showed the fault.

**After restoring a mutated file, delete `__pycache__` before re-running** — do not trust a
green that follows a same-size revert. The general rule: a size-preserving edit is the case
where every mtime-plus-size cache lies to you, and toggle-proofs are exactly where size-preserving
edits live (flipping a constant, `True`→`Fals`, `and`→`or `).

### Session cron is NOT a dead-man control — it silently does not fire

Measured twice, 2026-08-09. Five one-shot `CronCreate` jobs armed across the day to catch a
battery run; **not one fired.** They stay listed as pending past their fire time and simply never
arrive. They are session-only (nothing on disk), they only fire while the REPL is idle, and even
a genuinely idle 105-minute window did not produce a single firing.

**Do not use cron as the thing that catches a missed signal.** It is a reminder that sometimes
works, not a control. The only mechanism observed to fire reliably is a **`Monitor`** — a live
loop that emits on its own stdout — and it must be `persistent: true` or it dies at its timeout
(default 5 min, max 1 h) partway through anything worth watching.

Three ways a Monitor still fails to notice, all committed on the same afternoon:

1. **Watching the wrong file.** `night-*/battery-runner.log` is written at battery START and END
   only. Every per-task event — `TASK-START`, `TASK-END`, park, retry — goes to
   `state/fleet-runs/<runid>/journal.log`. A monitor on the night log sees nothing for hours while
   tasks complete and park.
2. **An upper bound on the staleness window.** A hang check written as
   `AGE -gt 200 && AGE -lt 900` excludes every stall longer than 15 minutes — i.e. exactly the
   ones worth waking for. Staleness alarms take a floor, never a ceiling.
3. **Emitting only on change.** "Nothing has happened" is then indistinguishable from "nothing has
   gone wrong". A dead-man must emit on SILENCE, on a timer, and keep re-emitting.

And the trap underneath all three: **quiet ≠ stuck.** A finished coder candidate stops writing its
`*.agent.log` exactly like a hung one does. What separates them is the terminal marker
(`exiting loop` / `disposing instance`) in the tail — require its ABSENCE before calling a hang,
or the watcher cries wolf on every successful candidate.

---

- **Restarting the launcher by hand: use `boot_launcher_detached`, never `Start-Process`** (2026-08-10)

  Stopping the launcher for a clean gate run is routine. Bringing it back is not, and three
  reasonable-looking attempts failed:

  | attempt | result |
  |---|---|
  | `Start-Process pythonw.exe -m launcher` (system python) | died before writing a log line |
  | `Start-Process .venv\Scripts\pythonw.exe … -RedirectStandardOutput/-Error` | full boot, then `AssertionError: Driver must be in application mode` |
  | `Start-Process .venv\Scripts\pythonw.exe … -WindowStyle Hidden` | same crash, same line |

  Every failure is the **Textual driver**, and every one of them happens AFTER a completely
  successful boot — Policy Agent up, AO up, preflight passed, heartbeat started — so the log
  looks healthy right up to the crash and the cleanup that follows reads like a normal shutdown.

  Two independent causes, both about what the child's std handles are:

  1. **Redirecting stdout/stderr** gives Textual handles whose `fileno()` is `None`.
  2. **A hidden console** (`-WindowStyle Hidden`, and equally `CREATE_NO_WINDOW`) is worse than
     either a real console or none at all — Textual takes the Windows driver path and then cannot
     enter application mode.

  The repo already says so, at `shared/fleet/swap_ops.py` `_NO_WINDOW`: *"NEVER apply this flag to
  a python/pythonw LAUNCHER spawn … a HIDDEN console is the exact shape that crashed Textual on
  2026-07-06 ('Driver must be in application mode')."* Same crash, same message, sixteen months of
  calendar apart in the log and one `grep` away the whole time.

  **Do this instead** — the production path, which spawns `pythonw` with
  `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB`, `stdin=DEVNULL`, and
  stdout to a real file handle, so Textual gets *no console at all* and takes its headless fallback:

  ```
  .venv/Scripts/python.exe -c "
  import sys; sys.path.insert(0, '.')
  from pathlib import Path
  from tools.dispatch_harness.battery import boot_launcher_detached
  boot_launcher_detached(Path('C:/Users/mrbla/BlarAI'),
                         Path('C:/Users/mrbla/AppData/Local/BlarAI/launcher-restart.log'))
  "
  ```

  It runs the teardown barrier first (proving any prior AO holding the instance lock is dead), so
  it is also the safe thing to run when you are not certain the old one is gone. Boot to
  `Boot-Phase-3: OPERATIONAL — input enabled` takes **35-50 s** on a warm box — a check at 12 s
  reports "not running" for an instance that is booting perfectly well.

### An ad-hoc probe has none of the defences the real code has earned

Three times on 2026-08-14 a five-minute probe disagreed with a verifier and the probe was wrong.
Each is a distinct trap and all three cost real minutes:

1. **A `Write-Log` stub written with `Write-Output` pollutes the return value.** PowerShell's
   success stream IS the return value, so a function that logs with `Write-Output` returns
   `@(logline, actualResult)`. A `$null` return then fails `$null -eq $r`, and the probe reports
   a guard BLOCKING when it cleared. Production code is locked against this
   (`verify-battery-ao-lifecycle.ps1` A6, "Write-Log does NOT use Write-Output"); a throwaway
   stub is not. Use `$script:Log.Add($m) | Out-Null`, or `Write-Host`.

2. **`powershell` is 5.1, `pwsh` is 7.** Invoking a PS7 verifier with `powershell -File` fails on
   `??`, `?.`, and ternaries — surfacing as bogus assertion failures rather than a syntax error.
   A verifier that is green under `pwsh` and red under `powershell` is telling you which shell
   you used, not what the code does.

3. **Bash-nested quoting silently mangles a PowerShell parse check.** `powershell -Command "...
   \$(@(\$e).Count) ..."` from a bash heredoc reported 3 parse errors in a file that has none.
   Run parse checks through the PowerShell tool directly, never through a quoting layer.

The general rule, learned the same day three times: **when a probe you just wrote disagrees with
a verifier that has been green for months, suspect the probe first.** The verifier has toggle
tests, seam tests and a history; the probe has none of that and was written while you were
already convinced of the answer. (2026-08-14; #1380, #1375; lesson 349's mechanism at probe
scale.)

### agentic-setup verifiers do NOT share a summary format — a one-shape grep reports the others as silent

Sweeping the verifier suite on 2026-08-15 I grepped every result for `Passed: *[0-9]+` and read
two blanks as "no output". Both were passing:

| verifier | its summary line |
|---|---|
| most `verify-*.ps1` | `Passed:  138` |
| `verify-website-review-loop.ps1` | `107 passed, 0 failed` |
| `verify-capture-cdp.mjs` (node) | `pass 66` |

A silent verifier and a passing one are indistinguishable through a grep for one shape, and the
failure is in the reporting direction that reads as success. Match all three, or check the exit
code, and never infer green from a summary line you did not see.

### The verifier harness exits at its Result section — tests appended after it never run

Appending cases to the end of `verify-complexity.ps1` (2026-08-15) put them AFTER
`Section 'Result'`, which prints the tally and exits. The suite ran, reported `Passed: 37`, went
green, and silently executed none of the ten new checks. Moving them above the anchor took the
count 37 -> 47, which was the only tell.

Insert before the Result section, and read the COUNT rather than the exit code — a suite that
drops tests silently still exits 0. Same shape in `verify-mutationgate.ps1` and any sibling that
ends with a tally-then-exit block.

### `Get-Process` has no `CommandLine` under `powershell.exe` — a process probe written that way reads QUIET while the box is busy

`powershell.exe` is Windows PowerShell 5.1, whose `Get-Process` objects carry no `CommandLine`
property. So this:

```powershell
@(Get-Process -Name node,python,pwsh | Where-Object { $_.CommandLine -match 'run-fleet|battery' }).Count
```

returns **0** with six battery processes running — the filter matched nothing because the
property does not exist. It does not error. Use `Get-CimInstance Win32_Process` instead, which
carries `CommandLine` on both editions:

```powershell
@(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pwsh.exe' OR Name='node.exe'" |
  Where-Object { $_.CommandLine -match 'run-fleet|dispatch_harness\.battery' }).Count
```

`pwsh.exe` (7+) DOES populate `CommandLine` on `Get-Process`, so the same line works
interactively and fails when a script shells out through `powershell.exe`. That difference is
why it survives a read-through. Caught 2026-08-15 by running the probe against a live battery
and expecting a refusal that never came.

### A process probe can match ITSELF — filter by process name or it never reaches zero

A `Where-Object { $_.CommandLine -match 'run-fleet|battery' }` scan run from bash matches the
`bash.exe` and `powershell.exe` in its own pipeline, because the pattern text is *in their
command lines*. The count then never reaches 0 and any "wait until quiet" loop waits forever —
fail-closed, and uselessly so. The `-Filter "Name='...'"` clause is what excludes the probe's
own shell; it is load-bearing, not an optimisation.

Toggle-check any such probe both ways: the real pattern must count the live work, and an
impossible pattern must return 0. If the impossible pattern does not return 0, the probe is
counting itself.

### `verify_disposition.py`: write a disposition row starting with its ticket number and it used to vanish

Rows are naturally written `#1391 item 3 | FIXED | <sha>`, and the parser treated every line
beginning with `#` as a comment — so those rows never existed, and the verifier printed a
self-consistent `3 ok of 3` over a record holding eight. Fixed 2026-08-15 (`02177ca4`): a `#`
line is a comment only when it lacks the two pipes that make it a row, with the block's own
column header excluded by its literal `status` middle field. If you are reading an older
disposition record, check its row count by eye before trusting its total.

### The doctrine-freshness gate compares the two gate-figure surfaces only to EACH OTHER

`CLAUDE.md`'s `<status_snapshot>` "Standing gate:" line and `TEST_GOVERNANCE.md` §1's
`LIVE_GATE_BASELINE` must agree — and a **wrong-but-consistent pair passes silently**. Take the
number from the run, not from a landing card or from arithmetic. Predicting it first and then
checking the prediction against the gate output is cheap and catches a dropped test file: on
2026-08-15 the count moved 11057 → 11072 → 11080, each step exactly the number of tests added,
which is what proved none had been silently skipped.

### Watching a live battery run: three signals that look like liveness and are not

Three false readings in one session (2026-08-15), all the same shape — a watcher pointed at
something that does not move *while the work is happening*, so a healthy run and a dead one
produce identical silence. Grep this before writing any run monitor.

| signal | why it fools you |
|---|---|
| `state/battery/night-<stamp>/battery-runner.log` | **stays 0 bytes for the whole run.** Nothing ever writes it. A `tail -f` on it reports silence for five hours. |
| the launcher pid from `Start-Process battery-bootstrap.ps1` | **exits by design, minutes in.** Its own `swap-progress.log` says so: *"Swap driver spawned; the launcher is exiting now."* A liveness check on that pid fires a false end-of-run. |
| `state/fleet-runs/<run-id>/` file mtimes | written only **between** candidates. A candidate may take 30–60 min, so the directory is legitimately quiet for half an hour mid-task. A 12-minute idle threshold fires on a perfectly healthy run. |

**What actually moves while a candidate is generating:**

1. **`ovms.exe` CPU time climbs.** Measured on the 16:09 run: 293 s → 941 s → 1167 s → 2541 s
   across the first two tasks. This is the strongest single signal.
2. **`state/worktrees/<repo>-<task-slug>/`** gains and changes files — the coder builds in an
   isolated worktree, not in the sandbox and not in the run dir.
3. `state/fleet-runs/<run-id>/journal.log` gains `TASK-START` / `TASK-END` at task boundaries
   only. Good for progress, useless for liveness.

**Use at least two, and treat a stall as confirmed only when all of them are flat.** A single
flat signal is the default state of a working run, not evidence of a hang — which is the same
trap as `acp.idle_sec`, where a blind "no session update" signal was raised 120 s → 600 s
without ever becoming able to tell a slow generation from a wedged one.

Note the sandbox `C:/Users/mrbla/projects/<repo>` is NOT a liveness signal either: it changes
only at merge time, so it can sit untouched for an entire wave.

### Starting the launcher unattended: a HIDDEN console is worse than NO console

**Headless is designed, proven and named** — `Ensure-AoHeadless` (`run-battery-night.ps1:1312`),
and Textual ships a headless driver. It has worked for months. If a restart fails, the capability
is not missing; the spawn shape is wrong.

`shared/fleet/swap_ops.py:459-464` states it, and this note exists because the comment did not stop
a session from doing it anyway on 2026-08-15 — nine days after the same defect on 2026-07-06:

> **NEVER apply CREATE_NO_WINDOW to a python/pythonw LAUNCHER spawn**: a HIDDEN console is the
> exact shape that crashed Textual ("Driver must be in application mode"). The launcher chain uses
> pythonw.exe (no console AT ALL → Textual's proven headless-driver fallback).

**Three states, and the middle one is the trap:**

| spawn shape | result |
|---|---|
| real console | works, TUI renders |
| **hidden / partial console** (Scheduled Task, `CREATE_NO_WINDOW`) | **crashes** — Textual picks the Windows driver, which has no writer thread |
| **no console at all** (`pythonw.exe`) | **works** — headless driver |

**The authoritative command is already recorded**, not to be re-derived:
`state/fleet-swap/spec.json` → `relaunch_argv` = `["...\.venv\Scripts\pythonw.exe", "-m", "launcher"]`,
with `relaunch_cwd`. Read that before inventing a launch.

### The launcher also SELF-ELEVATES — a non-elevated start exits after ~44 seconds, quietly and cleanly

`python -m launcher` requests UAC elevation and then **terminates the current process** to relaunch
elevated. In a headless or detached context there is nothing to answer the prompt, so the relaunch
never happens and you are left with nothing running. The tell is one line in
`%LOCALAPPDATA%\BlarAI\launcher.log`:

```
[blarai.launcher] INFO: Elevation requested — current process exiting
[blarai.launcher] INFO: Cleanup: shutting down components
[blarai.launcher] INFO: Cleanup: complete
```

**It looks like a healthy shutdown**, because it is one — orderly cleanup, VM left as-is, lock
released. Nothing says "failed". A foreground run looks even healthier: token hardening, per-boot
mTLS certs, signed-manifest and weight-integrity checks all pass, the shared pipeline starts
building — and *then* it exits. Every early signal is green.

**Elevation is only the FIRST blocker, and a Scheduled Task is NOT the fix** — it supplies the
hidden console above, which is the second failure:

```
[blarai.launcher] ERROR: TUI crashed: Driver must be in application mode
  textual/drivers/windows_driver.py:53
  assert self._writer_thread is not None, "Driver must be in application mode"
```

That "Driver" is **Textual's terminal driver, not the GPU driver** — the name misleads badly on a
project where a GPU driver assertion is entirely plausible. The launcher's default surface is the
Textual TUI (ADR-014; `--winui` selects the other), and Textual needs a real console. A Scheduled
Task has none, so it starts, passes every security check, opens port 5001 for about fifteen
seconds, then crashes and cleans up.

**So a scheduled task gets FURTHER, not all the way.** `-RunLevel Highest` is necessary and not
sufficient.

**What actually works** is a relaunch from a process already inside the operator's interactive
desktop session — which is exactly what the battery's swap-back does. Its own recorded command
(`state/fleet-swap/spec.json`) is **byte-identical to the one that fails from a task**:

```json
"relaunch_argv": ["C:\Users\mrbla\BlarAI\.venv\Scripts\pythonw.exe", "-m", "launcher"]
```

**The command is not the variable. The session is.** Do not conclude from a failed restart that
the argv is wrong; check where it was spawned from.

```powershell
$a = New-ScheduledTaskAction -Execute 'C:\Users\mrbla\BlarAI\.venv\Scripts\pythonw.exe' `
       -Argument '-m launcher' -WorkingDirectory 'C:\Users\mrbla\BlarAI'
$p = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
Register-ScheduledTask -TaskName '<name>' -Action $a -Principal $p -Force
Start-ScheduledTask -TaskName '<name>'
```

`-RunLevel Limited` fails exactly as a bare `Start-Process` does. This is the same rule the
overnight GPU work already lives under — *hand-launched consoles strand on UAC* — and it applies
to the assistant itself, which is easy to miss because the battery's swap-back restores it
without anyone thinking about elevation (the battery already runs elevated).

**Two costs, both paid on 2026-08-15.** The assistant was stopped at 18:48 for a clean gate and
stayed down until 22:02, across three restart attempts, because each attempt produced processes
that existed when checked at 5–12 seconds and were gone by the time anyone looked again.

**And do not judge the restart by the port.** Port 5001 does not open until the 14B has compiled,
which is minutes. `netstat` at twelve seconds proves nothing either way — the correct check is
*process alive AND log advancing*, with the port as the final confirmation.

### A default value that is never overwritten looks exactly like a computed one

`REVIEW VERDICT: UNCLEAR` appears in **554 of 576** banked task logs. It reads as a reviewer
that could not decide. It is the **initialiser**:

```powershell
$verdict = 'UNCLEAR'; $reviewTail = ''
# [4/5] REVIEW ... Only runs when the gates are NOT both green (Test-ShouldRunReview)
# ... Green-gated work skips review entirely (the deterministic gate already decided).
```

554 means 554 tasks passed build + tests + verify and **correctly skipped review**. The system
working as designed. Nothing was undecided because nothing was asked.

**The check that would have caught it, in one line:** does an artifact exist that only the
computing code could have produced? Here, `*.review.log` — and there is none for any B9 run; the
newest on disk is from June, on a different project. *An output with no corresponding log was not
computed.*

**The trap that made it worse, and this is the transferable part.** The wrong hypothesis was
tested properly first: `new-agent-task.ps1:757` genuinely forces `UNCLEAR` when the review agent
times out, so that was a real candidate — and it was refuted with real data (3 logs corpus-wide
mention a review timeout, 2 of them UNCLEAR: **0.4%**). Refuting it correctly *increased*
confidence in the surrounding framing, which had never been checked at all.

> **Checking how a value can be OVERRIDDEN is not the same as checking whether the code that SETS
> it ever RUNS.** Eliminating a competing explanation says nothing about the one you started with.

Measured cost on 2026-08-16: twenty-five minutes and a high-priority ticket asserting a working
component was broken, filed and then retracted (#1426).

**Where else this shape lives in this codebase** — worth grepping before trusting any of them:
a skipped review reported as a verdict; `not_measured: []` on a run that measured almost nothing;
`DEFAULT_ORACLE_PATH` standing in for an oracle that was never generated (#1417); `gamed: False`
from a scan that read no delivered code (#1416). **The failure is never a blank — it is a
confident, plausible value where a blank belonged.**

### A slow coder-30b number is invalid while the BlarAI app is up — two causes, one symptom

`scripts/benchmark_ovms_http.py` now REFUSES to measure while `:5001` has a listener (exit 2,
before the warmup). If you are reading this because the guard fired: close the app or stop the
launcher, re-run, restart it afterwards. `--allow-ao-resident` measures anyway and stamps
`ao_resident: true` into the record so it can never be mistaken for a baseline.

**Why the refusal, rather than a warning.** On this iGPU "GPU shared memory" IS system RAM, so a
resident 14B does not merely compete with the 30B for a pool — the coder's weights spill and
decode collapses ~13x. **That collapse is byte-identical in shape to the `--cache_size` defect
(#1477): same ~3 tok/s, same watchdog kills, same everything.** Measured on one OVMS process
with nothing else changed: launcher UP → 2.11 / 3.20 tok/s; launcher STOPPED → 34.31 / 39.01.

So the two causes are indistinguishable from the number alone, and the wrong one sends you into
an OVMS bisect that will exonerate every flag — because there is nothing wrong with the server.

**A real dispatch never hits this**, which is why it is a measurement condition and not a defect:
`prepare_and_launch_swap` hands off to the detached driver and the coordinator then exits the
launcher for the whole run. The contended state is one a *diagnostic* session creates by hand-
starting OVMS next to a live app — i.e. exactly what you are doing when you reach for this bench.

> **A benchmark that cannot state the condition it was taken under is not evidence.** The guard is
> in the harness rather than in a ticket comment because guidance does not survive a context
> window; a non-zero exit does.

**What the record does NOT tell you.** The condition is sampled TWICE — at pre-flight and again
before the record is written — and `condition_samples: 2` says so in the record itself. The
interval between them is unsampled, so **both flags false means "clean at both ends", not "clean
throughout"**. An app that appears and exits inside the window is invisible here *and* leaves a
persistent depression behind it, because a 14B evicts the 30B's weights from shared memory and
that does not reverse when the launcher does (#1483). Also: `ao_resident_override` means THE
START GATE WAS OVERRIDDEN, not "this record is trustworthy" — **to select clean baselines filter
on `ao_resident == false`, never on the override field.**

Lock: `tests/integration/test_benchmark_ovms_http_ao_guard.py` (17 tests, including the toggle
proving `--allow-ao-resident` is what lifts the refusal — a guard with no off-switch and a guard
that never fires look identical from a green — and the lock proving an AO appearing mid-run is
caught by the end sample).

### A text-mode "restore" rewrites every line ending in the file — toggle-proofs must use bytes

*(lesson 359's arc, 2026-08-17.)* On Windows, `Path.write_text` and `open(mode="w")` translate
every `\n` to `\r\n`. So a save-mutate-restore cycle — toggle-proving a lock, patching a file in
place, mutating a fix back out to check the lock goes red — **does not restore the file**. It
rewrites it, silently, adding one byte per line. Measured once at **1,137 bytes of invisible
damage** in a single file, and separately a file that *grew by 281 bytes* while the edit was
trying to shrink it by 121.

**Use `read_bytes` / `write_bytes` for the whole cycle, and verify the restored sha256 equals the
original.** The hash check is the only thing that catches it; the file looks correct, `git diff`
shows the whole file changed, and by then you no longer know which lines you meant to touch.

The wider trap: a toggle that did not actually apply looks **exactly** like a lock that cannot
fail. Assert the file changed before running the tests, and assert it changed back afterwards.

---

### HTML `required` blocks the page's own submit handler — validation code can exist and be unreachable

*(lesson 357's arc, 2026-08-17.)* A control carrying the HTML `required` attribute is enforced by
the browser's **interactive constraint validation, which runs BEFORE the `submit` event fires**. A
page's own `submit` handler therefore never runs while any required field is blank — the browser
blocks submission and shows its own grey bubble instead.

Consequence when reading a page's source to decide whether it validates: custom per-field messages
written in a `submit` handler **cannot fire for blank input**. They can only appear for input that
passes `required` and then fails a JavaScript rule — a one-character name, a malformed email. Blank
is precisely the case they cannot cover, and blank is usually the case being asked about.

**Escapes that genuinely restore reachability**, all of which must be checked before concluding the
validation is dead:

- a listener on a non-submit event — `blur`, `input`, `change`, `click`
- `novalidate` on the `<form>`
- `formnovalidate` on the submit button
- a control without `required`

Attribute listeners to the **innermost** enclosing handler, not the outermost: two of three banked
deliveries nest `submit` inside `DOMContentLoaded`, and an outermost-span rule credits every
message to `DOMContentLoaded`, reads that as a non-submit trigger, and calls dead code reachable.

### A shell heredoc eats backslashes out of a regex — and `` can become a literal 0x08 byte

*(lesson 359's arc, 2026-08-31. This note was PROPOSED in a journal fragment, the fold's prose
claimed "all four are now field notes", and this was the one that never landed — recovered from
the deleted fragment during an independent review of the fold.)*

Writing a Python patch script into a `bash` heredoc collapses backslash escapes before Python
ever sees them, even when the delimiter is quoted in ways you expect to protect it:

- `and` silently becomes `and` — the word-boundary anchors are gone and the pattern now
  matches inside other words.
- Worse, `` can arrive as a literal **0x08** (backspace) byte *inside* the pattern, which is
  invisible in every editor and in most terminal output.

**Prefer patterns that need no backslashes at all** — `r",| and "` over `r",|and"` — and
**scan the written file for control bytes before trusting it**:

```python
bad = [(i, b) for i, b in enumerate(open(p, "rb").read()) if b < 9 or 13 < b < 32]
assert not bad, f"control bytes in the written file: {bad[:5]}"
```

Related failure in the same family: a `python - <<'PY'` heredoc whose payload is itself a
backslash sequence (see the `` note above). The general rule is that the shell is a second
escaping layer you did not design, so keep payloads escape-free rather than escaping them twice.

## `git checkout-index` is destructive and was not in the guard (2026-09-20)

The destructive-git hook (`~/.claude/hooks/block_destructive_git.py`) covered
`git checkout -- <path>`, `git restore`, `git reset --hard`, `git clean -f`,
`git branch -D`, force-push, rebase, filter-branch and `commit --amend`. It did
**not** cover `git checkout-index`, which overwrites working-tree files from the
index with no prompt and no undo.

I used it to "restore" a file during a mutation-test cleanup and destroyed an
uncommitted config change. Then, while adding the rule, I destroyed the same
file a second time. **Two mechanics, both worth knowing:**

1. **The guard is an allowlist-shaped blocklist.** A destructive git verb that
   is not named in `_RULES` is permitted, and a miss is silent. When reaching
   for an unfamiliar git verb, assume it is unguarded rather than assuming the
   hook has you covered. `cp` aside and `cp` back needs no verb at all.

2. **Editing the hook and exercising it in the SAME tool call does not work.**
   The hook evaluates the command before the call runs, so it reads the
   pre-edit file. The rule only takes effect from the next call onward — which
   is why the second destruction happened inside the very command that added
   the rule meant to prevent it.

**Verify a guard by MATCHING, never by executing.** Import the hook module and
run its `_RULES` regexes against candidate command strings. Executing the real
destructive command to see whether it is blocked is a test that destroys
something whenever it fails:

```python
import importlib.util, pathlib, re
spec = importlib.util.spec_from_file_location(
    "guard", pathlib.Path.home() / ".claude" / "hooks" / "block_destructive_git.py")
guard = importlib.util.module_from_spec(spec); spec.loader.exec_module(guard)
hit = next((label for pat, label, _ in guard._RULES if re.search(pat, cmd)), None)
```

Note the guard matches the raw command text, so the verb appearing inside a
quoted string in an unrelated script also trips it. That is a false positive in
the safe direction; build the verb at runtime (`"checkout" + "-index"`) if a
script genuinely needs to name it.


## The iGPU memory budget is a registry percentage that the display-driver installer rewrites (2026-09-21)

Two `HKLM` values decide how much system memory the Arc 140V may commit, and
they are not the same number (PERFORMANCE_LOG 2026-09-01, #1485, #1501):

- `SYSTEM\CurrentControlSet\Control\GraphicsDrivers\MemoryManager\SystemPartitionCommitLimitPercentage`
  — the budget PERFORMANCE_LOG 2026-09-01 identifies as the binding one (`pct/100 ×
  total RAM`; 87 → 27.25 GiB, 57 → 17.85 GiB). That entry calls it a strong candidate
  rather than a closed answer — #1485 owns settling it — but its 17.85 GiB predicted
  the measured cliff to the gigabyte.
- `SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\0001\GMM\GpuSystemMemoryPinninglimit`
  — what OpenVINO REPORTS, through `alignDown(floor(0.94 × pct/100 × total) − 450 MiB, 4096)`
  (87 → 27,031,388,160 bytes; 57 → 17,547,509,760 — both reproduced to the byte).

Mechanics observed on this box, all from key last-write times against the event
log: an Intel display-driver package install writes the DXGK key to 57 (26 Aug
18:04:55, oem180.inf; 14 Sep 23:08:17, the Windows Update install of
32.0.101.8831), and the Intel Arc software syncs the REPORTED key to the real one
about a minute after boot (1 Sep 03:26; 21 Sep 17:28:45). Between an install and
the next boot the two disagree and OpenVINO reports a budget ~7.3 GiB larger than
the DXGK one — the "instrument lies" week of 26 Aug–1 Sep. When weights plus the
reserved KV pool cross the DXGK figure, decode collapses by reservation, not
occupancy (the 13× coder cliff).

Read both keys before trusting any throughput number on this machine, and after
any driver or Arc-software install. `shared.perf_env_capture.capture_box_state()`
stamps both (`gpu_budget`) plus `machine_uptime_s` since #1611; a boot-time check
that refuses a model whose weights + pool exceed the real budget is #1455's. The
`Get-Item` cmdlet does not expose a key's last-write time; `RegQueryInfoKey` via
`Add-Type` does. Key last-write time = the second the value was written, which is
how the installer was identified.

## Qwen3.5/3.6 chat templates open a `<think>` block unless you say otherwise (2026-09-22)

*Grep this before building a prompt for, or reading an eval of, any Qwen3.5/3.6
export — including the 35B-A3B and the 27B. It cost a wrong model verdict that
stood for two months (#1611 S0c; lesson 369).*

**The template's default branch is the thinking branch.** In
`chat_template.jinja` of `OpenVINO/Qwen3.6-35B-A3B-int4-ov` (lines 171-175, and
the same shape in siblings):

```jinja
{%- if enable_thinking is defined and enable_thinking is false %}
    {{- '<think>\n\n</think>\n\n' }}      <- closed EMPTY block = do not think
{%- else %}
    {{- '<think>\n' }}                    <- a BARE OPEN = think now
{%- endif %}
```

`enable_thinking` **undefined takes the else branch**. There is no neutral
setting: a prompt that says nothing is a prompt that has opened a reasoning
block and is asking the model to fill it in. Omission is not a default here, it
is an instruction.

**Three ways to get the closed block, all verified to render correctly:**

- `Tokenizer.apply_chat_template(msgs, True, extra_context={"enable_thinking": False})`
  — the API built for it, and the cheapest way to CHECK a render without a GPU.
- Hand-built ChatML ending in the literal `<think>\n\n</think>\n\n`, with
  `GenerationConfig.apply_chat_template = False` set **explicitly** — this is
  what the Policy Agent ships. Leave that flag at its default `True` and the
  template wraps your string a second time.
- `set_chat_template` with the condition inverted so no-think is the default.
  Note this MUTATES the pipeline, so run it last in any multi-arm comparison.
  The patch that applies is on the **condition**; a naive replace of the
  `{{- '<think>\n' }}` literal is the fiddly one to get right.

**Cheap pre-flight, no model load:** `ov_genai.Tokenizer(model_dir)` loads only
the tokenizer IR. Render the prompt and assert on the tail before spending a
GPU window. `<think>` = token 248068 and `</think>` = 248069 on this export;
both round-trip through `decode()` as literal text, so they are NOT skipped as
special tokens and WILL appear in output text.

**The strip needs a matched pair, so a prompt-opened block is unstrippable.**
`shared/fleet/model_profiles.py:201-212` builds
`<think>.*?</think>|<tool_call>.*?</tool_call>`. If the prompt opened the block,
the generation contains only the orphan `</think>` and the regex matches
nothing:

```
'<think>\nx\n</think>\n\nYes.'  ->  'Yes.'        (matched pair, stripped)
'hmm\n</think>\n\nYes.'         ->  unchanged     (orphan, survives)
```

**The corollary that bites hardest in an eval:** a `no_think_tags` rubric check
passing is **not** evidence that thinking was suppressed. A model that reasons
in a *well-formed* block has that block stripped before scoring and passes
silently. The only honest witness is the FIRST GENERATED TOKEN — read it from a
streamer callback (`VLMDecodedResults` exposes no raw ids), and prove the
witness first by asserting `encode("<think>") == [248068]` and
`decode([248068]) == "<think>"`, else report the check unmeasurable.

---

## `ruff check --fix` deletes imports used only in annotations

Under `from __future__ import annotations` every annotation is a string at
runtime, so `F401` cannot see a module that appears **only** in one. Ruff's
autofix deletes the import and the file still imports, runs and passes its
tests — the breakage surfaces only at `typing.get_type_hints()`, or in the next
ruff run as `F821 Undefined name`.

Hit on 2026-09-22 in `evals/suites/answer_quality.py`: `import re` was used
solely in `def _production_tool_call_pattern() -> re.Pattern[str]`. The fix
removed it silently and the whole eval harness still ran green.

```
# ruff --fix removes `import re`; nothing fails until:
typing.get_type_hints(_production_tool_call_pattern)   # NameError: re
```

**Always re-run `ruff check` after `ruff check --fix` and read the NEW errors,**
not just the count. An `F821` that appears after a fix is the fix's own damage.
Grep the diff for removed imports before staging: `git diff -U0 <paths> | grep
-E '^-(import |from )'`.

## What the git-rules guard refuses in a Bash/PowerShell call (2026-10-07)

Four shapes, each hit while landing #1616 and #1699; none is a fault in the guard.

- `git commit` with arguments while the checkout is on `main`: refused. Work on a feature
  branch and land it with a `--no-ff` merge.
- `git add` and `git commit` in ONE call: refused. Two calls.
- A shell variable anywhere in a command line that builds a git command (`$V`, `$D`,
  `"$(...)"`): refused as "unresolved variable". Write literal paths; this also catches a
  non-git line that merely shares a call with a git command.
- `git merge -F -` (message from stdin): not supported. Write the message to a file and use
  `-F <file>`.

Also: a Windows checkout stores these files CRLF, so a Python `read`/`replace` that matches
`"
"` finds nothing; match bytes with `
` or edit through the Edit tool.

## Editing and publishing gotchas from the #1699 arc (2026-10-07)

- **The Bash tool collapses a doubled backslash inside a heredoc.** Python source written as a backslash-backslash-n
  escape arrived with one backslash, so it became a real line break inside a string literal and the file stopped
  parsing. Four edits broke this way. Write the file with the Write tool, or build the character with `chr(92)`, then run it.
- **A Windows working copy is CRLF while the index is LF.** Reading a file in text mode and writing it back with
  `\r\n` made a one-paragraph change show as 1460 insertions and 1442 deletions. Replace `\r\n` with `\n` on read and
  write LF; check `git diff --stat` before staging.
- **The git-rules guard also refuses** `git add -u`, `git add $VAR`, and any shell variable in a call that builds a
  git command. Use literal paths.
- **`scripts/hf_publish.py` takes derived tables only**: `.json .jsonl .csv .md .txt`, CSV columns from a fixed list
  (`KNOWN_CSV_COLUMNS`), id cells of at most 48 characters of `[A-Za-z0-9_.:@/+()-]`, no raw logs, no gzip, no local
  user name. Build a publishable copy (`scripts/build_gate_runtime_dataset.py` is the pattern) instead of editing the
  data. `plan` guesses the first CSV for the card's `data_files`; pass `--data-file` to `plan` (the `upload`
  subcommand has no such option), and fetch the live card read-only with `hf download ... README.md` before editing it.
- **A process scan on this box takes about 7 s** (380 processes, command lines read one by one): never put one in a
  per-sample loop.
