---
sprint_id: 16
sprint_name: "The Automation Wave — Production-Parity Test Lane + Gate-Critical Hardening (parallel)"
predecessor_sprint_id: 15
vikunja_tracking_task_id: 624
start_date: "2026-06-07"
target_completion_date: "2026-06-09"   # \~1-2 days agent wall-clock; LA estimate, not a hard deadline
sdv_version: 2
status: "SIGNED — LA-approved 2026-06-07 (Gate:Approved); v2 (LA-review additions folded)"
orchestrator_drafted_on: "2026-06-07"
la_approved_on: "2026-06-07"   # LA sign-off via docs/handoffs/sprint16-sdv-v2-review-response.md; the commit landing this frontmatter is the durable signature
---

# Strategic Design Vision — Sprint 16: The Automation Wave (Production-Parity Lane + Gate-Critical Hardening)

## 1. Executive brief

Sprint 16 **front-loads the test automation** that turns the rest of the air-gap-removal campaign from a
manual boot-and-check marathon into *a scripted run plus a human sign-off*. It is the direct answer to
the Sprint-15 finding that production-only seams slip past a green unit suite (BUILD_JOURNAL lesson 56;
`TEST_GOVERNANCE` §2.7): build the production-parity test lane + the GUI automation now, and the security
tiers after them self-verify. In the same wave — because the working sets are genuinely disjoint — it
lands two gate-critical hardening items: **full weight integrity (FUT-04 / #106)** and **dependency
pinning**, plus two read-mostly audits that give the campaign a verified state-tracker.

Per the LA's ratified planning decisions (2026-06-07), this sprint also **builds (does not yet activate)**
the **signed model-weight manifest** that the #598 gate now requires, and it does so behind the
mechanism-then-activate discipline proven in Sprint 15. The single on-chip ceremony this implies — a
4th TPM (Trusted Platform Module) key, `BlarAI-Manifest-Signing` — is **staged for a later batched
session**, not run this sprint, keeping the LA's Sprint-16 terminal time to essentially zero. When that
ceremony does run, it ships with a **non-developer runbook** and the Orchestrator drives it live, one
command at a time (the LA's novice-operator constraint, made a definition-of-done item).

Executed as **6 concurrent streams** — 4 worktree builder subagents + 2 read-mostly audit agents —
under the Orchestrator's serial merge gate (the cf-program Orchestrator + specialist-subagent shape;
the autonomous fleet stays LA-paused). Their working sets were **verified disjoint on disk** (2026-06-07,
3-way parallel survey). "Done" = the GUI + boot-path + key-transition automation lands in the local
suite, weight integrity covers every manifest entry, the signed-manifest machinery is built + staged +
tested + runbook-ready, deps are pinned, and the campaign has a verified §5 gate-tracker + a coverage
gap-list. The air-gap **stays up**; **#598 remains the GO/NO-GO gate** — this is Tier-2/Tier-3 hardening
+ the automation force-multiplier, one wave toward the gate, not the gate itself.

## 2. Context

### 2.1 Predecessor sprint outcome

- Predecessor SCR: `docs/sprints/sprint_15/strategic_completion_report.md` (COMPLETE — 8/8 SDV criteria
  MET; independent SWAGR `STRONG_ALIGNMENT`, 0 CRITICAL / 0 MAJOR / 6 MINOR, all dispositioned; production
  activation + cold-reboot continuity live-verified on-chip 2026-06-06/07).
- Sprint 15 flipped the running default to production posture (per-boot mTLS, dev-mode-off, audit-TPM +
  JWT signing live). Its defining lesson — *a green suite that mocks the boundary is not coverage of the
  boundary* — is **the reason this sprint leads with automation**.

### 2.2 Repo state at kickoff

- Main branch HEAD: `58eb28e` (Sprint-15 continuity addendum); tree clean except pre-existing leave-them
  files (a dirty `docs/guide-workstreams/README.md`, untracked perf/benchmark JSONs, `.worktrees/`).
- Live test baseline: **2172 passed, 2 skipped, 15 deselected** (Layer-A; `pytest shared/ services/
  launcher/ -m "not hardware and not winui and not slow"`).
- Open Vikunja `Gate:Pending-Human`: this sprint's tracking task **#624** (pending this SDV's sign-off).
- Known-active feature branches: none (clean `main`; all Sprint-15 EA branches merged).

### 2.3 External inputs driving this sprint

- **Strategic plan:** `docs/sprints/FORWARD_EXECUTION_PLAN_to_598.md` (outgoing-session survey, adopted).
- **LA decisions (binding, ratified 2026-06-07):**
  - **D-1 (FUT-04 scope):** the **signed manifest IS gate-required** for #598 — a 4th TPM ceremony
    (`BlarAI-Manifest-Signing`). Not hash-verify-only.
  - **D-2 (#615 gate-scoping):** the real guest↔host AF_HYPERV VM boundary (#615) **must land before
    #598** — not deferred to land with #556. (Scopes Sprint 17, not Sprint 16.)
  - **D-3 (novice-operator, NON-OPTIONAL):** every on-chip ceremony ships a non-developer runbook + the
    Orchestrator drives it live (one command at a time, paste-the-output); ceremonies are batched into as
    few sessions as possible.
- **Verified-on-disk survey (2026-06-07)** — corrections folded into scope below: the manifest-signing
  *machinery already exists* (so Builder B is lighter than the plan implied); #615 is an *addressing-fix +
  flip + verify*, not a one-liner (Sprint 17); **there is no CI infrastructure** and the GPU-dependent
  tests cannot run on a cloud runner (see §5.3 / §9 — "CI" here means the local suite + a dev-machine
  gate run).
- **User-memory invariants:** production posture is the only "works" for #598; mature-not-minimal;
  parallel-by-default across disjoint working sets; escalate capability/quality/security-posture
  decisions, proactively fix defects; make the operator's hands-on surface tiny + guided.

## 3. Sprint purpose

The Sprint-15 live-verify drove out ten production-only defects one boot at a time, at the LA's terminal,
because the green suite mocked the seams. `TEST_GOVERNANCE` §2.7 made "test the real integrated path" a
mandate — but a mandate with **near-zero standing enforcement** (no CI; only two static posture locks).
This sprint pays that testing debt: the production-parity lane (#619) and the GUI harness (#621) become
the automated coverage of the boot cascade + the rendered UI, so the security tiers after them — and the
#598 gate audit itself — self-verify in the local suite + a dev-machine run instead of a manual marathon.

Because that automation work is disjoint from two gate-critical hardening items, the wave also lands them
in parallel: **full weight integrity** (today only one model file is hash-checked at load; the gate needs
every manifest entry verified **and**, per D-1, a TPM-signed manifest) and **dependency pinning** (the
security-critical deps are currently unbounded across six `pyproject.toml`). Two read-mostly audits round
out the wave: a **verified §5 gate-tracker** (the roadmap checklist is stale — it lists shipped controls
as remaining) and a **coverage gap-list** (the umbrella audit #622 asks for).

If we skipped this sprint: the mock-passes-prod-crashes class keeps recurring at the LA's terminal
through Sprints 17–18; the #598 gate audit stays a manual marathon; and two gate-critical hardening items
(weight integrity, signed manifest) remain open with no automation to verify them.

## 4. Success criteria

1. **GUI harness extended (A / #621).** The pywinauto Layer-C harness (`tests/harness/`) is grown from
   its current 2 scenarios to the full critical-path list (app-launch/connect, session-list render incl.
   quarantined rows, send-prompt→stream→render, PGOV display, session lifecycle, thinking/streaming,
   document/provenance, voice, settings, degraded states), with `AutomationProperties.AutomationId`/`x:Name`
   added where missing. *Verification: the stub-backend tier (Layer C, `winui` marker) green on the dev
   machine; a model-loaded tier defined (combining #563 Layer B + C) and runnable; runbook for the
   dev-machine run.* **The model-loaded GUI tier is BUILT + runnable + runbooked this sprint; its run is
   batched/deferred — and when it runs it is a SCRIPT (pywinauto drives the window, never the LA clicking),
   so "zero LA terminal time this sprint" holds (Confirmation 2, LA review 2026-06-07).**
2. **Weight integrity — every manifest entry (B / #106 half a).** `verify_weight_integrity` is invoked
   over **all** entries in the manifest at load in BOTH `gpu_inference.py::load_model()` paths (PA + AO),
   not just `openvino_model.bin`. *Verification: a test that a swapped/extra/missing `.bin` relative to
   the manifest fails closed; the load-time sweep iterates the manifest digests.* **#106/FUT-04 is ADVANCED, not closed, by this
   sprint — the gate-critical closure (a real TPM-signed manifest enforced on the LA's hardware) is the
   later batched ceremony; #106 stays OPEN at Sprint-16 end and Stream E's §5 tracker marks weight
   integrity PARTIAL (Confirmation 1, LA review 2026-06-07).**
3. **Signed-manifest mechanism — built + STAGED, not activated (B / #106 half b).** The existing
   `manifest_signer.py` / `provision_manifest_signing_key.py` machinery is wired into the boot
   precondition cascade; `BlarAI-Manifest-Signing` is added to `ceremony_preflight.py`; the shipped
   default stays `require_signed_manifest=false` (no brick window) with production cleanly resolvable to
   `true` via a staged signal; fail-closed when `require_signed=true` and the signature is absent/invalid.
   *Verification: four mechanism locks — (a) shipped default still permits unsigned (with the WARNING);
   (b) a production/required signal resolves `require_signed=true`; (c) `require_signed=true` + missing
   `.sig` fails closed; (d) `require_signed=true` + valid stub-signed manifest boots clean (off-chip
   stub signer). The on-chip ceremony + the live flip to `true` are a later batched LA step (§5.2).*
4. **Manifest-ceremony novice runbook (B / D-3, NON-OPTIONAL).** A non-developer runbook
   (`docs/runbooks/` or `docs/sprints/sprint_16/`) for provisioning `BlarAI-Manifest-Signing` + signing
   the manifest: ≤ \~3 copy-paste full-path commands, public-only output (fingerprints/hashes),
   idempotent + clobber-guarded, fail-closed, "you never edit code," low-stakes framing — same standard
   as `EA4_ceremony_runbook.md`. *Verification: the runbook exists and the ceremony is one-command +
   idempotent; the Orchestrator can drive it line-by-line.*
5. **Dependency pinning (C).** Security-critical dependencies across the six `pyproject.toml` are pinned
   or upper-bounded (+ hash-verify where the toolchain supports it), without breaking the 2172 baseline.
   *Verification: the pins present on `main`; the full Layer-A suite still green; a short rationale note.*
6. **Production-parity lane, part 1 (D / #619) — TWO locks.** **(i)** Key-transition + sealer-stand-in
   tests that exercise the **real integrated** store/boot path (dev→prod key transition serves-not-bricks
   across BOTH stores; `SoftwareSealer` stand-in for the production cascade) land in the local suite.
   **(ii) Boot-cascade smoke lock — pulled earlier per LA review (2026-06-07):** a lightweight, automated,
   **headless, model-loaded** smoke that boots the production cascade (per-boot cert mint → service
   handshakes → the model-loaded prompt-flow preflight) **to the preflight passing, then tears down — no
   GUI, no LA babysitting** — landing as a dev-machine regression lock on the CURRENT (Sprint-15) working
   cascade, so Sprint 17's #615 + egress changes modify it **with the lock already in place**
   (lock-before-modify — the precise pain this automation push exists to kill). The builder picks the
   cleanest mechanism (a headless boot-to-preflight hook, or driving the cascade's component functions);
   the goal is to lock the regression-prone seams, not a specific entry point. *Verification: (i) the tests
   green, each asserting behaviour at the seam (not a mocked boundary), dev→prod as an explicit integration
   test; (ii) the smoke runs green against the current cascade — a one-command, **SCRIPTED** dev-machine
   run, BUILT this sprint with its green-baseline run batched at the Sprint-16 close / Sprint-17 kickoff (no
   babysitting). Honest scope (§5.3): the FULL production-mode boot integration test (covering the new
   #615/egress behaviour) stays Sprint-17 part 2; Sprint 16 lands the lightweight smoke-to-preflight lock on
   the cascade as it works today.*
7. **Tier-1 state reconciliation (E / §2a).** Every `SECURITY_ROADMAP` §5 gate criterion AND every TPM
   key is walked and confirmed against actual on-disk state; §5 becomes the authoritative tracker
   (verified, not inherited). *Verification: §5 updated — shipped controls (hash-chained TPM-signed audit
   stream, measured-boot ordering) marked done; genuinely-remaining Tier-1 items (PII-filter posture,
   measured-boot **attestation policy**) flagged; the 3-provisioned / 1-unprovisioned TPM key state
   recorded.*
8. **Coverage audit (F / #622).** Every major subsystem mapped → has a real-integrated-path test? at
   what fidelity? → a prioritized gap list that seeds Sprints 17+. *Verification: the coverage-audit doc
   on `main` with the per-subsystem table + the gap list.*
9. **No regressions; merge-gate held; working sets stayed disjoint.** Full Layer-A suite green on the
   integrated `main` (≥ 2172 + the sprint's own tests); every builder branch diff-reviewed + tests
   **re-run by the Orchestrator**; the branch-guard (`git branch --show-current == main` + toplevel) held
   before every main-tree merge. *Verification: the closing-session live suite run; the merge-gate record.*

## 5. Scope

### 5.1 In-scope (the 6 streams)

| # | Stream | Work | Ticket |
|---|---|---|---|
| **A** | GUI harness | Extend pywinauto Layer-C to the full critical-path list + automation IDs; define the model-loaded tier; runbook | #621 |
| **B** | Weight integrity + signed-manifest mechanism + ceremony runbook | Multi-entry weight verify at load (PA+AO); wire + STAGE `require_signed_manifest` + add the key to ceremony_preflight; mechanism locks; the novice runbook | #106 |
| **C** | Dependency pinning | Pin/upper-bound security-critical deps across the 6 `pyproject.toml` (+ hash-verify where supported) | Tier-3 |
| **D** | Production-parity lane (part 1) | Key-transition + sealer-stand-in integration tests in the local suite | #619 |
| **E** | Tier-1 reconciliation | Walk every §5 criterion + TPM key, confirm on-disk, make §5 the authoritative tracker (read-mostly) | §2a |
| **F** | Coverage audit | Map every subsystem → real-integrated-path test? → prioritized gap list (read-mostly) | #622 |

### 5.2 Out-of-scope (deliberately deferred) — each with its home

1. **The on-chip manifest ceremony EXECUTION + the live flip to `require_signed_manifest=true`** — BUILT
   + STAGED here; the LA runs the ceremony + the activation in a **later batched on-chip session**
   (candidate: alongside the Sprint-17 #615 Hyper-V boot, to minimise separate sessions per D-3). The
   signed manifest must be active by the #598 gate (Sprint 18), not by Sprint-16 end.
2. **#615 guest-boundary (AF_HYPERV)** — Sprint 17 (the serial Boot Cluster); per D-2 it lands before
   #598. Real work = a Windows AF_HYPERV addressing fix + the `launcher/__main__.py:927` topology flip +
   a real-Hyper-V verify boot.
3. **Tier-3 egress** (runtime raw-socket guard + PA-mediated carve-out + kill-switch arming) — Sprint 17;
   needs the egress-policy decision (a Sprint-17-kickoff LA decision).
4. **The FULL production-mode boot integration test (#619 part 2)** — Sprint 17, written against the
   stabilised post-#615/post-egress boot. *(A LIGHTWEIGHT boot-cascade smoke-to-preflight lock on the
   current cascade is pulled into Sprint 16 — criterion #6(ii) — per LA review, so the cascade is locked
   before Sprint 17 modifies it.)*
5. **A self-hosted CI runner** — *optional, later*. The lane delivers its value in the local suite + a
   dev-machine gate run (§5.3); a self-hosted runner is an enhancement, not a Sprint-16 dependency.
6. **#598 GO/NO-GO + the #612 capstone** — Sprint 18.
7. **#623 gateway method rename** — held (a 35-file rename on `transport.py` is collision-prone for low
   value; a quick solo task between sprints).

### 5.3 Scope boundaries and gate-honesty conditions

- **"CI" means the local suite + a dev-machine gate run, NOT a cloud pipeline.** No `.github/workflows/`
  exists and the model-loaded/GPU tests need the Arc 140V, which cloud runners lack. The production-parity
  lane (D) and the GUI harness (A) run as: the fast/deterministic/stub tier in every local `pytest` run;
  the model-loaded/hardware tier on the dev machine; a full dev-machine run is the pre-#598 "gate-SWAGR"
  automation. Claims are scoped exactly to that — no "runs in cloud CI" phrasing.
- **Signed manifest is BUILT + STAGED, not activated, this sprint.** The shipped default stays
  `require_signed_manifest=false` (unsigned permitted with a loud WARNING) so no boot can brick before
  the ceremony; the live flip is the later batched LA step. (Mirrors the Sprint-15 mechanism-vs-activation
  split.)
- **Weight-integrity covers the manifest's entries** (the `.bin` files in the deployed model dir), not a
  claim of "all conceivable weights"; the manifest is the source of truth for what's checked.
- **The two read-mostly streams (E, F) are audits**, not builds — they produce a verified tracker + a gap
  list, not code. They are parallel-safe (no code collision).
- **No new runtime dependencies** without LA approval (Stream C *pins* existing deps; it adds none).

## 6. Deliverable summary

| Deliverable | Type | Target location | Criterion |
|---|---|---|---|
| Extended Layer-C GUI scenarios + automation IDs + model-loaded tier + runbook | test + code + doc | `tests/harness/test_winui_*`, `services/ui_winui/` XAML | #1 |
| Multi-entry weight-verify at load (PA + AO) + test | code + test | `services/*/src/gpu_inference.py`, `shared/models/weight_integrity.py` | #2 |
| Signed-manifest mechanism wired + staged + 4 locks | code + test | `services/*/config/default.toml`, `*/entrypoint.py`, `shared/security/ceremony_preflight.py` | #3 |
| Manifest-ceremony **novice runbook** | doc | `docs/runbooks/` or `docs/sprints/sprint_16/` | #4 |
| Dependency pins + rationale | config + doc | the 6 `pyproject.toml` | #5 |
| Key-transition + sealer-stand-in integration tests | test | `tests/`, `services/ui_gateway/tests/`, `services/assistant_orchestrator/tests/` | #6 |
| Verified §5 gate-tracker | doc | `docs/security/SECURITY_ROADMAP_air_gap_removal.md` §5 | #7 |
| Coverage gap-list | doc | `docs/sprints/sprint_16/` (or `docs/`) | #8 |
| SCR + ledger close | doc | `docs/sprints/sprint_16/`, `docs/ledger/` | (all) |
| BUILD_JOURNAL fragments | doc | `docs/journal_fragments/` | (all) |

## 7. EA milestone plan

| Stream | Working title | Depends on | Working-set (verified disjoint) | Size |
|---|---|---|---|---|
| **A** #621 | GUI harness extend | uses D's fixtures | `tests/harness/test_winui_*`, `services/ui_winui/*.xaml(.cs)` | M/L |
| **B** #106 | Weight integrity + signed-manifest mechanism + runbook | main | `weight_integrity.py`, both `gpu_inference.py::load_model`, `ceremony_preflight.py`, `manifest_signer.py` wiring, `*/config/default.toml`, the runbook | M |
| **C** Tier-3 | Dependency pinning | main | the 6 `pyproject.toml` (+ a check) | S |
| **D** #619 | Production-parity lane pt.1 | main | `tests/harness/fakes.py`+`scenarios.py`, `services/*/tests/test_*_decrypt_resilience.py`, `shared/security` sealer/dek | M |
| **E** §2a | Tier-1 reconciliation | main | `SECURITY_ROADMAP` §5 (read-mostly across security/ + launcher/) | S (read-mostly) |
| **F** #622 | Coverage audit | main | a new coverage doc (read-mostly across the repo) | S (read-mostly) |

**Coordination assignments (assign, don't race) — the only touchpoints:**
- **D owns `tests/harness/fakes.py` + `scenarios.py`; A owns `tests/harness/test_winui_*`.** A imports
  from D's fixtures → **D merges first**, A builds on the merged fixtures.
- **C and B both reference config**, but different files (C: `pyproject.toml`; B: `default.toml`) — no
  overlap.
- Everything else is pairwise disjoint (verified survey, §8.4).

**Sequencing within the wave (LA review 2026-06-07):** **Stream E (the §5 reconciliation) starts
first/early** — it is read-mostly + fast, so if it surfaces a gate criterion that is NOT actually done (a
stale-checklist surprise), the LA + Orchestrator learn it BEFORE the wave finishes, not at merge. The four
code builders + F launch concurrently; E reports an early first-pass.

## 8. Dependencies and prerequisites

### 8.1 Upstream dependencies
- The Sprint-15 production posture on `main` (the cascade B/D build against). `cryptography` present.
- The existing manifest-signing machinery (`manifest_signer.py`, `provision_manifest_signing_key.py`) —
  confirmed present 2026-06-07; B wires + stages it rather than building it.

### 8.2 External dependencies
- A real **TPM 2.0** for the *eventual* manifest ceremony (a later batched LA session — NOT this sprint).
- The Arc 140V GPU + an interactive Windows desktop for the model-loaded GUI tier (dev-machine only).

### 8.3 Assumed invariants
- The `tests/harness/` Layer A/B/C structure + `fakes.py`/`scenarios.py` are stable (D extends, A consumes).
- `load_manifest_verified(require_signed=…)` + the boot precondition cascade are stable (B wires into them).
- The two coordination assignments hold (no builder edits another's owned file).

### 8.4 Parallel-Sprint Authorization & disjointness matrix (the "max parallel" answer)

**Single-sprint, 6 internal streams** (no concurrent *other* sprint). Disjointness verified on disk
2026-06-07:

```
        A(GUI) B(FUT04) C(pins) D(#619) E(§5) F(cov)
A(GUI)   —
B(FUT04) DISJ   —
C(pins)  DISJ  DISJ     —
D(#619)  COORD DISJ    DISJ    —          (A imports D's fixtures → D merges first)
E(§5)    DISJ  DISJ    DISJ    DISJ   —    (read-mostly)
F(cov)   DISJ  DISJ    DISJ    DISJ  DISJ  —  (read-mostly)
```

**Execution model:** 6 builders/auditors run concurrently; the **merge gate is serial** (each branch
diff-reviewed + tests re-run by the Orchestrator, one at a time — the deliberate quality bottleneck). The
branch-guard fires before every main-tree merge (the cwd-branch hazard scales with parallel worktrees —
lesson 52). Read-mostly E/F merge as docs (lighter review).

## 9. Risks and unknowns

### 9.1 Known risks

| Risk | Prob | Impact | Mitigation |
|---|---|---|---|
| The staged `require_signed_manifest` mechanism accidentally bricks boot before the ceremony | Low | High | Shipped default stays `false` (unsigned permitted + WARNING); the flip is a later LA step; mechanism lock (criterion #3a); same discipline as the Sprint-15 dev-mode flip |
| 6-way parallel worktrees worsen the cwd-branch hazard | Med | Med | Branch-guard before every merge; merge-gate serial; coordination assignments prevent file races |
| "CI" over-claimed — implying a cloud pipeline that can't run GPU tests | Med | Med | §5.3 condition: claims scoped to the local suite + dev-machine gate; named in the SCR |
| The multi-file weight sweep surfaces weights not in the manifest (or a stale manifest) | Med | Med | Treat a manifest/dir mismatch as fail-closed; E's reconciliation cross-checks the manifest |
| A coordination race (A edits D's fixtures, or vice-versa) | Low | Med | Explicit ownership (§7); D merges first; the merge-gate catches a cross-edit |

### 9.2 Known unknowns
1. The exact set of `.bin` files in the deployed model dir vs. the manifest (B + E resolve at load).
2. Which GUI critical-path scenarios need new automation IDs vs. already resolve `x:Name`→AutomationId
   (A determines).
3. Whether dependency pins surface a transitive conflict on the 2172 baseline (C resolves; full suite is
   the gate).

### 9.3 Unknown-unknowns posture
The production-parity lane (D) is *built to surface seams the unit suite missed* — so it may itself turn
up new production-only gaps (a key-transition path that bricks, a sealer-stand-in mismatch). That is the
lane doing its job; treat anything it surfaces as a defect to fix (proactively) or escalate (if it's a
posture decision), exactly as Sprint 15's live-verify did. We assume we have NOT found every seam by
reading code; the lane's first green run is the real test.

## 10. Alignment to long-term roadmap

- **Phase 5 Post-Operational Development; Tier-2/Tier-3 gate-critical + the automation force-multiplier**
  on the air-gap-removal campaign toward **#598**.
- **Use Case alignment:** UC-001 (PA) + UC-004 (AO) — the weight integrity + the GUI harness protect the
  two operational use cases; the coverage audit (F) maps all 9.
- **ADR alignment:** ADR-018 (TPM trust root — the manifest key), ADR-020 (egress kill-switch — armed,
  Tier-3 egress is Sprint 17), ADR-025/026 (the at-rest + per-boot-mTLS posture the lane tests). No new ADR
  required (the manifest-signing decision is a *scoping* ratification, recorded here + on #624; if the
  staged-flip design warrants it, a short ADR amendment is authored at merge).
- **DEC alignment:** `TEST_GOVERNANCE` §2.7 (the mandate this wave operationalises); DEC-15 sprint lifecycle.

## 11. Roles and accountability

| Role | Responsibility this sprint | Budget |
|---|---|---|
| **LA** | This SDV sign-off; CAR adjudication; SCR + SWAGR read. **No on-chip ceremony this sprint** (staged). | \~30–60 min interactive |
| **Orchestrator** | EA prompt authoring; serial merge-gate (diff + re-run); the novice-runbook standard enforced on B; SCR | Autonomous within the merge gate |
| **Builder subagents (A–D)** | Stream execution in isolated worktrees (model sonnet) | Per-stream, merge-gated |
| **Audit agents (E, F)** | Read-mostly reconciliation + coverage map | Per-stream |
| **Auditor** | Independent SWAGR at close (manual spawn; fleet paused) | Autonomous per DEC-15 |

## 12. Estimated effort
- **Duration:** \~1–2 days agent wall-clock (6 concurrent streams; serial merge-gate is the pacing item).
- **LA active-time:** \~30–60 min (sign-off + any CARs + SWAGR read). **Zero on-chip terminal time this
  sprint** — the one ceremony is staged for a later batched session (a deliberate novice-friendly property
  of this wave).
- **Confidence:** Medium-High — the working sets are verified-disjoint and most pieces are extend-not-build
  (the manifest machinery + the harness already exist); the main variables are the multi-file weight sweep
  and whatever the production-parity lane's first run surfaces (§9.3).

## 13. Deliberate non-goals
1. **Running the manifest ceremony this sprint** — *built + staged*; the on-chip step is batched later
   (novice-friendly + no brick window).
2. **A cloud / self-hosted CI runner** — the lane delivers in the local suite + a dev-machine gate; a
   runner is optional-later.
3. **#615 / egress / the production boot test** — Sprint 17 (the serial Boot Cluster).
4. **Claiming "CI-verified" beyond the local suite + dev-machine run** (§5.3).

## 14. Sign-off

### Lead Architect
> I, blarai, have reviewed this SDV on `<date at sign-off>`. I approve the Sprint-16 scope, the 6-stream
> parallel execution, the success criteria, and the risk posture — including: D-1 (signed manifest
> gate-required, built+staged this sprint with the on-chip ceremony batched later), D-2 (#615 before #598,
> Sprint 17), and D-3 (every ceremony ships a non-developer runbook + is Orchestrator-driven). I accept
> the §5.3 gate-honesty conditions (CI = local suite + dev-machine run; signed-manifest staged-not-
> activated; weight-integrity covers the manifest's entries). I will sign the SDV (a commit on `main`),
> read the SCR + SWAGR, and run the batched on-chip ceremony when it is prepared and runbooked.

_(Signed via the `la_approved_on` frontmatter + a commit on `main`. Until then this SDV is DRAFT /
`Gate:Pending-Human` on #624; no builders are dispatched.)_

### Orchestrator
> The Orchestrator will translate this signed SDV into the A–F prompts under the serial merge gate, hold
> the §5.3 honesty conditions + the staged-flip discipline + the novice-runbook DoD, manage the two
> coordination assignments, and escalate any scope deviation via a CAR or the merge gate.

---

## Appendix A — SDV revision log

| Version | Date | Changed by | Change summary |
|---|---|---|---|
| 1 | 2026-06-07 | Orchestrator (draft) | Initial draft from the FORWARD_EXECUTION_PLAN + the 2026-06-07 on-disk verification survey + LA decisions D-1/D-2/D-3. 6-stream parallel Automation Wave; signed-manifest built+staged; #615 deferred to Sprint 17; CI-reality + novice-runbook conditions baked in. Pending LA sign-off. |
| 2 | 2026-06-07 | Orchestrator (post-LA-review) | LA review additions (sign-ready): (a) criterion #6 expanded with a **boot-cascade smoke lock** pulled earlier — lock the Sprint-15 cascade before Sprint 17's #615/egress modify it; (b) #106/FUT-04 explicitly **advanced-not-closed** (stays open; §5 shows partial); (c) model-loaded tiers confirmed **scripted + dev-machine + batched** (zero LA terminal time holds); (d) Stream E sequenced **first/early**; (e) §5.2 item 4 clarified (lightweight smoke pulled in). The `update_task` field-wipe tool-bug tracked at #625 (interim: pass all fields). No change to the 6-stream shape, the serial merge-gate, the staged-manifest no-brick design, or the novice-runbook DoD. |
