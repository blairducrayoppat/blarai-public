"""Gate lock for the account-level containment evidence bundle (2026-10-05).

WHAT FAILURE THIS EXISTS FOR
----------------------------
The bundle publishes raw spike data and scripts from the operator's machine. These must stay true:
(a) no operator user name, machine name or real machine SID domain appears in any bundle file; (b) model text in the raw
results is cut to 100 characters; (c) CHANGES.md and the as-run MANIFEST are exactly what make_changes.py generates from the bundle, and the as-run script
hashes match the recorded manifest (the results come from those versions; the hardened set is labelled as later);
(d) every file the evidence document cites exists; (e) every claim row states all seven columns with a status from the
defined vocabulary; (f) the document keeps its limits section; (g) every bundled script's own -SelfTest (as-run and hardened sets) still passes under
PowerShell 7 and Windows PowerShell 5.1; (h) no control character (other than newline and tab) in any document; (i) all of the above hold on a copy
converted to CRLF (a Windows checkout with core.autocrlf=true): hashes, counts and the generator use LF-normalised bytes (a sanitiser once rewrote fake test SIDs into forms the scripts reject).

HONEST LIMIT: this locks the FORM (paths exist, columns non-empty, names scrubbed, self-tests run). It cannot see
whether a cited file supports the claim beside it; that is review's job. The -SelfTest runs create only temp
files, junctions and links under a temp directory and change no system state.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC = REPO_ROOT / "docs" / "research" / "account-level-containment-evidence-2026-10-05.md"
BUNDLE = REPO_ROOT / "docs" / "research" / "containment-evidence-2026-10-05"

# Built by concatenation so this file itself is not a leak.
FORBIDDEN = ("mr" + "bla", "NORTH" + "STAR100")
USER_PH, MACH_PH = "_OPERATOR_", "_MACHINE_"
PH_DOMAINS = ("1000000001-1000000002-1000000003", "1000000004-1000000005-1000000006")
# Allowed SID domains: the two placeholders and the fabricated literals the scripts use in their own self-tests.
ALLOWED_DOMAINS = set(PH_DOMAINS) | {"1111111111-2222222222-3333333333", "1-2-3"}
SID_RE = re.compile(r"S-1-5-21-(\d+-\d+-\d+)")
COLUMNS = 7
STATUS_RE = re.compile(r"OBSERVED|STATIC|NOT ESTABLISHED|CONTRADICTED")
PATH_RE = re.compile(r"`((?:docs|tests|scripts|services|shared)/[^`\s]+?)`")
CUT = 100
MARKER = "...[truncated to 100 chars]"
META = {"README.md", "CHANGES.md", "make_changes.py"}  # authored here (top level), not copies
AS_RUN = "confined-model-spike/as-run"


def bundle_files() -> list[Path]:
    return sorted(p for p in BUNDLE.rglob("*") if p.is_file() and "__pycache__" not in p.parts)


def leaked_names(root: Path) -> list[str]:
    hits: list[str] = []
    for f in sorted(p for p in root.rglob("*") if p.is_file()):
        text = f.read_bytes().decode("utf-8", errors="replace").lower()
        rel = f.relative_to(root).as_posix()
        for needle in FORBIDDEN:
            if needle.lower() in text or needle.lower() in rel.lower():
                hits.append(f"{rel}: {needle}")
    return hits


def foreign_sid_domains(root: Path) -> list[str]:
    bad: list[str] = []
    for f in bundle_files_in(root):
        text = f.read_bytes().decode("utf-8", errors="replace")
        for m in SID_RE.finditer(text):
            if m.group(1) not in ALLOWED_DOMAINS:
                bad.append(f"{f.name}: {m.group(0)}")
    return bad


def bundle_files_in(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts)


def overlong_model_text(value, path: str = "") -> list[str]:
    """Strings under keys text/completion longer than the cut (plus marker), and unparseable-or-long `body` values."""
    bad: list[str] = []
    if isinstance(value, dict):
        for k, v in value.items():
            if k in ("text", "completion") and isinstance(v, str) and len(v) > CUT + len(MARKER):
                bad.append(f"{path}/{k}")
            elif k in ("text", "completion") and isinstance(v, str) and len(v) > CUT and not v.endswith(MARKER):
                bad.append(f"{path}/{k} (cut without marker)")
            elif k == "body" and isinstance(v, str):
                try:
                    bad += overlong_model_text(json.loads(v), f"{path}/body")
                except ValueError:
                    if len(v) > CUT:
                        bad.append(f"{path}/body")
            else:
                bad += overlong_model_text(v, f"{path}/{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            bad += overlong_model_text(v, f"{path}[{i}]")
    return bad


def claim_rows(text: str) -> list[list[str]]:
    rows = []
    for line in text.splitlines():
        if re.match(r"\|\s*C\d", line):
            rows.append([c.strip() for c in line.strip().strip("|").split(" | ")])
    return rows


def cited_paths(text: str) -> list[str]:
    return sorted({m.group(1) for m in PATH_RE.finditer(text)})


def missing_paths(text: str) -> list[str]:
    return [p for p in cited_paths(text) if not (REPO_ROOT / p).exists()]


def incomplete_rows(text: str) -> list[str]:
    return [cells[0] if cells else "?" for cells in claim_rows(text) if len(cells) != COLUMNS or any(not c for c in cells)]


def bad_status_rows(text: str) -> list[str]:
    return [cells[0] for cells in claim_rows(text) if len(cells) == COLUMNS and not STATUS_RE.search(cells[4])]


def has_limits_section(text: str) -> bool:
    return re.search(r"^## \d+\. Limits \(what this does not establish\)\s*$", text, re.MULTILINE) is not None


def changes_rows(text: str) -> dict[str, tuple[int, int, int, int]]:
    out: dict[str, tuple[int, int, int, int]] = {}
    for line in text.splitlines():
        m = re.match(r"\|\s*`([^`]+)`\s*\|[^|]*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|[^|]*\|\s*$", line)
        if m:
            out[m.group(1)] = tuple(int(m.group(i)) for i in range(2, 6))  # type: ignore[assignment]
    return out


def changes_mismatches(root: Path) -> list[str]:
    """CHANGES.md must list every non-meta bundle file and its placeholder counts must equal the files' contents."""
    table = changes_rows((root / "CHANGES.md").read_text(encoding="utf-8"))
    bad: list[str] = []
    files = {
        p.relative_to(root).as_posix(): p
        for p in bundle_files_in(root)
        if p.relative_to(root).as_posix() not in META and not p.name.startswith("MANIFEST")
    }
    for rel in sorted(set(files) - set(table)):
        bad.append(f"{rel}: not in CHANGES.md")
    for rel in sorted(set(table) - set(files)):
        bad.append(f"{rel}: in CHANGES.md but missing")
    for rel, p in files.items():
        if rel not in table:
            continue
        text = p.read_bytes().replace(b"\r\n", b"\n").decode("utf-8")
        got = (text.count(USER_PH), text.count(MACH_PH), sum(text.count(d) for d in PH_DOMAINS))
        if got != table[rel][:3]:
            bad.append(f"{rel}: counts {got} != CHANGES.md {table[rel][:3]}")
    return bad


def control_chars(text: str) -> list[str]:
    return sorted({hex(ord(c)) for c in text if ord(c) < 32 and c not in "\n\t\r"})


def manifest_mismatches(root: Path) -> list[str]:
    """The recorded as-run manifest must equal the sha256 of the as-run files (and cover exactly them)."""
    import hashlib

    recorded: dict[str, str] = {}
    for line in (root / AS_RUN / "MANIFEST.sha256").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            digest, name = line.split("  ", 1)
            recorded[name] = digest
    actual = {
        p.name: hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        for p in (root / AS_RUN).iterdir()
        if p.is_file() and not p.name.startswith("MANIFEST")
    }
    bad = [f"{n}: hash differs from the manifest" for n in actual if recorded.get(n) != actual[n]]
    bad += [f"{n}: in the manifest but missing" for n in recorded if n not in actual]
    return bad


def load_generator():
    import importlib.util

    sys.dont_write_bytecode = True  # never leave a __pycache__ inside the bundle
    spec = importlib.util.spec_from_file_location("containment_make_changes", BUNDLE / "make_changes.py")
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def selftest_failed(returncode: int, output: str) -> bool:
    return returncode != 0 or "[FAIL]" in output or bool(re.search(r"\d+ FAILED", output)) or "STOPPED" in output


# -------------------------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def doc_text() -> str:
    return DOC.read_text(encoding="utf-8")


def test_bundle_has_no_operator_or_machine_name() -> None:
    assert BUNDLE.is_dir()
    assert leaked_names(BUNDLE) == []


def test_evidence_document_has_no_operator_or_machine_name(doc_text: str) -> None:
    assert not any(n.lower() in doc_text.lower() for n in FORBIDDEN)


def test_bundle_has_no_real_sid_domain() -> None:
    assert foreign_sid_domains(BUNDLE) == []
    assert foreign_sid_domains(BUNDLE.parent.parent.parent / "docs" / "research" / "containment-evidence-2026-10-05") == []


def test_model_text_is_cut_in_every_json_file() -> None:
    files = [p for p in bundle_files() if p.suffix == ".json"]
    assert len(files) >= 8
    for f in files:
        assert overlong_model_text(json.loads(f.read_text(encoding="utf-8"))) == [], f.name


def test_changes_table_matches_the_files() -> None:
    assert changes_mismatches(BUNDLE) == []


def lf(path: Path) -> str:
    return path.read_bytes().replace(b"\r\n", b"\n").decode("utf-8")


def generator_mismatches(root: Path) -> list[str]:
    gen = load_generator()
    bad = []
    if lf(root / "CHANGES.md") != gen.render_changes(root):
        bad.append("CHANGES.md")
    if lf(root / AS_RUN / "MANIFEST.sha256") != gen.render_manifest(root):
        bad.append("MANIFEST.sha256")
    return bad


def make_crlf_copy(dest: Path) -> Path:
    """A copy of the bundle with every file converted to CRLF: what a Windows checkout with core.autocrlf=true produces."""
    root = dest / "bundle-crlf"
    shutil.copytree(BUNDLE, root, ignore=shutil.ignore_patterns("__pycache__"))
    for f in root.rglob("*"):
        if f.is_file():
            f.write_bytes(f.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    return root


def test_changes_and_manifest_are_what_the_generator_produces() -> None:
    assert generator_mismatches(BUNDLE) == []


def test_bundle_checks_hold_on_a_crlf_checkout(tmp_path: Path) -> None:
    root = make_crlf_copy(tmp_path)
    assert (root / "CHANGES.md").read_bytes().count(b"\r\n") > 10  # really converted
    assert generator_mismatches(root) == []
    assert manifest_mismatches(root) == []
    assert changes_mismatches(root) == []
    assert leaked_names(root) == []
    assert foreign_sid_domains(root) == []


def test_crlf_copy_still_detects_a_tampered_as_run_file(tmp_path: Path) -> None:
    root = make_crlf_copy(tmp_path)
    f = root / AS_RUN / "spike_model.py"
    f.write_bytes(f.read_bytes() + b"# edit\r\n")
    assert manifest_mismatches(root) != []
    assert generator_mismatches(root) != []


def test_as_run_scripts_match_the_recorded_manifest() -> None:
    assert manifest_mismatches(BUNDLE) == []


def test_document_says_the_scripts_changed_after_the_runs(doc_text: str) -> None:
    assert "CHANGED AFTER the runs" in doc_text and "as-run" in doc_text and "post-run-hardened" in doc_text
    changes = (BUNDLE / "CHANGES.md").read_text(encoding="utf-8")
    assert "Scripts were changed AFTER the runs" in changes


def test_no_control_characters_in_any_markdown_or_text_document(doc_text: str) -> None:
    assert control_chars(doc_text) == []
    for f in bundle_files():
        if f.suffix in (".md", ".txt"):
            assert control_chars(f.read_text(encoding="utf-8")) == [], f.name


def test_document_does_not_claim_the_account_could_not_write_outside_its_folders(doc_text: str) -> None:
    # The raw data shows writes to C:\Windows\Temp and B:\models succeeded; the document must keep saying so.
    assert "`C:\\Windows\\Temp` and `B:\\models`" in doc_text or "C:\\Windows\\Temp" in doc_text
    assert "no correction comment exists" not in doc_text


def test_every_cited_raw_data_path_exists(doc_text: str) -> None:
    assert len(cited_paths(doc_text)) >= 15
    assert missing_paths(doc_text) == []


def test_every_claim_row_has_all_seven_columns(doc_text: str) -> None:
    assert len(claim_rows(doc_text)) >= 12
    assert incomplete_rows(doc_text) == []


def test_status_column_uses_the_defined_vocabulary(doc_text: str) -> None:
    assert bad_status_rows(doc_text) == []


def test_limits_section_is_present(doc_text: str) -> None:
    assert has_limits_section(doc_text)


# ---- every bundled script's -SelfTest must pass (changes no system state) ------------------------------------------
SCRIPTS = [("wfp-spike/wfp-coder-egress-spike.ps1", False)] + [
    (f"confined-model-spike/{subset}/{name}.ps1", name in ("spike-wfp", "spike-verify-cleanup"))
    for subset in ("as-run", "post-run-hardened")
    for name in ("spike-provision", "spike-cleanup", "spike-wfp", "spike-verify-cleanup", "spike-run-test")
] + [
    # arm 1 (the permit filter's role): the two scripts that changed, in the arm's own folder beside its results.
    ("arm1-permit/scripts/spike-wfp.ps1", True),
    ("arm1-permit/scripts/spike-run-test.ps1", False),
    ("arm1-permit/scripts/spike-cleanup.ps1", False),
    ("arm1-permit/scripts/spike-provision.ps1", False),
]
PYTHON_SELFTESTS = ["arm1-permit/scripts/spike_model.py"]
SHELLS = ["pwsh", "powershell"]


@pytest.mark.skipif(sys.platform != "win32", reason="the bundled scripts are Windows PowerShell")
@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("rel,needs_wfp", SCRIPTS)
def test_bundled_script_selftest_passes(shell: str, rel: str, needs_wfp: bool, tmp_path: Path) -> None:
    exe = shutil.which(shell)
    assert exe, f"{shell} not found on a Windows machine: install it or fix PATH (this is a defect, not a skip)"
    script = BUNDLE / rel
    args = [exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-SelfTest"]
    if needs_wfp:
        args += ["-WfpScript", str(BUNDLE / "wfp-spike" / "wfp-coder-egress-spike.ps1")]
    env = dict(os.environ, TEMP=str(tmp_path), TMP=str(tmp_path))
    if shell == "powershell":  # a 5.1 host that inherited a PowerShell 7 module path cannot load its Security module
        env["PSModulePath"] = r"C:\Windows\system32\WindowsPowerShell\v1.0\Modules"
    r = subprocess.run(args, capture_output=True, text=True, timeout=300, env=env, cwd=str(tmp_path))
    out = (r.stdout or "") + (r.stderr or "")
    assert not selftest_failed(r.returncode, out), f"{shell} {rel}\n{out[-3000:]}"
    assert re.search(r"all passed|\d+ passed, 0 failed", out), f"{shell} {rel}: no pass line\n{out[-1500:]}"


@pytest.mark.parametrize("rel", PYTHON_SELFTESTS)
def test_bundled_python_selftest_passes(rel: str, tmp_path: Path) -> None:
    """The account-side model/server script's own --selftest (pure helpers plus an in-process loopback listener)."""
    env = dict(os.environ, TEMP=str(tmp_path), TMP=str(tmp_path))
    r = subprocess.run([sys.executable, "-I", str(BUNDLE / rel), "--selftest"], capture_output=True, text=True, timeout=120, env=env, cwd=str(tmp_path), check=False)
    out = (r.stdout or "") + (r.stderr or "")
    assert r.returncode == 0 and "[FAIL]" not in out and "all passed" in out, f"{rel}: {out[-3000:]}"


# ---- toggle tests: each check must FAIL when the property is broken (security_by_design 12) ----


def test_toggle_leak_check_fails_on_a_planted_name(tmp_path: Path) -> None:
    (tmp_path / "x.txt").write_text("path C:\\Users\\" + FORBIDDEN[0].upper() + "\\x", encoding="utf-8")
    assert leaked_names(tmp_path) != []
    (tmp_path / "x.txt").write_text("path C:\\Users\\_OPERATOR_\\x", encoding="utf-8")
    assert leaked_names(tmp_path) == []


def test_toggle_sid_domain_check_fails_on_a_real_looking_domain(tmp_path: Path) -> None:
    (tmp_path / "x.txt").write_text("S-1-5-21-4125655822-2918122917-2734753367-1001", encoding="utf-8")
    assert foreign_sid_domains(tmp_path) != []
    (tmp_path / "x.txt").write_text("S-1-5-21-1000000001-1000000002-1000000003-1001 and S-1-5-21-1-2-3-1001", encoding="utf-8")
    assert foreign_sid_domains(tmp_path) == []


def test_toggle_truncation_check_fails_on_long_model_text() -> None:
    assert overlong_model_text({"runs": [{"text": "x" * 300}]}) != []
    assert overlong_model_text({"body": json.dumps({"completion": "y" * 300})}) != []
    assert overlong_model_text({"runs": [{"text": "x" * CUT + MARKER}]}) == []


def test_toggle_changes_table_detects_a_wrong_count_and_a_missing_file(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text(f"{USER_PH} {USER_PH}", encoding="utf-8")
    (tmp_path / "b.txt").write_text("plain", encoding="utf-8")
    good = "| `a.txt` | text copy | 2 | 0 | 0 | 0 | - |\n| `b.txt` | text copy | 0 | 0 | 0 | 0 | - |\n"
    (tmp_path / "CHANGES.md").write_text(good, encoding="utf-8")
    assert changes_mismatches(tmp_path) == []
    (tmp_path / "CHANGES.md").write_text(good.replace("| 2 |", "| 1 |"), encoding="utf-8")
    assert changes_mismatches(tmp_path) != []
    (tmp_path / "CHANGES.md").write_text(good.splitlines()[0] + "\n", encoding="utf-8")
    assert changes_mismatches(tmp_path) != []


def test_toggle_control_character_is_detected() -> None:
    assert control_chars("C:\x08larai") != [] and control_chars("a\tb\n") == []


def test_toggle_manifest_detects_a_changed_as_run_file(tmp_path: Path) -> None:
    d = tmp_path / AS_RUN
    d.mkdir(parents=True)
    (d / "a.ps1").write_text("one", encoding="utf-8")
    import hashlib

    good = hashlib.sha256(b"one").hexdigest()
    (d / "MANIFEST.sha256").write_text(f"{good}  a.ps1\n", encoding="utf-8")
    assert manifest_mismatches(tmp_path) == []
    (d / "a.ps1").write_text("two", encoding="utf-8")
    assert manifest_mismatches(tmp_path) != []


def test_toggle_selftest_failure_is_detected() -> None:
    assert selftest_failed(1, "") and selftest_failed(0, "  [FAIL] x") and selftest_failed(0, "STOPPED: x")
    assert not selftest_failed(0, "SelfTest: 45 passed, 0 failed")


def test_toggle_missing_path_check_fails_on_a_dead_citation(doc_text: str) -> None:
    broken = doc_text + "\n`docs/research/containment-evidence-2026-10-05/does-not-exist.json`\n"
    assert missing_paths(broken) == ["docs/research/containment-evidence-2026-10-05/does-not-exist.json"]


def test_toggle_empty_column_is_detected(doc_text: str) -> None:
    first = next(line for line in doc_text.splitlines() if re.match(r"\|\s*C\d", line))
    cells = first.strip().strip("|").split(" | ")
    cells[3] = ""
    mutated = doc_text.replace(first, "| " + " | ".join(cells) + " |", 1)
    assert incomplete_rows(mutated) != []
    assert incomplete_rows(doc_text) == []


def test_toggle_status_vocabulary_is_enforced(doc_text: str) -> None:
    first = next(line for line in doc_text.splitlines() if re.match(r"\|\s*C\d", line))
    cells = first.strip().strip("|").split(" | ")
    cells[4] = "PROVEN"
    assert bad_status_rows(doc_text.replace(first, "| " + " | ".join(cells) + " |", 1)) != []


def test_toggle_missing_limits_heading_is_detected(doc_text: str) -> None:
    assert not has_limits_section(doc_text.replace("## 6. Limits (what this does not establish)", "## 6. Notes"))
