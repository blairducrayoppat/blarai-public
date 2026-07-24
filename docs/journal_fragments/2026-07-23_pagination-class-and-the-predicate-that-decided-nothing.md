### 2026-07-23 — The well-formed deferral that still rotted, and the half-fix I shipped inside the fix for the lesson about half-fixes

*Plain summary: a known defect sat two days behind a perfectly-written ticket until it bit someone live; fixing it, I made the exact mistake the relevant lesson names, then closed the whole class and turned that lesson's completion test into a gate that runs.*

The Lead Architect's instruction was one sentence: queue the devplatform fix today rather than
leaving #1034 waiting for "a maintainer session" that nothing schedules. He ranked it just below
the retraction cleanup. The defect was small and specific — the Vikunja MCP tool
`list_task_comments` issued a single HTTP request, Vikunja clamps a page at 50 rows, and so every
call returned the OLDEST fifty comments of a thread with nothing saying it had truncated.

The direction is what makes it worth writing about. A truncated task list under-reports a project
and looks obviously partial. A truncated comment thread hands a session the *oldest* history of a
ticket it is grounding on — and our own doctrine tells sessions to record decisions as comments
rather than through `update_task`, because that is a full PUT that wipes unspecified fields. So
the newest comments are exactly where decisions live, and they were the ones being dropped. I hit
this myself an hour earlier: grounding for this session I went looking for #855's graduation
decision at c.2438, could not reach it, and worked from ticket descriptions instead. I recorded
that as a tool limitation and moved on. It did not occur to me that I was standing inside the
defect I would be asked to fix after lunch.

Measured on #740 against the live server: 95 comments, ids 1335 to 2345, the newest 45
unreachable. Among them id 2345 — an LA battery-cadence decision. The reporter of #1034 had gone
looking for that exact comment and could not see it. I fixed the read, added nine locks with
toggle-offs, live-verified two real page requests against the running Vikunja, and committed.

Then I went to close the ticket and read #1017, which I should have read first. #1017 already
described this defect. Not vaguely — at `server.py:857`, by name, with the cross-consumer
inconsistency spelled out, filed 2026-07-21 by the independent review of the *previous*
pagination fix. And it listed six MORE single-page collection reads in the same module:
`/projects`, `/labels` twice, `/users` three times, `/tasks/{id}/assignees`.

So my commit message was wrong. It reasoned that the earlier audit had checked whether each
*module* imported the shared page-walker rather than whether each *endpoint* used it, and that a
finer-grained audit would have caught the comments read. That explanation is tidy and false. The
audit was already endpoint-granular; it found the thing precisely. What failed afterwards was not
the looking. I cannot rewrite that commit message, so the correction opens the next one.

And the deeper embarrassment: lesson 64 says that when you fix a defect of a particular shape you
scan for the same shape before you close, because finding one and fixing only one is a half-fix.
Its own third instance, tallied two days ago, was *this pagination defect*. I had just shipped a
half-fix inside the fix for the ticket about half-fixes.

Closing the class properly turned out not to be the "one-line each" that #1017 prescribes. On four
of the seven sites that shape would have shipped a crash. `GET /users?s=<no match>` answers with
JSON `null`, not `[]` — measured, not assumed — and the page-walker honours its collection
contract by wrapping a non-list first page, so it hands back `[None]`: a one-row result whose row
is `None`. The single-request reads guarded that with `or []`, and the walker defeats the guard,
because `[None]` is truthy. Three tools would have raised `AttributeError` on every username miss.
The label case fails more quietly: `_attach_labels_to_task` builds a title-to-id map from
`/labels`, and a truncated map makes an existing label look absent, so it creates a *duplicate*
with the same title and a different id. Twenty-five labels today; the clamp bites at 51. A fix
shape written in a ticket by a reviewer who was reasoning about the pattern rather than the call
sites is a hypothesis, and I nearly inherited it as an instruction.

The trade-off I made and the one I refused: I widened the change beyond its ticket, because
shipping six known-defective siblings to keep a diff tidy is the failure the lesson names. I did
not widen it to `list_task_assignees`, which I discovered returns 500 on *every* task, with or
without paging parameters — it has never worked against this Vikunja version. That is a
pre-existing, unrelated defect; folding it in would have made an already-broad merge unauditable,
so it is #1072 with a positive-control requirement, because a "fix" that returns `[]` for
everything is indistinguishable from the broken state.

The thing worth keeping is about deferrals. #1017 was a *good* ticket. It had file-and-line
citations, a fix shape, and an observable predicate — "grep `server.py` for `_api_get(` at the
lines above" — which is precisely what our deferral discipline demands, and better than most
deferrals get. It still rotted for two days, until a session hit the bug live and filed it again
as new. The predicate made the deferral *checkable*; it did not make it *checked*. Nobody was
scheduled to run the grep, so the grep was never run. That is not a flaw in how the ticket was
written, and it is why the LA's instinct — that "waiting for a maintainer session" is a predicate
that nothing schedules — was the right read of a well-formed record.

Which points at what lesson 64's third instance actually shipped. It shipped a shared page-walker
module and a mutant-proven lock, and it wrote its completion test in prose: the class is closed
when every copy is bound to one shared fix and *a grep for the pattern comes back empty*. That is
the correct test. It was never made executable, so it depended on someone remembering it — and a
shared module that nobody is forced to use does not close a class either. So the control shipped
with this tally is that sentence turned into a test: it greps the live module source and fails on
any bare single-request read of a collection path, with `/info` as the single named exemption
because it is a scalar document. A new unpaginated collection read now has to come to that test
and justify itself. Suite 66 of 66, live-verified against the real server: 12 projects, 25 labels,
`find_user` hit and miss, 95 comments with id 2345 present.

**Recurrence of lesson 64:** FOURTH instance — and the sharpening is about the completion test
rather than the scan. Fixing one copy, ticketing the rest with excellent predicates, and shipping
a shared helper nobody is obliged to call leaves the class open; the residuals then read as
handled because a well-formed ticket looks like disposal. A class is closed when its completion
test EXECUTES — when the grep that proves emptiness is a gate that runs rather than a sentence in
a lesson. Control shipped with this tally: `test_no_unintentional_single_page_collection_reads_
remain` (devplatform `13495f4`), which makes lesson 64's own stated test machine-checked for this
defect class.

And the control failed on its first attempt, which is the part of this entry most worth keeping.
The version I shipped in `07cc521` — and cited in an earlier draft of this fragment as the
control — used a regex whose character class excluded `{`, so every f-string path was invisible
to it: seven of the module's ten call sites, including the exact line the whole branch existed to
fix. The independent review proved it by mutating the module and watching the gate stay green
while the original defect sat in front of it. I had written a lesson about completion tests that
only work when they execute, and then shipped one that executed and proved nothing. The working
version pins the exact SET of single-request read paths across both helpers, so an addition, a
removal, or a revert all fail it, and a companion test asserts the old pattern's blindness so the
gap cannot quietly reopen. The general form: an executable completion test is necessary and not
sufficient — you have to watch it go red against the real defect, or you have only moved the
unverified claim from prose into Python. That is lesson 30's discipline (a guard you have not
watched go red is decoration) meeting lesson 64's, and I needed both and applied neither.

The same review found two more things I had asserted without checking. The summary line I added
to prove reads were complete would itself say *"Listed all 50 comments"* on a partial walk,
because the page-walker has two early exits and I had documented only one — in a source comment
that explicitly denied the second existed. And I repeated a commit attribution straight out of
#1034's description without running `git show`; the commit named touched neither file I claimed
it did. Three sentences into correcting an inherited error, I inherited another one.

**Proposed field note:** Vikunja v2.3.0 answers `GET /users?s=<no match>` with JSON `null`, not
`[]`. Any code walking that endpoint through `get_all_pages` receives `[None]` — a truthy one-row
list — so an `or []` guard does not survive the conversion. `_api_get_all_rows` in
`tools/vikunja_mcp/server.py` is the normalising binding. Separately, `GET /tasks/{id}/assignees`
returns 500 on every task in this version (#1072).

**Next:** the #1066 B4 diagnostic — why `add-card` builds nothing and why the de-duplication guard
refuses its repair — then #1067's guard calibration ahead of any new shadow window.
