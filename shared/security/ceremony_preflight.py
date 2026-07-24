"""Ceremony preflight check for the EA-4 on-chip ceremony (Sprint 15).

Run this BEFORE the provisioning ceremony to confirm every prerequisite is
present on this machine.  This script is **READ-ONLY** — it never creates,
modifies, or deletes a key, certificate, or file.

Usage::

    python -m shared.security.ceremony_preflight

Output: a human-readable ✓/✗ checklist that a non-developer can read, plus
a one-line bottom-line verdict ("READY for production boot" / "NOT READY").

Checks performed:
  1. TPM availability  (tpm_sealer — RSA seal path)
  2. TPM availability  (tpm_signer — ECDSA sign path)
  3. DEK seal key present  (BlarAI-DEKSeal)
  4. Audit signing key present  (BlarAI-Audit-Signing-Key-v1)
  5. JWT signing key present  (BlarAI-PA-JWT-Signing)
  6. Manifest signing key present  (BlarAI-Manifest-Signing) [FUT-04 / ADR-018]
  7. DEK keystore file present  (BLARAI_DEK_KEYSTORE / default path)
  8. PA public certificate present  (certs/pa_public.pem)
  9. Production manifest present + digest matches the real model binary
     (if the model file exists; otherwise "model not found" advisory)

Safety: this module makes NO calls that could mutate state.  key_exists()
and is_available() are read-only probes; no ensure_key(), no file writes.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants (mirroring provision_dek_keystore.py for consistency)
# ---------------------------------------------------------------------------

_DEK_SEAL_KEY = "BlarAI-DEKSeal"
_AUDIT_KEY = "BlarAI-Audit-Signing-Key-v1"
_JWT_KEY = "BlarAI-PA-JWT-Signing"
# FUT-04 / ADR-018: manifest-signing key (staged — off by default until the
# LA runs the provisioning ceremony and flips require_signed_manifest=true).
_MANIFEST_SIGNING_KEY = "BlarAI-Manifest-Signing"

# The model-dir and manifest path must match services/.../config/default.toml.
# Both PA and AO point at the same model dir; we read the PA config as
# authoritative for the preflight.  Hard-coded here to avoid importing the
# full service config stack (which may not be present in a bare ceremony env).
_MODEL_DIR = Path("models/qwen3-14b/openvino-int4-gpu")
_MANIFEST_RELATIVE = _MODEL_DIR / "manifest.json"

# Primary model binary — the one the manifest records a digest for.
_PRIMARY_MODEL_BIN = _MODEL_DIR / "openvino_model.bin"

# FUT-05 / #107 + #917 — the SERVED-AND-ENFORCED speculative-decoding DRAFT model
# dirs, each signed with the SAME BlarAI-Manifest-Signing key and each verified by a
# real code path (a manifest no code checks must never appear as ceremony
# "coverage"):
#   - qwen3-0.6b-pruned-6l/openvino-int8-gpu — the shared-pipeline draft
#     (DRAFT_MODEL_OV_PATH), verified by build_shared_pipeline (#107).
#   - qwen3-0.6b/openvino-int4-gpu — the PA standalone/fallback draft, verified by
#     gpu_inference._verify_draft_integrity (#917).
# Each dir is gitignored, so an absent draft is INFO (advisory), never a hard FAIL —
# only a PRESENT draft whose weight digest mismatches its manifest is a FAIL.
_DRAFT_MODEL_DIRS: tuple[Path, ...] = (
    Path("models/qwen3-0.6b-pruned-6l/openvino-int8-gpu"),
    Path("models/qwen3-0.6b/openvino-int4-gpu"),
)

# certs/pa_public.pem — produced by the JWT-key provisioning ceremony.
_PA_PUBLIC_PEM = Path("certs/pa_public.pem")

# DEK keystore path: honour BLARAI_DEK_KEYSTORE env var if set (matching
# the convention from provision_dek_keystore._default_keystore_path()).
def _default_keystore_path() -> Path:
    local = os.environ.get("BLARAI_DEK_KEYSTORE", "")
    if local:
        return Path(local)
    localappdata = os.environ.get("LOCALAPPDATA", "")
    if localappdata:
        return Path(localappdata) / "BlarAI" / "dek_keystore.json"
    return Path.home() / ".local" / "share" / "BlarAI" / "dek_keystore.json"


# ---------------------------------------------------------------------------
# Visual helpers
# ---------------------------------------------------------------------------

_PASS = "[  OK  ]"
_FAIL = "[ FAIL ]"
_WARN = "[ WARN ]"
_INFO = "[ INFO ]"


def _line(symbol: str, label: str, detail: str = "") -> str:
    base = f"  {symbol}  {label}"
    if detail:
        base += f"\n           {detail}"
    return base


def _header(title: str) -> str:
    width = 70
    bar = "=" * width
    return f"\n{bar}\n  {title}\n{bar}\n"


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _check_tpm_sealer() -> tuple[bool, str]:
    """Check TPM sealer (RSA-2048 OAEP seal path) availability."""
    try:
        from shared.security import tpm_sealer
        ok = tpm_sealer.is_available()
        if ok:
            return True, _line(_PASS, "TPM sealer (RSA-2048 OAEP)        — available")
        return False, _line(
            _FAIL,
            "TPM sealer (RSA-2048 OAEP)        — NOT available",
            "The ceremony must run on this machine's deployment hardware "
            "(TPM 2.0 required).",
        )
    except Exception as exc:  # pragma: no cover — import-level failure
        return False, _line(_FAIL, "TPM sealer                         — import error", str(exc))


def _check_tpm_signer() -> tuple[bool, str]:
    """Check TPM signer (ECDSA P-256 signing path) availability."""
    try:
        from shared.security import tpm_signer
        ok = tpm_signer.is_available()
        if ok:
            return True, _line(_PASS, "TPM signer (ECDSA P-256)           — available")
        return False, _line(
            _FAIL,
            "TPM signer (ECDSA P-256)           — NOT available",
            "The ceremony must run on this machine's deployment hardware "
            "(TPM 2.0 required).",
        )
    except Exception as exc:  # pragma: no cover — import-level failure
        return False, _line(_FAIL, "TPM signer                         — import error", str(exc))


def _check_key(
    key_name: str,
    label: str,
    *,
    is_signer: bool,
) -> tuple[bool, str]:
    """Check whether a named TPM key (signer or sealer) exists.

    Returns (True, ok_line) if present, (False, fail_line) otherwise.
    If the TPM is unavailable the check is inconclusive — marked WARN.
    """
    try:
        if is_signer:
            from shared.security import tpm_signer as mod
        else:
            from shared.security import tpm_sealer as mod  # type: ignore[assignment]

        if not mod.is_available():
            return False, _line(
                _WARN,
                f"{label:<35}— TPM unavailable (cannot probe)",
                "Resolve TPM availability first.",
            )
        exists = mod.key_exists(key_name)
        if exists:
            return True, _line(_PASS, f"{label:<35}— present ({key_name})")
        return False, _line(
            _FAIL,
            f"{label:<35}— NOT FOUND",
            f"Run the provisioning ceremony to create key '{key_name}'.",
        )
    except Exception as exc:
        return False, _line(_FAIL, f"{label:<35}— error probing key", str(exc))


def _check_keystore(keystore_path: Path) -> tuple[bool, str]:
    """Check that the DEK keystore file exists at the expected path."""
    if keystore_path.exists():
        return True, _line(
            _PASS,
            "DEK keystore file                  — present",
            str(keystore_path),
        )
    return False, _line(
        _FAIL,
        "DEK keystore file                  — NOT FOUND",
        f"Expected: {keystore_path}\n"
        "           Run: python -m shared.security.provision_dek_keystore",
    )


def _check_pa_public_pem() -> tuple[bool, str]:
    """Check that certs/pa_public.pem exists."""
    if _PA_PUBLIC_PEM.exists():
        return True, _line(_PASS, "certs/pa_public.pem                — present")
    return False, _line(
        _FAIL,
        "certs/pa_public.pem                — NOT FOUND",
        "Run: python -m shared.security.provision_signing_key  "
        "(JWT key ceremony)",
    )


def _check_manifest() -> tuple[bool, str]:
    """Check manifest presence and, if the model binary exists, its digest.

    Three outcomes:
      - Model binary found + digest matches manifest  → PASS
      - Model binary NOT found                        → INFO advisory (not a
            FAIL — the manifest can be pre-staged without the model present)
      - Manifest missing                              → FAIL
      - Manifest present but digest does not match    → FAIL
    """
    if not _MANIFEST_RELATIVE.exists():
        return False, _line(
            _FAIL,
            "Production manifest                — NOT FOUND",
            f"Expected: {_MANIFEST_RELATIVE}\n"
            "           Run: python -m shared.models.stage_production_manifest",
        )

    # Manifest exists — check for the stub notice (EA-3 placeholder).
    import json as _json

    try:
        with _MANIFEST_RELATIVE.open("r", encoding="utf-8") as fh:
            data = _json.load(fh)
    except Exception as exc:
        return False, _line(_FAIL, "Production manifest                — unreadable", str(exc))

    if "_stub_notice" in data:
        return False, _line(
            _FAIL,
            "Production manifest                — contains EA-3 stub placeholder",
            "Run: python -m shared.models.stage_production_manifest  "
            "(to compute real digests)",
        )

    # If the primary model binary is present, verify its digest.
    if not _PRIMARY_MODEL_BIN.exists():
        # Manifest is present and not a stub, but model binary is absent.
        # This is informational: the manifest may have been staged on another
        # machine and copied here before the model download.
        return True, _line(
            _INFO,
            "Production manifest                — present (digest not verified)",
            f"Model binary not found: {_PRIMARY_MODEL_BIN}\n"
            "           Digest match will be verified on first production boot.",
        )

    # Model binary present — compute and compare.
    try:
        from shared.models.weight_integrity import compute_sha256, load_manifest

        digests = load_manifest(_MANIFEST_RELATIVE)
        if digests is None:
            return False, _line(
                _FAIL,
                "Production manifest                — failed to parse",
                f"Path: {_MANIFEST_RELATIVE}",
            )

        model_filename = _PRIMARY_MODEL_BIN.name
        expected = digests.get(model_filename)
        if expected is None:
            return False, _line(
                _FAIL,
                "Production manifest                — missing entry for model binary",
                f"Manifest has no entry for '{model_filename}'.  "
                "Re-run the manifest stager.",
            )

        computed = compute_sha256(_PRIMARY_MODEL_BIN)
        if computed == expected:
            return True, _line(
                _PASS,
                "Production manifest                — digest verified",
                f"Model: {model_filename}  digest: {computed[:16]}…",
            )
        return False, _line(
            _FAIL,
            "Production manifest                — DIGEST MISMATCH",
            f"Computed : {computed}\n"
            f"           Expected : {expected}\n"
            "           The model file may have been corrupted or replaced.  "
            "Re-run the stager.",
        )
    except Exception as exc:
        return False, _line(
            _FAIL, "Production manifest                — error during verify", str(exc)
        )


def _check_draft_manifests() -> list[tuple[bool, str]]:
    """Check each SERVED speculative-decoding draft manifest (FUT-05 / #107).

    One line per draft dir in ``_DRAFT_MODEL_DIRS``. Non-fatal by design (the
    drafts are NON-AUTHORITATIVE and gitignored):

      - Draft dir / manifest absent            → INFO (not on this box)
      - Manifest present, no ``.sig`` yet       → INFO advisory ("not yet signed";
            require_signed_draft_manifest is dormant until the ceremony signs it)
      - Manifest present + ``.sig`` present      → INFO ("signed"); if the weight
            binary is present its digest is verified — a MISMATCH is a FAIL
      - Manifest present + weight present, digest mismatch → FAIL (real integrity
            problem, surfaced even while the enforcement flag is dormant)
    """
    from shared.models.weight_integrity import compute_sha256, load_manifest

    results: list[tuple[bool, str]] = []
    for model_dir in _DRAFT_MODEL_DIRS:
        label = f"Draft manifest ({model_dir.parent.name}/{model_dir.name})"
        manifest = model_dir / "manifest.json"
        sig = model_dir / "manifest.json.sig"
        bin_path = model_dir / "openvino_model.bin"

        if not manifest.exists():
            results.append(
                (True, _line(_INFO, f"{label:<35}— absent (gitignored / not on this box)"))
            )
            continue

        signed = sig.exists()
        sig_note = "signed (.sig present)" if signed else "NOT yet signed (.sig absent — dormant)"

        # Verify the primary weight digest if the binary is present.
        if bin_path.exists():
            try:
                digests = load_manifest(manifest)
                if digests is None:
                    results.append(
                        (False, _line(_FAIL, f"{label:<35}— manifest failed to parse", str(manifest)))
                    )
                    continue
                expected = digests.get(bin_path.name)
                if expected is None:
                    results.append(
                        (
                            False,
                            _line(
                                _FAIL,
                                f"{label:<35}— no digest for {bin_path.name}",
                                "Re-run the manifest stager for this draft.",
                            ),
                        )
                    )
                    continue
                computed = compute_sha256(bin_path)
                if computed == expected:
                    results.append(
                        (True, _line(_INFO, f"{label:<35}— {sig_note}; digest verified"))
                    )
                else:
                    results.append(
                        (
                            False,
                            _line(
                                _FAIL,
                                f"{label:<35}— DIGEST MISMATCH",
                                f"Computed {computed[:16]}… != expected {expected[:16]}…. "
                                "The draft weight may be corrupted/replaced; re-stage.",
                            ),
                        )
                    )
            except Exception as exc:  # noqa: BLE001 — advisory check, never a hard crash
                results.append(
                    (False, _line(_FAIL, f"{label:<35}— error during verify", str(exc)))
                )
        else:
            # Manifest present but the weight is absent (gitignored) — advisory only.
            results.append(
                (True, _line(_INFO, f"{label:<35}— {sig_note}; weight absent (digest not verified)"))
            )
    return results


# ---------------------------------------------------------------------------
# Main preflight runner
# ---------------------------------------------------------------------------


def run_preflight() -> int:
    """Execute all preflight checks and print a clear checklist.

    Returns 0 if all hard-fail checks pass, 1 otherwise.
    """
    print(_header("BlarAI Ceremony Preflight Check"))
    print("  Checking every prerequisite for the EA-4 on-chip ceremony.")
    print("  This check is READ-ONLY — nothing is created or changed.\n")

    keystore_path = _default_keystore_path()

    checks: list[tuple[bool, str]] = []

    # --- TPM availability (both paths) ---
    checks.append(_check_tpm_sealer())
    checks.append(_check_tpm_signer())

    # --- TPM key existence ---
    checks.append(_check_key(_DEK_SEAL_KEY, "DEK seal key", is_signer=False))
    checks.append(_check_key(_AUDIT_KEY, "Audit signing key", is_signer=True))
    checks.append(_check_key(_JWT_KEY, "JWT signing key", is_signer=True))
    checks.append(
        _check_key(
            _MANIFEST_SIGNING_KEY,
            "Manifest signing key",
            is_signer=True,
        )
    )

    # --- File checks ---
    checks.append(_check_keystore(keystore_path))
    checks.append(_check_pa_public_pem())
    checks.append(_check_manifest())
    # FUT-05 / #107 — the served spec-decode draft manifests (one line each;
    # non-fatal on absence, FAIL only on a present-but-mismatched draft weight).
    checks.extend(_check_draft_manifests())

    # --- Print results ---
    print("  Prerequisite Checklist")
    print("  " + "-" * 64)
    for _, line in checks:
        print(line)

    # --- Bottom-line verdict ---
    # INFO lines from _check_manifest are not failures.
    failed = [label for ok, label in checks if not ok and _INFO not in label]
    passed_or_info = len(checks) - len(failed)

    print()
    print("  " + "-" * 64)
    if not failed:
        print(
            "  RESULT:  READY for production boot\n"
            "           All prerequisites are present.  You may proceed with\n"
            "           the EA-4 on-chip ceremony.\n"
        )
        return 0
    else:
        print(
            f"  RESULT:  NOT READY — {len(failed)} prerequisite(s) need attention.\n"
            "           Fix the FAIL items above and re-run this check.\n"
        )
        return 1


def main() -> int:
    """CLI entrypoint."""
    return run_preflight()


if __name__ == "__main__":
    raise SystemExit(main())
