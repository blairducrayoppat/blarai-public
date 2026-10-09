# Would the Agent Governance Toolkit be a better adjudicator than the Policy Agent, or a better foundation to replace it?

*Written 2026-09-16. Fourth document in the set. Unlike the first three, this one rests on source code on both sides: the toolkit was cloned and read at commit `c63c51e8` (15 September 2026), its verdict crate `responsibleai/agent-control-spec` at `a830ed5` (same day), and BlarAI's Policy Agent at `0750d506`. No tests were run and no wheel was built.*

## Outcome first

**No to both questions.** The Agent Governance Toolkit (AGT) would not be a better adjudicator than what BlarAI runs today, and it would be a worse foundation to build on. The reasons are not matters of taste. They are things the toolkit's own source and documentation say about itself.

But the question exposes something the LA should hear plainly first, because it changes what "replace my Policy Agent" would even mean.

**The Policy Agent, as a running service, adjudicates nothing.** It boots, verifies the model weights, attaches to the shared model, binds a socket, and then receives no traffic. ADR-041 recorded this on 2026-07-15 as a decision, not an oversight: the socket path was designed for a per-agent-VM topology this hardware cannot have. The thing that actually adjudicates every tool call and every URL is one pure-Python function, `DeterministicPolicyChecker.check`, about 150 lines of path, string and regex rules, which the Assistant Orchestrator and the gateway import and call directly. It has 49 tests locking its fail-closed paths, no dependencies, no network, no model, and one shared allowlist that both egress layers read.

So the honest comparison is: a 150-line, dependency-free, test-locked function against a 112,000-line beta toolkit whose decision engine is a separate alpha Rust crate on its own release train. Put that way the answer is obvious. What follows is the evidence, and then the part that matters more: what the toolkit does *better*, which is small, specific, and copyable without importing anything.

## What AGT actually is, from its source

The README says the toolkit intercepts every tool call in deterministic code so that denied actions are "structurally impossible". The source tells a more careful story, and the toolkit's own security-model document tells the same careful story.

**Three adjudicators, and the live one is a separate project.** The toolkit contains two readable pure-Python policy engines (an allowlist kernel and a YAML-rule engine), but since the current unreleased change, every framework adapter routes decisions to the Agent Control Specification (ACS) runtime. The toolkit's own Rust crate is a deprecation shim over `agent-control-spec`, a crate published from a different GitHub organisation (`responsibleai`) and pinned at `0.4.0-alpha.3`, its third alpha release. The crate is a serious artefact: about 19,600 lines of engine source, 469 test functions, and a 49-file conformance suite against the Agent Hooks contract. Fail-closed is in its code, not only in its specification: `runtime.rs` wraps every evaluation failure in a `deny` verdict carrying a `runtime_error:*` reason, and an unknown intervention point denies. But it is a separate alpha component on its own release train: the toolkit's 4,400 tests do not test it, and an evaluation of the toolkit is not an evaluation of its adjudicator. Both were read for this document.

**Expressive policy means Rego or Cedar, and the toolkit chose the subprocess.** The crate evaluates Rego in-process by default through the `regorus` library; its `opa` command-line dispatcher is an off-by-default legacy feature that spawns the binary without clearing the environment, which the crate's own notes say lets a manifest that controls the query read a host secret. The toolkit pins the crate with default features off and the `opa` feature on, so the toolkit as shipped selects the subprocess path and disables the in-process one. Cedar is embedded. The stock Rego library's terminal rule is `default verdict := {"decision": "allow"}`.

**An HTTP client is compiled into the engine.** `ureq` is a non-optional dependency of the engine crate, used by its endpoint dispatcher for remote policy and annotator calls. The engine cannot be built without a network client short of forking it. For BlarAI's runtime rulebook that is the same class of problem as the toolkit's `httpx` and `aiohttp`, one layer down.

**The verdict set is allow, deny, transform.** Escalation is a deny carrying an approval block that a host callback may lift. Warn is an allow with a note. This is clean and worth noting for later.

**The core wheel has hard network dependencies.** The core package's dependency list includes `httpx` and `aiohttp` as required, not optional. BlarAI's import scan permits an HTTP client in exactly one file. Installing this package into the runtime tree would require exempting a package tree, which is the opposite of the structural-absence principle.

**The engine cannot see what the host does not show it.** The security model's out-of-scope list says ACS "does not protect against a host application that ignores `deny`", "does not sandbox tools, models, OPA, annotators, SDK code, native libraries, or host processes", and "cannot observe or block a path that the host does not mediate". This is exactly the posture of BlarAI's in-process import today. Adopting AGT would not add a trust boundary; it would move the same cooperative check behind a much larger surface.

**The named features are thinner than the names.** "Four privilege rings" are integers compared against a table of booleans, gated on a resource type inferred from the action's name string; the toolkit's own sandbox module says "a determined attacker can still escape" and real isolation is a separate optional package. "Zero-trust identity" is local Ed25519 keypairs in an in-memory registry that issues its own SPIFFE-format certificates; the SPIRE integration is stubbed. "Merkle audit" is real code, in memory, unsigned; the persistent sink signs with HMAC under a key the writer holds. BlarAI already has a TPM-signed, hash-chained, append-only audit log. AGT's audit is weaker than what BlarAI has built and not wired.

**Release churn.** Sixteen releases between 4 March and 25 June 2026, three of them major. Every entry in the breaking-changes file is dated "TBD". The components a policy adjudicator would depend on carry alpha or preview classifiers.

## The comparison as adjudicators

| Dimension | BlarAI today (`DeterministicPolicyChecker`) | AGT (ACS path) |
|---|---|---|
| Can the decision code be read | Yes, 150 lines in the repo | Yes, in a separate alpha crate, about 19,600 lines |
| Deterministic | Yes | Yes; Rego in-process in the crate, via a spawned `opa` as the toolkit configures it |
| Fail-closed on error | Yes, any exception is DENY; 49 tests | Verified in the crate: evaluation failures become `deny` with a reserved reason; host callback errors deny; the control-plane Python engine lets a raising condition escape `syscall()` as an exception |
| Default when nothing matches | Allow after ten deny/escalate rules, inside a fixed tool allowlist | Stock library allows; manifest must be written to deny |
| Action identity | CAR: verb, resource, canonical args JSON, source agent, destination, sensitivity; `canonical_hash()` defined but not called on the live path (session id is a CAR field outside the hash) | Full policy input including tool, args, snapshot and a wall-clock timestamp; hashed as `enforced_identity` |
| Approval binding | Tool name and rule label, no hash (Gap A) | ACS: SHA-256 of the whole input, re-derived before execution, mismatch denies. Coordinator path: JCS digest, consume-once, expiry, in-memory store only |
| Receipt | Log lines at the live doors (Gap B); TPM-signed chain exists elsewhere | Hash chain in RAM; HMAC file sink; unsigned recorder |
| Runtime dependencies | None | `httpx`, `aiohttp`, `pydantic`, `cryptography`, `pynacl`, a Rust native wheel with its own compiled-in HTTP client, and an `opa` binary as the toolkit configures it |
| Lines shipped into the process | ~150 plus the CAR schema | ~112,000 |
| Trust boundary added | None (in-process) | None (in-process, cooperative, says so) |
| Relational rules BlarAI needs (source-agent versus target-owner, cross-agent paths) | Native | Expressible in Rego or Cedar; not in the YAML engine |
| Shared egress allowlist read by two layers | One frozenset, gate-pinned | Would have to be reproduced outside the engine |
| Release stability | Gate-locked; changes only by ticket | 16 releases in 16 weeks; breaking changes undated |

On every row that matters for a security control, the existing function is equal or better. The one row where AGT is better is approval binding, and that is a design BlarAI can copy in an afternoon without importing anything.

## Why "replace the Policy Agent" is the wrong frame

The question presumes the Policy Agent is weak. The evidence says its live part is strong and small, and its weakness is not in the adjudication at all. The gaps found across all four documents are:

- approvals bind a name, not the action (Gap A);
- the live doors write log lines, not signed receipts (Gap B);
- the two egress layers' agreement is one boot-time check (Gap C, #977);
- denials do not close into receipts (PCAA's non-execution proof).

AGT fixes none of these better than a local change would. Its approval binding is the right idea and BlarAI can adopt the idea. Its audit is weaker than BlarAI's. It has no equivalent of Gap C's problem because it has one engine, but BlarAI's fix for Gap C is a boot-time posture check, already specified in the test file's docstring.

What *is* weak in the Policy Agent is the dead machinery around the live function: the idle listener, the JWT minter, the hybrid adjudicator, the GPU classifier that has never scored a live action. ADR-041 slated that for removal under #910. That removal is the "replacement" the Policy Agent actually needs, and it is subtraction, not substitution.

## What to take from AGT

Three things, all as design references, none as dependencies.

1. **Content-bound approval identity.** ACS computes `enforced_identity` as a SHA-256 over the canonical policy input, hands it to the approval resolver, and re-derives it immediately before execution; a mismatch denies with a named reason. This is precisely the fix for Gap A. BlarAI's CAR already has `canonical_hash()`. The design is: put that hash in the escalation context as a descriptor, have the tool loop recompute it from the CAR it is about to dispatch, and refuse on mismatch. One caution: ACS includes a wall-clock timestamp in the hashed input, which makes an approval unreplayable even for the same arguments on a later turn. BlarAI should hash without the timestamp and expire by turn instead, or the envelope's N=3 behaviour breaks.

2. **The approval record shape.** The coordinator's `ApprovalRequest` carries a policy decision id, the action digest, the agent id, the operation, the policy version, an expiry, and a status that moves through pending, allowed, denied, expired, cancelled and consumed, with consume-once semantics. That is a complete specification of PCAA's action gate lease in fourteen fields. BlarAI's version can be simpler, but this is the checklist.

3. **Escalate as a liftable deny.** Treating ESCALATE as "deny unless a resolver returns allow" rather than as a third verdict makes every fail path collapse to deny by construction. BlarAI's checker already returns DENY or ESCALATE with a rule name; the tool loop already treats an unresolved escalation as a break. Naming the semantics this way in the docstring and the audit record costs nothing and closes an ambiguity.

A fourth, smaller one: the reserved-reasons file, a fixed vocabulary of machine-readable denial reasons. BlarAI's rule names already serve this purpose; a short list of the operational reasons (no adjudicator registered, adjudication error, approval identity mismatch, approval timeout) alongside them would make the future signed receipts consistent.

## What would go wrong if AGT were adopted anyway

Stated so the trade is visible, not to relitigate it.

- The import scan gate fails on day one, or is widened to exempt a package tree.
- A Rust native wheel with a compiled-in HTTP client and, as the toolkit configures it, an `opa` binary join the runtime's trusted computing base. Neither is covered by the signed-manifest posture, which today covers model weights.
- The two egress layers' shared allowlist has to be re-plumbed through a manifest the engine reads, which is a second copy by construction.
- Ten rules whose semantics are pinned by 49 tests, including NFKD normalisation and dual raw-plus-normalised path evaluation against specific found attacks, would have to be rewritten as Rego or Cedar and re-verified.
- The runtime would track an alpha crate on someone else's cadence, with breaking changes the project itself has not dated.
- None of the four gaps would close as a result.

## What was not verified

- The crate's tests and conformance suite were not run; counts are from file scans.
- AGT's test suite was not run. Test counts are from file scans.
- Whether AGT's ACS Python wheel builds and runs on Windows with the project's Python 3.12. Not attempted, because adoption is not proposed.

## Sources

- Toolkit clone: `microsoft/agent-governance-toolkit` at `c63c51e8`, files cited: `agent-governance-python/agent-governance-toolkit-core/pyproject.toml` (dependencies), `policy-engine/core/src/lib.rs` and `policy-engine/core/Cargo.toml` (shim over external crate), `policy-engine/sdk/python/agent_control_specification/_types.py` (decision enum, `enforced_identity`), `policy-engine/policy/lib/agt_default.rego` (default allow), `policy-engine/docs/security-model.md` (out of scope), `policy-engine/docs/acs-retarget.md` (OPA environment exposure), `README.md` line 55, `CHANGELOG.md`, `BREAKING_CHANGES.md`, `agent-governance-python/agent-mesh/src/agentmesh/governance/audit.py` and `audit_backends.py`, `agent-governance-python/agent-mesh/src/agentmesh/governance/approval_protocol/models.py`, `agent-governance-python/agent-mesh/src/agentmesh/core/identity/ca.py` and `identity/spiffe.py` (identity), `agent-governance-python/agent-hypervisor/src/hypervisor/rings/enforcer.py` (rings), `agent-governance-python/agent-os/src/agent_os/sandbox.py` (the "determined attacker" line), `agent-governance-python/agent-os/modules/control-plane/src/agent_control_plane/policy_engine.py` and `kernel_space.py` (the escaping exception).
- Verdict crate: `responsibleai/agent-control-spec` at `a830ed5`, files cited: `engine/Cargo.toml` (features and dependencies), `engine/src/runtime.rs` (runtime-error verdicts), `engine/src/policy_output.rs`; `conformance/` counted, not read.
- BlarAI: `services/policy_agent/src/gpu_inference.py` (checker at 349, rules 485 to 613, allowlist at 403), `services/policy_agent/src/entrypoint.py` (handler at 1188, boot ladder 457 to 496), `services/policy_agent/src/ipc.py`, `services/policy_agent/tests/test_gpu_inference.py` (49 checker tests from 541), `docs/adrs/ADR-041-Host-Mode-Action-Authorization-Boundary.md`, and the surfaces cited in the comparison document.
