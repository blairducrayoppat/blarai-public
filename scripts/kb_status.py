"""
Knowledge-bank status — verify what BlarAI has (and has NOT) stored.
====================================================================
A READ-ONLY inspector for the operator: after an `/ingest`, run this to confirm
exactly what landed in the encrypted knowledge bank and what the tamper-evident
ingest audit chain recorded. It NEVER decrypts content — it reads only the
plaintext bookkeeping columns (approval_state, source_type, word_count,
timestamps) and the labels-only audit records (ADR-029). Safe to run while BlarAI
is open (opens the SQLite file read-only).

What to look for:
  * A REJECTED doc has approval_state='rejected' and contributes ZERO searchable
    chunks — it is a tombstone (retained for audit), never retrievable.
  * Only APPROVED docs produce chunks (the searchable knowledge).
  * The audit log's records map verbs to decisions:
      INGEST_SUBMIT -> ESCALATE  (queued for your preview/approval)
      INGEST_APPROVE -> ALLOW    (you approved -> stored + indexed)
      INGEST_REJECT  -> DENY     (you rejected -> tombstone, not indexed)

Run:  .venv\\Scripts\\python.exe scripts\\kb_status.py
   (or double-click scripts\\kb_status.bat)
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys


def _localappdata() -> str:
    la = os.environ.get("LOCALAPPDATA")
    if not la:
        sys.exit("LOCALAPPDATA is not set — cannot locate the knowledge bank.")
    return la


def main() -> int:
    la = _localappdata()
    db = os.path.join(la, "BlarAI", "knowledge.db")
    print("=" * 64)
    print("BlarAI knowledge-bank status (read-only)")
    print("=" * 64)
    print(f"knowledge.db: {db}")
    if not os.path.exists(db):
        print("  (no knowledge bank yet — nothing has been ingested)")
        return 0

    # Read-only connection (works while BlarAI is running; WAL allows readers).
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    states = dict(
        conn.execute(
            "SELECT approval_state, COUNT(*) FROM knowledge_docs GROUP BY approval_state"
        ).fetchall()
    )
    print(f"\nDocuments by state: {states or '{}'}")
    print("  approved = stored + searchable | rejected = tombstone (NOT searchable) | pending = awaiting your decision")

    print("\nMost recent documents (state | type | words | created | decided):")
    rows = conn.execute(
        "SELECT doc_uuid, approval_state, source_type, word_count, created_at, decided_at "
        "FROM knowledge_docs ORDER BY created_at DESC LIMIT 10"
    ).fetchall()
    if not rows:
        print("   (none)")
    for doc_uuid, state, stype, words, created, decided in rows:
        n_chunks = conn.execute(
            "SELECT COUNT(*) FROM knowledge_chunks WHERE doc_uuid = ?", (doc_uuid,)
        ).fetchone()[0]
        flag = "  <-- NOT in memory" if state == "rejected" else ""
        print(f"   {state:<9} {stype:<5} {words:>6}w  created={created}  decided={decided}  chunks={n_chunks}{flag}")

    total_chunks = conn.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0]
    print(f"\nTotal SEARCHABLE chunks indexed (all approved docs): {total_chunks}")

    audit = os.path.join(la, "BlarAI", "audit", "ingest_audit.jsonl")
    print(f"\nIngest audit chain (tamper-evident, ADR-029): {audit}")
    if os.path.exists(audit):
        lines = open(audit, encoding="utf-8").read().splitlines()
        print(f"  last {min(6, len(lines))} decision record(s):")
        for ln in lines[-6:]:
            try:
                d = json.loads(ln)
                shown = {k: d[k] for k in ("verb", "decision", "source_type") if k in d}
                print(f"    {shown}")
            except json.JSONDecodeError:
                print(f"    {ln[:140]}")
    else:
        print("  (no audit log yet)")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())
