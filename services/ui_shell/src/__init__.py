"""
TUI Shell — Textual Chat Interface (P1.12, ADR-009)
=====================================================
Textual (MIT) | ~20–50MB | Zero network | Async-native Python

The TUI Shell is the primary user interaction surface for BlarAI.
It provides streaming token display, session management, PGOV denial
panels, and Boot-Phase-3 gating — all through a terminal interface
with zero network attack surface.

Migration path: Phase 4+ → Native Desktop Shell (PyQt6 or Tkinter)
per Lead Architect directive. Only this package is replaced; the
Transport Gateway API (services/ui_gateway) remains stable.
"""

__version__ = "0.1.0"
