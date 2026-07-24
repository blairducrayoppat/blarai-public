---
title: Test Governance
status: living
area: testing
---

# Test Governance

**BlarAI — Canonical Test Governance Reference** · Established 2026-04-18 (Ledger Entry 38)
**Maintained by:** the merging session that changes test counts or gate scope — update §1's
live baseline line in the SAME commit. This is gate-enforced:
`tests/security/test_doctrine_freshness.py` fails if §1's figure disagrees with
`CLAUDE.md <status_snapshot>` or if `.github/copilot-instructions.md` pins any count.

---

## 1. The Standing Gate

**Selection:**

```
pytest shared/ services/ launcher/ tests/integration/ tests/security/ -m "not hardware and not winui and not slow"
```

**Bar:** 0 failed, 0 skipped in a clean environment. A skip is investigated, never waved
through. Always redirect `LOCALAPPDATA` (§2.6); run from a TERM-bearing shell with no
`PYTHONIOENCODING` override (the PowerShell tool shell false-fails 3 tests — bash is the
proven runner).

> **LIVE_GATE_BASELINE: 9047 passed / 0 failed / 0 skipped / 125 deselected**
> *(as of 2026-07-23, #1067 v7 carve-out + honest grading instrument — prior 8919, +128:
> MEASURED on merged main `c2316106` (primary LF checkout, models present, app down,
> LOCALAPPDATA redirected, bash runner; 9047 passed / 0 failed / 0 skipped in 266 s),
> NOT derived. The delta is the #1067 v7 guard suite grown for the carve-out plus the
> grading instrument's new locks (exact-bipartition screen, fail-loud token cap,
> grade_window figure lock, characterisation test) and the merge-session disposition
> discipline. prose_guard.py's runtime behaviour is unchanged; nothing went live
> (coordinator stays shadow). The branch worktree read 9024/1-CRLF-artifact/21-model-skip;
> those resolve to 0/0 on the primary checkout, which is why the merged-main figure is
> the authority — RE-MEASURE here, never derive from a worktree run.)*
>
> *(prior entry, 2026-07-23, #1079 grading instrument — prior 8883 (post-#1043 clean-env), +26: the coordinator
> graduation grading tool's suite in
> `shared/tests/test_coordinator_graduation_grading.py` — positive control
> (asserted against a fixture whose known answer is a FAILING window), determinism,
> oracle/guard independence, corpus fail-loud, superseded-decision abstention, and
> the N-bar-counts-VERIFIED-decisions lock. MEASURED 8873 in the isolated build
> worktree, where 21 model-dependent tests env-skip on the gitignored weights;
> merged main restores those, hence 8909. The +26 was taken from
> `pytest --collect-only`, not derived: an earlier +23/8891 pair was off by the
> tests the later fix commits added, and BOTH surfaces carried the wrong figure
> consistently — which is exactly the #970 hole, so
> **RE-MEASURE on merged main before trusting this line** rather than relying on
> the freshness gate, which only compares this figure to the CLAUDE.md snapshot.)*
>
> *(prior entry, 2026-07-23, S3 slice A — prior 8852, +16: the #1055 honest-revise
> message's parametrized false-positive corpus (8 task-edit inputs the pre-merge
> review's F1/F2 flagged) + true-positive/scope corpus (6 inputs) in
> `tests/integration/test_dispatch_coordinator.py`. RE-MEASURED on merged main
> `70d5ddee` (4:17, app down, LOCALAPPDATA redirected, bash runner).)*
>
> *(prior entry, 2026-07-23, the scaffold window — prior 8851, +1: the neutral-seed
> prompt-companion lock (35e8df49). The merged-main re-run caught one
> pre-existing lock the merge semantically outdated — the oracle-contract test
> pinned the retired app.core literal; re-pinned to the app-package intent in
> 8dce0935 and re-measured green at 8852.)*
>
> *(prior entry, 2026-07-23, the #1049 window — prior 8828, +23: the already-satisfied
> pre-check suite + execute-handler contract locks, gated green on merged main
> c67e99ab in the change's own attribution window.)*
>
> *(prior entry, 2026-07-23, the overnight merge train — prior 8780, +48 across five
> serialized merges, each gated green on merged main: #1021 journal chronology
> gate +5 (8785), #946 guard lexicon locks +5 (8790), #1059 lesson-tally sync
> gate +10 (8800), #1060 ceremony-flag capability-truth gate +16 (8816), #1058
> sandbox-freshness precondition +12 (8828, incl. its timeout-registry row).
> Every figure MEASURED on merged main, never derived.)*
>
> *(prior entry, 2026-07-22, the journal fold's lesson-156 third-instance control — prior
> 8776, +4 in `test_acceptance_clarify.py`: an `ast` enumeration of every consumer
> of `planning_seed` after its mint in `generate_plan`, deny-by-default against an
> explicit allowlist (`rule_spec` alone, which owns the clean `spec.goal` by
> contract), a paired reached-by-the-seed assertion so "no offender" cannot be
> satisfied by "no consumer," and a planted-violation toggle-off. Both locks
> mutation-proven RED against the reverted #1032 fix (both the direct and the
> LAUNDERED shapes) with byte-exact restore verified by digest, plus a
> planted-violation toggle-off and a negative control. The figure was WRONG
> TWICE before it was right: first 8780 from a miscount of helper functions as
> tests, then 8779 after measuring — and back to 8780 once independent review
> added the negative control. The count is now MEASURED, never derived.
> Prior 8776: #1031 S1 advanced-intake DORMANT merge — prior 8744, +32
> across `test_advanced_intake.py` (realism guard + delivery floor + the #1041
> identity-idempotency and floor-then-guard ordering lock driven through the real
> generate_plan), `test_plan_handler.py` (the three #1042 dormancy locks over the
> REAL config loader + the fail-open close), and `test_acceptance_clarify.py`;
> measured on merged main `72c0990c`, app down, models present. Flag ships false.
> Prior 8744: #1050 ledger-candidate gate — prior 8735, +9 from
> `test_ledger_candidate_discipline.py` (every ledger "tuning candidate" names a
> `#NNN` or an explicit `no-ticket:` reason with a word floor; BLOCK-scoped, not
> line-windowed; whitespace-normalised so a hard-wrapped phrase is still seen;
> planted-violation toggle-off; both honest forms as negative controls; a
> different-block ticket must NOT satisfy a candidate). The gate FAILED on its
> first run against the live ledger, catching three unreferenced candidate
> blocks — two un-ticketed since the seed run (now #1049). An independent review
> then found the first implementation 25% blind to wrapped phrases and ~83%
> ineffective on its line window; rebuilt, and the reviewer's own plant-everywhere
> experiment went 16.8% -> 65.9% caught with all four realistic placements caught.
> Round 2 then fixed a FALSE POSITIVE (a nested sub-bullet reference was refused;
> only a top-level bullet starts a block now) and corrected a wrong characterisation
> of the residual in the round-1 commit message - measured 0 of 221 misses matched
> the stated mechanism, the true one being its mirror image.
> Measured 8742 with a battery run CONCURRENT (467s vs the usual ~230s); 0 failed
> / 0 skipped, and re-measured uncontended on merged main.
> Prior 8735: #1032 job-oracle requirements channel — prior 8733, +2 from
> `test_acceptance_clarify.py` (the clarified-requirements block reaches the
> MULTI-task job-oracle authoring prompt verbatim, captured from the real
> prompt rather than asserted on the argument, vacuity-guarded; plus the
> no-requirements byte-identity proof by prompt EQUALITY across the two
> no-requirements paths). Mutant proven: reverting the one argument turns the
> first lock RED and correctly leaves the second GREEN.
> Prior 8733: #989 wave-1 scope ceiling — prior 8711, +22: **21** from the
> new `test_wave1_scope_ceiling.py` (scope-ceiling composition reaching ROOT tasks,
> <2-task exemption, shared/ambiguous-ownership permitting, plan-time
> contract-coverage warn-loud on both oracle origins, added-only scope-sprawl
> finding, evidence control-stripping) + **1** from `test_integration_gate.py` (the
> exact-sequence dep-delta ref pin that replaced a provably weaker re-pinned lock —
> review round 1, F1); measured clean on merged main `49988be8`, app down.
> Prior 8711: #1006 tool-call status — prior 8695, +16 from
> `test_eval_harness.py` (TestToolCallStatus: closed-pair detection incl.
> unclosed-mention-stays-a-fail, full baseline transition matrix, offline-path
> equivalence, resolved-binding drift lock); measured clean on merged main
> `e28c255a`, app down.
> Prior 8695: #877 revise repo-path fix — prior 8694, +1 from
> `test_dispatch_coordinator.py` (revise-minted tasks carry the plan-time
> resolved repo path; production-shaped fixture, toggle-off proven red);
> measured clean on merged main `9c972dcc`, app down.
> Prior 8694: #1022 gate-spec restoration — prior 8692, +2 from
> `test_doctrine_freshness.py` (comprehension-gate section-list pin on every
> gate-stating surface + toggle-off proof); measured clean on merged main
> `c6d1926a`, app down.
> Prior 8692: #1003 order-probe — prior 8690, +2 from `test_oracle_qa.py`
> (coverage-map order-independence, both injection hooks, vacuity-guarded).
> Prior 8690: the six-merge overnight cluster — prior 8653, +37 measured
> on merged main (never summed per-branch): #1001 trend locks, #1008 the
> battery-plans suite, #1010 baseline-validation locks, #1004 corpus integrity,
> #795 stopword locks.
> Prior 8653: #1009 unwired-generator-is-a-skip (+2 from
> `test_eval_oracle_quality.py` — unwired generator does not fail the run; a
> generator that RAISES is still an ERROR, never a skip).
> Prior 8651: #1000 hardware-tier baseline teeth (+14, `test_eval_harness.py` —
> unbaselined-failure regression ×2 statuses, first-pass not-a-regression,
> recorded-known-failure unchanged, non-canonical baseline status ×6,
> non-string baseline status is a harness error ×4).
> Prior 8637: the #965 oracle-unfit attribution fix (+9, `test_integration_gate.py`).
> Prior 8628: the #994 doc-rot gate (+34 from `test_doc_pointers_and_banners.py`).
> Prior 8594: deferral-discipline (+28, `9ecad198`); 8566: #978 pair; 8555: #927.
> Clean env = models present, app down, TERM-bearing shell.
> An ISOLATED WORKTREE cannot confirm the 0-skipped half of this figure: without
> the gitignored models it reports 21 env-skips (20 `services/semantic_router/
> tests/test_router.py` needing bge-small-en-v1.5 ONNX, 1 `test_benchmark_kv_
> cache_sweep.py` needing the 14B `config.json`). Benign and bounded — but it
> means a worktree-measured figure is PROVISIONAL: the passed count is real,
> the 0-skipped claim is not yet evidence. Confirm it with a full run on merged
> main and correct this line if it differs (#1000, 2026-07-20).
> The merging session updates this line + `CLAUDE.md <status_snapshot>` in the same
> commit that changes counts — the freshness gate enforces agreement.
> NOTE: that gate compares these two surfaces only to EACH OTHER (#970), so a
> wrong-but-consistent pair passes silently — re-measure, never copy the other file.)*

**Documented environmental deltas (benign only because named and bounded):**
non-elevated shell → 2 symlink skips · isolated worktree without the gitignored models →
~21 router env-skips · live app on :5001 → 7 skips · PowerShell tool shell → 3
false-fails (TERM / PYTHONIOENCODING) · a `PYTHONUNBUFFERED`/`-u` override → 2
`launcher/tests/test_import_side_effects.py` false-fails (2026-07-21 — do not add
output-buffering overrides to gate invocations). An unexplained skip is a defect.

**Deselected tiers** run at their own dev-machine ceremonies: `@hardware` (model-loaded,
real Arc 140V), `@winui` (GUI harness), `@slow` (socket E2E). Model-quality eval gate:
`python -m evals.run --suite all` — committed baselines, regression exit codes with teeth.

**History:** every prior baseline chapter and the Sprint-8-era named-scope tables live in
[`docs/archive/testing/baseline_history.md`](archive/testing/baseline_history.md) — do
NOT append chapters here; the live line above and the shipping ticket are the record.

---

## 2. Scope Selection Guide

| Activity | Required Scope | Notes |
|----------|----------------|-------|
| Single-service code change | targeted service tests, then the standing gate | Run targeted first for fast feedback |
| Shared library change | standing gate | Shared code impacts all consumers |
| Cross-service change | standing gate | Any change touching 2+ services |
| Merge quality gate | standing gate | Branch gate-green before merge; re-run on merged main after |
| Runtime / E2E validation | `slow` tier or on-hardware | When testing against live services |
| Quick smoke check during dev | targeted paths | Fastest feedback loop |

> Dispatched/briefed work states its scope in the brief; default is the standing gate.

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

**Structural spawn-surface ratchet (#774 sub-task 4, 2026-07-17).** `tests/integration/test_no_new_raw_spawn_sites.py` is a deny-by-default gate in the standing selection: it AST-scans production `shared/` / `services/` / `launcher/` code and FAILS LOUD if any raw `subprocess.*` / `os.spawn*` / `os.system` call site is not in its documented allowlist, forcing new spawns through the blessed `shared/procspawn.py` helper (the lesson-219 Windows-stdio scar family). The allowlist is a ratchet — it only shrinks as #774 sub-task 2 migrates the known `shared/fleet/*` sites onto the helper. Test trees and `procspawn.py` itself are scoped out (documented in the test's SCOPE note).

**Doctrine-freshness ratchet (#945 D8, 2026-07-19).** `tests/security/test_doctrine_freshness.py`
is a deny-by-default gate over the always-loaded doctrine surfaces: it FAILS if this document's
§1 live figure and `CLAUDE.md <status_snapshot>` disagree, if `.github/copilot-instructions.md`
pins a test count, if `docs/sprints/ACTIVE_SPRINT.md`'s refresh date falls >14 days behind the
latest main commit, if a hot doctrine file exceeds its size budget, or if a retired-world term
re-enters an always-loaded surface (small documented allowlist in the test). One-time cleanups
rot; this is the structure that keeps them clean — every frozen doc the 2026-07-18 audit found
had a retired role as its stated owner.

---

## 3. Baseline Management

- **The live figure lives in exactly two places:** §1's `LIVE_GATE_BASELINE` line and
  `CLAUDE.md <status_snapshot>`. The merging session that changes test counts updates BOTH in
  the same commit. Everything else (briefs, tickets, this doc's other sections,
  `.github/copilot-instructions.md`) POINTS at those two — pinning a count elsewhere is a
  governance violation, now gate-enforced.
- **Re-baselining scope rule:** when tests are added, removed, or reclassified, re-run the
  standing gate (branch AND merged main), capture the summary line in the commit/ticket, and
  update the two live-figure surfaces.
- **Baselines are evidence:** an eval baseline once encoded a parser bug as expected behavior.
  Cross-check baselines on substrate changes; re-measure known-fail cases at every hardware
  ceremony.
- Historic baselines (the growth chapters, the Sprint-8 named-scope tables, that era's accepted
  skips): [`docs/archive/testing/baseline_history.md`](archive/testing/baseline_history.md).

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
3. Adding a marker that changes default selection MUST update §1's live baseline line.
4. Marker names: lowercase, single word, descriptive.
5. Any new marker requires an update to this document.

---

## 5. Gate-Checking Order

All merges follow this order. Do not skip or reorder.

### Gate 1 — COMPILE

| Field | Value |
|-------|-------|
| Command | `python -c "import py_compile; [py_compile.compile(f, doraise=True) for f in ['file1.py', 'file2.py']]"` |
| Pass criteria | Zero compilation errors |
| Fail action | **STOP** — do not proceed to TEST gate |

### Gate 2 — TEST

| Field | Value |
|-------|-------|
| Command | The standing gate (§1), unless the work's brief names a different scope |
| Pass criteria | (a) Zero new failures; (b) pass count ≥ the live baseline; (c) no new skips without documented justification |
| Fail action | **STOP** — diagnose and fix before proceeding |
| Evidence | Capture the pytest summary line in the commit message and/or ticket |

### Gate 3 — REGRESSION *(test infrastructure changes only)*

Required when test files are added/removed/renamed, markers changed, or `pyproject.toml`
test config modified: re-run the standing gate on the merged tree and update §1's live
line if counts changed.

### Relationship to `.github/copilot-instructions.md`

That file is the compressed mirror for non-Claude coding agents. It carries the gate
COMMAND and points at §1 for the figure — it never pins a count (gate-enforced).

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
  receive the `slow` marker (module-level `pytestmark`) when they meet §4's criteria.
- No test should require manual setup or external state beyond what pytest fixtures provide.

### Coverage Expectation

No numeric coverage target (avoids over-engineering).

Gate rule: Every public function or class added or modified MUST have at least one test
exercising its primary (happy) path AND at least one test exercising its error/edge path.
This is enforced by code review, not by tooling.

---

## 7. Stale Artifacts

The historical root-level pytest snapshots (`pytest_baseline.txt`, `pytest_output.txt`,
`pytest_m53_gate.txt`, `pytest_m54_gate.txt`) were archived to `docs/archive/root-debris/`
on 2026-07-19 (#945 D6). They were never authoritative; the canonical source of truth for
all test baselines is this document's §1 live line.
