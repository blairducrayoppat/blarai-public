r"""Windows-Hello biometric operator-approval verifier (Vikunja #649, ADR-024 §2.5).

The biometric implementation of
:class:`shared.security.escalation_consent.ApprovalVerifier`. When the Policy Agent
returns an ``ESCALATE`` verdict, the consumer
(:func:`shared.security.escalation_consent.request_escalation_consent`) calls
:meth:`BiometricApprovalVerifier.verify` synchronously; this raises a **system-modal
Windows Hello prompt** (fingerprint / PIN / face via WinRT
``UserConsentVerifier.RequestVerificationAsync``) showing the SAFE action descriptor,
and maps a successful biometric match to *approve*, anything else to *deny*.

This is the verifier the ``escalation_consent`` module docstring names as the future
extension point. It implements the SAME ``verify(context) -> ApprovalResult`` Protocol
the Textual ``TUIApprovalVerifier`` does, so wiring it is a single
:func:`register_verifier` call (see the launcher). Because the prompt is a *system*
dialog (not a window any BlarAI surface owns), this verifier is **surface-independent**:
it works identically whether the live surface is the TUI or the WinUI — the AO runs in
the launcher process for both, and this verifier spawns the helper from that process.

How it reaches Hello — a subprocess, not a Python WinRT binding
---------------------------------------------------------------
There is **no new Python dependency**. WinRT is reached through a tiny C# console
helper (``tools/hello_verify/`` → ``BlarAI.HelloVerify.exe``) that BlarAI builds with
``dotnet`` against the SAME Windows SDK projection the primary WinUI surface already
targets (``net8.0-windows10.0.19041.0``). This Python module simply spawns that exe
with :func:`subprocess.run` and reads its **exit code**:

  * ``--check``   → exit 0 iff Hello is *Available* (non-interactive; used by
                    :meth:`is_available` for the launcher's startup verifier selection).
  * verify (default, with the SAFE message as the sole arg) → exit 0 iff the operator
                    was *Verified* by Hello; any other code is a denial.

The helper's full exit-code contract is documented in its ``Program.cs`` (0 == yes;
distinct non-zero per Canceled / RetriesExhausted / DeviceNotPresent / …). This module
only distinguishes **0 (allow)** from **non-zero (deny)** — the specific non-zero code
is surfaced in the deny reason for the audit record but never changes the allow/deny.

Fail-Closed everywhere (matches the rest of ``shared/security/``)
-----------------------------------------------------------------
The safe state is DENY. Every one of these yields a denied :class:`ApprovalResult`:

  * the helper exits **non-zero** (operator cancelled / not verified / device issue),
  * the helper **is not found** at the resolved path (not built / wrong path),
  * the helper **times out** (a wedged dialog must never wedge the AO turn — the outer
    :func:`request_escalation_consent` also bounds the total wait, and this verifier
    additionally caps its own subprocess),
  * **any exception** while spawning/waiting (OSError, etc.),
  * (defence-in-depth) anything other than an explicit exit 0.

There is no path where "I could not get an answer" becomes "approved". Importing this
module has **no side effects** — nothing is spawned and no verifier is registered at
import; a process wires it explicitly at its entry point (the launcher) and tests
inject/patch it directly. The single-user-local, no-external-network design constraints
of ``shared/security/`` hold: the only subprocess is a local exe; no socket is opened.
"""

from __future__ import annotations

import logging
import subprocess
import threading
from pathlib import Path
from typing import Optional

from shared.security.escalation_consent import (
    ApprovalResult,
    EscalationContext,
)

logger = logging.getLogger(__name__)

# Identity stamped on results this verifier produces (the audit-record label).
_HELLO_VERIFIER_IDENTITY: str = "hello"

# Exit code the helper returns for success (Available / Verified). The ONLY code
# that allows. Mirrors CheckExit.Available / VerifyExit.Verified == 0 in Program.cs.
_EXIT_OK: int = 0

# Repo-root-relative location of the built helper exe. Mirrors the launcher's
# ``WINUI_EXE_REL`` convention (Release build of the #649 helper project). The
# launcher resolves this against the repo root and passes the absolute path in;
# this default lets the demo script and tests locate it when run from a checkout.
HELLO_EXE_REL: str = (
    "tools/hello_verify/bin/x64/Release/"
    "net8.0-windows10.0.19041.0/BlarAI.HelloVerify.exe"
)

# Bounded waits for the helper subprocess (seconds). These are fail-closed
# backstops, NOT the expected path — a console operator answers Hello in seconds.
#   * verify: must allow time to read the prompt and present a finger/PIN, but must
#     be finite so a never-answered system dialog cannot wedge the turn. The outer
#     request_escalation_consent timeout (DEFAULT_CONSENT_TIMEOUT_S = 120s) is the
#     primary bound; this is a slightly-longer hard cap so the subprocess is always
#     reaped even if the outer host thread is abandoned.
#   * check: non-interactive; a few seconds is generous.
DEFAULT_VERIFY_TIMEOUT_S: float = 125.0
DEFAULT_CHECK_TIMEOUT_S: float = 15.0


def _default_repo_root() -> Path:
    """Repo root inferred from this file's location (``shared/security/`` → root).

    ``<root>/shared/security/hello_verifier.py`` → ``parents[2]`` is ``<root>``.
    Used only to derive the default helper path; the launcher passes an explicit
    absolute path so it never relies on this inference.
    """
    return Path(__file__).resolve().parents[2]


def _default_exe_path() -> Path:
    """The default absolute path to the built helper exe (repo-root + HELLO_EXE_REL)."""
    return _default_repo_root() / HELLO_EXE_REL


class BiometricApprovalVerifier:
    """Windows-Hello operator-approval verifier (implements ``ApprovalVerifier``).

    Construct it (optionally with an explicit ``exe_path`` — the launcher passes the
    repo-root-resolved absolute path) and register it via
    :func:`shared.security.escalation_consent.register_verifier`. On each ESCALATE,
    :meth:`verify` raises the system Hello prompt with the SAFE descriptor and returns
    the operator's approve/deny. Fail-closed on every non-approval path.

    :param exe_path: absolute path to ``BlarAI.HelloVerify.exe``. Defaults to the
        repo-root-relative :data:`HELLO_EXE_REL`. The launcher supplies the resolved
        path so the verifier does not depend on the process CWD.
    :param verify_timeout_s: hard cap on the interactive verify subprocess. On expiry
        the subprocess is killed and the result is DENY (fail-closed).
    :param check_timeout_s: hard cap on the non-interactive ``--check`` subprocess.
    """

    def __init__(
        self,
        exe_path: "Optional[str | Path]" = None,
        *,
        verify_timeout_s: float = DEFAULT_VERIFY_TIMEOUT_S,
        check_timeout_s: float = DEFAULT_CHECK_TIMEOUT_S,
    ) -> None:
        self._exe_path: Path = Path(exe_path) if exe_path is not None else _default_exe_path()
        self._verify_timeout_s = verify_timeout_s
        self._check_timeout_s = check_timeout_s
        # is_available() caches its probe result here (None == not yet probed). The
        # availability of Hello does not change within a boot, so probing once at
        # startup is sufficient and avoids re-spawning the helper on every check.
        self._available_cache: Optional[bool] = None
        self._cache_lock = threading.Lock()

    # -- ApprovalVerifier protocol -------------------------------------------------

    def verify(self, context: EscalationContext) -> ApprovalResult:
        """Raise the Hello prompt for ``context`` and return the operator's answer.

        Builds a SAFE one-line message from ``context.describe()`` (labels/descriptors
        only — :class:`EscalationContext` guarantees no raw secret/PII), spawns the
        helper exe with that message, and maps **exit 0 → allow**, everything else
        (non-zero, timeout, helper missing, any exception) → **deny**. Synchronous and
        fail-closed: there is no path where a non-success becomes an approval.
        """
        # The SAFE descriptor — the exact one-line string the TUI modal renders, and
        # the same one the audit record carries. EscalationContext.describe() is
        # labels/descriptors only by construction, so no secret reaches the Hello
        # dialog (or any process arg list).
        message = self._safe_message(context)

        if not self._exe_path.is_file():
            logger.error(
                "Hello verifier: helper exe not found at %s — DENY (fail-closed) for "
                "%s. Build it: dotnet build -c Release tools/hello_verify.",
                self._exe_path, context.describe(),
            )
            return ApprovalResult.deny(
                "hello helper not found", verifier_identity=_HELLO_VERIFIER_IDENTITY
            )

        try:
            completed = subprocess.run(
                [str(self._exe_path), message],
                capture_output=True,
                text=True,
                timeout=self._verify_timeout_s,
                # No shell; argument vector form — the message is a single argv entry,
                # never interpolated into a command line, so it cannot be re-parsed.
            )
        except subprocess.TimeoutExpired:
            # The helper subprocess is killed by subprocess.run on timeout. A wedged
            # or unanswered system dialog must never wedge the AO turn → DENY.
            logger.warning(
                "Hello verifier: helper did not answer within %.1fs — DENY "
                "(fail-closed timeout) for %s",
                self._verify_timeout_s, context.describe(),
            )
            return ApprovalResult.deny(
                "timeout", verifier_identity=_HELLO_VERIFIER_IDENTITY
            )
        except OSError as exc:
            # Spawn failure (exe vanished between the is_file check and exec, perms,
            # etc.) → DENY.
            logger.error(
                "Hello verifier: could not run helper (%r) — DENY (fail-closed) for %s",
                exc, context.describe(),
            )
            return ApprovalResult.deny(
                f"helper spawn error: {type(exc).__name__}",
                verifier_identity=_HELLO_VERIFIER_IDENTITY,
            )
        except Exception as exc:  # noqa: BLE001 — fail-closed: ANY failure → DENY
            logger.error(
                "Hello verifier: unexpected error running helper (%r) — DENY "
                "(fail-closed) for %s",
                exc, context.describe(),
            )
            return ApprovalResult.deny(
                f"helper error: {type(exc).__name__}",
                verifier_identity=_HELLO_VERIFIER_IDENTITY,
            )

        rc = completed.returncode
        if rc == _EXIT_OK:
            logger.warning(
                "Hello verifier: operator APPROVED %s via Windows Hello.",
                context.describe(),
            )
            return ApprovalResult.allow(
                verifier_identity=_HELLO_VERIFIER_IDENTITY,
                reason="operator approved (Windows Hello)",
            )

        # Any non-zero exit is a denial. Surface the code in the reason for the audit
        # record (e.g. 15 == Canceled, 14 == RetriesExhausted — see Program.cs) but
        # the allow/deny decision is purely "was it exactly 0".
        logger.info(
            "Hello verifier: NOT approved (helper exit %s) — DENY for %s",
            rc, context.describe(),
        )
        return ApprovalResult.deny(
            f"hello not verified (exit {rc})",
            verifier_identity=_HELLO_VERIFIER_IDENTITY,
        )

    # -- availability probe (launcher startup selection) ---------------------------

    def is_available(self, *, force: bool = False) -> bool:
        """Whether Windows Hello is Available to verify on this box (cached).

        Runs the helper's non-interactive ``--check`` (which raises no dialog) and
        returns True iff it exits 0 (``UserConsentVerifierAvailability.Available``).
        The launcher calls this at startup to decide whether to register this
        biometric verifier or fall back. The result is cached for the process (Hello
        availability is boot-stable); pass ``force=True`` to re-probe.

        Fail-closed: a missing helper, a non-zero ``--check`` exit, a timeout, or any
        exception all return **False** (so the launcher falls back rather than
        registering a verifier that cannot actually prompt).
        """
        with self._cache_lock:
            if self._available_cache is not None and not force:
                return self._available_cache
            result = self._probe_available()
            self._available_cache = result
            return result

    def _probe_available(self) -> bool:
        if not self._exe_path.is_file():
            logger.info(
                "Hello verifier: helper exe not found at %s — reporting Hello "
                "UNAVAILABLE (launcher will fall back).",
                self._exe_path,
            )
            return False
        try:
            completed = subprocess.run(
                [str(self._exe_path), "--check"],
                capture_output=True,
                text=True,
                timeout=self._check_timeout_s,
            )
        except subprocess.TimeoutExpired:
            logger.warning(
                "Hello verifier: --check timed out after %.1fs — reporting "
                "UNAVAILABLE (fail-closed).",
                self._check_timeout_s,
            )
            return False
        except Exception as exc:  # noqa: BLE001 — fail-closed: any failure → unavailable
            logger.warning(
                "Hello verifier: --check failed (%r) — reporting UNAVAILABLE "
                "(fail-closed).",
                exc,
            )
            return False
        available = completed.returncode == _EXIT_OK
        logger.info(
            "Hello verifier: --check exit=%s → Hello %s.",
            completed.returncode, "AVAILABLE" if available else "unavailable",
        )
        return available

    # -- helpers -------------------------------------------------------------------

    @staticmethod
    def _safe_message(context: EscalationContext) -> str:
        """Build the SAFE one-line Hello-dialog message from the context.

        Reuses :meth:`EscalationContext.describe` (labels/descriptors only — never raw
        payload) and prefixes a short instruction so the system dialog reads clearly.
        The prompt is shown only in the OS Hello dialog; it is not logged with the
        argument echoed, and it is passed as a single argv entry (never a shell line).

        The prefix varies by ``context.source`` so the same verifier reads correctly
        for both consumers: a PA ESCALATE reads as an approval of an escalated action,
        while a rung-3 egress consent (``source="egress"``, ADR-023 Amendment 4 #723)
        reads as authorizing an outbound web search — the operator is approving content
        LEAVING the machine, a materially different act than approving a local action.
        """
        if context.source == "egress":
            return f"BlarAI — allow this outbound web search? {context.describe()}"
        return f"BlarAI — approve escalated action? {context.describe()}"

    @property
    def exe_path(self) -> Path:
        """The resolved absolute path to the helper exe (for diagnostics/tests)."""
        return self._exe_path
