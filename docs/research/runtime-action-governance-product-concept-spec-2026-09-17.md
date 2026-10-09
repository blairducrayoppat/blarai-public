# Concept specification (pre-feasibility): runtime action governance for AI agents on Windows PCs

> **OUTCOME, recorded 2026-09-20: the product hypothesis below was TESTED by the #1549 feasibility study and the LA answered NO-GO on 2026-09-18. The venture is CANCELLED (ADR-042, #1590)** — not deferred, no check-back. Kept as written, because a hypothesis document is only useful if it still says what was hypothesised.

*Written 2026-09-17 at the Lead Architect's (LA's) direction, as an input to the feasibility study (Vikunja #1549; brief: `docs/research/runtime-action-governance-product-feasibility-brief-2026-09-17.md`). This is a hypothesis document: it states what the product would be so that the study has a concrete target to test for feasibility. Every persona, scenario and requirement here is a claim the study confirms, revises or rejects. It is not a product requirements document; that comes after a go decision, informed by what the study finds about which agents can be governed and which can only be observed. Nothing here commits anyone to build anything.*

## The problem, in plain words

People are starting to run AI agents on their own PCs: coding agents in a terminal, assistants inside applications, features built into Windows itself. These agents read files, send data over the network, change settings, and act on the person's behalf. Today there is no single place on a Windows PC where a person can say what any agent may do, no record they own of what an agent did, and no honest statement of which agents are actually held to any rule. Each vendor offers partial controls for its own agent; the field's own documents admit that an agent which does not pass through a control is not governed by it; the platform vendor's version of this product exists only for enterprises and decides in the cloud. People do not trust AI on their machines, and the tools that would let them trust it do not exist in one place.

## The product hypothesis

A Windows application that:

1. **Inventories** what agents on this PC could reach: files and folders, accounts and credentials, network destinations, devices, installed agents and local models.
2. **Lets the person choose a profile** in plain language (a cautious profile, a developer profile, a small-business profile), adjust it, and keep it as a file they own; one profile governs every agent, because every action is described the same way whatever agent produced it.
3. **Enforces the profile** wherever an agent's actions pass through a seam the product controls, **observes and records** where only observation is possible, and **shows the person which is which**, per agent, with an honest default when nothing is known.
4. **Keeps a signed record** on the machine of every decision, including refusals and approvals, that the person can open, search and verify, and that the product itself verifies whenever it opens it.
5. **Asks the person only for what the profile cannot decide**, in the antivirus style: set up once, run in the background, interrupt for the exceptions, summarise the rest in a digest.
6. **Sends nothing off the machine** unless the person chooses to, and says so plainly.

## Who it is for (hypotheses the study tests)

**The cautious home user.** Uses an assistant or the agent features built into Windows and applications; has heard AI can "do things" and does not know what those things are on their PC. Wants one switch, a plain report, and to be asked only when it matters. Measures success by not being surprised.

**The developer running coding agents.** Runs Claude Code, Codex, Copilot or similar on Windows daily, often with broad permissions because narrow ones are tedious. Wants guardrails that do not slow the work, receipts when something goes wrong, and a way to give an agent a bounded lease rather than a blanket yes. The early-adopter segment, the loudest source of feedback, and the first governed agent (Claude Code exposes a pre-tool hook and is the agent that builds BlarAI).

**The small-business owner or the person who looks after a few PCs.** Compliance-minded; wants the same profile on several machines and an audit trail that would satisfy an auditor or an insurer. Probably a second-year segment; the study says whether it changes the first year's shape.

## Jobs to be done

- "Let me decide, once, what AI on my PC may do, and know it is enforced."
- "Tell me what an agent did, in a form I can prove to someone else."
- "Tell me honestly which agents you cannot control, and what I can do about them."
- "Do not nag me. Ask me for the things that matter and summarise the rest."
- "Keep this between me and my machine."

## Scenarios the product must handle

| # | Scenario | What the person sees | What the product does |
|---|---|---|---|
| S1 | First run | The inventory of what agents could reach; a choice of profile; the coverage screen showing each installed agent as governed, observed only, or out of reach | Scans; installs the seams it can; records the baseline; writes the first receipt |
| S2 | An agent attempts an action outside the profile | Nothing, or a notification, according to the profile's noise setting; the event in the history | Refuses before execution; writes a signed refusal receipt; tells the agent it was refused in a form the agent can act on |
| S3 | An action needs the person | A plain prompt: what kind of action, what it touches, where the data goes, with a presence check for the ones that matter; an option for a bounded lease for repeats | Binds the approval to that exact action; uses it once; refuses if what would run differs; records the approval and who gave it, never the private content |
| S4 | A new agent appears | The coverage screen updates; the agent is shown as ungoverned until classified; the profile's default for unknown agents applies | Detects installation or first run; applies the default (deny or observe, per profile); records the event |
| S5 | The weekly digest | Counts of allowed, refused and approved actions per agent; anything that ran ungoverned; anything that changed in coverage | Assembles from the receipts; nothing leaves the machine |
| S6 | "What did that agent do last Tuesday?" | A searchable history that says what was decided and why, and a verify button that proves the history has not been edited | Walks the signed chain; reports the first break if any |
| S7 | The product is attacked or fails | A loud refusal if its own record is tampered; the governor's own failure shows as a denial, never as a silent allow; disabling the product is itself recorded | Verifies the chain on load; fails closed inside; records its own disable and uninstall |
| S8 | An agent that cannot be governed | An honest statement per agent, with the options the platform offers (sandbox it, restrict its network, or accept the risk) | Observes what it can; never claims coverage it does not have |

## What the product must include

The thirteen requirements in the brief (R1 to R13, `docs/research/runtime-action-governance-product-feasibility-brief-2026-09-17.md`, "What the product must include") are the core, stated at product altitude. Three more belong here:

- **R14. A profile is a file the person owns.** Readable, editable, exportable, importable, and the same file governs every agent on every machine it is copied to.
- **R15. Plain language throughout.** Every screen and prompt readable by the cautious home user; every technical term expanded on first use; the developer sees the technical detail only if they open it.
- **R16. Disabling is honest.** Turning the governor off, or an agent slipping out of its coverage, is shown and recorded, never silent.

The mechanics behind each requirement (hashes, lease fields, record schemas, which Windows interface enforces what) are design-time detail; the brief points to where they live.

## What the product will not do (first year, hypotheses)

- Judge or filter what a model says (content safety, moderation, quality). It governs actions.
- Run a cloud service of any kind: no console, no account, no fleet management, no telemetry by default.
- Govern agents on other operating systems. Windows 11 first; the design must not preclude others.
- Replace antivirus, firewalls or the platform's own sandboxes. It composes with them.
- Promise coverage it cannot measure. The coverage screen is the product's contract.

## Design principles carried over from BlarAI, translated

BlarAI's own security-by-design principles (`CLAUDE.md`) become product commitments: every error inside the governor denies (fail-closed); profiles are allowlists, never blocklists (deny-by-default); every dangerous door has more than one independent lock (defence in depth); the product has no cloud dependency to remove, because it was never built with one (structural absence); one adjudication path per action, no side doors; receipts carry labels and hashes, never the private content (least data); a forged request dies at the boundary (validate before trust); keys and presence checks are rooted in the hardware the PC already has; a control that degrades silently is worse than none (fail-loud); every control ships with a test that proves it blocks and a test that proves it can be turned off, so that "secure" and "unreachable" are never confused; and any change to the product's own posture (a new seam, a new default) is an explicit act by the person, recorded, never automatic.

## How success is measured (the LA's outcomes, made measurable)

- **Adoption:** installs, weekly active machines, governed agents per machine, profiles shared. The LA's stated bar is hundreds of thousands of people; the study says what channel could reach it.
- **Trust:** the share of agent actions on a governed machine that are governed rather than merely observed; zero silent failures in the product's own record; the coverage screen's honesty audited against the receipts.
- **Revenue,** if the commercial path is taken: the study proposes the model and the price; the measure is whatever that model defines.
- **Adoption by Microsoft** counts as success in the LA's terms: the specification adopted, the product bundled, or the approach copied with attribution. The study says which of these are plausible and what each would require.

## The open questions the study must answer

Each maps to a question in the brief: which Windows seams exist and what each governs (Q1); where a governor could live so that agents cannot go around it, and what deep integration costs (Q2); whether one action vocabulary can be universal in practice and what the profiles look like (Q3); whether the antivirus interaction model transfers to actions (Q3a); how the coverage screen is designed (Q4); whether anyone would pay, and how much (Q5); how an open specification and reference implementation would be structured and governed (Q6); what of BlarAI's trust spine is extractable and where the boundary lies (Q7); and whether to go at all, and in what shape (Q8).

## Relationship to BlarAI

The product would be a separate artefact in a separate repository with its own rulebook: it runs on other people's machines, governs agents it does not control, and talks to cloud models when the person chooses. BlarAI's air-gap-by-default is not its threat model; BlarAI's design principles are. What is extractable is listed in the brief (the deterministic checker, the canonical action, the signed audit chain with its TPM signer, the per-turn envelope, escalation consent, the presence verifier). What must never cross between them: secrets, keys, and the LA's data.

## Sources

- `docs/research/runtime-action-governance-product-feasibility-brief-2026-09-17.md` (the study's questions and the seam inventory; R1 to R13).
- `docs/research/runtime-action-governance-landscape-2026-09-16.md` (the field on the five questions; the rejected list; BlarAI's row).
- `docs/research/trust-spine-proposed-items-index.md` (the fifteen items, several of which are this product's core features under BlarAI's names).
- `docs/governance/trust-spine-claim-register.md` (what the trust spine claims and its limits).
- Vikunja #1549 (the study's specification), #1540, #1537, #1541 to #1548.
