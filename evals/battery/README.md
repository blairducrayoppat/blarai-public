# M2 Capability Battery — spec v1 (W9, Vikunja #740)

The versioned **job battery** from the fleet-maturation program plan
(`docs/research/fleet-maturation-program-plan-2026-07.md` §9.4/§9.5): eight
jobs spanning the claimed capability envelope — unit counts {3,5,8}, stacks
{python-cli, python-lib, node-web}, dependency shapes {chain, diamond/fan-in,
independent, mixed} — each with a pre-authored **expected-outcome card**. The
battery is how the §7.2 scope claim ("reliably handles a multi-part
application of ~3-8 coherent units") gets *measured* instead of asserted, and
it re-runs as a regression suite after every orchestration or model change.

## The cards (`B1.json` … `B8.json`)

One JSON card per job, `schema: "battery-card/v1"`. Fields:

| Field | Meaning |
|---|---|
| `id` / `title` / `provenance` | Battery row id; the plan §9.4 row it implements. |
| `stack` / `units` / `shape` | The envelope cell this job probes (per the §9.4 table, exactly). |
| `repo` | The **sandbox** target repo name under the projects dir. MUST start with `battery-` — the runner refuses anything else (plan §10 S5: battery targets are pinned to sandbox repos; the operator's real repos are never eligible; `validate_repo` containment still applies underneath). |
| `goal` | The one-paragraph goal, written as a non-developer would write it. This exact text is what gets dispatched. |
| `clarify_answer` | The answer used if the Inc-4 clarifying question fires (option number or label). |
| `rigs` | Adversarial rigs this job carries (`[]` for capability jobs; B8 carries `["N1","N2","N3"]`). |
| `expected_outcome` | The pre-authored expectation card (below). |

`expected_outcome`:

- `must_verify_tiers` — acceptance tiers that MUST reach `verified` by
  mechanical check (`build`, `behavior`); a job whose objective tiers end
  `unverified` is not GREEN.
- `human_tiers_expected` — tiers that legitimately end eyeball/UNVERIFIED
  (`visual` on the web jobs). These are handed to the operator explicitly,
  never auto-passed.
- `oracle` — whether a job-level spec-blind oracle is expected, its
  ecosystem, and its expected path (`tests/test_job_acceptance.py` for
  python, `tests/acceptance.job.test.mjs` for node — plan §4.5).
- `allowed_terminal_verdicts` — the verdicts that count as the system
  *working* for this job. `target_verdict` is the aim, advisory only.
- `min_dependency_edges` / `expects_context_packs` / `expects_waves_gte` —
  structural facts the run should exhibit (used for scoring honesty, e.g.
  B1 must actually consume a context pack — plan §3.2 DoD).

## The verdict taxonomy (closed — plan §9.4)

| Verdict | Meaning |
|---|---|
| `GREEN` | Job oracle green on the integrated tree, unattended. The capability success. |
| `PARKED-HONEST` | The system refused/parked with evidence — a **verification success**, a capability miss. This is the system working. |
| `FALSE-DONE` | The system reported done while the job oracle was red, unrun, or "verified" without evidence. **Program-failing at any layer, any time. Zero tolerance.** |
| `STALLED` | The watchdog/monitor had to kill it, it never ran, or it ran but could not be scored — a harness defect, never a capability datum. |
| `RECOVERED` | A crash path fired and the recovery layer worked. |

Every **non-GREEN** verdict carries a failure-**attribution** tag naming the
faulty layer: `PLAN` (decomposition/graph wrong), `BUILD` (coder could not
produce it), `VERIFY` (gates/oracle wrong or missing), `HARNESS`
(environment/runner/swap fault). GREEN carries no attribution.

## Hard gates (what a battery run must satisfy)

1. **FALSE-DONE = 0**, across everything ever run. One FALSE-DONE fails the
   program, not the job.
2. **Negatives caught in full at Must tier** (100%): rigs N1/N4/N5 + the
   §10 security rigs N6/N7. A net never watched failing is theater.
3. **Zero human interventions mid-run** (`interventions` field, summed).

GREEN **rate** is reported, never gated (targeted ≥2/3 at 3-5 units;
expected to drop at 8 units — that is the envelope edge doing its job).

## Unattended safety — web jobs never seize the screen (B3/B5)

The node-web cards (**B3** budget, **B5** habit) run overnight, unattended, and
their built page is rendered for the #688 VLM design critique. That render is
**headless** and never takes over the operator's screen:

- **The web design capture is headless.** A web project has no `App.exe`, so
  `capture-app.ps1` skips the WinUI render (Tier 1) and the foreground GDI grab
  (Tier 2 — the *only* screen-taking tier) and renders the page off-screen with
  `msedge --headless=new --screenshot` (no visible window, no full-desktop grab;
  verified 2026-07-06: a real PNG, 0 visible browser windows during capture).
- **The coder browser is headless too.** During a web CODE task the coder drives
  a browser via `playwright-mcp --browser msedge --headless`
  (`agentic-setup/configs/opencode.json`) — no visible window either.
- **A stray dependency `App.exe` can't mis-route it.** `Find-AppExe` excludes
  `node_modules` (fixed 2026-07-06): before the fix, a binary literally named
  `App.exe` inside a dependency tree made a web project fall into Tier 1/2 —
  which *launched + foregrounded* that arbitrary binary — then a blind structural
  floor. Now a web project routes deterministically to the headless web tier.
- **The visual tier is eyeball, never auto-passed** (`human_tiers_expected:
  ["visual"]`), so the critique is only a loop signal; GREEN is decided by the
  node oracle (build + behavior).

These invariants are regression-locked in
`tests/integration/test_battery_runner.py` (BlarAI side) and
`agentic-setup/scripts/verify-capture.ps1` (the `WC*` section, co-located with
`capture-app.ps1`).

## Gold plans (`gold/`)

Three hand-authored **JobPlan v1** artifacts — `gold-b1`, `gold-b3`,
`gold-b6` — the W2 calibration reference (the 14B's decompositions are
measured against these) and the first exercise of the pinned schema.
Calibration compares graph structure (task grain, `depends_on` edges,
contract shape), **not** literal ids/prompts/`repo` strings.

`plan_hash` in these files is computed by the **reference canonicalization**
implemented at `tools.dispatch_harness.battery.reference_plan_hash`:
sha256 over `json.dumps({"goal": goal, "tasks": tasks_minus_status},
sort_keys=True, separators=(",", ":"), ensure_ascii=False)` (UTF-8), where
`tasks_minus_status` drops each task's volatile `status` field. The volatile
fields MUST stay out of the canonical form or every legitimate status write
would invalidate the hash — see the W9 schema-friction findings on #740. If
Lane A's PlanStore adopts a different canonicalization, re-stamp these files
and this note in the same change.

## Running the battery

```powershell
# Smoke (no GPU, no model, no live AO — the harness's fake-AO dry-run):
$env:LOCALAPPDATA = "$env:TEMP\blarai-battery-la"
.venv\Scripts\python.exe -m tools.dispatch_harness.battery --jobs B1 --dry-run

# Live subset (BlarAI running in production mode; see tools/dispatch_harness):
.venv\Scripts\python.exe -m tools.dispatch_harness.battery --jobs B1,B3,B8

# Full overnight battery:
.venv\Scripts\python.exe -m tools.dispatch_harness.battery --all
```

Scorecards land one-per-job (`<id>.scorecard.json`) plus a
`battery-summary.json`, in `--out DIR` if given, else the *state-appropriate*
default: `<agentic-setup>/state/battery/<stamp>/` for live runs, a fresh temp
dir (printed) for `--dry-run`. Exit codes: `0` = every job honest
(GREEN / PARKED-HONEST / RECOVERED), `1` = ≥1 STALLED (harness needs
attention), `2` = ≥1 **FALSE-DONE** (program-failing).

A job that cannot run or cannot be scored **always** emits a
`STALLED`+`HARNESS` scorecard — never silence.

## Scorecards (`scorecard.schema.json`)

Per-job record, `schema: "battery-scorecard/v1"`, validated by
`tools.dispatch_harness.scorecard`. **Structural only** (plan §10 S6): the
`evidence` object carries file **pointers** and short structured statuses,
never raw logs (no-newline caps are enforced at validation, fail-closed on
write). These JSONs are destined for `docs/performance/` and community
publication — any publication routes through the existing scrub pipeline
(`scripts/scrub_community_export.py` + `scripts/verify_community_scrub.py`)
as a mandatory gate.

The driver's REPORT phase (W6) will emit `scorecard.json` into the run dir
(`state/fleet-runs/<RunId>/`); the runner **adopts** it (validate → stamp
battery context → cross-check). Until that lands, the runner synthesizes a
conservative scorecard from the monitor verdict — and because a pre-W4 run
has no oracle evidence, a merged-but-unverifiable job scores `STALLED` +
`HARNESS` ("cannot be scored"), never GREEN. The FALSE-DONE cross-check has
teeth in the runner: an adopted scorecard claiming GREEN whose
`evidence.oracle_status` is not `"passed"` — or a GREEN on a rig-carrying
job (B8) — is rewritten to `FALSE-DONE` (attribution `VERIFY`).

## Results capture (non-optional)

Battery results are community-grade testing data: every live run's summary
gets a dated `PERFORMANCE_LOG.md` entry + the machine-readable JSONs under
`docs/performance/` (versions, methodology, per-job verdicts + attribution,
and what was NOT measured), per the repo's Testing-Data Capture rule.
