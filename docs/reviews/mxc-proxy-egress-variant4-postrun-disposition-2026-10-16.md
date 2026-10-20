---
title: "MXC proxy egress, variant 4 (WFP capture): post-run review, finding disposition"
status: closed
area: reviews
date: 2026-10-16
---

# Variant 4 post-run review: disposition

**Subject:** live batch `run-20261016-2` (raw in `%USERPROFILE%\blarai-research-data\mxc-proxy-egress\`), harness at `2f792246`, reviewed read-only by an independent agent on 2026-10-16 (`docs/reviews/mxc-proxy-egress-variant4-postrun-review-2026-10-16.md`, `0edfd824`, addendum `95bdeba0`). Answer of the review: ANSWERED for existence and ownership of the filters, NOT ANSWERED for which layer produced WinError 10013. Four findings, numbered as in the review, plus the review's merge-read wording condition.

**Record commit:** `bebb33da` (PERFORMANCE_LOG.md entry, `docs/performance/mxc_proxy_egress_variant4_wfp_2026-10-16.json`). Both state the 6 package-keyed and 2 SID-mentioning filters separately, list the attribution gap and the control failure under not measured, and carry no wording that the positive-control failure weakens or strengthens the reading.

The code findings (1 to 3) need a change to `summarise.py` or `run_probe.py`, both under the round approval hash, so each needs a new pre-run review before the next live run of the probe; that run is the next case-1 variant under #1798. Finding 4 needed no measurement: the records review (`a57f2aef`) derived the owner offline and the records were corrected in `b1923fd5`.

```disposition
merge-read-wording-6-plus-2-filters-and-no-control-inference | FIXED | bebb33da PERFORMANCE_LOG.md entry and the variant 4 JSON state "six keyed to the run package, two that only mention the SID" and "the control's failure neither weakens nor strengthens the reading"; the raw summary file is unchanged and the JSON lists it as a known record defect
F1-substring-match-overcounts-filters-referencing-the-container-sid | DEFERRED | #1798 blocked-by: the next pre-run review of mxc_proxy_egress under #1798 (a changed sha256 of tools/probes/mxc_proxy_egress/summarise.py in the approval file, `filters_referencing` split into package-keyed and mentions-only); incidence 8 listed against 6 genuine in 6 of 6 runs, reading unaffected, the record states 6 plus 2
F2-positive-control-uninformative-synthetic-package-compiles-to-no-filter | DEFERRED | #1798 blocked-by: the next pre-run review of mxc_proxy_egress under #1798 (the control in tools/probes/mxc_proxy_egress/run_probe.py replaced by a registered-package rule or a raw WFP filter and shown to pass on this host); until then the record calls the control uninformative and rests the capture's sight on the eight per-launch filters
F3-10013-mechanism-not-isolated-needs-classify-drop-events-or-capturedenials | DEFERRED | #1798 blocked-by: a #1798 live run that records WFP net-event (classify-drop with filterId) or MXC captureDenials reason codes (App Isolation 1 against Tessera 103) per attempt, which needs a new pre-run review of run_probe.py first; the record states B3 is attributable to the Tessera BLOCK by inference and B4(i) and B4(ii) are not distinguishable
F4-constant-s-1-15-2-2397545170-package-owner-unidentified | FIXED | b1923fd5 PERFORMANCE_LOG.md variant 4 entry and the variant 4 JSON (constant_package_sid_owner) name the owner: the constant SID is the AppContainer SID derived from the name MXC-Loopback (SHA-256 of the lower-cased UTF-16LE name, first 28 bytes as seven little-endian uint32, reproduced offline by the records review a57f2aef), MXC's own named loopback peer in the arm B source (microsoft/mxc, base_container_helpers.rs:24,176 and base_container_runner.rs:3231,3441); no new capture was needed
```
