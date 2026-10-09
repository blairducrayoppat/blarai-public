# How to tell when the coder-progress agent is going wrong, and what to type

**Who this is for:** you. It assumes you cannot read the code and should not have to. Every
check below is something you can see in the chat window, and every fix is a sentence you copy
and paste.

**What the agent is.** `.claude/agents/dod-witness.md` is a plain text file of instructions. A
session reads it and follows it. When the session does something wrong, the usual cause is that
the *file* told it something wrong or forgot to tell it something — so the fix is almost always
"change the file", not "argue with this session". That distinction is the whole of this
document.

**The one thing the agent exists to do.** There is a checklist of 21 things a working coder must
be able to do (`docs/design/CODER_DEFINITION_OF_DONE.md`). Three of them are marked "LIVE",
meaning proven. The agent's job is to move the other eighteen to LIVE **with evidence**, and to
refuse to mark anything LIVE without it.

---

## The five-second check

Ask yourself one question after any progress report:

> **Did it name a file that proves what it just claimed?**

If it says a row moved, or a fix works, or something is done, there must be a filename or a run
identifier (they look like `20260816-134142-bd`). No filename, no proof.

**Type this:**

> Which exact file proves that? Name it and show me the line.

---

## The eight tells

### 1. It says something is done, finished, or LIVE — and names no file

**Why this matters:** this is the single most likely way you get told the project is further
along than it is. It happened repeatedly today before being caught.

> Which exact file and which line proves that? If you cannot name one, say so plainly and tell
> me what would produce it.

---

### 2. It reports lots of activity, but the number of LIVE rows did not change

Shipping tickets is not the same as proving capability. Three of 21 rows were LIVE this morning
and three were LIVE this evening, after two tickets shipped. **That was correct** — but you
should always be able to get a straight answer.

> How many of the 21 rows are LIVE right now, and is that different from when you started? If
> it is not different, say so in one sentence.

---

### 3. It says a check came back "clean" or "passed"

A check that cannot see the thing it is checking also reports clean. That exact defect ran for
55 deliveries: a grader that could not read website code reported that the coder had written no
tests, when the coder had written nine.

> Could that check actually see what it was checking? How do you know — did you run it, or read
> it?

**"I read the code and it looks right" is not an answer.** Today fourteen defects in one
function were found by *running* it and zero by reading it.

---

### 4. It says it will do something "later", "as a follow-up", or "next session"

Work deferred without a ticket number disappears. Every deferral must have a number like
`#1431` attached.

> What is the ticket number for that? If there is not one, either do it now or make the ticket
> before you continue.

---

### 5. It wants to start a coder run

A run takes five to eight hours of the machine. Before one starts, three things must be true.

> Before you launch: have you saved a copy of the current website somewhere safe, have you
> checked the three settings that have caused failed launches before, and when will it finish
> relative to 11pm?

**Why:** starting a run wipes the current site and rebuilds from scratch. A copy must be made
first. If it cannot answer all three, it is not ready.

---

### 6. It says it is waiting for the 11pm run

Almost always wrong. A run can be started at any time, and most work does not need one at all.

> Does that actually need a run, or does it need a fix to the tool? Runs are the scarce thing.

**Why this matters:** twenty-seven open tickets claimed to be waiting for the nightly run when
they were not. And several things that looked like "we need more runs" turned out to be
instruments that were broken — no number of runs would ever have fixed them.

---

### 7. It asks you a technical question

It should never do this. You decide what the system should be able to do, how good it must be,
and what is safe. It decides how.

> That is your call to make, not mine. Research it, decide, and tell me the decision in plain
> language.

---

### 8. It writes a lot and merges nothing

Work that is not merged does not exist for the next session.

> Is that merged? If not, what is blocking the merge?

---

## How to fix the agent when it is wrong

**Do not just correct the session. Correct the file.** Otherwise the next session makes the same
mistake, and you have to catch it again.

Copy this:

> That was wrong, and I do not want the next session to repeat it. Update
> `.claude/agents/dod-witness.md` so the instructions prevent it, then tell me in one sentence
> what you changed and why.

**Do this every single time.** The file gets better only by being corrected. That is how it
turns from something written today into something that works.

---

## What good looks like

You should be seeing, regularly:

- A filename or run identifier next to every claim
- Plain statements of what was **not** proven, alongside what was
- Ticket numbers for anything postponed
- Occasional "I was wrong about that" — a session that never corrects itself is not checking

You should be suspicious of:

- Long reports with no filenames
- Steady progress with no setbacks
- "Should work", "looks right", "is now complete" without evidence

---

## Two things you personally have to do, that nobody can do for you

**1. Look at the built website and say what is wrong with it.** Your eyes have twice caught
things that four automated checks passed. This is not a formality — it is the only ground truth
the automated checks have.

**2. Decide when a capability is allowed to go live.** No session may flip that switch. If one
offers to, that is one of the few real red flags in this document.

---

## The honest state of this document

The agent was written on 2026-08-16 and **has never been used**. Its first session is its test,
not its proof. Expect it to be wrong somewhere in the first hour.

That is normal and it is why this file exists. The tells above are not hypothetical — every one
of them is a mistake that actually happened, most of them on the day the agent was written.
