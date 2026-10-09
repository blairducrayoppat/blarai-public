"""Gate: the dry-run executor refuses, and a rehearsal cannot smuggle content
to the operating system's consent surface (#1548 executor).

Two properties, and the second is the one that needed a redesign to be true.

1. **Refusal.** A tool with no registered rehearsal is not executed in its
   place. Every failure inside a rehearsal raises rather than returning, so a
   caller cannot read a failure as a result and proceed.

2. **The boundary.** ``DryRunResult.consent_summary`` is the one string that
   crosses to the OS consent dialog, outside BlarAI's encrypted boundary. The
   first design constrained it with a character allowlist and claimed titles
   could not fit the shape. ``Q3 Financials Acme Corp.pdf`` fits any such shape.
   The class now RENDERS the summary from typed fields, so there is no parameter
   through which free text can reach it — which is a property that can be tested
   by construction rather than by trying to recognise content.
"""

from __future__ import annotations

import datetime as _dt

import pytest

from shared.governance.dry_run import (
    ACTIONS,
    QUALIFIERS,
    UNITS,
    DryRunError,
    DryRunResult,
    Qualifier,
    clear_dry_runs,
    declares_dry_run,
    execute_dry_run,
    register_dry_run,
    registered_dry_runs,
)

_A_REAL_TITLE = "Q3 Financials Acme Corp.pdf"


@pytest.fixture(autouse=True)
def _empty_registry():
    clear_dry_runs()
    yield
    clear_dry_runs()


def _result(**overrides) -> DryRunResult:
    kwargs = {"action": "erase", "unit": "documents", "affected_count": 23}
    kwargs.update(overrides)
    return DryRunResult(**kwargs)


# ---------------------------------------------------------------------------
# 1. Refusal.
# ---------------------------------------------------------------------------


def test_an_unregistered_tool_cannot_be_rehearsed() -> None:
    with pytest.raises(DryRunError, match="no dry run registered"):
        execute_dry_run("curate_knowledge", '{"query": "x"}')


def test_declares_dry_run_is_deny_by_default() -> None:
    assert declares_dry_run("curate_knowledge") is False
    assert declares_dry_run("") is False
    assert declares_dry_run("a tool that has never existed") is False


def test_a_rehearsal_that_raises_is_a_REFUSAL_not_a_result() -> None:
    """The shape that matters: a caller must not be able to treat a failed
    rehearsal as a successful one and fall through to the real execution."""
    def _boom(args: str) -> DryRunResult:
        raise RuntimeError("the bank was unreachable")

    register_dry_run("curate_knowledge", _boom)
    with pytest.raises(DryRunError, match="failed"):
        execute_dry_run("curate_knowledge", "{}")


def test_a_rehearsal_returning_the_wrong_shape_is_a_REFUSAL() -> None:
    register_dry_run("curate_knowledge", lambda args: "23 documents would go")
    with pytest.raises(DryRunError, match="not a DryRunResult"):
        execute_dry_run("curate_knowledge", "{}")


def test_a_declaration_without_an_implementation_is_impossible() -> None:
    """#1548's hand-maintained frozenset allowed a name with no rehearsal behind
    it. Registration is the declaration now, so that state cannot be reached."""
    with pytest.raises(TypeError, match="not callable"):
        register_dry_run("curate_knowledge", "yes I can rehearse")  # type: ignore[arg-type]
    assert declares_dry_run("curate_knowledge") is False


def test_a_registered_rehearsal_runs_and_is_declared() -> None:
    """The other half: a lock that refuses everything proves nothing."""
    register_dry_run("curate_knowledge", lambda args: _result())
    assert declares_dry_run("curate_knowledge") is True
    assert registered_dry_runs() == frozenset({"curate_knowledge"})
    assert execute_dry_run("curate_knowledge", "{}").affected_count == 23


# ---------------------------------------------------------------------------
# 2. The boundary.
# ---------------------------------------------------------------------------


def test_the_consent_summary_is_RENDERED_not_supplied() -> None:
    """There is no constructor parameter named consent_summary at all."""
    with pytest.raises(TypeError):
        DryRunResult(  # type: ignore[call-arg]
            action="erase",
            unit="documents",
            affected_count=1,
            consent_summary=f"would erase {_A_REAL_TITLE}",
        )


def test_a_document_title_cannot_reach_the_consent_summary() -> None:
    """The property the first design claimed and did not have.

    A plain-ASCII title passes any character allowlist. It cannot pass this one
    because there is nowhere to put it.
    """
    result = _result(detail=(_A_REAL_TITLE, "Board minutes.docx"))
    assert _A_REAL_TITLE not in result.consent_summary
    assert result.consent_summary == "Would erase 23 documents"


def test_detail_DOES_carry_content_and_is_not_constrained() -> None:
    """The other side of the split: detail is meant to hold titles, in-app."""
    result = _result(detail=(_A_REAL_TITLE, "Notes — private.md", "中文.txt"))
    assert _A_REAL_TITLE in result.detail
    assert len(result.detail) == 3


@pytest.mark.parametrize("bad_action", ["delete everything", "erase ", "ERASE", ""])
def test_the_action_vocabulary_is_closed(bad_action: str) -> None:
    with pytest.raises(ValueError, match="action"):
        _result(action=bad_action)


@pytest.mark.parametrize("bad_unit", ["Q3 Financials", "documents ", "rows", ""])
def test_the_unit_vocabulary_is_closed(bad_unit: str) -> None:
    with pytest.raises(ValueError, match="unit"):
        _result(unit=bad_unit)


def test_a_qualifier_cannot_carry_a_string() -> None:
    """Qualifiers are the only extensible part, so they take int or date only —
    otherwise they would be the smuggling channel the rest of this prevents."""
    with pytest.raises(ValueError, match="only int and date"):
        Qualifier("sources", _A_REAL_TITLE)  # type: ignore[arg-type]


def test_a_qualifier_label_is_from_the_fixed_vocabulary() -> None:
    with pytest.raises(ValueError, match="not one of"):
        Qualifier("title of the first match", 1)


def test_a_bool_is_not_accepted_as_a_number() -> None:
    """bool is an int subclass; unguarded it renders as 'True'."""
    with pytest.raises(ValueError):
        Qualifier("sources", True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="affected_count"):
        _result(affected_count=True)


def test_qualifiers_must_be_Qualifier_instances() -> None:
    """A bare tuple would sidestep the vocabulary check entirely."""
    with pytest.raises(ValueError, match="Qualifier instances"):
        _result(qualifiers=(("sources", _A_REAL_TITLE),))  # type: ignore[arg-type]


def test_a_full_summary_renders_within_the_dialog_s_means() -> None:
    result = _result(
        affected_count=23,
        qualifiers=(
            Qualifier("sources", 4),
            Qualifier("oldest", _dt.date(2024, 1, 5)),
            Qualifier("newest", _dt.date(2026, 6, 30)),
        ),
        detail=(_A_REAL_TITLE,),
    )
    assert result.consent_summary == (
        "Would erase 23 documents (sources 4, oldest 2024-01-05, newest 2026-06-30)"
    )
    assert _A_REAL_TITLE not in result.consent_summary


def test_every_vocabulary_term_renders_without_leaking_its_own_shape() -> None:
    """A sweep, so a term added later cannot introduce free text by the back
    door — every one must render into the fixed sentence."""
    for action in sorted(ACTIONS):
        for unit in sorted(UNITS):
            summary = DryRunResult(
                action=action, unit=unit, affected_count=0
            ).consent_summary
            assert summary == f"Would {action} 0 {unit}"
    for label in sorted(QUALIFIERS):
        assert Qualifier(label, 1).render() == f"{label} 1"


def test_affected_count_cannot_be_negative() -> None:
    with pytest.raises(ValueError, match="negative"):
        _result(affected_count=-1)
