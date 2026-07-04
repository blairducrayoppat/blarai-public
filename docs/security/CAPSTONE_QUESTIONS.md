# Capstone Security Presentation — The Questions It Must Answer (#612)

**Purpose.** This is the **single accumulating list of questions** the #612 capstone presentation must
answer, so the User-Operator (LA) **fully understands the BlarAI security posture before signing off on
removing the air-gap (#598)**. Per #612 comment 921, the capstone is the LA's *pre-decision deep-dive*: the
deck is delivered, the LA goes through it and asks questions, **any work that surfaces is tasked to an agent
and resolved — then the LA signs off (or not)**. This list is what makes that review systematic instead of
ad hoc.

**Status:** v1.2 — opened 2026-06-08; the four proactively-proposed questions (Q13, Q41–Q43) accepted as required
2026-06-08; **§L audit-reconciliation added (LA-directed 2026-06-08).** **This list is OPEN and meant to grow.**
Add questions as they occur (see §M). Every question here is a deliverable requirement for the deck; the deck
answers *all* of them.

**Provenance (how this was assembled).** A search of the repo and the task tracker found **no pre-existing
consolidated list** — the questions had been living scattered. This doc consolidates them from the on-record
sources, tagged so you can see where each came from:
- **[BASE]** — the LA's four explicit "base/guideline" data-map questions (#612 comment 936 / `DATA_MAP.md`).
- **[REQ]** — derived from the #612 description's 8 must-cover requirements.
- **[SIGNAL]** — derived from the LA's recorded design/threat signals (#555 comments 783/784/787; #612 cmt 921).
- **[MAP]** — from the `DATA_MAP.md` §7 hardening register.
- **[ACCEPTED]** — originated as a proactive agent proposal; **LA-accepted 2026-06-08 → required** (now the same standing as every other question).

**How to use it.** Each question has an ID (Q#) and a deck-coverage box: ☐ unanswered · ◐ drafted · ☑ answered.
When the deck is built, every box should reach ☑. The **residual-risk / air-gap-removal questions (§H) are the
heart** of the LA's deep-dive (#612 cmt 921) — weight the deck accordingly.

---

## Presentation design & format (LA-directed 2026-06-08)

These govern HOW the deck presents, not just what it answers. **Audience:** a technically-literate person who
is **not familiar with this domain** (AI security / governance) — plain language on the surface, real technical
depth underneath, never dumbed-down-wrong.

- **Level of detail = tiered, not flat** ("not too much, not too little"). For the audit reconciliation (§L): a
  **summary scorecard** for the whole set + a compact **per-domain** before→after, with a **dedicated card/slide
  ONLY for the findings that earn it** — every Critical, the significant Highs, and **every still-open/residual
  gap** (the ones the LA most needs for the gate decision). Cleanly-closed minor findings get a matrix line, not
  a slide. (Avoids a ~30-slide table-read; spends the time where it matters.)
- **Card-style per-issue treatment** for those that earn one: what it was (+ severity) → what we did (mitigation
  + evidence) OR why it's still open (+ ticket). Self-contained, plain-language.
- **Attestation gets 2 dedicated slides, at least one a strong diagram/illustration** (LA-directed). Explain what
  attestation *proves* (the system booted into a known-good, untampered state), and how BlarAI does it
  (signed-manifest + TPM-key validation = the in-scope #598 bar; PCR measured-boot deferred per ADR-028 / #627 —
  be honest about scope). The diagram carries the explanation.
- **The "explain-to-a-13-year-old" standard** (must-cover #8): every complex feature has a plain-language surface
  a non-technical person grasps, with the depth underneath. Litmus: if the LA can explain it to a 13-year-old he
  can explain it fast to a non-technical interviewer (portfolio + interview prep).
- **Companion deliverable:** standalone 13-year-old explainers of single security features, in
  `docs/security/explainers/`. Portfolio / interview-practice artifacts, built from the REAL implemented design
  and honest about built-vs-planned. First one: **defense-in-depth vs prompt injection** (agent-chosen for
  interview value — teaches the universal "defense in depth" principle via BlarAI's AI-specific threat).

---

## A. Base / guideline questions — the data map  *(answered via `DATA_MAP.md`, presented in-deck)*

- **Q1** ☐ **[BASE]** Where are the **mTLS certificates** stored, and how are they protected (per-boot regeneration, private keys never leaving the box)?
- **Q2** ☐ **[BASE]** Where are **all sensitive artifacts** stored, **who has access rights**, and **what are those rights** (the real ACLs; the "encryption is the boundary, not the file perms" point; process identity; the orphaned-SID finding)?
- **Q3** ☐ **[BASE]** Where is **sensitive data** stored (`%LOCALAPPDATA%\BlarAI\` — sessions / substrate / keystore / audit / secrets)?
- **Q4** ☐ **[BASE]** Where is the **assistant's cross-conversation memory** (`substrate.db`, encrypted; no separate memory module), and how is it protected?

## B. The trust root & the keys  *(must-cover #1, #6)*

- **Q5** ☐ **[REQ]** What is the **hardware root of trust** (the TPM 2.0), and what specifically does it anchor?
- **Q6** ☐ **[REQ]** What are the **four TPM-sealed keys** (JWT-signing, DEK-seal, audit-signing, manifest-signing), what does each do, and **what happens if the TPM is unavailable** (fail-closed refuse-to-start)?
- **Q7** ☐ **[REQ]** How is data **encrypted at rest** (the DEK envelope, ADR-025)? Walk the full chain: TPM → DEK → HKDF subkeys → AES-256-GCM ciphertext.
- **Q8** ☐ **[SIGNAL]** What is the **offline recovery key** — where is it, who holds it, and what is the **blast radius** if it is lost or exposed? (the #1 operator footgun)
- **Q9** ☐ **[MAP]** What's the difference between the **production (TPM) keystore and the dev SoftwareSealer keystores**, and how do I *know* the running system is using the strong path, not the weak fallback? *(→ Sprint-18 C5 production-posture check)*

## C. The authorization choke-point — the Policy Agent  *(must-cover #1, #5)*

- **Q10** ☐ **[REQ]** What is the **Policy Agent**, and why is it the **single authorization point** for every action?
- **Q11** ☐ **[REQ]** What exactly does the PA gate, and how does one decision flow end-to-end (CAR → adjudication → signed capability JWT → tamper-evident audit record)?
- **Q12** ☐ **[SIGNAL]** When the PA **denies or escalates**, how does the human approve, and **how is that approval authenticated**? (the Windows Hello / biometric-consent idea, #783 — is it in or deferred?)
- **Q13** ☐ **[ACCEPTED]** **Can the PA be bypassed?** What structurally stops a component from acting without a PA-minted capability?

## D. Untrusted content & prompt injection  *(must-cover #1, #4 — the hostile-page scenario)*

- **Q14** ☐ **[REQ]** How does BlarAI defend against **prompt injection** from a document or web page (ADR-013 Layers 1–3 + the provenance model ADR-023 + Amendment 1)?
- **Q15** ☐ **[REQ]** **Walk through a hostile page** attempting injection — what stops it at *each* layer?
- **Q16** ☐ **[REQ]** What is the **Cleaner** (UC-003), and what classes of attack does it neutralize?
- **Q17** ☐ **[REQ]** What is **PGOV output validation**, and what does it catch on the way *out*?

## E. Containment & isolation  *(must-cover #1)*

- **Q18** ☐ **[REQ]** What is the **VM / mTLS containment** model (host-mode default vs guest-mode), and what does **#615** add when it lands?
- **Q19** ☐ **[REQ/MAP]** What are the **process-identity boundaries** (launcher admin, UI de-elevated to Medium integrity — ADR-019), and **what still runs with more privilege than it needs** (the PA/AO no-privilege-drop finding)?
- **Q20** ☐ **[SIGNAL]** What **network listeners** exist today and how are they restricted (named-pipe local-only + `PIPE_REJECT_REMOTE_CLIENTS`; vsock host-local) — i.e. the "zero external listeners" claim (#784)?

## F. The audit trail  *(must-cover #1, #5)*

- **Q21** ☐ **[REQ]** What does the **tamper-evident audit log** record, how is it signed (ECDSA P-256 TPM, hash-chained), and **how would I detect tampering**?
- **Q22** ☐ **[SIGNAL]** What are the **known audit gaps** (tail-deletion **#606**, retention **#607**), and why are they acceptable for now?

## G. The egress controls & the air-gap itself  *(must-cover #1, #5)*

- **Q23** ☐ **[REQ]** What exactly **is "the air-gap" today** — what enforces it in code, and how do I *know* there are zero external network calls (fail-closed, no fallback)?
- **Q24** ☐ **[REQ]** What is the **egress kill-switch** (ADR-020) — how does it arm, how does it auto-trip, and **who re-arms it**?
- **Q25** ☐ **[REQ]** What is the **deny-by-default egress allowlist** (ADR-027), and how does the **exfil-screen** (block-on-detect) work?
- **Q26** ☐ **[REQ]** What is the **dev-mode interlock**, and how does it prevent ever running the production posture network-facing in dev-mode?

## H. ★ Residual risk of removing the air-gap — THE HEART  *(must-cover #3, #4; #612 cmt 921)*

- **Q27** ☐ **[SIGNAL]** After **all** the hardening, **what can still go wrong once the air-gap is down**? (the honest residual-risk register — the central question)
- **Q28** ☐ **[SIGNAL]** What is the **threat-model shift** from air-gapped to network-facing — **inbound vs outbound** exposure (#784)?
- **Q29** ☐ **[SIGNAL]** For **OUTBOUND** (web nav; future device/smart-home control): what's the **data-exfiltration** risk, and which controls bound it?
- **Q30** ☐ **[SIGNAL]** For **INBOUND** (future phone push / external ingress): what's the **attacker-reaching-the-AI** risk, and **what is NOT yet built** to guard it (the highest-risk fork)?
- **Q31** ☐ **[REQ]** What is the **live-memory attacker** gap (**#611** — unsealed DEK / decrypted cache in RAM at runtime), and why is it accepted?
- **Q32** ☐ **[REQ]** What about **PII embedded in content** (**#608**) — what's redacted, what isn't, and what's the exposure?
- **Q33** ☐ **[MAP]** Of the **`DATA_MAP.md` §7 hardening candidates** (no DACL hardening; orphaned SID; unsigned draft manifests; dev keystores; unsigned compiled cache), which are **fixed vs deferred-and-tracked**, and why is each deferral acceptable?
- **Q34** ☐ **[SIGNAL]** What is the **Tier-0→3 hardening gate** (#787 — the LA's hard gate "complete through Tier 3 before facing the internet"), and is **every tier actually complete + verified**?
- **Q35** ☐ **[REQ]** What are the **load-bearing elements** whose failure breaks the *whole* posture (TPM keys, DEK, fail-closed-no-fallback, the PA as sole authz point, the air-gap/egress guard, the recovery key), and how are they protected from being weakened?

## I. Operator footguns  *(must-cover #7)*

- **Q36** ☐ **[REQ]** What **operator mistakes** would silently break security — lose/expose the recovery key; run prod in dev-mode; skip/rush the on-chip ceremony; disable a fail-closed control "to make it work"?
- **Q37** ☐ **[REQ]** What is the **dev-vs-production posture trap**, and how do I **always know which posture I'm in** at a glance?

## J. End-to-end data-flow walkthroughs  *(must-cover #4)*

- **Q38** ☐ **[REQ]** **Local document:** load → encrypt at rest → retrieve → answer. Where is the control at each hop?
- **Q39** ☐ **[REQ]** **Future web-fetch:** fetch → Cleaner → PA adjudication → egress screen → answer.
- **Q40** ☐ **[REQ]** **Authorization decision:** request → PA adjudication → signed capability → signed audit record.

## K. Verification & assurance  *(the "is it real?" layer — LA-accepted as required)*

- **Q41** ☐ **[ACCEPTED]** For each control: how was it **VERIFIED**, not just built? What's the evidence (tests, SWAGRs, live-verify, on-chip ceremonies)?
- **Q42** ☐ **[ACCEPTED]** What is **NOT tested / NOT verified**, and what's the residual uncertainty there? (name it, don't imply full coverage)
- **Q43** ☐ **[ACCEPTED]** What would a **hostile security reviewer attack first**, and would it hold?

---

## L. Audit reconciliation — the 2026-06-03 audit, before → after  *(LA-directed 2026-06-08; the deck's closing-bookend spine)*

The deck must include an explicit **comparison against the 2026-06-03 security audit** (`docs/security/audit_2026-06-03/`):
the status of **every** issue it raised, with mitigations detailed and residual gaps highlighted. This is the AFTER to
the audit's BEFORE — the literal #612 closing-bookend purpose.

- **Q44** ☐ **[REQ]** For **every finding** in the 2026-06-03 audit: what it was (title + severity + domain) and its **current status** — fixed / mitigated / accepted-residual / still-open.
- **Q45** ☐ **[REQ]** For each **fixed or mitigated** finding: **detail the mitigation** — what was done, in which sprint/commit, and the **evidence** it works (test / live-verify / ceremony).
- **Q46** ☐ **[REQ]** For each **still-open or accepted-residual** finding: **highlight the gap**, name its **tracking ticket**, and state **why** the residual is acceptable for the gate (or what's left to close it).
- **Q47** ☐ **[REQ]** A **summary scorecard**: of N audit findings — how many closed / mitigated / accepted-residual / open, each open item tied to a ticket. The one-glance before→after.

*Vehicle: a dedicated **audit reconciliation matrix** (every finding → status → mitigation/gap → evidence), finalized at
deck-build when the posture is final; pre-stageable now to surface where things stand for gate planning. Feeds the §H
residual-risk register.*

*Format (LA pref 2026-06-08): the matrix is the **overview**; significant issues each get a digestible **card/slide**
(what it was · severity · status · mitigation+evidence OR gap+ticket) at a calibrated detail level — not buried in dense
table rows. Audience = technically literate but NOT familiar with this domain, so define domain terms; per-issue depth
where warranted, grouped/summarized where not (no slide-per-trivial-finding). Plus two 13-yo-level explainers w/ diagrams
(must-cover #8): the **attestation** process (~2 slides, ≥1 diagram) and **host↔guest isolation + secure data flow**
(~2 slides, ≥1 diagram) — see #612 deck-design comment.*

---

## M. Open slots — ADD YOUR QUESTIONS HERE

This list is the accumulation surface. Append any question you want the deck to answer; it becomes a deck
requirement. (During the #612 Q&A, new questions raised here get tasked + resolved before sign-off, per cmt 921.)

- **Q48** ☑ **[Q&A 2026-06-10]** **(extends Q19)** What **OS-level privilege separations** are available for the **Assistant Orchestrator (AO)** beyond integrity-lowering — **Job Objects**, **AppContainer**, **restricted tokens / service accounts** — with the pros/cons of each and a recommended path forward? *(Answered live; full mechanism analysis + recommendation in `capstone_2026-06/deep_dive_log.md`. Outcome: tier-1 = integrity High→Medium + a Job Object that blocks child-process creation + privilege-strip (→ a separate agent owns this); **#651** OS-level egress firewall coupled to #598; AppContainer deferred as a GPU/TPM-inside-sandbox research spike on the young Arc/Lunar-Lake driver stack. The Q19 "AO does not de-privilege" residual is ACCEPTED for the egress-only posture; this is the menu to retire it.)*
- **Q49** ☑ **[Q&A 2026-06-10]** **(extends Q20)** What **is a named pipe** as used in the WinUI bridge, **how does it move data across an integrity boundary** (Medium-integrity UI ↔ High-integrity backend), and **what is the peer-authentication gap**? *(Answered live: the explicit security descriptor with a Medium mandatory label — `services/ui_backend/src/server.py:83`, `D:P(A;;FA;;;<user>)(A;;FA;;;SY)S:(ML;;NW;;;ME)` — lets the de-elevated client connect; the integrity level gates who may OPEN the pipe, not what flows through it. Peer-auth gap tracked as **#640** (neither end pins the other's PID/identity → squatting risk), raised to HIGH and LA-scoped onto the #598 gate. Detail in `deep_dive_log.md`.)*
- **Q50** ☐ _…_

---

**Refs:** `DATA_MAP.md`; `SECURITY_ROADMAP_air_gap_removal.md`; #612 (capstone) desc + comments 921/936;
#555 (audit "before" deck) comments 783/784/787; #598 (the GO/NO-GO gate); gap tickets #606/#607/#608/#611;
ADRs 013/018/019/020/023/025/027. **Maintenance:** this is a #598/#612 evidence artifact — keep it current;
every question reaches ☑ before the deck is considered complete.
