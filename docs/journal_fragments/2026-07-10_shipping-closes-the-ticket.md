### 2026-07-10 — The tickets that lied by staying open

*Plain summary: the #798 hygiene sweep reconciled 59 open tickets against on-disk
reality (3 closed with shipping evidence, 6 stamped CURRENT-STATE, 26 superseded drafts
closed on LA approval) and adopted the "shipping closes the ticket" convention into
CLAUDE.md. Subsystem: governance / tracking. Lesson class: state surfaces that drift from
reality compound confusion (the era-rot family, applied to project tracking).*

The trigger was the LA naming a pattern: "this confusion has happened multiple times."
Web search had been LIVE for a week while its ticket read as dormant; the air-gap removal
was half-misread the same way; a voice capability was re-discovered as "not started."
Every one of those was a session — sometimes the LA himself — trusting the ticket state
over the code, because the ticket state is what a fresh reader loads first. A capability
that is live while its ticket is open is not a bookkeeping lapse; it is a false statement
the whole coordination system keeps re-reading as true.

The sweep verified each open ticket against git, evals, and config rather than titles.
The honest surprise was how few were actually wrong: three shipped-but-open (closed with
their shipping SHAs), six partials (stamped with dated built-vs-remaining comments), and
twenty-six drafts from two completed eras — the pre-dispatch-fleet coding-agent spikes
and the pre-completion cf-program sprints — that the LA approved closing as superseded.
The durable fix is one paragraph of doctrine with the same standing as the
journal-entry-per-ship rule: closing the ticket is part of the ship itself, and partial
work gets a dated CURRENT-STATE stamp so the ticket never silently drifts. The trade-off
named: closure discipline costs a comment per merge forever; the alternative — every
future session re-deriving what is actually live — already cost more this month alone.

**Recurrence of the era-rot class** (lesson 195 family): a recorded state that nothing
re-verifies becomes wrong silently; the convention makes ticket state a maintained
surface instead of an archaeological one.

**Next:** the convention enforces socially for now; if shipped-but-open recurs, the
optional keywords-vs-done report from the ticket becomes the structural control.
