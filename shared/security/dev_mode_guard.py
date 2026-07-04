"""Dev-mode / network-facing interlock and loud opt-in banner. Sprint 13 Decision 8.

Two responsibilities live here:

1.  **resolve_dev_mode** — the *centralised, logged* source of truth for the
    dev_mode bool.  The original launcher used an inline ternary
    ``(True if runtime_mode == DeploymentMode.HOST else None)`` repeated in
    three places.  That silent pattern validated a never-ship configuration on
    every "BlarAI works" report.  This helper replaces it: it resolves
    production posture (False) for HOST by default, and emits a prominent
    multi-line INSECURE banner whenever dev-mode is active — so the insecure
    state is unmissable in every boot log.  Dev mode is now an explicit,
    loud opt-in via ``BLARAI_DEV_MODE=1``; production is the silent default.

2.  **assert_dev_mode_network_facing_safe** — a fail-closed interlock that
    RAISES when *both* dev_mode=True and network_facing=True are true at the
    same time.  Deny-by-default: if either input is ambiguous (i.e. the caller
    passes ``None``), the function treats the unknown as the unsafe value.
    HOST now resolves to dev_mode=False (production) by default; network_facing
    defaults to False, so the interlock never trips on the daily launch —
    but the moment internet egress lands (the Tier-2 network-facing work), the
    guard is the load-bearing control that refuses an insecure-mode start.

Design constraints (match the rest of shared/security/):
  - No external network.  No new dependencies (stdlib only).
  - Importing has no side effects.
  - Fail-Closed: when in doubt, raise.
"""

from __future__ import annotations

import logging

from shared.runtime_config import DeploymentMode

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# INSECURE banner text — emitted on every dev-mode boot.
# ---------------------------------------------------------------------------

_DEV_MODE_BANNER: str = """\
╔══════════════════════════════════════════════════════════════════════════════╗
║  WARNING — DEV MODE ACTIVE (INSECURE CONFIGURATION)                         ║
║                                                                              ║
║  • mTLS client/server certificates:  NOT CHECKED  (throwaway keys)           ║
║  • JWT signing keys:                 THROWAWAY    (rotated per session)      ║
║  • Measured-boot attestation:        DISABLED                                ║
║  • Network-facing with real data:    REFUSED      (interlock enforced)       ║
║                                                                              ║
║  Dev mode is valid only on an air-gapped development machine.                ║
║  NEVER use with network-facing=True or with real user data.                  ║
╚══════════════════════════════════════════════════════════════════════════════╝"""


class DevModeNetworkFacingError(RuntimeError):
    """Raised by the interlock when dev_mode and network_facing are both true.

    Subclasses RuntimeError so existing startup ``except Exception`` fail-closed
    paths degrade safely, but is distinguishable for test assertions.
    """


def resolve_dev_mode(
    runtime_mode: DeploymentMode,
    *,
    dev_mode_override: bool | None = None,
) -> bool:
    """Return the authoritative dev_mode bool and emit a loud banner when True.

    Resolution precedence:
      1. ``dev_mode_override`` if not None (explicit caller opt-in / opt-out).
      2. ``False`` when ``runtime_mode == DeploymentMode.HOST`` (production default,
         activated Sprint 15 EA-4b after Known-Good Manifest staged and JWT TPM
         key provisioned via EA-4 on-chip ceremony).
      3. ``False`` when ``runtime_mode == DeploymentMode.GUEST`` (production path).

    **Production is the HOST default.**  The Known-Good Manifest is staged
    (EA-3) and the JWT TPM key provisioned (EA-4 ceremony) — the activation
    conditions are met.  HOST resolves production (False) by default; the loud
    INSECURE banner never fires on a normal daily launch.

    **Explicit dev opt-in via ``BLARAI_DEV_MODE``:** set ``BLARAI_DEV_MODE=1``
    (or ``true`` / ``yes``) in the environment.  The launcher reads this via
    ``shared.runtime_config.resolve_dev_override()`` and passes the result as
    ``dev_mode_override=True``.  The loud INSECURE banner fires on every such
    boot — the opt-in is always visible.  The interlock still refuses the
    combination ``dev_mode=True + network_facing=True``.

    Args:
        runtime_mode:      The resolved :class:`~shared.runtime_config.DeploymentMode`.
        dev_mode_override: Explicit override; ``None`` uses the mode-derived default.

    Returns:
        The resolved dev_mode bool.  Emits ``logger.warning`` multi-line banner
        when the result is ``True``.
    """
    if dev_mode_override is not None:
        resolved = dev_mode_override
    elif runtime_mode == DeploymentMode.HOST:
        resolved = False  # production default — activated Sprint 15 EA-4b
    else:
        resolved = False

    if resolved:
        # Write to both logger (captures to file) and stderr (visible at boot).
        logger.warning(
            "DEV MODE ACTIVE — insecure configuration (no mTLS / throwaway keys / "
            "no measured boot). Network-facing + dev_mode is refused by interlock. "
            "runtime_mode=%s dev_mode_override=%r",
            runtime_mode.value,
            dev_mode_override,
        )
        # Print the banner to stderr so it is impossible to miss in a console boot.
        import sys  # local import to keep module-level clean
        print("\n" + _DEV_MODE_BANNER + "\n", file=sys.stderr, flush=True)

    return resolved


def assert_dev_mode_network_facing_safe(
    *,
    dev_mode: bool | None,
    network_facing: bool | None,
) -> None:
    """Fail-closed guard: refuse (dev_mode=True AND network_facing=True).

    Deny-by-default: if either input is ``None`` (unknown), the function treats
    the unknown as the *unsafe* value and raises.  This is the correct posture
    for a security control: "I don't know" is not the same as "it's safe".

    Args:
        dev_mode:       Whether dev mode is active.  ``None`` treated as True.
        network_facing: Whether the process is network-facing.  ``None`` treated
                        as True.

    Raises:
        DevModeNetworkFacingError: when the combination is unsafe.
    """
    # Treat None as the unsafe (True) value — deny-by-default.
    effective_dev_mode = True if dev_mode is None else dev_mode
    effective_network_facing = True if network_facing is None else network_facing

    if effective_dev_mode and effective_network_facing:
        msg = (
            "SECURITY INTERLOCK REFUSED: dev_mode and network_facing are both "
            "active simultaneously.  This configuration provides no mTLS, "
            "throwaway keys, and no measured boot — it MUST NOT be used when "
            "network-facing with real data.  "
            "Flip network_facing=False (air-gap, Tier-1 posture) OR disable "
            "dev_mode (Tier-2 cert provisioning required) before proceeding."
        )
        logger.critical(
            "SECURITY INTERLOCK REFUSED: dev_mode=%r network_facing=%r "
            "(effective: dev_mode=%r network_facing=%r)",
            dev_mode,
            network_facing,
            effective_dev_mode,
            effective_network_facing,
        )
        raise DevModeNetworkFacingError(msg)

    # Allowed combination — log a brief audit record.
    logger.info(
        "dev_mode interlock: PASSED (dev_mode=%r, network_facing=%r)",
        effective_dev_mode,
        effective_network_facing,
    )
