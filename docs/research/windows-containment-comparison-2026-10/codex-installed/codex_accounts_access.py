"""The exact read-only check run on 2026-10-10 ~22:25 -04:00 for #1743 (re-runnable, elevated).

AuthZ effective access of the two Codex sandbox accounts on effective_access.REAL_PATHS, with the
same added well-known groups the dedicated-account setup (A) uses: Everyone, LOCAL, Authenticated
Users, This Organization, BATCH. Output: codex-accounts-effective-access.json next to this file.
Usage:  python -I codex_accounts_access.py <path to tools/probes/containment_arms>
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
import effective_access as ea  # noqa: E402
import winsec as w  # noqa: E402

w.enable_privilege("SeBackupPrivilege")
ctxs = {}
groups = {}
for acct in ("CodexSandboxOffline", "CodexSandboxOnline"):
    sid = w.sid_of_account(acct)
    c = w.AuthzContext(sid, [ea.EVERYONE, ea.LOCAL, ea.AUTH_USERS, ea.THIS_ORG, ea.BATCH])
    ctxs[acct] = c
    groups[acct] = {"sid": sid, "computed": c.computed_groups, "added": c.added_groups}
rows = []
for _kind, p in ea.REAL_PATHS:
    if not os.path.lexists(p):
        continue
    d = w.read_descriptor(p)
    isd = os.path.isdir(p)
    row = {"path": p}
    for a, c in ctxs.items():
        s = w.summarize(c.access(d), isd)
        row[a] = ("R" if s["read"] else "-") + ("W" if s["write"] else "-")
    rows.append(row)
out = Path(__file__).with_name("codex-accounts-effective-access.json")
out.write_text(json.dumps({"groups": groups, "rows": rows}, indent=1), encoding="utf-8")
print(out)
