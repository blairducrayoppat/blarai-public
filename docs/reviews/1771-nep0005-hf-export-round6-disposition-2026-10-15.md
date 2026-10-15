# Disposition, round 6: adversarial review of the NEP-0005 half-set study export for Hugging Face (#1771)

Review: `docs/reviews/review-1771-nep0005-hf-export-2026-10-14.md`, Round 6 (adversarial reviewer, 2026-10-15, verdict PASS, findings R6-1 to R6-3). Earlier rounds: see the round 1 to 5 records in `docs/reviews/`.

```disposition
R6-1-unreadable-source-head-branch-has-no-test | FIXED | af30920a - test_upload_refuses_when_the_source_repo_is_not_a_repository (a non-repository directory as --source-repo: exit 1, "does not resolve", nothing sent) and toggle test_source_head_read_toggle_an_unreadable_head_passes_when_the_failure_is_ignored.
R6-2-mirror-repo-is-operator-supplied | REJECTED | --mirror-repo is the operator's own local clone of the public remote, inside the trust boundary the upload credential already sits in; the hold exists to catch an unsynced snapshot, not a forged local ref. An operator who can point it at a repository of their choosing can also run hf upload directly.
R6-3-r5-4-reasoning-wrong-for-the-0x-exemption | FIXED | 74b5c958 - the R5-4 row in the round-5 record now says the 0x exemption errs toward acceptance and states why it is accepted; the rejection of R5-4 stands (the wording edit is committed with this record).
```
