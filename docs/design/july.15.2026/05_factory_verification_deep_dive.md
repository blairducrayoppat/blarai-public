# Addendum — Factory Verification Deep-Dive (the "no human reads code" crux)

*This deep-dive extends Part 2's Factory target design and the Part 3 Factory gaps. It was folded in after the main synthesis, when the factory research agent's fuller final report arrived — and it sharpens the single most important factory question from a general answer into a concrete, buildable one. If you read one factory document, read this one.*

---

## Why this is the crux

Every classical way of trusting software eventually grounds out in **a human who reads the code or the formal spec.** Your factory forbids that — you never read code. So the entire Factory design reduces to one question the literature is thinnest on: **verification a non-developer can trust without reading anything technical.** The answer has two halves that lock together — a *reviewable contract* you can confirm, and a *mechanical oracle stack* that checks against it — and a hard limit you must know about.

## Half 1 — The Intent Contract (the one thing you *can* read)

The bridge between "intent a non-coder can state" and "verification a non-coder can trust" is a single plain-language artifact you confirm — never code. It has two proven, industrial parts:

- **EARS** (Easy Approach to Requirements Syntax) — a gentle constraint on plain English into a fixed shape: *"While `<precondition>`, when `<trigger>`, the system shall `<response>`."* Five simple patterns, no tooling, readable by anyone. It was built at Rolls-Royce for jet-engine control and is used by NASA, Airbus, Intel, and Bosch — and Amazon's new Claude-based coding tool (Kiro) already generates its acceptance criteria in exactly this form.
- **Specification by Example** (worked examples in "Given–When–Then" form) — a concrete illustration you can read and confirm: *"given an empty cart, when I check out, then I'm told the cart is empty."* It is simultaneously the requirement *and* an executable test.

**The keystone insight (the report's #1 novel connection):** the *same* EARS rules and worked examples you confirm in English are the seed from which the cloud fleet compiles the verification oracles, and the local machine runs them. You review the English contract; the code never enters your view; the oracles are derived from the thing you actually approved. This unifies "requirements," "specification," and "verification" into one artifact you own — and no published spec-tool or research does this framed around a *permanent* non-coder.

**The catch to design against:** the compile step (English contract → executable oracle) is itself AI work and can silently mistranslate — a rule you blessed becomes a test that checks something subtly different, and you cannot see the gap. The mandatory guards: every generated oracle must prove it can catch a deliberately-broken version (or it is presumed vacuous), and a *different-family* model back-translates each oracle to English for you to re-confirm.

## Half 2 — The layered oracle stack (what does the checking)

Because no human reads the code, trust is built from **mechanical checks you cannot argue with, rendered in plain language** — never "the AI said it looks fine." Weakest-but-broadest to sharpest:

1. **Crash/hang/leak detection under sanitizers** — throw huge generated input; any crash is an incontrovertible, code-free defect. Free, pure compute.
2. **Intent-derived partial oracles — metamorphic relations + properties.** When you cannot say the *right* answer, you can often say how answers must *relate* ("a narrower search returns fewer results"; "encode-then-decode returns the original"). A violation proves a bug without knowing the correct output — and the relation is *readable by you in English*. This is the heart of the answer: the relations are the specification you never had to write.
3. **Differential / N-version cross-check** — build several independent versions, run them on the same inputs, and halt on disagreement.
4. **Mutation testing — the check on the checks.** Deliberately inject small faults; a good test suite must *catch* them. This measures whether the tests can find bugs, not merely whether they run. **This layer is non-negotiable, and here is why:** a landmark study (EvalPlus) strengthened the tests on a standard benchmark and watched measured pass-rates drop by **~20%** — meaning roughly *one in five* AI solutions that "passed" were actually wrong and only looked correct because the tests were too weak. **Your Factory must gate on mutation score, not on code coverage.**
5. **A bounded, different-family AI judge — last, least, and only as a plain-language explainer or tie-breaker** among candidates that already passed the mechanical layers. Never the sole arbiter; never Claude judging Claude (a model measurably favors its own outputs).

**What the stack honestly delivers:** high, code-free assurance in plain language — *never a proof of correctness.* Your mental model must be exactly that: "strongly evidenced," not "guaranteed." Sold as more, the stack manufactures the very overconfidence it exists to prevent.

## The hard limit you must know (two structural findings)

These two are **not fixable by being more careful** — they are properties of the situation, and the design must absorb them rather than pretend to solve them:

1. **"Independent" checkers fail *together*.** The Factory's "one agent checks another" borrows its confidence from the idea that independent versions fail independently — which a 1986 experiment proved false *even for separate human teams* (they make the same mistakes on the same hard inputs), and which was **replicated for coding agents in 2026 at 3.7× more coincident failures than independence predicts**, clustered exactly on the hardest problems. Two runs of one model are far more alike than two human teams. **Agreement is a confidence signal, never proof — and unanimous agreement on the hard cases is exactly where they are most likely unanimously wrong.** The mitigation is *real model-family diversity*, which is where your local coder earns its keep (below).

2. **The go-live ceremony decays into rubber-stamping precisely as the Factory gets more reliable.** This is a measured human-factors law (complacency rises with an automation's trustworthiness), and the standard remedy — "make the human verify" — is *blocked* by your permanent non-coder status. The design cannot rely on your vigilance at the ceremony; it must substitute *mechanical evidence + honest distrust cues + accountability framing* ("you are endorsing X; the specific risk you accept is Y") for the verification you cannot perform. State this limit honestly; do not engineer around it with theater.

## The local 30-billion coder's real job

A useful reframe the report surfaced: the local Qwen3-Coder model is a **weak author and a weak judge but a fine re-executor and a genuinely decorrelated second opinion.** Its *difference from Claude* — a different model family, different training — is the asset, not its raw strength. So its highest-value roles are (a) the **decorrelated cross-lineage cross-check** that partially breaks the correlated-failure problem above, and (b) a **cost-efficient first tier** on easy, mechanical tickets, escalating to the cloud only when it fails the gate. Not the primary coder — the swap constraint (it evicts the product brain to run) makes that too costly — but a diversity source the swap constraint otherwise wastes.

## How this changes the gap register (Part 3)

- **GF-1 (grader strength)** is sharpened: the fix is not just "wire the mutation audit" but *gate on mutation score, not coverage* (EvalPlus shows ~20% of thin-test passes are wrong), and derive the oracles from a reviewable Intent Contract so the grader tests what you actually approved.
- **GF-2 (correlated planner/grader)** is sharpened: the 2026 replication (3.7× coincident failure) quantifies it, and the concrete fix is *cross-lineage* diversity — use the local 30B (or a non-AI static check) as the independent version, and back-translate oracles for your re-confirmation.
- **New gap GF-10 (no reviewable intent contract):** today the Factory captures your intent in one thin clarification pass, with no EARS/example artifact you confirm and no artifact the oracles are derived from. This is the missing reviewable bridge — the keystone of a non-coder's factory — and it is a *build*, sequenced in Wave 2.

## Guards for measuring the Factory itself (Part 2 §2.3, sharpened)

When the Factory measures its own quality, four traps must be designed around, all documented in the research: public coding benchmarks are **contaminated** (models recognize the answer from the issue text alone, up to 76%), so self-measurement needs a **private, monthly-rotated holdout** of your own recent work; "more agents helped" claims must beat a **same-model single-agent noise floor** (7 of 10 recent coordination designs failed this); the Factory should be scored on an **accuracy-vs-cost frontier**, not raw pass-rate (a trivial retry baseline matched complex agents at ~50× less cost); and **self-reported "this went well" is unreliable** (experienced developers were measured 19% slower with AI while feeling 20% faster) — only objective outcomes like **change-fail-rate** count. Indeed, when no human reads diffs, *change-fail-rate becomes the code-quality metric.*

## One doctrine correction worth noting

Your standing rule "keep the queue full — a quiet queue is a broken queue" is sharpened by its own source discipline (Reinertsen's flow economics) to **"keep the queue at *optimal* WIP, ordered by cost of delay."** An over-full queue *increases* cycle time and hides problems; the target is high utilization without saturation. For a personal project with no market clock, "cost of delay" re-bases onto *your* priorities and risk posture — which is a decision for you, not a technical default.
