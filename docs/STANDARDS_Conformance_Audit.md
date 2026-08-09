# BlarAI — Standards Conformance Audit

**Standards audited:** the Architectural Principles and File Rules from the engineering standards (global `CLAUDE.md` System Protocols) — DRY/modularity, functional paradigms, Twelve-Factor App, SOLID, YAGNI, boring-tech/dependency discipline, Rob Pike's rules + correctness-before-speed, and the file rules (140-col, indentation).
**Scope:** core runtime — `services/*/src`, `shared/`, `launcher/`. Benchmarks/experiments excluded.
**Method:** Read-only. Mechanical checks run directly; judgment-heavy standards audited by focused passes. Findings are file:line-anchored. No code was changed.
**Note:** This is a conformance audit against *engineering* standards, distinct from the OWASP/CWE/RFC external-standards sweep folded into the earlier system-qualities audit. Reuses the flexibility pass for the DRY/SOLID structural findings rather than re-deriving them.

---

## Scorecard

| Standard | Conformance | One-line reason |
|---|---|---|
| **File rules** (140-col, indentation) | **Strong** | 0 tab-indented files; 148 of ~133K lines exceed 140 cols (99.9%). |
| **Functional paradigms** | **Strong** | 89% of dataclasses frozen, 0 mutable-default-args, inheritance depth 1, composition-via-injection throughout. |
| **Boring-tech / dependencies** | **Strong** | 2 declared deps each with written rationale; all libs mature & used; 0 redundant/shiny picks. |
| **Rob Pike / correctness-before-speed** | **Adequate** | 3 major optimizations all measurement-justified; the one hand-rolled fancy algorithm is dead code. |
| **DRY / modularity** | **Adequate → weak** | Real seams undercut by god files + a "5 parallel maps must mirror exactly" pattern + duplicated security logic. |
| **SOLID** | **Adequate → weak** | Strong DIP (Protocols/injection) & LSP; SRP violated by god files, OCP violated by the tool-map fan-out. |
| **YAGNI** | **Weak** | A ~230-LOC second inference subsystem (autoregressive loop + custom sampler + preemption detector) is dead, kept green only by its own tests. |
| **Twelve-Factor App** | **Weak → adequate** | Config/Dependencies/Stateless-processes/Logs violated or partial; secrets-externalization is the standout strength. |

**Headline:** The *micro* standards — immutability, composition, dependency minimalism, line discipline — are genuinely well-observed and would pass a cheap CI gate today. The *macro* standards — YAGNI, SOLID-SRP/OCP, and the applicable 12-Factor factors — are where conformance drops, and they cluster on the same two files (`entrypoint.py`, the two `gpu_inference.py` twins) plus the config/dependency-declaration surface.

---

## File Rules — **Strong**

- **Indentation:** 0 production `.py` files contain tab-indented lines — 4-space conformant throughout.
- **Line length (≤140 cols):** only **148 lines out of ~133K** exceed 140 columns (99.9% conformant). Top offenders: `shared/timeout_registry.py` (47 — ironically the exemplary-centralization file, long because every entry carries a documented `surface=` string), `services/ui_shell/src/app.py` (16), `shared/crypto/jwt_validator.py` (9). No action needed beyond optional wrapping of the registry docstrings.
- README, `.gitignore` present. (`.claudeignore` per your global rule is a workspace-tooling file, not expected in this repo.)

*Note: the project's own `CLAUDE.md` also mandates strict type hints + PEP 8 + deterministic execution — observed conformance signals (pervasive type hints, `ruff` in the toolchain, `temperature=0` posture) but not deeply audited here since "our standards" refers to the global architectural principles.*

---

## Functional Paradigms — **Strong (leaning)**

*"Prefer functional paradigms: pure functions, immutability, composition over inheritance."*

**Immutability — strong.** Frozen dataclasses **100/112 = 89.3%**; **0 mutable-default-arguments** anywhere in the runtime; 9 `NamedTuple`. Value types (`Citation`, `SwapDriverResult`, the CAR/verdict types) are frozen by default, and the frozen/mutable split is deliberate (e.g. `websearch/state.py:46 Citation` frozen while the sibling accumulator `SourceLearning` is not).

**Composition over inheritance — strong.** Max concrete inheritance depth **1** (the only 2-deep chains are exception hierarchies — idiomatic). ~11 `Protocol` interfaces, 2 ABCs / 6 `@abstractmethod` used as interfaces not concrete reuse. Behavior is assembled by injected collaborators — `shared/fleet/swap_driver.py:283 SwapDriver` takes an injected `SwapOps` struct of ~25 callables (testable without a real backend); handlers depend on structural Protocols (`AdjudicationHandler`, `ApprovalVerifier`, `Sealer`, the `*Like` ingest interfaces). Textbook composition.

**Pure functions — strong.** Module-level functions (975) slightly outnumber methods (874); core transforms are pure (`websearch/adapter.py:48 parse_kagi_search_response`, `policy_agent/src/car.py:28 build_car`, `cleaner/src/normalize.py:77`, `tools.py:1162 parse_tool_call`), with I/O pushed to service edges.

**Deviations (minor):**
1. **Module-level mutable registries + `global` mutation in the security layer** — `shared/security/egress_guard.py:238-260,1013` (`_screeners`/`_external_allowlist`/`_resolution_pins`/`_arm_hooks` mutated via append/add/clear; `global _tripped,_armed` latched). Partly inherent — it monkeypatches the process-global `socket` module as a kill-switch — but it's genuine action-at-a-distance state. Same shape as the tool-runner globals (`tools.py:301-339`).
2. **`circuit_breaker.py:70 record_tokens(state, count)`** has a functional signature (state→state) but mutates the passed-in non-frozen `BreakerState` (`state.tokens_generated += count`). Freezing `BreakerState` + `replace()` would make it genuinely pure — a one-line missed opportunity.

**Metric:** frozen-dataclass ratio (89.3%), mutable-default-args (0), inheritance depth (1), Protocol count (~11) — all trivially greppable, **none currently gated in CI**. The project already treats immutability as load-bearing (the "frozen-dataclass mock-shape divergence" lesson), so a frozen-ratio gate would formalize an existing value.

---

## Boring-Tech / Dependencies — **Strong (with one DRY miss)**

*"Default to boring tech… prefer mature over new/shiny."* + *"add a dep only when it earns its place."*

- `pyproject.toml` declares exactly **2** runtime deps (`cryptography>=46,<47`, `httpx>=0.28,<0.29`), **each with a paragraph of in-file rationale**. The project's own constraint — *"Do NOT install packages or add dependencies without explicit approval"* — makes this minimalism deliberate.
- **No redundant/shiny picks.** The hypothesized PyJWT-vs-custom-JWT duplication does **not** exist — both `jwt_validator.py` and `jwt_minter.py` wrap PyJWT; there's no competing hand-rolled parser. `pydantic` is genuinely used (`shared/schemas/car.py` with real `Field(ge=…, le=…)` validation). numpy, openvino_genai, transformers, textual/rich, trafilatura/pypdf, pywin32 are all mature and used behind fail-closed optional-import guards.
- **One miss (ties to DRY):** hand-rolled config validation (`_require_section_dict`/`_require_non_empty_str`/`_require_int_range`/`_require_float_range`) is **duplicated across two services** (`policy_agent/src/entrypoint.py` and `assistant_orchestrator/src/entrypoint.py`) while `pydantic` — already a dependency — is the boring tool for it. There's a rationale (each raises a service-specific error code feeding "deterministic failure fingerprinting"), so it's not egregious, but the same helper suite living in two files rather than `shared/` is both a DRY miss and a boring-tech inconsistency.

**Metric:** 2 declared deps / 0 redundant / 0 shiny — strong. Caveat lives under 12-Factor (declared-vs-imported gap), not here.

---

## Rob Pike's Rules + Correctness-Before-Speed — **Adequate**

*"Do not assume bottlenecks; measure first… Fancy algorithms are slow/buggy when n is small."*

**Conformant — the measured optimizations are genuinely measured:**
- Speculative decoding (Qwen3-0.6B draft) — ~2× throughput recorded (ISS-1 closure, `PERFORMANCE_LOG.md`).
- Prefix caching (`gpu_inference.py:693`) — comment carries the measurement trail (OV 2026.0 OFF → re-checked empirically on 2026.1, ADR-012 Am.3).
- NPU encoder offload (`[embeddings].device`) — flipped CPU→NPU **on measurement** (13.6× @512-token windows, cosine 0.999996). Exactly Pike-compliant.
- `CircuitBreaker` is a plain counter + immutable state (~100 LOC) — simple data structure, self-evident.

**The one violation is also dead code:** `gpu_inference.py:1533 _sample_token` hand-rolls temperature/top-k (`argsort[::-1][:k]`)/top-p nucleus/`np.random.choice` over a ~150K-token vocab plus a stable `_softmax` — a fancy hand-rolled loop (Pike rules 3–4) that is **superseded by OpenVINO GenAI's own `GenerationConfig` sampling and never runs in production**. Delete-on-sight, not tune (overlaps YAGNI A1 and the earlier performance finding #9).

**Metric:** 0 premature optimizations in *live* code; 3 major optimizations all measurement-justified; 1 hand-rolled fancy algorithm that is unmeasured *and* dead.

---

## DRY / Modularity — **Adequate → weak**

*"Modular and DRY (modularity wins ties)."* (Structural findings reused from the flexibility pass.)

1. **`entrypoint.py` — 5106 LOC god file.** One `AssistantOrchestratorService` owns config load (285 LOC), config validation (380 LOC), security-material build, substrate + knowledge-bank build, and 8 request handlers. The merge-conflict epicenter; violates modularity directly.
2. **"Add a tool" touches 5 parallel maps that must mirror exactly** — `tools.py:498 TOOL_SCHEMAS` + `:469 _REGISTRY` + `:651/:659` arg-shape maps + `:762 _TOOL_RISK_TIER` + `pgov.py:514 TOOL_CALL_ALLOWLIST`. The code admits it (*"Must mirror `_REGISTRY` exactly"*), policed only by a coupling test. The **anti-DRY** pattern — and ironically the good DRY pattern already exists next door (grammar/prompt *derived* from `TOOL_SCHEMAS`, "no drift surface").
3. **Duplicated SSRF IP-block logic** — `egress_guard.py:264 _is_blocked_pin_ip` and `guarded_fetch.py:511 _is_blocked_ip` independently implement the same loopback/RFC-1918/CGNAT check, in the security-critical layer where divergence is most dangerous.
4. **Duplicated config-validation helper suite** across the two service entrypoints (see Boring-Tech miss).
5. **Per-service `constants.py` shadow** re-exports/renames `shared/constants.py` per service — dilutes the SSOT.

---

## SOLID — **Adequate → weak**

- **S (SRP) — violated by the god files.** `entrypoint.py` (8 responsibilities in one class), `launcher/__main__.py` 826-LOC `main()`, `swap_ops.py`/`swap_driver.py` (~2000 each), `acceptance.py` (2505, mixes schema-emission + parsing + prompt-compilation + codegen). 22 files >1000 LOC.
- **O (OCP) — violated by the tool-map fan-out.** Adding a tool/model/egress-provider requires *modifying* 4–5 existing maps rather than *extending* via one registration point. The web-search provider is compile-time hardcoded (`LiveKagiAdapter` baked into the launcher registrar) with no `SearchProvider` list to append to.
- **L (LSP) — strong.** Inheritance depth 1; the one ABC (`KagiAdapter`) has two clean 1-level implementations (Live/Mock) that substitute correctly.
- **I (ISP) — strong.** Interfaces are narrow structural Protocols (`*Like` ingest interfaces, `ApprovalVerifier`, `Sealer`), not fat base classes.
- **D (DIP) — strong, with 4 leaks.** Predominantly Protocol-based injection (`SwapDriver`←`SwapOps`, handler←Protocol). The 4 exceptions bypass IPC to import another service's internals: `ui_gateway/url_adjudicator.py:196,255`→`policy_agent.src.gpu_inference`; `ingest_coordinator.py:214,795,1042`→`cleaner.src.pipeline`; `ui_backend/dispatcher.py:578,684,765,790`→`voice.src.engine` — concrete dependencies on internal module layout where a seam belongs.

---

## YAGNI — **Weak** (the dominant finding)

*"Add abstraction, layers, or config only for a present need, never speculation."*

**A1 — an entire vestigial inference subsystem (~230 dead lines) in `services/assistant_orchestrator/src/gpu_inference.py`.** Production generation goes through `_generate_from_prompt → self._pipeline.generate()` (OpenVINO `LLMPipeline`). A second `InferRequest`-based path coexists and is completely dead — **zero production callers, verified by grep** (only its own tests call it):
- `_autoregressive_loop:1319`, `_sample_token:1533`, `_softmax:1513`, `_check_preemption:1429`, `_decode_tokens:1483` — each reachable only from the dead loop or tests.
- Backing fields `self._core`/`self._compiled_model`/`self._infer_request` (496-498) are assigned only `None` and read only inside the dead loop; comments label them *"legacy fields retained for compatibility."*

**A2 — dead preemption-detection subsystem** in the same file (`PreemptionEvent:242`, `preemption_events` property, `was_preempted`/`resume_latency_ms` fields). The live path hard-codes `was_preempted=False`. The docstring concedes the rationale evaporated: *"ADR-010 — PA moved to GPU, so NPU preemption no longer occurs. Retained for external NPU contention detection"* — retained for a case that **cannot occur on this single-box appliance** (the project `CLAUDE.md` confirms NPU retired from the core loop, ADR-011). This also drives Stability finding #2 (the `_preemption_events` list is one of the unbounded accumulators).

**A3 — the same vestige in the PA twin** (`policy_agent/src/gpu_inference.py:1049 _softmax`, `_infer_request`/`_compiled_model` None-only fields).

**A4 — tests-only public methods:** `reset_statistics` (`gpu_inference.py:1106`), `ContextManager.destroy_session` (`context_manager.py:524`) — no `src/` caller. (Note: `destroy_session` is *also* the fix the Stability audit wants *wired in*, not deleted — reconcile before acting: implement its caller rather than remove it.)

**A5 — inert/speculative config knobs:** `GenerationConfig.min_p` (only affects `do_sample=True`; production runs greedy, so inert in every production path); the `draft_device="NPU"` branch (ADR-011 retired the NPU; no caller passes it).

**Caveat honored:** documented security seams and *stated* future-proofing are not YAGNI violations. The findings above are genuinely-unused-with-retired-rationale, kept green only by their own unit tests — the classic "tests are the only caller" dead-code signature. Removing A1–A3 (and their pinning tests) deletes ~230 lines from the most security-sensitive module with **zero production behavior change**.

**Metric:** 1 dead subsystem (~230 LOC) / ~8 dead functions+classes / 3 vestigial fields / 2 tests-only methods / 2 inert knobs.

---

## Twelve-Factor App — **Weak → adequate**

| Factor | Rating | Evidence |
|---|---|---|
| I. Codebase | Conformant | One repo/service tree; "many deploys" ~N-A (appliance), undercut by machine-baked paths (III). |
| **II. Dependencies** | **Violated** | `pyproject.toml` declares 2 of ~13 imported packages (`textual`, `win32*`, `numpy`, `openvino_genai`, `jwt`, `rich`, `trafilatura`, `pypdf`, `pydantic` undeclared); reproducibility depends on the detached 253-line `requirements.2026.1.0.lock.txt` that `pyproject` never references. `pip install .` yields a non-runnable install. |
| **III. Config** | **Partial→violated** | ~200 tunables live in committed `services/*/config/default.toml`, not the environment; hardware/VM identity hardcoded in `constants.py` ("DO NOT modify"); a shipped default bakes one dev's home dir (`agentic_setup_dir="C:/Users/mrbla/agentic-setup"`). **Secrets externalized (DPAPI/TPM) — a real strength.** |
| IV. Backing services | Partial | IPC port/mTLS swappable via TOML, but VM GUID/disk path + model name compiled into `constants.py`. |
| V. Build/release/run | N-A | PyInstaller frozen appliance; no SaaS-style separation. |
| **VI. Stateless processes** | **Violated** | `context_manager.py:214 _sessions` holds live conversation state in-RAM in one daemon thread; never pushed to a backing store; sudden death loses all in-flight context. (Same root as Stability #1.) |
| VII. Port binding | Conformant (adapted) | Each service self-contained over vsock/AF_HYPERV or loopback mTLS. |
| VIII. Concurrency | N-A | Single-user appliance; services are daemon threads in one process. |
| IX. Disposability | Partial | Graceful `stop()` + Job-Object kill-on-close backstop, but **no `SIGTERM` handler** in AO/PA; heavy model compile contradicts fast startup. (Same root as Resilience #7.) |
| X. Dev/prod parity | Partial | Strong `dev_mode_guard` (loud banner + fail-closed on dev+network), but dev_mode swaps real backing services (TCP vs vsock+mTLS, DPAPI bypass). |
| XI. Logs | Violated (justified) | App manages its own `launcher.log` + segmented/gzip/sealed audit files rather than streaming stdout — deliberate tamper-evidence for the audit stream. |
| XII. Admin processes | Conformant | One-off admin ships as same-codebase `python -m` modules with the same config resolution. |

**Biggest gap:** Factor II — the declared manifest and the actual import graph have silently diverged with nothing enforcing the tie.

**Metric — config externalization:** ~15% environment-native (the 12-Factor ideal), ~60% in committed TOML, ~25% hardcoded in source. Secrets are the standout: externalized to DPAPI/TPM, never in source.

---

## Cross-Standard Notes

- **The dead code is a triple hit.** The vestigial inference path violates **YAGNI** (A1–A3), **Rob Pike** (the fancy unmeasured sampler), *and* feeds a **Stability** leak (`_preemption_events`). One deletion closes three findings — highest-leverage cleanup in the report.
- **`entrypoint.py` is the SRP + DRY + modularity nexus** — the same 5106-LOC file lands under three standards. Decomposing it is one large task that improves all three.
- **The minimal `pyproject` is deliberate** (the project forbids adding deps without approval) — but deliberateness doesn't resolve the 12-Factor II gap: declaring the already-present, already-locked packages costs nothing and doesn't add a dependency. This is a *documentation-of-truth* fix, not a *new-dependency* decision.
- **Reconcile YAGNI-A4 with the earlier Stability rec:** `destroy_session` is dead *and* wanted — the correct move is to **wire in its caller** (Stability), not delete it (YAGNI). Deleting `reset_statistics` is safe; deleting `destroy_session` is not.

---

## Prioritized Recommendations

Ranked by impact ÷ effort. Effort: **S** ≈ hours, **M** ≈ 1–3 days, **L** ≈ multi-day. All read-only until you pick.

1. **Delete the dead inference subsystem** (`_autoregressive_loop`/`_sample_token`/`_softmax`/`_check_preemption`/`_decode_tokens` + `_core`/`_compiled_model`/`_infer_request` fields in both `gpu_inference.py` twins, + the `PreemptionEvent` machinery) and their pinning tests. Closes YAGNI A1–A3, the Pike violation, and Stability #2. ~230 LOC, zero production behavior change. **S–M**
2. **Declare the real dependencies in `pyproject.toml`** (pin the already-present, already-locked packages: numpy, textual, rich, PyJWT, pydantic, trafilatura, pypdf, pywin32, openvino-genai) and reference/derive from the lock file. Closes 12-Factor II. Not a new-dependency decision — a truth fix. **S**
3. **Collapse the 5-map tool definition to one descriptor** (schema + callable + tier + arg-shape) and *derive* `TOOL_CALL_ALLOWLIST` from it. Closes DRY #2 + OCP. The derive-don't-duplicate pattern already exists next door. **M**
4. **Consolidate the duplicated SSRF IP-block logic** into one shared helper used by both `egress_guard` and `guarded_fetch`. Closes DRY #3; reduces divergence risk in the security layer. **S**
5. **Extract the config-validation helpers to `shared/`** (dedupe the two entrypoint copies); optionally back them with the already-present `pydantic` while preserving the service-specific error codes. Closes DRY #4 + the boring-tech miss. **S–M**
6. **Externalize machine-specific config** — move the baked home-dir path (`agentic_setup_dir`, `projects_dir`) and ideally the VM identity to environment/operator config so the shipped default runs on more than one box. Closes 12-Factor III/IV. **S–M**
7. **Add a `SIGTERM` handler** to the AO/PA entrypoints for graceful drain independent of the launcher. Closes 12-Factor IX + Resilience #7. **S**
8. **Freeze `BreakerState`** and switch `record_tokens` to `replace()` — make the state transition genuinely pure. Functional-paradigm polish. **S**
9. **Remove the inert config knobs** (`min_p` on the greedy path, `draft_device="NPU"`) or gate them behind a documented "future-work" flag. Closes YAGNI A5. **S**
10. **Wire in `destroy_session`** on disconnect/idle (do *not* delete it — reconcile with YAGNI A4). This is the Stability #1 fix; noted here so the two audits don't collide. **M**
11. **Add cheap CI gates for the micro-standards** (frozen-dataclass ratio, mutable-default-args=0, max-file-LOC, max-function-LOC, 140-col). Formalizes the strengths so they don't regress. **S–M**
12. **Decompose `entrypoint.py` and `launcher.main()`** — config→schema, handlers→registry, `main()`→boot-phase objects. Closes SRP + DRY #1 + OCP; large but highest structural payoff. **L**

---

*Which of these should I implement? Reply with numbers (e.g. "1, 2, 4"), "all", or "none". Note #1 and #10 interact — see the cross-standard note on `destroy_session`. Selecting authorizes the follow-up implementation; the audit itself changed nothing.*
