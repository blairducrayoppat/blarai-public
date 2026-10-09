# R4 — Law and liability for a Windows AI-agent governor, founder in the EU

Feasibility study #1549. Written 2026-09-17. Author: research agent R4. Not legal advice — this compiles
obligations with sources so a non-lawyer founder can see what a lawyer must confirm and roughly what it costs.

Every acronym is spelled out on first use.

---

## 0. Outcome first

**Five things dominate everything else in this file.**

1. **The Cyber Resilience Act (Regulation (EU) 2024/2847, "CRA") is the expensive one, not the AI Act.**
   A governor is plainly a "product with digital elements". The whole question is whether it lands in Annex III
   Class I (self-assessment possible) or is treated as a firewall or intrusion-prevention system in Class II
   (an outside certification body is *mandatory*, no exceptions). **The design decision that moves it is where you
   enforce.** Adjudicating an agent's *action* keeps you out of Class II. Putting a packet-level chokepoint on the
   machine and blocking traffic makes "firewall" a live argument, and firewalls are Class II. Full application is
   **11 December 2027**; the vulnerability-reporting duty starts **11 September 2026** and applies to products
   already on the market.

2. **The new Product Liability Directive has a clause written as if for this product.** Directive (EU) 2024/2853
   Article 7(2)(i): in assessing defectiveness, account is taken of *"in the case of a product whose very purpose
   is to prevent damage, any failure of the product to fulfil that purpose."* Software is a product (Article 4(1)).
   Liability is strict, **cannot be excluded by any contract term** (Article 15), and covers *"destruction or
   corruption of data that are not used for professional purposes"* (Article 6(1)(c)). Applies to products placed
   on the market after **9 December 2026**. Money moved by a wrong "allow" is pure economic loss and falls outside
   this Directive; **family photos and personal documents destroyed by a wrong "allow" fall squarely inside it.**

3. **A deterministic rule engine is not an AI system.** Commission Guidelines C(2025) 5053 final of 29 July 2025,
   paragraph 46: systems that follow "predefined, explicit instructions or operations… without any 'learning,
   reasoning or modelling' at any stage" are "basic data processing" and fall outside the definition. The AI Act
   is therefore a **demand driver, not a compliance burden** — and that demand just moved: the **AI Omnibus
   entered into force 27 July 2026** and pushed Annex III high-risk obligations to **2 December 2027** and
   Annex I product obligations to **2 August 2028**. Roughly sixteen months of compliance-driven demand vanished.

4. **BlarAI's licence does not qualify as free and open-source for either the CRA or the PLD.** PolyForm
   Noncommercial 1.0.0 forbids commercial use. The CRA (Article 3, definition 48) requires a licence "which
   provides for all rights to make it freely accessible, usable, modifiable and redistributable". Publishing a
   governor under PolyForm buys **none** of the open-source exclusions. If the founder wants those exclusions he
   must use a genuine free-and-open-source licence (Apache-2.0, MIT, GPL). He holds the copyright, so he can.

5. **"Free" does not mean "out of scope."** Both the CRA and the PLD attach to supply "in the course of a
   commercial activity, whether in return for payment or free of charge". CRA recital 15 names the triggers:
   charging a price, charging for support above cost, *an intention to monetise*, requiring personal-data
   processing for anything beyond security/compatibility/interoperability, donations above cost. A free build
   that exists to sell a paid build is commercial.

**The three checklists are in section 3. The multi-user privacy design answer is in section 2.**

---

## 0.1 How every item is graded

| Grade | Meaning |
|---|---|
| **REPORTED** | Read in a primary or official source in this study. The source URL, instrument number, article and page/document date are given. |
| **GUESSED** | Not read in a source during this study. The reasoning is shown and the surface a lawyer should read is named. Treat as a question, not an answer. |

Where a figure came from a **sibling report in this same study** (R2-D on distribution and code signing), it is marked
**REPORTED (R2-D)** and the sibling's own source number is given. That is second-hand within this study and is flagged
as such.

Primary texts were fetched from the EU Publications Office cellar repository (`publications.europa.eu/resource/...`),
not from eur-lex.europa.eu, which blocked automated access with an AWS WAF challenge (HTTP 202, empty body) on every
attempt. The cellar documents are the Official Journal XML/XHTML originals.

---

## 1. Obligations table

### 1.1 Legal form — sole trader, or a company

| Obligation / fact | Instrument + article | Trigger | What it requires concretely | Cost or step | Grade + source + date |
|---|---|---|---|---|---|
| Personal liability is unlimited for a sole trader, and product liability cannot be contracted away | Dir. (EU) 2024/2853 Art. 15: liability "is not, in relation to the injured person, limited or excluded by a contractual provision or by national law" | selling / free-in-commerce / EU | A sole trader's personal assets stand behind every defect claim. A company interposes a legal person. | Company formation, below | **REPORTED** — cellar PLD OJ text, Art. 15; OJ L, 2024/2853, 18.11.2024 |
| A company is **required** to use the cheapest credible code signing | Microsoft Azure Artifact Signing eligibility terms | selling / free (any signed binary) | Public Trust certificates are issued to **organisations** in the EU; "Individual developers must be located in the United States or Canada." An EU sole trader without a registered entity cannot use it. | €8.58/month (Basic, $9.99) | **REPORTED (R2-D)** — R2-D §3, source R[24], Microsoft Learn quickstart, ms.date 2026-05-21 |
| A company is **required** for an OV (organisation-validated) code-signing certificate | Commercial CA terms | selling / free | OV certificates are issued to organisations only. Individuals can buy IV (individual-validated) certificates instead. | OV €109–199/yr (SSL.com $109.65–129, Certum €177); IV ~$129/yr | **REPORTED (R2-D)** — R2-D §3 table, sources R[42]–[47], fetched 2026-09-17 |
| A company is **required** to be an open-source software steward | Reg. (EU) 2024/2847 Art. 3, def. 14: "'open-source software steward' means **a legal person**, other than a manufacturer…" | open-sourcing | An individual can never be a steward. He is either a manufacturer (if monetising) or out of scope. A foundation or company is needed to take the steward role. | Formation cost of the legal person | **REPORTED** — cellar CRA OJ text, Art. 3(14); OJ L, 2024/2847, 20.11.2024 |
| A Microsoft Store **company** account needs a business identity | Microsoft Partner Center onboarding | selling via Store | DUNS number or official business documents, manual review 2–5 business days, and a work e-mail on a domain the company owns. | No registration fee under the new onboarding (both account types) | **REPORTED (R2-D)** — R2-D §2, source R[3], ms.date 2026-09-17, updated 2026-07-17 |
| **Estonia — OÜ (osaühing) via e-Residency** | Estonian Commercial Code (Äriseadustik) | EU establishment | e-Residency digital identity, then online incorporation in the e-Business Register. No notary visit. Needs an Estonian legal address and a contact person (bought as a service). Annual report mandatory. | **e-Residency state fee €150**; **company registration €265**; legal address + contact person **€200–400/yr**; accounting ~€600–1,500/yr (not verified) | **REPORTED** for the three fee figures — e-resident.gov.ee/become-an-e-resident/ and /start-a-company/, fetched 2026-09-17. **GUESSED** for accounting. |
| Estonia — minimum share capital | Äriseadustik §136 | EU establishment | The former €2,500 minimum was abolished; the minimum is now €0.01 per share. Reasoning: this change was made by a 2022 amendment effective 1 February 2023 and is why e-Residency marketing no longer mentions €2,500. | €0.01 | **GUESSED** — read §136 of the Commercial Code to confirm |
| Estonia — corporate income tax | Estonian Income Tax Act | EU establishment | 0% on undistributed profits; tax falls due on distribution. This is the main reason founders choose Estonia. | — | **GUESSED** — confirm the current distribution rate with an Estonian accountant; the rate has been rising |
| **Ireland — private company limited by shares (LTD)** | Companies Act 2014 | EU establishment | Register with the Companies Registration Office (CRO) via CORE. Annual return (Form B1) plus financial statements every year. At least one director resident in the European Economic Area, **or** a Section 137 bond. | **Annual return (B1) filing fee €20**. Incorporation Form A1 fee **not verified** (cro.ie blocks automated access). Section 137 bond typically ~€2,000 for two years. | **REPORTED** for €20 — cro.ie/annual-return/filing-an-annual-return/ (via search index, 2026). **GUESSED** for A1 and the bond — read cro.ie/publications/fees/company/ |
| Ireland — minimum share capital / audit | Companies Act 2014 | EU establishment | No statutory minimum share capital for an LTD. Audit exemption available for small companies but **lost permanently for that year if the annual return is filed late** — a real trap for a one-person company. | — | **GUESSED** — confirm the audit-exemption-loss rule and current small-company thresholds |
| **Netherlands — BV (besloten vennootschap)** | Dutch Civil Code Book 2 | EU establishment | Incorporated by a civil-law notary (in person or online). The notary registers the BV, its directors and its ultimate beneficial owners with the Chamber of Commerce (KVK). Quarterly VAT returns. | **Notary €500–1,500**; **bookkeeping €600–1,800/yr**; **minimum capital €0.01**; KVK Business Register registration fee (amount not shown on the page) | **REPORTED** — business.gov.nl/starting-your-business/choosing-a-business-structure/private-limited-company-bv/, fetched 2026-09-17 |
| Netherlands — small business VAT scheme | Dutch VAT Act (KOR) | EU establishment | Turnover up to €20,000/yr: do not charge or reclaim VAT. | — | **REPORTED** — same page |
| Non-EU establishment: a Union importer or authorised representative becomes liable | Dir. (EU) 2024/2853 Art. 8(1)(c) | outside EU | If the manufacturer is established outside the Union, the **importer**, the **authorised representative**, and failing both the **fulfilment service provider** are liable alongside the manufacturer. Art. 8(3): a distributor who cannot name an EU-established liable operator within one month becomes liable itself. | Whoever you appoint carries strict liability — price it into their fee | **REPORTED** — cellar PLD text, Art. 8; 18.11.2024 |
| CRA authorised representative is **optional**, unlike the GDPR one | Reg. (EU) 2024/2847 Art. 18(1): "A manufacturer **may**, by a written mandate, appoint an authorised representative." | outside EU | No mandatory EU representative under the CRA. The importer and distributor obligations (Arts. 19–20) do the work instead. | €0 | **REPORTED** — cellar CRA text, Art. 18(1) |

**When is a company actually needed? Five independent reasons, any one of which is sufficient:**
(1) the cheapest code signing is organisations-only; (2) OV certificates are organisations-only; (3) a Store company
account needs a business identifier; (4) the PLD liability shield, because PLD liability cannot be disclaimed; (5) only
a legal person can be a CRA open-source steward. **The signing reason alone decides it for a commercial product.**

---

### 1.2 Warranty, conformity and what a licence cannot disclaim

| Obligation | Instrument + article | Trigger | What it requires concretely | Cost or step | Grade + source |
|---|---|---|---|---|---|
| The Digital Content Directive applies only where the consumer pays a price **or** provides personal data as counter-performance | Dir. (EU) 2019/770 Art. 3(1) | selling | Applies "where the trader supplies… and the consumer pays or undertakes to pay a price", and also where the consumer "provides… personal data", **except** where those data are processed exclusively to supply the content or to meet a legal requirement. | — | **REPORTED** — cellar DCD text, Art. 3(1); OJ L 136, 22.5.2019 |
| A free download with opt-in-only, off-by-default diagnostics is most likely **outside** the DCD | Dir. (EU) 2019/770 Art. 3(1), second subparagraph | free | Reasoning: the product is supplied identically whether diagnostics are on or off, so the consumer does not "provide personal data" *in exchange* for the software; nothing is given as counter-performance. If diagnostics were ever made a condition of use, this flips and the full conformity regime attaches to a free product. | €0 — but it is a **design constraint**: never gate any feature on diagnostics | **GUESSED** — reasoning above; have counsel read DCD recitals 24–25 |
| Objective conformity — the product must be fit and secure regardless of what the terms say | Dir. (EU) 2019/770 Art. 8(1)(a)–(b) | selling | Must be "fit for the purposes for which digital content… of the same type would normally be used" and possess the qualities "including in relation to functionality, compatibility, accessibility, continuity and **security**, normal for digital content… of the same type and which the consumer may reasonably expect". | Your marketing copy becomes a legal standard — Art. 8(1)(b) expressly imports "any public statement made by or on behalf of the trader… particularly in advertising". | **REPORTED** — cellar DCD, Art. 8(1) |
| **Duty to supply updates, including security updates** | Dir. (EU) 2019/770 Art. 8(2) | selling | "The trader shall ensure that the consumer is informed of and supplied with updates, including security updates, that are necessary to keep the digital content… in conformity, for the period of time… (b) that the consumer may reasonably expect, given the type and purpose". | For a one-off purchase of a security product, "reasonably expect" will be read generously. Budget the same period you commit to under the CRA (≥5 years). | **REPORTED** — cellar DCD, Art. 8(2) |
| Consumer's failure to install an update shifts the risk back — but only if you warned them | Dir. (EU) 2019/770 Art. 8(3) | selling | You escape liability for non-conformity caused solely by a missing update only if you told the consumer the update was available **and** what happens if they do not install it, **and** your installation instructions were adequate. | Build the warning into the updater UI; keep the text. | **REPORTED** — cellar DCD, Art. 8(3) |
| Minimum liability period | Dir. (EU) 2019/770 Art. 11(2) | selling | Where national law sets a period for latent non-conformity, it "shall not be less than two years from the time of supply". Continuous supply: liability runs for the whole contract period (Art. 11(3)). | — | **REPORTED** — cellar DCD, Art. 11 |
| **Disclaimers are simply not binding** | Dir. (EU) 2019/770 Art. 22(1) | selling | Any term that "to the detriment of the consumer, excludes the application of the national measures transposing this Directive, derogates from them or varies their effects" before the problem is raised "shall not be binding on the consumer". | The classic "AS IS, NO WARRANTY" block from an open-source licence **does not work** against an EU consumer who paid. | **REPORTED** — cellar DCD, Art. 22(1) |
| Unfair contract terms | Dir. 93/13/EEC Art. 3(1), Art. 6(1), Annex point 1(a)–(b) | selling | The general test is significant imbalance contrary to good faith in a non-negotiated term. The indicative Annex list includes terms excluding or limiting liability for death or personal injury caused by the trader, and terms inappropriately excluding the consumer's legal rights against the trader for non-performance. | — | **GUESSED** — the instrument and article numbers are stated from knowledge; the text was **not fetched** in this study (the Publications Office resolver would not return an English manifestation for CELEX 31993L0013). Have counsel read the consolidated 93/13 Annex. |
| 14-day right of withdrawal | Dir. 2011/83/EU Art. 9(1) | selling (distance contract with a consumer) | "the consumer shall have a period of 14 days to withdraw from a distance or off-premises contract, without giving any reason". | — | **REPORTED** — cellar CRD original text, Art. 9(1); OJ L 304, 22.11.2011 |
| **The digital-content exception to withdrawal** | Dir. 2011/83/EU Art. 16(m) | selling | No withdrawal right for "the supply of digital content which is not supplied on a tangible medium **if the performance has begun with the consumer's prior express consent and his acknowledgment that he thereby loses his right of withdrawal**." | Two separate tick-boxes on the download/checkout page, neither pre-ticked, logged with a timestamp. Without them you must honour a 14-day refund on every sale. | **REPORTED with a caveat** — cellar CRD **original 2011 text**, Art. 16(m). The consolidated version as amended by Dir. (EU) 2019/2161 adds a third condition (the trader has provided confirmation under Art. 7(2) or 8(7)). **Read the consolidated text before drafting.** |
| Pre-contractual information | Dir. 2011/83/EU Art. 6(1)(a)–(c) and following | selling | Before the consumer is bound: main characteristics, identity of the trader, geographical address, telephone number and e-mail, total price inclusive of taxes, duration, and the withdrawal information. | A "Legal" page and a checkout that shows all of it before the pay button. | **REPORTED** — cellar CRD, Art. 6(1) |
| **What a licence CAN and CANNOT do toward an EU consumer** | synthesis of the four instruments above | selling | **Cannot**: exclude product liability (PLD Art. 15); exclude or vary DCD conformity rights (DCD Art. 22); limit liability for death or personal injury (93/13 Annex); remove the withdrawal right other than through Art. 16(m). **Can**: define the product's intended purpose precisely (which narrows the Art. 8(1)(a) conformity benchmark and the PLD Art. 7(2)(b) "reasonably foreseeable use"); limit liability for pure economic loss toward **business** customers; set a support period and say so; disclaim fitness for purposes outside the stated purpose. | The single most valuable drafting move is **a precise, honest statement of what the product does and does not do** — it is the one lever that legitimately narrows every liability standard at once. | **GUESSED** (synthesis) — each underlying provision is REPORTED above |
| European Accessibility Act | Dir. (EU) 2019/882 Art. 2(1), Art. 4(5), Art. 3 def. of microenterprise | selling (own web shop) | Products in scope are "consumer general purpose computer hardware systems and **operating systems** for those hardware systems" — a desktop application is not caught. Services in scope include **e-commerce services**. But Art. 4(5): "Microenterprises providing services shall be exempt". Microenterprise = fewer than 10 persons and turnover or balance sheet ≤ €2 million. | €0 for a one-person vendor. Revisit at 10 employees. | **REPORTED** — cellar EAA text, Arts. 2, 3, 4(5); OJ L 151, 7.6.2019, p. 70. In force for services provided after 28 June 2025. |
| Data Act | Reg. (EU) 2023/2854 | — | Aimed at connected products (physical items that generate usage data) and at cloud data-processing services and switching. A local-only desktop application that sends nothing is neither. | €0 | **GUESSED** — reasoning above; source read was a law-firm summary (`_dataact_cc.txt`), not the Regulation |

---

### 1.3 Product liability — Directive (EU) 2024/2853

| Obligation / fact | Article | Trigger | What it requires concretely | Grade + source |
|---|---|---|---|---|
| **Software is a product** | Art. 4(1): "'product' means all movables… it includes electricity, digital manufacturing files, raw materials **and software**" | selling / free-in-commerce / EU | Strict liability. The injured person proves defectiveness, damage and causation — not fault. | **REPORTED** — cellar PLD, Art. 4(1) |
| Application date | Art. 2(1) | all | "This Directive shall apply to products placed on the market or put into service **after 9 December 2026**." Transposition deadline is the same date (Art. 22(1)). The old Directive 85/374/EEC continues for products placed before (Art. 21). | **REPORTED** — cellar PLD, Arts. 2(1), 21, 22(1) |
| **The open-source exemption** | Art. 2(2): "This Directive does not apply to free and open-source software that is developed or supplied **outside the course of a commercial activity**." | open-sourcing | Recital 14 explains: providing such software on open repositories is not "making it available on the market" unless it happens in the course of a commercial activity; supply by non-profits is presumptively non-commercial; **but** "where software is supplied in exchange for a price, or for personal data used other than exclusively for improving the security, compatibility or interoperability of the software, and is therefore supplied in the course of a commercial activity, this Directive should apply." | **REPORTED** — cellar PLD, Art. 2(2) and recital 14 |
| What "commercial activity" means for **open core** | Art. 2(2) + recital 14 | open-sourcing alongside a paid edition | Reasoning: the exemption turns on the *activity*, not the licence. Once the same person publishes a free core **and** sells a paid edition built on it, the core is being supplied in the course of a commercial activity — it is the funnel for the paid product. Recital 15 confirms the direction of travel: FOSS supplied non-commercially and later integrated commercially makes the **integrator** liable. Assume the free core is in scope. | **GUESSED** — reasoning shown; counsel should read recitals 14–15 and Art. 2(2) together |
| **Liability cannot be excluded** | Art. 15 | all | Member States must ensure liability "is not, in relation to the injured person, limited or excluded by a contractual provision or by national law." No EULA reaches this. | **REPORTED** — cellar PLD, Art. 15 |
| What damage is compensable | Art. 6(1) | all | (a) death or personal injury, including **medically recognised damage to psychological health**; (b) damage to or destruction of property, **except** the product itself, and except "property used exclusively for professional purposes"; (c) **"destruction or corruption of data that are not used for professional purposes."** Art. 6(2) adds non-material losses where national law allows. | **REPORTED** — cellar PLD, Art. 6 |
| **The clause written for this product** | Art. 7(2)(i) | all | Defectiveness is assessed on all circumstances including "**in the case of a product whose very purpose is to prevent damage, any failure of the product to fulfil that purpose.**" A governor's very purpose is to prevent damage. | **REPORTED** — cellar PLD, Art. 7(2)(i) |
| Other defectiveness factors that bite here | Art. 7(2)(c), (d), (f) | all | (c) "the effect on the product of any ability to continue to learn or acquire new features after it is placed on the market"; (d) the foreseeable effect of other products used together with it, including by inter-connection; (f) "relevant product safety requirements, including **safety-relevant cybersecurity requirements**" — i.e. CRA non-compliance is evidence of defectiveness. | **REPORTED** — cellar PLD, Art. 7(2) |
| The development-risk defence, and the hole in it | Art. 11(1)(e), Art. 11(2) | all | Art. 11(1)(e) exempts where "the objective state of scientific and technical knowledge… was not such that the defectiveness could be discovered". **But** Art. 11(2) removes the "the defect did not exist when I placed it on the market" defence where the defectiveness is due to a related service, software including updates, **a lack of updates necessary to maintain safety**, or a substantial modification, provided it is within the manufacturer's control. | **REPORTED** — cellar PLD, Art. 11 |
| Time limits | Arts. 16, 17 | all | Three years from awareness of damage, defectiveness and the liable operator (Art. 16(1)); absolute expiry 10 years from placing on the market (Art. 17(1)), extended to 25 years for latent personal injury (Art. 17(2)). | **REPORTED** — cellar PLD, Arts. 16–17 |
| **What a wrong "allow" actually looks like in liability terms** | Arts. 6, 7(2)(i) | all | Reasoning, three shapes: (1) **Agent moves money** — pure economic loss. *Not* covered by Art. 6, which lists no economic-loss head. The claim would be in contract (DCD conformity, a refund and damages under national law) or national negligence. (2) **Agent deletes or encrypts personal files, photos, documents** — Art. 6(1)(c) "destruction or corruption of data that are not used for professional purposes". Strict, undisclaimable, and Art. 7(2)(i) supplies the defectiveness finding almost on its own. **This is the exposure.** (3) **Agent exfiltrates personal data** — not a PLD damage head; runs through GDPR Art. 82 against whoever is the controller, and through national privacy torts. | **GUESSED** (application) — each provision cited is REPORTED |
| Joint liability and recourse | Arts. 12, 14 | all | Multiple liable operators are jointly and severally liable. Art. 12(2) removes a right of recourse against a defective software component's manufacturer in specified circumstances. | **REPORTED** — cellar PLD, Arts. 12, 14 |
| Disclosure of evidence | Art. 9 | all | A national court may order the defendant to disclose relevant evidence at the claimant's request. For a governor this means **your own signed record becomes discoverable** — which cuts both ways and is a reason to design it to be defensible. | **REPORTED** — cellar PLD, Art. 9 |

**The practical consequence:** the liability shape of this product is *asymmetric*. The money case is contract law and
can be managed with terms and a refund policy. The **data-destruction case is strict, uncappable and has an article
aimed at it**. Product liability insurance should be quoted before the product is priced.

---

### 1.4 Cyber Resilience Act — Regulation (EU) 2024/2847

#### Is a governor in scope?

**Yes. REPORTED.** Art. 2(1) applies the Regulation to "products with digital elements made available on the market,
the intended purpose or reasonably foreseeable use of which includes a direct or indirect logical or physical data
connection to a device or network." Art. 3(1) defines a product with digital elements as "a software or hardware
product and its remote data processing solutions". The Commission FAQ (v1.4, 04/09/2026) gives "standalone software
that can be downloaded and installed on a device… a program that can be downloaded via a website" as the first
example. A governor installed on a networked Windows PC meets the connection test.

#### Which class? — the expensive question

| Candidate category | The Commission's own technical description | Fit | Consequence |
|---|---|---|---|
| **Annex III Class I, entry 1** — "Identity management systems and privileged access management software and hardware…" | IR (EU) 2025/2392: identity management systems "provide mechanisms for authentication or authorisation… These systems include access management systems that control access of natural persons, legal persons, **devices or systems** to digital resources or physical locations." Privileged access management software "is an access management system that **controls and monitors access rights** to IT or OT systems and sensitive information **within an organisation**, including **systems enforcing differentiated access control policies** for privileged users." | **Strong.** A governor controls and monitors what agents may reach and enforces differentiated policies. "devices or systems" reaches software agents. Against it: "within an organisation" and "privileged users" both read as enterprise human-user PAM. | Class I → **Module A self-assessment is available only if a harmonised standard, common specification or EU cybersecurity certification scheme is applied** (Art. 32(2)). Otherwise a notified body under module B+C or module H. |
| **Annex III Class II, entry 2** — "Firewalls, intrusion detection and prevention systems" | IR (EU) 2025/2392: firewalls "protect a connected network or system from unauthorized access by **monitoring and restricting data communication traffic** to and from that network". Intrusion detection systems "**monitor traffic once it has entered the network environment** for suspicious activity and detect… that an intrusion has been attempted"; includes host-based IDS. Intrusion prevention systems are an IDS "that **actively responds** to an intrusion". | **Weak for action adjudication, strong for network enforcement.** A governor that adjudicates an agent's *action request* is not monitoring network traffic and is not responding to an *intrusion* — the agents are authorised software. But a governor that installs a packet filter or local proxy and blocks agent traffic **is** "monitoring and restricting data communication traffic", which is the firewall description almost word for word. | Class II → **a notified body is mandatory** (Art. 32(3)), even if harmonised standards are fully applied. There is no self-assessment route. |
| **Annex III Class I, entry 4** — "Software that searches for, removes, or quarantines malicious software" | IR: "typically referred to as antivirus or antimalware, that detect or search for malicious software or code on devices…" | **Weak.** A governor does not detect malicious code; it governs authorised agents. Unless the product markets itself as detecting rogue agents as malware. | Class I |
| **Annex III Class I, entry 7** — SIEM | IR: "collect data from multiple sources, analyse and correlate that data and present it as actionable information for security-related purposes" | **Weak but non-trivial** — the signed record plus a coverage dashboard does collect, correlate and present. IR recital 5 saves it: a SOAR product with SIEM-like functions is not a SIEM because its core functionality differs. Same argument applies. | Class I |
| **Default category** — none of the above | Art. 32(1) | **Arguable.** A governor's core functionality is a new thing: adjudicating AI-agent actions against a user policy. IR recital 5 makes core functionality decisive. | Default → **Module A self-assessment, no notified body, no harmonised standard needed.** |

**Verdict, marked GUESSED with the reasoning above:** the honest position is that **Class I entry 1 and the default
category are both defensible, and Class II is avoidable by design**. This is not resolvable from the texts alone — it
is the single most expensive legal uncertainty in the product, and it should be put to counsel *and*, if the answer
stays unclear, to a national market surveillance authority, before the architecture is frozen.

**The design rule that follows, and it is free to adopt now:** enforce by adjudicating the *action* at the agent's own
seam (a hook, a broker, a policy decision point the agent consults). Do **not** ship a network-layer chokepoint that
inspects and blocks traffic. The moment you do, "firewall" is a serious argument and the conformity route goes from
self-assessment to a mandatory notified body, with a cost and a calendar you do not control.

#### Obligations that apply whatever the class

| Obligation | Article | What it requires concretely | Grade |
|---|---|---|---|
| Secure by default | Annex I, Part I, point 2(b) | "made available on the market **with a secure by default configuration**… including the possibility to reset the product to its original state". For a governor this means the shipped profile is restrictive, not permissive. | **REPORTED** — cellar CRA Annex I |
| No known exploitable vulnerabilities at release | Annex I, Part I, point 2(a) | — | **REPORTED** |
| Automatic security updates on by default, with an opt-out | Annex I, Part I, point 2(c) | Automatic security updates "enabled as a default setting, with a clear and easy-to-use opt-out mechanism", notification of available updates, and the option to postpone. | **REPORTED** |
| Data minimisation is a **legal requirement**, not a policy | Annex I, Part I, point 2(g) | "process only data, personal or other, that are adequate, relevant and limited to what is necessary in relation to the intended purpose". The labels-and-hashes-not-content design is CRA compliance, not just good manners. | **REPORTED** |
| Security logging with an opt-out | Annex I, Part I, point 2(l) | "provide security related information by recording and monitoring relevant internal activity… **with an opt-out mechanism for the user**". The signed record must be switchable off by the user. | **REPORTED** — note the tension with the product's value proposition; see §2 |
| Secure and permanent deletion | Annex I, Part I, point 2(m) | "provide the possibility for users to securely and easily remove on a permanent basis all data and settings". | **REPORTED** |
| **Software bill of materials (SBOM)** | Annex I, Part II, point 1 | "identify and document vulnerabilities and components… including by drawing up a software bill of materials in a commonly used and machine-readable format covering **at the very least the top-level dependencies**". | **REPORTED** |
| Coordinated vulnerability disclosure policy and a contact address | Annex I, Part II, points 5–6 | Publish a CVD policy and a reporting contact before shipping. | **REPORTED** |
| Free security updates, disseminated without delay | Annex I, Part II, points 7–8 | Secure distribution mechanism; updates "free of charge" with advisory messages. | **REPORTED** |
| **Support period of at least five years** | Art. 13(8) | "the support period shall be at least five years" unless the product is expected to be in use for less. Determined by reasonable user expectations and the nature of the product; the reasoning goes in the technical documentation. | **REPORTED** — cellar CRA, Art. 13(8) |
| Updates stay available 10 years | Art. 13(9) | Each security update must remain available for 10 years after issue, or the rest of the support period, whichever is longer. | **REPORTED** |
| End-of-support date shown **at the time of purchase** | Art. 13(19) | Month and year, clearly and understandably, in an easily accessible manner. | **REPORTED** |
| Single point of contact | Art. 13(17) | Easily identifiable; users choose the means of communication; **"shall not limit such means to automated tools"** — a support bot alone is non-compliant. | **REPORTED** |
| Technical documentation | Art. 31 + Annex VII | Kept 10 years or the support period, whichever is longer (Art. 13(13)). | **REPORTED** |
| EU declaration of conformity and CE marking | Arts. 28, 29–30, Annex V | The CE mark must be visible, legible, indelible, generally ≥5 mm, and may not be placed where it is not easily visible. A simplified declaration with a URL to the full one is allowed (Art. 13(20), Annex VI). | **REPORTED** — Arts. from cellar CRA; the 5 mm rule from the Commission FAQ §6.7 |
| User information | Annex II | Name, address and contact of the manufacturer, single point of contact, intended purpose, known dependencies, CVD contact, support-period end, secure-deletion instructions. | **REPORTED** |
| **Reporting actively exploited vulnerabilities — from 11 September 2026** | Art. 14(1)–(2), Art. 71(2) | Early warning within **24 hours** of becoming aware, a fuller vulnerability notification within **72 hours**, simultaneously to the coordinator CSIRT and ENISA via the single reporting platform. The Commission FAQ confirms this applies to products placed on the market **before** 11 December 2027. | **REPORTED** — cellar CRA Arts. 14, 71(2); FAQ §§5.3, 7.1, v1.4 04/09/2026 |
| Application dates | Art. 71(2) | "This Regulation shall apply from **11 December 2027**. However, Article 14 shall apply from **11 September 2026** and Chapter IV (Articles 35 to 51) shall apply from **11 June 2026**." | **REPORTED — verified verbatim** |
| Harmonised standards timetable | — | Three horizontal standards requested: risk-based design by 30 August 2026; **Annex I Part I product properties by 30 October 2027**; vulnerability handling by 30 August 2026. Twenty-six vertical (product-category) standards due 30 October 2026. | **REPORTED** — Commission FAQ §6.10, v1.4 04/09/2026 |

**Read the timetable against the classification.** If the product is Class I, Module A self-assessment needs a
harmonised standard, and the one covering Annex I Part I is due **30 October 2027** — six weeks before the Regulation
applies, and that is the ESO adoption date, before Commission assessment and publication of the reference in the
Official Journal. Planning to rely on it is planning on a date you do not control.

#### The free-and-open-source position under the CRA

| Point | Source | Grade |
|---|---|---|
| Only FOSS "made available on the market, and therefore supplied for distribution or use **in the course of a commercial activity**" is in scope | CRA recital 18 | **REPORTED** |
| **What counts as commercial** | CRA recital 15: "not only by charging a price… but also by charging a price for technical support services where this does not serve only the recuperation of actual costs, by **an intention to monetise**, for instance by providing a software platform through which the manufacturer monetises other services, by requiring as a condition for use the processing of personal data for reasons other than exclusively for improving the security, compatibility or interoperability of the software, or by **accepting donations exceeding the costs** associated with the design, development and provision. Accepting donations without the intention of making a profit should not be considered to be a commercial activity." | **REPORTED** |
| The mere facts that do **not** make it commercial | CRA recital 18: financial support from manufacturers, manufacturer contributions, and "the mere presence of regular releases" do not in themselves make it commercial. Contributors of source code to products not under their responsibility are out of scope entirely. | **REPORTED** |
| Hosting on a repository is not placing on the market | CRA recital 20 | **REPORTED** |
| **Open core is in scope** | Reasoning: recital 18's test is whether the product is "monetised by their manufacturers". A dual-licensed or open-core product is monetised by its manufacturer by construction. | **GUESSED** |
| **Steward obligations** | Art. 24(1): a documented, verifiable cybersecurity policy fostering secure development and effective vulnerability handling, and fostering voluntary reporting. Art. 24(2): cooperate with market surveillance authorities on request and supply that documentation. Art. 24(3): Art. 14(1) reporting applies to the extent the steward is involved in development; Art. 14(3) and (8) apply to severe incidents affecting the steward's own infrastructure. **Art. 24(3) applies from 11 December 2027** (FAQ §5.5). | **REPORTED** — cellar CRA Art. 24; FAQ §5.5 |
| **The FOSS escape hatch from a notified body** | Art. 32(5): manufacturers of products qualifying as free and open-source software that fall under Annex III categories "shall be able to demonstrate conformity… by using one of the procedures referred to in paragraph 1" — i.e. **Module A self-assessment** — "provided that the technical documentation referred to in Article 31 is **made available to the public** at the time of the placing on the market". | **REPORTED** — cellar CRA Art. 32(5); confirmed by FAQ §§6.1, 6.6 |

**This is a genuine strategic option and it is worth naming plainly:** if the governor is Class I or even Class II,
open-sourcing it under a real FOSS licence **and publishing the technical documentation** replaces a notified body
with self-assessment. That is a route around the single largest CRA cost. It requires a real FOSS licence — PolyForm
Noncommercial does not qualify (§1.8).

---

### 1.5 AI Act — Regulation (EU) 2024/1689

| Question | Answer | Grade + source |
|---|---|---|
| **Is a deterministic rule engine an AI system?** | **No.** Art. 3(1) requires a "machine-based system… that, for explicit or implicit objectives, **infers**, from the input it receives, how to generate outputs". The Commission Guidelines of 29 July 2025 say at §46 that "basic data processing" — "a system that follows predefined, explicit instructions or operations… developed and deployed to execute tasks based on manual inputs or rules, **without any 'learning, reasoning or modelling' at any stage**" — is outside the definition. §40 quotes recital 12: the definition "should not cover systems that are based on the rules defined solely by natural persons to automatically execute operations." | **REPORTED** — Commission Guidelines C(2025) 5053 final, 29.7.2025, §§26–27, 40–41, 46 (`_pdf_aidef.pdf`, 13 pp.); cellar AI Act Art. 3(1) |
| When would it become one? | The moment a learned model classifies action risk, scores agent behaviour, or infers a policy from examples. Keep the adjudicator deterministic and the AI Act stays out. | **GUESSED** — direct application of the guidelines |
| Would it be high-risk even if it were an AI system? | Two routes. Art. 6(1) needs the system to be a safety component of, or itself be, a product covered by **Annex I** Union harmonisation legislation requiring third-party conformity assessment — the CRA is not in AI Act Annex I. Art. 6(2) needs it to be in **Annex III** (biometrics, critical infrastructure, education, employment, essential services, law enforcement, migration, administration of justice). A consumer agent governor is in none of those areas. | **GUESSED** — Art. 6 text is REPORTED (cellar); the Annex I / Annex III negative is reasoned, not read entry by entry |
| **Art. 14 as a demand driver** | Art. 14(1): "High-risk AI systems shall be designed and developed in such a way, including with appropriate human-machine interface tools, that they can be **effectively overseen by natural persons** during the period in which they are in use." Art. 14(3): oversight measures built in by the provider, or "identified by the provider… and… appropriate to be implemented by the deployer". A governor is the deployer-side implementation of exactly that. | **REPORTED** — cellar AI Act, Art. 14 |
| **Timeline, and the Omnibus delay** | Art. 113: general application 2 August 2026; Chapters I–II from 2 February 2025; Chapter III §4, V, VII, XII and Art. 78 from 2 August 2025; Art. 6(1) from 2 August 2027. **Superseded in part:** the AI Omnibus was proposed 19 November 2025, politically agreed 7 May 2026, and **entered into force 27 July 2026**, moving Annex III high-risk to **2 December 2027** and Annex I product high-risk to **2 August 2028**. | **REPORTED** — Art. 113 from cellar AI Act; the Omnibus dates from digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai, page last updated 3 August 2026, fetched 2026-09-17 |
| Open-source AI exemption | Art. 2(12): "This Regulation does not apply to AI systems released under free and open-source licences, unless they are placed on the market or put into service as high-risk AI systems or as an AI system that falls under Article 5 or 50." | **REPORTED** — cellar AI Act, Art. 2(12) |

**Read commercially:** the AI Act gives the product a *story* and a *buyer* (compliance officers who must show Art. 14
oversight), and costs it nothing. But the Omnibus just pushed the forcing date out by about sixteen months. Any revenue
model that assumed enterprises buying in 2026 to meet an August-2026 deadline needs re-basing to late 2027.

---

### 1.6 GDPR — Regulation (EU) 2016/679

| Question | Answer | Grade + source |
|---|---|---|
| **For a local-only product, is the vendor a controller at all?** | Most likely **no**, for the user's local records. A controller is one who "determines the purposes and means of the processing" (Art. 4(7)) — but there must be *processing by that person*. A vendor that receives nothing processes nothing. **The counter-argument is real and must be put to counsel:** recital 18's second sentence says "this Regulation applies to controllers or processors which **provide the means for processing** personal data for such personal or household activities." Read broadly, shipping the software is providing the means. Read narrowly (and this is the better view), that sentence prevents a *service* provider from hiding behind its users' household exemption; it does not turn a shrink-wrap vendor who receives no data into a controller. | **GUESSED** — recital 18 text is **REPORTED** (cellar GDPR); the conclusion is reasoned. **Put this one question to counsel explicitly.** |
| Household exemption | Art. 2(2)(c): the Regulation does not apply to processing "by a natural person in the course of a **purely personal or household activity**". Recital 18 adds "and thus with no connection to a professional or commercial activity." | **REPORTED** — cellar GDPR, Art. 2(2)(c), recital 18 |
| When the **user** loses the household exemption | Reasoning: (a) any employer-owned or work machine — never household; (b) a freelancer's own machine used for client work — the record then has "a connection to a professional activity"; (c) a shared machine where the record describes another person's activity and is used for something other than domestic purposes. The Court of Justice read the exemption narrowly in *Ryneš* (C-212/13, CCTV covering public space). | **GUESSED** — *Ryneš* cited from knowledge, **not read in this study** |
| **Opt-in diagnostics make the vendor a controller** | Yes, the moment anything that can single out a person is transmitted — an install identifier, a machine identifier, a file path, an application name, an IP address in the request. Then: Art. 4(7) controller; Art. 5 principles (lawfulness, minimisation, storage limitation, integrity); Art. 6(1)(a) consent as the basis for opt-in telemetry; Art. 13 information at the point of collection; Art. 30 records; Art. 32 security. | **REPORTED** for the articles (cellar GDPR); **GUESSED** for the "identifier makes it personal data" application |
| Art. 30 records — the small-vendor exemption does **not** save you | Art. 30(5): the obligation "shall not apply to an enterprise or an organisation employing fewer than 250 persons **unless** the processing it carries out is likely to result in a risk…, **the processing is not occasional**, or the processing includes special categories…". Continuous product telemetry is not occasional. **Keep the record.** | **REPORTED** — cellar GDPR, Art. 30(5) |
| DPIA | Art. 35(1): required where processing "is likely to result in a high risk", in particular "using new technologies". Art. 35(3) lists the mandatory triggers (systematic evaluation by automated processing; large-scale special categories; large-scale systematic monitoring of a publicly accessible area). Coarse counts-and-versions diagnostics hit none of them. | **REPORTED** — cellar GDPR, Art. 35. **Do the threshold assessment and write down the "no" anyway** — an unrecorded "no" is indistinguishable from never having asked. |
| Art. 27 EU representative | Art. 27(1): required only "where Article 3(2) applies" — i.e. a controller **not established in the Union** targeting EU data subjects. Art. 27(2)(a) exempts occasional, low-risk processing. **A founder established in the EU does not need one.** It becomes necessary if he later incorporates outside the EU and keeps selling into the EU. | **REPORTED** — cellar GDPR, Art. 27; representative-service pricing **not verified** |
| **Art. 25 by design and by default** | Art. 25(2): "only personal data which are necessary for each specific purpose… That obligation applies to the amount of personal data collected, the extent of their processing, the period of their storage and their accessibility." Labels-and-hashes-not-content, local-by-default and telemetry-off-by-default are literal Art. 25(2) compliance — and the best marketing claim the product has, because it is checkable. | **REPORTED** — cellar GDPR, Art. 25 |
| **Records describing another person's use of a shared machine** | The design problem, not just a legal one. A receipt that names a file path or an application can reveal special-category data under Art. 9 — a path under `\Health\`, a dating or religious application name, a union document. Design rule: store a **hash** of the path and a **label drawn from a closed vocabulary**, never a free-text string, and never the content. This is simultaneously CRA Annex I Part I 2(g), GDPR Art. 25, and the thing that stops a receipt from being a disclosure. | **GUESSED** (application) — Arts. 9 and 25 are REPORTED |
| Employment context | Art. 88(1): Member States may set more specific rules for employee data "by law or by collective agreements", and Art. 88(2) requires those rules to include safeguards "with particular regard to… **monitoring systems at the work place**". | **REPORTED** — cellar GDPR, Art. 88 |

---

### 1.7 Trade mark, distribution, VAT, platform rules and export

| Item | Instrument / source | Trigger | Concretely | Cost | Grade |
|---|---|---|---|---|---|
| **EU trade mark fees** | Reg. (EU) 2017/1001, Annex I, points 1–4 and 11–14 | selling / any public name | Application: **€1,000 on paper, €850 by electronic means**, covering one class. **€50** for the second class. **€150** for each class beyond two. Renewal (every 10 years): the same figures. Opposition fee €320. | **€850** for a single class filed online | **REPORTED** — cellar EUTMR Annex I; OJ L 154, 16.6.2017 |
| Clearance search before filing | — | any public name | Free tools exist (TMview, eSearch plus). A professional EU clearance opinion is the thing that stops you spending €850 and a launch on a name you must abandon. | **€500–1,500 estimated, not verified** | **GUESSED** |
| Open-sourcing does not open-source the name | Reg. (EU) 2017/1001 | open-sourcing | The code licence says nothing about the mark. Register before publishing, or lose the ability to stop forks trading on the name. | €850 | **GUESSED** (application) |
| Microsoft Store — registration | Microsoft Partner Center | selling via Store | "With the new onboarding experience, there are no registration fees for either account type." Individual: government ID + selfie. Company: DUNS or business documents, 2–5 business days, work e-mail on the company's own domain. | **€0** | **REPORTED (R2-D)** — R2-D §2, R[1]–[4]; ms.date 2026-09-17 |
| Microsoft Store — revenue share and merchant of record | App Developer Agreement v8.11, §6(b) and §5(e) | selling via Store | Store Fee is 15% of Net Receipts for apps. §5(e): "Purchases made on a third-party commerce engine are not subject to the Store Fee." A free Store listing that sells licences on your own site pays **0%**. | 15% via Microsoft, 0% with your own checkout | **REPORTED (R2-D)** — R2-D §2, R[6], published 2026-03-17, effective 2026-04-17 |
| Who owes the VAT | — | selling | When Microsoft collects the money it handles the consumer VAT; with your own commerce engine **you** are the seller and you owe it. Merchant-of-record providers (Paddle, Lemon Squeezy, FastSpring) take that burden for roughly 5% plus payment fees. | 15% (Microsoft) vs ~5%+ (MoR) vs 0% + your own VAT compliance | **GUESSED** — the MoR characterisation and the ~5% figure are **not verified** |
| **Microsoft Store policy risk for a governor** | Store Policies v7.20, §10.2.4 | selling via Store | "Generally, dependency on non-Microsoft provided drivers or NT services is not allowed but may be considered case by case for WHCP certified drivers… you must disclose that dependency to Microsoft in the certification notes." A governor with a machine-wide Windows service is exactly this. | Disclose in certification notes; expect case-by-case review | **REPORTED (R2-D)** — R2-D §2, R[5], ms.date 2026-09-14. Whether a Windows service inside an MSIX package passes certification was **not verified**. |
| **VAT — the €10,000 threshold and the One Stop Shop** | Council Directive 2006/112/EC as amended; Commission One Stop Shop guidance | selling across the EU | Below **€10,000** of total cross-border business-to-consumer supplies of telecommunications, broadcasting and electronic services plus intra-EU distance sales of goods, "in the current and the preceding calendar year", the place of supply stays in your own Member State and you charge your own VAT rate. Above it, VAT is due where the customer is: either register in each Member State or file one quarterly return through the OSS Union scheme in your Member State of identification. The threshold requires establishment in only **one** Member State. You may opt in early and are then bound for two calendar years. | OSS registration is free; the compliance cost is the quarterly return | **REPORTED** — ec.europa.eu VAT e-Commerce One Stop Shop, "The One Stop Shop" page, captured 2026-09-17 |
| **DSA trader information** | Reg. (EU) 2022/2065 Art. 30(1) | selling via a platform | The duty falls on "providers of online platforms allowing consumers to conclude distance contracts with traders": before letting a trader offer products they must obtain the trader's name, address, telephone number and e-mail, payment account details, trade register identifier, and a self-certification to offer only compliant products. **Your duty is to supply it and keep it accurate.** Selling only from your own site puts you outside Art. 30 entirely — your own shop is not an online platform because it hosts no third-party traders. | €0, but keep the registered details current | **REPORTED** — cellar DSA, Art. 30(1); OJ L 277, 27.10.2022 |
| PLD reaches the platform too | Dir. (EU) 2024/2853 Art. 8(4) | selling via a platform | An online platform allowing consumers to conclude distance contracts can be liable as a distributor where DSA Art. 6(3) conditions are met and no EU-established operator can be identified. Platforms therefore have their own reason to demand your details. | — | **REPORTED** — cellar PLD, Art. 8(4) |
| **Export control — cryptography** | Reg. (EU) 2021/821 Annex I, Category 5 Part 2; General Software Note; Note 3 (Cryptography Note) | selling / free / open-sourcing / outside EU | A governor that encrypts its record at rest and signs it uses cryptography and may fall in 5D002. Three releases: **(1) General Software Note entry (b), "in the public domain"** — and, critically, only GSN entries (a) and (c) are switched off for Category 5 Part 2; **entry (b) still applies**, so genuinely open published source is released. **(2) The Cryptography Note (Note 3)** — mass-market: generally available to the public by being sold without restriction from stock at retail selling points including electronic transactions; the cryptographic functionality cannot easily be changed by the user; designed for installation by the user without further substantial support; details supplied to the authority on request. The Note to the Cryptography Note adds: of potential interest to a wide range of individuals and businesses, and the price and main functionality available before purchase. **(3)** 5D002 note: software "integral to an operating system that is not specified in 5D002" — using Windows' own DPAPI/CNG rather than bundling a crypto library helps. | A one-page self-classification memo, kept on file. A national dual-use authority will give a binding classification opinion if you want certainty. | **REPORTED** — cellar Reg. (EU) 2021/821 Annex I, GSN and Note 3; Wassenaar WA-LIST (23) 1, 01-12-2023, pp. 93–94 for the identical wording and the definition |
| "In the public domain" definition | Wassenaar list, definitions section | open-sourcing | "'technology' or 'software' which has been made available **without restrictions upon its further dissemination**. Note: Copyright restrictions do not remove 'technology' or 'software' from being 'in the public domain'." | — | **REPORTED** for the Wassenaar wording; the identical EU definition was **not located** in the converted EU Annex I text and should be confirmed |
| A noncommercial licence may forfeit the public-domain release | reasoning on the definition above | open-sourcing under PolyForm | A licence that forbids commercial redistribution arguably *is* a restriction on further dissemination — distinct from a copyright restriction, which the Note expressly forgives. Do not rely on GSN(b) for PolyForm-licensed code. Rely on the mass-market Cryptography Note instead. | — | **GUESSED** |

---

### 1.8 Digital Markets Act — could a governor demand access to Microsoft's authorisation hooks?

**Question as put:** Microsoft is a gatekeeper for Windows; could a governor invoke the interoperability obligation to
demand access to the Windows Model Context Protocol proxy's authorisation hooks?

**The facts, REPORTED:**
- Microsoft Corporation is a designated gatekeeper. **Windows PC OS is a designated core platform service**, case
  **DMA.100026**, designated **6 September 2023**. Source: digital-markets-act.ec.europa.eu/gatekeepers_en, fetched
  2026-09-17.
- Regulation (EU) 2022/1925 Art. 6(7), first subparagraph: "The gatekeeper shall allow providers of services and
  providers of hardware, **free of charge, effective interoperability with, and access for the purposes of
  interoperability to, the same hardware and software features accessed or controlled via the operating system**…
  as are available to services or hardware provided by the gatekeeper. Furthermore, the gatekeeper shall allow
  business users and alternative providers of services provided together with, or in support of, core platform
  services, free of charge, effective interoperability with… the same operating system, hardware or software
  features, regardless of whether those features are part of the operating system, as are available to, or used by,
  that gatekeeper when providing such services." Source: cellar DMA, Art. 6(7); OJ L 265, 12.10.2022.
- Art. 6(7), second subparagraph: "The gatekeeper shall not be prevented from taking **strictly necessary and
  proportionate measures** to ensure that interoperability does not compromise the integrity of the operating system…
  provided that such measures are duly justified by the gatekeeper."

**The answer, GUESSED, with the reasoning shown:**

*In principle, yes.* If Microsoft's own agent-governance or security surface consumes a policy-decision-point hook in
the Windows agent stack that third parties cannot reach, that is the paradigm Art. 6(7) case: the same software
feature, controlled via the operating system, available to the gatekeeper's service and not to a rival's. The
first subparagraph does not require the feature to be part of a *designated* service — it says "accessed or
controlled via the operating system", and the second sentence says "regardless of whether those features are part
of the operating system".

*In practice, four things blunt it.*

1. **The integrity carve-out is the strongest defence Microsoft has, and this is the strongest place to run it.** A
   third-party policy decision point sitting in the authorisation path of every agent action is, from a platform
   engineer's view, exactly the kind of hook that can brick a machine. Microsoft has recently been arguing this line
   generally about kernel-adjacent access. Expect "strictly necessary and proportionate" to be contested for years,
   not settled in a memo.
2. **Standing.** Art. 6(7) runs to "providers of services", "providers of hardware" and "business users". A commercial
   desktop-software vendor qualifies. A non-commercial open-source project's standing is much weaker — another reason
   the commercial path and the interoperability lever go together.
3. **There is no fast private remedy.** The DMA is enforced by the Commission. A third party complains, the Commission
   may open a specification proceeding under Art. 8(2), and that takes many months to over a year. National courts can
   apply the DMA, but a one-person company litigating against Microsoft is not a plan.
4. **It may never be needed.** If Microsoft publishes the agent authorisation hooks as ordinary public API — which is
   the announced direction — Art. 6(7) is moot.

**The one action that costs nothing and preserves the option:** keep a dated, contemporaneous engineering record of
every hook, interface or privilege that Microsoft's own agent-governance surface uses and that the public API does not
expose, with the evidence (binary analysis, ETW traces, documentation gaps) attached. That record is precisely what a
Commission complaint would need, it is cheap to maintain while building, and it is impossible to reconstruct later.
Treat the DMA as a **negotiating and public-argument fact**, not as a route to shipping.

---

### 1.9 BlarAI's licence and what a clean extraction needs

**What is on disk, read read-only on 2026-09-17:**

- `C:/Users/mrbla/BlarAI/LICENSE.md` — "Required Notice: Copyright (c) 2026 Blair DuCray-Oppat
  (mr.blair.do@gmail.com)"; "Commercial use requires a separate license — see COMMERCIAL-LICENSE.md"; then the full
  text of **PolyForm Noncommercial License 1.0.0**. Permitted purposes are noncommercial only: personal study, hobby,
  research, charities, educational institutions, public research and government bodies.
- `C:/Users/mrbla/BlarAI/COMMERCIAL-LICENSE.md` — a dual-licensing statement: any commercial use requires a paid
  licence from the copyright holder; "Copyright (c) 2026 Blair DuCray-Oppat. All rights not expressly granted under
  the PolyForm Noncommercial License 1.0.0 are reserved."
- `git shortlog -sne main` on the repository: **Blair <mr.blair.do@gmail.com> 3829**, blarai <blarai@local> 5,
  claude <claude@local> 3, Blair <blair@local> 2.

**A clean extraction needs six things:**

1. **A written statement of sole authorship**, kept with the extracted repository, confirming that the three
   secondary git identities (`blarai@local`, `claude@local`, `blair@local`) are his own machine identities and that
   no third party contributed code. Grade **GUESSED** on the legal need — but it costs one file and removes the only
   question a due-diligence reviewer or acquirer will ask first.
2. **File-by-file copying, never tree copying.** The BlarAI working directory contains an `openvino/` checkout of
   Intel's OpenVINO (Apache-2.0, with its own `thirdparty/` tree) and dozens of third-party research PDFs. None of
   that may travel into a product repository.
3. **A third-party dependency audit and a NOTICES file.** The runtime virtual environment's packages carry their own
   licences. A commercial product needs the notices, and needs to know whether any GPL or AGPL component is in the
   graph. **Not audited in this study.**
4. **Nothing needs to change about BlarAI's own licence.** He holds the copyright, so he may licence the extracted
   code under any terms he chooses — including a proprietary end-user licence — without amending LICENSE.md. A
   copyright holder is not bound by the licence he grants to others.
5. **PolyForm Noncommercial is not a free-and-open-source licence for regulatory purposes.** CRA Art. 3, definition
   48: "'free and open-source software' means software the source code of which is openly shared and which is made
   available under a free and open-source licence **which provides for all rights to make it freely accessible,
   usable, modifiable and redistributable**." PolyForm withholds commercial use, so it does not provide all those
   rights. The PLD's recital 14 description is the same shape. **Consequence: publishing the governor under PolyForm
   gets none of the CRA scope exclusion, none of the PLD Art. 2(2) exemption, and none of the Art. 32(5)
   self-assessment route — while still giving away the source.** Worst of both. Grade **GUESSED** on the legal
   conclusion; the definition quoted is **REPORTED** from the cellar CRA text.
6. **Pick the licence for the outcome wanted.** If the goal is the CRA/PLD exclusions and the Art. 32(5) escape from
   a notified body, use Apache-2.0 (patent grant, permissive) or GPL-3.0 (copyleft, keeps forks open). If the goal is
   source-available marketing without giving competitors a free product, keep PolyForm — and accept the full
   manufacturer burden.

---

## 2. Q13 — privacy of the record, and shared machines

### 2.1 Data map

| What is stored | Contents | Where | Retention default | Who can read it | Encryption at rest | On uninstall | Export |
|---|---|---|---|---|---|---|---|
| **Profile** | The chosen plain-language profile, per-agent overrides, the action vocabulary version | Per user: `%LOCALAPPDATA%\<product>\profile.json`. Machine floor (if used): `%PROGRAMDATA%\<product>\floor.json`, ACL write-restricted to Administrators | Until changed | The user; any process running as that user; local administrators | Not secret — but must be **integrity-protected** (signed), because a silently edited profile is a silent policy downgrade | Removed with the user's data, on the prompt below | Plain, human-readable, copy-pasteable |
| **Receipts** (the signed record) | One entry per agent decision: timestamp, agent identity, action verb from the closed vocabulary, **target label** from a closed vocabulary, **target hash**, decision (allow/deny/observe), the policy rule that fired, the seam used, and a hash chain link to the previous entry. **No file contents, no free-text paths, no prompt text.** | Per user, under `%LOCALAPPDATA%` | **90 days rolling**, user-settable 7 days to forever | The user; processes running as that user; local administrators | DPAPI (CurrentUser scope) for confidentiality, **plus** a hash chain with periodic checkpoints signed by a TPM-sealed key for integrity | **Prompt: delete or keep. Default: delete.** | Signed bundle: JSONL receipts + manifest (chain root, public key, product version) + an HTML render |
| **Coverage state** | Which agents are present, which are governed, which are only observed, which are unknown; the inventory of reachable surfaces | Per user; the machine-wide part under `%PROGRAMDATA%` | Current state only, no history | Same as receipts | Integrity-protected; confidentiality matters less | Deleted | Included in the bundle |
| **Opt-in diagnostics** | Counts, product and OS versions, error fingerprints, seam-availability booleans. **Off by default.** Never agent names, never targets, never hashes of user paths. | Local send queue only; nothing retained after acknowledgement | Queue only, ≤7 days | The user (with a preview), the vendor after send | TLS in transit; the local queue under DPAPI | Deleted | Shown to the user before the first send |
| **Record signing key** | The key that signs checkpoints | TPM-sealed, non-exportable | Life of the install | Nobody, by construction | TPM 2.0 sealing | Destroyed | Public half only |

### 2.2 Honest limits of encryption on Windows

State these in the product, not only in a design document — a security product that overstates its own protection is
the worst kind.

- **DPAPI CurrentUser protects against other local users and against an offline disk.** It does **not** protect
  against code running as that user — DPAPI unprotects transparently for any process in that user's session. An agent
  running with the user's rights can read the record.
- **A local administrator can read everything**, by taking ownership if necessary. There is no design that prevents it.
- **TPM sealing raises the cost of offline and different-OS attacks** and makes the signing key non-exportable. It
  does not stop a live attacker with the user's rights from *asking* the TPM to sign.
- **Therefore the property to engineer for is tamper-evidence, not secrecy.** A hash chain with TPM-signed checkpoints
  means an attacker who deletes or edits entries leaves a visible gap. That is achievable. Confidentiality against a
  same-user attacker is not, and should not be claimed.

### 2.3 The multi-user design decision

**(a) Per-user profiles and per-user records, with a machine-wide service**

| Setting | How it lands |
|---|---|
| Family PC | Each family member gets their own profile and their own record. A parent cannot read a teenager's record from inside the product. The service enforces for everyone, so the protection is real for all accounts. The gap: a parent who wants oversight of a child's machine has no supported path. |
| Shared PC (several people, one Windows account) | **Fails.** Profiles are keyed to the Windows account. If everyone shares one login, the record mixes people with no attribution and no separation. |
| Employer-owned PC | The best shape available. The service is machine-wide so IT can deploy and set a floor; the record stays per-user, which is the data-minimising arrangement. Still monitoring software — see the co-determination note below. |
| Security | The service is the trusted computing base. It must run as a protected or SYSTEM service with a tight ACL and a signed binary, or a user-level agent simply stops it. |

**(b) One machine-wide profile and one machine-wide record**

| Setting | How it lands |
|---|---|
| Family PC | Simple and matches what a non-technical owner expects: "this machine is governed this way." But the record then shows what every account did, readable by anyone who can read the file, and the profile is whatever the installer chose. |
| Shared PC | Attribution only works if each receipt names the Windows account — which is exactly the privacy problem, written into the data model. |
| Employer PC | The shape that most clearly *is* employee monitoring. Co-determination and consultation duties are at their strongest, and a works council can block deployment outright. |
| Security | Simplest to protect: one file, one ACL, one service. |

**(c) Per-user only, no machine-wide service**

| Setting | How it lands |
|---|---|
| Family PC | Each person protects themselves; nobody is protected from anyone else's agents; an agent under account A still reaches shared folders. |
| Shared PC | Identical to a single-user product, which is fine for one household account. |
| Employer PC | Least legal friction — no central visibility, so the monitoring characterisation is weak. Also no enterprise value: IT cannot verify that anything is covered. |
| Security | **The fundamental weakness.** The governor runs at the same privilege as the agents it governs. An agent with the user's rights can terminate it. "Enforce" degrades to "advise". |

**Employment-law overlay (applies to (a) and especially (b)):**

- **Germany:** Betriebsverfassungsgesetz (Works Constitution Act) **§87(1) no. 6** gives the works council a
  co-determination right over "the introduction and use of technical devices designed to monitor the behaviour or
  performance of the employees". German courts read "designed to" as *objectively suited to*, regardless of the
  employer's intent. A governor that logs per-employee agent actions is squarely within it: **without a works
  agreement, deployment can be enjoined.** Grade **GUESSED** — the provision number is stated from knowledge and was
  **not read** in this study; have German counsel confirm against the current BetrVG.
- **France:** Code du travail **L.2312-38** requires the employer to inform and consult the Comité social et
  économique before introducing means or techniques allowing monitoring of employees' activity; **L.1222-4** provides
  that no information concerning an employee personally may be collected by a device not previously brought to their
  knowledge. Grade **GUESSED** — provision numbers stated from knowledge, **not read** in this study.
- **GDPR Art. 88** is the hook that lets both of these sit alongside the Regulation, and Art. 88(2) singles out
  "monitoring systems at the work place" for safeguards. **REPORTED** (cellar GDPR).

### 2.4 Recommendation

**[PROPOSED] Default to (a): per-user profiles and per-user records, a machine-wide enforcement service, and a
machine-wide floor that an administrator can set — where a user's own profile may only be *stricter* than the floor,
never looser.**

**The trade-off in plain language.** The machine-wide service is what makes the word "enforce" mean anything. Without
it the product runs with exactly the same rights as the agents it is supposed to stop, and any of them can switch it
off; the product becomes advice with a nice interface. Keeping each person's profile and record inside their own
Windows account is what stops the product becoming spyware: nobody — not even the person who installed it — can read
another account's record from inside the product. The price is that the family member who bought the machine cannot
see what everyone else's agents did. **That is the right price, and it should be printed on the box rather than
discovered.** The floor is what makes the workplace case work without building a second product: the organisation
sets "no agent may move money, ever", and each person can add their own restrictions on top but cannot remove that one.

The shared-single-account case (one Windows login for a whole household) is the one this design does not serve. The
honest answer is to say so in the product and recommend separate Windows accounts, rather than to invent per-person
attribution inside a shared account, which cannot be done reliably and would be a privacy hazard if attempted.

### 2.5 Consent posture

1. **The local record needs no separate consent screen** — it is the product. It needs a **first-run disclosure**, one
   screen: what is recorded (labels and hashes, never content), where it lives, how long it is kept, who can read it,
   how to export it, how to delete it. Then a link to that same screen from the main window forever.
2. **A machine-wide floor must never be silent.** Whoever sets it is told, in the product, that every other user will
   see that a floor exists and what it contains; every other user sees it on their own screen. A floor that users
   cannot see is the definition of covert monitoring, and it is what both the German and the French rules are aimed at.
3. **On a managed or domain-joined machine, refuse to run in any mode where the person using the machine cannot read
   their own record.** This single design decision removes most of the works-council and consultation risk, because
   what those regimes object to is covert and unilateral behavioural monitoring — not a control the worker can inspect.
   It costs nothing in the consumer case and is a selling point in the enterprise case.
4. **Opt-in diagnostics: separate, explicit, off by default, withdrawable in one click.** Consent under GDPR
   Art. 4(11) must be freely given, specific, informed and unambiguous, and Art. 7(3) requires withdrawal to be as
   easy as giving it. Concretely: the product must work identically with diagnostics off (otherwise consent is not
   free); the consent must not be bundled into licence acceptance (bundled consent is not free); and the product
   should **show the exact payload** before the first send. A preview of what leaves the machine is the most
   convincing privacy claim a local-first product can make, because it is verifiable by the user.
5. **Never make diagnostics a condition of any feature**, ever. Beyond the consent point, it is what would drag a free
   build into the Digital Content Directive (Art. 3(1), personal data as counter-performance) and into CRA commercial
   activity (recital 15).

---

## 3. Three checklists, with costs

### 3.1 Before the first paid sale in the EU

| # | Step | Cost | Why |
|---|---|---|---|
| 1 | **Form a company.** Estonia OÜ via e-Residency: €150 + €265 + €200–400/yr address and contact person. Netherlands BV: €500–1,500 notary + €600–1,800/yr bookkeeping + KVK fee. Ireland LTD: CRO filings, €20/yr annual return, plus an EEA-resident director or a Section 137 bond. | **€400–2,000 setup, €800–2,500/yr** | Five independent reasons: signing eligibility, OV certificates, Store company account, the PLD liability shield, steward eligibility |
| 2 | **Code signing.** Azure Artifact Signing Basic (organisations only) or an OV certificate. | **€8.58/month** or **€109–199/yr** | Unsigned installers are stopped by SmartScreen; reputation takes weeks to accrue |
| 3 | **Consumer contract pack.** Pre-contractual information (CRD Art. 6(1)); two unticked boxes on the checkout for CRD Art. 16(m) express consent and acknowledgment of losing the withdrawal right, timestamped and logged; terms that do not purport to exclude DCD conformity (Art. 22) or PLD liability (Art. 15); a stated support period with a month and year (CRA Art. 13(19)). | **Counsel, 1–3 hours** | Without the Art. 16(m) boxes, every sale carries a 14-day no-reason refund |
| 4 | **VAT.** Register for the One Stop Shop Union scheme in your Member State before crossing **€10,000** of cross-border B2C supplies, or use a merchant-of-record provider. | OSS registration free; MoR ~5% | Below €10,000 you charge your home rate; above it, the customer's |
| 5 | **Privacy.** Privacy notice for the opt-in diagnostics (GDPR Art. 13); Art. 30 record (the under-250-persons exemption does not cover regular telemetry); a written DPIA threshold assessment, even if the answer is no. | **€0–500** | An unrecorded "no DPIA needed" is indistinguishable from never asking |
| 6 | **CRA classification — decide it and write down the reasons.** Then either (i) default category / Class I with a harmonised standard → Module A self-assessment, or (ii) Class I without a standard, or Class II → notified body under module B+C or H, or (iii) publish as genuine FOSS with public technical documentation and use Art. 32(5) to keep Module A. | Self-assessment: your time. Notified body: **four figures upward, not verified** | The single largest cost fork in the product |
| 7 | **Build the CRA deliverables in from day one.** SBOM (machine-readable, top-level dependencies); coordinated vulnerability disclosure policy plus a published contact; secure-by-default profile; signed automatic updates with an opt-out; a **five-year** support commitment; Annex II user information; Annex VII technical documentation; Annex V EU declaration of conformity; CE marking ≥5 mm. Stand up the Art. 14 reporting capability (24-hour early warning, 72-hour notification) — **live from 11 September 2026**. | Engineering time; €0 in fees | Retrofitting any of this after the architecture is frozen costs multiples |
| 8 | **Product liability insurance — get quotes before you set the price.** PLD Art. 7(2)(i) makes a governor's failure to prevent damage the definition of its defect, and Art. 15 means no term can cap it. | **Not verified** — quote it | This is the line item most likely to change the business model |
| 9 | **Trade mark.** Clearance search first, then file. One class, filed online. | **€850** + search | Filing before searching risks losing both the €850 and the launch |
| 10 | **Export.** A one-page self-classification memo against the Cryptography Note (Note 3, Category 5 Part 2), kept on file. | **€0** | Cheap now; awkward to reconstruct under a customs query |
| 11 | **If using the Microsoft Store:** company account, and disclose the Windows service dependency in the certification notes under policy §10.2.4. | €0, 15% of Store sales | A governor with a machine-wide service is a case-by-case certification review |

### 3.2 Before the first free public download in the EU

| # | Step | Cost | Why |
|---|---|---|---|
| 1 | **Decide, in writing, whether this is a commercial activity — and then live by the answer.** CRA recital 15 triggers: any price, paid support above cost, an intention to monetise, personal-data processing as a condition of use, donations above cost. If a paid tier exists or is planned, the free build is commercial and **the full CRA and PLD apply to it**. | €0 | This one decision determines whether steps 2–6 are needed at all |
| 2 | If non-commercial: **use a genuine free-and-open-source licence** (Apache-2.0, MIT, GPL). PolyForm Noncommercial does **not** qualify under CRA Art. 3(48) or PLD recital 14 and buys no exclusion. | €0 | Publishing under a non-qualifying licence gives the source away and keeps the duties |
| 3 | **Code signing still matters**, commercial or not. An individual-validated certificate is available to individuals (~$129/yr); Azure Artifact Signing is not (EU organisations only). | **~€120/yr** | SmartScreen does not care whether you charge money |
| 4 | **Publish the CVD policy and a security contact before the first download**, not after the first report. | €0 | Required by CRA Annex I Part II points 5–6 if in scope, and the right thing regardless |
| 5 | **State a support period and an end date** even if not legally required. | €0 | Sets the DCD Art. 8(2)(b) "reasonably expect" benchmark in your favour, and it is honest |
| 6 | **Not applicable to a genuinely free, non-commercial, no-data build:** DCD (no price, no personal data as counter-performance), CRD (no consumer contract for payment), VAT, DSA trader duties. **Still applicable:** GDPR, but only if you actually receive data — so keep diagnostics off by default and opt-in. | €0 | — |
| 7 | **Write down the date and the reasoning.** The moment a paid tier appears, both the CRA and the PLD attach retroactively to the supply activity, not to the licence. | €0 | The record of when the activity became commercial is the record a regulator will ask for |

### 3.3 Before open-sourcing

| # | Step | Cost | Why |
|---|---|---|---|
| 1 | **Choose the licence for the regulatory outcome, not the aesthetics.** Apache-2.0 or GPL gives the CRA scope exclusion (if non-commercial), the PLD Art. 2(2) exemption (if non-commercial), and — even if commercial — the **Art. 32(5) route to Module A self-assessment for an Annex III product, provided the technical documentation is published**. PolyForm gives none of these. | €0 | Potentially replaces a notified body with self-assessment |
| 2 | **Confirm sole authorship in writing** and check the git identities (`blarai@local`, `claude@local`, `blair@local` alongside 3,829 commits as Blair). | €0 | The first question any acquirer or contributor asks |
| 3 | **Copy named files, never the tree.** The BlarAI working directory contains an `openvino/` checkout (Apache-2.0, with its own third-party tree) and third-party research PDFs. | €0 | A single stray file can poison a licence claim |
| 4 | **Audit dependency licences and ship a NOTICES file.** Check for GPL/AGPL in the graph before choosing a permissive licence. **Not audited in this study.** | Engineering time | Copyleft in a dependency changes what you can licence the whole under |
| 5 | **Decide who stewards it.** CRA Art. 3(14) requires a **legal person** to be an open-source software steward — an individual cannot be one. If a foundation or company takes the role, Art. 24(1)–(2) duties attach, with Art. 24(3) reporting from 11 December 2027. | Formation cost if a new entity is needed | Non-obvious, and it constrains the governance model |
| 6 | **If an open core will coexist with a paid edition, assume both are in CRA and PLD scope.** | — | Recital 18's test is monetisation by the manufacturer |
| 7 | **Export:** publishing without restriction on further dissemination gives the General Software Note entry (b) release, which — unlike entries (a) and (c) — is **not** switched off for Category 5 Part 2. A noncommercial restriction may forfeit it. | €0 | One paragraph in the self-classification memo |
| 8 | **Register the trade mark before publishing.** €850, one class, online. Open-sourcing the code does not open-source the name, but publishing first makes the name much harder to control. | **€850** | Cheapest irreversible mistake to avoid |

---

## 4. Not verified

Everything here is a real gap, named so it can be closed cheaply.

**Blocked sources.** `eur-lex.europa.eu` returned an AWS WAF challenge (HTTP 202, empty body) on every attempt, direct
and via WebFetch. `cro.ie` returned HTTP 403 to every automated request, direct and via WebFetch, on four URLs.
`euipo.europa.eu` fee URLs resolved to a 404 page. `learn.e-resident.gov.ee` returned 403. Primary EU texts were
obtained instead from the Publications Office cellar repository, which worked for every instrument except
Directive 93/13/EEC and Directive 2000/31/EC, for which the CELEX resolver returned no English manifestation.

**Not read in this study (instrument named, text not fetched):**
- Directive 93/13/EEC on unfair terms — Art. 3(1), Art. 6(1) and the Annex indicative list. Everything in §1.2 about
  unfair terms is **GUESSED**.
- Directive 2000/31/EC on electronic commerce, Art. 5 information duties for information-society services.
- Directive (EU) 2019/2161 (the Modernisation Directive) amendments to CRD Art. 16(m). **The consolidated Art. 16(m)
  adds a third condition and must be read before drafting the checkout.**
- Case C-212/13 *Ryneš* on the narrow reading of the household exemption.
- German Betriebsverfassungsgesetz §87(1) no. 6; French Code du travail L.2312-38 and L.1222-4. **Provision numbers
  stated from knowledge.**
- The AI Act's Annex I and Annex III entry-by-entry. The conclusion "a governor is in neither" is reasoned, not
  checked line by line.
- Estonian Commercial Code (Äriseadustik) §136 on minimum share capital, and the current Estonian distribution tax
  rate.
- The EU Annex I definition of "in the public domain" — the Wassenaar wording is cited instead.

**Figures not obtained:**
- Irish CRO Form A1 incorporation fee (electronic and paper); late filing penalties; the cost of a Section 137 bond.
- The Netherlands KVK Business Register registration fee amount.
- Estonian accounting costs and the e-Residency card validity period.
- The cost of a CRA notified body conformity assessment for a small software product. **This is the biggest unknown
  in the whole file and it should be quoted before any architecture is frozen.**
- Product liability insurance premiums for a one-person EU software vendor.
- GDPR Art. 27 representative-service pricing (only relevant if he later establishes outside the EU).
- Professional trade mark clearance search pricing.
- Merchant-of-record provider fee percentages (Paddle, Lemon Squeezy, FastSpring).
- Certum's open-source code signing certificate price (R2-D also failed to obtain it).

**Questions only counsel or an authority can settle:**
1. **The CRA classification.** Annex III Class I entry 1 versus the default category. This is the money question.
2. Whether a *machine-wide* enforcement service that blocks agent network egress tips the product into Class II
   "firewall" territory.
3. Whether the vendor of a purely local product is a GDPR controller at all, given recital 18's "provide the means"
   sentence.
4. Whether a free build supplied alongside a paid build loses the PLD Art. 2(2) and CRA commercial-activity
   exclusions — the reasoning here says yes, but it is a reasoning, not a ruling.
5. Whether PolyForm Noncommercial forfeits the export-control "in the public domain" release.

**Not attempted, by instruction:** nothing was posted, filed, purchased, registered or sent. No account was created.
No authority, registry, foundation or company was contacted. Names were not proposed.

---

## 5. Sources

Fetched or read on **2026-09-17** unless a different date is given. Cellar URLs are the EU Publications Office's
Official Journal originals.

**EU primary law (Publications Office cellar, Official Journal XML/XHTML):**
1. **Regulation (EU) 2024/2847** (Cyber Resilience Act) — OJ L, 2024/2847, 20.11.2024.
   `http://publications.europa.eu/resource/cellar/21b7d4eb-a6e2-11ef-85f0-01aa75ed71a1.0006.02/DOC_1` (Formex package;
   Annexes I, II, III, IV, V, VI, VII, VIII in separate files). Articles read: 2, 3, 13, 14, 18, 24, 25, 26, 32, 71;
   recitals 15, 18, 20, 44, 45, 91; Annexes I, III, IV. (Recital numbers verified against the Formex CONSID elements.)
2. **Commission Implementing Regulation (EU) 2025/2392** of 28 November 2025 on the technical description of the
   categories of important and critical products with digital elements — C/2025/8052, OJ L, 2025/2392, 1.12.2025.
   `http://publications.europa.eu/resource/cellar/2d4a6388-ce5f-11f0-8da2-01aa75ed71a1.0006.03/DOC_1`. Recital 5 and
   the Annex descriptions for identity/privileged access management, antimalware, SIEM, firewalls/IDS/IPS.
3. **Directive (EU) 2024/2853** (Product Liability) — OJ L, 2024/2853, 18.11.2024.
   `http://publications.europa.eu/resource/cellar/10bdc8d8-a54e-11ef-85f0-01aa75ed71a1.0006.03/DOC_1`. Articles 2, 4,
   6, 7, 8, 9, 11, 12, 14, 15, 16, 17, 21, 22; recitals 14, 15.
4. **Regulation (EU) 2024/1689** (AI Act) — OJ L, 2024/1689, 12.7.2024.
   `http://publications.europa.eu/resource/cellar/dc8116a1-3fe6-11ef-865a-01aa75ed71a1.0006.03/DOC_1`. Articles 2(12),
   3(1), 6, 14, 25(4), 113.
5. **Directive (EU) 2019/770** (Digital Content) — OJ L 136, 22.5.2019.
   `http://publications.europa.eu/resource/cellar/c426ed23-7c64-11e9-9f05-01aa75ed71a1.0006.03/DOC_1`. Articles 3, 7,
   8, 11, 12, 22.
6. **Directive 2011/83/EU** (Consumer Rights), **original 2011 text** — OJ L 304, 22.11.2011.
   `http://publications.europa.eu/resource/cellar/6c8e7593-7a75-4b58-b709-542f06ee7a28.0018.03/DOC_1`. Articles 6, 9,
   16(m), 17.
7. **Regulation (EU) 2016/679** (GDPR) — OJ L 119, 4.5.2016.
   `http://publications.europa.eu/resource/cellar/3e485e15-11bd-11e6-ba9a-01aa75ed71a1.0006.03/DOC_1`. Articles 2(2)(c),
   3, 4(7), 25, 27, 30(5), 35, 88; recital 18.
8. **Regulation (EU) 2022/2065** (Digital Services Act) — OJ L 277, 27.10.2022.
   `http://publications.europa.eu/resource/cellar/3ff67256-55c4-11ed-92ed-01aa75ed71a1.0006.03/DOC_1`. Article 30.
9. **Regulation (EU) 2022/1925** (Digital Markets Act) — OJ L 265, 12.10.2022.
   `http://publications.europa.eu/resource/cellar/b4326c28-49cd-11ed-92ed-01aa75ed71a1.0006.03/DOC_1`. Article 6(7).
10. **Regulation (EU) 2021/821** (dual-use) — OJ L 206, 11.6.2021.
    `http://publications.europa.eu/resource/cellar/d8e79ebf-ca4e-11eb-84ce-01aa75ed71a1.0006.03/DOC_1`. Annex I General
    Software Note, General Information Security Note, Category 5 Part 2 Note 3 (Cryptography Note), 5D002.
11. **Regulation (EU) 2017/1001** (EU trade mark) — OJ L 154, 16.6.2017.
    `http://publications.europa.eu/resource/cellar/...` via `oj/JOL_2017_154_R_0001.ENG.xhtml`. Annex I, points 1–4,
    10–18; Article 53(3).
12. **Directive (EU) 2019/882** (European Accessibility Act) — OJ L 151, 7.6.2019, p. 70.
    via `oj/JOL_2019_151_R_0003.ENG.xhtml`. Articles 2(1), 2(2), 3 (microenterprise definition), 4(5).

**Commission guidance:**
13. **Commission FAQ on the Cyber Resilience Act**, version 1.4 of **04/09/2026** (revision history: 1.2 16/01/2026,
    1.3 01/07/2026, 1.4 04/09/2026). Sections 1.1–1.4, 2.3, 3.1–3.4, 4.2.4, 4.4.4, 4.5.1–4.5.2, 5.3–5.5, 6.1–6.10,
    7.1–7.3. Local copy `_cra_faq.txt` (downloaded by a predecessor agent, 2026-09-17).
14. **Commission Guidelines on the definition of an artificial intelligence system established by Regulation
    (EU) 2024/1689**, C(2025) 5053 final, Brussels, **29.7.2025**, 13 pp. Paragraphs 26–27, 40–41, 42–48. Local copy
    `_pdf_aidef.pdf`.
15. **Regulatory framework for AI**, digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai —
    **page last updated 3 August 2026**, fetched 2026-09-17. AI Omnibus: proposed 19 November 2025, agreed
    7 May 2026, **in force 27 July 2026**; Annex III high-risk to 2 December 2027; Annex I to 2 August 2028.
16. **VAT e-Commerce — One Stop Shop**, "The One Stop Shop", ec.europa.eu (DG TAXUD), captured 2026-09-17. The
    EUR 10,000 threshold and its three conditions.
17. **DMA designated gatekeepers**, digital-markets-act.ec.europa.eu/gatekeepers_en, fetched 2026-09-17. Microsoft
    Corporation; Windows PC OS, case DMA.100026; designated 6 September 2023.

**Other primary:**
18. **Wassenaar Arrangement, List of Dual-Use Goods and Technologies**, WA-LIST (23) 1, **01-12-2023**. General Software
    Note (p. 3), Category 5 Part 2 Note 2 and Note 3 with the Note to the Cryptography Note (pp. 93–94), and the
    definition of "in the public domain". Local copy `_wassenaar.txt`.
19. **Directive (EU) 2024/2853 negotiating text** PE-CONS 7/24, Brussels, 25 September 2024 — used to read Articles 8,
    11, 16, 17 and 21 in a cleaner layout. Local copy `_pld.txt` / `_pld_pecons.pdf`.

**Company formation and commerce:**
20. **e-resident.gov.ee/become-an-e-resident/** — e-Residency application state fee **€150**. Fetched 2026-09-17.
21. **e-resident.gov.ee/start-a-company/** — company registration **€265**; legal address and contact person
    **€200–400/year**. Fetched 2026-09-17.
22. **business.gov.nl/starting-your-business/choosing-a-business-structure/private-limited-company-bv/** — civil-law
    notary **€500–1,500**; bookkeeping **€600–1,800/year**; minimum starting capital **€0.01**; KOR small-business
    scheme up to €20,000. Fetched 2026-09-17.
23. **cro.ie/annual-return/filing-an-annual-return/** — annual return (Form B1) filing fee **€20**; additional €15 if
    filing a G5 with an A1. Obtained via search index 2026-09-17; the CRO site itself returned HTTP 403.

**Sibling report in this study (second-hand, with its own sources):**
24. **R2-D-distribution-signing.md** (this study, 2026-09-17). §2 Microsoft Store registration and fees (its sources
    R[1]–R[7], ms.date 2025-08-07 to 2026-09-17), §2 Store Policies v7.20 §10.2.4 (its R[5], ms.date 2026-09-14),
    App Developer Agreement v8.11 (its R[6], effective 2026-04-17), §3 Azure Artifact Signing pricing and eligibility
    (its R[21]–R[27]), §3 certificate price table (its R[31]–R[47]).

**Repository, read read-only:**
25. `C:/Users/mrbla/BlarAI/LICENSE.md` — PolyForm Noncommercial License 1.0.0 with a Required Notice naming
    Blair DuCray-Oppat as copyright holder, 2026.
26. `C:/Users/mrbla/BlarAI/COMMERCIAL-LICENSE.md` — dual-licensing statement; commercial use requires a paid licence.
27. `git shortlog -sne main` in `C:/Users/mrbla/BlarAI` — 3,829 commits Blair <mr.blair.do@gmail.com>; 5 blarai@local;
    3 claude@local; 2 blair@local. Run 2026-09-17.
