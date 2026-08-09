"""#1161 — the empty-project gradeable-stack default + the plan card's build-risk line.

Run evidence (2026-07-29, run 20260729-085557-bd): a brand-new EMPTY project whose
operator never named a platform was classified ``desktop-gui`` by the build-signal
model, scaffolded winui-from-nothing, and burned ~103 fleet-minutes with zero merge —
the exam machinery blind the whole way. These locks pin the fix at BOTH altitudes:

  * the deterministic refiner (:func:`default_gradeable_platform`) as a unit, AND
  * driven THROUGH the real ``generate_plan`` seam with a fake model that MISBEHAVES the
    way the live 14B demonstrably did (confidently emits desktop for a silent goal) —
    mocks that are polite where the model isn't are how the original defect shipped.

The toggle-off bars: an existing/non-empty project, a card-driven dispatch, an
operator-named platform, an explicit non-gated language hint, and every sentinel surface
must all pass through BYTE-IDENTICAL.
"""

from __future__ import annotations

import json

import pytest

from shared.fleet import acceptance as acc
from shared.fleet import clarify as cl
from shared.fleet.acceptance import AcceptanceCriterion, AcceptanceSpec


# ---- fakes: the misbehaving model ------------------------------------------


def _fake_model(*, tasks_json, criteria_json, assumptions_json="[]",
                build_plan_json="", oracle_py=""):
    """Routes generate_plan's chained prompts by their unique phrases (the
    test_acceptance idiom). ``build_plan_json`` defaulting to desktop is the point:
    the live 14B confidently classified a platform-silent goal as desktop-gui."""

    def gen(prompt: str) -> str:
        if "ACCEPTANCE CRITERIA" in prompt:
            return criteria_json
        if "PRODUCT assumptions" in prompt:
            return assumptions_json
        if "Classify what KIND of software" in prompt:
            return build_plan_json
        if "pytest test file" in prompt:
            return oracle_py
        if "node:test" in prompt:
            return ""
        if "image assets this product should DISPLAY" in prompt:
            return ""
        return tasks_json

    return gen


_DESKTOP_PLAN = json.dumps({
    "surface": "desktop-gui", "language_hint": None,
    "complexity": "moderate", "components": [],
})


def _empty_repo(projects_dir, name="fresh"):
    (projects_dir / name / ".git").mkdir(parents=True)
    (projects_dir / name / "README.md").write_text("# fresh", encoding="utf-8")
    return name


def _gen(goal, repo, projects, *, build_plan_json=_DESKTOP_PLAN, requirements=""):
    gen = _fake_model(
        tasks_json=json.dumps([{"task": "add-thing", "prompt": "build it"}]),
        criteria_json=json.dumps(
            [{"text": "it works", "tier": "behavior", "check": ""}]
        ),
        build_plan_json=build_plan_json,
    )
    return acc.generate_plan(
        goal, repo, generate_fn=gen, projects_dir=projects,
        requirements=requirements,
    )


# ---- operator_platform_signal (the deterministic scan) ---------------------


@pytest.mark.parametrize("text,expected", [
    ("a habit tracker", ""),
    ("a calculator for my kid", ""),
    ("a personal website for my books", "web"),
    ("one web page with my recipes", "web"),
    # The operator's stated vocabulary (LA, 2026-07-29): "i often say webpage or
    # web page, or website, or web site" — all four variants are pinned.
    ("a webpage for my garden photos", "web"),
    ("a web site about local birds", "web"),
    ("something I open in my browser", "web"),
    ("an html page", "web"),
    ("an iphone app for recipes", "mobile"),
    ("something for my phone", "mobile"),
    ("an Android tablet thing", "mobile"),
    ("a desktop app for notes", "desktop-gui"),
    ("a WinUI notes tool", "desktop-gui"),
    ("a C# calculator", "desktop-gui"),
    ("a .NET service", "desktop-gui"),
    ("a windows application for invoices", "desktop-gui"),
    ("a command-line tool for renaming", "command-line"),
    ("a CLI for my notes", "command-line"),
    ("something I run in the terminal", "command-line"),
    # precedence: web outranks mobile (a browser page WORKS on a phone) …
    ("a web page I can read on my phone", "web"),
    # … and mobile outranks desktop.
    ("a phone app, not a desktop one", "mobile"),
    # word-boundary narrowness: near-misses must NOT count as named platforms.
    ("a webinar planner", ""),
    ("a briOS-themed game", ""),
    ("", ""),
    # Bare "site"/"sites" as a WEB indicator (LA vocabulary extension, 2026-07-29:
    # '"ecommerce site". site is probably a pretty good indicator of it being a web
    # project'). Required pins first:
    ("an ecommerce site", "web"),
    ("a portfolio site", "web"),
    ("a landing site for the product", "web"),
    ("a site for my paintings", "web"),
    ("two sites, one for each shop", "web"),
    # …but NOT in physical-place compounds ("site" = a place, not a deliverable):
    ("a camp site tracker", ""),
    ("a campsite tracker", ""),          # one-word form never matches at all
    ("a job site checklist", ""),
    ("a construction site log", ""),
    ("a work site roster", ""),
    ("a dig site catalog", ""),
    ("an on-site inventory list", ""),
    ("a site visit planner", ""),
    # a non-excluded occurrence still wins even next to an excluded one — both orders
    # (the second exercises the excluded-then-found scan path):
    ("a portfolio site with a construction site gallery", "web"),
    ("a construction site diary and a portfolio site", "web"),
    # DUAL-SIGNAL interaction: bare site is WEAK-TIER — an explicit platform word
    # always beats it (required pin + the general rule):
    ("a desktop app for my construction site logs", "desktop-gui"),
    ("a desktop app for my portfolio site", "desktop-gui"),
    ("a command-line tool for my site stats", "command-line"),
    # …including mobile: the honest refusal (which itself names the web escape)
    # beats a weak indicator silently overriding the explicit word "phone".
    ("an ecommerce site for my phone", "mobile"),
])
def test_operator_platform_signal_table(text, expected):
    assert acc.operator_platform_signal(text) == expected


# ---- is_empty_new_project (the #888 pair, named once) ----------------------


def test_is_empty_new_project_fresh_shell_true(tmp_path):
    repo = tmp_path / "fresh"
    (repo / ".git").mkdir(parents=True)
    (repo / "README.md").write_text("# fresh", encoding="utf-8")
    assert acc.is_empty_new_project(repo) is True


def test_is_empty_new_project_existing_python_false(tmp_path):
    # Loose .py scripts with no manifest: detect_ecosystem says python — an EXISTING
    # project, never "empty", even though repo_will_scaffold alone would say True.
    repo = tmp_path / "scripts"
    repo.mkdir()
    (repo / "tool.py").write_text("print('hi')\n", encoding="utf-8")
    assert acc.is_empty_new_project(repo) is False


def test_is_empty_new_project_manifest_false(tmp_path):
    repo = tmp_path / "node"
    repo.mkdir()
    (repo / "package.json").write_text("{}", encoding="utf-8")
    assert acc.is_empty_new_project(repo) is False


def test_is_empty_new_project_nested_marker_false(tmp_path):
    repo = tmp_path / "mono"
    (repo / "packages" / "app").mkdir(parents=True)
    (repo / "packages" / "app" / "package.json").write_text("{}", encoding="utf-8")
    assert acc.is_empty_new_project(repo) is False


# ---- default_gradeable_platform (the refiner as a unit) --------------------


def _bp(surface="desktop-gui", hint=None, **extra):
    d = {"surface": surface, "language_hint": hint,
         "complexity": "moderate", "components": []}
    d.update(extra)
    return d


def test_refiner_silent_desktop_on_empty_becomes_python_cli(tmp_path):
    repo = tmp_path / "fresh"
    (repo / ".git").mkdir(parents=True)
    out, note = acc.default_gradeable_platform(
        _bp(), operator_text="a calculator for my kid", repo_path=repo
    )
    assert out["surface"] == "command-line"
    assert out["language_hint"] == "python"
    assert acc.scaffold_gated_ecosystem(out) == "python"
    assert "command-line tool" in note
    # the exam machinery is sighted by construction now
    assert note != ""


def test_refiner_untouched_on_non_empty_repo(tmp_path):
    repo = tmp_path / "existing"
    repo.mkdir()
    (repo / "app.csproj").write_text("<Project/>", encoding="utf-8")
    plan = _bp()
    out, note = acc.default_gradeable_platform(
        plan, operator_text="a calculator", repo_path=repo
    )
    assert out == plan and note == ""


def test_refiner_honors_named_desktop(tmp_path):
    repo = tmp_path / "fresh"
    (repo / ".git").mkdir(parents=True)
    plan = _bp()
    out, note = acc.default_gradeable_platform(
        plan, operator_text="a desktop app for notes", repo_path=repo
    )
    assert out == plan and note == ""


def test_refiner_honors_CORROBORATED_non_gated_hint(tmp_path):
    # Review F2: a non-gated hint is honored ONLY when the operator's own words back it
    # — "a PowerShell script" keeps its PowerShell CLI; a C++ tool keeps cpp; a C# ask
    # returns even earlier as a named desktop platform.
    repo = tmp_path / "fresh"
    (repo / ".git").mkdir(parents=True)
    cases = (
        ("powershell", "a PowerShell script that renames my files"),
        ("cpp", "a C++ tool that renames my files"),
        ("dotnet", "a C# renaming tool"),
    )
    for hint, text in cases:
        plan = _bp(surface="command-line", hint=hint)
        out, note = acc.default_gradeable_platform(
            plan, operator_text=text, repo_path=repo
        )
        assert out == plan and note == "", hint


def test_refiner_steers_UNCORROBORATED_non_gated_hint(tmp_path):
    # Review F2's probe: the hint is authored by the same 14B whose surface discipline
    # caused the incident — a model-invented dotnet/cpp/powershell hint on a SILENT goal
    # must not suppress the gradeable default (the adjacent emission shape to the
    # measured hint=null morning run).
    repo = tmp_path / "fresh"
    (repo / ".git").mkdir(parents=True)
    for hint in ("dotnet", "cpp", "powershell"):
        for surface in ("desktop-gui", "command-line"):
            out, note = acc.default_gradeable_platform(
                _bp(surface=surface, hint=hint),
                operator_text="a renaming script", repo_path=repo,
            )
            assert out["surface"] == "command-line", (hint, surface)
            assert out["language_hint"] == "python", (hint, surface)
            assert note != "", (hint, surface)


def test_refiner_forces_web_when_operator_named_web(tmp_path):
    repo = tmp_path / "fresh"
    (repo / ".git").mkdir(parents=True)
    # "website" (explicit) and "ecommerce site" (the LA's bare-site vocabulary,
    # 2026-07-29) both force web over a model desktop misread on an empty repo.
    for text in ("a website for my books", "an ecommerce site for my pottery"):
        out, note = acc.default_gradeable_platform(
            _bp(), operator_text=text, repo_path=repo
        )
        assert out["surface"] == "web", text
        assert acc.scaffold_gated_ecosystem(out) == "node"
        assert note != ""


def test_refiner_leaves_web_and_web_static_alone(tmp_path):
    repo = tmp_path / "fresh"
    (repo / ".git").mkdir(parents=True)
    for surface in ("web", "web-static"):
        plan = _bp(surface=surface)
        out, note = acc.default_gradeable_platform(
            plan, operator_text="a page for my books, plain html", repo_path=repo
        )
        assert out == plan and note == "", surface


def test_refiner_leaves_sentinels_alone(tmp_path):
    # unknown keeps today's honest no-seed path; ambiguous keeps the increment-4
    # numbered platform question (the c.2639-observed lever) — the refiner must never
    # eat the question by resolving the fork itself.
    repo = tmp_path / "fresh"
    (repo / ".git").mkdir(parents=True)
    unknown = _bp(surface="unknown")
    out, note = acc.default_gradeable_platform(
        unknown, operator_text="a calculator", repo_path=repo
    )
    assert out == unknown and note == ""
    ambiguous = _bp(surface="ambiguous", candidates=["desktop-gui", "web"])
    out, note = acc.default_gradeable_platform(
        ambiguous, operator_text="an app with buttons", repo_path=repo
    )
    assert out == ambiguous and note == ""
    assert acc.resolve_clarifying_question(out) is not None  # the question still fires


def test_refiner_gated_stack_passes_through(tmp_path):
    repo = tmp_path / "fresh"
    (repo / ".git").mkdir(parents=True)
    for plan in (_bp(surface="command-line"), _bp(surface="library", hint="node")):
        out, note = acc.default_gradeable_platform(
            plan, operator_text="a thing", repo_path=repo
        )
        assert out == plan and note == ""


def test_refiner_none_build_plan_passes_through(tmp_path):
    out, note = acc.default_gradeable_platform(
        None, operator_text="a thing", repo_path=tmp_path / "missing"
    )
    assert out is None and note == ""


# ---- THROUGH generate_plan (the seam, with the misbehaving model) ----------


def test_generate_plan_empty_project_silent_goal_defaults_to_python_cli(tmp_path):
    # THE morning-run shape: empty repo, platform-silent goal, model confidently says
    # desktop. The plan must compile NATIVELY for the gradeable stack — surface,
    # language hint, task threading and the card's assumption line all agree.
    projects = tmp_path / "projects"
    repo = _empty_repo(projects)
    res = _gen("a calculator for my kid", repo, projects)
    assert res.ok
    assert res.spec.build_plan["surface"] == "command-line"
    assert res.spec.build_plan["language_hint"] == "python"
    assert res.tasks[0]["surface"] == "command-line"
    assert any("command-line tool" in a for a in res.spec.assumptions)
    preview = acc.render_criteria_preview(
        res.spec, ecosystem="unknown", tasks=res.tasks,
        scaffold_ecosystem=acc.scaffold_gated_ecosystem(res.spec.build_plan),
        will_scaffold=True,
    )
    assert "Building this as: a command-line tool." in preview
    assert "checks WILL run" in preview  # the gated-scaffold disclosure, not the risk line


def test_generate_plan_existing_project_keeps_model_surface(tmp_path):
    projects = tmp_path / "projects"
    repo = "existing"
    (projects / repo / ".git").mkdir(parents=True)
    (projects / repo / "app.csproj").write_text("<Project/>", encoding="utf-8")
    res = _gen("a calculator for my kid", repo, projects)
    assert res.ok
    assert res.spec.build_plan["surface"] == "desktop-gui"
    assert not any("command-line tool" in a for a in res.spec.assumptions)


def test_generate_plan_named_desktop_on_empty_is_honored(tmp_path):
    projects = tmp_path / "projects"
    repo = _empty_repo(projects)
    res = _gen("a desktop app for notes", repo, projects)
    assert res.ok
    assert res.spec.build_plan["surface"] == "desktop-gui"


def test_generate_plan_assumed_default_does_not_count_as_named(tmp_path):
    # The "just decide for me" defaults ride the requirements block as (assumed) lines.
    # System words must never masquerade as the operator having answered the platform
    # question — even when the assumed text mentions a device.
    projects = tmp_path / "projects"
    repo = _empty_repo(projects)
    req = cl.compose_requirements_block([
        {"question": "q", "answer": "a simple app that runs on this computer",
         "assumed": True},
    ])
    res = _gen("a calculator for my kid", repo, projects, requirements=req)
    assert res.ok
    assert res.spec.build_plan["surface"] == "command-line"


def test_generate_plan_operator_answer_naming_desktop_wins(tmp_path):
    projects = tmp_path / "projects"
    repo = _empty_repo(projects)
    req = cl.compose_requirements_block([
        {"question": "q", "answer": "I want a proper desktop app please",
         "assumed": False},
    ])
    res = _gen("a calculator for my kid", repo, projects, requirements=req)
    assert res.ok
    assert res.spec.build_plan["surface"] == "desktop-gui"


def test_generate_plan_card_driven_dispatch_is_never_steered(tmp_path):
    # A frozen battery card is the measurement instrument (#989 confound class): the
    # refiner must self-suppress on the card sandbox prefix even on an empty repo.
    projects = tmp_path / "projects"
    repo = "battery-b9-fresh"
    (projects / repo / ".git").mkdir(parents=True)
    res = _gen("a calculator card goal", repo, projects)
    assert res.ok
    assert res.spec.build_plan["surface"] == "desktop-gui"
    assert not any("command-line tool" in a for a in res.spec.assumptions)


# ---- operator_authored_answers (the scan's input discipline) ---------------


def test_operator_authored_answers_drops_assumed_keeps_authored():
    block = cl.compose_requirements_block([
        {"question": "q1", "answer": "a simple app that runs on this computer",
         "assumed": True},
        {"question": "q2", "answer": "keep my data between uses", "assumed": False},
    ])
    got = cl.operator_authored_answers(block)
    assert got == ("keep my data between uses",)
    # the sibling keeps BOTH (its corpus contract is unchanged)
    assert len(cl.operator_answers_from_block(block)) == 2


def test_operator_authored_answers_empty_and_blank():
    assert cl.operator_authored_answers("") == ()
    assert cl.operator_authored_answers(None) == ()  # type: ignore[arg-type]


# ---- decide_defaults axis_defaults (the empty-project decide text) ---------


def test_decide_defaults_axis_defaults_none_is_byte_identical():
    qs = (cl.ClarifyQuestion("surface", "Where will you use it?"),
          cl.ClarifyQuestion("feature", "What must it do well?"))
    assert cl.decide_defaults(qs) == cl.decide_defaults(qs, axis_defaults=None)


def test_decide_defaults_axis_defaults_overrides_one_axis_only():
    qs = (cl.ClarifyQuestion("surface", "Where will you use it?"),
          cl.ClarifyQuestion("feature", "What must it do well?"))
    got = cl.decide_defaults(
        qs, axis_defaults={cl.AXIS_SURFACE: cl.EMPTY_PROJECT_SURFACE_ANSWER}
    )
    assert got[0]["answer"] == cl.EMPTY_PROJECT_SURFACE_ANSWER
    assert got[0]["assumed"] is True
    assert got[1]["answer"] == cl.DEFAULT_AXIS_ANSWERS[cl.AXIS_FEATURE]


def test_empty_project_surface_answer_classifies_as_cli_not_named():
    # The decide text must be a SYSTEM default in the scan's eyes (assumed lines are
    # dropped upstream), and — read as text — must not accidentally name web/mobile.
    assert acc.operator_platform_signal(cl.EMPTY_PROJECT_SURFACE_ANSWER) in (
        "command-line", ""
    )


# ---- #1161 d2: the plan card's BUILD-RISK line -----------------------------


def _desktop_spec():
    return AcceptanceSpec(
        "a notes app",
        (AcceptanceCriterion("c1", "it builds", "build", ""),
         AcceptanceCriterion("c2", "notes save", "behavior", "")),
        build_plan={"surface": "desktop-gui", "language_hint": None,
                    "complexity": "moderate", "components": []},
    )


def test_build_risk_line_fires_for_fresh_blind_named_stack():
    out = acc.render_criteria_preview(
        _desktop_spec(), ecosystem="unknown", will_scaffold=True
    )
    assert "built from an EMPTY project" in out
    assert "command-line tool" in out
    assert "couldn't tell this project's language" not in out


def test_build_risk_line_absent_for_existing_repo():
    # will_scaffold False == every pre-#1161 caller and parked row: the generic honest
    # warning renders byte-identically.
    out = acc.render_criteria_preview(
        _desktop_spec(), ecosystem="unknown", will_scaffold=False
    )
    assert "built from an EMPTY project" not in out
    assert "couldn't tell this project's language" in out


def test_build_risk_line_absent_when_scaffold_is_gated():
    # A fresh WEB repo: the #888 "checks WILL run" arm outranks the risk line — the
    # stack is sighted, so there is no build-risk disclosure to make.
    spec = AcceptanceSpec(
        "a page",
        (AcceptanceCriterion("c1", "it builds", "build", ""),),
        build_plan={"surface": "web", "language_hint": None,
                    "complexity": "simple", "components": []},
    )
    out = acc.render_criteria_preview(
        spec, ecosystem="unknown", scaffold_ecosystem="node", will_scaffold=True
    )
    assert "checks WILL run" in out
    assert "built from an EMPTY project" not in out


def test_build_risk_line_absent_without_a_named_stack():
    # No build_plan -> no friendly surface -> nothing to warn ABOUT: the generic
    # warning keeps its job (never a guessed platform in the risk line).
    spec = AcceptanceSpec(
        "a thing", (AcceptanceCriterion("c1", "it builds", "build", ""),)
    )
    out = acc.render_criteria_preview(spec, ecosystem="unknown", will_scaffold=True)
    assert "built from an EMPTY project" not in out
    assert "couldn't tell this project's language" in out


def test_web_static_arm_outranks_build_risk_line():
    spec = AcceptanceSpec(
        "a page",
        (AcceptanceCriterion("c1", "it builds", "build", ""),),
        build_plan={"surface": "web-static", "language_hint": None,
                    "complexity": "simple", "components": []},
    )
    out = acc.render_criteria_preview(spec, ecosystem="unknown", will_scaffold=True)
    assert "plain HTML page" in out
    assert "built from an EMPTY project" not in out


# ---- review F1: the web-force is subordinate to any other named platform ----


def test_F1_web_force_never_overrides_named_cli_or_desktop(tmp_path):
    # The three execution-confirmed probes: an INCIDENTAL web word must not force web
    # over an operator-NAMED CLI or desktop platform on an empty repo.
    repo = tmp_path / "fresh"
    (repo / ".git").mkdir(parents=True)
    probes = (
        # (operator text, the surface the model emitted)
        ("a command-line tool that scrapes a website for prices", "desktop-gui"),
        # the worst probe: the force used to FLIP an already-sighted gradeable CLI
        ("a CLI that calls a web API and prints the result", "command-line"),
        ("a desktop app to save interesting web pages", "desktop-gui"),
    )
    for text, surface in probes:
        plan = _bp(surface=surface)
        out, note = acc.default_gradeable_platform(
            plan, operator_text=text, repo_path=repo
        )
        assert out == plan and note == "", (text, surface)


def test_F1_web_only_asks_still_force_web(tmp_path):
    # The no-regression bar: web named ALONE (explicit or bare-site) still wins over a
    # model misread — the F1 guard must not disable the force itself.
    repo = tmp_path / "fresh"
    (repo / ".git").mkdir(parents=True)
    for text in ("a website for my books", "an ecommerce site for my pottery"):
        out, note = acc.default_gradeable_platform(
            _bp(), operator_text=text, repo_path=repo
        )
        assert out["surface"] == "web", text
        assert note != ""


def test_F1_site_tier_leak_cannot_reach_the_force_on_named_platform(tmp_path):
    # Merge-record note: the documented site-tier leaks (novel compounds reading web)
    # must not reach the force-web arm when the operator ALSO named a platform.
    repo = tmp_path / "fresh"
    (repo / ".git").mkdir(parents=True)
    plan = _bp()
    out, note = acc.default_gradeable_platform(
        plan, operator_text="a desktop app for the site survey results", repo_path=repo
    )
    assert out == plan and note == ""


# ---- review F3: the fresh-repo platform menu never offers "On a phone" -----


def test_F3_suppress_phone_option_three_way_becomes_two():
    q = acc.resolve_clarifying_question(
        {"surface": "ambiguous", "candidates": ["desktop-gui", "web", "mobile"]}
    )
    filtered = acc.suppress_phone_option_for_fresh_repo(q)
    assert [o["surface"] for o in filtered["options"]] == ["desktop-gui", "web"]
    assert filtered["question"] == q["question"]
    # the original question dict is untouched (fresh copy, never mutation)
    assert [o["surface"] for o in q["options"]] == ["desktop-gui", "web", "mobile"]


def test_F3_two_way_mobile_forks_degrade_to_one_option_confirm():
    # A one-option menu is still an explicit operator turn — never a silent default.
    for candidates, kept in (
        (["desktop-gui", "mobile"], "desktop-gui"),
        (["web", "mobile"], "web"),
    ):
        q = acc.resolve_clarifying_question(
            {"surface": "ambiguous", "candidates": candidates}
        )
        filtered = acc.suppress_phone_option_for_fresh_repo(q)
        assert [o["surface"] for o in filtered["options"]] == [kept], candidates


def test_F3_filter_fail_closed_shapes():
    assert acc.suppress_phone_option_for_fresh_repo(None) is None
    assert acc.suppress_phone_option_for_fresh_repo("junk") is None  # type: ignore[arg-type]
    assert acc.suppress_phone_option_for_fresh_repo({"question": "q", "options": []}) is None
    only_mobile = {"question": "q", "options": [{"label": "On a phone", "surface": "mobile"}]}
    assert acc.suppress_phone_option_for_fresh_repo(only_mobile) is None


# ---- review F4: the build-risk line never contradicts itself for a CLI -----


def _blind_cli_spec():
    return AcceptanceSpec(
        "a renaming script",
        (AcceptanceCriterion("c1", "it builds", "build", ""),),
        build_plan={"surface": "command-line", "language_hint": "powershell",
                    "complexity": "simple", "components": []},
    )


def test_F4_blind_cli_card_names_python_alternative():
    # A corroborated PowerShell CLI on an empty repo: the checkable alternative is
    # named precisely — never "a command-line tool is fully checkable" two clauses
    # after warning about this command-line tool.
    out = acc.render_criteria_preview(
        _blind_cli_spec(), ecosystem="unknown", will_scaffold=True
    )
    assert "built from an EMPTY project" in out
    assert "A python command-line tool is the kind I can fully check" in out


def test_F4_desktop_card_keeps_generic_cli_alternative():
    out = acc.render_criteria_preview(
        _desktop_spec(), ecosystem="unknown", will_scaffold=True
    )
    assert "A command-line tool is the kind I can fully check" in out
    assert "A python command-line tool" not in out


# ---------------------------------------------------------------------------
# #1172 — an ASSUMED platform is asked, never ridden
# ---------------------------------------------------------------------------
#
# #1161 (above) made the empty-project default HONEST: the card had said "an app on this
# computer" while the build came out command-line, so the label was changed to match the
# build. That fixed a real lie and prevented a real failure (a winui-from-nothing scaffold
# that burned ~103 fleet-minutes for zero merge).
#
# What it could not fix is that the operator was never asked. Run 20260729-164648-bd, 12
# minutes after that fix merged: five clarifications, every one `assumed: True`, rendered
# under the header "The person clarified these requirements" — and the surface among them
# resolved to a command-line tool "the kind whose behavior can be fully checked
# automatically". The operator expected an app. The system had chosen the shape easiest to
# grade and attributed the choice to them.
#
# So the surface — and ONLY the surface — stops being assumable on a repo we are about to
# scaffold. Every other axis still answers itself.


def _assumed(axis: str) -> dict:
    return {"question": "q", "answer": "a", "assumed": True, "axes": [axis]}


def _answered(axis: str) -> dict:
    return {"question": "q", "answer": "in a web browser", "assumed": False, "axes": [axis]}


def test_platform_was_assumed_true_for_an_assumed_surface():
    assert acc.platform_was_assumed([_assumed(cl.AXIS_SURFACE)])


def test_platform_was_assumed_false_when_the_operator_answered():
    """The whole point of the gate: an operator who spoke never gets re-asked."""
    assert not acc.platform_was_assumed([_answered(cl.AXIS_SURFACE)])


def test_platform_was_assumed_false_for_other_assumed_axes():
    """Scope, styling and persistence stay assumable — a wrong guess there is visible in
    the result and cheap to redo. The surface is neither."""
    for axis in (cl.AXIS_SCOPE, cl.AXIS_VISUAL, cl.AXIS_PERSISTENCE, cl.AXIS_FEATURE):
        assert not acc.platform_was_assumed([_assumed(axis)]), axis


def test_platform_was_assumed_ignores_untagged_and_malformed_entries():
    """The quick path records no axes. An untagged entry cannot CLAIM the surface, so it
    is treated as no-claim rather than guessed at — a false fire would add a turn to a
    flow that never had one."""
    assert not acc.platform_was_assumed([{"question": "q", "answer": "a", "assumed": True}])
    assert not acc.platform_was_assumed([None, "nonsense", 42])
    assert not acc.platform_was_assumed([])
    assert not acc.platform_was_assumed(None)


def test_platform_question_reuses_the_increment_4_wording():
    """ONE platform question exists in this system. If increment 4 and this path ever
    drifted apart, the operator would meet two dialects of the same choice."""
    forced = acc.platform_question_for_assumed_surface()
    ambiguous = acc.resolve_clarifying_question(
        {"surface": "ambiguous", "candidates": ["desktop-gui", "web", "mobile"]}
    )
    assert forced == ambiguous


def test_platform_question_offers_every_real_surface():
    q = acc.platform_question_for_assumed_surface()
    assert [o["surface"] for o in q["options"]] == ["desktop-gui", "web", "mobile"]


def test_forced_question_still_drops_the_phone_option_on_a_fresh_repo():
    """#1161 review F3 composes with this: a fresh repo cannot build a phone app, so the
    menu must not offer one. Offer-then-refuse is the same lie in a friendlier voice."""
    q = acc.suppress_phone_option_for_fresh_repo(acc.platform_question_for_assumed_surface())
    assert [o["surface"] for o in q["options"]] == ["desktop-gui", "web"]


# ---------------------------------------------------------------------------
# The WIRING — driven, not grepped (#1197)
# ---------------------------------------------------------------------------
#
# #1174 claimed these two as wiring locks. They were `read_text()` substring greps: they
# asserted the call string appears in the coordinator's source, constructed no coordinator,
# passed no spec, and observed no question. They were GREEN throughout the false negative
# #1197 records — the call site existed and never fired, because the axis tag it keys off
# was written only under an opt-in token. A test that greps for its own fix is
# built-but-wired-into-nothing applied to the test suite.
#
# These drive the REAL DispatchCoordinator through its REAL entry point and observe the
# question being raised.


def _coord_for(tmp_path, plan_fn):
    from services.ui_gateway.src.dispatch_coordinator import DispatchCoordinator
    from shared.fleet import dispatch as fleet

    return DispatchCoordinator(
        config=fleet.FleetDispatchConfig(
            scripts_dir=tmp_path / "scripts", queue_path=tmp_path / "q.json",
            runs_dir=tmp_path / "runs", projects_dir=tmp_path / "projects",
        ),
        enabled=True, plan_fn=plan_fn, execute_fn=None,
        mint_run_id=lambda: "RID-DET",
    )


def _real_build_plan(surface: str, **extra) -> dict:
    """A build_plan produced by the REAL parser (#1220 F4).

    Never hand-write this dict. The previous fixture wrote ``candidates`` onto a
    ``command-line`` surface — a shape :func:`_parse_build_plan` FORBIDS, since it attaches
    candidates only to ``ambiguous``. Every test here passed on that impossible shape while
    the live path was broken, because ``apply_clarification`` validates against exactly the
    key the fixture invented. A fixture production cannot produce is not a weaker test; it
    is a test of a different program."""
    return acc._parse_build_plan(json.dumps({
        "surface": surface, "complexity": "simple", **extra
    }))


def _asking_plan(*axes: str, surface: str = "command-line",
                 record_goals: "list | None" = None, fail_replan_after: int = 0,
                 coverage_by_pass: "list[str] | None" = None,
                 empty_replan_after: int = 0,
                 replan_without_build_plan: bool = False,
                 pin_replan_surface: str = ""):
    """A plan_fn shaped like the real one: CLARIFY questions on the first pass, a plan on
    the re-plan (goal now carries the requirements sentinel).

    The returned task prompt is composed the way :func:`generate_plan` composes it — the
    operator's clarifications rendered under :data:`REQUIREMENTS_PROMPT_MARKER` — because
    #1220 carrier B is precisely that the prompt froze at this moment while the card kept
    re-rendering. A fixture whose prompt is a bare ``"p"`` cannot observe that at all.

    *record_goals* collects every goal the AO is asked to plan, so a test can see WHICH
    seed each pass ran on (#1224 N1). *fail_replan_after* makes the Nth sentinel-carrying
    pass fail, exercising the fail-closed retry on the surface-choice re-plan.

    #1237 adds the two shapes that were reachable and unobserved. *empty_replan_after* makes
    the Nth pass return ``ok`` with NOTHING to build — not a failure, so it must not be
    reported as one. *replan_without_build_plan* returns a spec whose ``build_plan`` is
    ``None``, the shape ``_parse_build_plan`` legitimately produces on unparseable model
    output, in which case the choice reaches the requirements but NOT the build signal.

    *pin_replan_surface* pins the re-plan's CLASSIFIED surface regardless of what the seed
    says, while leaving the criteria seed-driven. It exists to separate two things every
    other test here conflates: whether the answer reached the build signal because
    `apply_clarification` APPLIED it, or merely because the re-seeded pass happened to
    classify the same way. Only the first is a control."""
    from shared.fleet.acceptance import AcceptanceCriterion, AcceptanceSpec, PlanResult

    seeds = {"n": 0}

    async def plan_fn(repo, goal):
        if cl.REQUIREMENTS_SENTINEL not in goal:
            return PlanResult(ok=True, questions=[
                {"axis": a, "question": f"question about {a}?"} for a in axes
            ])
        if record_goals is not None:
            record_goals.append(goal)
        seeds["n"] += 1
        if fail_replan_after and seeds["n"] == fail_replan_after + 1:
            return PlanResult(ok=False, message="No response from the AO.")
        if empty_replan_after and seeds["n"] == empty_replan_after + 1:
            return PlanResult(ok=True, tasks=[], spec=None, message="planned")
        # Mirror generate_plan: the clarifications ride the goal across the seam, and the
        # rendered block is appended to every compiled task prompt. The criteria are
        # authored FROM THIS SEED — which is the whole point of #1224's re-plan.
        clean, req_block = cl.split_planning_goal(goal)
        prompt = "Build the thing."
        if req_block:
            prompt += f"{acc.REQUIREMENTS_PROMPT_MARKER}\n{req_block}"
        browser = "In a web browser" in req_block
        coverage = ""
        if coverage_by_pass:
            coverage = coverage_by_pass[min(seeds["n"] - 1, len(coverage_by_pass) - 1)]
        return PlanResult(
            ok=True, tasks=[{"repo": repo, "task": "t", "prompt": prompt}],
            coverage_blocked=coverage,
            spec=AcceptanceSpec(
                "a todo app",
                (AcceptanceCriterion("c1", "the project builds", "build", ""),
                 AcceptanceCriterion(
                     "c2",
                     "the page shows a converted value" if browser
                     else "the CLI prints a converted value",
                     "behavior",
                     "npm test" if browser else "pytest test_cli.py")),
                # A CLASSIFIED surface, as the real re-plan returns: the 14B was sure,
                # because the system had just told it what to think. That is the whole
                # shape of the defect — resolve_clarifying_question stays silent here.
                build_plan=(
                    None if replan_without_build_plan
                    else _real_build_plan(
                        pin_replan_surface or ("web" if browser else surface))
                ),
            ),
            message="planned",
        )
    return plan_fn


async def _drive(coord, text):
    from services.ui_gateway.src.dispatch_coordinator import parse_dispatch_command

    return await coord.handle_command("s", parse_dispatch_command(text))


@pytest.mark.asyncio
async def test_the_quick_path_asks_before_riding_an_assumed_surface(tmp_path):
    """#1197 — the acceptance test, on the DEFAULT path.

    No `advanced` token: this is the plain dispatch the operator ran. An empty repo, the
    "just decide for me" escape hatch, and the surface must be ASKED rather than assumed.
    Pre-#1197 this returned the approval card directly."""
    coord = _coord_for(tmp_path, _asking_plan(cl.AXIS_SURFACE, cl.AXIS_SCOPE))
    await _drive(coord, "/dispatch todo | a todo app")
    reply = await _drive(coord, "/dispatch just decide for me")

    assert coord._clarifying.get("s") is not None, \
        "the platform question was not raised on the quick path"
    assert "Where will you mainly use this?" in reply
    assert "/dispatch approve" not in reply, "the plan rode an unasked surface to approval"
    # #1161 F3 composes: a fresh repo is never offered a phone it cannot build.
    labels = [o["label"] for o in coord._clarifying["s"].question["options"]]
    assert labels == ["On this computer", "In a web browser"]


@pytest.mark.asyncio
async def test_the_operator_who_answered_is_never_re_asked(tmp_path):
    """The narrowness claim, driven. An operator who answered in their own words records
    assumed=False, so the gate must stay silent — a false fire adds a turn to a flow that
    never had one, on the path where the operator already spoke."""
    coord = _coord_for(tmp_path, _asking_plan(cl.AXIS_SURFACE))
    await _drive(coord, "/dispatch todo | a todo app")
    reply = await _drive(coord, "/dispatch in a web browser please")

    assert coord._clarifying.get("s") is None, "an operator who answered was re-asked"
    assert "/dispatch approve" in reply


@pytest.mark.asyncio
async def test_the_free_text_path_records_its_axes_on_the_quick_path_too(tmp_path):
    """#1197 also un-gated the FREE-TEXT path's axis recording, and a mutation run found
    that change asserted by nothing — re-gating it left the entire suite green.

    It cannot affect the gate (a free-text answer is ``assumed=False``, so
    :func:`platform_was_assumed` can never fire from it), which is precisely why it needed
    a lock of its own: a silent revert would cost no test, and would quietly make the
    acceptance RECORD path-dependent again — a quick dispatch's answer could no longer be
    attributed to the axes it answered."""
    coord = _coord_for(tmp_path, _asking_plan(cl.AXIS_SURFACE, cl.AXIS_SCOPE))
    await _drive(coord, "/dispatch todo | a todo app")
    await _drive(coord, "/dispatch in a web browser, keep it small")

    cls = coord.pending_for("s").spec.clarifications
    assert len(cls) == 1, "the one-reply-answers-all shape records a single entry"
    # The merged reply carries the FULL asked-axes list, on the QUICK path (no `advanced`
    # token anywhere in this test). Before #1197 this was None.
    assert cls[0].get("axes") == [cl.AXIS_SURFACE, cl.AXIS_SCOPE]
    assert cls[0]["assumed"] is False


@pytest.mark.asyncio
async def test_an_existing_project_never_reaches_the_forced_question(tmp_path):
    """The other narrowness claim: the gate is bounded to repos about to be scaffolded."""
    repo_dir = tmp_path / "projects" / "todo"
    repo_dir.mkdir(parents=True)
    (repo_dir / "pyproject.toml").write_text("[project]\nname='todo'\n", encoding="utf-8")
    coord = _coord_for(tmp_path, _asking_plan(cl.AXIS_SURFACE))
    await _drive(coord, "/dispatch todo | a todo app")
    reply = await _drive(coord, "/dispatch just decide for me")

    assert coord._clarifying.get("s") is None
    assert "/dispatch approve" in reply


@pytest.mark.asyncio
async def test_a_non_surface_assumed_axis_still_self_answers(tmp_path):
    """Scope/visual/persistence stay assumable — a wrong guess there is visible in the
    result and cheap to redo. Only the surface is neither."""
    coord = _coord_for(tmp_path, _asking_plan(cl.AXIS_SCOPE, cl.AXIS_VISUAL))
    await _drive(coord, "/dispatch todo | a todo app")
    reply = await _drive(coord, "/dispatch just decide for me")

    assert coord._clarifying.get("s") is None
    assert "/dispatch approve" in reply


@pytest.mark.asyncio
async def test_the_operators_answer_reaches_the_requirements_the_coder_reads(tmp_path):
    """#1197 — asking a question and discarding the answer would be worse than not asking.

    The clarifying turn refines ``build_plan.surface``; before this fix it left the ASSUMED
    default text riding into the coder's requirements block, so an operator who picked "In a
    web browser" still had "a simple command-line tool …" written down as their requirement.
    Both carriers must agree, and the answer must stop being labelled an assumption."""
    coord = _coord_for(tmp_path, _asking_plan(cl.AXIS_SURFACE, cl.AXIS_SCOPE))
    await _drive(coord, "/dispatch todo | a todo app")
    await _drive(coord, "/dispatch just decide for me")
    await _drive(coord, "/dispatch 2")  # "In a web browser"

    card = coord.pending_for("s")
    spec = card.spec
    # CARRIER A — the build signal. #1220: this was the assertion that passed only because
    # the fixture hand-wrote `candidates` onto a non-ambiguous surface.
    assert spec.build_plan["surface"] == "web", (
        "the operator's platform answer never reached the build signal — "
        "apply_clarification found no allowlist and returned the plan unchanged"
    )
    surface = [c for c in spec.clarifications if c.get("axes") == [cl.AXIS_SURFACE]]
    assert surface and surface[0]["answer"] == "In a web browser"
    assert surface[0]["assumed"] is False, "the operator's own answer is not an assumption"
    # And it now renders under the OPERATOR header, not the assumed one.
    block = cl.compose_requirements_block(spec.clarifications)
    assert "In a web browser" in block.split(cl._ASSUMED_HEADER)[0]
    assert cl.EMPTY_PROJECT_SURFACE_ANSWER not in block
    # The genuinely-assumed axis is untouched — this rewrites the surface and nothing else.
    assert cl.DEFAULT_AXIS_ANSWERS[cl.AXIS_SCOPE] in block

    # CARRIER B — the text the CODER actually reads. The card re-renders from the spec on
    # every turn; the prompt was baked at re-plan time and froze. Only the card was
    # visible to him, so a disagreement here is invisible until the wrong thing is built.
    prompt = card.tasks[0]["prompt"]
    assert acc.REQUIREMENTS_PROMPT_MARKER in prompt, "fixture lost its requirements section"
    assert "In a web browser" in prompt, (
        "the coder's prompt never learned the operator's platform answer"
    )
    assert cl.EMPTY_PROJECT_SURFACE_ANSWER not in prompt, (
        "the coder is still told to build the surface the operator rejected"
    )
    # The task dict's build-signal field (what the fleet resolves the scaffold from).
    assert card.tasks[0]["surface"] == "web"


@pytest.mark.asyncio
async def test_the_surface_choice_RE_PLANS_so_the_graded_criteria_follow_it(tmp_path):
    """#1224 N1 — the residue that mattered.

    `generate_plan` authors the criteria, the task name, the body AND the graded exam
    command from the goal it is given, and on this path that goal carried the system's
    ASSUMED command-line default, because the platform question is raised after that pass.
    Rewriting only the requirements block left the coder four signals — three saying
    command-line, including the GRADED one — so it was REWARDED for ignoring his answer:
    a browser app fails `pytest test_cli.py`, and with the scaffold now node a python CLI
    fails the build criterion too. He picks the browser and gets a BROKEN BUILD.

    So the choice re-plans. This asserts the re-plan is seeded with HIS answer, which is
    what makes the regenerated criteria and exam follow it."""
    seen: list[str] = []
    coord = _coord_for(tmp_path, _asking_plan(
        cl.AXIS_SURFACE, cl.AXIS_SCOPE, record_goals=seen))
    await _drive(coord, "/dispatch todo | a todo app")
    await _drive(coord, "/dispatch just decide for me")
    planned_before = len(seen)
    await _drive(coord, "/dispatch 2")  # In a web browser

    assert len(seen) == planned_before + 1, (
        "the platform choice did not trigger a re-plan — the criteria and the graded exam "
        "are still the ones authored from the assumed command-line default"
    )
    seed = seen[-1]
    assert "In a web browser" in seed, "his answer never reached the re-plan seed"
    assert cl.EMPTY_PROJECT_SURFACE_ANSWER not in seed, (
        "the re-plan was re-seeded with the system's assumed default"
    )
    # And the seed is composed the SAME way the #819 re-plan composes it — one goal shape
    # reaches the AO, not two.
    assert cl.REQUIREMENTS_SENTINEL in seed

    # The point of re-planning: the GRADED artifacts followed his answer. Before #1224 the
    # criterion read "the CLI prints a converted value" and the exam ran `pytest
    # test_cli.py` — so building what he asked for would have FAILED the grade.
    spec = coord.pending_for("s").spec
    graded = [c for c in spec.criteria if c.tier == "behavior"]
    assert graded, "fixture must carry a graded criterion or this asserts nothing"
    assert "page" in graded[0].text, f"criterion still command-line: {graded[0].text!r}"
    assert graded[0].check == "npm test", f"exam still command-line: {graded[0].check!r}"
    assert "CLI" not in graded[0].text


@pytest.mark.asyncio
async def test_the_re_planned_card_carries_the_NEW_coverage_measurement(tmp_path):
    """#1224 — `coverage_blocked` is a MEASUREMENT of whether THIS plan's behaviour checks
    can run. After a re-plan the plan it measured no longer exists, so carrying the
    pre-choice marker forward would either block approval over a finding about a discarded
    plan, or clear a block the regenerated plan warrants. A mutation run caught this line
    unasserted, which is how a fix with no test announces itself."""
    coord = _coord_for(tmp_path, _asking_plan(
        cl.AXIS_SURFACE, cl.AXIS_SCOPE,
        # pass 1 (the requirements re-plan) is blocked; pass 2 (his surface choice) is not.
        coverage_by_pass=["orphan-exam:c2", ""]))
    await _drive(coord, "/dispatch todo | a todo app")
    await _drive(coord, "/dispatch just decide for me")
    assert coord.pending_for("s") is None, "the menu should be open, not an approval card"

    await _drive(coord, "/dispatch 2")

    assert coord.pending_for("s").coverage_blocked == "", (
        "the card kept the PRE-CHOICE coverage marker — it describes a plan that was "
        "discarded when his answer re-planned it"
    )


@pytest.mark.asyncio
async def test_a_failed_re_plan_keeps_his_choice_and_never_relabels(tmp_path):
    """Fail-closed, #1152 shape. If the re-plan does not come back, his choice must not be
    lost AND the old command-line plan must not be relabelled and shipped — relabelling is
    exactly the broken-build outcome the re-plan exists to prevent."""
    coord = _coord_for(tmp_path, _asking_plan(
        cl.AXIS_SURFACE, cl.AXIS_SCOPE, fail_replan_after=1))
    await _drive(coord, "/dispatch todo | a todo app")
    await _drive(coord, "/dispatch just decide for me")
    reply = await _drive(coord, "/dispatch 2")

    assert coord.pending_for("s") is None, "a relabelled plan was shipped anyway"
    assert coord._clarifying.get("s") is not None, "his choice was thrown away"
    assert "wasn't lost" in reply and "/dispatch 2" in reply
    # Retrying the same number now succeeds and the answer is still his.
    reply2 = await _drive(coord, "/dispatch 2")
    assert "/dispatch approve" in reply2
    spec = coord.pending_for("s").spec
    assert spec.build_plan["surface"] == "web"


def _ambiguous_fork_plan(record_goals: "list | None" = None):
    """The menu's OTHER entry point (#1237): the 14B FLAGS an ambiguous platform fork, so
    `resolve_clarifying_question` raises the menu straight off the first pass — with no
    clarify questions asked and therefore NO clarifications at all.

    Every other fixture in this file reaches the menu through the #1174 assumed-surface
    fallback, which by construction leaves an assumed surface entry behind for the answer to
    be written into. This one leaves nothing, which is exactly the condition under which the
    answer used to vanish. Shaped like `_asking_plan` otherwise: the prompt is composed the
    way `generate_plan` composes it, and the criteria and the exam are authored FROM THE
    SEED, because that is the thing under test."""
    from shared.fleet.acceptance import AcceptanceCriterion, AcceptanceSpec, PlanResult

    async def plan_fn(repo, goal):
        if record_goals is not None:
            record_goals.append(goal)
        _, req_block = cl.split_planning_goal(goal)
        browser = "In a web browser" in req_block
        prompt = "Build the thing."
        if req_block:
            prompt += f"{acc.REQUIREMENTS_PROMPT_MARKER}\n{req_block}"
        return PlanResult(
            ok=True, tasks=[{"repo": repo, "task": "t", "prompt": prompt}],
            spec=AcceptanceSpec(
                "an app with buttons",
                (AcceptanceCriterion("c1", "the project builds", "build", ""),
                 AcceptanceCriterion(
                     "c2",
                     "the page shows a converted value" if browser
                     else "the CLI prints a converted value",
                     "behavior", "npm test" if browser else "pytest test_cli.py")),
                build_plan=(
                    _real_build_plan("web") if browser
                    else _real_build_plan(
                        "ambiguous", candidates=["desktop-gui", "web", "mobile"])
                ),
            ),
            message="planned",
        )
    return plan_fn


@pytest.mark.asyncio
async def test_the_model_flagged_fork_carries_his_answer_into_the_re_plan_seed(tmp_path):
    """#1237 — THE blocker, on the increment-4 path.

    The re-plan seeds from `record_operator_surface_choice`, which rewrote only an entry that
    was both assumed AND surface-tagged. This path arrives with the list EMPTY, so it rewrote
    nothing, composed an empty requirements block, and composed the BARE GOAL — a seed
    byte-identical to the one the first pass already ran on, with no platform in it. `_choose`
    then discarded the plan the menu was raised about, re-ran the whole ~6-7-call chain on
    that platform-blind seed, and finalized a DIFFERENT plan under "Got it — building it for:
    In a web browser". Nothing observed it in either direction."""
    seen: list[str] = []
    coord = _coord_for(tmp_path, _ambiguous_fork_plan(record_goals=seen))
    await _drive(coord, "/dispatch todo | an app with buttons")

    parked = coord._clarifying.get("s")
    assert parked is not None, "the flagged fork did not open the platform menu"
    assert tuple(parked.spec.clarifications) == (), (
        "precondition of the finding: this path reaches the menu with NO clarification "
        "for the answer to be written into"
    )
    planned_before = len(seen)
    reply = await _drive(coord, "/dispatch 2")  # In a web browser

    assert len(seen) == planned_before + 1, "the choice did not re-plan"
    seed = seen[-1]
    assert "In a web browser" in seed, (
        "his answer never reached the re-plan seed — the second pass ran on the same "
        "platform-blind goal as the first, and its criteria and exam were authored from it"
    )
    assert cl.REQUIREMENTS_SENTINEL in seed, "the seed is not composed the one shared way"

    # What the re-plan is FOR: the graded artifacts followed his answer.
    spec = coord.pending_for("s").spec
    graded = [c for c in spec.criteria if c.tier == "behavior"]
    assert graded, "fixture must carry a graded criterion or this asserts nothing"
    assert graded[0].check == "npm test", f"exam still command-line: {graded[0].check!r}"
    assert spec.build_plan["surface"] == "web"
    assert "Got it — building it for: In a web browser" in reply
    # And the answer is on the record, so the card can show it and the next dispatch recalls
    # it — an appended entry is a record, not a one-turn variable.
    assert [c["answer"] for c in spec.clarifications] == ["In a web browser"]
    assert spec.clarifications[0]["assumed"] is False
    assert spec.clarifications[0]["axes"] == [cl.AXIS_SURFACE]
    assert spec.clarifications[0]["question"] == "Where will you mainly use this?"


@pytest.mark.asyncio
async def test_the_seed_carries_the_gradeability_steer_and_the_card_shows_the_label(tmp_path):
    """#1237 F5. The label he picked replaced a default that also told the planner the build
    must be automatically checkable, and the criteria and exam are now authored from that
    seed — so answering honestly could produce a LESS gradeable plan than staying silent.

    The steer therefore rides the seed BESIDE his label. It must not follow the label into
    anything he reads, and it must not survive into the coder's prompt, which is recomposed
    from the record and holds only what he actually said."""
    seen: list[str] = []
    coord = _coord_for(tmp_path, _asking_plan(
        cl.AXIS_SURFACE, cl.AXIS_SCOPE, record_goals=seen))
    await _drive(coord, "/dispatch todo | a todo app")
    await _drive(coord, "/dispatch just decide for me")
    reply = await _drive(coord, "/dispatch 2")  # In a web browser

    steer = cl.surface_gradeability_steer("web")
    assert steer, "the web steer is empty — this test would assert nothing"
    assert steer in seen[-1], (
        "the re-plan seed carries only the bare menu label, so the gradeability clause "
        "EMPTY_PROJECT_SURFACE_ANSWER used to supply is gone from the pass that authors "
        "the criteria and the exam"
    )
    card = coord.pending_for("s")
    assert "In a web browser" in reply and steer not in reply, \
        "the steer leaked into what he reads"
    assert [c["answer"] for c in card.spec.clarifications if c.get("axes")
            and cl.AXIS_SURFACE in c["axes"]] == ["In a web browser"], \
        "his answer must be recorded verbatim, never annotated"
    assert steer not in card.tasks[0]["prompt"]


@pytest.mark.asyncio
async def test_his_answer_flips_a_build_plan_that_carries_no_candidates(tmp_path):
    """The #1174 door's allowlist, driven through the shape PRODUCTION produces.

    `apply_clarification` validates the answer against an allowlist. Its original allowlist
    was the plan's own ``candidates``, and `_parse_build_plan` attaches that key ONLY to an
    ``ambiguous`` surface — while this door fires precisely when the surface is CLEAR. So the
    allowlist was empty by construction, every answer was off-list, and the function returned
    the plan semantically unchanged: he tapped a platform and the build kept the one the
    system had assumed. #1220 carrier A made the allowlist the menu the caller actually
    rendered (`offered`), which is the same rule stated precisely rather than a loosening.

    Every other test on this path lets the re-seeded pass classify the answer for itself, so
    a green tells you nothing about whether the allowlist worked. This one PINS the re-plan's
    classification to command-line no matter what the seed says, so the finalized ``web`` can
    only have come from `apply_clarification` applying his answer. The plan is built by the
    REAL parser, so the missing ``candidates`` key is production's, not a fixture's."""
    coord = _coord_for(tmp_path, _asking_plan(
        cl.AXIS_SURFACE, cl.AXIS_SCOPE, pin_replan_surface="command-line"))
    await _drive(coord, "/dispatch todo | a todo app")
    await _drive(coord, "/dispatch just decide for me")

    parked = coord._clarifying.get("s")
    assert parked is not None, "the assumed-surface door did not open the menu"
    assert "candidates" not in parked.spec.build_plan, (
        "precondition of the finding: the real parser attaches candidates only to an "
        "ambiguous surface, and this door fires on a CLEAR one — so the plan's own "
        "allowlist is absent and cannot admit anything"
    )
    assert [o["surface"] for o in parked.question["options"]] == ["desktop-gui", "web"]

    reply = await _drive(coord, "/dispatch 2")  # In a web browser

    card = coord.pending_for("s")
    assert card.spec.build_plan["surface"] == "web", (
        "his answer did not reach the build signal — the plan the fleet receives still "
        "says command-line while the card and the note say browser"
    )
    assert card.tasks[0]["surface"] == "web", "the choice never reached the task dicts"
    # The two lines he reads agree, which is the visible half of the same defect.
    assert "Got it — building it for: In a web browser" in reply
    assert "Building this as: a web app" in reply


@pytest.mark.asyncio
async def test_an_unwired_plan_fn_reports_the_wiring_gap_not_an_endless_retry(tmp_path):
    """#1237 F2. `_replan_after_surface_choice` returned the same `None` for a missing
    plan/execute wiring as for a transport failure, so the operator was told to reply the
    same number again — a retry loop with no exit but `/dispatch reject`, against a
    dependency no retry can supply. Every other site in this class says so plainly.

    The wiring is dropped after the menu is parked because that is the live shape: the hold
    is durable across a restart (#1116), and a restart is precisely when the AO wiring may
    not be back."""
    coord = _coord_for(tmp_path, _asking_plan(cl.AXIS_SURFACE))
    await _drive(coord, "/dispatch todo | a todo app")
    await _drive(coord, "/dispatch just decide for me")
    assert coord._clarifying.get("s") is not None
    coord._plan_fn = None

    reply = await _drive(coord, "/dispatch 2")

    assert "isn't connected yet" in reply, f"not the wiring notice: {reply!r}"
    assert "again to retry" not in reply, "an unwired dependency was offered as a retry"
    assert coord.pending_for("s") is None, "a relabelled plan was shipped anyway"
    assert coord._clarifying.get("s") is not None, "his choice was thrown away"


@pytest.mark.asyncio
async def test_a_failed_re_plan_tells_him_what_actually_went_wrong(tmp_path):
    """#1237 F3. The failure branch logged `plan.message` and showed him a fixed sentence, so
    the only account of WHY reached a file he does not read. Its sibling
    `_replan_with_requirements` has always surfaced it."""
    coord = _coord_for(tmp_path, _asking_plan(
        cl.AXIS_SURFACE, cl.AXIS_SCOPE, fail_replan_after=1))
    await _drive(coord, "/dispatch todo | a todo app")
    await _drive(coord, "/dispatch just decide for me")

    reply = await _drive(coord, "/dispatch 2")

    assert "No response from the AO." in reply, (
        "the plan said why it failed and he was shown a fixed sentence instead"
    )
    assert "wasn't lost" in reply and "/dispatch 2" in reply


@pytest.mark.asyncio
async def test_a_re_plan_that_returns_nothing_to_build_is_not_reported_as_a_failure(tmp_path):
    """#1237 F3, the other half. `ok=True` with no tasks is not a transport failure — nothing
    went wrong, the pass simply produced nothing buildable. It fell into the same branch and
    became the same "reply the same number to retry", which for a deterministic planner is
    the same loop again. Say what happened and point at the moves that change something."""
    coord = _coord_for(tmp_path, _asking_plan(
        cl.AXIS_SURFACE, cl.AXIS_SCOPE, empty_replan_after=1))
    await _drive(coord, "/dispatch todo | a todo app")
    await _drive(coord, "/dispatch just decide for me")

    reply = await _drive(coord, "/dispatch 2")

    assert "no tasks" in reply, f"the empty-plan exit is indistinguishable: {reply!r}"
    assert "again to retry" not in reply, "an identical retry was offered for a deterministic pass"
    assert "/dispatch reject" in reply, "he was left with no move that changes anything"
    assert coord.pending_for("s") is None, "a relabelled plan was shipped anyway"
    assert coord._clarifying.get("s") is not None, "his choice was thrown away"


@pytest.mark.asyncio
async def test_the_note_never_claims_a_platform_the_plan_did_not_take(tmp_path):
    """#1237 F4 — the arc's own defect class inside the fix for it.

    "Got it — building it for: X" was emitted unconditionally. When the re-plan returns no
    parseable build_plan, `apply_clarification` returns None, the card omits the platform line
    and the scaffold reads nothing — and that sentence still told him the choice had been
    applied. A control reporting a pass it did not measure. His answer DID reach the seed and
    the requirements, so the honest note says that much and stops."""
    coord = _coord_for(tmp_path, _asking_plan(
        cl.AXIS_SURFACE, cl.AXIS_SCOPE, replan_without_build_plan=True))
    await _drive(coord, "/dispatch todo | a todo app")
    await _drive(coord, "/dispatch just decide for me")

    reply = await _drive(coord, "/dispatch 2")

    card = coord.pending_for("s")
    assert card is not None and card.spec.build_plan is None, \
        "fixture must reach the no-build_plan shape or this asserts nothing"
    assert "Building this as" not in reply, "the card named a platform it does not carry"
    assert "building it for" not in reply, (
        "the note asserted the choice reached the build signal, which it did not"
    )
    assert "In a web browser" in reply, "his choice was not acknowledged at all"
    # It reached the two carriers it really did reach.
    assert "In a web browser" in card.tasks[0]["prompt"]
    assert any(c["answer"] == "In a web browser" for c in card.spec.clarifications)


@pytest.mark.asyncio
async def test_an_out_of_range_platform_answer_is_still_refused(tmp_path):
    """#1220 anti-rubber-stamp. Widening `apply_clarification` to accept an `offered`
    allowlist must not turn validation off: a surface that was NOT on the menu he saw is
    still refused, and the plan keeps the surface it had."""
    coord = _coord_for(tmp_path, _asking_plan(cl.AXIS_SURFACE))
    await _drive(coord, "/dispatch todo | a todo app")
    await _drive(coord, "/dispatch just decide for me")
    parked = coord._clarifying["s"]
    # The fresh-repo menu offers desktop-gui + web only; mobile is suppressed (#1161 F3).
    assert [o["surface"] for o in parked.question["options"]] == ["desktop-gui", "web"]

    reply = await _drive(coord, "/dispatch 9")  # out of range

    spec = coord.pending_for("s").spec
    assert spec.build_plan["surface"] == "command-line", \
        "an out-of-range answer moved the build signal"
    assert "didn't catch which option" in reply


def _generate_plan_with_requirements(repo, projects_dir, requirements: str):
    """Drive the REAL `generate_plan` to get a compiled task prompt whose requirements
    section was composed by the WRITER (#1224 N2). Only the MODEL is stood in for, and the
    routing markers are imported from the suite that already proves them against
    `generate_plan` — approximating them here is how the first attempt at this lock ended
    up testing nothing."""
    from shared.tests.test_acceptance_clarify import _gen

    return acc.generate_plan(
        "a todo app", repo, generate_fn=_gen([]), projects_dir=projects_dir,
        clarify=False, requirements=requirements,
    )


def test_the_requirements_marker_round_trips_writer_to_rewriter(tmp_path):
    """#1224 N2 — the ONE hazard the marker's own docstring names, finally locked.

    A reviewer drifted the WRITER by a single space (`build  ---`) while the rewriter held
    the constant: all 323 tests passed and carrier B silently reverted to the #1220 defect.
    The failure is silent by construction — `partition` finds nothing, every task is
    skipped, nothing raises — which inverts fail-loud in a correctness path.

    The lock must run the REAL writer. My first attempt at it composed the prompt from
    `REQUIREMENTS_PROMPT_MARKER` directly, so drifting the writer's literal inside
    `generate_plan` changed nothing it could see — the mutant SURVIVED, and the lock for the
    named hazard was itself an instance of the fixture problem it was written after. The
    writer is `generate_plan`; drive it."""
    proj = tmp_path / "projects"
    repo = proj / "myapp"
    (repo / ".git").mkdir(parents=True)
    (repo / "main.py").write_text("x = 1\n", encoding="utf-8")

    assumed = cl.compose_requirements_block([
        {"question": "q", "answer": "a command-line tool", "assumed": True,
         "axes": [cl.AXIS_SURFACE]},
    ])
    plan = _generate_plan_with_requirements(repo, proj, assumed)
    written = plan.tasks[0]["prompt"]
    assert "a command-line tool" in written, "the writer did not compose the block at all"

    # ...now the REWRITER, on what the WRITER actually emitted.
    acc.recompose_task_requirements(plan.tasks, [
        {"question": "q", "answer": "In a web browser", "assumed": False,
         "axes": [cl.AXIS_SURFACE]},
    ])
    prompt = plan.tasks[0]["prompt"]
    assert "In a web browser" in prompt, (
        "the rewriter could not find the WRITER's marker — they have drifted apart and "
        "carrier B is silently a no-op"
    )
    assert "a command-line tool" not in prompt
    assert prompt.count(acc.REQUIREMENTS_PROMPT_MARKER) == 1, "the section was duplicated"


def test_recompose_is_idempotent_and_leaves_unmarked_tasks_alone():
    """Applying it twice must not stack sections, and a task that never carried a
    requirements block must not acquire one."""
    marked = {"prompt": f"body{acc.REQUIREMENTS_PROMPT_MARKER}\nold"}
    unmarked = {"prompt": "body with no requirements section"}
    entries = [{"question": "q", "answer": "In a web browser", "assumed": False,
                "axes": [cl.AXIS_SURFACE]}]

    acc.recompose_task_requirements([marked, unmarked], entries)
    once = marked["prompt"]
    acc.recompose_task_requirements([marked, unmarked], entries)

    assert marked["prompt"] == once, "recompose is not idempotent"
    assert marked["prompt"].count(acc.REQUIREMENTS_PROMPT_MARKER) == 1
    assert unmarked["prompt"] == "body with no requirements section"
    # Empty clarifications drop the section rather than leaving a stale one.
    acc.recompose_task_requirements([marked], [])
    assert acc.REQUIREMENTS_PROMPT_MARKER not in marked["prompt"]
    assert marked["prompt"] == "body"


def test_an_empty_offered_list_denies_everything():
    """#1224 N3. `raw = offered or …` survives on a plan with no candidates, because both
    forms deny identically there. On an AMBIGUOUS plan they diverge: `offered=[]` must deny
    `web`, and a truthiness coalesce would fall through to the model's own fork list and
    ACCEPT it. Deny-by-default is the sentence the docstring leans on, so it is asserted
    where the two implementations actually differ."""
    amb = _real_build_plan("ambiguous", candidates=["desktop-gui", "web", "mobile"])
    assert amb["candidates"], "fixture must carry a real fork or the test is vacuous"
    assert acc.apply_clarification(amb, "web", offered=[])["surface"] == "ambiguous"
    assert acc.apply_clarification(amb, "web", offered=())["surface"] == "ambiguous"
    # ...while omitting `offered` entirely still consults the model's fork (increment 4).
    assert acc.apply_clarification(amb, "web")["surface"] == "web"


def test_apply_clarification_refuses_a_surface_that_was_not_offered():
    """The unit-level anti-rubber-stamp, at every shape the allowlist can take."""
    plan = _real_build_plan("command-line")
    assert "candidates" not in plan, "the parser must not attach candidates here"

    # On the menu -> accepted.
    assert acc.apply_clarification(
        plan, "web", offered=["desktop-gui", "web"])["surface"] == "web"
    # NOT on the menu -> refused, plan unchanged.
    assert acc.apply_clarification(
        plan, "mobile", offered=["desktop-gui", "web"])["surface"] == "command-line"
    # Deny-by-default: an empty or absent allowlist accepts nothing.
    for empty in ([], (), None):
        assert acc.apply_clarification(
            plan, "web", offered=empty)["surface"] == "command-line", empty
    # A forged/garbage menu entry cannot smuggle a surface through — the allowlist is
    # still intersected with the real surfaces.
    assert acc.apply_clarification(
        plan, "ambiguous", offered=["ambiguous", "unknown"])["surface"] == "command-line"
    assert acc.apply_clarification(
        plan, "nonsense", offered=["nonsense"])["surface"] == "command-line"


def test_increment_4_keeps_its_candidates_based_validation():
    """Toggle-off bar: the ambiguous-fork path passes no `offered` and must behave exactly
    as it did pre-#1220 — validated against the candidates the 14B itself flagged."""
    amb = _real_build_plan("ambiguous", candidates=["desktop-gui", "web", "mobile"])
    assert amb["candidates"] == ["desktop-gui", "web", "mobile"]
    assert acc.apply_clarification(amb, "web")["surface"] == "web"
    assert acc.apply_clarification(amb, "web")["candidates"] == []
    # Off the model's own fork list -> still refused, with no `offered` in play.
    off = acc.apply_clarification(amb, "library")
    assert off["surface"] == "ambiguous"


def test_record_operator_surface_choice_rewrites_the_assumed_entry_and_nothing_else():
    """The REWRITE half: it targets exactly what platform_was_assumed targets. An entry
    already carrying the operator's own words is never overwritten — a free-text reply holds
    his answers for EVERY axis it covered in one entry, so relabelling it to a platform would
    destroy the rest of what he said."""
    entries = [
        {"question": "q", "answer": "old", "assumed": True, "axes": [cl.AXIS_SURFACE]},
        {"question": "q", "answer": "keep", "assumed": True, "axes": [cl.AXIS_SCOPE]},
    ]
    frozen = [dict(e) for e in entries]
    out = cl.record_operator_surface_choice(entries, "In a web browser", question="Where?")
    assert entries == frozen, "input must not be mutated"
    assert len(out) == 2, "a rewritten entry must not ALSO be appended"
    assert out[0] == {"question": "q", "answer": "In a web browser",
                      "assumed": False, "axes": [cl.AXIS_SURFACE]}
    assert out[1]["answer"] == "keep" and out[1]["assumed"] is True
    # A blank label records nothing at all — there is no answer to record.
    assert cl.record_operator_surface_choice(entries, "  ") == frozen


def test_record_operator_surface_choice_appends_when_there_is_nothing_to_rewrite():
    """The APPEND half (#1237), and the reason the rewrite alone shipped a broken build.

    The menu's OTHER entry point — the model-flagged ambiguous fork — fires regardless of
    clarifications, so the list handed here is routinely EMPTY. Returning it unchanged made
    his answer reach nothing: an empty list renders an empty requirements block, which
    composes the bare goal, which is the seed the pre-choice pass already ran on."""
    appended = cl.record_operator_surface_choice(
        [], "In a web browser", question="Where will you mainly use this?")
    assert appended == [{
        "question": "Where will you mainly use this?",
        "answer": "In a web browser", "assumed": False, "axes": [cl.AXIS_SURFACE],
    }]
    # The block his answer must reach renders identically on both paths.
    assert cl.compose_requirements_block(appended) == cl.compose_requirements_block(
        cl.record_operator_surface_choice(
            [{"question": "q", "answer": "assumed text", "assumed": True,
              "axes": [cl.AXIS_SURFACE]}],
            "In a web browser",
        )
    )
    # An UNTAGGED assumed entry is not a surface claim (platform_was_assumed refuses to guess
    # one), so it is left alone and the answer is recorded beside it — never a silent no-op.
    untagged = cl.record_operator_surface_choice([{"answer": "a", "assumed": True}], "x")
    assert untagged[0] == {"answer": "a", "assumed": True}
    assert untagged[1]["answer"] == "x" and untagged[1]["assumed"] is False
    # An operator-authored surface entry is preserved verbatim; the menu answer is the more
    # specific and more recent one and lands beside it.
    authored = cl.record_operator_surface_choice(
        [{"question": "q", "answer": "mine", "assumed": False,
          "axes": [cl.AXIS_SURFACE, cl.AXIS_SCOPE]}],
        "In a web browser",
    )
    assert authored[0]["answer"] == "mine", "an operator-authored entry is never overwritten"
    assert authored[1]["answer"] == "In a web browser"
    # Total: no clarifications at all, and no question text, still records the answer.
    assert cl.record_operator_surface_choice(None, "x") == [
        {"question": "", "answer": "x", "assumed": False, "axes": [cl.AXIS_SURFACE]}
    ]


def test_the_gradeability_steer_is_for_the_planner_and_names_no_platform():
    """#1237 F5. His menu answer displaces EMPTY_PROJECT_SURFACE_ANSWER, which carried a
    second clause the bare label does not — that the build's behaviour must be checkable
    automatically. With the criteria and the exam now authored from that seed, losing it lets
    an answered menu produce a LESS gradeable plan than an unanswered one.

    Two properties make carrying it safe. It names NO platform, so it can never contribute a
    surface of its own; and it renders as a system line, so the #1161 operator-words scan
    drops it even while it rides the same block."""
    assert set(cl.SURFACE_GRADEABILITY_STEER) == {"desktop-gui", "web", "mobile"}, \
        "the menu's own option surfaces are the ones that need a steer"
    for surface, steer in cl.SURFACE_GRADEABILITY_STEER.items():
        assert acc.operator_platform_signal(steer) == "", (
            f"the {surface} steer names a platform ({steer!r}) — it could override his "
            "choice through the operator-words scan"
        )
        assert cl.surface_gradeability_steer(surface) == steer
    # Total + fail-safe: an off-vocabulary surface contributes nothing rather than a guess.
    assert cl.surface_gradeability_steer("command-line") == ""
    assert cl.surface_gradeability_steer("") == ""
    assert cl.surface_gradeability_steer(None) == ""

    answer = {"question": "q", "answer": "In a web browser", "assumed": False,
              "axes": [cl.AXIS_SURFACE]}
    plain = cl.compose_requirements_block([answer])
    steered = cl.compose_planning_steer(plain, cl.surface_gradeability_steer("web"))
    assert cl.compose_planning_steer(plain, "") == plain, "a blank steer changes nothing"
    assert cl.SURFACE_GRADEABILITY_STEER["web"] in steered
    # The operator-words extractor sees ONLY his words; the coder-corpus extractor sees both.
    assert cl.operator_authored_answers(steered) == ("In a web browser",)
    assert cl.SURFACE_GRADEABILITY_STEER["web"] in cl.operator_answers_from_block(steered)


def test_a_task_body_that_echoes_the_requirements_marker_keeps_its_body():
    """#1237 F6. The rewriter matched the FIRST marker; the writer appends the LAST one. A
    model-authored body that quotes the heading it was handed therefore split the prompt at
    the ECHO, silently discarding every real word between it and the section. Low likelihood,
    unbounded blast radius, and nothing observed it."""
    body = (f"Build the thing.{acc.REQUIREMENTS_PROMPT_MARKER}\n"
            "(the model quoted the heading back at us)")
    task = {"prompt": f"{body}{acc.REQUIREMENTS_PROMPT_MARKER}\nthe stale requirements"}

    acc.recompose_task_requirements([task], [
        {"question": "q", "answer": "In a web browser", "assumed": False,
         "axes": [cl.AXIS_SURFACE]},
    ])

    assert task["prompt"].startswith(body), (
        "the rewriter split the prompt at the ECHOED marker and threw away the task body"
    )
    assert "the model quoted the heading back at us" in task["prompt"]
    assert "In a web browser" in task["prompt"]
    assert "the stale requirements" not in task["prompt"]


# ---------------------------------------------------------------------------
# DURABILITY — the distinction, not the sentence (#1197)
# ---------------------------------------------------------------------------
#
# The operator's bar: "every fix is durable … many uses, device reboots, complex
# projects." A wording fix that can drift back to the false form without a test going
# red is not fixed. So these lock the PROPERTY — no operator-attributing claim may sit
# over a system-chosen answer — across EVERY operator-facing renderer, by DRIVING each
# renderer rather than grepping its source. A future edit is free to rewrite any
# sentence; it is not free to re-attribute.

#: Phrases that assert the OPERATOR supplied something. None may appear anywhere near an
#: answer the system invented, in any renderer, ever. Add to this list, never subtract.
OPERATOR_ATTRIBUTION_CLAIMS = (
    "person clarified", "you asked for", "you asked me for", "you told me",
    "you said", "your requirements", "you requested", "as requested",
    "you specified", "what you told me", "you chose", "you picked",
)


def _assumed_only():
    """The exact shape of the operator's failing run: every answer system-chosen."""
    return [
        {"question": "Where will you use it?", "assumed": True,
         "axes": [cl.AXIS_SURFACE], "answer": cl.EMPTY_PROJECT_SURFACE_ANSWER},
        {"question": "How big?", "assumed": True, "axes": [cl.AXIS_SCOPE],
         "answer": cl.DEFAULT_AXIS_ANSWERS[cl.AXIS_SCOPE]},
    ]


def test_no_operator_attribution_over_an_assumed_answer_in_the_coder_prompt():
    """Renderer 1 — the requirements block, which is what the coder reads and what the
    operator read in the run log for 20260729-164648-bd."""
    block = cl.compose_requirements_block(_assumed_only()).lower()
    assert block, "the renderer produced nothing — the probe would pass vacuously"
    for claim in OPERATOR_ATTRIBUTION_CLAIMS:
        assert claim not in block, f"{claim!r} attributes a system choice to the operator"


def test_no_operator_attribution_over_an_assumed_answer_on_the_plan_card():
    """Renderer 2 — the approval card, the operator's PRIMARY read.

    Nothing locked this before #1197: the card's assumed section could have been reworded
    to "Here's what you told me" and every test would have stayed green."""
    spec = AcceptanceSpec(
        "a little kitchen conversion helper",
        (AcceptanceCriterion("c1", "the project builds", "build", ""),),
        clarifications=tuple(_assumed_only()),
    )
    card = acc.render_criteria_preview(spec, ecosystem="unknown").lower()
    assert cl.EMPTY_PROJECT_SURFACE_ANSWER.lower() in card, \
        "the assumed answer is not on the card — the probe would pass vacuously"
    for claim in OPERATOR_ATTRIBUTION_CLAIMS:
        assert claim not in card, f"{claim!r} attributes a system choice to the operator"


def test_the_card_still_says_plainly_that_the_system_chose():
    """The other half: absence of a false claim is not the same as presence of a true
    one. Silence would technically pass the probe above and tell the operator nothing."""
    spec = AcceptanceSpec(
        "a helper", (AcceptanceCriterion("c1", "builds", "build", ""),),
        clarifications=tuple(_assumed_only()),
    )
    card = acc.render_criteria_preview(spec, ecosystem="unknown")
    assert "asked me to decide" in card.lower()
    block = cl.compose_requirements_block(_assumed_only())
    assert "did NOT ask for these" in block and "I picked them" in block


def test_a_surface_nobody_was_asked_about_says_where_it_came_from():
    """#1219 case (d), the cheap half. When the clarify stage judged the goal sufficient,
    nobody was asked and no clarification covers the surface — yet the card stated the
    platform as flat fact, indistinguishable from a choice he had made."""
    spec = AcceptanceSpec(
        "a kitchen helper", (AcceptanceCriterion("c1", "builds", "build", ""),),
        build_plan=_real_build_plan("command-line"), clarifications=(),
    )
    card = acc.render_criteria_preview(spec, ecosystem="unknown")
    assert "Building this as: a command-line tool." in card
    assert "I worked that out from your goal" in card
    assert "you weren't asked to pick" in card
    # A disclosure, not an accusation: no operator-attributing claim appears.
    for claim in OPERATOR_ATTRIBUTION_CLAIMS:
        assert claim not in card.lower(), claim


@pytest.mark.parametrize("assumed", [True, False])
def test_a_surface_that_WAS_put_to_him_keeps_the_bare_line(assumed):
    """Toggle-off bar. Both cases that already disclose themselves elsewhere on the card
    ("what you told me" / "you asked me to decide") keep the line byte-identical, so #1219
    adds no noise to the paths #1174 and #1197 already made honest."""
    spec = AcceptanceSpec(
        "a kitchen helper", (AcceptanceCriterion("c1", "builds", "build", ""),),
        build_plan=_real_build_plan("command-line"),
        clarifications=({"question": "Where?", "answer": "on this computer",
                         "assumed": assumed, "axes": [cl.AXIS_SURFACE]},),
    )
    card = acc.render_criteria_preview(spec, ecosystem="unknown")
    assert "Building this as: a command-line tool.\n" in card
    assert "I worked that out from your goal" not in card


def test_surface_axis_helper_agrees_with_platform_was_assumed():
    """The two helpers must never disagree about which entry IS the surface, or the card
    could disclose one story while the gate acts on another."""
    surface_assumed = [{"answer": "a", "assumed": True, "axes": [cl.AXIS_SURFACE]}]
    surface_answered = [{"answer": "a", "assumed": False, "axes": [cl.AXIS_SURFACE]}]
    other_axis = [{"answer": "a", "assumed": True, "axes": [cl.AXIS_SCOPE]}]
    untagged = [{"answer": "a", "assumed": True}]

    assert acc.surface_axis_was_put_to_the_operator(surface_assumed)
    assert acc.platform_was_assumed(surface_assumed)
    assert acc.surface_axis_was_put_to_the_operator(surface_answered)
    assert not acc.platform_was_assumed(surface_answered)
    for none_of_them in (other_axis, untagged, [], None, [42, "x"]):
        assert not acc.surface_axis_was_put_to_the_operator(none_of_them)
        assert not acc.platform_was_assumed(none_of_them)


def test_an_operator_authored_answer_may_still_be_attributed_to_them():
    """The toggle: the vocabulary above is banned over ASSUMED answers, not banned
    outright. An answer the operator really gave is theirs, and the card says so —
    otherwise this suite would 'pass' by deleting all attribution everywhere."""
    spec = AcceptanceSpec(
        "a helper", (AcceptanceCriterion("c1", "builds", "build", ""),),
        clarifications=({"question": "Where?", "answer": "in a web browser",
                         "assumed": False, "axes": [cl.AXIS_SURFACE]},),
    )
    card = acc.render_criteria_preview(spec, ecosystem="unknown")
    assert "what you told me" in card.lower(), \
        "an answer the operator DID give must still be credited to them"


@pytest.mark.asyncio
@pytest.mark.parametrize("repo_files,label", [
    ({"pyproject.toml": "[project]\nname='x'\n"}, "existing python project"),
    ({"pyproject.toml": "[project]\nname='x'\n",
      "package.json": '{"name":"x"}',
      "src/App/App.csproj": "<Project/>"}, "multi-language existing repo"),
    ({"packages/app/package.json": '{"name":"app"}'}, "monorepo, scaffold buried deep"),
])
async def test_the_axis_is_recorded_on_complex_projects_too(tmp_path, repo_files, label):
    """Durability across project shapes. #1161's incident was an empty repo, but the
    RECORD must be honest everywhere — an existing repo does not reach the platform
    question (deliberate, #1174's narrowness) and still records what it assumed."""
    repo = tmp_path / "projects" / "todo"
    repo.mkdir(parents=True)
    for rel, body in repo_files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")

    coord = _coord_for(tmp_path, _asking_plan(cl.AXIS_SURFACE, cl.AXIS_SCOPE))
    await _drive(coord, "/dispatch todo | add a feature")
    reply = await _drive(coord, "/dispatch just decide for me")

    assert coord._clarifying.get("s") is None, f"{label}: an existing repo was re-asked"
    assert "/dispatch approve" in reply
    cls = coord.pending_for("s").spec.clarifications
    assert cls and all(c.get("axes") for c in cls), \
        f"{label}: a quick dispatch recorded an untagged clarification"
    # And the attribution property holds here too, not only on the empty-repo path.
    block = cl.compose_requirements_block(cls).lower()
    for claim in OPERATOR_ATTRIBUTION_CLAIMS:
        assert claim not in block, f"{label}: {claim!r} over a system choice"


@pytest.mark.asyncio
async def test_the_forced_question_is_filtered_before_parking(tmp_path):
    """Order lock, driven: suppression runs AFTER the forced question is built, or a fresh
    repo's menu would carry the phone option the corridor refuses to honour. Observed on
    the PARKED question — the thing that survives a restart — not on the source text."""
    coord = _coord_for(tmp_path, _asking_plan(cl.AXIS_SURFACE))
    await _drive(coord, "/dispatch todo | a todo app")
    await _drive(coord, "/dispatch just decide for me")

    parked = coord._clarifying["s"]
    assert [o["surface"] for o in parked.question["options"]] == ["desktop-gui", "web"]
    assert parked.question == acc.suppress_phone_option_for_fresh_repo(
        acc.platform_question_for_assumed_surface()
    )


# ---- #1161 F-A: the weak-tier operator vocabulary, driven FROM the table ----
#
# THE STRUCTURAL CONTROL for the operator-vocabulary class (third instance in one day,
# 2026-07-29: webpage variants -> bare "ecommerce site" -> bare "page"). LESSONS Rule 3
# requires the third instance to ship a control, not a fourth patch.
#
# Every case below is generated FROM :data:`acc.OPERATOR_WEB_VOCABULARY`. That is the
# whole point: a term added to the table without its exclusions cannot ship silently,
# because these tests enumerate the table rather than restating a hand-written list.
# The failure this guards is not a crash — it is the system being UNABLE TO HEAR a word
# the operator used, which raises nothing and renders as a confident wrong plan.

_VOCAB_KEYS = sorted(acc.OPERATOR_WEB_VOCABULARY)


@pytest.mark.parametrize("key", _VOCAB_KEYS)
def test_every_weak_tier_term_reads_web_when_bare(key: str) -> None:
    """Each term, used bare and unqualified, names web. The tier's whole purpose."""
    noun = "site" if key == "site" else "page"
    assert acc.operator_platform_signal(f"a {noun} for my recipes") == "web"


@pytest.mark.parametrize("key", _VOCAB_KEYS)
def test_every_weak_tier_modifier_disqualifies_its_occurrence(key: str) -> None:
    """Every non-web modifier in the table actually suppresses the signal. Enumerated so
    a term contributed without exclusions fails here rather than in a live plan."""
    term = acc.OPERATOR_WEB_VOCABULARY[key]
    noun = "site" if key == "site" else "page"
    assert term.modifiers, f"{key!r} contributes no modifiers — is that deliberate?"
    for modifier in sorted(term.modifiers):
        text = f"notes about the {modifier} {noun}"
        assert acc.operator_platform_signal(text) == "", (
            f"{modifier!r} + {noun!r} must not read web ({text!r})"
        )


@pytest.mark.parametrize("key", _VOCAB_KEYS)
def test_every_weak_tier_follower_disqualifies_its_occurrence(key: str) -> None:
    term = acc.OPERATOR_WEB_VOCABULARY[key]
    noun = "site" if key == "site" else "page"
    for follower in sorted(term.followers):
        text = f"handle the {noun} {follower}"
        assert acc.operator_platform_signal(text) == "", (
            f"{noun!r} + {follower!r} must not read web ({text!r})"
        )


@pytest.mark.parametrize("key", _VOCAB_KEYS)
def test_numeric_follower_rule_is_honoured_as_the_table_declares(key: str) -> None:
    """A numbered page is a document page. Asserted in BOTH directions off the flag, so
    the table's declaration and the code cannot drift apart."""
    term = acc.OPERATOR_WEB_VOCABULARY[key]
    noun = "site" if key == "site" else "page"
    signal = acc.operator_platform_signal(f"go to {noun} 3")
    if term.numeric_follower_excludes:
        assert signal == "", f"{noun!r} + digit must not read web"
    else:
        assert signal == "web"


@pytest.mark.parametrize("key", _VOCAB_KEYS)
@pytest.mark.parametrize(
    "named,expected",
    [
        ("a desktop app", "desktop-gui"),
        ("a command line tool", "command-line"),
        ("an app for my phone", "mobile"),
    ],
)
def test_explicit_platform_words_outrank_every_weak_term(
    key: str, named: str, expected: str
) -> None:
    """The weak tier never overrides a word the operator actually said. This is the
    precedence rule the whole #1161 arc exists to protect, enumerated over the table so a
    new term cannot quietly acquire override power."""
    noun = "site" if key == "site" else "page"
    assert acc.operator_platform_signal(f"{named} for my {noun}") == expected


def test_the_operator_words_that_caused_1161_F_A_now_read_web() -> None:
    """The LA's verbatim ask from the 2026-07-29 ceremony drive. Before this change the
    scan returned '' — his words never reached the precedence rule, the refiner saw an
    unanswered platform question, and the card said 'Building this as: a command-line
    tool' for a recipe web page."""
    goal = (
        "one page that displays my two recipes from assets/recipes.txt as vertical "
        "steps with my photos"
    )
    assert acc.operator_platform_signal(goal) == "web"


def test_proper_noun_page_is_not_a_web_signal() -> None:
    """Conservative by design: a capitalized non-sentence-initial term reads as a name.
    Sentence-initial capitalisation is ordinary prose and still counts."""
    assert acc.operator_platform_signal("ask Page about the invoices") == ""
    assert acc.operator_platform_signal("Page that shows my recipes") == "web"


def test_weak_tier_probe_fails_when_the_term_is_removed_from_the_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TOGGLE-PROOF (security principle 12). Proves the table is what carries the signal —
    without it, a passing test above could be passing for some unrelated reason. Remove
    'page' from the vocabulary and the LA's sentence must go dark again."""
    reduced = {
        k: v for k, v in acc.OPERATOR_WEB_VOCABULARY.items() if k != "page"
    }
    monkeypatch.setattr(acc, "OPERATOR_WEB_VOCABULARY", reduced)
    goal = "one page that displays my two recipes"
    assert acc.operator_platform_signal(goal) == "", (
        "with 'page' removed the signal must vanish — if it survives, something other "
        "than the vocabulary table is producing it and this control does not control it"
    )
