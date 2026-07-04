# BlarAI-Orchestrator VM — Lifecycle Runbook

> **Who this is for**: anyone operating or debugging the BlarAI launcher's
> Hyper-V VM lifecycle (`BlarAI-Orchestrator`, Dynamic Memory 512 MB–2 GB
> since #661 — see §5).
>
> **Short version**: the launcher stops the VM when BlarAI exits. If you ever
> find the VM still `Running` after BlarAI is closed, this doc tells you why and
> how to release it.

---

## 1. What the launcher does on exit

On a clean exit the launcher's `atexit` cleanup (`launcher/__main__.py` →
`_cleanup` → `_cleanup_vm`) applies the **stop-on-exit policy** to the VM. The
policy is resolved per-launch and logged in `launcher.log`, with the *reason* a
stop did or did not happen on the same line.

### Stop-on-exit policy (`vm_stop_on_exit`)

| Value | Behaviour | When to use |
|-------|-----------|-------------|
| `always` | **(DEFAULT)** Stop the VM whenever it is currently `Running`, regardless of whether this launcher started it. No spurious `Stop-VM` when the VM is already `Off`/`Saved`. | Normal single-user operation — the assistant releases its memory assignment (Dynamic Memory, \~512 MB–1 GB; see §5) on every close. |
| `if_started` | Stop the VM **only** if this launcher started it this boot (legacy behaviour). | Parallel-dev: another session/tool owns the VM and this launcher must not yank it out from under that session. |
| `never` | Never stop the VM; leave it `Running` on exit. | Deliberately keeping the VM warm across launches. |

Set the policy via the environment variable **`BLARAI_VM_STOP_ON_EXIT`**
(case-insensitive) before launching, e.g.:

```powershell
$env:BLARAI_VM_STOP_ON_EXIT = "if_started"   # opt into legacy behaviour
```

An unrecognised, empty, or unset value resolves to the safe default (`always`)
— a typo can never silently re-arm a leak. The unrecognised value is logged as a
WARNING.

The log lines to look for in `%LOCALAPPDATA%\BlarAI\launcher.log`:

- `Cleanup: stopping Hyper-V VM (policy=always, VM is Running, was_started=...)`
- `Cleanup: leaving VM as-is (policy=always, VM not Running: state=...)`
- `Cleanup: stopping Hyper-V VM (policy=if_started, this launcher started it this boot)`
- `Cleanup: leaving VM running (policy=if_started, VM was already running at boot)`
- `Cleanup: leaving VM running (policy=never)`

If `stop_vm()` does not confirm the VM reached `Off` within its \~30s timeout (a
slow shutdown, or `Stop-VM` itself failing), cleanup logs a WARNING and still
completes — the exit path never crashes on a slow stop. The WARNING includes the
manual one-liner below.

---

## 2. Manual stop (one-liner)

If the VM is still running and you want it down:

```powershell
Stop-VM -Name "BlarAI-Orchestrator"
```

Check its state:

```powershell
Get-VM -Name "BlarAI-Orchestrator" | Select-Object Name, State
```

---

## 3. `AutomaticStartAction` MUST stay `Nothing`

The VM's Hyper-V `AutomaticStartAction` is set to **`Nothing`** (set 2026-06-10).
**Do not change it back to `StartIfRunning`.**

`StartIfRunning` re-inflates a *leaked* VM at every Windows boot: if the VM was
left `Running` when Windows shut down (a crash, a hard power-off, a leak), Hyper-V
resurrects it on the next boot — silently consuming its startup allocation
(1 GB under Dynamic Memory; see §5) before BlarAI is ever launched. With `Nothing`, the VM only ever starts when the BlarAI launcher starts
it. Verify / re-assert:

```powershell
# Verify
Get-VM -Name "BlarAI-Orchestrator" | Select-Object Name, AutomaticStartAction
# Re-assert if it ever drifts
Set-VM -Name "BlarAI-Orchestrator" -AutomaticStartAction Nothing
```

---

## 4. The leak this fixed (background)

Before the 2026-06-10 fix, the launcher only marked the VM "mine to stop" if it
was **not** already running at boot (`_vm_was_started`), and `_cleanup` stopped
it only under that flag. The consequence was an ownership **ratchet**: once the
VM was *ever* left `Running` across a launcher start — a crash, a hard console
close that killed the process before the \~30s `Stop-VM` completed, a host reboot
that resurrected it (via the old `StartIfRunning`), or another tool starting it —
every subsequent *clean* exit then skipped the stop, and the leak
self-perpetuated forever. The signature in `launcher.log` was a cleanup that ran
`Cleanup: stopping Policy Agent service` → `Cleanup: complete` with **no**
`Cleanup: stopping Hyper-V VM` line in between.

The `always` default closes the ratchet: the stop decision is now based on the
VM's *current* state, not on who started it. The `if_started` value preserves the
old behaviour for the parallel-dev case where it is actually correct.

---

## 5. Memory sizing — Dynamic Memory (since #661, 2026-06-13)

The VM was **static 2 GiB** until 2026-06-13. It now runs **Hyper-V Dynamic
Memory**, because the guest homes *only* the NIC-less trafilatura parser
(UC-003) — the LLM, VLM, and voice all run host-side, so every GB the VM pins is
taken straight from the host's 31.323 GB budget.

| Setting | Value |
|---------|-------|
| `DynamicMemoryEnabled` | `True` |
| Minimum | 512 MB |
| Startup | 1 GB |
| Maximum | 2 GB |

**Measured behaviour** (cold boot, parser idle + a 60 s sustained \~248 KB-parse
burst; `scripts/measure_guest_parser_memory.py`; see `PERFORMANCE_LOG.md`
2026-06-13): the balloon engages \~60 s after boot and reclaims `MemoryAssigned`
to the **512 MB floor**, held through both load and idle. Idle demand is \~199 MB
and the sustained-parse peak demand is \~256 MB — both far below the floor, so the
assignment floats at 512 MB regardless of the 2 GB maximum. Net: **\~1.5 GB
returned to the host** versus the old static 2 GiB, while the 2 GB max preserves
spike headroom (never worse than the old static ceiling under load). **The hot-add direction —
growth above the 1 GB startup toward the 2 GB ceiling — was NOT exercised here:**
demand never reached even the 512 MB floor (peak 256 MB, \~half the floor, a
deliberate headroom choice), so the ceiling's protective value rests on the
*assumed* `hv_balloon` hot-add path, not a measured one (the reclaim/shrink
direction is proven by the 1024 → 512 MB drop). 195
consecutive near-cap parses ran with zero OOM; the parser reached READY 34.5 s
into a cold boot (well inside the `health_timeout_s = 120` budget).

**Why Dynamic Memory and not a smaller static value:** a static 1 GB would
reclaim only \~1 GB and leave the parser no spike headroom; DM reclaims \~1.5 GB at
rest *and* can still grow to 2 GB if a future heavier parse needs it. The balloon
driver (`hv_balloon`) is present in the Alpine guest — proven by the assigned
1024 → 512 MB reclaim, since only ballooning can drop the assignment below the
startup value.

**Apply / re-assert** — the VM must be **Off** (Dynamic Memory cannot be toggled
while the VM is running):

```powershell
Set-VMMemory -VMName "BlarAI-Orchestrator" -DynamicMemoryEnabled $true `
  -MinimumBytes 512MB -StartupBytes 1GB -MaximumBytes 2GB
```

**Revert to the old static 2 GiB** (also VM-Off):

```powershell
Set-VMMemory -VMName "BlarAI-Orchestrator" -DynamicMemoryEnabled $false -StartupBytes 2GB
```

The launcher does **not** set or assert VM memory at boot — `vm_manager` only
starts/stops/queries the VM — so this `Set-VMMemory` definition persists across
every launch with no launcher change needed.

---

## 6. Automatic checkpoints — DISABLED (since 2026-06-13)

`AutomaticCheckpointsEnabled` is set to **`False`** on `BlarAI-Orchestrator`.
**Do not re-enable it.**

Hyper-V's automatic checkpoints snapshot the VM (and spin up a differencing
`.avhdx`) on every start. On this VM that is a hazard, not a convenience: the
guest parser is updated by re-running the CD-ISO `provision.sh` at the Hyper-V
console (the proven guest-update channel — see #662), and a stray **Revert** on a
lingering automatic checkpoint would silently roll the guest back, undoing a
re-provision with no error. With the feature off and no checkpoints present, there
is no revert target.

Surfaced 2026-06-13: an "Automatic checkpoint detected — Revert / Continue /
Cancel" prompt appeared during a failed VM start (the `guest_cd.iso` ACL-after-
rebuild incident). A clean launcher stop had already merged the open checkpoint
forward into the base `Orchestrator.vhdx` (automatic checkpoints merge forward on
a clean stop — they do **not** roll back), so disabling the feature left the disk
consolidated with nothing to revert to.

```powershell
# Verify
Get-VM -Name "BlarAI-Orchestrator" | Select-Object AutomaticCheckpointsEnabled  # expect False
Get-VMCheckpoint -VMName "BlarAI-Orchestrator"                                   # expect no output
# Re-assert if it ever drifts back on (VM may be Off or Running)
Set-VM -Name "BlarAI-Orchestrator" -AutomaticCheckpointsEnabled $false
```

> **Companion lesson (for #662's guest-update runbook):** rebuilding
> `build/guest_cd.iso` *in place* replaces the file and strips the per-VM ACL
> Hyper-V needs to open it, so the next start fails closed (`0x80070005`,
> "service Account does not have permission to open attachment"). After every ISO
> rebuild, re-grant the VM read ACL
> (`icacls <iso> /grant "NT VIRTUAL MACHINE\<vm-id>:(R)"`) or re-attach via
> `Set-VMDvdDrive` (which re-grants automatically).
