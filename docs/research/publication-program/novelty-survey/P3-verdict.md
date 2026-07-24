---
title: Novelty + Venue Survey Verdict — P3 "The instrument-trust ladder"
status: draft
area: research
piece: P3
tier: engineering epistemology
purpose: REACH (general expert)
surveyed: 2026-07-19
---

# P3 — "The instrument-trust ladder" — survey verdict

Structure follows Author Kit rubric §I.4. All URLs access-dated **2026-07-19**. Tiers:
**T1** primary (peer-reviewed / official first-party docs / methodology / a venue's own rules);
**T2** expert practitioner; **T3** community thread. `[CC]` = closest-competitor.

**Verification note (Author Kit §B).** I personally fetched and confirmed on 2026-07-19
(title / author / date / claim checked against the primary page) the **eleven** sources
most load-bearing for this verdict or most likely to be wrong: EvalGen (2404.12272),
Panickssery et al. (2404.13076), the Judge Reliability Harness (2603.05399), optivem's TDD
essay, TestDino, the Yegge-8-Levels writeup, Proof-or-Stop (2607.14890), the False Success
paper (2606.09863), Böckeler & Ford, Osmani's "Own the Outer Loop," Eugene Yan, and Simon
Willison's "Vibe engineering" (2025-10-07). The two
arXiv IDs I was initially suspicious of (2603.05399, 2607.14890) both resolved to real
papers. **Every OTHER row comes from the parallel research pass and is NOT independently
re-verified by me here** — including the acknowledged classics (mutation testing 1978 / Jia
& Harman 2011; the oracle-problem survey 2015; Thompson 1984; chaos principles), the broader
judge corpus (JudgeBench, MT-Bench), the first-party grader docs, and TRL/GRADE/DoD. All are
canonical or research-sourced but MUST be re-verified verbatim by the author at draft time
per §B.

---

## §I.4.1 — Prior-art map

### Thread A — the ladder's rung CONTENT (green tests → mocks lie → positive controls)

| Who | What | Where / When | Tier | Link | Relevance |
|---|---|---|---|---|---|
| Pratik Patel | "How to Test AI-Generated Code (Without Shipping Confident Bugs)" | TestDino blog / upd. 2026-07-14 | T2 | https://testdino.com/blog/how-to-test-ai-generated-code | **[CC] on rung content.** Independently walks all three rungs for the exact AI-code audience, incl. positive control. Verbatim: *"a unit test is a claim about your mocks, not your system"*; *"change the code so it's wrong, and confirm the test goes red."* |
| DeMillo, Lipton, Sayward | "Hints on Test Data Selection" (mutation testing origin) | IEEE Computer / 1978 | T1 | https://www.scirp.org/reference/referencespapers?referenceid=953139 | **[CC] formal ancestor.** The original "positive control for your test suite" — inject a known-bad mutant; the suite earns trust only if it *kills* it. |
| Jia & Harman | "An Analysis and Survey of the Development of Mutation Testing" | IEEE TSE 37(5) / 2011 | T1 | https://web.eecs.umich.edu/~weimerw/2022-481F/readings/mutation-testing.pdf | Definitive survey; high coverage + low mutation score = P3's "green suite that never fired on a known-bad input." |
| Barr, Harman, McMinn, Shahbaz, Yoo | "The Oracle Problem in Software Testing: A Survey" | IEEE TSE 41(5) / 2015 | T1 | https://discovery.ucl.ac.uk/1471263/ | **[CC] on the concept axis.** The academic name for P3's problem: can the checker be believed? |
| T.Y. Chen et al. | "Metamorphic Testing: A Review of Challenges and Opportunities" | ACM Comput. Surv. 51(1) / 2018 | T1 | https://dl.acm.org/doi/10.1145/3143561 | The field's main answer to "what do you do when you can't trust/have an oracle." |
| Valentina Jemuović | "TDD: If Your Test Never Fails, It's Broken" | optivem journal / 2026-04-07 | T2 | https://journal.optivem.com/p/tdd-if-your-test-never-fails-its-broken | **[CC] on the metaphor.** P3's claim near-verbatim + the SAME fire-alarm image: *"skipping RED is like installing a fire alarm that never goes off."* |
| Basiri, Rosenthal et al. (Netflix lineage) | "Principles of Chaos Engineering" | principlesofchaos.org / upd. 2019 | T1 | https://principlesofchaos.org/ | **[CC] on the "borrow experimental-science rigor" axis.** Already frames verification as a controlled experiment with explicit *control vs. experimental group* language. |
| Google SRE | Testing alerting / validating monitoring | SRE Workbook & Book | T1 | https://sre.google/workbook/monitoring/ | A positive control for monitoring in all but name: inject a known-bad signal, confirm the alarm fires. |
| Ken Thompson | "Reflections on Trusting Trust" | CACM 27(8) / 1984 | T1 | https://www.cs.cmu.edu/~rdriley/487/papers/Thompson_1984_ReflectionsonTrustingTrust.pdf | The philosophical ceiling above P3's ladder: you must eventually trust a tool you cannot fully verify. |
| (benchmarking-skeptic genre) | "Your benchmark is lying to you" (FOSDEM 2026 talk; JMH field guides) | 2026 | T2/T3 | https://kakkoyun.me/posts/fosdem-2026-measuring-software-performance/ | Direct analog to P3's incident #2 — a performance scare caused by the measuring instrument, not the system. A named, recurring sub-genre. |

### Thread B — the LLM-as-judge reliability debate (P3's rung-3 "soft oracle" material)

| Who | What | Where / When | Tier | Link | Relevance |
|---|---|---|---|---|---|
| Shankar, Zamfirescu-Pereira, Hartmann, Parameswaran, Arawjo | "Who Validates the Validators? …" (EvalGen) | arXiv 2404.12272 / UIST 2024 | T1 | https://arxiv.org/abs/2404.12272 | **[CC] — overall closest on the judge thread.** Thesis verbatim: *"LLM-generated evaluators simply inherit all the problems of the LLMs they evaluate, requiring further human validation."* Generates BOTH Python assertions and grader prompts; validates against human grades; names "criteria drift." |
| Eugene Yan | "Evaluating the Effectiveness of LLM-Evaluators (aka LLM-as-Judge)" | eugeneyan.com / 2024-08 | T2 | https://eugeneyan.com/writing/llm-evaluators/ | **[CC] at T2.** "Validate the evaluators before use"; covers self-enhancement/position/verbosity bias with measured self-preference win-rates. |
| Hamel Husain | "Creating a LLM-as-a-Judge that drives business results" | hamel.dev / 2024-10 | T2 | https://hamel.dev/blog/posts/llm-judge/ | The most-cited practitioner canon on making a judge trustworthy; distrust naive 1–5 scores. |
| Panickssery, Bowman, Feng | "LLM Evaluators Recognize and Favor Their Own Generations" | arXiv 2404.13076 / NeurIPS 2024 | T1 | https://arxiv.org/abs/2404.13076 | **[CC] for the "answer-key" incident.** The published academic form of "a grader with the answer key in its pocket": self-recognition causally drives self-preference. |
| Zheng et al. | "Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena" | arXiv 2306.05685 / NeurIPS 2023 | T1 | https://arxiv.org/abs/2306.05685 | Foundational; named the position/verbosity/self-enhancement bias taxonomy P3 stands on. |
| Dev, Sloan, Kavner, Kong, Sandler | "Judge Reliability Harness: Stress Testing the Reliability of LLM Judges" | arXiv 2603.05399 / ICLR 2026 wksp | T1 | https://arxiv.org/abs/2603.05399 | **[CC] for the positive-control move.** Already an instantiated 2026 tool that probes judges with label-flipped known-bad responses — P3's "feed the detector a known-bad case." |
| Tan et al. | "JudgeBench: A Benchmark for Evaluating LLM-Based Judges" | arXiv 2410.12784 / ICLR 2025 | T1 | https://arxiv.org/abs/2410.12784 | "Who judges the judges" at benchmark scale — strong judges barely beat random on checkable pairs. |
| OpenAI / Anthropic / Braintrust / DeepEval | Code-based graders vs model graders; "combine grader types"; deterministic-vs-judge rule | first-party docs / current | T1 | https://developers.openai.com/api/docs/guides/graders · https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents | The deterministic-gate-under-the-soft-oracle pattern, already first-party guidance. |

### Thread C — AI-coding epistemology (the "ladder / levels / instrument" framing)

| Who | What | Where / When | Tier | Link | Relevance |
|---|---|---|---|---|---|
| Birgitta Böckeler & Chris Ford | "Harness engineering and agent feedback: Exploring AI coding sensors" | Thoughtworks / 2026-05-13 | T2 | https://www.thoughtworks.com/insights/blog/generative-ai/harness-engineering-agent-feedback-exploring-ai-coding-sensors | **[CC] on instrument vocabulary.** "Sensors" observe what the agent produced; splits deterministic vs LLM judgement (*"a…deterministic tool gives you more assurance"*). **Explicitly does NOT argue the sensors must themselves be validated** — this is exactly where P3's rung 3 is unoccupied. |
| Steve Yegge (model); Augment Code writeup | "The 8 Levels of AI-Assisted Development" | augmentcode.com / 2026 | T2 | https://www.augmentcode.com/guides/steve-yegge-8-levels-ai-assisted-development | **[CC] on "staged ladder for AI dev" — but different axis** (autonomy/orchestration, not verification-trust). Owns the levels-model real estate on an unrelated axis. |
| Addy Osmani | "Own the Outer Loop" | addyosmani.com / 2026-07-15 | T2 | https://addyosmani.com/blog/own-the-outer-loop/ | **[CC] on the honesty/reporting boundary.** *"an independent check, not the model's own say-so, decides when the work is done."* Binary human-owned verdict — NOT a graded scale. |
| Simon Willison | "Vibe engineering" | simonwillison.net / 2025-10-07 | T2 | https://simonwillison.net/2025/Oct/7/vibe-engineering/ | Names the senior practices that make AI-assisted coding trustworthy; no ladder, no scale. High-reach amplifier. |

### Thread D — "honesty machinery" (false-done intolerance, evidence tiers, verdict grammar)

| Who | What | Where / When | Tier | Link | Relevance |
|---|---|---|---|---|---|
| Huang, Hsia, Sun, Shi, Huang, White | "Proof-or-Stop: Don't Trust the Agent, Trust the Evidence — …Evidence-Gated Lifecycle Control" | arXiv 2607.14890 / 2026-07-16 | T1 | https://arxiv.org/abs/2607.14890 | **[CC] — closest to the honesty machinery, and THREE DAYS OLD.** Evidence-gated lifecycle; *"treats agent outputs as claims rather than lifecycle state"*; deterministic receipts (no LLM oracle); *"passed 10 of 10 scenarios with zero false-DONE."* |
| Laksh Advani | "From Confident Closing to Silent Failure: Characterizing False Success in LLM Agents" | arXiv 2606.09863 / 2026-06 | T1 | https://arxiv.org/abs/2606.09863 | Names the exact phenomenon P3 targets (*"assert task completion when the environment state shows otherwise"*, 3–75.8%). **Also AMMUNITION:** finds deterministic TF-IDF detectors beat LLM judges — independent support for "deterministic gate under the soft oracle." |
| Patrick Hughes | "Your AI Agent Says 'Done.' Make It Prove It." | bmdpat.com / 2026-06-24 | T2 | https://bmdpat.com/blog/ai-agent-claims-done-verify-2026 | **[CC].** Verdict grammar + deterministic checker + zero-tolerance, for practitioners: *"Completion is legitimate only after the checker is green."* No graded scale. |
| NASA | Technology Readiness Levels (TRL) | nasa.gov / classic | T1 | https://www.nasa.gov/directorates/somd/space-communications-navigation-program/technology-readiness-levels/ | Canonical graded-maturity scale; DESIGNED-DEFERRED→BUILT-DORMANT→TESTED→VERIFIED-LIVE mirrors TRL's concept→lab→relevant-env→operational. |
| GRADE Working Group | Certainty-of-evidence grading (High/Moderate/Low/Very Low) | Cochrane Handbook ch.14 / 2004+ | T1 | https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-14 | The medical analog structurally closest to P3's **four**-grade "how much do we believe this" ordinal. |
| Scrum | "Definition of Done" | scrumguides.org / classic | T1 | https://scrumguides.org/ | The binary-checklist analog P3's graded scale supersedes. |

*(RELATED-WORK, not competitors: LessWrong "AI Evaluations" tag & eval-gaming discourse — T3, interest not a claim; RewardBench, PoLL juries-of-judges, JudgeDeceiver, Preference Leakage — the broader judge-reliability corpus; DEMM arXiv 2605.04093 — graded agent-evidence on the governance axis. Full list in the source pass.)*

---

## §I.4.2 — The gap

**The core concept is SATURATED. P3 can claim no conceptual novelty for "verify your
verifier," for positive controls, for LLM-judge distrust, or for false-done intolerance.**
Each is independently published, several by first-party labs, and — critically — several
within DAYS of this survey (TestDino 2026-07-14; Osmani 2026-07-15; Proof-or-Stop
2026-07-16). Mutation testing (1978) is the 48-year-old formal ancestor of "positive
controls for tests"; the oracle-problem survey (2015) is the academic name for "can the
checker be believed"; chaos engineering already transplanted experimental-science
control-group rigor into verification; EvalGen/Yan/Panickssery own "validate the
validators"; Proof-or-Stop implements the honesty machinery as architecture with a
measured false-DONE=0.

**What genuinely survives — a narrow but real envelope, three parts:**

1. **Cross-domain synthesis for a general audience.** These silos do not talk to each
   other. Mutation-testers, chaos engineers, SRE alert-testers, benchmarking skeptics,
   LLM-eval researchers, and agent-false-success researchers each independently
   discovered "instruments must earn belief" — nobody has named the through-line as one
   legible **epistemology ladder for AI-driven software development**. Yegge owns "levels
   for AI dev" on the autonomy axis; nobody owns it on the verification-trust axis.

2. **The meta-trust rung, applied to AI-agent verification, with reach.** Böckeler &
   Ford have the "sensor" vocabulary but *explicitly stop short* of "the sensors must
   themselves be validated." P3's rung 3 — positive controls FOR the AI-verification
   instruments — is the least-occupied ground in the high-reach practitioner space (its
   only close neighbours are formal: mutation testing, and the model-eval Judge
   Reliability Harness).

3. **Named, first-person incidents from one fully-instrumented build.** The corpus is
   dominated by benchmark-scale statistics and vendor tooling docs — NOT a longitudinal
   engineering narrative with named incidents: the screenshot tool that "convicted an
   innocent app" via file:// artifacts; the performance scare that was three instrument
   bugs; the AI grader that had the answer key; deliberately rigged failing cases to
   prove a detector detects. This is the freshest, most defensible ground, and it is
   exactly the program's declared asset (n=1, everything documented and checkable).

**The recent literature is both competition AND ammunition:** Advani's finding that
deterministic detectors beat LLM judges, and Böckeler-Ford's "deterministic tool gives
more assurance," are citable *support* for P3's thesis — cite them as corroboration, not
just as prior claimants.

---

## §I.4.3 — Verdict

**RESHAPE → GO (once repositioned). NOT a KILL; NOT a STRONG-GO.**

Reasoning an expert in this space would accept: the piece as currently conceived is
exposed on novelty — an expert reviewer can falsify any "here's a new idea" framing in one
citation (mutation testing, EvalGen, or the three-days-old Proof-or-Stop). But the
first-person **documented-case-study register with named instrument-failure incidents is
genuinely underserved**, and the cross-domain synthesis + the AI-agent-verification
application of the meta-trust rung is real, defensible white space. The reshape is not
cosmetic; it changes what the piece claims:

- **Reposition as synthesis, not discovery.** Credit the saturated prior art up front
  (mutation testing, oracle problem, chaos engineering, EvalGen). Stake the claim
  explicitly on the through-line + the AI-agent application + the incidents.
- **Lead with the incidents.** They are the irreplaceable n=1 asset; the abstractions
  must be cashed out in a documented incident within a paragraph (Author Kit §G, P3
  voice). The file:// screenshot and the three-instrument perf scare are the strongest.
- **Engage the days-old competitors directly as related work** — Proof-or-Stop, False
  Success, TestDino, Böckeler-Ford — distinguishing P3's contribution (a *documented
  practitioner epistemology*, not a system or a benchmark).
- **Cite, don't re-discover, the "answer-key" phenomenon** (Panickssery 2024; self-
  preference / preference-leakage) — the incident is a single-project instance of a
  named academic result.
- **Do the Phase-1 deep survey close to draft time.** This field is filling weekly; the
  honesty-machinery half especially.

---

## §I.4.MERGE — one piece or two?

**CONFIRM THE MERGE: ONE piece.** The honesty machinery is the *mechanism half* of a
single ladder essay, subordinated under the epistemology, with a clean seam kept so it can
be spun out later if it grows.

Reasoning:
- **Shared thesis spine.** Both halves say one thing: *an AI agent's self-report cannot
  be trusted; belief is earned by evidence, and the evidence-instruments must themselves
  be validated.* The ladder is the epistemology; the honesty machinery (four-grade scale,
  verdict grammar, deterministic gate under the soft oracle) is how you operationalize it.
  The two 2026 works closest to P3 — Osmani's "Own the Outer Loop" and Proof-or-Stop —
  each naturally fuse epistemology and mechanism, which is evidence the fusion is the
  natural unit.
- **The named incidents serve both halves** (the AI-grader-with-answer-key incident is
  simultaneously a rung-3 instrument-failure and the motivation for the honesty machinery),
  so splitting would duplicate the evidence base and thin both pieces.
- **Right publishable unit for the target venues.** One arced 3–4k-word essay (epistemology
  → the machinery we built to enforce it → the incidents that taught us each rung) is what
  LessWrong-Frontpage and HN reward; two overlapping essays would compete and dilute.

Two caveats on the merge:
- **Give the honesty machinery its own related-work paragraph.** Its prior-art landscape
  (Proof-or-Stop, False Success, Hughes, TRL/GRADE/DoD) is *distinct* from the ladder's
  (mutation testing, oracle problem, chaos, EvalGen). A merged essay must not blur the two
  maps.
- **Keep the option to extract.** The honesty machinery is the more crowded, faster-moving
  half (Proof-or-Stop is 3 days old). If a reviewer finds it dilutes the epistemology arc,
  extract it into a focused practitioner-short (P7-adjacent). Default: merged.

---

## §I.4.4 — Venue fit

### Home base — GitHub Pages blog on the public mirror (T1: author-owned)
**Fit: the anchor, publish here always.** Canonical URL he owns, no gatekeeper, no
moderation queue, instant + permanent. Satisfies HN's "submit the original source" and
LW's linkpost model by *being* the original, so zero self-promotion risk. **Limitation:**
no built-in audience — discovery depends entirely on the outbound LW/HN posts. Publish
here first; every community post links back here.

### LessWrong (lesswrong.com)
**Fit: STRONG, with one framing caveat.** The essay is literally about when to trust a
verification instrument — LW's home turf ("improving human reasoning and decision-making",
https://www.lesswrong.com/about). The judge/evals thread connects to the live **AI
Evaluations** tag (https://www.lesswrong.com/tag/ai-evaluations, **298 posts**, access
2026-07-19) — the natural discovery surface and correct tag. Caveat: written as "here's a
cool thing I built" it lands as a *Personal blogpost*; written argument-first
(project-as-evidence) it can earn *Frontpage*.

**Mechanics / gates (all from LW's own pages, access 2026-07-19):**
- **First post is human-reviewed before it goes live.** *Quoted:* "We review every first
  post and comment before it goes live to ensure it's up to par."
  (https://www.lesswrong.com/posts/LbbrnRvc9QwjJeics/new-user-s-guide-to-lesswrong)
- **New-user rate limits (karma-gated).** *Quoted:* "Users whose total karma is < 5 are
  limited to 3 comments a day, and 2 posts per week."
  (https://www.lesswrong.com/posts/hHyYph9CcYfdnoC5j/automatic-rate-limiting-on-lesswrong)
  — live policy; re-check at posting time.
- **Linkposts/crossposts welcome but write for LW.** *Quoted:* "Linkposts that include at
  least a short description of why the topic is relevant/interesting to LessWrongers tend
  to get more engagement." (https://www.lesswrong.com/faq); the New User's Guide warns
  against low-effort crossposts.
- **Frontpage is moderator-decided; author opts in.** *Quoted criteria:* "Useful, novel,
  and relevant to many LessWrong members"; "'Timeless'… likely to remain useful even after
  a few years"; "attempts to explain rather than persuade."
  (https://www.lesswrong.com/posts/5conQhfa4rgb4SaWx/site-guide-personal-blogposts-vs-frontpage-posts)
  → keep it explain-not-sell, minimize time-bound detail.
- **Self-promotion:** no explicit anti-self-promo rule found on FAQ/About/Site-Guide; the
  governing constraint is the quality bar + first-post review (gap flagged: absence of a
  rule is not a stated permission).

**Exemplars (the bar):**
1. Elizabeth, "Epistemic Legibility" (324 karma, 2022) —
   https://www.lesswrong.com/posts/jbE85wCkRr9z7tqmD/epistemic-legibility — *the register:*
   being explicit about evidence so others can check you is a virtue distinct from being
   right; LW will judge P3 by exactly this.
2. Yudkowsky, "Security Mindset and Ordinary Paranoia" (134 karma, 2017) —
   https://www.lesswrong.com/posts/8gqrbnW758qjHFTrH/security-mindset-and-ordinary-paranoia
   — *the thesis shape:* you need positive arguments a system is secure, not a pile of
   patched flaws = "instruments must earn belief via positive controls."
3. Yudkowsky, "Local Validity as a Key to Sanity and Civilization" (252 karma, 2018) —
   https://www.lesswrong.com/posts/WQFioaudEH8R7fyhm/local-validity-as-a-key-to-sanity-and-civilization
   — step-level checkable validity = the backbone of "deterministic gates under LLM judges."

### Hacker News (news.ycombinator.com)
**Fit: GOOD — submit as a NORMAL LINK, not Show HN.** A technical-epistemology essay from
a personal blog is core HN fare. *Quoted* (https://news.ycombinator.com/showhn.html):
"blog posts… other reading material… can't be tried out, so can't be Show HNs."

**Mechanics / rules (HN's own pages, access 2026-07-19):**
- **No account-age/karma gate to submit; goes live immediately** (no first-post review).
  Story rank is not karma-weighted — *quoted:* "Do posts by users with more karma rank
  higher? No." (https://news.ycombinator.com/newsfaq.html). Karma thresholds exist only for
  voting/flagging actions, and the exact numbers are *not published* (gap flagged).
- **Self-promotion allowed in moderation.** *Quoted*
  (https://news.ycombinator.com/newsguidelines.html): "Please don't use HN primarily for
  promotion. It's ok to post your own stuff part of the time, but the primary use of the
  site should be for curiosity."
- **No solicited votes.** *Quoted:* "Don't solicit upvotes, comments, or submissions."
  (→ do NOT ask colleagues/the fleet to upvote — a real hazard for a fleet-built piece.)
- **Submit the canonical source; don't editorialize the title.** *Quoted:* "Please submit
  the original source."; "don't editorialize"; "Please don't do things to make titles stand
  out, like using uppercase or exclamation points."
- Front-page is timing/variance-sensitive; a curiosity-first title about the IDEA beats one
  about the personal system. Reposts allowed sparingly if it sank without attention.

**Exemplars (front-page bar; counts via HN's official Algolia API, access 2026-07-19):**
1. Hillel Wayne, "Why Don't People Use Formal Methods?" — 420 pts/225 comments —
   https://www.hillelwayne.com/post/why-dont-people-use-formal-methods/ — *closest
   analogue:* a deep honest essay about verification tools and why practitioners trust
   them, from a personal blog exactly like the intended home base.
2. Hillel Wayne, "Are We Really Engineers?" — 317 pts/389 comments —
   https://www.hillelwayne.com/post/are-we-really-engineers/ — turning one body of evidence
   into a transferable epistemological claim, which is P3's task.
3. Dan Luu, "Willingness to look stupid" — 1,859 pts/777 comments —
   https://danluu.com/look-stupid/ — the tone model: first-person, evidence-honest,
   general-expert register that carries a reasoning essay to the top of HN.

---

## §I.4.5 — Piece-specific risks

1. **Overclaim (the #1 risk, and why RESHAPE).** Presenting "verify your verifier" /
   positive controls / false-done intolerance as novel is falsified in one citation
   (mutation testing 1978; EvalGen 2024; Proof-or-Stop 3 days old). Mandatory: position as
   synthesis, credit prior art up front.
2. **A fast-moving competitor field.** Three of the closest competitors landed within a
   week of this survey. The honesty-machinery half is especially exposed (Proof-or-Stop
   does it as measured architecture). Phase-1 must re-survey at draft time.
3. **n=1 overreach.** One project/box/operator. Every generality claim stays
   INTERPRETATION-typed and hedged (Author Kit §E); the strength is the documentation, not
   the sample.
4. **Incident specificity vs. leak gate.** The named incidents are the asset but must clear
   the public-mirror leak standard (Author Kit §D): no local paths/hostnames, no
   security-sensitive residuals of the egress/policy machinery beyond what the mirror
   exposes.
5. **LW audience-fit hazard.** "Here's what I built" → Personal blogpost, misses Frontpage.
   Must be argument-first; the single-project framing must not read as promotion.
6. **Merge-seam risk.** If merged (recommended), the honesty machinery needs its OWN
   related-work paragraph — its prior-art map is distinct from the ladder's; blur them and
   a reviewer conflates the two landscapes.
7. **AI-authorship optics on HN.** A fleet-built essay about trusting AI output, on the
   venue most allergic to solicited votes and self-promotion — honor the disclosure stance
   (once the LA sets it) and the no-solicited-votes rule strictly.
