---
title: "#1578 audit key rotation — adversarial review disposition"
status: final
area: security
---

# Disposition — #1578 (a key rotation must not brick the audit chain)

**Review run 2026-09-18, pre-merge, by an agent that did not write the code.** Target `429c5732`
(branch tip `1270b968`); fixes in `bdc23f30`. The reviewer was told this session had shipped ten
defects of one shape, and that two of its "structural" locks had already been defeated — once by a
string literal, once by a comment.

**The finding in one line: the remedy caused the defect. The ceremony bricked the Policy Agent on the
SECOND boot, and the only reason it had never fired is that the ceremony could not be run at all.**

```disposition
# finding | status | evidence-or-predicate
review finding 1 (CRITICAL) — THE CEREMONY BRICKS THE POLICY AGENT ON THE SECOND BOOT AFTER A ROTATION. Both services chose their signing key from the compiled-in AUDIT_TPM_KEY_NAME; read_history had exactly ONE production consumer and it chose only the VERIFICATION start. So after the ceremony wrote a bridge declaring the new key, the service rebooted holding the RETIRED key and appended adjudications signed by it AFTER that bridge. Boot #1 verified — nothing followed the bridge yet — and the runbook's Step 3 ("if it starts, the rotation is complete") confirmed success at exactly the moment the chain was being poisoned. Boot #2 walked to the bridge, switched keys as designed, and refused. Reproduced across three boots. NO RECOVERY EXISTS: the ceremony's own step 1 refuses on a chain that does not verify, and append_key refuses to re-adopt a retired key, so both shipped escapes are closed by design | FIXED | bdc23f30 — _audit_signing_key_name in BOTH services returns the newest history entry, falling back to the constant only when there is no history. Re-ran the reviewer's scenario: three consecutive boots all verify and all sign with the key the bridge declared. Locked by test_three_consecutive_boots_after_a_rotation_all_verify, which exists in that shape because the defect PASSED boot #1 — a single-boot test would have certified it. A history that does not name a TPM key now raises rather than falling back, since falling back is what produced the state
review finding 2 (HIGH) — THE FAST PATH ACCEPTED A CHAIN FORGED UNDER A KEY THE OPERATOR NEVER ADOPTED, with no bridge record at all. Each segment-index row picked its verifier from its own claimed signer_id, independently of the key in force, and tpm_key_resolver resolved ANY key provisioned on the chip — measured on the real TPM, that is four keys, three of which (model-manifest, PA-JWT, DEK-sealing) have nothing to do with the audit chain. The parent commit REFUSES the same forged chain, so this was introduced by rotation support, and it opens precisely when the feature is used, because a resolver is only passed once a rotation has happened. verify()'s docstring claimed an attacker "cannot smuggle in a key because reaching the end would require forging a bridge" — false, no bridge was needed | FIXED | bdc23f30 — tpm_key_resolver takes the chain's key history as a DENY-BY-DEFAULT allowlist, and _row_verifier refuses a row naming a key outside that order or one PRECEDING the key already in force. Re-ran the reviewer's forgery: refused on both paths, with the genuine rotated chain still verifying on both as the control. The docstring now states what is actually bounded — which keys a chain may be signed by — and names the limit: this does not stop someone who can already sign with a key in the history
review finding 3 (HIGH) — THE CEREMONY NAMED A FILE NO SERVICE WRITES. _default_log_path returned audit.jsonl; the real chains are adjudication_audit.jsonl (Policy Agent, under its SERVICE root, not LOCALAPPDATA), ingest_audit.jsonl and verdict_audit.jsonl. The runbook's Step 1, run verbatim, printed "REFUSED: no audit log at ..." — an outcome the runbook does not document. This is also why finding 1 had never fired: the two defects masked each other | FIXED | bdc23f30 — discover_chains() finds the real chains and skips the segment index; _resolve_log_path uses the only one present and REFUSES TO GUESS between several, because rotating the wrong chain writes a bridge that cannot be undone. The runbook gains a Step 0 naming all three chains and where each lives, and the --audit-log flag it never mentioned
review finding 4 (MEDIUM) — the Assistant Orchestrator's two chains were not wired at all: bare log.verify() and a hardcoded signing key. A ceremony aimed at a compromised key would have rotated the Policy Agent and left ingest and verdict signing with the suspect key indefinitely, with nothing reporting it. Both chains also live in ONE directory while history_path was parent/audit-keys.json, making a per-chain rotation unrepresentable | FIXED | bdc23f30 — both AO chains read their own history for signing and verification. history_path is now per CHAIN, named after the log file stem plus the -keys.json suffix, locked by a test that rotating one chain does not declare a key the other never adopted
review finding 5 (MEDIUM) — rotate_signing_key's docstring set out the REJECTED ordering as if implemented, with its rationale and conclusion, contradicted by the inline comment eight lines below and by the code. Its stated invariant — that no sealed segment spans a rotation — is FALSE: measured, one always does on the first seal after any rotation, including in this branch's own fixture. Verification survives it because the record walk chains through the bridge and the summary format is versioned | FIXED | bdc23f30 — the docstring now describes seal-then-bridge, says why, and carries the spanning case as an explicit HONEST LIMIT rather than claiming it was designed out. It matters to whoever next touches the index format
review finding 6 (LOW) — the recovery guidance was circular: the key-mismatch operator_guidance says to run the ceremony, and the ceremony printed that same guidance when its own verification refused. In the state finding 1 produced, the Policy Agent said "run the ceremony" and the ceremony said "run the ceremony" | FIXED | bdc23f30 — the ceremony writes its own remedy per fault class and never echoes operator_guidance. My first lock for this was a text search that matched the COMMENT explaining the removal — the third time this session a source scan certified its own explanation — so it is rebuilt on the AST, where an attribute access is a node and a comment is not
review finding 7 (LOW) — history[-1].split(":", 1)[1] raised a bare IndexError on a colon-less history entry, and yielded an empty key name for ":" or "a:" | FIXED | bdc23f30 — partition with an explicit REFUSED message naming the malformed entry
review finding 8 (LOW, hypothesis the reviewer did not reproduce) — the rotation read the outgoing id, sealed, appended and swapped the signer across THREE separate lock acquisitions. A concurrent append between the bridge and the swap is signed by the old key and lands after the bridge, producing finding 1's state directly | FIXED | bdc23f30 — one RLock held across the whole ceremony. Recorded as fixed rather than rejected-for-want-of-a-reproduction: the window is real in the code, the fix is a few lines, and the state it produces is the one that has no recovery
reviewer's note — the cross-commit migration and the 32-lock suite could not be dented: v1 summary bytes byte-identical to the parent's, a legacy chain verifies fast and full, a tamper in it is still caught, and ten mutants against the original locks all died | REJECTED | Not a defect. Recorded because it is the part of this change that was built correctly the first time, and the contrast is the useful information: the locks over the ALGORITHM held, and every defect above was in the WIRING the algorithm needed to be real
```

## What the reviewer attacked and could not break

- **Cross-commit migration.** A chain written entirely with `429c5732^`'s code — sealing three
  segments — verifies under the new code, fast and full, with all three v1 summary byte strings
  byte-identical and `summary_version` reading as 1. A tamper inside a sealed legacy segment is still
  caught in both modes.
- **All 32 original locks fire.** Ten mutants, none survived.
- **`--dry-run` changes nothing** — directory snapshot by size and SHA-256 before and after is
  identical — and no code path deletes a key.
- **Bridge injection via a request** is unreachable: `ActionVerb` is a closed enum and `build_car`
  coerces through it. The reviewer correctly notes the protection is upstream and incidental; the
  audit log itself accepts any verb.
- **Forged history, withheld key, missing resolver, wrong starting key, redirected bridge, deleted
  bridge** all fail closed.

## The honest note

Every defect above is in wiring, not in the algorithm. The bridge design, the versioned summary and
the migration were right the first time and survived a determined attack. What was wrong was that
nothing in production used them: the signing key still came from a constant, the resolver opened onto
the whole keyring, and the ceremony pointed at a filename that does not exist. That is the same
failure this session has now shipped in three separate tickets — a mechanism built correctly and
connected to nothing — and here it produced a remedy that would have bricked the service it was
written to rescue.
