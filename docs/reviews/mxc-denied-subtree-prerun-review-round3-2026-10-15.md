# MXC denied-subtree probe: pre-run adversarial review, round 3 (2026-10-15)

Target: branch `feat/mxc-denied-subtree`, commit `42fd5f1c` (round-2 fixes on `4abd6442`), `tools/probes/mxc_denied_subtree/` (7 files), working tree clean against the commit. Spec: the CASE_2 mxc-denied-subtree file of 2026-10-15 (read only). MXC source read: main `525d0f25` and v1.0.0 under the spike work directory; both shipped `wxc-exec.exe` binaries string-scanned.

**VERDICT: PASS (no BLOCKER or HIGH). Approval file written** (`%USERPROFILE%\blarai-research-data\mxc-denied-subtree\APPROVED_SHA256.txt`, seven lines, hashes taken with certutil under the non-elevated runner at 2026-10-15T20:08:41Z; `launch.ps1 -CheckOnly` under the same runner: `hash check passed for 7 scripts`, exit 0).

One condition travels with the approval (finding 1): until it is fixed, a FAIL whose record has a non-empty `judge.read_errors` or a `sub` listing error is to be read as INSTRUMENT-BLIND by hand, not routed.

## What was run, at 42fd5f1c

- `self_test.py` through `run_nonelevated.ps1` (whoami: Medium Mandatory Level; Administrators and S-1-5-114 deny-only): **123 passed, 0 failed**, exit 0. Token line: `guarded privileges enabled before secure_token []; after []`.
- `run_probe.py --dry-only --s5 --runs 1` with the real v1.0.0 and main launchers, non-elevated: S0 base-container on both, `fs_deny_advertised true`; fx-a dry-run tier base-container; `S5 not applicable on Tier 1`; token outcome all four guarded privileges `absent`; MXC state start equals end; tree removed; `C:\mxc-fx` absent afterwards.
- Reviewer fixtures (non-elevated runner): `attack3.py` (struct layout, read-error handling, layout check, directory time, privilege-skip verdict, code-5 rule, attribute and time comparison, ACE parser on real objects, security-suite record); `e2e3.py` driving the real `run_probe.main` with `fake3.cmd` in modes `landnoreport` (the round-2 reproduction) and `lockafter` (new: a held tree, then a third-party handle without read sharing on `sub\marker.txt` at the after-snapshot).
- Package-shadow check on a scratch copy of the directory (reviewer's own shell, elevated Git Bash; an import involves no privilege).
- No container launched, no listener, no firewall change.

## Round-2 findings

| R2 | Severity | Status at 42fd5f1c | Evidence |
|----|----------|--------------------|----------|
| 1 | HIGH | FIXED (code); demonstrated only by reading in the elevated contexts | `_TokenPrivileges` is size 16, LUID at 4, Attributes at 12 (measured). `secure_token` disables, reads back with `GetTokenInformation`, refuses if any of backup, restore, take-ownership or security stays enabled; header and every launch record the list; a launch is skipped with a STOP when any is enabled. In the binding (non-elevated) context the four privileges are absent, so the removal, the old-layout toggle and the refusal check are not exercised there (finding 5). Container inheritance: see "secure_token and MXC's child" below. |
| 2 | HIGH | FIXED | Real `run_probe` with `fake3.cmd landnoreport`: `STOP: FAIL condition met (T/sub changed: [...6 paths]; container report absent)`, `VERDICT: FAIL`, summary change tagged `no report`, tree kept. |
| 3 | MEDIUM | PARTLY FIXED | Blind HOLD closed: no unreadable entry or unlistable sub produced a HOLD in any fixture (`layout_ok` and `read_errors` block it). False FAIL still open through the attribution predicates and through directory-listing failures (finding 1). The self-test lock for it checks `sub_changes` only. |
| 4 | LOW | FIXED | HOLD needs Win32 error 5 on every refused attempt; codes 2, 3, 32 and 1920 on every attempt each give INSTRUMENT-BLIND. Spec-deviation note in finding 6. |
| 5 | LOW | FIXED for bytecode; one sibling open | `__pycache__` or any `.pyc` refused by both `launch.ps1` and `run_probe.py`; Python started `-I -B -X pycache_prefix=<fresh>`. A package directory shadowing a module is outside the binding (finding 4). |
| 6 | LOW | FIXED for attributes and file times; per-entry ACL residual | Read-only and hidden attributes and a file last-write change are each caught; the archive bit is deliberately masked. A DENY ACE added to `sub\marker.txt` gives `sub_changes []` and is not in the NOT MEASURED list (finding 7). |
| 7 | LOW | FIXED; same class re-introduced for privileges | Real `run_probe` with a tier-mismatch dry-run gives `TIER-MISMATCH` with both tiers and the reason (self-test e2e). A privilege-skip record gives INCOMPLETE (finding 3). |
| 8 | LOW | FIXED, with one reversed bound | Conditional and callback ACEs make `parse_ok` false and `same_acl` refuse; real DACLs of `C:\`, the toolchain and the launcher folder parse (`A` only). AppContainer registry check scoped to keys whose name or contents carry the container id (MXC's Tier 2/3 profile name is the container id, `appcontainer_runner.rs`). System tools by absolute path. Append now opens `FILE_APPEND_DATA` only, so `FILE_WRITE_DATA` is no longer attempted (finding 7). |
| 10 | LOW | FIXED in form, values absent | Security Center products are recorded, but both versions are `null` and one entry is a stale registration (finding 8). |

## New findings

### 1. MEDIUM: a host-side read or listing failure still yields FAIL; the STOP line contradicts itself
- **Where:** `landing.py:174-188` (`landings`, `open_write_append` compares `sha256` and an unreadable entry carries `None`), `landing.py:92-98` (a failed directory listing drops every child from the snapshot), `landing.py:148-153` (`_differs` treats an absent child as a change), `run_probe.py:268-270` (FAIL decided before `read_errors`), `summarise.py:58-61`.
- **What is wrong:** the docstring says "an unreadable entry is never a change by itself"; that holds for `sub_changes` but not for the attribution predicates, which feed `landed_count`, which alone decides FAIL; and an unlistable `sub` (after-snapshot only, or before-snapshot only) makes its files vanish or appear.
- **Reproduced (real `run_probe`, non-elevated, `fake3.cmd lockafter`):**
  ```
  STOP: FAIL condition met (T/sub changed: []; container report present)
  VERDICT: FAIL
  launch-fx-a-r1.json | sub_changes [] | landed ['open_write_append'] | read_errors ['sub/marker.txt']
  SUMMARY FAIL [['fx-a-r1', ['open_write_append'], [], 'report']]
  ```
  Listing failure on the after-snapshot only (`attack3.py`): `sub_changes ['sub/delete_me.txt', 'sub/marker.txt', 'sub/rename_me.txt']`, landed `{'delete'}`, VERDICT FAIL, nothing written.
- **Lock that over-certifies:** `self_test.py:244` "exclusive handle: not counted as a change" asserts `sub_changes == []`; the verdict path goes through `landings`, which the lock never calls.
- **Cost:** a held run stops with FAIL and enters the private route; the record carries the read error, so a reader can catch it. Never a false HOLD.
- **Incidence:** 0 banked. Needs a handle without read sharing on a `sub` file, or a listing failure, during the after-snapshot. The active product is Defender.

### 2. LOW: the directory last-write time was dropped on a false premise; a transient landing is visible only there
- **Where:** `landing.py:4-5, 107`.
- **What is wrong:** the docstring says a directory's stamp "is updated lazily by NTFS". Measured on this volume: reading every file, listing `sub`, the payload's five refused attempts and an ACL reset each left `sub`'s last-write time unchanged; a file created and deleted inside `sub` changed it, and `sub_changes` was `[]`.
- **Answer to the brief's question:** yes, a create-then-delete (or a rename and back) is visible only as the directory time. With this payload it cannot reach HOLD: the report's `ok: true` makes a disagreement (INSTRUMENT-BLIND), and with no report the run is LAUNCH-FAILED. It loses evidence; it does not certify a false HOLD.

### 3. LOW: a per-launch privilege refusal is summarised as INCOMPLETE; the docstring and the lock say INSTRUMENT-BLIND
- **Where:** `run_probe.py:218-220` (launch skipped, `launched` false), `summarise.py:81-82` (privilege check only over completed launches), `summarise.py:17` (docstring), `self_test.py:130` (lock built from a completed-launch record, a shape `run_probe` never writes).
- **Reproduced:** the record as `run_probe` writes it plus S4: `VERDICT INCOMPLETE blind []`. The console STOP line is correct; `summary.json` gives no reason.

### 4. LOW: a package directory shadows a hashed module and passes the hash binding
- **Where:** `launch.ps1:38-46` (hashes top-level `.py`/`.ps1` only; refuses only `.pyc`/`__pycache__`), `run_probe.py:318-321`.
- **Reproduced (scratch copy):** `landing/__init__.py` that loads `landing.py` and overrides `sub_changes` and `landings`: `launch.ps1 -CheckOnly` prints `hash check passed for 7 scripts`, exit 0; `import landing` loads `landing\__init__.py`; a real landing gives `sub_changes [] landed_count 0`. Same for any extension module (`.pyd`), which the import system prefers to a `.py`. Needs deliberate tampering. Fix direction: refuse any entry in the directory that is not one of the approved files.

### 5. LOW: the token locks pass vacuously in the binding context
- **Where:** `self_test.py:369-376`.
- Under the non-elevated runner the guarded privileges are absent; "secure_token refuses when the disable did nothing" compares the value with itself, and the old-layout toggle is skipped. The binding self-test therefore cannot show the privilege control works; that rests on round 2's elevated fixture and on reading. No builder claim for elevated Git Bash or elevated PowerShell was found on disk (the commit message and the self-test docstring make none). Reading the handling: in elevated PowerShell the privileges are held and disabled, `secure_token` returns `disabled` for each, the test child enables backup and restore, the old layout leaves them enabled (toggle exercised), the patched no-op disable is refused, the real one clears them. In elevated Git Bash they start enabled and the same path runs. That reading is consistent; it was not run.

### 6. LOW: the code-5 rule is stricter than the spec
- **Where:** `summarise.py:107-110`.
- The spec's HOLD is "S2 refused 5 of 5 attempts". The harness also requires error 5. MXC's documents say only that denied paths "cannot access at all" (`docs/schema.md`); what error a Tier 1 native deny returns is not documented. If it returns 2 or 3, a run that held reads INSTRUMENT-BLIND; the codes are in `summary.json`, so it is recoverable by reading, never a false HOLD.

### 7. LOW: two bounds missing from the NOT MEASURED list and one stale sentence
- Per-entry ACL changes inside `sub` are not compared (a DENY ACE on `sub\marker.txt`: `sub_changes []`); change time and the archive bit are not compared by design. Not in `run_probe.py`'s NOT MEASURED list.
- The append attempt opens `FILE_APPEND_DATA` only; `FILE_WRITE_DATA` is not attempted. `run_probe.py:5` still says "open marker.txt for write and append". For the register row: say the append was an append-only open.

### 8. LOW: the security-suite record holds no version and a stale product
- `security_suite()` on this host: `Windows Defender` (version `null`, path `windowsdefender://`) and `McAfee` (version `null`, path under `C:\Program Files\McAfee\wps\...`, which does not exist). A Bitdefender process (`bdredline.exe`) is running and is not in the list (it is in `machine_conditions` by process name). The register row needs the product and version written by hand (for Defender, from `Get-MpComputerStatus`).

## secure_token and MXC's child (the brief's question)

- **What the source says:** the Tier 1 runner starts the payload with `CreateProcessW` plus `PROC_THREAD_ATTRIBUTE_SECURITY_ENVIRONMENT` and no token argument (`base_container_runner.rs:962`), so the container process's token is derived by the OS from `wxc-exec`'s primary token, which `CreateProcess` copies from the harness with the privileges in the state `secure_token` left (disabled). The SDK calls `AdjustTokenPrivileges` only in `wxc_host_prep` (not run). Neither shipped `wxc-exec.exe` contains `AdjustTokenPrivileges`, `SeBackupPrivilege` or `SeRestorePrivilege` (string scan: 0 and 0 for v1.0.0 and main). The test seams `MXC_FORCE_DENY_PATHS`, `MXC_FORCE_TIER`, `MXC_FORCE_BC_USABLE` are `cfg(test)`-only and absent from both binaries.
- **What the docs say:** nothing about the container token's privileges.
- **Not known (hypothesis):** whether the PSEC derivation keeps the privileges (disabled) or strips them. Either way they are not enabled in the container unless something enables them; the payload never does and MXC does not. The harness disables rather than removes (`SE_PRIVILEGE_REMOVED`), so a process in the chain could re-enable them; none does.

## Attacked and could not break

- **No HOLD from an unreadable or blind host:** exclusive handle, unlistable `sub` (before, after, both), failed stream reads: each gives FAIL or INSTRUMENT-BLIND, never HOLD.
- **Judge on every launched record:** a landing with no report is FAIL with the tree kept; a launch that returns early and lets the payload write after the after-snapshot gives a disagreement (INSTRUMENT-BLIND) or LAUNCH-FAILED, not HOLD, because the report is written after the S2 calls return.
- **Attribute and time comparison:** read-only, hidden and last-write changes on a file are caught; the archive bit and change time are not compared, so a benign scan or an ACL capture cannot false-FAIL through them.
- **ACE parser:** conditional (`XA`), callback (`ZA`) and audit-type text are refused; a null DACL parses as empty and still differs from a real one.
- **Registry scoping:** a key naming the container counts; an unrelated AppContainer key does not; `ProcessSandboxes` is still compared whole.
- **Bytecode:** `__pycache__` or `.pyc` anywhere in the directory refused by both entry points; the payload runs as a script, which Python never loads from a cache.
- **Tier handling, REFUSED vs LAUNCH-FAILED, state directory, S5 on Tier 1:** as in round 2, re-run in the self-test e2e.

## Merge read

No blocker for the live run. Finding 1 costs a stopped run and a confusing FAIL, never a false HOLD, and the condition above neutralises it until fixed; it should be fixed before any FAIL from this probe is reported, and the lock at `self_test.py:244` should be made to go through `judge` and `verdict`. Findings 2 to 8 are bounds and record-quality items for the register row.

Suites run by the reviewer at `42fd5f1c`, all under `run_nonelevated.ps1` (Medium integrity): `self_test.py` (123/0); `run_probe.py --dry-only --s5 --runs 1` with the real launchers; `attack3.py`; `e2e3.py` with `fake3.cmd` (`landnoreport`, `lockafter`); certutil hashes; `launch.ps1 -CheckOnly`. The package-shadow check and the MXC source and binary reads ran in the reviewer's own shell, which is elevated Git Bash; the shadow check is an import on a scratch copy and involves no privilege. No harness code path was judged from an elevated run. No container launched.
