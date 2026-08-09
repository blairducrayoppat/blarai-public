# BlarAI — System Qualities Audit

**Scope:** All five system qualities — Robustness, Stability, Resilience, Flexibility, Performance — across the core runtime (`services/*`, `shared/`, `launcher/`). Benchmarks/experiments (`scripts/`, `phase2_gates/`, `evals/`, `tools/`) excluded except as evidence of what is measured.
**Method:** Read-only. Findings are file:line-anchored and ranked worst-first within each dimension. ~133K LOC of production code reviewed.
**Nature:** This is an audit — it observes and recommends. No code was changed.

---

## Standards Check

**Applied (folded into findings):**
- **OWASP ASVS 4.0 (V5 input validation), CWE-20, CWE-502** → Robustness findings on IPC parsing, egress seam, deserialization.
- **CWE-617 (assert as validation)** → Robustness finding #1 (security invariants stripped under `python -O`).
- **Backoff-with-jitter norm (AWS "Exponential Backoff and Jitter"), RFC 9110 timeout norms** → Resilience findings on retries/timeouts.
- **OpenTelemetry (latency instrumentation)** → Performance finding on absent runtime metrics.

**Considered, not applicable:** WCAG/Section 508 (native WinUI shell, not public web UI — not audited as a dimension). PCI-DSS (no cardholder data). HIPAA (no PHI in scope). Crypto correctness (TPM/DEK/JWT) folded into Robustness + Resilience rather than treated separately.

---

## Overall

The security-critical seams are genuinely well-built — the egress/SSRF door, JWT validation, IPC framing, subprocess spawn, atomic swap-state recovery, and the tamper-evident audit chain are all hardened and fail-closed. The recurring weakness across **four of five** dimensions is the same shape: **a correct mechanism exists in code but is not wired into steady-state operation, and nothing measures whether it's working.** Session teardown exists but is never called; recovery is atomic in the swap path but there's no supervisor outside it; latency is timed per-call but never aggregated. The system is asserted-correct-by-construction rather than observed-correct.

| Dimension | Verdict | One-line reason |
|---|---|---|
| Robustness | **Adequate (→strong)** | Critical trust boundaries hardened & fail-closed; residual risk is security invariants enforced by `assert` (stripped under `-O`) + inconsistent IPC integer parsing. |
| Stability | **Adequate (→weak)** | Two in-memory accumulators in the resident orchestrator grow monotonically under normal use; their clearing paths exist but are never called, and no soak metric would catch them. |
| Resilience | **Adequate** | Swap-path crash recovery is textbook, but there is no steady-state supervisor — a core service dying mid-session has a fully manual, unmeasured recovery time. |
| Flexibility | **Adequate (→weak)** | Real seams exist, but god files (`entrypoint.py` 5106 LOC) and a "5 parallel maps must mirror exactly" pattern make the most common change (add a tool/model/provider) a multi-site edit. |
| Performance | **Adequate** | Heavy inference levers are real runtime code (spec-decode ~2×, KV-cache, NPU offload 13.6×), undercut by avoidable per-turn host overhead and zero in-runtime latency instrumentation. |

---

## Robustness — *tolerance to bad/extreme input without failing*

**Verdict: Adequate, bordering strong.** JWT validation, the egress/SSRF seam, IPC framing, and subprocess spawn are hardened and fail-closed; residual risk is concentrated in security invariants enforced by `assert` and inconsistent integer parsing of untrusted IPC payloads.

**Strong (context):** No unsafe deserialization anywhere (zero `pickle`/`yaml.load`/`eval`/`exec` in runtime dirs — meets CWE-502). No shell-injection surface (every `subprocess` uses vector argv, no `shell=True`). The egress seam `shared/security/guarded_fetch.py` is exemplary — scheme allowlist, IP-range blocking incl. CGNAT, DNS re-resolution recheck, `follow_redirects=False`, streaming byte-cap, decompression-bomb ceiling, fail-closed. JWT validator pins ES256, forces all claims present, type-checks post-decode, never raises.

**Findings (worst-first):**
1. **Security invariants enforced by `assert` — silently removed under `python -O`** (CWE-617 / ASVS V5.1.1). `entrypoint.py:2888` & `:3603` (`assert store.has_encryption is True`), `ui_gateway/src/session_store.py:1411` (same), `policy_agent/src/adjudicator.py:376-377` (`assert self._manifest_path is not None` right before `verify_weight_integrity`). Under `-O` these gates evaporate and a store with encryption silently disabled — or a `None` weight path — proceeds. Should be explicit `if not …: raise`.
2. **Untrusted IPC integers parsed with bare `int()`** (CWE-20). `shared/ipc/protocol.py` `decode_ingest_result:778`, image-list decode `:1099,:1135,:1142`, and `ui_gateway/src/transport.py:149`. A peer sending `{"chunk_count": []}` raises `TypeError`, not the `ValueError` the contract documents and callers catch (`transport.py:942`). Sibling channel `parse_channel.py:538 _require_int` does it correctly. Latent inconsistency (outer `except Exception` masks it today), but any `except ValueError`-only caller crashes.
3. **Silent type coercion accepts malformed fields instead of rejecting** (ASVS V5.1). `protocol.py:330-331,:706`, `transport.py:150-153` coerce with `str(...)`/`bool(...)` — a list becomes `"['x']"` and flows on as "valid." Robustness-by-swallowing rather than refusal.
4. **No centralized schema at the JSON envelope boundary** (ASVS V5.1.2). `MessageFramer.decode` validates only `isinstance(dict)` + enum lookup; per-message field validation is hand-rolled and uneven (strict `encode_ingest_submit` vs loose `decode_ingest_result`). Coverage depends on each decoder remembering to validate.
5. **`except Exception: pass` around generation config** (CWE-703). `gpu_inference.py:1155,1160,1167` swallow stop-token setattr failures — a broken stop config passes silently. Low severity (documented OpenVINO version-skew fallback); noted.
6. TOCTOU between DNS pre-check and connect in `guarded_fetch.py:548-559` — *mitigated* by the armed egress guard re-resolving at connect; listed as considered, not a gap.
7. Unbounded `read_bytes()` on local DB/blob files (`substrate.py:1247`, `session_store.py:1266`, `ingest_staging.py:188`) — local access-controlled artifacts, low risk; the network image path *is* capped, the at-rest staging read is not.

**Metric:** Negative/adversarial unit-test coverage per trust boundary. **Measured and strong** for the critical seams (JWT 19 malformed cases, IPC transport 98KB of tests, SSRF/oversized cases). **Weakest measured spot:** the protocol decoders (~3 malformed-input assertions) — exactly where findings #2–#4 land. **Not measured at all:** property-based/fuzz testing (no `hypothesis` or fuzz harness).

---

## Stability — *stays correct over time & load*

**Verdict: Adequate, leaning weak.** Real discipline exists (managed daemon threads with stop-events + joins, per-session token-budget trimming, segmented audit rotation), but the resident Assistant Orchestrator carries two in-memory accumulators that grow monotonically under normal use — each with a clearing path that exists in code but is **never wired into steady-state operation** — and no runtime soak metric would catch them.

**Findings (worst-first):**
1. **`ContextManager._sessions` grows unbounded — `destroy_session` is dead code.** `context_manager.py:214`; every new chat adds a permanent entry via `create_session`; `destroy_session` (`:524`) has **zero production callers** (only tests). `trim_to_budget` caps turns *within* a session but not the *number* of sessions. Parallel sets `_kv_warm`, `_documents_trusted_for_tools`, `_user_documents_loaded` accumulate identically. On a system "designed for decades of use," RSS climbs one `ConversationContext` per unique session until restart.
2. **`GpuInference._preemption_events` — unbounded list, cleared only on paths that never run steady-state.** `gpu_inference.py:515`, appended per detected GPU preemption (`:1462`). Cleared only in `reset_stats()` (zero production callers) and `unload()` (fires only at shutdown; the AO 14B is "never evicted"). Under sustained GPU contention — the *design* scenario — the list grows continuously; the getter also copies the whole list per read.
3. **`GatewayTransport._pgov_cache` grows one entry per turn**, cleared only on reconnect (`transport.py:312`, populated `:1802`, cleared only in `reset()` `:1913`). A long-lived connected UI session accumulates one `GatewayPGOVResult` per turn until disconnect.
4. **Audit log retention defaults to OFF — unbounded disk growth.** `audit_log.py` rotation is sound, but `archive_max_bytes`/`archive_max_age_days` default `None` (keep all, `:607,:621-628`). Sealed `.jsonl.gz` segments are never pruned; on a decades-resident system a full disk eventually breaks the fail-safe write path. Deliberate governance choice, but it's the primary time-driven disk vector — warrants an explicit operator ceiling.
5. **Session-keyed coordinator dicts have no abandonment cleanup** (`transport._pending_documents/_pending_preview_meta`, `ingest_coordinator._pending:588`, `dispatch_coordinator._pending/_clarifying/_last_action`, `egress_envelope._envelopes:119`). Cleanup is tied to the completion path only — an abandoned mid-flow session leaks its entry, with no TTL/idle-reaper backstop. Compounds with #1.
6. Abandoned consent worker threads under sustained verifier timeout (`egress_rearm.py:199-209`, `escalation_consent.py:407`) — fire-and-abandon daemon retains verifier + closure. Low severity (egress dormant in this build; documented fail-closed trade-off).
7. Module-level mutable registries in `egress_guard.py` (`_screeners`, `_arm_hooks`, `_resolution_pins`) — bounded today by dedup guards + per-host drop; observation, not a live leak.

**Metric:** RSS slope of the resident AO over a multi-hour soak while cycling new session_ids under GPU contention, plus fd/socket count and p99 first-token drift. **Not measured.** The root `soak_log.txt` is a ~46-min *fleet-process monitor* (process counts, scheduled-task states) — no RSS, no fd count, no growth-slope. The two accumulators (#1, #2) and disk growth (#4) have no measurement that would detect them. Recommend a `psutil` RSS + `num_fds` soak harness asserting a bounded slope.

---

## Resilience — *recovers after failure, and how fast*

**Verdict: Adequate.** Crash recovery *within the model-swap subsystem* is genuinely strong, but there is **no steady-state supervision** — nothing auto-restarts a crashed AO/PA/VM outside the swap path, so the dominant real-world failure (a core service dies during normal use) has a fully manual, unmeasured recovery time. (Single-user/single-box/air-gapped context lowers retry-storm severity but not the supervision gap.)

**Strong (context):** Swap crash recovery is textbook — `swap_state.py:114 _atomic_write` (temp + `os.replace`, never a torn record), write-ahead phase records, an idempotent boot reconciler (`:206`) that converges to "14B up, 30B down" and no-ops when nothing was in flight, and a `driver_alive` pid+create-time gate (`:181`) that distinguishes a crashed swap from a live one. Audit log is crash-consistent (per-record fsync, fail-safe rotation, atomic index rewrite, cryptographic chain detects post-crash tamper). Stale-lock reclaim (`instance_lock.py:104`). RESTART-AO retry is bounded + capped-backoff + launcher-alive-guarded. IPC waits are broadly bounded (`vsock.py:372,538,722`).

**Findings (worst-first):**
1. **No steady-state supervision — a crashed AO/PA/VM is never auto-restarted.** `orphan_guard.py` only prevents children *outliving* the launcher; `swap_driver.py:1915 _restart_with_retry` restarts the AO *only inside the swap teardown path*. The gateway's only health gate is boot-time (`transport.py:395`); after boot, a dead AO surfaces as per-prompt fail-closed errors (`:928-946`). **MTTR = time-until-human-notices + manual relaunch — unbounded, unmeasured.** Single largest recovery gap.
2. **Boot handshake gives up after ~3 attempts / ~15s, then hard-fails — shorter than the system's own cold-load worst case.** `transport.py:416` (3 attempts, 1/2/4s backoff) → `StartupState.FAILED`, permanent. Yet `timeout_registry.py:168` documents cold 14B load "can exceed 2 minutes" (`real_backend_ready`=180s). A transient-slow dependency is converted into a hard outage requiring full manual relaunch.
3. **No dependency circuit breaker or failover for the model backend.** The class named `CircuitBreaker` (`assistant_orchestrator/src/circuit_breaker.py`) is a token/recursion cap, *not* a dependency breaker — no open/half-open state. When OVMS/AO is unreachable, every prompt opens a fresh connection-per-message and fails closed; no fast-fail, no half-open probe, no degraded mode.
4. **No defined RTO/RPO; MTTR and restart-success unmeasured.** `timeout_registry.py` is a disciplined catalog of *abort ceilings*, not *recovery objectives*. No MTTR target, no restart-success counter, no measured "crash → serving again."
5. **Egress door has no transient-retry** (`guarded_fetch.py:886`) — a timeout/`HTTPError` maps straight to denied with zero retry; one network blip fails a whole idempotent-GET ingest, forcing manual re-issue. (A silent auto-retry is undesirable given fail-closed posture, but one bounded retry-with-jitter on idempotent GET would cut ingest MTTR.)
6. **Backoff carries no jitter anywhere** (`transport.py:417`, `swap_driver.py:1965`, `vm_manager.py:411` flat sleep, `policy_agent/src/boot.py:70-71`). Non-conformant with backoff-with-full-jitter norm. Low severity (single-box, no herd), but RESTART-AO + handshake could collide on the single-instance lock.
7. `launcher/process_launch.py:175` `WaitForSingleObject(self._h, _INFINITE)` — launcher liveness is hostage to a wedged child handle with no supervisory timeout.
8. Ingest-staging blob write is not atomic (`ingest_staging.py:127` `write_bytes` in place vs the temp+`os.replace` used elsewhere) — torn ciphertext on crash. Low impact: read side is AES-256-GCM AAD-bound and fail-closed, so corruption is *detected*, and the file is a transient handoff.

**Metric:** MTTR (crash → serving again), decomposed into `% of dependency boundaries with automatic detection+recovery` and `restart success rate`. **Not measured.** Recovery is bounded only in the swap driver (180s + 3 retries) and manual everywhere else. Highest-leverage next step: a steady-state supervisor loop with a recorded restart-success/MTTR metric — closes #1 and makes #4 measurable at once.

---

## Flexibility — *cost to adapt to new requirements* (the "code quality" dimension)

**Verdict: Adequate, leaning weak.** Real seams exist where they count (a tool registry, runner-injection points, centralized `shared/constants.py` + `timeout_registry.py`, clean IPC boundaries between most services), but they're undercut by god files and a "several parallel maps must mirror each other exactly" pattern that makes the single most-likely change — adding a tool, model, or egress provider — a multi-file, multi-location edit policed only by coupling tests.

**Findings (worst-first):**
1. **`entrypoint.py` — 5106 LOC god file.** One `AssistantOrchestratorService` class owns config load (`_load_entrypoint_config`, 285 LOC), config validation (`_validate_config_data`, 380 LOC of hand-rolled `_require_int_range`/`_require_float_range` where a schema would collapse it to a declaration), security-material build, substrate + knowledge-bank build, and **8 request handlers** with deeply-nested closures. Any new request type, config field, or image op edits this file — the merge-conflict epicenter.
2. **`launcher/__main__.py` — 2184 LOC, with an 826-LOC `main()` (`:1228-2053`)** doing admin-elevation → privilege-hardening → instance-lock → VM lifecycle → guest-parser → egress arming → voice → WinUI → cleanup as one linear procedure over 30+ helpers on implicit shared module state. No boot-phase registry to insert into; changing boot order or adding a phase is surgery on one function.
3. **"Add a tool" touches 5 parallel maps that must mirror exactly.** `tools.py:498 TOOL_SCHEMAS` + `:469 _REGISTRY` + `:651 _PRIMARY_STRING_PARAM`/`:659 _JSON_ARGS_TOOLS` + `:762 _TOOL_RISK_TIER` + `pgov.py:514 TOOL_CALL_ALLOWLIST`. The code admits it (*"Must mirror `_REGISTRY` exactly"*), enforced only by a coupling test. This is the **highest-frequency plausible change** and the most error-prone: forget one and a tool runs un-adjudicated or is allowlisted with no schema. A single tool-descriptor object with the allowlist *derived* would cut it to one site — the good pattern already exists (grammar/prompt derived from `TOOL_SCHEMAS`, "no drift surface"); it just isn't applied here.
4. **Egress/web-search provider is compile-time hardcoded.** `LiveKagiAdapter`/`KagiAdapter` baked into the launcher's `_maybe_register_web_search`; egress allowlist (`egress_guard.py:245`) widened imperatively with a hand-maintained IP-pin map. Adding a 2nd provider touches the adapter, launcher registrar, `TOOL_SCHEMAS`/allowlist, and egress-widening machinery — no `SearchProvider` interface to append to.
5. **Duplicated SSRF "blocked IP range" logic across two modules** — `egress_guard.py:264 _is_blocked_pin_ip` and `guarded_fetch.py:511 _is_blocked_ip` independently implement the same loopback/RFC-1918/link-local/CGNAT/reserved check. A new range to block must be fixed twice, in the security-critical layer.
6. **Cross-service reach into internals (bypassing IPC).** `ui_gateway/src/url_adjudicator.py:196,255` → `policy_agent.src.gpu_inference`; `ingest_coordinator.py:214,795,1042` → `cleaner.src.pipeline`; `ui_backend/src/dispatcher.py:578,684,765,790` → `voice.src.engine`. Lazy imports to dodge import-time coupling signal the coupling is unwanted — refactoring the target service's module layout breaks a different service.
7. Per-service `constants.py` shadow (`assistant_orchestrator` 79 LOC etc.) re-exports/renames `shared/constants.py` — a rename ripples through a re-export layer and hides the real dependency. Minor SSOT dilution.
8. Single-target hardware/model values frozen with "DO NOT modify" (`TARGET_MODEL="Qwen3-14B"`, VM disk path, GUID, `EFFECTIVE_CEILING_GB=31.323`). Reasonable for a locked appliance, but "swap the model" is a multi-file diff (constants + `30b`/`14b`-named load functions).
9. `swap_ops.py` (2216) + `swap_driver.py` (1988) — fleet monolith with model-count baked into function names (`real_load_30b`/`real_load_14b`); adding/reordering a phase edits the driver's private phase methods. Mitigated by injected `SwapOps` callables (a real test seam).
10. `acceptance.py` (2505) mixes schema-emission + LLM-output parsing + prompt compilation + Python/JS oracle codegen + ecosystem if-chain — a new target ecosystem touches extractor, validator, detector in one file.
11. Hardcoded ports as default-arg literals (`5001` AO, `8000` OVMS) in `swap_ops.py:1426`/`swap_driver.py`/`timeout_registry.py` rather than resolving from `constants.py`.

**Positives (so "weak" isn't misread):** `timeout_registry.py` is an exemplary centralization (every timeout documented + `live_value()` from config) — the model the tool/egress maps should follow. `runtime_config.py` gives clean deterministic resolution. Runner-seam DI in `tools.py` and injected `SwapOps` are proper substitution points. Services talk via `shared/ipc` in the overwhelming majority of cases.

**Metric:** Max file/function LOC, files-changed-per-feature, duplication. Max file **5106 LOC**; **22 files >1000 LOC**; max function **826 LOC**; add-a-tool = **≥5 edit sites / 2 files**; add-a-provider = **≥4 files**; SSRF logic duplicated **2×**; **4** cross-service internal imports. **Size/fan-out is not measured** — no max-LOC lint, no complexity gate. The coupling tests guarantee the 5 maps stay *in sync* but never push toward collapsing them to 1.

---

## Performance — *efficiency of one unit of work*

**Verdict: Adequate.** The heavy inference levers are genuinely wired into the runtime (speculative decoding ~2× *measured*, OV prefix caching, KV-cache warm path, INT4, NPU embedding offload 13.6× *measured*) — not benchmark-only capabilities. That's undercut by avoidable **per-turn host-side CPU/IO overhead** and by **zero in-runtime latency/throughput instrumentation**. Per Pike: the GPU forward pass dominates a turn, so most host findings are second-order — real and fixable, but not the bottleneck (flagged accordingly).

**Findings (worst-first):**
1. **Fresh mTLS SSL context (3 PEM disk reads + TLS handshake) built per IPC message** [SUSPECTED, hot path]. `transport.py:594-626` & `:688-699` call `create_client_ssl_context(...)` on every connection, and `_open_prompt_transport` opens a fresh connection *per message* (send_prompt, each tool round-trip, ingest, imagine, plan…). `vsock.py:251-258` does `load_cert_chain` + `load_verify_locations` (3 PEM reads) + context build, per unit. Connection-per-message is architectural, but **the SSLContext is reusable across connections** — build once at construction. Highest-signal *fixable* finding.
2. **Single global lock serialises all 14B generation across PA + AO** [MEASURED, by design, hot path]. `shared/inference/shared_pipeline.py:97` — one `threading.Lock` wraps every `.generate()`; PA classify + AO turn + N tool-call generations all funnel through it on one GPU model. Dominant throughput ceiling (PA 78ms mean/125ms P95; gen 3.59 tok/s median). Inherent to single-GPU/single-model, not a defect — but it's the measured constraint any concurrency ambition must reckon with.
3. **O(n²) streaming visibility filter — regex over full accumulated text per token** [SUSPECTED, hot path]. `gpu_inference.py:1217` calls `_visible_text("".join(streamed_chunks))` (`:404-429`, `_HIDDEN_BLOCK_RE.sub` + find/rfind over the whole accumulated response) on **every** chunk → O(M²) per M-chunk response, on the CPU thread draining the stream.
4. **Full re-tokenization of the output on every response** [SUSPECTED, hot path]. `gpu_inference.py:1281-1289` re-encodes the entire generated text through the HF tokenizer purely to get token IDs/count — a second full tokenizer pass per response for a number the pipeline could report directly.
5. **PGOV Stage-5 leakage re-embeds all retrieved chunks per response, on CPU** [SUSPECTED, hot path, grounded turns]. `pgov.py:1088-1089` runs the bge model over generated text + all N retrieved chunks every grounded response; chunks were already embedded at store time. Worse, the module-level `check_leakage → _get_detector()` path (`:1121`) defaults `device="CPU"` — the #720 NPU offload only applies to an explicitly-constructed singleton.
6. **Knowledge retrieval rebuilds the full embedding matrix + full sort per query** [SUSPECTED, hot path, small-N]. `knowledge_bank.py:1899-1903` reallocates the `(N,384)` matrix from the dict every `retrieve()` and `argsort`s all N when top-k would do (`argpartition`). Low-priority while N is small (Pike), but pure redundant work; the matrix could be maintained incrementally. (Good: the cache decrypts once at DEK-unlock, not per query.)
7. Prompt history JSON-encoded twice per turn (`transport.py:1623` sizing + `protocol.py:376` envelope encode) — bounded by 40KB cap, minor.
8. **No runtime latency/throughput instrumentation** [MEASURED absence]. `grep` for `opentelemetry|prometheus|histogram|p95|p99` across `services/`+`shared/` returns nothing. `perf_counter` timings exist but are returned per-call or logged, never aggregated. p50/p95/p99, tokens/sec, TTFT live only in `scripts/benchmark_*.py` + `PERFORMANCE_LOG.md`. A production regression is invisible between manual benchmark ceremonies — the biggest observability gap.
9. Dead/duplicated Python sampling + preemption path (`gpu_inference.py:_autoregressive_loop:1319`, `_sample_token:1533` full-vocab `argsort`, `statistics.median(step_times[:-1])` recomputed every step) — unreachable in the shipped `LLMPipeline.generate` flow. Not a live cost; delete or gate it.

**Positives:** Spec-decode, OV prefix caching, KV-cache precision, KV warm-prefill are real runtime code. PA's `DeterministicPolicyChecker.check` short-circuits the LLM on DENY/ESCALATE. All hot-path regexes compiled at module/class scope.

**Metric:** Per-turn latency (TTFT + total) and generation throughput (tok/s), with PA classification p95 as the gating sub-metric. **Measured — but only in `scripts/benchmark_*.py` + `PERFORMANCE_LOG.md`, not the runtime** (TTFT 876ms median, gen 3.59 tok/s, PA 78ms/125ms P95, spec-decode ~2×, offload 13.6×). Highest-value change: an in-runtime aggregator around `SharedInferencePipeline.generate` + the transport path.

---

## Cross-Dimension Notes (real tradeoffs)

- **One metrics gap serves three dimensions.** Stability (RSS/fd slope), Resilience (MTTR/restart-success), and Performance (p50/p95/p99, tok/s) are all *unmeasured in the runtime*. A single lightweight in-process telemetry layer would give all three their missing proxy — the highest-leverage cross-cutting investment.
- **The "mechanism exists but isn't wired" pattern spans Stability + Resilience.** `destroy_session` (stability leak #1) and a steady-state supervisor (resilience #1) are the same class of gap: correct code paths that never run in steady state.
- **Fail-closed posture (a Robustness/security strength) is in tension with Resilience.** The boot handshake hard-failing at 15s (resilience #2) and the egress door denying on one blip with no retry (resilience #5) are fail-closed choices that hurt recovery — the fix is bounded retry within the fail-closed envelope, not abandoning it.
- **DRY-vs-safety in the egress layer.** The duplicated SSRF IP-block logic (flexibility #5) is security-critical *and* duplicated — consolidating it improves flexibility and reduces the risk of the two copies diverging on a security fix.

---

## Prioritized Recommendations

Ranked by impact ÷ effort. Effort: **S** ≈ hours, **M** ≈ 1–3 days, **L** ≈ multi-day.

1. **Replace security-invariant `assert`s with explicit `raise`.** (Robustness #1) `entrypoint.py:2888,:3603`, `session_store.py:1411`, `adjudicator.py:376-377`. Removes a silent-bypass-under-`-O` risk on encryption + weight-integrity gates. **S**
2. **Add an in-runtime telemetry layer** — aggregate the existing `perf_counter`/`latency_ms` deltas into p50/p95/p99 + tok/s counters, and sample resident-process RSS + `num_fds`. Serves Performance #8, Stability metric, Resilience #4 at once. **M**
3. **Wire session teardown + a bounded soak test.** (Stability #1,#2,#5) Call `destroy_session` on disconnect/idle; add TTL/idle-reaper for orphaned session-keyed dicts; ring-buffer `_preemption_events`; add a `psutil` soak harness asserting bounded RSS slope across N sessions. **M**
4. **Add a steady-state supervisor loop** that health-checks AO/PA/VM and auto-restarts on death, recording restart-success + MTTR. (Resilience #1, makes #4 measurable) **M**
5. **Reuse the mTLS `SSLContext`** — build once at transport construction, reuse across per-message connections. (Performance #1) **S**
6. **Widen the boot-handshake budget to the cold-load ceiling** (~180s from `timeout_registry`) before `FAILED`, or make it retry against a not-yet-ready PA. (Resilience #2) **S**
7. **Collapse the 5-map tool definition to one descriptor** (schema + callable + tier + arg-shape), derive `TOOL_CALL_ALLOWLIST` from it. (Flexibility #3) **M**
8. **Route all untrusted IPC integer parsing through a `_require_int`-style guard** and reject container-typed fields instead of `str()`-coercing them. (Robustness #2,#3) **S**
9. **Consolidate the duplicated SSRF IP-block logic** into one shared helper used by both `egress_guard` and `guarded_fetch`. (Flexibility #5 / Robustness) **S**
10. **Set an explicit audit-log retention ceiling** (operator-configurable `archive_max_bytes`/`_age_days`) so disk growth is bounded by default. (Stability #4) **S**
11. **Fix the two O(n²)/redundant hot-path items** — incremental `_visible_text` (track only new suffix) and drop the per-response re-tokenization by reading token count from the pipeline. (Performance #3,#4) **S–M**
12. **Add a bounded retry-with-jitter on idempotent-GET egress timeouts** within the fail-closed envelope. (Resilience #5) **S**
13. **Introduce a real dependency circuit breaker** (open/half-open) for the model backend, distinct from the token-cap class. (Resilience #3) **M**
14. **Decompose `entrypoint.py` and `launcher.main()`** — extract config load/validate (→ a schema), split the 8 request handlers into a handler registry, break `main()` into boot-phase objects. (Flexibility #1,#2) **L**
15. **Delete the dead Python sampling/preemption path** (`gpu_inference._autoregressive_loop` et al.) to remove latent O(n²) code. (Performance #9) **S**
16. **Add a fuzz/property pass** (`hypothesis`) over `MessageFramer.decode_*`. (Robustness metric gap) **M**

---

*Which of these should I implement? Reply with numbers (e.g. "1, 5, 8"), "all", or "none". Selecting them authorizes the follow-up implementation work — the audit itself changed nothing.*
