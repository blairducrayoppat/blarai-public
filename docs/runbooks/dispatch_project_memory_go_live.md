# Go-live runbook — `[fleet_dispatch].project_memory` (#1120 / #1124)

<!-- doc-rot gate (#994): the config flag gating this ceremony. The STATUS banner below must agree with its LIVE state in services/assistant_orchestrator/config/default.toml — read there, never from this doc. -->
<!-- Gating-flag: [fleet_dispatch].project_memory -->

> ## STATUS: NOT EXECUTED — dormant since 2026-07-27 (#1124).
>
> **Project memory is OFF.** `[fleet_dispatch] project_memory = false` in
> `services/assistant_orchestrator/config/default.toml`. Nothing is recalled, nothing is
> written, and no row is created — the dispatch corridor behaves exactly as it did before
> #1120. Read every step below in the future tense.
>
> The LA reserved the ON state for focused validation runs (2026-07-27): *"we'll turn it
> on for validation but we'll want it off otherwise."* If you flip it, flip it back.

**Status:** DORMANT (`project_memory = false` shipped default)
**Decision owner:** Lead Architect. This is a **privacy-posture** flip, which `CLAUDE.md`
`decision_boundary` reserves to him — not a technical choice.
**Authored:** 2026-07-27, after independent review found #1120 had merged LIVE with no gate.

---

## Why this flag exists at all

#1120 shipped without one. Independent security review (2026-07-27) called that a
**governance breach rather than a defect**: every neighbouring capability in
`[fleet_dispatch]` carries its own gate (`clarify`, `revise`, `advanced_intake`,
`advanced_intake_bad_input_floor`, `advanced_intake_coherence_gate`,
`research_grounding`), and `CLAUDE.md` `autonomy` requires that *"anything constituting a
NEW capability, a quality change, or a security/governance posture flip merges DORMANT
behind a config flag and waits for his ceremony."*

Retention of the operator's typed goal text is exactly that. Reverting it had required a
code change; now it is one line of config. The LA chose **"add the switch, default OFF"**
on 2026-07-27 and reserved the ON state for validation runs.

## What the operator is actually deciding

**ON** means BlarAI **retains your typed project descriptions and clarification answers
INDEFINITELY** — no expiry, no size cap — and **replays them into the planning prompt on
every later dispatch for that project**.

The content is born-encrypted at rest the entire time (AES-256-GCM under the shared
one-DEK envelope, AAD-bound to the project) and never leaves the machine. **The decision
is about RETENTION, not exposure.**

**OFF** is full dormancy, not a degraded mode: nothing recalled, nothing written, no row
created. The corridor behaves exactly as it did before #1120 — *including* the amnesia
this feature exists to fix (answers given to a clarifying question are lost when a plan is
rejected).

## Known limitations at first go-live — READ BEFORE FLIPPING

Tracked by #1123–#1125. Until they land:

1. **Once a project has any remembered answer, BlarAI stops asking clarifying questions
   for that project**, and the old goal's answers are applied to every NEW goal on it.
   Safe for re-running the SAME goal; wrong for a different goal on the same project.
2. **Deleting a conversation does not delete what was remembered.**
3. **There is no listing surface** — you cannot see everything BlarAI has banked, only
   what a given plan card shows.
4. There is **no cap and no expiry**, so memory for a long-lived project grows and
   consumes planning context.

Honest guidance until those close: **turn it on for a focused validation run, turn it off
afterwards.**

## The ceremony

LA-present. Not an autonomous flip.

1. **State the decision back to him** in plain language — the retention sentence above and
   the four limitations. He is deciding retention, not encryption.
2. Stop the assistant: `agentic-setup/scripts/stop-assistant.ps1`.
3. Edit `services/assistant_orchestrator/config/default.toml`:
   `project_memory = false` → `true`.
4. Start the assistant. Confirm in `%LOCALAPPDATA%/BlarAI/launcher.log` that boot is clean
   and `DispatchStateStore initialized` appears.
5. **Live-verify the round trip**, do not assume it: dispatch a goal, answer the questions,
   `/dispatch reject`, then re-dispatch the same goal. The plan card must show the
   *"I'm still using what you told me about this project earlier"* section.
6. Record the flip: dated ledger entry + a comment on #1124 citing the config commit.

## Reverting

One line: `project_memory = false`, restart. Immediate and complete — no code change, no
rebuild.

**Reverting does NOT delete rows already written.** To remove banked data:

- `/dispatch forget <project>` — per project. Works whether the flag is on or off
  (deliberate: turning retention off must never disable the eraser).
- Or delete `%LOCALAPPDATA%/BlarAI/dispatch_state.db` outright, which also clears the
  #1116 parked-dispatch state.

## What must NOT be done

- **Do not flip this autonomously**, in an overnight run, or as a side effect of another
  change. `security_by_design` principle 13: irreversible/posture changes are LA-present
  events.
- **Do not gate #1116 durability on this flag.** They are separately gated on purpose — a
  parked question surviving a restart carries no retention decision, and collapsing them
  would make the LA's privacy choice silently re-open the lost-answer defect #1116 fixed.
  Locked by `test_dormant_memory_does_not_disable_1116_durability`.

## Gate locks

- `test_config_default_ships_project_memory_dormant` — reads the shipped TOML; fails
  loudly if the default is ever flipped by an unrelated edit.
- `test_missing_project_memory_key_resolves_dormant` — an absent key resolves OFF.
- `test_project_memory_is_dormant_by_default` — proves dormancy is structural (no row
  written, no requirements sentinel threaded), not merely unread.
- `test_forget_still_works_while_memory_is_dormant`.
