# R2-D — Distribution channels for a Windows security utility (one-person EU company)
(Persisted by the compiler from the sub-agent's returned text; content unchanged.)

Grading key: R = REPORTED (source number in the Sources list, with the page's ms.date or fetch date); M = MEASURED here (an API sample pulled on 2026-09-17, conditions stated); G = GUESSED (estimate with reasoning). All fetches were made 2026-09-17. The session's WebSearch quota was exhausted after the first 10 searches, so everything below rests on direct fetches of primary pages. Currency is stated per figure.

## Outcome in five lines
1. Listing on the Microsoft Store is free for both individual and company accounts since the 2025 onboarding flow, but a one-person company selling software must use a Company account (policy 10.14), and a utility that installs an NT service or driver hits policy 10.2.4 ("generally not allowed", case-by-case for WHCP-certified drivers). A pure user-mode utility lists fine via the EXE/MSI route; a service/driver one is at Microsoft's discretion.
2. winget is free and reachable to every Windows 11 machine, but its pipeline scans installers with several antivirus engines and explicitly refuses "genuine tools used for debugging and low-level activities" that look like PUA; a privileged governor is the shape it refuses. winget alone does not reach consumers.
3. Cheapest credible signing for an EU company is Azure Artifact Signing (formerly Trusted Signing) at €8.58/month (Basic), which is open to EU organisations with no minimum company age since GA, but not to EU individuals (US/Canada only). An EU sole proprietor without a registered entity must buy an OV/IV certificate (€177–€199/yr class).
4. No certificate gives instant SmartScreen reputation any more — Microsoft's own page says so (EV included) and says clearing takes "several weeks and hundreds of clean installs"; Artifact Signing customers lost reputation twice in 2026 through silent CA rotations.
5. The channel that reached hundreds of thousands for comparable indie utilities is direct download from GitHub Releases or the project site (Rufus 266M, Notepad++ 353M, ShareX 34M, simplewall 3.6M, Sandboxie-Plus 8.7M release downloads), at near-zero channel cost, monetised by donations, paid Store copies or supporter licences. The Store adds consumer reach for consumer-shaped apps (Lively: 18,717 Store ratings); winget/Chocolatey add 10^4–10^6.

## 1. Microsoft Store
- Registration fee. Individual account: the $19 one-time fee is waived in the new flow at storedeveloper.microsoft.com; government ID + selfie verification. R[1] (ms.date 2025-08-07), R[2] (blog 2025-09-10). Company account: "With the new onboarding experience, there are no registration fees for either account type"; verification by DUNS or official business documents (manual review 2–5 business days), work e-mail on the company's domain. R[3] (ms.date 2025-09-17, updated 2026-07-17). The pre-2025 company fee was about $99 USD. R[4] (secondary).
- Which account a one-person EU company must use. Policy 10.14: "Company accounts must be used for organizations, businesses, and any person acting in relation to their trade or profession." R[5] (policies v7.20, ms.date 2026-09-14), R[3]. A company account requires a registered legal entity and a domain e-mail.
- Revenue share. App Developer Agreement v8.11 (published 2026-03-17, effective 2026-04-17), §6(b): Store Fee = 15% of Net Receipts for Apps, 12% for Games, 30% for Xbox-console; §5(e): "Purchases made on a third-party commerce engine are not subject to the Store Fee." R[6]. The Learn benefits page states the same: keep 100% with your own commerce for non-games. R[7] (ms.date 2023-12-13). Practical consequence: a free Store listing that sells licences on the developer's own site pays 0%.
- Policies that bind a security utility (v7.20, R[5]): 10.2.3 no malware per Microsoft's criteria; 10.2.4 "Generally, dependency on non-Microsoft provided drivers or NT services is not allowed but may be considered case by case for WHCP certified drivers... you must disclose that dependency to Microsoft in the certification notes"; 10.1.5 add-ons may not be drivers or NT services; 10.2.8 changing Windows settings requires supported methods and user consent; 10.2.9 the EXE/MSI route: HTTPS direct link; every PE file signed with a certificate chaining to a Microsoft Trusted Root Program CA; versioned URL whose binary never changes; silent install required, UAC dialog allowed; no downloader stubs. Same text in R[9] (ms.date 2022-10-30, updated 2026-08-24). 10.5.1 privacy policy. No policy text mentions antivirus, "security software", Defender or elevated privileges as such. Not verified: whether a Windows service inside an MSIX passes certification.
- Can a utility with a service/driver be listed? User-mode-only: yes. With an NT service or kernel driver: 10.2.4 makes it discretionary. G: expect a certification-notes negotiation and a real chance of rejection; design the Store SKU as user-mode-only, or accept the driver build lives outside the Store.
- Reach. Store: "250+ million monthly active users" R[2] (2025-09-10). Store PDP figures via the Store's product API 2026-09-17 R[10]: Files App — $12.99 list, 3.9★, 2,993 ratings; Lively Wallpaper — free, 4.6★, 18,717 ratings; Sysinternals Suite — free, 4.4★, 179 ratings. G: at a 0.5–2% rating rate Lively's Store installs are 1–4M, Files' paid listing 150k–600k. Store-installed MSIX apps never see SmartScreen R[11] (ms.date 2026-05-04).

## 2. winget (Windows Package Manager)
- Free. Preinstalled on Windows 11, Windows 10 1809+, Windows Server 2025. R[12] (ms.date 2026-07-19). Installer types: EXE, MSI, MSIX/APPX, INNO, NULLSOFT, WIX, BURN, ZIP, PORTABLE, FONT.
- Manifest/submission requirements R[13] (ms.date 2024-11-21, updated 2026-07-14): HTTPS URL directly from the publisher's release location; SHA-256 pinned per URL; silent install and clean uninstall, tested as admin and non-admin; URL reputation check (SmartScreen); installers run through "several antivirus programs"; manual moderator review. Policies v1.0 (2021-05-22, ms.date 2026-08-30) R[15]. No signed-installer requirement — integrity comes from the hash.
- Policy on privileged/security tools: "Sometimes, genuine tools used for debugging and low-level activities appear as PUA to antivirus software... the Windows Package Manager repository unfortunately can't allow these applications." Microsoft first asks the AV vendor to clear a false positive; if the vendor cannot, the PR is rejected. R[13]. That is the concrete risk for a process-governing utility.
- Review time (M): GitHub Search API sample 2026-09-17: 18 merged "New package" PRs created 2026-08-31 → 2026-09-13, created→merged min 0.2 h, median ≈9.7 h, max 176 h (7.3 days). R[17]. Backlog: 1,043 open "New package" PRs; oldest 59 days. R[18]. Conditions: one snapshot, n=18.
- Reach: no public winget figures. Chocolatey counters as the CLI-channel proxy: 7-Zip 35.6M, Notepad++ 22M, Sysinternals 11.1M, Everything 5.0M, PowerToys 4.0M, WizTree 2.6M, Rufus 858k, ShareX 541k, simplewall 36k, Sandboxie-Plus 32k, GlassWire 57k. R[20]. G: winget is a delivery/update rail, not a reach channel.

## 3. Direct download and code signing

### Azure Artifact Signing (formerly Trusted Signing)
- Price (R[21], Azure Retail Prices API, effective 2024-06-01): Basic $9.99/month, Premium $99.99/month, overage $0.005/signature; in EUR: Basic €8.5781, Premium €85.8578. Quotas: Basic 5,000 signatures/month and 1 certificate profile of each type; Premium 100,000 and 10 each. Not pro-rated; a paid Azure subscription required. R[23] (FAQ ms.date 2026-05-14). "Starts at $9.99/month." R[11].
- Eligibility (R[24], quickstart ms.date 2026-05-21): Public Trust certificates for organisations in the US, Canada, the EU, the UK, Australia, New Zealand, Japan, South Korea, Singapore, Switzerland, Norway and Israel; "Individual developers must be located in the United States or Canada." A French individual was told on 2026-03-06 that individual onboarding is paused outside US/CA. R[25]. Microsoft's Meha-MSFT answered on 2026-08-17: "no minimum org age restrictions." R[27]. Organisation validation needs a legal entity name, a website, a primary e-mail on a domain the entity owns, a business identifier and an individual ID check; 1–20 business days. So an EU one-person company with its own domain qualifies; an EU sole trader without a registered entity does not.
- Region: North Europe, West Europe, Poland Central, Switzerland North available. R[24].
- Certificates: short-lived (3-day signing window with timestamped signatures valid indefinitely R[28]). No EV certificates. Kernel-mode signing stays with Partner Center. R[23].
- SmartScreen: Microsoft's own table lists Artifact Signing under "reputation accumulates over time based on download volume", same row as OV/EV. R[11]. Incident record: GitHub Azure/artifact-signing-action #128 (opened 2026-04-07, still open, 60+ comments): a silent intermediate-CA migration around 2026-03-21/23 made freshly signed files show "Windows protected your PC"; regressions 04-16/17 and 04-24/26; #136 (2026-05-05) repeated it. R[30].

### OV / EV certificates from commercial CAs
- Hardware rule: since 2023-06-01 code-signing keys must live in FIPS 140-2 Level 2 hardware or a cloud HSM (R[31]). Validity capped at 460 days for certificates issued from 2026-03-01 (R[32]); Sectigo limits orders to 1 year since February 2026 (R[33]); GlobalSign 1-year only since 2025-12-26 (R[34]).
- EV no longer buys SmartScreen reputation. Microsoft: "EV certificates no longer bypass SmartScreen... Paying a premium for EV solely to avoid SmartScreen warnings is no longer justified." R[11]. EV is still mandatory to register for the Windows Hardware Developer Program and to submit drivers for attestation signing (R[38] ms.date 2026-08-11; R[39]; R[40]).

| Option | Provider | Price | Term | Who is eligible | Token/HSM | SmartScreen effect | Grade |
|---|---|---|---|---|---|---|---|
| Artifact Signing Basic | Microsoft Azure | $9.99/mo (€8.58) + $0.005/sig over 5,000 | monthly | Orgs in EU/UK/US/CA/+8; individuals US/CA only; no min. org age | cloud HSM, no token | reputation accumulates like OV; CA-rotation resets seen 2026 | R |
| Artifact Signing Premium | Microsoft Azure | $99.99/mo (€85.86), 100k sigs, 10 profiles | monthly | as above | cloud HSM | as above | R |
| OV code signing | SSL.com | $129 / $116.10 / $109.65 per yr | 1/2/3 yr | organisations only | YubiKey +$379 or eSigner cloud | warning until reputation | R |
| IV (individual) code signing | SSL.com | $129 / $116.10 / $109.65 per yr | 1/2/3 yr | individuals, government ID | YubiKey +$379 or eSigner | "starts with no reputation" | R |
| EV code signing | SSL.com | $349 / $299 / $249 per yr | 1/2/3 yr | orgs; sole-proprietor EV offered | YubiKey +$379 | none since Mar-2024 | R |
| Standard (OV/IV) | Sectigo (sectigostore) | $313.50 / $265.65 / $219.45 per yr | 1/2/3 yr | orgs and individual developers | token or own HSM | none special | R |
| EV | Sectigo (sectigostore) | $410.85 / $349.80 / $288.20 per yr | 1/2/3 yr | organisations only | token or HSM | none special | R |
| OV / EV | DigiCert direct | $44/mo and $62/mo (≈ $528 / $744 per yr) | 12 months | organisations | KeyLocker cloud or token | none claimed | R |
| Standard code signing (cloud) | Certum via LeaderSSL | €177 / €277 / €362 excl. VAT | 1/2/3 yr | organisations (OV) | SimplySign cloud | — | R |
| Standard (SimplySign) | Certum via sslpoint | $199 / $149/yr / $129/yr | 1/2/3 yr | "For individual Devs" | virtual token | — | R |
| EV (cloud) | Certum via LeaderSSL / sslpoint | €297 / €480 / €695 excl. VAT | 1/2/3 yr | organisations | SimplySign cloud | — | R |
| Open Source code signing | Certum | price not captured (certum.eu refused connection) | ~1 yr | individuals only, open-source non-commercial software; revoked if used commercially | SimplySign cloud HSM | none special | R (terms) / G (price) |
| Windows Hardware Dev Program | Microsoft Partner Center | account free; needs an EV certificate to register | — | organisations with Entra ID | EV cert on HSM | n/a (kernel drivers) | R |

### SmartScreen build-up
Microsoft (R[11], ms.date 2026-05-04): two signals — publisher (certificate) reputation and file-hash reputation; "no exact threshold, but it can take several weeks and hundreds of clean installs from a wide audience"; no mechanism to manually submit a file for reputation review for consumer endpoints; reputation carries to new versions only when signed with the same identity; Smart App Control on Windows 11 blocks unsigned files outright. G: budget 2–6 weeks and a few hundred to low thousands of installs per new signing identity; keep one signing identity for life.

### Antivirus false-positive risk
- Microsoft's classification criteria (R[50], ms.date 2026-01-29) contain a "Tampering software" class that a governor brushes against: disabling security software, firewall abuse, manipulating kernel drivers or system services, privilege escalation, unauthorised registry changes; plus PUA "Evasion software". Design implication: never touch Defender/third-party AV state, use documented APIs, be transparent about what it blocks.
- Microsoft Security Intelligence file submission: free; "Software developer" category; medium priority "within a few days". R[51]. Kaspersky Allowlist Program exists (terms not verified). Bitdefender submit pages 403/404 — not verified. Avast free false-positive form; Norton/Gen free forms.
- Evidence that privileged utilities survive: simplewall (WFP, admin) and Sandboxie-Plus (kernel driver) ship millions of downloads via GitHub; both on winget/Chocolatey, so the winget PUA gate is passable for known projects. G: a new unknown publisher will hit Defender "unknown/uncommon" warnings and at least one third-party engine on first release; plan a submission round to Microsoft, Kaspersky, Bitdefender, Avast/Norton and ESET before launch.

## 4. Which channel reaches "hundreds of thousands"
Indie reach table (read 2026-09-17; GH = GitHub release-download total; Choco = Chocolatey total; SF = SourceForge weekly):
| App | Reach metric | Channels | Monetisation |
|---|---|---|---|
| Files | 45.5k stars; GH 56k; Choco 135k; Store 2,993 ratings, $12.99 | Store (paid) + free classic installer + winget/choco | paid Store copy, sponsors |
| Flow Launcher | 15.6k stars; GH 26M; Choco 45k | GitHub, winget, Scoop, Chocolatey | donations |
| ShareX | 39.6k stars; GH 34M; Choco 541k | GitHub, Store, Steam, site | donations |
| Everything (voidtools) | Choco 5.02M | direct; winget/choco | donations |
| WizTree | Choco 2.60M | direct | free personal; paid supporter/enterprise licence |
| Rufus | 37.7k stars; GH 266M; Choco 858k | GitHub Releases, rufus.ie | none; site ads |
| Sysinternals | Choco 11.1M; Store 179 ratings | live.sysinternals.com, Store, winget | free; acquired by Microsoft 2006-07-18 |
| PowerToys | 138.8k stars; GH 139M; Choco 3.96M | GitHub, Store, winget | free (Microsoft) |
| Notepad++ | 29.3k stars; GH 353M; Choco 22.0M | GitHub, site, SourceForge | GPL, donations |
| 7-Zip | SF 22,670/wk; Choco 35.6M | site, SourceForge | LGPL, donations |
| Sandboxie-Plus | 19.4k stars; GH 8.7M; Choco 32k | GitHub, winget, Chocolatey | supporter certificates €40 Home / €80 Personal / €50 Family / €60 renewal; Patreon |
| GlassWire | vendor claim "Over 54 million downloads!"; Choco 57k | direct | freemium; Premium $2.99/mo billed annually |
| simplewall | 9.0k stars; GH 3.6M; Choco 36k | GitHub (GPG-signed) | donations |
| O&O ShutUp10++ | Choco 277k | direct | free; optional Premium |
| Bulk Crap Uninstaller | 21.4k stars; GH 2.8M; Choco 203k | GitHub, SourceForge, FossHub | Apache-2.0, donations |
| Ventoy | 79.3k stars; GH 17M; Choco 204k | GitHub, SourceForge | GPLv3, donations |
| Greenshot | 5.1k stars; GH 14M; Choco 4.13M | GitHub, site, Chocolatey | GPL, donations |
| Lively Wallpaper | 19.6k stars; GH 22M; Store 18,717 ratings 4.6★ free | Store + GitHub | free, Patreon |

Reading: direct download carries the large figures; the two privileged-utility peers (simplewall 3.6M, Sandboxie-Plus 8.7M) cleared "hundreds of thousands" on GitHub alone, over years of free availability and word of mouth; none bought distribution. G: channel cost ≈ €0 beyond code signing; the real spend is years. The Store is second and policy-gated for a service/driver. winget/Chocolatey are third by an order of magnitude. Monetisation observed: donations, a paid Store SKU of a free app, supporter licences (€40–80), freemium subscription ($2.99/mo), ads. No one in this set charges for the direct download itself.

## What could not be found or verified
EUR registration fee figures (moot); whether a Windows service inside an MSIX passes Store certification; whether Store-launched EXE/MSI installers are SmartScreen-exempt; any Microsoft-published winget usage figure; Certum's own price list; the April-2025 Trusted Signing restriction post (cited via Q&A); Kaspersky Allowlist terms, Bitdefender whitelisting, Avast whitelisting article, VirusTotal; Store rating counts for PowerToys.

## Sources (all fetched 2026-09-17)
1. learn.microsoft.com/en-us/windows/apps/publish/whats-new-individual-developer — ms.date 2025-08-07
2. blogs.windows.com/windowsdeveloper/2025/09/10/free-developer-registration-for-individual-developers-on-microsoft-store/ — 2025-09-10
3. learn.microsoft.com/en-us/windows/apps/publish/partner-center/open-a-developer-account — ms.date 2025-09-17, updated 2026-07-17
4. winbuzzer.com 2025-09-12; pcworld.com/article/2785825 — 2025-09 (secondary)
5. learn.microsoft.com/en-us/windows/apps/publish/store-policies — v7.20, ms.date 2026-09-14
6. go.microsoft.com/fwlink/?linkid=528905 → MS.Store.ADAv8.11.US.EN.pdf — published 2026-03-17, effective 2026-04-17
7. learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/why-distribute-through-store — ms.date 2023-12-13
8. xda-developers.com/microsoft-store-build-2025/ — 2025-05-19
9. learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msi/app-package-requirements — ms.date 2022-10-30, updated 2026-08-24
10. storeedgefd.dsx.mp.microsoft.com/v9.0/pages/pdp?productId=9NGHP3DX8HDX (Files), 9NTM2QC6QWS7 (Lively), 9P7KNL5RWT25 (Sysinternals) — 2026-09-17
11. learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation — ms.date 2026-05-04
12. learn.microsoft.com/en-us/windows/package-manager/winget/ — ms.date 2026-07-19
13. learn.microsoft.com/en-us/windows/package-manager/package/repository — ms.date 2024-11-21, updated 2026-07-14
14. github.com/microsoft/winget-pkgs/blob/master/doc/README.md — 2026-09-17
15. learn.microsoft.com/en-us/windows/package-manager/package/windows-package-manager-policies — ms.date 2026-08-30
17. api.github.com/search/issues (merged "New package" PRs) — 2026-09-17 (n=18)
18. api.github.com/search/issues (open "New package" PRs) — 2026-09-17
20. community.chocolatey.org/packages/{...} — 2026-09-17
21. prices.azure.com/api/retail/prices?$filter=contains(productName,'Signing') (USD and EUR) — effective 2024-06-01, fetched 2026-09-17
22. azure.microsoft.com/en-us/pricing/details/artifact-signing/ — 2026-09-17
23. learn.microsoft.com/en-us/azure/artifact-signing/faq — ms.date 2026-05-14
24. learn.microsoft.com/en-us/azure/artifact-signing/quickstart — ms.date 2026-05-21
25. learn.microsoft.com/en-nz/answers/questions/5810735/... — 2026-03-06
27. learn.microsoft.com/en-us/answers/questions/5977141/azure-artifact-signing-trusted-signing-is-a-us-llc — 2026-08-17
28. weblog.west-wind.com/posts/2025/Jul/20/Fighting-through-Setting-up-Microsoft-Trusted-Signing — updated 2026-03-02
30. github.com/Azure/artifact-signing-action/issues/128 (2026-04-07) and /136 (2026-05-05)
31. digicert.com/signing/code-signing-certificates — 2026-09-17
32. my-ssl.com/learn/open-source-code-signing-certificate — 2026-07-23
33. sectigostore.com/code-signing/sectigo-code-signing-certificate — 2026-09-17
34. shop.globalsign.com/en/code-signing — 2026-09-17
35. todesktop.com/blog/posts/windows-apps-psa-ev-certs-do-not-grant-immediate-reputation-anymore — 2026-05-10
36. ssl.com/products/software-integrity/code-signing/ev/ — 2026-09-17
37. knowledge.digicert.com/alerts/ev-signed-application-showing-microsoft-defender-smartscreen-warnings — 2026-06-02
38. learn.microsoft.com/en-us/windows-hardware/drivers/dashboard/register-for-the-hardware-program — ms.date 2026-08-11
39. learn.microsoft.com/en-us/windows-hardware/drivers/dashboard/code-signing-attestation — ms.date 2025-07-15
40. learn.microsoft.com/en-us/windows-hardware/drivers/dashboard/code-signing-reqs — ms.date 2025-05-29
41. learn.microsoft.com/en-us/windows-hardware/drivers/dashboard/driver-signing-offerings — ms.date 2026-03-23
42–47. ssl.com OV/IV pages; sectigostore EV; codesigncert.com; sslpoint.com; leaderssl.com Certum — 2026-09-17
48. news.ycombinator.com/item?id=24220307 — 2020-08-20
49. learn.microsoft.com/en-us/answers/questions/417016/... — 2021-06
50. learn.microsoft.com/en-us/defender-xdr/criteria — ms.date 2026-01-29
51. microsoft.com/en-us/wdsi/filesubmission — 2026-09-17
52–54. kaspersky.com/partners/allowlist-program; avast.com/false-positive-file-form.php; submissions.norton.com/submitsample — 2026-09-17
55–79. GitHub repos + shields.io download badges, Chocolatey pages, SourceForge pages, vendor sites for Files, Flow Launcher, ShareX, Everything, WizTree, Rufus, Sysinternals, PowerToys, Notepad++, 7-Zip, Sandboxie-Plus (xanasoft.com/shop), GlassWire, simplewall, ShutUp10, Bulk Crap Uninstaller, Winaero, Ventoy, Greenshot, Lively — 2026-09-17
