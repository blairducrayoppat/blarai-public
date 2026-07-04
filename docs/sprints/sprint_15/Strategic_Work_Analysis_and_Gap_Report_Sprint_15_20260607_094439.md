---
sprint_id: 15
sprint_name: "Tier-2 Production Posture — Per-Boot mTLS + Dev-Mode-Off Flip (fidelity-2)"
document_type: SWAGR
auditor: "Independent Sprint Auditor (Claude Opus 4.8, 1M context)"
audit_date: "2026-06-07"
vikunja_tracking_task_id: 616
sdv_path: "docs/sprints/sprint_15/strategic_design_vision.md"
sdv_version_reviewed: 4
scr_path: "docs/sprints/sprint_15/strategic_completion_report.md"
scr_version_reviewed: 1
auditor_session_fired_at: "2026-06-07T09:44:39-07:00"
main_tip_reviewed: "0cbe5e2"
swagr_version: 1
overall_alignment_verdict: "STRONG_ALIGNMENT"
functional_impact_verdict: "SIGNIFICANT"
architecture_health_verdict: "IMPROVED"
test_baseline_reproduced: "2172 passed, 2 skipped, 15 deselected, 0 failed (84.41s) — independently re-run, exit 0"
test_baseline_delta: "+117 tests (2055 → 2172); regression PASS, 0 failures, 0 regressions"
criteria_summary: "8/8 MET, 0 CRITICAL, 0 MAJOR, 6 MINOR"
gaps_count_critical: 0
gaps_count_major: 0
gaps_count_minor: 6
---

# Strategic Work Analysis and Gap Report — Sprint 15: Tier-2 Production Posture (Per-Boot mTLS + Dev-Mode-Off Flip)

**Adversarial, independent, read-only.** Every load-bearing claim below was verified against
git history, the actual source, the live production `launcher.log` on disk, the Vikunja gate
tickets, and an independently-reproduced test run — *not* against the SCR's prose. Findings
are cited with commit SHAs, `file:line`, test names, and `launcher.log` line numbers.

---

## 0. Auditor's stance

The default posture for this audit was "something was probably missed — prove otherwise."
I formed my own view of the sprint window (git log `e08a7db..0cbe5e2`, the launcher.log, the
shipped source, the test suite) BEFORE reading the SCR, in the prescribed order. The
notable result here is the opposite of the usual divergence finding: **I agree with all 8
of the SCR's criterion verdicts, and on criterion #8 my independent read is actually
*stronger* than the SCR's own cautious self-grade** (the SCR under-claims the daily-driver
continuity evidence it already holds — see §4). That agreement is earned, not rubber-stamped:
every criterion below carries an independent citation, and I independently reproduced the
2172-test baseline and re-read the 22:36 production boot line-by-line.

No commendations are included (per project doctrine). The findings are six MINOR
honesty-of-record / doc-currency items, none of which compromises the production-security
substance the sprint delivered.

---

## 1. Executive judgment

**Product lens (functional_impact_verdict: SIGNIFICANT).** Sprint 15 flipped BlarAI's running
default from the security-OFF dev posture to the production posture (`dev_mode=false`) and
brought three previously-dormant security mechanisms alive simultaneously: per-boot ephemeral
mTLS over the vsock channel, audit-stream TPM signing, and JWT signing. This is the single
most consequential operational change since at-rest encryption landed: every "BlarAI works"
report now describes the configuration that actually ships. The proof is on disk — the
2026-06-06 22:36 boot ran end-to-end in production posture (`dev_mode interlock: PASSED
(dev_mode=False ...)`, `launcher.log:10084`), served prompts, described a never-seen photo via
Qwen3-VL, evicted the VLM, and shut down clean (rc=0). This is not a TUI-feature sprint; it is
the gate-critical posture step that makes the #598 air-gap GO/NO-GO evaluable at all.

**Technical lens (overall_alignment_verdict: STRONG_ALIGNMENT).** The work was executed
correctly and — uniquely valuable for this campaign — the sprint's defining outcome was the
live-verify *catching what the green suite could not*: the unit suite was green throughout
(2126 at EA-4f) yet the first real `dev_mode=false` boots surfaced ten production-only defects,
each living in a seam the units mock. All ten were fixed, merged, and merge-gate-re-verified;
I independently confirmed the two highest-value ones (the #618 decrypt-brick and the #620
gateway misroute) are backed by real seam-exercising tests, not unit locks. The three LA
gate-honesty conditions are honored in the *shipped artifacts* (`shared/ipc/vsock.py`,
`default.toml`, ADR-026 §5), not merely asserted in prose. The single most important thing the
LA should know: **the sprint is genuinely complete and the activation live-verify genuinely
passed in production posture; the only uncaptured element is a post-OS-reboot repeat boot,
which the SCR names honestly and which my evidence shows is low-risk** (seven consecutive
zero-manual production-default boots already ran on 2026-06-06).

---

## 2. Review method

### 2.1 Artifacts consulted

| Artifact | Version / commit | Date / range |
|---|---|---|
| SDV: `docs/sprints/sprint_15/strategic_design_vision.md` | v4 (signed 2026-06-06T12:12:23-07:00) | 2026-06-06 |
| Predecessor SWAGR: `docs/sprints/sprint_14/...swagr.md` | — | 2026-06-05 (cross-sprint baseline) |
| SCR: `docs/sprints/sprint_15/strategic_completion_report.md` | v1 | 2026-06-07 |
| Git log (sprint merge ancestry) | `e08a7db..0cbe5e2` | 60 commits |
| Live production evidence: `%LOCALAPPDATA%/BlarAI/launcher.log` | 10217 lines (mtime 2026-06-06 22:41) | READ-ONLY |
| Vikunja tracking tickets | #615, #618, #620 (gate-trace only) | — |
| ADRs reviewed | ADR-026 (full), ADR-025 §2.7 amendment | — |
| TEST_GOVERNANCE.md | §2.5, §2.6, §2.7 | — |
| Independently re-run test suite | `2172 passed, 2 skipped, 15 deselected` | 2026-06-07, 84.41s, exit 0 |

### 2.2 Deliberate exclusions

- **No chat transcript / Orchestrator narration read** — independence from the team's narrative
  is the audit's value (per the template's "does NOT read" list).
- **Did not run the launcher / boot the system** — the launcher.log was read READ-ONLY; the
  live-verify is the LA's on-chip step, not the auditor's.
- **Did not run pytest against the real `%LOCALAPPDATA%`** — confirmed the root `conftest.py`
  isolation is active (§8.1) before running the suite.
- **Did not post any Vikunja comment or create any task** — read tickets #615/#618/#620 as
  gate-trace evidence only.

### 2.3 Test-process isolation confirmed (lesson-55 guard)

Before running any test, I read `conftest.py` (repo root). It mutates `os.environ` at
**module load** (process startup, before collection imports any BlarAI module): redirects
`LOCALAPPDATA`, `HOME`, `XDG_DATA_HOME` to a throwaway `tempfile.mkdtemp(prefix=
"blarai-pytest-userdata-")` and `os.environ.pop("BLARAI_DEK_KEYSTORE", None)`
(`conftest.py:74-79`). This is the durable fix for the Sprint-14 incident where a suite run
corrupted the real `sessions.db`. The isolation is regression-locked by
`tests/security/test_root_test_isolation.py` (per TEST_GOVERNANCE §2.6). My suite run therefore
never touched the operator's real user-data dir.

---

## 3. Functional / product-value assessment

### 3.1 Use Case advancement

| Use Case | Pre-sprint status | Post-sprint status | Change | Evidence |
|---|---|---|---|---|
| UC-001 Policy Agent | OPERATIONAL (dev posture) | OPERATIONAL (production posture) | `+` | PA measured-boot gate passed at `dev_mode=false`, `launcher.log:10109`; JWT signing key minted (criterion #5) |
| UC-002 | not built | not built | `=` | — |
| UC-003 The Cleaner | deferred | removed from this roadmap → #613 | `=` | SCR §5; `244c55e` |
| UC-004 Assistant Orchestrator | OPERATIONAL (dev posture) | OPERATIONAL (production posture) | `+` | AO entrypoint ready at `dev_mode=false`, `launcher.log:10122`; prompt round-trip live (`launcher.log:10167-10170`) |
| UC-005 | not built | not built | `=` | — |
| UC-009 | not built | not built | `=` | — |

The two operational use cases did not gain *features*; they gained the **production security
posture** they will permanently run under. That is a status change worth recording as `+`:
the JWT mint (UC-001's authorization artifact) and audit-TPM signing went live in this sprint.

### 3.2 Operational capability delta

What the running system does differently today: it boots **production-by-default**. Before
the flip (2026-06-05 boots), every launch logged `DEV MODE ACTIVE — insecure configuration
(no mTLS / throwaway keys / no measured boot)` (`launcher.log:9240`). After the flip
(every 2026-06-06 boot from 17:58 on), it logs `dev_mode interlock: PASSED (dev_mode=False,
network_facing=False)` with **no DEV MODE warning** — the per-boot mTLS handshake engages,
the encrypted stores open under the production TPM-sealed DEK, and the audit/JWT signing keys
are live. The explicit `dev_mode=true` opt-in remains as the loud, air-gapped escape hatch
(`resolve_dev_override` / `BLARAI_DEV_MODE=1`, EA-4b `e1858a5`).

### 3.3 User / operator experience impact

- **Boot experience:** a new **default-ON model-loaded prompt-flow preflight** runs before the
  UI appears (`launcher.log:10132-10140` — `Executing minimal prompt-flow preflight… →
  Minimal prompt-flow preflight passed ✓`). This self-verifies the real `send_prompt → AO →
  stream → generation complete` path at boot, fail-closed, so a broken prompt route is caught
  before the user sees the window (the exact gap #620 exploited).
- **Reliability / fail-closed correctness:** the #618 decrypt-quarantine fix means a single
  un-decryptable legacy row no longer bricks the whole session list. On the 22:36 boot, two
  dev-era rows (`7308bf05…`, `a5b9160d…`) were quarantined (`launcher.log:10151-10153`,
  `SESSION_ROW_DECRYPT_QUARANTINE … 2 session row(s) quarantined`) and **the app kept serving**
  (subsequent real prompts completed). This is a strict reliability improvement with no
  confidentiality cost (plaintext is never returned).
- **Observability:** the quarantine events are structured WARNING logs with the session_id and
  a `check key rotation / dev->prod key transition` hint — more observable than the prior
  generic store-wide failure.

### 3.4 Phase 5 roadmap position

This is **Tier-2 gate-critical** work on the air-gap-removal campaign. After Sprint 15, the
production-posture verification that #598's controlling criterion requires is *partially* in
hand (host-local fidelity-2), with the remaining gate-critical work explicitly tracked: #615
(guest-boundary fidelity-3 handshake), #106 (full FUT-04 weight integrity), and Tier-3 egress
mediation for web tools. The air-gap **stays up**; #598 remains the GO/NO-GO gate. Sprint 15
advances the campaign one step — correctly framed by the SCR as "not the end."

### 3.5 Open issues and ISS tracker status

| Issue | Pre-sprint status | Post-sprint status | Notes |
|---|---|---|---|
| ISS-1 (AO spec-decode) | RESOLVED (2026-05-21) | RESOLVED | Not in sprint scope; unaffected |
| ISS-2 (think tags in TUI) | open | open | Not in sprint scope |
| ISS-3 (PA classification misses) | open | open | Not in sprint scope |
| ISS-8 (#618 decrypt-brick) | **surfaced this sprint** | FIXED + merged (`4af2033`/`6fe1fcc`) | Vikunja #618 still `done:false` — see MINOR-3 |
| ISS-10 (#620 gateway misroute) | **surfaced this sprint** | FIXED + merged (`ecbd991`) | Vikunja #620 still `done:false` — see MINOR-3 |

Two new ISS-class defects surfaced *and were fixed* within the sprint window — the healthy
shape (found by live-verify, fixed, regression-locked, merge-gated).

---

## 4. Success-criteria gap analysis

| # | Criterion (abbrev from SDV §4) | SCR verdict | Auditor's independent verdict | Evidence reviewed | Gap severity |
|---|---|---|---|---|---|
| 1 | Per-boot mTLS cert gen exists + exercised; fail-closed lock extended | MET | **MET** | `shared/security/cert_provisioning.py` (420 LOC, EA-1 `336fcc2` + EA-4e `a410be9`); original lock `test_ipc_transport.py::test_transport_connect_no_mtls_production_fails` (:367) intact; new "Group J: Per-boot cert provisioning + rotation (ADR-026)" (:459+) asserts PEM files, CNs, EKUs, 24h lifetime, fail-closed | NONE |
| 2 | Dev-mode-off MECHANISM built + locked; shipped default stays dev (4 locks) | MET | **MET** | EA-2 `bab1219`; `test_dev_mode_interlock.py` — lock-a was a *premature-flip sentinel* through EA-1/2/3 (default stayed dev); merge msg "shipped HOST default UNCHANGED" diff-verified docstring/comment-only in `dev_mode_guard.py` | NONE |
| 3 | Precondition cascade satisfied (off-chip stub harness) | MET | **MET** | EA-3 `b499bc6`; `test_cascade_stub_harness.py` (456 LOC) proves `dev_mode=false` cascade 7/7 off-chip; isolation-guard asserts no real keystore touched | NONE |
| 4 | Fidelity-2 production live-verify: mTLS handshake succeeds w/ valid certs, fails closed w/o; audit-TPM + JWT live at `dev_mode=false` | MET | **MET** | `launcher.log:10126` `Transport gateway ready (production host-mode: loopback + mTLS, fidelity-2)`; PA handshake succeeded attempt 1 (:10130); fail-closed side locked by `test_ipc_transport.py` Group K (absent/wrong-CA certs fail closed); scoped host-local only (Condition 2) | NONE |
| 5 | Ceremony honesty (JWT net-new; DEK+audit already provisioned) | MET | **MET** | SCR §4 + `shared/security/ceremony_preflight.py` (349 LOC); JWT key via `provision_signing_key`; DEK+audit confirmed present from Sprint-14 ceremony (idempotent). *Note:* I did not independently re-run the on-chip ceremony (private terminal, never a Claude session); verified the preflight machinery + the production boot that consumes its keys | NONE |
| 6 | New ADR-026 authored + accepted (freshness-not-attestation limitation) | MET | **MET** | `docs/adrs/ADR-026-Per-Boot-mTLS-Ephemeral-Certificates.md` ACCEPTED 2026-06-06; §5.1 "Freshness proven; issuer attestation not" records the measured-image-CN limitation; §3 explicitly claims Condition 2 not Condition 3 (no over-claim). *Cert-count drift — MINOR-1* | NONE (MINOR-1 separate) |
| 7 | Gate-honesty obligations tracked, not silently closed (#615, #106) | MET | **MET** | Vikunja #615 exists (`done:false`, Blocked+Arch+Security, full deferral rationale); #106 bound in SDV §5.2; `default.toml:26 require_signed_manifest = false` confirms minimal-not-FUT-04 | NONE |
| 8 | Activation + daily-driver continuity (flip's final gated step; regression lock) | MET (activation+lock); cold-reboot = routine confirmation outstanding | **MET** (stronger than SCR — see divergence) | EA-4b `e1858a5` flip live (`test_lock_a_host_default_is_production` asserts `resolve_dev_mode(HOST)==False`, `test_dev_mode_interlock.py:312`); **seven** consecutive zero-manual `dev_mode=False` boots on 2026-06-06 (`launcher.log` 17:58/18:12/18:42/19:04/19:35/20:59/22:36); only the post-OS-reboot (cold-VM) permutation uncaptured | NONE |

**8 of 8 criteria MET.**

### Divergence — Criterion #8 (auditor verdict is *stronger* than SCR)

(a) **What I observed:** the launcher.log shows **seven** distinct production-default
(`dev_mode=False`) boots on 2026-06-06 (`launcher.log:9645, 9696, 9745, 9787, 9855, 9993,
10084`), each a zero-manual `python -m launcher` invocation resolving production by default,
several reaching steady-state and serving real prompts. "Daily-driver continuity across
repeated launches" is therefore *over-demonstrated*. (b) **The SCR's claim:** "MET
(activation + lock); cold-reboot continuity = routine confirmation outstanding" — grading #8
as not-fully-MET pending a post-OS-reboot boot. (c) **Why I differ:** the SDV criterion #8
verification text asks for "boot 2 — zero manual steps — proves daily-driver continuity";
that bar is met seven times over. The one genuinely-uncaptured permutation is narrower than
"continuity": it is specifically a boot **after a full OS restart**, where the Hyper-V VM
*cold-starts* rather than persists (every logged boot shows `VM 'BlarAI-Orchestrator' already
running`, `launcher.log:10092` — the VM survived across all these launches). (d) **Evidence
quality:** the per-boot certs are minted fresh on every launch regardless of VM state, and
the seven warm-VM boots prove the mint+handshake+serve path repeats deterministically; the
TPM-sealed keys + DEK keystore persist across an OS restart by construction. **I therefore
grade #8 MET**, with the post-OS-reboot boot as a genuinely-routine, low-risk confirmation —
exactly as the SCR names it, only I do not dock the criterion for it. This is a case of the
SCR being *more* conservative than the evidence requires; the honest-naming is correct, the
self-downgrade is over-cautious. Recorded as a strength of the record, not a gap.

---

## 5. Scope integrity analysis

### 5.1 Promised deliverables — completion audit

| # | Deliverable (SDV §5.1) | SCR status | Auditor finding | Commits | Gap |
|---|---|---|---|---|---|
| 1 | Per-boot mTLS cert gen + ADR-026 | COMPLETE | **CONFIRMED** | `336fcc2` (`cert_provisioning.py`, ADR-026); `a410be9` (orch+router certs) | NONE |
| 2 | Extend fail-closed mTLS lock | COMPLETE | **CONFIRMED** | `test_ipc_transport.py` Groups J/K/L/M; original :367 lock preserved | NONE |
| 3 | Dev-mode-off MECHANISM + escape hatch + blast-radius overrides | COMPLETE | **CONFIRMED** | `bab1219` (mechanism); `e1858a5` (activation + `resolve_dev_override`) | NONE |
| 4 | Precondition cascade + off-chip stub harness | COMPLETE | **CONFIRMED** | `b499bc6` (`test_cascade_stub_harness.py` 7/7) | NONE |
| 5 | Substrate comment tightening (ratify, not re-architect) | COMPLETE | **CONFIRMED** | `b499bc6` (`entrypoint.py:1012-1014` comment; +8/-2, no behavior change) | NONE |
| 6 | Ceremony + ACTIVATION + fidelity-2 live-verify | COMPLETE | **CONFIRMED** | EA-4a-f + `e1858a5`; `launcher.log` 22:36 boot | NONE |

All six in-scope deliverables landed on main and are independently confirmed.

### 5.2 Deferred items — integrity check

The three gate-honesty conditions are honored in the **shipped artifacts**, not just asserted:

- **Condition 1 (guest-boundary deferred #615):** `shared/ipc/vsock.py` marks the AF_HYPERV
  guest path "RESERVED and DEFERRED pending #615" at 8+ sites (`:26-27, 41, 64-68, 195, 254,
  275-276, 418, 471, 516-518`); `services/policy_agent/src/ipc.py:21` echoes it. The production
  path exercised was host-mode loopback+mTLS (AF_INET 127.0.0.1), with AF_HYPERV preserved but
  not claimed. **Honored.**
- **Condition 2 (no "production-verified" over-claim for the guest boundary):** ADR-026 §3
  states "this ADR claims SDV Condition 2 (host-local), not Condition 3 (guest boundary)"; the
  SCR §1/§3/§4 consistently scope the claim to host-local. I found **no** broader
  "production-verified" phrasing for the guest boundary anywhere in the shipped record.
  **Honored.**
- **Condition 3 (minimal manifest, NOT FUT-04, #106):** `default.toml:26
  require_signed_manifest = false`; `launcher.log:10102` confirms it lived in production
  ("require_signed_manifest=false; proceeding without signature verification");
  `stage_production_manifest.py:30-31` notes signing is "FUT-04 ... out of scope." Per-file
  weight integrity IS still verified (`launcher.log:10095-10105`), but signed-manifest FUT-04
  stays deferred. **Honored.**

No §5.2 out-of-scope item was pulled in. The guest channel was correctly NOT touched.

### 5.3 Unplanned additions

| Item | SCR justification | Within "mature not minimal"? | Auditor agreement | Notes |
|---|---|---|---|---|
| #618 decrypt-quarantine (both stores) | live-verify-surfaced defect, LA-ratified posture amendment | YES | **AGREE** | A defect with one nameable fix (per §6); reverses a test-locked S14 decision → correctly LA-ratified (Vikunja #618). Not silent scope creep |
| #620 gateway prompt-routing | live-verify-surfaced defect masked by EA-4f | YES | **AGREE** | Clear defect (gateway → PA:5000 instead of AO:5001); single-source-of-truth fix + real round-trip test |
| EA-4c-f boot-cascade fixes (×7) | production-only seams the green suite missed | YES | **AGREE** | Each is a refuse-to-start / wrong-boundary defect, not a capability decision; merge-gate-verified one at a time |
| EA-4e orch+router cert pairs | AO listener needed its own cert pair | YES | **AGREE** | Necessary for the host-mode mTLS handshake; *but ADR-026 not updated to match — MINOR-1* |

All unplanned additions are live-verify-driven **defect** fixes (the §"Proactive Defect-Fixing"
doctrine class), not capability decisions. None required LA escalation beyond the #618 posture
ratification, which *was* escalated (correctly — it reversed a documented S14 posture).

### 5.4 Ghost commits — independent discovery

I read the 60-commit window `e08a7db..0cbe5e2` independently. Every substantive commit maps to
an SDV deliverable, a live-verify defect ticket (#618/#620), an ACTIVE_SPRINT pointer, a
journal fold, or a governance doc (DECISION_REGISTER backfill, forward-execution-plan). No
commit represents undocumented scope drift.

| Commit | Subject | Classification | Requires LA attention? |
|---|---|---|---|
| `25211c3`, `66130e5` | DECISION_REGISTER security-ADR backfill + maintenance rule | MINOR_UNDOC (governance hygiene, not in SDV) | NO |
| `0cbe5e2` | forward execution plan (Sprint 16 → #598 → beyond) | MINOR_UNDOC (planning doc for new lead) | NO |
| `f3d4411`, `8206800`, `1730a39` | journal entries / fold | TRIVIAL (doc; expected per journal discipline) | NO |
| (all EA / #618 / #620 merges) | per SDV + defect tickets | TRIVIAL (documented scope) | NO |

The DECISION_REGISTER backfill (`25211c3`/`66130e5`) is governance-hygiene that rode the sprint
window; it is doctrine-maintenance, not EA scope drift. Correctly classified MINOR_UNDOC, no
LA attention required.

### 5.5 Cross-repo ghost-commit sweep

**N/A — single-repo sprint.** SDV §8.4 declares serial single-repo kickoff (`active_tasks.yaml`
empty at kickoff). The sprint wrote only to BlarAI `main`. The vendored `./openvino/` directory
is an upstream clone unrelated to this sprint and was excluded from all diffs.

---

## 6. Deliverable artifact fitness-for-purpose

| Deliverable | On main? | Matches SDV intent? | Fitness assessment | Evidence |
|---|---|---|---|---|
| `cert_provisioning.py` | YES | YES | Per-boot CA + ECDSA-P256 server/client certs, in-memory CA key, fail-closed on unwritable dir. Real, tested at the seam | `336fcc2`; `test_ipc_transport.py` Group J |
| Extended fail-closed mTLS lock | YES | YES | Original :367 lock preserved; Groups J/K/L add issuance/rotation/handshake/wiring coverage | `test_ipc_transport.py` (1058 LOC after) |
| ADR-026 | YES | PARTIAL | Records the decision, crypto choices, fail-closed discipline, and the freshness-not-attestation limitation correctly. **But §2/§3/§6 describe FIVE cert artifacts; the shipped code produces NINE** (orch+router added EA-4e). Doc-currency drift | ADR-026 §2.1/§6 vs `test_provision_writes_nine_pem_files` — MINOR-1 |
| Dev-mode flip + regression lock | YES | YES | `resolve_dev_mode(HOST)==production` locked; loud dev opt-in preserved; interlock refuses dev+network-facing | `e1858a5`; `test_dev_mode_interlock.py:312` |
| Minimal KGM + JWT wiring | YES | YES | `manifest.json` (real digest) staged; `require_signed_manifest=false` (minimal, not FUT-04) | `b499bc6`; `default.toml:26` |
| #618 decrypt-quarantine | YES | YES (defect fix, ADR-025 §2.7 amended) | Bulk readers quarantine; single-record/write stay hard-fail; both stores covered | `4af2033`/`6fe1fcc`; `test_session_store_decrypt_resilience.py`, `test_substrate_decrypt_resilience.py` |
| #620 round-trip integration test | YES | YES | **Real** gateway↔AO round-trip (real `VsockListener`/serve loop, GPU stubbed), red→green, both directions | `ecbd991`; `tests/integration/test_prompt_round_trip_host_mode.py` |
| Fidelity-2 live-verify evidence | YES (launcher.log) | YES | 22:36 boot: preflight, quarantine-serve, prompts, vision, clean shutdown | `launcher.log:10084-10217` |

### Detail — the two highest-value seam fixes are genuinely real (not unit locks)

**#620 (`test_prompt_round_trip_host_mode.py`, 13 KB):** stands up the **REAL** Assistant
Orchestrator IPC listener at the fixed production port 5001 (`real_ao_listener` fixture, GPU
stubbed via a fake inference that still runs the real `VsockListener` / serve loop /
`_handle_prompt_request`), points a **real** `TransportGateway` at
`resolve_gateway_port(host_mode=True)`, sends a real `PROMPT_REQUEST`, and asserts a
`STREAM_TOKEN` returns with **no** "Unsupported message type" error
(`test_prompt_reaches_ao_via_resolved_port`, asserts `resolved_port == 5001`). It also carries
the *witness* test (`test_prompt_to_pa_port_is_rejected`) reproducing the exact
`Unsupported message type: PROMPT_REQUEST` symptom against the real PA listener. This is a true
red→green reproduction **at the seam the unit suite mocked away** — lesson 65 earned.

**#618 (`test_session_store_decrypt_resilience.py` + substrate sibling):** all three bulk
readers (`list_sessions`, `get_session_turns`, `_backfill_empty_titles`) quarantine
un-decryptable rows; the single-record leaf path **still raises** (`test_single_record_leaf_
decrypt_still_raises` → `pytest.raises(RuntimeError, match="refusing to return plaintext")`).
Critically, the *mis-asserting Sprint-14 test was actually corrected*: I read
`test_session_store_encryption.py::test_wrong_key_on_existing_db_fails` (`:660`) — its docstring
now reads "Wrong-key rows are quarantined (omitted), not raised -- corrected posture" and it
asserts BOTH `list_sessions()` does NOT raise AND single-record `_dec_session_title` STILL
raises. The test that previously *locked the defect* now locks the corrected behavior — lesson
66 ("a test can lock a defect, not just a feature") is genuinely demonstrated, not just claimed.
ADR-025 §2.7 amendment (`:157`) records the bulk-vs-single-record posture with both
`SESSION_ROW_DECRYPT_QUARANTINE` and `SUBSTRATE_ROW_DECRYPT_QUARANTINE` event names.

---

## 7. EA milestone lineage and governance audit

| EA-# | Comprehension gate | Scope respected per diff? | Negative constraints honored? | CARs | Resolution |
|---|---|---|---|---|---|
| EA-1 | (paused-fleet manual dispatch) | YES | YES (mint dev_mode-gated, fail-closed) | merge-gate mint-placement fix | `3fa2315` moved mint after admin-confirmed (fire once) |
| EA-2 | manual dispatch | YES (default stayed dev) | YES (no premature flip; lock-a sentinel) | 0 | merge msg diff-verified comment-only |
| EA-3 | manual dispatch | YES (minimal, not FUT-04) | YES (substrate ratify only) | 0 | isolation-guard asserts no real keystore |
| EA-4a | manual dispatch | YES | YES | 0 | ceremony helper CLIs |
| EA-4b | manual dispatch | YES (activation = final action) | YES | 0 | THE flip; lock-a flipped True→False |
| EA-4c-f | manual dispatch | YES (each a single seam fix) | YES (#615 deferral preserved in code) | iterative live-verify | 7 boot-cascade gaps driven out one boot at a time |
| #618 / #620 | manual dispatch | YES (defect fixes) | YES | #618 posture A/B escalated to LA | LA ratified quarantine posture; #620 single-source-of-truth |

**Gate-chain narrative.** The fleet was LA-paused; EAs were manually dispatched as
worktree-isolated builder subagents under the Orchestrator merge gate. Every merge message
records a diff-review + a test re-run ("never trusted from a builder summary"), and I
spot-verified the substance: EA-1's mint-placement hardening (`3fa2315`) is a real fire-once
fix; EA-2's "default stays dev" is diff-confirmed (docstring/comment-only in `dev_mode_guard.py`,
launcher comment-region only); EA-4b's flip is the one-line `dev_mode_guard` HOST-branch
True→False with the lock flipped in the same commit. The EA-4f→#620 masking incident is the
sprint's costliest lesson and is **honestly carried in the SCR §6 and Vikunja #620** ("EA-4f …
inadvertently hid this"): a downstream fix (PA answers handshakes) made the boot *look* healthy
and concealed the upstream misroute until a real prompt was sent. This is a genuine
"mock-passes-prod-crashes / built-but-wired-into-nothing" recurrence at the system-boundary
scale — and the response (a real seam test, single-source-of-truth port, + the §2.7 mandate)
is the right systemic answer, not a patch.

**Cross-EA consistency.** Earlier EAs' outputs remained stable as later EAs built on them; the
EA-4 sub-phasing is *additive* (each sub-phase fixes a distinct seam), not rework of a prior
EA. The one cross-EA coupling — EA-4f masking #620 — was caught and corrected, not left.

---

## 8. Test coverage and quality assessment

### 8.1 Baseline delta — independently reproduced

| Metric | Before sprint | After sprint | Delta | SCR claimed |
|---|---|---|---|---|
| Layer-A suite (passed / skipped / deselected) | 2055 / — / 15 | **2172 / 2 / 15** | **+117** | 2172 / 2 / 15 ✓ |
| Failures | 0 | **0** | = | 0 ✓ |

**Command (exactly as specified):**
`.venv/Scripts/python.exe -m pytest shared/ services/ launcher/ -m "not hardware and not winui and not slow" -q -p no:cacheprovider`
**Result: `2172 passed, 2 skipped, 15 deselected, 2 warnings in 84.41s` — exit code 0.**
This matches the SCR's claim **exactly**. The 2 warnings are the same benign SWIG
`DeprecationWarning`s from a transitive C-extension noted in the Sprint-14 SWAGR, unrelated to
this sprint. The 2 skips are the two permanently-accepted Qwen3 thinking-suppression skips
(TEST_GOVERNANCE §3). Collection integrity confirmed (suite ran to completion, snapshot test
passed). Arc 2055 → 2172 confirmed against both frontmatters.

### 8.2 Per-service coverage change

| Service cluster | Coverage direction | Notable additions | Notable gaps remaining |
|---|---|---|---|
| `policy_agent` | STABLE | handshake handler test (EA-4f) | guest-boundary AF_HYPERV (#615, deferred) |
| `assistant_orchestrator` | IMPROVED | substrate decrypt-resilience (quarantine + leaf-hard-fail) | — |
| `ui_gateway` | IMPROVED | session-store decrypt-resilience; round-trip integration | model-loaded GUI path (#621, deferred) |
| `shared` | IMPROVED | cert_provisioning (Group J/K/L), ceremony_preflight, vsock host-mode | — |
| `launcher` | IMPROVED | dev-mode interlock (mechanism + activation locks); `resolve_gateway_port` | production-parity boot cascade in CI (#619, deferred) |
| `tests/integration` | IMPROVED | `test_prompt_round_trip_host_mode.py` (real gateway↔AO) | full E2E in CI (deferred to #619) |

### 8.3 Test quality (not just quantity)

The new tests assert on **behavior at the seam**, not existence:
- `test_prompt_round_trip_host_mode.py` exercises the real AO listener + real gateway and
  asserts the *absence* of the failure symptom in caplog — a true integration assertion.
- The #618 tests assert the precise differentiated posture (bulk quarantines, single-record
  raises) with `pytest.raises(... match="refusing to return plaintext")` — boundary-correct.
- **No assignment-in-place-of-assertion pattern observed** in the files I read.
- **Critically — a fail-closed test was *corrected*, not weakened:** the Sprint-14
  `test_wrong_key_on_existing_db_fails` was rewritten to assert the *corrected* quarantine
  posture while **retaining** the single-record hard-fail assertion (§6). This is the rare,
  legitimate case where changing a green test is the right move because the test encoded a
  defect — and the confidentiality lock (no-plaintext-fallback) is provably preserved.

### 8.4 TEST_GOVERNANCE.md compliance

- The integration test landed in `tests/integration/` (correct placement per §6 boundary rule).
- TEST_GOVERNANCE §2.7 ("Test Coverage Mandate") was authored this sprint (`0834d44`/`8206800`)
  and is dated 2026-06-06 — a genuine doctrine artifact, not a stub (§9.5 confirms currency).
- The §1 named-scope baseline table (UNIT 755 / FOCUSED 791 / etc.) is **stale** vs. the live
  2172 Layer-A count — but those rows are the older named-scope baselines, not the Layer-A
  selection; the canonical live baseline is carried in CLAUDE.md + the SCR. Minor staleness,
  consistent with how the project tracks Layer-A separately. Recorded as MINOR-5.

### 8.5 Security-domain regression check

The sprint touched the security boundary heavily (`shared/ipc/`, `shared/security/`,
`session_store.py`, `substrate.py`, `dev_mode_guard.py`, both service entrypoints). I scanned
the full sprint diff `e08a7db..0cbe5e2` for the regression patterns:

| Surface | Pre-sprint | Post-sprint | Regression? | Evidence |
|---|---|---|---|---|
| Session-store bulk decrypt | raise whole op (brick) | quarantine row + WARNING; single-record still raises | **NONE (intentional improvement)** | `session_store.py` +97; `test_session_store_decrypt_resilience.py` |
| Substrate bulk decrypt | raise (brick AO start) | quarantine; leaf decrypt still raises | **NONE (intentional improvement)** | `substrate.py` +128; `test_substrate_decrypt_resilience.py` scenario (c) |
| Leaf/single-record decrypt | raise `RuntimeError`/`FieldCipherError` | **unchanged** — still raises | **NONE** | `test_single_record_leaf_decrypt_still_raises`; `test_direct_decrypt_wrong_key_raises` |
| Dev-mode default (HOST) | dev (insecure) | production (secure) | **NONE (the sprint's point)** | `test_lock_a_host_default_is_production`; interlock retained |
| mTLS handshake | placeholder certs (would fail-to-start) | real per-boot certs, CERT_REQUIRED both ways | **NONE (new control)** | ADR-026 §2.4; Group K |

**No assertion downgrade, no fail-closed weakening, no mock-papering, no threshold relaxation.**
The two decrypt changes are *availability* improvements that provably preserve confidentiality
+ integrity (plaintext never returned; quarantine = absent, not decrypted-under-wrong-key).

**Privacy-mandate scan:** `git diff e08a7db..0cbe5e2 -- shared/ services/ launcher/` shows
**no** added `requests` / `urllib` / `httpx` imports and **no** external `socket.create_connection`
to a non-loopback host (the only socket additions are the AF_INET 127.0.0.1 loopback transport
and the reserved AF_HYPERV path). **ADR-011 (GPU-only) scan:** no NPU revival in production
source (the only `input(...)` matches are interactive ceremony prompts; no `openvino ... NPU`
device strings). The privacy + GPU-only mandates hold.

---

## 9. Architecture and governance completeness

### 9.1 ADR alignment

| ADR | Relevant? | Respected? | Evidence | Drift |
|---|---|---|---|---|
| ADR-010 (PA on GPU) | YES | YES | PA classifier loaded device=GPU (`launcher.log:10107`) | NONE |
| ADR-011 (GPU-only inference) | YES | YES | shared LLMPipeline device=GPU; no NPU in window source | NONE |
| ADR-012 (Qwen3-14B + spec-decode) | YES | YES | target Qwen3-14B + draft Qwen3-0.6B-pruned-6L (`launcher.log:10099`) | NONE |
| ADR-018 (TPM trust root) | YES | YES | DEK+audit+JWT keys TPM-backed; ceremony idempotent | NONE |
| ADR-021 (TPM-sealed JWT key) | YES | YES | JWT key minted via `provision_signing_key` (criterion #5) | NONE |
| ADR-025 (at-rest) | YES | YES | §2.7 amended for quarantine; encrypted stores live (`launcher.log:10118/10124`) | NONE |
| ADR-026 (per-boot mTLS) | YES (authored) | YES | the sprint's own ADR; freshness-not-attestation limitation recorded | **MINOR-1 (cert-count drift in the ADR text)** |

ADR-026's one drift: §2/§3/§6 describe five cert artifacts; the shipped code mints nine (orch +
router pairs added EA-4e). The *decision and limitations* are correct; the *artifact inventory*
is stale. Full detail in §13 MINOR-1.

### 9.2 DEC governance completeness

The #618 posture change (bulk-read quarantine, reversing a test-locked Sprint-14 decision) was
the one mid-sprint *decision* (vs. defect). It was correctly escalated to the LA for
ratification (Vikunja #618: "pending LA ratification of the posture amendment ... NOT a
unilateral defect fix") and recorded in **ADR-025 §2.7 amendment** + the SDV §3 amendment
(per the #618 merge message). This is the right governance shape — a decision that changes a
documented posture went through ADR amendment, not a silent fix. No missed DEC trigger found.

### 9.3 Ledger completeness

- **Sprint-15 ledger entry: ABSENT.** `docs/ledger/` ends at
  `20260606_010000_sprint14_scr_at-rest-encryption.md`; no Sprint-15 entry exists.
- This is **benign sequencing** (identical to Sprint-14 SWAGR MINOR-2): the SWAGR runs *before*
  the Orchestrator's final close commit, and SCR §9 "Post-SWAGR reconciliation" is explicitly
  pending. Per CLAUDE.md DEC-17 (permanent rule), the entry must land in `docs/ledger/` per-file
  at the close. Recorded as MINOR-2 so it is not dropped.
- The 13 journal fragments WERE folded into BUILD_JOURNAL (`1730a39`, lessons 57-66) — the
  journal discipline is complete; only the *ledger* close entry is outstanding.

### 9.4 Nomenclature and naming discipline

- One known stale-naming residual is **already ticketed**: the gateway's
  `check_pa_status`/`_attempt_pa_handshake` methods now handshake the AO (post-#620), not the
  PA — tracked #623 (low priority, ~35 files, deliberately kept out of the #620 diff per SCR
  §5). Correctly deferred per the hardening-followups-are-non-optional rule.
- No NPU-in-production-source naming drift (ADR-011). Service names + path conventions consistent.

### 9.5 Documentation currency

| Document | Accurate? | Stale section |
|---|---|---|
| CLAUDE.md | STALE (expected) | "Active State" still describes Sprint 11 as ACTIVE; the live HEAD/sprint advanced to 15. This is the known "pinning HEAD in doctrine goes stale" pattern the doc itself warns about; not a Sprint-15 defect — recorded as MINOR-4 for the close sweep |
| TEST_GOVERNANCE.md | YES (§2.7 current) | §1 named-scope baseline rows stale vs. Layer-A 2172 (MINOR-5) |
| ADR-026 | STALE (cert count) | §2/§3/§6 say 5 certs, code mints 9 (MINOR-1) |
| ADR-025 | YES | §2.7 amendment current |
| SECURITY_ROADMAP_air_gap_removal.md | STALE | §1/§3/§4 + Decision-1 still read Cleaner "post-#598 fast-follow"; reconcile per #613 (MINOR-6; SCR §7 already flags it) |

---

## 10. Risks and unknowns — hindsight analysis

### 10.1 SDV §9.1 known risks — actualization audit

| Risk (SDV) | Actualized? | Mitigation effective? | SCR honest? | Notes |
|---|---|---|---|---|
| Flip touches boot path → refuse-to-start regression | **YES** (×7 boot-cascade gaps + 2 decrypt-bricks) | **YES** | YES | The staged-cascade + escape-hatch + iterative live-verify caught every gap before the default flip stuck; no brick window materialized (default stayed dev until everything present) |
| Ceremony/live-verify needs LA chip, can stall | PARTIAL | YES | YES | The on-chip session ran iteratively (the predicted 1-2 cycles became more, but each cycle was a discrete merge-gated fix); off-chip stub harness narrowed the chip surprises as designed |
| Per-boot cert rotation edge cases | NO (no rotation defect surfaced) | YES | YES | Group J/K cover issuance + lifetime; 24h lifetime decision recorded in ADR-026 §2.1 |
| Scope blur — fidelity-2 over-claimed | NO | YES | YES | Conditions 1/2/3 held in shipped artifacts (§5.2); no over-claim found |
| Guest-channel temptation | NO | YES | YES | Guest path explicitly reserved/deferred in `vsock.py`; not touched |

The headline risk (boot-path regression) **actualized ten times** — and the §9.3 "unknown
unknowns posture" ("treat the first clean `dev_mode=false` boot as the real test, not the unit
suite") proved exactly right. The SCR's assessment of each risk is honest and matches the
evidence.

### 10.2 SDV §9.2 known unknowns — resolution audit

1. **Sprint-14 ceremony provisioned audit key on *this* chip?** — RESOLVED (confirmed present,
   idempotent; criterion #5). Independent caveat: I verified the *preflight machinery* and the
   production boot consuming the keys, not the on-chip ceremony itself (correctly a non-Claude
   private-terminal step).
2. **Per-boot cert lifetime/cadence?** — RESOLVED (24h, ADR-026 §2.1).
3. **Host-local vsock vs. real TLS socket for fidelity-2?** — RESOLVED (AF_INET 127.0.0.1
   loopback + production SSL contexts; `launcher.log:10126`).

### 10.3 New risks discovered during this audit

| Risk | Severity | How noticed | Evidence | Suggested mitigation |
|---|---|---|---|---|
| **The §2.7 "test the seam" mandate has near-zero CI enforcement yet** — there is no `.github/workflows/` at the BlarAI repo root; the only running enforcement is the static `test_secure_defaults.py` posture lock + the one #620 round-trip test | MEDIUM | Searched for CI workflows; only the vendored `openvino/.github/` exists | no BlarAI CI runner; §2.7 cadence defers production-parity lane to #619/#621/#622 (Sprints 16+) | Prioritize #619 (production-parity boot cascade in CI) early in Sprint 16 — the mandate is currently policy + one seam test, not structural prevention |
| **Cold-VM (post-OS-reboot) cert/handshake permutation untested** | LOW | every logged boot shows "VM already running" | `launcher.log:10092` etc. | The one routine confirmation boot the SCR already names (criterion #8) |
| **Two dev-era un-decryptable rows persist in the live `sessions.db`** | LOW | quarantine WARNINGs every boot | `launcher.log:10151-10153` | Quarantine handles them safely; optionally wipe the practice rows (operator action) to silence the recurring WARNING — no security impact |

The first is the most valuable forward signal: the sprint *named and ticketed* the
mock-passes-prod-crashes class (TEST_GOVERNANCE §2.7, #622) and made a real down-payment (the
#620 round-trip test), but the **structural** prevention — prod-only bugs hitting CI instead of
the LA's terminal — is entirely deferred. That is honest (not a paper claim — §2.7 says so
explicitly), but it means the class can recur in Sprint 16 until #619 lands.

### 10.4 Carry-over items for next sprint

In-scope-for-next-sprint: (1) **#619** production-parity test lane (the systemic fix; should be
early Sprint 16); (2) the **cold-reboot continuity boot** (criterion #8 routine confirmation,
LA on-chip). Backlog-until-prioritized: #621 (WinUI harness — extend existing pywinauto, NOT
build FlaUI), #622 (coverage-audit umbrella), #623 (gateway method rename), #615 (guest
boundary — VM-occupant sprint), #106 (FUT-04 weight integrity — Tier-3).

---

## 11. Fleet process health

### 11.1 EA comprehension quality

The fleet was LA-paused; EAs were manually-dispatched worktree builder subagents (model
sonnet). Comprehension is inferred from scope discipline in the merged diffs rather than from
gate-comment streams: each EA's diff is tightly scoped to its deliverable (EA-2 comment-only in
the resolver; EA-3 ratify-not-rearchitect on the substrate comment; EA-4 sub-phases each a
single seam). No scope overrun observed.

### 11.2 Orchestrator (merge-gate) review rigor

The merge gate held throughout and demonstrably caught real issues: EA-1's mint-placement was
*rejected and re-fixed* at the gate (`3fa2315`, fire-once); every merge message records a diff
review + an independent test re-run with a count ("never trusted from a builder summary"); the
closing session re-ran the full Layer-A suite live (2172) rather than inheriting a number — which
I independently confirmed. This is the genuine article, not a rubber stamp.

### 11.3 LA review rigor (the #618 escalation)

The #618 posture change was twice (per SCR §6) almost escalated as a *decision*, and the LA
collapsed it each time to a *defect* with one nameable fix ("is there really more than one
correct answer?"). This is the §"Proactive Defect-Fixing" boundary working correctly: the bulk
readers had one correct behavior (quarantine), so it was a defect; the *posture amendment* that
documented it (ADR-025 §2.7) was the part that warranted ratification, and it got it. Clean.

### 11.4 CAR frequency and resolution

| Metric | Value |
|---|---|
| Merge-gate rejections (CAR-equivalent) | ≥1 (EA-1 mint-placement) |
| Live-verify-driven defect tickets | 2 (#618, #620) + 7 boot-cascade in-flight fixes |
| Escalated to LA | 1 (#618 posture amendment) |

The "CARs" here are the live-verify defect cycles — all appropriate (genuine production-only
defects, not over-triggering). None should-have-been-raised-but-missed found.

### 11.5 Autonomy budget compliance

Fleet was LA-paused; all work was manually dispatched under the merge gate (`review_all`
posture by construction). No autonomy-budget breach possible.

### 11.6 DEC-15 sprint lifecycle health

The SDV → SCR → SWAGR chain produced the expected artifacts. One lifecycle nuance worth noting:
the SCR was authored 2026-06-07 (after all EAs + #618/#620 merged and after the closing-session
test re-run) — correctly sequenced, not premature. This SWAGR fires after the SCR with the full
2172 baseline and all merges visible. The ledger close entry (MINOR-2) is the only lifecycle
artifact still pending, which is the normal SWAGR-before-close ordering.

---

## 12. System maturity trajectory

### 12.1 Capability maturity narrative

BlarAI today runs **production-by-default**: the two operational use cases (UC-001 PA, UC-004
AO) boot under real per-boot mTLS, TPM-sealed at-rest encryption, and live audit/JWT signing —
the configuration that ships, not a relaxed dev fiction. What works reliably: the full
prompt+vision round-trip in production posture (proven on the 22:36 boot), with the new
default-ON preflight self-checking the prompt route before the UI appears. What is fragile: the
*verification* of that posture is still largely manual (the LA's terminal caught all ten
production-only defects, not CI). What is unbuilt: the guest-boundary handshake (#615), full
FUT-04 weight integrity (#106), and everything Tier-3 (egress mediation, web-nav). Against the
9 Use Cases, this sprint moved UC-001/UC-004 from "operational in dev posture" to "operational
in production posture" — a maturity step, not a capability expansion.

### 12.2 Reliability and correctness trajectory

Trending **up**: +117 tests (2055 → 2172), zero regressions, zero fail-closed weakenings, and
the highest-value addition is *integration* coverage at a seam that had burned the project (the
#620 round-trip). The decrypt-quarantine change converts a self-inflicted-DoS failure mode (one
bad row bricks the store) into isolate-and-surface. Ledger/journal discipline is healthy (13
fragments folded, lessons 57-66). The one counter-signal: the sprint *discovered* that the
existing test apparatus (unit suite + the #563 scenario harness) systematically misses
production seams — an honest, valuable finding that the §2.7 mandate now targets.

### 12.3 Technical debt accumulation / repayment

**Net debt repayment.** Closed: the dev-mode-as-default trap (the central debt this sprint
existed to pay), two decrypt-brick defects (both stores), the gateway-misroute. Added (all
ticketed, none silent): the §2.7 CI-enforcement gap (#619), the WinUI harness gap (#621), the
gateway method-naming debt (#623), the ADR-026 cert-count drift (MINOR-1, new). Doc debt is
small and tracked (SECURITY_ROADMAP Cleaner refs #613; CLAUDE.md staleness). The hardening
follow-ups are correctly non-optional tickets, not "suggested."

### 12.4 Projected next-sprint impact

The single most important Sprint-16 outcome: **stand up #619 (the production-parity test lane)**
so the mock-passes-prod-crashes class hits CI instead of the LA's terminal. Sprint 15 paid the
posture debt and *named* the testing debt; Sprint 16 should pay the testing debt before it
recurs. The cold-reboot confirmation boot (criterion #8) is a 5-minute LA action that can ride
alongside.

---

## 13. Consolidated gap inventory

| # | Section | Gap description | Severity | Evidence | Recommended action |
|---|---|---|---|---|---|
| 1 | §6/§9.1 | **ADR-026 cert-count drift**: §2/§3/§6 describe FIVE cert artifacts (CA + PA-server + gateway-client); the shipped `cert_provisioning.py` mints NINE (orch + router pairs added EA-4e `a410be9`). ADR text never mentions the orch/router certs. Code is correct + tested; the ADR artifact inventory is stale | MINOR | ADR-026 §2.1 "All five artifacts" / §6 "five per-boot cert artifacts" vs `test_ipc_transport.py::test_provision_writes_nine_pem_files` | Update ADR-026 §2/§3/§6 to describe the 5→9 cert set (add orch + router pairs + their gitignore entries), as part of the close |
| 2 | §9.3 | **No Sprint-15 ledger close entry** in `docs/ledger/` (ends at the Sprint-14 entry). Benign SWAGR-before-close sequencing (mirrors S14 SWAGR MINOR-2); DEC-17 requires the per-file entry | MINOR | `docs/ledger/` newest = `20260606_010000_sprint14_...`; SCR §9 "Post-SWAGR reconciliation (pending)" | Author the Sprint-15 `docs/ledger/` close entry at the close (fold this SWAGR's verdict + the cold-reboot carry-over) |
| 3 | §3.5 | **Vikunja #618 and #620 still `done:false`** though both are fully implemented + merged + tested | MINOR | `mcp__vikunja__get_task` 618/620 → `done:false`; merges `4af2033`/`6fe1fcc`/`ecbd991` on main | Mark #618 + #620 complete (with the merge SHA + test count) at the close |
| 4 | §9.5 | **CLAUDE.md "Active State" stale** — still describes Sprint 11 as ACTIVE; HEAD/sprint advanced to 15. The doc itself warns HEAD-pinning goes stale | MINOR | CLAUDE.md §"Active State" vs `git log` HEAD `0cbe5e2` | Refresh CLAUDE.md Active-State to Sprint 15 close at the next doctrine sweep (not a Sprint-15 defect) |
| 5 | §8.4 | **TEST_GOVERNANCE §1 named-scope baseline rows stale** (UNIT 755 / FOCUSED 791 / FULL 835) vs. the live Layer-A 2172. The §2.7 mandate text is current; only the §1/§3 baseline table lags | MINOR | TEST_GOVERNANCE §1/§3 vs reproduced 2172 | Reconcile the §1/§3 baseline rows (or annotate that Layer-A is tracked separately in CLAUDE.md/SCR) |
| 6 | §9.5 | **SECURITY_ROADMAP_air_gap_removal.md §1/§3/§4 + Decision-1 still read Cleaner "post-#598 fast-follow"** (Decision-4 already amended; #613 moved the Cleaner off-roadmap) | MINOR | SCR §7 already flags this | Reconcile the remaining Cleaner refs per #613 |

**Totals**: Critical: **0** · Major: **0** · Minor: **6**

All six MINORs are honesty-of-record / doc-currency / ticket-hygiene items. **None compromises
the production-security substance**, which is real and live-verified. MINOR-2/3 are the normal
SWAGR-before-close residuals (author the ledger entry + mark the two tickets done at the close).
MINOR-1 is the one genuinely-new finding the SCR did not surface (the ADR-026 cert-count drift).

---

## 14. Recommendations for next sprint

1. **(LA)** **Stand up #619 (production-parity test lane) early in Sprint 16.** Evidence: the
   sprint discovered the unit suite + the #563 scenario harness both miss production seams
   (§7, §10.3); §2.7 mandates the fix but defers all CI enforcement. The #620 round-trip test is
   the seed — generalize it to a boot-cascade + key-transition lane before the class recurs.
2. **(LA)** **Capture the cold-reboot continuity boot** (criterion #8 routine confirmation) — one
   `python -m launcher` after an OS restart, evidence appended. Low-risk, closes the one
   uncaptured permutation. ~5 min on-chip.
3. **(BOTH)** **Fix the ADR-026 cert-count drift (MINOR-1)** as part of the close — the ADR
   under-describes the shipped artifact set by 4 cert files. A doc-currency fix on the
   IAPP-portfolio surface, where the standard is strictest.
4. **(LA)** **Author the Sprint-15 ledger close entry + mark #618/#620 done** (MINOR-2/3) — the
   normal post-SWAGR close actions.
5. **(PM/LA)** **Sequence #621 (WinUI harness) by *extending the existing pywinauto Layer-C
   harness*, not building FlaUI from scratch** — the SCR §6 already corrected this from a false
   "no UI tests exist" claim; ensure the Sprint-16 SDV inherits the corrected framing.
6. **(LA)** **Keep #615 + #106 as named #598 gate obligations** in the Sprint-16 SDV — they are
   the remaining gate-critical work; the air-gap cannot come down on fidelity-2 alone.

---

## 15. LA action items

### 15.1 Product / PM actions

- **Prioritize #619 ahead of feature work in Sprint 16** (gap §10.3 / rec 1): the testing-debt
  the sprint named will let production-only defects keep reaching your terminal until the
  production-parity lane exists. This is a roadmap-priority call only you can make.
- **Confirm the #621 framing** (rec 5): the harness is an *extension* of the existing pywinauto
  apparatus, not a from-scratch FlaUI build — the prior session's confident-but-wrong claim was
  caught; ensure the corrected scope sticks.

### 15.2 Technical / LA actions

- **Capture the cold-reboot boot** (criterion #8 / rec 2): the only uncaptured continuity
  permutation; high-confidence pass.
- **Approve the ADR-026 cert-count correction** (MINOR-1 / rec 3): the ADR should match the
  nine-cert reality the code already ships + tests.

### 15.3 Process / fleet health actions

- **Direct the close actions**: author the Sprint-15 `docs/ledger/` entry (MINOR-2) and mark
  Vikunja #618 + #620 done (MINOR-3); reconcile the stale CLAUDE.md Active-State (MINOR-4),
  TEST_GOVERNANCE §1 baseline (MINOR-5), and SECURITY_ROADMAP Cleaner refs (MINOR-6) at the next
  doctrine sweep. None blocks the sprint; all are tracked here so none is dropped.

---

## Appendix A — Auditor scope declaration

The Sprint Auditor was invoked manually (fleet LA-paused) as a peer to the Orchestrator per
DEC-15, with a fresh context and no memory of this sprint's in-flight reasoning. I formed my own
view of the sprint window — git log `e08a7db..0cbe5e2`, the live `launcher.log`, the shipped
source, the Vikunja gate tickets, and an independently-reproduced 2172-test run — BEFORE reading
the SCR, in the prescribed order. The audit posture is adversarial by design; the agreement with
all 8 SCR verdicts is earned by independent citation, not deference, and on criterion #8 my read
is independently *stronger* than the SCR's. All verdicts are my best-faith independent read based
solely on the artifacts in §2.1. I did not read any chat transcript or Orchestrator narration; I
did not run the launcher or boot the system; I did not run pytest against the real
`%LOCALAPPDATA%` (confirmed conftest isolation first); I did not post any Vikunja comment or
mutate any file other than this SWAGR. The auditor may be wrong; LA veto rights apply in full. If
a gap assessment is disputed, this SWAGR is NOT rewritten — per DEC-15, the LA opens a separate
workstream.

_(Signed via frontmatter `auditor_session_fired_at` + the git commit by the Orchestrator that
lands this SWAGR on main — the auditor does not commit.)_

---

## Appendix B — Independent verification log (what I actually ran/read)

| Check | Method | Result |
|---|---|---|
| Test baseline | re-ran the exact pytest command, `-p no:cacheprovider` | 2172 passed / 2 skipped / 15 deselected / 0 failed, 84.41s, exit 0 — matches SCR exactly |
| Test isolation | read `conftest.py` | module-load redirect of LOCALAPPDATA/HOME/XDG + `BLARAI_DEK_KEYSTORE` unset confirmed active |
| EA merge SHAs | `git show --stat` on 336fcc2/bab1219/b499bc6/e1858a5/04c45fd/ecbd991 (+ log for 217ba32/c26cf11/a410be9/5ac5f9e/4af2033/6fe1fcc) | all 12 claimed SHAs present in `e08a7db..0cbe5e2`, diffs substantive + coherent |
| Criterion #1 | read `test_ipc_transport.py` Groups J/K/L; confirmed `cert_provisioning.py` (420 LOC) | original :367 lock intact; per-boot issuance/rotation covered |
| Criterion #2/#8 | read `test_dev_mode_interlock.py` | `test_lock_a_host_default_is_production` asserts `resolve_dev_mode(HOST)==False`; lock-a history shows sentinel→production flip |
| Criterion #4 | read `launcher.log:10084-10131` | production interlock PASS, fidelity-2 transport ready, mTLS handshake attempt-1 success |
| #618 | read `test_session_store_decrypt_resilience.py` + substrate sibling + the *rewritten* `test_wrong_key_on_existing_db_fails` | bulk quarantine + single-record hard-fail both verified; mis-test corrected |
| #620 | read `test_prompt_round_trip_host_mode.py` | real AO listener + real gateway round-trip, both directions (green + witness) |
| Gate-honesty | grep `vsock.py` (#615 deferral), `default.toml` (require_signed_manifest=false), ADR-026 §3/§5 | all 3 conditions honored in shipped artifacts |
| Live-verify boot-1 | read `launcher.log:10091-10217` (the 22:36 boot) | preflight pass, decrypt-quarantine-then-serve, prompts, Qwen3-VL load/describe/evict, rc=0 shutdown — every SCR claim confirmed |
| Criterion #8 continuity | grep dev_mode interlock across all 2026-06-06 boots | 7 consecutive zero-manual production-default boots (warm VM); cold-VM permutation the only gap |
| Privacy/NPU | `git diff e08a7db..0cbe5e2 -- shared/ services/ launcher/` pattern scan | no external network calls added; no NPU revival |
| Vikunja gate-trace | `get_task` 615/618/620 | #615 done:false (correctly open obligation); #618/#620 done:false (MINOR-3, fully merged) |

---

*Independent Sprint Auditor — read-only. This report was written to
`docs/sprints/sprint_15/Strategic_Work_Analysis_and_Gap_Report_Sprint_15_20260607_094439.md`;
the Auditor did not modify source, did not commit, and did not merge.*
