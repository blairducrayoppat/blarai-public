"""
Cleaner pipeline performance capture (Testing-Data rule, CLAUDE.md).
====================================================================
NOT a pytest module (no ``test_`` prefix — never collected). Run manually:

    C:\\Users\\mrbla\\blarai\\.venv\\Scripts\\python.exe \\
        services/cleaner/tests/perf_capture.py

Times ``clean_html`` over the committed fixture corpus — the full pipeline
(trafilatura extraction → normalization → sanitization → verdict) on CPU,
no model, no network — and writes the community-grade JSON record to
``docs/performance/cleaner_pipeline_<date>.json``. Methodology: 3 warmup
passes, then ``NUM_RUNS`` measured passes over the whole corpus with
per-fixture ``perf_counter`` timings; statistics are computed per fixture
and per corpus pass.
"""

from __future__ import annotations

import datetime
import json
import platform
import statistics
import sys
import time
from importlib import metadata
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO))

from services.cleaner.src.pipeline import CLEANER_VERSION, clean_html  # noqa: E402

NUM_WARMUP = 3
NUM_RUNS = 20

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def main() -> None:
    fixtures = sorted(_FIXTURES.glob("*.html"))
    corpus = {f.name: f.read_text(encoding="utf-8") for f in fixtures}
    assert corpus, "fixture corpus missing"

    for _ in range(NUM_WARMUP):
        for raw in corpus.values():
            clean_html(raw, source_url="https://example.org/warmup")

    per_fixture_ms: dict[str, list[float]] = {name: [] for name in corpus}
    corpus_pass_ms: list[float] = []
    for _ in range(NUM_RUNS):
        pass_start = time.perf_counter()
        for name, raw in corpus.items():
            start = time.perf_counter()
            clean_html(raw, source_url="https://example.org/" + name)
            per_fixture_ms[name].append((time.perf_counter() - start) * 1000.0)
        corpus_pass_ms.append((time.perf_counter() - pass_start) * 1000.0)

    def stats(values: list[float]) -> dict[str, float]:
        return {
            "mean_ms": round(statistics.mean(values), 3),
            "median_ms": round(statistics.median(values), 3),
            "stdev_ms": round(statistics.stdev(values), 3),
            "min_ms": round(min(values), 3),
            "max_ms": round(max(values), 3),
        }

    record = {
        "benchmark": "cleaner_pipeline_clean_html",
        "config_stamp": {
            "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
            "hardware_cpu": "Intel Core Ultra 7 258V (Lunar Lake)",
            "hardware_gpu": "not used — pipeline is CPU-only, no model",
            "os": platform.platform(),
            "python": platform.python_version(),
            "trafilatura_version": metadata.version("trafilatura"),
            "lxml_version": metadata.version("lxml"),
            "cleaner_version": CLEANER_VERSION,
            "num_runs": NUM_RUNS,
            "num_warmup": NUM_WARMUP,
            "methodology": (
                "clean_html (bare_extraction with metadata, favor_recall off, "
                "comments off; NFC/control/zero-width normalization; injection "
                "scan + delimiter strip; verdict) timed per fixture with "
                "time.perf_counter over the committed 7-fixture synthesized "
                "corpus (services/cleaner/tests/fixtures/); 3 warmup passes "
                "then 20 measured corpus passes on the otherwise-idle dev box."
            ),
        },
        "corpus": {
            name: {"raw_bytes": len(raw.encode("utf-8"))}
            for name, raw in corpus.items()
        },
        "results": {
            "corpus_pass": stats(corpus_pass_ms),
            "per_fixture": {name: stats(vals) for name, vals in per_fixture_ms.items()},
        },
        "not_measured": [
            "real-world fetched pages (corpus is synthesized; production news "
            "pages are 50-500 KB and will extract slower — re-measure at fetch "
            "activation)",
            "clean_text paste path (trivially cheaper; no extraction stage)",
            "memory footprint of the lxml/trafilatura stack",
            "co-resident cost while the 14B model occupies the GPU/RAM",
            "throughput under the guest-homed (Hyper-V VM) topology of "
            "ADR-030 §3 — these numbers are host-side",
        ],
    }

    out = _REPO / "docs" / "performance" / (
        "cleaner_pipeline_" + datetime.date.today().isoformat() + ".json"
    )
    out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print("wrote", out)
    print(json.dumps(record["results"]["corpus_pass"], indent=2))


if __name__ == "__main__":
    main()
