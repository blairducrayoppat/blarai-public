"""Stage a weight-integrity manifest for a model directory (#930, ceremony prep).

Computes SHA-256 over every weight-bearing binary in a model directory and
writes the flat ``manifest.json`` shape the loader already verifies::

    {"version": "1.0.0", "digests": {"<filename>": "<sha256>", ...}}

**This script does NOT sign anything.** Signing is a separate, operator-present
provisioning ceremony (``shared.models.manifest_signer.sign_manifest``, TPM
backed). Staging and signing are deliberately two steps so the operator can
read what is about to be signed before it is: a manifest is a statement that
*these exact bytes are the model we trust*, and it is worth nothing if nobody
looked at what went into it.

Refuses to overwrite an existing manifest unless ``--force`` is given — an
existing manifest may already be signed, and silently replacing it would
invalidate the signature while leaving the file looking healthy.

Usage::

    python scripts/stage_model_manifest.py <model-dir>            # write
    python scripts/stage_model_manifest.py <model-dir> --dry-run  # inspect only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

MANIFEST_VERSION = "1.0.0"
MANIFEST_NAME = "manifest.json"
CHUNK = 1024 * 1024 * 8  # 8 MiB — large files, keep the read syscall count sane


def sha256_file(path: Path) -> tuple[str, float]:
    """Return ``(hex_digest, seconds)`` for *path*."""
    digest = hashlib.sha256()
    t0 = time.perf_counter()
    with path.open("rb") as handle:
        while True:
            block = handle.read(CHUNK)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest(), time.perf_counter() - t0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model_dir", help="Directory holding the OpenVINO export")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute and print the digests without writing the manifest.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing manifest.json (INVALIDATES any signature).",
    )
    args = parser.parse_args()

    model_dir = Path(args.model_dir)
    if not model_dir.is_dir():
        print(f"FATAL: not a directory: {model_dir}", file=sys.stderr)
        return 2

    manifest_path = model_dir / MANIFEST_NAME
    if manifest_path.exists() and not (args.force or args.dry_run):
        print(
            f"REFUSING: {manifest_path} already exists. It may be signed, and "
            "replacing it would invalidate the signature while leaving the file "
            "looking healthy. Pass --force only if you intend to re-sign.",
            file=sys.stderr,
        )
        return 3

    binaries = sorted(p for p in model_dir.glob("*.bin") if p.is_file())
    if not binaries:
        print(f"FATAL: no *.bin weight files under {model_dir}", file=sys.stderr)
        return 2

    total_bytes = sum(p.stat().st_size for p in binaries)
    print(f"Model dir : {model_dir}")
    print(f"Files     : {len(binaries)} binaries, {total_bytes / 1024**3:.2f} GiB total")
    print("-" * 74)

    digests: dict[str, str] = {}
    t_all = time.perf_counter()
    for path in binaries:
        size_gib = path.stat().st_size / 1024**3
        hexdigest, seconds = sha256_file(path)
        digests[path.name] = hexdigest
        rate = size_gib / seconds if seconds > 0 else 0.0
        print(f"  {path.name:<46} {size_gib:7.2f} GiB  {seconds:6.1f}s  {rate:5.2f} GiB/s")
        print(f"      sha256 {hexdigest}")
    elapsed = time.perf_counter() - t_all
    print("-" * 74)
    print(f"Hashed {total_bytes / 1024**3:.2f} GiB in {elapsed:.1f}s")

    manifest = {"version": MANIFEST_VERSION, "digests": digests}
    rendered = json.dumps(manifest, indent=2) + "\n"

    if args.dry_run:
        print("\n--- manifest.json (DRY RUN, not written) ---")
        print(rendered)
        return 0

    manifest_path.write_text(rendered, encoding="utf-8")
    print(f"\nWrote {manifest_path}")
    print(
        "NOT SIGNED. The signing ceremony is a separate, operator-present step:\n"
        "    from shared.models.manifest_signer import sign_manifest\n"
        f'    sign_manifest(r"{manifest_path}")'
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
