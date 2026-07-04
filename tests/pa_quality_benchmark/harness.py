"""
PA Quality Benchmark — Harness
================================
Corpus loading, classifier adapters, and evidence artifact production.

The harness is intentionally thin: it loads JSONL, builds CARs, runs
the injected classifier, and writes a JSON artifact. The metrics
computation lives in metrics.py.

Classifier injection pattern
-----------------------------
The benchmark supports three classifier modes:

1. rule_engine_only: DeterministicPolicyChecker + rule engine only — no GPU.
   This is what the deterministic tests use. Runs in CI with no hardware.

2. full_adjudicator(mock_gpu_result): Full adjudication pipeline with a
   mocked GPU result. The mock returns a fixed label + confidence, so the
   decision matrix can be exercised without OpenVINO.

3. real_gpu (slow + hardware marker): Full pipeline with a real
   PolicyGPUInference — skipped unless --hardware is passed to pytest.

All three adapters return a plain str (ALLOW / DENY / ESCALATE) for a
given raw CAR dict. They share the run_benchmark() interface from metrics.py.
"""

from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path
from typing import Any, Callable

from shared.schemas.car import (
    ActionVerb,
    AdjudicationDecision,
    CanonicalActionRepresentation,
    Sensitivity,
)
from services.policy_agent.src.gpu_inference import (
    DeterministicPolicyChecker,
    GPUClassificationResult,
)
from services.policy_agent.src.adjudicator import adjudicate
from services.policy_agent.src.rule_engine import run_rule_engine
from tests.pa_quality_benchmark.metrics import BenchmarkResult, run_benchmark

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

CORPUS_PATH: Path = Path(__file__).parent / "corpus.jsonl"
EVIDENCE_DIR: Path = Path("phase2_gates/evidence")


# ---------------------------------------------------------------------------
# Corpus loading
# ---------------------------------------------------------------------------

def load_corpus(path: Path = CORPUS_PATH) -> list[dict[str, Any]]:
    """Load the labeled corpus from JSONL.

    Args:
        path: Path to the corpus.jsonl file.

    Returns:
        List of corpus items, each with id / label / category / description / car.

    Raises:
        FileNotFoundError: If the corpus file does not exist.
        ValueError: If a line is malformed or missing required fields.
    """
    items: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Corpus line {lineno}: invalid JSON — {exc}") from exc

            for required_field in ("id", "label", "car"):
                if required_field not in item:
                    raise ValueError(
                        f"Corpus line {lineno}: missing required field '{required_field}'"
                    )

            valid_labels = {d.value for d in AdjudicationDecision}
            if item["label"] not in valid_labels:
                raise ValueError(
                    f"Corpus line {lineno}: invalid label '{item['label']}'"
                    f" — must be one of {sorted(valid_labels)}"
                )

            items.append(item)

    return items


def build_car_from_dict(car_dict: dict[str, Any]) -> CanonicalActionRepresentation:
    """Construct a CanonicalActionRepresentation from a raw dict.

    Args:
        car_dict: Dict with source_agent, destination_service, verb,
            resource, sensitivity, and optional parameters_schema / session_id.

    Returns:
        A CanonicalActionRepresentation.
    """
    return CanonicalActionRepresentation(
        source_agent=car_dict.get("source_agent", ""),
        destination_service=car_dict.get("destination_service", ""),
        verb=ActionVerb(car_dict["verb"]) if car_dict.get("verb") else ActionVerb.READ,
        resource=car_dict.get("resource", ""),
        sensitivity=Sensitivity(car_dict["sensitivity"]) if car_dict.get("sensitivity") else Sensitivity.UNCLASSIFIED,
        parameters_schema=car_dict.get("parameters_schema") or {},
        request_id=str(uuid.uuid4()),
        session_id=car_dict.get("session_id", ""),
    )


# ---------------------------------------------------------------------------
# Classifier adapters
# ---------------------------------------------------------------------------

def make_deterministic_classifier(
    acl_matrix: dict[str, list[str]] | None = None,
) -> Callable[[dict[str, Any]], str]:
    """Build a deterministic-only classifier adapter (no GPU).

    Pipeline:
      1. DeterministicPolicyChecker (pre-filter).
      2. Rule engine (STRUCTURAL, SENSITIVITY, ACL, RATE, RESOURCE).
      3. Decision matrix with a mocked DENY/0.0 GPU result when rule engine
         passes — the GPU is never consulted.

    This adapter is used by all non-hardware tests. It is deterministic:
    the same corpus item always produces the same result.

    Args:
        acl_matrix: Source-agent -> destination-service permission matrix.
            If None, the ACL rule will deny any request (Fail-Closed).

    Returns:
        A callable (car_dict: dict) -> str.
    """
    def classify(car_dict: dict[str, Any]) -> str:
        car = build_car_from_dict(car_dict)

        # DeterministicPolicyChecker pre-filter (runs before rule engine in classify_car)
        prefilter = DeterministicPolicyChecker.check(car)
        if prefilter is not None:
            label, _rule = prefilter
            return label

        # Rule engine
        rule_result = run_rule_engine(car, acl_matrix=acl_matrix)
        if not rule_result.passed:
            return AdjudicationDecision.DENY.value

        # Rule engine passed but no GPU in this adapter — return DENY (fail-closed).
        # This represents the "rule engine ALLOW, GPU not consulted" state.
        # For ALLOW labels in the corpus that reach this point, the benchmark
        # requires a real GPU or a mocked GPU result.
        return AdjudicationDecision.DENY.value

    return classify


def make_hybrid_classifier(
    acl_matrix: dict[str, list[str]] | None,
    mock_gpu_label: str = "ALLOW",
    mock_gpu_confidence: float = 0.9,
) -> Callable[[dict[str, Any]], str]:
    """Build a hybrid classifier adapter with a mocked GPU result.

    The full adjudication decision matrix is exercised, but the GPU
    classifier is replaced by a fixed (label, confidence) pair. This
    allows testing the decision matrix and rule engine together without
    OpenVINO hardware.

    Args:
        acl_matrix: Source-agent -> destination-service permission matrix.
        mock_gpu_label: Label returned by the mocked GPU (default ALLOW).
        mock_gpu_confidence: Confidence returned by the mocked GPU.

    Returns:
        A callable (car_dict: dict) -> str.
    """
    mock_gpu_result = GPUClassificationResult(
        label=mock_gpu_label,
        confidence=mock_gpu_confidence,
        latency_ms=0.0,
        error=None,
    )

    def classify(car_dict: dict[str, Any]) -> str:
        car = build_car_from_dict(car_dict)

        # DeterministicPolicyChecker pre-filter
        prefilter = DeterministicPolicyChecker.check(car)
        if prefilter is not None:
            label, _rule = prefilter
            return label

        # Rule engine
        rule_result = run_rule_engine(car, acl_matrix=acl_matrix)

        # Full decision matrix
        artifact = adjudicate(car, rule_result, mock_gpu_result)
        return artifact.decision.value

    return classify


# ---------------------------------------------------------------------------
# Evidence artifact production
# ---------------------------------------------------------------------------

def write_evidence_artifact(
    result: BenchmarkResult,
    git_sha: str | None = None,
    output_dir: Path = EVIDENCE_DIR,
) -> Path:
    """Write a JSON evidence artifact for the benchmark run.

    Args:
        result: Completed BenchmarkResult.
        git_sha: Git SHA to embed in the filename (resolved if None).
        output_dir: Directory to write the artifact into.

    Returns:
        Path to the written artifact.
    """
    if git_sha is None:
        try:
            git_sha = subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
        except Exception:
            git_sha = "unknown"

    output_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = output_dir / f"pa_quality_benchmark_{git_sha}.json"

    per_class_data = {
        cls: {
            "precision": pcm.precision,
            "recall": pcm.recall,
            "f1": pcm.f1,
            "tp": pcm.tp,
            "fp": pcm.fp,
            "fn": pcm.fn,
            "tn": pcm.tn,
            "support": pcm.support,
        }
        for cls, pcm in result.per_class.items()
    }

    artifact = {
        "git_sha": git_sha,
        "total_samples": result.security.total,
        "correct": result.security.correct,
        "accuracy": result.security.accuracy,
        "false_allow_rate": result.security.false_allow_rate,
        "false_deny_rate": result.security.false_deny_rate,
        "per_class": per_class_data,
        "missed": result.missed,
        "sample_count_by_label": {
            label: sum(1 for g, _ in result.predictions if g == label)
            for label in ("ALLOW", "DENY", "ESCALATE")
        },
    }

    artifact_path.write_text(
        json.dumps(artifact, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return artifact_path
