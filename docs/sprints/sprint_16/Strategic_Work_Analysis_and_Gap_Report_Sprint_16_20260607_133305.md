---
sprint_id: 16
sprint_name: "The Automation Wave — Production-Parity Test Lane + Gate-Critical Hardening (parallel)"
document_type: SWAGR
auditor: "Independent Sprint Auditor (Claude Opus 4.8, 1M context)"
audit_date: "2026-06-07"
vikunja_tracking_task_id: 624
sdv_path: "docs/sprints/sprint_16/strategic_design_vision.md"
sdv_version_reviewed: 2
scr_path: "docs/sprints/sprint_16/strategic_completion_report.md"
scr_version_reviewed: 1
auditor_session_fired_at: "2026-06-07T13:33:05-07:00"
main_tip_reviewed: "560b6ad"
swagr_version: 1
overall_alignment_verdict: "STRONG_ALIGNMENT"
functional_impact_verdict: "MODERATE"
architecture_health_verdict: "IMPROVED"
test_baseline_reproduced: "Layer-A 2187 passed, 2 skipped, 15 deselected, 0 failed (86.23s) — independently re-run, exit 0; #619 lane tests/integration 18 passed, 88 deselected, 0 failed (6.58s) — independently re-run, exit 0"
test_baseline_delta: "+15 Layer-A (2172 → 2187); +17 integration-lane (D's key-transition 9 + boot-cascade-stubbed 8); 0 regressions"
criteria_summary: "9/9 MET (8 deliverable criteria + #9); 2 MET-as-scoped carry deferred dev-machine green runs (#1 GUI, #6(ii-b) real-GPU)"
gaps_count_critical: 0
gaps_count_major: 0
gaps_count_minor: 5
---

# Strategic Work Analysis and Gap Report — Sprint 16: The Automation Wave (Production-Parity Lane + Gate-Critical Hardening)

**Adversarial, independent, read-only.** Every load-bearing claim below was verified against git
history, the actual shipped source, two independently-reproduced test runs, and the on-disk artifacts
— *not* against the SCR's prose. Findings are cited with commit SHAs, `file:line`, and test names.

---

## 0. Auditor's stance

The default posture for this audit was "something was probably missed — prove otherwise." I formed my
own view of the sprint window (git log `82a21e5..560b6ad`, the 7 stream merges, the shipped source, and
both reproduced test lanes) BEFORE reading the SCR's verdicts, in the prescribed order. I read no chat
transcript and no Orchestrator narration; the Vikunja #624 `Gate:Approved` state was noted as gate-trace
only and treated as a claim to verify, not ground truth.

The notable result mirrors Sprint 15: **I agree with all 9 of the SCR's criterion verdicts**, and that
agreement is earned, not deferred — every criterion below carries an independent citation, I reproduced
both the 2187 Layer-A baseline and the 18-test integration lane exactly, and I independently confirmed
the two hardest-to-trust gradings (#1 GUI BUILT-not-VERIFIED, #6(ii-b) real-GPU BUILT-not-VERIFIED) are
**honest** — neither over-claims a green run that did not happen. The five findings are all MINOR
(doc-currency / honesty-of-record / a relocated-not-closed structural gap), none of which compromises
the substance the sprint delivered.

No commendations are included (project doctrine).

---

## 1. Executive judgment

**Product lens (functional_impact_verdict: MODERATE).** Sprint 16 is a force-multiplier sprint, not a
capability sprint. It did not add a user-facing feature; it built the **automated coverage of the seams
the unit suite mocks** — the boot cascade and the key-transition path now have real-integrated-path
locks (17 tests in `tests/integration/`), the WinUI critical path has a real pywinauto harness (13
scenarios, built + scripted), and the model weight-integrity gate now sweeps **every** manifest entry
instead of one file. In the same wave it landed two gate-critical hardening items (dependency pinning,
the staged signed-manifest mechanism) and two read-mostly audits that give the #598 campaign a verified
state-tracker and a coverage gap-list. The functional delta to the *running system* is the
weight-integrity sweep (a real fail-closed widening at load) and the staged-but-inert manifest signature
mechanism; everything else is test/automation/doc infrastructure that pays down the testing debt
Sprint 15 named. That is exactly what the SDV promised — "one wave toward the gate, not the gate."

**Technical lens (overall_alignment_verdict: STRONG_ALIGNMENT).** The work was executed correctly and
the disjoint 7-stream parallel shape held end-to-end: I independently inspected all 7 merge diffs and
found **no two streams touch the same file** (§7). The merge gate's "never trust the summary" discipline
is demonstrably real — I reproduced the exact collection-error count (4, confined to `tools/tests/`) that
the SCR says the Orchestrator caught a builder over-stating at 41. The single most important thing the LA
should know: **the sprint is genuinely complete as scoped, the two deferred green runs are honestly named
(not claimed), and #106/FUT-04 correctly stays PARTIAL with no signature staged** (no `.sig` exists in
HEAD; the shipped `require_signed_manifest=false` in both configs means no boot can brick). The one
forward signal worth the LA's attention is a *relocated* structural gap, not a new defect: the
production-parity lane lands in `tests/integration/`, which the canonical Layer-A gate excludes — so the
lock-before-modify guarantee for Sprint 17 holds only if the cascade gate is run in a `tests/`-inclusive
scope. The SCR names this honestly (lesson 70 + a carry-over recommendation); it is the Sprint-15
"§2.7 has near-zero CI enforcement" pattern paid down in part and relocated, not closed (§10.3).

---

## 2. Review method

### 2.1 Artifacts consulted

| Artifact | Version / commit | Date / range |
|---|---|---|
| SDV: `docs/sprints/sprint_16/strategic_design_vision.md` | v2 (signed 2026-06-07) | 2026-06-07 |
| SCR: `docs/sprints/sprint_16/strategic_completion_report.md` | v1 | 2026-06-07 |
| Predecessor SWAGR: `docs/sprints/sprint_15/...20260607_094439.md` | v1 | 2026-06-07 (cross-sprint baseline) |
| Git log (sprint merge ancestry) | `82a21e5..560b6ad` | 18 commits (7 merges + 9 stream/fragment + fold + SCR) |
| Stream E output: `docs/security/SECURITY_ROADMAP_air_gap_removal.md` §5 | `7c7db3d` | 2026-06-07 |
| Stream F output: `docs/sprints/sprint_16/coverage_audit.md` | `45746ef` | 2026-06-07 |
| `docs/TEST_GOVERNANCE.md` | §2.5/§2.6/§2.7 + §1 baseline | — |
| Shipped source (B1/B2/C/D/A) | per §4 citations | — |
| Independently re-run Layer-A suite | `2187 passed, 2 skipped, 15 deselected` | 2026-06-07, 86.23s, exit 0 |
| Independently re-run #619 lane | `18 passed, 88 deselected, 0 failed` | 2026-06-07, 6.58s, exit 0 |
| Vikunja tracking task #624 (gate-trace only) | `Gate:Approved`, `done:false` | — |

### 2.2 Deliberate exclusions

- **No chat transcript / Orchestrator narration read** — independence from the team's narrative is the
  audit's value (per the template's "does NOT read" list).
- **Did not run the launcher / boot the system / run `dotnet build`** — no Windows .NET toolchain run was
  performed; the `dotnet build SUCCEEDED` evidence is the Orchestrator's merge-gate record (it is not
  load-bearing for the "MET-as-scoped, run deferred" grade for #1).
- **Did not run the `hardware`/`winui`-marked tiers** — by construction they need the GPU/desktop; I
  confirmed they are correctly marked + deselected, and read their bodies to confirm they are real.
- **Did not post any Vikunja comment or create any task; did not mutate any file other than this SWAGR.**

### 2.3 Test-process isolation confirmed (lesson-55 guard) — RAN BEFORE ANY PYTEST

Before running any test, I read `conftest.py` (repo root). It mutates `os.environ` at **module load**
(process startup, before collection imports any BlarAI module): redirects `LOCALAPPDATA`, `HOME`,
`XDG_DATA_HOME` to a throwaway `tempfile.mkdtemp(prefix="blarai-pytest-userdata-")` and
`os.environ.pop("BLARAI_DEK_KEYSTORE", None)` (`conftest.py:74-79`). This is the durable fix for the
Sprint-14 incident where a suite run corrupted the real `sessions.db`. Both my suite runs therefore never
touched the operator's real user-data dir. I confirmed this **first**, then ran pytest.

---

## 3. Functional / product-value assessment

### 3.1 Use Case advancement

| Use Case | Pre-sprint status | Post-sprint status | Change | Evidence |
|---|---|---|---|---|
| UC-001 Policy Agent | OPERATIONAL (production posture) | OPERATIONAL (production posture) | `=` (hardened) | Weight-integrity sweep widened to all manifest entries at PA `load_model()` (`gpu_inference.py:~632`, `5b9123b`) |
| UC-004 Assistant Orchestrator | OPERATIONAL (production posture) | OPERATIONAL (production posture) | `=` (hardened) | Same sweep at AO `load_model()` (`gpu_inference.py:~467`, `5b9123b`) |
| UC-002 / UC-005..009 | not built | not built | `=` | — |
| UC-003 Cleaner | removed from roadmap (#613) | removed from roadmap (#613) | `=` | unchanged |

No use case gained a feature; UC-001/004 gained a **stronger integrity gate at model load** (every
manifest entry verified + extra-`.bin` rejection, fail-closed). The coverage audit (F) maps all 9 UCs'
test posture. This is a maturity/hardening step, correctly `=`-with-hardening, not `+`.

### 3.2 Operational capability delta

What the running system does differently today: at model load, **both** services now refuse to start if
*any* manifest entry's digest mismatches, an entry is missing, or an extra `.bin` is present in the model
dir (previously only `openvino_model.bin` was checked). The signed-manifest mechanism is wired and
config-gated but **inert** (`require_signed_manifest=false` shipped) — so no behavioural change to boot
yet, by design. Everything else the sprint shipped is test/automation/doc and does not change runtime
behaviour.

### 3.3 Phase 5 roadmap position

This is **Tier-2/Tier-3 gate-critical hardening + the automation force-multiplier** on the
air-gap-removal campaign toward #598. After Sprint 16: the production-parity lane exists (stubbed tier
green), the GUI harness exists (built + scripted), weight integrity is advanced (PARTIAL — sweep done,
signature staged), deps are pinned, and §5 is a verified tracker. Remaining gate-critical: #615
(guest-boundary AF_HYPERV), Tier-3 egress (mediation + exfil-screen + kill-switch arming), #106 full
closure (the manifest ceremony), the production-mode boot integration test (#619 pt2), and the #598
GO/NO-GO + #612 capstone. The air-gap **stays up**; #598 remains the GO/NO-GO gate — correctly framed by
the SCR as "not the end." This is one wave within a decades-horizon roadmap, not a terminal milestone.

### 3.4 Open issues and ISS tracker status

| Issue | Pre-sprint | Post-sprint | Notes |
|---|---|---|---|
| ISS-1 (AO spec-decode) | RESOLVED | RESOLVED | Not in scope; unaffected |
| ISS-2 (think tags in TUI) | open | open | Not in scope (WinUI fixed separately) |
| ISS-3 (PA classification misses) | open | open | Not in scope |
| #106 / FUT-04 | open (PARTIAL) | open (PARTIAL — advanced) | Sweep landed; signature staged default-OFF; ceremony is the later batched closure |

No new ISS-class defect surfaced this sprint (consistent with a test/automation/hardening wave, not a
live-verify boot marathon). One production-seam *constraint* surfaced (D's `asyncio.run()` nesting) and
was correctly classified not-a-defect (§7).

---

## 4. Success-criteria gap analysis

Per-criterion independent verdict. Evidence cites commit SHA + `file:line` + test names I read/ran.

| # | Criterion (abbrev SDV §4) | SCR verdict | Auditor's independent verdict | Gap |
|---|---|---|---|---|
| 1 | GUI harness extended (A / #621) | MET (built+scripted; runs deferred) | **MET (built+scripted; runs deferred)** | NONE (MINOR-2 count) |
| 2 | Weight integrity — every manifest entry (B1 / #106a) | MET | **MET** | NONE |
| 3 | Signed-manifest mechanism built + STAGED (B2 / #106b) | MET | **MET** | NONE |
| 4 | Manifest-ceremony novice runbook (B2 / D-3) | MET | **MET** | NONE |
| 5 | Dependency pinning (C) | MET | **MET** | NONE (MINOR-2 count) |
| 6 | Production-parity lane pt1 (D / #619) — two locks | MET (i)+(ii-a); (ii-b) built, deferred | **MET (i)+(ii-a); (ii-b) built, deferred** | NONE (MINOR-4 scope) |
| 7 | Tier-1 state reconciliation (E / §2a) | MET | **MET** | NONE (MINOR-3 header) |
| 8 | Coverage audit (F / #622) | MET | **MET** | NONE |
| 9 | No regressions; merge-gate; disjointness | MET | **MET** | NONE |

**9 of 9 MET** (8 deliverable criteria + #9). Two MET-as-scoped items (#1, #6(ii-b)) carry deferred
dev-machine green runs, honestly named as Sprint-17-kickoff prerequisites.

### Criterion #1 — GUI harness extended (A / #621) — MET (built + scripted; runs deferred)

I scrutinised this hardest per the brief (is the BUILT-not-VERIFIED grading honest?). **It is.**
- `aed13ad` adds `tests/harness/test_winui_critical_path.py` (13 scenarios) + `test_winui_model_loaded.py`
  (model-loaded tier). Both carry module-level `pytestmark = [pytest.mark.slow, pytest.mark.winui, ...]`
  (`test_winui_critical_path.py:61-65`; `test_winui_model_loaded.py:61-64` adds `pytest.mark.hardware`).
  Both markers are registered in `pyproject.toml:42-44` under `--strict-markers`, so they cannot be typos.
  The Layer-A selection `-m "not hardware and not winui and not slow"` correctly **deselects** them — I
  confirmed they are NOT in the 2187 count.
- The stub tier is a **real GUI exercise, not a trivial smoke**: it launches the real WinUI exe
  (`subprocess.Popen([str(EXE)])`, `:94`), connects a scripted pipe backend, resolves the window by PID
  (the sprint12 lesson, `:84`), and drives real UI Automation against named controls (`MessagesList`,
  `SessionsList`, `NewChatButton`, `SettingsButton`, `MicButton`, … via `auto_id=`), with real
  visibility/item-count polling helpers (`:157-180`). It `pytest.skip`s if the exe is not built (`:90-91`).
- The XAML carries the AutomationIds the harness targets (`MainWindow.xaml`, `2c4d85e`). **The grading is
  honest** — the harness is real but its first green run needs a built exe + a display, so it is correctly
  graded BUILT + scripted, runs deferred (§5 of the SCR). It does NOT claim a green GUI run.
- **MINOR-2:** the SCR + the merge message say "15 AutomationIds"; the builder commit `2c4d85e` actually
  adds **24** `AutomationProperties.AutomationId` lines (0 pre-existing). An *under*-count, not an
  over-claim (more delivered than stated) — but an inaccurate number on the IAPP-portfolio record.

### Criterion #2 — Weight integrity, every manifest entry (B1 / #106a) — MET

- `shared/models/weight_integrity.py:279` `verify_all_manifest_entries(model_dir, manifest_path)` iterates
  **all** manifest digests (`:321` `for filename, expected in digests.items()`), fail-closed on missing
  (`:323`), tampered (`:355`), IO error (`:340`), AND rejects extra `.bin` files on disk not in the
  manifest (`:387-403`). `ManifestSweepResult.all_verified` is `False` on any failure.
- The sweep is **wired at BOTH call sites** (I read both diffs): PA `gpu_inference.py:~632` and AO
  `gpu_inference.py:~467` both now call `verify_all_manifest_entries(model_dir=…)` and `return False`
  (refuse to load) when `not sweep.all_verified` (`5b9123b`). Guarded by the pre-existing
  `if self._manifest_path is not None`.
- `shared/tests/test_weight_integrity_sweep.py` (289 LOC, 8 tests) — green in the reproduced 2187.
  Lesson 67 captures the "verify every member + reject omissions" principle. **#106 stays PARTIAL** —
  the SCR is explicit; not claimed done anywhere (§5).

### Criterion #3 — Signed-manifest mechanism built + STAGED (B2 / #106b) — MET

- **The signature gate is real and fail-closed.** `shared/models/manifest_signer.py::verify_manifest_signature`
  (`:114-219`): missing `.sig` + `require_signed=False` → `True` with a WARNING (`:146-153`); missing `.sig`
  + `require_signed=True` → `False` FAIL-CLOSED (`:154-159`); `.sig` present but invalid → `False`
  **regardless** of `require_signed` (`:204-212`, the anti-downgrade protection); TPM unavailable when
  required → `False`. `load_manifest_verified` (`weight_integrity.py:130-179`) verifies the signature
  **before** reading content.
- **The cascade wiring is genuinely present in both entrypoints** (I verified the exact cited lines, not
  the SCR's prose): PA `services/policy_agent/src/entrypoint.py:790` and `:862-864` call
  `load_manifest_verified(… require_signed=require_signed_manifest)`; AO
  `services/assistant_orchestrator/src/entrypoint.py:884` does the same. Config-driven, default False
  (PA `:601-602`, AO `:546-547`). This is **NOT a "built-into-nothing" gap** (lesson 61 class). The grep
  also confirms the wiring pre-dated this sprint (present in the Sprint-15 `.worktrees/ea4d` snapshot), so
  B2 correctly scoped its delta to the missing preflight key + locks + runbook — the SCR process-note #6
  ("verified, not assumed") is honest.
- **The 4 mechanism locks exercise the real shared gate with teeth.** `shared/tests/test_manifest_signing_mechanism.py`
  (335 LOC): (a) default-off + unsigned → loads with WARNING, asserts the warning text (`:94-123`); (b)
  required + valid stub-sig → passes, asserts `verify` called exactly once (`:133-167`); (c) required +
  missing `.sig` → `None` fail-closed + a separate no-raise test (`:177-218`); (d) required + valid stub
  → boots clean, PLUS a tampered-after-sign → fail-closed test proving cryptographic binding (`:228-290`),
  PLUS a 6th test confirming `ceremony_preflight` probes `BlarAI-Manifest-Signing` (`:300-335`). The
  test's own docstring honestly notes it tests `load_manifest_verified` directly rather than via
  `entrypoint.start()` — a reasonable scoping, and I independently confirmed the entrypoint wiring.
- **Staged-not-activated CONFIRMED:** no `manifest.json.sig` exists in HEAD (`git show` → `fatal: path …
  does not exist`); the model dir on disk holds only `manifest.json` + `manifest.json.example`. Shipped
  `require_signed_manifest=false` in BOTH `default.toml` (PA `:26`, AO `:81`) — no brick window. Lesson 59
  (build the mechanism + pin the sentinel before flipping) is the pattern, correctly applied.

### Criterion #4 — Manifest-ceremony novice runbook (B2 / D-3) — MET

- `docs/runbooks/manifest_signing_ceremony.md` (194 LOC) present. Opens "For the Lead Architect
  (non-developer-friendly)", "Stakes right now: very low" — the EA4 standard. `provision_manifest_signing_key.py`
  (the ceremony script) is present and is the "run ONCE on the deployment host" entry point. The runbook is
  Orchestrator-drivable line-by-line. The D-3 NON-OPTIONAL constraint is satisfied.

### Criterion #5 — Dependency pinning (C) — MET

- `7994639` adds upper bounds to security-critical deps across **5** service `pyproject.toml` (AO, PA,
  semantic_router, ui_gateway, ui_shell). **I verified every pin against the installed version:**
  cryptography 46.0.5 ∈ `>=46,<47`; PyJWT 2.11.0 ∈ `>=2.8,<3`; openvino 2026.1.0 ∈ `>=2026.1,<2027`;
  numpy 2.4.3 ∈ `>=2.0,<3`; pydantic 2.12.5 ∈ `>=2.5,<3`; onnxruntime 1.24.2 ∈ `>=1.16,<2`; textual
  8.0.0 ∈ `>=0.89,<9`. **No pin contradicts any installed version**; the floor-raises (openvino
  2024→2026.1, crypto 41→46) reflect the actual deployed toolchain. The Layer-A suite is green at 2187 —
  **no pin broke anything**.
- The hash-pinning gap is **honestly named** (carry-over: "version-containment, not supply-chain
  integrity"; lesson 71; `uv lock`/`pip-compile --generate-hashes` is the named next step).
- **MINOR-2 (count):** the SCR/SDV say "across the 6 `pyproject.toml`" but C changed **5** — the root
  `pyproject.toml` was already pinned in Sprint 14 (`c824f6a`, `cryptography>=46,<47`). Defensible framing
  (all 6 are now pinned), but the *this-sprint diff* is 5 files. Folded with the AutomationId count.

### Criterion #6 — Production-parity lane pt1 (D / #619) — MET (i)+(ii-a); (ii-b) built, deferred

I scrutinised the BUILT-not-VERIFIED grading and read the test bodies.
- **(i) key-transition tests are real, at the seam.** `tests/integration/test_key_transition_integration.py`
  (379 LOC, 9 tests) constructs the **REAL** `EncryptedSessionStore` and `EncryptedSubstrateStore` across
  a dev→prod cipher rotation — both stores, serves-not-bricks, quarantine logged
  (`SESSION_ROW_DECRYPT_QUARANTINE` / `SUBSTRATE_ROW_DECRYPT_QUARANTINE` asserted), AND the leaf-decrypt
  fail-closed invariant preserved (`test_fail_closed_without_fallback_to_plaintext:251`
  `pytest.raises(RuntimeError, match="refusing to return plaintext")`). These assert at the real seam, not
  a mock (lesson 63/64 class). All 9 RAN green in my reproduced lane (not silently deselected).
- **(ii-a) the stubbed boot-cascade tier is a real cascade exercise, NOT a trivial smoke.**
  `tests/integration/test_boot_cascade_smoke.py` `TestBootCascadeSmoke` (8 tests, all RAN green) exercises:
  REAL `provision_per_boot_certs()` (asserts 5 cert files + PEM markers, `:215-242`); REAL
  `build_session_store()` write/read (`:293-309`); REAL `AssistantOrchestratorService.start()/.stop()`
  lifecycle (`:311-355`); REAL `TransportGateway.check_pa_status()` against the REAL AO listener asserting
  `StartupState.OPERATIONAL` (`:357-410`); the central lock — REAL `_run_uat2_prompt_flow_preflight()`
  through the real send_prompt→AO→PGOV→session path (`:412-503`); the `resolve_gateway_port` invariant
  (port == AO, NOT PA — the Sprint-15 misroute lock, `:275-291`); and teardown releasing the port
  (`:505-547`). The **ONLY** stubbed component is `OrchestratorGPUInference` (the model load) — exactly as
  the SCR claims.
- **(ii-b) the real-GPU tier is correctly deferred + honestly graded.** `TestBootCascadeSmokeRealModel.
  test_real_model_cascade_to_preflight_passing` is `@pytest.mark.hardware` (`:584`) — Layer-A deselects it.
  It boots the cascade with the real Qwen3-14B. The SCR grades it BUILT + scripted, run deferred — it does
  **NOT** claim a green real-GPU run. Lesson 68 ("a lock you cannot run green yet must verify everything
  the missing resource does not gate") is the discipline, correctly applied.
- **#619 lane reproduced exactly: 18 passed, 0 failed** (17 D-tests + 1 pre-existing `test_pdf_load_e2e`).
- **MINOR-4 (scope-of-the-lock):** these tests are in `tests/integration/`, which the canonical Layer-A
  command excludes — so a green Layer-A run says nothing about the lane. The SCR names this (lesson 70 +
  carry-over). See §10.3 — this is the Sprint-15 §2.7-enforcement pattern paid-down-and-relocated, the one
  real residual the LA must action.

### Criterion #7 — Tier-1 state reconciliation (E / §2a) — MET

- `7c7db3d` rewrites `SECURITY_ROADMAP_air_gap_removal.md` §5 as a verified tracker with file:line
  evidence. **I spot-checked 2 DONE re-grades against the cited code:** (a) the armed runtime egress guard
  — `egress_guard.arm()` IS called at `launcher/__main__.py:1133` in the `if __name__ == "__main__"` block
  (the §5.2 claim of `:1131-1133`); (b) the hash-chained TPM-signed audit stream — `audit_log.py:65`
  `AUDIT_TPM_KEY_NAME = "BlarAI-Audit-Signing-Key-v1"`, `AuditProvisioningError` (`:77`) "must refuse to
  start" (`:82`). Both DONE grades are accurate.
- The §5 counts (DONE 7 / PARTIAL 1 / REMAINING 9 / NOT-GATE 1) are internally consistent with the
  per-criterion table; weight integrity is correctly PARTIAL (#106); the open LA decisions (PII posture,
  measured-boot PCR-attestation scope, audit retention) are flagged not smoothed. The TPM key state table
  records 3-provisioned / 1-unprovisioned (`BlarAI-Manifest-Signing`). Lesson 69 captures the "a tracker
  never re-verified drifts both ways" principle. E correctly surfaced a forward gate-scoping question
  (PCR attestation) rather than resolving it unilaterally.
- **MINOR-3:** the §5 header (`:118`) + §0/§2/§4 still read "#787 GO/NO-GO" — a pre-existing conceptual
  placeholder from the Sprint-12 SDV. Line 275 already documents the mapping ("gate ticket: Vikunja #598
  — the roadmap's conceptual '#787'"), so #787 is a **stale conceptual reference, not a real sub-ticket**.
  E rewrote §5's *criteria* but left the legacy *header* name. The SCR honestly flags it as a carry-over.

### Criterion #8 — Coverage audit (F / #622) — MET

- `45746ef` adds `docs/sprints/sprint_16/coverage_audit.md` (154 LOC). 15 subsystems mapped (14/15 unit,
  7/15 real-integrated-path, 2/15 e2e) → 14 prioritized gaps (7 HIGH) cross-referenced to
  #619/#621/#615/#106 → Sprint 17/18 burn-down. The **as-of honesty is correct**: it states "Audit scope:
  `main` at HEAD `82a21e5`, BEFORE the Sprint-16 code builders merge" (`:4`) and marks the gaps the wave
  closes as "closing in Sprint 16 (stream X)" rather than "open" (`:6` + every HIGH row) — it neither
  claims the gaps still open nor already-closed; it marks them in-flight. Honest, fit-for-purpose.

### Criterion #9 — No regressions; merge-gate held; disjointness — MET

- **Layer-A reproduced exactly: 2187 passed, 2 skipped, 15 deselected, 0 failed (86.23s, exit 0)** —
  matches the SCR. Arc 2172 → 2187 (+8 B1, +7 B2; C/D/A add 0 to Layer-A as their tests are
  `tests/integration` / `winui`-marked). The 1 snapshot test passed (collection integrity). 2 warnings are
  the benign SWIG `DeprecationWarning`s; 2 skips are the permanent Qwen3 thinking-suppression skips.
- **Disjointness held end-to-end** — I inspected all 7 merge diffs (§7): no two streams touch the same
  file. The two coordination assignments held (D added no fixtures to `tests/harness/`, putting its
  doubles inline; A owned `test_winui_*`).
- **Branch-guard / merge-gate:** all 7 stream branches merged `--no-ff`; HEAD is `main` at `560b6ad`. The
  "never trust the summary" rule is independently validated — I reproduced the exact 4 collection errors
  (§8.2) the SCR says a builder over-stated at 41.

---

## 5. Scope integrity analysis

### 5.1 Promised deliverables — completion audit

| # | Deliverable (SDV §6) | SCR status | Auditor finding | Commit | Gap |
|---|---|---|---|---|---|
| 1 | Extended Layer-C GUI scenarios + AutomationIds + model-loaded tier + runbook | MET | **CONFIRMED (built+scripted)** | `aed13ad` | NONE (MINOR-2) |
| 2 | Multi-entry weight-verify at load (PA+AO) + test | MET | **CONFIRMED** | `5b9123b` | NONE |
| 3 | Signed-manifest mechanism wired + staged + 4 locks | MET | **CONFIRMED** | `66f6b61` | NONE |
| 4 | Manifest-ceremony novice runbook | MET | **CONFIRMED** | `66f6b61` | NONE |
| 5 | Dependency pins + rationale | MET | **CONFIRMED (5 files; 6th pre-pinned)** | `7994639` | NONE (MINOR-2) |
| 6 | Key-transition + sealer-stand-in integration tests + boot-smoke | MET | **CONFIRMED (i+ii-a; ii-b deferred)** | `469a442` | NONE (MINOR-4) |
| 7 | Verified §5 gate-tracker | MET | **CONFIRMED** | `7c7db3d` | NONE (MINOR-3) |
| 8 | Coverage gap-list | MET | **CONFIRMED** | `45746ef` | NONE |

All 8 in-scope deliverables landed on `main` and are independently confirmed.

### 5.2 Deferred items — integrity check

The §5.2/§5.3 out-of-scope items are honored, not silently pulled in:

- **On-chip manifest ceremony EXECUTION + the flip to `require_signed=true`:** DEFERRED. Confirmed no
  `.sig` in HEAD; `require_signed_manifest=false` shipped in both configs. **Honored** (built + staged +
  runbooked, not run).
- **#615 guest-boundary (AF_HYPERV):** NOT touched. The privacy scan and merge-diff review found no
  AF_HYPERV implementation change in the window. **Honored** (Sprint 17).
- **Tier-3 egress / kill-switch arming:** NOT touched (the egress guard is pre-existing/armed from Sprint
  15; no new egress mediation). **Honored** (Sprint 17).
- **The FULL production-mode boot integration test (#619 pt2):** NOT built — only the lightweight
  smoke-to-preflight lock on the current cascade. **Honored** (the SCR scopes #6 exactly to the
  lightweight smoke; pt2 is Sprint 17).
- **No new runtime dependency:** confirmed — C *pins* existing deps, adds none (the 5 diffs only add
  bounds). **Honored.**

### 5.3 Unplanned additions

| Item | SCR justification | Auditor agreement | Notes |
|---|---|---|---|
| Stream B split B→B1/B2 | LA-approved split of the heaviest stream | **AGREE** | Disjoint (B1 = `weight_integrity.py`+`gpu_inference.py`; B2 = `ceremony_preflight.py`+runbook); both in the SDV's B working-set; recorded in the SCR frontmatter |
| `ManifestSweepResult` dataclass + `verify_all_manifest_entries` (new public API) | needed for the multi-entry sweep | **AGREE** | In scope for criterion #2; tested (8 tests) |

No unplanned addition is a capability/posture *decision*. The B1/B2 split is an execution-shape change
the SDV v2 anticipated (the SDV's §11 lists "Builder subagents (A–D)"; the split is additive). None
required LA escalation.

### 5.4 Ghost commits — independent discovery

I read the 18-commit window `82a21e5..560b6ad` independently. **Every non-merge commit maps to an SDV
stream, a journal fragment, the journal fold, or the SCR.** No undocumented scope drift.

| Commit(s) | Classification | Requires LA attention? |
|---|---|---|
| `59fa496` (B1), `046b5fc` (B2), `639c9b0` (C), `2df25d8` (D), `2c4d85e` (A), `2800d53` (E), `0adbf93` (F) | TRIVIAL (documented stream scope) | NO |
| `07344a6` (E), `0efb9a1` (C) — "resolve self-reference SHA" | TRIVIAL (the allowed `<this>` self-ref carveout, resolved pre-fold) | NO |
| `1a7b92c` (journal fold) | TRIVIAL (doc; expected per journal discipline) | NO |
| `560b6ad` (SCR) | TRIVIAL (the close artifact) | NO |
| 7 `--no-ff` merges | TRIVIAL (the stream merges) | NO |

No commit represents undocumented scope drift.

### 5.5 Cross-repo ghost-commit sweep

**N/A — single-repo sprint.** All 7 streams wrote only to BlarAI `main`. The `.worktrees/` directories
(`ea4d-fidelity2-transport`, `ea4e-orch-cert-mint`) are pre-existing Sprint-15 EA worktrees on disk; they
are NOT in any `main`-tree diff (the merges show only canonical paths) and contribute to the stale-worktree
carry-over the SCR §7 flags. They did not affect the audit.

---

## 6. Deliverable artifact fitness-for-purpose

| Deliverable | On main? | Matches SDV intent? | Fitness | Evidence |
|---|---|---|---|---|
| `verify_all_manifest_entries` + sweep wiring (PA+AO) | YES | YES | Real, fail-closed, all-entries + extra-`.bin` rejection; wired at both `load_model()` | `5b9123b`; `weight_integrity.py:279`; 8 tests |
| Signed-manifest mechanism (gate + preflight key + locks) | YES | YES | Fail-closed signature gate; anti-downgrade; staged default-OFF; 6 locks exercise the real fn | `66f6b61`; `manifest_signer.py:114`; `test_manifest_signing_mechanism.py` |
| Manifest-ceremony novice runbook | YES | YES | EA4 standard, non-dev framing, Orchestrator-drivable | `66f6b61`; `manifest_signing_ceremony.md` |
| Dependency pins + rationale | YES | YES | All 7 listed pins validated vs installed; suite green; hash-gap named | `7994639`; `dependency_pinning_rationale.md` |
| Key-transition integration tests | YES | YES | Real stores, both, serves-not-bricks, leaf fail-closed preserved | `469a442`; `test_key_transition_integration.py` (9 tests) |
| Boot-cascade smoke (stubbed + real-GPU) | YES | YES | Stubbed tier real cascade exercise (8 tests green); real-GPU tier `hardware`-marked, deferred | `469a442`; `test_boot_cascade_smoke.py` |
| WinUI critical-path harness + AutomationIds + model tier | YES | YES (built+scripted) | Real pywinauto harness (13 scenarios); 24 AutomationIds; model tier defined; runbook | `aed13ad`; `test_winui_critical_path.py` |
| Verified §5 gate-tracker | YES | YES | DONE re-grades spot-verified accurate; open decisions flagged | `7c7db3d`; SECURITY_ROADMAP §5 |
| Coverage gap-list | YES | YES | 15 subsystems → 14 gaps; as-of honesty correct | `45746ef`; `coverage_audit.md` |
| SCR | YES | YES | Accurate; reproduced numbers match exactly; honest deferred-run + PARTIAL framing | `560b6ad` |
| BUILD_JOURNAL fold (lessons 67-71) | YES | YES | Genuine distilled lessons; arc entry; fragments deleted | `1a7b92c` |

All deliverables are on `main`, fit-for-purpose, and match SDV intent. No "built into nothing" gap found
(I specifically checked criterion #3's wiring — it is real and config-driven at both entrypoints).

---

## 7. EA / stream lineage and merge-gate rigor

| Stream | Working-set (per merge diff) | Scope respected? | Cross-stream collision? |
|---|---|---|---|
| E (§2a) | `SECURITY_ROADMAP` §5 + fragment | YES (read-mostly) | NONE |
| F (#622) | `coverage_audit.md` + fragment | YES (read-mostly) | NONE |
| B1 (#106a) | `weight_integrity.py`, both `gpu_inference.py`, `test_weight_integrity_sweep.py` + fragment | YES | NONE |
| B2 (#106b) | `ceremony_preflight.py`, runbook, `test_manifest_signing_mechanism.py` + fragment | YES | NONE |
| C (Tier-3) | 5 service `pyproject.toml`, rationale + fragment | YES | NONE |
| D (#619) | `test_boot_cascade_smoke.py`, `test_key_transition_integration.py` + fragment | YES | NONE |
| A (#621) | `MainWindow.xaml`, `test_winui_critical_path.py`, `test_winui_model_loaded.py`, runbook + fragment | YES | NONE |

**Disjointness held end-to-end** — independently confirmed by inspecting all 7 merge `--stat` diffs: no
file appears in two streams. The dispatch order the SCR claims (E+F first, B1/B2/C/D concurrent, A after
D) is consistent with the merge SHAs in window order. B1/B2 are genuinely disjoint despite both being
"Stream B" (B1 = models/services inference; B2 = security preflight + runbook).

**Merge-gate rigor.** All 7 merges are `--no-ff`; each merge message records a diff-review against its
criterion + a test re-run. The "never trust the summary" discipline is **independently validated**: the
SCR claims a builder reported "41 collection errors" and the Orchestrator's `--collect-only` showed 4 —
I ran `--collect-only` myself and got **exactly 4**, all in `tools/tests/` (§8.2). The branch-guard
(`branch==main` + toplevel) held — HEAD is `main` at `560b6ad`, no feature branch leaked onto the main
tree.

**Production-seam constraint, correctly classified not-a-defect.** D documented that
`_run_uat2_prompt_flow_preflight()` calls `asyncio.run()` internally (the launcher's synchronous bridge),
so it cannot be called from inside an async test loop; D worked around it (a sync test + a fresh event
loop, `test_boot_cascade_smoke.py:432-503`) and documented the constraint in the docstring. This is
by-design in the production launcher (called from synchronous `main()`), not a defect — no production fix
required. I agree with the classification.

---

## 8. Test coverage and quality assessment

### 8.1 Baseline — independently reproduced

| Metric | Before sprint | After sprint | Delta | SCR claimed |
|---|---|---|---|---|
| Layer-A (passed / skipped / deselected) | 2172 / 2 / 15 | **2187 / 2 / 15** | **+15** | 2187 / 2 / 15 ✓ |
| Layer-A failures | 0 | **0** | = | 0 ✓ |
| #619 lane (`tests/integration`, non-slow) | (lane partly pre-existing) | **18 passed / 88 deselected / 0 failed** | +17 (D) | 18 / 0 ✓ |

**Commands (exactly as specified):**
- `.venv/Scripts/python.exe -m pytest shared/ services/ launcher/ -m "not hardware and not winui and not slow" -q -p no:cacheprovider` → **`2187 passed, 2 skipped, 15 deselected, 2 warnings in 86.23s`, exit 0.**
- `.venv/Scripts/python.exe -m pytest tests/integration/ -m "not hardware and not winui and not slow" -q -p no:cacheprovider` → **`18 passed, 88 deselected, 2 warnings in 6.58s`, exit 0.**

Both match the SCR **exactly**. In the integration lane, the 8 boot-cascade-stubbed + 9 key-transition
tests **RAN** (not silently deselected) — confirmed by the per-file dots in the output
(`test_boot_cascade_smoke.py ........` / `test_key_transition_integration.py .........`).

### 8.2 Collection errors — independently characterized

`pytest --collect-only` (full discovery) → **exactly 4 errors, all in `tools/tests/`**:
`test_project_context.py`, `test_v_matrix_v6_mcp_project_id.py`, `test_v_matrix_v7_cross_project_byte_identity.py`,
`test_vikunja_client_scope.py` — all `ModuleNotFoundError` (`tools._vikunja_client` / `tools._project_context`).
Pre-existing, outside BlarAI runtime + the canonical scope (the wave never touched `tools/`). The SCR's
claim (4, confined to `tools/tests/`) is **exact**. Recommend a tracking ticket (MINOR-5).

### 8.3 Test quality (not just quantity)

The new tests assert on **behaviour at the seam**, not existence:
- The key-transition tests construct the REAL encrypted stores across a cipher rotation and assert
  serves-not-bricks + the leaf fail-closed invariant (`pytest.raises(… "refusing to return plaintext")`).
- The boot-cascade stubbed tier exercises real cert mint, real service start/stop, the real gateway
  handshake (asserting `StartupState.OPERATIONAL`), and the real prompt-flow preflight — only the model
  load is stubbed.
- The manifest mechanism locks exercise the real `load_manifest_verified`, including a tampered-after-sign
  cryptographic-binding test, not assertion-free smoke.
- **No assignment-in-place-of-assertion pattern observed** in any file I read.

### 8.4 Privacy + GPU-only regression scan

`git diff 82a21e5..560b6ad -- shared/ services/ launcher/`:
- **No added external-network imports** (`requests`/`urllib`/`httpx`/`aiohttp`/`socket.create_connection`
  to a non-loopback host) — scan returned NONE. Privacy mandate holds.
- **No NPU revival** — the only `N…` match was a false positive (`AutomationProperties.Name="Message
  input"` in the XAML). No `device=…NPU…` strings added. ADR-011 holds.

### 8.5 TEST_GOVERNANCE.md compliance

- The integration tests landed in `tests/integration/` (correct §6 boundary placement).
- **MINOR-4 (the one substantive test-governance residual):** the new lane is in `tests/integration/`,
  included in `testpaths` (`pyproject.toml:32`) so it runs in bare-`pytest`/REGRESSION discovery, but the
  *canonical Layer-A baseline command* (`shared/ services/ launcher/`) excludes it — so a green Layer-A run
  proves nothing about the lane. The key-transition + boot-cascade-stubbed tests carry **no** module-level
  `slow`/`hardware` mark, so they DO run in bare `pytest tests/integration` — but the standing gate the
  project quotes does not cover them. The SCR names this (lesson 70) and recommends folding
  `tests/integration` (non-slow) into the standing gate scope. **This is a real LA action** (§12), not a
  defect — the lock exists and runs, but its scope-vs-the-gate reconciliation is required for the
  lock-before-modify guarantee to be structural.
- The §1 named-scope baseline rows (UNIT 755 / FOCUSED 791 / FULL 835) remain stale vs Layer-A 2187 — but
  this is the *same* MINOR the Sprint-15 SWAGR (MINOR-5) already flagged and TEST_GOVERNANCE §1's own
  warning box already annotates (updated 2026-06-07). Not a new Sprint-16 finding; not re-counted here.

---

## 9. Architecture and governance completeness

### 9.1 ADR / DECISION_REGISTER alignment

- **No new runtime ADR or DEC was authored** — consistent with SDV §10 ("no new ADR required; the
  manifest-signing decision is a *scoping* ratification recorded here + on #624"). I confirmed
  `DECISION_REGISTER.md` has **no** Sprint-16 / manifest-signing / #624 entry — the maintenance rule was
  not triggered (no runtime trust/security ADR or DEC was created). Correct.
- ADRs respected: ADR-011 (GPU-only — no NPU revival, §8.4); ADR-018 (TPM trust root — the manifest key
  is the 4th TPM key, staged); ADR-020 (egress kill-switch — armed from Sprint 15, untouched);
  ADR-025/026 (at-rest + per-boot mTLS — the lane tests the key-transition path these created). No ADR
  drift introduced.

### 9.2 Ledger completeness

- **Sprint-16 ledger entry: ABSENT.** `docs/ledger/` ends at
  `20260607_094439_sprint15_scr_production-posture-flip.md`; no Sprint-16 entry exists. This is **benign
  SWAGR-before-close sequencing** (identical to Sprint-14 SWAGR MINOR-2 and Sprint-15 SWAGR MINOR-2):
  the SWAGR runs *before* the Orchestrator's final close commit, and SCR §9 "Post-SWAGR reconciliation"
  is explicitly pending. Per CLAUDE.md DEC-17, the entry must land in `docs/ledger/` per-file at the
  close. Recorded as MINOR-1 so it is not dropped.
- **Positive cross-sprint signal:** the Sprint-15 ledger entry (which the Sprint-15 SWAGR flagged as
  absent) NOW EXISTS — the Sprint-15 close-action discipline held. This raises confidence the Sprint-16
  ledger entry will land at close.

### 9.3 Journal completeness

- **Complete.** The 7 fragments were folded into `BUILD_JOURNAL.md` (`1a7b92c`); the arc entry
  "2026-06-07 — The Automation Wave" is present (line 2205) and lessons **67-71** are added (lines
  145-153), each a genuine distilled portfolio lesson tied to a criterion (67 → #2; 68 → #1/#6(ii-b);
  69 → #7; 70 → #6/the lane-scope residual; 71 → #5). The `docs/journal_fragments/` dir holds only
  README — fragments correctly deleted. Journal discipline is fully satisfied.

### 9.4 Nomenclature / doc currency

- **MINOR-3 (SECURITY_ROADMAP #787 header):** §5 header + §0/§2/§4 still read "#787 GO/NO-GO"; line 275
  documents #787≡#598. Pre-existing conceptual placeholder; E rewrote the criteria but not the header.
  Honestly flagged by the SCR as a carry-over.
- The gateway `check_pa_status`/`_attempt_pa_handshake` stale-naming (now handshakes the AO) remains
  ticketed at **#623** (deliberately deferred per the SCR; the boot-cascade smoke even uses
  `check_pa_status()` against the AO, exercising the misnamed-but-correct method). Correctly deferred.
- No NPU-in-production naming drift; service names + path conventions consistent.

### 9.5 Documentation currency

| Document | Accurate? | Stale section |
|---|---|---|
| SDV v2 | YES | — |
| SCR v1 | YES (reproduced numbers match exactly) | AutomationId count "15" vs 24 (MINOR-2); "6 pyproject" vs 5-changed (MINOR-2) |
| coverage_audit.md | YES (as-of honest) | — |
| SECURITY_ROADMAP §5 | YES (criteria) | "#787" header (MINOR-3) |
| TEST_GOVERNANCE.md | YES (§2.7 current; §1 already annotated stale) | §1 named-scope rows (pre-existing, Sprint-15 MINOR-5) |
| CLAUDE.md "Active State" | STALE (expected) | describes Sprint 15 as the close; HEAD advanced to 16. The known "HEAD-pinning goes stale" pattern; recorded as a close-sweep item, not a Sprint-16 defect |

---

## 10. Risks and carry-overs — hindsight analysis

### 10.1 SDV §9.1 known risks — actualization audit

| Risk (SDV) | Actualized? | Mitigation effective? | SCR honest? |
|---|---|---|---|
| Staged `require_signed_manifest` bricks boot before ceremony | NO | YES | YES — default stayed false; no `.sig`; lesson 59 |
| 6-way parallel worktrees worsen cwd-branch hazard | NO | YES | YES — branch-guard held; HEAD==main |
| "CI" over-claimed (cloud pipeline that can't run GPU) | NO | YES | YES — claims scoped to local suite + dev-machine run throughout |
| Multi-file weight sweep surfaces weights not in manifest | NO (resolved as design: extra-`.bin` rejection) | YES | YES |
| Coordination race (A↔D fixtures) | NO | YES | YES — D added no fixtures; A owned `test_winui_*` |

No headline risk actualized into a defect. The one risk-class that *partly* materialized is the lane's
own §9.3 "unknown-unknowns" posture: the lane was built to surface seams — and it surfaced the
scope-of-the-lock truth (the `tests/integration` Layer-A exclusion), correctly classified as a
carry-over, not a defect.

### 10.2 SDV §9.2 known unknowns — resolution audit

1. **Exact `.bin` set vs manifest** — RESOLVED by design (the sweep + extra-`.bin` rejection handles any
   set; the manifest is the source of truth).
2. **Which GUI scenarios need new AutomationIds** — RESOLVED (24 added; `x:Name`→AutomationId where
   already resolvable).
3. **Dependency pins surface a transitive conflict** — RESOLVED (suite green at 2187; no conflict).

### 10.3 Cross-sprint pattern — did Sprint 16 pay down the Sprint-15 §2.7 enforcement gap?

**The Sprint-15 SWAGR flagged (MEDIUM): "the §2.7 'test the seam' mandate has near-zero CI enforcement."**
Sprint 16's answer is **a real partial pay-down that is honestly named as relocated-not-closed**:
- **Paid down:** the production-parity lane now EXISTS (8 boot-cascade-stubbed + 9 key-transition real-seam
  tests, all green), moving from "one #620 round-trip test" to a real boot-cascade + key-transition lane.
  The GUI harness is built. This is a genuine down-payment on the named debt.
- **Relocated, not closed:** the lane lives in `tests/integration/`, which the canonical Layer-A gate
  (the count the project quotes) excludes — so the *structural* enforcement (prod-only bugs hitting the
  standing gate, not the LA's terminal) is **not yet in the canonical gate**. It runs in bare-pytest /
  REGRESSION, but the lock-before-modify guarantee for Sprint 17 depends on someone running a
  `tests/`-inclusive scope. The SCR names this (lesson 70 + carry-over: "the Sprint-17 cascade gate MUST
  run a `tests/`-inclusive scope"). This is the right shape (named + ticketed, not hidden), but it is the
  one residual the LA must action (ratify the gate-scope fold) for the pattern to be truly closed rather
  than relocated. **The pattern recurred in a milder, honestly-surfaced form** — better than Sprint 15
  (where it was deferred entirely), not yet fully closed.

### 10.4 Carry-over items (consolidated from SCR §5 + my audit)

| Carry-over | Severity | Note |
|---|---|---|
| D real-GPU boot-smoke + A GUI green runs | (deferred work) | Sprint-17-kickoff prerequisites BEFORE the first #615/egress edit; community-grade perf capture required when they run |
| Fold `tests/integration` (non-slow) into the standing gate scope | MINOR-4 | The lock-before-modify guarantee is structural only if the cascade gate includes the lane's scope (lesson 70) |
| #106 / FUT-04 full closure (manifest ceremony + flip) | (deferred work) | PARTIAL; the on-chip `BlarAI-Manifest-Signing` ceremony, runbooked, a later batched LA session |
| Dependency hash-pinning (lock file) | (deferred work) | `uv lock`/`pip-compile --generate-hashes`; lesson 71; Sprint-17 candidate |
| 4 pre-existing `tools/tests/` collection errors | MINOR-5 | Tracking ticket recommended (per the non-optional-followups rule) |
| SECURITY_ROADMAP "#787" header reconcile | MINOR-3 | Stale conceptual ref; #787≡#598 already documented at line 275 |
| Measured-boot PCR-attestation scope | (forward LA decision) | E surfaced it; queue alongside egress-policy + audit-retention #607 |
| Stale worktree + branch inventory | (LA, post-wave) | \~33 worktrees + 217 branches; inventory only — no destructive git |

---

## 11. Recommendations for next sprint

1. **(LA)** **Ratify folding `tests/integration` (non-slow) into the standing gate scope** (MINOR-4 /
   §10.3) — the single most important forward action. The production-parity lane is real but the canonical
   gate doesn't see it; the lock-before-modify guarantee for Sprint 17's #615/egress edits holds only if
   the cascade gate runs a `tests/`-inclusive scope. This finally closes the Sprint-15 §2.7-enforcement
   pattern instead of relocating it.
2. **(LA)** **Run the deferred dev-machine green runs at the Sprint-17 kickoff, BEFORE the first
   #615/egress edit** — D's real-GPU boot-smoke + A's GUI tiers. A lock that has never gone green locks
   nothing; capture the boot/model-load timings to `PERFORMANCE_LOG.md` + `docs/performance/` (the
   community-grade data rule).
3. **(BOTH)** **Fix the SCR AutomationId/pyproject count imprecision (MINOR-2)** at the close — the SCR
   says "15 AutomationIds" (actual 24) and "6 pyproject" (5 changed; 6th pre-pinned). Small, but the
   IAPP-portfolio surface holds the strictest accuracy bar (mirrors the Sprint-15 ADR-026 cert-count
   drift fix).
4. **(LA/Orchestrator)** **Author the Sprint-16 ledger close entry (MINOR-1)** in `docs/ledger/` per-file
   (DEC-17) at the close, folding this SWAGR's verdict + the carry-overs.
5. **(LA)** **Open a tracking ticket for the 4 `tools/tests/` collection errors (MINOR-5)** — pre-existing,
   outside BlarAI runtime, but the non-optional-followups rule wants it ticketed, not left.
6. **(LA)** **Reconcile the SECURITY_ROADMAP "#787" header to #598 (MINOR-3)** in the close-sweep — line
   275 already documents the mapping; the header just lags.
7. **(LA)** **Keep #615 + Tier-3 egress + #106 closure as named #598 gate obligations** in the Sprint-17
   SDV — they are the remaining gate-critical work; the air-gap cannot come down on this wave alone.

---

## 12. LA action items

### 12.1 Product / PM actions

- **Ratify the gate-scope fold (rec 1):** a roadmap-priority call only the LA can make — it converts the
  production-parity lane from "exists but the gate ignores it" to "the standing gate enforces it." This is
  the structural fix the Sprint-15 SWAGR asked for and Sprint 16 set up.
- **Schedule the Sprint-17 kickoff dev-machine session (rec 2):** the deferred green runs are
  prerequisites, not agenda items.

### 12.2 Technical / LA actions

- **Approve the SCR count corrections (rec 3)** — AutomationId 15→24, pyproject 6→5-changed.
- **Run the batched manifest ceremony when prepared** — `manifest_signing_ceremony.md` is runbooked;
  #106 closes when `require_signed_manifest=true` is active on-chip (a later batched session, not Sprint
  16).

### 12.3 Process / fleet health actions

- **Direct the close actions:** author the Sprint-16 `docs/ledger/` entry (MINOR-1); open the
  `tools/tests/` tracking ticket (MINOR-5); reconcile the SECURITY_ROADMAP "#787" header (MINOR-3);
  refresh CLAUDE.md Active-State to the Sprint-16 close at the next doctrine sweep. None blocks the
  sprint; all are tracked here so none is dropped.

---

## 13. Consolidated gap inventory

| # | Section | Gap description | Severity | Evidence | Recommended action |
|---|---|---|---|---|---|
| 1 | §9.2 | **No Sprint-16 ledger close entry** in `docs/ledger/` (ends at the Sprint-15 entry). Benign SWAGR-before-close sequencing (mirrors S14/S15); DEC-17 requires the per-file entry | MINOR | `docs/ledger/` newest = `20260607_094439_sprint15_…`; SCR §9 "Post-SWAGR reconciliation (pending)" | Author the Sprint-16 close entry at the close (fold this SWAGR's verdict + carry-overs) |
| 2 | §4#1/§4#5 | **SCR count imprecision (honesty-of-record):** "15 AutomationIds" (builder `2c4d85e` adds **24**, 0 pre-existing); "6 `pyproject.toml`" (C changed **5**; the root was pre-pinned in S14 `c824f6a`) | MINOR | `git show 2c4d85e -- MainWindow.xaml` → 24; `git diff … -- pyproject.toml` → no change | Correct both numbers in the SCR at the close (IAPP-portfolio accuracy) |
| 3 | §9.4 | **SECURITY_ROADMAP §5 header + §0/§2/§4 read "#787 GO/NO-GO"** — a stale conceptual placeholder; line 275 documents #787≡#598. E rewrote the criteria but not the header | MINOR | `SECURITY_ROADMAP §5:118` "#787"; `:275` mapping; SCR §5 already flags | Reconcile the header to #598 in the close-sweep |
| 4 | §8.5/§10.3 | **Production-parity lane is in `tests/integration/`, excluded from the canonical Layer-A gate** — a green Layer-A run says nothing about the lane; the lock-before-modify guarantee needs a `tests/`-inclusive Sprint-17 gate. The Sprint-15 §2.7-enforcement pattern paid-down-and-relocated, not closed | MINOR | `pyproject.toml:32` testpaths; key-transition/boot-cascade have no module `slow` mark; SCR lesson 70 + carry-over | LA ratify folding `tests/integration` (non-slow) into the standing gate scope (rec 1) |
| 5 | §8.2 | **4 pre-existing `tools/tests/` collection errors** (`tools._vikunja_client`/`tools._project_context` import failures). Outside BlarAI runtime + the canonical scope; the wave never touched `tools/` | MINOR | `pytest --collect-only` → 4 errors, all `tools/tests/`; SCR §5 already flags | Open a tracking ticket (non-optional-followups rule) |

**Totals: Critical 0 · Major 0 · Minor 5.**

All five MINORs are doc-currency / honesty-of-record / a relocated-not-closed structural gap. **None
compromises the substance the sprint delivered** — which is real, tested, and independently reproduced.
MINOR-1 is the normal SWAGR-before-close residual. MINOR-2 is the one genuinely-new honesty finding the
SCR did not surface (the AutomationId/pyproject counts). MINOR-3/4/5 the SCR already named as carry-overs;
I record them here with my own severity so none is dropped. **MINOR-4 is the highest-value forward action**
(the gate-scope fold) — it is the structural completion of the testing-debt arc Sprint 15 named.

---

## 14. System maturity trajectory

### 14.1 Capability / reliability trajectory

Trending **up on verification maturity**, flat on capability (by design). The system gained: a real
boot-cascade + key-transition automated lane (the exact seam class that burned the LA at a terminal in
Sprint 15), a real GUI harness, a widened weight-integrity gate (all manifest entries, fail-closed), and
a verified §5 gate-tracker. +15 Layer-A tests (2172→2187), +17 integration-lane tests, zero regressions,
zero fail-closed weakenings, no privacy/NPU regressions. The counter-signal: the highest-value new
coverage (the production-parity lane) sits outside the canonical gate the project quotes — so its
*enforcement* maturity lags its *existence* until the gate-scope fold (MINOR-4).

### 14.2 Technical debt accumulation / repayment

**Net debt repayment.** Paid down: the §2.7 enforcement gap (partially — lane built, gate-scope fold
pending); the single-file weight-integrity limitation (now all-entries); unbounded security-critical deps
(now pinned). Added (all tracked, none silent): the gate-scope-fold residual (MINOR-4), the SCR count
imprecision (MINOR-2), the `tools/tests/` collection errors surfaced + recommended for ticketing
(MINOR-5). Doc debt small + tracked. The hardening follow-ups are correctly non-optional carry-overs, not
"suggested."

### 14.3 Projected next-sprint impact

The single most important Sprint-17 enabler: the gate-scope fold (MINOR-4) + the deferred green runs
(rec 2), so Sprint 17's #615/egress edits modify a cascade that is genuinely locked by the standing gate.
Sprint 16 built the locks; Sprint 17's first action should be to *run them green on hardware* and *fold
them into the gate* before the first edit — exactly the lock-before-modify discipline this wave exists to
enable.

---

## Appendix A — Auditor scope declaration

The Sprint Auditor was invoked manually (fleet LA-paused) as a peer to the Orchestrator per DEC-15, with
a fresh context and no memory of this sprint's in-flight reasoning. I formed my own view of the sprint
window — git log `82a21e5..560b6ad`, all 7 stream merge diffs, the shipped source, both reproduced test
lanes, and the on-disk artifacts — BEFORE reading the SCR's verdicts, in the prescribed order. The audit
posture is adversarial by design; the agreement with all 9 SCR verdicts is earned by independent citation
+ two exactly-reproduced test runs, not deference. All verdicts are my best-faith independent read based
solely on the artifacts in §2.1. I did not read any chat transcript or Orchestrator narration; I did not
run the launcher, boot the system, or run `dotnet build`; I did not run the `hardware`/`winui` tiers (I
confirmed they are correctly marked + read their bodies); I did not run pytest against the real
`%LOCALAPPDATA%` (confirmed conftest isolation first); I did not post any Vikunja comment or mutate any
file other than this SWAGR. The auditor may be wrong; LA veto rights apply in full. If a gap assessment is
disputed, this SWAGR is NOT rewritten — per DEC-15, the LA opens a separate workstream.

_(Signed via frontmatter `auditor_session_fired_at` + the git commit by the Orchestrator that lands this
SWAGR on main — the auditor does not commit.)_

---

## Appendix B — Independent verification log (what I actually ran/read)

| Check | Method | Result |
|---|---|---|
| Test isolation | read `conftest.py` BEFORE any pytest | module-load redirect of LOCALAPPDATA/HOME/XDG + `BLARAI_DEK_KEYSTORE` unset confirmed active (`:74-79`) |
| Layer-A baseline | re-ran the exact pytest command, `-p no:cacheprovider` | **2187 passed / 2 skipped / 15 deselected / 0 failed, 86.23s, exit 0** — matches SCR exactly |
| #619 lane | re-ran `pytest tests/integration/ -m "not hardware and not winui and not slow"` | **18 passed / 88 deselected / 0 failed, 6.58s, exit 0** — matches SCR; boot-cascade + key-transition RAN (per-file dots) |
| Collection errors | `pytest --collect-only -q` | **4 errors, all `tools/tests/`** — matches SCR exactly (refutes the "41" a builder claimed) |
| Sprint window | `git log --oneline 82a21e5..560b6ad` + `git show --stat` on all 7 merges + fold + SCR | 18 commits; every non-merge maps to a stream/fragment/fold/SCR; no ghost commit |
| Disjointness | inspected all 7 merge `--stat` diffs | no file in two streams; coordination assignments held |
| Criterion #2 | read `weight_integrity.py:279` + both `gpu_inference.py` diffs | `verify_all_manifest_entries` iterates all entries + rejects extra `.bin`; wired + fail-closed at PA `:~632` / AO `:~467` |
| Criterion #3 (gate) | read `manifest_signer.py:114-219` | fail-closed signature gate; anti-downgrade on invalid sig; WARNING on unsigned+not-required |
| Criterion #3 (wiring) | grep `load_manifest_verified` in `main` (excluded `.worktrees/`) | PA entrypoint `:790`/`:862-864`, AO `:884`, config-driven default False — exact cited lines confirmed |
| Criterion #3 (locks) | read `test_manifest_signing_mechanism.py` | 6 tests exercise the real `load_manifest_verified` incl. tampered-after-sign binding test |
| Criterion #3 (staged) | `git show HEAD:…/manifest.json.sig` + `ls` model dir | no `.sig` in HEAD; `require_signed_manifest=false` in both `default.toml` (`:26`/`:81`) |
| Criterion #4 | read `manifest_signing_ceremony.md` head + `provision_manifest_signing_key.py` | EA4 non-dev runbook present; ceremony script present |
| Criterion #5 | `git diff … -- services/*/pyproject.toml` + `importlib.metadata` versions | 5 files pinned; all 7 listed pins ∈ installed versions; root pre-pinned in S14 (`c824f6a`) |
| Criterion #6(i) | read `test_key_transition_integration.py` | 9 tests, real stores, both, serves-not-bricks, leaf fail-closed preserved |
| Criterion #6(ii-a) | read `test_boot_cascade_smoke.py` `TestBootCascadeSmoke` | 8 tests, real cert mint/service start-stop/handshake/preflight/teardown; only model load stubbed |
| Criterion #6(ii-b) | read `TestBootCascadeSmokeRealModel` | `@pytest.mark.hardware` (`:584`); deferred; not claimed green |
| Criterion #1 | read `test_winui_critical_path.py:61-180` + AutomationId count | real pywinauto harness (launches exe, drives by auto_id); `slow`+`winui` marked; 24 AutomationIds added |
| Criterion #7 | grep `egress_guard.arm` + `audit_log.py` key/refuse-to-start | `arm()` at `launcher/__main__.py:1133`; `AUDIT_TPM_KEY_NAME`+`AuditProvisioningError` confirmed |
| Criterion #8 | read `coverage_audit.md` header + rows | as-of `82a21e5` stated; gaps marked "closing in Sprint 16 (stream X)" — honest |
| Privacy / NPU | `git diff 82a21e5..560b6ad -- shared/ services/ launcher/` pattern scan | no external-network imports; no NPU revival (one false-positive "Name=") |
| DECISION_REGISTER | grep sprint-16/manifest/#624 | no entry — consistent with SDV §10 "no new ADR" |
| Journal | `git show HEAD:BUILD_JOURNAL.md` grep lessons 67-71 + arc + `ls journal_fragments` | lessons 67-71 + arc entry present; fragments deleted (README only) |
| Ledger | `ls docs/ledger/` | ends at Sprint-15 entry; Sprint-16 entry pending (MINOR-1) |
| Vikunja gate-trace | `get_task` 624 | `Gate:Approved`, `done:false` — noted, not treated as ground truth |

---

*Independent Sprint Auditor — read-only. This report was written to
`docs/sprints/sprint_16/Strategic_Work_Analysis_and_Gap_Report_Sprint_16_20260607_133305.md`; the Auditor
did not modify source, did not commit, and did not merge.*
