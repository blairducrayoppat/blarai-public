"""
Substrate re-embed migration (128 -> 512 token embedding window)
================================================================
Vikunja #655 (UC-002 Substrate v2).  The existing ``substrate.db`` rows were
embedded through the PGOV leakage detector's 128-token window while chunks are
2048 chars (~512 tokens) — only roughly the first quarter of each stored chunk
informs its vector.  This utility re-embeds every row at the 512-token window:

    decrypt text -> re-embed (512) -> re-encrypt embedding -> write back

and records the new window in ``substrate_meta`` (``embed_max_tokens``) so the
migration is detectable and idempotent (a second run is a no-op skip).

Follows the ``migrate_plaintext_to_encrypted`` precedent in ``substrate.py``:
per-row errors are counted and logged, never half-written; a verify pass
re-reads each migrated row and checks vector shape + L2 norm.

Runnable module (executed MANUALLY on the live box, never by tests — tests
exercise :func:`reembed_substrate` with a stub ``embed_fn``)::

    python -m services.assistant_orchestrator.src.reembed_substrate [--dry-run]

The runnable path resolves the production DEK (``BLARAI_DEK_KEYSTORE`` +
TpmSealer) — or the dev SoftwareSealer keystore beside the DB with ``--dev`` —
and binds the real bge-small embedder at the 512-token window via
``LeakageDetector.embed_documents``.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from services.assistant_orchestrator.src.substrate import (
    EMBED_DIM,
    EmbedFn,
    _natural_row_id,
)

logger = logging.getLogger(__name__)

# The target embedding window this migration moves the substrate to.
TARGET_EMBED_MAX_TOKENS: int = 512

# substrate_meta key recording the embedding token window.  Absent == the
# legacy 128-token leakage-path default (pre-#655 stores never wrote it).
_META_KEY: str = "embed_max_tokens"


def reembed_substrate(
    db_path: str,
    cipher: "FieldCipher",  # type: ignore[name-defined]  # noqa: F821
    embed_fn: EmbedFn,
    *,
    target_max_tokens: int = TARGET_EMBED_MAX_TOKENS,
    dry_run: bool = False,
    accept_quarantined: bool = False,
) -> dict[str, int]:
    """Re-embed every substrate row with *embed_fn* and bump ``substrate_meta``.

    Idempotent: when ``substrate_meta.embed_max_tokens`` already equals
    *target_max_tokens* the migration is skipped entirely (``{"skipped": 1}``
    in the result).  Per-row failures (undecryptable text/embedding) are
    counted as errors and left untouched — the migration never half-writes a
    row and never aborts the remaining rows.

    Meta-stamp discipline (#655 review fix): ``substrate_meta.embed_max_tokens``
    is stamped ONLY on a fully-clean run (``errors == 0`` and
    ``verify_failures == 0``).  A run with failures leaves the meta unset so a
    later healthy run actually re-migrates instead of being skipped as "done"
    — a partially-migrated store must never advertise itself as migrated.

    Args:
        db_path: Path to the substrate SQLite file.
        cipher: :class:`~shared.security.field_cipher.FieldCipher` derived from
            the unsealed DEK (the SAME DEK the store was written under).
        embed_fn: Callable mapping ``list[str]`` to ``(N, 384)`` L2-normalised
            float32 vectors — already bound to the TARGET window (the caller
            binds ``LeakageDetector.embed_documents`` at 512; tests pass a stub).
        target_max_tokens: The window being migrated to (recorded in meta).
        dry_run: When True nothing is written; counts report what would happen.
        accept_quarantined: When True, a genuinely-undecryptable row
            (``FieldCipherError`` — e.g. a quarantined dev-key remnant) is
            counted under ``quarantined`` instead of ``errors`` and does NOT
            block the meta stamp.  It is reported, never silently forgotten.
            Other per-row failures (bad embed shape, undecodable text) remain
            hard errors regardless of the flag.

    Returns:
        ``{"migrated": N, "errors": K, "skipped": 0|1, "verified": M,
        "verify_failures": F, "quarantined": Q}``.
    """
    import numpy as np
    from shared.security.field_cipher import (
        FIELD_CIPHER_VERSION,
        FieldCipherError,
        make_aad_for,
    )

    conn = sqlite3.connect(db_path, check_same_thread=False)
    try:
        meta_row = conn.execute(
            "SELECT value FROM substrate_meta WHERE key=?", (_META_KEY,)
        ).fetchone()
        if meta_row is not None and str(meta_row[0]) == str(target_max_tokens):
            logger.info(
                "reembed_substrate: substrate_meta.%s already %s — skipping "
                "(idempotent no-op)",
                _META_KEY,
                target_max_tokens,
            )
            return {
                "migrated": 0,
                "errors": 0,
                "skipped": 1,
                "verified": 0,
                "verify_failures": 0,
                "quarantined": 0,
            }

        # A pure-plaintext store (never encryption-migrated) lacks the
        # source_hash column — select NULL in its place so those rows take
        # the plaintext branch below.
        cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(substrate_chunks)").fetchall()
        }
        source_hash_expr = "source_hash" if "source_hash" in cols else "NULL"
        rows = conn.execute(
            f"SELECT id, kind, {source_hash_expr}, session_id, chunk_index, text "
            "FROM substrate_chunks"
        ).fetchall()

        migrated = 0
        errors = 0
        quarantined = 0
        migrated_ids: list[tuple[int, str]] = []  # (row_id, nat_id or "")

        for row_id, kind, source_hash_blob, session_id, chunk_index, text_raw in rows:
            try:
                if (
                    source_hash_blob is not None
                    and isinstance(text_raw, (bytes, bytearray))
                    and len(text_raw) > 0
                    and text_raw[0] == FIELD_CIPHER_VERSION
                ):
                    # Encrypted row — decrypt text, re-embed, re-encrypt embedding.
                    nat_id = _natural_row_id(
                        str(kind), bytes(source_hash_blob), str(session_id),
                        int(chunk_index),
                    )
                    text = cipher.decrypt(
                        bytes(text_raw),
                        aad=make_aad_for("substrate_chunks", "text", nat_id),
                    ).decode("utf-8")
                    new_vec = np.asarray(embed_fn([text]), dtype=np.float32)[0]
                    if new_vec.shape != (EMBED_DIM,):
                        raise ValueError(
                            f"embed_fn returned shape {new_vec.shape}, "
                            f"expected ({EMBED_DIM},)"
                        )
                    enc_emb = cipher.encrypt(
                        new_vec.tobytes(),
                        aad=make_aad_for("substrate_chunks", "embedding", nat_id),
                    )
                    if not dry_run:
                        conn.execute(
                            "UPDATE substrate_chunks SET embedding=? WHERE id=?",
                            (enc_emb, row_id),
                        )
                    migrated_ids.append((int(row_id), nat_id))
                else:
                    # Plaintext (pre-encryption-migration) row — re-embed raw.
                    text = (
                        text_raw
                        if isinstance(text_raw, str)
                        else bytes(text_raw).decode("utf-8")
                    )
                    new_vec = np.asarray(embed_fn([text]), dtype=np.float32)[0]
                    if new_vec.shape != (EMBED_DIM,):
                        raise ValueError(
                            f"embed_fn returned shape {new_vec.shape}, "
                            f"expected ({EMBED_DIM},)"
                        )
                    if not dry_run:
                        conn.execute(
                            "UPDATE substrate_chunks SET embedding=? WHERE id=?",
                            (new_vec.tobytes(), row_id),
                        )
                    migrated_ids.append((int(row_id), ""))
                migrated += 1
            except FieldCipherError as exc:
                if accept_quarantined:
                    quarantined += 1
                    logger.warning(
                        "reembed_substrate: row %d quarantined (undecryptable, "
                        "left untouched — accepted via --accept-quarantined): %s",
                        row_id,
                        exc,
                    )
                else:
                    errors += 1
                    logger.error(
                        "reembed_substrate: row %d failed (left untouched): %s",
                        row_id,
                        exc,
                    )
            except (ValueError, UnicodeDecodeError) as exc:
                errors += 1
                logger.error(
                    "reembed_substrate: row %d failed (left untouched): %s",
                    row_id,
                    exc,
                )

        verified = 0
        verify_failures = 0
        if not dry_run:
            # Persist the migrated rows first (independent of the meta stamp).
            conn.commit()

            # Verify pass: every migrated row decrypts to a unit-norm 384-vector.
            for row_id, nat_id in migrated_ids:
                emb_row = conn.execute(
                    "SELECT embedding FROM substrate_chunks WHERE id=?", (row_id,)
                ).fetchone()
                if emb_row is None:
                    verify_failures += 1
                    continue
                try:
                    if nat_id:
                        raw = cipher.decrypt(
                            bytes(emb_row[0]),
                            aad=make_aad_for("substrate_chunks", "embedding", nat_id),
                        )
                    else:
                        raw = bytes(emb_row[0])
                    vec = np.frombuffer(raw, dtype=np.float32)
                    norm = float(np.linalg.norm(vec))
                    if vec.shape == (EMBED_DIM,) and abs(norm - 1.0) < 1e-3:
                        verified += 1
                    else:
                        verify_failures += 1
                        logger.error(
                            "reembed_substrate verify: row %d shape=%s norm=%.4f",
                            row_id,
                            vec.shape,
                            norm,
                        )
                except FieldCipherError as exc:
                    verify_failures += 1
                    logger.error(
                        "reembed_substrate verify: row %d failed decrypt: %s",
                        row_id,
                        exc,
                    )

            # Meta stamp ONLY on a fully-clean run (#655 review fix): errors
            # or verify failures leave the meta UNSET so a later healthy run
            # re-migrates instead of skipping a partially-migrated store.
            # Flag-accepted quarantined rows are reported, not blocking.
            if errors == 0 and verify_failures == 0:
                conn.execute(
                    "INSERT OR REPLACE INTO substrate_meta(key, value) VALUES(?, ?)",
                    (_META_KEY, str(target_max_tokens)),
                )
                conn.commit()
            else:
                logger.error(
                    "reembed_substrate: %d error(s) / %d verify failure(s) — "
                    "substrate_meta.%s NOT stamped; re-run after fixing the "
                    "failing rows (a partial migration must not advertise "
                    "itself as complete).",
                    errors,
                    verify_failures,
                    _META_KEY,
                )

        logger.info(
            "reembed_substrate%s: migrated=%d errors=%d verified=%d "
            "verify_failures=%d quarantined=%d (target window: %d tokens)",
            " (dry run)" if dry_run else "",
            migrated,
            errors,
            verified,
            verify_failures,
            quarantined,
            target_max_tokens,
        )
        return {
            "migrated": migrated,
            "errors": errors,
            "skipped": 0,
            "verified": verified,
            "verify_failures": verify_failures,
            "quarantined": quarantined,
        }
    finally:
        conn.close()


def _main() -> int:
    """Manual live-box entry point (never invoked by tests)."""
    import argparse
    import os
    from pathlib import Path

    parser = argparse.ArgumentParser(
        description=(
            "Re-embed substrate.db rows at the 512-token window (UC-002 v2). "
            "Run manually on the live box after the knowledge-bank merge."
        )
    )
    parser.add_argument(
        "--db",
        default="",
        help=r"Substrate DB path (default: %%LOCALAPPDATA%%\BlarAI\substrate.db)",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Use the dev SoftwareSealer keystore beside the DB instead of "
        "BLARAI_DEK_KEYSTORE + TPM (development boxes only).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Report only; write nothing.")
    parser.add_argument(
        "--accept-quarantined",
        action="store_true",
        help="Count genuinely-undecryptable rows as quarantined (reported) "
        "instead of errors, so they do not block the substrate_meta stamp. "
        "Use only after confirming the rows are dev-key remnants.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    db_path = args.db
    if not db_path:
        local = os.environ.get("LOCALAPPDATA", "")
        if not local:
            print("LOCALAPPDATA is not set and no --db given; refusing.")
            return 2
        db_path = os.path.join(local, "BlarAI", "substrate.db")
    if not Path(db_path).exists():
        print(f"Substrate DB not found: {db_path}")
        return 2

    from shared.security.dek_envelope import DekEnvelope
    from shared.security.field_cipher import FieldCipher, derive_subkeys

    if args.dev:
        from shared.security.tpm_sealer import SoftwareSealer

        keystore_path = Path(db_path).with_suffix(".keystore.json")
        if not keystore_path.exists():
            print(f"Dev keystore not found: {keystore_path}")
            return 2
        envelope = DekEnvelope.load(sealer=SoftwareSealer(), keystore_path=keystore_path)
    else:
        keystore_env = os.environ.get("BLARAI_DEK_KEYSTORE", "")
        if not keystore_env:
            print(
                "BLARAI_DEK_KEYSTORE is not set; run the ceremony or pass --dev "
                "for a development keystore (Fail-Closed refuse)."
            )
            return 2
        from shared.security.tpm_sealer import TpmSealer

        envelope = DekEnvelope.load(
            sealer=TpmSealer(key_name="BlarAI-DEKSeal"),
            keystore_path=Path(keystore_env),
        )

    cipher = FieldCipher(derive_subkeys(envelope.unseal_dek()))

    from services.assistant_orchestrator.src import pgov

    detector = pgov._get_detector()
    if not detector.loaded and not detector.load_model():
        print("Embedding model failed to load; refusing (Fail-Closed).")
        return 2

    def _embed_512(texts: list[str]) -> Any:
        return detector.embed_documents(texts, max_length=TARGET_EMBED_MAX_TOKENS)

    result = reembed_substrate(
        db_path,
        cipher,
        _embed_512,
        dry_run=args.dry_run,
        accept_quarantined=args.accept_quarantined,
    )
    print(result)
    return 0 if result["errors"] == 0 and result["verify_failures"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(_main())
