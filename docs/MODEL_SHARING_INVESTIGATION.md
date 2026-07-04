# Model-Sharing Investigation — One 14B, Not Two

**Date:** 2026-05-22
**Author:** Blair + Claude (Opus 4.7)
**Status:** Findings — input to a possible ADR-012 amendment
**Trigger:** RAM measured at \~17 GB with BlarAI running (system 24.5 / 31.3 GB
used, < 7 GB free). Boot \~43–56 s. Blair asked why the 14B model is loaded twice.

---

## 1. The question

Why does BlarAI compile and hold the Qwen3-14B model **twice** — once for the
Policy Agent, once for the Assistant Orchestrator — and can the two share one
copy to reclaim the memory and the boot time?

## 2. Headline finding — the code diverged from ADR-012

ADR-012 §2.1 lists the model's consumers and is explicit:

> Consumers | PA (M2), AO (M3), USE-CASE-005 (Code Agent) | **Unified model —
> single compilation, shared weights**

ADR-012 §3.1.2: *"Unified model confirmed. PA, AO, and USE-CASE-005 all share
the same Qwen3-14B target model. This simplifies weight loading (**single GPU
compilation**, shared weights) …"*

**The locked architecture decision was one compilation, shared. The running
code does two.** Measured from `launcher.log`: the Policy Agent
(`PolicyGPUInference`, `services/policy_agent/src/entrypoint.py:304`) and the
Orchestrator (`OrchestratorGPUInference`,
`services/assistant_orchestrator/src/entrypoint.py:244`) each independently
construct an `ov_genai.LLMPipeline` for `models/qwen3-14b/openvino-int4-gpu`
and each compiles it for the GPU (\~15 s + \~18 s). Two \~8–9 GB compiled copies
end up resident at once.

This is an **implementation gap**, not a deliberate design choice — no ADR
rescinded the "single compilation" intent.

## 3. Measured cost

| Metric | Measured |
|---|---|
| BlarAI footprint, idle (model loaded) | \~17 GB (GPU "Local Usage"); system 24.5 / 31.3 GB used |
| Compiled-model copies | 2 × \~8 GB |
| Boot — model compile | PA \~15 s + AO \~18 s ≈ 33 s of a \~43–56 s boot |
| Free RAM while running | < 7 GB |

A single shared copy would, in principle, free \~8 GB and remove one \~15–18 s
compile from every boot.

## 4. Why it diverged — construction-config drift

The two pipelines are no longer identical, which is why "just share one" is not
a trivial revert. Their **construction-time** configuration differs:

| Construction-time config | Policy Agent | Orchestrator | ADR-012 says |
|---|---|---|---|
| Draft model | `qwen3-0.6b` (full 28L INT4) | `qwen3-0.6b-pruned-6l` (INT8) | both: `qwen3-0.6b` full (§2.6) |
| `enable_prefix_caching` | OFF | ON | OFF for all profiles (DEC-06) |
| `MODEL_PRIORITY` | HIGH (priority 0) | MEDIUM (priority 1) | — |

The Orchestrator's draft-model and prefix-caching changes came from the
streaming / draft-model work (see `BUILD_JOURNAL.md`, 2026-05-22 entries) and
were never reflected back into ADR-012. The Policy Agent still matches ADR-012.
So there are really two drifts here: the lost "single compilation," and the
AO's pipeline config moving away from the ADR.

## 5. Is sharing feasible? Yes

Both services run **in one process** — measured: a single `python` process
holds the launcher, Policy Agent, Orchestrator, and TUI. Sharing therefore does
**not** need a separate inference server; an earlier claim that it would need
"a substantial re-architecture" was wrong and is corrected by this measurement.

The settings that genuinely differ per use — `max_new_tokens` (PA 10, AO
variable), thinking mode (PA `/no_think`, AO thinking allowed), stop tokens —
are all `GenerationConfig` passed **per `.generate()` call**, not at pipeline
construction. One `LLMPipeline` can serve both callers, each passing its own
per-call config.

What must be unified is the **construction-time** config in §4: one draft
model, one prefix-caching setting, one priority.

## 6. What the change requires

1. **Reconcile construction config** — choose one draft model and one
   prefix-caching setting. These were tuned empirically for streaming, so they
   must be re-checked, not guessed (the pruned draft enables streaming; the PA
   does not stream, so the AO's needs likely win). Record the outcome as an
   ADR-012 amendment.
2. **Shared-pipeline refactor** — build the `LLMPipeline` once and have both
   `PolicyGPUInference` and `OrchestratorGPUInference` reference it, instead of
   each calling its own `load_model()`.
3. **Serialize access** — one pipeline cannot serve two concurrent
   `.generate()` calls. For a single-user local assistant, serializing PA
   classification against AO generation is acceptable, but it is a real
   behaviour change and needs an explicit lock.
4. **Preserve Policy Agent isolation (security)** — the PA is the security
   gate; its classification must stay isolated from AO conversation state. Both
   callers already invoke `.generate()` with self-contained prompts (no
   pipeline-side chat state), so isolation is preservable — but it must be
   explicitly verified, not assumed. `shared/models/weight_integrity.py`
   already treats PA/consumer weight-sharing as a known, mitigated coupling
   ("Red Team ISSUE-003").
5. **ADR-012 amendment** — record the draft-model + prefix-caching
   reconciliation and re-affirm "single compilation, shared."

## 7. Does the Policy Agent need the 14B at all?

A separate question Blair raised. ADR-012 locks the 14B for the PA, and the
2,000 ms PA latency budget (§2.5) accommodates it (the PA generates only \~10
tokens). Notably, ADR-012 §2.4 records that the PA's *hardest* decisions
(ESCALATE) are carried by the **DeterministicPolicyChecker** — 10 regex rules —
not the LLM; the thinking-mode experiments measured the LLM path alone at only
0.61–0.72 quality. So the PA leans on deterministic rules with the 14B as a
backstop classifier. Switching the PA to a smaller model is therefore plausible
*on quality grounds* — but it is a distinct ADR-012 amendment and is **not
required** for the memory win: sharing the single 14B (as ADR-012 already
intended) halves the footprint regardless of which model the PA uses.

## 8. Recommendation

Worth doing. It frees \~8 GB of RAM and \~15 s of every boot, and it realigns the
code with the locked ADR-012 architecture. But it is a deliberate,
sprint-sized change touching the **security-critical PA inference path**: it
needs the empirical config reconciliation, careful tests, an ADR-012
amendment, and live boot + classification verification. It is not a quick
patch and should be its own focused effort.

The perf-tracking dataset (`docs/performance/perf_history.jsonl`) now holds a
pre-change baseline; re-running `scripts/perf_snapshot.py` after the change
will measure the result directly.
