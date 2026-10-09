"""Read-only reference-corpus tier (#1616).

Separate from the operator's knowledge bank by design: see
:mod:`shared.corpus.reader` for why the two cannot share a retrieval path.
"""

from shared.corpus.reader import (
    CorpusError,
    CorpusHit,
    ReferenceCorpus,
    default_manifest_path,
    fts_match_expr,
)

__all__ = [
    "CorpusError",
    "CorpusHit",
    "ReferenceCorpus",
    "default_manifest_path",
    "fts_match_expr",
]
