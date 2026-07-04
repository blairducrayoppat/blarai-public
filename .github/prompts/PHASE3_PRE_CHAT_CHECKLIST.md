# Phase 3 New Chat – Pre-Chat Checklist

**Before starting a new Copilot chat, execute these steps to ensure clean context:**

---

## 1. Verify Git State (ensure clean branch)

```powershell
cd C:\Users\mrbla\BlarAI
git status
# Expected: On branch feature/phase2-scaffolding, nothing to commit, working tree clean

git log --oneline -3
# Expected: Latest commit is P1.10 integration test (fd64261)
```

**Action:** If `git status` shows uncommitted changes:
- Review with `git diff`
- Stage with `git add .`
- Commit with descriptive message before starting new chat

---

## 2. Verify Python Environment Ready

```powershell
& .venv/Scripts/Activate.ps1
python --version
# Expected: Python 3.11.9

pip list | Select-String "openvino|pytest|pydantic"
# Expected: openvino 2025.4.1, pytest latest, pydantic 2.x
```

**Action:** If venv inactive or packages missing:
- Activate: `& .venv/Scripts/Activate.ps1`
- Install: `pip install -r requirements.txt` (if exists) or `pip install openvino pytest pydantic`

---

## 3. Run Full Test Suite (Baseline)

```powershell
cd C:\Users\mrbla\BlarAI
pytest -v --tb=short 2>&1 | Tee-Object -FilePath baseline_p1_tests_$(Get-Date -Format yyyyMMdd_HHmmss).log
# Expected: 484 passed in ~10s
```

**Action:** If <484 tests pass:
- Investigate failure
- Do NOT proceed with new chat until tests pass
- Fix + commit before new chat
- Attach test log to new chat if there are edge-case failures

---

## 4. Copy Bootstrap Prompt to Clipboard (for new chat)

```powershell
Get-Content ".github/prompts/phase3-ui-design-bootstrap.xml" | Set-Clipboard
# Verify: Paste into Notepad — should see XML preamble
```

---

## 5. Prepare File List for Attachment

Open `.github/prompts/PHASE3_ATTACHMENTS.md` and verify all 8 files exist:

```powershell
$files = @(
  ".github/copilot-instructions.md",
  "Use Cases_FINAL.md",
  "docs/IMPLEMENTATION_PLAN.md",
  "docs/adrs/ADR-007-iGPU-Trust-Boundary-Software-Fallback.md",
  "services/policy_agent/src/ipc.py",
  "services/assistant_orchestrator/src/npu_inference.py",
  "services/assistant_orchestrator/src/pgov.py",
  "tests/integration/test_p110_end_to_end.py"
)
foreach ($file in $files) {
  $exists = Test-Path $file
  Write-Host "$($exists ? '✓' : '✗') $file"
}
# Expected: All 8 show ✓
```

---

## 6. Open New Copilot Chat in VS Code

1. **Open VS Code** (if not already open)
2. **Ctrl+Shift+P** → `Copilot: Open Chat`
3. **New Chat** (not "New Codebase Chat")

---

## 7. Paste Bootstrap Prompt

1. **Paste clipboard** (Ctrl+V) into new chat
   - Should see: `<?xml version="1.0"...`
2. **Do NOT send yet**

---

## 8. Attach Files in Order

**Attach the 8 files listed in PHASE3_ATTACHMENTS.md in strict order:**

1. `.github/copilot-instructions.md`
2. `Use Cases_FINAL.md`
3. `docs/IMPLEMENTATION_PLAN.md`
4. `docs/adrs/ADR-007-iGPU-Trust-Boundary-Software-Fallback.md`
5. `services/policy_agent/src/ipc.py`
6. `services/assistant_orchestrator/src/npu_inference.py`
7. `services/assistant_orchestrator/src/pgov.py`
8. `tests/integration/test_p110_end_to_end.py`

**In VS Code Copilot chat:**
- Click **paperclip icon** (attach)
- Select file by path
- Repeat 8 times
- Files should appear as tags above the message input area

---

## 9. Send Bootstrap Prompt + Attachments

Once all 8 files are attached and bootstrap prompt is pasted:

- **Ctrl+Enter** (or click Send)
- Wait for response

---

## 10. Verify Agent Activation

Expected first response from new agent:
- Acknowledgment of Phase 3 directives
- Confirmation of autonomy scope (can edit docs, create ADR, auto-commit)
- Summary of 3 UI options to analyze
- Request for any clarifications before starting

**If response is off-topic or generic:**
- Regenerate (up-arrow → Ctrl+Enter)
- Or manually clarify in next message

---

## Troubleshooting

| Issue | Resolution |
|-------|-----------|
| "Files not found" error | Verify paths are relative to `C:\Users\mrbla\BlarAI` |
| Chat responds with generic AI assistant tone | Paste bootstrap XML again, regenerate |
| Chat asks for permission to edit docs | Remind: "You have autonomy to edit directly per Phase_3 directives" |
| Tests fail during chat | Ask agent to pause; run `pytest -v`, fix + commit, then resume |

---

## Post-Chat (after Phase 3 design is complete)

1. Verify all new files are staged:
   ```powershell
   git status
   ```
2. Review agent's commits:
   ```powershell
   git log --oneline -5
   # Expected: 4 new commits (ADR, plan, scaffold, evidence)
   ```
3. Run full test suite:
   ```powershell
   pytest -v
   # Expected: 484 + N_UI_tests passed
   ```
4. Return to this chat (or new chat) with evidence link to proceed to P1.11–P1.14 implementation.

---

**All set. Execute the checklist above, then start the new chat.**
