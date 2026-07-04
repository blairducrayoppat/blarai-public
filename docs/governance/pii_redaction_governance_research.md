# PII Redaction & AI Data Governance — Research Reference

**Purpose.** Foundational research for BlarAI's *provenance-aware honest-redaction*
capability (Post-Generation Output Validator — PGOV — Stage 2 `redact` mode).
Compiled as portfolio substrate toward the IAPP AIGP (Artificial Intelligence
Governance Professional) certification. §6 maps the capability to the AIGP exam
body of knowledge.

**Compiled.** 2026-05-22 — 45 sources, listed in full at the end.

**Honesty note.** Most claims below trace to primary sources (NIST, EDPB, HHS,
ISO, IAPP, vendor docs). Where this document draws an inference or coins a term,
it says so explicitly — see §4 on the term "provenance-aware redaction."

---

## 1. Governance framework landscape

PII (Personally Identifiable Information) handling in AI systems is governed by a
small set of recognized frameworks. Each is summarized below for what it says
about *redaction, de-identification, and data minimization* specifically.

### NIST AI Risk Management Framework (AI 100-1)
Voluntary US framework, four core functions: **GOVERN, MAP, MEASURE, MANAGE**.
Privacy-enhancement is one of seven named *trustworthiness characteristics*. The
framework explicitly names data minimization and de-identification as privacy
methods; the 2024 Generative-AI Profile (AI 600-1) extends this to training-data
memorization and output leakage. A redaction system operationalizes the MANAGE
function's privacy controls.

### NIST Privacy Framework (v1.1)
Companion to the Cybersecurity Framework. Five functions: IDENTIFY-P, GOVERN-P,
**CONTROL-P**, COMMUNICATE-P, PROTECT-P. CONTROL-P covers data minimization,
de-identification, and access controls. Names "disassociated processing" — using
data without linking it to individuals — as an explicit privacy goal.

### NIST SP 800-122 (Guide to Protecting the Confidentiality of PII)
The foundational US federal PII guide. Defines PII as **contextual, not
categorical** — "information which can be used to distinguish or trace an
individual's identity." Establishes a PII confidentiality *impact level*
(low / moderate / high) that governs which safeguards apply. The contextual model
directly supports provenance-aware logic: the same data may warrant different
handling depending on origin and context.

### ISO/IEC 27701 (Privacy Information Management) + ISO/IEC 42001 (AI Management)
27701 extends ISO 27001 with a Privacy Information Management System — mandates
data minimization, purpose limitation, pseudonymization, privacy-by-design. The
2025 edition is explicitly designed to integrate with **ISO/IEC 42001**, the AI
management-system standard, giving one governance spine for both information
security and AI-specific privacy.

### GDPR — three distinct legal concepts
- **Art. 4(5) pseudonymization** — replace direct identifiers with tokens;
  re-identification needs separately held data. Pseudonymized data *stays in
  GDPR scope*; it is a risk-reduction measure, not an exemption.
- **Recital 26 anonymization** — if no individual is *reasonably* identifiable by
  any likely means, GDPR does not apply. A high bar, hard to reach for rich text.
- **Art. 5 data minimization** — process only what is "adequate, relevant and
  limited to what is necessary." Directly relevant to output filtering: an AI
  should not regurgitate PII unnecessary to the user's purpose.
- **Art. 22** — automated decisions with significant effects must be explainable
  and auditable. Relevant to any automated redaction decision.
The **EDPB January 2025 pseudonymisation guidelines** are the current
authoritative interpretation for AI pipelines.

### HIPAA de-identification (45 CFR 164.514)
Two methods for US health data (PHI — Protected Health Information):
- **Safe Harbor** — remove all **18 enumerated identifier categories**: names;
  geographic units smaller than a state; dates finer than year; phone; fax;
  email; SSN; medical-record numbers; health-plan beneficiary numbers; account
  numbers; certificate/license numbers; vehicle IDs; device IDs; URLs; IP
  addresses; biometric IDs; full-face photos; any other unique identifier.
- **Expert Determination** — a qualified statistician documents that
  re-identification risk is "very small." More flexible; requires sign-off.
The 18-identifier list is the most concrete PII taxonomy in US federal law and a
natural starting point for a detector's entity set.

### EU AI Act — Article 10 (Data and Data Governance)
Applies to *high-risk* AI; enforceable 2 August 2026. Training/validation/test
datasets must be relevant, representative, and "free of personal data where
technically feasible" — the Act's closest thing to a data-minimization mandate
for AI training data. It defers the specific de-identification *mechanism* to
GDPR. A local single-user assistant like BlarAI is likely low-risk or
out-of-scope, but demonstrating Article-10-style governance is still portfolio-
and exam-relevant.

### IAPP AIGP — Body of Knowledge v2.1 (effective 2 February 2026)
The certification standard this portfolio targets. Four domains; see §6 for the
full mapping. Exam: 100 questions, 3 hours, pass = 300/500.

---

## 2. De-identification & redaction technique taxonomy

| Technique | What it does | When appropriate | Reversible | Utility kept |
|---|---|---|---|---|
| Masking / suppression | Replace span with fixed chars (`****`) or delete it | Quick sanitization, logs, output filtering | No | Low |
| Pseudonymization | Replace PII with consistent tokens; mapping held separately | GDPR-aligned analytics; preserve referential links | Yes (with key) | High |
| Tokenization | Replace with non-exploitable, format-keeping surrogate | Payment data (PCI-DSS); LLM prompt sanitization | Yes (with vault) | High |
| Generalization | Replace specific value with a range/category (age 34 → "30–40") | Analytics; quasi-identifier protection | No | Medium |
| k-anonymity | Each record indistinguishable from k−1 others on quasi-identifiers | Tabular dataset release | No | Medium-low |
| Differential privacy | Add calibrated statistical noise; formal guarantee | Population analytics; DP-SGD model training | No | Medium (ε tradeoff) |
| Format-preserving encryption | Encrypt but keep field format (16 digits stay 16 digits) | Legacy systems needing real-looking format | Yes (with key) | Very high |
| Synthetic substitution | Replace PII with plausible fake values ("John Smith" → "Alice Chen") | Training/test data needing realistic context | No | Very high |
| Label-replacement redaction | Replace span with its entity-type label (`<PHONE_NUMBER>`) | AI output filtering; audit trails | No (label shown) | Medium |

**For BlarAI's provenance-aware design:** the relevant technique is
**label-replacement redaction** for untrusted/hallucinated PII, and
**pass-through** (no redaction) for PII from the user's own trusted documents.
The novel part is not the technique — it is the *context-routing layer* that
chooses between them based on data origin.

---

## 3. Reference architectures (detect → classify → transform)

All major tools implement the same logical pipeline:

```
Input text
  → DETECT     NLP/NER + regex + rule-based  → (entity, offset, confidence, type)
  → CLASSIFY   filter by confidence + entity-type policy
  → TRANSFORM  per-entity operator: redact / mask / replace / encrypt / pass-through
  → OUTPUT     redacted text + audit record (what was found, what was done, why)
```

### Microsoft Presidio (open-source — the reference architecture)
Two-stage, cleanly separated:
- **Analyzer** (detect) — recognizers of three kinds: NLP/NER (spaCy, HuggingFace,
  Stanza), regex/pattern, and rule-based with checksum (e.g. Luhn for credit
  cards). Each recognizer declares *context words*; a context word near a match
  boosts its confidence score. Output: `RecognizerResult` list with entity type,
  character offsets, confidence 0.0–1.0.
- **Anonymizer** (transform) — five built-in operators: Replace, Redact, Mask,
  Hash, Encrypt. Operators are assigned **per entity type**. Custom operators are
  fully pluggable — any Python callable.

Crucially: Presidio's "context" means *linguistic* context (nearby words), **not
data provenance**. It has no built-in notion of "this entity came from a trusted
vs. untrusted source." The **custom-operator interface is the documented
extension point** for provenance-aware routing — a custom operator can receive
source metadata and choose pass-through vs. redaction accordingly.

### Cloud services (managed, not local)
- **AWS Comprehend** — `DetectPiiEntities` returns spans + confidence;
  `ContainsPiiEntities` returns labels only (triage). Redaction is the caller's job.
- **Google Cloud Sensitive Data Protection** (ex-DLP) — 200+ infoType detectors;
  offers redaction, masking, format-preserving encryption, date-shifting,
  KMS-backed pseudonymization.
- **Azure AI Language PII** — NER + regex; separate text / conversation /
  document endpoints; `domain=phi` restricts to health identifiers.

**BlarAI implication:** BlarAI is local-first and lightweight; the cloud services
are out of scope as dependencies. Presidio is the architecture to *mirror* — the
detect/classify/transform split and the per-entity-type operator model — even if
the detector itself stays a lightweight local component.

---

## 4. Provenance / lineage as a governance signal

Enterprises increasingly drive governance decisions from **where data came
from**, not just what it is. Documented patterns:

1. **Semantic classification beyond binary PII/non-PII** — an SSN in a live
   customer record is handled differently from the same SSN in a test dataset;
   the source context governs the policy.
2. **Lineage-propagated policy tags** — a "contains PII" tag on a source
   propagates through the data-lineage graph to every downstream model/report.
3. **Provenance signals in RAG pipelines** — retrieval is routed by data
   classification labels and segmented vector indexes.
4. **Lineage-aware auto-actions** — systems "mask, quarantine, or rollback
   automatically with audit-ready evidence."
5. **Governance signals for LLMs** — industry sources state LLMs "rely on
   governance signals — provenance, classification, lineage — to determine what
   data can be used, transformed, or returned."

**Honest framing for the portfolio.** The functional pattern — context/lineage-
aware governance — is well established and citable. The *specific term*
"provenance-aware redaction" does **not** appear as a branded industry standard;
the closest named patterns are "context-aware governance," "lineage-aware
auto-action," and "governance-aware AI agents." BlarAI's "provenance-aware
honest redaction" is therefore best presented as an **original synthesis grounded
in established enterprise lineage-governance practice** — not as an existing
named standard. That honesty is itself good portfolio practice.

---

## 5. Enterprise AI + PII use cases

Two trigger types: **(a)** PII flows *through* an AI system; **(b)** a user asks
an AI to retrieve or reason *about* someone's PII (needs entitlement-aware
filtering).

### (a) PII flowing through an AI system
1. **LLM customer-support copilot** — call transcripts and CRM records (names,
   account numbers, payment data) enter the model context; outputs and logs must
   be redacted. Drivers: PCI-DSS, CCPA, GDPR.
2. **RAG over PII-laden document stores** — enterprise knowledge assistants
   retrieve HR docs, contracts, employee records; needs entitlement-aware
   retrieval plus output-layer PII filtering, routed by each chunk's
   classification label.
3. **AI clinical scribe** — transcribes clinician–patient conversations (PHI);
   notes must be de-identified before secondary use (HIPAA Safe Harbor / Expert
   Determination).
4. **AI processing support tickets / call transcripts** — analytics must use
   pseudonymized IDs; archived transcripts redacted.
5. **Code assistant + log scrubbing** — developers paste logs/traces containing
   emails, user IDs, tokens; the LLM gateway scrubs inbound prompts and outbound
   suggestions.
6. **Fine-tuning / training-data scrubbing** — de-identify corpora before
   training so the model cannot memorize and regurgitate individuals (explicit
   EU AI Act Art. 10 and HIPAA concern).
7. **LLM gateway for third-party APIs** — pseudonymize PII before sending to
   OpenAI/Anthropic/Azure, deanonymize on return; the model reasons about
   "Alice" while Alice's real identity never leaves the perimeter.
8. **AI-powered analytics & data sharing** — reports use aggregate/pseudonymized
   data; differential privacy can give a formal guarantee on shared statistics.

### (b) Users asking an AI about someone's PII (entitlement-aware)
9. **DSAR fulfillment copilot** — a Data Subject Access Request: the AI finds all
   records about the requester, **redacts third-party PII** in those records, and
   produces an auditable report. (GDPR Art. 15; CCPA; HIPAA right of access.)
10. **HR / people-analytics queries** — a manager asks for salary data; the AI
    enforces role-based access — aggregate bands yes, individual figures only if
    authorized.
11. **Legal e-discovery** — AI document review must separate discoverable PII,
    withheld-and-logged privileged material, and third-party PII to redact; the
    *provenance* of each PII instance (party vs. non-party) drives the decision.
12. **Consumer AI assistant asked about a third party** — "find my neighbour's
    address." The AI must recognize the data belongs to a non-consenting third
    party, decline/redact, and log the request. **This is the closest analogue
    to BlarAI's design:** PII from documents *the user loaded* is trusted; PII
    the model generates or pulls about non-users is redacted.

---

## 6. AIGP body-of-knowledge alignment (v2.1, effective 2026-02-02)

| Domain | Title | ~Questions | ~% of exam |
|---|---|---|---|
| I | Foundations of AI Governance | 16–20 | ~21% |
| II | Laws, Standards and Frameworks for AI | 19–23 | ~25% |
| III | Governance of AI Development | 21–25 | ~27% |
| IV | Governance of AI Deployment and Use | 21–25 | ~27% |

**How the provenance-aware redaction capability maps:**

| AIGP domain / indicator | What the capability demonstrates |
|---|---|
| **I.C** — AI Governance Program Components | A concrete data-governance policy artifact, evaluated and documented. |
| **II.A** — Privacy & Data Protection Laws | Implements GDPR data minimization (Art. 5) and the trusted/untrusted handling distinction; correct use of pseudonymization (Art. 4(5)) vs. anonymization (Recital 26). |
| **II.A.3** — Automated Decision-Making | The redaction engine makes automated decisions about what PII to surface vs. suppress — explainable and logged. |
| **II.B** — AI-Specific Laws | EU AI Act Article 10 data-governance posture. |
| **II.D** — Industry Standards & Tools | References NIST AI RMF, NIST Privacy Framework, ISO/IEC 42001 & 27701 as the normative frame; mirrors Microsoft Presidio's reference architecture. |
| **III** — Governance of AI Development | Data governance enforced at inference time. |
| **IV** — Governance of AI Deployment & Use | Logged, auditable, *visible* redaction decisions + ongoing monitoring. |

The single capability yields a worked example touching **all four domains** —
strongest on II.A, II.D, III, and IV. A write-up that maps each design decision
to a specific domain is directly usable as AIGP exam-preparation evidence.

---

## Sources

1. NIST AI 100-1 (AI RMF 1.0) — https://nvlpubs.nist.gov/nistpubs/ai/nist.ai.100-1.pdf
2. NIST AI RMF overview — https://www.nist.gov/itl/ai-risk-management-framework
3. NIST AI 600-1 (GenAI Profile) — https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf
4. NIST Privacy Framework v1.1 IPD — https://nvlpubs.nist.gov/nistpubs/CSWP/NIST.CSWP.40.ipd.pdf
5. NIST SP 800-122 — https://csrc.nist.gov/pubs/sp/800/122/final
6. ISO/IEC 27701 — https://www.iso.org/standard/27701
7. ISO/IEC 27701:2025 overview — https://www.aarc-360.com/iso-iec-277012025-what-the-new-privacy-management-standard-means-for-your-organization/
8. GDPR Art. 4(5) commentary — https://academic.oup.com/book/41324/chapter/352294530
9. GDPR Recital 26 — https://www.dsgvo-portal.de/gdpr_recital_26.php
10. EDPB Pseudonymisation Guidelines 01/2025 — https://www.edpb.europa.eu/system/files/2025-01/edpb_guidelines_202501_pseudonymisation_en.pdf
11. EDPB Opinion 28/2024 on AI Models & Personal Data — https://www.edpb.europa.eu/system/files/2024-12/edpb_opinion_202428_ai-models_en.pdf
12. HIPAA De-identification Guidance (HHS) — https://www.hhs.gov/hipaa/for-professionals/special-topics/de-identification/index.html
13. 45 CFR 164.514 Safe Harbor vs. Expert Determination — https://www.accountablehq.com/post/hipaa-de-identification-standards-safe-harbor-vs-expert-determination-45-cfr-164-514
14. EU AI Act Article 10 — https://artificialintelligenceact.eu/article/10/
15. EU AI Act Article 10 (Service Desk) — https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-10
16. IAPP AIGP Certification — https://iapp.org/certify/aigp
17. AIGP Body of Knowledge v2.1 (PDF) — https://assets.contentstack.io/v3/assets/bltd4dd5b2d705252bc/blt0d33152fd20bc134/AIGP_Cert%20BOK.pdf
18. AIGP BoK v2.1 2026 update summary — https://www.privacybootcamp.com/Resources/Article/aigp-body-of-knowledge-2026
19. AIGP study path / domain weights — https://trainingcamp.com/articles/how-to-study-for-the-aigp-a-learning-path-built-around-the-bok-v2-1-blueprint/
20. Microsoft Presidio (GitHub) — https://github.com/microsoft/presidio
21. Presidio documentation — https://microsoft.github.io/presidio/
22. Presidio Analyzer docs — https://microsoft.github.io/presidio/analyzer/
23. Presidio — PII detection introduction — https://medium.com/neural-engineer/microsoft-presidio-an-engineers-introduction-to-pii-detection-and-de-identification-6a7c3fed6e50
24. AWS Comprehend DetectPiiEntities API — https://docs.aws.amazon.com/comprehend/latest/APIReference/API_DetectPiiEntities.html
25. AWS Comprehend real-time PII guide — https://docs.aws.amazon.com/comprehend/latest/dg/realtime-pii-api.html
26. AWS Comprehend responsible-AI card — https://docs.aws.amazon.com/ai/responsible-ai/comprehend-detectpii/overview.html
27. Google Cloud Sensitive Data Protection docs — https://docs.cloud.google.com/sensitive-data-protection/docs
28. Azure AI Language PII overview — https://learn.microsoft.com/en-us/azure/ai-services/language-service/personally-identifiable-information/overview
29. Azure AI Language PII how-to (text) — https://learn.microsoft.com/en-us/azure/ai-services/language-service/personally-identifiable-information/how-to/redact-text-pii
30. Azure AI Language PII transparency note — https://learn.microsoft.com/en-us/azure/ai-foundry/responsible-ai/language-service/transparency-note-personally-identifiable-information
31. Data lineage in the age of AI (Euno) — https://euno.ai/resources/data-lineage-in-the-age-of-ai/
32. AI data governance — lineage & oversight — https://softwaremind.com/blog/ai-data-governance-retrieval-security-lineage-and-oversight/
33. Solidatus — lineage for AI governance — https://www.solidatus.com/blog/why-data-lineage-is-essential-for-ai-7-governance-challenges-solved-by-ai-ready-lineage/
34. Governance signals for LLMs (Acceldata) — https://www.acceldata.io/blog/what-governance-signals-llms-rely-on-for-enterprise-ai-trust
35. Governance-aware AI agents (Acceldata) — https://www.acceldata.io/blog/how-governance-aware-ai-agents-enforce-data-policies
36. RAG pipeline security in enterprise SaaS (CSO Online) — https://www.csoonline.com/article/4163888/securing-rag-pipelines-in-enterprise-saas.html
37. RAG pipeline security best practices (Kiteworks) — https://www.kiteworks.com/cybersecurity-risk-management/rag-pipeline-security-best-practices/
38. Preventing LLM data leakage (Kiteworks) — https://www.kiteworks.com/cybersecurity-risk-management/prevent-llm-data-leakage-controls/
39. Participant-aware access control in enterprise AI (arXiv) — https://arxiv.org/pdf/2509.14608
40. Preventing data leakage in enterprise LLM (arXiv) — https://arxiv.org/pdf/2601.06366
41. LLM compliance risks & best practices (Lasso) — https://www.lasso.security/blog/llm-compliance
42. Redacting PII/PHI for legal compliance (Caseguard) — https://caseguard.com/articles/how-to-redact-pii-and-phi-for-legal-compliance/
43. Detecting & redacting PII with AWS Comprehend — https://aws.amazon.com/blogs/machine-learning/detecting-and-redacting-pii-using-amazon-comprehend/
44. k-Anonymity — Programming Differential Privacy — https://programming-dp.com/chapter2.html
45. Data anonymization techniques explained — https://data-security.business/data-anonymization-techniques-explained/
