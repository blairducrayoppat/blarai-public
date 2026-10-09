---
paths:
  - "tests/**"
  - "**/tests/**"
  - "**/test_*.py"
  - "**/conftest.py"
  - "docs/TEST_GOVERNANCE.md"
  - "evals/**"
  - ".claude/rules/testing.md"
x-blarai-commands:
  - '\bpytest\b'
---
<testing priority="the-project's-control-system" ssot="docs/TEST_GOVERNANCE.md">
<standing_gate>
- Selection: `pytest shared/ services/ launcher/ tests/integration/ tests/security/ -m "not hardware and not winui and not slow"`. Fast form: `python scripts/run_standing_gate.py` (6 parallel groups, same tests, about 12 min vs 24; exits 3 if the count differs from the single collection). Bar: 0 failed, 0 skipped in a clean environment. A skip is investigated, never waved through. Current counts live in <status_snapshot> + the ticket record — never pin them elsewhere in doctrine.
- Deselected tiers run at their own ceremonies: @hardware (model-loaded, real Arc 140V), @winui (C# headless project), @slow. Model-quality eval gate: `python -m evals.run --suite all` — committed baselines, regression exit codes with teeth.
- Every fix ships its regression lock in the same change. New/changed timeouts register in shared/timeout_registry.py (itself gate-locked).
</standing_gate>
<seams note="hardest-won lesson class">
- Mocks lie. Canonical failures: mock-passes-but-prod-crashes (mock-shape divergence); built-but-wired-into-nothing (control exists, nothing calls it — recurred repeatedly). Therefore: drive REAL objects through REAL entry points; verify REACHABILITY, not just behavior; live-verify on the actual system before claiming done. The screen has caught what three green sweeps missed.
- Test the boundary itself, not both sides separately: vsock handshake, IPC dispatcher, WinUI↔backend passthrough allowlist (gate test parses the C# array, fails loudly naming missing commands), egress door driven through the REAL policy checker.
- Author ≠ verifier: adversarial review stays independent; the reviewer never writes the fix.
</seams>
<protect_the_gate>
- ALWAYS redirect LOCALAPPDATA for pytest — an unredirected run corrupted the real sessions.db.
- The gate must not kill / be killed by the live system. Pattern-match every new test against the known kill shapes (each has happened; each now has a structural control): a leaked service turning failures into silent skips; an in-test instance-lock os._exit killing the collector mid-run; a boot-reconcile tree-killing a live dispatch.
- Environmental deltas are named, not ignored: non-elevated → 3 symlink skips; missing gitignored models → router-test env-skips; live app → port-5001 skips. Benign only because documented and bounded. An unexplained skip is a defect.
- Baselines are evidence: an eval baseline once encoded a parser bug as expected behavior. Cross-check baselines on substrate changes; re-measure known-fail cases at every hardware ceremony.
</protect_the_gate>
</testing>
