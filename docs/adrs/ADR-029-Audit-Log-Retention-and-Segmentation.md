# ADR-029 — Audit-Log Retention and Segmentation

**Status:** ACCEPTED 2026-06-10 (Lead-Architect-decided; policy delegated to the guide for implementation).
**Deciders:** Lead Architect (blarai); code-specialist (implementation).
**Builds on:** ADR-018 (TPM 2.0 trust root), ADR-025 §2.8(a) (audit refuse-to-start posture), #602/#605 (the tamper-evident audit log + TPM signer), #637 (owner-only file DACL hardening).
**Relates to:** Vikunja #607 (audit retention policy — the gate carry-over this ADR closes), #606 (tail-deletion attack class), `SECURITY_ROADMAP_air_gap_removal.md` §5.

## Context

`shared/security/audit_log.py` persists every adjudication decision as a SHA-256-chained, signed JSON-line record. Its design intent has been documented from the start: *"Append-only, unbounded by default. Forensic completeness for a decades-use system means we keep everything."* That intent is right for an AIGP-governance-evidence platform on a single-user air-gapped box. But the as-built primitive had two real, unaddressed gaps that compound over a decades-long lifetime:

1. **Unbounded RAM.** Construction loaded the ENTIRE history into `self._records` (`AuditLog._load_existing` → append every line). On a decades-use system this grows without bound — the in-RAM working set is proportional to total history, not to recent activity.
2. **Unbounded active file + O(n) boot.** A single ever-growing `audit.jsonl` is re-read in full on every startup, so boot cost also grows with total history.

The remaining open question for the #598 gate (carried as #607) was the **retention policy**: what do we do as the audit history grows? The choices ranged from "delete old records" (various purge schemes) to "keep everything but fix the unboundedness." The records are **metadata-only** (no prompt/response content — adjudication seq, decision, hashes, agent/verb/resource, timestamps), the data volume is tiny (single user, air-gapped), and the documented history *is* the User-Operator's IAPP AIGP portfolio evidence. Destroying any of it has real governance cost and \~no storage benefit.

## Decision

Adopt **"Segmented keep-everything with a bounded working set"** (rotate-and-retain):

> Keep the full forensic history **forever**, but in **sealed, individually-verifiable, gzip-compressed segments** rotated at a size/count cap — so the in-RAM working set and the active file stay **bounded** while complete history is **retained on disk**. **Never hard-delete by default.**

Concretely (implemented in `shared/security/audit_log.py`, wired at the `_build_audit_log` factory in `services/policy_agent/src/entrypoint.py`):

- **Rotation by size/count.** Config knobs `audit_max_active_bytes` (default **64 MiB**) and `audit_max_active_records` (default **100_000**); whichever trips first rotates. On rotation the active file is fsync'd + closed, renamed to a sealed segment `audit-{first_seq:012d}-{last_seq:012d}-{YYYYMMDDTHHMMSSZ}.jsonl`, gzip-compressed to `.jsonl.gz`, DACL-hardened (#637 `ensure_owner_only_dacl`), and a fresh active `audit.jsonl` is started. The next record's `prev_hash` equals the sealed segment's last `record_hash` — **chain continuity is unchanged; it just spans files.**
- **Segment index = cross-segment verifiable anchor.** `audit-segments.jsonl` records, per sealed segment, `{first_seq, last_seq, first_prev_hash, last_record_hash, file_sha256, segment_signature}`, where `segment_signature` is the existing `RecordSigner.sign()` over the canonical segment summary (which binds the four boundary hashes **and** the compressed file's SHA-256). This is what lets a later `verify()` confirm the sealed segments form one unbroken, signed chain even though they are separate files. DACL-hardened too.
- **Bounded RAM.** At startup ONLY the active segment is loaded into `self._records`; the chain head is restored from the active file's last record, or — if the active file is empty (just rotated) — from the segment index's `last_record_hash` / `last_seq`. Sealed segments are never loaded into RAM. After an in-process rotation, `self._records` holds only the new active segment. RAM is bounded by the active cap, not total history.
- **`verify()` spans segments.** The default `verify()` stays fast (active segment + the segment-index anchor chain: per-segment signature + on-disk `.jsonl.gz` SHA-256 + consecutive linkage). `verify(full=True)` additionally gunzips every sealed segment and walks every record end-to-end, still raising `AuditChainError` at the first tamper **anywhere**, including inside a sealed `.jsonl.gz`.
- **Retention ceiling — default OFF (keep all).** `audit_archive_max_bytes` / `audit_archive_max_age_days` default `None` (unlimited — the chosen policy keeps everything). IF an operator ever sets one, WHOLE sealed segments are pruned **oldest-first only**, and the prune is itself written as a normal chained+signed audit record with `decision="RETENTION_PRUNE"` and `resource=<segment id>`. A later `verify(full=True)` then sees a **documented, signed** gap (policy), distinguishable from a #606 tail-deletion attack (which leaves no such record). Never prune mid-chain; never prune the active segment.
- **Fail-safe + fail-closed preserved.** If any rotation step fails, it is logged and the log **degrades to status-quo unbounded** (keep appending to the active file) rather than drop or corrupt a record; partial sealed artifacts are cleaned up. The existing write-failure contract is unchanged — `_write_record` still raises `AuditSinkError` on write failure (fail-closed). The production `TpmRecordSigner` path is unchanged; rotation is signer-agnostic.

## Alternatives not taken

- **Time-based purge (e.g. keep 90 days, delete older).** Rejected: it destroys AIGP governance/portfolio evidence for **no benefit** on a single-user air-gapped box with tiny data volume and metadata-only records. The evidentiary value of the history is the whole point; a time window throws it away to save storage that is not scarce.
- **FIFO hard size-cap dropping the oldest records.** Rejected: same evidence loss, **and** it breaks tamper-evidence mid-chain — silently dropping the oldest records severs the hash chain at the head with no signed record of why, which is indistinguishable from an attack and defeats the audit log's purpose.
- **Status-quo: single unbounded file, no rotation.** Rejected: this is the actual gap — unbounded RAM (whole history in `self._records`) and O(n) boot. "Keep everything" is right; "in one ever-growing file loaded whole into RAM" is the defect.

## Consequences

- **Positive:** the documented "keep everything — forensic completeness for a decades-use system" intent is preserved *and* the real unboundedness gap is closed. RAM and boot cost are bounded by the active cap, independent of total history. Each sealed segment is independently verifiable; tamper-evidence is preserved **across** segments via the signed anchor index. Operators get a retention ceiling if they ever need one, and using it cannot silently destroy evidence — every prune is itself a signed audit record.
- **Security posture:**
  - *Tamper-evidence across segments.* A swapped or byte-edited sealed `.jsonl.gz` is caught two independent ways: the signed index pins each segment's compressed SHA-256 (caught by the fast `verify()` without gunzipping), and `verify(full=True)` re-walks every record's hash chain. A forged index row fails its `segment_signature` check.
  - *Prune-is-audited.* A retention prune is a signed `RETENTION_PRUNE` record in the chain, so a policy gap is documented and attributable — distinct from a #606 tail-deletion attack, which has no such record. The prune-record append advances the chain head before the file is removed, so the gap is provably post-prune.
  - *Bounded RAM* removes a slow-burn denial-of-service / resource-exhaustion vector on a decades-use system.
  - *DACL hardening* (#637) is applied to sealed segments and the index, not just the active file.
- **Accepted trade-offs:**
  - The **default `verify()` trusts the signed anchor index** for sealed segments (it checks each segment's signature + on-disk SHA but does not re-walk every sealed record). `verify(full=True)` is the exhaustive walk. This is a deliberate fast-path/slow-path split; the anchor's SHA pin still catches any sealed-file mutation in the fast path.
  - After a retention prune removes all sealed history, the active tail legitimately starts mid-chain (its first `prev_hash` is not `GENESIS`). `verify()` recognises this only because the segment-index file persists (created on first rotation, never deleted — rewritten empty on full prune); an **unrotated** single-file log still strictly requires its first record to chain from `GENESIS`. This keeps the strict tamper-detection contract for the common unrotated case while allowing the documented-gap case after a prune.
  - **Confidentiality: sealed segments + the index are stored SIGNED-PLAINTEXT + owner-only-DACL'd, NOT DEK-encrypted** like `sessions.db` / `substrate.db` (ADR-025). **LA-RATIFIED 2026-06-10** (the guide escalated the question; the LA confirmed *keep signed-and-locked*): for a forensic audit log this is the *correct* posture, not a residual — the trail must stay **independently verifiable** (a reviewer, or future-you, can check it without holding the DEK) and must **survive DEK loss/compromise**, and the records are **metadata** (decisions, resource identifiers, hashes), not conversation/document content. Encrypting the log would couple the witness to the very key whose use it witnesses. **Revisit trigger:** once post-#556 network tools begin writing *sensitive* resource identifiers (real file paths, URLs) into `resource`, re-weigh at-rest encryption of those identifiers with the keyed-hash-for-index pattern (the Sprint-14 precedent that keeps a ciphertext store verifiable/dedup-able).

## Verification

- 62 tests in `shared/tests/test_audit_log.py` (38 pre-existing + 24 added) — rotation triggers exactly at the byte AND record thresholds; chain continuity across a rotation seam (`verify` + `verify(full=True)` both pass); a tampered byte in a sealed `.jsonl.gz` is caught by `verify(full=True)` and by the fast `verify()` SHA anchor; bounded RAM (`len(log.records)` reflects only the active segment after rotation; reload loads only the active); a `RETENTION_PRUNE` flow writes the signed meta-record and `verify(full=True)` still passes with the documented gap; fail-safe (a simulated rotation error keeps appending, loses no record, leaves no partial artifact). `HmacSha256Signer` + injected timestamps/seq are used for determinism; the production `TpmRecordSigner` path is unchanged.
- The `_build_audit_log` factory + `default.toml` `[security]` knobs were exercised end-to-end (config → rotating `AuditLog` → cross-segment verify) during implementation.

## References

`shared/security/audit_log.py`; `services/policy_agent/src/entrypoint.py` (`_build_audit_log`, `_audit_retention_kwargs`); `services/policy_agent/config/default.toml` `[security]`; `shared/tests/test_audit_log.py`; ADR-018; ADR-025 §2.8(a); #602/#605/#606/#607/#637. DECISION_REGISTER index updated in the same change (the non-optional maintenance rule).
