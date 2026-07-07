# AIGP 6-Week Study Plan

**Goal.** Pass the IAPP AIGP (Artificial Intelligence Governance Professional)
exam by early July 2026.

**Owner.** Blair. **Created.** 2026-05-22.

This plan runs in parallel with the BlarAI build. The build supplies *worked
examples* — concrete, hands-on anchors for the abstract material — but the plan
below is the syllabus. Studying the plan is what passes the exam; the build makes
it stick.

---

## The exam at a glance

- **Credential:** AIGP — Artificial Intelligence Governance Professional, issued by the IAPP (International Association of Privacy Professionals).
- **Body of Knowledge:** v2.1, effective 2 February 2026 — this plan tracks that version.
- **Format:** 100 multiple-choice questions (85 scored + 15 unscored pilot questions), 3 hours.
- **Pass mark:** 300 out of 500 (scaled scoring).
- **Case studies:** roughly 30% of questions attach to a scenario — you read a situation and apply the right governance reasoning. Practising this style matters as much as knowing facts.

### The four domains and their weights

| Domain | Title | \~% of exam |
|---|---|---|
| I | Foundations of AI Governance | \~21% |
| II | Laws, Standards and Frameworks for AI | \~25% |
| III | Governance of AI Development | \~27% |
| IV | Governance of AI Deployment and Use | \~27% |

Domains III and IV together are over half the exam — the plan weights time accordingly.

---

## Your timeline

- **Start:** 2026-05-22 (Week 1).
- **Target exam date:** \~2026-07-03 (end of Week 6).
- **Action this week:** book the exam now, for a date around 1–3 July. A booked exam is a commitment device and it locks the plan. Tell me the real date once booked and I will recalibrate the weekly split.
- **Effort:** budget \~5–8 hours per week — a little most days beats one long session.

---

## Core resources

| Resource | Use | Note |
|---|---|---|
| IAPP AIGP Body of Knowledge v2.1 (official PDF, free) | The spine — every topic below maps to it | https://iapp.org/certify/aigp |
| Primary framework texts (free) | Deep source for the heavily-weighted Domains II–III | NIST AI RMF, EU AI Act, NIST Privacy Framework — all free online; see the research doc's source list |
| Official IAPP AIGP textbook / training | Optional depth if budget allows | IAPP-published; the most exam-aligned paid option |
| A practice-question set / mock exam | Highest-yield activity in Weeks 5–6 | Prefer IAPP's official practice exam; treat third-party banks with caution — I can't vouch for their accuracy |
| `docs/governance/pii_redaction_governance_research.md` | The worked-example backbone for Weeks 2–3 | Already in this repo |

---

## Week-by-week

### Week 1 — Domain I: Foundations of AI Governance (\~21%)

**Topics.** What AI and machine learning are; types of AI (supervised, unsupervised, reinforcement learning; generative AI and large language models; computer vision); narrow vs. general AI. The AI/ML lifecycle at a high level. Core technical concepts: training data, models, parameters, inference, foundation models. *Why* AI governance exists — the risks and harms of AI: bias and discrimination, privacy loss, safety, security, opacity, accountability gaps, environmental cost. Responsible / trustworthy-AI principles: fairness, accountability, transparency, explainability, safety, privacy, human oversight, robustness. Roles in AI governance and how an AI governance program is structured.

**BlarAI worked example.** BlarAI itself as a case study: fail-closed architecture, privacy-by-architecture (local, no network at runtime), human oversight (you verify every change live), and the PGOV as a responsible-AI control.

**Self-check.** In your own words: bias, explainability, the difference between narrow and general AI. Name the trustworthiness characteristics. Why does AI need governance distinct from ordinary software governance?

### Week 2 — Domain II, part 1: Existing laws applied to AI (\~half of \~25%)

**Topics.** Data-protection / privacy law and AI: GDPR's principles (lawfulness, fairness, transparency, purpose limitation, data minimization, accuracy, storage limitation, integrity & confidentiality, accountability); legal bases; data-subject rights; automated decision-making and profiling (Art. 22); Data Protection Impact Assessments. Pseudonymization vs. anonymization. The US privacy landscape — sectoral laws (HIPAA, GLBA, FCRA, COPPA) and state laws (CCPA/CPRA). Anti-discrimination and civil-rights law applied to AI (hiring, credit, housing). Intellectual property and AI. Product liability and consumer protection.

**BlarAI worked example — the payoff week.** The provenance-aware redaction build maps straight onto this domain: GDPR data minimization (Art. 5), pseudonymization (Art. 4(5)) vs. anonymization (Recital 26), HIPAA de-identification (Safe Harbor's 18 identifiers and Expert Determination), and automated decision-making (the redaction engine *is* an automated decision). You will have built the thing the exam asks about.

**Self-check.** Recite GDPR's principles. Explain pseudonymization vs. anonymization and why it matters legally. Name HIPAA's two de-identification methods.

### Week 3 — Domain II, part 2: AI-specific laws, standards & frameworks (\~half of \~25%)

**Topics.** The EU AI Act: risk tiers (unacceptable, high, limited, minimal), high-risk obligations, general-purpose-AI rules, the timeline, and Article 10 data governance. The US picture: federal action, state AI laws (e.g., Colorado), sectoral guidance. Global instruments: OECD AI Principles, UNESCO, the Council of Europe AI Convention, and other jurisdictions. Standards and frameworks: NIST AI Risk Management Framework (its GOVERN / MAP / MEASURE / MANAGE functions), ISO/IEC 42001 (AI management system), ISO/IEC 23894 (AI risk), ISO/IEC 27701, the NIST Privacy Framework.

**BlarAI worked example.** The redaction artifact cites NIST AI RMF's MANAGE function and ISO/IEC 42001 / 27701 as its normative frame; working out BlarAI's (low-risk / out-of-scope) classification under the EU AI Act is itself a Domain-II exercise.

**Self-check.** List the EU AI Act risk tiers. Name NIST AI RMF's four functions. Say what ISO/IEC 42001 is for.

### Week 4 — Domain III: Governance of AI Development (\~27%)

**Topics.** The AI development lifecycle in depth: problem definition, data collection and governance, model design and training, testing and validation, documentation. Data governance for AI — data quality, representativeness, bias in data, provenance and lineage, minimization in training data. Model documentation — model cards, datasheets, technical documentation. Testing — validation, bias and fairness testing, red-teaming, adversarial testing. Impact assessments — AI impact assessments, fundamental-rights impact assessments, DPIAs. Designing in privacy, security and safety from the start; identifying and mitigating risk at the design phase. Third-party and procured components in development.

**BlarAI worked example.** BlarAI's PGOV as an inference-time data-governance control; the BUILD_JOURNAL as living system documentation; the test-suite-plus-live-verification discipline as testing/validation governance.

**Self-check.** Name the lifecycle stages. Say what belongs in a model card. Describe what an AI impact assessment covers and when you run one.

### Week 5 — Domain IV: Governance of AI Deployment and Use (\~27%)

**Topics.** Deployment readiness and release governance. Post-deployment monitoring — model drift, performance degradation, ongoing testing. AI incident management and response. Human oversight in operation (human in / on / out of the loop). Transparency and disclosure to users; labeling AI-generated content. Third-party and procurement governance for deployed systems; vendor management and contracts. Decommissioning and retirement. Ongoing risk management, audits, and accountability structures.

**BlarAI worked example.** The redaction artifact's audit logging and *visible* (honest) decisions are deployment-phase transparency and auditability; the `pii_mode` config switch is a release-governance control; the devplatform "monitored unpause" pattern is incident-response-style governance in practice.

**Self-check.** Distinguish monitoring from incident response. Name the human-oversight modes. Say what decommissioning governance has to cover.

### Week 6 — Integration, case studies and practice exams

**Topics.** Sit at least one full-length practice exam under timed (3-hour) conditions. Drill the case-study question style — read a scenario, identify the domain, apply the reasoning. Review every weak area surfaced by the Week 1–5 self-checks and your practice score. Memorize the framework cheat-sheet: NIST AI RMF's four functions, the EU AI Act tiers, GDPR's principles, the ISO numbers, the AIGP domain weights. Keep the final two days light — review only, and rest before exam day.

**Self-check.** Score a practice exam at or above the pass line twice before sitting the real one.

---

## How the BlarAI build maps into the plan

| BlarAI build feature | AIGP domain it demonstrates | Study week |
|---|---|---|
| Provenance-aware honest redaction (`pii_mode = redact`) | II.A — privacy law (GDPR, HIPAA); II.A.3 — automated decision-making | Week 2 |
| Redaction's NIST / ISO normative framing | II.D — standards and frameworks | Week 3 |
| PGOV as inference-time data governance + BUILD_JOURNAL as documentation | III — governance of AI development | Week 4 |
| Redaction audit logging + visible decisions + `pii_mode` config | IV — governance of AI deployment and use | Week 5 |
| BlarAI as a whole — fail-closed, local, human-verified | I — foundations / responsible AI | Week 1 |

---

## Weekly method

- **Spread it out.** A little most days beats one marathon — spaced repetition is how this material sticks.
- **Practice questions are the highest-yield activity.** Start them in Week 3, not Week 6. Wrong answers tell you where to study.
- **Explain it aloud.** If you can teach a concept in plain words (the Feynman technique), you know it. The build gives you something concrete to teach *from*.
- **Use the self-checks as gates.** Don't move to the next week until you can pass the current one.
- **I will quiz you on request** — ask me to drill any domain, or to run a mock case-study question, any time.

---

*Recalibrate this plan if the exam date moves, if a week runs long, or if practice
scores reveal a weak domain. The plan serves the deadline — not the other way around.*
