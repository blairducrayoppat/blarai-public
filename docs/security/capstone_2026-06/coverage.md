# Capstone Deck — Coverage Tracker (Q1–Q47 → section → ☑)

**Purpose.** Proves the #612 capstone deck answers *every* question in
`docs/security/CAPSTONE_QUESTIONS.md` (the read-only spec). The deck is complete only when
every box is ☑. This is the deck-builder's own tracker — `CAPSTONE_QUESTIONS.md` is left untouched.

**Deck:** `capstone_presentation.html` (built from `deck_outline.json` via `build_deck.py`;
outline authored in `make_outline.py`). 50 screens, 9 diagrams. Built 2026-06-08; the four
densest reconciliation slides auto-paginate (3 detailed cards / 6 attack cards per screen) so
each slide fits one screen — verified zero-overflow at 1440×810 in a headless render.

**Method note.** Statuses below are the disk-rooted reconciliation result (five read-only verifier
passes over current code + my own spine verification of the credibility-core claims). Every "fixed"
claim cites real code / commit / test in the deck cards.

---

## A. Data map (Q1–Q4)

| Q | Theme | Deck home | ☑ |
|---|---|---|---|
| Q1 | mTLS certificate storage + per-boot regen | "Where Everything Lives — the Data Map" | ☑ |
| Q2 | All sensitive artifacts, access rights, encryption-is-the-boundary | "Who Can Read It — and the Real Boundary" | ☑ |
| Q3 | Sensitive data location (%LOCALAPPDATA%\BlarAI) | "Where Everything Lives — the Data Map" | ☑ |
| Q4 | Cross-conversation memory = substrate.db, encrypted | "The Assistant's Memory — substrate.db, Encrypted" | ☑ |

## B. Trust root + keys (Q5–Q9)

| Q | Theme | Deck home | ☑ |
|---|---|---|---|
| Q5 | Hardware root of trust (TPM) | "The Trust Root — the TPM and Four Sealed Keys" | ☑ |
| Q6 | Four TPM keys + fail-closed if unavailable | "The Trust Root …" | ☑ |
| Q7 | At-rest encryption chain (TPM→DEK→HKDF→AES-GCM) | "Encryption at Rest — the Key Chain" (diagram) | ☑ |
| Q8 | Offline recovery key — blast radius | "The Offline Recovery Key — Your One Real Footgun" | ☑ |
| Q9 | Production TPM keystore vs dev SoftwareSealer | "Strong Path or Weak Path?" | ☑ |

## C. The Policy Agent choke-point (Q10–Q13)

| Q | Theme | Deck home | ☑ |
|---|---|---|---|
| Q10 | What the PA is + why it's the single authz point | "The Policy Agent — the Single Authorization Choke-Point" | ☑ |
| Q11 | One decision end-to-end (CAR→JWT→audit) | "The Policy Agent …" + "Data Flow 3" | ☑ |
| Q12 | Human approval on deny/escalate (honest: ESCALATE inert) | "Human Approval, and Can the Gate Be Bypassed?" | ☑ |
| Q13 | Can the PA be bypassed? | "Human Approval, and Can the Gate Be Bypassed?" | ☑ |

## D. Untrusted content + prompt injection (Q14–Q17)

| Q | Theme | Deck home | ☑ |
|---|---|---|---|
| Q14 | Defense-in-depth vs injection (ADR-013 + ADR-023) | "Untrusted Content and Prompt Injection" | ☑ |
| Q15 | Hostile-page walk, layer by layer | "Walking a Hostile Page Through the Layers" | ☑ |
| Q16 | The Cleaner (re-homed #613) | "Untrusted Content and Prompt Injection" | ☑ |
| Q17 | PGOV output validation | "Untrusted Content and Prompt Injection" | ☑ |

## E. Containment + isolation (Q18–Q20)

| Q | Theme | Deck home | ☑ |
|---|---|---|---|
| Q18 | VM/mTLS containment (host-mode default vs #615) | "Containment and Isolation" + "Host↔Guest" explainer | ☑ |
| Q19 | Process-identity boundaries (de-elevation; no privilege drop) | "Containment and Isolation" | ☑ |
| Q20 | Network listeners (zero external) | "Containment and Isolation" | ☑ |

## F. The audit trail (Q21–Q22)

| Q | Theme | Deck home | ☑ |
|---|---|---|---|
| Q21 | Tamper-evident audit log (hash-chain + TPM sign) | "The Audit Trail — Tamper-Evident" | ☑ |
| Q22 | Known audit gaps (#606 tail, #607 retention) | "The Audit Trail — Tamper-Evident" | ☑ |

## G. Egress controls + the air-gap (Q23–Q26)

| Q | Theme | Deck home | ☑ |
|---|---|---|---|
| Q23 | What the air-gap IS today (import-scan + armed guard) | "The Egress Controls and the Air-Gap Itself" | ☑ |
| Q24 | The egress kill-switch (ADR-020) | "The Egress Controls …" | ☑ |
| Q25 | Deny-by-default allowlist + exfil-screen (dormant) | "The Egress Controls …" | ☑ |
| Q26 | The dev-mode interlock | "The Egress Controls …" | ☑ |

## H. ★ Residual risk of removing the air-gap — THE HEART (Q27–Q35)

| Q | Theme | Deck home | ☑ |
|---|---|---|---|
| Q27 | What can still go wrong post-air-gap | "★ The Heart …" (section) | ☑ |
| Q28 | Threat-model shift, inbound vs outbound | "The Threat-Model Shift — Inbound vs Outbound" | ☑ |
| Q29 | Outbound exfiltration risk + bounding controls | "Residual Register — Outbound Exposure" | ☑ |
| Q30 | Inbound risk + what is NOT built | "Residual Register — Inbound, the Highest-Risk Fork" | ☑ |
| Q31 | Live-memory attacker (#611) | "Residual Register — Accepted and Tracked" | ☑ |
| Q32 | PII embedded in content (#608) | "Residual Register — Accepted and Tracked" | ☑ |
| Q33 | DATA_MAP §7 hardening candidates | "Residual Register — Accepted and Tracked" | ☑ |
| Q34 | Tier-0→3 completeness + verified | "Tier Completeness and the Load-Bearing Elements" | ☑ |
| Q35 | Load-bearing elements | "Tier Completeness and the Load-Bearing Elements" | ☑ |

## I. Operator footguns (Q36–Q37)

| Q | Theme | Deck home | ☑ |
|---|---|---|---|
| Q36 | Operator mistakes that silently break security | "Operator Footguns — Mistakes That Silently Break Security" | ☑ |
| Q37 | Dev-vs-production posture trap | "The Dev-vs-Production Posture Trap" | ☑ |

## J. End-to-end data-flow walkthroughs (Q38–Q40)

| Q | Theme | Deck home | ☑ |
|---|---|---|---|
| Q38 | Local document: load→encrypt→retrieve→answer | "Data Flow 1 — A Local Document, End to End" (diagram) | ☑ |
| Q39 | Future web-fetch: fetch→Cleaner→PA→egress screen→answer | "Data Flow 2 — A Future Web-Fetch, the Designed Path" (diagram) | ☑ |
| Q40 | Authorization decision → signed audit record | "Data Flow 3 — An Authorization Decision → Signed Audit" (diagram) | ☑ |

## K. Verification + assurance (Q41–Q43)

| Q | Theme | Deck home | ☑ |
|---|---|---|---|
| Q41 | How each control was VERIFIED, not just built | "Is It Real? — Verified, Not Just Built" + per-card GRADE badges throughout | ☑ |
| Q42 | What is NOT tested / NOT verified (named) | "Is It Real? — Verified, Not Just Built" (the named NOT-verified list) | ☑ |
| Q43 | What a hostile reviewer attacks first | "What a Hostile Reviewer Attacks First — and Would It Hold?" | ☑ |

## L. Audit reconciliation (Q44–Q47)

| Q | Theme | Deck home | ☑ |
|---|---|---|---|
| Q44 | Per-finding current status (every issue + attack paths) | "Per-Domain Before → After" matrix + "Headline Attack Paths — Then → Now" | ☑ |
| Q45 | Mitigation detail + evidence for closed items | 3× "The Findings That Earned a Card" (Closed / Dormant+Mitigated / …) | ☑ |
| Q46 | Gap + ticket + why-acceptable for open/residual | "… Still Open and Accepted-Residual" + the §H residual register | ☑ |
| Q47 | Summary scorecard | "Audit Reconciliation — the Scorecard" | ☑ |

---

## Must-cover cross-check (#612 description's 8)

1. All the layers — Parts 1–2 (B–G) ☑ · 2. How they interact — the 3 system diagrams + data-flows ☑ ·
3. Gaps + tickets — §H residual register + reconciliation cards ☑ · 4. Data flows — Part 4 (3 flows) ☑ ·
5. Security gates / fail-closed — woven through Part 2 + "The Decision" ☑ · 6. Load-bearing elements — Q35 slide ☑ ·
7. Operator footguns — Part 7 ☑ · 8. Explain-to-a-13-year-old — the two explainers (attestation; host↔guest), each \~2 slides + a diagram ☑.

## Reconciliation status summary (the 55 findings)

| Status | Count |
|---|---|
| FIXED | 24 |
| MITIGATED | 5 |
| BUILT-DORMANT | 3 |
| ACCEPTED-RESIDUAL | 15 |
| STILL-OPEN | 8 |

Both Critical expressions (the cleartext-signing-key finding + its forge-token attack path) → **CLOSED** (commit `23b2802`).
The 12 headline attack paths are reconciled then→now on their own slide. The honest center of gravity for the
online decision is the **BUILT-DORMANT egress stack** (armed guard + import-scan are active; the kill-switch,
allowlist, and exfil-screen are real but never exercised against external traffic, and the exfil-screen is not
yet registered on the live path).

**Open boxes:** none. Every Q1–Q47 is ☑. §M (open slots) stays open for questions raised during the LA's
deep-dive — each becomes a deck requirement and is tasked→resolved before the #598 sign-off (the cmt-921 flow).
