# Disposition — #1069 S3-F coverage gate, independent pre-merge review (2026-07-28)

Review: independent author≠verifier subagent over branch `feat/1069-s3f-coverage-gate`
(`773d5491` + `424b5728`), verdict **NEEDS-FIXES** (1 HIGH / 3 MED / 4 LOW). The HIGH is
the finding that earns the review its keep: the gate's own RELEASE decisions (repair
adoption, post-revision unblock) keyed on the warning helper's empty string, which
conflates "measured clean" with "could not measure" — a fail-open inside the engaged
control, reachable through the repair door by an over-complying repair that strips every
first-party import. The reviewer also verified sound: the active predicate, the
one-repair bound, the QA-evidence chain both ways, the step-2i floor interplay (stable —
the floor only emits imports of modules the exam already imports), the `_approve`
placement, `_choose`/reaper safety, the IPC crossing incl. the #1152 over-cap refusal
shape, render honesty, and toggle-off byte-identity.

Fixes at `17d52250` on the branch; fix-verification round returned to the same reviewer.

```disposition
F1 repair adoption + revision unblock treat UNMEASURABLE coverage as clean (warning "" == clean bill; an importless repair measures None and would be ADOPTED) | FIXED | 17d52250 - _coverage_measured_clean reads contract_coverage directly (None and crash are NOT clean) and gates BOTH release decisions; importless-repair lock + helper contract lock added
F2 coordinator re-evaluation crash fail-opens with the false "closed the coverage gap" affirmative | FIXED | 17d52250 - same helper at the gateway seam; unmeasurable keeps the ORIGINAL marker verbatim (no new gap text is invented); unmeasurable + crash locks added
F3 blocked plan at the revision cap: the card offers revise, the cap refusal recommends approve, approve refuses — a mutual-refusal loop with a lying exit sign | FIXED | 17d52250 - the at-cap blocked card supersedes the baked revise offer explicitly; the cap refusal on a blocked plan routes to reject and never says approve; end-to-end 3-revision lock
F4 an orphan-only gap can never be cleared by revision but the marker invites revising | FIXED | 17d52250 - _coverage_orphan_only classifies the gap at both marker-build sites; the orphan-only message routes to reject + re-describe; orphan-direction locks at plan time and message level
F5 toml capabilities line labels the re-evaluation reader as the approve refusal | FIXED | 17d52250 - renamed post-revision-re-evaluation; the refusal's method home (DispatchCoordinator._approve) named in prose; measured-clean rule added as its own capabilities line
F6 QUALITY-3 regeneration re-authors without the coverage pin, weakening by-construction on that path | DEFERRED | #1155 blocked-by: shared/fleet/oracle_qa.py::_reauthor prompt redesign - the regeneration is a single-focus code REPAIR, not a template re-authoring, so the pin needs a prompt-design change there; SAFE meanwhile because the deterministic measured-clean release rule blocks (never approves) a regeneration that drops pinned imports, and the limit is documented in generate_plan's S3-F docstring
F7 no end-to-end boot-restore lock through the real store | FIXED | 17d52250 - blocked plan parked through the real born-encrypted store, restored by a NEW coordinator at boot, approve still refused - locked
F8 the repair round adds one authoring+QA pass to the worst-case PLAN sequence; the 720s PLAN budget's registry review line asks for re-measurement on plan-shape changes | FIXED | 56d369a0 - the batched D/E/F/G ceremony runbook's gapped-plan live-verify step now TIMES the cold PLAN against the #1152 720s budget (the runbook lives on feat/1069-s3g-criteria-revise, which merges immediately after this branch)
```

## Carried, not dispositioned

The reviewer's verified-sound list is recorded in the review report and stands as
independent corroboration; no defect asserted there. The reviewer read but did not
execute the suites (read-only mandate) — execution evidence is the branch gates (F branch
full gate re-run after `424b5728`; the fix round's suites 93/93; merged-main gate at
merge time per standing doctrine).
