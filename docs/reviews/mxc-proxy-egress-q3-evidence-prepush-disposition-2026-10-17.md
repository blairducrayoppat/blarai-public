---
title: "MXC proxy egress, Q3 and variant 4 evidence bundle: pre-push review disposition"
status: closed
area: reviews
date: 2026-10-17
---

# Q3 and variant 4 evidence bundle pre-push review: disposition

**Subject:** the five pre-push review rounds of the sanitised bundle `evidence/2026-10-16-mxc-proxy-egress-standard-token-and-wfp/` in the public evidence repository (`docs/reviews/mxc-proxy-egress-q3-evidence-prepush-review-2026-10-16.md`, rounds 1 to 5, the last PUSH-OK). The fixes live in the evidence repository, whose commits this verifier cannot resolve, so each row names the evidence-repository change in words: the published merge of `publish/mxc-q3-standard-token-wfp` into that repository's main, squashed from the reviewed branch tip so that no intermediate state was published, and byte-identical to the tree round 5 passed.

```disposition
F1-installed-package-inventory-in-appcontainer-snapshots | FIXED | 73439ca7 records round 5 verifying it: the evidence-repository sanitiser drops every appcontainer_mappings entry except the probe's own profiles, keeps the totals, and the leak gate refuses the inventory shape; the published bundle carries none
F2-ipv6-link-local-interface-addresses-in-wfp-dumps | FIXED | 145ace0e records round 4 verifying the four addresses rewritten as ipv6-interface-1 to -4 and the leak gate's ipv6-interface rule
F3-sid-binary-asstring-residue | FIXED | 145ace0e records round 4 verifying the rendering recomputed from the zeroed blob and the sid-binary-asstring gate rule
F4-gate-widening-in-the-same-commit-as-the-data | FIXED | 145ace0e records the tools changes reviewed on their own as separate commits on the reviewed branch, each widening scoped and each new rule with a self-test that bites
F5-tessera-filters-carry-an-account-user-condition | FIXED | 145ace0e records round 4 verifying the bundle README states the ALE_USER_ID condition with the account SID redacted and its bearing on case 3
F6-b4-candidates-omit-bitdefender-filters | FIXED | 145ace0e records round 4 verifying the README reads at least two candidates with the 728 Bitdefender filters named and unanalysed
F7-mxc-documentation-citation-line | FIXED | 145ace0e records round 4 verifying the corrected logging-access-denied.md line citations
F8-root-readme-index-omits-recent-bundles | REJECTED | the precedent bundles of 2026-10-15 added no root index row either; adding one row for this bundle alone would make the index inconsistent, so the index stays as precedent left it and the bundle README is the entry point
F9-reserved-range-exemption-justified-by-a-false-source | FIXED | 145ace0e records round 4 verifying the comment and PROVENANCE name the three Bitdefender LAN filters as the source, with each address's registry, the scope unchanged at seven bases, and a self-test refusing the neighbouring address
F10-bitdefender-provider-name-embeds-an-install-timestamp | FIXED | 145ace0e records round 4 verifying all 20 dumps read Bitdefender.TICKS-Provider and the gate's device-timestamp rule
R-inventory-layouts-and-non-bitdefender-timestamps-unseen | DEFERRED | #1801 blocked-by: #1801 (the evidence repository's leak gate widened to the remaining inventory layouts and timestamp forms before the next bundle carrying AppContainer snapshots or WFP dumps); incidence 0 in the repository today, round 5 73439ca7
```
