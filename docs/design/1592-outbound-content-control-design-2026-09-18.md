---
title: "#1592 — outbound content control: research, options, recommendation"
status: proposal
area: security
ticket: "#1592"
---

# Outbound content control for the one egress door

**Written 2026-09-18 after the Lead Architect asked whether the proposed fix had been researched and
designed well enough to approve. It had not. This is that work.**

The short version: **the fix I proposed is the wrong one, and the published landscape says so.** The
right control is already 80% built and is being undermined by two specific, closeable details.

---

## 1. What I originally proposed, and why it was wrong

I told the LA that the exfil screen never sees HTTPS (true, measured, #1592) and that the fix is to
move content inspection above TLS, into the egress door. Two things are wrong with that.

**It mislocates the control.** The door that already adjudicates every tool call is handed the exact
string that would leave — `_adjudicate_tool_dispatch(tool_name, tool_args, session_id)` receives
`{"query":"..."}` and builds a CAR from it, before any request exists. No new interception point is
needed anywhere.

**More importantly, it assumes inspection is the right lever.** It is not, and the evidence against
it is strong enough that proposing it without checking was the substantive error.

---

## 2. What the published landscape actually says

### 2.1 The industry has moved away from outbound content inspection for this problem

Every major vendor shipping an agent egress control in the last two years — Anthropic, OpenAI,
Google, Stripe, StepSecurity, AWS, GitHub — ships a **destination control at a proxy the agent
cannot reconfigure**, and explicitly declines to inspect payloads. Anthropic's Claude Code proxy
["does not terminate or inspect TLS"](https://code.claude.com/docs/en/sandboxing); its
TLS-terminating mode exists for credential substitution and "does not add content filtering."

### 2.2 But destination allowlists do not solve it either, and there is a published proof

Across at least five independent incidents the exfiltration channel **was** the allowlisted
destination: `script.google.com` (Bard), GitHub's own signed Camo proxy (CamoLeak),
`blob.core.windows.net` (ChatGPT, twice), Teams/SharePoint inside M365's own CSP (EchoLeak), and
`api.anthropic.com` (Claude "Pirate").

Anthropic's own post-mortem states the lesson exactly, and it applies to us verbatim:

> "Previously, we'd conceptualized the allowlist as a destination filter… But it may be better
> conceptualized as a **capability grant**."

**A search provider is an arbitrary-text sink.** Our allowlist naming `kagi.com` has already granted
the capability to send arbitrary text. That is the honest statement of our position.

### 2.3 Content inspection for personal data is a ~75%-precision instrument

Measured, peer-reviewed ([arXiv:2609.03464](https://arxiv.org/abs/2609.03464)): Microsoft Presidio on
**clean** data scores **precision 0.755**. Roughly one detection in four is wrong.

For the shape we would most want to catch, it is far worse. **An SSN has no checksum** — Microsoft
says so in their own reference — and Presidio prices a bare nine-digit number at **0.05 out of 1.0**,
labelled "very weak". Microsoft Purview requires a supporting keyword within 300 characters and its
recommended confidence level **excludes post-2011 randomised SSNs entirely**.

Secret detection is no better: an IEEE benchmark over 97,479 labelled secrets measured TruffleHog at
**6% precision**, gitleaks at 46%, GitHub's own scanner at 75%.

The generalisation that matters: **precision is a property of the credential's shape, not of the
scanner's quality.** A distinctively-structured token can be matched at 99%; a password or a bare
identifier cannot be, by anyone.

### 2.4 Over-blocking is itself a security failure, not merely an annoyance

Microsoft Purview's planning guidance, verbatim:

> "A haphazard, rushed deployment can negatively impact business processes and annoy your users.
> Those consequences slow acceptance of DLP technology… **Ultimately, those consequences make your
> sensitive items less safe in the long run.**"

GitHub declines to block on its own low-confidence patterns "to avoid blocking commits
unnecessarily", and ships "It's a false positive" as a first-class bypass reason.

**This lands directly on a lesson from earlier today.** Twice in #1580 I attached a global
kill-switch to a local condition and had to undo it. A content screen at 75% precision wired to
"cut all egress until the operator re-arms" is the same mistake with a worse trigger.

### 2.5 Character-at-a-time encoding defeats content filters outright

CamoLeak leaked data **one ASCII character per image request**, every request CSP-legal and
GitHub-HMAC-signed. A filter examining a single request sees one character.

OpenAI rediscovered the same bound independently: for "123 Main Street" an attacker "would require
the model to make **13 separate sequential accesses**." Lampson named this in 1973 — you can bound a
covert channel's capacity, but "reducing it to zero requires more far-reaching measures."

**Any content screen we build is a bandwidth limiter, not a barrier.** That is worth having. It is
not worth mistaking for a wall.

### 2.6 What the frontier actually recommends

The strongest published direction is constraining the **shape and provenance of what goes in the
field**, not scanning it:

- **OWASP LLM06:** *"Implement authorization in downstream systems rather than relying on an LLM to
  decide if an action is allowed."*
- **OWASP LLM03:2026 #3:** *"Tools should define a strict schema for any input parameters, and
  validate contents prior to use."*
- **OWASP Agentic ASI02:** a pre-execution policy enforcement point that *"validates intent and
  arguments"*; **"Fail closed on ambiguous resolution."**
- **Fides** ([arXiv:2505.23643](https://arxiv.org/abs/2505.23643)) supplies the one published
  argument that a bounded field is a smaller channel: a type lattice **`bool ⊑ enum ⊑ string`**, on
  the explicit rationale that lower-capacity types carry less information.
- **PACT** ([arXiv:2605.11039](https://arxiv.org/abs/2605.11039)): injection becomes dangerous "when
  it determines an **authority-bearing argument**." Its own stated limitation lands on us: arguments
  named `query` resolve ambiguously between content, selector and command.
- **The most widely shipped control of all** is human approval showing the exact arguments — OpenAI
  Agents SDK, Microsoft Agent Framework, Cloudflare Agents, Strands, Agno.

### 2.7 An honest gap in the evidence

There is **no canonical published paper** whose thesis is "narrow the tool signature as a security
control." It exists as a supporting device inside larger architectures and as a reasoned claim in
exactly two places. Anyone citing it as settled practice is over-reading. Equally, there is **no
independently-measured false-positive rate for DLP content screening anywhere in the literature**,
and no published post-mortem of a DLP deployment disrupting a business — an absence that biases the
available evidence toward *under*-counting the cost of over-blocking.

---

## 3. What BlarAI already has, read from the code

| Layer | Control | State |
|---|---|---|
| Destination | `_EGRESS_ALLOWLIST = frozenset({"kagi.com"})`, enforced at both the dispatch loop and the door | LIVE |
| Human presence | Windows Hello on the **first** egress of a turn, **showing the query text** | LIVE |
| Subsequent searches | `searches_per_fingerprint = 3` — disclosed in chat, **not re-approved** | LIVE |
| Shape | URL, method and headers are compile-time constants; body is `{"query": <one string>}` | structural |
| Content | nothing that is ever invoked (#1592) | **absent** |

**Our position is much better than "no content screen" suggests.** The model's entire outbound
surface is one string field, and the operator is already shown that string and asked to approve it.
That is the control the research says is most widely shipped, and we built it.

---

## 4. The two defects that actually matter

Both are specific, both are closeable, and neither is a content screen.

### 4.1 The operator approves a TRUNCATED view of what leaves

`egress_envelope.extract_query()` returns `descriptor[:200]`, and that 200-character string is what
`request_egress_fingerprint()` puts in the Hello dialog. The full, untruncated query is what the
adapter sends.

**So a 5,000-character query shows the operator 200 characters and sends 5,000.** Everything after
character 200 is approved without ever being displayed. The truncation is well-intentioned — the
docstring says it "bounds a pathological one" for dialog rendering — but it bounds the *display*,
not the *payload*, and the asymmetry is the exfiltration channel.

This is the single most exploitable detail found in this whole review, and it needs no classifier to
fix.

### 4.2 Searches two and three are not approved

One Hello approval covers up to three searches in a turn. The claim register already names this as a
known 2026-07-02 decision rather than a defect. In light of the research it reads differently:
**the approved search establishes presence, and the two unapproved ones are the exfiltration
window.** The pattern of "get one benign action approved, then act" is the shape of several of the
incidents above.

---

## 5. Options, ranked

**Option 1 — Make the approval honest (RECOMMENDED, and it is not a posture change).**
Show the operator the complete query, or refuse to send a query longer than what was displayed.
Concretely: cap the query at a length that renders fully in the dialog, and make the cap a *send*
constraint rather than a *display* constraint, so what is approved is byte-identical to what leaves.
This closes §4.1 entirely, introduces no classifier, has no false positives, and is the control the
published landscape ranks highest.
*Cost:* a long legitimate query gets refused and the model must shorten it. **Fides' argument applies
directly: a bounded field is a smaller channel**, and this is the structural constraint the research
recommends over inspection.

**Option 2 — Reduce `searches_per_fingerprint` (LA's call; it is a posture flip).**
From 3 to 1 makes every outbound search individually approved. This is a friction increase and a
genuine capability/quality trade, so it is his decision, not mine.

**Option 3 — A content screen at the dispatch door, as a SECOND layer.**
Worth having as a bandwidth limiter, on three conditions the research makes non-negotiable: it
**denies the tool call** rather than tripping the kill-switch; it fires only on
**distinctively-shaped, high-precision** patterns (a Kagi token, a JWT, a private-key header) and
**not** on bare nine-digit numbers at 0.05 confidence; and it ships in **audit-only mode first**,
which is Microsoft's and GitHub's published doctrine and which we have no local equivalent of.

**Option 4 — Provenance constraint (the research frontier; NOT proposed now).**
Constrain the query when the turn has ingested untrusted content, per PACT and the design-patterns
paper. This is the strongest published direction and the least mature. It deserves its own ticket
after 1 and 2, not a bolt-on here.

**Rejected: TLS-terminating local proxy.** Durumeric et al. (NDSS 2017, 7.75bn handshakes) found
interception made 62% of middlebox connections *less* secure, with 58% carrying severe
vulnerabilities, and eleven of twelve corporate middleboxes exposing connections to known attacks by
default. US-CERT TA17-075A says the same. We would be adding the attack the paper describes in order
to inspect one string field we already hold in plaintext one layer up.

---

## 6. What is mine and what is his

**Mine, and I will build them without further asking:** Option 1 (making the approved string identical
to the sent string is a defect fix, not a posture change), and the honest correction to claim-register
row 12 already landed.

**His:** Option 2 (`searches_per_fingerprint` is a quality/friction trade he decided in July and only
he can revisit); and whether Option 3 is wanted at all, given that on this evidence a content screen
is a bandwidth limiter rather than a barrier, and carries a measured one-in-four false-positive rate
that must be spent on *something*.

**Neither, yet:** Option 4 needs its own research and its own ticket.

---

## 7. What this design does NOT claim

- It does not claim the model would attempt exfiltration. A published evaluation across 25 models
  ([arXiv:2510.09093](https://arxiv.org/abs/2510.09093)) measured success from 72.4% (Grok-4) to
  **0.0%** (Claude-Sonnet-4, Gemini-2.0-Flash-Lite, Nova-Micro, GPT-OSS-120B). **Qwen3-14B, the model
  we actually run, was not among them.** Model-layer refusal is therefore not a control we can claim.
- It does not close the covert channel. Nothing here does; Lampson's 1973 argument stands.
- It does not address the response direction — search results re-entering context as untrusted
  content is the second leg of the lethal trifecta and is out of scope for this ticket.
- The research on which §2 rests is recorded with its sources at `docs/research/` and on #1592. Three
  separate summarised fetches during that research returned claims not present in the underlying
  documents; every load-bearing figure above was checked against a primary artifact.
