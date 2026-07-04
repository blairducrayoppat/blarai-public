Critical Design Review — Red Team Assessment
[ISSUE-001]: Secure Bootstrap Paradox — Policy Agent Cannot Self-Attest at Cold Start
Severity: Critical
Affected Use Case(s): [001], [002], [003], [004], [005], [009]
Root Cause Analysis: The architecture mandates that every inter-agent IPC connection requires a valid mTLS certificate issued by the Policy Agent's internal CA, and every tool call requires an Agentic JWT minted by the Policy Agent after dual-gate (CAR + LLM) adjudication. However, the Policy Agent itself must boot inside a Hyper-V VM, load its NPU model weights via mmap, initialize its deterministic rule engine, and establish its Pluton-backed CA — all before any other VM can authenticate. During this bootstrap window:
The Policy Agent's own SGX attestation requires verifying its code hash and rule-set hash against a known-good measurement. Who verifies the verifier? The attestation root is Pluton/SGX silicon, but the chain from silicon to "Policy Agent VM is running unmodified code" requires a measured launch sequence that is not specified. If the host OS or Hyper-V hypervisor is compromised before the Policy Agent completes attestation, a tampered Policy Agent binary could be loaded, and all downstream JWTs would be valid but issued by a compromised gate.
During the bootstrap window (estimated 5–15 seconds for NPU model load + rule engine init + CA cert generation), no other agent can start because there is no CA to issue mTLS certificates and no JWT minter. This creates a hard serial dependency: the entire multi-agent system is blocked until a single microservice completes initialization. If the Policy Agent crashes during boot, the system is permanently inoperable until manual intervention — there is no fallback or recovery path defined.
The Policy Agent must issue its own mTLS certificate from its own CA. This is a self-signed trust root with no external anchor. If an attacker can substitute the CA key during the bootstrap window (before SGX attestation completes), they control the entire identity infrastructure.
Recommended Mitigation: Define an explicit Measured Boot Sequence as a numbered, deterministic phase-gate:
Phase 0 (Silicon Root): Pluton measures the UEFI → Hyper-V hypervisor → Policy Agent VM image hash chain before any VM launches. The measurement is sealed to Pluton's hardware key. This is the only trust anchor.
Phase 1 (Policy Agent Only): Only the Policy Agent VM is permitted to launch. It completes SGX local attestation, derives its CA key from Pluton-sealed storage (key material never exists in host RAM), and generates ephemeral per-boot CA certificates.
Phase 2 (Controlled Agent Launch): The Policy Agent issues mTLS certificates to each agent VM in a deterministic, sequenced order. Each agent VM presents its own measured image hash; the Policy Agent validates against a known-good manifest before issuing credentials.
Phase 3 (Operational): Only after all Priority 1/2 agents hold valid mTLS certificates does the system accept user input.
Crash Recovery: If the Policy Agent fails during any phase, the system remains in a hard-locked state (no agents operational). This is the correct Fail-Closed behavior — but it must be explicitly documented as an accepted availability tradeoff, and a user-initiated manual recovery procedure (re-trigger measured boot from Pluton root) must be specified.
[ISSUE-002]: NPU Multiplexing — Undocumented Concurrency Ceiling on Lunar Lake NPU
Severity: Critical

Affected Use Case(s): [001], [002], [004]

Root Cause Analysis: The architecture simultaneously assigns the following persistent workloads to the Intel NPU (48 TOPS):

[001] Policy Agent: 1.7B INT4 model — continuous inference on every IPC message.
[002] Substrate: 384-dim sentence transformer INT8 — inference on every retrieval query (bi-encoder stage).
[004] Semantic Router: BAAI/bge-small-en-v1.5 (33M params, ONNX FP16 on CPU / OpenVINO INT8 on NPU) — inference on every user query.
[004] Assistant Orchestrator: 1.7B INT4 model — continuous conversational inference.
[007] Health Analytics (Future): Lightweight time-series models INT8 — 24/7 background.
The Intel NPU on Lunar Lake is a single inference accelerator with a unified command queue. Current Intel OpenVINO NPU plugin documentation does not guarantee true concurrent multi-model execution on the NPU — it implements time-sliced scheduling with context-switch overhead. The architecture treats the NPU as if it were a multi-core GPU capable of running 4–6 models simultaneously with independent latency guarantees.

The physics failure: When the user sends a chat query, the following must execute near-simultaneously on the NPU: (1) Semantic Router classifies intent (~50ms assumed), (2) Policy Agent adjudicates the resulting tool call, (3) Substrate bi-encoder embeds the retrieval query, (4) Assistant Orchestrator generates the response. If these are time-sliced on a single NPU queue, the actual latency is additive, not parallel: 50ms + Policy Agent inference + embedding + generation. The 1-second first-token latency target for [004] becomes physically unachievable under concurrent load. If [007] and [008] are also active (future phase), the NPU becomes the single bottleneck for the entire system.

Additionally, the KV-cache for the Policy Agent (350–550MB) and Assistant Orchestrator (300–500MB) must remain resident in NPU-accessible memory to maintain "warm" state. If the NPU has a limited context-slot count (Intel has not publicly documented this for Lunar Lake), swapping between model contexts could invalidate KV-caches, converting every context switch into a cold-start.

Recommended Mitigation:

Empirical NPU concurrency test must be a Phase 2 Day-1 validation gate: load the Policy Agent model and Assistant Orchestrator model simultaneously on the NPU via OpenVINO, measure actual concurrent throughput, and determine whether the NPU supports parallel inference or only time-sliced scheduling. This is a hardware-dependent unknown that cannot be resolved architecturally.
Define NPU scheduling priority hierarchy: Policy Agent inference is Priority 0 (preemptive — never queued behind other workloads). All other NPU consumers yield to it. This ensures the security gate is never starved.
Fallback compute allocation: If empirical testing proves the NPU cannot sustain concurrent multi-model inference within latency budgets, the architecture must define which workloads migrate to CPU (candidate: Semantic Router and Substrate bi-encoder are small enough for CPU inference with acceptable latency degradation). The 1-second latency target for [004] must be re-evaluated under the measured NPU scheduling model.
KV-cache residency policy: Explicitly define whether the NPU supports persistent KV-cache across context switches. If it does not, the "warm state" assumption collapses, and the architecture must budget for KV-cache reconstruction latency on every model switch.
[ISSUE-003]: Shared mmap Weight File — Single Corruption Point Across Security Boundary
Severity: High

Affected Use Case(s): [001], [004]

Root Cause Analysis: The architecture specifies that the Policy Agent [001] and Assistant Orchestrator [004] share the same 1.7B quantized weight file via zero-copy mmap to conserve RAM. This means both the security enforcement agent and the user-facing conversational agent execute inference against identical physical memory pages.

This creates two failure modes:

Integrity coupling: If the shared weight file is corrupted (bit-flip, disk error, malicious modification before mmap), both the security gate AND the conversational agent fail simultaneously with the same corruption. The Policy Agent cannot detect its own corruption because it has no independent reference — its classification logic is derived from the same corrupted weights. This violates the principle that the security gate must be independently verifiable and must not share failure modes with the agents it monitors.
Copy-on-Write attack surface: While mmap is read-only in the standard case, if any process triggers a copy-on-write fault (e.g., via an exploit in the inference runtime that attempts to write to the mmaped region), the OS creates a private copy for that process. An attacker who can trigger CoW in the Assistant Orchestrator's address space could then modify the weights used by the Orchestrator without affecting the Policy Agent's view — or vice versa. This is subtle because the system assumes both agents always see identical weights, but CoW semantics break this assumption silently.
Recommended Mitigation:

Boot-time integrity verification: The Measured Boot Sequence (ISSUE-001 mitigation) must include a SHA-256 hash verification of the weight file against a Pluton-sealed known-good measurement before mmap. If the hash fails, the system refuses to boot (Fail-Closed).
Runtime integrity monitoring: Periodically (candidate: every 60 seconds) verify the mmap region's hash against the known-good measurement. If divergence is detected, halt all inference and escalate to user (Fail-Closed).
Explicit CoW prevention: The mmap must be established with MAP_SHARED | PROT_READ (no write permission) at the OS level. Any process that triggers a write fault against the region must be immediately terminated by the hypervisor. This should be documented as a hard architectural constraint, not an assumed inference-runtime behavior.
Architectural acknowledgment: The shared-weight design is a measured RAM optimization with a documented residual risk: the Policy Agent and the Orchestrator share a failure mode. If this coupling is unacceptable after further analysis, the fallback is loading two independent copies (~2GB additional RAM), which fits within the 25.6GB operational ceiling but increases the Priority 1 Core Loop footprint.
[ISSUE-004]: 25.6GB Operational Ceiling Violated Under Concurrent Peak Load
Severity: Critical

Affected Use Case(s): [001], [002], [004], [005]

Root Cause Analysis: The architecture defines a 32GB hard ceiling with ~6.4GB reserved for Windows 11 + Hyper-V hypervisor, yielding 25.6GB operational. The Use Cases enumerate the following concurrent resident costs:

Component	Stated Resident RAM
[001] Policy Agent (incremental)	350–550MB
[002] Substrate (HNSW + embedder + re-ranker + ORAM + spotlighting)	1.9–3.0GB
[004] Semantic Router	66–80MB
[004] Orchestrator (KV-cache, incremental)	1.0–1.2GB
Shared 1.7B mmap weights	~1.0GB
Priority 1+2 Subtotal	~4.3–5.8GB
[005] Code Agent during active synthesis	12–14GB
Total with [005] Active	~16.3–19.8GB
This appears to fit. However, the analysis omits several critical memory consumers:

Hyper-V VM overhead: Each Hyper-V VM has a minimum memory footprint for its guest kernel, virtio drivers, and runtime. A minimal Linux guest consumes ~256–512MB. The architecture implies at minimum 4 concurrently resident VMs during Priority 1+2+3 operation (Policy Agent VM, Substrate VM, Assistant VM, Code Agent VM) plus the Cleaner VM (on-demand). That is 1–2.5GB of guest OS overhead not accounted for.
mTLS state per connection: Each mTLS handshake maintains TLS session state (~50–100KB per connection). With N active vsock connections (conservatively 6–10 during active operation), this is trivial individually but contributes to unaccounted overhead.
Windows 11 memory pressure: The "6.4GB" Windows reservation is a baseline idle figure. During active operation with Hyper-V managing multiple TDX-enabled VMs, the Hyper-V root partition memory consumption can spike to 8–10GB due to extended page tables (EPT), IOMMU remapping structures, and TDX metadata (TDMR structures consume ~1/256th of assigned memory for integrity metadata).
iGPU Shared Memory Override: The 20GB iGPU allocation for [005] comes from the unified 32GB LPDDR5X pool. When the Code Agent is active with ~9GB model + KV-cache in GPU-accessible memory, this memory is simultaneously subtracted from system RAM. The Use Case states 12–14GB resident for [005], but this may not account for the GPU memory controller's reservation granularity (Intel iGPU shared memory is allocated in large contiguous blocks, potentially reserving more than the model actively uses).
Worst-case concurrent scenario (user is chatting while Code Agent is active):

Windows + Hyper-V root: 8–10GB (realistic under TDX load)
VM overhead (4 VMs): 1–2GB
Priority 1+2 agents: 4.3–5.8GB
[005] Code Agent: 12–14GB
Total: 25.3–31.8GB
The upper bound exceeds the 32GB hard ceiling. The system will trigger Windows memory pressure responses (paging to SSD, process termination by the OOM killer), causing cascading agent failures including potential Policy Agent termination — a catastrophic Fail-Open condition.

Recommended Mitigation:

Construct a precise memory map as a Phase 2 deliverable before any agent implementation begins. Every consumer must be measured empirically, not estimated. The map must include: Windows base, Hyper-V root partition (with TDX metadata overhead), each VM guest OS, each agent's true measured resident set size, iGPU reservation granularity, and KV-cache actual sizes.
Define exclusive execution tiers: The Code Agent [005] and the full Priority 1+2 stack cannot safely co-exist at peak utilization within 32GB. The architecture must enforce a memory-aware scheduler at the Hyper-V level: when [005] is activated, the Substrate's cross-encoder re-ranker and ORAM state machine are paged down (accepting degraded retrieval latency), and the Assistant Orchestrator's KV-cache is flushed (accepting cold-start latency on the next user query). When [005] completes, Priority 1+2 agents are restored. This must be specified as an explicit architectural tradeoff.
Hard memory reservation per VM: Each Hyper-V VM must have a hard maximum memory limit (not dynamic memory) to prevent any single agent from consuming more than its allocated share. The Policy Agent VM gets a guaranteed minimum reservation that Windows cannot reclaim (highest priority).
Lenovo Y700 offload trigger: The Substrate offload strategy (noted in [002]) must be formalized with a specific RAM pressure threshold (e.g., if system committed memory exceeds 28GB, the Substrate automatically migrates to the secondary node). This converts it from a "future scaling path" to a defined degradation mode.
[ISSUE-005]: Context Spotlighting Layer 3 Relies on LLM Compliance — Not Enforceable
Severity: High

Affected Use Case(s): [002], [004], [005]

Root Cause Analysis: The three-layer defense-in-depth against Indirect Prompt Injection is:

Layer 1: Cleaner probabilistic sanitization [003].
Layer 2: Substrate cryptographic spotlighting delimiters [002].
Layer 3: Consuming agent's system prompt "hardcoded directive" that treats spotlighted content as inert [004], [005].
Layer 3 is architecturally unenforceable. The "hardcoded Context Spotlighting enforcement directive" in the Orchestrator's system prompt is a natural-language instruction to a probabilistic model. The model's compliance with this instruction is a function of its training, RLHF alignment, and the specific adversarial payload — it is not a deterministic constraint. Current research demonstrates that system-prompt override attacks are a primary vector for prompt injection, and that no system prompt instruction is guaranteed to be followed by an LLM under adversarial conditions.

The Use Case states: "even if an injection attempts to close or spoof the delimiter structure, the Orchestrator's instruction hierarchy treats any retrieval-sourced content block as inert regardless of its internal structure." This claim is not physically enforceable. The LLM processes all tokens in its context window through the same attention mechanism; it has no hardware-enforced separation between "system prompt tokens" and "retrieved content tokens." A sufficiently sophisticated injection that successfully spoofs or escapes the delimiter structure can influence the model's next-token prediction, including tool-call token generation, regardless of what the system prompt instructs.

The architecture implicitly acknowledges this by requiring three layers, but claims Layer 3 provides independent reduction in attack probability. The actual probability is unknown and unmeasurable — it depends on the specific model, injection, and context window state.

Recommended Mitigation:

Do not claim Layer 3 is independently enforceable. Reclassify it as a "probabilistic alignment bias" rather than a "security control." This is a documentation accuracy issue with design implications.
Add a deterministic Layer 3 alternative: After the Orchestrator generates a response, but before it is executed or returned to the user, a deterministic post-generation validator (running CPU-side, outside the LLM) inspects the output for:
Tool-call tokens that reference destinations not present in the original user query's expected skill set.
Tool-call payloads containing content fragments that match bi-encoder similarity (above a threshold) to the retrieved spotlighted content — indicating the model "leaked" retrieved content into a tool call.
Any output that references or repeats the spotlighting delimiter structure, indicating the model is processing delimiters as content rather than boundaries.
This post-generation validator is architecturally equivalent to the deterministic layer in the Policy Agent's hybrid gate (ISSUE: consistency across the architecture). It transforms Layer 3 from "ask the LLM to behave" to "verify the LLM behaved" — shifting from trust to verification.
[ISSUE-006]: Agentic JWT Replay and Lifetime Management Undefined
Severity: High

Affected Use Case(s): [001], [002], [004], [005], [009]

Root Cause Analysis: The architecture mandates that every approved action is accompanied by an Agentic JWT minted by the Policy Agent via Pluton. Destination microservices reject requests lacking a valid JWT. However, the JWT lifecycle is unspecified:

Token lifetime: If JWTs have no expiration (or a long TTL), a compromised agent that captures a valid JWT can replay it indefinitely against the destination microservice. The destination validates the signature (which is valid) and the CAR schema (which matches the original approved action), and executes it. This permits arbitrary replay of any previously approved action.
Token scope: A JWT minted for "query Substrate for document X" — is it valid for querying document Y? If the JWT authorizes a class of action (e.g., "Substrate read") rather than a specific instance (e.g., "read embedding ID 47291"), then a compromised agent can use a single captured JWT to perform unlimited operations within that class.
Token revocation: If the Policy Agent detects anomalous behavior from an agent mid-session and revokes its mTLS certificate, do previously issued JWTs remain valid at the destination? If destinations only check the JWT signature (using the CA's public key, which hasn't changed), revoked agents can continue operating with cached JWTs.
Recommended Mitigation:

Single-use, nonce-bound JWTs: Each JWT must contain a unique nonce and a cryptographic binding to the specific CAR instance (hash of the full CAR payload). The destination microservice must maintain a nonce-seen set and reject any JWT with a previously observed nonce. This makes replay impossible.
Short TTL: JWTs must expire within a tight window (candidate: 5–30 seconds). The destination rejects expired JWTs. Combined with the nonce, this limits the replay window to seconds even if the nonce-seen set is compromised.
Instance-scoped claims: The JWT claims must encode the specific action instance (e.g., target CID, operation type, payload hash), not just the action class. The destination validates that the JWT claims match the actual request parameters exactly.
Revocation signal propagation: When the Policy Agent revokes an agent's mTLS certificate, it must simultaneously broadcast a revocation event to all destination microservices via a signed revocation message. Destinations must check both JWT validity and certificate revocation status before processing.
[ISSUE-007]: ORAM and Isochronous Execution — Unquantified Performance and Feasibility on Lunar Lake
Severity: High

Affected Use Case(s): [002]

Root Cause Analysis: The architecture prescribes ORAM for the Substrate [002] and isochronous (constant-time) execution for future sensitive temporal databases to close timing side-channel gap (Phase 3, Gap 5). These are cited as "candidate mitigations" without quantifying their actual cost on the target hardware:

ORAM overhead: Oblivious RAM protocols (Path ORAM, Ring ORAM) incur O(log N) bandwidth blowup per access, where N is the number of stored elements. For a Substrate with 5 million embeddings, each retrieval operation requires ~23 additional dummy accesses (log₂ 5M ≈ 22.3). Each dummy access is a full vector read from the HNSW index. The stated 10–15% latency overhead is drastically underestimated — published ORAM benchmarks on conventional hardware show 10–100x latency overhead for database operations, depending on implementation. For a 2-second latency budget, this could push actual retrieval to 20–200 seconds.
Isochronous execution on variable-latency hardware: Constant-time execution requires that every code path takes exactly the same number of cycles regardless of input. This is achievable for simple cryptographic operations (e.g., constant-time comparison) but is architecturally incompatible with (a) HNSW graph traversal (which is inherently data-dependent — the number of hops depends on the query's position in the embedding space), (b) SQLite or equivalent temporal database queries (which have data-dependent I/O patterns), and (c) YOLO inference (which has data-dependent NMS post-processing). The architecture states these operations will be constant-time but does not acknowledge that the underlying algorithms are fundamentally variable-time.
The fallback ("If strict constant-time is not feasible, randomized noise is injected into processing delays") is acknowledged but not quantified. The amount of noise required to achieve statistical indistinguishability (p > 0.05) depends on the actual timing variance of the operations, which is unknown on Lunar Lake hardware.
Recommended Mitigation:

Replace full ORAM with a pragmatic threat-model-scoped alternative. The ORAM threat model assumes a compromised adjacent VM performing timing analysis on the Substrate's memory access patterns. In the architecture, all VMs are launched by the same user on the same machine — if an adjacent VM is compromised, the attacker already has host-level access (since they compromised a Hyper-V guest, likely via an exploit in an agent's inference runtime). At that point, ORAM is insufficient because the attacker has access to the hypervisor's EPT mappings. The actual threat boundary should be scoped: if the threat is a compromised skill container (Hyper-V worker jail, not a TDX VM), then vsock mTLS + JWT + the Policy Agent's AAB already prevent data access. ORAM may be unnecessary given the existing isolation stack. If retained, re-scope it as a defense-in-depth measure with realistic overhead estimates and a degraded-latency fallback, not a primary control.
Replace "isochronous execution" with "bucketed-delay execution": Rather than attempting true constant-time (which is infeasible for the underlying algorithms), pad all operations to the nearest time bucket (e.g., all Substrate queries take exactly 2.0 seconds, all health DB queries take exactly 1.0 seconds, regardless of actual completion time). This is achievable, quantifiable, and provides timing indistinguishability within the bucket granularity. Document the residual risk: an attacker who can measure sub-bucket timing (unlikely over vsock) could still distinguish operations.
Phase 2 empirical gate: Measure actual ORAM overhead and bucketed-delay feasibility on Lunar Lake before committing to either mitigation. If ORAM overhead exceeds 5x latency, formally downgrade it to "accepted residual risk" with documented compensating controls.

**Resolution (Approved — Option A: Isochronous Retrieval with Fixed-Latency Padding):**

The Lead Architect selected Option A for [002] Substrate: ORAM is rejected as a category mismatch for the defined threat model (IPC-timing adversary, not hypervisor-level memory observer). All Substrate retrieval operations are padded to a fixed worst-case execution deadline (2× empirically measured P99 HNSW latency) via deterministic `sleep_until(deadline)` barrier, eliminating the timing side-channel completely from the perspective of any external IPC observer. Phase 2 benchmarking calibration is a prerequisite for deadline setting.

**Forward Constraint — System-Wide Isochronous Timing Standard:**

The isochronous fixed-latency padding pattern established for [002] Substrate is the architectural standard for timing side-channel mitigation across all use cases that expose query-dependent latency over IPC. When future temporal databases are architecturally defined in a future phase, they MUST inherit this pattern — each with its own empirically calibrated P99 deadline measured against its specific workload profile (SQLite temporal queries for [007]; YOLO inference + NMS post-processing for [008]). The "bucketed-delay" recommendation from the Red Team is subsumed by this standard: a single-bucket isochronous deadline is the degenerate (and strongest) case of bucketed-delay execution. ORAM remains a deferred decision, to be re-evaluated only if the threat model is extended to include hypervisor-level memory access pattern observation (e.g., post-TDX hardening).

[ISSUE-008]: TDX Connect (TDISP) for iGPU — Unverified Hardware Dependency Bearing Critical Security Claims
Severity: High

Affected Use Case(s): [005]

Root Cause Analysis: The architecture designates TDX Connect with TDISP as the mitigation for Phase 3, Gap 3 (iGPU trust-boundary leakage). [005] states: "The architecture mandates Intel TDX Connect (candidate solution) utilizing TDISP to extend the hardware-encrypted trust boundary to the iGPU."

The problem: TDX Connect is a specification, not a product. As of the document's date, TDX Connect availability on the Lunar Lake SoC is listed as "a pending hardware validation item." Intel's published TDX specifications (through 1.5) do not confirm TDISP support for integrated GPUs — the specification targets discrete PCIe devices. The Arc 140V is an integrated GPU sharing the same die and memory controller, which presents a fundamentally different trust boundary topology than a discrete PCIe device with its own memory.

The architecture builds Use Case [005] with critical security claims ("GPU memory cryptographically inaccessible to host OS during inference") on an unverified hardware capability. The fallback posture (if TDX Connect unavailable) relies on "compensating controls" including the Policy Agent's AAB and zero-outbound-network — but these compensating controls protect against exfiltration, not against local host-level memory scraping. If the host OS or hypervisor is compromised, the attacker can read raw iGPU memory without needing any network access or tool call. The AAB is irrelevant in this threat model because the attacker is not using an agent to extract data — they are reading GPU memory directly.

This means the actual fallback security posture for [005] under a compromised-host threat model is: standard TDX CPU isolation only, with GPU memory unprotected. The architecture should not describe this as "accepted residual risk with compensating controls" — it should describe it as "GPU memory is unprotected against a compromised host" with specificity about what that means for each data category.

Recommended Mitigation:

Reclassify TDX Connect as a conditional enhancement, not an architectural mandate. Remove the phrasing "The architecture mandates" and replace with "The architecture requires TDX Connect as a prerequisite for operational approval of [005] under the compromised-host threat model. If TDX Connect is unavailable on Lunar Lake, [005] operates under a reduced threat model that excludes host-level memory scraping, with this exclusion explicitly documented in the security attestation."
Quantify the fallback explicitly for each data category:
[005] Source Code: If host is compromised and GPU memory is readable, source code fragments in the context window are exposed. Compensating control: source code is regenerable and rotatable (lower severity).
Phase 2 hardware validation gate: Before any code is written for [005], empirically verify TDX Connect TDISP support on the physical Lunar Lake unit. This is a binary go/no-go gate.

**Resolution (ISSUE-008 — Option A: Conditional Enhancement with Data-Category Fallbacks + Option A: Fixed DVMT Pre-Allocation):**
- **TDX Connect/TDISP:** Reclassified from architectural mandate to conditional enhancement. Phase 2 binary go/no-go gate determines operational posture:
  - **[005] Source Code (Conditional Enhancement):** If TDX Connect available, [005] operates on iGPU with full trust boundary. If unavailable, [005] operates on iGPU under a reduced threat model excluding host-level memory scraping — source code is regenerable/rotatable (lower severity residual risk). Compensating controls (AAB + zero-outbound-network) remain active.
- **DVMT Pre-Allocation:** Fixed at 512MB BIOS minimum granularity. Effective system memory ceiling adjusted from 32GB to 31.5GB. All memory budget calculations, execution tier validations, and Phase 2 memory map gate outcomes computed against the adjusted 31.5GB ceiling. VALIDATE_DVMT_BUDGET introduced as Phase 2 empirical confirmation gate.
- **Forward Constraint:** All future use cases requiring iGPU inference must declare their data-category severity and inherit the corresponding TDX Connect posture ([005]-pattern for rotatable data). VALIDATE_IGPU_TRUST_BOUNDARY applies to all iGPU consumers.
[ISSUE-009]: Cleaner [003] Signs Output, but Signing Key Provenance Is Unspecified
Severity: High

Affected Use Case(s): [002], [003]

Root Cause Analysis: The success metrics for [003] state: "Substrate rejects non-Cleaner-signed inputs." The Substrate's architectural gate enforces that only documents bearing a valid Cleaner signature are ingested. However, the signing mechanism is not specified:

Who issues the Cleaner's signing key? If it is the Policy Agent's CA, then the Cleaner depends on [001] for signing capability. If the Policy Agent is rebooting or unavailable, the Cleaner cannot sign cleaned documents, and the ingestion pipeline halts.
Where is the signing key stored? If it is in the Cleaner's VM memory, a compromised Cleaner can sign arbitrary (unsanitized) documents and the Substrate will accept them — the signature proves provenance from the Cleaner VM but not that the sanitization pipeline actually executed.
This creates a single-point-of-trust problem: the Substrate trusts any document signed by the Cleaner key, but the signature only attests to source identity, not to processing integrity. A compromised Cleaner could skip sanitization entirely and still produce valid signatures.
Recommended Mitigation:

Processing attestation, not just source attestation: The Cleaner's signature must attest not only that the document originated from the Cleaner VM, but that the specific sanitization pipeline version (code hash) executed against the document. Candidate: the signature covers a tuple of (document hash, sanitization pipeline code hash, timestamp, Cleaner VM attestation report). The Substrate validates all four fields.
Key derivation from Pluton via Policy Agent CA: The Cleaner's signing key is derived from the Policy Agent's CA chain (bound to the Measured Boot Sequence from ISSUE-001). The key is sealed to the Cleaner VM's measured image hash via SGX/TDX sealing — if the Cleaner VM's code is modified, the sealed key becomes inaccessible, and the compromised Cleaner cannot produce valid signatures.
Offline ingestion resilience: If the Policy Agent is temporarily unavailable, the Cleaner queues cleaned documents in a local staging area (signed with its sealed key). The Substrate accepts staged documents only after the Policy Agent validates the Cleaner's attestation report on recovery. This prevents the ingestion pipeline from permanently halting on Policy Agent unavailability.

**Resolution (Approved — Option B: Code-Hash-Bound Signing Key):**

The Lead Architect selected Option B for [002] Substrate / [003] Cleaner. Per-document SGX attestation reports (Option A) are rejected as redundant: the Cleaner VM's binary integrity is already attested during Phase 2 credential issuance (the Policy Agent validates the Cleaner's measured image hash against the KGM before issuing mTLS credentials), making per-document re-attestation a re-proof of an already-established guarantee at 10–50ms additional cost per document. Option C is rejected as architecturally regressive: routing every ingested document through the Policy Agent's hybrid gate (70–230ms per document) converts the Policy Agent into an ingestion bottleneck, consumes NPU Priority 0 inference cycles on content validation rather than tool-call adjudication, and reintroduces probabilistic dependency at the ingestion boundary.

**Option B Selected — Mechanism:**
- **Cleaner Signing Key:** Derived from the Policy Agent's CA chain during Phase 2; sealed to the Cleaner VM's measured image hash via SGX/TDX sealing. If the Cleaner binary is modified, the sealed key becomes inaccessible at the next boot, Phase 2 credential issuance fails, and the ingestion pipeline halts (Fail-Closed). Key material never exists outside the TEE-attested Cleaner VM.
- **Signature Tuple (Three-Field):** Each processed document is signed over `(document_content_hash, sanitization_pipeline_code_hash, timestamp)`. The `sanitization_pipeline_code_hash` is computed once at Cleaner VM boot from the sanitization pipeline binary, cached for the session, and carried in every per-document signature for that boot cycle.
- **Substrate Validation:** The Substrate's ingestion handler validates all three fields in strict order — (a) signature verification against the Cleaner's CA-issued public key, (b) document_content_hash match, (c) `sanitization_pipeline_code_hash` match against the KGM-propagated known-good value, (d) timestamp recency check (>60 seconds rejected). Fail-Closed: any check failure rejects the document with no fallback ingestion path.
- **Offline Resilience:** Cleaner queues signed documents locally if Policy Agent is temporarily unavailable. Substrate accepts documents using the boot-time-propagated KGM pipeline hash during Policy Agent absence. Queue flushed on Policy Agent recovery.
- **Signing Latency:** 5–25ms per document (negligible against sanitization pipeline and 100 docs/hour throughput target).
- **Residual Risk (Bounded and Documented):** A runtime in-memory code injection into the Cleaner VM that modifies execution flow post-boot without altering the on-disk binary could bypass sanitization while retaining the valid signing key and cached pipeline code hash. This attack requires breaching SGX/TDX memory isolation, equivalent in difficulty to compromising any TEE-attested agent in the system. Accepted as consistent with the system-wide TEE trust boundary assumption.

Summary of Findings
ID	Severity	Domain	Core Issue
ISSUE-001	Critical	Workflow Deadlock	No measured boot sequence; self-attestation paradox; no crash recovery
ISSUE-002	Critical	Hardware & Compute	NPU treated as parallel multi-model accelerator; actual scheduling unknown
ISSUE-003	High	Security & Isolation	Shared mmap weights couple Policy Agent and Orchestrator failure modes
ISSUE-004	Critical	Hardware & Compute	32GB ceiling violated under concurrent peak; VM overhead omitted
ISSUE-005	High	Security & Isolation	Layer 3 context isolation is LLM compliance, not enforceable
ISSUE-006	High	Security & Isolation	JWT replay, scope, TTL, and revocation undefined
ISSUE-007	High	Hardware & Compute	ORAM and isochronous execution costs drastically underestimated
ISSUE-008	High	Security & Isolation	TDX Connect reclassified: conditional enhancement ([005])
ISSUE-009	High	Security & Isolation	Cleaner code-hash-bound signing: signature covers (document_content_hash, sanitization_pipeline_code_hash, timestamp); key sealed to Cleaner VM measured image hash via SGX/TDX; Substrate validates all three fields + timestamp recency; offline queue resilience; bounded residual risk (in-memory injection post-boot) documented and accepted. RESOLVED — Option B.
3 Critical, 6 High. All 9 issues resolved. Architectural baseline cleared for Phase 2 entry.

