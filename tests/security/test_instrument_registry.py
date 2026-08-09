r"""The #1223 structural control — every grader must be able to say "I did not look".

WHY THIS GATE EXISTS.
---------------------
On 2026-07-30, NINE instruments were found in a single day reporting a pass, a clean or a
number they had not measured. ``CLAUDE.md``'s lesson-curation rule requires a structural
control at the THIRD instance; this is that control, nine instances late. Every one of the
nine was caught by a person or an agent READING CODE — never by a gate — and every one erred
toward LOOKING FINE. Not one produced a false alarm. An error distribution that one-sided is
not chance: it is what happens when the "cannot measure" path is written by someone thinking
about the happy path, and it means the population of UNDISCOVERED instances is skewed the
same way.

The SSOT is :mod:`shared.instrument_registry`. Read its docstring first — it states the
invariant (an instrument is BORN unmeasured), the four status shapes, and the residue no gate
can reach.

FOUR TEETH, matching the ticket's four parts:

  (1) **The born-unmeasured contract** (:func:`test_every_registered_instrument_conforms`) —
      every registered result type carries a status field whose DECLARED DEFAULT is the
      unmeasured value. A grader with no honesty bit fails here by name. This is what caught
      ``CraftFinding`` and ``CoderTestQAResult``.

  (2) **No falsy-collapse at the renderer**
      (:func:`test_no_registered_renderer_collapses_a_count_into_truthiness`) — the half that
      makes (1) real. A ``measured`` attribute no caller consults is the same defect wearing
      the fix's uniform, so every renderer that branches on what an instrument FOUND must
      consult, on the same receiver path, whether it LOOKED.

  (3) **The named toggle / seam / quiet TRIO**
      (:func:`test_every_entry_names_a_live_toggle_and_seam_test`,
      :func:`test_every_entry_proves_it_stays_quiet_on_a_healthy_input`) — principle 12
      demands a control ship with a test proving it blocks and a probe that fails when the
      control is off. Instances 1-6 shipped without one, so the registry makes them REQUIRED,
      RESOLVED fields rather than habits. The THIRD case is not in principle 12 and is here
      because three agents independently warned, on one night, that noise is how this fix
      fails: an instrument that convicts healthy configurations gets muted, and a muted
      control is worse than the silence it replaced. The register throughout is the WinUI
      passthrough allowlist gate's: parse the real artifact, fail loudly, name what is
      missing.

  (4) **Fixture realism — PRODUCED, not CONSTRUCTED**
      (:func:`test_every_seam_test_drives_the_real_entrypoint`) — a seam test must CALL the
      registered entrypoint and must NOT construct the result type. The sharpest statement of
      why came from the #1197 author about its own work: *"I wrote a test that fabricated the
      precondition for its own fix... the test agrees with the AUTHOR instead of with
      PRODUCTION."* 1,416 green over a defect that reproduced on the first real drive. An
      author already holds a model of the program, and the cheapest way to make a test pass
      is to encode that model into the fixture; the suite then reports agreement as evidence.
      A related instance the same night: a corrupt-input test enumerating SEVEN hand-built
      shapes, where the one the writer actually emits — file absence — was absent from the
      seven and was the only one that failed open. Seven wrong shapes read exactly like
      thoroughness.

AND THE GATE'S OWN TOGGLE, DRIVEN THROUGH THE ASSEMBLED PATH. This is a control ABOUT
controls, so it is the last place an always-passing check may hide.
:func:`test_the_gate_fires_on_a_non_conforming_instrument` and
:func:`test_the_gate_passes_a_conforming_instrument` drive
:func:`~shared.instrument_registry.audit` — the same composed call the standing gate uses,
justification filtering included — over two REAL modules written to disk, one broken and one
sound. Driving the HELPERS instead is the specific mistake being avoided: on 2026-07-30 a
brand-new structural gate for this very defect class convicted nothing, because ``&`` binds
tighter than ``|`` and its guard was permanently truthy, and its own proved-off test missed
it by exercising one helper in isolation.

WHAT THIS GATE CANNOT DO. It checks the FORM of an instrument that is REGISTERED. It cannot
see one nobody registered and nobody renders through a registered renderer, it cannot see a
renderer nobody registered, and it can never judge whether a ``measured=True`` is HONEST.
``scripts/verify_disposition.py`` carries the identical limit and states it; this ticket is
NOT closable on a claim that the class is now impossible.
"""

from __future__ import annotations

import ast
import importlib
import re
import sys
from pathlib import Path

import pytest

from shared.instrument_registry import (
    JUSTIFICATION_MIN_CHARS,
    JUSTIFIED_COLLAPSES,
    JUSTIFIED_NON_INSTRUMENT_READS,
    RATE_UNMEASURED,
    REGISTRY,
    STATUS_KINDS,
    STATUS_PREDICATE,
    STATUS_SENTINEL,
    InstrumentEntry,
    audit,
    collapse_key,
    falsy_collapse_defects,
    guard_alias_reads,
    live_collapse_keys,
    renderer_defects,
    renderer_source,
    resolve_attr,
    status_defects,
    unclaimed_reads,
)

_REPO = Path(__file__).resolve().parents[2]

#: ``tests/path.py::test_name`` — the form every toggle/seam field takes.
_TEST_REF_RE = re.compile(r"^(?P<path>[\w./-]+\.py)::(?P<name>test_\w+)$")


def _test_function(ref: str) -> tuple[Path, ast.FunctionDef]:
    """Resolve a ``path::name`` reference to the real test function's AST, or fail loudly."""
    match = _TEST_REF_RE.match(ref)
    assert match, f"{ref!r} is not a 'tests/....py::test_name' reference"
    path = _REPO / match.group("path")
    assert path.is_file(), f"{ref}: {path} does not exist"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == match.group("name"):
            return (path, node)  # type: ignore[return-value]
    raise AssertionError(f"{ref}: {path} defines no function {match.group('name')!r}")


def _called_names(fn: ast.AST) -> set[str]:
    """Every bare or dotted callee name invoked in a function body."""
    out: set[str] = set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            out.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            out.add(node.func.attr)
    return out


# ---------------------------------------------------------------------------
# Registry shape
# ---------------------------------------------------------------------------


def test_registry_is_non_empty_and_well_formed() -> None:
    """Every entry carries the full contract, and no field is a placeholder."""
    assert REGISTRY, "the instrument registry is empty - the #1223 control has no subjects"
    seen: set[str] = set()
    for e in REGISTRY:
        assert e.name and e.name not in seen, f"duplicate/empty instrument name: {e.name!r}"
        seen.add(e.name)
        assert e.status_kind in STATUS_KINDS, f"{e.name}: unknown status_kind {e.status_kind!r}"
        for field_name in ("module", "result_type", "entrypoint", "status", "incident",
                           "not_measured", "toggle_test", "seam_test"):
            assert getattr(e, field_name), f"{e.name}: empty {field_name}"
        assert e.counts, f"{e.name}: no count fields - nothing for the renderer rule to bite on"
        assert e.renderers, (
            f"{e.name}: no renderers. An instrument nothing renders is not an instrument for "
            f"this registry, and an entry with no renderers exempts itself from the half of "
            f"the gate that has teeth."
        )
        if e.status_kind != STATUS_PREDICATE:
            assert e.receivers, (
                f"{e.name}: no receivers, so no read in any renderer can be charged to it"
            )


# ---------------------------------------------------------------------------
# (1) The born-unmeasured contract — THE TEETH
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("entry", REGISTRY, ids=lambda e: e.name)
def test_every_registered_instrument_conforms(entry: InstrumentEntry) -> None:
    """Every registered result type can tell 'ran and found nothing' from 'did not run'.

    Removing an instrument's status field, or changing its default away from the unmeasured
    value, turns this green suite red and NAMES the instrument."""
    defects = status_defects(entry)
    assert not defects, (
        f"{entry.name} ({entry.module}:{entry.result_type}) does not carry the "
        f"born-unmeasured contract:\n  - " + "\n  - ".join(defects)
    )


@pytest.mark.parametrize("entry", REGISTRY, ids=lambda e: e.name)
def test_every_registered_entrypoint_resolves(entry: InstrumentEntry) -> None:
    """The registered producer exists and is callable (catches a typo'd or renamed path)."""
    fn = resolve_attr(entry.module, entry.entrypoint)
    assert callable(fn), f"{entry.name}: {entry.module}:{entry.entrypoint} is not callable"


# ---------------------------------------------------------------------------
# (2) No falsy-collapse at the renderer — THE OTHER TEETH
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("entry", REGISTRY, ids=lambda e: e.name)
def test_no_registered_renderer_collapses_a_count_into_truthiness(
    entry: InstrumentEntry,
) -> None:
    """No renderer branches on what an instrument FOUND without consulting whether it LOOKED.

    The recurring mechanic of instances 3, 4 and 5: ``if result.x:`` where ``None`` and ``0``
    are both falsy and mean opposite things."""
    defects: list[str] = []
    for site in entry.renderers:
        defects.extend(f"{site} {d}" for d in renderer_defects(site, entry))
    assert not defects, (
        f"{entry.name}: renderer(s) cannot tell an unmeasured result from a clean one:\n  - "
        + "\n  - ".join(defects)
        + f"\n\nFix the renderer to consult `{entry.status}` on the same receiver, or - if the "
        f"falsy branch is an ACCUSATION rather than a clean claim - argue it into "
        f"JUSTIFIED_COLLAPSES in shared/instrument_registry.py."
    )


def test_registered_renderers_all_resolve() -> None:
    """Every renderer site names a function that exists (a renamed renderer fails here)."""
    for entry in REGISTRY:
        for site in entry.renderers:
            path, fn = renderer_source(site)
            assert isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)), site
            assert path.is_file(), site


def test_no_unregistered_instrument_is_rendered() -> None:
    """THE SWEEP: a boolean-context read of a registered count field that NO entry claims.

    This is how a grader nobody registered becomes visible — ``if layer1.new_lint.flagged:``
    wired into the band belongs to no entry's receivers and surfaces here by name. Bounded
    honestly (see :func:`~shared.instrument_registry.unclaimed_reads`): it sees a read that
    REUSES a count field name already in the table, not one whose fields are all novel."""
    orphans: list[str] = []
    for site in sorted({s for e in REGISTRY for s in e.renderers}):
        _path, fn = renderer_source(site)
        orphans.extend(f"{site} line {lineno}: `{path}`" for lineno, path in unclaimed_reads(fn))
    assert not orphans, (
        "a registered renderer branches on an instrument no registry entry claims - register "
        "it in shared/instrument_registry.py, or justify it in "
        "JUSTIFIED_NON_INSTRUMENT_READS:\n  - " + "\n  - ".join(orphans)
    )


def test_justifications_are_argued_and_still_live() -> None:
    """An exclusion must carry a real argument AND still describe a real collapse.

    A suppression that outlives its subject is how an exclusion list turns into a list of
    things nobody rechecks — the same discipline
    ``test_external_probe_registry.test_justified_exclusions_are_documented_and_live``
    applies to the egress-door sweep."""
    live = live_collapse_keys()
    for key, reason in JUSTIFIED_COLLAPSES.items():
        assert len(reason) >= JUSTIFICATION_MIN_CHARS, (
            f"justified collapse {key!r} asserts rather than argues "
            f"({len(reason)} < {JUSTIFICATION_MIN_CHARS} chars)"
        )
        assert key in live, (
            f"justified collapse {key!r} no longer describes a real collapse - remove the "
            f"stale justification rather than leaving a suppression nobody rechecks"
        )
    for key, reason in JUSTIFIED_NON_INSTRUMENT_READS.items():
        assert len(reason) >= JUSTIFICATION_MIN_CHARS, (
            f"justified non-instrument read {key!r} asserts rather than argues"
        )


# ---------------------------------------------------------------------------
# (3) + (4) The named toggle/seam/quiet trio, and fixture realism
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("entry", REGISTRY, ids=lambda e: e.name)
def test_every_entry_proves_it_stays_quiet_on_a_healthy_input(entry: InstrumentEntry) -> None:
    """THE THIRD CASE: the instrument must not convict a correct configuration.

    Principle 12 asks for "it fires" and "it fails when disabled". Three agents independently
    warned on 2026-07-30 that this registry's real risk is the opposite one: make eleven
    instruments loud, let ONE speak on healthy runs, and the operator learns to skim the
    caveat block — at which point all eleven are silent, including the honest ones. A
    fail-loud control that convicts healthy configurations gets muted, and a muted control is
    worse than the silence it replaced.

    The quiet case must drive the REAL producer, for the same reason the seam case does:
    "it stays quiet in production" is a claim about production, and a hand-built result
    cannot support it."""
    _path, quiet = _test_function(entry.quiet_test)
    assert entry.entrypoint in _called_names(quiet), (
        f"{entry.name}: quiet test {entry.quiet_test} never calls `{entry.entrypoint}()` - "
        f"a hand-built result cannot show that the REAL instrument stays quiet."
    )


@pytest.mark.parametrize("entry", REGISTRY, ids=lambda e: e.name)
def test_every_entry_declares_a_disclosure_marker_its_toggle_pins(
    entry: InstrumentEntry,
) -> None:
    """A DISCLOSURE and a FINDING must be tellable apart, and the marker is how.

    "I could not measure this" and "I measured this and it is wrong" are different facts with
    different urgencies. Collapsing them is this module's own defect one level up: a
    disclosure read as a finding is a false accusation, and a finding read as a disclosure is
    the false clean the whole ticket is about. The marker is the declared substring that
    separates them in a rendered report — or, for a machine-facing renderer, the key that
    carries the fact.

    The toggle test must PIN it, so the wording cannot drift out from under a reader who
    learned to look for it."""
    assert entry.disclosure_marker, f"{entry.name}: no disclosure marker declared"
    _path, toggle = _test_function(entry.toggle_test)
    assert entry.disclosure_marker in ast.unparse(toggle), (
        f"{entry.name}: toggle test {entry.toggle_test} never pins the declared disclosure "
        f"marker {entry.disclosure_marker!r} - nothing stops the wording drifting away from "
        f"the reader who learned to look for it."
    )


def test_disclosure_rates_are_measured_figures_or_honestly_unmeasured() -> None:
    """A firing rate is DATA, and a guessed one is this registry's own defect in uniform.

    An instrument that discloses on 94% of runs is technically honest and practically silent
    — the #1198 verification measured that exact shape, 3 clean bills in 373 reports — and it
    is worth knowing as a number rather than discovering as a habit. Every entry therefore
    carries either a measured figure WITH its provenance, or the literal
    :data:`RATE_UNMEASURED`. Nothing in between, because a plausible number nobody measured is
    precisely what this module exists to make impossible."""
    for entry in REGISTRY:
        if entry.disclosure_rate == RATE_UNMEASURED:
            continue
        assert re.search(r"\d", entry.disclosure_rate), (
            f"{entry.name}: disclosure_rate {entry.disclosure_rate!r} is neither "
            f"RATE_UNMEASURED nor a figure"
        )
        assert len(entry.disclosure_rate) >= JUSTIFICATION_MIN_CHARS, (
            f"{entry.name}: a measured disclosure rate must carry its provenance (which "
            f"corpus, how many runs), never a bare percentage"
        )


@pytest.mark.parametrize("entry", REGISTRY, ids=lambda e: e.name)
def test_every_entry_names_a_live_toggle_and_seam_test(entry: InstrumentEntry) -> None:
    """Both named tests exist, and neither is a stub that touches nothing.

    Non-vacuity is checked structurally rather than trusted: the toggle test must NAME the
    result type (or, for a dict-shaped instrument, the predicate) and a guard, because a
    control whose proof mentions neither is a control with a filename and no teeth."""
    _toggle_path, toggle = _test_function(entry.toggle_test)
    _seam_path, seam = _test_function(entry.seam_test)

    toggle_src = ast.unparse(toggle)
    if entry.status_kind == STATUS_PREDICATE:
        assert entry.status in toggle_src, (
            f"{entry.name}: toggle test {entry.toggle_test} never mentions the predicate "
            f"`{entry.status}` - it cannot be proving the renderer consults it"
        )
    else:
        assert entry.result_type in toggle_src, (
            f"{entry.name}: toggle test {entry.toggle_test} never mentions "
            f"{entry.result_type} - it cannot be driving this instrument"
        )
        assert any(g in toggle_src for g in entry.guard_names), (
            f"{entry.name}: toggle test {entry.toggle_test} never mentions "
            f"{' or '.join(entry.guard_names)} - it cannot be proving the unmeasured case"
        )
    assert seam is not toggle, f"{entry.name}: toggle and seam test are the same function"


@pytest.mark.parametrize("entry", REGISTRY, ids=lambda e: e.name)
def test_every_seam_test_drives_the_real_entrypoint(entry: InstrumentEntry) -> None:
    """FIXTURE REALISM: the seam test must CALL the registered producer.

    A test that hand-builds the unmeasured result proves the renderer and never crosses the
    boundary where the real failure lives — the trap found twice on 2026-07-30 (a substituted
    runner measuring 0.9 s against the real command's 5.67 s, and fixtures building a shape
    the production parser forbids). Naming the call is checkable; 'the fixture is realistic'
    is not."""
    _path, seam = _test_function(entry.seam_test)
    called = _called_names(seam)
    assert entry.entrypoint in called, (
        f"{entry.name}: seam test {entry.seam_test} never calls "
        f"`{entry.entrypoint}()`. Drive the real producer - a hand-built result proves the "
        f"renderer, not the seam."
    )
    # PRODUCED, NOT CONSTRUCTED. The sharpest statement of this class came from the #1197
    # author about its own work: "I wrote a test that fabricated the precondition for its own
    # fix... the test agrees with the AUTHOR instead of with PRODUCTION." An author already
    # holds a model of the program, and the cheapest way to make a test pass is to encode
    # that model into the fixture; the suite then reports agreement as evidence. 1,416 green
    # over a defect that reproduced on the first real drive.
    #
    # A seam test that CONSTRUCTS the result type has done exactly that — it has written down
    # what it believes the producer emits. The degraded condition must come from the real
    # environment (an absent tree, an unparseable file, an unresolvable binary), never from a
    # literal. Skipped for STATUS_PREDICATE, whose "result type" is a plain dict.
    if entry.status_kind != STATUS_PREDICATE:
        assert entry.result_type not in called, (
            f"{entry.name}: seam test {entry.seam_test} CONSTRUCTS {entry.result_type}(...). "
            f"That fixture is the author's belief about what the producer emits, not the "
            f"producer's output - drive `{entry.entrypoint}()` into a real degraded condition "
            f"instead. (Build-by-hand belongs in the toggle test, where the renderer is the "
            f"subject.)"
        )


# ---------------------------------------------------------------------------
# THE GATE'S OWN TOGGLE — a control about controls may not be an always-pass
# ---------------------------------------------------------------------------

_BROKEN_INSTRUMENT = '''
"""A grader with no honesty bit, and a renderer that cannot tell silence from cleanliness."""
from dataclasses import dataclass


@dataclass
class ProbeResult:
    findings: list = None
    files_scanned: int = 0

    def summary(self) -> str:
        if self.findings:
            return f"{len(self.findings)} finding(s)"
        return "clean"


def run_probe(path):
    return ProbeResult(findings=[])
'''

_SOUND_INSTRUMENT = '''
"""The same grader, built to the registry's contract."""
from dataclasses import dataclass, field


@dataclass
class ProbeResult:
    findings: list = field(default_factory=list)
    files_scanned: int = 0
    measured: bool = False

    def summary(self) -> str:
        if not self.measured:
            return "could-not-determine"
        if self.findings:
            return f"{len(self.findings)} finding(s)"
        return "clean"


def run_probe(path):
    return ProbeResult(findings=[], measured=True)
'''


_MENTIONING_INSTRUMENT = '''
"""The INNOCENT shape: the honesty bit is emitted, and nothing ever consults it."""
from dataclasses import dataclass, field


@dataclass
class ProbeResult:
    findings: list = field(default_factory=list)
    files_scanned: int = 0
    measured: bool = False

    def summary(self) -> dict:
        return {
            "measured": self.measured,
            "status": "clean" if not self.findings else "dirty",
        }


def run_probe(path):
    return ProbeResult(findings=[], measured=True)
'''

_AND_GUARDED_INSTRUMENT = '''
"""The short-circuit arrangement: the guard is a sibling operand of the read's `and`."""
from dataclasses import dataclass, field


@dataclass
class ProbeResult:
    findings: list = field(default_factory=list)
    files_scanned: int = 0
    measured: bool = False

    def summary(self) -> str:
        if self.measured and self.findings:
            return f"{len(self.findings)} finding(s)"
        if not self.measured:
            return "could-not-determine"
        return "clean"


def run_probe(path):
    return ProbeResult(findings=[], measured=True)
'''

_OR_GUARDED_INSTRUMENT = '''
"""The INVERTED arrangement: `or` reaches the read exactly when the guard was false."""
from dataclasses import dataclass, field


@dataclass
class ProbeResult:
    findings: list = field(default_factory=list)
    files_scanned: int = 0
    measured: bool = False

    def summary(self) -> str:
        if self.measured or self.findings:
            return f"{len(self.findings)} finding(s)"
        return "clean"


def run_probe(path):
    return ProbeResult(findings=[], measured=True)
'''


def _synthetic_entry(module: str) -> InstrumentEntry:
    """A registry entry over a module written for this test — same type, same code path."""
    return InstrumentEntry(
        name=f"synthetic {module}",
        module=module,
        result_type="ProbeResult",
        entrypoint="run_probe",
        status="measured",
        status_kind="field",
        unmeasured=False,
        counts=("findings", "files_scanned"),
        receivers=("self",),
        renderers=(f"{module}:ProbeResult.summary",),
        toggle_test="tests/security/test_instrument_registry.py::test_the_gate_fires_on_a_non_conforming_instrument",
        seam_test="tests/security/test_instrument_registry.py::test_the_gate_fires_on_a_non_conforming_instrument",
        quiet_test="tests/security/test_instrument_registry.py::test_the_gate_passes_a_conforming_instrument",
        disclosure_marker="could-not-determine",
        incident="the gate's own toggle",
        not_measured="nothing - this instrument is synthetic",
    )


def _write_module(tmp_path: Path, name: str, source: str) -> str:
    """Write a real module to disk and make it importable — no in-memory stand-in.

    The analysis reads its subject from the FILESYSTEM via ``inspect.getsourcefile``, so a
    synthetic module that never touched a disk would exercise a path production never uses."""
    (tmp_path / f"{name}.py").write_text(source, encoding="utf-8")
    if str(tmp_path) not in sys.path:
        sys.path.insert(0, str(tmp_path))
    # The documented remedy for modules created at runtime: ``FileFinder`` caches each
    # sys.path directory's listing against that directory's mtime, so a SECOND module written
    # into a directory already on the path can be invisible to import. Observed twice here —
    # a ModuleNotFoundError arriving as a resolution "defect", which a test asserting
    # `assert defects` would read as a conviction. NOT a reproducible failure: six runs with
    # this line removed all passed, so treat it as prophylaxis, not as a proven fix. The
    # control that does not depend on reproducing it is :func:`_defects_of`.
    importlib.invalidate_caches()
    return name


def _defects_of(entry: InstrumentEntry) -> list[str]:
    """The assembled audit's defects for ONE synthetic entry, with resolution failure refused.

    THE PASS NOBODY MEASURED, one level up. A synthetic module that did not import produces
    ``does not resolve`` defects, and every conviction test below is written ``assert defects``
    — so an import failure SATISFIES the assertion while the analysis under test never ran.
    That is this gate's own defect class, inside this gate, which is where it keeps being
    found.

    It is not hypothetical: a second module written into a ``tmp_path`` already on
    ``sys.path`` was twice invisible to import here. :func:`_write_module` now invalidates the
    import caches, but that remedy is a prophylactic against a failure nobody could reproduce
    on demand, and a control resting on an unreproducible fix is a control resting on nothing.
    This one does not care WHY the module is missing: a test that cannot confirm its subject
    was loaded reports that, never a result."""
    (_entry, defects), = audit([entry])
    unresolved = [d for d in defects if "does not resolve" in d]
    assert not unresolved, (
        "the synthetic instrument never loaded, so the analysis under test did not run and "
        "these are import errors, not convictions:\n  - " + "\n  - ".join(unresolved)
    )
    return defects


def test_the_gate_fires_on_a_non_conforming_instrument(tmp_path: Path) -> None:
    """PROOF OF TEETH, THROUGH THE ASSEMBLED PATH — not through its parts.

    Drives :func:`~shared.instrument_registry.audit`, the same composed call the standing
    gate and the CLI use, so status resolution, renderer analysis AND justification filtering
    are all under test at once.

    Driving the helpers separately is the specific mistake this arrangement exists to avoid.
    On 2026-07-30 a brand-new structural gate for this very defect class convicted nothing —
    ``REMEDY_NAMES & {names} | {attrs}`` binds as ``(REMEDY_NAMES & {names}) | {attrs}``, and
    ``{attrs}`` is non-empty for every real module, so the guard was permanently truthy. A
    purpose-built offender scored ``1 passed in 0.04s``. Its proved-off test missed it
    because it exercised ONE HELPER IN ISOLATION and never the composed guard. A control
    about controls is the last place that may happen."""
    module = _write_module(tmp_path, "blarai_broken_instrument_1223", _BROKEN_INSTRUMENT)
    entry = _synthetic_entry(module)

    defects = _defects_of(entry)
    assert defects, (
        "the ASSEMBLED gate accepted an instrument with no status field AND a renderer that "
        "collapses on its findings - it convicts nothing"
    )
    joined = "\n".join(defects)
    assert "measured" in joined and "ProbeResult" in joined, (
        f"the gate fired without naming the missing status field: {defects}"
    )
    assert "self.findings" in joined, (
        f"the gate fired without naming the collapsing read: {defects}"
    )


def test_the_gate_passes_a_conforming_instrument(tmp_path: Path) -> None:
    """THE OTHER HALF OF THE TOGGLE: the assembled gate over a SOUND instrument is silent.

    Without this, an always-failing check would satisfy the test above and prove nothing.
    The two together are what make the gate a discriminator rather than a constant."""
    module = _write_module(tmp_path, "blarai_sound_instrument_1223", _SOUND_INSTRUMENT)
    entry = _synthetic_entry(module)

    defects = _defects_of(entry)
    assert not defects, f"the assembled gate rejected a conforming instrument: {defects}"


def test_a_justification_cannot_suppress_a_defect_it_does_not_name(tmp_path: Path) -> None:
    """The escape hatch is keyed to ONE collapse at ONE site, and cannot widen.

    :data:`~shared.instrument_registry.JUSTIFIED_COLLAPSES` is the part of this gate most
    likely to hollow it out over time, and the failure would be silent: an over-broad key
    suppresses everything and the suite stays green. Proved through the assembled path,
    because the filtering lives in ``renderer_defects`` rather than in the analysis."""
    module = _write_module(tmp_path, "blarai_broken_instrument_1223b", _BROKEN_INSTRUMENT)
    entry = _synthetic_entry(module)
    site = entry.renderers[0]

    _path, fn = renderer_source(site)
    real = falsy_collapse_defects(fn, entry)
    assert real, "fixture no longer produces a collapse, so this test proves nothing"

    # A justification naming a DIFFERENT read at the same site must not suppress this one.
    wrong_key = collapse_key(site, "self.files_scanned")
    assert wrong_key not in JUSTIFIED_COLLAPSES, "test fixture collided with a real entry"
    assert any("self.findings" in d for d in renderer_defects(site, entry)), (
        "renderer_defects suppressed a collapse that no justification names"
    )


def test_mentioning_the_guard_does_not_excuse_a_collapse(tmp_path: Path) -> None:
    """THE INNOCENT SHAPE: a renderer that EMITS the honesty bit and never consults it.

    This is the hole the first cut of the analysis had, and it did not need anyone to be
    gaming it. The guard set was every attribute chain ANYWHERE in the function, so a
    renderer returning ``{"measured": self.measured, "status": "clean" if not self.findings
    else "dirty"}`` was acquitted while shipping the exact defect: the dict says the bit was
    known, the status line proves nobody asked. Verified exploitable on production code too —
    a dead ``_dead = reg.measured`` in ``card.py`` let BOTH real guards be deleted with the
    gate still green, and dropping ONE of ``band.py``'s two regression guards was invisible
    because the sibling branch still mentioned it.

    The rule now is that the guard must DECIDE whether the line runs (see
    :func:`~shared.instrument_registry.guarding_expressions`)."""
    module = _write_module(tmp_path, "blarai_mentioning_instrument_1223", _MENTIONING_INSTRUMENT)
    entry = _synthetic_entry(module)

    defects = _defects_of(entry)
    assert defects, (
        "the gate acquitted a renderer that emits `measured` and then collapses on "
        "`findings` - a mention is being read as a guard"
    )
    assert any("self.findings" in d for d in defects), defects


def test_both_real_guard_arrangements_are_still_accepted(tmp_path: Path) -> None:
    """THE OTHER HALF: the tightening must not convict the shapes production actually uses.

    A control that fires on correct configurations gets muted, and a muted control is worse
    than the silence it replaced - so the two arrangements every renderer in this tree is
    written in are pinned here, and a future tightening that breaks either fails loudly
    rather than filling the report with false accusations.

    ``_SOUND_INSTRUMENT`` is the guard-clause form (``if not self.measured: return ...``, then
    the collapsing read below it); ``_AND_GUARDED_INSTRUMENT`` is the short-circuit form
    (``if self.measured and self.findings:``). Both genuinely decide whether the read runs."""
    for name, source in (("blarai_guardclause_1223", _SOUND_INSTRUMENT),
                         ("blarai_andguarded_1223", _AND_GUARDED_INSTRUMENT)):
        module = _write_module(tmp_path, name, source)
        defects = _defects_of(_synthetic_entry(module))
        assert not defects, f"{name}: a real guard arrangement was convicted: {defects}"


def test_an_or_is_not_a_guard(tmp_path: Path) -> None:
    """``if f.measured or f.flagged:`` reaches the read precisely when the guard was FALSE.

    Pinned because it is the one boolean arrangement that LOOKS like the accepted one and
    inverts it, and because accepting ``or`` would be the cheapest way to widen this analysis
    back into a mention check without anyone noticing."""
    module = _write_module(tmp_path, "blarai_or_instrument_1223", _OR_GUARDED_INSTRUMENT)
    defects = _defects_of(_synthetic_entry(module))
    assert defects, "an `or` between the guard and the read was accepted as a guard"
    assert any("self.findings" in d for d in defects), defects


def test_the_sentinel_rule_is_stricter_than_the_field_rule(tmp_path: Path) -> None:
    """A mere mention of an Optional sentinel is NOT a guard — only an ``is None`` test is.

    #1189's exact shape: ``if x.ruff_findings:`` reads "did not run" and "ran, found nothing"
    as one answer, and no amount of referring to the same attribute disambiguates it."""
    source = (
        "from dataclasses import dataclass\n"
        "from typing import Optional\n\n"
        "@dataclass\n"
        "class ProbeResult:\n"
        "    findings: Optional[int] = None\n"
        "    files_scanned: int = 0\n\n"
        "    def summary(self) -> str:\n"
        "        if self.findings:\n"
        "            return f'{self.findings} finding(s)'\n"
        "        return 'clean'\n\n"
        "def run_probe(path):\n"
        "    return ProbeResult()\n"
    )
    module = _write_module(tmp_path, "blarai_sentinel_instrument_1223", source)
    entry = _synthetic_entry(module)
    sentinel = InstrumentEntry(**{**entry.__dict__, "status": "findings",
                                  "status_kind": STATUS_SENTINEL, "unmeasured": None,
                                  "counts": ("findings",)})
    _path, fn = renderer_source(sentinel.renderers[0])
    defects = falsy_collapse_defects(fn, sentinel)
    assert defects and "is None" in defects[0], (
        f"the sentinel rule accepted a bare truthiness test: {defects}"
    )


# ---------------------------------------------------------------------------
# F1, on LIVE CODE — the synthetics above prove the rule; this proves the rule reaches
# production. The original exploit was found by editing a real renderer, not a fixture, and
# a synthetic-only lock would leave the analysis free to stop applying to the tree it guards.
# ---------------------------------------------------------------------------

#: The live renderer the exploit was demonstrated against: five instruments guarded in the
#: short-circuit ``and`` form, in one function. The other two accepted arrangements are pinned
#: by the synthetics above; every live renderer of every arrangement is swept by
#: :func:`test_no_registered_renderer_collapses_a_count_into_truthiness`.
_LIVE_SITE = "tools.dispatch_harness.green_quality.card:_caveat_from_layer1"


def _analyse_source(source: str, func_name: str) -> list[str]:
    """Run the REAL falsy-collapse analysis over *source* for every entry rendering there.

    Parses text rather than importing, so a MUTATED copy of a production file can be driven
    through the same code path the gate uses without touching the file on disk."""
    tree = ast.parse(source)
    target = next((n for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and n.name == func_name), None)
    assert target is not None, f"{func_name} not found in the source under test"
    return [f"[{e.name}] {d}" for e in REGISTRY if _LIVE_SITE in e.renderers
            for d in falsy_collapse_defects(target, e)]


def test_the_live_renderer_is_acquitted_as_written() -> None:
    """THE QUIET HALF, on production code. ``_caveat_from_layer1`` guards every one of its
    five instruments, and the tightening must leave it alone. If the analysis ever convicts
    it, the gate has started manufacturing false accusations against correct code — which is
    how a control gets muted, and a muted control is worse than the silence it replaced."""
    path, _fn = renderer_source(_LIVE_SITE)
    assert not _analyse_source(path.read_text(encoding="utf-8"), "_caveat_from_layer1")


def test_a_dead_mention_no_longer_excuses_the_live_renderer() -> None:
    """THE EXPLOIT, reproduced against the real file rather than a fixture.

    The first cut of the analysis collected every name appearing ANYWHERE in the function, so
    one dead ``_dead = reg.measured`` let BOTH of ``card.py``'s real guards be deleted with the
    gate still green. That is not a hypothetical: it was demonstrated on this exact renderer,
    and it is why a mention check was worse than no check — it certified the collapse.

    The mutation is applied to a COPY in memory; the file on disk is never touched."""
    path, _fn = renderer_source(_LIVE_SITE)
    src = path.read_text(encoding="utf-8")
    assert ".measured and " in src, (
        "card.py no longer uses the `<instrument>.measured and <claim>` form this exploit "
        "deletes; re-point this test at the arrangement it does use"
    )

    # Every guard mentioned but nothing guarded — the innocent-looking shape.
    mentions = ("\n    _dead = (reg.measured, seed.measured, layer1.dead_scaffold.measured,\n"
                "             layer1.stale_readme.measured, layer1.no_entry_point.measured)\n")
    exploited = src.replace(
        "    reg = layer1.regression\n",
        "    reg = layer1.regression\n    seed = layer1.seed_divergence\n" + mentions)
    assert exploited != src, "the exploit could not be injected - the renderer was restructured"
    exploited = re.sub(r"[\w.]+\.measured and ", "", exploited)

    defects = _analyse_source(exploited, "_caveat_from_layer1")
    assert defects, "the dead-mention exploit was ACQUITTED on live renderer code"
    # every instrument whose guard was deleted is convicted BY NAME, not just one of them
    for claim in ("reg.regressed", "reg.changed", "seed.flagged",
                  "layer1.dead_scaffold.flagged", "layer1.stale_readme.flagged",
                  "layer1.no_entry_point.flagged"):
        assert any(f"`{claim}`" in d for d in defects), (claim, defects)


# ---------------------------------------------------------------------------
# The analysis's own blind spot, refused rather than tolerated
# ---------------------------------------------------------------------------

_ALIASED_GUARD_INSTRUMENT = '''
"""The one shape this analysis CANNOT read: the guard is bound to a local name first."""
from dataclasses import dataclass, field


@dataclass
class ProbeResult:
    findings: list = field(default_factory=list)
    files_scanned: int = 0
    measured: bool = False

    def summary(self) -> str:
        ok = self.measured
        if ok and self.findings:
            return f"{len(self.findings)} finding(s)"
        return "clean"


def run_probe(path):
    return ProbeResult(findings=[], measured=True)
'''


def test_an_aliased_guard_is_refused_by_name_not_silently_convicted(tmp_path: Path) -> None:
    """A guard bound to a local name is a REAL guard the path-scoped analysis cannot see.

    Convicting it would be a false accusation out of a control whose entire product is
    certification, and tracing it would mean a dataflow approximation that errs toward
    ACQUITTAL — the original defect in a subtler shape. So it is refused: the gate fails, and
    the message names the two honest responses (inline the guard, or argue the collapse).

    The docstring of ``guarding_expressions`` used to assert instead that no alias existed in
    the tree — a claim about one day's state of the world that a docstring cannot keep true
    and no reader can check. This test is what replaced it."""
    module = _write_module(tmp_path, "blarai_aliased_guard_1223", _ALIASED_GUARD_INSTRUMENT)
    entry = _synthetic_entry(module)

    defects = _defects_of(entry)
    assert defects, "an aliased guard passed silently - the analysis cannot read it"
    assert any("binds this instrument's status to a local name" in d for d in defects), defects
    assert any("JUSTIFIED_COLLAPSES" in d for d in defects), defects


def test_no_registered_renderer_aliases_a_guard() -> None:
    """THE LIVE SWEEP: today's tree must be readable by the analysis that judges it.

    Runs over every registered renderer, so the day someone writes ``ok = f.measured`` in one,
    the gate says so here instead of the sweep quietly reporting a collapse that is not
    there."""
    aliased: list[str] = []
    for entry in REGISTRY:
        for site in entry.renderers:
            _path, fn = renderer_source(site)
            aliased.extend(f"{site} {d}" for d in guard_alias_reads(fn, entry))
    assert not aliased, (
        "a registered renderer binds an instrument's status to a local name, which the "
        "path-scoped guard analysis cannot follow:\n  - " + "\n  - ".join(aliased)
    )


def test_a_receiver_alias_is_still_followed(tmp_path: Path) -> None:
    """The distinction that keeps the refusal above narrow enough to live with.

    ``reg = layer1.regression`` binds an INSTRUMENT, not its status, and every renderer in this
    tree does it — ``card.py`` opens with exactly that line. Only a binding of the STATUS is
    refused. If this test starts failing, the refusal has widened into a ban on the house
    idiom and will be deleted rather than worked around."""
    module = _write_module(tmp_path, "blarai_receiver_alias_1223", _SOUND_INSTRUMENT)
    entry = _synthetic_entry(module)
    _path, fn = renderer_source(f"{module}:ProbeResult.summary")
    assert guard_alias_reads(fn, entry) == []

    live_path, live_fn = renderer_source(_LIVE_SITE)
    assert "reg = layer1.regression" in live_path.read_text(encoding="utf-8")
    for e in REGISTRY:
        if _LIVE_SITE in e.renderers:
            assert guard_alias_reads(live_fn, e) == []


def test_a_conviction_test_cannot_pass_on_a_module_that_never_loaded() -> None:
    """THE BACKSTOP, driven directly, because it is the only part of this that is
    deterministic.

    Point an entry at a module nobody wrote. The audit returns two ``does not resolve``
    defects, which is TRUTHY — so every ``assert defects`` conviction test in this file would
    pass, having proved nothing about the analysis it names. :func:`_defects_of` is what
    stands between that and a green suite, so it is proved here against the exact input rather
    than assumed from its own docstring.

    This is the same shape as the instruments the registry governs, one level up: a check that
    could not run must not be readable as a check that ran and agreed."""
    entry = _synthetic_entry("blarai_module_that_was_never_written_1223")

    (_e, raw), = audit([entry])
    assert raw, "the premise failed: an unimportable module produced no defects at all"
    assert all("does not resolve" in d for d in raw), raw

    with pytest.raises(AssertionError, match="never loaded"):
        _defects_of(entry)
