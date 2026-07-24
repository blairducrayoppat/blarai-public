# #1043 (S3 slice B) — review disposition, 2026-07-23

Findings from the independent pre-merge review of `feat/1043-spec-corpus-alignment`
(author ≠ verifier throughout: the reviewer found every finding below and wrote none of
the fixes). Verdict carried into this record: MERGE-AFTER-FIXES.

This record covers BOTH review rounds and is the single disposition for the slice. It
replaces the round-1 record (`1043-spec-corpus-alignment-disposition-2026-07-23.md`,
committed in `12060058` and deleted here), whose F1 stated the fix as "ground on the
clarification `answer` only" — necessary but NOT sufficient, since it left the rendered
block flowing through `authored_from`. Keeping a superseded record beside this one would
leave a wrong fix description readable as current.

The reviewer reproduced #1043's own isolating control through the real functions before
judging, with a positive-control check first — their initial probe harness returned 0 for
every arm including the control, which correctly indicted the harness rather than the code.

```disposition
F1 BLOCKER: `authored_from` carried the RENDERED requirements block, so `compose_requirements_block`'s fixed house header entered the grounding corpus on every clarified dispatch — granting authority to "person", "build", "clarified", "requirements", "them", "these", words no operator uttered, and excusing an oracle asserting `classify(...) == 'person'` | FIXED | 098173a8 — the gate now grounds on `operator_answers`, the operator's answers as DATA, extracted from the block by the new `clarify.operator_answers_from_block`; renderer and extractor share named boilerplate constants so they cannot drift; mutant M2 (plan site passes the rendered seed, the defect verbatim) is CAUGHT
F2: the corpus also admitted the MODEL-authored clarify `question`, letting the model launder its own invention into its own excuse — and a mutant deleting just that append SURVIVED, so the channel was both unreachable-on-the-live-path and untested | FIXED | 098173a8 — the question is not admitted; `test_model_authored_question_cannot_launder_an_invention` carries the refused-value case plus a positive control, and mutant M4 (re-admit the question) is now CAUGHT rather than surviving
F3: the negative test `test_alignment_does_not_blind_the_scanner_to_a_real_invention` hand-wrote `authored_from` and never called `compose_requirements_block`, hand-approximating "the person clarified" — a near-miss fixture that let F1 survive a suite written to catch that class | FIXED | 098173a8 — every #1043 grounding fixture is now built through the REAL composer via the `_real_operator_answers` helper, `'person'` is an explicit case in `test_house_boilerplate_never_enters_the_grounding_corpus`, and `test_operator_answers_round_trip_through_the_real_composer` locks composer↔extractor against drift
F4: the `authored_from=""` default silently reproduced the old broken grounding for any future caller that omitted it | FIXED | 098173a8 — the SEMANTICS are fixed, and that is the part genuinely closed: the parameter is answers-as-data, so absent now means "the operator supplied nothing extra" rather than "old broken behaviour". The residual risk is MITIGATED AND LOCKED, NOT structurally eliminated — `security_by_design` principle 4 reserves "structural" for what CANNOT be expressed, and a test is a lock. `test_the_qa_gate_grounds_on_operator_answers_not_the_rendered_seed` pins BOTH links of the EXISTING chain (its toggle-off proves it catches a dropped argument and a seed-bound one), but a NEW caller holding operator answers can still omit the parameter, get the narrow corpus, and trip no lock. Eliminating that would require a mandatory parameter, which would break the many callers correctly grounding on the spec alone
F5: `_spec_corpus`'s "the only channel carrying the enrichment" was a call-graph claim that would rot as callers changed | FIXED | 098173a8 replaced the call-graph claim, and THIS commit corrects the replacement — which asserted a provenance rule ("a source may enter only if the operator authored it") that is FALSE on this very function: `spec.criteria[].text`/`.check` are 14B-written (`generate_plan` step 2) and do enter the corpus. The docstring now states the rule that is actually true and actually load-bearing: a source is admitted when it is requirement content the CODER was also given (verified on disk — `compile_prompts` puts every criterion verbatim into the coder's task prompt, so it cannot blindside them) AND a statement of what to build rather than house framing. It explains why a model-written criterion passes both tests while a clarify question fails both. Locked by `test_model_written_criteria_ground_because_the_coder_is_given_them`, which asserts the premise against the real compiler rather than trusting the prose
F6: invented-return grounding uses an unanchored substring match, so a short literal is excused when its characters appear inside an incidental word ('ok' inside 'broken' / 'token') | DEFERRED | #1082 — blocked-by: `scan_invented_return_contracts` in `shared/fleet/oracle_qa.py` still uses the bare `norm.lower() in spec_corpus` test that arrived with #826; this slice amplified exposure but did not introduce it, and replacing the matching rule alters the verdict for every oracle on every dispatch in the more-convictions direction, so #1082 must first measure the findings-per-dispatch delta against the eval corpus
```

## Mutation battery — every mutant caught

Each mutant fails at least one lock; the battery is the evidence that these locks are not
gates that pass against the bug. M2 and M4 are the two review findings in mutant form.

| mutant | caught |
|---|---|
| M1 plan site drops `operator_answers` | yes |
| M2 plan site passes the RENDERED seed (F1 verbatim) | yes |
| M3 gate ignores `operator_answers` | yes |
| M4 corpus re-admits the model-authored question (F2; **survived before this change**) | yes |
| M5 corpus drops the clarification answers | yes |
| M6 extractor stops stripping the header | yes |
| M7 extractor stops stripping the `(assumed)` tag | yes |
| M8 author forwards nothing to the gate | yes |
| M9 criteria stop reaching the coder's prompt (the F5 admission rule's premise) | yes |

## Verification notes

- Provenance of every admitted source was checked rather than assumed:
  `answered_from_free_text` carries the operator's literal reply; `decide_defaults` carries
  a fixed per-axis constant from `shared/fleet/clarify.py`. Neither is model output.
- The reviewer's verified-clean items were left alone: the toggle-off honesty (M1/M3), the
  fail-soft behaviour, and `acceptance.py`'s pass-through shape.
- Gate after the fixes: 8861 passed / 21 skipped / 125 deselected (isolated worktree; the
  21 are the documented gitignored-model env-skips).
