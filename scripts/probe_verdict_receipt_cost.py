"""#1587 - MEASURE the cost of a #1542 verdict receipt on the SHIPPED path.

WHY THIS EXISTS. An earlier probe reported 131-157 ms per TPM signature against
0.027 ms for software. That probe called ``shared.security.tpm_signer``
DIRECTLY. It did not touch ``_audit_verdict``, ``build_receipt``, the hash
chain, the segment ceiling, or the JSONL append - i.e. none of the shipped
path. A per-signature figure is not a per-receipt figure, and designing a
software-chain-with-TPM-signed-head optimisation off it would be designing
against a number that was never measured on the thing being optimised.

WHAT THIS MEASURES, on the real path:
  ARM 0  loop overhead      - the instrument measuring itself. Establishes the
                              floor and the machine's own variance BEFORE any
                              arm is compared. (Standing rule: an effect smaller
                              than the measuring variance is not a finding.)
  ARM S  software chain     - AO's shipped dev ladder: HmacSha256Signer via
                              _build_audit_chain(dev_mode=True), driven through
                              the SHIPPED _audit_verdict.
  ARM T  TPM chain          - AO's shipped production ladder:
                              _build_audit_chain(dev_mode=False) -> TpmRecordSigner,
                              same _audit_verdict, same receipt payload.
  BOOT   chain verification - _verified()'s log.verify() walk at several chain
                              lengths. This is the cost that scales with the
                              chain and is paid at EVERY service restart; the
                              per-append figure alone cannot predict it.

SAFETY:
  * local_root is a SCRATCH directory. Nothing is written to the operator's
    real %LOCALAPPDATA%/BlarAI/audit/ chains. The scratch root is printed.
  * Read-only with respect to the repo tree.
  * The TPM arm uses the audit signing key the AO itself selects, via the
    shipped shared.security.audit_verification.signing_key_name(), so it exercises the real key, not a
    probe-invented one. It only SIGNS; it provisions nothing and rotates nothing.
  * If the TPM arm cannot be built, the probe REFUSES to report a comparison.
    A software-only number presented as "the cost" would be the blind-instrument
    failure this session already shipped once.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import statistics
import sys
import time
import uuid
from pathlib import Path

#: The checkout this probe measures: the one it is IN, derived from its own
#: location, not a hardcoded absolute path. The first committed version pinned
#: `C:/Users/mrbla/BlarAI`, so running it from a branch measured `main` and said
#: nothing about it — the wrong-instrument failure this ticket exists to correct,
#: inside the instrument correcting it. Override with BLARAI_REPO to measure a
#: different tree deliberately.
REPO = Path(os.environ.get("BLARAI_REPO") or Path(__file__).resolve().parents[1])
sys.path.insert(0, str(REPO))

SCRATCH = Path(os.environ["PROBE_SCRATCH"])
SCRATCH.mkdir(parents=True, exist_ok=True)

N_WARMUP = 5
N_ITER = int(os.environ.get("PROBE_ITER", "60"))
BOOT_LENGTHS = (0, 50, 200, 500)


def _percentiles(xs: list[float]) -> dict[str, float]:
    s = sorted(xs)
    n = len(s)

    def p(q: float) -> float:
        if n == 1:
            return s[0]
        idx = q * (n - 1)
        lo = int(idx)
        hi = min(lo + 1, n - 1)
        return s[lo] + (s[hi] - s[lo]) * (idx - lo)

    return {
        "min_ms": s[0] * 1e3,
        "p50_ms": p(0.50) * 1e3,
        "p90_ms": p(0.90) * 1e3,
        "p99_ms": p(0.99) * 1e3,
        "max_ms": s[-1] * 1e3,
        "mean_ms": statistics.fmean(s) * 1e3,
        "stdev_ms": (statistics.stdev(s) * 1e3) if n > 1 else 0.0,
        "n": n,
    }


class _Shim:
    """Minimal carrier for the SHIPPED _audit_verdict.

    _audit_verdict is an instance method that reads exactly one attribute off
    self (_verdict_audit) and calls _verdict_audit_fallback only when that is
    None. Binding it to this shim runs the REAL function - the real
    build_receipt call, the real append kwargs, the real try/except - rather
    than a reimplementation of it. That distinction is the whole point of this
    ticket.
    """

    def __init__(self, log) -> None:
        self._verdict_audit = log
        self._verdict_audit_memory = None

    def _verdict_audit_fallback(self):  # pragma: no cover - must never fire here
        raise AssertionError(
            "the probe fell back to the in-memory chain: it was NOT measuring "
            "the durable path it claims to measure"
        )


def _identity() -> str:
    return "sha256:" + uuid.uuid4().hex + uuid.uuid4().hex


def _drive(audit_verdict, shim) -> bool:
    return audit_verdict(
        shim,
        decision="allow",
        reason="blarai.tool.allowed",
        source_door="ao_tool_dispatch",
        action_identity=_identity(),
        resource="tool:probe_1587",
        liftable=False,
    )


def _timed(fn, n: int, *, require_true: bool = False) -> list[float]:
    """Time ``fn`` n times, optionally REFUSING a run in which it returned False.

    ``_audit_verdict`` returns False through its except-Exception path when an
    append fails, and a failed append costs about 0.027 ms against roughly 6 ms
    for a successful one. So a partially-failing run reports a LOWER p50 and
    looks like good news. The timed loop used to discard the return value.
    """
    out: list[float] = []
    for i in range(n):
        t0 = time.perf_counter()
        result = fn()
        out.append(time.perf_counter() - t0)
        if require_true and result is not True:
            raise AssertionError(
                f"append {i} returned {result!r}, not True — a failed append is "
                f"~230x faster than a successful one, so these timings would "
                f"read as an improvement"
            )
    return out


def _conditions() -> dict[str, object]:
    """Conditions MEASURED, not asserted.

    The first version wrote `"elevated": True` as a literal — it printed
    `elevated: true` whether or not it was — and a `"note"` field whose value was
    an instruction to a human sitting in a slot that reads as data. A condition
    block that cannot be wrong is not a condition block.
    """
    import ctypes
    import subprocess

    try:
        elevated = bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001 - a probe must not die reporting on itself
        elevated = None

    def _git(*args: str) -> str:
        try:
            return subprocess.run(
                ["git", "-C", str(REPO), *args],
                capture_output=True, text=True, timeout=10,
            ).stdout.strip()
        except Exception:  # noqa: BLE001
            return "(unavailable)"

    return {
        "host": platform.node(),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "processor": platform.processor(),
        "elevated": elevated,
        "repo_measured": str(REPO),
        "repo_head": _git("rev-parse", "--short", "HEAD") or "(unavailable)",
        "repo_branch": _git("rev-parse", "--abbrev-ref", "HEAD") or "(unavailable)",
        "repo_dirty": bool(_git("status", "--porcelain")),
        "entrypoint_loaded_from": str(
            Path(sys.modules["services.assistant_orchestrator.src.entrypoint"].__file__)
        ) if "services.assistant_orchestrator.src.entrypoint" in sys.modules else "(not loaded)",
    }


def main() -> int:
    print("=== #1587: verdict-receipt cost on the SHIPPED path ===")
    print(f"scratch local_root : {SCRATCH}")
    print(f"iterations per arm : {N_ITER} (+{N_WARMUP} warmup)")
    print()

    from services.assistant_orchestrator.src.entrypoint import (
        AssistantOrchestratorService as AO,
    )

    audit_verdict = AO._audit_verdict
    build = AO._build_audit_chain

    results: dict[str, object] = {}

    # ---- ARM 0: the instrument measuring itself -----------------------------
    def _noop() -> None:
        pass

    _timed(_noop, N_WARMUP)
    results["arm0_loop_overhead"] = _percentiles(_timed(_noop, N_ITER))
    print("ARM 0 loop overhead  :", json.dumps(results["arm0_loop_overhead"]))

    # ---- ARM S: software chain, shipped construction ------------------------
    sw_root = SCRATCH / "sw"
    (sw_root / "BlarAI" / "audit").mkdir(parents=True, exist_ok=True)
    sw_log = build(
        dev_mode=True,
        local_root=str(sw_root),
        filename="verdict_audit.jsonl",
        stub_domain=b"BlarAI-verdict-audit-hmac-stub-v1",
        purpose="verdict",
    )
    sw_shim = _Shim(sw_log)
    for _ in range(N_WARMUP):
        assert _drive(audit_verdict, sw_shim), "software arm failed to record"
    sw = _timed(lambda: _drive(audit_verdict, sw_shim), N_ITER, require_true=True)
    results["armS_software_chain"] = _percentiles(sw)
    print("ARM S software chain :", json.dumps(results["armS_software_chain"]))

    # ---- ARM T: TPM chain, shipped construction -----------------------------
    tpm_root = SCRATCH / "tpm"
    (tpm_root / "BlarAI" / "audit").mkdir(parents=True, exist_ok=True)
    try:
        tpm_log = build(
            dev_mode=False,
            local_root=str(tpm_root),
            filename="verdict_audit.jsonl",
            stub_domain=b"BlarAI-verdict-audit-hmac-stub-v1",
            purpose="verdict",
        )
    except Exception as exc:  # noqa: BLE001
        print()
        print(
            f"REFUSED TO REPORT A COMPARISON: the TPM arm did not build "
            f"({type(exc).__name__}: {exc})."
        )
        print(
            "A software-only figure presented as 'the cost of a receipt' "
            "would be a blind instrument."
        )
        return 4

    tpm_shim = _Shim(tpm_log)
    for _ in range(N_WARMUP):
        assert _drive(audit_verdict, tpm_shim), "TPM arm failed to record"
    tp = _timed(lambda: _drive(audit_verdict, tpm_shim), N_ITER, require_true=True)
    results["armT_tpm_chain"] = _percentiles(tp)
    print("ARM T tpm chain      :", json.dumps(results["armT_tpm_chain"]))

    # The control that makes the comparison mean something: the two arms must be
    # separated by more than the instrument's own spread.
    floor = results["arm0_loop_overhead"]["p50_ms"]
    spread_s = results["armS_software_chain"]["stdev_ms"]
    delta = (
        results["armT_tpm_chain"]["p50_ms"]
        - results["armS_software_chain"]["p50_ms"]
    )
    results["separation"] = {
        "delta_p50_ms": delta,
        "software_stdev_ms": spread_s,
        "instrument_floor_ms": floor,
        "separated": delta > 3 * spread_s,
    }
    print("separation           :", json.dumps(results["separation"]))

    # ---- BOOT: the verification walk at several chain lengths ---------------
    from shared.security.audit_log import AuditLog, HmacSha256Signer

    boot: list[dict[str, float]] = []
    for length in BOOT_LENGTHS:
        root = SCRATCH / f"boot_{length}"
        (root / "BlarAI" / "audit").mkdir(parents=True, exist_ok=True)
        log = build(
            dev_mode=True,
            local_root=str(root),
            filename="verdict_audit.jsonl",
            stub_domain=b"BlarAI-verdict-audit-hmac-stub-v1",
            purpose="verdict",
        )
        shim = _Shim(log)
        for _ in range(length):
            _drive(audit_verdict, shim)
        path = root / "BlarAI" / "audit" / "verdict_audit.jsonl"
        key = hashlib.sha256(
            b"BlarAI-verdict-audit-hmac-stub-v1"
            + b"::"
            + str(path).encode("utf-8")
        ).digest()

        def _verify_once(p: Path = path, k: bytes = key) -> None:
            AuditLog.from_path(p, HmacSha256Signer(key=k)).verify()

        samples = _timed(_verify_once, max(5, N_ITER // 6))
        row = {"records": length, **_percentiles(samples)}
        boot.append(row)
        print(f"BOOT verify n={length:<4}:", json.dumps(row))
    results["boot_verification_software"] = boot

    results["conditions"] = _conditions()

    out = SCRATCH / "probe_1587_results.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print()
    print(f"results written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
