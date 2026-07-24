---
title: Documentation Lifecycle Convention
status: living
area: governance
---

# Documentation Lifecycle Convention

*Plain summary: how a BlarAI document is born, marked, and retired — the four-part
frontmatter every governed doc carries, the five lifecycle states it can be in, and
the rule that keeps the top level of `docs/` to the small set of documents that are
actually live.*

This document is the convention half of Vikunja **#267** (doc-sprawl
consolidation). It defines the lifecycle a document moves through and the metadata
that records where it is in that lifecycle. It is **descriptive of the target
convention and additive** — establishing it moved, renamed, or deleted nothing. The
one-time reorganization that stamps the existing tree (archiving the ~127 historical
top-level files, back-filling frontmatter on the living set) is #267's separate,
serialized, Lead-Architect-gated workstream — see [§ Adoption](#adoption-this-is-newly-established-not-yet-retroactively-applied).

## Audience

- **Future agent** — the primary reader. Before authoring a new doc under `docs/`,
  or before deciding whether a doc you are reading is current guidance, read this
  convention. It is how you tell a live document from a historical artifact without
  guessing from the filename.
- **Developer** — extends the enforcement tool (`tools/doc_lint/`) or wires it into
  a gate once the living set is compliant.
- **Operator / Lead Architect** — decides *when* a document graduates between states
  (a living doc becoming reference, a superseded doc being archived) and owns the
  serialized archive-move workstream. The states are a vocabulary for those calls;
  the calls themselves stay with the LA.

## Why this exists

Top-level `docs/` accumulated 183 tracked files at #267's filing (2026-04-24) and
sat at ~156 when this convention was authored. Most of that mass is *historical
working artifact* — Phase-5 `Task4.*` execution prompts, `P5_*` agent-initiation
files, closed upstream-contribution drafts — kept for the decades-horizon portfolio
record but **not live guidance**. Nothing in a filename reliably told a reading agent
"this is current" versus "this is a April-2026 scaffold." Agents grep, find a stale
version, and act on it. This convention gives every governed doc an explicit,
greppable lifecycle marker so that failure mode closes structurally rather than by
vigilance.

## The five lifecycle states

Every governed document is in exactly one state. The states below reconcile the two
vocabularies the ticket history used (`living | reference | archived` and
`active | superseded | archived | draft`) into one canonical set. `active` is
accepted as a synonym of `living`; prefer `living`.

| State | Meaning | Lives at | Still authoritative? | Still edited? |
|-------|---------|----------|----------------------|---------------|
| `living` | The current, canonical document for its subject. The default for anything you are actively maintaining. | Top-level `docs/` or its domain subdir (`docs/governance/`, `docs/runbooks/`, …). | Yes | Yes |
| `reference` | A closed, frozen record that is still correct and still cited, but no longer edited. Point-in-time truth. | Where it already lives (usually top-level or a subdir). | Yes, for the period it covers | No — frozen |
| `draft` | In progress; not yet authoritative. Do not act on it as settled guidance. | Top-level or subdir, conventionally with a `DRAFT_` filename prefix. | No | Yes |
| `superseded` | Replaced by a newer document. Carries `superseded_by:` pointing at the replacement. | `docs/archive/<year>/…` once the move batch runs. | No — read the successor | No |
| `archived` | Historical artifact retained for the portfolio/audit record. Not live guidance. | `docs/archive/<year>/<cluster>/`. | No | No |

`reference` vs `archived` is the subtle pair: a **reference** doc is still *true and
cited* (e.g. a frozen milestone ledger you still quote); an **archived** doc is a
*retired working artifact* you keep only for provenance. When unsure, `reference` is
the more conservative mark (it keeps the doc discoverable as valid); `archived` is
for the historical mass that no reader should treat as current.

## Required frontmatter

Governed documents carry YAML frontmatter as the very first bytes of the file — a
`---` line, the fields, a closing `---` line — before the `# Title` heading.
Frontmatter is **flat scalars only** (no nested maps or lists); this keeps it
trivially parseable by tooling and by eye.

```yaml
---
title: Human-Readable Title
status: living            # living | reference | draft | superseded | archived
area: governance          # the owning domain (see below)
superseded_by: ../archive/2026/…/old-thing.md   # REQUIRED iff status: superseded
owner: fleet-hygiene      # OPTIONAL — the steward; defaults to the area's owner
---
```

Field rules:

- **`title`** — required, non-empty. The human title; may differ from the filename.
- **`status`** — required; one of the five canonical states above (or the alias
  `active` = `living`).
- **`area`** — required, non-empty. The owning domain — conventionally one of:
  `governance`, `architecture`, `security`, `performance`, `runbooks`, `research`,
  `testing`, `operations`, `upstream`, `fleet`, `portfolio`. The `area` is what makes
  ownership legible without naming an individual (this is an agent-run repository;
  the steward is a role/domain, not a person).
- **`superseded_by`** — required **if and only if** `status: superseded`; a
  repo-relative path to the replacement. Present on any other status is a violation
  (it means the status is wrong). The lint additionally *warns* if the target path
  does not resolve on disk.
- **`owner`** — optional. A named steward when one is useful; otherwise the `area`
  implies it.

### This document dogfoods the convention

The frontmatter at the top of this file (`title` / `status: living` /
`area: governance`) is itself a minimal-compliant example. A doc-lifecycle convention
that did not carry its own frontmatter would be the first thing to distrust.

## Where each state lives — and the top-level budget

The load-bearing spatial rule: **top-level `docs/` holds only `living` (and a small
number of `reference`) documents.** Everything `superseded` or `archived` lives under
`docs/archive/<year>/…`. `draft` documents may sit at top level or in a subdir,
conventionally `DRAFT_`-prefixed.

That rule has a number attached to it. The genuinely-live top-level set is roughly
**fifteen documents** — the `CLAUDE.md` `<live_state_pointers>` surfaces
(`DECISION_REGISTER.md`, `TEST_GOVERNANCE.md`, `INDEX.md`,
…) plus a few standalone studies. They are enumerated in
[`docs/INDEX.md` §2](../INDEX.md). When top-level `docs/` grows well past that, the
excess is almost always historical artifact that should be `archived`, not new living
guidance. `docs/INDEX.md` is the navigation map of the living set; **this file is the
rule that keeps that set small.** The two are companions: INDEX says *where things
are*, this convention says *what earns a place at the top level*.

## Versioned families

When a document goes through revisions that each supersede the last
(`…_v1.xml`, `…_v2.xml`, `…_v3.xml`):

- Exactly **one** live file exists at the top level, and it carries **no version
  suffix** — it is simply the current document, `status: living`.
- Every older `_vN` sibling is `status: superseded`, carries `superseded_by:` pointing
  at the current file, and moves to `docs/archive/<year>/…` in the archive workstream.

A genuinely *additive* series (each part augments rather than replaces its
predecessor — e.g. a base study plus dated addenda) is not a versioned family; each
part is its own `living`/`reference` doc. A one-line `superseded_by:`/`title` header
resolving the relationship is the tell for which case you are in.

## How this harmonizes with lifecycle signals already in use

This convention does not overwrite mechanisms the repo already relies on; it
generalizes them and leaves the established ones authoritative in their own areas:

- **Architecture Decision Records (`docs/adrs/`)** already carry a body-level
  `**Status:** ACCEPTED | DRAFT | SUPERSEDED` field and a `DRAFT_` filename prefix,
  and are indexed by `DECISION_REGISTER.md`. ADRs keep that established mechanism and
  are **out of scope for the frontmatter lint** — their lifecycle is governed by their
  own Status line and the register, which pre-date and outrank this file for that
  directory.
- **The `DRAFT_` filename prefix** (e.g. `DRAFT_cert_remint_race_durable_fix.md`) is
  the existing signal for `status: draft`; the frontmatter makes it machine-checkable
  without dropping the prefix.
- **`docs/archive/`** already exists (holding `platform_separation/`) and is the
  canonical destination for `superseded` / `archived` documents. This convention adds
  the `<year>/<cluster>/` layout beneath it.
- **Frozen-record prose** — a doc that says "FROZEN at Entry 52" or "Frozen Phase-4
  closed record" (e.g. `POST_OPERATIONAL_MATURATION_LEDGER.md`,
  `GAP_TO_OPERATIONAL_REPORT.md`) — is exactly `status: reference`.
- **Journal fragments (`docs/journal_fragments/`)** are a deliberately ephemeral
  staging inbox, folded into `BUILD_JOURNAL.md` and then deleted; they use dated
  `###` headers, not frontmatter, and are **exempt** from this convention.

## Enforcement — the frontmatter lint

`tools/doc_lint/` is the checker. It parses the leading frontmatter of the documents
it is pointed at and reports every file that is missing frontmatter, missing a
required field, carrying an out-of-vocabulary `status`, or misusing `superseded_by`.

- **Advisory today, not gated.** It is deliberately **not** wired into the standing
  test gate. Right now *zero* documents carry this frontmatter, so gating would fail
  the entire tree. The tool exits non-zero on violations precisely so it *can* be
  gated later — after the living set is back-filled — but until then it runs on
  demand and reports.
- **Default scope is the top level only.** Pointed at a directory it scans that
  directory's direct `*.md` children and does **not** recurse, so it never wanders
  into the ~19,000 gitignored `node_modules` files under
  `docs/security/**/_validate/` that balloon any recursive scan of `docs/`.
- Usage: `python -m tools.doc_lint docs` (report), `python -m tools.doc_lint --json docs`
  (machine-readable), `python -m tools.doc_lint --strict …` (promote warnings to
  violations). See `tools/doc_lint/README.md`.

## Adoption — this is newly established, not yet retroactively applied

Honest current state: as of authoring, **no document in the tree carries this
frontmatter yet.** This file establishes the convention; adoption is incremental and
is *not* a single retroactive rewrite:

1. **New documents** authored from now carry compliant frontmatter (this file is the
   first).
2. **The archive move batches** (#267's serialized, quiet-tree workstream) stamp
   `status: archived` + `area:` on each historical file as they move it into
   `docs/archive/<year>/…` — frontmatter arrives *with* the move, not as a separate
   churn pass.
3. **A living-set back-fill** adds frontmatter to the ~15 top-level living documents
   in one later serial pass, at which point the lint becomes gate-eligible.

Sequencing rationale: the archive batches and the back-fill both rewrite existing
top-level files and so must run serially on a quiet tree (one commit per batch, gate
re-run between) to avoid colliding with other sessions' work. This convention doc and
its lint are the *additive* half that is safe to land in parallel first — which is
why they ship ahead of the moves.

## Source References

- `docs/INDEX.md` — the navigation map of the living top-level set (#267 additive
  slice, merged `6bc43941`). This convention is its companion rule.
- `tools/doc_lint/` — the enforcement tool defined by this convention.
- `CLAUDE.md` `<live_state_pointers>` — the enumeration of the load-bearing living
  top-level documents.
- Vikunja **#267** — the doc-sprawl consolidation ticket; comment 1989 (research
  decomposition) and comment 1999 (LA archive-not-delete decision) scope the
  serialized move workstream this convention precedes.

## Open Questions / Deferred Items

- **Gate wiring** is deferred until the living-set back-fill (step 3 above) makes the
  top level compliant. Until then the lint is advisory by design.
- **`area` vocabulary** is a recommended, not closed, set. If a genuinely new domain
  appears, extend the list here in the same change that introduces it rather than
  inventing an unlisted value silently.
- **XML documents.** The lint targets Markdown. The large top-level `.xml` clusters
  are historical agent-orchestration scaffolding headed for `archived`; YAML
  frontmatter in XML is awkward, so their lifecycle is recorded by their archive
  location rather than by in-file frontmatter. If a *living* XML doc ever needs a
  lifecycle marker, revisit this.
