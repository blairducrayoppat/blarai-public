### 2026-09-20 — A question had been waiting for him for months, and it was never his

*Plain summary: a runbook recorded an open decision for the Lead Architect — which of
two security policies should win when they collide. Settling it took reading the code:
they do not collide. Each one is correct for a different kind of request, the request
already says which kind it is, and the "collision" was one piece of wiring quietly
overwriting the other. No decision was needed from anyone.*

The ticket that sent me here was careful about this in advance. It said, in as many
words, that the framing on disk might be wrong and that settling it was step one — and
it attached the standing rule underneath: *technical questions are not his to answer.*

**What the runbook said.** The egress door has exactly one adjudicator slot. Two
components fill it. The launcher registers the operator policy — ADR-027 Amendment 1,
*the paste IS the consent for that one URL*, which rebuilds the allowlist from the
request's own address. The Assistant Orchestrator registers the standing policy — one
fixed host, everything else denied. Whichever held the slot decided the policy for both.
The runbook called this an open governance question about which adjudicator should win,
and noted it was "checked by vigilance, not by a control" — and it also called the slot
first-wins, which is wrong, as the review below establishes.

**What the code says.** Both answers are right. A pasted URL *should* authorise its own
host; a model-initiated search *should* be confined to the standing list. The only
thing needed to tell them apart is which kind of request arrived — and that is already
in the Canonical Action Representation, in a field called `purpose`, which the very
same function already reads a few lines earlier to keep the image door welded.

So there is one adjudicator now, and the request picks the policy. Both registration
sites build the same callable. Startup order decides nothing.

**The hazard the ticket attached, which is the part that had to be settled first.**
Keying consent on `purpose` is only safe if the model cannot choose `purpose`. If it
can, a model-composed request can claim the operator pasted something, and
paste-is-consent becomes consent-for-anything. The ticket was explicit: prove it before
adopting the design, and *if it is forgeable the design is worse than the gap and must
be rejected.*

It is not forgeable. Every runtime path into the door pins a module-level literal at
the call site; the model picks a door, never the string. The analyser that establishes
this is AST rather than text — a source scan cannot tell a call from a comment, nor a
module constant from a parameter that happens to share its name, and both have defeated
locks in this repository before. It resolves imports to their module-level bindings,
follows a parameter threaded through its callers with a depth bound and a cycle guard,
refuses to treat a name bound twice at module level as a constant, and — the part that
matters — **reports anything it does not recognise as FORGEABLE rather than as proof.**
An unrecognised indirection is exactly where guessing favourably would destroy the
value of the check.

**What the old wiring was actually doing, which nobody had written down.** The
launcher's policy rebuilt the allowlist from the request's own URL *for every
purpose* — including web search. The door
authorised whatever host the request named. Nothing was exploitable: the tool-loop
check still adjudicated web search against the standing list, and that URL is a
compile-time constant. But a layer of defence-in-depth was silently absent in that
mode, and the only thing standing between "not exploitable" and "exploitable" was a
constant nobody had connected to the argument.

**Two documents in the same module disagreed, and the wrong one was the docstring.**
`make_operator_url_adjudicate` promised that an unparseable resource "yields None →
empty allowlist → RULE 3 DENY … refused, never silently allowed". RULE 3 only fires on
a resource that *starts with* an external-network scheme, so a resource with no scheme
skips it entirely and falls through to ALLOW. Measured: the old function returns ALLOW
for `"not-a-url-at-all"`.

The correction I want to keep is about who knew. Its own test file had this right the
whole time — `test_non_web_egress_scheme_denies` explains in its docstring that a bare
non-URL "is not an external-network action at all" and that the door's SSRF guard is
what refuses it. The test was accurate, the function's docstring was not, they sat forty
lines apart, and nobody reconciled them. My first instinct was to write this up as a
discovery. It was a *contradiction*, already on disk, that two readers had passed over.

The refusal is explicit now rather than delegated to RULE 3. Nothing was exploitable
either way, because the door's https-only validation catches it independently — but a
fail-closed claim that rests entirely on the next layer down is how a layer gets deleted
later by someone who reads the claim and believes it.

**Both superseded factories are deleted, not deprecated.** After the unification one had
zero callers in the repository and the other had a smoke script. Leaving a security
factory that nothing calls — one of them carrying a false guarantee — is the shape this
week has made me re-find five times.

**The mutation run earned its keep twice.** Seven mutants: inverting the purpose test,
removing the branch, deleting the no-host refusal, widening the paste set to cover web
search, dropping a type guard, removing the image weld, ignoring the standing allowlist.
Six died on the first pass. The survivor was the type guard, and it survived *honestly*:
with or without it the door ends at DENY, so no test driven through the door could tell
the difference. They differ in how — without the guard, an unhashable purpose makes the
set membership test raise, and the door's blanket except catches it. Fail-closed by
accident rather than by design. The contract now gets asserted at the function, which is
where it lives, because that function is called directly by a smoke script and by tests
and not only through the door.

**Then a reviewer took it apart, and the corrections are the better half of this
entry.**

*The lock that everything rested on failed open on three ordinary shapes.* Its own
headline sentence — anything it does not recognise is FORGEABLE, never proof — was
false, and I had quoted that sentence as the safety argument in four separate
documents. An aliased import of the door produced **no row at all**, which is worse
than a finding, because a report with nothing in it reads as a clean bill of health.
And the proof that one module's seam was safe was being lent to *any* module that
reused the attribute name — so the summarizer the runbook already anticipates, copying
the obvious name, would have inherited a guarantee it never earned.

My first attempt to prove the second fix **passed for the wrong reason**. The fixture
tripped a different check, so it stayed green with the fix reverted. I only caught it
by mutating the fix out and watching the test not care — which is the only way that
class of mistake ever surfaces.

*I wrote three paragraphs about a defect and fixed half of it.* The whole argument was
that leaning on a rule which never fires is wrong. I applied it to one branch of two.
The other still returned ALLOW for a hostless resource. Writing the reasoning down and
then covering half the code is worse than not writing it, because the comment now
certifies the part it does not reach.

*I propagated a wrong mechanism into five new places.* Everything I wrote said the
adjudicator slot was "first-wins" and that startup order decided the policy. It is
last-write-wins, and the launcher does not guard its registration while the
orchestrator does — so the operator policy won whenever the launcher ran, in either
order. Not a race: a precedence, which makes the old widening deterministic rather than
an unlucky edge case. Claim-register row 2 had recorded this correctly all along, one
row above the row I rewrote, in the file I was editing.

*And a mutant survived that was right to survive.* Adding an extra host to the paste
allowlist changed no verdict — because nothing ever looked at the allowlist, only at
what it produced. Which meant this entry's own headline claim, that a paste authorises
its host and nothing more, was unfalsifiable by construction. It is asserted at the
seam now: the set handed to the checker is captured and required to be exactly the one
host. The mutant stopped being equivalent the moment the claim became testable.

**Proposed lesson:** *A question parked for someone else should be re-read before it is
escalated again, because the parking is what stops it being examined.* This one was
labelled a governance call in a runbook, and that label was load-bearing: it made the
question look answered-pending-approval rather than unexamined. It survived several
sessions that all read the runbook. The tell is a decision that has been waiting a long
time without anyone being blocked by it.

**Proposed lesson:** *When two artifacts in the same module disagree, prefer the one that
executes.* The test asserted the true behaviour and the docstring asserted the false one.
Both had been reviewed. The test was the one being run.

**Proposed lesson:** *A mutation score is a statement about the mutants you wrote.* The
first battery reported 7 of 7 and I wrote the record on it. The review then defeated the
central lock three ways and found two survivors my battery had not imagined. "All mutants
killed" means the ones I thought of, and the ones I thought of are drawn from the same
understanding that produced the code.

**Next:** #1595 — provenance-based constraint on the outbound query, the research pass
its ticket describes.
