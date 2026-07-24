# Advanced-Intake (S1) Go-Live Runbook

<!-- doc-rot gate (#994): the config flag gating this ceremony. The EXECUTED banner below must agree with its LIVE state in services/assistant_orchestrator/config/default.toml — read there, never from this doc. -->
<!-- Gating-flag: [fleet_dispatch].advanced_intake -->

> ## STATUS: EXECUTED — 2026-07-22 (#1031). Do not re-run.
>
> **The advanced-intake front (S1) is LIVE.** `[fleet_dispatch] advanced_intake = true`
> in `services/assistant_orchestrator/config/default.toml`. The two deterministic
> intake rulers — the empty-check realism guard and the web delivery floor — now act on
> every operator-facing and headless dispatch's acceptance spec. Read every step below in
> the past tense unless you are deliberately RE-WELDING (see the reversal path).
>
> Live posture is read from `default.toml`, never from this file.

**Flip → boot → drive one real web intake → confirm both rulers fire → evidence.** This is
the LA-present ceremony that takes S1 from DORMANT to live. For the Lead Architect
(non-developer-friendly). Everything here is **reversible** — unlike an egress ceremony,
there is no point of no return: flipping the flag back to `false` and restarting fully
restores the prior behaviour, because S1's rulers only ADD or DEMOTE criteria at plan time
and never touch anything already built or shipped.

## What this ceremony makes live

With `advanced_intake = true`, `generate_plan` runs two deterministic rulers over the
acceptance spec, in floor-then-guard order (#1041):

1. **Delivery floor** — a web / web-static spec gains a machine-gated SMOKE criterion,
   `id = delivery-floor`, asserting *"the served page loads and displays its main content."*
   The direct answer to the Bill Splitter class: a build that passes every code gate and
   serves a dead page.
2. **Realism guard** — a criterion claiming an objective (machine-checked) tier whose
   `check` is EMPTY is demoted to human-judged. It never manufactures a check, never
   auto-passes, and never promotes.

It does **NOT** light up S2–S4: no wider elicitation interview, no co-authored criteria, no
1:1 oracle import contract, no blocking coverage enforcement. Those are unbuilt and have
their own decisions. `advanced_intake` gates only the two rulers above.

## What was ALREADY BUILT (verify, don't build)

- `shared/fleet/acceptance.py` — `_ensure_delivery_floor` (idempotent by `DELIVERY_FLOOR_ID`,
  #1041) and `_apply_realism_guard`, invoked at the 2e gate in `generate_plan` when
  `advanced_intake` is true and the dispatch is not card-driven (`_is_card_driven` — battery
  cards are frozen and never receive an injected criterion).
- `services/assistant_orchestrator/src/entrypoint.py` — the resolved property
  `fleet_dispatch_advanced_intake_enabled` (validate-not-coerce: only an explicit boolean
  `true` enables it, #1042).

## The ceremony, as performed (2026-07-22)

1. **Flip.** `advanced_intake = false → true` in `default.toml`, on a feature branch, with
   this runbook + the DECISION record + a journal entry in the same change.
2. **Gate.** Standing gate green on the branch and re-measured on merged main; the doc-rot
   gate confirms this banner agrees with the live flag.
3. **Merge LIVE** (not dormant — the flip IS the go-live).
4. **Boot** the assistant so the resolved config carries the flag.
5. **Live-verify** — drive one real web-app intake through the running assistant and confirm
   the resulting plan carries a `delivery-floor` SMOKE criterion, and that an empty-check
   objective criterion is demoted to human. This is the go-live moment, witnessed by the LA.
6. **Evidence** — the live plan's criteria captured to the #1031 ticket.

## Reversal (RE-WELD) — fully sufficient, no residue

Flip `advanced_intake = false` in `default.toml` and restart the assistant. Because S1's
rulers act only at plan time and only ADD/DEMOTE criteria, no built artifact, no shipped
dispatch, and no stored spec is altered by the reversal — the next plan is byte-identical to
the pre-go-live behaviour. There is no key to destroy and no allowlist to empty; the flag is
the whole surface.
