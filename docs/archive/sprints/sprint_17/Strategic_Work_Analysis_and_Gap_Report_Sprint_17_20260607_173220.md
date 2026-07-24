---
sprint_id: 17
sprint_name: "The Boot Cluster"
document_type: SWAGR
auditor: "Independent Sprint Auditor (Claude Opus 4.8, 1M context)"
audit_date: "2026-06-07"
vikunja_tracking_task_id: 628
sdv_path: "docs/sprints/sprint_17/strategic_design_vision.md"
sdv_version_reviewed: 1
scr_path: "docs/sprints/sprint_17/strategic_completion_report.md"
scr_version_reviewed: 1
auditor_session_fired_at: "2026-06-07T17:32:20-07:00"
sprint_window: "148f3e1 (SDV/baseline) .. 61f0daf (final merge)"
main_tip_reviewed: "61f0daf"
swagr_version: 1
overall_alignment_verdict: "STRONG_ALIGNMENT"
functional_impact_verdict: "MODERATE"
architecture_health_verdict: "IMPROVED"
test_baseline_reproduced: "2320 passed, 22 skipped, 108 deselected, 0 failed (51.56s) — independently re-run from the audit worktree with the .venv python, exit 0. NOTE: the SCR's 2340 passed / 2 skipped is the PROVISIONED-DEV-MACHINE split; in a clean worktree 20 model-dependent router tests + 0 (already-skipped on dev) symlink tests skip instead of passing. The reproducible invariant is 2342 selected (passed+skipped), 0 failed, 108 deselected. See §3."
criteria_summary: "C1-C6 MET for the buildable (gate) tier — independently verified + gate-green; C7 + C8 honestly PENDING the LA on-chip session (committed != done); C9 in progress (this SWAGR is one of its steps)."
gaps_count_critical: 0
gaps_count_major: 0
gaps_count_minor: 5
---

# Strategic Work Analysis and Gap Report — Sprint 17: "The Boot Cluster"

**Adversarial, independent, read-only.** Every load-bearing claim below was formed from the SDV (what was
promised), the git log + per-merge diffs (what was delivered), the shipped source + tests on disk, and a
gate I re-ran myself — **not** from the SCR's prose and **not** from any Orchestrator narration. Findings
carry per-claim citations (`file:line`, commit SHA, pytest test name + result). The SCR was read LAST and
its claims audited against my independent findings.

---

## 0. Auditor's stance + method

Default posture: **"something was probably missed — prove otherwise."** An uncomfortable critical read is
the intended product; a glowing rubber-stamp without specific citations would itself be a process failure.

**Independence (structural).** I did not read the Vikunja #628 narration comments or any chat transcript.
I read #628's *description* only (scope/metadata, via `get_task`) — it matches the SDV verbatim, no
narration leaked in. I formed my own view of the sprint window (`git log 148f3e1..61f0daf`, the seven
stream merges + the J-fix, the shipped source, my own gate run) before opening the SCR
(`strategic_completion_report.md`, uncommitted, read via absolute path at the end).

**The notable result, stated up front:** I agree with the SCR's per-criterion *gate-tier* verdicts
(C1–C6 MET; C7/C8 PENDING; C9 in progress) and that agreement is **earned, not deferred** — every
criterion below carries an independent citation, I reproduced the gate to a 0-failed result, and I
independently confirmed the two highest-risk honesty gradings (the staged/dormant egress air-gap, and the
hardware-tier committed-≠-done split). The five findings are all **MINOR** — four doc/record-precision
items and one pre-existing out-of-gate carry — none of which compromises the substance Sprint 17 shipped.

**What I ran (reproducible).**
- The standing gate: `pytest shared/ services/ launcher/ tests/integration/ tests/security/ -m "not
  hardware and not winui and not slow"` from the audit worktree with `C:/Users/mrbla/BlarAI/.venv/Scripts/python.exe`. Exit 0.
- The C2/C4/C5/C6 criterion files in isolation (skip-hunt) and the three `@hardware` tiers (deselection
  proof).
- The H-split seam class `TestExfilScreenSeamToEgressGuard` explicitly (RUNS-vs-skips proof).
- `git diff 148f3e1..61f0daf --stat` (full file inventory — nothing audited out of band).

**Test-data isolation confirmed active.** The rootdir `conftest.py:74-78` redirects `LOCALAPPDATA` /
`HOME` / `XDG_DATA_HOME` to a fresh `tempfile.mkdtemp("blarai-pytest-userdata-")` at import time, and
`tests/security/test_root_test_isolation.py` (3 passed) re-asserts it. No run touched the live
`%LOCALAPPDATA%`.

No commendations are included (project doctrine).

---

## 1. Overall alignment verdict — STRONG_ALIGNMENT

**Product lens (functional_impact_verdict: MODERATE).** Sprint 17 is a gate-enablement wave, not a
user-feature wave. It makes the **real production guest↔host boot path exist** (C1, the #615 AF_HYPERV
addressing fix + topology flip with a clean host fallback), **builds the decided egress machinery dormant**
(C3, ADR-027 — the air-gap is byte-for-byte unchanged this sprint), and **locks the burned boot/posture
seams with automation** (C2/C4/C5/C6). The user-facing capability set is unchanged on purpose; what
changed is that the #598 air-gap GO/NO-GO becomes a scripted audit rather than a manual boot marathon.

**Architecture lens (architecture_health_verdict: IMPROVED).** Three things improved structurally: (a) the
egress guard is now a real code-enforced control with a latched kill-switch + a no-circular-import
screener-registration seam (`egress_guard.py`), built and tested ahead of need rather than bolted on under
deadline; (b) the production boot cascade and the security cascade now have real-integrated-path locks in
the standing gate (C2, C4); (c) the offline key-recovery path — the decades-of-use break-glass — is a
sharply-scoped, auditable-in-isolation module (`recovery_key_store.py`) with a fresh-environment recovery
lock (C6). The DECISION_REGISTER was updated in-step for both ADR-027 and ADR-028 (the non-optional SSOT
maintenance rule honored — `DECISION_REGISTER.md:41-42, 63`).

**Gate-honesty lens.** The SCR's §1 honesty line is accurate and the structure enforces it: the five
hardware/real tiers (C1 real-VM, C2 model-loaded, C4 real-TPM, C7 ceremony+flip, C8 Sprint-16 baseline)
are BUILT + SCRIPTED and **not claimed green** — they are deselected from the gate by `@pytest.mark.hardware`
and homed to the one LA on-chip session. `require_signed_manifest=false` is still on disk everywhere, so
the C7 PARTIAL is real, not papered over.

The verdict is **STRONG_ALIGNMENT** rather than a bare ALIGNED because the delivered scope maps to the SDV
§4 criteria one-for-one with no silent substitutions, no scope drift against ADR-027/028, and the one
merge-gate defect (J) was caught and fixed correctly — and because the highest-risk claims (dormancy,
committed-≠-done) survived adversarial probing.

---

## 2. Per-criterion verdicts (C1–C9)

Tier convention from SDV §4: each criterion has a **gate tier** (buildable, must be green in the standing
gate) and, where applicable, a **hardware/deferred tier** (`@hardware`/`@slow`, first green = LA on-chip).

### C1 — #615 guest boundary — **MET (gate tier); real-VM tier correctly deferred**

The SDV promised: the Windows `AF_HYPERV` addressing bug fixed; the dormant path activated in
`vsock.py`/`transport.py`; the `launcher` topology flip wired with a clean fallback; a real-Hyper-V
round-trip test written (`@hardware`).

- **Addressing fix (defect 1).** `shared/ipc/vsock.py:75-117` adds `_hyperv_sockaddr()`, which builds the
  Windows `(VmId, ServiceId)` GUID pair and **fails closed** (`ValueError`) on a missing GUID — replacing
  the Linux `(str(cid), int_port)` shape winsock cannot parse. `VsockAddress` gains optional
  `vm_id`/`service_guid` fields (`:146-150`, backward-compatible). The socket is created with
  `HV_PROTOCOL_RAW` (proto=1) in both `connect()` (`:347`) and listener `start()` (`:593`).
- **Protocol fix (defect 2).** `services/ui_gateway/src/transport.py:576` creates the AF_HYPERV socket with
  `HV_PROTOCOL_RAW`; the comment at `:574` ("proto=HV_PROTOCOL_RAW is mandatory on Windows AF_HYPERV")
  documents the WSAEPROTOTYPE/WinError-10041 root cause. The two defects had masked each other while the
  path was dormant.
- **Topology flip with clean fallback.** `launcher/__main__.py:161-207` `resolve_gateway_topology()`:
  `HOST` returns `host_mode=True` **unconditionally** (the default is never overridden); `GUEST` flips to
  AF_HYPERV **only if** `_hyperv_transport_available()` (`:127-158`, a cheap probe) succeeds, else logs the
  downgrade and falls back to host-mode. Wired at `:1015`; the fell-back boot is recorded distinctly in the
  activation evidence (`gateway_topology` / `gateway_topology_downgraded`, `:1091-1097`) — a fell-back boot
  is never silently indistinguishable from a true host-mode boot. The AF_INET dev/host paths are untouched
  (`vsock.py:328-339`).
- **Tests.** Gate tier green: `shared/tests/test_ipc_transport.py` (the addressing/protocol groups),
  `launcher/tests/test_resolve_gateway_port.py::TestResolveGatewayTopology`,
  `tests/integration/test_guest_boundary_hyperv.py::TestGuestBoundaryHyperv::test_hyperv_address_is_validated_guid_pair`.
  The real-VM round-trip `...::test_hyperv_guest_host_round_trip` is `@hardware` and **deselected** from my
  gate (proven below, §4). Merge `19ded19`, source `142cbda`.

**Citation of honesty:** C1's real-VM tier is committed-≠-done and is correctly homed to the on-chip
session — no green-run claim is made for it in the gate.

### C2 — Full production-mode boot integration test — **MET (gate tier); model-loaded tier correctly deferred**

The composed production cascade (cert-mint → PA → AO → mTLS handshake → preflight → prompt → teardown)
against the post-#615 topology. `tests/integration/test_production_boot_integration.py` (merge `61f0daf`,
891 lines).

- **Gate tier executes, not skip-only.** `TestProductionBootCascadeGate` (5 tests) runs:
  `test_full_production_cascade_to_preflight` performs a REAL per-boot CA mint, a REAL
  `AssistantOrchestratorService.start(dev_mode_override=False)` in production posture with stand-in manifest +
  JWT CA + an mTLS listener (GPU stubbed), a REAL loopback+mTLS `check_pa_status()` handshake, and a REAL
  prompt round-trip with a stub reply, then a clean teardown (`test_production_boot_integration.py:54-75`
  documents each step). My isolated run: **5 passed, 0 skipped** in this class.
- **The hardware line is documented honestly and is a *fact*, not a capability decision.** The file's
  docstring (`:22-52`) explains that the AO production gate is satisfiable off-chip (manifest digest + JWT
  CA + mTLS, GPU stubbed) but the PA production gate is irreducibly TPM-bound (provisioned JWT + audit keys
  per ADR-025 §2.8(a) + real model). So the model-loaded PA-start + generation live in
  `TestProductionBootCascadeRealModel::test_full_production_cascade_real_model_and_tpm` (`@hardware`,
  deselected — proven §4), homed to on-chip/Sprint-18.

**Runtime-vs-pytest caveat (auditor):** this is a *composed-path* test with the GPU stubbed and the air-gap
UP. It proves the cascade composes when the production security gate is armed; it is **not** real-boot
evidence (no model load, no real PA TPM start, no real VM). The SCR does not conflate them — it explicitly
marks the model-loaded tier deferred. See §4 + §10.

### C3 — ADR-027 egress machinery (STAGED/DORMANT) — **MET; dormancy independently proven**

Merges `7034f9a` (H-a, egress-core) + `010bda6` (H-b, exfil-screen + PA carve-out). The four ADR-027 rules
are implemented as independent layers, all shipped dormant. I proved the air-gap is unchanged this sprint
(the load-bearing claim) — see §5 for the full dormancy proof. Summary of fidelity:

- **Rule 1 (allowlist, deny-by-default).** `egress_guard.allow_external_endpoint()` (`:609-643`) is the
  one-at-a-time widening mechanism; `_external_allowlist` is `set()` (empty, `:197`); **no runtime caller
  invokes it** (grep across `shared/ services/ launcher/` minus tests returns nothing — §5).
- **Rule 2 (PA auto-approve + log, off-list deny).** `gpu_inference.py:482-507` RULE 3
  `DENY_EXTERNAL_NETWORK` with the carve-out; `_EGRESS_ALLOWLIST = frozenset()` (`:368`, empty). The
  carve-out restricts auto-approval to http/https (`_EGRESS_CARVEOUT_SCHEMES`, `:382`) — ftp/ws/gopher stay
  denied even to an allowlisted host (a scheme-smuggling fail-open H-b self-caught + closed).
- **Rule 3 (kill-switch default-off, auto-trip, LA-only re-arm).** `_tripped = False` (`:184`); `trip()`
  (`:227`) latches; `rearm()` (`:269`) is a bare LA-only function on no automatic path; the guard
  auto-trips on an off-allowlist connect/bind/DNS (`_check_connect:380`, `_check_bind:409`,
  `_guarded_getaddrinfo:556`) and on a screener positive (`_screen_outbound:462`).
- **Rule 4 (exfil screen, block-on-detection).** `exfil_screen.screen()` (`:224-298`) reuses the canonical
  PGOV PII path + a credential layer (PEM/JWT/GitHub/Slack/Google/secret-assignment, `:137-165`), is
  fail-closed on undecodable/recognizer error, and reports labels+offsets only (never raw secret values).
  Registration is via the no-circular-import arm-hook seam (`register_arm_hook`/`register_screener`).
- **4 mechanism locks + activation doc.** `tests/security/test_egress_core.py` (635 lines, all pass),
  `tests/security/test_egress_screen.py` (339 lines, all pass), `docs/security/egress_activation.md` +
  `egress_machinery.md` ("what activates this / how to add an allowlist entry").

**Seam verified RUNS, not skips** — see §6.

### C4 — Security-cascade integration test (GAP-7) — **MET (gate tier); real-TPM tier deferred**

`tests/integration/test_security_cascade.py` (merge `bacd5f3`, 602 lines). Gate tier:
`TestSecurityCascadeSoftwareSealer` (2 tests, SoftwareSealer stand-in) — `test_full_security_cascade_software_tier`
+ `test_cascade_mtls_rejects_unrelated_cert`. My isolated run: **2 passed, 0 skipped**. The real-TPM tier
`TestSecurityCascadeRealTpm::test_full_security_cascade_real_tpm` is `@hardware`, deselected (§4).

**SCR side-claim flagged (MINOR-2):** the SCR §2/§4 asserts the real-TPM tier "ran GREEN on the reference
TPM during the build." I **cannot independently verify** this — the test is deselected and there is no
captured evidence artifact (stdout/exit-code/log) in the audited tree. The scorecard still correctly homes
the tier to on-chip/Sprint-18, so the *criterion grade* is unaffected; the parenthetical green-claim is an
unverifiable record item. See §4 + §9 MINOR-2.

### C5 — Production-posture runtime guard (GAP-12 / #600) — **MET; the J-fix is correct**

`tests/security/test_production_posture.py` (merge `475facd` + J-fix merge `22c2161`). My isolated run:
**12 passed, 0 skipped**. The runtime assertion — production posture (`dev_mode=False`) fail-closes at a
security-material gate, dev mode skips it — executes. The J-fix is a genuine gate-honesty catch, fully
analysed in §6. The runtime gate (`_validate_security_material`) was never wrong; the test premise was
environment-fragile and is now deterministic (asserts the invariant `AO_CFG_KGM_*` **or** `AO_CFG_JWT_CA_*`,
both reachable only past the `dev_mode` early-return).

### C6 — Offline key-recovery path (§5.5) — **MET**

Merge `873f5b5` (K). `shared/security/recovery_key_store.py` (315 lines) owns the recovery key material:
`generate()` (256-bit CSPRNG), `to_hex`/`to_display_groups` (operator transcription + truncated-SHA-256
transcription checksum), `parse_hex()` (fail-closed on wrong length / non-hex / checksum mismatch — never
truncates or pads), `redact()` (length + non-reversible fingerprint only). **No `save_to_disk`** — the raw
recovery key is never persisted by this module (deliberate footgun-avoidance, `:24-29`). `dek_envelope.py`
gains `unseal_via_recovery_hex()` (`+46` lines) routing the operator string through the single validated
parser and re-raising `RecoveryKeyError` as `DekEnvelopeError` so no key fragment leaks via a
differently-typed error. `tests/security/test_key_recovery.py` (546 lines, **34 passed**) includes the
fresh-environment (dead-chip) recovery-decrypts-real-at-rest-data lock. Stdlib-only (`secrets`, `hashlib`).

### C7 — #106/FUT-04 close (manifest ceremony + flip) — **PENDING (honestly)**

The runbook `docs/runbooks/manifest_signing_ceremony.md` exists (per SDV §7); the 4th TPM key + the
`require_signed_manifest=true` flip + a clean signed-manifest boot are the on-chip session. **Independently
confirmed PENDING:** `require_signed_manifest = false` in **all** config files (PA + AO, default +
guest_runtime — `services/{policy_agent,assistant_orchestrator}/config/{default,guest_runtime}.toml`) and
the code default is `False` (`entrypoint.py:101/239, :547/602`). #106/FUT-04 correctly stays **PARTIAL**.
This is committed-≠-done, marked as such. No overclaim.

### C8 — Sprint-16 deferred green baseline (#6(ii) boot-smoke + #621 GUI) — **PENDING (honestly)**

BUILT + SCRIPTED in Sprint 16; the first green run is the on-chip session, FIRST (lock-before-modify). No
green-run claim is made. Outside the buildable scope of this audit (these are dev-machine tiers); the SCR
homes them to on-chip step 1. PENDING is correct.

### C9 — Close hygiene — **IN PROGRESS (on track)**

- Gate green at a 0-failed result (my reproduction §3); zero regressions vs the 2212 baseline.
- SCR authored. This **independent Auditor SWAGR** is being delivered now (a C9 step).
- **Open close items (tracked in SCR §8, correctly unchecked):** fold the **8** sprint-17 journal fragments
  → `BUILD_JOURNAL.md` (still on disk, expected — fold happens at an uncontended tree, after the SWAGR);
  reconcile SECURITY_ROADMAP §5 gate-tracker; doctrine-currency sweep (the stale CLAUDE.md Phase-History
  row); ledger entry in `docs/ledger/`; close #628. #628 is correctly still open (`done: false`,
  `percent_done: 0.05`).

---

## 3. Independent gate reproduction

**Command (from the audit worktree root, `.venv` python):**
```
pytest shared/ services/ launcher/ tests/integration/ tests/security/ -m "not hardware and not winui and not slow" -q
```

**My result:** `2320 passed, 22 skipped, 108 deselected, 3 warnings in 51.56s` — **exit 0, zero failures.**

**The SCR claims** `2340 passed, 2 skipped, 108 deselected` and says "the 2 skips are the pre-existing
baseline skips." **The deselected count matches exactly (108). The passed/skipped split does NOT
reproduce in a clean worktree** — and the reason is the *same* worktree-vs-provisioned-machine seam the
J-fix documents:

| | passed | skipped | deselected | passed+skipped | failed |
|---|---|---|---|---|---|
| SCR (provisioned dev machine) | 2340 | 2 | 108 | 2342 | 0 |
| This audit (clean worktree) | 2320 | 22 | 108 | **2342** | 0 |

The 20-test delta is fully accounted for (I enumerated the skips with `-rs`):
- **20 × `services/semantic_router/tests/test_router.py`** skip with reason *"bge-small-en-v1.5 ONNX FP16
  model not available"* — the embedding model is not in a git worktree (same `models/` absence as the
  J-fix). On the provisioned dev box these 20 **pass**; in my worktree they **skip**.
- **2 × `shared/tests/test_runtime_config.py:84,104`** skip with *"Symlink creation requires elevated
  privileges"* — these are the 2 skips the SCR counts (they skip on the dev machine too, since the
  Orchestrator session was non-elevated). They are **pre-existing** (last touched Sprint 8 `f25e5b4`,
  present at baseline `148f3e1`).

**Auditor conclusion on the count.** There is **no regression and no hidden failure** — the invariant
(2342 collected-and-selected, 0 failed, 108 deselected) reproduces exactly. The SCR's *exact* "2340 passed
/ 2 skipped" figure is **environment-conditional** (it requires the embedding model present) and the SCR
states it as if universal. This is a record-precision MINOR (§9 MINOR-1), not a substance gap. **The
air-gap import control passed** (`tests/security/test_no_external_egress.py` → `..`, 2 passed).

Per-criterion isolated runs (skip-hunt), all from the audit worktree:
- C2+C4+C5+C6 files together: **53 passed, 3 deselected, 0 skipped** (the 3 deselected = the C2/C4 hardware
  tiers).
- C5 `test_production_posture.py`: **12 passed**. C6 `test_key_recovery.py`: **34 passed**.

---

## 4. Gate-honesty: the hardware tiers (committed ≠ done)

The SDV §8 conditions are **structurally enforced**, not merely promised. I proved the three `@hardware`
tiers are deselected from the gate by running them explicitly under the gate's `not hardware` filter:

```
pytest \
  tests/integration/test_guest_boundary_hyperv.py::TestGuestBoundaryHyperv::test_hyperv_guest_host_round_trip \
  tests/integration/test_production_boot_integration.py::TestProductionBootCascadeRealModel::test_full_production_cascade_real_model_and_tpm \
  tests/integration/test_security_cascade.py::TestSecurityCascadeRealTpm::test_full_security_cascade_real_tpm \
  -m "not hardware and not winui and not slow"
```
→ **`3 deselected`** (collected, not run). The hardware tiers exist as named tests and are correctly held
out of the gate.

| Tier | Test | Status in audit | Honesty |
|---|---|---|---|
| C1 real-VM round-trip | `test_hyperv_guest_host_round_trip` | `@hardware`, deselected | not claimed green — on-chip step 2 ✓ |
| C2 model-loaded | `test_full_production_cascade_real_model_and_tpm` | `@hardware`, deselected | not claimed green — on-chip/Sprint-18 ✓ |
| C4 real-TPM | `test_full_security_cascade_real_tpm` | `@hardware`, deselected | scorecard defers to on-chip ✓ — **but** SCR §2/§4 adds an unverifiable "ran GREEN on the reference TPM" side-claim (MINOR-2) |
| C7 ceremony+flip | (no test; runbook + flip) | `require_signed_manifest=false` on disk | PARTIAL, honest ✓ |
| C8 Sprint-16 baseline | (#6(ii) + #621) | dev-machine tiers | PENDING, honest ✓ |

**Verdict:** the committed-≠-done discipline holds. The one blemish is the C4 "ran GREEN on the reference
TPM" claim, which has no evidence artifact in the audited tree and cannot be reproduced by an auditor with
no TPM — recorded as MINOR-2.

---

## 5. Egress dormancy + the air-gap (the load-bearing C3 claim)

I treated "the air-gap is unchanged this sprint" as a claim to **disprove**. It survived:

1. **`egress_guard`'s live allowlist is loopback + vsock only.** `_allowed_families()` (`egress_guard.py:95-99`)
   = `AF_INET (+AF_INET6) + AF_HYPERV`; `_external_allowlist = set()` (`:197`, empty);
   `_is_allowlisted_external()` returns `False` whenever the set is empty (`:209-210`). A non-loopback
   `AF_INET` connect/bind hits `trip()` + `EgressDenied` (`:380-385`, `:409-413`); an external DNS query is
   denied (`:556`). **No external endpoint is in the live list.**
2. **`allow_external_endpoint()` has zero runtime callers.** `git grep "allow_external_endpoint" --
   shared/ services/ launcher/` minus tests returns **only** the definition + docstrings in
   `egress_guard.py` itself. Nothing in runtime code widens the allowlist. The mechanism exists; the door
   stays shut.
3. **The PA carve-out's allowlist is empty.** `gpu_inference.py:368` `_EGRESS_ALLOWLIST = frozenset()`.
   `_is_allowlisted_egress()` uses the class default unless a *test* injects one (`:416-420`), so in
   production every external URL falls through to `("DENY", "DENY_EXTERNAL_NETWORK")` (`:507`) — byte-for-byte
   identical to pre-sprint behavior.
4. **The kill-switch is default-off.** `_tripped = False` (`:184`); nothing arms a trip in normal boot.
5. **Importing the dormant modules has no side effects.** Neither `egress_guard` nor `exfil_screen` arms or
   registers itself at import; registration is explicit at `egress_guard.arm()` time via the arm-hook seam.
6. **The air-gap import control still passes.** `tests/security/test_no_external_egress.py` (2 passed) —
   the forbidden-import set (`requests/httpx/aiohttp/boto3/openai/anthropic/...`) is unbroken across all
   runtime roots; `urllib.parse` (used by the carve-out) is explicitly on the ALLOWED list (`:11-14`).

**Conclusion:** C3 is genuinely **STAGED/DORMANT**. The egress machinery changes no runtime egress behavior
this sprint; the air-gap stays welded. This matches ADR-027 §"Activation" (enforces only post-#598 +
post-#556 web features) and the SCR §7 dormancy claim.

---

## 6. The H-split seam + the J-fix

### H-split seam — verified RUNS (not skips) on merged main

The heaviest stream H was split H-a (egress-core) / H-b (screen). The risk: the seam test silently *skips*
(its `_require_egress_guard_interface()` calls `pytest.importorskip` + a conditional `pytest.skip` if
`register_screener`/`trip` are absent — `test_egress_screen.py:282-296`). On a clean worktree base that
skips; the claim is that on merged main (where H-a is present) it **runs**.

**I ran the class explicitly:**
```
pytest tests/security/test_egress_screen.py::TestExfilScreenSeamToEgressGuard -v
```
→ **3 passed** (0 skipped): `test_block_fires_egress_guard_trip` (a simulated SSN exfil through
`screen_and_enforce()` fires `egress_guard.trip()` exactly once with the block reason),
`test_clean_payload_does_not_fire_trip` (no false positive), `test_screen_registers_as_a_screener`. The
screen→trip seam genuinely exercises on merged main. The SCR §7 claim ("3/3 RUN+PASS") is **confirmed**.

### The J-fix — a TEST-premise defect, NOT a runtime regression (verified)

The SDV/§7 framed J's failure as a merge-gate catch; I verified it was the test, not the runtime.

- **Root cause (confirmed from the diff `b836818~1..b836818` + journal fragment
  `2026-06-07_sprint17-j-posture-fix.md`):** the original `test_assistant_orchestrator_production_security_gate_fires`
  constructed the AO against the shipped `default.toml` via `from_runtime_mode` and expected the Known-Good
  Manifest to be **absent** ("in the test tree"). True in a `git worktree` (no `models/`); **false** on the
  provisioned dev machine where `models/qwen3-14b/openvino-int4-gpu/manifest.json` is present — the gate
  correctly **accepted** the unsigned manifest under the staged-OFF `require_signed_manifest=false` (the
  *correct* pre-C7 behavior) and resolved cleanly → no raise → test failed on real main.
- **The runtime gate behaved correctly throughout.** The AO accepting an unsigned manifest under
  `require_signed_manifest=false` is the intended pre-C7 state (independently confirmed: the flag is `false`
  everywhere on disk — §C7). The fail-closed control `_validate_security_material` was never wrong.
- **The fix (diff confirmed).** The test now writes its **own** tmp_path config with NO JWT CA + NO manifest
  and asserts the **invariant** — fail-closes at `AO_CFG_KGM_*` **or** `AO_CFG_JWT_CA_*`, both reachable only
  past the `dev_mode` early-return — rather than a host-specific code. The dev-mode control test proves the
  method is skipped in dev. Deterministic on any host now.

**Auditor assessment:** this is the precise shape of seam the gate-honesty discipline exists to catch (a
worktree's emptiness standing in for a control), it was caught by the Orchestrator re-running the gate on
merged main (not trusting the builder's in-worktree green), and the fix is correct. This is **evidence FOR**
the project's merge-gate discipline, and it directly motivates §3's finding that the SCR's exact pass/skip
count is environment-conditional (the same seam, one layer over).

---

## 7. ADR-027 / ADR-028 fidelity (no re-litigation, no scope drift)

- **ADR-027 (egress).** The four rules are implemented exactly as decided (§3 C3 + §5): deny-by-default
  allowlist (rule 1), PA auto-approve-within-allowlist + log + off-list-deny (rule 2), kill-switch
  default-off + auto-trip + LA-only re-arm (rule 3), exfil screen block-on-detection (rule 4). The build
  **honors** the ADR's "NOT YET ACTIVE / enforces only when web features ship" status — shipped dormant.
  No rule was softened, no fork re-opened. The "held option" (hybrid per-action consent) was correctly NOT
  built (it is a future refinement, not the default). DECISION_REGISTER indexed (`:41`).
- **ADR-028 (attestation scope).** The ADR says security-material validation IS the #598 bar and **PCR
  measured-boot must NOT be built this sprint** (deferred to #627). **Independently confirmed:** `git diff
  148f3e1..61f0daf` has **zero** pcr/measured-boot/attestation file changes, and there is **no new PCR-read
  call** anywhere in `shared/ services/ launcher/` runtime. The sprint did not build PCR measured-boot. The
  `boot.py:9` comment overstatement the ADR flags is correctly left for #627 (not touched). DECISION_REGISTER
  indexed (`:42`).
- **The `021ffda` parallel governance commit.** This is the LA's SECURITY_ROADMAP restructure (#612 Capstone
  promoted to its own gate-phase 6, #598 sign-off → phase 7), NOT a sprint stream. It (and its sibling
  `452ac98` + the fragment `2026-06-07_612-gates-598-signoff.md`) landed in the window but is out-of-scope
  for the seven-stream audit. Its only effect on this SWAGR's §5/§6 surfaces is that the SCR §5 correctly
  reconciles against the post-`021ffda` doc — which it does. No conflict with the sprint streams.

---

## 8. Cross-sprint patterns (vs Sprint 16)

Read the Sprint-16 SWAGR (`...20260607_133305.md`, STRONG_ALIGNMENT, 0 CRITICAL / 0 MAJOR / 5 MINOR) for
recurring signatures.

1. **Gate-scope fold (Sprint-15 MINOR-5 → Sprint-16 MINOR-4) — CLOSED, and Sprint 17 is the beneficiary.**
   Sprint 16 flagged that `tests/integration/` was outside the standing gate so the production-parity lock
   never fired. That fold was **ratified at Sprint-16 close** (CLAUDE.md Active State + lesson 70): the gate
   now includes `tests/integration/ tests/security/` and `addopts` deselects `hardware+winui+slow`. **My
   Sprint-17 gate run used exactly that widened scope and the C2/C4 integration locks + C3/C5/C6 security
   locks all fired inside it.** The recurring relocate-not-close pattern is, for this lane, **genuinely
   closed** — a positive cross-sprint signal.

2. **SCR numeric-precision (recurring, milder each time).** Sprint 14/15/16 each had an SCR/record-precision
   MINOR (Sprint-16 MINOR-2: AutomationId "15" vs 24, "6 pyproject" vs 5). Sprint 17's recurrence is §3
   MINOR-1 (the "2 skips / 2340 passed" figure is dev-machine-conditional, not reproducible in a worktree).
   **Milder than Sprint 16** — the number is *correct on the dev machine*; it just isn't annotated as
   environment-specific. The pattern persists but is shrinking.

3. **Ledger-after-SWAGR sequencing (recurring, by design).** Sprint 14/15/16 each recorded the ledger entry
   landing after the SWAGR. Sprint 17 repeats it (SCR §8 ledger item unchecked). This is the accepted
   SWAGR-before-close ordering, not a defect — recorded for continuity (MINOR-3, identical disposition to
   Sprint-16 MINOR-1).

4. **SECURITY_ROADMAP "#787" stale header (Sprint-16 MINOR-3) — STILL OPEN.** `git grep "#787"` in
   `SECURITY_ROADMAP_air_gap_removal.md` = 4 occurrences. The #787≡#598 conceptual-ref reconcile flagged in
   Sprint 16 was **not** done in Sprint 17. Recurs as MINOR-4 (pre-existing, ≡#598 already documented inline).

5. **#626 `tools/tests/` collection errors (Sprint-16 MINOR-5) — STILL OPEN, correctly out-of-scope.**
   Reproduced: `pytest tools/tests/ --collect-only` → **4 errors during collection**
   (`test_v_matrix_v6_mcp_project_id.py`, `test_v_matrix_v7_cross_project_byte_identity.py`,
   `test_vikunja_client_scope.py`, +1). The SDV §5 explicitly named #626 out-of-scope and the SCR §6 carries
   it forward. Not a Sprint-17 regression (MINOR-5).

6. **No assignment-in-place-of-assertion** in any of the six new Sprint-17 test files (grep for `assert X =`
   returns nothing) — the test-quality smell the Sprint-16 auditor checked is absent here too.

**Net:** the highest-value cross-sprint pattern (gate-scope relocation) is **closed**; the residual patterns
are doc-currency carries, all honestly surfaced, none compromising substance.

---

## 9. Findings (CRITICAL / MAJOR / MINOR)

**0 CRITICAL, 0 MAJOR, 5 MINOR.**

- **MINOR-1 — SCR gate-count is dev-machine-conditional, stated as universal.** SCR §3/§frontmatter:
  "2340 passed, 2 skipped" with "the 2 skips are the pre-existing baseline skips." In a clean worktree the
  reproducible result is `2320 passed, 22 skipped` (20 router-model tests skip without the embedding model;
  same `models/`-absence seam as the J-fix). The invariant (2342 selected, 0 failed, 108 deselected)
  reproduces exactly. *Disposition:* at close, annotate the SCR (and the CLAUDE.md test-baseline line if it
  inherits the figure) that the exact pass/skip split assumes the provisioned dev machine (embedding model
  present); the auditable invariant is "2342 selected / 0 failed / 108 deselected." Evidence: my run §3.

- **MINOR-2 — C4 "ran GREEN on the reference TPM" is an unverifiable side-claim.** SCR §2 (C4 row) + §4
  (item 5) assert the real-TPM tier already ran green during the build; there is no captured evidence
  (stdout/exit/log) in the audited tree and the test is `@hardware` (deselected). The criterion grade is
  unaffected (the scorecard defers the tier to on-chip), but the green-claim cannot be reproduced.
  *Disposition:* either capture the TPM-run evidence artifact (a dated log under `phase2_gates/` or
  `docs/performance/`-style record) into the tree, or soften the SCR wording to "expected to pass on the
  reference TPM; first recorded green = on-chip/Sprint-18." Pairs with the community-grade testing-data
  rule. Evidence: §4 table.

- **MINOR-3 — Ledger entry lands after the SWAGR (recurring, by design).** SCR §8 ledger item unchecked at
  SWAGR time. *Disposition:* author the Sprint-17 ledger close entry in `docs/ledger/` (per-file, DEC-17)
  at close so it is not dropped — identical to Sprint-16 MINOR-1. Evidence: SCR §8; `docs/ledger/` has no
  sprint-17 entry yet.

- **MINOR-4 — SECURITY_ROADMAP "#787" stale header persists (pre-existing; Sprint-16 MINOR-3).** 4
  occurrences of "#787" remain in `SECURITY_ROADMAP_air_gap_removal.md`; #787≡#598 is documented inline but
  the header/§refs were not reconciled in Sprint 17's §5 touch. *Disposition:* reconcile "#787" → "#598" in
  the close-sweep (a doc-currency edit, non-optional per the hardening-follow-ups rule). Evidence:
  `git grep -c "#787"` = 4.

- **MINOR-5 — #626 `tools/tests/` collection errors persist (pre-existing; Sprint-16 MINOR-5; explicitly
  out-of-scope).** 4 collection errors in `tools/tests/`, outside the gate. *Disposition:* keep the tracking
  ticket open; not gate-blocking, not a Sprint-17 regression. Evidence: `pytest tools/tests/ --collect-only`
  → 4 errors.

**Honesty note (process):** I record these five rather than rubber-stamp, but I want the weight calibrated —
all five are doc/record-precision or pre-existing-carry items. The substantive surfaces I tried hardest to
break (egress dormancy / air-gap, the committed-≠-done hardware split, the H-split seam, the J-fix being a
test-not-runtime defect, ADR-028 no-PCR) **all held** under adversarial probing.

---

## 10. Recommendations for Sprint 18

1. **(Orchestrator/LA, close)** Action MINOR-1 + MINOR-2 + MINOR-3 + MINOR-4 at the Sprint-17 close: annotate
   the SCR's count as dev-machine-conditional; resolve the C4 TPM-green claim (capture or soften); land the
   ledger entry; reconcile "#787"→"#598". MINOR-5 stays a tracked ticket.
2. **(LA on-chip, the one batched session — the gating prerequisite for #598)** Run, in SDV §7 order: C8
   first (Sprint-16 boot-smoke #6(ii) + GUI #621, lock-before-modify) → C1 real-Hyper-V round-trip → C7
   ceremony + `require_signed_manifest=true` flip + clean signed boot (closes #106) → C2 model-loaded tier →
   C4 real-TPM tier. **Until these are green, C1/C2/C4/C7/C8 are committed-≠-done** — the #598 GO/NO-GO
   cannot proceed on the gate-tier alone. Capture each run's evidence (community-grade where it is a
   model/HW run), per the testing-data-capture rule.
3. **(Sprint 18 scope)** The pre-gate production-posture SWAGR sweep + GAP-5/6/8/9 model-loaded automation
   (SDV §5 out-of-scope, named for Sprint 18); then the #612 Capstone phase (now SECURITY_ROADMAP phase 6
   per `021ffda`); then the §5.12 #598 sign-off (phase 7). Egress (#556) and PCR measured-boot (#627) remain
   post-gate.
4. **(Auditor, durable)** Promote the "SCR exact pass/skip count is provisioned-machine-specific; auditor
   reproduces only the selected/failed/deselected invariant in a worktree" pattern to the Auditor lessons —
   it has now recurred (the J-fix seam, one layer over) and will recur every sprint that adds model- or
   privilege-dependent tests. The reproducible gate contract is **0 failed + deselected-count + selected-count**,
   not the absolute passed number.

---

## 11. Verdict summary

| Criterion | Gate tier | Hardware/deferred tier | Auditor verdict |
|---|---|---|---|
| C1 #615 guest boundary | MET (`19ded19`) | real-VM `@hardware`, deselected | **MET (gate); tier honestly deferred** |
| C2 production boot integration | MET (`61f0daf`) | model-loaded `@hardware`, deselected | **MET (gate); tier honestly deferred** |
| C3 ADR-027 egress (dormant) | MET (`7034f9a`/`010bda6`) | — (post-#556) | **MET; dormancy independently proven** |
| C4 security cascade (GAP-7) | MET (`bacd5f3`) | real-TPM `@hardware`, deselected | **MET (gate); TPM-green side-claim = MINOR-2** |
| C5 production-posture guard | MET (`475facd`+`22c2161`) | real-boot `@slow` | **MET; J-fix correct (test-not-runtime)** |
| C6 offline key-recovery | MET (`873f5b5`) | (optional real-TPM round-trip) | **MET** |
| C7 FUT-04 ceremony+flip | — | on-chip | **PENDING (honest; flag=false on disk)** |
| C8 Sprint-16 green baseline | — | on-chip | **PENDING (honest)** |
| C9 close hygiene | in progress | — | **IN PROGRESS (on track)** |

**Overall: STRONG_ALIGNMENT.** 0 CRITICAL / 0 MAJOR / 5 MINOR. Gate reproduced to 0 failures
(2342 selected / 108 deselected). The buildable scope (C1–C6) is delivered, merged, and gate-green; the
hardware tiers (C1/C2/C4/C7/C8) are honestly committed-≠-done and homed to the one LA on-chip session that
is now the #598 gating prerequisite.

**Refs:** SDV `docs/sprints/sprint_17/strategic_design_vision.md`; SCR `docs/sprints/sprint_17/strategic_completion_report.md`;
ADR-027, ADR-028; Sprint-16 SWAGR `docs/sprints/sprint_16/Strategic_Work_Analysis_and_Gap_Report_Sprint_16_20260607_133305.md`;
sprint window `148f3e1..61f0daf`; journal fragments `docs/journal_fragments/2026-06-07_sprint17-*.md`; #628, #615, #600, #627, #106, #607, #626.
