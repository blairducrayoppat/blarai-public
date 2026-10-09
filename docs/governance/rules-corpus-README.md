# Rules corpus

`rules-corpus.yaml` is a machine-readable index of the rules in `CLAUDE.md` and the
path-scoped doctrine files in `.claude/rules/` (#1700), one record per atomic rule, with the
enforcement that backs each rule. It is **generated**. Those files are the only authored
source; never hand-edit the corpus or `rules-gaps.md`. The generator costs the doctrine no
bytes (no ids or metadata live in it). Each rules file holds one section in `CLAUDE.md`'s tag
register and is spliced in before the closing root tag, so a rule keeps its id when it moves
between files; the record's `source` says which file holds it.

## Regenerate

    python scripts/extract_rules_corpus.py            # rewrite both outputs
    python scripts/extract_rules_corpus.py --check    # exit 1 if either is stale

`tests/security/test_rules_corpus.py` (in the standing gate) fails when the committed files
differ from a fresh extraction. The extractor refuses (exit 2, writes nothing) on an unbalanced
or unclassified tag, an unparseable line in a rule section, a duplicate id, or an enforcement
entry that names a rule id that does not exist. After regenerating, READ the diff of
`rules-corpus.yaml`: a changed `enforcement` column is a claim to review, not an approval step.

## What is a rule

Every list item and prose line inside a rule-bearing section. In the fact and pointer sections
(`authority`, `blarai_identity`, `host_environment`, `stack`, `repo_constellation`,
`live_state_pointers`, `user_operator/facts`, `identity_split/facts`) an item is a rule only if it
carries an imperative marker (never, always, must, do not, only, require, forbidden, keep,
`USE`); the rest are facts. `status_snapshot` is volatile dated state and is never parsed.
Current counts: 19 fact-section items included as rules, 31 fact items excluded, 14 snapshot
lines skipped (a test keeps these numbers true). The marker test is a heuristic: a few
included items are facts that happen to say "never".

## Record schema

- `id`: `<tag.path>.<name>`, the name being the rule's own leading words (principle FAIL-CLOSED
  is `security_by_design.principles.fail-closed`). Position never enters the id, so inserting
  a rule moves no other id or enforcement. A collision raises.
- `anchor`: `<tag/path>#<ordinal>`, the location in the spliced doctrine.
- `source`: the file that holds the rule, `CLAUDE.md` or `.claude/rules/<name>.md`.
- `text`, `text_sha256`: verbatim text and its SHA-256.
- `why_pointer`: `agent-doctrine-evidence.md#<title>` only where that file has an entry.
- `scope`: any of `git tests journal vikunja security perf process`, inferred from the section
  and keywords. Empty means always. Over-inclusion is intended.
- `enforcement`: list of `{kind, ref, note?}`; kind is `test hook verifier reviewer gate none`.
- `severity`: `critical` (critical_rules, git absolute_rules), `high` (security principles), else `normal`.
- `owner`: `LA` for `decision_boundary/his_decisions`, else `session`.

## What the enforcement column means

It means **a trace marker or a curated entry exists**, nothing more. An enforcing test, script or
hook declares `enforces-rule: <rule id> [-- note]` in a comment or docstring; things that cannot
carry a marker (the user-level hook, reviewer agents) are entries in `rules-enforcement.yaml`.
The column is built only from those two sources. The marker is the author's claim that the file
enforces the rule (the `note` says how much of it); it is not a coverage measurement.
`test_rules_corpus.py` checks that every marker and curated entry names an existing rule id (a
rename breaks loudly), that every curated ref exists, and that the column equals an independent
re-scan of the repo.

The commit-protection controls behind the two `git_discipline` markers are explained in
`commit-protection-explained.md` (plain language) and `git-rules-guard.md` (technical); the decision is ADR-043.

## Gap list

`rules-gaps.md`: rules whose enforcement is `none` or reviewer-only, sorted by severity. Its
suggestion column is hand-written for a few rules and reads "none proposed" otherwise.

## How a reviewer uses it (proposed, not yet proven on a real diff)

1. Take the diff. 2. Select records whose `scope` matches the changed paths or tools (empty
scope always applies). 3. For each in-scope record, report VIOLATED / NOT-VIOLATED / N-A with a
line cite and the record `id`. 4. A non-`none` enforcement entry means a marker exists, for the
part its `note` names; the reviewer still owns the rest. Findings go to a disposition record.
