"""#1581: the operator can check the audit record without rotating a key.

Before this, the only code that walked a chain end to end was step 1 of the
rotation ceremony, so the only route to "is my record intact?" began by changing
a signing key.

THE TOGGLE FIRST. ``test_a_clean_chain_verifies`` leads this file deliberately.
A command that reported failure unconditionally would satisfy every tamper test
here and be worthless; the clean-chain pass is what makes the others mean
anything, and it is the assertion most likely to be quietly lost.

WHY THESE TESTS INJECT A KEY SOURCE. ``inspect_chain`` takes ``keys``, defaulting
to :class:`TpmKeys`. The chains below are HMAC-signed so they can be built on any
machine, and everything else -- discovery, the read-only open, the full
record-by-record walk, the classification, the exit codes -- is the production
path. ``test_the_default_key_source_is_the_TPM`` pins the default so the seam
cannot quietly become the shipped behaviour.

LIVE EVIDENCE, recorded because no test here can produce it: run against the real
TPM-signed chain on this machine (2026-09-20), the command reported the
``ingest_audit.jsonl`` chain VERIFIED, 33 records, 2026-06-11 to 2026-07-13, exit
0 -- and the file's mtime and byte size were identical afterwards, with
``services/policy_agent/data/`` still absent although the command had resolved
that path and found no chain there.
"""

from __future__ import annotations

import ast
import json
import warnings
from pathlib import Path

import pytest

from shared.security.audit_key_history import append_key, read_history
from shared.security.audit_log import (
    AuditLog,
    AuditProvisioningError,
    AuditSinkError,
    HmacSha256Signer,
    hmac_key_resolver,
)
from shared.security.verify_audit_chain import (
    ABSENT,
    ChainReport,
    EXIT_CANNOT_RUN,
    EXIT_FAILED,
    EXIT_NOT_CHECKED,
    EXIT_OK,
    KEY_MISMATCH,
    TAMPER,
    UNCHECKABLE,
    UNREADABLE,
    VERIFIED,
    ChainLocation,
    TpmKeys,
    exit_code_for,
    inspect_chain,
    known_chains,
    main,
    policy_agent_chain_path,
    render,
)

_A = HmacSha256Signer(key=b"A" * 32, key_id="keyA")
_B = HmacSha256Signer(key=b"B" * 32, key_id="keyB")
_KEYS = {s.signer_id(): s for s in (_A, _B)}

_COMMON = dict(
    source_agent="ao",
    destination_service="tools",
    verb="EXECUTE",
    sensitivity="INTERNAL",
    rule_engine_passed=True,
    confidence=1.0,
)


class _HmacKeys:
    """The HMAC twin of :class:`TpmKeys`, mirroring it including its refusal."""

    prefix = "HMAC-SHA256:"

    def __init__(self, keys: dict, default=None) -> None:
        self._keys = keys
        self._default = default if default is not None else _A

    def accepts(self, signer_id: str) -> bool:
        return signer_id.startswith(self.prefix)

    def current(self, path: Path):
        """Mirrors ``TpmKeys.current`` INCLUDING its refusal.

        Review finding 11: this used to return a default and never raise, so
        the ``except AuditProvisioningError`` arm around ``keys.current`` in
        ``inspect_chain`` was unreachable from any test. A double that cannot
        fail the way the real thing fails leaves the failure path unlocked.
        """
        history = read_history(path)
        if not history:
            return self._default
        newest = history[-1]
        if not newest.startswith(self.prefix) or not newest[len(self.prefix):]:
            raise AuditProvisioningError(
                f"the audit key history's newest entry {newest!r} does not name "
                "a key. Repair the history rather than deleting it."
            )
        return self._keys.get(newest, self._default)

    def start(self, path: Path):
        history = read_history(path)
        if len(history) < 2:
            return None, None, None
        resolver = hmac_key_resolver(self._keys)
        first = resolver(history[0])
        if first is None:
            raise AuditProvisioningError(
                f"the audit key history names {history[0]!r} as this chain's "
                "first signing key, and that key is not available on this TPM."
            )
        return first, resolver, history


def _chain(path: Path, signer=_A, count: int = 4) -> Path:
    log = AuditLog.from_path(path, signer)
    for i in range(count):
        log.append(
            adjudication_id=f"id{i}", decision="ALLOW", car_hash=f"h{i}",
            resource=f"r{i}", **_COMMON,
        )
    return path


def _at(path: Path, name: str = "ingest_audit.jsonl") -> ChainLocation:
    return ChainLocation(name=name, path=path, holds="test chain")


def _tracked_python_files() -> list[Path]:
    """Every .py file GIT knows about in this repo, and nothing else.

    NOT ``rglob``. The primary checkout holds other sessions' worktrees under
    ``.claude/worktrees/``, each a full copy of this repo -- so an ``rglob``
    from the repo root found a second ``audit_verification.py`` in a sibling
    checkout, and the "exactly one implementation" locks below FAILED on merged
    main while passing in every worktree. MEASURED: 3 failed / 11736 passed at
    46c44454. They were asserting about whatever directories happened to sit
    inside the folder, not about this repo.

    ``git ls-files`` is the authority on what is in the repo. It excludes
    untracked worktrees, ``.venv`` and ``__pycache__`` without an exclusion set
    that has to be kept correct as the tree changes -- and the set it replaced
    was already wrong.
    """
    import subprocess

    repo = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["git", "ls-files", "--", "*.py"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    files = [repo / line for line in result.stdout.splitlines() if line.strip()]
    assert len(files) > 500, (
        f"git ls-files returned only {len(files)} python files; every scan built "
        "on this would be vacuously true. Something is wrong with the checkout, "
        "not with the code under test."
    )
    return files


def _parsed(path: Path):
    """The file's syntax tree, or None when it will not parse."""
    try:
        with warnings.catch_warnings():
            # Scratch files elsewhere in the tree carry invalid escapes;
            # parsing them is not any caller's finding.
            warnings.simplefilter("ignore", DeprecationWarning)
            return ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return None


# ---------------------------------------------------------------------------
# The toggle. Everything below it is meaningless without this passing.
# ---------------------------------------------------------------------------


def test_a_clean_chain_verifies(tmp_path: Path) -> None:
    """THE TOGGLE. A command that always reported failure would pass every
    tamper test in this file."""
    path = _chain(tmp_path / "ingest_audit.jsonl")
    report = inspect_chain(_at(path), keys=_HmacKeys(_KEYS))

    assert report.status == VERIFIED, (
        f"a chain nobody touched was reported {report.status}: {report.detail}"
    )
    assert report.records == 4, (
        f"reported {report.records} records for a 4-record chain — a size the "
        "command cannot read must never be reported as a number."
    )
    assert report.first_utc and report.last_utc, "no period reported"


def test_a_tampered_record_is_reported_as_TAMPER(tmp_path: Path) -> None:
    path = _chain(tmp_path / "ingest_audit.jsonl")
    lines = path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[2])
    record["resource"] = "something-else"
    lines[2] = json.dumps(record)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = inspect_chain(_at(path), keys=_HmacKeys(_KEYS))
    assert report.status == TAMPER, f"altered bytes reported as {report.status}"
    assert "2" in report.detail, "the failing record is not named"
    assert report.remedy, "a TAMPER finding with no remedy is half a report"


def test_a_chain_that_spans_a_rotation_verifies(tmp_path: Path) -> None:
    """The case the fast path and a single verifier both get wrong."""
    path = tmp_path / "ingest_audit.jsonl"
    log = AuditLog.from_path(path, _A)
    for i in range(3):
        log.append(
            adjudication_id=f"pre{i}", decision="ALLOW", car_hash=f"h{i}",
            resource=f"r{i}", **_COMMON,
        )
    log.rotate_signing_key(_B)
    append_key(path, _A.signer_id())
    append_key(path, _B.signer_id())
    for i in range(2):
        log.append(
            adjudication_id=f"post{i}", decision="ALLOW", car_hash=f"p{i}",
            resource=f"q{i}", **_COMMON,
        )

    report = inspect_chain(_at(path), keys=_HmacKeys(_KEYS))
    assert report.status == VERIFIED, (
        f"a legitimately rotated chain reported {report.status}: {report.detail}"
    )


def test_a_rotated_chain_whose_oldest_key_is_gone_is_not_called_TAMPER(
    tmp_path: Path,
) -> None:
    """The #1578 alarm, one layer out — and the defect this ticket fixed.

    The Assistant Orchestrator's copy of the verification-start helper returned
    None for an unavailable oldest key. ``verify()`` reads None as "use the log's
    own signer", so the pre-rotation records were checked against the NEWEST key
    and the operator was told their record had been ALTERED when a key had merely
    been retired. The Policy Agent's copy guarded this; the Orchestrator's did
    not. There is now one implementation, and it refuses.
    """
    path = tmp_path / "ingest_audit.jsonl"
    log = AuditLog.from_path(path, _A)
    for i in range(3):
        log.append(
            adjudication_id=f"pre{i}", decision="ALLOW", car_hash=f"h{i}",
            resource=f"r{i}", **_COMMON,
        )
    log.rotate_signing_key(_B)
    append_key(path, _A.signer_id())
    append_key(path, _B.signer_id())

    # The oldest key is gone from this machine.
    without_a = {_B.signer_id(): _B}
    report = inspect_chain(_at(path), keys=_HmacKeys(without_a, default=_B))

    assert report.status != TAMPER, (
        "a retired key was reported as TAMPER — the operator is told their audit "
        "record was altered when nothing was altered. This is the exact false "
        "alarm #1569 and #1578 both exist to prevent."
    )
    assert report.status == UNCHECKABLE, (
        f"expected UNCHECKABLE for an unavailable key, got {report.status}"
    )
    assert "never be deleted" in report.remedy


def test_verification_start_itself_refuses_an_absent_oldest_key(
    tmp_path: Path,
) -> None:
    """The SHIPPED function, not the test double.

    MEASURED: the test above passes with the refusal mutated out of
    ``verification_start``, because ``_HmacKeys.start`` carries its own copy of
    it. A test double that reimplements the guard tests the double. This drives
    the real function, with a history naming TPM keys this chip does not hold --
    which is what the resolver returns None for.
    """
    from shared.security.audit_verification import verification_start

    path = tmp_path / "ingest_audit.jsonl"
    append_key(path, "ECDSA-P256-TPM:BlarAI-Absent-Key-For-Test-v1")
    append_key(path, "ECDSA-P256-TPM:BlarAI-Absent-Key-For-Test-v2")

    with pytest.raises(AuditProvisioningError, match="not available on this TPM"):
        verification_start(path)


def test_verification_start_is_silent_for_a_chain_that_never_rotated(
    tmp_path: Path,
) -> None:
    """The toggle: the refusal above must not be what the function always does.

    An unrotated chain must return ``(None, None, None)`` so verification
    behaves exactly as it did before rotation existed.
    """
    from shared.security.audit_verification import verification_start

    path = tmp_path / "ingest_audit.jsonl"
    assert verification_start(path) == (None, None, None)
    append_key(path, "ECDSA-P256-TPM:BlarAI-Audit-Signing-Key-v1")
    assert verification_start(path) == (None, None, None), (
        "a chain with ONE key in its history was treated as rotated"
    )


def test_a_chain_this_command_cannot_verify_is_not_called_clean(
    tmp_path: Path,
) -> None:
    """Deny-by-default: not-checked is its own outcome, never a pass."""
    path = _chain(tmp_path / "ingest_audit.jsonl")
    report = inspect_chain(_at(path), keys=TpmKeys())  # HMAC chain, TPM source

    assert report.status == UNCHECKABLE, (
        f"a chain the command cannot verify reported {report.status}"
    )
    assert report.status != VERIFIED
    # The REASON, not just the verdict. Removing the algorithm check entirely
    # still yields UNCHECKABLE — the TPM verifier fails on HMAC signatures and
    # lands in the generic handler — so a status-only assertion passes with the
    # check deleted. MEASURED. The operator is owed which of the two it was.
    assert "development key" in report.detail, (
        "the chain was refused, but not for the reason the operator needs: it "
        f"was refused generically. detail={report.detail!r}"
    )


# ---------------------------------------------------------------------------
# Read-only: the command must be usable ON A PRESERVED COPY, and must not
# invent the directory of a chain that does not exist.
# ---------------------------------------------------------------------------


def test_inspecting_an_absent_chain_creates_no_directory(tmp_path: Path) -> None:
    """A command that merely LOOKED for the Policy Agent's chain must not leave
    behind a directory implying one had been provisioned.

    WHAT ACTUALLY HOLDS THIS: the ``exists()`` check in ``inspect_chain``, which
    returns before any ``AuditLog`` is constructed. NOT ``read_only`` — that was
    measured. Removing the ``read_only`` mkdir guard leaves this test green,
    because an existing chain always has an existing parent, so the mkdir is a
    no-op on every path this command takes. ``read_only`` is held instead by
    ``test_read_only_construction_creates_no_directory`` and
    ``test_read_only_construction_does_not_harden_the_DACL``, which drive
    ``AuditLog`` directly.
    """
    missing = tmp_path / "never" / "written" / "adjudication_audit.jsonl"
    report = inspect_chain(_at(missing), keys=_HmacKeys(_KEYS))

    assert report.status == ABSENT
    assert not missing.parent.exists(), (
        "inspecting an absent chain created its directory — the operator now has "
        "a directory that says a chain was provisioned here."
    )


def test_read_only_construction_creates_no_directory(tmp_path: Path) -> None:
    """``AuditLog.__init__`` mkdirs by default; ``read_only`` must not."""
    missing = tmp_path / "never" / "written" / "audit.jsonl"

    AuditLog.from_path(missing, _A, read_only=True)
    assert not missing.parent.exists(), (
        "a read-only open created the chain's directory"
    )

    # The toggle: prove the default DOES create it, or the assertion above would
    # pass just as well against a class that had stopped creating directories.
    AuditLog.from_path(missing, _A)
    assert missing.parent.exists(), (
        "the default no longer creates the directory, so the read-only "
        "assertion above proves nothing"
    )


def test_read_only_construction_does_not_harden_the_DACL(tmp_path: Path) -> None:
    """The guard that IS load-bearing for this command.

    Hardening an existing file's ACL is a write, and it requires write
    permission — so the default mode cannot open a preserved forensic copy on
    read-only media, which is the one reader this mode exists for.
    """
    path = _chain(tmp_path / "ingest_audit.jsonl")

    read_only = AuditLog.from_path(path, _A, read_only=True)
    assert read_only._dacl_hardened is False, (
        "a read-only open hardened the file's ACL — it wrote to the chain it "
        "was asked only to read, and would fail outright on read-only media"
    )

    normal = AuditLog.from_path(path, _A)
    assert normal._dacl_hardened is True, (
        "the default no longer hardens an existing file, so the read-only "
        "assertion above proves nothing"
    )


def test_inspecting_changes_not_one_byte(tmp_path: Path) -> None:
    path = _chain(tmp_path / "ingest_audit.jsonl")
    before_bytes = path.read_bytes()
    before_mtime = path.stat().st_mtime_ns

    inspect_chain(_at(path), keys=_HmacKeys(_KEYS))

    assert path.read_bytes() == before_bytes, "inspection altered the chain"
    assert path.stat().st_mtime_ns == before_mtime, "inspection touched the file"


def test_a_read_only_log_refuses_to_append(tmp_path: Path) -> None:
    """The toggle for read-only: a handle that could still write would make the
    guarantee unenforceable."""
    path = _chain(tmp_path / "ingest_audit.jsonl")
    log = AuditLog.from_path(path, _A, read_only=True)

    with pytest.raises(AuditSinkError, match="read-only"):
        log.append(
            adjudication_id="x", decision="ALLOW", car_hash="h",
            resource="r", **_COMMON,
        )


def test_read_only_is_OFF_by_default(tmp_path: Path) -> None:
    """The other half of the toggle: prove the default still writes, or the test
    above would pass just as well on a class that never appends at all."""
    path = tmp_path / "ingest_audit.jsonl"
    log = AuditLog.from_path(path, _A)
    log.append(
        adjudication_id="x", decision="ALLOW", car_hash="h",
        resource="r", **_COMMON,
    )
    assert path.exists() and path.read_text(encoding="utf-8").strip()


# ---------------------------------------------------------------------------
# Discovery: the chain that ``discover_chains()`` does not find.
# ---------------------------------------------------------------------------


def test_the_policy_agent_chain_is_among_the_chains_checked() -> None:
    """``discover_chains()`` finds TWO chains, not three.

    Its own docstring records that the Policy Agent's chain lives under the
    SERVICE root, not the audit directory it globs. A command that reused it
    alone -- which is what this ticket's Done said to do -- would report every
    chain healthy while never opening the record of every policy decision.
    """
    paths = [chain.path for chain in known_chains()]
    assert policy_agent_chain_path() in paths, (
        "the adjudication chain is not checked. The command would report all "
        "clear without ever looking at it."
    )
    names = [chain.name for chain in known_chains()]
    assert any("Policy Agent" in name for name in names)


def test_an_absent_chain_is_reported_by_name_not_omitted(tmp_path: Path) -> None:
    """Silence reads as health. 'No adjudication record exists yet' and 'the
    adjudication record is fine' are different statements."""
    missing = tmp_path / "adjudication_audit.jsonl"
    text = render([inspect_chain(_at(missing, "Policy Agent adjudications"))])

    assert "Policy Agent adjudications" in text
    assert ABSENT in text
    assert "never been written" in text


def test_the_three_canonical_chains_are_all_named(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    names = " ".join(chain.name for chain in known_chains())
    for expected in ("Policy Agent", "Knowledge ingestion", "Tool and egress"):
        assert expected in names, f"{expected} chain is not reported at all"


# ---------------------------------------------------------------------------
# What the operator is handed.
# ---------------------------------------------------------------------------


def _synthetic(status: str) -> ChainReport:
    return ChainReport(
        location=_at(Path("x")), status=status, records=1, sealed_segments=0,
        first_utc=None, last_utc=None, detail="d", remedy="",
    )


def test_every_status_maps_to_the_right_exit_code() -> None:
    """A chain that could not be checked must not exit 0 -- an operator
    scripting this would read success.

    Driven through ``exit_code_for`` rather than ``main``: on this machine the
    test chains are HMAC-signed, so ``main`` can never reach TAMPER, and the
    earlier version of this test accepted "FAILED or NOT_CHECKED" and therefore
    asserted nothing about either.
    """
    assert exit_code_for([_synthetic(VERIFIED)]) == EXIT_OK
    assert exit_code_for([_synthetic(ABSENT)]) == EXIT_OK
    assert exit_code_for([]) == EXIT_OK
    for bad in (TAMPER, KEY_MISMATCH):
        assert exit_code_for([_synthetic(bad)]) == EXIT_FAILED, bad
    for gap in (UNCHECKABLE, UNREADABLE):
        assert exit_code_for([_synthetic(gap)]) == EXIT_NOT_CHECKED, gap


def test_a_failure_outranks_an_unchecked_chain_in_the_exit_code() -> None:
    """One chain tampered and another unreadable must report the FAILURE. The
    gap is a gap; the finding is a finding."""
    both = [_synthetic(UNCHECKABLE), _synthetic(TAMPER)]
    assert exit_code_for(both) == EXIT_FAILED
    assert exit_code_for(list(reversed(both))) == EXIT_FAILED


def test_main_exits_non_zero_for_a_chain_it_cannot_check(tmp_path: Path) -> None:
    """The end-to-end path, through the real CLI entry point."""
    clean = _chain(tmp_path / "clean.jsonl")
    # A NAMED file that is not there is exit 2, not 0 — see
    # test_naming_a_file_that_is_not_there_is_an_error_not_an_all_clear.
    assert main(["--audit-log", str(clean)]) == EXIT_NOT_CHECKED, (
        "an HMAC chain the TPM source cannot verify exited 0"
    )

def test_a_size_that_cannot_be_read_is_never_printed_as_zero() -> None:
    """MEASURED on the first real run: ``total_record_count`` is a property, and
    calling it raised TypeError into a broad except, so the command printed
    '0 records' and 'ALL CLEAR ... record by record' for a 33-record chain."""
    from shared.security.verify_audit_chain import ChainReport

    report = ChainReport(
        location=_at(Path("x")), status=VERIFIED, records=None,
        sealed_segments=None, first_utc=None, last_utc=None,
        detail="d", remedy="",
    )
    text = render([report])
    assert "0 record" not in text, "an unreadable size was printed as zero"
    assert "could not be read" in text

    # The toggle: a KNOWN size must still print as the number, or "could not be
    # read" everywhere would satisfy the assertion above while telling the
    # operator nothing.
    known = ChainReport(
        location=_at(Path("x")), status=VERIFIED, records=7,
        sealed_segments=0, first_utc=None, last_utc=None, detail="d", remedy="",
    )
    assert "7 records" in render([known]), (
        "a size the command DID read was not printed"
    )


def test_the_headline_leads_with_the_outcome(tmp_path: Path) -> None:
    path = _chain(tmp_path / "ingest_audit.jsonl")
    text = render([inspect_chain(_at(path), keys=_HmacKeys(_KEYS))])
    assert text.splitlines()[0].startswith("ALL CLEAR"), text.splitlines()[0]


# ---------------------------------------------------------------------------
# Structural: one implementation, and the seam stays a seam.
# ---------------------------------------------------------------------------


def test_the_default_key_source_is_the_TPM(tmp_path: Path) -> None:
    """A seam that can quietly become the production path is a second
    implementation."""
    path = _chain(tmp_path / "ingest_audit.jsonl")
    report = inspect_chain(_at(path))  # no keys= argument
    assert report.status == UNCHECKABLE, (
        "the default key source accepted an HMAC chain, so the default is not "
        "the TPM and the tests below verify something the operator never runs."
    )


def test_there_is_exactly_one_verification_start_implementation() -> None:
    """Two copies disagreed on the case that matters, and the unguarded one
    turned a retired key into a TAMPER alarm.

    Located by walking the syntax tree, never by matching source text: a text
    scan flags this file's own prose about the defect.
    """
    repo = Path(__file__).resolve().parents[2]
    found: list[str] = []
    for py in _tracked_python_files():
        tree = _parsed(py)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
                node.name in ("verification_start", "_audit_verification_start")
            ):
                rel = str(py.relative_to(repo)).replace("\\", "/")
                found.append(f"{rel}::{node.name}")

    assert found == [
        "shared/security/audit_verification.py::verification_start"
    ], f"expected exactly one implementation, found: {found}"


def test_there_is_exactly_one_signing_key_name_implementation() -> None:
    """The same pair, the same divergence: one raised a catchable
    ``AuditProvisioningError``, the other a bare ``RuntimeError``."""
    repo = Path(__file__).resolve().parents[2]
    found: list[str] = []
    for py in _tracked_python_files():
        tree = _parsed(py)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
                node.name in ("signing_key_name", "_audit_signing_key_name")
            ):
                found.append(str(py.relative_to(repo)).replace("\\", "/"))

    assert found == ["shared/security/audit_verification.py"], (
        f"expected exactly one implementation, found: {found}"
    )


# ---------------------------------------------------------------------------
# Review findings (#1581 adversarial review, 2026-09-20). Each of these is a
# lock for a defect the review REPRODUCED.
# ---------------------------------------------------------------------------


def test_the_segment_index_is_not_reported_as_a_chain(monkeypatch, tmp_path) -> None:
    """Review finding 3, reproduced: the first segment rotation made the
    system's own bookkeeping file appear as an ``Unrecognised chain --
    UNCHECKABLE``, and the command exited 4 permanently from then on.

    ``discover_chains()`` excluded ``*-index.jsonl``; the real name is
    ``audit-segments.jsonl``, which does not match that suffix.
    """
    from shared.security.audit_log import SEGMENT_INDEX_NAME

    audit_dir = tmp_path / "BlarAI" / "audit"
    audit_dir.mkdir(parents=True)
    _chain(audit_dir / "ingest_audit.jsonl")
    (audit_dir / SEGMENT_INDEX_NAME).write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    paths = [chain.path for chain in known_chains()]
    assert audit_dir / SEGMENT_INDEX_NAME not in paths, (
        "the segment index is reported as an audit chain; the operator is told "
        "an unrecognised chain exists and the command exits non-zero forever"
    )
    names = " ".join(chain.name for chain in known_chains())
    assert "Unrecognised" not in names, names


def test_a_genuinely_unexpected_chain_IS_still_reported(monkeypatch, tmp_path) -> None:
    """The toggle for the test above: excluding the index must not have
    switched off the unexpected-chain report altogether."""
    audit_dir = tmp_path / "BlarAI" / "audit"
    audit_dir.mkdir(parents=True)
    _chain(audit_dir / "mystery_audit.jsonl")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    names = " ".join(chain.name for chain in known_chains())
    assert "Unrecognised chain (mystery_audit.jsonl)" in names, names


def test_a_read_only_handle_cannot_seal_truncate_or_prune(tmp_path: Path) -> None:
    """Review finding 1, reproduced: ``rotate_signing_key`` seals the active
    segment BEFORE it appends, so a read-only handle wrote the gzip, wrote the
    segment index and TRUNCATED THE ACTIVE FILE TO ZERO BYTES, then refused the
    append. Guarding the last step of a multi-step write keeps nothing.
    """
    path = _chain(tmp_path / "ingest_audit.jsonl", count=4)
    before_files = sorted(p.name for p in tmp_path.iterdir())
    before_bytes = path.stat().st_size

    read_only = AuditLog.from_path(path, _A, read_only=True)
    with pytest.raises(AuditSinkError, match="read-only"):
        read_only.rotate_signing_key(_B)

    assert path.stat().st_size == before_bytes, (
        "the active file was truncated by a handle opened read-only"
    )
    assert sorted(p.name for p in tmp_path.iterdir()) == before_files, (
        "a read-only handle created files: "
        f"{sorted(set(p.name for p in tmp_path.iterdir()) - set(before_files))}"
    )


def test_every_write_entry_point_refuses_when_read_only(tmp_path: Path) -> None:
    """Not just ``append``. Each of these is a way to change the record."""
    path = _chain(tmp_path / "ingest_audit.jsonl")
    log = AuditLog.from_path(path, _A, read_only=True)

    for label, call in (
        ("append", lambda: log.append(
            adjudication_id="x", decision="ALLOW", car_hash="h",
            resource="r", **_COMMON)),
        ("rotate_signing_key", lambda: log.rotate_signing_key(_B)),
        ("_rotate_active_segment", log._rotate_active_segment),
        ("_enforce_retention", log._enforce_retention),
        ("_write_record", lambda: log._write_record(log.records[0])),
    ):
        with pytest.raises(AuditSinkError, match="read-only"):
            call()
            pytest.fail(f"{label} did not refuse on a read-only log")


def test_the_command_opens_every_chain_read_only(tmp_path: Path, monkeypatch) -> None:
    """Review finding 6: mutating ``read_only=True`` to ``False`` at the
    command's own call site left all tests green.

    ``test_inspecting_changes_not_one_byte`` compares bytes and mtime, and the
    write that ``read_only`` prevents is a DACL rewrite — neither of those. The
    review measured a default-mode open silently rewriting the ACL of a
    simulated preserved forensic copy. This locks the wiring instead: the
    command must ASK for read-only, whatever the mode happens to do.
    """
    import shared.security.audit_log as audit_log_module

    # Build the chain BEFORE the spy is installed: the fixture opens it for
    # writing, and counting that open made this assert fail on its own setup.
    path = _chain(tmp_path / "ingest_audit.jsonl")

    seen: list[bool] = []
    real = audit_log_module.AuditLog.from_path

    def _spy(path, signer, **kwargs):
        seen.append(bool(kwargs.get("read_only", False)))
        return real(path, signer, **kwargs)

    monkeypatch.setattr(audit_log_module.AuditLog, "from_path", staticmethod(_spy))

    inspect_chain(_at(path), keys=_HmacKeys(_KEYS))

    assert seen, "the command never opened the chain at all"
    assert all(seen), (
        "the command opened a chain WITHOUT read_only — on a preserved forensic "
        "copy that rewrites the evidence file's ACL"
    )


def test_tpm_key_resolver_is_called_from_exactly_one_module() -> None:
    """Review finding 2: there was a THIRD key ladder, inline inside
    ``rotate_audit_key.rotate()`` under no function name — so the
    match-by-function-name lock below certified "exactly one implementation"
    while sitting one directory from the third, which raised TypeError on every
    invocation.

    A ladder is built by CALLING ``tpm_key_resolver``. Locking the call site is
    what the name-based lock could not do.
    """
    repo = Path(__file__).resolve().parents[2]
    callers: set[str] = set()
    for py in _tracked_python_files():
        if "tests" in py.parts:
            continue
        tree = _parsed(py)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "tpm_key_resolver"
            ):
                callers.add(str(py.relative_to(repo)).replace("\\", "/"))

    assert callers == {"shared/security/audit_verification.py"}, (
        f"the key ladder is built in more than one place: {sorted(callers)}"
    )


def test_a_pruned_chain_is_not_reported_as_complete(tmp_path: Path) -> None:
    """Review finding 5, reproduced: with retention on, ten of twelve records
    were gone, no archive files remained, and the report said "verified
    completely, record by record ... including every record inside the sealed
    archive files". The surviving chain IS internally consistent, so it
    verifies correctly — the defect is the claim, not the verdict.
    """
    path = tmp_path / "ingest_audit.jsonl"
    # BOTH knobs. Retention prunes whole SEALED segments, so the active file
    # must rotate first; with the default 100k ceiling, 12 records never sealed
    # and this fixture pruned nothing while asserting that it had.
    log = AuditLog.from_path(path, _A, max_active_records=2, archive_max_bytes=1)
    for i in range(12):
        log.append(
            adjudication_id=f"i{i}", decision="ALLOW", car_hash=f"h{i}",
            resource=f"r{i}", **_COMMON,
        )

    report = inspect_chain(_at(path), keys=_HmacKeys(_KEYS))
    assert report.status == VERIFIED, report.detail
    assert report.pruned, (
        "records were pruned and the report does not say so. The operator reads "
        "a complete-looking record that has lost most of its history."
    )

    text = render([report])
    assert "GONE:" in text, text
    assert "ALL CLEAR" not in text, (
        "the headline still says ALL CLEAR over a chain missing most of itself"
    )
    assert "NOT COMPLETE" in text


def test_an_unpruned_chain_says_nothing_about_pruning(tmp_path: Path) -> None:
    """The toggle: a GONE line on every report would satisfy the test above."""
    path = _chain(tmp_path / "ingest_audit.jsonl")
    report = inspect_chain(_at(path), keys=_HmacKeys(_KEYS))

    assert not report.pruned, f"pruning claimed on an untouched chain: {report.pruned}"
    text = render([report])
    assert "GONE:" not in text
    assert text.splitlines()[0].startswith("ALL CLEAR")


def test_naming_a_file_that_is_not_there_is_an_error_not_an_all_clear(
    tmp_path: Path, capsys
) -> None:
    """Review finding 7, reproduced: it exited 0 and printed "NO AUDIT RECORD
    EXISTS YET on this machine" — a claim about the machine, from a run that
    examined one named path. A scripted ``--audit-log X || alert`` could never
    fire on the file disappearing.
    """
    code = main(["--audit-log", str(tmp_path / "not-there.jsonl")])
    out = capsys.readouterr().out

    assert code == EXIT_CANNOT_RUN, f"exited {code} for a file that is not there"
    assert code != EXIT_OK
    assert "NO AUDIT RECORD EXISTS YET" not in out, (
        "a single-file run claimed the whole machine holds no record: " + out
    )
    assert "CANNOT RUN" in out


def test_the_empty_headline_only_claims_the_machine_when_it_scanned_it() -> None:
    """The other half of finding 7: the headline's scope must follow the run's."""
    machine = render([], scanned_machine=True)
    named = render([], scanned_machine=False)

    assert "on this machine" in machine
    assert "on this machine" not in named
    assert "THE FILE YOU NAMED IS NOT THERE" in named


def test_the_command_always_walks_the_archives(tmp_path: Path, monkeypatch) -> None:
    """Review finding 8: mutating ``full=True`` to ``False`` left every test
    green, because no chain in this suite has a sealed segment whose verdict
    differs between the two modes.

    The review tried to build the discriminating case and could not — an edit
    inside a sealed archive is ALSO caught on the fast path, by the index
    anchor's SHA-256 pin. So the exhaustive walk is defence in depth rather
    than a strictly stronger check, and what is lockable is the WIRING: the
    command must ask for it. Recorded as an honest limit rather than dressed up
    as a behavioural lock.
    """
    seen: list[bool] = []
    real = AuditLog.verify

    def _spy(self, **kwargs):
        seen.append(bool(kwargs.get("full", False)))
        return real(self, **kwargs)

    path = _chain(tmp_path / "ingest_audit.jsonl")
    monkeypatch.setattr(AuditLog, "verify", _spy)
    inspect_chain(_at(path), keys=_HmacKeys(_KEYS))

    assert seen == [True], (
        "the command did not ask for the exhaustive walk it advertises; "
        f"full= was {seen}"
    )


def test_the_policy_agent_chain_path_follows_the_config(tmp_path: Path) -> None:
    """Review finding 9: ``policy_agent_chain_path`` was unlocked. The only test
    asserted it appeared in ``known_chains()`` — both sides call the same
    function, so it was self-consistent under any mutation, including the
    mutation of ignoring the config entirely, which is precisely what its
    docstring warns would cause a false all-clear."""
    service = tmp_path / "services" / "policy_agent"
    (service / "config").mkdir(parents=True)
    config = service / "config" / "default.toml"

    config.write_text("[security]\n", encoding="utf-8")
    assert policy_agent_chain_path(tmp_path) == (
        service / "data" / "audit" / "adjudication_audit.jsonl"
    ), "an unset override did not fall back to the service-root default"

    moved = tmp_path / "elsewhere" / "moved_audit.jsonl"
    config.write_text(
        f'[security]\naudit_log_path = "{moved.as_posix()}"\n', encoding="utf-8"
    )
    assert policy_agent_chain_path(tmp_path) == moved, (
        "the command ignores [security].audit_log_path, so an operator who "
        "moved the adjudication chain is told it is ABSENT — a false all-clear "
        "about the record of every policy decision"
    )

    config.write_text(
        '[security]\naudit_log_path = "data/custom/chain.jsonl"\n', encoding="utf-8"
    )
    assert policy_agent_chain_path(tmp_path) == service / "data/custom/chain.jsonl", (
        "a relative override did not resolve against the service root, which is "
        "what PolicyAgentService._resolve_path does"
    )


def test_every_write_method_guards_read_only_at_its_own_top() -> None:
    """Defence in depth, locked structurally rather than one call path at a time.

    MEASURED: removing the guard from ``rotate_signing_key`` alone left all
    tests green, because ``_rotate_active_segment``'s guard fires first on that
    path. The outer guard is therefore redundant TODAY — and is exactly what
    keeps the mode honest the day the seal moves, is skipped, or a new write
    path is added. An unlocked control is a gap even when a second control
    happens to cover it (security_by_design 12), so this asserts the guard is
    present on each write method rather than asserting one call path refuses.

    By syntax tree: the guard must be a STATEMENT at the top of each method, not
    a mention anywhere in the file.
    """
    import shared.security.audit_log as audit_log_module

    source = Path(audit_log_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    cls = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.ClassDef) and n.name == "AuditLog"
    )

    WRITE_METHODS = {
        "append",
        "_write_record",
        "_rotate_active_segment",
        "_enforce_retention",
        "rotate_signing_key",
    }
    guarded: set[str] = set()
    for node in cls.body:
        if not isinstance(node, ast.FunctionDef) or node.name not in WRITE_METHODS:
            continue
        for stmt in node.body:
            call = stmt.value if isinstance(stmt, ast.Expr) else None
            if (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "_refuse_if_read_only"
            ):
                guarded.add(node.name)
                break

    assert guarded == WRITE_METHODS, (
        "these write methods do not refuse a read-only log at their own top: "
        f"{sorted(WRITE_METHODS - guarded)}. A read-only handle that reaches "
        "one of them can change the operator's audit record."
    )
