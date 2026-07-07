# Phase 3 UI — Gate Evidence Summary

**Date**: 2025-07-19  
**Branch**: `feature/phase2-scaffolding`  
**Agent**: Copilot (Claude Opus 4.6)  
**Lead Architect Decision**: Option A: Textual TUI approved with PyQt6/Tkinter migration path for Phase 4+

---

## Deliverables Completed

| # | Deliverable | Status | Artifact |
|---|-------------|--------|----------|
| 1 | Security Posture Review | DONE | No amendment needed — zero external network calls apply to P1.11-P1.14 |
| 2 | Comparative Interface Analysis | DONE | 3 options scored across 9 weighted criteria (TUI=98, Web=86, Desktop=82) |
| 3 | Architectural Decision Gate | DONE | Lead Architect approved Option A (Textual TUI) |
| 4 | ADR-009 | DONE | `docs/adrs/ADR-009-Assistant-Interaction-Surface.md` |
| 5 | Use Cases Addendum | DONE | UC-004 UI Addendum in `Use Cases_FINAL.md` |
| 6 | Implementation Plan Update | DONE | `docs/IMPLEMENTATION_PLAN.md` v3.0 (P1.11-P1.14) |
| 7 | Scaffold + Tests | DONE | `services/ui_gateway/` + `services/ui_shell/` — 24 new files |

## Test Results

| Scope | Count | Status |
|-------|-------|--------|
| P1.0-P1.10 (existing) | 548 | ALL PASS |
| P1.11 ui_gateway (new) | 60 | ALL PASS |
| P1.12 ui_shell (new) | 31 | ALL PASS |
| **Total** | **639** | **ALL PASS** |

## Decision Matrix (ADR-009)

| Criterion | Weight | TUI | Web | Desktop |
|-----------|--------|-----|-----|---------|
| Memory footprint | HIGH (×3) | 15 | 12 | 9 |
| Network attack surface | HIGH (×3) | 15 | 6 | 15 |
| Privacy compliance | HIGH (×3) | 15 | 12 | 15 |
| Startup latency | MEDIUM (×2) | 10 | 6 | 8 |
| Streaming token support | MEDIUM (×2) | 8 | 10 | 8 |
| Dev complexity (MVP) | MEDIUM (×2) | 10 | 10 | 6 |
| Accessibility | LOW (×1) | 3 | 5 | 4 |
| Migration path | LOW (×1) | 5 | 5 | 5 |
| Testing cost | MEDIUM (×2) | 10 | 8 | 4 |
| **TOTAL** | | **98** | **86** | **82** |

## Architecture

```
User ↔ [TUI Shell (host)] ↔ [Transport Gateway (vsock+mTLS)] ↔ [Orchestrator VM]
                                      ↓
                              [SQLite sessions.db]
```

### P1.11 Transport Gateway (`services/ui_gateway/`)
- **transport.py**: `TransportGateway` class (Boot-Phase-3 handshake with exponential backoff, `send_prompt()`, `stream_tokens()` async generator, `get_pgov_result()`, tool-call buffer/flush)
- **session_store.py**: SQLite WAL + CASCADE FK, `SessionStore` CRUD (create/list/get_turns/add_turn/delete/clear/set_active)
- **Data types**: `StartupState` enum, `StreamToken`, `GatewayPGOVResult`, 6 reason code constants

### P1.12 TUI Shell (`services/ui_shell/`)
- **app.py**: `BlarAIApp` (Textual App subclass, 3-region layout, 5 keybindings, Boot-Phase-3 gating)
- **streaming.py**: `StreamingDisplay` (RichLog, token append FSM, tool-call block rendering)
- **session_panel.py**: `SessionPanel` (ListView sidebar, create/delete session)
- **pgov_display.py**: `PGOVPanel` (denial rendering, 6 reason labels, truncation)

## Dependencies Added

| Package | Version | Size | License |
|---------|---------|------|---------|
| textual | 8.0.0 | \~5MB | MIT |
| pytest-asyncio | 1.3.0 | \~50KB | Apache-2.0 |

## Commits

| # | Hash | Description |
|---|------|-------------|
| 1 | cd94a38 | ADR-009 + UC-004 UI Addendum |
| 2 | 84f26d8 | IMPLEMENTATION_PLAN v3.0 — P1.11-P1.14 |
| 3 | e7a3bbc | P1.11 + P1.12 scaffold + tests (639/639) |
| 4 | (this) | Evidence/summary |

## Rollback

```powershell
# To revert all Phase 3 changes:
git revert --no-commit HEAD~3..HEAD
git commit -m "revert: Phase 3 UI scaffold"
```
