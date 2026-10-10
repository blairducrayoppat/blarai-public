# BlarAI

**A personal, locally-run, security-first AI system engineered for decades of use on consumer hardware.**

I believe the laptop already in your bag can run useful AI privately, and that an
AI agent acting on any machine should answer to controls you can check.

BlarAI runs an agentic AI assistant entirely on a single laptop — the language
model on the integrated GPU, the knowledge base and audit log encrypted on the
local disk, and **zero external network dependency by default**. It is a
personal research project and my long-term local AI system — not a wrapper
around a cloud API. It's designed to survive hardware generations, with a
security and governance architecture treated as a primary engineering artifact
from the start, not an afterthought.

The design premise is uncompromising: a system that holds decades of a person's
private data must assume every component can fail or be subverted, must fail
*closed* when it does, and must be able to prove — cryptographically and in a
tamper-evident audit trail — what it did and why.

---

## Recent advancements (as of October 2026)

Highlights of what has landed on the main line since the previous public snapshot.
Every item below corresponds to code, tests, measurements or decision records in
this repository — not roadmap intentions.

- **The coding agent is being moved into a restricted Windows account, and the
  record says exactly how far that has got.** BlarAI's coder fleet writes and
  tests code with no person typing; today that code runs as the operator's own
  account. [ADR-045](docs/adrs/ADR-045-Coder-Containment-Account-Level-Fused-Leg-and-WFP-Egress-Block.md)
  records the design: only the coder step runs as a dedicated account, so Windows
  file permissions, not the agent's own settings, decide what it can read and
  write; the quality gate, every `git` commit and the merge stay with the
  operator. The code lives in the companion repository, agentic-setup. The switch
  is **off** (`containment = off`), the permission-narrowing stage is merged but
  not applied to the machine, and no complete dispatch has yet run through the
  coder account. The [design overview](docs/design/CODER_CONTAINMENT_DESIGN_OVERVIEW.md)
  is written to be read cold; its section 1 is a dated status table and its
  section 13 lists what is not yet verified. This is an account boundary, not a
  kernel or virtual-machine boundary.
- **One measurement of the egress gap, with its limits attached.** Blocking the
  coder account's outbound network traffic is an open, accepted gap: the ordinary
  Windows Firewall rule does nothing on this machine because a third-party
  security suite owns the firewall. The
  [evidence record](docs/research/account-level-containment-evidence-2026-10-05.md)
  shows that a raw Windows Filtering Platform block keyed to a dedicated
  low-privilege account stopped its outbound connects on this laptop: the coder
  account in three runs of about five seconds, and a throwaway account of the same
  kind in one run of about two minutes and in six alternated runs on 2026-10-09
  that showed the loopback permit filter is what keeps such an account's path to a
  local model server open while the block stands. It ran in a session that vanishes
  when the script exits, so it is evidence, not a control. Section 6 of the record lists what it
  does not establish: one machine, one security suite, one graphics driver, IPv4
  TCP to one port, no reboot or persistence test, no hold longer than about two
  minutes, and the coder account still holding write access on the operator's
  `projects` folder today.
- **A commit-protection control moved inside git after a command-text guard was
  bypassed more than twenty times across four review rounds**
  ([ADR-043](docs/adrs/ADR-043-Commit-Protection-Layers.md)). A parser of
  command text and the program that executes the command are two parsers, and a
  control built on the first can never be airtight. The control for `main` now
  lives in a git hook that sees every ref update by any route; the text guard
  stays only where nothing better exists, labelled best-effort.
- **A venture reopened on a narrower claim than the one it was cancelled for.**
  [ADR-049](docs/adrs/ADR-049-Governator-Venture-Reopened.md) reopens the
  runtime action-governance venture that ADR-042 had cancelled in September. What
  changed is evidence on one dimension, on one machine; the record states those
  limits in its own context section rather than omitting them, and decides
  nothing about the venture's claim, form or licence. No BlarAI runtime behaviour
  changed.
- **The standing test gate reads 13,317 passed / 0 failed / 3 skipped / 620
  deselected** on the merged main line at `ce925cf2` (2026-10-09, non-elevated
  run; the 3 skips are the documented symlink delta). The last elevated full run
  read 13,302 / 0 / 0 / 620 on `ea7ee8c3` (2026-10-08). The run conditions that
  make either figure mean something are in `docs/TEST_GOVERNANCE.md` section 1.
  The lesson index in `LESSONS.md` runs to number 385.

---

## Target hardware

BlarAI is built and measured against one machine, and every number in this
repository is real measurement on it:

| Component | Specification |
|-----------|---------------|
| CPU | Intel Core Ultra 7 258V (Lunar Lake) |
| GPU | Intel Arc 140V (Xe2) integrated |
| NPU (Neural Processing Unit) | Intel AI Boost (used for encoder offload) |
| Memory | 32 GB LPDDR5X — **31.323 GB effective** ceiling after firmware reservation |
| Trust root | TPM 2.0 (Trusted Platform Module, STMicroelectronics); Windows Cryptography Next Generation (CNG) Platform Crypto Provider |
| Host OS | Windows 11 Pro + Hyper-V |

The 31.323 GB effective ceiling is a hard architectural constraint. Every model,
cache, and co-residency decision below is sized against it and validated by
on-device measurement, not estimation.

---

## Inference stack

All language-model inference runs on the Arc 140V GPU via **OpenVINO GenAI**
(2026.2.1). BlarAI does not use llama.cpp, Ollama, or any cloud runtime — it is
an Intel/OpenVINO-native stack tuned for Lunar Lake.

- **Primary model — Qwen3-14B, INT4 (GPU).** 40 layers, 5120 hidden, 8 key-value (KV) attention heads
  using grouped-query attention (GQA), \~9.1 GB of INT4-symmetric weights. A single shared model instance backs
  both the Policy Agent (classification) and the Assistant Orchestrator
  (conversation) — one weight load, distinct KV-caches — so the security gate and
  the conversational agent never double the RAM cost.
- **Speculative decoding.** A Qwen3-0.6B draft, pruned to 6 layers and quantized
  INT8, drives speculative decoding for **1.48–1.68× sustained** throughput
  (short turns 1.68×, long turns 1.48×; interleaved A/B, 2026-07-10, OpenVINO
  2026.2.1 — `PERFORMANCE_LOG.md`). Two earlier figures are superseded, not wrong:
  a "~2×" traced to a cool-GPU burst against a thermally disadvantaged baseline,
  and a methodology-corrected **~1.4×** from 2026-05 measured on a different,
  unpruned INT4 draft two runtime generations back. The pruned draft
  was chosen over a full 0.6B draft specifically because it *streams* token by
  token — a deliberate trade of some peak throughput for a responsive, live-typing
  feel on every reply.
- **Embeddings — bge-small-en-v1.5, NPU-offloaded.** The shared 384-dim encoder
  (substrate retrieval, knowledge bank, and leakage detection all ride one
  session) runs on the NPU by default. Measured **13.6× faster** than the CPU path
  on 512-token document windows (168.9 ms → 12.4 ms) at 0.999996 cosine parity,
  while freeing both the P-cores and the GPU-contended 14B. Fail-soft: a box
  without a working NPU falls back to CPU automatically.
- **Voice loop.** Whisper speech-to-text (STT, on GPU) + Kokoro text-to-speech (TTS), with speak-to-submit and
  streaming synthesis. Whisper-on-NPU was measured and found *not* viable on the
  current driver — recorded honestly, STT stays on GPU.
- **Vision.** Qwen3-VL-8B provides local image understanding, host-side, load-on-
  demand.
- **Local image generation (UC-010).** Text→image and image+text→image on the
  Arc 140V via OpenVINO `Text2ImagePipeline` / `Image2ImagePipeline`, using an
  Stable Diffusion XL (SDXL) INT8 photoreal finetune (RealVisXL V5.0) plus a base SDXL +
  runtime Low-Rank Adaptation (LoRA) for illustration and cartoon styles. Because SDXL and the 14B
  cannot always co-reside under the 31.323 GB ceiling, generation is choreographed
  against memory: the diffusion pipeline is evicted after every generate, and a
  high-resolution refine will evict the shared 14B and lazily reload it. The
  Phase-0 memory gate measured a **\~26.0 GB co-resident peak (5.3 GB headroom)**;
  base 1024² generation completes in \~10.7 s.

---

## Governance and security architecture

This is the part of BlarAI that matters. The capabilities above are table stakes;
the differentiator is that every one of them operates behind a deterministic,
fail-closed governance boundary.

The rule the whole architecture follows: a control is enforced where the agent
cannot argue with it. Deterministic checks decide before the classifier model is
consulted; where the operating system can hold the line, the design puts the
boundary in the account's own token and the kernel's filters rather than in a text
or path check (that is the coder-containment design above, merged with its switch
off); a second, independent layer stands behind the first; and a tamper-evident
record keeps what crossed.

### The Policy Agent — model-initiated tool calls are adjudicated

BlarAI's Policy Agent is a resident semantic gatekeeper: every model-initiated
tool call and fetch in the assistant is reduced to a canonical action and checked
deterministically (the coding fleet's dispatch gate is by repository name). It
uses a hybrid model:

1. Each action is reduced to a **Canonical Action Representation (CAR)** and
   evaluated by a deterministic checker (allowlist + schema constraints).
2. Only actions the deterministic layer admits proceed; a probabilistic
   classifier backstops semantic intent.

The deterministic-first design is a direct response to a documented weakness: a
sub-8B classifier alone is empirically insufficient against adversarial
out-of-distribution payloads, so schema enforcement — not the model — is the
non-bypassable layer.

### Fail-closed everywhere

Unclassified, ambiguous, or unverifiable inputs are blocked by default and
escalated to the operator. Stores refuse to start rather than open in a degraded
state. A missing or invalid signature blocks boot. This is enforced in code
(`fail_closed = true`), not by convention.

### Hardware-rooted trust and at-rest encryption

- **TPM 2.0 trust root (Architecture Decision Record ADR-018).** SGX (Software Guard Extensions), referenced in the original architecture,
  is absent from Lunar Lake; the trust root was migrated to non-exportable TPM 2.0
  keys via the Windows CNG Platform Crypto Provider. The signing primitive is
  implemented and hardware-verified.
- **At-rest encryption (ADR-025).** Application-layer AES-GCM (Advanced Encryption Standard, Galois/Counter Mode) over the session and
  substrate/knowledge databases, under a TPM-sealed Data Encryption Key with an
  offline recovery-key ceremony. Stores open with `secure_delete=ON` so discarded
  content is zeroed at rest.
- **Signed model manifests.** Model weights are SHA-256-manifested and
  signature-verified at load (fail-closed), covering the nested diffusers-OV
  layout as well as the flat 14B.

### Isolation and egress

- **Hyper-V guest isolation** with `AF_HYPERV` vsock for host↔guest communication
  — **no TCP/IP inside the guest**. Hostile web bytes are parsed inside a guest with no network interface card
  (the launcher asserts zero network interface cards at start, fail-closed); only cleaned text
  crosses the vsock boundary.
- **One governed egress door (ADR-027).** By default BlarAI makes no external
  calls. When network features are enabled, all outbound traffic flows through a
  single sanctioned path (`shared/security/guarded_fetch`, the only module
  permitted to import an HTTP client, enforced by an import scan) against a
  deny-by-default allowlist. The first standing allowlist entry is `kagi.com`, for
  the model-callable `web_search` tool; every other host is denied by rule. A
  tamper-evident, segmented audit log (ADR-029) records every decision, kept
  forever in individually-verifiable sealed segments.

### Provenance-based trust and prompt-injection defense

Trust follows provenance (ADR-023). Content is tagged `TRUSTED_LOCAL`,
`TRUSTED_MEMORY`, `UNTRUSTED_EXTERNAL`, `UNTRUSTED_KNOWLEDGE`, or `UNTRUSTED_WEB`.
Untrusted content is datamarked at ingest, action-locked (it can steer words, not
fire tools), and passed through spotlighting and a cosine-similarity leakage
detector before any response leaves the system. Trusted local files carry zero
daily friction; the injection defenses fire only when genuinely untrusted content
is present. The design keeps consent at the grain a human can actually judge —
egress and privacy decisions go to the operator (a turn-scoped Windows-Hello
envelope gates model-initiated egress), while danger is routed to deterministic
controls rather than a per-item rubber-stamp.

---

## Tool calling, evaluation, and testing

- **Native JSON tool calling.** Tool calls use the Qwen3-native JSON form with
  strict, fail-closed parse-time schema validation. An xgrammar structural-tags
  constraint (which makes a malformed or unknown-tool call structurally impossible
  at the decoder) is built and proven to compose with speculative decoding and
  streaming; it is currently gated off pending an upstream runtime fix, with
  parse-time validation as the guard in the interim — recorded transparently in
  config, not hidden.
- **Model-quality eval harness.** A golden-set eval suite (`evals/`) covers Policy
  Agent classification, tool calling, and governance behavior, with committed
  per-case baselines and regression exit codes that have teeth. First
  model-in-the-loop Policy Agent classification measured 26/30 (86.7%) — and, importantly,
  all four misses were *over-denials* of benign actions, never a dangerous
  false-allow.
- **Standing test gate.** **13317 passed / 0 failed / 3 skipped / 620 deselected**
  on the merged main line at `ce925cf2` (2026-10-09, non-elevated; the 3 skips are
  the documented symlink delta). The last elevated full run read 13302 / 0 / 0 /
  620 on `ea7ee8c3` (2026-10-08). The model-quality eval gate runs beside it.
  Hardware, WinUI, and slow tiers are deselected from the standing gate and run
  separately. Test policy, run conditions and baseline management are governed in
  `docs/TEST_GOVERNANCE.md`.

---

## Surfaces

- **WinUI desktop app** — the primary operator interface: streaming chat, voice
  conversation, inline generated-image rendering and a gallery, and a knowledge
  ingest/approval flow.
- **Knowledge bank** — an operator-curated, approval-gated encrypted store
  (`knowledge.db`, a sibling of the substrate under the same DEK) with hybrid
  retrieval (cosine + BM25, reciprocal-rank fusion) over approved content only.
- **Headless coding-agent dispatch (ADR-034 / ADR-035)** — BlarAI can decompose a
  natural-language goal into tasks with verifiable acceptance criteria and dispatch
  them to a local coding fleet, orchestrating a host-level model swap (the 14B and
  the fleet's larger model cannot co-reside) with never-zero teardown and
  idempotent crash recovery. The coder runs as the operator's own account today;
  the account-level containment design (ADR-045, code in agentic-setup) is merged
  with its switch off, and the coder's outbound network block is an open, accepted
  gap.

---

## Project structure

```
shared/              Shared libraries — security (guarded_fetch, egress guard,
                     tpm_signer), inference, config, inter-process communication, provenance, evals feed
services/
  policy_agent/          USE-CASE-001 — deterministic + probabilistic adjudication
  assistant_orchestrator/ USE-CASE-004 — conversation, tool loop, PGOV governance
  semantic_router/       Intent routing
launcher/            Hyper-V virtual-machine manager, boot sequencing, deployment
evals/               Golden-set model-quality eval suites (regression exit codes)
docs/
  adrs/                  Architecture Decision Records (ADR-005..049)
  design/                Design records (coder-containment overview, coder definition of done)
  research/              Evidence records and their raw-data bundles
  DECISION_REGISTER.md   Single-source-of-truth index of runtime decisions + ADRs
  IMPLEMENTATION_PLAN.md Milestone tracking
  TEST_GOVERNANCE.md     Test policy, marker taxonomy, baseline
  ledger/                Per-entry milestone ledger
tests/               Integration + security posture tests
BUILD_JOURNAL.md     The running narrative of how BlarAI was built
LESSONS.md           Distilled, numbered lessons (the compounding surface)
PERFORMANCE_LOG.md   Reproducible, community-grade inference measurements
```

---

## The Use Cases

BlarAI's full vision spans nine original Use Cases, with a tenth — local image
generation — added later as a deliberate, documented expansion. Two are operational,
one is live, and the rest are defined and staged; the most developed are summarized
below.

| # | Use Case | Status |
|---|----------|--------|
| 001 | Policy-Driven Security & Access Orchestration (Policy Agent) | **Operational** |
| 002 | Personal Knowledge Substrate | Knowledge bank live; layered store merged |
| 003 | Local Data Normalization with Mobile Local Area Network Ingress (Cleaner) | Ingest flow merged; fetch limb governed |
| 004 | Context-Aware Private Assistant with Modular Skills | **Operational** |
| 005 | Interactive Local Software Engineer (headless) | Dispatch integration live |
| 009 | Autonomous System Maintainer | Defined |
| 010 | Local Generative Imaging (text→image, image+text→image) | **Live** |

Canonical definitions live in `Use Cases_FINAL.md`.

---

## Phase history

| Phase | Status | Summary |
|-------|--------|---------|
| 1 — Architectural Definition | Closed | Use Cases locked; canonical architecture defined |
| 2 — Empirical Validation | Closed | All hardware gates passed; core backend complete |
| 3 — UI Design & Scaffolding | Closed | Desktop shell; UI backend |
| 4 — Operational Gap Closure | Closed | User Acceptance Testing sign-off; operational baseline |
| 5 — Post-Operational Development | **Active** | Capability program: eval harness, native tool calls, NPU offload, image generation, web search, dispatch |

---

## On the build journal

`BUILD_JOURNAL.md` and `LESSONS.md` are load-bearing parts of this repository, not
decoration. They are the honest record of how BlarAI was built — and they keep the
failures in. A benchmark that corrected two wrong assumptions in two minutes; a
"2× faster" measurement that turned out to be a hot GPU and was walked back that
week to an honest ~1.4× (the sustained figure on today's pruned draft is
1.48–1.68×); a prompt-injection defense that failed its own test and was parked on a
branch rather than shipped; a security fix that three passing test sweeps missed
and a live screen caught. The judgment behind each call is the point. Sanitized
journals do not compound; this one is meant to.

---

## Status and provenance

BlarAI is a **personal, single-operator system**, built **AI-assisted under human
governance** — every substantive change is reviewed against the real code, the
tests are re-run, and it is verified live on the actual hardware before it is
committed. It is shared publicly as a portfolio artifact: a worked example of
building and governing a local AI system to a mature-not-minimal standard. It is
not a supported product, and the security properties described here are engineering
intent backed by tests and measurement, not a third-party audit.

The state of the coder-containment work is read from two documents, not from this
page: the [design overview](docs/design/CODER_CONTAINMENT_DESIGN_OVERVIEW.md), whose
section 1 is a dated status table and whose section 13 lists what is not verified,
and the [evidence record](docs/research/account-level-containment-evidence-2026-10-05.md),
whose section 6 states what its measurements do not establish. The switch is off,
the measurement is evidence rather than a control, and nothing here claims the coder
is contained.

---

## License

BlarAI is licensed under the **PolyForm Noncommercial License 1.0.0** — free for
individuals and noncommercial use (personal projects, hobby use, education,
research, evaluation). See [LICENSE.md](LICENSE.md).

**Commercial use requires a separate paid license** — including use by or for any
organization in its business, building products or services on top of the
software, or use as part of revenue-generating work. See
[COMMERCIAL-LICENSE.md](COMMERCIAL-LICENSE.md).

To obtain a commercial license, contact **Blair DuCray-Oppat —
mr.blair.do@gmail.com**.

Copyright (c) 2026 Blair DuCray-Oppat. All rights not expressly granted under the
PolyForm Noncommercial License 1.0.0 are reserved.
