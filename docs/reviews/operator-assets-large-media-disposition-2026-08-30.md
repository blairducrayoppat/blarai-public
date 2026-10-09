# Disposition — operator-assets large-media arc (#1469), adversarial review 2026-08-30

**Change under review:** `agentic-setup` `3925d3e` + `d772b52` (the widened `Add-AssetHint`),
alongside the BlarAI half on `feat/1165-operator-assets-large-media` (caps 25 MB → 2 GB,
`video`/`audio` classes, markup floor derived from media classes only, card size disclosure).

**Reviewer:** independent adversarial pass, author excluded from verification. Every finding
was reproduced by running the function against constructed directory trees; the reviewer also
re-ran the suite under pwsh 7.6.5 and Windows PowerShell 5.1.26100.

**Outcome:** 9 findings, plus one re-ranking on a second pass. Nothing deferred. The three
the reviewer flagged as merge blockers were all the change's own stated purpose failing one
level deeper, and all three are fixed with kill-tests rather than ticketed.

**Verification after fixes:** `verify-assets.ps1` 37 → **55 checks, all passing under both
pwsh 7.6.5 and Windows PowerShell 5.1**. BlarAI standing gate 11272 passed / 0 failed /
7 skipped / 133 deselected (481.93 s) — the 7 skips all name `AO loopback port 5001 is in
use`, the documented signature of the operator's app being open.

```disposition
served-root-404: web seeds serve public/ only, so a root assets/ file was handed to the coder as a path guaranteed to 404, while the filename-presence floor still passed the broken build | FIXED | agentic-setup@f172973 - each entry carries whether it is under the served root; unserved files are marked and told to be copied into public/assets/ first. Kill-tests AH38-AH48.
fonts-graded-but-never-named: `other` (ttf/otf/woff/woff2) is inside _OPERATOR_ASSET_MARKUP_CLASSES so the smoke floor demands the font filename in markup, but the steer skipped fonts entirely - a guaranteed undiagnosable failure for a fonts-only folder | FIXED | agentic-setup@f172973 - fonts get their own @font-face block. Kill-tests AH49-AH51.
card-and-steer-disagree: the manifest applies an ASCII filename allowlist and reports the rest as skipped; the steer had none, so the card said "5 skipped, rename them" about the five the coder was told to use, and dropped four the card said the build was graded on | FIXED | agentic-setup@f172973 - the manifest allowlist and path cap are mirrored in the steer. Kill-tests AH52-AH53.
ah34-ah35-over-certify: the "each file is named ONCE" fixture only built one directory, so it could not reach the case where the duplicate returns (two genuinely different asset dirs) | FIXED | agentic-setup@f172973 - AH45-AH48 build public/assets and assets together and count occurrences of the served file.
binary-docs-impossible-order: pdf/docx/xlsx/odt were ordered "OPEN AND READ EACH ONE ... NOT optional" with no caveat for a format the coder cannot read, while the next paragraph forbade the only remaining move | FIXED | agentic-setup@f172973 - an explicit unreadable-format exception that still forbids inventing a value. Kill-tests AH54-AH55.
console-line-false-provenance: new-agent-task.ps1 announced "Generated image assets present" for a documents-only or video-only folder - the provenance falsehood retired on 2026-08-06, plus a file class that was not there | FIXED | agentic-setup@f172973 - the line now describes what was actually emitted and claims no provenance.
suite-header-asserts-inverted-rule: verify-assets.ps1's .SYNOPSIS/.DESCRIPTION still advertised "non-image files are ignored" and scoped the suite to pre-generated raster images | FIXED | agentic-setup@f172973 - header rewritten, with the retired claim kept visible and dated so a later reader sees why it changed.
dead-Assets-mapping-entry: the third mapping entry ('Assets') can never fire on a case-insensitive filesystem, and its accompanying comment mis-described the dedupe as what makes the web path strip public/ | REJECTED | The entry is deliberately retained rather than deleted: it is unreachable on Windows but correct and necessary for any case-sensitive consumer of the same worktree (a Linux deploy, an MSBuild content path), and removing it would silently break that case to tidy a line that costs nothing. The mis-describing comment WAS a real defect and is corrected in f172973. Reviewer ranked this LOW and explicitly did not block on it.
no-filename-hygiene-on-prompt-path: untrusted directory text reached an LLM prompt with one validator where the manifest path has two (defense-in-depth / validate-before-trust) | FIXED | agentic-setup@f172973 - the same per-component ASCII allowlist now runs on the steer path, so the second validator exists. Same change as card-and-steer-disagree; recorded separately because it is a distinct security property.
```

## Notes carried forward, not deferred

- **The reviewer could not measure incidence.** `verify-assets.ps1` is one of ~65 hand-run
  `verify-*.ps1` scripts with no automated runner referencing it, so there is no bank of
  asset-hint outputs to count against. Findings 1–3 are argued from the *designed* directory
  layout, not from observed dispatches. Zero observed incidence is a reason to be calm, not a
  reason to ship — and the first real dispatch of `blairproweb` will be the first observation.
  That absence of a runner is itself worth a ticket and is recorded on #1469.
- **`agentic-setup/docs/LESSONS-LEARNED.md:1640`** describes the pre-widening behaviour
  ("verify-assets — 15 checks … non-image-ignored"). Correctly scoped to what was true at #714
  on 2026-06-30, and append-only lessons are history: **left as written, deliberately.**
