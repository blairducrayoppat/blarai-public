---
title: "#746 research grounding — full validation program"
status: in-progress
area: research
---

# #746 plan-time research grounding — validation program

**Plain summary:** one test isn't enough for a capability the LA considers critical for a
small local model. This is the real methodology: multiple cards, a paired on/off comparison,
a purpose-built test the current battery set doesn't provide, and a live-fire check of the
reactive coder tool — written down before running, so results aren't fitted to a story
afterward.

**Standing constraint, stated up front:** only one GPU, one battery job at a time. Each phase
below runs sequentially. This is a multi-hour program, not a quick check — that's accepted as
the cost of doing it properly.

## Phase 1 — B7 sandbox safety check (grounding ON)

**Status: COMPLETE, GREEN** (`night-20260724-080244`, fleet-run `20260724-080505-bd`). All 3
tasks merged, zero errors/crashes/degradation. Grounding fired exactly once (confirmed via the
usage log, one call per `decompose_request`), honest `no_match` — no relevance-floor hit for
this vanilla-JS-utility goal against the Python/web-focused docset, which is a sane result, not
a failure. `research_grounding` reverted to `false` (committed) immediately after evidence
capture. Full detail: `docs/quality/dispatch-quality-ledger.md`'s `night-20260724-080244` entry.

**A real defect was found and fixed during this phase, not just flagged**: the usage log
initially looked anomalous (~10 calls, 2 `unavailable`, for a single 3-task job) — traced to
THREE test files (`shared/tests/test_decompose_research_wiring.py`,
`shared/tests/test_research_substrate.py`, `agentic-setup/tools/tests/test_search_docs.py`)
silently writing synthetic records to the same production log path on every pytest run,
including the standing gate itself. Fixed (autouse fixtures redirecting to `tmp_path` in all
three), verified via the full gate (9,206 passed) leaving the real log at 0 bytes afterward.
This was a genuine gap the validation program surfaced by actually looking for usage evidence
that had never existed before tonight — worth naming as a benefit of running Phase 1 for real
rather than assuming the logging instrumentation was correct.

## Phase 2 — B6 paired comparison (grounding OFF, then ON)

**Purpose:** the first real paired signal. B6 (Python, inventory manager, 8-unit stretch —
CSV export, search, low-stock warnings) is the deepest-docset-coverage card among the
reachable set (B3/B5/B6/B7/B8) and has no known reliability issues in the ledger (unlike B5,
whose last two historical runs hit budget starvation before #927's fix — avoided here to keep
the comparison clean).

- Run 1: grounding OFF (the true current-behavior baseline — B6 has no prior ledger entry to
  reuse, so this must be measured fresh, not assumed).
- Run 2: grounding ON, same card, same complexity band.
- Compare: final verdict, wall-clock, the dispatch-quality-ledger's six standing dimensions
  (decomposition grain, check realism, scope fidelity, honesty lines, assumption quality,
  acceptance-criteria pinning), and the research-usage.jsonl log (did grounding even fire for
  this goal, and with what hit content).
- **Honest limitation, stated before running:** N=1 per arm is not statistical proof — a
  single pair shows a data point, not a trend. Read the result as a first real signal, not a
  verdict, exactly per the LA's own standard for measurements tonight.

## Phase 3 — Purpose-built "genuine need" scenario

**Why:** #1101 measured tonight that the fleet's existing battery cards are ~100%
stdlib/vanilla-JS by design (zero third-party deps mandate) — none of B1-B8's goals were
ever written to need documentation help. Testing grounding only on cards that don't need it
risks a null result that looks like "doesn't help" when it's really "never had anything to
help with." This phase closes that gap without changing the zero-deps skeleton policy: a
task requiring genuine STDLIB DEPTH — an area with real, documented subtlety a smaller model
plausibly gets wrong without a reference.

**Candidate scenario:** a Python CLI tool requiring a `contextlib`-based custom context
manager with correct exception-safe cleanup (a class exposing `__enter__`/`__exit__` is the
naive approach; the generator-based `@contextmanager` decorator has real, documented gotchas
around exception re-raising inside the generator that smaller models frequently get wrong).
This is entirely within the existing zero-third-party-deps policy (contextlib is stdlib) and
the corpus's own Python core actually covers it.

Run this as an ad hoc dispatch (not a frozen battery card) with grounding OFF then ON,
comparing whether the generated context-manager code is actually correct on the exception
path (a concrete, checkable behavioral difference, not just "did it look up docs").

## Phase 4 — Reactive tool live-fire (the coder-side half)

**Status: not yet started** — everything above tests plan-time grounding only. The coder's
`search_docs` tool (agentic-setup, `BLARAI_RESEARCH_DOCS`) has never been exercised in a real
dispatch — only the standalone CLI, by hand, tonight. This phase:
1. Sets `BLARAI_RESEARCH_DOCS=1` for one dispatch only (not persisted — a per-run override).
2. Dispatches a task that deliberately surfaces an unfamiliar error or symbol during the
   build (not just an unfamiliar goal — a runtime error the coder must actually resolve).
3. Confirms via `state/research-usage.jsonl` AND the task's own build log that `search_docs`
   was actually invoked, with what query, and whether the returned excerpt was real local-doc
   text (not the model inventing something that happens to look plausible).

## Phase 5 — Consolidated report

Written after all phases complete: full methodology recap, every run's evidence pointer, the
research-usage.jsonl hit-rate summary across all phases, the dispatch-quality-ledger
dimension comparison for Phase 2 and Phase 3, what moved and what didn't, and explicit
statistical caveats (this is not a large-N study — it's the first rigorous look, sized to
what one GPU and one evening can produce).

## What happens to the flag between phases

`research_grounding` sits at `false` (dormant, committed) whenever a phase isn't actively
running. Each ON run is a deliberate, temporary, uncommitted flip, reverted the moment that
run's evidence is captured — never left on unattended, never committed as `true` until the
LA makes an informed go-live decision from Phase 5's actual results.

## Log

- 2026-07-24 08:02 — Phase 1 (B7) launched.
- 2026-07-24 09:12 — Phase 1 (B7) completed: GREEN. Usage-log pollution defect found via the
  same-window investigation, fixed in three test files, verified via the full gate.
  `research_grounding` reverted to `false` (committed). Session paused here (LA credits
  caution) — Phase 2 handed to a dedicated follow-on session per
  `docs/handoffs/746-validation-handoff-20260724.md`.
