"""Tests for functional measured-boot sequencing and retry behavior."""

from __future__ import annotations

from services.policy_agent.src.boot import (
    BootState,
    MeasuredBootPolicy,
    MeasuredBootStep,
    run_measured_boot,
)


def test_run_measured_boot_success_sets_ready() -> None:
    calls: list[str] = []

    steps = [
        MeasuredBootStep(
            name="attestation",
            state_field="attestation_verified",
            action=lambda: calls.append("attestation") is None or True,
            error_code="PA_BOOT_ATTESTATION_FAILED",
        ),
        MeasuredBootStep(
            name="weights",
            state_field="weights_verified",
            action=lambda: calls.append("weights") is None or True,
            error_code="PA_BOOT_WEIGHT_VERIFY_FAILED",
        ),
        MeasuredBootStep(
            name="model",
            state_field="npu_model_loaded",
            action=lambda: calls.append("model") is None or True,
            error_code="PA_MODEL_LOAD_FAILED",
        ),
        MeasuredBootStep(
            name="rules",
            state_field="rules_loaded",
            action=lambda: calls.append("rules") is None or True,
            error_code="PA_RULE_CONFIG_LOAD_FAILED",
        ),
        MeasuredBootStep(
            name="listener",
            state_field="listener_started",
            action=lambda: calls.append("listener") is None or True,
            error_code="PA_LISTENER_START_FAILED",
        ),
    ]

    state = run_measured_boot(
        "services/policy_agent/config/default.toml",
        steps=steps,
        policy=MeasuredBootPolicy(max_attempts=3, retry_delay_s=0),
        sleep_fn=lambda _delay: None,
    )

    assert state.ready is True
    assert state.hard_locked is False
    assert state.attempt_count == 1
    assert calls == ["attestation", "weights", "model", "rules", "listener"]
    # WI-8: step-field booleans pin the step-to-state mapping. A typo in a
    # step's state_field would not be caught by state.ready alone.
    assert state.config_loaded is True
    assert state.attestation_verified is True
    assert state.weights_verified is True
    assert state.npu_model_loaded is True
    assert state.rules_loaded is True
    assert state.listener_started is True


def test_run_measured_boot_retries_then_succeeds() -> None:
    attempts = {"count": 0}

    def fail_once_then_pass() -> bool:
        attempts["count"] += 1
        return attempts["count"] > 1

    steps = [
        MeasuredBootStep(
            name="attestation",
            state_field="attestation_verified",
            action=fail_once_then_pass,
            error_code="PA_BOOT_ATTESTATION_FAILED",
        ),
    ]

    state = run_measured_boot(
        "services/policy_agent/config/default.toml",
        steps=steps,
        policy=MeasuredBootPolicy(max_attempts=3, retry_delay_s=0),
        sleep_fn=lambda _delay: None,
    )

    assert state.ready is True
    assert state.attempt_count == 2
    assert state.hard_locked is False


def test_run_measured_boot_hard_locks_after_max_attempts() -> None:
    steps = [
        MeasuredBootStep(
            name="attestation",
            state_field="attestation_verified",
            action=lambda: False,
            error_code="PA_BOOT_ATTESTATION_FAILED",
        ),
    ]

    state = run_measured_boot(
        "services/policy_agent/config/default.toml",
        steps=steps,
        policy=MeasuredBootPolicy(max_attempts=3, retry_delay_s=0),
        sleep_fn=lambda _delay: None,
    )

    assert state.ready is False
    assert state.hard_locked is True
    assert state.attempt_count == 3
    assert state.error_code == "PA_BOOT_ATTESTATION_FAILED"


# ---------------------------------------------------------------------------
# WI-4: Exception-in-action path
# ---------------------------------------------------------------------------

def test_run_measured_boot_action_raises_exception_fails_closed() -> None:
    """A step whose action() raises is treated as fail-closed; state.error_code
    is the step's own error_code (not a generic PA_BOOT_UNKNOWN_FAILURE) and
    state.error_message carries the exception text.
    """

    def _raising_action() -> bool:
        raise RuntimeError("test boot exception")

    steps = [
        MeasuredBootStep(
            name="raising_step",
            state_field="attestation_verified",
            action=_raising_action,
            error_code="PA_BOOT_ATTESTATION_FAILED",
        ),
    ]

    state = run_measured_boot(
        "services/policy_agent/config/default.toml",
        steps=steps,
        policy=MeasuredBootPolicy(max_attempts=2, retry_delay_s=0),
        sleep_fn=lambda _delay: None,
    )

    assert state.ready is False
    assert state.hard_locked is True
    assert state.error_code == "PA_BOOT_ATTESTATION_FAILED"
    assert state.error_message is not None
    assert "test boot exception" in state.error_message


# ---------------------------------------------------------------------------
# WI-5: BootState.failed_step property (direct, not via run_measured_boot)
# ---------------------------------------------------------------------------

def test_failed_step_returns_none_when_all_passed() -> None:
    state = BootState(
        config_loaded=True,
        attestation_verified=True,
        weights_verified=True,
        npu_model_loaded=True,
        rules_loaded=True,
        listener_started=True,
    )
    assert state.failed_step is None


def test_failed_step_returns_first_incomplete_field() -> None:
    state = BootState(
        config_loaded=True,
        attestation_verified=True,
        weights_verified=False,
    )
    assert state.failed_step == "weights_verified"


def test_failed_step_returns_config_loaded_when_nothing_set() -> None:
    state = BootState()
    assert state.failed_step == "config_loaded"


# ---------------------------------------------------------------------------
# WI-6: dev_mode parameter is currently a no-op at HEAD c6f429d
# ---------------------------------------------------------------------------

def test_dev_mode_parameter_accepted_without_error() -> None:
    """Documents current production behavior: at HEAD c6f429d `run_measured_boot`
    assigns `_ = dev_mode` and does not branch on it. Passing dev_mode=True vs
    dev_mode=False does not alter state. If dev_mode is later wired to bypass
    attestation, this test must be revisited.
    """

    def _always_ok() -> bool:
        return True

    def _one_success_step() -> list[MeasuredBootStep]:
        return [
            MeasuredBootStep(
                name="attestation",
                state_field="attestation_verified",
                action=_always_ok,
                error_code="PA_BOOT_ATTESTATION_FAILED",
            ),
        ]

    state_dev = run_measured_boot(
        "services/policy_agent/config/default.toml",
        dev_mode=True,
        steps=_one_success_step(),
        policy=MeasuredBootPolicy(max_attempts=1, retry_delay_s=0),
        sleep_fn=lambda _delay: None,
    )
    state_prod = run_measured_boot(
        "services/policy_agent/config/default.toml",
        dev_mode=False,
        steps=_one_success_step(),
        policy=MeasuredBootPolicy(max_attempts=1, retry_delay_s=0),
        sleep_fn=lambda _delay: None,
    )

    assert state_dev.ready is True
    assert state_prod.ready is True
    assert state_dev.attestation_verified is True
    assert state_prod.attestation_verified is True


# ---------------------------------------------------------------------------
# WI-7: retry_delay_s is threaded through to sleep_fn
# ---------------------------------------------------------------------------

def test_measured_boot_policy_sleep_fn_receives_retry_delay() -> None:
    """sleep_fn receives the exact retry_delay_s value from the policy — not
    a hardcoded constant. Pins the sleep-injection contract: a regression
    substituting a literal delay would fail this test.
    """

    attempts = {"count": 0}

    def _fail_once_then_pass() -> bool:
        attempts["count"] += 1
        return attempts["count"] > 1

    captured_sleeps: list[float] = []

    steps = [
        MeasuredBootStep(
            name="attestation",
            state_field="attestation_verified",
            action=_fail_once_then_pass,
            error_code="PA_BOOT_ATTESTATION_FAILED",
        ),
    ]

    state = run_measured_boot(
        "services/policy_agent/config/default.toml",
        steps=steps,
        policy=MeasuredBootPolicy(max_attempts=3, retry_delay_s=0.123),
        sleep_fn=captured_sleeps.append,
    )

    assert state.ready is True
    assert state.attempt_count == 2
    assert len(captured_sleeps) == 1
    assert captured_sleeps[0] == 0.123
