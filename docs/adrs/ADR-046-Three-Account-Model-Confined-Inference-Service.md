# ADR-046 — A Three-Account Model: Operator, an Inference-Only Account, and the Coder Account (PROPOSED, spike first)

**Status:** PROPOSED. **No decision has been taken and nothing is built.** *(Status line amended 2026-10-09; the original text read: "The feasibility spike has not run; its make-or-break unknown (whether a non-interactive account can use the Arc 140V iGPU through OpenVINO GenAI or OVMS) is not established.")* The feasibility spike ran on 2026-10-05 (#1689 comments 3896 and 3897; evidence claims C3a, C3b, C6a, C6g in `docs/research/account-level-containment-evidence-2026-10-05.md`): a restricted non-interactive batch account in session 0 loaded Qwen3.5-4B INT8 on the Arc 140V GPU through OpenVINO GenAI and served a completion over loopback under a raw WFP block, on one machine. Not shown: speed parity under the cold gate, the 14B plus draft production pipeline, the loopback-permit direction with the confined account as client, a real model server, streaming. Adoption is undecided. Any adoption would be built DORMANT behind a flag (a topology change) and shown to the LA at a go-live ceremony.
**Date:** 2026-10-05
**Deciders:** The idea is the LA's (2026-10-05, #1689 description). The design note answering his question ("the coder already has an account; do we need another one?") is the session's (#1689 comment 3882). The LA decides adoption and the go-live; the session owns the spike and its technical design.
**Related:** #1689 (this proposal; open) · #1682 (persistent per-account WFP block; blocks the network leg) · #775 / ADR-045 (the coder account and the egress block) · #1671 (the WFP result) · ADR-011 (all LLM inference on the host GPU) · ADR-012 (one resident Qwen3-14B shared by the Policy Agent and the Assistant Orchestrator; speculative decoding) · ADR-041 (a Hyper-V guest cannot reach the host GPU) · ADR-043 (names #1689 as the long-term answer for the coder, not for interactive sessions) · `docs/security/post_capstone_2026-07/PHASE1_DISPATCH_THREAT_MODEL.md` §5

## Context

Today the model runtime runs in the operator's own process and account (the shared in-process pipeline, ADR-012) with the operator's file rights. A runtime bug, a poisoned weights or tokenizer file, or a driver exploit would execute with those rights. The coder fleet's design has the same shape for one workload (OVMS on 127.0.0.1:8000 reached by the coder account over loopback), but with containment off the production coder traffic comes from the operator's account; the separate-account loopback was exercised once, on 2026-07-10 (#775 comment 1654), and the #1671 runs reached a stub listener, not OVMS.

The proposal: a headless model server under a restricted account (no agent, no tools), serving another account over one local channel, text in and text out.

## Proposal

**End state, three accounts** (#1689 comment 3882):

| Account | Does | Rights |
|---|---|---|
| operator | the app, the Assistant Orchestrator, the launcher | the operator's own |
| `blarai-model` | inference only | READ on the model directories only; write only its own cache; no network at all (a raw WFP block keyed to the account, the mechanism #1671 observed enforcing under Bitdefender: single TCP connects to 1.1.1.1:443 over about 3 to 5 s per run, IPv4 port 443 only, 3 runs; see ADR-045, productionised in #1682); no access to the operator's secrets or sessions; GPU access; one local channel (a named pipe whose ACL names the allowed client SIDs, or loopback restricted to the client account) |
| `blarai-coder` | model-written code execution | write its worktree only; egress blocked except loopback to the model port |

**A separate account, not `blarai-coder`.** The duties differ and the risks are opposite: the coder runs model-written code, the model server runs the model runtime. A shared account would let a compromise of either reach the other (the coder reading or tampering with the model process or cache; a runtime bug reaching coder worktrees). Network rules differ (coder: blocked except loopback to the model port; model: blocked entirely, listener only) and file rights differ. The cost is one account, one vaulted password and one start-up item.

**What it does not give.** "Safe output." The model emits text and what is dangerous is what the orchestrator does with it, which is the adjudication door (ADR-044). It contains the runtime, not the answer. Principles served: 3 (defence in depth), 9 (isolation scaled to the input), 10 (integrity).

## Unknowns and costs (each to be settled by the spike or by design)

1. **GPU in a non-interactive account** (session-0 or batch logon, driver access): the make-or-break unknown. Stop if the GPU is unavailable to the account.
2. **IPC latency and streaming overhead** against the in-process path: token streaming, the speculative-decoding draft model and the prefix cache must still work, with a single resident copy shared by the Policy Agent and the Assistant Orchestrator through one server (ADR-012).
3. **Memory:** still one resident copy. The NPU embedding and Whisper and SDXL runtimes are separate models; whether they are in scope is a scope decision not yet taken.
4. **The signed-manifest check at load** must still run inside the confined account.
5. **Operations:** the logon-as-batch right, a vaulted password, start-up ordering in the launcher, and fail-closed behaviour when the server or the filters are absent (the app refuses to answer rather than falling back to in-process).

## Spike (dev-side, no runtime change)

*Note added 2026-10-09: this spike was run on 2026-10-05 with a throwaway account (since removed) and showed feasibility on one machine; results and limits are in #1689 comments 3896 and 3897 and `docs/research/account-level-containment-evidence-2026-10-05.md`. The plan below is the original text and is kept as written.*

In a scratch directory, run OVMS or a minimal GenAI server as a THROWAWAY account (deleted afterwards) with the 4B model: (a) does the GPU work; (b) tokens per second and first-token delay against in-process; (c) the WFP block holds while serving over loopback; (d) a read of the operator's files is denied. Creating the real `blarai-model` account is a later LA-run provisioning step (account and ACL changes are blocked for the harness). Blocked-by: #1682 for the network leg; the spike itself can start after #775.

## Alternatives considered

- **Share `blarai-coder`.** Rejected in the design note, reasons above.
- **Status quo (in-process, operator account).** Not rejected: it is the current state and the baseline the spike measures against.
- **Run the model in a Hyper-V guest.** Foreclosed by ADR-011 and ADR-041: a guest cannot reach the host iGPU.

## Consequences if adopted

A topology change touching the launcher, the Policy Agent and the Assistant Orchestrator transport, the signed-manifest regime, and the start-up and failure story; built dormant behind a flag; LA go-live ceremony. Nothing in this ADR changes the shipped system.

- **Related note (commit-protection hardening; see ADR-043 alternative (k), which lives on the unmerged install-hardening branch).** If Claude Code sessions ran non-elevated or under a separate account, installing the commit-protection hooks in an administrators-only folder outside the user-writable tree would be a cheaper and stronger hardening than any TPM-signed manifest. Today's sessions run elevated, so it would not help yet.

## Re-visit triggers

The spike result (GPU available or not, latency, WFP-while-serving, file denial) and #1682 landing. The ticket names no other trigger.
