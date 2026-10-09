"""#1587 follow-up — the arm the first run left out: TPM-chain VERIFICATION.

The first run measured boot verification on the SOFTWARE chain only (0.16 ms at
0 records, 8.16 ms at 500, ~16 us/record). That figure cannot be carried across
to production, because production verifies a chain signed by the TPM, and if
`verify()` performs a chip operation PER RECORD then boot cost is the per-append
TPM figure multiplied by the chain length — 500 records would be roughly a
minute of startup, which would be the single most decision-relevant number in
this ticket and was not in the report.

Reporting the software boot figure as "the" boot cost would be the same error
this whole ticket exists to correct: a number taken on the wrong instrument.

Chains of 0, 50 and 200. The first version stopped at 50, and an independent
verification showed that is too shallow to estimate the slope: the WITHIN-run
spread across 10/25/50 records (8.54, 13.77, 12.28 ms/record) was wider than the
between-run range being reported as the honest figure. At 200 records each point
is backed by a thousand chip verifications and the cumulative-average slope has
converged.

SAFETY: scratch local_root only; the operator's real audit chains are never
opened. Signs only; provisions nothing, rotates nothing.
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import time
import uuid
from pathlib import Path

#: Derived from this file's own location, for the reason in the companion probe:
#: a hardcoded absolute path makes a doubter running this from a branch measure
#: `main` and say nothing about it.
REPO = Path(os.environ.get("BLARAI_REPO") or Path(__file__).resolve().parents[1])
sys.path.insert(0, str(REPO))

SCRATCH = Path(os.environ["PROBE_SCRATCH"])
SCRATCH.mkdir(parents=True, exist_ok=True)

LENGTHS = (0, 50, 200)
REPEATS = 5

#: Fallback only. The software chain's marginal boot-verification cost is
#: MEASURED in this run by `_software_slope()`; this constant is used only if
#: that measurement cannot be taken, and the output says which was used.
#:
#: It was previously a frozen constant, described as "measured rather than a
#: threshold somebody picked" — true of its provenance and not of its liveness,
#: since nothing re-derived it and nothing would notice it going stale. Replacing
#: one hardcoded number with another that has a better story is not a fix.
SOFTWARE_MS_PER_RECORD_FALLBACK: float = 0.016

#: Lengths for the software reference sweep. Cheap (microseconds per record), so
#: it is measured in the same run rather than carried across from another.
SOFTWARE_LENGTHS = (0, 200)


def _stats(xs: list[float]) -> dict[str, float]:
    s = sorted(xs)
    return {
        "min_ms": s[0] * 1e3,
        "p50_ms": s[len(s) // 2] * 1e3,
        "max_ms": s[-1] * 1e3,
        "mean_ms": statistics.fmean(s) * 1e3,
        "n": len(s),
    }


class _Shim:
    def __init__(self, log) -> None:
        self._verdict_audit = log
        self._verdict_audit_memory = None

    def _verdict_audit_fallback(self):
        raise AssertionError("fell back to the in-memory chain — NOT the durable path")


def _software_slope(build, audit_verdict) -> tuple[float, str]:
    """MEASURE the software chain's marginal verification cost, in this run.

    Returns (ms_per_record, provenance). This used to be a frozen constant
    described as "measured rather than a threshold somebody picked" — true of
    where the number came from, and not of whether anything would notice it
    going stale. Nothing re-derived it and nothing would have failed if it
    drifted, which makes it a threshold with a better story rather than a
    measurement.

    Cheap to take: the software walk is microseconds per record, so both points
    cost less than the first TPM point does.
    """
    try:
        points: list[tuple[int, float]] = []
        for length in SOFTWARE_LENGTHS:
            root = SCRATCH / f"swref_{length}"
            (root / "BlarAI" / "audit").mkdir(parents=True, exist_ok=True)
            log = build(
                dev_mode=True, local_root=str(root),
                filename="verdict_audit.jsonl",
                stub_domain=b"BlarAI-verdict-audit-hmac-stub-v1", purpose="verdict",
            )
            shim = _Shim(log)
            for _ in range(length):
                if audit_verdict(
                    shim, decision="allow", reason="blarai.tool.allowed",
                    source_door="ao_tool_dispatch",
                    action_identity="sha256:" + uuid.uuid4().hex + uuid.uuid4().hex,
                    resource="tool:probe_1587", liftable=False,
                ) is not True:
                    raise RuntimeError("software reference fill append failed")
            samples = []
            for _ in range(REPEATS):
                t0 = time.perf_counter()
                build(
                    dev_mode=True, local_root=str(root),
                    filename="verdict_audit.jsonl",
                    stub_domain=b"BlarAI-verdict-audit-hmac-stub-v1",
                    purpose="verdict",
                )
                samples.append(time.perf_counter() - t0)
            points.append((length, sorted(samples)[len(samples) // 2] * 1e3))
        (lo_n, lo_ms), (hi_n, hi_ms) = points[0], points[-1]
        slope = (hi_ms - lo_ms) / max(1, hi_n - lo_n)
        if slope <= 0:
            raise RuntimeError(f"non-positive software slope {slope}")
        return slope, f"measured in this run, {lo_n}->{hi_n} records"
    except Exception as exc:  # noqa: BLE001 - a reference that fails says so
        return (
            SOFTWARE_MS_PER_RECORD_FALLBACK,
            f"FALLBACK CONSTANT — live measurement failed ({type(exc).__name__}); "
            f"the ratio below is against a figure this run did not take",
        )


def main() -> int:
    from services.assistant_orchestrator.src.entrypoint import (
        AssistantOrchestratorService as AO,
    )

    print("=== #1587: does TPM-chain VERIFICATION cost per record? ===")
    print(f"scratch: {SCRATCH}")
    print()

    audit_verdict = AO._audit_verdict
    build = AO._build_audit_chain

    rows: list[dict[str, object]] = []
    for length in LENGTHS:
        root = SCRATCH / f"tpmboot_{length}"
        (root / "BlarAI" / "audit").mkdir(parents=True, exist_ok=True)
        # Build ONCE to populate, then rebuild to time the verification the
        # construction performs — _build_audit_chain calls _verified() itself,
        # so rebuilding IS the boot path, not a reimplementation of it.
        log = build(
            dev_mode=False, local_root=str(root), filename="verdict_audit.jsonl",
            stub_domain=b"BlarAI-verdict-audit-hmac-stub-v1", purpose="verdict",
        )
        shim = _Shim(log)
        for _ in range(length):
            assert audit_verdict(
                shim, decision="allow", reason="blarai.tool.allowed",
                source_door="ao_tool_dispatch",
                action_identity="sha256:" + uuid.uuid4().hex + uuid.uuid4().hex,
                resource="tool:probe_1587", liftable=False,
            ), "append failed"

        samples: list[float] = []
        for _ in range(REPEATS):
            t0 = time.perf_counter()
            build(
                dev_mode=False, local_root=str(root),
                filename="verdict_audit.jsonl",
                stub_domain=b"BlarAI-verdict-audit-hmac-stub-v1", purpose="verdict",
            )
            samples.append(time.perf_counter() - t0)
        row = {"records": length, **_stats(samples)}
        per_record = (
            (row["p50_ms"] - rows[0]["p50_ms"]) / length if length and rows else 0.0
        )
        row["per_record_ms"] = per_record
        rows.append(row)
        print(f"BOOT(TPM) n={length:<3}: {json.dumps(row)}")

    print()
    base = rows[0]["p50_ms"]
    last = rows[-1]
    slope = (last["p50_ms"] - base) / max(1, last["records"])
    print(f"fixed cost at 0 records : {base:.2f} ms")
    print(f"marginal cost per record: {slope:.3f} ms")
    print()
    # The discriminating question, answered against a MEASURED reference rather
    # than a round number. The first version of this used `if slope > 10.0` and
    # printed "does NOT do per-record TPM work" for a slope of 8.763 ms/record,
    # sitting directly beneath a table showing that against the software chain's
    # 0.016 ms. An arbitrary threshold beat its own data. The comparison that
    # decides this is TPM-versus-software, and the software figure comes from the
    # companion probe rather than from a constant chosen here.
    sw_slope, sw_source = _software_slope(build, audit_verdict)
    print(f"software marginal cost  : {sw_slope:.4f} ms/record ({sw_source})")
    ratio = slope / sw_slope
    print(f"ratio                   : {ratio:.0f}x")
    if ratio > 10:
        print()
        print("VERDICT: verification does PER-RECORD TPM work. Boot cost scales with")
        print("the chain, so the active-record ceiling is what bounds startup — it is")
        print("load-bearing, not a tuning constant.")
        print(f"  at PRODUCTION_MAX_ACTIVE_RECORDS=1000: ~{(base + slope*1000)/1000:.1f} s "
              "PER CHAIN, and the AO builds two.")
    else:
        print()
        print("VERDICT: the marginal cost is within an order of magnitude of the")
        print("software chain, so the chip is touched a bounded number of times.")
    (SCRATCH / "probe_1587_boot_tpm.json").write_text(
        json.dumps({"rows": rows, "slope_ms_per_record": slope}, indent=2),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
