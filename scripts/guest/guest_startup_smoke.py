"""Guest startup smoke for Priority-5 runtime deployment.

Runs inside the Alpine guest after artifact extraction. It validates that
both service entrypoint boot paths are reachable, and records deterministic
failure fingerprints for fail-closed behavior.
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
import sys


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _failure(stage: str, code: str, message: str) -> dict[str, str]:
    return {
        "timestamp": _timestamp(),
        "stage": stage,
        "code": code,
        "message": message,
        "disposition": "FAIL",
        "fail_closed": "true",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Priority-5 guest startup smoke")
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    runtime_root = Path(args.runtime_root).resolve()
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    sys.path.insert(0, str(runtime_root))

    failures: list[dict[str, str]] = []
    policy_started = False
    orchestrator_started = False

    try:
        from services.policy_agent.src.entrypoint import PolicyAgentService
        from services.assistant_orchestrator.src.entrypoint import AssistantOrchestratorService
    except Exception as exc:  # noqa: BLE001
        failures.append(_failure("import", "P5_IMPORT_FAILED", str(exc)))
        with open(output_path, "w", encoding="utf-8") as file_obj:
            json.dump(
                {
                    "timestamp": _timestamp(),
                    "disposition": "FAIL",
                    "failures": failures,
                },
                file_obj,
                indent=2,
            )
        return 1

    try:
        policy = PolicyAgentService.from_runtime_mode(
            "guest",
            dev_mode_override=True,
        )
        policy_started = policy.start()
        if not policy_started:
            if policy.last_failure is not None:
                failures.append(
                    _failure(
                        "policy_start",
                        policy.last_failure.get("code", "P5_POLICY_START_FAILED"),
                        policy.last_failure.get(
                            "message",
                            "Policy Agent start returned False",
                        ),
                    )
                )
            else:
                failures.append(
                    _failure(
                        "policy_start",
                        "P5_POLICY_START_FAILED",
                        "Policy Agent start returned False",
                    )
                )
    except Exception as exc:  # noqa: BLE001
        failures.append(_failure("policy_start", "P5_POLICY_START_EXCEPTION", str(exc)))

    try:
        orchestrator = AssistantOrchestratorService.from_runtime_mode("guest")
        orchestrator_started = orchestrator.start()
        if not orchestrator_started:
            if orchestrator.last_failure is not None:
                failures.append(
                    _failure(
                        "orchestrator_start",
                        orchestrator.last_failure.get(
                            "code",
                            "P5_ORCH_START_FAILED",
                        ),
                        orchestrator.last_failure.get(
                            "message",
                            "Assistant Orchestrator start returned False",
                        ),
                    )
                )
            else:
                failures.append(
                    _failure(
                        "orchestrator_start",
                        "P5_ORCH_START_FAILED",
                        "Assistant Orchestrator start returned False",
                    )
                )
    except Exception as exc:  # noqa: BLE001
        failures.append(_failure("orchestrator_start", "P5_ORCH_START_EXCEPTION", str(exc)))

    try:
        if policy_started:
            policy.stop()
    except Exception as exc:  # noqa: BLE001
        failures.append(_failure("policy_stop", "P5_POLICY_STOP_EXCEPTION", str(exc)))

    try:
        if orchestrator_started:
            orchestrator.stop()
    except Exception as exc:  # noqa: BLE001
        failures.append(_failure("orchestrator_stop", "P5_ORCH_STOP_EXCEPTION", str(exc)))

    disposition = "PASS" if not failures else "FAIL"
    payload = {
        "timestamp": _timestamp(),
        "disposition": disposition,
        "runtime_root": str(runtime_root),
        "policy_started": policy_started,
        "orchestrator_started": orchestrator_started,
        "failures": failures,
    }

    with open(output_path, "w", encoding="utf-8") as file_obj:
        json.dump(payload, file_obj, indent=2)

    return 0 if disposition == "PASS" else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(main())
