"""
Priority-5 Guest Runtime Deployment
===================================
Deploys Policy Agent + Assistant Orchestrator runtime artifacts from host
to the Hyper-V guest (BlarAI-Orchestrator) using Guest Service Interface.

Security:
  - No external network calls.
  - Fail-Closed on all deployment or validation failures.
  - Deterministic failure fingerprints recorded in evidence JSON.
"""

from __future__ import annotations

import argparse
import json
import logging
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import zipfile

from launcher.vm_manager import (
    VMState,
    copy_file_to_vm,
    ensure_vm_running,
    get_vm_state,
    is_guest_service_interface_enabled,
)
from services.assistant_orchestrator.src.entrypoint import AssistantOrchestratorService
from services.policy_agent.src.entrypoint import PolicyAgentService
from shared.constants import (
    ORCHESTRATOR_VM_ID,
    ORCHESTRATOR_VM_NAME,
    VSOCK_PORT,
    VSOCK_SERVICE_GUID,
)

logger = logging.getLogger(__name__)


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class GuestDeployConfig:
    vm_name: str
    guest_root: str
    evidence_file: Path
    include_models: bool


_RUNTIME_DIRS: tuple[str, ...] = (
    "services/policy_agent",
    "services/assistant_orchestrator",
    "shared",
)

_MODEL_DIRS: tuple[str, ...] = (
    "models/qwen3-14b/openvino-int4-gpu",
    "models/qwen3-0.6b/openvino-int4-gpu",
    "models/bge-small-en-v1.5/onnx-fp16",
    "models/bge-small-en-v1.5/openvino-int8",
)

_RUNTIME_FILES: tuple[str, ...] = (
    "scripts/guest/bootstrap_runtime.sh",
    "scripts/guest/guest_startup_smoke.py",
)


def _failure_fingerprint(
    *,
    stage: str,
    code: str,
    message: str,
) -> dict[str, str]:
    return {
        "timestamp": _timestamp(),
        "stage": stage,
        "code": code,
        "message": message,
        "disposition": "FAIL",
        "fail_closed": "true",
    }


def _write_json(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as file_obj:
        json.dump(data, file_obj, indent=2)


def _validate_vsock_topology(repo_root: Path) -> tuple[bool, list[str]]:
    evidence_path = repo_root / "phase2_gates" / "evidence" / "vsock_validation.json"
    if not evidence_path.exists():
        return False, ["vsock evidence file missing"]

    try:
        with open(evidence_path, "r", encoding="utf-8") as file_obj:
            data = json.load(file_obj)
    except (OSError, json.JSONDecodeError) as exc:
        return False, [f"unable to parse vsock evidence: {exc}"]

    issues: list[str] = []
    if data.get("disposition") != "PASS":
        issues.append("vsock disposition is not PASS")

    host = data.get("host", {})
    test = data.get("test", {})

    if host.get("vm_id") != ORCHESTRATOR_VM_ID:
        issues.append("vm_id mismatch with shared constants")
    if host.get("service_guid") != VSOCK_SERVICE_GUID:
        issues.append("service_guid mismatch with shared constants")
    if int(host.get("vsock_port", -1)) != VSOCK_PORT:
        issues.append("vsock_port mismatch with shared constants")
    if not bool(test.get("connection_successful", False)):
        issues.append("connection_successful is false")
    if bool(test.get("tcp_ip_used", True)):
        issues.append("tcp_ip_used is true; expected AF_HYPERV-only")

    return len(issues) == 0, issues


def _zip_directory(zip_obj: zipfile.ZipFile, source_dir: Path, arc_prefix: str) -> None:
    for child in source_dir.rglob("*"):
        if child.is_dir():
            continue
        rel = child.relative_to(source_dir)
        zip_obj.write(child, f"{arc_prefix}/{rel.as_posix()}")


def _build_bundle(
    *,
    repo_root: Path,
    bundle_path: Path,
    include_models: bool,
) -> tuple[bool, str]:
    required_dirs = list(_RUNTIME_DIRS)
    if include_models:
        required_dirs.extend(_MODEL_DIRS)

    for rel_dir in required_dirs:
        if not (repo_root / rel_dir).exists():
            return False, f"required directory missing: {rel_dir}"

    for rel_file in _RUNTIME_FILES:
        if not (repo_root / rel_file).exists():
            return False, f"required file missing: {rel_file}"

    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as zip_obj:
        for rel_dir in required_dirs:
            source = repo_root / rel_dir
            _zip_directory(zip_obj, source, rel_dir)

        for rel_file in _RUNTIME_FILES:
            source = repo_root / rel_file
            zip_obj.write(source, rel_file)

    return True, "ok"


def _validate_guest_runtime_configs() -> tuple[bool, list[dict[str, str]]]:
    failures: list[dict[str, str]] = []

    policy_ok, policy_failure = PolicyAgentService.validate_runtime_config(
        deployment_mode="guest",
        dev_mode_override=True,
    )
    if not policy_ok and policy_failure is not None:
        failures.append(
            _failure_fingerprint(
                stage="config_preflight",
                code="P6_POLICY_CONFIG_INVALID",
                message=(
                    f"{policy_failure.get('code', 'UNKNOWN')}: "
                    f"{policy_failure.get('message', 'unknown')}."
                ),
            )
        )

    orchestrator_ok, orchestrator_failure = (
        AssistantOrchestratorService.validate_runtime_config(
            deployment_mode="guest",
        )
    )
    if not orchestrator_ok and orchestrator_failure is not None:
        failures.append(
            _failure_fingerprint(
                stage="config_preflight",
                code="P6_ORCH_CONFIG_INVALID",
                message=(
                    f"{orchestrator_failure.get('code', 'UNKNOWN')}: "
                    f"{orchestrator_failure.get('message', 'unknown')}."
                ),
            )
        )

    return len(failures) == 0, failures


def deploy_guest_runtime(config: GuestDeployConfig) -> bool:
    repo_root = Path(__file__).resolve().parents[1]
    fingerprints: list[dict[str, str]] = []

    vm_state_before = get_vm_state(config.vm_name)
    vm_started = ensure_vm_running(config.vm_name)
    if not vm_started:
        fingerprints.append(
            _failure_fingerprint(
                stage="vm_start",
                code="P5_VM_START_FAILED",
                message=f"Unable to start VM '{config.vm_name}'",
            )
        )
        _write_json(
            config.evidence_file,
            {
                "milestone": "Priority-5",
                "timestamp": _timestamp(),
                "disposition": "FAIL",
                "vm_state_before": vm_state_before.value,
                "failure_fingerprints": fingerprints,
            },
        )
        return False

    if not is_guest_service_interface_enabled(config.vm_name):
        fingerprints.append(
            _failure_fingerprint(
                stage="preflight",
                code="P5_GSI_DISABLED",
                message="Guest Service Interface is not enabled",
            )
        )
        _write_json(
            config.evidence_file,
            {
                "milestone": "Priority-5",
                "timestamp": _timestamp(),
                "disposition": "FAIL",
                "vm_state_before": vm_state_before.value,
                "failure_fingerprints": fingerprints,
            },
        )
        return False

    vsock_ok, vsock_issues = _validate_vsock_topology(repo_root)
    if not vsock_ok:
        fingerprints.append(
            _failure_fingerprint(
                stage="topology_validation",
                code="P5_VSOCK_TOPOLOGY_INVALID",
                message="; ".join(vsock_issues),
            )
        )
        _write_json(
            config.evidence_file,
            {
                "milestone": "Priority-5",
                "timestamp": _timestamp(),
                "disposition": "FAIL",
                "vm_state_before": vm_state_before.value,
                "failure_fingerprints": fingerprints,
            },
        )
        return False

    guest_config_ok, guest_config_failures = _validate_guest_runtime_configs()
    if not guest_config_ok:
        fingerprints.extend(guest_config_failures)
        _write_json(
            config.evidence_file,
            {
                "milestone": "Priority-5",
                "timestamp": _timestamp(),
                "disposition": "FAIL",
                "vm_state_before": vm_state_before.value,
                "failure_fingerprints": fingerprints,
            },
        )
        return False

    with tempfile.TemporaryDirectory(prefix="blarai-p5-probe-") as probe_tmp:
        probe_file = Path(probe_tmp) / "probe.txt"
        probe_file.write_text("priority5-probe", encoding="utf-8")
        probe_destination = f"{config.guest_root}/.blarai_probe.txt"
        probe_ok = copy_file_to_vm(
            source_path=probe_file,
            destination_path=probe_destination,
            vm_name=config.vm_name,
            timeout=30.0,
            retries=5,
            retry_delay_s=2.0,
        )
        if not probe_ok:
            fingerprints.append(
                _failure_fingerprint(
                    stage="preflight_copy_probe",
                    code="P5_GUEST_CHANNEL_NOT_READY",
                    message=(
                        "Guest file-copy channel not ready after retries; "
                        "copy probe failed"
                    ),
                )
            )
            _write_json(
                config.evidence_file,
                {
                    "milestone": "Priority-5",
                    "timestamp": _timestamp(),
                    "disposition": "FAIL",
                    "vm_state_before": vm_state_before.value,
                    "failure_fingerprints": fingerprints,
                },
            )
            return False

    guest_bundle_path = f"{config.guest_root}/runtime_bundle.zip"
    guest_bootstrap_path = f"{config.guest_root}/bootstrap_runtime.sh"

    with tempfile.TemporaryDirectory(prefix="blarai-p5-") as tmp_dir:
        tmp_path = Path(tmp_dir)
        bundle_path = tmp_path / "runtime_bundle.zip"

        bundle_ok, bundle_msg = _build_bundle(
            repo_root=repo_root,
            bundle_path=bundle_path,
            include_models=config.include_models,
        )
        if not bundle_ok:
            fingerprints.append(
                _failure_fingerprint(
                    stage="bundle",
                    code="P5_BUNDLE_BUILD_FAILED",
                    message=bundle_msg,
                )
            )
            _write_json(
                config.evidence_file,
                {
                    "milestone": "Priority-5",
                    "timestamp": _timestamp(),
                    "disposition": "FAIL",
                    "vm_state_before": vm_state_before.value,
                    "failure_fingerprints": fingerprints,
                },
            )
            return False

        bootstrap_source = repo_root / "scripts" / "guest" / "bootstrap_runtime.sh"

        copy_bundle_ok = copy_file_to_vm(
            source_path=bundle_path,
            destination_path=guest_bundle_path,
            vm_name=config.vm_name,
            timeout=900.0,
        )
        if not copy_bundle_ok:
            fingerprints.append(
                _failure_fingerprint(
                    stage="copy",
                    code="P5_COPY_BUNDLE_FAILED",
                    message=f"Copy-VMFile failed for {guest_bundle_path}",
                )
            )
            _write_json(
                config.evidence_file,
                {
                    "milestone": "Priority-5",
                    "timestamp": _timestamp(),
                    "disposition": "FAIL",
                    "vm_state_before": vm_state_before.value,
                    "failure_fingerprints": fingerprints,
                },
            )
            return False

        copy_bootstrap_ok = copy_file_to_vm(
            source_path=bootstrap_source,
            destination_path=guest_bootstrap_path,
            vm_name=config.vm_name,
            timeout=120.0,
        )
        if not copy_bootstrap_ok:
            fingerprints.append(
                _failure_fingerprint(
                    stage="copy",
                    code="P5_COPY_BOOTSTRAP_FAILED",
                    message=f"Copy-VMFile failed for {guest_bootstrap_path}",
                )
            )
            _write_json(
                config.evidence_file,
                {
                    "milestone": "Priority-5",
                    "timestamp": _timestamp(),
                    "disposition": "FAIL",
                    "vm_state_before": vm_state_before.value,
                    "failure_fingerprints": fingerprints,
                },
            )
            return False

    _write_json(
        config.evidence_file,
        {
            "milestone": "Priority-5",
            "timestamp": _timestamp(),
            "disposition": "PASS",
            "vm_name": config.vm_name,
            "vm_state_before": vm_state_before.value,
            "vm_state_after": VMState.RUNNING.value,
            "guest_service_interface_enabled": True,
            "vsock_topology_validation": {
                "passed": True,
                "source": "phase2_gates/evidence/vsock_validation.json",
            },
            "artifacts": {
                "bundle_destination": guest_bundle_path,
                "bootstrap_destination": guest_bootstrap_path,
                "include_models": config.include_models,
            },
            "guest_startup": {
                "invocation_mode": "manual-in-guest",
                "command": (
                    f"chmod +x {guest_bootstrap_path} && "
                    f"{guest_bootstrap_path} {config.guest_root} {guest_bundle_path}"
                ),
                "expected_evidence": f"{config.guest_root}/evidence/priority5_guest_startup.json",
            },
            "config_preflight": {
                "deployment_mode": "guest",
                "policy_agent": "PASS",
                "assistant_orchestrator": "PASS",
            },
            "failure_fingerprints": fingerprints,
        },
    )
    return True


def _parse_args() -> GuestDeployConfig:
    parser = argparse.ArgumentParser(description="Priority-5 guest runtime deploy")
    parser.add_argument(
        "--vm-name",
        default=ORCHESTRATOR_VM_NAME,
        help="Hyper-V VM name",
    )
    parser.add_argument(
        "--guest-root",
        default="/opt/blarai",
        help="Guest root directory for deployment",
    )
    parser.add_argument(
        "--evidence-file",
        default="phase2_gates/evidence/priority5_guest_deploy.json",
        help="Host-side evidence JSON output path",
    )
    parser.add_argument(
        "--exclude-models",
        action="store_true",
        help="Skip model artifact packaging (not recommended for operational run)",
    )
    args = parser.parse_args()

    return GuestDeployConfig(
        vm_name=args.vm_name,
        guest_root=args.guest_root,
        evidence_file=Path(args.evidence_file),
        include_models=not bool(args.exclude_models),
    )


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    config = _parse_args()
    ok = deploy_guest_runtime(config)
    if not ok:
        logger.error("Priority-5 guest deployment failed (Fail-Closed)")
        return 1
    logger.info("Priority-5 guest deployment completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
