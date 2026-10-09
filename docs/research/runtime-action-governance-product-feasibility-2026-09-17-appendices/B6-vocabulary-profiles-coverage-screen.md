# R6 — The action vocabulary, the profiles, the device scan, the approval model, the antivirus interaction model, and the coverage screen

Study: Vikunja #1549, runtime action governance for AI agents on Windows PCs. This report answers Q3, Q3a and Q4 of the brief.
Written 2026-09-17 (machine local time, EDT) on Windows 11 Pro 10.0.26200.
**Everything designed here is a hypothesis, marked [PROPOSED]. Nothing is built, nothing was installed, nothing left the machine.**

Grades used throughout: **MEASURED** = run on this machine during the study (this agent's own runs, or the study's P1/P3a/P3b probe reports, cited by file). **ARTEFACT** = read from a vendor's own shipped file on this disk (outranks vendor prose, but is not a run). **REPORTED** = read in documentation; source named with its date where the page shows one. **DERIVED** = my own reasoning from the above, labelled as mine.

Acronyms are expanded on first use: CAR (Canonical Action Representation), CAVA (Canonical Action Verification Architecture), ACS (Agent Control Standard / Specification), MCP (Model Context Protocol), TOML (Tom's Obvious Minimal Language, a plain-text configuration format), TPM (Trusted Platform Module), WFP (Windows Filtering Platform), ETW (Event Tracing for Windows), CFA (controlled folder access).

---

## Outcome first

**A single action vocabulary is workable, and its weakest point is not a corner case — it is the single most common event a coding agent produces.** The vocabulary below has ten fields. Nine of them can be filled exactly for most tool calls. The tenth, and the whole record with it, collapses to "unknown" for one tool: the shell. On this machine it was measured that Claude Code's `Bash` tool carries the entire command as one opaque string, and a real HTTPS fetch to example.com travelled inside `python -c "import urllib.request; …"` as an ordinary, allowed `Bash` call (P1 run c1). Nothing in the event said "network". A vocabulary that pretends to classify that string is lying; one that marks it `execute, unknown scope` is honest and then forces the profile to decide. **That decision — what a profile does with "unknown" — is the real design problem, and the answer is: ask or deny, never allow.**

Five things follow, and they shape everything below.

1. **The vocabulary needs an eleventh field nobody else has: how the record was derived.** CAVA, the Agent Control Standard and MCP's tool annotations all describe *what an action is*. None of them records *how sure the describer is*. Without that field, a governor cannot distinguish "this is a read" from "I guessed this is a read", and the coverage screen cannot be honest. I propose `derivation ∈ {declared, parsed, annotated, unknown}` as a first-class, hashed field.

2. **Don't try to parse the shell. Constrain the process instead.** A parser that resolves `python` to an allowlisted binary passes the measured c1 fetch. The correct answer for the developer profile is not a better parser, it is a second, independent lock on the process (network, credential store, path scope). **And on this machine that second lock is not available**: the per-process firewall block failed silently because Bitdefender owns the firewall rule categories (P3a §1, MEASURED). So the coverage screen must carry a row that says a seam is not owned by this product because another security product owns it — which is Q4's most important row and the one no competitor shows.

3. **The antivirus interaction model transfers almost completely on the quiet side and almost not at all on the loud side.** Every consumer suite studied has the same three devices — an automatic mode, a per-app exception list, and an event history — and all three map cleanly onto leases, per-agent per-path rules, and the receipt history. What does not transfer is the consequence of a wrong "allow": a quarantined file can be restored, and Windows Protection History gives the user "Quarantine threats or allow them on the device… Remove quarantined threats or restore them" (REPORTED). **An executed action has no restore. There is no quarantine for a sent e-mail or a charged card.** That asymmetry is the reason the interruption list below is short and strict.

4. **The honest default for an agent is "unknown", not "governed".** Two of three named coding agents fail open when the governor crashes (Claude Code MEASURED, Copilot CLI 1.0.3 ARTEFACT), and Claude Code's `--safe-mode` skipped the hook entirely with no trace (MEASURED). Neither failure is visible to the governor. The coverage screen therefore must be a live instrument driven by a per-adapter canary, not a static claim.

5. **The vocabulary must be borrowed, not invented, and the study bets on no company.** CAVA's core package is Apache-2.0 (LICENSE fetched today), the Agent Control Standard's code and schemas are Apache-2.0 with its documentation CC BY-SA 4.0 (repository README fetched today), and the Agent Hooks / Agent Control Specification text BlarAI already aligned to is MIT. The names below come from all three plus MCP's tool annotations; no field is original where a public one exists, and the design depends on none of their implementations.

---

# 1. Q3 — The canonical action vocabulary [PROPOSED]

## 1.1 The field set

Eleven fields. Every field is a label, an enum, a class, or a hash. **No field carries payload** — this is BlarAI's redaction rule (`acs-vocabulary-adoption-design-2026-09-16.md`, §19) carried over as a product commitment (R5, R10).

| # | Field | Type | Values | Notes |
|---|---|---|---|---|
| 1 | `actor` | object | `{kind: agent \| user \| unknown, agent_id, agent_version, session_id}` | `agent_id` is a stable local identity for the installed agent (e.g. `claude-code`), not a cloud identity. `user` is the Windows account's local identifier, never a name or e-mail. |
| 2 | `categories` | **set** of enum | `read`, `write`, `delete`, `execute`, `network-send`, `network-receive`, `credential-use`, `device-use`, `settings-change`, `purchase-or-payment`, `message-send`, `install`, **`unknown`** | A **set**, not a scalar, because one tool call is routinely two things: a web fetch is `network-send` + `network-receive`; an install is `network-receive` + `write` + `execute`. `unknown` is a legal value and is the honest answer for a shell command. |
| 3 | `systems_touched` | set of enum | filesystem path classes: `user-documents`, `project-tree`, `system`, `removable`, `cloud-synced`; plus `network`, `accounts`, `devices`, `other-apps`, `unknown` | Classes, never paths. The path itself lives in `target` and is hashed. `cloud-synced` is separate from `user-documents` because a change there propagates off the machine even when nothing "sends" anything. |
| 4 | `reversibility` | enum | `reversible`, `reversible-with-backup`, `irreversible`, `unknown` | `reversible-with-backup` is only claimable when the governor's own snapshot is on for that path class; otherwise the same action is `irreversible`. This is a property of the machine's configuration, not of the tool. |
| 5 | `destination` | object | `{class: local \| loopback \| lan \| internet \| unknown, host: <name or literal address or null>}` | `host` is the hostname when the adapter can see one, the literal address when it cannot, `null` when neither. Measured constraint: the network seam sees addresses, never hostnames (P3a, P3b seam 8) — so `host` is usually populated from the *tool argument*, not the network. |
| 6 | `data_class` | enum | `none`, `personal`, `credential`, `financial`, `unknown` | A *kind*, deliberately not a *grade*. See §1.2 on why this does not simply map onto BlarAI's `sensitivity`. |
| 7 | `target` | object | `{class: <from systems_touched>, display: <short, redacted>, full_hash: sha256}` | The concrete resource. `display` is what a person is shown (a folder name, a hostname, an account label); `full_hash` is the hash of the full value so an approval can bind to it without the receipt storing it. A list when a tool touches several (e.g. a multi-file edit). |
| 8 | `raw_tool` | string | verbatim vendor tool name | `Bash`, `WebFetch`, `mcp__vikunja__create_task`, `github-mcp-server/list_issues`. Kept unmodified so a receipt can be read back against the agent's own transcript. |
| 9 | `args_hash` | string | `sha256:` + hex | SHA-256 over the canonical (sorted-key, compact-separator) JSON of the arguments. This is BlarAI's `canonical_hash()` discipline, and it is what an approval binds to (§4). |
| 10 | **`derivation`** | enum | `declared`, `parsed`, `annotated`, `unknown` | **The field this study adds.** `declared` = the tool name alone determines the record (a `Read` is a read). `parsed` = an argument string was parsed to get here. `annotated` = an MCP server's own annotations supplied it, and those are untrusted. `unknown` = nothing determined it. |
| 11 | `adapter` | object | `{name, version, seam, intervention_point, host_posture}` | Which seam produced the record. `intervention_point` uses the ACS name (`pre_tool_call`). `host_posture` carries what the agent told us about itself — on Claude Code this is the measured `permission_mode` field, which is how a governor knows it is the only lock left. |

Derived identity: `action_id = sha256` over fields 1–10 with keys sorted and timestamps excluded, exactly as BlarAI's `CanonicalActionRepresentation.canonical_hash()` excludes `timestamp` and `request_id` (`shared/schemas/car.py:112`). Excluding the clock is deliberate and is BlarAI's existing, correct choice: a lease covering three searches cannot work under a timestamped identity.

**The two invariants the field set exists to serve.**

- **No field may be absent.** A record missing a field is not a record; it is `unknown` in that field, which is a value, and the profile must decide about it. BlarAI's CAR already enforces this shape (`is_complete()`, and `sensitivity` has no default "so no default prevents silent misclassification"). Carried over verbatim.
- **`derivation` may only ever tighten.** A `parsed` or `annotated` derivation may **add** categories, **narrow** reversibility toward irreversible, or **widen** `systems_touched`. It may never remove a category, never move `reversibility` toward reversible, and never turn `unknown` into `none`. This is ADR-041's rule ("any model-based judgment may only tighten a decision, never loosen it", brief R12) generalised from models to *any* inference, which is what a command parser and an MCP annotation both are.

## 1.2 Relation to BlarAI's Canonical Action Representation

Read from `C:/Users/mrbla/BlarAI/shared/schemas/car.py` today. The CAR has eight fields: `source_agent`, `destination_service`, `verb` (READ, WRITE, EXECUTE, DELETE, QUERY, DISPATCH, EGRESS), `resource`, `parameters_schema`, `sensitivity` (PUBLIC, INTERNAL, SENSITIVE, UNCLASSIFIED), `timestamp`, `request_id`, `session_id`, and `canonical_hash()` over identity plus action fields only.

| Vocabulary field | In the CAR today? | What changes |
|---|---|---|
| `actor` | **Exists, wrong shape.** `source_agent` is documented as a "Cryptographic identity of the requesting agent (mTLS CN)" — a *service* identity inside one system, not a *product* identity of a third-party agent. | **Widened.** The product governs `claude-code` and `copilot-cli`, which have no mutual-TLS certificate. `actor.kind` and `agent_version` are new. |
| `categories` | **Partly.** `verb` is a single enum of 7. | **Replaced by a set of 13.** `READ/WRITE/DELETE/EXECUTE` map one to one; `EGRESS` becomes `network-send` (+ usually `network-receive`); `QUERY` and `DISPATCH` are BlarAI-internal routing verbs with no product meaning. **Six categories are new and have no CAR verb at all:** `credential-use`, `device-use`, `settings-change`, `purchase-or-payment`, `message-send`, `install`. Those six are exactly the ones a home user cares about most. |
| `systems_touched` | **Absent.** | **New.** Named by CAVA as required (`systems_touched`); already flagged as a CAR gap in `cava-vs-microsoft-agent-framework-vs-blarai-trust-spine-2026-09-16.md` (proposed item 4). |
| `reversibility` | **Absent.** | **New.** CAVA requires `reversible` (boolean). The three-valued form here is my change, because "reversible if a backup exists" is a different promise from "reversible", and a product that says the wrong one is lying to a person about whether they can undo. |
| `destination` | **Absent as a field.** At the egress door the destination is the URL inside `resource`. | **New.** The ACS design already recommends recording the host only in `resource` and letting the hash carry the full URL (an open [PROPOSED] privacy decision on BlarAI's side); this field set makes that structural instead of a convention. |
| `data_class` | **Adjacent, not the same.** `sensitivity` is PUBLIC/INTERNAL/SENSITIVE/UNCLASSIFIED — a *grade*. | **New, alongside.** `personal`/`credential`/`financial` is a *kind*. A person can answer "does this touch my passwords?"; nobody can answer "is this INTERNAL?". Recommendation: the product carries `data_class` and drops the grade; BlarAI keeps `sensitivity` because its rule engine is written over it. |
| `target` | **Exists as a string** (`resource`, e.g. `tool:<name>` or a URL). | **Structured** into class + display + hash, so a receipt can show a person something readable without storing the value. CAVA has `target` as an optional field. |
| `raw_tool` | **By convention only** — the ACS mapping document records `resource` as `tool:<name>`. | **Promoted to its own field**, so the convention cannot rot. |
| `args_hash` | **Unclear, and this is a discrepancy worth settling.** `car.py`'s docstring says `parameters_schema` is "JSON Schema of the action parameters (**not the values** — the schema)". The comparison document says the live dispatch check builds the CAR "from the tool name plus the canonical JSON of its arguments". Both cannot be true of the same field. | **Made explicit.** `args_hash` is a hash of the *values*, never the schema, and never the values themselves. I did **not** read `entrypoint.py` to settle which the live path does; flagged in §7 as not verified. |
| `derivation` | **Absent.** | **New, and the study's own addition.** Neither CAVA, nor the Agent Control Standard, nor MCP annotations carries a confidence-of-mapping field. |
| `adapter` | **Absent.** (`destination_service` is the target service, not the observing seam.) | **New.** CAVA has an optional `adapter` field; `host_posture` is new and comes straight from the measured Claude Code payload. |

**Summary in one line:** four CAR fields survive with changes (`source_agent`, `verb`, `resource`, and the hash discipline), one is dropped for the product (`destination_service`), one is replaced (`sensitivity` → `data_class`), and six fields are additions, of which one (`derivation`) exists nowhere in the field that I found.

## 1.3 Relation to CAVA, the Agent Control Standard, and protocol annotations — with licence lineage

| Source | What is borrowed | Licence | Read |
|---|---|---|---|
| **CAVA core** (`github.com/OndCo/CAVA`, Ond Holdings) | The required-field discipline itself: `runtime`, `operation`, `category`, `systems_touched`, `reversible` required; `adapter`, `executable`, `target`, `subject`, `metadata` optional. Also the action-gate-lease idea used in §4. | **Apache-2.0** — `LICENSE` fetched 2026-09-17, first lines "Apache License / Version 2.0, January 2004". | MEASURED (raw `schema.js` and `LICENSE` fetched today) |
| **Agent Control Standard**, OWASP GenAI Security Project (`github.com/GenAI-Security-Project/agent-control-standard`) | The disposition names used in §4: `allow`, `deny`, `modify`, `ask`, `defer`; the idea of a closed lifecycle-hook set. | **Code and schemas Apache-2.0; documentation CC BY-SA 4.0** — stated in the repository, fetched 2026-09-17. | REPORTED (repository page read today) |
| **Agent Control Specification / Agent Hooks contract** (the Microsoft-side text BlarAI aligned to) | The eight intervention-point names (`pre_tool_call` is the one used here), the three-valued verdict with escalate-as-liftable-deny, the `sha256:` identity encoding, the reserved-reason namespaces, the redaction rule. | **MIT** (`policy-engine/LICENSE.acs`, responsibleai, 2026), as recorded in BlarAI's `acs-vocabulary-adoption-design-2026-09-16.md`. | REPORTED (from BlarAI's on-disk document, not re-fetched) |
| **MCP tool annotations** (protocol-annotation vocabulary) | `readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint` as a *pre-existing, machine-readable* way for a tool to describe itself. | Not checked. | MEASURED (schema fetched today; see below) |

**MCP tool annotations, verbatim from the specification schema (`schema/2025-06-18/schema.ts`, fetched 2026-09-17):**

| Annotation | Type | Default | Doc comment |
|---|---|---|---|
| `title` | string | — | "A human-readable title for the tool." |
| `readOnlyHint` | boolean | **false** | "If true, the tool does not modify its environment." |
| `destructiveHint` | boolean | **true** | "If true, the tool may perform destructive updates to its environment… meaningful only when `readOnlyHint == false`" |
| `idempotentHint` | boolean | **false** | "If true, calling the tool repeatedly with the same arguments will have no additional effect" |
| `openWorldHint` | boolean | **true** | "If true, this tool may interact with an 'open world' of external entities… the world of a web search tool is open, whereas that of a memory tool is not." |

Two things matter here and both are in the product's favour.

- **The defaults already fail safe.** An MCP server that declares nothing is, by the specification's own defaults, destructive and open-world. Mapped into this vocabulary: `readOnlyHint=false` + `destructiveHint=true` + `openWorldHint=true` → `categories ⊇ {write}`, `reversibility = irreversible`, `destination.class = internet`, `host = null`. That is the right starting point for an unknown tool.
- **The specification itself forbids trusting them.** Verbatim: *"clients MUST consider tool annotations to be untrusted unless they come from trusted servers."* So annotations enter the record as `derivation = annotated` and are bound by the tighten-only rule: they may make an action look more dangerous, never less. A server that claims `readOnlyHint=true` gets no benefit from it.

**The study bets on no company.** Nothing above imports code from Ond Holdings, OWASP, Microsoft or Anthropic. The vocabulary is a naming choice; the enforcement is this product's. If any of those projects dies, is acquired, or changes its licence, the only cost is a version string. That is the same posture BlarAI already took toward the Agent Control Specification ("adopt as a vocabulary, not a dependency", and never claim conformance without running the conformance suite) and it is the posture recommended here.

## 1.4 Mapping (a): Claude Code's built-in tools — MEASURED payload

The payload a governor receives was measured on this machine on 2026-09-17 (Claude Code 2.1.273; 12 real payloads in `probes/p1/hook-payloads.jsonl`). Verbatim from run a1:

```json
{ "session_id": "62277f99-…", "transcript_path": "…", "cwd": "…\\p1-claude",
  "scratchpad_dir": "…", "prompt_id": "faf9a02f-…", "permission_mode": "default",
  "effort": { "level": "high" }, "hook_event_name": "PreToolUse",
  "tool_name": "Bash",
  "tool_input": { "command": "echo PROBE_DENY_ME", "description": "Echo the string PROBE_DENY_ME" },
  "tool_use_id": "toolu_01SkTVpkCmdoGndHHKRBHZBm" }
```

What the adapter therefore has to work with, per call: `tool_name`, the **full** `tool_input` object, a per-call identifier (`tool_use_id`), the session, the working directory, and `permission_mode`. What it does **not** have: the user's prompt, the model's reasoning, prior turns, the tool's result, any child process, and any network destination other than whatever the argument text happens to contain.

| Tool | `categories` | `systems_touched` | `reversibility` | `destination` | `derivation` | Notes |
|---|---|---|---|---|---|---|
| `Read` | `read` | filesystem class of the path; `accounts`/`devices` never | `reversible` | `local` | `declared` | `data_class` from the path class (a read of `~/.ssh` is `credential`). |
| `Glob` | `read` | filesystem class | `reversible` | `local` | `declared` | Names only, no contents → `data_class = none` even over a credential folder. Worth distinguishing in the receipt; a person reads "listed file names in" differently from "read". |
| `Grep` | `read` | filesystem class | `reversible` | `local` | `declared` | Reads contents. `data_class` from the path class. |
| `Edit` | `write` | filesystem class | `reversible-with-backup` **if** the governor's snapshot covers that class, else `irreversible` | `local` | `declared` | The agent offers no undo; the reversibility claim is the *governor's*, not the agent's. |
| `Write` | `write` (+ `delete` when it overwrites) | filesystem class | as `Edit` | `local` | `declared` | Overwriting an existing file destroys the old content; the record should carry `delete` too, and the adapter can only know that by a `Test-Path`, which is a local read it may do. |
| `MultiEdit` | `write` | filesystem class per target | as `Edit` | `local` | `declared` | **`target` must be a list.** One event, N files. The `args_hash` covers all of them, so an approval binds to the whole batch and a changed batch re-asks. |
| `NotebookEdit` | `write` | filesystem class | as `Edit` | `local` | `declared` | Same shape as `Edit`. |
| `WebFetch` | `network-send`, `network-receive` | `network` | `reversible` (the fetch) — but a GET can still be a state change on the far side | `internet`, `host` = the URL's host | `declared` | The host comes from the *argument*, never from the network seam. A redirect is invisible to the hook. |
| `WebSearch` | `network-send`, `network-receive` | `network` | `reversible` | `internet`, `host` = the search provider | `declared` | The query text leaves the machine; if the query contains personal data that is `data_class = personal` and the adapter cannot tell without reading it. Honest answer: `personal` by default for search queries under a cautious profile. |
| `Task` | `execute` | `unknown` | `unknown` | `unknown` | **`unknown`** | Delegation to a subagent. Whether the subagent's own tool calls fire their own `PreToolUse` events was **not measured** (see §7). Until it is, a `Task` is an unbounded `execute` and the profile decides. |
| `mcp__<server>__<tool>` | from the server's annotations if present, else `unknown` | as annotated, else `unknown` | `irreversible` unless annotated otherwise | `internet` unless annotated otherwise | `annotated` or `unknown` | Tighten-only. A server claiming `readOnlyHint=true` does not become a `read`. Note the measured limit: the event is the *invocation*; whatever the MCP server itself does afterwards (its own file and network I/O) produces no event at all. |
| **`Bash`** | **`execute`, and nothing else** | **`unknown`** | **`unknown`** | **`unknown`** | **`unknown`** | **The weakest point. See below.** |

### The weakest point, stated plainly

`Bash` (and its Copilot equivalents `bash` / `powershell`) delivers one string. The governor sees the string and nothing else. Measured, on this machine: the command

```
python -c "import urllib.request; print(urllib.request.urlopen('https://example.com').status)"
```

was presented as an ordinary `Bash` call, the hook allowed it, and it performed a real HTTPS request returning 200 (P1 run c1, 2026-09-17 06:57:22 UTC). **The event contained no network category, no destination, no host.** A vocabulary that fills those fields from the command text is guessing, and a governor that acts on the guess is a governor a person should not trust.

The honest treatment, and its ceiling:

1. **Default: `categories = {execute}`, everything else `unknown`, `derivation = unknown`.** The profile's `unclear_action` setting decides. It has exactly two legal values, `ask` and `deny`.
2. **An optional parser may raise `derivation` to `parsed`, under strict conditions, and may only tighten.** It may classify a command only when *all* of these hold: the whole string parses with no unparsed residue; there is no shell re-entry (`$( )`, backticks, `&&`, `||`, `;`, `|`, `>`, `<`, newline); there is no interpreter invoked with inline code (`python -c`, `node -e`, `pwsh -Command`, `sh -c`, `perl -e`, and their aliases); and every binary named resolves to a path on an allowlist. **The measured c1 case fails condition three, which is the point** — `python` is a perfectly ordinary allowlisted binary and the whole action lives inside its `-c` argument.
3. **The ceiling is lower still.** `python script.py` is `unknown` even to a perfect parser, because the action is in a file the parser has not read; and reading the file does not help, because the file can be rewritten between the hook's check and the shell's execution. That is a time-of-check-to-time-of-use gap the seam cannot close.
4. **Therefore the answer is not a better parser. It is a second, independent lock on the process** — a bounded working directory, no credential-store access, no outbound network except an allowlist. Defence in depth doing the work classification cannot. **And on this machine one of those locks is unavailable:** the per-process outbound firewall block was accepted by every management surface and enforced by none, because Bitdefender owns the firewall rule categories (P3a §1, MEASURED — 37 of 37 requests passed through the block, 0 kernel filters for the rule). A product that assumes the firewall lock is there will ship a developer profile that is one lock short on every PC with a third-party security suite, and will not know it. **That is why the coverage screen in §6 has a "seam not owned" row.**

## 1.5 Mapping (b): GitHub Copilot CLI — ARTEFACT

GitHub Copilot CLI 1.0.3 is installed on this machine but could not be exercised (the account's Copilot policy answered `Access denied by policy settings`; P1 §B, MEASURED). Its tool set was therefore read from the shipped bundle, which is the vendor's own artefact on this disk.

Read today from `C:\Users\mrbla\.copilot\pkg\win32-x64\1.0.3\`:
- `definitions/explore.agent.yaml` names, verbatim: `grep`, `glob`, `view`, `bash`, `read_bash`, `stop_bash`, `powershell`, `read_powershell`, `stop_powershell`, `lsp`, plus MCP tools written as `github-mcp-server/<tool>` and `bluebird/<tool>`.
- `definitions/task.agent.yaml` and `code-review.agent.yaml` grant `tools: ["*"]` — a wildcard, which is itself a finding: a subagent can hold the whole tool surface.
- `copilot-sdk/docs/agent-author.md` names `edit` and `create` as the file-writing tools, and `extensions_manage` / `extensions_reload` as extension-management tools.
- A read-only string scan of `app.js` finds the remaining built-in names in tool position: `create`, `edit`, `write`, `str_replace`, `fetch`, `view`, `plan`, `task`, `todos`, `web_search`.

| Copilot CLI tool | `categories` | `systems_touched` | `reversibility` | `destination` | `derivation` |
|---|---|---|---|---|---|
| `view` | `read` | filesystem class | `reversible` | `local` | `declared` |
| `glob`, `grep` | `read` | filesystem class | `reversible` | `local` | `declared` |
| `lsp` | `read` | `project-tree` | `reversible` | `local` | `declared` |
| `create`, `write` | `write` (+ `delete` on overwrite) | filesystem class | `reversible-with-backup` / `irreversible` | `local` | `declared` |
| `edit` / `str_replace` | `write` | filesystem class | as above | `local` | `declared` |
| `fetch` | `network-send`, `network-receive` | `network` | `reversible` | `internet`, host from the argument | `declared` |
| `web_search` | `network-send`, `network-receive` | `network` | `reversible` | `internet`, provider host | `declared` |
| `bash`, `powershell` | **`execute`** | **`unknown`** | **`unknown`** | **`unknown`** | **`unknown`** |
| `read_bash`, `stop_bash`, `read_powershell`, `stop_powershell` | `read` / `execute` | `other-apps` | `reversible` | `local` | `declared` |
| `task` | `execute` | `unknown` | `unknown` | `unknown` | `unknown` |
| `plan`, `todos` | `write` | `project-tree` | `reversible` | `local` | `declared` |
| `extensions_manage`, `extensions_reload` | `install`, `execute`, `settings-change` | `other-apps`, `system` | `irreversible` | `local` | `declared` |
| `github-mcp-server/<tool>`, `bluebird/<tool>`, any MCP tool | from annotations, tighten-only; else `unknown` | as annotated, else `unknown` | `irreversible` unless annotated | `internet` unless annotated | `annotated` / `unknown` |

**Two adapter differences that matter, and are not cosmetic.**

1. **Copilot's `preToolUse` payload is `{sessionId, timestamp, cwd, toolName, toolArgs}` where `toolArgs` is the raw argument JSON as a *string*** (ARTEFACT, `app.js`). There is **no per-call identifier**. Claude Code gives a `tool_use_id`; Copilot does not. So on Copilot an approval can only be bound by `args_hash` — which is exactly why `args_hash` is a field and not an optional extra, and why the re-derivation step in §4 is mandatory rather than a nicety.
2. **Copilot's payload has no equivalent of `permission_mode`.** On Claude Code the governor learns from the event when it is the only lock left (`bypassPermissions` was measured twice in the payload log). On Copilot it cannot know. `adapter.host_posture` is therefore `unknown` for Copilot, and the coverage screen shows it as such.

A generic MCP client (any agent whose actions are only visible as protocol tool calls) maps the same way as the `mcp__…` row: annotations if present, `unknown` if not, tighten-only either way.

## 1.6 How a profile treats the unknown

**Deny or ask. Never allow. This is a property of the file format, not of the user interface** — see §2, where `unclear_action` and `unknown_agent` accept only `"ask"` and `"deny"`, and a file that says `"allow"` is rejected with a plain-language error. Reasons, in order:

- It is the brief's R8 and R9 (honest default when nothing is known; fail closed) and BlarAI's security-by-design principles 1 and 2 (fail-closed, deny-by-default) carried into the product.
- The measured failure modes all produce "no information", not "a safe action": a crashed hook is silence (Claude Code run d2, MEASURED — the denied command ran), `--safe-mode` is silence (run e1, MEASURED), Copilot 1.0.3 catches hook errors and proceeds (ARTEFACT). If silence meant allow, every one of those is a bypass.
- The asymmetry from §Outcome: a wrong deny costs a retry; a wrong allow can move money or send data and has no restore.

The one legitimate softening, and it is a *profile* choice the person makes, not a default: the developer profile may set `unclear_action = "ask"` **and** declare a bounded working area within which an unknown `execute` is allowed-and-recorded rather than asked — but only while the independent locks named in §1.4(4) are actually in force. If the coverage screen says the network seam is not owned (the Bitdefender case), that softening is withdrawn automatically and the person is told why.

---

# 2. The profile format [PROPOSED]

**Format: TOML.** Chosen over JSON (no comments, and a person will want to write notes to themselves), over YAML (indentation errors are silent and a mis-indented deny becomes an allow), and over a bespoke format (nothing to learn, and every editor already highlights it). A profile is a single file the person owns, can read aloud, can e-mail to themselves, and can copy to a second PC (brief R14).

**Three rules the format enforces, checked when the file loads:**
1. Every key is a full plain-language phrase. No abbreviations, no enum codes in the file a person reads. The vocabulary's machine names appear only in the receipts.
2. Lists are `freely` / `after_asking` / `never`. **There is no fourth list**, and anything a list does not name falls to `when_it_is_not_sure`.
3. `unclear_action` and `unknown_agent` accept exactly two values each. A file containing `"allow"` there does not load, and the error says, in plain words, why.

## 2.1 Profile 1 — "Cautious home"

```toml
# ===========================================================================
#  AI action profile — "Cautious home"
#  For: someone who wants to be surprised as little as possible.
#  This file is yours. You can read it, change it, copy it to another PC,
#  and send it to someone you trust. It never leaves this machine on its own.
# ===========================================================================

profile_name        = "Cautious home"
written_for         = "A person who wants AI on this PC to stay inside ordinary, undoable things"
profile_version     = "1"
vocabulary_version  = "action-vocabulary 0.1-draft"

[how_much_it_talks_to_me]
# One of: "silent", "notify", "ask".
routine_allowed_actions  = "silent"     # things the profile already permits
refusals                 = "notify"     # I want to know when something was stopped
things_it_cannot_decide  = "ask"        # the only case that interrupts me
weekly_summary           = "Sunday 18:00"

[when_it_is_not_sure]
# Only "ask" or "deny" are accepted here. "allow" is not a choice this file
# offers: an action nobody could describe is not an action anybody approved.
an_action_it_cannot_describe = "ask"
an_agent_it_has_never_seen   = "deny"

[reading_my_files]
freely       = ["my downloads"]
after_asking = ["my documents", "my desktop", "my pictures"]
never        = ["my saved passwords", "my sign-in keys", "system files"]

[changing_my_files]
freely       = []
after_asking = ["my documents", "my desktop", "my downloads"]
never        = ["system files", "removable drives", "my saved passwords"]
keep_a_copy_before_changing = true

[deleting_things]
freely       = []
after_asking = []
never        = ["everything"]            # nothing on this PC may be deleted by an agent

[running_programs]
# A command typed into a terminal is one line of text. This product cannot
# see what that line will do. On this profile it is always a question.
anything_it_cannot_explain = "ask"
never                      = ["programs on a removable drive"]

[sending_things_out]
freely       = []
after_asking = ["searching the web", "fetching a web page"]
never        = ["sending my documents anywhere", "sending anything to an address I have not seen before"]

[using_my_sign_ins]
never = ["everything"]                   # passwords, keys and saved sign-ins are off limits

[camera_and_microphone]
never = ["everything"]

[changing_settings]
never = ["everything"]

[spending_money]
never = ["everything"]                   # this can never be turned into a standing yes

[sending_messages_as_me]
after_asking = ["everything"]            # e-mail, chat, calendar invitations
require_my_fingerprint = true

[installing_software]
never = ["everything"]

[how_long_a_yes_lasts]
default          = "this one action"
longest_allowed  = "30 minutes"
never_lasts      = ["spending money", "using my sign-ins", "sending messages as me"]
```

**What the app shows beside it (the plain-language rendering):**

> **Cautious home.** AI on this PC may look at your downloads on its own. It will ask before it opens or changes anything in your documents, desktop or pictures, and it keeps a copy of any file before it changes it. It may never delete anything, never touch your saved passwords or sign-in keys, never use the camera or microphone, never change a setting, never install anything, and never spend money.
> It will ask before it searches the web or opens a web page. It will ask before sending any message as you, and it will ask for your fingerprint when it does.
> When something is unclear, it asks you. When an agent it has never seen appears, it refuses and tells you.
> You will hear from it when something is refused, and once a week on Sunday evening with a summary. Otherwise it stays quiet. A "yes" you give lasts for that one action, and never longer than 30 minutes.

## 2.2 Profile 2 — "Developer running coding agents"

```toml
# ===========================================================================
#  AI action profile — "Developer running coding agents"
#  For: someone who runs coding agents daily and needs them to keep working.
#  The trade this profile makes: wide freedom inside the folders you name,
#  and hard limits everywhere else.
# ===========================================================================

profile_name        = "Developer running coding agents"
written_for         = "Someone whose coding agents must not be slowed down inside their own projects"
profile_version     = "1"
vocabulary_version  = "action-vocabulary 0.1-draft"

[my_project_folders]
# The boundary everything else in this file is measured against.
folders = ["C:/Users/mrbla/code", "C:/Users/mrbla/work"]

[how_much_it_talks_to_me]
routine_allowed_actions  = "silent"
refusals                 = "notify"
things_it_cannot_decide  = "ask"
weekly_summary           = "Monday 09:00"

[when_it_is_not_sure]
an_action_it_cannot_describe = "ask"
an_agent_it_has_never_seen   = "deny"

[reading_my_files]
freely       = ["my project folders"]
after_asking = ["my documents", "my desktop", "my downloads"]
never        = ["my saved passwords", "my sign-in keys", "my browser profiles", "system files"]

[changing_my_files]
freely       = ["my project folders"]
after_asking = ["my documents", "my desktop"]
never        = ["system files", "removable drives", "cloud-synced folders outside my projects", "my saved passwords"]
keep_a_copy_before_changing = true       # only inside the project folders; elsewhere nothing is changed without asking

[deleting_things]
freely       = ["files inside my project folders that are tracked by version control"]
after_asking = ["other files inside my project folders"]
never        = ["anything outside my project folders"]

[running_programs]
# This is the honest heart of this profile. A shell command is one string and
# the product cannot read it. Rather than guess, it fences the process.
inside_my_project_folders  = "allowed and recorded"
anywhere_else              = "ask"
this_permission_depends_on = ["the network fence below", "the sign-in fence below"]
# If the coverage screen reports either fence is not in force on this PC,
# "allowed and recorded" is withdrawn on its own and you are told why.

[sending_things_out]
freely       = ["package registries", "my source-code host", "documentation sites"]
after_asking = ["any other address"]
never        = ["sending files from outside my project folders"]

[using_my_sign_ins]
freely       = []
after_asking = ["my source-code host sign-in"]
never        = ["my saved passwords", "my browser profiles", "my cloud provider keys"]

[camera_and_microphone]
never = ["everything"]

[changing_settings]
after_asking = ["settings that belong to my development tools"]
never        = ["Windows settings", "security settings", "anything that would change this product"]

[spending_money]
never = ["everything"]

[sending_messages_as_me]
after_asking = ["everything"]
require_my_fingerprint = true

[installing_software]
freely       = ["packages into a project folder"]
after_asking = ["tools installed for my whole account"]
never        = ["anything installed for the whole computer"]

[how_long_a_yes_lasts]
default          = "this one action"
longest_allowed  = "this session"
never_lasts      = ["spending money", "using my sign-ins", "sending messages as me", "changing settings"]
```

**Plain-language rendering:**

> **Developer running coding agents.** Inside the two project folders you named, your agents work without interruption: they read, change and run things there, and everything is recorded. Outside those folders, everything changes. They will ask before touching your documents or desktop, and they may never touch system files, removable drives, your saved passwords, your browser profiles or your cloud keys.
> Running a command is the case this product is honest about: a command is one line of text and this product cannot read what it will do. Inside your project folders it lets commands run and records them, **because two other fences hold** — one on the network and one on your sign-ins. If either fence is not in force on this PC, this permission switches itself off and you are told which fence is missing.
> Web traffic to package registries, your source-code host and documentation goes through freely; anything else is a question. Nothing is ever bought. Messages sent as you always need your fingerprint. A "yes" can last a working session, but never for money, sign-ins, messages or settings.

## 2.3 Profile 3 — "Small business"

```toml
# ===========================================================================
#  AI action profile — "Small business"
#  For: the person who looks after a handful of PCs and has to be able to
#  show someone else what happened. The same file goes on every machine.
# ===========================================================================

profile_name        = "Small business"
written_for         = "Someone who must be able to prove afterwards what AI did on these PCs"
profile_version     = "1"
vocabulary_version  = "action-vocabulary 0.1-draft"
applies_to_machines = ["reception", "back-office", "the laptop"]

[how_much_it_talks_to_me]
routine_allowed_actions  = "silent"
refusals                 = "notify"
things_it_cannot_decide  = "ask"
weekly_summary           = "Friday 16:00"
also_keep_a_monthly_report = true

[when_it_is_not_sure]
an_action_it_cannot_describe = "deny"    # stricter than the other two profiles
an_agent_it_has_never_seen   = "deny"

[reading_my_files]
freely       = ["the shared work folder"]
after_asking = ["staff documents"]
never        = ["payroll", "customer records", "my saved passwords", "my sign-in keys"]

[changing_my_files]
freely       = []
after_asking = ["the shared work folder"]
never        = ["payroll", "customer records", "system files", "removable drives"]
keep_a_copy_before_changing = true

[deleting_things]
never = ["everything"]

[running_programs]
anything_it_cannot_explain = "deny"

[sending_things_out]
freely       = []
after_asking = ["searching the web", "fetching a web page"]
never        = ["sending any file anywhere", "any address not on the list below"]
addresses_i_allow = ["our accounting service", "our supplier portal"]

[using_my_sign_ins]
never = ["everything"]

[camera_and_microphone]
never = ["everything"]

[changing_settings]
never = ["everything"]

[spending_money]
never = ["everything"]

[sending_messages_as_me]
never = ["everything"]                   # nothing is sent in the business's name by an agent

[installing_software]
never = ["everything"]

[how_long_a_yes_lasts]
default          = "this one action"
longest_allowed  = "this one action"     # no leases at all on this profile
never_lasts      = ["everything"]

[the_record]
keep_for                = "7 years"
who_can_read_it         = "only this Windows account"
verify_every_time_it_opens = true
export_as               = "a signed file I can hand to an accountant or an insurer"
```

**Plain-language rendering:**

> **Small business.** On these PCs, AI may read the shared work folder and nothing else on its own. It asks before changing anything there. It may never touch payroll or customer records, never delete anything, never run a command it cannot explain, never send a file anywhere, never use a sign-in, never change a setting, never buy anything, and never send a message in the business's name.
> Every "yes" you give covers one action only. There are no standing permissions on this profile.
> Everything that happened is kept for seven years, readable only from this Windows account, checked for tampering every time you open it, and exportable as a signed file you can hand to an accountant or an insurer.
> You hear about refusals as they happen, get a summary every Friday afternoon, and a report every month.

## 2.4 The noise setting, stated once

Three values, used everywhere in the file: **`silent`** (recorded, nothing shown), **`notify`** (a Windows notification, no answer needed, and the event is in the history), **`ask`** (the action waits for the person). `ask` is the only value that blocks. The `[how_much_it_talks_to_me]` block is the only place noise is configured, so a person who finds the product chatty has one place to go — the lesson the antivirus vendors learned, and the one place all five of them put it (§5).

---

# 3. The device scan as an inventory [PROPOSED]

The scan answers one question for the person: *what could an AI on this PC reach?* It is the thing profiles are written against (brief R7). It runs at first setup and then on a schedule.

## 3.1 What it enumerates

Presence of every item below was checked read-only on this machine today (PowerShell, `Test-Path` / `Get-Volume` / `Get-NetAdapter` / `Get-PnpDevice` / `cmdkey /list` counted, never read) — so the list is not a wish list, it is what an enumerator actually finds here.

| Group | What is enumerated | Found here (MEASURED, 2026-09-17) |
|---|---|---|
| Your folders | Documents, Desktop, Downloads, Pictures, Music, Videos, Public folders | Documents ✓ Desktop ✓ Downloads ✓ |
| Folders that sync to the internet | OneDrive and equivalents; any folder redirected into one | OneDrive ✓ — and this matters: Microsoft's own controlled folder access documentation notes that when OneDrive Known Folder Move backs up Documents, the *protected* folder moves with it, so a folder's class can change under the person |
| Saved sign-ins | Windows Credential Manager (**count of entries only**), browser profile folders, SSH key folders, cloud command-line tool folders | Credential Manager: **15 entries** (count only; no target names, no values). Edge profile ✓ Chrome profile ✓ `.ssh` ✓ `.aws` ✓ `.azure` ✓ GitHub CLI ✓ gcloud ✗ |
| Version-control and package identities | `.gitconfig`, `.npmrc` and equivalents | `.gitconfig` ✓ `.npmrc` ✗ |
| Network | Adapters that are up, the DNS servers in use, whether a VPN is present | 2 adapters up. (P3a MEASURED separately: Name Resolution Policy Table has 0 entries; DNS-over-HTTPS configured but `AutoUpgrade False`; a VPN client is installed with its tunnel stopped.) |
| Devices | Cameras, microphones, removable drives | 2 cameras, 1 microphone input, 0 removable volumes (2 fixed) |
| Installed agents | Agent executables on PATH and in the usual per-user locations, with versions | Claude Code ✓ (2.1.273) · GitHub Copilot CLI ✓ (1.0.3) · Copilot app ✓ (153.x) · Codex ✗ on PATH |
| **Agent configuration folders that exist without the agent** | The same locations, checked independently of the executable | **`~/.codex` exists although `codex` is not on PATH.** This is exactly the case the scan must surface: a configuration folder is a place a hook can be registered, and an agent that is not installed *today* can be installed tomorrow into a folder that already has settings in it. |
| Local model runtimes | Ollama, LM Studio, Foundry Local, OpenVINO Model Server | none found (`.ollama` ✗, `.lmstudio` ✗) |
| Protocol server configurations | MCP server entries found inside the agents' own configuration files — **server names and command names only** | `~/.claude.json` present; its MCP entries were **not read** for this report (see §3.3) |
| Security products that own a seam | Registered firewall products (`INetFwProducts`), registered antivirus | **Bitdefender Firewall, claiming rule categories BOOT, STEALTH and FIREWALL** (P3a MEASURED). This row is what feeds the "seam not owned" line on the coverage screen. |

## 3.2 How it is presented

Not as a table of paths. As a short page of sentences with counts, each expandable:

> **What AI on this PC could reach**
>
> **Your files.** Three folders with your own documents in them, and one folder — OneDrive — that copies anything put in it to the internet automatically. *(Show me the folders)*
>
> **Your sign-ins.** Windows is holding **15 saved sign-ins**. There are sign-in keys for two cloud services, a key folder used by developer tools, and two web-browser profiles that hold saved passwords. **This product did not open any of them and never will.** *(What is in here?  →  only their names and where they live; we never read what is inside)*
>
> **Your network.** Two connections are active. A VPN is installed but switched off.
>
> **Your devices.** Two cameras and one microphone. No removable drives plugged in right now.
>
> **AI programs installed here.** Three, plus settings left behind by a fourth that is not installed at the moment. *(Show me)*
>
> **Something you should know.** Your firewall is run by Bitdefender, not by Windows. That means this product cannot put a network fence around an AI program on this PC. It affects one thing in the developer profile, and it is shown on the coverage screen. *(Explain)*

## 3.3 What the scan must never do

These are rules of the product, not settings.

1. **Never read contents.** It records that `~/.ssh` exists and that the Credential Manager holds 15 entries. It does not read a key, does not call `CredRead`, does not open a browser profile database, does not open a document. The distinction is the difference between an inventory and a data-collection tool, and a governor that reads the things it is protecting has become the threat it was installed to stop.
2. **Never send anything.** No telemetry, no "anonymous" inventory upload, no crash dump containing the scan, no cloud reputation lookup on the file names it saw. The product has no cloud to send to, by construction (brief R10, concept spec "structural absence").
3. **Never store a value where a class will do.** The stored inventory is classes and counts. A path is stored only where the person themselves named it (their project folders) and is treated as their data.
4. **Never enumerate another user's profile on a shared PC**, and never present one person's inventory to another. (Multi-user design is Q13 and is another agent's section; the scan's rule is stated here because it is the scan that would violate it first.)
5. **Never require administrator rights to run the basic scan.** Everything in the table above except the registered-security-product check and the ETW-based observation was readable from an ordinary user session.

---

# 4. The approval and lease model [PROPOSED]

## 4.1 Events that must interrupt

An interruption is the product spending the person's attention. The list is short on purpose, and every entry is on it because the action cannot be undone or because it binds something outside the machine.

| Must interrupt | Why |
|---|---|
| Spending money, in any form | No restore exists. Never leasable, on any profile. |
| Using a saved sign-in, password, key or token | The credential outlives the action; a wrong yes is a standing compromise. |
| Sending a message as the person (e-mail, chat, calendar invitation) | It reaches another human, and cannot be recalled. |
| Deleting anything outside a declared project folder | No restore unless the governor's own snapshot covers it, and `reversibility` says whether it does. |
| Sending a file whose `data_class` is `personal`, `credential` or `financial` anywhere | This is the exfiltration case; it is the one a person can actually judge. |
| Changing a Windows or security setting, or anything about this product | The self-governance rule: the governor cannot widen its own coverage without the person (concept spec; BlarAI's self-governance boundary). |
| Installing software for the whole computer | Persistent, privileged, and outlives the session. |
| An action whose record is `unknown` when the profile says `ask` | The honest default doing its job. |

## 4.2 Events that must not interrupt

| Must not interrupt | Instead |
|---|---|
| Anything the profile already allows | Recorded silently; visible in the history and counted in the digest. |
| Anything the profile already refuses | Refused, receipted, and shown as a notification if the profile's `refusals` setting says `notify`. **A refusal is never a question.** A governor that turns every deny into a prompt has re-invented approval fatigue with extra steps. |
| Repeats of an action already approved under a live lease | Covered by the lease; each repeat is still disclosed in the history. |
| The product's own housekeeping | Verification of the record, scans, adapter canaries. Only a *failure* surfaces. |
| Anything at all while the person is in a full-screen application | Held and shown when they come back — the Bitdefender/Norton/ESET/Malwarebytes device (§5), with one exception: an action on the "must interrupt" list is not held, it is **refused**, and the refusal is shown afterwards. This is the inversion the vendors do not have to make, because holding a virus alert is safe and holding a payment approval is not. |

## 4.3 The lease grammar

A lease is a bounded standing yes. It is CAVA's Action Gate Lease and BlarAI's per-turn envelope wearing one name.

```
LEASE
  covers   categories      : a subset of the profile's own permissions, never wider
           target_class    : one class, never "anything"
           destination     : one class + optional host, never "anywhere"
  bound to agent_id        : the exact agent, and its version
           user            : the Windows account that granted it
           profile_hash    : sha256 of the profile file as it was when granted
           vocabulary_ver  : the vocabulary version used to describe the action
           origin_action_id: the action that caused the person to be asked
  lasts    N minutes  |  N uses  |  this session          (whichever comes first)
  dies on  any of the conditions below
```

**A lease dies immediately on any of:** the profile file changing; the agent updating to a different version; the Windows account changing or the machine locking or sleeping; the first refusal inside its scope (latched — a fooled agent must not be able to retry past a refusal, which is BlarAI's measured envelope behaviour, `egress_envelope.py`: `env.denied` latches and a later egress in the same turn is refused without re-prompting); the adapter's canary failing; the person revoking it.

**A lease may never cover:** `purchase-or-payment`, `credential-use`, `message-send`, `settings-change`, or any action whose record is `derivation = unknown` **and** `reversibility = irreversible`.

**Binding, and the re-derivation that makes it mean anything.** This is BlarAI's approval-binding design (`acs-vocabulary-adoption-design-2026-09-16.md`, "The approval binding", five steps) carried over, and it is the field's strong pattern:

1. The adapter builds the record and computes `action_id` and `args_hash` regardless of the outcome.
2. The person is asked, and is shown the plain-language rendering plus the first twelve characters of `action_id`, so the prompt and the receipt can be matched by eye.
3. The approval carries `action_id` back. An approval without it, or with a different one, is a refusal.
4. **Immediately before the governor answers "allow", it rebuilds the record from what is actually about to run and recomputes the hash.** A mismatch is a refusal, with the reason `approval_identity_mismatch`, a receipt, and the turn ends. This is the step that makes "what you approved is what runs" true rather than aspirational — and on Copilot CLI, where there is no per-call identifier at all (§1.5), it is the *only* thing that makes it true.
5. The single-use approval is consumed. A lease is decremented.

## 4.4 The presence check

Windows Hello reports `Available` on this machine with face and fingerprint devices present (P3b seam 9, MEASURED), and BlarAI's existing verifier uses only public, portable Windows surfaces, so this is portable to any Windows 11 PC with the hardware.

**Which actions require presence, not just a click:** spending money; using a saved sign-in; sending a message as the person; deleting outside a project folder; sending anything whose `data_class` is `credential` or `financial`; changing this product's own settings or coverage. Everything else is an ordinary dialog.

The reason for the distinction is that a click can be produced by software on the machine and a fingerprint cannot. It is the one control that answers "an agent clicked its own approval dialog".

**The measured constraint on signing, which changes the design.** A throwaway TPM ECDSA P-256 key on this machine signed in **77–94 ms median warm, and 131–157 ms in the open-provider-open-key-sign-free pattern the existing signer uses**, against **0.027 ms** for software ECDSA — a 3,000 to 5,000-fold gap (P3b seam 9, MEASURED). A coding agent produces tool calls far faster than that. **Therefore: chain every record by hash, and sign the chain head periodically and at every close** — never sign per action. The chain gives tamper-evidence per record; the periodic signature gives hardware rooting. This is the brief's Q12 budget question answered for the one number that was measured.

## 4.5 The digest

Assembled entirely from the receipts on the machine; nothing leaves (brief R10). Per the profile's schedule.

> **This week on this PC.**
> Your AI programs did **3,412** things. **3,389** were things you had already allowed. **19** were refused. **4** you were asked about, and you said yes to 3.
> **Claude Code** did most of it, all inside your project folders.
> **One thing changed.** GitHub Copilot CLI updated itself on Wednesday, and this product could not confirm it was still being governed for 40 minutes afterwards. It is governed again now. *(Show me what happened in those 40 minutes)*
> **One thing you may want to look at.** Something tried to read your `.ssh` folder on Tuesday and was refused. *(Show me)*
> Nothing left this PC. *(Verify the record)*

The digest's job is to make the *absence* of surprises legible, and to put coverage gaps in the same place as the counts — because "what ran ungoverned" is a scenario the concept specification requires (S5) and is the number a person actually needs.

---

# 5. Q3a — The antivirus interaction model

## 5.1 What the consumer suites do about decision fatigue

| Product | Automatic mode | Quiet mode | Per-item exception | History / activity | Periodic report | Notification control | Grade |
|---|---|---|---|---|---|---|---|
| **Bitdefender Total Security** (installed here, 27.0.60.341) | **Autopilot** — "acts as a Security Advisor"; "recommend security actions in the context of your system needs and usage patterns"; "detects when you play, work or watch a movie, so it knows not to bother you with unnecessary requests" | **Profiles** — Work, Movie, Game, Public Wi-Fi, Battery Mode. "Bitdefender automatically enables the appropriate profile based on your current activity or running applications"; one at a time; "while in use, profiles also stop all notifications from being displayed on the screen" | **Exceptions**, scoped to a path: antivirus exclusions by file/folder/extension; **Advanced Threat Defense exceptions accept only `.EXE` files**, "as Advanced Threat Defense only monitors running processes" | **Notifications** area: "a detailed log of events concerning its activity on your computer", three severities — Critical ("check them immediately"), Warning ("check and fix them when you have the time"), Information ("successful operations"); each entry shows "a short description, the action Bitdefender took on it when it happened, and the date and time" | Consumer monthly/security report: **not verified** (the vendor pages found were the business GravityZone reporting docs) | Per-severity sections, "delete or mark as read all events in that section"; profiles suppress everything | REPORTED |
| **Microsoft Defender / Windows Security app** | Defaults are the automatic mode; **controlled folder access is off by default** and has an **Audit Mode** so its effect can be measured before it blocks anything | No consumer quiet mode equivalent | **Allowed apps** for controlled folder access, by exact path, with environment variables and wildcards **in the folder portion only**; and "By default, Microsoft Defender Antivirus automatically trusts apps based on their prevalence and reputation" | **Protection history** — "a comprehensive list of actions that Microsoft Defender Antivirus has taken on your behalf"; colour-coded cards, red = urgent, yellow = worth checking; **"Protection history only retains events for two weeks"**; per-entry actions include quarantine/allow, remove/**restore**, allow a blocked app, turn a service back on | "a summary of scans and threat detections appear at regular time intervals" (enhanced notifications) | **Suppress all notifications**, **Suppresses reboot notifications**, **Turn off enhanced notifications**; verbatim: "Disabling other notifications doesn't disable critical notifications, such as threat detection and remediation alerts" | REPORTED (ms.date 2026-07-02, 2026-08-12) |
| **Norton** | — | **Silent Mode** "stops sending alert messages and suspends background tasks"; **Quiet Mode** "suspends the background activities but does not suppress alerts"; **Full Screen Detection** "helps you turn on Silent Mode automatically when Norton detects a full-screen application" | Per-application list: Settings → General → Notification settings → **Edit Apps** → Add Application | — | — | Two separate modes, deliberately: one for noise, one for CPU | REPORTED |
| **ESET** | — | **Gamer mode / Presentation mode** — "all pop-up windows are disabled and the activity of the scheduler will be stopped completely"; "System protection still runs in the background but does not demand any user interaction"; can "start whenever you initiate a full-screen application and stop after you exit"; **"Enabling Gamer mode is a potential security risk"** and the tray icon "will turn orange and display a warning" | — | — | — | The one vendor that **says out loud that its quiet mode is a risk and shows a persistent warning while it is on** | REPORTED |
| **Malwarebytes** | — | **Play Mode** — hides notifications "when selected apps are open"; "Suspend notifications and updates when selected apps are open" toggle **On by default**; Premium only | Per-application list a user adds to | Detection history (separate feature) | — | "If a notification occurs that requires user action, it is displayed after you close the apps that are added in Play Mode" | REPORTED |

**The common shape, across all five.** One automatic mode so the product is usable without configuration. One quiet mode that turns itself on by detecting what the person is doing (a full-screen application, every time). One exception list, always scoped to a path or an application, never global. One event history. Notification control in one place, with critical alerts carved out of it.

## 5.2 What transfers to governing actions

| Antivirus device | Becomes | Why it works |
|---|---|---|
| **"Allow once" / "Allow always"** on a detection | **A lease** (§4.3) | Same shape — a bounded standing yes — but with the bounds made explicit and expiring, which "always" never is. Bitdefender's exception list has no expiry; a lease does, and that is the improvement. |
| **Exclusions** (path-scoped, `.EXE`-scoped) | **Per-agent, per-path rules** | Bitdefender's Advanced Threat Defense already scopes exceptions to *one executable path* and refuses folders because "it only monitors running processes". That is precisely the grain a governor wants: this agent, this folder. Microsoft's "only the app in that location is allowed" rule is the same idea. The vocabulary's `actor.agent_id` + `target.class` pair is that grain generalised. |
| **The security report / summary notifications** | **The weekly digest** (§4.5) | Same job: make a quiet period legible. The addition a governor must make is a coverage line, because a quiet week with a broken adapter looks identical to a quiet week. |
| **The activity feed / protection history / notifications area** | **The receipt history** | Bitdefender's three severities map onto refusals / asks / allowed; its "the action Bitdefender took on it when it happened, and the date and time" is the receipt's minimum. The governor adds two things no suite has: **the reason** (which profile rule decided) and **verification** (a signed chain the product checks whenever it opens it). |
| **Autopilot / profile auto-switching** | **The profile's noise setting**, and nothing more | The deliberate non-transfer. Bitdefender's Autopilot chooses *security actions* for the person. A governor must not: the profile is the person's decision and the governor's job is to apply it, not to improve on it. What transfers is the *quietness*, not the autonomy. |
| **Audit Mode** (controlled folder access) | **A first-week observe-only period, offered once** | Microsoft recommends running CFA in Audit Mode first "to assess its effect before you move to Enabled (block) mode". The equivalent is valuable and is also a trap: BlarAI's own rule is that a silent evaluate-only posture must never be added by default. So: offered explicitly at setup, time-boxed, with a persistent banner while it is on, and it ends by itself. Never the default, never silent. |
| **ESET's orange tray icon while Gamer mode is on** | **The visible-degradation rule** | The single best idea in the five products, and the only one that is really about honesty: when protection is reduced, say so continuously, not once. It becomes the coverage screen's amber state and the banner during any observe-only period. |

## 5.3 Where it breaks

Four breaks. The first is the important one.

1. **A wrong allow can bind money or send data, and an action is not quarantinable.** Antivirus's whole interaction model is safe because its mistakes are recoverable in both directions: a false positive is restored from quarantine ("Remove quarantined threats or **restore** them"), and a false negative is caught later by a signature update and cleaned. **A governor has neither.** An approved payment is made. An approved e-mail is read by its recipient. An approved `rm -rf` on an untracked folder is gone. There is no restore-from-quarantine analogue, because there is no quarantine — the object is an *event*, not a *file*, and events do not sit still waiting to be reviewed. Everything strict in §4.1 follows from this one sentence.
2. **"Reputation" has no analogue.** Defender "automatically trusts apps based on their prevalence and reputation" — a cloud judgment about a file hash seen on millions of machines. A local, no-telemetry governor has no such population and must not invent one. The substitute is not reputation but *structure*: deterministic rules over categories, a bounded lease, and an honest `unknown`. This is a real capability the incumbent has and this product does not, and pretending otherwise would be the kind of vendor prose the study exists to discount.
3. **Holding an interruption is not always safe.** Play Mode's rule — "if a notification occurs that requires user action, it is displayed after you close the apps" — is correct for a virus alert and wrong for an approval, because the agent is blocked while the person is in a game. The governor's resolution (§4.2): hold *notifications*, but **refuse** anything on the must-interrupt list rather than hold it, and show the refusal afterwards. The person loses an action, not a decision.
4. **The product's own telemetry posture is a design decision, and it is the one that decides whether anyone believes the rest.** Every product in §5.1 sends something somewhere by default. This one has no cloud to send to (brief R10; concept spec's "structural absence"). The consequences must be accepted openly rather than engineered around: there is no crash reporting, no usage analytics, no cloud reputation, and no way to learn that an adapter broke on ten thousand machines. The substitute — opt-in diagnostics the person can read in full before they are sent — is Q11's territory and is not solved here. **The recommendation stands anyway: no telemetry by default, stated on the box.** A governor that phones home is asking to be trusted with exactly the thing it exists to prevent.

## 5.4 Setup, then background: the three profiles as short narratives

### Cautious home

**First run (about four minutes).** The product scans and shows the inventory page from §3.2 — three folders, one that syncs to the internet, fifteen saved sign-ins it did not open, two cameras, three AI programs. It offers three profiles in one sentence each and pre-selects *Cautious home*. She takes it. It asks for her fingerprint once, to prove the machine is hers and to make the record hers. It writes the first receipt and says: **"Two of your three AI programs are governed. One is watched but cannot be stopped. Here's the difference."**

**Week one.** Nothing. Two notifications: on Tuesday, "An AI program tried to read a folder with sign-in keys in it. I refused."; on Thursday, "Copilot updated itself. I checked it's still governed." She does not open the app.

**The first interruption.** She asks her assistant to tidy her tax folder. It proposes deleting eleven files. The screen says: **"Your assistant wants to delete 11 files from Documents\Tax. This cannot be undone. Should I let it?"** — with the file names, a *Keep a copy first* button already ticked, and *Yes* / *No*. She says yes. One approval, for those eleven files. When the assistant then tries a twelfth, the hash no longer matches and she is asked again.

**The weekly digest.** Sunday evening, one notification, six lines, the shape in §4.5. She reads it in fifteen seconds.

**Opening the history.** A search box and a list of sentences in plain English: *"Tuesday 14:02 — your assistant asked to read your sign-in keys. Refused, because your profile never allows that."* A **Verify** button at the top. She presses it and gets: *"All 3,412 entries are intact and unchanged since they were written."*

### Developer running coding agents

**First run (about eight minutes).** He picks *Developer*, names two project folders, and reads the one screen that matters: **"Commands are one line of text and I cannot read what they will do. Inside your project folders I let them run and record them. That is safe only because two other fences hold — one on the network, one on your sign-ins."** Then the honest part: **"On this PC the network fence is not available. Bitdefender runs your firewall, not Windows, and my rules would be stored and not enforced. Here is what I can do instead."** He is offered three options and picks "record everything and refuse any command that names a credential path".

**Week one.** Silence inside the projects. Two refusals: a `git push` to a host not on his list, and a command that read `~/.aws`. Both notified, both in the history with the exact command. He adds the host to the profile in his editor; the file reloads and every live lease dies, which the product tells him.

**The first interruption.** An agent proposes `npm install` of a package he has not seen. Because the install writes outside the project folder, the screen asks — with the package name, the registry, and the size — and offers a 30-minute lease for "installs into this project from this registry". He takes the lease. Four more installs follow without asking, each disclosed in the history as it happens.

**The weekly digest.** Monday morning. **11,904 actions, 11,860 allowed, 38 refused, 6 asked.** One line he actually reads: **"Claude Code ran 4,201 commands I could not classify. All inside your project folders. None named a credential path."** That number is the product being honest about its own blind spot rather than hiding it in a green tick.

**Opening the history.** Filter by agent, by folder, by "commands I could not classify". Each entry has the raw tool name, the arguments hash, the twelve-character action identifier, and the profile rule that decided. He exports a day as a signed file and diffs it against his shell history.

### Small business

**First run (about twelve minutes, on three PCs).** She sets it up on the back-office PC, picks *Small business*, marks payroll and customer-records folders as never-touch, and exports the profile to a file. On the other two PCs she imports it; the inventory differs, so each machine tells her what is different here. The record is set to seven years.

**Week one.** One notification on the reception PC: an AI feature in an application tried to read a customer-records folder and was refused. She had not known that feature existed. She finds it on the coverage screen listed as *observed only — cannot be stopped*, with the three options (sandbox it, restrict its network, accept the risk), and turns the feature off in the application instead.

**The first interruption.** None in week one, which is the point of `an_action_it_cannot_describe = "deny"` on this profile: unclear actions are refused rather than queued for her.

**The weekly digest, and the monthly report.** Friday afternoon, per machine, plus one combined monthly report she saves. The monthly report includes what she will actually be asked for: *"Every decision on these three PCs for this month, 41,207 of them, verified intact, exportable as one signed file."*

**Opening the history.** Searchable per machine, per agent, per folder. The **Verify** button reports the chain and, if it ever breaks, reports the **first** broken entry by date — because an auditor's question is not "is it fine" but "when did it stop being fine".

---

# 6. Q4 — The coverage screen [PROPOSED]

The coverage screen is the product's contract (concept spec, non-goals: "Promise coverage it cannot measure. The coverage screen is the product's contract"). It is a live instrument, not a claim.

## 6.1 The wireframe

```
┌────────────────────────────────────────────────────────────────────────────────┐
│  COVERAGE — what I can actually hold on this PC          Last checked  09:41    │
│                                                          Next check    10:41    │
├────────────────────────────────────────────────────────────────────────────────┤
│                                                                                │
│  ● GOVERNED        2 agents      I see each action before it happens and can    │
│                                  stop it.                                       │
│  ◐ OBSERVED ONLY   1 agent       I can see what it did afterwards. I cannot     │
│                                  stop it.                                       │
│  ○ OUT OF REACH    1 agent       I cannot see or stop anything it does.         │
│  ? UNKNOWN         1 agent       I do not know. I will not guess. Treated as    │
│                                  ungoverned until I do.                         │
│                                                                                │
├────────────────────────────────────────────────────────────────────────────────┤
│                                                                                │
│  ● Claude Code  2.1.273                                          GOVERNED      │
│    Through      its own pre-tool-use hook (I answer before each tool runs)     │
│    Last proof   09:38 — my test action was refused, as expected  [what is this?]│
│    ⚠ It has a switch (--safe-mode) that skips me. If it is used I will say so.  │
│    ┌ What I can promise about the record ─────────────────────────────────────┐ │
│    │ Which actions I record   Every tool call, before it runs, plus my answer │ │
│    │ Which phases I cover     Before a tool runs. Not the result, not the     │ │
│    │                          prompt, not what a command spawns afterwards.   │ │
│    │ Which rules I can check  All of them for named tools. For a typed        │ │
│    │   mechanically           command: none — I see one line of text.         │ │
│    │ Who is responsible       You approved; I decided; Claude Code executed.  │ │
│    │                          Each receipt names all three.                   │ │
│    │ How the record is        Every entry hashed to the one before it; the    │ │
│    │   protected              chain signed by this PC's security chip.        │ │
│    │ If the record is missing I say so, loudly, and name the first gap by     │ │
│    │                          date. I never fill a gap in silently.           │ │
│    └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                                │
│  ● GitHub Copilot CLI  1.0.3                                     GOVERNED      │
│    Through      its own pre-tool-use hook                                      │
│    Last proof   09:38 — test action refused                                    │
│    ⚠ In this version, if I crash it carries on without me. I cannot detect     │
│      that from inside. My hourly test is the only thing that would notice.     │
│    ⚠ It does not tell me when it is running with its own checks switched off.  │
│    [ Show the six questions ]                                                  │
│                                                                                │
│  ◐ Copilot (the Windows app)  153.x                         OBSERVED ONLY      │
│    Through      Windows process and network tracing (after the fact)           │
│    I can see    that it ran, and which addresses it connected to               │
│    I cannot see the web address, the content, or what it was asked to do       │
│    I cannot stop anything it does.                                             │
│    What you can do →  [ Sandbox it ]  [ Restrict its network ]  [ Accept ]     │
│    [ Show the six questions ]                                                  │
│                                                                                │
│  ○ AI features inside other applications                      OUT OF REACH     │
│    They run inside the application. They do not pass through me at all.        │
│    What you can do →  [ Turn the feature off in that app ]  [ Accept ]         │
│                                                                                │
│  ? Codex CLI                                                       UNKNOWN     │
│    Not installed — but its settings folder exists on this PC, so it has been    │
│    here or is expected. Your profile refuses agents I have never seen.          │
│    I will classify it the first time it runs. Until then: not governed.         │
│                                                                                │
├────────────────────────────────────────────────────────────────────────────────┤
│  ⚑ A fence I do not own on this PC                                             │
│                                                                                │
│    The network fence  —  NOT AVAILABLE HERE                                    │
│    Your firewall is run by Bitdefender, not by Windows. Bitdefender has taken   │
│    ownership of firewall rules on this PC. If I add a rule to stop one AI       │
│    program reaching the internet, Windows stores it and nothing enforces it —   │
│    and nothing warns you. I tested this: 37 of 37 connections went through a    │
│    block that every screen said was in place.                                   │
│                                                                                │
│    What this costs you:  one of the two fences the developer profile leans on   │
│                          when it lets commands run. That permission is off.     │
│    What you can do →  [ Use Bitdefender's own rules ]  [ Explain ]  [ Accept ]  │
│                                                                                │
├────────────────────────────────────────────────────────────────────────────────┤
│  Coverage over the last 7 days: 96.4% of actions governed, 3.6% observed only. │
│  [ Verify the record ]   [ Export this screen as a signed file ]                │
└────────────────────────────────────────────────────────────────────────────────┘
```

## 6.2 The four states and their rules

| State | Means | Rule |
|---|---|---|
| **GOVERNED** | The product answers before the action runs, through a named seam, and a canary proved it within the check interval | May only be shown when a canary passed. Never inferred from a configuration file being present. |
| **OBSERVED ONLY** | A receipt arrives after the fact | Must name what the observation cannot see. On Windows that is: no command line, no hostname, no URL, no content (P3b seam 8, MEASURED). |
| **OUT OF REACH** | Nothing passes through the product | Must offer the platform's real options, never a vague reassurance. |
| **UNKNOWN** | Nothing is known | **The default for anything newly seen.** The profile's `unknown_agent` setting decides what happens meanwhile, and it is `deny` on all three example profiles. |

## 6.3 The six Auditability Card questions, one line each, per agent

The card is item 15 of BlarAI's proposed list (#1544), refining the per-surface interception-depth table with Auditable Agents' six questions. Rendered per agent as in the wireframe:

1. **Which actions are recorded** — for a hook-governed agent: every tool call before it runs, with the product's answer. For an observed-only agent: process starts and network connections only.
2. **Which lifecycle phases are covered** — the ACS coverage statement in plain words. For Claude Code today: `pre_tool_call` only. **Naming the four points it does *not* emit is the load-bearing half**: the absence of a record at `post_tool_call` means "not instrumented", never "always allowed".
3. **Which rules are mechanically checkable** — all of them for named tools; **none of them for a typed command**, because the seam delivers one string (§1.4). This line is where the product says its weakest point out loud, on the screen, per agent.
4. **What the responsibility chain is** — who approved, what decided, what executed. Three names on every receipt.
5. **What integrity protection the records have** — hash-chained per entry, chain head signed by the TPM periodically (per the measured 77–157 ms cost, §4.4), verified on every open.
6. **What happens when records are missing** — the product says so loudly and names the first gap by date. It never interpolates, never back-fills, and never shows a gap as green.

## 6.4 What the screen does when an adapter's canary fails

**Every adapter ships a canary**: a harmless action the governor drives through the agent on a schedule and expects to be asked about. It exists because the two ways a hook governor dies are both invisible from inside — a crashed hook is treated as silence and the action runs (MEASURED, run d2), and `--safe-mode` skips the hook entirely with no trace (MEASURED, run e1).

On a failed canary:

1. The agent's row goes from **GOVERNED** to **UNKNOWN**, amber, immediately. It never silently stays green, and it never goes to a green "degraded" state — ESET's orange icon is the model (§5.2).
2. The row names what it observed: *"My test action was not refused at 10:41. Either the hook is not running, or it ran with hooks switched off."*
3. **Every live lease bound to that agent dies** (§4.3). A lease is a promise made on the assumption that the governor is still in the path.
4. The profile's `unknown_agent` setting takes effect for that agent, which on all three example profiles is `deny`.
5. A receipt is written for the coverage change itself — the coverage screen's history is part of the record, because "when did it stop being governed" is an auditor's question (concept spec S6, R16).
6. The person gets a notification **regardless of the profile's noise setting**, because a coverage loss is not an event, it is a change to what the product is.
7. **The gap is bounded, not hidden.** The digest and the history show the exact window: *"not confirmed governed between 10:41 and 11:21"*, with everything that ran in it.

## 6.5 The "seam not owned" row, and why it must exist

This row exists because of a measured finding on this machine and is the honest form of a claim no competitor makes.

The measurement (P3a §1): a Windows Firewall rule blocking one program's outbound traffic was accepted by the cmdlet (`PrimaryStatus OK`), listed by `netsh`, present in the registry, and logged as event 2097 "rule added" — and **every one of 37 HTTPS requests by that program returned HTTP 200**. The Windows Filtering Platform dump taken while the rule was in place held **zero** filters for it, across all 2,405 filters. Bitdefender Firewall is registered as a third-party firewall product claiming rule categories BOOT, STEALTH and FIREWALL, which Microsoft's own API description defines as the categories "for which the third-party firewall wishes to take ownership from Windows Firewall". `netsh advfirewall show allprofiles` reported `State ON` throughout.

**Nothing in the normal management surface says the rules are not being enforced.** A product that adds a firewall rule and reports "network restricted" on such a PC is telling the person something false, with every screen agreeing with it.

So the screen carries a row, per fence, with three facts and no softening: **which fence**, **who owns it instead**, and **what it costs the person's chosen profile**. The detection is cheap and deterministic — read `INetFwProducts` (the `HNetCfg.FwProducts` component object) and treat a non-empty list as *seam not owned*. Windows Security Center is **not** a substitute: on this machine it still lists a McAfee firewall and antivirus as enabled whose executable path no longer exists (MEASURED).

The same row shape serves every other fence the product may or may not own on a given PC: process isolation (AppContainer works from user mode with nothing installed, MEASURED — but it costs the agent the person's files, credentials and tools, which is right for an unknown agent and wrong for a coding agent); after-the-fact observation (needs administrator rights at every session start and wrote 290 MB per minute at the keywords tested, MEASURED); and the agent-protocol filter contract `com.microsoft.windows.ai.mcpFilter`, which **exists on this machine with Microsoft Defender as its only registrant** (MEASURED by the study's OS-seam probe). That last one is the most important row the screen may ever carry, because it is the difference between a third party being allowed to be the authorising component on Windows and only being allowed to watch. Today, on this machine, the contract exists and someone else holds it.

---

# 7. Sources

## Files read on this machine (read-only; nothing written outside the scratch directory)

- `C:/Users/mrbla/BlarAI/docs/research/runtime-action-governance-product-concept-spec-2026-09-17.md` — personas, S1–S8, R14–R16, non-goals, success measures.
- `C:/Users/mrbla/BlarAI/docs/research/runtime-action-governance-product-feasibility-brief-2026-09-17.md` — "What the product must include" (R1–R13), Q3, Q3a, Q4, the framing-bias paragraph.
- `C:/Users/mrbla/BlarAI/shared/schemas/car.py` — the CAR: fields, `ActionVerb`, `Sensitivity`, `canonical_hash()` at line 112, `is_complete()`, `DecisionArtifact`.
- `C:/Users/mrbla/BlarAI/docs/research/acs-vocabulary-adoption-design-2026-09-16.md` — the eight intervention points, the three-valued verdict, reserved reasons, the receipt field table, the five-step approval binding, the MIT `LICENSE.acs`.
- `C:/Users/mrbla/BlarAI/docs/research/cava-vs-microsoft-agent-framework-vs-blarai-trust-spine-2026-09-16.md` — the CAVA schema field list, gaps A/B/C, proposed item 4 (extend the CAR).
- `C:/Users/mrbla/BlarAI/services/assistant_orchestrator/src/egress_envelope.py` — the per-turn lease: `begin_turn`/`gate`/`end_turn`, the latched-denied flag, fail-closed on a missing envelope, `request_egress_fingerprint`.
- `C:/Users/mrbla/BlarAI/docs/research/runtime-action-governance-landscape-2026-09-16.md` — item 15, the Auditability Card's six questions; the rejected list; the note that the identity of OWASP's Agent Control Standard with the Microsoft Agent Control Specification is an inference.
- `…/scratchpad/study/reports/P1-hooks.md` and `…/probes/p1/hook-payloads.jsonl` — the verbatim PreToolUse payload, runs a1–e1 and d2, the timing tables, the escape list.
- `…/scratchpad/study/reports/P3a-network.md` §1–2 — the firewall ownership finding.
- `…/scratchpad/study/reports/P3b-os.md` — ETW observation limits, AppContainer, Windows Hello and TPM signing latencies.
- `C:\Users\mrbla\.copilot\pkg\win32-x64\1.0.3\` — `definitions/explore.agent.yaml`, `definitions/task.agent.yaml`, `definitions/code-review.agent.yaml`, `copilot-sdk/docs/agent-author.md`, and a read-only string scan of `app.js` (ARTEFACT).

## Own measurements taken for this report (2026-09-17, read-only PowerShell)

Presence check of inventory targets (`Test-Path` on 19 paths), `cmdkey /list` **counted only** (15 targets; no target names or values recorded), `Get-Volume` (2 fixed, 0 removable), `Get-NetAdapter` (2 up), `Get-PnpDevice` (2 cameras, 1 microphone input). No machine state changed; nothing installed; nothing sent.

## URLs read (all 2026-09-17)

- `https://modelcontextprotocol.io/specification/2025-06-18/server/tools` — the untrusted-annotations warning, verbatim.
- `https://raw.githubusercontent.com/modelcontextprotocol/modelcontextprotocol/main/schema/2025-06-18/schema.ts` — the `ToolAnnotations` interface and its four defaults, verbatim.
- `https://github.com/GenAI-Security-Project/agent-control-standard` — Apache-2.0 for code and schemas, CC BY-SA 4.0 for documentation; the five dispositions; the repository's own statement that "The default failure posture is fail-open".
- `https://raw.githubusercontent.com/OndCo/CAVA/main/packages/cava-core/src/schema.js` — required `runtime`, `operation`, `category`, `systems_touched`, `reversible`; optional `adapter`, `executable`, `target`, `subject`, `metadata`.
- `https://raw.githubusercontent.com/OndCo/CAVA/main/LICENSE` — Apache License 2.0.
- `https://learn.microsoft.com/en-us/defender-endpoint/controlled-folders` — **ms.date 2026-07-02** — CFA modes including Audit Mode, allowed-apps path and wildcard rules, the notification text, the automatic trust-by-reputation statement.
- `https://learn.microsoft.com/en-us/defender-endpoint/configure-notifications-microsoft-defender-antivirus` — **ms.date 2026-08-12** — "Suppress all notifications", "Suppresses reboot notifications", "Turn off enhanced notifications", and the carve-out for critical notifications.
- `https://support.microsoft.com/en-au/windows/protection-history-in-the-windows-security-app-f1e5fd95-09b4-46d1-b8c7-1059a1e09708` — what Protection History shows, the **two-week** retention, the per-entry actions including restore.
- `https://www.bitdefender.com/consumer/support/answer/2062/` — the five Bitdefender Profiles and automatic activation.
- `https://www.bitdefender.com/consumer/support/answer/2103/` — the Notifications area and its three severities.
- `https://www.bitdefender.com/consumer/support/answer/130706/` and `…/answer/13427/` (via search result summaries) — Advanced Threat Defense exceptions accept `.EXE` only; antivirus exclusions by file, folder and extension.
- `https://help.eset.com/eis/16.2/en-US/idh_config_gamer.html` — Gamer mode: pop-ups disabled, scheduler stopped, protection still running, the orange warning, automatic start on full-screen applications.
- Norton Silent Mode / Quiet Mode / Full Screen Detection and the Edit Apps list, and Malwarebytes Play Mode ("Suspend notifications and updates when selected apps are open", on by default, deferred notifications) — from vendor support search-result summaries; the two direct page fetches attempted returned 404 or a page that did not contain the definitions.

## Not verified — the honest list

1. **Whether BlarAI's live dispatch path hashes argument *values* or an argument *schema*.** `car.py`'s docstring says `parameters_schema` holds "not the values — the schema"; the comparison document says the dispatch check builds the CAR from "the tool name plus the canonical JSON of its arguments". I did not read `services/assistant_orchestrator/src/entrypoint.py`. §1.2 flags this; it must be settled before `args_hash` is specified as an extraction of BlarAI code.
2. **Whether a Claude Code `Task` subagent's own tool calls fire `PreToolUse`.** Not measured. The `Task` row in §1.4 is `unknown` for that reason, and if subagent calls *do* fire, the row improves. If they do not, `Task` is an unbounded hole in an otherwise governed agent and it is the single most important follow-up probe.
3. **Every Copilot CLI mapping is from the shipped bundle, not from a run.** The account's Copilot policy refused the CLI (P1 §B). The tool names, the payload shape and the fail-open behaviour are artefact-read; none was exercised.
4. **Bitdefender's consumer monthly/security report** — the pages found were the business GravityZone reporting documents. Whether the consumer product has a periodic report, and what it contains, is not established. Bitdefender is installed on this machine, but reading its interface would mean taking the screen, which the study's rules forbid.
5. **Norton's exact Silent Mode duration and its auto-off behaviour** — the two pages fetched did not contain the definitions; the distinction between Silent Mode and Quiet Mode is from search-result summaries of Norton's own support pages, not from a page read end to end.
6. **The MCP specification's own licence** was not checked; only its schema was read.
7. **The identity of OWASP's Agent Control Standard with the Microsoft Agent Control Specification** is not established — the landscape document already records it as an inference, and the two shapes differ (16 hooks and five dispositions against eight points and three verdicts). This report borrows names from both and treats them as two sources, not one.
8. **`com.microsoft.windows.ai.mcpFilter`** — the filter contract's existence and Microsoft Defender's sole registration are MEASURED by the study's OS-seam probe and relayed to this agent; I did not run that probe myself and did not read the contract's interface definition.
9. **Nothing in §2 was parsed by a real TOML parser.** The three profiles are drafts; the constraint that `unclear_action` rejects `"allow"` is a design rule, not an implemented check.
10. **No profile, prompt or screen has been shown to a person.** Everything about readability is my judgment. Q16 (the first user) is the test that would settle it, and it has not been run.
