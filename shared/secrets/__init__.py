"""BlarAI DPAPI-backed secret storage for operator-provisioned credentials.

This package provides the DPAPI-encrypted blob store for secrets that must
survive process restarts but never leave the machine in plaintext.  The
initial consumer is the Kagi API key used by the Agentic Web-Search Skill
(W2, Vikunja #573).

Public exceptions (re-exported here so callers only need one import)
-------------------------------------------------------------------
    KagiKeyNotProvisioned
    KagiKeyDecryptError

Public functions (re-exported)
-------------------------------
    store_kagi_api_key
    load_kagi_api_key
"""

from __future__ import annotations

from shared.secrets.dpapi_store import (
    KagiKeyDecryptError,
    KagiKeyNotProvisioned,
    load_kagi_api_key,
    store_kagi_api_key,
)

__all__ = [
    "KagiKeyNotProvisioned",
    "KagiKeyDecryptError",
    "store_kagi_api_key",
    "load_kagi_api_key",
]
