# Work Plan — From-Source GPU Build Capability Proof (OpenVINO + GenAI on Arc 140V)

**Author:** Claude (persistent-KV upstream session, 2026-07-06)
**For:** the scheduling/orchestrator agent coordinating the next ~2 days/nights of work.
**Status:** EXECUTED — **capability PROVEN 2026-07-06.** Phase 1 (GPU plugin built from source: 89 MB `openvino_intel_gpu_plugin.dll`, ~40 min at `-j8`, registered in `plugins.xml`) + Phase 2 (GenAI C++ samples built against the local core → **coherent LLM inference on the Arc 140V**, ~40 tok/s via `benchmark_genai -d GPU`; `greedy_causal_lm` on GPU returned correct coherent text) both DONE. Records: `PERFORMANCE_LOG.md` 2026-07-06 + `docs/performance/gpu_plugin_from_source_capability_proof_2026-07-06.json`. Phase 3 (current-OpenVINO refresh for the KV feature) remains conditional/future. The GenAI **Python** stack was ALSO proven the same day (**#753**): core rebuilt `ENABLE_PYTHON=ON` (`_pyopenvino.cp311.pyd` + `openvino_c.lib`) + GenAI `py_openvino_genai`, and `openvino_genai.LLMPipeline(model, "GPU").generate()` from Python 3.11.9 returned coherent output (`devices: ['CPU','GPU','NPU']`). So **both the C++ and Python paths** to the from-source GPU plugin are proven. Reuse env: `OPENVINO_LIB_PATHS=<core bin>` + `PYTHONPATH=<core>/python;<genai build-gpu>`; throwaway build venv `oss/ovpy-venv` (Cython/pybind11). Two fiddly bits recorded on #753 (`Development.Module` → explicit `-DPython3_INCLUDE_DIR/_LIBRARY`; `OPENVINO_LIB_PATHS` for the from-source layout).
**Related:** Vikunja #710 (OSS: persistent-KV feature request, filed as `openvinotoolkit/openvino.genai#4091`); Vikunja #711 (in-house prefix-cache A/B — NOT dependent on this build, see §7); #4082 (xgrammar fix, GPU-verify gap this build can close — see §7).

---

## 1. Purpose (why this work exists)

We want to contribute a **persistent / savable-restorable KV-cache** capability to OpenVINO GenAI (issue #4091; maintainer @Wovchena's preferred direction is a first-class savable/restorable cache object + arch review). Before we offer Intel that we can *implement and validate* it, we must confirm one unproven capability: **that we can build the OpenVINO Intel GPU plugin from source on this machine and run inference through it on the Arc 140V.**

We have never done this. We have built OpenVINO *core* + CPU plugin from source, and OpenVINO GenAI from source, but **the GPU plugin has never been linked** (confirmed: `2026-07-05_xgrammar-fix-verified-and-filed.md` journal entry, and no `openvino_intel_gpu_plugin.dll` exists in the build tree). That gap is why the #4082 xgrammar fix could only be verified on CPU.

**This plan proves the capability and does the prep. It does NOT commit us to building the full KV feature** — that is a larger, separate effort gated on (a) this proof succeeding and (b) Intel showing arch-review appetite on #4091.

---

## 2. Verified current state on disk (2026-07-06)

| Fact | Value | Source |
|---|---|---|
| OpenVINO source checkout | `C:/Users/mrbla/oss/openvino` @ commit `e4e180d` (pinned for the NPU-compiler work; older than 2026.2.1) | `git rev-parse` |
| CMake configured with GPU? | **YES** — `ENABLE_INTEL_GPU = ON`, and configure **succeeded** (GPU build-deps already found: OpenCL, VS2022, Ninja) | `ov_configure.log` |
| GPU plugin built? | **NO** — the build command only targeted `openvino_intel_npu_plugin` + `ov_dev_targets` + `compile_tool`. But the GPU plugin's CMake rules/objects dir **already exists** (`build-x86_64/RelWithDebInfo/src/plugins/intel_gpu/CMakeFiles/openvino_intel_gpu_plugin.dir/`) | `build_ov.cmd`, `find` |
| Existing build tree size | 13 GB (`build-x86_64/RelWithDebInfo`) | `du` |
| Prior partial build wall-clock | ~1h41m (`CONFIGURE_OK 18:57 → BUILD_OK 20:38`, 2026-06-10) at `-j4`, BelowNormal throttle | `ov_build_status.txt` |
| Build flavor | RelWithDebInfo, `ENABLE_DEBUG_CAPS=ON`, `ENABLE_PYTHON=OFF` | `build_ov.cmd` |
| **Free disk on C:** | **~215+ GB free** — a 2026-07-06 cache cleanup reclaimed ~175 GB (HuggingFace cache 132 GB, Temp 38 GB, uv/pip/npm caches; was 41 GB / 96% full). **Disk prerequisite RESOLVED** — no longer a blocker; even a Phase-3 fresh checkout now fits. | measured |
| GenAI checkouts | `C:/Users/mrbla/oss/openvino.genai` and `.../openvino.genai-pr-worktree` (the #4082 fork branch) | `ls` |
| Toolchain | VS2022 BuildTools (`vcvars64.bat`), CMake+Ninja — all present and proven working | `build_ov.cmd` |

**Net:** this is an **incremental build on an already-configured tree**, which is the fast path. The hard setup (submodules, toolchain, GPU dependency discovery) is already done and proven.

---

## 3. The work, in phases

### Phase 0 — Pre-flight (attended, ~10 min)
1. **Disk — ALREADY SATISFIED** (~215+ GB free after the 2026-07-06 cleanup; see §2). No action needed; just re-confirm with `Get-PSDrive C` before a big build.
2. Confirm no other heavy build is mid-flight in `oss/` (the other agent's scheduled builds may contend for cores/disk — coordinate).
3. **Do NOT overlap the 23:00 night battery** — the GPU-plugin compile is an all-core, multi-hour job; running it concurrently with the 23:00 test/eval battery starves both. Sequence them: either finish the compile before 23:00, or start it after the battery completes. See §8.
4. Re-confirm the GPU driver present (Arc 140V, driver `32.0.101.8826` per PERFORMANCE_LOG) so the runtime smoke test in Phase 2 can enumerate `GPU`.

### Phase 1 — Build the GPU plugin (mostly UNATTENDED, ~2–4 h throttled / ~1.5–2.5 h at `-j8`)
Incremental build of the one missing target on the existing tree:

```cmd
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
cd /d C:\Users\mrbla\oss\openvino
echo GPU_CONFIGURE_START %date% %time% > C:\Users\mrbla\oss\ov_gpu_build_status.txt
cmake --build build-x86_64\RelWithDebInfo --target openvino_intel_gpu_plugin -- -j 4 ^
    > C:\Users\mrbla\oss\ov_gpu_build.log 2>&1
if errorlevel 1 ( echo GPU_BUILD_FAILED %date% %time% >> C:\Users\mrbla\oss\ov_gpu_build_status.txt & exit /b 1 )
echo GPU_BUILD_OK %date% %time% >> C:\Users\mrbla\oss\ov_gpu_build_status.txt
```

- Use `-j 4` + BelowNormal (cores 3-7) if the operator needs the machine during the day; `-j 8` unthrottled overnight when he's away (faster). Mirror the throttling approach already used in `build_ov.cmd`.
- **Monitor** via `ov_gpu_build_status.txt` (poll) + tail `ov_gpu_build.log`. This matches the existing status-file pattern the scheduler already knows.
- **Success = `openvino_intel_gpu_plugin.dll` produced** (expected under `build-x86_64/RelWithDebInfo/bin/.../` — confirm exact path at build time) and present in the built `plugins.xml`.

### Phase 2 — Rebuild GenAI against the local GPU-capable core + smoke-test on GPU (attended-ish, ~1 h)
The #4082 ABI wall was: release-wheel `.pyd` vs local-core mismatch. Building GenAI **against this same local core** (not the release wheel) avoids it, and now the core will *have* a GPU plugin to load.

```cmd
cd /d C:\Users\mrbla\oss\openvino.genai
cmake -S . -B build-gpu -G Ninja ^
    -DCMAKE_BUILD_TYPE=RelWithDebInfo ^
    -DOpenVINODeveloperPackage_DIR=C:/Users/mrbla/oss/openvino/build-x86_64/RelWithDebInfo ^
    -DENABLE_PYTHON=ON
cmake --build build-gpu -- -j 4
```
*(Confirm the exact developer-package var/path at run time — OpenVINO exposes `OpenVINODeveloperPackage_DIR` pointing at the core build dir. Adjust if the tree uses a different export.)*

**Smoke test (the actual capability proof):** with the local build's runtime + plugins on `PATH`, run a minimal `LLMPipeline` generate on `device="GPU"` against a small OpenVINO IR (e.g. the existing Qwen3-0.6B draft or any converted small model) and confirm **coherent output from the from-source GPU plugin**. Compare a one-line output against the release wheel on GPU as a sanity cross-check.

**Decision gate:** GPU plugin builds + links + runs coherent inference from source → **capability PROVEN**. Record it (PERFORMANCE_LOG + a short note). If it fails, capture the exact error and fall back to the §5 Option-B offer (Intel CI validates GPU).

### Phase 3 — (CONDITIONAL / FUTURE, not part of this proof) Refresh to current OpenVINO for the real feature
Only if (a) Phase 1–2 succeed AND (b) Intel greenlights KV-cache work on #4091. The existing tree is pinned to old `e4e180d`; the feature must be built against current `master`/release. This is a **full-core rebuild** (bigger, ~half-to-full day) and **needs substantial free disk** — schedule the cleanup first. Flagged here so the scheduler can reserve a later slot; do not start it now.

---

## 4. Time & attention summary (for scheduling)

| Phase | Wall-clock | Operator/agent active attention | Machine profile |
|---|---|---|---|
| 0 Pre-flight | ~15 min | full | light |
| 1 GPU plugin build | 2–4 h (throttled) / 1.5–2.5 h (`-j8`) | ~5 min to kick off, then unattended | **all-core, sustained, heat** |
| 2 GenAI rebuild + GPU smoke test | ~1 h | ~45 min | moderate build + short GPU run |
| **Proof total** | **~half a day, mostly unattended** | **~1 h active** | CPU-bound compile |
| 3 (future feature build) | ~half–full day | ~1–2 h | full rebuild; needs disk |

**Best slotting:** Phase 1 into an **unattended/overnight window at `-j8`** (fits the operator's existing overnight pattern; he's away, machine free, no throttle needed). Phases 0 and 2 need him/an agent semi-present, so pair them either side of the overnight compile (kick off Phase 1 at night → verify Phase 2 in the morning).

---

## 5. What this unlocks (the offer to Intel)

- **Proof succeeds →** we can honestly offer Intel the *full* contribution on #4091: design + core savable/restorable-cache logic + CPU unit tests + **independent GPU validation on Arc 140V** + benchmark. Highest-credibility offer.
- **Proof fails →** we offer the same *minus* independent GPU validation, leaning on OpenVINO's own GPU CI runners for the GPU proof (a normal outside-contributor arrangement). Still strong, still cooperative.

Either way we don't overpromise — the proof result decides which offer we make.

---

## 6. Resource / environment notes

- **CPU:** Core Ultra 7 258V, 8 cores, fanless → sustained all-core compile self-heats; throttle (cores 3-7, BelowNormal, `-j4`) when the operator is using the machine, unthrottle (`-j8`) overnight. (Matches the throttle-background-builds standing preference.)
- **RAM:** 32 GB is ample for `-j4`/`-j8` OpenVINO builds; GPU-plugin link is the memory peak but well within budget.
- **Disk:** the binding constraint — see §8.
- **No network dependency** for the incremental build (submodules already fetched). A Phase-3 fresh checkout would re-fetch.

---

## 7. Synergy opportunities (map against the other agent's scheduled work)

The reviewing agent should check these against what's already scheduled — some effort here plausibly satisfies other work:

1. **A reusable from-source GPU-capable OpenVINO build** is a general capability, not single-use. It unblocks **any** future OpenVINO **GPU-plugin** upstream contribution, GPU bug **reproduction-from-source**, and GPU **patch validation**. If the schedule contains any OpenVINO GPU-plugin fixes/repros (cf. the `openvino_2026.2_upgrade_opportunity_catalog` and the prior NPU-plugin contribution line), this build is a **shared prerequisite** — do it once, both benefit.
2. **Retroactively closes the #4082 GPU-verify gap.** The xgrammar fix (#4082) was verified only on CPU because we had no from-source GPU build. Once this build exists, we can **re-verify the xgrammar fix on the GPU from source** and post that as a strengthening follow-up on #4082 — turning a disclosed limitation into a completed GPU proof. Same build, second win.
3. **Toolchain / build-tree warm-up is shared.** Any other scheduled from-source OpenVINO or GenAI build reuses this configured tree, the compiled core objects (13 GB already built), and the warm toolchain — so ordering this *before* other source-build work amortizes setup.
4. **Coordinate the target commit for Phase 3.** If other scheduled work also needs a *current*-OpenVINO from-source build, pick ONE refresh commit that serves all consumers and build it once, rather than two multi-hour checkouts. (Disk makes two full trees impractical anyway — see §8.)
5. **Disk cleanup is likely already needed** and could be a shared prerequisite — freeing space benefits this build, the Phase-3 refresh, and anything else disk-bound in the schedule.
6. **NOT a synergy (avoid false coupling):** the in-house **prefix-cache A/B (#711)** runs on the **release wheel**, not a source build — it does **not** need this GPU build and should not be blocked on it.

---

## 8. Risks & fallbacks

| Risk | Likelihood | Mitigation |
|---|---|---|
| ~~Disk exhaustion~~ **RESOLVED** | — | 2026-07-06 cleanup reclaimed ~175 GB → ~215+ GB free. No longer a constraint for Phase 1 or a Phase-3 fresh checkout. |
| **Overlap with the 23:00 night battery** | **High if unscheduled** | The GPU-plugin compile is all-core + multi-hour and will contend with the 23:00 test/eval battery. **Sequence, don't overlap:** finish before 23:00 or start after the battery. Kicking a `-j8` compile at, say, ~19:00 leaves margin; a late-night start should wait for the battery to finish. |
| OpenCL / Level-Zero link errors on first GPU-plugin link | Low–Med | Configure already **passed** with GPU=ON (deps discovered), which removes the biggest risk. Capture full `ov_gpu_build.log` on any failure; most fixes are a missing SDK/loader path. |
| Old commit `e4e180d` GPU numerics differ from 2026.2.1 | Low (irrelevant to proof) | The proof question is "can we build + run GPU from source," which is commit-independent. Feature work uses the Phase-3 refreshed commit. |
| ABI mismatch (the #4082 wall) | Low | Avoided by building GenAI against **this same local core**, not the release wheel. |
| Fanless thermal throttling during compile | Low (cosmetic) | Only affects wall-clock, not success; overnight `-j8` is fine. |
| Contention with the other agent's scheduled builds | Med | Scheduler serializes heavy builds; don't run two all-core compiles concurrently on 8 cores. |

---

## 9. Success criteria (checklist for the executing agent)

- [ ] Phase 0: ≥ ~20 GB free confirmed; no contending build; GPU driver present.
- [ ] Phase 1: `openvino_intel_gpu_plugin.dll` built; appears in the local `plugins.xml`.
- [ ] Phase 2: GenAI rebuilt against local core (`ENABLE_PYTHON=ON`), loads without the #4082 ABI error.
- [ ] Phase 2: `LLMPipeline` generate on `device="GPU"` from the **from-source** build returns coherent output.
- [ ] Result recorded (PERFORMANCE_LOG + note on #710); capability PROVEN/FAILED stated plainly.
- [ ] (If proven) draft the calibrated full-capability offer for #4091; (optionally) the #4082 GPU re-verify follow-up.

---

## 10. Explicitly out of scope here

- Writing any KV-cache feature code (gated on Intel arch-review appetite + this proof).
- Posting anything to Intel (the operator posts; drafts only, on his approval).
- The Phase-3 current-OpenVINO refresh (future slot, needs disk).
- The prefix-cache A/B (#711) — independent, release-wheel-based.

**Reviewing agent:** please slot Phase 1 into the best unattended/overnight window, confirm the disk prerequisite, and check §7 against the live schedule for shared-prerequisite ordering. Flag back anything that changes the sequencing.
