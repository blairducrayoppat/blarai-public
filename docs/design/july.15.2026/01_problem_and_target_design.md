# Part 1 — The Problem Set as Plain Requirements · Part 2 — The Target Design

*This is the design an expert would draw for BlarAI's actual problem today, and the requirements it must satisfy. It is what the gap register (file 02) measures the running system against. It is deliberately hardware-anchored: every choice is costed against one 31.3-gigabyte Lunar Lake laptop that is simultaneously the development box and the production machine.*

---

# PART 1 — THE PROBLEM, RESTATED AS REQUIREMENTS

BlarAI's problem set, stripped to its essentials:

> A **single non-technical person** wants a **private-by-construction, locally-run AI system** that will **last decades** on **his own hardware**, that he can **build and operate without reading code**, and that **never leaks his data**.

Five plain-language requirement families fall out of that sentence. The whole design serves these.

**R-PRODUCT — The AI itself must be genuinely private and genuinely capable, on one small machine.**
- All inference local; no data leaves the machine except through deliberate, gated, ceremony-opened doors.
- Every dangerous action passes through one adjudication point; every error path denies (fail-closed).
- Content-bearing data is encrypted from birth; decrypted bytes never rest on disk.
- The system reasons well over decades of the operator's accumulated knowledge — which must be *found*, not just *stored*.
- All of the above fits alongside one resident ~14-billion-parameter model in ~31.3 GB of unified memory, on an integrated GPU, with no cloud and no second large model available.

**R-FACTORY — The machinery that builds the system must produce correct software the operator never reads.**
- Intent enters in plain language; correctness is judged by machines the operator can trust.
- "Done" must be honest — impossible to fake from inside the builder's reach.
- The judgment of correctness cannot rest on a single AI model checking its own kind of thinking.
- The Factory must keep a durable, tamper-evident record of what it built and merged, and must measure its own defect rate over time.
- The Factory's own components (its coder, its build environment) are themselves an attack surface and must be secured like the product.

**R-MANAGEMENT — The operator must be able to detect, decide, and act, despite being non-technical.**
- **R0 (training floor):** manufacture just enough operator competence to command the system safely.
- **R1 (detection):** the operator reliably knows *when* something has gone wrong.
- **R2 (decision):** the operator knows *what to do* — every alarm carries its own plain-language procedure.
- **R3 (action):** the operator can safely fix novel problems he does not understand, because every action he can reach is safe-by-construction and reversible.

**R-SURVIVE — The system must outlive hardware generations, model generations, and dependency rot.**
- A *tested* path to restore the encrypted data onto new hardware; no single point of total loss.
- The model, its runtime, and the raw knowledge are all archival objects that must survive format and hardware change.
- The build must be reconstructible decades from now without depending on any third party still existing.

**R-CROSS — Two constraints bind everything above.**
- **The operator can never take manual control.** He is non-technical permanently, by design. Therefore *vigilance can never be the safety mechanism* — safety must be structural and reversible. This is the single most consequential requirement in the whole set, and it is the thread through the entire target design.
- **Memory is the scarcest resource.** Every design choice is costed against the real budget below.

### The real hardware budget (what every choice is costed against)

| Resident item | Footprint | Note |
|---|---|---|
| Qwen3-14B INT4 weights | ~9.7 GB | the resident "brain," shared by the security gate and the assistant |
| **KV cache at 32K context (FP16)** | **~5.0 GB** | **the largest *elastic* cost — it grows with context and is where the memory budget actually binds** |
| OS + app + Python services | ~6–10 GB | measured as In-Use, not working-set sums |
| Everything else (draft model, embeddings, retrieval working set) | the remainder | realistic free headroom is **~8–14 GB, and it shrinks as context grows** |

Two facts drive the whole product design: (1) the memory bottleneck is the **KV cache**, not the fixed model weights — so the highest-leverage lever is KV-cache *quantization*, not a smaller model; and (2) the product's 14B brain and the Factory's 30-billion-parameter coder **cannot both be in memory at once**, which is why the Factory must physically swap one model out to load the other.

---

# PART 2 — THE TARGET DESIGN

## 2.1 The unifying principle (the spine of everything)

**Safety by construction and reversibility, never by vigilance or by a smarter model.**

This single principle, forced by R-CROSS (the operator can never take over), is the answer in three domains the literature treats as separate — and connecting them is the core design insight:

- **In security:** trust lives in a small, deterministic, non-AI plane (rule-checker + single door + signed capabilities). The model is treated as untrusted. Making the model bigger or adding a second model does not help (proven empirically — see file 04). *This is why the shared-single-14B constraint is not a security limitation.*
- **In operations:** every control the operator can touch sits *inside* a guaranteed-safe boundary (an "envelope"), so he literally cannot command a catastrophe — only choose among safe options.
- **In recovery:** every action is *undoable*. The system optimizes for fast, cheap recovery from error rather than for never erring (Recovery-Oriented Computing). Because a non-expert *will* make mistakes, mistakes must be cheap.

Everything below is an application of this one principle.

## 2.2 Product target design

**Security (mature the plane you already have; do not chase a bigger model).**
- **Resolve the adjudication-door fork.** Either (a) wire a real, receipt-checked verdict into the live path (an in-process "verdict token" chokepoint is the cheap, hardware-fitting form), or (b) formally record that host-mode's live gate is the deterministic checker + prompt/output governance, and reserve the cryptographic receipt for the future multi-process topology — and rewrite the vision to match. **Recommendation: (b) now, (a)'s structural-chokepoint idea folded in** — make the single door a place code *cannot* skip, rather than a discipline it chooses to honor.
- **Mature the provenance tags into a real information-flow label.** Today an untrusted/trusted bit; the target is a two-axis (who-may-read, who-may-influence) label on a lattice, propagated automatically, with *one* audited, fail-closed operation that is the only bridge from untrusted to trusted (the "endorsement" gate). This is the rigorous form of "untrusted content never gains instruction authority," and it is deterministic and cheap.
- **Mature the action tokens into attenuable capabilities (macaroons).** Today a single-use signed token is a one-bit capability; the target carries caveats ("only this tool, only on data of this provenance, only before this time, only for this intent") and can only be *narrowed* as it passes down a tool chain. This is a solved 1988–2014 problem the agent field is currently reinventing.
- **Harden the model itself at training time (nearly free, and you own the finetune).** Bake in an instruction hierarchy (system > user > tool-content), datamarking of untrusted spans, and injection-resistance training (StruQ/SecAlign). These compose with the deterministic plane rather than replacing it.
- **Stand up a standing security benchmark (AgentDojo)** against your own model + gate, so the security claims become a regression-locked *number*, matching your existing measure-everything culture.

**Memory & knowledge (local-native, decades-safe, cheap on this box).**
- **Verbatim-first storage** as the durable primary layer — raw chunks beat model-extracted summaries for retrieval *and* survive model generations (a future model can re-ingest raw text; it cannot re-derive this model's extracted ontology). Extraction becomes a *secondary, lazy* index.
- **Keep the existing hybrid retrieval** (dense vectors + keyword BM25 + reciprocal-rank fusion) — the external literature validates it as exactly right. Put the whole thing inside SQLite (sqlite-vec + FTS5), no server.
- **Add cheap associative memory** (HippoRAG-style): a disk-backed entity graph queried by Personalized PageRank on the CPU — milliseconds, negligible RAM — giving "what connects X and Y across my decades of notes" in a single model call. The one cost (building the graph) runs in the overnight window.
- **Adopt a bi-temporal schema** (every fact carries *when it was true* and *when it was learned*; superseded facts are invalidated, not deleted) on SQLite — not a heavyweight graph server. Essential for a decades memory ("I moved cities in 2021, then again in 2024" must be representable without contradiction).
- **Consolidate memory overnight** ("sleep-time compute"): the 23:00 GPU window does the expensive memory-linking, index rebuilds, and (see survivability) compaction — off the live path. All such self-edits are advisory-only, respecting the self-governance boundary.

**Inference (the hardware levers).**
- **Make KV-cache quantization a first-class dial** — the single biggest reclaimable chunk of the fixed memory budget. This is **measured, not hypothetical**: the 2026-07-01 sweep (#709) found **INT8 (u8) is the sweet spot** — KV 5.0→2.5 GiB *and* 2.3× faster prefill at 32K; GPU support is confirmed and INT8 KV is **already live for the 30B coder**. It is deliberately *not* enabled on the product 14B — that flip is gated on the answer-quality A/B (#715), which has not yet run (INT4 saves more memory but risks long-context recall, so INT8 is the candidate). Target: run #715, decide, and record it (now ADR-040). Tie the dial to workload; quality first, so not free.
- **Re-verify the speculative-decoding configuration.** External measurement on your exact chip shows draft-on-NPU is a net *slowdown*; the mandated ~2× speedup must be coming from draft-on-GPU. Confirm the resident config and re-measure — a concrete, checkable item.
- **Codify the silicon-placement rule:** embeddings/encode on the NPU, decode + KV on the GPU, speculative draft on GPU or CPU but *never* the NPU.

**Structural health.**
- **Break the "built-but-wired-into-nothing" class once, structurally** — a reachability gate test that fails when a control has no live caller. This single control addresses a pattern that recurs across the whole system (the flagship door, the oracle strength-check, the boot canary, the dead router).
- **Add a documentation/reality reconciliation gate** — a test that fails when a docstring or config comment contradicts the live configuration. This closes the honesty-drift class permanently.
- **Decompose the assistant "god-object"** (~5,700 lines, ~40 responsibilities in one class) into real sub-services, so seams stop hiding inside it.
- **Add a decades data-lifecycle policy** — retention, compaction, and tombstone-purge for the growing stores; nothing reaps them today.

## 2.3 Factory target design

**Fix the keystone: make the model-authored grader trustworthy.**
- **Wire in the strength check.** The mutation-audit tool that measures whether the grader's tests actually discriminate right code from wrong is built but connected to nothing — connect it into the "green" path as at least a recorded advisory, with a weak-grader → demote policy. Add grader best-of-N and reference-implementation pre-validation.
- **Break the planner = grader-author correlation.** Re-derive the acceptance criteria with a *second, deliberately different* pass (ideally a different model family, or a non-AI static check as one "version") before certifying — the direct answer to the Knight-Leveson correlated-failure result. Always surface the plan's assumptions to the operator so a silently-dropped feature is visible.

**Give the Factory a durable memory of itself.**
- **One signed, git-durable attestation per built artifact**, unifying supply-chain provenance (which pipeline built this, reproducibly) with AI-authorship provenance (which model, under which policy, endorsed at which ceremony by which human) — shaped to a record-keeping standard so it doubles as governance evidence.
- **Stand up the self-measurement instruments** (defect-rate, false-done-rate, grader-strength, leniency-drift trends) that are designed but not running — the proven need is a real incident where the same job passed seven nights running while its quality silently degraded.
- **Schedule the false-done positive-control rigs** into the campaign, so "zero false-dones" means "the detector provably fires," not merely "nothing tripped it."

**Secure the workshop like the product.**
- **Decide the coder-containment question:** the prompt-injectable local coder runs elevated with its restricted-account + firewall containment dormant. Either activate it or formally retire it and harden the air-gap.
- **Turn the product's security lens on the builders.** The build agents plausibly hold all three legs of the data-exfiltration "lethal trifecta" (secrets + untrusted content + internet). Apply capability-tagging, existence-checks against invented dependency names ("slopsquatting"), and the dual-model separation you already trust for the product.

**Resist aging (the Factory's changes are all made by stateless agents — "ignorant surgery" is its default).**
- Encode the design's invariants as **fitness-function tests the Factory runs on itself** (layering rules, the single-door invariant, the egress-lock count) so a change that erodes the architecture is blocked and cites the decision it would break.
- Maintain a **living assurance-case argument** ("safe to run and evolve for decades") over the governance trail the Factory already emits — but have it *challenged by an independent party*, never self-graded (a green self-assessment is the most dangerous artifact it could produce).

## 2.4 Management-layer target design (the concrete build)

A single fused **Command Surface** for a non-expert, drawn from control-room, aviation, and recovery-computing practice. Nine components:

1. **One overview surface** (in the desktop app), styled the way petrochemical control rooms are: **muted and colorless until something is abnormal**, so the one thing wrong is the highest-contrast object on screen. Top line = **fleet liveness**; its *silence* is the master alarm.
2. **A rationalized alarm set** — every alarm justified, actionable, symptom-based, rate-limited (a hard budget, e.g. no more than one routine alarm per ten minutes), with flood-suppression. Today there is *zero* formal alarm design.
3. **An operator runbook library** ("Quick Reference Handbook") — plain-language, do-then-confirm procedures, each keyed so that **every alarm names its own procedure**. Authored by Claude sessions, served deterministically.
4. **An escalation matrix** you read and edit in plain language: wake-me for X, hold Y till morning, never bother me with Z.
5. **A pre-ceremony go/no-go poll** — before any go-live, each subsystem reports GO/NO-GO into one readiness view, so a ceremony becomes "read a green board and click go," not "click go and hope."
6. **An always-visible "STOP THE FLEET" button** (a Toyota-style Andon cord) — pull on suspicion alone, no diagnosis required; it pauses all agent activity and summons a Claude session.
7. **A recovery-first spine:** intent-log every fleet action, snapshot state, and offer a **Rewind → Repair → Replay** "fleet undo." Guarded auto-remediation runs only for *reversible* fix classes, through the single adjudication door; anything irreversible is a ceremony. The whole operator surface is an **envelope** — every reachable button is inside a guaranteed-safe boundary.
8. **An operator "type rating":** a Claude-authored ground-school + a **safe simulator** that injects failures on a sandboxed copy so you rehearse a crisis before it is real + supervised ceremonies + a check-ride before the first egress go-live, refreshed by periodic "game days."
9. **A lightweight systems-safety pass** to *derive* the alarm set and the guardrails rather than guess them.

**The hardware-placement rule for all of the above:** default to deterministic/templated (zero GPU); use the resident 14B only for real-time, low-grain translation (competes with the assistant, so budget it tightly); route all hard or novel diagnosis to a Claude session (async, zero runtime cost). **Critically, plain-language failure translation must be static/rule-based** — the 14B is unavailable exactly when the operator most needs an explanation (the backend is down, memory is exhausted, boot failed).

## 2.5 Survivability target design

- **Drill the encrypted-restore-onto-new-hardware path** end to end (an LA-present ceremony needing a second machine with a compatible security chip), and **make the recovery key redundant** (a second printed copy, or a split-key scheme) so it is not a single point of total loss.
- **Fix the disaster-recovery build** (the dependency-install command is currently broken as written) and **archive dependencies + a second copy of the model weights offline**, so a decades-later rebuild does not depend on any third party still existing.
- **Convert the public-mirror gate** from a blocklist (which already leaked the machine hostname) to an allowlist of publishable paths, with a test that proves it blocks when engaged and fails when disabled.
- **Treat the model and its runtime as archival objects** — with verbatim raw sources kept in open formats, a future model can re-ingest even if this one cannot be run; write a model-agnostic upgrade runbook and plan the interpreter migration (the current Python reaches end-of-life ~October 2027).
