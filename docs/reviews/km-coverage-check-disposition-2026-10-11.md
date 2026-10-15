# Disposition: independent reviews of the knowledge-map coverage check (#1744)

**Reviews:** an independent adversarial reviewer (did not write it), 2026-10-11, two rounds, of branch `feat/1744-km-coverage-check`: round 1 at `cfa51f25` (verdict merge after fixes, 7 findings), round 2 verifying `5d0a306a` (verdict merge; real-tree recount 68 studies, 55 cited, 13 listed matched; 15 mutants and about 60 fixture attacks). Fixes are in `5d0a306a` and `f9f3f677`.

```disposition
round1-1-journal-fragment-stale-numbers-and-false-gate-claim | FIXED | 5d0a306a
round1-2-four-guards-survived-mutation | FIXED | 5d0a306a
round1-3-study-type-defined-by-an-allowlist | FIXED | 5d0a306a
round1-4-false-green-citation-shapes | FIXED | 5d0a306a
round1-5-ordinary-citation-shapes-failed-closed | FIXED | 5d0a306a
round1-6-reason-checked-for-presence-only | FIXED | 5d0a306a
round1-7-planted-tests-depended-on-the-real-tree | FIXED | 5d0a306a
round2-residual-3a-map-prefix-excluded-folders-and-non-md-files | FIXED | f9f3f677
round2-N1-non-cp1252-file-name-crashed-the-report | FIXED | f9f3f677
round2-residual-3b-hidden-files-folder-with-a-sibling-page | REJECTED | a saved-page asset folder is excluded only when its sibling page exists and is tracked, the rule is documented in the script header, the incidence in the tree is zero, and the page itself must be cited so the folder rides on a cited page
round2-4-sentence-naming-a-study-as-not-mapped-counts-as-citation | REJECTED | a mention of a path in a map is the citation the check can verify, deciding whether the sentence asserts coverage needs a reader, and the unmapped yaml is the explicit way to say not covered
round2-4-four-space-indented-block-counts | REJECTED | removing every non-list indented line still leaves all 55 citations so none depends on it, but the maps nest lists with four-space indents and treating them as code would cause false reds, documented and pinned by a test
round2-5-markdown-emphasis-and-curly-quote-citation-shapes-fail-closed | REJECTED | these shapes exit 1 and name the study so the author fixes the citation, they never give a false green, and the real tree uses backticked paths only
round2-6-reason-form-check-cannot-reject-xxxxxxxxxxxx | REJECTED | a form check cannot judge meaning, the reasons are reviewed in the diff of the yaml file, and the 12-character floor plus the placeholder list rejects the lazy cases
round2-N2-non-ascii-repository-root-switches-git-discovery-off | DEFERRED | #1744 blocked-by: the symbol `test_non_ascii_repository_root_still_uses_git_discovery` exists in tests/security/test_knowledge_map_coverage.py; the repository path is ASCII today and the fallback prints a visible note and fails closed
round2-N3-two-guards-survive-mutation-file-slash-child-and-lexists-filter | DEFERRED | #1744 blocked-by: the symbols `test_file_slash_child_is_not_a_citation` and `test_tracked_but_deleted_file_is_not_a_study` exist in tests/security/test_knowledge_map_coverage.py
round2-N4-listed-untracked-entry-never-goes-stale | REJECTED | tolerating a listed untracked draft is the stated design so another session's untracked draft cannot turn the standing gate red, a worktree without the draft reports the entry stale and fails closed, and no tracked study is masked
```
