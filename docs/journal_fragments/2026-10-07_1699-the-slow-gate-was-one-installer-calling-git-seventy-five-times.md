### 2026-10-07 — The slow gate was one installer calling git seventy-five times

*Plain summary: The test gate took 27 minutes instead of 11 because new security tests each run a hook installer that starts 75 small git programs; batching those into a handful cut each install from about 3 seconds to 1, with the checks unchanged and a test now proving each one still fires.*

The gate had read 554 s on 09-22 and about 1480 s on 10-07, and every explanation I could have offered from one or two readings was a guess. So I ran the older tree and the current one, alternately, on the same idle machine with an instrument that refuses to start unless the laptop is untouched and on mains power: 703 and 693 s for the old tree, 1632 and 1687 s for the new, both pairs within 3.5 % of each other. The box was not the cause. Summing time per test file attributed 884 of the 954 s difference to twelve test files that did not exist on 09-22, the git-hook tooling of #1690. Profiling one install showed 75 git processes at about 36 ms each: a hash per file, a blob read per file, and eleven repeated lookups of the same directory.

The tempting fix was a tiered subset of those tests, and it was not mine to take: moving tests out of the standing gate changes coverage of a security control, which is the operator's call. Batching the calls keeps every test in. The installer is itself a security control, so the review mattered more than the speed-up: it found that a corrupt object made the refusal name the wrong file, and, worse, that I could disable the check that the written copy matches main's blob and all 271 existing git tests still passed. They had never been able to tell. Both were fixed, and each verification now has a test that fails when it is removed (eight mutations, eight failures).

What it taught me about measuring: the profile came after the control, not instead of it. Had I profiled first I would have found a slow installer and optimised it without knowing it explained 93 % of the gap.

Trade-off: the batched hash is all-or-nothing, so one unreadable installed file now shows every file as drifted in the review; I accepted that because the direction is fail-closed and the alternative needs a per-file fallback I could not exercise.

**Next:** time the gate again on the idle box with the change merged, and decide from the per-file sums whether anything else is worth touching.
