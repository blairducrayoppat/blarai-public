"""Tests for the guest-certified oracle executor (shared/fleet/guest_oracle.py, #744).

Locks: the snapshot builder's collection scope + caps, the plan-bytes-win
oracle overlay, the offline dependency scan (deps-unavailable fail-closed —
design constraint 5), the host pipeline's structural transport dormancy, the
advisory certificate block (divergence flagged, never a verdict), and the
guest-side extract+execute half (zip-slip/zip-bomb guards; one real
``python -m pytest`` run each way).
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest

from shared.fleet import guest_oracle as go

ORACLE_PATH = "tests/test_job_acceptance.py"

_PASSING_ORACLE = (
    "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"
)
_FAILING_ORACLE = (
    "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 99\n"
)


def _repo(tmp_path, *, calc_body: str = "def add(a, b):\n    return a + b\n"):
    (tmp_path / "calc.py").write_text(calc_body, encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_job_acceptance.py").write_text(
        "def test_placeholder():\n    pass\n", encoding="utf-8")
    return tmp_path


# ---- snapshot builder --------------------------------------------------------


def test_snapshot_collects_only_python_source_sorted(tmp_path):
    repo = _repo(tmp_path)
    (repo / "README.md").write_text("nope", encoding="utf-8")
    (repo / "data.json").write_text("{}", encoding="utf-8")
    files = go.build_source_snapshot(repo)
    assert [p for p, _ in files] == ["calc.py", "tests/test_job_acceptance.py"]


def test_snapshot_excludes_hygiene_and_hidden_dirs(tmp_path):
    repo = _repo(tmp_path)
    for d in (".git", "__pycache__", ".venv", "node_modules", ".worktrees"):
        (repo / d).mkdir()
        (repo / d / "x.py").write_text("import requests\n", encoding="utf-8")
    (repo / ".hidden.py").write_text("import requests\n", encoding="utf-8")
    files = go.build_source_snapshot(repo)
    assert [p for p, _ in files] == ["calc.py", "tests/test_job_acceptance.py"]


def test_snapshot_per_file_cap_fail_closed(tmp_path):
    repo = _repo(tmp_path)
    (repo / "big.py").write_bytes(b"#" * (go.SNAPSHOT_MAX_FILE_BYTES + 1))
    with pytest.raises(go.GuestOracleError, match="per-file cap"):
        go.build_source_snapshot(repo)


def test_snapshot_total_cap_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(go, "SNAPSHOT_MAX_TOTAL_BYTES", 10)
    with pytest.raises(go.GuestOracleError, match="total bytes"):
        go.build_source_snapshot(_repo(tmp_path))


def test_snapshot_file_count_cap_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(go, "SNAPSHOT_MAX_FILES", 1)
    with pytest.raises(go.GuestOracleError, match="files"):
        go.build_source_snapshot(_repo(tmp_path))


def test_snapshot_missing_repo_fail_closed(tmp_path):
    with pytest.raises(go.GuestOracleError, match="not a directory"):
        go.build_source_snapshot(tmp_path / "nope")


# ---- oracle overlay (plan bytes always win) ----------------------------------


def test_overlay_replaces_merged_oracle_bytes():
    files = [("calc.py", b"x = 1\n"), (ORACLE_PATH, b"# coder-edited oracle\n")]
    out = go.overlay_oracle(files, ORACLE_PATH, _PASSING_ORACLE)
    assert dict(out)[ORACLE_PATH] == _PASSING_ORACLE.encode("utf-8")
    assert [p for p, _ in out] == sorted(p for p, _ in out)


def test_overlay_appends_when_oracle_absent():
    out = go.overlay_oracle([("calc.py", b"x = 1\n")], ORACLE_PATH, _PASSING_ORACLE)
    assert dict(out)[ORACLE_PATH] == _PASSING_ORACLE.encode("utf-8")


# ---- offline dependency scan ---------------------------------------------------


def test_dep_scan_allows_stdlib_pytest_hypothesis_and_local_modules():
    files = [
        ("calc.py", b"import json\nimport os.path\nfrom pathlib import Path\n"),
        ("pkg/__init__.py", b""),
        ("pkg/mod.py", b"from . import sibling\n"),
        ("main.py", b"import calc\nimport pkg\n"),
        (
            ORACLE_PATH,
            b"import pytest\n"
            b"from hypothesis import given, strategies as st\n"
            b"from calc import x\n",
        ),
    ]
    assert go.scan_snapshot_deps(files) == []


def test_dep_scan_flags_non_stdlib_imports():
    files = [("calc.py", b"import requests\nfrom numpy import array\n")]
    assert go.scan_snapshot_deps(files) == ["numpy", "requests"]


def test_dep_scan_unparseable_source_fail_closed():
    with pytest.raises(go.GuestOracleError, match="source-unparseable"):
        go.scan_snapshot_deps([("bad.py", b"def broken(:\n")])


# ---- deterministic zip ---------------------------------------------------------


def test_zip_snapshot_deterministic_and_round_trips():
    files = [("b.py", b"y = 2\n"), ("a.py", b"x = 1\n")]
    z1, z2 = go.zip_snapshot(files), go.zip_snapshot(list(reversed(files)))
    assert z1 == z2                       # order- and time-independent bytes
    with zipfile.ZipFile(io.BytesIO(z1)) as zf:
        assert zf.namelist() == ["a.py", "b.py"]
        assert zf.read("a.py") == b"x = 1\n"


# ---- host pipeline (run_guest_oracle) -------------------------------------------


def test_pipeline_transport_unregistered_is_structural_dormancy(tmp_path):
    # THE dormancy lock at the executor layer: a fully valid, shippable snapshot
    # still reports an honest not-run because NO transport exists in this build.
    res = go.run_guest_oracle(str(_repo(tmp_path)), ORACLE_PATH, _PASSING_ORACLE)
    assert res["status"] == "not-run"
    assert res["reason"] == go.REASON_TRANSPORT_UNREGISTERED


def test_pipeline_no_oracle_code_not_run(tmp_path):
    res = go.run_guest_oracle(str(_repo(tmp_path)), ORACLE_PATH, "")
    assert (res["status"], res["reason"]) == ("not-run", go.REASON_NO_ORACLE)


def test_pipeline_unpinned_path_refused(tmp_path):
    res = go.run_guest_oracle(str(_repo(tmp_path)), "tests/evil.py", _PASSING_ORACLE)
    assert (res["status"], res["reason"]) == ("not-run", go.REASON_REFUSED_PATH)


def test_pipeline_node_oracle_stays_host_side(tmp_path):
    res = go.run_guest_oracle(
        str(_repo(tmp_path)), "tests/acceptance.job.test.mjs", "test('x', () => {})")
    assert (res["status"], res["reason"]) == ("not-run", go.REASON_NON_PYTHON)


def test_pipeline_deps_unavailable_fail_closed_before_shipping(tmp_path):
    repo = _repo(tmp_path, calc_body="import requests\n\ndef add(a, b):\n    return a + b\n")
    calls = []
    res = go.run_guest_oracle(
        str(repo), ORACLE_PATH, _PASSING_ORACLE,
        transport=lambda z, p: calls.append(1) or {"status": "passed"})
    assert (res["status"], res["reason"]) == ("not-run", go.REASON_DEPS_UNAVAILABLE)
    assert "requests" in res["evidence"]
    assert calls == []                    # NOTHING shipped — decided host-side


def test_pipeline_snapshot_failure_not_run(tmp_path):
    res = go.run_guest_oracle(str(tmp_path / "missing"), ORACLE_PATH, _PASSING_ORACLE)
    assert (res["status"], res["reason"]) == ("not-run", go.REASON_SNAPSHOT_FAILED)


def test_pipeline_ships_overlaid_snapshot_and_returns_guest_outcome(tmp_path):
    repo = _repo(tmp_path)
    # Poison the on-disk oracle: the PLAN bytes must be what ships.
    (repo / "tests" / "test_job_acceptance.py").write_text(
        "def test_rigged():\n    assert True\n", encoding="utf-8")
    seen = {}

    def transport(snapshot_zip: bytes, oracle_path: str) -> dict:
        seen["path"] = oracle_path
        with zipfile.ZipFile(io.BytesIO(snapshot_zip)) as zf:
            seen["oracle"] = zf.read(ORACLE_PATH).decode("utf-8")
            seen["names"] = zf.namelist()
        return {"status": "failed", "evidence": "1 failed"}

    res = go.run_guest_oracle(str(repo), ORACLE_PATH, _FAILING_ORACLE, transport=transport)
    assert res == {"status": "failed", "reason": "", "evidence": "1 failed"}
    assert seen["path"] == ORACLE_PATH
    assert seen["oracle"] == _FAILING_ORACLE          # plan bytes won
    assert "calc.py" in seen["names"]


def test_pipeline_transport_raise_is_not_run_never_a_raise(tmp_path):
    def transport(_z, _p):
        raise RuntimeError("vsock died")

    res = go.run_guest_oracle(str(_repo(tmp_path)), ORACLE_PATH, _PASSING_ORACLE,
                              transport=transport)
    assert (res["status"], res["reason"]) == ("not-run", go.REASON_GUEST_ERROR)


@pytest.mark.parametrize("bad", [None, "passed", {"status": "certified"}, {"no": "status"}])
def test_pipeline_malformed_guest_response_never_a_silent_pass(tmp_path, bad):
    res = go.run_guest_oracle(str(_repo(tmp_path)), ORACLE_PATH, _PASSING_ORACLE,
                              transport=lambda _z, _p: bad)
    assert res["status"] == "not-run"
    assert res["reason"] == go.REASON_GUEST_ERROR


# ---- the advisory certificate block ----------------------------------------------


def test_certificate_block_flags_host_pass_guest_fail_divergence():
    block = go.certificate_block({"status": "failed", "evidence": "1 failed"},
                                 host_status="passed")
    assert block["divergence"] is True
    assert block["advisory"] is True
    assert block["status"] == "failed" and block["host_status"] == "passed"
    assert "DIVERGENCE" in block["evidence"]


@pytest.mark.parametrize("host,guest,expect", [
    ("passed", "passed", False),
    ("failed", "failed", False),
    ("failed", "passed", False),          # guest-pass over host-fail is NOT flagged
    ("passed", "not-run", False),
])
def test_certificate_block_no_false_divergence(host, guest, expect):
    block = go.certificate_block({"status": guest, "reason": "r" if guest == "not-run" else ""},
                                 host_status=host)
    assert block["divergence"] is expect


def test_certificate_block_coerces_unknown_status_fail_closed():
    block = go.certificate_block({"status": "certified"}, host_status="passed")
    assert block["status"] == "not-run" and block["divergence"] is False


# ---- guest side: safe extraction ---------------------------------------------------


def _zip_of(members: list[tuple[str, bytes]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members:
            zf.writestr(name, data)
    return buf.getvalue()


def test_safe_extract_round_trip(tmp_path):
    z = go.zip_snapshot([("calc.py", b"x = 1\n"), (ORACLE_PATH, b"def test_a(): pass\n")])
    extracted = go.safe_extract_snapshot(z, tmp_path)
    assert extracted == ["calc.py", ORACLE_PATH]
    assert (tmp_path / "calc.py").read_bytes() == b"x = 1\n"


@pytest.mark.parametrize("hostile_name", [
    "../escape.py",
    "a/../../escape.py",
    "/abs.py",
    "C:/win.py",
    "a\\b.py",       # survives the stdlib reader on the Linux guest (os.sep == '/')
    ".hidden/x.py",
    "__pycache__/x.py",
    "notes.txt",
])
def test_member_name_validation_refuses_hostile_names(hostile_name):
    # The SAME validator safe_extract_snapshot runs per member — unit-tested
    # directly so the matrix is OS-independent (on Windows the stdlib READER
    # normalizes '\\' to '/' before this check can see it; on the Alpine guest
    # it does not).
    with pytest.raises(go.GuestOracleError, match="refused member name"):
        go._validate_member_name(hostile_name)


@pytest.mark.parametrize("hostile_name", [
    "../escape.py",
    "a/../../escape.py",
    "/abs.py",
    "C:/win.py",
    ".hidden/x.py",
    "__pycache__/x.py",
    "notes.txt",
])
def test_safe_extract_refuses_hostile_member_names_end_to_end(tmp_path, hostile_name):
    # End-to-end through a real zip for every hostile shape the stdlib writer can
    # produce (the backslash case is covered by the validator unit test above).
    z = _zip_of([(hostile_name, b"boom")])
    with pytest.raises(go.GuestOracleError, match="refused member name"):
        go.safe_extract_snapshot(z, tmp_path)


def test_safe_extract_refuses_declared_oversize_member(tmp_path, monkeypatch):
    monkeypatch.setattr(go, "SNAPSHOT_MAX_FILE_BYTES", 4)
    z = _zip_of([("big.py", b"12345678")])
    with pytest.raises(go.GuestOracleError, match="per-file cap"):
        go.safe_extract_snapshot(z, tmp_path)


def test_safe_extract_refuses_total_bomb(tmp_path, monkeypatch):
    monkeypatch.setattr(go, "SNAPSHOT_MAX_TOTAL_BYTES", 8)
    z = _zip_of([("a.py", b"12345"), ("b.py", b"12345")])
    with pytest.raises(go.GuestOracleError, match="total-byte cap"):
        go.safe_extract_snapshot(z, tmp_path)


def test_safe_extract_refuses_garbage_zip(tmp_path):
    with pytest.raises(go.GuestOracleError, match="not a valid zip"):
        go.safe_extract_snapshot(b"not a zip at all", tmp_path)


# ---- guest side: execution ------------------------------------------------------


def _snapshot_zip(oracle_body: str) -> bytes:
    files = [("calc.py", b"def add(a, b):\n    return a + b\n")]
    files = go.overlay_oracle(files, ORACLE_PATH, oracle_body)
    return go.zip_snapshot(files)


def test_execute_snapshot_injected_runner_passed_and_failed():
    calls = []

    def fake_run(cmd, timeout_s, cwd):
        calls.append((cmd, cwd))
        return (True, "2 passed", "")

    res = go.execute_snapshot(_snapshot_zip(_PASSING_ORACLE), ORACLE_PATH, run=fake_run)
    assert res["status"] == "passed" and "exit 0" in res["evidence"]
    cmd, _cwd = calls[0]
    assert cmd[1:] == ["-m", "pytest", "-q", ORACLE_PATH]  # -m pytest, never bare pytest

    res = go.execute_snapshot(_snapshot_zip(_FAILING_ORACLE), ORACLE_PATH,
                              run=lambda c, t, w: (False, "1 failed", ""))
    assert res["status"] == "failed"


def test_execute_snapshot_refuses_unpinned_path():
    res = go.execute_snapshot(_snapshot_zip(_PASSING_ORACLE), "tests/evil.py",
                              run=lambda c, t, w: (True, "", ""))
    assert (res["status"], res["reason"]) == ("not-run", go.REASON_REFUSED_PATH)


def test_execute_snapshot_missing_oracle_not_run():
    z = go.zip_snapshot([("calc.py", b"x = 1\n")])
    res = go.execute_snapshot(z, ORACLE_PATH, run=lambda c, t, w: (True, "", ""))
    assert (res["status"], res["reason"]) == ("not-run", go.REASON_NO_ORACLE)


def test_execute_snapshot_bad_zip_not_run_never_a_raise():
    res = go.execute_snapshot(b"garbage", ORACLE_PATH, run=lambda c, t, w: (True, "", ""))
    assert (res["status"], res["reason"]) == ("not-run", go.REASON_SNAPSHOT_FAILED)


def test_execute_snapshot_runner_exception_not_run():
    def exploding_run(_c, _t, _w):
        raise OSError("no python")

    res = go.execute_snapshot(_snapshot_zip(_PASSING_ORACLE), ORACLE_PATH, run=exploding_run)
    assert (res["status"], res["reason"]) == ("not-run", go.REASON_GUEST_ERROR)


def test_execute_snapshot_real_pytest_passes_and_fails():
    # The REAL guest-side half end-to-end on the host: extract + `python -m pytest`
    # (pure stdlib + pytest — exactly what the provisioned guest will run).
    res = go.execute_snapshot(_snapshot_zip(_PASSING_ORACLE), ORACLE_PATH)
    assert res["status"] == "passed", res
    res = go.execute_snapshot(_snapshot_zip(_FAILING_ORACLE), ORACLE_PATH)
    assert res["status"] == "failed", res


def test_build_result_json_closed_shape():
    doc = json.loads(go.build_result_json({"status": "failed", "evidence": "1 failed"}))
    assert doc == {"status": "failed", "reason": "", "evidence": "1 failed"}
