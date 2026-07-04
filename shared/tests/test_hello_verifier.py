r"""Tests for the Windows-Hello biometric approval verifier (shared/security/hello_verifier.py).

Vikunja #649 / ADR-024 §2.5 — the biometric implementation of the
``shared.security.escalation_consent.ApprovalVerifier`` Protocol. It reaches Windows
Hello by spawning a tiny C# helper exe and reading its exit code (0 == Verified /
Available). These tests prove the load-bearing FAIL-CLOSED contract WITHOUT ever
raising the real Hello prompt (that needs a human fingerprint — it is the LA's on-box
live-verify via ``scripts/demo_escalation_hello.py``):

  - exit 0 → allow; ANY other outcome → deny:
      * non-zero exit (operator cancelled / not verified / device issue) → deny,
      * helper exe missing → deny,
      * subprocess timeout → deny,
      * OSError on spawn → deny,
      * any other exception → deny,
      * (defence-in-depth) only an explicit 0 allows;
  - the Hello-dialog message carries the SAFE descriptor only — never a raw secret,
    and it is passed as a single argv entry (never a shell command line);
  - ``is_available()`` parses ``--check`` correctly (0 → True; non-zero/missing/
    timeout/exception → False) and caches the result (re-probe only with force=True);
  - the verifier satisfies the ApprovalVerifier Protocol and registers via the seam.

Every subprocess call is mocked; no real exe runs and no dialog appears.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from shared.security import hello_verifier as hv
from shared.security.escalation_consent import (
    ApprovalResult,
    ApprovalVerifier,
    EscalationContext,
    active_verifier,
    clear_verifier,
    register_verifier,
    request_escalation_consent,
)
from shared.security.hello_verifier import BiometricApprovalVerifier


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_verifier_around_each_test():
    """Guarantee a clean (no verifier) registry before and after every test."""
    clear_verifier()
    yield
    clear_verifier()


@pytest.fixture
def fake_exe(tmp_path: Path) -> Path:
    """An on-disk file standing in for the built helper exe.

    Its presence satisfies the verifier's ``is_file()`` guard; it is NEVER executed
    because ``subprocess.run`` is mocked in every test that gets this far.
    """
    exe = tmp_path / "BlarAI.HelloVerify.exe"
    exe.write_bytes(b"MZ")  # token bytes; never run
    return exe


def _ctx() -> EscalationContext:
    """A representative SAFE context (labels/descriptors only)."""
    return EscalationContext.from_pa_verdict(
        "ESCALATE_CRYPTO_MATERIAL",
        tool_name="read_keystore",
        action_summary="READ /keystore/master.key",
    )


class _FakeCompleted:
    """Minimal stand-in for subprocess.CompletedProcess (only returncode is read)."""

    def __init__(self, returncode: int) -> None:
        self.returncode = returncode
        self.stdout = ""
        self.stderr = ""


def _patch_run(monkeypatch, *, returncode=None, raises=None, capture: list | None = None):
    """Patch shared.security.hello_verifier's subprocess.run.

    Either returns a _FakeCompleted(returncode) or raises ``raises``. When ``capture``
    is provided, the call's (args, kwargs) tuple is appended to it for assertions.
    """

    def _fake_run(*args, **kwargs):
        if capture is not None:
            capture.append((args, kwargs))
        if raises is not None:
            raise raises
        return _FakeCompleted(returncode)

    monkeypatch.setattr(hv.subprocess, "run", _fake_run)


# ---------------------------------------------------------------------------
# verify() — the allow path
# ---------------------------------------------------------------------------


def test_verify_exit_zero_allows(monkeypatch, fake_exe):
    _patch_run(monkeypatch, returncode=0)
    verifier = BiometricApprovalVerifier(exe_path=fake_exe)

    result = verifier.verify(_ctx())

    assert isinstance(result, ApprovalResult)
    assert result.approved is True
    assert result.verifier_identity == "hello"


def test_verify_allow_flows_through_consumer(monkeypatch, fake_exe):
    """End-to-end through request_escalation_consent: exit 0 → approved."""
    _patch_run(monkeypatch, returncode=0)
    register_verifier(BiometricApprovalVerifier(exe_path=fake_exe))

    result = request_escalation_consent(_ctx(), timeout_s=5.0)

    assert result.approved is True
    assert result.verifier_identity == "hello"


# ---------------------------------------------------------------------------
# verify() — the FAIL-CLOSED deny paths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rc", [15, 14, 13, 12, 11, 10, 1, 30, 19, 255, -1])
def test_verify_nonzero_denies(monkeypatch, fake_exe, rc):
    """Any non-zero helper exit is a denial (operator cancel / device / error)."""
    _patch_run(monkeypatch, returncode=rc)
    verifier = BiometricApprovalVerifier(exe_path=fake_exe)

    result = verifier.verify(_ctx())

    assert result.approved is False
    assert result.verifier_identity == "hello"
    # The exit code is surfaced in the reason for the audit record.
    assert str(rc) in result.reason


def test_verify_missing_helper_denies(tmp_path):
    """Helper exe absent → deny, without ever calling subprocess."""
    missing = tmp_path / "does_not_exist.exe"
    verifier = BiometricApprovalVerifier(exe_path=missing)

    result = verifier.verify(_ctx())

    assert result.approved is False
    assert "not found" in result.reason.lower()


def test_verify_missing_helper_does_not_spawn(monkeypatch, tmp_path):
    """The is_file() guard must short-circuit BEFORE any subprocess.run call."""
    called = {"ran": False}

    def _boom(*a, **k):
        called["ran"] = True
        raise AssertionError("subprocess.run must not be called when exe is missing")

    monkeypatch.setattr(hv.subprocess, "run", _boom)
    verifier = BiometricApprovalVerifier(exe_path=tmp_path / "nope.exe")

    result = verifier.verify(_ctx())

    assert result.approved is False
    assert called["ran"] is False


def test_verify_timeout_denies(monkeypatch, fake_exe):
    """A wedged/unanswered Hello dialog (TimeoutExpired) → deny."""
    _patch_run(
        monkeypatch,
        raises=subprocess.TimeoutExpired(cmd="hello", timeout=125.0),
    )
    verifier = BiometricApprovalVerifier(exe_path=fake_exe)

    result = verifier.verify(_ctx())

    assert result.approved is False
    assert result.reason == "timeout"
    assert result.verifier_identity == "hello"


def test_verify_oserror_denies(monkeypatch, fake_exe):
    """A spawn failure (OSError) → deny."""
    _patch_run(monkeypatch, raises=OSError("exec format error"))
    verifier = BiometricApprovalVerifier(exe_path=fake_exe)

    result = verifier.verify(_ctx())

    assert result.approved is False
    assert "spawn error" in result.reason


def test_verify_generic_exception_denies(monkeypatch, fake_exe):
    """ANY other exception → deny (fail-closed catch-all)."""
    _patch_run(monkeypatch, raises=ValueError("unexpected"))
    verifier = BiometricApprovalVerifier(exe_path=fake_exe)

    result = verifier.verify(_ctx())

    assert result.approved is False
    assert "error" in result.reason.lower()


def test_verify_exception_flows_closed_through_consumer(monkeypatch, fake_exe):
    """The verifier swallows its own errors, so the consumer sees a clean deny."""
    _patch_run(monkeypatch, raises=RuntimeError("boom"))
    register_verifier(BiometricApprovalVerifier(exe_path=fake_exe))

    result = request_escalation_consent(_ctx(), timeout_s=5.0)

    assert result.approved is False


# ---------------------------------------------------------------------------
# The message carries no secret + is a single argv entry
# ---------------------------------------------------------------------------


def test_message_contains_only_safe_descriptor(monkeypatch, fake_exe):
    """The Hello-dialog message is built from context.describe() — labels only."""
    capture: list = []
    _patch_run(monkeypatch, returncode=0, capture=capture)
    verifier = BiometricApprovalVerifier(exe_path=fake_exe)

    verifier.verify(_ctx())

    assert capture, "subprocess.run was not called"
    (call_args, _call_kwargs) = capture[0]
    argv = call_args[0]
    # argv = [exe_path, message]
    assert argv[0] == str(fake_exe)
    assert len(argv) == 2, "message must be exactly ONE argv entry, never a shell line"
    message = argv[1]
    # The safe descriptor is present...
    assert "ESCALATE_CRYPTO_MATERIAL" in message
    assert "READ /keystore/master.key" in message
    # ...and the describe() output is exactly what got embedded (no extra fields).
    assert _ctx().describe() in message


def test_message_does_not_leak_raw_argument_path(monkeypatch, fake_exe):
    """A secret never reaches the argv: from_pa_verdict only takes safe descriptors.

    EscalationContext has no field for raw tool arguments, so even a 'secret-looking'
    value can only enter via the action_summary the CALLER deems safe. This test
    documents that the verifier embeds describe() verbatim and adds no other source.
    """
    capture: list = []
    _patch_run(monkeypatch, returncode=0, capture=capture)
    verifier = BiometricApprovalVerifier(exe_path=fake_exe)

    ctx = EscalationContext.from_pa_verdict(
        "ESCALATE_LARGE_WRITE",
        tool_name="write_file",
        action_summary="WRITE /home/user/dump.bin (~250 MB)",
    )
    verifier.verify(ctx)

    message = capture[0][0][0][1]
    # Only the safe summary appears; the message equals the prefix + describe().
    assert message == f"BlarAI — approve escalated action? {ctx.describe()}"


def test_egress_source_uses_web_search_prompt_wording(monkeypatch, fake_exe):
    """ADR-023 Amendment 4 (#723 rung 3): a context with source='egress' reads as
    an outbound-web-search consent, not an escalated-action approval — the same
    verifier, a source-appropriate prompt. The operator is approving content
    LEAVING the machine, a materially different act than a local action."""
    capture: list = []
    _patch_run(monkeypatch, returncode=0, capture=capture)
    verifier = BiometricApprovalVerifier(exe_path=fake_exe)

    ctx = EscalationContext(
        rule_label="EGRESS_WEB_SEARCH",
        action_summary="Search the web: bitcoin price (one approval covers up to 3 searches for this question)",
        tool_name="web_search",
        source="egress",
    )
    verifier.verify(ctx)

    message = capture[0][0][0][1]
    assert message == f"BlarAI — allow this outbound web search? {ctx.describe()}"
    # The exact query the operator must judge is surfaced in the dialog.
    assert "bitcoin price" in message
    # And a PA ESCALATE (default source) still reads as an escalated action.
    assert BiometricApprovalVerifier._safe_message(_ctx()).startswith(
        "BlarAI — approve escalated action?"
    )


def test_run_uses_no_shell(monkeypatch, fake_exe):
    """subprocess.run must be called WITHOUT shell=True (argv form only)."""
    capture: list = []
    _patch_run(monkeypatch, returncode=0, capture=capture)
    verifier = BiometricApprovalVerifier(exe_path=fake_exe)

    verifier.verify(_ctx())

    (_call_args, call_kwargs) = capture[0]
    assert call_kwargs.get("shell", False) is False
    # And a finite timeout is always passed (fail-closed bound).
    assert call_kwargs.get("timeout") is not None


# ---------------------------------------------------------------------------
# is_available() — the launcher startup probe
# ---------------------------------------------------------------------------


def test_is_available_true_on_exit_zero(monkeypatch, fake_exe):
    capture: list = []
    _patch_run(monkeypatch, returncode=0, capture=capture)
    verifier = BiometricApprovalVerifier(exe_path=fake_exe)

    assert verifier.is_available() is True
    # It invoked the helper with --check.
    argv = capture[0][0][0]
    assert argv == [str(fake_exe), "--check"]


@pytest.mark.parametrize("rc", [10, 11, 12, 13, 19, 1, 30])
def test_is_available_false_on_nonzero(monkeypatch, fake_exe, rc):
    _patch_run(monkeypatch, returncode=rc)
    verifier = BiometricApprovalVerifier(exe_path=fake_exe)

    assert verifier.is_available() is False


def test_is_available_false_when_missing(tmp_path):
    verifier = BiometricApprovalVerifier(exe_path=tmp_path / "absent.exe")
    assert verifier.is_available() is False


def test_is_available_false_on_timeout(monkeypatch, fake_exe):
    _patch_run(
        monkeypatch, raises=subprocess.TimeoutExpired(cmd="hello", timeout=15.0)
    )
    verifier = BiometricApprovalVerifier(exe_path=fake_exe)

    assert verifier.is_available() is False


def test_is_available_false_on_exception(monkeypatch, fake_exe):
    _patch_run(monkeypatch, raises=OSError("nope"))
    verifier = BiometricApprovalVerifier(exe_path=fake_exe)

    assert verifier.is_available() is False


def test_is_available_caches(monkeypatch, fake_exe):
    """The probe runs once and is cached; a later state change is not re-read."""
    calls = {"n": 0}

    def _fake_run(*a, **k):
        calls["n"] += 1
        return _FakeCompleted(0)

    monkeypatch.setattr(hv.subprocess, "run", _fake_run)
    verifier = BiometricApprovalVerifier(exe_path=fake_exe)

    assert verifier.is_available() is True
    assert verifier.is_available() is True
    assert verifier.is_available() is True
    assert calls["n"] == 1, "is_available must cache (one probe per process)"


def test_is_available_force_reprobes(monkeypatch, fake_exe):
    """force=True bypasses the cache and re-runs the probe."""
    calls = {"n": 0}

    def _fake_run(*a, **k):
        calls["n"] += 1
        return _FakeCompleted(0)

    monkeypatch.setattr(hv.subprocess, "run", _fake_run)
    verifier = BiometricApprovalVerifier(exe_path=fake_exe)

    assert verifier.is_available() is True
    assert verifier.is_available(force=True) is True
    assert calls["n"] == 2


# ---------------------------------------------------------------------------
# Protocol conformance + path resolution
# ---------------------------------------------------------------------------


def test_satisfies_approval_verifier_protocol(fake_exe):
    verifier = BiometricApprovalVerifier(exe_path=fake_exe)
    assert isinstance(verifier, ApprovalVerifier)


def test_registers_via_seam(fake_exe):
    verifier = BiometricApprovalVerifier(exe_path=fake_exe)
    register_verifier(verifier)
    assert active_verifier() is verifier


def test_exe_path_defaults_to_repo_root_rel():
    """With no explicit path, the default resolves to <repo_root>/HELLO_EXE_REL."""
    verifier = BiometricApprovalVerifier()
    expected = hv._default_repo_root() / hv.HELLO_EXE_REL
    assert verifier.exe_path == expected
    # And the relative path matches the Release output of the helper csproj.
    assert verifier.exe_path.name == "BlarAI.HelloVerify.exe"
    assert "Release" in str(verifier.exe_path)


def test_exe_path_explicit_is_honoured(fake_exe):
    verifier = BiometricApprovalVerifier(exe_path=fake_exe)
    assert verifier.exe_path == fake_exe


def test_str_path_accepted(fake_exe):
    """exe_path accepts a str as well as a Path."""
    verifier = BiometricApprovalVerifier(exe_path=str(fake_exe))
    assert verifier.exe_path == fake_exe
