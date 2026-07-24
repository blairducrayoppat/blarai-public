# Disposition — #994 doc-rot control build findings (2026-07-20)

Building the #994 doc-rot structural control ran a new verification pass (the
`verify_doc_pointers_and_banners.py` checker) across `docs/`. That pass returned
findings; per `<deferral_discipline>` every one gets a disposition here, and the
verifier `scripts/verify_disposition.py` is run against this record before the
work is reported done.

## Context

The checker was built to catch the documentation-asserts-a-false-state class
that recurred ~6× in 48 hours (#978, #979, #988, #990). Running it surfaced two
kinds of finding: real dead pointers that #979 missed (fixed as part of landing
the gate, at the LA's explicit direction), and a large inline-path backlog whose
measured shape decided the gate's scope.

## Findings

### 1. Dead markdown links #979 missed (22 flagged; 13 fixed, 9 in tombstone docs left as-is)
The checker flagged 22 dead markdown links. **13 were in LIVING docs and were
fixed:** `docs/governance/` linked three since-RENAMED ADRs (010/011/012, 8 links);
`README.md` linked an absent `fleet-hygiene.md` (2, struck `RETIRED (file absent)`);
the live `LA_REBOOT_CHECKLIST.md` linked a bare `AUTONOMOUS_FLEET_OPERATIONS.md`
(3, repointed to its archived copy). **The other 9 were in wholesale-RETIRED
"tombstone" runbooks** (`LA_CAR`, `LA_FLEET_REPORTS`, `LA_SPRINT_KICKOFF/DEBRIEF`) —
see finding 5.

### 2. Resolver false positives
The first draft flagged `Use%20Cases_FINAL.md` (a real file — needed percent-
decoding), and `javascript:` / `url` / `{turns}` illustrative placeholders. Fixed
in `_clean_target`: percent-decode, scheme-skip, placeholder-skip. These are
locked by both-directions negative controls in the gate test — the reason the
pair could not go green before the fix is exactly this class.

### 3. Inline path references are not gated (scope decision)
The inline-path scan over all of `docs/` produced 2,892 hits vs 118 markdown-link
hits. The inline set is dominated by non-defects: backup-directory layouts in the
disaster-recovery runbook, retired-fleet-world paths, gitignored model-internal
dirs (`unet/`), and cross-repo agentic-setup refs. Gating that would be the exact
cry-wolf failure this control exists to prevent, so the gate covers markdown links
only; inline-checking is retained behind `--inline` but not gated. A bounded,
optional cleanup of the *living* runbooks is tracked as #995. This is a REJECTED
disposition (the premise "the gate should cover inline refs" is refused with
measurement), not a deferral of a #994 defect — the #994 defect class (dead
pointers) is fixed.

### 4. Independent adversarial review (author != verifier, pre-merge)

An independent reviewer who did not write the code found six real defects before merge — most severely that the ceremony-banner detector was a bare document-wide EXECUTED search, which both defeated the #990 guarantee (a live-flag runbook containing the incidental word "executed" passed) and cried wolf on a pending runbook. All six were fixed on the branch before merge, each with a both-directions regression lock. That is the value of the separation: a control built to catch "looks-done-but-isn't" shipped its first draft with exactly that flaw, and only an adversarial second reader surfaced it.

### 5. Merge-time: I contradicted a deliberate "left as-is" decision in 6 tombstone runbooks

Switching to `main` to merge revealed that six of the runbooks whose dead links the
checker flagged carry whole-document SUPERSEDED / ⛔ RETIRED banners, four of which
say the dead links are **"left as-is rather than repointed, because the procedures
they belong to are themselves retired"** — a documented #945/#979 decision. Reading
only the flagged link lines, not the top banners, I had repointed/struck 9 of them,
contradicting that decision. The checker was mechanically right (the links are dead)
but the right remediation was to recognise these docs as historical tombstones and
exclude them (like `docs/archive/`), not to "fix" links a human chose to leave.
Resolved: the four docs restored to `main` verbatim, and a `_is_tombstone` exclusion
added (keyed on a SUPERSEDED/RETIRED heading WORD, not the ⛔ emoji — so
`at_rest_encryption_ceremony.md`'s live "⛔ STOP - DO NOT DELETE" warning stays
gated, and `LA_OPERATIONS_INDEX.md`'s "⚠ PARTIALLY RETIRED" living index stays gated).

```disposition
Dead markdown links #979 missed (ADR renames, archived fleet-ops, absent DEC/fleet-hygiene) | FIXED | branch docs/994-doc-rot-gate — 22 links repointed or struck RETIRED across governance/ + 5 runbooks
Resolver false positives (Use%20Cases percent-encoding, javascript:/url/{turns} placeholders) | FIXED | branch docs/994-doc-rot-gate — percent-decode + scheme/placeholder skip in _clean_target, pinned by both-directions negative controls
Inline path references not covered by the gate | REJECTED | measured 2892-hit corpus scan is dominated by non-defects (backup layouts, retired-fleet paths, gitignored model dirs like unet/, cross-repo refs); gating them is the cry-wolf failure the control prevents; capability kept behind --inline and documented; optional bounded living-runbook cleanup tracked as #995
Banner detector too loose: a bare document-wide EXECUTED search gave a false-negative on an incidental word and a false-positive on pending prose | FIXED | branch docs/994-doc-rot-gate — tightened _EXECUTED_BANNER_RE to the shipped banner forms; both directions locked by test_incidental_executed_word_is_not_a_banner and its pending twin
Whole-line RETIRED-marker skip hid a live link sharing the line | FIXED | branch docs/994-doc-rot-gate — skip scoped to strikethrough spans only; test_dead_link_sharing_a_line_with_a_retired_note_is_still_caught
Only the first gating declaration was honored, and trailing text after the comment close broke detection | FIXED | branch docs/994-doc-rot-gate — finditer over all declarations + tolerant value capture; test_multiple_declaration_lines_are_all_checked and test_trailing_text_after_comment_close_still_parses
Gating-state was an unchecked config bypass | FIXED | branch docs/994-doc-rot-gate — closed label allowlist _VALID_GATING_STATES; test_unknown_gating_state_is_caught
Reference-style dead links were unchecked | FIXED | branch docs/994-doc-rot-gate — added _MD_REFDEF_RE with a conservative path-shape filter so spec lines are not flagged; test_reference_style_dead_link_caught_but_spec_lines_are_not
Repointed/struck dead links in 6 wholesale-retired tombstone runbooks, contradicting a deliberate "left as-is" decision | FIXED | branch docs/994-doc-rot-gate — restored the 4 edited docs to main verbatim and added a _is_tombstone exclusion (SUPERSEDED/RETIRED heading word, not the emoji); test_tombstone_docs_are_excluded_but_partially_retired_is_not
```

## Honest limit

This record disposes of the findings the checker RETURNED. The checker itself does
not catch semantic falsehoods (a comment claiming a lock that isn't engaged); that
class stays with human/adversarial review or an executable posture check (#977),
and is stated as a limit in the verifier's and the gate test's own docstrings.
