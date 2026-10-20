---
paths:
  - "docs/**"
  - "scripts/**"
  - "tools/**"
  - "tests/**"
  - ".claude/rules/identity.md"
x-blarai-commands:
  - 'scrub_public_identifiers'
  - 'identity_lock'
  - 'rotate_log'
  - 'hf_publish'
---
<identity_hygiene priority="standing-control">
- Before any public snapshot, dataset upload or post that links one: run `python scripts/scrub_public_identifiers.py` then `python scripts/scrub_public_identifiers.py --check` (exit 0) so the host name leaves the tree and the operator name leaves the containment evidence and performance records deterministically; the scrub is a standing control, never a question put to the LA (evidence: docs/governance/agent-doctrine-evidence.md, 2026-10-14 #1765).
- The operator's account name never spreads (ratchet, `scripts/identity_user_baseline.json`): a new file, or a listed file carrying it more often than listed, fails `--check` and the gate; the remedy is to write `%USERPROFILE%` or `__USER__` in that file by hand, never to extend the list; a listed count follows the file down: lowered to the file's count, and the file dropped at none, in the same change; a count above the file's is a finding (LA 2026-10-14 #1765).
- Text moved between files (journal rotation, archive volumes, copies into reviews) is a new file to the ratchet: the name reads `__USER__` before it is written anywhere new; `tools/doc_hygiene/rotate_log.py` refuses otherwise.
- A `--check` failure the scrub does not clear (a shape the lock sees but the rewrite does not cover) is a hand edit, named in the scrub's log and output; never a widened list, never a loosened lock.
- Land any branch touching the ratchet's files (`scripts/identity_user_baseline.json`, `scripts/scrub_public_identifiers.py`, `scripts/identity_lock.py`) or the research-tracker lock's (`scripts/research_tracker_baseline.json`, `scripts/research_tracker_lock.py`) with `git merge --no-ff`: a fast-forward puts every intermediate baseline version on main's reference line; the reference reads the last 20 baseline versions, so a growth that merged ungated stops being seen after 20 more (#1781).
</identity_hygiene>
