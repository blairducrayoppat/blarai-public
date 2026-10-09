"""Check your own audit record, without starting a key rotation (#1581).

The point of a tamper-evident record is that its owner can check it rather than
take someone's word. Until this existed the only way to walk a chain end to end
was step 1 of ``rotate_audit_key``, so the only route to "is my record intact?"
began by changing a signing key.

Usage::

    python -m shared.security.verify_audit_chain
    python -m shared.security.verify_audit_chain --audit-log <path>

Exit codes: 0 every chain present verified; 3 a chain FAILED; 4 a chain could
not be checked at all; 2 the command could not run (including a ``--audit-log``
path that is not there). Any other non-zero code is an unhandled error in the
command itself, not a finding about the record.

WHAT THIS DOES NOT DO: it never writes, never creates a directory, never touches
a key. It opens every chain ``read_only`` so that inspecting a chain cannot
change it, and so a preserved copy on read-only media can be checked at all.

WHY IT WALKS THE CHAINS THE SLOW WAY: ``full=True``, always. The fast path
trusts the signed sealed-segment anchor and does not reopen the sealed
``.jsonl.gz`` files. This command exists for the person who does not want to
trust an anchor, so it gunzips and re-walks every record.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "ChainLocation",
    "TpmKeys",
    "ChainReport",
    "known_chains",
    "inspect_chain",
    "policy_agent_chain_path",
    "render",
    "exit_code_for",
    "main",
]

# Outcomes. ABSENT is a first-class result, not silence: "no adjudication record
# exists yet" and "the adjudication record is fine" are different statements, and
# a command that omitted the absent chain would let the second be read for the
# first.
VERIFIED = "VERIFIED"
ABSENT = "ABSENT"
TAMPER = "TAMPER"
KEY_MISMATCH = "KEY_MISMATCH"
UNCHECKABLE = "UNCHECKABLE"
UNREADABLE = "UNREADABLE"

EXIT_OK = 0
EXIT_CANNOT_RUN = 2
EXIT_FAILED = 3
EXIT_NOT_CHECKED = 4

_TPM_PREFIX = "ECDSA-P256-TPM:"


class TpmKeys:
    """Where this command gets its verifiers: the security chip. THE DEFAULT.

    A seam, not a mock. ``inspect_chain`` takes a key source so the regression
    locks can drive the REAL walk -- discovery, the read-only open, the full
    record-by-record verification, the classification and the exit codes -- over
    HMAC-signed chains they can build, on machines with no TPM. Everything but
    the choice of verifier is the production path.

    The default is pinned by a gate test. A seam that can quietly become the
    production path is not a seam, it is a second implementation.
    """

    prefix: str = _TPM_PREFIX

    def accepts(self, signer_id: str) -> bool:
        """True when this source can verify a chain whose records claim ``signer_id``."""
        return signer_id.startswith(self.prefix)

    def current(self, path: Path):
        """The verifier for a chain that has never rotated."""
        from shared.security.audit_log import TpmRecordSigner
        from shared.security.audit_verification import signing_key_name

        return TpmRecordSigner(key_name=signing_key_name(path))

    def start(self, path: Path):
        """``(first signer, resolver, key order)`` for a possibly-rotated chain."""
        from shared.security.audit_verification import verification_start

        return verification_start(path)


@dataclass(frozen=True)
class ChainLocation:
    """One audit chain this machine may hold, named in plain language."""

    name: str
    path: Path
    holds: str


@dataclass(frozen=True)
class ChainReport:
    """What walking one chain established."""

    location: ChainLocation
    status: str
    records: int | None
    sealed_segments: int | None
    first_utc: str | None
    last_utc: str | None
    detail: str
    remedy: str
    pruned: int | None = None
    """Records the chain once held that are no longer on disk, or None.

    Retention prunes whole sealed segments, each prune attested by a signed
    ``RETENTION_PRUNE`` record, and the surviving chain stays internally
    consistent -- so it VERIFIES, correctly. Without this the report said
    "verified completely, record by record" over a chain that had lost ten of
    its twelve records, and the size line presented the RETAINED count as the
    record's size."""


def policy_agent_chain_path(repo_root: Path | None = None) -> Path:
    """The Policy Agent's adjudication chain, honouring its config override.

    Read from ``[security].audit_log_path`` in the Policy Agent's own
    ``default.toml``, resolved by the same rule the service uses, falling back
    to the service-root default. Hardcoding the default instead would report
    ABSENT for an operator who had moved the chain -- a false all-clear about
    the one chain that records every policy decision.
    """
    root = repo_root or Path(__file__).resolve().parents[2]
    service_root = root / "services" / "policy_agent"
    config_path = service_root / "config" / "default.toml"
    default = service_root / "data" / "audit" / "adjudication_audit.jsonl"
    try:
        with open(config_path, "rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return default
    raw = str(data.get("security", {}).get("audit_log_path", "")).strip()
    if not raw:
        return default
    candidate = Path(raw)
    if candidate.is_absolute():
        return candidate
    if (root / candidate).exists():
        return root / candidate
    return service_root / candidate


def known_chains(repo_root: Path | None = None) -> list[ChainLocation]:
    """Every chain this machine may hold -- present or not.

    Three are canonical and are always reported by name, because an absent one
    must be visible. ``discover_chains()`` is then consulted for anything ELSE
    under the user-data audit directory: a fourth chain nobody told this command
    about is exactly what an operator needs to see, so it is reported rather
    than ignored.

    ``discover_chains()`` alone would NOT be enough. Its own docstring records
    that the Policy Agent's chain lives under the SERVICE root, not the audit
    directory it globs, so a command that trusted it would report every chain
    healthy while never opening the adjudication record.
    """
    from shared.security.rotate_audit_key import discover_chains

    local = os.environ.get("LOCALAPPDATA", "")
    audit_dir = Path(local) / "BlarAI" / "audit" if local else None

    chains: list[ChainLocation] = [
        ChainLocation(
            name="Policy Agent adjudications",
            path=policy_agent_chain_path(repo_root),
            holds="every policy decision this system has made",
        )
    ]
    if audit_dir is not None:
        chains.append(
            ChainLocation(
                name="Knowledge ingestion",
                path=audit_dir / "ingest_audit.jsonl",
                holds="every document taken into the knowledge bank",
            )
        )
        chains.append(
            ChainLocation(
                name="Tool and egress verdicts",
                path=audit_dir / "verdict_audit.jsonl",
                holds=(
                    "every tool call and outbound request allowed or refused"
                ),
            )
        )

    known = {chain.path for chain in chains}
    for found in discover_chains():
        if found not in known:
            chains.append(
                ChainLocation(
                    name=f"Unrecognised chain ({found.name})",
                    path=found,
                    holds=(
                        "unknown -- this is not one of the three chains this "
                        "system is known to keep"
                    ),
                )
            )
    return chains


def _first_signer_id(path: Path) -> tuple[str | None, str | None]:
    """``(signer_id of the first record, error)`` -- read, never trusted as a key.

    The first record's claimed ``signer_id`` decides only whether this command
    CAN check the chain, never which key it checks against. Choosing the key
    from a record's own claim is the forgery #1578's review demonstrated: a
    chain rewritten end to end under an unrelated on-chip key passed. The key
    comes from the chain's key history, so a claim that this is an unsupported
    algorithm can only cost a refusal to check, never buy a false pass.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                return str(json.loads(line).get("signer_id", "")), None
    except (OSError, json.JSONDecodeError, ValueError, UnicodeDecodeError) as exc:
        return None, str(exc)
    return None, "the file contains no records"


def inspect_chain(location: ChainLocation, *, keys: "TpmKeys | None" = None) -> ChainReport:
    """Walk one chain fully and classify the outcome. Writes nothing.

    ``keys`` defaults to :class:`TpmKeys` -- the production path. See that
    class for why it is injectable.
    """
    from shared.security.audit_log import (
        AuditChainError,
        AuditLog,
        AuditProvisioningError,
    )

    keys = keys if keys is not None else TpmKeys()

    def _report(status: str, detail: str, remedy: str, log=None) -> ChainReport:
        records: int | None = None
        sealed: int | None = None
        pruned: int | None = None
        first = last = None
        if log is not None:
            # Properties, not methods. Calling them raised TypeError on the
            # first real run, which the broad except below used to swallow --
            # so the command reported "0 records" and "ALL CLEAR ... record by
            # record" for a 33-record chain. A size it cannot read is reported
            # as UNREADABLE-size, never as zero: zero is a claim.
            try:
                records = int(log.total_record_count)
                sealed = int(log.segment_count)
                active = list(log.records)
                if active:
                    first = active[0].timestamp_utc
                    last = active[-1].timestamp_utc
                    # seq is monotonic from 0, so the last one names how many
                    # records the chain has EVER held. total_record_count is
                    # what is retained on disk. A gap is pruned history.
                    ever = active[-1].seq + 1
                    if ever > records:
                        pruned = ever - records
            except Exception as exc:  # noqa: BLE001 - loud, not silent
                records = sealed = None
                detail = (
                    f"{detail} (This command could not read the chain's size: "
                    f"{exc}. That is a defect in the command, not a finding "
                    "about your records.)"
                )
        return ChainReport(
            location=location,
            status=status,
            records=records,
            sealed_segments=sealed,
            first_utc=first,
            last_utc=last,
            detail=detail,
            remedy=remedy,
            pruned=pruned,
        )

    if not location.path.exists():
        return _report(
            ABSENT,
            "No such file. This chain has never been written on this machine.",
            "Nothing to do. If you expected a record here, the service that "
            "writes it has not run, or is writing somewhere else.",
        )

    signer_id, read_error = _first_signer_id(location.path)
    if read_error is not None:
        return _report(
            UNREADABLE,
            f"The file could not be read as an audit chain: {read_error}",
            "Preserve the file. A chain that cannot be parsed is not the same "
            "as one that fails to verify, and the difference matters to whoever "
            "investigates it.",
        )
    if signer_id is None or not keys.accepts(signer_id):
        return _report(
            UNCHECKABLE,
            f"This chain is signed with {signer_id or 'an unnamed key'}, which "
            "this command cannot verify. It checks chains signed by the TPM "
            "(the security chip), whose public key it can use. A chain signed "
            "with a development key can only be checked by the service that "
            "holds that secret.",
            "If you expected a TPM-signed chain here, this is worth "
            "investigating: it means these records were written by a service "
            "running in development mode.",
        )

    try:
        current_signer = keys.current(location.path)
        first_signer, resolver, order = keys.start(location.path)
    except AuditProvisioningError as exc:
        return _report(
            UNCHECKABLE,
            f"The chain's key history could not be used: {exc}",
            "Restore the named key. A retired audit key must never be deleted "
            "-- records it signed verify under it and under nothing else.",
        )

    try:
        log = AuditLog.from_path(location.path, current_signer, read_only=True)
    except Exception as exc:  # noqa: BLE001 - opening is not verifying
        return _report(
            UNREADABLE,
            f"The chain could not be opened: {exc}",
            "Preserve the file and investigate; do not delete or regenerate it.",
        )

    try:
        log.verify(
            signer=first_signer, key_resolver=resolver, key_order=order, full=True
        )
    except AuditChainError as exc:
        return _report(
            TAMPER if exc.is_tamper else KEY_MISMATCH,
            f"Verification failed at record {exc.index}: {exc.reason}",
            exc.operator_guidance,
            log,
        )
    except Exception as exc:  # noqa: BLE001
        # A TPM that cannot answer is NOT a tamper finding. Reporting it as one
        # would tell the operator their record was altered when the security
        # chip was merely unavailable -- the #1569 alarm, one layer out.
        return _report(
            UNCHECKABLE,
            f"The chain could not be checked: {exc}",
            "This is not a finding about your records -- it means the check "
            "could not be completed. The security chip may be unavailable.",
            log,
        )

    detail = "Every record still on disk was re-hashed and its signature re-checked"
    detail += (
        ", including every record inside the sealed archive files."
        if log.segment_count
        else ". This chain has no sealed archive files."
    )
    return _report(VERIFIED, detail, "", log)


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" + ("" if count == 1 else "s")


def render(reports: list[ChainReport], *, scanned_machine: bool = True) -> str:
    """The operator-facing report. Plain language, outcome first.

    ``scanned_machine`` is False when the operator named ONE file. The empty
    headline used to say "no audit record exists yet ON THIS MACHINE" from a run
    that had examined a single named path -- so someone checking a preserved
    copy whose drive had not mounted was told their machine held no record.
    """
    failed = [r for r in reports if r.status in (TAMPER, KEY_MISMATCH)]
    unchecked = [r for r in reports if r.status in (UNCHECKABLE, UNREADABLE)]
    verified = [r for r in reports if r.status == VERIFIED]

    if failed:
        headline = (
            f"PROBLEM FOUND. {_plural(len(failed), 'audit chain')} did not verify."
        )
    elif unchecked:
        headline = (
            f"NOT FULLY CHECKED. {_plural(len(unchecked), 'chain')} could not be "
            "checked at all, so this is not a clean bill of health."
        )
    elif verified and any(r.pruned for r in verified):
        headline = (
            f"VERIFIED, BUT NOT COMPLETE. {_plural(len(verified), 'audit chain')} "
            "verified record by record — but part of the history has been "
            "removed by retention and is no longer on disk. See GONE below."
        )
    elif verified:
        headline = (
            f"ALL CLEAR. {_plural(len(verified), 'audit chain')} verified "
            "completely, record by record."
        )
    elif scanned_machine:
        headline = (
            "NO AUDIT RECORD EXISTS YET on this machine. That is not a failure, "
            "but it means there is nothing here to check."
        )
    else:
        headline = (
            "THE FILE YOU NAMED IS NOT THERE. Nothing was checked. This says "
            "nothing about the rest of your audit record."
        )

    lines = [headline, ""]
    for report in reports:
        lines.append(f"{report.location.name} -- {report.status}")
        lines.append(f"  file:   {report.location.path}")
        lines.append(f"  holds:  {report.location.holds}")
        if report.status != ABSENT:
            span = "unknown"
            if report.first_utc and report.last_utc:
                span = f"{report.first_utc} to {report.last_utc}"
            size = (
                _plural(report.records, "record")
                if report.records is not None
                else "could not be read (see below)"
            )
            lines.append(f"  size:   {size}")
            if report.sealed_segments:
                lines.append(
                    "  note:   "
                    f"{_plural(report.sealed_segments, 'sealed archive file')}"
                    " -- every record inside was re-walked, but the period below"
                    " covers the active file only; this command does not read"
                    " timestamps out of the archives."
                )
            lines.append(f"  period: {span}")
            if report.pruned:
                lines.append(
                    f"  GONE:   {_plural(report.pruned, 'record')} this chain "
                    "once held are no longer on disk. Retention removed whole "
                    "archive files, and each removal is itself recorded and "
                    "signed — so what remains is genuine and complete in "
                    "itself, but it is NOT the whole history. The size and "
                    "period above describe what is left."
                )
        lines.append(f"  {report.detail}")
        if report.remedy:
            lines.append(f"  WHAT TO DO: {report.remedy}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def exit_code_for(reports: "list[ChainReport]") -> int:
    """The verdict as a number, for anyone scripting this.

    A separate function so it can be locked against every status directly.
    Driven only through ``main`` it could not be: on a machine whose test
    chains are HMAC-signed, ``main`` never reaches TAMPER, so a test asserting
    "FAILED or NOT_CHECKED" passed while proving nothing about either.

    Order matters. A run holding both a failure and an unchecked chain reports
    the FAILURE: the unchecked one is a gap, the failure is a finding.
    """
    if any(r.status in (TAMPER, KEY_MISMATCH) for r in reports):
        return EXIT_FAILED
    if any(r.status in (UNCHECKABLE, UNREADABLE) for r in reports):
        return EXIT_NOT_CHECKED
    return EXIT_OK


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m shared.security.verify_audit_chain",
        description=(
            "Walk every audit chain on this machine end to end and report "
            "whether it verifies. Changes nothing."
        ),
    )
    parser.add_argument(
        "--audit-log",
        type=Path,
        default=None,
        help="Check only this chain, instead of every chain found.",
    )
    args = parser.parse_args(argv)

    scanned_machine = args.audit_log is None
    if not scanned_machine:
        if not args.audit_log.exists():
            # NOT exit 0. The operator named this file, so its absence is a
            # failure of the request, not a clean bill of health -- and a
            # scripted `verify_audit_chain --audit-log X || alert` could never
            # alert on the file disappearing.
            sys.stdout.write(
                f"CANNOT RUN: there is no file at {args.audit_log}.\n"
                "Nothing was checked. If you meant to check every chain on "
                "this machine, run the command with no arguments.\n"
            )
            return EXIT_CANNOT_RUN
        locations = [
            ChainLocation(
                name="The chain you named",
                path=args.audit_log,
                holds="(named on the command line)",
            )
        ]
    else:
        locations = known_chains()

    reports = [inspect_chain(location) for location in locations]  # TpmKeys()
    sys.stdout.write(render(reports, scanned_machine=scanned_machine))

    return exit_code_for(reports)


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
