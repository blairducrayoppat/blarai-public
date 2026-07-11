### 2026-07-10 — Stamping the door the vectors came through

*Plain summary: #794 — stamp the embedding-model identity (name + revision) into
`substrate_meta` and `knowledge_meta` at index build, and cross-check it at load;
on mismatch loud-disable the vector limb only (ADR-031 §7 middle ground) rather
than serve cosine scores from a different model's space. Substrate (vector-only)
returns no memory; the knowledge bank keeps BM25.*

The substrate already stamped an `embed_max_tokens` window into its meta table
and, since #655, refused loudly when a store's recorded window disagreed with the
configured one — the mixed-depth guard. What it did NOT guard was the *identity of
the model itself*. Both stores wrote `embed_model = 'bge-small-en-v1.5'` as a
hardcoded literal and then never read it back. That is the OpenClaw "index
identity" gap the assistant-memory reference study flagged (§2.2b / verdict row 3):
the day bge-small is ever upgraded, every stored vector becomes a point in the old
model's space, and a query embedded by the new model produces cosine numbers that
*look* fine and *mean* nothing. C5 — what you configure is not what runs — applied
to the vector index. Dormant today, load-bearing the first time the model-upgrade
watch fires.

The fix rides the discipline that was already there rather than inventing a new
one. Each store now stamps `embed_model` + a new `embed_model_revision` (the
export/precision variant — `onnx-fp16` — derived in production from the model file
the shared detector actually loads, so a swap of `[pgov].embedding_model_path` is
what the check sees), reads them back, and compares. The stamping is `INSERT OR
IGNORE`, which is also the whole migration: a fresh store adopts the configured
identity; a legacy store that predates the revision key gets stamped at the current
one (no false alarm — historically only bge-small has ever run); and a store
previously stamped under a *different* identity is the one case that trips. Same
mechanism the window check uses, so there is one idea to understand, not two.

The posture was the one real choice, and the ticket flagged it for the kickoff:
hard-fail the whole retrieval, or degrade. I took the ticket's recommendation —
**loud-disable the vector limb only**, the ADR-031 §7 "loud-disable" middle ground.
BM25 does not depend on the embedder at all, so a model swap leaves lexical
retrieval perfectly valid; hard-failing it too would throw away a working limb to
punish the broken one. So the knowledge bank skips the cosine limb (and does not
even embed the query) while its FTS5/BM25 limb runs untouched and fuses
lexical-only; the substrate, which has no lexical limb, returns nothing rather than
garbage. Both log a stable `EMBED_MODEL_IDENTITY_MISMATCH` ERROR at construction
naming the stored-vs-configured identities and the rebuild path (re-embed ceremony
or restore the prior model path), and expose the mismatch as a read-only property.
The confidentiality controls underneath (per-row decrypt-quarantine) are untouched;
this is an availability/correctness guard layered above them, and it is fail-SAFE —
an unreadable meta table or an unrecognised table name resolves to "no mismatch"
because identity resolution must never be the thing that blocks boot.

The strongest lock in the gate proves the limb boundary rather than just the flag:
a knowledge store built with a pinned embedder where the query and the target share
a vector but **zero** words, reopened under a mismatched identity with a *poison*
embedder that raises if called — the vector-only query returns nothing (cosine off,
query never embedded), while a word-sharing query still returns the doc through
BM25. That single test would fail if the vector limb were secretly still running or
if the degradation had taken BM25 down with it.

Tests: 23 new in `test_embedding_identity_stamp.py` (identity resolution + path
parsing, fresh-stamp, match/mismatch on both stores, the BM25-survives lock, the
legacy-migration no-alarm path, and the fail-safe helper). Touched-module run 182
green; the `shared/ + services/` standing-gate slice **4494 passed, 0 failed** (the
20 skips are the known worktree env-skips — the gitignored bge-small ONNX absent).

**Next:** the check is wired through `_build_substrate` / `_build_knowledge_bank`
from the detector's actual model path, so it is live the next AO boot with no
ceremony. It becomes visibly load-bearing only at a genuine embedding-model
upgrade — at which point the operator's action is the ADR-031 §3 re-embed ceremony
the mismatch log already names. No behavior change until then. A future refinement,
if a same-name/same-variant re-export ever needs distinguishing, is a real weight
content-hash as the revision — deferred as heavier than this ticket wanted (it would
read the model bytes at every boot); the path-derived variant is the honest,
cheap identity for the swaps that actually happen.
