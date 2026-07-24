---
title: Governance Documentation Style Authority
status: living
area: governance
---

# Governance Documentation Style Authority

> **Acronyms on first use.** ADR = Architecture Decision Record. DEC = Decision
> Register entry. LA = Lead Architect. PA = Policy Agent. AO = Assistant
> Orchestrator. OWASP-LLM = Open Worldwide Application Security Project, Large
> Language Model Top-10 risk taxonomy. AIGP = Artificial-Intelligence Governance
> Professional (the certification the documented journey supports). SDV = Strategic
> Design Vision. EA = Execution Agent (a Sprint-9 authoring role).

*Plain summary: the house style every document in `docs/governance/` follows — the
six-part doc template, the ≥ 150-substantive-line floor, how sources are anchored so a
future reader can re-verify a claim, the five reader personas, the frontmatter each doc
carries, the Markdown and filename conventions, and what does not belong in this
directory. It records the conventions the existing governance docs already follow; it
invents none.*

## What this document is

`docs/governance/README.md` names this file as the **style authority** for the
directory, and its Audience Taxonomy Matrix cites `STYLE.md §Audience Taxonomy` as the
source of the five reader personas. This file is that authority: it is the checklist a
future agent reads **before authoring a new governance doc**, and the contract an
adversarial reviewer checks a governance doc **against**.

It is **descriptive, not aspirational.** Every rule below is one the merged docs in this
directory already keep — `weight-integrity.md`, `credential-lifecycle.md`,
`rule-engine.md`, `configuration-management.md`, and their siblings are the worked
examples. Where two docs diverge on a point, the rule states the convergent practice and
names the allowed variation rather than legislating a new one. When a genuinely new
convention is needed, add it here **in the same change** that first uses it, the way
`doc-lifecycle.md` established the frontmatter rule alongside its own frontmatter.

This document is not a domain doc. Like the README, it **adapts** the template below
(§Doc Template) rather than carrying every section — see the index-and-meta-doc
allowance in that section. In particular it carries no `## Audience` section of its own;
its sole reader persona is stated in §Audience Taxonomy.

## Doc Template

A governance **domain doc** — one that owns a single decision surface (a wire-protocol
contract, a fail-closed boundary, a configuration schema, a runtime invariant) — is
built from six parts, in this order:

1. **Audience** — a `## Audience` section that opens with **Primary**: (the one persona
   the doc is written for, almost always the auditor — see §Voice and Framing) and
   **Secondary**: (the other personas that read it and the section each reads). This
   section is what the README's Audience Taxonomy Matrix is mechanically built from, so
   it must name personas using the exact labels in §Audience Taxonomy.
2. **Prerequisites** — the ADRs, DECs, and peer governance docs a reader must already
   understand, each as a relative link with a one-line statement of what it contributes.
   This is where the doc declares the decision records it binds to.
3. **Source References** — a table (`| Artifact | Path | Notes |`) mapping each governed
   claim to the production file and the specific symbols that implement it. This table is
   the doc's spine: it is what lets a developer find the code a change must preserve.
4. **Governance Content** — the substance, as numbered `### N. <title>` subsections. This
   is where the contract, the mechanism, the coverage, and the failure behavior live.
5. **Recovery** — the failure-fingerprint behavior, the operator-visible symptoms, and
   the sanctioned recovery / rollback paths. It may be a standalone `## Recovery`-style
   section or, as in `weight-integrity.md` (§5 divergence + §6 provisioning) and
   `credential-lifecycle.md` (§8 operational runbooks), one or more numbered Governance
   Content subsections. Present as a distinct surface either way — never omitted for a
   doc whose subject can fail.
6. **Open Questions** — an `## Open Questions` section naming the honest residual gaps,
   the unpublished measurements, and the LA capability calls the doc surfaces but does
   not decide. Empty-only when the surface genuinely has none; that is rare.

A doc closes with a **source-verification footer** — a `## Verified against` list (as in
`weight-integrity.md`) or a `## Cross-reference index` table (as in
`credential-lifecycle.md`) — enumerating every anchor the author actually checked. See
§Source Anchoring for what that footer is for.

**Index and meta-doc allowance.** A doc that is a synthesis index (`README.md`) or a
style/meta authority (this file) **adapts** the template: it replaces Source References /
Governance Content / Recovery with its own organizing sections (an inventory and an
audience matrix for the README; the rule sections for this file) and carries no
`## Audience` section, because it defines or catalogues audiences rather than serving
one. An adapting doc says so explicitly, as the README's Style Authority section does.

## Line-Count Floor

A domain doc carries **≥ 150 substantive lines** (non-blank, non-comment). The floor is
a proxy for completeness, not padding: a governance surface worth a dedicated doc has
enough contract, coverage, failure behavior, and residual-gap detail to clear 150 lines
without filler. Every current domain doc clears it comfortably — the README itself lands
at ~290 substantive lines.

The floor is a target for a domain doc, not for every file: a short pointer, a template,
or a stub is exempt by nature. If a domain doc cannot reach the floor honestly, that is a
signal its surface is too thin to own a doc and should fold into a sibling — not a signal
to pad it. Measure with `grep -cvE '^$|^<!--' <file>`, the same command the Sprint-9
authoring gate used.

## Source Anchoring

The purpose of anchoring is **re-verifiability**: a future reader must be able to open the
cited source and confirm the doc's claim still holds. Two rules follow.

- **Prefer a path plus a section header or symbol name over a bare line range.** A line
  range (`entrypoint.py:924-938`) is precise but *fragile* — it rots the moment the file
  is edited above it. Anchor to the durable handle first (the function name, the config
  key, the ADR section), and use line ranges as the *secondary*, refreshable locator
  gathered in the closing `## Verified against` footer. The footer is explicitly the
  place where line-range drift is expected and re-checked, so the body stays readable and
  the precise anchors stay auditable.
- **Handle ADR absence explicitly.** When a governed claim has **no** backing ADR, do not
  leave it unanchored and do not invent one. Anchor it to the dated LA decision plus the
  `docs/DECISION_REGISTER.md` row that records it (as `weight-integrity.md` §7 anchors the
  2026-07-15 hardware-trust decline). "No ADR exists for this; the decision is the dated
  LA call in the register" is itself a valid, honest anchor — a silent gap is not.

Never cite a claim you did not check. The `## Verified against` footer is a statement that
the author opened each listed source; it is the doc's integrity guarantee, and an
externally-cited SHA or line range must be verified against file history before it ships.

## Audience Taxonomy

Every governance doc is written for a subset of **five reader personas**. These are the
canonical labels; a doc's `## Audience` section must use them verbatim so the README's
matrix can be built mechanically (near-synonyms such as "operator (LA)" map back to the
base persona and are recorded in the ledger, not spelled as new personas).

- **Operator** — runs BlarAI day-to-day. Reads for behavior, observable symptoms, and the
  small set of self-service remediations governance sanctions (rolling back a model,
  restarting a service, reading an evidence JSON).
- **Developer** — extends or refactors a service module. Reads for the invariants,
  contracts, and source anchors a code change must preserve before it can merge.
- **Auditor** — reviews the security boundary or the decision-record (ADR / DEC) anchor
  behind a fail-closed surface. Reads for the Red Team issue closure, the OWASP-LLM
  Top-10 mapping, or the audit-trail contract. This is the default **Primary** persona.
- **Incident responder** — opens an investigation when BlarAI misbehaves in a way an
  operator cannot self-remediate. Reads for the failure-fingerprint catalogue, the
  recovery procedures, and the rollback paths.
- **Future agent** — a Configuration Agent, Sprint Auditor, EA, Co-Lead Architect, or a
  successor model resuming after weeks of silence. Reads to learn the contract before
  touching any fleet-shared file or before authoring a new governance doc.

**STYLE.md's own reader is the future agent** — it is this file's primary consumer,
otherwise rare. That is why the README's matrix marks STYLE.md under **Future Agent**
only, and why this file carries its persona statement here in the taxonomy rather than in
a `## Audience` section it does not have.

## Lifecycle Frontmatter

Every governed doc authored from now carries the lifecycle frontmatter defined by
[doc-lifecycle.md](doc-lifecycle.md) as the very first bytes of the file — flat scalars,
no nested maps:

```yaml
---
title: Human-Readable Title
status: living            # living | reference | draft | superseded | archived
area: governance
---
```

`title`, `status`, and `area` are required and non-empty; `superseded_by:` is present
**iff** `status: superseded`. For a doc in this directory `area` is `governance` and a
current, canonical doc is `status: living`. The `tools/doc_lint/` checker enforces this
(advisory today, gate-eligible once the living set is back-filled). This file, like
`doc-lifecycle.md` and `credential-lifecycle.md`, dogfoods the convention: a style
authority that failed its own lint would be the first thing to distrust.

Adoption is incremental — some older docs in this directory (e.g. `weight-integrity.md`)
predate the frontmatter rule and carry the `> **Acronyms on first use.**` header without
it yet; that back-fill is `doc-lifecycle.md`'s serialized workstream, not a defect to fix
opportunistically inside an unrelated change.

## Markdown Conventions

- **Header depths.** One `#` H1 title per file. Major sections are `##` H2. Numbered
  Governance Content subsections are `### N. <title>` H3, and deeper structure is `####`
  H4 (as in `credential-lifecycle.md` §3.1–§3.4). Do not skip a level.
- **Code-fence language tags.** Every fenced block declares its language — ```json for a
  manifest excerpt, ```yaml for frontmatter, ```bash for a command. An untagged fence is
  a lint smell; the tag is what makes an excerpt render and grep correctly.
- **Bold-for-verdict.** The load-bearing conclusion of a paragraph is **bold** — the
  fail-closed guarantee, the coverage verdict, the one sentence a skimming auditor must
  not miss. Bold marks the verdict, not for emphasis-as-decoration.
- **Status labels.** A mechanism's live-ness is stated with an explicit, bold label:
  **LIVE** (wired into a real path and exercised), **DESIGN-INTENT** (code present but
  reached by nothing live), **DECLINED** (an ambition the LA has ruled out), or
  **DEFERRED** (postponed behind a tracked ticket). `credential-lifecycle.md` labels every
  §-mechanism this way; never let a reader guess whether a described control actually
  runs.
- **Acronyms on first use.** Open the doc with a `> **Acronyms on first use.**` blockquote
  expanding every acronym the doc uses (both current docs do this). The LA is
  non-technical and the record feeds an AIGP portfolio; an unexpanded acronym is a defect.
- **No emoji.** Governance docs, like the journal, carry no emoji — anywhere.
- **Relative cross-references.** Link a sibling doc by bare filename
  (`[ipc-protocol.md](ipc-protocol.md)`) and the wider repo with `../`
  (`../adrs/`, `../../CLAUDE.md`). A link that resolves from the wrong directory is a dead
  link; verify each resolves from `docs/governance/`.

## Voice and Framing

- **Lead with the outcome.** Open a doc, a section, and most paragraphs with the
  conclusion — what the mechanism guarantees, what the verdict is — then the mechanism.
  The reader who stops after one sentence should still have the load-bearing fact.
- **Auditor-first.** The default Primary persona is the auditor; write the substance for
  the reader verifying a security boundary, and let the operator / developer / incident
  responder read the sections that serve them. This is why the mechanism, its coverage,
  and its *declined* scope get equal, explicit treatment.
- **Plain language, expanded acronyms.** The record is read by the non-technical LA and
  feeds a governance-professional portfolio. Prefer plain phrasing; spell out every
  acronym on first use (§Markdown Conventions).
- **No "prototype" / "nearly done" framing.** BlarAI is a decades-horizon system; its
  public framing is a "personal research project" / "long-term local AI system", never a
  "prototype", and no doc frames the work as "nearly complete". State what is LIVE, what
  is DESIGN-INTENT, and what is DECLINED — maturity is described by those labels, not by a
  progress-toward-done narrative.
- **Failures stay in.** A governance doc that hides the failure path is worse than none.
  Document the stale docstring, the unpublished measurement, the coverage gap — honestly
  and in place — the way `weight-integrity.md` flags its own stale "Pluton-sealed"
  language and unmeasured `integrity_ms`. Sanitized records do not compound.
- **No commendations.** No praise or self-congratulation sections; the record states what
  is, not how well it was done.

## Filename Conventions

- **lower-kebab-case.** `weight-integrity.md`, `credential-lifecycle.md`,
  `rule-engine.md`. Words joined by single hyphens; no camelCase, no snake_case, no
  spaces.
- **No `_GOVERNANCE` suffix.** The directory *is* `docs/governance/`; a
  `WEIGHT_INTEGRITY_GOVERNANCE.md`-style suffix is redundant and is the exact
  upper-snake-case pattern this directory's layout convention (inherited from the
  Sprint-9 SDV §5.1 plan) replaced. The filename names the surface, not its category.
- **The current file in a versioned family carries no version suffix.** Per
  [doc-lifecycle.md](doc-lifecycle.md), exactly one live file exists with no `_vN`
  suffix; superseded `_vN` siblings move to `../archive/<year>/…`.

## Out of Scope

`docs/governance/` holds documents that own a governed decision surface. The following do
**not** belong here and have their own homes:

- **Personal-LA runbooks** — hands-on operator recovery procedures live in
  `../runbooks/`; a governance doc *references* the runbook and states the contract, but
  the step-by-step operator ceremony is a runbook.
- **ADR proposals** — a decision under debate is a `DRAFT_`-prefixed ADR in `../adrs/`,
  indexed by `../DECISION_REGISTER.md`. A governance doc records the contract that a
  *locked* decision produced; it is not where a decision is argued.
- **Conversational design notes** — exploratory back-and-forth, options-weighing, and
  session narrative belong in the journal (`../../BUILD_JOURNAL.md`) or a handoff brief,
  not in a governance doc. A governance doc states the settled contract in the
  descriptive register, with no first-person deliberation.

When unsure whether a document belongs here, apply the test: *does it state the standing
contract of a governed surface a future reader must honor before changing code?* If yes,
it is a governance doc; if it is a procedure, a proposal, or a narrative, it lives in the
directory for that kind.

## Source References

- [README.md](README.md) — the governance index that names this file as the style
  authority and whose Audience Taxonomy Matrix consumes §Audience Taxonomy. The
  index-and-meta-doc allowance in §Doc Template is the rule the README's Style Authority
  section invokes.
- [doc-lifecycle.md](doc-lifecycle.md) — the frontmatter and lifecycle-state convention
  that §Lifecycle Frontmatter points to; the authority for `title` / `status` / `area` /
  `superseded_by` and the top-level-budget rule.
- `tools/doc_lint/` — the checker that enforces the frontmatter convention this file
  requires (advisory today, per `doc-lifecycle.md` §Enforcement).
- [weight-integrity.md](weight-integrity.md), [credential-lifecycle.md](credential-lifecycle.md),
  [rule-engine.md](rule-engine.md), [configuration-management.md](configuration-management.md)
  — the worked examples every rule above is drawn from (template order, LIVE/DECLINED
  labeling, `path:line` anchoring, the source-verification footer).
- `../../CLAUDE.md` `<security_by_design>` and `<journal_discipline>` — the project-level
  posture (fail-closed, no-emoji, failures-stay-in, no-commendations) the Voice and
  Framing rules inherit and apply to documentation.

## Verified against

- `docs/governance/README.md` — Style Authority section (this file named as authority;
  the seven capabilities it promises STYLE.md defines: Doc Template, Line-Count Floor,
  Source Anchoring, Audience Taxonomy, Markdown Conventions, Filename Conventions, Out of
  Scope), the "How to Read This Directory" cross-reference rules, and the Audience
  Taxonomy Matrix note that STYLE.md carries no `## Audience` section and is Future-Agent
  only.
- `docs/governance/doc-lifecycle.md` — required frontmatter, the five lifecycle states,
  the flat-scalar rule, the versioned-family rule.
- `docs/governance/weight-integrity.md` — no-frontmatter-yet + acronyms-blockquote,
  auditor-first Audience, Source References table, numbered Governance Content, §5–§6
  recovery/provisioning, Open Questions, `## Verified against` footer, `path:line`
  anchoring, DECLINED-scope labeling.
- `docs/governance/credential-lifecycle.md` — living frontmatter, `## Status` LIVE
  labeling, LIVE / DESIGN-INTENT / DECLINED / DEFERRED per §, `## Cross-reference index`
  footer, `####` depth usage.
- `tools/doc_lint/lint.py` — the frontmatter fields, canonical statuses, and
  `superseded_by` rule enforced (`REQUIRED_FIELDS`, `CANONICAL_STATUSES`,
  `STATUS_ALIASES`).
- `docs/ledger/20260424_050528_sprint9_ea5_governance-landing-page.md` — the LINE-FLOOR
  (≥ 150) and MATRIX-SHAPE authoring gates, and the recorded matrix-construction rule
  that STYLE.md is Future-Agent-only because it "does not have its own `## Audience`
  section" but "identifies 'future agent' as STYLE.md's primary consumer".
