# Sprint 18 — Comprehension-Gate Confirm (guide-reviewed; relay to the execution agent)

Paste the block below to the Sprint-18 execution agent. It confirms the gate and carries
two pre-flight heads-ups (the skip-signature disambiguation + the production-security-material
check) plus three no-action confirmations. None change the wave plan.

---

**Sprint 18 — comprehension gate CONFIRMED. Dispatch the wave (P first).**

Your understanding is accurate on all 7 criteria, the P→M/N/O fan-out, the serial single-GPU
model-load order (C1→C2→C3), and the gate-runnable vs agent-run split. Base verified
independently from the main checkout: `main` is clean at `0b9fed5` (the SDV commit), toplevel
correct, only the known unrelated files in the tree. Scope is baked; you have no open decisions.
Go.

Three things to carry into the run — all pre-flight, none alter the plan:

**1. Distinguish the two gate skip-causes by signature — do not conflate them.** The clean
standing-gate baseline is **2342 passed / 0 skipped / 108 deselected**, and that exact number is
only guaranteed from the **MAIN checkout** (the embedding model lives there). Two *different*
things cause skips, and only one is C6's target:
- **Port-5001 leak (C6's target):** a leaked AO on loopback 5001 makes the **boot-cascade** tests
  skip → ~**2333/9**. This is the non-determinism you are fixing.
- **Model-absence in a worktree (NOT a leak):** a builder **worktree** does not have the embedding
  model, so ~20 **semantic_router** tests skip → ~**2320/22**. The Sprint-17 SWAGR reproduced
  exactly this in a worktree (2320/22/108/0). It is expected and is *not* what C6 fixes.

So: confirm the clean **2342/0** by running the authoritative gate from the **main checkout**. If
you re-run inside a worktree and see ~2320/22, check *which* tests skipped before reacting —
router/embedding skips = model-absence (fine, ignore), boot-cascade skips = the port-5001 leak
(the real bug). Do not read a worktree's 22 router-skips as a leak; that would send C6 chasing a
non-bug, or worse, mask the real one.

**2. Pre-flight the production security material, exactly as you pre-flighted the model.** C1/C2/C5
run in production posture (`dev_mode=False`, production mTLS, signed manifest). You confirmed the
Qwen3-14B is on disk (8.42 GB) — now also confirm the **production security material is provisioned
for a `dev_mode=False` start** *before* you commit to those tiers: the mTLS certificate material,
the signed manifest present on disk, and TPM access. Sprint 17's on-chip ceremony very likely left
all of it in place (`require_signed_manifest=true` is live and the real-TPM cascade passed), so this
is a *verify*, not a *build* — but do it as pre-flight so a missing cert surfaces now, not after
you have authored every test file. If any piece is genuinely absent, mark that tier committed-≠-done
with an explicit home (SDV §7) rather than letting it skip silently into the gate.

**3. Three confirmations — no action needed:**
- Your **C4 reading is correct**: it is slow-marked, so you run it with `-m slow`; it is *not* in
  the bare `not slow` standing gate. The SDV's "green in the standing gate" was loose shorthand —
  your reading is the right one.
- **Landing P fully before M/N/O fan out** (rather than strictly concurrent) is the right call:
  P's autouse conftest changes fixture resolution for the whole harness, so a stable post-P base is
  worth the few minutes, and the long pole is the serial GPU runs anyway. Batching C1/C2/C3 into as
  few model loads as the shared fixtures allow is also right.
- The **~40 stale worktrees**: inventory-not-delete is correct, and it is correctly *not* this
  sprint. Leave them; flag as a post-sprint housekeeping note if you want, but do not act on it now.

Automate-first holds: you run every tier yourself, including the model-loaded ones — this confirm is
the LA's first of two touches, the close is the second. Surface a genuine posture/quality/capability
**decision** (named, with alternatives) if one appears; otherwise proceed straight through to the
close, and the guide will verify your merge-gate + SWAGR when you report.

---
