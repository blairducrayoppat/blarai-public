"""Gate: curating the knowledge bank rehearses, refuses, and erases EXACTLY
what was approved (#1567).

Driven through the REAL ``EncryptedKnowledgeBank`` — real cipher, real schema,
real ``secure_delete``, real ``ON DELETE CASCADE``. The rehearsal and execution
methods are the AO's own, bound to a shim carrying only the two attributes they
touch (``_knowledge``, ``_rehearsed_curation``), which is the pattern #1587
used to drive a shipped method without booting the service. The shim has no
other attributes, so a method that reached for one would raise rather than
silently take a different path.

WHAT IS LOCKED, and each is a sentence from the ticket:

  * a dry run mutates nothing
  * an empty selector refuses, and matches NOTHING rather than everything
  * a match set over the cap refuses, and is never truncated
  * an approved execution erases exactly the rehearsed set and no more
  * a set that changed between the rehearsal and the approval fails closed
  * an erase with no matching rehearsal fails closed
  * ``delete`` always rehearses; ``mark_saved`` does not
  * the operator's document titles never reach the consent surface

Each with a toggle proving the probe fails when the control is off.
"""

from __future__ import annotations

import json
import uuid

import pytest

from services.assistant_orchestrator.src import tools
from services.assistant_orchestrator.src.entrypoint import (
    AssistantOrchestratorService,
)
from services.assistant_orchestrator.src.knowledge_bank import EncryptedKnowledgeBank
from shared.security.dek_envelope import DekEnvelope, generate_recovery_key
from shared.security.field_cipher import FieldCipher, derive_subkeys
from shared.security.tpm_sealer import SoftwareSealer

_OTHER_SOURCE = "https://elsewhere.example/keep-me"


def _fake_embed(texts):
    import numpy as np

    from services.assistant_orchestrator.src.substrate import EMBED_DIM

    return np.zeros((len(list(texts)), EMBED_DIM), dtype="float32")


class _Shim:
    """Carries ONLY what the two methods touch. Anything else raises."""

    def __init__(self, bank: EncryptedKnowledgeBank | None) -> None:
        self._knowledge = bank
        self._rehearsed_curation: tuple[str, tuple[str, ...]] | None = None

    rehearse = AssistantOrchestratorService._rehearse_curate_knowledge
    run = AssistantOrchestratorService._run_curate_knowledge_tool


@pytest.fixture()
def bank():
    sealer = SoftwareSealer()
    env = DekEnvelope.create(sealer=sealer, recovery_key=generate_recovery_key())
    b = EncryptedKnowledgeBank(
        db_path=":memory:",
        embed_fn=_fake_embed,
        cipher=FieldCipher(derive_subkeys(env.unseal_dek())),
    )
    yield b
    b.close()


def _approved(
    bank: EncryptedKnowledgeBank, *, source_ref: str, title: str,
    source_type: str = "url",
) -> str:
    doc_uuid = str(uuid.uuid4())
    bank.submit_pending(
        doc_uuid=doc_uuid,
        source_type=source_type,
        source_ref=source_ref,
        # DISTINCT per document: the bank dedups on a keyed content digest
        # and REPLACES a match, so identical bodies would collapse three
        # fixtures into one and this file would be testing a set of size 1.
        content=f"Saved content {title} about engines and their behaviour.",
        title=title,
        byline="A. Writer",
        published_date="2026-06-01",
        cleaner_version="cleaner-v1",
        word_count=9,
    )
    bank.approve(doc_uuid)
    return doc_uuid


def _rows(bank: EncryptedKnowledgeBank) -> tuple[int, int]:
    docs = bank._conn.execute("SELECT COUNT(*) FROM knowledge_docs").fetchone()[0]
    chunks = bank._conn.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0]
    return int(docs), int(chunks)


#: Selects by TYPE, not by source_ref, and the reason is a property of the bank
#: rather than a preference. ``submit_pending`` dedups on ``source_hash`` and
#: never replaces an APPROVED document, so a source reference identifies AT MOST
#: ONE approved document. A ``source_ref`` selector therefore matches a set of
#: size one -- the case where the argument IS the effect, which is exactly the
#: condition #1567 names as NOT needing a rehearsal. The selectors that produce
#: a set nobody can compute in their head are ``source_type`` and the date
#: ranges, so those are what this file drives.
_SELECTOR = json.dumps({"action": "delete", "source_type": "file"}, sort_keys=True)


@pytest.fixture()
def populated(bank):
    """Two 'file' documents to erase, one 'url' document that must survive."""
    keep = _approved(bank, source_ref=_OTHER_SOURCE, title="Keep me", source_type="url")
    a = _approved(
        bank, source_ref="file:///docs/q3.pdf", title="Q3 Financials Acme",
        source_type="file",
    )
    b = _approved(
        bank, source_ref="file:///docs/board.docx", title="Board minutes",
        source_type="file",
    )
    return bank, {"keep": keep, "targets": {a, b}}


# ---------------------------------------------------------------------------
# The rehearsal.
# ---------------------------------------------------------------------------


def test_a_rehearsal_mutates_nothing(populated) -> None:
    bank, _ = populated
    before = _rows(bank)

    shim = _Shim(bank)
    result = shim.rehearse(_SELECTOR)

    assert result.affected_count == 2
    assert _rows(bank) == before, (
        "the rehearsal changed the store. A dry run that mutates is not a dry run."
    )


def test_the_rehearsal_toggle_would_SEE_a_mutation(populated) -> None:
    """Toggle. Without it, `_rows` could be measuring something that never moves."""
    bank, ids = populated
    before = _rows(bank)
    bank.delete_docs([next(iter(ids["targets"]))])
    assert _rows(bank) != before


def test_titles_never_reach_the_consent_summary(populated) -> None:
    """The operator's content stays inside the application.

    ``consent_summary`` is what crosses to the operating system's consent
    dialog; ``detail`` is what the app shows.
    """
    bank, _ = populated
    result = _Shim(bank).rehearse(_SELECTOR)

    assert "Q3 Financials Acme" not in result.consent_summary
    assert "Board minutes" not in result.consent_summary
    assert result.consent_summary.startswith("Would erase 2 documents")
    assert any("Q3 Financials Acme" in d for d in result.detail), (
        "the titles are missing from detail, so the operator is being asked to "
        "approve an erasure he cannot see the contents of"
    )


def test_an_oversized_match_set_REFUSES_and_is_never_truncated(populated, monkeypatch) -> None:
    bank, _ = populated
    monkeypatch.setattr(tools, "CURATE_KNOWLEDGE_MAX_MATCHES", 1)
    with pytest.raises(RuntimeError, match="over the"):
        _Shim(bank).rehearse(_SELECTOR)


def test_under_the_cap_still_rehearses(populated, monkeypatch) -> None:
    """Toggle for the cap: the refusal above comes from the cap, not a dead path."""
    bank, _ = populated
    monkeypatch.setattr(tools, "CURATE_KNOWLEDGE_MAX_MATCHES", 2)
    assert _Shim(bank).rehearse(_SELECTOR).affected_count == 2


# ---------------------------------------------------------------------------
# The selector.
# ---------------------------------------------------------------------------


def test_an_empty_selector_matches_NOTHING_not_everything(populated) -> None:
    """Deny-by-default applied to a selector, checked at the bank itself."""
    bank, _ = populated
    assert bank.select_docs_for_curation() == []
    assert bank.select_docs_for_curation(source_ref="", source_type="") == []


def test_a_constrained_selector_does_match(populated) -> None:
    """Toggle: the emptiness above is the absence of predicates, not a dead query."""
    bank, _ = populated
    assert len(bank.select_docs_for_curation(source_type="file")) == 2


def test_a_rehearsal_with_no_selector_refuses(bank) -> None:
    with pytest.raises(RuntimeError, match="no selector"):
        _Shim(bank).rehearse(json.dumps({"action": "delete"}))


# ---------------------------------------------------------------------------
# The execution.
# ---------------------------------------------------------------------------


def test_an_approved_execution_erases_EXACTLY_the_rehearsed_set(populated) -> None:
    bank, ids = populated
    shim = _Shim(bank)
    shim.rehearse(_SELECTOR)

    message = shim.run(_SELECTOR)

    assert "Erased 2 documents" in message
    survivors = {
        row[0]
        for row in bank._conn.execute("SELECT doc_uuid FROM knowledge_docs").fetchall()
    }
    assert survivors == {ids["keep"]}, (
        "the execution erased a different set than the one rehearsed"
    )


def test_an_erase_WITHOUT_a_rehearsal_fails_closed(populated) -> None:
    """The shape that matters most: an erase must not reach the bank unrehearsed."""
    bank, _ = populated
    before = _rows(bank)

    message = _Shim(bank).run(_SELECTOR)

    assert "refused" in message.lower()
    assert "Nothing was erased" in message
    assert _rows(bank) == before


def test_a_rehearsal_is_SINGLE_USE(populated) -> None:
    """An approval cannot be replayed against a later request."""
    bank, _ = populated
    shim = _Shim(bank)
    shim.rehearse(_SELECTOR)
    shim.run(_SELECTOR)

    second = shim.run(_SELECTOR)
    assert "refused" in second.lower()


def test_a_set_that_CHANGED_between_rehearsal_and_approval_fails_closed(populated) -> None:
    """The file system -- or here the bank -- can move underneath an approval.

    The operator approved a SET, not a query, so a set that no longer matches
    is refused rather than reinterpreted (#1567 design point 6).
    """
    bank, _ = populated
    shim = _Shim(bank)
    shim.rehearse(_SELECTOR)

    # A third 'file' document arrives after the rehearsal.
    _approved(
        bank, source_ref="file:///docs/late.pdf", title="Arrived late",
        source_type="file",
    )
    before = _rows(bank)

    message = shim.run(_SELECTOR)

    assert "changed" in message.lower()
    assert "Nothing was erased" in message
    assert _rows(bank) == before, "a changed set was erased anyway"


def test_the_rehearsed_set_matching_is_what_ALLOWS_it(populated) -> None:
    """Toggle for the check above: an unchanged set does proceed."""
    bank, _ = populated
    shim = _Shim(bank)
    shim.rehearse(_SELECTOR)
    assert "Erased 2 documents" in shim.run(_SELECTOR)


def test_an_absent_bank_refuses(monkeypatch) -> None:
    assert _Shim(None).run(_SELECTOR) == tools.CURATE_KNOWLEDGE_UNAVAILABLE_NOTICE
    with pytest.raises(RuntimeError, match="not available"):
        _Shim(None).rehearse(_SELECTOR)


# ---------------------------------------------------------------------------
# Which actions rehearse.
# ---------------------------------------------------------------------------


def test_delete_always_rehearses_and_mark_saved_does_not() -> None:
    assert tools.curate_action_needs_rehearsal('{"action": "delete"}') is True
    assert tools.curate_action_needs_rehearsal('{"action": "mark_saved"}') is False


@pytest.mark.parametrize("junk", ["", "not json", "[]", '{"action": null}'])
def test_unreadable_arguments_are_rehearsed_not_executed(junk: str) -> None:
    """Fail-closed: arguments nobody can read are not executed on a guess."""
    assert tools.curate_action_needs_rehearsal(junk) is True


# ---------------------------------------------------------------------------
# Dormancy.
# ---------------------------------------------------------------------------


def test_the_tool_is_dormant_until_a_runner_is_registered() -> None:
    """With no runner the registry body reaches no store at all."""
    tools.clear_curate_knowledge_runner()
    assert tools.execute("curate_knowledge", _SELECTOR) == (
        tools.CURATE_KNOWLEDGE_UNAVAILABLE_NOTICE
    )


def test_the_shipped_config_has_curation_disabled() -> None:
    import tomllib
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    cfg = tomllib.loads(
        (repo / "services" / "assistant_orchestrator" / "config" / "default.toml")
        .read_text(encoding="utf-8")
    )
    assert cfg["curate_knowledge"]["enabled"] is False, (
        "curate_knowledge is LIVE in the shipped config. Erasure is irreversible "
        "— flipping it is an LA-present ceremony, not a commit."
    )


def test_curate_knowledge_is_DANGEROUS_by_declaration_not_by_fallback() -> None:
    """risk_tier would reach DANGEROUS via its fallback too. A control that is
    right by accident is the defect class this sprint spent itself on."""
    assert "curate_knowledge" in tools._TOOL_RISK_TIER
    assert tools.risk_tier("curate_knowledge") is tools.RiskTier.DANGEROUS


# ---------------------------------------------------------------------------
# Controls that survived mutation with nothing red — they had no lock at all.
# ---------------------------------------------------------------------------


def test_the_SELECTOR_IDENTITY_comparison_is_what_refuses_a_swap(populated) -> None:
    """Rehearse one selector, execute a DIFFERENT one that matches THE SAME SET.

    The two selectors must agree on the match set, or this test cannot tell its
    own control from the set comparison below it. The first version used
    selectors matching 2 and 3 documents, so the SET check refused the swap and
    the test passed with the identity check deleted -- verified by the
    verification review, which ran that exact mutation and saw 105 green.

    Both refusal messages contain "refused" and "Nothing was erased", so the
    assertion is on the DISTINGUISHING clause.
    """
    bank, ids = populated
    shim = _Shim(bank)
    shim.rehearse(_SELECTOR)

    # Same two 'file' documents, different selector text.
    same_set = json.dumps(
        {"action": "delete", "source_type": "file", "created_after": "2000-01-01"},
        sort_keys=True,
    )
    assert [c.doc_uuid for c in bank.select_docs_for_curation(source_type="file")] == [
        c.doc_uuid
        for c in bank.select_docs_for_curation(
            source_type="file", created_after="2000-01-01"
        )
    ], "the two selectors no longer agree on the match set; this test is vacuous"

    message = shim.run(same_set)

    assert "could not match this to the rehearsal" in message, (
        f"refused for the wrong reason: {message!r}. With the identity check "
        "gone the set check would let this through, because the sets agree."
    )
    assert _rows(bank)[0] == 3, "documents were erased on a swapped selector"


def test_the_PARSE_BOUNDARY_is_what_the_registry_body_calls(monkeypatch) -> None:
    """Deleting `parse_curate_args` from `_curate_knowledge` left every suite
    green. The body must validate before the runner is ever reached."""
    seen: list[str] = []
    tools.register_curate_knowledge_runner(lambda args: seen.append(args) or "ok")
    try:
        # No selector -> the runner must NOT be called.
        out = tools.execute("curate_knowledge", '{"action": "delete"}')
        assert seen == [], "the runner was called with an unvalidated request"
        assert out == tools.CURATE_KNOWLEDGE_NO_SELECTOR_NOTICE
        # A valid one -> it is, and with the NORMALISED selector.
        tools.execute("curate_knowledge", '{"action":"delete","source_type":"file"}')
        assert len(seen) == 1
        assert json.loads(seen[0]) == {"action": "delete", "source_type": "file"}
    finally:
        tools.clear_curate_knowledge_runner()


def test_applies_to_is_WIRED_not_merely_defined() -> None:
    """`curate_action_needs_rehearsal` had coverage; its wiring into
    `declares_dry_run` / `route_simulate_first` had none, and that wire is the
    only thing separating a rehearsed delete from an unrehearsed mark_saved."""
    from shared.governance import dry_run as _dry_run

    before = dict(_dry_run._DRY_RUNS)
    _dry_run._DRY_RUNS.clear()
    try:
        _dry_run.register_dry_run(
            "curate_knowledge",
            lambda args: _dry_run.DryRunResult(
                action="erase", unit="documents", affected_count=1
            ),
            applies_to=tools.curate_action_needs_rehearsal,
        )
        delete = '{"action": "delete"}'
        saved = '{"action": "mark_saved"}'

        assert tools.declares_dry_run("curate_knowledge", delete) is True
        assert tools.declares_dry_run("curate_knowledge", saved) is False
        assert tools.route_simulate_first(
            "curate_knowledge", enabled=True, tool_args=delete
        ) == tools.SIMULATE_FIRST
        assert tools.route_simulate_first(
            "curate_knowledge", enabled=True, tool_args=saved
        ) is None
    finally:
        _dry_run._DRY_RUNS.clear()
        _dry_run._DRY_RUNS.update(before)


def test_a_predicate_that_RAISES_means_rehearse_not_execute() -> None:
    """The fail-closed guarantee the module states in bold. Flipping its except
    arm from True to False left every suite green."""
    from shared.governance import dry_run as _dry_run

    def _boom(_args: str) -> bool:
        raise RuntimeError("cannot decide")

    before = dict(_dry_run._DRY_RUNS)
    _dry_run._DRY_RUNS.clear()
    try:
        _dry_run.register_dry_run(
            "t",
            lambda a: _dry_run.DryRunResult(
                action="erase", unit="documents", affected_count=1
            ),
            applies_to=_boom,
        )
        assert _dry_run.declares_dry_run("t", "anything") is True, (
            "a tool that declared a rehearsal and could not decide whether it "
            "applies must be REHEARSED, not executed"
        )
    finally:
        _dry_run._DRY_RUNS.clear()
        _dry_run._DRY_RUNS.update(before)


# ---------------------------------------------------------------------------
# The date selectors — a fail-open that returned the whole bank.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "stamp", ["9999-99-99", "2026-13-45", "2026-99-01", "0000-00-00", "2026-02-30"]
)
def test_a_date_that_is_not_a_DATE_is_refused(stamp: str) -> None:
    """`9999-99-99` passed the old regex and sorts above every real timestamp,
    so `created_before` with it selected the ENTIRE approved bank."""
    assert tools.parse_curate_args(
        json.dumps({"action": "delete", "created_before": stamp})
    ) == {}


@pytest.mark.parametrize("stamp", ["2026-06-01", "2026-06-01T12:30", "2026-06-01T12:30:05"])
def test_a_real_date_IS_accepted(stamp: str) -> None:
    """Toggle: the refusals above are calendar validity, not a dead branch."""
    assert tools.parse_curate_args(
        json.dumps({"action": "delete", "created_before": stamp})
    )


def test_the_SPACE_separator_is_refused_because_it_inverts_the_comparison() -> None:
    """Stored timestamps are `2026-09-21T03:16:23+00:00`. `' '` (0x20) sorts
    BELOW `'T'` (0x54), so the two spellings of one instant produced opposite
    match sets. One spelling, one meaning."""
    assert tools.parse_curate_args(
        json.dumps({"action": "delete", "created_before": "2026-06-01 12:30"})
    ) == {}


def test_the_date_selectors_actually_select(populated) -> None:
    """They had NO coverage, and the commit claimed the tests drove them."""
    bank, _ = populated
    assert len(bank.select_docs_for_curation(created_after="2000-01-01")) == 3
    assert len(bank.select_docs_for_curation(created_before="2000-01-01")) == 0
