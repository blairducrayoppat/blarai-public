"""The behaviour-smoke CONTRACT: the plan declares what the headless capture must exercise.

WHAT THIS LOCKS. ``capture-web-cdp.mjs`` has always been able to read a declared behaviour spec
from ``<app-dir>/blarai-smoke.json`` — and nothing in either repo ever wrote that file. So the
declared arm was unreachable on every web build ever done: the capture fell back to a heuristic
("first visible enabled control") whose failures are a soft note rather than a finding. This is the
built-but-wired-into-nothing shape the testing doctrine names, and the tests below are written in
the two directions that shape demands:

* the contract is PRODUCED by the plan, threaded to the dispatch, materialised as bytes the capture
  can read, and REACHABLE from the live entry points that run it; and
* ABSENCE is still legal — a plan with no contract produces task dicts, wire payloads and a
  delivery byte-identical to before, with the capture on exactly today's heuristic path.

A control that is not tested OFF cannot be distinguished from one the test cannot reach, so the
off-direction is tested as deliberately as the on-direction.
"""

from __future__ import annotations

import inspect
import json
import re
import time
from dataclasses import replace

import pytest

from shared.fleet import acceptance as acc
from shared.fleet import swap_driver as sd

# A plan emission the 14B would produce for an interactive page, and the build_plan that gates it.
_EMISSION = json.dumps([{"action": "the Calculate button", "result": "the total below the form"}])
_WEB_PLAN = {"surface": "web"}


def _gen(_prompt: str) -> str:
    return _EMISSION


# ---------------------------------------------------------------------------
# Derivation — the model names the control, the RULER owns the selectors
# ---------------------------------------------------------------------------


def test_a_web_plan_produces_a_contract_with_ruler_owned_selectors():
    spec = acc._smoke_spec_from_plan("a tip calculator", _WEB_PLAN, generate_fn=_gen)
    assert spec is not None
    # The selectors are NOT the model's: a selector invented at plan time describes code that does
    # not exist yet, so it would name a control the coder had no reason to build.
    assert spec["click"] == acc.SMOKE_CLICK_SELECTOR
    assert spec["expectDelta"] == acc.SMOKE_DELTA_SELECTOR
    assert spec["actionLabel"] == "the Calculate button"
    assert spec["resultLabel"] == "the total below the form"


@pytest.mark.parametrize("surface", ["desktop-gui", "mobile", "command-line", "library", "unknown"])
def test_only_web_gets_a_contract(surface):
    """desktop-gui/mobile are VISUAL (they take image-asset specs) but never reach the headless
    browser capture, so a contract for them would be a check nothing can run."""
    assert acc._smoke_spec_from_plan("x", {"surface": surface}, generate_fn=_gen) is None
    assert acc._smoke_spec_from_plan("x", None, generate_fn=_gen) is None


def test_a_static_page_declares_no_contract_and_that_is_the_correct_answer():
    """The model's empty-array answer means "nothing here to press". It must yield no contract —
    a brochure page forced to grow a primary action would burn a fix cycle on a false defect."""
    assert acc._smoke_spec_from_plan("about my pottery", _WEB_PLAN, generate_fn=lambda _p: "[]") is None


@pytest.mark.parametrize("emission", [
    "not json at all",
    "[]",
    "[{}]",
    '[{"action": "ok"}]',                    # half a contract is no contract
    '[{"action": "a", "result": "the out"}]',  # 'a' is below the vacuous-label floor
    '[{"action": "  ", "result": "  "}]',
    "{}",
])
def test_a_garbage_emission_yields_no_contract_never_a_half_one(emission):
    assert acc._smoke_spec_from_plan("x", _WEB_PLAN, generate_fn=lambda _p: emission) is None


def test_a_raising_model_never_crashes_the_plan():
    def boom(_prompt):
        raise RuntimeError("GPU fell over")

    assert acc._smoke_spec_from_plan("x", _WEB_PLAN, generate_fn=boom) is None


def test_the_grammar_hook_is_tried_first_and_falls_back_soft():
    seen: list[str] = []
    spec = acc._smoke_spec_from_plan(
        "x", _WEB_PLAN, generate_fn=lambda _p: (seen.append("free"), _EMISSION)[1],
        structured_generate_fn=lambda _p, _s: _EMISSION,
    )
    assert spec is not None and seen == []          # the free-text path was never reached
    # A grammar hook that raises must be indistinguishable from one that is absent.
    spec2 = acc._smoke_spec_from_plan(
        "x", _WEB_PLAN, generate_fn=_gen,
        structured_generate_fn=lambda _p, _s: (_ for _ in ()).throw(RuntimeError("no grammar")),
    )
    assert spec2 is not None and spec2["actionLabel"] == "the Calculate button"


# ---------------------------------------------------------------------------
# Selector validation — the wire boundary (principle 7: validate before trust)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("good", [
    '[data-blarai-action="primary"]', "#chart", ".results", "div", "div > .out", "button.primary#go",
])
def test_the_selector_allowlist_admits_the_shapes_a_contract_needs(good):
    assert acc.is_valid_smoke_selector(good) is True


@pytest.mark.parametrize("bad", [
    "a,b",                      # a selector LIST would let one garbled half hide behind a working one
    "button:hover",             # pseudo-class
    ":has(.x)",                 # functional notation
    '[onerror="alert(1)"]',
    "x" * 200,
    "", "   ", None, 42, ["#x"],
])
def test_the_selector_allowlist_denies_everything_else(bad):
    assert acc.is_valid_smoke_selector(bad) is False


@pytest.mark.parametrize("pathological", [
    "a" * 119 + "!",            # longest input the cap admits, near-missing at the very end
    "[" + "a" * 118 + "!",      # an attribute selector that never reaches its `="`
    "a>" * 59 + "!",            # maximal child-combinator chain
    "a " * 59 + "!",            # maximal descendant-combinator chain
])
def test_a_rejected_selector_cannot_wedge_the_thread_that_validates_it(pathological):
    """REGRESSION LOCK on catastrophic backtracking.

    The allowlist used to be ONE regex —
    ``(?:…|[a-zA-Z][a-zA-Z0-9]*)+(?:(?:\\s*>\\s*|\\s+)(?:…|[a-zA-Z][a-zA-Z0-9]*)+)*`` — a nested
    quantifier over an alternation whose last branch matches a bare run of letters. Measured on
    this box: 0.077 s at 20 characters, 1.15 s at 24, 65.7 s at 30 and 958.5 s at 34, roughly 4x
    per two more characters. :data:`_SMOKE_SELECTOR_MAX` is 120 — about ninety characters PAST
    the point of no return — so the cap the design leaned on bounded nothing.

    Reachable, and the validator's own docstring says why: it sits at the WIRE boundary, where a
    ``from_dict`` payload is untrusted input. ``_coerce_smoke_spec`` is reached from
    ``AcceptanceSpec.from_dict``, which the gateway's dispatch coordinator and transport call on
    IPC and on dispatch-state RESTORE. A stored record whose ``spec.smoke_spec.click`` is forty
    junk letters would wedge the restoring thread — and every caller's ``try/except Exception``
    is UNREACHABLE against a hang, because no error path is ever taken. Fail-closed is not merely
    bypassed by this, it is unreachable.

    A REAL time bound, not a shape assertion: an implementation that reintroduces the nesting
    fails here even while admitting exactly the same language."""
    started = time.perf_counter()
    assert acc.is_valid_smoke_selector(pathological) is False
    elapsed = time.perf_counter() - started
    assert elapsed < 0.25, (
        f"rejecting a {len(pathological)}-character selector took {elapsed:.3f} s — the validator "
        "is backtracking again, and the cap does not bound it")


def test_the_two_repos_admit_ONE_language_and_the_ascii_classes_prove_it():
    """The Python and JavaScript validators must accept exactly the same selectors.

    They did not. ``\\w`` is UNICODE-AWARE in Python and ASCII-only in JavaScript, so this side
    admitted a strict superset — a selector the ruler could mint and the capture would refuse,
    invisible until a non-ASCII identifier appeared. Both sides now spell the classes out, which
    is why these are refused HERE as well.

    The lock has two halves on purpose. The behavioural half is below; the TEXTUAL half lives in
    :func:`test_the_capture_mirrors_this_module_s_selector_grammar_and_status_vocabulary`, which
    compares the two pattern sources directly — a behavioural test alone can only sample the
    language, while the sources being equal settles it."""
    for non_ascii in ("café", "#café", ".café", '[data-é="x"]',
                      '[data-x="café"]', "中文"):
        assert acc.is_valid_smoke_selector(non_ascii) is False, (
            f"{non_ascii!r} is admitted here and refused by capture-web-cdp.mjs")
    # ...and the ASCII language is unchanged, in BOTH directions.
    for good in ("form div.card > span#out", '[data-x="a b-c_1"]', "a>b", "a >b", 'a[b="c"]d'):
        assert acc.is_valid_smoke_selector(good) is True
    # A trailing combinator is refused — but note that BOTH sides strip first, so "a b " is the
    # valid "a b" on both and is not a case that tells them apart.
    for bad in (">a", "a>", "#1bad", "a > ", "a >> b"):
        assert acc.is_valid_smoke_selector(bad) is False


def test_a_forged_wire_payload_is_refused_whole_not_repaired():
    """The contract crosses ``to_dict``/``from_dict`` and the gateway IPC, and its value ends up in
    a browser's ``document.querySelector``. A payload with one bad half is dropped ENTIRELY —
    repairing it would send the capture hunting for a selector the coder was never told about."""
    assert acc._coerce_smoke_spec(None) is None
    assert acc._coerce_smoke_spec({"click": "button:hover", "expectDelta": "#out",
                                   "actionLabel": "go", "resultLabel": "out"}) is None
    assert acc._coerce_smoke_spec({"click": "#go", "expectDelta": "a,b",
                                   "actionLabel": "go", "resultLabel": "out"}) is None
    assert acc._coerce_smoke_spec({"click": "#go", "expectDelta": "#out"}) is None  # labels missing


def test_labels_are_hygiened_before_they_reach_a_prompt_or_a_finding():
    spec = acc._coerce_smoke_spec({
        "click": "#go", "expectDelta": "#out",
        "actionLabel": 'the "Go"\nbutton\x00', "resultLabel": "the  out" + "!" * 200,
    })
    assert spec is not None
    assert spec["actionLabel"] == "the Go button"          # quotes, control chars, newlines gone
    assert len(spec["resultLabel"]) <= 80                  # capped


# ---------------------------------------------------------------------------
# Round-trip + threading — and the OFF direction at every hop
# ---------------------------------------------------------------------------


def _spec_with_contract() -> acc.AcceptanceSpec:
    base = acc.AcceptanceSpec(goal="a tip calculator", build_plan=dict(_WEB_PLAN))
    return replace(base, smoke_spec=acc._smoke_spec_from_plan(
        "a tip calculator", _WEB_PLAN, generate_fn=_gen))


def test_the_contract_survives_the_wire_round_trip():
    spec = _spec_with_contract()
    back = acc.AcceptanceSpec.from_dict(spec.to_dict())
    assert back.smoke_spec == spec.smoke_spec


def test_OFF_a_contract_less_spec_emits_no_key_at_all():
    """Byte-identical to pre-contract payloads — the conditional emit, not a null."""
    d = acc.AcceptanceSpec(goal="g", build_plan={"surface": "command-line"}).to_dict()
    assert "smoke_spec" not in d
    assert acc.AcceptanceSpec.from_dict(d).smoke_spec is None
    # A payload that predates the field entirely reconstructs as None, never as a half-contract.
    assert acc.AcceptanceSpec.from_dict({"goal": "g"}).smoke_spec is None


def test_the_contract_is_threaded_identically_onto_every_task():
    spec = _spec_with_contract()
    tasks = acc._thread_build_fields(
        [{"repo": "R", "task": "a", "prompt": "p"}, {"repo": "R", "task": "b", "prompt": "q"}], spec)
    stamped = [t["smoke_spec_json"] for t in tasks]
    assert stamped[0] == stamped[1]                       # one authority, stamped once
    assert acc.decode_smoke_spec(tasks) == spec.smoke_spec


def test_OFF_no_contract_leaves_the_task_dicts_byte_identical():
    plain = acc.AcceptanceSpec(goal="g", build_plan={"surface": "web"})
    tasks = acc._thread_build_fields([{"repo": "R", "task": "a", "prompt": "p"}], plain)
    assert "smoke_spec_json" not in tasks[0]
    assert acc.decode_smoke_spec(tasks) is None
    assert acc.decode_smoke_spec([{"repo": "R", "task": "a", "prompt": "p"}]) is None


def test_decode_is_fail_closed_on_a_poisoned_stamp():
    assert acc.decode_smoke_spec([{"smoke_spec_json": "not json"}]) is None
    poisoned = json.dumps({"click": "a,b", "expectDelta": "#o", "actionLabel": "x", "resultLabel": "y"})
    assert acc.decode_smoke_spec([{"smoke_spec_json": poisoned}]) is None


# ---------------------------------------------------------------------------
# The file the capture actually reads
# ---------------------------------------------------------------------------


def test_the_file_bytes_are_stable_and_carry_the_whole_contract(tmp_path):
    spec = _spec_with_contract().smoke_spec
    assert acc.write_smoke_spec_file(tmp_path, spec) is True
    written = tmp_path / acc.SMOKE_SPEC_FILENAME
    payload = json.loads(written.read_text(encoding="utf-8"))
    assert payload["click"] == acc.SMOKE_CLICK_SELECTOR
    assert payload["expectDelta"] == acc.SMOKE_DELTA_SELECTOR
    assert payload["actionLabel"] and payload["resultLabel"]
    # Stable bytes are what make the driver's pre-capture re-write a NO-OP on an untampered tree
    # (no spurious diff in the coder's worktree) and a RESTORE on a tampered one.
    assert acc.smoke_spec_file_bytes(spec) == acc.smoke_spec_file_bytes(spec)
    assert written.read_bytes() == acc.smoke_spec_file_bytes(spec)


def test_OFF_no_contract_writes_no_file_at_all(tmp_path):
    assert acc.write_smoke_spec_file(tmp_path, None) is False
    assert acc.smoke_spec_file_bytes(None) is None
    assert not (tmp_path / acc.SMOKE_SPEC_FILENAME).exists()
    # An invalid contract is refused rather than written half-formed.
    assert acc.write_smoke_spec_file(tmp_path, {"click": "a,b", "expectDelta": "#o"}) is False
    assert not (tmp_path / acc.SMOKE_SPEC_FILENAME).exists()


def test_a_write_failure_is_fail_soft_never_a_raise(tmp_path):
    """The write sits on the pre-swap path and the pre-capture path; neither may be derailed."""
    blocked = tmp_path / "not-a-dir"
    blocked.write_text("i am a file", encoding="utf-8")
    assert acc.write_smoke_spec_file(blocked, _spec_with_contract().smoke_spec) is False


# ---------------------------------------------------------------------------
# The tamper lock — the plan is the authority, not the candidate's copy
# ---------------------------------------------------------------------------


def _pin_driver(tmp_path, tasks):
    """A driver whose side effects are all injected — the pin is pure filesystem work, so nothing
    here needs to be real."""
    ops = sd.SwapOps(
        available_gb=lambda: 26.0, backend_alive=lambda: False, load_30b=lambda: True,
        wait_ready=lambda: True, run_task=lambda _t: None, cancel_requested=lambda: False,
        disarm_watchdog=lambda: None, stop_ovms=lambda: None,
        write_report=lambda _r, _o: None, restart_launcher=lambda: None,
        backend_ready=lambda: True, signal_failure=lambda _m: None,
    )
    return sd.SwapDriver(
        run_id="R1", session_id="s1", tasks=tasks,
        swap_state_path=tmp_path / "swap.json",
        ops=ops, gate_gb=21.0, sleep=lambda _s: None,
    )


def test_the_driver_restores_the_plans_bytes_over_a_tampered_contract(tmp_path):
    """The contract is seeded into the tree the CODER writes to, so a candidate could edit the exam
    it is about to sit — the self-written-exam problem this project already fixed elsewhere. The
    plan's bytes are written back at the last possible moment before the capture reads them."""
    spec = _spec_with_contract()
    tasks = acc._thread_build_fields([{"repo": str(tmp_path), "task": "a", "prompt": "p"}], spec)
    target = tmp_path / acc.SMOKE_SPEC_FILENAME
    # A candidate points the check at something trivially clickable that always "changes".
    target.write_text(json.dumps({"click": "body", "expectDelta": "body",
                                  "actionLabel": "x", "resultLabel": "y"}), encoding="utf-8")

    _pin_driver(tmp_path, tasks)._pin_smoke_contract(str(tmp_path))

    assert target.read_bytes() == acc.smoke_spec_file_bytes(spec.smoke_spec)
    assert json.loads(target.read_text(encoding="utf-8"))["click"] == acc.SMOKE_CLICK_SELECTOR


def test_the_pin_is_a_no_op_on_an_untampered_tree(tmp_path):
    spec = _spec_with_contract()
    tasks = acc._thread_build_fields([{"repo": str(tmp_path), "task": "a", "prompt": "p"}], spec)
    acc.write_smoke_spec_file(tmp_path, spec.smoke_spec)
    before = (tmp_path / acc.SMOKE_SPEC_FILENAME).read_bytes()
    _pin_driver(tmp_path, tasks)._pin_smoke_contract(str(tmp_path))
    assert (tmp_path / acc.SMOKE_SPEC_FILENAME).read_bytes() == before


def test_OFF_the_pin_writes_nothing_when_the_plan_declared_no_contract(tmp_path):
    tasks = [{"repo": str(tmp_path), "task": "a", "prompt": "p"}]
    _pin_driver(tmp_path, tasks)._pin_smoke_contract(str(tmp_path))
    assert not (tmp_path / acc.SMOKE_SPEC_FILENAME).exists()
    # An empty app dir is a no-op too, and never a raise.
    _pin_driver(tmp_path, tasks)._pin_smoke_contract("")


# ---------------------------------------------------------------------------
# REACHABILITY — the failure this whole change exists to retire
# ---------------------------------------------------------------------------


def test_the_pin_is_actually_called_before_both_captures():
    """A control nothing calls is the exact defect being fixed here: ``readSmokeSpec`` existed for
    months and no writer ever ran. So assert the CALL SITES, not just the function."""
    exec_src = inspect.getsource(sd.SwapDriver._exec_smoke)
    assert "_pin_smoke_contract" in exec_src, (
        "the executability floor's web arm drives the same headless capture and must get the "
        "plan's contract bytes")
    design_src = inspect.getsource(sd.SwapDriver._design_phase)
    assert "_pin_smoke_contract" in design_src, (
        "the design loop is where the behaviour smoke has teeth; without the pin here a coder's "
        "edit survives into the capture that grades it")


def test_the_ao_seeds_the_contract_into_the_baseline_before_the_swap():
    """The coder can only be TOLD about the contract if the file is in the baseline its worktree
    is branched from. Locks that the seam exists AND that the EXECUTE path calls it."""
    from services.assistant_orchestrator.src import entrypoint as ep

    svc = ep.AssistantOrchestratorService
    assert getattr(svc, "_maybe_seed_smoke_contract", None) is not None, (
        "the AO smoke-contract seam is gone")
    callers = [
        name for name, fn in inspect.getmembers(svc, predicate=inspect.isfunction)
        if name != "_maybe_seed_smoke_contract"
        and "_maybe_seed_smoke_contract" in inspect.getsource(fn)
    ]
    assert callers, (
        "_maybe_seed_smoke_contract is defined but nothing calls it — built-but-wired-into-nothing, "
        "the exact shape this change exists to retire")


def _capture_source() -> str:
    """The installed fleet's ``capture-web-cdp.mjs``, or a skip when it is not on this box.

    Resolved through the operator override first — the same SSOT
    :func:`shared.fleet.dispatch.resolve_fleet_root` is used everywhere, and the idiom
    ``shared/tests/test_fleet_dedup_guard.py`` already follows — so a cross-repo branch PAIR can be
    checked before either half merges by pointing ``BLARAI_FLEET_AGENTIC_SETUP_DIR`` at the sibling
    worktree. Read from the WORKING TREE, which is the point: these gates answer "has the paired
    half landed", and a pin a pre-change tree already satisfies answers nothing."""
    from shared.fleet.dispatch import (
        FLEET_AGENTIC_SETUP_DIR_ENV,
        build_default_config,
        resolve_fleet_root,
    )

    # INSTALLED scripts, derived from queue_path: since #1181a ``scripts_dir`` follows a live
    # run's pin while queue/runs stay on the state root, so reading scripts_dir here would
    # point this cross-repo gate at a MEASURED worktree during any pinned battery — and a tree
    # predating the paired half turns the gate's answer into a SKIP, breaking the 0-skips bar
    # for a reason that has nothing to do with the contract it checks.
    cfg = build_default_config(resolve_fleet_root(FLEET_AGENTIC_SETUP_DIR_ENV) or None)
    scripts = cfg.queue_path.parent.parent / "scripts"
    capture = scripts / "capture-web-cdp.mjs"
    if not capture.exists():
        pytest.skip(f"fleet capture helper not present at {capture} (sibling repo absent)")
    return capture.read_text(encoding="utf-8", errors="replace")


def test_the_capture_reads_the_same_filename_and_field_names_this_module_writes():
    """A cross-repo pin on the SHARED CONTRACT. The writer lives here and the reader lives in
    agentic-setup, so a rename on either side would silently disable the check — the same seam class
    the WinUI passthrough-allowlist gate parses the C# for.

    EVERY pin here must be a symbol that exists ONLY once the paired half has landed, because a gate
    that a pre-change sibling already satisfies cannot report the one failure it is for. The version
    that shipped first asserted two of the four field names and matched them with
    ``f".{field}" in src`` — ``.click`` matched the pre-existing heuristic path's ``el.click()``, and
    both ``'blarai-smoke.json'`` and ``spec.click`` were already on the sibling's main. It passed with
    the paired half unmerged, which is precisely the state it existed to detect. Note the direction
    of the cost: this gate is RED between the two merges, deliberately — a cross-repo change is not
    landed until both halves are, and that is the honest reading.

    Skips (never fails) if the sibling repo is not on this box."""
    src = _capture_source()
    assert f"'{acc.SMOKE_SPEC_FILENAME}'" in src, (
        f"capture-web-cdp.mjs does not read {acc.SMOKE_SPEC_FILENAME} — the writer and the reader "
        "have drifted apart and the declared check is silently dead")
    # All FOUR fields, matched where the reader actually consumes them off the parsed JSON. `raw.`
    # is the object readSmokeSpec parsed from the file; nothing in the heuristic path spells these.
    for field in ("click", "expectDelta", "actionLabel", "resultLabel"):
        assert f"raw.{field}" in src, (
            f"capture-web-cdp.mjs no longer reads the '{field}' field this module writes — the two "
            "halves of the contract have drifted, or the paired branch has not landed")
    assert "isValidSmokeSelector" in src, (
        "capture-web-cdp.mjs has no selector validator: the value this module writes reaches "
        "document.querySelector unvalidated on the reader's side")


def test_the_capture_mirrors_this_module_s_status_vocabulary_and_selector_grammar():
    """D1 — the two repos' SHARED VOCABULARY, parsed rather than trusted.

    ``SMOKE_STATUSES``'s own comment says "a value outside this set is a cross-repo drift signal".
    Nothing kept that promise: the set was a hand-maintained copy of eight ``export const SMOKE_*``
    declarations in a file in another repository. The house already parses a sibling for exactly
    this (``shared/tests/test_fleet_script_agreement.py``, and the WinUI passthrough gate reading a
    C# array), so this does the same — set EQUALITY in both directions, because a status the capture
    can emit and this side does not know is the drift the comment names, and a status this side
    expects and the capture cannot emit is dead vocabulary.

    The selector grammar is pinned the same way and for a sharper reason: the two validators must
    admit ONE language. Python's ``\\w`` is Unicode-aware and JavaScript's is ASCII, so the two
    patterns were NOT equivalent — this side admitted a strict superset. Both now spell the ASCII
    classes out, and comparing the pattern SOURCES settles the equivalence where a behavioural test
    could only sample it."""
    from shared.fleet import swap_ops

    src = _capture_source()

    exported = {m.group(1) for m in re.finditer(
        r"^export const SMOKE_[A-Z_]+ = '([a-z-]+)';", src, re.MULTILINE)}
    assert exported, (
        "no `export const SMOKE_* = '…'` declarations found in capture-web-cdp.mjs — the parse "
        "shape drifted, and a gate that silently matches nothing passes for the wrong reason")
    assert exported == set(swap_ops.SMOKE_STATUSES), (
        "the capture's status vocabulary and SMOKE_STATUSES have drifted.\n"
        f"  only in capture-web-cdp.mjs: {sorted(exported - set(swap_ops.SMOKE_STATUSES))}\n"
        f"  only in swap_ops.py:         {sorted(set(swap_ops.SMOKE_STATUSES) - exported)}")

    grammar = re.search(r"^const _CSS_SIMPLE = '(.*)';$", src, re.MULTILINE)
    assert grammar, (
        "capture-web-cdp.mjs no longer declares `_CSS_SIMPLE` — the selector allowlists cannot be "
        "compared, so nothing keeps the two repos admitting the same language")
    # A JS single-quoted literal: the only escape it carries is a doubled backslash.
    assert grammar.group(1).replace("\\\\", "\\") == acc._CSS_SIMPLE_SELECTOR, (
        "the selector allowlists have drifted. A selector one repo mints and the other refuses "
        "disables the declared check on whichever side lost, silently")
