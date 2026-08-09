# How We Measure Quality — An Assessment Prompted by an Evaluation-Frameworks Survey

**Date:** 2026-07-20
**Asked by:** Lead Architect ("is any of this helpful to us?")
**Answered by:** Claude session (Opus 4.8), grounded on disk + primary sources
**Ticket:** #998
**Status:** COMPLETE. Five research legs, all reported. **No code changed** — every finding is ticketed.
Load-bearing claims were re-verified at source independently of the legs that reported them; one leg's
claim did not survive that check and is corrected in §3.4.

> **Acronyms on first use.** LLM = Large Language Model (the kind of AI that produces text).
> RAG = Retrieval-Augmented Generation (fetching documents, then answering from them).
> CI = Continuous Integration (the automated checks that run before code is allowed to merge).
> LA = Lead Architect. AO = Assistant Orchestrator. PA = Policy Agent.
> Best-of-N = generating several candidate answers and picking the best one.

---

## 0. The short version

**The article itself is worth little to us. Investigating its one good idea was worth a great deal.**

Its tooling advice describes machinery we already built, and its top-recommended tool turns out to be one
we must refuse. But its observation that *every* framework ultimately asks a model to grade a model sent us
looking at our own judges — and that search turned up four defects, three of them unrelated to judge bias
and one of them shipping in production since 2026-07-10.

| # | Question | Answer | Why, in one line |
|---|---|---|---|
| 1 | Should we adopt any of the four frameworks? | **No** | Three phone home by default; the fourth is viable but only incrementally useful. |
| 2 | Are our judges biased? | **Structurally exposed, not measurably inflated** | Every model in the fleet is the same family, but the deterministic layer carries almost all the weight. |
| 3 | Is our headline quality number inflated? | **No** | GREEN is a pure function over real test exit codes; every eval suite is judge-free by design. |
| 4 | Do we measure retrieval quality? | **No — and the blind spot is hiding a live defect** | Production ranking has measurably underperformed since 07-10; nothing can see it. |
| 5 | Does the standing gate measure model quality? | **Essentially not at all** | All 41 model cases across all suites are skipped; the gate is conventional software testing. |
| 6 | Does the hardware tier catch regressions? | **No — it has no teeth** | A branch fall-through absorbed 3 of 4 injection-resistance failures as "0 regressions". |

**Four defects found, all ticketed, none deferred:**

| Ticket | Defect | Severity |
|---|---|---|
| **#1000** | Hardware-tier eval cases cannot fail the run; 3 of 4 injection-resistance failures were reported as "0 regressions" | **Highest** — a security control degrading silently |
| **#795** (re-raised) | Production retrieval ranking measurably below the simpler alternative it contains; root cause named 07-10, unchanged in source | High — live answer quality |
| **#1001** | The battery's night-over-night trend has never produced a delta across 11 nights | Medium — the only longitudinal instrument |
| **#999** | A comment asserts a live isolation control is dormant behind a "double lock" that does not exist | Medium — false protection claim |

**Three decisions for the Lead Architect** are collected in §8.2. Everything else in §8 is mine and is
either done or ticketed.

---

## 1. What the article actually offers us

The article surveys four evaluation tools — RAGAS, DeepEval, Promptfoo, and lm-evaluation-harness —
and makes a reasonable structural point: "LLM evaluation" is really three different activities that get
confused with each other.

| Category | What it asks | Typical tools |
|---|---|---|
| Model benchmarking | How good is this model in the abstract? | MMLU, GSM8K, lm-evaluation-harness |
| Application evaluation | Is *this system's* output correct for *its* task? | RAGAS, DeepEval |
| Production monitoring | What is actually happening in live use? | LangSmith, Braintrust, Arize Phoenix |

That frame is useful and we adopt it in §4 to map our own machinery.

**Most of the article's tooling advice does not apply to us.** Its central recommendation — adopt a
pytest-integrated framework that blocks merges on quality thresholds — describes something this project
already built and has been running for months. The standing gate and the `evals` suite gate are exactly
that shape, native, with committed baselines and regression exit codes.

**One part of the article is genuinely load-bearing**, and it is not the tool comparison. It is the section
on judge bias: the observation that every one of these frameworks ultimately asks a language model to
grade another language model's output, and that this act carries measurable, systematic distortions.
That claim is worth taking seriously because it applies to machinery we already run, regardless of whether
we ever install any of the four tools.

So the rest of this document largely sets the article aside and investigates the bias question directly,
against our own code and against the primary research literature rather than a secondary summary.

---

## 2. What the research literature actually establishes

The article asserts three biases. Because a blog post is not evidence, each was checked against the
underlying papers. Two are well-established with measured effect sizes; one of them turns out to be more
interesting than the article conveys, and one directional claim in the secondary sources was **wrong** and
had to be resolved against the paper itself.

### 2.1 Self-preference bias is really a familiarity bias

**Source:** Wataoka, Takahashi & Ri, *Self-Preference Bias in LLM-as-a-Judge*
([arXiv:2410.21819](https://arxiv.org/abs/2410.21819), Oct 2024, rev. Jun 2025).

The paper introduces a quantitative metric for self-preference and confirms GPT-4 exhibits it
significantly. But its important finding is the *mechanism*. Quoting the abstract:

> "Our findings reveal that LLMs assign significantly higher evaluations to outputs with lower perplexity
> than human evaluators, **regardless of whether the outputs were self-generated**. This suggests that the
> essence of the bias lies in perplexity and that the self-preference bias exists because LLMs prefer texts
> more familiar to them."

This reframes the risk in a way that matters for us. The bias is not a vanity effect requiring the judge to
somehow recognise its own handiwork. It is a preference for text that is *statistically familiar* to the
judge — low-perplexity text. Two consequences follow:

1. **A same-family judge is exposed by mechanism, not by coincidence.** A Qwen judge finds Qwen-generated
   text familiar whether or not it can identify the author. Swapping to a different model family is
   therefore a grounded mitigation rather than a superstition.
2. **The bias systematically favours the generic over the distinctive.** Low perplexity means predictable,
   conventional, boilerplate-shaped. A judge under this bias will tend to prefer unremarkable code over
   unusual-but-better code. Any grading band we operate that is meant to reward craft is pushing directly
   against this gradient.

Reported effect sizes elsewhere in the literature: roughly 10% inflation for GPT-4o on its own outputs,
around 25% for earlier Claude models, with much wider ranges on adversarial datasets.

### 2.2 Position bias is worst exactly where we use ranking

**Source:** Shi et al., *Judging the Judges: A Systematic Study of Position Bias in LLM-as-a-Judge*
([arXiv:2406.07791](https://arxiv.org/abs/2406.07791), Jun 2024, rev. Nov 2025) — 15 judge models,
over 150,000 evaluation instances.

Position bias is the tendency to favour a candidate because of *where it sits in the prompt*. The paper
establishes it is systematic, not noise, and defines three metrics: repetition stability, position
consistency, and preference fairness.

The finding that matters to us concerns *when* the bias bites. **The secondary summaries got this
backwards**, and the two sources consulted contradicted each other outright, so it was resolved against the
paper's own text. Verbatim:

> "PC is positively proportional to δ_q. This aligns with our intuition that the answer pairs with larger
> quality disparities are easier to achieve consistency"

> "whereas those of similar quality are difficult to judge, **increasing the likelihood of position bias**
> that leads to lower PC."

So: position bias is **mild when candidates differ clearly in quality, and severe when they are close.**

That is the sharp edge for this project. Best-of-N candidate selection generates several candidates *from
the same model, on the same task, under the same prompt*. By construction those candidates are near-equal
in quality — the precise regime the paper identifies as most susceptible. A ranking mechanism is least
trustworthy exactly where we lean on it hardest.

> **Method note, recorded deliberately.** Both the article and an initial source summary stated the
> quality-gap relationship the wrong way round. Had this document been written from the summaries, its
> central finding would have been inverted. This is the same failure the project has logged three times
> already on 2026-07-20 — documentation describing an artifact, believed instead of the artifact — and it
> recurred here on the fourth attempt within the same day. The rule held only because it was applied.

### 2.3 Verbosity bias

Consistently measured across judges: a preference for longer responses of about +17.3%, against +12.9%
for human evaluators — so judges are not merely reproducing a human preference, they are amplifying it.
Noted for completeness; less immediately actionable for us than the first two.

### 2.4 The "80% agreement with humans" figure does not license what it is used to license

**Source:** Zheng et al., *Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena*
([arXiv:2306.05685](https://arxiv.org/abs/2306.05685), Jun 2023, rev. Dec 2023).

This is the paper behind the reassuring statistic that circulates whenever anyone questions model-based
grading. Its actual claim, verbatim:

> "strong LLM judges like GPT-4 can match both controlled and crowdsourced human preferences well,
> achieving over 80% agreement, the same level of agreement between humans."

Read carefully, that figure describes **agreement with human *preference* judgements on open-ended
conversational questions** — which of two chat answers a person likes better. It is a strong result for
that task. It says nothing about agreement on the questions we actually ask our judges: did this code
satisfy its contract, is this answer grounded in the passage that was retrieved, did this run genuinely
succeed. Those are verifiable-truth questions, not preference questions, and the paper does not measure
them. Notably, the same paper independently names position, verbosity, and self-enhancement bias as
limitations — the reassuring number and the warnings come from the same authors.

The practical upshot: 80% agreement is not a warrant for trusting a model verdict about whether something
*works*. Where truth is checkable, check it. This is the direction the project has already been moving
under #855 and #946, and the literature supports it.

---

## 3. Our own judge paths — self-preference exposure

**Headline: today, measured quality is largely NOT inflated — and the deterministic layer is why. But the
exposure is real, it is armed rather than firing, and it sits one level up from where you would look.**

### 3.1 The structural fact

`configs/model-profiles.json` settles the family question without inference. Every model in the fleet
carries `"family": "qwen3"` — the 30B coder, the 14B planner/oracle-author/critic/assistant, and the 8B
vision model. **There is no non-Qwen model anywhere in any judgement path in either repository.**

That matters specifically because of §2.1's mechanism. The manifest describes one path as a "14B cross-model
critic" — accurate as far as it goes, since 14B ≠ 30B. But under a perplexity/familiarity mechanism,
*cross-model is not the property that protects you.* Shared pretraining lineage is. A Qwen judge finds Qwen
text familiar whether or not the parameter counts differ.

### 3.2 Where measurement is genuinely safe

The good news is structural and deliberate:

- **GREEN is fully deterministic.** `compute_job_verdict` (`swap_driver.py:860`) is a pure function over
  task statuses, gate results and oracle status. A GREEN requires a real pytest exit code under the #822
  clean-environment recipe. The nightly battery's headline number is not inflated by judge bias in scoring.
- **Best-of-N selection is exit-code arithmetic** (confirmed independently, §4).
- **Every eval suite is deterministic.** `rubric.py:6` states outright: "no LLM judge, no similarity model."
  `evals/README.md:84-86` confirms a local-14B-as-judge suite is a documented *follow-on*, not something
  built. `evals/suites/coordinator.py:968` fails closed rather than model-grade.
- The Layer-1 green-quality signals — `regressed` and `craft-residue`, the two tallies that appear on every
  night's report — are deterministic archetype-diff and craft lints with no model involved.

The project's sustained push toward the deterministic layer (#946, #855, ADR-037's *model proposes,
deterministic disposes*) has genuinely worked. The prose judging is thin; the deterministic layer carries
the weight. That should be reported as the finding it is.

### 3.3 Where the exposure is real, in priority order

**1. The green-quality jury — armed, not firing.** This is the surface §2.1 predicted, and it is worse in
shape than expected. `green_quality/jury.py:247` builds a three-juror panel whose stated purpose is to
"decorrelate the errors a homogeneous panel would repeat." But all three jurors share **one injected model
call** — a single Qwen3-14B — differing only by lens emphasis and seed (mode string `det+14b-x3`).

Prompt emphasis and seed cannot decorrelate a bias that lives in the weights. All three jurors share one
identical perplexity gradient, so majority-voting them **amplifies** the shared bias rather than cancelling
it. The abstain-on-disagreement rule compounds this in the worst direction: the three will agree most
reliably exactly where the shared prior is strongest — on familiar boilerplate.

And it grades `naming_structure` (`band.py:81`), the purest craft-versus-blandness axis in the rubric. A
band designed to reward craft, scored by an instrument that systematically rewards familiarity.

**It is currently dormant.** Both live callers pass no jurors; live mode is `det-only`. The mitigations are
genuinely strong: Layer-1 outranks the jury by design, an abstained field never worsens a band, advisory
status is enforced in code (`__init__.py:24-28` snapshots and restores verdict/attribution), and the KPI
line self-discloses its mode — so `det+14b-x3` appearing in that string is the tell to watch for.
`jury.py:255` already notes the fix seam: route jurors to different models via a dispatcher function.

**2. Oracle and criteria authoring — live, wide reach, structurally invisible.** `acceptance.py:2442`/`:2679`
have the 14B author the acceptance tests that grade the 30B's code. The docstring claims this is
"CROSS-MODEL by construction… sidesteps the self-test validity problem" — true about *authorship*, silent
about *family*. Execution is immune (a pytest exit code), so the exposure is not in scoring but in **what
the oracle chooses to assert**: a same-lineage author finds its sibling's API shapes, naming and
error-handling idioms unsurprising, and under-tests precisely the shared conventions. Nothing downstream
can see this, because every deterministic control faithfully executes whatever the oracle asserts.

This has a measured sibling. Battery card B4 (run `20260719-002208-bd`) recorded an oracle with
`oracle_coverage 0/6` — a grader that graded nothing, with failures charged to the coder until
`oracle_unfit` was added. That is grader *inadequacy*, and it was loud. Same-family bar-setting is its
quieter twin: it moves the number the other way, producing a too-easy exam, which raises no alarm at all.

**3. VLM design critique — live, bounded.** Qwen3-VL-8B grading screenshots of Qwen3-coder's apps; same
family. Well-mitigated (deterministic layout-lint findings injected into the prompt, three lenses under a
*skeptical union* so any lens flagging work wins, and visual criteria can never be marked verified). The
one leak: a satisfied review reclasses a run STALLED → PARKED-HONEST, so the STALLED/PARKED split in
battery statistics is not model-free. It can never mint GREEN.

### 3.4 There is no independent-judge mitigation anywhere — and a correction

The decisive question was whether the guest-oracle cross-check provides independent verification. **It does
not, and it was never meant to.** `guest_oracle.py:339` compares *the same oracle bytes, run by pytest in
both places*, with runner versions deliberately pinned identical (un-pinning them is described in-source as
"a fake-DIVERGENCE manufacturer"). No second model. No model at all, on either side. Its real purpose
(`guest_oracle.py:5`) is an **isolation certificate** proving model-written test code cannot exfiltrate,
because the Alpine guest has no network stack. As an exfiltration control it is well built. As a bias
cross-check it never was one.

> **Correction, recorded deliberately.** The audit reporting this also stated the guest oracle was
> transport-dormant and "can never fire today," with high stated confidence. **That is wrong**, and it was
> caught by checking the claim against live run data rather than accepting it. The transport is registered
> (`swap_ops.py:2405`), `default.toml:461` records the control LIVE since the 2026-07-08 supervised
> ceremony, and last night's certificate contains a real guest pytest run. The auditor had been misled by a
> stale in-code comment (`swap_ops.py:3053-3056`) asserting dormancy and a "double lock" that does not
> exist — now **ticket #999**. Note the direction this cuts: the cross-check *does* fire, and it *does*
> report agreement — and that agreement is still not evidence of judge independence. A reader who saw
> `guest_agreement: agree` on every card and inferred "two graders concur" would be wrong twice over.

**So: no independent-judge mitigation exists anywhere in either repository.**

### 3.5 The honest limit

This audit establishes where the structure *permits* inflation. **It does not measure any.** Nothing here
is evidence that inflation has occurred, and that distinction should survive into any summary of this work.

Measuring it would require an out-of-family grader. The privacy mandate rules out a cloud judge
(`evals/README.md:86`), so it would mean provisioning a non-Qwen **local** model purely as a measurement
instrument. That is a capability decision for the Lead Architect — see §8.

---

## 4. Our own ranking paths — position-bias exposure

**Headline: the severe case is architecturally absent. The exposure that remains is real, mild, and
cheap to close.**

§2.2 predicted where this would hurt: ranking several candidates that are near-equal in quality. We have
exactly that shape — best-of-N coder sampling, where several attempts are generated from the same model on
the same task. That is the textbook worst case.

**It is not exposed, because no model ever ranks them.** Candidates are never co-presented: each is
generated from its own separate prompt (`fleet-lib.ps1:1813` appends an "INDEPENDENT ATTEMPT k OF n"
suffix per candidate), so there is no slot for a judge to favour. Selection is integer arithmetic over
deterministic gate signals (`fleet-lib.ps1:1832` — verify pass +600, test pass +200, timeout −2000,
secret-blocked −100000), and those signals come from `dotnet build` / `pytest` / `npm test` exit codes.
Test-pass counting and exit codes carry no judge bias at all. The downstream consumer merely counts log
lines and is documented as never touching verdict or attribution (`swap_driver.py:676-678, :738`).

This is worth stating plainly because it was not luck. The one place the literature says a ranking is
least trustworthy is the one place this project built the ranking deterministically.

One honest caveat: `Select-BestCandidateIndex` (`fleet-lib.ps1:1860`) compares with strictly-greater, so an
exact tie keeps the earliest candidate. That is a first-slot preference — but an arithmetic, reproducible
one, deliberately chosen for determinism and cheapest-attempt. It is not a model preferring slot one.

### 4.1 Where model-prose ordering is genuinely uncontrolled

| Path | What is ordered | Order control | Blast radius |
|---|---|---|---|
| Oracle coverage-map (`oracle_qa.py:703-711`) | Criteria list + test-name list, co-presented for matching | **None** — one list in spec order, the other in AST source order (incidental file layout) | Scorecard number + BUILD-vs-HARNESS attribution on a parked job |
| Plan revision (`revise.py:160`) | Numbered plan tasks the model revises against | None — existing plan order | **Highest** — the revised plan is what gets built (mitigated by operator confirmation + range validation) |
| Tool selection (`tools.py:795`) | All tool specs in one block, model picks one | Fixed insertion order, **deliberately** — byte-stability is a stated reproducibility property (`:803-804`) | Answer quality / wrong tool. **Not** a security exposure: a biased pick cannot open a door policy denies |
| Multivote critique (`critique.py:316`) | Nothing pairwise — separate calls, union-aggregated (`:356`) | Order-independent by construction | Advisory only; forbidden from marking anything verified |

The coverage-map path is the most exposed, and even it is capped by two existing mitigations: the grammar
schema pre-fills every criterion id as a required key, so a late-listed criterion cannot be silently
dropped, and `verify_traceability` (`:731`) re-checks each declaration against the real AST. Bias could
produce a wrong *pairing*, not a silent omission. Its trip condition needs total mismapping, not a nudge.

Confirmed deterministic and unexposed: `evals/rubric.py` (states explicitly "no LLM judge"; scoring is
containment/absence/format/length checks), `oracle_quality.py` soundness/sensitivity (pass/fail against
frozen references and mutants), `plan_graph.py`, `doom_check.py`, `static_pregate.py`, and `acceptance.py`'s
clarify fork (keyed on a frozenset, deliberately order-independent).

### 4.2 The real gap: nothing would catch it

No test anywhere runs a model comparison twice with the order swapped. A search of `shared/tests/`,
`tests/`, and the `verify-*.ps1` scripts for shuffle/permutation/reversal patterns found exactly one
order-independence test — `test_acceptance.py:2318` — and it covers a deterministic frozenset map with no
model involved. The best-of-N verifiers unit-test the selector policy without a model, which is correct for
a deterministic selector but structurally cannot catch prose ordering.

So the honest position is: **order is uncontrolled and untested, and the effect has not been measured.**
This audit establishes exposure, not presence. Only a swapped-order run against the live 14B would settle
whether the bias actually bites here.

### 4.3 Recommended control

Add a swap-and-compare probe to the oracle-QA suite: call `request_coverage_map` twice against a scripted
generator — once with criteria and test names in source order, once with **both reversed** — and assert the
covered-id set from `verify_traceability` is identical. No live model is needed; the injection seam already
exists at `oracle_qa.py:692-693`. One test converts "we assume order doesn't matter" into a gate-enforced
claim, and the same shape generalises to `revise.py`.

**Explicitly rejected: randomising the live candidate order.** That trades a measurable bias for
run-to-run nondeterminism in a subsystem whose design premise is deterministic reproducibility, and it
would break the byte-stability property `tools.py:803-804` deliberately holds. The probe measures the bias
without paying that price.

---

## 5. Retrieval quality — the gap is real, and it is already hiding a measured defect

**Answer to the central question: No. Nothing in this repository would catch retrieval getting worse while
answers still read fluently.**

That was searched for properly before being concluded — all eval suites, goldens, fixtures and baselines;
`tests/`, `tests/security/`, `tests/integration/`, `shared/tests/`, the AO's own tests; and a repo-wide
sweep for the whole metric vocabulary (faithfulness, groundedness, context precision/recall, answer
relevancy, recall@, nDCG, MRR, hallucination).

### 5.1 Why the existing suites cannot see it

`EncryptedKnowledgeBank.retrieve` **is never called anywhere under `evals/`.** Fourteen of the forty
`answer_quality` cases carry a grounded context, and in every one the chunks are hand-written into the
golden JSON and pushed through the real `ContextManager`. The suite faithfully measures what the model does
*with* a context. It has no opinion on how that context was chosen.

Two further limits worth naming plainly:

- The 19 model-tier cases are **skipped unless `--include-hardware`**, so a standing-gate run executes
  **zero live-model cases** (`baselines/answer_quality.json`: `evaluated: 21, skipped_hardware: 19`).
- The retrieval-adjacent unit tests prove each limb *functions*, not that ranking is *good* — 2–3 document
  smoke tests. One of them, `test_scores_descending` (`test_knowledge_bank.py:550`), asserts the returned
  scores are sorted, which is true by construction of the `sorted()` at `knowledge_bank.py:2384`. It
  cannot fail on a quality regression.

Every one of these would still pass if fusion started returning the 4th-best chunks. The answers would read
exactly as fluently, and `answer_quality` would still score 21/21, because its context is hardcoded.

### 5.2 This is not hypothetical — the blind spot is currently hiding a live defect

On 2026-07-10 a one-off script measured the real retrieval path end-to-end and found a genuine regression.
Verified today against `PERFORMANCE_LOG.md` and current `main`:

| Limb | R@4 | MRR |
|---|---|---|
| vector-only | **1.000** | **0.979** |
| bm25-only | 0.917 | 0.875 |
| **hybrid RRF (production)** | **0.917** | **0.921** |

**The production fusion ranks below the single limb it contains.** Named mechanism: `_fts_match_expr`
(`knowledge_bank.py:489`) OR-joins every query token including stopwords, so BM25 contributes a common-word
noise set with no gold-token match, and reciprocal-rank fusion then buries a correct vector rank-1 hit.
Query q02 falls from vector rank 1 to RRF rank **18**; q07 from rank 1 to rank **22**. Both drop out of the
production top-4.

**The root cause is unchanged in source ten days later** — `_fts_match_expr` still does
`re.findall(r"\w+", query)` and OR-joins the lot, stopwords included.

The measurement was recorded correctly and escalated correctly as an LA decision. It then landed on a
ticket in a *Drafts* project at priority 1, was never closed, and the decision was never put in front of
anyone. Re-raised today as a comment on #795. This is the shape `durability requires distribution` warns
about: written down is not the same as queued to the next actor.

So the honest framing of this gap is not "we might be missing something." It is: **the project already
proved it can measure this, the measurement immediately found a real defect on the shipping path, and the
measurement was never converted into a control.**

### 5.3 What a suite would look like — and how far determinism actually goes

Mirror `oracle_quality`, which already solves the two hard parts (a deterministic check engine in its own
module, plus a sensitivity axis): `evals/suites/retrieval_quality.py` + `evals/grounding_checks.py` +
fixtures/golden/baseline in the established layout.

Deliberately **not** an extension of `rubric.py`: that check allowlist is exhaustive by design and
gate-pinned, and grounding needs a second input (the retrieved passages) that `score_answer(answer, checks)`
has no slot for. Extending it would weaken a lock to add a feature.

**Four of the five things worth measuring need no judge at all:**

| Category | Method | Judge? |
|---|---|---|
| `context_recall` | Seed the real bank, run the real `retrieve()`, check the gold chunk is in top-k — the #795 math promoted to a suite | **No** |
| `context_precision` | Fraction of returned chunks gold-labelled for that query | **No** |
| `fusion_sanity` | Assert RRF rank ≤ min(vector rank, bm25 rank) + tolerance — the q02/q07 burial class, as a permanent lock | **No** |
| `groundedness` | Every claim-bearing sentence supported by a retrieved passage | **Mostly no** |
| `answer_relevancy` | Does the answer address the question | **Yes** — omit |

Deterministic groundedness goes further here than the RAGAS framing implies, because this corpus is
unusually favourable to it. The knowledge bank holds personal notes — hostnames, addresses, part numbers,
dates, proper nouns. Extracting every number, date, quoted string, address and capitalised multi-word token
from the answer and requiring it to appear verbatim in the retrieved passages catches an invented IP or a
fabricated release date instantly, with pure regex. A semantic tier can go further by reusing the *same*
encoder the bank already uses — architecturally identical to the cosine leakage detector already shipping
(`context_manager.py:103-144`), pointed inward rather than a new mechanism.

Where determinism genuinely runs out, stated precisely rather than generously: **paraphrase-heavy support**
("the release slipped to spring" is faithful to a date it shares no tokens with), and inference-shaped
support derived from two facts. Cosine catches some; it will not catch all. That is a real ceiling.

**Recommendation: do not import a model judge, even for those.** Two reasons, the second stronger. The
baseline machinery treats a previously-passing case that now fails as a regression, so a nondeterministic
scorer would manufacture false regressions — and the predictable response is to loosen the gate, which
costs more than the coverage buys. More importantly: #855 and #946 are this project's standing evidence
that *model prose asserting its own success* is the failure class being defended against. Importing a model
judge to detect retrieval failure would re-import that exact class into the control meant to detect it. If
a judge tier is ever wanted it belongs behind `--include-hardware`, reported as advisory **alongside** the
deterministic verdict, never as the verdict.

**The part most likely to be skipped, which should not be.** `oracle_quality`'s best idea is its
sensitivity axis — a weak oracle passes broken code, "the silent direction." That maps onto
security-by-design principle 12: every control ships with a test proving it fails when the lock is off.
Concretely, degrade retrieval on purpose (force `k=1`, disable the vector limb — the
`_embed_model_mismatch` path at `knowledge_bank.py:2343` already provides that degraded state for free,
shuffle the fusion, substitute an off-topic chunk) and assert the score drops below threshold. Without it
you cannot distinguish "grounded" from "the check can't see anything."

### 5.4 Fixtures mostly exist

`docs/research/fixtures/knowledge_retrieval_ab.json` — 35 labelled documents, 24 gold-labelled queries,
probe-class tagged, already driven end-to-end against the real bank. Three additions needed: a gold
supporting-span per query (it currently labels which *document* is right, not what a faithful answer looks
like); adversarial absent-gold queries so abstention is measured against the *real* retriever returning
nothing; and **multi-chunk documents** — every fixture doc is deliberately sized under `CHUNK_CHARS`, so as
it stands the chunker is entirely unexercised and a chunking regression would be invisible.

### 5.5 Honest calibration

This is not a project without evaluation discipline. The harness is well built, the honesty notes in the
suite docstrings are unusually candid, and the deterministic posture is a deliberate strength rather than
an oversight. This is one specific blind spot in an otherwise mature layer — and roughly 80% of it closes
without departing from the deterministic idiom at all.

**Undetermined:** whether the NPU embedder is bit-reproducible run to run. The #795 run was served on CPU
due to live-AO contention, and the log calls device "a latency knob, not a numerics knob" — but no
measurement establishes that cosine scores are identical across NPU and CPU. If they are not, any
cosine-threshold check must be hardware-tiered with a margin and never run in CI. Worth measuring before
the semantic tier is designed around it.

---

## 6. The four frameworks, judged from source

Every judgement below rests on LICENSE files, dependency manifests, and telemetry source fetched raw from
GitHub and read verbatim — not on READMEs or docs sites. The full artifact list is in §6.4.

**The headline is uncomfortable for the article: its most warmly recommended tool is the one we must
refuse outright, and the reason is invisible from its documentation.**

| | License | Phones home | Local endpoint | Weight | Verdict |
|---|---|---|---|---|---|
| **DeepEval** | Apache-2.0 | **Yes — opt-out, at module import.** Sentry + PostHog + public-IP lookup + global exception hook | Yes | Heavy; telemetry clients are **core deps** | **Reject outright** |
| **RAGAS** | Apache-2.0 | **Yes — opt-out.** Posts to `t.explodinggradients.com`, persistent on-disk UUID | Yes | Heavy; whole LangChain stack | **Reject; reimplement 2 algorithms** |
| **Promptfoo** | MIT | **Yes — opt-out.** PostHog, an email-bearing post, an update check, and **red-team remote generation on by default** | Yes | Very heavy (Node) | **Reject; extract one corpus** |
| **lm-eval-harness** | MIT | **None found** (caveat §6.5) | **Yes, no API key required** | Light; no torch in core | **Only viable candidate** |

**All three of DeepEval, RAGAS, and Promptfoo are opt-OUT. None asks. There is no opt-in tool in this set.**

### 6.1 Why DeepEval is disqualifying, not merely untidy

The article recommends DeepEval as the CI quality gate — the exact role we would plausibly want. Reading
the source instead of the README:

Merely **importing** the package (`deepeval/telemetry.py:113-126`, executed at import time, guarded only by
an unset-means-enabled opt-out at `:37-38`) initialises a Sentry client and a PostHog client, and calls
`requests.get("https://api.ipify.org")` to resolve the machine's public IP. Every event is then stamped
with `user.public_ip`.

Worse, it installs a process-global `sys.excepthook` that calls `sentry_sdk.capture_exception` on **every
uncaught exception in the process**.

That last one is the disqualifier. Exception text routinely carries file paths, argument values, and prompt
fragments. On a machine holding the operator's private data, this ships unchosen content off-box by
default, and the resolved public IP means "anonymous" is not an accurate description of the collection.
This fails our stated rule for dev-side use, never mind runtime — and none of it is visible from the
documentation that recommends the tool.

### 6.2 Promptfoo: the advertised corpus is mostly not in the repository

The article's most appealing offer was Promptfoo's large library of adversarial attack vectors as a
ready-made red-team set for testing the Policy Agent. **That claim is substantially false as a statement
about local content.** The named corpora — HarmBench, BeaverTails, Aegis, ToxicChat, UnsafeBench, VLGuard,
Pliny/L1B3RT4S — are not shipped. Each plugin is a small fetcher that pulls its data from
`raw.githubusercontent.com` or HuggingFace at runtime. Installing it and running a red-team produces a
machine that reaches out to GitHub, HuggingFace, and `api.promptfoo.app` before generating a single attack.
Red-team remote generation is on by default, and most strategies **hard-fail** if you disable it.

One genuinely useful asset does ship locally: `src/redteam/strategies/promptInjections/data.ts`, 232 KB of
flat prompt-injection templates with a `__PROMPT__` placeholder — at least 67 entries, likely ~70–75 (exact
count undetermined; some span lines). Usage is a plain string substitution; there is no runtime magic to
reproduce. License position is clean and doubly so: Promptfoo is MIT, and the corpus's own README records
that the jailbreaks derive from Protect AI's `llm-guard` at a pinned commit, reproducing that MIT notice in
full. The strings can be lifted as static fixtures with no install, no Node, and no network — carrying both
notices.

### 6.3 RAGAS: reject the framework, take the algorithms

Same opt-out defect, materially quieter in scope (event metadata only, no exception capture, no IP
resolution), but still unasked, still with a persistent on-disk identifier, and its `@silent` decorator
swallows failures so it fails without telling you. Adoption would pull the entire LangChain ecosystem plus
`datasets` onto the dev box in exchange for roughly thirty lines of real algorithm.

Both metrics are prompts plus arithmetic, and neither uses embeddings in its default form:

- **Faithfulness** = two model calls (break the answer into atomic statements with no pronouns; then judge
  each statement 1/0 for direct inferability from the retrieved context), scored as
  `faithful_statements / num_statements`. Returns `NaN` rather than 0 when no statements are generated —
  a detail worth copying, since 0 and "unmeasurable" are different facts.
- **Context precision** = one verdict per retrieved chunk, then rank-weighted average precision over the
  verdicts **in retrieval order**, so it rewards putting useful chunks first.

Both are intrinsically judge-metrics — that is a property of the metric, not of RAGAS — which points them
at our own local 14B. Reimplementing natively is well under a day and pulls in zero dependencies.

Explicitly not to be copied: the `FaithfulnesswithHHEM` variant, which loads a cross-encoder with
`trust_remote_code=True` — that executes arbitrary downloaded code.

### 6.4 Artifacts actually read

DeepEval: `pyproject.toml`, `LICENSE.md`, `deepeval/telemetry.py`, `constants.py`, `cli/main.py`.
RAGAS: `pyproject.toml`, `LICENSE`, `src/ragas/_analytics.py`, `_faithfulness.py`, `_context_precision.py`,
`llms/base.py`.
Promptfoo: `package.json`, `LICENSE`, `src/constants.ts`, `telemetry.ts`, `updates.ts`,
`redteam/remoteGeneration.ts`, `redteam/plugins/` listing, `harmbench.ts`, `pliny.ts`,
`promptInjections/{README.md,data.ts,index.ts}`.
lm-eval: `pyproject.toml`, `LICENSE.md`, `lm_eval/models/openai_completions.py`, plus repo-wide code search
for telemetry vendors (posthog 0, sentry 0, mixpanel 0, telemetry 0 hits).

### 6.5 Honest limits

- **lm-eval's "no telemetry" is the weakest claim here.** It rests on the manifest plus code search, not a
  line-by-line read. A negative search result is weaker evidence than a positive one. Grepping the
  installed package on disk would convert inference to verification — a two-minute check, required before
  any adoption.
- lm-eval does reach the network at runtime via HuggingFace `datasets` to fetch task data. That is dataset
  fetching, not telemetry — a different risk class, but still egress from the dev box. Whether the offline
  environment variables fully seal it is **undetermined**.
- For DeepEval and RAGAS the telemetry modules were read but not every call site. Mechanism, endpoints, and
  defaults are established; an exhaustive event inventory is not. Neither verdict turns on that.
- **No evidence was found in any of the four that prompt or response content is transmitted in telemetry
  payloads.** Collected fields are versions, platform, counts, metric names, and identifiers. DeepEval's
  exception capture is the one path where private content could plausibly escape, and it is why that tool
  rates worst.

---

## 7. Our complete measurement surface, mapped

Using §1's three categories.

### (A) Model benchmarking — effectively absent, deliberately

No MMLU/GSM8K-style harness exists in either repository. `docs/performance/` and `PERFORMANCE_LOG.md`
benchmark the *substrate* — tokens/sec, time-to-first-token, load time, RAM — not the intelligence.
`evals/README.md:113-115` says so outright.

One consequence worth naming: the 35B-A3B consolidation is blocked partly on a "clean quality-parity
re-run" because the project has no standardised instrument for "is model X better than Qwen3-14B" other
than re-running its own application evals.

### (B) Application evaluation — strong, and larger than it looks

Seven suites, **316 golden cases**, with committed baselines carrying `git_sha` provenance and genuinely
toothy regression semantics (exit 1 on a baseline-pass case now failing, on a new failing case absent from
baseline, and on a baselined case that vanished; exit 2 on a malformed baseline, because "an uncomparable
run is never a silent success").

The eval harness is **not** a separate CI step — 185 integration tests wire the deterministic slice into
the standing pytest gate, so `evals.run` executes on every gate run.

Notable design quality, worth recording because it is unusual: `governance` drives the *real* policy
checker and real `ContextManager`; `answer_quality` derives its leak-detection needles at runtime from the
imported real system prompt rather than copying them, so a prompt change moves the check with it;
`tool_calling` treats a golden case asking to dispatch a non-SAFE tool as a harness error rather than
executing it; `oracle_quality` is the only bidirectional grading of a grader in the project — *soundness*
(must pass a known-good reference) and *sensitivity* (must fail a deliberately broken mutant).

### (C) Production monitoring — one strong instrument, one total absence

The **nightly battery** is the project's real production-monitoring instrument. But it measures the
**pipeline as a whole and is architecturally incapable of isolating the model** — its unit is a job, and
model quality is one of four possible *attributions* (PLAN / BUILD / VERIFY / HARNESS), never a measured
quantity.

**Nothing watches the assistant the operator actually uses.** The only telemetry in the AO source tree is
a generated-token counter for throughput. No answer-quality logging, no response sampling, no rubric
applied to live turns, no drift detection, no operator feedback capture. The asymmetry is exact: the one
surface with live quality instrumentation is the coordinator's shadow mode — a subsystem whose output
reaches nobody by design — while the surface used every day has none.

### 7.1 The strongest thing here

The battery's **honesty machinery** — not because it measures the model well, but because it is the only
instrument built to resist its own optimism, structurally rather than aspirationally:

- The verdict set separates a *valid failure* (PARKED-HONEST, banks) from an *invalid run* (STALLED,
  blocks), so a crashed night cannot be laundered into a data point. That distinction is the sharpest
  design decision in the whole measurement surface.
- FALSE-DONE is a first-class verdict with a hard gate at zero: claiming done without evidence is treated
  as categorically worse than any quality miss.
- Advisory instruments are **advisory-locked in code** — the classifier snapshots verdict/attribution per
  card and, if a future edit ever mutates them, restores the original and records the breach. Exactly one
  instrument has verdict authority, by explicit LA ratification, documented in an ADR.
- The classifier has a **positive control**: nine hand-classified instances it must reproduce.
- `UNCLASSIFIED` is a published metric — the instrument reports its own blindness rate.

The real argument for it is behavioural: it found three faults **in itself** in one morning (#987, #991,
#989), and the response was to put the battery into instrument-repair mode and hold the build rather than
keep banking numbers. That is what a working measurement culture looks like.

### 7.2 The thinnest — and a defect inside it

**Model-quality measurement of the assistant's own answers is thin in four independent ways**, and
`answer_quality` is the only instrument aimed at what the operator experiences.

1. **A standing-gate run executes zero live-model cases.** Across all seven suites, 41 of 316 golden cases
   are model-in-the-loop, and all 41 are skipped without `--include-hardware`. So essentially 100% of the
   8,637-test gate is conventional software testing. This is by design (`evals/README.md:8-10`) — but the
   model-quality half of that design only fires at a ceremony.
2. **That ceremony has not run since 2026-07-07** — thirteen days stale, N=1, variance never measured.
3. **The hardware tier has no teeth at all.** See below.
4. The rubric's ceiling is acknowledged in its own docs: it measures containment, absence, format,
   grounding fidelity and length — not whether an answer is genuinely helpful.

**The defect (verified independently at source, now ticket #1000).** `evals/baseline.py:149-162` branches:
`base_status is None` → regression; `base_status == "pass"` → regression; **else → known_failures**. A case
whose baseline is `skipped_hardware` and which then *fails on hardware* is neither, so it lands in the
`else` and is recorded as a known failure. The run exits 0.

`baselines/answer_quality.json` records 21 `pass` and 19 `skipped_hardware`. **So all 19 model cases can
fail on hardware indefinitely at exit 0.**

This already happened, and it took the security-relevant cases with it. `PERFORMANCE_LOG.md:2214-2218`,
the 2026-07-07 run: *"35/40 passed (87.5%), 0 errors, 0 regressions (exit 0). The 5 fails are the
baseline-tracked known deficiencies: `aq-fact-mod-02`, `aq-inj-mod-01/02/03` (injection-resistance — the
security-relevant cluster), `aq-unc-mod-02`."*

**Three of four injection-resistance cases failed, and the harness reported no regression.** And the
narrative is subtly wrong in a way that made it read as fine: those cases were not "baseline-tracked known
deficiencies" — the baseline had no recorded expectation for them at all. They were absorbed by a branch
fall-through. The log reads "we knew about these"; the mechanism was "the comparison had nothing to compare
against and defaulted to benign."

By contrast `pa_classification`'s baseline *was* generated with `--include-hardware`, so its 13 model cases
are recorded `pass` and genuinely exit 1 on regression. **Same harness, opposite teeth, purely as an
artifact of how each baseline happened to be generated.**

> **A trap worth flagging.** `tests/pa_quality_benchmark/` looks like the project's most metric-rich
> quality instrument — precision, recall, F1, false-allow and false-deny rates, with thresholds. It builds
> its classifier with `mock_gpu_label="ALLOW"`, and the `@hardware` "real GPU benchmark" uses the same
> mock, its own comment conceding "the real GPU test is a stub here." It measures the **rule engine**,
> never the model — and it sits outside the standing-gate selection entirely.

### 7.3 Genuinely absent

Two total absences: **live observability of the running assistant** (§7 category C), and **retrieval
quality** (§5). Both are unmeasured in any form.

### 7.4 A second dead instrument (ticket #1001)

The battery's night-over-night trend — the one mechanism explicitly built to be longitudinal, existing to
produce the program KPI line — has **never produced a delta.** `load_history` globs
`Path(out_dir).parent / "*/battery-summary.json"`, but the runner passes `--out <night>/scorecards`, so it
searches for siblings *inside a single night*. Eleven consecutive nights each report `trend.nights = 1`.

What makes this instructive: the code correctly refuses to fabricate a zero for a first night, and defends
that in its docstring as honesty. The honesty is real. But a permanently-first night looks exactly like a
correctly-handled first night, so the fault was invisible. This is the second instrument found today that
was reporting nothing while looking healthy — the first being #987's admission gate, dead since 07-06. A
third instance triggers the structural-control rule.

---

## 8. Recommendations

### 8.1 Mine — decided, ticketed, no LA input needed

| # | Action | Status |
|---|---|---|
| R1 | **Fix the baseline branch fall-through** so a hardware-tier case that fails cannot be absorbed into `known_failures`. Only affects `--include-hardware` runs, so it cannot destabilise the standing gate. | **#1000**, priority 4 |
| R2 | **Add a `retrieval_quality` eval suite** mirroring `oracle_quality`'s shape — `context_recall`, `context_precision`, `fusion_sanity`, deterministic `groundedness`, plus a sensitivity axis that degrades retrieval on purpose and asserts the score drops. Fixtures 80% exist. | **#1002** |
| R3 | **Fix the dead battery trend** (glob depth) with a regression lock asserting N synthetic nights yield `nights == N`; refresh the stale `governance` baseline. | **#1001** |
| R4 | **Correct the false-protection comment** in `swap_ops.py` to point at `default.toml` as the authority rather than restating wiring. | **#999** |
| R5 | **Add a swap-and-compare order probe** to the oracle-QA suite — call the coverage map twice with both lists reversed, assert an identical covered-id set. The injection seam already exists; no live model needed. | **#1003** |
| R6 | **Extract Promptfoo's prompt-injection corpus** (232 KB, ~70 templates, MIT, no install, no network) as static red-team fixtures against the Policy Agent, carrying both required notices. | **#1004** |

### 8.2 The Lead Architect's — three decisions

**D1. The retrieval fusion (#795).** Production hybrid ranking measures below plain vector ranking on our
own corpus, with two queries falling out of what the assistant reads. This affects answer quality, so it is
his call. **Recommendation: filter stopwords in the keyword limb** — low-risk, addresses the named
mechanism directly, and does not churn architecture on a 35-document corpus. Alternatives: leave it and
re-measure at larger corpus scale before the episodic tier; or go vector-only for now. *The regression lock
is not part of this decision and proceeds regardless.*

**D2. Whether to provision a non-Qwen local model purely as a measurement instrument.** This is a
capability decision. Every model in the fleet shares the `qwen3` family, so **no independent grader exists
anywhere**, and the perplexity mechanism (§2.1) means same-family grading is exposed by mechanism rather
than coincidence. The privacy mandate rules out a cloud judge, so measuring our own judge bias at all
requires a local out-of-family model. **Recommendation: not yet.** The exposure is real but currently
armed-not-firing, and the deterministic layer is doing the work. Revisit if the green-quality jury is ever
wired — at that point the panel would need genuinely different weights, not different seeds.

**D3. Scheduling an answer-quality hardware ceremony.** The last live measurement of the assistant's own
answers was 2026-07-07 — thirteen days ago, N=1, variance never measured — and it left three
injection-resistance failures whose current state is unknown. **Recommendation: run it once #1000 lands**,
and regenerate the baseline with `--include-hardware` in the same window so those 19 cases finally carry
real recorded statuses. Sequencing matters: baselining before the fix would freeze today's failures in as
"known."

### 8.3 Rejected, argued

- **Adopt DeepEval** — rejected outright. Importing it opens Sentry and PostHog clients, resolves the
  machine's public IP, and installs a process-global exception hook shipping every uncaught exception
  off-box. On a machine holding the operator's private data that is disqualifying for dev-side use, not
  merely for runtime.
- **Adopt RAGAS** — rejected. Opt-out telemetry with a persistent on-disk identifier, failing silently by
  design, and it would pull the entire LangChain stack onto the dev box for ~30 lines of real algorithm.
  Reimplement the two metrics natively *if* a judge tier is ever wanted.
- **Adopt Promptfoo** — rejected as a tool. Three independent network behaviours on by default, including
  red-team generation that posts to their API with most strategies hard-failing when disabled. Take the
  one local corpus (R6) and install nothing.
- **Adopt lm-evaluation-harness** — not now. It is the only one that clears the bar (MIT, light core, no
  telemetry found, keyless local endpoint), but its value to us is incremental. If it is ever adopted, grep
  the installed package on disk first — the no-telemetry finding rests on code search, and a negative
  search result is weaker evidence than a positive one.
- **Import a model judge into the eval layer** — rejected. The baseline machinery treats a
  previously-passing case that now fails as a regression, so a nondeterministic scorer manufactures false
  regressions, and the predictable response is to loosen the gate. More importantly, #855 and #946 are this
  project's standing evidence that *model prose asserting its own success* is the failure class being
  defended against; importing a judge to detect failure would re-import that class into the detector.
- **Randomise candidate order to mitigate position bias** — rejected. It trades a measurable bias for
  run-to-run nondeterminism in subsystems whose design premise is deterministic reproducibility. The
  swap-and-compare probe (R5) measures the bias without paying that price.

---

## 9. What this exercise says about method

Four times in this single day, reading the artifact reversed what the documentation implied — and every
time, the documentation made the riskier option look safer:

1. A blog post and a source summary both stated the position-bias/quality-gap relationship **backwards**.
   Written from the summaries, this document's central finding would have been inverted (§2.2).
2. DeepEval's documentation recommends it as a CI quality gate; its source ships private data off-machine
   by default (§6.1).
3. Promptfoo's advertised adversarial corpus is largely **not in the package** — fetched from third-party
   hosts at runtime (§6.2).
4. A stale in-code comment convinced an expert reader that a live isolation control was dormant, with
   stated high confidence (§3.4, #999).

The fourth is the one to keep. It was not a vendor overselling — it was **our own comment**, misleading
**our own audit**, today. The rule that documentation is not evidence is usually aimed outward at third
parties. It applies with equal force to what we write about ourselves, and a stale comment is the most
credible false witness in any codebase, because nobody suspects it.
