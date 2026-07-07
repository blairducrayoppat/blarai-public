# Agent Kickoff — INT8 NPU Issue: Evidence Collection + Mature Draft Revision

**Hand this entire file to a fresh GitHub Copilot chat session in the BlarAI workspace.**

---

## 1. Who I am (the user)

I am the **Lead Architect** of BlarAI — a personal, locally-run, security-first AI system. I am a **non-developer "vibe coder"**: I direct AI agents to design, implement, test, and operationalize software. I do not write code directly and I cannot read code fluently. I make all architectural and product decisions; I rely on you for execution detail.

I need you to:

- Be highly technical, direct, zero fluff. Do not hedge or pad.
- Explain *what* you are doing and *why*, but assume I will not validate code by reading it. The way I confirm work succeeded is by running terminal commands you give me and looking at the output.
- Tell me clearly when you need something from me (a copy-paste, a file path, a yes/no decision) versus when you are working autonomously.
- Manage git for me. I am a git novice. Do not assume I know what `cherry-pick`, `rebase`, `--no-ff`, or `stash pop` mean — but you can use those commands, just narrate what you're doing.
- Stop me if I'm about to do something that will make a mess.

## 2. Why this work matters to me

I am trying to become a **helpful, valuable contributor to the OpenVINO project at Intel**. I have already filed and helped close one substantive issue (#34450 — INT4 NPUW LLVM ABORT, closed completed). I want my filings to:

- Save Intel triagers time, not waste it
- Demonstrate that the report came from someone who tested rigorously before posting
- Match the quality and tone of mature open-source contributors
- Build a reputation for quality so future filings get faster, more substantive engagement

The current draft (`phase2_gates/evidence/issue34450/github_issue_int8_npu_DRAFT.md`, on `main` at HEAD) was reviewed and judged **"above-average minimal but not yet mature."** Your job is to help me close that gap.

## 3. The motto

**Mature, not minimal.** Pre-empt the predictable Intel triage questions in the first post so we save round-trips.

---

## 4. Repo state at session start

- **Workspace**: `c:\Users\mrbla\BlarAI`
- **Sister repo (for fleet ops)**: `c:\Users\mrbla\devplatform`
- **BlarAI main HEAD at handoff**: revision committed by prior session (the draft is at `phase2_gates/evidence/issue34450/github_issue_int8_npu_DRAFT.md`)
- **Active branch when you start**: `evidence/int8-npu-mature-prep` (created by prior session for the kickoff-prompt file you are reading; that branch will be merged before you do anything substantive)
- **Fleet state**: PAUSED by prior session. You will need to verify state and re-pause under your own reason string before starting your evidence-collection work.

**Your first git action**: confirm we're back on `main` after the prior session merges the kickoff-prompt branch. If not, ask me to merge it first.

## 5. Branch strategy for your work

**Yes, create a new branch.** Recommended name: `evidence/int8-npu-mature-revision`.

All evidence-collection commits AND the final draft revision go on that single branch. Merge to main at the end with `--no-ff`, delete the branch, resume the fleet. This is the standard BlarAI cycle.

Do **NOT** commit directly to `main`. Ever.

## 6. Fleet management — MANDATORY

The BlarAI workspace has an autonomous fleet (SDO / Co-Lead / EA Code / Sprint Auditor) that wakes on cron from the **devplatform** repo. If it fires while you are mid-edit, it will auto-stash your work and you will spend time recovering.

**Canonical pause/resume cycle:**

```powershell
# PAUSE — do this BEFORE any file edit or branch checkout
cd C:/Users/mrbla/devplatform
python -c "from tools.autonomy_budget import state; state.pause_fleet('<short reason>', updated_by='copilot_agent', path='C:/Users/mrbla/devplatform/tools/autonomy_budget/state.json')"
git add -A; git commit -m "chore(ops): pause fleet -- <short reason>" --allow-empty
cd C:/Users/mrbla/BlarAI

# ... your work here ...

# RESUME — do this AFTER your final BlarAI merge to main, before signaling done
cd C:/Users/mrbla/devplatform
python -c "from tools.autonomy_budget import state; state.resume_fleet(updated_by='copilot_agent', path='C:/Users/mrbla/devplatform/tools/autonomy_budget/state.json')"
git add -A; git commit -m "chore(ops): unpause fleet -- <reason> done" --allow-empty
cd C:/Users/mrbla/BlarAI
```

**Important**: the function is `resume_fleet`, NOT `unpause_fleet`. Calling `unpause_fleet` raises `AttributeError`.

**At session end** (before you tell me you're done), verify:
- `git status` (clean)
- `git stash list` (only pre-existing `chore/platform-extraction` stashes — do not touch those)
- `git branch -a` (your feature branch deleted)
- `git log --oneline -5` (merge commit present)
- `tools/autonomy_budget/state.json` shows `"fleet_paused": false`

Leaving the fleet paused at end of session is a process failure.

---

## 7. Comprehension Gate — DO THIS FIRST

Before any tool call, present me a structured summary covering:

1. **Your understanding of the objective** in your own words (one paragraph).
2. **The list of evidence-collection actions** you'll walk me through, in order, with a one-line description of each (don't include commands yet — just what each action accomplishes).
3. **What you need from me at each step** (am I copy-pasting from Event Viewer? running a script? approving a registry change?).
4. **Files you will create or modify**, with paths.
5. **Any risks or ambiguities** you see.
6. **Estimated total wall-clock time** for the session.

**Then STOP and WAIT for me to approve.** Do not start writing code, creating branches, or running terminal commands until I say go.

---

## 8. The work — overview

### Phase A — Evidence collection (I run things; you tell me what to run and where to put output)

Goal: close the eight maturity gaps identified in the prior review.

| # | Gap | Action |
|---|-----|--------|
| 1 | Native crash diagnostic missing | Open Windows Event Viewer → Application log → grab the `python.exe` Application Error entry. You tell me exactly where to click and what to copy. |
| 2 | No crash dump captured | Walk me through enabling WER LocalDumps via registry (one-time), rerun the NPU repro, capture the `.dmp` from `%LOCALAPPDATA%\CrashDumps\`. We do NOT attach the dump to the GitHub issue — we keep it local and offer it on request. |
| 3 | Log-level matrix not enumerated | Rerun the NPU repro under each of: `OPENVINO_LOG_LEVEL=5`, `OV_NPU_LOG_LEVEL=5`, both. Capture each stdout/stderr to a separate log file. |
| 4 | Determinism not stated | Rerun the NPU repro 3× consecutively. Confirm same exit code each time. |
| 5 | Prefill-vs-decode scope not stated | Rerun the NPU repro with `--tokens 1`. Does it still crash? |
| 6 | OpenVINO install source not stated | Confirm whether our `2026.0.0` came from PyPI wheel, Intel archive, or source. (You can grep/inspect `pip show openvino` and `pip show openvino-genai` for me.) |
| 7 | NPU + GPU driver currency unknown | I'll check the Intel ARC and AI Boost download pages and tell you the latest available versions. You note any delta from installed. |
| 8 | Skip second-INT8-model test for v1 | Per prior decision. Note as open-question in final draft. |

**Existing artifact directory**: `phase2_gates/evidence/issue34450/`. New files land there. Suggested filename pattern: `cell_i_<purpose>.log`, e.g., `cell_i_npu_logged_ovlevel5.log`, `cell_i_npu_run3_determinism.log`.

**Existing reproducer**: `repro_int8_npu.py` (cited in the draft). Use it as-is — do not modify.

**Commit cadence during Phase A**: commit each evidence file as it's captured, with a clear message (e.g., `evidence(issue34450): capture OPENVINO_LOG_LEVEL=5 NPU run`). This gives me a clean per-step audit trail.

### Phase B — Draft revision

After all Phase A evidence is collected, revise `phase2_gates/evidence/issue34450/github_issue_int8_npu_DRAFT.md` to:

- Add the Event Viewer faulting-module info to **Actual behavior**
- Add a "Diagnostics attempted" subsection enumerating the log-level matrix and what each yielded (or didn't)
- Add deterministic-across-N-runs statement
- Add prefill-vs-decode scope statement
- Add `--tokens 1` result
- Tighten environment table to include OpenVINO install source and a precise GPU driver version string (replace the "latest WHQL at 2026-04-25" hand-wave)
- Add NPU driver currency statement ("X.Y.Z is the latest publicly available as of <date>" or "newer driver A.B.C exists, not yet tested")
- Add one-line acknowledgment in **Suggested resolution** that if INT8 weight-only is on the NPU roadmap, the underlying defect is the silent-construct → uncatchable-native-crash transition, not the lack of INT8 support
- Replace the "Happy to re-run" closer with a statement that the obvious extra log levels have been run and reported above
- Update **Evidence on file** inventory with new artifacts

Commit as one revision commit with a message listing the eight gap closures.

### Phase C — Merge + verify + resume

- `git checkout main`
- `git merge --no-ff evidence/int8-npu-mature-revision -m "Merge evidence/int8-npu-mature-revision: mature evidence + draft revision for INT8 NPU issue"`
- `git branch -d evidence/int8-npu-mature-revision`
- Resume fleet (see §6)
- Run end-of-session verification block (see §6)
- Tell me the draft is ready to post and give me the file link

---

## 9. OpenVINO project posting guidelines (for the eventual post)

When the time comes (I will post manually — you have no GitHub write access), here are the conventions, verified against recent issues in `openvinotoolkit/openvino`:

- **Title prefix**: reporter sets `[Bug][NPU]` (or `[Bug]:[NPU]`, `[Bug]: NPU:`, all attested). Intel staff add the workflow labels (`category: NPU`, `support_request`, `PSE`) on triage — do not try to set those yourself in the title.
- **Suggested labels at submit time**: `category: NPU`, `bug`, `support_request` (you can request these in the submit form; Intel may adjust).
- **AI Usage Policy disclosure**: MANDATORY. The current draft has it as the closing section. Do NOT remove it. Any further revisions you do must preserve it verbatim or with only minor wording tweaks. Intel's policy requires this disclosure for AI-assisted issue bodies.
- **Cross-references**: link prior related issues by `#NNNNN` (we already cite #34450 and #34617).
- **Tone**: factual, dispassionate, evidence-anchored. No advocacy ("this is important because…"), no editorializing about user UX, no requests framed as demands. Suggested resolution should be one option, neutrally proposed.
- **Reproducer**: subprocess-isolated when the failure is a native crash (we already have this). Include the full source inline in a code block — do not link to an external repo.
- **Evidence**: list available artifacts under "Evidence on file" with a brief description of each. Do not attach files to the initial post; attach on request after Intel confirms which they want.
- **Account**: posting will be from `blairducrayoppat`.

## 10. General GitHub mature-contributor norms (in case helpful)

- Search existing issues before filing — we've already done this for #34450 and #34617.
- One issue, one bug. Don't bundle unrelated observations.
- Provide complete reproducer (env, exact commands, exact versions, exact outputs).
- Use fenced code blocks with language hints.
- Cite the docs page that defines expected behavior.
- Do not @-mention specific employees in the opening post (Diego asked us to file separately — that's why he's mentioned in the cross-ref, but the body itself doesn't @-tag).
- Do not threaten escalation, deadlines, or business impact. Intel doesn't owe us SLAs on a free open-source NPU plugin.

---

## 11. Reference materials in the workspace

- **Current draft**: `phase2_gates/evidence/issue34450/github_issue_int8_npu_DRAFT.md`
- **Closed sibling closeout record**: `phase2_gates/evidence/issue34450/github_comment_v3_7_closeout_DRAFT.md`
- **Existing evidence logs**: `phase2_gates/evidence/issue34450/cell_*.log`
- **Existing reproducer**: search for `repro_int8_npu.py` in the same directory or `scripts/`
- **Project conventions**: `.github/copilot-instructions.md`, `CLAUDE.md`, `AGENTS.md`
- **Fleet hygiene authority**: `docs/governance/fleet-hygiene.md` §4

---

## 12. Closing — your first message back to me

Per §7, your first message must be the comprehension-gate summary, then STOP. Do not call any tools (other than read-only ones to verify state if needed) before I approve.

Once approved, you'll work through Phases A → B → C, with frequent stops to hand me the next thing to run/check/copy-paste.

Welcome aboard. Let's make this a mature filing.
