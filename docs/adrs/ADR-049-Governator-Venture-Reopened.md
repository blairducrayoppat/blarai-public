# ADR-049 — The Runtime-Governance Venture ("The Governator") Is Reopened, on a Narrower Claim Than the One It Was Cancelled For

**Status:** Accepted (LA decision 2026-10-05); supersession scope CONFIRMED by the LA 2026-10-05 ('Your recommendations are approved', recorded on #1693 comment 3898: this approval was given to the session's recommendations in general and was recorded by the session as covering the scope). Reopens a *venture*; decides nothing about what the venture is. **No BlarAI runtime change.** Supersedes **ADR-042 Decision 1 and the repository disposition in ADR-042 Decision 6**; flags **ADR-042 Decision 3's ground for re-examination**; ADR-042 Decisions 2, 4, 5 and the rest of 6 stand.
**Date:** 2026-10-05
**Deciders:** LA (the reopening). The session recorded it; the session did not take it and does not claim to have recommended it.
**Related:** #1693 (the scoping gate, feasibility refresh and plan) · #1549 (the feasibility study, comments 3510 / 3551 / 3569) · #1590 (ADR-042's record) · #1671 (raw WFP block, comments 3873 / 3891 / 3894) · #1689 (confined model account, comments 3882 / 3896) · #775 (coder containment, comments 1653 / 1654 / 3874 / 3893) · #1682 (productionising the egress filters) · ADR-042 · `docs/research/runtime-action-governance-product-feasibility-2026-09-17.md` (the study, merged `50f7100d`, not retracted) · the evidence document `docs/research/account-level-containment-evidence-2026-10-05.md` (on branch `docs/containment-evidence`, pending merge; not on disk when this ADR was written, so every figure below is cited to the Vikunja comments and the raw data in `C:/Users/mrbla/blarai-research-data/wfp-spike` and `confined-model-spike`)

## Context

ADR-042 cancelled the standalone venture on 2026-09-18. The LA's reason, in his words: *"if we can never truthfully say 'agents cannot get around this' then we don't have a product."* That rested on the #1549 study's central measured finding: every enforcement seam a third party can reach on Windows is **cooperative** — the agent's own program runs the governor and honours its answer, a flag skips it, a crashed hook fails open, a shell command is one opaque string. The one non-cooperative seam the study probed, a per-process firewall rule, **failed silently** (37/37 requests succeeded) because a third-party security product owned the firewall categories.

On **2026-10-05** the LA decided, in his words: *"between this and the BitDefender study results, The Governator is reopened."* **The session's reading, which the LA may correct:** "this" was taken to mean the account-level containment evidence described below, and the session did not identify a separate document called "the BitDefender study". The Bitdefender results it can trace are the #1549 seam-6 finding (Bitdefender owns the filtering, a per-process rule is inert) and the conditions under which the new measurements were taken (Bitdefender present and running). Which results he meant is his to say.

**What the new evidence is.** Two spikes on this machine, both with the LA present, both recorded on tickets with raw data on disk:

1. **#1671 (comment 3873, corrected by 3891 and 3894).** A raw Windows Filtering Platform (WFP) BLOCK filter keyed to the dedicated `blarai-coder` account enforced while Bitdefender owned filtering: **3 of 3 live runs identical.** Coder baseline egress open; with the filters, coder outbound blocked, operator traffic unaffected; engine closed, filters gone, coder egress open again (so the block is attributable to the filters, not to the probe's exception-counts-as-blocked rule). Raw reports: `wfp-spike/result-20261004-235941.json`, `result-20261005-000002.json`, `result-20261005-000028.json`.
2. **#1689 (comment 3896).** A restricted, non-interactive, non-elevated local account (batch logon, session 0) loaded a model on the Arc 140V iGPU through OpenVINO GenAI, generated tokens, was **denied** every operator secret read (8 of 8) and outside write (4 of 4) with positive controls allowed, and — with the raw WFP block keyed to its SID — served a completion over loopback to the operator while its own outbound probe was blocked. Raw data: `confined-model-spike/runs/`.

**The limits of that evidence, exactly as the sources state them.** These are the reason this ADR is narrow.

- **One dimension:** network egress and file access of a process tree under a dedicated account (#1693 description).
- **One machine, one antivirus, one driver:** this laptop, Bitdefender, GPU driver 32.0.101.8831 (#1693; #1689 comment 3896).
- **IPv4 TCP 443 only.** The #1671 observations are single TCP connects to 1.1.1.1:443 (baseline also 8.8.8.8:443), each run holding the filters about 3–5 seconds per #1671 comment 3891 (the raw timestamps give an upper bound of 5.1–5.35 s), in a **dynamic** WFP session. #1671 comment 3891: "'Enforces' is the observed result of those three runs, not a proof of general enforcement." Not tested (comment 3873): persistence across reboot, IPv6 destinations, UDP/DNS, non-443 ports, behaviour under a Bitdefender update or restart, a real coder dispatch under the block.
- **The loopback permit was shown against a stub listener** the spike started on 127.0.0.1:8000, not the real model path (comment 3891). #1689 later served a model completion over loopback, but with a 4B INT8 model, one prompt, 64 tokens; speed parity, the 14B + draft pipeline, streaming and a Bitdefender-isolated run were **not measured** (comment 3896).
- **Not per-action semantic governance.** Nothing here decides whether an individual action is allowed; it bounds where a process tree can reach (#1693).
- **Nothing outside the account.** Software that runs as the operator is not covered (#1693).
- **Administrator and kernel adversaries are out of scope** (#1693).
- **The setup is not self-service.** Account, ACL and firewall changes are blocked for the harness and are LA-run provisioning (#1689 comment 3882; #775 comment 3862). Whether that is acceptable for any audience is not established.
- **Results that cut against the candidate claim ("cannot reach the network or read your files"), from the same tickets:**
  - `B:\models` is writable by the confined account (#1689 comment 3896, informational; #1692), as is `C:\Windows\Temp`. In the #1689 spike the account was denied all 8 operator secret reads and 4 outside writes; those two writes were allowed.
  - `blarai-coder` holds Modify, and so read, on the whole `C:\Users\mrbla\projects` folder (#1678; #775 comment 3879).
  - `C:\blarai-fleet` is writable by every local account (#1686; #775 comment 3879).
  - Coder egress is open today: the shipped containment is `off` (#775 comments 3858, 3879). The block was only demonstrated in a dynamic session held open by the operator's elevated process.
  - The loopback permit was shown only against a stub listener in the #1671 spike (comment 3891).
  - The first #1689 Test A run misreported "access denied" as "not denied" through a classifier bug in the spike, fixed and rerun (comment 3896).
- **Source correction.** #1671 comment 3873 called this result a "re-visit trigger" on #775; comments 3893 and 3894 correct that: the LA's named triggers (#775 comment 1653) are a Bitdefender posture change, the VM containment leg going live, or an egress incident. The result is new evidence that the gap is closable, not a trigger he named.

## Decision

1. **The venture cancelled in ADR-042 Decision 1 is REOPENED.** This **supersedes ADR-042 Decision 1 only.** What is reopened: the venture as a standalone product, the repository `C:/Users/mrbla/governator` (kept, **untouched until scoped**), and the board and ADR line of work.
2. **What else of ADR-042 changes, stated precisely (the session's reading; confirmed in general form, see Status):**
   - **Decision 6's repository disposition is superseded.** ADR-042 left `C:/Users/mrbla/governator`'s fate to the LA (archive, keep, or delete) and barred any session from working in it. This ADR keeps it, untouched until a scope exists. The rest of Decision 6 (no BlarAI runtime behaviour was ever changed; nothing published, purchased, registered or applied for) stands.
   - **Decision 3 (the asymmetric boundary is moot) is NOT re-affirmed.** Its stated ground was that "there is no second party", which a returning product may remove. Nothing is derived from the 2026-09-17 register row meanwhile; whether the boundary stays moot is re-examined at the scoping gate. The locks it leaned on are BlarAI's own and unchanged.
   - **Decisions 2, 4 and 5 stand as recorded:** the capabilities in BlarAI continue, the appendices are kept, the study is not retracted.
3. **What is explicitly NOT decided.** These are the LA's and are to be scoped, not assumed:
   - the product's **claim** (the candidate in #1693 is *"an agent run inside the contained account cannot reach the network or read your files; enforced by Windows, not by the agent"* — a candidate, not an adopted claim);
   - its **form** (specification plus reference implementation, or a product), **audience**, **licence**, **publication**, and **naming and trademark** (the name "The Governator" came from the cancelled line of work and is not re-ratified here);
   - its **relation to a third-party open-source agent sandbox (#1669) and to Anthropic's sandbox runtime**;
   - **funding and time commitment.** ADR-042 records the study's attention estimate for the specification path, 8–14 hours a week, and "effectively full time" for a paid product. That estimate is on record; **whether the LA will spend it still needs a decision.** The session has not assumed a figure, a date or a budget.
4. **No build before a gate.** The session must present a full comprehension gate for the reopened program (a new engagement) and receive confirmation before any build work. #1693 carries `blocked-by: LA confirmation of the scoping gate`.

## Alternatives considered

- **Option A — keep the venture cancelled (ADR-042 unchanged).** **Rejected by the LA's decision;** the reasoning is the session's, from the evidence. ADR-042's objection was that no inescapability claim could be made. The new evidence supports a claim for one dimension where the enforcement is an operating-system filter keyed to an account, not a hook the agent runs, so the agent's cooperation is not what makes it hold (session's reading of #1671 / #1689; the study's cooperative-seam finding was about seams a third party reaches *through the agent's own program*). The finding the study measured has not changed; what changed is that one seam outside that set was shown to hold here.
- **Option B — reopen only as a BlarAI-internal capability.** **Rejected, as redundant:** this is what ADR-042 Decision 2 already retained, and the containment work is already BlarAI engineering (#775, #1682, #1689). Reopening the *venture* is only meaningful if it concerns something other than BlarAI's own work. The session's reasoning.
- **Option C — reopen as a specification-only effort now.** **Not chosen, and not rejected:** it is one of the forms the LA has not decided (Decision 3). Choosing it here would pre-empt the scoping gate. The study's evidence for it (8–14 hours a week, one adapter, the one asset that survives being copied) is in the study and is not re-weighed here.
- **Option D — reopen the venture and scope it at the gate. (CHOSEN, by the LA.)**

## Consequences

- **No BlarAI runtime change.** Byte-identical behaviour. This ADR, the register row and the journal fragment are the whole footprint. No BlarAI posture is altered; the accepted coder-egress gap (#775 comment 1653) is unchanged by this ADR, and whether to reopen it is the LA's call (comment 3893).
- **The evidence document becomes the cited basis**, once merged from `docs/containment-evidence`. Until then the Vikunja comments and the raw data directories are the basis.
- **The claim the product could truthfully make is NARROWER (the session's reading) than the one ADR-042 asked for.** ADR-042 asked for "agents cannot get around this". The evidence supports at most a bounded statement about one dimension, on one machine, under stated conditions, for software run inside a dedicated account. It does not support the broader claim, and it does not settle whether the narrower claim is enough of a product. That judgement is the LA's.
- **A feasibility refresh is the next technical step** (#1693 step 3): what the new evidence changes in the 2026-09-17 study and what it does not. It is the session's to run and does not wait on the LA.
- **The reopening does not rest on a larger sample.** It rests on 3 identical runs and one account-level model-serving run. #1693 and this ADR name the limits; they do not remove them.
- **What this record does not settle:** whether reopening was correct. The limits are recorded in Context rather than omitted.

## Re-visit triggers

(The session's proposal, not the LA's.) Evidence that **contradicts the observations**: a different antivirus product, a Bitdefender or GPU-driver update, or any bypass of the dedicated-account block. And the LA's call at any time. Per ADR-042's own discipline, no date is set.
