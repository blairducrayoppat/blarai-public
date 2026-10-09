### 2026-10-04 (evening) — The two "misses" were a prompt the model never saw, and four of my own explanations had to be taken back

*Plain summary: I tested the 9B Qwen3.5 as a possible replacement brain. It repeated the 4B's two Policy Agent
"misses" in three runs out of three, so I went looking for why. The answer is that no model is ever shown the
command in those two requests: the Policy Agent's own check rejects the field and shows the model a rejection
marker instead. On the evaluation prompt the 14B says DENY because of the marker and the Qwen3.5 models did not react to it (two cases, one variant)
(a second review later showed that is not the live path; see below). That overturned what I
had written about the 4B that morning, and it was not the only explanation of mine that the data refused.*

The question (#1665) was whether the 9B INT8 with its Multi-Token Prediction head closes the Policy Agent gap the
4B left. I ran the same protocol as the 4B (cold-gated speed, live first-token delay, every suite, three
Policy Agent runs, byte-identity) after generalising the harness to a size parameter, and the numbers came
back in the shape the 4B had set: 33 of 35 on the Policy Agent in all three runs, the same two cases
(`pa-mdl-007`, `pa-mdl-013`), with the parsed label and confidence identical each time (I first wrote "byte-identical";
the comparison hashed the parsed verdict, not the raw text, which was captured for one run only). I had already written, in the 4B verdict, that this was
two dangerous actions let through, and that I did not know why.

I wrote a candidate mechanism on the ticket from reading the prompt: the DENY list has no metadata-endpoint
or audit-log example. I labelled it unproven, which was right, and it was also wrong. An agent with no stake in
my wording built a variant probe that ran the real Policy Agent prompt through the 4B, the 9B and the 14B under
eight prompt variants, with the shipped prompt as a harness check first (it reproduced the banked result for
all three). Replacing the command with `echo ok` gave a prompt byte-identical to the shipped one on all 13
model-judged cases: the schema validator rejects the key `command`, so the model receives
`[SCHEMA_REJECTED: Disallowed schema key: command]` and nothing else. Adding DENY examples changed nothing, and
showing the command made both Qwen3.5 sizes DENY. On that prompt the 14B passes because of the rejection marker: it stays DENY
with a harmless command plus the marker, and goes ALLOW when the marker is removed. So the 14B's 35 of 35 on
these two cases says nothing about whether it understands an SSRF, and the "dangerous actions let through" line
I had published was a claim about a prompt the model was never given. The 4B verdict, journal fragment, log
entry and dataset card are corrected in place with the old sentences left visible. What I still do not know:
~~whether real orchestrator requests ever carry a command under a rejected key~~ (a second review answered that from
the code, below), and anything about the 14B beyond two cases and one run each (its probability and sampling arms
failed and are void).

**Round-2 correction, and a recommendation I withdrew.** The verdict I wrote after the probe recommended a fixed
rule that denies any request whose schema is rejected, and recommended keeping the 14B because it refuses on the
marker. Both rested on a premise I had listed as "not checked" and then built on anyway. The second independent
review read the code: every Assistant Orchestrator tool call with arguments puts them under the key `args`
(`entrypoint.py:401`), and the validator rejects that key, so the marker is the normal shape of a live
argument-bearing request, and a deny-on-rejection rule placed where live requests are judged could deny every one of
them and every URL fetch. A search of `services/`, `shared/` and `launcher/` also finds no production sender of a
request to the model-backed classifier: the tool loop and the URL door call the rule checker in process. That second
point is static evidence; nobody has traced a real tool call. So the "14B refuses on the marker" reasoning describes
my evaluation prompt and is not shown to be the live path, the deterministic-DENY recommendation is withdrawn until the
live shapes are traced, and what goes to the Lead Architect is a design question: if the model is shown only a
rejection marker instead of the arguments, the arguments are judged only by the rule checker. The same review
recomputed the Jev note's numbers from the rows (104 answers, 103 at 0.95, 11 ALLOW against the golden DENY label, not
103/102/10) and the correction sits in that note with the old text visible.

Three more explanations of mine did not survive contact. The independent Opus review found that my on-versus-off
byte-identity comparison looked only at the first pinned run of each suite, so "identical in every check" described only
the runs I looked at and was not true across all twelve pinned runs: 2 of 366 calls differ for the 9B and 1 of 377 for
the 4B, in the middle of a reply, never the first token, with the same per-case pass or fail. The Phase 1
claim is retracted where I made it. Second, the speed top-up made the variation worse, not better (9B MTP-on
long-prompt decode CV 26 percent), and I said the slow visit overlapped agent CPU work. The sampler's window
average did not support that, and the slowest rows were five readings taken after waiting about three minutes
without the laptop reaching the 72 C gate, which the analyser had pooled as cold rows without saying so. The direct flag (`cold_wait.reached`) was in every row; I had reasoned from a proxy while it sat
there. The analyser now excludes those rows uniformly, lists them, and keeps the old numbers in a second file;
that was decided after the data were read and every document says so. Ten ratios the rule had refused now
pass, five of the ratios that use the two near-limit visit spreads (CV 14.4 and 14.1 percent against the 15 percent
limit) pass narrowly. The cause of the gate
failures was my own: review and builder agents were running while the thermal-gated top-up ran. The A4 outlier at
13.5 tok/s met its gate and is unexplained.

Trade-offs: I could have re-run the contaminated invocation instead of excluding the rows; the exclusion was
faster and is defined by the protocol, and the cost is a post-hoc rule that the reader has to trust me on, so it is
disclosed in the card and the log. The second review also found that the gate I excluded on is the wait loop's flag,
not the temperature read before each generation: 38 of the 154 kept rows started above 72 C, at 72.9 to 81.9 C. Dropping those too (a
sensitivity file, written after the fact) moves the 9B long-prompt cell from 9 visits to 5 and its MTP on-over-off
ratio from 2.17 to 2.30, and leaves the headline 9B-over-14B ratios where they were (1.076, 1.715, 1.164 to 1.077,
1.718, 1.164). I rejected quoting the median-based ratios as findings; they are labelled
exploratory and only the refused first-token pairs keep one. I also kept the 14B quality baseline from the 4B run
rather than re-running it, because the code path it uses did not change.

Lessons proposed, not numbered: (1) an explanation that fits the data is a hypothesis until a probe that could
have refuted it has run; the one I wrote first would have sent the Lead Architect to add examples to a prompt
whose command the model never reads. (2) A check that compares only the run it was pointed at certifies that run:
enumerate the runs the claim covers and compare all of them. (3) When a row carries the direct flag for the
thing you suspect, read the flag before reaching for a proxy. (4) A thermally gated measurement is not run beside
other work on the same machine, including mine.

**Next:** a runtime trace of one real tool call through the adjudicator (no model needed to see the request) comes
first; the Lead Architect then decides whether the model should see the arguments and whether a rejected schema means
anything (#1673 and #1672 are corrected not to presume it; the new ticket carries the trace); INT4 and the 9B image
check stay in #1665. The coder-containment steps (#775) start after this merge.
