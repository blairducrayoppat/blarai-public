# Supply-chain hash-pinning of the runtime dependency set

**Outcome:** BlarAI's Python runtime dependencies can now be installed
tamper-evidently. Every pinned package version is bound to the SHA-256 digests
of its published distribution files, so a `pip install --require-hashes` of the
lock reproduces the exact bytes BlarAI was built against — and a *substituted*
build of an otherwise-allowed version fails the install **closed**. This closes
the residual named in Sprint 16 (`#560` bullet 1, lesson 71): version pins are
version-*containment*; hashes are supply-chain *integrity*.

**Status: dormant groundwork.** The hash-pinned lock is committed and
gate-checked, but it is **not** wired into any boot or install path, and no
posture flag is flipped. Turning `--require-hashes` on at install time is a
separate, Lead-Architect-gated step, scoped as a condition of the *next* egress
/ network go-live ceremony (`#560` gate-framing, 2026-07-07) — not a retroactive
blocker on the already-open Kagi door.

---

## The two locks

BlarAI commits two files that describe the **same** resolved virtual
environment (`.venv`). They are kept consistent by the standing gate.

| File | Role | Form |
|---|---|---|
| `requirements.2026.2.1.lock.txt` | Reproducibility SSOT — the exact resolved set the runtime venv is built from (`#810`) | `name==version` |
| `requirements.2026.2.1.hashed.lock.txt` | Supply-chain integrity companion — same versions, plus every published file's digest | `name==version` + `--hash=sha256:` |

The version-pinned lock answers *"which versions?"*. The hashed lock adds
*"and are these the genuine, unmodified builds of those versions?"* — the
question the zero-egress test cannot answer, because a poisoned wheel of an
allowed version travels through an allowed install channel.

The hashed lock's first directive is `--require-hashes`, which makes the file
**self-enforcing**: pip refuses to process it if *any* requirement in it lacks a
hash. The control cannot silently decay back into a plain version pin.

### Coverage and the honest exclusions

The hashed lock covers **251** distributions — every `name==version` entry of
the reproduction lock. Five lines of the reproduction lock are **un-hashable**
and appear only inside a commented exclusion block at the foot of the hashed
lock (pip rejects an entire `--require-hashes` file that contains an editable or
a VCS/URL requirement):

- `-e c:\users\mrbla\projects\csv-json-validator-...` — a co-resident,
  non-BlarAI editable project in the shared dev venv.
- `optimum @ git+https://github.com/huggingface/optimum@60b86d7...`
- `-e git+https://github.com/rkazants/optimum-intel.git@d8864c4...`
- `optimum-onnx @ git+https://github.com/huggingface/optimum-onnx.git@b0367e9...`

**None of the five is a declared runtime dependency** in `pyproject.toml`. The
three `optimum*` entries are build/model-conversion toolchain (pinned by their
git commit ref, which is itself a content address); the editable is unrelated to
BlarAI. They are intentionally *not* installed by a `--require-hashes`
reproduction of the runtime set. Every distribution the runtime actually imports
(`pyproject.toml [project] dependencies`) **is** hash-covered — the standing-gate
test asserts exactly this.

---

## How to regenerate the hashed lock

Run at each substrate ceremony, whenever the version-pinned lock is refreshed.
It is a **dev-side tool** (stdlib only): it reads the SHA-256 digests PyPI
already publishes for each pinned release over the public JSON API, downloads no
packages, installs nothing, and never touches the runtime `.venv`. Use any
system Python.

```bash
python scripts/generate_hashed_lock.py \
    requirements.2026.2.1.lock.txt \
    requirements.2026.2.1.hashed.lock.txt
```

It exits non-zero if any `name==version` resolves to zero published digests (a
silent gap in a supply-chain control is a defect, not a warning). The output is
deterministic (entries sorted by normalized name, digests sorted) so a
regeneration diff shows only genuine changes.

---

## How to verify / reproduce

### Full runtime reproduction (heavy — downloads the whole set)

Into a **fresh, throwaway** virtual environment — never the runtime `.venv`:

```bash
python -m venv /tmp/blarai-verify
/tmp/blarai-verify/Scripts/pip install \
    --require-hashes -r requirements.2026.2.1.hashed.lock.txt
```

If every downloaded artifact's digest is listed, the install succeeds and the
venv is byte-reproduced. If any artifact has been tampered with, pip aborts
before installing it.

### Fast enforcement proof (a small slice)

`pip download --require-hashes --no-deps` drives the identical hash-verification
path without pulling the multi-gigabyte set:

```bash
# a 3-line slice cut verbatim from the hashed lock
pip download --require-hashes --no-deps -r slice.txt -d ./out   # -> success
```

---

## Live enforcement proof (recorded 2026-07-16)

Driven through real pip 25.3 (Python 3.14), a 3-package slice
(`colorama`, `idna`, `six`) cut verbatim from
`requirements.2026.2.1.hashed.lock.txt`, downloading into a throwaway dir (the
runtime `.venv` untouched):

1. **Correct hashes → SUCCESS.** All three wheels downloaded and hash-verified;
   `pip download` exit `0`.

2. **One of colorama's two hashes broken → still SUCCESS.** This is the
   important nuance: `--require-hashes` accepts a downloaded file whose digest
   matches **any** listed `--hash` for that pin (the lock records every platform
   wheel + sdist digest of a version). Breaking a single hash left the second,
   still-valid one to satisfy the check.

3. **Both of colorama's hashes broken → FAIL-CLOSED.** `pip download` exit `1`
   with:

   ```
   ERROR: THESE PACKAGES DO NOT MATCH THE HASHES FROM THE REQUIREMENTS FILE.
   ... someone may have tampered with them.
       colorama==0.4.6 ...
           Expected sha256 18695f5c...   (mutated)
           Expected     or 5f1d9991...   (mutated)
                Got        4f1d9991...   (the genuine wheel)
   ```

**Takeaway for any future tamper test:** because of the any-match semantics, a
faithful "tampered artifact fails closed" proof must invalidate **every**
recorded hash of the chosen distribution, not just one. The standing-gate test
`test_tamper_requires_breaking_all_hashes_note` records this so the mistake is
not repeated.

---

## What keeps it honest (standing gate)

`tests/security/test_supply_chain_hashes.py` (network-free, in the default gate):

- the lock exists and begins with `--require-hashes` (self-enforcing);
- every pin carries at least one valid 64-hex sha256 (no decorative entries);
- no active editable/VCS lines (which would make pip reject the whole file);
- the hashed and version-pinned locks agree on the exact version set (catches a
  version bumped in one lock but not regenerated in the other);
- **every declared runtime dependency is hash-covered** at a version satisfying
  its `pyproject.toml` specifier — the security-relevant completeness assertion.

It is a static parse only. It does not re-fetch PyPI to confirm each digest is
current (the generator's job) and does not assert any install path uses the lock
(it is deliberately dormant).

---

## What is deliberately NOT done here (`#560` b1 scope)

- **Not wired into boot or install.** Enabling `--require-hashes` at runtime-venv
  build time is the LA-gated enable step (next egress-door condition).
- **b2 — broader weight-integrity signing** (the model-manifest arc, `#107` /
  `#917`) is a separate `#560` sub-item and is not touched here.
- **The version set is unchanged.** No dependency was added, removed, upgraded,
  or reinstalled; the runtime `.venv` was read-only throughout (a `pip freeze`
  drift check confirmed it matches the reproduction lock exactly).
