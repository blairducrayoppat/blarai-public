"""
Shared mmap Weight Integrity Verification
==========================================
Red Team ISSUE-003: Shared mmap weights create an integrity coupling
between the Policy Agent and all consumers.

Three-layer mitigation:
  1. Boot-time SHA-256 verification against Pluton-sealed Known-Good Manifest.
  2. Event-triggered runtime re-verification before every adjudication cycle.
  3. Hypervisor-enforced CoW prevention (read-only EPT page protections).

This module implements layers 1 and 2. Layer 3 is hypervisor-configured.

Manifest format (JSON):
  {
    "version": "1.0.0",
    "digests": {
        "policy_classifier.bin": "sha256hexdigest..."
    }
  }

Security:
  - No external network calls.
  - Fail-Closed: verification failure blocks all inference.
  - SHA-256 digest compared against locally-stored manifest only.

Multi-entry sweep (Sprint 16, SDV #2 / #106 partial):
  ``verify_all_manifest_entries`` extends the single-file check to the
  full manifest: every ``.bin`` in the manifest is hashed and compared;
  any extra ``.bin`` files present in the model directory but absent from
  the manifest also cause a fail-closed rejection. This is the function
  used in both PA and AO ``load_model()`` paths as of Sprint 16.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from shared.models.manifest_signer import (
    MANIFEST_SIGNING_KEY_NAME,
    verify_manifest_signature,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IntegrityCheckResult:
    """Result of a weight file integrity verification."""

    verified: bool
    """True if the SHA-256 digest matches the known-good manifest."""

    computed_digest: str
    """SHA-256 hex digest of the weight file."""

    expected_digest: str
    """Expected digest from the manifest."""

    model_path: str
    """Path to the verified weight file."""

    error: str | None = None
    """Human-readable error if verification failed."""


def compute_sha256(file_path: str | Path, chunk_size: int = 65_536) -> str:
    """Compute SHA-256 hex digest of a file.

    Args:
        file_path: Path to the file.
        chunk_size: Read buffer size in bytes.

    Returns:
        Lowercase hex digest string.
    """
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def load_manifest(manifest_path: str | Path) -> dict[str, str] | None:
    """Load the Known-Good Manifest JSON.

    Expected format::

        {
            "version": "1.0.0",
            "digests": {
                "model_file.bin": "sha256hexdigest"
            }
        }

    Args:
        manifest_path: Path to the JSON manifest file.

    Returns:
        Dict mapping filename → expected SHA-256 hex digest (lowercased).
        None on any error (Fail-Closed).
    """
    try:
        path = Path(manifest_path)
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        digests = data.get("digests")
        if not isinstance(digests, dict):
            logger.error("Manifest missing 'digests' dict: %s", manifest_path)
            return None
        # Validate all keys and values are strings
        for key, value in digests.items():
            if not isinstance(key, str) or not isinstance(value, str):
                logger.error("Manifest contains non-string entry: %s", key)
                return None
        # Normalize digests to lowercase
        return {k: v.lower() for k, v in digests.items()}
    except (OSError, json.JSONDecodeError, TypeError, KeyError) as e:
        logger.error("Failed to load manifest %s: %s", manifest_path, e)
        return None


def load_manifest_verified(
    manifest_path: str | Path,
    *,
    require_signed: bool,
    key_name: str = MANIFEST_SIGNING_KEY_NAME,
) -> dict[str, str] | None:
    """Load the Known-Good Manifest, optionally verifying its TPM signature first.

    This is the signature-aware replacement for bare ``load_manifest`` calls in
    the boot path and per-request re-hash path.  It gates on the
    ``require_signed_manifest`` config flag so the current air-gapped boot is
    not broken while building the capability.

    Args:
        manifest_path: Path to the ``manifest.json`` file.
        require_signed: Sourced from config flag ``require_signed_manifest``.
            ``True`` → signature MUST be present and valid; any failure returns
            ``None`` (FAIL-CLOSED).  ``False`` → missing signature is permitted
            (a WARNING is emitted); invalid signature (file present but wrong)
            is still FAIL-CLOSED to prevent silent downgrade attacks.
        key_name: Persisted TPM key name (default: ``MANIFEST_SIGNING_KEY_NAME``).

    Returns:
        Dict mapping filename → expected SHA-256 hex digest (lowercased) on
        success, or ``None`` on any failure (Fail-Closed).

    Security invariant:
        When ``require_signed=True``, a tampered manifest (either the JSON
        content or its ``.sig`` file) will always cause this function to return
        ``None``.  A missing ``.sig`` when ``require_signed=True`` also returns
        ``None``.  The ONLY case where an unsigned manifest proceeds is
        ``require_signed=False`` **and** no ``.sig`` file exists — and that case
        emits a WARNING so the unsigned state is never silent.
    """
    path = Path(manifest_path)

    # Step 1: Verify signature BEFORE reading manifest content.
    # This ensures an attacker who can write both files cannot craft a
    # consistent (manifest, sig) pair using only local write access — they
    # would also need the non-exportable TPM private key.
    sig_ok = verify_manifest_signature(path, require_signed=require_signed, key_name=key_name)
    if not sig_ok:
        logger.error(
            "Manifest signature verification failed; refusing to load manifest: %s",
            path,
        )
        return None

    # Step 2: Load and validate the manifest content (unchanged from bare load_manifest).
    return load_manifest(path)


def verify_weight_integrity(
    model_path: str | Path,
    manifest_path: str | Path,
    *,
    require_signed: bool = False,
) -> IntegrityCheckResult:
    """Verify a model weight file against the Known-Good Manifest.

    Verification steps:
      1. Load manifest JSON from ``manifest_path`` (TPM-signature-checked when
         ``require_signed`` is set).
      2. Look up the model filename in the manifest's ``digests`` dict.
      3. Compute SHA-256 of the weight file at ``model_path``.
      4. Compare computed digest against expected digest.

    Args:
        model_path: Path to the .bin weight file.
        manifest_path: Path to the JSON manifest containing expected digests.
        require_signed: When ``True`` the manifest is loaded through the
            signature-checked ``load_manifest_verified`` path, so the per-request
            re-hash trusts a signature-verified digest set rather than a raw
            on-disk ``manifest.json`` an attacker could rewrite alongside a
            tampered weight (#571). Sourced from
            ``[security].require_signed_manifest``. Default ``False`` keeps every
            existing caller (boot sweep, tests) byte-identical.

    Returns:
        IntegrityCheckResult. On ANY error, verified=False (Fail-Closed).
    """
    model_path = Path(model_path)

    # Step 1: Load manifest. When require_signed is set (production posture), go
    # through the TPM-signature-checked loader so a manifest.json rewritten at
    # runtime alongside a tampered weight is rejected — closing the per-request
    # gap where the boot gate was signed but the re-hash was not (#571). The
    # default keeps the unsigned load byte-identical for existing callers.
    digests = (
        load_manifest_verified(manifest_path, require_signed=require_signed)
        if require_signed
        else load_manifest(manifest_path)
    )
    if digests is None:
        return IntegrityCheckResult(
            verified=False,
            computed_digest="",
            expected_digest="",
            model_path=str(model_path),
            error=f"Failed to load manifest: {manifest_path}",
        )

    # Step 2: Look up expected digest by filename
    filename = model_path.name
    expected = digests.get(filename)
    if expected is None:
        return IntegrityCheckResult(
            verified=False,
            computed_digest="",
            expected_digest="",
            model_path=str(model_path),
            error=f"Model file '{filename}' not found in manifest.",
        )

    # Step 3: Compute actual digest
    try:
        computed = compute_sha256(model_path)
    except (OSError, IOError) as e:
        return IntegrityCheckResult(
            verified=False,
            computed_digest="",
            expected_digest=expected,
            model_path=str(model_path),
            error=f"IO error reading weight file: {e}",
        )

    # Step 4: Compare
    verified = computed == expected
    error = (
        None
        if verified
        else f"Digest mismatch: computed={computed}, expected={expected}"
    )

    logger.info(
        "Weight integrity check: model=%s, verified=%s",
        model_path.name,
        verified,
    )

    return IntegrityCheckResult(
        verified=verified,
        computed_digest=computed,
        expected_digest=expected,
        model_path=str(model_path),
        error=error,
    )


@dataclass(frozen=True)
class ManifestSweepResult:
    """Result of a full manifest sweep across all .bin entries.

    Aggregates per-file results from ``verify_all_manifest_entries``.
    A single failure in any entry causes ``all_verified=False``.
    """

    all_verified: bool
    """True only when every manifest entry passes and no extra .bin files exist."""

    per_file: list[IntegrityCheckResult]
    """One entry per .bin checked (manifest entries + any extra .bin found)."""

    error: str | None = None
    """Short summary of the first failure encountered, or None on full pass."""


def verify_all_manifest_entries(
    model_dir: str | Path,
    manifest_path: str | Path,
) -> ManifestSweepResult:
    """Verify every .bin file listed in the manifest AND reject extra .bin files.

    FLAT, ``.bin``-ONLY — DO NOT EXTEND to ``.xml`` / ``model_index.json``: the
    signed production 14B/PA/draft manifests are ``.bin``-only, so requiring the
    topology/index here would refuse the next real boot (re-covering them needs a
    re-stage + re-sign ceremony, a separate LA-present event). The nested sibling
    :func:`verify_all_manifest_entries_nested` carries the ``.xml`` +
    ``model_index.json`` coverage for the diffusers-OV (UC-010) layout.

    This is the load-time sweep for both PA and AO ``load_model()`` paths
    (Sprint 16, SDV criterion #2 / #106 partial).  The check is fail-closed on
    any of these conditions:

    - The manifest cannot be loaded.
    - A .bin listed in the manifest is missing from ``model_dir``.
    - A .bin listed in the manifest has a digest that does not match.
    - A .bin present in ``model_dir`` is NOT listed in the manifest (extra file).

    Rationale for extra-file rejection: an attacker who swaps the primary
    weight binary and drops a new filename into the model directory would not
    be caught by digest comparison alone — only by also checking that the
    directory contains no .bin files the manifest has not accounted for.

    Args:
        model_dir: Directory containing .bin weight files.
        manifest_path: Path to the JSON manifest containing expected digests.

    Returns:
        ``ManifestSweepResult``.  ``all_verified=False`` on any failure
        (Fail-Closed).
    """
    model_dir = Path(model_dir)
    results: list[IntegrityCheckResult] = []

    # Step 1: Load the manifest.
    digests = load_manifest(manifest_path)
    if digests is None:
        return ManifestSweepResult(
            all_verified=False,
            per_file=[],
            error=f"Failed to load manifest: {manifest_path}",
        )

    # Step 2: Verify every entry listed in the manifest.
    first_error: str | None = None
    for filename, expected in digests.items():
        bin_path = model_dir / filename
        if not bin_path.exists():
            err = f"Manifest entry '{filename}' not found in model directory: {model_dir}"
            result = IntegrityCheckResult(
                verified=False,
                computed_digest="",
                expected_digest=expected,
                model_path=str(bin_path),
                error=err,
            )
            results.append(result)
            if first_error is None:
                first_error = err
            logger.error("Weight sweep FAIL (missing): %s", err)
            continue

        try:
            computed = compute_sha256(bin_path)
        except (OSError, IOError) as e:
            err = f"IO error reading '{filename}': {e}"
            result = IntegrityCheckResult(
                verified=False,
                computed_digest="",
                expected_digest=expected,
                model_path=str(bin_path),
                error=err,
            )
            results.append(result)
            if first_error is None:
                first_error = err
            logger.error("Weight sweep FAIL (IO): %s", err)
            continue

        ok = computed == expected.lower()
        err_msg = (
            None
            if ok
            else f"Digest mismatch for '{filename}': computed={computed}, expected={expected}"
        )
        result = IntegrityCheckResult(
            verified=ok,
            computed_digest=computed,
            expected_digest=expected,
            model_path=str(bin_path),
            error=err_msg,
        )
        results.append(result)
        if err_msg is not None and first_error is None:
            first_error = err_msg
            logger.error("Weight sweep FAIL (tampered): %s", err_msg)
        else:
            logger.info("Weight sweep OK: %s", filename)

    # Step 3: Detect extra .bin files not listed in the manifest.
    manifest_filenames: frozenset[str] = frozenset(digests.keys())
    try:
        on_disk_bins = sorted(p.name for p in model_dir.glob("*.bin"))
    except OSError as e:
        err = f"Cannot enumerate model directory '{model_dir}': {e}"
        return ManifestSweepResult(
            all_verified=False,
            per_file=results,
            error=first_error or err,
        )

    for extra_name in on_disk_bins:
        if extra_name not in manifest_filenames:
            err = (
                f"Extra .bin file '{extra_name}' is present in model directory "
                f"but NOT listed in the manifest — refusing to load (fail-closed)."
            )
            result = IntegrityCheckResult(
                verified=False,
                computed_digest="",
                expected_digest="",
                model_path=str(model_dir / extra_name),
                error=err,
            )
            results.append(result)
            if first_error is None:
                first_error = err
            logger.error("Weight sweep FAIL (extra file): %s", err)

    all_ok = first_error is None
    return ManifestSweepResult(
        all_verified=all_ok,
        per_file=results,
        error=first_error,
    )


def verify_all_manifest_entries_nested(
    model_dir: str | Path,
    manifest_path: str | Path,
    *,
    require_signed: bool = False,
) -> ManifestSweepResult:
    """Verify a NESTED-layout model's weights + topology against the manifest.

    The flat :func:`verify_all_manifest_entries` globs ``*.bin`` in the TOP
    directory only and keys the manifest by the bare filename — correct for the
    single-binary LLM layout (one ``openvino_model.bin``), but WRONG for a
    diffusers-OpenVINO diffusion model (UC-010 / ADR-033), where the weights
    live in subdirectories (``unet/openvino_model.bin``,
    ``vae_decoder/openvino_model.bin``, …) and the bare name
    ``openvino_model.bin`` repeats across several subdirs (a key collision).

    This sibling treats every manifest KEY as a POSIX-style RELATIVE PATH under
    ``model_dir`` (``"unet/openvino_model.bin"``) and walks the tree. It reuses
    the proven primitives — :func:`load_manifest` (same JSON shape + lowercasing)
    and :func:`compute_sha256` — so the hashing/comparison logic is not
    re-implemented. Coverage extends beyond ``.bin`` weights to the OpenVINO
    ``.xml`` topology files AND ``model_index.json`` (UC-010 WS1), so a
    write-capable local actor cannot swap the compute graph (``.xml``) or the
    pipeline index past a ``.bin``-only digest list. Fail-closed on any of:

    - The manifest (or, when ``require_signed``, its TPM ``.sig``) cannot be
      loaded / signature-verified.
    - A relative path listed in the manifest is missing from ``model_dir``.
    - A listed entry has a digest that does not match.
    - A ``.bin`` / ``.xml`` / ``model_index.json`` present ANYWHERE under
      ``model_dir`` (recursive) is NOT listed in the manifest (extra-file
      rejection — the swap-and-drop defense, extended to subdirectories and to
      the topology/index files). ``manifest.json`` itself is not swept.

    A manifest key is rejected fail-closed if it escapes ``model_dir`` (``..``
    or an absolute path) so a tampered manifest cannot point the verifier at an
    arbitrary file.

    Args:
        model_dir: Root directory of the nested model layout.
        manifest_path: Path to the JSON manifest. Keys are relative POSIX paths.
        require_signed: When True the manifest MUST carry a valid TPM signature
            (``.sig``) — the load routes through :func:`load_manifest_verified`
            and a missing/invalid signature fails closed
            (``all_verified=False``). Default False keeps every existing nested
            caller byte-identical; the image path passes
            ``cfg.require_signed_manifest`` (FUT-04 parity with the signed 14B).

    Returns:
        ``ManifestSweepResult``. ``all_verified=False`` on any failure
        (Fail-Closed).
    """
    model_dir = Path(model_dir)
    results: list[IntegrityCheckResult] = []

    digests = (
        load_manifest_verified(manifest_path, require_signed=require_signed)
        if require_signed
        else load_manifest(manifest_path)
    )
    if digests is None:
        return ManifestSweepResult(
            all_verified=False,
            per_file=[],
            error=(
                f"Failed to load manifest (or signature invalid/missing): {manifest_path}"
                if require_signed
                else f"Failed to load manifest: {manifest_path}"
            ),
        )

    first_error: str | None = None
    model_dir_resolved = model_dir.resolve()

    def _safe_join(rel: str) -> Path | None:
        """Resolve *rel* under model_dir; None if it escapes the root."""
        candidate = (model_dir / rel).resolve()
        try:
            candidate.relative_to(model_dir_resolved)
        except ValueError:
            return None
        return candidate

    # Step 1: Verify every relative-path entry listed in the manifest.
    for rel_name, expected in digests.items():
        bin_path = _safe_join(rel_name)
        if bin_path is None:
            err = (
                f"Manifest entry '{rel_name}' escapes the model directory "
                f"(traversal/absolute) — refusing (fail-closed)."
            )
            results.append(
                IntegrityCheckResult(
                    verified=False, computed_digest="", expected_digest=expected,
                    model_path=str(model_dir / rel_name), error=err,
                )
            )
            if first_error is None:
                first_error = err
            logger.error("Weight sweep (nested) FAIL (traversal): %s", err)
            continue
        if not bin_path.exists():
            err = (
                f"Manifest entry '{rel_name}' not found in model directory: "
                f"{model_dir}"
            )
            results.append(
                IntegrityCheckResult(
                    verified=False, computed_digest="", expected_digest=expected,
                    model_path=str(bin_path), error=err,
                )
            )
            if first_error is None:
                first_error = err
            logger.error("Weight sweep (nested) FAIL (missing): %s", err)
            continue
        try:
            computed = compute_sha256(bin_path)
        except (OSError, IOError) as e:
            err = f"IO error reading '{rel_name}': {e}"
            results.append(
                IntegrityCheckResult(
                    verified=False, computed_digest="", expected_digest=expected,
                    model_path=str(bin_path), error=err,
                )
            )
            if first_error is None:
                first_error = err
            logger.error("Weight sweep (nested) FAIL (IO): %s", err)
            continue
        ok = computed == expected.lower()
        err_msg = (
            None
            if ok
            else f"Digest mismatch for '{rel_name}': computed={computed}, expected={expected}"
        )
        results.append(
            IntegrityCheckResult(
                verified=ok, computed_digest=computed, expected_digest=expected,
                model_path=str(bin_path), error=err_msg,
            )
        )
        if err_msg is not None and first_error is None:
            first_error = err_msg
            logger.error("Weight sweep (nested) FAIL (tampered): %s", err_msg)
        elif ok:
            logger.info("Weight sweep (nested) OK: %s", rel_name)

    # Step 2: Detect extra weight/topology files (recursive) not listed in the
    # manifest. Covers .bin weights AND the OpenVINO .xml topology files AND
    # model_index.json — so a write-capable actor cannot swap the compute graph
    # (the .xml) or the pipeline index past a .bin-only digest list (UC-010 WS1,
    # nested path only; the flat sibling stays .bin-only — see its docstring).
    # NOTE: manifest.json itself is NOT swept (only model_index.json by exact
    # name), so the manifest sitting in model_dir is never mistaken for an extra.
    manifest_rel: frozenset[str] = frozenset(
        Path(k).as_posix() for k in digests.keys()
    )
    try:
        swept: set[Path] = set()
        swept.update(model_dir.rglob("*.bin"))
        swept.update(model_dir.rglob("*.xml"))
        swept.update(model_dir.rglob("model_index.json"))
        on_disk = sorted(p.relative_to(model_dir).as_posix() for p in swept)
    except OSError as e:
        return ManifestSweepResult(
            all_verified=False,
            per_file=results,
            error=first_error or f"Cannot enumerate model directory '{model_dir}': {e}",
        )
    for extra_rel in on_disk:
        if extra_rel not in manifest_rel:
            err = (
                f"Extra weight/topology file '{extra_rel}' is present under the "
                f"model directory but NOT listed in the manifest — refusing to "
                f"load (fail-closed)."
            )
            results.append(
                IntegrityCheckResult(
                    verified=False, computed_digest="", expected_digest="",
                    model_path=str(model_dir / extra_rel), error=err,
                )
            )
            if first_error is None:
                first_error = err
            logger.error("Weight sweep (nested) FAIL (extra file): %s", err)

    all_ok = first_error is None
    return ManifestSweepResult(
        all_verified=all_ok,
        per_file=results,
        error=first_error,
    )
