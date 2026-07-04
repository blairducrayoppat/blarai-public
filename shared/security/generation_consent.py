r"""Per-generation-batch approval consent — DORMANT SEAM (ADR-023 Amendment 4, #723 rung 2).

The one-click operator consent in FRONT of a REAL model-initiated local generation
(an image the operator did NOT ask for by typing ``/imagine``). It replaces the
per-session ``/trust`` untrusted-content lock for a real generator tool with a
per-event, judgeable approval that shows the EXACT prompt + image count — so an
injected/unexpected generation is self-announcing (the operator sees a prompt he
never asked for and denies in one click).

**This is a dormant seam.** The current in-loop ``generate_image`` tool is a
directive shim that generates nothing (see ``tools._generate_image`` /
``tools._GEN_APPROVAL_TOOLS`` — deliberately empty), so nothing routes here today.
The infrastructure exists so the control is ready the day a real model-initiated
generation path is added (autonomous image work): add the generator to
``_GEN_APPROVAL_TOOLS`` and register a verifier (the launcher wires the one-click
``SystemConfirmApprovalVerifier``).

Design mirrors :mod:`shared.security.escalation_consent`: a single-verifier
registry (separate from the ESCALATE registry, because the LA chose a **one-click
approve/deny surface, NOT a Windows-Hello fingerprint** for local generation —
egress is identity-assertion, local generation is intent-confirmation, a different
grain), routed through the SAME shared fail-closed harness
(:func:`shared.security.escalation_consent.run_verifier_bounded`). No external
network, no new dependency, no import side effects, and the safe state is DENY.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Optional

from shared.security.escalation_consent import (
    DEFAULT_CONSENT_TIMEOUT_S,
    ApprovalVerifier,
    EscalationContext,
    run_verifier_bounded,
)

logger = logging.getLogger(__name__)

_NO_VERIFIER_IDENTITY: str = "no-verifier"

# Cap for the prompt shown in the approval dialog (a prompt is short by nature;
# this bounds a pathological one from bloating the dialog).
_PROMPT_DISPLAY_CAP: int = 300


# ---------------------------------------------------------------------------
# Single-verifier registry (separate from the ESCALATE / egress registries)
# ---------------------------------------------------------------------------

_gen_verifier: Optional[ApprovalVerifier] = None
_gen_verifier_lock = threading.Lock()


def register_generation_verifier(verifier: ApprovalVerifier) -> None:
    """Register the one-click generation-approval verifier (the seam's activation).

    A verifier implements ``verify(context) -> ApprovalResult`` (the same Protocol
    the ESCALATE surface uses). The launcher wires the one-click
    ``SystemConfirmApprovalVerifier`` here when the per-batch approval is activated.
    Single-verifier: registering replaces any previous one. Registering does not by
    itself allow anything — absent/failed answers still fail closed.
    """
    if not hasattr(verifier, "verify") or not callable(getattr(verifier, "verify")):
        raise TypeError(
            "register_generation_verifier requires an ApprovalVerifier "
            "(a verify(context) method)"
        )
    global _gen_verifier
    with _gen_verifier_lock:
        _gen_verifier = verifier
    logger.info(
        "Generation consent: approval verifier registered (%s) — model-initiated "
        "generation now routes to a one-click operator approval.",
        type(verifier).__name__,
    )


def clear_generation_verifier() -> None:
    """Unregister the verifier — return to the dormant deny-every-generation default."""
    global _gen_verifier
    with _gen_verifier_lock:
        _gen_verifier = None


def active_generation_verifier() -> Optional[ApprovalVerifier]:
    """Return the currently-registered generation verifier, or ``None`` if none."""
    with _gen_verifier_lock:
        return _gen_verifier


# ---------------------------------------------------------------------------
# The consumer entry point + the arg extractor
# ---------------------------------------------------------------------------


def extract_generation_request(canonical_args: str) -> tuple[str, int]:
    """Best-effort pull of ``(prompt, image_count)`` from a generator tool's
    canonical-args JSON, for the approval dialog + audit descriptor.

    ``prompt`` from the ``prompt`` field (capped); ``image_count`` from the first
    of ``count`` / ``num_images`` / ``n`` that is a positive int, default 1. On any
    parse failure the prompt degrades to a generic descriptor and the count to 1 —
    the gate's allow/deny does not depend on this (that is the fingerprint/approval),
    only on what the operator is SHOWN, so a degraded descriptor is safe (they can
    still deny).
    """
    prompt = "(prompt unavailable)"
    count = 1
    try:
        parsed = json.loads(canonical_args) if canonical_args else {}
        if isinstance(parsed, dict):
            p = parsed.get("prompt")
            if isinstance(p, str) and p.strip():
                prompt = p.strip()
            for key in ("count", "num_images", "n"):
                v = parsed.get(key)
                if isinstance(v, int) and not isinstance(v, bool) and v > 0:
                    count = v
                    break
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return prompt[:_PROMPT_DISPLAY_CAP], count


def request_generation_consent(
    prompt: str,
    image_count: int = 1,
    *,
    timeout_s: Optional[float] = None,
) -> bool:
    """Raise the one-click generation approval and return the operator's decision.

    Builds a SAFE :class:`EscalationContext` (``source="generation"``) surfacing the
    EXACT prompt + image count — the operator MUST see the prompt to judge whether he
    intended this generation — and routes it to the registered generation verifier
    through the shared fail-closed harness. **Fail-closed:** no verifier registered
    (the dormant default) / timeout / error / non-approval → ``False``.
    """
    verifier = active_generation_verifier()
    if verifier is None:
        # Dormant default: no operator surface wired → DENY. With _GEN_APPROVAL_TOOLS
        # empty this is never reached in production; it is the fail-closed floor for
        # when a real generator tool is added before a verifier is registered.
        logger.info(
            "Generation consent: no verifier configured — DENY (fail-closed default).",
        )
        return False

    n = max(1, int(image_count))
    context = EscalationContext(
        rule_label="GENERATE_IMAGE",
        action_summary=(
            f"Generate {n} image{'s' if n != 1 else ''}: {prompt}"
        ),
        tool_name="generate_image",
        source="generation",
    )
    result = run_verifier_bounded(
        verifier,
        context,
        timeout_s=DEFAULT_CONSENT_TIMEOUT_S if timeout_s is None else timeout_s,
        label="Generation consent",
    )
    return bool(result.approved)
