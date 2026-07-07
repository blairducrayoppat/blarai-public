### 2026-07-01 — Packing the house before the fire

Today the system got something it has never had in eight months of building:
an existence outside this one disk. The trigger was operational — the
User-Operator wants to reformat the drive — but the discovery pass turned up
a fact worth sitting with: **not one of the five live repos had a git
remote.** BlarAI's 401 branches, the full ADR corpus, BUILD_JOURNAL.md
itself, the coding-fleet dispatch program, the jobhunt tool — every commit of
all of it existed exactly once, on the hardware it was written on. We had
built a security-first system with TPM-sealed keys and fail-closed egress,
and its single point of failure was a SATA connector.

The backup now has three legs, chosen by what each store is good at. GitHub
(private repos) carries the five repos — 398 of blarai's 401 branches, with
uncommitted work captured first as `backup/wip-*-20260701` snapshot branches
built through a temporary index so no working tree was touched mid-flight.
OneDrive carries what git can't: the 33.7 GB of converted model weights, the
encrypted runtime databases with their TPM-wrapped keystores, the Vikunja
database (snapshotted live via SQLite's backup API), the OVMS install, the
Claude memory namespaces, the Hyper-V VHDX, and full `git bundle` files of
all five repos — including the three branches GitHub refused because an old
Intel-PR-reproduction commit carries a 385 MB model binary. A USB-bound
secrets bundle carries the keys and credentials, deliberately staged OUTSIDE
the cloud path — the permission classifier balked at SSH keys heading to
OneDrive, and rather than route around the objection I put the question to
the operator, who chose the air-gapped leg. The trade-off is a manual step
(copy one folder to a stick) bought for keeping key material off Microsoft's
servers; the rejected alternative was convenience.

Two discoveries would have made a naive backup silently worthless. First,
the at-rest encryption: the DEK keystore JSONs copy cleanly, but they are
sealed to THIS machine's TPM — the copies are only decryptable via the
`--recover` ceremony with the offline recovery key printed once at
provisioning. A backup of the databases without confirming that key exists
is a backup of noise; the runbook now leads with it. Second, the "dirty
worktrees" that weren't: two `.worktrees/` directories reported 33 modified
files each, matching main's count exactly — orphan directories whose `.git`
files were gone, letting git walk up to the parent repo and report its state
as theirs. I snapshotted them before noticing, then deleted the two junk
branches. The lesson from the #714/#715 arc holds here too: match the
measurement to the thing you think you're measuring.

What was deliberately left behind: 124 GB of `oss/` OpenVINO upstream clones
(clean, pushed, re-cloneable — a 900-byte patch file preserves the one local
tweak), the 15 GB coder-30b (one HuggingFace download), \~34 GB of compiled
model caches, every `.venv`, and the graveyard of fleet test projects. A
backup that includes everything is a backup nobody audits.

**Next:** operator copies `reformat-secrets` to USB and confirms the offline
recovery key is findable; OneDrive sync runs to "Up to date"; then the
reformat, and `RESTORE_RUNBOOK.md` (OneDrive backup root) drives the rebuild
phase by phase, ending with the standing gate as the proof the house moved
intact.

**Proposed lesson:** A system's disaster-recovery posture is part of its
security posture — TPM-sealed keys and fail-closed egress meant nothing
against a failed disk while every repo was remote-less. And the backup is
only as good as its decrypt path: verify the recovery ceremony's inputs
exist BEFORE the event that makes them unobtainable.
