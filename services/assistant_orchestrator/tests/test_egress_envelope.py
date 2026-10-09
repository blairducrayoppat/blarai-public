r"""Unit tests for the turn-scoped Hello egress envelope (ADR-023 Am.4, #723 rung 3).

Covers the pure state machine (:class:`EgressEnvelopeManager`), the query
extractor, and the production ``consent_fn`` (:func:`request_egress_fingerprint`)
routing to the shared operator-approval verifier — all WITHOUT a biometric device
(the consent callback is injected / the verifier is a mock). The end-to-end tool
loop wiring is exercised in test_retrieval_tools.py.
"""

from __future__ import annotations

from typing import Any

import unicodedata

import pytest

from services.assistant_orchestrator.src import egress_envelope
from services.assistant_orchestrator.src.egress_envelope import (
    MAX_DISCLOSABLE_QUERY_CHARS,
    QueryNotDisclosableError,
    EgressEnvelopeManager,
    extract_query,
    request_egress_fingerprint,
)


# ---------------------------------------------------------------------------
# The state machine
# ---------------------------------------------------------------------------


class _ConsentRecorder:
    """A stub consent_fn recording (query, n) calls and returning a fixed verdict
    (or a per-call sequence)."""

    def __init__(self, verdicts: list[bool] | bool = True) -> None:
        self.calls: list[tuple[str, int]] = []
        self._verdicts = verdicts

    def __call__(self, query: str, n: int) -> bool:
        self.calls.append((query, n))
        if isinstance(self._verdicts, bool):
            return self._verdicts
        return self._verdicts[len(self.calls) - 1]


class TestEgressEnvelopeManager:
    def test_gate_without_begin_turn_is_denied_fail_closed(self) -> None:
        mgr = EgressEnvelopeManager()
        consent = _ConsentRecorder(True)
        decision = mgr.gate("s1", "q", consent_fn=consent)
        assert decision.allowed is False
        assert decision.fingerprinted is False
        assert consent.calls == []  # never prompted — no envelope armed

    def test_first_egress_fingerprints_then_window_covers_up_to_n(self) -> None:
        """N=3: query 1 fingerprints; 2 and 3 ride the open window (no re-prompt);
        query 4 (beyond N) triggers a fresh fingerprint."""
        mgr = EgressEnvelopeManager()
        consent = _ConsentRecorder(True)
        mgr.begin_turn("s1", 3)

        d1 = mgr.gate("s1", "q1", consent_fn=consent)
        d2 = mgr.gate("s1", "q2", consent_fn=consent)
        d3 = mgr.gate("s1", "q3", consent_fn=consent)
        d4 = mgr.gate("s1", "q4", consent_fn=consent)

        assert [d.allowed for d in (d1, d2, d3, d4)] == [True, True, True, True]
        # Only q1 and q4 required a fingerprint.
        assert [d.fingerprinted for d in (d1, d2, d3, d4)] == [True, False, False, True]
        assert consent.calls == [("q1", 3), ("q4", 3)]

    def test_n_equals_1_fingerprints_every_query(self) -> None:
        mgr = EgressEnvelopeManager()
        consent = _ConsentRecorder(True)
        mgr.begin_turn("s1", 1)
        for q in ("q1", "q2", "q3"):
            d = mgr.gate("s1", q, consent_fn=consent)
            assert d.allowed and d.fingerprinted
        assert consent.calls == [("q1", 1), ("q2", 1), ("q3", 1)]

    def test_denied_fingerprint_latches_for_the_turn(self) -> None:
        """A denied first fingerprint ends egress for the turn — a later egress is
        refused WITHOUT re-prompting (a fooled model cannot retry past a refusal)."""
        mgr = EgressEnvelopeManager()
        consent = _ConsentRecorder(False)
        mgr.begin_turn("s1", 3)

        d1 = mgr.gate("s1", "q1", consent_fn=consent)
        d2 = mgr.gate("s1", "q2", consent_fn=consent)

        assert d1.allowed is False and d1.fingerprinted is True
        assert d2.allowed is False and d2.fingerprinted is False
        assert consent.calls == [("q1", 3)]  # prompted once, then latched denied

    def test_consent_fn_exception_is_fail_closed(self) -> None:
        mgr = EgressEnvelopeManager()

        def _boom(query: str, n: int) -> bool:
            raise RuntimeError("verifier blew up")

        mgr.begin_turn("s1", 3)
        d = mgr.gate("s1", "q1", consent_fn=_boom)
        assert d.allowed is False
        # And it latched — a second egress is refused without another attempt.
        d2 = mgr.gate("s1", "q2", consent_fn=_ConsentRecorder(True))
        assert d2.allowed is False

    def test_begin_turn_resets_the_envelope(self) -> None:
        mgr = EgressEnvelopeManager()
        consent = _ConsentRecorder(True)
        mgr.begin_turn("s1", 3)
        mgr.gate("s1", "q1", consent_fn=consent)  # fingerprint window opens
        mgr.begin_turn("s1", 3)  # NEW turn — must re-fingerprint
        d = mgr.gate("s1", "q_new", consent_fn=consent)
        assert d.fingerprinted is True
        assert consent.calls == [("q1", 3), ("q_new", 3)]

    def test_begin_turn_clamps_n_below_one_to_one(self) -> None:
        mgr = EgressEnvelopeManager()
        consent = _ConsentRecorder(True)
        mgr.begin_turn("s1", 0)  # nonsensical N — floored to 1 (fingerprint every)
        d1 = mgr.gate("s1", "q1", consent_fn=consent)
        d2 = mgr.gate("s1", "q2", consent_fn=consent)
        assert d1.fingerprinted and d2.fingerprinted

    def test_sessions_are_independent(self) -> None:
        mgr = EgressEnvelopeManager()
        consent = _ConsentRecorder(True)
        mgr.begin_turn("s1", 3)
        mgr.begin_turn("s2", 3)
        mgr.gate("s1", "a", consent_fn=consent)  # opens s1 window
        d = mgr.gate("s2", "b", consent_fn=consent)  # s2 still needs its own fp
        assert d.fingerprinted is True


class TestRetainOnly:
    """#801: the session idle-reaper's envelope companion."""

    def test_drops_envelopes_for_dead_sessions(self) -> None:
        mgr = EgressEnvelopeManager()
        mgr.begin_turn("live", 3)
        mgr.begin_turn("dead", 3)
        dropped = mgr.retain_only(["live"])
        assert dropped == ["dead"]

    def test_survivor_window_state_is_untouched(self) -> None:
        # retain_only must not reset a live session's open window.
        mgr = EgressEnvelopeManager()
        consent = _ConsentRecorder(True)
        mgr.begin_turn("live", 3)
        mgr.gate("live", "q1", consent_fn=consent)  # window open (1 of 3)
        mgr.begin_turn("dead", 3)
        mgr.retain_only(["live"])
        d = mgr.gate("live", "q2", consent_fn=consent)
        assert d.allowed is True
        assert d.fingerprinted is False  # still within the open window
        assert consent.calls == [("q1", 3)]

    def test_dropped_session_gates_fail_closed(self) -> None:
        # After the drop, an egress on the dead session DENIES (no envelope).
        mgr = EgressEnvelopeManager()
        mgr.begin_turn("dead", 3)
        mgr.retain_only([])
        d = mgr.gate("dead", "q", consent_fn=_ConsentRecorder(True))
        assert d.allowed is False

    def test_empty_manager_and_idempotency(self) -> None:
        mgr = EgressEnvelopeManager()
        assert mgr.retain_only(["anything"]) == []
        mgr.begin_turn("s1", 3)
        assert mgr.retain_only(["s1"]) == []
        assert mgr.retain_only(["s1"]) == []


class TestExtractQuery:
    def test_valid_query(self) -> None:
        assert extract_query('{"query":"bitcoin price"}') == "bitcoin price"

    def test_missing_query_field(self) -> None:
        assert extract_query('{"max_results":5}') == "(query unavailable)"

    def test_malformed_json(self) -> None:
        assert extract_query("not json") == "(query unavailable)"

    def test_empty_args(self) -> None:
        assert extract_query("") == "(query unavailable)"

    def test_non_string_query(self) -> None:
        assert extract_query('{"query":123}') == "(query unavailable)"

    def test_blank_query_falls_back(self) -> None:
        assert extract_query('{"query":"   "}') == "(query unavailable)"

    def test_long_query_is_REFUSED_not_capped(self) -> None:
        """Was ``test_long_query_capped_at_200``, and it asserted the defect.

        The old test read ``assert len(out) == 200`` on a 500-character query and
        passed, which means the truncation was not an oversight — it was LOCKED.
        A test that encodes a defect as expected behaviour is the strongest form
        of the thing this suite exists to prevent, and it is worth naming rather
        than quietly rewriting: what the operator was shown and what the adapter
        sent had drifted apart, and a green test certified the drift.

        #1592: a query that cannot be disclosed in full is refused, because an
        approval covering the first 200 characters approves the rest unseen.
        """
        long_q = "x" * 500
        with pytest.raises(QueryNotDisclosableError):
            extract_query('{"query":"' + long_q + '"}')


# ---------------------------------------------------------------------------
# The production consent_fn — routes to the shared operator-approval verifier
# ---------------------------------------------------------------------------


class _RecordingVerifier:
    """A mock ApprovalVerifier capturing the context it was handed."""

    def __init__(self, approved: bool) -> None:
        self._approved = approved
        self.seen: list[Any] = []

    def verify(self, context: Any) -> Any:
        from shared.security.escalation_consent import ApprovalResult

        self.seen.append(context)
        if self._approved:
            return ApprovalResult.allow(verifier_identity="mock-hello")
        return ApprovalResult.deny("mock deny", verifier_identity="mock-hello")


@pytest.fixture(autouse=True)
def _isolate_verifier() -> Any:
    """Snapshot + clear the process verifier registry around each test so a mock
    never leaks and the dormant default is restored."""
    from shared.security.escalation_consent import (
        active_verifier,
        clear_verifier,
        register_verifier,
    )

    saved = active_verifier()
    clear_verifier()
    yield
    clear_verifier()
    if saved is not None:
        register_verifier(saved)


class TestRequestEgressFingerprint:
    def test_no_verifier_registered_is_denied(self) -> None:
        # Dormant default (no operator surface wired) → fail-closed deny.
        assert request_egress_fingerprint("q", 3, timeout_s=1.0) is False

    def test_approved_verifier_allows_and_context_is_egress_shaped(self) -> None:
        from shared.security.escalation_consent import register_verifier

        verifier = _RecordingVerifier(approved=True)
        register_verifier(verifier)
        assert request_egress_fingerprint("bitcoin price", 3, timeout_s=1.0) is True
        # The context routed to the verifier is EGRESS-shaped: source="egress"
        # (so the Hello dialog reads as an egress consent) and the query + the
        # "up to N" bound are surfaced (the operator must SEE the query to judge).
        ctx = verifier.seen[0]
        assert ctx.source == "egress"
        assert ctx.tool_name == "web_search"
        assert "bitcoin price" in ctx.action_summary
        assert "up to 3 searches" in ctx.action_summary

    def test_denied_verifier_denies(self) -> None:
        from shared.security.escalation_consent import register_verifier

        register_verifier(_RecordingVerifier(approved=False))
        assert request_egress_fingerprint("q", 3, timeout_s=1.0) is False

    def test_singular_search_wording_for_n_1(self) -> None:
        from shared.security.escalation_consent import register_verifier

        verifier = _RecordingVerifier(approved=True)
        register_verifier(verifier)
        request_egress_fingerprint("q", 1, timeout_s=1.0)
        assert "up to 1 search " in verifier.seen[0].action_summary + " "


# ===========================================================================
# #1592 — the approved string and the sent string must be the SAME string.
# ===========================================================================
class TestTheOperatorApprovesWhatActuallyLeaves:
    """The envelope's entire value is that a human read the outbound query.

    `extract_query` used to return `descriptor[:200]`, and that 200-character
    string was what `request_egress_fingerprint` put in the Windows Hello dialog
    while the adapter sent the full, untruncated query. A 5,000-character query
    showed the operator 200 characters and sent 5,000 — everything after
    character 200 approved without ever being displayed.

    The cap bounded the DISPLAY, not the PAYLOAD. An approval is worth exactly
    the fraction of the string it covers, so that asymmetry was an exfiltration
    channel straight through the control.

    These hold the mechanism fixed and vary only the query LENGTH.
    """

    @staticmethod
    def _args(query: str) -> str:
        import json

        return json.dumps({"query": query}, separators=(",", ":"), sort_keys=True)

    def test_a_query_that_FITS_is_returned_whole_and_unmodified(self) -> None:
        """The control. Without it, "refuses long queries" is indistinguishable
        from "refuses everything", and the refusal below proves nothing."""
        query = "what is the weather in reykjavik tomorrow"
        assert extract_query(self._args(query)) == query

    def test_a_query_AT_the_limit_is_still_returned_whole(self) -> None:
        """The boundary, from the allowed side. An off-by-one here would refuse
        a legitimate query and read as security rather than as a bug."""
        query = "x" * MAX_DISCLOSABLE_QUERY_CHARS
        assert extract_query(self._args(query)) == query
        assert len(extract_query(self._args(query))) == MAX_DISCLOSABLE_QUERY_CHARS

    def test_a_query_ONE_CHARACTER_OVER_is_REFUSED_not_truncated(self) -> None:
        """The boundary, from the refused side — and the regression itself.

        One character over the limit must RAISE. It must not return a shortened
        string, because a caller that receives a string proceeds, and what it
        proceeds to send is the untruncated original.
        """
        query = "x" * (MAX_DISCLOSABLE_QUERY_CHARS + 1)
        with pytest.raises(QueryNotDisclosableError):
            extract_query(self._args(query))

    def test_a_LONG_query_carrying_a_secret_is_REFUSED(self) -> None:
        """The shape that made this a security defect rather than a display bug.

        A query whose first 200 characters are innocuous and whose tail carries a
        planted secret: the operator would have seen only the innocuous prefix,
        approved it, and the whole thing would have left.
        """
        innocuous = "best hiking trails near reykjavik " * 8  # comfortably > 200
        query = innocuous + " ssn 123-45-6789"
        assert len(query) > MAX_DISCLOSABLE_QUERY_CHARS
        with pytest.raises(QueryNotDisclosableError) as caught:
            extract_query(self._args(query))
        # The refusal must not echo the payload into a log line or a dialog.
        assert "123-45-6789" not in str(caught.value), (
            "the refusal message quotes the secret it refused to send"
        )
        assert str(len(query)) in str(caught.value), (
            "the refusal should tell the operator how long the query was"
        )

    def test_WITH_THE_CHECK_DISABLED_the_secret_reaches_the_operator_surface(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The off-test, second attempt — this one can fail when the lock is off.

        My first version computed ``query[:200]`` inside the test body and
        asserted things about that local string. It never called
        ``extract_query``, so it passed with the length check entirely removed:
        a probe that cannot fail when the lock is off certifies nothing, which
        is the exact criticism this session has levelled at three other files.

        This disables the lock the way a regression would — by raising the cap
        past the fixture — and then measures the SHIPPED function. What it
        returns is what the Hello dialog displays, so the assertion is about the
        operator's surface rather than about slicing.
        """
        innocuous = "best hiking trails near reykjavik " * 8
        query = innocuous + " ssn 123-45-6789"
        assert len(query) > MAX_DISCLOSABLE_QUERY_CHARS, "fixture too short"

        # With the lock ON, the shipped function refuses.
        with pytest.raises(QueryNotDisclosableError):
            extract_query(self._args(query))

        # With the lock OFF — one condition varied — it returns, and what it
        # returns is a string the operator would have been shown.
        monkeypatch.setattr(
            egress_envelope, "MAX_DISCLOSABLE_QUERY_CHARS", len(query) + 1
        )
        shown = egress_envelope.extract_query(self._args(query))
        assert shown == query, (
            "with the cap lifted the function must return the query — if it does "
            "not, this probe is measuring something other than the lock"
        )
        assert "123-45-6789" in shown, (
            "the secret is in what the operator is shown; the fixture does not "
            "reproduce the hidden-tail case"
        )


def _unrender(rendered: str) -> str:
    """Decode a disclosure rendering back to the query it was made from.

    Test-side on purpose. Shipping an inverse nothing calls would be the
    built-but-wired-into-nothing shape this ticket keeps tripping over; what the
    runtime needs is the forward direction, and what the RECORD needs is evidence
    that the forward direction loses nothing. This is that evidence.
    """
    out: list[str] = []
    i = 0
    while i < len(rendered):
        char = rendered[i]
        if char != "\\":
            out.append(char)
            i += 1
        elif rendered[i + 1] == "\\":
            out.append("\\")
            i += 2
        elif rendered[i + 1] == "u":
            out.append(chr(int(rendered[i + 2 : i + 6], 16)))
            i += 6
        elif rendered[i + 1] == "U":
            out.append(chr(int(rendered[i + 2 : i + 10], 16)))
            i += 10
        else:  # pragma: no cover - would mean the encoding emitted something else
            raise AssertionError(f"unrecognised escape at offset {i}")
    return "".join(out)


class TestAQueryMustNotBeAbleToHIDEItself:
    """Findings 2 and 1 of the #1592 review, in that order.

    FINDING 2 - I fixed the instance, not the class. The defect class is "what the
    operator sees is not what is sent"; I had bounded LENGTH. A THIRTY-TWO
    character query passes any cap untouched and reaches both the Hello prompt and
    the chat disclosure verbatim, with its tail pushed off whatever the reader is
    looking at. ``q.strip()`` removes outer whitespace and nothing else, so
    control characters, zero-width characters and bidi overrides all survive it.
    **A length cap is not a disclosure guarantee.**

    FINDING 1 - my first answer to that was to REFUSE any query containing such a
    character, and it was over-broad in a way that cost real capability: U+200C
    and U+200D are orthographically required in Persian and Devanagari and are
    carried by ordinary emoji sequences, ``Cc`` contains TAB, and ``Cn`` is every
    code point newer than the interpreter's Unicode table - so the same query
    could be refused on one Python and sent on the next. The refusal ended the
    whole turn.

    **The answer is to ESCAPE, not to refuse.** The operator sees every byte, the
    hidden-tail attack becomes visible rather than merely blocked - which tells
    them strictly more than a refusal does - and nothing legitimate is turned
    away. These tests hold both halves: what must become visible, and what must
    still go through untouched.
    """

    @staticmethod
    def _args(query: str) -> str:
        import json

        return json.dumps({"query": query}, separators=(",", ":"), sort_keys=True)

    @pytest.mark.parametrize(
        ("label", "query"),
        [
            ("newline-scrolled tail", "cats" + "\n" * 12 + " ssn 123-45-6789"),
            ("carriage-return overwrite", "cats\r" + " ssn 123-45-6789"),
            ("bidi override U+202E", "cats‮ ssn 123-45-6789"),
            ("zero-width spaces", "cats" + "​" * 20 + " ssn 123-45-6789"),
            ("ANSI erase-screen", "cats\x1b[2J\x1b[H ssn 123-45-6789"),
            ("line separator U+2028", "cats  ssn 123-45-6789"),
            ("paragraph separator U+2029", "cats  ssn 123-45-6789"),
            ("private use U+E000", "cats ssn 123-45-6789"),
            ("unassigned U+0378", "cats͸ ssn 123-45-6789"),
        ],
    )
    def test_a_SHORT_query_that_hides_its_tail_is_MADE_VISIBLE(
        self, label: str, query: str
    ) -> None:
        """Each of these is well under the length cap, so ONLY the rendering can
        expose it. If the length check were the whole control, every one of these
        would be shown to the operator with its tail hidden, and then sent.

        The assertion is that the shown string contains NO invisible character and
        DOES contain the planted secret - the operator can read the whole thing,
        including the part that was hiding, and decide.
        """
        assert len(query) <= MAX_DISCLOSABLE_QUERY_CHARS, (
            f"{label}: fixture is long enough that the LENGTH rule would catch it, "
            "which would make this test measure the wrong control"
        )
        shown = extract_query(self._args(query))

        offenders = [
            f"U+{ord(c):04X}({unicodedata.category(c)})"
            for c in shown
            if unicodedata.category(c) in egress_envelope._INVISIBLE_CATEGORIES
        ]
        assert not offenders, (
            f"{label}: the string shown to the operator still contains characters "
            f"they cannot see: {offenders}"
        )
        assert "123-45-6789" in shown, (
            f"{label}: the planted tail is absent from what the operator is shown, "
            "so the rendering hid it rather than revealing it"
        )
        assert _unrender(shown) == query, (
            f"{label}: the rendering is not reversible, so what the operator "
            "approved cannot be shown to be what is sent"
        )

    @pytest.mark.parametrize(
        ("label", "query"),
        [
            ("plain english", "openvino release notes"),
            ("punctuation and accents", "what's the weather in Reykjavík? (°C)"),
            ("japanese", "東京の天気"),
            ("arabic", "الطقس في دبي"),
            ("greek", "Ποιος είναι ο καιρός"),
            ("persian with ZWNJ", "کتاب‌های تاریخ"),
            ("hindi with ZWJ", "क‍ष हिंदी"),
            ("emoji", "\U0001f600 best pizza"),
            ("currency and maths", "€50 → $55 ± 2%"),
        ],
    )
    def test_ORDINARY_TEXT_GOES_THROUGH_UNTOUCHED(
        self, label: str, query: str
    ) -> None:
        """The control, and the finding-1 regression lock.

        Without this, "makes hidden tails visible" is indistinguishable from
        "mangles or refuses anything interesting". The Persian and Hindi cases are
        the specific ones the reviewer caught being REFUSED outright: U+200C and
        U+200D are required orthography there, not smuggling. They are escaped
        rather than refused now, so the search runs, and the operator sees the
        escape where the joiner is - which is honest and costs no capability.
        """
        shown = extract_query(self._args(query))
        assert _unrender(shown) == query, f"{label}: rendering is not reversible"
        has_escapable = any(
            unicodedata.category(c) in egress_envelope._INVISIBLE_CATEGORIES
            or c == "\\"
            for c in query
        )
        if not has_escapable:
            assert shown == query, (
                f"{label}: ordinary text was altered on the way to the operator"
            )

    def test_a_TAB_does_not_end_the_turn(self) -> None:
        """A model composing ``site:x.com<TAB>python`` should get a search, not a
        refusal. Tab is category Cc, which the refusing version denied outright.
        """
        assert extract_query(self._args("site:x.com\tpython")) == (
            "site:x.com\\u0009python"
        )

    def test_a_BACKSLASH_is_escaped_so_the_rendering_is_UNAMBIGUOUS(self) -> None:
        """Without this the encoding is not injective: a query containing the six
        literal characters of an escape sequence would render identically to one
        containing the actual character, and the operator could not tell which
        they were approving. An ambiguous rendering is not a disclosure.
        """
        literal = "cats \\u200c dogs"
        actual = "cats ‌ dogs"
        assert literal != actual
        shown_literal = extract_query(self._args(literal))
        shown_actual = extract_query(self._args(actual))
        assert shown_literal != shown_actual, (
            "two different queries render to the same string shown to the operator"
        )
        assert _unrender(shown_literal) == literal
        assert _unrender(shown_actual) == actual

    def test_the_LENGTH_cap_is_measured_on_what_the_operator_READS(self) -> None:
        """An escaped character costs six characters of the operator's attention,
        so the cap has to be applied to the rendering. Applying it to the raw
        query would let a 40-character query become a 240-character wall of
        escapes that does not fit - the original defect, re-entered sideways.
        """
        query = "​" * 40  # 40 raw, 240 rendered
        assert len(query) <= MAX_DISCLOSABLE_QUERY_CHARS
        assert len(egress_envelope.render_for_disclosure(query)) > (
            MAX_DISCLOSABLE_QUERY_CHARS
        )
        with pytest.raises(QueryNotDisclosableError) as caught:
            extract_query(self._args(query))
        assert "renders to 240" in str(caught.value), (
            "the refusal should report the length the operator would have read, "
            "not the raw length, or the number in it is about the wrong string"
        )

    @pytest.mark.parametrize("category", ["Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"])
    def test_EVERY_declared_category_is_actually_escaped(self, category: str) -> None:
        """Principle 12, applied to the SET rather than to the function.

        The reviewer dropped each category from ``_INVISIBLE_CATEGORIES`` in turn
        and found only Cc and Cf were held by any test - the other five were
        declared and unlocked, including Zl and Zp, which are hidden-tail
        characters in exactly the sense this control exists for. A set is not
        tested because one of its members is.
        """
        sample = {
            "Cc": "\x07",
            "Cf": "‍",
            "Cs": "\ud800",
            "Co": "",
            "Cn": "͸",
            "Zl": " ",
            "Zp": " ",
        }[category]
        assert unicodedata.category(sample) == category, (
            f"the {category} sample is not {category} on this interpreter "
            f"(unicodedata {unicodedata.unidata_version}); the fixture needs "
            "updating, not the control"
        )
        rendered = egress_envelope.render_for_disclosure(f"a{sample}b")
        assert rendered == f"a\\u{ord(sample):04x}b", (
            f"category {category} is declared invisible but passes through "
            "unescaped, so the operator is shown a character they cannot see"
        )

    @pytest.mark.parametrize(
        ("label", "char"),
        [
            ("LANGUAGE TAG U+E0001", "\U000e0001"),
            ("TAG LATIN A U+E0041", "\U000e0041"),
            ("TAG SPACE U+E0020", "\U000e0020"),
            ("plane-15 private use U+F0000", "\U000f0000"),
            ("unassigned astral U+E0002", "\U000e0002"),
        ],
    )
    def test_ASTRAL_invisible_characters_are_escaped_too(
        self, label: str, char: str
    ) -> None:
        """The above-U+FFFF branch, which a mutation run found untested — and it
        is the branch that matters most.

        U+E0000–U+E007F is the Unicode TAG BLOCK: invisible characters that mirror
        ASCII and are the published ASCII-smuggling channel (the 2024 M365 Copilot
        proof of concept exfiltrated a multi-factor code through it). They are
        category Cf, so the category rule already covers them, but they need the
        eight-digit escape form, and dropping that branch left every one of them
        passing through the disclosure unseen while the whole suite stayed green.
        """
        query = f"cats{char} ssn 123-45-6789"
        shown = extract_query(self._args(query))
        assert shown == f"cats\\U{ord(char):08x} ssn 123-45-6789", (
            f"{label}: an invisible astral character reached the operator's "
            "screen unescaped"
        )
        assert _unrender(shown) == query, f"{label}: rendering is not reversible"

    def test_the_refusal_names_the_LENGTH_not_the_text(self) -> None:
        """What the operator and the log get must locate the problem without
        reproducing the payload.
        """
        query = "reykjavik hiking " * 30 + " ssn 123-45-6789"
        with pytest.raises(QueryNotDisclosableError) as caught:
            extract_query(self._args(query))
        message = str(caught.value)
        assert str(MAX_DISCLOSABLE_QUERY_CHARS) in message
        assert "123-45-6789" not in message, (
            "the refusal quotes the secret it refused to disclose"
        )
        assert "reykjavik" not in message, (
            "the refusal echoes the query text; it should measure, not quote"
        )

    def test_a_MISSING_query_still_degrades_rather_than_raising(self) -> None:
        """Unchanged behaviour, asserted so the fix did not widen the refusal.

        A parse failure or absent field yields a generic descriptor: the gate
        never depends on this for allow/deny, only for what is SHOWN, and the
        operator can still refuse. Turning that into an exception would deny
        legitimate calls for a reason unrelated to disclosure.
        """
        assert extract_query("") == "(query unavailable)"
        assert extract_query("not json at all") == "(query unavailable)"
        assert extract_query('{"not_query": "x"}') == "(query unavailable)"
