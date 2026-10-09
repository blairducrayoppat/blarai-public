---
paths:
  - "CLAUDE.md"
  - ".claude/**"
  - "docs/governance/agent-doctrine-evidence.md"
  - "docs/governance/rules-*"
  - ".claude/rules/doctrine.md"
---
<maintenance>
- Register of CLAUDE.md and .claude/rules/*: terse-directive, agent-only. Updates keep that register.
- Register discipline (LA 2026-08-17, #1442): every rule is an imperative with a one-clause reason. Incident stories and dates go to docs/governance/agent-doctrine-evidence.md — appended in the same motion as the rule they justify — never inline in CLAUDE.md, .claude/rules/* or .claude/agents/*. Decision provenance and operational dates stay. Reserve emphasis for the few load-bearing rules; dense emphasis stops carrying information.
- Volatile state lives ONLY in <status_snapshot>, refreshed at merge clusters and replaced (not appended).
- Doctrine changes to CLAUDE.md or .claude/rules/ follow the same rules as any ship: feature branch, journal entry if a judgment was made, DECISION_REGISTER row if a governance posture changed.
- Deliberately excluded (do not re-add): phase-history tables, per-merge test-count archaeology, legacy role-name mappings and devplatform fleet-management doctrine (that fleet is being sunset), Vikunja label IDs/priority scales (discoverable via list_labels).
- Doctrine freshness is GATE-ENFORCED (tests/security/test_doctrine_freshness.py, #945 D8): the snapshot's gate figure must equal TEST_GOVERNANCE §1's LIVE_GATE_BASELINE line (update both in the count-changing commit); hot surfaces carry size budgets; always-loaded files are scanned for retired-world vocabulary; ACTIVE_SPRINT's refresh date must track main. A doc whose stated maintainer is a retired role is stale by definition — re-own it or retire it the day the role dies.
</maintenance>
