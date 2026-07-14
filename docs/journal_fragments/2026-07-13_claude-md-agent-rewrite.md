### 2026-07-13 — The doctrine file stopped talking to nobody

*Plain summary: CLAUDE.md rewritten from accumulated prose into an
agent-directed XML doctrine file — audience declared as Claude sessions only,
the ever-growing Active State chapters retired in favor of a replace-not-append
status snapshot, the comprehension gate given a full six-part specification,
security-by-design codified as thirteen named principles, and the sunsetting
devplatform fleet-management references scrubbed. Doctrine/governance surface;
no runtime code touched.*

The old CLAUDE.md had grown the way doctrine files grow when nobody decides
who they are for: a project-instructions header written for a human, an
Active State section that appended a new test-count chapter at every merge
until the history outweighed the instructions, and the actual operating rules
scattered between them. The User-Operator asked the pointed question that
started the arc: would a fresh agent reading this actually understand him —
a non-technical Lead Architect — and the way he needs agents to work? Walking
that question through the file honestly, the answer kept coming back no. The
rules were there; the person they served was not.

The rewrite went through several deliberate turns, each an LA call made in
session. First: center the User-Operator — who owns WHY versus HOW, the
never-ask-him-a-technical-question rule, the build-merge-dormant-then-present
arc that keeps him out of manufactured mid-work approval gates. Second: close
the gaps a stress-test surfaced — the host device, the stack top to bottom,
the repo constellation, git discipline for a shared multi-agent tree where he
cannot rescue a mistake, and the testing seam-lessons. Third, the structural
decision: the audience is Claude sessions only, so the file became XML-tagged
directives in second person rather than prose — precision over readability,
accepting that the LA himself will never comfortably read his own project's
doctrine file. The rejected alternative was keeping a dual-audience prose
document; it was rejected because every prior revision showed the two
audiences pulling the register apart, and the LA reads the project through
Vikunja and the journal, not through doctrine.

The costliest trade-off was retiring the Active State section. Hundreds of
lines of per-merge test-count archaeology (3225 → … → 7909) carried real
history — and made the file stale within a sprint, by its own admission. The
replacement is a dated `<status_snapshot>` capped at ~15 lines that gets
REPLACED at merge clusters, never appended, with the history left where it
already lives: the ledger, the journal, the tickets, and git history holding
the full prior file. If a future session mourns the lost detail, the mourning
is the point — doctrine should point at live state, not embalm it.

Two late passes earned their keep. An adversarial ambiguity hunt found seven
real conflicts the drafting had created — the worst being that "merge dormant"
read as unconditional while "proven features default LIVE" sat three sections
away, and that the comprehension gate as written would deadlock a headless
dispatch agent waiting for a confirmation that cannot come. And the LA's
final question — will they understand the security level? — exposed that the
security section stated posture without principles: an agent could follow
every literal rule and still bolt security on at the end. The new
`<security_by_design>` names thirteen principles distilled from controls this
project actually shipped (fail-closed, structural absence over configuration,
every-control-tested-OFF, and the rest), with the level check stated plainly:
the shipped controls are the bar; match them, never dilute them.

**Next:** live-verify the file does its job — the next fresh session's
comprehension gate is the test (it should arrive grounded, gate properly, and
not re-ask anything the file answers). Refresh `<status_snapshot>` at the next
merge cluster to prove the replace-not-append discipline holds. Open the
relocation ticket for the Vikunja server binary before the devplatform sunset
date is set.

*(commits: `<this>` (the rewrite + this fragment); doc-only diff, standing
gate re-run on merged main as post-merge verification.)*
