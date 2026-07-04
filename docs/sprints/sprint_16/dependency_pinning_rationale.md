# Sprint 16 — Dependency Pinning Rationale (Stream C)

**Date:** 2026-06-07
**Stream:** C (dependency pinning, SDV criterion #5)
**Scope:** The six `pyproject.toml` files listed below — no `.py` files touched.

---

## 1. Files modified

| File | Changes |
|---|---|
| `pyproject.toml` (repo root) | **No change** — `cryptography>=46,<47` already correctly pinned (Sprint 14 EA-2) |
| `services/policy_agent/pyproject.toml` | `pydantic`, `openvino`, `tomli`, `PyJWT`, `cryptography` all pinned/upper-bounded |
| `services/assistant_orchestrator/pyproject.toml` | `pydantic`, `openvino`, `tomli`, `numpy` pinned/upper-bounded |
| `services/semantic_router/pyproject.toml` | `onnxruntime`, `tomli`, `numpy` pinned/upper-bounded |
| `services/ui_gateway/pyproject.toml` | `tomli` upper-bounded |
| `services/ui_shell/pyproject.toml` | `textual`, `tomli` upper-bounded |

---

## 2. Dependency-by-dependency decisions

### 2.1 `cryptography` — HIGH security criticality

**Installed:** 46.0.5

Root `pyproject.toml` already has `>=46,<47` (Sprint 14 EA-2, ADR-025 §5.1 #3). The Policy Agent
had `>=41.0` — a wide-open lower bound that would permit installing a 5-major-version-old library.
Changed to `>=46,<47` to match the root pin exactly.

**Trade-off accepted:** When `cryptography` 47 ships, both specs need a deliberate increment. That
is the desired behaviour — a human reviews the release before it enters the installed set.

### 2.2 `PyJWT` — HIGH security criticality

**Installed:** 2.11.0. Used in Policy Agent JWT minting — the token sits on BlarAI's trust boundary.

Changed from `>=2.8` (unbounded) to `>=2.8,<3`. A PyJWT 3.x major release could introduce
API-breaking changes or new default behaviours on the signing path. Containing within the 2.x
series means that class of breakage is blocked until explicitly reviewed.

**Trade-off accepted:** A hypothetical PyJWT 3.x that fixes a security issue would not be auto-picked.
In practice, security patches within 2.x backport; the `<3` ceiling is the safer posture here because
it forces review before a major boundary crosses the trust surface.

### 2.3 `pydantic` — MEDIUM-HIGH security criticality (parsing/serialization)

**Installed:** 2.12.5. Used in Policy Agent + Assistant Orchestrator for all inter-service message
validation — the parsing surface of an incoming message is part of the security boundary.

Changed from `>=2.5` (unbounded) to `>=2.5,<3`. Pydantic v3 is not yet released (as of 2026-06-07)
but is on the roadmap; its v2→v3 migration will involve validator-semantic changes that must be
reviewed before they reach BlarAI's validation layer.

### 2.4 `openvino` — MEDIUM security criticality (model loading)

**Installed:** 2026.1.0. Used in Policy Agent + Assistant Orchestrator for model inference. The model
loading path is part of the weight-integrity chain; an unexpected openvino upgrade could silently
change binary parsing behaviour.

Changed from `>=2024.0` (very wide) to `>=2026.1,<2027`. This pins to the verified-working version
series. The year-based versioning makes major-series containment unambiguous.

**Trade-off accepted:** When the 2027.x series ships, the pin must be incremented. BlarAI is an
OpenVINO upstream contributor — that upgrade will be deliberate, not silent.

### 2.5 `numpy` — MEDIUM-LOW security criticality (security-adjacent signal processing)

**Installed:** 2.4.3. Used in Assistant Orchestrator for PGOV (Privacy Governor) leakage detection
and in Semantic Router. Not on the cryptographic trust boundary, but on the signal path that gates
PII-classification decisions.

Changed from `>=1.26` (very wide — would permit an 18-month-old release) to `>=2.0,<3`. The jump
from >=1.26 to >=2.0 merely reflects the installed reality (2.4.3); numpy 1.x has been superseded
and the 2.x API is the current baseline. The `<3` ceiling gates the next major series.

### 2.6 `onnxruntime` — MEDIUM security criticality (binary model parsing)

**Installed:** 1.24.2. Used in Semantic Router to load ONNX models. ONNX is a binary format; a
maliciously crafted ONNX file is a known attack surface for model-serving systems. Containing the
parser to a known-good minor series (`>=1.16,<2`) means a 2.x release with changed binary-parsing
behaviour cannot be silently pulled in.

Changed from `>=1.16` (unbounded) to `>=1.16,<2`.

### 2.7 `textual` — LOW security criticality (TUI framework)

**Installed:** 8.0.0. Not on a security boundary; text rendering of the chat UI. Upper-bounded to
`>=0.89,<9` to contain the next major version, which typically involves breaking widget-API changes.
Textual's versioning is rapid; the `<9` ceiling is a wide but nonzero bound.

**Note:** The original spec was `>=0.89` which matches the 0.89 era, but the installed version is
8.0.0 (Textual moved to calendar-style major versioning). The lower bound of `>=0.89` is satisfied
by 8.0.0 (8 > 0.89 numerically), so no conflict arises. The upper bound `<9` contains the NEXT
major Textual series.

### 2.8 `tomli` — LOW security criticality (TOML parsing, Python < 3.12 only)

**Installed:** Not found as a standalone wheel (on Python 3.12+, `tomllib` is stdlib; `tomli` is
only used on <=3.11). Upper-bounded to `<3` across all five service files that reference it. The TOML
parsing surface is read-only configuration, not a network-facing or user-input-facing parser.

---

## 3. Dev-only dependencies (not pinned — rationale)

The `[project.optional-dependencies].dev` sections (pytest, pytest-asyncio, pytest-cov,
pytest-textual-snapshot, ruff, mypy) were intentionally left with lower-bound-only specs. Dev
tooling is not part of the runtime security surface and tight dev-dep pins are a known source of
contributor friction in local environments. The quality gate is the installed .venv baseline (2172
tests passing), not the spec ceiling on test tooling.

**Installed versions for reference (verified 2026-06-07 from the project .venv):**
- pytest 8.4.2
- pytest-asyncio 1.3.0
- pytest-textual-snapshot 1.1.0
- mypy 1.19.1

---

## 4. Build-system deps (not pinned — rationale)

`[build-system].requires = ["setuptools>=68.0", "wheel"]` in the five service `pyproject.toml` files
were left with lower bounds only. Build-system deps apply only during wheel construction, not at
runtime, and adding upper bounds to setuptools is known to break `pip install -e .` with newer pip
resolvers. These are not part of the runtime security surface.

---

## 5. Hash verification — coverage gap (honest)

**PEP 508 (the `[project].dependencies` format used by `pyproject.toml`) does NOT support hash
specifications.** Hash pinning (`--require-hashes`) is a feature of the *install toolchain*
(pip-tools `requirements.txt`, `uv.lock`, Poetry `poetry.lock`), not of the declarative package
metadata format.

**What this means:** the pins here establish version bounds that a resolver must satisfy, but they
do NOT prevent a resolver from downloading any version within those bounds from PyPI. A
supply-chain attack that serves a malicious wheel at a pinned version (e.g. `cryptography==46.0.5`)
would not be blocked by these specs.

**Full hash verification requires a lock file**, generated by `pip-tools` (`pip-compile
--generate-hashes`) or `uv lock` and committed to the repo. That would be a new artifact (a
`requirements.lock` or `uv.lock`) — adding it is out of scope for this stream per SDV §5.3 ("pin
existing deps; add none"). Flagging this as a KNOWN GAP for the Orchestrator:

> **Coverage gap:** Version pins are present; hash-verified lock file is NOT. The security value of
> the pins is real (major-version surprises blocked; deliberate upgrade required before a new major
> series enters the installed set) but they do not constitute the full supply-chain assurance that
> hash-pinning provides. A lock file generation pass is the logical next step; it is a separate,
> deliberate act, not something this stream can add without creating a new artifact type.

---

## 6. Trade-offs requiring Orchestrator/LA attention

None rise to the level of escalation: all pins are conservative (contain within an already-installed
major series), no version is pinned *below* what is installed, and no capability is dropped. The
`openvino>=2026.1` pin is slightly opinionated (it narrows from `>=2024.0`) but installs the
already-present 2026.1.0 correctly.

The one decision worth noting: the `numpy>=2.0` lower bound is *higher* than the previous `>=1.26`.
This is not a narrowing that would break the installed 2.4.3 (which satisfies `>=2.0`), but if
someone were to install on an environment with numpy 1.x they would now get a resolution error
rather than silent installation of an older API. That outcome is intentional — numpy 1.x is past
its support window — but I flag it for completeness.

---

## 7. Verification

Full Layer-A suite command (run from the worktree root):

```
C:/Users/mrbla/BlarAI/.venv/Scripts/python.exe -m pytest shared/ services/ launcher/ \
    -m "not hardware and not winui and not slow" -q -p no:cacheprovider
```

The suite result must be >= 2172 passed, 0 failed. Actual result is recorded in the journal
fragment `docs/journal_fragments/2026-06-07_c-dependency-pinning.md`.
