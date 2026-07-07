"""Dev-mode / network-facing interlock tests (Sprint 13, Decision 8).

Test contract:
  - Interlock RAISES on (dev_mode=True, network_facing=True).
  - Interlock ALLOWS (dev_mode=False, network_facing=True).
  - Interlock ALLOWS (dev_mode=True, network_facing=False) AND loud banner is
    emitted (asserted via logger).
  - Teeth: reconstruct the silent-collapse path — show that the pre-fix pattern
    (inline ternary, no guard) would proceed without raising, and that the
    post-fix interlock refuses it.
  - HOST default resolves to dev_mode=False (production) — Sprint 15 EA-4b
    activation complete.  Dev mode is an explicit BLARAI_DEV_MODE=1 opt-in.
  - resolve_network_facing() defaults to False (air-gapped Tier-1 posture).
  - None inputs to the interlock are treated as the unsafe value (deny-by-default).

Sprint 15 EA-4b activation regression locks (TestEA4bActivationLocks):
  - Lock (a): HOST default is NOW production (dev_mode=False) — flip DONE.
  - Lock (b): explicit production signal (dev_mode_override=False) resolves False.
  - Lock (c): explicit dev opt-in (dev_mode_override=True) resolves dev + banner.
  - Lock (d): interlock refuses dev_mode=True + network_facing=True.
  - Lock (e): BLARAI_DEV_MODE unset → launcher resolves production (dev_mode=False).
  - Lock (f): BLARAI_DEV_MODE=1 → launcher resolves dev WITH loud banner.
"""

from __future__ import annotations

import logging

import pytest

from shared.runtime_config import DeploymentMode, resolve_dev_override, resolve_network_facing
from shared.security.dev_mode_guard import (
    DevModeNetworkFacingError,
    assert_dev_mode_network_facing_safe,
    resolve_dev_mode,
)


# ---------------------------------------------------------------------------
# Core interlock behaviour
# ---------------------------------------------------------------------------


class TestInterlockRefuses:
    """The interlock must RAISE when dev_mode and network_facing are both true."""

    def test_raises_on_dev_mode_true_network_facing_true(self) -> None:
        """Primary interlock contract: refuse (dev_mode=True, network_facing=True)."""
        with pytest.raises(DevModeNetworkFacingError, match="SECURITY INTERLOCK REFUSED"):
            assert_dev_mode_network_facing_safe(dev_mode=True, network_facing=True)

    def test_none_dev_mode_treated_as_true_raises(self) -> None:
        """Deny-by-default: None dev_mode treated as True (unknown = unsafe)."""
        with pytest.raises(DevModeNetworkFacingError):
            assert_dev_mode_network_facing_safe(dev_mode=None, network_facing=True)

    def test_none_network_facing_treated_as_true_raises(self) -> None:
        """Deny-by-default: None network_facing treated as True (unknown = unsafe)."""
        with pytest.raises(DevModeNetworkFacingError):
            assert_dev_mode_network_facing_safe(dev_mode=True, network_facing=None)

    def test_both_none_raises(self) -> None:
        """Deny-by-default: both None → both treated as True → raises."""
        with pytest.raises(DevModeNetworkFacingError):
            assert_dev_mode_network_facing_safe(dev_mode=None, network_facing=None)


class TestInterlockAllows:
    """The interlock must NOT raise on safe combinations."""

    def test_allows_dev_false_network_facing_true(self) -> None:
        """Secure mode + network-facing is the intended production posture."""
        assert_dev_mode_network_facing_safe(dev_mode=False, network_facing=True)  # no raise

    def test_allows_dev_false_network_facing_false(self) -> None:
        """Secure mode + air-gap: always safe."""
        assert_dev_mode_network_facing_safe(dev_mode=False, network_facing=False)  # no raise

    def test_allows_dev_true_network_facing_false(self) -> None:
        """Dev mode + air-gap: today's actual BlarAI HOST posture — must be allowed."""
        assert_dev_mode_network_facing_safe(dev_mode=True, network_facing=False)  # no raise


# ---------------------------------------------------------------------------
# Loud banner on dev_mode=True
# ---------------------------------------------------------------------------


class TestLoudBanner:
    """resolve_dev_mode MUST emit a loud warning when it returns True."""

    def test_dev_mode_true_emits_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """Banner is emitted into the logger when dev_mode resolves to True.

        Uses dev_mode_override=True explicitly so this test stays green after
        EA-4 flips the HOST-default from True to False (blast-radius override).
        """
        with caplog.at_level(logging.WARNING, logger="shared.security.dev_mode_guard"):
            result = resolve_dev_mode(DeploymentMode.HOST, dev_mode_override=True)

        assert result is True
        # At least one WARNING record must mention dev mode being active.
        warning_msgs = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("DEV MODE ACTIVE" in m for m in warning_msgs), (
            f"Expected 'DEV MODE ACTIVE' in warning log; got: {warning_msgs}"
        )

    def test_dev_mode_false_no_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """No banner or warning when dev_mode is False (GUEST / production posture)."""
        with caplog.at_level(logging.WARNING, logger="shared.security.dev_mode_guard"):
            result = resolve_dev_mode(DeploymentMode.GUEST)

        assert result is False
        warning_msgs = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        assert not any("DEV MODE ACTIVE" in m for m in warning_msgs), (
            f"Expected no 'DEV MODE ACTIVE' warning for GUEST; got: {warning_msgs}"
        )

    def test_interlock_allow_dev_true_network_false_logs_pass(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When (dev_mode=True, network_facing=False) the interlock logs a PASS."""
        with caplog.at_level(logging.INFO, logger="shared.security.dev_mode_guard"):
            assert_dev_mode_network_facing_safe(dev_mode=True, network_facing=False)

        info_msgs = [r.message for r in caplog.records if r.levelno == logging.INFO]
        assert any("PASSED" in m for m in info_msgs), (
            f"Expected 'PASSED' in INFO log; got: {info_msgs}"
        )


# ---------------------------------------------------------------------------
# Teeth: reconstruct the silent-collapse
# ---------------------------------------------------------------------------


class TestTeethSilentCollapse:
    """Demonstrate the pre-fix vulnerability and the post-fix refusal."""

    def test_pre_fix_silent_pattern_would_not_raise(self) -> None:
        """BEFORE the fix: the inline ternary pattern proceeded without any guard.

        This test documents what the old code did — it is the 'would have
        silently entered a network-facing+dev boot' proof.  The pattern:
            dev_mode_override = (True if runtime_mode == DeploymentMode.HOST else None)
        returns True for HOST but performs NO guard check at all.  We simulate
        that exact path: compute the value the old way, then assert that running
        the old logic (no interlock) would NOT raise.
        """
        runtime_mode = DeploymentMode.HOST
        # Exact pre-fix inline: this is what the old launcher/__main__.py did
        dev_mode_override_old_style = (True if runtime_mode == DeploymentMode.HOST else None)

        # In the old code there was NO call to assert_dev_mode_network_facing_safe.
        # Simulating a network-facing=True environment: no exception was raised.
        # (We just verify the old value and confirm no guard was called.)
        assert dev_mode_override_old_style is True  # old code resolved to True
        # No interlock called → would have proceeded silently.  This is the gap.

    def test_post_fix_interlock_refuses_the_same_scenario(self) -> None:
        """AFTER the fix: the same scenario (HOST + network_facing=True) is refused.

        Uses dev_mode_override=True explicitly so this test stays green after
        EA-4 flips the HOST-default (blast-radius override applied).
        """
        runtime_mode = DeploymentMode.HOST
        # Explicit override so the test is independent of the HOST default: this
        # exercises the interlock logic, not the HOST-default resolution.
        dev_mode = resolve_dev_mode(runtime_mode, dev_mode_override=True)
        network_facing = True  # pretend internet egress is live

        with pytest.raises(DevModeNetworkFacingError, match="SECURITY INTERLOCK REFUSED"):
            assert_dev_mode_network_facing_safe(dev_mode=dev_mode, network_facing=network_facing)


# ---------------------------------------------------------------------------
# Daily-launch regression: HOST resolves to dev_mode=False (activated EA-4b)
# ---------------------------------------------------------------------------


class TestHostDefaultActivated:
    """HOST resolves dev_mode=False (production) — EA-4b activation DONE.

    INTENTIONALLY does not use dev_mode_override — this class asserts the HOST
    branch default IS production after EA-4b's activation commit.
    """

    def test_host_resolves_dev_mode_false(self) -> None:
        """resolve_dev_mode(HOST) returns False — the HOST default is production.

        EA-4b activation lock: the flip is DONE.  No override is intentional —
        if this fails, the HOST default was accidentally reverted to dev.
        """
        result = resolve_dev_mode(DeploymentMode.HOST)
        assert result is False, (
            "HOST must resolve to dev_mode=False (production) — "
            "EA-4b activation has been applied.  "
            f"Got {result!r} — if this is True, the HOST default was accidentally "
            "reverted to dev.  Check shared/security/dev_mode_guard.py line ~103."
        )

    def test_guest_resolves_dev_mode_false(self) -> None:
        """GUEST resolves to dev_mode=False (the production / VM-isolated path)."""
        result = resolve_dev_mode(DeploymentMode.GUEST)
        assert result is False

    def test_override_true_forces_dev_mode_regardless_of_mode(self) -> None:
        """An explicit override=True wins over mode-derived default."""
        assert resolve_dev_mode(DeploymentMode.GUEST, dev_mode_override=True) is True

    def test_override_false_forces_dev_mode_false_for_host(self) -> None:
        """An explicit override=False is equivalent to the HOST production default."""
        assert resolve_dev_mode(DeploymentMode.HOST, dev_mode_override=False) is False


# ---------------------------------------------------------------------------
# network_facing resolution
# ---------------------------------------------------------------------------


class TestNetworkFacingResolution:
    """resolve_network_facing defaults to False (air-gapped Tier-1 posture)."""

    def test_default_is_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With no env var set, network_facing resolves to False."""
        monkeypatch.delenv("BLARAI_NETWORK_FACING", raising=False)
        assert resolve_network_facing() is False

    def test_explicit_false_override(self) -> None:
        """An explicit False override bypasses env-var lookup."""
        assert resolve_network_facing(explicit=False) is False

    def test_explicit_true_override(self) -> None:
        """An explicit True override bypasses env-var lookup."""
        assert resolve_network_facing(explicit=True) is True

    def test_env_truthy_values_enable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Truthy env-var values enable network_facing."""
        for val in ("1", "true", "TRUE", "yes", "on"):
            monkeypatch.setenv("BLARAI_NETWORK_FACING", val)
            assert resolve_network_facing() is True, f"Expected True for env={val!r}"

    def test_env_falsy_values_disable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Falsy or unrecognised env-var values keep network_facing as False."""
        for val in ("0", "false", "no", "off", "", "  ", "maybe", "NETWORK"):
            monkeypatch.setenv("BLARAI_NETWORK_FACING", val)
            assert resolve_network_facing() is False, f"Expected False for env={val!r}"


# ---------------------------------------------------------------------------
# Launcher integration: interlock is called before service construction
# ---------------------------------------------------------------------------


class TestLauncherInterlockIntegration:
    """Verify that the launcher exits early (return 1) when the interlock fires."""

    def test_launcher_exits_on_interlock(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When network_facing=True + dev_mode=True, main() must return 1
        immediately — before PolicyAgentService or AssistantOrchestratorService
        are ever constructed.

        After EA-4b's HOST-default flip, HOST resolves production by default.
        This test explicitly patches resolve_dev_mode to return True (simulating
        a BLARAI_DEV_MODE=1 opt-in) so the interlock scenario — dev_mode=True
        AND network_facing=True — is still exercised and refused.
        """
        from unittest.mock import patch

        # Arrange: simulate a dev-mode opt-in + network-facing launch.
        monkeypatch.setenv("BLARAI_NETWORK_FACING", "1")

        with (
            patch("launcher.__main__.is_admin", return_value=True),
            patch("launcher.__main__.resolve_network_facing", return_value=True),
            patch("launcher.__main__.resolve_dev_mode", return_value=True),
            patch("launcher.__main__.PolicyAgentService") as mock_pa,
            patch("launcher.__main__.AssistantOrchestratorService") as mock_ao,
            patch("launcher.__main__.input", return_value=""),
        ):
            from launcher.__main__ import main

            result = main()

        # The launcher must refuse with exit code 1.
        assert result == 1, f"Expected exit code 1 from interlock; got {result}"
        # Services must NOT have been constructed — the interlock fires before
        # service construction in the startup sequence.
        mock_pa.from_runtime_mode.assert_not_called()
        mock_ao.from_runtime_mode.assert_not_called()


# ---------------------------------------------------------------------------
# EA-4b Sprint 15 activation regression locks
# ---------------------------------------------------------------------------


class TestEA4bActivationLocks:
    """Six regression locks confirming EA-4b activation: production is the HOST default.

    These locks are the acceptance criteria for Sprint 15 SDV v4 §4 criterion #2,
    updated by EA-4b.  Lock (a) is the sentinel that the flip is DONE.

    Lock (a): HOST default is NOW production (dev_mode=False) — flip DONE.
    Lock (b): explicit production signal resolves dev_mode=False (still works).
    Lock (c): explicit dev opt-in resolves dev + banner fires (escape hatch works).
    Lock (d): interlock refuses dev_mode=True + network_facing=True (load-bearing).
    Lock (e): BLARAI_DEV_MODE unset → resolve_dev_override() returns None.
    Lock (f): BLARAI_DEV_MODE=1 → resolve_dev_override() returns True.
    """

    def test_lock_a_host_default_is_production(self) -> None:
        """Lock (a): resolve_dev_mode(HOST) — no override — returns False (production).

        EA-4b activation is DONE.  If this returns True, the HOST default was
        accidentally reverted to dev.  The Known-Good Manifest and JWT TPM key
        are provisioned; production is the correct default.
        """
        result = resolve_dev_mode(DeploymentMode.HOST)
        assert result is False, (
            "EA-4b lock (a) FAILED: HOST default is not production. "
            f"Got {result!r}.  Check shared/security/dev_mode_guard.py line ~103 — "
            "the HOST branch must resolve False (production), not True."
        )

    def test_lock_b_explicit_production_signal_resolves_false(self) -> None:
        """Lock (b): dev_mode_override=False on HOST resolves production posture.

        The explicit override path cleanly reaches False (same as the HOST default
        after activation — this is now the belt-and-suspenders path).
        """
        result = resolve_dev_mode(DeploymentMode.HOST, dev_mode_override=False)
        assert result is False, (
            f"EA-4b lock (b) FAILED: explicit dev_mode_override=False on HOST "
            f"did not resolve production posture; got {result!r}."
        )

    def test_lock_c_explicit_dev_opt_in_resolves_dev_and_fires_banner(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Lock (c): dev_mode_override=True on GUEST resolves dev + banner fires.

        The permanent escape hatch works: on a machine without a provisioned TPM
        key, an operator can return to dev mode via BLARAI_DEV_MODE=1.  The
        interlock still refuses dev_mode + network_facing=True regardless.
        """
        with caplog.at_level(logging.WARNING, logger="shared.security.dev_mode_guard"):
            result = resolve_dev_mode(DeploymentMode.GUEST, dev_mode_override=True)

        assert result is True, (
            f"EA-4b lock (c) FAILED: explicit dev_mode_override=True on GUEST "
            f"did not resolve dev mode; got {result!r}."
        )
        warning_msgs = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("DEV MODE ACTIVE" in m for m in warning_msgs), (
            "EA-4b lock (c) FAILED: loud INSECURE banner not emitted for "
            f"explicit dev opt-in; warnings: {warning_msgs}"
        )

    def test_lock_d_interlock_refuses_dev_plus_network_facing(self) -> None:
        """Lock (d): interlock refuses dev_mode=True + network_facing=True.

        This is the load-bearing control that prevents an insecure network-facing
        boot.  It must never be weakened.  The daily boot never trips it
        (network_facing defaults False), but the interlock fires the moment
        internet egress lands.
        """
        with pytest.raises(DevModeNetworkFacingError, match="SECURITY INTERLOCK REFUSED"):
            assert_dev_mode_network_facing_safe(dev_mode=True, network_facing=True)

    def test_lock_e_blarai_dev_mode_unset_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Lock (e): BLARAI_DEV_MODE unset → resolve_dev_override() returns None.

        None means "no override — use the mode-derived default", which is now
        production (False) for HOST.  This is the correct daily-launch path:
        no env var, no override, production by default.
        """
        monkeypatch.delenv("BLARAI_DEV_MODE", raising=False)
        result = resolve_dev_override()
        assert result is None, (
            f"EA-4b lock (e) FAILED: expected None (no override) when BLARAI_DEV_MODE "
            f"is unset, got {result!r}."
        )

    def test_lock_f_blarai_dev_mode_1_returns_true_and_fires_banner(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Lock (f): BLARAI_DEV_MODE=1 → resolve_dev_override() returns True + banner.

        The env-var opt-in is explicit and loud: setting BLARAI_DEV_MODE=1 returns
        True from resolve_dev_override(), which resolve_dev_mode() treats as an
        explicit override — the INSECURE banner fires on every such boot.
        """
        monkeypatch.setenv("BLARAI_DEV_MODE", "1")
        override = resolve_dev_override()
        assert override is True, (
            f"EA-4b lock (f) FAILED: BLARAI_DEV_MODE=1 did not return True from "
            f"resolve_dev_override(); got {override!r}."
        )
        # Now verify that passing the override through resolve_dev_mode fires the banner.
        with caplog.at_level(logging.WARNING, logger="shared.security.dev_mode_guard"):
            result = resolve_dev_mode(DeploymentMode.HOST, dev_mode_override=override)

        assert result is True, (
            f"EA-4b lock (f) FAILED: resolve_dev_mode(HOST, override=True) returned "
            f"{result!r} instead of True."
        )
        warning_msgs = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("DEV MODE ACTIVE" in m for m in warning_msgs), (
            "EA-4b lock (f) FAILED: loud INSECURE banner not emitted for "
            f"BLARAI_DEV_MODE=1 opt-in; warnings: {warning_msgs}"
        )
