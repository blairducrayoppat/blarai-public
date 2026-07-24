---
title: Battery Cadence — the 23:00 anchor and daytime targeted runs
status: living
area: runbooks
---

# Battery cadence: the 23:00 anchor, and how to run a targeted battery in daylight

**Maintained by:** any session that changes battery cadence, the wrapper, or the campaign
config. **Audience:** Claude sessions. This is the operational surface; the *why* behind each
rule is cited to the ticket or lesson that produced it, never restated from memory.

**Why this file exists (2026-07-22).** The cadence was real but undocumented — it lived in
`run-battery-night.ps1`'s header comments, in `battery-campaign.json`'s `notes` field, and in
ticket comments. A session picking up #1035 read that ticket's plan text, which says *"one
daytime targeted run each (`--jobs B1` / B6 / B7) … FRESH SANDBOX per the nightly script's
archive+init pattern"*, and found the two clauses in direct tension: **the command named does
not do the thing the same sentence requires.** B1's sandbox was measured dirty (4 inherited
`agent:` commits) at that moment. Following the ticket literally would have produced a
confounded result.

---

## 1. The two rules

**RULE 1 — 23:00 is a standing anchor.** The nightly scheduled task
`\BlarAI\BlarAI-M2-Battery-Nightly` fires daily at 23:00, unattended, and it is the campaign's
backbone. Never disable it, never let a supervised run unregister it, and never edit
`state/battery-campaign.json` while a runner is live.

**RULE 2 — one change per battery RUN, not per day.** Attribution belongs to conditions, not
to the calendar. A battery run measures one change against a condition-matched baseline; two
changes in one run make the result unattributable. But that bounds *changes per run*, not
*runs per day* — so the development cycle is as fast as you can produce clean, separated runs.
Daytime targeted runs are how you get that speed without waiting for 23:00.

A run carrying **no code change at all** — a pure validation of merged main, e.g. #1035's
credential re-verification — consumes **no attribution window** and never stacks with anything.

---

## 2. The daytime targeted run — the only correct invocation

```powershell
& C:\Users\mrbla\agentic-setup\scripts\run-battery-night.ps1 `
    -Now `
    -CampaignConfig C:\Users\mrbla\agentic-setup\state\<your-side-config>.json
```

`-Now` is the sanctioned manual daytime path: it skips the dispatch guard and the lean
wait-loop. The script's own header calls it "manual daytime invocation".

### DO NOT invoke the harness directly

```
python -m tools.dispatch_harness.battery --jobs B1      # <-- WRONG for a targeted run
```

**This does not archive or re-initialise the sandbox.** The archive-by-rename + `git init`
block lives in `run-battery-night.ps1` (~line 662), not in the harness. Run the harness
directly and the card builds on top of its previous run's commits — which is the 2026-07-21
17:19 confounded-baseline lesson, and the shape lesson 225 exists to prevent. Going through
the wrapper makes sandbox freshness true **by construction** rather than by anyone remembering.
Since #1058 the harness REFUSES a dirty or unreadable sandbox on the live path (fail-loud
STALLED [HARNESS], see §4) — so a direct invocation onto a used sandbox no longer runs
confounded, it stops. The wrapper is still the correct path: the gate refuses the run; only
the wrapper *produces* a fresh sandbox.

Note the wrapper *archives* (renames), never deletes. Nothing is lost.

---

## 3. Always use a SIDE campaign config

Never point a targeted run at `state/battery-campaign.json`.

**The reason is a real incident (2026-07-09):** a supervised one-shot run hit its own `1/1`
target and the post-run check silently **unregistered the real nightly task**. The 23:00
campaign would simply not have fired; it was caught only by the operator's pre-battery
checklist question. `run-battery-night.ps1` now scopes self-unregister to the *default* config
only — but that guard works because you pass a side config.

Side-config template (see `state/battery-1035-b1-revalidate-20260722.json` for a worked one):

```json
{
  "campaign": "<ticket>-<card>-<purpose>-<YYYYMMDD>",
  "description": "SUPERVISED daytime targeted run (NOT the m2-baseline campaign): <what and why>",
  "jobs": ["B1"],
  "excluded": [],
  "target_full_passes": 1,
  "completed_passes": 0,
  "end_date": "2099-12-31",
  "notes": "One-shot supervised config passed via -CampaignConfig; state/battery-campaign.json is UNTOUCHED."
}
```

**`completed_passes` MUST be below `target_full_passes`** — see §3a(c). An earlier version of
this template published `1/1`, copied from the 2026-07-09 side config, which was written *after*
its run completed. That makes step 1 exit immediately: the runbook would have published the exact
artifact whose failure mode it documents six lines later.

`end_date` is required too (§3a(b)); a far-future date means no calendar cutoff.

---

## 3a. Launch gotchas — three that each cost a failed launch on 2026-07-22

All three were hit in sequence launching #1035's B1 run. None is in the script's header.

**(a) Use `pwsh.exe`, never `powershell.exe`.** The script is BOM-less UTF-8. Windows
PowerShell 5.1 reads a BOM-less `.ps1` as ANSI, which mangles every em dash and produces a
cascade of bogus parse errors (`Unexpected token 'night' in expression or statement`, etc.)
that look exactly like a corrupted file. **It is not corrupted** — verify with
`python -c "open(p,'rb').read().decode('utf-8')"` before alarming. The scheduled task itself
uses `pwsh.exe`, so the 23:00 run is unaffected by this; it only bites hand-launches.

**(b) A side config MUST include `end_date`.** The script's own comment at ~line 228 says
*"end_date = no calendar cutoff (a side/manual config just omits it)"* — and the code cannot
honour it: `if ($camp.end_date)` throws `The property 'end_date' cannot be found on this
object`. Set a far-future date (`"2099-12-31"`) until #1045 is fixed.

**The cause is `Set-StrictMode`, not the PowerShell edition.** An earlier version of this
runbook blamed `pwsh` vs 5.1; that was wrong, and the correction is worth carrying because the
real cause is a *scope leak* that will bite other things in this script. `run-battery-night.ps1:59`
dot-sources `ao-ownership-lib.ps1`, which sets `Set-StrictMode -Version Latest` at `:62`.
Dot-sourcing runs in the **caller's** scope, so StrictMode is live for the remaining ~776 lines
including the `end_date` check. Measured across all four cells — `powershell.exe` 5.1 and
`pwsh` 7.6.4, StrictMode off and Latest — the edition makes no difference and StrictMode makes
all of it: **both** editions return null-and-continue with StrictMode off, and **both** throw the
identical message with it on. The script already documents this leak at `:757-758`.

Consequence beyond `end_date`: **any bare `$camp.<optional_key>` access anywhere after line 59
is equally exposed.** Guard with `$obj.PSObject.Properties.Name -contains 'key'`, which the
script already does correctly for `baseline_jobs`.

**(c) Set `completed_passes` BELOW `target_full_passes`.** The 2026-07-09 side-config template
carries `1/1` because it was written *after* its run completed. Copy it verbatim and step 1
(CAMPAIGN CHECK) sees a complete campaign and **exits immediately** — correctly logging *"side
campaign config complete (1/1) — NOT touching the shared scheduled task"*, which reads like a
successful guard rather than a run that never happened. Use `"completed_passes": 0`.

**Also expect the lean preflight to stop restartable desktop apps** (it stopped `WINWORD` on
2026-07-22) to free RAM. That is by design and they are safe to reopen — but if the operator is
mid-document, warn before launching.

## 4. Before you spend the GPU — the cheap precondition probe

Lesson 225: *gate the expensive resource on the cheapest probe of the experiment's validity
precondition, and read the system's own emitted evidence rather than an assumption.*

```bash
cd C:/Users/mrbla/projects/battery-<card>-<slug>
git log --oneline | head            # 'agent:' commits == a previous run's work
git rev-list --count HEAD
```

A seed-only sandbox shows the `seed:` commit and nothing else. Any `agent:` commit means the
sandbox is dirty. **This does not block a wrapper-launched run** (the wrapper archives and
re-inits), but record what you found — the run's *condition* belongs in its own evidence, which
is the actual content of the lesson.

> The structural version of this check is **BUILT (#1058)** — lesson 225's third-instance
> control. The harness itself (`tools/dispatch_harness/battery.py`,
> `probe_sandbox_freshness` + the gate in `run_battery`) refuses a live card whose sandbox
> history is not provably init/seed-only, BEFORE the AO re-ensure or any dispatch: a dirty or
> unreadable history is a fail-loud STALLED [HARNESS] refusal, deny-by-default. The manual
> probe above remains the cheap pre-launch habit — and it reads HEAD only, while the harness
> gate reads `--all` refs, so a prior PARKED run's unmerged branch dirties too. The only
> opt-out is `--allow-dirty-sandbox` (a deliberate dirty-sandbox experiment); the observed
> condition is recorded in the scorecard evidence (`sandbox_freshness` / `sandbox_opt_out`)
> either way, and an UNREADABLE history is refused even under the opt-out — a condition
> nobody observed cannot ride the evidence.

---

## 5. Guards to verify before every targeted launch

| Check | How | Why |
|---|---|---|
| Nightly task intact | `Get-ScheduledTask` → state `Ready` | The 23:00 anchor must survive your run |
| Default campaign untouched | `state/battery-campaign.json` counters unchanged after | A side config must never move real counters |
| No runner live | no `run-fleet` / `swap_ops` processes; battery task not Running | Never edit the campaign config mid-run; never clobber a run in flight |
| Card not silently promoted | your side config's `jobs` ≠ `baseline_jobs` | `jobs == baseline_jobs` set-equality makes nights bank **FULL** passes, and at `target_full_passes` the scheduled task **SELF-UNREGISTERS** |
| GPU free | no other model resident | Any second model load contends at the 31.323 GB ceiling |

**Restoring a retired card to the nightly `jobs` list is an LA decision, never a session's** —
because of the set-equality/self-unregister chain in the row above (#1035 states this
explicitly).

---

## 6. Where the authoritative state lives

Read these; never restate their contents from memory.

- `C:/Users/mrbla/agentic-setup/scripts/run-battery-night.ps1` — the wrapper. Its header is the
  authoritative description of the run sequence.
- `C:/Users/mrbla/agentic-setup/state/battery-campaign.json` — the live campaign: `jobs`,
  `baseline_jobs`, counters, `end_date`, and a `notes` field carrying every LA cadence decision
  with its date and rationale. **Gitignored — a corrupted count cannot be reconstructed.**
- `C:/Users/mrbla/agentic-setup/state/battery/night-<stamp>/` — per-run artifacts: `launcher.log`
  (the wrapper's transcript), `battery-runner.log`, `scorecards/`, `MORNING-REPORT.md`.
- `evals/battery/B*.json` (this repo) — the cards themselves.
- `shared/timeout_registry.py` (this repo) — **the budget SSOT.** Any duration, budget or
  watchdog reasoning starts here.

**Known observability gap (#1039):** `JobReport.asked_requirements` and `asked_clarifying` are
**not** persisted to the scorecard, and the harness's own `self.log(...)` lines do not reach
`battery-runner.log` (that file is the PowerShell wrapper's transcript). Verified by control
greps: harness strings such as `"PLAN did not yield"` return zero hits there. So their absence
from run artifacts is **not** evidence they never fired.
