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

> *Older per-merge stamps are rotated to*
> [`docs/archive/test-governance-baseline-history.md`](archive/test-governance-baseline-history.md)
> *(2026-08-08, when this file breached its 40,000-byte budget). Nothing was deleted; the
> retractions and corrections are there in full.*
>
> **LIVE_GATE_BASELINE: 10845 passed / 0 failed / 0 skipped / 133 deselected**
> *(**CONFIRMED on merged `main`**, 2026-08-09, **started 04:59:07, finished 05:05:13**
> local, **362.82 s** — assistant STOPPED, no dispatch, no battery. **+2 over 10843**:
> `6e7a15bd` (#1352 — a dispatch-asset nicety crashed the Assistant Orchestrator and cost
> the 2026-08-08 night; it degrades to no-asset now).*
>
> *This baseline is stamped after a RED gate, and the red is the lesson. Three
> `test_image_placement.py` tests failed at 04:56 with nothing about the grader changed:
> they asserted exact figures against `~/projects/battery-b9-pottery-site`, which the
> overnight battery had rebuilt. **A working directory the fleet rewrites is
> evidence-by-reference, and the reference moved while the tests slept** — capability 16
> (#1318) committed by tests written to enforce it. Retargeted to a dated
> `repos-archived/` snapshot with byte-identical findings. The rule: assert exact numbers
> only against immutable artifacts.*
>
> *Previous: **10843** @ `88a634eb` — (2026-08-08, **started 22:04:53, finished
> 22:12:28** local, **450.47 s** — primary checkout, assistant STOPPED, no dispatch, no
> battery. **+33 over 10810**: `c9fc9633` (#1349, +5 — the grader stopped calling the
> operator's own photographs pipeline waste) and `88a634eb` (#1348, +28 — requirement
> coverage can finally see a website; the assessor globbed `*.py` and then reported "no
> seeded job oracle" while a `.mjs` one sat in the same directory).*
>
> *A merge lesson banked with the figure: the first #1348 merge at 21:55 took only the
> branch's FIRST commit, because I merged while its agent was still working. The second
> commit — the reachability tests proving the node path is reached at BATTERY CLOSE, not
> just from `assess_run` — landed in a second merge. Merging a branch whose author has not
> reported is merging a moving target.*
>
> *Previous: **10810** @ `e8038c95` — (**CONFIRMED on merged `main`**, 2026-08-08, **started
> 21:00:01, finished 21:07:40** local, **455.06 s** — the CONFIRMING run, stamped rather
> than the 20:50:48 run that carried the same count but FAILED on the grammar gate; a
> baseline must cite the run that actually passed. Primary checkout, models
> present, assistant STOPPED, no dispatch and no battery live (the guard's own pattern —
> image AND invocation form — returned 0 driving processes). **+86 over 10724**, from the
> evening's second arc: every instrument that publishes a verdict now has to say what it did
> not measure.*
> - *`83633ce0` (#1342 item 2, +19, `test_oracle_qa_measurement_honesty.py`) — the QA record
>   reported `findings_total: 0` beside `f2p_baseline: "not-run"`. `findings_conclusive` is
>   now false whenever any producing stage did not run.*
> - *`74257ce7` (#1345, +38, `test_image_placement.py`) — grades where a site's pictures
>   LAND. Catches the operator's own two remaining complaints on the real delivery.*
> - *`ca742a99` (#1346, +24, `test_morning_website_section.py`) — the morning report names
>   the site built last night, or says why it cannot.*
> - *`95e007be` (lesson 33's owed control, +5,
>   `test_graders_disclose_what_they_did_not_measure.py`) — deny-by-default: a module that
>   publishes a findings total must carry some way to say a check did not run. Found zero
>   real offenders; it is a ratchet against the next one, proved able to fire by planting one.*
>
> *This run FAILED once before passing, and the failure was worth having:
> `test_coder_dod_grammar.py` rejected a `Status: STARTED` line written into capability 12
> earlier the same evening. STARTED is not in the legend, and PARTIAL was the honest word
> anyway — one reviewed delivery is a data point, not the published rate the row asks for.
> The grammar gate caught a status claim that had drifted past its own legend.*
>
> *Previous: **10724** @ `75e8e24f`, 2026-08-08 19:48:05→19:55:09, 419.62 s, **+69 over
> 10655**, from two merges that give the delivered PRODUCT its first automated examination:*
> - *`32a9ed1f` (#1345, +26, `shared/tests/test_link_lint.py`) — every href/src in a
>   delivered site resolved against the root a server actually mounts. The operator found a
>   broken "View Details" button by hand in under a minute that four gates had passed;
>   nothing was asking whether a link's target existed. Advisory, not a gate: a regression
>   lock proves a broken site and a clean site produce identical verdicts.*
> - *`75e8e24f` (#1343, +43, `tests/integration/test_battery_website_presentation.py`) — a
>   website battery run now ends by leaving him a record and a double-click launcher, after
>   every measurement has landed. Fail-open by design in this one place, proved
>   byte-identical across seven forced failure paths.*
>
> *Previous: **10655** @ `462c55cb`, 2026-08-08 18:37:54→18:43:50, 353.32 s, **+81 over
> 10574**, from the evening's three merges, all of them locks on instruments that were reporting
> passes they had not measured:*
> - *`4a51fb5e` (#1342, +38, `shared/tests/test_oracle_qa_node.py`) — node oracles skipped BOTH
>   execution-stage probes unconditionally, so a website was exactly the case where nobody
>   checked whether the exam could fail. Fail-to-pass baseline + static vacuity for node.*
> - *`7821bab4` (#1342, +19, `test_already_satisfied_precheck.py` 16→35) — an oracle never shown
>   capable of failing may no longer delete work from the plan.*
> - *`462c55cb` (#1341, +27, `tests/integration/test_battery_evidence_capture.py` and its
>   `live_dispatch` witness) — the scorecard cited a mutable file as evidence and stamped a
>   pre-build commit count as a run property.*
>
> *Measured AFTER all three merges, so it is the merge tree's own figure, not inherited from any
> branch. Each of the three ships its refusal case (principle 12): the #1342 precheck lock was
> toggle-proven by forcing its probe to `return True` — 14 locks fail, while the
> still-skips test keeps passing, so the suite tells "correctly gated" from "broken outright".*
>
> *(prior — CONFIRMED on merged `main` @ `0ea1f32b`, 2026-08-08, 14:31:48→14:37:38, 346.57 s,
> **10574**; +9 over 10565, all `test_failure_taxonomy.py`, #1324's honesty split.)*
>
> *(prior — CONFIRMED on merged `main` @ `be0ad99b`, 2026-08-07, 23:28:25→23:33:57, 325.96 s,
> **10565**.)*
>
> *(**RE-MEASURED on the resolved merge tree** of `docs/dod-ratification-20260807` × `main@49e4cb18`,
> 2026-08-07, **started 23:21:58, finished 23:27:32** local, **327.66 s** — worktree
> `blarai-wt-dod-rat` at model parity, venv interpreter, AO stopped, no battery live. **The
> re-merge was CLEAN — no conflicts in this file or in the `CLAUDE.md` snapshot**, contrary to
> the landing brief's expectation, because the branch already carried main's measurement history
> and the four commits main gained since (`cce07cc6`, `43e30e59`, `a6bfd39a`, `49e4cb18`) touched
> neither. The figure the files already carried was therefore MEASURED rather than inherited —
> a clean merge of two independent baseline edits is precisely the case the doctrine-freshness
> gate cannot catch, since it compares the two documents to each other and never to reality.*
>
> *(**MEASURED on the merge tree** of `docs/dod-ratification-20260807` × `main@bcaf2cd7`,
> 2026-08-07, **started 19:56:24, finished 20:04:43** local, **490.93 s** — dedicated worktree
> `blarai-wt-dod-rat` at model parity (junction-completed; an earlier same-tree run skipped ONE
> test, `test_benchmark_kv_cache_sweep.py`, on a missing linked model file — completed, re-run
> 27/27, then clean full runs only), venv interpreter, AO stopped (launcher pid 9752 stopped
> 19:21 for the gate window, restarted after the post-merge confirmation), no dispatch, no
> concurrent gate. **+13 over 10552**, all of it `tests/security/test_coder_dod_grammar.py` —
> the DoD status-grammar gate ratified with capability 11 (#1325): status presence on all 21
> rows, legend vocabulary, LIVE-requires-dated-citation, acceptance-test Executed lines, four
> checker fail-proofs and one conforming-pass proof, plus 2 beyond-range hardening tests from
> the pre-merge review. Reconciles across tonight's three parallel arcs:
> 10526 + 21 (#1327) + 5 (#1324) + 13 = 10565. Deselected unchanged at 133.*

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

**Structural spawn-surface ratchet (#774 sub-task 4, 2026-07-17).** `tests/integration/test_no_new_raw_spawn_sites.py` is a deny-by-default gate in the standing selection: it AST-scans production `shared/` / `services/` / `launcher/` code and FAILS LOUD if any raw `subprocess.*` / `os.spawn*` / `os.system` call site is not in its documented allowlist, forcing new spawns through the blessed `shared/procspawn.py` helper (the lesson-219 Windows-stdio scar family). The allowlist is a ratchet — it only shrinks as #774 sub-task 2 migrates the known `shared/fleet/*` sites onto the helper. Test trees and `procspawn.py` itself are scoped out (documented in the test's SCOPE note). **API scope (N2):** the gate covers the `subprocess.*` call family and the `os` spawn/exec/system family only; deliberately OUT of current scope — spawn paths it does not see — are `ctypes` Win32 `CreateProcess`/`ShellExecute`, `os.startfile`, and `asyncio.create_subprocess_exec`/`_shell` (none used on the current surface; a future need for one is a deliberate extension of the gate's API sets, never a silent gap).

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
