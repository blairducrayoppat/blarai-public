---
title: UAT-1_ACCEPTANCE_PLAN
status: archived
area: portfolio
---

# UAT-1 Acceptance Plan — BlarAI Assistant (Mock Backend)

**Stage:** UAT-1 (Mock Backend)  
**Branch:** `feature/p1-uat1-launcher`  
**Version:** P1.15  
**Date:** 2025-07-17  
**Executor:** Lead Architect  
**Test Count at Gate:** 747/747 passing  

---

## UAT-2 Cross-Link

For the real-runtime operational activation plan (post-mock path), see:
`docs/UAT-2_ACCEPTANCE_PLAN.md`

Launcher profile switch for real-runtime activation:

```powershell
$env:BLARAI_LAUNCH_PROFILE = "uat2_real"
.\.venv\Scripts\python.exe -m launcher
```

Reset to UAT-1 mock path:

```powershell
Remove-Item Env:BLARAI_LAUNCH_PROFILE
```

---

## 1. Purpose

UAT-1 validates the complete **user-visible experience** — from double-clicking a
Windows Start Menu shortcut through live chat interaction — using a deterministic
mock backend. This isolates the TUI, transport layer, session persistence, PGOV
display, and VM lifecycle management from the not-yet-deployed inference pipeline.

**UAT-2** (planned) will substitute the mock backend with the real LLM inference
running inside the Hyper-V VM over vsock. The TUI and launcher code are identical
across both stages.

---

## 2. Architecture (UAT-1)

```
┌──────────────────────────────────────────────┐
│           Windows Host (Admin)               │
│                                              │
│  ┌──────────────────────────────┐            │
│  │  BlarAI.exe (PyInstaller)   │            │
│  │                              │            │
│  │  ┌────────────────────────┐  │            │
│  │  │  MockPAServer (thread) │◄─┤ TCP :50051 │
│  │  └────────────────────────┘  │            │
│  │          │                   │            │
│  │  ┌───────▼────────────────┐  │            │
│  │  │  TransportGateway      │  │            │
│  │  │  (dev_mode=True)       │  │            │
│  │  └───────┬────────────────┘  │            │
│  │          │                   │            │
│  │  ┌───────▼────────────────┐  │            │
│  │  │  SessionStore (SQLite) │  │            │
│  │  └───────┬────────────────┘  │            │
│  │          │                   │            │
│  │  ┌───────▼────────────────┐  │            │
│  │  │  BlarAIApp (Textual)   │  │            │
│  │  └────────────────────────┘  │            │
│  └──────────────────────────────┘            │
│                                              │
│  ┌────────────────────────────────┐          │
│  │  BlarAI-Orchestrator VM       │          │
│  │  (Hyper-V — started but idle) │          │
│  └────────────────────────────────┘          │
└──────────────────────────────────────────────┘
```

---

## 3. Prerequisites

| Requirement | Detail |
|---|---|
| **OS** | Windows 11 Pro, Hyper-V enabled |
| **Hardware** | Intel Core Ultra 7 258V (or compatible) |
| **Python** | 3.11.x (for build only — exe is self-contained) |
| **VM** | BlarAI-Orchestrator VM provisioned (Phase 2) |
| **Admin** | UAC prompt will appear on first launch |
| **Terminal** | Windows Terminal recommended for Textual rendering |

---

## 4. Installation Steps

### 4.1 Build (one-time)

```powershell
cd C:\Users\mrbla\BlarAI
.\.venv\Scripts\Activate.ps1
.\scripts\build.ps1
```

Expected output:
- `dist\BlarAI\BlarAI.exe` created
- Start Menu shortcut "BlarAI Assistant" created

### 4.2 Launch (normal usage)

**Option A:** Start Menu → Search "BlarAI" → Click "BlarAI Assistant"  
**Option B:** Double-click `dist\BlarAI\BlarAI.exe`  
**Option C:** Right-click → Run as Administrator (if UAC auto-elevation fails)

### 4.3 Dev-mode Launch (no build required)

```powershell
cd C:\Users\mrbla\BlarAI
.\.venv\Scripts\python.exe -m launcher
```

---

## 5. First-Launch Walkthrough

On first launch, the console window will display:

```
╔══════════════════════════════════════╗
║        BlarAI Assistant v0.1.0       ║
║   Local AI · Zero Cloud · Private    ║
╚══════════════════════════════════════╝

[1/6] Checking admin privileges...     ✓
[2/6] Starting BlarAI-Orchestrator VM... ✓  (or ⚠ non-fatal if Hyper-V unavailable)
[3/6] Starting mock backend server...  ✓
[4/6] Initializing session store...    ✓
[5/6] Connecting transport gateway...  ✓
[6/6] Launching TUI...                ✓
```

The Textual TUI then takes over the terminal with:
- Chat panel (center)
- Session history panel (left sidebar, toggle with `Ctrl+B`)
- PGOV overlay (appears on policy-governed responses)

---

## 6. Test Scenarios

### TC-01: Boot Sequence

| Step | Action | Expected Result | Pass? |
|------|--------|-----------------|-------|
| 1 | Launch BlarAI.exe | UAC prompt appears | ☐ |
| 2 | Accept UAC | Console shows 6-step boot | ☐ |
| 3 | Observe step [2/6] | VM start attempted (✓ or ⚠) | ☐ |
| 4 | Observe step [6/6] | TUI renders in terminal | ☐ |
| 5 | Check `%LOCALAPPDATA%\BlarAI\launcher.log` | Log file created with timestamps | ☐ |

### TC-02: Prompt Submission & Streaming

| Step | Action | Expected Result | Pass? |
|------|--------|-----------------|-------|
| 1 | Type "hello" in input, press Enter | User message appears in chat | ☐ |
| 2 | Observe response | Tokens stream in word-by-word (\~30ms/token) | ☐ |
| 3 | Response completes | Full greeting message visible | ☐ |
| 4 | PGOV footer | Shows PERMIT status with reason codes | ☐ |

### TC-03: Multiple Prompts

| Step | Action | Expected Result | Pass? |
|------|--------|-----------------|-------|
| 1 | Type "What is your architecture?" | Architecture description streams | ☐ |
| 2 | Type "Tell me about PGOV" | PGOV explanation streams | ☐ |
| 3 | Type "help" | Keyboard shortcuts listed | ☐ |
| 4 | Scroll up | Previous messages visible | ☐ |

### TC-04: PGOV Denial

| Step | Action | Expected Result | Pass? |
|------|--------|-----------------|-------|
| 1 | Type "deny this request" | User message appears | ☐ |
| 2 | Observe response | "I cannot process this request" message | ☐ |
| 3 | Check PGOV overlay | Shows DENY verdict | ☐ |
| 4 | Check reason codes | PII_DETECTED + LEAKAGE_DETECTED displayed | ☐ |

### TC-05: Session Management

| Step | Action | Expected Result | Pass? |
|------|--------|-----------------|-------|
| 1 | Press `Ctrl+N` | New session created | ☐ |
| 2 | Send a prompt in new session | Response appears | ☐ |
| 3 | Press `Ctrl+B` | Session sidebar toggles | ☐ |
| 4 | Click previous session | Original messages restored | ☐ |
| 5 | Close and relaunch BlarAI | Sessions persist from SQLite | ☐ |

### TC-06: Keyboard Shortcuts

| Shortcut | Action | Expected | Pass? |
|----------|--------|----------|-------|
| `Ctrl+N` | New session | Session panel updates | ☐ |
| `Ctrl+B` | Toggle sidebar | Sidebar opens/closes | ☐ |
| `Ctrl+D` | Delete session | Session removed (with confirmation) | ☐ |
| `Ctrl+Q` | Quit | Graceful shutdown, VM stopped | ☐ |
| `Ctrl+C` | Interrupt | Same as Ctrl+Q | ☐ |

### TC-07: Error Handling

| Step | Action | Expected Result | Pass? |
|------|--------|-----------------|-------|
| 1 | Launch without Hyper-V | Step [2/6] shows ⚠, app continues | ☐ |
| 2 | Send very long prompt (500+ chars) | Handled gracefully | ☐ |
| 3 | Send empty prompt (just Enter) | No crash, no request sent | ☐ |
| 4 | Rapid-fire prompts | Queued or debounced, no crash | ☐ |

### TC-08: VM Lifecycle

| Step | Action | Expected Result | Pass? |
|------|--------|-----------------|-------|
| 1 | Before launch: `Get-VM BlarAI-Orchestrator` | Note current state | ☐ |
| 2 | Launch BlarAI | VM state → Running | ☐ |
| 3 | `Ctrl+Q` to quit | VM state → Off | ☐ |
| 4 | Verify in Hyper-V Manager | VM stopped cleanly | ☐ |

### TC-09: Shutdown & Cleanup

| Step | Action | Expected Result | Pass? |
|------|--------|-----------------|-------|
| 1 | Press `Ctrl+Q` | TUI exits | ☐ |
| 2 | Console shows cleanup | Mock server stopped, VM stopped | ☐ |
| 3 | Check process list | No orphan Python/BlarAI processes | ☐ |
| 4 | Check `launcher.log` | Clean shutdown logged | ☐ |

---

## 7. Known Limitations (UAT-1)

| Limitation | Detail | Resolved In |
|---|---|---|
| **No real inference** | Responses are canned/deterministic from MockPAServer | UAT-2 |
| **No vsock transport** | TCP loopback on localhost:50051, not AF_HYPERV | UAT-2 |
| **VM is idle** | Started/stopped for lifecycle validation only | UAT-2 |
| **No model loading** | No ONNX/OpenVINO model files used | UAT-2 |
| **Fixed responses** | 5 canned response patterns via keyword matching | UAT-2 |
| **No multi-turn context** | Mock doesn't track conversation history | UAT-2 |
| **Console window** | PyInstaller builds as console app (required for Textual) | Permanent |

---

## 8. Acceptance Criteria

UAT-1 is **ACCEPTED** if:

- [ ] All 9 test scenarios (TC-01 through TC-09) pass
- [ ] 747/747 automated tests pass
- [ ] BlarAI.exe launches from Start Menu without manual commands
- [ ] Streaming token display is visually smooth
- [ ] PGOV governance overlay renders correctly for both PERMIT and DENY
- [ ] Session history persists across restarts
- [ ] VM starts and stops with the application
- [ ] No orphan processes after shutdown
- [ ] Launcher log captures full session activity

---

## 9. UAT-2 Preview

UAT-2 will modify only the **launcher startup sequence** — replacing the
MockPAServer thread with a vsock connection to the real inference pipeline
running inside the BlarAI-Orchestrator VM. Changes required:

1. Deploy inference service to VM (Alpine + OpenVINO + Qwen3-1.7B)
2. Install `mock_backend/server.py --vsock` as OpenRC service in VM
   (initially, then replace with real `assistant_orchestrator`)
3. Change launcher step [3/6] from `MockPAServer(port=50051)` to
   `TransportGateway(dev_mode=False)` (vsock to VM)
4. Remove mock server thread and TCP loopback

The TUI, session store, PGOV display, and all keyboard shortcuts remain
**identical** between UAT-1 and UAT-2.

---

## 10. Sign-Off

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Lead Architect | | | |
| QA (if applicable) | | | |

---

*Document generated as part of P1.15 milestone on branch `feature/p1-uat1-launcher`.*
