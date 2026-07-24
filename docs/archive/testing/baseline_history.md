---
title: Standing-gate baseline history (archived chapters)
status: reference
area: testing
---

# Standing-gate baseline history — archived chapters

*Plain summary: the per-merge baseline growth-log that used to live as nested "prior
chapter" paragraphs inside `docs/TEST_GOVERNANCE.md` §1 (violating that section's own
"do NOT append a chapter per merge" rule), plus the Sprint-8-era named-scope tables.
Moved here verbatim 2026-07-19 (#945 D4). The LIVE figure lives ONLY in
`docs/TEST_GOVERNANCE.md` §1 + `CLAUDE.md <status_snapshot>` — never here.*

## The growth-log chapters (verbatim, as they stood 2026-07-19)

> **CURRENT standing-gate baseline (2026-07-17 DAY session): 8490 passed / 0 failed / 0 skipped / 125 deselected** (clean env, models present, app down — measured on merged main `60b79687`, a full gate ran 0-failed after each merge). **Day-session growth 8430 → 8490:** #929 handoff-brief verifier (+0, out-of-gate, `c7bfd65e`) + #931 eval-model-dir override (+30 in-gate, `f3d4f583`) + #774-st4 spawn-doctrine gate (+12 in-gate, `79248f55`) + #727 web-search parse-guard (+18 in-gate, `60b79687`). **Prior chapter — 8430** (2026-07-17 overnight cluster #902 + #846-evals + #790-5, derived) — from the **measured 8402 passed / 0 failed / 28 benign skips** (21 model env-skips + 7 live-app `:5001` skips; the cluster gates ran detached-worktree with the post-battery AO still up) at merged main `90da3967`, four gate runs across the ladder (branch + after each merge: 8378 → 8396 → 8402, 0 failed throughout). Growth chain: 2026-07-16 evening = **8391** at `78f0342b` (measured ×8, main checkout, elevated, models present, app down); + #902 reconcile-identity + launcher tripwires (+15, merge `123bb8c3`; the launcher failure-path tests no longer compile the real 14B mid-gate) + #846 coordinator eval suite (+18, merge `7bed8a6c`, joins via SUITE_NAMES) + #790-5 probe-parity/canonical-package (+6, merge `90da3967`) = 8430. **Prior chapter — 8373** (2026-07-16, post-#107 dormant; derived from the measured 8352/0/21 #902-safe detached-worktree gate at merged main `c3c6fccd`; growth: post-#907/#911/#913 = 8325; + #900 instrumentation (+37) = 8362; + #107 draft-manifest-signing locks (+11, ships DORMANT behind require_signed_draft_manifest=false) = 8373; #267 doc-lifecycle + #14 credential-lifecycle doc were docs/tools-only; prior arc #906/#896/#909 + #907/#911/#913 web-search-security + mTLS-cache hardening). The 7 live-app(`:5001`) skips appear only when BlarAI is UP — both delta classes documented, both bar-neutral.
>
> *(Post-history addendum, recorded at archive time: 2026-07-18 Saturday arc measured **8518 / 0 / 0 / 125** ×4 — pre+post #107 enforcement, pre+post #853.)*

> **⚠️ Baseline currency (updated 2026-06-07, Sprint-16 close — gate-scope fold, LA-directed):** the
> per-scope counts in the named-scope table below are Sprint-8-era named-scope baselines and are **stale** (the suite
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
> `pytest` becoming the gate is unblocked.) Treat this scope as the authority; the named-scope rows
> awaited a re-measure pass.

## Sprint-8-era named-scope tables (archived verbatim)

| Scope | Command | Covers | Baseline |
|-------|---------|--------|----------|
| UNIT | `pytest shared/ services/ --tb=short -q` | `shared/`, `services/` (no launcher, no integration) | 755 passed, 2 skipped |
| FOCUSED | `pytest shared/ services/ launcher/ --tb=short -q` | `shared/`, `services/`, `launcher/` | 791 passed, 2 skipped |
| REGRESSION | `pytest shared/ services/ tests/ --tb=short -q` | `shared/`, `services/`, `tests/` (slow excluded by default) | 755 passed, 2 skipped, 80 deselected |
| FULL | `pytest -m "slow or not slow" shared/ services/ tests/ --tb=short -q` | All scopes including slow-marked integration tests | 835 passed, 2 skipped ⚠️ requires live runtime |
| SLOW | `pytest -m slow tests/integration/ --tb=short -q` | `tests/integration/` (slow-marked only) | 80 tests ⚠️ requires live runtime |

### Baseline provenance (2026-04-18, Task 6, Ledger Entry 38)

Branch `feature/p5-task6-test-governance`; main HEAD `103dfe6`; empirical runs of all scope
commands. FULL baseline (835/2) from Task 5 M5.5 (Entry 37); `-m "slow or not slow"`
override confirmed 2026-04-18.

### Pre-existing skips of that era (since resolved — the live gate runs 0-skipped clean-env)

`test_build_prompt_does_not_contain_no_think` and `test_stop_token_ids_constants_defined`
were permanently-skipped Task-4-era deferrals, accepted at the time.
