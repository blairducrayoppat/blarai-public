"""An instruction that tells the operator what to type must survive the real parser.

WHAT THIS CLOSES. Three times now, the same defect has reached the operator's hands:

    #1116  a reply arrived in a state that could not consume it, and the usage nag
           threw away the words he had typed.
    #1126  he pasted a numbered answer as "/dispatch\\n1. In a web browser…" — the most
           ordinary way to format one — and ``startswith("/dispatch ")`` was False, so the
           parser returned None, the message went to the ORDINARY CHAT PATH, and the
           assistant burbled about /imagine while a question sat waiting for that text.
    #1406  he answered the intake interview with no prefix at all. Same chat path, same
           silence: the model called ``generate_image`` three times and emitted no prose.
           He got an empty bubble. His verdict was one word.

CLAUDE.md requires a structural control at the third instance, and the honest control is
not "did someone remember the rule". It is this: **take the literal the operator is told
to send, and drive it through the parser that has to accept it.** ``parse_dispatch_command
("2")`` is ``None`` — so an instruction saying *"Reply with the number (e.g. `2`)"* is a
shipped invitation to reproduce the defect, however plainly it is written. That exact line
was live in :meth:`_render_clarifying_question` when this file was written, together with
three prose siblings, and is corrected in the same change.

THE ORACLE, and why it is clause-shaped. A per-LINE substring test ("the line mentions
/dispatch somewhere") passes the worst string on the surface, because *"Reply with the
number (e.g. `2`), or `/dispatch reject` to cancel"* does mention it — in the other half of
the sentence. A per-SENTENCE test has the same hole. So each string is split into clauses,
and a clause that OPENS with an imperative send-verb must itself carry a literal the
parser accepts. The em-dash is deliberately not a clause boundary: *"Answer in your own
words — reply `/dispatch <your answers>`"* is one instruction, and splitting it would
convict the correct form.

WHAT IT DOES NOT CLAIM. This reads shipped instruction STRINGS. It cannot see an
instruction the operator infers from a layout, one rendered by the WinUI, or one a model
composes at runtime. It also cannot judge whether an instruction is *good* — only whether
following it literally reaches the corridor at all. The verb set is deliberately narrow
(a wider one convicts ordinary prose like "say 'web page' in your answer", which is not a
command instruction), so a novel phrasing can still slip past. What it makes impossible is
the specific shape that has now recurred three times: a literal, printed as the thing to
send, that the parser refuses.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from services.ui_gateway.src.dispatch_coordinator import parse_dispatch_command

_REPO = Path(__file__).resolve().parents[2]

#: The surface this control governs: the /dispatch corridor, where all three instances of
#: the class occurred. A (module, parser) row — adding another command family is one row,
#: not a rewrite.
_SURFACES: tuple[tuple[Path, object], ...] = (
    (
        _REPO / "services" / "ui_gateway" / "src" / "dispatch_coordinator.py",
        parse_dispatch_command,
    ),
)

#: A clause that OPENS with one of these, and then says something, is telling the operator
#: to send something. Narrow on purpose — see the module docstring. "say" is excluded
#: because it introduces content advice ("say 'web page' in your answer"), not a command
#: to type, and a control that cries wolf gets an exemption list instead of a fix.
#:
#: The trailing ``\S`` is load-bearing rather than tidy: the parser's own dispatch table
#: contains the bare literals ``"answer"`` and ``"answer "`` (:func:`parse_dispatch_command`),
#: and a verb with nothing after it is a ``kind`` value, not a sentence addressed to a human.
_INSTRUCTION = re.compile(
    r"^\s*(?:or\s+|and\s+)?(reply|answer|respond|send|type|tell)\b\s+\S", re.I
)

#: Clause boundaries. Two deliberate exclusions, each protecting a shipped correct form:
#:
#: * the EM-DASH, which joins an instruction to its literal — *"Answer in your own words —
#:   reply `/dispatch <your answers>`"* is one instruction, and splitting it would convict
#:   the very phrasing this control exists to require;
#: * a full stop that is NOT a sentence end. A bare ``.`` shatters ``e.g.`` into ``e`` and
#:   ``g``, which silently defeats :func:`_merge_examples` below and convicts every
#:   instruction that names its literal by example. Only ``.`` before whitespace-and-a-
#:   capital, or at the very end, is treated as a boundary.
_CLAUSE_SPLIT = re.compile(r"[,;:()?\n]|\.(?=\s+[A-Z])|\.$")

#: A backtick-quoted literal — how this codebase presents anything the operator types.
_LITERAL = re.compile(r"`([^`\n]+)`")

#: The command verb written into prose rather than fenced. Typeable, so it counts.
_BARE_PREFIX = re.compile(r"(?<![\w/])/dispatch\b")


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """The id()s of every docstring constant, so prose ABOUT the code is never read as
    an instruction TO the operator. Without this the corpus is 92 literals of module
    paths and identifiers; with it, seven."""
    out: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)) or not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            out.add(id(first.value))
    return out


def instruction_clauses(path: Path) -> "list[tuple[int, str]]":
    """Every ``(lineno, clause)`` in *path* that tells the operator to send something."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip = _docstring_nodes(tree)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in skip:
            continue
        for clause in _merge_examples(_CLAUSE_SPLIT.split(node.value)):
            if _INSTRUCTION.match(clause):
                found.append((node.lineno, clause.strip()))
    return found


def _merge_examples(clauses: "list[str]") -> "list[str]":
    """Fold an ``e.g. …`` clause back into the instruction it illustrates.

    The corridor's idiom is *"Tell me what to change, e.g. `/dispatch revise do the export
    first`"* — one instruction whose literal sits after a comma. Convicting that would be
    a formatting complaint, so the example is merged.

    Only ``e.g.`` merges, and that narrowness is the point. *"Answer again with where it
    should run, `/dispatch forget my-site` if an earlier answer mentioned a phone"* has the
    same punctuation and is NOT the same thing: the literal there is a different action, so
    the first instruction still names nothing the operator can send. It stays convicted.
    """
    out: list[str] = []
    for clause in clauses:
        if out and clause.strip().lower().startswith(("e.g", "eg ", "for example")):
            out[-1] = f"{out[-1]}, {clause.strip()}"
        else:
            out.append(clause)
    return out


def clause_is_reachable(clause: str, parser) -> bool:
    """Does *clause* name something *parser* accepts?

    Two forms count, because the corridor ships both: a backtick-quoted literal the parser
    accepts, and a bare ``/dispatch`` written into the prose ("or reply /dispatch reject
    to cancel"). The second is less copyable but it is still typeable and still correct,
    and convicting it would turn this control into a formatting preference.

    An instruction with NEITHER fails: "reply with the option number" names no text at all,
    and the number by itself is precisely what the parser refuses.

    Note the scope — *clause*, never the whole line. "Reply with the number (e.g. `2`), or
    `/dispatch reject` to cancel" mentions ``/dispatch``, so a line-level version of this
    check certifies the exact string that caused the defect.
    """
    if _BARE_PREFIX.search(clause):
        return True
    return any(parser(lit) is not None for lit in _LITERAL.findall(clause))


@pytest.mark.parametrize("path,parser", _SURFACES, ids=lambda v: getattr(v, "name", ""))
def test_every_send_instruction_names_something_the_parser_accepts(path, parser):
    """The control."""
    offenders = [
        f"{path.name}:{lineno}  {clause!r}"
        for lineno, clause in instruction_clauses(path)
        if not clause_is_reachable(clause, parser)
    ]
    assert not offenders, (
        "these shipped instructions tell the operator to send something the parser "
        "refuses — following them lands the message in ordinary chat, which is #1116 / "
        "#1126 / #1406:\n  " + "\n  ".join(offenders)
        + "\n\nName the literal in the clause that says it: `/dispatch 2`, not "
        "\"reply with the option number\"."
    )


@pytest.mark.parametrize("path,parser", _SURFACES, ids=lambda v: getattr(v, "name", ""))
def test_the_corpus_is_not_empty_so_a_pass_means_something(path, parser):
    """Guards the vacuous shape. If the extractor ever returns nothing — a regex broken,
    the docstring filter over-reaching, the file renamed — every assertion above passes
    over an empty list and this control silently stops being one. Measured 2026-08-15:
    twenty-one instruction clauses on the dispatch corridor."""
    clauses = instruction_clauses(path)
    assert len(clauses) >= 15, (
        f"only {len(clauses)} send-instructions extracted from {path.name}; 21 were "
        f"measured on 2026-08-15. A collapsed corpus makes this gate vacuous — check "
        f"_INSTRUCTION and the docstring filter before lowering this floor."
    )


def test_the_shipped_bare_number_instruction_is_REFUSED():
    """The toggle, and it is not hypothetical: this is the string that was live in
    ``_render_clarifying_question`` when this control was written.

    It is the case a per-line substring oracle waves through — the sentence does contain
    ``/dispatch``, in its other half — so it also proves the clause split is doing real
    work rather than decorating the docstring.
    """
    pre_fix = "Reply with the number (e.g. `2`), or `/dispatch reject` to cancel."
    clauses = [c for c in _CLAUSE_SPLIT.split(pre_fix) if _INSTRUCTION.match(c)]
    assert clauses, "the fixture must contain a send-instruction clause"
    assert not any(clause_is_reachable(c, parse_dispatch_command) for c in clauses), (
        "the pre-fix instruction passed — this control cannot fail and is decoration"
    )
    assert "/dispatch" in pre_fix, (
        "and note WHY it must fail on a clause basis: the sentence does mention "
        "/dispatch, so a substring oracle would have certified it clean"
    )


def test_the_corrected_instruction_is_ACCEPTED():
    """Precision. A control that refused the fix would be reverted within a day."""
    fixed = (
        "Reply `/dispatch 2` with the number of the option you want, or "
        "`/dispatch reject` to cancel."
    )
    clauses = [c for c in _CLAUSE_SPLIT.split(fixed) if _INSTRUCTION.match(c)]
    assert clauses, "the fixture must contain a send-instruction clause"
    assert all(clause_is_reachable(c, parse_dispatch_command) for c in clauses)


def test_an_em_dash_instruction_is_not_split_apart():
    """Precision, for the specific over-reach that would make this control hated: the
    shipped correct form puts the verb and its literal either side of an em-dash."""
    good = "Answer in your own words — reply `/dispatch <your answers>` (one message is fine)."
    clauses = [c for c in _CLAUSE_SPLIT.split(good) if _INSTRUCTION.match(c)]
    assert clauses, "the fixture must contain a send-instruction clause"
    assert all(clause_is_reachable(c, parse_dispatch_command) for c in clauses)


def test_a_bare_number_really_is_refused_by_the_real_parser():
    """The premise the whole control rests on, asserted against the parser itself rather
    than believed. If this ever goes green, the instructions above are no longer wrong
    and this file needs rethinking, not silencing."""
    assert parse_dispatch_command("2") is None
    assert parse_dispatch_command("mostly on computer") is None
    assert parse_dispatch_command("/dispatch 2") is not None
