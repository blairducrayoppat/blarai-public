# Arm 3 design note: a persistent filter set, its rollback, and fail-closed on absence

Written before the scripts; revised on 2026-10-11 after the arm 3a run and an independent safety review (sections 2, 4 and 7 state what changed; statements the review showed to be false were replaced, not kept). Subject: the throwaway spike account only (never the real `blarai-coder` account, whose
`containment=off` state this arm does not touch). Machine-wide state is involved, so this note states the failure modes
and the order of defences before anything is built. Question (brief section 5): can the filter set be made to survive a
restart, and can its absence be detected before the account is allowed to run?

## 1. What is added

One Windows Filtering Platform (WFP) provider, one sublayer, and two BLOCK filters at `ALE_AUTH_CONNECT_V4` and
`ALE_AUTH_CONNECT_V6`, each filter carrying the `ALE_USER_ID` condition for the spike account's SID (a per-SID security
descriptor, as in arms 1 and 2). All four objects carry the persistent flag (`0x1` in `FWPM_PROVIDER_FLAG_PERSISTENT`,
`FWPM_SUBLAYER_FLAG_PERSISTENT`, `FWPM_FILTER_FLAG_PERSISTENT`) and are added in a NON-dynamic session
(`FWPM_SESSION0.flags = 0`) in one transaction. There is no loopback permit filter in this set: the question is whether
the block persists, not whether loopback works (arm 1 answered that).

| Object | Fixed key | Name carries |
|---|---|---|
| provider | `7e1f6a10-5c0b-4d8e-9a31-2b6d4c8e3f01` | `BlarAI #1682 persist spike provider` |
| sublayer (weight `0xFFFF`) | `7e1f6a10-5c0b-4d8e-9a31-2b6d4c8e3f02` | `BlarAI #1682 persist spike sublayer` |
| filter V4 (block, weight `0x1000`) | `f1300003-0000-4d8e-9a31-2b6d4c8e3f21` | `BlarAI #1682 persist spike: block-account-v4` |
| filter V6 (block, weight `0x1000`) | `f1300004-0000-4d8e-9a31-2b6d4c8e3f22` | `BlarAI #1682 persist spike: block-account-v6` |

Every key is fixed in the source and generated once for this spike; none is generated at run time, because removal is BY
KEY and must work with no memory of the run that added them. The keys differ from the dynamic set of arms 1 and 2
(`7e1f6a10-...-1f01`, `f1100003-...`), so the two cannot be confused. The boot-time variant (`FWPM_FILTER_FLAG_BOOTTIME`)
is NOT used: it protects the window before the Base Filtering Engine (BFE) starts, and the thing being filtered is an
account that cannot hold a token until after logon, which is after BFE is up. Adding it would widen the blast radius
(it is the form that can lock a machine out of its network at boot) for no gain in the question asked.

## 2. The dead-man does not exist, so the rollback is the safety

Arms 1 and 2 relied on the dynamic session: closing the engine handle, or the process dying, removed everything, and a
timer thread closed the handle after `hold + 30` seconds. Persistent objects have none of that. The defences, in the order
they act:

1. **Rollback by key, tested first.** `Remove-FenceSet` deletes filters, then the sublayer, then the provider, each by its
   fixed key, each in its own call (not one transaction, so one failure cannot undo the others). "Not found" counts as
   success. Every key is attempted whatever happened to the one before. The verdict is the state read back afterwards:
   removal is verified only when all four objects read ABSENT. It works for a whole set, a half-added set, and an empty
   one. The same logic is exposed as `spike-wfp-persist.ps1 -Remove`.
2. **The add path is unreachable until the rollback has been self-tested.** `Add-FenceSet` is the only function that adds,
   and it demands a proof token that only `Test-RollbackProof` produces from a result file. That file is written by
   `-SelfTest -WriteProof` only when every rollback check passed (a half-failed add, a failing delete, an unreadable
   engine, a stale object, a forged proof) AND every sibling script's own self-test passed, and it records the SHA-256 of
   each script of the code set (LF-normalised) AND of the wrapped #1671 script (the code that builds the security
   descriptor), plus the evidence a real run leaves (checks run and passed, each sibling's result). A proof without that
   evidence, or with a changed script or wrapped script, or older than 24 hours, makes the add refuse. The proof file sits
   beside the scripts, in the admin-only folder (item 7). There is no standalone `-Add` mode; the two add paths are `-Arm3a`
   and the 3b arming script.
3. **Removal on every exit path of the run.** `-Arm3a` removes by key in its normal flow, again in a `finally` block, and
   its wrapper task runs `-Remove` once more as a follow-up whatever the run did.
4. **An optional SYSTEM dead-man task for arm 3a** (`-DeadManTask`, default OFF; `blarai-arm3a-deadman`, fires
   `-DeadManMinutes` after the add, runs only `-Remove` with the hash of the wrapped script pinned, unregisters itself after a
   verified removal). It is off by default because registering a SYSTEM task is a separate grant and a privilege-escalation
   surface (item 7); the 2026-10-11 3a run used the per-run elevated task only. With it off, the rollback in force is items
   1 to 3.
5. **The operator watchdog** is unchanged from arms 1 and 2 (an operator connect every 2 s; two failures in a row abort),
   except that an abort now removes by key instead of closing a handle. Its coverage is narrower than the arms 1 and 2 text
   suggested: in 3a it ticks between steps and not during an export (`netsh wfp show filters` can take up to 120 s); in 3b
   there is NO operator watchdog after the add (the thing watched there is the operator's input).
7. **SYSTEM and elevated tasks run scripts from an admin-only folder.** `Start-ElevatedOnce.ps1` (the per-run elevated task),
   the 3a dead-man and the two 3b SYSTEM tasks all execute scripts from the folder they were started from; if a non-elevated
   process of the operator can write there, it can run code elevated. Each refuses to register or run unless
   `Test-AdminOnlyFolder` finds that only SYSTEM, Administrators and TrustedInstaller can write to the folder, to the files in it
   and to nothing above it that lets the folder be replaced. The SYSTEM tasks also pin the SHA-256 of the wrapped script taken
   at arming and refuse any other file BEFORE its text becomes code; if it cannot be used at all, removal falls back to the
   self-contained snippet (item 6), which depends on nothing else.
   Check-then-use gaps are closed the same way everywhere: a library is read ONCE and the hash recorded for the proof and the code-set id is the hash of
   the bytes that ran (`Get-VerifiedLibBlock`); the wrapped script is read once, hashed, parsed and evaluated from those same bytes, and the proof is compared with
   that hash, not with a second read of the path; the SYSTEM tasks carry the code-set id taken at arming and refuse to run on any other code set (falling back to
   the self-contained snippet). Anything an elevated or SYSTEM process writes goes through a guard that refuses a file, folder or ancestor that is a junction or
   symlink, or a hard-linked file; the 3b arming script and the optional dead-man additionally require the output/state folder to be admin-only, and the proof
   is trusted only from the script folder or another admin-only folder. What cannot be closed from inside a script: the entry script itself is read by
   PowerShell before it can hash itself, so its integrity rests on the admin-only folder rule plus the code-set id, which includes it, checked at task start.
6. **Manual rollback** that needs no other file: a self-contained PowerShell snippet (in the README, printed by `-DryRun`,
   and compile-checked by `-SelfTest` under another type name) that deletes the four keys. `netsh wfp` can show filters but
   has no delete verb, so `netsh wfp show filters file=check.xml` plus a search for `BlarAI #1682` is the CHECK, not the removal.

## 3. Fail-closed on absence

`Get-FenceState` reads the four objects by key and returns ABSENT, PRESENT (all four), PARTIAL (some), or UNKNOWN (the engine
could not be queried: BFE down, not elevated, an unexpected status). `Test-FenceAllowsAccount` allows the account to run
only for PRESENT. `Invoke-GuardedProbe` calls it before it starts the account's task and, when it refuses, returns
`fence_absent_not_started` without starting anything. What it does not check: the filter CONDITIONS are not read back, so a
key reused with different content would read PRESENT; and "the account may run" is a decision in these scripts, not a
control inside Windows (nothing stops the account's task being started some other way). The claim is therefore narrow:
the check detects that the fence objects are missing and refuses, in the places these scripts start the account.

## 4. Arm 3a (no restart) and arm 3b (restart)

**3a** (`spike-wfp-persist.ps1 -Arm3a`): preflight (proof, SID safety, fence ABSENT) -> gate on the empty fence must refuse
-> baselines -> optional dead-man task (`-DeadManTask`) -> add -> read back PRESENT and persistent -> the account's probe through the gate (must be
blocked) -> short dwell with the watchdog -> export -> remove by key -> read back ABSENT -> gate must refuse and start
nothing -> the account's probe unguarded (egress must be open again) -> report. Evidence for C11 (absence detected), and a
persistent-add/remove cycle with no restart.

**3b** is two scripts and a watchdog:

* `spike-arm3b-arm.ps1 -Live` refuses unless the script folder is admin-only and the machine has been idle 30 minutes
  (`GetLastInputInfo`, in the operator's own session), then shows a toast and a window for a 10-minute countdown during which
  any input aborts (nothing is added until it ends), then registers the SYSTEM startup task `blarai-arm3b-post-reboot` and
  the SYSTEM veto task `blarai-arm3b-veto` FIRST, then adds the set, then runs `shutdown /r /t 600 /c "arm 3b"`. **That
  restart is forced:** `shutdown /?` on this machine says a timeout above 0 implies `/f`, so applications are closed without
  forewarning when the ten minutes end; leaving `/f` out of the arguments changes nothing. The idle gate and the input watch
  are therefore the only protection for unsaved work, and a forced restart of the operator's machine is the Lead Architect's
  decision to accept or refuse (see section 7). One input baseline (the tick read at the idle gate) runs through the
  countdown and the pending-restart watch. Input before the restart runs `shutdown /a`, removes the set by key and deletes
  both tasks.
* `spike-arm3b-post-reboot.ps1 -Live` runs once at startup as SYSTEM: reads the fence state by key (C10: PRESENT and
  persistent after a CONFIRMED restart, meaning the boot time is later than the arm time), waits for the network, probes the
  account through the gate (must be blocked), exports the filters, removes by key, verifies, probes unguarded (egress must be
  open), checks the gate now refuses (C11), writes `post-reboot-result.json`, deletes its tasks. If the removal cannot be
  verified it keeps its own task for a bounded number of further startups (3 attempts, and not past 24 hours after arming), then
  deletes it and says a manual rollback is required. Removal is verified by the engine reading ABSENT; the network is
  needed for the probes only, so a down network is reported as such and never as "did not survive", and a repeat attempt
  or an arm state with no recorded add is reported as inconclusive, never as survival or failure to survive.
* `spike-arm3b-veto.ps1 -Live` fires 30 minutes after arming. No restart: `shutdown /a`, remove by key, delete the startup
  task, record "reboot vetoed". Restarted and the post-reboot task still running: leave it alone. Restarted and a set is left
  with nothing running: remove it (safety net).

The Lead Architect authorised unattended runs of 3a and 3b on 2026-10-11, scoped to WFP objects keyed to the spike SID. 3a
ran that day; 3b was NOT run on that day (section 7; it ran on 2026-10-12, claims row C10). The idle and countdown gates exist because the restart is the one step that can
cost the operator unsaved work: they make "away" a measured fact, but they do not make the restart gentle.

## 5. Failure modes and what answers each

| Failure | Answer |
|---|---|
| Rollback logic wrong | Tested first against a fake engine, including a half-failed add and a failing delete; the proof binds the tested bytes. |
| Add succeeds, process dies | Dead-man task (3a) / veto and post-reboot tasks (3b) run `-Remove` by key; the manual snippet is the last resort. |
| Add half-fails | `Add-FenceSet` removes by key and reports not added; also covered for an add that "succeeds" without the persistent flag. |
| Stale objects from an earlier run | The add refuses (state is not ABSENT) and says to run `-Remove`; nothing is added over them. |
| Engine unreadable | State UNKNOWN: the gate refuses, the add refuses, `-Check` exits 22. |
| Block hits the operator | Not possible by construction (SID safety refuses the operator's SID or any group in his token, exit 3), and the watchdog aborts and removes after two failed connects. |
| Restart happens while he is back | Input aborts the countdown; input while the restart is pending cancels it; the veto task covers a restart that never comes. |
| Restart never happens | The veto task cancels any pending restart, removes by key, deletes the startup task. |
| Post-reboot script cannot remove | It keeps its task for up to 3 attempts and 24 hours, then deletes it and records that a manual rollback is required; manual rollback documented. |
| The check passes without a restart | The result is inconclusive (exit 4) unless the boot time is later than the arm time. |

## 6. What this arm cannot show

One suite, one driver, one account, one restart; nothing about fast startup, hibernation, a Windows feature update, a
BFE crash, or another suite's sublayer winning after boot; IPv6/UDP/DNS untested as in arms 1 and 2; the gate is a decision
inside these scripts. Claims rows C10 and C11 are written from the result files, with CONTRADICTED or NOT ESTABLISHED if
that is what the data shows.

## 7. The 2026-10-11 review, and what 3b still needs

Arms 2 and 3a ran live on 2026-10-11 (results: claims C9, C10a and C11 in `docs/research/account-level-containment-evidence-2026-10-05.md`).
An independent safety review of the scripts found eleven problems; each has a disposition in
`docs/reviews/trackb-arms23-safety-review-disposition-2026-10-11.md`. The ones that decide whether 3b may run:

1. The restart is forced (above). **Needs the Lead Architect's decision**: accept a forced restart of this machine with ten minutes' warning,
   or choose another way to restart that does not close applications (none is built).
2. The window between the add and the registration of the cleanup tasks is closed: the tasks are registered first and an interrupted arming is
   recognisable (no add recorded).
3. SYSTEM and elevated tasks run only from an admin-only folder, and the wrapped script is pinned (item 7 of section 2).
4. The post-reboot result no longer depends on the network, is bounded in attempts and time, and tells a down network from a set that did not survive.
5. The proof covers the wrapped script and requires the evidence of a real self-test run.
6. Every automatic removal path has the self-contained fallback.

What was not changed as of the 2026-10-11 review (arm 3b has since run once, on 2026-10-12, claims row C10): the live 3b flow had never run, the toast and window cannot be shown to have been seen, and no part of 3b has been
exercised against the real task scheduler or a real restart.

## 2026-10-11, second review: what changed

The wrapped #1671 script was evaluated before any hash or proof check and its default path was user-writable (code execution as the operator when elevated, reproduced by the reviewer). The gate now runs before the read-as-code; the default is the copy beside the scripts. The admin-only check also fails on non-administrator owners, ancestors that grant delete or change-permissions rights, and links. The proof refuses implausible check counts, recorded failed checks and a non-admin proof folder. The Lead Architect's decision on the forced 3b restart (section 7) is enforced by `arm3b-restart-decision.json`. Arm 3a itself ran the earlier scripts; `runs/AS_RUN.md` records which.
