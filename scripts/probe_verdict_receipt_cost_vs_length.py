"""#1587 — what a verdict receipt costs AS THE CHAIN GROWS.

WHY THIS EXISTS. The first #1587 measurement reported a single pair of numbers —
software 6.26 ms, TPM 111.90 ms, ratio 17.9x — and an independent review found
that every sample behind them landed on a chain holding 0 to 65 records, because
the probe ran into a fresh file. The shipped software append cost is not constant
in chain length: it climbs from roughly 6 ms empty to roughly 45 ms at the
1000-record production ceiling.

So the RATIO is not a property of the system. It is a property of how full the
chain was when someone measured it, and it falls from about 13x to about 3x
across the range the system actually operates in. The plain-language sentence
"the gap is eighteen times" was true only on a nearly-empty chain, and that is
the sentence an operator would act on.

WHAT IS STABLE is the DELTA — the chip signature — at roughly 90 to 115 ms
regardless of length. A design decision about whether to keep per-record TPM
signing turns on that constant, not on a ratio whose denominator moves.

This probe reports the curve for both arms so no single pair can be quoted
without its length.

SAFETY: scratch local_root only. The operator's real audit chains under
%LOCALAPPDATA%/BlarAI/audit are never opened, for read or write. Signs only;
provisions nothing, rotates nothing.
"""

from __future__ import annotations

import json
import os
import platform
import statistics
import sys
import time
import uuid
from pathlib import Path

#: The checkout this probe measures: the one it is IN. See the companion probes.
REPO = Path(os.environ.get("BLARAI_REPO") or Path(__file__).resolve().parents[1])
sys.path.insert(0, str(REPO))

SCRATCH = Path(os.environ["PROBE_SCRATCH"])
SCRATCH.mkdir(parents=True, exist_ok=True)

#: Chain depths to sample at. Stops below the 1000-record ceiling on purpose:
#: `_should_rotate()` seals a segment at exactly 1000 and the per-append cost
#: RESETS, so a sample straddling that point averages two regimes.
DEPTHS = (0, 65, 250, 500, 900)
SAMPLES = 25
N_TPM_DEPTHS = (0, 65, 250, 500)  # the chip arm is ~100x slower; fewer depths


def _p50(xs: list[float]) -> float:
    s = sorted(xs)
    return s[len(s) // 2] * 1e3


def _stats(xs: list[float]) -> dict[str, float]:
    s = sorted(xs)
    return {
        "min_ms": s[0] * 1e3,
        "p50_ms": _p50(xs),
        "max_ms": s[-1] * 1e3,
        "mean_ms": statistics.fmean(s) * 1e3,
        "stdev_ms": statistics.stdev(s) * 1e3 if len(s) > 1 else 0.0,
        "n": len(s),
    }


class _Shim:
    """Carries the SHIPPED _audit_verdict. See probe_verdict_receipt_cost.py."""

    def __init__(self, log) -> None:
        self._verdict_audit = log
        self._verdict_audit_memory = None

    def _verdict_audit_fallback(self):
        raise AssertionError("fell back to the in-memory chain — NOT the durable path")


def _drive(audit_verdict, shim) -> bool:
    return audit_verdict(
        shim,
        decision="allow",
        reason="blarai.tool.allowed",
        source_door="ao_tool_dispatch",
        action_identity="sha256:" + uuid.uuid4().hex + uuid.uuid4().hex,
        resource="tool:probe_1587",
        liftable=False,
    )


def _sweep(build, audit_verdict, *, dev_mode: bool, depths) -> list[dict[str, object]]:
    """Append cost at each depth, on a chain grown to that depth first."""
    rows: list[dict[str, object]] = []
    for depth in depths:
        root = SCRATCH / f"{'sw' if dev_mode else 'tpm'}_{depth}"
        (root / "BlarAI" / "audit").mkdir(parents=True, exist_ok=True)
        log = build(
            dev_mode=dev_mode, local_root=str(root),
            filename="verdict_audit.jsonl",
            stub_domain=b"BlarAI-verdict-audit-hmac-stub-v1", purpose="verdict",
        )
        shim = _Shim(log)
        for _ in range(depth):
            if _drive(audit_verdict, shim) is not True:
                raise AssertionError(f"fill append failed at depth {depth}")

        samples: list[float] = []
        for i in range(SAMPLES):
            t0 = time.perf_counter()
            ok = _drive(audit_verdict, shim)
            samples.append(time.perf_counter() - t0)
            # A FAILED append returns False in ~0.027 ms against ~6 ms for a
            # successful one, so it drags p50 DOWN and reads as good news.
            if ok is not True:
                raise AssertionError(
                    f"timed append {i} at depth {depth} returned {ok!r}"
                )

        path = root / "BlarAI" / "audit" / "verdict_audit.jsonl"
        row = {
            "records_before": depth,
            "file_kb": round(path.stat().st_size / 1024, 1) if path.exists() else 0.0,
            **_stats(samples),
        }
        rows.append(row)
        print(f"  depth {depth:<4} {'sw ' if dev_mode else 'tpm'} "
              f"p50={row['p50_ms']:8.3f} ms  file={row['file_kb']:8.1f} KB")
    return rows


def main() -> int:
    from services.assistant_orchestrator.src.entrypoint import (
        AssistantOrchestratorService as AO,
    )

    print("=== #1587: receipt cost AS THE CHAIN GROWS ===")
    print(f"repo measured : {REPO}")
    print(f"scratch       : {SCRATCH}")
    print(f"samples/depth : {SAMPLES}")
    print()

    build = AO._build_audit_chain
    audit_verdict = AO._audit_verdict

    print("software chain:")
    sw = _sweep(build, audit_verdict, dev_mode=True, depths=DEPTHS)
    print("TPM chain:")
    tpm = _sweep(build, audit_verdict, dev_mode=False, depths=N_TPM_DEPTHS)

    by_depth = {r["records_before"]: r for r in sw}
    paired: list[dict[str, object]] = []
    for r in tpm:
        d = r["records_before"]
        if d not in by_depth:
            continue
        s_ms, t_ms = by_depth[d]["p50_ms"], r["p50_ms"]
        paired.append({
            "records_before": d,
            "software_p50_ms": round(s_ms, 3),
            "tpm_p50_ms": round(t_ms, 3),
            "delta_ms": round(t_ms - s_ms, 2),
            "ratio": round(t_ms / s_ms, 2),
        })

    print()
    print("depth | software p50 | tpm p50 | delta | ratio")
    for row in paired:
        print(f"{row['records_before']:>5} | {row['software_p50_ms']:>12.3f} | "
              f"{row['tpm_p50_ms']:>7.2f} | {row['delta_ms']:>5.1f} | "
              f"{row['ratio']:>5.2f}x")

    deltas = [r["delta_ms"] for r in paired]
    ratios = [r["ratio"] for r in paired]
    print()
    print(f"DELTA  spans {min(deltas):.0f}-{max(deltas):.0f} ms "
          f"({(max(deltas)-min(deltas))/min(deltas)*100:.0f}% of the smallest)")
    print(f"RATIO  spans {min(ratios):.2f}x-{max(ratios):.2f}x "
          f"({(max(ratios)-min(ratios))/min(ratios)*100:.0f}% of the smallest)")
    print()
    print("The DELTA is the chip signature and is roughly constant. The RATIO is")
    print("not a property of the system — it is a property of how full the chain")
    print("was when it was measured. Quote the delta; quote a ratio only with its")
    print("depth attached.")

    out = {
        "measurement": "verdict_receipt_cost_vs_chain_length",
        "ticket": "#1587",
        "repo_measured": str(REPO),
        "host": platform.node(),
        "python": sys.version.split()[0],
        "samples_per_depth": SAMPLES,
        "software_sweep": sw,
        "tpm_sweep": tpm,
        "paired": paired,
    }
    (SCRATCH / "probe_1587_vs_length.json").write_text(
        json.dumps(out, indent=2), encoding="utf-8"
    )
    print()
    print(f"written: {SCRATCH / 'probe_1587_vs_length.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
