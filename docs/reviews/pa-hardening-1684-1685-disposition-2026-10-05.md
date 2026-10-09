# Disposition - #1684 (Policy Agent prompt validator) and #1685 (rules 5 and 7): three review rounds, J1-J12, K1-K5, L1-L2 and three automated security reviews

**Review:** `docs/reviews/code-review-1684-1685-pa-hardening-2026-10-05.md` (independent reviewer on Opus, who
ran the code and wrote no fix; rounds 1 to 3 in one file). Three automated background security reviews of the
commits are dispositioned as rows A1-A3. **Author of the work and of this disposition:** the session on #1684/#1685
(fixes written by Sonnet builders under its direction). The reviewer did not write fixes.

```disposition
J1 chat-template special tokens forge prompt structure through every interpolated field | FIXED | 61fead17 - control-text spellings are rejected in schema values, property names and every plain field, with the 26 added tokens read from tokenizer.json; 50542fbb widens the list to the union of the four local brain tokenizers (33 tokens); locked by TestChatTemplateControlText and a tokenizer-parsing test
J2 truncation and rejection create a classifier-versus-actor differential | FIXED | 61fead17 - truncation is removed and any tampered or over-cap field is a deterministic CAR_FIELD_REJECTED deny from classify_car with no model call; 50542fbb makes the verdict independent of key order; 739031c0 adds the total size cap
J3 the rejected-key reason echoes attacker text outside the untrusted markers | FIXED | 3458ce7e - hash-only reason except for plain identifiers keeping the golden prompts byte-identical; 50542fbb narrows the echo to a named compatibility list of the nine golden keys so identifier-safe attack keys are hashed; the 35 golden prompts recomputed identical to main by the reviewer
J4 the validator walks only dict, list and str so a tuple skips it | FIXED | 61fead17 - exact JSON-native types only (subclasses, tuples, sets, bytes, NaN and infinity are rejected); locked by TestNonJsonTypes
J5 Unicode variants of the delimiter | REJECTED | the reviewer closed it with evidence: the schema renderer escapes non-ASCII so look-alike characters are not visual forgeries inside the schema block, plain fields are covered by the control-text refusal and the identifier-only echo rule, and no normalisation step exists between validation and rendering so there is no validated-versus-rendered differential to exploit
J6 no aggregate size cap on the schema | FIXED | 739031c0 - MAX_SCHEMA_TOTAL_LEN of 16384 serialised characters enforced in the validator walk with a deny, a boundary test and a toggle
J7 the new tests may not be strong enough | FIXED | 61fead17 - the reviewer's mutation runs (7 of 7 caught at 3458ce7e) and the builder's later mutations (every control turned red when disabled) are recorded; the one survivor (dict subclass accepted) got its own test
J8 the pre-existing test isolation hole on single-file policy_agent runs | DEFERRED | #1688 - blocked-by: ticket #1688 (the keystore isolation guard fix)
J9 the non-applicability statement for rules 5 and 7 must name rule 6 and the verb | FIXED | 0702f506 - the rule table names RULE 6, states that rules 6 and 7 need the WRITE verb and that the assistant door sends EXECUTE for every tool and the URL door EGRESS, with a lock test
J10 the argument-name lock matches exact top-level names only | FIXED | f5b8dd80 - recursive substring scan; 4945bc9a walks every dict key and list value in every nesting form with a toggle per form
J11 where rules 5 and 7 are live elsewhere | REJECTED | no change needed: the reviewer's repository-wide search found them live only on the Policy Agent IPC door which has no known sender, and the statement in 93570276 is already scoped to the assistant and URL doors
J12 the 1685 worktree shows two files modified | REJECTED | the difference is line endings only (core.autocrlf), the bytes equal the committed ones, nothing was staged and the files are not in the merged tree
K1 whether tampering is detected depends on key order | FIXED | 50542fbb - the walk records a keyword miss and continues, tampering anywhere returns at once; TestKeyOrderIndependence covers both orders and nested shapes
K2 3458ce7e weakens a control that 61fead17 had by echoing identifier-safe keys | FIXED | 50542fbb - the echo is restricted to a named compatibility allowlist computed from the golden file and test-matched exactly; every other key including DECISION_ALLOW is hashed
K3 the control-text list is pinned to the 14B vocabulary | FIXED | 50542fbb - the union of the four local tokenizers with a test that parses each tokenizer file and asserts every added token is refused
K4 the argument-name lock misses two schema forms | FIXED | 4945bc9a - generic walk of every dict key and list value with a parametrised toggle for ten nesting forms
K5 a lone pipe-greater-than is refused as a false positive | REJECTED | accepted and documented in the constant's comment: refusing it is fail-closed, the model path it protects is unwired today so no user-visible request is affected, and narrowing it risks a split-field forgery
L1 the key-order fix also applies the 1024-character cap and newline rule to the arguments value so long assistant tool arguments would be denied on the model path | DEFERRED | #1683 - blocked-by: ticket #1683 (the decision to wire the model-backed classifier into the door or retire it, recorded there)
L2 the tokenizer-union test reads absolute machine paths | REJECTED | the test skips with a stated reason when a tokenizer directory is absent and runs with zero skips on this machine, which is the documented bounded environment delta for model-dependent tests; hard-coding a repository-relative copy of third-party tokenizers would add large files for no gain
A1 automated review: prompt-injection and parser differential in gpu_inference.py | FIXED | 61fead17 - reproduced as J1 and J2 by the independent reviewer and fixed there; 50542fbb closes the order-dependent form
A2 automated review: classifier and actor differential where truncation hides the payload | FIXED | 61fead17 - truncation removed, over-cap fields denied; the same full strings reach the rule checker and the prompt
A3 automated review: prompt-injection control regression in the latest commit | FIXED | 50542fbb - confirmed by the reviewer as K2 (identifier echo) and fixed with the compatibility allowlist
```

## Notes for the reader

- The model-backed classifier these controls protect is on no live path in the shipped configuration (#1683); the
  fixes are defence in depth for the day it is wired and cost nothing today. The 35 shipped evaluation prompts are
  byte-identical to main.
- The standing gate figure for this merge is a WORKTREE figure and does not replace the baseline in
  `docs/TEST_GOVERNANCE.md` section 1.
