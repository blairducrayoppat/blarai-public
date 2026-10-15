"""Gate lock for the account-level containment evidence bundle (2026-10-05).

WHAT FAILURE THIS EXISTS FOR
----------------------------
The bundle publishes raw spike data and scripts from the operator's machine. These must stay true:
(a) no operator user name or machine name appears in any bundle file, and no machine SID domain other than the placeholder and
fabricated domains in ALLOWED_DOMAINS, in any file, with no per-file exemption (the whole tracked tree is held to the same bar by
tests/security/test_no_machine_sid_domain_in_tree.py); (b) model text in the raw
results is cut to 100 characters; (c) CHANGES.md and the as-run MANIFEST are exactly what make_changes.py generates from the bundle, and the as-run script
hashes match the recorded manifest (the results come from those versions; the hardened set is labelled as later);
(d) every file the evidence document cites exists; (e) every claim row states all seven columns with a status from the
defined vocabulary; (f) the document keeps its limits section; (g) the bundled scripts listed in this file's self-test tables still pass their own -SelfTest under
PowerShell 7 and Windows PowerShell 5.1 (the NEP-0005 scripts are not in those tables: their self-tests need the admin-only live folder); (h) no control character (other than newline and tab) in any document; (i) all of the above hold on a copy
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
ALLOWED_DOMAINS = set(PH_DOMAINS) | {"1111111111-2222222222-3333333333", "1-2-3", "9-9-9", "17630000-17630001-17630002"}  # 9-9-9 and the last: fabricated SIDs of the NEP-0005 matrix self-tests (the last never resolves)
SID_RE = re.compile(r"S-1-5-21-(\d+-\d+-\d+)")
COLUMNS = 7
STATUS_RE = re.compile(r"OBSERVED|STATIC|NOT ESTABLISHED|CONTRADICTED")
PATH_RE = re.compile(r"`((?:docs|tests|scripts|services|shared)/[^`\s]+?)`")
CUT = 100
MARKER = "...[truncated to 100 chars]"
META = {"README.md", "CHANGES.md", "make_changes.py"}  # authored here (top level), not copies
AS_RUN = "confined-model-spike/as-run"
# The NEP-0005 code files (#1763) carry the test account's SID as a recorded constant on the placeholder domain, the same domain the run
# data was sanitised to; the hashes of the reviewed bytes and of the rewritten bytes are both recorded in nep0005-open-questions/runs/AS_RUN.md.
# The scan has no per-file exemption: any SID not on an allowed domain fails, in every file.
_SPIKE = "S-1-5-21-1000000001-1000000002-1000000003-1271"
_MOCK = "S-1-5-21-1000000001-1000000002-1000000003-1272"
# The whole token, case-insensitive, every sub-authority: a SID with extra parts appended, or an allowed domain followed by more numbers,
# is read as one token and fails unless it is exactly an allowed shape.
FULL_SID_RE = re.compile(r"S-1-5-21(?:-\d+)+", re.IGNORECASE)


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
        for m in FULL_SID_RE.finditer(text):
            token = m.group(0)
            subs = token.split("-")[4:]
            if len(subs) < 3:  # fewer than three numbers name no machine domain (prose like "S-1-5-21-...")
                continue
            if len(subs) in (3, 4) and "-".join(subs[:3]) in ALLOWED_DOMAINS and token.startswith("S-"):
                continue
            bad.append(f"{f.relative_to(root).as_posix()}: {token}")
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


def test_sid_scan_has_no_per_file_exemption(tmp_path: Path) -> None:
    """The same bar in every file: a SID on the placeholder domain passes anywhere (code constants, run data, prose), and a SID on any other
    machine-shaped domain is caught anywhere, including inside the NEP-0005 code files that once held a real one. The scan is byte-level
    on the whole token: an appended relative id, a lower-cased token, and a real-looking domain glued onto a fabricated prefix all fail."""
    assert "sid_allowed_here" not in globals() and "SID_SCAN_EXEMPT" not in globals()
    foreign = "S-1-5-21-111-222-333-1271"
    real_looking = "S-1-5-21-4000000001-2000000002-3000000003-1001"
    cases = (
        ("nep0005-open-questions/scripts/spike-nep5-lib.ps1", _SPIKE, False),
        ("nep0005-open-questions/harness/halfset.rs", _MOCK, False),
        ("nep0005-open-questions/scripts/spike-nep5-lib.ps1", real_looking, True),
        ("nep0005-open-questions/harness/halfset.rs", foreign, True),
        ("nep0005-open-questions/harness/tests/refusals.ps1", real_looking, True),
        ("nep0005-open-questions/scripts/spike-nep5-connect-probe.ps1", real_looking, True),
        ("nep0005-open-questions/SPEC.md", _SPIKE, False),
        ("nep0005-open-questions/runs/x.json", real_looking, True),
        ("x.md", _SPIKE, False),
        ("x.md", real_looking, True),
        ("x.md", real_looking.lower(), True),
        ("x.md", "S-1-5-21-9-9-9-" + real_looking.split("-", 4)[4].rsplit("-", 1)[0] + "-1001", True),
        ("x.md", _SPIKE + "-1001", True),
        ("x.md", "S-1-5-21-1-2-3-1001", False),
        ("x.md", "S-1-5-21-1000000004...", False),
    )
    for rel, sid, caught in cases:
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(f"x {sid} y", encoding="utf-8")
        assert (foreign_sid_domains(tmp_path) != []) is caught, (rel, sid)
        f.unlink()


def test_the_real_bundle_tree_passes_the_sid_scan() -> None:
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
    # arm 2 (the long hold): the three changed scripts and the two new tools.
    ("arm2-hold/scripts/spike-wfp.ps1", True),
    ("arm2-hold/scripts/spike-run-test.ps1", False),
    ("arm2-hold/scripts/Start-ElevatedOnce.ps1", False),
    ("arm2-hold/scripts/Convert-ToLive.ps1", False),
    # arm 3 (persistence): every script that can add, remove or gate. Their self-tests use an in-memory fake engine and call no WFP API.
    ("arm3-persist/scripts/spike-wfp-persist.ps1", True),
    ("arm3-persist/scripts/spike-arm3b-arm.ps1", True),
    ("arm3-persist/scripts/spike-arm3b-post-reboot.ps1", True),
    ("arm3-persist/scripts/spike-arm3b-veto.ps1", True),
    ("arm3-persist/scripts/Start-ElevatedOnce.ps1", False),
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


# ---- arms 2 and 3: structure the self-tests cannot see (what is in the proof's code set, what may add, what shutdown may say) ----
ARM2_SCRIPTS = BUNDLE / "arm2-hold" / "scripts"
ARM3_SCRIPTS = BUNDLE / "arm3-persist" / "scripts"


def lf_bytes(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n")


def code_set_names(lib_text: str) -> list[str]:
    """The names listed in `$script:CodeSetFiles = @(...)` of spike-persist-lib.ps1: the files the rollback proof binds."""
    m = re.search(r"\$script:CodeSetFiles\s*=\s*@\((.*?)\)", lib_text, re.DOTALL)
    return re.findall(r"'([^']+)'", m.group(1)) if m else []


def code_set_problems(scripts_dir: Path) -> list[str]:
    """Every .ps1 in the arm 3 scripts folder must be in the code set (an unbound script could add or remove without the proof noticing
    an edit), and every name in the code set must exist."""
    names = code_set_names((scripts_dir / "spike-persist-lib.ps1").read_text(encoding="utf-8"))
    on_disk = sorted(p.name for p in scripts_dir.glob("*.ps1"))
    bad = [f"{n}: listed in CodeSetFiles but missing" for n in names if n not in on_disk]
    bad += [f"{n}: a script in the folder that the rollback proof does not bind" for n in on_disk if n not in names]
    return bad


def live_part(script_text: str) -> str:
    """The text before `function Invoke-SelfTest`: the code that runs for real."""
    return script_text.split("function Invoke-SelfTest", 1)[0]


def add_calls_in_live_code(scripts_dir: Path) -> list[str]:
    """`.AddAll(` is the backend's add. Outside the library's Add-FenceSet (and the backends' own definitions) no live code may call it."""
    bad = []
    for p in sorted(scripts_dir.glob("*.ps1")):
        text = live_part(p.read_text(encoding="utf-8")) if p.name != "spike-persist-lib.ps1" else ""
        if ".AddAll(" in text:
            bad.append(p.name)
    lib = (scripts_dir / "spike-persist-lib.ps1").read_text(encoding="utf-8")
    span = re.search(r"function Add-FenceSet \{.*?\n\}\n", lib, re.DOTALL)
    for m in re.finditer(r"\.AddAll\(", lib):
        line = lib[lib.rfind("\n", 0, m.start()) + 1 : lib.find("\n", m.start())]
        in_fn = span is not None and span.start() <= m.start() <= span.end()
        if not in_fn and "-Name AddAll" not in line:
            bad.append("spike-persist-lib.ps1: AddAll( called outside Add-FenceSet")
    return bad


def test_arm3_scripts_are_byte_identical_copies_where_they_claim_to_be() -> None:
    for name in ("spike-lib.ps1", "Start-ElevatedOnce.ps1"):
        assert lf_bytes(ARM2_SCRIPTS / name) == lf_bytes(ARM3_SCRIPTS / name), name


def test_the_rollback_proof_binds_every_script_in_the_arm3_folder() -> None:
    assert code_set_problems(ARM3_SCRIPTS) == []
    assert len(code_set_names((ARM3_SCRIPTS / "spike-persist-lib.ps1").read_text(encoding="utf-8"))) >= 10


def test_the_only_add_path_is_add_fenceset_and_there_is_no_standalone_add_mode() -> None:
    assert add_calls_in_live_code(ARM3_SCRIPTS) == []
    persist = (ARM3_SCRIPTS / "spike-wfp-persist.ps1").read_text(encoding="utf-8")
    params = persist.split("param(", 1)[1].split(")\n$ErrorActionPreference", 1)[0]
    assert "[switch]$Add" not in params and "$Add," not in params
    callers = [p.name for p in sorted(ARM3_SCRIPTS.glob("*.ps1")) if "Add-FenceSet -Backend" in live_part(p.read_text(encoding="utf-8")) and p.name != "spike-persist-lib.ps1"]
    assert callers == ["spike-arm3b-arm.ps1", "spike-wfp-persist.ps1"]


def forced_restart_claims(root: Path) -> list[str]:
    """Documentation claims that leaving /f out makes the restart gentle. `shutdown /r /t N` with N above 0 IMPLIES /f (shutdown /? on
    Windows 11 says so), so such a claim is false; each file must instead say the restart is forced."""
    bad: list[str] = []
    claims = (r"WITHOUT\s+`?/f", r"\(no /f\)", r"never contain\s+/f", r"no /f, ever", r"without /f")
    for rel in ("arm3-persist/DESIGN.md", "arm3-persist/scripts/README.md", "arm3-persist/scripts/spike-arm3b-arm.ps1", "arm3-persist/scripts/arm3-idle-gate.ps1"):
        text = (root / rel).read_text(encoding="utf-8")
        for c in claims:
            if re.search(c, text, re.IGNORECASE):
                bad.append(f"{rel}: claims the restart is not forced ({c})")
    return bad


def forced_restart_disclosures_missing(root: Path) -> list[str]:
    miss: list[str] = []
    for rel in ("arm3-persist/DESIGN.md", "arm3-persist/scripts/README.md", "arm3-persist/scripts/arm3-idle-gate.ps1", "ARMS_HANDOFF.md"):
        text = (root / rel).read_text(encoding="utf-8")
        if not (re.search(r"implies?\s+`?/f", text) or re.search(r"implied", text) or re.search(r"FORCED", text)):
            miss.append(rel)
    return miss


def test_the_shutdown_arguments_are_exactly_the_documented_ones_and_the_docs_say_the_restart_is_forced() -> None:
    gate = (ARM3_SCRIPTS / "arm3-idle-gate.ps1").read_text(encoding="utf-8")
    fn = re.search(r"function Get-ShutdownArgs \{.*?\n\}\n", gate, re.DOTALL)
    ret = re.search(r"return @\(.*\)", fn.group(0)) if fn else None  # the argument list itself, not the comment above it
    assert ret and ret.group(0) == "return @('/r', '/t', \"$DelaySeconds\", '/c', $Comment)"
    arm = (ARM3_SCRIPTS / "spike-arm3b-arm.ps1").read_text(encoding="utf-8")
    live = live_part(arm)
    assert "'/f'" not in live and re.search(r"shutdown(\.exe)?\"?\s+/f\b", live) is None
    assert "$Idle -lt 30" in arm and "$Countdown -lt 10" in arm and "$Delay -lt 600" in arm
    # The true property: a timeout above 0 implies /f, so the restart IS forced. No file may claim otherwise, and each must disclose it.
    assert forced_restart_claims(BUNDLE) == []
    assert forced_restart_disclosures_missing(BUNDLE) == []


def test_toggle_the_forced_restart_claim_check_fails_on_the_false_sentence(tmp_path: Path) -> None:
    for rel in ("arm3-persist/DESIGN.md", "arm3-persist/scripts/README.md", "arm3-persist/scripts/spike-arm3b-arm.ps1", "arm3-persist/scripts/arm3-idle-gate.ps1", "ARMS_HANDOFF.md"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("a timeout above 0 implies /f: the restart is FORCED\n", encoding="utf-8")
    assert forced_restart_claims(tmp_path) == [] and forced_restart_disclosures_missing(tmp_path) == []
    (tmp_path / "arm3-persist/DESIGN.md").write_text("runs shutdown /r /t 600 WITHOUT `/f`\n", encoding="utf-8")
    assert forced_restart_claims(tmp_path) != [] and forced_restart_disclosures_missing(tmp_path) != []


def test_the_admin_only_folder_check_is_the_same_text_in_the_wrapper_and_the_library() -> None:
    lib = (ARM3_SCRIPTS / "spike-persist-lib.ps1").read_text(encoding="utf-8")
    wrap = (ARM2_SCRIPTS / "Start-ElevatedOnce.ps1").read_text(encoding="utf-8")
    for name in ("Get-NonAdminWriteGrants", "ConvertTo-AclRuleRows", "Get-PathSecurityObject", "Get-PathAttributes", "Test-AdminOnlyFolder", "Test-RestartDecision"):
        a = re.search(rf"function {name} \{{.*?\n\}}\n", lib, re.DOTALL)
        b = re.search(rf"function {name} \{{.*?\n\}}\n", wrap, re.DOTALL)
        assert a and b and a.group(0) == b.group(0), name


def test_every_system_or_elevated_registration_is_behind_the_admin_only_check() -> None:
    wrap = (ARM2_SCRIPTS / "Start-ElevatedOnce.ps1").read_text(encoding="utf-8")
    assert wrap.index("Test-AdminOnlyFolder -Path $PSScriptRoot", wrap.index("# ---- register + start")) < wrap.index("Register-ScheduledTask -TaskName $Name")
    persist = (ARM3_SCRIPTS / "spike-wfp-persist.ps1").read_text(encoding="utf-8")
    assert persist.index("Test-AdminOnlyFolder -Path $PSScriptRoot") < persist.index("Register-DeadManTask -Def $def")
    arm = (ARM3_SCRIPTS / "spike-arm3b-arm.ps1").read_text(encoding="utf-8")
    assert arm.index("& $W.AdminOnly") < arm.index("& $W.RegisterTask $defs.Post")


def test_the_persistent_objects_use_fixed_keys_and_the_persistent_flag() -> None:
    lib = (ARM3_SCRIPTS / "spike-persist-lib.ps1").read_text(encoding="utf-8")
    assert lib.count("Guid.NewGuid") == 0 and "[guid]::NewGuid" not in lib
    assert "public const uint Persistent = 1;" in lib and lib.count("flags = PersistKeys.Persistent") >= 3
    assert "s.flags = 0;" in lib  # a NON-dynamic session
    assert "FWPM_SESSION_FLAG_DYNAMIC" not in lib


def test_arm2_probe_mode_is_in_the_schema_and_the_task_script() -> None:
    lib = (ARM2_SCRIPTS / "spike-lib.ps1").read_text(encoding="utf-8")
    run = (ARM2_SCRIPTS / "spike-run-test.ps1").read_text(encoding="utf-8")
    assert "'probe'" in lib and "StepNamesProbe" in lib
    assert "'feasibility', 'serve', 'client', 'probe'" in run


def test_no_arm2_or_arm3_script_names_a_function_like_a_powershell_alias() -> None:
    """An earlier probe named `Rd` deleted a tracked file: a function named like an alias shadows or is shadowed by the alias."""
    aliases = {"rd", "ls", "cat", "rm", "cp", "mv", "del", "dir", "type", "sort", "sc", "gc", "gci", "gi", "gl", "gm", "gp", "gu", "ps", "kill", "cd", "cls", "copy", "echo", "erase", "move", "rmdir", "sleep", "start", "tee", "write", "where", "select", "sl", "sv", "si", "ni", "ri", "rni", "rvpa", "mi", "mp", "pwd", "r", "h", "history", "man", "more", "oh", "md", "mkdir", "ac", "clc", "clp", "cli", "cnsn", "cpi", "diff", "ft", "fl", "fw", "iex", "ii", "ipmo", "nv", "rv", "sal", "saps", "sasv", "shcm", "spps", "spsv", "sp", "wget", "curl"}
    bad = []
    for d in (ARM2_SCRIPTS, ARM3_SCRIPTS):
        for p in sorted(d.glob("*.ps1")):
            for name in re.findall(r"^\s*function\s+([A-Za-z0-9_-]+)\s*[({]", p.read_text(encoding="utf-8"), re.MULTILINE):
                if name.lower() in aliases:
                    bad.append(f"{p.name}: function {name}")
    assert bad == []


ENTRY_SCRIPTS = ["spike-wfp-persist.ps1", "spike-arm3b-arm.ps1", "spike-arm3b-post-reboot.ps1", "spike-arm3b-veto.ps1"]


def toctou_problems(scripts_dir: Path) -> list[str]:
    """Check-then-use gaps: a library or the wrapped script must be read ONCE (the bytes hashed are the bytes run), and elevated JSON writes go through the link guard."""
    bad: list[str] = []
    for name in ENTRY_SCRIPTS:
        text = (scripts_dir / name).read_text(encoding="utf-8")
        if re.search(r'^\. "\$PSScriptRoot\\', text, re.MULTILINE):
            bad.append(f"{name}: dot-sources a library by path (a second read of what the proof hashed)")
        if "Get-VerifiedLibBlock" not in text:
            bad.append(f"{name}: does not load its libraries through Get-VerifiedLibBlock")
        if "Write-JsonAtomic" in text:
            bad.append(f"{name}: writes JSON without the reparse-point guard (Write-JsonGuarded)")
    lib = (scripts_dir / "spike-persist-lib.ps1").read_text(encoding="utf-8")
    fn = re.search(r"function Import-WfpHelpers \{.*?\n\}\n", lib, re.DOTALL)
    if not fn or "ParseFile(" in fn.group(0) or fn.group(0).count("ReadAllBytes") != 1 or "Get-NormalizedSha256 -Path" in fn.group(0):
        bad.append("spike-persist-lib.ps1: Import-WfpHelpers must read the wrapped script once (ReadAllBytes) and hash and parse those bytes")
    if fn and not 0 <= fn.group(0).find("Test-AdminOnlyFolder") < fn.group(0).find("ReadAllBytes"):
        bad.append("spike-persist-lib.ps1: Import-WfpHelpers must run the pin-or-admin-only gate BEFORE it reads the wrapped script as code")
    for name in ENTRY_SCRIPTS:
        text = (scripts_dir / name).read_text(encoding="utf-8")
        if re.search(r"\[string\]\$WfpScript\s*=", text):
            bad.append(f"{name}: -WfpScript must not default to a fixed (user-writable) path")
        if "Join-Path $PSScriptRoot 'wfp-coder-egress-spike.ps1'" not in text:
            bad.append(f"{name}: -WfpScript must default to the copy beside the scripts")
    if "WrappedScript" in lib:
        bad.append("spike-persist-lib.ps1: the proof check must take the hash of the imported bytes (-WrappedSha256), not re-read the path")
    return bad


def test_libraries_and_the_wrapped_script_are_read_once_and_elevated_writes_are_guarded() -> None:
    assert toctou_problems(ARM3_SCRIPTS) == []
    helpers = []
    for name in ENTRY_SCRIPTS:
        text = (ARM3_SCRIPTS / name).read_text(encoding="utf-8")
        m = re.search(r"function Get-VerifiedLibBlock \{.*?\n\}\n", text, re.DOTALL)
        assert m, name
        helpers.append(m.group(0))
    assert len(set(helpers)) == 1  # the same loader in every entry script


def test_toggle_the_read_once_check_fails_on_a_second_read(tmp_path: Path) -> None:
    for name in ENTRY_SCRIPTS:
        (tmp_path / name).write_text("function Get-VerifiedLibBlock { }\n. (Get-VerifiedLibBlock 'x.ps1')\nWrite-JsonGuarded\nJoin-Path $PSScriptRoot 'wfp-coder-egress-spike.ps1'\n", encoding="utf-8")
    (tmp_path / "spike-persist-lib.ps1").write_text("function Import-WfpHelpers {\n    $ao = Test-AdminOnlyFolder\n    $b = [IO.File]::ReadAllBytes($Path)\n}\n", encoding="utf-8")
    assert toctou_problems(tmp_path) == []
    (tmp_path / "spike-persist-lib.ps1").write_text("function Import-WfpHelpers {\n    $h = Get-NormalizedSha256 -Path $Path\n    $ast = [X]::ParseFile($Path)\n    $b = [IO.File]::ReadAllBytes($Path)\n}\n", encoding="utf-8")
    assert toctou_problems(tmp_path) != []
    (tmp_path / "spike-persist-lib.ps1").write_text("function Import-WfpHelpers {\n    $ao = Test-AdminOnlyFolder\n    $b = [IO.File]::ReadAllBytes($Path)\n}\n", encoding="utf-8")
    (tmp_path / ENTRY_SCRIPTS[1]).write_text('. "$PSScriptRoot\\spike-lib.ps1"\nGet-VerifiedLibBlock\nWrite-JsonAtomic\n', encoding="utf-8")
    assert toctou_problems(tmp_path) != []


# ---- toggle tests: each check must FAIL when the property is broken (security_by_design 12) ----


def test_toggle_code_set_check_fails_on_an_unbound_script_and_on_a_missing_one(tmp_path: Path) -> None:
    (tmp_path / "spike-persist-lib.ps1").write_text("$script:CodeSetFiles = @('a.ps1', 'spike-persist-lib.ps1')\n", encoding="utf-8")
    (tmp_path / "a.ps1").write_text("x", encoding="utf-8")
    assert code_set_problems(tmp_path) == []
    (tmp_path / "extra.ps1").write_text("x", encoding="utf-8")
    assert code_set_problems(tmp_path) != []  # a script the proof does not bind
    (tmp_path / "extra.ps1").unlink()
    (tmp_path / "a.ps1").unlink()
    assert code_set_problems(tmp_path) != []  # a name that is listed but missing


def test_toggle_add_path_check_fails_when_live_code_calls_the_backend_add(tmp_path: Path) -> None:
    lib = "function Add-FenceSet {\n    $ids = @($Backend.AddAll($Plan))\n}\nfunction New-FakeBackend {\n    $be | Add-Member -MemberType ScriptMethod -Name AddAll -Value { }\n}\n"
    (tmp_path / "spike-persist-lib.ps1").write_text(lib, encoding="utf-8")
    (tmp_path / "live.ps1").write_text("function Go {\n    $b.AddAll($p)\n}\nfunction Invoke-SelfTest {\n    $fake.AddAll($p)\n}\n", encoding="utf-8")
    assert add_calls_in_live_code(tmp_path) == ["live.ps1"]
    (tmp_path / "live.ps1").write_text("function Go {\n    Add-FenceSet -Backend $b\n}\nfunction Invoke-SelfTest {\n    $fake.AddAll($p)\n}\n", encoding="utf-8")
    assert add_calls_in_live_code(tmp_path) == []




def test_toggle_leak_check_fails_on_a_planted_name(tmp_path: Path) -> None:
    (tmp_path / "x.txt").write_text("path C:\\Users\\" + FORBIDDEN[0].upper() + "\\x", encoding="utf-8")
    assert leaked_names(tmp_path) != []
    (tmp_path / "x.txt").write_text("path C:\\Users\\_OPERATOR_\\x", encoding="utf-8")
    assert leaked_names(tmp_path) == []


def test_toggle_sid_domain_check_fails_on_a_real_looking_domain(tmp_path: Path) -> None:
    (tmp_path / "x.txt").write_text("S-1-5-21-4000000001-2000000002-3000000003-1001", encoding="utf-8")
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


def test_the_3b_arming_script_needs_the_recorded_restart_decision_in_code_and_in_the_wrapper() -> None:
    arm = (ARM3_SCRIPTS / "spike-arm3b-arm.ps1").read_text(encoding="utf-8")
    assert arm.index("& $W.Decision") < arm.index("& $W.Proof") and "-not $dec.Ok" in arm
    wrap = (ARM2_SCRIPTS / "Start-ElevatedOnce.ps1").read_text(encoding="utf-8")
    assert "Test-RestartDecision -Folder $Folder" in wrap and "spike-arm3b-arm.ps1" in wrap
    assert "arm3b-restart-decision.json" in (ARM3_SCRIPTS / "README.md").read_text(encoding="utf-8")


def test_toggle_default_path_and_gate_order_checks_fail_on_the_old_shape(tmp_path: Path) -> None:
    import shutil
    d = tmp_path / "s"
    shutil.copytree(ARM3_SCRIPTS, d)
    f = d / "spike-wfp-persist.ps1"
    f.write_text(f.read_text(encoding="utf-8").replace("Join-Path $PSScriptRoot 'wfp-coder-egress-spike.ps1'", "'elsewhere.ps1'"), encoding="utf-8")
    assert any("beside the scripts" in x for x in toctou_problems(d))
