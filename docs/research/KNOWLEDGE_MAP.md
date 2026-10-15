---
title: BlarAI Knowledge Map
status: living
area: research
---

# BlarAI Knowledge Map: topic cards (first cluster: containment and isolation)

Drafted 2026-10-11 from the main checkout `C:/Users/mrbla/BlarAI` (main contains the merged #1740 work; every repo path below was checked to exist). Written for the Lead Architect (LA). Acronyms are spelled out on first use.

## Summary (10 lines)

1. Two separate questions sit in this cluster: how to confine the AI **coder** (it writes and runs code), and how to isolate **untrusted input** (hostile web pages, images) so it never touches the host. They use different machinery today: a restricted Windows account for the coder, a network-less Hyper-V Linux guest for parsing.
2. Coder, current answer (provisional): keep the dedicated account `blarai-coder`. It is built and merged but **switched off** (`containment = off`); the switch-on is an LA-present ceremony (ticket #775, ADR-045).
3. The #1740 study (2026-10-10/11) measured five alternatives on one test program. None can replace the account today: git-bash fails in every confined alternative and Microsoft's container refuses localhost on this Windows build. Recommendation (the session's, awaiting the LA): keep the account, test adding a "write-restricted token" on top.
4. The strongest single measured result: a raw Windows Filtering Platform (WFP, the Windows packet-filter layer) block keyed to the coder account stopped its internet while a loopback permit kept the local model reachable (ticket #1671, arm 1). Limits: windows of 3 to 127 seconds, one machine, not persistent.
5. Untrusted input, current answer: HTML parsing is designed to live in a network-less Hyper-V Alpine guest reached only over vsock (virtual socket); the guest parser is built and provisioned but **dormant** (`enabled = false`). The guest "oracle" (test runner) is live.
6. The MXC (Microsoft eXecution Container) library study found no alternative backend that offers vsock; several are separate-kernel designs but experimental. Nobody has measured whether any beats the current VM design.
7. Nothing in the Definition of Done (docs/design/CODER_DEFINITION_OF_DONE.md) has a containment row; containment is tracked only by ADR-045 and tickets. That is a gap.
8. A claim in this cluster was corrected at least 14 times (section 5). The pattern: a number from one session ("3 of 3", "known to run") was later narrowed by a reviewer.
9. Knowledge sits in about 90 files across 12 folders; `docs/INDEX.md` lists none of the containment studies and describes `research/` as 16 files when it holds 61 top-level files (section 6).
10. Not verified by me: Vikunja ticket text (not read), raw data outside the repo (existence checked, contents not), full text of the primer HTML, and the workstream-0 notes beyond their openings.

---

**Second project:** the LA is building The Governator as well as maturing BlarAI. How the two knowledge systems connect, what may cross the wall between the repositories and by what process, and the BlarAI findings that bear on the Governator are in `GOVERNATOR_BRIDGE.md` (same folder).

**More cards (batch 2, 2026-10-11):** the single adjudication door (Policy Agent and egress), egress and the ceremonies, inference and performance on the Arc and NPU, and memory, ingestion and born-encrypted storage are in `KNOWLEDGE_MAP_BATCH2.md` (same schema, same folder). Batch 3 (the coder fleet and the Definition of Done; the self-governance boundary, the Coordinator and supervised autonomy; the people-facing surface; measurement discipline and the evidence system) is in `KNOWLEDGE_MAP_BATCH3.md`. Audit item raised by batch 3: ticket #1750 (are the ADR-039 boot controls wired into a boot path). Batch 4 (the agent-governance landscape and the Governator venture; models and the upgrade watch; upstream, community and publication; host, operations and ceremonies) is in `KNOWLEDGE_MAP_BATCH4.md`. Batch 5 (governing agent actions: the concept spec and confidentiality axis; agent protocols and the code-review loop; memory headroom; web search methods; record corrections and upkeep, including the two saved-page asset folders) is in `KNOWLEDGE_MAP_BATCH5.md`. The folder-by-folder catalogue is `KNOWLEDGE_FOLDER_CATALOGUE.md`. The comparison with off-the-shelf products is `OFFTHESHELF_VS_BLARAI.md`.

## 1. How to use this map

- Read the Summary, then the topic card whose question is yours. Each card goes from the big picture (section d, "layers of zoom") down to the smallest detail you can ask for.
- Table (c) is the evidence list. The **grade** column tells you how far to trust a line: *measured on this machine* > *read from source* > *vendor documentation only* > *reasoning*.
- Section 4 (Connections) is where new ideas come from: each link pairs two documents from different studies. All are hypotheses marked [PROPOSED].
- Section 5 lists claims that were later corrected. Section 6 lists what is missing or scattered.
- Where a number appears, it was copied from the cited file. "Not verified" marks anything I could not check.

**Schema (reuse for every later topic card):** (a) the question in one sentence; (b) current answer and status (decided / provisional / open) with the deciding document; (c) evidence table: date | path | finding in one plain line | grade | confidence; (d) layers of zoom (outline from why-at-all down to a single error code or entry order); (e) open questions, each with the observable that would close it; (f) decisions made / waiting for the LA; (g) tickets; (h) raw sources and where they live.

Evidence grades used: **M** measured on this machine; **S** read from source code or a primary artifact; **V** vendor documentation only; **R** reasoning or design.

---

## 2. Topic card: Containing the coder

### (a) The question
How do we stop code that an AI model writes and runs (the "coder", the program opencode with node, git, git-bash and Python) from reading the operator's secrets, writing outside its work folder, or reaching the internet, without breaking the tools it needs and while it can still reach its local model?

### (b) Current answer and status
**Provisional, partly decided.**
- *Decided* (LA, 2026-07-10, ticket #787 "Decision 1(b)"): a separate limited Windows account `blarai-coder` plus a per-account outbound network block, as the floor for all dispatched code. Recorded in `docs/adrs/ADR-045-Coder-Containment-Account-Level-Fused-Leg-and-WFP-Egress-Block.md`.
- *Built, not switched on*: the "fused coder leg" (the coder step runs as that account through a scheduled task). The flag `containment` in agentic-setup `configs/fleet-driver.json` reads `off`. Per `docs/design/CODER_CONTAINMENT_DESIGN_OVERVIEW.md` (as of 2026-10-09; not re-read from the flag file by me) the permission-narrowing stage and the tool-setup stage are merged but not applied to the machine, and the egress block is not built as a persistent control. The LA decided (ticket #775 c.3901, quoted in the ADR-045 amendment) to flip with the egress gap accepted.
- *Open, the LA's*: whether to add or replace a mechanism. The #1740 recommendation (session's, provisional) is in `docs/research/windows-containment-comparison-2026-10-10.md`: keep the account, test layering a write-restricted token, do not adopt AppContainer, MXC or a fully restricted token now.
- Deciding documents: ADR-045 (design plus two amendments), the register rows of 2026-10-05, 10-09 and 10-10 in `docs/DECISION_REGISTER.md`.

### (c) Studies, measurements and decisions

| Date | Document path | What it found, one plain line | Grade | Confidence note |
|---|---|---|---|---|
| 2026-06 | `docs/security/capstone_2026-06/deep_dive_log.md` | AppContainer was deferred once for the Assistant Orchestrator on GPU/TPM grounds (as quoted in the ADR-045 amendment). | R | Reasoning does not obviously transfer to the coder; I quoted it from ADR-045, did not re-read the log. |
| 2026-07-09 | `docs/security/post_capstone_2026-07/RESEARCH_BRIEF_adversarial_testing_2026-07-09.md` (section 4, lines 113-125) | Web-sourced table: restricted local user = low setup, weak boundary; AppContainer = high setup, severe toolchain damage; Hyper-V VM is "the only option containing filesystem + network + kernel". | V (web sources) | Not measured on this machine; it was the only side-by-side before #1740. |
| 2026-07-10 | `docs/security/post_capstone_2026-07/PHASE1_DISPATCH_THREAT_MODEL.md` (section 5) | Defines the (b) floor, its honest residuals (local privilege escalation, destruction inside the account, dependency mirror needed) and the hybrid direction (VM for cross-platform jobs). | R | Design document. Section 5.1 pre-dates the Bitdefender finding (design overview section 14.9). |
| 2026-07-10 | ticket #775 c.1653/c.1654 (cited in ADR-045; ticket text not read by me) | Bitdefender owns packet filtering so the Windows Firewall per-account rule is inert; four-check proof green under "accepted egress gap"; check 2 (secret paths ACL-denied) passed once. | M, n=1 | Raw output exists only on the ticket (evidence doc section 6). |
| 2026-07-10 | `docs/performance/coder_in_vm_memory_2026-07-10.json` | Coder model (30B) plus a 6 GB toolchain VM peaks at 27.5 GB against a 31.323 GB ceiling (figure from threat model 5.4; I did not open the JSON beyond its header). | M | Speed of building inside the guest is the remaining unknown. |
| 2026-09-17 | `docs/research/runtime-action-governance-product-feasibility-2026-09-17.md` (Seam 6, 7; line 142-158) | A per-program firewall rule was accepted and never enforced (37/37 requests succeeded) under Bitdefender; one restricted-token form removed admin and nothing else; an AppContainer probe wrote nowhere but its package folder. | M | The AppContainer child-process test failed on a working-directory error before measuring (A4 appendix). |
| 2026-10-04 | `docs/research/coder-containment-lapsed-deferral-2026-10-04.md` | `containment=off` was the day-one default; the LA-approved deferral (bound 2026-07-18) lapsed with no owner (~78 days). | S (git history, subagent) | Subagent report, not independently re-run. |
| 2026-10-04/05 | `docs/research/account-level-containment-evidence-2026-10-05.md` claim C1; data `docs/research/containment-evidence-2026-10-05/wfp-spike/result-20261004-235941.json` (and `-000002`, `-000028`) | A raw WFP block keyed to `blarai-coder` stopped its outbound connect to 1.1.1.1:443 under Bitdefender, 3 of 3 runs. | M, n=3 | Filters stood at most about 5 s, dynamic session, one machine, IPv4 TCP 443 only. Three runs in 57 s are a repeat, not replications. |
| 2026-10-05 | same doc, claims C2a/C2b/C6f; `containment-evidence-2026-10-05/confined-model-spike/runs/` | Throwaway account: 8 of 8 secret reads denied, 4 of 4 named outside writes denied, but `C:\Windows\Temp` and `B:\models` were writable; for the real `blarai-coder` the "cannot write outside" claim is false today. | M | Status words OBSERVED / CONTRADICTED. |
| 2026-10-05 | same doc C3a/C3b/C6a; ADR-046 | A non-interactive restricted account loaded Qwen3.5-4B INT8 on the Arc 140V GPU and served a completion under the block. Speed 3.7-8.5 tok/s vs 4.5-4.8 in process, not cold-gated, so no ratio. | M, n=3 / n=1 | Speed claim NOT ESTABLISHED. |
| 2026-10-05 | `docs/research/containment-evidence-2026-10-05/reviews/code-review-775-fused-leg-2026-10-05.md` | Three review rounds reproduced a forged result, a folder-to-junction swap after the check, and ACL-gate holes in the fused leg. | M (reproduced in temp sandboxes) | Fixes merged 2026-10-05 per ADR-045 amendment; WMI process-create escape reproduced, not fixed. |
| 2026-10-05 | `docs/research/containment-evidence-2026-10-05/preflight/775-preflight-2026-10-05.md` | `C:\blarai-fleet` writable by every local account; coder had Modify on all of `projects`; last logon 2026-10-05 not 2026-08-14. | M (read-only) | Shell not elevated. |
| 2026-10-05 | `docs/adrs/ADR-045-...md` | Design: account-level containment, fused leg, funnels, job object, WFP egress block, flip criteria. Amended 2026-10-09 (status, LA decisions) and 2026-10-10/11 (comparison). | R + decisions | Authoritative. |
| 2026-10-05 | `docs/adrs/ADR-046-Three-Account-Model-Confined-Inference-Service.md` | PROPOSED: a third inference-only account `blarai-model`; spike showed feasibility on one machine; nothing built. | R + M (spike) | LA decides adoption. |
| 2026-10-09 | `docs/research/containment-evidence-2026-10-05/arm1-permit/runs/testc-on-20261009-180608.json` (and 5 siblings) | With the loopback permit, the confined account (as client) got a 32-token completion from a real local server while its internet was refused; without the permit its loopback request was refused (error 10013). 3 of 3 each. | M, n=3 per condition | Windows of 3-4 s; six runs in seven minutes. Claims C7, C8. |
| 2026-10-09 | `docs/design/CODER_CONTAINMENT_DESIGN_OVERVIEW.md` | Cold-readable description of the whole design, 25 verification checks, flip order, 17 not-verified items, 11 source disagreements. | S + R | As of 2026-10-09; I read lines 1-654 of 764. |
| 2026-10-10 | `docs/research/windows-containment-comparison-2026-10-10.md` (phase 1, then phase 2 on 10-11) | Compared dedicated account (A), SAFER token (B1), write-restricted (B2), fully restricted (B3), AppContainer (C), MXC container (E) vs unconfined control (D). | M (A is a model) | Section "Outcome" is the summary; limits stated: one machine, build 26200.9457, 3 runs per variant. |
| 2026-10-11 | `docs/research/windows-containment-comparison-2026-10/phase2/summary-phase2.md` | git-bash fails in B2, B3, C, E; opencode launcher fails in B3, C, E; MXC refused host-loopback (E3/E4 did not start). Control run-to-run variation 3-13 %. | M | Predictions from Windows' access check agreed with launches 48 of 48 writes, 15 of 15 secret reads per variant. |
| 2026-10-10/11 | same study, section 5 finding 1; `effective-access/deny-ace-check.json` | A refusal entry naming an AppContainer does not refuse it (12 of 12 launched runs). | M | No Microsoft page states it. |
| 2026-10-11 | same study, section 5 finding 2 | A fully restricted token can be singled out by a network rule (block naming operator plus restricting identity under an operator permit); a write-restricted token cannot. 3 of 3. | M | Scoped to one program file; unscoped form not run; IPv4 TCP 443 only. |
| 2026-10-10 | `docs/research/windows-containment-comparison-2026-10/workstream-0/ws0-codex-mxc.md`, `ws0-nono-srt.md`, `ws0-msdocs-bypass.md`, `openai-codex-writeup-read-note.md` | Source reads of OpenAI Codex, Anthropic srt, nono NEP-0005, Microsoft docs (25 claims of the primer checked). | S | I read only the openings of these four files. |
| 2026-10-10 | `docs/research/windows-containment-primer-2026-10-10.html` | The LA-facing plain explanation of tokens, access lists, AppContainer. | R + V | I read only the lines matching git-bash/whole. |
| 2026-10-11 | `docs/research/windows-containment-comparison-2026-10/mxc-library-study/studies.json`, `skeptic-checks.json` | MXC v1.0.0 as a library: no "dynamic composition" feature in shipped files; stateful sandbox only for IsolationSession and WSLC; audit mode over-grants and cannot see the git-bash denial. | S | All three studies passed skeptic checks "with corrections". No container was run. |
| 2026-10-10..11 | `docs/research/windows-containment-comparison-2026-10-10.md` section 6 | `C:\Windows\Temp` became administrators-only after 2026-10-08 21:59 (#1742); Codex sandbox accounts left on the machine can write `B:\models` (#1743). | M | Cause of #1742 is a candidate mechanism only. |
| 2026-07-20 | `docs/research/encryption-and-isolation-evaluation-2026-07-20.md` section 3 | Microsoft's README then said "no MXC profiles should be treated as security boundaries currently"; re-check trigger defined (warning removed AND non-alpha schema). | S | The trigger has not been evaluated in writing (see Gaps and Open questions). |
| 2026-10-04 | `docs/research/runtime-action-governance-landscape-2026-09-16.md` + four `landscape-*-agent-governance-2026-09-16.md` | These are about action-level governance (what an agent may do), not OS containment; they mention containment only in passing (Claude Code sandbox is the enforcement seam for shell commands in the Anthropic survey). | V | Documentation-level surveys by their own statement. |
| 2026-10-05 | `docs/research/jev-policy-agent-ideation-2026-10-04.md` | Not containment. Policy-judge ideas that bear on the layer above containment (see Connections). | V + M (9B data) | Corrected three times (section 5). |
| 2026-10-05 | `docs/adrs/ADR-049-Governator-Venture-Reopened.md`; `docs/adrs/ADR-042-...md` | The LA reopened the runtime-governance venture on the narrower, containment-evidence claim. | decision | No runtime change; claim and form are the LA's. |
| ongoing | `LESSONS.md` lesson 236; `FIELD_NOTES.md` | Lesson 236: a control on an agent's tool surface does not govern processes it spawns; assess containment at the layer the OS enforces (account/SID). | R | Transferable rule. |
| 2026-10-05 | `BUILD_JOURNAL.md` entry "A deferral nobody owned" (line 39); fragments `docs/journal_fragments/2026-10-10_1739-*.md`, `2026-10-10_1740-*.md`, `2026-10-11_1740-*.md`, `2026-10-09_1718-*.md`, `2026-10-08_775-*.md` | Narrative of the lapsed flip, the instrument validation, and the three places paper and measurement disagreed. | S (first-person accounts) | Fragments not yet folded into BUILD_JOURNAL.md as far as I checked. |
| 2026-10-14 | `docs/research/nono-9p-failclosed-control-2026-10-14/README.md`; data `docs/research/nono-9p-failclosed-control-2026-10-14/runs/run2-piped-20261014-231822.json` | nono's Landlock sandbox on the WSL 9P mount: 360 runs (30 probes, 4 command lines, 3 each), no operation the command line denies succeeded, including writes through a junction, symlinks, a hard link, `..`, other letter cases and 8.3 names; the #2089 over-denials reproduce; 24 runs not judged (a move nono refused to start, a stream 9P cannot address). | M, n=3 per cell | One machine, root, stdin piped; the pty run hung and is superseded; a rename out of the grant was not tested. |

Dispositions (reviews that checked this cluster, each with a machine-checkable table): `docs/reviews/containment-evidence-disposition-2026-10-05.md` (V1-V12, R1-R2, N1-N5, P1-P5), `docs/reviews/adrs-044-048-disposition-2026-10-05.md`, `docs/reviews/arm1-permit-scripts-disposition-2026-10-09.md`, `docs/reviews/adr045-appcontainer-amendment-disposition-2026-10-10.md`, `docs/reviews/containment-comparison-phase1-disposition-2026-10-10.md`, `docs/reviews/docs-replace-wrong-statements-disposition-2026-10-11.md`, `docs/reviews/final-review-1740-disposition-2026-10-11.md` (44 rows; exists on main), `docs/reviews/code-review-containment-evidence-adr049-2026-10-05.md`, `docs/reviews/code-review-adrs-044-048-2026-10-05.md`, `docs/reviews/1719-public-readmes-disposition-2026-10-09.md`.

### (d) Layers of zoom

1. **Why containment at all.** A coding model reads untrusted text (task, repository files, packages) then runs code with the rights of whoever launched it. Chain: attacker-influenced content, code execution, secret read, exfiltration (`PHASE1_DISPATCH_THREAT_MODEL.md` sections 3-5; design overview section 2).
   1. **What containment can and cannot do** (design overview section 2; ADR-045 Decision 1): it limits damage; it is not a defence against wrong code, not a kernel or virtual-machine boundary, not per-action governance.
   2. **Why an operating-system layer, not a rule on the program.** ADR-042 context: protections a third party reaches on Windows are cooperative (a flag skips them, a crash opens them). Lesson 236: a child process routes around any policy above the OS. Account-level controls are checked by Windows on every file open and connection.
2. **Which kind of boundary.** Three tiers of strength (research brief section 4; Microsoft servicing criteria table in the #1740 report):
   1. Dedicated account plus file permissions plus network filter (today's design). Microsoft services the "user boundary".
   2. Restricted token (same login with a weakened badge). Not a serviced boundary.
   3. AppContainer / MXC container (sealed identity granted things one by one). Microsoft services the AppContainer boundary.
   4. Virtual machine: separate kernel; the stronger option for hostile code (ADR-045 Decision 1; threat model 5.4; the hybrid direction). Designed, not built for the coder.
3. **The five properties the coder needs** (report "Outcome"): secrets refused; writes confined; network blocked except loopback to the model; the toolchain still starts; upkeep is bearable.
   1. **Secrets refused.** Dedicated account: by identity (check 2). Restricted tokens: B3 yes, B2 no. AppContainer/MXC: yes.
      - Detail: operator-profile folders carry no allow entry for the coder (denial by absence, not a deny entry). Evidence doc claim C2a.
      - Detail: a deny entry naming an AppContainer is ignored (12 of 12). Any design that relies on "add a deny for the container" does not work; exceptions must be made by not granting.
   2. **Writes confined.** The account inherits what broad groups grant (Authenticated Users, Users). Leaks named: `B:\models` (#1692), `C:\blarai-fleet` (#1686), `C:\Users\mrbla\projects` (#1678), `C:\Windows\Temp` (#1742, since locked). Provisioning stage narrows them; merged, not applied.
      - Detail: write-restricted token closed all 6 broad-group-writable fixture folders in 3 of 3 runs (the layering proposal), but folders granted to the coder's own identity stay writable.
   3. **Network.**
      1. Windows Firewall per-account rule: inert under Bitdefender (c.1653; feasibility Seam 6 A3 appendix).
      2. Raw WFP filter at the connect layer: enforced in 3 of 3 (C1).
         - Detail: block weight 0x1000, permit weight 0x2000, sublayer weight 0xFFFF; dynamic session vanishes when the script exits (fail-open) (ADR-045 Decision 4).
         - Detail: with the loopback permit absent the same request failed at the socket with error 10013, the same code as the internet connect (C8). The permit is load-bearing.
      3. Persistent, fail-closed version: ticket #1682, not built. Reboot persistence, IPv6, UDP, DNS, other ports untested (C6b-C6d).
   4. **Toolchain.** node, git, Python start in every variant from copies; git-bash fails in B2, B3, C, E; opencode launcher fails in B3, C, E. On the dedicated account itself: not verified (arm A not run).
      - Detail: git-bash under AppContainer-class setups fails creating a named object in the global namespace (`NtCreateDirectoryObject(\BaseNamedObjects\msys-2.0...)`, access denied); under restricted tokens the recorded errors differ ("couldn't create signal pipe, Win32 error 5"; `CreateFileMapping` access error) (report section 5 finding 4). MXC issue #1061 says no setting can grant it.
      - Detail: restricted tokens only launch when derived in one step from the launcher's token and with a default access list granting the restricting identities; otherwise the process dies in 0.05 s with `0xC0000142` (finding 3).
   5. **Loopback to the model.** Dedicated account: works (check 3, live OVMS in July; arm 1 with real server). AppContainer: blocked until an administrator-run loopback exemption. MXC tier 1: launcher refuses host-loopback on build 26200.9457 ("not supported by this version of Windows").
4. **The operator-side seam** (equally important): the biggest holes found were in the operator's own code around the account (forged result, junction swap, text guard bypasses), not in the account (evidence doc section 4; ADR-043). Funnels, held handles, job object, quarantine.
5. **Switch-on path** (ADR-045 Decision 6 and 2026-10-09 table; design overview section 12): ACL stage, tool-setup stage, real-mode verify (checks 2-25), one watched dispatch, flag edit, then deleting the nginx quarantine.

### (e) Open questions and the observable that closes each

| Question | Observable that would close it |
|---|---|
| Does the coder's toolchain run under the account itself? | LA runs `tools/probes/containment_arms/arm_a_operator.cmd` (the report names it); read the payload outcomes. |
| Does layering a write-restricted token on the account break the coder's tools? | A layered run on the account passes the same payload; git-bash result is the key line. |
| Is git-bash needed by opencode, or does it have a working fallback shell? | opencode run against the model in any confined setup (never run: model endpoints were down). |
| Does the WFP block hold beyond seconds, across reboot, IPv6, UDP, DNS, Bitdefender update? | Persistent filter build (#1682) plus a long-hold run (arm 2) and reboot run (arm 3), both listed NOT RUN in `containment-evidence-2026-10-05/ARMS_HANDOFF.md`. |
| Does a newer Windows build or MXC release add host-loopback to the process container? | `wxc-exec --probe` reports `baseContainerSupportsIngressHostLoopbackAllow: true` (currently false; the 0.9.0 notes name KB5124010, not installed here per the MXC study). |
| Does the identity-less loopback proxy in MXC main (PR #1406) work for the coder? | A run of MXC main's proxy mode with opencode's HTTP client (untested). |
| Is the dispatch orchestrator elevated? | A live token read (flip blocker 0; ADR-045 amendment; "inferred not elevated" and "probably elevated" are both unmeasured). |
| Does the separation rule (network rule singling out a fully restricted token) work unscoped, over IPv6, UDP? | A run without the app-scope; not run by choice (would expose the LA's traffic). |
| Why did `C:\Windows\Temp` change, and what is the build's default? | Reproduce the candidate mechanism (#1695 mutation test) or find the primary-source default (#1742). |
| Has the July MXC re-check trigger fired? | Compare the MXC README warning block and schema version at v1.0.0 with the July wording (see Gaps; a main snapshot at `C:/blarai-spike-1740-mxc/build1406/src-main/` had no such warning text in its README, which I did not verify at the v1.0.0 tag). |
| Is the speed of a confined model server equal to unconfined? | A cold-gated A/B (thermal zone at or below 72 C per generation); not run (C6a). |
| Can the 14B plus draft pipeline run in a confined account? | A run of the production pipeline in the throwaway account (C6e). |

### (f) Decisions

Made:
- LA 2026-07-10: Decision 1(b), accepted egress gap, keep Bitdefender (#787 c.1574; #775 c.1653).
- LA 2026-07-11: defer the flip (#775 c.1808); the bound lapsed.
- LA 2026-10-04: go-ahead for the raw WFP test (#1671); a WSL-hosted third-party sandbox was not adopted for the Windows-native coder (#1669).
- LA 2026-10-05: narrow (not accept) the coder's `projects` grant (#1678 c.3892); reopen the Governator venture (ADR-049).
- LA 2026-10-09: flip with the egress gap accepted (#775 c.3901); remove NginxGateway (#1695 c.3962, c.3969); extend check 25 (#775 c.3972).
- Session: all design choices in ADR-045 (funnels, job object, handle-based stamping), the #1740 study design.

Waiting for the LA:
- The switch-on ceremony and re-recording the egress-gap acceptance for the go-live (ADR-045 header).
- Whether to add a write-restricted token layer, or adopt anything else (#1740 recommendation).
- Run arm A (the dedicated account on the payload).
- #1742 (restore `C:\Windows\Temp` default?) and #1743 (the leftover Codex accounts).
- The coder's lack of an MCP browser tool, and its use of machine-wide Python (#775 c.3967/c.3971).
- Adoption of ADR-046 (third account).

### (g) Tickets (numbers from the cited files; ticket text not read)
#775 (tracking home, open) · #787 (original decision) · #1671 (WFP spike, closed) · #1682 (persistent egress block, open) · #1686, #1678, #1692 (permission leaks) · #1689 (third account) · #1691 (fused-leg flip blockers) · #1694, #1711, #1712, #1713, #1714, #1715 (follow-ups) · #1695 (nginx removal, boot-surface check) · #1669 (sandbox watch) · #1670 (guest-fit spike, no result) · #1739 (ADR-045 amendment) · #1740 (this study) · #1742, #1743 (machine findings) · #1693 (Governator scoping) · #1549/#1590 (feasibility, cancellation).

### (h) Raw sources and where they are
- In repo: `docs/research/containment-evidence-2026-10-05/` (scripts as-run and hardened, result JSON, README, `CHANGES.md`, integrity test `tests/security/test_containment_evidence_bundle.py`); `docs/research/windows-containment-comparison-2026-10/` (fixtures, arms D/B/C/E JSON, effective-access inventories, workstream-0 notes, MXC library study); probe code `tools/probes/containment_arms/`; copy of timings in `docs/performance/containment_probe_2026-10-10/` (a copy of `summary-phase2.md` is there); `PERFORMANCE_LOG.md` entries dated 2026-10-10 and 2026-10-11.
- Outside the repo (existence checked, contents not opened except where stated): `C:/Users/mrbla/blarai-research-data/` (`wfp-spike`, `confined-model-spike`, `ideation`); `C:/blarai-spike-1740-mxc/` (MXC downloads, studies, `video-brk262/transcript.txt` which I read around 10:31 to 13:05 and 16:52 to 18:06); `C:/blarai-spike-1740` (throwaway fixtures); `C:/Users/mrbla/agentic-setup` (the fleet scripts: `docs/fused-leg-operator-uses.md` exists, not read; not backed up in this repo); `C:/Users/mrbla/governator` (exists).
- Ticket comments (Vikunja) hold several primary records (for example #775 c.1654 raw check output). Not read.

---

## 3. Topic card: Isolating untrusted input

### (a) The question
How do we parse hostile bytes (web pages, images, pasted content) so that a flaw in the parser cannot reach BlarAI's keys, databases, GPU pipeline or network?

### (b) Current answer and status
**Decided as design; partly live.**
- Hostile HTML is parsed only inside a network-less Hyper-V Alpine guest reached over AF_HYPERV vsock; cleaned text returns to the host. Decided by LA 2026-06-05 (roadmap Decision 3, hybrid topology) and recorded in `docs/adrs/ADR-030-Cleaner-v1-Guest-Homed-Ingest-Pipeline.md`. The guest has zero network adapters and the launcher refuses to start the VM if one appears (`verify_vm_zero_nic`, ADR-030 section 8).
- The guest parser is **provisioned and proven end to end** (`docs/security/guest_parser_provisioning_record.md`: round trip 2026-06-12, port 50001) but **dormant at rest**: a normal launcher boot never starts the guest parser (`_maybe_start_guest_parser` runs only under `--go-live`, which overrides `launcher/config/default.toml` `[guest_parser] enabled = false`; the file read on main still shows that default). The trust-spine claim register row 6 marks the URL-ingest switch-off as DESIGN-INTENT with no go-live runbook.
- The guest oracle (test runner for the fleet) is **live** since the LA-supervised ceremony of 2026-07-08 (`docs/security/guest_oracle_provisioning_record.md`, port 50002; `guest_oracle_enabled = true` in `services/assistant_orchestrator/config/default.toml`, verified).
- Untrusted image decoding is **not** isolated: ADR-022 (Proposed, deferred) leans to "decode in a sandbox" when images arrive from the network.
- Whether any MXC-listed backend beats the VM design is **open and unmeasured**.

### (c) Studies, measurements and decisions

| Date | Document path | What it found, one plain line | Grade | Confidence note |
|---|---|---|---|---|
| 2026-06-05..11 | `docs/adrs/ADR-030-Cleaner-v1-Guest-Homed-Ingest-Pipeline.md` | Parse hostile HTML in the NIC-less guest; the host fetches through the single egress door and never parses; a NIC'd guest was rejected (a second egress path, a beachhead). | R | Authoritative design. |
| 2026-06 | `docs/research/trafilatura_supply_chain_vetting.md` | The HTML extraction library's most important mitigation is guest-homed parsing; its core C parser has a long vulnerability history. | S | Cited in ADR-030 section 4. |
| 2026-06-11/12 | `docs/security/guest_parser_provisioning_record.md`; `docs/security/uc003_live_fetch_proof_2026-06-12.md`; `docs/security/uc003_markdown_verify_2026-06-13.md` | Parser provisioned by CD image (the file-copy channel is dead on kernel 6.12.74); vsock round trip proved live; markdown extraction verified in guest with no egress. | M | Procedure requires a manual console step. |
| 2026-06 | `docs/runbooks/vm_lifecycle.md`; `FIELD_NOTES.md` section "Hyper-V / VM operations"; lessons 126, 127 in `LESSONS.md` | VM operational facts: re-grant per-VM ACLs after an in-place ISO rebuild; busybox needs `mount -t iso9660`; a boundary runbook is a hypothesis until a console runs every line. | M | Operations knowledge. |
| 2026-07-08 | `docs/security/guest_oracle_provisioning_record.md` | A second guest service (pytest/hypothesis runner) provisioned and live on port 50002 with a fail-closed supervisor. | M | Advisory-only, never changes a job verdict (as stated in the July evaluation, section 3.3). |
| 2026-07-10 | `docs/performance/coder_in_vm_memory_2026-07-10.json`; threat model 5.4 | Memory budget for the coder inside the same guest cleared (27.5 GB peak). | M | Coder-in-VM speed unknown. |
| 2026-06-04 | `docs/adrs/ADR-022-Isolate-Untrusted-Image-Handling.md` | No confidential GPU boundary on this silicon (TDX Connect / TDISP unavailable); Option B (decode-in-a-sandbox, VLM stays host-side) is the lean. | R + M (Gate 4 finding, cited) | Proposed, deferred; trigger is images arriving from the network. |
| 2026-07-20 | `docs/research/encryption-and-isolation-evaluation-2026-07-20.md` section 3 | MXC cannot replace Hyper-V: a Hyper-V guest cannot reach the host GPU (ADR-041/ADR-011), MXC has zero vsock/AF_HYPERV support in its 1,215-file tree, and its README then disclaimed being a security boundary. | S | Verified in a second pass; found the Alpine guest was not dormant (a corrected claim). |
| 2026-10-11 | `docs/research/windows-containment-comparison-2026-10/mxc-library-study/studies.json` (study 1, `fit_for_blarai`) | For parsing unbounded input: Hyperlight and NanVix (micro-VMs, experimental), WSLC (Linux containers, stable) and Windows Sandbox (heavy, singleton, experimental) are separate-kernel designs; none offers vsock; data goes by mounts, copies or stdout. | S (docs, read at the tag) | No latency measured, no container run; third-party licences not read. |
| 2026-10-11 | `.../mxc-library-study/skeptic-checks.json` | Skeptic added: Hyperlight's roadmap includes host-proxied allow/block lists for sockets; WSLC shares one WSL VM and daemon across containers, a weaker analogue to a private VM. | S | |
| 2026-10-11 | `docs/research/windows-containment-comparison-2026-10/sources/ms-build-2026-brk262/transcript.txt` (outside repo) | Microsoft's talk: one sandbox per agent action, isolation "proportionate to the risk and proportionate to the action"; backends from processes to micro-VMs to cloud PCs. | V (talk transcript) | Product direction, not shipped files (the #1740 report says so). |
| 2026-09-17 | `docs/research/runtime-action-governance-product-feasibility-2026-09-17.md` Seam 7 | Windows Sandbox was disabled on this machine; Hyper-V present with BlarAI's VM. | M | Oct study: `WindowsSandbox.exe` absent. |
| ongoing | `docs/security/capstone_explainers/host_guest_secure_dataflow.md`, `docs/security/explainers/host_guest.html`, `docs/learning/lessons_deck/` | Plain-language explainers of the host-to-guest flow. | R | Not read by me beyond existence. |
| ongoing | `docs/governance/trust-spine-claim-register.md` rows 6, 11, 20 | Row 20: guest isolation LIVE structural (ADR-007; vm_lifecycle runbook). Row 11: the armed socket guard allows only loopback and the VM channel. | S | |

### (d) Layers of zoom

1. **Why isolate input.** Parsers are the historically bug-rich surface (images, HTML). A flaw would run inside the process that holds the unsealed key and GPU pipeline (ADR-030 section 3; ADR-022 context).
   1. **Isolation scaled to the input** (CLAUDE.md principle 9, recorded in the design-overview-adjacent docs): unbounded attacker-shaped input parses in the guest; a capped, authenticated response parses host-side.
2. **The chosen shape.**
   1. Host fetches through the single policy-gated egress door (`guarded_fetch.fetch_external`), never parses.
   2. Bytes cross AF_HYPERV vsock to the guest; extraction only (the library's own fetch functions are banned by a static-scan test, ADR-030 section 4).
   3. Only cleaned text returns; it lands as a pending record; operator approves.
   4. Guest holds no secrets; no NIC (structurally fail-closed, ADR-030 3a).
3. **Details that decide it.**
   - Frame cap: the vsock frame is 64 KB so chunks are 45,000 bytes (git log: Stage C parse channel).
   - Python version bridge: the runtime venv is 3.11 which lacks `socket.AF_HYPERV`; a 3.14 helper reaches the guest (`launcher/config/default.toml` lines 74-78).
   - Channel facts: Copy-VMFile dead on kernel 6.12.74 (error `0x800710DF`); CD image is the proven channel.
4. **Alternatives found.** A NIC'd guest that fetches and parses (rejected 2026-06-11); host-side parsing first (rejected); decode-in-a-sandbox for images (ADR-022 lean); the MXC backends (section c).

### (e) Open questions

| Question | Observable |
|---|---|
| When is the guest parser switched on? | A controlled activation session and a go-live runbook (none exists per claim register row 6); `enabled = true` after an LA-present ceremony. |
| Does any MXC backend (Hyperlight, NanVix, WSLC, Windows Sandbox) parse BlarAI's formats safely and as fast as the Alpine guest? | A measured run per backend on the same parsing payload; startup latency recorded (none exists). |
| Could the image decoder (ADR-022 Option B) use an AppContainer-class process, where no GPU is needed? | A decode-only probe under AppContainer or MXC tier 1; the #1740 payload shows readable-copy Python starts, loopback not needed. Never tried. |
| Is the stale threat-model row on the guest oracle fixed? | `PHASE1_DISPATCH_THREAT_MODEL.md` line 304 still says "currently dormant (triple-gated)" (the July evaluation said it was stale and ticketed it; I did not check the ticket). |

### (f) Decisions
Made: roadmap Decision 3 hybrid topology (LA 2026-06-05); NIC-less guest and one egress door (LA 2026-06-10/11); guest oracle go-live (LA 2026-07-08); host-mode default deployment (config). Waiting for the LA: activating the guest parser; ADR-022 timing; whether MXC enters at all (July trigger plus the October evidence).

### (g) Tickets
#655 (Cleaner program, Stage C) · #615 (AF_HYPERV addressing) · #657 (VM stop-on-exit) · #662 (guest deploy channel) · #744 (guest oracle) · #562 (ADR-022) · #788 (lazy VM start, from the July evaluation) · #1670 (guest-fit spike for Landlock, open, no result) · #1740.

### (h) Raw sources
In repo: the provisioning records under `docs/security/`; `phase2_gates/evidence/vsock_validation.json` is cited in the parser record (path not checked by me); `build/guest_cd/` scripts are cited (not checked). Outside: the MXC downloads under `C:/blarai-spike-1740-mxc/`.

---

## 4. Connections (all [PROPOSED]; each cites two real documents; hypotheses are labelled)

1. **[PROPOSED] Three-account model (ADR-046) + WFP loopback finding (C7/C8).** `docs/adrs/ADR-046-Three-Account-Model-Confined-Inference-Service.md` plans an inference account with "no network at all" and one local channel. `docs/research/account-level-containment-evidence-2026-10-05.md` C8 shows a block without the loopback permit also cuts the local request (error 10013). Idea: the `blarai-model` account needs a block with an inbound-side design, not the coder's permit; the arm-1 pattern (permit-on versus permit-off pair) is the ready-made toggle test for it. Hypothesis: the listener direction needs a different layer than ALE_AUTH_CONNECT (filters are outbound-connect only, C3b).
2. **[PROPOSED] ADR-046 + MXC loopback finding.** The coder reaches its model over `127.0.0.1:8099/8000`; MXC's tier 1 refuses host-loopback on this build (`windows-containment-comparison-2026-10-10.md` item 3) while the dedicated account with a WFP permit succeeds (evidence doc C7). The service-account pattern in ADR-046 (a model server in its own account, clients over one channel) is the shape that sidesteps loopback limits in container designs. Idea: a named pipe with an ACL naming client SIDs (ADR-046's other channel option) works under AppContainer-class containers without the loopback exemption. Hypothesis: not tested; named pipes are listed as a bypass class "shared named pipes" for AppContainer in the study.
3. **[PROPOSED] Jev "second judge" idea + the coder containment flip.** `docs/research/jev-policy-agent-ideation-2026-10-04.md` scenario C reads the model's own probability to send a low-confidence ALLOW to ESCALATE; `docs/design/CODER_CONTAINMENT_DESIGN_OVERVIEW.md` section 6 shows the containment design has no equivalent "unsure" outcome (checks are binary). Idea: a probability-gated escalation (#1672) as a pre-filter for what the fused leg is allowed to start, keeping the OS layer as the lock and the judge as an early warning. Caveat: Jev's 9B evidence was corrected twice (6 informative rows, not 10); it is a reason to run the experiment, not a finding.
4. **[PROPOSED] Jev "small questions combined in code" + MXC audit mode.** Jev scenario D (narrow yes/no questions, most restrictive wins) and MXC audit mode (`mxc-library-study/studies.json` study 3: seeds a grant list from a real run but over-grants because protections are off) are both "let a machine propose, let code narrow". Idea: audit mode's exact-path list as input, a deterministic reviewer (allowlist diff against a fixed expected-folder list, which study 3 itself suggests) as the narrowing step. Both documents already say a person or code must narrow; the connection is that they describe the same pattern.
5. **[PROPOSED] WFP raw-filter findings + the egress door design.** The WFP spike's shape (block everything for an identity, permit loopback) is the same shape as the runtime kill-switch in `docs/adrs/ADR-020-Code-Enforced-Egress-Kill-Switch.md` (allowlist of loopback plus AF_HYPERV, all else denied). The runtime guard is in-process Python (`shared/security/egress_guard.py`, per trust-spine claim register row 11); a WFP block keyed to the account the app runs under would be an independent, OS-enforced second lock for the same rule. Principle: defence in depth requires independent locks (CLAUDE.md principle 3). Hypothesis: untested; the app runs as the operator, who has other needs on the network, so this is only natural for ADR-046's `blarai-model` account.
6. **[PROPOSED] AppContainer deny-entry finding + other deny-entry assumptions.** `windows-containment-comparison-2026-10-10.md` finding 1: a deny naming an AppContainer is ignored (12 of 12) while a deny naming a user still refuses. Anywhere else BlarAI reasons "we add a deny entry" is worth a look: ADR-045's worktree-root delete-child deny "binds a standard account only (an elevated token of the same user bypasses it, measured 2026-10-06)" (design overview section 8); the nginx quarantine "admin-only" folder (same doc section 10); the `ADR-045` provisioning stage's protected lists. Idea: a short "what deny entries actually bind" table, tested per token type. Hypothesis: the design overview's deny entries are aimed at standard accounts and may already be right; nobody has listed them together.
7. **[PROPOSED] MXC audit mode + the coder Definition of Done.** `docs/design/CODER_DEFINITION_OF_DONE.md` has no containment row (searched for the words "containment", "AppContainer", "WFP", "blarai-coder" - none found; row 15 only says where exercising the built site runs is a design decision, lines 1340-1343). MXC audit mode produces per-run access evidence ("denials.json", ETL trace). Idea: add a DoD row "the coder runs under containment and the verify suite is green" with `verify-coder-containment.ps1` checks 2-25 as its observable; rows must move only by measurement, which the check suite already supplies. This also answers the DoD's own rule that a capability is not LIVE until its observable has executed (row 11).
8. **[PROPOSED] Microsoft's "dynamic composition" / one-sandbox-per-action idea + BlarAI's single Policy Agent adjudication door.** The BRK262 transcript (`docs/research/windows-containment-comparison-2026-10/sources/ms-build-2026-brk262/transcript.txt`, 10:46 to 12:03) describes one container per action matched to policy, user consent and IT policy; the #1740 report says no shipped file implements that. BlarAI's equivalent is one adjudication door deciding every risky action (CLAUDE.md principle 5; `docs/adrs/ADR-044-Policy-Agent-Model-Path-and-Tool-Call-Arguments.md`). Idea: the verdict could pick the containment tier per action (Policy Agent says ESCALATE, so run it in a stricter container). July's evaluation already notes any MXC adoption could only be subordinate to the Policy Agent, never a second adjudicator (`encryption-and-isolation-evaluation-2026-07-20.md` section 3.4). Hypothesis: purely a design idea; the PA door and MXC use different decision inputs.
9. **[PROPOSED] Hyperlight / NanVix micro-VMs + the parsing VM.** Study 1 says both are hardware-VM designs with no network and read-only mounts, about 100 ms start for NanVix, python guests only (`mxc-library-study/studies.json`). ADR-030 requires a guest that holds no secrets, no NIC, and returns only cleaned text. Idea: a per-parse disposable micro-VM replacing a resident Alpine service would remove the persistent supervisor and CD-image provisioning pain (`guest_parser_provisioning_record.md` section 1) but loses vsock and the proven live round trip. Verification needed: do the guest libraries (the HTML extraction library and its parser) run there at all? Study 1 lists that as unknown.
10. **[PROPOSED] ADR-022 image decoding + #1740's AppContainer-class results.** ADR-022 Option B needs a sandbox for a decode-only step with a bounded RGB buffer back. The #1740 payload shows AppContainer/MXC tier 1 start Python from readable copies, have strict default-deny and no network by default (`phase2/summary-phase2.md`); the failures (git-bash, loopback to a model) are irrelevant to a decode step. Idea: image decode is a cleaner first customer for a container than the coder. Hypothesis: untested; PIL native library loading under an AppContainer is not checked.
11. **[PROPOSED] Lesson 236 + the landscape surveys.** `LESSONS.md` lesson 236 says assess containment at the OS layer. `docs/research/landscape-anthropic-agent-governance-2026-09-16.md` shows Claude Code's seam is hooks plus an OS sandbox for shell commands, and notes the self-hosted worker's file check "is a guardrail for the file tools only, not a sandbox; it does not constrain bash". Idea: the same distinction can be added as a column in the trust-spine coverage table (item 10 in `trust-spine-proposed-items-index.md`, ticket #1544): "enforced by OS" versus "enforced by a program".
12. **[PROPOSED] Trust-spine item 12 (audit chain verify on load) + the verify suite's "detector, not prevention" checks.** `trust-spine-proposed-items-index.md` item 12 and design overview checks 24 and 25 are both detectors that run only when something calls them. Pattern: a control that is only run by a verifier is evidence of state at that moment; consider whether the same boot-time "posture check" idea (item 3) fits check 25.
13. **[PROPOSED] July MXC re-check trigger + October evidence.** `encryption-and-isolation-evaluation-2026-07-20.md` section 3.4 re-keyed the trigger to two repository artifacts (README warning block removed or materially amended; non-alpha schema). The October studies read v1.0.0 closely but neither mentions the warning. A main snapshot at `C:/blarai-spike-1740-mxc/build1406/src-main/.../README.md` has no matching warning text (my search; not the tag). Idea: close the trigger in writing, on the MXC watch ticket. Hypothesis: the warning text may have moved to another file.
14. **[PROPOSED] Hybrid VM direction + the coder.** ADR-045 "Alternatives" and the threat model 5.4 keep a VM leg for cross-platform coder jobs (memory cleared 2026-07-10) while Windows-native jobs stay on the account. The #1740 finding that git-bash fails in every container but is not a problem inside a Linux guest (coder in Alpine uses a Linux shell) suggests the two blockers are Windows-specific; the VM leg avoids them. Not tested; the guest speed is the stated unknown. Also ties to the LA's re-visit trigger "the VM containment leg going live" (#775 c.1653), which would reopen the accepted egress gap.

---

## 5. Claims that have been corrected

| What was claimed | What replaced it | Where (and status) |
|---|---|---|
| The MXC release v1.0.0 is commit `c6f301d5` | Tag v1.0.0 is `7bf21024` (2026-10-06); `c6f301d5` is main, 20 commits later; earlier reads of docs were main | `windows-containment-comparison-2026-10-10.md` (the Microsoft MXC bullet); `mxc-library-study/README.md`. Fixed on main. |
| An AppContainer "starts with no access" | It starts with read access to Windows and Program Files through ALL APPLICATION PACKAGES | ADR-045 amendment 2026-10-10 (strike-through form on the branch earlier; text replaced on main after the replace-wrong merge). |
| NEP-0005 content "to be confirmed", and #1740 brief said open question 3 asks whether WFP can key to an identity | Confirmed from the raw file at `62bb720b`; open question 3 is uninstall and repair of persistent state; no question asks about identity keying | `ws0-nono-srt.md`; ADR-045 amendment. |
| (first draft) a restricted token "cannot be the network fence" | Withdrawn by independent review; measured: the fully restricted form can be singled out by a network rule; the write-restricted form cannot | `docs/journal_fragments/2026-10-10_1740-*.md`; report finding 2. |
| git-bash fails for one reason in all confined setups | Different recorded errors: named object in global namespace (AppContainer-class); "signal pipe, Win32 error 5" and `CreateFileMapping` access (restricted tokens) | `windows-containment-comparison-2026-10-10.md` finding 4; disposition rows consistency-3 and trace-1 FIXED. |
| (first phase-2 draft) no setup differed from the control in start times beyond its variation | No timing conclusion is drawn; times differ where a concurrent process applies a network rule | `docs/journal_fragments/2026-10-11_1740-*.md`; report section 2. |
| #1671 result is a "re-visit trigger MET" on #775 | New evidence, not a trigger the LA named | #775 c.3893/c.3894 vs c.3874 (the latter stands uncorrected per ADR-045 "Source disagreement"); design overview section 14.11. |
| #1671 "loopback OK" | The listener was a stub started by the script, not the live model; the permit's role was untested until arm 1 (C7/C8, 2026-10-09) | evidence doc C1b, C6g; #1671 c.3891. |
| 3 runs filtered for "hold 100 s" | The filters stood about 5 s at most; `hold_seconds` was the requested cap | evidence doc section 3. |
| #1689 c.3896: control ran "at the same time" | It started after Test B finished (16:02:18.9 vs 16:02:10.7) | evidence doc section 3; #1689 c.3897. |
| Throwaway account "could not write outside its folders" | It could write `C:\Windows\Temp` and `B:\models`; for `blarai-coder` today the claim is false | evidence doc C2b, C6f; disposition N2, P2. |
| ADR-046: "the feasibility spike has not run" | It ran 2026-10-05 | ADR-046 status line (amended 2026-10-09). |
| ADR-045: job-object design "in progress, not merged" | Merged 2026-10-05 as agentic-setup `3097116` | ADR-045 amendment 2026-10-09. |
| Orchestrator elevation: "inferred not elevated" (ADR-045) / "probably elevated" (agentic-setup doc) | Neither measured | ADR-045 amendment; design overview section 14.4. |
| Coder "last logon 2026-08-14" | Last logon 2026-10-05 00:00:26; the 08-14 logon is unexplained but superseded | `preflight/775-preflight-2026-10-05.md`. |
| "Check 25 is not covered for ordinary programs' working folders" | LA decided to cover (build in progress at the time) | design overview 14.6; #775 c.3972. |
| Jev 9B: "the family that ALLOWs the two dangerous cases" and 10 of 10 wrong ALLOWs below 0.75 | Retracted; population recomputed to 6 informative rows, all below 0.75 | `jev-policy-agent-ideation-2026-10-04.md` (corrections visible in the file). |
| (July) "the Alpine guest is dormant infrastructure" | The guest oracle is live; VM Off means idle until needed (lazy start) | `encryption-and-isolation-evaluation-2026-07-20.md` section 3.3. |
| (July) Hyperlight "Network: None" per its integration plan | Source says network policies are supported via host proxy; at v1.0.0 docs say rejected at preflight, roadmap to filtered sockets | evaluation 5c row 3; skeptic-checks.json. |
| The claim "known to run the whole job" | **Not found in the files I searched** (docs, research, journal fragments, primer HTML); not verified. | Not verified. |

---

## 6. Gaps in the knowledge base itself

**A. Folders holding relevant knowledge that `docs/INDEX.md` does not link or mislabels** (INDEX read on main):
- `docs/reviews/` (144 top-level files; 195 recursive; the dispositions for this whole cluster): no row in INDEX.
- `docs/research/`: INDEX row says 16 files; it holds 61 top-level files (303 recursive). None of the containment studies, the Jev note, the landscape files or the trust-spine index is named.
- `docs/adrs/`: INDEX says "34 ... ADR-005 ... ADR-038"; the folder holds 46 ADR files up to ADR-049, including 045, 046, 049 for this cluster. (The decision register does index them.)
- `docs/security/`: INDEX says 54 files; I counted 61 recursive. INDEX names the guest-parser/oracle provisioning records generally but not `capstone_explainers/host_guest_secure_dataflow.md`, `explainers/host_guest.html`, or `post_capstone_2026-07/` (threat model, research brief) individually.
- `docs/journal_fragments/`: INDEX says 6; the folder holds 27 files; the three #1740/#1739 fragments are not folded into `BUILD_JOURNAL.md` as far as I saw.
- `docs/reference/`, `docs/handoffs/` (INDEX says gitignored, 0 files), `docs/reports/` (INDEX says 38; fleet-process history; I found no containment content there by search of the keyword set: the search returned none for reports/), `docs/upstream/`, `docs/learning/`: no containment knowledge found except `docs/learning/lessons_deck/` mentions of the VM (act JSON files; not read).
- `docs/ledger/`: 2026-06 sprint-close entries mention the guest and vsock (`20260607_180000_sprint17_scr_boot-cluster-close.md`, `20260607_224258_sprint17-onchip-close.md`); no containment entries for October that I found.
- `docs/design/`: INDEX row names only `CODER_CONTAINMENT_DESIGN_OVERVIEW.md`; fine for this cluster.
- `docs/performance/`: the 2026-10-10 containment copy is present, but the earlier #1671 and #1689 measurements (WFP spike, confined 4B speed 3.7-8.5 tok/s) have no `PERFORMANCE_LOG.md` entry that I found (searched for WFP, 1671, 1689, "confined" in the log); only the #1740 probe entries and the July coder-in-VM memory JSON exist. CLAUDE.md rule 6 says unrecorded results are incomplete.

**B. Other gaps**
- No containment row in the coder Definition of Done (see Connection 7).
- Raw primary data outside the repo: ticket comments (Vikunja), `C:/Users/mrbla/blarai-research-data/`, `C:/blarai-spike-1740-mxc/` (MXC downloads and the BRK262 transcript), agentic-setup scripts and `docs/fused-leg-operator-uses.md`. The evidence bundle's scripts need agentic-setup helper scripts that are not bundled (`containment-evidence-2026-10-05/README.md`).
- ADRs not linked to their measurements: ADR-030 and ADR-022 cite no measurement of the guest parser's latency or throughput; ADR-046 links the evidence document but its status text was stale until 2026-10-09; ADR-049's header still says the evidence doc is "pending merge" while it is on main now (text as read).
- Studies with no disposition record I found: the four landscape surveys (documentation-level, not reviewed in the files I read), `encryption-and-isolation-evaluation-2026-07-20.md` (has an internal two-pass verification but I found no `docs/reviews/` file for it), the feasibility study and appendices, the Jev note (it carries visible corrections), the MXC library study (skeptic checks serve as its review).
- Stale statements that still sit in documents: `PHASE1_DISPATCH_THREAT_MODEL.md` line 304 (guest oracle "currently dormant") and section 5.1 (per-SID firewall block, pre-Bitdefender); `trust-spine-proposed-items-index.md` item 3 says #977 "open since 2026-07-19" while the claim register says #977 was closed 2026-09-20 by #1586; the 17 items in the design overview "not verified" list. Design overview section 14 lists 11 source disagreements, some fixed since.
- The July MXC re-check trigger has no written evaluation (Connection 13).
- Items I could not verify: what the Vikunja tickets say now; whether `containment` still reads `off` today (I relied on docs dated 2026-10-09 and the ADR); the contents of `phase2_gates/evidence/vsock_validation.json` and `build/guest_cd/`; the full text of `ws0-*` files, the primer HTML, `docs/security/capstone_explainers/host_guest_secure_dataflow.md`, `docs/learning/lessons_deck/`, ADR-007, ADR-041, ADR-042 (heads only), design overview lines 655-764. (Existence on main confirmed for the dispositions, `arm_a_operator.cmd`, `phase2_gates/evidence/vsock_validation.json` and the bundle test; their contents beyond what is cited were not read.)
