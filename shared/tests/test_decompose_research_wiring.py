"""#746 research substrate — plan-time grounding WIRING into decompose/PLAN.

The load-bearing property here is the DORMANT contract: with
``research_grounding=False`` (the default) the decompose prompt fed to the 14B is
BYTE-IDENTICAL to today's and ``shared.research`` is never even imported. When ON,
the prompt is prefixed with a bounded LOCAL-docs grounding block; a goal that clears
nothing (or an absent corpus) still yields a byte-identical prompt (pull-not-push +
degrade-gracefully). All local, zero egress — the fixture builds a mini docset index
in ``tmp_path`` and injects it (never the real staged corpus).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.fleet import acceptance as ac
from shared.fleet import decompose as dc
from shared.research import docset_index as di
from shared.research import lookup as lk
from shared.research.plan_grounding import GROUNDING_HEADER


# ---------------------------------------------------------------------------
# Fixtures — a fake repo + a tiny hash-pinned DevDocs index carrying json.dumps
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_usage_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test in this file exercises ``ground_goal``'s ALWAYS-ON usage logging
    as a side effect. Without this, every test run appends real-looking records to
    the operator's actual ``state/research-usage.jsonl`` (found 2026-07-24: two
    pytest runs' synthetic hit/miss/unavailable records sat in the log at the exact
    same timestamps as this file's own test run, and were briefly mistaken for a
    live-dispatch anomaly). Redirect to a throwaway per-test path instead."""
    monkeypatch.setenv("BLARAI_RESEARCH_USAGE_LOG", str(tmp_path / "test-research-usage.jsonl"))


def _projects(tmp_path: Path) -> Path:
    proj = tmp_path / "projects"
    (proj / "myapp" / ".git").mkdir(parents=True)
    return proj


_JSON_PAGE_HTML = (
    "<h1>json — JSON encoder and decoder</h1>"
    "<p>Serialization of python objects to JSON.</p>"
    '<dl><dt id="json.dumps"><code>json.dumps(obj, indent=None)</code></dt>'
    "<dd>Serialize obj to a JSON formatted str using this conversion table.</dd></dl>"
)


def _build_index(tmp_path: Path):
    """Build + load a minimal DevDocs-only docset index (json.dumps present)."""
    import hashlib

    corpus = tmp_path / "docsets"
    dd = corpus / "devdocs" / "python~3.11"
    dd.mkdir(parents=True)
    entries = [
        {"name": "json.dumps()", "path": "library/json#json.dumps", "type": "Data"},
        {"name": "json", "path": "library/json", "type": "Data"},
    ]
    (dd / "index.json").write_text(json.dumps({"entries": entries}), encoding="utf-8")
    (dd / "db.json").write_text(
        json.dumps({"library/json": _JSON_PAGE_HTML}), encoding="utf-8"
    )

    def _sha(rel: str) -> str:
        return hashlib.sha256((corpus / rel).read_bytes()).hexdigest()

    files = [
        ("dd-index", "devdocs/python~3.11/index.json"),
        ("dd-db", "devdocs/python~3.11/db.json"),
    ]
    artifacts = [
        {"name": n, "file": r, "sha256": _sha(r), "bytes": (corpus / r).stat().st_size}
        for n, r in files
    ]
    (corpus / di.CORPUS_MANIFEST_NAME).write_text(
        json.dumps({"schema": "blarai-docset-manifest/v1", "artifacts": artifacts}),
        encoding="utf-8",
    )
    index_dir = tmp_path / "index"
    di.build_index(corpus_dir=corpus, index_dir=index_dir)
    return di.load_index(index_dir=index_dir, corpus_dir=corpus)


class _Recorder:
    """A fake generate_fn that records every prompt and returns a fixed plan."""

    def __init__(self, payload: str) -> None:
        self.payload = payload
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.payload


#: A single-task plan whose goal names no independent units, so the #691 envelope
#: split is never offered — generate_fn is therefore called EXACTLY once (the main
#: decompose call), and prompts[0] is unambiguously the decompose prompt.
_ONE_TASK = json.dumps([{"task": "add-json-serializer", "prompt": "Add a json serializer."}])
#: A goal that names a real fixture symbol (json.dumps) AND enumerates no units.
_GOAL = "serialize config dicts using json.dumps"


# ---------------------------------------------------------------------------
# THE REGRESSION LOCK — OFF is byte-identical to today
# ---------------------------------------------------------------------------


def test_off_decompose_prompt_is_byte_identical_to_today(tmp_path: Path) -> None:
    """research_grounding defaulted-OFF and explicitly-OFF both feed the 14B EXACTLY
    the ungrounded template — the byte-identical dormant contract."""
    proj = _projects(tmp_path)
    expected = dc._DECOMPOSE_TEMPLATE.format(max_tasks=dc.DEFAULT_MAX_TASKS, idea=_GOAL)

    default_rec = _Recorder(_ONE_TASK)
    dc.decompose_request(_GOAL, "myapp", generate_fn=default_rec, projects_dir=proj)

    off_rec = _Recorder(_ONE_TASK)
    dc.decompose_request(
        _GOAL, "myapp", generate_fn=off_rec, projects_dir=proj,
        research_grounding=False,
    )

    assert default_rec.prompts == [expected]
    assert off_rec.prompts == [expected]
    # byte-for-byte identical to the pre-#746 call
    assert default_rec.prompts[0] == off_rec.prompts[0] == expected


def test_off_result_matches_no_param(tmp_path: Path) -> None:
    """The whole DecomposeResult is identical with the flag defaulted vs explicitly
    False — the wiring adds no behavioral drift when dormant."""
    proj = _projects(tmp_path)
    a = dc.decompose_request(_GOAL, "myapp", generate_fn=_Recorder(_ONE_TASK), projects_dir=proj)
    b = dc.decompose_request(
        _GOAL, "myapp", generate_fn=_Recorder(_ONE_TASK), projects_dir=proj,
        research_grounding=False, research_index=None,
    )
    assert a == b


def test_off_never_enters_the_grounding_path(tmp_path: Path, monkeypatch) -> None:
    """With the flag OFF, _grounded_prompt (and thus shared.research) is NEVER
    invoked — proven by making it explode if it is."""
    proj = _projects(tmp_path)

    def _boom(*_a, **_k):  # pragma: no cover - must never run when dormant
        raise AssertionError("_grounded_prompt called while research_grounding=False")

    monkeypatch.setattr(dc, "_grounded_prompt", _boom)
    res = dc.decompose_request(_GOAL, "myapp", generate_fn=_Recorder(_ONE_TASK), projects_dir=proj)
    assert res.ok and res.tasks  # decompose succeeded without touching grounding


# ---------------------------------------------------------------------------
# ON — grounding is applied to the prompt (and ONLY the prompt)
# ---------------------------------------------------------------------------


def test_on_prepends_grounding_block_but_output_shape_unchanged(tmp_path: Path) -> None:
    proj = _projects(tmp_path)
    index = _build_index(tmp_path)
    try:
        base = dc._DECOMPOSE_TEMPLATE.format(max_tasks=dc.DEFAULT_MAX_TASKS, idea=_GOAL)
        on_rec = _Recorder(_ONE_TASK)
        res = dc.decompose_request(
            _GOAL, "myapp", generate_fn=on_rec, projects_dir=proj,
            research_grounding=True, research_index=index,
        )
        prompt = on_rec.prompts[0]
        # The grounding block is PREPENDED; the base template is preserved as a suffix.
        assert prompt != base
        assert prompt.startswith(GROUNDING_HEADER)
        assert prompt.endswith(base)
        assert "json.dumps" in prompt
        assert "[python~3.11]" in prompt
        # Output shape is unchanged (the fake gen returns the same plan): grounding
        # touches the PROMPT only, never the parsed/ruled result.
        off = dc.decompose_request(
            _GOAL, "myapp", generate_fn=_Recorder(_ONE_TASK), projects_dir=proj,
        )
        assert res.tasks == off.tasks and res.ok == off.ok
    finally:
        index.close()


def test_on_but_nothing_clears_floor_is_byte_identical(tmp_path: Path) -> None:
    """Pull-not-push at the wiring: a goal the corpus cannot ground yields an EMPTY
    block, so the prompt is byte-identical to the OFF prompt."""
    proj = _projects(tmp_path)
    index = _build_index(tmp_path)
    try:
        junk = "qqxjz wvvbnq zzptk blorp nonsense"
        base = dc._DECOMPOSE_TEMPLATE.format(max_tasks=dc.DEFAULT_MAX_TASKS, idea=junk)
        rec = _Recorder(_ONE_TASK)
        dc.decompose_request(
            junk, "myapp", generate_fn=rec, projects_dir=proj,
            research_grounding=True, research_index=index,
        )
        assert rec.prompts == [base]
    finally:
        index.close()


def test_on_corpus_absent_degrades_gracefully_to_byte_identical(
    tmp_path: Path, monkeypatch
) -> None:
    """research_grounding=True with NO injected index and an absent default corpus:
    ground_goal returns '' (degrade-gracefully), so decompose runs ungrounded and
    byte-identical — a missing corpus never breaks a plan."""
    proj = _projects(tmp_path)
    monkeypatch.setattr(di, "DEFAULT_CORPUS_DIR", tmp_path / "absent")
    monkeypatch.setattr(di, "DEFAULT_INDEX_DIR", tmp_path / "absent" / "index")
    lk.reset_default_index()
    try:
        base = dc._DECOMPOSE_TEMPLATE.format(max_tasks=dc.DEFAULT_MAX_TASKS, idea=_GOAL)
        rec = _Recorder(_ONE_TASK)
        res = dc.decompose_request(
            _GOAL, "myapp", generate_fn=rec, projects_dir=proj,
            research_grounding=True, research_index=None,
        )
        assert rec.prompts == [base]  # ungrounded, byte-identical
        assert res.ok
    finally:
        lk.reset_default_index()


def test_grounding_failure_never_breaks_decompose(tmp_path: Path, monkeypatch) -> None:
    """Any retrieval exception (not just the modelled index errors) degrades to the
    ungrounded prompt — grounding is enrichment, never a new failure mode."""
    proj = _projects(tmp_path)

    def _explode(*_a, **_k):
        raise RuntimeError("retrieval blew up")

    # Patch the imported name inside shared.research so the lazy import in
    # _grounded_prompt resolves to the exploding stub.
    import shared.research as sr

    monkeypatch.setattr(sr, "ground_goal", _explode)
    base = dc._DECOMPOSE_TEMPLATE.format(max_tasks=dc.DEFAULT_MAX_TASKS, idea=_GOAL)
    rec = _Recorder(_ONE_TASK)
    res = dc.decompose_request(
        _GOAL, "myapp", generate_fn=rec, projects_dir=proj,
        research_grounding=True, research_index=None,
    )
    assert rec.prompts == [base] and res.ok


# ---------------------------------------------------------------------------
# acceptance.generate_plan threads the flag through to decompose
# ---------------------------------------------------------------------------


def test_generate_plan_off_is_byte_identical(tmp_path: Path) -> None:
    proj = _projects(tmp_path)
    base = dc._DECOMPOSE_TEMPLATE.format(max_tasks=dc.DEFAULT_MAX_TASKS, idea=_GOAL)
    rec = _Recorder(_ONE_TASK)
    ac.generate_plan(_GOAL, "myapp", generate_fn=rec, projects_dir=proj)
    # generate_plan ALSO calls generate_fn for criteria; the FIRST call is decompose.
    assert rec.prompts[0] == base


def test_generate_plan_on_grounds_the_decompose_limb(tmp_path: Path) -> None:
    proj = _projects(tmp_path)
    index = _build_index(tmp_path)
    try:
        rec = _Recorder(_ONE_TASK)
        ac.generate_plan(
            _GOAL, "myapp", generate_fn=rec, projects_dir=proj,
            research_grounding=True, research_index=index,
        )
        # The decompose prompt (first call) carries the grounding block; criteria
        # generation (later calls) is untouched by grounding.
        assert rec.prompts[0].startswith(GROUNDING_HEADER)
        assert "json.dumps" in rec.prompts[0]
    finally:
        index.close()

