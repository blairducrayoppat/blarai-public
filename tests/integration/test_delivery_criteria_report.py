"""Locks on `tools/probes/delivery_criteria_report.py`.

The property under lock is NOT "the tool reads HTML". It is the pair of properties that
make the report safe to put in front of the operator:

    **1. Three deliveries that genuinely differ must not score the same.**
    **2. A criterion this instrument cannot decide must never render as satisfied.**

The first is the whole reason the probe exists. On 2026-08-16 the operator opened a
delivered site and found it failed four of his eight stated criteria (#1343); an
instrument that returns the same verdict profile for a good build and a broken one would
have told him nothing while appearing to answer. The second is #1241's discipline: an
absence rendered as a confident value is the defect, and "the check could not decide" is
an answer, not a placeholder for one.

The trees below are built on disk and driven through the real `load_delivery` /
`judge` / `main` entry points -- no mocked filesystem, no stubbed checks. They are
modelled on the three banked deliveries, whose REAL measured profiles are (measured
2026-08-17, `python tools/probes/delivery_criteria_report.py <stamp> --json`):

    20260816-070923  4 satisfied / 2 not satisfied / 2 not decidable  (c2 and c1 fail)
    20260816-210245  4 satisfied / 3 not satisfied / 1 not decidable  (c1, c5, c8 fail)
    20260817-070902  5 satisfied / 1 not satisfied / 2 not decidable  (c1 fails)

Those trees live outside this repository under `agentic-setup/state/operator-review`, so
they are reproduced in `tmp_path` here rather than depended upon: a lock that only runs
on one machine is not a lock. Each test states which way it fails if the property breaks.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

_TOOL = Path(__file__).resolve().parents[2] / "tools" / "probes" / "delivery_criteria_report.py"


def _load_module():
    """Import the probe by path -- `tools/` is not a package on the standard path."""
    spec = importlib.util.spec_from_file_location("delivery_criteria_report", _TOOL)
    assert spec is not None and spec.loader is not None, f"cannot load {_TOOL}"
    module = importlib.util.module_from_spec(spec)
    sys.modules["delivery_criteria_report"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def probe():
    assert _TOOL.is_file(), (
        f"{_TOOL} is missing. If the probe was moved or renamed, move this lock with it "
        "rather than deleting it -- the honesty property is the point, not the path."
    )
    return _load_module()


#: The operator's OWN eight sentences, copied verbatim from
#: `fleet-runs/20260816-134142-bd/acceptance.json`. They are reproduced rather than
#: paraphrased on purpose: the check registry matches on English prose, so a paraphrase
#: would test a sentence he never wrote and could stay green while the real ones stopped
#: matching any check.
CRITERIA: list[dict[str, str]] = [
    {
        "id": "c1",
        "text": (
            "The website should have a home page, a pieces list page, individual piece "
            "pages, and a contact page."
        ),
        "tier": "behavior",
        "check": "Verify that all four pages are accessible and load without error.",
    },
    {
        "id": "c2",
        "text": "All pages should have the same heading and menu at the top.",
        "tier": "visual",
        "check": (
            "Check that the header and navigation menu are consistent across all pages."
        ),
    },
    {
        "id": "c3",
        "text": (
            "The list of pieces and individual piece pages should pull data from a shared "
            "source."
        ),
        "tier": "behavior",
        "check": (
            "Update a piece's price in the data source and verify that the change is "
            "reflected on both the list and individual pages."
        ),
    },
    {
        "id": "c4",
        "text": "The pieces list should allow filtering by category (e.g., mugs or bowls).",
        "tier": "behavior",
        "check": (
            "Select a category filter and verify that only the relevant pieces are "
            "displayed."
        ),
    },
    {
        "id": "c5",
        "text": "The contact page should store submitted enquiries in a readable format.",
        "tier": "behavior",
        "check": "Submit a test enquiry and verify that it is stored in a log or database.",
    },
    {
        "id": "c6",
        "text": "The contact page should provide feedback if a user leaves a field blank.",
        "tier": "behavior",
        "check": (
            "Submit the contact form with missing fields and verify that appropriate error "
            "messages are displayed."
        ),
    },
    {
        "id": "c7",
        "text": "The website should launch without crashing.",
        "tier": "smoke",
        "check": (
            "Start the Node.js server and confirm that it runs without errors and the "
            "website is accessible."
        ),
    },
    {
        "id": "c8",
        "text": "The website should be visually consistent and clean.",
        "tier": "visual",
        "check": (
            "Review all pages for consistent styling, readable text, and proper alignment "
            "of elements."
        ),
    },
]

#: Placeholder names shaped like the real ones. The review directory is
#: `<stamp>-<project>` and the run is `<stamp>-bd`; a short placeholder would skip the
#: REVIEW.html pointer path entirely and quietly test only the weaker fallback join.
SITE = "20260817-000000-site"
RUN = "20260817-000000-bd"

_NAV = """  <header><nav><ul>
    <li><a href="home.html">Home</a></li>
    <li><a href="pieces.html">Pieces</a></li>
    <li><a href="contact.html">Contact</a></li>
  </ul></nav></header>"""

#: The same menu with ONE link changed. Two pages shipping these two menus is the real
#: inconsistency in delivery 20260816-070923: four pages point Home at `index.html` and
#: one points it at `home.html`.
_ODD_NAV = """  <header><nav><ul>
    <li><a href="index.html">Home</a></li>
    <li><a href="pieces.html">Pieces</a></li>
    <li><a href="contact.html">Contact</a></li>
  </ul></nav></header>"""


def _page(body: str, *, wrapper: bool = True) -> str:
    shell = '<div class="container">' if wrapper else "<div>"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>t</title>
<link rel="stylesheet" href="styles.css"></head>
<body>
{shell}
{body}
</div>
</body></html>
"""


def build_site(
    root: Path,
    *,
    link_detail: bool = True,
    layout_wrapper: bool = True,
    consistent_menu: bool = True,
    storage: str = "inline",  # "inline" | "dead-module" | "api" | "none"
    error_writes: int = 3,
    #: ALL FIVE controls carry `required` by default, because all twelve banked
    #: deliveries do (measured 2026-08-17). A fixture without it would be the easy
    #: shape rather than the real one.
    required_fields: bool = True,
    novalidate: bool = False,
    blur_validation: bool = False,
    #: Wrap the submit listener in a DOMContentLoaded listener, as two of the three
    #: banked deliveries do. Listener attribution has to take the INNERMOST span.
    nest_in_domcontentloaded: bool = True,
    #: The method the delivered server guards its route with. A server that answers only
    #: GET is not storing anything the contact form POSTs.
    server_method: str = "POST",
) -> Path:
    """Write a small delivered tree on disk. Every knob mirrors a real banked defect."""
    public = root / "public"
    (public / "data").mkdir(parents=True, exist_ok=True)

    (public / "styles.css").write_text(
        ".container { max-width: 60rem; }\n.filters { display: flex; }\n"
        ".filter-btn { padding: 2px; }\n.form-group { margin: 1rem; }\n"
        ".error { color: red; }\n",
        encoding="utf-8",
    )
    (public / "data" / "pieces.json").write_text(
        json.dumps([{"id": "1", "category": "mug", "price": 20}]), encoding="utf-8"
    )
    (public / "index.html").write_text(
        "<!doctype html><html><head><title>t</title></head><body>"
        "<script>window.location.href = 'home.html';</script></body></html>",
        encoding="utf-8",
    )
    (public / "home.html").write_text(
        _page(_NAV + "<h1>Studio</h1>", wrapper=layout_wrapper), encoding="utf-8"
    )

    detail_link = (
        '<a href="piece-detail.html?id=1" class="filter-btn">detail</a>' if link_detail else ""
    )
    (public / "pieces.html").write_text(
        _page(
            (_NAV if consistent_menu else _ODD_NAV)
            + f"""
  <div class="filters">
    <button class="filter-btn" data-filter="mug">Mugs</button>
    <button class="filter-btn" data-filter="bowl">Bowls</button>
  </div>
  <div id="grid">{detail_link}</div>
  <script>
    fetch('./data/pieces.json').then(r => r.json()).then(all => {{
      document.querySelectorAll('.filter-btn').forEach(b => b.addEventListener('click', () => {{
        const want = b.getAttribute('data-filter');
        render(all.filter(p => p.category === want));
      }}));
    }});
  </script>""",
            wrapper=layout_wrapper,
        ),
        encoding="utf-8",
    )
    (public / "piece-detail.html").write_text(
        _page(
            _NAV
            + """
  <div id="piece"></div>
  <script>fetch('./data/pieces.json').then(r => r.json()).then(render);</script>""",
            wrapper=layout_wrapper,
        ),
        encoding="utf-8",
    )

    errors = "\n".join(
        f"""      if (!document.getElementById('{f}').value.trim()) {{
        document.getElementById('{f}Error').textContent = '{f} is required';
        ok = false;
      }} else {{
        document.getElementById('{f}Error').textContent = '';
      }}"""
        for f in ["name", "email", "message", "subject", "phone"][:error_writes]
    )
    store = {
        "inline": "localStorage.setItem('enquiries', JSON.stringify(data));",
        "api": "fetch('/api/enquiries', {method: 'POST', body: JSON.stringify(data)});",
        "dead-module": "submitEnquiry(data);",
        "none": "",
    }[storage]
    script_tag = '<script src="enquiries.js"></script>' if storage == "dead-module" else ""
    if storage == "dead-module":
        # ES module syntax in a file the page loads as a CLASSIC script. The browser
        # discards the whole file, so `submitEnquiry` never exists.
        (public / "enquiries.js").write_text(
            "let enquiries = [];\n"
            "export function submitEnquiry(d) {\n"
            "  enquiries.push(d);\n"
            "  localStorage.setItem('enquiries', JSON.stringify(enquiries));\n"
            "}\n",
            encoding="utf-8",
        )
    req = " required" if required_fields else ""
    nv = " novalidate" if novalidate else ""
    # Real-time validation on `blur`, as delivery 20260817-070902 ships it. `blur` fires
    # whether or not the browser's constraint validation would pass, so these DO reach a
    # user who tabbed out of an empty box.
    blur = (
        "\n".join(
            f"""    document.getElementById('{f}').addEventListener('blur', function () {{
      if (!this.value.trim()) {{
        document.getElementById('{f}Error').textContent = '{f} is required';
      }} else {{
        document.getElementById('{f}Error').textContent = '';
      }}
    }});"""
            for f in ["name", "email", "message", "subject", "phone"][:error_writes]
        )
        if blur_validation
        else ""
    )
    submit_body = f"""    document.getElementById('contactForm').addEventListener('submit', function (e) {{
      e.preventDefault();
      let ok = true;
{errors}
      if (ok) {{
        const data = {{name: 1}};
        {store}
      }}
    }});"""
    if nest_in_domcontentloaded:
        submit_body = (
            "    document.addEventListener('DOMContentLoaded', function () {\n"
            + submit_body
            + "\n    });"
        )
    (public / "contact.html").write_text(
        _page(
            _NAV
            + f"""
  <form id="contactForm"{nv}>
    <input id="name"{req}><div id="nameError" class="error"></div>
    <input id="email"{req}><div id="emailError" class="error"></div>
    <textarea id="message"{req}></textarea><div id="messageError" class="error"></div>
    <input id="subject"{req}><div id="subjectError" class="error"></div>
    <input id="phone"{req}><div id="phoneError" class="error"></div>
    <button type="submit">Send</button>
  </form>
  {script_tag}
  <script>
{submit_body}
{blur}
  </script>""",
            wrapper=layout_wrapper,
        ),
        encoding="utf-8",
    )

    (root / "package.json").write_text(
        json.dumps({"scripts": {"start": "node src/server.js"}}), encoding="utf-8"
    )
    (root / "src").mkdir(exist_ok=True)
    # Shaped like the fleet's real web skeleton, which guards route AND method on one
    # line: `if (pathname === '/api/enquiries' && req.method === 'POST')`.
    route = "/api/enquiries" if storage == "api" else "/api/items"
    (root / "src" / "server.js").write_text(
        f"if (pathname === '{route}' && req.method === '{server_method}') "
        "return store(req.body);\n",
        encoding="utf-8",
    )
    return root


def _bank(tmp_path: Path, name: str, run_id: str, **kwargs: Any) -> tuple[Path, Path]:
    """A delivery under `operator-review/` plus the run whose acceptance.json owns it."""
    state = tmp_path / "state"
    delivery = state / "operator-review" / name
    delivery.mkdir(parents=True, exist_ok=True)
    build_site(delivery, **kwargs)
    (delivery / "REVIEW.html").write_text(
        f"<html><body><span>run <b>{run_id}</b></span></body></html>", encoding="utf-8"
    )
    run = state / "fleet-runs" / run_id
    run.mkdir(parents=True, exist_ok=True)
    (run / "acceptance.json").write_text(
        json.dumps({"repo": f"C:\\projects\\{name.split('-', 2)[-1]}", "spec": {"criteria": CRITERIA}}),
        encoding="utf-8",
    )
    return state, delivery


def _states(report: dict[str, Any]) -> dict[str, str]:
    return {c["id"]: c["state"] for c in report["criteria"]}


# --------------------------------------------------------------------------------------
# 1. The primary property: it must DISCRIMINATE
# --------------------------------------------------------------------------------------


def test_three_deliveries_that_differ_do_not_score_the_same(probe, tmp_path):
    """THE lock. A probe that scores every build alike is not measuring anything.

    The three trees below reproduce the three banked deliveries' distinguishing defects:
    layout applied everywhere but a menu that disagrees with itself; a dead module script
    swallowing the storage code and a layout class applied to nothing; and a build that
    gets both right. If a future change collapses the checks into something that always
    returns the same shape -- the easiest way for this report to become decoration -- the
    three profiles converge and this fails.
    """
    state_a, deliv_a = _bank(
        tmp_path / "a", "20260816-070923-site", "20260815-230306-bd", consistent_menu=False
    )
    state_b, deliv_b = _bank(
        tmp_path / "b",
        "20260816-210245-site",
        "20260816-134142-bd",
        layout_wrapper=False,
        storage="dead-module",
        link_detail=False,
    )
    state_c, deliv_c = _bank(
        tmp_path / "c", "20260817-070902-site", "20260816-230306-bd", link_detail=False
    )

    a = probe.build_report(deliv_a, state_a)
    b = probe.build_report(deliv_b, state_b)
    c = probe.build_report(deliv_c, state_c)

    profiles = [tuple(sorted(_states(r).items())) for r in (a, b, c)]
    assert len(set(profiles)) == 3, (
        "two or more of three genuinely different deliveries scored identically. "
        f"profiles: {[_states(r) for r in (a, b, c)]}"
    )

    # And the differences are the RIGHT ones, not incidental noise.
    assert _states(a)["c2"] == probe.NOT_SATISFIED, "a disagreeing menu was not caught"
    assert _states(c)["c2"] == probe.SATISFIED, "a consistent menu was called inconsistent"
    assert _states(b)["c5"] == probe.NOT_SATISFIED, "storage in a dead script was credited"
    assert _states(c)["c5"] == probe.SATISFIED, "working localStorage was not credited"
    assert _states(b)["c8"] == probe.NOT_SATISFIED, "a layout class applied to nothing passed"
    assert _states(a)["c1"] == probe.SATISFIED, "a fully linked site was called unreachable"
    assert _states(b)["c1"] == probe.NOT_SATISFIED, "an orphaned detail page was not found"


# --------------------------------------------------------------------------------------
# 2. The honesty property: the third state is mandatory
# --------------------------------------------------------------------------------------


def test_an_undecidable_criterion_never_renders_as_satisfied(probe, tmp_path):
    """"The website should launch without crashing" cannot be decided without launching.

    Fails if someone infers a green from a present start script -- which reads like a
    reasonable convenience and is exactly the absence-as-a-confident-value defect #1241
    exists to remove.
    """
    state, delivery = _bank(tmp_path, "20260817-000000-site", "20260817-000000-bd")
    report = probe.build_report(delivery, state)
    launch = next(c for c in report["criteria"] if c["id"] == "c7")

    assert launch["state"] == probe.NOT_DECIDABLE, (
        f"the launch criterion rendered {launch['state']!r} from a probe that starts no "
        "process. Only a run that executed the site can answer this."
    )
    assert any("starts no process" in e for e in launch["evidence"]), (
        "the report did not say WHY it cannot decide; an unexplained NOT DECIDABLE is "
        "indistinguishable from a broken check"
    )


def test_a_sentence_no_check_recognises_is_not_decidable(probe, tmp_path):
    """An unfamiliar requirement must fall through to NOT DECIDABLE, not to a guess.

    Fails if a future default sends unmatched criteria to SATISFIED (silently inflating
    every report) or to NOT SATISFIED (convicting a delivery of failing a check that was
    never run).
    """
    _, delivery = _bank(tmp_path, SITE, RUN)
    verdicts = probe.judge(
        probe.load_delivery(delivery),
        [{"id": "cX", "text": "The tone of the copy should suit a rural studio.", "tier": "human"}],
    )
    assert verdicts[0].state == probe.NOT_DECIDABLE
    assert verdicts[0].heuristic == "no-matching-check"


def test_a_judgement_criterion_can_never_be_satisfied_by_this_instrument(probe, tmp_path):
    """"Visually consistent and clean" is falsifiable, not confirmable -- deliberately.

    The visual check may return NOT SATISFIED (it found a dead layout wrapper) or NOT
    DECIDABLE (it found nothing, which proves nothing). If it ever returns SATISFIED, an
    instrument with no eyes has told the operator his site looks fine, which is the single
    most damaging thing this report could say.
    """
    for kwargs in ({}, {"layout_wrapper": False}, {"storage": "none"}, {"error_writes": 0}):
        state, delivery = _bank(tmp_path / str(hash(str(kwargs))), SITE, RUN, **kwargs)
        report = probe.build_report(delivery, state)
        visual = next(c for c in report["criteria"] if c["id"] == "c8")
        assert visual["state"] in (probe.NOT_SATISFIED, probe.NOT_DECIDABLE), (
            f"the visual criterion rendered {visual['state']!r} for delivery options "
            f"{kwargs}. This check has no confirming direction by design."
        )


def test_a_delivery_with_no_web_surface_declines_rather_than_convicting(probe, tmp_path):
    """Pointed at something that is not a static site, it must decline on every criterion.

    Fails if the checks report NOT SATISFIED for a tree with no HTML -- which would turn
    the probe into a machine for marking unfamiliar work as broken, and would be a false
    accusation rather than a missing measurement.
    """
    state = tmp_path / "state"
    delivery = state / "operator-review" / "20260817-000000-lib"
    (delivery / "src").mkdir(parents=True)
    (delivery / "src" / "thing.py").write_text("def f() -> int:\n    return 1\n", encoding="utf-8")
    run = state / "fleet-runs" / "20260817-000000-bd"
    run.mkdir(parents=True)
    (run / "acceptance.json").write_text(
        json.dumps({"repo": "x", "spec": {"criteria": CRITERIA}}), encoding="utf-8"
    )
    (delivery / "REVIEW.html").write_text("run <b>20260817-000000-bd</b>", encoding="utf-8")

    report = probe.build_report(delivery, state)
    assert report["tally"][probe.NOT_SATISFIED] == 0, (
        "a delivery with no HTML pages was convicted of failing web criteria: "
        f"{_states(report)}"
    )
    assert report["tally"][probe.NOT_DECIDABLE] == len(CRITERIA)


def test_criteria_that_cannot_be_read_produce_no_verdicts_and_say_so(probe, tmp_path):
    """No criteria means no verdicts. Fails if the report invents an empty pass.

    A report that printed "0 not satisfied" with nothing to judge would read as a clean
    bill of health, which is the same shape as reporting a zero from a check that never
    ran (#1342).
    """
    state = tmp_path / "state"
    delivery = state / "operator-review" / "20260817-000000-site"
    delivery.mkdir(parents=True)
    build_site(delivery)

    report = probe.build_report(delivery, state)
    assert report["criteria_count"] == 0
    assert report["criteria"] == [], "verdicts were produced with no criteria to judge"
    rendered = probe.render(report)
    assert "COULD NOT BE READ" in rendered
    assert "real outcome" in rendered, (
        "the report did not state that unreadable criteria are an outcome rather than a "
        "gap, so a reader could mistake the silence for a pass"
    )


# --------------------------------------------------------------------------------------
# 3. The two contract requirements from #1439
# --------------------------------------------------------------------------------------


def test_it_reports_with_no_exam_artifacts_anywhere(probe, tmp_path):
    """#1439's reason for existing: it must not be downstream of an exam.

    The run directory here holds acceptance.json and NOTHING else -- no traceability.json,
    no oracle, no scorecard, no smoke capture. That is the state of the runs where the
    operator was told nothing at all. Fails if a future change starts reading an exam
    artifact, because then this report goes silent on exactly the runs it was built for.
    """
    state, delivery = _bank(tmp_path, "20260817-000000-site", "20260817-000000-bd")
    run = state / "fleet-runs" / "20260817-000000-bd"
    assert [p.name for p in run.iterdir()] == ["acceptance.json"]

    report = probe.build_report(delivery, state)
    assert report["criteria_count"] == 8
    decided = report["tally"][probe.SATISFIED] + report["tally"][probe.NOT_SATISFIED]
    assert decided >= 5, (
        f"only {decided} of 8 criteria were decided with no exam present; the point of "
        "this probe is that the delivery alone is enough for most of them"
    )
    assert "delivered" in report["question"].lower() and "exam" in report["question"].lower(), (
        "the report does not state which of the two questions it answers, so it can be "
        "confused with requirement_coverage_report.py"
    )


def test_every_verdict_names_the_heuristic_that_produced_it(probe, tmp_path):
    """#1439 requirement 3: a reader must be able to discount a heuristic verdict.

    Fails if a check is added without a heuristic name, which is how a string match starts
    reading like a measurement.
    """
    state, delivery = _bank(tmp_path, "20260817-000000-site", "20260817-000000-bd")
    report = probe.build_report(delivery, state)
    rendered = probe.render(report)
    for crit in report["criteria"]:
        assert crit["heuristic"], f"{crit['id']} carries no heuristic name"
        assert crit["evidence"], f"{crit['id']} carries no evidence lines"
        assert crit["heuristic"] in rendered, (
            f"{crit['id']}'s heuristic {crit['heuristic']!r} is recorded but never printed"
        )


def test_it_is_advisory_and_exits_zero_even_when_everything_fails(probe, tmp_path, capsys):
    """#1439 requirement 5, and the operator's direction of 2026-08-16: report, never fail.

    Driven through `main` -- the real entry point a caller would use -- on the worst
    delivery the builder can make. Fails if a future change starts returning non-zero on
    findings, which would make this report a gate nobody agreed to.
    """
    state, delivery = _bank(
        tmp_path,
        "20260817-000000-site",
        "20260817-000000-bd",
        layout_wrapper=False,
        storage="none",
        error_writes=0,
        link_detail=False,
        consistent_menu=False,
    )
    code = probe.main(["--state-root", str(state), "--delivery-path", str(delivery)])
    out = capsys.readouterr().out
    assert code == 0, f"the probe failed the caller with exit {code} over its own findings"
    assert probe.NOT_SATISFIED in out, "the worst possible delivery produced no failure at all"
    assert "ADVISORY ONLY" in out


# --------------------------------------------------------------------------------------
# 4. The individual defects that were found by measuring, not by reasoning
# --------------------------------------------------------------------------------------


def test_storage_in_a_dead_module_script_is_not_credited(probe, tmp_path):
    """A file using `export` loaded by a classic `<script src>` never runs at all.

    This is the real defect in delivery 20260816-210245: working `localStorage.setItem`
    code sitting in a file the browser discards with a SyntaxError, so the enquiry goes
    nowhere. A probe that greps for the storage call and stops would call it satisfied.
    """
    state, delivery = _bank(
        tmp_path, "20260817-000000-site", "20260817-000000-bd", storage="dead-module"
    )
    report = probe.build_report(delivery, state)
    storage = next(c for c in report["criteria"] if c["id"] == "c5")

    assert storage["state"] == probe.NOT_SATISFIED, (
        "storage code the browser cannot load was credited as working storage"
    )
    assert any("enquiries.js" in e and "classic" in e for e in storage["evidence"]), (
        f"the report did not name the unloadable file; evidence was {storage['evidence']}"
    )


def test_a_post_to_a_route_the_server_does_not_serve_is_not_credited(probe, tmp_path):
    """Both directions. A POST to an implemented route counts; to a missing one it does not."""
    state_ok, deliv_ok = _bank(tmp_path / "ok", SITE, RUN, storage="api")
    assert _states(probe.build_report(deliv_ok, state_ok))["c5"] == probe.SATISFIED

    # Same client code, server route removed.
    (deliv_ok / "src" / "server.js").write_text("// no routes\n", encoding="utf-8")
    after = _states(probe.build_report(deliv_ok, state_ok))["c5"]
    assert after == probe.NOT_SATISFIED, (
        f"a form posting to a route no delivered server implements read as {after!r}"
    )


def test_a_route_served_only_for_the_wrong_method_is_not_credited(probe, tmp_path):
    """Found by the step-4 sweep for the blank-field blindness elsewhere in the registry.

    Matching the path alone is the same shape: the handler exists and the operation the
    page performs still cannot reach it. A server implementing only `GET /api/enquiries`
    would have been credited with storing his enquiries while every POST returned 404.

    Latent on real data when found -- the one banked delivery that posts to a route has a
    server guarding `req.method === 'POST'` -- and latent is not the same as safe.
    """
    state, delivery = _bank(tmp_path, SITE, RUN, storage="api", server_method="GET")
    storage = next(c for c in probe.build_report(delivery, state)["criteria"] if c["id"] == "c5")
    assert storage["state"] == probe.NOT_SATISFIED, (
        f"a form POSTing to a GET-only route rendered {storage['state']!r}"
    )
    assert any("AND that method" in e for e in storage["evidence"]), (
        f"the report did not disclose that the method is part of the check: {storage['evidence']}"
    )


def test_a_link_inside_a_script_the_browser_discards_does_not_rescue_a_page(probe, tmp_path):
    """The MIRROR IMAGE of the blank-field defect, found by the same step-4 sweep.

    The blank-field check counted machinery that cannot RUN; the orphan audit counted a
    link living in code that cannot run. A dead module script naming `piece-detail.html`
    would have made an unreachable page read as reachable.

    Latent on real data when found -- the only dead script in any banked delivery names no
    HTML file at all -- so this fixture is synthetic and deliberately so.
    """
    state, delivery = _bank(tmp_path, SITE, RUN, link_detail=False, storage="dead-module")
    public = delivery / "public"
    (public / "enquiries.js").write_text(
        "export function go() { window.location.href = 'piece-detail.html'; }\n",
        encoding="utf-8",
    )
    pages = next(c for c in probe.build_report(delivery, state)["criteria"] if c["id"] == "c1")
    assert pages["state"] == probe.NOT_SATISFIED, (
        "a link inside a script the browser discards was accepted as a way to reach the "
        "page; that script never executes"
    )
    assert any("piece-detail.html: ORPHAN" in e for e in pages["evidence"])


def test_messages_behind_browser_constraint_validation_are_not_decidable(probe, tmp_path):
    """SHAPE 1 of 3. `required` on every control + custom messages behind `submit`.

    The mechanism, and it is the whole point of this trio: a control carrying `required`
    is checked by the browser BEFORE the `submit` event fires. Blank input means the
    browser blocks submission and shows its own bubble, and the page's submit handler
    never runs -- so the custom per-field messages can only fire for input that PASSES
    `required` and then fails a JavaScript rule. The blank case, the one his sentence
    names, is exactly the one they cannot cover.

    Fails if the check reverts to counting messages, which measures that the machinery
    EXISTS and silently claims it is REACHABLE. Real fixtures: 20260816-070923 and
    20260816-210245 both have this shape.
    """
    state, delivery = _bank(tmp_path, SITE, RUN, error_writes=5)
    feedback = next(
        c for c in probe.build_report(delivery, state)["criteria"] if c["id"] == "c6"
    )
    assert feedback["state"] == probe.NOT_DECIDABLE, (
        f"messages the browser prevents from ever running rendered {feedback['state']!r}. "
        "SATISFIED overclaims (the path is unreachable for blank input); NOT SATISFIED "
        "underclaims (the machinery is genuinely there)."
    )
    joined = " ".join(feedback["evidence"])
    assert "5 of 5 form control(s) carry `required`" in joined, (
        f"the report did not state the `required` fact a reader needs: {feedback['evidence']}"
    )
    assert "browser intercepts blank input" in joined, (
        "the report named the messages but not the reason they cannot fire"
    )


def test_messages_on_a_non_submit_handler_are_satisfied(probe, tmp_path):
    """SHAPE 2 of 3. Real-time validation on `blur` reaches blank input.

    `blur` fires whether or not constraint validation would pass, so tabbing out of an
    empty box does show the custom message even with `required` on every control. This is
    the shape delivery 20260817-070902 ships, and it is the one build of the twelve banked
    that actually solved the problem.

    Fails if a blanket "required means undecidable" rule is applied -- which would collapse
    all three fixtures to NOT DECIDABLE and lose the only build that got this right, the
    same defect as scoring every delivery alike.
    """
    state, delivery = _bank(tmp_path, SITE, RUN, error_writes=5, blur_validation=True)
    feedback = next(
        c for c in probe.build_report(delivery, state)["criteria"] if c["id"] == "c6"
    )
    assert feedback["state"] == probe.SATISFIED, (
        f"per-field messages on a blur handler rendered {feedback['state']!r}. These fire "
        "regardless of `required`, so blank input DOES reach them."
    )
    assert any("'blur'" in e and "regardless of `required`" in e for e in feedback["evidence"]), (
        f"the report did not name the reachable trigger: {feedback['evidence']}"
    )


def test_no_per_field_messages_at_all_is_not_satisfied(probe, tmp_path):
    """SHAPE 3 of 3. Nothing writes a per-field message -- a plain failure, not a doubt.

    Real fixture: 20260810-204018 ships error `<span>`s that no script ever writes to.
    Fails if the undecidable branch swallows this one; "we cannot tell" and "there is
    nothing there" are different answers and only the second is the coder's fault.
    """
    state, delivery = _bank(tmp_path, SITE, RUN, error_writes=0)
    feedback = next(
        c for c in probe.build_report(delivery, state)["criteria"] if c["id"] == "c6"
    )
    assert feedback["state"] == probe.NOT_SATISFIED, (
        f"a page with no per-field messages at all rendered {feedback['state']!r}"
    )


def test_novalidate_restores_reachability(probe, tmp_path):
    """The escape hatch: a form can opt OUT of the browser's validation entirely.

    With `novalidate` the submit event fires on blank input, so the custom messages run and
    the criterion is satisfied even with `required` on every control. Six banked deliveries
    (the 20260808 batch) set `novalidate`; none of them also has per-field messages, so this
    combination is SYNTHETIC and is marked as such.

    Fails if the check keys on `required` alone and ignores the attribute that disables it.
    """
    state, delivery = _bank(tmp_path, SITE, RUN, error_writes=5, novalidate=True)
    feedback = next(
        c for c in probe.build_report(delivery, state)["criteria"] if c["id"] == "c6"
    )
    assert feedback["state"] == probe.SATISFIED, (
        f"a form that sets `novalidate` rendered {feedback['state']!r}; the browser does "
        "not intercept anything, so the submit handler runs on blank input"
    )
    assert any("novalidate" in e for e in feedback["evidence"])


def test_listener_attribution_takes_the_innermost_handler(probe, tmp_path):
    """A submit listener nested inside DOMContentLoaded is a SUBMIT listener.

    Two of the three banked deliveries nest it exactly this way, and the first draft of
    this attribution took the first enclosing span. That credited every message to
    `DOMContentLoaded`, read it as a non-submit trigger, and concluded the messages were
    reachable for blank input. They are not. The nesting is the norm here, not an edge
    case, so it gets its own lock rather than riding on the shape tests.
    """
    _, delivery = _bank(tmp_path, SITE, RUN, error_writes=5, nest_in_domcontentloaded=True)
    facts = probe._form_feedback(probe.load_delivery(delivery).page("contact.html"))
    assert facts.in_submit == 5, (
        f"messages inside a submit listener nested in DOMContentLoaded were attributed "
        f"elsewhere: submit={facts.in_submit}, other={facts.in_other}, "
        f"unattributed={facts.unattributed}"
    )
    assert facts.in_other == 0
    assert not facts.reachable_for_blank


def test_clearing_an_error_message_is_not_counted_as_feedback(probe, tmp_path):
    """`errorEl.textContent = ''` erases a message; it is not feedback.

    Found by measuring: a page with eleven real error writes scored sixteen because its
    five `= ''` clears were counted too. A negative lookahead does NOT fix this -- `\\s*`
    backtracks to zero width and the lookahead passes on the space -- so the pattern
    requires a non-empty right-hand side positively. Fails if that is "simplified" back.
    """
    state, delivery = _bank(tmp_path, SITE, RUN, error_writes=0)
    public = delivery / "public"
    page = (public / "contact.html").read_text(encoding="utf-8")
    page = page.replace(
        "let ok = true;",
        "let ok = true;\n      document.getElementById('nameError').textContent = '';\n"
        "      document.getElementById('emailError').textContent = \"\";",
    )
    (public / "contact.html").write_text(page, encoding="utf-8")

    feedback = next(
        c for c in probe.build_report(delivery, state)["criteria"] if c["id"] == "c6"
    )
    assert feedback["state"] == probe.NOT_SATISFIED, (
        "a page whose only per-field writes CLEAR the error text was credited with giving "
        "the user feedback"
    )


def test_an_orphan_page_is_found_and_a_linked_page_is_not_called_one(probe, tmp_path):
    """The defect the operator found by clicking: a detail page nothing links to.

    Locked in both directions, because the cheap way to always find orphans is to look for
    a link nobody writes, and that would convict every delivery equally.
    """
    state_linked, deliv_linked = _bank(tmp_path / "l", SITE, RUN, link_detail=True)
    linked = next(
        c for c in probe.build_report(deliv_linked, state_linked)["criteria"] if c["id"] == "c1"
    )
    assert linked["state"] == probe.SATISFIED, (
        f"a site whose list page links to its detail page was called unreachable: "
        f"{linked['evidence']}"
    )

    state_orphan, deliv_orphan = _bank(tmp_path / "o", SITE, RUN, link_detail=False)
    orphan = next(
        c for c in probe.build_report(deliv_orphan, state_orphan)["criteria"] if c["id"] == "c1"
    )
    assert orphan["state"] == probe.NOT_SATISFIED
    assert any("piece-detail.html: ORPHAN" in e for e in orphan["evidence"]), (
        f"the orphaned page was not named; evidence was {orphan['evidence']}"
    )


def test_a_menu_injected_by_a_script_still_counts_as_a_menu(probe, tmp_path):
    """A real delivery grows its header from a shared script. That is one menu, not none.

    Fails if the nav check is narrowed to literal markup, which would convict the tidiest
    of the three banked deliveries for doing the right thing.
    """
    state, delivery = _bank(tmp_path, SITE, RUN)
    public = delivery / "public"
    (public / "header.js").write_text(
        "document.body.insertAdjacentHTML('afterbegin', `<header><nav><ul>"
        '<li><a href="home.html">Home</a></li>'
        '<li><a href="pieces.html">Pieces</a></li>'
        '<li><a href="contact.html">Contact</a></li>'
        "</ul></nav></header>`);\n",
        encoding="utf-8",
    )
    for name in ("home.html", "pieces.html", "piece-detail.html", "contact.html"):
        text = (public / name).read_text(encoding="utf-8")
        start, _, rest = text.partition("<header>")
        _, _, after = rest.partition("</header>")
        (public / name).write_text(
            start + '<script src="header.js"></script>' + after, encoding="utf-8"
        )

    menu = next(c for c in probe.build_report(delivery, state)["criteria"] if c["id"] == "c2")
    assert menu["state"] == probe.SATISFIED, (
        f"a menu injected by a shared script read as no menu at all: {menu['evidence']}"
    )
    assert any("injected:header.js" in e for e in menu["evidence"]), (
        "the report did not disclose that these pages depend on JavaScript for a header"
    )


def test_a_redirect_stub_is_excluded_from_the_menu_check_and_named(probe, tmp_path):
    """Shrinking a denominator silently is this project's oldest instrument defect.

    `index.html` forwarding to `home.html` carries no menu and never could. It is excluded
    -- and the exclusion is printed, so the reader can disagree with it.
    """
    state, delivery = _bank(tmp_path, SITE, RUN)
    report = probe.build_report(delivery, state)
    assert report["excluded_pages"]["redirect_stubs"] == ["index.html"]
    menu = next(c for c in report["criteria"] if c["id"] == "c2")
    assert any("redirect stub" in e and "named here" in e for e in menu["evidence"]), (
        f"the exclusion was applied without being disclosed: {menu['evidence']}"
    )


# --------------------------------------------------------------------------------------
# 5. Joining his criteria to the right delivery
# --------------------------------------------------------------------------------------


def test_criteria_are_joined_through_the_run_named_in_review_html(probe, tmp_path):
    """The join is read, not guessed -- and the report says which route it took.

    A criteria set attached to the wrong delivery would produce confident verdicts about a
    tree it never described, so the provenance has to travel with the answer.
    """
    state, delivery = _bank(tmp_path, "20260816-210245-site", "20260816-134142-bd")
    report = probe.build_report(delivery, state)
    assert "20260816-134142-bd" in report["criteria_resolved_by"]
    assert "REVIEW.html" in report["criteria_resolved_by"]


def test_the_project_name_fallback_discloses_that_it_is_a_fallback(probe, tmp_path):
    """With no run pointer the join drops to a project-name match, which is weaker.

    Real banked deliveries hit this path. Fails if the fallback ever presents itself as
    the same quality of evidence as the pointer -- the report would then look equally
    confident about a criteria set that may belong to a different build entirely.
    """
    state, delivery = _bank(tmp_path, "20260816-210245-pottery", "20260816-134142-bd")
    (delivery / "REVIEW.html").unlink()
    (state / "fleet-runs" / "20260816-134142-bd" / "acceptance.json").write_text(
        json.dumps({"repo": "C:\\projects\\pottery", "spec": {"criteria": CRITERIA}}),
        encoding="utf-8",
    )

    report = probe.build_report(delivery, state)
    assert report["criteria_count"] == 8
    assert "MATCH ON PROJECT NAME" in report["criteria_resolved_by"], (
        f"the weaker join was not disclosed as weaker: {report['criteria_resolved_by']!r}"
    )


def test_an_explicit_criteria_path_overrides_the_join(probe, tmp_path):
    """The escape hatch, so a delivery from anywhere can be judged against any criteria."""
    state, delivery = _bank(tmp_path, SITE, RUN)
    other = tmp_path / "other.json"
    other.write_text(json.dumps({"spec": {"criteria": CRITERIA[:2]}}), encoding="utf-8")
    report = probe.build_report(delivery, state, other)
    assert report["criteria_count"] == 2
    assert "explicit" in report["criteria_resolved_by"]


def test_an_unreadable_acceptance_file_is_not_read_as_zero_criteria(probe, tmp_path):
    """A corrupt criteria file and an absent one are different faults with different owners.

    Fails if the reader collapses them, which would report "he stated no requirements" for
    a run whose writer is broken.
    """
    state, delivery = _bank(tmp_path, SITE, RUN)
    (state / "fleet-runs" / RUN / "acceptance.json").write_text("{not json", encoding="utf-8")
    report = probe.build_report(delivery, state)
    assert report["criteria_count"] == 0
    assert "did not parse" in report["criteria_resolved_by"], (
        f"a corrupt acceptance.json was reported as {report['criteria_resolved_by']!r}, "
        "which reads like the file was simply absent"
    )


# --------------------------------------------------------------------------------------
# 9. Deleting pages must not improve the score (#1439, found by independent review
#    2026-08-31 on the branch, BEFORE merge)
# --------------------------------------------------------------------------------------
#
# The original c1 was decided PURELY by an inbound orphan audit -- "is every page I
# shipped linked from somewhere?" -- which a site gets BETTER at by shipping fewer pages.
# Measured on the banked corpus at that commit: 11 of 21 deliveries scored c1 SATISFIED
# and 9 of those shipped no individual-piece page at all; a one-page delivery whose menu
# linked to two files that did not exist scored SATISFIED and OUTSCORED a strictly better
# three-page build. The function's own docstring promised a page-count check that was
# never written.
#
# These locks pin all three halves. The last one is the property that actually matters:
# an instrument whose headline number improves when work is deleted is worse than none.


def _delete_pages(delivery: Path, *names: str) -> None:
    """Remove delivered pages, leaving every menu link to them in place -- which is what
    the real deliveries did, rather than tidily re-linking."""
    for n in names:
        (delivery / "public" / n).unlink()


def test_a_complete_site_still_passes_c1(probe, tmp_path: Path) -> None:
    """The toggle's other half. If this ever goes red the check has become unpassable,
    which is the same defect wearing the opposite face."""
    state, delivery = _bank(tmp_path / "full", "20260816-070923-site", "20260815-230306-bd")
    assert _states(probe.build_report(delivery, state))["c1"] == probe.SATISFIED


def test_a_link_to_a_page_that_was_never_delivered_fails_c1(probe, tmp_path: Path) -> None:
    state, delivery = _bank(tmp_path / "dead", "20260816-070923-site", "20260815-230306-bd")
    _delete_pages(delivery, "contact.html")
    report = probe.build_report(delivery, state)
    assert _states(report)["c1"] == probe.NOT_SATISFIED
    evidence = " ".join(
        line for c in report["criteria"] if c["id"] == "c1" for line in c["evidence"]
    )
    assert "contact.html" in evidence, "the dead link target is not named in the evidence"


def test_fewer_pages_than_the_criterion_names_fails_c1(probe, tmp_path: Path) -> None:
    """The blocker case, reduced: the criterion names four page kinds and the delivery
    ships fewer. Under the original check this scored SATISFIED."""
    state, delivery = _bank(tmp_path / "thin", "20260816-070923-site", "20260815-230306-bd")
    _delete_pages(delivery, "contact.html", "pieces.html", "piece-detail.html")
    assert _states(probe.build_report(delivery, state))["c1"] == probe.NOT_SATISFIED


def test_deleting_the_orphan_must_not_turn_a_failure_into_a_pass(probe, tmp_path: Path) -> None:
    """THE regression lock for this defect class, and it took three attempts to make it bite.

    v1 compared total SATISFIED counts: decoration, because deleting pages also degrades
    c3/c4/c5 so the total falls while c1 wrongly improves. v2 compared c1 before and after
    deleting three pages: also decoration, because under the defect BOTH read SATISFIED.
    Both were caught by mutating the fix out and watching the lock stay green, which is
    the entire reason locks are toggle-proved instead of trusted.

    v3 reproduces the corpus inversion exactly. A build that orphans its detail page FAILS
    the inbound audit. DELETE that orphan and the inbound audit has nothing left to
    complain about -- so under the original check the delivery got BETTER by losing a
    page, which is how 9 of 21 banked deliveries scored SATISFIED while shipping no piece
    page at all.
    """
    rank = {probe.NOT_SATISFIED: 0, probe.NOT_DECIDABLE: 1, probe.SATISFIED: 2}

    # A site whose detail page nothing links to: the inbound audit's own failing case.
    orph_state, orphaned = _bank(
        tmp_path / "o", "20260816-070923-site", "20260815-230306-bd", link_detail=False
    )
    # The same site with that unreachable page simply removed. Strictly less work shipped.
    del_state, deleted = _bank(
        tmp_path / "d", "20260816-070923-site", "20260815-230306-bd", link_detail=False
    )
    _delete_pages(deleted, "piece-detail.html")

    before = _states(probe.build_report(orphaned, orph_state))["c1"]
    after = _states(probe.build_report(deleted, del_state))["c1"]
    assert rank[after] <= rank[before], (
        f"deleting the unreachable page moved c1 from {before} to {after}: the score "
        "IMPROVED because work was deleted. That is the defect -- an inbound-only audit "
        "has fewer orphans to find the fewer pages you ship."
    )


def test_c1_is_undecidable_when_the_criterion_names_no_page_count(probe, tmp_path: Path) -> None:
    """Both audits passing is NOT enough. If his sentence does not say how many pages he
    wants, the criterion's principal claim went unchecked and SATISFIED would overclaim."""
    assert probe._named_page_count("All pages should have the same heading at the top.") is None
    assert probe._named_page_count("The website should launch without crashing.") is None
    assert (
        probe._named_page_count(
            "The website should have a home page, a pieces list page, "
            "individual piece pages, and a contact page."
        )
        == 4
    )
