"""Rules-corpus gate (#1690).

docs/governance/rules-corpus.yaml and rules-gaps.md are GENERATED from CLAUDE.md by
scripts/extract_rules_corpus.py. These tests make drift a failure rather than a habit:
the committed files must equal a fresh extraction, every record must hash to its own text,
every enforcement reference must exist, no critical rule may be silently omitted, and the
extractor must refuse (not emit a partial corpus) on a malformed CLAUDE.md.

Each control has a toggle test: an edited rule, a deleted rule and a tampered record each
make the corresponding check FAIL, so a pass is distinguishable from a check that cannot
see the change.
"""
from __future__ import annotations

import hashlib
import importlib.util
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("extract_rules_corpus", REPO / "scripts" / "extract_rules_corpus.py")
ex = importlib.util.module_from_spec(_spec)
sys.modules["extract_rules_corpus"] = ex
_spec.loader.exec_module(ex)

FIX = "Run: python scripts/extract_rules_corpus.py  (CLAUDE.md is the only authored source; never hand-edit the corpus)"
KINDS = {"test", "hook", "verifier", "reviewer", "gate", "none"}
CLAUDE_RAW = (REPO / "CLAUDE.md").read_text(encoding="utf-8")


def _norm(s: str) -> str:
    return s.replace("\r\n", "\n")


def _committed() -> str:
    return _norm((REPO / "docs/governance/rules-corpus.yaml").read_text(encoding="utf-8"))


def _fresh() -> tuple[str, str]:
    return ex.render_corpus(ex.build_records(CLAUDE_RAW, REPO)), ex.render_gaps(ex.build_records(CLAUDE_RAW, REPO))


def check_hashes(records: list[dict]) -> list[str]:
    return [r["id"] for r in records
            if hashlib.sha256(r["text"].encode("utf-8")).hexdigest() != r["text_sha256"]]


def check_paths(records: list[dict], root: Path = REPO) -> list[str]:
    bad = []
    for r in records:
        for e in r["enforcement"]:
            if e["kind"] not in KINDS:
                bad.append(f"{r['id']}: unknown kind {e['kind']}")
            elif e["kind"] == "none":
                continue
            elif not e["ref"]:
                bad.append(f"{r['id']}: kind {e['kind']} has no ref")
            elif e["ref"].startswith("external:"):
                continue
            elif not (root / e["ref"]).is_file():
                bad.append(f"{r['id']}: {e['ref']} does not exist")
    return bad


def corpus_is_stale(committed: str, raw: str) -> bool:
    return ex.render_corpus(ex.build_records(raw, REPO)) != committed


def critical_gap(records: list[dict], raw: str) -> tuple[int, int]:
    block = _norm(raw).split("<critical_rules", 1)[1].split("</critical_rules>", 1)[0]
    expected = len(re.findall(r"^\d+\. ", block, flags=re.M))
    have = sum(1 for r in records if r["id"].startswith("critical_rules."))
    return expected, have


def test_committed_corpus_equals_a_fresh_extraction() -> None:
    corpus, gaps = _fresh()
    assert not corpus_is_stale(_committed(), CLAUDE_RAW), f"rules-corpus.yaml is stale against CLAUDE.md. {FIX}"
    committed_gaps = _norm((REPO / "docs/governance/rules-gaps.md").read_text(encoding="utf-8"))
    assert committed_gaps == gaps, f"rules-gaps.md is stale against CLAUDE.md or the enforcement map. {FIX}"


def test_every_record_hashes_to_its_own_text() -> None:
    recs = ex.parse_corpus(_committed())
    assert recs, "corpus is empty"
    assert check_hashes(recs) == []


def test_committed_file_round_trips_and_is_valid_yaml() -> None:
    recs = ex.parse_corpus(_committed())
    assert ex.render_corpus(recs) == _committed()
    if importlib.util.find_spec("yaml") is not None:
        import yaml
        assert yaml.safe_load(_committed()) == recs


def test_every_enforcement_reference_exists_on_disk() -> None:
    assert check_paths(ex.parse_corpus(_committed())) == []


def test_ids_are_unique_and_why_pointers_resolve() -> None:
    recs = ex.parse_corpus(_committed())
    ids = [r["id"] for r in recs]
    assert len(ids) == len(set(ids))
    evidence = (REPO / "docs/governance/agent-doctrine-evidence.md").read_text(encoding="utf-8")
    for r in recs:
        if r["why_pointer"]:
            assert f"**{r['why_pointer'].split('#', 1)[1]}**" in evidence, r["id"]


def test_no_critical_rule_is_silently_omitted() -> None:
    recs = ex.parse_corpus(_committed())
    expected, have = critical_gap(recs, CLAUDE_RAW)
    assert expected >= 10 and have == expected, f"CLAUDE.md has {expected} critical rules, corpus has {have}. {FIX}"
    assert any(r["severity"] == "critical" for r in recs)


def test_every_rule_line_in_a_rule_section_has_a_record() -> None:
    # Independent of the extractor's own emit path: count list items + prose lines in two
    # rule-bearing sections straight from the raw text.
    for tag, prefix in (("security_by_design", "security_by_design."), ("git_discipline", "git_discipline.")):
        block = _norm(CLAUDE_RAW).split(f"<{tag}", 1)[1].split(f"</{tag}>", 1)[0].split("\n")[1:]
        content = [ln for ln in block if ln.strip() and not ln.startswith("<") or re.match(r"^<\w+[^>]*>.+</\w+>$", ln)]
        have = sum(1 for r in ex.parse_corpus(_committed()) if r["id"].startswith(prefix))
        assert have == len(content), f"{tag}: {len(content)} content lines, {have} records. {FIX}"


# ---- toggle tests: each control must FAIL when its subject is perturbed -------------------

def test_toggle_edited_rule_changes_output_and_fails_committed_check() -> None:
    edited = CLAUDE_RAW.replace("corrupted his real sessions.db.", "corrupted his real sessions.db, twice.")
    assert edited != CLAUDE_RAW
    assert not corpus_is_stale(_committed(), CLAUDE_RAW)       # control: unedited is fresh
    assert corpus_is_stale(_committed(), edited)


def test_toggle_deleted_rule_fails_committed_and_critical_count() -> None:
    lines = _norm(CLAUDE_RAW).split("\n")
    idx = next(i for i, ln in enumerate(lines) if ln.startswith("8. Redirect LOCALAPPDATA"))
    cut = "\n".join(lines[:idx] + lines[idx + 1:])
    # Deleting a rule that enforcement markers name is refused outright (loud, not stale).
    with pytest.raises(ex.RulesCorpusError, match="do not exist"):
        corpus_is_stale(_committed(), cut)
    # The completeness check compares CLAUDE.md to the COMMITTED corpus: a corpus that kept a
    # rule CLAUDE.md dropped, or the reverse, disagrees.
    expected, have = critical_gap(ex.parse_corpus(_committed()), cut)
    assert expected != have


def test_toggle_omitted_record_trips_critical_count() -> None:
    recs = [r for r in ex.parse_corpus(_committed()) if r["id"] != "critical_rules.you-are-not-blarai"]
    expected, have = critical_gap(recs, CLAUDE_RAW)
    assert expected != have


def test_toggle_tampered_text_trips_hash_check() -> None:
    recs = ex.parse_corpus(_committed())
    recs[0]["text"] += " (edited by hand)"
    assert check_hashes(recs) == [recs[0]["id"]]


def test_toggle_fabricated_enforcement_path_trips_exists_check() -> None:
    recs = ex.parse_corpus(_committed())
    recs[0]["enforcement"] = [{"kind": "test", "ref": "tests/security/test_that_does_not_exist.py"}]
    assert check_paths(recs) == [f"{recs[0]['id']}: tests/security/test_that_does_not_exist.py does not exist"]


def test_toggle_missing_evidence_degrades_enforcement_to_none(tmp_path: Path) -> None:
    recs = ex.build_records(CLAUDE_RAW, tmp_path)  # empty root: no enforcing file exists
    for r in recs:
        for e in r["enforcement"]:
            assert e["kind"] == "none" or e["ref"].startswith("external:"), (r["id"], e)


def test_gap_list_names_every_rule_without_machine_enforcement() -> None:
    recs = ex.parse_corpus(_committed())
    gaps = _norm((REPO / "docs/governance/rules-gaps.md").read_text(encoding="utf-8"))
    for r in recs:
        weak = all(e["kind"] in ("none", "reviewer") for e in r["enforcement"])
        assert (f"| {r['id']} |" in gaps) == weak, r["id"]


# ---- enforcement is trace-marked: markers + curated entries, nothing inferred -------------

def _lines(raw: str) -> list[str]:
    return _norm(raw).split("\n")


def _insert_before(raw: str, startswith: str, new_line: str) -> str:
    lines = _lines(raw)
    idx = next(i for i, ln in enumerate(lines) if ln.startswith(startswith))
    return "\n".join(lines[:idx] + [new_line] + lines[idx:])


def _by_id(raw: str) -> dict[str, list]:
    return {r["id"]: r["enforcement"] for r in ex.build_records(raw, REPO)}


def _scan_markers_independently() -> set[tuple[str, str]]:
    # Own re-scan (not the extractor's): (rule, ref) for every marker line in the repo.
    pat = re.compile(r"^\s*(?:#\s*|//\s*)?enforces-rule:\s*(\S+)", re.M)
    found = set()
    for top in ("tests", "scripts", "services", "shared", "launcher", ".claude"):
        for f in (REPO / top).rglob("*"):
            if f.suffix not in (".py", ".ps1", ".sh") or "__pycache__" in f.parts:
                continue
            rel = f.relative_to(REPO).as_posix()
            if rel.startswith(".claude/worktrees/"):  # another branch's checkout parked in this one; not this tree
                continue
            if rel in ex.MARKER_SELF:
                continue
            for m in pat.finditer(f.read_text(encoding="utf-8", errors="replace")):
                found.add((m.group(1), rel))
    root_conftest = REPO / "conftest.py"
    for m in pat.finditer(root_conftest.read_text(encoding="utf-8")):
        found.add((m.group(1), "conftest.py"))
    return found


def test_enforcement_column_equals_an_independent_rescan_of_markers_and_curated_entries() -> None:
    expected = _scan_markers_independently()
    for e in ex.load_curated(REPO):
        expected.add((e["rule"], e["ref"]))
    actual = {(r["id"], e["ref"]) for r in ex.parse_corpus(_committed())
              for e in r["enforcement"] if e["kind"] != "none"}
    assert actual == expected, f"enforcement column disagrees with the markers in the repo. {FIX}"
    assert len(actual) >= 25


def test_git_rules_are_enforced_by_the_guard_hook() -> None:
    by = {r["id"]: r["enforcement"] for r in ex.parse_corpus(_committed())}
    for rid in ("critical_rules.git-has-no-human-safety-net", "git_discipline.shared_tree.no-git-add-a-ever",
                "git_discipline.absolute_rules.never-commit-work-directly-to-main"):
        assert any(e["kind"] == "hook" and e["ref"] == "scripts/hooks/git_rules_guard.py" for e in by[rid]), rid


def _root_with(tmp_path: Path, rel: str, body: str) -> Path:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return tmp_path


def test_marker_naming_an_unknown_rule_id_fails(tmp_path: Path) -> None:
    root = _root_with(tmp_path, "tests/security/test_x.py", "# enforces-rule: critical_rules.no-such-rule\n")
    with pytest.raises(ex.RulesCorpusError, match="do not exist"):
        ex.build_records(CLAUDE_RAW, root)


def test_marker_naming_a_known_rule_id_is_picked_up_with_a_path_derived_kind(tmp_path: Path) -> None:
    root = _root_with(tmp_path, "tests/security/test_x.py",
                      "# enforces-rule: critical_rules.you-are-not-blarai -- demo note\n")
    rec = next(r for r in ex.build_records(CLAUDE_RAW, root) if r["id"] == "critical_rules.you-are-not-blarai")
    assert rec["enforcement"] == [{"kind": "test", "ref": "tests/security/test_x.py", "note": "demo note"}]


def test_markers_inside_a_nested_session_worktree_are_not_scanned(tmp_path: Path) -> None:
    """A checkout parked under .claude/worktrees/ is another branch's tree: its markers must not reach the corpus
    (they would fail the kind check under that prefix, and would double-count refs if they passed)."""
    root = _root_with(tmp_path, ".claude/worktrees/some-session/scripts/verify_x.py",
                      "# enforces-rule: critical_rules.you-are-not-blarai\n")
    _root_with(tmp_path, ".claude/worktrees/some-session/tests/security/test_x.py",
               "# enforces-rule: critical_rules.you-are-not-blarai\n")
    rec = next(r for r in ex.build_records(CLAUDE_RAW, root) if r["id"] == "critical_rules.you-are-not-blarai")
    assert all(e["kind"] == "none" and ".claude/worktrees" not in e["ref"] for e in rec["enforcement"]), rec["enforcement"]


def test_marker_in_a_file_whose_path_implies_no_kind_fails(tmp_path: Path) -> None:
    root = _root_with(tmp_path, "scripts/helper.py", "# enforces-rule: critical_rules.you-are-not-blarai\n")
    with pytest.raises(ex.RulesCorpusError, match="implies no kind"):
        ex.build_records(CLAUDE_RAW, root)


def test_curated_entry_with_a_missing_ref_or_unknown_rule_fails(tmp_path: Path) -> None:
    gov = "docs/governance/rules-enforcement.yaml"
    root = _root_with(tmp_path, gov, '- {"rule": "critical_rules.you-are-not-blarai", "kind": "test", "ref": "nope.py"}\n')
    with pytest.raises(ex.RulesCorpusError, match="does not exist"):
        ex.build_records(CLAUDE_RAW, root)
    root = _root_with(tmp_path, gov, '- {"rule": "x.y", "kind": "hook", "ref": "external:~/h.py"}\n')
    with pytest.raises(ex.RulesCorpusError, match="do not exist"):
        ex.build_records(CLAUDE_RAW, root)


def test_renaming_a_rule_breaks_the_marker_loudly_instead_of_moving_it() -> None:
    renamed = CLAUDE_RAW.replace("You are NOT BlarAI.", "You are not the product.")
    assert renamed != CLAUDE_RAW
    with pytest.raises(ex.RulesCorpusError, match="you-are-not-blarai"):
        ex.build_records(renamed, REPO)


# ---- id stability (name-derived ids) ----------------------------------------------------------

def test_inserting_a_principle_at_position_3_moves_no_other_id_or_enforcement() -> None:
    before = _by_id(CLAUDE_RAW)
    after = _by_id(_insert_before(CLAUDE_RAW, "3. DEFENSE-IN-DEPTH", "3. BRAND-NEW-PRINCIPLE: a new rule."))
    assert "security_by_design.principles.brand-new-principle" in after
    for rid, enf in before.items():
        assert after[rid] == enf, rid
    assert len(after) == len(before) + 1


def test_inserting_a_critical_rule_at_position_5_moves_no_other_id_or_enforcement() -> None:
    before = _by_id(CLAUDE_RAW)
    after = _by_id(_insert_before(CLAUDE_RAW, "5. Every ship", "5. Brand new critical rule. Details."))
    for rid, enf in before.items():
        assert after[rid] == enf, rid
    assert any(k.startswith("critical_rules.brand-new") for k in after)


def test_an_id_collision_fails_loudly() -> None:
    dup = _insert_before(CLAUDE_RAW, "3. DEFENSE-IN-DEPTH", "3. FAIL-CLOSED: second one.")
    with pytest.raises(ex.RulesCorpusError, match="duplicate rule id"):
        ex.build_records(dup, REPO)


# ---- fact sections: per-item classification, volatile snapshot ----------------------------------

_FACTS = ("<blarai_project_instructions>\n<stack>\n- Never install runtime deps.\n- Python 3.11 is used.\n"
          "</stack>\n<status_snapshot as_of=\"x\">\n- Phase 5 ACTIVE\n</status_snapshot>\n</blarai_project_instructions>\n")


def test_imperative_items_in_fact_sections_are_rules_and_plain_facts_are_not() -> None:
    recs, stats = ex.parse_claude_md_full(_FACTS)
    assert [r["id"] for r in recs] == ["stack.never-install-runtime-deps"]
    assert stats["facts_excluded"] == 1 and stats["status_snapshot_lines"] == 1


def test_whitespace_noise_in_the_volatile_snapshot_does_not_break_extraction() -> None:
    noisy = _FACTS.replace("- Phase 5 ACTIVE", "- Phase 5 ACTIVE   ").replace("</status_snapshot>", "  indented\n</status_snapshot>")
    assert [r["id"] for r in ex.parse_claude_md(noisy)] == ["stack.never-install-runtime-deps"]


def test_readme_publishes_the_true_fact_exclusion_counts() -> None:
    _recs, stats = ex.parse_claude_md_full(CLAUDE_RAW)
    readme = (REPO / "docs/governance/rules-corpus-README.md").read_text(encoding="utf-8")
    want = (f"{stats['fact_items_included_as_rules']} fact-section items included as rules, "
            f"{stats['facts_excluded']} fact items excluded, {stats['status_snapshot_lines']} snapshot")
    assert " ".join(want.split()) in " ".join(readme.split()), f"README counts are stale; should read: {want}"


# ---- fail-closed on malformed CLAUDE.md ---------------------------------------------------

_MIN = "<blarai_project_instructions>\n<critical_rules>\n1. A rule.\n</critical_rules>\n</blarai_project_instructions>\n"


def test_minimal_wellformed_input_parses() -> None:
    assert [r["id"] for r in ex.parse_claude_md(_MIN)] == ["critical_rules.a-rule"]


@pytest.mark.parametrize("bad", [
    _MIN.replace("</critical_rules>", "</wrong_tag>"),
    _MIN.replace("</blarai_project_instructions>\n", ""),
    _MIN.replace("<critical_rules>", "<brand_new_unclassified_tag>").replace("</critical_rules>", "</brand_new_unclassified_tag>"),
    _MIN.replace("<critical_rules>", "<critical_rules"),
    _MIN.replace("1. A rule.", "  indented surprise"),
    _MIN + "stray text after the root\n",
    "<critical_rules>\n1. A rule.\n</critical_rules>\n",
    _MIN.replace("1. A rule.\n", "1. A rule.\n2. B rule.\n</critical_rules>\n<critical_rules>\n2. B rule.\n"),
])
def test_malformed_claude_md_is_refused(bad: str) -> None:
    with pytest.raises(ex.RulesCorpusError):
        ex.parse_claude_md(bad)


def test_cli_refuses_and_writes_nothing_on_malformed_input(tmp_path: Path, monkeypatch) -> None:
    broken = tmp_path / "CLAUDE.md"
    broken.write_text(_MIN.replace("</critical_rules>", "</wrong_tag>"), encoding="utf-8")
    out, gaps = tmp_path / "rules-corpus.yaml", tmp_path / "rules-gaps.md"
    monkeypatch.setattr(ex, "CLAUDE_MD", broken)
    monkeypatch.setattr(ex, "CORPUS_OUT", out)
    monkeypatch.setattr(ex, "GAPS_OUT", gaps)
    monkeypatch.setattr(ex, "REPO_ROOT", tmp_path)  # no markers under the temp root
    assert ex.main([]) == 2
    assert not out.exists() and not gaps.exists()


def test_cli_check_mode_detects_stale_output(tmp_path: Path, monkeypatch) -> None:
    good = tmp_path / "CLAUDE.md"
    good.write_text(_MIN, encoding="utf-8")
    out, gaps = tmp_path / "rules-corpus.yaml", tmp_path / "rules-gaps.md"
    monkeypatch.setattr(ex, "CLAUDE_MD", good)
    monkeypatch.setattr(ex, "CORPUS_OUT", out)
    monkeypatch.setattr(ex, "GAPS_OUT", gaps)
    monkeypatch.setattr(ex, "REPO_ROOT", tmp_path)  # no markers under the temp root
    assert ex.main(["--check"]) == 1          # nothing written yet: stale
    assert ex.main([]) == 0
    assert ex.main(["--check"]) == 0          # fresh
    good.write_text(_MIN.replace("A rule.", "A changed rule."), encoding="utf-8")
    assert ex.main(["--check"]) == 1          # CLAUDE.md moved on


def test_extraction_is_deterministic() -> None:
    assert _fresh() == _fresh()
    assert ex.render_corpus(ex.build_records(CLAUDE_RAW.replace("\n", "\r\n"), REPO)) == _fresh()[0]
