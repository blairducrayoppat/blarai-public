### 2026-07-31 — Public-surface claim corrections ahead of the announcements campaign

Corrected both public-facing surfaces so they stop contradicting the record.
Driven by the campaign work in `Job Documents\Campaign\` — the standing rule
there is that nothing may drive traffic to GitHub until these surfaces are
accurate, and an audit found the problem was considerably larger than the
stale test count that originally flagged it.

**The real defect was the open-source section on the profile README.** It listed
`npu_compiler#265` and `#266` with no status marker under a header reading
"I contribute upstream fixes," and omitted `openvino.genai#4082` entirely.
Both listed PRs are closed unmerged; #4082 is the only one that merged. Every
link in that section resolves to a page showing a Closed badge, so the true
record was inverted on the one surface a reader checks first. Rewritten into
Merged / Open / Closed-unmerged groups with a status on every item, and the
framing changed to say plainly that most submissions do not land. That framing
is stronger than the overclaim it replaces, and it is the same argument the
campaign makes everywhere else: the failures are the differentiator.

Also removed `openvino#34651`'s "(fixes #34617, addresses 4 related issues)" —
it closed unmerged on 2026-07-30 and #34617 remains open, so a closed PR cannot
be said to fix it.

**Repo README, inference stack.** "roughly 2x throughput" for speculative
decoding was the exact claim walked back publicly after it was traced to a hot
GPU. Replaced with the sustained 1.48-1.68x range, and the walk-back is now
stated inline rather than only in the journal section. The dependent "~20% peak
throughput" figure was anchored to the old 2x and became double-counting once
the base changed, so it is now unquantified.

**Repo README, build-journal section.** The walk-back destination was written as
"true 1.4x", a third value matching neither the old claim nor the approved
range. Now 1.48-1.68x sustained. This same wrong value was independently found
in circulation in a LinkedIn draft, so it had propagated across surfaces.

**Profile README, three claims contradicted by our own repo README.**
- "no external network calls. Ever." — falsified by the governed egress door
  (ADR-027) and the model-callable web_search tool against `kagi.com`. Now
  states zero external network dependency by default, with the audited
  deny-by-default egress door named. The design is the better story than the
  absolutism was.
- "Pluton measured boot" — the documented trust root is non-exportable TPM 2.0
  keys via the Windows CNG Platform Crypto Provider (ADR-018), after SGX proved
  absent on Lunar Lake. Pluton appears nowhere in the repo. Corrected.
- "ensuring that no single-layer failure can authorize a malicious action" —
  "ensuring" asserts a proven property the repo explicitly disclaims
  ("engineering intent backed by tests and measurement, not a third-party
  audit"). Now "layered so that".

**Profile README, three claims that understated or overstated the build.**
- "streaming TUI" was stale and undersold — the shipped surface is a WinUI
  desktop app with voice and inline image rendering.
- "eliminate retrieval side-channels" — countermeasures suppress observable
  variance, they do not eliminate side channels, and no security reader will
  grant the absolute. Now "suppress".
- "Local Code Agent — GPU-accelerated code generation producing atomic Git
  diffs with compile-test-oracle gate loops" described capabilities the repo
  does not evidence. Reframed to the headless dispatch that actually ships.

Also dropped "uncensored" from the SDXL finetune description in the repo README.
In a document arguing for fail-closed governance it is the one word a hostile
reader screenshots, and the technical point survives without it.

**Deliberately not done.** No test-count churn. The public band is "9,400+",
which is designed to round down to a stable value and stays true as the gate
accretes; chasing the exact live figure across surfaces is the failure mode
that produced the original five-way discrepancy. The repo README already
carries the exact figure at its owning surface, which is where exact figures
belong.

**Open items for a later pass**, all low severity and none blocking the
campaign: `docs/INDEX.md` and `docs/DECISION_REGISTER.md` both understate the
ADR range, and README's project-structure block understates it further;
`Use Cases_FINAL.md` specifies seven use cases against a canonical nine-use-case
vision, which several surfaces render as "9 formally specified" — the profile
README no longer asserts a count at all.

Branch: `docs/public-surface-claim-corrections`. Not pushed — the profile README
here is a staging copy, and the real profile repository plus the `public` remote
mirror both need a separate push.
