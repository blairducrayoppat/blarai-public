### 2026-07-10 — The contractor we never checked: the coding fleet's threat model

*Plain summary: authored the #787 Phase-1 dispatch-fleet threat model (docs/security/post_capstone_2026-07/PHASE1_DISPATCH_THREAT_MODEL.md), grounded on disk; the honest finding is that the coding fleet was outside BlarAI's security model by construction, and Decision 1(b) fixes it at the OS layer.*

The security campaign built a genuinely good vault around the assistant — TPM trust root,
DEK-envelope encryption at rest, a fail-closed egress guard, a Policy-Agent choke point. But
that scope froze at the #598 gate, and every capability we shipped since lives outside it. The
biggest is the coding fleet, and Phase 1 of the post-capstone re-maturation is the threat model
nobody had written for it.

The finding I most wanted to be wrong about held up under grep. opencode is spawned with
`Start-Process` and no `-Credential` (`fleet-lib.ps1:394`), so the coder — and every child it
spawns, `npm`/`uv`/`node`/`git` — runs under the operator's own token, with the operator's file
ACLs and the operator's unrestricted network. It can read `~/.ssh`, the BlarAI keystores, the
backup-staging folder; it can open a socket to anywhere. And BlarAI's egress guard does not cover
it at all: a grep of the entire fleet for the adjudicator, the guarded-fetch door, the allowlist
returns zero files. The fleet is outside the security model by construction — the swap driver
outlives BlarAI itself. Overnight it is worse: the battery self-elevates, and the whole dispatch
tree inherits admin. This is the s1ngularity shape exactly, and it needs no clever prompt
injection — a poisoned `npm install` is enough.

The trade-off this documents, path-not-taken visible: every existing control (opencode's read-deny,
bash-ask, the tree-kill, the FALSE-DONE cross-check) sits at or above the layer that governs what
the *model* asks opencode to do. None of them can touch a child process that bypasses opencode's
tool surface via the OS. That is why Decision 1(b) — a distinct limited account + a per-SID
outbound firewall block — is the right floor: it acts at the OS, below the tool layer, un-bypassable
by children. The sharp design constraint the model surfaced for the ACP-01 rebuild is the
*elevation collision*: the coder leg must be de-elevated to the restricted account even on nights
the orchestrator runs elevated. And the load-bearing honesty — Windows per-account network
isolation is verify-not-assume; the E8 incident (a wrongly-scoped firewall rule that broke the
operator's own machine) is the precedent that makes a live per-SID egress proof mandatory, not
optional, before the floor is trusted. The (c) VM fallback for cross-platform jobs is now confirmed
memory-feasible (30B + a 6 GB guest = 27.5 GB, measured same day).

**Next:** LA reviews the threat model; Phase 2 extends the capstone coverage matrix to the four
post-capstone surfaces; Phase 3 builds the first adversarial suites (the prompt-injection→dispatch
chain first); the (b) floor + its de-elevated coder leg get built into ACP-01, with the per-SID
egress proof as the gate.

**Proposed lesson:** *A control that governs a delegated agent's tool surface does not govern the
processes that agent spawns — assess containment at the layer the OS enforces (the account/SID),
because a child process routes around every policy that lives above it.* (Adjacent to the
data-map / least-privilege classes; the dispatch fleet is the first instance where "the model's
tools are locked down" was mistaken for "the code it runs is contained.")
