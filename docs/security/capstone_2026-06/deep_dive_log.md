# #612 Capstone Security Deep-Dive — Session Log

**Date:** 2026-06-10 · **For:** the Lead Architect's #598 air-gap GO/NO-GO sign-off (§5.12)
· **Companion to:** `capstone_presentation.html` (deck, `b08a45f`), `EXECUTIVE_SUMMARY.md`,
`../CAPSTONE_QUESTIONS.md`.

**What this is.** The close-record of the LA's pre-sign-off walkthrough of the capstone deck.
Format per #612 cmt 921: the deck was walked top-to-bottom, the LA asked depth questions, every
answer was grounded against the code on disk (not the narrative), surfaced work was **ticketed —
never fixed live**, and decisions were recorded on the owning ticket. No runtime code or air-gap
posture was changed this session.

---

## Sections walked

Frame → Data Map → Security Stack Pt 1–6 (trust root · Policy Agent · prompt injection ·
containment & isolation · audit trail · egress controls) → Explainers (measured-boot attestation ·
host↔guest vsock) → Data Flows (local turn · memory recall · dormant web-fetch) → ★ the Heart
(residual register + go/no-go).

---

## What surfaced this session — findings & dispositions

1. **Pipe peer-authentication gap (#640).** Neither end of the WinUI↔backend named pipe pins the
   other's identity/PID — the server doesn't check the connecting client; the client connects by
   name without pinning the server (squatting risk). Evidence: `services/ui_backend/src/server.py`
   (no peer check on accept), `services/ui_winui/Ipc/PipeClient.cs:36` (connects by name only).
   LOW on the air-gapped single-user posture; rises network-facing. **Raised to HIGH, LA-scoped onto
   the #598 gate.**

2. **AO privilege-separation menu (Q19 → Q48).** The PA/AO inherit High integrity from the launcher
   (the documented "no de-privilege" residual). Analyzed the full menu against the AO's real
   dependencies (OpenVINO GPU, TPM, vsock, pipe, FS): (A) integrity High→Medium, (B) Job Object,
   (C) AppContainer, (D) restricted tokens / service accounts. **Recommendation:** tier-1 =
   A + B(block child-process creation) + D(privilege-strip) now while air-gapped (low GPU/TPM-breakage
   risk); **#651** OS-egress firewall coupled to #598; AppContainer deferred as a research spike
   (GPU/TPM-inside-sandbox unproven on the young Arc/Lunar-Lake driver stack). **LA decision:** tier-1
   → a separate agent; #651 created; AppContainer deferred. The Q19 residual is **ACCEPTED** for the
   egress-only posture — this menu is how it gets retired, not a gate-blocker.

3. **#639 ESCALATE has no human-in-the-loop.** An ESCALATE verdict resolves to a silent DENY — it
   **fails safe**, but there is no consent path. LA-scoped onto the #598 gate (tracked; not
   gate-blocking by its own fail-safe grade).

## Reconciliations past the deck (`b08a45f`) / executive summary (2026-06-08)

The deep-dive's disk-grounding found the gate-blocking picture has **sharpened** since the deck
was built — the sharpest documented gap closed:

| Item | Deck / summary said | Disk says (2026-06-10) |
|---|---|---|
| Exfil-screen wiring (#634) | *"single sharpest gap — structurally disconnected; `register_screener` has no runtime caller"* | **DONE** — `exfil_screen.wire_into_egress_guard()` runs at launcher boot (`launcher/__main__.py:1410`); screener registers via the arm-hook seam |
| Token containment (#638) | *"30s vs 5s spec; revocation/single-use not wired"* (the one fail-**open**) | **DONE** — 5s lifetime, `revoke()` wired, +18 regression tests → Tier B.7 **satisfied** |
| PCR-bound sealing (#627) | *"feasible, unproven"* | **DEMONSTRATED** on-chip 2026-06-09 (`docs/security/pcr_seal_poc_2026-06-09.md`); de-risks post-#598 attestation |

**Net effect:** the Tier-A gate-blocking work collapses from a list to essentially **one proof** —
the controlled sandboxed egress exercise (A.3 below).

---

## Tickets created / updated this session

- **#651** *created* — AO egress firewall allow-listing (Windows Filtering Platform), project 3,
  Security, HIGH, #598-coupled. The OS-enforced default-deny-outbound floor under #598 Decision 6,
  with a negative-test acceptance criterion + the ADR-020 kill-switch interlock.
- **#598** cmt 1012 — recorded the AO privilege-separation dispositions (tier-1 → separate agent;
  #651 coupled; AppContainer deferred); #639/#640 gate additions (per prior cmt 967).
- **#107** *re-scoped* — from the superseded FUT-05 PCR-seal ceremony to its real remainder: sign the
  spec-decode draft + fallback manifests (the dedicated draft-signing home). Not gate-blocking (a
  draft can't corrupt output — the target model verifies every token).
- **#637** item 3 marked **MOVED → #107** (so draft-signing has one canonical home).

---

## Live residual register (reconciled to disk, 2026-06-10)

| # | Residual | Grade | Disposition |
|---|---|---|---|
| **A.3** | Egress stack never exercised against real traffic | **BUILT-DORMANT** | **GATE-BLOCKING — the one remaining proof.** Allowlist one throwaway endpoint (Decision 8 sandbox); prove deny-by-default holds, kill-switch auto-trips off-allowlist, exfil-screen blocks a planted secret. Tracked as #598 gate criteria |
| B.4 | §5.12 sign-off (this deep-dive → LA act) | governance | **Yours.** In progress |
| B.5 | Audit + memory retention (#607) | governance | **Your decision.** Unbounded today; AIGP-portfolio item |
| B.6 | Guest-profile file still carries `dev_mode=true` | doc/file | Owed — runtime interlock neutralizes the path; reviewer flags a committed `dev_mode=true` |
| #639 | ESCALATE has no human-in-loop (→ silent DENY) | **fail-safe** | LA-scoped to gate; not gate-blocking |
| #640 | Pipe peer-auth (squatting/PID) | HIGH net-facing / **LOW now** | LA-scoped to gate; egress-only removal doesn't change it |
| #651 | OS-level egress firewall floor | DESIGNED | Coupled to gate; hard-criterion-vs-prerequisite disposition open for LA |
| C.8 | In-RAM secrets (#611) | accepted | Day-one-online (Intel Key Locker) — not pre-gate |
| C.9 | Dependency lockfile + hash-pin | accepted | Day-one-online |
| C.10 | Draft-model manifest signing (#107) | accepted | Not gate-blocking |
| — | Action-lock UAT re-run (#584/#591) in production posture | portfolio-clean | Not gate-blocking; recommended pre-sign-off (see Open items) |

## Finish-list mapped to tier (current)

- **Tier A — gate-blocking:** collapses to **A.3**, the controlled sandboxed egress exercise. (A.1
  wiring landed via #634; A.2 PII/secret screening is wired-but-dormant and folds into the A.3
  exercise.)
- **Tier B — governance / pre-sign-off:** §5.12 sign-off (B.4); #607 retention decision (B.5);
  guest-profile `dev_mode=true` file hardening (B.6). [#638 token containment — **satisfied**.]
- **Tier C — day-one-online (not gate-blocking):** #611 in-RAM hardening; dependency lockfile;
  #107 draft-manifest signing.

---

## Owed doc-sync (non-optional cleanup → ticketed)

The deep-dive surfaced stale documentation the disk now contradicts. Captured here and ticketed for
a builder (this session did not edit the roadmap/#598 body — out of the presenter scope):

- **Deck (`b08a45f`) stale cards:** token-containment STILL-OPEN → DONE; exfil-screen disconnected →
  wired; attestation feasible → DEMONSTRATED.
- **#598 criterion line-drift:** *"egress kill-switch armed … verified armed at launcher:944"* →
  the arm call is now `launcher/__main__.py:1429`.
- **`SECURITY_ROADMAP_air_gap_removal.md` §5 gate tracker + #598 body:** reflect #639 / #640 / #651
  on the gate.

---

## Open items surfaced for the LA (not actioned this session)

- **Action-lock UAT re-run (#584/#591) in production posture** (`dev_mode=False`). The Sprint-12
  live-screen verifications (lock fires on `/external` untrusted content; SAFE tool not locked) pass
  in automated tests but were not re-run in production posture. **Portfolio-clean, not gate-blocking.**
  Recommend ticketing pre-sign-off. (The offer parked during the walkthrough.)
- **#106 / FUT-04 reconciliation** — signed-manifest boot is live-verified; runtime re-verification +
  copy-on-write scope is real remainder, partly tracked by #571.

---

## The decision frame

- **Recommendation: NO-GO — not yet.** Direction unchanged from the executive summary; the finish-list
  is materially shorter (gate-blocking work ≈ one proof + the governance acts).
- **The go/no-go reduces to:** *do we trust Flow 3 hops 4–7 (PA-mediation → exfil-screen → provenance
  tag → action-lock) the first time they run for real — and have we run the one controlled exercise
  (A.3) that lights them up safely?*
- **The §5.12 sign-off is the LA's act.** Everything else is either done-by-construction (the strong
  base: closed Criticals, at-rest encryption, four-key TPM trust root, PA fail-closed, mTLS-in-
  production, tamper-evident audit, injection action-lock ON) or correctly deferred to day-one-online.

*Refs: #598 (gate), #612 (capstone), #651 (created), #640/#639/#107/#637 (this session);
`CAPSTONE_QUESTIONS.md` §M Q48–Q49; `EXECUTIVE_SUMMARY.md`; `pcr_seal_poc_2026-06-09.md`.*
