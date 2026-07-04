# Follow-up comment draft for npu_compiler PR #266

**Status**: Draft v1 for LA review. **Not** posted by Guide. LA reviews, edits if needed, posts via webUI.

**Paste-ready clean file**: `pr-npu-compiler-266-follow-up-PASTE.md` in this same directory (companion file). Open in VS Code, select all, copy, paste into the GitHub comment box.

**Target**: https://github.com/openvinotoolkit/npu_compiler/pull/266 (PR — comment goes on the PR conversation thread)

**Word count**: ~135 words. Intentionally short. The original technical content from 2026-04-17 is already in the thread; this comment exists only to re-surface the two open threads, not to re-litigate them.

**@-mentions**: two — `@andrey-golubev` (re-surface the IR-dumping question), `@DariaMityagina` (confirm the LIT test). Each is contextual.

## Draft rationale

After 25 days of no reviewer response on a CHANGES_REQUESTED PR with
substantive open questions, one polite, well-spaced follow-up is
appropriate. It signals continued interest without being naggy.

Tone discipline (matches the v5 lessons from #35641):
- No declarations about what's "the right" approach (we don't know).
- No critique of the wait time ("you haven't reviewed in 25 days" is
  not a thing we say).
- Specific, scoped questions — easier to answer than open-ended pings.
- Acknowledges that delay is fine ("happy to wait if other items have
  priority").
- AI Assistance disclosure included (per OpenVINO AI Usage Policy —
  applies to comments on PRs as well as PR descriptions).

## Comment body (paste-ready, between the rules)

For clean copy/paste with no markdown rendering artifacts, use
`pr-npu-compiler-266-follow-up-PASTE.md` (paste-only sibling file).

---

@andrey-golubev — checking in on the IR-dumping question from my April 17 reply: which env vars or compiler flags let me capture the IR after each pass in the NPU pipeline, so I can identify where the zero-dim shape is introduced? I'd like to follow your direction toward a root-cause fix, but I haven't been able to find the right knob from outside the project. Happy to wait if other items have priority — just want to make sure you have what you need from me to keep this moving.

@DariaMityagina — also flagging: I added the LIT test you requested at `tests/lit/NPU/dialect/IE/passes/unroll_fully_connected_zero_dim_guard.mlir` in commit `c5f9266`. Let me know if it's structured the way you'd want, or if it needs adjustments.

---

**AI Assistance:** AI assistance used: yes — Claude helped draft this follow-up comment. No new technical investigation was performed for this comment; all referenced material (commit SHA, test path, IR-dumping question) is from the April 17 conversation already on this PR.

---

## Authoring choices (LA-facing notes — do NOT post)

1. **Two @-mentions, each addressing a specific pending thread.** Not a generic ping. Andrey gets the IR-dumping question re-surfaced; Daria gets a confirmation request on the LIT test.
2. **Short.** ~135 words. The technical content from the April 17 exchange is already in the thread; this comment doesn't re-explain it.
3. **No mention of the 25-day delay.** Not a complaint vehicle.
4. **"Happy to wait if other items have priority"** — explicitly de-escalates urgency. Common Intel-engagement etiquette.
5. **"I'd like to follow your direction toward a root-cause fix"** — affirms Andrey's architectural framing rather than relitigating "defense-in-depth is OK."
6. **AI Assistance disclosure trimmed** vs. the #35641 comment — this follow-up didn't involve new test execution or retest, so the disclosure is one short sentence rather than the three-section format. Honest about scope of AI involvement.
7. **No reference to #265.** That PR has the same outstanding question but pinging both at once for the same person would be noisy. Andrey's answer here applies to both.

## Pre-post checklist (LA action items)

- [ ] Open `pr-npu-compiler-266-follow-up-PASTE.md` (same directory) in VS Code, select all, copy.
- [ ] **Verify the live state via the API one more time** before posting:
      `https://api.github.com/repos/openvinotoolkit/npu_compiler/issues/266/comments`
      Confirm no new comments arrived since 2026-05-12 that change the framing.
- [ ] Paste into the GitHub comment box on https://github.com/openvinotoolkit/npu_compiler/pull/266.
- [ ] Click "Comment".
- [ ] Append the posted comment URL to the Vikunja "Shepherd: PR #266" ticket comment thread.

## Companion file

`pr-npu-compiler-266-follow-up-PASTE.md` — body-only, clean copy/paste.
