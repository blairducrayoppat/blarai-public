"""External-contract adapter probe registry (Vikunja #739 — the L188 control).

Lesson 188 reached its THIRD instance and the LESSONS.md SOP requires the third
instance to ship an *enforced* structural control, not another checklist line.
This module is that control's data spine.

THE LESSON (three instances). Adapters that consume an EXTERNAL contract — a
specific vendor's API / tool / interface with a documented shape — broke because
reality diverged from the doc-derived assumption baked into the adapter:

  1. Kagi Search API ``v0 -> v1``: the build pinned v0 (``GET``, ``Bot`` header,
     flat ``data`` array) against the then-current help.kagi.com / ADR-024 docs;
     the first live fetch at go-live returned **HTTP 401**, and probing the real
     key proved the live contract is v1 (``POST``, ``Bearer``, results under
     ``data.search``). Four axes drifted together (#719 / #724, 2026-07-02).
  2. EAGLE-3 exporter / ``guidance_rescale``: a model-exporter toolchain axis
     diverged from its documented shape (2026-06-29).
  3. Chrome / Edge 149 console API change broke the browser console harness
     (2026-07-03).

THE CONTROL. Every in-repo adapter that consumes a fixed external contract
exposes a cheap, standalone LIVE PROBE — a ``--probe`` CLI entrypoint that
exercises the REAL endpoint's contract axes (endpoint / URL shape, auth-header
shape, response schema) against the real endpoint with the real credential where
one exists, and exits nonzero on drift. This registry is the declarative SSOT of
those adapter/probe pairs; the enforcement is the gate test
``tests/security/test_external_probe_registry.py``:

  * every registered probe entrypoint must EXIST and be importable + callable
    WITHOUT any network I/O at import time; and
  * a structural sweep fails the standing gate if any module under ``services/``
    or ``shared/`` reaches the one egress door's ``fetch_external`` /
    ``fetch_external_binary`` entrypoint WITHOUT enrolling here (or being named
    in the sweep's justified-exclusion set with a documented reason).

That is the teeth: a new external-contract adapter that skips its probe cannot
land green.

SCOPE (surveyed 2026-07-06).

  * IN REPO, registered below: the Kagi ``web_search`` adapter
    (:mod:`services.assistant_orchestrator.src.websearch.live_adapter`) — the
    only module that talks to a FIXED external API contract through the door.
  * OUT OF REPO (documented here, enforced in their own repos, NOT by this gate):
    the model-exporter toolchains (EAGLE-3 / draft-model conversion — L188
    instance 2) live outside this repository; the browser console harness (L188
    instance 3) is devplatform-side. A live probe for either belongs to the repo
    that owns the adapter code, not here.
  * JUSTIFIED IN-REPO NON-ADAPTER: the UC-003 ``/ingest`` URL coordinator
    (:mod:`services.ui_gateway.src.ingest_coordinator`) also reaches the door,
    but it fetches ARBITRARY user-supplied URLs — there is no stable vendor
    endpoint / auth / response schema to probe. It is named in the gate test's
    justified-exclusion set with that reason rather than given a contract probe.

This module performs NO network I/O and imports NO network client or adapter —
it is a pure declarative table (dotted-string references only), so importing it
is trivial and side-effect-free.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class ExternalProbe:
    """One registered external-contract adapter and its standalone live probe.

    All fields are dotted-string references (no live imports) so this registry
    stays a pure, side-effect-free table. The gate test resolves the references.
    """

    #: Stable, human-readable identifier for the adapter/probe pair.
    name: str
    #: Dotted import path of the adapter module that consumes the egress door
    #: (e.g. ``services.assistant_orchestrator.src.websearch.live_adapter``).
    adapter_module: str
    #: Dotted ``module:callable`` path to the probe's argparse-backed entrypoint
    #: (e.g. ``...websearch.probe:main``). MUST be importable + callable WITHOUT
    #: any network I/O at import time; the endpoint is hit only when the callable
    #: is actually invoked with ``--probe`` and the real credential is present.
    probe_entrypoint: str
    #: The external-contract axes the probe exercises against reality — the
    #: doc-derived assumptions that drift (L188): endpoint / URL shape, auth
    #: header shape, and response-schema fields.
    contract_notes: str

    @property
    def probe_module(self) -> str:
        """The module portion of :attr:`probe_entrypoint` (before the ``:``)."""
        return self.probe_entrypoint.split(":", 1)[0]

    @property
    def probe_callable(self) -> str:
        """The attribute portion of :attr:`probe_entrypoint` (after the ``:``)."""
        parts = self.probe_entrypoint.split(":", 1)
        return parts[1] if len(parts) == 2 else ""


#: THE registry (single source of truth). A new external-contract adapter MUST
#: enroll here or the gate test fails — the "new external adapter without a probe
#: fails the standing gate" teeth (Vikunja #739, the L188 third-instance control).
REGISTERED_PROBES: Final[tuple[ExternalProbe, ...]] = (
    ExternalProbe(
        name="kagi_web_search",
        adapter_module=(
            "services.assistant_orchestrator.src.websearch.live_adapter"
        ),
        probe_entrypoint=(
            "services.assistant_orchestrator.src.websearch.probe:main"
        ),
        contract_notes=(
            "Kagi Search API v1. Endpoint: POST https://kagi.com/api/v1/search. "
            "Auth: 'Authorization: Bearer <key>'. Request: JSON body "
            "{'query': <text>}. Response schema: "
            "{'data': {'search': [{'title', 'url', 'snippet', ...}]}} — genuine "
            "web results live under data.search. All four axes (v0->v1 path, "
            "GET->POST, Bot->Bearer, query-param->JSON-body) drifted together at "
            "the #724 go-live 401 (L188 instance 1)."
        ),
    ),
)


def registered_probe_names() -> frozenset[str]:
    """Return the set of registered probe names (convenience for callers/tests)."""
    return frozenset(probe.name for probe in REGISTERED_PROBES)


def registered_adapter_modules() -> frozenset[str]:
    """Return the dotted module paths of every registered adapter."""
    return frozenset(probe.adapter_module for probe in REGISTERED_PROBES)


def registered_probe_modules() -> frozenset[str]:
    """Return the dotted module paths of every registered probe entrypoint.

    A probe module deliberately reaches the egress door (that IS the probe), so
    the structural sweep treats these as enrolled alongside the adapter modules.
    """
    return frozenset(probe.probe_module for probe in REGISTERED_PROBES)
