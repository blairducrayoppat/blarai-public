# Rule Engine & CAR Validation Governance

## Audience

**Primary**: developer — extends the deterministic rule set in
`services/policy_agent/src/rule_engine.py`, adds new `ActionVerb`
members, or tunes the ACL matrix / deny list surface. Any change that
adds or modifies a rule stage, reorders the pipeline, or shifts the
fail-closed contract flows through this doc before merge.

**Secondary**: auditor — verifies that the deterministic pipeline is
the single, auditable gate that short-circuits before any probabilistic
classifier runs. The rule engine is the fail-closed surface for
USE-CASE-001 (Policy Agent); the enums and Fail-Closed invariants
below are the audit contract.

## Prerequisites

- [STYLE.md](STYLE.md) — binding governance template.
- [ADR-010](../adrs/ADR-010-PA-Device-Allocation-GPU-Classification.md) —
  Policy Agent classification on GPU. ADR-010 is the load-bearing ADR
  for this doc: it mandates a **deterministic pipeline before any
  probabilistic stage** (see §3 below). ADR-010 does not mandate the
  specific five-stage decomposition implemented today — that is
  encoded in source (`rule_engine.py`) and test fixtures, and is
  documented here as the authoritative enumeration.
- **ADR-absence note**: no ADR directly governs the five specific
  rule stages (STRUCTURAL, SENSITIVITY, ACL, RATE, RESOURCE) or
  the ACL matrix shape. Additions/removals to the stage list SHOULD
  be paired with a DEC-entry and a new ADR-candidate issue. See
  **Open Questions**.
- Peer governance docs:
  [pgov-validation.md](pgov-validation.md) (the probabilistic PGOV
  pipeline that follows the deterministic gate for the AO path);
  [ipc-protocol.md](ipc-protocol.md) (CAR wire format at the
  vsock boundary).

## Source References

| Artifact | Path | Notes |
|---|---|---|
| Deterministic rule engine — 5-stage pipeline | `services/policy_agent/src/rule_engine.py` | full file; the orchestrator is `run_rule_engine` |
| CAR schema, enums, `is_complete`, `canonical_hash` | `shared/schemas/car.py` | full file |
| CAR construction front-end (`build_car`) | `services/policy_agent/src/car.py` | full file; enum normalization |
| DecisionArtifact (adjudication receipt) | `shared/schemas/car.py` | `DecisionArtifact` class |
| Resource deny-list rule shape | `services/policy_agent/src/config_loader.py` | `ResourceDenyRule` |
| Cross-reference: probabilistic follow-on (PGOV cosine 0.85) | `services/assistant_orchestrator/src/pgov.py` | lines 460-585; documented in [pgov-validation.md](pgov-validation.md) |

**Source-authoritative note (I-4)**. The EA prompt that queued this
doc referenced a file called `deterministic_policy_checker.py`; that
file does not exist in the repo at the HEAD this doc was authored
from. The actual rule engine lives at
`services/policy_agent/src/rule_engine.py`. Source wins; the prompt
reference is stale. The divergence is recorded in **Open Questions**.

## Governance Content

### 1. Pipeline ordering — the five deterministic stages

Every CAR that reaches the Policy Agent flows through
`run_rule_engine` (`rule_engine.py` lines 290-355). The pipeline is
strictly ordered and **short-circuits on the first DENY**; subsequent
stages do not execute. Short-circuit is load-bearing — it prevents the
RATE counter from being inflated by CARs that are already
STRUCTURAL-ly or ACL-denied.

| Stage | Function | Input | DENY signal |
|---|---|---|---|
| 1 | `evaluate_structural` | CAR | `is_complete()` returned False |
| 2 | `evaluate_sensitivity` | CAR | `sensitivity == Sensitivity.UNCLASSIFIED` |
| 3 | `evaluate_acl` | CAR + `acl_matrix` | matrix missing or `destination_service` not in allow-list |
| 4 | `evaluate_rate` *(optional)* | CAR + `RateLimiter` | count ≥ `max_requests` in window |
| 5 | `evaluate_resource` *(optional)* | CAR + deny rules | `fnmatch` pattern match (optionally verb-scoped) |

Stages 4 and 5 are optional — a caller may invoke `run_rule_engine`
without a `rate_limiter` or `resource_deny_list` and those stages are
skipped. This is backward compatibility for P1.0/P1.1 callers; the
production Policy Agent passes both. Every evaluated stage produces a
`RuleResult` (name, verdict, reason) which is returned in the
aggregated `RuleEngineResult`.

### 2. Deterministic-before-probabilistic mandate (ADR-010)

ADR-010 mandates that the deterministic pipeline runs **before** any
probabilistic classifier. The rationale:

- **Latency**. The deterministic stages are pure Python, no GPU,
  and complete in well under a millisecond for any single CAR.
- **Explainability**. Every DENY carries a `rule_name` and
  human-readable `reason`. No probabilistic confidence-band analysis
  is required to explain a deterministic DENY.
- **Fail-Closed guarantee**. The deterministic pipeline has no
  model-load path that can fail silently. If a stage raises, the
  callsite treats the CAR as DENIED (every stage is total over CAR
  space — the function signatures do not raise; they return
  `RuleVerdict.DENY`).

The probabilistic complement lives in the AO's
`services/assistant_orchestrator/src/pgov.py` (cosine-similarity
leakage detection at threshold 0.85, documented in
[pgov-validation.md](pgov-validation.md)). The two surfaces do not
share a call path: the rule engine adjudicates actions on the PA side;
PGOV adjudicates generated responses on the AO side. Both surfaces are
fail-closed.

### 3. CAR schema enforcement

The STRUCTURAL stage delegates to
`CanonicalActionRepresentation.is_complete()` (`shared/schemas/car.py`
lines 132-142):

```python
return bool(
    self.source_agent
    and self.destination_service
    and self.resource
    and self.request_id
)
```

A CAR that fails this check is DENIED with
`rule_name="STRUCTURAL_COMPLETENESS"`. Note that `verb`,
`sensitivity`, `parameters_schema`, `timestamp`, and `session_id` are
**not** part of the completeness check — those are enforced at the
pydantic model level (pydantic raises at construction if a required
field is missing; `is_complete()` guards against empty-string
sentinels on the four identity/resource fields).

`canonical_hash()` (lines 112-130) produces a deterministic SHA-256
over the identity + action fields (`source_agent`,
`destination_service`, `verb`, `resource`, `parameters_schema`,
`sensitivity`). `timestamp` and `request_id` are excluded, so
`canonical_hash` is suitable for deduplication and replay detection.

### 4. Enums — the authoritative surface

`shared/schemas/car.py` defines the three enums that the rule engine
reads. New values require: a rule-engine hunk (extending whichever
stage the new verb/sensitivity touches), a test, and a doc update in
this section — in the same commit.

| Enum | Members |
|---|---|
| `ActionVerb` | `READ`, `WRITE`, `EXECUTE`, `DELETE`, `QUERY`, `DISPATCH`, `EGRESS` |
| `Sensitivity` | `PUBLIC`, `INTERNAL`, `SENSITIVE`, `UNCLASSIFIED` |
| `AdjudicationDecision` | `ALLOW`, `DENY`, `ESCALATE` |

SENSITIVITY uses an inverted convention: `UNCLASSIFIED` is the
fail-closed label, not `PUBLIC`. A CAR that never had its sensitivity
populated surfaces as `UNCLASSIFIED` at the boundary (there is no
default — the pydantic model requires explicit assignment) and is
DENIED at stage 2. This prevents the silent-misclassification vector
that a `PUBLIC`-default would open.

### 5. ACL matrix shape

The ACL matrix is a `dict[str, list[str]]` — source agent (mTLS CN)
→ list of allowed destination services. Evaluation:

- matrix is `None` → `DENY` with reason "ACL matrix not loaded —
  Fail-Closed." (this is the fail-closed boot path; a matrix that
  never loaded is treated as a deny-all)
- `car.destination_service` in `acl_matrix[car.source_agent]` → `ALLOW`
- otherwise → `DENY`

The matrix is loaded from TOML at service start (see
`config_loader.py` and the PA entrypoint). There is no hot-reload
path; a matrix change requires a PA restart.

### 6. Rate limiter semantics

`RateLimiter` (`rule_engine.py` lines 74-143) is a per-agent
sliding-window counter. Per
`check_and_record`:

- Expired entries (outside `window_seconds`) are purged first.
- If the post-purge count is at or above `max_requests`, returns
  `(False, count)` and **does not record** the request — the agent is
  already over budget; inflating further would extend the denial
  duration.
- Otherwise, records `now` and returns `(True, count + 1)`.

Thread-safety: **not thread-safe**. The PA runs a single-threaded
vsock listener by architectural design; the limiter is called from
that loop.

### 7. Resource deny-list semantics

`evaluate_resource` walks `deny_rules` in order. Per rule:

- If `rule.verb` is set and does not equal `car.verb.value`, skip.
- Else, `fnmatch.fnmatch(car.resource, rule.resource_pattern)` →
  DENY with the rule's `reason` on match.

The **first matching rule wins**. Ordering in `deny_list.toml`
therefore matters; more-specific patterns must precede more-general
ones if the author wants specificity to win.

### 8. Example adjudications

ALLOW (end-to-end):

```python
car = build_car(
    source_agent="ui_shell",
    destination_service="assistant_orchestrator",
    verb="DISPATCH",
    resource="skill.calendar.read",
    sensitivity="INTERNAL",
)
result = run_rule_engine(car, acl_matrix, rate_limiter=limiter, resource_deny_list=deny)
# result.passed == True; result.results has 5 RuleResult entries, all ALLOW.
```

DENY on STRUCTURAL:

```python
car = CanonicalActionRepresentation(
    source_agent="", destination_service="x", verb=ActionVerb.READ,
    resource="r", sensitivity=Sensitivity.INTERNAL, request_id="req-1",
)
# source_agent is empty; is_complete() → False.
# result.passed == False; result.blocking_rule == "STRUCTURAL_COMPLETENESS".
# Stages 2-5 not evaluated.
```

DENY on SENSITIVITY:

```python
car = build_car(source_agent="s", destination_service="d",
                verb="READ", resource="r", sensitivity="UNCLASSIFIED")
# result.blocking_rule == "SENSITIVITY_CLASSIFICATION"; stages 3-5 skipped.
```

### 9. DecisionArtifact — the adjudication receipt

On ALLOW (deterministic) → ESCALATE (probabilistic stage runs) →
final decision, the PA mints a `DecisionArtifact` (agentic JWT
payload, signed by `jwt_minter.py`). The artifact carries:

- `car_hash` — from `CanonicalActionRepresentation.canonical_hash()`.
- `decision` — one of `AdjudicationDecision.{ALLOW, DENY, ESCALATE}`.
- `deterministic_pass` — whether the rule engine returned passed=True.
- `probabilistic_pass` — whether the probabilistic stage approved.
- `confidence` — probabilistic classifier score in [0.0, 1.0].
- `request_id` — correlates back to the originating CAR.
- `expiry_seconds` — default 5 (Use Cases §3: 5s hard TTL).
- `issuer` — `"policy_agent"` (always).

Destination microservices validate the artifact's JWT signature and
TTL before executing the requested action. A DENY is encoded in the
artifact too (for audit-trail completeness) — the destination never
sees an ALLOWed-but-revoked request; a DENY artifact simply is not
useful to present at the boundary and callers drop it.

### 10. Rule authoring and versioning

New rules are added by extending the appropriate `evaluate_*` function
(or, for a net-new stage, inserting into `run_rule_engine`). There is
**no runtime hot-reload**: rule changes require a PA restart.
Versioning is by git commit — the rule engine does not emit a version
string today.

**Governance implication.** A PR that modifies rule ordering, adds a
new stage, or changes a DENY condition must:

1. Update `rule_engine.py`.
2. Update `test_rule_engine.py` (extend the per-rule test fixtures).
3. Update §1 and §4 of this doc (the five-stage table and the enums).
4. Open a ledger entry (Q1-1 per-file) describing the change.
5. If the change weakens a DENY condition, open an ADR-candidate
   issue — a DENY weakening has security-boundary implications and
   needs architecture review.

### 11. Performance budget

The deterministic pipeline is pure-Python with no I/O. Worst-case
latency is the RESOURCE stage on a long deny list (linear fnmatch
scan). For the current deny list (< 100 rules) and typical CAR shapes,
measured per-call latency is sub-millisecond on the production
hardware. There is no explicit SLA; the deterministic stage is
expected to be negligible compared to downstream probabilistic and
model-inference costs.

### 12. Persona guidance

- **Developer.** When adding an `ActionVerb`, the sequence is:
  (1) extend `ActionVerb` enum in `shared/schemas/car.py`,
  (2) if the verb has verb-specific rule behavior, extend
  `evaluate_resource` or add a new stage, (3) update tests,
  (4) update §4 of this doc in the same commit.
- **Auditor.** The five stage names in §1 are the complete
  deterministic-adjudication surface. Any DENY surfaces a
  `blocking_rule` value drawn from that set; a DENY whose rule name
  is not in the set is a governance gap — file an issue.

## Recovery / Remediation Procedures

Recovery for the rule engine is a non-event by design: a DENY is
governance behavior, not a failure. There is no externally triggered
failure mode that requires operator recovery — an incomplete or
UNCLASSIFIED CAR is rejected at the PA boundary and the caller sees
the DENY reason. The `## Recovery / Remediation Procedures` section
is retained (rather than merged) to document this explicitly:

1. **Unexpected DENY.** Developer/operator reads the adjudication log
   for the `blocking_rule` and `reason`, then inspects the CAR fields
   via `car_hash` cross-lookup in the PA audit log. If the DENY is
   incorrect, the fix is a rule change (see §10), not a retry.
2. **ACL matrix missing (boot).** `evaluate_acl` returns DENY with
   "ACL matrix not loaded" on every CAR. This is fail-closed by
   design; the recovery is to fix the TOML load path and restart the
   PA. There is no partial-ACL degraded mode.
3. **Rate-limiter state reset.** `RateLimiter.reset(agent_id=...)`
   clears one agent's window; `reset()` (no arg) clears all. Intended
   for test fixtures only; there is no operator-facing rate-reset
   procedure in production.

## Open Questions / Deferred Items

- **GOV-14-ADR-01 (ADR-absence).** No ADR governs the five specific
  rule stages or the ACL matrix shape. ADR-010 covers the
  deterministic-before-probabilistic ordering but not the stage
  decomposition. A future ADR-RULE-ENGINE-STAGES would formalize the
  stage list and the fail-closed contract.
- **GOV-14-FILENAME-01 (prompt divergence).** The queued EA prompt
  references `deterministic_policy_checker.py`, which does not exist.
  The actual file is `rule_engine.py`. The stale reference should be
  corrected in any future EA prompt that cites it. Source
  (`rule_engine.py`) is authoritative per STYLE.md §Source Anchoring.
- **GOV-14-HOTRELOAD-01.** No hot-reload of rule state (ACL matrix,
  deny list, rate-limiter budget). Every change requires a PA restart.
  Re-opening this question would require an ADR explaining how
  mid-adjudication matrix drift is ruled out.
- **GOV-14-THREAD-01.** `RateLimiter` is single-threaded by design.
  If the PA vsock listener is ever refactored to multi-threaded, the
  limiter becomes a correctness hazard; document this as a
  pre-refactor gate.
- **GOV-14-VERB-METADATA-01.** The `ActionVerb` enum has no metadata
  beyond the string value. Verb-specific rule behavior is encoded in
  individual rule bodies (`evaluate_resource` verb filter). A future
  refactor could attach metadata (e.g., "EGRESS is always
  security-relevant") to the enum itself, enabling rule authors to
  opt into verb-class behavior declaratively.
- **GOV-14-BOOT-SEQUENCE-01.** The ordering of rule-engine
  initialization (ACL matrix load, deny-list load, rate-limiter
  construction) relative to measured-boot and vsock bind is implicit
  in the PA `entrypoint.py` start sequence. A future
  `boot-sequence.md` will make the ordering explicit. (Phantom per
  STYLE.md until GOV-15 lands.)
