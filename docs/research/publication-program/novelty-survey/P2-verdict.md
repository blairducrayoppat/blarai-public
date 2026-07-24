---
title: P2 Novelty + Venue Survey Verdict — "When two correct things collide"
status: survey-output
area: research
piece: P2
tier: security education
purpose: REACH + security standing
surveyed: 2026-07-19
rubric: AUTHOR_KIT.md §I (all URLs access-dated 2026-07-19)
---

# P2 — "When two correct things collide" (composition-failure specimen collection)

**Piece (from VERIFIED_FACTS.md + README §1):** a curated collection of ~8 fully-documented
specimens where two *individually-correct* security controls interacted to produce a failure
(replay window between two TTLs, 2026-06-09 · SSRF-precheck-tripped kill-switch, 06-12 ·
write-only knowledge bank, 06-14 · unreachable ALLOW from composed fail-closed defaults, 07-02 ·
leak-validator swallow, 07-02 · instance-lock-killed test gate, 07-04 · recovery-killed-the-swap,
07-07). Each specimen: setup → collision → root cause → structural fix → transferable rule. One
real, fully-instrumented single-project system (n=1). Count "~8" — authors enumerate exactly from
the journal before print.

---

## 1. Prior-art map

Recency window applied: security architecture / composed-control failure = last 3 years + canonical
classics (rubric §I.2). Tiers per §I.3.

**Canonical classics (the thesis has deep ancestry — this is the honest framing anchor):**

| # | Who / what | Where | Tier | Overlap |
|---|---|---|---|---|
| A | Pamela Zave — the **feature-interaction problem**; "features individually correct still compose correctly together" is false; Distributed Feature Composition | pamelazave.com/fi.html ; Feature Interaction Workshop book series (IOS Press, vols V–IX) | T1 (author's own pages / proceedings) | Thesis axis: near-identical. Evidence axis: academic/formal-methods + telecom, not a security field collection. Audience axis: researchers. → **RELATED**, the canonical ancestor. |
| B | Hillel Wayne — "**Feature Interaction Bugs**" | hillelwayne.com/post/feature-interaction/ | T2 (named practitioner) | **Closest register.** Same thesis in a modern practitioner essay, quotes Zave. But: *hypothetical* SoupOn case + telecom, general software (explicitly "not security-focused"), a general essay — **not** a specimen catalog from one real instrumented system. → RELATED. |
| C | Charles Perrow — **Normal Accidents** (1984): interactive complexity + tight coupling → "system accidents" | en.wikipedia.org/wiki/Normal_Accidents (summary T3; book T1) | mixed | Theoretical backbone of *why* composed correct parts fail. No security specimen catalog. → RELATED/context. |
| D | Richard I. Cook — "**How Complex Systems Fail**" (1998/2000), classic essay | commonly hosted at how.complexsystems.fail — **verify URL at author time** (not live-fetched in this survey) | T2/classic | Same register (short, numbered, transferable). Medicine/systems, not security composition. → RELATED. |
| E | **Cryptographic composition** / Universal Composability (Canetti) — "security protocols are generally not compositional" | eprint.iacr.org/2000/067.pdf ; dl.acm.org/doi/10.1145/1165555.1165570 | T1 | Formal analog of our exact thesis, in security. Evidence axis: proofs about protocols, not operational controls in a running system. Audience: crypto theorists. → RELATED. |

**Recent (3-yr window):**

| # | Who / what | Where | Tier | Overlap |
|---|---|---|---|---|
| F | Kelly Shortridge & Aaron Rinehart — **Security Chaos Engineering** (O'Reilly, 2023) | securitychaoseng.com ; kellyshortridge.com/blog | T1/T2 | Nearest *security-register* treatment: "failure is never the result of one factor… multiple influencing factors working in concert." But methodology/how-to for running experiments, **not** a documented specimen collection of composition failures from one system. → RELATED (position against). |
| G | **danluu/post-mortems** + Dan Luu, "Reading postmortems" | github.com/danluu/post-mortems ; danluu.com/postmortem-lessons/ | T2 | The *collection* genre. But cross-org aggregation, general reliability (his own finding: config, not code, dominates), not security-control-composition from one instrumented system. → RELATED (genre model). |
| H | **LLM-agent guardrail-composition** failure literature (2025–2026): "Provably Secure Agent Guardrail" (arXiv 2605.29251); practitioner survey "AI Agent Security in 2026" ("every major 2025–2026 agent incident exploited the loop… none tripped a content filter") | arxiv.org/html/2605.29251v1 ; slavadubrov.github.io/blog/2026/04/20/ai-agent-security/ | T1/T2 | **Most timely adjacent** — composed guardrails bypass / over-refuse / cascade; our system *is* a composed-control AI agent. But these propose defenses/taxonomies; none is a field catalog of one system's own control collisions with shipped structural fixes. → RELATED (timeliness hook). |
| I | Illustrative single-instances of "two correct things collide": CrowdStrike 2024; Azure Front Door cleanup-tripped-latent-bug, Oct 2025; Cloudflare postmortem, Nov 18 2025 | en.wikipedia.org/wiki/2024_CrowdStrike-related_IT_outages ; news.ycombinator.com/item?id=45973709 | T2/T3 | Individual instances, not collections. Prove the *genre* is live in public discourse. → RELATED (not prior art per §I.1 — single instances). |

**No item is PRIOR ART** under §I.1 (substantial overlap on all three axes). Every candidate diverges
on at least one axis (evidence type, security-specificity, or single-system field-collection form).

## 2. The gap

The failure *class* is old and well-trodden (feature interaction, normal accidents, non-compositional
crypto) — **the idea is not the contribution and must not be claimed as one.** What is absent from the
literature is the **artifact**: a curated multi-specimen field collection of **security-control**
composition failures from **one fully-instrumented system**, each specimen carrying setup → collision
→ root cause → **shipped structural fix** → transferable rule, where both colliding things were
*individually-correct security controls*. The nearest works each miss exactly one leg — feature
interaction/UC have the thesis but are academic/formal and not security-operational; Security Chaos
Engineering has the security register but is methodology, not a specimen catalog; danluu has the
collection form but is cross-org general-reliability; the agent-guardrail papers are timely and
security-adjacent but propose defenses rather than documenting one system's own collisions.

**What a security educator would say ours adds:** the missing *worked-examples* layer between the
abstract phenomenon and the methodology — a teachable catalog that renders the composition-failure
class concrete in security controls, each with a named **structural-absence** remedy (the strongest
dormancy is code that isn't there) rather than a "be more careful" lesson. The transferable rule per
specimen is the pedagogical payload. The n=1 depth (every specimen cited to journal date + commit,
checkable) is the credibility engine, not a weakness.

## 3. Verdict

**GO** (confident), with one binding framing instruction — a within-GO reshape, not a structural one.

Reasoning an expert would accept: the thesis is 30+ years documented, so the piece earns its novelty
only from the artifact. Therefore it **must** name feature interaction (Zave) and normal accidents
(Perrow) as acknowledged ancestors in the opening, and lead with what is genuinely new — *security
controls specifically, one instrumented system, structural fixes shipped* — never with "composition
failures are a thing." Do that, and it clears expert scrutiny: it is the one thing none of the
ancestors is (a documented single-system security specimen catalog), which is precisely the program's
n=1 strength. Not STRONG-GO only because the phenomenon itself is saturated; the artifact is not.

## 4. Venue fit

Primary channels (README §1): home base + Hacker News; LessWrong crosspost; later BSides CFP; ACM
Queue / IEEE S&P as stretch pitches.

**(0) Home base — personal GitHub Pages blog on the public mirror.** Fit: **ideal** — the full ~8-specimen
collection lives here at a canonical URL the LA owns; every other channel links back. No gatekeeper,
no length limit. Register-defining exemplars: **danluu.com** (long-form systems essays that routinely
front-page HN), **rachelbythebay.com** (postmortem-voice deep-dives), **Hillel Wayne** (the
feature-interaction essay itself). Mechanics: none beyond the public-mirror leak gate (see §5).

**(1) Hacker News.** Fit: **strong** for the register, harsh on anything reading as self-promo.
Rules from news.ycombinator.com/newsguidelines.html (T1, accessed 2026-07-19), quoted:
- "*Please don't use HN primarily for promotion. It's ok to post your own stuff part of the time, but
  the primary use of the site should be for curiosity.*" → the LA account must not be promotion-only.
- "*use the original title, unless it is misleading or linkbait; don't editorialize*" and "*If the
  title contains a gratuitous number or number + adjective, we'd appreciate it if you'd crop it.*" →
  **do not title it "8 …"**; use the descriptive title.
- "*Don't solicit upvotes, comments, or submissions.*"
- Submission = paste the URL; no account-age/karma gate to submit; front-page survival is purely
  community votes. This is a normal link submission, **not** a "Show HN" (that tier is for things
  people can try/use).
Gold-standard exemplars (the bar): Cloudflare Nov-18-2025 postmortem — news.ycombinator.com/item?id=45973709
(transparent root-cause writeup, front-paged, "appreciated the honesty"); danluu/post-mortems —
news.ycombinator.com/item?id=18875834 (the collection genre, heavily discussed); danluu "Reading
postmortems" (thesis-from-a-corpus essay, widely front-paged). Why they're the bar: transparent,
mechanism-first, zero marketing tone.

**(2) LessWrong (crosspost — secondary; P3 is the LW-primary piece).** Fit: **good** —
security-mindset/engineering-epistemics is native here. Mechanics from lesswrong.com (T1, accessed
2026-07-19):
- Site Guide (…/5conQhfa4rgb4SaWx): new posts **default to Personal blogpost**; author can request
  **Frontpage**; moderators promote only if "*Useful, novel, and relevant to many LessWrong members*",
  "*Timeless*" (avoid current-events framing), and the post "*attempts to explain rather than
  persuade*." A specimen catalog fits "explain, not persuade" well.
- New User's Guide (…/LbbrnRvc9QwjJeics): **first post is reviewed before publication**; low/negative
  karma triggers **posting rate-limits**; crossposts should be **adapted to the LW audience**, not
  low-effort republished ("*many of these posts neither strike the moderators as particularly
  interesting… nor demonstrate an interest in LessWrong's culture/norms*"); higher bar for AI-topic
  newcomers.
Gold-standard exemplars: Yudkowsky, "Security Mindset and Ordinary Paranoia" —
lesswrong.com/posts/8gqrbnW758qjHFTrH (134 karma; the canonical LW security-reasoning post) and its
sequel "…and the Logistic Success Curve." Why: they teach a security *way of thinking* through worked
reasoning — exactly our register. Shaping note: as a new account, lead the crosspost with an
LW-culture-aware frame and request Frontpage.

**(3) BSides CFP (later).** Fit: **good** — first-timer-friendly, community-driven, case studies
preferred. Representative events (T1 CFP pages, accessed 2026-07-19):
- **BSides Las Vegas** (callforpapers.bsideslv.org/cfp ; bsideslv.org/proving-ground): **Proving
  Ground** pairs first-time speakers with a mentor for **4 months**, ending in a **25-min** talk;
  eligibility "*original research and not have previously presented a 20+ minute talk at an
  international security conference (1,000+ attendees)*"; 2026 CFP **opens Apr 1 / closes May 8**;
  reviewers reward "*thorough outline with time allocations*."
- **BSides San Diego** (bsidessd.org/cfp, via Sessionize): first-timers write "*Mentor Me Please!*"
  in Special Requests → paired with a mentor; dedicated **New Speaker Track** (unrecorded); 2026 CFP
  **closed Dec 15 2025** (timing varies per city).
- Cross-event norms (allbsides.com/cfp.html, T2 aggregator): CFPs open 3–6 mo out via
  Sessionize/Google Forms; **"No vendor pitches — reviewers will reject marketing content"**;
  "*demos, tools, or real-world case studies are strongly preferred over purely theoretical
  presentations.*"
Exemplars: the Proving Ground program + its 2024 retrospective panel "14 Years Later, Proving Ground
is Proving Out" (pretalx.com/bsideslv24/talk/SGL8CJ) evidence the first-timer→known-speaker pipeline.
**Gap flagged:** specific named alumni-talk attributions were not verifiable in this survey — author
must source concrete examples at draft time (do not assert unverified names). Shaping note: a
narrative catalog likely needs a **live-reproduction or released-tool hook** to compete in a CFP.

**(4) ACM Queue (stretch pitch).** Fit: register-**perfect** (problem-focused, practitioner audience:
architects, senior engineers) — but a **likely BLOCKER**. **Access gap (honest per §I.5):** the author-
guidelines page (queue.acm.org/author_guidelines.cfm) returned **HTTP 403 on direct fetch via two
routes on 2026-07-19**, and web.archive.org is not reachable from this tool, so I could not fetch the
page directly. Two independent search-engine snippets of that same primary page state Queue "*reviews
articles only from authors who have been specifically invited to submit manuscripts*" and "*does not
accept unsolicited submissions from the general public*." **Treat as invitation-only pending author-
time re-verification** — not a realistic unknown-author door without an invite or an editorial-board
contact. Exemplars (register bar): "The Network is Reliable" — queue.acm.org/detail.cfm?id=2655736
(thesis + real-world examples, practitioner voice); the 2025 memory-safety cluster ("Memory Safety
for Skeptics" id=3773095, "Practical Security in Production" id=3773097); "Kode Vicious" columns
(George V. Neville-Neil).

**(5) IEEE Security & Privacy magazine (stretch pitch).** Fit: **good** — explicitly practitioner-
inclusive. From the CFP page (computer.org/digital-library/magazines/sp/cfp-ieee-security-and-privacy,
T1, accessed 2026-07-19): writing should be "*down to earth, practical, and original*"; "*do not
submit research papers, particularly those that address a narrow technical area*"; welcomes surveys/
tutorials; "*contact the Editor-in-Chief*." **Access gap:** the canonical author page
(computer.org/csdl/magazine/sp/write-for-us/14680) is JS-rendered and returned only a shell on
2026-07-19 — **exact department names, word-limits, and review timelines not directly retrieved;
verify at author time.** Department precedent for a practitioner piece: "**Building Security In**"
(founded by Gary McGraw) — software-security-practice department; a composition-failure catalog fits a
**department/column**, not a peer-reviewed feature. Exemplar: the "Building Security In" department
line (garymcgraw.com hosts the archive). Shaping note: pitch a department editor with a 1-paragraph
proposal; peer-review timelines are long — this is a "after home base + HN traction" move.

## 5. Piece-specific risks

1. **Thesis-novelty overclaim (highest risk).** Composition failure is 30+ years documented (A–E
   above). Any "new failure class" claim gets shot down instantly. Mitigation is the §3 framing: cite
   ancestors up front; the contribution is the documented security artifact, not the idea. Claims about
   generality stay INTERPRETATION-typed and hedged (Author Kit §A/§E).
2. **Security-sensitive residuals (privacy-screen critical).** Several specimens describe failures in
   the live egress/policy machinery — the **SSRF-precheck kill-switch**, the **unreachable-ALLOW from
   composed fail-closed defaults**, the **leak-validator swallow**, and the **replay window between two
   TTLs**. Written as "collision" without "structural fix already shipped," any of these could read as
   partial vuln disclosure of the trust spine. **FLAG for the integrity/privacy reviewer:** confirm
   each specimen's fix is landed, and that no live-config detail of the egress/Policy-Agent door beyond
   what the public mirror already exposes appears in print (VERIFIED_FACTS.md §Privacy; source only from
   content clearing the public-mirror leak gate). This does not KILL the piece — it means each specimen
   must present as *closed* with the structural remedy, and the two egress-adjacent specimens get the
   hardest screen.
3. **Survivorship / n=1 framing.** The catalog is the collisions we *caught* on one instrumented
   system — frame as "what happened here, recorded as it happened," never "the composition failures
   agent systems exhibit" (Author Kit §E).
4. **"Structural fix" as universal law.** The structural-absence remedies are ours on this
   architecture; transferable rules are hedged INTERPRETATION, not general prescriptions.
5. **Enumeration accuracy (§B pass).** VERIFIED_FACTS lists the count as "~8" and **seven** dated
   specimens — reconcile the 7-vs-8 count and re-derive every date + commit SHA from the journal before
   print; no placeholders.
6. **HN title hazard.** Guidelines discourage gratuitous numbers in titles — do not lead with "8".
7. **BSides format mismatch.** A prose catalog may under-compete against demo/tool talks; reshape into
   "the class + one live reproduction" for a CFP.
