# Part 4 — Sequenced Remediation Roadmap

*A proposed order of work, sequenced by **safety-critical-and-cheap first**, then **decisions you must make**, then **larger builds**. Nothing here is started — each wave is a set of proposals for you to triage into tickets at your own priorities. Gap IDs refer to file 02.*

**How to use this:** the first wave is small, high-value, and mostly things you *decide* rather than build. Read it, tell me which items to convert into tickets, and I sequence the rest against your priorities. You do not have to accept the whole roadmap to start — Wave 0 stands alone.

---

## Wave 0 — Do first: safety-critical, cheap, mostly decisions (days)

These protect against the worst outcomes and cost little. Most are a decision from you plus a small amount of work.

| # | Action | Gap | Your part |
|---|---|---|---|
| 0.1 | **Make the backup recovery key redundant + drill the restore onto a second machine.** The single highest-priority item in the review. | GS-1 | Decide the redundancy form (second printed copy / split-key); attend one restore ceremony |
| 0.2 | **Fix the public-mirror gate before the next weekly sync** (convert blocklist → allowlist + add the block/fail-off test). This review adds documents to the repo. | GS-3 | Approve the posture change (blocklist → allowlist) |
| 0.3 | **Scrub the drifted documentation** (egress "welded" comments, "dormant" config, mis-named boot step) + add the doc/reality reconciliation gate. | GX-2 | None (defect — I can fix on your say-so) |
| 0.4 | **Fix the broken disaster-recovery build command** (the dependency lockfile). | GS-2 (defect half) | None (defect) |
| 0.5 | **Decide the adjudication-door fork** (GP-1): formally scope host-mode to the deterministic checker + a structural chokepoint, or wire the full receipt. | GP-1 | The capability/posture decision |
| 0.6 | **Wire the built-but-unwired controls** (grader-strength check, boot canary) + add the reachability gate. | GX-1, GF-1 (partial) | None (defect, once GP-1 is decided) |

**Why this wave first:** 0.1 closes the only path to total irreversible loss. 0.2 stops this very review's documents from feeding a leaky channel. 0.3/0.4/0.6 are defects (no trade-off) that also happen to close a recurring class. 0.5 is the one decision that unblocks several later items.

---

## Wave 1 — The Management Layer (weeks; mostly cheap deterministic build)

The layer you feel every day (#878). Almost all of it is deterministic — zero GPU cost. Build it in the order detection → decision → action → training, because each depends on the last.

1. **The fused Command Surface + the read-only Operations pane** — muted-until-abnormal, top line = fleet liveness, silence = master alarm. *(GM-1, GM-5)*
2. **A rationalized alarm set** — symptom-based, rate-limited, flood-suppressed; each alarm names its own runbook. *(GM-1)*
3. **The static failure-translation map** — fingerprint-code → "what's wrong + your move," in code (works when the model is down). *(GM-2)*
4. **The operator runbook library** + the always-visible "STOP THE FLEET" button. *(GM-2, target 2.4)*
5. **Retire the stale operator docs + archive the legacy board projects.** *(GM-3, GM-4 — defects)*
6. **The escalation matrix** (wake-me / hold-till-morning / never) in plain language. *(target 2.4)*

**Later in this layer (needs more design):** the go/no-go poll, the recovery-first "fleet undo" spine, the operator "type rating" simulator, and the lightweight systems-safety pass to derive the full alarm set. These are the deeper R3/R0 build and can follow once the detection+decision core is live.

---

## Wave 2 — Factory hardening (weeks)

Make the machine you trust actually trustworthy. **The central question — how software you never read gets verified in a way you can trust — is detailed in file 05.**

1. **Grader strength** — wire the mutation-audit into the green path (weak → demote); add grader best-of-N + reference-impl pre-validation. *(GF-1)*
2. **Break the planner=grader correlation** — differential criteria re-derivation (ideally a second model family) + always surface plan assumptions. *(GF-2)*
3. **Durable self-memory** — auto-archive run records into git; one signed per-artifact attestation. *(GF-3)*
4. **Self-measurement** — stand up the defect-rate / false-done / leniency-drift trends; schedule the positive-control rigs. *(GF-4, GF-5)*
5. **Containment decision** — activate the coder containment or formally retire+harden the air-gap; turn the security lens on the builders. *(GF-6, GF-8)*
6. **Decomposition reliability** — templating + gold-set + already-satisfied pre-check. *(GF-7)*
7. **Declare one orchestration source-of-truth** across the two repos. *(GX-3)*
8. **Build the reviewable Intent Contract + the layered oracle stack** — EARS rules + worked examples you confirm in plain English, from which the tests are derived; gate on mutation score (not coverage); use the local 30B coder as the decorrelated cross-lineage check. *(GF-1, GF-2, GF-10 — see file 05)*

---

## Wave 3 — Product deepening (weeks-to-months)

Mature the core on the principle it already embodies.

1. **Security maturation** — provenance tags → information-flow lattice with one audited endorsement gate; action tokens → attenuable capabilities (macaroons); bake instruction-hierarchy + datamarking + injection-resistance into the finetune; stand up the AgentDojo security benchmark. *(target 2.2)*
2. **Harden the live deterministic gate** — property-test rule completeness; fix the Windows-host path model. *(GP-2)*
3. **Memory architecture** — verbatim-first storage; cheap associative memory (disk-backed graph + CPU PageRank); bi-temporal schema on SQLite; RAPTOR-style summarization over heavyweight graph-building; overnight consolidation. *(target 2.2)*
4. **Inference levers** — run the #715 answer-quality A/B, then decide on enabling INT8 KV on the 14B (measured sweet spot; already live on the 30B; ADR-040); confirm the speculative-draft device and re-measure the speedup. *(GP-6)*
5. **Extend idle-unload/zeroing to the knowledge bank.** *(GP-5 — defect)*
6. **Decompose the assistant god-object; add the decades data-lifecycle policy.** *(GP-7, GP-8)*

---

## Wave 4 — Decades survivability + operator competence (ongoing)

The long-horizon work that makes "decades" real.

1. **Offline archival** — dependency wheelhouse + second weights copy; model-agnostic upgrade runbook; interpreter-migration plan (before ~Oct 2027). *(GS-2, GS-4)*
2. **Preservation discipline** — treat the model + runtime + raw sources as archival objects; keep raw knowledge in open formats so a future model can re-ingest. *(target 2.5)*
3. **Operator type-rating curriculum + recurring game-day drills** on a sandboxed copy. *(target 2.4, R0)*
4. **The recovery-first "fleet undo" spine** (Rewind → Repair → Replay), with egress as the "already-sent" compensation case. *(target 2.4, R3)*

---

## The three things to decide first

If you read nothing else in this file, these three decisions unblock the most:

1. **The recovery-key redundancy + restore drill (0.1)** — protects against total loss; decide the redundancy form and pick a date for the ceremony.
2. **The public-mirror posture: blocklist → allowlist (0.2)** — a security-posture decision, needed before the next public sync.
3. **The adjudication-door fork (0.5)** — decide whether host-mode's live gate is formally the deterministic checker (recommended) or gets the full cryptographic receipt wired in; this unblocks the security-maturation work and resolves the flagship divergence.

Everything else can be sequenced against your priorities once these are settled.
