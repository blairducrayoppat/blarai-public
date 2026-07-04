from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from launcher.guest_deploy import (
    GuestDeployConfig,
    _build_bundle,
    _validate_vsock_topology,
    deploy_guest_runtime,
)


def test_validate_vsock_topology_success() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    ok, issues = _validate_vsock_topology(repo_root)
    assert ok is True
    assert issues == []


def test_build_bundle_requires_runtime_files(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / "services" / "policy_agent").mkdir(parents=True)
    (repo_root / "services" / "assistant_orchestrator").mkdir(parents=True)
    (repo_root / "shared").mkdir(parents=True)

    ok, message = _build_bundle(
        repo_root=repo_root,
        bundle_path=tmp_path / "bundle.zip",
        include_models=False,
    )

    assert ok is False
    assert "required file missing" in message


@patch("launcher.guest_deploy.copy_file_to_vm", return_value=True)
@patch("launcher.guest_deploy._build_bundle", return_value=(True, "ok"))
@patch("launcher.guest_deploy._validate_vsock_topology", return_value=(True, []))
@patch("launcher.guest_deploy.AssistantOrchestratorService.validate_runtime_config", return_value=(True, None))
@patch("launcher.guest_deploy.PolicyAgentService.validate_runtime_config", return_value=(True, None))
@patch("launcher.guest_deploy.is_guest_service_interface_enabled", return_value=True)
@patch("launcher.guest_deploy.ensure_vm_running", return_value=True)
@patch("launcher.guest_deploy.get_vm_state")
def test_deploy_guest_runtime_success(
    mock_state,
    mock_ensure,
    mock_gsi,
    mock_policy_validate,
    mock_orch_validate,
    mock_vsock,
    mock_bundle,
    mock_copy,
    tmp_path: Path,
) -> None:
    class _State:
        value = "Off"

    mock_state.return_value = _State()
    config = GuestDeployConfig(
        vm_name="BlarAI-Orchestrator",
        guest_root="/opt/blarai",
        evidence_file=tmp_path / "evidence.json",
        include_models=False,
    )

    ok = deploy_guest_runtime(config)
    assert ok is True
    assert config.evidence_file.exists()

    payload = json.loads(config.evidence_file.read_text(encoding="utf-8"))
    assert payload["disposition"] == "PASS"
    assert payload["guest_service_interface_enabled"] is True


@patch("launcher.guest_deploy.ensure_vm_running", return_value=False)
@patch("launcher.guest_deploy.get_vm_state")
def test_deploy_guest_runtime_fail_closed_on_vm_start(
    mock_state,
    mock_ensure,
    tmp_path: Path,
) -> None:
    class _State:
        value = "Off"

    mock_state.return_value = _State()
    config = GuestDeployConfig(
        vm_name="BlarAI-Orchestrator",
        guest_root="/opt/blarai",
        evidence_file=tmp_path / "evidence.json",
        include_models=False,
    )

    ok = deploy_guest_runtime(config)
    assert ok is False

    payload = json.loads(config.evidence_file.read_text(encoding="utf-8"))
    assert payload["disposition"] == "FAIL"
    assert payload["failure_fingerprints"][0]["code"] == "P5_VM_START_FAILED"


# ---------------------------------------------------------------------------
# EA-4 WI-5: TestValidateVsockTopologyFailures
# ---------------------------------------------------------------------------

import pytest

from launcher.guest_deploy import _validate_guest_runtime_configs
from shared.constants import ORCHESTRATOR_VM_ID, VSOCK_PORT, VSOCK_SERVICE_GUID


def _valid_vsock_evidence() -> dict:
    """Return a baseline PASS evidence dict that tests mutate per-failure."""
    return {
        "disposition": "PASS",
        "host": {
            "vm_id": ORCHESTRATOR_VM_ID,
            "service_guid": VSOCK_SERVICE_GUID,
            "vsock_port": VSOCK_PORT,
        },
        "test": {
            "connection_successful": True,
            "tcp_ip_used": False,
        },
    }


def _write_evidence(repo_root: Path, data: dict | str | None) -> None:
    evidence_path = repo_root / "phase2_gates" / "evidence" / "vsock_validation.json"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    if data is None:
        return
    if isinstance(data, str):
        evidence_path.write_text(data, encoding="utf-8")
    else:
        evidence_path.write_text(json.dumps(data), encoding="utf-8")


class TestValidateVsockTopologyFailures:
    """Sprint 8 EA-4 WI-5: 8 distinct failure branches of _validate_vsock_topology."""

    def test_evidence_file_missing(self, tmp_path: Path) -> None:
        ok, issues = _validate_vsock_topology(tmp_path)
        assert ok is False
        assert any("evidence file missing" in i for i in issues)

    def test_evidence_malformed_json(self, tmp_path: Path) -> None:
        _write_evidence(tmp_path, "{not-valid-json")
        ok, issues = _validate_vsock_topology(tmp_path)
        assert ok is False
        assert any("unable to parse" in i for i in issues)

    def test_disposition_not_pass(self, tmp_path: Path) -> None:
        data = _valid_vsock_evidence()
        data["disposition"] = "FAIL"
        _write_evidence(tmp_path, data)
        ok, issues = _validate_vsock_topology(tmp_path)
        assert ok is False
        assert any("disposition is not PASS" in i for i in issues)

    def test_vm_id_mismatch(self, tmp_path: Path) -> None:
        data = _valid_vsock_evidence()
        data["host"]["vm_id"] = "wrong-vm-id"
        _write_evidence(tmp_path, data)
        ok, issues = _validate_vsock_topology(tmp_path)
        assert ok is False
        assert any("vm_id mismatch" in i for i in issues)

    def test_service_guid_mismatch(self, tmp_path: Path) -> None:
        data = _valid_vsock_evidence()
        data["host"]["service_guid"] = "00000000-0000-0000-0000-000000000000"
        _write_evidence(tmp_path, data)
        ok, issues = _validate_vsock_topology(tmp_path)
        assert ok is False
        assert any("service_guid mismatch" in i for i in issues)

    def test_vsock_port_mismatch(self, tmp_path: Path) -> None:
        data = _valid_vsock_evidence()
        data["host"]["vsock_port"] = 99999
        _write_evidence(tmp_path, data)
        ok, issues = _validate_vsock_topology(tmp_path)
        assert ok is False
        assert any("vsock_port mismatch" in i for i in issues)

    def test_connection_unsuccessful(self, tmp_path: Path) -> None:
        data = _valid_vsock_evidence()
        data["test"]["connection_successful"] = False
        _write_evidence(tmp_path, data)
        ok, issues = _validate_vsock_topology(tmp_path)
        assert ok is False
        assert any("connection_successful is false" in i for i in issues)

    def test_tcp_ip_used_true(self, tmp_path: Path) -> None:
        data = _valid_vsock_evidence()
        data["test"]["tcp_ip_used"] = True
        _write_evidence(tmp_path, data)
        ok, issues = _validate_vsock_topology(tmp_path)
        assert ok is False
        assert any("tcp_ip_used is true" in i for i in issues)


# ---------------------------------------------------------------------------
# EA-4 WI-6: TestValidateGuestRuntimeConfigsFailures
# ---------------------------------------------------------------------------


class TestValidateGuestRuntimeConfigsFailures:
    """Sprint 8 EA-4 WI-6: PA-fail, AO-fail, both-fail branches."""

    @patch("launcher.guest_deploy.AssistantOrchestratorService.validate_runtime_config", return_value=(True, None))
    @patch("launcher.guest_deploy.PolicyAgentService.validate_runtime_config",
           return_value=(False, {"code": "PA_BAD", "message": "pa invalid"}))
    def test_policy_agent_failure(self, _mock_pa, _mock_ao) -> None:
        ok, failures = _validate_guest_runtime_configs()
        assert ok is False
        assert len(failures) == 1
        assert failures[0]["code"] == "P6_POLICY_CONFIG_INVALID"
        assert "PA_BAD" in failures[0]["message"]

    @patch("launcher.guest_deploy.AssistantOrchestratorService.validate_runtime_config",
           return_value=(False, {"code": "AO_BAD", "message": "ao invalid"}))
    @patch("launcher.guest_deploy.PolicyAgentService.validate_runtime_config", return_value=(True, None))
    def test_orchestrator_failure(self, _mock_pa, _mock_ao) -> None:
        ok, failures = _validate_guest_runtime_configs()
        assert ok is False
        assert len(failures) == 1
        assert failures[0]["code"] == "P6_ORCH_CONFIG_INVALID"
        assert "AO_BAD" in failures[0]["message"]

    @patch("launcher.guest_deploy.AssistantOrchestratorService.validate_runtime_config",
           return_value=(False, {"code": "AO_BAD", "message": "ao invalid"}))
    @patch("launcher.guest_deploy.PolicyAgentService.validate_runtime_config",
           return_value=(False, {"code": "PA_BAD", "message": "pa invalid"}))
    def test_both_agents_fail_reports_both(self, _mock_pa, _mock_ao) -> None:
        ok, failures = _validate_guest_runtime_configs()
        assert ok is False
        assert len(failures) == 2
        codes = {f["code"] for f in failures}
        assert codes == {"P6_POLICY_CONFIG_INVALID", "P6_ORCH_CONFIG_INVALID"}
