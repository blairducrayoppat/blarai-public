"""#1474 — the job oracle must never import what the runtime cannot import.

**The measured failure.** On the operator's first real website dispatch
(run ``20260830-225825-bd``, 2026-08-30) the authored job exam opened with::

    import { default as photoAndBio } from '../src/add-photo-and-bio-section/index.html';

Node throws ``ERR_UNKNOWN_FILE_EXTENSION`` on that at load, before a single assertion runs,
so the exam was unpassable by construction. That alone would only have wasted a grade.

The damage was larger: the job oracle's import contract is **surfaced to every task prompt**
("Job oracle import contract surfaced to every task: …" in the run journal), so a goal that
said ONE PAGE in capital letters was being instructed to build six separate
``src/<section>/index.html`` files. The exam corrupted the BUILD, not merely the report.

The honest outcome for a static web delivery is NO job oracle — the driver then records job
acceptance ``not-run``, which is never an implied pass, and the delivery is graded by the
instrument actually built for it (the served-page browser check) rather than by a module
import that was never going to resolve.
"""

from __future__ import annotations

from shared.fleet.acceptance import (
    AcceptanceCriterion,
    AcceptanceSpec,
    _node_contract_importable,
    generate_job_acceptance_oracle,
)

_NEVER_CALLED = "the model must not be asked to author an unrunnable exam"


def _web_spec() -> AcceptanceSpec:
    return AcceptanceSpec(
        goal="a one-page personal website",
        build_plan={"surface": "web"},
        criteria=(
            AcceptanceCriterion(
                id="c1", text="the page loads and shows every section",
                tier="behavior", check="open the served page",
            ),
        ),
    )


def _tasks(*creates_lists):
    return [
        {"task": f"t{i}", "prompt": "build it", "contract": {"creates": list(c)}}
        for i, c in enumerate(creates_lists)
    ]


# --- the predicate ---------------------------------------------------------------


def test_html_and_css_contracts_are_not_node_importable():
    """The exact contract shape from run 20260830-225825-bd."""
    assert not _node_contract_importable(
        {"creates": ["src/add-photo-and-bio-section/index.html"]}
    )
    assert not _node_contract_importable({"creates": ["styles/site.css"]})


def test_real_modules_are_importable_and_a_mixed_contract_still_counts():
    assert _node_contract_importable({"creates": ["src/parse.mjs"]})
    assert _node_contract_importable({"creates": ["src/app.js"]})
    # A page PLUS a module: the module is importable, so the contract is usable.
    assert _node_contract_importable({"creates": ["src/index.html", "src/app.mjs"]})


def test_json_is_deliberately_not_importable():
    """Importing JSON needs an import attribute the authored oracle does not emit, so
    counting it would re-open this hole one extension over."""
    assert not _node_contract_importable({"creates": ["data/pieces.json"]})


def test_a_contract_with_only_exports_keeps_todays_behaviour():
    """No creates path means no evidence either way; tightening it would regress node
    library jobs that never had this bug. Deliberately unchanged."""
    assert _node_contract_importable({"exports": ["parse(text)"]})


# --- the gate --------------------------------------------------------------------


def test_no_job_oracle_is_authored_for_an_html_only_node_job():
    """[kill] The whole point: a static site gets NO exam rather than an unrunnable one —
    and the model is never even asked, so no import contract can reach the task prompts."""
    def gen(_prompt: str) -> str:  # pragma: no cover - must not be reached
        raise AssertionError(_NEVER_CALLED)

    code, path = generate_job_acceptance_oracle(
        "a one-page personal website",
        _web_spec(),
        _tasks(["src/photo-bio/index.html"], ["src/certification/index.html"]),
        generate_fn=gen,
    )
    assert (code, path) == ("", "")


def test_a_node_job_that_does_declare_modules_still_gets_its_oracle():
    """[kill] The fix must not silence node library jobs, which is the regression a
    surface-wide 'no oracle for web' rule would have caused."""
    seen: list[str] = []

    def gen(prompt: str) -> str:
        seen.append(prompt)
        return (
            "import { test } from 'node:test';\n"
            "import assert from 'node:assert';\n"
            "import { parse } from '../src/parse.mjs';\n"
            "test('parses', () => { assert.ok(parse('x')); });\n"
        )

    code, path = generate_job_acceptance_oracle(
        "a text utility",
        _web_spec(),
        _tasks(["src/parse.mjs"], ["src/format.mjs"]),
        generate_fn=gen,
    )
    assert seen, "the author should have been invoked for an importable contract"
    assert code and path, "an importable node job must still get its exam"
