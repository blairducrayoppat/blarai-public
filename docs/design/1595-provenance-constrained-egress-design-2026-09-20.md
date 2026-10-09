---
title: "#1595 — provenance-constrained outbound search: research, options, recommendation"
status: proposal
area: security
ticket: "#1595"
---

# Constraining the outbound query by PROVENANCE

**Written 2026-09-20. The proposal: if a turn has ingested untrusted content — a document, a
web page, a prior search result — constrain the outbound search query for the rest of that
turn. It is Option 4 of the #1592 design, described there as "the strongest published
direction and the least mature".**

**The short version: DO NOT BUILD IT. The published treatment for this exact shape is user
confirmation, and we shipped user confirmation on every outbound query yesterday (#1594).
The mechanism is real and readable, but every measurement of it in our shape reports
over-blocking, and the one benchmark family it is usually validated on is structurally
unable to show that cost.**

---

## 1. What the mechanism actually is

CaMeL (Google DeepMind, `arXiv:2503.18813`) is the reference. Every value carries
`Capabilities(sources_set, readers_set)`. Sources **union** along the dependency graph;
readers **intersect**. Policies are Python functions returning Allowed/Denied, checked
before each tool call, default-deny.

**It is per-VALUE, not per-turn**, and that distinction is the whole argument below.

Our exact rule exists in its shipped code. `banking.py::send_money_policy` opens:

> `if not is_trusted(recipient): return Denied("The recipient does not come directly from
> the user.")`

And `slack.py::get_webpage_policy` gates outbound fetch on `is_public(url)`. Note the
asymmetry — CaMeL gates *recipients* on integrity (where did this come from) and *outbound
fetch* on confidentiality (who may read this). **Constraining a search query because the turn
is tainted is the integrity direction applied to an egress sink, and CaMeL does not do
that.**

Readable implementation: `github.com/google-research/camel-prompt-injection`, Apache-2.0.
Its own README: *"research artifact… The interpreter implementation likely contains bugs…
might not be fully secure… not a Google product."*

---

## 2. Nobody ships it, and the way they don't is informative

| vendor | what ships | provenance? |
|---|---|---|
| **Google** | classifiers, security-thought reinforcement, Safe-Browsing URL sanitization, user confirmation | No. CaMeL appears in DeepMind's own Gemini defence report (`2505.14534`) **as an open question**, not as deployed |
| **Google Chrome** | **Agent Origin Sets** — read-only vs read-writable origins, data flows only from the former to the latter | **The one real instance** — and Google states in the same post: *"We've initially implemented a simpler version of origin gating that just tracks the read-writeable set."* The read-set, the half that confines, was not in the first iteration |
| **Microsoft** | Prompt Shields, Spotlighting, static egress allowlists, Purview sensitivity labels | No integrity taint. Its SFI architecture page recommends information-flow control and **links to a Microsoft Research arXiv paper** where every sibling row links to a product |
| **OpenAI** | classifiers, adversarial training, static capability limits, Watch Mode | No. Watch Mode triggers on *which site*, not on what was read |
| **Meta** | LlamaFirewall | No — six classifiers; zero taint/provenance symbols in the source |
| **Anthropic** | transcript classifier, tool-result stripping | No, and the tradeoff is stated: *"There is a tradeoff in terms of provenance… We accept that cost for injection robustness"* |

**The open-source frameworks are the same story**, from source reads rather than docs:
`openai-agents-python` guardrails are boolean tripwire callbacks with no label (its two
`provenance` symbols are conversation bookkeeping and config-mount validation); crewAI's
URL tool has real SSRF defence and then says in its own code that the returned text *"is
still untrusted remote content flowing into an agent's context"* — i.e. it states that the
taint is NOT tracked; pydantic-ai and smolagents have neither. The closest thing in open
source is Invariant Labs' policy DSL, which expresses a source→sink relation between tool
CALLS (*"check all flows of `get_url` to `run_python`"*) — trace-level, not a label carried
on a value, and whether its arrow is true dataflow or ordering was not established.

**Every architecture paper recommends it. Every shipped product uses classifiers.** That gap
is the finding, not an accident of what we searched for.

**Coverage note, because absence of evidence is not evidence of absence.** The vendor sweep
listed Microsoft and OpenAI as unexamined; they were covered by two separate reads whose
findings are in the table above. What remains genuinely unexamined across all threads:
LangChain/LangGraph, LlamaIndex, AutoGen, Semantic Kernel, and whether Microsoft's
"tool chain analysis" — one undocumented sentence in the Copilot defence page — hides a
shipped taint-like mechanism. Treat those as unchecked ground, not as negative findings.

---

## 3. The cost, measured — and it splits on one axis

**The axis is data-dependence: can the action plan be fixed BEFORE untrusted content is
read?**

**Where it can, the cost is near zero.** CapScope derives an authority ceiling from trusted
input before repository contents are read: injection succeeded in 3/75 runs vs 33–47/75 for
ambient-authority baselines, at 68/75 vs 68–72/75 task completion. CaMeL's banking suite is
+0.0 pp for Claude 4 Sonnet.

**Where it cannot — which is our shape — every measurement reports over-blocking.**

- **ContainmentBench** (Qwen2.5-7B, 504 scenarios, 5 seeds, 17,640 rollouts): taint-only
  enforcement **false-positive block rate 0.6205**. Its §5.1 is titled *"Why Taint-Only
  Enforcement Over-Blocks"*. Their term: *"an agentic analogue of over-refusal."*
- **PACT's ablation**: a uniform per-argument USER-trust threshold — the closest published
  analogue to "only operator-typed tokens" — reaches **100% security at 14.4% utility**.
- **RTBAS** on exactly our shape (*"reading content from untrusted websites and performing
  actions based on that content"*): utility drops to **33% / 22%** against a ~70% mean. The
  authors' own conclusion: *"We consider such tasks inherently unsafe, necessitating user
  confirmation."*
- **AgentDyn**, 60 open-ended tasks: CaMeL scores **0.00 utility** across every model tested,
  versus 53.33 undefended. Over-defence, not bypass — the attack was the stock one.
- **FIDES**: the strict planner stops every attack and sits **up to 57.52 pp below** the
  bounded-declassification version.
- **CaMeL's own false-taint rate**, no attack present: **33.87%** of tasks require user
  confirmation in NORMAL mode, **53.23%** in STRICT — and STRICT is the mode that closes the
  side channels, while the shipped default is NORMAL.

**And the strongest evidence is a convergence nobody planned.** Three independent IFC systems
collapse on the SAME AgentDojo suite — Slack, the one where the agent reads web pages and acts
on what it read — each for the same stated reason, and none derived from the others:

| system | Slack, benign, defence on | note |
|---|---|---|
| **CaMeL** | denial rate **60% (NORMAL) / 80% (STRICT)** | its Slack policies *are* egress gates: *"get webpage policy: Only allow if url is public"*. Its own §6.2.2: *"in the Slack suite, policies deny execution much more often… because in many tasks data come from web pages (which are untrusted)"* |
| **FIDES** | **95.24 → 20.95** (gpt-4o, basic planner) | no attack present |
| **RTBAS** | **33% / 22%** against a ~70% mean | *"We consider such tasks inherently unsafe, necessitating user confirmation"* |

---

## 4. The four arguments that decide it

**1. It is the wrong question at the wrong granularity.** PACT states it directly:
*"Indirect prompt injection becomes dangerous not when untrusted content appears in context,
but when it determines an authority-bearing argument."* A turn-level flat policy cannot
express "the web page may fill the body, not the recipient". Our authority-bearing argument
is the query string itself — and it is already approved, byte for byte, by a human.

**2. Label creep is structural here, not incidental.** RTBAS: *"Every piece of data in the
LM's history could theoretically influence its next tool call, exacerbating the label creep
problem… This unrestricted propagation disrupts task execution by flagging benign tool calls
unnecessarily and overburdening users with constant confirmations."* CaMeL's
`get_all_sources` is a pure union with **no declassification operator**.

**And our codebase is worse than the general case.** Grounded provenance is stored per
SESSION, and `clear_grounded_context` has exactly one production caller, reached only by an
explicit unload or a fresh document attachment on a later turn. **Nothing clears taint at
turn end.** So "constrain the tainted turn" would in practice mean *constrain every search
for the remainder of the session after any web result, knowledge recall, or pasted text*.
The first search taints the session; the second is constrained; every subsequent one too.

**3. We would be re-litigating a decision that already has reasons on the record.** The
Layer-3 lock already refuses non-SAFE tools on untrusted content — and **egress tools are
carved out of it deliberately** (ADR-023 Am.4 rung 3). Two reasons are in the code comment:
a search's own `UNTRUSTED_WEB` result would otherwise lock the next search, and the refusal
text itself was poisoning the conversation because the model imitated its own refusal lines
(#726). Re-introducing a provenance condition on `web_search` re-introduces exactly the
condition that exemption was written to remove.

Concretely, these would regress:
`test_retrieval_tools.py::test_egress_tool_not_layer3_locked_under_untrusted_content`
(its docstring calls itself *"THE MARQUEE FIX (#723 rung 3)"*),
`test_two_searches_one_turn_share_one_fingerprint_n3`, and eval goldens `gov-l3-010` /
`gov-l3-011`, whose descriptions record that their verdict was deliberately changed at Am.4.

**4. The published treatment for our shape is the thing we already ship.** RTBAS concludes
that read-the-web-then-act tasks need *user confirmation*. **#1594 moved
`searches_per_fingerprint` to 1 on 2026-09-19: every outbound query already raises its own
Windows Hello prompt showing the exact bytes that will be sent.** A provenance signal cannot
make that approval more binding. It can only turn some approvals into refusals — and
refusal is where the entire measured cost lives.

---

## 5. Two caveats against my own recommendation

**The evidence base is weaker than its volume suggests.** The benchmark nearly everything
rests on cannot show the cost that matters: AgentDyn, verbatim — *"even in the most advanced
AgentDojo benchmark, only 6 of 97 tasks require dynamic planning. This allows defenses to
exploit a shortcut: they can appear secure by forcing the agent to strictly follow the
initial plan."* ~94% of its tasks are the fixed-plan regime where provenance constraint is
cheap. And **no defence in this class has faced an adaptive attacker** — the methodology that
made in-band defences look strong until twelve were broken at >90% success has not been run
against this out-of-band class.

**The benchmark cannot see the design we actually ship.** AgentDojo's Benign Utility metric
does detect over-blocking — it is how its own authors caught their PI detector at 41% — but
RTBAS records the gap that matters here, verbatim: *"In this benchmark, we do not model user
confirmations. Instead, any apparent unauthorized calls contrary to the information-flow policy
are skipped and unperformed."* **A defence that ASKS is scored as though it DENIED.** So the
literature systematically understates ask-don't-deny designs — which is the category BlarAI is
already in. Every over-block figure above is therefore an upper bound on what the same policy
would cost us, and the gap is unmeasured in either direction.

**Nobody has measured our exact rule.** Every figure above is per-value, per-argument or
per-tool-call. A turn-scoped binary on a *search query* is measured nowhere. The closest —
ContainmentBench's taint-only arm and PACT's per-argument USER threshold — are stricter in
form than the proposal, so they bound the cost from above rather than estimating it.

I am recommending against on the weight of consistent directional evidence, not on a
measured figure for this design. That is the honest standing of it.

---

## 6. What I recommend instead, and it is small

**Option A — DO NOTHING (recommended).** The disclosure control from #1592 and the per-query
fingerprint from #1594 already put a human in front of every outbound query with the exact
bytes rendered losslessly. That is the treatment the literature prescribes for this shape.
Adding a provenance refusal on top buys security only in the case where the operator would
have approved an exfiltrating query *having read it* — and pays for that with a measured
over-block rate that starts at 33% and rises with session length.

**Option B — PROVENANCE-AWARE DISCLOSURE, not constraint (worth building, cheap).** When the
turn has ingested untrusted content, say so *in the approval prompt*: "this search was
composed after reading a web page". No refusals, no false positives, no capability cost —
it makes an approval the operator is already giving better informed. This is PACT's insight
applied honestly: the question is whether untrusted content determines an authority-bearing
argument, and the operator is the one deciding that, so give them the fact.

The data exists and is one call away: `context_manager.untrusted_provenance_tiers(session_id)`
already returns the distinct tiers, and `_egress_query` and `session_id` are both live locals
at the same point in the tool loop.

**Option C — origin-set confinement (NOT NOW).** Chrome's read/write origin split is the
strongest published design. Google has not shipped the read half. Revisit if they do, or if
a reference implementation appears that is not a research artifact.

**A note on the one paper that recommends the opposite.** Back-Reveal argues domain
allowlisting is impractical for retrieval agents and recommends *"outbound egress control
restricting web-search/HTTP tools to vetted host allow-lists with per-tool quotas"* — and then
states it will *"leave their empirical study to future work"*. Its impracticality claims cite
vendor blogs rather than measurements. So the strongest published recommendation FOR egress
control in this shape carries no cost figure at all.

**Rejected: turn- or session-scoped refusal of `web_search` on untrusted content.** The
measured over-block rate, the per-session taint lifetime in this codebase, and the #726
regression it would re-open all point one way. **If it is ever reconsidered, the precondition
is a declassification operator** — some way for taint to be cleared or bounded — because
without one, label creep is not a tuning problem but the terminal state.

---

## 7. What this design does NOT claim

- It does not claim provenance tracking is a bad idea in general. Where the authority ceiling
  can be fixed before untrusted content is read, the measured cost is near zero, and that is a
  real and useful regime. It is not the regime a search tool lives in.
- It does not claim our current controls stop exfiltration. They ensure a human reads the
  exact bytes. A patient attacker with a cooperative model can still compose a query that
  looks reasonable — #1592 §7 says the same thing and cites Lampson.
- It does not claim the numbers above are commensurable. Five reported CaMeL utility figures
  come from five different instruments, AgentDojo versions, models and denominators, two of
  them reimplementations. They should not be averaged, and are not.
- Every load-bearing figure here was read from the primary artifact. Items the research could
  not verify from a primary source are marked as such in the research record and are not used
  above.
