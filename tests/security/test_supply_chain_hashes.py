"""Supply-chain hash-pinning lock is well-formed and complete (#560 b1).

BlarAI commits two locks that describe the same resolved venv:

* ``requirements.2026.2.1.lock.txt`` — the VERSION-pinned reproduction SSOT
  (``name==version``), gate-locked by ``test_dependency_truth.py`` (#810).
* ``requirements.2026.2.1.hashed.lock.txt`` — the HASH-pinned companion
  (``name==version`` + ``--hash=sha256:`` per published distribution file),
  the ``--require-hashes`` supply-chain-integrity artifact this file guards.

Version pins are version-*containment*; the hashed lock adds supply-chain
*integrity* — a compromised build of an *allowed* version has a different
digest and fails a ``--require-hashes`` install closed (lesson 71; #560 b1).
This test is the standing-gate control that keeps the hashed lock honest:
every pin carries a real sha256, the two locks never drift apart on versions,
and every declared runtime dependency is actually hash-covered. It is a static
parse only — NO network, NO install — so it belongs in the default gate. The
end-to-end enforcement proof (``pip install --require-hashes`` fails closed on
a tampered artifact) is exercised live and recorded in
``docs/security/supply-chain-hash-pinning.md``; that proof surfaced pip's
any-match semantics, which ``test_tamper_requires_breaking_all_hashes_note``
documents so a future tamper test is written correctly.

Scope honesty: this proves the hashed lock is well-formed, hash-complete, and
version-consistent with the reproduction lock. It does NOT re-fetch PyPI to
confirm each recorded digest is the currently-published one (that is the
generator's job, ``scripts/generate_hashed_lock.py``, run at each substrate
ceremony), and it does NOT assert the lock is wired into any install path — it
is deliberately dormant groundwork until an LA-gated enable step.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from packaging.requirements import Requirement

_REPO = Path(__file__).resolve().parents[2]
_VERSION_LOCK = _REPO / "requirements.2026.2.1.lock.txt"
_HASHED_LOCK = _REPO / "requirements.2026.2.1.hashed.lock.txt"

_PIN_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9.!+*]+)\s*\\?$")
_HASH_RE = re.compile(r"^--hash=sha256:([0-9a-f]{64})\s*\\?$")


def _normalize(name: str) -> str:
    """PEP 503 distribution-name normalization."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _parse_hashed_lock() -> dict[str, tuple[str, list[str]]]:
    """normalized name -> (version, [sha256, ...]) from the hash-pinned lock.

    Parses the ``name==version \\`` / indented ``--hash=sha256:...`` block form
    pip's ``--require-hashes`` files use. Commented lines (including the
    documented un-hashable exclusion block) are ignored.
    """
    entries: dict[str, tuple[str, list[str]]] = {}
    current: str | None = None
    for raw in _HASHED_LOCK.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line == "--require-hashes":
            continue
        pin = _PIN_RE.match(line)
        if pin:
            current = _normalize(pin.group(1))
            entries[current] = (pin.group(2), [])
            continue
        h = _HASH_RE.match(line)
        if h:
            assert current is not None, f"orphan --hash line: {raw!r}"
            entries[current][1].append(h.group(1))
            continue
        raise AssertionError(
            f"unexpected line in {_HASHED_LOCK.name} (not a comment, pin, or "
            f"--hash): {raw!r}"
        )
    return entries


def _version_lock_pins() -> dict[str, str]:
    """normalized name -> version from the version-pinned reproduction lock.

    Mirrors ``test_dependency_truth._lock_versions``: only ``name==version``
    lines; editable (``-e``) and VCS (``name @ git+``) lines carry no ``==``
    and are skipped — they are the un-hashable set the hashed lock excludes.
    """
    pins: dict[str, str] = {}
    plain = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9.!+*]+)$")
    for raw in _VERSION_LOCK.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "-")):
            continue
        m = plain.match(line)
        if m:
            pins[_normalize(m.group(1))] = m.group(2)
    return pins


def _declared_dependencies() -> list[Requirement]:
    with (_REPO / "pyproject.toml").open("rb") as fh:
        pyproject = tomllib.load(fh)
    deps = pyproject.get("project", {}).get("dependencies", [])
    assert deps, "pyproject.toml [project] dependencies is empty"
    return [Requirement(d) for d in deps]


def test_hashed_lock_exists_and_is_require_hashes() -> None:
    """The file exists and self-enforces: the first directive is
    ``--require-hashes`` so pip refuses any un-hashed entry."""
    assert _HASHED_LOCK.exists(), f"missing hash-pinned lock: {_HASHED_LOCK}"
    directives = [
        ln.strip()
        for ln in _HASHED_LOCK.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    assert directives and directives[0] == "--require-hashes", (
        "hash-pinned lock must begin (first non-comment line) with "
        "'--require-hashes' so the file is self-enforcing"
    )


def test_every_pin_has_a_valid_sha256() -> None:
    """Every ``name==version`` in the hashed lock carries at least one
    64-hex sha256 — a decorative hash-less entry would silently downgrade the
    control to a plain version pin."""
    entries = _parse_hashed_lock()
    assert len(entries) >= 100, (
        f"hashed lock parse yielded suspiciously few pins ({len(entries)}) — "
        "format drifted?"
    )
    hashless = [name for name, (_v, hs) in entries.items() if not hs]
    assert not hashless, (
        "hash-pinned lock entries with NO --hash (would install unverified "
        f"under --require-hashes... in fact pip rejects the file): {sorted(hashless)}"
    )


def test_no_active_editable_or_vcs_lines() -> None:
    """Editable / VCS requirements make pip reject the whole ``--require-hashes``
    file. They may appear ONLY inside the commented exclusion block, never as
    active requirement lines."""
    offenders: list[str] = []
    for raw in _HASHED_LOCK.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-e") or line.startswith("git+"):
            offenders.append(raw)
        elif " @ " in line and ("git+" in line or "://" in line):
            offenders.append(raw)
    assert not offenders, (
        "active editable/VCS lines in the hash-pinned lock — pip would reject "
        f"the entire --require-hashes file: {offenders}"
    )


def test_hashed_and_version_locks_agree_on_versions() -> None:
    """The hashed lock pins exactly the PyPI distributions of the version-pinned
    reproduction lock, at the same versions. Catches the drift where a version
    is bumped in one lock but the other is not regenerated."""
    version_pins = _version_lock_pins()
    hashed = {name: v for name, (v, _h) in _parse_hashed_lock().items()}

    only_version = sorted(set(version_pins) - set(hashed))
    only_hashed = sorted(set(hashed) - set(version_pins))
    mismatched = sorted(
        f"{n}: version-lock {version_pins[n]} vs hashed-lock {hashed[n]}"
        for n in set(version_pins) & set(hashed)
        if version_pins[n] != hashed[n]
    )
    assert not (only_version or only_hashed or mismatched), (
        "hash-pinned lock has drifted from the version-pinned reproduction "
        "lock (regenerate with scripts/generate_hashed_lock.py):\n"
        f"  in version lock but not hashed: {only_version}\n"
        f"  in hashed lock but not version: {only_hashed}\n"
        f"  version mismatch: {mismatched}"
    )


def test_every_declared_runtime_dependency_is_hash_pinned() -> None:
    """The security-relevant assertion: every distribution the runtime actually
    imports (pyproject ``[project] dependencies``) is hash-covered in the lock
    at a version satisfying its declared specifier. A declared dependency
    missing from the hashed lock is an un-verified runtime supply-chain edge."""
    hashed = {name: (v, hs) for name, (v, hs) in _parse_hashed_lock().items()}
    problems: list[str] = []
    for req in _declared_dependencies():
        name = _normalize(req.name)
        if name not in hashed:
            problems.append(f"{req.name}: declared runtime dep NOT in hashed lock")
            continue
        version, hs = hashed[name]
        if not hs:
            problems.append(f"{req.name}: in hashed lock but has no --hash")
        if not req.specifier.contains(version, prereleases=True):
            problems.append(
                f"{req.name}: hashed lock pins {version} which does not satisfy "
                f"declared specifier '{req.specifier}'"
            )
    assert not problems, (
        "declared runtime dependencies are not fully hash-covered:\n  "
        + "\n  ".join(problems)
    )


def test_tamper_requires_breaking_all_hashes_note() -> None:
    """Guard-the-guard, documenting pip's any-match semantics for whoever writes
    a live tamper test. ``--require-hashes`` accepts a downloaded file if its
    digest matches ANY listed ``--hash`` for that pin (the lock records every
    platform wheel + sdist digest of a version). So a faithful 'tampered
    artifact fails closed' proof must invalidate EVERY hash of the chosen dist,
    not just one — breaking a single hash still installs. This test asserts the
    multi-hash reality the note depends on actually exists in the lock."""
    multi = [name for name, (_v, hs) in _parse_hashed_lock().items() if len(hs) >= 2]
    assert multi, (
        "expected at least one dist with >=2 recorded hashes (multiple "
        "published files) — the any-match note assumes this shape"
    )
