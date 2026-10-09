"""#1542 Gap B: every verdict at the two live doors closes into a signed receipt.

Before this, the AO tool-dispatch adjudicator and the guarded-fetch egress door
recorded allow/deny/escalate with the application logger alone. A refusal — the
most security-relevant event either produces — left nothing a later reader could
verify.

These tests drive the REAL doors. The receipt builder is exercised directly only
where a test is about the builder's own refusals; everything about whether a
verdict actually reaches the chain goes through the door, because a receipt
function with no caller is the #1548 defect this sprint has already shipped once.

Each lock ships with a toggle proving the probe fails when the control is off,
and every toggle uses ``monkeypatch`` rather than a hand-rolled restore — a
hardcoded restore is what silently disabled #1548's capability tripwire.
"""

from __future__ import annotations

import pytest

from shared.security import guarded_fetch
from shared.security.audit_log import AuditLog, HmacSha256Signer
from shared.security.verdict_receipt import (
    KNOWN_RESERVED_REASONS,
    RECEIPT_FIELDS,
    ReceiptError,
    build_receipt,
    canonical_receipt,
)

_IDENT = "sha256:" + "ab" * 32
_OTHER = "sha256:" + "cd" * 32


def _chain() -> AuditLog:
    return AuditLog.in_memory(HmacSha256Signer(key=b"k" * 32))


def _receipt(**over: object) -> dict:
    base = dict(
        intervention_point="pre_tool_call",
        decision="allow",
        source_door="ao_tool_dispatch",
        reason="NO_RULE_MATCHED",
        input_identity=_IDENT,
        enforced_identity=_IDENT,
        liftable=False,
    )
    base.update(over)
    return build_receipt(**base)  # type: ignore[arg-type]


class TestTheChainStillVerifiesAcrossTheSchemaChange:
    """The ticket's 'must be traced first': do the new fields change the canonical
    bytes of records written before they existed?"""

    def test_a_pre_receipt_record_verifies_unchanged(self) -> None:
        """THE MIGRATION LOCK. A record with no receipt canonicalises exactly as
        it did before receipts existed, so nothing already on disk breaks."""
        log = _chain()
        for i in range(20):
            log.append(
                adjudication_id=f"old-{i}", decision="ALLOW", car_hash=f"h{i}",
                source_agent="ao", destination_service="tools", verb="EXECUTE",
                resource=f"tool_t{i}", sensitivity="INTERNAL",
                rule_engine_passed=True, confidence=1.0,
            )
        log.verify()

    def test_a_mixed_chain_verifies(self) -> None:
        """Both schema versions in ONE chain. This is the real shape after the
        change lands: old records below, receipt-bearing records above."""
        log = _chain()
        common = dict(
            source_agent="ao", destination_service="tools", verb="EXECUTE",
            sensitivity="INTERNAL", rule_engine_passed=True, confidence=1.0,
        )
        for i in range(20):
            log.append(adjudication_id=f"old-{i}", decision="ALLOW",
                       car_hash=f"h{i}", resource=f"t{i}", **common)
        for i in range(13):
            log.append(adjudication_id=f"new-{i}", decision="ALLOW",
                       car_hash=f"n{i}", resource=f"t{i}",
                       receipt=_receipt(), **common)
        log.verify()

    def test_the_two_versions_produce_DIFFERENT_bytes(self) -> None:
        """TOGGLE. Without this, a receipt silently dropped from the canonical
        bytes would pass every test above while the receipt was unsigned — the
        whole point being that the receipt is COVERED by the hash."""
        from shared.security.audit_log import _canonical_bytes

        kw = dict(
            seq=0, adjudication_id="a", decision="allow", car_hash="c",
            source_agent="s", destination_service="d", verb="v", resource="r",
            sensitivity="PUBLIC", rule_engine_passed=True, confidence=0.5,
            timestamp_utc="t", prev_hash="p",
        )
        assert _canonical_bytes(**kw) != _canonical_bytes(**kw, receipt=_receipt())
        assert b"receipt" not in _canonical_bytes(**kw)


class TestATamperedReceiptIsDetected:
    """The receipt is only evidence if editing it breaks verification."""

    @pytest.mark.parametrize(
        "mutate,label",
        [
            (lambda r: {**r, "smuggled": "payload"}, "a forged extra key"),
            (lambda r: {k: v for k, v in r.items() if k != "liftable"}, "a removed key"),
            (lambda r: {**r, "decision": "deny"}, "a flipped decision"),
            (lambda r: {**r, "reason": "SOMETHING_ELSE"}, "a rewritten reason"),
        ],
    )
    def test_editing_a_receipt_breaks_the_chain(self, mutate, label: str) -> None:
        """A forged extra key is the one that matters most and the one that was
        WRONG first: canonical_receipt originally filtered to the known fields,
        which made an added key invisible to the hash. A receipt carrying
        ``smuggled: payload`` verified clean."""
        log = _chain()
        rec = log.append(
            adjudication_id="a", decision="ALLOW", car_hash="c", source_agent="ao",
            destination_service="tools", verb="EXECUTE", resource="tool_x",
            sensitivity="INTERNAL", rule_engine_passed=True, confidence=1.0,
            receipt=_receipt(),
        )
        original = dict(rec.receipt or {})
        rec.receipt = mutate(original)
        from shared.security.audit_log import _canonical_bytes
        import hashlib

        recomputed = hashlib.sha256(
            _canonical_bytes(
                seq=rec.seq, adjudication_id=rec.adjudication_id,
                decision=rec.decision, car_hash=rec.car_hash,
                source_agent=rec.source_agent,
                destination_service=rec.destination_service, verb=rec.verb,
                resource=rec.resource, sensitivity=rec.sensitivity,
                rule_engine_passed=rec.rule_engine_passed,
                confidence=rec.confidence, timestamp_utc=rec.timestamp_utc,
                prev_hash=rec.prev_hash, receipt=rec.receipt,
            )
        ).hexdigest()
        assert recomputed != rec.record_hash, (
            f"{label} did not change the canonical bytes, so the chain would "
            "still verify and the receipt is evidence of nothing."
        )

    def test_an_UNTOUCHED_receipt_still_matches(self) -> None:
        """TOGGLE for the four above. If canonicalisation were non-deterministic
        every mutation would 'pass' while proving nothing."""
        log = _chain()
        rec = log.append(
            adjudication_id="a", decision="ALLOW", car_hash="c", source_agent="ao",
            destination_service="tools", verb="EXECUTE", resource="tool_x",
            sensitivity="INTERNAL", rule_engine_passed=True, confidence=1.0,
            receipt=_receipt(),
        )
        from shared.security.audit_log import _canonical_bytes
        import hashlib

        assert hashlib.sha256(
            _canonical_bytes(
                seq=rec.seq, adjudication_id=rec.adjudication_id,
                decision=rec.decision, car_hash=rec.car_hash,
                source_agent=rec.source_agent,
                destination_service=rec.destination_service, verb=rec.verb,
                resource=rec.resource, sensitivity=rec.sensitivity,
                rule_engine_passed=rec.rule_engine_passed,
                confidence=rec.confidence, timestamp_utc=rec.timestamp_utc,
                prev_hash=rec.prev_hash, receipt=rec.receipt,
            )
        ).hexdigest() == rec.record_hash

    def test_canonical_receipt_does_not_drop_unknown_keys(self) -> None:
        """The regression lock for the defect above, at the function itself."""
        assert "smuggled" in canonical_receipt({"decision": "allow", "smuggled": "x"})


class TestTheReceiptCarriesNoPayload:
    """A receipt states that a decision happened. It does not carry what was
    decided about."""

    def test_an_over_long_value_REFUSES_rather_than_truncating(self) -> None:
        with pytest.raises(ReceiptError, match="cap"):
            _receipt(detail="x" * 5_000)

    def test_a_truncated_payload_is_still_a_payload(self) -> None:
        """TOGGLE. A cap that truncated would let this pass with 200 characters
        of content in the signed record."""
        try:
            r = _receipt(detail="x" * 5_000)
        except ReceiptError:
            return
        pytest.fail(f"over-long detail was accepted, truncated to {len(r['detail'])}")

    def test_a_structured_value_is_refused(self) -> None:
        with pytest.raises(ReceiptError, match="not str or bool"):
            _receipt(detail={"tool_args": "secret"})  # type: ignore[arg-type]

    def test_the_field_set_is_exactly_the_schema(self) -> None:
        assert set(_receipt()) == set(RECEIPT_FIELDS)


class TestTheIdentitiesMustAgree:
    """#1541 Gap A, restated where the receipt can enforce it."""

    def test_a_mismatch_refuses(self) -> None:
        with pytest.raises(ReceiptError, match="not the action enforced"):
            _receipt(input_identity=_IDENT, enforced_identity=_OTHER)

    def test_a_missing_identity_refuses(self) -> None:
        """An identity that could not be derived is a mismatch, never a pass."""
        with pytest.raises(ReceiptError, match="both required"):
            _receipt(input_identity="", enforced_identity="")

    def test_a_malformed_identity_refuses(self) -> None:
        with pytest.raises(ReceiptError, match="canonical action identity"):
            _receipt(input_identity="tool:calculate", enforced_identity="tool:calculate")

    def test_MATCHING_identities_are_accepted(self) -> None:
        """TOGGLE. Without this, a builder that refused everything would pass all
        three tests above."""
        assert _receipt()["input_identity"] == _IDENT


class TestReservedNamespacesAreNotInventable:
    """The vocabulary control from #1547, enforced at construction rather than
    found later by a tree scan."""

    def test_an_invented_reserved_reason_refuses(self) -> None:
        with pytest.raises(ReceiptError, match="invents an identifier"):
            _receipt(reason="host_error:something_i_made_up")

    def test_a_real_reserved_reason_is_accepted(self) -> None:
        """TOGGLE for the above."""
        assert _receipt(reason="runtime_error:tool_unknown")["reason"] == (
            "runtime_error:tool_unknown"
        )

    def test_a_blarai_rule_name_is_accepted(self) -> None:
        assert _receipt(reason="DENY_RESTRICTED_PATH")["reason"] == "DENY_RESTRICTED_PATH"

    def test_the_runtime_list_is_what_the_tree_scan_uses(self) -> None:
        """One owner for the seventeen. The scan test reads this module rather
        than keeping a second copy that can drift from it."""
        assert len(KNOWN_RESERVED_REASONS) == 17
        assert all(
            r.startswith(("host_error:", "runtime_error:"))
            for r in KNOWN_RESERVED_REASONS
        )


class TestTheEgressDoorRecordsEveryVerdict:
    """Door 2, driven through the real ``_adjudicate``."""

    def test_a_denial_closes_into_a_receipt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A refusal is the event this ticket exists for. With no adjudicator
        registered the door denies fail-closed, and that denial must be recorded."""
        seen: list[dict] = []
        monkeypatch.setattr(
            guarded_fetch, "_receipt_sink",
            lambda **f: (seen.append(dict(f)), True)[1],
        )
        monkeypatch.setattr(guarded_fetch, "_adjudicator", None)

        verdict, _ = guarded_fetch._adjudicate("https://example.com/p?q=1", "test")

        assert verdict is guarded_fetch.Verdict.DENY
        assert seen, "the egress door denied and recorded NOTHING — Gap B itself."
        assert seen[0]["decision"] == "deny"

    def test_the_recorded_resource_is_the_HOST_not_the_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The LA's recorded decision on this ticket. A receipt that carried full
        URLs would become a browsing history in a signed, permanent file."""
        seen: list[dict] = []
        monkeypatch.setattr(
            guarded_fetch, "_receipt_sink",
            lambda **f: (seen.append(dict(f)), True)[1],
        )
        monkeypatch.setattr(guarded_fetch, "_adjudicator", None)

        guarded_fetch._adjudicate("https://example.com/secret-path?q=hunter2", "test")

        assert seen[0]["resource"] == "example.com"
        blob = repr(seen[0])
        assert "secret-path" not in blob and "hunter2" not in blob, (
            "the URL's path or query reached the receipt. The full URL contributes "
            "through the identity hash only."
        )

    def test_an_unrecordable_ALLOW_is_downgraded_to_DENY(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fail-closed. An egress door whose decision left no tamper-evident
        record has not proved it, so the allow does not stand."""
        monkeypatch.setattr(
            guarded_fetch, "_adjudicate_uncorded",
            lambda url, purpose: (guarded_fetch.Verdict.ALLOW, None),
        )
        monkeypatch.setattr(guarded_fetch, "_record_verdict", lambda **f: False)

        verdict, reason = guarded_fetch._adjudicate("https://example.com", "test")

        assert verdict is guarded_fetch.Verdict.DENY
        assert reason and "receipt" in reason

    def test_a_recordable_ALLOW_still_allows(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TOGGLE for the above. Without it, a door that denied unconditionally
        would pass the downgrade test while egress was simply broken."""
        monkeypatch.setattr(
            guarded_fetch, "_adjudicate_uncorded",
            lambda url, purpose: (guarded_fetch.Verdict.ALLOW, None),
        )
        monkeypatch.setattr(guarded_fetch, "_record_verdict", lambda **f: True)

        verdict, _ = guarded_fetch._adjudicate("https://example.com", "test")
        assert verdict is guarded_fetch.Verdict.ALLOW

    def test_the_default_sink_is_a_REAL_chain_not_a_no_op(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With no sink registered the door records to an in-memory chain rather
        than denying every fetch. That is a DURABILITY fallback, not a fail-open:
        the verdict is still hashed, chained and signed. A no-op returning True
        would satisfy every other test here while recording nothing."""
        monkeypatch.setattr(guarded_fetch, "_receipt_sink", None)
        monkeypatch.setattr(guarded_fetch, "_fallback_chain", None)

        assert guarded_fetch._record_verdict(
            decision="deny", reason="DENY_EXTERNAL_FETCH",
            url="https://example.com/x", purpose="test", liftable=False,
        )
        chain = guarded_fetch._fallback_chain
        assert chain is not None, "the fallback recorded nothing"
        chain.verify()


class TestTheDispatchDoorRecordsThroughTheREALToolLoop:
    """The locks that replaced two vacuous ones.

    The first version of this file "proved" the dispatch door was wired with two
    ``str.find`` scans over ``entrypoint.py``. Neither executed anything, and an
    independent review defeated both by replacing the real calls with a string
    literal and an inert ``dict(...)`` carrying the searched-for bytes: the full
    suite stayed green at 2937 passed while EVERY allowed tool dispatch went
    unrecorded. That is the #1548 defect, committed inside the change that cited
    #1548 as its reason for care.

    These drive the real ``_handle_connection`` tool loop and then read the real
    chain. A source scan cannot tell a call from a comment; a chain can.
    """

    @staticmethod
    def _service_with_chain():
        from services.assistant_orchestrator.tests.test_tools import _make_service

        service = _make_service()
        service._verdict_audit = _chain()
        return service

    @staticmethod
    def _drive(service, tool_call_text: str) -> None:
        from types import SimpleNamespace
        from unittest.mock import MagicMock, patch

        from shared.ipc.protocol import MessageFramer
        from services.assistant_orchestrator.tests.test_tools import _FakeTransport

        service._inference = MagicMock()
        responses = [
            SimpleNamespace(text=tool_call_text, token_count=5, error=None),
            SimpleNamespace(text="done.", token_count=3, error=None),
        ]
        service._inference.generate_text.side_effect = (
            lambda *a, **k: responses.pop(0) if responses else
            SimpleNamespace(text="done.", token_count=3, error=None)
        )
        with patch(
            "services.assistant_orchestrator.src.entrypoint.validate_output"
        ) as pgov:
            pgov.side_effect = lambda generated_text, **_k: SimpleNamespace(
                approved=True, sanitized_text=generated_text
            )
            request = MessageFramer().encode_prompt_request(
                session_id="verdict-receipt-test", prompt="go", request_id="r1"
            )
            service._handle_connection(_FakeTransport(request))

    def test_a_turn_with_ONE_tool_call_writes_EXACTLY_one_receipt(self) -> None:
        """How many receipts does one turn cost? (#1587)

        The per-receipt figure is ~110 ms of chip signature, and what it costs
        the operator is that figure times this count. Nobody had counted it, and
        a redesign was being weighed without it.

        The enforcement-point comment (entrypoint.py, the ALLOW receipt site)
        promises "one dispatch yields one record, and the recorded identity is
        the one that actually executes". That promise was asserted nowhere. A
        regression to two receipts per dispatch would double a cost the operator
        had been told about, and every existing test here reads ``records[-1]``,
        which is blind to the count by construction.
        """
        from services.assistant_orchestrator.tests.test_tools import _TIME_CALL

        service = self._service_with_chain()
        self._drive(service, _TIME_CALL)

        records = list(service._verdict_audit.records)
        assert len(records) == 1, (
            f"one tool call wrote {len(records)} verdict receipts, not 1: "
            f"{[r.receipt.get('decision') if r.receipt else None for r in records]}. "
            "The per-turn cost of the receipt path is this count times the "
            "per-receipt cost, so a change here changes what the operator was told."
        )

    def test_a_turn_with_NO_tool_call_writes_NO_receipt(self) -> None:
        """The control, and the other half of the cost model.

        A plain conversational turn must cost nothing at the verdict door. Without
        this, the count above is consistent with "one receipt per turn regardless",
        which would be a different and much worse cost model — every turn paying
        the chip whether or not it did anything adjudicable.
        """
        service = self._service_with_chain()
        self._drive(service, "just a plain answer with no tool call at all.")

        records = list(service._verdict_audit.records)
        assert records == [], (
            f"a turn with no tool call wrote {len(records)} verdict receipt(s). "
            "The receipt cost is supposed to be per ADJUDICATED ACTION, not per turn."
        )

    def test_TWO_tool_calls_write_TWO_receipts_not_one_and_not_three(self) -> None:
        """The cost is linear in tool calls, which is what makes it predictable.

        One data point cannot distinguish "one per dispatch" from "one per turn"
        — both give 1 for a single-call turn. This is the discriminating input,
        and it is what lets a reader multiply: an agentic loop of N steps costs N
        receipts, so N times the per-receipt figure.
        """
        from services.assistant_orchestrator.tests.test_tools import _TIME_CALL

        service = self._service_with_chain()
        self._drive_n(service, [_TIME_CALL, _TIME_CALL])

        records = list(service._verdict_audit.records)
        assert len(records) == 2, (
            f"two tool calls wrote {len(records)} receipts, not 2. The cost model "
            "reported to the operator assumes one receipt per adjudicated action."
        )

    @staticmethod
    def _drive_n(service, tool_call_texts: list[str]) -> None:
        """Drive a turn in which the model emits several tool calls in sequence."""
        from types import SimpleNamespace
        from unittest.mock import MagicMock, patch

        from shared.ipc.protocol import MessageFramer
        from services.assistant_orchestrator.tests.test_tools import _FakeTransport

        service._inference = MagicMock()
        responses = [
            SimpleNamespace(text=t, token_count=5, error=None)
            for t in tool_call_texts
        ] + [SimpleNamespace(text="done.", token_count=3, error=None)]
        service._inference.generate_text.side_effect = (
            lambda *a, **k: responses.pop(0) if responses else
            SimpleNamespace(text="done.", token_count=3, error=None)
        )
        with patch(
            "services.assistant_orchestrator.src.entrypoint.validate_output"
        ) as pgov:
            pgov.side_effect = lambda generated_text, **_k: SimpleNamespace(
                approved=True, sanitized_text=generated_text
            )
            request = MessageFramer().encode_prompt_request(
                session_id="verdict-receipt-test", prompt="go", request_id="r1"
            )
            service._handle_connection(_FakeTransport(request))

    def test_an_allowed_dispatch_writes_a_chained_signed_receipt(self) -> None:
        """THE TICKET'S FIRST NAMED LOCK: "a real tool dispatch yields a chained,
        signed record whose input_identity equals the CAR hash". The identity is
        recomputed from the real CAR here, not compared against a fixture
        constant -- the previous file asserted only against ``_IDENT``."""
        from services.assistant_orchestrator.src.entrypoint import _action_identity
        from services.assistant_orchestrator.tests.test_tools import _TIME_CALL

        service = self._service_with_chain()
        self._drive(service, _TIME_CALL)

        records = list(service._verdict_audit.records)
        assert records, (
            "an allowed tool dispatch wrote NO verdict receipt. Gap B for the "
            "allow half, and invisible to any test that scans source text."
        )
        rec = records[-1]
        assert rec.receipt is not None, "the record carries no receipt"
        assert rec.receipt["decision"] == "allow"
        assert rec.receipt["source_door"] == "ao_tool_dispatch"

        expected = _action_identity("get_current_time", "", "verdict-receipt-test")
        assert rec.receipt["input_identity"] == expected, (
            "the recorded identity is not the CAR hash of the dispatched action: "
            f"recorded {rec.receipt['input_identity']!r}, CAR hash {expected!r}"
        )
        assert rec.receipt["input_identity"] == rec.receipt["enforced_identity"]
        service._verdict_audit.verify()

    def test_a_refused_dispatch_writes_a_DENY_receipt(self) -> None:
        """The ticket's second named lock. A tool outside ``TOOL_CALL_ALLOWLIST``
        is refused before adjudication -- one of the six refusal paths that
        recorded nothing at all in the first version of this ship."""
        service = self._service_with_chain()
        self._drive(
            service,
            '<tool_call>{"name": "not_a_real_tool", "arguments": {}}</tool_call>',
        )

        denies = [
            r for r in service._verdict_audit.records
            if r.receipt and r.receipt["decision"] == "deny"
        ]
        assert denies, (
            "a refused dispatch wrote no receipt. A refusal is the most "
            "security-relevant event this door produces and is exactly what "
            "#1542 exists to record."
        )
        assert denies[-1].receipt["reason"] == "runtime_error:tool_unknown"
        service._verdict_audit.verify()

    def test_no_tool_call_writes_no_receipt(self) -> None:
        """TOGGLE. Without it, a door that recorded unconditionally -- or a chain
        pre-seeded by the fixture -- would satisfy both tests above while proving
        nothing about the dispatch path."""
        service = self._service_with_chain()
        self._drive(service, "Just a plain answer, no tool call.")

        assert not list(service._verdict_audit.records), (
            "a turn with no tool dispatch produced a verdict receipt"
        )


class TestEveryDispatchRefusalIsAccountedFor:
    """The structural control. Six of seven refusal paths were unrecorded and no
    test could have told me: each is a separate ``break`` and nothing counted
    them. Counting them means a refusal path added later fails loudly rather than
    being silently unrecorded."""

    @staticmethod
    def _loop_source() -> str:
        from pathlib import Path

        entry = (
            Path(__file__).resolve().parents[2]
            / "services" / "assistant_orchestrator" / "src" / "entrypoint.py"
        ).read_text(encoding="utf-8")
        adjudication = entry.index("_pa_verdict = _adjudicate_tool_dispatch")
        start = entry.rindex("if tool_name not in TOOL_CALL_ALLOWLIST", 0, adjudication)
        return entry[start:entry.index("tool_result = tools.execute(")]

    def test_every_refusal_between_the_allowlist_and_execute_records(self) -> None:
        """Each ``break`` out of the dispatch path must be preceded by a receipt
        call.

        This is a source scan and says so: it COUNTS call sites and is not
        evidence that any of them runs. What proves they run is
        ``TestTheDispatchDoorRecordsThroughTheREALToolLoop``, which drives the
        loop. The two together are the point -- neither alone was enough, and
        shipping only the scan is what the review caught.
        """
        import re

        source = self._loop_source()
        lines = source.splitlines()
        unrecorded: list[str] = []
        for n, line in enumerate(lines):
            # A break STATEMENT, not the word "break" inside a log message or a
            # comment -- the first version of this counter split on the bare
            # substring and reported "breaking loop" as an unrecorded path.
            if not re.match(r"^\s+break\b", line):
                continue
            window = "\n".join(lines[max(0, n - 30):n])
            if (
                "_audit_dispatch_deny(" not in window
                and "_audit_verdict(" not in window
            ):
                unrecorded.append(f"line {n}: {line.strip()[:80]}")
        assert not unrecorded, (
            "dispatch-door refusal path(s) with no verdict receipt in the "
            "preceding lines:\n  " + "\n  ".join(unrecorded)
        )

    def test_the_counter_can_fail(self) -> None:
        """TOGGLE for the counter. A scan finding no break statements at all
        would pass vacuously, which is precisely how the locks this replaced
        passed."""
        import re

        found = [
            ln for ln in self._loop_source().splitlines()
            if re.match(r"^\s+break\b", ln)
        ]
        assert len(found) >= 5, (
            f"the counter matched only {len(found)} break statements; it is "
            "scanning the wrong region and would pass vacuously."
        )


class TestTheEgressSinkIsRegisteredInProduction:
    """``register_receipt_sink`` shipped with ZERO production callers: the egress
    door fell back to an in-memory chain forever while three docstrings claimed a
    registration made it durable. The same defect as #1548, in the commit that
    cited #1548 as its reason for care."""

    def test_the_registered_sink_routes_egress_verdicts_to_the_service_chain(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """BEHAVIOURAL. Registers the orchestrator's real sink, then drives the
        real egress door and reads the service's own chain. Proves the wire
        carries traffic, not merely that a call site exists."""
        from services.assistant_orchestrator.tests.test_tools import _make_service

        service = _make_service()
        service._verdict_audit = _chain()
        service._register_egress_receipt_sink()

        monkeypatch.setattr(guarded_fetch, "_adjudicator", None)
        verdict, _ = guarded_fetch._adjudicate("https://example.com/p?q=1", "test")

        assert verdict is guarded_fetch.Verdict.DENY
        records = list(service._verdict_audit.records)
        assert records, (
            "the egress door recorded nothing into the orchestrator's chain. The "
            "registration seam has no production effect and every egress verdict "
            "dies with the process."
        )
        assert records[-1].receipt["source_door"] == "guarded_fetch_egress"
        assert records[-1].receipt["decision"] == "deny"
        assert records[-1].resource == "example.com"
        service._verdict_audit.verify()

    def test_start_calls_the_registration(self) -> None:
        """The counting half. ``start()`` cannot run under the test config, so
        this asserts the call site exists -- and says plainly that it is a source
        scan. The test above is what proves the sink works; this is what catches
        the sink being built and never hooked up, which is the defect that
        actually happened."""
        from pathlib import Path

        entry = (
            Path(__file__).resolve().parents[2]
            / "services" / "assistant_orchestrator" / "src" / "entrypoint.py"
        ).read_text(encoding="utf-8")
        start_body = entry[entry.index("def start(self)"):]
        start_body = start_body[:start_body.index("\n    def ")]
        assert "_register_egress_receipt_sink()" in start_body, (
            "start() does not register the egress receipt sink. The seam would "
            "have no production caller, which is exactly what review found."
        )
