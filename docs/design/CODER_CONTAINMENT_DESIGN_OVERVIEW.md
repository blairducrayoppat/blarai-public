---
title: Coder Containment - Design Overview
status: living
area: security
as_of: 2026-10-09
---

# Coder Containment - Design Overview

How BlarAI keeps its AI coding agent (the "coder") inside a restricted Windows account, what that does and does not
protect, how each threat is handled, and how the switch-over is verified.

**Audience.** Engineers, security reviewers and governance reviewers who have not seen this project before. The document is
meant to be read cold. Terms are explained on first use and again in the glossary (section 15).

**As-of statement.** Facts are as of 2026-10-09. The authoritative status of the switch is the `containment` key in the
agentic-setup file `configs/fleet-driver.json`; on 2026-10-09 it reads `off` (agentic-setup `main` at `373f63f`). This document
is a description of a design, not a statement that the design is running.

**How the claims are anchored.** Each factual claim cites a file, a function name, a decision record (ADR), a ticket comment
(written `#775 c.3971`, meaning comment 3971 on ticket 775 in the Vikunja task tracker) or a commit. "AS:" means a path in the
agentic-setup repository (`C:/Users/mrbla/agentic-setup`), which holds the fleet scripts and is not part of this repository.
Where a claim is derived rather than read, it says "derived". Where code and documents disagree, section 14 lists the
disagreement; the document does not choose silently. Test and suite figures are copied from ticket comments written by the
people who ran them; the author of this document did not re-run any suite or check.

---

## 1. Summary

BlarAI is a personal, locally run AI system. One part of it, the "dispatch fleet", lets an AI coding model write and test code
inside a software project with no person typing. That model's output is code, and code can do anything the account that runs
it can do. Without containment the coder runs as the operator's own Windows account: it can read the operator's private keys
and databases, and it can open network connections (`PHASE1_DISPATCH_THREAT_MODEL.md` section 3).

Coder containment moves only the coder step to a second, deliberately powerless Windows account named `blarai-coder`. Windows
itself, not the coder's own program, then enforces what that account can read and write. The operator account keeps everything
else: the quality gate (build, tests, secret scan), all `git` commits and merges, and the decision to merge.

Status in one table:

| Part | State on 2026-10-09 |
|---|---|
| The `blarai-coder` account, its secret-file denial, the scheduled task that runs it | Built and applied in July 2026 (`#775 c.1654`, `c.3879`) |
| The fused coder leg (code that routes one dispatch through that account) | Built and merged; flag `off` (AS `d026f5c`, `39dc7e9`, `3097116`) |
| The permission-narrowing stage (read-only on source repositories, closed fleet folder, protected model folders) | Built and merged; NOT applied to the machine (`#1678 c.3908`; `#775 c.3971`) |
| The coder's own tool settings stage (own opencode configuration, read grants) | Built and merged; NOT applied (AS `934f273`; `#775 c.3967`) |
| Removal of the vulnerable `NginxGateway` service and its boot items | Done on the machine, 2026-10-09 (`#1695 c.3970`) |
| Check 25 (detects coder-writable boot items) | Built and merged; runs only inside `verify-coder-containment.ps1`. Extension to ordinary boot programs' working folders DECIDED by the Lead Architect, NOT yet built or merged (`#775 c.3972`; agentic-setup branch `feat/1695-boot-surface-working-folder`, no commits beyond `main` `373f63f` when read) |
| Network egress block for the coder account | NOT built as a persistent control. Gap accepted by the Lead Architect (`#775 c.1653`, `c.3901`) |
| Third, inference-only account `blarai-model` | Proposed only. Feasibility shown once on one machine. Not decided, not built (section 4) |
| The switch itself (`containment = restricted_account`) | NOT flipped. A ceremony with the Lead Architect present (section 12) |
| The first complete dispatch running through the coder account | Has never run (section 13) |

---

## 2. Purpose and the threat it answers

**The threat.** A coding model reads untrusted text (a task description, files in a repository, packages it installs) and then
runs commands and code. If its instructions are subverted, or if the code it writes or fetches is hostile, that code runs with
the rights of whoever launched it. The threat model names the chain: attacker-influenced content, then code execution, then
reading secrets, then sending them out (`docs/security/post_capstone_2026-07/PHASE1_DISPATCH_THREAT_MODEL.md` sections 3, 4 and
5.1; the "s1ngularity" pattern it cites is a supply-chain attack that stole local secrets through a build step).

**What containment is.** An operating-system boundary around the coder: a separate Windows identity (a security identifier,
SID) that is not granted rights to the operator's secrets and has write rights only where the design grants them. A rule
enforced by Windows binds every process the coder starts, including child processes of build tools, which the coder program's
own permission system cannot see (threat model section 2, boundary B5).

**What it is not.**
- Not a defence against the model being talked into producing wrong or malicious code. It limits the damage that code can do.
  The review, the build, the tests and the secret scan before merge remain the controls on code quality (threat model sections 4
  and 6, boundary B7).
- Not a kernel or virtual-machine boundary. A Windows privilege-escalation exploit escapes a limited account (threat model
  section 5.2; ADR-045 Decision 1).
- Not per-action governance. It binds what runs inside the account (ADR-045 Decision 5).

**Why a separate account rather than a rule on the program.** The project's earlier study found that protections a third
party can reach on Windows are cooperative: a flag skips them, a crash can open them (ADR-042 context, quoted in
`docs/DECISION_REGISTER.md`, 2026-09-20 row). Account-level controls (file permissions, kernel network filters) are enforced by
the operating system. ADR-045 Decision 5 records this as new evidence on one dimension only, on one machine.

---

## 3. Actors and accounts

| Actor | What it is | Rights it holds | Evidence |
|---|---|---|---|
| Operator account | The Lead Architect's own Windows user, which also runs the assistant, the launcher and the dispatch orchestration. Its profile folder is `C:\Users\mrbla` (derived from paths used throughout the scripts). | Everything the operator owns: source repositories, secrets, models, state, `git` | `PHASE1_DISPATCH_THREAT_MODEL.md` section 3 |
| `blarai-coder` | A local Windows standard account, member of Users only. Runs the coder step through a scheduled task. Password is generated in memory and never written to disk in plaintext; the Task Scheduler registration vaults it in Windows LSA secrets (an encrypted store, itself on disk). | After the narrowing stage is applied: modify on its worktree base `C:\blarai-fleet\worktrees` and the job folders `C:\blarai-fleet\coder-leg`; read-and-run on the source repositories; read on the tools it needs; nothing on operator secrets. Before that stage is applied (today): still has modify on all of `C:\Users\mrbla\projects` (`#775 c.3879`) and an explicit Modify, inherited by children, on the whole of `C:\blarai-fleet` (read from the folder's access list on 2026-10-09), beside the inherited Authenticated Users Modify. | AS `scripts/provision-coder-account.ps1` (header), `scripts/register-coder-leg-task.ps1` |
| Scheduled task `\BlarAI\BlarAI-Coder-Leg` | Runs `scripts/coder-leg-run.ps1` as `blarai-coder`, run level Limited (not elevated), no trigger (starts only when the operator side starts it), one instance at a time, 5-hour execution limit | See above | AS `scripts/register-coder-leg-task.ps1` |
| `SYSTEM`, `Administrators` | Windows built-ins. Hold full control of the protected folders alongside the operator. | Full | AS `scripts/coder-acl-lib.ps1`, `scripts/coder-setup-lib.ps1` (protected lists) |
| Throwaway `blarai-spike` | A temporary account used once on 2026-10-05 for the inference-account feasibility test. The account, task and rights were removed. The profile folder `C:\Users\blarai-spike` is still present on 2026-10-09 and Windows lists the profile as loaded (read from the machine); cleanup needs a reboot, then `spike-verify-cleanup.ps1`, then deletion of the folder if it remains (`#1689 c.3896`). Open cleanup, see section 13. It is not part of the design. | n/a | `#1689 c.3896` |

**How many accounts exist today.** Two that matter: the operator and `blarai-coder`. The "three-account" phrase refers to a
proposal (section 4).

**The coder account is created and has been used.** It exists, with a profile at `C:\Users\blarai-coder`, and has logged on in
batch mode for the July proof and the 2026-10-04/05 network-filter test runs (`#775 c.3879`), and for one probe task run on
2026-10-09 06:21 (`#775 c.3971`; that logon is derived from the run's check 4 reporting the coder SID, because c.3971 also says
"last logon 2026-10-05"). Which of its permissions are current is listed in the table in section 1; `verify-coder-containment.ps1`
checks them against the machine.

---

## 4. The third account: a proposal, not a design in force

**Precise status.** ADR-046 proposes a third account, `blarai-model`, that would run only the model runtime: read on model
folders, no network at all, one local channel to its clients. The state on disk:

- **Not decided.** The Lead Architect proposed the idea (`#1689` description); adoption is his decision, and no decision is
  recorded (ADR-046 header "Deciders").
- **Not built.** A search for the account name `blarai-model` in the agentic-setup scripts, configs, documents and tools, and in this
  repository's `shared/`, `services/`, `scripts/`, `tools/` and `configs/` found no use of it (the one substring hit is the
  unrelated folder name `blarai-models` in agentic-setup `scripts/backup-system.ps1:126`); the account name occurs only in ADR-046,
  the decision register, and the evidence bundle's spike notes (`docs/research/containment-evidence-2026-10-05/confined-model-spike/`).
  Account creation would be an operator-run provisioning step (ADR-046 "Spike").
- **Feasibility shown once, on one machine.** On 2026-10-05 a throwaway restricted account (batch logon, not elevated, session 0)
  loaded the Qwen3.5-4B INT8 model on the Arc 140V graphics processor through OpenVINO GenAI and served a completion over the
  loopback network address while a raw Windows Filtering Platform (WFP) block was in place (`#1689 c.3896`; evidence claims C3a
  and C3b in `docs/research/account-level-containment-evidence-2026-10-05.md`; raw data in
  `docs/research/containment-evidence-2026-10-05/confined-model-spike/`).
- **Not shown.** Speed parity under the project's cold-GPU protocol (the recorded 3.7-8.5 tokens per second versus 4.5-4.8 in
  process were not cold-gated; no ratio is claimed, claim C6a); the production 14B plus draft-model pipeline (C6e); streaming;
  the case where the confined account is the client of a real model server over loopback (the test had it as the listener and
  the filters are outbound-only, so the permit rule was not exercised, `#1689 c.3897`, C3b, C6g); a real model server instead of
  a small test listener. Protection of the model folders is open work (`#1692`; claim C6f records that the test account could
  write to `B:\models`).
- **ADR-046's own header** still says the spike "has not run" and "nothing is built". The second half is correct; the first is
  stale (section 14, item 1).

Everything below describes the two-account design (operator plus `blarai-coder`).

---

## 5. Architecture and trust boundaries

```
 OPERATOR ACCOUNT (trusted)                              BLARAI-CODER ACCOUNT (contained)
 ---------------------------------------------------     -------------------------------------------
 assistant / launcher
   |
   v
 dispatch: run-fleet.ps1 -> new-agent-task.ps1
   |  plan, task text, tests (the "oracle")
   v
 Invoke-CoderDriver  --containment=off--> coder runs as the operator (today)
   |
   | containment=restricted_account
   v
 Invoke-FusedCoderRun
   1 write job + prompt  ---------------->  C:\blarai-fleet\coder-leg\{queue,prompts}   (coder can write here)
   2 Start-ScheduledTask  ----------------> \BlarAI\BlarAI-Coder-Leg  runs coder-leg-run.ps1 as blarai-coder
                                              |  creates a kill-on-close job object
                                              |  starts the ACP client (acp_coder.py) INSIDE it
                                              |      -> opencode (the coder) -> node, git, python, builds
                                              |  edits files in  C:\blarai-fleet\worktrees\<job>   (coder can write here)
                                              |  reads source repos (read-only), toolchain folders (read-only)
                                              |  model calls: http://127.0.0.1:8099 (repair proxy) -> model server
   3 wait for the result  <---------------  C:\blarai-fleet\coder-leg\results\<id>.json
   4 check: job id, kind, SID, ok flag, file owner, creation time, job_zero_confirmed
   5 re-verify worktree (identity, links, .git pointer, git config/hooks fingerprint)
   6 gate: build, tests, secret scan      -- run by the operator, on files the coder wrote
   7 git add / commit / merge             -- run by the operator only (hardened git)
```

**Boundaries, in order of importance** (`PHASE1_DISPATCH_THREAT_MODEL.md` section 2 names B1-B7; the two used here):

| Boundary | Between | Enforced by |
|---|---|---|
| B6 | Coder code and the operator's files and network | Windows file permissions on a separate account; (egress block planned, not enforced) |
| Operator-side use of coder-writable paths | The operator's scripts and files the coder can alter | The funnels in section 7 |
| Operator account and `SYSTEM` | Anything that starts with the machine at high privilege and a writable file | Check 25 (section 10) |

**What the coder can influence and the operator later consumes** is the key design object: every file under the worktree base
and the coder-leg root, and the contents of the repository's own `.git` data for linked worktrees. Section 7 lists the one
funnel per kind of operator-side use (AS `docs/fused-leg-operator-uses.md`).

**The flag.** `containment` in AS `configs/fleet-driver.json` is `off` or `restricted_account`; any other value is refused. With
`off`, the only effect is which folder worktrees are created in (`Resolve-WorktreeBase`, AS `scripts/fleet-lib.ps1:4213`), and
the coder runs as the operator (`#775 c.3858`). With `restricted_account` the coder step goes through the fused leg, requires
`driver = acp` and refuses to run while the shared folder is writable by other accounts (the manifest `note` in
`fleet-driver.json`).

---

## 6. The fused coder leg

Implemented in AS `scripts/fleet-lib.ps1` (`Invoke-FusedCoderRun`, line 1276; `Invoke-CoderDriver`, line 1556), AS
`scripts/coder-leg-queue.ps1` (queue, strict parser, job-object wrapper), and AS `scripts/coder-leg-run.ps1` (the coder-side
runner).

**Flow.** The operator writes a job and a prompt into the queue folder, starts the scheduled task (the start is proven, with a
specific diagnosis if Windows leaves it un-run, error `0x41303`, `Start-CoderLegTask`, `coder-leg-queue.ps1:212`), waits for a
result file, binds it to the job (job id, kind, SID, boolean `ok`, file owner, creation time) and rebuilds it into the result
shape the unchanged gate and merge code expect (`#775 c.3886`).

**Fail closed.** Every failure throws; there is no fallback to running as the operator and none to the older standard-input
driver. Cases named in ADR-045 Decision 2 and `#775 c.3886`: missing account or task; task never started; timeout; missing or
unusable result; a manifest that cannot be read while the coder-leg task is registered; a queue tree writable by other accounts;
links in paths. The task is stopped on timeout or cancel. Several candidate attempts for one task take turns behind a
machine-wide named mutex `Global\BlarAI-Coder-Leg-Dispatch` (`fleet-lib.ps1:1315`; any local account can open that name, and the
code comments that a squatter would only cause a refusal, `fleet-lib.ps1:1290-1294`).

**Job object.** The runner, which runs as the coder, creates a Windows job object (kill-on-close, no breakaway), starts the
ACP client inside it suspended, assigns it, then resumes it, so every descendant is born inside the job. After the run it
terminates what is left, queries the job until empty and records `job_zero_confirmed` in the result (`Start-ProcessInJob`,
`coder-leg-queue.ps1:823`; `coder-leg-run.ps1`, "dispatch" branch). If the runner dies first, Windows closes the handle and kills
the tree. Design reason: the orchestrator's elevation is unmeasured, so the fix must not need elevation (ADR-045 Decision 2;
AS `docs/fused-leg-operator-uses.md`, "The swap window (N1)").

**What the `job_zero_confirmed` field is, and is not.** It is written by the coder's own runner, so it is not independent proof.
Bad news from the runner is believed (it quarantines the worktree); good news is accepted only together with an operator-side
fact: the task not Running after `Stop-ScheduledTask` plus a bounded wait (`Assert-CoderLegTaskIdle`,
`coder-leg-queue.ps1:266`). With an elevated operator, `Stop-CoderProcessesConfirmed` (`coder-leg-queue.ps1:394`) also enumerates
the coder SID's processes. A worktree whose coder processes cannot be excluded is quarantined (marker in the operator-only
folder `state\fused-worktrees`, `Get-FusedWorktreeStateDir`, `fleet-lib.ps1:942`) until a person runs `Clear-FusedQuarantine
-ClearedBy <name>`, which writes an audit line. The control is a name parameter plus the audit entry; it does not check identity
(ADR-045 Decision 2).

**Residual (reproduced by the reviewer, not fixed).** A coder process created through the Windows Management Instrumentation
call `Win32_Process.Create` is a child of a system service, not of the job, so it escapes the job and survives closing it. A
non-elevated operator cannot enumerate it. The held pin on the worktree stops a rename or swap of the worktree root, but not
an escaped process editing file contents between the gate and the merge (AS `docs/fused-leg-operator-uses.md`, "Non-elevated
residual"; `#1691 c.3903`; `#775 c.3900`).

**Is the orchestrator elevated?** Not measured. ADR-045 Decision 2 says the session inferred "not elevated" from the launch
command; the AS operator-uses document withdraws that and says "probably elevated" (section 14, item 4). A live read of the
token is flip-blocker 0 and had not been done on 2026-10-09 (`#775 c.3971`).

---

## 7. Git: who runs what, and why the coder cannot commit or merge

**Rule.** Under containment the operator account is the only account that commits and merges. The coder has read-only access to
the source repositories, including their `.git` data, so `git add` and `git commit` fail for it (`#1678 c.3902`, AS
`docs/fused-leg-operator-uses.md` "Who commits"). The check that proves this is check 9 (section 11).

**Why git is a risk at all.** A worktree is a folder the coder can write. Git reads configuration (`core.fsmonitor`, hooks,
attributes) from inside it, and some settings run programs. If the operator ran plain `git -C <worktree> ...` after the coder
had planted a setting, that program would run as the operator. A folder swapped for a junction after a check would make the
operator's `git add -A` stage another repository's files (reproduced in a temporary test sandbox, ADR-045 Decision 2, finding
N1).

**What runs as which account:**

| Step | Account | Mechanism |
|---|---|---|
| Edit files in the worktree; run build, test and `git status` | `blarai-coder` | Inside the job object; with git-safety environment variables (below) |
| Commit, reset, clean, diff, merge, worktree removal | operator | `Get-WtGit` funnel and hardened argument list (below) |
| Build, tests, secret scan (the gate) | operator | `Invoke-CandidateBuild` under `Assert-OperatorWorktree` |

**Operator-side funnel for git** (AS `fleet-lib.ps1`):
1. `Get-WtGit` (line 1114) returns the argument prefix for any operator-side git call: `git @(Get-WtGit $wt) <command>`. For a
   worktree with no fused-run record it returns the historical `-C <path>` unchanged. For a recorded one it first re-verifies
   identity, absence of links, the `.git` pointer file and a hash of the git directory's config, hooks and attributes
   (`Assert-FusedWorktreeTrusted`, `Get-GitDirFingerprint` at line 957), and throws before git starts if anything differs.
2. `Get-HardenedGitArgs` (line 992) then pins `--git-dir` and `--work-tree` explicitly and adds `--no-optional-locks
   --no-pager -c core.fsmonitor=false -c core.hooksPath=NUL -c core.sshCommand=false -c protocol.ext.allow=never -c
   core.pager=cat`. Command-line settings outrank every configuration file.
3. The pinned worktree is held by an open directory handle plus a share-read handle on the `.git` pointer file
   (`Lock-FusedWorktree`, line 1047), which stops rename, replacement or deletion of the root or any ancestor; git is handed
   the path the handle itself resolves to.
4. Other funnels: commands run in a worktree go through `Assert-OperatorWorktree` (line 1141); file writes, copies and deletes
   through `Get-OperatorWorktreePath` (line 1153); worktree removal through `Remove-WorktreeSafe` (line 1206). A lint in
   `scripts/verify-coder-fused-seam.ps1` (an abstract-syntax-tree check) fails when a new operator-side use skips its funnel.
   The full table is `docs/fused-leg-operator-uses.md` (AS), "Call-site audit".

**`safe.directory` scoping.** Git refuses commands in a folder owned by another account ("dubious ownership"). Two scoped
answers:
- Operator side: none is needed and none is added. The explicit `--git-dir`/`--work-tree` form is not ownership-checked; this was
  measured with a worktree owned by SYSTEM on git 2.55 (AS `docs/fused-leg-operator-uses.md`, "Git trust"; the suite
  `verify-coder-setup.ps1` section H locks that the plain `-C` form would be refused).
- Coder side: the runner sets `safe.directory` for exactly its one worktree through the environment, and the coder's own
  `~/.config/git/config` carries `safe.directory = <worktree base>/*` (a prefix entry, git 2.46 and later). Never `*`.

**`core.fsmonitor` scoping.** Disabled on the operator side by the hardened argument list; disabled on the coder side by the
environment (`GIT_CONFIG_KEY_1=core.fsmonitor`, value `false`).

**The seven git-safety variables** (`Get-CoderLegGitEnv`, AS `coder-leg-queue.ps1:886`): `GIT_OPTIONAL_LOCKS=0`,
`GIT_TERMINAL_PROMPT=0`, `GIT_CONFIG_COUNT=2`, `GIT_CONFIG_KEY_0=safe.directory`, `GIT_CONFIG_VALUE_0=<worktree>`,
`GIT_CONFIG_KEY_1=core.fsmonitor`, `GIT_CONFIG_VALUE_1=false`.

**`build_env` (this repository).** The coder's tool launcher gives opencode a whitelisted environment. Until ticket `#1694`, the
seven variables were set by the PowerShell runner and then dropped by the whitelist. `tools/dispatch_harness/acp_coder.py`
now lists them in `GIT_SAFETY_ENV_VARS` (line 530) and `build_env` (line 536) passes each through when the parent holds it;
nothing is added when the parent has none, so the ordinary-run environment is unchanged. Merged as `224e7f47`
(`#1694 c.3964`); tests in `tests/integration/test_acp_coder.py` (lines 440-496): all seven survive, ordinary run unchanged,
other `GIT_*` names not passed, a toggle test that empties the list. Known seam: the Python and PowerShell lists are two
hand-kept copies; a key added on one side only makes every coder git command fail loudly (reproduced, `#1694 c.3964`). Related
open defect `#1711`: the same whitelist drops `BLARAI_RESEARCH_DOCS`, `BLARAI_REPO` and `BLARAI_RESEARCH_PYTHON`.

**The commit instruction.** `Get-CoderAgentsRulesText` (AS `coder-leg-queue.ps1:906`) renders the coder's rules file without the
"git add / git commit" rule under `restricted_account` and replaces it with "stop; the operator saves the snapshot". The rendering
is installed into the coder's own configuration by `coder-setup-lib.ps1` (line 411).

**What the coder cannot do about git, and why.** It cannot write `.git/index`, `.git/refs` or `.git/objects` of the source
repository (read-only, check 8); it cannot commit (check 9); it cannot merge (never has a write path to the main repository). The
operator funnel commits and merges (checks 13 and 14).

---

## 8. File-system containment

**What is granted** (the "ACL stage", AS `scripts/provision-coder-acls.ps1`, library `scripts/coder-acl-lib.ps1`; tickets
`#1678` narrow, `#1686` close the fleet folder, `#1692` protect model folders). ACL means access control list, the permission
list on a file or folder. The stage is dry-run by default: it prints for each folder what, before, after (computed), the exact
commands and the undo, plus a plan digest; `-Apply -ExpectPlan <digest>` re-plans and refuses on any difference, saves every
list it will touch, applies, reads back and compares; `-Rollback` and `-RestoreFrom` undo (`docs/fused-leg-operator-uses.md`
"The ACL stage").

| Location | Coder gets | Source |
|---|---|---|
| `C:\Users\mrbla\projects` (every source repo, `.git` included) | One inheritable read-and-run entry (replaces the old Modify). New repositories inherit it, so no re-provisioning per project. | LA decision `#1678 c.3892`; design `c.3902` |
| `C:\blarai-fleet\worktrees` and `C:\blarai-fleet\coder-leg` | Modify (write) | same |
| `C:\blarai-fleet` root | Read on the folder itself only; inheritance from `C:\` removed (was Authenticated Users Modify) | `#1686`; `#775 c.3879` |
| Worktree root | A delete-child deny, a defence in the stage; binds a standard account only (an elevated token of the same user bypasses it, measured 2026-10-06) | AS `docs/fused-leg-operator-uses.md` |
| Model folders (`B:\models`, `C:\models`, `C:\Users\mrbla\BlarAI\models`, the default `-ModelRoots` of `provision-coder-acls.ps1:59`) | Read kept where it was; write entries of every account other than the operator, SYSTEM and Administrators removed | `#1692`; stage text |
| Operator secrets (`~/.ssh`, `~/.git-credentials`, `%LOCALAPPDATA%\BlarAI`, `~/.aws`, `~/.azure`) | Nothing. Denied by absence of any allow entry: these live under the operator's profile, which Windows denies to another standard user by default. | `provision-coder-account.ps1` header step 4; `#775 c.3879` |
| Toolchain: opencode package, fleet `tools`, offline docset | Inheritable read-and-run; the npm shim folder "this folder only" | AS `configs/coder-toolchain.json`; `docs/fused-leg-operator-uses.md` |

**Design choices recorded by measurement** (`docs/fused-leg-operator-uses.md`): `icacls /T` follows a directory symbolic link
even with `/L`, so the stage never uses `/T` and walks trees itself (`Invoke-NoFollowWalk`), listing links and never entering
them; every removal and write goes through one checked directory handle opened without following links; targets are
normalised (8.3 names, trailing dots, device prefixes) before the forbidden-folder gate.

**Handle-based stamping and the held-handle chain (`#1713`, AS `adeb3b6`).** The coder's own configuration folder is stamped
with owner and permission list through an open handle (`Set-CoderSecurityByHandle`, `coder-setup-lib.ps1:600`;
reparse-point refusal; no path-based `Set-Acl` remains in the setup library). A handle on the final folder does not say where
its ancestors lead, so `Install-CoderOpencodeConfig` (line 707) opens the profile root and then each config folder, parents
first, into one chain (`Add-CoderHeldDir`, line 631), each opened without delete-sharing, and `Assert-CoderHeldChain` (line 649)
re-resolves every handle before each create, write and stamp. An independent review had reproduced a high-severity ancestor
swap on the first handle-only version; fixed in `e213428` (`#1713 c.3968`).

**The coder-owned opencode configuration.** Rendered from the repository, not copied from the operator's profile: the
operator's `configs/opencode.json` minus its `mcp` block, the restricted rules rendering, two fleet plugins, an offline-docs tool
wrapper and a pinned `package.json`, into `C:\Users\blarai-coder\.config\opencode`. `Test-CoderOpencodeConfigSafe`
(`coder-setup-lib.ps1:291`) is the single verdict: no `mcp`, no plugin declaration, loopback providers only, no credential, every
non-allow permission entry of the operator's config present with the same value. Files and the folders `.config`, `opencode`,
`plugin`, `tool`, `git` carry a protected list and are owned by Administrators, so the coder cannot create, replace, rename or
delete inside them; `opencode\node_modules` is the one writable folder (AS `docs/fused-leg-operator-uses.md`, "The coder's
tool-chain setup"; `#775 c.3967`).

**Why the coder can still rename `~/.config`, and how check 24 detects it.** The coder owns its profile root. On NTFS the owner
of a parent folder may rename a child away through the parent's delete-child right, whatever the child's own permission list
says. Reproduced with an unelevated token on a scratch tree (journal fragment
`docs/journal_fragments/2026-10-08_775-a-protected-folder-can-still-be-renamed-by-the-account-that-owns-its-parent.md`). The
rename cannot be prevented while the coder owns its profile root. Protection therefore has two parts: (1) while the install
runs, the held-handle chain refuses a swap and creates nothing; (2) after the install, check 24 (probe key
`coder_config_root_intact`) fails if any of `~/.config`, `opencode`, `plugin`, `tool`, `git` is a link, is missing, or is not
owned by Administrators. A replacement stands until the next probe or `Test-CoderOpencodeConfigInstalled` run, and the
operator-side apply and undo refuse a link. Residual, from the same document: the profile-root path itself must contain no link
or 8.3 name; folders above the profile root are the operator's.

**Research usage log.** The coder's lookup tool writes its usage log in the coder profile
(`<profile>\.local\share\blarai-coder\research-usage.jsonl`) because the coder gets no write grant on the operator state folder.
Consequence: under containment the evidence stream that `docs/design/CODER_DEFINITION_OF_DONE.md` capability 6 reads from
`state\research-usage*.jsonl` splits; no merge step exists yet (`#1714`).

---

## 9. Network and egress

**What the design intended.** A deny-by-default outbound block keyed to the coder's SID (threat model section 5.1, ADR-045
Decision 1).

**What is true on this machine.**
- The Windows Firewall per-SID rule created by `provision-coder-account.ps1` (step 5) is still present and enabled on the
  machine (`blarai-coder-deny-outbound`, outbound, block; read 2026-10-09) but does not enforce, because the Bitdefender
  security product owns packet filtering here; a bisect showed that even a plain all-user outbound block did not enforce
  (`#775 c.1653`; threat model section 5.3).
- On 2026-07-10 the Lead Architect kept Bitdefender and accepted the coder-egress gap, with re-visit triggers: a Bitdefender
  firewall-module change, the VM containment leg going live, or any fleet-code egress incident (`#775 c.1653`). On 2026-10-05 he
  accepted flipping with the gap still open and #1682 as a follow-up, not a precondition (`#775 c.3901`). ADR-045 still lists
  re-recording the acceptance for the go-live as his (ADR-045 header).
- Under `verify-coder-containment.ps1 -AcceptedEgressGap`, check 1 (outbound must fail) is recorded as a conscious WARN
  rather than a FAIL; without the switch it is a hard FAIL, so the gap must be invoked every run
  (`verify-coder-containment.ps1` parameter comment).
- The code seam `Assert-CoderEgressContained` (`fleet-lib.ps1:859`) only records "accepted gap" and returns. The planned
  persistent filter set would make it throw when filters are absent.

**The Windows Filtering Platform (WFP) result (`#1671`).** A raw WFP block keyed to the coder's SID enforced while Bitdefender
owned filtering, in 3 of 3 runs on 2026-10-04/05: the operator's traffic unaffected, the coder's outbound connect to 1.1.1.1 port
443 blocked, filters removed and the coder's egress open again afterwards (ADR-045 Decision 4; evidence claim C1,
`docs/research/account-level-containment-evidence-2026-10-05.md`). **How narrow that is** (ADR-045 Decision 4): one TCP connect
per run, IPv4 port 443 only, filters present about 3 to 5 seconds, dynamic (non-persistent) session, loopback tested against a test
listener and not the real model server. **Not tested:** reboot persistence, IPv6 targets, UDP and DNS, other ports, a Bitdefender
update or restart, a real coder dispatch under the block.

**Ticket `#1682` (persistent, fail-closed filters)** is open and nothing is built. Its scope is in ADR-045 Decision 4. Until it
is built, the coder can reach the network from `blarai-coder` (including a package installer's downloads). That is the accepted
gap. No other control in this design limits coder egress.

---

## 10. Secrets, privilege escalation and the boot surface

**Secrets.** The coder's account holds no operator credentials, its opencode configuration contains no credential and no MCP
(Model Context Protocol) block, and it reads the model through the loopback repair proxy at `127.0.0.1:8099` (checks 15, 19;
`Test-CoderOpencodeConfigSafe`). Operator secret paths are denied by the profile's default permissions (checks 2 and 16).
Dropping the MCP browser block removes the coder's browser tool; that capability change is waiting for the Lead Architect (`#775
c.3967`, c.3971). Residual named in the threat model: the target repository's own contents are readable by the coder, so a
repository that holds live secrets must not be given to the fleet (threat model section 5.2).

**Privilege escalation surface.** A limited account is an access-control boundary, not a kernel boundary (section 2). Separately,
a contained coder becomes dangerous if it can rewrite something that later runs as `SYSTEM` or an administrator. Ticket `#1695`
found one: the `NginxGateway` service ran `C:\nginx\nginx.exe` as LocalSystem at every boot, and `C:\nginx` was writable by
Authenticated Users, as were scripts run by two enabled boot-time tasks (`#1695 c.3962`, `c.3963`; AS
`docs/fused-leg-operator-uses.md`). Nothing in BlarAI used it (`c.3963`).

*Removal.* Done 2026-10-09: the service, 12 scheduled tasks and 3 firewall rules were removed; the folder `C:\nginx` (which
held seven private-key files and a 145 MB git bundle) was moved to an admin-only quarantine
`C:\ProgramData\nginx-quarantine\nginx`, with permanent deletion only after the containment flip (Lead Architect, `#1695
c.3969`; shipped AS `827fbe2`, `b53df90`, `373f63f`, `c.3970`). Removal script: AS `scripts/remove-nginx-gateway.ps1`.

*Check 25 (the boot-surface check).* AS `scripts/coder-boot-surface-lib.ps1` (`Find-CoderWritableBootSurface`, line 336;
`Get-BootSurfaceVerdict`, line 476), hard-required in both verify modes. **It covers:** Automatic and Delayed-start services
running as LocalSystem, LocalService or NetworkService, and enabled scheduled tasks running as SYSTEM, a service account, the
Administrators group or a member (or an unresolvable principal); for each, the executable, any script named in the arguments,
the holding folder and every ancestor folder, against write by Everyone, Authenticated Users, Users, Guests, Power Users, the
interactive and batch and network groups, the coder SID and its groups, or ownership by those. It also judges: unquoted service
paths, interpreter working folders and relative script arguments, a service account that is an administrator, and a program whose
file and folder no longer exist. A list that cannot be read, a path that cannot be resolved, a sweep that saw no services or
no tasks, and any sweep error all FAIL. Real-machine result after the removal: 346 services (106 in scope), 323 tasks (177 in
scope), 0 offenders, 0 errors; before, 6 offenders, all nginx (`#1695 c.3970`).

**It runs only inside the verify script.** The library is loaded by `verify-coder-containment.ps1` and by nothing on the dispatch path
(`coder-boot-surface-lib.ps1` header; AS `docs/fused-leg-operator-uses.md` says it is "loaded only there; the containment=off
path never names it"; no reference to it was found in `fleet-lib.ps1`, `new-agent-task.ps1` or `run-fleet.ps1`). Check 25 is
therefore a **detector**: it returns a list of offenders and a PASS or FAIL when someone runs the verify script. It refuses
nothing. A coder-writable auto-start item created after the last run is found at the next run, not prevented. The one
preventive act was the one-time nginx removal.

**It does NOT cover, as built on `main` `373f63f`** (AS `docs/fused-leg-operator-uses.md`, "Check 25", "Not covered (stated)"):
- the working folder of an ordinary (non-interpreter) program whose arguments name nothing relative. The known instance is the
  Firefox background-update task, whose working folder under `ProgramData` is writable by Users; Firefox removes that folder
  from its library search path. Judging every program's working folder flagged only that task. **Decided to cover; not yet
  built:** on 2026-10-09 the Lead Architect decided that check 25 is to be extended to judge such working folders, so that a
  new boot item with a coder-writable start-in folder fails the check. The Firefox Background Update task (task name, program
  and folder) is accepted as one exact named exception, printed as a visible WARN on every run and never silent; any other
  such item fails (`#775 c.3972`). The build is in progress on agentic-setup branch `feat/1695-boot-surface-working-folder`,
  not merged; when read, that branch had no commits beyond `main` `373f63f`. Until it merges, the library header
  (`coder-boot-surface-lib.ps1` lines 38 and 158) and the operator-uses document still say "NOT COVERED" (section 14, item 6);
- libraries a binary loads from elsewhere; who may reconfigure a service (its control permissions and registry key);
  Manual-start services, drivers, Run keys, tasks whose action is a COM handler; a Deny entry is ignored (can only
  over-report). No decision about these was found; they remain not covered.

**Acceptance.** The Lead Architect's decision (`#775 c.3972`) accepts the Firefox task as the single named exception and
decides to cover the rest of the working-folder class. No decision accepting the other not-covered items was found in the
ticket comments read for this document (`#1695 c.3962`, `c.3963`, `c.3969`, `c.3970` contain none).

---

## 11. Verification suite

All checks run from AS `scripts/verify-coder-containment.ps1`; the coder-side half is `scripts/coder-containment-probe.ps1`,
run as `blarai-coder` through the real scheduled task (`-ViaScheduledTask`, the strongest form of check 4) or directly with
`-Credential`. Checks 1-4, 6-11, 15-21, 23 and 24 run in the probe as the coder; checks 5, 12, 13, 14, 22 and 25 run on the operator side (13 and 14 consume the file that check 11 wrote). The script
exits 0 only when all hard-required checks pass (check 1 may be a WARN under `-AcceptedEgressGap`).

| # | Purpose | Notes |
|---|---|---|
| 1 | Outbound connect to an external address must fail | WARN under `-AcceptedEgressGap`; not enforced (section 9) |
| 2 | Operator secret paths ACL-denied | Fails if it read zero existing paths: an empty path list cannot pass |
| 3 | Loopback GET of the model URL succeeds | Positive control; `-LoopbackStub` proves rule scoping without the model server |
| 4 | The spawned child's token SID equals the coder SID | Detects an impersonated token that would dodge a SID-scoped rule |
| 5 | No coder write entry anywhere under `projects` (operator-side scan) | Narrowing set, `#1678` |
| 6 | Coder cannot create a file in an existing sibling repository | |
| 7 | ... nor in a repository created after provisioning | |
| 8 | ... nor `.git/refs/heads/x` or `.git/objects/xx` | |
| 9 | `git add` / `commit` in its worktree fails for a permission reason | With a read control and HEAD unchanged |
| 10 | Coder reads `assets/README.txt` in the new repository | |
| 11 | Coder writes in its own worktree | |
| 12 | New repository carries the inherited read entry (operator-side) | |
| 13 | Operator funnel commits what the coder wrote | |
| 14 | The branch merges to main | Scratch repositories `.blarai-verify-*`, removed afterwards |
| 15 | Coder reaches the repair proxy on loopback | `127.0.0.1:8099`, address read from `configs/opencode.json` |
| 16 | Coder cannot read operator opencode config, `.ssh`, runtime keystore | |
| 17 | `git status` runs in its worktree under the scoped trust | From the runner environment and from its own git config |
| 18 | opencode, node, git, git-bash, python start for it | 15-second wait each |
| 19 | Its opencode config parses: no `mcp` block, permission block kept | |
| 20 | It cannot write, delete, rename or add to that config | |
| 21 | It writes its research usage log under its own profile | |
| 22 | Installed config equals the repository render, no coder write entry (operator-side) | `Test-CoderOpencodeConfigInstalled` |
| 23 | It cannot write in the fleet root, fleet scripts, operator state folder, BlarAI `shared` folder | |
| 24 | Each config folder is still a real folder owned by Administrators | Detector, not prevention (section 8) |
| 25 | No coder-writable high-privilege auto-start service or task | Operator-side; coverage in section 10 |

Source for 1-4: the script header and `Get-ContainmentVerdict` (`scripts/coder-provisioning-lib.ps1:84`); 5-14 and 15-24:
`docs/fused-leg-operator-uses.md` and the script header; 25: header and `coder-boot-surface-lib.ps1`. The mapping from numbers to the
probe's result keys (for example `secret_reads_denied`, `loopback_ok`, `proxy_loopback_ok`, `coder_config_root_intact`) is derived from
the purpose text and from `coder-containment-probe.ps1:373-390`; the verify script is the authority for numbering.

**The mutation-harness idiom.** A test suite proves only the guards its tests exercise; a guard that was never written has no
mutant. Each suite (for example `verify-coder-setup.ps1 -Mutations`) therefore re-runs itself against mutated copies of the source
with one control disabled at a time. A mutant is KILLED when the suite exits non-zero and prints a failure line, SURVIVED when it
exits 0, and ERROR when it exits non-zero with no failure line. The unmutated control must pass first, and `-ProveHarness` shows
the classification on a known survivor, crasher and kill. Equivalent mutants are dropped with a recorded reason. The idiom is
described in the header of `verify-coder-setup.ps1`. Its limit is stated on the tickets: the nginx-removal tests passed with every
mutant killed and still missed an ownership defect, because the test fixture trusted the operator account the production check
did not (`docs/journal_fragments/2026-10-09_1695-a-test-set-that-trusts-the-operator-cannot-see-the-operator-owning-the-lock.md`).

**The off-differential idiom.** With `containment = off` the coder path must be unchanged. `verify-coder-off-differential.ps1`
compares a pinned base commit with the current tree in two ways: structurally (every function in `fleet-lib.ps1` and
`coder-leg-queue.ps1` compared by parsed text; only `Invoke-FusedCoderRun` may differ in `fleet-lib.ps1`; `configs/AGENTS.md`
and `configs/fleet-driver.json` byte-identical after folding line endings) and behaviourally (`Invoke-CoderDriver` run in a fresh
process against both trees over many manifest shapes with recording stubs, comparing the call sequence, arguments and result).
A control makes one stub differ on purpose and the comparison must report it. The base is a pinned commit, not a branch name,
because a branch name moves after merge (script header; `#1678 c.3908`).

**Offline suites and their last recorded results** (from ticket comments, on the dates given; not re-run for this document):
`verify-coder-setup` 297/0 and 71 of 71 mutants killed (`#1713 c.3968`, `#1695 c.3970`); `verify-coder-boot-surface` 232/0 with
91/91 mutants; `verify-nginx-removal` 200/0 with 68/68 mutants; `verify-coder-narrowing` 450/0; `verify-coder-fused-seam` 993/0;
`verify-coder-off-differential` 19; `verify-coder-provisioning` 49; `verify-coder-leg-wiring` 14; `verify-fleet-driver` 37
(`#1695 c.3970`). The full 117-mutant pass named in ADR-045 criteria has no recorded completion in the comments read.

---

## 12. The flip: ceremony, order and rollback

**Who decides.** Flipping `containment` is a security-posture go-live and happens only with the Lead Architect present
(ADR-045 header and Decision 6). He stated the intent to flip once the fused-leg verdict is clean and decided to flip with the
network gap accepted (`#775 c.3900`, `c.3901`).

**Remaining order as of 2026-10-09** (`#775 c.3971`, `c.3901`):
0. A live read of the dispatch orchestrator's token elevation (not done).
1. Operator-run ACL stage: dry run (the dry run is read-only; run it elevated in the same window as the apply and confirm
   `unreadable: 0`), then `-Apply -ExpectPlan <digest>` (`#1678 c.3908`; pause the fleet; close anything holding files under the
   targets; keep the first backup folder; undo only with `-RestoreFrom` / `-Rollback -From`).
2. Operator-run tool-chain setup stage `provision-coder-setup.ps1` (dry run first; exits 3 if the coder profile does not exist;
   it does exist per `c.3971`).
3. `verify-coder-containment.ps1 -AcceptedEgressGap` in real mode with the model server and proxy up, green (checks 2-25 hard).
4. One watched fused dispatch of a small task with the Lead Architect present, merged, with the coder SID in transcript and
   result, using a process-scoped override and not the production file, including a live `Stop-ScheduledTask` test that a child
   and a grandchild both disappear.
5. The flip: edit `containment` in `configs/fleet-driver.json` to `restricted_account`.
6. After the flip: permanent deletion of the nginx quarantine (`#1695 c.3969`).

**Rollback.** Set `containment` back to `off` (the flag) and, for the account and grants, `provision-coder-account.ps1
-Rollback` (removes the account, rule, grants and task) and the ACL stage's `-Rollback` / `-RestoreFrom` (ADR-045 criteria;
the rollback path is stated in `#775 c.1808` and `c.3862` and in the script help).
A rollback drill is a flip criterion (ADR-045 Decision 6) and has not been run.

**Criteria and status** (ADR-045 Decision 6 as amended in its 2026-10-09 amendment): see that amendment for the table.

---

## 13. What is not verified

Each item is stated in the sources named; none is invented.

1. **No complete dispatch has ever run through the coder account.** The fused leg has run only as probe jobs
   (`#775 c.1654`, `c.3971`; ADR-045 Decision 2: "the real task could not be run"). The first real-mode verify on 2026-10-09
   06:21 produced check 1 WARN, check 2 FAIL, check 3 FAIL (both with empty detail), check 4 PASS, then crashed on a null
   `Checks` parameter (`#1715`). Whether checks 2 and 3 failed only because provisioning had not been applied, or also because
   probe output was not captured, is not known (`#1715` "NOT KNOWN").
2. **The real coder token.** Reading and running the granted folders and the machine-wide tools, and opencode's first start in
   the coder profile (it fills `node_modules`, which needs the package registry or a seeded copy, and may want to write in the
   config folder root, which is refused by design), the real `:8099` proxy as the coder; the `search_docs` tool may be silently
   absent (`#775 c.3967`; AS `docs/fused-leg-operator-uses.md` "Not verifiable offline"). The rename of `~/.config` and check 24
   as the coder token, and the non-elevated owner-set failure path (by reasoning) (`#1713 c.3968`).
3. **The orchestrator's token elevation** (section 6).
4. **`Stop-ScheduledTask` real behaviour** (child and grandchild termination) needs a registered task and a supervised session;
   the job object does not depend on it (AS `docs/fused-leg-operator-uses.md`).
5. **Race win-rates.** The swap and check-then-use windows are closed by holding handles and by identity checks; their
   remaining windows were demonstrated by hooks in tests and reasoned, not raced to a measured rate (ADR-045 Decision 2; the
   ACL stage text, "RESIDUAL, stated plainly").
6. **Reboot persistence and fail-closed behaviour** of egress filters: not built (`#1682`; claim C6b).
7. **IPv6, UDP, DNS, other ports, Bitdefender update or restart, other antivirus products, other graphics drivers** for the
   egress block (ADR-045 Decision 4; claims C6c, C6d).
8. **The first logon of `blarai-coder` on a clean setup**, which creates the profile; until then tool-chain setup exits 3. The
   profile exists today (`#775 c.3971`).
9. **Real-system calls of the nginx removal** were first exercised on 2026-10-09; the removal needed two partial runs and an
   operator hand-off before the quarantine read-back passed (`#1695 c.3970`). Permanent deletion not yet run.
10. **The 2026-08-14 logon** of `blarai-coder` is unexplained; the Windows Security log only reached back to 2026-10-02
    (ADR-045 Consequences; `#775 c.3879`).
11. **The stall monitor's ability to read another account's process CPU** is unmeasured (ADR-045 Consequences, review L8).
12. **The `verify-coder-containment` crash path** on missing probe results (`#1715`) and the standing-gate flake `#1712`.
13. **Dependency installs once egress is blocked** need a local package mirror; none exists (threat model section 5.2).
14. **The Alpine virtual-machine leg** (the "hybrid", cross-platform jobs) is designed, not built (ADR-045 Alternatives; threat model
    section 5.4). The Windows-guest variant was dropped for licensing and memory (threat model section 5 introduction).
15. **The fused leg's wait budgets are not registered in `shared/timeout_registry.py`.** They are written up in agentic-setup
    `docs/fused-leg-budgets.md` and derived in `Get-FusedLegBudgets` (`fleet-lib.ps1`); a search of the registry for the budget
    names (`QueueWait`, `ResultWait`, `StartWait`) and for "coder_leg", "fused_leg" or "Coder-Leg" found nothing, so the
    registration (a flip criterion, `#1691 c.3887`) is not done. It is a change in this repository.
16. **Open cleanup: the `blarai-spike` profile.** `C:\Users\blarai-spike` still exists and Windows lists its profile as loaded
    (2026-10-09). To finish: reboot, run `spike-verify-cleanup.ps1` (in the spike's research-data folder, `#1689 c.3896`), delete
    the folder if it remains. Not a design item; recorded so it is not lost.
17. **Open build: check 25's extension to ordinary programs' working folders** is decided (`#775 c.3972`) and not built or merged
    (agentic-setup branch `feat/1695-boot-surface-working-folder`). Until it merges, check 25 does not judge that class.

---

## 14. Source disagreements found

Where two sources disagree, this lists both and does not choose.

1. **ADR-046 status versus `#1689`.** ADR-046 header and "Spike" section say the feasibility spike "has not run"; `#1689 c.3896`
   and `c.3897` record that it ran on 2026-10-05, and the evidence record claims C3a and C3b describe it. The decision-register
   row for ADR-046 (`docs/DECISION_REGISTER.md`, row "Updated 2026-10-05 (a three-account model is PROPOSED...") also says the
   spike "runs as a throwaway account". Handled in the ADR-046 status edit of this change.
2. **ADR-045 status text versus the repository.** ADR-045's status and Decision 2 say the job-object design "is in progress and
   not merged". It merged to agentic-setup `main` as `3097116` on 2026-10-05 (`#1691 c.3903`). Handled in the ADR-045 amendment.
3. **ADR-045 criterion "#1682 built, and verify check 1 hard" versus `#775 c.3901`.** The Lead Architect's later decision lets the
   flip proceed with the gap accepted. The ADR text is unchanged; the amendment records it.
4. **Orchestrator elevation.** ADR-045 Decision 2 says "inferred not elevated"; `docs/fused-leg-operator-uses.md` (AS) withdraws
   that and says "probably elevated" while naming the live read as unverified. Neither is a measurement.
5. **Stale prose in AS `docs/fused-leg-operator-uses.md`.** (a) Section "Who commits" says the restricted rules rendering "is not
   yet read by a coder-owned opencode config (plan step 4 creates that config)"; step 4 merged (`934f273`) and
   `coder-setup-lib.ps1:411` installs it. (b) Its "Flip blockers" list shows items 2 to 4 as built and not run, and does not list
   `#1713`, `#1695` or check 25; those closed on 2026-10-08/09. This repository cannot edit that file.
6. **Check 25 "NOT COVERED" wording versus the Lead Architect's decision.** `scripts/coder-boot-surface-lib.ps1` (lines 38 and 158)
   and `docs/fused-leg-operator-uses.md` ("Check 25", "Not covered (stated)") describe the ordinary-program working-folder case as
   NOT COVERED, deliberately. `#775 c.3972` (2026-10-09) decides to cover it, with the Firefox Background Update task as one
   named WARN exception, and says it supersedes the "NOT COVERED" wording. The build is not merged, so the code and the
   operator-uses document still say "not covered" and this document says "decided to cover; not yet built". No Lead Architect
   decision on the other not-covered items (loaded libraries, service control permissions, Manual services, drivers, Run keys,
   COM tasks) was found.
7. **"Checks 2-4 are the hard-required set" and "four checks" wording in several places, while the script now hard-requires
   checks 2-25.** `verify-coder-containment.ps1` header ("Exit 0 iff all four checks pass", lines 67-69); the
   `Get-ContainmentVerdict` comment (`scripts/coder-provisioning-lib.ps1:84-91`, "Checks 2-4 ... HARD-REQUIRED in BOTH modes",
   true of that function's four inputs only); the `note` field of `configs/fleet-driver.json` ("checks 2-4 stay hard-required");
   `PHASE1_DISPATCH_THREAT_MODEL.md` section 5.3 (the four-check proof). The pass/fail gate for the flip is the whole script.
8. **`provision-coder-account.ps1` header** presents the per-SID Windows Firewall rule as the egress control and says loopback
   "survives on the Windows loopback exemption"; `#775 c.1653` and ADR-045 say that rule is inert under Bitdefender.
   The header does not qualify it.
9. **`PHASE1_DISPATCH_THREAT_MODEL.md` section 3** describes the coder as running as the operator and section 5.1 describes a
   per-SID firewall block. Section 3 is true while `containment` is `off`; section 5.1 predates the Bitdefender finding and the
   WFP result (section 5.3 of the same file carries the accepted-gap note).
10. **Mutant count for the nginx-removal suite before the repair.** The `#1695` journal fragment (line 3) gives "203 tests and 65 of
    65 mutations" for the first real run, and "68 of 68" after three mutants were added (line 9), which agrees with `#1695 c.3970`
    (`66/66` then `68/68`). The remaining difference is 65 versus 66 for the pre-repair run; not resolved here.
11. **`#775 c.3874` versus c.3893.** `c.3874` calls the WFP result a re-visit trigger "MET"; `c.3893` corrects it to new evidence,
    not a trigger the Lead Architect named. ADR-045 already records this in its "Re-visit triggers" section.

---

## 15. Glossary

| Term | Meaning |
|---|---|
| ACL (access control list) | The per-file or per-folder list of who may read or write |
| ACE (access control entry) | One line in an ACL |
| ACP (Agent Client Protocol) | The protocol the project's `acp_coder.py` client uses to drive the coder program opencode |
| ADR (architecture decision record) | A dated document recording a design decision |
| AO (Assistant Orchestrator) | The BlarAI component that runs the conversational assistant and starts dispatches |
| ASCII | Plain text characters; used for the diagram |
| Bitdefender | The security product on this machine that owns network packet filtering |
| Check N | A numbered verification in `verify-coder-containment.ps1` (section 11) |
| coder | The AI coding model plus its tools (opencode, node, git, python) running a build |
| containment | The flag `containment` in `fleet-driver.json`, and the design that flag turns on |
| DEC / Decision register | `docs/DECISION_REGISTER.md`, the index of decisions |
| dormant | Built and merged but switched off |
| egress | Outbound network traffic |
| fail closed | On any error or missing precondition, refuse to proceed rather than proceed without the control |
| fleet | The set of scripts that dispatch coding jobs (repository agentic-setup) |
| fused leg | The code path that runs only the coder step as `blarai-coder` |
| funnel | The single function through which a kind of operator-side use must pass |
| fsmonitor | A git feature that runs a helper program to watch files; disabled for safety |
| GPU | Graphics processing unit (the Intel Arc 140V) |
| job object | A Windows object that groups processes and can kill them all when it closes |
| junction / link / reparse point | A folder or file that points elsewhere; a swap hazard |
| LA (Lead Architect) | The human owner of vision, priorities, risk acceptance and go-live decisions |
| LPE (local privilege escalation) | An exploit that raises a limited account to administrator or SYSTEM |
| MCP (Model Context Protocol) | A way to attach tools to an AI program; dropped from the coder's configuration |
| mutation harness / mutant | A test of tests: disable one control and check the suite notices |
| NTFS | The Windows file system |
| OpenVINO, OVMS | Intel's inference runtime and its model server |
| operator | The Lead Architect's own Windows account |
| quarantine | A marker that makes every operator-side route refuse a worktree until a person clears it |
| SID (security identifier) | The identity number Windows permissions refer to |
| SYSTEM / LocalSystem | The highest-privilege built-in Windows account |
| UAC | User Account Control, Windows elevation prompt |
| TCP / UDP | Transmission Control Protocol (connection-based) and User Datagram Protocol (connectionless), the two main network transports |
| DNS | Domain Name System, the lookup that turns host names into addresses |
| IPv4 / IPv6 | The two generations of Internet Protocol addresses |
| HTTP | Hypertext Transfer Protocol, used here for the loopback model probe |
| JSON | JavaScript Object Notation, the text format of the job and result files |
| INT8 | 8-bit integer weights, a compressed model format |
| COM | Component Object Model, a Windows mechanism for running registered handlers (a task action can name one) |
| VM | Virtual machine |
| WFP (Windows Filtering Platform) | The Windows kernel network-filtering layer |
| WMI (Windows Management Instrumentation) | A Windows management interface that can start processes outside a job object |
| worktree | A separate working folder of a git repository, used as the coder's workspace |

---

## 16. Decisions and who decided

"LA" is the Lead Architect. "Session" is the AI development session that owns technical choices. Attribution is by ticket
comment; no wording is quoted.

| Decision | Who | Record |
|---|---|---|
| Separate limited account plus per-account egress block as the floor for dispatched code; a hybrid later | LA | `#787` 2026-07-10; threat model section 5; ADR-045 Context |
| Keep Bitdefender and accept the coder-egress gap, with named re-visit triggers | LA | `#775 c.1653` |
| Switch the ACP driver on | LA approved | `#775 c.1805` |
| Defer the containment flip to avoid confounding a battery; bound 2026-07-18 | LA | `#775 c.1808` |
| Close the lapsed deferral by ownership, not by a new date | Session | ADR-045 Decision 3 |
| Account-level containment; fused leg design; funnels; job object instead of elevated process kill | Session | ADR-045 Decisions 1, 2; `#775 c.3862`, `c.3886`, `c.3903` |
| Run the raw WFP test | LA go-ahead | `#1671` 2026-10-04; ADR-045 header |
| Do the remaining containment steps as secondary work | LA | `#775 c.3861` |
| Narrow the coder's grant on `projects` (do not accept it) | LA | `#1678 c.3892` |
| Replace it by an inheritable read entry; the operator funnel is the only committer | Session | `#1678 c.3902` |
| Review approach for the ACL stage (fresh reviewer; weaker read-only review if blocked; LA reads the dry run before anything runs) | LA approved the session's recommendations | `#1678 c.3907` |
| Flip with the egress gap accepted; intent to flip once the verdict is clean | LA | `#775 c.3900`, `c.3901` |
| Remove the `NginxGateway` service; extend to 12 tasks and 3 rules; quarantine the folder; delete it only after the flip | LA | `#1695 c.3962`, `c.3969` |
| Handle-based stamping, held-handle chain, check 24 as a detector | Session | `#1713 c.3968` |
| Extend check 25 to judge the working folder of ordinary boot programs; the Firefox Background Update task is one named exception shown as a WARN every run. DECIDED; build in progress, not merged | LA | `#775 c.3972` |
| Seven git variables through `build_env` | Session | `#1694 c.3964` |
| Coder-owned opencode config without MCP browser block | Session built it; the capability change awaits the LA | `#775 c.3967`, `c.3971` |
| Coder tests use machine-wide Python 3.14, not project virtual environments | Awaiting the LA | `#775 c.3967`, `c.3971` |
| Three-account model | Idea LA; adoption undecided; spike by session | `#1689`; ADR-046 |
| The actual flip; re-recording the egress acceptance for the go-live; a new due date | LA (open) | ADR-045 header |

---

## 17. Threat table

Status vocabulary: **enforced** (Windows or code refuses it, and a check exercises it on the real or a test system), **detected**
(an event is noticed after the fact), **accepted** (a person decided to live with it), **not covered** (named gap, no decision
found), **decided, not built** (a person decided it, the build is not merged), **not built**. "Tested" cites the check numbers of section 11 and the offline suites; "applied" status follows
section 1 (many controls are built and not yet applied to the machine).

| # | Vector | Control | Where it lives | How tested | Status / residual |
|---|---|---|---|---|---|
| 1 | Coder reads operator secrets (keys, keystores, credentials) | Separate SID; operator profile default-denied; no allow entries | `provision-coder-account.ps1` step 4; probe `Test-SecretReadsDenied` | Checks 2, 16; July proof PASS n=1 (`#775 c.1654`); 2026-10-09 real run showed check 2 FAIL, cause unknown (`#1715`) | Enforced by design; re-proof pending |
| 2 | Coder sends data out over the network | Raw WFP per-SID block | Not built (`#1682`); `Assert-CoderEgressContained` records the gap | Check 1 WARN under `-AcceptedEgressGap`; WFP spike 3/3 (`#1671`) | **Accepted** (LA `c.1653`, `c.3901`); not built |
| 3 | Coder writes into other repositories under `projects` | Replace Modify with inheritable read | `provision-coder-acls.ps1`, `coder-acl-lib.ps1` | Checks 5-8, 12; `verify-coder-narrowing.ps1` 450/0 with toggle (restore Modify, checks fail) | Built, not applied; today the old Modify grant is still live (`c.3879`) |
| 4 | Coder commits or alters the source repository's refs and objects | Read-only `.git`; operator is the only committer | Same; `Get-CoderAgentsRulesText` | Checks 8, 9, 13, 14 | Built, not applied |
| 5 | Operator-side git runs coder-planted settings or hooks | `Get-WtGit`, `Get-HardenedGitArgs`, git-dir fingerprint | `fleet-lib.ps1:1114`, `:992`, `:957` | `verify-coder-fused-seam.ps1` 993/0; 117-mutant harness (full pass not recorded) | Enforced in code; flag off |
| 6 | Worktree swapped for a link after the check (cross-repository staging) | Held handle pin, identity checks, no-link paths | `Lock-FusedWorktree` `fleet-lib.ps1:1047`; `Assert-OperatorWorktree` | Reproduced in sandbox; fix tested: 173 swap-after-check calls, no leak (`#1691 c.3903`) | Enforced for rename/swap. Residual: an escaped process editing file contents inside the pinned tree (non-elevated path) is not excluded |
| 7 | Coder process survives the leg | Kill-on-close job object; task-idle check; quarantine; elevated enumeration if elevated | `Start-ProcessInJob`, `Assert-CoderLegTaskIdle`, `Stop-CoderProcessesConfirmed` | Suite tests incl. refusing a zero claim against a survivor; real `Stop-ScheduledTask` not tested | Partly enforced; WMI-escape reproduced, not fixed; elevation unmeasured |
| 8 | Forged or replayed result or job | Strict single JSON parser and typed schemas; owner, SID, id, creation-time binding; queue ACL gate | `coder-leg-queue.ps1` (`BlarStrictJson`); `Wait-CoderLegResult` | 36-input differential; `fused-seam` suite | Enforced in code |
| 9 | Coder replaces its own tool configuration, or renames `~/.config` | Protected lists, Administrators ownership, held-handle install, check 24 | `coder-setup-lib.ps1:600,631,649,707` | `verify-coder-setup.ps1` 297/0, 71/71 mutants; checks 19-24 | Install: enforced. Rename after install: **detected, not prevented** |
| 10 | Coder alters fleet scripts, queue root or operator state | Fleet root closed; refusal while shared tree writable by others; check 23 | ACL stage; `Invoke-FusedCoderRun` refusal | Check 23; `fused-seam` suite | Built, not applied |
| 11 | Coder rewrites something that later runs as SYSTEM or administrator | The one known instance removed (nginx); check 25 sweep **detects** others when `verify-coder-containment.ps1` runs | `remove-nginx-gateway.ps1`; `coder-boot-surface-lib.ps1:336` (loaded only by the verify script; no dispatch-path caller) | `verify-coder-boot-surface.ps1` 232/0 with 91/91 mutants; real sweep 0 offenders (`#1695 c.3970`) | Removed (nginx instance) and **detected, not prevented**: nothing refuses a later coder-writable boot item between verify runs; the real-mode verify has never passed (`#775 c.3971`, `#1715`). Ordinary-program working folders: **decided to cover, not yet built** (`#775 c.3972`; Firefox update task the one named WARN exception). Not covered: loaded libraries, service control permissions, Manual services, drivers, Run keys, COM tasks |
| 12 | Local privilege-escalation exploit | None at this layer | Threat model section 5.2 | None | Accepted by design as a residual; the VM leg would address it, not built |
| 13 | Coder destroys what its own account can write | Throwaway worktrees; operator re-verifies before use | Threat model section 5.2 | Not separately tested | Accepted residual |
| 14 | Silent fallback to running as the operator | Every failure throws; no stdin fallback; an unreadable manifest refuses where the coder-leg task is registered or the provisioning marker exists, otherwise it is read as `off` (`fleet-lib.ps1:1591-1597`) | `Invoke-CoderDriver`; `Invoke-FusedCoderRun` | `fused-seam` suite; `off-differential` 19 | Enforced in code |
| 15 | Flag off by default drifts unnoticed | Flip is a ceremony with named criteria; the deferral needs an owner | ADR-045 Decisions 3, 6 | n/a | Process control |
| 16 | Coder alters model weights | Model-folder write entries removed except operator/SYSTEM/Administrators | ACL stage (`#1692`) | Stage plan and read-back; evidence C6f shows the problem | Built, not applied |
| 17 | Hostile packages or build scripts fetched when egress is open | None beyond row 2 | Threat model sections 4 (T-D2), 5.2 | None | Accepted residual with the egress gap |
| 18 | Prompt injection steers the coder | Out of scope here; containment limits the blast radius | Threat model section 4 (T-D3) | n/a | Not covered by this design |
| 19 | Git-safety variables dropped by the launcher | Whitelist passthrough | `acp_coder.py:530,536` | `test_acp_coder.py` four tests incl. toggle | Enforced; two hand-kept lists (seam); `#1711` sibling open |
| 20 | Two dispatch candidates collide | Named mutex; single-instance task | `fleet-lib.ps1:1315` | `fused-seam` | Enforced; a squatter can cause a refusal only |
| 21 | Evidence for the coder's research-tool use splits | None yet | `#1714` | n/a | Open defect |
| 22 | Model runtime compromise (not the coder) | Third account `blarai-model` | ADR-046 | Feasibility spike, one machine | **Not built**; not decided |

---

## 18. Where to read next

| Topic | Document |
|---|---|
| The accepted design and flip criteria | `docs/adrs/ADR-045-Coder-Containment-Account-Level-Fused-Leg-and-WFP-Egress-Block.md` and its 2026-10-09 amendment |
| The proposed third account | `docs/adrs/ADR-046-Three-Account-Model-Confined-Inference-Service.md` |
| Original threat model | `docs/security/post_capstone_2026-07/PHASE1_DISPATCH_THREAT_MODEL.md` |
| Evidence and its limits | `docs/research/account-level-containment-evidence-2026-10-05.md` |
| Why the flag was off | `docs/research/coder-containment-lapsed-deferral-2026-10-04.md` |
| Operator-side funnels, ACL stage, setup, check 25 (agentic-setup) | `C:/Users/mrbla/agentic-setup/docs/fused-leg-operator-uses.md` |
| Wait budgets (agentic-setup) | `C:/Users/mrbla/agentic-setup/docs/fused-leg-budgets.md` |
| Live status | Vikunja `#775` newest "CURRENT STATE" comment; `configs/fleet-driver.json` |
