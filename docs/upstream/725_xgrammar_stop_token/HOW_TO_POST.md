# How to post the #725 upstream issue

The finalized issue body is `ISSUE_BODY_FINAL.md` (this directory). It follows
the OpenVINO GenAI bug-report conventions (bold section headers, numbered
To-Reproduce, self-contained inline repro, pip-freeze-style environment block)
and the embedded script was run verbatim and confirmed to reproduce before this
was prepared.

## Pre-flight checks done (2026-07-05)

- **Duplicate search:** no existing issue covers this. Org-wide, the only match
  for `IsStopTokenAccepted` is PR #2295 (the xgrammar feature itself). Nearest
  issues are different mechanisms (#3675 Eagle3 `stored_seq_len`, #3887
  prefix-cache eagle3, #2817 xgrammar version bump). Re-run one live search
  before posting in case something landed since.
- **Supported-combination check:** OpenVINO docs present structured output and
  speculative decoding as independent, generally-available features with no
  documented exclusion for combining them — so this is not "used something
  unsupported." The issue includes an "Is this a supported combination?" section
  making the point that a hard `CHECK` abort is a defect either way.
- **AI Usage Policy compliance:** OpenVINO's
  [AI Usage Policy](https://github.com/openvinotoolkit/openvino/blob/master/AI_USAGE_POLICY.md)
  applies to issues and requires (a) disclosing significant AI assistance and
  (b) first-hand, reproducible observations. The issue body carries an AI-
  assistance disclosure line, and the observations are all first-hand + verified
  on your hardware. **Owner accountability is yours:** the policy asks the
  submitter to stand behind the report — which here means it is a genuine crash
  on your own machine that you reproduced by running the attached script, and
  the AI drafting is disclosed. You do not need to explain the C++ internals;
  you do need to be comfortable that the crash and repro are real (they are).

You post it (your account `blairducrayoppat` is authenticated). Two ways:

## Option A — one command (recommended)

From the repo root, in this Git Bash shell:

```bash
gh issue create \
  --repo openvinotoolkit/openvino.genai \
  --title 'xgrammar structured output crashes at EOS under speculative decoding: "GrammarMatcher has terminated after accepting the stop token" (grammar_matcher.cc:627)' \
  --body-file docs/upstream/725_xgrammar_stop_token/ISSUE_BODY_FINAL.md \
  --label bug
```

`gh` prints the new issue URL on success. If the `bug` label is rejected
(some repos gate label-setting to maintainers), drop `--label bug` and re-run —
a maintainer will triage the label.

## Option B — web form

Run `gh issue create --repo openvinotoolkit/openvino.genai --web` to open the
new-issue page in your browser, then paste the title and the contents of
`ISSUE_BODY_FINAL.md`.

## After posting

1. Paste the issue URL back here (or into Vikunja #725) so I can record it on
   the ticket and set the re-enable criterion to reference the upstream thread.
2. If a maintainer asks for a two-small-public-model repro or a specific
   config, I can run it on this box the same day.
