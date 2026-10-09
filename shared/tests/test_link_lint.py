"""Regression locks for :mod:`shared.fleet.link_lint` — DoD capability 15.

The load-bearing tests here are not the ones proving a broken link is found. They are:

* :func:`test_the_real_escaped_link_is_found_in_both_places` — drives the ACTUAL delivered
  site the Lead Architect reviewed on 2026-08-08, not a fixture. Mocks lie; this one
  cannot, because the bytes are the ones that shipped.
* :func:`test_a_site_with_no_pages_is_ABSENT_not_clean` — the honesty lock. A scan that
  examined nothing must never report a clean result.
* :func:`test_toggle_proof_*` — security_by_design principle 12: every control ships with
  proof it FAILS when disengaged, so "secure" can be told apart from "the probe cannot
  reach it".
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.fleet import link_lint

#: The delivered site the operator reviewed. Its broken "View Details" link is the
#: defect this whole module exists for. Skipped rather than failed when absent: the
#: battery archives are state, not repository content, so a clean checkout legitimately
#: lacks them — but when it IS present it is the strongest evidence available.
_REAL_SITE = Path(
    "C:/Users/mrbla/agentic-setup/state/battery/night-20260807-230003/"
    "repos-archived/battery-b9-pottery-site"
)


def _site(tmp_path: Path, files: dict[str, str]) -> Path:
    """Materialise a site tree from a {relative-path: content} map."""
    root = tmp_path / "site"
    for rel, content in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return root


# ---------------------------------------------------------------------------
# The real artifact
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _REAL_SITE.is_dir(), reason="battery archive not present in this checkout")
def test_the_real_escaped_link_is_found_in_both_places() -> None:
    """The operator clicked 'View Details' and got JSON. Both copies must be found.

    The link lives in ``public/app.js`` AND in an inline ``<script>`` in
    ``public/pieces.html``. An HTML parser is required to treat script content as opaque
    text, so a parser-only scan reports exactly half of this defect — which is what the
    first implementation did. Asserting on BOTH files is what keeps that gap closed.
    """
    report = link_lint.lint_site(_REAL_SITE)

    assert report["checked"] is True
    assert report["hard"] is True, "the delivered site's broken link must be a HARD finding"

    broken = [f for f in report["findings"] if f["rule"] == "broken-link"]
    assert broken, "the 'View Details' link must be reported"
    assert all("piece-detail.html" in f["reference"] for f in broken)

    files = {f["file"] for f in broken}
    assert "app.js" in files, "the JavaScript copy must be found"
    assert "pieces.html" in files, "the inline-<script> copy must be found too"


@pytest.mark.skipif(not _REAL_SITE.is_dir(), reason="battery archive not present in this checkout")
def test_the_real_site_produces_no_false_positives() -> None:
    """Every finding on the real site names ``piece-detail.html`` and nothing else.

    Precision-first is the whole design: a false positive nags a coder into 'fixing'
    correct markup. The delivered site has 30-odd working links; not one may be flagged.
    """
    report = link_lint.lint_site(_REAL_SITE)
    stray = [f for f in report["findings"] if "piece-detail.html" not in f["reference"]]
    assert stray == [], f"false positives on a working site: {stray}"
    assert report["counts"]["resolved"] > 20, "the working links must be counted as resolved"


# ---------------------------------------------------------------------------
# The honesty locks (capability 7 — 'did not run' is not 'ran and found nothing')
# ---------------------------------------------------------------------------


def test_a_site_with_no_pages_is_ABSENT_not_clean(tmp_path: Path) -> None:
    """A scan that examined nothing reports ``checked: False``, never a clean pass.

    Four empty scaffolds under ~/projects returned ``checked: true, hard: false`` on this
    module's first sweep — an unmeasured pass wearing a measured pass's clothes, which is
    the exact #1342 defect this module was written to catch. The instrument must not
    commit the disease it diagnoses.
    """
    root = _site(tmp_path, {"README.md": "# nothing here"})
    report = link_lint.lint_site(root)

    assert report["checked"] is False
    assert report["files_scanned"] == 0
    assert report["counts"] == {}, "no counts may be published when nothing was examined"
    assert "NOTHING was checked" in " ".join(report["not_measured"])
    assert "did not run" in link_lint.format_operator_summary(report)


def test_undecidable_references_are_counted_and_never_pass_silently(tmp_path: Path) -> None:
    """A link built at runtime is UNCHECKED, and the report must say so in words."""
    root = _site(
        tmp_path,
        {
            "public/index.html": '<a href="${route}">go</a><img src="${piece.image}">',
            "public/app.js": "const x = 1;",
        },
    )
    report = link_lint.lint_site(root)

    assert report["counts"]["undecidable"] == 2
    assert report["counts"]["broken"] == 0
    summary = link_lint.format_operator_summary(report)
    assert "NOT confirmed working" in summary
    assert "could not be decided" in " ".join(report["not_measured"])


def test_a_missing_site_directory_is_reported_not_crashed(tmp_path: Path) -> None:
    report = link_lint.lint_site(tmp_path / "does-not-exist")
    assert report["checked"] is False
    assert report["hard"] is False
    assert "does not exist" in report["reason"]


# ---------------------------------------------------------------------------
# The rules
# ---------------------------------------------------------------------------


def test_query_string_is_stripped_before_deciding(tmp_path: Path) -> None:
    """``page.html?id=${x}`` is DECIDABLE — the file is ``page.html``.

    This ordering is the module's central design decision. Testing for interpolation
    before splitting the query would classify the operator's actual defect as
    'undecidable' and pass the delivery that prompted the work.
    """
    root = _site(tmp_path, {"public/index.html": '<a href="detail.html?id=${p.id}">x</a>'})
    report = link_lint.lint_site(root)

    assert report["counts"]["broken"] == 1
    assert report["counts"]["undecidable"] == 0
    assert report["findings"][0]["rule"] == "broken-link"


def test_a_link_that_resolves_is_not_flagged(tmp_path: Path) -> None:
    root = _site(
        tmp_path,
        {
            "public/index.html": '<a href="about.html">about</a><link href="s.css" rel="stylesheet">',
            "public/about.html": "<p>hi</p>",
            "public/s.css": "body{}",
        },
    )
    report = link_lint.lint_site(root)
    assert report["findings"] == []
    assert report["counts"]["resolved"] == 2


def test_case_mismatch_is_hard_because_it_only_works_here(tmp_path: Path) -> None:
    """Resolves on this case-insensitive box, 404s on any real host.

    This defect class is invisible to opening the site locally, which makes it exactly
    the kind a human reviewer cannot be asked to catch.
    """
    root = _site(tmp_path, {"public/index.html": '<a href="About.html">a</a>', "public/about.html": "x"})
    report = link_lint.lint_site(root)

    rules = [f["rule"] for f in report["findings"]]
    if "case-mismatch" in rules:
        assert report["hard"] is True
    else:  # a genuinely case-sensitive filesystem reports it as an ordinary break
        assert "broken-link" in rules


def test_external_and_in_page_links_are_out_of_scope(tmp_path: Path) -> None:
    root = _site(
        tmp_path,
        {
            "public/index.html": (
                '<a href="https://example.com">e</a><a href="mailto:a@b.c">m</a>'
                '<a href="#top">t</a><a href="//cdn.example/x.js">p</a>'
            )
        },
    )
    report = link_lint.lint_site(root)
    assert report["findings"] == []
    assert report["counts"]["external"] == 3
    assert report["counts"]["in_page"] == 1


def test_extensionless_miss_is_LOW_because_it_may_be_a_route(tmp_path: Path) -> None:
    """Precision-first: a bare ``/pieces`` may be a server route this module cannot see."""
    root = _site(tmp_path, {"public/index.html": '<a href="/pieces">list</a>'})
    report = link_lint.lint_site(root)

    assert [f["rule"] for f in report["findings"]] == ["unresolved-extensionless"]
    assert report["hard"] is False, "an uncertain miss must never force a coder FIX"


def test_missing_parent_directory_is_hard_even_when_the_filename_is_not(tmp_path: Path) -> None:
    """``assets/${n}.png`` with no ``assets/`` breaks for every possible filename."""
    root = _site(tmp_path, {"public/index.html": '<img src="assets/${n}.png">'})
    report = link_lint.lint_site(root)

    assert [f["rule"] for f in report["findings"]] == ["broken-parent-dir"]
    assert report["hard"] is True


def test_an_existing_parent_directory_is_not_flagged(tmp_path: Path) -> None:
    root = _site(
        tmp_path,
        {"public/index.html": '<img src="assets/${n}.png">', "public/assets/real.png": "x"},
    )
    report = link_lint.lint_site(root)
    assert report["findings"] == []
    assert report["counts"]["undecidable"] == 1


def test_directory_link_resolves_through_its_index(tmp_path: Path) -> None:
    root = _site(tmp_path, {"public/index.html": '<a href="docs/">d</a>', "public/docs/index.html": "x"})
    report = link_lint.lint_site(root)
    assert report["findings"] == []


def test_site_absolute_and_relative_resolve_against_different_bases(tmp_path: Path) -> None:
    """``/x.css`` resolves at the mount root; ``x.css`` beside the containing file."""
    root = _site(
        tmp_path,
        {
            "public/sub/page.html": '<link href="/top.css" rel="s"><link href="near.css" rel="s">',
            "public/top.css": "a{}",
            "public/sub/near.css": "b{}",
            "public/index.html": "<p>root</p>",
        },
    )
    report = link_lint.lint_site(root)
    assert report["findings"] == []
    assert report["counts"]["resolved"] == 2


def test_srcset_candidates_are_each_resolved(tmp_path: Path) -> None:
    root = _site(tmp_path, {"public/index.html": '<img srcset="a.png 1x, b.png 2x">', "public/a.png": "x"})
    report = link_lint.lint_site(root)
    assert [f["reference"] for f in report["findings"]] == ["b.png"]


def test_api_route_fetches_are_not_mistaken_for_links(tmp_path: Path) -> None:
    """A ``fetch('/api/pieces')`` is not a file and must never be flagged.

    This is why JavaScript extraction is scoped to URL-bearing ATTRIBUTES rather than to
    every path-shaped string literal: the broader rule produces a false-positive class
    that would make the gate untrustworthy on any site with a backend.
    """
    root = _site(
        tmp_path,
        {
            "public/index.html": "<p>x</p>",
            "public/app.js": "fetch('/api/pieces').then(r => r.json()); const p = './data/x.json';",
        },
    )
    report = link_lint.lint_site(root)
    assert report["findings"] == []


def test_served_root_detection_reports_its_reasoning(tmp_path: Path) -> None:
    """A wrong root turns every link broken, so the report must show its working."""
    root = _site(tmp_path, {"public/index.html": "<p>x</p>"})
    report = link_lint.lint_site(root)
    assert report["served_root"].endswith("public")
    assert "public" in report["served_root_reason"]


def test_an_unparseable_document_degrades_instead_of_raising(tmp_path: Path) -> None:
    root = _site(tmp_path, {"public/index.html": '<a href="ok.html"><<<>>> <div unclosed', "public/ok.html": "x"})
    report = link_lint.lint_site(root)  # must not raise
    assert report["checked"] is True


# ---------------------------------------------------------------------------
# Toggle proofs — security_by_design principle 12
# ---------------------------------------------------------------------------


def test_toggle_proof_the_probe_fails_when_script_scanning_is_disengaged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Disengage inline-``<script>`` scanning and the inline defect must go UNDETECTED.

    Without this, a green suite cannot be told apart from a probe that never reached the
    code. The site here carries its only broken link inside a ``<script>`` — exactly the
    shape the first implementation missed.
    """
    root = _site(
        tmp_path,
        {"public/index.html": '<script>el.innerHTML = `<a href="gone.html">x</a>`;</script>'},
    )

    engaged = link_lint.lint_site(root)
    assert engaged["hard"] is True, "engaged: the inline-script link must be caught"

    monkeypatch.setattr(link_lint._RefCollector, "handle_data", lambda self, data: None)
    disengaged = link_lint.lint_site(root)
    assert disengaged["hard"] is False, (
        "disengaging script scanning must make this defect invisible — if it is still "
        "found, the engaged result was not produced by the control under test"
    )


def test_toggle_proof_the_probe_fails_when_query_splitting_is_disengaged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stop splitting the query first and the operator's real defect becomes invisible.

    This proves the central design decision is load-bearing rather than incidental: with
    naive ordering, ``detail.html?id=${p.id}`` grades 'undecidable' and the delivery that
    started all of this passes clean.
    """
    root = _site(tmp_path, {"public/index.html": '<a href="detail.html?id=${p.id}">x</a>'})

    assert link_lint.lint_site(root)["hard"] is True

    monkeypatch.setattr(
        link_lint,
        "_decidable_path",
        lambda raw: "" if link_lint._INTERPOLATION_RE.search(raw) else raw.split("?", 1)[0],
    )
    disengaged = link_lint.lint_site(root)
    assert disengaged["hard"] is False
    assert disengaged["counts"]["undecidable"] == 1


# ---------------------------------------------------------------------------
# Reachability — the gate must be WIRED, not merely present
# ---------------------------------------------------------------------------
#
# This project's most-repeated failure class is "built but wired into nothing": a control
# that exists, has passing unit tests, and is called by no one. These drive the REAL entry
# point (`real_run_exec_smoke`) rather than `lint_site`, so a future refactor that unhooks
# the lint fails here instead of shipping a silent no-op.


def _smoke_config(tmp_path: Path):
    from shared.fleet.dispatch import FleetDispatchConfig

    return FleetDispatchConfig(
        scripts_dir=tmp_path / "scripts",
        queue_path=tmp_path / "state" / "q.json",
        runs_dir=tmp_path / "state" / "runs",
        projects_dir=tmp_path / "projects",
    )


def _web_repo(tmp_path: Path, pages: dict[str, str]) -> Path:
    repo = tmp_path / "site"
    for rel, content in pages.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return repo


def test_reachability_the_web_floor_carries_a_link_report(tmp_path: Path) -> None:
    """A web build's executability floor must return a link report on the happy path."""
    from shared.fleet import swap_ops as so

    repo = _web_repo(tmp_path, {"index.html": '<a href="gone.html">x</a>'})
    res = so.real_run_exec_smoke(
        _smoke_config(tmp_path),
        "R1",
        str(repo),
        "tests/acceptance.job.test.mjs",
        surface="web",
        web_console_capture=lambda r, root: {"ok": True, "errors": [], "evidence": "loaded clean"},
        run=lambda _cmd, _t, _cwd=None, env=None: (True, "", ""),
    )

    assert "link_lint" in res, "the web floor must carry the link report — the gate is unwired"
    assert res["link_lint"]["counts"]["broken"] == 1
    assert "broken link" in res["evidence"], "a broken link must reach the evidence line"


def test_reachability_a_broken_link_does_NOT_change_the_verdict(tmp_path: Path) -> None:
    """Advisory by design: the operator asked for the delivery to be REPORTED, not failed.

    A brand-new way for a build to RED is a capability change and therefore his ceremony.
    This lock is what stops a later edit from quietly promoting the lint into a gate.
    """
    from shared.fleet import swap_ops as so

    broken = _web_repo(tmp_path / "a", {"index.html": '<a href="gone.html">x</a>'})
    clean = _web_repo(tmp_path / "b", {"index.html": '<a href="ok.html">x</a>', "ok.html": "y"})
    capture = lambda r, root: {"ok": True, "errors": [], "evidence": "loaded clean"}  # noqa: E731
    runner = lambda _cmd, _t, _cwd=None, env=None: (True, "", "")  # noqa: E731

    res_broken = so.real_run_exec_smoke(
        _smoke_config(tmp_path / "a"), "R1", str(broken), "tests/acceptance.job.test.mjs",
        surface="web", web_console_capture=capture, run=runner)
    res_clean = so.real_run_exec_smoke(
        _smoke_config(tmp_path / "b"), "R1", str(clean), "tests/acceptance.job.test.mjs",
        surface="web", web_console_capture=capture, run=runner)

    assert res_broken["ok"] is True and res_clean["ok"] is True
    assert res_broken["ok"] == res_clean["ok"], "the link lint must not move the verdict"
    assert res_broken["fingerprint"] == res_clean["fingerprint"]


def test_reachability_the_sidecar_is_written_for_the_review_loop(tmp_path: Path) -> None:
    """``link-lint.json`` must land in the run directory, where the review loop reads it."""
    from shared.fleet import swap_ops as so

    config = _smoke_config(tmp_path)
    repo = _web_repo(tmp_path, {"index.html": '<a href="gone.html">x</a>'})
    so.real_run_exec_smoke(
        config, "R7", str(repo), "tests/acceptance.job.test.mjs", surface="web",
        web_console_capture=lambda r, root: {"ok": True, "errors": [], "evidence": "clean"},
        run=lambda _cmd, _t, _cwd=None, env=None: (True, "", ""))

    sidecar = config.runs_dir / "R7" / "link-lint.json"
    assert sidecar.is_file(), "the review loop has nothing to read without this sidecar"
    assert json.loads(sidecar.read_text(encoding="utf-8"))["counts"]["broken"] == 1


def test_reachability_a_lint_raise_leaves_the_floor_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A presentation-layer failure must never take an executability floor down with it."""
    from shared.fleet import swap_ops as so

    def boom(_site_dir, _served_root=None):
        raise RuntimeError("lint exploded")

    monkeypatch.setattr(link_lint, "lint_site", boom)
    repo = _web_repo(tmp_path, {"index.html": "<p>fine</p>"})
    res = so.real_run_exec_smoke(
        _smoke_config(tmp_path), "R1", str(repo), "tests/acceptance.job.test.mjs",
        surface="web",
        web_console_capture=lambda r, root: {"ok": True, "errors": [], "evidence": "clean"},
        run=lambda _cmd, _t, _cwd=None, env=None: (True, "", ""))

    assert res["ok"] is True, "the floor must survive a lint raise"
    assert res["link_lint"]["checked"] is False
    assert "NOT checked" in res["evidence"]


# ---------------------------------------------------------------------------
# CLI contract
# ---------------------------------------------------------------------------


def test_cli_emits_one_json_object_and_exits_zero(tmp_path: Path) -> None:
    """Exit 0 even with findings: this is a SIGNAL, matching layout_lint's contract."""
    import subprocess
    import sys

    root = _site(tmp_path, {"public/index.html": '<a href="gone.html">x</a>'})
    proc = subprocess.run(
        [sys.executable, "-m", "shared.fleet.link_lint", "--site-dir", str(root)],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[2]),
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["hard"] is True
    assert payload["schema"] == "link-lint/v1"


def test_cli_rejects_a_missing_directory_with_exit_two(tmp_path: Path) -> None:
    import subprocess
    import sys

    proc = subprocess.run(
        [sys.executable, "-m", "shared.fleet.link_lint", "--site-dir", str(tmp_path / "nope")],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[2]),
    )
    assert proc.returncode == 2


# ---------------------------------------------------------------------------
# #1375 — fetch targets. The operator opened the delivered pottery site on
# 2026-08-10 and the gallery said "Failed to load pieces." in red. Both central
# pages ran `fetch('./data/pieces.json')`; the file existed at the project root
# while the server mounted `public/`, so every visitor got a 404.
#
# Nothing could have caught it: an href/src scan does not see a fetch, the
# console smoke only ever loaded the entry page, and image_placement read that
# very JSON off the FILESYSTEM without asking whether a browser could reach it.
# A file that exists is not a file that is served.
# ---------------------------------------------------------------------------

#: The delivered site as it stood when the operator found the defect — the IMMUTABLE
#: operator-review snapshot, not the live project tree.
#:
#: `~/projects/` is rewritten on every dispatch, so a test pinned there asserts figures
#: that expire at the next run; `tests/security/test_evidence_is_immutable.py` refuses it
#: and refused this file when it first pointed there. The night-*/repos-archived/ copies
#: it suggests instead do NOT carry this defect — the archive holds the tree from BEFORE
#: the run that built these pages, so the delivery exists in no archive.
#:
#: The review workspace is the right answer: `review-website.ps1` COPIES a build to a
#: dated directory before serving it, precisely so the reviewed bytes cannot change under
#: the reviewer. This is that copy — the exact tree the operator was looking at when he
#: reported the empty gallery on 2026-08-10.
_BROKEN_FETCH_SITE = Path(
    "C:/Users/mrbla/agentic-setup/state/operator-review/"
    "20260810-094231-battery-b9-pottery-site"
)


@pytest.mark.skipif(not _BROKEN_FETCH_SITE.is_dir(), reason="delivered project not on this box")
def test_the_real_unreachable_data_file_is_found_in_both_pages() -> None:
    """Drives the ACTUAL site the operator reviewed, not a fixture.

    Both `pieces.html` and `piece-detail.html` fetch the same unreachable path, so a
    checker that found one and not the other would still leave a dead page shipping.
    """
    report = link_lint.lint_site(_BROKEN_FETCH_SITE)
    fetches = [f for f in report["findings"] if "pieces.json" in f["reference"]]
    assert len(fetches) == 2, (
        "both delivered pages fetch './data/pieces.json' and both are unreachable from the "
        f"served root; found {len(fetches)} finding(s): {[f['file'] for f in fetches]}"
    )
    assert all(f["severity"] == link_lint.SEVERITY_HIGH for f in fetches)
    assert report["hard"] is True, "an unreachable data file must force a FIX, not advise"


@pytest.mark.skipif(not _BROKEN_FETCH_SITE.is_dir(), reason="delivered project not on this box")
def test_the_finding_does_not_tell_the_operator_someone_clicked_it() -> None:
    """A fetch is not clicked. The operator reads these words; they must be true of it."""
    report = link_lint.lint_site(_BROKEN_FETCH_SITE)
    fetches = [f for f in report["findings"] if "pieces.json" in f["reference"]]
    assert fetches, "precondition: the real finding must be present"
    for f in fetches:
        assert "clicks" not in f["message"], (
            "a fetch finding must not be described as a click — the page asks for this "
            f"itself and fails silently: {f['message']}"
        )
        assert "asks the server" in f["message"]


def test_a_fetch_naming_a_FILE_outside_the_served_root_is_hard(tmp_path: Path) -> None:
    """The #1375 shape, reduced: data beside the mount rather than inside it."""
    root = _site(
        tmp_path,
        {
            "public/index.html": "<script>fetch('./data/pieces.json').then(r=>r.json())</script>",
            "data/pieces.json": '[{"id":1}]',  # exists, but OUTSIDE public/
        },
    )
    report = link_lint.lint_site(root)
    assert report["hard"] is True
    assert any("pieces.json" in f["reference"] for f in report["findings"])


def test_the_same_fetch_is_CLEAN_once_the_file_is_reachable(tmp_path: Path) -> None:
    """The positive control. Without this, a checker that flags everything looks correct."""
    root = _site(
        tmp_path,
        {
            "public/index.html": "<script>fetch('./data/pieces.json').then(r=>r.json())</script>",
            "public/data/pieces.json": '[{"id":1}]',  # inside the served root
        },
    )
    report = link_lint.lint_site(root)
    assert report["hard"] is False, f"unexpected findings: {report['findings']}"


def test_api_routes_are_NOT_flagged(tmp_path: Path) -> None:
    """The false-positive class `extract_references_js` was written to avoid, preserved.

    Its docstring said a broader sweep "would flag fetch() calls against API routes, which
    are not files and are not defects." That reasoning is right and this locks it: only a
    target carrying a recognised web extension is decidable as a file.
    """
    root = _site(
        tmp_path,
        {
            "public/index.html": (
                "<script>"
                "fetch('/api/pieces');"
                "fetch('/api/enquiries', {method:'POST'});"
                "fetch(`/api/piece/${id}`);"
                "fetch(someUrlVariable);"
                "</script>"
            ),
        },
    )
    report = link_lint.lint_site(root)
    assert report["hard"] is False, (
        f"an API route is not a file and must not be flagged: {report['findings']}"
    )


def test_a_fetch_inside_an_inline_script_tag_is_seen(tmp_path: Path) -> None:
    """The defect lived in an inline <script>, where no HTML attribute parser looks.

    This is the reason the extractor runs over .html as well as .js — without it the
    checker would pass the exact delivery it was written to catch, which is the trap this
    module's own header warns about.
    """
    root = _site(tmp_path, {"public/index.html": "<script>fetch('./missing.json')</script>"})
    report = link_lint.lint_site(root)
    assert any("missing.json" in f["reference"] for f in report["findings"])


def test_toggle_proof_the_fetch_extractor_is_what_catches_it(tmp_path: Path) -> None:
    """security_by_design principle 12: prove the probe FAILS when the control is off.

    With `extract_fetch_targets` neutralised, the same site must come back clean — so a
    green result on the real site can be distinguished from a checker that cannot see.
    """
    root = _site(tmp_path, {"public/index.html": "<script>fetch('./data/pieces.json')</script>"})
    assert link_lint.lint_site(root)["hard"] is True, "precondition: the control catches it"

    original = link_lint.extract_fetch_targets
    try:
        link_lint.extract_fetch_targets = lambda text, source: []
        disabled = link_lint.lint_site(root)
    finally:
        link_lint.extract_fetch_targets = original

    assert disabled["hard"] is False, (
        "with the fetch extractor disabled the defect must go UNSEEN — if it is still "
        "found, something else is doing the work and this control is not what protects us"
    )
    assert link_lint.lint_site(root)["hard"] is True, "the control must be restored"


# ---------------------------------------------------------------------------
# #1367 — the entry point. The operator opened a six-page site and got a page
# saying "App" with a blue circle: public/index.html was the scaffold's 1044-byte
# placeholder, untouched by all seven delivered tasks, and the server mounts / to
# it. Four gates passed that tree, because each asks whether a page it was HANDED
# is well-formed and none asks whether the page a visitor REACHES is the product.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _BROKEN_FETCH_SITE.is_dir(), reason="review snapshot not on this box")
def test_the_real_front_door_that_reached_nothing_is_found() -> None:
    """The immutable snapshot of the site he actually opened."""
    report = link_lint.lint_site(_BROKEN_FETCH_SITE)
    entry = [f for f in report["findings"] if f["rule"] == "entry-reaches-nothing"]
    assert len(entry) == 1, f"expected the front-door finding, got {[f['rule'] for f in report['findings']]}"
    assert entry[0]["severity"] == link_lint.SEVERITY_HIGH
    # It must name what could not be reached, or the coder is left guessing.
    for page in ("home.html", "pieces.html", "contact.html"):
        assert page in entry[0]["message"], f"the finding must name {page}"


def test_an_entry_that_links_to_the_site_is_CLEAN(tmp_path: Path) -> None:
    """Positive control. Without it, a rule that fires on everything looks correct."""
    root = _site(
        tmp_path,
        {
            "public/index.html": '<a href="home.html">Home</a> <a href="pieces.html">Shop</a>',
            "public/home.html": "<h1>home</h1>",
            "public/pieces.html": "<h1>pieces</h1>",
            "public/contact.html": "<h1>contact</h1>",
        },
    )
    report = link_lint.lint_site(root)
    assert not [f for f in report["findings"] if f["rule"] == "entry-reaches-nothing"]
    assert report["hard"] is False


def test_a_single_page_site_is_NOT_flagged(tmp_path: Path) -> None:
    """The one real false-positive class: an entry with nothing to reach.

    A genuine single-page delivery has no siblings to link to. The rule requires two or
    more before it can fire, so a one-page site is exempt by construction rather than by
    a heuristic that could drift.
    """
    root = _site(tmp_path, {"public/index.html": "<h1>the whole app</h1>"})
    assert not [f for f in link_lint.lint_site(root)["findings"] if f["rule"] == "entry-reaches-nothing"]

    root2 = _site(tmp_path / "two", {
        "public/index.html": "<h1>app</h1>",
        "public/about.html": "<h1>about</h1>",
    })
    assert not [f for f in link_lint.lint_site(root2)["findings"] if f["rule"] == "entry-reaches-nothing"], (
        "one sibling is under the two-page threshold and must not fire"
    )


def test_the_scaffold_placeholder_shape_is_flagged(tmp_path: Path) -> None:
    """#1367 reduced: the seed's entry survives untouched beside everything that was built."""
    root = _site(
        tmp_path,
        {
            "public/index.html": "<h1>App</h1><svg><circle/></svg><p id='status'>Loading…</p>",
            "public/home.html": "<h1>Welcome to the studio</h1>",
            "public/pieces.html": "<h1>Our pieces</h1>",
            "public/contact.html": "<h1>Contact</h1>",
        },
    )
    report = link_lint.lint_site(root)
    entry = [f for f in report["findings"] if f["rule"] == "entry-reaches-nothing"]
    assert len(entry) == 1
    assert report["hard"] is True, "a site with no front door must force a FIX, not advise"


def test_toggle_proof_the_entry_rule_is_what_catches_it(tmp_path: Path) -> None:
    """security_by_design principle 12 — prove the probe FAILS when the control is off."""
    root = _site(
        tmp_path,
        {
            "public/index.html": "<h1>App</h1>",
            "public/home.html": "<h1>home</h1>",
            "public/pieces.html": "<h1>pieces</h1>",
        },
    )
    assert link_lint.lint_site(root)["hard"] is True, "precondition: the control catches it"

    original = link_lint._check_entry_reaches_the_site
    try:
        link_lint._check_entry_reaches_the_site = lambda root: None
        disabled = link_lint.lint_site(root)
    finally:
        link_lint._check_entry_reaches_the_site = original

    assert disabled["hard"] is False, (
        "with the entry rule disabled this site must come back CLEAN — if it is still hard, "
        "something else is doing the work and this rule is not what protects us"
    )
    assert link_lint.lint_site(root)["hard"] is True, "the control must be restored"


# ---------------------------------------------------------------------------
# #1389 — the denominator. DoD row 13 names this module as the class's THIRD
# instance, found by looking rather than by being bitten.
#
# The published total used to be `resolved + broken + undecidable + external +
# in_page` — a denominator derived from the numerators it is meant to check. A
# reference landing in no bucket left the numerator and the denominator
# TOGETHER, so the arithmetic stayed self-consistent while under-reporting.
# ---------------------------------------------------------------------------


def test_the_denominator_is_the_POPULATION_not_the_sum_of_the_buckets(tmp_path: Path) -> None:
    """`references` must count what was EXAMINED, independently of classification.

    This is #1231's property stated directly for this instrument. It is the one that must
    never regress: a grader that derives its total from its own counters cannot detect its
    own losses, because a lost item leaves both sides of the fraction at once.
    """
    site = _site(tmp_path, {
        "index.html": (
            '<a href="a.html">a</a>'
            '<a href="missing.html">gone</a>'
            '<a href="#top">anchor</a>'
            '<a href="https://example.com">out</a>'
        ),
        "a.html": "<p>a</p>",
    })
    report = link_lint.lint_site(site)

    assert report["checked"] is True
    counts = report["counts"]
    assert report["references"] == sum(counts.values()), (
        f"population {report['references']} disagrees with the buckets {counts} — every "
        f"examined reference must appear in exactly one"
    )
    assert report["references"] >= 4, "precondition: the fixture really has references"


def test_a_status_no_bucket_recognises_CANNOT_be_counted_silently(tmp_path: Path,
                                                                  monkeypatch) -> None:
    """The defect itself: could a sixth status be added and lose references quietly?

    Before #1389 the answer was yes. `_Tally` was a plain dataclass and the classification
    loop increments by computed name, so `setattr(tally, "skipped", 1)` created a NEW
    attribute nothing read — no exception, no red, and the reference gone from both the
    bucket and the total. Nothing PRODUCED a sixth status; nothing PREVENTED one either, and
    adding it was a one-line change two hundred lines from the tally.

    `slots=True` makes it an AttributeError at the increment. This test is the proof, and it
    is written against the mechanism rather than the current status list, so it keeps holding
    when the list changes.
    """
    tally = link_lint._Tally()
    with pytest.raises(AttributeError):
        setattr(tally, "some_new_status", 1)

    assert tally.unaccounted() == 0, "a fresh tally has lost nothing"


def test_the_reconciliation_notices_a_loss_and_says_so_loudly(tmp_path: Path) -> None:
    """The belt to slots' brace: if a reference is ever lost, the REPORT says so.

    Constructed directly, because the whole point is that no live path can produce it. A
    control that can only be proved by the absence of a failure is not proved at all.
    """
    tally = link_lint._Tally()
    tally.examined = 10
    tally.resolved = 7
    assert tally.unaccounted() == 3, "the residual is examined minus the buckets"

    tally.resolved = 10
    assert tally.unaccounted() == 0, "a balanced tally reports no residual"


def test_the_population_counter_is_not_vacuous(tmp_path: Path) -> None:
    """The toggle. If `examined` were incremented in the same place as the buckets, it would
    agree with them by construction and the invariant above would prove nothing.

    Drives a real site and checks the counter moved with real references — so a future edit
    that quietly stops incrementing it fails here rather than passing a tautology.
    """
    empty = _site(tmp_path / "none", {"index.html": "<p>no links at all</p>"})
    linked = _site(tmp_path / "some", {
        "index.html": '<a href="a.html">a</a><a href="b.html">b</a>',
        "a.html": "<p>a</p>",
        "b.html": "<p>b</p>",
    })

    assert link_lint.lint_site(empty)["references"] == 0
    assert link_lint.lint_site(linked)["references"] == 2, (
        "the population counter did not track real references"
    )
