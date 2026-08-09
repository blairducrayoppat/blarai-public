---
title: Coder fleet overhaul — the four gaps between today's battery and a trustworthy coder
status: proposed
area: fleet
date: 2026-07-30
---

# Coder fleet overhaul

**Operator direction, 2026-07-30:** *"I need a working, reliable, robust secure coder that
can do secure python and secure websites, that has the advanced intake and advanced
interview, a local corpus, and proper exams and reviewers."* Asked whether the battery or
the development process needs an overhaul. This is the answer.

## The one-paragraph answer

**The machinery is mature. What it measures is not.** The battery has eight verifiers, a
clean-room second grader, a fail-closed sandbox-freshness gate, per-card budgets and a real
attribution rule. That is a serious instrument. But on 2026-07-30 four independent parts of
it were found reporting confidently while measuring nothing, and the four gaps below are
what remain once those are repaired. None of them is a machinery problem. Every one is a
question the system does not currently ask.

## Where the goal already stands

| the operator's goal | today |
|---|---|
| advanced intake | **shipped** — S3 batched flags live `fb0bc9d6` |
| advanced interview | **shipped** — S2 live `31123cb1`; maturation #1165 in flight |
| working coder, Python | **yes, functionally** — B2/B4 GREEN, oracle + clean-room grader agree |
| **reliable / measurable** | **NO — gap 1** |
| **robust (graded on craft)** | **partly — gap 2** |
| **proper exams** | **NO — gap 3** |
| **secure Python, secure websites** | **NO — gap 4** |
| local corpus | not assessed here; needs its own scoping |

## Gap 1 — it does not test finished code (#1181)

`run-battery-night.ps1:35` points `$BlarRoot` at the **primary checkout**; `:703` resolves
the harness from there; `:663` reads the frozen exam cards from there. The scheduled task's
action targets the primary agentic-setup tree. Neither was on `main` on 2026-07-30 — last
night's scorecards are stamped `"blarai": "21b4e9be"`, the tip of an unmerged feature
branch, while `main` was `f2e4f27b`.

Consequences: the version stamp misleads; merging a fix does not deploy it; and the
condition-matched baseline that RULE 2 of `docs/runbooks/battery_cadence_and_targeted_runs.md`
depends on does not exist.

**Landed today (option c):** the run now stamps `blarai_branch` / `blarai_tree` and the
morning report leads with a banner when the tree was not clean `main`. This makes the
confound visible; it does not remove it.

**Still required (option a):** pin the battery to a dedicated worktree at a named ref, so a
night always measures a commit that exists on `main` and no session's in-flight work can
reach it. **This is the prerequisite for the entire rest of this program** — until it lands,
no change made here can be measured at all.

## Gap 2 — controls can be silenced by editing the template

`lint_stale_readme` (`green_quality/layer1.py:424-431`) matches marker strings from the seed
README. #1142 neutralised the seed text, so the marker no longer appears — in the seed *or*
in the untouched copy that ships. Both projects delivered on 2026-07-29 carry a README
byte-identical to the template (md5 `54dc5f83c79838d9603ca842de653aed`) and the audit calls
them clean. `AGENTS.md` instructs the coder to rewrite it; neither coder did; nothing noticed.

The band-A reading that followed #1142 records a detector that stopped detecting, not a
deliverable that improved.

**Required:** a **seed-divergence check** — flag when a delivered file is byte-identical to
the seed it came from. One control, covers README and `pyproject.toml` metadata together,
and cannot be satisfied by editing the seed. Explicitly rejected: neutralising the metadata
text and extending the marker list, which reproduces the blindness one file over.

Generalise the rule: **a control keyed on a string is a control that can be edited into
silence.** Prefer relational checks (delivered vs seed, exam vs spec) over marker matching.

## Gap 3 — it cannot tell whether an exam covers what was asked

Every GREEN to date carries `green_fingerprint: "oracle_coverage=unknown (no traceability
map)"` and classifies as `GREEN-UNVERIFIED`. Not once has the pipeline produced
`GREEN-VERIFIED`. The system passes work while explicitly recording that it does not know
whether the test exercises the requirement.

That is the single largest gap against "proper exams and reviewers." A GREEN today means
*the oracle passed*, not *the deliverable does what was asked*.

**Required:** a traceability map from each job card's stated requirements to the oracle
assertions that cover them, and a coverage figure on the scorecard. This is the work that
turns `GREEN-UNVERIFIED` into a real verdict. Related open tickets: #967, #1015 (oracle
quality), #965 (unfit-oracle attribution, closed).

Note the compounding risk: an unfit oracle currently mis-attributes its own bugs to the
coder. Coverage measurement and oracle quality are the same programme.

## Gap 4 — nothing asks whether the code is secure (#1182)

Verified by exhaustive grep on 2026-07-30 across all three surfaces that shape what the
coder builds and how it is judged — `AGENTS.md`, `green_quality/`, and all eight exam cards
in `evals/battery/`. Search terms `secur|injection|sanitiz|validat|secret|credential|xss|sql`.
**No match on any surface.**

Two of the eight cards are web applications (**B3** budget tracker, **B5** habit tracker).
These stand in for "secure websites". A delivered app with an injection flaw, a hardcoded
secret, or no input validation passes every gate the battery has and scores GREEN band A.

`CLAUDE.md`'s `security_by_design` holds that *"a build that works but was not designed to
these principles is a defective build — same standing as a failing gate."* That standard
binds every line of BlarAI. The code generator is the one component held to no security bar.

**Required, in four layers:** house rules in the brief → deterministic lints (secret scan,
dangerous sinks, web injection/encoding surfaces) → security acceptance criteria on the two
`node-web` cards (a deliberate re-mint; the cards are `card_class: frozen`) → an adversarial
security pass in the clean-room reviewer, which already exists as a seam.

## Sequencing

Every item below is a battery-path change and consumes its **own** attribution window
(RULE 2). The daytime targeted-run path exists precisely for this — a side campaign config,
never the default (pointing it at the default silently unregistered the real nightly task in
a 2026-07-09 incident).

```
  [DONE 2026-07-30]  repair the instruments        #1051 #1180 #1181(c) #1179
        |
  [NEXT, BLOCKING]   pin the battery to a worktree #1181(a)
        |                    ← nothing below is measurable until this lands
        +---> seed-divergence check                gap 2
        +---> oracle traceability + coverage       gap 3, with #967 #1015
        +---> security: brief → lints → cards → reviewer   gap 4, #1182
```

The security work is the operator's stated priority and the largest single gap, but it must
not go first: adding a security lint to a battery that does not run merged code, and cannot
tell whether an exam covers its spec, produces a number nobody can trust.

## What this program does not cover

- The **local corpus** goal — not assessed; needs its own scoping pass.
- **Node/web craft grading** generally: `green_quality` is Python-centric, and B3/B5/B7 are
  node cards. Coverage there is thinner than this document has examined.
- **#966** (the morning read has no owner) — open since 2026-07-19, and the reason every
  finding in this document waited for the operator to ask a question. Worth closing as part
  of the process half of the overhaul.
