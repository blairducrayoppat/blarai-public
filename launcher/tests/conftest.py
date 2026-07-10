"""
Shared launcher-test guards — instance-lock + token isolation (gate integrity).

``test_launcher.py`` drives the REAL launcher ``main()`` with its dependencies
mocked, but two early production steps were never among them:

1. **The single-instance lock (#670).** The lock is repo-path-keyed
   (``<repo_root>/certs/launcher.lock``), so a pytest run from a checkout
   whose lock a LIVE BlarAI holds walked into the real refusal path — whose
   deliberate ``os._exit(1)`` (correct in production: running cleanup there
   would stop the live instance's VM) killed the entire pytest process
   mid-run. The standing gate then TRUNCATES SILENTLY: no failure, no
   summary, and a piped consumer reads the run as green (observed 2026-07-04;
   the same gate-integrity class as the port-5001 silent-skip fixed at
   C6/#630).

2. **The privilege strip (#652).** ``strip_unused_privileges`` ran for REAL
   inside the pytest process, permanently removing 20 privileges from the
   test runner's own token (``SE_PRIVILEGE_REMOVED`` — irreversible for the
   process lifetime). Among them ``SeCreateSymbolicLinkPrivilege``, which the
   ``shared/tests`` symlink tests need — so launcher tests could flip
   later-collected tests from pass to env-skip within the same run.

3. **The per-boot cert mint (#751).** ``main()`` in production posture (the
   HOST default, ``dev_mode=False``) reaches Step 1.5 and calls the REAL
   ``provision_per_boot_certs(repo_root=<repo_root>)``, which mints nine fresh
   per-boot PEMs into the checkout's REAL ``<repo_root>/certs/`` dir,
   OVERWRITING whatever is there. Any launcher test that drives ``main()`` in
   production (``test_production_happy_path`` and its siblings) re-mints those
   certs as a side effect. The ``LOCALAPPDATA`` redirect the test-isolation
   discipline relies on does NOT cover ``certs/`` — it lives in the repo, not
   under ``LOCALAPPDATA``. When the standing gate runs from the operator's LIVE
   checkout this rotates the CA out from under a running AO whose in-memory CA
   no longer matches disk → ``CERTIFICATE_VERIFY_FAILED`` (lesson 55 recurrence,
   observed 2026-07-06; confirmed empirically — one run of
   ``test_production_happy_path`` writes nine PEMs into ``<repo_root>/certs/``).

The autouse fixture patches all three steps AS SEEN BY ``launcher.__main__`` so:

* a live BlarAI can never ``os._exit`` a test run (fail-loud gate integrity);
* tests never read or write the checkout's REAL ``certs/launcher.lock``
  (worktree runs used to create one as a side effect);
* the pytest process token is never mutated by a test;
* the per-boot cert mint is REDIRECTED to a throwaway tmp dir — the REAL
  ``provision_per_boot_certs`` still runs (the boot's cert flow keeps full
  coverage), but it never writes the checkout's ``<repo_root>/certs/`` (#751).

``test_instance_lock.py`` and ``test_privilege_hardening.py`` are unaffected:
they exercise ``launcher.instance_lock`` / ``launcher.privilege_hardening``
directly, and only the ``launcher.__main__`` bindings are patched here. The
production refusal semantics (refuse + hard exit WITHOUT cleanup) stay
covered by ``test_launcher.py``'s ``TestInstanceLockRefusal``, which
re-patches the lock to a refusal per-test.
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest import mock

import pytest

from launcher.instance_lock import InstanceLockResult

# Imported from the SOURCE module (not ``launcher.__main__``) so this reference
# stays the genuine, unpatched cert-minting function even while the fixture
# patches the ``launcher.__main__`` binding — the redirect wrapper delegates to
# it, preserving full real-cert-flow coverage.
from shared.security.cert_provisioning import (
    provision_per_boot_certs as _real_provision_per_boot_certs,
)

_NOOP_PRIVILEGE_REPORT: dict[str, list[str]] = {
    "removed": [],
    "kept": [],
    "errors": [],
}


@pytest.fixture(autouse=True)
def _isolate_launcher_process_side_effects(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[None]:
    """Patch ``launcher.__main__``'s lock + token-strip + cert-mint bindings.

    The lock + privilege-strip are neutralised (see the module docstring). The
    per-boot cert mint is REDIRECTED to a throwaway tmp dir so a launcher test
    that drives ``main()`` in production posture cannot re-mint the checkout's
    REAL ``<repo_root>/certs/`` (which would orphan a live AO's in-memory CA —
    #751). The REAL ``provision_per_boot_certs`` still runs, so the boot's cert
    flow keeps full coverage; only its write target changes.
    """
    import launcher.__main__ as main_mod

    lock_dir = tmp_path_factory.mktemp("instance-lock")
    certs_dir = tmp_path_factory.mktemp("per-boot-certs")
    acquired = InstanceLockResult(acquired=True)

    def _provision_into_tmp(*_args: object, **_kwargs: object):
        """Mint REAL per-boot certs, but into a tmp dir — never the repo certs/.

        ``main()`` calls ``provision_per_boot_certs(repo_root=<repo_root>)``; the
        production ``repo_root`` / ``certs_dir`` args are deliberately ignored and
        the mint is forced into the fixture's tmp ``certs_dir``. The real function
        runs end to end and returns a genuine ``PerBootCerts``, so ``main()``
        proceeds exactly as in production (only the write target moves to tmp).
        """
        return _real_provision_per_boot_certs(certs_dir=certs_dir)

    with (
        mock.patch.object(
            main_mod, "lock_path_for_repo", return_value=lock_dir / "launcher.lock"
        ),
        mock.patch.object(
            main_mod, "acquire_instance_lock", return_value=acquired
        ),
        mock.patch.object(main_mod, "release_instance_lock", return_value=True),
        mock.patch.object(
            main_mod,
            "strip_unused_privileges",
            return_value=dict(_NOOP_PRIVILEGE_REPORT),
        ),
        mock.patch.object(
            main_mod, "provision_per_boot_certs", _provision_into_tmp
        ),
    ):
        yield
