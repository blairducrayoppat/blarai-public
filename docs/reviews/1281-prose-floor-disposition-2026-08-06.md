# #1281 placeholder-prose floor — review disposition (2026-08-06)

Independent review of `feat/1281-placeholder-prose-floor` at `cf79f0a4`. The reviewer drove
20 adversarial cases through the real `extract_visible_text` -> `scan_visible` and measured
seven false positives, four of them at HIGH, plus a silencing vector that nothing counted.

Why the false positives outrank noise: `card.py` orders the operator's single caveat slot as
`_caveat_from_security(...) or _caveat_from_prose(...) or _caveat_from_layer1(...)`. A false
prose caveat does not add a wrong sentence beside a right one — it DISPLACES the true Layer-1
caveat and leaves the operator with only the wrong one.

Fixes landed in `5af333b0` on `feat/1281-placeholder-prose-floor`, with `8f6f886d` narrowing
the config-gate permission that FIX 6 required and closing a fail-closed gap the second review
pass found. Author of the fixes is not the reviewer; verification of this record belongs to the
reviewer, per author-not-verifier.

## What was measured, before and after

The reviewer's probe, re-run against the fixed module:

| case | before | after |
| --- | --- | --- |
| "Your logo here — become a supporter of the festival." | HIGH | quiet |
| "Advertise your business here from just 20 pounds a month." | HIGH | quiet |
| "Enter your address here and we will confirm by email." | HIGH ×2 | quiet |
| "Enter your bio here." | HIGH ×2 | quiet |
| "The title goes here, between the tags." | HIGH | quiet |
| "Ridge Pottery, 23 Main Street, Hexham" | medium | quiet |
| "Please enter your address, city, state and postcode." | medium | quiet |
| `<template><img alt='Lorem ipsum…'>` | HIGH ×2 | quiet |
| unclosed `<pre>` then lorem ipsum (through `scan_repo`) | CLEAN, 0 findings | HIGH, named in status |
| "123 Main Street, Boston" | medium | medium (unchanged — canonical) |
| `placeholder="you@example.com"` | quiet | quiet (unchanged) |

The seed proof still passes: the real `agentic-setup/build-infra/web-static/reference` seed's
`<h1 class="placeholder">Page title goes here</h1>` and "Replace this paragraph with the real
introduction the goal asks for" are both still HIGH.

## Disposition

```disposition
FIX-1 HIGH tier convicts genuine copy (sponsor slot, directory ad, two form labels) | FIXED | 5af333b0 - instruction matched by SHAPE: the "your NOUN here" form must be a whole fragment and the "NOUN goes here" form must end one (see `_FILL_IN_BARE_RES` and `_FILL_IN_TAIL_RES`); `enter` dropped from the imperative alternation; logo/business/brand dropped from the possessive noun list
FIX-2 `1?23 Main Street` convicts a real address on the commonest street name | FIXED | 5af333b0 - optional digit removed; only the canonical 123 matches, and both halves are pinned
FIX-3 an unbalanced suppressed tag silences the rest of the page, uncounted | FIXED | 5af333b0 - carried out of the parser as VisibleText.truncated, counted, named in the status, and backed by a raw unambiguous re-scan of the page
FIX-4 "your address, city, state" convicts a real checkout instruction | FIXED | 5af333b0 - pattern REMOVED rather than narrowed; no narrowing separates the template's example line from the form's own field list, because they are the same words
FIX-5 attributes are read inside suppressed regions | FIXED | 5af333b0 - handle_starttag now returns early while suppressed, so both halves of the suppression contract agree
FIX-6 band and card contribution ships live rather than dormant | FIXED | 5af333b0 - gated on [fleet_dispatch].green_quality_prose_band, default false, validated-not-coerced and fail-closed; sidecar, evidence stamp, rollup and KPI stay unconditional
EXTRA-1 config-truth gate cannot express a dispatch-side ceremony flag | FIXED | 5af333b0 then narrowed in 8f6f886d - tools/ is declarable and consumable for DISPATCH-SIDE SECTIONS ONLY via `_roots_for`, so an AO-runtime flag still cannot declare a tools/ symbol nor pass consumption on a literal only dispatch tooling reads; four planted tests cover both grants and both refusals
EXTRA-4 prose_band_enabled guarded the config load but not the value read | FIXED | 8f6f886d - both fault sites now inside the try, and test_a_config_fault_denies_the_consequence_rather_than_raising exercises both; the docstring promised denial in every direction while a cfg whose property raised would have propagated
EXTRA-2 a page ABOUT lorem ipsum is convicted at HIGH | REJECTED | Not a defect of this tier. A delivered page whose visible words include the Latin filler corpus is what the rule is defined to catch, and the tier's whole claim is that it holds without context; the alternative is a topic detector, which is the model-grade judgment #1281 explicitly excludes. The reviewer's own probe labelled this case a deliverable rather than a false positive, and it was not among the findings handed over.
EXTRA-3 alt text reading "Placeholder image for the upcoming gallery" is convicted at HIGH | REJECTED | Not a defect. That alt text ANNOUNCES the image as a placeholder in the words a screen-reader user hears, which is precisely what RULE_FILL_IN_THE_BLANK is for; silencing it would blind the rule on the one surface where a sighted reviewer cannot see the problem. Left firing deliberately, and recorded here so the decision is visible rather than merely unmade.
```

## Mechanism notes — where the fix differs from the finding's suggested shape

Three, none of them a disagreement with a finding. Each is a place where the outcome the
finding asked for was reached by a different route, or exceeded.

**The gate lives at the composition seam, not inside `band.py` and `card.py`.** The finding
named those two modules as where to make the contribution conditional. A config read inside
`band_reasons` would have cost that function the purity its own docstring calls "the
load-bearing lock of the whole instrument". Instead `audit_green` withholds the prose result
from both consumers when the flag is not granted, which reaches the same two surfaces through
one seam and is dormancy by structural absence rather than by a branch — the stronger form.
Both modules' docstrings now name the flag as the authority.

**FIX 3 recovers the finding as well as disclosing the silence.** The finding asked for
`parser._suppress != 0` to be checked at close and named in the status alongside `unparsed`.
That shipped. The page is ADDITIONALLY re-scanned through the unambiguous tier over its raw
source — the fallback an unparseable page already receives — so the lorem ipsum that was
silenced is now reported rather than merely flagged as possibly-missing. A superset of what
was asked for, not a departure from it.

A tree containing one sloppy unclosed `<pre>` and otherwise genuine copy is still reported
CLEAN, with the blind spot named in the status — the same treatment the module already gives
`unparsed`. Forcing a non-clean disposition there would manufacture a false positive by
construction, in a module whose first principle is that false positives are worse than misses.

**FIX 1 also retired an eighth false positive nobody had named.** "The title goes here, between
the tags" is a tutorial explaining markup, convicted at HIGH by the `NOUN goes here` rule. It
could not be made whole-fragment without breaking the seed proof (the seed's heading carries a
leading word), so that rule is anchored at the fragment's END instead: the seed still fires,
the tutorial does not.

## The gate permission FIX 6 required, and why it is bound to one section

FIX 6 could not be built as specified. `tests/security/test_config_comment_truth.py` refused
capability declarations outside `shared/`, `services/` and `launcher/`, and scanned only those
roots for consumption — so a `[fleet_dispatch]` flag read solely by the battery harness could
carry no machine-checked declaration at all. The only way to ship one without touching that
gate was a comment block dodging every membership trigger, which is the escape that file
documents as an honest limit and is worse than the lie the gate exists to catch.

The first attempt granted `tools/` globally, and that was broader than the need. Two
independent concessions came with it: an AO-runtime flag could declare a `tools/` symbol, and —
the half the honest-limits section failed to name — an AO-runtime flag whose key literal
appeared only in dispatch tooling could pass CONSUMPTION where it previously raised
`unconsumed-flag`. On a gate whose whole purpose is that documentation must not overclaim, a
limits section naming one of two costs is the defect the file exists to catch, in its own voice.

`8f6f886d` binds the permission to `_DISPATCH_SECTIONS` through a single `_roots_for(section)`
authority that both checks consult. Measured: the identical, entirely truthful declaration
resolves under `[fleet_dispatch]` and is refused under a runtime-owned section, and the needle
`green_quality_prose_band` is present in the dispatch blob and absent from the runtime one.
Both concessions are gone, so the honest-limits bullet got shorter rather than longer.

## Not done

Nothing in the six findings was deferred. Two residual false positives are REJECTED above with
argument rather than ticketed, because a ticket filed to stop thinking is a dropped finding
wearing a queue entry.

One residual is NOT this record's to dispose of and is named here so it is not invisible: the
silencing disclosure reaches the sidecar `status` but not the `green_quality_prose` evidence
stamp. It is acceptable because the residual loss past an unbalanced-tag break is MEDIUM-tier
only and MEDIUM never moves a band or a card. The lead session is ticketing it; this branch
does not carry the fix.

The branch is NOT merged and the ticket is NOT closed — the reviewer verifies, and the standing
gate's baseline bump belongs to the merging session on merged main.
