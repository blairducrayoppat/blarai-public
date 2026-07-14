# The Coordinator — Operator's Guide (Plain Language)

**Audience:** the User-Operator / Lead Architect, and eventually any non-technical operator. No programming knowledge assumed.
**Companions:** `coordinator-program-plan-2026-07.md` (the technical design), `coordinator-self-governance-research-2026-07.md` (the research + review evidence).
**Date:** 2026-07-11. Reflects the post-adversarial-review design (all 13 findings folded in). Nothing described here is built yet.

---

## 0. Meet the Coordinator — what changes for you

Today you are the project manager: you remember which projects have pending work, you type `/dispatch`, you check overnight results, you keep Vikunja honest, you notice when nothing is running. The Coordinator takes that job. You stop driving the work and start directing it.

**The entire interface is three things in the chat window you already use:**

1. **`/coord status`** — the state of the work, on demand: per-project board (what's running / Ready / Backlog, with ages and deadlines), flow numbers for the last two weeks, and how many proposals await you.
2. **The digest** — after its check-up cycles, a few lines on your screen: what finished (with evidence), what's next in line, what isn't Ready and why, whether anything stalled. Your standup, without the meeting.
3. **The briefing** — the only place it asks anything: numbered proposals, each with its lane (WORKSPACE = executable coding work; SELF-ADVISORY = a note for the human dev channel that BlarAI cannot act on), a plain-language outcome ("if approved: overnight run on repo X; result lands on ticket #212"), and `/coord approve N` / `/coord deny N`. Deny is always safe.

**A day with it:** morning — digest waiting, approve over coffee (~2 min; tickets already closed themselves, the board already matches reality). During the day — silence, unless a genuine alarm fires (wedged run, deadline at risk, or the quiet-queue tripwire: approved work + idle machine + nothing pulling). Evening — a briefing stocks the overnight queue before the 23:00 window (~1 min). Away — it drops to emergencies-only and hands you one catch-up brief on return. Monthly — your retrospective gets real flow numbers from the briefing ledger.

**It replaces nothing:** `/dispatch` still works manually; the Vikunja webUI is still yours; the overnight window, battery, and swap driver are untouched (it watches them); your chat assistant is unchanged. It is a colleague behind the same window, not a new app.

**The one-sentence version: you currently check on the machine; after this, the machine checks in with you.**

## 1. What this is, in one picture

Today BlarAI is a skilled worker: you hand it a coding job, it plans, you approve, it builds, it reports. The Coordinator program gives it a second job: **project manager**. It will watch running work, keep the ticket board honest, notice when the pipeline is empty, and come to you with "here's what I suggest we do next" — the way a good chief of staff runs your projects while you make the decisions.

The danger of giving a system that role is obvious once you see it: a project manager who can also assign work to a construction crew could, in principle, assign the crew to remodel the manager's own office — change its own rules, its own instructions, its own code. The single most important idea in this design is the fence that makes that impossible.

## 2. The new concepts, one at a time

**The governed core vs. the workspace.** Everything is sorted into two piles. The *governed core* is everything that defines what BlarAI **is**: its program code, its settings, its system instructions and policies, its AI models and the signatures that prove they're genuine, its rule documents — and, subtly, its memory tiers that feed into future instructions, plus the grading machinery that judges whether work passed. BlarAI has **zero ability to change anything in this pile, ever, at any trust level**. The *workspace* is everything it manages: your coding projects and the ticket board. Changes to the core travel exactly one road — you plus human-supervised development sessions. Think of the core as BlarAI's constitution: it lives under glass, and BlarAI doesn't own a key to the case.

**"Model proposes, deterministic ruler disposes."** Every idea the AI has passes through plain, non-AI computer code — a "ruler" — that checks it against hard rules before it goes anywhere. The AI is creative and fallible; the ruler is boring and exact. The ruler cannot be sweet-talked, because it doesn't read language — it checks facts (is this target inside the allowed projects folder? is this proposal too big?). This pattern already runs your dispatch system today; the Coordinator reuses it everywhere.

**The proposal queue and the briefing.** The Coordinator never *does* anything on its own. Every action it wants to take becomes a **proposal** in a queue. Periodically you get a **briefing**: a short, bounded list of proposals, each rendered as a plain-language outcome — "this will dispatch the recipe-app project to fix the login bug" — and you approve or deny each one. Approval is per-item for anything impactful. Denying is always safe: nothing breaks when you say no.

**The two lanes.** Proposals come in two colors. *Workspace* proposals (lane a) are about your projects — approve one and BlarAI can execute it through its own dispatch system. *Self-advisory* proposals (lane b) are BlarAI's observations about **itself** ("my ticket #612 looks stalled," "consider a control for X"). Approving a lane-b item only creates a specially-labeled advisory ticket that **humans** read and act on. BlarAI's own machinery refuses to execute lane-b work even if you approved it — the refusal is built into the pipes, not into politeness.

**The heartbeat.** Today BlarAI only acts when spoken to. The heartbeat is a timer that wakes a small check-up routine: read the state of running jobs, harvest finished results, count the queue, spot stalls. Almost all of this is plain code reading files — the AI model is only woken at the end, to *draft* proposals or a digest, never to act. If a big coding job has the machine's memory (the 14B "brain" is set aside during those), the cycle runs its plain-code checks and skips the drafting until the brain is back. One digest per cycle, maximum, and it goes to your screen — never spam into the ticket system.

**The quiet-queue tripwire.** Your own rule — "a quiet development queue is a broken queue" — becomes an alarm: approved, unblocked work exists AND nothing is running → alert. It's taught the household rhythms (overnight windows, active swaps, a grace period) so it doesn't cry wolf and train you to ignore it.

**The autonomy ladder.** Everything starts as propose-only. Over time, individual *tiny* action classes can be promoted to automatic — for example "re-try a failed job exactly once." Each promotion is a formal ceremony: you, a written decision record, a specific safety re-analysis, and its own on/off switch, default off. You can demote any class back instantly. Big things — creating tickets, changing priorities, anything touching scope — are marked *never automatic*.

**Untrusted content and provenance.** Everything the Coordinator reads — ticket text, job reports, project files — is treated as **untrusted**: possibly containing hostile instructions planted by a malicious webpage, dependency, or file ("prompt injection"). The design's stance: such text may influence what a proposal *says*, but can never choose what a proposal *targets* (targets are re-derived by plain code from verified fields), and the worst it can ever achieve is a weird suggestion sitting in your briefing, which you read verbatim and deny. Everything BlarAI itself writes is stamped with a tamper-resistant "authored by BlarAI" label so no one — including BlarAI later — mistakes its own notes for your orders.

**Small-model discipline.** BlarAI's brain is a 14-billion-parameter model — capable, but not a frontier genius. The design never asks it big open questions ("assess all my projects and decide priorities"). It asks many tiny ones ("is this one ticket stalled: yes/no?") and lets plain code assemble the answers. Crucially, **safety never depends on the model being smart** — a dumber model produces worse *suggestions*, never worse *actions*.

**Capability contracts (dense and MoE models).** BlarAI runs two shapes of AI model — a "dense" one (the 14B assistant) and a "mixture-of-experts" one (the 30B coder), and models will be swapped over the years. Each *role* carries a written contract of what a model must prove on measurement (output format discipline, tool-call behavior, benchmark baselines) before it can hold that role. Swapping a model is a paperwork-plus-testing event, not a redesign.

**The three rings.** A dispatched coder is checked at three moments: *before* (the ruler refuses forbidden targets at proposal time), *during* (a plain-code doorman answers the coder harness's real-time permission requests and cancels the run cleanly if it reaches for the core), and *after* (the existing verify-gate and merge review). No single ring is trusted alone; the coder harness's own permission settings are treated as a nice-to-have extra, because that product has documented enforcement bugs on Windows.

## 2b. How it actually manages projects — the method

The Coordinator manages via **Kanban**, an agile method built on continuous flow rather than fixed sprints. Why not Scrum? Scrum's sprints, standups, and planning meetings exist to synchronize a *team of humans*; you don't have one — you have one human and AI executors, which is a continuous-flow shop. Kanban was chosen for a second, deeper reason: all of its machinery is *arithmetic*, so plain code can run it and the AI stays out of the control loop.

What that looks like in Vikunja, concretely:

- **Every project gets a board** with columns: `Backlog → Ready → In Progress → In Review/Verify → Done`. Cards move only on real events — a dispatch starting, a verified merge — never because the AI "thinks" something is done.
- **"Ready" is earned, not declared.** A checklist in code (the *Definition of Ready*) — acceptance criteria written, target valid, nothing blocking it — gates the column. The Coordinator proposes refinements to get Backlog items over that bar. *Done* is the existing rule: verified green + merged, nothing else.
- **Work-in-progress limits.** Each column has a cap, enforced by code. The deepest one is physics: your machine runs one coding dispatch at a time. WIP limits are what make "keep the queue full" mean *flowing*, not *flooded* — too many started things is how everything becomes late at once.
- **Four classes of service** (labels on tickets) decide pull order, by code: **Expedite** (emergencies, jump the queue, one at a time), **Fixed-date** (has a deadline, pulled early enough to make it), **Standard** (first-in-first-out — oldest ready item goes next), **Intangible** (maintenance/docs, pulled when nothing else waits). The AI never picks what runs next; it can only *propose* adding or reclassifying work, which you approve.
- **Flow metrics instead of vibes.** Each heartbeat computes cycle time (how long items take), throughput (how many finish), and work-item age. "Stalled" stops being a feeling — it's an item whose age is abnormal for its class. Your digest reports these numbers.
- **The ticket is the home for everything about that work** — proposals, results, decisions, evidence all live as comments on the card they concern. Anyone (human or AI) picking up a card gets its whole story.
- **The cadences:** the digest is your standup equivalent; the briefing is the planning/replenishment meeting; the monthly retrospective you already run absorbs the flow trends. No sprints, no story points.

## 2c. Is the Coordinator a separate agent?

Yes as a **role**, no as a **program or model**. BlarAI already runs two roles on one shared AI model: the Policy Agent (the guardian) and the Assistant Orchestrator (your assistant) — same brain, different job descriptions, different permissions. The Coordinator becomes the **third role on that same shared model**: its own job description (system prompt), its own much smaller toolbox (read tickets, read state, stage proposals — deliberately *without* the assistant's preference/image/chat tools), and its own identity in the logs so every coordinator action is attributable. A separate model is impossible anyway (your 31 GB memory ceiling) and unnecessary — the research on multi-agent systems supports exactly this split-by-role-on-shared-weights pattern. You'll still talk to your assistant as always; `/coord` commands are just routed to the Coordinator role behind the scenes.

## 2d. How it earns your trust before going live — shadow mode

The Coordinator does not get to talk to you just because it was built. First it runs in **shadow mode**: full cycles, real monitoring, real drafting — but every proposal goes into a private journal instead of your briefing. That journal gets graded (by you at a review sitting, and by an automated test suite over fixture boards with known right answers). Only when its measured suggestion quality clears a set bar over enough cycles does a ceremony unlock live briefings. The same test suite re-runs whenever a model is swapped — a new brain re-earns the coordinator job on measurement, never on reputation. Think of it as a probation period with a written performance review, and it never ends: the tests stay in the standing gate forever.

Three more everyday behaviors worth knowing:

- **It knows the difference between "no work" and "can't see the work."** If the ticket server is down, the Coordinator says "PM substrate unreachable" — it will never report an empty, healthy board it couldn't actually read, and the quiet-queue alarm holds its tongue rather than false-report. A dead board must never look like a finished backlog.
- **It won't nag.** The same detected problem produces ONE proposal, no matter how many cycles observe it; proposals you haven't answered quietly expire after about a week instead of piling up.
- **It respects your absence.** If you're away (a switch, or it notices unanswered briefings), only genuine emergencies surface; everything else accumulates into a single catch-up brief for your return, and nothing expires while you're gone.

## 3. Strengths — why this design deserves trust

1. **It's mostly proven parts, recombined.** The Vikunja bridge, the approve-before-execute flow, the ruler pattern, the swap driver, the fail-closed idiom — all already live and tested in your system. The genuinely new organs are only two: the heartbeat and the proposal queue.
2. **Safety is structural, not behavioral.** Nothing relies on the AI choosing to be good or on you catching every mistake. The fence is in plain code, verified at boot, locked by regression tests.
3. **It fails soft toward you and closed toward risk.** If the Coordinator breaks, your assistant keeps working and the ticket system just gets quieter — annoying, not dangerous. Anything ambiguous is refused.
4. **Everything ships asleep.** Every phase arrives behind an off-switch, woken only by a deliberate ceremony with you present. There is no big-bang moment.
5. **It has already survived an independent attack.** A separate, adversarial review (web-research-armed) tried to break the design on paper, found 13 real weaknesses, and every one is now folded in — including one that would have corrupted your decision register.
6. **Honest claims.** The design states its own current limit plainly: until the "signed policy" control ships, this is *safe under expert operation* — not yet *safe to hand to strangers*.

## 4. Weaknesses and risks — honestly, with mitigations

| # | Risk (plain language) | How the design answers it | What honestly remains |
|---|---|---|---|
| 1 | **You are the single approver.** Tired humans rubber-stamp. | Bounded batch sizes; per-item confirmation for impactful classes; proposals rendered as plain-language outcomes; deny-is-always-safe. | Real. Approval fatigue can't be engineered away with one approver. Your discipline: never approve what you don't understand. |
| 2 | **The fence's own code lives on the same machine.** Something that got code-write access could, in theory, edit the ruler. | Control 6: a boot-time canary probes the fence every start and refuses to run if it finds a hole. Control 7: the rule files get cryptographic signatures checked at boot (extending the machinery that already protects the AI models). | Control 7 is the linchpin for the give-it-to-others future; until it ships, expert-operation only. Stated on the record. |
| 3 | **Hostile instructions hidden in what it reads** (tickets, job reports, project files). | Content can shape proposal *wording* only; targets come from verified fields via plain code; you read proposals verbatim; provenance stamps are structural, not text. | The weird suggestion still lands in your briefing. You are the last filter for *content*; the system is the filter for *action*. |
| 4 | **The 14B brain misjudges** — misses a stall, proposes silly work. | Tiny single-decision questions; deterministic evidence first; every judgment is only ever a proposal. | Suggestion *quality* is unproven until measured. Worst case is noise in briefings, never wrong actions. |
| 5 | **The heartbeat is BlarAI's first autonomous wake** — new territory. | Deterministic-first cycles; propose-only; crash-safe (reconciles on boot like the swap driver); swap-aware (never fights the coder for memory); ships dormant; go-live is a ceremony. | First-of-its-kind surfaces always harbor surprises; expect tuning in the first weeks live. |
| 6 | **Alert spam retrains you to ignore alerts** (this burned the project once — "Fleet Reports"). | Outcomes-only ticket discipline untouched; one digest per cycle, screen-only; tripwire suppressed during swaps/overnight/grace. | Thresholds will need real-world tuning. Tell the dev channel the moment an alert feels ignorable. |
| 7 | **A coding job could touch BlarAI's own files** via a renamed copy or link trick. | Identity-based checking: paths are resolved to their true physical location before the fence decides — a renamed clone or junction doesn't fool it. Enforced on both sides (BlarAI and the fleet). Evasion tricks get their own regression tests. | Path-resolution edge cases on Windows are subtle; the test suite carries that burden. |
| 8 | **More moving parts.** A coordinator, a queue, a heartbeat, three rings — all must be kept green. | Same gate discipline as everything else; each phase independently shippable and reversible. | Genuine long-term maintenance cost. Accepted deliberately — coordination was judged worth an organ, not a hack. |
| 9 | **Unmeasured technical assumptions** (grammar-constrained output on the coder's server; the ACP doorman in practice; model-call latency budget per cycle). | Explicitly flagged "measure, don't assume" in the plan; homes in tickets. | Until measured, these are scheduled unknowns. |

## 5. How you operate it (day-to-day, as phases land)

**Phase C1 — the window.** You get `/coord status`: one screen showing running work, queue depth, stalls, and open tickets. Read-only; use it as often as you like. Nothing to approve yet.

**Phase C2 — housekeeping.** Tickets start staying honest on their own: stalled runs get flagged, partial work gets dated "CURRENT STATE" notes, finished work closes with evidence. You'll notice the board matching reality without your intervention. Parked jobs produce *proposals* to retry — which wait for you.

**Phase C3 — the heartbeat.** Turned on by a ceremony with you present. From then on: a periodic digest on your screen (never in tickets) and a proposal queue. Your verbs: **`/coord approve <id>`** and deny. Your one alarm: the quiet-queue tripwire — treat it like a smoke detector; if it fires falsely twice, that's a defect to report, not a thing to tolerate.

**Phase C4 — the briefing.** Periodically the Coordinator presents next-work suggestions in two clearly marked lanes. Your reading protocol, every item: (1) which lane? (2) does the outcome sentence make sense — "this will dispatch X to do Y"? (3) approve or deny. **Rules: never approve an item you don't understand — an unclear proposal is itself a defect; say so. Lane-b items only create advisory tickets for the human dev channel — you or a dev session must eventually read and close those; the Coordinator never can.**

**Phase C5 — promotions.** Occasionally you'll be asked to promote one tiny action class to automatic. Each ask comes as a ceremony: what the class is, its blast radius, its bound (e.g., "at most once per job"), the safety re-analysis, its own off switch. You can decline, and you can demote any time with one config change. When in doubt: leave it propose-only. Propose-only is never wrong, just slower.

**Your non-delegable duties** (the things only you can do): approve/deny briefings; attend go-live and promotion ceremonies; triage ticket priorities; read lane-b advisory tickets; and say out loud when something feels noisy, confusing, or wrong — operator discomfort is a first-class defect signal in this design.

**What you never need to do:** watch logs, chase stalls, remember to close tickets, check whether the queue is full, or verify that BlarAI hasn't touched its own machinery — the last one is proven mechanically at every boot.

## 6. If something looks wrong

- **A proposal looks strange or manipulative** → deny it, and mention it. A denied proposal costs nothing. A strange one is evidence somebody's content is trying to steer the system — valuable to know.
- **The Coordinator goes quiet while work is pending** → that's the tripwire's job; if the tripwire ALSO stayed quiet, report it — a silent coordinator plus a full queue is the exact failure the program exists to prevent.
- **An alert fires that makes no sense** → report it as a false alarm; suppression windows get tuned. Never train yourself to ignore it.
- **You suspect the fence itself** → restart BlarAI. The boot canary re-proves the boundary on every start and refuses to run if it can't. A BlarAI that starts is a BlarAI whose fence held.

## 7. Where to read more

- Technical design: `docs/research/coordinator-program-plan-2026-07.md`
- Research + adversarial-review evidence, with citations: `docs/research/coordinator-self-governance-research-2026-07.md`
- Tickets: Vikunja #841 (epic), #842 (doctrine/ADR-039), #848 (the fence), #843–#847 (phases C1–C5)
- The decision record: #841 comments c.1798 (the boundary decision) and c.1802 (the review disposition)
