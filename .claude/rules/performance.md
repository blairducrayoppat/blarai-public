---
paths:
  - "PERFORMANCE_LOG.md"
  - "docs/performance/**"
  - "tools/probes/**"
  - "evals/**"
  - "scripts/*bench*"
  - "scripts/*measure*"
  - "scripts/*probe*"
  - ".claude/rules/performance.md"
x-blarai-tools:
  - '^mcp__plugin_github_github__'
  - '^WebFetch$'
x-blarai-commands:
  - '(^|[\s;&|(])gh\s'
  - 'bench'
  - 'measure_'
  - 'probe'
  - '\bevals\.run\b'
  - 'Start-ScheduledTask'
  - 'schtasks'
  - 'api\.github\.com'
---
<performance_capture priority="non-optional">
- Every hardware/model performance test gets recorded AT THE TIME IT RUNS: benchmarks, load/latency, memory, probes. Unrecorded = incomplete task (same standing as ship-without-journal).
- Where: dated narrative entry in PERFORMANCE_LOG.md + machine-readable JSON in docs/performance/ (the community-contribution dataset).
- Community-grade format: hardware (CPU+GPU), OpenVINO + GPU-driver versions, model + precision, methodology (prompt set/config/run count), measured numbers, AND name what was NOT measured.
- External contributions: engagement-first (coordinate on the issue thread before code); share proven results promptly; GitHub API for comments/review-state (WebFetch of HTML misses them); check pulls/{n}/reviews before claiming "unreviewed"; never cite a SHA externally without verifying against file history.
- Identifier hygiene for anything published (the scrub, the ratchet) is `.claude/rules/identity.md`.
</performance_capture>
