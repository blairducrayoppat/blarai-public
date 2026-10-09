# R5 — Threat model, maintenance and churn, performance budget, and the first user

Feasibility study #1549 (runtime action governance for AI agents as a Windows PC product), questions Q10, Q11, Q12, Q16.
Written 2026-09-17, 09:45–10:20 EDT (America/New_York, machine clock; the harness date is UTC).

**Conditions for every number produced here.** Windows 11 Pro 25H2, build 10.0.26200.9457 (this build is exactly what Microsoft
lists for 25H2), Intel Core Ultra 7 258V, 31.3 GB RAM, uptime 16 h 08 m at the time of measurement. Shell: **NOT elevated**
(the earlier probe agents ran elevated; one measurement below failed for that reason and is recorded as not probed).
Python 3.14.3 (`C:\Python314`). **The machine was not idle:** Bitdefender Total Security 27.0.60.341 active (9 processes),
several other `claude` sessions and ~20 `node` processes running. Every figure carries that load.

**Grades.** **MEASURED** = ran here, command and output recorded. **REPORTED** = read in documentation, a vendor advisory, a CVE
record or shipped source, with the URL and its date. **DERIVED** = computed from two or more recorded figures; the arithmetic is
shown. **[PROPOSED]** = a design recommendation of mine, not a finding.

**Re-used evidence.** The measured figures from the sibling probe reports are used as given and are not re-measured here:
`reports/P1-hooks.md` (Claude Code hook payload; 86.4 ms median hook process; fail-open on hook exit 1; `--safe-mode` skips hooks),
`reports/P3a-network.md` (a Windows Firewall rule accepted and never enforced because Bitdefender owns the firewall),
`reports/P3b-os.md` (TPM signing latency; Event Tracing for Windows volume; AppContainer denials),
`probes/p2/timing-run*.txt` (local Model Context Protocol proxy overhead).
New measurements made for this report: the release-churn tally (`probes/r5/churn2.py`), the resident-governor inter-process
latency probe (`probes/r5/pipe_latency.py` and its control `pipe_latency2.py`), and the always-on-agent memory census.

---

## Outcome first — the three threats most likely to bite a one-person governor product first

1. **The governor is skipped, not defeated.** Every agent seam measured is *cooperative*. On this machine, Claude Code's
   `--safe-mode` ran a command the governor had been configured to deny, and the hook was never invoked at all
   (P1 run e1, MEASURED); a hook that exits 1 is treated as "no opinion" and the command runs (P1 run d2, MEASURED). Nothing in
   the seam tells the person their governor was bypassed. A product whose whole promise is "every action is governed" ships, on
   day one, with a documented one-flag exit that leaves no trace in the governor's record. **This is a product-integrity problem
   before it is a security problem**, and the fix is not a stronger lock — it is a *liveness* design: the governor must detect its
   own absence (per-agent canary, heartbeat, recorded gap) and say so, because the agent will not.

2. **The governor inherits the exact bug class that has hit every antivirus vendor.** A privileged Windows service that performs
   file operations in a user-writable directory is the single most-exploited shape in endpoint security software. Eight or more
   CVEs from 2022–2026 across Bitdefender, Avast/AVG, ESET, Norton, Malwarebytes, K7 and Microsoft Defender share it; one of them,
   **CVE-2026-41091** in Microsoft Defender, is in CISA's Known Exploited Vulnerabilities catalogue (added 2026-05-20, remediation
   due 2026-06-03) — Microsoft's own security agent, exploited in the wild, by link following. A solo founder writing a SYSTEM
   service that writes a hash-chained record into a directory the user can reach is walking into that shape deliberately.

3. **The update channel is the highest-value target and the weakest link a solo founder has.** A governor is, by construction,
   privileged software installed on machines that hold source code and credentials. SolarWinds (CISA ED 21-01, 2020-12-13:
   the adversary had "covert access to the build process") and 3CX (CISA alert, 2023-03-30: the desktop app "was trojanized")
   show that the signature proves *who built it*, never *what was built*. One person with one signing key and one CI account is
   exactly the shape both of those attacks defeated. Signing alone is not an answer; provenance that the build platform
   attests to (SLSA Build L2/L3) and an update-metadata framework with offline keys (TUF) are, and both cost calendar time
   before the first release, not after.

A fourth, which is not a security threat but will kill the product just as dead: **approval fatigue**. Little Snitch — the
canonical per-application connection-approval product — ships a "Silent Mode" whose stated behaviour is that "new connections are
automatically allowed at first" so the person is not interrupted (obdev.at, fetched 2026-09-17). A governor whose honest answer
to "how many prompts will I see?" is "many" has already lost; the design must make *not asking* the normal case.

---

# Q10 — Threat table

Reading the table: "Control in hand" means either a control in the product hypothesis that follows from measured evidence, or a
control BlarAI already ships, named with its path under `C:\Users\mrbla\BlarAI\`. "Gap" is what would have to be built and does
not exist in either place today.

| # | Threat | How | What it gains | Control in hand (hypothesis, or BlarAI path) | Gap — does not exist yet | Evidence / precedent (date) |
|---|---|---|---|---|---|---|
| 1 | **Injected agent removes the hook entry** | The agent is told, by injected content in a repository, web page or issue, to edit `~/.claude/settings.json`, `.claude/settings.json`, `~/.copilot/hooks/*.json` or `.github/hooks/*.json` and delete the governor's hook. All are ordinary user-writable JSON. | Total, silent loss of the pre-tool-call veto for that agent, from the next session on. | File-integrity watch on every adapter's config file with a signed expected-hash, plus the governor writing a "hook absent" record at each agent launch. BlarAI precedent for the record: `shared/security/audit_log.py` (hash-chained, sealed segments, `verify()`); for hardened file permissions: `shared/security/file_dacl.py`. | **Nothing in any agent notifies a third party that its hook list changed.** No agent exposes "which hooks are registered" to an outside process; the governor must read the files itself and can be raced. | Claude Code hook discovery and merge order, and `disableAllHooks`, documented at `https://code.claude.com/docs/en/hooks` (fetched 2026-09-17; "Only `disableAllHooks` set at the managed settings level can disable managed hooks"). Copilot CLI 1.0.3 loads every `**/*.json` under `.github/hooks/` and `~/.copilot/hooks/` — read from the shipped `app.js` (P1 §B). Cursor precedent for editing an AI tool's own trusted config: **CVE-2025-54136**, published 2025-08-02, CVSS 7.2, CWE-78 — a trusted Model Context Protocol config is silently swapped after approval (`https://github.com/cursor/cursor/security/advisories/GHSA-24mc-g4xr-4395`). |
| 2 | **Injected agent (or the person) launches the agent with hooks off** | `claude --safe-mode`, `claude --bare`, `claude --setting-sources user` (omitting the file carrying the hook), `"disableAllHooks": true`. | The governed agent runs completely ungoverned, with no error and no event. | Only *managed* settings survive (`C:\Program Files\ClaudeCode\managed-settings.json` or `HKLM\SOFTWARE\Policies\ClaudeCode`) — so the governor must install its hook as a managed policy, not a user setting. **But** Anthropic's own documentation says an administrator can edit the managed source, and the study machine's user is an administrator. | **A liveness check.** Nothing tells the governor that an agent started without it. The hypothesis's "coverage screen" is the answer and it does not exist: per-adapter canary tool call, missed canary ⇒ that agent is demoted to observed-only and the person is told. | **MEASURED, P1 run e1 (2026-09-17 02:58 EDT):** `claude -p … --safe-mode` ran `echo PROBE_DENY_ME`, output `PROBE_DENY_ME`, hook log empty — the hook never ran. `claude --help` text: `--safe-mode` "hooks … disabled … Admin-managed (policy) settings still apply". Managed-settings tamper note: `https://code.claude.com/docs/en/managed-settings`. |
| 3 | **Injected agent crashes the governor's hook** | Make the hook fail: delete its interpreter, fill the disk, corrupt its script, exhaust its timeout, or simply make it throw. | The action proceeds. The seam's error path is *allow*. | Fail-closed can only be reached by making the hook's own wrapper a tiny, dependency-free binary that returns `deny` on any internal error, and never a Python script that can fail to start. BlarAI's equivalent posture: `shared/security/egress_guard.py` (deny-by-default allowlist, `arm()`), `shared/security/dev_mode_guard.py` (raises when the unsafe combination is even *ambiguous*). | **The fail-open is in the agent, not in the governor**, so no governor-side code can close it. Only a *second, independent* lock (OS-level, e.g. AppContainer or a network chokepoint) closes it, and that lock is exactly what the developer's own coding agent cannot tolerate (P3b). | **MEASURED, P1 run d2:** hook exited 1 after logging; the command ran; result text "It printed: `PROBE_DENY_ME`". Same shape REPORTED for Copilot CLI 1.0.3 shipped code (hook error caught, logged, tool proceeds) and for Codex ("marks the hook run as failed … and continues"). OpenAI's own words: treat tool hooks as "a useful guardrail, not a complete enforcement boundary" (`https://learn.chatgpt.com/docs/hooks`). |
| 4 | **Injected agent points the client at the real protocol server** | The governor interposes as a local Model Context Protocol proxy by rewriting the agent's MCP config to launch the proxy instead of the server. The agent edits that config back to the original server command. | Every MCP tool call bypasses the proxy: no decision, no record. | Same file-integrity watch as row 1, plus the proxy writing a "server reached me" heartbeat so that silence is evidence. | **Server-side attestation.** Nothing lets a server refuse a client that did not come through the proxy. Microsoft's Windows on-device agent registry proxy does authentication/authorisation/auditing — **but has no third-party authoriser slot and is not on Claude Code's or Codex's path at all** (R1 §7). | R1-integration.md §7, from the Microsoft MCP overview (ms.date 2025-12-06, updated 2026-06-04) and the Ignite blog (2025-11-18). Config-rewrite precedent: **CVE-2025-54135** (published 2025-08-05, CVSS 8.5) — indirect prompt injection creates `.cursor/mcp.json` where none existed, because creating a dotfile did not require approval. |
| 5 | **Injected agent resets the model base-URL variable** | The governor interposes on the model server by setting `ANTHROPIC_BASE_URL` / `OPENAI_BASE_URL` / `OLLAMA_HOST` to a local proxy. The agent `set`s it back, or launches a child with the original value, or uses a config file that outranks the variable. | All model traffic, and any governance that depended on seeing it, is lost. | Enforce the redirection at the network layer instead of the environment: deny the agent's process direct egress and allow only the proxy. | **On a consumer PC the network layer is not available.** **MEASURED, P3a:** a per-program outbound Block rule was accepted by `New-NetFirewallRule` (`PrimaryStatus OK`), listed by `netsh`, logged as event 2097 — and produced **0 filters** in the Windows Filtering Platform; all 5+16+16 HTTPS requests returned 200, identical to baseline. Bitdefender holds 2176 filters and the top sublayer; Windows Firewall holds 18. | P3a-network.md §1 (probe 02:47–03:04 EDT 2026-09-17). Microsoft's own description of the ownership transfer: `INetFwProduct::get_RuleCategories` — categories "for which the third-party firewall wishes to take ownership from Windows Firewall" (ms.date 2018-12-05). |
| 6 | **Impersonating a governed agent (path spoofing)** | Copy or symlink a binary to the path the governor's rules name (`…\.local\bin\claude.exe`), or name a hostile binary `claude.exe` on a different path that a path-based rule also matches. Firewall rules, Event-Tracing receipts and image-path-based adapters all key on the path. | Inherits whatever the governed agent is allowed to do; or, in reverse, evades a rule written for the real one. | Identity by *signature plus caller handle*, not by path: for an inter-process request, `GetNamedPipeClientProcessId` then verify the image's Authenticode signature and publisher. **MEASURED here: that identity lookup costs 18.6 µs** — it is free. BlarAI precedent for signature-before-trust: `shared/models/weight_integrity.py`, `shared/models/manifest_signer.py`, `shared/security/verify_trust_root.py`. | **A per-process capability the OS enforces.** Windows application control (WDAC/AppLocker) decides only *whether code may run*, never *what an action may touch* (P3b, MEASURED: AppLocker has 0 rules here; WDAC enforces 4 Microsoft policies). Note also that WDAC signer rules "only work with RSA … ECC algorithms, such as ECDSA, aren't supported" (learn.microsoft.com, ms.date 2026-03-29). | P3b-os.md seam 7; Event-Tracing process-start event 1 v4 carries `ImageName` but **no command line** (MEASURED), so path is all a passive observer gets. |
| 7 | **Malware presents itself as an agent to inherit a lease** | After the person approves "allow this agent to write to `C:\src` for 30 minutes", another process connects to the governor's pipe/socket claiming that agent's identity, or a child process of the real agent inherits the lease implicitly. | Uses a human-granted approval it never earned, inside the approval's validity window. | Bind the lease to the verified caller (pipe client process id + image signature + session id), never to a name; refuse child processes unless the lease explicitly covers a process tree; expire leases in seconds, not minutes. BlarAI's per-turn envelope precedent: `services/assistant_orchestrator/src/egress_envelope.py`. | **Nothing in the agent tells the governor which process will execute the approved action.** The Claude Code PreToolUse payload has **no child-process information at all** (MEASURED, P1 verbatim payload), so the governor cannot pre-bind the lease to the executor. | Impersonation-through-IPC precedent: **CVE-2021-37852** (published 2022-02-09, ZDI-22-148) — ESET products let an untrusted process "impersonate the client of a pipe" to reach `NT AUTHORITY\SYSTEM`; ESET's own advisory frames the same issue as misuse of the AMSI scanning feature by a caller holding `SeImpersonatePrivilege` (`https://support.eset.com/en/ca8223-…`, 2022-01-31, updated 2022-03-01). **The vendor's prose and the CVE record describe the same bug differently — a reminder to read the artefact.** |
| 8 | **Social engineering the person into approving** | Indirect prompt injection: content the agent reads (a README, an issue, a web page, a file the agent was asked to summarise) instructs it to request an action the person will wave through, phrased so the approval card looks routine. | One approved dangerous action; often enough (exfiltration of one file, one credential, one push). | The approval card must show *provenance*: what the agent read before it asked, and whether any of it was untrusted. BlarAI ships exactly this shape — `shared/security/injection_scan.py`, provenance tagging and datamarking of untrusted content (CLAUDE.md security principle 7), `shared/security/ingest_staging.py`, and a presence check on escalation: `shared/security/escalation_consent.py` + `shared/security/hello_verifier.py` (Windows Hello `UserConsentVerifier`, **MEASURED `Available` on this machine**). | **The provenance is not in the event.** The PreToolUse payload carries no prompt text, no prior turns, no tool results (MEASURED). A governor that wants to say "this request follows content fetched from `evil.example`" must read `transcript_path` itself and parse a private format that changes release to release (see Q11). | **CVE-2025-32711** ("EchoLeak", published 2025-06-11, CVSS 9.3, CWE-74): "Ai command injection in M365 Copilot allows an unauthorized attacker to disclose information over a network." **CVE-2025-54135** (2025-08-05) chains indirect prompt injection to hijack an AI editor's context. |
| 9 | **Approve-always fatigue** | No attacker needed. The person is asked too often, learns the shape of the card, and approves reflexively — or turns the governor down to "allow all" permanently. | Every later attack succeeds at the prompt. | Ask only for exceptions: a profile that pre-decides the common cases, leases instead of per-call prompts, and a *budget* on prompts per hour with the governor demoting itself to observe-and-record rather than prompting past the budget. Measure the prompt rate as a shipped metric. | **A published, evidence-based prompt budget for agent governance.** None found; the closest shipped design is Little Snitch's Silent Mode. | Little Snitch product page (fetched 2026-09-17): Silent Mode — "New connections are automatically allowed at first" so the person is not interrupted and reviews later; also rule groups and profiles. The agents themselves ship the fatigue exit: Claude Code has `--dangerously-skip-permissions` and `--permission-mode bypassPermissions` (MEASURED in P1 runs a3/a4). |
| 10 | **A tampered profile file** | The governor's own policy/profile (which agent may do what) is a file on disk. Edit it, or replace it with one whose rules are wider, or roll it back to a permissive earlier version. | Persistent, silent widening of what every agent may do — the most valuable single edit on the machine. | Profile signed by a key the user's TPM holds and verified at every load; profile version and hash written into the record at every decision so a rollback is visible in the history; the profile's directory hardened by DACL. BlarAI precedent: `shared/security/tpm_signer.py` (non-exportable ECDSA P-256 in the Microsoft Platform Crypto Provider, **MEASURED working here**), `shared/security/file_dacl.py`, `shared/models/manifest_signer.py`, and boot-time verification (`require_signed_manifest=true`). | **Nothing yet ties the profile version to each decision record**, which is what makes a rollback detectable rather than merely preventable. | Same class as row 1's Cursor advisory (**CVE-2025-54136**, 2025-08-02) — the attack is *modifying an already-trusted configuration file*, which needs no new consent. |
| 11 | **The update and code-signing channel** | Compromise the build machine, the CI account, the signing key, or the update-metadata host. The product is privileged and auto-updating, so one bad build reaches every installation with a valid signature. | Everything. Code running as SYSTEM on every customer machine, signed by the vendor. | Reproducible builds + build-platform-attested provenance (**SLSA Build L2**: provenance "tied to that infrastructure through a digital signature"; **L3**: build runs isolated and "prevent secret material used to sign the provenance from being accessible to the user-defined build steps"). Update metadata under **TUF** roles with offline root keys and threshold signatures, defending rollback, freeze, mix-and-match and key-compromise attacks. Signing key in hardware or a cloud HSM — which is now mandatory anyway (CA/Browser Forum rule, since 2023-06-01, per R2-D). | **For one person, the separation SLSA L3 assumes does not exist.** There is no second human to hold the offline root, no separate release engineer, no four-eyes on a tag. That is a structural gap a solo founder must buy around (a hardware token kept offline, a second signing identity held by a trusted third party or an escrow, a published transparency log so customers can detect a build they did not expect). | CISA ED 21-01 (issued 2020-12-13): adversary had "longstanding, covert access to the build process that SolarWinds uses for Orion". CISA alert "Supply Chain Attack Against 3CXDesktopApp" (2023-03-30): the app "was trojanized". **CVE-2025-30066** (published 2025-03-15, CVSS 8.6, CWE-506): `tj-actions/changed-files` — existing version *tags* were repointed at a malicious commit, so pinning by tag was not pinning. SLSA v1.0 levels (`https://slsa.dev/spec/v1.0/levels`, retired in favour of v1.2). TUF attack list (`https://theupdateframework.io/docs/security/`, last modified 2024-10-12). |
| 12 | **A compromised adapter plug-in** | The product's per-agent adapters are the natural extension point. A malicious or hijacked adapter runs inside the governor's process (or as a child of it) with the governor's privileges and sees every action of every agent. | Governor-level privilege plus the complete stream of what the person's agents do — the richest surveillance position on the machine. | Adapters as *signed, out-of-process, least-privileged* workers: no in-process plug-in loading; each adapter in its own low-privilege process; the decision authority stays in the governor and an adapter may only *report* and *translate*, never *decide*. This is BlarAI's single-adjudication-door principle (CLAUDE.md principle 5) plus structural absence (principle 4) applied to extensibility. | **An adapter signing and revocation scheme** — who may publish an adapter, how it is revoked on the day it is found bad, and how a revoked adapter fails (closed, for that agent). | DLL/library-loading precedent inside an endpoint product: **CVE-2023-6154** (published 2024-04-01, CVSS 7.8, CWE-15/610) — a configuration setting in Bitdefender's `seccenter.exe` allows changing expected behaviour and "potentially load a third-party library upon execution" (`https://bitdefender.com/support/security-advisories/local-privilege-escalation-in-bitdefender-total-security-va-11168/`). Third-party-component precedent: CVE-2025-30066 above. |
| 13 | **Privilege escalation through the governor's own service** | The governor runs a SYSTEM service that writes a record, rotates log segments, quarantines files, or cleans temporary data — in directories a normal user can reach. A local low-privilege process plants a symbolic link, junction or hardlink, or races the check, and redirects that privileged file operation. | SYSTEM on the machine, delivered *by the security product*. | Every privileged file operation performed only in a directory with an ACL that excludes normal users; open with `FILE_FLAG_OPEN_REPARSE_POINT` and reject reparse points; never delete or copy by path in a user-writable location; impersonate the requesting user for user-scoped work. BlarAI precedent: `shared/security/file_dacl.py` (record segments are DACL-hardened at rotation — see `shared/security/audit_log.py`). | **A test that proves the lock works when engaged and fails when disengaged** for each of these file paths — BlarAI's principle 12 ("every control is tested off") applied to the governor's own filesystem surface. Nothing in the hypothesis has this yet. | The CVE table below — eight-plus instances of this exact shape across seven vendors, 2022–2026. |
| 14 | **Who governs the governor** | The person (or malware with the person's rights, or an agent told to) turns the governor off, uninstalls it, stops the service, or excludes an agent — and the governor's own record does not show it happened, because the governor was not running. | A clean-looking history with a hole in it. Worse than no history, because the history is trusted. | **Disabling must itself be a recorded, signed event, written before the stop takes effect**, plus a "gap" record on the next start naming the interval with no coverage. Model: Defender's tamper protection, whose Linux and macOS *audit* modes detect and report tampering without blocking, and whose events land in a `DeviceEvents` table with `ActionType == "TamperingAttempt"` (learn.microsoft.com, ms.date 2026-09-09). BlarAI's own boundary: **ADR-039 Coordinator Self-Governance Boundary** (`docs/adrs/ADR-039-Coordinator-Self-Governance-Boundary.md`, ACCEPTED 2026-07-11) — the system has *zero write path to its own governed core*; its self-directed output is advisory-only; structural severance, never vigilance. Applied here: **the governor must not be able to edit its own policy, and the agents it governs must have no write path to the governor's configuration or record.** | **A consumer equivalent of tamper protection.** Defender's version depends on an anti-malware Protected Process Light backed by a Microsoft-signed Early Launch Anti-Malware driver, available only to Microsoft Virus Initiative members (P3b, REPORTED). A third party cannot have it. The honest consumer design is *visible, recorded disabling*, not prevented disabling. | Tamper protection overview (ms.date 2026-09-09); P3b-os.md seam 8 on ELAM/PPL gating. |
| 15 | **The record — tamper** | Edit a decision line to change a deny into an allow, or to remove the argument that made it dangerous. | The audit trail — the product's core claim — becomes a liability: it now asserts something false. | **Hash chaining per record plus a hardware-signed chain head.** BlarAI already ships this: `shared/security/audit_log.py` — every record carries a SHA-256 over its own canonical fields concatenated with the previous record's hash; "Altering any field, deleting a record, or reordering records breaks the chain downstream and is detected by `AuditLog.verify()`"; sealed segments carry `file_sha256` and a `segment_signature`; `verify(full=True)` walks every gzip segment and raises at the first tamper. Signer: `shared/security/tpm_signer.py`. | Nothing missing in the mechanism; what is missing is the **verification habit** — a person-facing "verify my history" action that runs the chain check and shows a plain-language result (Q16 task 5 tests exactly this). | `C:\Users\mrbla\BlarAI\shared\security\audit_log.py` (read read-only 2026-09-17); `shared/tests/test_audit_log.py`, `shared/tests/test_tpm_record_signer.py`. |
| 16 | **The record — delete** | Delete the whole log, or truncate the tail, or delete a sealed segment file. Hash chaining detects an *edit*; a wholesale deletion of the newest records leaves a shorter but internally consistent chain. | Removes the evidence of the interesting window. This is the oldest anti-forensic move there is. | Periodic signed *heads* published outside the log itself (a signed head every N seconds carrying sequence number and chain hash), so a truncation is visible as a missing sequence range. BlarAI's segment index (`audit-segments.jsonl`, with `first_seq`, `last_seq`, `last_record_hash`, `segment_signature`) is that anchor for sealed segments. | **An anchor outside the machine's own filesystem** — and the product's "sends nothing off the machine by default" promise forbids the usual answer (a remote transparency log). The available substitutes: a signed head in a second, differently-permissioned location; a head sealed to TPM Platform Configuration Registers; a head the person can copy out deliberately. This choice is a **Lead-Architect-grade decision** (it trades privacy against verifiability), not a technical one. | Deletion-of-evidence is a standard adversary technique; the record's own design is the only control, since a local file can always be deleted by someone with the rights to delete it. |
| 17 | **The record — replay** | Re-present an old, validly signed approval (or an old signed head) as if it were current: the same allow decision, replayed to authorise a second, later action. | An approval used twice. | Monotonic sequence number + timestamp + a per-decision nonce inside the signed material, and the executor checking that the decision id has not been consumed. BlarAI's chain gives the sequence; the consumption check is the missing half. | **Single-use binding between a decision and an execution.** Nothing in the agent seams returns a decision id to be echoed back at execution time, so the governor cannot tell a first use from a second. | Derived from the measured payload shape: `tool_use_id` exists in the PreToolUse payload and *could* serve as the nonce — but the agent never presents it again to the governor, so the governor cannot observe consumption (MEASURED, P1 verbatim payload). |
| 18 | **The record — read** | The record is the most sensitive file on the machine: every file path, command line, URL and prompt fragment the person's agents touched. Read it and you have a map of their work and their secrets. | Reconnaissance that is better than the original data, because it is indexed and chronological. | **Born-encrypted** content with metadata-only where possible (BlarAI principles 6 and 8), field-level encryption (`shared/security/field_cipher.py`), data encryption keys in an envelope (`shared/security/dek_envelope.py`, `shared/security/provision_dek_keystore.py`), DACL hardening (`shared/security/file_dacl.py`), and decryption only on an explicit operator action gated by a presence check (`shared/security/escalation_consent.py`). | **A retention and redaction policy the person can understand and set.** Keeping everything forever, which is right for tamper-evidence, is wrong for privacy; the two must be reconciled explicitly (hash the argument, keep the hash forever, keep the plaintext for N days). | `shared/security/audit_log.py` retention model ("keep everything forever" in sealed segments, ADR-029) — the tension with privacy is visible in the artefact itself. |
| 19 | **Denial of service against the governor** | Flood the governor with decision requests; exhaust its handles, its disk, its pipe instances; kill its process repeatedly; or make one decision hang so the queue backs up. | If the governor fails *open*, everything is permitted. If it fails *closed* but noisily, the person turns it off — which is the same outcome by another route. | **Fail-closed with a bounded, honest degradation**: when the governor cannot decide, the adapter denies and says so in words the person can act on; a watchdog restarts the service; the record gets a "degraded" entry with the interval. BlarAI's shape: deny-by-default everywhere, `shared/timeout_registry.py` as the single registered source of every duration and watchdog. The measured latencies in Q12 give the headroom: ~17–30 µs per decision means a single-threaded governor has enormous margin before a flood is real. | **A back-pressure design that does not become an availability outage for the person's own work.** Untested. The honest risk: a governor that denies under load stops the developer's coding agent, and the person's fix will be to uninstall. | DoS precedents in the same software class: **CVE-2022-37981** (Windows Event Logging Service denial of service, published 2022-10-11) — the logging service itself is a DoS target; **CVE-2024-6768** (published 2024-08-12, CWE-1284) — a low-privilege user forces a Blue Screen via `CLFS.sys`. **CVE-2025-13032** (Avast/AVG sandbox kernel driver, CVSS 9.9) shows the flip side: the defensive driver itself is the crash surface. |
| 20 | **Time-of-check to time-of-use, between approval and execution** | The governor approves `python build.py` (or "write to `C:\src\a.txt`"). Between the decision and the execution, the file at that path is replaced, the symlink is repointed, the script's content changes, or the command's meaning changes because an environment variable changed. | The person approved one action; a different one ran. The record says the approved one ran. | Decide on *content*, not on *name*: hash the script at decision time and have the executor refuse if the hash changed; resolve paths to a file id and reject reparse points; keep the approval window in the tens of milliseconds, which the measured latencies make possible. | **The governor does not execute the action, so it cannot bind the check to the use.** This is the structural limit of a hook-shaped seam and the deepest gap in the whole hypothesis. **MEASURED demonstration:** one `Bash` event carries one command string; `python -c "import urllib.request; print(urllib.request.urlopen('https://example.com').status)"` passed the governor as an allowed `Bash` call and made a real network fetch — nothing in the event says "network" (P1 run c1). | The same weakness is the dominant CVE class in endpoint software: **CVE-2024-13944** (Norton Utilities Ultimate, published 2025-05-09, CWE-59 + CWE-367) is explicitly "leveraging a TOCTTOU (time-of-check to time-of-use) attack"; **CVE-2025-13032** and **CVE-2022-26522/26523** are double fetches (CWE-367) in Avast/AVG drivers; **CVE-2025-13818** (ESET Management Agent, published 2026-02-06, CWE-367) is an insecure temporary batch file. |

## Q10a — The CVE precedent set: what a privileged security agent gets wrong

The governor is, architecturally, an endpoint security agent: a privileged always-on Windows service that watches other processes
and writes records. Its bug distribution will look like theirs. These are eight vendors' worth of published, fixed, real cases
from 2022–2026. All records were pulled from the National Vulnerability Database REST API on 2026-09-17
(`https://services.nvd.nist.gov/rest/json/cves/2.0?cveId=…`); descriptions are NVD's, and vendor advisories are named where NVD
lists one.

| CVE | Published | Product | Mechanism (CWE) | Why the governor inherits it |
|---|---|---|---|---|
| **CVE-2025-7073** | 2025-12-10 | Bitdefender Total Security < 27.0.47.241 (the suite on *this* machine) | `bdservicehost.exe` deletes files from the **user-writable** `C:\ProgramData\Atc\Feedback` **without symbolic-link validation**; chained with a file copy on network events and a filter-driver bypass via DLL injection ⇒ arbitrary file copy and code execution as SYSTEM (CWE-59). NVD scores 8.8 (CVSS 4.0); the vendor's own advisory VA-12590 scores it **4.0** — the severity is contested, the mechanism is not. | The governor will write records, rotate segments and clean temporary files from a privileged service. Any one of those in a user-writable directory is this bug. Vendor advisory: `https://www.bitdefender.com/support/security-advisories/local-privilege-escalation-via-arbitrary-file-operation-in-bitdefender-atc-va-12590` (published 2025-12-10, last modified 2026-03-31; fix delivered by automatic update). |
| **CVE-2026-41091** | 2026-05-20 | **Microsoft Defender** | "Improper link resolution before file access ('link following') … allows an authorized attacker to elevate privileges locally" (CWE-59), CVSS 7.8. **In CISA's Known Exploited Vulnerabilities catalogue, added 2026-05-20, remediation due 2026-06-03.** | If Microsoft ships this shape in the platform's own security agent and it is exploited in the wild, a one-person product will too. This is the single strongest argument for an external review before release. |
| **CVE-2025-13032** | 2025-11-11 | Avast/AVG Antivirus < 25.3, **sandbox kernel driver** | "Double fetch in sandbox kernel driver … allows local attacker to escalate privileges via pool overflow" (CWE-367), CVSS **9.9**. | The isolation mechanism itself becomes the escalation path. Directly relevant: the hypothesis's isolation adapter (AppContainer) is user-mode and therefore avoids this — a real design advantage worth stating. |
| **CVE-2022-26522 / -26523** | 2026-05-08 (NVD) | Avast/AVG anti-rootkit driver `aswArPot.sys` < 22.1 | Double fetch in the socket-connection handler ⇒ kernel-mode code execution or OS crash (CWE-367 / CWE-400). | Any IPC handler that reads a request twice from shared memory. The governor's decision endpoint is exactly such a handler. |
| **CVE-2021-37852** | 2022-02-09 | ESET products for Windows | "allows untrusted process to **impersonate the client of a pipe**", escalating to `NT AUTHORITY\SYSTEM` (CWE-269). Reported 2021-11-18 by ZDI (Michael DePlante), fixed from 2021-12-08. ZDI-22-148. | The governor's decision channel is a named pipe. Impersonating the client, or failing to verify who the client is, is the same bug. (The measured 18.6 µs `GetNamedPipeClientProcessId` call is the cheap half of the fix; refusing to impersonate is the other half.) |
| **CVE-2025-67826** | 2025-12-22 | K7 Ultimate Security 17.0.2045 | "Insecure access to a **named pipe** allows unprivileged users to edit" — local privilege escalation on default installations (CWE-269), CVSS 7.7. Vendor advisory 2025-12-22. | The pipe's security descriptor is a one-line mistake with a SYSTEM-level consequence. A solo founder writing `CreateNamedPipeW(..., NULL)` — as the probe script in `probes/r5/pipe_latency.py` does — inherits the default DACL and must not. |
| **CVE-2024-13944** | 2025-05-09 | Norton Utilities Ultimate 24.2.16862.6344, `NortonUtilitiesSvc` | Link-following LPE: symbolic link + **TOCTTOU** ⇒ arbitrary code as SYSTEM (CWE-59 + CWE-367), CVSS 7.8. | The named instance of row 20's threat inside a shipped security product. |
| **CVE-2023-26088** → **CVE-2025-67905** | 2023-03-23 → 2026-02-17 | Malwarebytes (quarantine), then AdwCleaner < 8.7.0 | Symbolic link against a privileged delete of a user-controllable log path ⇒ SYSTEM (CWE-59). NVD explicitly calls the 2026 one "a related issue to CVE-2023-28892". | **The same vendor shipped the same bug class three times in three years** (CVE-2023-26088, CVE-2023-28892, CVE-2025-67905). A one-person shop with no structural control against this class will repeat it too — which is why the fix must be a *test that fails when the lock is off*, not a code review. |
| **CVE-2021-43768** / **CVE-2022-50971** / **CVE-2025-54569** | 2025-10-24 / 2026-06-19 / 2025-07-28 | Malwarebytes for Teams (`mbamservice.exe` **COM interface**); Malwarebytes 4.5 (**unquoted service path**); Malwarebytes Windows Firewall Control installer | Three more service-surface shapes: an over-permissive COM interface, an unquoted `ImagePath`, and a privileged installer. | All three are configuration mistakes in the *installer and service registration*, not in the product logic. A solo founder's installer is the least-reviewed code they will ship. |

**The pattern, stated plainly.** Across these twelve records the mechanisms cluster into four shapes, in order of frequency:
(1) a privileged process performing a file operation — delete, copy, log-write, quarantine-restore — in a location a normal user
can write, without link validation (6 of 12); (2) an inter-process surface — named pipe or COM — with a weak access control list
or willing impersonation (3); (3) a kernel driver double fetch (3, counting the two aswArPot entries); (4) loading a library or
resolving a path the attacker can influence (2). The governor's hypothesis touches shapes 1, 2 and 4 directly; it avoids 3 only
if it ships no kernel driver — which the Event-Tracing and AppContainer measurements in P3b say it can, at the cost of not seeing
what an anti-malware Protected Process Light sees.

## Q10b — What an independent security review and a disclosure process cost before a first release

**What I could and could not price.** Neither Cure53 nor Radically Open Security publishes rates (both fetched 2026-09-17;
Cure53 confirms it publishes *reports* "upon explicit request by the project maintainers, or the party that sponsored the
penetration test", and lists dozens from 2020–2026, but no prices). The Open Source Technology Improvement Fund publishes only
aggregates: **"20,000 Hours of Coordinated Security Review"**, **"800 Security Vulnerabilities Found and Patched"**,
**"$3,000,000+ dollars raised for security"**, over **100+ audits since 2016** (`https://ostif.org/audits/`, fetched 2026-09-17).

**DERIVED, and only an order of magnitude:** $3,000,000 ÷ 20,000 hours ≈ **$150 per hour**; $3,000,000 ÷ 100 audits ≈
**$30,000 per audit**; 20,000 ÷ 100 ≈ **200 hours (≈ 25 person-days) per audit**. The page does not say those three aggregates
cover the same set of engagements, so this is an anchor, not a quote. On that anchor, a first external review of a privileged
Windows service — threat model, the service's IPC and file surfaces, the installer, the update path, the record's cryptography —
is a **15–30 person-day engagement, roughly €20,000–€45,000**, marked **GUESSED**.

**What the money must buy, in priority order** (this ordering is [PROPOSED], and follows directly from the CVE pattern above):
1. The privileged service's file operations and the installer — shapes 1 and 4, which are 8 of the 12 precedents.
2. The decision IPC endpoint: its security descriptor, its caller verification, its parsing of an untrusted request — shape 2.
3. The record: chain construction, the signing boundary, what a deletion looks like, what the verifier actually proves.
4. The update and signing pipeline — the one whose failure is unrecoverable.
5. The approval user interface, adversarially: can a request be phrased so the card misleads?

**The disclosure process, which is cheaper than the review and is not optional.** Minimum viable, all [PROPOSED] except where a
source is named:
- A `SECURITY.md` and a published `security@` address, with a stated response target. A GPG key or a Signal number for reporters
  who want one.
- A stated coordinated-disclosure window. **CISA's own default is 45 days**: it "may disclose vulnerabilities as early as 45 days
  after the initial attempt to contact the vendor is made" if the vendor is unresponsive or will not set a remediation timeframe,
  regardless of patch availability (`https://www.cisa.gov/coordinated-vulnerability-disclosure-process`, fetched 2026-09-17).
  A solo founder who cannot answer within days will be disclosed around.
- A `security.txt` at the well-known path, and a decision about whether to become a CVE Numbering Authority or to route through
  one (routing is right for a one-person shop).
- **A tested emergency-release path.** The ability to ship a signed fix within the window is the binding constraint, and it is
  the same pipeline as row 11: if signing takes a week because a certificate must be re-validated, the disclosure window is
  already lost. Azure Artifact Signing's 3-day signing window and the 2026 CA-rotation incidents recorded in R2-D are the
  concrete risk here.
- ISO/IEC 29147 (vulnerability disclosure) and ISO/IEC 30111 (vulnerability handling processes) are the named standards for this
  process. **NOT VERIFIED:** `https://www.iso.org/standard/72311.html` returned HTTP 403 to this session, so the edition,
  date and scope are unread and are not asserted here.
- The EU Cyber Resilience Act's reporting duties are a *law*, not a courtesy, and bind the release date rather than following it.
  Those obligations are R4law's question, not scored here.

---

# Q11 — Maintenance, churn and support

## Q11a — MEASURED churn in the three agents' own release records

**Counting rule, stated before the numbers.** One "entry" = one release or one changelog section whose publication date falls in
**2025-09-17 to 2026-09-17 UTC inclusive**. An entry "touches" a category if its body text matches that category's regular
expression, case-insensitively: `hook` = `\bhooks?\b|PreToolUse|PostToolUse|PermissionRequest|UserPromptSubmit`;
`permission` = `\bpermissions?\b`; `sandbox` = `\bsandbox`; `approval` = `\bapprov`. A "bullet" = one changelog line beginning
`-` or `*` that matches. "Semantics-changing" = a matching bullet that *begins* `Changed|Breaking|Removed|Renamed|Deprecated|
Rename|Remove|Replace|Migrat`. Dates come from npm publish times for Claude Code, from the dated headings for Copilot CLI, and
from GitHub `published_at` for Codex. Script: `probes/r5/churn2.py`, run 2026-09-17 09:47 EDT; raw semantics-changing bullets in
`probes/r5/churn2_semantics_bullets.txt`. Source files were downloaded by the predecessor at 02:53 EDT the same day.

| Agent | Entries in window | Window covered | Touching hook | permission | sandbox | approval | **Touching ANY** | Matching bullets | **Semantics-changing bullets** |
|---|---|---|---|---|---|---|---|---|---|
| **Claude Code** (`@anthropic-ai/claude-code` CHANGELOG.md, dated by npm publish time) | 281 changelog sections (315 npm versions published in the window across all tags) | 2025-09-18 → 2026-09-16, **full** | 112 | 139 | 62 | 60 | **173 (61.6%)** | 629 | **37** |
| **GitHub Copilot CLI** (`github/copilot-cli` changelog.md, dated headings) | 171 | 2025-09-26 → 2026-09-16, **full** | 48 | 54 | 19 | 28 | **84 (49.1%)** | 242 | **2** |
| **OpenAI Codex CLI** (`openai/codex` GitHub releases) | 800 releases, of which **100 stable** and 700 pre-release | 2025-12-05 → 2026-09-17, **only ~9.4 of the 12 months** | 39 | 44 | 67 | 53 | **76 (76% of stable)** | 931 | **3** |

Notes that change how those numbers should be read:
- **Codex's window is incomplete.** Release pages 9–12 hit the GitHub API rate limit when the predecessor fetched them
  ("API rate limit exceeded for 68.179.189.47"), so the earliest release on disk is 2025-12-05. The Codex row understates a
  12-month count. Separately, **all substantive notes sit on the 100 stable releases** — the stable-only tally is identical to
  the all-releases tally on every category — so Codex ships roughly **8–14 stable releases a month**, each with long notes.
- **Claude Code is the fastest-moving surface by a wide margin**: 281 dated changelog sections in twelve months (≈ 23/month,
  peaking at 28 in 2026-06 and 2026-08), **61.6% of them touching hooks, permissions, sandboxing or approvals**, and **37 bullets
  that explicitly changed, removed, renamed, deprecated or migrated one of those semantics** — about **three semantics changes a
  month, every month, on the exact surface a governor plugs into**.
- The 37 are not cosmetic. Examples read verbatim from the dump: `2.1.214` — "Changed single-segment `dir/**` hook `if:`
  conditions to match only `<cwd>/dir`" (a matcher whose meaning changed); `2.1.3` — "Changed tool hook execution timeout from
  60 seconds to 10 minutes"; `2.1.212` — "Deprecated the Task tool's `mode` parameter (now ignored)"; `2.0.35` — "Migrated
  `ignorePatterns` from project config to deny permissions"; `2.1.257` — `defaultMode: "bypassPermissions"` in project settings
  "to be ignored". Each of those would silently change what a third-party governor sees or blocks.
- **Copilot CLI's changelog is calmer (2 semantics-changing bullets) but its shipped artefact is behind its own documentation.**
  P1 measured that installed build 1.0.3 implements **8** hook events while the current documentation lists **14**, and that the
  build fails *open* on a hook error while the documentation says preToolUse fails *closed*. Its npm publishes in the window
  number **836** — far more than the 171 changelog sections — so the changelog is a partial view of the churn.
- **Codex's 3 semantics-changing bullets** include `rust-v0.147.0` "Remove the deprecated `codex exec --full-auto` flag",
  `rust-v0.131.0` "Removed obsolete tool paths, feature flags, config gates, and **legacy hooks** as defaults stabilized", and
  `rust-v0.128.0` "Deprecated `--full-auto` while steering users toward explicit permission profiles and trust flows".

**What this means for a one-person shop, plainly:** three adapters, on three independently versioned products, one of which
changes the governed semantics about three times a month and publishes roughly every working day. Adapter maintenance is not a
background task; **it is the product's main recurring cost**, and it is unbounded by anything the founder controls.

## Q11b — The platform underneath

**Windows feature updates are annual, and there are more live builds than that implies.** Microsoft states: "Windows 11 has an
annual feature update cadence. Feature updates are released in the second half of the calendar year and come with 24 months of
support for Home, Pro, Pro for Workstations, and Pro Education editions; 36 months of support for Enterprise and Education"
(`https://learn.microsoft.com/en-us/windows/release-health/windows11-release-information`, **ms.date 2026-09-14**, updated
2026-09-16). The live table on that date:

| Version | Availability | End of updates (Home/Pro) |
|---|---|---|
| 26H1 | 2026-02-10 | 2028-03-14 |
| 25H2 (this machine, build 26200.9457) | 2025-09-30 | 2027-10-12 |
| 24H2 | 2024-10-01 | 2026-10-13 |
| 23H2 | 2023-10-31 | ended |

**26H1 is the trap.** Microsoft says it "is scoped to support new devices that come to market in early 2026 and is not designed
as a feature update for existing devices" — so it is an *off-cadence* fourth build with its own kernel line (28000.x, versus
26200.x/26100.x). A product touching Event Tracing, the Windows Filtering Platform, AppContainer or the Platform Crypto Provider
must be tested on **three concurrent consumer builds plus 26H1**, not one a year. Monthly cumulative updates (the table's "latest
revision date" is 2026-09-14 for every row) can change behaviour inside a build without a version change.

**Windows on Arm is a second matrix, not a footnote.** "Windows 11 adds the ability to run unmodified x64 Windows apps on Arm
devices" under emulation, and Microsoft's own guidance is that "For the best performance, responsiveness, and battery life, users
will want and need Arm-native Windows apps" (`https://learn.microsoft.com/en-us/windows/arm/overview`, **ms.date 2026-06-25**).
Arm64EC exists to mix native and x64 code in one binary. *NOT VERIFIED:* that page says nothing about driver architecture, about
whether the Platform Crypto Provider's TPM latency differs on Arm, or about Event-Tracing volume there — none of it was probed,
and no Arm hardware was available.

## Q11c — [PROPOSED] Coverage-drift detection, conformance, maintenance and support

**1. Coverage-drift detection — the canary.** [PROPOSED] Every governed agent gets a **canary tool call**: a harmless,
uniquely-named action the governor expects to see through that agent's adapter (for Claude Code, a `Bash` call with a marker
string; for a Model Context Protocol proxy, a `tools/list` for a governor-private tool name; for the model-server proxy, a marker
header). The governor injects or expects the canary at agent start and at a low periodic rate thereafter.
- **Missed canary ⇒ that agent is demoted to "observed only", the demotion is written to the record as a signed event with the
  interval, and the person is told in one sentence naming the agent.** Never a silent continuation, and never a silent block.
- Why this is the load-bearing control: it is the *only* thing that catches rows 1, 2, 4 and 5 of the threat table, all of which
  are invisible from inside the governor. It also catches the ordinary, non-adversarial case — the agent updated overnight and
  its hook schema changed — which by the churn numbers above will happen several times a month.
- Cost: measured. A canary is one extra decision; at the measured ~17–30 µs per decision (Q12) the cost is unobservable, and at
  the 86 ms process-spawn shape it is still one spawn per agent start.

**2. A conformance suite per adapter.** [PROPOSED]
- **Fixture per agent version.** For each supported version of each agent, a recorded *real* payload (not a hand-written mock) —
  P1's `hook-payloads.jsonl` is exactly the right artefact and was produced by driving the real binary.
- **Golden payload + round trip.** Each fixture drives the adapter through **deny, allow and ask**, asserting the decision the
  agent actually honours — verified by the *agent's* observable behaviour (the command did not run; `permission_denials[]`
  contains the call), not by the adapter's own return value. This is BlarAI's "test the seams — mocks lie" rule, and the P1
  measurements show why: the Copilot CLI documentation and its shipped code disagree about fail-open.
- **Two CI rails.** (a) Against **pinned** agent versions — this must stay green, and a failure is a regression in the adapter.
  (b) **Nightly against `@latest`** for each agent — this is *allowed* to fail, and its failure is the product's early-warning
  system, converted into a maintenance ticket the same night. Given 23 Claude Code releases a month, the nightly rail is the only
  affordable way to find a breaking change before a customer does.
- **A toggle test per lock** (BlarAI principle 12): each adapter ships a test proving it blocks when engaged *and* a test proving
  the probe succeeds when the adapter is off — otherwise a green suite cannot distinguish "governed" from "the test could not
  reach it".

**3. Who maintains what, per path.** This is the strategic part of the churn answer.

| Path | Who owns the seam | Who must maintain the adapter | Standing risk |
|---|---|---|---|
| Agent hooks (Claude Code, Copilot CLI, Codex) | The agent vendor, unilaterally | **The governor vendor, alone**, forever | Highest. ~3 semantics changes/month on Claude Code alone; no deprecation contract exists for third parties |
| Local Model Context Protocol proxy | Shared: the protocol is a standard, the config file is the agent's | The governor vendor | Medium. Protocol versioning helps; config-file shape does not |
| Local model-server proxy | The agent's environment variables and config precedence | The governor vendor | Medium-high, and easily disabled (threat row 5) |
| Windows Firewall rules | **Whatever security suite registered a firewall** — Bitdefender here | Nobody can maintain a seam they do not own | **MEASURED failure.** Not a viable enforcement path on a consumer PC |
| Event Tracing for Windows | Microsoft | The governor vendor | Low churn, but administrator-only and 290 MB/min at naive keywords |
| Windows on-device agent registry / MCP proxy | Microsoft, exclusively | **No third-party slot exists** | Cannot be adapted to; can only be argued for (R1 §7) |
| Defender AI agent runtime protection | Microsoft, consuming the *same* vendor hooks | — | This is a competitor on the identical seam, gated behind Defender for Endpoint Plan 2 (P1) |

**4. A support model one person can carry.** [PROPOSED] The shape that follows from the churn numbers, not from ambition:
- **Asynchronous only, with a published response target** (two business days), and no telephone support. One founder cannot
  staff an interactive channel and also ship three adapters a month.
- **A public issue tracker as the primary channel**, so each answer is written once and read many times, and a private
  `security@` path for the disclosure process above.
- **A compatibility page that is generated, not written**: the nightly conformance rail publishes "agent X version Y: governed /
  observed-only / unsupported", dated. Most support load in this product will be "why did it stop governing my agent", and the
  honest answer is usually "that agent shipped a change last night" — a generated page answers it before the question is asked.
- **A hard supported-surface boundary**: name the agents and the versions that are supported; everything else is explicitly
  observed-only. A one-person shop that implies universal coverage is promising something the churn table says is impossible.
- **Opt-in, inspectable diagnostics.** Given "sends nothing off the machine by default", a diagnostic bundle must be: generated
  locally; **shown to the person in plain text before it leaves**; redacted by default (paths hashed, arguments elided, the
  record's content excluded and only its chain metadata included); and sent by the person's own deliberate action, never by the
  product. The bundle should be exactly what the founder needs to reproduce an adapter break — agent name and version, adapter
  version, the last N *decision metadata* rows without arguments, the canary history — and nothing else.

---

# Q12 — Performance budget

## Q12a — The measured numbers, assembled

All of these were measured on this machine, on 2026-09-17, under the loads stated in each source report. Nothing here is a
vendor figure.

| What | Measurement | n | Conditions | Source |
|---|---|---|---|---|
| **Hook as a spawned process** (the shape every agent's hook interface implies) | **median 86.4 ms** (min 75.5, max 104.0) for the JSON form; 86.7 ms for the exit-2 form | 15 each | Real 1.1 KB PreToolUse payload on stdin; `C:\Python314\python.exe`; 3 warm-ups discarded | P1 §Timing |
| Bare interpreter start, for comparison | median **88.5 ms** (`python -c pass`) | 15 | same | P1 §Timing |
| **Hook as a resident governor, named pipe, fresh connection per call** | **median 28.8 / 30.0 / 33.7 / 29.6 / 31.6 µs**; p95 42.9–59.2 µs | 5 runs × 200 | 692-byte payload, message-mode pipe, substring decision, same process | **NEW, MEASURED:** `probes/r5/pipe_latency.py`, 09:51 EDT |
| **…loopback TCP, fresh connection per call** | **median 2495–2543 µs** (≈ 2.5 ms) | 5 × 200 | same payload and decision | same |
| **Control: connection kept open, write+read only** | named pipe **median 16.4–19.2 µs**; loopback TCP **median 18.2–21.1 µs** | 5 × 200 | same | **NEW, MEASURED:** `probes/r5/pipe_latency2.py`, 09:52 EDT |
| **Caller identity** (`GetNamedPipeClientProcessId`) | **18.6 µs**, returned the correct process id | 1 | — | `pipe_latency.py` run 1 |
| **Local protocol proxy, internal overhead** | ALLOW (forward to child) **median 40.0–53.3 µs**; DENY (answered by the proxy) **median 31.5–40.0 µs** | 5 runs × 20 / × 10 | Real JSON-RPC over stdio, child server excluded | `probes/p2/timing-run1.txt`, `timing-runs2-5.txt` |
| …client-side round trip including the child server | ALLOW median 491.9–528.5 µs; DENY median 145.8–163.9 µs | same | child server time median ~203–216 µs | same |
| **Event Tracing volume**, 3 inbox kernel providers | **289,751,040 bytes in 60 s ≈ 4.8 MB/s ≈ 290 MB/min** | 1 × 60 s | Kernel-Process 0x10 + Kernel-Network 0x30 + Kernel-File 0x1290; machine not idle | P3b seam 8 |
| **TPM ECDSA P-256 signature, warm handle** | **median 93.8 / 76.8 ms** (min 45.1, max 125.1) | 2 × 30 | Throwaway key, STM TPM 2.0, Microsoft Platform Crypto Provider | P3b seam 9 |
| **…open-provider-open-key-sign-free pattern** | **median 156.8 / 131.3 ms** | 2 × 30 | The pattern `tpm_signer.sign()` actually uses | same |
| TPM key creation | 338.5 / 332.1 ms | 2 | — | same |
| **Software ECDSA P-256 signature** | **median 0.027 ms** (sign), 0.057 ms (verify) | 500 | `cryptography` 46.0.5 | same |
| **Always-on security agent memory, this machine** | Bitdefender family (`bdservicehost` ×5, `bdagent`, `bdredline` ×2, …): **9 processes, 958.7 MB working set, 889.2 MB private** | 1 census | 09:49 EDT, 16 h uptime, machine busy | **NEW, MEASURED** |
| Microsoft Defender antivirus engine (`MsMpEng`) memory | **Not measurable here: 0 instances** — Defender Antivirus is not running (Bitdefender is the active suite) | — | — | **NEW, MEASURED**; consistent with P1's `AMRunningMode: Not running` |
| Automatic-start services on this machine | **106** | 1 | — | **NEW, MEASURED** |

**The control that changes the conclusion.** The first pipe probe showed named pipes beating loopback TCP by about 80× and the
obvious story — "the third-party firewall inspects every loopback connection" — was available and wrong to publish. The control
run (`pipe_latency2.py`) keeps one connection open on both transports and they converge to ~17–21 µs. **So the 2.5 ms is
per-TCP-connection setup, not per-message cost, and the design rule is "keep the channel open", not "avoid TCP".** Whether the
2.5 ms setup is attributable to Bitdefender's 2176 Windows Filtering Platform filters was **not** isolated — a second machine
without a third-party firewall would be needed, and none was available.

**Published field figures for comparison — what I could and could not get.** This is the weakest part of Q12 and is stated as
such. Portmaster's Windows documentation names the service (`PortmasterCore`, "registered as a system service that starts
automatically on boot") but publishes **no memory, CPU or disk figures** (`https://docs.safing.io/portmaster/install/windows`,
fetched 2026-09-17). Little Snitch's product page publishes **no performance figures** either
(`https://www.obdev.at/products/littlesnitch/`, fetched 2026-09-17). Microsoft publishes a *CPU* guideline for Defender scans —
"Specify the maximum percentage of CPU utilization during a scan", **default 50**, and "The maximum CPU load isn't a hard limit,
but is guidance for the scanning engine to not exceed the maximum on average"
(`https://learn.microsoft.com/en-us/defender-endpoint/configure-advanced-scan-types-microsoft-defender-antivirus`,
**ms.date 2026-09-15**) — but no memory figure. **So the only honest comparable in this report is the measured one: the security
suite this person already runs occupies ~0.96 GB of working set across 9 processes, all day.** That is the bar the market has
already accepted, and it is also the reason a governor must not add another gigabyte.

**Boot-time cost of a service: NOT PROBED.** The Diagnostics-Performance event log (events 100/101/103, which name the services
that delayed boot and by how many milliseconds) requires an elevated shell and **this session's shell was not elevated**:
`Get-WinEvent -ListLog 'Microsoft-Windows-Diagnostics-Performance/Operational'` returned "To access the … log start PowerShell
with elevated user rights." The mechanism, REPORTED: an auto-start service can be configured as a **delayed** auto-start service
via `ChangeServiceConfig2` with `SERVICE_CONFIG_DELAYED_AUTO_START_INFO`, taking effect after the next boot
(`https://learn.microsoft.com/en-us/windows/win32/services/automatically-starting-services`, ms.date 2018-05-31). No boot-delay
number is asserted here.

## Q12b — [PROPOSED] The per-action budget

**Budget: 5 ms at the 95th percentile for a governed action that is decided locally and automatically; 50 ms absolute ceiling
before the governor reports itself as degraded.** Reasoning, from the measurements above:

- **The floor is ~20 µs.** A resident governor answering over a kept-open named pipe costs 17–19 µs median including caller
  identification. Anything the governor does beyond that is its own policy evaluation, not transport.
- **The realistic in-product cost is ~50–200 µs**, from the protocol-proxy probe: 31–53 µs of proxy-internal overhead per call
  with real JSON-RPC framing and a real decision, on top of the transport.
- **5 ms therefore leaves a 25–100× margin** for policy evaluation, a record append, and a fsync-less write. It is generous on
  purpose: the budget must survive a cold cache, a busy machine, and the disk that Bitdefender is scanning.
- **50 ms is the point at which the governor is not the bottleneck but is visible.** Against the measured end-to-end reality —
  a whole `claude -p` turn took 8.0–23.4 s (median 13.7 s, n=5) — even 50 ms is 0.4% of a turn. The ceiling exists so that a
  *pathological* case (a hung policy evaluation, a stalled disk) is caught and reported rather than absorbed silently.
- **The 86 ms process-spawn shape busts the budget by itself and must not be the steady state.** The hook script the agents
  invoke must therefore be a *thin client* — a small native binary that connects to the resident governor and returns its answer —
  not the governor. 86 ms per tool call is invisible next to a 13.7 s turn, which is why it is survivable as a fallback; but it
  is 4,000× the transport cost and it scales with the number of tool calls, so it should never be the design.
- **Event-Tracing observation is outside the per-action budget and needs its own:** at 290 MB/min unfiltered, the budget is
  **≤ 10 MB/min of trace written and ≤ 1% of one core, sustained**, achieved by per-process filtering, dropping the file-write
  keyword by default, and a circular in-memory buffer rather than an on-disk log. If those cannot be met, ship without the
  observation adapter rather than ship a product that fills the person's disk.
- **Memory budget: ≤ 150 MB resident for the service plus ≤ 250 MB for the user-facing app when open.** Justified against the
  measured 958.7 MB the person's existing security suite already takes: a governor that adds a comparable amount doubles the
  always-on overhead of security software on the machine and will be uninstalled on a laptop with 16 GB.

## Q12c — The receipt-signing design the TPM numbers force

The measurement settles this; it is not a judgement call.

- A warm TPM signature costs **77–94 ms median**, and the open-per-call pattern `tpm_signer.sign()` uses costs **131–157 ms**.
  This chip therefore delivers roughly **10–12 signatures per second at full occupancy**, and the TPM executes one command at a
  time.
- Software ECDSA on the same machine costs **0.027 ms** — **~2,800× (warm) to ~5,800× (cold) faster**.
- **Therefore: never sign a receipt with the TPM.** The design that the numbers force, and which BlarAI already implements, is:
  1. **Every decision record is hash-chained in software** — SHA-256 over the record's canonical fields concatenated with the
     previous record's hash. Cost: microseconds. This is `shared/security/audit_log.py`.
  2. **A software signing key signs each record or each segment**, with its private half **sealed by the TPM** (non-exportable
     key material, or a key unwrapped only on this machine and this user) — `shared/security/tpm_sealer.py`,
     `shared/security/verify_pcr_seal.py`.
  3. **The TPM signs only the chain head**, on a timer and at every seal/rotation — which is what `audit-segments.jsonl`'s
     `segment_signature` already is. At one head signature every 10 seconds the TPM is occupied ~1% of the time; at one per
     second it is ~10%, which is the practical upper bound.
  4. **Hold the key handle open.** The measured difference between the warm pattern (77–94 ms) and the open-close pattern
     (131–157 ms) is ~55–60 ms per call, purely from opening the provider and the key (measured separately at 5.7–6.6 ms, so
     most of the gap is elsewhere in the sequence and was not isolated).
- **Consequence for the product's promise.** "Hardware-signed periodically" is the correct phrasing and the hypothesis already
  uses it. "Every decision is hardware-signed" would be a false claim on this hardware: at 10–12 signatures per second, a single
  coding agent emitting tens of tool calls a minute is fine, but a governor watching several agents *and* the file/network
  receipts from Event Tracing (thousands per minute) is not.

---

# Q16 — [PROPOSED] A one-page usability protocol for the Lead Architect as the novice first user

**Why five users, and why this counts.** Jakob Nielsen, "Why You Only Need to Test with 5 Users" (Nielsen Norman Group,
**published 2000-03-18**): the proportion of usability problems found is `N(1 − L)^n` with `L ≈ 31%` per user, so five users
surface about **85%** of the problems, and the money is better spent on "3 studies with 5 users each" than on one 15-user study.
The consequence for this product: **one novice, iterated three times, is a legitimate method** — it is the first of three rounds,
not a substitute for a study.

**What is being measured, and against what definition.** ISO 9241-11:2018, *Ergonomics of human-system interaction — Part 11:
Usability: Definitions and concepts* (Edition 2, **published 2018-03**, confirmed 2023, 29 pages, CHF 159,
`https://www.iso.org/standard/63500.html`). The standard "explains that usability is an outcome of use" and frames it for
*specified users* achieving *specified goals* in a *specified context of use*. So each task below names the user (a non-technical
owner of the machine), the goal (in his words, not the product's), and the context (his own PC, his own agents, his own work).
The three outcome dimensions the standard frames — effectiveness, efficiency, satisfaction — are the three columns recorded.

**Method: think-aloud, one session, ~60 minutes.** He narrates what he is trying to do and what he expects to happen. **The
observer does not help, does not explain, and does not answer questions during a task** — a question asked is itself the finding.
Warn him before any screen recording (his standing rule) and get his agreement first.

**The five tasks.**

| # | Task (given to him in these words) | Goal being tested | Pass criterion | What a failure means |
|---|---|---|---|---|
| 1 | "Install this, and then tell me what it found on your computer." | Install + first-run inventory. Can a novice reach a true picture of what agents exist and what they can reach, unaided? | Completes install without asking a question; then **names, unprompted, at least one agent and one thing it can reach**, in his own words. ≤ 10 min. | The inventory is the product's opening claim. If he cannot restate it, the claim did not land — redesign the first-run screen before anything else. |
| 2 | "Pick the setting you'd want to live with." | Choosing a profile. Are the profiles distinguishable to someone who cannot evaluate them technically? | Chooses one and **states a consequence of the choice that is actually true** ("this one will ask me before anything goes on the internet"). ≤ 3 min. | If he picks by name or by position rather than by consequence, the profiles are labels, not choices. Rewrite the profile descriptions as consequences. |
| 3 | "Carry on with your work. When something happens, deal with it." *(the observer triggers a real approval — a governed agent attempting a genuinely borderline action)* | The approval prompt. Does he have enough to decide, and does he know what he decided? | Decides within **30 s**; when asked afterwards, **correctly restates what he allowed or denied, and which agent asked**. | Not recognising the agent, or misremembering what was approved, is the fatigue failure (threat row 9) arriving on the first prompt. Redesign the card around: who asked, what it will touch, what happens if you say no. |
| 4 | "Show me which of your agents isn't being watched." | The coverage screen. This is the product's honesty surface (Q11a's canary made visible). | **Finds the screen unaided and names the ungoverned agent correctly**, ≤ 2 min. *Set-up: before the session, one agent is deliberately left ungoverned — e.g. launched with hooks skipped, which P1 measured as a real and silent bypass.* | This is the **must-pass** task. A governor that cannot tell a novice where its blind spot is, in one screen, is selling a false sense of safety — the worst possible failure for this product, and grounds to hold the release. |
| 5 | "Check that the history hasn't been messed with." | The record and its verification. Does tamper-evidence mean anything to someone who cannot read a hash? | Runs the verification unaided and **states the result in his own words** ("nothing has been changed") ≤ 2 min. *Second half: the observer has tampered with one record beforehand; he must reach "something was changed" and be able to say roughly when.* | If the verification result is a hash, a status code, or a green tick he cannot explain, the product's central claim is unreadable by its owner. Rewrite the result as a sentence with a date range. |

**What is recorded, per task.** (a) **Effectiveness** — completed unaided / completed with a question / not completed;
(b) **Efficiency** — wall-clock time, and the number of distinct screens visited; (c) **Satisfaction** — his own one-sentence
verdict, verbatim, taken immediately; (d) **every question he asks** and the exact moment he asks it; (e) **every point at which
he says what he expects to happen next and is wrong** — expectation violations are the highest-yield finding in a think-aloud;
(f) the raw session notes, kept.

**What a failure changes, in order of severity.**
- **Task 4 fails ⇒ hold the release.** Coverage honesty is the product.
- **Task 3 or 5 fails ⇒ redesign that surface and re-run the whole protocol** with the next novice (round 2 of Nielsen's three).
- **Task 1 or 2 fails ⇒ fix the wording and re-run only that task**, then carry the fix into the next full round.
- Any task requiring the observer to explain a technical term ⇒ that term is removed from the interface, not explained better.
- **Three rounds of five, not one round**, per Nielsen — and the first round is this one, with one user, which is explicitly a
  first look and not a study.

---

# Not verified — the honest list

1. **Codex's 12-month churn is incomplete.** Release pages 9–12 were rate-limited by GitHub when downloaded; the earliest release
   on disk is 2025-12-05, so ~2.6 months of the window are missing and the Codex counts understate.
2. **Boot-time cost of a Windows service was not measured** — the Diagnostics-Performance log needs an elevated shell and this
   session's shell was not elevated. No boot-delay figure is asserted.
3. **No published memory figures for comparable always-on governors** (Portmaster, Little Snitch, GlassWire) could be found on
   their own sites; only the locally measured Bitdefender figure is offered as a comparable, and Defender's engine was not
   running so could not be measured at all.
4. **The 2.5 ms loopback-TCP connection setup was not attributed.** Bitdefender's 2176 Windows Filtering Platform filters are a
   plausible cause and were not isolated; a machine without a third-party firewall would be needed.
5. **ISO/IEC 29147 and ISO/IEC 30111 were not read** — `iso.org` returned HTTP 403 to this session. They are named as the
   relevant standards and nothing is asserted about their content.
6. **No security-audit day rate was found from a primary source.** Cure53 and Radically Open Security publish none; the
   €20,000–€45,000 estimate is DERIVED from OSTIF's three aggregate figures and marked GUESSED.
7. **MITRE ATT&CK pages could not be fetched** (the technique page returned empty content; the predecessor's saved copy was a
   redirect stub), so no ATT&CK technique identifier is cited. The CVE records carry the evidence instead.
8. **Windows on Arm was not probed at all** — no Arm hardware. Driver architecture requirements, TPM latency, and Event-Tracing
   volume on Arm are unknown.
9. **The governor's own service was never built or attacked.** Every privilege-escalation claim in row 13 is reasoning from other
   vendors' CVEs onto a design that does not exist; it is a prediction, not a finding.
10. **Approval-fatigue has no measurement here.** The prompt-budget proposal in Q9/row 9 is a design position supported only by
    Little Snitch's shipped Silent Mode, not by data.
11. **The 18.6 µs caller-identity figure is n=1** and does not meet this study's own five-run rule; it is reported as an order of
    magnitude only.
12. **The ESET advisory and the CVE record describe CVE-2021-37852 differently** (pipe-client impersonation vs AMSI misuse with
    `SeImpersonatePrivilege`). Both are quoted; neither is adjudicated.

---

# Sources

**Measured on this machine (2026-09-17).** `probes/r5/churn2.py` + `churn2_semantics_bullets.txt` (09:47 EDT);
`probes/r5/pipe_latency.py` + `pipe_latency_out.txt` (09:51 EDT); `probes/r5/pipe_latency2.py` + `pipe_latency2_out.txt`
(09:52 EDT); `probes/r5/nvd3_refs.py` + `nvd3_refs_out.txt` (09:55 EDT); process/memory census and service count (09:49 EDT).
Re-used: `reports/P1-hooks.md`, `reports/P3a-network.md`, `reports/P3b-os.md`, `probes/p2/timing-run1.txt`,
`probes/p2/timing-runs2-5.txt`, `probes/r5/nvd_out.txt`, `probes/r5/nvd2_out.txt`.

**BlarAI, read read-only under `C:\Users\mrbla\BlarAI\`.** `CLAUDE.md` (security_by_design principles 1–13);
`shared/security/audit_log.py`; `shared/security/egress_guard.py`; `shared/security/dev_mode_guard.py`;
`shared/security/tpm_signer.py`; `shared/security/hello_verifier.py`; `shared/security/escalation_consent.py`;
`shared/security/file_dacl.py`; `shared/security/field_cipher.py`; `shared/security/dek_envelope.py`;
`shared/security/injection_scan.py`; `shared/security/exfil_screen.py`; `shared/models/manifest_signer.py`;
`shared/models/weight_integrity.py`; `services/assistant_orchestrator/src/egress_envelope.py`;
`docs/adrs/ADR-039-Coordinator-Self-Governance-Boundary.md` (ACCEPTED 2026-07-11).

**CVE records** — all via the NVD REST API, pulled 2026-09-17: CVE-2025-7073 (pub 2025-12-10), CVE-2023-6154 (2024-04-01),
CVE-2025-13032 (2025-11-11), CVE-2022-26522 / CVE-2022-26523 (2026-05-08), CVE-2021-37852 (2022-02-09), CVE-2024-13944
(2025-05-09), CVE-2026-41091 (2026-05-20), CVE-2025-67826 (2025-12-22), CVE-2023-26088 (2023-03-23), CVE-2023-28892
(2023-03-29), CVE-2025-67905 (2026-02-17), CVE-2021-43768 (2025-10-24), CVE-2022-50971 (2026-06-19), CVE-2025-54569
(2025-07-28), CVE-2024-6260 (2024-11-22), CVE-2025-13818 (2026-02-06), CVE-2025-26684 (2025-05-13), CVE-2025-47161
(2025-05-15), CVE-2025-54135 (2025-08-05), CVE-2025-54136 (2025-08-02), CVE-2025-32711 (2025-06-11), CVE-2025-30066
(2025-03-15), CVE-2022-37981 (2022-10-11), CVE-2024-6768 (2024-08-12).

**Vendor advisories (fetched 2026-09-17).**
`https://www.bitdefender.com/support/security-advisories/local-privilege-escalation-via-arbitrary-file-operation-in-bitdefender-atc-va-12590` (VA-12590, 2025-12-10, modified 2026-03-31);
`https://bitdefender.com/support/security-advisories/local-privilege-escalation-in-bitdefender-total-security-va-11168/`;
`https://support.eset.com/en/ca8223-local-privilege-escalation-vulnerability-fixed-in-eset-products-for-windows` (2022-01-31, updated 2022-03-01);
`https://www.zerodayinitiative.com/advisories/ZDI-22-148/`;
`https://github.com/cursor/cursor/security/advisories/GHSA-24mc-g4xr-4395`;
`https://support.k7computing.com/index.php?/selfhelp/view-article/Advisory-issued-on-22nd-Dec-2025`;
`https://www.malwarebytes.com/secure/cves/cve-2023-26088`; `https://www.malwarebytes.com/secure/cves/cve-2025-67905`;
`https://msrc.microsoft.com/update-guide/vulnerability/CVE-2026-41091`.

**Government and standards (fetched 2026-09-17).**
`https://www.cisa.gov/known-exploited-vulnerabilities-catalog?field_cve=CVE-2026-41091` (added 2026-05-20, due 2026-06-03);
`https://www.cisa.gov/news-events/alerts/2023/03/30/supply-chain-attack-against-3cxdesktopapp` (2023-03-30);
`https://www.cisa.gov/news-events/directives/ed-21-01-mitigate-solarwinds-orion-code-compromise` (issued 2020-12-13);
`https://www.cisa.gov/coordinated-vulnerability-disclosure-process` (45-day default);
`https://slsa.dev/spec/v1.0/levels` (v1.0, retired in favour of v1.2);
`https://theupdateframework.io/docs/security/` (last modified 2024-10-12);
`https://www.iso.org/standard/63500.html` (ISO 9241-11:2018, Edition 2, 2018-03, confirmed 2023);
`https://www.iso.org/standard/72311.html` (ISO/IEC 29147 — **HTTP 403, not read**).

**Microsoft Learn (fetched 2026-09-17, ms.date given).**
`https://learn.microsoft.com/en-us/windows/release-health/windows11-release-information` (ms.date 2026-09-14);
`https://learn.microsoft.com/en-us/windows/arm/overview` (ms.date 2026-06-25);
`https://learn.microsoft.com/en-us/defender-endpoint/tamper-protection-overview` (ms.date 2026-09-09);
`https://learn.microsoft.com/en-us/defender-endpoint/configure-advanced-scan-types-microsoft-defender-antivirus` (ms.date 2026-09-15);
`https://learn.microsoft.com/en-us/windows/win32/services/automatically-starting-services` (ms.date 2018-05-31);
plus, via P1/P3a/P3b: `…/defender-endpoint/ai-agent-runtime-protection-overview` (ms.date 2026-09-16),
`INetFwProduct::get_RuleCategories` (ms.date 2018-12-05), `…/appcontainer-isolation` (ms.date 2025-07-08),
`…/select-types-of-rules-to-create` (ms.date 2026-03-29).

**Agent vendor documentation.** `https://code.claude.com/docs/en/hooks` and `…/managed-settings` (fetched 2026-09-17, no page
date); `https://learn.chatgpt.com/docs/hooks` (via P1); `https://docs.github.com/en/copilot/reference/hooks-reference` (via P1).

**Usability, product and industry.** `https://www.nngroup.com/articles/why-you-only-need-to-test-with-5-users/` (Jakob Nielsen,
2000-03-18); `https://www.obdev.at/products/littlesnitch/index.html`; `https://docs.safing.io/portmaster/install/windows`;
`https://cure53.de/` (publishes reports, no prices); `https://www.radicallyopensecurity.com/` (no prices);
`https://ostif.org/audits/` (20,000 hours, 800 vulnerabilities, $3,000,000+ raised, 100+ audits since 2016).
