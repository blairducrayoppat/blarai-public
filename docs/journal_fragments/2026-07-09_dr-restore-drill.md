### 2026-07-09 — The novice question that found the untested half

*Plain summary: disaster-recovery restore path audited, drilled, and made self-maintaining — four
restore legs rehearsed PASS, a stale-lockfile restore defect fixed (`requirements.2026.2.1.lock.txt`
frozen), the runbook promoted to a tracked master synced nightly to the backup root; Vikunja #782.*

The Lead Architect asked, an hour before handing me the night: *"I feel like the project is
missing a key piece that I am just unaware of because I am a novice."* The honest answer took an
audit, and the audit proved his instinct sound. The backup arc from 2026-07-01 (lesson 226) had
built a genuinely good CAPTURE side — nightly, all legs green, a thoughtful runbook already
sitting in the OneDrive root where a dead laptop can't take it. What eight days of heavy building
had never produced was a single proof that any of it could come BACK: no restore leg had ever been
rehearsed, and the runbook was a point-in-time document already wrong in ways that would hurt at
exactly the moment it was needed.

The drill made the gap concrete. Four legs rehearsed tonight, all PASS: a shallow clone from the
private remote (the remote is real and current), `git bundle verify` on the 7/1 bundle (complete
history), all three encrypted databases restored from OneDrive to scratch with `PRAGMA
integrity_check` ok, and a weights sha256 identical across local and mirror. But the runbook the
restore would follow said `py -3.12` where the validated runtime is pinned 3.11.9, counted 398
branches where 555 push nightly, and — the find that justified the whole evening — pointed the
venv rebuild at `requirements.2026.1.0.lock.txt`, a lockfile frozen one OpenVINO substrate ago. A
faithful restore would have silently rebuilt the inference stack on 2026.1.0 while every
measurement, the prefix-caching KEEP-ON, the swap-gate 20.0, and the spec-decode findings all rest
on 2026.2.1. The backup was fine; the *instructions* for using it would have quietly rebuilt a
different machine. I froze the current environment as `requirements.2026.2.1.lock.txt` and
repointed the runbook.

The trade-off worth recording is where the master now lives. A restore runbook's first duty is to
be readable when the machine is gone, which argues for OneDrive; its second duty is to stay
correct as the system drifts, which argues for the repo where review and diffs live. I took both:
the tracked master in `docs/runbooks/DISASTER_RECOVERY_RESTORE.md`, and one fail-loud line in
`backup-system.ps1` that copies it to the backup root every night — proven live tonight (the leg
logged `restore runbook synced from tracked master` on a manual run before the change merged). The
rejected alternative — keeping the OneDrive copy authoritative and hand-editing it — is exactly
how the 7/1 version rotted: an untracked document nobody diffs, drifting one fact per merge day.
Small honest finding on the way: the backup script's push-exclusion list names a branch
(`feat/719-golive-ceremony`) that no longer exists anywhere — stale entry, harmless, noted rather
than chased.

What tonight did NOT prove stays named: the TPM recovery-unwrap with the physical printed key
(the code path is gate-tested in `test_field_cipher_and_dek_envelope.py`; the *paper* is not), and
a restore onto different hardware. Both are LA-present steps — the printed-key check is two
minutes and is now the single most valuable unverified control in the project, tracked on #782.

**Recurrence of lesson 226:** the backup arc's own residual — "a backup is only as good as its
decrypt path; verify the recovery ceremony's INPUTS before the event that makes them
unobtainable" — recurred as tonight's finding-shape: the restore path existed on paper and had
never once been exercised (the lesson-222 positive-control judgment applied to disaster recovery).
Tonight lands the rehearsal + the self-maintaining runbook as the partial control; the printed-key
verification (#782) completes it.

**Next:** the LA's two-minute physical check of the printed recovery key (record on #782); a
full restore-onto-different-hardware ceremony when a second machine exists; bundle refresh at the
next quarterly pass.

*(commits: blarai `<this>` (runbook master + lockfile + index + this fragment); agentic-setup
`feat/782-runbook-nightly-sync` (the nightly sync leg, live-proven pre-merge); drill evidence in
#782 comments.)*
