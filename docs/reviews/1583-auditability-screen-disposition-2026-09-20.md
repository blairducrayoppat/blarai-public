---
title: "#1583 — the auditability screen, and the gate that certified a chain severed at its last link"
status: final
area: governance
---

# Disposition — #1583 (auditability card as an in-app screen)

**Seven findings from an independent adversarial review, every one reproduced by the reviewer.
Three were blockers. The first is the defect this project has shipped more often than any
other, and every one of the 111 tests certifying the change passed over it.**

**The finding in one line: the disclosure overlay was nested INSIDE the gallery overlay, which
is `Visibility="Collapsed"`, so the screen could never render — and 12 Python gates plus 99 C#
tests were green on a deliverable that did not exist.**

```disposition
# finding | status | evidence-or-predicate
BLOCKER 1 — THE SCREEN COULD NEVER APPEAR, AND THE GATE SAID IT COULD. `AuditabilityOverlay` was inserted as a CHILD of `GalleryOverlay` (`MainWindow.xaml`), which carries `Visibility="Collapsed"`. A collapsed element does not render its subtree, so `OnOpenAuditability` set the disclosure visible and nothing painted. The reviewer walked the real ancestor chain to prove it, and corroborated it twice more: the only writes to the ancestor's visibility are the gallery's own handlers, `OnOpenGallery` returns early without a backend — falsifying the docstring I had written claiming no backend is required — and `OnCloseGallery` would have taken the disclosure down with it. My insertion script matched the gallery's INTERNAL header grid as its close | FIXED | feat/1583-auditability-screen — the overlay is now a true sibling, verified by depth-walking the element tree (GalleryOverlay 559..683, the disclosure at 686). The gate gained the STRUCTURAL lock it lacked: `test_no_ancestor_of_the_disclosure_is_collapsed` and `test_the_disclosure_is_not_inside_another_overlay` walk the actual XAML tree, and `test_the_overlay_actually_contains_the_renderer` asserts containment rather than proximity. Mutation: re-nesting the overlay inside the collapsed gallery fails both ancestry locks
BLOCKER 1b — THE OLD LOCK WAS PROXIMITY, NOT CONTAINMENT, and the reviewer found its first clause was dead code besides. `test_the_overlay_renders_the_loaded_text` checked that "MarkdownBlock" appeared within 3000 characters of the overlay's name; `overlay.split("</Grid>")[0]` stopped at the header grid 1876 characters in and was always False, so the whole test rested on the `or` fallback. A 3000-character window cannot see where an element sits | FIXED | feat/1583-auditability-screen — replaced entirely by the three tree-walking tests above. Text proximity is gone from this gate
BLOCKER 2 — THE "NO SECOND COPY" GATE DID NOT SCAN THE FILE WHERE I PUT A SECOND COPY, AND THAT COPY HAD ALREADY DRIFTED. The sweep covered three shipping files. `MarkdownTableGateTests.cs` hand-retyped three card rows, and 3 of the gate's own 5 distinctive phrases were sitting in it. The transcription was already the optimistic abridgement the ticket warns about: the card's "Inline — and the **only** surface that writes receipts today" had become "Inline", dropping precisely the qualification that makes the row honest — under a method named `The_shape_of_the_auditability_cards_own_tables_parses` and a section header reading "The real disclosure parses" | FIXED | feat/1583-auditability-screen — two fixes, because either alone would leave the other half open. The test csproj now ships the REAL card into the test output, and the tests load it through the SHIPPED loader (`Every_table_in_the_REAL_auditability_card_parses`, `No_line_of_the_REAL_card_is_lost_between_parser_and_prose`); the transcription is deleted. And the Python sweep now walks every `.cs` and `.xaml` under `services/ui_winui`, tests included, with a vacuity check that it found more than five files. Mutation: pasting one card row into a test file fails the sweep
BLOCKER 3 — THE RENDERER SILENTLY TRUNCATED ANY ROW WIDER THAN ITS HEADER, contradicting the parser's own written contract that a long row is KEPT because a malformed row in a disclosure must still be shown. `BuildTable` sized itself to `table.Header.Count` and never constructed cells beyond it. Incidence is not hypothetical: the reviewer scanned 993 markdown files in this repo and found 3 rows with more cells than their header — pasted exception text with unescaped pipes — where the truncated tail was the failure reason itself. Pasted stack traces are ordinary chat content, so this fires in the assistant view too | FIXED | feat/1583-auditability-screen — `BuildTable` sizes to the widest row and pads the header instead. Locked by `A_row_with_MORE_cells_than_its_header_keeps_them_all`; the pre-existing short-row test covered only the other direction
FINDING 4 — ORDINARY PROSE WAS EATEN whenever a `---` rule followed a pipe-bearing line with no blank line between. `IsSeparator` accepted a bare `---` because `SplitRow("---")` yields one all-dashes cell, and `LooksLikeRow` reduced to "contains a bar". The reviewer reproduced five ordinary sentences becoming tables, and the parser then went on swallowing following prose lines as body rows while the rule vanished | FIXED | feat/1583-auditability-screen — a separator must now be a PIPE row with at least two cells. `LooksLikeRow` also now means what its summary always claimed (a pipe OUTSIDE inline code) rather than `line.Contains('|')`. Locked by a five-case theory reproducing the reviewer's exact inputs, plus `A_pipe_inside_inline_code_does_not_make_a_row`. The reviewer's zero-incidence measurement over 993 repo files is recorded but was NOT the argument: the population that matters is streamed assistant replies, which neither of us could measure
FINDING 4b — I BROKE IT WHILE FIXING IT, and its own regression test caught me. My first correction made `LooksLikeRow` require two or more cells, which dropped a single-cell pipe row — legitimate, single-column, and one the parser's contract promises to keep. `A_short_row_is_padded_rather_than_dropped` went red | FIXED | feat/1583-auditability-screen — `LooksLikeRow` scans for a pipe outside inline code directly. Recorded because the sequence is the point: the tightening that fixes an over-eager parser is one character away from a silent drop, which is the failure class this whole screen exists to prevent
FINDING 5 — THE XXE GUARD'S STATED RATIONALE WAS FACTUALLY WRONG. My docstring asserted "xml.etree resolves external entities". It does not, in CPython — the reviewer reproduced pyexpat refusing an undefined entity and never fetching a SYSTEM one. ElementTree's real exposure is internal entity expansion. The SYSTEM and PUBLIC substring checks defended nothing and were a latent false-positive risk besides: case-insensitive over the whole file including comments, in a repository whose doctrine discusses the "public mirror" and the "file system" | FIXED | feat/1583-auditability-screen — the docstring now states what ElementTree actually does and what the check actually defends (billion laughs / quadratic blowup, via `<!entity`). The two decorative checks are removed. A security rationale that misstates the library is the kind of sentence that gets cited later, which is why this is a fix and not a comment tidy
FINDING 6 — THE JUSTIFICATION FOR TOUCHING THE CHAT RENDERER DID NOT MATCH THE ARTIFACT. I wrote that the card is "mostly tables". Measured: 10 pipe-bearing lines in 171, one table of 8 rows, about 6%. This matters because that sentence is what licenses modifying a parser that runs over every assistant reply | FIXED | feat/1583-auditability-screen — the comment now carries the measured figure and states the real trade plainly: one 8-row table rendered correctly, against the risk of this parser misreading ordinary chat. The call still stands; it is now made against the true number
FINDING 7 — AN UNREADABLE CARD WAS REPORTED AS A MISSING ONE, and some exceptions crashed the app rather than refusing. `File.Exists` swallows every exception and returns false, so a card present but unreadable (an ACL denial, an untraversable path) took the "there is no card at {path}" branch — a confidently wrong reason for a fail-closed refusal, with the honest message unreachable below it. The `catch` filter also omitted `SecurityException` and `ArgumentException`, which would escape a synchronous void handler and take the app down | FIXED | feat/1583-auditability-screen — `File.Exists` is gone; `ReadAllText` runs and `FileNotFoundException`/`DirectoryNotFoundException` give the "no card" message while EVERY other exception gives the honest unreadable one. The reviewer explicitly left crash-versus-refuse to me: I chose refuse, because this path exists to tell the operator what is missing and where to read it instead, and a refusal is louder than a crash in the only sense that matters here
```

## Verification

`tests/security/test_auditability_screen_reads_the_card.py`: **14 passed** (was 12; the three
tree-walking tests replaced one proximity test). `dotnet test BlarAI.Desktop.Tests.csproj`:
**107 passed / 0 failed** (was 99). `dotnet build … -p:Platform=x64 -r win-x64 --self-contained`:
**0 warnings, 0 errors.**

**The card ships byte-identical to both outputs**: 12193 bytes, sha256 `5bbfa19b9e44…`, matching
the source exactly in the app's `win-x64/Governance/` and now in the test project's output too.

**Mutations run and confirmed to fail their locks**: re-nesting the overlay inside the collapsed
gallery (2 locks fire); pasting one card row into a test file; removing the csproj Content entry;
disagreeing the Link and the loader constant; dropping CopyToOutputDirectory; showing a literal
instead of loading; weakening the refusal text. Nine in total across the change.

## The honest limit, unchanged by this review

**I have not seen the screen.** I can build the app, compile and run its logic headless, prove
the card lands where the loader reads it, and now prove structurally that nothing collapsed sits
above it — but I cannot open the window. The reviewer could not either. Blocker 1 is exactly the
defect that gap admits, and it is why the fix is a structural assertion rather than a promise to
be careful. The visual render remains unverified until the Lead Architect opens it.

## What the review could not break

Recorded because it is the finding I most wanted and it came back negative: driving the REAL
card through the real loader and a faithful replication of the renderer's block loop accounts
for **every one of its 166 body lines, zero unaccounted, zero dropped cells, zero mis-splits**,
all 31 non-ASCII characters preserved. For the card as it stands, the render is faithful.
Findings 3 and 4 are about shapes the card does not currently have — which is a reason to fix
them before it does, not a reason to leave them.
