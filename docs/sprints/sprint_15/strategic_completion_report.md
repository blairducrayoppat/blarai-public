---
sprint_id: 15
sprint_name: "Tier-2 Production Posture — Per-Boot mTLS + Dev-Mode-Off Flip (fidelity-2)"
predecessor_sprint_id: 14
vikunja_tracking_task_id: 616
start_date: "2026-06-06"
sprint_completed: "2026-06-07"
sdv_path: "docs/sprints/sprint_15/strategic_design_vision.md"
sdv_version_at_completion: 4
orchestrator_authored_on: "2026-06-07"
main_tip_at_completion: "0cbe5e2"   # SCR + ledger + Vikunja close land on top
test_baseline_at_kickoff: "2055 passed (Sprint-14 completion, Layer-A: -m 'not hardware and not winui and not slow')"
test_baseline_at_completion: "2172 passed, 2 skipped, 15 deselected (same selection; re-run live by the closing session 2026-06-07)"
total_ea_milestones: 4   # EA-1..EA-4; EA-4 sub-phased a–f under the live-verify
scr_version: 1
---

# Strategic Completion Report — Sprint 15: Tier-2 Production Posture (Per-Boot mTLS + Dev-Mode-Off Flip)

## 1. Executive summary

Sprint 15 flipped BlarAI's **running default from dev-mode to production posture** — the gate-critical
step that makes "BlarAI works" mean "it works in the configuration that ships." Two dormant mechanisms
came alive at one moment: the **per-boot mutual-TLS (mTLS) certificate** machinery for the vsock channel,
and the **audit-stream TPM (Trusted Platform Module) signing + JWT (JSON Web Token) signing keys** that
had sat provisioned-but-dormant on the security chip since Sprint 14. The dev-mode-as-default trap the
LA named — `dev_mode_guard.py` silently resolving `HOST → dev` — is closed: production is now the host
default, behind a regression lock, with the explicit `dev_mode=true` opt-in preserved as the permanent,
loud, air-gapped escape hatch.

Executed as a per-tier DEC-15 fleet wave of worktree-isolated builder subagents (model sonnet) under the
Orchestrator's merge gate; builders never merged to `main` and never edited `BUILD_JOURNAL.md`. The plan
ran EA-1 (certs) → { EA-2 mechanism ∥ EA-3 cascade } → **EA-4 (ceremony + activation + live-verify)**, and
EA-4 sub-phased into **a–f** as the production live-verify drove out one production-only gap at a time.

**The defining work was the live-verify itself.** The unit suite was green throughout — yet the first
real `dev_mode=false` boots on the LA's hardware surfaced **ten production-only defects the green suite
could not see**, because each lived in a seam the units mock: 7 boot-cascade gaps (cryptography-not-in-
bare-python, wrong cwd, AF_HYPERV proto WinError 10041, host-mode loopback+mTLS transport, orchestrator
cert mint, router cert mint, PA handshake handler), 2 encrypted-store decrypt-brick defects (one
un-decryptable dev-era row bricking the whole store under the new production DEK), and 1 prompt-routing
misroute (gateway wired to the Policy Agent, not the Orchestrator). All fixed, merged, and
orchestrator-merge-gated (diff reviewed + tests re-run, never trusted from a builder summary).

**Boot-1 production live-verify PASSED on the LA's real hardware (2026-06-06):** prompts respond, a
paperclip→photo→"describe this" round-trip describes a never-seen image correctly, and Qwen3-VL evicts
from RAM after the prompt (+3857 MB reclaimed). The boot self-verified through the **new default-ON
model-loaded prompt-flow preflight** (launcher Step 6b) before the UI appeared — the 22:36 boot is the
first to run it by default and it passed (`Minimal prompt-flow preflight passed ✓`). This is the
"production is the only 'works'" bar — met for the activation boot.

**Scope honesty (the three LA gate-honesty conditions, held):** (1) the guest↔host AF_HYPERV boundary
handshake is **deferred + tracked #615** — fidelity-2 claims only the host-local machinery; (2) the
live-verify wording is scoped to exactly what host-local evidence proves, no broader "production-verified"
phrasing; (3) the staged manifest is **minimal-for-boot**, full FUT-04 weight integrity stays tracked
**#106**. The air-gap **stays up**; **#598 remains the GO/NO-GO gate** — Sprint 15 is one step toward it,
not the end.

Full Layer-A suite on integrated `main`: **2172 passed, 2 skipped, 15 deselected** (re-run live by the
closing session), arc 2055 → 2172, zero regressions.

**The lesson that earned doctrine:** *a green suite that mocks the boundary is not coverage of the
boundary — mocks pass, seams break.* Production-only seams kept slipping past both the green unit suite
and the existing `tests/harness/` scenario harness (which mocks the gateway), so the LA mandated
**`TEST_GOVERNANCE.md` §2.7**: every major subsystem gets an automated test of its real integrated path;
tests are part of "done." That mandate seeded the Sprint-16 coverage initiative (#619/#621/#622).

## 2. Context at completion

### 2.1 Repo state
- **BlarAI main HEAD**: `0cbe5e2` (forward-execution-plan doc). The SCR, the ledger entry, and the
  Vikunja close land on top.
- **Test baseline**: kickoff `2055 passed` (Sprint-14 completion); completion **`2172 passed, 2 skipped,
  15 deselected`** (`pytest shared/ services/ launcher/ -m "not hardware and not winui and not slow"`,
  `.venv` py3.11 where `cryptography` is present), **re-run live by the closing session 2026-06-07**
  (90.46s, exit 0) — not inherited from a builder summary. Arc: 2055 (S14) → EA-1..EA-3 → 2126 (EA-4f) →
  decrypt #618 + routing #620 + closing re-run → 2172. The skip count fell 20 → 2 (the additional
  Sprint-8-era skips were environment-driven, per the CLAUDE.md baseline-drift note; not source drift).
- **Open Vikunja `Gate:Pending-Human`**: 0.
- **Branches**: all EA feature branches merged `--no-ff`; kept (no destructive git). \~26 stale merged
  worktrees under `.claude/worktrees/`, `.worktrees/`, `C:/Users/mrbla/blarai-*` are inventoried for the
  LA to action (§7) — not deleted unilaterally.

### 2.2 Key commits (merge SHAs on `main`)
| Commit | Increment | Notes |
|---|---|---|
| `9857ac5`→`336fcc2` | **EA-1** per-boot mTLS cert gen + ADR-026 | CA + ephemeral per-boot issuance/rotation; extended fail-closed lock `test_ipc_transport.py`; 47 new tests. Mint moved after admin-confirmed (merge-gate hardening). |
| `bab1219` | **EA-2** dev-mode-off flip MECHANISM + locks | resolver-inversion capability, blast-radius overrides, interlock + loud banner, `ca.pem` untrack; shipped default still dev (activation deferred to EA-4b). |
| `b499bc6` | **EA-3** cascade + stub harness (7/7) + substrate ratify | minimal KGM staged, JWT cert/key wiring, off-chip stub-signer cascade green; substrate `:1012-1014` comment tightened. |
| `217ba32` | **EA-4a** ceremony helpers | 36 new tests; `manifest.json.example` committed (`git add -f`), real `manifest.json` untracked. |
| `e1858a5` | **EA-4b** ACTIVATION flip | HOST default → production; `resolve_dev_override`; launcher wiring; 6 regression locks incl. `resolve_dev_mode(HOST)==production`. |
| `c26cf11` | **EA-4c** vsock HV_PROTOCOL_RAW proto fix | + Group-M regression lock; guest-boundary round-trip deferred #615. |
| `04c45fd` | **EA-4d** fidelity-2 host transport wire | host loopback+mTLS transport unblocked. |
| `a410be9` | **EA-4e** orch + router cert mint | `cert_provisioning.py` orch + router cert pairs; 7 new tests. |
| `5ac5f9e` | **EA-4f** PA HANDSHAKE_REQUEST handler | PA answers the gateway handshake (later found to have *masked* #620 — §6). |
| `4af2033` | **#618** session-store decrypt-quarantine | 3 bulk readers; ADR-025 §2.7 + Sprint-14 SDV §3 amendments; merge-gate re-verified 105 tests. |
| `6fe1fcc` | **#618 sibling** substrate decrypt-quarantine | found by class-audit; 2 bulk decrypt sites; merge-gate re-verified 63 tests. |
| `ecbd991` | **#620** gateway→AO prompt routing | `resolve_gateway_port` single-source-of-truth; real round-trip integration test; **model-loaded prompt-flow preflight default-ON in prod**. |
| `244c55e` | ACTIVE_SPRINT + roadmap: boot-1 live-verify PASSED; Cleaner removed from roadmap (#613) | — |
| `1730a39` | journal fold (13 fragments → lessons 57–66) | fragment lifecycle complete. |

### 2.3 The flip is a precondition cascade, not a toggle (load-bearing)
With `dev_mode=false`, the Policy Agent **refuses to start** unless a weight manifest, the JWT TPM key +
CA cert path, and a Known-Good Manifest are all present (`entrypoint.py:720-789`). So "flip dev-mode off"
meant: build the per-boot certs the channel needs (EA-1), stage a minimal manifest so the cascade is
satisfiable (EA-3), run the on-chip ceremony that mints the JWT key (EA-4), and only then throw the
running-default flip (EA-4b) — so the **first** production-default boot succeeds with no brick window.
This is exactly the sequencing SDV v4 locked.

## 3. SDV success-criteria disposition

| # | Criterion (SDV §4) | Verdict | Evidence |
|---|---|---|---|
| 1 | Per-boot mTLS cert generation exists + exercised; fail-closed lock extended | **MET** | EA-1 `336fcc2`: CA + per-boot issuance/rotation in `shared/security/`; `test_ipc_transport.py` extended to per-boot issuance/rotation; 47 new tests green |
| 2 | Dev-mode-off flip MECHANISM built + locked; shipped default stays dev (4 locks) | **MET** | EA-2 `bab1219`: resolver-inversion capability; 4 mechanism locks green — shipped HOST default still dev through EA-1/2/3, production signal resolves `dev_mode=false`, explicit dev opt-in resolves dev (loud banner), interlock refuses `dev_mode=true + network_facing=true` |
| 3 | Precondition cascade satisfied for a clean production boot (off-chip stub harness) | **MET** | EA-3 `b499bc6`: minimal KGM staged + JWT cert/key paths resolve; off-chip stub-signer cascade harness 7/7 PASS at `dev_mode=false` |
| 4 | Fidelity-2 production live-verify (LA, on-chip): mTLS handshake succeeds w/ valid certs, fails closed w/o; `dev_mode=false` boot brings audit-TPM + JWT signing live | **MET** | Boot-1 live-verify PASSED (LA-confirmed 2026-06-06): production cascade passed, per-boot mTLS handshake on the freshly-minted CA, no dev fallback; the fail-closed side is locked by the extended `test_ipc_transport.py`. Audit-TPM + JWT signing live at `dev_mode=false`. Host-local fidelity-2 only (Condition 2) |
| 5 | Ceremony honesty (key inventory surfaced; JWT net-new; DEK+audit already provisioned) | **MET** | EA-4 ceremony: JWT signing key net-new via `provision_signing_key`; DEK seal + audit keys confirmed present from the Sprint-14 ceremony (idempotent); runbook `EA4_ceremony_runbook.md` surfaces the inventory before provisioning |
| 6 | New ADR-026 authored + accepted (freshness-not-attestation limitation recorded) | **MET** | `docs/adrs/ADR-026-Per-Boot-mTLS-Ephemeral-Certificates.md` on `main`; records the known limitation that per-boot certs prove *freshness*, not *measured-image-CN issuer-attestation* (deferred with measured-boot) |
| 7 | Gate-honesty obligations tracked, not silently closed (#615, #106) | **MET** | #615 (guest-boundary AF_HYPERV handshake) + #106 (full FUT-04 weight integrity) both exist + are bound as remaining #598 criteria in SDV §5.2 and this SCR §5 |
| 8 | Activation + daily-driver continuity (flip's final gated step; regression lock) | **MET (activation + lock); cold-reboot continuity = routine confirmation outstanding** | EA-4b `e1858a5`: activation flip live (`resolve_dev_mode(HOST)==production` regression lock green in the 2172-suite). A clean **zero-manual** production boot is demonstrated on disk (22:36 boot: default-ON preflight passed, decrypt-quarantine auto-handled legacy rows, prompts + vision + eviction, clean shutdown rc=0). The deliberate **post-OS-reboot repeat** is the one routine confirmation not yet captured (§4) |

**7 of 8 criteria fully MET.** Criterion #8's activation and its regression lock are MET and a zero-manual
clean boot is demonstrated; the only uncaptured element is the **cold-reboot repeat** of that boot —
recommended as a routine confirmation, high-confidence-to-pass (the TPM-sealed keys, the DEK keystore
file, and the deterministic decrypt-quarantine all persist across an OS restart by construction). It is
**honestly named, not claimed**. The independent SWAGR follows this record.

## 4. Live verification (production posture) — PERFORMED for activation; cold-reboot repeat outstanding

The LA ran the EA-4 ceremony + production live-verify on the real hardware this sprint:

- **Ceremony:** the net-new **JWT signing key** was minted on the TPM via `provision_signing_key`; the
  DEK seal key + audit signing key from the Sprint-14 ceremony were confirmed present (idempotent). The
  production manifest was staged. The `ceremony_preflight` reached **READY for production boot**.
- **Activation + Boot-1 live-verify — PASS (LA-confirmed 2026-06-06):** the running-default flip was
  thrown (production is now the HOST default); the first `dev_mode=false` boot brought the per-boot mTLS
  handshake live over the freshly-minted CA with **no dev fallback**, and audit-TPM + JWT signing went
  live. The **22:36 boot log** is the on-disk evidence of the clean steady-state run:
  - `Executing minimal prompt-flow preflight…` → `Minimal prompt-flow preflight passed ✓` — the new
    **default-ON** model-loaded `send_prompt→AO→stream` gate (fail-closed) passed *before* the UI.
  - `SESSION_ROW_DECRYPT_QUARANTINE … 2 session row(s) quarantined` — the #618 fix auto-quarantined the
    dev-era rows and the app kept serving (no brick).
  - `send_prompt → stream_tokens → generation complete` — prompts work end-to-end (the #620 routing fix).
  - `Vision grounding … Qwen3-VL loaded → describe → pipeline dereferenced + gc; +3857 MB` — vision on a
    never-seen photo, then VLM eviction.
  - `WinUI app exited (code 0) … Cleanup: complete` — clean shutdown.
- **Outstanding (routine):** a **cold-reboot continuity boot** — one `python -m launcher` after the OS
  restart, zero manual steps — to capture the daily-driver-continuity-across-reboot evidence for
  criterion #8. The LA rebooted the machine at close; the single launcher boot that captures this is the
  one remaining LA action. It is expected to pass (persistent TPM keys + keystore + deterministic
  quarantine); the evidence will be appended on capture.
- **Deferred (honestly named, not this sprint):** the guest↔host AF_HYPERV boundary handshake (#615) —
  fidelity-2 proves the host-local cert machinery only (Condition 2).

## 5. Carry-overs

| Carry-over | Ticket / tier | Note |
|---|---|---|
| **Cold-reboot continuity boot** (criterion #8 repeat) | LA on-chip, this close | One `python -m launcher` post-reboot; evidence appended on capture. Not a defect — a routine confirmation. |
| **Production-parity test lane** (boot cascade + key-transition in CI, software-sealer stand-ins) | **#619** — Sprint-16 | The systemic fix so prod-only bugs hit CI, not the LA's terminal. Seeded by the #620 round-trip test. |
| **WinUI GUI automation harness** (critical-path list + model-loaded tier) | **#621** — Sprint-16, urgent | **Extend the existing `tests/harness/` Layer-C pywinauto harness (#563)** — NOT build from scratch (see §6 honest-failure). Title still reads "FlaUI"; corrected in-ticket. |
| **Comprehensive automated test coverage** (umbrella; coverage audit is step 1) | **#622** — INITIATIVE | Folds the §2.7 mandate into a standing requirement; burns down across Sprints 16+. |
| **Rename gateway `check_pa_status`/`_attempt_pa_handshake`** (they handshake the AO post-#620, not the PA) | **#623** — low priority | Pure naming/doc; \~35 files; deliberately kept out of the #620 diff. |
| **Guest-boundary AF_HYPERV handshake** (fidelity-3) | **#615** — VM-occupant sprint | Remaining #598 criterion; guest deploy channel unproven (`priority5_guest_deploy.json` FAIL, stale). |
| **Full FUT-04 weight integrity** (`require_signed_manifest=true` + verify all weights) | **#106** — Tier-3 | Remaining #598 criterion; Sprint 15 staged only a minimal boot manifest (Condition 3). |
| **The Cleaner (UC-003)** | **#613** | **Removed from this roadmap** to a separate/future project (LA 2026-06-06); `SECURITY_ROADMAP_air_gap_removal.md` §1/§3/§4 + Decision-1 inline refs still read "post-#598 fast-follow" — reconcile per #613. |

**Campaign → #598 (remaining gate-critical work after Sprint 15):** #615 (guest-boundary handshake),
#106 (full FUT-04 weight integrity), Tier-3 egress per-action mediation + exfil-screen + kill-switch
arming for web tools (the egress kill-switch itself is already armed: `launcher/__main__.py:944`,
verified), and #612 (capstone post-hardening security presentation, the closing bookend).

## 6. Process notes

- **The live-verify earned its existence — ten times.** The unit suite was green at every step, yet the
  first real `dev_mode=false` boots surfaced ten production-only defects, each in a seam the units mock.
  The class is the Sprint-13/14 "built but wired into nothing / mock-passes-prod-crashes" trap, recurring
  at the system-boundary scale. The seven boot-cascade gaps (EA-4c–f) were driven out one boot at a time;
  the two decrypt-bricks and the routing misroute (#618/#620) followed once the app reached its window.
- **A downstream fix masked an upstream defect (the costliest single lesson).** EA-4f taught the Policy
  Agent to answer the gateway's handshake — which made the boot *look* healthy and **hid** #620: the
  gateway was wired to the PA (5000), not the Orchestrator (5001), in production host-mode, so the boot
  passed its handshake but every real prompt was rejected `Unsupported message type: PROMPT_REQUEST`. The
  fix made the gateway prompt-port and the AO listener port a **single source of truth**
  (`resolve_gateway_port`), regression-locked, plus a real gateway↔AO round-trip integration test
  (reproduced red→green). Lesson 65 (test the seam, not just the symptom).
- **A test can lock a *defect*, not just a feature.** The decrypt-brick (#618) was guarded by a *green*
  Sprint-14 regression test (`test_wrong_key_on_existing_db_fails`) that asserted the brick behaviour —
  one un-decryptable row → whole `list_sessions` raises → app-wide "backend not running." Twice the
  closing-of-Sprint-14 reflex was to escalate this as a posture *decision*; the LA collapsed it each time
  ("is there really more than one correct answer?"). It was a defect with one nameable fix: bulk readers
  **quarantine** the bad row (omit + structured `*_ROW_DECRYPT_QUARANTINE` WARNING) and keep serving;
  single-record + write paths keep hard fail-closed. Posture recorded in **ADR-025 §2.7**. The mis-test
  was rewritten as part of the fix (the test was part of the defect). Lesson 66.
- **Class-audit caught the sibling.** Fixing the session store immediately prompted "where else does this
  pattern live?" — the substrate store had the same bulk-decrypt brick (`_load_embed_cache`,
  `_search_kind`); fixed in the same posture (`6fe1fcc`) before it could surface in production. Lesson 64.
- **An honest failure that did NOT reach the permanent record.** The outgoing session twice told the LA
  "the WinUI app has no automated UI tests" — **wrong**: a pywinauto harness already exists
  (`tests/harness/` Layer C, #563). Caught by verify-first before it reached the journal; #621 was
  corrected from "build FlaUI from scratch" to "extend the existing pywinauto harness." *Verify your own
  claims on disk — even the confident ones.* (This SCR §5 carries the corrected #621 framing.)
- **Merge-gate held throughout.** Every EA branch was diff-reviewed against its criterion and its tests
  **re-run by the Orchestrator**, never trusted from the builder summary; the closing session re-ran the
  full Layer-A suite live (2172 green) rather than inheriting a count.
- **Worktree-cwd-branch guard applied.** Per lesson 52, `git branch --show-current == main` + toplevel
  were verified before every main-tree commit (the hazard bit this project 3×; the guard caught it twice
  in Sprint 14).

## 7. State hygiene (inventory — for the LA to action, NOT to delete unilaterally)

- **\~26 stale merged worktrees** under `.claude/worktrees/`, `.worktrees/`, and `C:/Users/mrbla/blarai-*`
  (Sprint-14/15 feature branches, all merged). They clutter `git worktree list` and worsen the cwd-quirk
  hazard. **Recommend** the LA approve `git worktree remove` of the merged ones (verify each is merged
  first; do **not** delete the branches — destructive). Inventory, then ask.
- **`SECURITY_ROADMAP_air_gap_removal.md`** §1/§3/§4 + Decision-1 inline Cleaner refs still read
  "post-#598 fast-follow" — reconcile per #613 (Decision-4 already amended).
- **Pre-existing dirty `docs/guide-workstreams/README.md`** + untracked perf/benchmark JSONs under
  `docs/performance/` — pre-existing, leave as-is.

## 8. Disposition

**COMPLETE — and live-verified (activation).** All EA milestones (EA-1..EA-4, EA-4 sub-phased a–f) plus
the two live-verify-surfaced defect tickets (#618 decrypt-quarantine across both encrypted stores, #620
prompt routing) are built, tested (2172 green on integrated `main`, re-run live), and merged under the
merge gate; SDV criteria **7/8 fully MET, #8 MET for activation + lock with the cold-reboot continuity
repeat as the one routine confirmation outstanding**. The production-posture activation live-verify was
**performed and passed** on the LA's real hardware (prompts, vision, VLM eviction, default-ON preflight
gate). The three gate-honesty conditions held: fidelity-2 host-local only, guest-boundary deferred #615,
minimal manifest with full FUT-04 tracked #106. The air-gap **stays up**; **#598 remains the GO/NO-GO
gate** — Sprint 15 advances the campaign one step, it is not the end. The independent Sprint Auditor's
SWAGR follows this record.

## 9. Post-SWAGR reconciliation

The independent Auditor's SWAGR (manual spawn, fleet LA-paused; Opus, adversarial posture) returned
**STRONG_ALIGNMENT — 8/8 criteria MET, 0 CRITICAL, 0 MAJOR, 6 MINOR**
(`docs/sprints/sprint_15/Strategic_Work_Analysis_and_Gap_Report_Sprint_15_20260607_094439.md`, commit
`423167e`). It independently reproduced the 2172 test baseline exactly, read the 2026-06-06 22:36
production boot line-by-line, verified all 12 EA merge SHAs and the three gate-honesty conditions in the
*shipped* artifacts, and confirmed the two highest-value seam fixes (#618, #620) are real integration
tests, not unit locks.

**Criterion #8 — the Auditor graded it a clean MET, *stronger* than this SCR's cautious self-grade.** It
found **seven** consecutive zero-manual `dev_mode=false` production boots on 2026-06-06 (not one), so
daily-driver continuity is over-demonstrated; the only genuinely uncaptured permutation is a boot after a
full OS restart (cold-VM), which it rates LOW-risk (per-boot certs mint fresh every launch; the
TPM-sealed keys + DEK keystore persist by construction). The honest-naming in §3/§4 stands; with the
Auditor's independent verification the **reconciled sprint disposition is 8/8 MET**, and the cold-reboot
boot is recorded as a low-risk **routine confirmation** (carry-over §5), not a gate.

All six MINORs were dispositioned at this close (none compromises the production-security substance):

- **MINOR-1 — ADR-026 cert-count drift (the one genuinely-new finding):** §2/§3/§6 described five cert
  artifacts; the shipped `cert_provisioning.py` mints **nine** (orchestrator + semantic-router cert pairs
  added EA-4e `a410be9`, asserted by `test_ipc_transport.py::test_provision_writes_nine_pem_files`). The
  decision + limitations were always correct; only the artifact inventory was stale. **FIXED at this
  close** — ADR-026 §2/§3/§6 reconciled to the nine-PEM reality.
- **MINOR-2 — no Sprint-15 ledger close entry:** **FIXED at this close** —
  `docs/ledger/20260607_094439_sprint15_scr_production-posture-flip.md` (DEC-17 per-file).
- **MINOR-3 — Vikunja #618 / #620 still `done:false`:** **FIXED at this close** — both marked complete
  with merge SHA + test evidence.
- **MINOR-4 — CLAUDE.md "Active State" stale (Sprint 11):** **FIXED at this close** — refreshed to the
  Sprint-15 close state (Sprints 7–14 complete; baseline 2172 / 2026-06-07; current carry-overs).
- **MINOR-5 — TEST_GOVERNANCE §1 named-scope baseline rows stale:** **FIXED at this close** — annotated
  with the canonical live Layer-A baseline (2172, 2026-06-07; named-scope rows flagged for a re-measure
  pass).
- **MINOR-6 — SECURITY_ROADMAP Cleaner refs read "post-#598 fast-follow":** **TRACKED under #613**, which
  owns the roadmap-doc reconciliation as part of the Cleaner removal-to-separate-project work (the §7
  carry-over). Scope made explicit on the ticket at this close — a coherent multi-section reconciliation
  (§1/§3/§4 + §6 Decision-1) belongs with #613's full context, not a partial close-time edit.

**One forward risk the Auditor flagged (§10.3, MEDIUM):** the `TEST_GOVERNANCE §2.7` "test the seam"
mandate has near-zero CI enforcement yet (no BlarAI-root CI runner; only the static posture lock + the
one #620 round-trip test). It is honestly deferred to **#619/#621/#622** (Sprints 16+), but the
mock-passes-prod-crashes class can recur until **#619** lands — so both the Auditor's and this SCR's top
Sprint-16 recommendation is to stand up **#619** (the production-parity test lane) early.

Final disposition stands **COMPLETE — 8/8 MET (Auditor-confirmed), live-verified (activation)**. The
cold-reboot continuity boot is a low-risk routine confirmation, capturable anytime (evidence appended on
capture). The air-gap stays up; **#598 remains the GO/NO-GO gate**.

## 10. Continuity addendum — cold-reboot boot CAPTURED (2026-06-07)

The one routine item §3 (criterion #8) and §4/§9 named as outstanding — a launcher boot after a full OS
restart — was **captured and PASSED** on 2026-06-07. The LA rebooted the machine, then ran
`python -m launcher` (the first 2026-06-07 boot; the log held zero 2026-06-07 lines before it) and sent a
basic prompt that worked. `launcher.log` (2026-06-07 09:58:26–09:59:56) confirms, **zero manual steps**:

- `Egress guard ARMED (Fail-Closed allowlist)` + `dev_mode interlock: PASSED (dev_mode=False,
  network_facing=False)` — production posture, no DEV-MODE warning.
- `Provisioning per-boot mTLS certificates (ADR-026)… → Per-boot mTLS certs provisioned ✓` — certs minted
  fresh this boot (`ca.pem` / `pa_server.pem` / `gateway_client.pem`).
- `Real-runtime handshake passed ✓` → `Executing minimal prompt-flow preflight… → Minimal prompt-flow
  preflight passed ✓` — the default-ON gate self-verified the `send_prompt→AO→stream→generation complete`
  path before the UI appeared.
- `SESSION_ROW_DECRYPT_QUARANTINE summary: 2 session row(s) quarantined` — the #618 fix auto-handled the
  dev-era rows; the app kept serving (the LA's prompt completed).
- `WinUI app exited (code 0)` — clean shutdown.

This confirms criterion #8 across the persistent-state-survives-OS-restart axis (the TPM-sealed keys, the
DEK keystore, and the deterministic decrypt-quarantine all survived the reboot, and a plain launcher run
served correctly). **Honest scope:** the VM logged `BlarAI-Orchestrator already running` — it auto-started
with the host on the OS boot (the normal daily-driver state), so the narrow "launcher powers on a stopped
VM" sub-path remains unexercised, by design. Criterion #8 is now fully captured, not merely Auditor-graded.
The sprint disposition is unchanged: **COMPLETE — 8/8 MET, live-verified (activation + cold-reboot
continuity).**
