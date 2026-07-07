# ADR-022: Isolate untrusted image handling (decode + VLM)

**Status:** Proposed — deferred to the network-facing-future hardening track.
LA-directed 2026-06-04. **Tracked:** Vikunja #562. **Relates to:** ADR-015
(Local Vision — Amendment 2026-06-04, which runs vision host-side AO-side),
ADR-007 (iGPU trust boundary — software fallback), Phase 2 Gate 4 (iGPU TDX
Connect / TDISP determination), and BUILD_JOURNAL lesson 13 (provenance ≠ trust).

> This ADR is written **Proposed** to preserve the reasoning while the decision
> is deferred. It records the question, the options, and the constraints so the
> eventual implementor (or future-me) does not re-derive them. It does not yet
> commit to an option.

## Context

An attached image is **untrusted, externally-sourced data**. Two stages process
its bytes:

1. **Decode** — `PIL.Image.open(...).convert("RGB")` in `shared/inference/vlm.py`.
   Image decoders (libjpeg/PNG/WebP/HEIF via Pillow) are a historically
   CVE-rich parsing surface (decompression bombs, buffer overflows).
2. **Inference** — `ov_genai.VLMPipeline` (Qwen3-VL) on the GPU.

Today both run **host-side**: the default deployment is `deployment_mode="host"`
(`services/assistant_orchestrator/config/default.toml`), so the Assistant
Orchestrator is a native host process and, per the ADR-015 amendment, it runs the
VLM in-process. The project's standing mandate is **VM isolation for service
execution** (untrusted work belongs in the Hyper-V/Alpine guest), and BlarAI is
on a **network-facing-future** track — the day images arrive from the web, this
host-side parsing of attacker-controlled bytes is the exposed surface.

## The question

Should untrusted image handling (decode and/or VLM) move into an isolation
boundary (the VM, or a host sandbox), and if so, which stage and which boundary?

## Forces / constraints (measured, not assumed)

- **No confidential-GPU boundary on this silicon.** Phase 2 Gate 4
  (`Phase_2_Test_Plan.md:345-357`) found **GPU-PV** (`Add-VMGpuPartitionAdapter`)
  available for the Arc 140V, but **TDX Connect / TDISP UNAVAILABLE**. So running
  the VLM in the VM gives the guest's **CPU-side** isolation (separate kernel,
  syscall sandbox, egress containment) but **not** a hardware-isolated GPU — the
  model weights and decoded pixels still live in GPU memory the host can see.
- **The VM does not help performance, and likely hurts.** The guest has no GPU of
  its own; via GPU-PV it shares the **same physical Arc 140V**. So the co-residency
  memory pressure (VLM \~5 GB + 14B \~8.7 GB vs the 31.3 GB ceiling) is identical
  wherever the process runs — a single-GPU fact — plus GPU-PV adds virtualization
  overhead. (The #561 freeze was an event-loop bug fixed by async, not a
  resource/location bug — do not conflate the two.)
- **Host-mode coupling to undo.** The ADR-015-amendment vision path runs AO-side
  and ships only a lightweight image **path** + `pending_vision` flag over vsock,
  because host mode has direct filesystem access and the path fits the 64 KB
  PROMPT_REQUEST frame. **Guest mode has neither** host FS nor room for MB-sized
  image bytes in a 64 KB vsock frame, so a VM-resident analyzer needs a new image
  **delivery** mechanism (a dedicated bulk vsock channel / shared volume / chunked
  transfer). This is the bulk of the engineering.

## Options

- **A — Full VLM-in-VM (GPU-PV).** Decode + inference both in the guest.
  - *+* Strongest CPU-side containment of both a decoder and a model exploit.
  - *−* Needs GPU-PV into Alpine with OpenVINO working; image-delivery channel;
    virtualization overhead; **no** confidential-GPU gain (TDISP absent).
- **B — Decode-in-a-sandbox (recommended starting point).** Isolate only the
  **decode** step (no GPU needed) in a sandboxed subprocess / minimal guest; hand
  the VLM a **validated, re-encoded** pixel buffer (fixed dimensions/format), and
  keep the VLM host-side.
  - *+* Captures most of the security win (the decoder is the richest exploit
    surface) at a fraction of the cost — no GPU-in-VM, no MB-image vsock problem
    (a normalized RGB buffer is bounded and can be size-capped).
  - *−* Does not contain a hypothetical exploit *inside* the VLM model runtime.
- **C — Status quo (host-side), rely on Fail-Soft + egress kill-switch (ADR-020).**
  - *+* Simplest; the egress guard already denies exfiltration paths.
  - *−* A decoder RCE on the host is uncontained; weakest posture for the
    network-facing future.

## Decision

**Deferred.** No option is committed yet. **Lean: Option B** (decode-in-a-sandbox)
as the first increment when the network-facing track activates, because it is the
best security-per-cost and sidesteps both the TDISP gap and the guest-mode image-
delivery problem. Revisit A if/when a confidential-GPU path (TDISP-capable
silicon) or a guest GPU stack materializes.

## Trigger to revisit

Any of: (1) BlarAI begins accepting images from the network (web nav / fetch);
(2) target hardware gains TDX Connect / TDISP (confidential GPU); (3) a Pillow/
decoder CVE lands that affects the bundled version. The network-facing milestone
is the primary trigger.

## Consequences

- **+** The reasoning (TDISP-absent, decode-is-the-surface, guest-mode coupling)
  is preserved rather than re-derived later under time pressure.
- **−** Until implemented, untrusted image decode runs on the host; the bounding
  controls are Fail-Soft (a decode failure degrades, not crashes) and the ADR-020
  egress kill-switch (no exfiltration), not containment of code execution.
