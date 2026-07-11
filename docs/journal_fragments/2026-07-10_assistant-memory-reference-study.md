### 2026-07-10 — Reading the neighbours' houses before building the second floor

*Plain summary: #770 M2/M3 research-and-draft session — an external-design study
(`docs/research/assistant_memory_reference_study_2026-07.md`, OpenClaw as primary
reference + the memory-plugin ecosystem + the salience/decay/poisoning literature)
and a phased M2/M3 iteration plan
(`docs/research/preference_memory_m2_m3_iteration_plan_2026-07.md`) whose eight LA
decisions (D-0..D-7) were settled in-chat the same day — three with modifications
(D-3 commitment upgrade, D-4 removal-semantics extension, D-5 local-14B override);
build tickets #792/#793/#796 (+optional #794/#795) filed. Documents and tickets
only — no runtime code.*

M1 shipped the preference tier yesterday; before M2 gets built I spent a session
reading how everyone else builds agent memory — OpenClaw first, because it is the
closest living analogue to what BlarAI's assistant wants to be: one operator, one
long-lived agent, memory meant to last years. The study's honest headline is
uncomfortable in a good way: most of what OpenClaw's memory design gets right,
BlarAI already built, sometimes in stronger form. Its files-are-authoritative,
index-is-derivative discipline is ADR-031's L2; its hybrid keyword+vector recall is
the RRF fusion #655 shipped in June; its bootstrap-budget truncation is the weaker
cousin of M1's write-door refusal. Independent convergence from a project with
enormously more users is validation worth recording — but the real finds were at
the edges. OpenClaw's "dreaming" consolidator gates promotions on score,
recall-frequency, and query-diversity before staging them for human review: that
three-gate shape, minus its fatal flaw, became the M3 miner's deterministic
pre-filter design. The fatal flaw is the flaw the whole 2026 field shares and the
security literature now measures: OpenClaw lets the agent edit its own memory, and
"Taming OpenClaw" names exactly that as the critical attack surface, with a CVSS
8.8 CVE chaining a crafted email through memory to cookie exfiltration. Every
surveyed system — Letta's blocks, the opencode plugin, Anthropic's memory tool,
mem0's extractor — puts a model hand on the memory pen somewhere. BlarAI is the
only design in the survey where the write path to injected memory structurally
does not exist for the model. P8 stopped looking like caution and started looking
like the differentiated position.

The literature pass paid for itself twice. First, it retired a ghost: MEMSAD, one
of five "un-fetched leads" the 2026-07-09 research appendix named, does not appear
to exist — no paper, no benchmark, under any query framing. The other four
(SAGE, FadeMem, A-MemGuard, SMSR) are real and now properly cited; the correction
is in the study so no future session builds on a hallucinated citation (the C8
discipline applied to our own research trail). Second, it handed M2 its red-team
suite nearly whole: MPBench's taxonomy — four write channels, six attack classes
split by signal strength, three objectives per case — with the one number that
settles an old argument: a commercial prompt-injection screen catches 84% of
strong-signal memory attacks and 42.5% of weak-signal ones. Classifiers cannot
close that gap; write-path structure can. The trade-off I took in the plan
follows from it: I recommended proposals stay *allowed* in untrusted-content
sessions (the stricter alternative — refusing them — kills capture in exactly the
knowledge-heavy sessions where corrections happen) with provenance flagged on the
card, accepting that the operator's judgment on a flagged card is the last line
against weak-signal nudges. That is a capability-vs-exposure call, so it goes to
the LA as D-1 with the alternatives on the record, not as a fait accompli — as do
seven more, including whether an operator-stated expiry ("answer in French until
Friday") belongs in a tier whose no-decay rule was written about *system*
forgetting, not operator-stated scope.

The consolidation-risk literature sharpened M3 more than it changed it. SSGM's
three failure points and the Memory-Contagion finding — bias propagates through
memory *worse on smaller models* — are aimed straight at a 14B consolidator, so
the plan hardens the program's propose→verify→land into mechanics: the miner may
select and count evidence but never paraphrase it (P2 extended to Loop 2),
its output is report-only so drift has no store to accumulate in, and it runs
off the response path in a differently-privileged actor — which is, amusingly,
where Letta's 2026 sleep-time redesign independently arrived.

The decision session came the same day, and it earned its own paragraph. The LA
accepted five recommendations plainly and changed three in ways that each carry a
lesson-shaped fingerprint. D-3 he upgraded rather than accepted: I had filed the
meaning-based contradiction check as an optional follow-up; his read — "the
smarter version is really where the value is" — turned it into committed,
measured work (#796), a correct recalibration against mature-not-minimal that I
should not have needed. D-4 he accepted and then asked the better question than
the one I had posed: not *whether* preferences expire but *how one is actually
removed* — naming, from his own experience, the LLM habit of appending "stop
doing X" instead of deleting the line that says X. The store already forbids that
failure (delete is a status flip; the block re-renders from active rows only),
but his question exposed the door it re-enters through: the M2 propose flow,
where the model's natural move is to propose a new negating preference. The plan
now requires retraction proposals — the model proposes deleting or editing the
matching existing row — and the same removals-as-removals rule became a format
lint on M3's instruction deltas. The non-expert operator's gut finding the design
gap the specialist missed is lesson 193's shape, again. And D-5 he overrode with
the trade-off stated in both directions: the miner runs on the local 14B from day
one — locality governs over model strength — accepting the small-consolidator
drift risk the literature warns about, and paying for it properly: a verification
harness (schema-constrained output; evidence quotes that must byte-match their
source scorecards; the deterministic ruler filters; a golden mining test set) and
a dormant posture — candidates surface to no one until the quality gate measures
acceptable, or a better local model lands. I had recommended the stronger
dev-side model; his override is the more principled read of this project's
identity — BlarAI's loops should not depend on a cloud session to learn — and
the harness-plus-dormancy shape means the risk is bounded by mechanism, not hope.

**Next:** both kickoffs are decision-unblocked. /sprint-kickoff on #792 (M2)
after M1 day-2's WinUI passthrough step lands; #793 (M3) builds in agentic-setup
with the D-5 harness as its spine; #796 (meaning-based check feasibility) is a
measured study any quiet slot can take; #794/#795 remain backlog. The M2
governance ADR ratifies D-0..D-4 + the removal-semantics position with its
DECISION_REGISTER row.

*(Session artifacts: the two docs above (plan updated same-day with all eight
verdicts inline + new §2.2a); Vikunja #792/#793/#794/#795/#796 filed, decision
records #792 c.1587 + #793 c.1588, program comments on #770, session task #791.
No code, no commits to runtime surfaces; fragment written per the
parallel-session rule — a sibling build session was active on this tree.)*
