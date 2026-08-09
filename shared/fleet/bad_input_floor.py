"""The bad-input coverage floor (#1044) — a deterministic, model-free exam ruler.

An acceptance exam can certify a job GREEN while asserting nothing about bad input. That
is not a hypothesis: a flashcards build passed the per-task oracles, the job-level exam,
the sandbox's own eight test files and the ``green_quality`` juror (which scored it
``bad_input_handling=graceful``), and its shipped ``run_quiz`` crashed on two ordinary
inputs — ``KeyError`` on a card dict without a ``question`` key, ``AttributeError`` on an
answer that was not a string. Both were confirmed by execution against the shipped file.
GREEN meant "the happy path works", and every capability number resting on a GREEN rate
inherits that caveat.

This module closes it the way the never-zero-tests floor
(:func:`shared.fleet.acceptance._ensure_test_floor`) and the delivery floor
(:func:`shared.fleet.acceptance._ensure_delivery_floor`) close their gaps: the requirement
is INJECTED by machinery, never requested from a model and hoped for. For every first-party
callable the exam already invokes, the exam gains one test that drives that callable with a
ladder of malformed inputs — empty, ``None``, wrong-type, missing-key — and asserts it does
not fall over.

**Rejecting bad input is correct behaviour and PASSES.** A ``ValueError``, a ``TypeError``,
a domain exception, a ``SystemExit``, or a clean return are all handled outcomes. Only the
crash family that means "assumed a shape it never checked" fails. ``TypeError`` and
``ValueError`` are deliberately outside that family: both are the idiomatic Python way to
reject an argument, so counting them would convict code that validates properly, and a
false RED on a correct build is a worse outcome than a missed crash.

**RETRACTED (#1044 pre-merge review, F1).** An earlier revision of this docstring and of
:func:`bad_input_floor_targets` claimed that *"the floor can never demand a call shape the exam
did not itself perform"*. That was false as written. Shapes were read from the MERGED
``probe_signatures`` view, which unions keywords across call sites, so an exam calling one
entry point positionally at one site and by keyword at another produced a synthesised shape no
site used — every probe row then died at argument binding and the emitted test passed green
without ever entering the function. The claim is retained here because it is the property this
module is FOR, and it now holds by construction: shapes come from individual
:class:`~shared.fleet.interface_contract.CallSig` entries, and a row that cannot bind is
detected and excluded rather than mistaken for a rejected input.

**Injected, not detected.** The floor does not inspect whether the model already wrote a
bad-input test, and it never suppresses itself on one. Deciding "this existing test already
covers bad input" from model-authored English or AST shape is the predicate class the
delivery floor DELETED after review measured it wrong in both directions (see
``_ensure_delivery_floor``): a false positive silently disables the guarantee for the whole
exam, while a redundant test costs one test run. Idempotence is by IDENTITY instead — the
reserved marker :data:`BAD_INPUT_FLOOR_MARKER` — so re-running over an already-floored exam
is a no-op because the marker is present, never because something looked bad-input-ish.

**What this asserts, and what it does not.** It asserts that *a* bad-input check exists and
that the entry point survives the ladder — not that the callee's handling is the RIGHT
handling. A build can satisfy the floor with a broad ``except Exception: pass``. That is
accepted as the structural floor. The stronger form — a deterministic fuzz probe per
declared entry point, scoring the QUALITY of the handling — is a new grading layer and
therefore a capability question, not a widening of this ruler.

**Scope, as a contract:** python pytest exams only. A node ``node:test`` exam is returned
unchanged — JavaScript has no equivalent crash family (a missing key yields ``undefined``
rather than raising), so the same ladder would assert a different and much weaker property
there, and asserting a weak property loudly is worse than asserting none. Entry points the
exam calls with zero arguments and no keywords are skipped: there is no input to malform.

**Three further limits, named rather than discovered later.** (1) The injected tests CALL the
code under test, so an entry point with destructive side effects is driven with arguments the
exam's own tests never gave it; that is bounded by the fact that the exam already calls the
same entry points and by the disposability of the tree it runs in, but it is a real widening
of what gets executed. (2) A callee that loops forever on a malformed input hangs the probe
rather than failing it — Python has no portable in-process call timeout, so the surrounding
run budget is the only bound. (3) The ladder's second round varies one argument at a time and
fills the rest with the duck-typed value, which is the value most likely to be ACCEPTED — but
"most likely" is not "always": a callee whose FIRST guard is an ``isinstance`` check on a
different argument still rejects the call before the varied argument is reached, and the probe
reports handled. Round two narrows the masking window that round one leaves wide open; it does
not close it, and closing it in general would require knowing each argument's intended type,
which is the fuzz-probe layer above.

DELIBERATELY free of first-party imports beyond
:mod:`shared.fleet.interface_contract` (itself pure ``ast`` + stdlib), so it can be imported
lazily from ``acceptance`` with no cycle. Deterministic: same exam source ⇒ same injection.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass

#: The reserved marker the injected block carries. Idempotence is keyed on THIS string, not
#: on what any test in the exam appears to assert. Versioned: a future change to the emitted
#: ladder bumps the suffix, so an exam floored by an older revision is re-floored rather than
#: silently kept at the old bar.
BAD_INPUT_FLOOR_MARKER: str = "blarai-bad-input-floor-v1"

#: The reserved prefix on every emitted test function. Read by
#: :func:`shared.fleet.oracle_qa.fail_to_pass_baseline`, which must EXCLUDE these from its
#: vacuity set: F2P asks "does this test discriminate an implemented build from an empty one",
#: and a floor test legitimately answers no — on a brownfield tree whose entry point already
#: exists and already validates, it passes pre-implementation and is still doing its job. Left
#: in the set it would be classed CONFIRMED-vacuous, a HARD finding, and the whole job exam
#: would be REFUSED — a floor meant to strengthen grading deleting grading instead.
FLOOR_TEST_PREFIX: str = "test_bad_input_floor__"

#: Prefix on every emitted helper. Not cosmetic: the block is appended LAST, so an unprefixed
#: ``survives`` / ``BadValue`` / ``VALUES`` would SHADOW a same-named module-level symbol in a
#: model-authored exam and silently change what that exam's own tests do — corrupting the
#: measuring instrument rather than failing loudly. Locked by
#: ``test_the_emitted_block_defines_NO_unreserved_module_level_name``.
_EMIT_PREFIX = "_bif_"

#: Cap on injected tests. An exam calling more distinct entry points than this is already
#: past the point where one more assertion changes the verdict, and an unbounded block would
#: turn a runaway exam into a runaway test run.
_MAX_TARGETS = 24

#: Cap on positional arguments in a driven call — defensive; a real oracle call site is short.
#: A site wider than this is skipped rather than truncated: a truncated call is a shape the
#: exam never performed, which is the F1 class.
_MAX_POSITIONAL = 8

#: Cap on distinct call shapes driven per entry point. Each shape costs a full ladder, and an
#: exam calling one function more than this many DIFFERENT ways has already told the floor
#: everything a further shape would.
_MAX_SHAPES = 3

_IDENT_SCRUB = re.compile(r"[^0-9A-Za-z]+")


@dataclass(frozen=True)
class FloorTarget:
    """One entry point the floor will drive, and the call shapes to drive it with.

    ``module``/``name`` are the import the emitted test performs (``from app.quiz_engine
    import run_quiz``). ``shapes`` is the set of DISTINCT ``(positional_count, keyword_names)``
    call shapes the exam was observed to perform, each one taken WHOLE from a single call site
    — never assembled across sites. ``test_name`` is the reserved, deterministic pytest
    function name, and the injection's unit of de-duplication.

    **Why shapes are per-site rather than merged (#1044 pre-merge review, F1).** The first
    version read :meth:`InterfaceContract.probe_signatures`, which deliberately MERGES call
    sites — ``max_positional`` spans the observed counts and ``keywords`` unions them. That is
    right for the import probe, which asks "can the built signature bind every observed call",
    but wrong here: an exam calling ``check_answer(a, b)`` at one site and
    ``check_answer(a, expected=b)`` at another merges to ``(2 positional, keyword expected)``,
    a shape no site ever used and the callee cannot bind. Every probe row then died at
    ARGUMENT BINDING with a ``TypeError`` the ladder treats as "rejected the input, therefore
    handled", so the emitted test passed green having never entered the function — the exact
    silent-GREEN class this module exists to retire, reproduced inside it. Measured through
    the real seam: 28 of 28 rows never bound.
    """

    module: str
    name: str
    shapes: tuple[tuple[int, tuple[str, ...]], ...]
    test_name: str


def _is_probe_target_module(top: str) -> bool:
    """True when a top-level package is safe to DRIVE with malformed input — i.e. it is the
    code under test, not the standard library and not the test runner.

    Stricter than either existing first-party predicate, and deliberately so. ``oracle_qa``
    filters against ``acceptance._ORACLE_NON_API_ROOTS``, a curated list whose misses cost it
    only a SOFT finding; a miss HERE would have the floor import a stdlib module and call it
    with junk, which can only produce a false RED against a build that did nothing wrong.
    So a module must clear BOTH filters — the interpreter's own complete stdlib set and the
    curated list — before it is treated as an entry point.
    """
    if not top:
        return False
    from shared.fleet.acceptance import _ORACLE_NON_API_ROOTS
    from shared.fleet.interface_contract import _default_is_first_party

    return _default_is_first_party(top) and top not in _ORACLE_NON_API_ROOTS


def _test_name(module: str, name: str) -> str:
    """The reserved pytest function name for one target — deterministic and collision-proof
    against model-authored tests by its :data:`FLOOR_TEST_PREFIX` prefix."""
    mod = _IDENT_SCRUB.sub("_", module).strip("_")
    fn = _IDENT_SCRUB.sub("_", name).strip("_")
    return f"{FLOOR_TEST_PREFIX}{mod}__{fn}"


def bad_input_floor_targets(oracle_code: str) -> tuple[FloorTarget, ...]:
    """The entry points the floor covers: every first-party callable the exam ITSELF invokes,
    each with the distinct call shapes the exam performed on it.

    "Every public entry point the oracle imports" is the stated quantifier; the callables it
    INVOKES are the actionable subset of that, and the only one this can act on. A name the
    exam imports but never calls has no observed arity, so there is no call to synthesise —
    guessing one would mean calling a class or a constant as if it were a function, and a
    spurious failure convicts valid work.

    Shapes are read from :attr:`InterfaceContract.calls`, one entry per real call SITE, so a
    driven shape is always one the exam itself performed. (The merged view,
    ``probe_signatures``, is deliberately not used here — see :class:`FloorTarget`.) Two kinds
    of call site are skipped, each because driving it would invent rather than reproduce:

    * a site with no arguments at all — there is no input to malform, and asserting "it runs"
      duplicates the exam's own smoke test;
    * an UNDER-DETERMINED site (``f(*args)`` / ``f(**kwargs)``), whose real argument count the
      AST cannot know; its recorded counts are a lower bound, so building a call from them
      would be a guess wearing an observation's clothes.

    A target whose every site is skipped yields no floor test at all. That is a real, silent
    gap in coverage — accepted deliberately, because the alternative is a synthesised call, and
    a synthesised call is what F1 was.

    Order is the contract's first-observed order (deterministic). Fail-soft: unparseable or
    contract-less source yields ``()``.
    """
    if not oracle_code:
        return ()
    try:
        from shared.fleet.interface_contract import derive_interface_contract

        calls = derive_interface_contract(
            oracle_code, is_first_party=_is_probe_target_module
        ).calls
    except Exception:  # noqa: BLE001 — a derivation failure means no floor, never a crash
        return ()

    # (module, name) -> the distinct observed shapes, first-observed order preserved.
    shapes_by_target: dict[tuple[str, str], list[tuple[int, tuple[str, ...]]]] = {}
    order: list[tuple[str, str]] = []
    for call in calls:
        if call.starargs or call.starkwargs:
            continue
        positional = int(call.positional)
        keywords = tuple(str(k) for k in call.keywords)
        if positional <= 0 and not keywords:
            continue
        if positional > _MAX_POSITIONAL:
            continue
        key = (call.module, call.name)
        if key not in shapes_by_target:
            shapes_by_target[key] = []
            order.append(key)
        shape = (positional, keywords)
        if shape not in shapes_by_target[key] and len(shapes_by_target[key]) < _MAX_SHAPES:
            shapes_by_target[key].append(shape)

    out: list[FloorTarget] = []
    seen: set[str] = set()
    for module, name in order:
        shapes = shapes_by_target[(module, name)]
        if not shapes:
            continue
        test_name = _test_name(module, name)
        if test_name in seen:
            continue
        seen.add(test_name)
        out.append(
            FloorTarget(module=module, name=name, shapes=tuple(shapes), test_name=test_name)
        )
        if len(out) >= _MAX_TARGETS:
            break
    return tuple(out)


#: The emitted block is deliberately ASCII-ONLY. It is written into a sandbox tree this process
#: does not own and re-read by whatever the fleet's grader uses; a non-ASCII byte in a
#: machine-generated file is a decode error waiting for the one host whose default encoding is
#: not UTF-8, and a floor that makes the exam unreadable is worse than no floor.
_PREAMBLE = f'''

# --- bad-input coverage floor ({BAD_INPUT_FLOOR_MARKER}) - machine-injected, do not edit ---
# Each test below drives one entry point this exam already calls with a ladder of malformed
# inputs. REJECTING bad input is correct and passes: a ValueError, a TypeError, a domain
# exception, a SystemExit, or a clean return are all handled outcomes. Only an unhandled
# crash from the family below - "assumed a shape it never checked" - fails.
#
# A row is BIND-CHECKED before it is called, and a target no row can bind fails LOUDLY rather
# than passing: an argument-binding TypeError is indistinguishable from "the callee rejected
# the input" once it has been raised, so without the bind check a probe that never entered the
# function reports the same green as one that entered and survived.
import inspect as {_EMIT_PREFIX}inspect


class {_EMIT_PREFIX}BadValue:
    """A malformed value that satisfies the common duck-typed accesses, so a callee that
    never validates its input runs DEEP into its own logic and fails where it assumes a
    type, instead of stopping harmlessly at the first access.

    Every method below is load-bearing twice over. In round 1 they carry the probe past a
    callee's early accesses to the place it actually assumes a type. In round 2 this value
    is the FILLER for every argument not being varied, so each one that raises instead of
    answering is an argument that rejects the call before the varied argument is reached,
    which collapses round 2 back into round 1 and silently un-does the whole reason round 2
    exists. They are not conveniences; they are the reach of the probe."""

    def __call__(self, *args, **kwargs):
        return 0

    def __iter__(self):
        return iter((self,))

    def __len__(self):
        return 1

    def __getitem__(self, key):
        return 0

    def __contains__(self, item):
        return False

    def __bool__(self):
        return True

    def __repr__(self):
        # Fixed, address-free: a failure message is a fingerprint, and one carrying a heap
        # address differs on every run of the same defect.
        return "<malformed>"


{_EMIT_PREFIX}CRASHES = (
    AttributeError, KeyError, IndexError, NameError, UnboundLocalError,
    ZeroDivisionError, StopIteration, RecursionError,
)

{_EMIT_PREFIX}VALUES = (None, "", 0, [], {{}}, [{{}}], {_EMIT_PREFIX}BadValue())


def {_EMIT_PREFIX}arg_rows(slots):
    """The argument rows to drive one entry point with.

    Two rounds, and the second is not decoration. Making EVERY argument malformed at once
    masks defects: a callee that validates argument B rejects the call before argument A ever
    reaches the code that mishandles it, so the probe reports "handled" for an entry point
    that crashes in production. The second round therefore varies ONE argument at a time and
    fills the rest with the duck-typed value, the one most likely to be ACCEPTED, so each
    argument is actually reached.
    """
    rows = [[value] * slots for value in {_EMIT_PREFIX}VALUES]
    if slots > 1:
        filler = {_EMIT_PREFIX}VALUES[-1]
        for index in range(slots):
            for value in {_EMIT_PREFIX}VALUES:
                row = [filler] * slots
                row[index] = value
                rows.append(row)
    return rows


def {_EMIT_PREFIX}binds(fn, args, kwargs):
    """True when *fn* can actually BIND this argument row, so a call would enter its body.

    Two callables defeat this, and are allowed to. One whose signature cannot be introspected
    at all (``functools.reduce``, ``min``, many C builtins). And one whose signature is
    REPORTED as ``(*args, **kwargs)`` and so binds everything, while the real arity check
    happens inside the C body (``operator.itemgetter``, ``functools.partial`` factories) -
    introspection succeeding and LYING, which is the likelier of the two and the one the
    author had not named. Either way the row is called, a real arity TypeError comes back out,
    and the ladder swallows it as a rejected input: the same silent green.

    It is BOUNDED, and the bound is why over-counting is right here. Binding depends on arity
    and parameter names, never on argument values, so if the exam's own call binds then this
    row binds too - same callable, same shape. The hatch is therefore reachable only when the
    build's signature disagrees with a shape the exam actually performs, and in exactly that
    case the exam's OWN test already fails. What is lost is a diagnostic, never a verdict.
    Under-counting instead would fire the never-bound alarm at callables that are fine, which
    costs verdicts. One residual runs the other way: a call site in a branch the exam never
    executes is still a real AST site, so a target whose ONLY site is dead and mismatched
    raises the alarm on a build whose exam passes. Rare, and it fails toward loud.
    """
    try:
        signature = {_EMIT_PREFIX}inspect.signature(fn)
    except (TypeError, ValueError):
        return True
    try:
        signature.bind(*args, **kwargs)
    except TypeError:
        return False
    return True


def {_EMIT_PREFIX}survives(fn, shapes):
    reached = 0
    for positional, keywords in shapes:
        keywords = tuple(keywords)
        for row in {_EMIT_PREFIX}arg_rows(positional + len(keywords)):
            args = tuple(row[:positional])
            kwargs = dict(zip(keywords, row[positional:]))
            if not {_EMIT_PREFIX}binds(fn, args, kwargs):
                continue
            reached += 1
            try:
                fn(*args, **kwargs)
            except {_EMIT_PREFIX}CRASHES as exc:
                raise AssertionError(
                    "bad-input floor: %s crashed on the malformed arguments %r (%s: %s). "
                    "Validate or reject the input instead of assuming its shape."
                    % (getattr(fn, "__name__", fn), row, type(exc).__name__, exc)
                ) from exc
            except SystemExit:
                pass
            except Exception:
                pass
    if not reached:
        raise AssertionError(
            "bad-input floor: could not enter %s with ANY argument shape this exam uses "
            "(%r) - its signature binds none of them, so bad-input coverage was NOT measured "
            "for it. An absent measurement is not a clean bill."
            % (getattr(fn, "__name__", fn), shapes)
        )
'''


def _render_target(target: FloorTarget) -> str:
    """The emitted pytest function for one target. The import is INSIDE the test so a
    missing module fails this test alone rather than the whole exam's collection."""
    return (
        f"\n\ndef {target.test_name}():\n"
        f'    """Bad-input floor: `{target.name}` from `{target.module}` must not crash on '
        f'malformed input."""\n'
        f"    from {target.module} import {target.name}\n\n"
        f"    {_EMIT_PREFIX}survives({target.name}, {target.shapes!r})\n"
    )


def inject_bad_input_floor(oracle_code: str) -> str:
    """Append the floor to a python exam and return the new source; return it UNCHANGED when
    the floor does not apply.

    Unchanged when: the exam is empty; the reserved marker is already present (idempotence by
    identity); no target is derivable; or — the self-check — the injected result does not
    parse. That last guard is why this can be trusted to run on model-authored source: a
    result that would not ``ast.parse`` is discarded rather than seeded, so the floor can
    never turn a collectable exam into an uncollectable one.
    """
    if not oracle_code or BAD_INPUT_FLOOR_MARKER in oracle_code:
        return oracle_code
    targets = bad_input_floor_targets(oracle_code)
    if not targets:
        return oracle_code
    block = _PREAMBLE + "".join(_render_target(t) for t in targets)
    floored = oracle_code.rstrip("\n") + "\n" + block
    try:
        ast.parse(floored)
    except (SyntaxError, ValueError):
        return oracle_code
    return floored
