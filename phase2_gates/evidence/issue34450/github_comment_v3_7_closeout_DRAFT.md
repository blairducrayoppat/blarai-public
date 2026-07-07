# GitHub comment v3.7 — closeout reply to @diego-villalobos

**Target:** https://github.com/openvinotoolkit/openvino/issues/34450
**Replying to:** diego-villalobos comment 4345375558 (2 days ago)
**Action after posting:** close the issue.

---

@diego-villalobos — thanks for taking this back to the dev team and for the clear disposition. Confirming the resolution and closing on my end.

**Confirmed.** Per-group asym INT4 on NPU is outside the [documented NPU LLM recipe](https://docs.openvino.ai/2026/openvino-workflow-generative/inference-with-genai/inference-with-genai-on-npu.html), and both failure manifestations on this thread (`StopLocationVerifierPass: 40 duplicated names` on 2026.0.0 / 2026.1.0 and the original `as_convolution` 0-channel `LLVM ABORT`) trace to that same unsupported configuration. Closing the issue.

**Documentation / early-rejection follow-up.** Glad to hear the team is evaluating this as part of the roadmap. The two cheapest user-facing wins from where I sat would be (a) an `optimum-cli export openvino` warning when `--weight-format int4` is selected without `--sym` for an NPU target (the documented recipe requires `--sym` with both `--group-size 128` and `--group-size -1`), and (b) an early `NPUW` plugin rejection with a one-line "use `--sym` per the NPU LLM recipe" pointer rather than deep MLIR pipeline failures. Either alone would have saved days of triage on my end. No urgency — just flagging the leverage points if the team wants concrete starting suggestions.

**INT8 NPU-runtime crash (Cell I).** Will file separately as you suggested. The `0xC0000005` inside the first `generate()` after a clean construct on NPU, with the same IR running end-to-end on GPU, is plainly a different scope. I have the IR, both venv lockfiles, and the verbose logs ready to attach when I open it.

Appreciate the thorough triage from you, @YuChern-Intel, and @Munesh-Intel. Running powerful AI models locally on Intel silicon remains a real passion of mine, so happy to keep contributing reproductions and matrices when I run into other rough edges.

---

*Per [OpenVINO AI Usage Policy](https://github.com/openvinotoolkit/openvino/blob/master/AI_USAGE_POLICY.md):*

```text
AI assistance used: yes
If yes: AI assistants (GitHub Copilot / Claude) helped draft this closeout
  comment and cross-check the disposition against the prior thread evidence
  (5-cell NPUW partition matrix, hypothesis tests Q1/Q2, failure taxonomy)
  posted by the human reporter earlier in this issue.
Human validation performed: the human reporter read @diego-villalobos's
  resolution comment in full, confirmed the per-group asym INT4 disposition
  matches the reporter's own matrix findings (cells G FAIL vs. G-B-sym /
  G-H OK), confirmed the documented NPU LLM recipe link resolves to the
  current 2026 docs page, and confirmed the INT8 (Cell I) crash referenced
  here is the same one captured in the reporter's local evidence pack and
  on-disk logs from the original repro run. The reporter understands every
  claim made here and is the one closing the issue.
```

---

## Pre-post checklist (for the operator)

- [ ] Verify the GitHub account being used is the intended BlarAI account (`blairducrayoppat`).
- [ ] Confirm we are commenting on **#34450**.
- [ ] In the GitHub Preview tab, confirm: `@diego-villalobos`, `@YuChern-Intel`, `@Munesh-Intel` render as user mentions; the docs link renders; the AI Usage Policy disclosure block renders as a code block.
- [ ] Click **Comment**.
- [ ] Then close the issue using **"Close as not planned"** — Diego's disposition is "not actually a bug" / unsupported configuration, so no fix is planned; "not planned" is the semantically correct option. (Plain **Close as completed** is acceptable if you prefer; either is fine.)
- [ ] Copy the resulting comment URL and the close-event URL; archive both alongside this draft.
- [ ] Do not edit the comment after posting.
- [ ] When ready, open the separate INT8 NPU-runtime crash issue and link back to this one in its description.
