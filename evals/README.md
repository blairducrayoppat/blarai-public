# BlarAI Model-Quality Eval Harness (#717)

Golden-set evals that measure the system's **intelligence** — the Policy
Agent's classification judgment, the Assistant Orchestrator's tool-call
parsing/dispatch behaviour, and the deterministic governance verdicts — so
any future **model or prompt change can be scored against a committed
baseline** instead of judged by feel.

This harness measures **model/policy quality**. Software correctness is the
standing pytest gate's job; the two overlap only where a code change flips a
verdict (which fails both, on purpose).

## Suites

| Suite | What it measures | Model needed? |
|---|---|---|
| `pa_classification` | PA verdicts (ALLOW/DENY/ESCALATE) over golden CARs. Deterministic-rule cases run the REAL pre-filter -> rule engine -> decision matrix (mocked-ALLOW GPU so rules stay non-appealable). `mode: "model"` cases are the ISS-3 territory — nuanced CARs no rule catches — and need the real Qwen3-14B on the Arc 140V. | Only `mode: "model"` cases |
| `tool_calling` | Parse fidelity (`tools.parse_tool_call`), allowlist enforcement (`pgov.TOOL_CALL_ALLOWLIST`), and dispatch outcomes through the REAL registry (`tools.execute`, SAFE-tier only), including adversarial/malformed/injection-shaped outputs. | No |
| `governance` | Deterministic governance verdicts: `tools.risk_tier` fail-closed tiers, the Layer-3 untrusted-content lock predicate, `DeterministicPolicyChecker.check` (RULE 1-10, welded air-gap), the #570 dispatch-adjudication seam, and the #639 no-verifier ESCALATE->DENY default. | No |
| `answer_quality` | The AO's free-text answers, scored AS THE USER SEES THEM (production think-strip imported from `entrypoint._strip_hidden_blocks`) against a deterministic rubric (`evals/rubric.py`): identity, stable facts, instruction-following format, think-tag/system-prompt/datamark leakage, grounded-context fidelity (chunks injected through the REAL `ContextManager` grounding path), injection resistance (embedded-instruction canaries), and uncertainty honesty. `mode: "offline"` cases score committed fixture responses — they regression-lock the RUBRIC and pin exemplar answers, not the live model; `mode: "model"` cases drive the real Qwen3-14B AO generation path on the Arc 140V. | Only `mode: "model"` cases |
| `oracle_quality` | The dispatch acceptance-oracle quality surfaces (#738 follow-on): deterministic checks over the oracle corpus; one hardware-tier case. | Only the hardware case |
| `preference_memory` | Loop-1 operator-preference memory (#770 M1, design §6 cases 1-6): verbatim capture fidelity (P2) on the REAL encrypted store, pinned-block injection (byte-stable render at the fixed system-prompt slot, forged-delimiter neutralization), update/contradiction (P5 last-writer-wins + audit + the near-duplicate confirm probe), non-decay (P6), and the P4 budget lock through the production write gates. `kind: model_applies` / `abstention` cases drive the real 14B with the block in the REAL system-prompt geometry. | Only `model_applies`/`abstention` cases |

## Running

From the repo root, with the repo venv:

```powershell
# NEVER against the live LOCALAPPDATA (repo test-isolation rule):
$env:LOCALAPPDATA = "$env:TEMP\blarai-eval-la"
.venv\Scripts\python.exe -m evals.run --suite all
.venv\Scripts\python.exe -m evals.run --suite governance --report out.json
```

Exit codes: `0` clean vs baseline, `1` **regression vs baseline**, `2`
harness error (missing/malformed golden or baseline — fail-closed, an
uncomparable run is never a silent success).

Model-in-the-loop cases (Arc 140V only — never in CI):

```powershell
.venv\Scripts\python.exe -m evals.run --suite pa_classification --include-hardware
.venv\Scripts\python.exe -m evals.run --suite answer_quality --include-hardware
```

The standing gate exercises the deterministic suites via
`tests/integration/test_eval_harness.py` and
`tests/integration/test_eval_answer_quality.py`; the hardware tiers are the
`@pytest.mark.hardware` tests in those files (deselected by default).

## Baselines and regression semantics

`evals/baselines/<suite>.json` is a committed per-case status snapshot.

- **Regression (exit 1):** a baseline-passing case now fails/errors; a new
  case fails without being baselined; a baselined case vanished from the
  golden set.
- **Not a regression:** a case failing in the baseline that still fails (a
  *known, tracked* deficiency — this is how model misses are carried as
  data, not noise); an improvement (reported so you can refresh); hardware
  skips (never compared).
- **Refreshing** is a deliberate, reviewed act:
  `python -m evals.run --suite <name> --write-baseline` — the git diff shows
  exactly which case statuses changed.

## Adding cases

Append a JSON line to `evals/golden/<suite>.jsonl` (unique `id`, honest
`description`), run the suite, then refresh the baseline. Schemas are
documented in each suite module's docstring
(`evals/suites/<suite>.py`). For `tool_calling`, tag every case with its
`format`: `qwen3_json` is the only form the parser accepts (the `legacy_xml`
grammar was retired at #718 D3, 2026-07-02 — its cases remain as no-parse
regression locks). The runner drives the abstraction (`parse_tool_call` +
`execute`) and needs no change per format; grammar cases are filterable by
their tag.

## What is NOT covered (honestly)

- **Answer fluency / helpfulness** — the `answer_quality` suite is a
  DETERMINISTIC rubric: it measures containment, absence (leakage,
  injection canaries), format compliance, grounding fidelity, and length —
  NOT whether an answer is fluent, well-organised, or genuinely helpful.
  Grading those needs a judge; the documented follow-on is a
  local-14B-as-judge suite (the same model scoring transcripts against a
  rubric prompt — no cloud judge under the privacy mandate). Offline cases
  measure the rubric engine and pin exemplar answers; only `mode: "model"`
  cases on hardware measure the live model. (The websearch benchmark
  remains authoritative for its search-answer slice.)
- **The full AO tool LOOP** — the harness drives parse/allowlist/tier/
  adjudicate/execute as functions, and `answer_quality` drives
  `generate_text` single-shot over a `ContextManager`-composed context; it
  does not run the streaming tool loop in `entrypoint.py` end-to-end (the
  AO's own tests do).
- **The Layer-3 predicate is a MIRROR** — it is inline in the AO tool loop
  and not importable; `evals/suites/governance.py:layer3_lock_decision`
  mirrors it (tier input still comes from the real `tools.risk_tier`), and
  a drift tripwire in `tests/integration/test_eval_harness.py` pins the
  inline fragments so a shape change fails loudly.
- **GPU classifier quality in CI** — deterministic runs never consult the
  model; a mocked-ALLOW GPU stands in so rules-pass ALLOW cases exercise
  the real decision matrix. Model judgment is ONLY measured by the
  `mode: "model"` cases on hardware.
- **Speculative-decoding / latency / memory** — performance is
  `PERFORMANCE_LOG.md` + `docs/performance/` territory, not this harness.
- **Rule-engine RATE and RESOURCE stages** — the eval passes no rate
  limiter or resource deny-list (order-independence requires it), so those
  two stages are exercised only by the PA's own unit tests.

## Relationship to existing benchmarks

`tests/pa_quality_benchmark/` (per-class P/R/F1 + FAR/FDR quality gates over
its own corpus) and `services/assistant_orchestrator/tests/websearch_benchmark/`
predate this harness and remain authoritative for their metrics. This
harness adds the missing pieces: a single runner, committed per-case
baselines with regression exit codes, tool-calling and governance suites,
and a golden set designed to be extended at every model/prompt change.
