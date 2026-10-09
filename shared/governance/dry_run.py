"""The dry-run executor: what a rehearsal IS, and what may leave with it (#1548).

#1548 shipped simulate-first as a fourth route outcome and deliberately shipped
NO execution machinery, so reaching the outcome refuses. This module is that
machinery. A tool that declares a dry run provides a function here; a tool that
does not cannot be routed, and a tool routed with nothing registered is REFUSED
rather than executed.

DECLARING AND PROVIDING ARE THE SAME ACT, and that is the point. #1548 kept the
declaring set as a hand-maintained frozenset separate from any implementation,
so a name could sit in it with no rehearsal behind it, and the only thing
between that and a real execution was the tool loop noticing. Here the registry
IS the declaration: :func:`declares_dry_run` reads what is registered, so a tool
cannot claim a rehearsal it cannot perform.

THE BOUNDARY THIS MODULE EXISTS TO HOLD
---------------------------------------
A rehearsal's value is showing the operator the EFFECT before it happens --
"23 documents would be erased" -- and that effect is computed from his own
content. But the approval prompt is rendered by the OPERATING SYSTEM's consent
surface, outside BlarAI's encrypted boundary, and
``EscalationContext.from_pa_verdict`` is written so "this path cannot carry a
secret to the operator surface": it takes labels and summaries, never raw
arguments or payload.

So a rehearsal's two halves are separated STRUCTURALLY:

    the consent summary   Rendered by THIS module from typed fields. A tool
                          supplies a count, a unit and an action drawn from
                          fixed vocabularies, plus optional integer or date
                          qualifiers. It never supplies free text, so it cannot
                          put a document title in the field that crosses.
    ``detail``            The full match set, titles and all. Rendered inside
                          the application, within the trust boundary. Never
                          passed to the consent path.

**A character allowlist was the first design and it was wrong.** The claim was
that the summary's shape is one titles do not fit; but ``Q3 Financials Acme
Corp.pdf`` is plain ASCII, passes any reasonable character class, and is exactly
the content the rule exists to keep out. No pattern separates a title from a
summary, because a title is arbitrary text. The only enforceable answer is to
stop accepting text at all (``security_by_design`` 4, structural absence over
configuration; 2, allowlists over blocklists; 8, least data across boundaries).

WHAT A DRY RUN MUST NOT DO. Mutate anything. That is not assertable here -- this
module cannot know what a given tool touches -- so it is the registering tool's
obligation, locked by that tool's own regression test driving the real store and
asserting the row count and chain head are unchanged. :func:`execute_dry_run`
claims nothing about side effects; it guarantees only that a tool with no
registered rehearsal never reaches execution in its place.
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Final

__all__ = [
    "ACTIONS",
    "QUALIFIERS",
    "UNITS",
    "DryRunError",
    "DryRunResult",
    "Qualifier",
    "clear_dry_runs",
    "declares_dry_run",
    "execute_dry_run",
    "register_dry_run",
    "registered_dry_runs",
]


class DryRunError(RuntimeError):
    """A rehearsal was requested for a tool that cannot perform one.

    Raised rather than returned so no caller can mistake it for a result. The
    tool loop treats it as a refusal -- an action reported as rehearsed and in
    fact executed is the inversion simulate-first exists to prevent.
    """


#: What a rehearsed action would DO. BlarAI's vocabulary, not the operator's
#: content, so a tool selects rather than writes.
ACTIONS: Final[frozenset[str]] = frozenset({
    "erase", "move", "mark as saved", "unmark as saved", "re-file",
})

#: What it would do it TO. Plural nouns; the renderer handles agreement.
UNITS: Final[frozenset[str]] = frozenset({
    "documents", "files", "images", "preferences", "knowledge entries",
})

#: Extra facts a rehearsal may state. Each carries an integer or a date --
#: never a string -- so a qualifier cannot become a smuggling channel.
QUALIFIERS: Final[frozenset[str]] = frozenset({
    "sources", "oldest", "newest", "total size in MB", "folders",
})


@dataclass(frozen=True, slots=True)
class Qualifier:
    """One extra fact, with a value that cannot carry text.

    Raises:
        ValueError: On a label outside :data:`QUALIFIERS`, or a value that is
            neither an ``int`` nor a ``date``. ``bool`` is rejected explicitly:
            it is an ``int`` subclass and would render as "True".
    """

    label: str
    value: int | _dt.date

    def __post_init__(self) -> None:
        if self.label not in QUALIFIERS:
            raise ValueError(
                f"qualifier {self.label!r} is not one of {sorted(QUALIFIERS)}. "
                "This field crosses to the operating system's consent surface, "
                "so its vocabulary is fixed rather than open."
            )
        # EXACT types, not isinstance. A subclass of int or date supplies its
        # own __str__/__format__, and that is attacker-chosen text rendered
        # straight into the field that crosses to the OS dialog. The first
        # version reasoned about exactly this hazard for bool -- "it is an int
        # subclass and would render as True" -- and handled one instance of it
        # instead of the class.
        if type(self.value) not in (int, _dt.date):
            # TRY004 would have this be a TypeError. ONE exception type for one
            # concept is the safer contract on a boundary a caller must handle
            # fail-closed: every violation of this class's rules -- vocabulary or
            # type -- raises ValueError, so a caller cannot guard one and miss
            # the other.
            raise ValueError(
                f"qualifier {self.label!r} has value of type "
                f"{type(self.value).__name__}; only int and date may cross"
            )

    def render(self) -> str:
        value = (
            self.value.isoformat()
            if isinstance(self.value, _dt.date)
            else str(self.value)
        )
        return f"{self.label} {value}"


@dataclass(frozen=True, slots=True)
class DryRunResult:
    """What a rehearsal found, split by which side of the boundary it may cross.

    Args:
        action: What the real execution would do. Must be in :data:`ACTIONS`.
        unit: What it would act on. Must be in :data:`UNITS`.
        affected_count: How many items. Carried as an integer so a caller can
            refuse an oversized set without parsing prose.
        qualifiers: Optional extra facts, each integer- or date-valued.
        detail: The full match set, including the operator's own content. Stays
            inside the application; never reaches the consent path.

    Raises:
        ValueError: On a vocabulary or type violation.
    """

    action: str
    unit: str
    affected_count: int
    qualifiers: tuple[Qualifier, ...] = field(default_factory=tuple)
    detail: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.action not in ACTIONS:
            raise ValueError(
                f"action {self.action!r} is not one of {sorted(ACTIONS)}"
            )
        if self.unit not in UNITS:
            raise ValueError(f"unit {self.unit!r} is not one of {sorted(UNITS)}")
        if type(self.affected_count) is not int:
            raise ValueError(
                "affected_count must be exactly an int; an int SUBCLASS can "
                "render arbitrary text into the consent summary"
            )
        if self.affected_count < 0:
            raise ValueError("affected_count cannot be negative")
        for qualifier in self.qualifiers:
            if type(qualifier) is not Qualifier:
                raise ValueError(
                    "qualifiers must be Qualifier instances; a bare tuple or "
                    "string would bypass this type's vocabulary check"
                )

    @property
    def consent_summary(self) -> str:
        """The ONE string that crosses to the operating system's consent surface.

        Rendered here from typed fields. There is no parameter anywhere on this
        class through which a caller could place free text into it, which is the
        property the whole design rests on -- not a filter that tries to
        recognise content after the fact.
        """
        # RE-VALIDATED at render time, not only at construction. `frozen=True`
        # stops assignment but not `object.__setattr__`, which reached straight
        # past __post_init__ and put a document title into `action`. Checking
        # here means the field that crosses is checked at the moment it is
        # built, whatever happened to the instance in between.
        if self.action not in ACTIONS or self.unit not in UNITS:
            raise ValueError(
                "this result's action or unit is no longer from the closed "
                "vocabulary; it was altered after construction and will not be "
                "rendered"
            )
        if type(self.affected_count) is not int:
            raise ValueError("affected_count is no longer exactly an int")
        # QUALIFIERS TOO -- the field this method actually RENDERS, and the one
        # the first re-validation skipped. `object.__setattr__` reached straight
        # past it three ways: overwriting a Qualifier's value, overwriting its
        # label, and substituting a non-Qualifier that merely has `.render()`.
        # Each check is re-run rather than trusted from construction.
        for qualifier in self.qualifiers:
            if type(qualifier) is not Qualifier:
                raise ValueError(
                    "a qualifier is no longer a Qualifier; it was substituted "
                    "after construction and will not be rendered"
                )
            if qualifier.label not in QUALIFIERS or type(qualifier.value) not in (
                int,
                _dt.date,
            ):
                raise ValueError(
                    f"qualifier {qualifier.label!r} was altered after "
                    "construction and will not be rendered"
                )
        summary = f"Would {self.action} {self.affected_count} {self.unit}"
        if self.qualifiers:
            summary += " (" + ", ".join(q.render() for q in self.qualifiers) + ")"
        return summary


@dataclass(frozen=True, slots=True)
class _Registration:
    """A rehearsal, and when it applies."""

    rehearse: Callable[[str], DryRunResult]
    applies_to: Callable[[str], bool]


#: tool name -> its registration. Registration IS declaration.
_DRY_RUNS: dict[str, _Registration] = {}


def register_dry_run(
    tool_name: str,
    rehearse: Callable[[str], DryRunResult],
    applies_to: Callable[[str], bool] | None = None,
) -> None:
    """Declare that ``tool_name`` can be rehearsed, by providing the rehearsal.

    Args:
        tool_name: The tool.
        rehearse: Computes what the real execution would do.
        applies_to: Optional predicate over the tool's argument string, for a
            tool whose actions differ in kind. ``curate_knowledge`` needs it:
            its ``delete`` is irreversible and must always be rehearsed, while
            its ``mark_saved`` is reversible and routes normally. Without this
            the choice would be per-TOOL, so making the destructive action safe
            would put a rehearsal prompt in front of a harmless one -- and an
            approval prompt that appears when nothing is at stake is how an
            operator learns to approve without reading.

            **Fail-closed**: a predicate that raises is treated as "applies",
            because the safe answer to "should this be rehearsed?" is yes.

    Raises:
        TypeError: If ``rehearse`` or ``applies_to`` is not callable -- a
            declaration without an implementation is the divergence this
            registry exists to prevent.
        ValueError: On an empty tool name.
    """
    if not tool_name:
        raise ValueError("tool_name is required")
    if not callable(rehearse):
        raise TypeError(
            f"dry run for {tool_name!r} is not callable; a declaration without "
            "an implementation is what this registry exists to make impossible"
        )
    if applies_to is not None and not callable(applies_to):
        raise TypeError(f"applies_to for {tool_name!r} is not callable")
    _DRY_RUNS[tool_name] = _Registration(
        rehearse=rehearse,
        applies_to=applies_to if applies_to is not None else (lambda _args: True),
    )


def clear_dry_runs() -> None:
    """Empty the registry. For tests; production registers at startup."""
    _DRY_RUNS.clear()


def registered_dry_runs() -> frozenset[str]:
    """The tools that can currently be rehearsed."""
    return frozenset(_DRY_RUNS)


def declares_dry_run(tool_name: str, tool_args: str = "") -> bool:
    """True iff ``tool_name`` has a rehearsal that applies to ``tool_args``.

    Deny-by-default: an unknown tool, or a known tool with nothing registered,
    is False.

    Fail-closed the other way round once a rehearsal EXISTS: if the registered
    ``applies_to`` predicate raises, the answer is True. A tool that declared a
    rehearsal and then could not decide whether it applies is rehearsed, not
    executed.
    """
    registration = _DRY_RUNS.get(tool_name)
    if registration is None:
        return False
    try:
        return bool(registration.applies_to(tool_args))
    except Exception:  # noqa: BLE001 - the safe answer to "rehearse?" is yes
        return True


def execute_dry_run(tool_name: str, args: str = "") -> DryRunResult:
    """Rehearse ``tool_name`` and return what the real execution would do.

    Raises:
        DryRunError: If the tool has no registered rehearsal, if the rehearsal
            raises, or if it returns something that is not a
            :class:`DryRunResult`. Every failure path raises, so a caller cannot
            read a failed rehearsal as a successful one and proceed.
    """
    registration = _DRY_RUNS.get(tool_name)
    if registration is None:
        raise DryRunError(
            f"no dry run registered for {tool_name!r}; it cannot be rehearsed, "
            "and an action that cannot be rehearsed is not executed in its place"
        )
    try:
        result = registration.rehearse(args)
    except Exception as exc:  # every failure path is a refusal, by design
        raise DryRunError(f"dry run for {tool_name!r} failed: {exc}") from exc
    # EXACT type. `isinstance` accepted a SUBCLASS that overrode
    # `consent_summary` with arbitrary text -- the one field that crosses to
    # the OS consent surface. A rehearsal must be the shape this module
    # defines, not something that merely passes for it.
    if type(result) is not DryRunResult:
        raise DryRunError(
            f"dry run for {tool_name!r} returned {type(result).__name__}, not a "
            "DryRunResult; a rehearsal whose shape is unknown -- or merely "
            "subclasses the known one -- cannot be shown to the operator as one"
        )
    return result
