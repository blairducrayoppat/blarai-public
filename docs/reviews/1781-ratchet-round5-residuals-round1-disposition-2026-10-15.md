# Disposition: review round 1 of #1781

Review: `docs/reviews/review-1781-ratchet-round5-residuals-2026-10-15.md` (FAIL at 7c179900, findings R1-1 to R1-4). Fixed in 4837ffac.

```disposition
R1-1-legacy-skip-reaches-first-landing | FIXED | 4837ffac - a list-shape version is skipped only when every element is a string, and a window with no version carrying counts returns a named finding ("legacy list-shape baselines") instead of FIRST_LANDING; lock tests/security/test_no_host_identity_in_tree.py::test_toggle_list_shape_never_reaches_first_landing_and_odd_shapes_are_unreadable (the reviewer's repro, and a list of objects is unreadable; fails with either change reverted); fragment and docstring sentences corrected
R1-2-six-of-six-overclaim | FIXED | 4837ffac - the R5-4 row of the round-5 residuals disposition and the journal fragment now say the mutant fails the 3 trailing-backslash profiles of 6
R1-3-claim-check-compares-strings | FIXED | 4837ffac - _claimed_surface_drift asks dr.path_matches for a depth-one and a depth-three path under each claimed directory; tests/security/test_doctrine_rules.py::test_delivery_claim_check_accepts_an_equivalent_glob (docs/**/* passes) and the narrowing toggles still fail
R1-4-top-level-list-or-null-crashes-the-reader | FIXED | 4837ffac - TypeError added to _parse_baseline's except; the same R1-1 test asserts a top-level list and null read as not a readable baseline (fails with TypeError removed)
```
