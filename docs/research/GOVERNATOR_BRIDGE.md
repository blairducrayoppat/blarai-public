---
title: BlarAI to Governator knowledge bridge
status: living
area: research
---

# The Governator bridge : one connected knowledge system for BlarAI and The Governator

Drafted 2026-10-11 (machine clock 12:36 EDT) for the Lead Architect (LA). Intended home: `C:/Users/mrbla/BlarAI/docs/research/GOVERNATOR_BRIDGE.md`, in the BlarAI repository only. Acronyms are spelled out on first use.

**This document must never be copied, in whole or in part, into the Governator repository.** It names BlarAI paths, ticket numbers, account names and internal findings. It refers to Governator records by path and identifier only, and it proposes (never performs) every content flow across the wall. Nothing in either repository was edited to produce it; no git, no Vikunja call.

Evidence grades used below (same as the Knowledge Map draft): **M** measured on this machine; **S** read from source code or a primary artifact; **V** vendor documentation or vendor talk only; **R** reasoning or design. The Governator's own grades map as: MEASURED = M, REPORTED = S or V (its record says which source and date), GUESSED = R, MEASURED-AGAINST-A-MOCK = M with a stand-in. Where the Governator has a claim-register identifier it is quoted as `P1` to `P12` (platform facts, `docs/governance/claim-register.md` section 2). The register's section 1 (product claims) is empty ("none yet — nothing is built"). Section 3 (claims the project must never make) has five unnumbered bullets; this document refers to them as `N1` to `N5` in file order (my labels, not the Governator's). The six bullets of "What is not measured today" in `docs/governance/coverage-disclosure.md` are referred to as `CD-1` to `CD-6` in file order (my labels).

---

## 1. Summary (10 lines)

1. BlarAI is the Lead Architect's private, local, security-first assistant. The Governator (`C:/Users/mrbla/governator`) is a separate, unbuilt product idea: a runtime action governor for AI agents on Windows PCs, with BlarAI as its first target (Governator ADR-004). Its claim register has no product claims yet, only 12 measured platform facts (P1 to P12).
2. The wall runs both ways and is asymmetric. Inbound to the Governator it is absolute and gate-enforced (`tests/test_never_cross.py`); outbound it is four named categories (telemetry path, update client, cloud-model adapter, externally sourced policy pack), not a ban on the governor itself.
3. The wall's gate is a floor, not the rule: it checks four case-sensitive text patterns and skips non-text suffixes (HTML among them). Anything crossing inbound needs a human-reviewed, scripted redaction with a printed substitution report, as the founding copy had.
4. The BlarAI #1740 and #1671 results bear directly on the Governator: a raw Windows Filtering Platform (WFP) block keyed to an account identity held under the installed security suite (3 of 3 runs) qualifies P9 and answers part of CD-2; an AppContainer ignores a refusal entry that names it (12 of 12); restricted tokens have two undocumented launch requirements; Microsoft's container (MXC) tier 1 refused host-loopback on this Windows build.
5. Of 21 BlarAI findings assessed in section 4, 17 are publishable to the Governator after redaction (E1 also needs the LA before any claim changes), 2 are not (BlarAI-internal configuration and tooling), and 2 need the LA first (they criticise a named company's product).
6. Microsoft's Build 2026 talk BRK262 names three platform primitives: agent identity, containment, manageability. The shipped MXC v1.0.0 files contain none of the "dynamic composition", user-consent or IT-policy layer the talk describes (library study); the talk describes direction, the code does not yet.
7. Thirteen [PROPOSED] connections are listed in section 5. The strongest: the Governator's vocabulary and profile as the policy layer MXC lacks (hypothesis), MXC and OS-issued agent identity as enforcement backends under a governor (hypothesis), and the two claim registers sharing one grade vocabulary.
8. One real conflict needs the LA: BlarAI's ADR-049 names a candidate claim ("cannot reach the network or read your files; enforced by Windows") while the Governator's register section 3 forbids "The Governator blocks agents from reaching the network" (written before the #1671 evidence). The two reasons behind that prohibition are independent; the new evidence touches only one (section 3(f), D1).
9. Competitive reading (section 6, facts separated from inference): Microsoft states the problem as the Governator does ("we cannot rely on the agent to self-govern"), but its answer is platform plus IT-managed policy; the consumer per-agent gap in the Governator's own window estimate (B2c, a GUESS) is neither closed nor refined by the talk.
10. Proposed process (section 7): an identifier-keyed bridge table on the BlarAI side, a scripted and reviewed redacted export that only a Governator-gated session may import, and a drift check at merge clusters. Nothing is automatic and no directory is shared. Not verified by me: Vikunja ticket text on either board, the Governator git history, and the full text of most raw data files.

---

## 2. The two projects and the wall

### 2.1 What each is

| | BlarAI | The Governator |
|---|---|---|
| What | The artefact: a personal, locally run AI system; Policy Agent (UC-001) is the single adjudication door for risky actions; fail-closed; per-scope policy-gated egress (BlarAI `CLAUDE.md`) | A runtime action governor for AI agents on Windows PCs: one vocabulary for "what the agent is about to do", a profile the person can read, a signed local record the person owns, and a coverage screen that states what it does not govern (Governator `CLAUDE.md`, `what_this_is`) |
| Status (read on disk, 2026-10-11) | Operating. Coder containment (account level) is built and switched off (`containment = off`, ADR-045; as stated in the Knowledge Map draft, not re-read from the flag file by me) | Founded 2026-09-17; cancelled 2026-09-18 (BlarAI ADR-042); reopened 2026-10-05 (BlarAI ADR-049); nothing built; claim register section 1 empty; ADR-005 (implementation language) not decided (`docs/governance/decision-register.md`, `docs/RECORDS_INDEX.md`) |
| Repository | `C:/Users/mrbla/BlarAI` | `C:/Users/mrbla/governator`, no remote, no LICENSE file; the name is cleared only for the uses in decision 3a |
| Who it serves | One operator, one machine he administers, a network welded shut and opened one door at a time | People on machines the author does not control, beside other security software, whose agents talk to the cloud model their owner chose |
| Rulebook | `CLAUDE.md` (security-by-design, 13 principles) | Its own `CLAUDE.md`, ADR-001 to ADR-004; inherits BlarAI's habits (claim register, coverage disclosure, disposition discipline, tests-off toggles) and not its rules |
| Relationship | Raw material, the founding study, and the first governed target | Uses BlarAI's mechanisms (rewritten, not copied) and, per ADR-004, BlarAI first in shadow then in the adjudicator slot at an LA-present ceremony |

Both are the LA's. The founding study (BlarAI `docs/research/runtime-action-governance-product-feasibility-2026-09-17.md`; Governator copy `docs/founding/feasibility-study-2026-09-17.md`) is the shared ancestor; the Governator copy is redacted. Decision register row of 2026-10-06 (Governator `docs/RECORDS_INDEX.md`): "The research material is BlarAI's."

### 2.2 The wall, as the Governator's own files state it

Sources read: `CLAUDE.md` (`the_wall`, critical rule 4), `docs/governance/never-cross.md`, `tests/test_never_cross.py`.

**Inbound (BlarAI into the Governator): absolute, gate-enforced.** Refused categories, per never-cross.md ("Categories, not literals"):
- hardware and derivation key names; local application-data paths including anything beneath them; database files, audit chains, key wraps and certificates; genesis and derivation labels; allowlist values including the name of the chosen search provider; built helper binaries, model weights and manifests; preference, profile and launcher data that may echo prompts.

**What the gate actually checks** (read from the test file): four case-sensitive patterns built from fragments: the project name followed by a hyphen and any name characters; the local-data path in its `%LOCALAPPDATA%\` form; the `AppData\Local\` form; the search provider's domain. It walks every tracked file whose suffix is in a fixed text list (`.md .py .txt .toml .json .yaml .yml .cfg .ini .ps1 .sh .rs .cs .go .c .h .csproj .gitignore` and no suffix). There is no exception list and no self-exclusion. A second test plants the strings and requires every pattern to match (the switched-off proof).

**The gate is a floor, not the rule** (my reading, each point checked by grep or from the test source):
- The patterns are case-sensitive. A lower-case account name, an upper-case probe name or a hyphen-less compound does not match. Examples already in the Governator copy of the founding appendices, which pass the gate: `BlarAIStudyProbe1549` (A3 lines 252 and 297; A4 line 95) and `BLARAI-STUDY-1549-NONADMIN` (A4 line 94). Both are throwaway probe names, not keys; whether they are "identity strings" under the rule is for the Governator side to judge.
- `.html` and every binary suffix are not scanned (the Governator holds `docs/NEXT-SESSION.html`).
- Paths other than the local-data path (a fleet folder, a models folder, a fixture root), the operator's profile name, security identifiers (SIDs), machine names and ticket-internal facts are not patterns at all. The #1740 report carries all of these (for example `C:\Users\mrbla`, `B:/models`, `C:/blarai-fleet`, `C:/Users/blarai-coder`: 12 occurrences of the operator profile name, 2 of the account name in the main report).
- Governator ADR-004 already quotes one BlarAI code symbol and file path (`register_url_adjudicator` in `shared/security/guarded_fetch.py`). A symbol is mechanism rather than identity under never-cross.md; I flag it only because section 7 proposes a drift check for exactly this kind of quoted BlarAI fact.

So the rule to apply is the categories in never-cross.md read generously, with the gate as a backstop; "the gate passed" is never the clearance.

**Outbound (the Governator into BlarAI's runtime): four named categories, not a ban.** No telemetry path, no update client, no cloud-model adapter, no externally sourced policy pack. "A local, deterministic, fail-closed adjudicator is not in that list; BlarAI is the first target under ADR-004's conditions" (CLAUDE.md rule 4). BlarAI's own locks already fire on the four categories (single-importer scan on any network library, socket guard, dependency-truth and supply-chain-hash locks).

ADR-004's conditions on integrating the governor into BlarAI: shadow first (never returns a verdict BlarAI acts on); occupies the one door or observes beside it, never a parallel path; none of the four categories; once in the slot verdicts may only tighten; identity never crosses; BlarAI's standing gate is the acceptance test.

**BlarAI's side of the same wall** (BlarAI `CLAUDE.md`): "ONE Policy-Agent adjudication door"; a new network client, a new decrypt point or a Policy-Agent bypass "is a decision_boundary escalation, not a design choice"; irreversible or posture changes are LA-present ceremonies; ADR-049 states "No BlarAI runtime change". So putting Governator code into BlarAI's adjudicator slot is an LA decision on BlarAI's side as well as on the Governator's.

### 2.3 Exactly what may cross, in each direction, and by what process

| # | Direction | What | Process | Evidence the process works |
|---|---|---|---|---|
| X1 | BlarAI to Governator | Measured facts about Windows behaviour and the method that produced them (what an operating-system mechanism did, with conditions) | A redacted derivative written for the purpose, never a raw copy: a script that prints an auditable substitution report, a human read, `tests/test_never_cross.py` green, and an LA decision where it touches a claim | Founding copy: 17 files copied at merge `50f7100d`; 3 rewritten, with the report reproduced in the founding journal entry (never-cross.md, "The founding documents were redacted") |
| X2 | BlarAI to Governator | Design mechanisms: how an action is written down, judged, recorded, asked | Re-implemented or re-described on the Governator side, replacing key names, dialog strings and path defaults, not lifted (never-cross.md, "When the rule would bite in practice"). The founding Q7 table lists ten surfaces and how each is cut | Governator ADR-001 ("inherits habits, not rules"); journal note that `verify_disposition.py` was copied and adapted (renamed home, sibling allowlist cut) |
| X3 | BlarAI to Governator | Public-source field research (landscape surveys, vendor and source reads) | As X1, after removing every BlarAI row (the landscape's BlarAI sub-rows cite BlarAI code and register rows) | Not yet done; proposed |
| X4 | BlarAI to Governator | The seven refused categories above; the component-by-component map of BlarAI internals | Never. The founding study's map appendix was deliberately not copied | never-cross.md |
| X5 | Governator to BlarAI | Specifications, vocabulary, measurements and decisions as reading material, referenced by path and ID | Free. Only the BlarAI side's own review applies | This document |
| X6 | Governator to BlarAI | The governor's adjudicator code in BlarAI's door slot | In principle allowed (ADR-004): shadow, then promotion at an LA-present ceremony, BlarAI's gate as acceptance. BlarAI side has not adopted shadow mode; see section 3(f) D3 | ADR-004; BlarAI landscape "Rejected" list (dry-run and evaluate-only modes are a posture choice for the LA) |
| X7 | Governator to BlarAI | Telemetry path, update client, cloud-model adapter, externally sourced policy pack | Never | never-cross.md; BlarAI's own locks |

**This document performs none of X1 to X3.** Section 4 classifies candidates; section 7 proposes the process; nothing is exported until the LA approves a first batch.

One further fence, from the Governator's `CLAUDE.md` rule 9 and decision register: nothing leaves the machine without the operator's explicit act; no contact with Microsoft or a foundation (decision 5, open). BlarAI's public mirror is a separate content-clearance gate; before this document is synced anywhere public it needs the LA's clearance, because it carries the Governator's internal status (for example "name clearance NOT done").

---

## 3. Topic card: Runtime action governance on Windows (The Governator)

(Schema: KNOWLEDGE_MAP draft, section 1. Cluster would sit next to "Containing the coder" and "Untrusted input".)

### (a) The question

Can a local, deterministic governor decide each action an AI agent is about to take on a Windows PC, in one agent-neutral vocabulary, record the decision where nobody can quietly edit it, and say truthfully which agents and which actions it can and cannot stop; and how much of that does Windows itself now provide, so the governor does not have to build it?

### (b) Current answer and status

**Open; partly decided; nothing built.**
- *Decided (LA):* reopen the venture (ADR-049, 2026-10-05), on a narrower claim than the one it was cancelled for; keep `C:/Users/mrbla/governator` untouched until a scope exists (ADR-049 Decision 1; the Governator was nevertheless edited on 2026-10-10 for its records index and decision 3a, per its journal fragment, so that statement has partly lapsed); the name may be used in BlarAI public documents within decision 3a; separate repository and rulebook (Governator decision 4).
- *Governator ADRs (Accepted 2026-09-17):* ADR-002 adjudicate at the agent's own seam, never ship a packet chokepoint, enumerate registered firewall products before touching the network seam; ADR-003 resident governor, thin hook client over a named pipe, record chained in software with the hardware chip signing only the chain head; ADR-004 target order, BlarAI in shadow first. ADR-001 repository and rulebook. ADR-005 (language) undecided.
- *Not adopted:* the product claim. ADR-049 lists a candidate only: "an agent run inside the contained account cannot reach the network or read your files; enforced by Windows, not by the agent."
- *Open decisions (Governator decision register):* 2 licence and form; 3 name clearance search (not done); 5 approach to Microsoft or a foundation; 6 legal form, jurisdiction, multi-user consent posture. Standing constraints: nothing posted, no accounts, no purchases, no contact with Microsoft.
- *Deciding documents:* BlarAI ADR-042, ADR-049; Governator `CLAUDE.md`, `docs/governance/decision-register.md`, ADR-001 to ADR-004.

### (c) Studies, measurements and decisions

Grade column: BlarAI grade, with the Governator's term in brackets. "Gov ID" is the Governator register entry the row bears on (none where the Governator has no entry yet).

| Date | Document path | What it found, one plain line | Grade | Gov ID | Confidence note |
|---|---|---|---|---|---|
| 2026-09-17 | Gov `docs/founding/feasibility-study-2026-09-17.md` (BlarAI copy `docs/research/runtime-action-governance-product-feasibility-2026-09-17.md`) | Three seams driven end to end (agent hook, protocol proxy, model-server proxy); all are cooperative; the one non-cooperative seam tried (per-process firewall rule) failed silently | M (MEASURED) | P1 to P9 | Machine never idle; one security suite; one machine |
| 2026-09-17 | Gov `docs/governance/claim-register.md` section 2 | Hook refusal holds under bypass modes (10 runs); 86.4 ms per process launch against 29 to 34 microseconds over a named pipe; three hook escapes; crashed governor read as no opinion on three agents (measured on one, read on two) | M / S (MEASURED / REPORTED) | P1 to P6 | Claude Code 2.1.273; two agents read, not run |
| 2026-09-17 | same, P7 and P8 | A local protocol proxy and a local model-server proxy can refuse a tool call before the agent acts; decision cost 46 microseconds median (n=30) | M (MEASURED, one against a mock) | P7, P8 | |
| 2026-09-17 | same, P9; Gov `docs/founding/appendices/A3-seam6-network-probe.md` | A per-process firewall rule was accepted by every management surface and never became a kernel filter: 37 of 37 requests that should have been blocked succeeded; the suite holds 2,176 filters against Microsoft's 18 | M (MEASURED) | P9, ADR-002, N2 | One machine, one suite, one interface; the own-provider route was not probed |
| 2026-09-17 | same, P11; Gov founding study Seam 3 | Windows' agent protocol layer carries a filter contract (`mcpFilter`) whose only registrant here is Microsoft Defender; undocumented in the pages read | M (MEASURED) | P11, CD-1 | No exhaustive documentation search |
| 2026-10-04/05 | BlarAI `docs/research/account-level-containment-evidence-2026-10-05.md` claim C1; data `docs/research/containment-evidence-2026-10-05/wfp-spike/` | A raw WFP block filter keyed to a dedicated account's identity, one provider, one sublayer at the top weight, stopped the account's outbound connect to 1.1.1.1:443 under the installed security suite, 3 of 3 runs; the operator's traffic was unaffected | M, n=3 (MEASURED) | P9 (qualifies), CD-2 (partly answers), N2, ADR-002 | Filters stood about 5 s (one hold about 127 s) in a dynamic session that vanishes when the script exits; IPv4 TCP 443 only; one machine, one suite; no reboot, IPv6, UDP, DNS or other ports |
| 2026-10-09 | same doc claims C7 and C8; data `containment-evidence-2026-10-05/arm1-permit/runs/` | With a loopback permit the confined account got a 32-token completion from a real local server while its internet was refused; without the permit the loopback request failed with error 10013; 3 of 3 each | M, n=3 per condition (MEASURED) | CD-2 | Windows of 3 to 4 s; six runs in seven minutes |
| 2026-10-05 | BlarAI `docs/adrs/ADR-049-Governator-Venture-Reopened.md` | The LA reopened the venture on the narrower, one-dimension containment claim; lists the limits exactly (one dimension, one machine, IPv4 443, not per-action governance, nothing outside the account, setup not self-service) | decision | N2 (tension), decision 1 | The candidate claim is the session's reading, not adopted |
| 2026-10-05 | `account-level-containment-evidence-2026-10-05.md` claim C2b and ADR-045 | A dedicated account was denied 8 of 8 secret reads and 4 of 4 named outside writes, but could write two other broad-group-writable folders; the "cannot write outside" claim is false for the real coder account today | M (MEASURED, with a CONTRADICTED status word) | none | Shows a dedicated account inherits broad-group grants; BlarAI configuration (not publishable as is) |
| 2026-10-10/11 | BlarAI `docs/research/windows-containment-comparison-2026-10-10.md` section 4 and `windows-containment-comparison-2026-10/phase2/summary-phase2.md` | Five alternatives plus a control on one probe payload; windows' own access check agreed with launches 48 of 48 writes and 15 of 15 secret reads per variant | M (MEASURED) | seam 7 (A4) | Build 26200.9457; 3 runs per variant; no model in the loop; arm A (the dedicated account itself) not run |
| 2026-10-11 | same report, section 5 finding 1; `windows-containment-comparison-2026-10/effective-access/deny-ace-check.json` | A refusal entry that names an AppContainer does not refuse it: 12 of 12 launched runs; an exception has to be made by not granting | M, n=12 (MEASURED) | seam 7 (A4) | No Microsoft page states it |
| 2026-10-11 | same, finding 2 | A fully restricted token can be singled out by a network rule (block naming operator plus restricting identity, under an operator permit: only that token blocked, 3 of 3); a write-restricted token cannot | M, n=3 (MEASURED) | P9, seam 6 | One program file scoped; IPv4 TCP 443; unscoped form not run |
| 2026-10-11 | same, findings 3 and 4 | Restricted tokens launch only when derived in one step from the launcher's token and with a default access list granting the restricting identities (otherwise `0xC0000142` in 0.05 s); git-bash fails to start in every restricted-token and container setup | M (MEASURED) | seam 7 (A4 "removed admin and nothing else") | Reasons recorded differ by setup |
| 2026-10-11 | same, finding 5 and table | Microsoft's container (MXC) tier 1 on build 26200.9457: signed launcher, archive matches published digest; refused the host-loopback setting; defaults stop node, git and Python ctypes until UI lockdown is off; inherited the elevated console's administrator groups | M (MEASURED) | B1 row 2 (MXC) | Only tier 1 was run; elevated console |
| 2026-10-11 | BlarAI `docs/research/windows-containment-comparison-2026-10/mxc-library-study/studies.json`, `skeptic-checks.json`, `README.md` | MXC v1.0.0 as a library: no "dynamic composition" feature, no user-consent or IT-policy layer in the shipped files; a held-open sandbox only for IsolationSession (Insider build) and WSLC; audit mode over-grants; config schemas 0.6 to 0.8 declared supported 29 Sept and rejected 7 Oct | S (REPORTED) | B2c ("not a governor") | All three studies "holds_with_corrections"; no container run; files in a throwaway folder outside the repo |
| 2026-06-03 (upload) | `docs/research/windows-containment-comparison-2026-10/sources/ms-build-2026-brk262/transcript.txt` (outside the repo; see Appendix); video "Building Agents You Can Trust on Windows | BRK262", Microsoft Developer | Microsoft names three primitives for agents on Windows: identity, containment, manageability; MXC library compiles declared needs against system and IT policy ("dynamic composition") | V (REPORTED) | B2c, B1 row 2, decision 5 | Auto-captioned transcript, 28:34 long, no Q&A; vendor talk, not a measurement |
| 2026-10-10/11 | BlarAI `windows-containment-comparison-2026-10/workstream-0/` (`ws0-codex-mxc.md`, `ws0-nono-srt.md`, `ws0-msdocs-bypass.md`, `openai-codex-writeup-read-note.md`, `ws0-grayswan.md`) and report section "State of each mechanism" | How OpenAI Codex, Anthropic's sandbox runtime, nono and Chromium confine on Windows, read at source; Microsoft's serviced-boundary table (dedicated account and AppContainer yes; restricted token not named) | S (REPORTED) | B1 row 2; ADR-049 "relation to nono and srt" | I read the report's summary of these, and only the opening of the four files |
| 2026-09-16 | BlarAI `docs/research/runtime-action-governance-landscape-2026-09-16.md` and four `landscape-*-agent-governance-2026-09-16.md` | 110 vendor, standards and open-source rows scored on identity, binding, receipt, seam and local operation; no vendor ships all five; Microsoft's Agent Hooks and Agent Control Specification hash the canonical action and refuse on mismatch | V + S (REPORTED) | concept-spec R-list | Documentation-level for most rows, by its own statement |
| 2026-09-17 | Gov `docs/founding/appendices/B2c-competition-and-microsoft-timing.md` | Microsoft Defender for Endpoint runtime protection (preview, June 2026) hooks four agents through their vendor hook interfaces; enterprise-licensed; window for a consumer per-agent surface guessed at 9 to 24 months, median 15 | V (REPORTED) with a GUESSED window | decision 5 | Low confidence by its own text |
| 2026-10-10 | Gov `docs/RECORDS_INDEX.md` and `docs/journal_fragments/2026-10-10-records-index.md` | The Governator repository did not know it had been cancelled and reopened; three design lessons from a third party's Windows sandbox rejection are open on its board | R | none | Lesson: carry a decision back to the record that claims to hold it |
| 2026-09-17 to 10-09 | BlarAI `docs/research/trust-spine-proposed-items-index.md`, `pcaa-placement-and-blarai-mapping-2026-09-16.md` | Fifteen proposed trust-spine items; four gaps (A approval binding, B receipts at the doors, C two egress layers, D chain never verified on load) | R + S | none (BlarAI internal) | Mechanism lessons transfer; code paths do not |

### (d) Layers of zoom

1. **Why a governor at all.** Agents act with the user's rights; prompts and agent self-restraint do not hold (BRK262 02:06 to 02:20: "we cannot rely on the agent to self-govern"; the Governator's N-list: nothing is "fully governed").
   1. **Where a third party can stand** (Governator Q1, ten seams). Cooperative: agent hooks, protocol proxy, model-server proxy. Non-cooperative: the operating system's own identity and filter layers.
      - Hooks: refusal holds under bypass modes (P1) but a flag skips them, a crashed hook fails open, a shell command is one opaque string (P4, P5). The governor can detect its own absence (liveness canary), not prevent it.
      - Network seam: not reliably ours (P9). Raw WFP keyed to an account identity did hold under the same suite (BlarAI C1), for processes run inside that account.
      - Isolation seam: launcher routes only (restricted token, AppContainer, Windows Sandbox, MXC): bypassed by starting the agent another way (B1).
2. **What the governor is made of** (Governator concept spec and ADR-002 to ADR-004).
   1. Vocabulary: one description of an action with a mandatory derivation field (declared, parsed, annotation, unknown).
   2. Decision: profiles are allowlists; model-derived mappings may only tighten.
   3. Record: chained in software, chain head signed on a timer (10 to 12 hardware signatures a second, P10).
   4. Coverage screen: four states per agent (Governed, Observed only, Out of reach, Unknown); Unknown is the default; a row for every seam it does not own.
3. **What Windows now provides** (BRK262; BlarAI #1740).
   1. Agent identity: the talk calls agents "a new type of identity", with their own security principal and OS-side audit (05:20 to 08:00). Governator seam 4 found no agent accounts on this machine on 2026-09-17.
   2. Containment: MXC v1.0.0 (tag commit 7bf21024); tier 1 measured here; other tiers not run.
   3. Manageability: IT policy, Agent 365, Defender, Entra, Intune (27:02 to 27:50). On-device pieces seen by the Governator study: an agent-governance configuration service provider and the Defender-held `mcpFilter` slot (inference that these are the same story).
4. **The operator-side lesson** (BlarAI ADR-045, report): the biggest holes were in the code around the account, not in the account. A governor's own adapter and launcher are its largest attack surface.
5. **Single-door vs second adjudicator** (BlarAI CLAUDE.md principle 5; Governator ADR-004): occupying the one door is not adding a second adjudicator; observing beside it is shadow. Both sides agree "never a parallel path".

### (e) Open questions and the observable that closes each

| Question | Observable that would close it |
|---|---|
| Does a governor's own network-filter provider hold beside the suite's top-weight layer beyond seconds, across reboot, IPv6, UDP, DNS, a suite update (CD-2) | BlarAI persistent filter (#1682) plus the long-hold and reboot arms listed NOT RUN in `containment-evidence-2026-10-05/ARMS_HANDOFF.md` |
| Is a governor-installed persistent filter fail-closed or does it vanish with its installer (the measured filter was a dynamic session that disappears when the script exits) | A run that kills the installer process and re-measures the account's connect |
| Does OS-issued agent identity now exist on a current Windows build, and can a network filter key on it | Re-run of the Governator seam-4 account and package census on a build with the agent workspace; a WFP condition test on the resulting principal |
| Does MXC ship the policy-matching, consent and IT-policy layer the talk describes | Compare the shipped schema and docs at the next MXC release with `studies.json` study 2 (no such feature at v1.0.0); PR #1309 merge state |
| Does a newer Windows build or MXC release add host-loopback to the process container | `wxc-exec --probe` reports `baseContainerSupportsIngressHostLoopbackAllow: true` (false here at 26200.9457) |
| Does a non-Microsoft package that registers the `mcpFilter` contract get loaded (CD-1, P11) | Build and install a package; not done, untestable without it |
| Do the two unrun agents' hooks fail open or closed (CD-3) | Run them; Codex not installed (ADR-004 item 3) |
| Is the governor's shadow observation of BlarAI acceptable to BlarAI's posture (single door, "no evaluate-only mode added silently") | LA decision D3 below |
| What does the Governator's cost of an enforcement backend look like if it follows MXC releases | Count semantic changes per month on MXC's surface; the Governator's own P12 gave about 3 a month for one agent's hook surface; MXC schema churn 29 Sept to 7 Oct is one data point |
| Is the Governator's N2 reason (P9) the only reason it must not claim network blocking | No: ADR-002 independently gives the EU conformity class reason. Closing observable: the Governator's legal reading (a lawyer, per its CLAUDE.md) of an account-scoped, identity-keyed block as not a "packet chokepoint" |

### (f) Decisions

Made: see (b). LA 2026-10-05 reopening (ADR-049). LA 2026-10-09 decision 3a (name in BlarAI public documents). Governator ADR-001 to ADR-004.

**Waiting for the LA** (technical choices are the session's; these are his, per both `decision_boundary` blocks):
- **D1 (claim honesty).** Reconcile ADR-049's candidate claim with the Governator's N2. N2 ("The Governator blocks agents from reaching the network") cites P9 (per-process firewall rule) and ADR-002 (EU conformity class); the #1671 evidence concerns an account-scoped, kernel-enforced filter, a different mechanism. Recommendation: leave N2 as written until a persistent, fail-closed account-scoped block exists and the conformity question has had legal reading; add a bridge row recording the qualification; do not edit the Governator's register from here. Alternative: narrow N2 now to "per-process firewall rules". Trade-off: narrowing early is more honest about P9 but opens a claim the evidence (3 of 3, seconds-long windows) does not yet carry.
- **D2 (boundary).** ADR-049 flagged ADR-042 Decision 3 ("there is no second party", the asymmetric boundary moot) for re-examination at the scoping gate. Governator `CLAUDE.md` already treats the asymmetric wall as live. Confirm which stands.
- **D3 (BlarAI posture).** Governator ADR-004 assumes BlarAI accepts a shadow observer; the BlarAI landscape's "Rejected" list says a dry-run or evaluate-only mode "should not be added silently" and is the LA's choice. Needs his answer before any shadow work.
- **D4 (this bridge).** Approve the process in section 7 and a first export batch (section 4, "yes" rows). Anything touching a claim is separately his.
- **D5 (Microsoft).** Whether BRK262 and MXC v1.0.0 change Governator decision 5 (approach Microsoft or a foundation). Recommendation: no change; no contact; revisit when the MXC policy-matching layer ships or does not.
- **D6 (stale records).** Governator "Known gaps" (board description still carries the old name rule; `docs/NEXT-SESSION.md` predates the cancellation) are the Governator side's to fix; listed for visibility.

### (g) Tickets

As cited in documents (ticket text not read by me, not verified on either board).
- BlarAI: #1549 feasibility study; #1590 cancellation record; #1693 reopening and scoping gate; #1671 raw WFP block; #1689 and ADR-046 confined model account; #775 and ADR-045 coder containment; #1682 persistent egress filters; #1678, #1686, #1692 broad-group grants; #1740 containment comparison; #1742 and #1743 machine findings; #1669 third-party sandbox (nono); #1537, #1540 to #1548, #977 trust-spine items and gaps A to D.
- Governator board: Vikunja project "The Governator" (resolve by name): sixteen founding tickets closed 2026-09-18 "CANCELLED, not completed" and kept closed by the LA's ruling of 2026-10-10; open: three design lessons from a third party's Windows sandbox work (build gate on Windows; per-invocation versus standing-account fence; mechanism separate from policy), recorded 2026-10-10, mirrored on the Architecture Decisions board.

### (h) Raw sources and where they live

- Governator: `C:/Users/mrbla/governator/docs/founding/` (study, brief, concept spec, 14 appendices A1 to A4, B1 to B6 and variants), `docs/governance/`, `docs/adr/`, `docs/RECORDS_INDEX.md`, `docs/LESSONS.md` (lessons 1 to 5), `docs/NEXT-SESSION.md` (predates the cancellation).
- BlarAI: `docs/research/` as cited; `docs/research/containment-evidence-2026-10-05/`; `docs/research/windows-containment-comparison-2026-10/`; `tools/probes/containment_arms/`; `docs/reviews/final-review-1740-disposition-2026-10-11.md`.
- Outside both repos: `C:/blarai-spike-1740-mxc/` (throwaway fixture root; holds the BRK262 transcript, caption files and the MXC study downloads; the report says it is on disk "until the teardown step runs").

---

## 4. Evidence from BlarAI studies that bears on the Governator

Publishable column: **yes** (after the stated redaction), **no** (BlarAI-internal; reasons given), **needs LA** (touches a claim, a posture, or criticises a named company). Redaction types use the never-cross categories. "Gov touch" quotes the Governator record the finding bears on.

| # | BlarAI finding (source) | Gov touch | Publishable | Redaction needed |
|---|---|---|---|---|
| E1 | Raw WFP block keyed to an account identity held under the installed security suite, 3 of 3 (evidence doc C1) | P9; CD-2; N2; ADR-002 "enumerate registered firewall products first"; Q1 seam 6 | yes; needs LA before any claim row changes | Account name to "a dedicated low-privilege account"; SID values, stub-listener port, operator profile and fleet paths, machine name; keep the suite vendor as the Governator already names it for its own measurements; keep filter structure (provider, sublayer, weights) as mechanism |
| E2 | Loopback permit on versus off, 3 of 3 each, error 10013 (C7, C8) | CD-2 | yes | Same as E1; drop the real model server's name and port |
| E3 | The measured filter was a dynamic session that vanishes when its installer exits (ADR-045 Decision 4) | Honesty obligations: liveness canary; "a gap bounded by time beats a gap hidden" | yes | Remove script and task names |
| E4 | A refusal entry naming an AppContainer is ignored: 12 of 12 launched runs (report finding 1; `deny-ace-check.json`) | Q1 seam 7 (A4: AppContainer from user mode works, child inheritance untested) | yes | Fixture root names (`C:/blarai-spike-1740` family) to neutral names |
| E5 | A fully restricted token can be singled out by a network rule; a write-restricted token cannot (finding 2) | P9; the third party's statement that the firewall cannot match a restricted token's second list | yes | Fixture paths; synthetic identity values |
| E6 | Restricted tokens launch only with a one-step derivation and a default access list granting the restricting identities (`0xC0000142` otherwise) (finding 3) | Seam 7; A4 | yes | None beyond paths |
| E7 | git-bash fails to start under every restricted-token and container setup, for different recorded errors (finding 4) | B1 launcher route; P12-type maintenance cost; adapter scope | yes | Paths; state that it is one toolchain on one build |
| E8 | MXC tier 1 on build 26200.9457: loopback refused, UI-lockdown default breaks node/git/Python ctypes, administrator groups inherited from the elevated console (finding 5) | B1 row 2 (MXC); B2c ("Sandbox SDK agents opt into; not a governor") | yes | None (public software); state the build and the elevated console |
| E9 | MXC library study: no dynamic composition, no consent or IT-policy layer in shipped files; held-open sandbox only for IsolationSession and WSLC; audit mode over-grants; schema churn; open PR #1309 (`studies.json`, `skeptic-checks.json`) | B1, B2c; open lesson "mechanism separate from policy"; competitive section | yes | Local download paths under the throwaway root; coder-specific "fit for the fleet" paragraphs |
| E10 | BRK262 content: identity, containment, manageability, dynamic composition, supervision, Agent 365 integration (transcript, section 6 below) | B1 row 2; B2c; decision 5 | yes, as a short cited summary with timestamps and the video title; quotes kept brief | Local transcript path; do not copy the transcript wholesale (copyright and auto-caption errors) |
| E11 | Microsoft servicing criteria as read live: dedicated account ("User boundary") and AppContainer serviced; restricted token not named; UAC not serviced (report) | ADR-002; Seam 7 | yes | None (public page, read date) |
| E12 | Workstream-0 source reads: Codex (dedicated accounts plus write-restricted token), srt (WFP block keyed to user, loopback ports), nono NEP-0005 (draft), MXC tiers | B1 row 2; ADR-049 "relation to #1669 and srt" | yes | Commit SHAs are public; drop BlarAI ticket text |
| E13 | Gray Swan AI section (hosted classifier; example configuration fails open) (`ws0-grayswan.md`, report) | B2c competitor list | needs LA | A statement about a named company's product; keep to what was read, hedged; the Governator's own rule 9 bars anything leaving the machine |
| E14 | Landscape matrix: 110 rows; no vendor ships all five questions; strong pattern appears six times | Concept spec R-list; decision 5 (contribute vocabulary to an existing standard) | yes | Remove every BlarAI sub-row and register citation (section "BlarAI's row" and the composite) |
| E15 | Microsoft Agent Hooks and Agent Control Specification re-derive the approval identity and fail closed; both say they are not a boundary against a hostile host | ADR-003; vocabulary and decision design | yes | Same cut as E14 |
| E16 | Control variation measured before comparing (3 to 13 % on timings; 45 of 45 outcomes identical in 7 runs); prediction against launch 48 of 48 and 15 of 15 | Grade definition of MEASURED; P2, P3 (n=15, n=30) | yes | Paths |
| E17 | Account-level containment limits: not per-action governance, binds only what runs inside the account, administrator and kernel adversaries out of scope, setup is not self-service (ADR-049) | N2 wording; audience question (decision 6) | yes | Ticket references fine; remove BlarAI-specific provisioning facts |
| E18 | A dedicated account inherits broad-group grants (C2b; report section 3 table) | Seam 7; Microsoft treats such access as authorised, not a vulnerability | no as measured (folder names and BlarAI configuration); yes as a one-line general lesson | Fleet, models and projects folders are BlarAI configuration; only the general lesson crosses |
| E19 | `C:\Windows\Temp` lock change after 2026-10-08 (#1742) and a candidate cause in BlarAI's dispatch tooling | none | no | BlarAI-internal tooling and machine state |
| E20 | Codex sandbox accounts left on the machine lack a firewall rule and can write BlarAI folders (#1743) | B2c; N-list "fully governed" | needs LA | Names a third party's installer behaviour on this machine; also reveals BlarAI folders |
| E21 | Trust-spine gaps A to D and the 15 proposed items (verify chain on load, `decision_source`, approval binding) | Concept spec "record"; liveness canary | mechanism yes, code and register rows no | Describe the pattern ("verify on load, fail loud on tamper"); drop `AuditLog` paths and register row numbers |

Counts (recounted row by row): 17 yes after redaction (E1 to E12, E14 to E17, and E21 for the mechanism only; E1 additionally needs the LA before any claim row changes), 2 no (E18 as measured, with its one-line general lesson crossing; E19), 2 need the LA first (E13, E20). Total 21.

---

## 5. Connections

All [PROPOSED]. Each pairs two real documents (verified by `ls`/`Read`). **Hypothesis** means I have no document showing it works; **Observation** means it follows from the two documents as written. Fuller design belongs to a later gate; none is started.

| # | Idea | Doc A | Doc B | Status |
|---|---|---|---|---|
| 1 | **The Governator's vocabulary plus profile as the policy layer MXC lacks.** BRK262 describes a library that compiles the agent's declared needs, the user's consent and IT policy into a container ("dynamic composition", 11:49 to 12:03). Shipped v1.0.0 has no such layer. A governor profile (a file the person owns, R14) could be the declarer and policy source that emits an MXC configuration. | BlarAI `docs/research/windows-containment-comparison-2026-10/mxc-library-study/studies.json` (study 2, point 3) | Gov `docs/founding/concept-spec-2026-09-17.md` (R14 "A profile is a file the person owns") | Hypothesis; risk: Microsoft ships that layer itself (section 6) |
| 2 | **BlarAI's Policy Agent as the adjudicator behind a Governator-style vocabulary.** BlarAI already has a canonical action object (source, destination, verb, resource, canonical arguments, sensitivity) and a single door. The Governator's vocabulary (with its derivation field) is a candidate richer front end; the Policy Agent keeps adjudicating. | BlarAI `docs/research/acs-vocabulary-adoption-design-2026-09-16.md` | Gov `docs/adr/ADR-004-first-governed-agent-and-the-governed-workspace.md` | Hypothesis; needs D3; ADR-004 quotes the door slot as "singular first-wins" while the landscape found the docstring and body disagreed (last-write-wins) and CLAUDE.md says both sites now register one request-keyed adjudicator since #1586; the three statements need reconciling before any design |
| 3 | **MXC (or an OS agent identity) as an enforcement backend under the Governator.** The governor decides; the OS container or account identity enforces what a hook cannot (network, file scope). Coverage screen gains a seam: "contained by the OS, keyed to identity". | BlarAI `docs/research/windows-containment-comparison-2026-10-10.md` (MXC tier 1 results, section 5 finding 5) | Gov `docs/founding/appendices/B1-deep-integration-routes.md` (row 2 launcher containment; "bypassed by starting the agent some other way") | Hypothesis; blockers measured: loopback refused, git-bash fails, v1.0.0 about 5 days old at study time; applies only to agents launched through it, so N3 ("Agents cannot bypass it") stands |
| 4 | **Coverage-disclosure versus BlarAI's Definition-of-Done rows.** The Governator's five-term absence vocabulary (Not measured / Measured, nothing found / Check failed / Not applicable / Not supported) would give each DoD evidence audit row a precise word for "no evidence": the Knowledge Map found the DoD has no containment row at all, though a verify suite already supplies observables. | Gov `docs/governance/coverage-disclosure.md` ("The vocabulary for absence") | BlarAI `docs/design/CODER_DEFINITION_OF_DONE.md` | Observation plus idea; BlarAI's `dod-witness` instrument-honesty work (#1241) is the nearest owner |
| 5 | **One grade vocabulary for the two claim registers.** Both registers have the same shape (claim, grade, evidence, limitation, blocks-test, switched-off test) and different grade words (MEASURED/REPORTED/GUESSED versus OBSERVED/STATIC/NOT ESTABLISHED/CONTRADICTED and M/S/V/R). Map them in one table so a finding keeps its grade across the wall. | BlarAI `docs/governance/trust-spine-claim-register.md` | Gov `docs/governance/claim-register.md` | Hypothesis |
| 6 | **OS-issued agent identity replaces hand-built dedicated accounts for the identity-keyed block.** BRK262 says agents become first-class principals; the #1740 WFP results key on an account identity that the LA had to provision by hand ("setup is not self-service", ADR-049). If an OS principal exists, the same filter conditions could key on it. | BlarAI `docs/research/account-level-containment-evidence-2026-10-05.md` (claims C1, C7) | Gov `docs/founding/appendices/A2-seams2-3-4-5-probe-record.md` (seam 4: no agent accounts existed on 2026-09-17) | Hypothesis; observable in 3(e) row 3 |
| 7 | **A liveness canary for a persistent identity-keyed filter.** The measured filter vanishes when its installer exits (dynamic session). The Governator's canary pattern (periodic call must be intercepted or the agent drops to Unknown) is the missing detector; BlarAI's own proposed boot-time posture check (items 3 and 12) is the same pattern for different locks. | BlarAI `docs/research/trust-spine-proposed-items-index.md` (items 3 and 12) | Gov `CLAUDE.md` (`honesty_obligations`, liveness canary) | Hypothesis |
| 8 | **Do not count the shared rule as corroboration.** Both repositories hold "a probabilistic layer may only tighten a deterministic allow" and "a wrongful allow is the dangerous direction". The Governator inherited its rulebook from BlarAI (ADR-001), so the agreement is one instrument, not two (the Governator's own lesson 1). Use it instead as a shared test corpus: mutants where a model-derived mapping loosens a decision must fail in both. | BlarAI `docs/research/runtime-action-governance-landscape-2026-09-16.md` ("BlarAI against the field", question 4, ADR-041 rule) | Gov `docs/LESSONS.md` (lesson 1) and `CLAUDE.md` rule 8 | Observation on derivation; test corpus is an idea |
| 9 | **The derivation field as the missing provenance in BlarAI's canonical action.** The Governator requires every field to say whether it was declared, parsed, taken from an annotation, or unknown. BlarAI's item 4 (extend the canonical action) lists CAVA's four missing fields and none says how trustworthy each is. | BlarAI `docs/research/trust-spine-proposed-items-index.md` (item 4) | Gov `docs/founding/appendices/B6-vocabulary-profiles-coverage-screen.md` | Hypothesis; any adoption on the BlarAI side is a hardening item of its own gate |
| 10 | **Measurement discipline imported into the Governator's MEASURED grade.** #1740 measured control variation first (7 runs, 45 of 45 outcomes identical, timing CVs 1.7 to 10.4 %) and checked its instrument by prediction against launch (48 of 48, 15 of 15). The Governator's grade says "run with command, version, date and result" and does not state a minimum for variation. | BlarAI `docs/research/windows-containment-comparison-2026-10-10.md` (section 2) | Gov `docs/governance/claim-register.md` (grade definitions, P2 and P3 conditions) | Idea; BlarAI's ADR-047 (evaluation protocol) is the nearer BlarAI home |
| 11 | **Governator as the policy layer over any backend (srt, nono, Codex, MXC).** The open lesson "mechanism separate from policy" and the report's finding that each backend has its own policy format point to a governor that emits per-backend policy. Facts for it already exist in the workstream-0 reads. | BlarAI `docs/research/windows-containment-comparison-2026-10/workstream-0/ws0-nono-srt.md` | Gov `docs/RECORDS_INDEX.md` (the three open design lessons) | Hypothesis; supports connection 1 |
| 12 | **The same disposition verifier lives twice.** Governator `scripts/verify_disposition.py` was copied from BlarAI and adapted. A periodic diff (read-only, on the BlarAI side) shows drift in a rule that "should not vary between them". | BlarAI `scripts/verify_disposition.py` | Gov `scripts/verify_disposition.py` | Observation (both exist); the Governator journal states the copy; I did not diff them |
| 13 | **Shadow observation as a source of real BlarAI measurements the Governator cannot get elsewhere**, bounded by ADR-004 ("proves the governor works and proves nothing about whether the product works": no coverage row earned on BlarAI may be generalised). The bridge should record that limit on every row it exports. | Gov `docs/adr/ADR-004-first-governed-agent-and-the-governed-workspace.md` | BlarAI `docs/adrs/ADR-049-Governator-Venture-Reopened.md` (limits list) | Observation |

---

## 6. Competitive and platform risk

### 6.1 Facts, from sources

Sources: transcript `docs/research/windows-containment-comparison-2026-10/sources/ms-build-2026-brk262/transcript.txt` (28:34; auto-captioned, captions garble some words); the video's metadata `CU4Wngb3JnA.info.json` (title "Building Agents You Can Trust on Windows | BRK262", channel Microsoft Developer, upload date 2026-06-03, duration 1720 s); MXC library study; the #1740 report.

- The talk's framing (02:06 to 02:20): "we cannot rely on the agent to self-govern ... even best effort prompting and prompt engineering can't solve this".
- Three platform primitives (05:15 to 05:56): agent identity "distinct from that of the human user"; containment, "a controlled environment where their blast radius is limited"; manageability, "an IT admin can deploy, monitor, govern, and enforce the policies".
- Identity (06:02 to 08:00): agents "a new type of identity ... security principle [sic]"; policies on what they may join; "whatever they do do needs to be audited by the system". The demo ran an agent gateway "as a different user account and in a different session".
- Containment (09:15 to 18:03): one sandbox per action; "isolation boundary needs to be proportionate to the risk"; MXC library "designed to help you create containers based on policy"; the developer and agent "declare the security requirements" and the library "match[es] that against the policies of the system and the policies defined by IT"; then "assemble together the right container for the job. That process is something we call dynamic composition" (11:49 to 12:03). Backends named: Windows, WSL, Linux, micro-VMs, cloud PCs; Hyperlight with NanVix demonstrated.
- Manageability (18:26 to 20:25): "IT, or you the user, need to be able to specify what you do and don't allow your agents to do"; supervision; consent "as a continuous thing"; "we earn autonomy with evidence".
- Product facts: GitHub Copilot CLI and SDK ship a sandbox "currently under the experimental flag", moving to GA (21:16 to 21:30); MXC use brings "Agent 365 native integration" with Defender, Entra, Intune and Purview (27:25 to 27:48); partners named include OpenAI, Hermes, Nvidia and OpenClaw (26:20 to 26:29); "try MXC right now" (28:16).
- What shipped (library study, `studies.json`): MXC v1.0.0 (tag commit 7bf21024; released 2026-10-07 per the report) contains no feature named dynamic composition, no consent layer (the only "consent" is for telemetry, off by default) and no IT-policy layer; the nearest piece is an open, unmerged proposal (PR #1309, "Policy Store", one contributor, changes requested) that composes per-tool allow lists from data embedded at build time. A held-open sandbox exists only for IsolationSession (Insider build, forces open network) and WSLC. Schemas 0.6 to 0.8 were declared supported on 29 September and rejected on 7 October without being listed as breaking. No CVE or advisory for MXC itself was found. Binaries are Authenticode-valid.
- The Governator's own earlier record: MXC is "Sandbox SDK agents opt into; not a governor" (B2c table); Defender for Endpoint's agent runtime protection (preview from June 2026) uses vendor hook interfaces, enterprise licences (B1 point 2); Codex documentation now calls MXC "recommended" and its own modes "legacy fallbacks" (#1740 report, table "Who uses what").
- Microsoft services the dedicated-account and AppContainer boundaries as security boundaries; a bare restricted token is not named (servicing criteria read live, #1740 report).

### 6.2 Inference (mine; flagged as such)

1. **The problem statement is validated, the packaging is not the Governator's.** Microsoft says what the Governator's N-list says (an agent cannot be trusted to govern itself) and answers with platform identity, a container library and IT management. Inference: the cross-agent action vocabulary, the person-owned record and the honest coverage screen (the Governator's three "nobody ships for a person's own machine" assets, study "Outcome first") are not claimed by anything in the talk.
2. **What the talk puts at risk.** (a) A Governator-built containment route: MXC is free, MIT-licensed, adopted by Copilot CLI and (per Codex's docs) preferred by OpenAI. The Governator should not build its own launcher containment; it can sit above it (connections 1 and 3). (b) The hand-built dedicated account as a differentiator: if the OS issues agent principals, that mechanism commoditises (connection 6). (c) The window estimate in B2c (GUESSED, 9 to 24 months for a consumer per-agent surface): the talk is enterprise-managed but says "IT, or you the user"; it neither closes nor refines that window.
3. **The risk Microsoft's own layer closes the gap.** If MXC's policy-matching layer ships, a governor profile is redundant for MXC-launched agents. The library study dates the shipped code at v1.0.0; the observable is in 3(e) row 4. Until then, "the talk describes direction, the code does not".
4. **Manageability on this machine.** The Governator's seam 3 measured an agent-governance configuration service provider and a Defender-held `mcpFilter` slot (P11). Inference only: these are the on-device parts of the manageability story. They are why the Governator must not promise that a third party can occupy those slots (P11 limits stand).
5. **Dependency risk of adopting MXC as a backend.** 5-day-old v1.0.0, schema churn, supply-chain notes (npm package without provenance; two dependencies run install scripts), and a launcher that refused host-loopback on this build. The Governator's measured maintenance-cost law (cost scales with agents times Windows branches, P12) suggests one backend is a bounded commitment and two are not.
6. **Standards.** BlarAI's landscape reads OWASP's Agent Control Standard as the Microsoft Agent Control Specification in a new home (the landscape marks this as inference). Governator decision 5's recommendation (contribute the vocabulary into an existing vendor-neutral standard) therefore points at Microsoft-originated text. This is a reason to keep decision 5 open, not to act on it.

### 6.3 What this section does not show

Nothing about Microsoft's plans for consumer editions; nothing about Q&A or slides (transcript ends at the applause); no measurement of MXC beyond tier 1 and its `--probe`; no source read of Agent 365, Entra or Intune behaviour (the talk's manageability claims are V grade).

---

## 7. Proposed process: keeping the two knowledge systems connected without breaking the wall

All of this is a proposal for the LA's decision D4. Nothing here is built.

**7.1 An identifier-keyed bridge table, on the BlarAI side only.** A section of `GOVERNATOR_BRIDGE.md` (or a sibling file) with one row per link and these columns: Bridge ID (BR-nn) | BlarAI record (path plus finding or ticket ID) | Governator record (path plus P-number, ADR number, decision number or lesson number) | relation (supports / qualifies / contradicts / answers an open question / duplicates) | flow state (not exported / candidate / exported on a date as a named Governator file) | redaction class | LA approval (comment or register ID) | last checked (date plus the file modified time of both sides). The table holds identifiers and paths, never excerpts of either side's protected content. Reason it is on the BlarAI side: BlarAI is allowed to name the Governator freely (X5); the reverse is where the gate lives.

**7.2 A redacted export step, with the Governator in control of what enters.**
1. BlarAI side writes an export candidate as a new document aimed at the Governator (never the original), from the section 4 "yes" rows, in a staging folder inside BlarAI (not shared, no junction, no symlink).
2. A script produces the redacted derivative and prints a substitution report listing every replacement (the founding precedent).
3. A BlarAI reviewer who did not write it reads the derivative against the never-cross categories, including the cases the gate cannot see (lower-case names, probe names, SIDs, fixture roots, paths other than the local-data path, HTML and binary files).
4. A Governator-gated session (its own comprehension gate, per its `CLAUDE.md`; ADR-049 says the repository stays untouched until scoped) imports it, runs `tests/test_never_cross.py`, files an import note naming the BlarAI source path, BlarAI commit, the substitution report and the bridge ID, and records the finding in its register only if its own decision boundary allows (anything that changes a claim is the LA's).
5. The BlarAI side updates the bridge row to "exported" with the Governator file and the date, in the same motion.

The Governator side's own form for imports (a dated "evidence imports" folder, or appendix files in `docs/founding/` style) is the Governator's decision; this is a suggestion.

**7.3 A periodic cross-check, read-only.** Triggered by events, not a schedule (no scheduled window exists, DEC-14): after any BlarAI merge touching containment, the trust spine or the Windows studies; after any Governator register, ADR or decision change; and on any new Microsoft MXC release or Windows build noted by a session. A script on the BlarAI side reads (never writes) the Governator repository and checks: both paths of every bridge row exist; either file changed since "last checked"; no flow state says "exported" without a Governator file; BlarAI facts quoted inside Governator records still match their source. First candidates found while preparing this draft:
- Governator ADR-004's description of the door slot ("a singular first-wins slot, currently unoccupied") against the landscape's finding that the body is last-write-wins, and BlarAI's current statement that both sites register one request-keyed adjudicator since #1586.
- Governator N2 against ADR-049's candidate claim (D1).
- Governator `docs/NEXT-SESSION.md` and the board description (its own "Known gaps").
- The two copies of `verify_disposition.py` (connection 12).
- The KNOWLEDGE_MAP draft's statement that `docs/INDEX.md` lists none of the containment studies, and that the transcript sits in a throwaway folder (Appendix).

**7.4 Shared vocabulary.** A short mapping table of grades (section header of this document) kept in the bridge file, and the Governator's five-term absence vocabulary adopted in BlarAI's evidence audits where the LA agrees (connection 4).

**7.5 Rules the process must never break** (each tested off before use, per both rulebooks):
- No automatic sync; no shared directory; no link between the two trees; nothing in the Governator repository reads BlarAI.
- The bridge document and any BlarAI-side export candidate are never copied into the Governator repository; only the redacted derivative is.
- The bridge records "needs LA" rows and never resolves them.
- Control tests: (1) plant a known refused string in a candidate and confirm the redaction script rejects it and the Governator gate fails if it slips through; (2) rename a Governator file and confirm the drift check flags the bridge row; (3) mark a row "exported" with no Governator file and confirm the check fails.

**7.6 Where this lands in the knowledge system.** A topic card (section 3) in the Knowledge Map beside the containment cluster; two rows in `connections.md` (connections 1 and 3 above are the first); a line in `FOLDER_CATALOGUE` for `docs/research/GOVERNATOR_BRIDGE.md`; the Governator's own `docs/RECORDS_INDEX.md` already lists BlarAI pointers, so the Governator side needs only a pointer to the bridge's existence if its owner agrees.

---

## Appendix: what was checked, what was not

Checked by `ls`, `Read` or `grep` (2026-10-11):
- Governator: `CLAUDE.md`; `docs/RECORDS_INDEX.md`; `docs/governance/{claim-register,coverage-disclosure,decision-register,never-cross}.md`; `docs/adr/ADR-001` to `ADR-004` (title, status, ADR-004 in full); `docs/founding/` headings of the study and concept spec, appendices B1 and B2c (relevant parts), A3/A4 string occurrences; `docs/LESSONS.md` headings; `docs/NEXT-SESSION.md` (opening); `docs/journal_fragments/2026-10-10-records-index.md`; tail of `docs/BUILD_JOURNAL.md`; `tests/test_never_cross.py` in full; `scripts/` listing.
- BlarAI: `docs/adrs/ADR-049` in full; ADR-042 (header, context, decision 1), ADR-045 (decisions 1 to 6), ADR-046 (header and context); `docs/research/windows-containment-comparison-2026-10-10.md` lines 1 to 440; `mxc-library-study/README.md`, `studies.json` summaries; `runtime-action-governance-landscape-2026-09-16.md` (outcome, matrix groups D and E, roll-up, verdicts, proposed list); `trust-spine-proposed-items-index.md`; `pcaa-placement-and-blarai-mapping-2026-09-16.md` (outcome); the first 40 lines of the evidence document; the BRK262 transcript 00:01 to 28:34 in full.
- Paths confirmed to exist: all those named in the tables, plus `docs/governance/trust-spine-claim-register.md`, `docs/DECISION_REGISTER.md`, `docs/ROADMAP.md`, `docs/design/CODER_DEFINITION_OF_DONE.md`, `docs/design/CODER_CONTAINMENT_DESIGN_OVERVIEW.md`, `tools/probes/containment_arms/`, `scripts/verify_disposition.py` on both sides, `docs/reviews/final-review-1740-disposition-2026-10-11.md`.

Corrections to the brief:
- `docs/research/KNOWLEDGE_MAP.md` did not exist when this was drafted (it landed in merge 43a94b4f) (with `connections.md` and `FOLDER_CATALOGUE-draft.md`). Its section 2 schema is the schema used in section 3 of this document.
- There is no `sources/ms-build-2026-brk262/transcript.txt.txt` and no `docs/research/mxc-library-study/`. The study is at `docs/research/windows-containment-comparison-2026-10/mxc-library-study/`. The transcript is at `docs/research/windows-containment-comparison-2026-10/sources/ms-build-2026-brk262/transcript.txt` (plus `.vtt` caption files and `CU4Wngb3JnA.info.json`) in the throwaway fixture root that the report says is deleted at the teardown step. Recommendation (the session's, not performed): bank the transcript and the metadata file under the repository before teardown, with the video title, channel, upload date and URL; the library-study README currently says "transcript at ... not copied here".

Not verified: any Vikunja ticket text (BlarAI or Governator boards); the Governator git history and whether its working tree has uncommitted changes; the machine's current state versus the Governator's 2026-09-17 measurements; the full text of `ws0-*.md`, the evidence document beyond its first sections, the raw data directories, `skeptic-checks.json` and the primer HTML; whether `docs/INDEX.md` lists the containment studies (taken from the Knowledge Map draft); the contents of ADR-041, ADR-044, ADR-020 and ADR-030 beyond their existence; the diff between the two `verify_disposition.py` copies; whether the Governator's founding appendix names (`BlarAIStudyProbe1549`, `BLARAI-STUDY-1549-NONADMIN`) are acceptable under the rule (flagged, not judged); the exact label counts in section 4 beyond my tally below the table (which I recounted: 17 yes, 2 no, 2 needs LA).
