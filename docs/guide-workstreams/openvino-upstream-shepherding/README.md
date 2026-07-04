# OpenVINO Upstream Shepherding (continuous workstream)

## 1. Charter

Provide a continuous Guide-coordinated layer that helps the LA understand,
monitor, and engage with their open OpenVINO upstream contributions —
without becoming the deep-code-authoring vehicle for any single fix.

The workstream's reason for existing: the LA has a non-trivial open
upstream portfolio (PRs in `openvino` and `npu_compiler` repos, plus
issues filed and watched) that benefits from disciplined shepherding —
periodic state checks via the GitHub REST API, careful follow-up comment
drafting, retest execution when upstream versions change, and decision
support on cadence and escalation timing.

Quoting the LA's framing at workstream founding (2026-05-12):
*"An agent (or agents) helps me understand what is happening on the
GitHub tickets, do any related testing, create related solutions to
problems, and post at professional-level quality on GitHub."*

This is a companion to — not a replacement for — focused deep-work
workstreams like
[`openvino-contribution-npu-int8-guard`](../openvino-contribution-npu-int8-guard/).
That kind of workstream owns one issue's entire contribution arc
(engage → recon → repro → fix → PR → review). This shepherding
workstream is the lighter coordination layer that runs across the LA's
whole upstream portfolio in parallel.

## 2. Scope boundary

### In scope

- **State monitoring** of the LA's open PRs and issues via the GitHub
  REST API (per `feedback_github_comments_use_api_not_webfetch` —
  always API, never HTML scraping for comment verification).
- **Drafting follow-up comments and PR responses** at
  professional-grade quality (mature-not-minimal). Each draft goes to
  disk for LA review before posting.
- **Coordinating retests** when an upstream version bump may have
  changed the bug status (e.g., the OV 2026.0.0 → 2026.1.0 retest done
  for issue #35641).
- **Cadence management**: deciding when "polite follow-up" is
  appropriate vs. "leave alone" vs. "escalate via Intel DevHub
  Discord / GitHub Discussions."
- **Decision support** for the LA on what action (if any) each open
  item needs.
- **Light technical research** to support comment drafting — e.g.,
  understanding the npu_compiler pipeline, checking related PRs for
  patterns, looking up GitHub permission semantics, etc.

### Out of scope (handle elsewhere)

- **Large code contributions.** When an item escalates into "we need
  to author a non-trivial fix," it spins out into its own deep-work
  workstream (the `openvino-contribution-npu-int8-guard` template).
- **Posting comments directly to GitHub.** Drafts go to disk; the LA
  reviews and posts via webUI. Same posting discipline as the
  `openvino-contribution-npu-int8-guard` workstream.
- **Modifying the BlarAI runtime.** No changes to BlarAI runtime venv,
  production paths, or `active_tasks.yaml` from this workstream.
- **Engaging on PRs / issues the LA didn't author.** Watching, yes;
  commenting from the LA's account, no.

## 3. Owners

- **Lead Architect**: Blair (`mr.blair.do@gmail.com` / GitHub `blairducrayoppat`)
- **Guide instance**: Guide-#11 (current). Successor Guide instances inherit.
- **Vikunja parent task**: project 3 (`BlarAI Core Development`), task **#466**

## 4. Cycle pattern (instead of fixed phases)

This is a continuous workstream, so there is no traditional Phase 1 / Phase 2
plan. Instead, work happens in **shepherding cycles**.

**Cadence (decided 2026-05-12 by LA): LA-triggered.** Cycles start
only when the LA flags that an item needs attention. The workstream
does NOT run on an auto-recurring schedule — no `ScheduleWakeup`,
no `CronCreate`. Guide stays quiet between LA pings.

The LA may ping for any reason — feeling that something is stale,
noticing a reviewer comment in their GitHub notifications, an
upstream release shipping, a related issue being filed, or a "let's
just check in on everything." Guide responds with a state survey
+ recommended actions, same pattern as cycle 1.

Each cycle produces a **dated directory** under the workstream:

```
openvino-upstream-shepherding/
├── README.md (this charter)
├── STATUS.md (chronological — one entry per cycle)
└── YYYY-MM-DD-cycleN-<short-slug>/
    ├── pr-state-survey.md  (what we observed)
    ├── <draft-files>.md    (any paste-ready follow-ups produced)
    └── decisions.md        (what the LA decided this cycle)
```

The dated directory captures everything produced in that cycle, in one
place. STATUS.md gets an append-only entry summarizing each cycle.

For agent involvement:
- **Guide** runs the cycle: surveys state, drafts, recommends.
- **EA** is spawned only when a cycle requires deep work that doesn't
  fit a Guide-direct session — e.g., a retest in an isolated venv
  (already established pattern from the `-int8-guard` workstream's
  Phase 1.5 retest).

## 5. Currently tracked items

Each item below has a dedicated Vikunja "Shepherd:" task in project 3
where decisions live (per BlarAI memory
`feedback_vikunja_ticket_decisions`). The shepherding workstream's
parent task (#466) tracks the overall workstream; individual decisions
live on the per-PR tickets.

| Item | Repo | Type | Vikunja | Last reviewer action | Status as of 2026-05-12 |
|---|---|---|---|---|---|
| **#34651** | openvino | PR | (TBD ticket created in this cycle) | None — no formal reviews | Stalled. No engagement. Last LA touch 2026-04-25 (rebase). |
| **#265** | npu_compiler | PR | (TBD ticket created in this cycle) | `andrey-golubev` CHANGES_REQUESTED 2026-04-17 (read-only-permissions). LA replied 2026-04-17 asking for IR-dumping guidance. | Waiting on andrey-golubev's reply. |
| **#266** | npu_compiler | PR | (TBD ticket created in this cycle) | `andrey-golubev` CHANGES_REQUESTED 2026-04-17 (same content as #265); `DariaMityagina` (CONTRIBUTOR) asked for LIT test 2026-04-17. LA added LIT test + asked IR-dumping guidance 2026-04-17. | Waiting on andrey-golubev's reply; Daria has not re-engaged. |
| **#35641** | openvino | issue | #443 (own workstream) | Cross-workstream; deep work owned by `openvino-contribution-npu-int8-guard`. Shepherd only when threads cross. |

Other issues the LA has touched (#34532, #34450, #34617, #33946, #33776) are documented in
[`../openvino-contribution-npu-int8-guard/phase1-ea17-coordinate-with-intel/upstream-state-report.md`](../openvino-contribution-npu-int8-guard/phase1-ea17-coordinate-with-intel/upstream-state-report.md). They are watched but not actively shepherded unless something changes.

## 6. State

**Current state**: `Active` (founded 2026-05-12).

This workstream stays Active indefinitely as long as the LA has open
upstream items being shepherded. It moves to `Deferred` only if the LA
decides to suspend all upstream engagement, and to `Complete` /
`Archived` only if all tracked items reach a terminal state.
