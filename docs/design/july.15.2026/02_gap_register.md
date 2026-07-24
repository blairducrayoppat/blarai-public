# Part 3 — The Gap Register

*Every gap between the running system and the target design (file 01). Numbered, severity-rated, each with a **verdict** (keep / refactor / rebuild), the **cost of leaving it**, and a **type**: **[defect]** = one correct fix, which I can make on your say-so, versus **[decision]** = a trade-off only you should weigh (capability, quality, or security posture). Per your own doctrine, defects I surface with a fix; decisions I surface for you to triage. This review changed nothing — everything here is a proposal.*

**Severity key:** CRITICAL = could cause irreversible loss or a silent security/quality failure · HIGH = serious, should be scheduled soon · MEDIUM = real, plan it · LOW = cleanup / hygiene.

**Tally:** 3 CRITICAL · 11 HIGH · 12 MEDIUM · several LOW. Almost all are **decisions**, because they touch capability, quality, or posture — which are yours.

---

## CROSS-CUTTING (findings that recur across all three systems — fix once, structurally)

**GX-1 · "Built-but-wired-into-nothing" is a recurring class, not isolated bugs. · HIGH · [decision→defect]**
The flagship security receipt (GP-1), the Factory's grader-strength check (GF-1), the coordinator boot canary, and the dead intent-router are all *built, tested, and called by nothing live*. Your own journal names this class (Lesson 46, six recurrences).
- **Verdict: refactor — one structural control.** A reachability gate test that fails when a control has no live production caller.
- **Cost of leaving it:** the pattern keeps recurring; controls that look present are absent, and the absence is invisible until a security or quality assumption built on them ships a hole.

**GX-2 · The system's own documentation has drifted from reality. · HIGH · [defect]**
Code comments call the internet-egress door "welded / empty / never fires in production" while it is live for search; configuration says "every flag OFF / DORMANT" directly above flags that are ON; a boot step named "verify TPM/Pluton attestation" actually does software-only validation; the 2026-07-15 decision to decline hardware-rooted trust is not in the decision register.
- **Verdict: refactor — scrub the drifted docs to match reality, add GX-1's sibling: a doc/reality reconciliation gate test.**
- **Cost of leaving it:** for a system whose documented journey is half the product (your portfolio + certification), a source tree that misdescribes its own security posture is actively misleading — and it drifted this far in under two months.

**GX-3 · Split-brain across two repositories. · MEDIUM · [decision]**
The Factory's "brain" (planning, grading, the swap driver) lives in the BlarAI repo — the product it builds — while its gates and containment live in the sibling `agentic-setup` repo, and the documented interface between them is bypassed by the live nightly path.
- **Verdict: refactor — declare one source-of-truth for orchestration.**
- **Cost of leaving it:** two orchestration surfaces that can silently drift; an auditor must read both repos to trust either; the Factory structurally depends on the artifact it produces.

---

## PRODUCT — architecture, security, data, inference

**GP-1 · The single-adjudication-door / cryptographic receipt is not in the live path. · CRITICAL · [decision]**
The "Action Authorization Boundary" — every action carries an unforgeable receipt, every destination refuses a request lacking one — is built, tested, and running as a service, but **no live code sends an action to it or validates a receipt.** The live gate is an in-process deterministic rule-check (sound, fail-closed) plus prompt/output governance. Not an open hole (a fixed tool allowlist + the structural egress guard cover it), but the flagship control is *absent where advertised*.
- **Verdict: refactor + decide.** Recommended: formally scope host-mode's gate to the deterministic checker + a **structural verdict-token chokepoint** (so a tool *cannot* skip adjudication), reserve the cryptographic receipt for the future multi-process topology, and rewrite the vision to match. Alternative: wire the full receipt path now.
- **Cost of leaving it:** a future capability expansion that *assumes* the receipt is enforcing would ship a real hole; and the documents keep claiming a live root-of-trust that is not live.

**GP-2 · The deterministic rules are now the *entire* live semantic gate — and they are modeled on the wrong operating system. · HIGH · [decision]**
Because the probabilistic gate is not in the live path (GP-1), the deterministic rule set *is* the security boundary — yet its restricted-path rules name Linux/guest paths (`/proc/`, `/etc/`, `/home/user/`) while the assistant runs host-side on Windows (`C:\Users\...`, the registry). Their completeness is unassured.
- **Verdict: keep the architecture (it is hardware-bound and correct), harden the rules** — property-test their completeness, add the Windows-host path model (or record that the fixed tool set makes path rules not-applicable in host-mode).
- **Cost of leaving it:** the one live semantic gate may not cover the real attack surface.

**GP-3 · No independent security supervisor; the gate and the assistant are the same weights. · HIGH · [decision — but the reframe is reassuring]**
The security gate and the assistant share one 14B model. **This is the constraint you asked about — and the review's headline finding is that it is *not* the binding limitation** (file 04): the correct answer is never a second model, it is the deterministic plane, which you have. The residual risks are narrower: the deterministic layer's completeness (GP-2), and a shared-model jailbreak affecting both roles at once — mitigated because the deterministic layer is authoritative and the probabilistic layer can only *tighten*, never loosen.
- **Verdict: keep the shared-model architecture; invest the security budget in the deterministic plane and training-side hardening, not in a second model.**
- **Cost of leaving it:** none, if the deterministic plane is matured (GP-1/GP-2) and the finetune is hardened (target 2.2). The danger is *mis*-diagnosing this as "we need more model," which wastes the budget where it cannot help.

**GP-4 · Internal isolation is nominal, not real. · HIGH · [decision]**
The security gate, the assistant, and the gateway are threads in *one* process sharing one memory space and one model; the "mutual TLS between agents" is loopback-to-self. A compromise of the assistant's tool loop is a compromise of the gate. The real isolation boundary (the guest VM) is dormant for daily chat.
- **Verdict: decide the threat model** — either state plainly what the loopback encryption defends (and drop the ceremony language that overclaims), or put the assistant behind real process/VM isolation as the decades target.
- **Cost of leaving it:** the design advertises isolation it does not have on the daily path; the honest threat model is undocumented.

**GP-5 · The knowledge bank's decrypted plaintext never leaves memory. · HIGH · [defect]**
The mitigation that zeroes and drops the decrypted embedding cache after idle (built for the substrate store) was never extended to the knowledge bank — its decrypted vectors, text, and search index sit in memory for the process's whole life. This is the largest long-lived plaintext-derived secret in RAM.
- **Verdict: refactor — extend the existing idle-unload/zeroing to the knowledge bank.**
- **Cost of leaving it:** a host-memory read (malware at your privilege, a crash dump, hibernation) exposes decrypted knowledge that a short idle timer would have cleared.

**GP-6 · KV-cache quantization is measured but not yet enabled on the 14B (gated on a quality A/B) and under-documented; the speculative-decoding speedup is unverified on your chip. · MEDIUM · [decision + defect]**
The binding memory cost is the KV cache (~5 GB at 32K), not the fixed weights, so **KV-cache quantization is a genuinely high-leverage lever — and it was measured** (2026-07-01 sweep, #709): **INT8 is the sweet spot** (KV 5.0→2.5 GiB, 2.3× faster prefill at 32K), GPU support confirmed, and INT8 KV is **already live for the 30B coder**. It is deliberately *not* enabled on the product 14B: per the DECISION_REGISTER, INT8-in-production is **gated on an answer-quality A/B (#715)** that has not yet run (INT4/2-bit KV can degrade the long-context recall a memory system leans on). So this is a measured, deliberately-deferred lever with only a provisional register note — *not* an unexplored one. Separately, external measurement on your exact processor shows draft-on-NPU speculative decoding is a net *slowdown*; the mandated ~2× must come from draft-on-GPU and needs re-confirming.
- **Verdict: decide + document — run the #715 answer-quality A/B, then decide on enabling INT8 KV for the 14B (INT8 the candidate), and formalize the measured lever + the decision in ADR-040 (was only a provisional register note). Separately, confirm the live speculative-draft device and re-measure the speedup.**
- **Cost of leaving it:** a measured ~2.5 GiB of KV headroom + a 2.3× long-context speedup stay unclaimed on the 14B until #715 runs, the decision stays undocumented, and the speculative-draft speedup may not be real.

**GP-7 · The assistant is a ~5,700-line god-object. · MEDIUM · [decision]**
One class carries ~40 responsibilities (conversation, tools, governance, retrieval, image generation, web search, dispatch, coordinator, preferences, vision) behind a 12-branch message router.
- **Verdict: refactor — decompose into real sub-services.**
- **Cost of leaving it:** the primary maintainability/testability risk and the place seams hide; every future change is riskier than it needs to be.

**GP-8 · No decades data-lifecycle. · MEDIUM · [decision]**
The knowledge/substrate stores grow forever; rejected documents, superseded preferences, and audit rows are retained indefinitely; nothing compacts. For a decades-horizon design there is no retention policy.
- **Verdict: refactor — define retention/compaction/tombstone-purge, run in the overnight window (unify with memory consolidation and CRDT compaction).**
- **Cost of leaving it:** unbounded on-disk growth and an ever-larger plaintext-on-decrypt surface over decades.

**GP-9 · Retrieval is brute-force with no approximate index; the semantic router is dead scaffolding; two search engines are duplicated. · MEDIUM/LOW · [decision]**
Cosine search scans every row per query (fine at personal scale, a named future cliff); a complete intent-router exists but is instantiated by nothing (and carries an unused certificate identity); two independent keyword-search implementations coexist.
- **Verdict: keep brute-force now (refactor to an approximate index at a named corpus-size trigger); rebuild-real or delete the router; unify the two search engines.**
- **Cost of leaving it:** modest now; a scaling cliff and a misleading dead service later.

**GP-10 · In-memory plaintext of decrypted content, the model, and prompts is an accepted-but-unstated residual. · MEDIUM · [decision]**
Decrypted data lives in host RAM as plaintext (deliberately out of scope today). For a decades system this is the largest standing residual once at-rest encryption is solved.
- **Verdict: decide — accept as a documented residual, or add a mitigation (disable hibernation/crash-dumps, host memory-integrity features).**
- **Cost of leaving it:** a documented, bounded residual; only a problem if left *undocumented*.

---

## FACTORY — the machinery that builds BlarAI

**GF-1 · The grader is the keystore the whole "no human reads code" premise rests on, and its strength is unmeasured. · CRITICAL · [decision]**
"Done" is judged by a test the 14B writes. The machinery refuses to fake a pass (genuinely excellent), but the grader's *discriminating strength* is never measured — the mutation-audit tool that would measure it is built and wired to nothing — and the grader is a single greedy model shot. A weak-but-non-empty test can bank an honestly-computed "green" on wrong code (measured coverage on real runs was 67%, with one "verified" criterion at zero coverage).
- **Verdict: rebuild the missing stage — wire the strength check into the green path (weak-grader → demote), add grader best-of-N and reference-implementation pre-validation.**
- **Cost of leaving it:** the one path where "green without a human" is honestly computed yet substantively *wrong* — and nothing catches it, because you never read the code.

**GF-2 · The planner and the grader-author are the same model — a correlated blind spot, and the classic reason cross-checking fails. · CRITICAL/HIGH · [decision]**
The 14B writes the plan, the tasks, *and* the grader. If it misreads your goal, plan and grader share the misreading and confidently certify the wrong build. The 1986 Knight-Leveson result proves "one version checks another" fails when both are built alike — and two runs of one model are far more alike than two human teams. This is structural.
- **Verdict: refactor — re-derive the acceptance criteria with a deliberately *different* pass (different model family, or a non-AI static check as one "version"); always surface the plan's assumptions to you so a silently-dropped feature is visible.**
- **Cost of leaving it:** a whole class of "built the wrong thing, certified it green" that no amount of Factory diligence can catch.

**GF-3 · The Factory has no durable memory of itself. · HIGH · [decision]**
The real record of what the Factory built and merged each night lives in a working directory outside version control and rotates away; the two in-repo logs hold two entries each; machine-written commits are not distinctly attributed.
- **Verdict: refactor — auto-archive run records into git; one signed per-artifact attestation binding supply-chain + AI-authorship provenance.**
- **Cost of leaving it:** from the durable record alone you cannot reconstruct what the Factory did most nights, nor prove a past "green" was correct — a decades-auditability hole.

**GF-4 · The Factory does not measure its own defect rate over time. · HIGH · [decision]**
Every trend instrument (defect-rate, false-done-rate, grader-leniency drift) is designed but not running. The proven need: one real job banked "green" seven nights running while its quality degraded monotonically — caught only by a human reading transcripts.
- **Verdict: rebuild-forward — stand up the minimal always-on self-measurement.**
- **Cost of leaving it:** slow quality erosion is invisible until a human happens to look.

**GF-5 · "Zero false-dones" is an unfalsified zero. · HIGH · [decision]**
The positive-control rigs that would prove the false-done detector *fires when it should* are excluded from the live campaign. So "zero false-dones" means "nothing tripped it," not "it provably works."
- **Verdict: keep the detector; schedule the positive-control rigs into the campaign.**
- **Cost of leaving it:** the headline safety metric is unproven.

**GF-6 · The prompt-injectable coder runs elevated; its containment is dormant. · HIGH · [decision]**
The local coder — air-gapped but prompt-injectable — runs as the elevated operator account overnight; the restricted-account + firewall containment is built but off, and its egress leg is knowingly unenforced (antivirus owns filtering).
- **Verdict: decide — activate containment, or formally retire the firewall leg and harden the air-gap.**
- **Cost of leaving it:** the component the review names as "the constrained artifact" is, at build time, the *least* constrained.

**GF-7 · Decomposition grain is the dominant real-world defect. · MEDIUM · [decision]**
The single biggest cause of failed builds is the 14B choosing the wrong task breakdown (over-splitting one file), which turns downstream steps into no-ops and manufactured busywork. Both recorded end-to-end runs hit this.
- **Verdict: refactor — templated decomposition + a measurement gold-set + an "already-satisfied" pre-check.**
- **Cost of leaving it:** most build failures, and wasted overnight GPU budget.

**GF-8 · Turn the security lens on the workshop. · MEDIUM · [decision]**
The build agents plausibly hold all three legs of the data-exfiltration "lethal trifecta" (repo secrets + untrusted issues/dependencies + full internet), and default to more privilege than any single task needs.
- **Verdict: decide — apply the product's own controls to the builders (capability-tagging of untrusted content, invented-dependency existence checks, planner/summarizer separation). This trades some build velocity for safety — a genuine posture call.**
- **Cost of leaving it:** the workshop is a softer target than the product it hardens.

**GF-9 · Latency/throughput residuals in the model-swap subsystem. · MEDIUM/LOW · [decision]**
The swap is fail-closed-to-brain-restored on every traced path (a real strength), but: the fast "stop a doomed run" watchdog is off (a 3-hour budget is the only backstop); the memory-gate measurement is a single sample that did not test the worst cases; serial one-at-a-time execution is a hardware fact.
- **Verdict: keep the fail-closed core; consider enabling the doom watchdog; widen the memory-gate measurement.**
- **Cost of leaving it:** wasted GPU time on wedged runs; unmeasured worst-case swap behavior.

**GF-10 · No reviewable intent contract — the keystone of a non-coder's factory is missing. · HIGH · [decision] · (deep-dive: file 05)**
Today the Factory captures your intent in a single thin clarification pass; there is no plain-language artifact you confirm (structured "EARS" rules + worked examples) and none that the grading oracles are derived from. This is the reviewable bridge a non-coder needs — the one thing you *can* read — and its absence is why GF-1 and GF-2 bite as hard as they do: the grader tests whatever the model inferred, not what you actually approved. **File 05 also sharpens GF-1** (gate on mutation score, not coverage — thin AI-written tests over-report success by ~20%) **and GF-2** (the correlated-failure result was replicated for coding agents in 2026 at 3.7× excess coincident failure; the fix is cross-lineage diversity — e.g. the local 30B coder as the independent check).
- **Verdict: build (Wave 2) — an owner-confirmable Intent Contract compiled into the layered oracle stack (file 05).**
- **Cost of leaving it:** you approve outcomes you cannot inspect, and the grader may faithfully certify a build against a goal you never actually confirmed.

---

## MANAGEMENT LAYER

**GM-1 · Detection (R1) is absent — you are structurally blind to faults. · HIGH · [decision]**
No proactive alerting anywhere; the app shows no health (no memory, model, VM, or service state — the backend exposes no health channel at all); coordinator alarms die at a log line the operator never sees; during a model swap the window closes and you are blind. Your own words (#878).
- **Verdict: build — the read-only Operations pane as the home for machinery-health alarms + a health line in the status surface.** Additive, no posture change.
- **Cost of leaving it:** you learn of a fault only by trying to act and failing — the defining pain of the whole layer.

**GM-2 · Decision support (R2) is absent, and must be static. · MEDIUM · [decision]**
Errors surface as raw exception text / codes; plain-language translation is deliberately routed to a log. There is no "here's what's wrong, here's your move" layer.
- **Verdict: build a static, rule-based fingerprint-code → plain-language "what's wrong + your move" map.** It **must** be static: the 14B is dead exactly when you need it (backend down, out of memory, boot failed).
- **Cost of leaving it:** even when you detect a fault, you have no idea what to do about it.

**GM-3 · Operator training/runbooks (R0) are thin and partly misinformation. · MEDIUM · [defect]**
The guides you are told to read first describe the *retired* devplatform agent fleet and point at files in the wrong repo; the "escalate to a technical owner" they name does not exist (you are the only human).
- **Verdict: rebuild-lean around the live system; scrub the retired-fleet framing (don't caveat it).**
- **Cost of leaving it:** the operator's mental-model documents actively mislead the person steering.

**GM-4 · The board is dominated by retired-fleet projects. · MEDIUM · [defect]**
Your Vikunja board's structure still reflects the sunsetting legacy fleet (one project 54% stale-open; an orphaned dashboard pointing at a file that does not exist).
- **Verdict: refactor — archive/retire the legacy projects so the board reads as the live source-of-truth.**
- **Cost of leaving it:** the board you steer by is cluttered with a system being retired.

**GM-5 · No coordinator liveness / the best plain-language digest is invisible. · MEDIUM · [decision]**
The one artifact designed to translate system state into plain language (a model-drafted digest) is routed only into an encrypted journal you cannot open; the status surface renders identically whether the coordinator is healthy or dead.
- **Verdict: fold into GM-1 (the Operations pane is the designed home); add a liveness indicator.**
- **Cost of leaving it:** a wedged or dead coordinator looks healthy.

---

## SURVIVABILITY

**GS-1 · No tested restore of the encrypted data; the recovery key is a single point of total loss. · CRITICAL · [decision]**
The recovery code is excellent and fail-closed, but decrypt-with-the-physical-key on *different hardware* has never been executed end to end, and the key is a single physical artifact with no required redundancy. Lose it and all born-encrypted data is permanently gone.
- **Verdict: keep the code; ADD a supervised hardware-migration drill (needs a second machine with a compatible security chip — an LA-present ceremony) + a key-redundancy decision (second copy / split-key).** **This is the #1 action in the whole review.**
- **Cost of leaving it:** the single worst outcome in the system — total, irreversible loss of decades of data — is one lost piece of paper away, on an untested path.

**GS-2 · The disaster-recovery build is broken as written, with no offline archive. · HIGH · [defect + decision]**
The documented recovery dependency-install command aborts (it pins an unrelated local package and a non-existent version); there is no offline dependency archive; a rebuild needs live third-party services to survive for decades; the model weights sit behind a single cloud copy.
- **Verdict: refactor the lockfile (defect) + build an offline dependency archive and a second weights copy (decision — cost vs decades-survivability).**
- **Cost of leaving it:** the primary decades recovery path does not work, and was never drilled.

**GS-3 · The public-mirror gate is a blocklist on an irreversible channel, and it already leaked. · HIGH · [decision]**
The weekly public-mirror leak-gate is a blocklist (the wrong default for the one outward, un-take-back-able channel); it already published the machine hostname and the encrypted-database access map; no test proves it blocks a planted secret or fails when disabled.
- **Verdict: refactor to an allowlist/manifest of publishable paths + a blocks-when-engaged / fails-when-off test.** **Fix this before the next public sync** (this review adds documents to the repo).
- **Cost of leaving it:** more leaks onto a channel where history-rewrite is prohibited, so a leaked secret is hard to purge.

**GS-4 · The model-upgrade path is untested and welded to one model family; the interpreter reaches end-of-life ~Oct 2027. · MEDIUM · [decision]**
The mandatory speculative decoding welds the brain to Qwen3's vocabulary (a cross-family swap forfeits the ~2× lever); no model-agnostic upgrade runbook exists; the runtime Python EOLs in ~2027; the runtime environment carries a 256-package development freeze.
- **Verdict: keep the upgrade watch; add a model-agnostic upgrade runbook; plan the interpreter migration; slim the runtime environment.**
- **Cost of leaving it:** the decades-horizon upgrade and migration paths are unproven.
