# Guest Oracle Provisioning Record — #744 Go-Live Ceremony (2026-07-08)

**Status:** PROVISIONED + LIVE 2026-07-08 (LA-supervised ceremony). Corridor proven in
both directions BEFORE the production wiring was written; registration + knob flip
merged as `097605d` (branch `feat/744-guest-oracle-service`).
**Governs:** the provisioning + re-provisioning of the guest-certified oracle service
(`blarai-oracle`) in the BlarAI-Orchestrator Hyper-V guest (Alpine Linux 3.21,
NIC-less, Python 3.12.12).
**Relates to:** Vikunja #744 (design c.1404-1410, transport c.1444-1445, ceremony
comments of 2026-07-08); the UC-003 parser precedent
(`docs/security/guest_parser_provisioning_record.md` — the access-mechanism table
there, CD-ISO channel + dead Copy-VMFile, applies verbatim); #615 (AF_HYPERV
addressing); ADR-030 §3 (guest-homed composition pattern).

---

## 1. What was provisioned

A SEPARATE service from the proven UC-003 parser — own prefix, own venv, own OpenRC
unit, own vsock port. `provision_oracle.sh` never touches the parser install (never
churn a live, go-live-proven corridor to serve a new one).

| Item | Value |
|---|---|
| Service | `blarai-oracle` (OpenRC, runlevel default, auto-start on guest boot) |
| Listener | AF_VSOCK port **50002** (`0xC352`; the parser owns 50001) |
| hv_sock GUID (host-registered) | `0000c352-facb-11e6-bd58-64006a7986d3` |
| Prefix | `/opt/blarai/oracle` (`venv/`, `app/`, `bin/`, `run/`, `evidence/`) |
| Entry module | `shared.fleet.guest_oracle_service` (`--allow-plaintext` bring-up; mTLS env plumbing dormant) |
| Supervisor | `oracle_supervisor.sh` (fail-closed: 3 crashes/120 s → supervisor exits → host reports honest `not-run guest-unreachable`) |
| In-guest runtime | Python 3.12.12; **pytest 9.1.1**, **hypothesis 6.155.7** (+ pluggy 1.6.0, iniconfig 2.3.0, pygments 2.20.0, sortedcontainers 2.4.0, attrs 26.1.0) — all pure-Python wheels, installed offline |
| Bundle | `shared/fleet/{guest_oracle,guest_oracle_service}.py` + `shared/ipc/{oracle_channel,protocol}.py` (import-discipline-verified: stdlib + shared.ipc only) |
| Evidence (in-guest) | `/opt/blarai/oracle/evidence/provision.json` (`service_started: 1`) |

## 2. The channel + the one manual step

Same as the parser record §1: the CD ISO is the only host→guest file channel
(Copy-VMFile confirmed dead on kernel 6.12.74). This ceremony's ISO:
`build/guest_cd_744.iso` (25,131,008 bytes; new name because the old
`guest_cd.iso` was attach-locked as the VM's then-current DVD). Payload =
`oracle/` bundle + `provision_oracle.sh` + `scripts/{blarai-oracle.initd,
oracle_supervisor.sh}` + the 7 new wheels, all covered by the regenerated
`SHA256SUMS` (54 entries, verified on host and again in-guest before install).

Operator console step (run at the Hyper-V console, LA executed 2026-07-08):

    umount /mnt 2>/dev/null; mount -t iso9660 /dev/cdrom /mnt && sh /mnt/provision_oracle.sh

Host registry step (elevated, idempotent, reversible —
`scripts/register_parser_vsock_service.ps1 -VsockPort 50002`):
`HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Virtualization\GuestCommunicationServices\0000c352-facb-11e6-bd58-64006a7986d3`.

## 3. The live proof (run BEFORE the production wiring)

1. **Reachability** — `GuestOracleBridge.reachable()` through the discovered
   `py -3.14` bridge: **True** (first live host↔guest contact on the corridor).
2. **Pass direction** — a real snapshot (calc.py + a passing pinned-path oracle)
   through `make_guest_oracle_transport(vsock_port=50002)`:
   `{"status": "passed", "evidence": "exit 0; … 1 passed in 0.40s"}` — real pytest,
   in the guest, over AF_HYPERV.
3. **Fail direction** — the same oracle over broken code: `{"status": "failed"}`
   with the real pytest failure text. A guest that cannot say no proves nothing;
   this one can.

## 4. The wiring (the ceremony's conscious amendments, merged `097605d`)

- `swap_ops.real_run_guest_oracle` registers the transport factory
  (`GUEST_ORACLE_VSOCK_PORT = 50002`); factory failure degrades fail-soft to an
  honest `not-run` — never a raise into the swap teardown.
- `[fleet_dispatch].guest_oracle_enabled = true` (default-proven-to-LIVE).
- The four former dormancy locks amended to pin the LIVE posture: call-site
  registration lock (+ port-parity with the guest service), registration-CONTAINMENT
  scan (swap_ops is the one sanctioned wiring site), toml ships-enabled lock, and
  the pipeline lock now injects a factory seam — its first post-flip run reached
  the REAL guest from inside pytest, so tests never live-call the corridor.
- Pipeline `transport` default stays `None` (that lock is unchanged).

## 5. First light (the first driver-invoked run, in the RAM-free window)

Run `20260708-140241-bd` (a small dispatched Python job, post-flip, post-AO-reboot):
the driver invoked the guest-oracle phase in the RAM-free teardown window and wrote
the first driver-produced certificate:

    {"schema": "guest-oracle/v1", "advisory": true, "status": "not-run",
     "reason": "flat-queue-mode", "host_status": "not-run", "divergence": false}

Honest shape: the tiny goal decomposed to one task, the PLAN degraded to flat-queue
(the #760 grain class), and a flat-queue job has no job oracle to certify — so the
correct certificate is a reasoned `not-run`, which is exactly what landed (trail
line present; verdict untouched). The GRADED in-driver certificate self-proves in
the campaign: every plan-mode Python battery job now produces one, and the
consumption half (scorecard evidence + agreement tally + morning-report line with
a DIVERGENCE banner) merged the same afternoon (blarai `7356d11e`, agentic-setup
`ca0a8dd`). The corridor's pass/fail grading itself was live-proven pre-wiring (§3).

## 6. Re-provisioning recipe

Code changes: sync the bundle (`build/guest_cd/oracle/…` from the repo modules),
regenerate `SHA256SUMS` over `wheels parser oracle scripts provision.sh
provision_oracle.sh`, rebuild the ISO (`build_iso.ps1 -Source . -Output
..\guest_cd_<tag>.iso`), attach in Hyper-V Manager, run the §2 console command.
The parser record's §3/§4 runbook defects (fs auto-detection → always
`-t iso9660`; never rebuild an ISO in place while attached) apply.

## 7. Posture notes

- Advisory-only: the guest verdict lands beside the scorecard as
  `guest-oracle.json`; host verdict/attribution are UNTOUCHED. Whether a
  host-pass/guest-fail divergence ever GATES remains an open LA decision (#744).
- Plaintext-AF_HYPERV bring-up on a local VM boundary (the #615/#655 posture);
  mTLS plumbing dormant on both sides (populate the cert env vars / factory
  params — no code change).
- Node-oracle jobs report honest `not-run non-python-oracle` (pure-Python guest
  scope per the accepted design).
