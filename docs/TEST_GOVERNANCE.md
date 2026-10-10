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

**Fast form (development and merges):** `python scripts/run_standing_gate.py` runs the SAME selection as 6 concurrent
pytest processes over disjoint groups of whole files (the fixed-port files alone afterwards), prints one combined
line, and exits 3 if the groups ran a different number of tests than the single collection found. About 12 minutes
against about 24 for the sequential form; use `--groups 3` while you work at the machine. The sequential form above
remains the definition of the bar and the only form that yields a timing figure (rule 8).

**Bar:** 0 failed, 0 skipped in a clean environment. A skip is investigated, never waved
through. Always redirect `LOCALAPPDATA` (§2.6); run from a TERM-bearing shell with no
`PYTHONIOENCODING` override (the PowerShell tool shell false-fails 3 tests — bash is the
proven runner).

> *Older per-merge stamps are rotated to*
> [`docs/archive/test-governance-baseline-history.md`](archive/test-governance-baseline-history.md)
> *(2026-08-08, when this file breached its 40,000-byte budget). Nothing was deleted; the
> retractions and corrections are there in full.*
>
> ### How to run a gate so the figure means something
>
> Accumulated the hard way; moved here from the `CLAUDE.md` snapshot on 2026-09-20 because
> that bullet had grown into a paragraph, which its own staleness rule names as rot.
>
> 1. **A GATE IS A MEASUREMENT.** Nothing else heavy on the box, and never against a live
>    battery. One loaded run took 21:32 against ~10:00 quiet, and an earlier one produced a
>    failure that took three sessions to diagnose (#1597).
> 2. **PREDICT THE FIGURE BEFORE RUNNING IT** — and **predict the SKIP column too.** A run
>    read 11658 passed / 3 skipped against a predicted 11661 / 0. The total reconciled, so it
>    looked green, and it hid an env-skip that could never lift (#1594). Three consecutive
>    merges had confirmed the pass count exactly while nobody predicted the other column.
> 3. **CAPTURE FULL OUTPUT.** Summarise for display, never the reverse. A `tail`ed gate
>    discards the traceback, which cost three sessions one misdiagnosis each (#1597).
> 4. **NEVER EDIT THE TREE MID-GATE.**
> 5. **A WORKTREE FIGURE IS NOT THE BASELINE.** Reconcile as
>    `branch_passed + skipped + failed = primary_passed` and write the prediction down first.
>    At `eb0af7db` the worktree reads 11671/2/26 against the primary's 11699.
> 6. **STATE ELEVATION WITH EVERY FIGURE.** 0 skipped is the elevated reading; a non-elevated
>    run reads 3 — the symlink delta. Assistant DOWN; up adds 7 port-5001 skips.
> 7. `.venv/Scripts/python.exe`, bash, stamp start→finish.
> 8. **A TIMING FIGURE COMES FROM THE INSTRUMENT.** `scripts/gate_timing_runner.py` starts a run only after 15 minutes of
>    input idle on AC power with a quiet CPU, samples idle, power and CPU through the run, and voids it on any input,
>    non-AC sample, second test runner or silent log. A hand-started run is a correctness run: its wall-clock is not a
>    figure. Run-to-run spread on this machine, measured with it: 1.4 % (09-22 tree) to 3.5 % (current).
> 9. **TRIMMING THE GATE.** A speed-up that keeps every test in is made freely (the installer batching, #1699). A test leaves the
>    standing gate only by the operator's decision. The parallel form keeps every test in (#1707, rule 10).
> 10. **A PARALLEL FIGURE NAMES ITS GROUP COUNT** and is not comparable with a sequential one. Real checkout, 13288 tests, elevated, app down:
>     3 groups 848.7 / 894.6 / 894.1 s; 6 groups 704.3 / 700.8 / 708.6 s; sequential about 1450 s. Whole files only, in collection
>     order within a group (some tests leave module state a later test expects clean, which sequential order had hidden: #1707);
>     files that bind the fixed ports 5000/5001 run alone after the parallel phase.

> **LIVE_GATE_BASELINE: 13317 passed / 0 failed / 3 skipped / 620 deselected**
>
> *(**MERGED `main` at `ce925cf2`, REAL checkout**, 2026-10-09, 20:04 to 20:16 -04:00, **NON-ELEVATED** (the 3 skips are the
> symlink delta; the elevated reading of this tree is predicted 13320 / 0 / 0 and has not been taken), app down, `LOCALAPPDATA`
> redirected, `scripts/run_standing_gate.py` (6 groups + serial tail): 13317 passed / 0 failed / 3 skipped / 620 deselected in
> 695.9 s; 13320 = 13302 + 9 tests from the #1716 merges + 9 from #1718 (arm 1 bundle self-tests for four scripts on two
> hosts, one python self-test, one rules-corpus lock); counted by collection before the run. The same form read 13313 / 0 / 3
> at `642edeb8` (671.5 s) and 13317 / 0 / 3 at `14e5d442` (603.3 s); at `8559fd79` it read 13316 / 1 / 3, the one failure
> being the liveness flake ticketed as #1720, which passed alone 3 of 3 and in every other run.
> The previous stamp (`ea7ee8c3`, 13302 tests, **ELEVATED**, 2026-10-08 07:30 to 07:42 -04:00): 13302 passed / 0 failed / 0 skipped / 620 deselected in
> 698.0 s; the same form at `dda7e90a` (13288 tests) ran three times in a row: 704.3 s, 700.8 s and 708.6 s. 13302 = 13288 + 13 tests
> (#1707 follow-ups) + 1 timeout-registry case; counted by collection before the run.
> The previous stamp (`c5b83a31`, 13253 tests) was the SEQUENTIAL form, idle-controlled by `scripts/gate_timing_runner.py`:
> 1448.0 s. The 09-22 tree read 703.0 s and 693.0 s and the pre-batching tree 1631.7 s and 1687.2 s in worktrees, same box.
> Parallel runs were not idle-controlled (the operator may have been at the machine). Data and method:
> `docs/performance/gate_runtime_2026-10-07/`. Older stamps: `docs/archive/test-governance-baseline-history.md`.)*
>

> **READ THE SKIP COLUMN BEFORE COMPARING.** The elevation of the figure above is stated in its
> parenthetical and decides what the skip column should read: an ELEVATED run reads **0 skipped**;
> a NON-ELEVATED run of the same tree reads **3 skipped**, the documented symlink skips (rule 6),
> benign ONLY because they are named. Reconcile elevated and non-elevated readings as
> `non_elevated_passed + 3 = elevated_passed` before calling either stale.
> A branch WORKTREE reads lower again by the gitignored-asset skips (rule 5: the worktree figure
> plus its skips must reconcile to the elevated total); a WORKTREE FIGURE IS NOT THIS NUMBER.
> A live app adds 7 port-5001 skips. An unexplained skip is a defect, never a rounding error.
>
> Earlier per-merge entries and their lessons (prediction by collection, the skip column, the nested-checkout
> walk, the 21:32 loaded gate, retractions) are in `docs/archive/test-governance-baseline-history.md`; rules 1-9 above
> carry what they taught.

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
- Rules-tooling slow tier (`tests/security/test_git_*.py`, per-test marks via `_git_hook_helpers.mark_slow_except`): `pytest tests/security -m slow -k "git_rules or reference_transaction or git_native or git_hooks or git_install or git_update or git_swap"` (~45 min). Run before changing the guard, hooks, installer or CLAUDE.md git rules; at least monthly.

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
