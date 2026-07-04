# Stage 3 EA-Numbering Posterity Correction (Ticket A)

**Status:** Active — canonical correction artifact for the EA-numbering defect documented at STATUS.md Anomaly A12.
**Authored:** 2026-05-07 (Stage 6 Phase 3, EA-12).
**Tracking:** Vikunja DevPlatform-Meta (project 10) Ticket A (id 282).

---

## Origin

Anomaly A12 — EA-numbering defect. Stage 3 verdict files used `g7-ea1_n*` labels (reflecting the *first* EA spawned for Stage 3, locally numbered `EA-1`), but the correct global identifier per the project's cross-stage cumulative EA count is `g7-ea7_n*` (Stage 1 EA-1, Stage 2 EA-2..EA-6, Stage 3 EA-7). This is documented in the user's feedback memory `feedback_ea_numbering_global.md`:

> "EA numbering is global, not stage-scoped — Stage 3 EA is EA-7 (global count from Stage 1 EA-1, Stage 2 EA-2..EA-6). New acks: g7-ea7_n*. Prior g7-ea1_n* in committed verdicts is documentation defect deferred to Stage 6.7.5."

Per the no-amend doctrine for committed audit artifacts (`dn30`, also reinforced as `dn25` in `3.10-GUIDE_HANDOFF_INSTANCE_7_TO_8.xml`), the four frozen Stage 3 verdict files are NEVER retroactively edited. This document is the canonical correction artifact: callers who encounter `g7-ea1_n*` in Stage 3 verdict files must resolve to the corrected `g7-ea7_n*` form via this table. The frozen verdict files remain as originally emitted.

The first verdict to adopt the corrected global naming convention is `3.10-GUIDE_RESPONSE_INSTANCE_7_STAGE3_CLOSE_VERIFIED.xml`, which introduces ack `g7-ea7_n14` (already correct, not in this correction's scope) while restating the prior n10..n13 acks verbatim under their original `g7-ea1_n*` labels per `dn30`.

---

## Section 1 — Canonical Ack Declarations (per ack ID)

The Stage 3 ack chain comprises 13 ack atoms (n1–n13) declared under the defective `g7-ea1_n*` namespace, plus `g7-ea7_n14` (already corrected, declared in the Stage 3 close-verified verdict). The table below maps each defective label to its corrected form and the canonical declaration source.

| Ack ID (verbatim from verdicts) | Corrected ID | Canonical Declaration | Substantive Content |
|---|---|---|---|
| `g7-ea1_n1` | `g7-ea7_n1` | 3.0.v2 line 656 | Initial Stage 3 EA-1 comprehension gate iter-1 acknowledgments (n1 through n9). |
| `g7-ea1_n2` | `g7-ea7_n2` | 3.0.v2 line 657 | [g7-ea1_n2 from initialization pointer; standing.] |
| `g7-ea1_n3` | `g7-ea7_n3` | 3.0.v2 line 658 | [g7-ea1_n3; standing — v2-baseline file list, including the spec-drift line that triggered n11.] |
| `g7-ea1_n4` | `g7-ea7_n4` | 3.0.v2 line 659 | [g7-ea1_n4; standing — governance count "7 files" inheritance from INFRA_DELTA_v2.md §1.2 (subsequently superseded by n12).] |
| `g7-ea1_n5` | `g7-ea7_n5` | 3.0.v2 line 660 | [g7-ea1_n5; standing — `.copy_manifest_v2.yaml` schema for Item 3.10.v2.] |
| `g7-ea1_n6` | `g7-ea7_n6` | 3.0.v2 line 661 | [g7-ea1_n6; standing — `daily_digest --dry-run` smoke verification for Item 3.7.] |
| `g7-ea1_n7` | `g7-ea7_n7` | 3.0.v2 line 662 | [g7-ea1_n7; standing — devplatform/docs/ no-BlarAI-pattern verification for Item 3.8.] |
| `g7-ea1_n8` | `g7-ea7_n8` | 3.0.v2 line 663 | [g7-ea1_n8; standing — single Stage-3 commit on devplatform main, parent `3894221`, for Item 3.9.] |
| `g7-ea1_n9` | `g7-ea7_n9` | 3.0.v2 line 664 | [g7-ea1_n9; standing — append-only STATUS.md update on BlarAI side for Item 3.10.] |
| `g7-ea1_n10` | `g7-ea7_n10` | 3.0.v2 line 665 / 3.10 line 507 (restated) | OQ-1 V0i HEAD drift dispositioned as STATUS-staleness; verdict `3.1-GUIDE_RESPONSE_INSTANCE_7_ITERATION_1_APPROVED_STAGE3_EA_1.xml`. Iter 1 EA-7 gate APPROVED. |
| `g7-ea1_n11` | `g7-ea7_n11` | 3.1.v2 line 210 (NEW_THIS_VERDICT, FORWARD-ACTIVE-AT-3.10) / 3.0.v2 line 666 + 3.10 line 508 (restated standing) | Item 3.1.v2 `escalation_watchdog.ps1` spec-correction (option a: hyphen → underscore); verdict `3.1.v2-GUIDE_RESPONSE_INSTANCE_7_ITEM_3_1_V2_VERIFIED_SPEC_CORRECTION_AUTHORIZED.xml`. |
| `g7-ea1_n12` | `g7-ea7_n12` | 3.2.v2 line 534 (NEW_THIS_VERDICT, HIGH, FORWARD-ACTIVE-AT-3.10-AND-AT-STAGE-5-EA) / 3.0.v2 line 667 + 3.10 line 509 (restated standing) | Item 3.2.v2 selective governance copy (3 fleet-only files copied; 14 BlarAI-runtime files preserved) + 11 noted-for-Stage-EA findings (F-N1..F-N11) + two-layer audit binding (Stage 4 PRIMARY + Stage 5 SECONDARY) + 4 Stage 6.7.5 hardening tickets (A–D); verdict `3.2.v2-GUIDE_RESPONSE_INSTANCE_7_ITEM_3_2_V2_RECLASSIFICATION_REQUIRED_SELECTIVE_COPY_AUTHORIZED.xml`. |
| `g7-ea1_n13` | `g7-ea7_n13` | 3.0.v2 line 668 (NEW_THIS_VERDICT) / 3.10 line 510 (restated standing) | Stage 3.X comprehensive audit checkpoint amendments — Items 3.4 through 3.10.v2 spec-correction binding, sub-clauses (a) through (h). Audit evidence at `docs/platform_separation/temp_for_responses/3.0.v2-AUDIT_SUBAGENT_OUTPUT_STAGE3_COMPREHENSIVE_DRIFT_INVENTORY.md`. Discharged at EA-7 Stage 3 close (`76f6050`) per Stage 3 Closure Footnotes §4. |

**Note on `g7-ea7_n14`:** Already correctly named (the first ack atom to adopt the global ea7 convention). Declared at `3.10-GUIDE_RESPONSE_INSTANCE_7_STAGE3_CLOSE_VERIFIED.xml` line 511. Not in scope of this correction. Substance: Stage 3.10 closure verification — three-subagent convergence on VERIFIED; five new findings dispositioned via sub-clauses (a-d): (a) NEW rr8 Stage 4 preflight gitignore cleanup; (b) Stage 6.7.5 TICKET E scope expansion; (c) Stage 4 init pointer requirement; (d) Stage 6.7.5 TICKET A enrichment.

---

## Section 2 — Per-File Reference Inventory

All `g7-ea1_n*` line occurrences across the four frozen verdict files (Step A-2 grep results). One row per (file × ack) pair; line numbers list every occurrence in that file.

### File: `3.0.v2-GUIDE_RESPONSE_INSTANCE_7_STAGE3_COMPREHENSIVE_AUDIT_CHECKPOINT.xml`

| Ack (verbatim) | Corrected ID | Lines |
|---|---|---|
| `g7-ea1_n1` | `g7-ea7_n1` | 656 (declaration) |
| `g7-ea1_n2` | `g7-ea7_n2` | 657 (declaration) |
| `g7-ea1_n3` | `g7-ea7_n3` | 658 (declaration) |
| `g7-ea1_n4` | `g7-ea7_n4` | 659 (declaration) |
| `g7-ea1_n5` | `g7-ea7_n5` | 660 (declaration) |
| `g7-ea1_n6` | `g7-ea7_n6` | 661 (declaration) |
| `g7-ea1_n7` | `g7-ea7_n7` | 662 (declaration) |
| `g7-ea1_n8` | `g7-ea7_n8` | 663 (declaration) |
| `g7-ea1_n9` | `g7-ea7_n9` | 664 (declaration) |
| `g7-ea1_n10` | `g7-ea7_n10` | 665 (declaration) |
| `g7-ea1_n11` | `g7-ea7_n11` | 156, 403, 472, 502, 666 (declaration), 687, 713, 736, 748 |
| `g7-ea1_n12` | `g7-ea7_n12` | 156, 403, 478, 479, 480, 481, 482, 483, 484, 502, 556, 596, 620, 624, 625, 626, 627, 667 (declaration), 687, 713, 748, 750 |
| `g7-ea1_n13` (incl. sub-clauses) | `g7-ea7_n13` | 12, 33, 37, 156, 219, 225, 403, 469 (n13(f)), 488 (n13(c)), 489 (n13(c)), 490 (n13(c)(iii)), 491 (n13(a)), 501 (n13(g)), 502, 588, 603 (n13(c)(iii)), 611 (n13(f)), 630, 633, 668 (declaration), 674, 687, 713, 731, 735, 748, 750 |

### File: `3.1.v2-GUIDE_RESPONSE_INSTANCE_7_ITEM_3_1_V2_VERIFIED_SPEC_CORRECTION_AUTHORIZED.xml`

| Ack (verbatim) | Corrected ID | Lines |
|---|---|---|
| `g7-ea1_n1` | `g7-ea7_n1` | 284, 298 |
| `g7-ea1_n3` | `g7-ea7_n3` | 44, 167, 204, 216 |
| `g7-ea1_n4` | `g7-ea7_n4` | 280 |
| `g7-ea1_n5` | `g7-ea7_n5` | 291 |
| `g7-ea1_n6` | `g7-ea7_n6` | 286 |
| `g7-ea1_n7` | `g7-ea7_n7` | 287, 296 |
| `g7-ea1_n8` | `g7-ea7_n8` | 78, 288, 302, 306 |
| `g7-ea1_n9` | `g7-ea7_n9` | 245, 262, 289, 303 |
| `g7-ea1_n10` | `g7-ea7_n10` | 54, 245, 246, 262, 289 |
| `g7-ea1_n11` | `g7-ea7_n11` | 72, 86, 210 (declaration), 246, 260, 262, 271, 290, 330, 331 |

### File: `3.2.v2-GUIDE_RESPONSE_INSTANCE_7_ITEM_3_2_V2_RECLASSIFICATION_REQUIRED_SELECTIVE_COPY_AUTHORIZED.xml`

| Ack (verbatim) | Corrected ID | Lines |
|---|---|---|
| `g7-ea1_n1` | `g7-ea7_n1` | 1004, 1026 |
| `g7-ea1_n4` | `g7-ea7_n4` | 336 |
| `g7-ea1_n5` | `g7-ea7_n5` | 1013 |
| `g7-ea1_n6` | `g7-ea7_n6` | 1005 |
| `g7-ea1_n7` | `g7-ea7_n7` | 1007 |
| `g7-ea1_n8` | `g7-ea7_n8` | 1008, 1032 |
| `g7-ea1_n9` | `g7-ea7_n9` | 757, 1010 |
| `g7-ea1_n10` | `g7-ea7_n10` | 298, 757, 1011 |
| `g7-ea1_n11` | `g7-ea7_n11` | 87, 298, 747, 757, 1011 |
| `g7-ea1_n12` | `g7-ea7_n12` | 148, 169, 291, 292, 504, 534 (declaration), 748, 757, 764, 775, 932, 939, 954, 955, 961, 964, 968, 1011, 1076, 1102 |

### File: `3.10-GUIDE_RESPONSE_INSTANCE_7_STAGE3_CLOSE_VERIFIED.xml`

| Ack (verbatim) | Corrected ID | Lines |
|---|---|---|
| `g7-ea1_n10..n13` (collective references) | `g7-ea7_n10..n13` | 19, 45, 345, 504, 523, 531 |
| `g7-ea1_n*` (collective glob) | `g7-ea7_n*` | 118, 504 |
| `g7-ea1_n10` | `g7-ea7_n10` | 507 (restated standing declaration) |
| `g7-ea1_n11` | `g7-ea7_n11` | 508 (restated standing declaration) |
| `g7-ea1_n12` | `g7-ea7_n12` | 357, 474, 475, 478, 482, 486, 509 (restated standing declaration) |
| `g7-ea1_n13` (incl. sub-clauses) | `g7-ea7_n13` | 295, 357 (n13(c)(i)), 490, 491, 510 (restated standing declaration) |

---

## Section 3 — Typo Audit Results (Step A-1)

### `BlarAI/docs/platform_separation/INFRA_DELTA_v2.md` (living reference spec; amendment permitted)

The hyphen-vs-underscore drift on `escalation_watchdog.ps1` (originally surfaced and dispositioned at ack `g7-ea1_n11` per verdict 3.1.v2) was found at five locations in INFRA_DELTA_v2.md. The on-disk reality is mixed: the script is `escalation_watchdog.ps1` (underscore); the matching scheduled-task XML is genuinely `escalation-watchdog.xml` (hyphen). Precision corrections applied:

| Line | Pre-fix | Disposition | Post-fix |
|---|---|---|---|
| 121 | `Pairs with \`escalation-watchdog.ps1\`.` | FIXED — `.ps1` typo | `Pairs with \`escalation_watchdog.ps1\`.` |
| 125 | `### 1.7 \`tools/scheduled-tasks/escalation-watchdog.ps1\` + \`.xml\` ...` | FIXED — `.ps1` typo (header) | `### 1.7 \`tools/scheduled-tasks/escalation_watchdog.ps1\` + \`.xml\` ...` |
| 134 | `escalation-watchdog.xml` | PRESERVED — `.xml` filename genuinely uses hyphen on disk per verdict 3.1.v2 §(a) | (unchanged) |
| 257 | `\`escalation-watchdog\`` (bare reference describing the scheduled task) | PRESERVED — informal bare reference; the actual task name in Task Scheduler is `Escalation Watchdog` (Title Case Spaces). Either underscore or hyphen form would equally misrepresent the live task name. | (unchanged) |
| 337 | `tools/scheduled-tasks/escalation-watchdog.*` (wildcard) | FIXED — split into explicit references because the wildcard cannot accurately resolve both files (script uses underscore; XML uses hyphen) | `tools/scheduled-tasks/escalation_watchdog.ps1, tools/scheduled-tasks/escalation-watchdog.xml` |

### Frozen Verdict Files — Read-Only Grep Results

The frozen verdict files contain references to `escalation-watchdog.ps1` and `escalation-watchdog.xml` as part of the **audit narrative** documenting the original typo's existence and its disposition. These are NOT typos that need correcting — they are documentation of the typo for posterity. Per `dn30`, these references remain verbatim:

- `3.1.v2-GUIDE_RESPONSE_INSTANCE_7_ITEM_3_1_V2_VERIFIED_SPEC_CORRECTION_AUTHORIZED.xml`: lines 17, 23, 27, 41, 95, 112, 124, 126, 130, 152, 153, 219, 222, 255 contain `escalation-watchdog.ps1` (HYPHEN) and `escalation-watchdog.xml` references — all are audit narrative quoting the original typo or referencing the correctly hyphenated XML filename. **No edits.**
- `3.0.v2-...AUDIT_CHECKPOINT.xml`: line 472 already uses `escalation_watchdog.ps1` (underscore — correct); line 473 references `escalation-watchdog.xml` (correct hyphen XML filename). **No defects.**
- `3.2.v2-...SELECTIVE_COPY_AUTHORIZED.xml`: line 477 references `escalation-watchdog.ps1 HYPHEN typo` as audit narrative. **No edits.**
- `3.10-GUIDE_RESPONSE_INSTANCE_7_STAGE3_CLOSE_VERIFIED.xml`: no `escalation-watchdog` references found.

### Adjacent Artifact (handoff brief, not in dispatch's 4-file scope)

- `3.10-GUIDE_HANDOFF_INSTANCE_7_TO_8.xml` line 78: `Stage 3 v2_updates Item 3.1.v2 referenced \`escalation-watchdog.ps1\` (hyphen). Actual filename is \`escalation_watchdog.ps1\` (underscore). Spec-correction option (a) authorized. Bound at ack g7-ea1_n11.` — Audit narrative documenting the disposition. Per `dn30` (extends to handoff briefs as committed artifacts), no edits.

---

## Section 4 — Scope and Authority

This document is the **canonical posterity correction artifact** for the EA-numbering defect documented at `STATUS.md` Anomaly A12 and the doctrine inherited via `dn25` / `dn30`. It does NOT supersede or amend any prior artifact:

- The four frozen Stage 3 verdict files (3.0.v2, 3.1.v2, 3.2.v2, 3.10-CLOSE_VERIFIED) **remain as originally emitted**. Their `g7-ea1_n*` labels are preserved verbatim per the no-amend doctrine.
- The Stage 3 cumulative-ack chain is restated verbatim in successor agent artifacts (Guide-#8 onward) per `dn25`. New acks emitted by Guide-#8+ use the corrected global naming convention (`g8-ea8_n*`, etc.).
- This document provides the **resolution table**: any caller who encounters `g7-ea1_n*` in Stage 3 verdict files (or in restated cumulative-ack chains in successor artifacts) resolves the corrected ID via Section 1.

Future references should use the corrected `g7-ea7_n*` form when discussing Stage 3 acks in non-frozen contexts (new docs, narrative summaries, status reports). Quoting the verbatim verdict text retains the legacy `g7-ea1_n*` form per `dn30`.

---

## References

- **STATUS.md Anomaly A12**: original defect record at `BlarAI/docs/platform_separation/STATUS.md` (the detailed A12 entry documenting EA-1-vs-EA-7 identifier drift).
- **Feedback memory**: `feedback_ea_numbering_global.md` (rule: "EA numbering is global, not stage-scoped — Stage 3 EA is EA-7. Prior g7-ea1_n* in committed verdicts is documentation defect deferred to Stage 6.7.5.").
- **No-amend doctrine**: `dn25` (introduced in Guide-#7 instance, prohibits silent correction of EA-numbering defect in committed verdict files) and `dn30` (Guide-#7 introduction; binds Guide-#8 to use corrected naming for new acks while preserving verbatim restatement of legacy labels).
- **Vikunja tracking**: DevPlatform-Meta project (id 10), Ticket A (id 282).
- **Audit-evidence cross-references** (per `g7-ea7_n14(d)` enrichment): see Stage 3 close-verified verdict `3.10-GUIDE_RESPONSE_INSTANCE_7_STAGE3_CLOSE_VERIFIED.xml` §6.7.5 ticket A enrichment block.
