# doc_lint — documentation frontmatter lint

Advisory checker for the BlarAI documentation lifecycle convention. It reports
Markdown documents that are missing the required lifecycle frontmatter.

- **Convention (the rules):** [`docs/governance/doc-lifecycle.md`](../../docs/governance/doc-lifecycle.md)
- **Ticket:** Vikunja #267 (doc-sprawl consolidation)

## What it checks

Each governed doc must open with flat YAML frontmatter carrying:

- `title` — required, non-empty
- `status` — one of `living | reference | draft | superseded | archived` (alias `active` = `living`)
- `area` — required, non-empty owning domain
- `superseded_by` — required **iff** `status: superseded`; a violation on any other status

It additionally *warns* (does not fail) when a `superseded_by:` target does not resolve
on disk.

## Usage

```bash
python -m tools.doc_lint                 # scan top-level docs/*.md (report mode)
python -m tools.doc_lint docs services   # scan explicit paths
python -m tools.doc_lint --json docs     # machine-readable report
python -m tools.doc_lint --recursive docs # descend (skips node_modules/_validate/.git)
python -m tools.doc_lint --strict docs   # warnings also fail the run
```

Exit code is `0` on pass (no violations; under `--strict`, no warnings either) and `1`
otherwise, so the tool is gate-ready. Directory scans are **non-recursive by default**,
so a `docs` scan never wanders into the ~19k gitignored `node_modules` files under
`docs/security/**/_validate/`.

## Status: advisory, not gated

This tool is deliberately **not** wired into the standing test gate yet. As of its
authoring, zero documents carry lifecycle frontmatter, so gating would fail the whole
tree. It becomes gate-eligible after the living top-level set is back-filled with
frontmatter (see the convention's Adoption section). Until then it runs on demand.

## Tests

```bash
python -m pytest tools/doc_lint -q
```

The tests use temporary fixture files only — they touch no real repo documents.
