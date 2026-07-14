# Post-Capstone Security — Your Options Briefing

**For:** the Lead Architect (you) · **Written:** overnight 2026-07-09→10 · **Ticket:** #787
**Your time to read this:** ~15 minutes. **Decisions it asks of you:** 4, each with my recommendation.

This is the "walk me through the options" you asked for. It's written for you to *decide*, not to
learn security. Every technical claim is either verified against our own code or cited to the research
brief next to this file (`RESEARCH_BRIEF_adversarial_testing_2026-07-09.md`), which flags where the
public sources were shaky so we don't build on sand.

---

## The one-paragraph version

BlarAI has already had a real security campaign — the encryption, the air-gap, the trust root, the
capstone. That work is genuine and it holds. But it was scoped and frozen back in June, and **since
then we built four new things it never covered** — the biggest being the coding fleet that writes and
*runs* code on your laptop. The honest finding, verified on our own disk tonight: **the air-gap
protects the assistant, but it does not protect against what the coding agent's own code does once it
runs.** Nothing has gone wrong. But we've never actually *attacked* our own system to find out where
it bends, and that's the work this ticket is. It doesn't need your Cyber Verification approval (testing
your own machine never did), and I can do almost all of it — I need you for four decisions.

---

## What's actually exposed (plain language)

Think of BlarAI's security like a bank vault. The campaign built a very good vault: the money (your
data) is encrypted, the doors (network) are sealed, and a guard (the Policy Agent) checks every
withdrawal the assistant asks for. That vault is real and it works.

Here's what changed. We hired a **contractor** — the coding fleet — and gave it a workshop inside the
building to build things you ask for. The guard still checks what the *assistant* does. **But the
contractor works with its own tools, and nobody checks what those tools do.** When the contractor runs
`npm install` to fetch a library, that request goes straight out the building's back door — not past
the guard. And the contractor can read any room it has keys to, which right now is **every room you
can enter**, because it runs as *you*.

That's not a hypothetical worry. In August 2025 (the "s1ngularity" incident, in the research brief),
attackers poisoned a popular code library so that when developers installed it, it **used their own AI
coding assistants to hunt for passwords and keys on their machines** and mail them out. ~190
organizations hit. It's the exact shape of what our contractor *could* be tricked into — not because
our fleet is badly built, but because *no* coding agent on a plain Windows machine has a wall around it
today. (Even Anthropic's own Claude Code can't sandbox itself on native Windows — it needs Mac or
Linux.)

**The three things worth testing** (they map to the industry's brand-new checklist for exactly this
kind of system — OWASP's 2026 "Agentic" Top 10):
1. **The coding fleet** (their item "Unexpected Code Execution") — can it be steered into reading your
   secrets or reaching the internet in a way you didn't intend? *This is the big one.*
2. **The preference memory** we're shipping tomorrow (their "Memory Poisoning") — since it goes
   straight into the assistant's instructions every turn, could someone slip a false "preference" in
   that the assistant then obeys? (Good news: the review I ran tonight found we already built this the
   right way — the only path to write a preference is you. Phase 3 stress-tests that.)
3. **The image generator and the test-runner VM** — smaller surfaces, worth a look.

---

## Your four options (what kind of testing, not which — you can pick several)

| Kind | Plain-language | What it'd find here | My call |
|---|---|---|---|
| **A. Adversarial eval suites** | Automated attacks we write once and run forever, like the test gate you already have | The specific weaknesses, turned into permanent alarms | **Do this — it's the backbone.** Every finding becomes a test that can never silently come back |
| **B. A "purple team" check** | Verify the guards actually *sound the alarm* when attacked, not just quietly refuse | Whether the Policy Agent + egress guard *log* an attack (not just block it) | **Do this — cheapest, ~a day, high value** |
| **C. A hands-on pen test** | I actively try to break in, breadth-first, and write up what gives | Real exploitable gaps a checklist misses, especially in the coding fleet | **Do this, but after the containment decision below** |
| **D. A red-team engagement** | A stealthy campaign to achieve one goal while "defenders" try to catch me | — | **Skip it.** It's for organizations with a security team to surprise; you're a team of one. Wrong tool |

So: **A + B + C, not D.** A red team sounds the most impressive and is the wrong instrument for a
single-operator system — the research is unambiguous on this, and I'd be doing you a disservice
dressing it up.

---

## The four decisions I need from you

I've put my recommendation first on each. None are urgent tonight; they gate the *build*, not your
sleep.

### Decision 1 — How much should the coding agent be walled off? *(the important one)*
Right now the coding fleet runs as **you** — it can read anything you can (your SSH keys, the backup
staging folder, the BlarAI keystores) and reach the internet freely. Options, cheapest to strongest:

- **(a) Accept the risk, add tripwires** — leave it as-is but add monitoring + a documented
  accepted-risk record. Cheap, honest, weakest.
- **(b) ⭐ Restricted user + firewall rule** *(my recommendation as the first step)* — run the coder as
  a separate limited Windows account that *can't* read your personal files and *can't* reach the
  internet (a firewall rule scoped to just that account). Breaks the dangerous chain without breaking
  git/node/the toolchain. Days of setup, not weeks.
- **(c) Run the coder inside the VM we already have** — the strongest, and elegant: we already run a
  network-less Hyper-V guest for tests. Move code execution *into* it. The trade-off: the VM can't
  reach the internet, so libraries have to be pre-staged — which, after s1ngularity, is arguably a
  feature. Bigger build.

My honest read: **(b) now as the floor, (c) as the direction** — and here's the timing that matters:
we're about to rebuild the exact part of the code that launches the coder (the "ACP-01" work you
approved). **If you pick a containment direction now, it gets built into the new machinery for free. If
we decide later, we rebuild it.** That's why I moved this decision *ahead* of that work in the queue.

### Decision 2 — Test against a clone, or the live system?
Attacking a system that runs code *will*, eventually, run something destructive. Standard practice is a
full disk image first, and testing the dangerous parts against a **copy**, not your real encrypted data.

- **⭐ My recommendation:** the safe probes (injection attempts, alarm-verification) run against the
  live system — they can't hurt anything. The destructive tier (actually letting the coder execute
  hostile code) runs against a clone with a disk image taken first. Standard, and I set it all up.

### Decision 3 — How deep, and how public?
This is portfolio-load-bearing for your governance certification. Options: keep it internal, or write
it up as a public security case study (the journey is the portfolio).

- **⭐ My recommendation:** build it as a documented campaign either way (rules-of-engagement,
  findings, fixes-as-tests) so it *can* be public later — decide publication when you see the results.
  No cost to keeping the option open.

### Decision 4 — Do you want to be in the loop per-phase, or just at decisions?
- **⭐ My recommendation:** I run the building autonomously and bring you only the genuine
  decisions (Decision 1 is the real one; the rest I can drive). You review the findings, not the work.

---

## What happens next (you don't need to act on this tonight)

The queue already has this sequenced:
1. **Phase 0 (this doc)** — done; you read it when you wake.
2. **Phase 1 — the coding-fleet threat model + Decision 1**, deliberately *before* the ACP-01 rebuild
   so containment is designed in, not bolted on.
3. **Phase 2** — extend the capstone's coverage to the four new surfaces (the honest residual-risk
   register).
4. **Phase 3** — build the first real adversarial eval suites (A above), starting with the coding-fleet
   chain and preference poisoning.
5. **Phase 4** — the hands-on pen test (C), scoped by your Decision 1.

**The single sentence to remember:** *the assistant is walled off; the coding contractor it hired is
not — and deciding how much to wall it off is worth doing before we rebuild the wall it lives in.*

When you're ready, the only decision that blocks anything is **Decision 1**. The rest I can carry with
the recommendations above unless you say otherwise.
