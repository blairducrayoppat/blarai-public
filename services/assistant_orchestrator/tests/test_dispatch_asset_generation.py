"""Tests — UC-010 dispatch image assets (SEAM A) in the AO EXECUTE handler.

The AO generates the planned image assets WHILE the 14B is resident and BEFORE the swap
(`_maybe_generate_dispatch_assets`), writing plain PNGs into the target repo and committing
them into the baseline the coder candidates inherit. Everything is DORMANT behind
`BLARAI_ENABLE_ASSET_GENERATION` and WHOLLY FAIL-SOFT — it never raises into the handler, so
the swap is never derailed. These tests bind the unbound methods to fakes + monkeypatch the
`image_gen` module so they assert the wiring/gating/fail-soft WITHOUT a GPU:

  * the flat-vector wrap constant is byte-identical to the gateway SSOT (drift-locked);
  * the flag gates generation (off -> a no-op, today's behaviour);
  * a spec generates -> writes into <repo>/<target_rel_path> -> commits the named file;
  * every failure (no config, unsafe path, no image, PA deny, gen raises) is swallowed;
  * generation forces hires OFF (14B kept) and SKIPS the born-encrypted store.
"""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

from services.assistant_orchestrator.src import entrypoint
from services.assistant_orchestrator.src.entrypoint import AssistantOrchestratorService
from shared.inference import image_gen
from shared.ipc.protocol import MessageFramer


# ---- SSOT drift lock ------------------------------------------------------


def test_illustration_template_is_byte_identical_to_gateway_ssot():
    # The dispatch generates BELOW the gateway, so it mirrors the gateway's flat-vector wrap.
    # If the gateway constant is ever tuned, this fails LOUDLY so the two never drift.
    from services.ui_gateway.src import imagine_coordinator
    assert entrypoint._ASSET_ILLUSTRATION_TEMPLATE == imagine_coordinator._ILLUSTRATION_TEMPLATE


# ---- the dormancy flag ----------------------------------------------------


def test_asset_generation_flag_on_by_default_opt_out(monkeypatch):
    # Production default (LA-approved 2026-06-30, #714): ON. Unset/empty/unknown -> enabled;
    # only an EXPLICIT falsy value opts out.
    monkeypatch.delenv("BLARAI_ENABLE_ASSET_GENERATION", raising=False)
    assert entrypoint._asset_generation_enabled() is True
    for v in ("", "1", "true", "TRUE", "yes", "on", " On ", "anything"):
        monkeypatch.setenv("BLARAI_ENABLE_ASSET_GENERATION", v)
        assert entrypoint._asset_generation_enabled() is True, v
    for v in ("0", "false", "no", "off", " OFF "):
        monkeypatch.setenv("BLARAI_ENABLE_ASSET_GENERATION", v)
        assert entrypoint._asset_generation_enabled() is False, v


# ---- _maybe_generate_dispatch_assets (the orchestration) ------------------


class _FakeAO:
    """Stand-in carrying just what `_maybe_generate_dispatch_assets` reads — the per-asset
    generate + the git commit are STUBBED (no GPU, no git)."""

    def __init__(self, *, gen, resolved=SimpleNamespace()):
        self._resolved_config = resolved
        self._gen = gen                      # callable(spec) -> bytes | None, or raises
        self.generated: list = []
        self.committed: list = []
        self.pipeline_unloaded = 0
        # the 14B handle SEAM A evicts BEFORE generation (it is swapped out next anyway, #714)
        self._shared_pipeline = SimpleNamespace(unload=self._rec_unload)

    def _rec_unload(self):
        self.pipeline_unloaded += 1

    def _generate_one_dispatch_asset(self, spec, session_id):
        self.generated.append((spec["target_rel_path"], session_id))
        return self._gen(spec)

    def _commit_dispatch_assets(self, repo_path, rel_paths):
        self.committed.append((repo_path, list(rel_paths)))

    _maybe_generate_dispatch_assets = AssistantOrchestratorService._maybe_generate_dispatch_assets


def _repo_under(projects, name="myapp"):
    repo = projects / name
    (repo / ".git").mkdir(parents=True)
    return repo


def _tasks_for(repo, *, specs):
    return [{
        "repo": str(repo), "task": "t", "prompt": "p",
        "asset_specs_json": json.dumps(specs),
    }]


_ELEPHANT = {
    "name": "elephant", "prompt": "a friendly cartoon elephant waving hello",
    "style": "cartoon", "width": 1024, "height": 1024,
    "target_rel_path": "public/assets/elephant.png",
}


def test_maybe_generate_flag_off_is_a_noop(tmp_path, monkeypatch):
    monkeypatch.setenv("BLARAI_ENABLE_ASSET_GENERATION", "0")   # EXPLICIT opt-out (default is now ON)
    projects = tmp_path / "projects"
    repo = _repo_under(projects)
    ao = _FakeAO(gen=lambda spec: b"PNGBYTES")
    ao._maybe_generate_dispatch_assets(
        _tasks_for(repo, specs=[_ELEPHANT]), SimpleNamespace(projects_dir=projects), "s"
    )
    assert ao.generated == [] and ao.committed == []       # nothing generated when dormant
    assert not (repo / "public" / "assets" / "elephant.png").exists()


def test_maybe_generate_writes_and_commits_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("BLARAI_ENABLE_ASSET_GENERATION", "1")
    projects = tmp_path / "projects"
    repo = _repo_under(projects)
    ao = _FakeAO(gen=lambda spec: b"REALPNGBYTES")
    ao._maybe_generate_dispatch_assets(
        _tasks_for(repo, specs=[_ELEPHANT]), SimpleNamespace(projects_dir=projects), "sess"
    )
    dest = repo / "public" / "assets" / "elephant.png"
    assert dest.is_file() and dest.read_bytes() == b"REALPNGBYTES"   # written to the web-served dir
    assert ao.generated == [("public/assets/elephant.png", "sess")]
    assert ao.committed == [(repo.resolve(), ["public/assets/elephant.png"])]  # committed the named file
    assert ao.pipeline_unloaded == 1   # #714: the 14B is evicted BEFORE generation (fast, no thrash)


def test_maybe_generate_no_image_writes_nothing_no_commit(tmp_path, monkeypatch):
    monkeypatch.setenv("BLARAI_ENABLE_ASSET_GENERATION", "1")
    projects = tmp_path / "projects"
    repo = _repo_under(projects)
    ao = _FakeAO(gen=lambda spec: None)                    # generation fail-soft -> None
    ao._maybe_generate_dispatch_assets(
        _tasks_for(repo, specs=[_ELEPHANT]), SimpleNamespace(projects_dir=projects), "s"
    )
    assert not (repo / "public" / "assets" / "elephant.png").exists()
    assert ao.committed == []                              # nothing written -> no commit


def test_maybe_generate_gen_raises_is_swallowed(tmp_path, monkeypatch):
    monkeypatch.setenv("BLARAI_ENABLE_ASSET_GENERATION", "1")
    projects = tmp_path / "projects"
    repo = _repo_under(projects)

    def _boom(spec):
        raise RuntimeError("generation blew up")

    ao = _FakeAO(gen=_boom)
    # MUST NOT raise (a raise here would abort the dispatch swap).
    ao._maybe_generate_dispatch_assets(
        _tasks_for(repo, specs=[_ELEPHANT]), SimpleNamespace(projects_dir=projects), "s"
    )
    assert ao.committed == []


def test_maybe_generate_no_specs_is_noop(tmp_path, monkeypatch):
    monkeypatch.setenv("BLARAI_ENABLE_ASSET_GENERATION", "1")
    projects = tmp_path / "projects"
    repo = _repo_under(projects)
    ao = _FakeAO(gen=lambda spec: b"X")
    tasks = [{"repo": str(repo), "task": "t", "prompt": "p"}]   # NO asset_specs_json
    ao._maybe_generate_dispatch_assets(tasks, SimpleNamespace(projects_dir=projects), "s")
    assert ao.generated == [] and ao.committed == []


def test_maybe_generate_no_resolved_config_skips(tmp_path, monkeypatch):
    monkeypatch.setenv("BLARAI_ENABLE_ASSET_GENERATION", "1")
    projects = tmp_path / "projects"
    repo = _repo_under(projects)
    ao = _FakeAO(gen=lambda spec: b"X", resolved=None)     # no resolved config -> skip
    ao._maybe_generate_dispatch_assets(
        _tasks_for(repo, specs=[_ELEPHANT]), SimpleNamespace(projects_dir=projects), "s"
    )
    assert ao.generated == [] and ao.committed == []


def test_maybe_generate_repo_outside_projects_dir_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("BLARAI_ENABLE_ASSET_GENERATION", "1")
    projects = tmp_path / "projects"
    projects.mkdir()
    outside = tmp_path / "elsewhere"                        # a repo NOT under projects_dir
    (outside / ".git").mkdir(parents=True)
    ao = _FakeAO(gen=lambda spec: b"X")
    ao._maybe_generate_dispatch_assets(
        _tasks_for(outside, specs=[_ELEPHANT]), SimpleNamespace(projects_dir=projects), "s"
    )
    assert ao.generated == [] and ao.committed == []       # validate_repo refused -> skipped
    assert not (outside / "public" / "assets" / "elephant.png").exists()


# ---- _generate_one_dispatch_asset (the per-asset generate) ----------------


class _GenAO:
    """Carries just what `_generate_one_dispatch_asset` reads: the style-config resolver +
    `_generate_image_bytes` (stubbed to record the prompt it is asked to render)."""

    def __init__(self):
        self._resolved_config = SimpleNamespace()
        self.gen_calls: list = []

    def _image_gen_config_for_style(self, resolved, style):
        # a REAL frozen ImageGenConfig (dataclasses.replace needs one); hires ON so the test
        # proves the seam forces it OFF.
        return image_gen.ImageGenConfig(enabled=True, hires_enabled=True)

    def _generate_image_bytes(self, *, mode, prompt, width, height, steps, seed,
                              staging_ref, staging_image_id):
        self.gen_calls.append({"mode": mode, "prompt": prompt, "width": width, "height": height, "steps": steps})
        return b"PNGDATA"

    _generate_one_dispatch_asset = AssistantOrchestratorService._generate_one_dispatch_asset


@pytest.fixture
def _patched_image_gen(monkeypatch):
    configured: list = []
    unloaded: list = []
    monkeypatch.setattr(entrypoint.image_gen, "configure", lambda cfg: configured.append(cfg))
    monkeypatch.setattr(entrypoint.image_gen, "is_available", lambda: True)
    monkeypatch.setattr(entrypoint.image_gen, "unload", lambda: unloaded.append(True))
    monkeypatch.setattr(entrypoint, "_adjudicate_tool_dispatch", lambda *a: None)   # PA ALLOW
    return SimpleNamespace(configured=configured, unloaded=unloaded)


def test_generate_one_cartoon_wraps_prompt_forces_hires_off_and_unloads(_patched_image_gen):
    ao = _GenAO()
    out = ao._generate_one_dispatch_asset(dict(_ELEPHANT), "sess")
    assert out == b"PNGDATA"
    # the flat-vector template was wrapped on (the /illustrate look, applied here below the gateway)
    assert ao.gen_calls[0]["prompt"] == (
        "vector illustration of a friendly cartoon elephant waving hello, "
        "flat design, bold outlines, solid color background"
    )
    assert ao.gen_calls[0]["mode"] == image_gen.KIND_TEXT2IMAGE
    assert ao.gen_calls[0]["steps"] == entrypoint._DISPATCH_ASSET_STEPS == 18   # #714 reduced steps
    # hires FORCED off (base 1024²) + the model is always unloaded after
    assert _patched_image_gen.configured[0].hires_enabled is False
    assert _patched_image_gen.unloaded == [True]


def test_generate_one_photoreal_uses_raw_prompt(_patched_image_gen):
    ao = _GenAO()
    spec = {**_ELEPHANT, "style": "photoreal"}
    ao._generate_one_dispatch_asset(spec, "s")
    assert ao.gen_calls[0]["prompt"] == "a friendly cartoon elephant waving hello"  # NO wrap


def test_generate_one_unavailable_returns_none_without_generating(monkeypatch):
    monkeypatch.setattr(entrypoint.image_gen, "configure", lambda cfg: None)
    monkeypatch.setattr(entrypoint.image_gen, "is_available", lambda: False)   # model absent
    monkeypatch.setattr(entrypoint.image_gen, "unload", lambda: None)
    monkeypatch.setattr(entrypoint, "_adjudicate_tool_dispatch", lambda *a: None)
    ao = _GenAO()
    assert ao._generate_one_dispatch_asset(dict(_ELEPHANT), "s") is None
    assert ao.gen_calls == []                             # never reached the generate


def test_generate_one_pa_deny_returns_none(_patched_image_gen, monkeypatch):
    monkeypatch.setattr(entrypoint, "_adjudicate_tool_dispatch", lambda *a: ("DENY", "layer3-lock"))
    ao = _GenAO()
    assert ao._generate_one_dispatch_asset(dict(_ELEPHANT), "s") is None
    assert ao.gen_calls == []                             # PA deny -> never generated


def test_generate_one_empty_subject_returns_none(_patched_image_gen):
    ao = _GenAO()
    assert ao._generate_one_dispatch_asset({**_ELEPHANT, "prompt": "   "}, "s") is None
    assert ao.gen_calls == []


# ---- _commit_dispatch_assets (surgical, named-file commit) ----------------


def test_commit_dispatch_assets_commits_only_named_files(tmp_path):
    repo = tmp_path / "proj"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    (repo / "public" / "assets").mkdir(parents=True)
    (repo / "public" / "assets" / "elephant.png").write_bytes(b"PNG")
    (repo / "untracked.txt").write_text("should NOT be swept in")   # proves it is not `git add -A`

    AssistantOrchestratorService._commit_dispatch_assets(
        object(), repo, ["public/assets/elephant.png"]
    )
    # the asset is committed (HEAD subject names it), the untracked file is NOT committed
    subj = subprocess.run(["git", "-C", str(repo), "log", "-1", "--format=%s"],
                          capture_output=True, text=True).stdout.strip()
    assert "generated image asset" in subj
    tracked = subprocess.run(["git", "-C", str(repo), "ls-files"], capture_output=True, text=True).stdout
    assert "public/assets/elephant.png" in tracked
    assert "untracked.txt" not in tracked                 # surgical: never `git add -A`


def test_commit_dispatch_assets_bad_repo_is_failsoft(tmp_path):
    # A non-git dir -> the git commands fail; the method must NOT raise (fail-soft).
    not_a_repo = tmp_path / "plain"
    not_a_repo.mkdir()
    AssistantOrchestratorService._commit_dispatch_assets(
        object(), not_a_repo, ["assets/x.png"]
    )   # no assertion needed — the win condition is "did not raise"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
