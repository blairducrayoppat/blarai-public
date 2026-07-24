# RAM Headroom Assessment — what is movable, what is not, and what each move costs

**Date:** 2026-07-15 · **Ticket:** #897 · **Census data:** `docs/performance/ram_census_2026-07-15.json` + PERFORMANCE_LOG.md entry of the same date
**Machine:** ASUS ExpertBook P5405CSA — Intel Core Ultra 7 258V (Lunar Lake), 32 GB on-package memory, Intel Arc 140V integrated GPU, Windows 11 Pro build 26200, BIOS P5405CSA.328 (latest)

---

## 1. Bottom line

1. **The firmware reservation (692.8 MB) is normal, fixed, and closed as a topic.** It is set by the firmware at every boot, sits almost exactly at the platform default for this chip family, and no setting on this laptop can change it. Reclaimable: ~0 MB. (§3 has the evidence, including the checks run against the possibility of a past pre-allocation configuration — none exists.)
2. **The real reclaimable memory is in background software: roughly 1.5–3 GB**, dominated by Microsoft Edge's login-time preload (149 background processes, ~3.0 GB of committed memory at census time), plus Copilot, Widgets, Game Bar, and similar autostarts. This is one coarse go/no-go decision (§5.1).
3. **The biggest BlarAI-side lever is compressing the model's conversation memory (the "KV cache" — key-value cache): ~0.6–0.9 GB** at typical context length, more at long contexts — the switch already exists in our config, the measurement data already exists (#708/#709), and only the quality-gated live flip remains (#899). A second, subtler finding: this exact chip is known to **hold GPU memory after models are unloaded** instead of returning it to Windows, which matches our past "insufficient memory with 22 GB free" incident — #900 now tracks verifying our eviction paths actually free what they claim (§6).
4. **Nothing recommended here weakens the security posture.** The two levers that would (disabling virtualization-based security; trimming the antivirus) were evaluated and are recommended AGAINST or left explicitly to you (§5.3–5.4).

Expected outcome if the recommended set is applied: **~2–4 GB more standing headroom** on a 31.3 GB budget, plus meaningfully lower risk of stalls/failures during 10–20 GB model-load spikes.

---

## 2. What was measured (census summary)

Full data in the JSON. Highlights, taken 2026-07-15 under real conditions (a concurrent session's test-gate run live during part of the capture):

| Measurement | Value |
|---|---|
| Installed / visible to Windows | 32 GiB / 31.323 GiB (**692.8 MB hardware-reserved**) |
| In use near-idle (dev sessions running) | 16.31 GB |
| In use under build + model load | 28.23 GB (only 3.10 GB available) |
| The 14B model resident on GPU | **~9.7 GB of system RAM** (GPU-shared; invisible in per-process working sets) |
| Microsoft Edge background | 149 processes, ~3.0 GB private |
| Bitdefender antivirus | ~1.0 GB private (high-normal for real-time AV) |
| Windows Search indexer | 22 MB, already in narrow "Classic" mode — **not** a problem on this machine |
| Hyper-V parser VM | Off, 0 MB (dynamic memory, floats at 512 MB when on — #661) |
| Memory compression / SysMain | Both off — verified **correct** for this workload (§4) |
| Pagefile | Auto-managed 19 GB; peaked at 11.75 GB this boot |

Method note: RAM is measured as In-Use = Total − Available throughout (never working-set sums), per the project's standing accounting rule.

---

## 3. The firmware reservation — closed with evidence

**What the 692.8 MB is:** physical memory the firmware excludes from Windows' map at boot. On this chip it is dominated by the integrated GPU's pre-allocated framebuffer (~512 MB inferred platform default) plus smaller firmware regions (system-management code, the Intel management engine, power-configuration tables, firmware runtime services, and firmware for the AI accelerator and sensor hub). The chip's much-discussed 8 MB "memory-side cache" is on-die silicon, not carved from the 32 GB.

**Why it is not movable on this machine — four separate verifications:**
1. **No BIOS lever exists.** ASUS ExpertBook-class firmware exposes no graphics pre-allocation setting (consistent vendor pattern; no model-specific exception found). The BIOS is already the latest (328; changelogs mention nothing about memory).
2. **No boot-configuration cap is set** (verified directly: no `truncatememory`/`removememory` entry — the "MSConfig maximum memory" trap is not engaged).
3. **No past pre-allocation configuration survives on this machine** (verified directly, answering the Lead Architect's recall of possibly having configured something: no Intel `GMM`/`DedicatedSegmentSize` registry tweak, no graphics-driver memory overrides, nothing memory-related anywhere under the Intel registry tree, GPU dedicated-memory counter at zero). If something was configured historically, it was most plausibly the Intel driver's "Shared GPU Memory Override" — which governs a *dynamic* pool that borrows from normal RAM on demand and returns it, and therefore never touches the hardware-reserved figure — or it did not survive a driver/BIOS update.
4. **The number itself is diagnostic:** 693 MB sits in the expected default band. A surviving raised pre-allocation would show >1.2 GB; a lowered one, <500 MB.

**Verdict: ~0 MB reclaimable. Do not spend further effort here.**

---

## 4. Settings verified correct as-is (no action)

- **Memory compression OFF** — on a 32 GB machine running large-model inference, compression's CPU cost on hot paths outweighs its benefit; OFF is the standard recommendation for this profile. (One nuance: during evict/reload churn, compression would absorb some pagefile traffic. Not compelling enough to flip; the pagefile fix in §5.2 addresses the same risk more directly.)
- **SysMain (prefetch service) disabled** — correct on a machine with a fast solid-state drive; its predictive preloading would compete with the resident model for RAM.
- **Windows Search** — already in narrow "Classic" mode and holding only 22 MB. The commonly-cited ~1 GB indexer reclaim does not exist on this machine.
- **The parser VM's memory config (#661)** — already optimal. Two fresh recommendations from this study's research (switch to static; tighten the 2 GB cap) were both checked against the decision record and found already adjudicated: with dynamic memory the assignment floats at the 512 MB floor (measured), the 2 GB cap costs zero at rest and exists purely as spike headroom, and the VM is Off outside launches anyway.
- **Standing rule reaffirmed:** never schedule standby-cache purges ("RAM cleaner" utilities) — the standby cache is what makes model reloads fast; purging it would force disk re-reads.

---

## 5. Your decisions (each is one coarse yes/no)

### 5.1 Background-app cleanup batch — RECOMMENDED: YES (~1.5–3 GB standing)
One approval applies all of these; name any you actually use and I will skip it:
- **Edge login-time preload off** ("Startup Boost" + "continue running background apps when Edge is closed") — the source of the 149 background processes / ~3 GB. Cost: Edge's first launch each session is a beat slower.
- **Copilot autostart off** — it relaunches on demand; only the always-on preload goes.
- **Widgets off**, **Xbox Game Bar + game capture off** (also frees GPU capture overhead), **Intel "Endurance Gaming" off** (a gaming battery limiter, 142 MB, no value here).
- **OneDrive autostart** — flagging rather than recommending: if you rely on OneDrive sync, it stays.
- Not touched: KeePass preload (yours), Logi Tune (yours), Vikunja (required), Bitdefender, Windows security tray.

### 5.2 Fix the pagefile at a generous floor — RECOMMENDED: YES (robustness, not RAM)
Model loads spike committed memory by 10–20 GB. Today the pagefile is auto-managed: it grows only when nearly full, and that growth stall lands mid-model-load — the failure shape is an abrupt "out of memory" from the inference stack. Setting a fixed 24–32 GB pagefile on the 1 TB drive eliminates the stall and the failure mode at a cost of reserved disk only. Needs one reboot to take effect. (Never disabling the pagefile — that removes the safety margin entirely.)

### 5.3 Virtualization-Based Security — RECOMMENDED: NO CHANGE (evaluated, rejected)
What runs on this machine is the lightweight boot-integrity half (Secure Launch + firmware measurement); the two expensive components (Credential Guard, memory-integrity enforcement) are already off. Disabling the rest would reclaim only ~100–300 MB and remove the machine's firmware-level root of trust — a bad trade for a security-first project. Presented for transparency, not as an open question.

### 5.4 Bitdefender — YOUR CALL, split into two honest halves
- Its ~1 GB standing footprint is the cost of real-time antivirus; it cannot be meaningfully reduced without turning protection off. Recommendation: accept it.
- Separately, adding **scan exclusions for the model-weights and build directories** would NOT reduce RAM but would remove antivirus scanning latency from every model load (a real speed win). The trade: those directories go unscanned. Mitigation that exists anyway: BlarAI independently verifies signed weight manifests at boot, so model files are integrity-checked by us regardless. This is a security-posture change, so it is yours to make.

---

## 6. BlarAI-side levers (mine; ticketed, quality-gated)

- **#899 — engage KV-cache compression on the resident 14B.** The conversation-memory cache costs 160 KB per token of context at full precision (~1.3 GB at 8K context; ~5 GB at 32K). 8-bit compression halves it; 4-bit (new in substrate 2026.2) cuts it to about a third, with upstream reporting accuracy parity specifically for 4-bit-weight models like ours. The config switch (`kv_cache_precision`) already exists and is deliberately disengaged pending exactly this evaluation. The draft model's cache gets the same treatment (it is 70% of the 14B's per-token cost — not free). Ships only after our own quality-evaluation gate passes and you sign off, since answer quality is yours.
- **#900 — verify eviction actually returns memory on this chip.** Upstream reports (from this study's research-agent thread review — not yet independently verified on our hardware; that verification is exactly this ticket's job) say this chip *retains* GPU memory when idle where the next chip generation releases it, that on integrated GPUs the cache limits may not bound system-RAM growth, and that repeated load/unload cycles are only fully recovered by process exit. Our past "insufficient memory with 22 GB actually free" incident matches this pattern. The ticket instruments our real evict paths (image-generation eviction, 14B evict/reload, embedding-cache idle-unload) with In-Use deltas; if the driver holds memory, the fix is running big image jobs in a short-lived separate process (exit guarantees Windows gets the memory back) plus the substrate's new memory-mapped model-cache import (reportedly ~85% faster reloads). Our measurements here are also exactly what the upstream issue threads lack — a community-contribution opportunity (engagement-first, on-thread coordination before code).
- **Cross-references updated:** standing memory ticket #564's audit note ("3 GB KV cache is fixed") is now stale and has been annotated; its residual question (should host mode start the VM at all) stays open there.

---

## 7. Honest boundaries of this study

- All census numbers were taken with development sessions running; a true zero-load idle baseline is still unmeasured (worth one capture on a quiet morning).
- Per-lever savings above are researched/derived, not yet measured on this machine; each applied lever gets a before/after In-Use measurement recorded per the performance-capture rule (the after-picture is the next entry in this study).
- The 2 GB "vmmemCmZygote" process seen in the census is a dormant Windows container stub (Application Guard / Windows Sandbox plumbing), commits ~776 MB of address space but holds 0 MB of physical RAM — cosmetic, not a consumer.
- Compile-time RAM spikes for the 14B on this GPU, cache-blob sizes, and whether the driver's memory-release behavior affects us in practice are all "measure locally" items — they live in #899/#900, not in estimates here.
