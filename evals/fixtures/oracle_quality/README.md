# oracle_quality fixtures (#765)

- `b2_reference/app/` — a FROZEN known-good implementation of the B2 text-stats
  goal, harvested 2026-07-07 from a battery run that went GREEN (all tasks
  merged + the job oracle passed on the integrated tree). The soundness cases
  run generated/fixture oracles against it: a correct oracle MUST pass here.
- `b2_job_oracle.py` — the 14B-written job-level oracle that graded that GREEN
  run (plan-carried bytes; the per-task seed-guard header stripped). Offline
  cases pin it as the known-good oracle exemplar.

Sensitivity mutations are defined in the golden cases (append-override
transforms applied to a TEMP COPY of the reference — fixtures are never
mutated in place).

The SAME two fixtures also back the `contract` (#752-F3 import/contract) and
`criteria-coverage` golden cases (`oq-contract-*` / `oq-covg-*`) — no
separate fixture files were needed: `declared_exports` and `criteria` ride
inline in the golden JSONL, checked against `b2_job_oracle.py`'s real
imports and the real B2 behavior criteria.
