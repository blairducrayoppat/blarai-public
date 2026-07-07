# Guest Parser Provisioning Record — UC-003 Stage C (#655, ADR-030 §3)

**Status:** PROVISIONED 2026-06-11 via CD ISO (`build/guest_cd.iso` attached as VM DVD;
`mount /dev/cdrom /mnt && sh /mnt/provision.sh` run at Hyper-V console). Round-trip proven
2026-06-12 (AF_HYPERV vsock, GUID `0000c351-facb-11e6-bd58-64006a7986d3`, port 50001;
health probe PASS; evidence: `docs/security/uc003_live_fetch_proof_2026-06-12.md`). VHDX
backup: `C:\HyperV\BlarAI\backups\Orchestrator_20260611_161145.vhdx`.
**UC-003 markdown extraction update (2026-06-13):** ISO rebuilt (`build/guest_cd.iso`,
22,675,456 bytes) with `include_formatting=True` in `extraction.py` and `vsock.py` drift
fix; re-provisioned at the Hyper-V console and **VERIFIED LIVE** — a heading/list/bold
fixture parsed in the guest returned markdown markers (`#`/`##`/`**`/`- `) over the vsock
channel, no egress (`docs/security/uc003_markdown_verify_2026-06-13.md`). Two runbook
defects were found and fixed during this re-provision (see §3 + §4): the bare
`mount /dev/cdrom` command relied on fs auto-detection this guest does not do, and an
in-place ISO rebuild strips the Hyper-V per-VM read ACL.
**Governs:** the provisioning + re-provisioning of the guest-homed HTML parser in the
BlarAI-Orchestrator Hyper-V guest (Alpine Linux 3.21, NIC-less, 2 GB / 2 vCPU).
**Relates to:** ADR-030 §3 (guest-homed parsing composition), Vikunja #655 (comment 1045 —
guest facts), #615 (AF_HYPERV addressing), #657 (VM stop-on-exit), #662 (guest deploy
channel — CD ISO), roadmap §6 Decision 3.

---

## 1. The access mechanism (what exists and what is proven)

The guest is NIC-less by ratified posture (`verify_vm_zero_nic` refuses VM start otherwise),
so every interaction uses Hyper-V's own channels:

| Channel | Direction | Status |
|---|---|---|
| **Copy-VMFile** (Guest Service Interface + in-guest `hv_fcopy_daemon`) | host → guest files | **CONFIRMED DEAD** — kernel 6.12.74 removed the legacy fcopy device; error `0x800710DF` at the 2026-06-11 controlled session. `hv_fcopy_daemon` has no device node to bind on this kernel. Non-revivable without a kernel rebuild. **Do not attempt.** |
| **CD ISO** (IMAPI2 ISO built at `build/guest_cd/build_iso.ps1`; attached as VM DVD) | host → guest parser tree | **PROVEN** — actual channel used at 2026-06-11 provisioning. In-guest: `mount /dev/cdrom /mnt && sh /mnt/provision.sh` (idempotent, \~30 s). Re-provisions use the same channel (§3). |
| **AF_HYPERV vsock** (GUID-pair addressing, #615) | host ↔ guest frames | **PROVEN** — transport (`phase2_gates/evidence/vsock_validation.json`, echo round-trip PASS) and application level (2026-06-12 round-trip: GUID `0000c351-facb-11e6-bd58-64006a7986d3`, port 50001, health probe PASS). |
| **Host → guest command execution** | — | **DOES NOT EXIST** — PowerShell Direct is Windows-guest-only; no SSH (no NIC); vsock carries parse frames only. Provisioning eliminates the need for remote exec: the `blarai-parser` service auto-starts on boot; code updates ship via CD ISO. |

**The provisioning model (proven 2026-06-11):** the parser is *resident* — installed into
`/opt/blarai/parser/app/` at provision time and auto-started by the `blarai-parser` OpenRC
supervisor on every guest boot. There is no rolling bundle-deploy loop. The launcher's
`deploy()` step is a no-op on the resident path (`gp_config.resident`); `launcher/__main__.py`
skips straight to `start()` — health-check only. The `incoming/` supervisor model and
Copy-VMFile bundle protocol from the original design brief are superseded by the CD ISO
channel.

**CD ISO channel (re-provision procedure):** code changes are synced into the ISO payload
at `build/guest_cd/parser/`, `SHA256SUMS` is regenerated, and a new ISO is built via
`build/guest_cd/build_iso.ps1`. The operator attaches the ISO as the VM DVD in Hyper-V
Manager, then runs `mount /dev/cdrom /mnt && sh /mnt/provision.sh` at the Hyper-V console.
`provision.sh` stops `blarai-parser`, copies `/mnt/parser/.` into `/opt/blarai/parser/app/`,
verifies `SHA256SUMS`, and restarts the service. See §3 and §6.

**The one permanent manual step:** attaching the ISO in Hyper-V Manager and running the
mount + provision call at the console. Everything after provisioning (start / health-check /
stop) is fully host-automatable via the launcher.

## 2. The extraction stack and its pins

Guest facts (#655 comment 1045): Alpine 3.21 / Python 3.12. The in-guest stack as actually
installed at the 2026-06-11 controlled session:

- **lxml** — actual installed version is **6.1.1 from pip wheels** (NOT apk). Alpine 3.21's
  `py3-lxml` package is 5.3.0, which does NOT satisfy trafilatura 2.1.0's `>=6.1.1` floor;
  the apk-sourced lxml plan in the original design brief was incompatible and was superseded
  at the controlled session. The actual wheel
  (`lxml-6.1.1-cp312-cp312-musllinux_1_2_x86_64.whl`) is in `build/guest_cd/wheels/` and
  installs into the venv via pip along with the rest of the closure. The host pin
  (`requirements/ingest-cleaner.txt`, lxml 6.1.1 cp311-win) and the guest version now match
  on major.minor.
- Everything else installs from `requirements/guest-parser.txt` — the ingest-cleaner.txt
  closure **minus lxml** (17 packages), same versions, **no `--hash` entries** (pip's
  hash-checking mode would refuse the musllinux platform wheels that were never pinned for
  the host). Install is offline and resolution-free:
  `pip install --no-index --no-deps --find-links wheels/ -r wheels/guest-parser.txt`.

**Integrity chain (two links, each verified):**

1. **PyPI → host** — `scripts/stage_parser_wheels.ps1` downloads the closure targeting
   cp312/musllinux_1_2_x86_64, then verifies every wheel's SHA-256 against the LA-approved
   hash universe in `requirements/ingest-cleaner.txt`. Wheels outside that universe are
   permitted ONLY for the named platform-wheel packages (regex, charset-normalizer), are
   loudly warned, and land in `staging_report.json` for operator spot-check against PyPI.
   Anything else aborts the staging.
2. **Host → guest** — `build/guest_cd/SHA256SUMS` (LF-terminated, sha256sum -c format,
   binary `*` mode) covers every wheel + the full parser source tree + `provision.sh`; the
   in-guest provisioning script runs `sha256sum -c SHA256SUMS` and refuses to install on any
   mismatch. This is corruption/transfer integrity — the host is the trust root; the
   guest's containment value is the other direction: hostile parser input cannot reach the
   host process.

## 3. The re-provision runbook (CD ISO channel)

This is the repeating procedure for every future guest code update. Estimated operator time:
\~5 min. Add a VHDX backup step before destructive or structural changes; a code-only
re-provision via the idempotent `provision.sh` does not require one.

**Agent-side (autonomous, before the ceremony):**

1. Make code changes to the relevant source files under `services/` and/or `shared/`.
2. Sync the changed files to the ISO payload mirror at `build/guest_cd/parser/` (same
   relative path under `services/` or `shared/`). Use `shutil.copy2` or equivalent;
   preserve line endings.
3. Regenerate `build/guest_cd/SHA256SUMS`:
   - Covers: `wheels/`, `parser/**`, `scripts/`, `provision.sh` — NOT `SHA256SUMS` itself,
     NOT `build_iso.ps1`.
   - Format: LF line endings; `sha256sum -c`-compatible; binary mode prefix (`*`):
     `<64-char-hash> *<path-relative-to-cd-root>`.
4. Rebuild the ISO:
   `pwsh -File build/guest_cd/build_iso.ps1 -Source build/guest_cd -Output build/guest_cd.iso -VolumeName BLARAI_PROV`
   **ACL WARNING (load-bearing — cost a failed VM start on 2026-06-13):** rebuilding the
   ISO *in place* creates a new file that does NOT inherit Hyper-V's per-VM read grant
   (`NT VIRTUAL MACHINE\<vm-guid>:(R)`). If the VM then tries to start with that stale
   path attached, it fails `0x80070005` (Access denied). The LA ceremony step 2 re-attach
   (`Set-VMDvdDrive` / GUI re-select) re-grants the ACL automatically — this is why the
   re-attach is mandatory after every rebuild, not optional. (Quick fix if a rebuild
   shipped without a re-attach: `icacls <iso> /grant "NT VIRTUAL MACHINE\<vm-guid>:(R)"`.)
5. Commit the **canonical source edits** (under `services/` / `shared/`) + this record to
   the feature branch. NOTE: `build/` is gitignored — the payload mirror, `SHA256SUMS`,
   and the rebuilt `.iso` are **local build artifacts**, not committed. They live only on
   the build machine, which is also the Hyper-V host, so they are already where the
   ceremony needs them (no transfer step).

**LA ceremony (\~5 min at Hyper-V console):**

1. **Re-attach the ISO while the VM is Off** (re-grants the Hyper-V read ACL — see the §3
   agent-side ACL warning). Hyper-V Manager → VM Settings → DVD Drive → re-select
   `build/guest_cd.iso` as the image file, Apply. (Re-selecting the *same path* still
   re-applies the per-VM ACL grant the in-place rebuild stripped; merely confirming the
   path is attached does NOT.) Then start the VM.
2. At the Hyper-V console (Alpine login), mount the CD with the filesystem type made
   **explicit** and run the provisioner:
   `mount -t iso9660 -o ro /dev/sr0 /mnt && sh /mnt/provision.sh`
   The `-t iso9660` is load-bearing: a cold-booted busybox guest does not auto-detect the
   CD filesystem, so a bare `mount /dev/cdrom /mnt` fails `Invalid argument` (EINVAL). Use
   `/dev/sr0` (the Gen-2 SCSI DVD); if it reports no such device, substitute `/dev/cdrom`.
   The script stops `blarai-parser`, copies updated files, verifies `SHA256SUMS`, restarts
   the service. Version lines + `OK` from sha256sum confirm success (\~30 s).
3. Verify the service: `rc-service blarai-parser status` → `started`.
4. **Verify the change is live (off the egress path):** from the host, run
   `./.venv/Scripts/python.exe scripts/uc003_markdown_verify.py` (or the analogous
   parse-only smoke for a later change). It sends a fixture over the vsock parse channel
   and checks the returned text — NO fetch, NO `guarded_fetch`/adjudicator/`egress_guard`.
   GREEN is the acceptance evidence (template:
   `docs/security/uc003_markdown_verify_2026-06-13.md`). Prefer this over a live
   `/ingest <url>`, which would hit the deliberately welded egress door.

## 4. What is verified vs. what remains pending

**Verified at the 2026-06-11 controlled session** (evidence:
`docs/security/uc003_live_fetch_proof_2026-06-12.md`): CD ISO channel; `provision.sh`
stop/copy/SHA256SUMS-verify/restart sequence; lxml 6.1.1 from pip wheels (satisfies
trafilatura 2.1.0's `>=6.1.1` floor); venv closure; `blarai-parser` OpenRC auto-start on
boot; host vsock-service GUID registration (`0000c351-facb-11e6-bd58-64006a7986d3`,
port 50001); AF_HYPERV connect on port 50001; the end-to-end frame-level health round-trip
through `launcher/parser_channel_seam.py`.

**Copy-VMFile root cause (closed):** the 2026-02-25 `P5_GUEST_CHANNEL_NOT_READY` failure
was not a daemon-not-started issue — the kernel device is gone (kernel 6.12.74, fcopy
removed; `0x800710DF`). The CD ISO channel is the permanent proven replacement.

**Verified at the 2026-06-13 re-provision (UC-003 markdown extraction):** the rebuilt ISO
(`build/guest_cd.iso`, 22,675,456 bytes) carrying `include_formatting=True` in
`extraction.py` + the `vsock.py` drift fix was re-attached, mounted, and provisioned into
the guest; a heading/list/bold fixture parsed in the guest returned markdown markers
(`#`/`##`/`**`/`- `, status `clean`, 212 words, confidence 1.000) over the vsock channel —
`docs/security/uc003_markdown_verify_2026-06-13.md` (+ `.json`). No egress was touched.

**Two runbook defects found + fixed during this re-provision** (proactive — both were
defects in this record's prior runbook, surfaced by the real ceremony):

1. **Mount auto-detect.** The prior `mount /dev/cdrom /mnt` failed `Invalid argument` —
   busybox does not auto-detect the CD filesystem on a cold boot. Corrected to
   `mount -t iso9660 -o ro /dev/sr0 /mnt` (§3), verified working.
2. **In-place-rebuild ACL strip.** Rebuilding the ISO at the same path created a file
   lacking Hyper-V's per-VM read ACL, so VM start failed `0x80070005`. The fix is the
   mandatory re-attach (§3 ceremony step 1), which re-grants the ACL; `icacls` is the
   manual fallback. Now documented as load-bearing, not optional.

**Unit-tested baseline** (61 tests in `launcher/tests/`): launcher lifecycle state machine
and fail-closed paths remain in the standing gate unchanged.

## 5. Fail-closed behaviour matrix (host-side lifecycle)

> **Resident model note:** the guest parser runs on the resident path (`gp_config.resident`);
> `deploy()` is a no-op. Rows `GP_GSI_DISABLED`, `GP_SOURCE_MISSING`, and `GP_COPY_FAILED`
> are unreachable at runtime in this configuration — they apply only if the bundle-deploy
> path is ever activated. All other rows apply unchanged.

| Condition | Result | Code |
|---|---|---|
| `[guest_parser] enabled=false` (shipped default) | capability unavailable; boot unaffected; URL ingest refuses | — |
| Config missing/unparseable/typed wrong | capability unavailable (loud) | `GP_CONFIG_*` |
| `service_guid` ≠ hv_sock template for `vsock_port` | refuse at config load | `GP_CONFIG_GUID_MISMATCH` |
| VM not Running at deploy | FAILED | `GP_VM_NOT_RUNNING` |
| Guest Service Interface disabled | FAILED | `GP_GSI_DISABLED` |
| Parser service source dir absent (parallel branch not landed) | FAILED | `GP_SOURCE_MISSING` |
| Any Copy-VMFile failure (incl. trigger) | FAILED | `GP_COPY_FAILED` |
| vsock listener never reachable in budget | FAILED | `GP_HEALTH_TIMEOUT` |
| No health probe bound (integration pending) | FAILED — parser can never be READY | `GP_CHANNEL_UNBOUND` |
| Health frame check fails / probe raises | FAILED | `GP_HEALTH_FAILED` / `GP_HEALTH_PROBE_ERROR` |
| READY parser stops answering (crash, guest restart) | READY → FAILED, availability withdrawn | `GP_HEALTH_LOST` |
| Guest child crashes 3× in 120 s | supervisor exits → listener gone → host sees `GP_HEALTH_LOST` | (guest-side) |
| Backup requested while VM not exactly `Off` (or state unknown) | backup refused | exit 2 |

In every row the ONLY downstream effect is **refusal of URL-mode ingest**; there is no
host-parsing fallback anywhere in the code (ADR-030 §3's named anti-pattern).

## 6. Key artifacts and evidence

| Artifact | Location | Notes |
|---|---|---|
| ISO payload source | `build/guest_cd/` | Sync target for code updates |
| Built ISO | `build/guest_cd.iso` | Attach as VM DVD for re-provision; 22,675,456 bytes post-2026-06-13 rebuild |
| ISO build script | `build/guest_cd/build_iso.ps1` | IMAPI2-based; pass `-VolumeName BLARAI_PROV` |
| SHA256SUMS | `build/guest_cd/SHA256SUMS` | LF, `*` binary mode, 37 entries (post-2026-06-13 rebuild) |
| Round-trip proof | `docs/security/uc003_live_fetch_proof_2026-06-12.md` | 2026-06-12 health probe PASS (this one fetched) |
| Markdown verify (parse-only, no egress) | `scripts/uc003_markdown_verify.py` + `docs/security/uc003_markdown_verify_2026-06-13.{md,json}` | 2026-06-13 GREEN — formatting markers live in guest; the egress-free verification template |
| VHDX backup | `C:\HyperV\BlarAI\backups\Orchestrator_20260611_161145.vhdx` | Pre-provision snapshot |
| In-guest evidence | `/opt/blarai/parser/evidence/provision.json` (guest FS) | Written by provision.sh at each run |
| Vikunja tracking | #655 (UC-003 program), #662 (guest deploy channel) | #655 comment 1045 = original guest facts |
