# Disposition — #1144 landing-card redesign, independent pre-merge review (2026-07-28)

Review: independent author≠verifier subagent, verdict APPROVE-WITH-FIXES against branch
tip `2477fd8e` (3 MAJOR / 6 MINOR / 5 NIT). Fixes landed in `95b71a5f`; re-verification
requested from the same reviewer before merge. The reviewer independently reproduced the
9298 collection arithmetic and the full tests/security tier (676/0) before these fixes;
post-fix collection is 9303 (+5 fires-proofs).

```disposition
M1 ops-paste count overclaimed (137x vs measured ~30 of 137) in ops-surface, register row, audit HTML | FIXED | 95b71a5f
M2 author-neq-verifier-at-handoff clause dropped with no destination | FIXED | 95b71a5f
M3 subagent-state handover dropped with no destination (agents not OS-visible) | FIXED | 95b71a5f
MIN4 self-reported frontmatter date bypasses landing gates (copied legacy date) | FIXED | 95b71a5f
MIN5 stamp staleness timezone-fragile (naive local ISO vs verifier-local reinterpretation) | FIXED | 95b71a5f
MIN6 live-machine probes in gate tests + probe decode crash violates fail-soft contract | FIXED | 95b71a5f
MIN7 fragment-count derivation has three divergent semantics (python/anchor/template) | FIXED | 95b71a5f
MIN8 slug validator rejects the module docstring's own example | FIXED | 95b71a5f
MIN9a 8dbb2164 historical correction re-orphaned by template rewrite | FIXED | 95b71a5f
MIN9b de-risk guidance (test baseline, residual risk) had no new home | FIXED | 95b71a5f
MIN9c sequencing-constraints guidance dropped unstated | FIXED | 95b71a5f
NIT10 verify_brief catches OSError only; decode error tracebacks instead of clean fatal | FIXED | 95b71a5f
NIT11 UTF-8-BOM brief fails frontmatter matching confusingly | FIXED | 95b71a5f
NIT12 required-section check satisfiable by section names quoted in a code fence | REJECTED | The gates guard cooperative authors against momentum and template drift, not adversaries constructing evasive cards; a card whose section headings exist only inside a fence has no plausible honest authoring path (the assembler emits real sections), and hardening the matcher to full markdown parsing would add real complexity for a threat the model does not include. The reviewer classified it "acceptable for the threat model, noting only" and no change is made.
NIT13 principle-12 gaps: byte-arm, Start-Process sentinel, both stamp WARNs lacked fires-proofs | FIXED | 95b71a5f
NIT14 overwrite test builds filename from now() twice (midnight straddle) | REJECTED | The race requires the two main() calls inside one test to straddle local midnight, a window of milliseconds once per day on a test that runs in under a second; monkeypatching datetime.now inside the loaded module to close it would add a fake-clock shim with more failure surface than the defect it retires. The reviewer's own framing was "vanishing probability; freeze one now() if touched" — the test body was touched only to stub probes, and the clock behavior is deliberately left alone.
NIT15 "hand-editing voids the stamp" overclaims what the verifier detects | FIXED | 95b71a5f
```

Observations carried, not dispositioned (no defect asserted): the merged-main confirmation
run remains load-bearing and is recorded on #1144 in the merge motion; CLAUDE.md sits at
47,947 of 48,000 bytes and #1146 (staged R4) is the real relief; the +25 baseline-drift
attribution was independently confirmed by the reviewer.
