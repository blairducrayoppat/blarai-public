# #725 upstream report package — xgrammar stop-token crash

Filing package for the OpenVINO GenAI xgrammar `IsStopTokenAccepted` crash
under speculative decoding. See BlarAI Vikunja #725.

| File | What it is |
|---|---|
| `REPORT.md` | The full write-up: summary, root-cause hypothesis, environment, verbatim error, evidence table, repro instructions, pre-filing checklist, open threads. **Start here.** |
| `xgrammar_standalone_repro.py` | Minimal reproducer — **OpenVINO GenAI only, no app code**. The artifact to attach upstream. |
| `repro_prompts_generic.json` | Generic prompts + generic 2-tool schema + stock system prompt (nothing BlarAI-specific) — proven to crash. Feeds the standalone repro. |
| `app_probe_with_partial_capture.py` | The richer probe (streamed partial capture + spec-decode on/off + `trigger_seen`) used to establish that the `<tool_call>` trigger is NOT a precondition. Imports BlarAI modules — for our records / deeper diagnosis, NOT for upstream attachment. |
| `production_posture_eval_grammar_off.json` | The grammar-OFF control eval (0 generation errors) — evidence, not for upstream. |

**To file:** follow `REPORT.md` §8 (search existing issues first; the operator
is the upstream contributor and owns the filing). Attach only
`xgrammar_standalone_repro.py` + `repro_prompts_generic.json`.
