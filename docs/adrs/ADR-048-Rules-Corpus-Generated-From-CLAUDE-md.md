# ADR-048 — The Rules Corpus Is Generated From CLAUDE.md, Enforcement Is Trace-Marked, and the Slow Tests Run in Their Own Tier

**Status:** Accepted as the design; **partly shipped** (merge `32e31564`, 2026-10-05). The generated corpus, its test, the trace markers and the fast and slow test tiers are merged. Not built: the advisory rules-review pilot and the skills audit's decision; the install-step hardening is in progress on a branch and not merged (see Residuals). No BlarAI runtime change; CLAUDE.md is untouched by this work.
**Date:** 2026-10-05
**Deciders:** The LA directed the analysis (2026-10-05, #1690) of an outside suggestion; the session decided and built (all technical). No capability, quality or runtime posture changed, so no LA decision gate applied. The commit-protection layers are ADR-043 and are not restated here.
**Related:** #1690 (open) · #1687 (the as-built guide draws on this corpus and must stay in sync with its enforcement mappings, comment 3888) · #1679 (gate baseline refresh) · ADR-043 (the commit-protection layers: git-native hooks, text guard, installer, `--no-ff` rule) · `docs/governance/rules-corpus.yaml` · `docs/governance/rules-gaps.md` · `docs/governance/rules-enforcement.yaml` · `docs/governance/rules-corpus-README.md` · `scripts/extract_rules_corpus.py` · `tests/security/test_rules_corpus.py` · `docs/TEST_GOVERNANCE.md` section 4

## Context

The outside suggestion, quoted on #1690: structure rules so they are programmatically extractable rather than embedded in prose; a "rules shadow agent" that loads a rules corpus to gate commits (reads the diff, compares it with the corpus) is emerging; and skills are just context files, reserved for enabling a capability rather than loading context. The LA asked for it to be analysed against Anthropic's agent-skills best-practices guidance and for processes and documents to be updated accordingly.

CLAUDE.md is always loaded and has a byte budget enforced by `tests/security/test_doctrine_freshness.py`; any metadata added to it is a tax on every session. Its rules had no machine-readable index and no record of which rules anything enforces.

## Decision

1. **CLAUDE.md is the only authored source of rule text. The corpus and the gap list are GENERATED and never hand-edited.** `scripts/extract_rules_corpus.py` parses CLAUDE.md into one record per atomic rule (168 rules at the merge: 12 critical, 13 high, 143 normal) and writes `rules-corpus.yaml` and `rules-gaps.md`. Output is deterministic (no timestamps, stable order). `tests/security/test_rules_corpus.py`, in the standing gate, fails when either file differs from a fresh extraction. The extractor is fail-closed: an unbalanced or unclassified tag, an unparseable line in a rule section, a duplicate id, or an enforcement entry naming a rule that does not exist raises and writes nothing; every top-level tag must be classified as rules or as state, so a new section cannot silently escape the corpus. It costs CLAUDE.md no bytes: no ids or metadata live in it.
2. **Ids are derived from the rule's own NAME (its leading words), not its position.** Inserting a rule moves no other id or mapping; a collision raises. A rename or deletion breaks loudly instead of silently moving mappings.
3. **Enforcement is TRACE-MARKED, never inferred.** A test, script or hook declares what it enforces with `enforces-rule: <rule-id> [-- note]` in a docstring or comment; things that cannot carry a marker (the user-level destructive-git hook, reviewer agents) are entries in `rules-enforcement.yaml`. The `enforcement` column is built only from those two sources, and a test checks every marker and curated entry names an existing rule, every curated ref exists, and the column equals an independent re-scan of the repository. **The column means a marker or curated entry exists; it is the enforcing file's author's claim, not a coverage measurement.** The kinds are `test`, `hook`, `verifier`, `reviewer`, `gate`, `none`. Reading the diff of the corpus after regeneration is part of the process: a changed enforcement column is a claim to review.
4. **The gap list is the product.** Tallied from `rules-corpus.yaml`: 29 of 168 rules have an enforcement entry (26 with a test, hook, verifier or gate entry, which is a marker or curated claim and not a coverage measure, and 3 reviewer-only curated entries; one of the 26 also carries a reviewer entry); 139 have none. `rules-gaps.md` lists the 142 that have no test, hook, verifier or gate (139 `none` plus 3 reviewer-only), by severity with a suggested cheapest check that is a suggestion and not a decision. Six critical rules read `none` (including the atomic-ship motion, the comprehension gate, performance recording, test-the-seams). Making a gap smaller means building the check and its marker, not editing the column.
5. **Fast and slow test tiers** (TEST_GOVERNANCE section 4). The commit-protection tests (real bash and PowerShell, a recording git shim, fuzzed variants, mutation runs) are expensive, so the git-tooling tests are marked `slow` per test (`_git_hook_helpers.mark_slow_except`) and run before changing the guard, the hooks, the installer or CLAUDE.md's git rules, and at least monthly; a fast core stays in the standing gate. The gate on merged main after the split: 12806 passed, 0 failed, 0 skipped, 482 deselected, 1547 s (the deselected count rose from 133 to 482, so 349 slow tests moved out, matching the ticket's 349). That is a worktree figure with a builder running verifies in parallel, not the TEST_GOVERNANCE baseline.

## Alternatives considered

- **Embed rule ids and metadata in CLAUDE.md.** Rejected: costs bytes in the always-loaded file, and position-based ids move on every insertion.
- **Infer enforcement by matching test names or text to rules.** Rejected: a heuristic column reads as coverage; trace markers make the claim explicit and checkable for existence.
- **Hand-maintained corpus.** Rejected: it drifts from CLAUDE.md the day a rule is edited; generation plus a freshness test makes drift a red gate.
- **Fold the whole extra suite into the standing gate.** The commit-protection tests alone were estimated at about 25 minutes added to the gate (ADR-043); the tier split is the answer. Sources disagree on the slow tier's cost: TEST_GOVERNANCE says about 45 minutes, the #1690 ticket says about 35 minutes for 349 tests, ADR-043 says about 25 minutes added to the gate before the split. These were measured at different times and under different load; none is a controlled measurement.
- **A rules-shadow reviewer agent as the commit gate.** Not built as a gate. Planned as an ADVISORY pilot (diff versus corpus), to be proven on 3 past diffs plus planted violations, 3 repeats, with a false-positive rate, before anyone relies on it; extends author-is-not-verifier. Not built.
- **Skills audit.** The suggestion's second claim (skills are context files) is applied as: keep the three agents and the sprint and gate skills; measure the plugin skill-listing cost, then decide on disabling unused plugin skill sets. The measurement and decision are pending (#1690 comment 3889).

## Consequences

- A rule edited in CLAUDE.md fails the corpus test until the generator is re-run and its diff read.
- A rule that something enforces can now be traced to the file that says so; a rule nobody enforces appears in the gap list, which the as-built guide (#1687) reuses.
- The slow tier must be run deliberately; a change to the guard, hooks or installer that skips it is a process lapse the gate does not catch.
- The marker is trust in the author of the enforcing file. Three rules still read `none` although partial tests exist (review finding N11, open; the review record is on the unmerged install-hardening branch).

## Residuals and known gaps

- **Install-step hardening, in progress, not merged** (branch `feat/1690-install-hardening`): hooks copied from main into the git common dir so a branch switch cannot disable or break them (R3), scope read from an identity recorded at install and not from CLAUDE.md content or the HEAD of an orphan branch (R1, R2), the refusal message and a text-guard refusal of plain merge, `--ff-only`, pull and cherry-pick on main before git touches files (R4), `--check` failing when the hooks differ from main, a live ceremony proof. Until it merges, ADR-043's description of the shims governs, and that branch also updates ADR-043 and its explainer.
- **The native hooks are inert until installed** (ADR-043); the text guard is active in sessions of this repository once the branch is checked out and is best effort.
- **Rules-review pilot and skills-audit decision: not built.** Gate baseline refresh: #1679.
- Which of the 142 gaps to close first is not decided.

## Re-visit triggers

A rule edited in CLAUDE.md that the generator cannot parse (the extractor raises); the pilot's result and false-positive rate once it exists; the install-hardening merge (ADR-043 is amended there). The ticket names no other trigger.
