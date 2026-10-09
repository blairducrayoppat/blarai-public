"""#1570: BlarAI-NATIVE tests using ACS vocabulary. NOT CTK vectors passing.

**Read this before citing these tests anywhere.** They are not conformance, they do not
run either ACS suite, and passing them does not make BlarAI "ACS-conformant" or
"CTK-passing". Both of those phrases are barred by
`docs/governance/acs-conformance-disclosure.md`.

What they are: BlarAI's own assertions about BlarAI's own doors, written to mirror the
*rules* two upstream conformance cases express. Zero of the 70 cases across the two suites
are runnable here — the Agent Hooks CTK vectors need a mocked model, mocked tools, an
interceptor at all eight interception points and an assembled RunRecord; the Agent Control
Specification crate's cases are `operation: "evaluate"` against a manifest, and BlarAI has
no manifest loader and no Rego evaluator. What IS portable is the input→output mapping two
of them assert, and that is what is mirrored below.

Sources, read at the versions named in the disclosure:
  - `spec-14-verdict-normalization.case-01` (`responsibleai/agent-control-spec` @ `a830ed5`):
    a policy returning an unrecognised decision must normalise to `deny`, not pass through
    and not default to allow.
  - `spec-08-action-identity.case-08` (same): an `escalate` normalises to a `deny` carrying
    an action identity and an approval block — escalate is a *liftable deny*, never an allow.
"""

from __future__ import annotations

import re

import pytest

from services.assistant_orchestrator.src.entrypoint import (
    _action_identity,
    _adjudicate_tool_dispatch,
)
from shared.security.verdict_receipt import KNOWN_RESERVED_REASONS

_SID = "acs-vocab"


class TestUnrecognisedVerdictFailsClosed:
    """Mirrors spec-14-verdict-normalization.case-01's RULE, not its fixture.

    The upstream case stubs a policy that returns `{"decision": "block"}` — not a member
    of the closed verdict set — and requires the engine to normalise it to `deny` with
    `runtime_error:policy_output_invalid`. The rule underneath is: an unrecognised
    decision is never passed through and never treated as allow.

    BlarAI has no policy plugin to return a bad decision, so the equivalent reachable
    fault is an adjudication that raises. The rule is the same: the door must not fall
    open.
    """

    def test_adjudication_error_denies(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import services.assistant_orchestrator.src.entrypoint as ep

        def _boom(*_a, **_k):
            raise RuntimeError("policy returned something unrecognisable")

        monkeypatch.setattr(ep, "_build_dispatch_car", _boom)

        verdict = _adjudicate_tool_dispatch("calculate", '{"expression": "2+2"}', _SID)

        assert verdict is not None, "an unrecognised/failed adjudication fell open to ALLOW"
        assert verdict[0] == "DENY"

    def test_a_healthy_adjudication_still_allows(self) -> None:
        """The toggle. Without it, a door that denied everything would pass the test
        above while refusing every legitimate turn — indistinguishable from safety."""
        assert _adjudicate_tool_dispatch("calculate", '{"expression": "2+2"}', _SID) is None


class TestEscalateIsALiftableDenyNeverAnAllow:
    """Mirrors spec-08-action-identity.case-08's RULE.

    Upstream: a policy `escalate` normalises to a `deny` carrying `action_identity` and
    an `approval` block. BlarAI's tool loop implements exactly this shape — an ESCALATE
    that is not operator-approved collapses to a refusal, and #1541 added the identity
    the approval binds to.

    Asserted here at the vocabulary level: the identity exists, is a `sha256:`
    descriptor, and is derivable for an escalated dispatch. The *behaviour* (ESCALATE
    without approval refuses) is locked in
    `services/assistant_orchestrator/tests/test_tools.py::TestEscalateConsumerAtAOLoop`.
    """

    def test_an_escalatable_action_has_a_sha256_identity(self) -> None:
        identity = _action_identity("web_search", '{"query": "x"}', _SID)

        assert identity.startswith("sha256:")
        assert len(identity) == len("sha256:") + 64

    def test_the_identity_is_a_descriptor_not_the_arguments(self) -> None:
        """The upstream rule carries an identity, not the action's payload."""
        secret = "not-for-the-audit-record"
        identity = _action_identity("web_search", f'{{"query": "{secret}"}}', _SID)

        assert secret not in identity


class TestReservedReasonNamespacesAreNotInvented:
    """The specification's one hard prohibition: a host MUST NOT invent identifiers in
    either reserved namespace.

    **The inventory is what the suites NAME, not what they happen to assert.** An earlier
    version of this test built the set from strings appearing inside `expect{}` blocks and
    got 7 `host_error:*`. Adversarial review found that undercounts by four: the CTK
    *declares* eleven in `conformance/CLAIMS.md`, and vectors like AH-CTK-022 are entirely
    *about* a reserved reason while asserting only `run_outcome: "blocked"`. The asserted-set
    criterion answers "what does the suite string-assert"; the question here is "what may a
    host legitimately use", which is a different and larger set.

    That gap was not cosmetic: the narrow set would have rejected
    `host_error:approval_resolver_failed` — a genuinely reserved identifier the adjacent
    #1542 design adopts — and blocked the next ticket in the chain.
    """

    #: Every identifier NAMED by either suite, at the versions in the disclosure.
    #: CTK (agent-hooks @ v0.1.0-alpha.3): 11 host_error:*, from CLAIMS.md and the vectors.
    #: Crate (agent-control-spec @ a830ed5): 6 runtime_error:*, from the 23 cases.
    #: `transform_target_forbidden` is named in BOTH namespaces — not a duplicate.
    #: IMPORTED, never re-typed. This list had a second hand-maintained copy
    #: here; two copies drift, and the copy that drifts permissively is the one
    #: nobody notices. shared/security/verdict_receipt.py is the runtime owner
    #: and refuses an invented identifier at construction; this scan catches one
    #: written anywhere else in the tree.
    KNOWN_RESERVED = KNOWN_RESERVED_REASONS

    #: Extensions scanned. An earlier version looked only at `*.py` under three
    #: directories, so the WinUI C# surface and every `.toml` were invisible.
    _SCANNED_SUFFIXES = (".py", ".cs", ".toml", ".md")
    _SCANNED_ROOTS = ("shared", "services", "launcher", "tools", "scripts", "evals")

    def _scan(self) -> set[str]:
        from pathlib import Path

        repo = Path(__file__).resolve().parents[2]
        pattern = re.compile(r"\b(?:host_error|runtime_error):[a-z_]+")
        found: set[str] = set()
        for sub in self._SCANNED_ROOTS:
            root = repo / sub
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if path.suffix not in self._SCANNED_SUFFIXES or not path.is_file():
                    continue
                try:
                    found.update(pattern.findall(path.read_text(encoding="utf-8")))
                except (OSError, UnicodeDecodeError):
                    continue
        return found

    def test_no_invented_reserved_identifiers_in_the_tree(self) -> None:
        invented = self._scan() - self.KNOWN_RESERVED

        assert not invented, (
            f"reserved-namespace identifier(s) named by neither ACS suite: {sorted(invented)}. "
            "The specification forbids a host inventing identifiers in these namespaces. "
            "Either use one of the seventeen, or use a BlarAI policy reason outside the "
            "reserved prefixes. If the suites have added one, update KNOWN_RESERVED and say "
            "which suite version names it."
        )

    def test_the_scan_actually_finds_something(self) -> None:
        """The REAL toggle, replacing one that guarded the wrong variable.

        The previous version asserted `len(KNOWN_RESERVED) == 13` — which says nothing
        about whether the scan reaches any code. Its own docstring named the correct
        hazard ("an empty *found* set ... would pass while checking nothing") and then
        checked the other side. This asserts the instrument is live: if the scan finds
        nothing, it is not evidence of cleanliness, it is evidence of a broken scan.
        """
        found = self._scan()

        assert found, (
            "the reserved-identifier scan found NOTHING anywhere in the tree. That is not "
            "a clean bill of health — BlarAI emits host_error:approval_identity_mismatch "
            "at the #1541 binding. A scan that finds nothing has stopped reaching the code."
        )
        assert found <= self.KNOWN_RESERVED

    def test_a_planted_invented_identifier_is_caught(self, tmp_path) -> None:
        """Proves the matcher works, without planting anything in the real tree."""
        probe = tmp_path / "probe.py"
        probe.write_text('BAD = "host_error:blarai_invented_thing"\n', encoding="utf-8")
        pattern = re.compile(r"\b(?:host_error|runtime_error):[a-z_]+")

        hits = set(pattern.findall(probe.read_text(encoding="utf-8")))

        assert hits == {"host_error:blarai_invented_thing"}
        assert hits - self.KNOWN_RESERVED, "a planted invented identifier was not flagged"

    def test_the_scan_cannot_see_a_constructed_identifier(self, tmp_path) -> None:
        """A KNOWN and DELIBERATE limit, asserted so it is not mistaken for coverage.

        A literal-text scan cannot see `f"host_error:{name}"`. Review demonstrated exactly
        that plant passing. This test pins the limitation rather than leaving a reader to
        assume the scan is exhaustive — the honest claim is "no invented identifier is
        written literally", not "none exists".
        """
        probe = tmp_path / "probe.py"
        probe.write_text('BAD = f"host_error:{name}"\n', encoding="utf-8")
        pattern = re.compile(r"\b(?:host_error|runtime_error):[a-z_]+")

        assert not pattern.findall(probe.read_text(encoding="utf-8")), (
            "the scan now sees constructed identifiers — good, but this test documents "
            "the opposite; update the disclosure's stated limits before deleting it"
        )
