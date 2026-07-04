"""
UI Transport Gateway — vsock ↔ IPC Adapter (P1.11, ADR-009)
=============================================================
Zero network | vsock + mTLS relay | Interface-agnostic Python API

The Transport Gateway bridges the host-side UI Shell to the Orchestrator VM
via vsock + mTLS IPC. It exposes a Python API (send_prompt, stream_tokens,
get_sessions, get_pgov_result) that any UI frontend (TUI, Desktop, or future)
can consume without understanding the IPC protocol.

Security:
- Zero external network calls (no socket, requests, urllib, httpx)
- All communication via vsock (AF_HYPERV) or localhost TCP in dev_mode
- mTLS certificates loaded from disk, issued by PA during Boot Phase 2
- Fail-Closed: all errors return deny/error results
"""

__version__ = "0.1.0"
