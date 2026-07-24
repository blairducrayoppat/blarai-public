---
title: "Disposition — independent review of 804626ac (#1006 tool-call status)"
date: 2026-07-21
review_of: "804626ac on feat/1006-tool-call-status"
reviewer: independent subagent (author≠verifier; red-verified the detection lock against the parent commit in a throwaway worktree; probed the full transition matrix)
---

# Disposition — #1006 tool-call status review (2026-07-21)

Review verdict: NO BLOCKING findings; 2 SHOULD-FIX + 4 NOTEs. Fix-round commit: `07bd960d`.

```disposition
finding-1-unclosed-mention-false-positive | FIXED | 07bd960d
finding-2-drift-lock-pins-fallback-not-resolved-binding | FIXED | 07bd960d
finding-3-case-variant-tag-asymmetry | REJECTED | Pre-existing asymmetry in the production strip itself, not introduced by this change; detection short-circuits on the strip's own output (an unstripped uppercase block leaves the stripped answer non-empty, so detection cannot fire), and inheriting the imported production pattern's IGNORECASE therefore cannot mis-record a case; the asymmetry belongs to the strip's model binding, not to this eval change.
finding-4-preference-memory-suite-inconsistency | DEFERRED | #1023 blocked-by: evals/suites/preference_memory.py:879,895 still applying the production strip to model output without tool-call detection (grep-observable); named as an input to the #1023 harness design rather than patched piecemeal under the LA's answer_quality-only scoping.
finding-5-generic-malformed-baseline-message | REJECTED | The generic branch is loud, crash-free (reviewer probed list and None values), and its remedy text is correct; a dedicated malformed-value message would duplicate load_baseline's exit-2 guard for committed files without adding any safety, and the cosmetic divergence does not change any exit code or absorb anything.
finding-6-offline-path-equivalence-unlocked | FIXED | 07bd960d
```
