---
title: Windows coder containment, dedicated account vs restricted token vs AppContainer vs Microsoft's container (#1740)
status: measured, awaiting the Lead Architect's decision; arm A not yet run
area: security
ticket: "#1740"
date: 2026-10-11
---

# Windows coder containment: dedicated account, restricted token, AppContainer, Microsoft's container

**Status (2026-10-11):** research and measurements are complete for every setup except arm A, the dedicated
account itself, which only the Lead Architect can run (`tools/probes/containment_arms/arm_a_operator.cmd`).
The opencode coding agent against the local model was not run in any setup (the model endpoints were down).
The recommendation in the next section is the session's and is provisional on those two gaps. Nothing on the
machine was changed as a result of this work. The throwaway network rules, AppContainer profiles and the
loopback exemption were removed and checked as gone (`phase2/stage-verify-clean.json`). The throwaway fixture
folders (`C:\blarai-spike-1740`, `C:\blarai-spike-1740-mxc`) are still on disk until the teardown step runs; the
arm A script needs them and should be run before that teardown, after the #775 flip.

**Terms used below.** ACL: access control list, the list of who may do what to a file or folder. SID: security
identifier, the number Windows uses for an account or group. NTFS: the Windows file system. WFP: Windows
Filtering Platform, the part of Windows that holds network rules. MXC: Microsoft's Execution Containers project.
Loopback or localhost: the machine talking to itself (127.0.0.1). A write-restricted token is a login badge with
a second list that Windows checks only when the program writes; a fully restricted token checks that list for every access.

## Outcome, in plain language

**Recommendation (the decision is the Lead Architect's).**
1. **Keep the dedicated account as the base design.** It is the only setup in this study for which the three
   things the coder needs have each been shown: its secrets are refused by identity (check 2, 2026-07-10), the
   local model is reachable over loopback (check 3), and a persistent network block keyed to the account held in
   three of three runs (#1671). The coder's tools on the account itself have not been verified (the arm A run
   would do it). No other setup can replace it today (below).
2. **[PROPOSED] Test layering a write-restricted token on the account's processes (OpenAI Codex's design).**
   Measured here on the operator's token: a write-restricted token confined writes to the folders granted to it
   and denied every folder that broad groups can write (all 6 such folders refused in 3 of 3 runs; 48 of 48
   predictions matched over all 16 folders). That is the leak class the account design has had to chase folder by
   folder (`B:\models`, ProgramData, Public, `C:\Windows\Temp` when it was open). It is a complement, not a
   replacement: reads stay open and the network stays unfenced. Two limits. Folders granted to the coder
   account's own identity (`projects`, the fleet folder) stay writable under any list that holds that identity,
   so the layer narrows only what broad groups grant. And git-bash got past start-up in one restricted test
   only with the operator's own identity in the list (section 5.4), which cancels the confinement of everything
   that identity owns; for the coder account that would leave exactly its own folders writable, which is what it
   needs, but it has not been tested on the account.
3. **Do not adopt AppContainer or Microsoft's container (MXC) for the coder now; keep watching both.** Both give
   the strongest default-deny in the study (only granted folders reachable, no network until granted, no
   separate account to maintain), and Microsoft services the AppContainer boundary. Both stop short for this
   coder today: git-bash and opencode's launcher do not start inside them, the real tool folders are not
   readable without copies or grants, and MXC's one-shot process container (tier 1, the only MXC form run) refused
   the host-loopback setting on this Windows build. Other MXC backends and its stateful mode were not run (see
   the MXC library study). Revisit when the probe reports host-loopback support, or when the coder no longer needs
   git-bash.
4. **Do not adopt a fully restricted token (B3) in place of the account.** It protects what only the operator's
   own identity can reach (secrets, profile, projects) but leaves a subset of the account's broad-group leaks (models, fleet, ProgramData), breaks
   git-bash and opencode, and needs a purpose-built network rule to be fenced at all.

**Microsoft MXC as a library (added 2026-10-11 after the Lead Architect pointed to Microsoft Build 2026 session BRK262).**
In that talk (11:55) Microsoft calls "dynamic composition" the library building a container on the fly from the
agent's declared needs, the user's consent and IT policy, matched to what the operating system offers (a process
boundary, a micro virtual machine, a Linux container, a cloud PC). Arm E tested one pinned slice of that, the
one-shot Windows process container. A read-only study of the rest (full detail in
`docs/research/windows-containment-comparison-2026-10/mxc-library-study/`) found, at release v1.0.0:
- The shipped files contain no feature named "dynamic composition" and no user-consent or IT-policy layer
  (the only "consent" is for telemetry, off by default). The talk's description reads as product direction.
  The nearest shipped pieces are helper functions that merge file-access lists discovered from the *caller's*
  environment, and the five-step stateful lifecycle. One open, unmerged proposal (PR #1309) composes per-tool allow lists.
- A held-open (stateful) sandbox exists only for IsolationSession, which needs a Windows Insider build this
  laptop lacks and forces open network, and for WSLC Linux containers, which cannot run the Windows git-bash and opencode launcher.
  The process container arm E used has no stateful form.
- No documented backend lets a confined coder reach the model on 127.0.0.1 while the network stays blocked.
  One change on MXC's main branch after v1.0.0 (PR #1406, an identity-less loopback proxy) aims at this; untested.
- Audit mode can seed a grant list from a real run but runs with protections off, grants whatever was touched
  and cannot see the git-bash denial; it does not replace hand-narrowing.
- Maturity: v1.0.0 is 5 days old; config schemas 0.6 to 0.8 were declared supported on 29 September and rejected
  on 7 October, without being listed as breaking; open bugs overlap the coder's tools (git-bash, git working folder, loopback).
- For the job the Hyper-V Linux guest does today (parsing untrusted input), Hyperlight, NanVix and WSLC are
  separate-kernel designs, but Hyperlight and NanVix are experimental and none offers the vsock channel; whether any beats the current design is unknown.
- Correction: the v1.0.0 tag is commit 7bf21024; the c6f301d5 cited earlier is main, 20 commits later. The launcher
  tested in arm E was the release archive checked against its published digest; some documentation was read from main.

**What the flip of containment (#775) needs from this study: nothing.** None of this changes the flip's steps.

**What would change the recommendation:** arm A failing to run the toolchain under the account; the layered test in
item 2 breaking the coder's tools; an MXC release whose probe reports host-loopback support; or opencode proving
not to need git-bash.

**Limits that apply to everything below:** one machine, one Windows build (26200.9457), one antivirus
(Bitdefender, not re-checked), IPv4 TCP 443 for network tests, 3 runs per variant (control 5), the fixture
copy of the toolchain rather than the real install, and no model in the loop.

## What was measured

### The comparison the ticket asked for

All rows measured on the same probe payload unless marked. A is a model plus earlier evidence, because only the
Lead Architect can run it. "Secrets" are the five operator secret paths; "other folders" are the 15 throwaway
folders that copy real folders' access lists plus grant/deny pairs; the work folder is always writable.

| | D unconfined (control) | A dedicated account | B2 write-restricted token | B3 fully restricted token | C AppContainer | E Microsoft container |
|---|---|---|---|---|---|---|
| Secrets readable | 5 of 5 | 0 (modelled; proven 2026-07-10, check 2) | 5 of 5 | 0 of 5 | 0 of 5 | 0 of 5 |
| Other folders writable | 11 | models, fleet, projects, ProgramData, Public (modelled) | 1 (the one granted to it) | 5, plus 1 write-only (the broad-group-writable ones and the granted one) | 2 (the granted pair; the refusal on one is ignored) | 0 |
| Network by default | open | open until the account-keyed block is applied | open | open | **blocked** | **blocked** |
| Network rule keyed to the identity | n/a | yes (#1671, 3 of 3) | no: the token acts as the operator | **yes, with a block plus operator permit** (3 of 3) | yes (package identity, 3 of 3) | built in: egress denied by default, allowed in E2 |
| Local listener over loopback | works | works (check 3, 2026-07-10, the live model) | works | works | **blocked until a loopback exemption** (an administrator-run step; it worked here, then was removed) | **refused by the launcher on this build** |
| node, git, Python | ok | not verified on the account | ok | ok | ok (copies) | ok (UI lockdown off) |
| git-bash | ok | not verified on the account | **fails** | **fails** | **fails** | **fails** |
| opencode launcher | ok | not verified on the account | ok | **fails** | **fails** | **fails** |
| Real tool folders usable | yes | grants needed | predicted yes (not launched on the real install) | **no** (the npm folder is unreadable: opencode cannot start) | **no** (Python, node unreadable) | copies |
| Setup and upkeep | none | account, ACL narrowing, persistent network rules (LA-run) | per launch, none | per launch, none | per launch profile, plus an administrator step for loopback | none; one self-cleaning registry key per run |
| Starting token | operator, administrator groups deny-only, medium | n/a | same as D | same as D | same as D | **inherited the elevated console's administrator groups, enabled, 2 privileges** |
| Microsoft services breaks as a security boundary | no (not a boundary) | yes ("user boundary") | no | no | yes ("AppContainer boundary") | not stated for MXC itself; its identity is an AppContainer identity |

### 1. Setups compared

| Setup | What it is here |
|---|---|
| A | the dedicated account `blarai-coder` (today's design) |
| B1 | the operator's token through SAFER "normal user" (`runas /trustlevel:0x20000`; the 2026-09-17 study's form) |
| B2 | the operator's limited token, write-restricted, restricting list = Codex's published list (a synthetic identity granted only on the work folder, Everyone, the logon identity) |
| B3 | the operator's limited token, fully restricted (restricting list applies to reads too), broad list (synthetic identity, Everyone, Users, Authenticated Users, logon identity, RESTRICTED) |
| C | an AppContainer with no capabilities; variants add the loopback exemption, `internetClient`, and a network rule keyed to the package |
| D | the operator's limited token, unconfined (the control) |
| E | Microsoft's MXC container, tier 1 (the operating system's own container), `microsoft/mxc` v1.0.0 |

**Instruments** (all under `tools/probes/containment_arms/`, dev tooling, nothing ships):

| Instrument | What it measures | How it was checked before use |
|---|---|---|
| `effective_access.py` | what Windows' access check grants each setup on each path, read-only | the tokens agreed with the real limited token on all 40 paths; the AuthZ machinery agreed with the kernel check for the operator's identity on all 40 paths; repeats returned identical masks. A's group set is modelled (computed groups plus Everyone, LOCAL, Authenticated Users, This Organization, BATCH), so A's column is a model until arm A runs |
| `fixtures.py` | throwaway folders under `C:\blarai-spike-1740` carrying copies of real folders' access lists, grant/deny pairs per identity, a copy of the toolchain | the grant/deny pairs are the on/off test: each identity is granted on one folder and refused on its twin |
| `run_arm.py`, `run_arm_e.py`, `arm_payload.py` | the probe payload run inside a setup: toolchain, one small real task, loopback, secret reads, fixture writes, egress, child and grandchild | arm D (7 runs on the real install, 5 on the copy): all 45 categorical outcomes identical every run |
| `wfp_fence.ps1` | a temporary network rule keyed to one identity (account, synthetic identity, package identity) or the app-scoped separation test; dynamic session, removal verified | self-test 0 failures; dry run opened the filter engine read-only; derived from the #1671 spike's definitions |
| `countdown_gate.ps1` | the visible 2-minute countdown with a STOP button before the separation test | functional test: window visible, topmost, foreground |
| `summarise_phase2.py`, `analyse.py` | summaries, run-to-run variation, prediction against run | re-run on the banked data reproduces the banked summaries |

**Conditions (2026-10-11, 11:00 to 11:25 -04:00):** Intel Core Ultra 7 258V, Windows 11 Pro 10.0.26200 (build
26200.9457, 25H2), 31.3 GB, 19 GB free and CPU 59 % at start, elevated console, Python 3.14.3. Running
alongside: this session, background builder and reviewer agents, the operator desktop; no GPU work and no test
gate. Phase 1 (2026-10-10 22:11) used the real install and 12.2 GB free, CPU 11 %. Raw data:
`docs/research/windows-containment-comparison-2026-10/` (`conditions-phase1.json`, `phase2/conditions-phase2.json`).

### 2. Run-to-run variation (control)

Arm D on the real install, 7 runs: launch to exit 6.587 s (CV 1.9 %); git-bash start 0.528 s (2.7 %);
git, node, Python start 0.057 to 0.068 s (1.7 to 4.5 %); opencode `--version` 0.525 s (10.2 %); the small task
0.768 s (9.9 %); all 45 categorical outcomes identical. Arm D on the fixture copy, 5 runs: node 10.4 %, git
8.8 %, Python 9.6 %, task 3.9 %, payload total 3.1 %. A timing difference smaller than these is not a finding.
No timing conclusion is drawn in this study. Start times are 0.05 to 0.2 s, and the variants differ from the
control by more than its variation in three situations: while a concurrent process was applying a network rule
(Python start from about 10 % faster to 77 % slower than its own unfenced run, so part of that range is inside the control's roughly 10 % variation), where a step failed fast, and where a connection waited for its
timeout. Full table: `phase2/summary-phase2.md`.

### 3. What each setup can reach (Windows' own access check, read-only)

R read, W write, D delete, P change permissions. C* is the in-memory AppContainer prediction; A is a model.
The launches in section 4 agreed with these predictions in every case (below).

| path | D | A | B1 | B2 | B3 | C* | instr. agree |
|---|---|---|---|---|---|---|---|
| `C:\Users\__USER__\.ssh` | RWDP | ---- | RWDP | R--- | ---- | ---- | ok |
| `C:\Users\__USER__\.git-credentials` | RWDP | ---- | RWDP | R--- | ---- | ---- | ok |
| `C:\Users\__USER__\AppData\Local\BlarAI` | RWDP | ---- | RWDP | R--- | ---- | ---- | ok |
| `C:\Users\__USER__\.config\opencode` | RWDP | ---- | RWDP | R--- | ---- | ---- | ok |
| `C:\Users\__USER__\.aws` | RWDP | ---- | RWDP | R--- | ---- | ---- | ok |
| `C:\Users\__USER__\.codex\.sandbox-secrets` | RWDP | ---- | RWDP | R--- | ---- | ---- | ok |
| `C:\Users\__USER__` | RWDP | ---- | RWDP | R--- | ---- | ---- | ok |
| `C:\Users\__USER__\Documents` | RWDP | ---- | RWDP | R--- | ---- | ---- | ok |
| `C:\Users\__USER__\BlarAI` | RWDP | ---- | RWDP | R--- | ---- | ---- | ok |
| `B:/models` | RWD- | RWD- | RWD- | R--- | RWD- | ---- | ok |
| `C:/Windows/Temp` | ---- | ---- | ---- | ---- | ---- | ---- | ok |
| `C:/blarai-fleet` | RWD- | RWD- | RWD- | R--- | RWD- | ---- | ok |
| `C:\Users\__USER__\projects` | RWDP | RWD- | RWDP | R--- | ---- | ---- | ok |
| `C:/blarai-fleet/worktrees` | RWD- | RWD- | RWD- | R--- | RWD- | ---- | ok |
| `C:/blarai-fleet/coder-leg` | RWD- | RWD- | RWD- | R--- | RWD- | ---- | ok |
| `C:/ProgramData` | RW-- | RW-- | RW-- | R--- | RW-- | ---- | ok |
| `C:/Users/Public` | RW-- | RW-- | RW-- | R--- | ---- | ---- | ok |
| `C:/` | R--- | R--- | R--- | R--- | R--- | ---- | ok |
| `C:/Users/blarai-coder` | ---- | RWDP | ---- | ---- | ---- | ---- | ok |
| `C:/Python314` | R--- | R--- | R--- | R--- | R--- | ---- | ok |
| `C:/Program Files/nodejs` | R--- | R--- | R--- | R--- | R--- | ---- | ok |
| `C:/Program Files/Git` | R--- | R--- | R--- | R--- | R--- | R--- | ok |
| `C:\Users\__USER__\AppData\Roaming\npm` | RWDP | ---- | RWDP | R--- | ---- | ---- | ok |
| `C:/Windows/System32` | R--- | R--- | R--- | R--- | R--- | R--- | ok |

What the table separates:
- **What the identity closes.** A is refused the operator's secrets and profile by identity alone. B3 closes the
  same operator-only resources (its restricting list holds no entry the operator's own files grant) and nothing
  else. B1 and B2 are the operator, so they read everything the operator reads. C* is refused everything not
  granted to an AppContainer.
- **What the permissions close.** A and B3 stay writable wherever a broad group (Authenticated Users, Users)
  has Modify: `B:\models`, the fleet folders, ProgramData. The provisioning stage narrows the first three
  (#1692, #1686, #1678). B2 and C* write nowhere on this list without a grant.
- **B1 equals D on every folder:** the SAFER "normal user" token removes administrator rights and nothing that
  matters for these paths. (B1 was launched from the elevated console, so it kept high integrity and the
  S-1-5-114 group enabled where D had it deny-only; whether the 2026-09-17 study launched elevated was not
  rechecked.)
- **C* cannot read** `C:\Python314`, nodejs or the npm folder.

### 4. Launches on the probe payload

3 runs per variant (control 5). Prediction against run: fixture writes 48 of 48 and secret reads 15 of 15 agree
in every variant (control 80 of 80 and 25 of 25); the toolchain results below are measured, not predicted.

| Variant | What it showed |
|---|---|
| D-fixture (control) | everything works: node, git, git-bash, Python, opencode; secrets readable; 11 other folders writable; network open |
| B1 | same outcomes as the control on every check; it ran at high integrity with the local-administrator group enabled, where the control ran at medium with it deny-only |
| B2 | writes confined to the one folder granted to its synthetic identity plus the work folder; secrets readable; network open; **git-bash fails**; the rule naming the synthetic identity matched nothing, as the model predicted |
| B3 | secrets refused 5 of 5; writable only where broad groups or the synthetic identity are granted; **git-bash and opencode fail** |
| B3 on the real install | Python, node and git start (Users and Authenticated Users grant them); git-bash and opencode fail |
| C, real install | does not start (the interpreter cannot load: Python and node folders are unreadable to an AppContainer) |
| C0, fixture copy, nothing granted | node, git, Python ok; git-bash and opencode fail; secrets refused; only the work folder and the granted pair writable; **network and loopback blocked by the container itself** |
| C1, plus the loopback exemption | the local listener reachable; internet still blocked |
| C2, plus `internetClient` | internet reachable; loopback still blocked without the exemption |
| C3, plus exemption and a rule keyed to the package | loopback reachable, internet blocked again. C3 differs from C2 in two things (the exemption and the rule), so C2 is not a clean lock-off run for the rule alone |
| E0, Microsoft container, defaults | secrets refused; only the work folder writable; network and loopback blocked; **node, git and git-bash fail to start** (default UI lockdown) and Python's `ctypes` fails |
| E1, UI lockdown off, network none | node, git, Python ok; git-bash and opencode fail; the rest as E0 |
| E2, plus egress allowed | internet reachable; loopback still blocked |
| E3, direct host-loopback allow | **refused by the launcher**: "not supported by this version of Windows" |
| E4, proxy mode plus the same host-loopback allow | refused by the launcher for the host-loopback setting; proxy mode on its own was not run |

**Cleanup verified** after every stage: no AppContainer profile folder, no loopback exemption, no network-rule
objects, no MXC registry mapping, no changes to the granted folders' access lists (hashes before and after
every MXC run), no MXC recovery state.

### 5. Findings the instruments and the runs produced

1. **A refusal entry naming an AppContainer does not refuse it.** A refusal naming the package identity
   left the write allowed in AccessCheck (in memory), in a real file open under the AppContainer token
   (independent reviewer) and in **12 of 12 launched AppContainer runs** (the one deny-for-container fixture).
   Refusals naming ALL APPLICATION PACKAGES or a held capability were checked in AccessCheck only, not in a
   launched run. A refusal naming the user's own identity still refuses, but the launched user-identity control
   is not a discriminating test, because even a grant to the user is refused to the container. Entries that name the container can only add
   access; an exception has to be made by not granting. No published source states this (Project Zero 2014-12
   sets deny entries aside).
2. **A fully restricted token can be singled out by a network rule; a write-restricted token cannot.** The
   separation test (app-scoped to one program file under the throwaway root, so nothing else on the machine could
   match): a block naming the operator and a synthetic identity blocked D, B2 and B3 (positive control, 3 of 3
   each, children included); adding a higher-weight permit naming the operator alone left D and B2 connected and
   **blocked only B3** (3 of 3 each; 0 failed operator connectivity checks in any rule hold). The write-restricted
   token behaves as the operator because Windows consults restricting identities only for write requests, and
   the network rule's request is not a write (the likely reason, not separately verified). OpenAI's statement that Windows Firewall rules cannot match a
   restricted token's second list concerns firewall rules; at the raw filter level the fully restricted form can
   be matched. This is one machine, IPv4 TCP 443, three runs, and a rule scoped to one program; the unscoped
   form was not run.
3. **Restricted tokens have two launch requirements that are in no source read.** A restricted token launches
   only when derived in one step from the launching process's own token, and its default access list must grant
   the restricting identities, or the process dies during library initialisation (`0xC0000142`, in 0.05 s).
   Codex's and Chromium's published designs set the default list; this study found the two requirements by
   failing without them. A true capability identity (S-1-15-3-...) as a restricting identity was attempted in the
   diagnostic scripts and was refused; that output was not banked, so treat it as unverified.
4. **git-bash does not start under a restricted token or an AppContainer, for different recorded reasons.**
   Under the AppContainer-class setups (C, E) its runtime fails creating a named object in the global namespace
   (`NtCreateDirectoryObject(\BaseNamedObjects\msys-2.0...)`, access denied). Under the restricted tokens the
   recorded errors differ: "couldn't create signal pipe, Win32 error 5" (B2 and B3 on the fixture copy) and a
   `CreateFileMapping` access error (B3 on the real install). In one diagnostic restricted test it got past
   start-up (exit 1) with the operator's own identity in the restricting list, which cancels the confinement of
   everything that identity owns; that output was not banked. Whether git-bash then runs correctly was not tested.
5. **Microsoft's container, tier 1, on build 26200.9457:** the launcher is Microsoft-signed and its release
   archive matches the published digest; `--probe` reports tier "base-container", no access-list augmentation, native
   deny paths supported, host-loopback allow **not** supported, session isolation not available. Its default
   turns on Windows' graphics lockdown, which stops node, git and Python's `ctypes`; with it off they start. Its
   file grants did not change the access lists of the granted folders. The container identity is an AppContainer
   identity at low integrity. The container's processes kept the launching console's administrator group
   enabled (and 2 privileges), because tier 1 does not strip them; every other setup in this study started with
   the administrator groups deny-only. Run from a standard console that difference would not exist.
6. **The AppContainer loopback exemption and profile creation worked from an administrator console** and were
   removed and verified; whether they need administrator rights was not tested from a standard console.

### 6. Machine findings (nothing changed; both need the Lead Architect)

- **#1742: `C:\Windows\Temp`.** The folder and 197 of its 266 objects carry a protected SYSTEM-plus-Administrators
  list, so the lock happened after 2026-10-08 21:59:23 (the newest locked object's creation). An upper bound
  cannot be read from the folder: objects created there by SYSTEM before the lock already carried the same
  inherited entries, and 4 objects created before 21:59:23 have inherited entries. No operating-system update
  in that period. Candidate cause: a mutation test in agentic-setup's `verify-nginx-removal.ps1` (#1695) that
  disables the folder gate while a test calls the real lock function on `C:\Windows\Temp` (added in
  agentic-setup `fc1c1f3`, 2026-10-08 19:32); the lock list and the unchanged SYSTEM owner match a lock applied
  with ownership-taking stubbed out. If the mechanism is right, every run of that suite re-applies the lock.
  The default to restore is not established from a primary source for this build (section "Not known").
- **#1743: the Codex sandbox accounts.** Codex's setup ran here on 2026-04-16 and recorded an error creating its
  firewall rule. Only two loopback block rules for `CodexSandboxOffline` exist, so its "offline" account has no
  Windows Firewall rule blocking its egress (Codex's source installs raw filters, which the firewall cmdlets
  cannot list; a raw filter was neither confirmed nor ruled out). Both accounts are enabled, members of Users, and
  can write `B:\models` and `C:\blarai-fleet`. Codex also left a Modify grant on `C:\Users\__USER__\BlarAI` for a
  Codex workspace identity (`~/.codex/cap_sid`, a random S-1-5-21-shaped identity), effective only for a token
  carrying it as a restricting identity.

## State of each mechanism (workstream 0)

### Who uses what, read at source

| Product | Windows mechanism (read at source unless marked) | Status, date | AppContainer? |
|---|---|---|---|
| **OpenAI Codex** (Windows sandbox) | "elevated" mode: two dedicated local users (`CodexSandboxOffline`, `CodexSandboxOnline`) running a **write-restricted token** whose restricting list is Everyone, the logon identity and a synthetic identity; ACL grants to the synthetic identity on writable roots; firewall rules block all outbound traffic for the Offline user; read grants for the sandbox users on `C:\Users\<real-user>`, `C:\Windows`, Program Files and ProgramData. "Unelevated" mode: the restricted token on the real user with environment-variable network suppression, which OpenAI calls "only advisory". Source `codex-rs/windows-sandbox-rs` @`cc7ba336`; write-up by David Wiesen, 2026-05-13 (read in full) | shipped; Codex docs now name MXC "recommended" and these modes "legacy fallbacks" | considered and rejected: "Codex is not one tightly scoped app ... that made AppContainer the wrong shape for the problem." An AppContainer PR (#4175, 2025-09-24) closed unmerged without a stated reason |
| **Anthropic sandbox runtime (srt)** | dedicated local user `srt-sandbox` launched by `CreateProcessWithLogonW`; a LUA restricted token with administrators and logon identities disabled, privileges stripped, **no restricting identities** ("that breaks Schannel/LSA RPC"); job object; isolated window station; persistent machine-wide WFP block keyed to the user identity with a loopback permit to ports 60080-60089; additive explicit ACEs per session. `anthropics/sandbox-runtime` @`5507fb0e` | Windows marked **alpha**; 21 Windows issues, most open | none in the code |
| **Microsoft MXC** (eXecution Container) | tiers: OS-native "BaseContainer" with per-container network filters (needs build 26200.9278; this machine qualifies); AppContainer plus file-system brokering; AppContainer plus DACLs (needs an admin preparation step); "IsolationSession", a per-execution OS-provisioned dedicated user in its own session (needs 26200.9550; this machine does not qualify). `microsoft/mxc` @`c6f301d5` | v1.0.0 2026-10-07 | yes, as two of its tiers; MXC's own host-prep doc records that `cmd`, `pwsh` and `node` fail at the system-drive root until extra entries are added |
| **nono** (nolabs-ai) | NEP-0005 (draft 2026-09-29, one commit `62bb720b`): phase 1 WFP block keyed to the sandbox user identity; phase 2 AppContainer plus capability identities primary, dedicated user plus restricted token plus ACLs "documented fallback only" | no Windows code in main; external Windows PRs all closed unmerged (last 2026-07-31); 111 releases, none with a Windows asset; issue #2000 open with only a bot reply; SECURITY.md: production use "not recommended" | proposed, unimplemented |
| **Chromium** | restricted token, job object, alternate desktop, integrity levels; AppContainer without capabilities and LPAC for some processes | production since 2008-era | partly |
| **Firefox** | Chromium sandbox library: restricted tokens, job lockdown, alternate desktop and window station, low/untrusted integrity | production | not in its content-process table |
| **Win32 App Isolation** (Microsoft) | AppContainer-based isolation for desktop apps | still "preview" on Microsoft Learn since 2023-06 | yes |
| **Defender Application Guard** | Hyper-V | removed in Windows 11 24H2 | n/a |
| **Windows Sandbox** | disposable VM | available on Pro, not Home | n/a |

### Security boundary status (Microsoft Security Servicing Criteria, read live)

| Mechanism | Microsoft services breaks as a security boundary? |
|---|---|
| Dedicated standard account | yes: "User boundary". A folder that grants Users or Authenticated Users is authorized access, not a vulnerability, so the #1686/#1689/#1692 class is ours to close (reading of the criteria, not a sentence on the page) |
| AppContainer | yes: "AppContainer sandbox boundary" |
| Restricted token, low integrity | not named, therefore not a serviced boundary |
| UAC | named as not serviced |
| Hyper-V VM | yes |

### Published bypass classes (primary sources read, details in the research file)

- **Dedicated account:** broad-group grants (Users, Authenticated Users, Everyone); SYSTEM services, tasks and
  installers that read user-writable paths; kernel elevation bugs; the network is not token-gated, so a network
  filter is required; named pipes and COM with Everyone rights.
- **Restricted token:** kernel token-handling bugs (CVE-2020-0981); a shared desktop; sibling processes opening
  each other (CVE-2020-12388 class); a write-restricted token leaves reads open; no network gating. A Microsoft
  Office sandbox author (David LeBlanc) calls a bare restricted token "a speedbump" unless restricting
  identities and a separate desktop and window station are done right.
- **AppContainer:** weak access lists on the same user's objects that name ALL APPLICATION PACKAGES
  (CVE-2014-6350 class); COM and RPC brokers; firewall configuration bypasses (Project Zero issue 2207,
  WontFix); the loopback exemption is an administrator-only facility; shared named pipes.
- **All three:** none holds against an in-kernel exploit. A virtual machine is a separately serviced boundary
  and the stronger option.

### Deprecation and roadmap signals; criticism of the account shape

No deprecation found for AppContainer or restricted tokens. Application Guard is removed. Win32 App Isolation
has stayed in preview since 2023-06. MXC reached 1.0 on 2026-10-07 and Codex now prefers it. Microsoft lists an
experimental `CreateProcessInSandbox` API (page dated 2026-06-01), not evaluated. Nobody credible calls the
dedicated-account shape weaker in those words: nono NEP-0005 calls it "coarse" and "stateful: an account, ACLs,
and a broker survive between runs" (and "robust and battle-tested on Windows"); srt issue #402 (2026-10-04, no
maintainer reply) reports writes outside the grants through the account's Authenticated Users membership, the
class measured here, and proposes a write-restricted token; OpenAI added the dedicated account to make the
network fence possible.

## NEP-0005 against #1669 comment 4016

Read from the raw file (20,356 bytes, last and only commit `62bb720b`, 2026-10-01, PR #2032): every claim on
#1669 c.4016 is confirmed - draft, created 2026-09-29, author lukehinds; phase 1 a WFP block keyed to the sandbox
user identity plus a loopback permit (a range of about 10 ports, and phase 1 itself needs the dedicated user's
identity); phase 2 AppContainer plus capability identities as the primary mechanism ("**AppContainer + capability
SIDs as the primary FS/ process mechanism**"); dedicated user plus restricted token plus ACLs as "a **documented
fallback only**"; open question 1 "**Does AppContainer hold up?**". NEP-0005's open question 3 is uninstall and
repair of persistent state; it does not ask whether a network rule can key to an arm's identity. For an
AppContainer, Microsoft documents it (`FWPM_CONDITION_ALE_PACKAGE_ID`, "the SID of an app container"), and this
study measured it (C3). The NEP lists no AppContainer limitation about loopback, toolchains, administrator steps
or profile creation; those come from Microsoft, OpenAI, MXC and the runs above.

## The primer against Microsoft's documentation

25 claims were checked (table in the research file `ws0-msdocs-bypass`). Confirmed: how tokens, groups and
privileges are checked by Windows; children inheriting the parent's token; inheritance of access-list entries;
WFP keying on an identity; the restricted-token mechanics; network and loopback being off by default for
AppContainer; low integrity and private object names. The statements the primer carries on the points that
needed precision:
- **Access-list order:** Windows reads the entries in order and the first match decides. Explicit entries come
  before inherited ones, refusals before allows at each level, and inherited entries level by level (the
  parent's refusals, the parent's allows, then the grandparent's). A refusal written on the folder beats an
  allow; an allow written on the folder comes before a refusal inherited from above.
- **What an AppContainer can reach:** a folder that grants only Users or Authenticated Users does not admit it; a
  folder that grants ALL APPLICATION PACKAGES does, and that group holds read and execute on `C:\Windows`,
  `C:\Program Files` and `System32` here. Microsoft: AppContainers "are granted access to certain system
  files/directories, common registry keys and COM objects". Only the less-privileged variant (LPAC, ALL
  RESTRICTED APPLICATION PACKAGES) is near nothing.
- **Network rule on an AppContainer:** documented and measured (C3).
- **Network rule on a restricted token:** not stated in Microsoft's documentation; measured here (finding 2).
- **Access lists** cover every securable object (processes, pipes, sections, COM servers, registry keys, files),
  not the network; an AppContainer profile persists per user until deleted.

## Gray Swan AI (added by the Lead Architect, 2026-10-10)

- **What it sells:** Cygnal, a hosted classifier for prompts, responses and tool calls (with a "Cygnal Code"
  pre-tool-use hook for Codex and Claude Code, not opencode); Shade, automated red-teaming; Arena, crowdsourced
  red-teaming competitions; adversarial-evaluation services. On-premises deployment is claimed on marketing pages
  only; pricing is demo-gated; SOC 2 Type 2 is listed.
- **OS containment:** none. Everything works on text at the model or agent layer.
- **Data leaving the machine:** the vendor's own plugin sends the system prompt, full history, prior tool
  results and the pending call to `api.grayswan.ai`, and its example configuration fails open (`failOpen: true`).
  That is the shape BlarAI refused for a hosted judge.
- **Research and open artifacts:** circuit breakers (2024-06; a 2024-07 paper reports 100 % attack success under
  embedding-space attacks); agent red-teaming (2025-07, 1.8 M attacks); indirect injection (2026-03, 0.5 to 8.5 %
  attack success across 13 models). MIT-licensed benchmark code (`ipi_arena_os`, 41 behaviours, 15 coding) and 95
  attack strings generated against Qwen are the only pieces usable offline; neither has been run against
  Qwen3-14B. No Cygnal weights, no OpenVINO artifacts, no independent evaluation found. Paper full texts were
  not read (abstracts only).

## Artifacts read and artifacts only summarised

**Read at the primary source:** nono NEP-0005 raw file, its commit history, issue #2000 and comments, issue #463,
PRs #530/#555/#583/#643/#725/#726, releases (111, every asset name), SECURITY.md; `anthropics/sandbox-runtime`
README and Windows sources (`wfp`, `token`, `launch`, `job`, `logon`, `runner`, `self_protect`, `winsta`,
`install`, `acl`, `windows-sandbox-utils.ts`) @`5507fb0e`, issues #402, #559, #657, #105, #396, #579, #160, #17;
`openai/codex` `windows-sandbox-rs` (`token`, `lib`, `identity`, `wfp`, `cap`, `app_package`,
`service_identity`) @`cc7ba336`, PRs #4175, #4905, issue #48721, `developers.openai.com/codex/windows`; OpenAI's
write-up "Building a safe, effective sandbox to enable Codex on Windows" (2026-05-13, read in full by the lead
session through a Playwright browser after direct fetches were refused; `ws0-codex-mxc.md` records it as not read
because that agent could not reach it; the read record and the quotes used are in
`workstream-0/openai-codex-writeup-read-note.md`); `microsoft/mxc` README, os-version-support, networking,
host-prep, oneshot, dispatcher, schema, and the sources `fallback_detector.rs`, `sandbox_tracking.rs`,
`filesystem_dacl.rs` @`v1.0.0`, plus the release archive and its signatures; about 20 Microsoft Learn pages
through the MicrosoftDocs markdown (DACLs, ACE order, inheritance, access tokens, restricted tokens,
`CreateRestrictedToken`, `CreateAppContainerProfile`, AppContainer implementation and isolation, mandatory
integrity control, SID constants, WFP filtering conditions, `NetworkIsolationSetAppContainerConfig`, loopback and
network-capability pages); the live Microsoft Security Servicing Criteria page; Project Zero posts (2014-12,
2016-01, 2020-04, 2020-06, 2021-08, 2015-11); Chromium's sandbox design document; Mozilla's sandbox wiki; David
LeBlanc's "Practical Windows Sandboxing" parts 1 and 3; Gray Swan's site, docs and trust page, arXiv abstracts, and
the READMEs of its open repositories; the Codex setup files on this machine.

**Only summarised (not read at source):** the Windows Developer blog post on MXC (2026-10-07); third-party claims
that Copilot and Replit use MXC; Adobe Reader and Office Protected View internals; third-party CVE write-ups
(CVE-2020-13149, CVE-2024-28827, CVE-2022-22715); Forshaw's *Windows Security Internals* chapter 7; the bodies of
eight srt issues (titles only); every Gray Swan paper's full text; the Cygnal Code installer and plugin source
(not located).

Research files with every quote and URL: the four workstream-0 files and the OpenAI read record are banked under
`docs/research/windows-containment-comparison-2026-10/workstream-0/`.

## Not known

- Arm A on the payload (A's column is a model plus earlier evidence). The script is
  `tools/probes/containment_arms/arm_a_operator.cmd`; it needs the Lead Architect.
- opencode against the model, in any setup (the model endpoints were down), and so whether opencode needs git-bash
  or has a working fallback shell.
- A write-restricted token layered on the dedicated account itself (item 2 of the recommendation).
- Whether the separation rule works unscoped (not app-scoped), over IPv6, UDP, or other ports.
- Whether `CreateAppContainerProfile` and the loopback exemption need administrator rights on this build
  (Microsoft's pages are silent; Project Zero says the exemption is administrator-only; they worked here from an
  administrator console).
- Whether a newer Windows build or MXC release adds host-loopback support to the container's tier 1.
- The cause of the `C:\Windows\Temp` change (#1742) beyond the candidate mechanism, and the exact default
  DACL, owner and inheritance flags of that folder on build 26200: the best-supported listing (Users: create
  files, create folders, traverse; CREATOR OWNER, Administrators and SYSTEM full control, inherit-only on
  children) comes from Microsoft's AppLocker text, Microsoft's Windows XP security template and four
  third-party listings, but no primary source for this build was reached.
