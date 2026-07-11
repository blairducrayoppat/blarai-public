"""
#795 - Hybrid-vs-vector-vs-BM25 retrieval A/B on the knowledge bank.
====================================================================
assistant_memory_reference_study_2026-07 4.2 (verdict row 6). The 2026
literature has no rigorous hybrid-vs-pure-vector head-to-head on an
agent-memory workload; BlarAI already runs both limbs (cosine + FTS5 BM25,
reciprocal-rank fusion k=60), so the A/B is nearly free and is a publishable
community gap-filler (the operator is an OpenVINO upstream contributor).

This drives the REAL production retrieval path: a genuine
``EncryptedKnowledgeBank`` (born-encrypted, TPM-software-sealed DEK, the same
submit -> approve -> chunk -> embed -> index pipeline the AO runs), seeded with
a labelled personal-knowledge corpus + query set
(docs/research/fixtures/knowledge_retrieval_ab.json), with the encoder being
the production bge-small-en-v1.5 on the NPU path (fail-soft CPU).

Each query is scored three ways, all reconstructed from the SAME in-RAM caches
the bank builds, using the SAME query embedding, the SAME ``_fts_match_expr``
and the SAME ``RRF_K`` the production ``retrieve()`` uses:
  - vector-only   : brute-force cosine ranking over the decrypted embeddings.
  - bm25-only     : FTS5 BM25 ranking over the in-memory index.
  - hybrid (RRF)  : reciprocal-rank fusion of the two (== ``bank.retrieve``,
                    cross-checked per query as a self-test).

Metrics: recall@{1,3,4,5,10} and MRR per limb, overall and split by the limb
each query is designed to stress (vector / lexical / neutral). Community-grade
JSON under docs/performance/ with hardware / OpenVINO / driver identity, the
encoder device actually served, corpus + query methodology, and an explicit
"what is NOT measured". No GPU, no OVMS, no AO - encoder + an in-memory
SQLite store only.

Usage (from the worktree repo root, main-checkout venv + model):
  C:/Users/mrbla/blarai/.venv/Scripts/python.exe \
    scripts/measure_795_hybrid_vs_vector.py \
    --model C:/Users/mrbla/blarai/models/bge-small-en-v1.5/onnx-fp16/model.onnx \
    --device NPU
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import numpy as np

_FIXTURE = _REPO_ROOT / "docs" / "research" / "fixtures" / "knowledge_retrieval_ab.json"
_K_LIST = (1, 3, 4, 5, 10)


def _default_model() -> str:
    local = _REPO_ROOT / "models" / "bge-small-en-v1.5" / "onnx-fp16" / "model.onnx"
    if local.is_file():
        return str(local)
    return "C:/Users/mrbla/blarai/models/bge-small-en-v1.5/onnx-fp16/model.onnx"


def _first_gold_rank(ranked_docs: list[str], gold: set[str]) -> int | None:
    """1-based rank of the first gold doc in a doc-id ranking (None if absent)."""
    for i, d in enumerate(ranked_docs):
        if d in gold:
            return i + 1
    return None


def _metrics(ranks: list[int | None]) -> dict[str, Any]:
    n = len(ranks)
    out: dict[str, Any] = {}
    for k in _K_LIST:
        hits = sum(1 for r in ranks if r is not None and r <= k)
        out[f"recall@{k}"] = round(hits / n, 4) if n else 0.0
    rr = [1.0 / r if r is not None else 0.0 for r in ranks]
    out["mrr"] = round(sum(rr) / n, 4) if n else 0.0
    out["n"] = n
    out["found_any"] = sum(1 for r in ranks if r is not None)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default=_default_model())
    ap.add_argument("--device", default="NPU", help="Encoder device: NPU (production) | CPU")
    args = ap.parse_args()

    if args.device.upper() == "GPU":
        print("REFUSED: GPU is reserved by another workstream; use NPU or CPU.", file=sys.stderr)
        return 3
    if not Path(args.model).is_file():
        print(f"ERROR: model not found at {args.model}", file=sys.stderr)
        return 2

    data = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    corpus = data["corpus"]
    queries = data["queries"]

    from services.assistant_orchestrator.src.knowledge_bank import (
        EncryptedKnowledgeBank,
        RRF_K,
        _fts_match_expr,
        _guard_embed_input,
    )
    from services.assistant_orchestrator.src.pgov import LeakageDetector
    from shared.security.dek_envelope import DekEnvelope, generate_recovery_key
    from shared.security.field_cipher import FieldCipher, derive_subkeys
    from shared.security.tpm_sealer import SoftwareSealer

    # ── Production encoder (NPU path; fail-soft CPU) ──────────────────────
    det = LeakageDetector(model_path=args.model, max_input_length=128, device=args.device)
    t0 = time.perf_counter()
    if not det.load_model():
        print("ERROR: encoder failed to load", file=sys.stderr)
        return 4
    load_s = time.perf_counter() - t0

    def embed_fn(texts: list[str]) -> np.ndarray:
        # The knowledge-bank document window is 512 (config embed_max_tokens);
        # the SAME embed_fn embeds both chunks (approve) and the query
        # (retrieve), exactly as production binds it.
        return np.asarray(det.embed_documents(texts, max_length=512), dtype=np.float32)

    # ── Real born-encrypted store (software-sealed DEK) ───────────────────
    sealer = SoftwareSealer()
    env = DekEnvelope.create(sealer=sealer, recovery_key=generate_recovery_key())
    cipher = FieldCipher(derive_subkeys(env.unseal_dek()))
    bank = EncryptedKnowledgeBank(
        db_path=":memory:", embed_fn=embed_fn, cipher=cipher, embed_max_tokens=512
    )

    # Seed: submit + approve every doc; map our stable id -> store doc_uuid.
    id_to_uuid: dict[str, str] = {}
    uuid_to_id: dict[str, str] = {}
    ingest_t0 = time.perf_counter()
    total_chunks = 0
    for doc in corpus:
        du = str(uuid.uuid5(uuid.NAMESPACE_URL, f"blarai795/{doc['id']}"))
        id_to_uuid[doc["id"]] = du
        uuid_to_id[du] = doc["id"]
        bank.submit_pending(
            doc_uuid=du,
            source_type="paste",  # store enum is file|paste|url; fixture 'note' is decorative
            source_ref=f"fixture://{doc['id']}",
            content=doc["text"],
            title=doc["title"],
            byline="fixture",
            published_date="2026-07-10",
            cleaner_version="fixture-v1",
            word_count=len(doc["text"].split()),
        )
        total_chunks += bank.approve(du)
    ingest_s = time.perf_counter() - ingest_t0

    # One chunk per doc is a fixture invariant (docs < CHUNK_CHARS); assert it so
    # doc-level == chunk-level recall labelling stays honest.
    multi_chunk = [d for d in corpus if id_to_uuid[d["id"]] and
                   sum(1 for key in bank._chunk_vecs if key[0] == id_to_uuid[d["id"]]) != 1]
    if multi_chunk:
        print(f"WARN: {len(multi_chunk)} docs produced != 1 chunk: {[d['id'] for d in multi_chunk]}", file=sys.stderr)

    N = len(corpus)

    def rank_limbs(query: str) -> tuple[list[str], list[str], list[str], bool]:
        """Reproduce retrieve()'s three rankings, mapped to doc ids.

        Returns (vector_docs, bm25_docs, rrf_docs, rrf_matches_production).
        """
        q = np.asarray(bank._embed(_guard_embed_input([query])), dtype=np.float32)
        q_vec = q[0] if q.ndim == 2 else q

        keys = list(bank._chunk_vecs.keys())
        matrix = np.vstack([bank._chunk_vecs[k] for k in keys])
        scores = matrix @ q_vec
        vector_ranked = [keys[int(i)] for i in np.argsort(scores)[::-1]]

        lexical_ranked: list[tuple[str, int]] = []
        match_expr = _fts_match_expr(query)
        if match_expr:
            rows = bank._fts.execute(
                "SELECT doc_uuid, chunk_index FROM knowledge_fts "
                "WHERE knowledge_fts MATCH ? ORDER BY bm25(knowledge_fts)",
                (match_expr,),
            ).fetchall()
            lexical_ranked = [(str(r[0]), int(r[1])) for r in rows]

        fused: dict[tuple[str, int], float] = {}
        for ranked in (vector_ranked, lexical_ranked):
            for rank, key in enumerate(ranked):
                fused[key] = fused.get(key, 0.0) + 1.0 / (RRF_K + rank + 1)
        rrf_ranked = [k for k, _ in sorted(fused.items(), key=lambda kv: kv[1], reverse=True)]

        v_docs = [uuid_to_id.get(k[0], k[0]) for k in vector_ranked]
        b_docs = [uuid_to_id.get(k[0], k[0]) for k in lexical_ranked]
        r_docs = [uuid_to_id.get(k[0], k[0]) for k in rrf_ranked]

        # Cross-check the reconstructed RRF against the production retrieve().
        prod = bank.retrieve(query, k=N)
        prod_docs = [uuid_to_id.get(h.doc_uuid, h.doc_uuid) for h in prod]
        matches = prod_docs == r_docs[: len(prod_docs)]
        return v_docs, b_docs, r_docs, matches

    per_query: list[dict[str, Any]] = []
    ranks_by_limb: dict[str, list[int | None]] = {"vector": [], "bm25": [], "hybrid_rrf": []}
    ranks_by_probe: dict[str, dict[str, list[int | None]]] = {}
    rrf_mismatch = 0
    bm25_empty = 0

    for q in queries:
        gold = set(q["gold"])
        v_docs, b_docs, r_docs, ok = rank_limbs(q["query"])
        if not ok:
            rrf_mismatch += 1
        if not b_docs:
            bm25_empty += 1
        rv = _first_gold_rank(v_docs, gold)
        rb = _first_gold_rank(b_docs, gold)
        rr = _first_gold_rank(r_docs, gold)
        ranks_by_limb["vector"].append(rv)
        ranks_by_limb["bm25"].append(rb)
        ranks_by_limb["hybrid_rrf"].append(rr)
        probe = q.get("probe", "neutral")
        ranks_by_probe.setdefault(probe, {"vector": [], "bm25": [], "hybrid_rrf": []})
        ranks_by_probe[probe]["vector"].append(rv)
        ranks_by_probe[probe]["bm25"].append(rb)
        ranks_by_probe[probe]["hybrid_rrf"].append(rr)
        per_query.append({
            "id": q["id"], "probe": probe, "query": q["query"], "gold": q["gold"],
            "rank_vector": rv, "rank_bm25": rb, "rank_hybrid_rrf": rr,
            "bm25_returned": len(b_docs),
        })

    det.unload()
    bank.close()

    overall = {limb: _metrics(ranks) for limb, ranks in ranks_by_limb.items()}
    by_probe = {
        probe: {limb: _metrics(ranks) for limb, ranks in limbs.items()}
        for probe, limbs in ranks_by_probe.items()
    }

    # Environment / device identity.
    env_info: dict[str, Any] = {
        "python": sys.version.split()[0],
        "os": f"Windows {sys.getwindowsversion().major}.{sys.getwindowsversion().build}",  # type: ignore[attr-defined]
    }
    try:
        import onnxruntime as ort
        env_info["onnxruntime"] = ort.__version__
    except Exception:  # noqa: BLE001
        env_info["onnxruntime"] = "unavailable"
    try:
        import openvino as ov
        env_info["openvino"] = ov.__version__
        core = ov.Core()
        env_info["devices"] = {}
        for dev in core.available_devices:
            entry: dict[str, str] = {}
            try:
                entry["name"] = str(core.get_property(dev, "FULL_DEVICE_NAME"))
            except Exception:  # noqa: BLE001
                pass
            for key in ("NPU_DRIVER_VERSION", "GPU_DRIVER_VERSION", "DRIVER_VERSION"):
                try:
                    entry["driver"] = str(core.get_property(dev, key))
                    break
                except Exception:  # noqa: BLE001
                    continue
            env_info["devices"][dev] = entry
    except Exception:  # noqa: BLE001
        env_info["openvino"] = "unavailable"

    payload = {
        "measurement": "hybrid_vs_vector_retrieval_795",
        "ticket": "#795",
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "encoder": "BAAI/bge-small-en-v1.5 ONNX fp16 (384-dim), mean-pool + L2-norm, 512-token document window",
        "retrieval_surface": "services.assistant_orchestrator.src.knowledge_bank.EncryptedKnowledgeBank (real store; cosine + FTS5 BM25, RRF k=60)",
        "requested_device": args.device,
        "active_device": det.active_device,
        "backend": det.backend,
        "rrf_k": RRF_K,
        "load_s": round(load_s, 3),
        "ingest_s": round(ingest_s, 3),
        "environment": env_info,
        "corpus": {
            "path": str(_FIXTURE.relative_to(_REPO_ROOT)).replace("\\", "/"),
            "n_docs": N,
            "n_chunks": total_chunks,
            "n_queries": len(queries),
            "probes": {p: sum(1 for q in queries if q.get("probe") == p)
                       for p in sorted({q.get("probe", "neutral") for q in queries})},
        },
        "methodology": {
            "labelling": "single gold doc per query; docs sized < CHUNK_CHARS so 1 doc == 1 chunk, so recall@k is doc-level hit@k.",
            "limbs": "all three rankings reconstructed from the bank's OWN in-RAM caches with the SAME query embedding, _fts_match_expr, and RRF_K as retrieve(); the hybrid ranking is cross-checked == bank.retrieve() per query.",
            "metrics": "recall@{1,3,4,5,10} and MRR (reciprocal rank of the first gold), per limb, overall + per probe class.",
            "rrf_production_crosscheck_mismatches": rrf_mismatch,
            "queries_with_empty_bm25": bm25_empty,
        },
        "results_overall": overall,
        "results_by_probe": by_probe,
        "per_query": per_query,
        "not_measured": [
            "co-resident Qwen3-14B contention (encoder run in isolation; the GPU is reserved by another workstream).",
            "multi-chunk documents and long-article chunking effects (fixture docs are single-chunk by design for clean labelling).",
            "MMR diversity pass / min-score floor / retrieval-time recency boost (study row 5 - the episodic-tier tuning follow-on, out of scope).",
            "the operator's real ingested corpus (this is a synthetic labelled set; production knowledge.db content differs).",
            "weighted-score fusion (0.7/0.3) as an alternative to RRF - the study already recommends keeping RRF; this A/B measures limb contribution, not the fusion-rule choice.",
            "graded relevance / multiple gold docs per query (single-gold binary relevance only).",
        ],
    }

    out_dir = _REPO_ROOT / "docs" / "performance"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    out_path = out_dir / f"hybrid_vs_vector_795_{stamp}.json"
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # ---- human summary ----
    print(f"\nJSON written: {out_path}")
    print(f"encoder: {args.device}->{det.active_device} ({det.backend})  load={load_s:.2f}s  ingest={ingest_s:.2f}s")
    print(f"corpus: {N} docs / {total_chunks} chunks / {len(queries)} queries   RRF-vs-production mismatches: {rrf_mismatch}   empty-BM25 queries: {bm25_empty}")
    hdr = f"{'limb':12}" + "".join(f"{('R@'+str(k)):>8}" for k in _K_LIST) + f"{'MRR':>8}"
    print("\n=== OVERALL ===")
    print(hdr)
    for limb in ("vector", "bm25", "hybrid_rrf"):
        m = overall[limb]
        print(f"{limb:12}" + "".join(f"{m[f'recall@{k}']:>8.3f}" for k in _K_LIST) + f"{m['mrr']:>8.3f}")
    for probe in sorted(by_probe):
        print(f"\n=== probe: {probe}  (n={by_probe[probe]['vector']['n']}) ===")
        print(hdr)
        for limb in ("vector", "bm25", "hybrid_rrf"):
            m = by_probe[probe][limb]
            print(f"{limb:12}" + "".join(f"{m[f'recall@{k}']:>8.3f}" for k in _K_LIST) + f"{m['mrr']:>8.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
