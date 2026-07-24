# Dispatch Quality Ledger — the development-system learning loop

> **What this is.** The durable, git-versioned home for per-dispatch quality
> observations — the evidence store behind the PLAN-layer learning loop
> (Vikunja #877). Adopted 2026-07-14 at LA direction: a Vikunja ticket is for
> WORK, not for accumulating process wisdom; ticket comments are unversioned,
> ungreppable, and live in a server database. Evidence rows live HERE;
> #877 remains the work ticket (graduation work items, prompt tunes, eval
> locks); decisions stay on the ticket that caused them (doctrine).

## Method (from #877, the #717 precedent: observe → pattern → measured tune → eval lock)

- **One entry per dispatch run**, appended at run completion, grading the run
  on the six standing dimensions below. Evidence pointers (run id, log paths,
  scorecard verdicts), never vibes. Failures stay in — a sanitized ledger
  doesn't compound.
- **Standing observations** (cross-run patterns, tooling lessons) get dated
  entries in their own section as they surface, mid-run allowed.
- **Graduation:** when a dimension shows the same defect across ~5 runs, it
  graduates — write the eval pair FIRST (good/bad plan for the same ask), tune
  the PLAN persona against it, commit the baseline to `evals/` (regression
  exit codes with teeth). Never tweak-and-hope.
- **After appending here:** one-line pointer comment on #877 and a pointer on
  the run's Coder Jobs ticket (project 12). The ledger row is the record; the
  comments are the notification.
- Related machinery: ADR-037 (grading taxonomy + quarterly review — this
  ledger feeds it), ADR-038 (frozen/dev eval split — new scenario cards are
  born-dev, add-only), #722 (answer-quality suite), #834 (model profiles),
  #855 (coordinator shadow grading — a sibling loop over the shadow journal).

## The six standing dimensions (seeded from run 20260714-191219-bd)

1. **DECOMPOSITION GRAIN** — over-split? (Seed evidence: 5 tasks including
   three same-file edits for a one-file page — heavy; exercised the waves,
   wasteful for production.)
2. **CHECK REALISM** — boilerplate checks? ("compiles and installs without
   errors" for a static HTML page is a template artifact, not a real check.
   Watch also the inverse defect: a plan MANUFACTURING verifiability it
   cannot deliver — a fake objective check for "premium feel" is the seed of
   a future false-GREEN. See #877 c.1902.)
3. **SCOPE FIDELITY** — silent additions? ("responsive on different screen
   sizes" appeared in assumptions/checks; never asked.)
4. **HONESTY LINES** — present and correct? (The language-detection warning
   was the best line in the seed run's output: no verification promised that
   cannot be delivered.)
5. **ASSUMPTION QUALITY** — declared vs smuggled. (All four declared in the
   seed run.)
6. **ACCEPTANCE-CRITERIA PINNING** — does the plan pin the ask's named
   artifacts/texts (e.g. the site title), or rely on the goal text riding
   through?

---

## Run entries (newest first)

### 20260716-234039-bd — "flashcards CLI" (B4, lean-battery night 2) — VERDICT: PARKED-HONEST (attribution: BUILD) — and the two-night park cause REVERSED onto the probe

Night 2 of the #904 lean diagnostic (B2+B4; banking frozen). **B2 GREEN**
(run 20260716-230110-bd, 2,233s — down from night 1's 4,008s; oracle passed;
**guest-oracle certificate minted and AGREE** — the clean-room cross-check
concurring with the host verdict). **B4 PARKED-HONEST[BUILD]** (7,065s);
runner exit 0, stalled=0. B4 mechanism as logged: waves 1–4 integration gates
PASSED (including `implement-card-management`, the night-1 scratch-test victim
— that class did not recur); wave-5 `implement-command-interface` parked →
`acceptance-tests` skipped; the wave-final **layout gate failed with all four
contract imports unresolved**, the fix-cycle fired (re-ran the wave-5 owner)
and did not recover; job oracle not-run; guest certificate honestly `not-run
(host-oracle-not-run)`.

**Root-cause REVERSAL (corrects the night-1 entry below).** The overnight #790
sub-task-5 build + two independent reviews proved the two-night layout-gate
park cause is the **probe itself**: `shared/fleet/import_probe.py` checked
`hasattr(mod, name)` only and never modeled Python's submodule fallback for
`from pkg import name` — it false-parked trees a real interpreter imports
fine. The night-1 entry's "eager `__init__`" mechanism is retracted: the
archived `flashcard_app/__init__.py` is LAZY (docstring + `__version__` only),
and the "all-modules-fail signature" is the probe's own dialect bug (its
"resolves but export absent" reason is only producible by the hasattr-only
path over a lazy init). Replay proof on the archived night-1 tree: old probe
exit 1 with byte-identical production reasons; the oracle's exact import line
succeeds in a fresh interpreter; fixed probe exit 0. This also explains why
the fix-cycle cannot recover this shape — it re-runs a coder to produce names
that are already importable.

**Fix SHIPPED tonight** (BlarAI `90da3967` — probe mirrors CPython
`_handle_fromlist`, stricter-never-looser, park-only; agentic-setup `5f2f649`
— canonical-package scaffold seed kills the duplicate `app/`+oracle-pkg twin).
**Tomorrow night is the A/B; tonight's B4 is the clean pre-fix baseline.**
Honest residual: wave-5's task-level park happened BEFORE the layout gate and
its own cause was not dug out tonight — the A/B may still show a wave-5 BUILD
park even with the layout false-park dead; that would be the next honest
signal, not a fix failure.

### 20260716-001549-bd — "flashcards CLI" (B4, first lean-battery night) — VERDICT: PARKED-HONEST (attribution: BUILD; failure_class ORACLE-DEFECT)

First night on the #904-trimmed lean battery (B2+B4 only). **B2 GREEN**
(text-stats, the canary — 4,008s); **B4 PARKED-HONEST[BUILD]** (8,360s);
runner exit 0, **stalled=0** (the #906-class stall did NOT recur as a stall —
see the machinery note below). Read-only forensic from the archived sandbox
(`repos-archived/battery-b4-flashcards-cli/`); the #790 worktree was never
touched.

**B4 root cause — the duplicate-scaffold defect (#790 sub-task 5) PROMOTED
from benign to the park cause.** B4 built all 6 waves clean (every wave
integration gate PASSED — the coder produced working modules), then the FINAL
**layout gate failed**: the integrated tree could not satisfy the oracle
contract `from flashcard_app import card_manager, quiz_engine, score_tracker,
main, data_storage`, and the targeted **fix-cycle ran but did NOT resolve it**.
The as-built tree carried BOTH `app/` (generic scaffold — `app/core.py` +
`tests/test_core.py` importing `from app.core import summarize`, a text-stats
leftover) AND `flashcard_app/` (the real modules + an `__init__.py` that
EAGERLY imports every submodule). The oracle wants `flashcard_app`; the eager
`__init__` means one submodule import-error fails the WHOLE package, so all
contract imports fail (the gate repeated the contract 4× = all-modules-fail
signature). **Last night (2026-07-15) the same duplicate trees existed but the
layout gate PASSED (benign); tonight they are the park cause** — so sub-task 5,
previously ranked "lower priority — did not cause a park," now has.

**Machinery finding (first live exercise of the layout-fix-cycle repair
path).** The layout fix-cycle (merged `311cfe8f`, N1-locked `562ce1a1`) had
been regression-locked but never *live*-triggered (c.1888). Tonight it fired
live on a real layout failure and **did NOT recover** — it re-ran an owner,
but the duplicate-tree root is not something re-running a single task can fix
(the fix picks an owning task for a missing module; here the module exists in
the WRONG package, so no single re-run collapses the duplicate). Worth its own
look under #790.

**What did NOT recur:** last night's scratch-test gate-artifact park class —
waves 1–6 all merged clean, no buggy coder-authored `test_*.py` blocked a
merge. That failure class did not reappear this run.

**Machinery note — the #906 stall class (control observation).** The cert-drift
condition #906 targets recurred at the B2→B4 boundary (`battery-runner.log:8`,
`mTLS handshake FAILS — cert drift`), but the #750 re-ensure + #805
cache-drop-on-failure won the race this time — B4 connected and ran (parking on
the unrelated BUILD defect above), `stalled=0`, runner exit 0. Last night the
identical condition lost the race 3× (B2/B5/B7 STALLED). This confirms the
class is an intermittent race; #906 (merged `4d410a3a`, live-verified same
night) makes recovery deterministic. #906 was NOT live during this run.

### 20260715-081634-bd — "Bill Splitter" web tool (Candidate-2 supervised e2e) — VERDICT: ABORTED (attribution: EXTERNAL — Windows auto-restart)

Plan-graph (M2), 7 tasks. A Windows automatic restart (upgrade install) at
09:49:33 killed the run mid-CODE; it never reached REPORT (no `scorecard.json`;
swap-state reconciled to RECOVERED on the 10:09 relaunch). NOT an honest park —
an external interruption. No project-12 bridge ticket was created (the #749
REPORT leg never ran — so an aborted-pre-REPORT run is invisible to project 12;
note for #878 dashboard: mid-flight runs need a surface that does not depend on
the REPORT leg). One task merged (handle-zero-bill, `20e419d` + visual-fix
`d76c98c`); a second (integrate-bill-split candidate 2) was in flight at kill.

The headline observable of this test — the coordinator's first redispatch DRAFT
on an honest park — was NOT reached (killed, not parked). Re-run deferred (LA:
record-and-move-on).

**Timing / concurrency (the #889 question — ANSWERED):**
- handle-zero-bill      TASK-START 08:20:59 → TASK-END 09:12:45 (~51.8 min)
- integrate-bill-split  TASK-START 09:12:49 (4 s later) → killed mid-candidate-2

The two "wave 1" tasks ran STRICTLY SERIAL (zero wall-clock overlap); each
wave-member is its OWN sequential fleet invocation (separate `run-fleet-<task>.log`,
own done.txt/SUMMARY.txt, "processed 1 of 1"). A plan "wave" is a dependency
grouping, not concurrent execution — the single 30B decodes one agent at a time
(WIP=1, #841 c.1804). There is NO parallel sample; #889 re-scoped to a deliberate
controlled concurrency test.

Six dimensions (PARTIAL — only the plan + one merged task were observable):

1. **DECOMPOSITION GRAIN — HEAVY** (same shape as the seed run): 7 tasks for a
   one-file bill-split page, five of them same-file edits to `bill_split.js`
   (handle-zero / -empty / -no-people / -non-number / friendly-messages) — the
   classic over-split that turns downstream same-file waves into no-ops. Not run
   to completion, so the no-op cascade is INFERRED, not observed.
2. **CHECK REALISM — REALISTIC this run.** The seeded job oracle pinned real
   behaviors ($100/4 = $25; 15% tip → $28.75; friendly messages for
   zero/empty/non-number/no-people); c1 (handle-zero-bill) passed 12/12 tests +
   build/verify.
3. **SCOPE FIDELITY — not fully auditable** (aborted); no obvious silent
   additions in the plan tasks read.
4. **HONESTY LINES — n/a at job level** (no verdict rendered; correctly no
   scorecard for an unfinished job).
5. **ASSUMPTION QUALITY — GOOD**: four declared (normal window; decimals
   supported; no calculation history; clear friendly message for invalid input).
6. **ACCEPTANCE-CRITERIA PINNING — GOOD**: the 14B-authored job oracle pinned
   the named numeric checks + message texts (imports `splitBill` from `../app.js`).

**Efficiency observation (single data point, task 1):** ~51.8 min for a "simple"
task — ~15 min real build (all tests green at 08:35) + ~37 min post-merge
COSMETIC visual-fix retries (fix1 timed out ~10 min, discarded; fix2 ~13 min,
merged `d76c98c`). Distinct from the seed run's empty-attempt cost: here the
retries were VISUAL polish on an ALREADY-GREEN, non-visual-critical task. If this
recurs, the fix is a "skip cosmetic visual-fix when deterministic gates are GREEN
and the task's own contract is non-visual" pre-check (cross-ref tuning candidate
(b) in the seed-run standing observation - tracked as **#1049**).

**Machinery finding (own record): the swap-recovery reconciler passed its first
REAL exercise.** `shared/fleet/swap_state.py`'s boot reconciler read the stranded
CODE-phase record, saw the driver dead (`driver_alive`=False → crashed-swap path,
not the #758 live-driver hands-off), disarmed the watchdog sentinel, converged to
"14B up, 30B down", stamped RECOVERED — no hand-editing of state needed. First
non-drill exercise under a genuine OS reboot; passed. Separately, the FIRST
relaunch fast-exited with no on-disk reason (pythonw discards stderr) — ticketed
#890.

---

### 20260714-191219-bd — "Blair's Lab" static site (first supervised e2e) — VERDICT: STALLED (attribution: HARNESS)

Plan-graph (M2), 5 dependent waves; wall-clock 10,801 s vs the 10,800 s budget
— the budget watchdog tree-killed wave 4 (validate-html → parked TIMEOUT),
wave 5 skipped as its dependent; waves 1–3 merged with integration gates
`verify=pass; tests=pass (node)`. The site is content-complete (and was by
19:30); the job-level oracle never ran (`job_acceptance: pending`) so the
verdict machinery refused GREEN — the honest outcome. Bridge ticket
project-12 #880 stayed OPEN with the outcome comment (the #749 REPORT leg's
first STALLED exercise — pass; nit: ticket titled after the first task, not
the job goal).

Six dimensions:

1. **DECOMPOSITION GRAIN — DEFECT, the run's root cause.** Three same-file
   edits invited wave-1 over-delivery (+83 lines built the whole page);
   waves 2–3 became no-ops; the produced-changes retry pressure then burned
   ~80+ min of GPU across 5 empty/manufactured attempts; the budget died of
   it. The stall is a GRAIN defect wearing a TIMEOUT costume.
2. **CHECK REALISM — WEAK** (seed evidence: "compiles and installs" on a
   static page; the validate-html wave itself was a reasonable check task).
3. **SCOPE FIDELITY — MIXED** ("responsive" appeared unasked; wave-1
   over-delivery matched job scope but broke wave contracts).
4. **HONESTY LINES — STRONG.** STALLED/HARNESS named truthfully; no false
   GREEN over a complete-LOOKING site; oracle status carried as unknown;
   ticket left OPEN. The machinery preferred "I didn't verify" to "looks
   done" at every layer.
5. **ASSUMPTION QUALITY — GOOD** (all four declared at plan time).
6. **ACCEPTANCE-CRITERIA PINNING — PARTIAL EVIDENCE** (14B-authored job
   oracle pinned named content; full assertion set not audited tonight).

Machinery findings this run (each with its own record): oracle protection
held structurally against a real coder write (restore-before-grade);
retry-pressure manufactured diffs twice; coordinator harvest blind — two
defects ticketed (#881 lexical-sort, #882 SUMMARY-truncation) and the shadow
invariant held throughout (board move + digest journal-only, zero Vikunja
writes, dead-man silent through step-aside/reboot).

---

## Standing observations (cross-run patterns and tooling lessons)

### 2026-07-14 — The coordinator's debut harvest was blind: latest_run_id's lexical sort lost to letter-named scratch (DEFECT, ticketed #881)

The night's sharpest catch, found by reading the heartbeat's cycle-2 stamp
rather than trusting it: `harvest-board-move` and `redispatch-staging` said
"no finished run" seven minutes after the STALLED scorecard for
20260714-191219-bd landed. Root cause: `shared/fleet/dispatch.py
latest_run_id()` picks `sorted(dirs)[-1]` ("run-fleet names sort by time") —
and stale June scratch (`selftest-8df957`, `regr-f8dcef`) plus an oracle-test
capture (`live-negatives-*`) start with letters, permanently outsorting every
timestamp name. Every latest-run consumer (harvest, redispatch staging,
tripwire active-run perception, ACP progress, the #843 /coord status surface)
was reading a month-old selftest dir. The go-live ceremony's cycle-1 "no
finished run" was true-but-blind — right for the wrong reason; only a night
with a REAL finished run could expose the difference (the strongest argument
yet for supervised e2e tests over green gates). Mitigation: three non-run
dirs quarantined (nothing deleted, README left); proper fix + regression lock
+ writer sweep = #881. Lesson shape: a namespace with semantics (runs_dir)
must be guarded at the READER (shape filter), because writers multiply.

### 2026-07-14 — Run-done signals: SUMMARY.txt is per-wave, never the done signal (migrated from #877 c.1903)

In plan-graph (M2) mode `SUMMARY.txt` is written/rewritten PER WAVE —
"Processed this run: 1 of 1 queued" reflects the CURRENT wave's task queue,
not the whole job. Detecting SUMMARY.txt existence as run-done fires
prematurely (a live watcher did exactly this on the seed run). TRUE done
signals: swap phase leaving CODE→REPORT/COMPLETE, `scorecard.json` appearing
(the driver's REPORT-phase artifact), or the AO returning on :5001 with
done.txt listing all tasks. Applies to any future run-watching, including the
#878 Operations dashboard's "is a run done?" logic — key on scorecard/phase,
never SUMMARY presence.

### 2026-07-14 — First-attempt no-change is the dominant time cost; retry machinery recovers it (migrated from #877 c.1905)

Two of the seed run's first three waves saw coder attempt 1 complete "clean"
(ExitCode 0, no timeout, ~524 s) while producing ZERO diff: wave 2
(add-about-section — retry 2/3 from a clean worktree recovered it → merged,
gate passed) and wave 3 (add-projects-list). Wave 1's cosmetic FIX pass also
produced no changes and correctly kept the prior merged version.

- **Resilience verdict: PASS** — nothing empty was merged or faked; the
  no-change detector + clean-worktree retry earns its keep; fail-safe
  direction (keep known-good) held.
- **Efficiency verdict: the tuning target** — each empty attempt burns ~9 min
  of 30B GPU time before the retry starts; on the seed run this crowded the
  23:00 battery window. Evidence: per-attempt agent logs recorded in
  `run-fleet-*.log` (e.g. `blairs-lab-add-projects-list-20260714-204037.c1.agent.log`),
  driver=acp phase=run.
- **DIAGNOSED same night (mid-run forensics, target-repo git history):** not a
  coder failure — **the tasks were already satisfied.** Wave 1's visual-fix
  pass (`796e40e`, 19:30, +83 lines to `public/index.html`) built the ENTIRE
  page — header, about section, AND the projects list — in one over-delivering
  pass. Downstream same-file waves then had nothing real to do: wave 3's
  attempts honestly produced no diff (then spun on completion-echo commands
  until the 45-step ceiling aborted the session — "ExitCode 0, no changes"
  masks an aborted-at-ceiling spin); wave 2's retry, under produce-something
  pressure, manufactured a junk edit instead (below). ROOT CAUSE is
  dimension-1 DECOMPOSITION GRAIN: three same-file edits invited wave-1
  over-delivery, which converted the remaining waves into no-ops.
- **Tuning candidates:** (a) an "already-satisfied" pre-check — before
  building, test the wave's contract against the current tree; skip honestly
  ("nothing to do — prior wave covered it") instead of burning 3 × ~9 min GPU
  attempts; (b) the no-change retry pressure can INDUCE low-value diffs (see
  the oracle-file edit below) — a retry prompt should permit "no change
  needed" as a first-class honest outcome.
  *(Tracked as **#1049**. Reference added 2026-07-22 by the ledger-candidate gate
  — both had been un-ticketed since this entry was written.)*
- **Wave-3 resolution (same night, closes the loop):** attempt 3 verified the
  requirements were already met — it wrote a scratch `test-verification.js`
  (checks: about-section present, exactly 3 project items), committed it, then
  deleted it in the next commit (`e930dd7` + `e3159f6`, merged as the wave).
  The PAGE stayed byte-identical (correct; no duplicate/embellished section —
  better discipline than wave 2), but the create-then-delete pair existed only
  to satisfy the produced-changes detector and exit the retry loop. **Pattern
  now confirmed across two waves: the machinery's demand for a diff converts
  honest "already done" into manufactured diffs** (wave 2: comment scribble in
  the protected oracle file; wave 3: ephemeral scratch script). Tuning
  candidate (b) is the fix's home - tracked as **#1049**. Wave 3 gate: PASSED (tree correct).
- **Note (semantics):** a wave producing no changes across all retries is
  NOTHING, not PARKED — and NOTHING is redispatch-ineligible. Tonight the
  required content EXISTS (built early by wave 1), so the job-level oracle
  should PASS at run end — the missing-section → honest-park path is NOT
  expected to trigger.

### 2026-07-14 — Coder edited the seeded job-oracle file; verdict integrity held structurally (seed run, wave 2)

Wave 2's merged commit (`afccf8c`) touched ONLY `tests/acceptance.job.test.mjs`
(+8/−3) — the seeded, "protected" job-level acceptance oracle. Forensics:

- **The edit was comment-only** — it rewrote the illustrative commented-out
  example inside the `__blarai_seed_skip` block (verified: zero non-comment
  changed lines). Its about-section work was already done (wave 1's fix pass),
  and the retry-from-clean-worktree pressure to produce a diff appears to have
  induced the coder to "improve" the one file it was told never to touch.
- **Why the verdict is safe anyway (verified in code, not assumed):** the job
  oracle's canonical bytes are authored by the 14B at PLAN time (cross-model —
  the 30B never writes it), ride the plan artifacts (task dict → swap-state,
  never the repo), and the driver grades the final integrated tree with
  **restore-before-grade semantics** — plan-carried bytes are written over
  whatever is on disk at the oracle path immediately before the run, prior
  disk state restored after (`shared/fleet/acceptance.py:2238` block; runner
  `swap_ops.real_run_job_oracle`; pinned-path allowlist
  `JOB_ORACLE_ALLOWED_PATHS`). The #690 per-task oracle has the parallel
  guard (`fleet-lib.ps1:2192` restore-before-gate, `verify-oracle.ps1`
  tamper-survival tests).
- **Ledger verdict:** the "protected" promise is enforced at judgment time,
  not at write time — a deliberate, sound design (don't trust the coder's
  tree; re-assert the oracle when it matters). Tonight is its first REAL
  (non-test) exercise: a coder DID write into the oracle file, and the
  protection held by construction. Residual: the junk edit pollutes the
  target repo's history — cosmetic, but it is retry-pressure evidence for
  tuning candidate (b) above - tracked as **#1049**.

### 2026-07-18 — B4 post-probe-fix park: the interactive-I/O testability ceiling (run 20260717-233441-bd, #944)

The #790 probe fix's A/B night moved B4 (flashcards-cli) from "parks early" to
"parks one task short of done": `import-probe.log ok=True` (the old
layout/import defect is CLEARED), 6 of 7 tasks merged, and the run finished
PARKED-HONEST[BUILD] on `implement-command-interface` — the quiz command-line
interface. #944 diagnosis, from the per-task fleet log:

- **All three best-of-3 candidates failed the py:test gate on the same wall.**
  The card's essence is an `input()`-driven interactive loop, and no honest
  test of that path can pass under a captured-stdin pytest gate as the coder
  writes it: candidate 1's direct test died on pytest's captured stdin
  (`OSError: reading from stdin while output is captured`) plus a
  test-isolation break (dependency tasks had pre-seeded the shared
  `flashcards.json`/`scores.json`, so its clean-store count assertions failed —
  3 cards where it expected 1); candidate 2 spun to the 10-turn no-edit cap and
  delivered no tests at all (pytest exit 5); candidate 3 drove the CLI via
  subprocess but piped no stdin, so `quiz` hit `EOFError` and returned 1.
- **ROOT CAUSE dimension: a coder-capability class, not a card trap** —
  testability-aware design for interactive standard-input I/O. The 30B builds
  the natural interactive implementation, then cannot test it. This is the
  Python analog of the WinUI `CS0246` ceiling: a repeatable, scaffold-
  addressable class, NOT the expected demonstrator behavior (that was the old
  import-probe park, now fixed).
- **Tuning candidates:** (c) the python scaffold / card guidance gains an
  interactive-I/O testability rule — route prompts through an injectable input
  function (or accept answers via args / piped stdin); tests drive input via
  monkeypatch or `subprocess.run(..., input=...)`, never a live terminal
  (C1 scaffold-library territory); (d) a test-isolation rule — tests point the
  app at a temp data path, never the repo-shared JSON store the dependency
  tasks already populated.
  *(Tracked as **#1036**, filed 2026-07-21 — three days after this entry, and only
  because the User-Operator asked. Reference added 2026-07-22.)*
- **Notes:** the spin cap fired twice tonight — the known stall class, already
  ledgered; no new evidence dimension. Honesty machinery held end-to-end
  (PARKED-HONEST, no false GREEN; parked work intact on
  `agent/implement-command-interface`).

## Run 20260720-230148-bd — B2 text-stats — GREEN (2026-07-21, first #987/#991-valid night)

- **DECOMPOSITION GRAIN** — clean: 4 build arms + acceptance on the card-authorised
  diamond, 4 context packs consumed, plan-graph mode, 0 interventions. Grain matched
  the card's intent exactly.
- **CHECK REALISM** — real end-to-end: job oracle passed on the integrated tree,
  guest clean-room agreed. No boilerplate checks observed in the run artifacts.
- **SCOPE FIDELITY** — no sprawl signal; B2 remains the clean card (24.9% wave-1
  share across its 15-run history, at the even split).
- **HONESTY LINES** — GREEN is exit-code-backed; the green-quality marker records
  GREEN-UNVERIFIED 1 (post-verification of the GREEN class pending its own pass).
- **ASSUMPTION QUALITY** — nothing notable declared or smuggled.
- **ACCEPTANCE-CRITERIA PINNING** — oracle import contract 4/4 modules, 1:1 with
  build arms — the #989-predictor shape that correlates with clean waves.
- **Notes:** 2,922s wall vs 1,899s the prior night (+54% on n=1 — first night under
  the #987 admission path and full candidate flow; watch, don't conclude). Evidence:
  `night-20260720-230001/scorecards/B2.scorecard.json`, run dir `20260720-230148-bd`.

## Run 20260720-235311-bd — B4 flashcards — PARKED-HONEST [VERIFY] (2026-07-21)

- **DECOMPOSITION GRAIN** — the 14B decomposed 6 tasks (5 build + acceptance),
  plan-graph, degraded=false: decomposition itself worked. **First full six-wave
  completion in B4's recorded history** — every integration gate + the layout gate
  PASSED; the park came only from the exam.
- **CHECK REALISM** — per-task and wave gates real and green; the JOB oracle is the
  broken seventh-night exam (`data_storage` called, never imported — #1008). The run
  was graded by an exam that cannot pass; **attribution VERIFY, not BUILD — the
  first honest attribution night** (#965's arc landing in practice).
- **SCOPE FIDELITY** — the import contract surfaced to wave 1 still named four
  foreign modules and omitted wave 1's own (`swap-progress.log`, verbatim — the
  #989 mechanism live); wave gates held regardless this night.
- **HONESTY LINES** — PARKED-HONEST + VERIFY + guest-agree: the machinery told the
  truth end to end. No false GREEN pressure anywhere in the artifacts.
- **ASSUMPTION QUALITY** — nothing notable.
- **ACCEPTANCE-CRITERIA PINNING** — root cause of seven parked nights: the contract
  omitted `data_storage` because the generated oracle forgot it. Fixed forward by
  the card-authored plan + oracle (main `4b847d20`); from the next night B4 grades
  against a deterministic 1:1 contract.
- **Notes:** operator-caused candidate kill at ~00:31 (wrong-clock misdiagnosis —
  #1016 corrected+closed, rule in session memory) was absorbed by the
  no-result-envelope→stdin fallback, **its first live proof**; the task then merged.
  Post-run the wrapper's postlude crashed before banking/report (StrictMode leak,
  #1019, fixed `824c35c` same hour; lean pass hand-banked; morning report
  reconstructed). Wall 7,134s. Evidence: `B4.scorecard.json`, run dir
  `20260720-235311-bd`, `oracle-qa.json` (coverage 0/6, 2 regen rounds, the blind
  import-contract checker now #1015).

## Run 20260721-111715-bd — Bill Splitter e2e (Candidate 2, #877) — PARKED-HONEST [BUILD] (2026-07-21, LA-present front)

- **DECOMPOSITION GRAIN** — best interactive card on record: 1 build task +
  acceptance, reached after 2 operator revisions (the decomposer's first offer for
  the check-enriched goal was 3 tasks; the plain morning goal drew 1 — one added
  check-sentence doubled the offered build grain, a dimension-1 instrument reading).
  Matches the day's research read (docs/research/ui-seam-and-task-grain-research-
  2026-07-21.md): one-file tool → one task.
- **CHECK REALISM** — 7 machine-gated checks including the LA's result-reaches-the-
  page check (in the ASK, so first-class — the revision wall cannot add gated
  checks, learned this morning). The authored exam then operationalized that check
  ONE LAYER BELOW the seam it names (`validateAndDisplay` returns the right string
  ≠ the string lands on the page) — the exam-demotion finding, structural fix
  #1025. The executability floor supplied the real user-side check instead and
  caught what the demoted check could not.
- **SCOPE FIDELITY** — no sprawl signal; 2-task plan, single build wave; exam
  import contract 1:1 with build tasks (the #989-predictor clean shape).
- **HONESTY LINES** — strong end to end: layout gate green, then the floor served
  the page, found the boot failure, ran ONE targeted fix cycle, failed, and refused
  verified-done. Oracle recorded `not-run`; ticket #1026 stays OPEN; design
  critique honestly reported "unavailable — judge for yourself"; verdict
  PARKED-HONEST [BUILD]. No false-GREEN pressure anywhere in the artifacts.
- **ASSUMPTION QUALITY** — 4 declared, all sound (resizable window, decimals, no
  history, friendly messages); the no-history call correctly fenced scope.
- **ACCEPTANCE-CRITERIA PINNING** — every awkward case the LA named pinned as a
  gated check; both operator revision instructions recorded on the spec and visible
  to the exam author (the clarification→exam channel works — by name and intent,
  demoted in mechanism, see CHECK REALISM).
- **Notes:** the park cause is the delivery-seam class at the SERVING layer: the
  page references `/src/validation.mjs`; the served root does not expose it —
  logic exists, imports resolve, the user gets nothing (third instance of the
  class today; the planted zero-people trap never got its moment). First live
  `/dispatch revise` exposed the bare-name mint defect (approve refused by the
  forbidden-root guard — the guard working; fixed same hour, `9c972dcc` + lock).
  Revise-model edit quality: asked to MERGE tasks → delivered a RENAME (round 1);
  explicit removal phrasing worked (round 2) — tuning candidate for the #820
  revise persona. Critique cadence 13–15 min/round with one 35+-minute round
  (proven alive by CPU-delta measurement, not narrative; watcher scope widened
  twice — per-candidate worktrees remain a named blind spot). Fix-cycle efficacy
  0/1 on a serving-layer boot error (n=1). Coordinator redispatch-DRAFT
  observable: checked post-restore under its own record. Wall ~2h45m
  front-to-scorecard. Evidence: run dir `20260721-111715-bd`, `scorecard.json`
  (oracle_status not-run), #877 c.2335, #1026 c.2336, the seeded exam
  `bill-splitter-r2/tests/acceptance.job.test.mjs`.

## Run 20260721-172005-bd — B4 flashcards — GREEN (2026-07-21, daytime run-1 of the #989 A/B)

- **DECOMPOSITION GRAIN** — card-authored plan (#1008 debut in daylight): 5 build
  arms + acceptance, plan-graph, 6/6 wave gates PASSED, zero interventions.
  **First GREEN in B4's recorded history.**
- **CHECK REALISM** — the card-authored exam's deterministic 1:1 import contract
  ran for the first time: job oracle passed on the integrated tree, guest
  clean-room AGREE. The exam that graded this run names `data_storage` — the
  module the old generated exam forgot for seven straight nights.
- **SCOPE FIDELITY** — **wave-1 sprawl ABSENT on pre-fix code**: `store-cards`
  authored exactly its contract (`app/data_storage.py` + test + `__init__`,
  +168 of 1,018 build lines = 16.5% vs 20% even split; every task ADDED only its
  own module). The c.2299 predictor (1:1 contract coverage → clean wave-1)
  validated live: the #1008 exam repair alone removed B4's EXPRESSION of the
  wave-1 defect. #989's ceiling remains the systemic guardrail for cards without
  1:1 contracts; run-2's question becomes non-regression (a clean card must stay
  clean under the ceiling), not sprawl reduction.
- **HONESTY LINES** — GREEN is exit-code-backed; green-quality band B
  (unused-starter-code residue — see Notes); GREEN-UNVERIFIED class marker,
  consistent with B2's standing marker.
- **ASSUMPTION QUALITY** — nothing notable in the artifacts.
- **ACCEPTANCE-CRITERIA PINNING** — oracle import contract 6 modules across
  5 build tasks + acceptance, 1:1 — the #989-predictor clean shape, now by
  construction (card-authored) rather than by luck.
- **Notes:** **CONDITION CAVEAT — dirty sandbox.** The 17:19 launch skipped the
  nightly script's archive+fresh-init step, so the run started on last night's
  completed six-wave build (its history begins at the 07-20 23:01 init). All six
  `app/` modules + tests were freshly ADDED by this run's tasks — authorship is
  clean — but last night's leftovers were visible to the coder throughout and are
  the likely source of the green-quality residue; the record wall (4,790s vs
  7,134s last night) reads with that caveat. The #989 A/B baseline role therefore
  moves to tonight's 23:00 nightly (fresh sandbox, pre-fix); run-2 =
  `20260721-184705-bd` (fresh sandbox, `efb7f17e`). Versions: blarai `d4818cf6`
  (pre-#989, deliberate — c.2333 run-1). Evidence:
  `state/battery/20260721-171936/B4.scorecard.json`, run dir
  `20260721-172005-bd`, archived sandbox
  `state/battery/20260721-171936/repos-archived/battery-b4-flashcards-cli`.

## Run 20260721-184705-bd — B4 flashcards — GREEN (2026-07-21, daytime run-2: first run under the #989 scope ceiling)

- **DECOMPOSITION GRAIN** — same plan shape as run-1 (5 build arms + acceptance,
  plan-graph, 5 packs): the 14B decomposed identically under the ceiling —
  plan-parity for the A/B held.
- **CHECK REALISM** — job oracle passed on the integrated tree; guest clean-room
  AGREE; card-authored 1:1 contract (deterministic, data_storage present).
- **SCOPE FIDELITY** — **the non-regression proof the run existed for**: every
  build task authored exactly its own contracted module (store-cards +148,
  import-deck +270, add-card +132, quiz +241, track-scores +232 source lines;
  wave-1 share 14.5% vs 20% even split, run-1's was 16.5%). The ceiling text
  verified IN the wave-1 production prompt ("SCOPE — this task builds ONLY its
  own contracted deliverable(s)…" — the first root task ever to receive it).
  `scope_sprawl` finding correctly ABSENT from evidence. Plan-time coverage
  check silent, as designed on a 1:1 contract.
- **HONESTY LINES** — GREEN exit-code-backed, GREEN-UNVERIFIED class marker;
  green-quality band B (same unused-starter-code residue as run-1 — on a FRESH
  sandbox, which relocates that residue's origin to the seeded skeleton, not
  leftover code; softens run-1's caveat and names a scaffold-hygiene tuning
  candidate - tracked as **#1048**).
- **ASSUMPTION QUALITY** — nothing notable.
- **ACCEPTANCE-CRITERIA PINNING** — 1:1 by construction (card-authored exam).
  Observation, honest not alarming: the acceptance-tests task authored +0 —
  under the ceiling it declined to recreate the already-seeded protected exam;
  wave-5 gate and job oracle passed on the seeded one. (Run-1's acceptance task
  wrote a +233-line duplicate criteria file. The +0 is arguably the more correct
  behavior; noting for the next B4 read.)
- **Notes:** FRESH sandbox (this session re-inited per the nightly script's
  pattern after finding run-1's launch had skipped it). Versions: blarai
  `efb7f17e` (the review-complete #989 branch tip; wrapper hard-verified HEAD
  before launch). Wall 5,546s vs run-1's 4,790s (run-1 was dirty-sandbox-
  advantaged) and last night's fresh-sandbox 7,134s. Verdict for the c.2346
  auto-merge trigger: **run-2 is CLEAN — machinery worked, non-regression
  proven; merge proceeds on the branch-gate result.** A/B closes with tonight's
  23:00 nightly (fresh, pre-fix) as the condition-matched baseline. Evidence:
  `state/battery/20260721-184637/B4.scorecard.json`, run dir
  `20260721-184705-bd`, sandbox history at `projects/battery-b4-flashcards-cli`.

## Run 20260721-230126-bd — B2 text-stats — GREEN (2026-07-22, nightly; the A/B's control card)

- **DECOMPOSITION GRAIN** — 4 build arms + acceptance, plan-graph, 4 packs; waves
  1/2/3/4 all PASSED their integration gates. Standing B2 shape, unchanged.
- **CHECK REALISM** — job oracle passed on the integrated tree; guest clean-room
  certificate PASSED and AGREE.
- **SCOPE FIDELITY** — nothing notable; B2 is the card the #989 c.2299 audit
  measured clean across 15 runs (24.9% wave-1 share vs a 25% even split).
- **HONESTY LINES** — GREEN exit-code-backed; GREEN-UNVERIFIED class marker;
  interventions 0, FALSE-DONE 0, stalled 0.
- **ASSUMPTION QUALITY** — nothing notable.
- **ACCEPTANCE-CRITERIA PINNING** — unchanged from the standing B2 contract.
- **Notes:** wall **4,769 s** against the 2026-07-20 night's **2,922 s (+63%)**.
  **This delta is recorded, NOT diagnosed — it crosses an unmeasured variable.**
  `samples_consumed` was **2** tonight and **-1** on 07-20, and -1 is the documented
  sentinel meaning "no task drew more than one candidate, OR not measured" — the two
  are indistinguishable from that signal alone (`_samples_consumed_from_run_dir`
  docstring; the PowerShell sampler only logs when a task resamples). So tonight's run
  did at least one extra full generation, which is *consistent with* part of the delta
  and is NOT evidence for it. Per-task walls from sandbox commit timestamps, tonight
  vs 07-20: `tokenize` 13m15s / 4m28s · `word-frequencies` 5m36s / ~5m17s ·
  `neighbor-pairs` 7m51s / 8m32s · `report` 28m41s / ~12m49s · `acceptance-tests`
  20m12s / 13m14s — concentrated in `tokenize` and `report`. Versions: blarai
  `d4818cf6` (pre-#989). Evidence: `state/battery/night-20260721-230001/
  scorecards/B2.scorecard.json`, run dir `20260721-230126-bd`.

## Run 20260722-002149-bd — B4 flashcards — GREEN (2026-07-22, nightly; **the #989 A/B's condition-matched BASELINE**)

- **DECOMPOSITION GRAIN** — 5 build arms + acceptance, plan-graph, 5 packs; wave 1 =
  `store-cards` alone, wave 2 = `import-deck` + `add-card`. **Plan parity with BOTH
  daytime runs** — the three A/B legs decomposed to the same shape, which is what makes
  the comparison a comparison rather than three experiments.
- **CHECK REALISM** — job oracle passed on the integrated tree; guest clean-room
  AGREE; the #1008 card-authored 1:1 contract (deterministic, `data_storage` present).
- **SCOPE FIDELITY** — **the A/B's missing leg, now measured**: wave-1 `store-cards`
  authored **+147 of 938 build lines = 15.7%** against a 20% even split (per-task:
  store-cards +147, import-deck +229, add-card +143, quiz +129, track-scores +290).
  Measured with the same validated instrument as the other two legs.
- **HONESTY LINES** — GREEN exit-code-backed; GREEN-UNVERIFIED class marker;
  interventions 0, FALSE-DONE 0, stalled 0. `green_fingerprint:
  oracle_coverage=unknown (no traceability map)`.
- **ASSUMPTION QUALITY** — nothing notable.
- **ACCEPTANCE-CRITERIA PINNING** — 1:1 by construction (card-authored exam, #1008).
- **Notes:** **FRESH SANDBOX CONFIRMED FROM THE WRAPPER'S OWN LOG** ("archived previous
  battery-b4-flashcards-cli" → "fresh sandbox: battery-b4-flashcards-cli", 23:00:47-48)
  — the condition run-1 lacked and the reason the baseline role moved here (c.2349).
  Versions: blarai `d4818cf6` (pre-#989, the baseline condition). Wall **4,879 s**
  vs the 07-20 night's 7,134 s. `samples_consumed -1` — no task drew a second
  candidate. **First B4 GREEN on a NIGHTLY in its recorded history** (run-1/run-2 were
  daytime). Evidence: `state/battery/night-20260721-230001/scorecards/B4.scorecard.json`,
  run dir `20260722-002149-bd`.

### The #989 A/B, closed (all three legs, one instrument)

| Leg | Sandbox | blarai | Verdict | Wave-1 share | Wall |
|---|---|---|---|---|---|
| run-1 `20260721-172005-bd` | **dirty** | `d4818cf6` pre-fix | GREEN | 16.5% | 4,790 s |
| **baseline `20260722-002149-bd`** | **fresh** | `d4818cf6` pre-fix | GREEN | **15.7%** | 4,879 s |
| run-2 `20260721-184705-bd` | fresh | `efb7f17e` **with fix** | GREEN | **14.5%** | 5,546 s |

Even-split reference 20%. **Reading:** against the condition-matched baseline (fresh,
pre-fix) the ceiling moved wave-1 share 15.7% → 14.5%, a 1.2-point improvement on a card
whose #1008-repaired exam had ALREADY removed the defect's expression (c.2349) — so the
A/B's honest claim is **non-regression plus a small real improvement**, not the large
sprawl reduction the ticket originally predicted. GREEN survives the ceiling. The
guardrail's value still waits on cards whose exams are not 1:1.

Wave-1 shares measured by one instrument across all three legs (reproduces the two
previously hand-computed rows exactly: run-1 +168/1018 = 16.5%, run-2 +148/+270/+132/
+241/+232 = 1023 = 14.5%). The earlier hand method drifted 1–2 lines per task by counting
non-source data files (`flashcards.json`, `scores.json`, `test_cards.json`); source-only
counting reproduces both published rows exactly.

**Green-quality band B, now on its third consecutive B4 run** (run-1 dirty, run-2 fresh,
baseline fresh) — "unused starter code that was never cleaned up." Three runs across both
sandbox conditions and both code versions puts the origin definitively in the **seeded
skeleton**, not in leftover code. Scaffold-hygiene tuning candidate; not a coder defect.
*(Tracked as **#1048**, filed 2026-07-22 — again only because the User-Operator asked.
LA decision the same day: build a NEUTRAL seed; exempting seeded paths from the jury was
explicitly rejected, because suppressing a true finding to raise a score inverts what the
instrument is for.)*

## Run 20260722-122919-bd — B1 expense-tracker (chain, 4 tasks) — GREEN (2026-07-22, #1035 credential re-validation, daytime targeted)

First of three #1035 re-validations: retired cards' "reliable passer" credentials, earned under
the pre-repair instrument (blind oracle-QA #1015, pre-#989/#1008), re-checked on merged main.
GREEN, 2,743 s, **0 interventions**, plan-graph 4-task chain, `samples_consumed` -1. Credential
HOLDS. **Condition record (lesson 225):** the sandbox was measured DIRTY before launch — 10
commits, 4 `agent:` from the 2026-07-15 run — and the wrapper's archive-by-rename + `git init`
made it fresh by construction. Had this been launched as `python -m tools.dispatch_harness.battery
--jobs B1` (which the #1035 plan text literally named) it would have built on the inherited
commits; the archive+init lives only in `run-battery-night.ps1`, not the harness (now documented:
`docs/runbooks/battery_cadence_and_targeted_runs.md`). This run's postlude then CRASHED on the
#1045 empty-array unroll (no morning report; a 12.5 GB AO stranded) — the first live instance of
that defect, fixed same day.

## Run 20260722-140757-bd — B6 inventory-cli (plan-graph, 8 tasks) — GREEN (2026-07-22, #1035, daytime targeted)

Second re-validation, and the sharpest card: B6 is the one that flipped 0%→44% when its contract
shape changed, so it is the most sensitive to exactly the kind of change #989's scope ceiling makes.
GREEN, 5,947 s, **0 interventions**, 8-task plan-graph (`degraded:false`), `samples_consumed` -1.
Credential HOLDS. **First targeted run to ride the #1045 postlude fix** — morning report written,
postlude clean (direct A/B against B1's crash). Sandbox was dirty pre-run (8 `agent:` commits),
archived+reinit by the wrapper.

## Run 20260722-165617-bd — B7 util-trio (independent, 3 helpers + acceptance) — PARKED-HONEST [BUILD] (2026-07-22, #1035, daytime targeted)

Third re-validation, and the most instructive. All three CLI helpers (slugify / unit-converter /
password-generator) BUILT and MERGED; both wave integration gates PASSED (verify+node tests). The
JOB-level acceptance exam failed on ONE assertion: it demanded the unit converter throw the EXACT
string `'Invalid unit conversion'`, while the coder correctly threw the more descriptive
`'Invalid unit conversion: units must be of the same type'` (`src/unit-converter-helper.js:93`) —
Node `assert.throws({message})` is exact-equality, so a correct implementation was convicted on
error-message WORDING the goal never specified. **Not a coder regression; a 14B-authored exam
inventing a contract the requirements never named** — the #1043 class, now demonstrated changing a
real verdict rather than driving a soft regeneration. B7 has no arm builder, so its exam is
14B-authored and varies run-to-run; this is N=1 against a variable exam. Live instance recorded on
#1043 (c.2392) with a concrete fix: for a `throws` expectation, assert that it throws, never an
exact invented message. 3,104 s, 0 interventions, node grading DID execute here (the caveated #894
partial-grading was not the limiter). AO stopped post-run (#1053).

**#1035 conclusion (3/3 run):** 2 of 3 credentials (B1, B6) cleanly HOLD on the repaired
instrument; B7's PARK is attributable to exam over-specification (#1043), not lost coder
capability. Comparability held across all three — S1's go-live (advanced_intake=true) does not
touch the battery instrument, because the advanced-intake rulers are suppressed for card-driven
dispatches (`_is_card_driven`, #1042), verified pre-launch.

## Run 20260722-230151-bd — B2 text-stats — GREEN (2026-07-23 nightly; the merge-train baseline's control card)

- **DECOMPOSITION GRAIN** — standing B2 shape (4 build arms + acceptance, plan-graph), all wave
  gates PASSED, 0 interventions.
- **CHECK REALISM** — job oracle passed on the integrated tree; guest clean-room AGREE.
- **SCOPE FIDELITY / HONESTY / ASSUMPTIONS / PINNING** — nothing notable; GREEN exit-code-backed,
  `samples_consumed` -1 (no resample).
- **Notes:** wall **4,170 s** vs the prior night's 4,769 s (−12.6%, n=1 — recorded, not
  diagnosed). Versions: blarai `2d694ed0` (pre-merge-train — the condition the baseline needed).
  Lean pass 4 banked on the lean counter; the full-campaign counter stayed 3/5. Evidence:
  `night-20260722-230001/scorecards/B2.scorecard.json`, run dir `20260722-230151-bd`.

## Run 20260723-001147-bd — B4 flashcards — PARKED-HONEST [BUILD] (2026-07-23 nightly)

- **DECOMPOSITION GRAIN** — plan-graph; wave 1 (`store-cards`) merged with its gate PASSED,
  wave 2 (`import-deck` + `add-card`) entered build; the park arrived at the integration seam.
- **CHECK REALISM** — `failure_class: INTEGRATION-SEAM`, fingerprint `import-probe unresolved:
  app.card_entry, app.quiz_engine, app.score_tracker` — three contract modules unresolved on the
  integrated tree; job oracle honestly `not-run`, guest honestly `not-run (host-oracle-not-run)`.
  This is the REPAIRED probe ruling (post-#790 CPython-mirroring semantics), not the retired
  false-park class: the modules genuinely are not importable because their tasks did not land.
- **HONESTY LINES** — PARKED-HONEST + not-run oracle + guest not-run: truthful end to end;
  0 interventions, FALSE-DONE 0.
- **Notes:** wall **3,337 s** (a short park night — the run ended at the probe, not at a
  timeout). B4 remains the intermittent-ceiling card: GREEN on 3 of its last 5 nights, parked
  tonight one run after four consecutive GREENs. **CONDITION CAVEAT:** a review-verification
  pytest sweep from the overnight session's builder overlapped part of this run's window on CPU
  — the wall reads with that concurrent-load caveat; the verdict is load-independent (module
  absence is not a timing artifact). Versions: blarai `2d694ed0` (pre-merge-train baseline
  condition). Evidence: `night-20260722-230001/scorecards/B4.scorecard.json`, run dir
  `20260723-001147-bd`.

## Run night-20260723-014251 (B2) — GREEN (2026-07-23, #1058 validation window, daytime-cadence targeted)

The #1058 instrument-validation leg: proves the wrapper launch path runs clean under the merged
sandbox-freshness gate. **GREEN, 3,899 s, 0 interventions, oracle passed, guest AGREE** — and the
gate's first wrapper-path pass recorded its condition into the scorecard: `sandbox_freshness:
fresh / sandbox_commit_count: 1` (fresh-by-construction, now fresh-by-evidence). Paired with the
same night's live REFUSAL proof (real CLI, throwaway dirty fixture, 0 s spent, condition stamped
dirty — #1058 c.2430), the control is validated in both directions. Versions: blarai `d1496204`
(post-merge-train tip — the one change in window). Side config banked 1/1 on itself; the default
campaign counters verified untouched (3/5). The wrapper deliberately left the AO up per the
manual-run ownership rule; the overnight session stopped it through the audited stop-assistant
seam (11.5 GB freed) before the next window — the #1053 class, handled without incident.

## Run night-20260723-030020 (B4) — PARKED-HONEST [BUILD] (2026-07-23, #1049 measurement window, daytime-cadence targeted)

The #1049 window's measurement leg (already-satisfied pre-check + NO-CHANGE-NEEDED escape, the
one change in window). **Non-interference proven:** fresh sandbox stamped by the #1058 gate
(`sandbox_freshness: fresh`), clean completion, runner exit 0, honest park. **The park is not
attributable to #1049:** PARKED-HONEST[BUILD] at the IDENTICAL fingerprint as the pre-change
baseline night — `import-probe unresolved: app.card_entry, app.quiz_engine, app.score_tracker` —
1,418 s vs the baseline's 3,337 s (faster to the same wall; n=1, unattributed). The honest-skip
and no-change occasions did not arise this run; the features' locks remain the standing evidence.
**Diagnostic worth its own look:** B4 has parked twice consecutively on the SAME three unresolved
contract modules — recurring, not noise. *(Originally read "a recurring 14B plan/contract shape";
that attribution is RETRACTED — the contract is identical to the GREEN nights'. See the mechanism
correction at the end of this file and #1066 c.2437.)* Versions: blarai `7b06ddf0` (the #1049 window tip). Evidence:
`night-20260723-030020/scorecards/B4.scorecard.json`.

## Run night-20260723-033913 (B4) — PARKED-HONEST [BUILD] (2026-07-23, #1036/#1048 scaffold window, daytime-cadence targeted)

The scaffold window's measurement leg (neutral seed + testability rules + the acceptance.py
prompt companion — the one change in window). **Non-interference proven:** fresh sandbox
stamped, clean completion, honest park — at the IDENTICAL fingerprint as BOTH pre-change runs
(`import-probe unresolved: app.card_entry, app.quiz_engine, app.score_tracker`), 2,401 s.
**The band-B readout carries forward honestly:** no GREEN → no green-quality jury read; the
predicate is B4's next GREEN under the neutral seed. **The night's sharpest diagnostic, now at
three consecutive occurrences across three code conditions (baseline `2d694ed0`, #1049
`7b06ddf0`, scaffold `5aecaa84`): B4's 14B-authored plan/contract names the same five modules
every run and the coder work does not land three of them. Invariant to every change shipped
tonight; wants a daylight look at the wave/task outcomes across the GREEN→PARK boundary.
Routing to the #1043/#1054 exam-authoring thesis is CONDITIONAL on where the root cause lands —
the 07-23 forensics puts it in the build/repair machinery, not in exam authoring (#1066
c.2446).** Versions: blarai `5aecaa84`. Evidence:
`night-20260723-033913/scorecards/B4.scorecard.json`.

> **MECHANISM CORRECTION (2026-07-23 morning, #1066 c.2437 — applies to this row and to the
> #1049-window row above).** This row originally read "a plan-authoring shape flip that began at
> the 07-22 nightly (the two prior nights' GREENs used a different module vocabulary:
> store_cards/import_deck/add_card/quiz/track_scores)". **That mechanism is RETRACTED**: it
> compared task SLUGS on the GREEN nights against MODULE names in the park fingerprint. Artifact
> truth (`import-probe-targets.json` + `decompose-diagnostics.json`, GREEN run `20260722-002149`
> vs park run `20260723-001147`): the 5-module contract (card_entry, data_storage, deck_import,
> quiz_engine, score_tracker) and the 6 task slugs are **identical on both**. The GREEN night's
> probe resolved all five; the park nights fail on the same contract's last three. The plan did
> not change — the coder stopped LANDING add-card/quiz/track-scores' modules. Established since:
> `add-card` parked as NOTHING in wave 2 (dependents skipped), and the fix-cycle's re-dispatch
> was refused as `[skip] add-card (already processed in this run)`. Diagnosis continues on #1066;
> the measured facts in this row (three occurrences, identical fingerprint, invariance to every
> change in window) are unaffected — only the mechanism attributed to them was wrong.

## Run 20260723-104107-bd — B4 flashcards — GREEN (2026-07-23, #1066 nul-clearance verification, daytime targeted)

The #1066 verification leg: after the 2026-07-23 forensics separated B4's three-park chain into
two failure classes, this run tests the ONE cleared variable — the leaked `nul` worktree removed
at ~10:07 (#1073). **GREEN, 3,793 s, 0 interventions, degraded:false, `samples_consumed` 2.**
All five build tasks MERGED (store-cards, import-deck, add-card, quiz, track-scores); four wave
gates PASSED (verify+python tests); **job acceptance oracle PASSED (`tests/test_job_acceptance.py`,
8 passed).** Versions: blarai `eb834a59` (post-restore main tip); the side config banked 1/1 on
itself and the default campaign counters were verified UNTOUCHED (3/5, jobs B2+B4) — self-unregister
scoped to the default config, so the 23:00 nightly stayed Ready (verified before and after).

**The decisive #1066 observation — Class B CLEARED.** `add-card` executed as a normal ~7-minute
task (TASK-START 11:17:22 → TASK-END 11:24:14, MERGED) instead of dying in one second on
`Could not create the isolated workspace`, which is how it failed on the two parked nights
(`20260723-030159`, `-034134`) with the leaked directory present. The workspace-creation failure
class is attributable to the leaked `nul` file and cleared by removing it.

**Class A did NOT reproduce on a clean run.** The nightly's silent-commit-loss (#1074) needs the
specific git-failure condition (probably the `nul` file itself) to fire; a clean sandbox produced
no empty build, so #1074/#1075 stay latent — confirmed-latent, not confirmed-fixed. Do not read
this GREEN as those defects resolved (the config's own `notes` said so up front); the durable fix
is #1073, still open.

**#1049 fired live here** — a bonus the overnight #1049 window run never got to observe: `add-card`'s
downstream `acceptance-tests` task was honestly SKIPPED by the already-satisfied pre-check (the job
oracle passed on the integrated tree BEFORE wave 5 dispatched — `exit 0; 8 passed in 0.22s` — no
coder candidate spent). The #1049 escape hatch is now demonstrated on a real GREEN, not just its
unit locks.

**Band-B readout UNBLOCKED.** #1048's predicate was "B4's next GREEN under the neutral seed"; this
is it. The green-quality jury read can now run on this GREEN archive (`run dir 20260723-104107-bd`).
AO left up post-run (#1053) and stopped through the audited stop-assistant seam (~10.9 GB freed).
Evidence: `state/fleet-runs/20260723-104107-bd/scorecard.json`.

---

## Run 20260723-165716-bd — B4 flashcards — GREEN (2026-07-23, #1074 fail-loud validation, daytime targeted)

**Purpose, and the limits stated BEFORE launch so the read could not be fitted afterwards.** This
run validated **#1074** (fail-loud git capture), merged earlier the same evening to agentic-setup
`3ffbb13`. The side config `battery-1074-failloud-b4-20260723.json` recorded up front that a clean
run **CANNOT** prove the fix works — a healthy run never executes `Resolve-CommitCapture`'s failure
branches — and that what it CAN establish is the absence of a **false-alarm regression**, which is
the specific risk the change carried: it converts previously-silent non-zero exits into loud errors,
and `git commit` legitimately exits non-zero on the honest "nothing to commit".

**Measured.** Verdict **GREEN**. Wall clock **3,878.08 s** (battery night `night-20260723-165520`,
fleet run `20260723-165716-bd`, started 23:56:11Z, finished 2026-07-24T01:01:08Z). `packs_consumed`
4, `interventions` 0, `samples_consumed` **-1** (the no-resample sentinel, not a count). Four build
tasks MERGED — `import-deck` (17:23:32), `add-card` (17:37:38), `quiz` (17:51:48), `track-scores`
(17:59:31), all local. Job oracle passed; `#1049`'s already-satisfied pre-check fired again and
honestly skipped the remaining task without spending a coder candidate.

**The #1074 finding: zero false alarms.** Grep across the run journal for `CAPTURE FAULT`,
`ERRORED`, `BASELINE UNRESOLVABLE` and `Nothing to merge` returns **0**. Every task that produced
work was classified as producing work. The discrimination that IS the fix — read the index, attempt
a commit only when it holds staged paths, so the honest no-op never enters the failure channel —
held under live conditions across four consecutive tasks. **This is what the run was for and it is
the only claim it supports.**

**`add-card` MERGED.** The task that parked three consecutive times and set off the whole #1066 →
#1073/#1074/#1075/#1076 chain built and merged normally, for the second consecutive GREEN. Combined
with the morning's `nul`-clearance run this is two clean B4 GREENs in one day on a card that had
parked three nights running.

**What this run does NOT establish, restated because a GREEN invites over-reading.** It says nothing
about whether #1074's failure branches work — that rests entirely on the executed toggle-off
(reverting the capture block took the lock from 152 passed to 29 failed on *behavioural* cases, not
source greps) and on the D-case matrix. It also says nothing about #1075 or #1076, which were
deliberately NOT merged into this run's condition: one change per RUN, and both remain on branches
awaiting their own attribution windows. Do not read this GREEN as those defects resolved.

**Cadence hygiene verified before and after.** Default campaign `state/battery-campaign.json`
UNTOUCHED at 3/5, jobs B2+B4. `BlarAI-M2-Battery-Nightly` State=Ready with a future NextRunTime
(23:00) both sides of the run — self-unregister is scoped to the default config, and this used a
side config. Sandbox freshness true by construction: the wrapper archived the previous
`battery-b4-flashcards-cli` and re-initialised before dispatch (16:56:11). Known residual: `-Now`
leaves the AO up afterwards (#1053) — the launcher log records `this run claimed no AO (manual -Now
run) - leaving the assistant running`.

Evidence: `state/battery/night-20260723-165520/scorecards/B4.scorecard.json`,
`state/fleet-runs/20260723-165716-bd/journal.log`.

*(Placement note: the file's §"Run entries (newest first)" begins at the top, but the two 2026-07-23
runs are appended at the end following the immediately preceding entry's precedent, and kept
adjacent so the day reads together. The convention drift is recorded rather than silently
reorganised.)*

## Run 20260723-190434-bd — B4 flashcards — GREEN (#1076 evidence-preservation validation)

**Supervised daytime targeted run**, side config `state/battery-1076-evidence-b4-20260723.json`,
launched 19:01:42 PDT via `run-battery-night.ps1 -Now` (pwsh). Verdict **GREEN**. Five of six tasks
merged; `acceptance-tests` honestly SKIPPED as already-satisfied (#1049) — the job-acceptance oracle
passed on the integrated tree *before* wave 5 dispatched, so no coder candidate was spent, and the
skip carries its evidence (`exit 0; 8 passed in 4.23s`). All four wave integration gates passed.
Job acceptance passed: `exit 0; 8 passed in 4.75s`. Wall clock **5685.3 s** at the battery scorecard
(**5477.0 s** at the fleet-run scorecard; the delta is wrapper overhead — archive, sandbox re-init,
model restore). `packs_consumed` 4, `interventions` 0, `redecompose_spent` 0.

Per-task wall: `store-cards` 16.2 m · `import-deck` 16.0 m · `add-card` 13.9 m · `quiz` 24.9 m ·
`track-scores` 16.0 m. `quiz` ran long because candidate 1 hit the turn cap (`spin: 10 turns with no
edit after work began`) — work kept, gate decided the merge, which is the harness behaving as
designed rather than a fault.

**Zero fault markers.** `grep -rniE "capture fault|ERRORED|nothing to merge|no changes to commit"`
over the entire run directory returns nothing, run twice at different points. That is the #1074 +
#1076 happy-path result: the fail-loud git capture introduced no false-alarm regression across five
live task dispatches, and appending the per-task log did not break any consumer.

**THE METRIC THIS RUN WAS WATCHING — and it behaved as predicted in the falsifiable direction.**
`samples_consumed` is **-1** with `not_measured: ["samples_consumed"]` (the no-resample sentinel).
The side config stated BEFORE launch that #1076's F1 moves this figure UP for any run containing a
fix cycle — under truncation only the last attempt's Best-of-N line counted, under append both do —
and that *a clean run with no fix cycle should show no change at all, which is itself the useful
control*. No fix cycle ran; the figure did not move. The prediction was written where it could have
been falsified and was not.

**CONDITION DEFECT — the stated condition was WRONG, and this run cannot be cited for #1076's
agentic-setup half.** The battery executed agentic-setup from the primary checkout
`C:/Users/mrbla/agentic-setup`, parked on `fix/1074-fail-loud-git-capture` @ `84724f8`, NOT on main
(`e929975`). Verified with `git merge-base --is-ancestor`: `84724f8` IS contained in main, but
`16e0ef5` — #1076's agentic half, "carry git's own message off the worktree-add failure path" — is
NOT an ancestor of `84724f8`, and nor are `d2412ad` / `512e232` / `7aee51a`. The BlarAI half WAS
present (the harness runs from BlarAI main `231374d5`), and that is the half carrying the
`swap_ops.py` append/byte-offset work this run existed to exercise. The absent commits are
worktree-add **failure**-path plus tests and docs, which a clean run never reaches, so their absence
is inert here — but **#1076's agentic-setup half still owes a window**, and the side config's stated
condition is corrected on #1076 c.2523 rather than quietly left standing.

**`add-card` MERGED again — third consecutive GREEN for the card that parked three nights running.**
It built a real `app/card_entry.py` with its contracted exports. **It did so WITHOUT #1075**, which
was deliberately not merged into this condition, so #1075's fix-cycle prompt-contradiction repair is
NOT what unblocked it and must not be credited with it. What actually explains the original #1066
parks remains unestablished.

**One-change-per-RUN audited, not assumed.** #1043 merged at 16:27:45 and is NOT dormant — it is
gated only by the pre-existing `BLARAI_ORACLE_QA` — so it sat inside both of today's validation runs,
each of which claims a single variable. Checked whether that falsifies them: it does not. A
card-driven battery dispatch carries `clarifications: []`, so `operator_answers_from_block("")`
yields `()`, the pre-#1043 default, and `_spec_corpus` is byte-identical on that path. Verified from
this run's own `acceptance.json`, not from the source comment that asserts it. Merge timeline:
#1043 16:27:45 · #1074 16:42:55 · #1074 run 16:57:16 · #1079 18:34:43 · #1076 18:55:03 ·
this run 19:04:34.

**What this run does NOT establish, stated because a GREEN invites over-reading.** It cannot prove
the evidence-preservation fix works: a healthy run never enters a fix cycle, so the append/offset
behaviour was never exercised. That rests on the executed toggle-off (restoring `mode="w"` turns 7 of
10 red) and the two-dispatch integration locks. It says nothing about #1075, which was deliberately
absent. It does not exercise #1087's deferral predicate (a `TASK-START` with `dispatch=2/4` after a
`TASK-END` reading `delivered=False`) — every task delivered, so no repair path ran, exactly the
limit the side config named before launch.

**Cadence hygiene verified both sides.** Default campaign `state/battery-campaign.json` UNTOUCHED at
`completed_passes` 3 / `target_full_passes` 5, jobs B2+B4 — file mtime `2026-07-23 01:06:39`,
eighteen hours before launch. `BlarAI-M2-Battery-Nightly` read `State=Ready`, `NextRunTime
2026-07-23 23:00:00`, `LastTaskResult 0` both before and after: self-unregister is scoped to the
DEFAULT config and this used a side config. Known residual: `-Now` strands the AO afterwards (#1053).

Evidence: `state/battery/night-20260723-190142/scorecards/B4.scorecard.json`,
`state/fleet-runs/20260723-190434-bd/{journal.log,JOB_SUMMARY.txt,scorecard.json,oracle-qa.json}`.

*(Placement note: as with the preceding two 2026-07-23 entries, appended at the END despite the
file's "newest first" header, following the immediately preceding entry's precedent and keeping the
day's three runs adjacent. The convention drift is recorded rather than silently reorganised.)*
