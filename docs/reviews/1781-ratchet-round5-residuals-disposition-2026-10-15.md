# Disposition: round-5 residuals of the public-identifier ratchet (#1781)

Review: `docs/reviews/review-1765-public-identifier-scrub-2026-10-14.md`, section "Round 5" (findings R5-1 to R5-5), first dispositioned as DEFERRED to #1781 in `docs/reviews/1765-public-identifier-scrub-round5-disposition-2026-10-15.md`. Fixed on `fix/1781-ratchet-round5-residuals` in c864df44.

```disposition
R5-1-fast-forward-puts-the-legacy-list-baseline-in-mains-window | FIXED | c864df44 - _is_legacy_list_shape in scripts/scrub_public_identifiers.py reads the list schema as no version; lock tests/security/test_no_host_identity_in_tree.py::test_toggle_legacy_list_baseline_in_history_is_no_version_not_unreadable (fails with the skip removed; a garbage version still fails closed); the --no-ff rule is in .claude/rules/identity.md
R5-2-index-claim-check-is-a-prefix-match | FIXED | c864df44 - _claimed_surface_drift requires the directory glob (docs/**, scripts/** and so on) itself; lock tests/security/test_doctrine_rules.py::test_delivery_claim_check_fires_when_a_surface_is_narrowed_to_a_subdirectory (docs/** narrowed to docs/reviews/** fails the claim check; fails with the prefix match restored)
R5-3-main-dropped-message-skips-the-fork-comparison | FIXED | c864df44 - the dropped-entry branch of ratchet_violations applies the raise test against the fork count; lock tests/security/test_no_host_identity_in_tree.py::test_toggle_main_dropped_message_does_not_absolve_a_raise (the 3 to 5 example; fails with the condition removed)
R5-4-run-arm-call-site-locked-only-by-substring | FIXED | c864df44 - tools/probes/containment_arms/run_arm.py payload_command builds the command line; tests/security/test_containment_arm_launchers.py parses its real output with CommandLineToArgvW for six profiles (the payload is never run); the USERPROFILE+argv_tail("") mutant fails the 3 trailing-backslash profiles of 6
R5-5-ratchet-window-of-twenty-unnamed-in-the-honest-limit | FIXED | c864df44 - WINDOW=20 and the --no-ff rule are named in the reference_baseline docstring HONEST LIMIT (scripts/scrub_public_identifiers.py) and as one rule in .claude/rules/identity.md; rules corpus regenerated
```
