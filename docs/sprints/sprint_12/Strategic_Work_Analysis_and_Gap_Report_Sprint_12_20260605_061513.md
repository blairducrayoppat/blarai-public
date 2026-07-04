---
sprint_id: 12
sprint_name: "Provenance- and intent-aware content handling"
artifact: SWAGR (Strategic Work Analysis and Gap Report)
auditor: "Sprint Auditor (independent, adversarial)"
date: "2026-06-04"
sdv_version: 3
sdv_path: "docs/sprints/sprint_12/strategic_design_vision.md"
scr_path: "docs/sprints/sprint_12/strategic_completion_report.md"
main_tip_audited: "90b2bed"
test_baseline_reproduced: "1661 passed, 2 skipped, 95 deselected (-m 'not slow'); reproduced independently by the Auditor"
verdict: "PASS-WITH-GAPS"
criteria_tally: "5 PASS / 2 PARTIAL"
critical_findings: 0
major_findings: 3
---

# Strategic Work Analysis and Gap Report — Sprint 12

## 1. Executive verdict

**Overall: PASS-WITH-GAPS.** The sprint's security spine is real, on `main`, and rests on
deterministic mechanisms that the headless suite proves regardless of model behaviour. I
reproduced the full sweep independently (`1661 passed, 2 skipped` — the SCR's headline number is
honest to the digit), repointed every claim to the file/line/test that backs it, and probed for the
holes the predecessor SWAGRs taught me to expect. The provenance foundation, the re-pointed Layer-3
gate, the leakage-feed redesign, and the #570 in-process adjudication are all genuinely built and
genuinely tested with teeth.

**The sprint is NOT a clean 7/7, and the SCR over-states completeness in two places it should have
flagged louder.** Two criteria are PARTIAL, not PASS:

- **Criterion #5 (workspace-folder input)** is delivered only as the interim `/external` channel; the
  contracted workspace-folder read path, scope-limit, and pin affordance are **not built** and there
  is **no real-UI (Layer C) automated test** — the SDV made that test a *deliverable, not optional*.
  The SCR acknowledges EA-6-proper as a carry-over but still implies the criterion is "serviced." It
  is serviced in *function*, not in *contract*.
- The SDV's central verification promise — a **real-model (Layer B) / real-UI (Layer C) automated
  test authored in the same increment** for every user-facing criterion (#3–#7) — was **not kept for
  any criterion**. No Layer-B (real Qwen3-on-Arc) or Layer-C (pywinauto) automated test landed this
  sprint. The deterministic `call_count` / `retrieved_chunks` assertions are good headless tests
  against a *mocked* model; they are explicitly NOT the real-model coverage the SDV §4 made binding.
  The binding gate the sprint promised was downgraded to manual LA live-verify without an SDV
  amendment recording the deviation. This is the single largest honesty gap and the root of both
  PARTIALs and MAJOR-1.

None of this rises to CRITICAL: the deterministic controls are proven, the runtime ships
secure-by-default, the live-verify did happen (manually), and every shortfall is a tracked
carry-over. But the SCR's "COMPLETE (security scope)" disposition is **stronger than the evidence for
the verification *method*** the sprint contracted for.

### Criteria tally

| # | Criterion | Verdict |
|---|---|---|
| 1 | Provenance foundation (enum threaded, fail-closed default) | **PASS** |
| 2 | ADR-023 ratified (+ DECISION_REGISTER) | **PASS** |
| 3 | Provenance-driven action-lock, secure-by-default | **PASS** |
| 4 | Leakage control redesigned (untrusted-only, flag honored) | **PASS** |
| 5 | Workspace-folder input | **PARTIAL** |
| 6 | Intent disambiguation | **PARTIAL** |
| 7 | #570 closed (enforced, not relocated) | **PASS** |

---

## 2. Per-criterion verification

### Criterion #1 — Provenance foundation — PASS

- `Provenance` enum (`TRUSTED_LOCAL` / `TRUSTED_MEMORY` / `UNTRUSTED_EXTERNAL`) at
  `context_manager.py:93-120`; threaded as `grounded_provenance` index-aligned with `grounded_chunks`
  (`:150-153`, appended in lockstep `:293`, cleared in lockstep `:509`).
- Consumed by the gate via `has_untrusted_content` (`:352-372`) and by the leakage feed via
  `get_untrusted_chunk_texts` (`:574-591`).
- **Fail-closed default is enforced, not merely asserted.** `_SOURCE_TO_PROVENANCE.get(source,
  Provenance.UNTRUSTED_EXTERNAL)` at `:276` maps any unrecognized `source=` to untrusted;
  `has_untrusted_content` (`:369-372`) treats anything not in the two trusted tiers as untrusted.
  Tested: `test_unrecognized_source_fails_closed_to_untrusted`, `test_untrusted_provenance_trips_gate`,
  `test_has_untrusted_content_false_on_unknown_session` (`test_context_manager.py` `TestProvenanceFoundation`,
  \~lines 599-703). I ran these — green.
- Evidence on disk matches the SDV verification clause exactly (per-tier unit tests; enum threaded
  through ContextManager and read by the gate + validator; unknown ⇒ untrusted).

### Criterion #2 — ADR-023 ratified — PASS

- `docs/adrs/ADR-023-Provenance-Based-Trust-Model.md` present on `main` (commit `41acbcf`), Status
  ACCEPTED, supersedes #558, amends ADR-013 §2.1 — all four required content elements present
  (taxonomy §2.1; Layer-3 read rule §2.2; `/trust` fate §2.3; #570 mediation §2.4; path-not-taken §5).
- **Amendment 1** is appended in the same document (§A1.1–A1.8) and is internally consistent.
- `docs/DECISION_REGISTER.md:32` carries the ADR-023 row including the Amendment-1 clause and the
  #558 supersession. Verified.
- One nit (not a gap): the LA "\~20-minute-ratifiable" intent is contradicted by the document's actual
  size (Amendment 1 roughly doubled it). Defensible — the amendment was an in-session design pivot —
  but the "tight, 20-min" framing in the SDV no longer describes the artifact. Documentation, not
  substance.

### Criterion #3 — Provenance-driven action-lock, secure-by-default — PASS

- Gate repointed from `has_user_loaded_documents` to `has_untrusted_content` at `entrypoint.py:1414-1419`.
- **Secure-by-default restored on disk:** `block_tools_on_untrusted_content = true` in BOTH
  `default.toml:66` and `guest_runtime.toml:55` (I grepped both — the `false` that the SDV §2.2 said
  shipped is gone). Back-compat on the legacy key at `entrypoint.py:614-621`. A startup WARNING fires
  if the gate is disabled (`:454-461`) — a real misconfiguration-drift defense.
- Trusted-local fires tools (`test_tool_fires_when_trusted_user_document_present`); untrusted blocks
  (`test_tool_call_refused_when_untrusted_content_present`); `/unload` restores
  (`test_untrusted_then_unload_then_tool_fires`, the 2026-05-26 bug). All green.
- Fail-closed-default-on-unknown-provenance ⇒ locked is covered at the foundation layer (criterion
  #1) and inherited by the gate.
- **Caveat folded into MAJOR-1/MAJOR-2 below, not a fail here:** the *shipped* gate (Amendment 1
  applied, commit `90b2bed`) fires only for `GUARDED`-tier tools, and all four shipped tools are
  `SAFE`, so the action-lock is **dormant in production today**. This is the ratified, intended
  behaviour (ADR-023 A1.5 states it explicitly), and the lock is proven by tests that patch a tool to
  `GUARDED`. It is correct — but it means the live-verified-on-2026-06-04 lock behaviour is no longer
  what ships, which the SCR §4 does not flag at the point it lists the live-verify as ✅ (see MAJOR-2).
- Verdict PASS on the criterion *as written* (the gate reads provenance, secure-by-default, `/unload`
  fixed). The verification-method shortfall is scored once, in MAJOR-1, not re-deducted per criterion.

### Criterion #4 — Leakage control redesigned — PASS

- Stage-5 detector is fed **untrusted-only** chunks: `entrypoint.py:1522-1526` passes
  `get_untrusted_chunk_texts(session_id)` (gated on the flag) instead of all grounded content. The
  false-positive root cause (a summary is cosine-similar to its trusted source) is fixed by
  *exclusion*, not a threshold tweak — matching ADR-023 §2.5 and rejecting the path-not-taken (#579).
- **`leakage_detection_enabled` flag is now honored** (was vestigial): resolved at `:611-613`, read at
  `:1524`. Tested: `test_leakage_detection_disabled_feeds_empty`.
- The "8 accessor unit tests + 1 previously-skipped wiring test re-enabled and green" claim is
  **true**: at `84f21de`, `test_pgov_leakage_wiring.py::TestPGOVLeakageWiring::test_validate_output_receives_chunks_when_grounded`
  carried `@pytest.mark.skip("Un-skip and update when the leakage detector is redesigned.")` (verified
  via `git show 84f21de:...`). HEAD replaces it with the un-skipped
  `test_untrusted_content_is_fed_to_leakage_detector` plus `test_trusted_document_is_not_fed_to_leakage_detector`.
  `TestGetGroundedChunkTexts` retains its 8 accessor tests. I ran the file: 15 passed, 0 skipped.
- **One honesty gap acknowledged (and the SCR is straight about it):** the untrusted-firing path was
  **not live-exercised** — no untrusted-leakage scenario was run on the real model. The live-verify
  (SCR §4) covered only the *negative* case (a trusted summary produces no false hold). So "fires on a
  real untrusted leak" is proven by a *mocked* assertion, never by the real model. See MINOR-1; this
  is consistent with the SDV's own admission that mocking is what let the original false-positive
  through — and the sprint did not close that exact gap for the firing direction.
- PASS: the criterion's three sub-claims (no suppression of legitimate answers; flag honored; fires on
  untrusted only) are all backed; the verification-depth shortfall is captured in MAJOR-1 + MINOR-1.

### Criterion #5 — Workspace-folder input — PARTIAL

- **Not built.** No workspace-folder read path feeding `provenance=TRUSTED_LOCAL`; no folder-scope
  limit; no new pin affordance. The deliverable row (SDV §6: "Workspace-folder read path + pin
  affordance") has no corresponding code commit.
- The interim `/external` channel (`transport.py:578-613`, `entrypoint.py:1262-1275`,
  `MainWindow.xaml.cs:198`) delivers the **untrusted** input function — it is the wrong half of #583
  to point at this criterion. #583 is the *trusted-local workspace* UX (retire the upload metaphor);
  `/external` is the *untrusted* opt-in. The SCR §3 says the criterion's "function is covered by
  `/external`" — that conflates two different features. `/external` does not let a user "drop files in
  a permitted workspace folder and ask about them by name."
- **The SDV-mandated real-UI (Layer C, pywinauto) automated test does not exist.** SDV §4 criterion #5
  and §6 made it a deliverable.
- Carry-over is correctly tracked (#583 open, Status:Draft, SCR §5.1). Verdict PARTIAL: the criterion
  is deliberately deferred with a ticket, which is legitimate sprint hygiene — but it is **not
  serviced**, and the SCR's framing implies more coverage than exists. A PARTIAL (not FAIL) because
  the deferral is explicit and the untrusted-input function it stands in for is real.

### Criterion #6 — Intent disambiguation — PARTIAL

- The SDV criterion has **two halves**: (a) an ambiguous multi-referent turn yields a *one-line
  clarification* rather than a confused answer; (b) a single-referent turn answers directly (freshest
  pin wins).
- **Half (b) is built and tested.** The fresh-attachment-is-the-referent fix (EA-7, commit `15d9203`)
  clears prior grounded docs on a new attachment (`entrypoint.py:1195-1198`) and records the recency
  rule in the built context (`context_manager.py:428-437`). Tested:
  `TestFreshAttachmentReferent::test_fresh_attachment_clears_prior_grounded_documents` +
  `test_same_turn_multi_attachments_kept_together`. Green. This is the #585 live-verify bug fix.
- **Half (a) — the clarification step — is NOT built.** There is no prompt-assembly disambiguation
  step that detects ">1 high-relevance candidate" and emits a one-line clarification. I searched the
  AO `src/` for any clarification/disambiguation affordance and found none; the SCR §2.2 maps #585 to
  the *referent fix* only. The SDV §5.1(7) "cheap disambiguation step at prompt-assembly when >1
  high-relevance candidate exists" was not delivered.
- **No real-model (Layer B) automated test for the two-referent and one-referent cases**, as SDV §4
  #6 required.
- Verdict PARTIAL: the freshest-pin-wins half shipped and is genuinely useful (it closed a live bug);
  the clarification-on-ambiguity half — the part the criterion title actually names — did not. The SCR
  treats #585 as fully serviced; it serviced the recency half, not the disambiguation half. This is
  the criterion where the SCR's silence is least defensible: there is no carry-over ticket for the
  missing clarification step (see MAJOR-3).

### Criterion #7 — #570 closed (enforced, not relocated) — PASS

- AO tool dispatch is adjudicated **before execution** at `entrypoint.py:1441-1448` via
  `_adjudicate_tool_dispatch` (`:149-188`), which builds a CAR (`build_car`, `EXECUTE`,
  `resource=tool:<name>`) and runs the PA's **own** `DeterministicPolicyChecker.check` in-process —
  single source of truth, not a copy. P-004 is reachable: a CAR carrying an external URL hits RULE 3
  `DENY_EXTERNAL_NETWORK` (`gpu_inference.py:399-405`).
- **Enforced, not a convention:** `test_pa_deny_refuses_tool_at_ao_loop` patches the adjudicator to
  DENY and asserts the tool does **not** execute (call_count == 1, `mock_adjudicate.assert_called_once`).
  `test_adjudicate_helper_allows_local_denies_external_network` proves a local tool returns `None`
  (allow) and a `http://…` CAR returns `("DENY","DENY_EXTERNAL_NETWORK")` — P-004 reachable from the
  AO loop, not only the PA boundary. Both green.
- **Fail-closed:** an adjudication exception returns `("DENY","ADJUDICATION_ERROR")` (`:183-188`).
- **Honest scope-narrowing the Auditor flags as adequate, not a gap:** the criterion's third clause —
  "the registration-time approval for fixed-action tools is a **real enforced check against a
  PA-approved manifest**" — is **NOT delivered this sprint**. ADR-023 §2.4 implementation note and the
  Amendment-1 A1.6 both say the signed-manifest signature-verification is a FUT-04 follow-on (#590,
  open). What ships is: (i) per-dispatch deterministic deny (built, enforced) + (ii) the existing
  `TOOL_CALL_ALLOWLIST` membership check (`entrypoint.py:1429`). The *signed manifest* is not the
  gate yet; `TOOL_CALL_ALLOWLIST` is a hand-maintained list, not a derived view of a signed artifact.
  **This is correctly disclosed** (ADR-023 §2.4 note; #590 carry-over) and is harmless today (4
  network-free tools), so I score #570 PASS on the *bypass-closure* that was the criterion's core
  ("AO dispatch is adjudicated; P-004 enforced at the loop; a deny-class tool is refused") — the
  manifest-signing half is a named, ticketed deferral, not a silent miss. A reader should not, however,
  read criterion #7 as "tool-registry integrity is now tamper-evident" — it is not (see MAJOR-2 cross-ref).

---

## 3. Adversarial findings

### MAJOR-1 — The SDV's binding verification method (real-model Layer-B / real-UI Layer-C automated tests, in-increment) was not delivered for ANY user-facing criterion, and no SDV amendment records the downgrade

**Evidence.** SDV §4 is unambiguous and repeats itself: "Each ships with a **real-model (Layer B …)
and/or real-UI (Layer C …) automated test, authored in the same increment** … Real-model/real-UI
coverage is therefore a deliverable, not optional." §6 lists "Real-model (Layer B) / real-UI (Layer C)
automated tests, one per user-facing criterion, in-increment" as a deliverable row. §11 makes these
"the binding verification, not the human."

On disk: every Sprint-12 test added is a **mocked-model** headless test (`SimpleNamespace` generation
stubs, `mock_validate_output`, `_seed_untrusted` injecting tags directly). I found **no** test that
drives real Qwen3 on the Arc 140V, and **no** pywinauto/WinUI Layer-C test added this sprint. The SCR
§3 concedes this implicitly ("the deterministic controls are proven by the headless suite … the
user-facing surface is LA-live-verified") — i.e. the binding gate became the *manual* LA live-verify,
exactly the constraint the SDV said it was *removing*.

**Why it matters.** This is the sprint's own thesis turned against it: §4 argues the mocked suite is
*why the Stage-5 false-positive slipped past CI*, and makes real-model tests the fix. Shipping the
sprint on the mocked suite + a manual human check reinstates the precise gap the sprint was scoped to
close. The [[feedback_mature_reframing_needs_sdv_amendment]] discipline (now at 2 prior instances) is
directly on point: deviating from an SDV §4 criterion's literal text requires amending the SDV first,
then claiming PASS against the amended text. That did not happen — the SCR claims completion against
the *original* §4 while delivering a *weaker* verification method.

**Rating: MAJOR** (not CRITICAL): the controls are real and the manual live-verify did occur, so the
behaviour is evidenced — but the *method* the sprint contracted for, and justified at length, is
absent, and the deviation is undocumented.

**Recommended disposition.** Either (a) author an SDV v4 amendment that honestly records "Layer-B/C
automated tests deferred; binding verification was manual LA live-verify + mocked headless suite,"
landing it before the sprint is called complete; **and/or** (b) carry a Sprint-13 ticket to build the
Layer-B real-model harness for the three security-critical behaviours (untrusted lock fires; leakage
fires on a real untrusted leak; PA-deny refuses a real egress-shaped dispatch) — the §9.1 mitigation
the sprint named but did not execute. (a) is mandatory for honesty; (b) is the mature close.

### MAJOR-2 — Amendment-1 makes the shipped action-lock dormant and routes DANGEROUS to a per-action deny that is NOT total — a DANGEROUS tool whose action matches no DENY rule would execute under untrusted content

**Evidence.** Shipped gate (`entrypoint.py:1414-1419`) fires only when
`tools.risk_tier(tool_name) == tools.RiskTier.GUARDED`. ADR-023 A1.2/A1.4 route `DANGEROUS` tools to
"the per-action PA deny, **not** the lock." The per-action deny is
`DeterministicPolicyChecker.check`, whose DENY rules are RULE 1–4 only: restricted path,
`/tmp/export/` exfiltration, external-network URI schemes, authority-claim regex
(`gpu_inference.py:383-409`). RULE 5–10 are ESCALATE, and in `_adjudicate_tool_dispatch` an ESCALATE
verdict is non-`None`, so it also blocks (`entrypoint.py:1442`) — good. **But a DANGEROUS action that
matches *no* rule returns `None` (allow).** Concretely: a future `delete_local_note(path)` tool
(`DELETE` verb, `resource=/home/user/notes.txt` — an *allowed* path, no external scheme, no
`/tmp/export/`) would (i) not be locked (it is DANGEROUS, not GUARDED) and (ii) pass adjudication
(no DENY rule matches an in-home delete). It executes — even with untrusted content present.

This is **the exact gap the prompt asked me to probe**, and the SCR §5.4 flags it ("revisit whether to
*also* session-lock DANGEROUS under untrusted content … against a deny-rule coverage gap"). The flag
is *honest* but **understated**: it is filed as a "future consideration," moot "today (no DANGEROUS
tools exist)." That is true for *liveness* but the gap is **structural in the ratified design**, not
merely a future tool's problem: Amendment 1's own §A1.5 leans the whole safety argument on the
per-action deny ("Security for the current toolset then rests **entirely on the per-action PA deny**"),
and that deny is an allowlist-of-denies (deny-known-bad), not a deny-by-default. For a DANGEROUS tier
whose entire justification is "egress/irreversible mutation," resting it on deny-known-bad inverts the
fail-closed posture the SDV §5.3 calls "non-negotiable" for the gate. The gate fail-closes (unknown
provenance ⇒ locked); the DANGEROUS *action* path fail-OPENS (unmatched action ⇒ allowed).

**Why it matters.** Today: zero live impact (all tools SAFE — confirmed `tools.py:151-156` +
`test_shipped_tools_are_safe`). But this sprint's entire reason for existing is to lay the trust
substrate *before* the internet-facing future, and the first DANGEROUS tool added (a `web_fetch` is
caught by RULE 3, but a `file_write`/`file_delete`/`smart_home_control` is **not**) walks through this
seam unless the design is tightened. A latent fail-open in the highest-risk tier, shipped as a
"future consideration," is the kind of thing the predecessor SWAGRs existed to surface.

**Rating: MAJOR** (not CRITICAL): no DANGEROUS tool exists, so nothing is exploitable on `main` today;
and the gap is disclosed (§5.4). It is not MINOR because the disclosure under-rates a structural
fail-open in the design's own load-bearing argument, and the remedy is a one-clause gate change that
should arrive *with* the first DANGEROUS tool, not be rediscovered then.

**Recommended disposition.** Promote SCR §5.4 from "future consideration" to a **tracked Tier-2
carry-over ticket** with explicit acceptance: *before any DANGEROUS-tier tool ships, the Layer-3 gate
must also lock DANGEROUS under untrusted content (defense-in-depth over the deny-known-bad rules), OR
the per-action deny must become deny-by-default for the DANGEROUS tier.* Add a fail-closed test:
a tool declared DANGEROUS whose action matches no DENY rule is refused (locked) under untrusted
content. (ADR-023 A1.6's planned test (d) only covers "no declared tier ⇒ DANGEROUS"; it does **not**
cover "declared DANGEROUS + unmatched action under untrusted ⇒ refused" — that is the missing teeth.)

### MAJOR-3 — Criterion #6's clarification-on-ambiguity half is undelivered AND uncarried — the only success criterion with a silent (un-ticketed) gap

**Evidence.** SDV §4 #6 and §5.1(7) specify a prompt-assembly disambiguation step that, on >1
high-relevance candidate, emits a one-line clarification. Neither the SCR §2.2/§3 nor any carry-over
in §5 mentions it. The mapped commit (#585, `15d9203`) implements only the fresh-attachment recency
fix. I found no clarification step in the AO source. So unlike #583 (PARTIAL but ticketed at #583) and
the manifest-signing half of #7 (ticketed at #590), the missing half of #6 has **no carry-over
ticket** — it is the one scope item that fell through silently.

**Why it matters.** [[feedback_doc_cleanup_non_optional]] / the Stage-6.7.5 pattern: any deferred
scope item is a REQUIRED ticket, not an optional one. A success criterion that is half-built and
half-forgotten is precisely the carry-over-completeness failure mode the SWAGR exists to catch (cf.
the Sprint-11 SCR §14.1 carry-over-classification miss). The SCR's "the seven criteria are serviced by
the increments in §2.2" (SCR §3) is, for #6, an over-claim: the clarification behaviour the criterion
names is not serviced.

**Rating: MAJOR** for carry-over completeness (the gap itself is low-severity product polish — a missing
clarification prompt is a UX nicety, not a security hole — but an *unrecorded* dropped criterion is a
governance miss, and governance integrity is what this artifact audits).

**Recommended disposition.** File a Sprint-13 carry-over ticket for the intent-disambiguation
clarification step (the §5.1(7) "cheap disambiguation at prompt-assembly when >1 high-relevance
candidate"), and correct the SCR's criterion-#6 disposition to PARTIAL. The freshest-pin-wins half
stays delivered.

### MINOR-1 — Leakage control's untrusted-FIRING direction is proven only by mocked assertion, never live-exercised

**Evidence.** SCR §4 live-verify covers leakage only in the negative ("two-document summary + a PII
recall streamed and stayed; no LEAKAGE_DETECTED hold"). No untrusted-leakage scenario was run on the
real model, so "the detector still catches a real untrusted leak" (SDV §4 #4: "an untrusted leak is
still caught") rests on `test_untrusted_content_is_fed_to_leakage_detector` — which asserts the chunks
are *fed*, with a mocked `validate_output`; the actual cosine firing on real embeddings of a real
untrusted leak is never exercised end-to-end. The SCR does not explicitly name this gap (it lists
leakage live-verify as ✅ for the summary case only).

**Rating: MINOR** — the *feed* is correct (the only thing the redesign changed), and the cosine
detector itself is unchanged from the Tier-1 wave; so the firing path is inductively covered. But the
SDV asked for a real-model proof of *both* directions and got one direction live + one direction
mocked. Folds into MAJOR-1's remedy (b).

**Recommended disposition.** Subsumed by MAJOR-1(b): the Layer-B harness should include an untrusted-
leak-fires case. No separate ticket needed if MAJOR-1(b) is filed with that scope.

### MINOR-2 — `/external` ingest is architecturally inconsistent (gateway-side) and that inconsistency is disclosed but the interim's own scope-creep risk is not bounded in a ticket

**Evidence.** `/external` is parsed gateway-side (`transport.py:_parse_external_command`,
`send_prompt:643`) while every other slash command is WinUI-side (the SCR §1 and the `MainWindow.xaml.cs:198`
comment both say so). The inconsistency is **documented** (SCR §1, ADR-023 §3.1(b), the docstring) and
**ticketed** as EA-6-proper (#583). Control-bypass check: `/external` does **not** bypass any control —
it routes content to `provenance=UNTRUSTED_EXTERNAL` (`entrypoint.py:1273-1275`), which is *stricter*
than the default, and it is explicit-opt-in (never silent paste-marking, per ADR-023 §3.1). I confirmed
the ordering is safe: the fresh-attachment clear (`:1197`) keys on `documents` only, not
`external_documents`, so `/external` content is not wiped by an unrelated attachment in the same turn,
and it is added after the clear. No bypass.

**One real wrinkle the SCR omits:** because `/external` is gateway-side and the WinUI fall-through
(`MainWindow.xaml.cs:198`) special-cases the literal prefix `/external`, the two must stay in sync by
hand — a WinUI-side command that later shadows `/external`, or a rename, breaks the channel silently.
There is no test pinning the WinUI fall-through (it is C#, lessons 16/32 — not headlessly testable),
and the gateway-side `TestExternalCommandParse` cannot see the WinUI swallow. This is the EA-6a-fix bug
(SCR §4: "the WinUI rejects unknown slash-commands rather than forwarding them") and it could recur.

**Rating: MINOR** — disclosed, ticketed, no bypass; the sync-fragility is the only un-noted residue.

**Recommended disposition.** When EA-6-proper (#583) lands the proper UI gesture, **delete** the
interim `/external` gateway path rather than leaving two affordances; until then, note the
gateway↔WinUI sync coupling in #583 so the replacement removes both halves. No new ticket required.

### MINOR-3 — Test honesty of the GUARDED-patch fixtures: sound, but it relocates real lock coverage onto a non-shipped tier

**Evidence.** Three lock-mechanism test classes (`TestToolCallLoop`, `TestLayer3LoadedVsRetrieved`,
`TestUntrustedIngest`) use an autouse fixture `patch.dict(tools._TOOL_RISK_TIER, {"get_current_time":
GUARDED})` so the lock can be exercised (since all real tools are SAFE post-Amendment-1). I checked
each: the patching does **not** hide a regression — it makes the *lock mechanism* testable, and
`TestRiskTiers::test_safe_tool_not_locked_under_untrusted_content` separately proves the SAFE-default
(the *shipped* behaviour) with no patch, asserting `get_current_time` fires (2 generates) under
untrusted content. So both the lock (via patched GUARDED) and the SAFE-not-locked default (unpatched)
are genuinely tested, not merely asserted in prose. The SCR/journal are honest about this
(`BUILD_JOURNAL` 2026-06-04 "Capability-scoped locking" entry says exactly this).

**The residue:** there is **no test that the lock fires for a tool that is GUARDED *by declaration*** —
the `_TOOL_RISK_TIER` map ships with zero GUARDED entries, so the only GUARDED coverage is via
monkeypatch. If a future change broke `risk_tier()`'s handling of a *real* GUARDED declaration (vs a
patched dict entry), no test would catch it. Low severity — the code path is identical — but worth a
single declared-GUARDED fixture when the first GUARDED tool is contemplated.

**Rating: MINOR** — the patching is honest and disclosed; the gap is only that "GUARDED" is never
exercised as a *shipped declaration*.

**Recommended disposition.** No action this sprint. When the first GUARDED tool is added (alongside
the MAJOR-2 remedy), add a fixture that declares a real GUARDED tool in `_TOOL_RISK_TIER` and asserts
the lock fires — replacing the monkeypatch coverage with declaration coverage.

### Note (no finding) — Fail-closed for unknown tool tier IS enforced

The prompt asked me to confirm "unknown tool tier ⇒ DANGEROUS" is enforced, not asserted.
`tools.risk_tier()` (`tools.py:161-168`) returns `_TOOL_RISK_TIER.get(tool_name, RiskTier.DANGEROUS)`
— a real `.get(...)` default, exercised by `test_unknown_tool_is_dangerous_fail_closed`
(`risk_tier("send_email")` and `risk_tier("")` both DANGEROUS), which I ran green. Enforced. (The
*consequence* of DANGEROUS under untrusted content is the MAJOR-2 gap, but the *classification*
fail-closed is solid.) Similarly, unknown provenance ⇒ UNTRUSTED is enforced (criterion #1).

---

## 4. Carry-over reconciliation

The SCR §5 lists four carry-overs. Assessed against the evidence:

| Carry-over | SCR status | Auditor assessment |
|---|---|---|
| EA-6 proper — WinUI workspace-folder + mark-external UI (#583) | open, paired live session | **Confirmed open** (#583 Status:Draft). Correctly carried — but it covers criterion #5's *trusted* half; SCR over-implies `/external` "covers the function." |
| #590 — sign the AO tool manifest | open | **Confirmed open** (#590, priority medium). Correctly carried; it is also the undelivered half of criterion #7's "enforced manifest check" clause. |
| Branch-hygiene pass (LA-gated) | open, no autonomous deletion | Confirmed; correctly fenced behind the destructive-git standing rule. Not audited further (out of scope). |
| §5.4 — DANGEROUS-tier lock posture | "future consideration," moot today | **Under-rated → see MAJOR-2.** Should be promoted from prose to a tracked ticket with a fail-closed acceptance test. |

**Completeness gap in the carry-over set:** the carry-over set is **NOT complete**. Two items are
missing:

1. **The intent-disambiguation clarification step** (criterion #6 half (a)) — undelivered and
   un-ticketed (MAJOR-3).
2. **The SDV-mandated Layer-B/Layer-C automated-test harness** (criterion #3–#7 verification method) —
   undelivered, no ticket, no SDV amendment recording the downgrade (MAJOR-1).

So the prompt's question — "Are #583 (EA-6), #590, the branch pass, and §5.4 the complete carry-over
set, or is something silently dropped?" — resolves to: **something is silently dropped.** Two things,
both above.

---

## 5. Disposition

**PASS-WITH-GAPS. 5 PASS / 2 PARTIAL. 0 CRITICAL, 3 MAJOR, 3 MINOR.**

The security spine — provenance foundation, provenance-driven gate (secure-by-default restored),
untrusted-only leakage feed, in-process #570 adjudication — is genuinely built, deterministically
tested with teeth, and shipping on `main` at `90b2bed`. The headline test number (1661/2) is honest
and reproduced. The mid-sprint Amendment-1 pivot is sound design and the journal/lesson-38 capture is
portfolio-grade. None of the gaps is exploitable on `main` today (all tools SAFE; no live DANGEROUS
path; no live untrusted channel beyond explicit `/external`).

It is **not** a clean completion because: (1) the verification *method* the SDV made binding and
justified at length — in-increment real-model/real-UI automated tests — was not delivered for any
criterion and the downgrade to manual live-verify is undocumented (MAJOR-1); (2) the DANGEROUS tier's
safety rests on a deny-known-bad rule set that fail-OPENS on unmatched actions, disclosed only as a
"future consideration" (MAJOR-2); (3) criterion #6 shipped half its scope with the other half silently
dropped (MAJOR-3); and (4) criteria #5 and #6 are PARTIAL, which the SCR's "the seven criteria are
serviced" framing over-states.

**The MAJORs do not block calling the *security work* complete; they block calling the *sprint as
specified* complete without two corrections:** (i) an SDV amendment honestly recording the
verification-method deviation, and (ii) two new Sprint-13 carry-over tickets (the disambiguation
clarification step; the DANGEROUS-lock / deny-by-default tightening + its fail-closed test), plus
optionally the Layer-B harness. With those recorded, the sprint closes honestly as a strong
security increment with explicitly-deferred verification depth and two product half-features.
