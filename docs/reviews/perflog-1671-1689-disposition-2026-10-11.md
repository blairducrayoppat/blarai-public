# Disposition: independent recount review of the #1671 and #1689 performance-log entries (#1745)

**Review:** an independent adversarial reviewer (did not write the entries), 2026-10-11, of branch `docs/1745-perflog-1671-1689` at `36cf6aa4`. It recomputed every number, time, range, ratio, count and filter id in both entries and both JSON files from the raw run files with its own script and found no mismatch. **Verdict:** merge after wording fixes; the fixes are in `9374f35c`.

```disposition
finding-1-1671-headline-claims-bitdefender-owns-filtering-not-observed | FIXED | 9374f35c
finding-2-1671-failure-cause-unrecorded-and-probe-definition-outside-repo | FIXED | 9374f35c
finding-3-1689-as-run-scripts-presented-as-as-they-stood | FIXED | 9374f35c
finding-4-1689-removal-time-stated-as-measured-is-an-upper-bound | FIXED | 9374f35c
finding-5-1671-comment-ids-attributed-to-the-wrong-ticket | FIXED | 9374f35c
finding-6-1689-headline-speed-basis-not-named | FIXED | 9374f35c
finding-7-1689-not-recorded-list-omits-power-source-second-probe-two-timings | FIXED | 9374f35c
finding-8-heading-date-1671-cosmetic-2026-10-04-vs-runs-into-10-05 | REJECTED | the heading carries the date of the first run and the entry text gives the three start times, so a reader sees both dates and re-dating would break the newest-first ordering convention the reviewer verified
finding-9-json-schemas-differ-between-the-two-new-files | FIXED | f1daf1a5
finding-10-hugging-face-dataset-upload-rule-for-measurement-arcs | DEFERRED | #1745 blocked-by: the LA lifting the goal-2026-10-11 limit on publishing anywhere (observable: a dated LA comment on #1745 or #1746 approving the dataset upload)
```
