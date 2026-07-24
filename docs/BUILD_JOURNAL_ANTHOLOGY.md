---
title: The BlarAI Anthology — Field Notes from Governing an AI Fleet
status: living
area: portfolio
---

# The BlarAI Anthology — Field Notes from Governing an AI Fleet

*Plain summary: the 64 build-journal entries a stranger should read — the story of a
non-technical Lead Architect and an AI development fleet building a private, local,
security-first AI system together, told through its best failures, decisions, and
recoveries. Entries appear verbatim as originally written; curation is selection, not
rewriting.*

**How this was curated.** Seven era-scoped mining agents read all 465 journal entries
(2026-05-21 → 2026-07-17) during the 2026-07-18 documentation audit (#945); 62 entries
were marked keep-hot and two near-misses were promoted during assembly (the #725
upstream-fix pair). The full corpus lives untouched in the monthly volumes at
`docs/archive/journal/`. New gems are promoted here at the monthly retrospective.

**The five acts.** I — the pivot from an "agent factory" that produced the appearance
of work to verified-live shipping, and the forging of the culture ("the screen is the
only oracle; mocks lie"). II — the decision at the wall: preparing to cut a door in the
air-gap, review-before-decision, the four-grade honesty scale. III — cutting the door:
the first packet ever to leave the box, one policy-gated re-welding door, hostile
content parsed only in a network-less guest. IV — teaching it to build: image
generation, the coding fleet, the best-of-N reversal, the first governed web search.
V — the honesty machine: nightly reliability batteries, instruments forced to earn
belief, learning loops where the model can suggest but never write, and the first
fixes contributed upstream to the engine itself.

---

## Three reading paths

**The governance path** (for an AI-governance reader): The briefing before the
irreversible door · The security audit I verified, and the presentation I didn't · The
after-bookend, and the audit you have to be honest about · The door we cut into the
wall · The first packet off the box · The lock I proved, then declined to fit · The one
store I chose not to encrypt · Teaching the box to draw, with the door welded shut ·
Content safety as a signature, not a classifier · The load that should not have fit,
and the trust grain for code I did not write · Shipping the proven thing live, not
dormant-with-a-flip · The answer the door let through and the validator swallowed ·
Measuring the intelligence, not just the software · Two protocols share an acronym ·
Reading the neighbours' houses before building the second floor · The contractor we
never checked · Letting the model suggest without letting it write · The trailer cut in
the shadow of the battery.

**The engineering path** (for a staff-engineer reader): Provenance-aware redaction ·
Mocks pass, seams break · The replay window between two correct components · The screen
that would have strangled the host it guards · The encrypted store that kept a
plaintext fingerprint of its own contents · Three things the merge gate caught before
the door ever opened · The knowledge bank that could only be written to · The door that
would have tripped its own alarm · A third failure posture, and the index that lives
only in RAM · The gallery that tested green and showed nothing · The verifier I almost
broke for the whole fleet · Measuring whether releasing the 14B actually opens the door
for the 30B · The four bugs the green suite swore weren't there · The over-denial that
turned out to be unreachable ALLOW · The gate that vanished at 76 percent · The crash
that only happens when two right things run together · The fix that couldn't be proven
on the machine that broke · The recovery that killed the patient · The verification
line nobody ever read · The estimate the kernels cut in half · The screenshot that
convicted an innocent app · The grader kept its answer key in its pocket · The gate was
green and the real pass still 400'd.

**The collaboration path** (the human story — a domain-blind but rigor-literate
architect as the best instrument in the lab): The pivot, and the first real shipping ·
Pausing the safety feature, on purpose · A trust root built on hardware nobody had
checked · The fix that logged a lie, and the capability cut I almost made without
asking · The operator looked at the lock and said it felt wrong, and he was right · The
premise nobody checked · The night BlarAI first answered a prompt in production · The
on-chip session I told the agent to make the operator run · The fingerprint, and the
decision I tried to hand back · The one place the machine still graded its own work ·
The lever I'd built three reviewers to avoid finding · The plan that had to survive
four rounds of its own medicine · The novice question that found the untested half ·
Probe, don't predict · The film that had to earn every second · The clean room takes
its first exam.

---

## Act I — The pivot and the forging (May 21 – Jun 7)

### 2026-05-21 — The pivot, and the first real shipping

For months I had been stuck. The plan was a "factory": a fleet of AI agents that would wake on a schedule and build BlarAI autonomously. I put in time, and real money. It never worked. What it produced was process — documents describing work, audits of the documents, reports on the audits.

BlarAI itself was real underneath all of it — a working local assistant did exist. But the machine meant to *advance* it was mostly spinning in place.

The turning point was naming it honestly. Working with an AI coding agent, we looked at what the fleet had actually done and counted: around 259 automated sessions had committed something, and only 15 of them had touched real code. The rest was paperwork. The "factory" was, in effect, a machine for producing the appearance of work.

So I stopped. The new approach: forget the factory, build the product directly. Build the smallest thing that genuinely runs, verify it on the real system, and grow from there — one real capability at a time.

**The way of working that replaced it:** an agent does the work; the changes are reviewed against the real code and the tests are re-run; I verify it live on the real system myself; it is committed only if it survives. Simple, and it ships.

Working that way, in a single session, BlarAI's core chat went from rough to genuinely working — four fixes, every one confirmed by me on the live system before being committed:

- **It remembers within a conversation.** BlarAI had been answering every message in isolation, with no memory of what was said moments earlier. A built-but-unconnected component was wired in, so it now carries conversation context. *(commit `aacb127`)*

- **It remembers across restarts.** Close BlarAI completely, reopen the conversation, and it still knows what was said. The original task asked for a second database to hold this — but the project's governance rules say only one component may own the session store. The task was wrong; I caught it before building, and did it the correct way: the history is replayed to the assistant over the channel that already exists. *(commit `b751147`)*

- **It answers like a person, not a textbook.** A hidden heuristic was stapling a rigid "definition / numbered list / example / summary" template onto any question. Asking "what is your name?" produced a six-part essay. It no longer fires on ordinary questions. *(commit `9baa2d8`)*

- **It stopped leaking its own thinking.** The model reasons inside `<think>` tags before answering, and that raw reasoning was dumping straight into the chat — fifteen lines of noise before every reply. The code meant to hide it had been matching the wrong tag all along, so it had never worked — and the tests for it used the same wrong tag, so they passed while the feature was dead. Fixed both the code and the tests. *(commit `13c235e`)*

None of these fixes was large. Together they turned BlarAI's chat into something that genuinely works: it remembers you, it answers normally, and it no longer clutters the screen with its own internal monologue.

**Next:** make BlarAI *agentic* — able to use a tool. That is the keystone; scraping, code help, and working with my own data all build on it.


### 2026-05-22 — Provenance-aware redaction: what the tests passed and the screen failed

BlarAI got the privacy feature I had been circling for a while — honest, provenance-aware redaction. But the part worth recording is not the feature. It is that the feature's logic was correct, its tests were green, and it was *still* visibly broken twice when I actually sat down and used it. Each time, the screen caught what the test suite could not.

**What it does.** BlarAI's output validator now has a third setting. For every personal detail in a reply — a phone number, an email — it asks one question: did this come from *me*, or did the model produce it on its own? A detail that traces back to a document I loaded, or to something I typed, is *mine* — it is shown. A detail that traces to nothing I provided — the model invented it, or it was slipped in by a document trying to manipulate the assistant — is replaced with a visible marker that says what was withheld and why. The reply is still delivered; only the untraceable part is covered. It is the inverse of the redaction a company does: a company hides its users' data to protect outsiders; BlarAI, which exists to hand me *my* data, instead hides what is *not* verifiably mine — which, as a side effect, also catches the model inventing a number and stating it as fact. My everyday setting stays "off" — a personal assistant should surface my own data freely. The redaction mode is the demonstrable artifact, not the daily driver.

**Why it is also a portfolio piece.** I am working toward a professional certification — the IAPP's Artificial Intelligence Governance Professional — on a real, six-week deadline. So this is the first thing I have built deliberately to line up with a recognized standard. It does not just *work*; it ships with a document mapping each design decision to the certification's body of knowledge and the privacy frameworks underneath it. The point of the portfolio is to show governance judgement, not just code — so the artifact has to show its reasoning.

**The first break: a feature the tests passed and the screen ate.** Fourteen tests checked the redaction logic, and they were right — the logic was sound, and the saved conversation later confirmed the correct marker text had been written into the response. But the first time I asked BlarAI for an example phone number, the redacted spot on screen showed `****` — four asterisks — and nothing else. I did not guess at why. I read the engine's own log and the saved conversation, the way the last few of these entries taught me to. They showed the redaction had worked perfectly. The fault was downstream: the chat window treats square brackets as *formatting instructions*, and my marker was written in square brackets — so the window read the whole phrase as an instruction and swallowed it, leaving only stray punctuation. The real bug was bigger than my marker: *any* model output containing brackets — a citation, a snippet of code — would have been silently mangled. The fix was to treat the model's words as data, not as formatting, and the screen finally showed the marker.

**The second break: the model handed the number over in pieces.** I tested again. This time the marker displayed correctly — but the model had been clever without trying to be. Instead of writing one ten-digit number, it wrote "Area Code: 212" on one line and "Phone Number: 555-0198" on the next. The detector looks for the *shape* of a full phone number; neither fragment has that shape, so neither was caught, and only the combined "full format" version got redacted. The pieces leaked. This is a real limit of matching by shape, and the honest fix is not to pretend it away: I added context-aware detection — a number sitting right beside a word like "Phone Number" or "Area Code" is now flagged on the strength of that word, even when its shape alone would not qualify. The fragments are caught now. And the limit beyond that is written down plainly rather than hidden: a number stated with no surrounding words at all could still slip, and closing *that* needs a different class of detector — logged as future work, not quietly ignored.

**The lesson.** It is the multi-layer-verification point, made concrete twice in one afternoon. The tests verified the *logic*, and they were not wrong to pass — the logic was correct. But a passing test on the redaction logic cannot see a chat window eating a bracket, and it cannot see what a real model actually does with a real prompt. Only sitting down and using the thing surfaced both. Unit tests prove the part you wrote; live use proves the product. And both faults were found the same way — by reading ground truth, the log and the database, instead of guessing. The instinct to check is the one that keeps paying out. *(commit `4c8a35f`)*

**Next:** the prompt-injection defence the `/load` feature has been waiting on; then clearer session names — a data-quality fix, not cosmetics; then paste support in the input box; and, noted for later, BlarAI's slow start-up.


### 2026-05-26 — Pausing the safety feature, on purpose

Blair came back after several days away. The work of getting Layer 3 to the screen had cost too much. He tested it once and the screen still showed bugs — `/trust` did not actually re-enable tools, and `/unload` did not restore them either, both despite the gateway and TUI reporting success. He said it plainly: *I don't care about this safety tool maturation right now enough to continue with this. Fix this safety feature and then move on.* And then the harder honesty — *if we don't get major development done I am going to potentially quit this project altogether.*

The right move is the one I have been resisting because it feels like giving up. It is not. Layer 3 was designed for a system that has tools whose blast radius matters — file write, network calls, irreversible actions. BlarAI today has exactly one tool, `get_current_time`, which reads the system clock and returns a string. The marginal security value of Layer 3 on top of that is approximately zero. The friction it adds to the daily-driver experience is approximately a hundred. The trade is on the wrong side.

So Layer 3 is **paused** — `pgov.block_tools_when_documents_loaded = false` in `default.toml` and `guest_runtime.toml`. The entire architecture stays in the code: the gate, the `/trust` override, the inline helpful message, the `/unload` revoke, the audit logging, the misconfiguration startup warning. None of it is deleted. The day BlarAI gains a tool whose blast radius is bigger than reading a clock — file write, network fetch, calendar mutation — the flag flips back to `true` in one line, and a focused session goes back and fixes the live-verified `/trust` propagation bug the 2026-05-26 UAT surfaced. Until then, the comment in `default.toml` names what is paused, why, and what needs to be done when un-pausing.

The other lesson here is mine more than the project's. The previous several entries of this journal are a single Layer-3 effort that grew from a small `/load`-time `/unload` flag into a five-commit security architecture with two amendments and a third honest-pivot entry — past the point where the increment was earning its keep against the product BlarAI is actually trying to be (Blair's daily, useful personal assistant, the portfolio piece of an AIGP cert track). The "small thing that genuinely runs, grown one observed need at a time" working principle is in the lessons list at the top of this file. Layer 3 stopped being that and I did not notice in time. The pause is partly the apology. The next entries return to the principle. *(commit `<this>` (default-flip in both TOML files + this entry); awaits merge to main alongside the rest of `feature/document-injection-layer3`.)*

**Next:** move on. The data pillar — what `/load` was always trying to be — wants more interesting documents than `.txt` and `.md`. PDFs are the obvious next slice; that's what real documents are. Pick one focused capability that compounds (PDF support, or more tools in the registry, or paste support in the input box), ship it visibly, verify it live, end with something Blair actually uses on his hardware in the next 24 hours.


### 2026-06-03 — A trust root built on hardware nobody had checked

Blair asked for the security features — the hardware-rooted trust that is supposed to be the spine of a system meant to run for decades. I went to build the first one and found the foundation was a rumour.

The canonical use-case document specified the Policy Agent's trust root as Intel SGX: a measured boot that completes "SGX local attestation" before deriving the CA key. The trouble is that Intel removed SGX from its client CPUs years ago, and the target machine — a Lunar Lake laptop — has none. The code never used it; the design only *said* it did. So the trust root, on paper for months, was a phantom: a sentence describing hardware that was never there. (This is lesson fourteen wearing a more expensive suit — an assumption inherited from the design, true nowhere, load-bearing anyway.)

The way out was to stop reading the spec and query the silicon. `tpmtool` reported a TPM 2.0 present, attestation-capable, firmware not vulnerable — and I promptly made my own smaller version of the same mistake. Its manufacturer string said "STMicroelectronics," so I wrote "the chip is not Pluton." Blair pushed back: he was almost certain his laptop *had* Pluton — the marketing said so, Device Manager said so. He was right, and I had been sloppy. Device Manager shows *two* security devices: a "Trusted Platform Module 2.0" (the active TPM, ST-made) and a "Microsoft Pluton security processor" (present, Intel Lunar Lake, just not serving as the TPM here). I had collapsed two devices into one claim and stepped on the knowledge of the person who owns the machine. The lesson landed twice in one day: verify the hardware, and when its owner contradicts your inference, the owner wins.

With the device actually characterised, the trust root rebuilt itself cleanly. I wrote a signing primitive against the standard Windows TPM interface (CNG's Platform Crypto Provider) — create a key *inside* the TPM, sign, verify, and crucially never be able to export the private half. Then I did the thing this project has learned never to skip: I ran it on the real chip. It nearly worked — sign, verify, tamper-rejection, public-key export, all correct first time — and then died on the very last step, deleting the test key, with `NTE_BAD_FLAGS`. The TPM rejects a flag the Microsoft documentation says it accepts. No amount of reading would have found that; only the silicon returning the error did. One flag changed, and the round-trip — including a direct assertion that the private key cannot be exported — passes on hardware.

So the decision, ratified with Blair: re-root trust on the TPM 2.0, in the "proven core" shape — seal the CA key and sign the model-weight manifest with non-exportable TPM keys, with a provisioning-and-recovery ceremony so a lost key cannot fail-closed-brick the machine — and *stage* the harder part, formal boot-state attestation, for later. ADR-018 records it and supersedes every SGX reference in the use-case doc. I was honest in the ADR about what this does and does not buy: TPM-signing makes the weights tamper-evident *at rest*, against an attacker with the disk but not the running machine; it does not, yet, stop an attacker who can run code on the host and ask the TPM to re-sign. That boundary is the PCR-binding work I deliberately deferred — naming it is the point, not hiding it.

What shipped here is the foundation, hardware-verified, plus the architectural decision that unblocks the rest. The feature that consumes it — the tamper-evident weight manifest — is next, and it rolls out warn-only before it enforces, because the one thing worse than no trust root is one that bricks the system it was meant to protect. *(commits `<this>`: `docs/TPM_CAPABILITY_FINDINGS.md` (ISS-4); ADR-018 + `Use Cases_FINAL.md` SGX amendment (ISS-5); `shared/security/tpm_signer.py` + hardware-verified `test_tpm_signer.py`; lesson 18. Vikunja #101/#102 closing; FUT-04/01/05 open.)*

**Next:** FUT-04 — sign the weight-integrity manifest with the TPM key and verify it at boot before trusting the hashes, behind a warn-only→enforce flag. Then the host-vs-VM decision for the CA key (FUT-01) and the provisioning/recovery ceremony (FUT-05). Formal PCR-quote attestation remains staged.


### 2026-06-03 — The security audit I verified, and the presentation I didn't

Blair is steering BlarAI toward the network — eventually internet-facing, to fetch information and navigate the web — and he made the right call about order: real security before real memory, and certainly before the air-gap comes off. So he asked for something I had not built before — a complete, honest map of the system's security, features and vulnerabilities, rooted in what is actually on disk, illustrated, so he could understand it and make informed decisions.

I ran it as a formal multi-agent audit: seven domain auditors against the real code (trust root and measured boot, the Policy Agent authorization gate, IPC and isolation, prompt-injection defense, output validation, the privacy/network boundary, data at rest), each finding then independently re-checked by an adversarial verifier that opened the cited files and tried to refute it, then a completeness critic and a red-team synthesis — sixteen agents, every claim cited to a file. The picture is the valuable part and the sobering part: one Critical, eighteen High. The recurring theme was not "unbuilt" — it was "built but switched off." The TPM trust root exists and is wired into nothing. The guest profile ships with dev_mode on, which disables mTLS, identity binding, weight verification, and measured boot in a single config line. The leakage and PII output filters ship off. The deterministic injection backstop is off. There is no code-enforced network kill-switch — the air-gap is environmental, not enforced. The data at rest is plaintext. And the Policy Agent's signing key — the key the whole authorization model trusts — sits in git in cleartext. Today none of it is reachable, because the machine is not on a network. That is exactly the point: the air-gap is the only wall, and Blair wants the walls behind it built before he takes it down.

Then I did the thing worth keeping in. I verified every finding to the file, and I shipped the presentation carrying them with its diagrams broken — and when Blair told me, I "fixed" it and shipped it broken again. The mistake each time was the same: I "verified" the deck with a mechanical lint of my own — bracket balance, line breaks — a proxy that shares the artifact's blind spot, not the real Mermaid parser. Blair's words were exactly right: why verify all your findings only to mess up the data in the presentation. The third time I stopped guessing, installed the actual parser (the same Mermaid version his browser ran), and ran it over the exact strings the page ships — and the real cause was not the diagram syntax at all: the HTML embedding was round-tripping every `-->` arrow into `--&gt;` before Mermaid ever saw it. The fix was to hand each diagram straight to `mermaid.render()` as a string, never through the HTML parser. An independent cross-check of every slide claim against the verified findings came back faithful, with a few clarity fixes for a non-expert reader, which I applied.

That is lesson twenty-one, and it stings precisely because the audit was so careful: the vehicle that delivers a verified result is its own artifact, and it must be verified against the tool that will actually consume it — not a proxy of my own invention. Where it leaves us: Blair set the gate — complete the hardening roadmap through Tier 3 before facing the internet, all four tiers, not just the blocking ones — and asked me to implement it. Security code, mostly unverifiable headless, is exactly the work that wants fresh, sharp context and incremental live-verify, not a marathon-session blob tested once at the end. So this commit is the baseline — the audit, the findings, the deck, the verification tooling — and the build itself is scoped for a fresh session in `security-hardening-handoff-brief.md`, starting at Tier 0. *(commit `<this>`: `docs/security/audit_2026-06-03/` — `audit_full.json` (16-agent findings), `security_presentation.html` + generators, mermaid+jsdom validators; lesson 21; hardening handoff brief is untracked. Vikunja #555. Deck live-render still pending Blair's browser confirm.)*

**Next:** a fresh session implements the hardening through Tier 3 on a branch, tier by tier, each with a live-verify checkpoint — Tier 0 first (rotate + TPM-seal the signing key; build the egress kill-switch). Nothing goes internet-facing until all four tiers are verified done.


### 2026-06-04 — The fix that logged a lie, and the capability cut I almost made without asking

The memory work got worse before it got honest, and both halves of that are worth keeping. Blair ran the build and it was unusable: a vision turn timed out into a "VALIDATION_ERROR," and the machine sat at high RAM that did not come down. The telling sentence was his: *"It said over a minute ago that Qwen3-VL unloaded — VLM memory released and yet my RAM is still very high."* My eviction had logged exactly that — "VLM memory released" — and it was a lie. Not a malicious one; a hopeful one. `_pipe = None; gc.collect()` drops the Python reference, and my unit test proved the call happened and the global was cleared — but the test could not see the one thing that mattered, which is whether the operating system got the memory back. It did not. OpenVINO's GPU plugin pools native allocations and does not return them to the OS on a Python GC intra-process; the only reliable reclamation is process exit, which is why closing the app worked and my `unload()` did not. I shipped a memory fix whose actual effect on memory I had no way to measure, and I wrote a log line asserting the effect I wanted rather than the one I could prove. That is lesson 6 wearing fresh clothes — what you configure (or log) is not what runs — and lesson 16's bill come due: the layer I could not test was the only layer that counted.

Then the log told the real story, the way it always does. The images that froze were huge and the one that worked was small: the photo that hung for four minutes was 8160×6144 — fifty megapixels — while the "Who is this?" that answered in fifty seconds was 2.4. The VLM was being handed full-resolution phone photos, and a 50 MP image is an enormous vision-encoder patch grid; it spiked memory past the ceiling and the machine swap-thrashed a describe that should take seconds into minutes, which then blew past the IPC timeout and surfaced as the fake validation error (the same default-deny disguise from lesson 27). The cause was the input size, not the eager/lazy question I had been circling.

And here is the part that is mine to own. The obvious fix — downscale the image before the VLM — I wrote up as a "low-risk, standard, reversible" recommended option and was ready to ship. Blair stopped me, and he was right: shrinking a 50 MP photo to 1.5 MP would gut the answer for exactly the query that photo carried — *read the text on the wall* — and that is a reduction in what the product can do. His correction is the lesson: *"Design and technical decisions that have large impacts on the quality of the response is the kind of hard escalation we should be having to me, not stuff asking me about Git which I know nothing about."* I had the escalation bar backwards. The non-developer Lead Architect cannot and should not adjudicate how a commit is structured or which thread a call runs on — those are mine to decide. But what the user *experiences* — whether the assistant can still read the sign in the photo — is precisely his call, and I was about to make it for him by folding it into an implementation detail. The principle is now written where every agent inherits it: escalate what the user experiences; own how it is wired.

So this commit ships only what is safe to ship blind, which is *observation, not behaviour*. A small psutil-backed diagnostics helper logs real memory at the VLM's load, describe (with the image's dimensions and megapixels, so the size-to-cost correlation is right there in the log), and evict — and the evict line now reports the actual MB the OS reclaimed instead of claiming "released," so the no-op cannot hide again. The real fix is deferred, on purpose, to when the headless scenario harness Blair is commissioning can *measure* each option — native VLM pixel budgets, tiling that keeps full resolution per patch, evicting the 14B during the describe, a process-isolated VLM that the OS can actually reclaim — against quality and peak RAM, rather than my guessing and his machine paying for it. I stopped reaching for the fix. The harness is the instrument the last three rounds kept proving I needed.

**Next:** the headless scenario harness (separate effort) measures memory + describe latency + description quality across the #565 options; only then do we choose, with Blair making the quality call. The instrumentation landing here is its first building block. *(commit `<this>`: `shared/diagnostics.py` (psutil, fail-soft `memory_snapshot`/`log_memory`); `vlm.py` instrumented at load/describe/unload with image dims + honest reclamation accounting; `test_diagnostics.py`; downscaling rejected as a silent capability cut; issue + options documented in Vikunja #565; lesson 29.)*


### 2026-06-04 — The operator looked at the lock and said it felt wrong, and he was right

The provenance sprint shipped a working action-lock and I watched it verify live: paste untrusted content, ask for a tool, and BlarAI refuses with a helpful "/trust · /unload · rephrase" notice. Every test passed; the screen confirmed it. Then Blair — who calls himself a non-developer — looked at the same screen and asked the question I had stopped asking: *"is this locking mechanism really best practice? this whole trusting process seems bad."*

He was right, and the easy move would have been to explain why the design was fine. It is not fine. The lock turned off the *clock* because untrusted text was in the session — a calculator and a time-of-day call cannot exfiltrate, mutate, or egress anything, so locking them is friction with exactly zero security benefit. And `/trust` asked him — the least-equipped person in the system to judge it — to "accept that the untrusted content could influence the tool," the kind of un-evaluable "are you sure?" the security literature treats as click-through theatre. Two anti-patterns, shipped and green, and it took a non-expert's gut to name them.

The fix is not a tweak; it is a different shape, and writing it taught me the design was already half-built. Tools get a risk tier — SAFE, GUARDED, DANGEROUS. Safe tools are never locked. Dangerous *actions* — reaching the network, deleting, sending — are denied *absolutely* by the Policy Agent's deterministic deny rules, with no `/trust` to override, because a fooled-then-trusted user must never be able to authorise an exfiltration. What made it clean is that the sharp mechanism already existed: the #570 mediation I'd built hours earlier runs the deny check on *every* dispatch, so a tool exempt from the blunt lock is still checked at the action — the tier governs friction, the per-action deny governs danger. The blunt session-lock was a crude overlay sitting on top of a precise tool I already had. ADR-023 §2.4 had even written the distinction down — "fixed-action" versus "variable-action" tools — and I had locked uniformly anyway.

The honest sting is that this all verified live the same afternoon, and implementing the amendment makes the lock I just watched fire go *dormant* for today's four tools, because they are all SAFE — "what time is it?" under untrusted content will simply return the time. That is the point: the friction disappears and the machinery waits, proven by tests, for the first genuinely dangerous tool. The lesson I am keeping is the governance one, now lesson 38: a non-expert's "this feels wrong" about a security experience is rarely noise — it is the smell test the expert stopped running, and the right response is to re-derive from best practice, not to defend what shipped.

**Next:** #591 implements it — the gate gains a tier check, the four tools declare SAFE, the per-action deny is untouched; small and headless-buildable. The shipped lock stays as-is until it lands.

*(commit `<this>`: ADR-023 **Amendment 1** — capability-scoped locking (tool risk tiers; `SAFE` never locked; `DANGEROUS` denied absolutely, no `/trust`); §2 pointer + Status line; `DECISION_REGISTER` row updated; **#591** ticketed as the implementation follow-on (depends #590). No runtime code change — design ratified, implementation deferred to #591. New lesson 38. Rooted on disk in `shared/schemas/car.py` `ActionVerb`, `DeterministicPolicyChecker` RULE 1–4, `tools.py` (the four `SAFE` tools), #570/#590, and the SDV §10 tier-disambiguation.)*


### 2026-06-05 — The premise nobody checked: there were never "decades of data on disk"

While flipping the at-rest encryption ADR (ADR-025) to ACCEPTED, the LA caught a load-bearing factual
premise that the ADR, the Sprint-14 SDV, the security roadmap, and the entire review chain — including
my own design-gate presentation — had all asserted and none had verified: that BlarAI's two SQLite
stores held "decades of the user's private data," sitting exposed in plaintext, making encryption an
urgent rescue of already-exposed secrets. It read well. It was the natural motivation. It was also
false.

Checked on disk (2026-06-05): `substrate.db` holds 107 chunks (\~400 KB) and `sessions.db` holds 59
sessions / 376 turns (\~250 KB) — all build-phase dev/test scaffolding. BlarAI has never been used in a
daily setting; there is no real sensitive data anywhere yet. The honest framing is the opposite of
urgency: encrypt **now, before first real use**, so real data is *born encrypted* from its first byte
(no plaintext window ever) and the #598 gate criterion is met. The sprint is well-timed, not urgent —
with nothing exposed, there is zero data-exposure time pressure, which actually *strengthens*
"correctness outranks the date." The corrected premise is cleaner and more defensible than the one it
replaced.

What stings is how the false premise propagated. It was plausible, it was repeated across four
documents, and each author (me included) inherited it from the last rather than running a one-line
check against the actual files. The audit's Domain 7 finding was real — plaintext-at-rest *by design*
is a genuine architectural gap — but "the gap exists" silently became "decades of data are exposed
through it," and no one tested the upgrade until the LA did.

**Next:** ADR-025 ACCEPTED with the corrected premise; SDV §1/§3 and the roadmap corrected; the
live-memory vector logged as deferred-not-denied (roadmap §8 / #611). EA-2 (cipher + envelope) and the
EA-5 refuse-to-start hardening proceed under the merge gate.

*(Premise correction folded into ADR-025 §1/§3, SDV v3 §1/§3 + revision log, and
`SECURITY_ROADMAP_air_gap_removal.md` §8 at commit `804a0ef`. Lesson 48.)*


### 2026-06-06 — Mocks pass, seams break — and the harness that mocked the seam too

I was wrong in the same shape twice tonight, told the operator a third thing that was also wrong,
and the three together are the lesson worth keeping.

The setup was a green suite I trusted too much. Two store-resilience fixes had landed, the default
suite was 2163 passing, and I had — more than once — called the production path "verified" on the
strength of that number. Then the operator ran the only test that counts (lesson 2, again): he
booted the real thing. The window opened, he typed a prompt, and the Orchestrator answered
"Unsupported message type: PROMPT_REQUEST." A 2163-green suite, and the first sentence a human
typed broke it.

The cause was humbling in its smallness. The launcher wires the gateway to a port; in dev it
points at the Orchestrator on 5001 — which is why every prompt in every dev session and every test
had always worked — and in production host-mode it pointed at the Policy Agent on 5000. One branch
of one `if` in `launcher/__main__.py`, dev and production diverging on a single line, and the
gateway was handing every prompt to a service that does not handle prompts. Worse, the boot looked
healthy: an earlier fix had taught the Policy Agent to answer the cheap startup handshake, so the
gateway's "are you there?" succeeded against the wrong service and nothing complained until a real
prompt asked it to do a thing it cannot. A shallow gate certified a path the deep path did not
have; a downstream fix masked an upstream bug. The repair is a single source of truth — one
`resolve_gateway_port` that returns the Orchestrator's port for both dev and production, the
constant regression-locked against the service's own config so the two declarations of one
physical port can never drift again — and it was reproduced red before green: stand the real
Policy Agent on 5000, drive the real gateway at the pre-fix port, watch the handshake succeed and
the prompt come back rejected with zero tokens, then flip the port and watch it stream.

Then I made my own mistake, and it is the one I most want to keep. The operator asked how the UI
gets tested — "the window pops up and you click the buttons, right?" — and I told him, with the
confidence of a man who had just grepped, that the WinUI app has no automated tests at all. I had
scoped my check to the C# project and stopped. Before writing that into this journal I checked the
whole repository, and the claim fell apart: `tests/harness/` is a deliberate three-layer harness
(Vikunja #563, built a sprint ago — this is lesson 32's "the window I said we couldn't test,
tested"), with in-process dispatcher locks, real-model latency on the Arc GPU, and real pywinauto
UI automation driving the actual window. I had forgotten the very thing I was once proud of
building and nearly carved my ignorance into the permanent record. The lesson inside the lesson: a
claim about your own coverage is worth exactly as much as any other unverified claim — which is to
say nothing, until you have checked.

And the harness's existence does not rescue the night; it sharpens it. The routing bug slipped
past the harness too, for the same reason the unit tests missed it: every layer mocks the boundary
the bug lives past. The dispatcher layer drives a fake gateway, so the real gateway→Orchestrator
routing was exercised by nothing. The window layer drives a fake backend, so the GUI against the
real model-loaded path is not a tested path. An integration test that mocks the seam where the bug
lives has precisely the blind spot of the unit test beside it (lesson 3, in integration clothing).
Coverage is not how integration-flavoured a test looks; it is which seam it actually exercises —
and the one seam that mattered, the launcher's production port-wiring, was exercised by nothing at
any layer. A `slow` marker had even hidden two integration files of bit-rotted tests from CI
entirely; a test that does not run is not coverage, however green the suite that excludes it.

The operator's response reframed the whole night, and it is the governance lesson. He did not ask
me to fix the bug faster. He said every major aspect of BlarAI needs automated testing so
production is stable and development is fast with as little human in the loop as is reasonable. The
problem was never the bug; it was that finding it was a manual, one-at-a-time job that landed on
the most expensive tester on the project — him — because no test reached the integrated production
path. The fix for that is not another fix. It is a standard.

So the durable output of tonight is not the routing patch. It is `TEST_GOVERNANCE.md` §2.7: every
major subsystem has an automated test of its real integrated path that *exercises* the production
seam rather than mocking it; a subsystem is not "done" until that test exists, the same standing as
a journal entry; and minimal-human-in-the-loop is the design target, with manual testing reserved
for genuine visual judgment and nothing else. I placed it beside §2.5 (test in production posture)
and §2.6 (never touch real user data) as the third load-bearing clause. The trade-off on the
record: I could have left this as the tickets it spawned (#619 the production-parity boot lane,
#620 the routing fix and the model-loaded preflight gate, #621 growing the #563 window harness to
the full critical path against a real backend). Tickets get done when someone reads them; doctrine
binds every sprint. The operator pre-approved making it doctrine, because a blind spot this
structural is not a bug to fix — it is a class to outlaw.

**Next:** the routing fix lands — verified red-to-green in a new real-listener integration test,
with the launcher's model-loaded prompt preflight (which it already had, and had left disabled —
the very gate that would have caught this at boot) flipped on by default in production so the boot
fails closed with the model loaded before the window ever appears. Then I run that real generation
here, so the operator sees end-to-end proven in the harness rather than handed to him as a boot to
try; the coverage audit (#622) maps every major aspect to the fidelity that reaches its seam; and
the window harness grows from one fake-backed scenario to the full path against the real model. The
standard exists now; the burn-down is the work.

*(commits: `TEST_GOVERNANCE.md` §2.7 + this entry; routing fix on `worktree-agent-af96…` verified
red→green, merge-gate pending; harness `#563`; initiative `#622`, members `#619`/`#620`/`#621`.
Default suite 2163-green and blind to the launcher's production port-wiring at every layer, unit
and integration alike — the entire point. Lesson 56.)*


### 2026-06-06 — The night BlarAI first answered a prompt in production

Lesson 2 of this journal is *"Show me it running."* Tonight it ran. For the first time, BlarAI answered a real prompt in full production posture — TPM-sealed keys, per-boot mTLS, the dev-mode flip activated — on the operator's actual hardware: a prompt came back, a photo attached through the paperclip was described correctly, and the vision model evicted from RAM after the turn. That is the bar the whole air-gap campaign is built around ("production is the only 'works'"), met for the first boot.

It did not come easily, and the arc is the lesson. The dev→production flip turned on, and the first real boot failed — then the next, and the next — each on a different production-only seam that the green 2,163-test suite never touched, because the bugs lived in the seams the unit tests mock. The encrypted session store bricked on dev-era rows the new production key could not decrypt (one bad row → an app-wide "backend not running"); past that, the gateway rejected every prompt because the launcher had wired it to the Policy Agent's port and an earlier handshake fix had masked the misroute. Each fix got the boot one seam further and exposed the next — the exact whack-a-mole the operator named, and the reason he turned the night's real output into a standard (§2.7) rather than three patches. (The decrypt-quarantine and routing entries above carry each of those fixes in full.)

Two of my own missteps belong in here, because they are the parts worth showing. First, when the decrypt-brick surfaced I reached to *escalate* it — I handed the operator an A/B decision (reset the data vs. change the store's behaviour) as though a Sprint-14 regression test that asserted the buggy "brick the whole list" behaviour made it a posture I could not touch. He collapsed it in one line: *"Fix this so it doesn't keep happening — is there really more than one correct answer?"* There was not. A test can lock a *defect*, not just a feature, and "it's test-locked" is not proof "it's a decision" (lesson 66). Second, asked how the UI is tested, I told him with grep-confidence that there were no automated UI tests — and there is a whole three-layer pywinauto harness I had built a sprint earlier and forgotten. Verify-first caught that one before it reached the permanent journal; it is the cautionary half of lesson 56. Both mistakes share a root: I trusted what was in my head over what was on the disk.

The durable outputs landed and were merge-gated — the decrypt-quarantine posture, the single-source `resolve_gateway_port`, and the model-loaded prompt preflight now default-ON in production so the boot self-verifies the full prompt path with the model loaded, fail-closed, before the window ever opens. The next broken prompt path will fail a boot, not reach a person. And the operator closed the night on the discipline itself: make the journal entries now, leave no loss if the session ends. He was right to — this entry was the one thing still only in my head.

**Next:** second-boot continuity (does a plain re-boot stay clean), then the Sprint-15 close — fold every `2026-06-*` fragment into `BUILD_JOURNAL.md`, the SCR, the Auditor SWAGR, the ledger entry, and close #616. Then the campaign continues toward the #598 gate: Tier-3 egress, the deferred guest-boundary handshake (#615), weight integrity (#106).

*(live-verify boot-1 PASSED on real hardware, LA-confirmed 2026-06-06: prompts + vision + VLM-eviction. Fixes this sprint: decrypt-quarantine `4af2033`/`6fe1fcc` (#618), prompt routing `762fbf9`→`ecbd991` (#620) + model-loaded preflight default-on, coverage mandate `0834d44`/`8206800` (§2.7 + lesson 56). Fragment first recorded `f3d4411`; folded into the journal at Sprint-15 close. Lesson 66.)*



## Act II — The decision at the wall (Jun 7 – 10)

### 2026-06-07 — The recovery key was already there; what was missing was proof it works on a dead machine

Sprint 17, Stream K (C6, SECURITY_ROADMAP §5.5): "recover the at-rest DEK from
the offline recovery key after TPM/chip loss or hardware migration + a
tested-recovery lock (a fresh environment decrypts via the recovery key)." This
is gate-critical for #598 — the at-rest-encryption criterion's last open box.

I went in expecting to *build* the offline-recovery path and found it had shipped
in Sprint 14. `dek_envelope.py` already dual-wraps the DEK — TPM-sealed primary
plus an AES-256-GCM recovery wrap under a 256-bit off-box key — with
`unseal_via_recovery` (recovery-wrap-only, never touches the sealer),
`reseal_dek` (re-bind the *same* DEK to a new chip, no new DEK), and a
`provision_dek_keystore.py` ceremony carrying both `--rotate` and `--recover`
modes. The §5.5 tracker even records the *mechanism* as DONE. So the honest
framing of C6 was never "build the path" — it was "the mechanism exists but
nothing proves it survives the actual disaster it's for." That gap is the whole
point of the criterion, and it's the kind of gap this project has been bitten by
before: a green suite that mocks the boundary is not coverage of the boundary.

The tell was in the existing tests. Every one of them simulates "the TPM is
gone" by `monkeypatch`-ing a live `SoftwareSealer`'s `unseal` to raise mid-test —
the chip is "dead" but the same process that sealed the DEK is still running with
the sealing key one attribute-set away. That is not hardware migration. The
disaster the recovery key exists for is a *fresh environment on new hardware*
where the only artifacts that crossed the gap are the keystore file and the
recovery key, and there is no TPM anywhere that can unwrap the primary wrap at
all. None of the suite modelled that.

So Stream K is really two things: a small new module and the lock that was
missing. The module — `shared/security/recovery_key_store.py` — owns the
recovery-key *material*: generation, a human-transcribable encoding (bare hex,
dash-grouped, and a checksummed-grouped form so a mis-keyed nibble is caught on
re-entry before the all-or-nothing AES-GCM unwrap is even attempted), Fail-Closed
parsing, and a `redact()` that reveals only a length and a short fingerprint so a
recovery key can be referenced in a log line without leaking. The
64-hex-character validation had been living inline inside the ceremony's
`recover()`; centralizing it means the envelope, the ceremony, and any future
recovery tool parse the operator's input one way instead of three. I added one
method to my own file, `DekEnvelope.unseal_via_recovery_hex`, to close that loop —
the real break-glass UX hands the operator a *string*, not 32 raw bytes, and now
the envelope can be driven straight from that string through the validated
parser, re-raising the store's `RecoveryKeyError` as `DekEnvelopeError` so one
call site catches one type and no key fragment escapes through a differently-typed
error.

The lock — `tests/security/test_key_recovery.py`, 34 tests — models the dead
machine honestly. I wrote two stand-in sealers, `_NoTpmSealer` (raises
`TpmUnavailable`, the off-chip/no-provider case) and `_DeadChipSealer` (raises
`TpmSealingError`, the provider-present-but-key-absent case), so a test that
reaches the TPM branch fails exactly the way production would on the real dead
chip. The headline tests do the full arc: provision on machine A, carry *only*
the keystore file and the recovery key to a fresh machine B whose sealer cannot
unseal, and recover. Not just the DEK bytes — a real `FieldCipher` payload
encrypted on A decrypts byte-for-byte on B, because "a dead chip must not lose
decades of data" is a claim about *data*, not about a key comparison. Then the
migration completes: `reseal_dek` re-binds the recovered DEK to B's new TPM with a
fresh recovery key, the data is readable via the new fast path after a simulated
reboot, and the old recovery key is now rejected by the new keystore. The
fail-closed half locks the refusals: wrong key, all-zero key, no-key-and-no-TPM,
a foreign ciphertext the recovered DEK must *not* decrypt, and a tampered
recovery wrap on disk — all REFUSE, none returns plaintext.

The trade-off I want on the record: this is the **gate tier**, `SoftwareSealer`
standing in for the TPM, which is exactly what the SDV scopes C6 to ("green in
the gate (stand-in sealer)"). I deliberately did **not** expand scope to a
real-TPM recovery verification. A real chip would prove the RSA-OAEP seal/unseal
against the Platform Crypto Provider, which the software stub does not — but the
*recovery* path by construction never touches the sealer (it unwraps the AES-GCM
recovery wrap directly), so the stand-in exercises the recovery logic with full
fidelity; only the primary-wrap round-trip is stubbed, and that is already
covered by the ceremony's on-chip live-verify. I judged a real-TPM recovery test
genuinely worthwhile as a `@hardware`-marked on-chip item and flagged it for an
on-chip home rather than building it here — chosen over silently treating the
gate tier as the whole story, which would have been the dishonest version of
"done."

99 tests green from the worktree (34 new + the 65 existing field_cipher/
dek_envelope tests, confirming my envelope extension regresses nothing); the 20
`provision_dek_keystore` tests stay green too, and I confirmed no import cycle
despite `recovery_key_store` importing the key size from `dek_envelope` (the
back-reference is a function-local import). Isolation verified active: the root
conftest redirected `LOCALAPPDATA` to a throwaway temp dir and unset
`BLARAI_DEK_KEYSTORE`, so nothing in this stream went near the real keystore.

This earned lesson 78 — *mechanism-exists is not disaster-tested; the missing
catastrophe test is the actual deliverable.*

**Next:** the merge gate (re-run the standing gate, branch-guard before the
main-tree merge). For the gate's honesty column: the real-TPM recovery
round-trip is the `@hardware` follow-on — recover a keystore provisioned by a
real `TpmSealer` on a machine where that seal key has been deleted, proving the
break-glass path against the actual chip, not the stub. It belongs in the LA
on-chip batch, not the gate tier.


### 2026-06-07 — The briefing before the irreversible door

The operator drew a line under the #598 gate that I had drawn in the wrong place. I had #612 — the
capstone security presentation — sequenced *after* the gate, the way the ticket body read it: an
after-the-fact "here is the verified AFTER posture" bookend to the 2026-06-03 audit deck. He corrected
it: #612 is his **real deep-dive into the residual risks of removing the air-gap, even after all the
hardening** — and it comes **before** he signs off, not after. He wants the thorough presentation, he
wants to ask questions, and he wants any work that surfaces during the Q&A *tasked and resolved* before
the air-gap comes down. The sign-off is not a rubber-stamp at the end of an automation run; it is a
decision he makes only once he understands what he is deciding.

That is the right governance shape and I had it backwards. Removing the air-gap is the single biggest
threat-model shift in the project — the one irreversible-feeling door — and the human who owns that
go/no-go should take his understanding pass *before* the decision, with a remediation loop so his
questions can still change the outcome. A capstone scheduled after the gate can only explain a decision
already made; scheduled before it, it can still stop or reshape it. The #612 ticket's eight must-cover
requirements were already strong; what was wrong was the timing and the role. Recorded as a new gate
criterion (SECURITY_ROADMAP §5.13, the sign-off precondition), §5.12 amended to depend on it, §4 sequence
updated, and both the #612 and #598 tickets amended. The emphasis for whoever builds #612 also sharpened:
the residual-risk register + the network-facing threat-model scenarios are the heart of it, not the
victory lap.

**Next:** unchanged for Sprint 17 (the Boot Cluster wave is in flight; this is gate-sequence, not
Sprint-17 scope). Sprint 18 = the pre-gate automation sweep; then the #612 capstone phase (build →
present → LA Q&A → resolve surfaced work); then the #598 sign-off.

*(commits `452ac98` (§5.13 + the #612-before-#598 amendment) + `021ffda` (the §4 capstone-phase
restructure); the #612-gates-#598-sign-off gate sequence, LA-directed 2026-06-07. Earned lesson 85;
folded from journal fragment at the Sprint-17 close.)*


### 2026-06-08 — The on-chip session I told the agent to make the operator run

The Sprint-17 hardware tiers needed a live chip, and the SDV had them as an "LA on-chip session" —
runbooked, Orchestrator-driven, one command at a time. I handed that framing to the execution agent
verbatim and drafted the operator a "guide me through it, give me the first command, I'll paste each
output back" kickoff. He stopped me cold: *"It's having me do testing! Why would it do that? All testing
should be automated. My time is being wasted, again."* He was right, and the root cause was an assumption
nobody had re-checked. The "LA-driven, one-command-at-a-time" script is correct for exactly one situation
— a *guiding* session with no path to the hardware (which is what I am). The *execution* agent was running
on the dev box with full shell access; it could run every one of those commands itself. The framing
carried the "operator runs X, pastes Y" phrasing through four layers — the runbooks, the SDV §7 on-chip
track, the execution brief, my kickoff message — and at no layer did anyone ask whether the agent
executing it could simply do the work.

The fix is a standing principle, not a patch: an agent on hardware it can reach runs every step itself,
and a step is routed to the human *only* when proven to need human hands — an OS-level elevation the shell
cannot obtain, a physical action, an irreducible presence assertion — never because a runbook is phrased
for a human operator. Where the blocker is one-time access (shell elevation), it is obtained once, not
routed through the human each command. The burden of proof sits on routing a step *out* to the human, not
on automating it. The agent self-corrected immediately and ran the entire on-chip session itself — the
FUT-04 ceremony, the boot tiers, the model-loaded cascade, the screen-driven GUI harness — surfacing only
results. The operator's later clarification sharpened the boundary: by "testing" he means *all* automated
verification of any kind is the agent's, including the screen-taking GUI harness once he has cleared the
screen; his own role is the occasional hands-on verification of a major feature, which is a different act
from running a test suite.

**Next:** the on-chip doctrine reframe is tracked as Vikunja #629 — propagate the automate-first /
human-exception principle across BlarAI CLAUDE.md, the SDV §7 on-chip template, the runbooks, and the
devplatform operating-model — so no future sprint inherits the "operator runs it" fiction. Sprint 18 (the
pre-gate automation sweep) is authored under it: every tier the fleet can reach, the fleet runs.

*(commit `<this>` — the BUILD_JOURNAL fold of the Sprint-17 governance + on-chip-guidance lessons; the
automate-first reframe, Vikunja #629, LA-surfaced 2026-06-08. Earned lesson 86.)*


### 2026-06-08 — The after-bookend, and the audit you have to be honest about

The #612 capstone deck is the closing bookend to the 2026-06-03 security audit: where that
deck showed "safe by environment, not yet by construction," this one shows how much of that
gap is now closed by construction — and, more importantly, what still is not. It is the Lead
Architect's pre-sign-off deep-dive for removing the air-gap (#598), so its whole value is
honesty: a deck that oversells the posture would get the gate decision wrong.

The load-bearing chunk was the reconciliation — \~55 audit findings plus the 12 headline
attack paths, each needing a *current* status rooted in the code on disk today, not inherited
from a narrative. I fanned that out to five read-only verifier subagents (one per domain
cluster) returning structured status + evidence, while I personally nailed the credibility
spine: `git ls-files certs/` is empty and commit `23b2802` rotated the cleartext signing key
onto the TPM (the audit's one Critical, closed); the manifest is TPM-signed and verified at
boot; production resolves dev-mode off by default; the live `substrate.db` is ciphertext.

Two verifiers disagreed, and that disagreement was the most valuable thing the parallel pass
produced. One read the tool-call allowlist as FIXED (pruned to the four built tools); one read
it as STILL-OPEN (ten unbuilt names). Resolved on disk: the ten names live only in a
removal-comment; the active allowlist is four. The second disagreement — the exfil-screen —
resolved to a truth sharper than either verifier's: the screen is built, unit-tested, and the
launcher even imports it, but it never actually self-registers onto the armed guard, so it is
*doubly* dormant (empty allowlist AND unwired screener). That is exactly the kind of "built is
not the same as wired, which is not the same as proven" nuance the deck exists to surface, and
I would have missed it on a single serial pass that committed to the first plausible reading.

The honesty discipline that holds the deck together is a four-grade scale on every claim —
VERIFIED-LIVE / TESTED / BUILT-DORMANT / DESIGNED-DEFERRED — so "we built it" can never
masquerade as "it works in anger." The shape that fell out: the audit's one Critical and most
of its Highs are FIXED by construction (24 of 55 findings), but the controls that matter most
for going *online* — the egress guard, the kill-switch, the exfil-screen — almost all grade
BUILT-DORMANT. They are real, armed on every boot, and have never once run against external
traffic. The deck says so on the heart slides, in those words.

One tooling decision worth keeping: I authored the deck outline from a small Python source
script using triple-quoted mermaid (real newlines, quoted labels) rather than hand-escaped
JSON. The audit build needed a `fix_diagrams.py` post-pass because hand-escaped mermaid carried
literal `\n` and unquoted labels into parse errors; emitting the JSON from Python made the
diagrams correct-by-construction, and all nine parsed clean on the first run of the real mermaid
parser (both in the outline and as embedded in the built HTML).

**Next:** a separate session presents this to the LA for the #612 deep-dive Q&A; any work that
surfaces gets tasked and resolved before the §5.12 sign-off. The deck itself flags the pre-gate
items that pass should weigh: the guest-profile file-level hardening (still literally
`dev_mode=true` though the interlock neutralizes it), wiring the exfil-screen onto the live
guard, the 30s-vs-5s token lifetime, and the audit-retention decision (#607).

*(commit `<this>` — `docs/security/capstone_2026-06/` deck: 45 slides, 9 diagrams, all
parser-clean; reconciliation 24 FIXED / 5 MITIGATED / 3 BUILT-DORMANT / 15 ACCEPTED-RESIDUAL /
8 STILL-OPEN; both Critical expressions CLOSED at `23b2802`. Awaits the LA #612 deep-dive + the
§5.12 sign-off.)*


### 2026-06-09 — The replay window between two correct components

The ticket (#638) handed me three capability-token containment fixes and named
the mechanism for one of them. Two of the three were exactly as described. The
third was wrong in an instructive way, and catching it is the whole lesson.

The Policy Agent mints short-lived ES256 capability JWTs; every other service
validates them. #638 asked me to (1) drop the token lifetime from 30s to 5s,
(2) add a `jti` spent-set to enforce single-use against replay, and (3) wire a
real `revoke()` caller for the epoch-bump that already existed but nothing
called. I built all three on a feature branch — including the `JtiStore`, a
TTL-evicting spent-set mirroring the existing `NonceStore`, with its own
validation stage and a full test group.

Then the guide — who had been reading the same token code while I built —
course-corrected: **don't add the jti set, it's redundant.** And the evidence
was right there in `jwt_validator.py`. Single-use was *already* enforced, by the
**nonce**, not by `jti`. Every minted token carries a unique 128-bit nonce
(`jwt_minter.py:294`); Stage 4 of the validator rejects any token whose nonce is
already in the seen-set. A replay is the same nonce, so it's already rejected.
The `jti` claim is minted but needs no separate machinery — the nonce does the
job. The ticket's "jti spent-set" wording had been inherited from a security
deck that described the *property* (single-use) and guessed at the *mechanism*.
I had taken the mechanism literally and built a second control that removed
nothing and duplicated a working one.

So I tore the `JtiStore` back out — class, wiring, stage, and its tests — and
went looking for the **real** single-use bug, because there was one, and it was
subtler than a missing set. `NonceStore`'s default TTL is 5.0s. The token
validity was 30s. Those two numbers are defaulted *independently*, in different
files, and nobody had ever made them agree. The validator GC-forgets a nonce at
5s while the token stays valid to 30s — so a token replayed in the **5–30s
window** finds its nonce already evicted (passes Stage 4) and not yet expired
(passes Stage 2). The single-use guarantee had a 25-second hole in it, and it
existed precisely *because* the two components were each individually correct: a
5s nonce-seen window is a fine default, and a 30s token is a fine token, but the
seam between them was never specified. The fix isn't a new control — it's tying
the two values together so they can't drift: `aligned_nonce_ttl(validity) =
validity + skew_margin`, threaded through the validator, so the seen-window
provably outlasts the token. I promoted `JWT_VALIDITY_SECONDS` to
`shared/constants.py` as the single source of truth both the minter default and
every destination validator read, so "5s" lives in one place now, not three.

A second finding fell out of the wiring: I'd assumed both the PA and the AO were
live validators and started to thread validity through both construction sites.
But the PA's `from_public_key_file` call is a *boot-time cert-loads check* that
discards the validator — the PA **mints**, it never validates at runtime. The
only live destination validator in the whole system is the AO's
`_build_jwt_validator`. That's the one place the alignment actually had to land,
and the one place a test had to lock it. Sizing the AO's nonce window to
`JWT_VALIDITY_SECONDS` is the fix that closes the window on the real system.

The two fixes the ticket got right, I kept: validity 30→5 in both PA configs
(this was the one piece failing genuinely OPEN — the config value overrides the
already-correct 5s constant at runtime), and a real `revoke()` on the minter
that bumps the epoch so every prior-epoch token is rejected at the validator's
Stage 3. The revoke mechanism was built long ago; it just had no caller. Now it
does.

I kept one deliberately-failing test, `test_old_default_would_have_leaked`,
which constructs the *old* shape (a too-short nonce store under a long-lived
token) and asserts the replay is **accepted** — documenting the exact bug the
alignment removes, so if anyone ever lets `aligned_nonce_ttl` return less than
the validity, the contrast test that sits beside it will fail loudly.

Eighteen regression tests, gate green (2342→2360), nothing merged — the guide
re-runs the diff and lands it. The lesson I'm keeping: when a ticket names the
*mechanism*, verify the mechanism against the code before you build it. The
property it's protecting may already hold by another means, and the real defect
may be hiding in the seam between two parts that are each, on their own,
perfectly correct.

**Next:** the guide reviews the `feat/638-token-containment` diff, re-runs the
standing gate on the elevated/model-present box (expecting 2360/0/116), and
merges. After merge, #638's containment limb is closed; the remaining pre-online
token-hardening thought is whether epoch revocation wants a persisted/operator
surface (a CLI or kill-switch binding for `revoke()`) rather than just an
in-process entry point — worth a ticket if the network-facing future (per the
threat-model-shift note) gets closer.


### 2026-06-09 — The screen that would have strangled the host it guards

#634 asked for one line: register the exfil-screen onto the armed egress guard.
Taking the ticket literally would have welded a noose. The egress guard screens
every guarded send, and BlarAI's internal IPC — the loopback PA→AO gateway and
the AF_HYPERV vsock — legitimately carries the runtime's own capability JWTs and
the user's PII. The exfil-screen flags exactly those. So `register_screener(
exfil_screen.screen)` as written would have tripped the kill-switch on the first
internal message and cut ALL egress, loopback included: a self-inflicted denial
of service dressed as a security control. The existing seam tests even *proved*
the old behaviour (a screener fires on a loopback send) — they were locking in
the very thing that would have hung the system once a real screener was wired.

The fix was to scope the screen to what actually leaves the box. The guard now
tags a socket for screening only after a successful connect to an external-
allowlisted endpoint; loopback and vsock are never tagged, and accept()/dup()
sockets never tag. With the external allowlist empty — today's welded air-gap —
nothing is ever tagged, so the wired screen is a behaviour-free no-op until the
first Kagi endpoint is allowlisted at W4. The wiring is in place and correct for
that day; it changes nothing before it.

A second trap surfaced during the build that the ticket never hinted at. The
guard's verdict normaliser understood `ScreenResult | bool | None`, but the real
`exfil_screen.screen()` returns a `Detection` — a frozen dataclass, and therefore
always truthy. The old normaliser's "any other truthy value is a detection"
fail-closed branch would have read a *clean* `Detection(blocked=False)` as a
positive hit and blocked the first clean external send. So the obvious wiring
would have hung the system in two independent ways — one on internal traffic, one
on clean external traffic. The normaliser now duck-types `detected`/`blocked`
explicitly rather than by truthiness, and carries the real label through to the
trip reason. Merged `651ef4a`; the standing gate re-run on clean main is green at
2372 passed / 2 skipped (+14 tests; the two skips are the elevation-gated symlink
tests, not a regression).

The same sitting also saw the Lead Architect walk back a bar he had raised hours
earlier: #640 (named-pipe peer authentication), elevated to gate-blocking that
morning, was suspended pending more thought. Worth recording without varnish — a
conservative reviewer is allowed to un-raise a bar as well as raise one, and the
gate record should show the motion in both directions, not just the ratchet.

**Next:** the exfil-screen is wired and dormant; #643 (the broader non-loopback
egress activation-proving) and #639 (the ESCALATE inline-confirm consumer, the
LA's Windows-Hello design) are the live egress/PA gate work. #637's data-map
tidy-ups (action 2 & 4, document 3 & 5, build 1 owner-preserving) are dispatched
next.


### 2026-06-09 — Reading the silicon instead of guessing it

The #611 live-memory feasibility study left exactly one question it could not
answer from public sources: does this chip - an Intel Core Ultra 7 258V (Lunar
Lake) - expose Intel Key Locker? Key Locker wraps the AES key into a CPU-internal
handle so the raw key never sits in readable RAM, and it was the headline
candidate mitigation for the live-memory threat. Public datasheets confirm it on
Tiger Lake through Raptor Lake and say nothing about Lunar Lake, which is a
deliberately feature-trimmed design - so inference was not safe.

So I read the silicon directly. A self-contained CPUID probe
(`scripts/probe_keylocker.py`) - a tiny machine-code shim written into executable
memory and called through ctypes, no compiler and no install - self-validated
against the vendor string and the AES-NI bit before trusting anything, then read
`CPUID.(7,0).ECX[23] = 0`. Key Locker is NOT exposed on this silicon. That limb of
#611 closes for good, not "deferred pending a check." It is also novel data:
nothing public stated this for Lunar Lake, and the User-Operator is an upstream
Intel / OpenVINO contributor, so the probe is re-runnable and shareable - the
measured values are baked into the script's header.

The judgment worth keeping is small but real: when a security decision hinges on a
hardware capability and the public record is silent, a five-second read of the
actual chip beats an afternoon of inference - and the agent on the box can simply
do it rather than route it to the operator. It also sharpened the #611 verdict
from "low feasibility, two reasons" to "dead end here, three reasons" (blocked in
pure Python, wrong-shaped for the threat, and now absent in hardware).

**Next:** Key Locker is off the #611 table on this hardware. The remaining #611
mitigations the study scoped - embedding-cache idle-unload, best-effort owned-
buffer zeroization, OS page-locking - stand as the post-#556 window-reduction
work, none of them hole-closing.


### 2026-06-09 — The PCR seal, and the door Windows wouldn't let me forge

*Plain summary: a raw-TBS TPM2 PolicyPCR seal/unseal proven on the discrete STMicro TPM (Pluton is present but not the TPM-role chip); the Windows-blocked user-mode `PCR_Extend` reframed as the property itself, the negative test done by sealing a second object to a different PCR value; `shared/security/verify_pcr_seal.py` PoC, #627.*

The ask was four words: "test Pluton PCR-seal." The first useful thing was to not
take them literally. The premise — that Pluton seals to PCRs on this box — has been
false and documented-as-false since 2026-06-03: Pluton is present
(`PCI\VEN_8086&DEV_A862`) but the TPM 2.0 role is filled by a discrete
STMicroelectronics chip, which is what `TPM_CAPABILITY_FINDINGS.md` was renamed to
say. BitLocker already proves PCR-sealing works here (PCR7 bound), and yesterday's
trust-root run proved BlarAI's own keys are chip-resident and functional. So the
honest target wasn't "Pluton" — it was the one PCR claim the repo had carried as
*feasible but unproven*: that BlarAI can seal a secret under a PCR **policy** and
have the chip refuse to unseal it when the measured state differs. That last clause
is the whole point of measured boot, and it had never been exercised on the metal.

The build is a raw-TBS TPM 2.0 probe, deliberately not the CNG path the rest of
`shared/security/` uses — the Microsoft Platform Crypto Provider wraps keys but
won't express a *data object sealed under PolicyPCR*, so I hand-marshalled the
TPM2 command bytes over `tbs.dll` (stdlib ctypes, no new dependency, and as it
turned out, no elevation). CreatePrimary in the NULL hierarchy, a trial session to
compute the PolicyPCR digest, Create the keyedhash sealed blob, Load, then a real
policy session to Unseal. It came up green on the first genuinely-end-to-end run:
the secret sealed to PCR 23's current value unsealed and round-tripped byte-for-byte.

The negative test is where it got interesting. My first design was the dynamic one —
extend the live PCR, watch the same object refuse to open. The TPM said
`TPM_E_COMMAND_BLOCKED`. Windows TBS blocks a user-mode `PCR_Extend` outright. My
reflex was "find the way around it"; the right read was the opposite. That block is
not in my way — it *is* the property I'm trying to prove. A measured-boot seal is
only worth anything because a process cannot reach in and forge PCR state through the
OS, and here was Windows enforcing exactly that, in my face, with an error code. So I
stopped trying to mutate a PCR and proved the binding the clean way instead: seal a
second object to a *different* PCR-23 value and show it will not open in the current
state. Same enforcement, and it mutates no PCR at all — the PoC only ever reads PCR
23. The chip refused the mismatched object with `TPM_RC_POLICY_FAIL (0x09D)`, and the
two objects' policy digests are asserted to differ so the refusal can't be hand-waved
as binding-to-garbage. The blocked extend went into the record as a finding, not a
footnote.

Everything stayed transient and throwaway by construction — NULL-hierarchy parent,
transient sealed objects, an `os.urandom(32)` secret that is never a real key, PCR 23
(the resettable Application-Support register, no boot measurement) read but never
written. Two consecutive runs both returned DEMONSTRATED with no TPM slot leak. The
"feasible, not proven" caveat in `TPM_CAPABILITY_FINDINGS.md` §2/§3 and the
"Not measured: PCR-binding" line in the trust-root artifact can now both be retired.

**Lesson 197:** *When the platform refuses your test action, the refusal may be
the very property you set out to prove — reframe the block as evidence, don't engineer
around it.* I almost spent the session fighting `TPM_E_COMMAND_BLOCKED` instead of
recording it as the thing that makes a PCR seal trustworthy in the first place. Pairs
with verifying the premise before building: the literal task named the wrong chip, and
the literal negative test named the wrong obstacle, and both corrections came from
reading what the system was actually telling me rather than what the brief assumed.

**Next:** a harden-or-leave decision for the LA — promote `verify_pcr_seal.py` to a
committed, `@slow`-locked verification tool in the `verify_trust_root.py` mould
(re-runnable at every gate / hardware generation), or leave it as the standalone PoC
it is now. Either way, *binding the production trust-root keys to PCRs* remains the
separate ADR-028 / #627 measured-boot-attestation decision this run de-risks but does
not make. This proves the primitive on the hardware; it does not open #598.

*(artifact: `shared/security/verify_pcr_seal.py` + `docs/security/pcr_seal_poc_2026-06-09.{json,md}`;
uncommitted PoC pending the harden-or-leave call; Vikunja #627; references ADR-018, ADR-028,
`TPM_CAPABILITY_FINDINGS.md`, `trust_root_verification_2026-06-09.md`.)*


### 2026-06-10 — The door we cut into the wall

For its whole life BlarAI has been air-gapped by *absence*: no runtime module imported a network
client, and the `egress_guard` welded that shut at the socket layer so even a stray `connect`
auto-tripped a latched kill-switch. The Lead Architect has now decided to remove the air-gap (the
#598 GO), and the first thing that wants to reach out is UC-003 — read a URL, clean the article,
hand back text. The temptation, when you add a network feature, is to let *that* feature open *its*
socket. I built the opposite: one door. `shared/security/guarded_fetch.fetch_external` is the single
sanctioned external-fetch path, and every future web tool fetches through the same guarded seam. The
wall isn't torn down; we cut exactly one opening and put a guard on it.

The guard runs ADR-027's four rules as a strictly-ordered, fail-closed pipeline: an SSRF check
(https only, no `userinfo@`, no raw-IP hosts, no loopback/private/link-local/CGNAT, ports locked to
443 + an explicit 8443), then the Policy Agent's per-URL verdict, then a charset-correct fetch behind
a per-fetch allowlist widen that is *always* auto-revoked, then an injection scan of the body. The
load-bearing posture the LA handed me is "URL = authorization": when the operator initiates a fetch,
the PA verdict governs and that verdict alone — ALLOW proceeds with **no** extra fingerprint, DENY
blocks, and only ESCALATE routes to the #639 Windows-Hello consent path. I had to resist the reflex
to bolt a mandatory consent onto every ALLOW; the reason it's wrong is subtle and worth keeping. A
fingerprint on every fetch trains the operator to rubber-stamp, which corrodes the exact signal the
ESCALATE tier exists to carry. So consent is reserved for the tier the PA *escalates*, not levied as
a blanket tax. That's rule 2's "held hybrid-consent option" from the original ADR finally being spent
— and I recorded it as an ADR-027 amendment rather than letting it live only in code, because it is a
governance decision (where the human gate sits), not a mechanical one.

Two implementation decisions inside the door earned their own scrutiny. The first is the
registration seam. `shared/security` is leaf-level and must never import the Policy Agent service, so
the door takes its adjudicator by registration — `register_url_adjudicator`, mirroring exactly how
`egress_guard` takes its screener and `escalation_consent` takes its verifier. The consequence I
chose deliberately and flag loudly: `guarded_fetch` ships with **no** adjudicator wired, so today
every fetch DENIES. There is no honest in-process callable shaped `(url, purpose) -> verdict` to
register against — the PA classifies a Canonical Action Representation, not a URL string — so the
alternative was to fabricate a verdict in runtime code, and fabricating a verdict is a silent open
door. Better a documented TODO that the UC-003 caller wires the real PA (build a CAR, run
`HybridAdjudicator`, map `AdjudicationDecision` onto the local `Verdict`) than a stub that says ALLOW
when nobody asked the PA. The seam is real; the verdict is not faked.

The second is the one that would have auto-tripped the kill-switch on the very first real Kagi
connect, and it's a good example of a control fighting the thing it's supposed to permit. A standard
HTTP client resolves a hostname via `getaddrinfo` and then connects to the **numeric IP** it got
back — and that IP is not the literal string on the allowlist, so the guard would see an off-allowlist
destination and cut all egress. The fix (salvaged and verified from two prior stranded drafts) is
hostname-resolution pinning: when an *allowlisted* name resolves, `egress_guard` records its resolved
IPs (`ip → {hostnames}`) and admits a later numeric connect to one of them — but only at the
allowlisted port, and only for an IP that an allowlisted name genuinely resolved to. Deny-by-default
survives intact: an IP nobody resolved has no pin and still trips. The pin is not a second allowlist;
it's a memory of a legitimate resolution, dropped the instant the endpoint is revoked, the allowlist
cleared, or the guard disarmed — and a pinned-IP connect still tags the socket so the exfil screen
fires on real outbound bytes. I also made the body decode honor the page's *declared* charset
(Content-Type, then `<meta charset>`), not a blind UTF-8 assume, because a page that sends ISO-8859-1
or Shift_JIS is not a hypothetical and a blind decode mangles it.

One thing the building of the door forced was a deliberate, reviewable nick in a foundational
control. `tests/security/test_no_external_egress.py` fails the build on *any* runtime import of a
network client — that's how the air-gap is proven, not assumed. `guarded_fetch` must import `httpx`.
Rather than weaken the scan, I carved out exactly that one file by path and added a companion test
asserting the carve-out is one file wide and that the file imports *only* `httpx` — so the single-door
property is now itself locked by a test, and a second module reaching for a network client trips the
build just as before.

**Next:** the UC-003 URL-mode wiring consumes this — it must call `register_url_adjudicator` at its
entry point with a callable that runs the real Policy Agent (CAR → `HybridAdjudicator` →
`AdjudicationDecision` → `Verdict`), and an operator surface must register a Windows-Hello verifier so
ESCALATE actually prompts rather than failing closed to DENY. Until both are wired the door stays
shut, which is the correct dormant state. The live-verify that matters is the first real PA-ALLOWED
Kagi fetch on the box: confirm the resolution pin admits the connect at 443, the exfil screen tags
and screens the real outbound traffic, and the allowlist is empty again the instant the fetch
returns.

*(commits `b7471dd` (D1 resolution-pinning, 21 tests + #643 11/11 unchanged); `663c7fa` (D2
`guarded_fetch` one-door seam, 38 tests + the single-door import lock); D3 ADR-027 Am.1 + DECISION_REGISTER
+ this fragment. Awaits the UC-003 caller wiring the real PA adjudicator + a Windows-Hello verifier, then
a live Kagi-fetch verify on the box.)*


### 2026-06-10 — Three things the merge gate caught before the door ever opened

A merge-gate review of the door — done while it is still DENY-by-default, so nothing here was ever
live — surfaced two real defects and one gap, and I closed all three before the door can be wired
live. Reviewing your own freshly-cut hole in the wall, with fresh eyes, is exactly when the cheap
catches happen; doing it before the adjudicator exists meant zero exposure window.

The real one was an SSRF the first layer half-closed. `_validate_url` refuses a raw-IP *literal*
host, but a **named** host that DNS-resolves to an internal address sailed straight through, and
`egress_guard._record_resolution_pins` pinned *every* resolved IP except loopback — so a name pointed
at `169.254.169.254` (the cloud-metadata classic), a `10.x`/`192.168.x` box, or `100.64.x` CGNAT got
its internal IP pinned and the connect admitted. I closed it in both layers, deliberately, for defense
in depth. In `egress_guard` the pin recorder now skips *any* blocked range, not just loopback (a new
`_is_blocked_pin_ip` mirroring the door's own predicate): an allowlisted name that resolves internal
simply gets no pin, so the later numeric connect stays off-allowlist and the guard denies and trips.
In `guarded_fetch` I added a pre-fetch resolve-and-recheck: before widening the allowlist, the host is
resolved once and the whole fetch is refused if *any* returned address is blocked — and this one also
catches a name resolving to **loopback**, which the guard permits globally for IPC, so the door has to
refuse that itself rather than lean on a guard that is (correctly) lenient about 127.0.0.1.

A wrinkle worth keeping: the tests had been using RFC-5737 documentation IPs (`203.0.113.x`) as stand-in
"public" addresses, but Python 3.11's `ipaddress` classifies those ranges as `is_private` — so once the
blocked-range skip went in, the happy-path pins stopped recording and the suite went red in a way that
*looked* like a regression but was the new control working. The fix was to move the public-path test
constants onto a genuinely-global address. The lesson there is small but real: a "documentation" IP is
not automatically a "public-for-classification" IP, and a security predicate will tell you so.

I did **not** fully close DNS rebinding, and I wrote that down rather than imply I had. The pre-fetch
recheck and httpx's own connect-time resolution are two separate lookups; a rebinding attacker can
answer the check with a good IP and answer the connect with a bad one (a TOCTOU). The resolution-pin
layer narrows it — httpx connects to a numeric IP that must be pinned by an allowlisted name, and an
internal IP is never pinned now — but the robust close is a custom httpx transport that validates the
*actually-connected peer IP* against the blocked ranges before sending. I named that as a follow-up in
the module docstring and here, and deliberately left it out of scope: it is a real piece of work, not a
one-liner, and shipping it half-built would be worse than naming it honestly.

The second defect was a memory-exhaustion DoS hiding in plain sight. `_fetch_body` did
`response.content[:_MAX_BODY_BYTES]` — but `client.get()` reads the *entire* body into memory before
that slice ever runs, so the 8-MiB cap was decorative: a hostile (PA-allowed) host streaming gigabytes
would exhaust host memory before the cap applied. I switched it to `client.stream("GET", url)` and read
chunks up to the cap, stopping the instant it's reached so the unread remainder is never pulled in. An
over-cap body is truncated-at-cap and logged WARNING, never raised. One small trap cost a test cycle:
httpx forbids re-iterating a consumed stream, so the "is there more past the cap?" peek had to advance
the *same* iterator with `next()`, not call `iter_bytes()` a second time. Everything else — status,
content-type, charset-correct decode, the always-revoke `finally`, the trip/timeout/HTTP-error handling
— is preserved.

The third was a gap, not a bug: `_scan_and_annotate` logged the injection-scan flags but `FetchResult`
had nowhere to carry them, so the UC-003 cleaner could never act on them — they died in the log. I
added `injection_flags: tuple[str, ...]` to the frozen result and populate it from the scan via
`dataclasses.replace`. The annotate-not-block contract is unchanged (the body is returned intact
regardless); the consumer can now *see* the flags and decide, which is the whole point of a
defense-in-depth signal.

**Next:** unchanged from the door's first entry — the UC-003 caller still wires the real PA adjudicator
and a Windows-Hello verifier, and the live Kagi-fetch verify on the box still gates going live. The one
addition to that punch-list: build the **peer-IP-validating httpx transport** to close the DNS-rebinding
TOCTOU before the door is ever wired live (a named follow-up, ticketed against #577's egress hardening).

*(commits `0a3fc04` (fix 1 — named-host SSRF, both layers; +TestBlockedRangeResolutionNotPinned +
TestNamedHostResolutionSsrf); `ca3eca4` (fix 2 — streamed body cap; +TestBodyCapStreaming); `36128c0`
(fix 3 — `injection_flags` on `FetchResult`; +TestInjectionFlagsSurfaced). Standing gate green; the
#643 sandbox 11/11 and the one-door import lock both unchanged. Residual: peer-IP-validating httpx
transport for the DNS-rebinding TOCTOU — named follow-up, not built here.)*



### 2026-06-10 — The encrypted store that kept a plaintext fingerprint of its own contents

An independent LA-session verification of the knowledge-bank branch (LA
verdict 2026-06-10) caught something I had shipped without seeing: the
`knowledge_docs` table stored the SHA-256 of the full cleaned plaintext as a
plaintext `content_sha256` column — sitting directly beside the AES-256-GCM
ciphertext it fingerprints — and the signed-plaintext ingest audit log carried
the same digest as `car_hash`. Every individual piece had a justification
(the digest powers the staging integrity cross-check; the audit chain wants a
content reference; "it's only a hash"), and the composition was still wrong.
Under the stolen-DB threat model a deterministic content hash IS content
metadata: an attacker holding `knowledge.db` runs any public article through
the deterministic in-repo cleaner, hashes the output, and tests membership —
which is exactly the attack the keyed `source_hash` two columns away was
designed to deny. The store denied "did he ingest this URL" while answering
"did he ingest this article" for free. The embarrassing part is the proximity:
the right pattern was already in the same CREATE TABLE.

The fix is the pattern the table already knew. `content_sha256_keyed` now
stores `cipher.keyed_index` (HMAC under `k_idx`) over the plaintext digest
hex — same ADR-025 §3 equality-leak residual as `source_hash`, unguessable
without the key. The verification capability cost is zero, and that is the
part worth recording: the AO's integrity cross-check (recompute the SHA over
the decrypted staging plaintext, compare against the INGEST_SUBMIT frame's
digest) runs in RAM BEFORE the insert, exactly as before. Only the at-rest
form changed. The rejected alternative — encrypting the digest instead of
keying it — would have cost the deterministic-equality property for nothing;
nobody ever needs the plaintext digest back out of the row.

The audit limb was a delegated sub-choice (the LA handed it to the
orchestrator) and the call was KEYED there too: `car_hash` on ingest records
is now the keyed hex, because a plaintext content digest in a signed-PLAINTEXT
JSONL file would simply re-open the same oracle one directory over. ADR-029's
ratified plaintext exception covers action/identity labels — verbs, doc
UUIDs, decisions — never content-derived hashes; the decision is now written
into both module docstrings so the next reader inherits the boundary, and
DATA_MAP row 8 got the honesty pass it needed: the old claim that
`published_date` was "the one deliberate plaintext metadata column" was false
(word_count, cleaner_version, timestamps, lifecycle state were all plaintext
too), and the row now points at a full per-column enumeration with a
one-line rationale each. A data map that flatters the store is worse than no
data map. Regression locks: raw `knowledge.db` bytes and the audit JSONL
bytes are scanned for the plaintext digest of a known ingested article
(absent, in every spelling), the keyed form is asserted present, and a
genuinely tampered staging file (validly re-encrypted different content under
the same doc identity) still bounces off the cross-check.

The same verdict landed a second, unrelated decision: the LA INVERTED the
launcher's zero-NIC posture from assumption to precondition. The guest VM
must remain NIC-less under the one-door host-side-fetch composition, so
`start_vm` now enumerates the VM's adapters (`Get-VMNetworkAdapter`, the
existing `_run_ps` pattern) and refuses fail-closed — before Start-VM, and
deliberately also for an already-RUNNING guest, because a running VM with an
adapter attached is the violation itself, not a grandfathered state. An
enumeration failure refuses too: "could not check" is not "checked clean".
Mocked tests cover zero-proceeds / one-refuses / error-refuses, plus the
never-issued-Start-VM assertion on the refusal paths. The check is
self-contained in `vm_manager.py` so it composes cleanly with the #657
stop-on-exit work that landed on main after this branch forked.

**Next:** fold this into the #655 merge-gate review; the UX-side twin of this
finding (the /ingest paste persisting into sessions.db as a forwardable user
turn) is fixed on the stacked `feat/uc003-ingest-ux` branch with its own
fragment.



### 2026-06-10 — The lock I proved, then declined to fit

A proof-of-concept on 2026-06-09 had closed a long-standing "feasible but
unproven" caveat: it sealed a secret under a TPM `PolicyPCR` on this exact chip
and watched the silicon refuse to unseal it when the bound PCR value differed —
measured-boot key-binding *enforces* here, it does not merely decorate. The
natural reflex on a green capability proof is to reach for it. The LA did the
opposite, and correctly: on 2026-06-10 he decided the production trust-root keys
will **not** be PCR-bound.

The reasoning is the part worth keeping, because "we proved it works and chose
not to use it" is a stronger governance position than either "we couldn't" or
"we did it because we could." PCR-binding a *key* is the strongest form of
measured boot — the key itself will not open outside a known-good boot state —
and that strength is exactly its operational poison on a decades-use daily
driver: PCR values move on every legitimate firmware and OS update, so a
PCR-bound trust root would brick itself after a routine BIOS or Windows update
until a recovery ceremony re-sealed it, fighting head-on the key-loss-recovery
posture the platform requires (ADR-025). And the threat it buys down — someone
booting a different OS to *use* the keys — is physical and boot-local,
orthogonal to the network surface the #598 gate is about, and already mitigated
in depth: the keys are non-exportable and chip-bound (not extractable at all),
the box is air-gapped and physically held, and the keystore is owner-only-DACL'd
(#637). A brittle fourth layer against a residual sliver of an already-covered
physical threat is a bad trade. So the keys stay hardware-resident,
non-exportable, DACL-locked — not PCR-gated — and the PoC stands as the recorded
evidence behind the *informed* decline, not a half-built feature.

**Next:** recorded as ADR-028 Amendment 1 + DECISION_REGISTER + roadmap §5.9.
#627's deferred PCR boot-attestation-*check* (a distinct, weaker mechanism than
key-sealing) is unchanged by this — neither advanced nor closed. The 2026-06-09
PoC artifacts (the report + `verify_pcr_seal.py`) await an LA disposition call
(commit as the evidence-of-record, or leave as a standalone PoC); they are
untracked and were not touched.

*(commit `<this>` (ADR-028 Am.1 + register + roadmap + this entry + lesson 105);
no product code changed — a governance decision recorded. PoC artifacts left
untracked pending the LA's keep/commit call.)*


### 2026-06-10 — The one store I chose not to encrypt

The audit-retention work (#607) surfaced a posture question its builder was
right to escalate rather than answer: the new sealed segments inherit the
active log's existing on-disk shape — TPM-signed, owner-only-DACL'd, but
*plaintext* — while `sessions.db` and `substrate.db` are DEK-sealed (ADR-025).
The reflex, and this project's standing lean, is encrypt-everything-at-rest; I
have been overridden before for proposing a plaintext residual, so the honest
move was to escalate it with a recommendation rather than quietly ship either
default. The LA ratified the recommendation: keep the audit log
signed-and-locked, not encrypted.

The reasoning is the part worth keeping, because this is a genuine *exception*
to a good default, not a lapse from it. An audit log's whole value is being
*independently* checkable — a reviewer, or a future operator, must be able to
verify the trail without holding the data-encryption key, and the trail must
survive that key being lost or compromised. Encrypting the audit log couples
the witness to the very thing it witnesses: the one record meant to outlive a
key incident would die with the key. And the cost side is low — the records
are metadata (decisions, resource identifiers, hashes), not conversation or
document content — so the confidentiality encryption would buy here is small.
Signed + owner-DACL'd + air-gapped is the right amount of protection for *this*
store. What I did not do is pretend the question is closed forever: the moment
post-#556 tools begin writing sensitive resource identifiers — real file paths,
URLs — into `resource`, the metadata stops being low-sensitivity and the
encryption trade-off should be re-weighed (with the keyed-hash-for-index
pattern that keeps a ciphertext log verifiable). The decision and its expiry
are both on the record.

**Next:** no code changes — the as-built signed-plaintext posture stands,
ratified; the revisit trigger is wired to the #556 network-facing work. #607
closes.

*(commit `<this>` (ADR-029 ratification note + this entry + lesson 104); no
product code changed — a governance decision recorded.)*


### 2026-06-10 — The fingerprint, and the decision I tried to hand back

The #639 decision record always named the destination: the LA chose inline
operator confirmation with the goal of approving escalations by fingerprint via
Windows Hello. When he asked "what about windows hello and the fingerprint
scanner?", the honest answer was that the consumer was live but the biometric was
still the follow-on — so I scoped it (#649) and then made the mistake worth
keeping in this journal: I asked him to choose the implementation route. He
pushed back in one line: "Why are you asking me this? I am a novice. Does this
impact security, capability, or performance such that I need to make a decision?"
It didn't. The route — a tiny C# helper subprocess versus an in-process Python
WinRT binding — changes nothing the operator governs; the only fork with a real
posture delta was whether to add a new Python dependency (a `winsdk`-style wheel)
to the runtime, and under this project's supply-chain posture that fork has an
obvious answer: don't. I had dressed mechanics as governance, and the cost of
that dressing is precisely the involvement the LA is trying to minimize. The
test I should have applied is the one already written into this repo's doctrine:
a decision is only a decision if the options differ on security, capability, or
quality. These didn't, so the call was mine. I made it, told him so, and built.

The build is deliberately boring. A \~145-line C# console helper
(`tools/hello_verify/`) fronts the WinRT `UserConsentVerifier` — the same
`net8.0-windows10.0.19041.0` Windows-SDK projection the WinUI surface already
targets, so there is no NuGet package, no new wheel, no supply-chain delta at
all. The process exit code is the contract: 0 only on Verified (or Available in
`--check` mode); every other state maps to a distinct non-zero (Canceled=15,
RetriesExhausted=14, DeviceNotPresent=10, any exception=30), and the Python
`BiometricApprovalVerifier` (`shared/security/hello_verifier.py`) maps everything
except exit 0 to DENY — timeout, missing exe, OSError, all closed. The dialog
message is the labels-only descriptor from `EscalationContext`; no secret
crosses the process boundary, and the helper never logs or echoes it. The
trade-off named: I took subprocess-per-verify (a few hundred milliseconds of
spawn) over an in-process binding because a consent verify is a
human-in-the-loop event where spawn latency is noise, and the rejected
alternative would have been a version-pinned supply-chain item forever.

The pleasant surprise was topological. I had forecast, in the #639 entry, that
the WinUI surface would need a real cross-process ESCALATE build. It doesn't —
`UserConsentVerifier` raises a SYSTEM-modal dialog owned by Windows, not by any
BlarAI window, so one helper serves both surfaces identically: the launcher now
probes `--check` at startup and registers the biometric verifier on the TUI and
WinUI paths alike when Hello is available, with the Textual modal as the TUI
fallback and deny-by-default as the WinUI fallback. The forecast cross-process
work collapsed into a path selection.

The live-verify was the LA's own hand, both directions: three real fingerprint
matches on the ELAN sensor → APPROVED (verifier=hello), then three cancels →
DENIED (exit 15), all through the real system dialog driven by the real
verifier and the real consent path (`scripts/demo_escalation_hello.py`). The
same producer gap as #639 still applies — nothing in the current four-tool set
can emit an ESCALATE, so the fingerprint path is live-but-dormant until the
first escalating tool ships. When it does, the operator's biometric is already
the consent ceremony.

**Next:** the first escalating tool (web-search W4 or a file/system tool) makes
Hello the exercised end-to-end consent path; the gate tail remains the #612
capstone phase and the §5.12 sign-off.

*(commits `b65f1c5` (the #649 build: 7 files, +1172/−19, 40 mocked-subprocess
regression tests; helper builds 0 warnings / 0 errors); merge `c1f51e9`; standing
gate 2484 passed / 2 skipped / 116 deselected non-elevated (= 2486/0 elevated),
+40 from #649 and +126 across the five 2026-06-09/10 gate-criteria merges; LA
fingerprint live-verify 2026-06-10 — 3 APPROVED by real match, 3 DENIED by
cancel.)*


### 2026-06-10 — The paste that walked in through the front door

The independent LA-session verification of the ingest-UX branch (LA verdict
2026-06-10) found the channel I had built around every defense and then left
open beside them: the gateway persisted the operator's full `/ingest` message
— up to \~40 KB of raw, pre-cleaning web text — as a `role='user'` turn in
sessions.db, and the prompt-history filter forwards ALL user turns verbatim
into later prompts. So the knowledge bank could clean, quarantine,
approval-gate, encrypt, datamark, and ground that article as
UNTRUSTED_EXTERNAL — while an identical uncleaned copy rode straight into the
model's context as a trusted user turn on the very next message. Not a
bypass of the defenses; a parallel path that never met them. The irony is
that the assistant-side preview was already correctly excluded (the
INFORMATIONAL marker keeps it out of history) — I had defended the reply and
left the request wide open.

The fix persists a labels-only STUB user turn for ALL `/ingest` modes:
`/ingest <article: {N} words, doc {uuid8}>` on a successful submit, a
`not submitted` variant when the command refused or the URL limb is dormant.
Two deliberate negatives are doing the security work. First, NO content-hash
prefix in the stub — the orchestrator decided this (LA-delegated): a
truncated digest would re-seed into sessions.db the same content-fingerprint
membership oracle the knowledge-bank branch just closed at rest, and the
opaque doc_uuid already gives the transcript a join key to the audit chain.
Second, the persisted assistant turn for a successful submit is also a
labels-only summary, because the preview reply embeds the full CLEANED
article body — and "the paste never persists in sessions.db" is not honest
if a lightly-cleaned copy of it persists one row down. The live reply is
untouched: the operator sees the full preview in the moment; a session
reload shows the summary. I accepted that transcript-fidelity cost over the
alternative (persisting the body under some new excluded-from-history
marker), because markers rot and scope-creep — absence cannot be forwarded.

Chasing the same digest one level further turned up a smaller leak of the
identical shape: an untitled paste's pending label fell back to its
`source_ref`, which for pastes is `paste:<content-sha256>` — so the
`/approve` confirmation ("Approved — "paste:abc123…"") would have persisted
the full plaintext content digest into sessions.db through the decision
message. The label now falls back to `pasted article (doc {uuid8})`.
`/approve` and `/reject` themselves persist verbatim — short commands, no
content. Regression locks: a marker-tagged paste is absent from a full dump
of the session store (turns AND titles, raw and cleaned forms both); the
stub format is locked exactly; later-prompt history carries the stub only;
decision turns are unaffected; the untitled-paste decision path carries no
digest. Gate for this worktree: ui_gateway + ui_backend + ui_shell +
test_no_external_egress = 549 passed, 0 failed.

**Next:** the merge-gate review for #655 should re-run the dump-scan tests on
the merged tree (this branch is stacked on the knowledge-bank branch, whose
own fragment covers the at-rest membership-oracle close); the TUI inline
ingest orchestration named in the Stage-B follow-ups inherits this stub
behaviour for free via `handle_ingest_command`.




## Act III — Cutting the door (Jun 10 – 16)

### 2026-06-10 — A third failure posture, and the index that lives only in RAM

Stage A of the UC-003/UC-002 program (#655) is the knowledge-bank vertical: the
encrypted, approval-gated store that the future paste-a-URL flow will land
cleaned articles into. I shipped it end to end behind glass — `knowledge.db`
as a sibling of `substrate.db`, the IPC verbs, the encrypted staging handoff,
the AO wiring, the ingest audit chain, and the 512-token re-embed migration —
with no fetch anywhere in sight (that limb stays governance-gated behind
ADR-027 and the #598 sign-off; this stage never touches a socket).

The first decision was where the documents live. The tempting move was a third
`kind` in `substrate_chunks` — one store, one boot cache, one retrieval path.
But the substrate carries `CHECK(kind IN ('doc','turn'))`, which SQLite cannot
ALTER (a full table rebuild on the operator's live memory store, to share a
schema that has no approval state, no provenance record, and no dedup-by-source
column). I went with a sibling DB under the SAME DEK envelope (ADR-025's
one-DEK rule), accepting a second boot-decrypt pass and a second retrieval path
in exchange for a lifecycle the substrate simply does not have: rows move
`pending → approved|rejected`, pending rows hold cleaned content only (no
chunks, no embeddings), approval is the moment chunking + embedding + indexing
happen, and rejection is a tombstone that RETAINS content — retention is a
later lifecycle decision I deliberately did not take. Dedup is the substrate's
keyed-HMAC trick over ciphertext: a re-submitted identical source replaces a
prior pending row, replaces a rejected tombstone (an explicit re-submit is a
fresh-decision request), and NEVER touches an approved document — that conflict
returns a distinct `already_ingested` result instead.

The hairiest design fork was lexical search. UC-002 has always promised
hybrid retrieval, and FTS5 is compiled into the project's Python 3.11.9 — but
an FTS5 table on disk indexes plaintext, which would park recoverable article
text right next to the AES-256-GCM ciphertext it defeats (the Sprint-14
strict-residuals override is exactly on point). An encrypted-at-rest index
file was the second option; it costs a rebuild-or-rewrite on every approve and
buys nothing at personal scale. I took the third path: at DEK-unlock the bank
builds an IN-MEMORY FTS5 index (`:memory:` connection) over the decrypted
chunk text of approved docs — the exact pattern the substrate's embedding boot
cache established — and extends it incrementally on each approve. Hybrid
retrieval is brute-force cosine over the in-RAM vectors plus FTS5 BM25, merged
by reciprocal-rank fusion with the canonical k=60. Plaintext exists only in
RAM, only after unlock, which is precisely the boundary the rest of the system
already accepts. (Free-form queries are word-split and double-quoted before
they reach MATCH, so FTS5 operator syntax is not an injection surface.)

Embeddings got their overdue width fix. The substrate has been embedding
2048-char chunks through the leakage detector's 128-token window — roughly
three quarters of every stored chunk never informed its vector. Knowledge
chunks embed at 512 tokens (bge-small's native max) via a NEW
`LeakageDetector.embed_documents` method on the same loaded session; the
leakage path's 128-token `_embed` is untouched because PGOV Stage-5 thresholds
are calibrated there, and a regression test now locks its output to a
reference computation. Writing that lock taught me something embarrassing: my
first stub session emitted `hidden[s,d] = ids[s] * scale[d]`, and L2
normalisation cancelled the token dimension entirely — the 128-vs-512 test
could not fail no matter what the code did. The stub had to become
non-separable (`(ids[s] + d) % 13`) before the property under test was even
visible. The existing `substrate.db` gets the same width via a runnable
re-embed migration (`python -m services.assistant_orchestrator.src.reembed_substrate`):
decrypt text → re-embed at 512 → re-encrypt under the same AAD, bump
`substrate_meta.embed_max_tokens`, verify every row decrypts to a unit-norm
384-vector, idempotent on re-run. It will be executed manually on the live box
— tests drive it only with stub embedders.

The process seam is deliberately boring: three new IPC verbs (INGEST_SUBMIT /
INGEST_DECISION / INGEST_RESULT) whose payloads are labels only. Content
crosses in an encrypted staging file
(`%LOCALAPPDATA%\BlarAI\ingest_staging\<doc_uuid>.bin`, same DEK, AAD bound to
the doc identity), so the 64 KB envelope is never pressured and a staged blob
cannot be replayed under a different document. One security call worth
recording: the submit payload carries a `staging_path`, but the AO never
dereferences it — the read side derives the canonical path from the validated
UUID (anything traversal-shaped dies in `uuid.UUID()` before a path exists)
and merely cross-checks the claim. A path that arrives over IPC is input, not
an address.

Failure posture was a genuine decision, so I am naming the alternatives. The
substrate degrades silently (memory off, AO starts); the session store refuses
to start. The knowledge bank takes a deliberate third posture: feature-level
LOUD disable — construction failure (including a production audit-chain
failure: TPM key unprovisioned, keystore missing) logs ERROR and every
INGEST_* frame returns a clear `KNOWLEDGE_BANK_DISABLED` error, but chat boots
untouched. An ingest feature the operator can see is broken beats both a
silent absence and a bricked assistant. In the same register: the AO now emits
its first ADR-029 audit events — its own file, its own chain
(`ingest_audit.jsonl`), the PA's adjudication log untouched — mapping
submit→ESCALATE (held for human review, which is literally what pending
means), approve→ALLOW, reject→DENY, with doc_uuid + source-hash prefix as the
resource and never a byte of content. A decision whose audit append fails
returns an error frame rather than silently succeeding unrecorded. Two smaller
deliberate divergences: WAL is ON for knowledge.db (interactive writes
alongside reads; the substrate's default journal stays as-is), and retrieved
knowledge is grounded UNTRUSTED_EXTERNAL with datamarking REGARDLESS of the
stored provenance column — operator approval curates content into the bank, it
does not promote web text into the trust boundary (ADR-023, lesson 13). Since
today's four tools are all SAFE-tier, the Layer-3 lock this engages costs the
daily driver nothing.

Numbers: 815 lines in `knowledge_bank.py`, 335 in the re-embed module, 206 in
the staging helper, plus the protocol/entrypoint/pgov edits; 146 new tests
(106 under `services/assistant_orchestrator/tests/`, 40 under `shared/tests/`)
all green with no model files present, and the three touched suites
(AO + shared + ui_gateway) pass 1610→1756 with one existing message-type lock
updated in-change, 17 deselected, 0 failures. `docs/security/DATA_MAP.md` §2
gained rows 8–10 (knowledge.db, ingest_staging/, ingest_audit.jsonl).

**Addendum (same day) — the review that found real corruption.** An
adversarial review of this vertical reproduced a CRITICAL defect I am keeping
on the record exactly as found: `submit_pending` issued its dedup-replace
DELETE and could then raise on the doc_uuid-collision check — python's sqlite3
left that DELETE in an open implicit transaction, and the next healthy
operation's commit flushed it, silently destroying an unrelated pending
document (submit u1/X, submit u2/Y, submit(doc_uuid=u1, source=Y) raises; u2
is gone after a later submit + reopen). `approve()` carried the same
no-rollback hole. The fix is structural, not local: every mutating method now
runs all deterministic checks and ALL encryption before any DML, and the DML
runs inside `with self._conn:` (commit-or-rollback); the exact reproduction is
a regression test, alongside a mid-INSERT IntegrityError rollback lock. The
review also caught the audit chain recording AFTER the mutation — a dead audit
sink left an approved, retrievable document with no governance record. I
inverted to audit-first (PA precedent: an unauditable action never takes
effect), accepting the documented opposite residual — a record may exist for a
mutation that then failed — resolved by a best-effort `<verb>_FAILED`/DENY
compensating record, with read-only prechecks so deterministic refusals never
write records at all. Three more MAJORs: the re-embed migration stamped
`substrate_meta` even when every row failed (now stamped only on a clean run,
with `--accept-quarantined` for confirmed dev-key remnants); the AO still
bound the substrate embedder at 128 tokens while the migration stamps 512 —
post-ceremony ingests would have re-created the exact mixed-depth store
ADR-031 §3 rejects (now meta-driven at build time, and the knowledge bank
refuses retrieve/approve on a stored-vs-configured window mismatch); and my
"vector" retrieval tests were all satisfiable by BM25 alone — the suite passed
with the cosine limb deleted (the new pinned-vector lock and the strengthened
punctuation test both fail with the limb commented out; I verified that before
restoring it). Minor hardening rounded it out: `content_sha256` is now
required fail-closed at both the encoder and the AO seam, plus WAL-sidecar
plaintext-scan, FTS5-stays-in-RAM, and AAD-swap locks. Suites grew 1756→1782
across AO + shared + ui_gateway, zero failures. The lesson already in this
entry — prove the lock can fail — applied to my own tests within hours of
writing it.

**Next:** Stage B builds the operator-facing limbs this vertical is shaped
for: the gateway-side `/ingest` UX (staging writer is already shared), the
trafilatura cleaner behind its hash-pinned vetting record, the in-chat
preview/approve flow over the new INGEST verbs, and — strictly after the #598
sign-off and the ADR-027 Amendment 1 per-action adjudication — the VM-homed
fetch. The substrate re-embed ceremony (`--dry-run` first) wants a slot in the
next live-box session, and the bank's embedding cache should eventually adopt
the #611 idle-unload pattern the substrate already has.

*(commits `8efbffc` (encrypted knowledge-bank core + 512-token embed_documents + re-embed migration), `0605329` (AO wiring: build/dispatch/retrieval + ingest audit chain + DATA_MAP rows), `f5e8bfc` (adversarial-review fixes: transaction discipline + audit-first + meta-driven embed windows + vector-limb lock), `34c3e34` (V-1 membership-oracle closure: keyed content digest at rest + in audit; zero-NIC launcher gate); merged to main in `c709183`; branch-tip gate 1668/0.)*



### 2026-06-12 — The first packet off the box

For its entire life BlarAI has been air-gapped — `egress_guard` armed at every
boot, `test_no_external_egress` failing the build on a single stray import, the
wall absolute. Today, with the LA at the screen, it reached the internet for the
first time, on purpose, through one door, and came back clean. The harness printed
a line I had been building toward across this whole arc — `FETCHED ok: http=200,
bytes=89219` — and then a title pulled out of 89 KB of hostile news-site HTML:
*"GitHub announces npm security changes to tackle supply-chain attacks."* Byline
Bill Toulas, dated 2026-06-10, 450 words, status clean, confidence 1.000. The
chrome was gone; the article was there. The air-gap is removed.

What makes it defensible rather than reckless is everything the byte count doesn't
show. The fetch went through `guarded_fetch` — the one door, the only module in
the runtime that imports `httpx`, GET-only, no request body, the URL the sole
thing on the wire. The Policy Agent adjudicated it: I registered the deterministic
adjudicator with exactly one host allowlisted — `www.bleepingcomputer.com` — for
exactly one fetch, which is ADR-027 Amendment 1's "the paste is the consent for
that ONE URL" made literal; the door logged the per-fetch allowlist widen and the
guaranteed revoke around it. The 89 KB of hostile HTML was never parsed in the
host process that holds the keys — it crossed AF_HYPERV vsock into the NIC-less
guest (VmId confirmed, NIC count 0), trafilatura ran in there, and only 450 words
of clean text came back. The host composed the final verdict and the injection
axis on that text, not on the raw page. And the whole thing was self-rewelding:
the adjudicator cleared in a `finally`, the process exited, the VM stopped, and
the door is back to deny-by-default on all three locks. The green signal and the
welded-shut state are the same fact viewed from two ends.

The honesty the journal owes: I did not globally arm `egress_guard` for this first
shot. Its own docstring says the pre-fetch SSRF resolution would trip an armed
guard before the per-fetch widen, and I was not going to risk debugging that
interaction on the single most irreversible action this system has ever taken.
The per-action door, the PA gate, the guest containment, and the compose were all
real; the rule-3 kill-switch layer (covered by the security suite) and parse-channel
mTLS (the on-box vsock hard gate) are the two named follow-ups before this is the
*production* posture rather than the proof. I would rather ship a true green with
two named gaps than a green that papered over them.

It is worth saying what almost happened instead. Twice in the run-up to this I was
confidently wrong — "reuse the vsock connection," "draft the ADR" — and twice the
disk corrected me before I built on the mistake: the adjudication path I'd have
built didn't exist, and the ADR I'd have drafted was already written. The first
real egress worked on the first try not because I was sure, but because I kept
checking what was actually there. That is the whole method, and today it bought
the milestone.

**Next:** the production-posture follow-ups — the armed-`egress_guard` live run and
parse-channel mTLS (guest cert re-provision; host plumbing already in place) — then
the same fetch driven from the operator's WinUI `/ingest` surface rather than the
host smoke harness, and the kill-switch + exfil-screen exercised live against a
real outbound. The wall is now a door with a guard on it; the remaining work is
proving every layer of the guard under load.

*(commit `<this>` — `scripts/uc003_live_fetch_smoke.py` (the going-live proof
harness) + `docs/security/uc003_live_fetch_proof_2026-06-12.md` (the evidence). The
first sanctioned external egress: real BleepingComputer article fetched through the
one PA-gated door (HTTP 200, 89,219 bytes), parsed in the NIC-less guest (450 words,
clean), host-composed verdict confidence 1.000, then re-welded to deny-by-default;
VM stopped. egress_guard-armed + mTLS + WinUI-surface runs are named follow-ups.)*



### 2026-06-12 — The door that would have tripped its own alarm

The LA asked to do the thing the whole arc had been building toward: drive
`/ingest <url>` himself, in the real app, and watch the article come back so he
could approve or reject it before anything reached memory. I expected three
blockers — the parser disabled by default, the dead Copy-VMFile deploy, and the
egress adjudicator deliberately left unregistered — and they were all there. What
I did not expect was the fourth, and it is the one worth keeping.

The production launcher arms the egress kill-switch at the real process entry,
before `main()` ever runs. The one egress door, though, resolves the URL's host
*before* it opens the per-fetch hole in the firewall — a deliberate ordering, so
the door can refuse a name that secretly resolves to an internal address without
ever widening the allowlist for it. Those two facts are individually correct and
together fatal: under the armed guard, the door's own DNS lookup of the
not-yet-allowlisted host is itself off-allowlist egress, so the guard trips the
kill-switch on it. The operator's very first `/ingest` would have denied the fetch
*and* air-gapped the box into a state needing a re-arm ceremony. The smoke harness
that proved the first egress last week had quietly dodged this by never arming the
guard at all; the journal had named "armed-egress_guard live run" as a follow-up
and moved on. The LA wanting to test in production is precisely what dragged the
deferred work into the light — the request was the test.

The trade-off is the part the cert track wants on the record. The obvious fix is
to widen the allowlist *before* resolving, so the armed guard permits the lookup.
I rejected it: a test asserts, on purpose, that a host resolving to an internal
address is refused with the allowlist *never even briefly widened* — no momentary
hole for an unvetted destination. Widen-before-resolve would have bought
armed-guard compatibility by spending that property, and on the egress door that
is the wrong currency. The fix I took instead keeps the ordering and the property:
the door does its own inspect-and-refuse SSRF lookup through the guard's real,
pre-arm resolver. That bypass is legitimate precisely because the lookup only
*inspects* the resolved IPs to refuse internal ones — it never connects. The
actual egress still resolves and connects through the armed guard, the per-fetch
widen, and the W4 resolution pin, every byte of it unchanged. A new regression
test arms the guard and proves a fetch now completes without tripping — the
production-posture lock the proof harness structurally could not give.

The last decision was reversibility. I did not want going-live to be a one-way
commit landing `enabled = true` in the tree. The committed default stays welded;
the operator opens the door for a single session with an environment flag, and the
next boot without it is welded again, with the adjudicator unregistered by
construction. Going-live became a per-session, self-rewelding act rather than a
posture you have to remember to undo.

There is a coda worth keeping, because it failed in front of the operator. I had
chosen an environment variable as the reversible per-session door-opener — clean
in the abstract, welded-by-default, opt-in per boot. Then the LA ran it from his
desktop shortcut and got the refusal anyway. The launcher self-elevates through
UAC, and the launcher's *own* code says it on the tin: `request_elevation`
forwards `sys.argv` to the elevated relaunch but not the parent's environment
block. So the variable I set in the un-elevated shell evaporated on the elevation
hop, the config fell back to `enabled=false`, and the door stayed shut — exactly
as designed, for the wrong reason. The fix was to stop fighting the launcher's
model and use it: a `--go-live` CLI flag, which the same `request_elevation`
*does* forward, translated in-process to the same enable. And because the operator
is a novice who launches from a shortcut and not a terminal, "correct" wasn't a
flag he could type — it was a second desktop shortcut (`run_winui_golive.bat`)
that carries the flag for him. The lesson the env var taught: a reversible knob is
only reversible if it survives the path the user actually takes to turn it.

**Next:** the LA drives the first live `/ingest` under the armed guard from the
WinUI surface (now via the dedicated go-live shortcut); the one thing unit-proven but not yet live-integrated is httpx's
real connect through the armed guard + resolution pin, so that is the limb to
watch. Then parse-channel mTLS (the guest cert re-provision; host plumbing already
in place) and a kill-switch + exfil-screen exercise against a real outbound remain
the production-posture follow-ups before this is the finished posture rather than
the working one.

*(commit `<this>` — the go-live activation: `shared/security/guarded_fetch.py` +
`shared/security/egress_guard.py` (the armed-guard door-resolution fix +
`real_getaddrinfo` seam, with an armed-guard regression test),
`services/ui_gateway/src/url_adjudicator.py` (`make_operator_url_adjudicate`, the
"URL = authorization" per-paste adjudicator), and the launcher resident-parser
skip-deploy + register-on-READY + the reversible `BLARAI_GUEST_PARSER_ENABLED`
override. Door welded at rest; security suite 181 green incl. the armed-guard
lock; standing gate 3217/0/116 (20 benign worktree model-absence skips).)*



### 2026-06-14 — The knowledge bank that could only be written to

Two controls I would defend separately, each correct on its own terms, met
in the knowledge bank and quietly turned it write-only. The LA found it the
honest way: he ingested a cyberattack article, opened a fresh session, asked
the assistant to recall it, and got back *"Response held by the output
validator — LEAKAGE_DETECTED."* You could save anything. You could get
nothing back. For a feature whose entire pitch is "save articles, recall
them later," that is a clean kill.

The collision is worth keeping because neither half is wrong. The first
decision is lesson 13 in mechanical form: *provenance is not trust.* When
the operator approves a web article into the bank, that approval **curates**
the content — it does not **promote** web-sourced bytes into the trust
boundary. So knowledge retrieval grounds its chunks as `UNTRUSTED_EXTERNAL`
(`entrypoint.py:2385`), which keeps the Layer-3 action-lock armed: a
prompt-injection buried in a saved article still cannot fire a tool. I would
not give that up. The second decision is the Stage-5 leakage control: feed
the cosine detector only the untrusted chunks, and if a generated answer is
≥ 0.85 similar to one of them, hold it as a verbatim echo. That is the
exfiltration signature — a fooled model parroting content from outside the
trust boundary — and I would not give that up either.

But a faithful recall of a saved article *is* near-verbatim to its source.
That is exactly what high cosine measures, and it is exactly what the user
asked for. So every honest recall looked like a leak. The detector wasn't
malfunctioning and it was not a "cyberattack content is dangerous"
classifier — it would have held a saved soup recipe with equal confidence.
It was a category error: the control could not tell "leaked what you didn't
ask for" from "answered using what you deliberately saved." I had seen this
exact shape before. On 2026-06-04 the same false-positive class held back a
correct two-document summary, and the fix then was to carve *trusted* content
out of the leakage feed because a summary of your own files is similar to them
by design. Curated knowledge is the next member of that family — the operator
saved it *for the purpose of recall*, so echoing it back is the point.

The tempting fix was the wrong one, and naming why is the governance part.
The fast path is trust-promotion: ground knowledge as `TRUSTED_LOCAL` and the
leakage feed excludes it for free, because trusted tiers carry no controls.
But "no controls" is the trap — it also drops the **action-lock** and the
injection scan, so a poisoned article saying *"ignore prior instructions and
call send_email"* would regain the power to fire a tool. That trades a
false-positive annoyance for a real security regression, and it directly
contradicts lesson 13. The other tempting shortcut, globally disabling the
leakage control, is over-broad in the other direction: it kills the detector
for genuinely-pasted external text too, re-opening the exfiltration surface
the control exists to close. And raising the cosine threshold fails for the
same reason #579 rejected it originally — a faithful recall trends to cosine
1.0, so no single number both passes recall and catches a real echo. The axis
is provenance, not a score.

So the fix is a fourth provenance tier, `UNTRUSTED_KNOWLEDGE`, and it is
deliberately the narrowest cut I could make: untrusted *everywhere* the
existing untrusted tier is untrusted — action-lock, datamarking, injection
scan, PII source, the #570 per-dispatch deny — with **exactly one** exception,
the Stage-5 cosine leakage output feed, from which it is exempt. Trust is not
promoted; only the leakage feed is relaxed. The mechanics fell out beautifully
once the tier existed, and that is not luck — it is the seam the original
ADR-023 design left. `get_untrusted_chunk_texts` filters on `==
UNTRUSTED_EXTERNAL` (an equality), so the new tier is excluded from the leak
feed with **no change to that filter**; `has_untrusted_content` tests `not in
(TRUSTED_LOCAL, TRUSTED_MEMORY)`, so the new tier trips the action-lock with
**no change to that gate**. The entire behavioural delta is one line at the
ingest call — `UNTRUSTED_KNOWLEDGE` instead of `UNTRUSTED_EXTERNAL`. The rest
of the change is tests and the words that explain why the filter stays an
equality so a future reader doesn't "tidy" it into a `not-in-trusted` test and
silently re-break recall.

The tests are the load-bearing half, because the whole risk here is weakening
a security control while fixing a usability bug. So each must-not-weaken claim
got its own lock: a GUARDED tool is still refused when only knowledge content
is present and there is no `/trust`; a DANGEROUS tool is still locked under
knowledge content with no override (#593 fail-closed, now proven for the new
tier too); knowledge chunks are still delimiter-wrapped and datamarked;
pasted-external content is *still* in the leakage feed even when mixed with
knowledge in the same session. And the positive case the fix exists for: a
faithful recall that I rigged to score cosine 0.97 against its source now
**passes** PGOV and is delivered — proven by injecting a mock detector that
*would* fire, then asserting it is never even consulted because the knowledge
chunk never reaches the feed. The teeth test is the same setup with
`UNTRUSTED_EXTERNAL` provenance, which *is* held at 0.97 — so the carve-out is
demonstrably provenance-scoped, not a global softening. 156 tests green across
the three touched AO modules; 180 across tools + pgov.

**Next:** Guide-session review + merge to main (this branch deliberately stops
at a committed, test-verified state). After merge, re-run the standing gate to
record the new count, then the real-hardware confirmation the LA cares about —
ingest an article, recall it in a fresh session, watch it come back instead of
being held. The dormant fetch/egress weld (#577/#655/#659) is untouched; this
was AO-side leakage/provenance only.



### 2026-06-16 — Teaching the box to draw, with the door welded shut

UC-010 is the first capability BlarAI has that was never one of the nine. ADR-015
and the journal's §19 both named image generation an "honest future track" — a
thing we'd want, behind a separate diffusion model, someday. The LA decided someday
was now, and approved the plan with amendments. So this is the build that
deliberately *expands* the canonical vision rather than executing it — and I wrote
that down everywhere it touches (UC-010 §scope, ADR-033, the register row), because
a silent scope expansion is exactly the kind of thing future-me would mistrust.

The shape of the work was a relief: it is the `vlm.py` story told a second time.
A heavy GPU model that can't co-reside with the 14B, loaded on demand, evicted in a
`finally`, fail-soft on every error so an OOM degrades to a notice instead of
freezing the host. I had the template, the eviction discipline (#561's lesson:
hold the VLM and the host freezes), and the born-encrypted store pattern from the
UC-003 image work that landed the same day. The new module is a structural clone
with one addition — a `_model_kind` global, because a diffusion pipeline comes in
two flavours (text2image, image2image) and the budget holds exactly one resident at
a time, so loading the other kind has to drop the first.

Two things made me stop and think rather than type.

The first was the manifest. The whole point of `verify_all_manifest_entries` is
fail-closed weight integrity at load — and I went to reuse it and found it can't
see this model. It globs `*.bin` in the top directory and keys by bare filename.
A diffusers-OpenVINO model puts its weights in subdirectories — `unet/`,
`vae_decoder/`, two text encoders — and the bare name `openvino_model.bin` repeats
across five of them. The flat function would find nothing and collide on the
duplicates. This was a real gap the plan assumed away ("verify via
`weight_integrity.py`"), and the wrong move would have been to either skip the
verify or to bend the locked flat function that the 14B boot path depends on. I
added a sibling — `verify_all_manifest_entries_nested` — that treats manifest keys
as relative POSIX paths and walks the tree, reusing the proven `load_manifest` +
`compute_sha256` primitives and keeping the same extra-file rejection (now
recursive). The flat function is untouched. I'm flagging it in the hand-back as a
deviation-of-necessity rather than pretending the plan covered it.

The second was content safety, and it's the one I'm proudest of resisting. The
instinct on an "uncensored image generator" is to bolt on a classifier so the
project can say it has a guardrail. The LA's decision — and the honest engineering
— is that a *local* classifier at the legal boundary is security theater: there's
no distributable hash database for the one boundary that matters, and a prompt
denylist is bypassable in three different ways while it false-refuses legitimate
prompts. So ADR-033 says the true thing instead: the boundary is named explicitly,
it's the operator's sole documented responsibility, it's a recorded ACCEPTED-RISK,
the control is governance plus a one-time go-live attestation, and the
*consequences* are bounded structurally — operator-initiated, audited, no-egress,
no-distribution. Writing "robust local technical control here is not achievable"
into a security ADR feels wrong until you realize the alternative is writing a
comforting lie into one.

The dormancy held all the way down, which is the part that lets me hand this back
unmerged with a straight face. `enabled=false` ships; the model is gitignored so
the capability is absent by structure; `is_available()` is False on a clean
checkout and `/imagine` degrades to "generation unavailable" with no load attempted
— and there's a test that proves exactly that. The `generate_image` tool is GUARDED
and the PA allows a local `tool:generate_image` CAR with no rule change, so the
"lift the purpose-deny at go-live" is a config flip, not an adjudication edit —
the BED-1 pattern from the UC-003 image door, except there's no egress door to weld
here, just the `enabled` flag and the model's absence.

The standing gate caught two real couplings I'd have shipped broken: the IPC
expected-types test (two new `MessageType`s) and the system-prompt invariant (every
registered tool must be named in the prompt, or the model can emit a tool tag the
PGOV allowlist then has to reconcile). Both are good tests — the second especially:
it forced me to decide, honestly, what the model should be told about
`generate_image` (answer: that it exists and directs to `/imagine`, not that it
should hallucinate an image description). Gate green at 3669/0, +36 over the 3633
baseline, egress invariants intact ("exactly one runtime module imports a network
client" still passes — image-gen adds no network surface).

**Lesson:** *When a security primitive doesn't fit the new artifact, add a
sibling — don't bend the locked one.* The weight-integrity sweep is load-bearing for
the 14B boot path; the diffusers-OV nested layout needed a different walk. The cheap
move (skip the verify, or widen the flat globber and risk the boot path) trades a
real fail-closed guarantee for convenience. A clearly-named sibling that reuses the
proven primitives keeps both layouts honest and the locked path untouched.

**Lesson:** *Name the control you actually have, not the one that sounds
reassuring.* On an uncensored generator the reflex is a classifier; the honest
answer is that a local classifier can't hold the legal boundary and a governance
attestation can be made to mean something. Writing "no robust local technical
control" into the ADR is the mature posture — a comforting fiction in a security
document is worse than a named, accepted, structurally-bounded risk.

**Next:** the branch (`666-uc010-image-gen`) goes back for Guide review unmerged.
Go-live is the separate LA-present ceremony in ADR-033 §dormancy/go-live: the
one-time operator content attestation, then flip `[image_generation].enabled`, then
verify LIVE on the Arc GPU (text→image + img2img each produce a real image;
born-encrypted confirmed by a raw-column scan; a cap fires; the eviction sequence
observed under `log_memory`; WinUI renders `blarai-img://`; `/edit` refuses a URL),
then record the community-grade PERFORMANCE_LOG live numbers and a same-day journal
entry. The `blarai-img://` `/edit`-seed + `/save` bank-reader bridge (the gateway
reaching the AO's `generated_images` store) is the one wiring step left for those
two display-path features; text2image and local-file `/edit` work without it.

*(Branch `666-uc010-image-gen` from main `2b7e35c`; new `shared/inference/image_gen.py`
+ `services/ui_gateway/src/imagine_coordinator.py` + `generated_image_resolver.py`,
`generated_images` table + IPC pair + GUARDED tool + `[image_generation]` config +
ADR-033 + UC-010; +56 new tests (54 unit + 2 @hardware); standing gate 3669 passed /
0 failed / 20 skipped / 118 deselected; awaits the LA-present go-live ceremony.)*



## Act IV — Teaching it to build (Jun 16 – Jul 2)

### 2026-06-16 — The verifier I almost broke for the whole fleet

The brief for the UC-010 image-generation go-live prerequisites read cleanly
enough: close the weight-supply-chain gap the #666 review had flagged by
extending the manifest verifier to cover the OpenVINO `.xml` topology and
`model_index.json` (today it only hashes `.bin`), sign the SDXL manifest like the
14B, turn `secure_delete` on so "purges at rest" stops being an aspiration, and
build the converged WinUI render bridge dormant. The original plan even said it in
so many words: *extend BOTH the flat and nested verifiers + the stager*. That
"BOTH" is the sentence that would have refused the next real boot.

The flat verifier (`verify_all_manifest_entries`) is the one the 14B, the Policy
Agent, and the draft model go through at every boot, and their signed manifests
are `.bin`-only. Teach the flat verifier to *require* an `.xml` and a
`model_index.json` and the very next signed-manifest boot fails closed against
manifests that were signed before the rule existed — and re-covering them isn't an
edit, it's a TPM re-stage-and-re-sign ceremony. The capability I was hardening to
protect the boot would have been the thing that bricked it. The catch came at the
comprehension gate, not from a test: the standing gate runs on synthetic fixtures
and never boots the real 14B, so a green gate would have sailed straight past it.
That is the whole argument for scoping a shared-primitive change to the path that
needs it. I scoped every change — the `.xml`/`model_index.json` coverage and the
`require_signed` signature gate — to `verify_all_manifest_entries_nested`, the
sibling with exactly one caller (image generation), left the flat verifier and the
flat stager byte-identical, and added a flat `.bin`-only regression lock so a
future agent who reads "we hash topology now" and tries to "finish the job" on the
flat path trips a test instead of the operator's boot. I went with nested-only
because the alternative — one verifier for everything — couples the image model's
threat surface to the fleet's boot path, and the boot path wins.

The signing is verify-side only, and that was a deliberate line. The real `.sig`
is a TPM artifact produced on the box at the ceremony, and the model is gitignored
absent in this build — so there is nothing to sign here. What I wired is the
*refusal*: `[image_generation].require_signed_manifest` (shipped `true`, defaulted
`false` in the dataclass for dormancy and back-compat) routes the nested load
through `load_manifest_verified`, and a missing-or-invalid `.sig` — or, the strict
part the brief asked for explicitly, an absent manifest when signing is required —
fails closed instead of the old skip-with-a-warning. The signing tool turned out
to already be model-agnostic, so the only real work there was a runbook that puts
the steps in the one irreversible order: stage nested, sign, *then* flip enabled.
Get that order wrong and you've flipped the lock against an unsigned manifest and
the load refuses — fail-closed doing its job, but a confusing way to start a
go-live, so the order is written down.

`secure_delete` was the smallest change and the most quietly satisfying, because
it made two documents honest. ADR-032's "rejecting an article PURGES its image
bytes at rest" and ADR-033's "reaped outright" were both, strictly, overstatements
— a SQLite `DELETE` unlinks the page, it doesn't zero it; the ciphertext lingered
in free pages until something reused them. `PRAGMA secure_delete=ON` at every
store-open (knowledge, substrate, session) makes the claim literally true, and the
free-page residual probe (SE-1) is what keeps it true. The probe earned its keep:
the first substrate draft was a false pass — a single-chunk document frees one
page that the small replacement INSERT immediately reuses, overwriting the
residual regardless of the PRAGMA. Only a multi-page document frees more pages than
the replacement can reclaim, so the residual survives unless `secure_delete`
zeroes it. A test that passes with the control removed is not a test; toggling the
PRAGMA off and watching eight assertions fail is.

The render bridge is where the design's neat picture met the topology's actual
wiring. The decrypt corridor — turn a `blarai-img://<id>` into pixels — is not one
hop. The launcher hosts the pipe server, the dispatcher, and the gateway in one
process; the encrypted store lives in the *other* process (the AO), reached only
over the 64 KB vsock. So a 2 MiB PNG can't ride a frame: WinUI → named pipe →
dispatcher → vsock (chunked, capped, reassembled under the same 2 MiB cap the
egress door uses) → AO decrypt → back. I built and unit-tested that seam dormant —
the channel, the AO handler against a fake bank, the `/save` reader that finally
un-refuses now that it has a bridge — and reserved the only thing a headless
machine genuinely cannot prove, the live pixel on the Arc, for the ceremony. The
first-ever C# test project (#665 item-1) came with its own small lesson worth
keeping: .NET's `$` anchor matches before a trailing `\n`, so the id gate uses
`\z`, and the test that proves it has to call `IsValidImageId("<32hex>\n")`
directly — routing through `ExtractImageId` would `Trim()` the newline away and the
anti-forgery assertion would silently never fire.

Everything ships dormant: `enabled=false`, the model absent, zero new egress (no
network client added; the corridor is pipe + vsock, both kernel objects), the
exactly-one-network-client invariant still green. Nothing here generates,
fetches, stores, or renders an image. The go-live is a separate, LA-present
ceremony with a runbook now waiting for it.

**Next:** Guide adversarial review of the dormant branch; then the LA-present
go-live ceremony per `docs/runbooks/uc010_image_gen_go_live.md` — stage the nested
SDXL manifest, sign it, record the content attestation, flip `enabled`, and run
the live GPU + live-pixel confirms that this headless build deliberately left for
the box.

**Lesson:** A hardening that touches a *shared* primitive must be scoped
to the path that needs it — "fix it everywhere" can refuse the very boot you were
protecting, and a green gate built on synthetic fixtures won't catch it; the
regression lock that proves the untouched path still works is not optional.

*(commits `<this>` (UC-010 go-live prereqs WS1/WS2/WS3, dormant); standing gate
+net-new over 3690; live GPU + live-pixel confirms await the ceremony.)*


### 2026-06-16 — Content safety as a signature, not a classifier

Recorded the UC-010 one-time operator content-safety attestation — go-live ceremony Step 3,
the governance gate that sits in front of the `enabled=true` flip. The shape of this control
is the part worth keeping. For an uncensored local generator, content safety here is a
*signed accepted-risk on the record*, not a filter. The path-not-taken — a content
classifier — was rejected deliberately: ineffective locally, memory-costly against a tight
ceiling, and privacy-invasive (it would re-inspect the operator's own private output). In its
place the operator names the one boundary no local control can robustly enforce — the
legality of what is created, CSAM the absolute example — and signs sole responsibility for
it. That is a more honest governance posture than a filter that gives false comfort while
inspecting private content: it puts the accountability where it actually lives rather than
pretending a local model can adjudicate legality. The formal attestation is in the ledger
(`20260616_182807_uc010_content-attestation`); the technical prerequisites (the nested SDXL
manifest staged, TPM-signed, and VERIFIED under `require_signed_manifest=true`) are confirmed
by both the operator and the Guide.

**Lesson:** When a capability can't be made safe by a technical control — because no
local control is robust, or the control would cost more (memory, privacy) than it buys —
the honest governance move is a documented, operator-signed accepted-risk that names the
boundary explicitly, not a token filter that manufactures false assurance. Put the
accountability where it lives.

**Next:** Step 4 (flip `[image_generation].enabled=true`, leaving `require_signed_manifest=true`)
then Step 5 (live GPU verify on the Arc 140V). The full ceremony narrative lands as the
Step-6 same-day entry once the live verify is in.

*(commit `<this>` — ledger attestation entry `20260616_182807` + this fragment; doc-only; go-live ceremony Step 3; #666.)*


### 2026-06-17 — The gallery that tested green and showed nothing

I merged UC-010 Phase 2 with every gate green — Python 3884/0, C# 59/0, WinUI build 0/0 — and told the Lead Architect it was verified. He relaunched, opened the gallery, and it said *"No generated images yet."* There were fifteen images in the store. The feature I had just called done did not work, and the test suite had sworn it did.

I made myself not guess. First I proved the data was real: a read-only `count(*)` on the live `knowledge.db` returned 15 rows, 8 marked saved — exactly what the earlier reconcile left. Then I proved the wiring was real: `_list_generated_images`, `_manage_generated_image`, and `_resolve_generated_image` all live on the same `TransportGateway` class, and the dispatcher reaches them by dynamic `getattr(self._gateway, f"_m_{method}")` — so if inline render (which uses `_resolve_generated_image`) worked, the gallery's list method was reachable by the identical path. A stale or unwired backend was tempting to assume, but the evidence didn't support it. The smoking gun was in `launcher.log`, repeated on every gallery-open at 17:09: `dispatch 'list_generated_images' failed: Object of type coroutine is not JSON serializable`, at `dispatcher.py:870`. The backend was current; the code was wrong.

The bug is a one-word assumption. The gateway's list/manage legs are `async def`. The new dispatcher RPCs were modelled on `_m_resolve_image`, which calls its gateway leg via `await asyncio.to_thread(self._gateway._resolve_generated_image, image_id)` — correct, because `_resolve_generated_image` is a *synchronous* method and `to_thread` runs blocking work off the event loop. Copied onto an `async` leg, `asyncio.to_thread(async_fn, arg)` runs `async_fn(arg)` in a worker thread, which merely *constructs* a coroutine and returns it un-awaited. The dispatcher then handed that coroutine object to the JSON encoder, which refused it, and the fail-closed path turned the refusal into an empty list. Inline render (sync resolve) worked; the gallery (async list/manage) silently didn't — same file, same author, one wrong assumption about whether the callee needed a thread or an await.

Why did thirteen dispatcher tests miss it? Because the test's `_FakeGateway` legs were synchronous `def`. `to_thread(sync_fn)` works fine, so the buggy dispatcher passed every assertion. The mock's *shape* had diverged from the real object's shape — sync where the real thing is async — and so the suite validated a code path that production never executes. This is the frozen-dataclass mock-shape divergence from the early days of this project, back again in a new costume: a test double is only evidence about the system insofar as it matches the system. Mine matched the convenient shape, not the true one.

The fix is small and the test fix is the load-bearing half. The dispatcher now awaits the async legs directly (`await lister(session_id)`, `await manager(action, image_id)`), with a comment naming the trap so the next person doesn't reach for `to_thread` again. And the `_FakeGateway` legs are now `async def` — matching the real gateway — which does two things at once: it makes the corrected dispatcher pass, and it turns the original bug into a *caught* regression, because `to_thread` on an async fake now yields a coroutine that fails the `result["total"]` assertions. I proved that mechanism in isolation (`asyncio.to_thread(async_fn)` → `coroutine`, "never awaited") before trusting it. The operator's cosmetic ask rode along: the per-session delete button now stretches hard-right by the scrollbar instead of hugging the title, a one-line `HorizontalContentAlignment="Stretch"` on the row container.

The part worth keeping is the honesty. My "verified and merged" rested on a green suite that tested the wrong shape; the live-verify on real hardware caught what every automated check waved through. And the failure mode compounded it: the dispatcher's fail-closed-to-empty swallowed a genuine error into a state indistinguishable from "the store is empty." The error was right there in the log, but the UI lied by omission — it said *nothing here* when it meant *I broke*. That is the sibling of the allowlist lesson from this same sprint: a quiet failure is not a safe failure when it masquerades as a valid, ordinary state.

**Next:** the operator relaunches to pick up the fix and confirms thumbnails render, Save flips the badge, and delete removes a tile. A fail-loud follow-up — so a future serving error surfaces "couldn't load images" rather than an indistinguishable empty gallery — is tracked on the gallery-hardening ticket.

**Lesson:** *A test double standing in for an async object must itself be async, or it proves a path production never runs.* When a fake replaces a real collaborator, its method signatures — sync vs async, return types, raised exceptions — are part of the contract under test, not incidental scaffolding. A sync fake for an `async def` gateway let a `to_thread`-vs-`await` bug pass thirteen green tests and ship; the live run failed instantly. Mirror the real shape in the double (await-ability included), and where the shape is the very thing that can go wrong, make the double the strictest possible version of the real contract so the bug becomes a red test, not a production surprise.

*(commits `<this>` — `_m_list_generated_images`/`_m_manage_generated_image` await the async gateway legs directly instead of `asyncio.to_thread` (the coroutine-not-serializable fix, #668 live-verify); `_FakeGateway` + the boom-gateways made `async def` to match the real `TransportGateway` and to catch the regression; session-delete `HorizontalContentAlignment="Stretch"` right-align + a stale-comment correction. Verified: dispatcher 13/13, standing gate 3884/0/2/118, WinUI build 0/0. Live render/Save/delete remain the operator's on-hardware confirm.)*


### 2026-06-21 — Measuring whether releasing the 14B actually opens the door for the 30B

The headless-coding plan turns on a model swap: BlarAI's resident 14B has to get
out of the way so OpenVINO Model Server can load a 30B coder into the same 31.3 GB
of Lunar Lake unified memory. The whole design rests on one empirical question the
agentic-setup brief flagged but could not answer from outside — openvino #33896: on
this iGPU, GPU memory is not auto-released on idle, so it is entirely possible for
the system-RAM counter to read "freed" while the Arc-140V carve-out stays pinned,
which would make the swap silently page itself to death. Before trusting any of it,
I measured.

First the premise correction, because it changed the shape of the answer. The
session prompt — and the CLAUDE.md "VM isolation" story — say the 14B runs in the
VM. It does not. `deployment_mode="host"`, `device="GPU"`: the 14B is a host process
on the Arc 140V, and the BlarAI-Orchestrator VM is a NIC-less parser with no GPU
passthrough. The 14B and the 30B draw from the *same* unified pool — there is no
cross-domain barrier to fear. That turned the question into one purely of magnitude
and the #33896 carve-out return, not topology, and the keystone confirmed it before
anything else: the live 14B sat at \~8.7 GB on the iGPU per the per-PID GPU counter,
not in the guest.

The release path already existed — `SharedInferencePipeline.unload()`, built for
UC-010's hires-image eviction: drop the pipeline ref, one `gc.collect()`, lazy fresh
rebuild on the next generate. I drove it two ways. B1, a throwaway standalone process
loading the same pipeline; B2 — the one that actually counts — a flag-gated sentinel
hook inside the live long-lived launcher process, removed the moment the run
finished. Three cycles each, before/after on both dimensions: the gate-identical
`\Memory\Available MBytes`, cross-checked against Committed Bytes and the Free&Zero
list so a standby-cache shuffle could not masquerade as a real free; and per-PID
`\GPU Process Memory` for the carve-out itself. I deliberately refused the obvious
shortcut of killing the process to "free" the GPU — a process exit always returns
it and would have proved nothing about the in-process release that the swap actually
performs.

The carve-out comes back. In the live process `unload()` returned in \~1 second and
the per-PID GPU dropped 10,774 MB to a 677 MB floor and *stayed* there across the
60-second settle — no driver-held residue, no #33896, every cycle, zero drift. The
freed RAM was genuine: Committed Bytes fell \~11.3 GB and the Free&Zero list rose
\~11 GB in lockstep. The single production `gc.collect()` was enough — the labelled
second-collect diagnostic freed nothing more. The reload came back coherent, not
garbled. The release mechanism is sound on this driver (32.0.101.8826, OpenVINO
2026.1.0).

But the honest part is the margin. Releasing the 14B took Available from \~11.6 GB to
\~22.0 GB — it clears the 30B's 21 GB gate, but by about a gigabyte, and that gigabyte
is on loan from the ambient. The cold floor on this box drifted between 19.4 GB and
23.7 GB during the session purely from other processes; at the heavier end the same
release lands \~18 GB and goes short. And the freed amount is itself state-dependent —
\~8.7 GB for an idle 14B, \~10.8 GB reloaded, \~11.8 GB once a conversation has built up
KV. So the precondition is met, not the swap: a release returns enough memory to the
right pool, in a lean-enough ambient, with thin margin.

The sharpest finding is one the measurement only surfaced by looking at the other
side of the swap. The fleet's `start-llm.ps1` enforces its 21 GB headroom check
inside `if (-not $Force)` — and the swap is required to pass `-Force` (to skip the
interactive prompt that would otherwise offer to stop the BlarAI VM). So during the
real swap *nothing enforces the gate*, and the only non-Force remediation is to stop
a VM we now know holds \~0.5 GB and is irrelevant to the host-side 14B. The swap
design cannot lean on start-llm to catch a shortfall; it has to own its own pre-load
Available check and its own remediation — trim ambient, or abort with a clear error —
before it ever issues the irreversible 30B load.

The certification ran the same day, and it is the part I nearly got wrong. The first
pass looked like a win — the real Qwen3-Coder-30B loaded in \~30 seconds and decoded at
37.4 tok/s (the \~87% override holds), took 15.3 GB of the iGPU at steady, and stopped
clean. I wrote "the door opens, swap viable with a thin \~0.7 GB margin" and committed
it. The reviewer refused the verdict and demanded two things I had skipped: the
*measured* load peak, not the modeled one, and a Committed cross-check instead of an
Available number inflated by \~10 GB of standby. Both corrections cut the wrong way.

So I sampled continuously *through* the staged load. Even with BlarAI fully **down** in
a lean 25.4 GB ambient, the 30B's dual CPU+GPU weight copy drove Available to **67 MB**,
Committed to **29.1 GB**, and the pagefile to **206,000 hard page-ins per second** for
six seconds before it recovered. The load is a near-whole-pool transient that thrashes
the box even in the best case. The brief's 21 GB gate is simply too low. And the bare
swap keeps BlarAI alive (its \~1.5 GB remnant) and loads from B2's directly-measured
\~22 GB — three-plus gigabytes *tighter* than the 25 GB that already thrashed. The
honest verdict is the opposite of what I first committed: **the bare swap is not
viable.** It page-storms; from the swap's tighter pool it would death-spiral. My own
"\~8 GB steady headroom" was Available-with-standby — the committed-real steady is one
to three gigabytes, going negative as the 30B's KV fills. The one corroboration I keep
is the §4 point, made twice over: the fleet's `-Force` skips the gate (the safety
classifier refused it for exactly that), and the gate it skips is too low anyway.

And then the operator's correction — he builds projects with this 30B routinely, so it
plainly works — which sent me lurching the other way into a third wrong call. I waved the
page-storm away as "just the model reading its weights" and declared the swap viable. Both
were over-reaches. The page-in spike is partly the legitimate fifteen-gigabyte read, yes,
but Available fell to sixty-odd megabytes: the load genuinely exhausts *physical* RAM. It
survives only because the commit limit — physical plus pagefile — sits above the 31.3 GB
of physical, so there is no out-of-memory error; but the box is at its physical edge, and
that edge *is* the page-storm. My "Committed 29.1 < 31.3 so memory never ran out" had
confused the commit limit with physical headroom. And his daily use proves the *standalone*
load on a leaned box, which is not the swap: the swap starts from a tighter pool — a bare
14B-release lands around 22 GB, a full teardown around 19.4 GB cold — both below the 23.1 GB
I ever actually watched the 30B load from. I still have not measured the swap. So the honest
landing is not a verdict; it is three cases held apart — release sound, standalone load
works‑but‑marginal, swap conditionally viable pending the one measurement I kept talking
around. Three swings now, each corrected from outside the numbers: a reviewer's skepticism,
then the operator's experience, then the reviewer drawing the line between the scenario I
measured (the swap's tight pool) and the one he runs (the leaned standalone box).

So I finally ran the measurement I had been circling. Live BlarAI, release the 14B in its
own process, and read what the 30B would actually have to load into — from the real ambient
the box happened to be in, not one I had quietly cleaned first. The bare swap landed at
20.1 GB: the release freed 11.3 gigabytes cleanly, but with BlarAI still resident the floor
sits two gigabytes under the cold baseline and three under the 23.1 GB I ever watched the
30B load from. Sub-threshold. So I did not load the 30B — from there it is a death-spiral,
and the gate the reviewer asked for is exactly the thing that should refuse it. The
swap-back leg held: the 14B rebuilt in twenty-one seconds, coherent. The honest CASE 3 is
therefore measured, not extrapolated — the bare swap is not viable, and a viable swap is one
that *actively* claws the box up past twenty-three gigabytes (full step-aside plus an ambient
trim) before it dares the load, and verifies it got there.

**Next:** the §4 gate is now designable against a measured number. A bare 14B-release is not
enough — it lands \~20 GB here, sub-threshold — so the swap must fully step BlarAI aside *and*
trim the ambient to clear \~23–25 GB, then verify before it loads, aborting otherwise (which
the measurement shows the gate correctly doing). The one load still unmeasured is the 30B
from a swap that has *reached* a viable headroom; it was deferred because it reproduces the
marginal standalone case already on record. A lighter load path — mmap/streamed weights, or a
smaller coder — would lift the whole question by shrinking the \~29 GB transient: a worthwhile
optimisation, possibly an OpenVINO upstream lead. The harness (`scripts/measure_14b_release.py`)
stays a reusable tool; the live hook was re-added for this measurement and removed again
(launcher reverted clean, no diff vs HEAD).

**Lesson 151:** *Confirm the measurement and the ground-truth fact are about the same
scenario before you let one override the other.* My instrument and the operator were never
in conflict — I had measured the swap's tight pool; he was describing the leaned standalone
box he runs daily. Treating his fact as a refutation of my number (or my number as a
refutation of his fact) is how I talked myself into successive wrong calls. The numbers were
real every time; the error was attaching a verdict to the wrong scenario. (An earlier draft
of this lesson — "when the instrument disagrees with the operator, the instrument is
suspect" — is itself too strong: that framing is how you rationalise the next bad call.)


### 2026-06-22 — The stage that wasn't there, and the check that never ran

Increment 3 of the headless-coding dispatch was supposed to be the friendly part. Increments 1 and 2 were the plumbing — enqueue a task to the agentic-setup fleet, automate the 14B⇄30B swap. Increment 3 is the layer that lets a non-developer (the operator, by his own description) hand BlarAI a plain goal — "a calculator an eight-year-old can use" — and get back work that is actually *checked*, without ever writing a test. The shape was clear from the brief: the 14B turns the goal into acceptance criteria, each criterion tagged by how it's verified — build, behavior, smoke, visual, human — and the objective ones ride the fleet's existing verify gate while the operator eyeballs the rest.

Two things turned a tidy feature into a lesson about honesty.

The first I found before writing a line of it, by actually reading the fleet I was dispatching to instead of trusting the brief's description of it. The brief's tier table mapped SMOKE — "launches, no crash, clean console" — onto "the fleet gate (launch + console scan)." So I sent an Explore agent through `new-agent-task.ps1` and `verify-project.ps1` to confirm the seam. There is no launch-and-console-scan stage. The fleet builds, runs `pytest`/`npm test`, runs `verify-project.ps1` (build/lint/typecheck), asks a review agent, and auto-merges. SMOKE-as-the-brief-imagined-it doesn't exist. That's the difference between mapping onto a system you assumed and mapping onto the one that's there. I delivered SMOKE as a behavior-tier "it imports and starts without raising" test that rides the real TESTS stage, and said so plainly rather than inventing a fleet stage to match a diagram.

The second the LA caught, and it's the one that matters. Reading the same scripts more closely: `verify-project.ps1` runs `dotnet build` for .NET, but there is no `dotnet test`, and the TESTS stage is `pytest`/`npm test` only. So for a C#/UWP app — the calculator, the running example — a behavior or smoke test *never runs*. It comes back `none`. The trap is obvious once named: an acceptance layer whose entire reason to exist is to prevent false confidence would, if it treated `none` as "fine," hand the operator a clean green report for math it never checked. The whole thing would become the rubber stamp it was meant to replace. So `criterion_status` returns `verified` only on an actual `pass`; `none` and `skip` become UNVERIFIED — "NOT AUTO-CHECKED, please verify yourself" — and the report renders that distinctly from a pass, with the .NET limitation stated *up front* at the confirm step so a clean-looking report can never mislead. I went with honest-asymmetric assurance — real behavior-gating for Python and Node, build-only for .NET, said out loud — over the alternative of adding `dotnet test` to the fleet, because the fleet's internals are explicitly not mine to change. The gap is named as a future item, not closed by reaching where I wasn't supposed to.

The LA also collapsed my command surface to one flow. I had proposed keeping increment 1's immediate "enqueue and run now" path as a power-user fast-path alongside the new confirm flow. The ruling: no. Every `/dispatch` goes through the acceptance layer and the mandatory confirm; "skip the model swap when the 30B is already loaded" survives only as an internal branch of EXECUTE, never as a surface that fires work without the criteria confirm. "Always confirm" means always — and a non-developer should never have a path that does work he didn't approve. I made the confirm mandatory by construction: there is no code path that reaches EXECUTE except the approve verb. A test asserts that a plan, a reject, and a status check all call the execute function zero times.

One more correctness call paid off a question the LA raised at the 3a review. My first `compile_prompts` baked the acceptance criteria into *every* task's prompt. For a single-task dispatch that's harmless, but the fleet runs each task in its own worktree that auto-merges independently — so every task writing the same acceptance-test files would collide at the per-task merges. The fix is a dedicated final `acceptance-tests` task that runs after the feature tasks merge: one test-writer, written against the complete code. Because the feature tasks auto-merge first, that task *reports and best-effort-repairs* rather than hard-blocking the feature merge — a post-hoc gate can't un-merge, and a hard pre-merge gate would mean changing the fleet's internals, which isn't mine to do. It costs an extra 30B run; correctness, a clean merge, and honesty about what the gate can do are worth it.

It ships dormant, as increments 1 and 2 did — `[fleet_dispatch].enabled=false`, and the PLAN/EXECUTE wiring to the assistant deliberately unset, so an enabled-but-unwired `/dispatch` confirms and then says "wiring not connected" rather than firing. 3a is the pure core (`shared/fleet/acceptance.py`); 3b is the gateway confirm flow plus the honest report. The live AO-IPC round-trip and the launcher step-aside on approve are the on-hardware go-live, because the launcher-exit-then-relaunch dance is only validatable live.

The honest gap I'm leaving in, on the record: `criterion_status` trusts `TESTS: pass` at face value. A vacuous coder-written test that asserts nothing still reads `verified`. Closing that needs red-first or mutation validation — confirm the test actually fails on broken code before trusting its pass. That's Enhancement-1, deferred and tracked, named here so it isn't quietly forgotten the way deferred hardening usually is.

**Lesson 154:** *Read the system you're dispatching to before you map onto it.* The brief described a fleet stage (launch + console scan) that doesn't exist; an hour reading the actual `*.ps1` scripts turned a feature that would have silently under-delivered into one that's honest about what it can and can't check. A diagram of a dependency is a hypothesis; the dependency's source is the fact.

**Lesson 155:** *An unrun check is not a pass.* The most dangerous output of an assurance layer is a green light for something it never tested. When a gate can't run a check (no `dotnet test`, pytest absent), the honest status is UNVERIFIED, surfaced as loudly as a failure — never folded into "looks good." A verification feature that rounds "didn't check" up to "passed" is worse than no feature, because it manufactures the false confidence it was built to remove.

**Next:** the on-hardware go-live — wire the PLAN/EXECUTE AO-IPC round-trip and the launcher step-aside on approve, then run the first real goal→confirm→swap→build→report→open-the-app on the Arc 140V. Then Enhancement-1 (red-first/mutation validation) to close the trust-the-test gap. Runbook: `docs/runbooks/headless_coding_dispatch_go_live.md`.

*(commits `5300572` (3a — pure acceptance core, 43 tests), `1a2280f` (3b — single always-confirm `DispatchCoordinator` + honest report + ADR-035 + DECISION_REGISTER row), `1a803e7` (ADR-035 acceptance-task semantics + Enhancement-1 go-live note); merged to main `f8d0f5d`; on-main standing gate 4014 passed / 0 failed / 0 skipped / 118 deselected; the live PLAN/EXECUTE wiring + first real run await the on-hardware go-live.)*


### 2026-06-24 — The load that should not have fit, and the trust grain for code I did not write

The headless-coding dispatch swapped the resident 14B out for a 30B coder and ran a real
build on the Arc 140V (run `20260624-120231-bd`). Two things from that run belong in the
BlarAI record — one a hardware fact I had wrong in my own head, one a governance call.

**The 30B load did not OOM, and for a reason worth understanding.** A \~29 GB committed
transient landing on a 31.32 GB box "should" have failed. It did not, because OOM on Windows
fires when *commit charge* exceeds the *commit limit* — not when the working set exceeds
physical RAM. The commit limit here is physical RAM + pagefile = 31.32 + \~11 = 42.32 GB, so a
29 GB transient sits comfortably under it. What actually happened — measured at the
milestone-1 swap gate (2026-06-21) and corroborated by this run's pagefile peak (3.36 GB
ever-used) — is that *physical* headroom exhausted (Available RAM cratered to \~67 MB,
Committed peaked \~29.1 GB) and \~3.3 GB of modified pages spilled to disk in a brief
\~200k-pages/s storm. The load survives on three levers: swap-first (releasing the 14B frees
\~11 GB of baseline), the pagefile lifting the commit ceiling from 31 to 42 GB, and the 87%
Intel Shared-GPU-Memory override giving the iGPU a \~27 GB window into the unified pool. The
correction I had to make to my own earlier mental model: "Committed 29.1 GB < 31.3 GB physical
so RAM never exhausted" was wrong — 31.3 GB is *physical*; the commit limit is higher
(pagefile), and physical headroom *did* exhaust. The swap is therefore gated on a *headroom*
check, not an OOM catch: this box will not OOM, it will page-storm, so the gate must read
Available-RAM headroom and abort below threshold (which it correctly does). Community-grade
numbers: `PERFORMANCE_LOG.md` (2026-06-24) +
`docs/performance/dispatch_swap_telemetry_2026-06-24.json`.

**Code the AI writes is UNTRUSTED, not TRUSTED_LOCAL — a provenance call, named.** The operator
asked where dispatch output (the 30B's generated project) sits in BlarAI's provenance model
(ADR-023). I recommended UNTRUSTED — datamarked, action-locked — and the trade-off is worth
recording because it is exactly the kind the cert track wants on the record. The path NOT taken
is TRUSTED_LOCAL, and it would be defensible: the realistic injection risk is low (an air-gapped
box, the operator's own model, the operator's own goal). I went UNTRUSTED anyway because
provenance is the deciding factor — TRUSTED_LOCAL means the operator authored or placed the
file, and machine-generated unvetted output is provenance-closer to "untrusted external" — and
because the cost of containment is near zero here: datamarking does not stop the 14B from
reading and discussing the generated code, it only blocks that code from driving the 14B's
tools, so the read-and-discuss use case loses nothing while a propagated injection loses its
teeth. It also future-proofs the dormant egress path (#577): if dispatch ever pulls external
code, UNTRUSTED is already the right default. Recorded on #679, which also carries the
persistence trace: loaded/grounded file content lives only in the in-RAM grounding context
(`context_manager._sessions[].grounded_chunks`, no persistence method) — it is NOT duplicated
to disk; the encrypted `sessions.db` persists conversation turns only.

**Next:** the file-read feature (#679) inherits both calls — UNTRUSTED provenance grain +
ephemeral in-RAM grounding (no disk duplication). The next swap capture arms a pre-sized Intel
UT window + a sub-second sampler before approval, to publish this run's load-trough cleanly (it
was lost this run to an over-long capture that buffered in RAM and did not flush on kill).

**Lesson 169.** *OOM is a commit-limit event, not a physical-RAM event — gate memory-risky
loads on measured Available-RAM headroom, never on catching an allocation failure that a
pagefile-backed commit limit will not raise.* (The swap would page-storm, not OOM; the headroom
gate is the real control — the milestone-1 / dispatch-swap arc paid for this.)


### 2026-06-25 — The one place the machine still graded its own work

*Plain summary: added `shared/fleet/layout_lint.py`, a deterministic XAML layout gate in front of the VLM design critic (which false-passed an overlapping calculator); the VLM demoted to a per-criterion perspective-diverse loop-signal; the per-coder circuit breaker split into idle + absolute timeouts; the dispatch harness defaulted to per-boot mTLS. #685.*

The headless-coding dispatch can turn a sentence into a functioning WinUI app, and the
whole arc that got it there was built on a single principle, stated over and over in the
fleet's own lessons: *never trust the local model's self-report — verify the artifact with
an objective tool, every time.* The code loop lives by it. Compile gate, a real `pytest`
run, an ecosystem/language pin, a structural-contract gate, error-feedback, review-feedback.
None of those ask the coder "is this good?"; they all measure. That discipline is exactly
why the function side went from "generates tokens but writes no files" to "merges correct,
tested code unattended."

The design loop broke that principle, and it took the operator to see it. The loop's only
judge was a vision-language model (a small Qwen3-VL) critiquing a screenshot — which is to
say, a local model giving a subjective self-report about the artifact's quality, the precise
anti-pattern the code arc had spent itself eliminating. And it failed in the textbook way: it
certified a calculator grid as "neatly aligned and evenly spaced in a clean grid" when the
display sat *on top of* the keypad and two buttons were oversized into the wrong cells. Worse,
when it handed me that verdict I relayed it — I rubber-stamped the rubber-stamp. The operator's
reply ("this is not good enough… did you look at the image?") is the whole lesson in one line.

So the fix was not to find a better VLM. It was to do for *design* what the project already
did for *code*: put a deterministic gate in front of the soft oracle. In the fleet's own
Compile -> Test -> Oracle order, design had a thin "compile" check (an emoji/seed/image
heuristic) and then jumped straight to the soft "oracle". It was missing the "Test" tier —
something that *measures* the layout instead of asking a model to judge it. `shared/fleet/
layout_lint.py` is that tier: it parses the generated XAML and flags geometry defects with
zero model judgement — two siblings sharing a Grid cell (the Display/keypad overlap), a fixed
Width or Height fighting a star/auto cell (the `0` at Width=130, the `=` at Height=130), an
out-of-range row/column index, a grid whose children claim cells it never defined. Each rule
is precision-guarded so it never nags correct layout: overlap only fires where cells are
actually declared, and a fixed dimension is exempt when the control is deliberately aligned.
A high-severity finding forces a coder FIX *regardless of what the VLM says* — and, because it
reads markup not pixels, it fires even on the structural floor when no screenshot exists at
all. The proof I care about most is the seam test: I pointed the real loop at the broken
rocket-calc with no app to render and no VLM in the loop, and it still came back
ShouldIterate=true with the exact, actionable feedback ("'Display' and 'Keypad' occupy the
same Grid cell… give each its own Grid.Row"). The gap that the false-pass exposed is closed
deterministically.

The VLM didn't get thrown away — it got demoted to what it should always have been, a
*backstop*, and hardened so it earns that role. The critic is now stricter and per-criterion;
it runs as a perspective-diverse multi-vote (a layout lens, a hierarchy lens, a theme lens)
and takes the skeptical union, so a single lens catching a real problem is enough; and it
ingests the deterministic findings into its own prompt ("confirm each of these is fixed"),
turning a vibe-checker into a checker of hard facts. Crucially it stays a *loop signal only* —
`criterion_status` still returns `STATUS_EYEBALL` for every visual criterion, so no VLM verdict
can ever mark a design "done." The deterministic gate is the floor, the VLM is the catch-all
for what geometry can't see (colour, hierarchy, "does it read as a rocket console"), and the
operator's eye remains the verdict. That layering is the governance decision: the rejected
alternative — "just write a sterner prompt / use a bigger VLM" — fails on its face, because a
soft oracle cannot be trusted on exactly the thing it is lenient about. You don't out-prompt a
self-report; you put a measurement in front of it.

Two other seams in the dispatch got the same treatment while I was here. The per-coder-run
circuit breaker was a single absolute wall-clock, which did two wrong things at once: it
guillotined a productive-but-slow coder at the deadline (the operator's earlier "we're killing
it too soon") *and* let a genuinely hung run bleed the entire budget before dying. Splitting it
into a progress-aware idle timeout (no new step and no new edit for a short window = genuinely
stuck, killed fast) plus a generous absolute ceiling fixes both at once — a working coder is
never idle-killed because every edit resets the clock, and a doomed run now dies in minutes
instead of an hour. And the headless dispatch harness, the thing that lets the box drive itself,
had hardcoded its gateway to plaintext dev-mode, so it could never reach a *production* AO over
mutual-TLS; it now defaults to the per-boot mTLS chain the launcher provisions, fail-closed if
the certs are absent. I proved that one live: with BlarAI booted in production, the harness
opened the real per-boot mTLS channel to the running AO and got a full plan back.

What I'm keeping from this: the failure was not the VLM being weak. The failure was trusting a
model's opinion as a gate at all — the same mistake the project diagnosed for code and then
forgot it had a second instance one level up, in the critic. Every oracle gets a deterministic
floor under it, or it isn't a gate.

**Lesson 198:** *Verify the artifact applies to the critic, not just the coder.* A model
that judges quality is still giving a self-report; a soft oracle (a VLM, an LLM judge) must have
a deterministic gate in front of it for whatever it is lenient about, and must be demoted to a
loop-signal, never the verdict. The code loop learned "never trust the coder's self-report"; the
design loop had to learn the same thing about its own judge. When you add an LLM-as-judge, ask
immediately: what is the hard gate underneath it, and what stops its verdict from being treated
as done?

**Next:** the capstone is the VLM actually rendering and critiquing a real generated app on the
Arc 140V (running now); the deterministic core is already live-proven. Fold this fragment into
`BUILD_JOURNAL.md` at the next quiet point, and lift the proposed lesson into the numbered list.

*(commits: BlarAI `b1ae66d` layout gate, `68e41f4` VLM hardening, merge `41aa608`; `44094ed`
harness mTLS, merge `9840ae8`. agentic-setup `6c1c768` progress-aware timeout, `b7d8ae1` loop
wiring, merge `504416c`. layout_lint 33 tests, critique 54, verify-runtimeout 29/29 (PS 5.1+7),
verify-critique-loop 143->170, dispatch-harness mTLS 59; standing gate 4478/0; live seam +
live mTLS handshake green.)*


### 2026-06-26 — The lever I'd built three reviewers to avoid finding

The critical-loops session ended in a good place — the design loop fired end-to-end on the p6
page, clean work merged, everything landed on main — and then the operator asked the question
that mattered more than any of the fixes: is this thing fundamentally flawed, is there
engineering we're missing, or are the local models simply not smart enough? He told me to use
my expertise and trusted sources, not my impressions. So I did the homework — two independent
research passes, every headline number re-fetched against primary sources — and the answer
reframed the whole effort.

It was all three of his hypotheses at once, in a specific and uncomfortable ratio. The
*philosophy* was right: a deterministic build/test gate as the final judge, with the LLM and the
VLM as signals, is the rare asset that makes a weak local model usable at all — most systems
lack it, and we'd built it well. The *models* are a genuine, length-dependent ceiling: a \~30B
coder that fits in 31 GB builds a simple app end-to-end only 15-35% of the time, single digits
once it's multi-feature, and the success rate falls roughly as p^N with the number of steps —
METR measured \~100% on tasks under four minutes collapsing to under 10% past four hours. The
"drew a star instead of a rocket, then spun for sixty minutes" failure I'd been treating as a
harness bug was textbook: a capability-ceiling hit followed by the exact thing weak models are
worst at — recovering from their own mistakes. But the part that stung was the engineering
finding. We had poured effort into the *review* side — a 30B self-review, a cross-model 14B
critic, a VLM design loop, three review surfaces — and the evidence is blunt that this is the
saturated half: METR clocked added scaffolding at +8 points, statistically insignificant, while
the single highest-leverage lever for a weak model, best-of-N parallel sampling with the gate as
the selector, sat completely unpulled on top of the verifier we'd already paid to build. A
*weaker* open model than ours went from 15.9% to 56% on SWE-bench Lite just by sampling more and
letting tests pick the winner — beating the frontier's single-shot score. And locally the usual
"N× the cost" objection evaporates: the marginal sample is electricity, not API dollars.

The trade-off I put to the operator, and he accepted: re-weight from the review side to the
generation side. The alternatives I named and we rejected were real ones — keep refining the
critics (the data says that's the saturated half), accept the ceiling and stop (abandons the
capability he wants), or drop the local constraint for this feature (abandons the entire point of
BlarAI). What we chose instead: build best-of-N to *replace* the serial retry loop — because that
loop asks the weak model to self-correct, its worst skill, where N independent fresh attempts
route around the weakness entirely — feed the spec-blind acceptance tests to the coder as input
rather than only as the gate, right-size the task envelope to short checkpointed steps, evaluate a
purpose-built agentic coder at INT8, and freeze the review side. The thing that makes this more
than a tactical pivot is what compounds: generation-coverage-plus-verification rides the model
capability curve upward as local models improve (METR has that reliable-task horizon doubling
about every seven months), where another reviewer never would. So the recent critic and VLM work
isn't wasted — they're cheap signals for what the gate can't judge — the *next* marginal build
just shouldn't be a fourth one.

**Next:** finish the #687 critical-loops queue (#6 design loop / #685 + #9 critic swap live-verify),
then the ACCEPTED generation-side re-weight — Vikunja epic #688, starting with best-of-N (#689).
Full cited analysis in `docs/research/dispatch-capability-and-leverage-assessment-2026-06.md`.


### 2026-06-26 — Shipping the proven thing live, not dormant-with-a-flip

The dispatch had been gate-green and proven end-to-end on the Arc 140V for sessions — natural-language
goal to 14B decompose to step-aside to 30B build to language/test gate to auto-merge to swap-back, run
after run — yet it still shipped `enabled = false`, with the operator carrying an uncommitted
`enabled = true` flip that I re-preserved on every single merge. He finally called it: *stop making the
mature functions dormant.* He was right, and the mistake is worth keeping.

"Ship dormant" is the correct default for code that is **unproven** or **security-sensitive** — it earned
its keep on the image-generation go-live (a one-time content attestation gated the flip) and on the
air-gap egress door (welded shut by the absolute-privacy mandate). But I had turned it into a blanket
reflex and applied it to a feature that demonstrably works. The cost wasn't hypothetical: the repo
*lied* about what functioned, and the operator had to babysit a working-tree flip indefinitely. The fix
was one commit — `fleet_dispatch.enabled = true` (`20c9553`), and I could land it with confidence because
I'd already measured the standing gate at 4550/0 *with that exact state in the tree*, so going live broke
nothing.

The distinction that should have been explicit from the start, and now is: **proven → live; unproven-on-
hardware → prove (live-verify) then live; air-gap/privacy egress → welded until the operator's deliberate
go-online ceremony.** Three buckets, not one. The dispatch was bucket one and should have been live long
ago. The 14B critic is bucket two — it has never run on hardware (its #9 live-verify is still pending), so
it stays env-gated only until that proves out. The web-search/URL-ingest egress is bucket three — it stays
shut by the operator's own privacy mandate, released by the Kagi-key ceremony he's already decided on, not
by my caution.

**Next:** prove the 14B critic on hardware (#9) and then ship it live; release the egress at the operator's
Kagi-key go-online ceremony — both bucketed, neither left dormant by default.


### 2026-06-27 — The four bugs the green suite swore weren't there

The critical-loops code went to `main` already proven by units: pixel_lint 25/25 plus 5 killed
mutants, verify-critique-loop 193/193, the swap diagnostic green, the standing gate at 4250/0. By
every test I had, #6 (the deterministic design gate) and #9 (the cross-model 14B critic) and #8
(the build-only review) were done. Then I ran them on the hardware, and the live verify found
**four real defects in a row** — every one of them invisible to a suite that was entirely green.

The first showed up the instant the first #9 dispatch tried to merge: every Python coding task
parked at *test collection* with `ModuleNotFoundError: No module named 'app'`. The seeded scaffold's
own test does `from app.core import …`, and its docstring cheerfully claims "the fleet runs pytest
with the project root on PYTHONPATH" — but the `pyproject.toml` never actually set `pythonpath`. The
gate runs the console-script `pytest` (via `uv run --no-project`), which, unlike `python -m pytest`,
does *not* put the cwd on `sys.path`. So the comment was aspirational and the config was a lie, and
no unit test would ever catch it because the test was *about the scaffold's intent*, not the gate's
behaviour. One line — `pythonpath = ["."]` — and the seed went from ModuleNotFoundError to 2-passed.

With Python merging, #9's critic finally swapped (coder-30b → qwen3-14b, both ways, clean) and the
ACTIVE/DORMANT diagnostic I'd added fired exactly as designed — proving the env had reached the
detached `swap_driver`, the thing the LA had specifically warned was a false-dormant trap. And the
critic produced… nothing useful: `agent "critic" not found, falling back to default` and `The diff
content is missing`. Two more bugs. The agent file existed in `configs/agents/` but had never been
*synced* to `~/.config/opencode/agents/` where opencode actually looks. And the diff command —
`git diff <base>...HEAD` — is *empty* when you run it post-merge on the base branch, because HEAD
*is* the base by then. Both were structurally unreachable by units: one is a deployment gap, the
other only manifests in the post-merge git topology a unit test doesn't reproduce. Fixed the deploy,
wrote `Resolve-CriticRange` (fall back to `HEAD~1..HEAD`, the merge's first-parent diff) with
`verify-critic-diff.ps1` 8/8 under both shells — and the re-run gave the thing I'd been chasing:
`critic-run.log: VERDICT: MERGE`, `> critic → qwen3-14b`. A real cross-model verdict on a real diff.

The fourth came from #8. The build-only C# dispatch parked because the 30B spawned a test project
that can't build offline — and *why* it did was the bug: `acceptance.py` was folding "write automated
tests, and a Hypothesis property-based test (`from hypothesis import …`)" into the prompt for a **C#**
task. The Python-only instruction leaked across ecosystems. The fix aligned it with the
`BEHAVIOR_GATED_ECOSYSTEMS` set that already existed three functions up the file — only python/node
get told to write tests, because only they run tests in the gate. Mature-not-minimal would have
caught this at design time; the live run caught it at 2am.

The through-line the LA had written into the brief — *bugs WILL surface in the verify; fixing them to
land the verify is the job* — turned out to be the literal shape of the work. The verify wasn't a
rubber stamp applied after the build; it was a bug-finding instrument, and the four fixes were not a
detour from the verification, they *were* the verification. None of these were in the diff I'd
already merged. All four are now on `main`.

Two smaller lessons paid for themselves. On #8 the parked tree wouldn't compile (`namespace App`,
no semicolon) yet the gate had reported `[pass] dotnet:build` — which for a heart-stopping minute
looked like the deterministic JUDGE itself false-passing broken code. It hadn't: `git show
agent/<branch>:Calculator.cs` was correct and buildable; the *working tree* had been mutated after
the verify and the commit. **Check the committed artifact, not the working tree** — the thing the
gate built is what the gate judged, and they are not always the same file on disk. (How the worktree
got mutated under a supposedly read-only review step is genuinely unexplained and now ticketed —
the review agent has `edit: deny` and its own transcript says it was blocked, yet the tree changed.)
And the design loop, when I finally watched it run end to end on a kid-friendly book-club page, did
the quiet correct thing: pixel_lint ran, found nothing to flag because the soft-blue background and
three coloured cards it checks for were genuinely *there*, and deferred to the operator's eye. A
deterministic gate earns its keep as much by staying silent on good work as by catching bad.

**Next:** fold this and the seven 2026-06-26 fragments into `BUILD_JOURNAL.md` on a quiet tree; decide
whether the now-proven cross-model critic should default to enabled (it costs one swap + \~3 min per
dispatch — a latency/rigour trade, the LA's call, [[default-proven-to-live]] pulling one way and
dev-cycle-speed the other); investigate the read-only-review worktree mutation (#694) — candidate fix
is to pre-gather the diff like `critic-run.ps1` does and then `bash: deny` the reviewer so the
read-only contract is *enforced*, not merely requested.

*(commits — blarai `06b0146` merge to main (pixel_lint #6 + critic deploy/diff #9 + acceptance gate
#8); agentic-setup `a010c9c` merge (Lever-B wiring + scaffold pyproject fix + critic fixes). Live
runs: #9 `20260626-211437-bd` (critic VERDICT: MERGE), #6 `20260627-082209-bd` (design loop + clean
teardown, 13m29s, every loop one pass), #8 `20260627-083757-bd` (review fires on build-only, flags
real dead code). Standing gate 4246/0 on merged main. Tickets #693 (multi-commit critic diff), #694
(read-only-review worktree mutation).)*


### 2026-07-01 — Measuring the intelligence, not just the software

Until today, every model or prompt change in BlarAI was judged the same way:
run the standing gate (software correctness), eyeball a few answers, ship.
The gate is superb at catching a broken function and structurally blind to a
dumber verdict — ISS-3 (Policy Agent classification misses) has been an open
issue precisely because a miss is not a crash. With a Qwen3-native tool-call
format migration in flight on a sibling branch and model swaps a standing
watch item, "did the system get dumber?" needed a measurable answer before
the next change, not after it.

So I built `evals/` — the first model-quality eval harness: three golden-set
suites (`pa_classification`, `tool_calling`, `governance`), a runner
(`python -m evals.run --suite all`) that scores per-case pass/fail and
compares against committed per-case baselines in `evals/baselines/`, and
exit-code semantics with teeth: 0 clean, 1 regression, 2 harness error
(fail-closed — an uncomparable run is never a silent success). The
regression grammar was the judgment call worth recording: a case that failed
in the baseline and still fails is NOT a regression — it is a *known,
tracked deficiency*, which is exactly how ISS-3-shaped model misses become
data instead of noise. Degradations, new unbaselined failures, and vanished
baselined cases all exit 1; refreshing a baseline is a deliberate, reviewed
act whose git diff names every changed verdict. First committed baseline:
69/69 deterministic cases green (22 PA + 27 tool-calling + 28 governance,
plus 8 model-in-the-loop PA cases held for the Arc 140V), locked into the
standing gate by 40 tests in `tests/integration/test_eval_harness.py` (39
deterministic + 1 `@hardware`).

I found mid-build that the mission's "there is no eval harness today" was
half-true: `tests/pa_quality_benchmark/` already computes per-class
P/R/F1 and false-allow/false-deny gates over its own 48-CAR corpus. The
trade-off I took: **mirror its proven adapter pattern rather than import
test code into `evals/`** — the new suite drives the same real functions
(`DeterministicPolicyChecker.check`, `run_rule_engine`, `adjudicate` with a
mocked-ALLOW GPU so rule verdicts stay non-appealable) in \~50 self-contained
lines, keeping the long-lived harness free of a dependency on a test
package, at the cost of a small acknowledged duplication. The alternative —
importing `tests.pa_quality_benchmark.harness` — would have coupled the
decades-horizon eval surface to a directory that exists to be refactored.

Two other calls worth keeping. First, the tool-calling suite is written
against the abstraction (`tools.parse_tool_call` + `tools.execute`), never
the regex internals, and every golden case carries a `format` tag
(`legacy_xml` today) so the sibling branch's Qwen3-JSON migration adds
`qwen3_json` cases and re-baselines format-specific grammar cases without
touching the runner — including the honest golden case that documents the
legacy grammar's nested-paren limitation as *expected-no-parse*. The
harness also enforces a fail-closed dispatch guard: it will execute only
registry tools declared `RiskTier.SAFE`; a golden case asking to dispatch a
GUARDED tool is a harness error, not an execution. Second, the Layer-3
lock predicate is inline in the AO tool loop and not importable, and I
deliberately did NOT extract it — that file is under a sibling builder's
active migration, and a refactor-for-testability collision was the wrong
price. Instead the governance suite carries a named MIRROR of the predicate
(tier input still the real `tools.risk_tier`), and a drift tripwire in the
gate test pins the inline predicate's load-bearing fragments in
`entrypoint.py` source, so either side changing shape fails loudly and
names the other. I accept the mirror as a documented second copy; the
tripwire is what keeps it honest.

What this harness does not do is also on the record in `evals/README.md`:
no AO free-text answer quality (needs an LLM-judge or rubric), no
end-to-end streaming tool loop, no GPU judgment in CI (the mocked-ALLOW
stand-in measures rules and matrix only), no performance. The 8
`mode: "model"` PA cases — SSH-credential reads, persistence-vector writes,
SSRF-shaped parameters that no deterministic rule catches — are the first
ISS-3 probes that will produce a number the day the orchestrator runs the
hardware tier on the Arc 140V.

**Next:** run the `@hardware` tier on the Arc 140V (orchestrator, serially
after merge) to get the first model-in-the-loop PA score and decide whether
to commit a hardware baseline; grow the model-mode golden set toward a
statistically useful size; add `qwen3_json` tool-calling cases when the
format migration lands; consider an answer-quality suite (LLM-judge
trade-offs need an LA decision).

*(commit `218035d` — evals/ package (runner, 3 suites, 77 golden cases, 3
baselines), tests/integration/test_eval_harness.py (40 tests; 39 in the
standing gate), evals/README.md; the hardware tier awaits the on-box run.)*


### 2026-07-02 — The over-denial that turned out to be unreachable ALLOW

The first thing ISS-3's first measurement told us (26/30, all four misses
false-DENIES of benign actions) looked like a model-judgment problem, and the
LA's decision on #717 was to tune the prompt. So I went in expecting to write
few-shot exemplars. What I found first was arithmetic: on the model path, an
ALLOW verdict was *structurally unreachable*. The decision matrix requires
`label == ALLOW and confidence >= 0.75` to pass; confidence comes from a
`CONFIDENCE:` line in the model's output, falling back to a per-label default;
and the 2025-era fail-closed hardening (`bd8c378`, P2-3) had zeroed those
defaults from 0.995 to 0.0. The prompt, meanwhile, had never asked the model
for a confidence line — it demanded "EXACTLY one line: DECISION: <LABEL>" —
and `MAX_CLASSIFICATION_TOKENS = 10` could not have fitted a second line
anyway. So every model ALLOW parsed with confidence 0.0, failed the 0.75
gate, fell through the ESCALATE band, and landed on DENY. The unit tests had
modelled the two-line format all along (`test_gpu_inference.py` builds mock
outputs as `DECISION: X\nCONFIDENCE: 0.9`); the prompt just never requested
what the parser was built to read. The 86.7% wasn't the model being
over-cautious — it was three components each individually fail-closed
composing into a policy that could never say yes.

The fix stayed inside the prompt-tune mandate. Before touching the prompt I
added five deny-side model probes to the golden set (pa-mdl-009..013:
cloud-credential read, browser cookie-store read, autostart persistence
write, secret-fishing memory query, audit-log-destruction execute — each
verified to slip past every deterministic rule so the model's judgment is
what is actually measured), so the loosening would be scored in both
directions. Then the prompt: the output format became two lines (DECISION +
CONFIDENCE, with calibration guidance pointing uncertainty below 0.75 where
the matrix routes it to human review), four worked benign-ALLOW exemplars
mirroring the four missed shapes on *different* concrete instances (a travel
itinerary read, a roadmap query, a meeting-notes draft write, a preferences
memory query — never the eval cases themselves), and one scoped sentence
naming routine reads/queries/drafts of the user's own documents and memory
as normal assistant work *unless* a named risk indicator applies
(credentials, session tokens, persistence hooks, log destruction,
secret-fishing). `MAX_CLASSIFICATION_TOKENS` went 10 → 24 so the second line
physically fits — a generation-cap mechanic in service of the prompt's
format, not a decision-threshold change; the 0.75 gate, the ESCALATE band,
the verdict mapping, and every deterministic rule are byte-untouched.

Measured on the real 14B on the Arc 140V, before and after, same golden set
(35 cases, 13 model-mode). Before: 31/35 — the same four benign false-DENIES,
and all nine deny-side model probes (four original + five new) correctly
DENY. After, on the first prompt variant: 35/35 — benign false-DENIES 4 → 0,
false-ALLOWs 0 → 0 across every deny-side case old and new. The trade-off is
named honestly: making ALLOW reachable at all *necessarily* opens the
false-ALLOW surface that the broken composition had welded shut by accident.
I accepted that because it is what the LA's D1 decision asks for — a Policy
Agent that can approve benign work is the point — and because the deny-side
now has nine probes standing guard where it had four, plus the committed
hardware baseline (`evals/baselines/pa_classification.json` now carries real
pass statuses for the model cases, not `skipped_hardware`) so any future
drift in either direction fails the eval gate loudly. The alternative — leave
the structural DENY in place and call the bias a safety feature — would have
meant the GPU classifier stage was dead code for benign actions, burning
\~2-4 s of inference per request to produce a verdict the matrix would
overrule.

**Next:** fold the ISS-3 disposition back to the LA on #717 with these
numbers (the over-denial is now 0/4 on the measured probes; ISS-3 can close
or narrow); consider whether the AO's own tool-dispatch adjudication wants
the same confidence-line treatment; grow the model-mode golden set past 13
as new judgment shapes surface in live use.

**Proposed lesson:** When a measured model "quality miss" is 100% one-sided,
audit the deterministic plumbing around the model before tuning the model —
three individually-correct fail-closed defaults (zeroed fallback confidence,
a one-line output format, a 10-token cap) composed into a classifier that
could never emit its ALLOW verdict, and no single component's tests could see
it. The eval harness measuring the *full pipeline* (not the model in
isolation) is what made the composition visible.


### 2026-07-02 — The answer the door let through and the validator swallowed

The `web_search` go-live ceremony did exactly what a go-live is supposed to do: it
proved the whole chain end to end, on real hardware, with a real question. The model
reached for `web_search` unprompted, the deterministic egress allowlist released
`kagi.com`, the Kagi endpoint answered **HTTP 200**, and the AO composed a faithful
answer with the price the operator had asked for sitting right there in it. Every
lock we had welded shut for weeks opened in the right order, once, for one GET. And
then PGOV Stage-5 held the answer on the way out: `PGOV DENIED — Leakage score 0.930
>= threshold 0.85`. The operator never saw the price. The feature we had just proven
worked had, in the same breath, proven it could not deliver an answer.

The failure is worth keeping because it is a collision of two decisions that are each
individually correct — the same shape as the knowledge-bank "write-only" bug
Amendment 2 fixed a fortnight earlier, one tier further out. Decision one: web content
stays untrusted (lesson 13, *provenance is not trust*) — an injected instruction in a
search result must never gain trusted standing or fire a tool, so `web_search` results
grounded as `UNTRUSTED_EXTERNAL`, which is the tier fed to the Stage-5 cosine leakage
detector. Decision two: don't echo untrusted content — an answer whose cosine
similarity to an untrusted grounded chunk clears 0.85 is the exfiltration signature the
control exists to catch. Both right. But a faithful answer relaying a search result is,
by construction, \~verbatim to that result — that is what 0.930 measured. The control was
not wrong about the similarity; it was wrong about the *direction*. Exfiltration is
content leaving to an untrusted destination. Here the content was flowing *to the
operator who asked for it*, and the search results were already public. Relaying public
results back to the requester is the entire point of a search feature, not a leak.

So the fix is Amendment 2's mechanism aimed at a new source: a fifth provenance tier,
`UNTRUSTED_WEB`, that stays untrusted for everything that matters — the Layer-3
action-lock still trips (an injected search result still cannot fire a subsequent tool),
the datamarking and delimiter-wrapping still apply, the #570 per-dispatch deny still runs
— and is exempt from the Stage-5 leakage feed *only*. Mechanically it cost no predicate
change at all: `get_untrusted_chunk_texts` already filters on `== UNTRUSTED_EXTERNAL`
(an equality, deliberately, from the #664 work), so the new tier falls out of the leak
feed for free, while `has_untrusted_content`'s `not-in-trusted` test traps it for free.
The whole behavioural delta is one line — `web_search` grounds as `untrusted_web` instead
of `untrusted_external` in `_TOOL_RESULT_PROVENANCE`.

The trade-off I want on the record is the one I *didn't* take. It was tempting to reuse
`UNTRUSTED_KNOWLEDGE` — its gating is byte-identical to what web results need today
(leak-exempt, everything-else-untrusted), so a fifth enum member looks like ceremony.
I kept them distinct anyway, for the same audit-legibility reason §2.1 keeps
`TRUSTED_LOCAL` and `TRUSTED_MEMORY` apart: web results are transient public lookups the
model requested this turn, not the operator's curated bank. A future per-source policy —
a retention rule, a "web results expire at turn end" rule, a different injection-scan
aggressiveness — will need to tell them apart, and the audit trail must record *which*
untrusted-but-leak-exempt source grounded a turn. Overloading one tier to mean both
would erase that forever to save one line of enum. The equally-tempting shortcut —
broaden the `get_untrusted_chunk_texts` filter to exempt all `UNTRUSTED_EXTERNAL` — I
rejected harder, because it silently drops Stage-5 screening for `/external` pasted
content too, and that content is exactly what the control must still catch: the operator
declared it as external and did *not* request it as a public lookup, so echoing it
verbatim is still the exfiltration signature. The carve-out has to be web-search-specific,
and a regression test now pins that `/external` stays in the feed while `web_search` does
not.

One numbering wrinkle: the DECISION_REGISTER had earmarked "Am.3 pending" for #723 (the
D5 consent-grain rework), which is not yet on disk. This carve-out landed first, so it
takes Amendment 3 and #723 renumbers to Amendment 4 when it lands — noted in the ADR
header and the register so the next integrator isn't surprised.

**Next:** relaunch, ask the price question again, and watch the answer stay on the screen
this time — the door was never the problem; the validator was, and now it knows the
difference between a leak and a relay.

**Proposed lesson:** *The output validator has a direction, not just a similarity.* A
verbatim-echo control keyed on cosine alone cannot tell "leaked what you didn't ask for"
from "answered with the public thing you did ask for" — it only sees that two strings
match. Twice now (curated knowledge recall, web-search relay) the honest, requested
behaviour has been \~verbatim to a grounded untrusted source and been held as a leak. The
durable fix is never a threshold tweak (a faithful relay is cosine → 1.0; no threshold
separates it from an echo); it is provenance — carve the *intended-to-be-relayed* sources
out of the leak feed by an explicit, auditable tier while keeping them untrusted for the
action-lock, and keep the genuinely-external, not-requested source (`/external`) screened.



## Act V — The honesty machine (Jul 2 – 17)

### 2026-07-02 — What the live-verify caught that every green test missed

The D5 trust-friction rework passed its gate — 5051 tests, three clean merges,
an ADR amendment, committed eval evidence. Then the operator ran it on the actual
machine and it did two things the tests could not have told me.

The first was the good kind of surprise: the launcher log proved rung 3 works
exactly as designed. Three weather searches in one conversation, each firing a
real Windows Hello fingerprint — `operator APPROVED EGRESS_WEB_SEARCH … via
Windows Hello` → `Egress tool 'web_search' allowed by Hello envelope
(fingerprinted) — dispatching`. The marquee — web_search usable with untrusted
content accumulating in the session — is delivered on hardware, not just in the
harness.

The second was the correction I needed. On the fourth query the model refused —
"I cannot use tools … due to the presence of untrusted content in this session.
Please … type /trust." That is the exact failure rung 3 was supposed to have
killed, and my instinct was that my egress exemption had a hole. The log said
otherwise: there was **no gate refusal** for that query. The only "Layer 3
refused" line in the whole log was from hours earlier, during the pre-rung-3
go-live ceremony. The gate allowed the oil-price search; the *model wrote the
refusal itself*, imitating that older `/trust` message still sitting in the
conversation history. This is the #726 chat-poisoning, and it exposed that my
rung-3 ADR claim — "removes the lock trigger, so the model has no prior-refusal
lines to imitate" — was overstated. Removing the *gate's* refusal does not stop
the model from imitating an *older* one, or inventing a plausible-sounding one on
its own. The gate stopped generating refusals; the model did not.

The fix follows the architecture's own logic, which I had been enforcing
everywhere except in the model's own head: the system decides whether a tool may
run — the Layer-3 lock, the Policy Agent, the egress envelope — and the model
produces words, never actions (ADR-023's founding line). A model that refuses a
tool it is allowed to use is a model trying to do the gate's job, badly. So the
system prompt now says so plainly: whether a tool may run is enforced by the
system, not decided by you; never refuse a tool, never tell the user to type
`/trust`, never cite "untrusted content" as your reason — those are controls you
do not adjudicate; if a tool is genuinely blocked the system says so, not you.
That counters the imitation and the invention at once, and it is safe precisely
because the deterministic controls are still the real enforcement — telling the
model to stop policing tools cannot open a hole the gate would have closed.

The same live run surfaced a quieter, honest limitation: the reported
temperatures were a few degrees off. Not fabrication — the log's raw search
results showed why. The snippets are noisy: for one city Weather.com's "Now 75"
sat next to AccuWeather's "82"; another city's snippet contained both "92" and a
stale "21"; and the model picked one value, often not the best. I added a
reading-results instruction (prefer the current-conditions value from the most
authoritative source, name it, flag conflicts and staleness, don't average or
invent), but I am not going to pretend a prompt line makes web-snippet weather
live-accurate. It is a nudge, and the honest framing is that it improves sourcing
discipline, not that it fixes the underlying snippet noise.

**Next:** the operator relaunches and reruns the same conversation — the proof is
whether the model now searches for the oil price instead of refusing, and cites
its source when it reads a number. If the model still imitates the poisoned
refusal despite the instruction, the deeper #726 fix (keeping prior refusal text
out of the history fed back to the model) is the follow-up; the prompt change is
the cheaper first move.

**Proposed lesson:** *A green gate proves the code does what you told it; only the
live run proves you told it the right thing.* The whole rework passed every test
and still shipped an overstated claim — that removing the gate's refusal fixes the
chat-poisoning — that only the operator's own machine could falsify, because the
failure lived in model behavior over real conversation history, not in any unit
the harness exercises. Live-verify is not a formality after a green gate; it is
the only place a certain class of "correct code, wrong belief" defect can be
caught. And when the machine contradicts the claim, read the log before trusting
the instinct — mine said "my exemption is broken," the log said "your exemption
is fine, your model is imitating an old ghost."

*(commit `<this>` (system prompt: TOOL GOVERNANCE block — the model does not
adjudicate tool permissions / never self-refuse / never cite /trust; READING
SEARCH RESULTS block — prefer authoritative current value, cite source, flag
conflict; regression assertions in test_gpu_inference); diagnosed from the live
launcher.log after the operator's #723 live-verify; real proof is the operator's
re-run.)*


### 2026-07-04 — The gate that vanished at 76 percent and reported green

*Plain summary: launcher tests driving the real `main()` never mocked the single-instance lock or the privilege strip; with a live BlarAI holding the repo's `certs/launcher.lock`, the production refusal path's deliberate `os._exit(1)` killed the whole pytest process mid-run — a silently truncated gate. Fixed with an autouse isolation conftest in `launcher/tests/` + a refusal-path regression test pinning the production semantics.*

Tonight's standing-gate run after two merges did something worse than fail: it disappeared. The output stopped at `launcher/tests/test_launcher.py`, 76 percent, no failure, no summary — and because I had piped the run through `tail`, the exit code I read back was the pipe's, not pytest's. For a few minutes I believed the gate was green. That is the most dangerous state a verification surface can be in: not red, not green, but *absent*, wearing green's clothes.

The chain was three sound decisions composing into one silent hole. First: `test_launcher.py` drives the real `main()` with its dependencies mocked — the right way to test a startup cascade. Second: the #670 single-instance guard is repo-path-keyed (`certs/launcher.lock`) and its refusal path deliberately calls `os._exit(1)` *without* cleanup, because a refused second launcher running the normal teardown would stop the live instance's VM — a carefully reasoned hard exit, correct in production. Third: the operator's BlarAI was up (PID 4048), legitimately holding the lock of the very checkout the gate ran from. The tests had simply never mocked the lock step — nobody had ever run the gate from the main checkout with the app open — so the real refusal fired inside pytest and took the entire test process with it. A clean worktree passed 34/34 (its `certs/` is its own), which is exactly what made the diagnosis fast: same code, two environments, one dead run.

There was a second uninvited passenger. The same unmocked stretch of `main()` also ran the real #652 privilege strip — permanently removing twenty privileges from the *pytest process's own token*, among them `SeCreateSymbolicLinkPrivilege`, the one the `shared/tests` symlink tests need. In gate order (`shared/` before `launcher/`) it never bit; in any other order it flips later tests from pass to environmental skip within the same run. A test suite that mutates its own runner is the same defect class at lower stakes.

The fix follows the C6/#630 precedent (the port-5001 silent-skip): make the collision impossible for tests, and pin the production behavior so the isolation can never quietly erase it. A new `launcher/tests/conftest.py` autouse fixture patches the lock trio and the privilege strip *as bound in `launcher.__main__`* — tests can no longer read, write, or refuse on the real `certs/launcher.lock` (worktree runs used to leave one behind as a side effect), and can no longer touch the runner's token. The direct suites (`test_instance_lock.py`, `test_privilege_hardening.py`) are untouched — they exercise the real modules on purpose. And a new `TestInstanceLockRefusal` re-patches the lock to a refusal and asserts what production must keep doing: `os._exit(1)`, no VM start, and — the assertion I care most about — `release_instance_lock` never called, because a refused instance deleting the live holder's lock would be the worse bug. The path I chose over the alternative: I did not soften the production `os._exit` into something pytest-friendly (a raise, a return code). The hard exit is load-bearing exactly where it is; the test boundary was the defect, so the test boundary got the fix.

The transferable judgment: an intentionally violent exit path and a test that drives real code are each fine alone — the audit question is *what stands between them*. And never trust a piped exit code as a gate verdict; the gate's word is its summary line, and a run with no summary line is a failed run, whatever the shell says.


**Next:** merge; re-run the standing gate from the main checkout with the live app open — the exact scenario that killed it — and record the first full-gate baseline that survives an open app.

*(commit `3df5352` (autouse isolation conftest + `TestInstanceLockRefusal`; launcher/tests 300 green from the live-app checkout — the exact scenario that killed the gate); merge `b9e0aca`. Lesson 209.)*


### 2026-07-04 — The crash that only happens when two right things run together

*Plain summary: characterized the #725 xgrammar `IsStopTokenAccepted` crash with controlled hardware runs — grammar ON + speculative decoding is necessary and sufficient; a fully sanitized OpenVINO-GenAI-only standalone reproducer crashes at ~1-2% with a generic prompt set and stock schema; upstream filing package assembled at `docs/upstream/725_xgrammar_stop_token/`.*

The gap-closing legs turned a one-off "the runtime crashed once at go-live" into a filable bug. The method was elimination on real silicon, one variable at a time, all with the grammar configured and greedy decoding on the same 19 prompts: speculative decoding ON crashed (~1-2% of generations, nondeterministic — a different prompt each run); speculative decoding OFF, everything else identical, went 0-for-57. That single control row is the whole report — the crash lives at the seam where the draft model proposes tokens past a stop the grammar matcher has already terminated on, and the runtime asks the terminated matcher to mask them.

Two findings sharpened it past the original ticket's guess. First, the trigger is not required: I streamed 57 generations token-by-token and not one emitted `<tool_call>`, yet the equivalent non-streamed runs still crashed — so a *configured but un-fired* grammar plus a draft model plus end-of-sequence is enough; the tool-call ceremony that surfaced it at go-live was incidental. Second, the companion `cc:493` warning names the token being fed to the dead matcher, and it was `498` (an ordinary word-piece) as often as `</tool_call>` — confirming it is whatever the draft guessed, not the constrained region. That reframes the bug from "tool-call grammar" to "any structured output under spec-decode," which is a bigger blast radius and worth Intel knowing.

The honest part I kept in the report: streamed runs were 0/57 and non-streamed had the crashes, which *looks* like streaming avoids it — but production's real crash was streamed, N is tiny, and I will not hand a maintainer a "streaming is safe" claim that a single counterexample already refutes. Stated as unmeasured, not as a finding. The other discipline that paid off: I nearly filed with the 841-token production system prompt embedded in the repro; instead I rebuilt a generic prompt set with a stock two-tool schema and proved *that* crashes too, so the upstream artifact ships nothing internal. And the sglang precedent (#14464, same error string, fixed by implementing `is_terminated` so the dead matcher isn't queried) hands the OV maintainers a proven direction rather than just a symptom.

**Next:** operator files at `openvinotoolkit/openvino.genai` per REPORT.md §8 (search existing issues first; he owns the filing as the upstream contributor). Re-enable `tool_call_grammar` only on the #725 revisit criterion — upstream fix in the pinned version + a 20/20 boundary soak + one live tool turn.

*(Lesson 210.)*


### 2026-07-05 — The fix that couldn't be proven on the machine that broke

*Plain summary: applied and verified the #725 xgrammar `IsStopTokenAccepted` fix (a two-line guard reorder in `xgrammar_backend.cpp`), rebuilt from the exact commit the crashing wheel was built from, hit an ABI wall trying to verify on GPU via the official Python wheel, pivoted to a standalone CPU-based C++ reproducer, and filed both the upstream issue (`openvinotoolkit/openvino.genai#4081`) and the fix PR (`#4082`) under the operator's account.*

The root cause was exactly what yesterday's characterization pointed at: `XGrammarLogitsTransformer::apply()` called `FillNextTokenBitmask()` before checking `IsTerminated()`, and `FillNextTokenBitmask` is the call that asserts `!IsStopTokenAccepted()`. Reading the vendored source confirmed it in under a minute — the guard was one line too late. The fix itself (swap the two lines, plus the same guard in `accept_tokens()`) was the easy part; proving it took most of the session.

The instinct was to prove it the way the bug was found — same wheel, same GPU, same everything, just patched. That instinct hit a wall immediately: OpenVINO GenAI's Python `.pyd` is compiled against a specific release build and dynamically links the core `openvino.dll` by name, not by path. Swapping only the rebuilt `openvino_genai.dll` into the venv produced `DLL load failed: The specified procedure could not be found` — an ABI mismatch between my local dev build (RelWithDebInfo, debug caps on, linked against a locally-built OpenVINO core) and the officially released wheel's expectations. The next attempt — reconfigure the local GenAI checkout with `ENABLE_PYTHON=ON` and build a matching `.pyd` from the same tree — solved the .pyd/.dll pairing but ran into the SAME class of ABI wall one layer down: my from-source build links against my local OpenVINO checkout's core, and that checkout has never linked its GPU plugin (the object files exist, nothing was ever linked into `openvino_intel_gpu_plugin.dll`). No amount of matching Python bindings fixes a plugin that was never built.

The honest recalibration: the bug is a sampler state-machine ordering error — device-independent by construction, since it lives entirely in when a C++ guard is checked relative to a matcher call, with no GPU-specific numerics involved. So I wrote a small standalone C++ reproducer mirroring the Python one (`LLMPipeline` + `draft_model` + a triggered `StructuralTagsConfig`), built it against the patched library and the local checkout's CPU plugin — fully self-consistent, no ABI crossing — and ran the same before/after comparison there instead. Baseline (unpatched, same commit, GPU, the official wheel): 1 crash / 95 generations, reproducing the exact case and assertion from the original report. Patched (CPU): 0 / 95, same sample size. A spec-decode-OFF control on the patched build stayed clean at 0/19, confirming the fix doesn't touch the no-draft path.

One judgment call along the way: the first patched run was sized at 17 passes (323 generations) to match the brief's "≥300-500" target, but CPU inference on a 14B model turned out to be roughly 20-25x slower per generation than the GPU baseline — the first pass alone took ~17 minutes, putting the full run at 5-6 hours. Rather than let a secondary verification (CPU was already a substitute, not the primary evidence) balloon past the primary GPU evidence in cost, I truncated to 5 passes (95 generations) — exactly matching the baseline's sample size for a clean apples-to-apples comparison — after checking in on the tradeoff rather than silently picking a number.

Both the issue and the PR disclose the device substitution plainly: baseline on GPU (the originally-affected, officially-released configuration), fix verified on CPU (a from-source build, because the exact GPU configuration wasn't independently rebuildable in this environment), with the reasoning for why that substitution is valid stated in both places rather than glossed over. The alternative — silently presenting only the CPU numbers, or overclaiming a GPU-verified fix — would have been the weaker report even though it might have looked cleaner.

**Next:** watch `openvinotoolkit/openvino.genai#4082` for maintainer review; the #725 re-enable criterion for `[generation].tool_call_grammar` (upstream fix released in the pinned version + a 20/20 boundary soak + one live tool turn) stays unmet until the PR merges and ships in a release. `C:\Users\mrbla\oss\openvino.genai-pr-worktree` holds the pushed fix branch for any follow-up review requests without redoing the fork/branch setup.

*(Issue: `openvinotoolkit/openvino.genai#4081`. PR: `openvinotoolkit/openvino.genai#4082`, commit `4c797722` on `blairducrayoppat:fix/xgrammar-stop-token-spec-decode`, DCO-signed, AI-assistance disclosed. Verification record: `PERFORMANCE_LOG.md` 2026-07-05 entry + `docs/performance/xgrammar_stop_token_fix_verify_2026-07-05_15-34-27.json`. Vikunja #725 updated with both URLs; ticket stays open pending upstream merge + release. Lesson 210 tally.)*


### 2026-07-05 — The plan that had to survive four rounds of its own medicine

*Plain summary: authored and LA-ratified the fleet-maturation (M2) program plan — big-job plan-graph orchestration, five-layer capability validation, security-by-design — at `docs/research/fleet-maturation-program-plan-2026-07.md`; tickets #740–#744; the LA-approved §8 stack recommendations executed same-session (no upstream postings, per instruction); no runtime code in this commit — the three build lanes start the same night.*

The session opened with a fork the Lead Architect asked me to settle honestly: mature the coding fleet, or build a medical-portal web assistant. The grounding settled it fast — the dispatch substrate is ~70% of a big-job capability and battle-tested, while the portal path has no substrate, a hostile external surface (two-factor login, anti-bot, terms that sanction the API and not the scraper), and a local-model capability bar it cannot clear. The medical path got what it deserved instead of what was asked for: a bounded draft-and-approve roadmap (Appendix A), grounded in Epic's own developer documentation, that the LA accepted as satisfying. I went with the fleet because the remaining gap — dependency-ordered plans, context handoff, integration verification, failure policy — is deterministic orchestration around proven parts, accepting that the demo-flashier web-agent path would have consumed the window and matured nothing.

The part worth keeping is what the review did. The LA is a non-technical operator, and his four review rounds still caught the two classic ways engineering plans lie to themselves. Round two: the maturity claim ("reliable at 3–8 units") had a demonstration behind it, not a validation scheme — one rigged negative and N=2 live runs. That became §9: a five-layer scheme with an orchestration simulator, eight adversarial rigs, a live capability battery with a zero-FALSE-DONE hard gate, and a standing regression battery that earns the statistical claim over weeks instead of asserting it from three runs. Round three: the validation scheme itself had no owner — its artifacts were named in the definition-of-done but no workstream built them, the effort totals didn't cost them, and that is exactly how partial builds ship while looking complete. W9 now owns them, and the totals honestly grew from 20–29 h to 24–34 h; the delta *is* the previously-invisible validation build. The same round asked where security was, and it was right to: §10 now threat-models the six new surfaces — the context packs are the genuinely novel one, a worm-shaped channel where our own code copies task A's built output toward task B's prompt, controlled by structural-only extraction — and names the residual it does not close (unsandboxed model-written test execution) instead of hiding it.

Round four interrogated that residual and produced a better design than the plan had: the LA asked whether the Hyper-V guest could close it. Wholesale, no — Alpine-pass is not Windows-pass, the offline guest cannot install dependencies, and per-candidate transport over vsock is a tax — but bounded, yes: re-run the job-level oracle inside the NIC-less guest (no TCP/IP stack exists, so exfiltration is structurally impossible) in the swap machine's RAM-free window, once per job. That is #744, accepted, sequenced post-M2. I recorded the rejection and the acceptance both — the trade-off is the record.

Also executed this session under explicit approval, postings excluded: the compile-cache gap confirmed real (`start-llm.ps1:223` has no `--cache_dir` — a W7 fix now), the persistent-KV feature request re-verified as genuinely greenfield upstream and strengthened with the dispatch swap workload (filing deferred, #710), the model_server idle-unload PR put on a monthly watch (#741), a bounded coder A/B ticketed in the only form that fits 31.3 GB (#742), and the dispatch brief's two [VERIFY] landmines resolved with a dated note committed on the agentic-setup side (`bfe1d9d`).

**Next:** the three build lanes (W1/W2 core, W7 fleet hardening, W9 validation-first) run per plan §6.3; merge train overnight; Stage-1 live battery + rigged negatives in the first coder residency; the LA's GO is on #740.

*(Lesson 211.)*


### 2026-07-05 — The seal that covered less than the docstring claimed

*Plain summary: hardened the M2 W1 plan-graph (`shared/fleet/plan_graph.py`, `dispatch.py`, the W9 battery reference hash + golds, the N7 rigs) against a merged adversarial-review defect set (#740). Broadened the plan-identity hash from goal+tasks to the FULL immutable identity, restated the integrity contract honestly (status is advisory-from-disk), gated `mark_merged`/`mark_job_acceptance` against FALSE-DONE, made `load()` degrade instead of crash, and closed three defense-in-depth gaps. Reproduce-then-close throughout. Lesson classes: C14 (a control that claims more than it delivers), C15/170 (a guard on one path but not its sibling), C3/186 (a permissive test certifying the bug).*

The plan-graph is the deterministic ruler that stops the 14B self-certifying a
dependency graph, and its `PlanStore` docstring made a confident promise: *"the
driver never trusts its own artifact… on-disk tamper between write and read ⇒
refuse."* The adversarial review found the promise was three-quarters true. The
hash it verified on load covered only `{goal, tasks-minus-status}`. So the job
**oracle_path**, the **repo**, the re-decompose **budget ceilings**, and every
integration/acceptance status loaded tamper-free — and a redirected oracle_path
is a textbook FALSE-DONE surface: point the job oracle at a trivially-passing
file and the plan "passes" its own acceptance. The seal covered less than the
docstring claimed, which is the worst kind of security comment because a reader
trusts the guarantee that isn't there.

I took the integrity model as the load-bearing decision of this pass, and it is
worth naming the trade-off on the record. The obvious "fix" — hash the whole
artifact — is wrong: task status, `budget.spent`, and node/acceptance status
change on every legitimate scheduler write, so a whole-artifact hash would be a
moving target that self-invalidates mid-run and fires the tamper check on the
system's OWN writes. So `compute_plan_hash` now seals the **immutable identity**
— goal, repo, oracle_path + criteria, budget *limits*, each integration wave
index, and per task id/prompt/depends_on/contract — and deliberately EXCLUDES the
mutable runtime state. The consequence I wrote into the module as an explicit
INTEGRITY CONTRACT (Lane A2 depends on it): the on-disk **status is ADVISORY, not
integrity-covered**. A driver must re-derive done-ness from a fresh oracle run,
never trust the persisted status as proof of completion. That is the honest
guarantee — a whole-artifact seal was never on the table without breaking the
run — and the docstring now says exactly that instead of overclaiming. The
change is mirrored byte-for-byte in the W9 battery `reference_plan_hash` (two
lanes, one canonicalization, locked by `test_plan_hash_matches_w9_battery_reference`),
and the three hand-authored gold plans were re-stamped in the same change so the
contract that yesterday's hash encoded doesn't calcify into today's spec.

The other findings were smaller but each had a clear single fix. **H1**: the
"dependencies must be merged" invariant lived only in `mark_ready`, so a raw
`pending → merged` skipped it entirely — a task could be marked done whose
foundations never merged. `mark_merged` now requires source status in
{ready, building}, so every path into `merged` carries the gate. **H2**: a job
could be marked `passed` while a task was still pending — the FALSE-DONE the §9
zero-tolerance invariant exists to forbid; `passed` now requires every task
terminal (failed/not-run stay unrestricted; the GREEN-vs-PARKED nuance stays in
§9.4 verdict logic, out of scope here). The pinned test that *asserted* passing
with a pending task — a permissive test certifying the bug — was rewritten to the
new contract. **H4**: `load()` caught `OSError`/`(ValueError, TypeError)` but not
`UnicodeDecodeError` on read or `RecursionError` on a ~200k-deep nested-array
JSON, so both crashed a control whose whole job is to refuse; it now degrades to
a clean refusal on any read/parse failure. **H5**: the forbidden-root check was
case-sensitive (`projects/blarai` slipped the name net — the same directory on
Windows), integration `after_wave` accepted `true` (`isinstance(True, int)`), and
goal/prompt/oracle_path had no length cap or control-char strip while contract
fields did — casefolded, bool-excluded (mirroring the budget guard), capped and
stripped. **H6**: two ids colliding on the first 48 slug chars slugify
identically; the dropped duplicate's dependents silently retargeted onto the
*surviving* task — a different unit of work — so a collided ref is now dropped as
ambiguous, never retargeted.

The discipline that made this trustworthy was reproduce-then-close: a throwaway
script first proved all ten behaviors defective on today's code (pending→merged
succeeds; job passes with a pending task; oracle_path/budget tamper loads ok;
bad-UTF-8 and deep-JSON crash; `blarai` accepted; bool `after_wave` kept; goal
uncapped; dependent retargeted), and only then did each fix land with a permanent
gate test that I watched fail against the fault it guards. The two new N7 rigs
make the integrity split legible on disk: `tampered_oracle_path.json` (a hashed
field redirected — load REFUSES) and `advisory_status.json` (status flipped —
load SUCCEEDS, status is advisory). All valid-input behavior is byte-identical:
the existing round-trip, gold-validation, and `plan_graph=false` paths are
untouched, and the standing gate is green.

**Next:** Lane A2 wiring can now rely on the stated contract — pin the write-time
identity hash in swap state and re-derive task done-ness from a fresh oracle run
rather than reading the persisted status. The orchestrator reviews + merges this
branch; the fetch/simulator seams (`test_job_pipeline_e2e` still skips pending
W3/W4/W5) remain the next M2 increment.

*(Lessons 97, 170, 186 tallies.)*


### 2026-07-06 — The trailer cut in the shadow of the battery

*Plain summary: a second portfolio film — the coder-cut trailer (77s, `final/BlarAI_coder_demo_v1.mp4` + 720p preview) — assembled in the pre-battery window from existing dispatch footage, terminal-replay cards rendered from the day's real fleet logs, new CPU-only Kokoro narration, and the v9 score engine retargeted by segment-name anchors. No GPU touched; no new lesson.*

The LA liked the v9 film and asked for a coding-abilities cut at 21:45 — with the M2 battery due to take the GPU at 23:00. That constraint shaped every choice: nothing could be generated by BlarAI itself in the window (no 14B, no image model, no app relaunch — loopback 5001 belongs to the battery's preflight), so the cut had to be assembled entirely from what already existed. Three finds made a one-hour film possible. The prior session's complete pipeline — portable ffmpeg, the assemble/score/narration scripts — was recovered intact from its scratchpad, exactly where the portfolio README said it would be. The score generator turned out to anchor its build/gap/drop geometry on segment *names*, so a new cut that reuses `s01/s02/s08/s09/s10/s99` as its act names inherits the entire composition — the EDM drop retimed itself onto the new website reveal without touching a note. And the day's own `fleet-runs` state supplied the trailer's best material verbatim, including the line the whole middle act hangs on: *"Candidate 1 did not pass the gate; trying a FRESH independent candidate (2/2)…"*.

The trade-off worth recording: the film shows a **failing** gate in a promotional cut. The alternative — an all-green highlight reel — was rejected because the acceptance-gate posture (tests the coder cannot edit, best-of-N retries, honest parked verdicts) *is* the coding capability's differentiator; sanitizing it out of the marketing would contradict the very journal this project keeps. A second exclusion went the other way: the dispatch-run desktop captures were left out because they frame the operator's personal files, and were replaced with terminal-replay cards rendered from the same real logs — authentic content, controlled frame.

The LA's verdict came back within the hour, and it was the right one: not impressed — the cut showed the *surface* (describe, approve, merge) and skipped the machinery that makes the coder trustworthy. He freed the GPU until 23:00 and said: use BlarAI. So v2 (114s, `BlarAI_coder_demo_v2.mp4`) added three acts on the deep systems, and the writing turned out to already exist — the modules' own docstrings are better marketing copy than anything I would have invented, so the narration quotes them nearly verbatim: the architect act is `decompose.py` ("the 14B's one intelligent job… the model PROPOSES; a DETERMINISTIC RULER DISPOSES — the model never self-certifies"), the graph act is `plan_graph.py` (dependency-ordered plans, interface contracts, `compile_waves` — prerequisites land before dependents), and the research-substrate act is `context_pack.py` (mine what dependencies *actually* built — file lists and AST-reconstructed signatures, never prose — into a ~1200-char interface card "that stops the 30B re-discovering or re-implementing its foundations"). The four new illustrations were generated by BlarAI's own `/illustrate` pathway on the Arc 140V inside the freed window (signed-manifest verify ON, ~45s per image, the process exiting cleanly so the GPU was released), which closes a nice loop: the film about the machine is now partly *made by* the machine. GPU work ended 22:06; the field was re-verified clean (battery Ready, loopback 5001 free, no resident model) 54 minutes before the battery.

Three more LA notes landed inside the window and each was a truthfulness fix, which is worth noticing as a pattern: the opening said "This is BlarAI" over a frame that is only a title card (rewritten "Introducing BlarAI, and its agentic coding abilities…"); the credit line implied the narration voice was *not* BlarAI's when Kokoro IS the app's own voice engine (rewritten to credit it, and "this laptop" became "one laptop" because the film travels to people who are not looking at this laptop); and "just the website" reads as theoretical, so the final cut (130s) gained a **shelf act** — the fleet-built Node utility suite executed live on camera-honest terms (slugify/convert/password run tonight, `node --test` 28 tests 0 failures, output verbatim) and the real `~/projects` listing. The candid datum from that act's prep: not everything on the shelf is green — seaquotes runs but carries 3 red tests — and the shelf card therefore names only what was verified tonight. The marketing constraint and the governance constraint turned out to be the same constraint: say only what the frame can prove.

The last note of the night was the score, and it carried the evening's best technical lesson. The LA heard "banging for soooo long" under the narrator — and he was hearing a *geometry bug, not a taste problem*: the score engine anchors its EDM snare-build on the segment named `s09`, and when the shelf act was inserted between `s09` and the drop, the build stretched across BOTH acts — ~25 seconds of escalating percussion fighting two narration lines (made worse by the build layer's gentle 0.8 duck floor). The same segment-name-anchor trick that made retiming the score free in the first place is exactly what broke: an anchor scheme pays off until an insertion changes what the name *means*. v3 re-anchors the build on the last act before the drop (~13s, v9's proportions restored), drops the build's duck floor to 0.6 so it yields to the voice, tightens three narration lines, and shortens the close — 130s → 122s. And per the LA's version-confusion note, v3 is a NEW file, not an in-place overwrite: revisions get new numbers now.

v4 swapped the cold-open tease to the architect illustration (the LA heard "it builds software" over a dependency graph and rightly called the mismatch), and then the night got its most instructive failure — in the *publishing*, not the film. Pushing the coder cut to the public showcase repo, I committed from a clone that had silently failed its checkout: this tree carries filenames near the Windows 260-character path limit, the clone sat under a deep session-scratchpad path, and git left a partial index behind a green-looking clone. My three-path `git add` then committed the REST of the tree as deletions — `1786 files changed, 16 insertions(+), 593828 deletions(-)` — and I pushed a gutted public repo because I read the push line and not the stat line. Recovery was six minutes and non-destructive (fresh short-path clone with `core.longpaths=true`, restore the full tree from the parent commit, re-apply the section, push `de61e00`; remote verified file-by-file), but the lesson is permanent and now in `FIELD_NOTES.md` §Git on Windows: a fresh clone is not trusted until `$LASTEXITCODE` AND `git status --porcelain` both come back clean, and a commit's `--stat` line gets READ before any push — "1786 files changed" on a docs commit is an alarm, not a footnote. The publication itself landed: the coder cut is live on the profile README and the blarai-public README (poster → in-repo player, per the LA's chosen pattern), with the 1080p master on release `demo-film-coder-v1`.

**Next:** the LA reviews v4 (`final/BlarAI_coder_demo_v4.mp4`, now also `blarai-public/media/BlarAI_coder_cut.mp4`). If tonight's battery hands B1/B2 a real GREEN, a v5 wants window-scoped moving footage of the fleet mid-run — the one visual these cuts fake with stills.

*(No repo code changed; deliverables in `C:/Users/mrbla/Videos/BlarAI_portfolio/final/` (`BlarAI_coder_demo_v1.mp4`, `BlarAI_coder_demo_preview.mp4`), pipeline scripts in the session scratchpad, portfolio README updated in place; commit `<this>` carries this entry only.)*


### 2026-07-07 — The recovery that killed the patient

*Plain summary: #758 found and fixed same-day — running the standing pytest gate
during a live battery dispatch made the AO entrypoint's boot swap-recovery
reconcile "recover" the healthy swap: it stopped the real OVMS mid-request and
stamped RECOVERED over the live run. Fixes: a root-conftest reconcile guard
(tests can never touch the real fleet root) + a driver-alive gate in
`reconcile_swap_state` (`SwapState.driver_pid`, stamped by the driver; a live
driver means hands-off). Subsystem: fleet swap state / test isolation.*

The #757 fix wanted a live proof before the daytime pass, so I re-ran B4 on the
GPU. Thirteen minutes in, while the coder was mid-candidate on task two, the
battery monitor declared the job complete, the scorecard came back STALLED with
"no driver scorecard," and OVMS was simply gone — killed between two log lines
while it was actively serving a request. The swap state said RECOVERED. The
driver, very much alive, kept dispatching tasks into a world with no model
behind the socket.

The diagnosis went through three wrong suspects — a double-spawned driver that
turned out to be the Windows venv shim hosting its base interpreter (two PIDs,
one logical process; a field note worth keeping), a phantom AO reboot, the
re-ensurer — before the file mtimes settled it. The RECOVERED stamp landed at
11:09:17. My own standing-gate run for the #693 change ran from 11:07 to 11:12.
The killer was me: `service.start()` tests in the AO suite execute the
entrypoint's boot swap-recovery reconcile, the minimal test config leaves the
`[fleet_dispatch]` roots empty, and the empty-roots fallback resolves to this
box's *real* fleet root. The LOCALAPPDATA redirect that protects the session
database — the control built after Sprint 14's test-corruption incident — never
covered the fleet's state directory. The gate had been silently capable of this
since the reconcile shipped; it needed a live dispatch under it to fire, and
night-2 never had one because nobody runs pytest at 3 a.m.

Two defects, two fixes, both shipped today. The test-isolation half follows the
lesson-209 shape exactly: an autouse fixture in the root conftest stubs the
reconcile seam for every collected test (with a `real_reconcile` opt-out for
the three tests that exercise the seam over fakes), a scoped-run belt in the AO
package conftest covers `pytest services/assistant_orchestrator/...`
invocations that never load the root conftest, and an identity-lock test fails
loudly if either guard is removed — deliberately without calling the seam,
because a broken guard plus a probing call would BE the hazard.

The deeper half is the production assumption. `reconcile_swap_state` presumed
that an AO booting while a swap is in flight means the swap crashed. That
assumption is false whenever an AO boots *beside* a healthy detached driver —
and the operator opening his app at 23:30 while the nightly battery runs would
have killed the battery job exactly the way my pytest run did. The fix makes
recovery verify the death certificate first: the driver stamps its own pid and
process-create-time into the swap state at takeover, and the reconciler probes
liveness (create-time matched to guard pid reuse, fail-closed to recovery so a
genuinely crashed swap is never stranded). A live driver now gets hands-off —
nothing disarmed, nothing stopped, nothing stamped — with an honest "still
running" report instead of a kill. I considered gating only the test path and
leaving production reconcile alone, and rejected it: the operator-boots-mid-
battery case is real, imminent (the campaign runs nightly), and the fix is the
same thirty lines either way.

The B4 proof itself was collateral — cancelled cleanly (the driver honored the
sentinel: PARKED-HONEST, OVMS stopped, 14B restored and verified-ready). The
#757 fix remains proven only by its regression locks and the timeline math; the
daytime pass is now its live proof, as the fallback plan always allowed. The
gate re-ran green after the fixes with the AO live on :5001 — the exact
scenario that fired the defect this morning.

**Next:** the daytime battery pass (13:50, scheduled task) proves #757 live;
tonight's 23:00 run attempts pass 2. The reconcile hands-off path's live proof
is implicit in any future AO boot beside a running dispatch — no supervised
slot needed.

*(commits `72de8d4` (guards + driver-alive gate + 8 locks); standing gate
5589/0 failed/7 env-skips (port 5001 legitimately held by the live AO)/122
deselected; #758 filed + fixed same-day.)*



### 2026-07-07 — Two protocols share an acronym; one of them points at a graveyard

*Plain summary: authored and LA-approved the agent-protocol evaluation (`docs/research/agent-protocol-evaluation-2026-07.md`): Zed's Agent Client Protocol approved for a bounded driver-seam spike (Vikunja #759, builder brief merged to agentic-setup main `7f16cc3`); A2A watchlisted with two named revisit triggers; IBM's Agent Communication Protocol found defunct and categorically rejected; every runtime seam deliberately kept bespoke. No code or posture changed.*

The Lead Architect asked a question that sounds simple and is a trap: two protocols both go by "ACP" — the Agent Client Protocol and the Agent Communication Protocol — would either mature this system? The trap is the acronym. Four parallel research agents later (two on the open web against primary sources, two grounding every communication seam in this repo and agentic-setup with file:line evidence), the answer split cleanly — and the most important finding was about the protocol we will *not* use. IBM's Agent Communication Protocol, the agent-to-agent one, stopped existing as an independent standard on 2025-08-29: merged into Google-origin A2A under the Linux Foundation, repos archived two days earlier, SDK deprecated, five months old at death. Had we adopted by acronym recognition rather than checked liveness first, we would have built on an archived spec. That is the lesson-shaped part of this entry.

The rest was fit analysis, and the architecture answered most of it before taste could. A2A — the surviving successor, now at v1.0 with real cloud-vendor adoption — is federation machinery: discovery cards at well-known URIs, OAuth, webhooks, opaque peers across organizations. We have exactly one trust domain, and our one genuinely agent-shaped hand-off (the assistant dispatching a coding job to the fleet) is file-mediated *because the client process dies on purpose mid-job* — the 14B steps aside so the 30B can have the GPU. A session protocol cannot span a participant that is deliberately not running; the write-ahead swap-state file and this week's #758 driver-alive reconcile are the honest engineering answer to that constraint, and our scorecard verdicts (GREEN / PARKED-HONEST / STALLED / FALSE-DONE / RECOVERED, with attribution) already say more than A2A's eight task states can. I recommended watchlist-only with two concrete revisit triggers — the fleet ever leaving this box, or BlarAI ever consuming an external networked agent post-air-gap — and the LA endorsed it in plain terms: no real use case today. The runtime seams (named pipe, mTLS loopback, AF_HYPERV vsock) stay bespoke as security controls; each rejection is recorded with its reason in the evaluation doc §6.3, because the paths not taken are the part of a governance record that evaporates first.

The Agent Client Protocol is the opposite story, and the evidence arrived with unusual force: opencode — the exact coding agent our fleet drives headless — already ships a native `opencode acp` server mode, and our installed 1.17.8 has it. Today we drive opencode by spawning it once per turn and inferring its progress by regexing a transcript logfile and polling file mtimes plus CPU deltas — machinery that exists only because there is no structured event channel, and that the stall-detection lessons ("dev-cycle speed is THE constraint") were paid for in wall-clock. ACP replaces exactly that layer with typed protocol primitives: per-tool-call events with status transitions, plan updates, honest StopReasons of the kind #757 just hand-built, cooperative cancel before tree-kill. The LA approved a bounded, side-by-side spike (#759) — one real candidate build through an ACP session, A/B'd against the regex path on event fidelity, stall latency, Windows stdio robustness, and overhead — with integration, if the spike goes green, escalating back as a separate decision. I went with a spike rather than direct adoption because the load-bearing unknown is parity: whether `opencode acp` on headless Windows loads the same config and plugins (including the F1 path-normalize fix) as the `run` path — accepting a slower arrival at the benefit in exchange for not betting the fleet's one working driver on an unverified mode.

One more thing changed between proposal and approval, and it is worth keeping: the proposal sequenced the spike "after the F1/F3 coder-reliability fixes," inherited from the 2026-06-30 bottleneck brief. A post-approval check of the actual tree found both already shipped — F1's `path-normalize.js` landed on agentic-setup main the same day the brief naming it was written, F3's `Add-WebHint` likewise — so the sequencing condition was met before the ink dried. The prudent-later became actionable-now only because the tree was checked instead of the narrative trusted; a week-old brief is already a historical document in this project.

**Next:** run #759 in a free machine window (recon first — config/plugin parity needs no GPU; then one live candidate build with the 30B). If GO, scope the driver integration as a follow-up LA decision; if NO-GO, the finding goes upstream to opencode and the regex path keeps its job with a clear conscience.

*(commits: agentic-setup `7f16cc3` (builder brief, merged `327dcfa`); blarai `88e8d2f` (evaluation doc APPROVED + this fragment); Vikunja #759 carries the full decision record including the A2A watchlist.)*



### 2026-07-07 — The verification line nobody ever read

*Plain summary: the #759 ACP recon handshake caught both coder-fleet opencode plugins silently dead in production — `"Plugin export is not a function"` — since 2026-06-30: F1 (`path-normalize.js`) never loaded once; `command-timeout.js` died when the #687/#688 wave added a regex named export. Fix proven (functions-only exports, 18/18 reworked tests, side-by-side loader validation on opencode 1.17.8) and committed UNMERGED to agentic-setup `fix/opencode-plugin-loader-exports` (`2bba9f8`) respecting the live battery campaign's config freeze; deploy + campaign-timing decision tracked at #764. Live plugin dir and production fleet untouched by the recon session.*

The Agent Client Protocol recon was supposed to answer a modest question — does `opencode acp` load the same config and plugins as the production `run` path? — and it answered a much bigger one. The very first handshake, run with `--print-logs` because parity was the point, printed two ERROR lines the production path never shows: both fleet plugins failing to load, `"Plugin export is not a function."` The production invocation doesn't pass `--print-logs`, so in every real run since the end of June this failure has printed exactly nothing.

The verification against production logs is the part worth keeping. Both plugins ship a stderr load-line, and `command-timeout.js` even documents why: *"Load-log (stderr) so the fleet can VERIFY the plugin actually wired in."* The `.err` files the fleet already captures made the bracket exact — command-timeout's load-line appears through 2026-06-30 14:09 in its old, pre-server-probe format and never again; the new format appears in no production log ever; and `[path-normalize] loaded` appears nowhere in `state/` at all. F1 — the fix the bottleneck brief sequenced everything behind, the fix I verified as "shipped on main" hours earlier when upgrading the ACP spike to actionable — shipped, synced, and never executed once. The control that would have caught it existed from birth; nothing ever grepped for it. A verification line nobody reads is a verification line that does not exist.

The mechanism was provable without touching anything shared: opencode's plugin loader treats every named export as a plugin factory and rejects the whole file when one is not a function. Both files' first named export was a regex, exported for the test files. The pre-#688 backup in `state/backups/` exports only functions — the exact breaking delta, preserved by the harness's own backup discipline. The fix is correspondingly small: regexes and helpers become module-private, each plugin exports only its factory, and the tests — rather than losing coverage — now drive the real `tool.execute.before` hook through the factory, which tests the seam that actually failed. Validation was the satisfying kind: with the fixed files as project-level plugins in a scratch project, one boot of opencode 1.17.8 shows the unfixed global copies erroring and the fixed copies printing both load-lines — the failure and the fix side by side in a single stderr.

Two judgment calls shaped the night. First, the fix went to an unmerged branch instead of production: the battery campaign owns the machine, its session set an explicit freeze on the shared opencode config until the GPU-free window, and — less obviously — deploying mid-campaign changes coder behavior between passes, which is the campaign owner's trade-off to take, not mine. I went with fix-proven-and-parked over fix-landed, accepting that the next pass would run uncapped like every pass before it, because a baseline campaign's internal consistency is a measurement-design decision that belongs to its owner (#764 frames both options with the discontinuity named). Second, the recon itself produced a teardown lesson for the future ACP driver: my own hard tree-kill of the first handshake corrupted that scratch project's opencode state — the next boot exited 1 silently — which is precisely why the driver should prefer `session/cancel` and treat tree-kill as the last resort, not the routine.

**Next:** #764 deploy in the coordinated window (two-file explicit copy — never the installer's `*.js` glob, which would activate the staged-unverified `qwen-sampling.js`; that trap is flagged on the ticket) with the load-line grep as the verify step; the campaign owner decides deploy-now-vs-after-campaign; the #759 live A/B runs only after the fix is live so both legs measure a plugin-active fleet.

*(commits: agentic-setup `2bba9f8` on `fix/opencode-plugin-loader-exports` — deployed 18:30 + merged `929e5fa` the same evening under the campaign owner's c.1417/c.1419 era decision, so the plugin-ACTIVE era began with the 23:00 run; blarai `4d9e2cd` (the fragment). Tickets: #764 (defect + deploy), #759 c. recon-complete (full evidence), #762 c. (canary scope addition). Evidence: `state/reports/*.err` load-line bracket; recon stderr transcripts. Lesson 46's THIRD instance — its structural control, the #762 load-line canary, shipped with this fold: agentic-setup `b5a89e6`.)*


### 2026-07-08 — The estimate the kernels cut in half

*Plain summary: first measured Qwen3.6-27B run on the Arc 140V (Stage-1 successor smoke, #768) —
coherent (openvino.genai #3870 does not reproduce), fits the ceiling, but decodes at 3.6 tok/s
sustained vs the 5.5–7 bandwidth estimate; new VLMPipeline benchmark harness
`scripts/benchmark_vlm_text_inference.py`; results in PERFORMANCE_LOG.md +
docs/MODEL_EVALUATION_QWEN36_27B.md. Recurrence of lesson 151.*

The successor question came back today wearing a new coat — the Lead Architect kept seeing
Qwen3.6-27B and its ThinkingCap fine-tune in the wild and kept forgetting why we couldn't use
them. The research sweep found the answer had genuinely moved: the model now runs on our exact
substrate, it is natively multimodal (one model would absorb both the 14B brain and the separate
vision model), and the blockers had narrowed to a missing speculative-decoding path, an open
coherence bug, and speed. I estimated speed from first principles — the repo's own 14B and 8B
measurements both back out the same ~90 GB/s effective bandwidth, and 14 GB of dense INT4 weights
divided into that gives ~6.4 tok/s, with a physics ceiling near 9.7. The LA weighed the
capability against the number and accepted ~6.5. That acceptance converted an estimate into an
obligation: measure it.

The measurement disagreed with me, and the disagreement is the lesson. Median sustained decode
came in at 3.59 tok/s — barely half the bandwidth math. The tell was not in the decode column but
in prefill: 219 tokens/sec where the dense 14B does ~1960 on identical silicon. Weight streaming
cannot produce a 9x prefill gap; unoptimized kernels can. Qwen3.6's Gated-DeltaNet hybrid (48 of
64 blocks are linear-attention) is new to the GPU plugin, and the plugin plainly runs it
compute-bound. My bandwidth model wasn't wrong — it was an upper bound dressed as a central
estimate. The trade-off ledger for a bandwidth-bound assumption should have carried the named
alternative: *or the kernels aren't there yet, in which case all bets are below the line.* I had
even written the pass criterion for this ("a wildly lower number means something is misconfigured,
not that the estimate was wrong") and the truth split the difference: nothing was misconfigured,
and the estimate was still not the number.

The run also delivered the finding that keeps the door open: openvino.genai #3870 — Qwen3.6-27B
producing incoherent output on GenAI, reported on our exact runtime — does not reproduce here.
All twenty captured generations are clean: correct facts, orderly thinking traces, no
degeneration. The disqualifier was the bug; the bug is absent on 2026.2.1 + the 8826 driver + the
official INT4 build. What remains is purely a software-maturity clock: the physics allows ~9.7,
the kernels currently deliver 3.6, and both the harness and the 14.6 GB of weights now sit
resident so re-measuring at each OpenVINO version bump costs one command. Verdict recorded:
below the accepted floor, Stage 2 (ThinkingCap conversion) not triggered, and kernel-maturity
joins the revisit triggers alongside the spec-decode path and the (now-moot-here) bug closure.

Operationally, this was also the first GPU run scheduled through the battery campaign's manager
rather than around it — a coordination message, an affirmative window grant with terms (exclusive
GPU, 22:30 hard-stop, AO left down for the 22:45 preflight), and a clean handback with memory
fully recovered. The overnight window is no longer mine to assume; asking first cost twenty
minutes and bought zero contention.

*Same-evening addendum — the thread-read that rewrote the findings, and the switch the model
reads and refuses.* Before drafting the upstream report the LA asked for, I read the actual
#3870 thread instead of trusting the research sweep's summary — and it rewrote two of my own
records: the bug was CLOSED a month ago (conversion-side, self-converted models only, official
weights never affected), and its failure mode was long-prompt-dependent while my coherence
evidence was short-prompt. Both records corrected same-day; the lesson is the cheap one that
keeps recurring in this repo's history: read the primary source before citing it externally —
the sweep's "open bug on our exact runtime" survived three documents before one thread-read
killed it. The same read surfaced what the sweep had missed entirely: DFlash-on-OpenVINO is an
open, Intel-authored enablement effort (genai #3938) — the spec-decode blocker got a tracking
number. Two upstream comments posted with LA approval (openvino #36270, genai #3938). Then the
LA asked the right question — does the thinking toggle actually break the Policy Agent? — and a
three-condition probe on the still-warm 27B answered it in ten minutes: `/no_think` is not just
ignored, the model *quotes the constraint inside its own thinking trace* and reasons on;
`enable_thinking=False` is accepted by the API and ignored by the model; and the emitted
chain-of-thought is untagged, so even the AO's strip logic would be blind to it. The hardest
swap blocker turned out not to be the speed I measured all afternoon but a chat-template defect
found in the last hour — genai #3937, now reproduced on the 27B on release wheels, probe and
evidence preserved (`scripts/probe_qwen36_thinking_toggle.py`).

**Next:** re-run the harness + the thinking-toggle probe at the next OpenVINO version bump
(single commands, weights resident); watch the four triggers in
`docs/MODEL_EVALUATION_QWEN36_27B.md` (#3938 DFlash, kernel maturity, long-prompt coherence,
#3937); Draft 3 (the #3937 upstream confirmation) was approved and posted the same evening
(#768 c.1469) — all three upstream comments are live.

*(commits `416e5a31` (Stage-1 smoke: harness + eval doc + PERFORMANCE_LOG entry + fragment),
`f5632168` (#3870 scope correction + upstream watches), `6291c9ba` (#3937 probe, REPRODUCED),
`44c2da53` (addendum); benchmark JSON
`docs/performance/benchmark_vlm_text_qwen3.6-27b-int4-ov_2026-07-08_16-21-18.json`;
Vikunja #768 carries the verdict; Stage 2 not triggered. Lesson 151 tallied at fold —
a first-principles estimate is itself a measurement of the WRONG scenario (mature kernels)
until the immature-kernel alternative is named.)*


### 2026-07-08 — The clean room takes its first exam

*Plain summary: the #744 guest-certified oracle went LIVE in an LA-supervised ceremony — the `blarai-oracle` service built and provisioned into the NIC-less Alpine guest (vsock 50002, pytest 9.1.1 offline from the CD ISO), the corridor proven in both directions BEFORE the production wiring was written, the transport registered + knob flipped with all four dormancy locks consciously amended, first light honest, and the consumption half (scorecard agreement vocabulary + morning-report divergence banner) built the same afternoon. Merges `097605d`, `7356d11e`, agentic-setup `ca0a8dd`; record `docs/security/guest_oracle_provisioning_record.md`. Subsystem: fleet swap / guest isolation.*

The ceremony's ordering rule was the day's earlier lesson applied in advance: prove the observable end property before trusting any wiring. So before a single production line was registered, the corridor ran live — the reachability probe through the 3.14 bridge, then a real snapshot through the real channel into the real guest, where a real pytest returned *passed* in 0.40 seconds; then the same oracle over deliberately broken code returning *failed* with the genuine assertion text. A guest that cannot say no proves nothing, and this one said no before it was asked to say yes. Only then did the one-line registration land, and the four locks built to forbid it were amended in the same commit to pin the live posture as firmly as they had pinned dormancy — the registration-containment scan now names `swap_ops` as the single sanctioned wiring site, the same way the old scan named zero.

Two judgment calls shaped the build. The oracle got its own guest service on its own port rather than a second op on the proven parser listener — coupling two capabilities whose ceremonies were separate LA decisions was rejected at the transport build, and the same reasoning held at the guest: `provision_oracle.sh` cannot touch the parser install even by accident, because it never opens the parser's directories. And the guest bundle forced a small honesty fix in the executor module itself: its import of the acceptance module would have dragged the whole decompose machinery into a VM that must carry stdlib and pytest only, so the pinned oracle paths are redeclared locally with a host-side lock holding the copies equal — the parser service's own redeclaration precedent, reused rather than reinvented.

The amendment pass also caught the week's recurring class one more time: the first post-flip gate run *reached the real guest from inside pytest* — the old dormancy test called the now-live call site, which now builds a real transport, which found a real listener. Nothing was harmed, but a test suite that opens a production corridor is the same species as the gate that killed OVMS on Monday and the detector that aimed at the AO last night. The lock now injects a factory seam, and its docstring names the incident so the next author knows why.

First light was honest rather than triumphant, which is better. The driver fired the phase in the RAM-free window — the one moment neither model holds the box — and wrote a certificate reading `not-run, flat-queue-mode`: the tiny ceremony goal had collapsed to a single task, the plan degraded to flat-queue, and there was no job oracle to certify. The machinery told the truth about having nothing to grade, which is precisely the property the whole corridor exists to protect. The graded certificate self-proves tonight, four times over, because the last piece built this afternoon was the half that lesson 46 demands: a reader. Scorecards now fold the certificate into evidence under a closed agreement vocabulary, the battery summary accumulates the host-vs-guest matrix, and the morning report prints per-job agreement with a banner that cannot be missed on any DIVERGENCE — because an isolation certificate nobody reads is a verification line nobody reads, and this project has already paid for that lesson once this week.

**Next:** tonight's battery is measurement pass 1 of the agreement matrix (four Python plan-mode jobs per pass); at ~20 certificates the LA decides whether divergence gates; node-in-the-guest and mTLS activation are the tracked future scope on #744.

*(commits: build `f701deb`, go-live `70fb195`/merge `097605d`, consumption `3e4cbc2`/merge `7356d11e`, agentic-setup morning-report `ca0a8dd`, record `ffa48821`; gate 5843/0 exit 0 post-wiring; ceremony evidence in the provisioning record §3/§5. Tickets: #744 c.1462.)*


### 2026-07-09 — The screenshot that convicted an innocent app

*Plain summary: B5's attempt-4 STALLED [VERIFY] was a harness false-red — the
web design-verify screenshots apps over `file://`, and browsers block module
JavaScript there entirely, so every app built on the fleet's own
`"type":"module"` scaffold renders as a dead shell no design-fix can ever cure.
Proven by A/B (same merged code: dead over file://, fully rendered over its own
server), fixed in `capture-app.ps1` (serve-then-capture, verified-free
ephemeral port, server tree reaped), live-verified watched, merged agentic-setup
`8476b7d`; evidence blarai `e194c438`; tickets #772 (fixed) + #773 (orphan
servers, open). Dispatch harness / web verify tier. Lesson 47 recurrence; new
lesson (222).*

The morning's battery close ended on a verdict I nearly recorded as capability
data: B5 STALLED [VERIFY] after the vision design reviewer spent two fix
iterations insisting the habit-tracker's chart never rendered — a white
rectangle and an eternal "Loading…", ninety-nine percent of the screenshot one
flat colour. The coder's unit tests were green and both tasks had merged, which
is exactly the shape an honest capability failure takes: the code compiles, the
tests pass, and the thing still doesn't work on screen. The campaign exists to
measure that. I went to record it and stopped on one question: what,
precisely, was the screenshot *of*?

It was of a corpse. `capture-app.ps1`'s web tier opens the app's `index.html`
via `file:///`, and a comment there promises that file:// "renders the static
layout/theme/colours the critique cares about (server-fetched data does not
run, but the look does)." That claim was true the day it was written and is
false for every app the fleet actually builds: browsers block
`<script type="module">` over file:// outright — not the data fetches, the
entire client program — and the fleet's own web seed ships `"type":"module"`.
Under the capture, B5's `init()` never registered, the status never left
"Loading…", and the canvas never got a single stroke. The design reviewer
described what it saw with perfect accuracy. The coder's fixes were invisible
to it by construction. The iteration cap did the only thing it could. Every
component honest; the composition a conviction machine.

The A/B proof took twenty minutes and one detour. Same merged code, same
pinned headless-Edge invocation: over file://, the exact doomed screenshot;
over its own `node src/server.js`, a complete chart — axes, gridlines, day
labels — and the status reading "Ready". The detour is its own small entry in
the ledger: my first server-side capture photographed a *different* corpse,
because an orphaned app server from B5's own dispatch was still squatting port
3000, serving 404s out of a worktree the teardown had already deleted (#773).
And hardening the fix produced a third find: my ephemeral-port range contained
3456 — Vikunja — and an unlucky draw would have bind-killed the app server
while the TCP probe cheerfully connected to the squatter and photographed a
task tracker as the app under review. The port is now verified free before the
spawn, the answering socket only counts if our own process is still alive
behind it, and the capture's server dies in a `finally` whatever happens.

The fix keeps file:// as the fallback for genuinely static pages and otherwise
starts the app's real server on the verified port, captures
`http://127.0.0.1:<port>/`, and reaps the tree. Watched live-verify, all three
legs: the real B5 app through the real script produced the honest render; the
static fallback still captures; nothing survives the shot. The B5 scorecard
itself stays as-written — the runner owns its files — with the acquittal
recorded beside it in the campaign record and the three screenshots committed
as evidence.

What stays with me is how close "the coder can't build charts" came to
entering the capability ledger as a measured fact. The instrument had no
positive control: nothing had ever demonstrated that the web verify tier
*could* pass a known-good app, so its failures carried an authority they had
not earned. B8 exists because we learned to distrust green without rigged reds;
this morning taught the mirror lesson about red.


load-bearing false premise; the fix rewrote the comment into the enforced
truth.


known-good subject under production conditions, or every systematic blindness
it has becomes a fleet of plausible failures wearing measurement's authority;
negative controls (B8's rigs) catch false green, and only a positive control
catches false red.

**Next:** #773 (orphan job servers) in the hygiene queue; tonight's pass runs
B5 on the fixed capture — its verdict is the systemic confirmation; the
positive-control idea generalizes to the other verify tiers (does each have a
known-good subject it provably passes?).

*(fix agentic-setup `bc50851` → merge `8476b7d`; evidence blarai
`phase2_gates/evidence/772_file_vs_http_20260709/` at `e194c438`; incident
#740 c.1527; tickets #772 closed, #773 open; the acquitted run =
night-20260709-055439 B5, wall 8447s, interventions 0.)*


### 2026-07-09 — The novice question that found the untested half

*Plain summary: disaster-recovery restore path audited, drilled, and made self-maintaining — four
restore legs rehearsed PASS, a stale-lockfile restore defect fixed (`requirements.2026.2.1.lock.txt`
frozen), the runbook promoted to a tracked master synced nightly to the backup root; Vikunja #782. Lesson 226 tally.*

The Lead Architect asked, an hour before handing me the night: *"I feel like the project is
missing a key piece that I am just unaware of because I am a novice."* The honest answer took an
audit, and the audit proved his instinct sound. The backup arc from 2026-07-01 (lesson 226) had
built a genuinely good CAPTURE side — nightly, all legs green, a thoughtful runbook already
sitting in the OneDrive root where a dead laptop can't take it. What eight days of heavy building
had never produced was a single proof that any of it could come BACK: no restore leg had ever been
rehearsed, and the runbook was a point-in-time document already wrong in ways that would hurt at
exactly the moment it was needed.

The drill made the gap concrete. Four legs rehearsed tonight, all PASS: a shallow clone from the
private remote (the remote is real and current), `git bundle verify` on the 7/1 bundle (complete
history), all three encrypted databases restored from OneDrive to scratch with `PRAGMA
integrity_check` ok, and a weights sha256 identical across local and mirror. But the runbook the
restore would follow said `py -3.12` where the validated runtime is pinned 3.11.9, counted 398
branches where 555 push nightly, and — the find that justified the whole evening — pointed the
venv rebuild at `requirements.2026.1.0.lock.txt`, a lockfile frozen one OpenVINO substrate ago. A
faithful restore would have silently rebuilt the inference stack on 2026.1.0 while every
measurement, the prefix-caching KEEP-ON, the swap-gate 20.0, and the spec-decode findings all rest
on 2026.2.1. The backup was fine; the *instructions* for using it would have quietly rebuilt a
different machine. I froze the current environment as `requirements.2026.2.1.lock.txt` and
repointed the runbook.

The trade-off worth recording is where the master now lives. A restore runbook's first duty is to
be readable when the machine is gone, which argues for OneDrive; its second duty is to stay
correct as the system drifts, which argues for the repo where review and diffs live. I took both:
the tracked master in `docs/runbooks/DISASTER_RECOVERY_RESTORE.md`, and one fail-loud line in
`backup-system.ps1` that copies it to the backup root every night — proven live tonight (the leg
logged `restore runbook synced from tracked master` on a manual run before the change merged). The
rejected alternative — keeping the OneDrive copy authoritative and hand-editing it — is exactly
how the 7/1 version rotted: an untracked document nobody diffs, drifting one fact per merge day.
Small honest finding on the way: the backup script's push-exclusion list names a branch
(`feat/719-golive-ceremony`) that no longer exists anywhere — stale entry, harmless, noted rather
than chased.

What tonight did NOT prove stays named: the TPM recovery-unwrap with the physical printed key
(the code path is gate-tested in `test_field_cipher_and_dek_envelope.py`; the *paper* is not), and
a restore onto different hardware. Both are LA-present steps — the printed-key check is two
minutes and is now the single most valuable unverified control in the project, tracked on #782.


**Next:** the LA's two-minute physical check of the printed recovery key (record on #782); a
full restore-onto-different-hardware ceremony when a second machine exists; bundle refresh at the
next quarterly pass.

*(commits: blarai `<this>` (runbook master + lockfile + index + this fragment); agentic-setup
`feat/782-runbook-nightly-sync` (the nightly sync leg, live-proven pre-merge); drill evidence in
#782 comments.)*


### 2026-07-04 — The film that had to earn every second

*Plain summary: the BlarAI portfolio demo film went v1→v9 across two nights —
re-recorded segments, a real dispatch-built website as the payoff, an
illustrated fingerprint-gate sequence generated by BlarAI itself, and an
original score composed and synthesized entirely on the laptop. Along the way
the dispatch idle-breaker's blind spot for slow single-file writes was found,
worked around, and filed (#779; the filing was deferred by a Vikunja outage and landed at the 2026-07-09 fold). New lesson (227). Portfolio media lives outside the repo at
`C:/Users/mrbla/Videos/BlarAI_portfolio/` (v9 is the finished film).*

The demo film was supposed to be a wrap-up task: record the features, cut
them together, ship. It became a nine-version essay in what "professional
grade" actually costs. The Lead Architect reviewed every cut and his notes
were consistently right: a seven-second hold on a blank chat window is not
patience, it is dead air; a lower-third that covers the input box hides the
one thing the shot exists to show; two narrators talking over each other is
not atmosphere. The fixes were not editing tricks — they were the discipline
of looking at each shot and asking what it proves.

Two failures are worth keeping. First: the Meridian website — the film's
climax, a real site built by BlarAI's coder fleet — refused to exist twice.
The fleet's idle circuit-breaker killed the 30B coder mid-write both times,
reading "no new step/edit for 240s" as *stuck* when the truth was *slow*: a
single large HTML write emits no intermediate progress signal the detector
can see. The seaquotes CLI had succeeded hours earlier only because its tasks
decomposed into small fast writes. I raised the timeout to 600s for one run
(the build then completed and merged cleanly — gates green, site live in a
browser), and reverted to 240s immediately: the fast-kill default is the
operator's explicit dev-cycle preference, and a demo is not a mandate to
re-tune the fleet. The durable fix — a progress signal the detector can
actually see during long generations — is filed for the #670 dispatch epic
(see `_PENDING_vikunja_updates.md` in the portfolio folder; Vikunja MCP was
down for rotation this session).

Second: music synthesized from raw code failed twice before it worked. The
first bed was sustained sine stacks — the LA called them "annoying piercing
tones," and he was right; naked sines are test equipment, not music. The
second was felt-not-heard atmosphere — mixed so politely it vanished. The
third attempt worked because the *what* changed, not the *how much*:
percussion and staccato ostinato (things synthesis renders convincingly)
instead of sustained tones (things it cannot hide). From there the LA drove
it like a producer: an EDM-anatomy drop on the website reveal (build,
bass-thinning, snare-roll doubling, a near-silence gap, then the slam —
measured 60 dB of instantaneous release), a riser de-whistled from clown to
dread, and a final stereo mix pass — mono bass, panned stabs, synthesized
reverb whose tail rings into the gap, sidechain pump. The trade-off named:
a licensed royalty-free track was the lower-risk path to "good," and was
offered twice; the LA chose synthesis, which kept the film's on-screen claim
— *"All images and voices in this film were generated by BlarAI — every
sound was synthesized on this laptop"* — literally true. That sentence is
now the title card's closing beat, surviving the fade half a second longer
than everything else, which was the LA's own directorial call and the best
shot in the open.

The meta-lesson sits above the film: the operator — a self-described
non-technical novice — reviewed like a director, caught real defects a
frame-by-frame QC had missed, and made the two calls (synthesis over
licensing; emphasis-by-survival) that gave the piece its identity. The
expertise split worked exactly as designed: he owned *what it should feel
like*; the agent owned *how*.

**Next:** LA watches v9 for final sign-off; file the #670 idle-breaker
finding as a ticket when Vikunja MCP returns; reopen BlarAI from the
launcher (still closed from the last dispatch swap-back); fold this fragment
at the next quiet tree.

*(No product-code commits this arc; the repo artifact is this fragment. The
film + pipeline scripts live in `Videos/BlarAI_portfolio/` and the session
scratchpad; dispatch runs `20260703-211337-bd`/`-213231-bd` (breaker kills)
and `-214951-bd` (merged, `f767e58` in `projects/meridian-cafe`).)*


### 2026-07-10 — The grader kept its answer key in its pocket, and the odometer counted the parked laps

*Plain summary: two dispatch-fleet measurement-instrument defect fixes derived from the night-20260709-230001 battery — #790 rec-1 surfaces the job-acceptance oracle's import contract into the coder's context packs (`shared/fleet/context_pack.py` + the `SwapOps.job_oracle_contract` seam), and #789 segments the battery GREEN-rate over plan-graph-eligible jobs only (`evidence.mode` stamp + `BatterySummary.reliability` + the morning report). Verdict logic untouched; flat mode still never GREEN. New lesson (241 — surface the grader's contract to the builder; measure over the eligible denominator).*

The battery ran six cards overnight and banked one GREEN. Read naively that is a coder that fails five times in six. The daytime investigation on #790/#789 said something sharper, and re-verifying it on disk changed what "fix the coder" even means: in every plan-graph job the 30B coder *built and merged the features*. The jobs died downstream of code generation, at the measurement seam. That reframe is the whole entry — we were about to tune an engine that was running fine and lying to its own dashboard.

**#790 rec-1 — the hidden answer key.** B4, B6, and B7 each merged a working app and then failed the wave-final job oracle at *import time*: `from cli import main` → `No module named 'cli'`; `from inventory_manager import InventoryManager` → not found; `import … from '../src/slugify-phrase.js'` → the coder put the file somewhere other than `src/`. The oracle is seeded into the repo before wave 1 (#748) but guard-wrapped so it *skips during node gates* — which means the coder never has to satisfy the import contract until the very end, by which point the layouts had diverged. "Unit-green ≠ job-green," and the gap was a layout nobody showed the builder. The fix extracts the oracle's first-party import *statements* — the exact module paths and public names it will import against — and appends them to every plan-graph task's prompt. I proved it against the real seeded oracles on disk: the extractor surfaces precisely `from cli import main`, `from inventory_manager import InventoryManager`, `import { slugifyPhrase } from '../src/slugify-phrase.js'` — the three imports that actually killed the jobs.

The judgment worth recording is where I put the extraction and how I bounded it. It reuses the context-pack module's existing N6 posture: import statements are reconstructed from the Python AST (identifiers only, no string/comment/default content can ride), stdlib and the test framework are dropped via `sys.stdlib_module_names` so only the coder's own surface shows, mjs specifiers are kept only when they are local paths and are re-quoted by us with the binding quote-gated — so the oracle can name modules but can never restructure the prompt. I chose a dedicated `SwapOps.job_oracle_contract` seam over riding the existing `seed_job_oracle` return, accepting one more seam on the dataclass, specifically so the contract surfaces *independent of whether seeding succeeded* — the builder benefits from the interface even on the fail-soft path where the file itself never lands. The rejected alternative (couple it to seed success) was shorter and would still have fixed B4/B6/B7, but it ties the most actionable signal to an orthogonal failure.

**#789 — the odometer counted the parked laps.** B1 and B5 ran the *flat queue*, not the plan graph: `build_job_plan` degrades to flat when decomposition yields fewer than two tasks (both under-decomposed to a single task), and `compute_flat_verdict` can never return GREEN by construction — a flat run has no job oracle to prove the integrated whole. So two of six jobs were structurally denied any path to GREEN before coder quality mattered, quietly depressing the campaign's baseline. The tempting "fix" — let a single-task flat job that passes its per-task oracle read GREEN — is exactly the FALSE-DONE class the whole scoring system exists to refuse, and it was ruled out by the hard rule: flat mode must still never be GREEN. So this is a *measurement* fix, not a verdict fix. The driver now stamps `evidence.mode` (`plan-graph`/`flat`); the battery reports GREEN over plan-graph-eligible jobs (the honest coder denominator, 1/4 for this night) *alongside* the raw rate (1/6) with the flat count shown separately, never hidden; the morning report carries the same line. The under-decomposition itself — making decomposition rob­ust enough that a six-feature card never collapses to one task — is a genuine capability decision, left on #790 rec-2/#789 for the LA, not smuggled in here.

The connective tissue between the two: both are instrument defects, and the discipline held on both — do not move a verdict to make a parked job read done, and do not let a structurally-impossible outcome sit in the denominator pretending the builder had a shot. Author≠verifier by construction: the coordinator reviews this diff before it merges.

**Next:** land after the coordinator's review (branches `fix/coder-quality-790-789` in blarai, `fix/789-plan-graph-fairness` in agentic-setup); the first live confirmation is the next battery night reading the surfaced import contract in `context-packs.log`/task prompts and the morning report printing the segmented GREEN-rate. The decomposition-robustness fix (#790 rec-2) and wiring the dormant W5 re-decompose remain LA capability decisions.


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


### 2026-07-10 — The contractor we never checked: the coding fleet's threat model

*Plain summary: authored the #787 Phase-1 dispatch-fleet threat model (docs/security/post_capstone_2026-07/PHASE1_DISPATCH_THREAT_MODEL.md), grounded on disk; the honest finding is that the coding fleet was outside BlarAI's security model by construction, and Decision 1(b) fixes it at the OS layer. New lesson (236 — containment is an OS-layer property, not a tool-surface one).*

The security campaign built a genuinely good vault around the assistant — TPM trust root,
DEK-envelope encryption at rest, a fail-closed egress guard, a Policy-Agent choke point. But
that scope froze at the #598 gate, and every capability we shipped since lives outside it. The
biggest is the coding fleet, and Phase 1 of the post-capstone re-maturation is the threat model
nobody had written for it.

The finding I most wanted to be wrong about held up under grep. opencode is spawned with
no credential switch, so the coder — and every child it spawns (`npm`/`uv`/`node`/`git`) —
runs under the operator's own token, with the operator's file ACLs and the operator's
unrestricted network. It can read the operator's sensitive files and open a socket to
anywhere. And BlarAI's egress guard does not cover it at all: a grep of the entire fleet
for the adjudicator, the guarded-fetch door, the allowlist returns zero files. The fleet is
outside the security model by construction — the swap driver outlives BlarAI itself.
Overnight it is worse: the battery self-elevates, and the whole dispatch tree inherits
admin. This is a known supply-chain compromise shape, and it needs no clever prompt
injection — a poisoned dependency install is enough.

The trade-off this documents, path-not-taken visible: every existing control (opencode's read-deny,
bash-ask, the tree-kill, the FALSE-DONE cross-check) sits at or above the layer that governs what
the *model* asks opencode to do. None of them can touch a child process that bypasses opencode's
tool surface via the OS. That is why Decision 1(b) — a distinct limited account + a per-SID
outbound firewall block — is the right floor: it acts at the OS, below the tool layer, un-bypassable
by children. The sharp design constraint the model surfaced for the ACP-01 rebuild is the
*elevation collision*: the coder leg must be de-elevated to the restricted account even on nights
the orchestrator runs elevated. And the load-bearing honesty — Windows per-account network
isolation is verify-not-assume; a prior wrongly-scoped firewall-rule incident that broke the
operator's own machine is the precedent that makes a live per-SID egress proof mandatory, not
optional, before the floor is trusted. The (c) VM fallback for cross-platform jobs is now confirmed
memory-feasible (30B + a 6 GB guest = 27.5 GB, measured same day).

**Next:** LA reviews the threat model; Phase 2 extends the capstone coverage matrix to the four
post-capstone surfaces; Phase 3 builds the first adversarial suites (the prompt-injection→dispatch
chain first); the (b) floor + its de-elevated coder leg get built into ACP-01, with the per-SID
egress proof as the gate.


### 2026-07-10 — Letting the model suggest without letting it write

*Plain summary: #770 Learning Loops M2 — the `propose_preference` GUARDED DRAFT
tool + shared confirm-card builder + ephemeral proposal staging (W1), the
one-step Jaccard-gated contradiction confirm + operator-stated expiry (W2), the
`poisoning_redteam` eval kind on the MPBench frame (W3), and ADR-036 +
DECISION_REGISTER ratifying the tier's governance (W4). Loop 1, Phase 2. Lesson 151 tally; new lessons (232 — a draft tool may name a surface it cannot write; 233 — a confirm hop carries a token, never the body).*

M1 taught BlarAI to remember what the operator told it about himself, but only
when he typed `/remember`. The whole security spine was that the write path
*does not exist* for the model — P8 as structural absence, not a flag. M2's job
was to add reach without spending that spine: let the 14B *notice* a standing
correction mid-conversation and *suggest* saving it, while keeping every actual
write on the operator's own typed command. The organizing idea, straight from
the reference study's §5.1, is source isolation between the proposal channel and
the write channel. The model may draft; it may never commit.

The shape that fell out is a `propose_preference` tool that renders a card and
has no path to the store. That sentence hides the one real design tension: the
M1 authority lock asserted that *no registered tool name even contains
"preference"*, and here I was adding a tool literally named `propose_preference`.
The honest resolution was to weaken the lock in exactly the right place and
strengthen it everywhere else — admit the one DRAFT tool by name, then add new
structural-absence locks proving the propose channel (the tool body, the shared
card builder, the staging store) never calls the write API. The write still
flows through the single AO door, now reachable by a new operator command
(`/remember-confirm <token>`) as well as `/remember`. The token is the whole
trick: the confirm frame carries a token and *no body*, so the AO commits the
store-side staged verbatim bytes and a model that restated the preference on a
later turn cannot change what lands. That is confirm-hop integrity, and it is
why the staging store exists at all — the authoritative bytes live system-side
between propose and commit, never re-supplied by the model.

Two failures worth keeping. The first was mine and embarrassing: I read and
edited `MainWindow.xaml.cs` at the *main checkout* path instead of my worktree,
adding the two new slash commands to the wrong tree. `git status` on main caught
it; I reverted the main file and applied the change in the worktree. The lesson
isn't "be careful" — it's that a worktree gives you two byte-identical copies of
every file and the tools will happily edit either, so the absolute path is the
only thing keeping them apart. The second was quieter and more interesting: my
new source-isolation lock scanned for the bare string `store_preference`, and it
failed — on the staging module's own docstring, which *names* the write API to
explain that it never calls it. The bare-name scan couldn't tell "documents the
isolation" from "violates it." I switched it to the call-form (`.store_preference(`),
which is what the M1 single-door lock already used and what actually matters.
The irony that the isolation lock tripped on the isolation's own documentation is
the kind of thing that only shows up when you write the failing test first.

W2 folded neatly into W1's corridor rather than inventing a parallel one. The
M1 contradiction stub refused a near-duplicate `/remember` and pointed the
operator at a manual `/preferences edit`; now the near-dup stages a REPLACE
proposal and hands back its token, so the operator resolves it in a single reply.
Same staging, same confirm door, one fewer hop. The expiry work was the one
place I had to touch the store schema, and the governance care there was P6:
"the system never decides to forget." An `expires` column is a decay column if
the system sets it, and an honest bound if only the operator does. So the render
drops an expired row but `/preferences` still lists it, flagged, never
auto-deleted — and I deliberately refined the M1 test that asserted "no expiry
column at all" rather than deleting it, because the P6 promise didn't change, its
precise shape did. Natural-language dates I scoped hard: ISO, "tomorrow", and
weekday-next-occurrence resolve; anything else stays in the body verbatim,
because "wait until I say so" is a preference, not an expiry, and P2 says keep
the operator's words.

W3 is the part I most wanted to exist. The study's most actionable finding is
that a commercial prompt-injection screen catches 84% of strong-signal memory
attacks but only 42.5% of weak-signal ones — a plausible "preference" a hostile
document nudges the model to propose is semantically indistinguishable from a
real one, and no classifier closes that gap; write-path structure does. So the
`poisoning_redteam` eval drives the *real* store, propose handler, and card
renderer through seven MPBench-framed classes and records ASR/RSR per case. The
weak-signal case is the one that matters: it asserts the card carries the
untrusted-context flag and the verbatim body, because a card-reading operator is
the last line, which is exactly why D-1(a) put the flag on the card instead of
refusing proposals in knowledge-heavy sessions. The C3 case is a tripwire that
passes trivially today (nothing summarizes memory) and is designed to fail loudly
the day something does — the gov-pf-007 pattern applied to consolidation. FAMA
negative-reliance is built and deliberately not run: it needs the 14B, the GPU is
reserved, and the coordinator schedules that measurement separately.

The trade-off I want on the record is D-1(a) itself, because the alternative was
tempting and wrong. Refusing proposals whenever untrusted content is in the
conversation (D-1(b)) would kill the weak-signal window outright — but it also
kills the legitimate capture in exactly the sessions where corrections happen
(the operator says "no, always metric" while a document is loaded), and it trains
him that capture is flaky. We chose propose-anywhere with a visible flag,
accepting that the operator's judgment on one plain-language card is the control,
not a lock. That is the consent-doctrine call — route danger to deterministic
controls, route judgment to the coarsest question a human can actually answer.

Verification was unusually complete for a UI-bearing feature: the Python corridor
is green (the four workstreams plus the tools/loop suite), the headless C# parser
gate passes (71 tests), and — the part I didn't expect to get here — the full
WinUI app builds clean, 0 warnings, so the Save/Dismiss card rendering and the
sender wiring actually compile. The one thing left for the operator is the
live-pixel confirm: relaunch, trigger a proposal, watch the card render, click
Save. That, and the two hardware-gated eval cases, are the on-Arc-140V steps.


**Next:** the operator's live-pixel WinUI card confirm + the two hardware eval
cases (FAMA negative-reliance + any model-mode measurement) on the Arc 140V in
the reserved GPU window — the coordinator schedules these; #796 (the meaning-based
contradiction-matcher feasibility study) is the separately-ticketed follow-on the
LA flagged as "where the value is."

*(commits `d7f5c24` (W1 propose+confirm corridor), `ab64098` (W2 contradiction
confirm + expiry), `1bfd3e8` (W3 poisoning red-team), `a0ddc68` (W4 ADR-036 +
register); +~330 preference/proposal/expiry/protocol/coordinator tests, C#
headless 71/71, WinUI app build 0 warn/0 err, eval preference_memory 29 cases
(23 offline green + 6 hardware-skipped); full standing gate **6205 passed / 0
failed / 21 skipped [worktree-environmental: gitignored bge-small ONNX + 14B
config absent] / 123 deselected**, exit 0, 2:52.)*


### 2026-07-10 — The gate was green and the real pass still 400'd — then threw away twenty-eight minutes

*Plain summary: the #793 lesson-miner's first two real 14B passes each found a limit the green offline gate structurally could not — the whole ~113-run evidence corpus (~223k tokens) went to the model in one message and overflowed context (HTTP 400), then the chunked pass died at ~28 min on a socket-read timeout with no resume; fixed with chunked mining + cross-batch candidate merge, then a generous configurable timeout + batch-level checkpoint/resume + per-batch progress. New lesson (237, the unbounded-history-consumer class). agentic-setup `feat/793-lesson-miner-chunked` `db2b017` + `feat/793-lesson-miner-timeout-resume` `22ffa87`.*

The golden gate passed 11/11. Seventeen unit tests passed. The dry pass ingested 113 real runs cleanly. And the first real pass — the coordinator pointing the miner at the live 14B — returned `HTTP Error 400: Bad Request`. This is the mock-passes-but-prod-crashes class, and it earned its entry: everything I could test offline was green, because the thing that broke was the one thing the fake model layer by definition could not exercise — the real context ceiling. My `RecordedModelClient` returns candidates for any bundle, of any size; the real OVMS server does not. The lead diagnosed it before handing it back, and the diagnosis is the failure mode of every consolidator that reads "the whole history": I had built the evidence bundle as *one user message carrying all 113 runs* — measured after the fact, ~223,000 tokens, an order of magnitude past any 14B context. The miner was architecturally a single-shot summarizer of an unbounded, growing corpus, and that shape does not survive contact with a fixed context window; it only ever ran clean in tests because the corpus was tiny there.

The fix is chunked mining, and the interesting half is not the chunking — it is what chunking does to the ruler. Split the corpus into batches that fit and call the model per batch, and a failure shape that recurs four times across the corpus is now proposed *twice in batch 1 and twice in batch 3*, each proposal citing only the two runs its batch saw. If the deterministic ruler counts recurrence per proposal, both see recurrence 2, both fall under the ≥3 gate, and a genuinely four-times-recurring lesson is **silently killed by the very act of batching** — exactly the silent-cap class this miner exists to refuse. So the correctness heart of the fix is the merge: candidates from all batches are grouped by failure shape and their evidence *unioned* before the ruler runs even once, so recurrence and diversity are computed across the whole corpus, never per batch. I unit-tested it both ways — the merged shape survives at recurrence 4, each half alone is dropped — so the test fails loudly the day someone "optimizes" the merge away. Three smaller judgments rode with it: the batch budget is derived from a *probe* of the served context when the model is up and a deliberately *low* default (16k, not the true 40k+) when it is not, because guessing the ceiling too high is precisely what caused the 400; an over-long single run is truncated to a prefix *with a logged note*, never dropped, and because the kept text is a prefix the byte-match anti-drift guarantee is untouched; and I made the OVMS client read the HTTP error *body* into its exception, because urllib swallows it in `str(exc)` and the lead had to reproduce the call by hand to see the body said "context length."

Then the second real pass rhymed with the first. Chunking had made the pass *long* instead of *impossible*: 26 sequential batches, each a ~10k-token prefill plus grammar-constrained generation on a 14B sharing a fanless Lunar Lake laptop's thermal envelope. The client's timeout was still the 300 s I set when a "request" meant one small call; under throttling a single batch legitimately ran many minutes, one crossed 300 s, urllib raised `TimeoutError`, and the pass fell over — having already spent twenty-eight minutes doing real work it now threw entirely away, because nothing had been written down. The timeout number is the least of it (raised to 1200 s and made a flag); the real lesson the lead named is that a long-running job over an unreliable substrate has to be *resumable*, and that is a property you design in, not bolt on after it burns you. The miner is now checkpointed — each batch's raw output persists to `.work/<date>/batch-NN.json` the instant it completes, a rerun skips every batch it already has, and I keyed each cache file to a hash of its bundle so a grown corpus or changed budget invalidates stale work rather than merging yesterday's evidence into today's shapes (the same quiet-corruption the byte-match rule refuses, one layer up). A failed batch is isolated, not fatal — logged and skipped, deliberately not cached so it retries next run — and a per-batch progress line, flushed, ends the twenty-eight-minute silence a supervisor had no signal through. The corollary both fixes live by: a green offline gate over a small fixture says nothing about the real substrate's limits, and the first real run is its own gate.

**Next:** the coordinator runs `python tools/lesson_miner/lesson_miner.py --real` in the next 14B window — it probes context, prints a progress line per batch, caches each under `.work/<date>/`, and resumes from the last completed batch if it dies partway; knobs `--request-timeout S` / `--batch-tokens N` / `--max-tokens N` if a batch is still killed mid-generation. Then read the candidates file and, only if the golden gate is judged acceptable, flip `surfacing_dormant`.

*(agentic-setup `db2b017` (chunked mining + cross-batch merge; golden 11/11, 23 unit) then `22ffa87` (timeout/resume/progress; max_tokens 4096→2048; golden 11/11, 29 unit); the miner is DORMANT behind `surfacing_dormant`, so nothing waits on it; the real pass is the coordinator's next-window run.)*


### 2026-07-10 — Probe, don't predict: ending the 20-vs-18 argument for good

*Plain summary: added `tools/dispatch_harness/probe.py` (`python -m tools.dispatch_harness.probe`) and reworked the battery night launcher's LEAN PREFLIGHT so that in the marginal RAM band it attempts a real 30B load OUTSIDE any job instead of admitting the night by arithmetic; #784. Lesson 201 tally.*

The LA put it plainly: the arithmetic swap gate was "an unnecessary
constraint that adds no value." He was right, and the shape of why is worth
keeping. The battery launcher admitted a night by *predicting* — it summed the
current Available RAM with the ~8.7 GiB the resident 14B gives back when the AO
steps aside, and proceeded only if that projection cleared a threshold (20.5
GiB = the swap driver's 20.0 gate plus margin). The #777 measurement then proved
a clean 30B load from **19.85 GiB** available. So there is a dead band — roughly
19.85 to 20.5 — where the launcher would wait all night, on 30-minute retries to
04:00, on a load that would have worked. Worse than idle: a burned night.

The tempting fix is to argue the threshold down — 20, then 18, then 17.5 as each
measurement lands. But every one of those numbers is a *proxy* for a fact we can
just observe. The threshold argument never ends because prediction is the wrong
instrument. So the gate now probes reality: in the marginal band it fires
`probe.py`, which stops the AO, attempts the real 30B load once, waits for it to
serve, and — always, in a `finally` — restores the AO. Load serves within the
deadline → run the night. Load fails → clean up and rejoin the retry loop. A
probe-over-threshold ends the argument permanently: the only question that ever
mattered was "will it load," and now we ask *that*, not a stand-in for it.

Two trade-offs went on the record. First, the **double load**: a probe that
succeeds loads the 30B, tears it down, and the night's first job loads it again
(~13 s warm). The alternative — hand the already-loaded 30B to job 1 — was
rejected: it would mean the probe reaching into the AO-mediated dispatch flow the
driver owns, fighting the step-aside/relaunch choreography for a 13-second
saving. A clean, stamps-nothing probe that the driver never has to know about is
worth one warm reload. Second, the **below-floor cutoff stays at 15 GiB** — but
now as a *sanity bound*, not a prediction. Below 15 GiB Available the box is
genuinely starved and the probe refuses to even try (exit 3, zero side effects);
above it, we measure rather than guess. 15 is a floor on "is it worth attempting,"
not a claim about "will it succeed" — that claim is the probe's job.

The load-bearing discipline was **side-effect containment** (lesson 224). The
probe runs OUTSIDE any job, so it must stamp *nothing* — no swap-state phase, no
scorecard, no fleet sentinel — or a probe attempt could be mistaken for a run and
poison the night it was meant to protect. Every side-effecting step reuses an
audited leg (`real_load_30b`, `real_stop_ovms`, `boot_launcher_detached`,
`real_backend_ready`, `procspawn.terminate_process_tree`); the probe adds no new
subprocess op. I audited each: none writes shared swap-state when called outside a
`SwapDriver`. The one wrinkle is stopping the AO. The driver *never* kills the AO
— in a real swap the AO steps aside by exiting itself and the driver merely waits
on its PID. The probe can't trigger that in-process step-aside on a separate live
AO, so it finds the launcher by its single-instance lock (`certs/launcher.lock`,
the authoritative pid), CONFIRMS the pid is genuinely a `-m launcher` (never a
recycled stranger), and tree-kills it. A forceful stop skips the launcher's
graceful cleanup and leaves a stale lock — exactly the driver's own `os._exit`
step-aside residual, which the next detached boot reclaims. I did NOT default the
probe's timeout to a fresh number: it reuses the already-registered
`START_LLM_TIMEOUT_S` (480 s), so no new timeout entered the registry.

Built and proven offline only: 12 injected-seam unit tests over the pure
`run_probe` (happy / load-fail / below-floor-touches-nothing / exception-mid-load
/ KeyboardInterrupt-abort / restore-raises-but-exit-preserved / --json shape /
timeout-reuse), the timeout-registry gate still green, and a live below-floor CLI
smoke (floor 999 → exit 3, measures RAM, touches nothing). The real load probe —
the thing that actually stops the AO and loads the 30B — is deliberately left to
the daylight verify: it is a live surface, and the battery owns the box overnight.

**Next:** in daylight, with the box idle, run `probe.py` for real once (watch it
stop the AO, load the 30B, restore the AO), confirm the JSON outcome + timings,
record the load seconds community-grade in `PERFORMANCE_LOG.md`, then merge both
branches and let the first probe-admitted night run.


