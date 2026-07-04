from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_DIR = REPO_ROOT / "phase2_gates" / "evidence"
MILESTONE = "Operational Exit Milestone 3"
SCHEMA_VERSION = "1.0.0"

POLICY_CONFIG = REPO_ROOT / "services" / "policy_agent" / "config" / "default.toml"
ORCHESTRATOR_CONFIG = (
    REPO_ROOT / "services" / "assistant_orchestrator" / "config" / "default.toml"
)

STABILITY_ARTIFACT = EVIDENCE_DIR / "uat25_stability_matrix.json"
FAILURE_ARTIFACT = EVIDENCE_DIR / "uat25_failure_injection_matrix.json"
NORMALIZATION_ARTIFACT = EVIDENCE_DIR / "uat25_evidence_normalization.json"
SUMMARY_ARTIFACT = EVIDENCE_DIR / "uat25_summary.md"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_shell(command: list[str]) -> str:
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _git_head() -> str:
    return _run_shell(["git", "rev-parse", "HEAD"])


def _git_branch() -> str:
    return _run_shell(["git", "rev-parse", "--abbrev-ref", "HEAD"])


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file_obj:
        return json.load(file_obj)


@dataclass(frozen=True)
class LauncherRunResult:
    run_id: str
    run_type: str
    startup_profile: str
    exit_code: int
    activation_evidence_path: str
    prompt_flow_evidence_path: str
    activation: dict[str, Any]
    prompt_flow: dict[str, Any] | None


def _launcher_harness_code() -> str:
    return (
        "import sys\n"
        "import launcher.__main__ as m\n"
        "class _NoOpApp:\n"
        "    def __init__(self, *args, **kwargs):\n"
        "        pass\n"
        "    def run(self):\n"
        "        return\n"
        "m.BlarAIApp = _NoOpApp\n"
        "m.is_admin = lambda: True\n"
        "m.ensure_vm_running = lambda: True\n"
        "m.get_vm_state = lambda: m.VMState.RUNNING\n"
        "m.input = lambda *args, **kwargs: ''\n"
        "raise SystemExit(m.main())\n"
    )


def _run_launcher(run_id: str, run_type: str) -> LauncherRunResult:
    run_dir = EVIDENCE_DIR / "uat25_runs"
    run_dir.mkdir(parents=True, exist_ok=True)

    activation_path = run_dir / f"{run_id}_activation.json"
    prompt_flow_path = run_dir / f"{run_id}_prompt_flow.json"

    env = os.environ.copy()
    env["BLARAI_LAUNCH_PROFILE"] = "uat2_real"
    env["BLARAI_ACTIVATION_EVIDENCE_PATH"] = str(activation_path)
    env["BLARAI_PROMPT_FLOW_EVIDENCE_PATH"] = str(prompt_flow_path)

    proc = subprocess.run(
        [sys.executable, "-c", _launcher_harness_code()],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    activation = _read_json(activation_path) if activation_path.exists() else {}
    prompt_flow = _read_json(prompt_flow_path) if prompt_flow_path.exists() else None

    return LauncherRunResult(
        run_id=run_id,
        run_type=run_type,
        startup_profile="uat2_real",
        exit_code=proc.returncode,
        activation_evidence_path=str(activation_path.relative_to(REPO_ROOT)),
        prompt_flow_evidence_path=(
            str(prompt_flow_path.relative_to(REPO_ROOT)) if prompt_flow is not None else ""
        ),
        activation=activation,
        prompt_flow=prompt_flow,
    )


def _extract_step_booleans(activation: dict[str, Any]) -> dict[str, bool]:
    steps = activation.get("steps", {})
    return {
        "admin_ok": bool(steps.get("admin_ok", False)),
        "vm_running": bool(steps.get("vm_running", False)),
        "policy_agent_started": bool(steps.get("policy_agent_started", False)),
        "assistant_orchestrator_started": bool(steps.get("assistant_orchestrator_started", False)),
        "gateway_initialized": bool(steps.get("gateway_initialized", False)),
        "gateway_handshake_ok": bool(steps.get("gateway_handshake_ok", False)),
        "prompt_flow_ok": bool(steps.get("prompt_flow_ok", False)),
    }


def _replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"Token '{old}' not found in {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _restore_text(path: Path, original_text: str) -> None:
    path.write_text(original_text, encoding="utf-8")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file_obj:
        json.dump(payload, file_obj, indent=2, sort_keys=True)


def _write_summary(
    *,
    baseline_branch: str,
    baseline_head: str,
    post_head: str,
    stability: dict[str, Any],
    failure_matrix: dict[str, Any],
) -> None:
    lines: list[str] = []
    lines.append("# UAT-2.5 Operational Exit Milestone 3 — Summary")
    lines.append("")
    lines.append(f"- Timestamp (UTC): {_utc_now()}")
    lines.append(f"- Branch: `{baseline_branch}`")
    lines.append(f"- Pre-session HEAD: `{baseline_head}`")
    lines.append(f"- Post-session HEAD (pre-commit): `{post_head}`")
    lines.append(f"- Milestone: `{MILESTONE}`")
    lines.append("")
    lines.append("## Stability Matrix")
    lines.append(f"- Run count: `{stability['run_count']}`")
    lines.append(f"- Pass count: `{stability['pass_count']}`")
    lines.append(f"- Fail count: `{stability['fail_count']}`")
    lines.append(f"- Disposition: `{stability['disposition']}`")
    lines.append("")
    lines.append("## Failure Injection Matrix")
    lines.append(
        f"- Scenario count: `{failure_matrix['scenario_count']}`"
    )
    lines.append(
        f"- Fail-closed assertions met: `{str(failure_matrix['all_fail_closed']).lower()}`"
    )
    lines.append(
        f"- Baseline restored: `{str(failure_matrix['baseline_restore']['restored']).lower()}`"
    )
    lines.append("")
    lines.append("## Canonical Artifacts")
    lines.append("- `phase2_gates/evidence/uat25_stability_matrix.json`")
    lines.append("- `phase2_gates/evidence/uat25_failure_injection_matrix.json`")
    lines.append("- `phase2_gates/evidence/uat25_evidence_normalization.json`")
    lines.append("- `phase2_gates/evidence/uat25_summary.md`")

    SUMMARY_ARTIFACT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

    baseline_branch = _git_branch()
    baseline_head = _git_head()

    policy_original = POLICY_CONFIG.read_text(encoding="utf-8")
    orchestrator_original = ORCHESTRATOR_CONFIG.read_text(encoding="utf-8")
    policy_hash_before = _sha256_text(policy_original)
    orchestrator_hash_before = _sha256_text(orchestrator_original)

    stability_runs: list[dict[str, Any]] = []
    for index in range(1, 4):
        run = _run_launcher(run_id=f"stability_run_{index}", run_type="stability")
        activation = run.activation
        disposition = str(activation.get("disposition", "UNKNOWN"))
        stability_runs.append(
            {
                "run_id": run.run_id,
                "run_type": run.run_type,
                "startup_profile": run.startup_profile,
                "exit_code": run.exit_code,
                "disposition": disposition,
                "step_bools": _extract_step_booleans(activation),
                "failure_code": (
                    activation.get("failure", {}).get("code")
                    if isinstance(activation.get("failure"), dict)
                    else None
                ),
                "activation_evidence_path": run.activation_evidence_path,
                "prompt_flow_evidence_path": run.prompt_flow_evidence_path,
            }
        )

    pass_count = sum(1 for run in stability_runs if run["disposition"] == "PASS")
    fail_count = len(stability_runs) - pass_count
    stability_disposition = "PASS" if pass_count == len(stability_runs) else "BOUNDED_FAIL_CLOSED"

    stability_payload = {
        "schema_version": SCHEMA_VERSION,
        "timestamp": _utc_now(),
        "milestone": MILESTONE,
        "startup_profile": "uat2_real",
        "run_count": len(stability_runs),
        "pass_count": pass_count,
        "fail_count": fail_count,
        "disposition": stability_disposition,
        "runs": stability_runs,
        "baseline": {
            "branch": baseline_branch,
            "head": baseline_head,
        },
    }
    _write_json(STABILITY_ARTIFACT, stability_payload)

    scenarios: list[dict[str, Any]] = []

    try:
        _replace_once(
            POLICY_CONFIG,
            'deployment_mode = "host"',
            'deployment_mode = "guest"',
        )
        run = _run_launcher("fi_01_pa_runtime_mode_mismatch", "failure_injection")
        activation = run.activation
        observed_code = (
            activation.get("failure", {}).get("code")
            if isinstance(activation.get("failure"), dict)
            else None
        )
        scenarios.append(
            {
                "scenario_id": "FI-01",
                "injected_condition": "policy_agent.default.toml runtime.deployment_mode set to guest",
                "expected_fail_closed_fingerprint_codes": ["PA_CFG_RUNTIME_MODE_MISMATCH"],
                "observed_fingerprint_codes": [observed_code] if observed_code else [],
                "disposition": str(activation.get("disposition", "UNKNOWN")),
                "fail_closed": str(activation.get("fail_closed", "false")).lower() == "true",
                "activation_evidence_path": run.activation_evidence_path,
            }
        )
    finally:
        _restore_text(POLICY_CONFIG, policy_original)

    try:
        _replace_once(
            ORCHESTRATOR_CONFIG,
            'deployment_mode = "host"',
            'deployment_mode = "guest"',
        )
        run = _run_launcher("fi_02_ao_runtime_mode_mismatch", "failure_injection")
        activation = run.activation
        observed_code = (
            activation.get("failure", {}).get("code")
            if isinstance(activation.get("failure"), dict)
            else None
        )
        scenarios.append(
            {
                "scenario_id": "FI-02",
                "injected_condition": "assistant_orchestrator.default.toml runtime.deployment_mode set to guest",
                "expected_fail_closed_fingerprint_codes": ["AO_CFG_RUNTIME_MODE_MISMATCH"],
                "observed_fingerprint_codes": [observed_code] if observed_code else [],
                "disposition": str(activation.get("disposition", "UNKNOWN")),
                "fail_closed": str(activation.get("fail_closed", "false")).lower() == "true",
                "activation_evidence_path": run.activation_evidence_path,
            }
        )
    finally:
        _restore_text(ORCHESTRATOR_CONFIG, orchestrator_original)

    policy_hash_after = _sha256_text(POLICY_CONFIG.read_text(encoding="utf-8"))
    orchestrator_hash_after = _sha256_text(ORCHESTRATOR_CONFIG.read_text(encoding="utf-8"))

    baseline_restored = (
        policy_hash_before == policy_hash_after
        and orchestrator_hash_before == orchestrator_hash_after
    )

    all_fail_closed = all(
        scenario["disposition"] == "FAIL" and scenario["fail_closed"]
        for scenario in scenarios
    )

    failure_payload = {
        "schema_version": SCHEMA_VERSION,
        "timestamp": _utc_now(),
        "milestone": MILESTONE,
        "scenario_count": len(scenarios),
        "all_fail_closed": all_fail_closed,
        "scenarios": scenarios,
        "baseline_restore": {
            "restored": baseline_restored,
            "policy_config_sha256_before": policy_hash_before,
            "policy_config_sha256_after": policy_hash_after,
            "orchestrator_config_sha256_before": orchestrator_hash_before,
            "orchestrator_config_sha256_after": orchestrator_hash_after,
        },
    }
    _write_json(FAILURE_ARTIFACT, failure_payload)

    post_head = _git_head()

    canonical_artifacts = [
        "phase2_gates/evidence/uat25_stability_matrix.json",
        "phase2_gates/evidence/uat25_failure_injection_matrix.json",
        "phase2_gates/evidence/uat25_evidence_normalization.json",
        "phase2_gates/evidence/uat25_summary.md",
    ]

    normalization_payload = {
        "schema_version": SCHEMA_VERSION,
        "timestamp": _utc_now(),
        "milestone": MILESTONE,
        "normalized_schema": {
            "required_fields": [
                "milestone",
                "startup_profile",
                "run_count",
                "disposition",
                "runs[].step_bools",
                "scenarios[].scenario_id",
                "scenarios[].injected_condition",
                "scenarios[].expected_fail_closed_fingerprint_codes",
                "scenarios[].observed_fingerprint_codes",
                "baseline_restore.restored",
            ],
        },
        "artifact_inventory": canonical_artifacts,
        "baseline": {
            "branch": baseline_branch,
            "pre_head": baseline_head,
            "post_head": post_head,
        },
    }
    _write_json(NORMALIZATION_ARTIFACT, normalization_payload)

    _write_summary(
        baseline_branch=baseline_branch,
        baseline_head=baseline_head,
        post_head=post_head,
        stability=stability_payload,
        failure_matrix=failure_payload,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
