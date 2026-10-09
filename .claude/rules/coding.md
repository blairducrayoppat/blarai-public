---
paths:
  - "**/*.py"
  - "**/*.pyi"
  - "**/*.cs"
  - "**/*.ps1"
  - "**/*.js"
  - "**/*.ts"
  - ".claude/rules/coding.md"
---
<coding_standards>
Docstrings/comments state defaults, contracts and conditionals — NEVER current wiring or sprint state ("empty this sprint", "no live consumer today", "dormant until X ships"). A ceremony flips config and runbooks; nobody reopens the docstrings, so every time-anchored claim rots into a false security assertion. Where current state must be named, point at the authority (default.toml, the runbook), never restate it.
Python: strict type hints, PEP 8. Deterministic execution (temperature-0 equivalent). Gate-check order: Compile → Test → Oracle. Deterministic failure fingerprinting. Match surrounding code's idiom and comment density.
</coding_standards>
