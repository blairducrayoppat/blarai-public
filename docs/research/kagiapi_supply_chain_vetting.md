# Supply-Chain Vetting: `kagiapi` Python Package

**Scope:** W2 (Agentic Web-Search Skill, ticket #573) — fork-free pre-work.
**Author:** supply-chain specialist subagent, 2026-06-04
**Status:** VETTED — adoption pending explicit Lead-Architect approval.
This document does NOT add kagiapi to pyproject.toml or any requirements file.
That step is W2 proper.

---

## 1. Canonical Package Identity

| Field | Value |
|---|---|
| PyPI name | `kagiapi` |
| Latest stable version | **0.2.1** |
| Release date | 2024-05-11 |
| GitHub | https://github.com/kagisearch/kagiapi |
| Author | Vladimir Prelovac (vlad@kagi.com), Kagi Search |
| License | MIT (confirmed via LICENSE file in repo, copyright Kagi Search 2023) |
| PyPI classifiers | None declared (license classifier absent — see §5) |
| Python requires | >=3.7 |
| Total releases | 3 (0.1.0, 0.2.0, 0.2.1) |

---

## 2. Architecture: Thin Wrapper Confirmed

`kagiapi` is a **thin synchronous requests wrapper** around Kagi's REST API (base URL `https://kagi.com/api/v0`). Source in `kagiapi/api.py` defines one class, `KagiClient`, with four public methods:

- `search()` — GET `/search`
- `summarize()` — GET `/summarize`
- `fastgpt()` — POST `/fastgpt`
- `enrich()` — GET `/enrich/news`

All methods use a single persistent `requests.Session`. Authentication: API key passed via constructor argument or the `KAGI_API_KEY` environment variable; transmitted as the HTTP header `Authorization: Bot {api_key}`. No async, no heavy framework, no ML inference, no local database.

The wheel is **3,703 bytes** (unzipped source \~8 KB). This is a thin client by any measure.

---

## 3. Transitive Dependency Tree

kagiapi 0.2.1 declares two direct dependencies without version pins (`requests`, `typing-extensions`). The full transitive tree under `requests` is:

```
kagiapi 0.2.1
├── requests          (no pin)  — HTTP client
│   ├── charset-normalizer <4,>=2  — encoding detection
│   ├── idna <4,>=2.5              — IDNA hostname support
│   ├── urllib3 <3,>=1.21.1        — HTTP/1.1 connection pool
│   └── certifi >=2017.4.17        — Mozilla root CA bundle
└── typing-extensions (no pin) — typing backport
```

None of `requests`'s optional extras (`socks`, `use-chardet-on-py3`) are needed and must not be installed. The core tree is five packages total. No package pulls in a C extension, ML framework, cloud SDK, or unexpected network-calling library.

---

## 4. Pinned + Hash-Checked Requirements

The lines below are the exact pip hash-checking-mode requirement blocks for all five packages. Version selection rationale for each follows in §4.1.

```
# W2 Kagi API client — pinned + hashed per BlarAI #560 supply-chain hardening
# Install ONLY with: pip install --require-hashes -r this_file.txt
# Do NOT install until Lead-Architect approves W2 adoption.

kagiapi==0.2.1 \
    --hash=sha256:f3f1466908041d117770b7f93bee12097e114dd518c4dda35413df785546799a \
    --hash=sha256:355fe407b4c683d6f084827e4f854fd95134df2842f15d089dacff620e3f4aeb

requests==2.32.3 \
    --hash=sha256:70761cfe03c773ceb22aa2f671b4757976145175cdfca038c02654d061d6dcc6 \
    --hash=sha256:55365417734eb18255590a9ff9eb97e9e1da868d4ccd6402399eaf68af20a760

typing_extensions==4.12.2 \
    --hash=sha256:04e5ca0351e0f3f85c6853954072df659d0d13fac324d0072316b67d7794700d \
    --hash=sha256:1a7ead55c7e559dd4dee8856e3a88b41225abfe1ce8df57b7c13915fe121ffb8

charset_normalizer==3.4.1 \
    --hash=sha256:56f1371d137d5c9ebc3d07cade541f66d55e61eb114ecc80e7cf5b735c70d67c \
    --hash=sha256:f30bf9fd9be89ecb2360c7d94a711f00c09b976258846efe40db3d05828e8089

idna==3.10 \
    --hash=sha256:946d195a0d259cbba61165e88e65941f16e9b36ea6ddb97f00452bae8b1287d3 \
    --hash=sha256:12f65c9b470abda6dc35cf8e63cc574b1c52b11df2c86030af0ac09b01b13ea9

urllib3==2.3.0 \
    --hash=sha256:1cee9ad369867bfdbbb48b7dd50374c0967a0bb7710050facf0dd6911440e3df \
    --hash=sha256:f8c5449b3cf0861679ce7e0503c7b44b5ec981bec0d1d3795a07f1ba96f0204d

certifi==2025.1.31 \
    --hash=sha256:ca78db4565a652026a4db2bcdf68f2fb589ea80d0be70e03929ed730746b84fe \
    --hash=sha256:3d5da6925056f6f18f119200434a4780a94263f10d1c21d032a6f6b2baa20651
```

Each line includes both the wheel hash and the sdist hash. When pip runs with `--require-hashes`, it verifies the downloaded artifact before installation; mismatches hard-fail. For packages with architecture-specific wheels (charset-normalizer ships C-extension wheels for CPython), the py3-none-any wheel is the one that applies on BlarAI's Windows/Python stack unless Cython is available; the sdist hash is the fallback safety net.

### 4.1 Version Selection Rationale

**kagiapi 0.2.1** — the only available stable release; no choice to make.

**requests 2.32.3** — the latest stable release at vetting time (2026-06-04). Fixes CVE-2024-35195 (proxy credential leakage in prior versions). Required python >=3.8 is met by BlarAI's stack.

**typing_extensions 4.12.2** — selected as the last release that supports Python 3.7 (matching kagiapi's declared floor) while remaining fully compatible with Python 3.11+. Version 4.15.0 (latest at time of vetting) drops Python 3.7/3.8 support; since BlarAI runs Python 3.11+ in practice, either works, but 4.12.2 is the last version with broad cross-version tolerance and is what most published packages pin against. The LA may bump to 4.15.0 if desired — both hashes are verifiable on PyPI.

**charset-normalizer 3.4.1** — latest stable within the `<4,>=2` constraint. No runtime dependencies of its own.

**idna 3.10** — latest stable within the `<4,>=2.5` constraint. No runtime dependencies.

**urllib3 2.3.0** — chosen as 2.3.0 over 2.4.0 (also available) because 2.4.0 raises the floor to Python 3.10+. BlarAI runs 3.11+ so either works in practice; 2.3.0 is the safer conservative pin that matches the broadest environments. The LA may bump to 2.4.0 if preferred.

**certifi 2025.1.31** — latest stable at vetting time within the `>=2017.4.17` constraint. Ships Mozilla's April 2025 root CA bundle. Note: certifi is **relevant only to HTTPS egress from the web-search skill worker**; it is not used by the BlarAI runtime proper (which is air-gapped). The runtime egress guard (`shared/security/egress_guard.py`) will block any outbound call from unarmed processes; the web-search worker process must be explicitly designed to arm/not-arm appropriately per the W2 architecture.

---

## 5. Supply-Chain Risk Assessment

### 5.1 Maintenance Status — YELLOW FLAG

kagiapi's PyPI history shows 3 releases over approximately 14 months (March 2023 through May 2024), then **no new PyPI releases for over two years** (the latest is 0.2.1, 2024-05-11). The GitHub repository has 32 commits total; the most recent commit is April 18, 2025 (a docs/PR merge). There are 5 open issues and 3 open pull requests — the project is not abandoned but is clearly low-cadence and receives no security-response-grade maintenance.

**Risk bearing on BlarAI:** The Kagi API itself is versioned (`/api/v0`). If Kagi deprecates v0 or changes authentication schemes, kagiapi will not self-update. The dependency is thin enough that the BlarAI team can fork or replace it without cost. The package itself has no CVEs — its attack surface is limited to HTTP header construction and JSON parsing, both delegated to `requests`.

Rejected framing — "this is fine because it's thin." Thinness reduces the blast radius of a supply-chain compromise but does not eliminate it. A compromised kagiapi 0.2.2 that injects the API key into an additional header or exfiltrates it via a side channel would be invisible without pinning. The `--require-hashes` discipline (§4) eliminates that vector: the installed artifact must byte-match the vetted hashes.

### 5.2 No Version Pins in kagiapi's Own Manifest — YELLOW FLAG

kagiapi's setup.py declares `requests` and `typing_extensions` without version constraints. This is standard for small wrappers but means `pip install kagiapi` without `--require-hashes` would pull whatever `requests` is current. The pinned-requirements block in §4 supersedes this: installing from that block always resolves to the exact audited versions.

### 5.3 License Classifier Absent — LOW

The PyPI metadata has no license classifier; the `License` field is empty. However, the repo's `LICENSE` file is a standard MIT License, copyright Kagi Search 2023. MIT is permissive, attribution-only, and compatible with BlarAI's closed personal build. The absent classifier is a packaging quality gap, not a legal risk. **MIT license is confirmed and is permissive.**

### 5.4 No Release Tags on GitHub — LOW

GitHub's "Releases" page shows "No releases published" despite three PyPI uploads. Versions were pushed to PyPI directly from the repo without tagging. This is a quality signal (not a security risk), and it means you cannot trivially `git checkout v0.2.1` to audit the exact source. Mitigation: the PyPI sdist (`kagiapi-0.2.1.tar.gz`) is the authoritative artifact; its sha256 hash is pinned in §4 and can be manually verified at any time.

### 5.5 Dependency Chain — PASS

`requests` is one of the most downloaded Python packages (\~300M downloads/week, depended upon by 4M+ repos). Its transitive deps (`charset-normalizer`, `idna`, `urllib3`, `certifi`) are equally canonical. No unexpected packages appear in the tree. No package in the tree is a cloud SDK, telemetry library, or network-calling framework beyond HTTP.

### 5.6 Egress Interaction — NOTE

The web-search worker will be the first BlarAI process designed to make **intentional external network calls**. This is a planned and design-governed carve-out, not a violation of BlarAI's privacy mandate. However:

- The web-search skill process must **not arm the egress guard** (or must arm it with an extended allowlist that permits `kagi.com`). The existing `egress_guard.py` allowlist permits only loopback and AF_HYPERV; it will block `requests` calls to `kagi.com` as currently written (ADR-020).
- This is an **architecture decision for W2 proper**, not a supply-chain finding. It is noted here because it affects how kagiapi is wired into the process model.

---

## 6. Summary Verdict

| Criterion | Result |
|---|---|
| Canonical package on PyPI | PASS — official Kagi Search package |
| Dependency footprint | PASS — thin wrapper, five packages, no surprises |
| License | PASS — MIT confirmed |
| Hash-pinnable | PASS — §4 requirement block ready for adoption |
| Maintenance cadence | YELLOW — low-cadence, no recent PyPI release; acceptable given thinness |
| Version pinning in manifest | YELLOW — mitigated by the §4 hash-locked block |
| License classifier | LOW — absent from metadata but MIT confirmed in repo |
| CVE history | PASS — none found |

**Recommendation:** kagiapi 0.2.1 is acceptable for adoption under the pinned/hashed requirement block in §4. The two yellow flags (maintenance cadence, absent version pins) are mitigated by hash-pinning discipline and do not warrant rejection. The egress-guard interaction noted in §5.6 must be resolved in the W2 architecture before the first network call is made.

Adoption requires explicit Lead-Architect approval. This document is the pre-approval vetting record.
