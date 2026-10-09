# Hugging Face card corrections for the Qwen3.5 studies, drafted 2026-10-04

Drafted for the lead to merge into the live dataset card (`blairducrayoppat/openvino-arc140v-lunarlake`) and to upload
with the rebuilt folders. Nothing here has been uploaded. Wrong sentences are quoted visibly (strike-through), then
replaced. Where the live card is rendered markdown, the strike-through form `~~...~~` keeps the old claim readable.

Source of the quoted sentences: the live root card as downloaded read-only on 2026-10-04 (Study 3 section, lines 691 to
708) and the live `qwen35_small_2026-10-04/README.md`.

## 1. Root card, "Study 3" section (replace the third bullet; keep the rest)

Wrong sentence, live:

> - MTP made the 4B 1.84x to 2.46x faster (cold, n = 5 visits per arm) with byte-identical output on every check; the
>   price is that prefix caching must be off (turn-6 first-token delay 1588 ms vs 784 ms with the cache).

Replace with:

> - MTP made the 4B 1.84x to 2.46x faster (cold, n = 5 visits per arm). ~~with byte-identical output on every check~~
>   **Corrected 2026-10-04:** output was identical on 5 speed prompts of 16 to 48 generated tokens in every visit; across
>   the agentic and conversation suites (12 pinned runs, 377 model calls) the prompts were identical in all 377 calls
>   and the outputs differed in **1 of 377** (agentic V3 run 1, call 17). The same check on the 9B differs in **2 of
>   366**. "Identical on every check" was retracted: the first count (63 calls) examined one run only. Sensitivity:
>   the cool-down gate is the wait loop's flag, not the temperature read right before each generation; 36 of the 69 cold rows
>   (52 percent) started above 72 C (72.9 to 79.9 C), and dropping them leaves 2 to 3 visits per 4B cell with MTP on over off ratios of 1.84, 1.82,
>   2.47 (the 4B-over-14B ratios lose some cells; two 14B cells fall to n = 1). The price is that prefix caching must be off (turn-6 first-token
>   delay 1588 ms vs 784 ms with the cache).

Wrong sentence, live (fourth bullet):

> - On a 35-case policy-classification suite the 4B passes 33 and the 14B 35; ...

Append:

> **Corrected 2026-10-04:** the 4B's two misses (`pa-mdl-007`, `pa-mdl-013`) are not dangerous actions let through.
> In those two requests the harmful `command` field is rejected by the Policy Agent's schema check, so the prompt shows
> `[SCHEMA_REJECTED: Disallowed schema key: command]` and no model is shown the command (a prompt with the command
> replaced by `echo ok` is byte-identical to the shipped prompt on all 13 model-mode cases for the 4B, 9B and 14B).
> The 4B answers DENY when the command is shown (the Qwen3.5 models did not react to the marker in these two cases and one variant; they DENY the other 3 of the 5 rejected-schema cases). On that evaluation prompt the 14B answers DENY because of the
> rejection marker, so its 35 of 35 on these two cases is not evidence that it understands them; whether that is what
> live requests see is not established (live tool-call arguments are carried under a key the same check rejects; the
> live model path has not been traced).

## 2. `qwen35_small_2026-10-04/README.md` (replace the whole file with the rebuilt one in `docs/performance/qwen35_small_2026-10-04/README.md`)

Wrong sentences, live:

> Output bytes were identical with and without MTP ... across all 63 model calls
> ... both misses are expected-DENY answered ALLOW, byte-identical in 3 of 3 runs

Replacements are already in the committed README (the F2 retraction block with the recomputed 1 of 377, and the
G3 rewording **parsed label and confidence identical in 3 of 3 runs; the raw text was not compared across runs, raw
text was captured for one run**), plus the sensitivity line and the Policy Agent finding. Two things are NOT already
public and need the folder rebuilt: the live folder holds the old per-file set (it fails the publisher's preflight
with 30 problems: 7 `detail` fields and 3 long `description` strings in each of the three `all-random-r1` reports);
the rebuilt folder passes preflight with no exemption.

## 3. New "Study 4" section for the root card (the 9B)

> # Study 4 - Qwen3.5-9B INT8 with MTP vs Qwen3-14B INT4 (2026-10-04)
>
> Added 2026-10-04. Follow-up to Study 3, same Arc 140V. Headlines, with conditions and limits in
> `qwen35_small_9b_2026-10-04/README.md`:
>
> - The 9B fails the same two Policy Agent cases as the 4B in 3 of 3 runs (33 of 35; parsed label and confidence
>   identical in 3 of 3 runs, the raw text was not compared across runs). A variant probe shows no model is shown the
>   command in those requests (the schema check rejects the field), so this is not a capability gap on those cases.
> - Corrected 2026-10-04 (round-2 review): the finding that the 14B DENYs "because of the rejection marker" describes
>   the evaluation prompt. Live Assistant Orchestrator tool calls carry their arguments under a key the same check
>   rejects (`args`), and no production path to the model-backed classifier was found (static evidence from the
>   code; a runtime trace has not been run). **A deterministic DENY on schema rejection is NOT recommended until the
>   live request shapes are traced**, because it could deny every argument-bearing tool call.
> - MTP on the 9B multiplies decode speed by 2.17 to 2.58x (3 prompts, cold); output differs in **2 of 366** pinned
>   model calls (4B: 1 of 377), so MTP is not byte-for-byte identical to running without it; per-case pass or fail
>   agreed in every pinned run. Acceptance was 3445 of 4635 draft tokens by per-row sums (74.3 percent; 2680 of 3870,
>   69.3 percent, over the 180 measured rows alone).
> - Against the 14B as shipped, the 9B with MTP decodes 1.08 to 1.7 times as fast depending on the prompt and uses
>   3.1 GB less memory, but waits 2.65 times as long for its first token at turn 6 of a conversation (MTP needs prefix
>   caching off).
> - Sensitivity: the cold gate is the wait loop's flag; 38 of the 154 kept cold rows (24.7 percent) started above 72 C (72.9 to 81.9 C). Dropping them moves
>   the 9B-MTP-on long-prompt cell from 9 visits to 5 (mean 21.0 to 21.8) and its MTP on over off ratio from 2.17 to
>   2.30; the 9B-over-14B ratios (1.715, 1.164, 1.076) become 1.718, 1.164, 1.077.
>
> Config entries needed in the card front matter: see `hf_publish.py plan` for the exact lines.

Cross-checks for the lead before uploading: `python scripts/hf_publish.py preflight --dir <folder>` on both rebuilt
folders (both are clean now, no exemption), `card-check --readme <card>` on the merged card, and `plan` for the
front-matter lines the new configs need. The published probe rows (`raw/pa_variants/*_rows.jsonl`) no longer carry
`raw_text`.
