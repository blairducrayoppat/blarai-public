# Disposition: independent review of the MXC PR #1406 loopback-proxy probe (#1746 item a)

**Review:** an independent adversarial reviewer (did not write the probe), 2026-10-11, of branch `docs/1746-mxc-1406-probe` at `a21a03c3`. It recounted all 18 raw records with its own script, replicated T-on and L-off-c once, ran an unconfined positive control, and checked provenance. **Verdict:** merge after fixes; the headline result (the container reached the throwaway listener 3 of 3, every other destination blocked) held on recount and replication. Fixes are wording and banking, in `c7e1f70f`.

```disposition
finding-1-verify-clean-cannot-see-mxc-artifacts | FIXED | c7e1f70f
finding-2-dns-contrast-changes-three-inputs-and-inbound-untested | FIXED | c7e1f70f
finding-3-dns-exfiltration-direction-unshown | DEFERRED | #1746 blocked-by: a probe-only DNS test of a unique random subdomain with a packet capture, recorded as a dated comment on #1746
finding-4-measured-path-is-marked-temporary-upstream | FIXED | c7e1f70f
finding-5-headline-claims-more-than-tested | FIXED | c7e1f70f
finding-6-l-off-c-example-com-never-attempted | FIXED | c7e1f70f
finding-7-provenance-hard-coded-and-outside-repo | FIXED | c7e1f70f
finding-8-condition-figures-thermal-cpu-stderr | FIXED | c7e1f70f
finding-9-verdict-counts-untagged-connections | REJECTED | zero untagged lines and zero pre-launch lines exist in the banked data, the reviewer's independent recount agrees with every count, and the harness is one-shot study tooling so a stricter filter would not change any result
```
