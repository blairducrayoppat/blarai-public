# Provenance-Aware PII Redaction — AIGP Alignment

**What this document is.** A mapping from the concrete design decisions of
BlarAI's provenance-aware PII-redaction capability to the IAPP AIGP (Artificial
Intelligence Governance Professional) body of knowledge (v2.1) and the
recognized standards underneath it. The capability plus this mapping is a
portfolio artifact: evidence that each engineering choice was a *governance*
choice with a named professional basis — not an ad-hoc regex.

**Companion documents.** Framework research and 45-source bibliography:
[pii_redaction_governance_research.md](pii_redaction_governance_research.md).
Study plan: [aigp_study_plan.md](aigp_study_plan.md).

---

## The capability in one paragraph

BlarAI's Post-Generation Output Validator (PGOV) gained a third PII policy,
`pii_mode = "redact"`. For every personal detail in a model response, the
validator asks a *provenance* question: does this trace to content the user
provided — a loaded document or their own message — or did the model produce it
on its own? PII that traces to the user is **surfaced** (it is the user's data);
PII that cannot be traced is **redacted** in place with a visible, labelled
marker, and every decision is written to an audit trail. The response is still
delivered — redaction is honest and partial, never silent whole-response
suppression. Detection runs two layers: canonical full-format patterns (high
confidence) and context-gated recognizers that catch fragmented disclosure
(medium confidence). Production posture is `pii_mode = "off"` — a single-user
personal assistant exists to surface the user's own data; `"redact"` is the
demonstrable governance artifact.

---

## Design-decision → AIGP mapping

| # | Design decision | AIGP domain(s) | Underlying standard | What it demonstrates |
|---|---|---|---|---|
| 1 | **Provenance-gated routing** — surface user-traceable PII, redact untraceable PII | II.A — Privacy & Data Protection Laws; III — Governance of AI Development | GDPR Art. 5 (data minimization); NIST Privacy Framework CONTROL-P; lineage-aware governance | Data is governed by *origin*, not treated as uniformly safe or uniformly dangerous — the contextual PII model of NIST SP 800-122 put into code |
| 2 | **Honest, visible redaction** — a labelled marker, not silent suppression | IV — Governance of AI Deployment & Use; I — responsible-AI principles | NIST AI RMF (transparency, explainability); GDPR Art. 22 (automated decisions must be explainable) | An automated decision the user can *see and understand* — transparency designed in, not a silent filter |
| 3 | **Audit trail that carries no raw PII** — records label, span, confidence, action, reason | IV — monitoring & accountability | NIST AI RMF MEASURE/MANAGE; ISO/IEC 42001 (logging) | Auditability — and data minimization applied recursively: the audit log does not itself become a PII store |
| 4 | **Confidence scoring** — HIGH (canonical) / MEDIUM (context-gated) | II.A.3 — Automated Decision-Making; II.D — Industry Standards & Tools | Microsoft Presidio analyzer model (graded recognizer scores) | Detection expresses graded certainty, not false binary certainty — mirrors the industry-standard reference architecture |
| 5 | **Context-aware detection** — recognizers gated by neighbouring PII-announcing words | III — Governance of AI Development | Defense-in-depth; Presidio context-enhancement mechanism | Detection coverage is treated as a recall problem to be raised deliberately, with documented precision trade-offs |
| 6 | **`pii_mode` policy control** — `off` / `block` / `redact` in versioned config | IV — deployment/release governance; I.C — AI governance program components | NIST AI RMF GOVERN; ISO/IEC 42001 | The privacy posture is an explicit, auditable, version-controlled configuration decision — a governance program component |
| 7 | **Fail-closed validation** — a PGOV error suppresses the response | I / risk management | NIST AI RMF MANAGE; fail-safe design | Errors degrade toward safety, not toward exposure |
| 8 | **Documented limitations** — fragmentation ceiling; ML/NER logged as future work | I — Foundations; IV — ongoing risk management | NIST AI RMF (residual-risk documentation) | Honest residual-risk posture — AI controls are probabilistic, and saying so is the governance-correct stance |

---

## Per-decision notes

**1 — Provenance-gated routing.** Conventional enterprise redaction hides a
user's data to protect third parties. BlarAI inverts it: the user owns the data,
so what is redacted is what is *not verifiably theirs*. The same mechanism that
enforces data minimization also catches model-hallucinated and prompt-injected
PII — one control, three risks addressed.

**2 — Honest redaction over suppression.** The predecessor behaviour suppressed
an entire response if it contained any PII — a control built for the wrong
threat model. Honest redaction replaces only the untraceable span, tells the
user what was withheld and why, and delivers the rest. Transparency is the
difference between a governance control and a black box.

**3 — Minimized audit trail.** Each decision is logged with entity label, span
offsets, confidence, action, and reason — never the raw PII value. An audit
trail that leaked the data it audits would be its own breach.

**4 — Confidence scoring.** Mirroring Presidio's `RecognizerResult` score, every
detection is graded: a canonical 10-digit phone match is high confidence; a
fragment flagged only by a neighbouring "Phone Number:" label is medium. The
grade is carried into the audit trail.

**5 — Context-aware detection.** Regex catches canonical formats; it misses PII
disclosed in fragments ("Area Code: 212" / "Phone Number: 555-0198"). Context-
gated recognizers flag a number when a PII-announcing word sits beside it.
Precision is preserved — a bare number with no such word is not flagged.

**6–8** are summarized in the table above.

---

## Known limitations (honest residual risk)

- **Detection is probabilistic.** Context-aware recognizers raise recall for
  realistic, labelled fragmentation, but a model emitting digits with *zero*
  surrounding cues can still evade pattern-and-context detection. This is a
  property of the problem, not a defect.
- **The path to closing it is ML/NER detection** — the approach used by
  production tools (Microsoft Presidio, AWS, Azure). It is logged as a future
  enhancement; it was deliberately not adopted now because it is a heavy
  dependency on a local-first system and does not, by itself, reassemble
  fragmented numbers better than context rules do.
- **Provenance matching is verbatim (format-normalized).** A PII value the model
  paraphrases beyond recognition would not be traced to its source. Short
  fragments (e.g. a 3-digit area code) have a higher chance of coincidentally
  matching trusted text and being surfaced — a low-stakes, documented bias
  toward trusting the user's own data.

Documenting residual risk plainly is itself the AIGP-aligned posture: an AI
governance control is a risk-reduction measure with a stated coverage envelope,
not a guarantee.

---

## Verification evidence

- **Automated:** 1,123 tests pass, including dedicated suites for provenance
  routing, context-aware detection, confidence scoring, and the audit trail.
- **Runtime:** the validator logs each decision to `launcher.log`
  (`PGOV redact — N PII span(s): X redacted, Y surfaced …`), with per-span
  confidence — the fleet self-attesting.
- **Live, user-operated:** trusted PII (a number from a loaded contacts file)
  surfaced correctly; untrusted PII (a model-invented example number, including
  fragmented disclosure across "Area Code" / "Phone Number" labels) redacted
  with the visible marker.

Multi-layer verification is the point: automated tests proved the redaction
*logic*; only live, user-operated testing surfaced a UI rendering defect and a
real-world detection-recall gap. Both layers were necessary.
