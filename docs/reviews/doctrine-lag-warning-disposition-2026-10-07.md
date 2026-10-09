# Disposition — independent adversarial review of #1703 (SessionStart doctrine-lag warning)

**Review:** independent adversarial-reviewer session (did not author the change), run against
`f55589d2`. Verdict: block until findings 1 and 2 are fixed; the check itself behaved correctly in
every shape constructed through the real entry point.
**Author of the change and of this disposition:** this session.
**Outcome:** all six findings resolved in `281d3f33`; two sub-points of finding 6 are recorded as
limits in the hook's docstring.

```disposition
R1 the lock certifies CLAUDE.md, .claude/rules and .claude/settings.json but every fixture changes only CLAUDE.md, so dropping either of the other two paths left the suite green (75 passed under both mutations) | FIXED | 281d3f33 - test_each_doctrine_path_alone_makes_a_lag is parametrized over rules, settings, agents and CLAUDE.md, each changed alone on main
R2 the merge-base error branch (returncode not in 0,1) is untested; mutating it to read as in sync stayed green | FIXED | 281d3f33 - test_an_ancestor_check_that_errors_is_loud_not_in_sync drives an unborn HEAD so merge-base fails and asserts the loud notice
R3 synced_checkout leaks a scratch repo into the temp directory every run because read-only git objects defeat rmtree on Windows | FIXED | 281d3f33 - the atexit rmtree now clears the read-only bit and retries; the blarai-lag-* count in the temp directory did not grow across the next full run of the file
R4 the SessionStart failure text says rules were NOT delivered for this tool call, which is false at SessionStart | FIXED | 281d3f33 - the failure notice is event-specific and says the lag check did not complete and is UNKNOWN; the test asserts both the new wording and the absence of the old
R5 the SessionStart hook timeout is 15 s while each git call could take 10 s and up to four are made | FIXED | 281d3f33 - the per-call cap is 3 s, so four calls stay inside the 15 s budget; stated in the docstring
R6 limits worth recording: comparison is against the local refs/heads/main, .claude/agents is outside the paths, a cherry-picked copy reads as lagging | FIXED | 281d3f33 - .claude/agents added to DOCTRINE_PATHS (doctrine.md names it a register surface) and the other two limits are written into the docstring
```

## Reviewer observations kept for the record

- Incidence at review time: 11 of 16 existing trees lag main's doctrine and none contains this
  hook, so the warning fires in none of them until each merges main. The control protects trees
  created after it lands; this is stated on #1703.
- Not reproduced, and not claimed: nothing about Claude Code's own handling of a hook that exceeds
  its timeout was tested; the 3 s cap removes the reachable case instead.
