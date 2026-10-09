### 2026-09-18 — The rescue bricked the thing it was written to rescue

*Plain summary: if BlarAI's audit signing key ever had to change, the Policy Agent would refuse to
start and never start again. I built the fix. The fix would have bricked it on the second start
instead of the first — and the only reason that had never happened is that the repair procedure
pointed at a file that does not exist, so nobody could run it. Two defects hiding each other.*

The defect was real and the ticket had it right. Measured on a real chain: records written before a
key change need the retired key, records after need the new one, and `verify()` bound a single
verifier for the whole walk. So the chain verified under **neither** key. The Policy Agent refuses to
start on a chain it cannot verify — correctly — and there was no path back. Three identical refusals,
no escape in any code path. The remedy the refusal itself named, `verify(signer=...)`, could not have
worked for exactly the same reason.

He cut through the framing I had inherited. The ticket said this part "is a decision and goes to the
LA — how much rotation tooling to build is a decision about ceremony and posture." His answer:
*"huh? We need to build it such that it works. It working vs not working is a binary choice."* That
is correct and the ticket was wrong. A system that permanently bricks on a legitimate key change is
broken, not configured.

**The design was the easy part, and it held.**

Published practice is a rollover record signed by the *outgoing* key, naming the incoming one. Put
the naming inside the canonical bytes and the outgoing key's signature covers it, so a verifier
walking forward meets a record it can check and that record says which key signs what follows. The
segment index needed the same treatment — with two rotations its rows are signed by different keys —
and that is versioned exactly the way the receipt work was versioned the night before, so every row
already on disk keeps its original bytes.

The reviewer attacked that design hard and could not dent it. It wrote a chain with the *parent
commit's* code, sealing three segments, and verified it with mine: byte-identical summaries, verifies
fast and full, tampering still caught. Ten mutants against the lock suite, all dead.

**Every single defect it found was in the wiring.**

The signing key still came from a compiled-in constant. I had wired the *verification* start to read
the key history and simply not thought about the other half. So after the ceremony wrote a bridge
declaring the new key, the service would reboot holding the retired one and append records signed by
it *after* that bridge. Boot one verifies — nothing follows the bridge yet — and my runbook said, in
as many words, that a successful start means the rotation is complete. Boot two walks to the bridge,
switches keys as designed, and refuses. Permanently: the ceremony refuses to run on a chain that does
not verify, and the history refuses to re-adopt a retired key. I had closed both exits myself.

The reason it had never fired is almost funny. My script defaulted to `audit.jsonl`, and no service
writes a file by that name — the real ones are `adjudication_audit.jsonl`, `ingest_audit.jsonl` and
`verdict_audit.jsonl`. The runbook's first command could only ever print "no audit log at …". The two
defects were masking each other.

There were two more of the same kind. The resolver I wrote to turn a key id into a verifier resolved
*any* key on the chip — on this machine that includes the model-manifest key, the Policy-Agent JWT
key and the disk-encryption key — and each index row picked its own verifier from its own claimed id.
The reviewer forged an entire chain under an unrelated key, with no bridge at all, and the fast path
accepted it. The previous commit refused that same chain. I had opened a hole while closing another,
and it opened *precisely when the feature was used*, because the resolver is only supplied once a
rotation has happened. And the Assistant Orchestrator's two chains were not wired at all, so a
rotation aimed at a compromised key would have left two of the three chains still signing with it.

**The lesson is not "test more".** The locks I wrote over the algorithm were good — thirty-two of
them, all firing, none defeated. What had no locks was the question of whether anything in production
*used* the algorithm. That is the third ticket in a row where the mechanism was right and connected
to nothing, and this time the disconnection turned a rescue into a brick.

One smaller thing, recorded because it is the same disease at a smaller scale: my first lock for the
circular-guidance fix searched the source for `exc.operator_guidance` — and matched the comment I had
written explaining why the call was removed. Third time this session a source scan certified its own
explanation. It is on the AST now, where an attribute access is a node and a comment is not.

**Next:** the doctrine surfaces need the new standing-gate figure, and the thirteen journal fragments
are still unfolded.

---

**Proposed lesson (unnumbered per the fragment convention):** *Lock the wiring with the same rigour
as the algorithm, and boot it twice.* Every defect in this change was a correct mechanism with no
production consumer, or a consumer reading a constant instead of the mechanism's output. The
three-boot test now in the suite exists because the defect **passed the first boot** — a single-boot
check, which is what anyone would write, would have certified the brick. When a change alters what a
service does at startup, the regression lock has to restart it more than once, because the first
restart is the one that looks fine.
