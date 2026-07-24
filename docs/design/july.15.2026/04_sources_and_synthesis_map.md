# Appendix — Sources & Synthesis Map

*Where every idea came from, and the novel "connect-the-dots" combinations the review produced. This appendix is deliberately portfolio-grade: it is the kind of literature-to-mechanism mapping that supports the AI-Governance-Professional certification and the community-contribution narrative. The method was: seed from named papers, snowball two hops through open citation graphs (arXiv / Semantic Scholar / OpenAlex), prefer primary and small-researcher sources, and pass every idea through the hardware filter before admitting it.*

**Honesty flags carried from the research (do not cite externally without checking):** a handful of benchmark percentages reached the researchers through a summarizer rather than a direct read of the results table (marked `[verify-number]` in the raw notes). The "verbatim-beats-extracted-storage" claim rests on a *single* January-2026 ablation — directionally useful, not settled. Several 2026-dated speculative-decoding arXiv IDs surfaced but were not individually verified and are not relied on. The mechanisms, authorships, and architecture claims are high-confidence; the exact numbers are not, until pulled from the primary source.

---

## 1. The load-bearing external finding (why your hardware worry dissolves)

The entire modern field of securing AI agents has independently re-derived one thesis: **a language model is an untrusted component; security must come from a deterministic control/data-flow layer *outside* the model, not from a bigger or a second "more trusted" model.** Google DeepMind's own Gemini-hardening paper states it plainly — even an adversarially fine-tuned frontier model still exfiltrated data; *"raw model size won't save you."* This is the empirical warrant that BlarAI's shared-single-14B constraint costs nothing essential in security: the security was never supposed to live in the model.

Key sources: DeepMind *CaMeL / "Defeating Prompt Injections by Design"* (arXiv:2503.18813); DeepMind *"Lessons from Defending Gemini"* (2505.14534); Microsoft *FIDES / Information-Flow Control for agents* (2505.23643); Berkeley *Progent* (2504.11703); ETH/Invariant *"Design Patterns for Securing LLM Agents"* (2506.08837); Willison *"lethal trifecta"* + *"dual-LLM pattern"*; and the nearest published prior synthesis, *"Systems Security Foundations for Agentic Computing"* (2512.01295) — which validates the premise and means the review's novelty is the *mechanism-level mapping onto BlarAI specifically*.

---

## 2. Source map by domain

**Agent security (attacks & benchmarks):** Greshake et al. *indirect prompt injection* (AISec 2023); Rehberger *Embrace the Red* (memory-poisoning, exfiltration); Debenedetti et al. *AgentDojo* (NeurIPS 2024); OWASP Agentic Security Initiative; MITRE ATLAS.

**Agent security (defenses):** CaMeL; FIDES; Progent; IsolateGPT (NDSS 2025); the six Design Patterns; Task Shield (ACL 2025); MELON (ICML 2025); Spotlighting/datamarking (Microsoft); the Instruction Hierarchy (OpenAI); StruQ/SecAlign (USENIX 2025).

**Classical security foundations the agent field is reinventing:** Saltzer & Schroeder (1975); Lampson *confinement problem* (1973); Denning lattice / Bell-LaPadula / Biba (1973–77); Myers & Liskov *decentralized information-flow control* (1997); Miller *object-capabilities / "Robust Composition"* (2006); Hardy *the confused deputy* (1988); Birgisson et al. *Macaroons* (NDSS 2014); Rutkowska *Qubes / disposable VMs*; Agache et al. *Firecracker* (NSDI 2020); Rushby *separation kernels* (1981).

**Durability & local-first:** Kleppmann et al. *Local-first software* (Onward! 2019); CRDTs; Ink & Switch *Keyhive*; Perkeep content-addressing; restic/borg/ZFS backup discipline; the OAIS digital-preservation model.

**Memory & personal-AI architecture:** *CoALA* memory taxonomy (TMLR 2024); MemGPT/Letta; *HippoRAG* 1 & 2 (NeurIPS 2024 / ICML 2025); *Zep/Graphiti* bi-temporal graph (2025); Microsoft GraphRAG + its cost critique → LightRAG / LazyGraphRAG / RAPTOR (ICLR 2024); Anthropic contextual retrieval; ColBERT late-interaction; A-MEM / Mem0 / Letta sleep-time compute; Matryoshka embeddings (NeurIPS 2022).

**Constrained local inference:** *NITRO* (Intel-laptop-NPU inference, 2412.11053) + OpenVINO discussion #36484 (measured on the 258V itself); KIVI / KVQuant KV-cache quantization; EAGLE-3 / LayerSkip speculative decoding; llama.cpp imatrix + mmap discussions; sqlite-vec + FTS5.

**Automation trust & human factors (the Factory + Management spine):** Bainbridge *Ironies of Automation* (1983); Parasuraman/Sheridan/Wickens *levels of automation* (2000); Lee & See *trust calibration* (2004); Parasuraman & Manzey *complacency* (2010); Endsley *situation awareness* (1995); Klein *Recognition-Primed Decision*; Santoni de Sio & van den Hoven *Meaningful Human Control* (2018); Knight & Leveson *N-version independence fails* (1986).

**Software aging & maintenance:** Parnas *Software Aging* (1994); Lehman's laws; architecture-erosion surveys; Ford et al. *fitness functions / evolutionary architecture*; software rejuvenation (FTCS 1995).

**Control-room / aviation / recovery (the Management layer):** ANSI/ISA-101 high-performance HMI; ANSI/ISA-18.2 & EEMUA-191 alarm management; Google SRE alerting + the CASE method; aviation Quick Reference Handbook design; Degani & Wiener *flight-deck procedures*; Gawande *Checklist Manifesto*; NASA go/no-go + flight rules; Incident Command System; Toyota Andon / poka-yoke; Airbus flight-envelope protection; **Recovery-Oriented Computing** (Patterson/Fox/Brown, Berkeley/Stanford 2001–2004) + *"Undo for Operators"* (USENIX ATC 2003, Best Paper); Kubernetes reconciliation; IBM autonomic computing / MAPE-K; Nygard *Release It!*; Leveson STAMP/STPA; Cook *How Complex Systems Fail*; aviation type-rating; chaos-engineering game days.

**Factory provenance & supply chain:** in-toto (USENIX 2019); SLSA; NIST Secure Software Development Framework; SBOM (SPDX / CycloneDX); Sigstore + reproducible builds; Thompson *Reflections on Trusting Trust* (1984) + Wheeler *Diverse Double-Compiling*; the xz-utils backdoor; Spracklen et al. *package hallucination / slopsquatting* (USENIX 2025); Perry et al. *insecure code with AI assistants* (CCS 2023); EU AI Act (record-keeping, human oversight).

---

## 3. The novel dot-connections (the synthesis payload)

*Combinations the research could **not** find published together, but that fit BlarAI specifically. Each carries a skeptic's note — the reason it might not hold — because a connection you cannot break is a connection you have not tested.*

**DC-1 · The one principle under three domains: safe-by-construction + reversibility.**
The single deepest connection in the review. The requirement that the operator can *never* take manual control forces the *same* answer in three fields the literature studies separately: security (trust the deterministic plane, not a smarter model), operations (wrap every operator control in a guaranteed-safe envelope), and recovery (make every action undoable — Recovery-Oriented Computing). Fusing security's "deterministic plane," aviation's "flight-envelope protection," and Berkeley's "recovery-oriented computing" into one design principle for a personal AI system is, as far as the hunt found, unpublished.
*Skeptic's note:* reversibility is bounded — anything that already crossed the egress boundary (a search query, a public push) cannot be un-sent; "undo" is honestly *undo + compensation*, and must be advertised as such or it over-promises safety.

**DC-2 · Object-capabilities + macaroons as the rigorous form of your action tokens.**
Your single-use signed tokens are already an object-capability system; naming them as such lets you adopt the finished 1988/2006/2014 answers (bound *authority* not just *permission*; carry attenuable caveats; narrow-only down a tool chain) that the agent field is currently reinventing without citation.
*Skeptic's note:* macaroons are bearer credentials — if one leaks from host memory the caveats are all that stand between an attacker and the action, so they must be tight; and bounding *transitive* authority is hard for tools with side effects.

**DC-3 · Biba low-water-mark + decentralized information-flow control as the engine under your provenance tags.**
"Once an agent ingests untrusted content, bar it from consequential actions" is the 2025 agent-security design-pattern core — and it is Biba's 1977 integrity rule verbatim. Mature the 1-bit tag into a two-axis lattice label with a single audited endorsement gate; the self-governance boundary ("the system cannot declassify its own core") is *literally* decentralized-information-flow-control's "no owner unilaterally relabels shared data," which no agent paper connects.
*Skeptic's note:* the chronic failure is over-tainting — if reading any untrusted content taints the whole session to uselessness, the operator routes around the control. The endorsement gate is where all the risk concentrates; tuning that one operation is the whole game.

**DC-4 · The confused-deputy lens unifies the entire agent-tool boundary.**
State the whole problem in one 1988 sentence: *a tool-calling agent is a confused deputy holding ambient authority while being fed untrusted content designed to misdirect it; the fix is to de-ambient-ize the deputy — authority travels with the validated, intent-bound request, never sits in the agent.* This unifies the deterministic plane, capabilities, and information-flow control under one classical idea a non-expert can follow.
*Skeptic's note:* capabilities fix the *authority* half cleanly, but an LLM's "authority" includes its trained-in willingness to be persuaded, which no token can externalize — the *confusion* half is only mitigated (by training-side hardening), never eliminated.

**DC-5 · Verbatim-first, extract-lazily, structure-overnight — the memory default the hardware forces.**
The central tension of the whole review — rich memory wants many model calls, but the box has one slow GPU — resolves by making the *raw* layer free and decades-safe (raw text survives model generations) and treating *all* structure (association graphs, summaries, contextual prefixes) as a cache rebuilt in the overnight window.
*Skeptic's note:* "lazy" means cold queries into never-structured regions get only flat retrieval; and verbatim-beats-extracted rests on a single 2026 ablation — keep the extracted index so you can A/B it on your own eval gate.

**DC-6 · Sleep-time compute unifies memory consolidation, index rebuilds, and durability compaction on the 23:00 window.**
One overnight job does three chores that all need the GPU-idle window and are studied separately: memory linking/consolidation, expensive index (re)builds, and the tombstone-compaction that a decades CRDT-based sync would otherwise let grow without bound. A durability problem, a memory-architecture mechanism, and a hardware fact, connected into one job.
*Skeptic's note:* overnight edits must stay advisory (self-governance boundary); and compaction that rewrites the encrypted store is a data-integrity hazard — snapshot-before / verify-after is mandatory.

**DC-7 · KV-cache quantization as the context-length/headroom *dial*, not a throughput trick.**
Reframe KV-quant from "faster tokens" to "the single biggest reclaimable chunk of a fixed 31 GB budget" — the lever that decides whether a rich memory index and the 14B can both be resident.
*Skeptic's note:* OpenVINO GPU KV-quant support is **confirmed and the sweet spot already measured** (INT8, 2026-07-01 sweep; already live for the 30B coder) — a measured lever, not an open question. The remaining gate is **answer quality** (#715): INT4/2-bit KV degrades exactly the long-context recall a memory system leans on, so **INT8 is the candidate** (not INT4), it must pass the eval-quality A/B before flipping on the 14B, possibly per-workload rather than globally. Now recorded in ADR-040.

**DC-8 · Knight-Leveson correlated failure as the quantified indictment of same-model author≠verifier.**
The Factory's "author agent ≠ verifier agent" borrows independence from N-version programming — which a 1986 experiment showed *humans* violate (different authors make the same mistakes on the same hard inputs), and two instances of *one model* violate far worse. The prescription is engineered diversity: a different model family, or a non-AI static check as one "version."
*Skeptic's note:* diversity costs what the single-model economics were saving, and models trained on overlapping corpora may share correlated failures anyway — the independence you buy may be less than you pay for; the human who would truly break the correlation is the one who cannot read code.

**DC-9 · The three-industry Management Layer: control-room detection × aviation decision × recovery-computing action.**
Detection science lives in petrochemical control rooms (muted-until-abnormal HMI + situation-awareness + alarm rationalization), decision support lives in aviation (Quick Reference Handbook + go/no-go + Andon cord), and safe-action-by-non-experts lives in an almost-forgotten early-2000s computing program (Recovery-Oriented Computing). Fusing all three into one command surface for a single non-technical operator of an AI-agent fleet is, per the hunt, unpublished.
*Skeptic's note:* the muted control-room palette has a documented ~12-week adoption trough a lone operator with no shift-team culture may abandon; and aviation runbooks work because pilots are *drilled* on the type — which is exactly why the operator "type rating" (R0) is load-bearing and cannot be skipped.

**DC-10 · Bainbridge's irony taken to its limit: the operator who cannot, even in principle, take over.**
Classic automation theory assumes a deskilled operator *could* intervene with practice; here the operator is non-technical permanently, so the usual safety net (keep the human sharp) is structurally impossible. Reframe him as a *governance/values sensor*, never a manual-control fallback — and replace the missing net with legibility, calibrated-distrust prompts, and diverse automated cross-checks.
*Skeptic's note:* if the human can never take over, you have removed a defensive layer and are betting on the automated layers being independent — which DC-8 says they usually are not. "The human owns WHY not HOW" may be quietly load-bearing in ways that only surface when a WHY-judgment secretly required HOW-comprehension.

---

## 4. Where BlarAI already does, unnamed, what a named discipline formalizes

The system is unusually governance-dense; much of the literature describes practices it already runs by instinct. Naming them lets it borrow the discipline's *tools* rather than reinvent them:

| BlarAI practice | The named discipline it already is | What the name buys |
|---|---|---|
| Go-live ceremony; "irreversible = ceremony" | Meaningful Human Control (tracing); human-in-command | a formal test for whether a ceremony is *meaningful* vs a rubber-stamp |
| Comprehension gate | MHC tracking condition; bridging the "gulf of execution" | a shared-mental-model handshake with known failure modes |
| Decision records in the same change as the decision | design-rationale capture (Parnas's antidote to "ignorant surgery") | the evidence graph for a living assurance case already exists |
| The standing test gate + timeout registry + passthrough-allowlist gate | architectural fitness functions | systematically add fitness functions for *aging/erosion* |
| Egress welded by 3+ independent locks | defense-in-depth / Swiss-cheese; anti-lethal-trifecta | latent-condition vocabulary for auditing where holes could align |
| "Built-but-wired-into-nothing," "test the seams" | latent conditions (Reason); reachability testing | elevates a recurring bug class to a named, catalogued risk |
| Journal: failures stay in, name the rejected path | blameless postmortem / just culture | import postmortem templates, severity tiers, action tracking |
| Lessons: third recurrence ships a structural control | the feedback-system law (Lehman VIII) operationalized | a principled "three strikes → automate the guard" rule |
| Dormant-merge behind a flag | progressive delivery + recovery-oriented reversibility | the deep theory (DC-1) behind your most-used safety pattern |
| ">30-line outputs to a file + pointer"; "attention is managed" | Attention Investment + information foraging | optimize the pointer as engineered "information scent" |

The lesson of this table: BlarAI arrived at many best practices by trial-and-error and honest journaling. The value of the external literature is not to replace that instinct but to give it **names, tools, and the failure modes each discipline already learned** — which is itself the portfolio narrative.

---

*Full raw research (eight specialist reports, ~2,700 lines, with per-idea claim / source / evidence-strength / hardware-fit tables and complete source ledgers) is preserved as evidence outside the committed tree. Ask if you want any specific report surfaced.*
