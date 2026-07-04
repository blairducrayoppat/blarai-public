# Engagement comment draft — to post on openvino **issue** #35641

**Status**: Draft **v5** for LA review. **Not** posted by Guide. LA reviews, edits if needed, posts via webUI.

**Paste-ready clean file (for copying without chat-rendering artifacts)**:
`engagement-comment-PASTE.md` in this same directory. Open it in VS Code,
select all, copy, paste into the GitHub comment box.

**Target**: https://github.com/openvinotoolkit/openvino/issues/35641 (issue — comment goes on the issue)

**Word count**: ~510 words. Length is signal density (data block + IR
fingerprints + NNCF detail). v5 over v4 is a tone pass, not a content cut.

**@-mentions**: three direct replies — `@Zulkifli-Intel`, `@diego-villalobos`,
`@dmfallak`. Each is contextual and addresses their specific contribution.

## Version history

- **v1** (commit `7702dba`): authored on the false premise that #35641 had received zero Intel responses. WebFetch missed three comments.
- **v2** (commit `7295427`): rewritten to address all three commenters and commit to retest 2026.1.0. Still a promise, not data.
- **v3** (commit `d2b535c`): rewritten with actual retest data. Refuted Diego's no-repro on Lunar Lake. Word count 291.
- **v4** (commit `835f0db`): mature-not-minimal pass — added representative stdout, IR fingerprints, NNCF bitwidth, deeper AI Assistance disclosure, restructured timings as a table. Word count 490.
- **v5** (this file): tone pass. LA flagged that v4 read as confidently declaring what is/isn't correct (e.g., *"proposes the right pattern"*, *"the separable defect"*, *"the plugin could surface as an actionable exception"*). Those framings are above our domain expertise — the retest data is ours; what the correct fix shape is is Intel's call. v5 keeps data confident, softens interpretive sections to defer to Intel.

## What changed v4 → v5 (tone pass)

| v4 phrasing (declarative) | v5 phrasing (deferential) | Why |
|---|---|---|
| "the failure mode has shifted slightly — the NPU plugin loads/compiles the unsupported graph without complaint and only fails during kernel execution" | "the `CONSTRUCT_OK` line prints in ~17–18s before the process exits, so on this version the failure appears to occur after pipeline construction completes. The actual call site for the access violation is for the team to determine." | "Without complaint" framed Intel's code negatively. v5 describes what we observe and explicitly leaves the actual call site to Intel. |
| "This is the **separable defect** — undefined behavior on an unsupported configuration that the plugin **could surface as an actionable exception at load time**." | "INT8 weight-only being outside the documented NPU LLM matrix is useful framing regardless of where the crash originates. If a clearer signal at load time (a warning, an exception, or sharper docs) would help users avoid this configuration..." | v4 declared what the defect is AND what the plugin should do. v5 validates Diego's framing and offers three alternative shapes (warning / exception / docs) for whoever owns it to choose. |
| "PR [#34651](...) — same plugin file, same `Plugin::compile_model` layer — **proposes the right pattern**" | "PR [#34651](...) takes a similar approach in the same plugin file (`Plugin::compile_model`) for a different unsupported case. **Whether that pattern fits here is for the team to judge.**" | v4 declared #34651 to be THE right pattern. v5 cites it as a reference point and explicitly defers the fit question. |
| "Would the team prefer (a) extending PR #34651 ..., (b) a separate companion PR ..., or (c) deferring ...? I'm happy to follow whichever direction works best." | "If it would be useful, I'm happy to contribute in whatever shape fits your plans — extending PR #34651, opening a small companion PR following a similar pattern, providing more diagnostic captures, or simply standing by while the dev team investigates. No preference from this end." | v4 framed the ask as a menu we were asking Intel to pick from. v5 frames it as us offering help if useful, without implying Intel needs to choose from our list. |
| "**Result: crash still reproduces deterministically — 3/3 NPU runs.**" | "In this environment, the crash still reproduces deterministically across 3/3 NPU runs." | Just slightly less proclamation-y. Data is the same. |

Data block, IR fingerprints, NNCF bitwidth, AI Assistance disclosure, run table, and per-contributor acknowledgments are unchanged from v4 (those were already correct).

## Comment body (paste-ready, between the rules)

For clean copy/paste, use `engagement-comment-PASTE.md` instead — it has only the body, no LA-facing notes, no rendering ambiguity.

---

Thanks for taking the time to investigate this — @Zulkifli-Intel for the NPU/GPU performance comparison and @diego-villalobos for the 2026.1.0 reproduction attempt.

@diego-villalobos — followed up on your finding by retesting on 2026.1.0. Environment: Intel Core Ultra 7 258V (Lunar Lake) / NPU AI Boost (driver `32.0.100.4724`) / Windows 11 Pro / OpenVINO `2026.1.0-21367-63e31528c62` / openvino_genai `2026.1.0.0-2957-1dabb8c2255`, fresh isolated venv (Python 3.11.9).

In this environment, the crash still reproduces deterministically across 3/3 NPU runs.

Representative stdout (each run produces this pattern through `CONSTRUCT_OK`, then exits without further output, no Python traceback):

```
READY device=NPU ir=...\qwen3-0.6b-int8-ov2026.1
openvino=2026.1.0-21367-63e31528c62-releases/2026/1
openvino_genai=2026.1.0.0-2957-1dabb8c2255
CONSTRUCT_OK elapsed=17.51s
[process exits -1073741819 (0xC0000005) ~3-4s later]
```

NPU run timings:

| Run | Construct | Generate | Exit code |
|---|---|---|---|
| 1 | 17.51s | crashed | `-1073741819` (`0xC0000005`) |
| 2 | 17.78s | crashed | `-1073741819` (`0xC0000005`) |
| 3 | 18.29s | crashed | `-1073741819` (`0xC0000005`) |
| GPU control (same IR) | 5.65s | 0.27s for 16 tokens | `0`, coherent output |

IR fingerprints for verification:

- `openvino_model.xml`: SHA256 `93d053e8d55ccda5d2943510a43b90c440aacd2dee28fe44bd321d92e5507ccb` (2,851,220 bytes)
- `openvino_model.bin`: SHA256 `3fdde9ac20058bbdf364c98dbe3508b8eddffd1d33a0d213d111159f826dc939` (597,735,053 bytes)
- NNCF bitwidth distribution: 100% `int8_asym, per-channel` across 197/197 layers (matches the 2026.0.0 export's distribution).

One observation different from the original 2026.0.0 report: on 2026.1.0, the `CONSTRUCT_OK` line prints in ~17–18s before the process exits, so on this version the failure appears to occur after pipeline construction completes rather than during it. The actual call site for the access violation is for the team to determine.

Could you share which NPU hardware family was tested in your no-repro runs (Meteor Lake, Lunar Lake, Arrow Lake, etc.)? That would help me understand whether what we're seeing on Lunar Lake is silicon-specific or environment-specific.

To your second point: INT8 weight-only being outside the documented NPU LLM matrix is useful framing regardless of where the crash originates. If a clearer signal at load time (a warning, an exception, or sharper docs) would help users avoid this configuration, PR [#34651](https://github.com/openvinotoolkit/openvino/pull/34651) takes a similar approach in the same plugin file (`Plugin::compile_model`) for a different unsupported case. Whether that pattern fits here is for the team to judge.

If it would be useful, I'm happy to contribute in whatever shape fits your plans — extending PR #34651, opening a small companion PR following a similar pattern, providing more diagnostic captures, or simply standing by while the dev team investigates. No preference from this end.

Available on request: the full retest report as a Gist (environment + fingerprints + per-run logs + NNCF detail), the exported IR via download link, Windows Event Viewer fault entries from each crash, or a screen recording of the reproduction.

Separately — @dmfallak, your Meteor Lake `StopLocationVerifierPass` failure does look like a distinct compiler-stage bug; thanks for cross-linking, and filing separately is the right call.

---

**AI Assistance:**

AI assistance used: yes.

AI (Claude, via Claude Code) was used for: drafting this comment, and orchestrating the OV 2026.1.0 retest (creating an isolated venv, installing packages, exporting the IR via `optimum-cli`, authoring and running the minimal `LLMPipeline + generate` repro script, and summarizing the retest into the data block above).

Human validation: All retest commands, exit codes, IR fingerprints (XML + BIN SHA256), NNCF bitwidth distribution, and timing values were captured directly from the test environment on Intel Core Ultra 7 258V (Lunar Lake) with NPU driver `32.0.100.4724`. The exported IR's NNCF distribution was verified against the issue body's original 2026.0.0 export (100% `int8_asym, per-channel`, 197/197 layers). Every claim in this comment was checked against the actual retest log files by the contributor before posting.

---

## Pre-post checklist (LA action items)

- [ ] Open `engagement-comment-PASTE.md` (same directory) in VS Code, select all, copy.
- [ ] **Verify the live state via the API one more time** before posting:
      `https://api.github.com/repos/openvinotoolkit/openvino/issues/35641/comments`
      Confirm no new comments arrived since 2026-05-12 that change the framing.
- [ ] Verify CLA status (see `cla-and-ai-policy-brief.md` — still valid).
- [ ] Paste into the GitHub comment box on https://github.com/openvinotoolkit/openvino/issues/35641.
- [ ] Click "Comment".
- [ ] Append the posted comment URL to `STATUS.md` §E4 (or tell Guide-#11).

## Linked retest artifacts

- Full report: `retest-2026.1-report.md` (this directory) — offer as a Gist if Intel asks.
- Repro script: `repro_int8_npu_2026.1.py` (this directory).
- Per-run logs and IR exports at `C:\Users\mrbla\openvino-test-exports\` (outside the repo).
