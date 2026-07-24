# injection_corpus fixtures (#1004)

Static prompt-injection **technique** strings, extracted verbatim from
promptfoo's red-team prompt-injection strategy data, for use as adversarial
test **inputs** against the BlarAI Policy Agent and the untrusted-content path
(datamarking, spotlighting, provenance tiering, the `UNTRUSTED_KNOWLEDGE`
tier). These are attack strings exercised against a control **we own, on our
own machine**. No third-party service is involved, and nothing here runs, is
imported by the runtime, or reaches the network.

## What this is

- `promptfoo_injection_corpus.json` — the corpus: a top-level `provenance`
  block, pinned `counts`, a `content_sha256` integrity pin, and a `templates`
  array. Each entry carries `id`, `source_index` (its position in the upstream
  array), `technique`, `has_placeholder`, `placeholder_count`, `byte_length`,
  and the verbatim `template` text.
- `LICENSE.promptfoo` — promptfoo's MIT license, verbatim.
- `NOTICE.md` — both required attribution notices (promptfoo MIT + the Protect
  AI / `llm-guard` MIT notice that upstream itself reproduces).

## Exact provenance (pinned)

| field | value |
|---|---|
| repo | `github.com/promptfoo/promptfoo` |
| path | `src/redteam/strategies/promptInjections/data.ts` |
| commit | `e8fc168b60eb73702f4ab543f694d5a230e7cd7f` |
| blob sha | `b3e8383667ee3fbe2dd14248d354c75b7a6ef82f` |
| source bytes | 232,021 |
| extracted | 2026-07-21 |

Upstream ships the corpus as `export default [ ... ]` — a flat array of string
literals. Extraction evaluated that module with Node and serialized the
resulting array to JSON with **no transformation of the template text**. The
`content_sha256` in the fixture is a SHA-256 over every template in source
order (NUL-joined); the integrity test pins it, so any silent edit or reorder
fails loud.

## Count: 106 templates — and a correction to the origin premise

Ticket #1004 (and the upstream advertising) describe this as "a flat array of
prompt-injection templates **each carrying a `__PROMPT__` placeholder**,
~70–75 entries." The source as pinned actually holds **106 entries**, split:

- **74** carry the `__PROMPT__` placeholder (the wrapper templates — substitute
  the token with a payload). This 74 is what matches the ticket's "~70–75."
- **32** carry **no** placeholder: self-contained jailbreak prompts (DAN,
  Developer Mode, STAN, DUDE, "ignore all instructions", persona roleplay,
  hypothetical-framing, entity-splitting word games, the
  `auto_regressive_modelling` code trick). A few embed an inline
  *swap-the-words* instruction instead of the token (e.g. the "hotwire a car"
  hypothetical, which says to replace those words with your task).
- **0** carry more than one placeholder (the ticket guessed some might).

All 106 are prompt-injection **techniques**, so all are in scope for injection
resistance. The `has_placeholder` field distinguishes wrapper templates from
self-contained ones.

## Content scope / what was excluded

A severity scan of the standalone (no-placeholder) entries for genuinely
egregious targets (CSAM, bioweapon/nerve-agent synthesis, etc.) returned **zero
hits** — this corpus is jailbreak *wrappers* and persona attacks, not standalone
harmful payloads. The placeholder templates never get filled with a harmful
string here; they ship with the literal `__PROMPT__` marker intact. **Nothing
was excluded on content grounds.** The corpus does contain the canonical mild
academic demo goal ("hotwire a car") inside a few technique templates; that is
the injection *method*, not a harmful payload, and is retained.

## What was NOT extracted (do not mistake this for the full advertised corpus)

promptfoo advertises much larger attack corpora, but **they are not in the
package** — each is fetched from `raw.githubusercontent.com` or HuggingFace at
plugin runtime (see #998 §6.2): **HarmBench, BeaverTails, Aegis, ToxicChat,
UnsafeBench, VLGuard, and Pliny/L1B3RT4S**. None of those are here, and none
could be extracted as repo-resident static data. This fixture is **only** the
one file that genuinely ships locally: the prompt-injection strategy array.

## Technique tags are a LOCAL heuristic

Upstream ships a single flat array with **no per-entry tags** (its only category
is the strategy id `prompt-injection`). The `technique` field here is a local
keyword classification (`technique_source: "local-heuristic"` on every entry),
added for analysis — it is **not** upstream provenance. The authoritative
upstream coordinate is `source_index`. Entry 0 is tagged `skeleton-key` because
upstream's `index.ts` names the first element the default "skeleton key."
Unmatched entries fall back to `generic-injection`. Do not treat the tag
distribution as a stable contract; the integrity test pins counts and content,
not per-technique tallies.

## Usage contract

- `has_placeholder: true` → substitute every literal `__PROMPT__` with the
  attack payload (upstream `index.ts`: `injection.replace(/__PROMPT__/g,
  prompt)`).
- `has_placeholder: false` → used verbatim.

## Intended consumption

Static adversarial **inputs** for Policy-Agent red-team cases. **Wiring these
into an eval suite (e.g. widening `answer_quality`'s `injection_resistance`
cases) is explicitly NOT this ticket** — #1004 delivers the static corpus, its
notices, and a deterministic integrity lock only. `answer_quality` already
carries 8 `injection_resistance` cases; #1000 gave hardware-tier eval cases
teeth, so model-tier consumers built on top of this corpus will no longer fail
silently at exit 0.

## License

MIT (both promptfoo and the Protect AI material it derives from). MIT permits
use, copy, modification, and redistribution provided the copyright and
permission notices are preserved — which is why `LICENSE.promptfoo` and
`NOTICE.md` travel in this directory. Keep them with the corpus.

## Regeneration (dev-side; reproducible)

Not part of the runtime. To reproduce from source at the pinned commit:

1. `curl` the raw `data.ts` at commit `e8fc168b…` from
   `raw.githubusercontent.com/promptfoo/promptfoo/<commit>/…/data.ts`.
2. Evaluate it as a CommonJS module with Node (`export default` →
   `module.exports =`) and `JSON.stringify` the array.
3. Feed that array to the builder (kept with the #1004 work notes) that stamps
   provenance, classifies techniques, and computes `content_sha256`.

The pins in this README plus `content_sha256` are sufficient to verify any
regeneration byte-for-byte.
