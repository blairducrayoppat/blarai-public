---
title: ACS Conformance Disclosure
status: living
area: governance
---

# What BlarAI may and may not claim about the Agent Control Specification

**Written 2026-09-17 under #1570, sprint 19.** This document exists so that nobody — a future
session, a certification assessor, or the operator writing a portfolio entry — has to guess how
strong BlarAI's alignment with the Agent Control Specification (ACS) actually is. It states the
claim, the evidence, and the limit.

## The claim, in the exact words that may be used

> BlarAI is **ACS-vocabulary aligned**. It adopts the Agent Hooks contract's verdict enum, its two
> reserved-reason namespaces (`host_error:*` and `runtime_error:*`), and its approval-identity
> rule, as **naming**. It does not run the ACS engine, does not load manifests, and does not
> evaluate Rego or Cedar.
>
> **TWO conformance suites exist, and both were inventoried, not run.** The Agent Hooks CTK —
> **47 vectors**, `responsibleai/agent-hooks` at tag `v0.1.0-alpha.3` — and the Agent Control
> Specification crate's own `tests/conformance/` tree — **23 cases** plus streaming inputs and
> bindings, `responsibleai/agent-control-spec` at `a830ed5`.
>
> **Zero of 70 are executable against BlarAI's doors.** Every CTK vector needs the full-loop
> harness: a mocked model, mocked tools, an `Interceptor` registered at all eight interception
> points, and an assembled `RunRecord`. Every crate case is `operation: "evaluate"` — run the
> engine's evaluate against a manifest — and BlarAI has no manifest loader and no Rego evaluator.
> BlarAI has four hand-written, single-point doors and implements neither harness.
>
> **No conformance percentage is claimed.** The terms "ACS-conformant" and "CTK-passing" must not
> be used.

## Why no number appears above, including "0 of 70"

A fraction implies BlarAI could in principle attempt some of the suites' own pass bar and fell
short by some margin. It cannot attempt one case. Publishing "0 of 70" would be as misleading as
publishing "12 of 70" — both invite the reader to imagine a spectrum BlarAI is not on.

**This document has been wrong twice about its own history, and the second time was the
retraction.** Both are recorded here because a disclosure that tidied them would be advertising
the opposite of what it teaches.

*First pass.* Examined only the Agent Hooks CTK and reported "zero of 47", with a correction:
47 test **cases**, not 49 **files**.

*Second pass — the retraction, which was WRONG.* Reading a sibling document, this session found
"49 conformance fixtures" attributed to the `agent-control-spec` crate, concluded the first pass
had answered about the wrong suite, and retracted the 49→47 correction. It also minted a lesson
on that premise.

*Third pass — the retraction is itself retracted.* `conformance/agent-hooks/` at `a830ed5` holds
**exactly 49 files**: the 47 vectors plus `PROVENANCE.md` and `REPORT.md`. That directory *is* a
conformance suite against the Agent Hooks contract — the origin sentence's own words. **The first
pass was right, about the right suite.** The arithmetic used to justify the retraction
(`23 + 18 + 7 + 1 = 49`) reached its target only by silently discarding **7 of the 56** files in
the crate's `tests/conformance/` tree, under a rule that was never stated: reverse-engineering to
a wanted number, inside the document about not doing that.

The evidence was in hand throughout. The downloading pass's own `MANIFEST.json` reads: *"47
AH-CTK-*.json vectors + PROVENANCE.md + REPORT.md = 49 files total in that directory — this is the
most likely source of BlarAI design doc's '49-file' claim."* Nobody read it before retracting.

**So the standing figures are: 47 test cases in the CTK, in a directory of 49 files; 23 cases in
the crate's own tree, of 56 files. The "49-file suite" in the design document counts CTK files
rather than CTK test cases, and the original correction stands.**

The count belongs in the *reason* sentence, where it describes the suite, not in a score position
where it describes BlarAI.

## The crate's 23 cases, triaged — because they are the ones that came closest

Unlike the CTK vectors, these have no mocked model and no mocked tools: each is a
`policy_response` in and an `expected` out. That shape is portable in substance even though it is
not runnable, so the triage says which **rules** BlarAI could hold itself to.

| Cases | Why not portable |
|---|---|
| `spec-08-intervention-points` ×7 | Turn on which of the eight intervention points a manifest declares. BlarAI emits at four and models them differently. |
| `spec-16-effects` ×5, `spec-14-effects` ×2 | The effects/transform model. BlarAI has no transform path. |
| `spec-09-tool-projection` ×2 | Tool projection — no BlarAI equivalent. |
| `spec-18-ifc` ×2 | Information-flow control. This is #1546's subject and is undesigned. |
| `spec-10-annotators`, `spec-12-dispatcher`, `spec-15-resource-limits` ×1 each | Annotators, the engine dispatcher, engine resource limits. None exist in BlarAI. |

**Two whose rules ARE portable**, and which BlarAI-native tests should mirror:

- `spec-14-verdict-normalization.case-01` — a policy returning `{"decision": "block"}` must
  normalise to `deny` with `runtime_error:policy_output_invalid`. An unrecognised decision is not
  passed through and is not treated as allow.
- `spec-08-action-identity.case-08` — an `escalate` must normalise to a `deny` carrying
  `action_identity` and `approval`. That is exactly the rule #1541 implements.

**On the manifests, stated precisely rather than dramatically.** The 23 cases carry **9 distinct
`manifest_yaml` values**, so an earlier claim that they are "identical boilerplate" — generalised
from reading two files — was wrong. But the correction overstated in the other direction: **12 of
the 23 share one identical 10-line manifest** and four more differ from it by two lines, and *both*
cases named portable above use that modal manifest. So the engine's configuration does vary across
the suite, and it does **not** vary for the two cases this deliverable rests on.

## What was read, so this can be checked rather than trusted

| Artefact | Source | What it settled |
|---|---|---|
| 47 vectors, `conformance/vectors/*.json` | `responsibleai/agent-hooks` @ `v0.1.0-alpha.3`, sha `60647b160487cdefb5779301bcdaab65e05d73e8` | Machine-scanned for top-level and `scenario` keys: **all 47** carry `scenario.model_script`; **41** carry `scenario.tools` |
| `AH-CTK-072-resolver-identity-mismatch.json` | same | Opened and read in full. The fixture closest to BlarAI's own approval-identity work (#1541), and still a scripted scenario: mocked `wire_transfer` returning `UNREACHED`, two-turn model script, `approval_script` with `identity_override`, `expect` asserting `interceptions_absent` and `tool_not_invoked` |
| `AH-CTK-071-malformed-verdict.json` | same | Opened and read in full. Same scenario shape |
| `conformance/HARNESS.md` | same | Describes the harness as "the ~100-line shim a framework author writes" — the scaffolding BlarAI would have to build |
| `REPORT.md`, `PROVENANCE.md` | `responsibleai/agent-control-spec` @ `a830ed5` | Its reference-host run reads "46 passed, 0 failed, 1 skipped (capability-gated) of 47", and its `PROVENANCE.md` records the CTK vectors as "vendored verbatim from agent-hooks 0.1.0-alpha.3" |
| All **23** cases under `tests/conformance/cases/` | `responsibleai/agent-control-spec` @ `a830ed5` | Fetched and machine-scanned in full. All `operation: "evaluate"`; **9 distinct manifests**; six distinct `runtime_error:*` reasons asserted |
| Repository tree at `a830ed5` | GitHub API | The arithmetic behind "49": 23 cases + 18 streaming inputs + 7 bindings + 1 bundle |

The "49-file suite" figure in `docs/research/acs-vocabulary-adoption-design-2026-09-16.md` counted
files in the directory rather than test cases. That document now carries a superseded banner.

## The reserved-reason inventory, which is worth more than any score

Between them the two suites exercise **both** reserved namespaces. **The criterion is what a suite
NAMES, not what it happens to assert inside an `expect{}` block** — an earlier version of this table
used the narrower rule and listed 7 `host_error:*` instead of 11, because vectors like `AH-CTK-022`
are entirely *about* a reserved reason while asserting only `run_outcome: "blocked"`. That
undercount was not cosmetic: it would have rejected `host_error:approval_resolver_failed`, which
#1542's design adopts, as an invented identifier.

**Eleven `host_error:*`** (agent-hooks CTK, `CLAIMS.md` and the vectors):
`approval_identity_mismatch`, `approval_resolver_failed`, `composition_disagreement`,
`context_invalid`, `interceptor_failed`, `no_interceptor`, `streaming_unsupported`,
`transform_conflict`, `transform_invalid`, `transform_target_forbidden`, `verdict_invalid`.

**Six `runtime_error:*`** (agent-control-spec crate's 23 cases):
`intervention_point_unknown`, `policy_invocation_failed`, `policy_output_invalid`,
`resource_limit_exceeded`, `tool_unknown`, `transform_target_forbidden`.

`transform_target_forbidden` is named in **both** namespaces and is not a duplicate. Seventeen
distinct identifiers in total, and that set is what
`tests/security/test_acs_vocabulary_alignment.py` enforces against invention.

## Which fixtures the vocabulary was taken from, and by what rule

A fixture is **vocabulary-relevant** when its assertions reference a reserved-namespace reason or
the approval-identity rule — the elements BlarAI actually adopts. Applied mechanically to all 47
rather than hand-picked: 12 assert a reserved reason, 8 touch approval identity, **union 15**.

`AH-CTK-030`, `072`, `085`, `087`, `089`, `090`, `091`, `092`, `095`, `096`, `098`, `099`, `101`,
`102`, `103`.

**15 is not a denominator.** Those 15 are exactly as unrunnable as the other 32 — identical
scenario shape. They are where vocabulary is quoted from. Any BlarAI test written from them is a
**BlarAI-native test using ACS vocabulary**, and must never be described as a CTK vector passing.

## What would change this document

Building the CTK harness shim would make the vectors runnable and a real score possible. That is
**declined**, and the reason is not cost: conforming to the suite's eight interception points would
mean reshaping four hand-written doors to fit a test rig. The doors are the product; the rig is
not. If that decision is ever revisited, this document is what has to be rewritten.
