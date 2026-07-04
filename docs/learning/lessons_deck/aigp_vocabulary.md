# AIGP Vocabulary Sheet — verified framework facts for the Lessons Deck

**Purpose:** the ONLY framework vocabulary the lessons-deck content may use for its
"AIGP connection" beats. Every claim below was verified against live sources on
2026-06-10. Content drafters MUST map lessons using this vocabulary and MUST NOT
invent framework details beyond it. (AIGP = Artificial Intelligence Governance
Professional, the IAPP — International Association of Privacy Professionals —
certification.)

## 1. IAPP AIGP Body of Knowledge v2.1 (effective 2026-02-02)

Four domains (restructured from seven in v2.0.1, February 2025; v2.1 keeps the
four-domain structure):

- **Domain I — Understanding the Foundations of AI Governance**
  - I.A Understand what AI is and why it needs governance
  - I.B Establish and communicate organizational expectations for AI governance
  - I.C Establish policies and procedures throughout the AI life cycle
- **Domain II — Understanding How Laws, Standards and Frameworks Apply to AI**
  - II.A Existing data-privacy laws as applied to AI
  - II.B Other existing laws as applied to AI
  - II.C AI-specific laws (EU AI Act; v2.1 adds South Korean and U.S. regulation)
  - II.D Main industry standards and tools (NIST AI RMF, ISO/IEC 42001; v2.1 adds ISO/IEC 42005)
- **Domain III — Understanding How to Govern AI Development**
  - III.A Govern the designing and building of the AI model and system
  - III.B Govern the collection and use of data in training and testing
  - III.C Govern the release, monitoring and maintenance of the model and system
- **Domain IV — Understanding How to Govern AI Deployment and Use**
  - IV.A Evaluate key factors and risks relevant to the decision to deploy
  - IV.B Perform key activities to assess the AI model and system
  - IV.C Govern the deployment and use of the model and system

v2.1 notable deltas: "AI model" → "AI model and system" terminology; agentic
architectures added as deployment examples; expanded data-governance and
automated-decision-making coverage.

## 2. NIST AI Risk Management Framework (AI RMF 1.0, NIST AI 100-1)

Four core functions — use these exact names, uppercase by convention:

- **GOVERN** — cross-cutting: risk culture, policies, accountability structures,
  roles, workforce; the enabling function for the other three.
- **MAP** — establish context: categorize the system, its purpose, capabilities,
  deployment environment, affected parties, and the risks specific to them.
- **MEASURE** — analyze, assess, benchmark and track AI risks with quantitative
  and qualitative methods; home of **TEVV** (test, evaluation, verification, and
  validation).
- **MANAGE** — prioritize and respond to risks: treatment plans, response
  implementation, residual-risk monitoring, communication.

Trustworthy-AI characteristics (NIST AI RMF §3): valid and reliable; safe;
secure and resilient; accountable and transparent; explainable and
interpretable; privacy-enhanced; fair with harmful bias managed.

Key distinction the deck leans on: **verification** (built to spec) vs.
**validation** (does the real job in the real context) — both live inside TEVV.

## 3. ISO/IEC 42001:2023

The first AI management system standard (**AIMS**). Management-system clauses
plus **Annex A** reference controls; organizations document a **Statement of
Applicability** justifying control inclusion/exclusion; continual improvement
on the plan-do-check-act management-system pattern.

**Accuracy rule:** do NOT cite specific Annex A control numbers or counts
(public sources disagree); refer to control themes generically (e.g. "ISO/IEC
42001's Annex A controls on the AI system life cycle"). ISO/IEC 42005 (AI
system impact assessment, added in BoK v2.1) may be named where impact
assessment is the topic.

## 4. OECD AI Principles (2019, updated 2024)

Values-based principles, stable vocabulary: human-centred values and fairness;
transparency and explainability; **robustness, security and safety**;
accountability; inclusive growth, sustainable development and well-being.

## 5. EU AI Act (concept level only)

Risk-based regulation: prohibited / high-risk / limited (transparency) /
minimal-risk tiers. High-risk obligations include: a risk-management system,
data governance, technical documentation, record-keeping/logging, transparency,
**human oversight**, and accuracy/robustness/cybersecurity.
**Accuracy rule:** do NOT cite article numbers.

## 6. Mapping discipline for drafters

- Map each lesson to **one primary AIGP domain** (a competency where obvious),
  plus **one or two framework anchors** (a NIST function, TEVV, ISO/IEC 42001
  AIMS/Annex-A theme, an OECD principle, or an EU AI Act concept).
- The mapping must be earned by the lesson's actual content, not decorative.
- Mark nothing as "required by" a framework; these are voluntary frameworks —
  say "exemplifies", "is what NIST's MEASURE function asks for", etc.
- All mappings are DRAFT until verified by the integrating session.

## Sources (verified 2026-06-10)

- https://iapp.org/certify/aigp (certification home)
- https://www.privacybootcamp.com/Resources/Article/aigp-body-of-knowledge-2026 (v2.1 deltas, effective date)
- https://oliverpatel.substack.com/p/the-unofficial-aigp-resource-guide (v2.0.1 domain/competency enumeration)
- https://nvlpubs.nist.gov/nistpubs/ai/nist.ai.100-1.pdf (NIST AI 100-1, AI RMF 1.0)
- https://airc.nist.gov/airmf-resources/airmf/5-sec-core/ (AI RMF core functions)
- https://www.isms.online/iso-42001/annex-a-controls/ + https://www.a-lign.com/articles/understanding-iso-42001 (ISO/IEC 42001 overview; control-count disagreement noted)
