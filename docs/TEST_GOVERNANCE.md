# Test Governance

**BlarAI Phase 5 — Canonical Test Governance Reference**
**Established:** 2026-04-18 | **Task:** P5-Task-6 | **Ledger:** Entry 38
**Maintained by:** The EA that changes test counts MUST update this document.

---

## 1. Named Test Scopes

| Scope | Command | Covers | Baseline |
|-------|---------|--------|----------|
| UNIT | `pytest shared/ services/ --tb=short -q` | `shared/`, `services/` (no launcher, no integration) | 755 passed, 2 skipped |
| FOCUSED | `pytest shared/ services/ launcher/ --tb=short -q` | `shared/`, `services/`, `launcher/` | 791 passed, 2 skipped |
| REGRESSION | `pytest shared/ services/ tests/ --tb=short -q` | `shared/`, `services/`, `tests/` (slow excluded by default) | 755 passed, 2 skipped, 80 deselected |
| FULL | `pytest -m "slow or not slow" shared/ services/ tests/ --tb=short -q` | All scopes including slow-marked integration tests | 835 passed, 2 skipped ⚠️ requires live runtime |
| SERVICE | `pytest services/{service_name}/tests/ --tb=short -q` | Single service only | Varies |
| SLOW | `pytest -m slow tests/integration/ --tb=short -q` | `tests/integration/` (slow-marked only) | 80 tests ⚠️ requires live runtime |

**Valid `{service_name}` values:** `policy_agent`, `assistant_orchestrator`, `semantic_router`, `ui_gateway`, `ui_shell`

> **FULL and SLOW scopes** exercise slow-marked integration tests that establish real socket connections
> to the Orchestrator VM. Running without live services will cause test failures. Use these scopes only
> for task/phase closure gates and runtime validation sessions.

> **⚠️ Baseline currency (updated 2026-06-07, Sprint-16 close — gate-scope fold, LA-directed):** the
> per-scope counts in the table above are Sprint-8-era named-scope baselines and are **stale** (the suite
> has grown many sprints since). The **canonical live baseline** is now the **standing gate** selection
> `pytest shared/ services/ launcher/ tests/integration/ tests/security/ -m "not hardware and not winui and not slow"`
> = **3225 passed, 0 skipped, 116 deselected** (2026-06-12, **post the #655 go-live prep** — ADR-027 Am.1 precondition-2 verification (all four activation preconditions MET) + dormant mTLS host-side plumbing (`[guest_parser].mtls_cert/key/ca`, plaintext default); **+3 regression tests** → **3225/0/116 green on clean main** (`6096387`, 2:21). The door stays welded by three implementation locks. **Prior chapter — 3222** (2026-06-12, **post the #655 url-adjudicator deterministic adapter** — `make_deterministic_url_adjudicate` over the already-dormant ADR-027 §2 egress carve-out (in-process `DeterministicPolicyChecker`, the verified pathway — NOT a vsock hop nor a second GPU adjudicator); **+7 regression tests** over the REAL checker → **3222/0/116 green on clean main** (`be603db`, 2:18). The empty egress allowlist denies every URL = a third door lock (adjudicator not-registered + `guest_parser` disabled being the other two). **Prior chapter — 3215** (2026-06-12, **post the #655 sub-task 6 host glue** — the `/ingest <url>` fetch→guest-parse→preview corridor: `clean_from_guest_parse` (host ADR-030 §5 injection compose, byte-identical to `clean_html`), `parse_round_trip` + `GuestParserManager.parse_html` (bridge/in-process content parse), the `ingest_coordinator` URL path through the one PA-gated `guarded_fetch` door, and the `url_adjudicator` factory; **+40 regression tests** → measured **3215/0/116 green on clean main** (`75ba1c7`, 2:10). The egress door stays **deny-by-default**: the adjudicator is built-not-registered and `guest_parser` ships `enabled=false`, so URL ingest refuses by two independent locks until the LA go-live ceremony. **Prior chapter — 3175** (2026-06-11, **post the #655 Stage C merges + the parser error-path hardening + the version bridge + the plaintext-AF_HYPERV fix**: the program-merge 2991 below grew **+70** (Stage C parse channel — `INGEST_PARSE_*` framing + chunking over the 64 KB vsock cap + the guest parser service + egress-scan extension over `services/cleaner/guest`) and **+61** (Stage C guest provisioning + launcher `guest_parser` wiring, `enabled=false` shipped default) → **3122/0/116 measured green** on the integrated tree (1:43; collect-only derivation 2991→3122, zero shortfall); then **+9** parser error-path regression locks (`526e798` — drop-not-crash on un-encodable error replies, 256-char request_id cap, accept-loop catch-all, violation-code split) → **3131/0/116**, 1:18; then **+29** the version bridge (3.14 AF_HYPERV subprocess so the 3.11 runtime reaches the guest; `83580ab`) + **+15** the plaintext-AF_HYPERV bring-up fix (decoupling transport-family from mTLS, fail-closed default; `01538fb`) → **3175/0/116 measured green** on the bridge+fix tree, 4:48. The guest-homed parser's host↔guest round-trip was PROVEN live over the real AF_HYPERV vsock boundary that day — see #655 c.1063). **Prior chapter — 2991** (2026-06-10, **post the #655 UC-002/003 program merge**: the 2565 post-eight-merge figure below grew **+4** (#657 VM stop-on-exit) then **+90** (#577 `guarded_fetch` egress door) → **2659** (the door merge-gate re-run measured 2659/2/116 non-elevated), then **+323** measured net-new from the UC-002/003 program — #655 knowledge bank / cleaner / ingest UX / Stage-A ADRs; collect-only derivation 2661→2984 selected, zero shortfall against the merged tree; measured **2984/0/116 green** on the integrated tree 2026-06-10 on a symlink-privilege (Dev-Mode/elevated) shell — a shell without the symlink-create privilege yields the standing ±2 symlink-skip delta described below; then **+7** from the merge-time real-pipeline integration test (`tests/integration/test_ingest_real_pipeline.py`, `689a08e` — real cleaner through the real ingest coordinator, runbook c.1040 item 4) → **2991/0/116 measured green on clean main**, 5:07). **Prior chapter — 2565** (2026-06-10, **post the eight LA-added gate-criteria merges**; that live run measured **2563/2/116 on a non-elevated shell** — the ±2 is exactly the standing symlink-privilege delta described below; bumped from the 2026-06-09 2360/0/116 by **+126 regression tests across #634 exfil-screen wiring (+14, `651ef4a`), #643 egress proving (+11, `14d21c3`), #637 data-map DACL hardening (+30, `2d82f69`), #639 ESCALATE human-review consumer (+31, `494ebb8`), and #649 Windows-Hello biometric verifier (+40, `c1f51e9`)** — taking the gate to 2486 — then **+61 more across the 2026-06-10 #652 launcher privilege-strip (+26: 16 privilege-strip + 10 orphan-guard), #607 audit-retention/segmentation (+24), and #653 egress fingerprint re-arm (+11)**; all eight landed in the gate selection (deselected unchanged at 116), then **+18 from #611 embedding-cache idle-unload** (2026-06-10, a live-memory footprint feature, not a gate criterion) → 2565. The 2360 itself = the Sprint-18-close 2342/0/113 + 18 #638 token-containment tests + 3 @hardware/@slow from the post-close #612 capstone work (113→116 deselected)). **Shell-elevation note (Sprint-18 finding (a)):** 2565/0 is the **elevated / Dev-Mode shell** number; a **non-elevated shell yields 2563/2**, where the two symlink tests `shared/tests/test_runtime_config.py:84` / `:104` skip for lack of the symlink-create privilege — **0 failures, identical coverage**. Do NOT mistake 2563/2 for a regression. (An isolated worktree that lacks the gitignored `bge-small-en-v1.5` ONNX model additionally env-skips \~20 `services/semantic_router/tests/test_router.py` cases — also benign, also not a regression; they pass on the main checkout where the model is present.) **Port-5001 seam — FIXED (Sprint-18, C6/#630):** the WinUI-harness teardown now reaps its spawned process tree (`tests/harness/process_tree.py`) and a session-scoped autouse fail-loud detector in the root `conftest.py` surfaces a leaked AO on loopback 5001 as a *failure* (free→held delta), not a silent skip — so the deterministic 2360/0 reproduces **without a manual process-kill** (re-confirmed twice from main + by the Sprint-18 Auditor SWAGR). (Under `require_signed_manifest = true` the FUT-04 C7 flip un-skipped 2 signed-manifest tests — prior figures 2212/2/103 Sprint-16, the suite grew across Sprints 17–18; Sprint-18 C1 verified the detached `.sig` at boot.)
>
> **This scope CHANGED at the Sprint-16 close** (BUILD_JOURNAL lesson 70; Sprint-16 SWAGR MINOR-4): the
> prior Layer-A subset was `shared/ services/ launcher/` = 2187, which **excluded** two dirs whose locks
> must actually fire — `tests/integration/` (the #619 production-parity lane: the boot-cascade smoke +
> key-transition tests) and `tests/security/` (the posture guards `test_secure_defaults` /
> `test_root_test_isolation` / `test_no_external_egress`). Both could pass on disk while a green gate said
> nothing about them. They are now folded into the standing gate so a green run is real coverage. The
> default `pytest` marker filter (`addopts`) now also deselects `hardware` + `winui` (matching the marker
> docs), so the GPU boot-smoke (#619 real-model tier), the GUI harness (#621), and the socket E2E (`slow`)
> stay dev-machine-only. **Still outside the gate:** the benchmark dirs (`tests/pa_quality_benchmark`,
> `tests/substrate_benchmark`) — excluded from the explicit gate paths. (`tools/tests` was REMOVED
> 2026-07-04, closing #626: its 4 collection errors were stale orphans of the platform-separation
> extraction — the modules they import (`tools._project_context`, `tools._vikunja_client`) and the
> maintained twin copies of all 6 test files live in devplatform, where the suite runs green (85 passed,
> 2026-07-04) against the real modules. With the orphans gone, full-suite collection is clean and a bare
> `pytest` becoming the gate is unblocked.) Treat this scope as the authority; the named-scope rows above
> await a re-measure pass.

---

## 2. Scope Selection Guide

| Activity | Required Scope | Notes |
|----------|----------------|-------|
| Single-service code change | SERVICE + REGRESSION | Run targeted first, then regression |
| Shared library change | REGRESSION | Shared code impacts all consumers |
| Cross-service change | REGRESSION | Any change touching 2+ services |
| Code-change milestone gate | REGRESSION | Standard EA quality gate |
| Runtime / E2E validation | SLOW or FULL | When testing against live services |
| Task closure gate | FULL | All tests including slow must pass |
| Phase closure gate | FULL | All tests including slow must pass |
| Quick smoke check during dev | UNIT | Fastest feedback loop |

> **Default scope for SDO-generated EA prompts:** REGRESSION, unless the milestone explicitly
> requires FULL (runtime validation or task/phase closure).

---

## 2.5 Test Posture — dev-mode vs production (Decision 8, 2026-06-05)

**The scope tables above say WHAT is tested; this says in WHICH SECURITY POSTURE — and it is load-bearing.**

A failure this project already lived: with `dev_mode` the silent runtime default
(launcher-forced for HOST; shipped `dev_mode=true` in `guest_runtime.toml`), every
scope above ran against the security-OFF profile. The suite was green and agents
reported "BlarAI works" — but validated a configuration that would never ship (no
mTLS, throwaway keys, no measured-boot). **A green test on a fiction.** This must
never recur, and the guard CANNOT depend on anyone remembering a flag — the
User-Operator does not run tests manually and must not have to.

**Rules (Decision 8 / gate #598 / tracked #600):**

1. **Production posture is the verification target.** Any "works" / "verified"
   claim that gates something (task closure, phase, the air-gap GO/NO-GO #598) MUST
   be measured with `dev_mode=false` + real certs/keys. A dev-mode result is
   **dev-scoped** and must be labelled so — never reported as unqualified "works."
   (Runnable once the Tier-2 cert/mTLS build lands; until then production-posture
   gating tests are a TRACKED deliverable, #600, not silently skipped.)
2. **Network-feature tests own their sandbox.** Tests for network-facing features
   (web-nav) programmatically stand up their own sandbox — test data + throwaway
   keys + a controlled endpoint — inside the fixture. The deliberate, loud
   dev-mode-network-facing path is the HARNESS's job, asserted in-test; it is NEVER
   a human-invoked flag.
3. **The wrong posture fails loudly.** A CI posture-guard (building on
   `tests/security/test_secure_defaults.py`, which already locks the shipped config
   to `dev_mode=false`) FAILS if dev-mode is the silent runtime default or if
   production-posture verification is absent from a closure gate. The trap
   re-announces itself in CI; it cannot go quietly green.

This section is policy now; the automation in rules 1–3 lands with Tier 2 + the
web-nav feature (#600). Until then: **no dev-mode result counts as production
verification.**

---

## 2.6 Test-Process Isolation — never touch the real user-data dir (2026-06-06)

**The suite must never read or write the operator's real `%LOCALAPPDATA%\BlarAI\`.** That directory
holds the live `sessions.db`, `substrate.db`, and the TPM-sealed `dek_keystore.json`. A Sprint-14
incident proved the risk concretely: tests that call service startup resolved the real `LOCALAPPDATA`
and wrote dev-key-encrypted rows into the operator's live `sessions.db`, which the production key could
not decrypt — the backend then refused to start (`[7199c5ab]`).

The guard is layered, and the order matters:

1. **Root `conftest.py` (first layer, load-bearing).** At pytest process startup — before collection
   imports any module — the rootdir `conftest.py` redirects `LOCALAPPDATA`, `HOME`, and `XDG_DATA_HOME`
   to a throwaway `tempfile.mkdtemp(prefix="blarai-pytest-userdata-")` dir and unsets
   `BLARAI_DEK_KEYSTORE`. This is the ONLY layer that can protect **import-time module constants** (e.g.
   `SESSION_DB_PATH` in `services/ui_gateway/src/constants.py`), which resolve the path the moment their
   module is imported — before any fixture runs. A function- or session-scope fixture is too late for
   these. `tests/security/test_root_test_isolation.py` is the regression lock: it fails if the conftest
   is removed or its mutations are moved into a fixture.
2. **Package autouse fixtures (second layer, defense-in-depth).** The `assistant_orchestrator` and
   `ui_gateway` package conftests redirect the same env vars per-test, covering **call-time** reads
   (e.g. `_build_substrate()` reading `os.environ` at runtime). They remain even though the root
   conftest now precedes them.

A test that needs a specific user-data path sets it explicitly via `tmp_path`; it never relies on the
real directory being present. This isolation is non-negotiable: a test that can reach real user data is
a data-corruption risk, not a flaky-test risk.

---

## 2.7 Test Coverage Mandate — every major aspect automated, minimal human-in-the-loop (2026-06-06)

**§2.5 says test in the production posture; §2.6 says never touch real user data; this says
there must BE an automated test of every major aspect in the first place — including its real
integrated path, not only its mocked units.**

A failure this project lived on 2026-06-06 (Sprint 15 EA-4 production live-verify): the suite
was green — 2163 passing — yet the first real production boots failed repeatedly, each on a
different production-only seam. The boot cascade (certs / service handshakes); then the prompt
route (the gateway was wired to the Policy Agent's port instead of the Orchestrator's, so every
prompt came back "Unsupported message type"). Both passed the unit suite — because unit tests
mock the seam (the IPC boundary, the boot wiring) and the bug lived in the seam. And the project's
own three-layer scenario harness (#563) did not catch it either: its dispatcher layer drives a
*fake* gateway, so the real gateway→Orchestrator routing the launcher mis-wired was exercised by
nothing, and its window layer (real pywinauto UI automation) drives a *fake* backend, so the GUI
against the real model-loaded path is still untested. **A green unit suite that mocks the boundary
is not coverage of the boundary — and an integration test that mocks the same boundary is no
better.** Each break was found by the User-Operator at a
terminal, one at a time — the exact human-in-the-loop cost this mandate removes.

**Mandate (Lead Architect directive, 2026-06-06; initiative tracked #622):**

1. **Every major subsystem has automated tests at the right fidelity** — not only unit (mocked)
   coverage per §6, but an automated test of its **real integrated / end-to-end path** wherever
   a meaningful seam exists (cross-service IPC, boot wiring, the model-loaded prompt round-trip,
   the GUI). §6 governs "every function has a happy + error test"; this governs "every subsystem
   has a test that exercises the seam its units mock away."
2. **Minimal human involvement is the design target.** Routine verification MUST NOT require the
   User-Operator at a terminal — strengthening §2.5's "the User-Operator does not run tests
   manually and must not have to." The only verification that may need a human is what genuinely
   needs human judgment (visual/aesthetic polish, novel-UX exploration), and even there the
   harness asserts everything it can (state, text, behaviour) so the human judges only what
   automation cannot.
3. **Tests are part of done.** A subsystem or feature is not "done" until its automated tests
   exist, including an integrated / end-to-end test where one is meaningful. Same standing as the
   BUILD_JOURNAL entry: shipping a subsystem without its automated coverage is an incomplete
   deliverable. New code ships WITH its tests; it does not get them "later."
4. **Fidelity ladder.** unit (mocked, §6) → integration (real cross-service, `tests/integration/`
   + `slow`) → on-hardware end-to-end (model loaded, production posture per §2.5). A seam that has
   burned the project — IPC routing, boot wiring, GUI — earns a test that EXERCISES it, never one
   that mocks it. Where the full end-to-end needs hardware (the GPU, the real TPM, a desktop
   session for the GUI), that tier runs on the dev machine with results recorded; the cheaper
   tiers run in CI.

**Cadence (#622):** a coverage audit maps every major aspect → has automated tests / at what
fidelity / where the gap is → a prioritized burn-down across Sprints 16+. Open members: #619
(production-parity boot cascade in CI), #620 (prompt-route integration + the model-loaded
prompt-flow preflight as a default boot gate), #621 (the WinUI GUI automation harness). The
objective named by the Lead Architect: *production stability and speedy development with as little
human involvement as is reasonable.*

---

## 3. Canonical Baseline

### Current Baseline

| Scope | Passed | Skipped | Deselected | Notes |
|-------|--------|---------|------------|-------|
| UNIT | 755 | 2 | — | No launcher / no integration |
| FOCUSED | 791 | 2 | — | Adds 36 launcher tests vs. UNIT |
| REGRESSION | 755 | 2 | 80 | 80 slow tests deselected by default |
| FULL | 835 | 2 | — | Requires live Orchestrator VM |
| SLOW | 80 collected | — | — | Requires live runtime to pass |
| SERVICE | Varies | — | — | Parameterized — run per service |

### Baseline Provenance

| Field | Value |
|-------|-------|
| Branch at establishment | `feature/p5-task6-test-governance` |
| main HEAD at Task 6 start | `103dfe6` |
| Date | 2026-04-18 |
| Ledger entry | Entry 38 |
| Verification method | Empirical runs of all scope commands |

FULL scope baseline (835/2) is from Task 5 M5.5 pre-streamlining gate (Entry 37) and confirmed
by verifying that `-m "slow or not slow"` successfully overrides the default `addopts` marker
filter (override syntax confirmed working 2026-04-18).

### Update Policy

- Baseline MUST be updated whenever tests are added, removed, or reclassified.
- The EA that changes test counts MUST update this section as part of their milestone commit.
- `.github/copilot-instructions.md` baseline MUST stay in sync with this document.
  **This document is the canonical source of truth.**
- Stale baselines are a governance violation.
- **Re-baselining scope rule:** When an EA adds, removes, or reclassifies tests, they MUST
  re-run ALL scopes that could be affected — not just the scope used during development.
  Example: adding a unit test affects UNIT, FOCUSED, REGRESSION, and FULL. The EA must run
  each affected scope, capture the summary line, and update every baseline row that changed.
  This prevents drift where an EA adds tests but only updates one row.

### Pre-Existing Skips

Two tests are permanently skipped (pre-existing since Task 4, accepted):

| Test | Reason |
|------|--------|
| `test_build_prompt_does_not_contain_no_think` | Qwen3 thinking suppression constants intentionally deferred |
| `test_stop_token_ids_constants_defined` | Qwen3 stop token constants intentionally deferred |

These skips are accepted and do not constitute failures. They will be resolved when the
deferred constants work is scheduled.

---

## 4. Marker Policy

### Current Markers

| Marker | Registered In | Purpose | Default Behavior |
|--------|--------------|---------|-----------------|
| `asyncio` | `pyproject.toml` | Async coroutine tests | Auto-applied (`asyncio_mode=auto`) |
| `slow` | `pyproject.toml` | Socket-timeout integration / real-hardware tests | **Deselected by default** (in the `addopts` filter) |
| `hardware` | `pyproject.toml` | Real OpenVINO models on the GPU/CPU — dev machine (e.g. the #619 real-model boot-smoke) | **Deselected by default** (added to `addopts` at the Sprint-16 close) |
| `winui` | `pyproject.toml` | Drives the real WinUI window via UI Automation — dev machine (the #621 GUI harness) | **Deselected by default** (added to `addopts` at the Sprint-16 close) |

> **`addopts` filter (since the Sprint-16 close):** `-m 'not slow and not hardware and not winui'` — the three dev-machine/socket tiers are deselected on every default `pytest` run, so the standing gate (§1, run over `shared/ services/ launcher/ tests/integration/ tests/security/`) exercises the production-parity lane + the posture guards while the GPU/GUI/E2E tiers stay dev-machine-only.

### Qualification Criteria for `slow`

A test MUST receive the `slow` marker if it:
- Requires real socket connections with timeout waits
- Takes >30 seconds individually
- Requires running services (integration / E2E)

Application rule: Apply at module level via `pytestmark`, not per-test.

**Current `slow` usage:**
- `tests/integration/test_p110_end_to_end.py` — `pytestmark = pytest.mark.slow`
- `tests/integration/test_p114_ui_end_to_end.py` — `pytestmark = pytest.mark.slow`

### Future Marker Guidelines

1. New markers MUST be registered in root `pyproject.toml` with a description.
2. New markers MUST have documented default behavior (selected or deselected).
3. Adding a marker that changes default selection MUST update the baseline table above.
4. Marker names: lowercase, single word, descriptive.
5. Any new marker requires an update to this document.

---

## 5. Gate-Checking Order

All EA milestones follow this order. Do not skip or reorder.

### Gate 1 — COMPILE

| Field | Value |
|-------|-------|
| Command | `python -c "import py_compile; [py_compile.compile(f, doraise=True) for f in ['file1.py', 'file2.py']]"` |
| Pass criteria | Zero compilation errors |
| Fail action | **STOP** — do not proceed to TEST gate |

### Gate 2 — TEST

| Field | Value |
|-------|-------|
| Command | Use the scope defined in the EA prompt (default: REGRESSION) |
| Pass criteria | (a) Zero new failures; (b) pass count ≥ baseline for the scope used; (c) no new skips without documented justification |
| Fail action | **STOP** — diagnose and fix before proceeding |
| Evidence | Capture the pytest summary line in the commit message and/or ledger entry |

### Gate 3 — REGRESSION *(test infrastructure changes only)*

Required when test files are added/removed/renamed, markers changed, or `pyproject.toml`
test config modified.

| Field | Value |
|-------|-------|
| Command | FULL scope: `pytest -m "slow or not slow" shared/ services/ tests/ --tb=short -q` |
| Pass criteria | Total pass count matches FULL baseline (835 passed, 2 skipped) |
| Fail action | **STOP** — the test infrastructure change broke something |

### Relationship to `copilot-instructions.md`

The `copilot-instructions.md` gate-checking order (Compile → Test → Oracle) is the top-level
rule. This document provides the detailed implementation of the TEST gate: which scope to use,
pass criteria, and evidence requirements.

### SDO Prompt Integration

- Every SDO-generated EA prompt MUST specify which test scope to use in its `<quality_gate>` section.
- Default is REGRESSION unless the milestone involves runtime validation or task/phase closure.
- The EA MUST capture and report the exact pytest summary line.

---

## 6. Test Development Policy

### When Tests Are Required

- Every code-change milestone that modifies production Python files MUST include tests for
  new or changed behavior.
- DOCS-ONLY milestones and runtime-validation milestones are exempt.
- "Production Python files" = any `.py` file under `services/`, `shared/`, or `launcher/`
  that is NOT in a `tests/` directory.

### Where Tests Go

| Code location | Test location |
|---------------|---------------|
| `services/{service_name}/src/` | `services/{service_name}/tests/` |
| `shared/src/` | `shared/tests/` |
| `launcher/` (non-tests) | `launcher/tests/` |
| Cross-service integration | `tests/integration/` + add `slow` marker |

New service → create new `tests/` directory → update `testpaths` in root `pyproject.toml`.

### Naming Convention

File naming: `test_{module_name}.py`
- Examples: `test_car.py` tests the `car` module; `test_pgov.py` tests the `pgov` module.

Function naming: `test_{descriptive_snake_case}` — fully descriptive, no abbreviations,
snake_case throughout.

Observed styles (all acceptable):

| Style | Examples |
|-------|----------|
| Verb-noun | `test_build_car_minimal`, `test_ssn_detected` |
| State-behavior | `test_frozen_immutable`, `test_construction_defaults` |
| Condition-result | `test_elevation_denied_returns_1`, `test_encode_size_limit_exceeded_raises` |

Do NOT invent new conventions. Follow the established patterns above.

### Test Boundary Rule

- **Unit tests** (`services/*/tests/`, `shared/tests/`, `launcher/tests/`) MUST mock external
  dependencies: IPC sockets, file I/O, network calls, hardware interfaces. They run without
  any running services.
- **Integration tests** (`tests/integration/`) test real cross-service interaction and MUST
  receive the `slow` marker (module-level `pytestmark`).
- No test should require manual setup or external state beyond what pytest fixtures provide.

### Coverage Expectation

No numeric coverage target (avoids over-engineering).

Gate rule: Every public function or class added or modified MUST have at least one test
exercising its primary (happy) path AND at least one test exercising its error/edge path.
This is enforced by code review (SDO or Lead Architect), not by tooling.

---

## 7. Stale Artifacts

The following root-level files are historical snapshots and are **NOT authoritative**.
Do not use them for current baselines.

| File | Era | Content | Status |
|------|-----|---------|--------|
| `pytest_baseline.txt` | Phase 3 closure | 670 passed | STALE |
| `pytest_output.txt` | Task 4 era | 786 collected | STALE |
| `pytest_m53_gate.txt` | Task 5 M5.3 | 835 passed | Superseded by this document |
| `pytest_m54_gate.txt` | Task 5 M5.4 | 835 passed | Superseded by this document |

The canonical source of truth for all test baselines is this document (`docs/TEST_GOVERNANCE.md`).
