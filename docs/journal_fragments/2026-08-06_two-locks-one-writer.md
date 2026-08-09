### 2026-08-06 — Two locks are defence-in-depth for a read and a trap for a write

*Plain summary: the battery's stop date is protected by two independent locks, which is good design — but changing the date needs two edits, nobody ever built a tool to do them together, and the pair half-landed for the second time in three weeks.*

The Lead Architect extended the nightly battery campaign by three months at 11:45 this
morning. At 12:22 an independent review of my comprehension gate found that the battery
was still going to stop on 2026-08-11. I ran the project's own conformance checker and it
said so plainly:

```
T7  DIVERGED: campaign end_date = 2026-11-11 (script lock: last night 2026-11-11)
    vs trigger EndBoundary = 2026-08-12T00:00:00 (OS lock: last firing night 2026-08-11)
    The EARLIER lock wins SILENTLY.
RESULT: 7 passed, 1 FAILED
```

The cutoff is enforced twice on purpose. The campaign file's `end_date` makes the 23:00
preflight unregister the scheduled task once the date passes; the trigger's `EndBoundary`
is pure Task Scheduler and involves no script at all. Either one alone stops the battery.
Neither depends on the other working. That is a good design and I would not change it.

But it has a property nobody wrote down: **defence-in-depth on the enforcement side
becomes a two-write-site problem on the change side.** Reading the cutoff is robust.
Changing it requires editing a JSON file and a Windows scheduled task, in two formats,
and getting both right. And a repo-wide search finds no script that writes either one —
only readers. The entire control at write time was remembering to do both.

It failed on 2026-07-19 (#972: extended to 08-11, boundary left at 07-22) and again today
(#1283: extended to 11-11, boundary left at 08-12). Same subsystem, same signature, one
campaign apart, reconciled by hand both times.

My first instinct was the wrong fix, and I had already written it into the ticket before I
checked: *nothing runs the T7 check at preflight, so wire it in.* Then I read
`run-battery-night.ps1:682-720` and found the preflight **already runs it, every night,
unconditionally**, and prepends a `## !! BATTERY TASK-SETTINGS DRIFT` banner to the
morning report at line 1223. Tonight's run would have caught this and reported it
tomorrow, with five nights still in hand. So the honest account is better than the one I
first banked, and I went back and corrected the ticket rather than letting the record
carry a false premise — the description is still wrong in the archive, with a correction
comment above it, which is the trade I chose over a silent edit.

That correction is what made the real fix visible. **Detection was never the gap.** T7
exists, it works, it caught this in seconds when asked. The gap is that the divergence is
*born at the instant of the edit*, and no amount of after-the-fact checking prevents a
thing it can only observe. The tempting move — add a third hand-run check — would have
repeated the mistake at one further remove.

So `set-campaign-end-date.ps1` (agentic-setup `a621d34`) removes the second hand-write
instead. It takes a date, writes both locks, verifies, and restores both if the
verification fails. Every precondition runs before a byte is written, and the ordering is
deliberate: the elevation check comes first, because the trigger write needs Administrator
and the campaign file does not — so an unelevated run would write lock 1, fail on lock 2,
and manufacture the exact half-applied state the script exists to prevent. The failure
mode of the fix would have been the defect.

Two design choices I'd defend and one limit I'd rather state than hide. The JSON edit is an
anchored regex value-replace, not a `ConvertTo-Json` round-trip: `battery-campaign.json` is
a 10,842-byte hand-maintained file full of prose notes, and round-tripping it through
PowerShell's serialiser would silently reformat every line of it. The self-test proves a
date appearing in a *note* is left alone. A side-file probe config is refused outright
unless you assert ownership of the shared task, because a throwaway diagnostic rewriting
production's schedule is how a measurement quietly reschedules the thing it measures. And
the script only *changes* an existing cutoff — introducing or removing one decides whether
a cutoff exists at all, which is a different call, made far more rarely, and not the
operation that has now failed twice. It refuses those with a message instead of
half-supporting them.

Verification was the part I actually enjoyed. Seventeen self-test checks over the pure
derivation and the JSON edit; the three refusal paths driven until they refused; `-WhatIf`
proving every precondition passes against the live pair while writing nothing. Then the
real thing: a live write of the *same* date, which exercises the whole
write → verify → NextRunTime motion at zero net change. The campaign file came out
SHA256-identical, 10,842 bytes in and out, the verifier at 8/8, and the trigger still
firing tonight at 23:00. A no-op write is the cheapest honest end-to-end test I know for a
tool whose whole job is to touch production carefully.

The wider lesson is not really about scheduled tasks. It is that **a control which exists
and is never invoked is indistinguishable from one that was never built** — and the
distinction only surfaces when someone runs it. T7 had been sitting there since July,
correct and unasked. The review that found this did not discover a missing guard; it
discovered that nobody had pressed the button.

**Next:** re-dispatch `create-habit-tracking` to actually verify #1277's rename-not-delete
against a real park — the parked branch on disk proves nothing, since the destructive
version ran at dispatch time too.
