### 2026-08-08 — A zero is not a number until you know who counted it

*Plain summary: the record that graded the websites said "0 problems found" when what it meant was "we did not look." I did not change a single count — I made the counts readable, so that the two can never again look the same. Then I ran the new link checker over every website this system has ever built and found a site nobody had ever opened whose stylesheet is missing.*

The line I keep returning to from this morning's finding is not the vacuous oracle. It is this pair of fields, sitting two lines apart in the same JSON object:

```
"findings": { "f2p_vacuous": 0, ... },
"f2p_baseline": "not-run",
```

`f2p_vacuous` **is** the check for vacuous tests. It reported zero against an exam that was three-fifths vacuous. The reason is not that it looked and missed them; it is that the stage which produces that finding never ran. And the honest field admitting so was *right there*, adjacent, in plain sight — and did nothing, because nobody reads a record field by field. They read the headline, and the headline said zero.

That is what makes this class dangerous rather than merely wrong. The unmeasured result is not disguised. It is **accompanied** by its own disclaimer, and the disclaimer's presence makes the whole record look scrupulous. An honest field standing next to a confident one lends the confident one credibility. I have now found this shape four times in two days, and every time the disclosure was already present and already ignored.

So the fix changes no count at all. It makes a count **interpretable**. Every finding class now names the stage that produces it — vacuity comes from the fail-to-pass baseline, collectability from the load probe, traceability from the coverage map, the rest from the static scan — and a single field, `findings_conclusive`, is false whenever any producing stage did not run. The reasoning underneath is asymmetric and worth stating plainly: an unrun check can only ever have *missed* something, never over-reported it, so a total from an incomplete scan is a floor and not a count. Calling it a count is the error.

Re-emitting this morning's exact stamps now produces `findings_conclusive: false`, a status of `partial`, and three sentences naming what did not happen. A fully measured run produces `true` and an empty list. Those two records were previously **byte-indistinguishable in every field a reader looks at**, which is the entire explanation for how a missing page survived four gates.

I also retired a second copy of a vocabulary while I was in there. The set of stamps meaning "did not run" was declared privately inside `swap_driver`, the consumer, rather than inside `oracle_qa`, which writes them. Two copies of a vocabulary drift, and this one would have drifted in the direction that hurts: a stamp the consumer failed to recognise as unmeasured would be read as evidence, and an unvalidated oracle would be free to delete work from the plan again. The module that writes a word owns what it means.

Then the part that actually reaches him. Making a record honest is worth very little if the record is read by machines and the person deciding whether to trust the delivery never sees it. His review page now answers one question in his own register — *was the marking any good?* — and for the site he looked at, the answer is: **the exam that graded this was never shown able to fail, so your eyes are the only real check on this delivery.** Three renderings, never two: validated, not-validated, and no-record-at-all, with the last saying *unknown* rather than *fine*. The subtle part is the fallback for records written before the new field existed, and it took its own toggle-proof to get right, because the tempting implementation reads a missing field as a pass. The absence of the field is the absence of the check.

The day's last measurement was the cheapest and, I suspect, the most useful. I pointed the new link checker at every tree this fleet has ever produced: 209 candidates, of which 31 actually contain pages. 128 links resolve, 8 lead nowhere, 3 sites carry a hard finding. Two of those three I already knew about. The third I did not: `authorwebsite3000`, which nobody has ever opened, loads `header/header.styles.css` — a file that is not in the delivered tree. **The site renders unstyled.** It has four working links and four broken ones. That is not a subtle defect; it is the first thing anyone would notice, and it shipped, and it sat there.

The sweep also vindicated the one design decision I was least sure about. Three of that site's four breaks are extensionless paths like `/about-me`, which might be routes the server builds at runtime. The checker grades those LOW and says it cannot tell; only the missing stylesheet, which no routing story rescues, is HIGH. Had I flagged all four, the gate would be nagging a coder about three things that may be perfectly correct, and a gate that cries wolf stops being read. The instrument's usefulness lives entirely in the gap between what it knows and what it merely suspects, and in being willing to say which is which.

Worth keeping in proportion, though: of the seven things he observed on the pottery site, this instrument would have caught **one**. The repeated photographs and the descriptions that do not match their pictures need a grader that does not exist yet. A cheap automatic check does not replace the person looking at the thing. It narrows what the person has to look for, and that is a smaller claim than I would like to be making.

**Next:** the 23:00 battery, and the single question of whether `create-piece-detail-page` gets built or skipped for a third night. Whatever happens, the run's own record will now say whether its exam was ever checked — so if it grades itself GREEN, that GREEN arrives with its provenance attached for the first time.
