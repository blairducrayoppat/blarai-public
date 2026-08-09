# Oracle coverage traceability — requirement → oracle-assertion evidence

**Status:** design ratified by its own measurement; L0–L3 implemented, L4 named and NOT measured.
**Owns:** what `oracle_coverage` on a scorecard MEANS, and when `GREEN-VERIFIED` may be stamped.
**Read with:** `shared/fleet/oracle_qa.py` (the incumbent map), `tools/dispatch_harness/failure_taxonomy.py`
(the class emitter), `shared/fleet/oracle_mutation.py` (#828, the discrimination sibling).

---

## 1. What was actually broken (measured, not assumed)

The starting claim was "no traceability map exists". That is not what the substrate says. A map
exists — `oracle_qa.request_coverage_map` + `oracle_qa.verify_traceability` (#821) — and it has
produced a real `k/n` **14 times in 64 recorded dispatch runs**. Two separate defects hide behind
the single `GREEN-UNVERIFIED` stamp, and they need opposite fixes:

**Defect A — the instrument is dark.** `request_coverage_map` asks the 14B for the
`{criterion_id: [test_name]}` map and returns `None` when the emission does not parse. On `None`
the denominator is set to 0 and `coverage_fraction()` returns `"unknown"`. Measured over
`state/fleet-runs/*/oracle-qa.json`:

| window | runs | real `k/n` |
|---|---|---|
| 2026-07-12 → 2026-07-22 14:07 | 38 | 14 |
| 2026-07-22 16:56 → 2026-07-29 (last) | 26 | **0** |

The last run carrying a real coverage figure is `20260722-140757-bd`. Every run since is
`unknown`, `traceability_gap: 0`, `regeneration.rounds: 0` — the shape of a coverage stage that
never ran, not of an oracle that scored badly. B4 (flashcards) scored `0/6` on ten separate
nights through 2026-07-20 and has read `unknown` ever since. **A detector stopped detecting and
the scorecard reported nothing wrong** — the exact failure class this work exists to close.

**Defect B — and this is the larger one — "covered" is too weak to mean anything.** Driving the
real 2026-07-29 B2 and B4 oracles through `verify_traceability` with a *declaration that maps
every criterion to every test* returns **6/6 covered, zero gaps, for both**. B2's oracle has four
test functions for six test-tier criteria. It scores 6/6 because the current covered-predicate is:

> the mapper declared test *T* for criterion *C*, *T* exists in the AST, and *T* touches **any**
> first-party symbol.

The subject-binding hook that would tighten this (`criterion_subjects`) defaults, in
`validate_authored_oracle`, to *the full declared-export set for every criterion* — which is the
same "any first-party symbol" rule wearing a tighter name. So the predicate reduces to *the model
said so*, and a model that says so about everything scores full marks.

**This is why Defect A must not be fixed on its own.** Repairing the model call would make
`GREEN-VERIFIED` reachable immediately and near-universally, on a predicate that a maximally lazy
mapper saturates. That is lowering the bar while appearing to raise it.

## 2. What counts as a "requirement"

**Decision: the test-tier acceptance criteria** — `spec.criteria` filtered to
`TEST_TIERS = {behavior, smoke}` — as recorded in the run's own `acceptance.json`.

Rejected alternatives, and why:

- **The card's prose `goal`.** It is one natural-language blob with no addressable parts. Any
  decomposition into countable units is itself an inference, so the denominator would be
  something we invented and could tune. Unusable as a unit.
- **The card's `expected_outcome.must_verify_tiers`.** Structured and honest, but far too coarse
  — it names *tiers*, not requirements. It answers "should there be behavior tests", never "is
  *this* behavior tested".
- **The plan's task list.** Structured and tempting. Rejected because it is the *solution
  decomposition*, not the requirement: measuring the exam against what we decided to build is
  self-confirming, and cannot by construction detect that we built the wrong thing.

**What is lost by choosing criteria, stated plainly because it does not go away:** the criteria
are themselves 14B-authored from the goal. Coverage against them therefore **cannot** detect a
criterion set that missed part of what the operator asked for. This instrument measures
*exam ⟶ criteria*, never *criteria ⟶ goal*. That second gap is real, is not closed here, and is
recorded on every emission (§5). Also excluded by construction: `build`, `visual`, `human` tiers —
no pytest verifies "visually clear". The denominator is therefore a **subset** of the criteria and
must say so; the incumbent `7/8` fingerprint did not disclose this.

## 3. What counts as "covered" — a ladder, not a boolean

A single covered/uncovered bit forces every judgement into the weakest predicate that can carry
it. Instead each criterion earns an **evidence level**, deterministically, from artifacts already
banked in the run directory. No model participates.

| level | name | evidence | who can fake it |
|---|---|---|---|
| **L0** | `UNMAPPED` | no test binds to the criterion at all | — |
| **L1** | `DECLARED` | a mapper named test *T*; *T* exists and touches some first-party symbol | the mapper, trivially — **today's whole rule** |
| **L2** | `SUBJECT-BOUND` | *T* exercises the criterion's **own** subject symbol | requires the test to touch the right code |
| **L3** | `ASSERTED` | *T* carries an assertion that **bears on** that subject — the subject named in the `assert` subtree, or reached from it through a local bound from the subject | requires an assertion *about the subject*; `assert True` and an assertion about a different symbol both fail it |
| **L4** | `DISCRIMINATING` | *T* goes RED when the subject's implementation is mutated | nothing short of a real test |

**The headline figure counts L3 and above. L1 is never counted as covered.** L1 is retained and
reported because the distance between L1 and L3 is precisely the leniency this instrument exists
to measure.

Subjects are derived **deterministically**: identifier tokens of the oracle's first-party symbols
(`word_frequencies` → `{word, frequencies}`, with light singular/plural folding) matched against
the token set of the criterion's `text` + `check`. No model, no network, same answer every run.

**First-party is resolved, never assumed.** A symbol only becomes a candidate subject when the
delivered tree actually provides its module root — established from the run's own banked #822
resolve-probe pair (`import-probe-targets.json` + `import-probe-verdict.json`), or failing that
from the tree named by `scorecard.json`'s `repo`. Neither available ⇒ `available=False`, never a
number. The rejected design was a denylist of non-first-party roots, under which every root nobody
had thought of was first-party by default: an oracle importing `mean` from `statistics` handed the
criterion "the report should show the mean value" a subject the deliverable never wrote, and L3
coverage it never proved.

**L4 is defined and NOT measured in this pass.** `shared/fleet/oracle_mutation.py` (#828) already
implements deterministic mutation, but whole-file (`killed/ran`), not per-criterion, and it needs
a live repo and a wall-clock budget — battery close has the artifacts, not the tree. Reaching L4
means running the mutation operators restricted to each criterion's subject module and attributing
kills per declared test. That is a bounded, named piece of work, blocked on a
per-criterion attribution surface in `oracle_mutation.py`; it is not hand-waved as "later".
Until then **no criterion can be stamped L4, and the emission says so in every record.**

## 4. The honest output when coverage cannot be determined

The load-bearing rule, and the one that decides whether this instrument can be trusted:

> **A criterion whose subject cannot be derived is neither covered nor uncovered. It is
> `UNDECIDABLE`, and it is reported as its own count.**

A ratio is never emitted alone. Every emission carries a four-way split over the denominator:

```
verified (L3+)  |  weak (L1–L2)  |  gap (L0)  |  undecidable
```

Consequences, deliberately chosen:

- **`undecidable > 0` ⇒ `GREEN-VERIFIED` is unreachable.** Not-knowing can never present as
  passing. This is the direct answer to the README-lint failure: an instrument that goes blind
  must produce a *worse* class, never a clean one.
- **The stamp names its own blindness in-band.** The fingerprint reads
  `oracle_coverage=4/6 L3+ (weak:1 gap:0 undecidable:1; L4 not measured)` — a reader cannot
  mistake it for a pass, and cannot lose the exclusion by quoting the number alone.
- **No fallback softening.** Unparseable oracle, missing criteria, absent `acceptance.json` → the
  whole emission is `unavailable` with a reason string. It never degrades to a number.
- **This is strictly stricter than the incumbent.** Under the shipped rule the real B2/B4 oracles
  score 6/6 with a saturating declaration. Under this ladder they score what §6 records. The bar
  moved up; nothing was tuned to let anything through.

## 5. Emission

New module `tools/dispatch_harness/green_quality/traceability.py`, advisory and fail-soft, same
contract as the rest of `green_quality/` — never a gate, never a crash, no verdict field.

Schema `traceability/v1`, one block per job, written to `<run>/traceability.json` and consumed by
`failure_taxonomy.classify_green` as an **optional sidecar**, exactly the pattern `green-audit.json`
already uses. Every block carries `measured` (the levels actually computed), `not_measured`
(`["L4-discriminating"]`), and `denominator_excludes` (`["build", "visual", "human"]`) — the
community-grade "name what was NOT measured" discipline applied to an integrity instrument.

The classifier edit is minimal and additive: when the deterministic block is present it wins
(it is evidence; the 14B declaration is an assertion), otherwise behaviour is byte-identical to
today. `GREEN-VERIFIED` now requires `undecidable == 0 and gap == 0 and weak == 0`.

## 6. What the real oracles score

Measured against the actual 2026-07-29 deliveries, recorded here because an instrument's first
duty is to report its own subject honestly — see the commit and the run report for the figures.
If they are bad, that is the finding, and the finding is the deliverable.

## 7. Regression locks

- The ladder's own toggle test (principle 12): each level's probe must FAIL to fire when the
  evidence that justifies it is removed — otherwise "covered" cannot be distinguished from
  "the check could not reach it".
- A saturating declaration (every criterion → every test) must NOT reach `GREEN-VERIFIED` on the
  real B2 oracle. This is the anti-tuning lock: it fails if anyone weakens the predicate back
  toward L1.
- `undecidable > 0` must block `GREEN-VERIFIED` in the classifier, driven through the real
  `classify_green` entry point rather than the helper.
