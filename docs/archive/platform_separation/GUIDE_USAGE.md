# Guide — Usage (Lead Architect Only)

This is the only LA-facing doc for the Guide. The agent never reads it.

The Guide's operating prompt lives at [`GUIDE_PROMPT.xml`](GUIDE_PROMPT.xml) — single audience (the agent), pure XML, do not paste it into chat as instructions; attach it.

## Starting a Guide chat

1. Open a fresh VS Code Copilot chat in the BlarAI workspace. Pick Claude Sonnet 4.5+ or equivalent.
2. Attach **two** files:
   - `docs/platform_separation/GUIDE_PROMPT.xml`
   - `docs/platform_separation/STATUS.md`
   - (If activating a successor instance, also attach `docs/platform_separation/GUIDE_HANDOFF_LATEST.md`.)
3. Paste the chat-init block below verbatim. Send.

## Chat-init block (copy-paste)

```xml
<initiate_guide>
  <role>You are the Platform Separation Guide.</role>
  <attached_files>
    <file>docs/platform_separation/GUIDE_PROMPT.xml</file>
    <file>docs/platform_separation/STATUS.md</file>
  </attached_files>
  <instruction>
    Read GUIDE_PROMPT.xml in full. Adopt it verbatim as your operating
    instructions. No handoff brief is attached, so you are instance 1 — run
    Variant A of the &lt;comprehension_gate&gt; before answering anything else.
  </instruction>
</initiate_guide>
```

For a **successor** instance, replace the inner `<instruction>` and add the handoff file to `<attached_files>`:

```xml
<initiate_guide>
  <role>You are the Platform Separation Guide (successor instance).</role>
  <attached_files>
    <file>docs/platform_separation/GUIDE_PROMPT.xml</file>
    <file>docs/platform_separation/STATUS.md</file>
    <file>docs/platform_separation/GUIDE_HANDOFF_LATEST.md</file>
  </attached_files>
  <instruction>
    Read GUIDE_PROMPT.xml in full. Adopt it verbatim as your operating
    instructions. A handoff brief from the predecessor instance is attached —
    run Variant B of the &lt;comprehension_gate&gt; before answering anything else.
  </instruction>
</initiate_guide>
```

## What the Guide will do first

It will produce a structured briefing (sections A–I for instance 1, A–F for successor) and end with a hard-stop line. You then ask it whatever you need.

## What the Guide will NOT do

- Edit, create, or delete files
- Run mutating commands or commit anything
- Generate Executor / EA prompts (the 7 stage XMLs are the Executors)
- Touch Vikunja write tools
- Touch the fleet pause state

For any of those, open a separate Executor chat — attach the relevant `NN_STAGEN_*.xml` plus `STATUS.md` and tell it `Execute this stage prompt.`

## When to retire the Guide

The Guide self-monitors and will say `**HANDOFF RECOMMENDED — <reason>.**` when it hits any handoff trigger. When it does, reply `emit handoff`. It will produce a Markdown brief; save that as `docs/platform_separation/GUIDE_HANDOFF_LATEST.md` (overwrite previous), then start a successor chat using the successor variant above.

## Reviewing an EA comprehension gate

When an Executor produces its comprehension-gate summary in its own chat, paste that summary into the Guide chat and say "review this EA gate". The Guide will return a `<guide_review_response>` XML block you paste back to the Executor. See `<ea_comprehension_gate_review>` in `GUIDE_PROMPT.xml` for the full protocol.
