---
sprint_id: 18
sprint_name: "The Pre-Gate Sweep"
document: SWAGR (Strategic Work Analysis and Gap Report) — independent adversarial audit
swagr_role: "Independent Auditor (manual opus spawn; fleet LA-paused). Conducted in PRODUCTION POSTURE to double as the §5.1 #598 gate criterion (C5)."
audited_against: "docs/sprints/sprint_18/strategic_design_vision.md §4 (C1–C7), §7 (automate-first), §8 (gate-honesty)"
main_head_at_audit: "61f2e8c (close) — Sprint-18 merges P f6193d1 / O 798c8a1 / M b1d7c96 / N be75335 / C1-fix dedf341"
authored_on: "2026-06-08"
reproduced_gate: "2342 passed, 0 skipped, 0 failed, 113 deselected (102.25s) — project .venv"
reproduced_c1: "PASS (production posture, dev_mode=False, real Qwen3-14B, real mTLS, signed-manifest boot) — 30.29s"
section_5_1_determination: "QUALIFIED-YES"
---

# Sprint 18 SWAGR — "The Pre-Gate Sweep" (independent adversarial audit)

## Verdict

**STRONG_ALIGNMENT** — six of seven criteria MET with agent-run green and the
seventh (C3) honestly scored **PARTIAL** because the work *falsified its own
premise* (the AO→router wiring it was meant to test does not exist) and escalated
the decision (#632) instead of forcing a green. The standing gate and the C1
production-posture round-trip were **independently reproduced** by this Auditor and
match the team's claims exactly. No overclaim, no fail-open, no built-into-nothing,
no gate-honesty violation was found. The one material gate-scoping caveat is on the
**§5.1 determination** (§ below): the production-posture *verification mechanism* is
proven and C1 is green in production posture, but §5.1's literal text ("Tiers 1–3
**complete** AND independently SWAGR-verified in production posture") rests on
upstream tier-completion facts this Auditor flags as **QUALIFIED**, not a clean
unconditional YES.

## Executive summary

Sprint 18 set out to make the real BlarAI system end-to-end automation-verifiable
under production posture with the model loaded, so the #598 gate's §5.1
production-posture check becomes a scripted fleet run rather than a manual
boot-and-click marathon. It delivered that: a genuine `dev_mode=False` + real mTLS +
signed-manifest model-loaded round-trip (C1), a model-loaded IPC-routing regression
lock (C2), a real-gateway TUI test (C4), and a deterministic gate baseline restored
by a real teardown-leak fix with a fail-loud detector (C6). The model-loaded
@hardware tiers were agent-run on the Arc 140V with community-grade evidence
captured — the proof of the #629 automate-first reframe.

The adversarial findings are limited and almost entirely to the project's credit:

- **C3 is the headline honesty test, and it passed it.** The SDV's C3 criterion
  ("the real bge-small router invoked *inside a real AO turn*, proving the AO→router
  wiring") is **not satisfiable as worded** — the wiring does not exist. This Auditor
  independently grepped `services/assistant_orchestrator/src/` and confirms zero
  `SemanticRouter` / `.classify()` calls. The team did not dress this up: the test
  proves the *testable* surface (real router loads + classifies via real ONNX; a real
  AO turn runs; the cross-service path doesn't crash), the docstring states plainly
  that the router "is today a standalone service rather than being directly called
  inside `_handle_connection`," C3 is scored PARTIAL (not PASS), the perf JSON labels
  it "AO→router wiring absent," and the finding is escalated to #632 (which exists and
  is a rigorous write-up). This is the correct disposition of a falsified premise.

- **The gate and C1 reproduce exactly.** The standing gate is `2342 passed / 0
  skipped / 0 failed / 113 deselected`. C1 in production posture PASSES with the real
  14B, `dev_mode=False`, real `CERT_REQUIRED` mTLS, and `require_signed_manifest=true`
  reaching the detached-`.sig` verification. Both reproduced from `main` with the
  project `.venv`. The C6 leak detector did **not** false-fire on the clean gate run
  (free→free silent pass held).

- **No overclaim on C2/C4.** C2 explicitly stays `dev_mode=True` to hold the wiring
  constant while varying real-model-vs-stub, and explicitly defers production mTLS to
  C1 — faithful to the SDV (C2's criterion does not require production posture; that is
  C1/C5). C4 uses a real `TransportGateway` + real AO listener with a stub GPU
  (SDV-permitted: "stub-GPU acceptable") and asserts streaming + PGOV-approved +
  session persistence over the real seam; the denial path is honestly noted as
  not-exercised.

Findings: **0 CRITICAL, 0 MAJOR, 5 MINOR** (all dispositioned below).

---

## Reproduced evidence (this Auditor, not trusted from the Orchestrator)

### Standing gate (SDV §8 "reproduced by the Auditor")

Command (project `.venv`, `-p no:cacheprovider`):
```
.venv/Scripts/python.exe -m pytest shared/ services/ launcher/ tests/integration/ tests/security/ -m "not hardware and not winui and not slow" -p no:cacheprovider
```
Result line (exact):
```
======== 2342 passed, 113 deselected, 3 warnings in 102.25s (0:01:42) =========
```
**2342 passed / 0 skipped / 0 failed / 113 deselected.** Matches the SCR (§3) and
TEST_GOVERNANCE §1 to the test. No port-5001 skip-shift (no ~2333/9) — the port was
free throughout, the C6 autouse detector recorded free→free and passed silently
(confirming the no-false-positive contract on the live gate path, not just the unit
truth-table). The 3 warnings are pre-existing SwigPy/`\p`-escape `DeprecationWarning`s,
not Sprint-18 regressions.

### C1 — production-posture round-trip (the §5.1 reproduction)

Command:
```
.venv/Scripts/python.exe -m pytest -m hardware tests/harness/test_model_loaded_round_trip.py -s -p no:cacheprovider -v
```
Result:
```
tests/harness/test_model_loaded_round_trip.py::TestModelLoadedRoundTripProduction::test_production_round_trip_streams_real_model_output
C1_PERF model_load_seconds=18.341
C1_PERF first_token_ms=1935.4
C1_PERF total_ms=2359.9
C1_PERF response_chars=36
PASSED
======================= 1 passed, 2 warnings in 30.29s ========================
```
**PASS.** Real Qwen3-14B (7.84 GB `openvino_model.bin` confirmed on disk), real
detached `manifest.json.sig` + `.pub` on disk (so the signature verifies rather than
fail-closes for absence), `dev_mode=False`. The PASS is load-bearing: it can only be
reached if `service.start()` returned True, which the entrypoint code path
(`entrypoint.py:572 _validate_security_material` → `:884 load_manifest_verified(...,
require_signed=True)`) gates on the detached-`.sig` verification, the JWT validator
init (`:404` required when not dev_mode), and the `VsockListener` building a real
`CERT_REQUIRED` mTLS server context (`vsock.py:181/196`). My captured first-token
(1935 ms) differs from the SCR's 3101 ms — ordinary cold-load run-to-run variance
(n=1, file-cache state differs); the PASS verdict is identical.

*Model is genuinely on disk and the test genuinely ran — it did NOT silently skip
into a PASS.* (`_signed_manifest_present()` returned True; verified the three files
exist.)

---

## Per-criterion independent assessment

### C1 — Model-loaded prompt round-trip (production posture) · GAP-5/§5.1 · **MET**

`tests/harness/test_model_loaded_round_trip.py`. **Independently reproduced PASS in
production posture (above).** Read critically, line by line:

- **`dev_mode=False` on both ends — real, not stubbed.** The AO config writes
  `[security] dev_mode = false` (`:165`); the service is constructed with no
  `dev_mode_override` (`:400–405`), so `dev_mode` resolves False from config
  (`entrypoint.py:542`). The listener gets `dev_mode=resolved.dev_mode`=False, and
  `create_server_ssl_context` sets `verify_mode = ssl.CERT_REQUIRED`
  (`vsock.py:196`). The gateway is `TransportGateway(dev_mode=False, host_mode=True,
  …)` with the gateway-client cert (`:430–438`). Real mTLS both ways. **Not a stubbed
  handshake.**
- **`require_signed_manifest=true` reaches the detached-`.sig` verification.** Config
  sets it (`:166`); `_validate_security_material(dev_mode=False,
  require_signed_manifest=True)` calls `load_manifest_verified(manifest_path,
  require_signed=True)` (`entrypoint.py:884`). A missing/invalid `.sig` would
  fail-close the boot — proven empirically by the C1 path-fix history (the test first
  hit `AO_CFG_KGM_PATH_NOT_FOUND`, the gate refusing to start; SCR §7). The load-time
  digest sweep (`verify_all_manifest_entries`, `gpu_inference.py:475`,
  fail-closed) also runs because the `engine` fixture passes `manifest_path`.
  **Both halves of the signed-manifest path are exercised.**
- **The cert-wiring trade-off is named** (the SDV asks for it): the fixture mints
  per-boot certs via the *real* `provision_per_boot_certs` (verified returns the
  `PerBootCerts` dataclass with the exact attributes referenced —
  `cert_provisioning.py:102–384`) into a tmp dir, chosen over the gitignored
  ceremony `certs/` so cert-absence does not muddy the model signal. `dev_mode` stays
  False either way, so the production mTLS code path executes regardless. Sound and
  honest.
- **The single fidelity gap is named and acceptable:** AF_INET loopback vs AF_HYPERV
  is the only delta from true production (docstring `:24`; perf JSON `not_measured`).
  The mTLS code path, signed-manifest boot, JWT init, and `_handle_prompt_request` are
  the production ones. Air-gap-compliant (loopback never leaves the machine).
- The model loads once at module scope; the `_PreloadedInference.__getattr__`
  forwards `generate_text` to the real engine (only `load_model`/`unload` overridden),
  so **real generation runs** — not a canned reply. Acceptance conditions (a)–(d) are
  each genuinely asserted.

No defect. C1 is the strongest tier and is exactly what §5.1 needs as its scripted
production-posture evidence.

### C2 — IPC-routing regression lock, model-loaded · GAP-6/§5.1 · **MET**

`tests/integration/test_prompt_round_trip_host_mode.py::TestPromptRoundTripModelLoaded`
(`:530–570`). The model-loaded twin of the ISS-10 stub lock: lets the real 14B load
instead of `_StubInference`, asserts `resolve_gateway_port(dev_mode=False,
host_mode=True)` resolves to the AO loopback port, a `STREAM_TOKEN` carrying real
output returns, and no "Unsupported message type: PROMPT_REQUEST" / "error from
Orchestrator" misroute appears under real load. Marked `@hardware`, skips on
model-absence, `@hardware`-deselected from the standing gate.

**Adversarial check — is the `dev_mode=True` here an overclaim?** No. The test header
(`:361–365`) is explicit: this tier "stays in `dev_mode=True` to mirror the existing
stub scenario's contract exactly — the variable under test here is REAL-MODEL vs stub,
holding the rest of the wiring constant. The production-mTLS posture … is C1's bar."
The SDV C2 criterion asks for "a real-model `@hardware` scenario asserting correct
gateway→AO port resolution + no … misroute … under real load" — it does **not**
require production posture (that is C1/C5). C2 is faithful to its criterion. The
`require_signed_manifest` note (`:386`) correctly observes dev_mode short-circuits
signature-material validation while the digest sweep still runs. MET.

### C3 — Semantic-router cross-service path · GAP-8 · **PARTIAL (honest)**

`tests/harness/test_sprint12_real_model.py::test_real_router_invoked_inside_ao_turn`
(`:205–320`). This is the criterion the brief asks me to attack hardest, in both
directions.

**Independent verification of the central claim.** I grepped
`services/assistant_orchestrator/src/` for `SemanticRouter` / `.classify(` /
`semantic_router` / router imports. **Result: zero call sites** — the only hit is a
comment in `pgov.py:658` referencing `SemanticRouter._embed_raw` as an *embedding
pattern note*, not a call. The AO→router wiring genuinely does not exist. (#632's body
adds that ACL-matrix entries grant a *permission* to call the router — not a call;
consistent with zero invocations in the turn path.)

**Does the test overclaim "router inside an AO turn"?** The *mechanism* does not match
the criterion's literal wording: the test calls `router.classify()` **adjacent to**,
not **inside**, the AO turn — it classifies the prompt, then separately drives
`_handle_connection` (which does not call the router). So the test does **not** prove
"AO→router wiring." **But the test does not hide this** — the docstring (`:30–35`,
`:218–224`) states the router "is today a standalone service … not called from inside
`_handle_connection`" and that the test "proves the INTENDED cross-service path." So
the honesty is genuine: the *premise was falsified*, the disposition is PARTIAL, and
the gap is escalated to #632.

**Is the PARTIAL dishonest in the *other* direction (hiding that the test is weaker
than the criterion)?** No. The SCR (§2, §7), the ledger (PARTIAL), the perf JSON
("AO→router wiring absent"), the journal (lesson 90), and #632 all state the same
thing. The disposition is consistent across every artifact.

**The one residue — the test *name*.** `test_real_router_invoked_inside_ao_turn`
asserts in its identifier the very thing that is false ("inside an AO turn"). A future
reader scanning test names (not docstrings) could be misled into thinking the wiring
is covered. The docstring corrects it, but the name is a latent overclaim. → MINOR-1.

PARTIAL is the correct score. C3 is, paradoxically, the strongest evidence in the
sprint that the audit culture is real: the work was allowed to *fail its premise* and
say so.

### C4 — TUI against a real gateway · GAP-9 · **MET**

`tests/integration/test_tui_real_gateway.py` (slow). Stands up the real AO IPC
listener (GPU stubbed) at the production loopback port, points a **real
`TransportGateway`** (`:335`, `dev_mode=True` no-mTLS — SDV permits stub-GPU; the seam
under test is TUI→gateway→AO, not mTLS) at it, and drives `BlarAIApp` via
`action_submit_prompt()`. Four tests assert: streaming render (tokens reach the
display), PGOV approved-path (no denial card), session persistence (assistant turn
with `pgov_status='approved'` written to the real `SessionStore` over the real seam),
and handshake→OPERATIONAL.

**Adversarial check — is the gateway really real (not a mock)?** Yes —
`TransportGateway` is the production class, the AO listener is the real
`AssistantOrchestratorService`, the `SessionStore` is real (`:memory:`). Only the four
*widget* selectors (`#prompt-input` etc.) are stubbed via a `query_one` replacement —
the established `test_p114` pattern, and the right call (a Textual pilot event loop is
not needed to exercise the IPC seam). The denial path is honestly noted as
not-exercised (`:25–26`, `:398–403`) to avoid coupling to live PGOV heuristic
thresholds — a reasonable, named scope cut. Re-confirmed green on main under `-m slow`
per the SCR; the tests are in `tests/integration/` (in the standing-gate paths) but
`slow`-marked so they deselect from the standing gate and run in the slow tier. MET.

### C5 — Production-posture SWAGR sweep (§5.1) · **MET (this document)**

This SWAGR is C5. It was conducted in production posture: the §5.1 reproduction is the
C1 `dev_mode=False` run above, plus line-by-line verification that the production mTLS
+ signed-manifest + JWT boot path is the one C1 exercises. The independent gate
reproduction, the C1 production reproduction, and the per-criterion falsification
attempts satisfy the SDV C5 requirement ("the independent Auditor verifies all tiers
in production-mode posture"). See the §5.1 determination below for the gate-scoping
qualification.

### C6 — #630 test-teardown leak fix · **MET (closed)**

The most safety-relevant tier for the gate's *trustworthiness*, because a detector
that false-fires would break the clean baseline. Read end to end:

- **The fix is genuine.** Build commit `5698936` replaces `proc.terminate()` (parent
  -only kill that orphaned the Python backend child holding port 5001) with
  `terminate_process_tree(proc.pid)` in the WinUI harness launch sites. Verified the
  before/after diff on `test_winui_input.py` (bare `proc.terminate()` → tree-kill).
  `terminate_process_tree` (`tests/harness/process_tree.py`) uses
  `psutil.Process(pid).children(recursive=True)`, terminates leaves-first then root,
  waits/kills, with a `taskkill /T /F` fallback — never raises out of `finally`. Wired
  into **5** call sites (`test_winui_sprint12.py:77`, `test_winui_critical_path.py:148`,
  `test_winui_input.py:63`, `test_winui_model_loaded.py:220` + the helper) — a superset
  of the SDV's "4 WinUI teardown edits," not a deficit.
- **Could the detector FALSE-POSITIVE and break the clean gate?** The contract is
  locked: `port_leak_verdict` (`conftest.py:145`) returns a failure **only** on
  `free→held`; `free→free`, `held→held`, `held→free` all return `None` (silent pass).
  `tests/test_port_leak_detector.py` locks all four cases, with `free→free is silent
  pass` called out as "the most important case — it must NEVER produce a failure." The
  autouse session fixture (`:189`) samples `held_at_start`/`held_at_end` via a bind
  probe (`_port_held`, `SO_REUSEADDR=0`) and only fails on the free→held delta.
  **Empirically confirmed:** my clean gate run (free→free, no @hardware port-binder
  selected) passed silently — the detector did not move the 2342/0 baseline. A
  pre-existing live instance (held→held) is correctly a silent pass, so an operator
  using the machine is not punished. Residual edge (full-suite path only, not the
  clean gate): a same-session @hardware test that binds 5001 then a racy/TIME_WAIT
  teardown *could* theoretically read as held at session end — but those tiers
  `service.stop()` in `finally`, and the standing gate deselects them. → MINOR-2
  (note, not a defect).
- Deterministic baseline reproduced (my run) without a manual process-kill. Vikunja
  #630 closed. MET.

### C7 — Close hygiene · **MET**

Gate green + deterministic baseline (reproduced); model-loaded @hardware tiers
agent-run green with community-grade perf
(`docs/performance/sprint18_model_loaded_roundtrip_2026-06-08.json` +
`PERFORMANCE_LOG.md` 2026-06-08, both verified present; the JSON carries the mandatory
`not_measured` block naming warm-cache, throughput, co-residency, n=1, and AF_HYPERV
as uncovered — community-grade and honest). Journal fragments folded → BUILD_JOURNAL
lessons 87–90 (verified present, narrative form, correct cross-refs; no s18 fragments
remain). SCR + ledger landed. C3 ticketed (#632, verified exists). §5.1 reconcile +
#631 close are correctly gated on this SWAGR's verdict (SCR §5/§8 leave those two
boxes open pending C5) — appropriate, not a gap. MET.

---

## §5.1 determination — QUALIFIED-YES

**Question:** Does Sprint 18's evidence satisfy SECURITY_ROADMAP §5.1 —
"Tiers 1–3 complete **AND** independently SWAGR-verified in the *production* posture
(`dev_mode=false`, real certs/keys)"?

**Determination: QUALIFIED-YES.** The production-posture *verification* limb is
satisfied; the "Tiers 1–3 *complete*" limb is satisfied *as the roadmap itself
defines completeness for the gate*, but with two standing qualifications the LA should
see before flipping §5.1 REMAINING→DONE.

**What IS satisfied (the verification limb — this Auditor's core charge):**
- A real `dev_mode=False`, real-`CERT_REQUIRED`-mTLS, signed-manifest-boot,
  real-Qwen3-14B, real-PGOV round-trip is **independently reproduced green** (C1). This
  is the production-posture composed-path evidence §5.1's text demands, and it is now a
  scripted fleet run, not a manual marathon — exactly the campaign goal (§4 step 5).
  The "mock-passes-prod-fails" trap §5.1 was written to prevent is directly defeated:
  the production boot *fail-closed correctly* during development (the C1 path-fix), then
  passed once pointed at real material.
- The independent SWAGR (this document) is conducted in production posture, satisfying
  the SDV C5 instruction and §8's "a SWAGR run in dev posture does NOT satisfy §5.1."

**The qualifications (why QUALIFIED, not an unconditional YES):**

1. **Only C1 is production-posture; C2/C3/C4 are `dev_mode=True` by design.** That is
   *correct per each criterion's wording*, but it means the production-posture evidence
   is **one composed path** (gateway→AO→14B→PGOV over mTLS), not the full tier ladder
   re-run with `dev_mode=False`. §5.1 says "**Tiers 1–3** … SWAGR-verified in production
   posture." A maximally-strict reading wants more than one production-posture path
   (e.g., the boot cascade, the PA classify path, at-rest encryption, the egress guard)
   each exercised at `dev_mode=False`. The composed C1 path is the *highest-value* such
   path and transitively exercises the security-material boot, mTLS, and PGOV; but the
   LA should flip §5.1 knowing the production-posture *reproduction* is C1-anchored, with
   the other tiers verified in dev-posture + static/config locks (the standing gate's
   `tests/security/` guards: `test_secure_defaults`, `test_production_posture`,
   `test_no_external_egress`, `test_root_test_isolation`, all green). → MINOR-3.

2. **The "Tiers 1–3 complete" limb inherits upstream PARTIAL/DORMANT facts Sprint 18
   did not change.** Per the roadmap's own §5 summary table: the FUT-04 signed-manifest
   was gate-MET at the Sprint-17 close but #106 stays **PARTIAL** (runtime
   per-adjudication re-verify + CoW deferred — explicitly NOT a #598 blocker per
   ADR-028); the egress allowlist / kill-switch / PA carve-out / PII screen are **BUILT
   DORMANT** (enforce only post-#556); audit retention (#607) and the #612 capstone
   (§5.13) + §5.12 sign-off remain. Sprint 18 was scoped as a *verification* sweep, not
   a tier-completion sweep, so it neither closed nor regressed these. §5.1 can read DONE
   *for the production-posture-verification criterion specifically* while these
   forward/dormant items remain tracked — but DONE on §5.1 must **not** be read as
   "Tiers 1–3 are wholly complete and the gate is clear." The gate still requires §5.13
   (#612 capstone + LA deep-dive) and §5.12 (sign-off), both of which the roadmap and
   SCR correctly keep REMAINING. → MINOR-4 (a reconciliation-wording caution, not a
   defect).

**Net:** I assess §5.1's production-posture-verification criterion **satisfiable from
this evidence** and recommend the LA flip it REMAINING→DONE **with the two
qualifications recorded inline** (production-posture reproduction is C1-anchored; DONE
scopes the *verification* limb, not whole-ladder tier-completion — §5.13/§5.12 still
gate #598). This is consistent with the SCR's conditional language ("on a
STRONG/ALIGNED verdict, §5.1 flips … to DONE") and does not over-declare the gate.

---

## Findings (CRITICAL / MAJOR / MINOR)

**CRITICAL: 0.** No fail-open, no built-into-nothing, no stubbed-posture-dressed-as-
production, no detector that breaks the clean gate, no committed-but-not-green dressed
as done.

**MAJOR: 0.** No overclaimed criterion; no dishonest PARTIAL (C3 is consistent across
every artifact); no missing regression lock for what was claimed; no stale doc claim
the code contradicts within Sprint-18 scope.

**MINOR (5):**

- **MINOR-1 — C3 test name asserts the falsified premise.**
  `test_real_router_invoked_inside_ao_turn` names the router as "invoked inside an AO
  turn," which the test itself proves false (the router is called adjacent to, not
  inside, the turn). The docstring corrects it, but a name-only reader is misled.
  *Action:* on the #632 disposition, rename to e.g.
  `test_real_router_classify_and_ao_turn_cross_service` (or `…_router_standalone_plus_ao_turn`)
  so the identifier matches the documented reality. Low urgency; fold into #632.

- **MINOR-2 — Port-leak detector edge on the full-suite path (not the clean gate).**
  The `free→held` detector is correct and was empirically silent on the clean gate, but
  on a full-suite run that selects an @hardware tier binding port 5001, a TIME_WAIT /
  racy teardown could in principle read as `held` at session end and fail loud. The
  @hardware fixtures `service.stop()` in `finally` and the standing gate deselects them,
  so the clean baseline is safe; this is a theoretical full-suite edge. *Action:* if a
  future full-suite run ever false-fails, add a short settle/poll on the end-of-session
  probe (e.g., retry `_port_held` for ~1–2 s) before the verdict. Note only; no change
  needed now.

- **MINOR-3 — §5.1 production-posture evidence is C1-anchored (single composed path).**
  Production posture (`dev_mode=False`) is proven for the gateway→AO→14B→PGOV mTLS path
  only; the other tiers are verified in dev-posture + static locks. *Action:* when
  flipping §5.1 to DONE, record inline that the production-posture reproduction is
  C1-anchored, and (forward, not gate-blocking) consider a production-posture boot-cascade
  tier (the #619 lane's natural `dev_mode=False` extension) so more than one path has
  `dev_mode=False` coverage. Aligns with the roadmap's own "production-parity lane (#619)
  … path to satisfying this criterion automatically."

- **MINOR-4 — §5.1 DONE must be scoped to the verification limb, not whole-ladder
  completion.** Several §5 items remain PARTIAL/DORMANT/REMAINING (FUT-04 #106 runtime
  re-verify; egress dormant; #607; §5.13 #612; §5.12 sign-off). *Action:* the §5.1
  reconcile wording should say "production-posture SWAGR verification: DONE (Sprint 18,
  C1-anchored)" and explicitly NOT imply Tiers 1–3 are wholly complete or the gate is
  clear — #598 still gates on §5.13 + §5.12. (The SCR and roadmap already keep those
  REMAINING; this is a caution against a careless table edit, not a contradiction.)

- **MINOR-5 — Coverage-audit GAP-8 wording is now known-false and should be
  reconciled.** `coverage_audit.md` GAP-8 still asserts the premise "the real path — AO
  receives a prompt, calls the real bge-small router," which Sprint-18 C3 falsified.
  Leaving it unannotated risks a future sprint re-deriving the same dead premise.
  *Action:* annotate GAP-8 (or let #632's resolution do it) with a pointer to the
  finding — consistent with the project's hardening-followups-are-non-optional rule for
  stale/incorrect doc claims. Low urgency; #632 is the natural home.

---

## Closing note

The sprint's most adversarially-significant outcome is that **C3 was permitted to
falsify its own premise and say so** — the inverse of the failure modes a SWAGR hunts
for. Combined with the independently-reproduced clean gate (2342/0) and the
independently-reproduced production-posture C1 PASS, the evidence supports
STRONG_ALIGNMENT. The only material caution is to flip §5.1 with its two
qualifications recorded (C1-anchored production-posture; DONE scopes the verification
limb, not the whole tier ladder) so the #598 gate is advanced honestly and not
over-declared.
