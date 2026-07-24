# BlarAI Whole-System Design Review — 2026-07

**Commissioned by:** the Lead Architect (LA), 2026-07-15 · **Ticket:** #905 · **Status:** analysis complete, awaiting LA triage
**Nature:** a top-down expert design review + gap analysis. It changed **no code and no configuration**. Every recommendation returns to you as a decision to make.

---

## How to read this dossier

| File | What it is | Read it if you want… |
|---|---|---|
| **README.md** (this file) | Plain-language executive summary + index | the whole picture in ten minutes |
| **01_problem_and_target_design.md** | Your problem restated as plain requirements, then the design an expert would draw for it today — Product, Factory, Management, Survivability | to see the target we're measuring against |
| **02_gap_register.md** | Every gap found, numbered, severity-rated, each with a keep / refactor / rebuild verdict and the **cost of leaving it** | the gap analysis you asked for — the core deliverable |
| **03_roadmap.md** | A sequenced plan: what to decide and do, in what order, cheapest-highest-safety first | to know what happens next |
| **04_sources_and_synthesis_map.md** | Where every idea came from + the novel "connect-the-dots" combinations, with skeptic's notes | your AI-Governance-Professional portfolio material |
| **05_factory_verification_deep_dive.md** | The central Factory question answered in depth — how software you never read gets verified in a way you can trust | the deepest Factory finding; folded in after a research agent's fuller report arrived post-synthesis |

The full research (eight specialist reports, ~2,700 lines, ~130 external sources) is preserved as evidence outside this folder; it is cited throughout.

---

## The one-paragraph answer

BlarAI is not one system, it is **three** — the **Product** (the AI that runs on your machine), the **Factory** (the machinery of agents that builds it), and the **Management Layer** (the controls *you* operate). They are at very different levels of maturity, and the review found each has one or two load-bearing gaps rather than being broadly unfinished. The most important finding is reassuring: **the 32-gigabyte / smaller-model constraint you worried about is not the thing limiting your security or your quality.** The best expert thinking says safety should never rest on having a bigger or a second AI model watching the first — it should rest on deterministic (ordinary, non-AI) checks and on making mistakes cheap to undo. Your system is, at its core, already built that way. The work ahead is to finish wiring that principle through, close a small number of genuinely serious gaps, and — above all — build the Management Layer, which is the weakest part and the one you already told the system you needed ("I feel like I'm blind to the operational status of my development efforts," ticket #878).

---

## The seven findings that matter most

**1. Your hardware limit is not your security limit (the reframe that changes everything).**
The entire modern field of securing AI agents has converged on one lesson: a language model is an *untrusted* component, and making it bigger or adding a second "supervisor" model does not fix that — even a frontier model, adversarially hardened, still leaks. Security has to live in a deterministic plane *outside* the model. BlarAI already has that plane (its rule-checker, its single decision door, its signed action tokens). So sharing one 14-billion-parameter model between the security gate and the assistant costs you **nothing essential** in security terms. This dissolves the worry behind your whole "is this tailored to my hardware?" question — for security, yes, and the constraint was never the real limiter.

**2. Your flagship security control is built but not actually switched into the live path.**
The system's most-advertised protection — a cryptographic "receipt" that every action must present and every destination must check (the "Action Authorization Boundary") — is fully built, tested, and running as a service, but **nothing in the live chat path actually sends an action to it or checks a receipt.** The real live gate is a simpler deterministic rule-check, which is sound and fail-closed, but it is not the thing the documents describe. This is not an open hole (other locks cover the gap), but it is a genuine divergence between the written vision and reality, and it is invisible unless you go looking. It needs a decision: wire it up, or formally rewrite the vision to match what actually protects you.

**3. The Factory's "grader" is the keystone the whole thing rests on — and its strength is unproven.**
Because you never read code, the Factory judges its own work with an automated test (an "oracle") written by the 14B model. The machinery around this is genuinely excellent and refuses to fake a "done." But two things compound: the test's *strength* is never measured (a tool that would measure it is built but wired to nothing), and the test is written by the *same* model that planned the work — so if that model misunderstands your goal, the plan and the grader share the misunderstanding and confidently certify the wrong thing. Worse, the industry's classic result (Knight & Leveson, 1986) proves that "one checker reviews another" fails when both are built the same way — and two instances of one AI model are far more alike than two human teams. This is structural; it cannot be fixed by being more careful. **The concrete answer is in file 05:** a plain-language "Intent Contract" you confirm in English (never code), from which the tests are derived and then checked by a layered stack of mechanical oracles — the one number to remember is that thin AI-written tests over-report success by roughly 20%, so the Factory must grade on whether its tests can *catch* bugs, not on how much code they run.

**4. The Management Layer is the weakest part, and it is the one you feel every day.**
Today the running app shows you *no* system health — no memory, no model status, no alarms. If something breaks while you are not actively using it, nothing tells you; you find out by trying to act and failing. There are no operator runbooks, and the guides you are told to read first describe a fleet of agents that has been retired. The good news: this gap is well-understood, and the research produced a concrete, buildable design for it, drawn from three industries that solved exactly this — control rooms, aviation, and a forgotten early-2000s computing program.

**5. One gap could lose everything, and it is cheap to fix: the backup recovery key.**
Your encrypted data (conversations, knowledge) can only be recovered with a single physical recovery key that has **no required backup copy**, and the "restore onto a new machine" procedure has **never once been tested end to end**. Lose that key and every encrypted byte is gone forever. This is the single highest-priority action in the whole review, and closing it is mostly a decision (make a second copy; rehearse the restore) rather than a build.

**6. The deepest connected insight: because you can never take manual control, safety must be built-in, not watched-for.**
An aviation-human-factors result taken to its limit: a non-expert operator cannot be the safety net, because they cannot catch what the automation misses. So BlarAI's safety cannot come from *your* vigilance — it must come from things being **safe by construction and reversible.** Remarkably, this *same* principle is the answer in three places the industry studies separately: in security (trust the deterministic plane, not a smarter model), in operations (wrap every control you touch in a guaranteed-safe "envelope"), and in recovery (make every action undoable — the "Recovery-Oriented Computing" idea). Connecting those three is the spine of the target design, and — as far as the research could find — nobody has published that connection for a personal AI-agent system.

**7. A quiet, systemic honesty problem: the system's own documents have already drifted from reality.**
In several places the code says one thing and does another — comments call the internet-egress door "welded shut" while it is live for search; configuration says "every flag off" directly above flags that are on. None of these are security holes, but for a system whose *documented journey is half the product* (your portfolio and certification), a source tree that misdescribes itself is corrosive. The fix is a small structural one: a test that fails when the documentation contradicts the live configuration.

---

## What this means for you

- **Nothing is broken today that needs an emergency response tonight.** The serious items are latent risks and design decisions, not fires.
- **The single most urgent action is the backup recovery key** (finding 5) — and it is mostly a decision you can make in a sentence.
- **Most of what follows is yours to decide**, because the findings are about capability, quality, and security posture — which are your calls, not technical ones. The gap register (file 02) marks each as either a defect (I can just fix it) or a decision (you weigh it). The roadmap (file 03) sequences them.
- **The good news is real and structural:** the core of the system is designed on the right principle, the constraint you worried about is not the limiter, and the weakest layer (management) now has a concrete design ready to build.
