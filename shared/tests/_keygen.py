"""Shared test utility re-exporting PA jwt_minter surface for consumer tests.

Centralizes the cross-service coupling to one file under `shared/tests/` so
that individual consumer tests (AO test_entrypoint, shared test_jwt_validator)
no longer reach into `services.policy_agent.src.jwt_minter` directly.

Underscore-prefixed module name ensures pytest does not collect this file
as a test module.
"""

from services.policy_agent.src.jwt_minter import (
    AgenticJWTMinter,
    EpochManager,
    MintedJWT,
)

__all__ = ["AgenticJWTMinter", "EpochManager", "MintedJWT"]
