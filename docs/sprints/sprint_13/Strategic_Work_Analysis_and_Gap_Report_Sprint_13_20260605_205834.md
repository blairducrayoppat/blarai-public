---
sprint_id: 13
sprint_name: "Tier-1 security finishers"
artifact: SWAGR (Strategic Work Analysis and Gap Report)
auditor: "Sprint Auditor (independent, adversarial)"
date: "2026-06-05"
sdv_version: 1
sdv_path: "docs/sprints/sprint_13/strategic_design_vision.md"
scr_path: "docs/sprints/sprint_13/strategic_completion_report.md"
main_tip_audited: "7081b6f"
test_baseline_reproduced: "1883 passed, 98 deselected, 0 failed (-m 'not hardware and not winui and not slow' on shared services launcher tests/integration tests/harness); reproduced independently by the Auditor (185.98s)"
verdict: "PASS"
criteria_tally: "5 MET / 0 PARTIAL / 0 FAIL"
critical_findings: 0
major_findings: 0
minor_findings: 4
---

# Strategic Work Analysis and Gap Report — Sprint 13

## 1. Executive verdict

**Overall: PASS.** Sprint 13 is the honest inverse of its predecessor. Where the Sprint-12
SWAGR found three MAJORs behind a "COMPLETE" SCR — a binding verification method silently
downgraded, a structural fail-open shipped as a "future consideration," and a success criterion
half-built and un-ticketed — Sprint 13's SCR over-states **nothing of substance**. I reproduced
the full sweep independently (`1883 passed, 98 deselected, 0 failed` — the SCR headline is honest
to the digit), repointed every criterion claim to the file/line/test that backs it, ran the three
EA test files plus the regression and secure-defaults guards, and probed the exact edge cases the
prompt flagged (the Luhn regex/digit-count alignment, the audit chain's tamper/removal/reorder
teeth, the dev-mode interlock truth table, the "built but wired into nothing" recurrence). Every
load-bearing claim survives the probe.

The defining test of this sprint's integrity was the same one the prompt named: **did the audit
sink actually get wired into the live Policy Agent, or only unit-tested in isolation?** The SCR's
own §1/§6 narrative says the merge gate caught EA-2's round-1 building a 38-test-green sink that
the production factory never invoked — the 2026-06-03 audit's own "built but wired into nothing"
anti-pattern recurring inside the sprint built to close it. I verified this against git history,
not the prose: round 1 (`17adf05`) had **no** `_build_audit_log` and `_build_adjudicator` did
**not** pass `audit_log=`; round 2 (`42b3e56`) adds the factory, passes the sink, defaults the
path to a real location, and locks it with a regression test that drives both an ALLOW and a
rule-DENY through the *production* factory and confirms records land on disk and re-verify. The
catch was real, the fix is real, and the lock has teeth. (BUILD_JOURNAL lesson 46.)

**Where the SCR is imprecise, it is imprecise in the conservative direction.** Its §5 carry-over
table says "New ticket recommended" / "recommend a tracked ticket" for the three audit-stream
follow-ups — but #605 (TPM signer swap), #606 (tail-deletion attestation), and #607
(retention/rotation) **already exist** in Vikunja, open, with thorough descriptions. The sprint
did more carry-over hygiene than its own completion record claims. That is the opposite failure
mode from Sprint 12, and it is a good problem to have.

My four findings are all **MINOR** — completeness and disclosure nuances, none of which
undermines a criterion or is exploitable on `main` today: (1) a pre-existing CREDIT_CARD
false-negative on PANs embedded in a >19-digit run, untouched by this sprint and arguably out of
its accuracy-fix scope; (2) the SCR's "41 tests" for EA-2 is an aggregate the record does not
itemise (38 audit_log unit tests + 3 production-wiring regression tests); (3) the HMAC stub key's
forgeability is correctly disclosed but its derivation deserves one explicit "this is not a
security boundary" callout at the call site, which the code already carries; (4) the SCR §5 text
understates the carry-over ticketing. None rises to MAJOR.

### Criteria tally

| # | Criterion (SDV §4) | Verdict |
|---|---|---|
| 1 | PII credit-card detector is Luhn-correct (both paths; `pii_mode` unchanged) | **MET** |
| 2 | Tamper-evident audit stream live in code (every decision persisted; pluggable signer; fail-closed) | **MET** |
| 3 | dev-mode interlock + loud opt-in built (running-default NOT flipped) | **MET** |
| 4 | Fleet vehicle proven (parallel builders, orchestrator-only merges, fragments) | **MET** |
| 5 | Suite green + live baseline recorded | **MET** |

**5 of 5 MET. 0 CRITICAL, 0 MAJOR, 4 MINOR.**

---

## 2. Per-criterion verification

### Criterion #1 — PII credit-card detector is Luhn-correct — MET

- **Luhn gate is real and registered as visible code, not a comment.** `_luhn_valid` implements
  the ISO/IEC 7812 mod-10 algorithm (`pgov.py:156-182`); `_luhn_filter` strips space/dash
  separators, length-gates 13-19, then calls it (`:185-194`); both are registered in a named
  per-label table `_POST_MATCH_VALIDATORS = {"CREDIT_CARD": _luhn_filter}` (`:200-202`).
- **Both detection paths are covered through a single chokepoint.** `find_pii_spans` applies the
  post-match validator and `continue`s (drops the span) when it returns False (`:347-349`).
  `check_pii` is implemented as `sorted({span.label for span in find_pii_spans(text)})`
  (`:205-212`) — so the block path (`check_pii`) and the redact path (`find_pii_spans` →
  `_apply_provenance_redaction`) both flow through the same Luhn gate. There is no second,
  un-gated detection path. This directly answers the prompt's "BOTH paths" probe: yes.
- **`pii_mode` is genuinely unchanged.** `validate_output(..., pii_mode: str = "block")` default
  is untouched at the function signature (`:803`); the live PGOV caller's shipped `pii_mode='off'`
  config is not modified by this sprint (confirmed: the diff touches only `pgov.py` detection
  internals + tests, not `default.toml`/`guest_runtime.toml` `pii_mode`). Accuracy fix only, per
  Decision 5. ✓
- **Teeth tests present and run green (107 passed).** `TestLuhnChecksum` (`test_pgov.py:858+`):
  canonical Visa/MC/AmEx/Discover PANs pass `_luhn_valid`; bad-checksum, all-same, sequential
  rejected; spaced/dashed cards pass `_luhn_filter`; 12-digit too-short rejected. Integration:
  spaced/dashed/compact PANs trigger CREDIT_CARD in `check_pii` AND `find_pii_spans`; non-Luhn
  13- and 16-digit IDs do NOT. **The meta-test (`test_meta_old_code_false_positive_no_longer_fires`,
  `:963`) reconstructs the exact pre-fix false positive** (`1234567890123` order-number) AND
  asserts the real Visa PAN still fires — guarding against a broken detector, exactly the
  lesson-30 shape. Both-path block+redact via `validate_output` covered (`:992`, `:1014`). I ran
  the file: **107 passed**.
- **Edge-case probe (regex vs digit-count alignment).** The regex `\b(?:\d[ -]*?){13,19}\b` and
  the `_luhn_filter` length gate `13 <= len <= 19` **align** for the 13-19 range — both gate the
  same window, so there is no slip-through in that band. The >19 boundary is the subject of
  MINOR-1 (a false-negative, pre-existing, not a slip-to-allow).
- **Verdict MET.** The SDV verification clause (Luhn-valid incl. spaced/dashed detected; non-Luhn
  not flagged; meta-test against the old no-checksum behaviour; full suite green) is satisfied on
  disk, in both paths.

### Criterion #2 — Tamper-evident audit stream is live in code — MET

- **The sink is ACTUALLY active in the live PA, not merely unit-tested.** This is the criterion
  the prompt told me to scrutinise hardest, and it passes:
  - `_build_audit_log` (`entrypoint.py:919-947`) constructs an `AuditLog.from_path(...)` with an
    `HmacSha256Signer` whenever `resolved.audit_log_path is not None` — and the path **defaults to
    a real location** `service_root/"data"/"audit"/"adjudication_audit.jsonl"` (`:603-604`) when
    no override is set, so on a default boot the sink is never None-skipped.
  - `_build_adjudicator` (`:950-972`) calls `_build_audit_log(resolved)` and passes
    `audit_log=audit_log` into `HybridAdjudicator.from_config` (`:963-971`). The production
    factory genuinely wires it.
- **All THREE `adjudicate_car` return points persist.** `_persist_context_with_car(ctx, car)` is
  called before every return: the rule-engine DENY short-circuit (`adjudicator.py:357`→358), the
  integrity-failure DENY (`:408`→409), and the full-GPU path (`:453`→454). I read each. No early
  return skips the sink.
- **Round-1 inertness confirmed against git, validating the merge-gate story.** `git show
  17adf05:.../entrypoint.py` has **0** references to `_build_audit_log`, and its `_build_adjudicator`
  ends `model_bin_path=...)` with no `audit_log=`. The "built but wired into nothing" recurrence
  was real; round 2 (`42b3e56`) closed it. The SCR's §1/§6 narrative is honest.
- **Fail-closed-on-write is real.** `AuditLog._write_record` raises `AuditSinkError` on OSError
  (`audit_log.py:487-490`); `append` propagates it; `_persist_context_with_car` does not catch it.
  Tests with teeth: `test_unwritable_path_raises_audit_sink_error`,
  `test_sink_error_propagates_from_adjudicator`, and crucially
  `test_sink_error_does_not_silently_allow` (`test_audit_log.py:467`) — an ALLOW whose sink write
  fails **raises** rather than returning an ALLOW context. Fail-closed coupling confirmed, not
  asserted in prose.
- **`verify()` actually catches tamper / removal / reorder — I read the test teeth, not the
  names.** `verify()` (`audit_log.py:492-555`) checks, per record, (a) `prev_hash` linkage against
  the prior record's `record_hash` (or GENESIS), (b) recomputed canonical SHA-256 == stored
  `record_hash`, (c) signature authenticity. Tests: middle/first/confidence/source-agent tamper →
  `AuditChainError` at the right index; remove-first (`:241`) and remove-middle (`:253`) detected
  via prev_hash break; swap-first-two (`:282`) and swap-middle (`:295`) detected; forged signature
  (all-zeros, `:487`) and wrong-key (`:499`) → "signature" reason. All run green (38 passed).
- **The tail-deletion limitation is honestly disclosed AND ticketed (#606) — not hidden.** This is
  a *real* gap and the SCR is straight about it. `test_remove_last_record_does_not_affect_remaining_chain`
  (`:264-273`) explicitly asserts truncating the newest record leaves a shorter-but-valid chain
  that `verify()` accepts, with a docstring naming the design property. The module docstring and
  carry-over #606 (S13-FU2, open, priority 2) both document it with the mitigation (external
  record-count attestation / WAL / TPM-sealed counter). Disclosed in code, in the SCR, and in a
  tracked ticket. The hash chain detects *internal* mutation; tail-truncation is a known,
  documented, ticketed residue — exactly the honest shape.
- **HMAC stub key derivation scrutinised.** `_build_audit_log` derives the key as
  `sha256(b"BlarAI-audit-hmac-stub-v1::" + path.encode())` (`entrypoint.py:943-945`) — a
  deterministic, per-install, filesystem-recomputable value. The docstring (`:932-936`) is explicit
  that this is **NOT a security boundary on its own** (an attacker with filesystem access
  recomputes it); the hash-chain is the tamper-evidence, and the signer becomes non-forgeable only
  once the TPM-sealed key (carry-over #605) replaces this stub. Honest. (See MINOR-3 for the one
  call-site polish.)
- **Production round-trip regression has teeth.** `TestAuditLogWiredIntoProductionAdjudicator`
  (`test_entrypoint.py:458-602`) drives a real adjudication through `_build_adjudicator` and
  asserts `has_audit_log is True`, the record lands on disk at the resolved path, and the reopened
  chain re-verifies — for both the full-GPU ALLOW path and the rule-DENY short-circuit. 15 passed.
- **Verdict MET.** Sink active in the live PA, all three returns persist, ALLOW+DENY both persist,
  fail-closed real, verify() catches tamper/removal/reorder with real teeth, tail-deletion honestly
  disclosed + ticketed. The SDV clause is fully satisfied. (Real non-forgeability awaits the TPM
  signer — #605, explicitly out of scope, correctly named.)

### Criterion #3 — dev-mode interlock + loud opt-in built (running-default NOT flipped) — MET

- **The running default is genuinely NOT flipped — I verified the boundary by direct probe.**
  `resolve_dev_mode(DeploymentMode.HOST)` returns **True** (the deliberate Tier-1 default,
  `dev_mode_guard.py:90-91`); GUEST returns False. `resolve_network_facing()` default is **False**
  (`runtime_config.py:52-53`). So HOST still resolves to dev-mode (loudly), the flip to
  `dev_mode=false` is deferred, and the air-gapped posture holds. This is the criterion's boundary
  and it is honored.
- **The interlock is called BEFORE service construction.** In `launcher/__main__.py`, the security
  posture block (`:450-473`) resolves dev_mode + network_facing and calls
  `assert_dev_mode_network_facing_safe` at `:461-465` — *before* the admin check (Step 1, `:498`),
  VM start (Step 2), pipeline build (Step 2.5), and any service. A refusal returns 1 before
  anything is touched. ✓
- **None → unsafe (deny-by-default) holds.** Direct probe of the truth table:
  `(dev=T, net=T)` → REFUSE; `(None, None)` → REFUSE; `(dev=T, net=None)` → REFUSE (unknown net
  treated unsafe); `(dev=T, net=F)` → ALLOW (today's HOST path); `(dev=F, net=T)` → ALLOW (future
  prod); `(None, net=F)` → ALLOW. Matches `dev_mode_guard.py:130-134` (`True if x is None else x`).
- **The daily HOST launch is not broken.** All three launcher dev_mode call sites flow through the
  single resolved `_dev_mode` (gateway uses `gateway_dev_mode = _dev_mode`, `:763`; PA/AO factories
  pass `dev_mode_override=_dev_mode`, `:615`/`:681`) — "resolve once, use everywhere," so the
  interlock covers the gateway too. The SCR §2.1 records `test_launcher.py` 19/19 on the
  models-bearing tree including `test_production_happy_path`; `launcher/tests` pass in my full sweep.
- **`test_secure_defaults.py` is unchanged + green.** `git log 56703cd..HEAD -- tests/security/test_secure_defaults.py`
  is empty (last touched at `9e693be`, a Tier-1 commit *before* this sprint's kickoff `56703cd`).
  I ran it: **2 passed**. Untouched and green, as the criterion requires.
- **Loud banner is real and reachable.** `resolve_dev_mode` emits a `logger.warning` + a multi-line
  INSECURE banner to stderr whenever the result is True (`dev_mode_guard.py:95-106`); my probe
  confirmed the banner fires on a HOST resolution. 22 interlock tests pass.
- **Verdict MET.** Interlock refuses (T,T) before service construction, allows the two safe
  combinations (one loud), deny-by-default on unknown, running default deliberately not flipped,
  secure_defaults untouched + green. The SDV clause is satisfied.

### Criterion #4 — The fleet vehicle is proven — MET

- **No builder committed to `main`; merges are orchestrator-only `--no-ff`.** The three feature
  merges `d910739` (EA-1), `ea879ed` (EA-3), `a8284d1` (EA-2) each have **2 parents** (`git rev-list
  --parents` → 3 tokens), confirming genuine `--no-ff` merge commits, not fast-forwards. The builder
  work landed on branches (`41cd757`, `27612b4`, `17adf05`→`42b3e56`) and was merged by the
  orchestrator. (Authorship is uniformly "Blair" because all subagents run under the one git
  identity; the SDV criterion is about *merge topology and the BUILD_JOURNAL boundary*, both of
  which hold — not about distinct commit authors.)
- **No builder touched `BUILD_JOURNAL.md`.** The only BUILD_JOURNAL edit in the sprint range is the
  orchestrator fold `aa41a0e` (`docs(journal): fold Sprint 13 … lessons 46-47`). Builder branch
  commits do not touch it.
- **The one minor deviation (EA-2 fragment-as-file) is real, harmless, and reconciled — confirmed
  against git, not just the SCR's word.** `docs/journal_fragments/2026-06-05_audit-stream-tamper-evident.md`
  was **added in `17adf05`** (EA-2 round 1, on its branch) and **deleted in `aa41a0e`** (the fold).
  So EA-2 wrote a fragment *file* instead of reporting text — which the dispatch said not to do —
  but it (a) did NOT touch `BUILD_JOURNAL.md`, and (b) was folded into lessons 46-47 and deleted at
  the quiet-tree fold. The journal_fragments dir now holds only README.md. This is exactly the SCR
  §3/§6 disclosure; the deviation is process-cosmetic, not a control or topology breach.
- **Lessons 46-47 are portfolio-grade and present.** `BUILD_JOURNAL.md:103` (lesson 46 — "a control
  wired into a function but not into the boot path is still built-but-wired-into-nothing") and `:105`
  (lesson 47 — "a comment that claims a property the code does not enforce is governance debt").
  Both name the trade-off and the evidence; both compound on prior lessons.
- **Verdict MET.** Parallel worktree builders, orchestrator-only `--no-ff` merges, no builder commit
  on `main` or in `BUILD_JOURNAL.md`, fragments folded by the orchestrator. The single fragment-file
  deviation is disclosed and reconciled. The SCR's "MET (1 minor deviation)" is accurate; I confirm
  the deviation is the *only* one and that it was folded+deleted.

### Criterion #5 — Suite green + live baseline recorded — MET

- **Reproduced to the digit.** `cd /c/Users/mrbla/BlarAI && .venv/Scripts/python.exe -m pytest
  shared services launcher tests/integration tests/harness -q -m "not hardware and not winui and not
  slow" -p no:cacheprovider` → **`1883 passed, 98 deselected, 2 warnings in 185.98s`. 0 failed.**
  Matches `test_baseline_at_completion: "1883 passed, 0 failed, 98 deselected"` exactly. (A
  concurrent background run of the same command also exited 0.)
- **The four finisher guard groups are additive-green** within that total: 107 pgov (incl. the Luhn
  meta-test), 38 audit_log (incl. tamper/removal/reorder/forged-sig/fail-closed), 22 dev-mode
  interlock, plus the 3-test production-wiring regression in `test_entrypoint.py`. I ran each file
  individually and confirmed the counts.
- **The kickoff→completion delta is explained and honest.** Kickoff baseline 1797 → completion 1883
  (+86) from the finishers' own tests, zero regressions; the SCR supersedes the stale 1501/1661
  snapshots per the baseline-drift discipline. The `tools/tests` pre-existing collection error
  (`ModuleNotFoundError: tools._vikunja_client`, 4 errors) is genuinely unrelated to Sprint 13 and
  correctly excluded — I confirmed it is a Vikunja-MCP module-path issue, not security code.
- **Verdict MET.** Suite green on the integrated tree, count recorded in the SCR, finisher guards
  additive-green, delta explained.

---

## 3. Adversarial findings

All four findings are **MINOR**. None undermines a criterion, none is exploitable on `main` today,
and three of the four are disclosure/precision nuances rather than code gaps. I went looking for the
Sprint-12 failure modes — a downgraded verification method, a fail-open shipped as a "future
consideration," a half-built un-ticketed criterion, a built-but-inert recurrence the merge gate
missed — and found none of them. The sprint is clean.

### MINOR-1 — CREDIT_CARD false-negative on a valid PAN embedded in a >19-digit run (pre-existing; not introduced or closed by this sprint)

**Evidence.** The CREDIT_CARD regex `\b(?:\d[ -]*?){13,19}\b` is anchored by `\b` on both ends and
capped at 19 repetitions. In a pure run of 20+ digits, no 13-19-digit sub-window has a word boundary
on both sides, so the regex matches **nothing** — even when the run contains an embedded valid
16-digit PAN. Direct probe:
- `check_pii("99994111111111111111")` (4×`9` + valid Visa `4111111111111111`, 20 digits) → `['PHONE_US']`, **no CREDIT_CARD**.
- `check_pii("44111111111111110000")` (20 digits, valid Visa in the middle) → `['PHONE_US']`, **no CREDIT_CARD**.
- For contrast, a standalone 19-digit Luhn-valid PAN (`4000000000000000006`) IS detected.

So a card number concatenated into a longer digit string evades CREDIT_CARD detection. **This is a
false-negative, not a slip-to-allow** (the detector errs toward *not* flagging, which on the
redact-at-egress path means under-redaction, not over-disclosure of a control bypass).

**Pre-existing.** `git show 56703cd:.../pgov.py` shows the identical regex `\b(?:\d[ -]*?){13,19}\b`
at kickoff. The Luhn fix changed the *post-match validator*, not the candidate regex, so this
boundary behaviour is unchanged by Sprint 13 — it neither introduced nor closed the gap.

**Why it matters (and why it is only MINOR).** SDV criterion #1 says "Luhn-valid cards … detected,"
and a PAN buried in a 20-digit run is not. But: (a) the audit's Domain 5 finding was specifically
about *false positives* (any long run flagged as a card) — which this sprint fixed — not about
embedded-PAN recall; (b) `pii_mode='off'` ships, so the detector is inert on the live path today;
(c) the gap is pre-existing and out of the stated accuracy-fix scope; (d) it is a recall edge case,
not a fail-open. It does not move criterion #1 off MET, but it is the one place the criterion's
literal "cards detected" is incomplete, and an honest record should name it.

**Rating: MINOR** — pre-existing, not a regression, not exploitable, off-path today; a recall
completeness nuance the criterion's wording does not cover.

**Recommended disposition.** Add a one-line note to carry-over #607 (or a new low-priority hardening
ticket) that the CREDIT_CARD candidate regex does not detect a PAN embedded in a contiguous >19-digit
run, to be revisited if/when `pii_mode` moves off `off` for the egress path. No source change this
sprint (the criterion is MET on the audit's actual ask).

### MINOR-2 — The SCR's "41 tests" for EA-2 is an un-itemised aggregate

**Evidence.** SCR §2.2 and §3 cite "41 tests" for EA-2. On disk: `shared/tests/test_audit_log.py`
is **38** tests (I ran it: 38 passed), and the EA-2 production-wiring regression lives separately in
`services/policy_agent/tests/test_entrypoint.py::TestAuditLogWiredIntoProductionAdjudicator` (3
tests). 38 + 3 = 41. The number is correct but the SCR does not say it spans two files, which
briefly reads as if `test_audit_log.py` alone carries 41.

**Why it matters.** Trivially — it is a documentation precision nit. I flag it only because the
audit's standing instruction is to name where every claimed count lives, and a future reader
reconciling "41" against `test_audit_log.py` (38) would momentarily mismatch.

**Rating: MINOR** — documentation precision, no substance.

**Recommended disposition.** None required; if the SCR is ever revised, itemise "38 audit_log unit +
3 production-wiring regression = 41." Not blocking.

### MINOR-3 — HMAC stub forgeability is disclosed in prose; one explicit "not a security boundary" assertion at the call site would close the loop

**Evidence.** The stub key (`sha256(label + path)`, `entrypoint.py:943-945`) is filesystem-
recomputable. This is correctly and repeatedly disclosed: the `_build_audit_log` docstring
(`:932-936`), the module docstring (`audit_log.py:108-118`), the `HmacSha256Signer` docstring, and
carry-over #605 all state the signer is tamper-*evident*-only until the TPM swap. The hash-chain —
not the signature — is the tamper-evidence today; the signature hardens authenticity and becomes
non-forgeable only with the TPM-sealed key. This is honest and consistent.

**The one residue.** There is no test that *asserts* the stub posture is understood as non-binding
— e.g., a test demonstrating that a filesystem-capable attacker who recomputes the key produces a
record that `verify()` accepts (proving the signature is not the boundary, the chain is). The
limitation is documented everywhere in prose but never encoded as a visible-fail assertion, which is
the lesson-30/lesson-47 shape this very sprint articulated (lesson 47: "encode the secondary gate as
something the reader can see fail, not as prose").

**Why it matters.** Only as defense-in-depth on the *understanding* of the stub: the disclosure is
complete, so no one is misled today; but the project's own lesson 47 argues a property worth stating
is worth encoding. Low value — this is a stub being replaced by #605 — but consistent with the
sprint's stated discipline.

**Rating: MINOR** — disclosure is complete; the gap is only that the stub's non-binding nature is
prose, not a test.

**Recommended disposition.** Fold into #605 (the TPM swap): when the TPM signer lands, add the
contrast test (stub key recomputable → forgeable signature accepted by chain; TPM key →
non-recomputable) so the upgrade's value is encoded, not asserted. No action this sprint.

### MINOR-4 — The SCR §5 carry-over table understates its own ticketing (the favorable direction)

**Evidence.** SCR §5 lists the three audit-stream follow-ups with "New ticket recommended" (TPM
swap), "(append-only/unbounded default by design)" (retention), and "recommend a tracked ticket"
(tail-deletion). But all three **already exist** in Vikunja, open, with full descriptions:
- **#605** (S13-FU1, Security): TPM signer swap — drop-in at `_build_audit_log`, gates #598.
- **#606** (S13-FU2, Architecture+Security, prio 2): tail-deletion attestation / WAL.
- **#607** (S13-FU3, Infrastructure+Security, prio 1): retention/rotation, chain-continuity-aware.

So the carry-over set is **complete and ticketed** — the exact opposite of Sprint-12's silently-
dropped, un-ticketed carry-overs (that SWAGR's MAJOR-3). The SCR's "recommend a ticket" language is
stale relative to its own execution: the tickets were filed (created 2026-06-05 15:54, before the
SCR commit `14c413c`).

**Why it matters.** It does not — except that an auditor reading only the SCR §5 table would
conclude the tickets are pending creation, when they exist. A completion record should reflect that
its carry-overs are *tracked*, not *recommended*. This is a precision miss in the safe direction.

**Rating: MINOR** — the work (ticketing) is done and better than claimed; only the SCR wording lags.

**Recommended disposition.** If the SCR is revised, replace "recommend a tracked ticket" with the
live ticket numbers (#605/#606/#607). Not blocking; the substance is already correct on the board.

### Note (no finding) — Verification-method honesty held; the Sprint-12 MAJOR-1 trap was genuinely avoided, not skipped

The prompt asked whether the SCR's claim to have avoided Sprint-12's MAJOR-1 (promising a heavier
verification method than delivered) is honest, or whether a needed real-model/real-UI test was
quietly skipped. **It is honest.** All three finishers are deterministic and model/UI-independent: a
pure-function Luhn checksum, a stdlib hash chain, and launcher/config logic. None touches the Qwen3
model or the WinUI screen, so Layer-B (real-model) or Layer-C (real-UI) automated tests would add
**zero signal** — and the SDV §4 preamble + §13(4) say exactly this *in advance*, as a deliberate
non-goal, not a post-hoc excuse. The delivered Layer-A-with-teeth coverage is the correct method for
this work (lesson 30). Crucially, the SCR does **not** claim the production-posture live-verify
(`dev_mode=false`, real keys/certs, TPM signing) — it names that as the LA's batched Tier-2 step
(§4), which is the correct boundary. This is the inverse of the Sprint-12 honesty miss: the method
matches the work, and the deferred production posture is named, not silently dropped. No SDV
amendment is needed because no criterion's literal text was deviated from (contrast Sprint-12, where
the §4 method *was* downgraded without amendment).

### Note (no finding) — No "built but wired into nothing" recurrence survives elsewhere

The prompt asked me to look for any *other* built-but-inert recurrence the merge gate might have
missed. I checked the three load-bearing wirings end-to-end: (1) the audit sink IS invoked at all
three `adjudicate_car` returns AND constructed by the production factory with a real default path
(criterion #2); (2) the dev-mode interlock IS called before service construction on the real
launcher path, not only in tests (criterion #3); (3) the Luhn gate IS the single chokepoint for both
PII detection paths, not a parallel un-gated path (criterion #1). The one recurrence that *did* occur
(EA-2 round 1) was caught by the merge gate and fixed in round 2, with a regression lock. I found no
surviving inert mechanism.

---

## 4. Carry-over reconciliation

The SCR §5 lists five carry-overs. Assessed against Vikunja + disk:

| Carry-over | SCR framing | Auditor assessment |
|---|---|---|
| TPM signer swap for the audit stream | "New ticket recommended" | **Ticketed and open: #605** (S13-FU1, Security). Correctly carried; the swap point (`_build_audit_log`) is real and mirrors `_build_jwt_minter`. SCR wording understates that the ticket exists (MINOR-4). |
| dev-mode running-default flip (`dev_mode=false` for HOST) | Tier-2 (cert-gated) + LA live-verify | **Confirmed genuinely deferred, not skipped.** HOST still resolves dev_mode=True (criterion #3 probe); the flip is blocked on cert provisioning (audit Domain 3); the interlock already guards the transition. This is an explicit SDV §13(1) non-goal, honestly out-of-scope. No ticket needed (it is a tier-gated LA step, tracked under the campaign #598 gate). |
| Audit-stream retention/rotation | "Sprint 14 operational hardening … no cap enforced (by design)" | **Ticketed and open: #607** (S13-FU3, prio 1). `on_rotate` is a real stub hook (`audit_log.py:472-473`); unbounded-by-design is documented. Correctly carried. |
| Audit-stream tail-deletion limitation | "Documented in the module; recommend a tracked ticket" | **Ticketed and open: #606** (S13-FU2, prio 2). The limitation is real, documented in the module + tested as a known property (`test_remove_last_record_does_not_affect_remaining_chain`), and ticketed with the mitigation. This is a genuine gap, honestly handled end-to-end. |
| Measured-boot attestation (4th Tier-1 item) | ceremony-bound, deferred | Confirmed out-of-scope per SDV §5.2(1)/§13(3); needs on-chip attestation. Not this no-ceremony wave. No ticket assessed here (campaign-tracked). |

**Completeness check.** The prompt asked whether #605/#606/#607 + the deferred items are complete or
whether something was dropped. **Nothing is dropped.** All three audit-stream follow-ups are filed,
open, and described; both deferred items (the dev-mode flip, measured-boot) are explicit SDV
non-goals correctly named as LA/ceremony steps. The EA tickets #601/#602/#603 are all `done: true`.
The tracking task #604 remains open (correct — it closes after this SWAGR). This is the inverse of
the Sprint-12 carry-over set, which the predecessor SWAGR found incomplete (two silently-dropped
items). Sprint 13's carry-over hygiene is, if anything, **better than its own SCR §5 text claims**
(MINOR-4).

---

## 5. Disposition

**PASS. 5 MET / 0 PARTIAL / 0 FAIL. 0 CRITICAL, 0 MAJOR, 4 MINOR.**

The three Tier-1 finishers are genuinely built, deterministically tested with teeth, and shipping on
`main` at `7081b6f` (build scope). The headline test number (`1883 passed, 0 failed, 98 deselected`)
is honest and I reproduced it independently. The criterion the prompt told me to scrutinise hardest
— *is the audit sink actually live in the PA, or only unit-tested?* — passes against git history and
a production round-trip regression: the round-1 built-but-inert recurrence was real, the merge gate
caught it, round 2 wired it with a lock that fails the day the wiring is removed. The dev-mode
boundary (HOST still dev_mode=True, default not flipped) is honored; the interlock is called before
service construction with correct deny-by-default semantics; `test_secure_defaults.py` is untouched
and green. The fleet vehicle held: orchestrator-only `--no-ff` merges, no builder commit on `main` or
in `BUILD_JOURNAL.md`, the single fragment-file deviation folded + deleted.

This sprint is the honest inverse of Sprint 12. The Sprint-12 SWAGR found three MAJORs behind a
"COMPLETE" SCR — a downgraded verification method without an amendment, a structural fail-open shipped
as a "future consideration," and a half-built un-ticketed criterion. **Sprint 13 has none of these.**
The verification method matches the deterministic work (Layer-A-with-teeth, with the production
posture honestly named as the LA's step, no SDV deviation to amend); there is no fail-open shipped as
prose; and every carry-over is ticketed (#605/#606/#607) — the SCR's §5 wording actually *understates*
its own ticketing. My four MINOR findings are all completeness/disclosure nuances: a pre-existing
CREDIT_CARD recall edge case off the live path (MINOR-1), an un-itemised test aggregate (MINOR-2), a
prose-not-test stub-forgeability disclosure (MINOR-3), and a stale "recommend a ticket" phrasing for
tickets that exist (MINOR-4). **None blocks calling the sprint complete; none requires a source change
or an SDV amendment this sprint.**

The recommended dispositions are all light-touch and non-blocking: optionally fold MINOR-1 into #607
and MINOR-3 into #605 as scope notes; optionally tighten the SCR's §2.2/§5 wording (MINOR-2/MINOR-4)
if it is ever revised. The production-posture live-verify and the TPM signing ceremony remain the LA's
batched Tier-2 steps (SCR §4), correctly deferred. The air-gap stays up; #598 remains the go/no-go.

Sprint 13 closes honestly as a clean Tier-1 increment with no over-claim — a low-risk, well-executed
proving ground for the build→review→merge fleet vehicle before Tier 2's heavier lift.
