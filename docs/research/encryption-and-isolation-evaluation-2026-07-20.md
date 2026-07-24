# Four Technology Questions — Homomorphic Encryption, MXC, and win-dev-skills

**Date:** 2026-07-20
**Asked by:** Lead Architect
**Answered by:** Claude session (Opus 4.8), grounded on disk + primary sources
**Status:** ANALYSIS + RECOMMENDATIONS. No code changed. Decisions recorded to Vikunja (#611 comment, plus two new tickets).

> **Acronyms on first use.** FHE = Fully Homomorphic Encryption. MXC = Microsoft eXecution Container.
> TEE = Trusted Execution Environment. VBS = Virtualization-Based Security. DEK = Data-Encryption Key.
> RAM = the computer's working memory. iGPU = integrated graphics processor (our Arc 140V).
> LA = Lead Architect. ADR = Architecture Decision Record.

---

## 0. The four answers, up front

| # | Question | Answer | Why, in one line |
|---|---|---|---|
| 1 | Should BlarAI use homomorphic encryption? | **No** | Its value comes from separating who computes from who holds the key. BlarAI is both, on one machine — there is no separation to exploit. |
| 2 | Would it be practical? | **No, by a wide margin** | 1,000–10,000× slowdown, on the machine where memory is already our scarcest resource. |
| 3 | Same questions for the coder agent? | **No, more clearly** | The coder agent's exposure is that a cloud model must *read* the code. No encryption scheme lets a model understand text it cannot read. |
| 4 | MXC instead of Hyper-V? | **No** — and the premise doesn't hold | MXC is not a hypervisor and not a Hyper-V replacement. Microsoft states plainly that **"no MXC profiles should be treated as security boundaries currently."** |
| 5 | Does win-dev-skills provide value safely? | **Qualified yes** | Real value for our WinUI app — but **vendor 3 skills at a pinned commit; never marketplace-install**, which tracks the latest automatically. |

---

## 1. Homomorphic encryption for BlarAI

### 1.1 Why this was a good question to ask

This is not a naive question. It targets a genuine, documented gap in our own analysis.

Ticket **#611** ("live-memory attacker — key/plaintext in RAM during operation") is our standing record of
the one hole at-rest encryption does not close: while BlarAI runs, the encryption key and the decrypted
text must exist in readable memory. The June 2026 feasibility study concluded honestly that this window is
**irreducible**, and its §4 named "confidential-compute / TEE-style isolation" as *the only* class of
construct that changes it. Quoted inline, verbatim (`611-live-memory-feasibility.md:325`):

> "The only constructs that meaningfully change *that* are confidential-compute / TEE-style isolation
> (out of scope for this hardware/era)."

> **Why quoted rather than cited.** That study lives at `docs/handoffs/611-live-memory-feasibility.md`,
> and `docs/handoffs/` is **gitignored** (`.gitignore:199`). A future session grounding itself through git
> will never find the file. The load-bearing text is therefore reproduced here, in a tracked document, so
> this conclusion does not rest on a path that vanishes.

**That study never evaluated homomorphic encryption.** FHE is the one technology that claims to compute on
data without ever decrypting it — precisely the claim #611 says is unachievable. So the question fills a
real gap, and the answer below is being recorded onto #611 so the next person doesn't have to re-ask it.

### 1.2 What FHE actually is, in plain language

Ordinary encryption is a locked box: to use what's inside, you unlock it, and while it's open, it's readable.
Homomorphic encryption is a box with gloves built into the sides — someone can reach in and rearrange the
contents without ever opening it. You hand them a sealed box, they do work on it, they hand it back still
sealed, and only you can open the result.

The value is entirely in that hand-off. FHE exists so you can send your private data to **someone else's
computer** — a cloud provider, a hospital, a bank — and have them compute on it while remaining unable to
read it.

### 1.3 Why it does not help BlarAI — the structural reason

**BlarAI has no hand-off.** The data owner, the computer doing the work, and the holder of the key are all
the same party, on the same laptop. There is no second party to be protected from.

Walk the #611 threat through it. The attacker in #611 is someone who gets code running on the live machine.
Under FHE, that attacker finds:

- The **key**, sitting in the same RAM — because BlarAI must hold the key to encrypt your question and to
  decrypt the answer it shows you.
- Your **question in plaintext**, because you typed it and it had to be readable to be encrypted.
- The **answer in plaintext**, because it must be decrypted for you to read it on screen.

FHE would encrypt the *intermediate* arithmetic in the middle. The attacker doesn't want the intermediate
arithmetic; they want the question, the answer, and the key — all three of which remain exactly as exposed
as they are today. **The window barely moves, and the key protection is nil.**

This is the general rule, and it is worth internalizing because it recurs: *encryption protects data from
parties that don't hold the key. When you hold your own key on your own machine, encrypting against
yourself buys nothing.* It is the cryptographic equivalent of locking your front door and taping the key to
the door.

**Scope boundary on this argument (added after verification).** The argument holds for **single-machine
local inference** — BlarAI's actual and intended architecture. It would **legitimately reopen** if BlarAI
ever burst inference to remote compute it does not control. That is the one architecture where FHE genuinely
applies, and it is the architecture every paper in the field assumes. Recording the boundary explicitly so a
future reader knows exactly which change would reopen the question, rather than treating "no" as permanent
regardless of design.

**Adopting FHE would also *increase* our attack surface.** This is not a neutral "costs a lot, gains
nothing" — it is net negative. Practical IND-CPA^D key-recovery attacks against standard BFV/BGV parameters
were published in February 2024, recovering secret keys *"from few minutes up to a couple of hours on a
standard machine."* More broadly, FHE is a low-level primitive that *"is not possible [to build secure
protocols from] without the help of a cryptography expert; even in the simplest cases such protocols can
result in unexpected or unintended security gaps."* Against a fail-closed, defense-in-depth posture that
deliberately avoids hand-rolled cryptography (ADR-025 §2: no new crypto dependency), introducing FHE would
add a novel, expert-only failure surface in exchange for nothing.

**Every alternative construction was tested and failed.** The verification pass attacked this argument with
threshold/multi-key FHE (needs two or more *non-colluding* parties — one laptop is one party, and it adds a
key-recovery surface), holding the key in the TPM instead of RAM (FHE evaluation keys run ~150–240 MB and
bootstrapping keys reach multiple GB; TPMs cannot store or compute on these, and the decrypted output is
plaintext in RAM regardless), encrypted index search (inverted premise — in that setting the *server* holds
the database; here the user owns both query and index), hybrid partial encryption (dominated, per §1.4), and
FHE as intra-machine privilege separation for untrusted plugins (our existing VM/vsock boundary already
solves that structurally at zero cost). None survived.

### 1.4 Why it would not be practical either, even if it did help

*(Figures below corrected 2026-07-20 after an adversarial verification pass. The original draft cited an
unanchored "~68 seconds" and left a contrary data point unresolved. Both are fixed; the corrected numbers
are **worse** for FHE than what was first filed.)*

The consensus overhead for running a transformer under FHE is roughly **1,000× to 10,000× slower than
plaintext** ([wavect, 2026](https://wavect.io/blog/fully-homomorphic-encryption-practical-2026/)) — and for
transformers specifically that consensus figure *understates* it. Measured results:

| System | Model | Hardware | Result |
|---|---|---|---|
| NEXUS (NDSS 2024) | BERT-base (110M) | server | 37.3 s per inference |
| THOR (CCS 2025) | BERT-base, 128 tokens | single GPU | **600 s (10 minutes)** |
| **Cachemir (Feb 2026)** | **Llama-3-8B** | **NVIDIA A100-80GB** | **under 100 s per output token** |
| Cachemir (Feb 2026) | Llama-3-8B | Xeon 8558P, 192 threads | 477.81 s per output token |

The load-bearing comparator is **Cachemir**: a *generative* model *smaller* than our Qwen3-14B, on a
datacenter A100, at **under 100 seconds per output token**. THOR's 600 s against a ~5–50 ms plaintext
BERT-base forward pass is a **12,000×–120,000×** slowdown.

Three facts make this worse specifically for us:

- **Memory is disqualifying before speed even matters.** Cachemir keeps *weights in plaintext* and still
  reports weight plaintexts in the hundreds of gigabytes, plus **~17 GB for a 1024-token key-value cache
  alone**. Our 31.323 GB ceiling is exceeded by the cache before any weights load.
- **This machine sits below the FHE acceleration floor on CPU, GPU, and NPU simultaneously.** *(This
  replaces a weaker original claim that "no FHE runs on OpenVINO" — true but not the sharp point, and
  slightly too strong given a research SYCL backend for Intel GPUs exists.)* The real finding: **Intel HEXL,
  the main CPU acceleration path for SEAL/OpenFHE/HElib, requires AVX512-IFMA52**, which Lunar Lake does not
  expose. The NPU is structurally mismatched — low-precision integer matrix multiply versus FHE's
  high-precision modular arithmetic over a 1763-bit modulus.
- **No FHE accelerator has shipped to buyers.** The DARPA DPRIVE lineage (Intel HERACLES, Duality/TREBUCHET,
  Niobium), Fabric Cryptography, Optalysys, and Cornami have produced *"simulation results and projections,
  not shipped silicon."* ASICs are expected 2027 or later. The only purchasable acceleration is
  datacenter-class GPUs.

**The open item is now closed — and it was never a contradiction.** The earlier draft flagged arXiv
2604.12168 (*"Fully Homomorphic Encryption on Llama 3 model"*), which reports far better figures, and
honestly noted it was unverified. The paper was fetched and read. It **encrypts one attention head of one
layer, leaving 31 of 32 layers in plaintext**, at 2-bit quantization, with the decrypted logits passed to
softmax *"in clear."* Its own numbers tell the story: plaintext 142 tokens/sec → 80 with a single head
encrypted (a 44% loss to protect ~1/32 of one layer) → **30 tokens/sec with all heads encrypted, and only at
2-bit quantization** — itself a severe quality reduction that would be an LA decision in its own right. The
paper also contains an internal inconsistency (237 ms/token implies ~4 tokens/sec, not 80).

**And the decisive irony:** that paper's own architecture is explicitly client-server — *"Client: Holds
sensitive input text and the private key"*; *"Server: Hosts the LLM and receives encrypted embeddings."*
The apparent counter-example presupposes exactly the separation BlarAI does not have. **It corroborates the
structural argument rather than undermining it.**

Realistically: a response that takes seconds today would take hours to days, on hardware that cannot hold
the intermediate state. This is not a tuning problem.

*One claim held provisional:* the Lunar Lake AVX-512 status above rests on an ISA listing plus secondary
technical reporting, not an Intel datasheet line. High confidence, but it should get one datasheet
confirmation before being cited externally — see §5b for why that caution is not hypothetical.

### 1.5 Where FHE genuinely is the right tool — for contrast

FHE ships in production, but always in the hand-off shape: Apple's Live Caller ID Lookup (your phone asks
Apple's servers about a number without revealing the number), private set intersection between two companies,
encrypted password-breach checking. Every one of these has **two parties who don't trust each other**.

BlarAI's founding design decision — everything runs locally on your own hardware — is precisely the decision
that makes FHE unnecessary. **We already have what FHE is a workaround for.** Adopting FHE would be paying a
four-order-of-magnitude tax to simulate a property we obtained for free by not using the cloud.

### 1.6 What actually addresses #611's residual

The adjacent technology is confidential computing / TEE — hardware that walls off memory even from the
operating system. Industry consensus in the search evidence is explicit: *"for private LLM inference today,
confidential GPUs are the pragmatic option compared to fully homomorphic encryption."*

**That door is closed here twice over — once by hardware, once by your decision.**

- **By hardware:** ADR-007 (accepted 2026-02-23) records the *measured* result on this silicon —
  **TDX = false, SGX = false, TME/MKTME = false, TDISP = false** on Lunar Lake, disposition
  `EXPECTED_ABSENT`. The confidential-computing features that would close the in-use window are physically
  not present on this chip. This is the hardware fact underneath #611's "out of scope for this
  hardware/era" phrasing.
- **By decision:** on 2026-07-15 you declined full hardware-rooted trust — Pluton sealing, measured boot,
  and PCR-seal tooling all declined, tickets #103/#104/#105/#106/#627 closed, while the live
  signed-manifest / TPM / mTLS / at-rest controls stay.

FHE does not reopen either and is not a way around them.

**ADR-007 is also independent on-disk confirmation of the structural argument.** That ADR accepted a
specific residual risk: because TME/MKTME is absent, *"LPDDR5X contents are not encrypted at rest"* — an
accepted cold-boot exposure. That is this machine's one genuine in-RAM exposure. **FHE cannot close it
either**, because the FHE secret key and evaluation keys would sit in exactly that same unencrypted
LPDDR5X alongside everything else. The machine's real memory-exposure gap is precisely the gap FHE is
structurally incapable of addressing.

**There is also a directly applicable precedent — with an important asymmetry.** ADR-028 Amendment 1 records
that production trust-root keys will **not** be PCR-bound — a decision taken *after*
`docs/security/pcr_seal_poc_2026-06-09.md` proved the primitive works on this chip. Combined with the
2026-07-15 decision, the project has a standing pattern: **prove an exotic cryptographic primitive feasible,
then deliberately decline to adopt it** because the operational cost exceeds the marginal security return.

**FHE is a stronger "no" than either of those, and the difference matters.** In the PCR case the primitive
was *feasible* and was declined on cost. FHE is **neither feasible here nor applicable anywhere in this
architecture**. A future reader should not mistake this for a close call that better hardware might flip.
**It will not flip on hardware** — the structural argument in §1.3 is independent of performance entirely.
Only an architecture change (moving inference to compute we do not control) would reopen it.

So #611's disposition is unchanged: it remains a **window-and-footprint reduction exercise, not a
hole-closure exercise**, exactly as the June study framed it. FHE is now evaluated and closed as a fourth
candidate. Nothing to build.

---

## 2. The same question for the coder agent

**No — and here the reasoning is even shorter.**

The coder agent's privacy exposure is not that data sits in memory. It is that **source code leaves this
machine and is read by a cloud model** in order to be reasoned about.

FHE cannot touch that. A model must *understand* the code to write code against it, and understanding
requires reading. There is no scheme in which a remote language model produces a correct patch for code it
cannot read. The gloves-in-the-box trick works for arithmetic on numbers; it does not work for comprehension.

The controls that actually address the coder agent's exposure are the ones already decided and in flight:

- **Containment** — the restricted Windows account + firewall approach (Dispatch containment Decision 1,
  2026-07-10), limiting what a dispatch can reach.
- **Scoping** — controlling which parts of the tree a dispatch can read at all.

Those are the right lever. FHE is not on this axis.

---

## 3. MXC instead of Hyper-V

### 3.1 The premise doesn't hold — and that's the useful part of the answer

I verified the repository directly. `microsoft/mxc` is real, active, MIT-licensed (created 2026-02-06,
pushed 2026-07-20, ~1,139 stars). But it is **not a hypervisor, and not a Hyper-V alternative.**

MXC describes itself as *"a sandboxed code execution system for running untrusted code (model output,
plugins, tools) on Windows, Linux, and macOS."* It is a **portable abstraction layer over about nine
different sandboxing backends** — ProcessContainer, Windows Sandbox, LXC, Bubblewrap, Seatbelt, MicroVM,
Hyperlight, IsolationSession, WSLC. It sits *above* isolation primitives; it does not replace one.

So "MXC instead of Hyper-V" compares two different categories of thing. That's worth knowing rather than
glossing — the question you're really asking ("is our isolation substrate the right one?") is a good one,
and it has a separate answer in §3.3.

### 3.2 The disqualifier, in Microsoft's own words

From the project's own README:

> **"no MXC profiles should be treated as security boundaries currently."**

It is labelled an *"early preview of code published to enable early integration,"* with acknowledged
*"known cases where the current policies… are overly permissive."*

That single sentence ends the evaluation for our purposes. BlarAI's isolation is load-bearing and
fail-closed. Our security principles require **defense-in-depth with multiple independent locks** and treat
a **fail-open as a defect to fix immediately**. Adopting a component that explicitly disclaims being a
security boundary, *as* a security boundary, is the exact anti-pattern those principles exist to prevent.

**Verified against the full warning block (2026-07-20).** The scope is **blanket** — *"**no** MXC profiles"*
is universal quantification, carving out no custom profile and no exempt backend. The reading holds. Two
refinements from that verification:

- **The disclaimer scopes the *profile layer*, not the underlying primitives.** Hardware virtualization
  (WHP/KVM) is real and exists independently of MXC. What Microsoft disclaims is that **its profile layer
  correctly and completely drives those primitives**. The precise framing: *a hardware boundary may
  genuinely exist underneath; MXC's profile is not what guarantees you got it.*
- **The narrower defect claim is narrower than I quoted.** *"Known cases… overly permissive"* applies
  specifically to policies **generated by the MXC SDK in this repository** — not to the whole project.

**Correction — I treated MXC as monolithic, and the backend tiers matter:**

| Backend | Boundary class | Default? |
|---|---|---|
| Hyperlight | **Hardware-virtualization** (KVM/WHP) | Experimental |
| MicroVM / NanVix | **Hardware-virtualization** (WHP/KVM) | Experimental |
| Windows Sandbox | Hardware-virtualization (Hyper-V) | Experimental |
| WSLC | Mixed — VM shared; per-sandbox is namespace-level | Experimental |
| LXC | Kernel / namespace | Stable (Linux) |
| Bubblewrap | Kernel / namespace | **Linux default** |
| IsolationSession | OS-policy (session) | Experimental |
| ProcessContainer | **OS-policy** (AppContainer) | **Windows default** |
| Seatbelt | OS-policy (macOS) | macOS default |

So "not a security boundary" is **too broad as a statement about isolation technology** but **correct about
MXC as a product**. Crucially, the composition strengthens rather than weakens the disqualifier: **every
hardware-enforced backend is gated behind an experimental opt-in, and both platform defaults sit in the
weakest tier.** The virtualization backends are the *least* mature code in the repository, not a stronger
exempt tier one could adopt instead.

**Two fail-opens found in the source, worth recording:** on the *stable, default Linux* backend, a Bubblewrap
proxy combined with `defaultPolicy='block'` emits only a **warning**, not a rejection — raw-socket clients
ignoring `HTTP_PROXY` reach the host network. And `--audit` *"relaxes the rejection of
`permissiveLearningMode`"* such that AppContainer restrictions are not enforced; it also elevates via
`runas`, producing a UAC prompt per start and stop, which would strand any scheduled or overnight run.

### 3.3 And the hypervisor isn't our constraint anyway

Even setting MXC aside: swapping isolation substrates would not buy what it appears to buy, because our
real constraint is hardware, not hypervisor.

**ADR-041** records it precisely: LLM inference runs only on the host-resident Arc 140V iGPU (ADR-011), and
**a Hyper-V guest cannot reach that GPU**. This is why the original per-agent-VM topology is *foreclosed* —
not deferred, foreclosed. Any isolation technology, MXC included, hits the same wall: the AI work must run
host-side regardless of what we containerize with.

**Correction to an earlier draft of this section.** I initially wrote that the Alpine guest is "dormant
infrastructure" because `Get-VM` reports **BlarAI-Orchestrator = Off**, and concluded we would be swapping
out a substrate that isn't running. **That was wrong, and an independent on-disk check caught it.** The
accurate picture:

- Host-mode is confirmed live: `deployment_mode = "host"` in both
  `services/assistant_orchestrator/config/default.toml:6` and `services/policy_agent/config/default.toml:5`,
  with `DeploymentMode.HOST` as the code default (`shared/runtime_config.py:191`).
- But **the guest oracle is LIVE, not dormant** — `guest_oracle_enabled = true`
  (`services/assistant_orchestrator/config/default.toml:467`), live since the LA-supervised go-live ceremony
  of 2026-07-08 (#744), running over vsock 50002 in the NIC-less Alpine guest.
- The VM reads `Off` only because since #788 the launcher performs **lazy point-of-use VM start**
  (`launcher/__main__.py:821-859`) — it boots the guest on demand per job and fails closed if it cannot.
  **Off means idle-until-needed, not decommissioned.**
- The guest *parser* is genuinely off (`launcher/config/default.toml:22` → `enabled = false`).

**What survives and what doesn't.** The core claim survives: nothing in the conversational hot path —
Policy-Agent adjudication, the Assistant Orchestrator, model inference — crosses the VM boundary, so a
substrate change buys nothing where it would matter. **What does not survive is the implication that a
substrate change would therefore be cheap.** It would break the live #744 guest-oracle corridor and require
its own go-live re-ceremony. The guest oracle is advisory-only and fail-soft (it never changes a job verdict;
the host gate remains the fidelity gate), so the blast radius is bounded — but it is not zero, and I should
not have said the substrate was idle.

*(Related documentation defect found during this check: `PHASE1_DISPATCH_THREAT_MODEL.md:304` still describes
the guest oracle as "currently dormant (triple-gated)". That row is stale — superseded by the 2026-07-08
ceremony — and it is a security document. Ticketed separately; do not cite that row.)*

### 3.4 But it is worth watching — for a different job

MXC's actual purpose maps onto a real BlarAI need we haven't solved: **sandboxing untrusted model output and
tool execution**. That is genuinely adjacent to our guest-side parser boundary work (#615) and to any future
capability where BlarAI executes something it generated.

**Recommendation:** watchlist ticket, not adoption.

**Correction — "watchlist only" understated what is happening.** MXC is not drifting; it is on an **active
general-availability program** with fail-closed enforcement as the stated destination. Its network GA
specification defines `egress.allow[]/deny[]` with CIDR, port and protocol, and states that when a
connection matches both, **"the deny wins (fail-closed)"**, with proxy cooperation *"never the enforcement
mechanism itself."* It launched publicly at Build 2026, where Microsoft's developer blog says MXC
*"enforces those boundaries at runtime."* Becoming a real enforcement boundary is the goal, not a
disclaimed non-goal. It is also already shipping inside Microsoft products (GitHub Copilot CLI process
isolation; Agent 365 integration in preview), at 207 commits in 30 days — while **every schema remains
`-alpha`**.

**Correction — the re-check trigger as originally filed was unsafe and is re-keyed.** I wrote "exits early
preview AND makes an affirmative security-boundary claim." Microsoft's *marketing* arguably already
satisfies the second half — the Build blog's "enforces those boundaries at runtime" sits in direct tension
with the repository's own warning. A trigger that marketing copy can trip is not a trigger. **Re-keyed to
repository artifacts:**

1. The `[!WARNING]` block in `README.md` is **removed or materially amended**, and
2. The configuration schema reaches a **non-alpha version**.

**Adoption would additionally require resolving four things**, recorded now so a future re-check doesn't
rediscover them: there is **no Python SDK** (TypeScript/Node only — we would shell out to `wxc-exec.exe`);
the default backend is the weak tier, so a real boundary means the experimental ones; **MXC ships its own
policy engine**, so it could only ever be adopted as an enforcement mechanism *subordinate to* the Policy
Agent, never as a second adjudicator (our single-adjudication-door principle); and `--audit` must be
structurally blocked, not merely unused.

**A warning to carry into any future re-check.** MXC's own `docs/hyperlight-integration-plan.md` states
*"Network: None"* and *"No network stack in guest."* **The source contradicts it.**
`src/backends/hyperlight/common/src/lib.rs` documents *"Networking | Host-proxied sockets via
NetworkPolicy"* and states plainly that *"network policies ARE supported."* Hyperlight networking is
policy-configured off — **not structurally absent**. Anyone re-evaluating MXC from its documentation, without
reading that source file, will reach the wrong conclusion about the single property that matters most to us.
*(This is the third independent instance of the same failure mode in this session — see §5c.)*

---

## 4. microsoft/win-dev-skills

### 4.1 Verdict (REVISED 2026-07-20 after a file-level audit): text-only, binaries stripped

> **This section was materially revised.** The original verdict was formed by reading the repository README.
> A subsequent audit read the actual skill files, all six plugin manifests, the PowerShell scripts, and the
> C# source of the shipped binary — and **refuted the top-rated recommendation**. A README describes intent;
> it cannot describe what a 7.6 MB executable does at runtime. The original reasoning about the *instruction
> text* held up well; the reasoning about the *artifact layer* did not. Details in §4.3 and §4.5.

Verified: real, active, MIT-licensed (created 2026-03-03, pushed 2026-07-17, ~359 stars). It provides one
agent (`winui-dev`) and eight skills for WinUI 3 / Windows App SDK development.

The value is real and specific. Our desktop app — the primary face of BlarAI — is
`services/ui_winui/BlarAI.Desktop.csproj`: **WinUI 3, Windows App SDK 1.8.260508005, .NET 8, unpackaged
self-contained**. That is dead center of what this repo targets.

**Critically: this is dev-side, not runtime.** These are instructions for the tool that *builds* BlarAI, not
code that ships *inside* BlarAI. BlarAI's air-gap and runtime restrictions are untouched by this. The
relevant risk is to the machine that builds the system, which is why the pinning discipline below matters.

### 4.2 Per-skill assessment against our actual stack

| Skill | Verdict | Reasoning |
|---|---|---|
| `winui-design` | ~~Adopt~~ → **TEXT ONLY, strip the binary** | **Original rating refuted.** The command this skill instructs the agent to run (`winui-search.exe`) silently spawns a *detached* background process that fetches from the `main` branch of two other repositories and feeds the result to the agent as design guidance. See F4. Static guidance is valuable; the executable is not adoptable. |
| `winui-code-review` | **Adopt (text), with a caveat** | Instruction text is clean. But it depends on an analyzer shipped inside `winui-dev-workflow` (Skip), so the analyzer never loads. Usable as review guidance only. |
| `winui-ui-testing` | ~~Adopt (highest value)~~ → **Not adoptable standalone** | Instruction text is clean, but the skill is built entirely on the `winapp ui` CLI (16 verbs) — an external tool only `winui-setup` (Reject) installs. Cannot run without accepting the toolchain we rejected. |
| `winui-dev` (agent) | **Reject as-is** | Its "Before continuing" block *mandates* loading `winui-dev-workflow` (Skip) and `winui-design`. Does not compose with selective adoption. |
| `winui-dev-workflow` | Skip | We have a proven build invocation. Also instructs *"**Never** specify `--version`"* — an explicit anti-pinning instruction (F6). |
| `winui-packaging` | **Reject** (upgraded from Skip) | Not merely irrelevant. Instructs installing a code-signing certificate into the **machine Trusted Root store**, persisting across reboots, with a documented default PFX password of `password` (F5). |
| `winui-wpf-migration` | Skip (clean) | We have no WPF. Pure guidance, no executable content. |
| `winui-setup` | **Reject** | Confirmed: `winget install Microsoft.DotNet.SDK.10` (we target .NET 8), always-on `winget upgrade`, template installs, and an HKLM `AllowDevelopmentWithoutDevLicense` write via `Start-Process -Verb RunAs`. *Mitigation originally missed: it carries `disable-model-invocation: true`, so an agent cannot self-trigger it.* |
| `winui-session-report` | **Reject** | Confirmed: reads `CLAUDE_SESSION_ID`, `CLAUDECODE`, `CLAUDE_CODE_ENTRYPOINT`, `COPILOT_*`, and parses session JSONL including subagent transcripts. *Mitigations originally missed: `disable-model-invocation: true`, plus a mandated verbatim privacy warning naming "your prompts verbatim (including any secrets you may have pasted)."* |

### 4.3 Security findings (revised — file-level audit)

**F1 — the marketplace install path tracks HEAD. CONFIRMED, and worse than first stated.** Documentation
states *"the marketplace install path always picks up the latest,"* making a third-party repository an
auto-updating source of instructions loaded into an agent's context. **But pinning does not fix the whole
problem** — see F4.

**F2 — prebuilt binaries. PARTIALLY CORRECT; one sub-claim refuted.** Two committed blobs:
`Microsoft.WindowsAppSDK.Analyzers.dll` (49,664 B, in `winui-dev-workflow/analyzer/`) and `winui-search.exe`
(7,992,832 B, in `winui-design/`). My original framing implied opaque executables. **That is refuted for
provenance:** full C# source for `winui-search.exe` *is* in the repo at `src/tools/winui-search/`. The
accurate, narrower finding: the DLL is sha256-compared against a CI rebuild, while CI **explicitly declines
to verify the exe** — *"The skill ships a prebuilt **unsigned** Native AOT winui-search.exe. We can't compare
hashes against a CI rebuild reliably"* — substituting a smoke test and a size-delta tolerance. So the shipped
binary is unsigned and not reproducibly tied to its source.

**F3 (positive) — UAC handling. CONFIRMED.** `winui-setup/SKILL.md:107`: *"**Do not just trigger UAC out of
nowhere — ask the user first**"*, with a scripted consent prompt and a decline path.

**F4 — THE FINDING THAT CHANGES THE RECOMMENDATION (missed entirely at README level).**
`winui-search.exe` — invoked by the *top-rated* skill — performs undisclosed network egress.
`src/tools/winui-search/Program.cs:17-19`: hot-path commands *"DO opportunistically spawn a background
'update --background' child if the cache is >7 days old."* `BackgroundUpdater.cs:10-12` confirms the
detachment is deliberate — it *"outlives"* the parent — and line 17 says *"skip silently."* It fetches from
five URLs across `microsoft/WinUI-Gallery` and `CommunityToolkit/Windows`, **all tracking `main`**, then
hands that XAML/C# to the agent as guidance it turns into code in our project.

This is fetch-and-follow-remote-content at runtime, inside an ADOPT-rated skill. **It defeats the original
mitigation:** vendoring win-dev-skills at a pinned commit pins *this* repo — it does not pin what the
vendored executable downloads at runtime from two *other* repositories' moving branches. The only opt-out is
the environment variable `WINUI_SEARCH_NO_BACKGROUND=1`, which **appears nowhere in the skill documentation**;
an adopter reading the skill cannot learn the background fetch exists. It also writes a cache to
`%LOCALAPPDATA%\winui-search\cache\`.

**F5 — `winui-packaging` instructs a Trusted Root install with a known password (missed).** `SKILL.md:35-37`
directs `winapp cert install ./devcert.pfx`, described as *"Adds cert to machine Trusted Root store. Persists
across reboots"*, and `:58` documents the **default PFX password as `password`**. A code-signing certificate
in the machine Trusted Root CA store with a publicly-known password is a larger system-state change than
enabling Developer Mode — which the original verdict rejected while merely skipping this. **The original
severity ranking was inverted.**

**F6 — an explicit anti-pinning instruction (missed).** `winui-dev-workflow/SKILL.md:23-25`: *"**Never**
specify `--version` — omitting it gets the latest stable."* Compounds F1.

**F7 — `BuildAndRun.ps1` writes into the adopter's project (missed).** It drops a `Directory.Build.props`
into the project directory wiring in an `<Analyzer>` — and Roslyn analyzers execute arbitrary code inside the
compiler process on every build. *Credit where due:* it refuses to overwrite an existing file and removes its
own file in a `finally` block.

**F8 — the ADOPT/SKIP split does not compose (missed).** Adopting exactly the three originally-named skills
yields two that cannot run: `winui-code-review`'s analyzer ships in a skipped skill, and `winui-ui-testing`
depends on a CLI only the rejected setup skill installs.

**Re-verified negatives:** no telemetry, analytics, or crash reporting anywhere; **no MCP server
registration** (confirmed from all six manifests, not the README — `index.js` is a genuine no-op with
`register() {}`); no auto-approve, `Set-ExecutionPolicy`, Defender exclusions, or confirmation suppression
across any skill. Both PowerShell scripts are maintenance-only and never run on an adopter's machine.

**One negative REFUTED as stated:** the original claim of "no Microsoft-account sign-in requirement" is not
supported. `.agents/plugins/marketplace.json` declares `"policy": { "authentication": "ON_INSTALL" }`. There
is no sign-in code anywhere in the tree, so what a host actually does with that field is **unresolved** —
recorded as an open question, not as a confirmed sign-in requirement.

### 4.4 Recommended adoption shape (revised)

1. **Adopt text only, at a pinned commit:** `winui-design`, `winui-code-review`, `winui-wpf-migration` as
   reference material. Read every line first — these are agent instructions, not a library.
2. **Strip every binary.** Do not ship or run `winui-search.exe` or the analyzer DLL. With the exe removed,
   `winui-design` degrades gracefully to static guidance — it carries 766 KB of embedded fallback data and
   remains usable fully offline, which is the part worth having.
3. **If the search tool is ever wanted:** build from in-repo source and run with
   `WINUI_SEARCH_NO_BACKGROUND=1`, accepting that refreshed results still originate from third-party `main`.
   Default answer is no.
4. **Never** use `claude plugin marketplace add` for this repo.
5. **Accept that the automation value is not reachable.** `winui-ui-testing` — the highest-value item — needs
   the `winapp` CLI, which needs the rejected `winui-setup`. Under a fail-closed posture, what we can take is
   reference text, not working automation. That is a real reduction from the original recommendation and
   should not be papered over.
6. Re-review deliberately on any version bump. Updates are a decision, not a default.

### 4.5 What the two-pass audit demonstrates

The first pass read the README and produced a confident, wrong recommendation: it rated as *highest value* a
skill whose shipped executable performs silent, detached, undisclosed network fetches from moving branches —
and proposed a mitigation (pin the commit) that does not address that behavior at all. Nothing in the README
was false; it simply did not describe the artifact layer.

This is the project's own **"mocks lie — drive the real objects"** lesson in a new setting: *documentation
about code is not evidence about code.* An audit of a repository that ships executables is not complete until
the executables' source, the manifests, and the scripts have been read. Worth a lesson entry.

---

## 5. Where these decisions are recorded

- **#611** — comment added: FHE evaluated as a fourth candidate mitigation and closed as structurally
  inapplicable. Fills the gap left by §4 of the June feasibility study.
- **New ticket** — MXC watchlist, with the two named re-check triggers.
- **New ticket** — win-dev-skills vendored adoption (3 skills, pinned commit, binaries dropped).

## 5a. Independent verification pass (2026-07-20)

The conclusions above were filed first and verified second, by a separate agent reading the tree
independently. Outcome: **two claims confirmed, one materially corrected.**

| Claim checked | Result |
|---|---|
| No prior FHE consideration anywhere in the repo | **CONFIRMED.** Full sweep of code, docs, ADRs, journal + archives, LESSONS and research notes for `homomorphic\|FHE\|CKKS\|BFV\|OpenFHE\|TFHE\|lattigo\|tenseal\|zama\|palisade\|HElib\|Microsoft SEAL\|encrypted inference\|encrypted search` found zero real hits. ("SEAL" in-tree = TPM sealing; "Concrete" = the English adjective.) Nothing was duplicated. |
| #611 study §4 quote and its meaning | **CONFIRMED** verbatim at `611-live-memory-feasibility.md:325`. FHE is indeed never named. |
| Host-mode live / VM dormant | **CORRECTED** — see §3.3. Host-mode confirmed; "dormant" was wrong. The guest oracle is live on-demand infrastructure. |
| vsock/AF_HYPERV blast radius "high" | **EMPHASIS CORRECTED** — see below. |
| DECISION_REGISTER contradictions | **NONE FOUND.** Two rows *strengthen* the FHE conclusion (ADR-007 hardware absence; ADR-028 Am.1 precedent), now incorporated into §1.6. |

**On blast radius, my emphasis was wrong even though the direction was right.** Raw coupled surface is
~4,500–5,000 non-test lines, which sounds pervasive. The composition tells a different story: the genuinely
substrate-coupled core is only ~150 lines in `shared/ipc/vsock.py` (42 `AF_HYPERV` refs) plus ~100 in
`services/ui_gateway/src/transport.py` (19 refs). The protocol/channel layer — ~3,400 lines across
`protocol.py`, `parse_channel.py`, `oracle_channel.py`, `resolve_channel.py` — is substrate-agnostic and two
of those files contain **zero** references. A further ~3,085 lines are a Python-version workaround (the venv
is 3.11.9; `socket.AF_HYPERV` arrived in 3.12), which will need replacing on a runtime bump regardless of
substrate. `shared/security/egress_guard.py` bakes AF_HYPERV into the deny-by-default allowlist as an
always-permitted family, so a substrate change does touch the egress spine.

Honest framing: **wide surface area, narrow actual seam** — moderate and cleanly layered, not pervasive.
This does not change the recommendation (§3.2's disqualifier is independent of cost), but "high blast radius"
overstated it and is corrected here.

**One caution for future readers:** `Use Cases_FINAL.md` §5 still carries extensive Pluton/SGX/TDX sealing
language. That is the superseded original vision, overridden by ADR-018 and the 2026-07-15 decision. It is
not current posture and must not be cited as such.

## 5b. Adversarial verification of the encryption conclusion

The FHE conclusion was filed first and attacked second, by an agent tasked specifically to break it.

**Result: the structural argument (§1.3) could not be broken.** Every alternative construction failed (see
§1.3). The primary literature actively corroborates it, because essentially every FHE transformer paper
defines its threat model as a two-party client/server split and derives its security claim from that split.
The "even free, it buys nothing" formulation stands as written.

**The practical argument survived but four specifics were wrong** — all corrected in §1.4, and all wrong in
the *conservative* direction. The real numbers are worse for FHE than what was originally filed.

**A verification-pass self-correction worth recording, because it is the same failure mode twice in one
session.** The verifier's own draft recommended Intel TME-MK (memory encryption) as an available alternative
tool, citing the **Core Ultra 200V datasheet**, which lists it at the SKU-family level. Checking ADR-007
instead showed it **measured absent on this actual machine**. The datasheet described the product family;
the measurement described the laptop. Measurement governs.

That is the identical shape as the win-dev-skills failure in §4.5 — *documentation about a thing is not
evidence about the thing* — arrived at independently, on a different question, within the same hour. Once is
an error; twice in one session on unrelated subject matter is a pattern worth a lesson entry. It is also why
the AVX-512 claim in §1.4 is explicitly marked provisional pending a datasheet check rather than asserted.

**Claims the verification could not settle, recorded rather than buried:** THOR's explicit threat-model
section could not be retrieved (the preprint PDF returned 403); one Cachemir GPU figure has an internal
ambiguity, so the conservative reading (<100 s/token) is used; and there is **no Matthew Green source** on
FHE key-colocation — nothing should be attributed to them.

## 5c. The finding that outlasts all four answers: documentation is not evidence

The same failure mode occurred **three times, independently, on three unrelated questions, within one
session** — twice by verifiers who had been explicitly warned about it.

| # | Question | The document said | The source said | Cost |
|---|---|---|---|---|
| 1 | win-dev-skills | README described a design-guidance skill | `Program.cs` / `BackgroundUpdater.cs`: silently spawns a **detached process fetching from third-party `main` branches** | **Top recommendation refuted; the proposed mitigation did not address the actual risk** |
| 2 | Homomorphic encryption | Intel Core Ultra 200V **datasheet** lists TME-MK at family level | ADR-007 **on-chip measurement**: TME/MKTME = false on this unit | A false alternative was nearly recommended |
| 3 | MXC | `docs/hyperlight-integration-plan.md`: *"Network: None"*, *"No network stack in guest"* | `src/backends/hyperlight/common/src/lib.rs`: *"network policies ARE supported"* — host-proxied sockets | A conclusion about the single most important property was reversed mid-analysis |

**The generalization:** *documentation about a thing is not evidence about the thing.* Vendor READMEs,
datasheets, and integration plans describe **intent, or a product family, or a past state**. Source code,
manifests, shipped binaries, and on-chip measurements describe **what is actually true here, now**. Where
they disagree, the artifact wins — and in all three cases above they disagreed in the direction that made
the safer-looking option actually riskier.

This is the project's existing **"mocks lie — drive the real objects through real entry points"** lesson,
generalized from *our* code to *external* artifacts under evaluation. The existing lesson protects us when we
test our own system. Nothing yet protects us when we evaluate someone else's, which is precisely what all
four of this session's questions required.

**Doctrine trigger.** Project doctrine holds that a third instance of a recurring lesson must ship a
**structural control** in the same change, not merely another lesson entry. Three independent instances in
one session meets that bar. A candidate control, proposed rather than assumed: **any evaluation that
recommends adopting third-party code must record which artifacts were actually read** — source, manifests,
binaries — and a recommendation resting on documentation alone is incomplete by definition, in the same way
an unrecorded performance measurement is an incomplete task. Filed for LA triage rather than self-approved,
since it changes how evaluations are done rather than fixing a defect.

*(A related structural finding: MXC has **zero** vsock / AF_HYPERV / Hyper-V-socket support anywhere in its
1,215-file tree. It could therefore only ever be an *additional* isolation mechanism alongside our existing
transport — never a substrate swap. This independently confirms §3.3's corrected conclusion, by a different
route than the GPU-reachability argument.)*

## 6. Honest limits of this analysis

- **Two-pass process.** Every conclusion here was filed first and adversarially verified second. That is why
  the document contains visible corrections rather than a clean narrative: §3.3 (VM not dormant), §4.1–4.5
  (top skill recommendation refuted), §1.4 (performance figures corrected, open item closed). The
  corrections are the evidence the process worked, not noise to be tidied away.
- **The FHE conclusion does not depend on any number in §1.4.** It rests entirely on the structural argument
  in §1.3, which no performance improvement can change. The performance section is corroboration, not
  foundation.
- **The MXC assessment (§3) has now been verified** and survives. The single-sentence disqualifier was read
  correctly (blanket scope, verified against the full warning block), but three corrections were applied: the
  backend tiers are not monolithic, "watchlist only" understated an active GA program, and **the original
  re-check trigger was unsafe** — Microsoft's own Build-2026 marketing arguably already satisfied half of it,
  so it has been re-keyed to repository artifacts that marketing cannot trip.
- **Three of four original research subagents failed on account usage credits** partway through, and the
  first pass was completed directly at less depth than planned. That is what produced the two overturned
  findings. The verification pass was run after capacity was restored.
- **One claim is provisional:** Lunar Lake's AVX-512 status (§1.4), pending a datasheet confirmation.

## Sources

- [Fully Homomorphic Encryption in 2026: What Ships and What Is Still Hype](https://wavect.io/blog/fully-homomorphic-encryption-practical-2026/)
- [A Survey on Private Transformer Inference](https://arxiv.org/pdf/2412.08145)
- [Private LLM Inference with Homomorphic Encryption (EDBT 2026)](https://openproceedings.org/2026/conf/edbt/paper-T1.pdf)
- [Scaling Long-Sequence Homomorphic Encrypted Transformer Inference](https://arxiv.org/html/2604.03425)
- [FHE on Llama 3 for privacy-preserving LLM inference](https://arxiv.org/abs/2604.12168) (the flagged contrary claim)
- [microsoft/mxc](https://github.com/microsoft/mxc) — README, GitHub API metadata
- [microsoft/win-dev-skills](https://github.com/microsoft/win-dev-skills) — README, contents API

On disk: `docs/handoffs/611-live-memory-feasibility.md` · `docs/adrs/ADR-041-Host-Mode-Action-Authorization-Boundary.md` ·
`docs/security/SECURITY_ROADMAP_air_gap_removal.md` §8.1 · `services/ui_winui/BlarAI.Desktop.csproj` · Vikunja #611
