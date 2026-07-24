"""Frontmatter lint for the BlarAI documentation lifecycle convention (Vikunja #267).

Checks that governed Markdown documents carry the YAML frontmatter defined by
``docs/governance/doc-lifecycle.md``: a ``title``, a ``status`` drawn from the five
canonical lifecycle states, an owning ``area``, and a ``superseded_by`` pointer iff
the status is ``superseded``.

This is an *advisory* report tool. It exits non-zero on violations so it CAN be wired
into a gate later, but it is deliberately NOT part of the standing test gate yet:
today zero documents carry this frontmatter, so gating would fail the whole tree.

Deterministic, no third-party dependencies. The frontmatter the convention defines is
flat scalars only, so a small built-in parser handles it without a YAML library.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, Sequence

# The five canonical lifecycle states (docs/governance/doc-lifecycle.md).
CANONICAL_STATUSES: frozenset[str] = frozenset(
    {"living", "reference", "draft", "superseded", "archived"}
)
# Accepted spellings normalized to a canonical state before validation.
STATUS_ALIASES: dict[str, str] = {"active": "living"}
# Fields every governed doc must carry, non-empty.
REQUIRED_FIELDS: tuple[str, ...] = ("title", "status", "area")

# Directory names never descended into during a recursive scan — the gitignored
# validator toolchains balloon a recursive docs/ scan ~20x, and VCS/tooling dirs
# hold nothing governed.
_SKIP_DIRS: frozenset[str] = frozenset(
    {"node_modules", ".git", ".venv", "__pycache__", "_validate"}
)


@dataclass(frozen=True)
class Finding:
    """A single lint result on one file."""

    path: Path
    level: str  # "violation" | "warning"
    code: str
    message: str


@dataclass
class FileReport:
    """All findings for one document."""

    path: Path
    findings: list[Finding] = field(default_factory=list)

    @property
    def violations(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "violation"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "warning"]

    @property
    def ok(self) -> bool:
        """True when the file has no violations (warnings do not fail a file)."""
        return not self.violations


@dataclass
class LintReport:
    """Aggregate result across every scanned document."""

    files: list[FileReport] = field(default_factory=list)

    @property
    def violations(self) -> list[Finding]:
        return [f for fr in self.files for f in fr.violations]

    @property
    def warnings(self) -> list[Finding]:
        return [f for fr in self.files for f in fr.warnings]

    @property
    def compliant_files(self) -> list[FileReport]:
        return [fr for fr in self.files if fr.ok]

    @property
    def ok(self) -> bool:
        """True when no file has a violation."""
        return all(fr.ok for fr in self.files)

    def passed(self, *, strict: bool = False) -> bool:
        """Overall pass. Under ``strict`` a warning also fails the run."""
        if strict:
            return self.ok and not self.warnings
        return self.ok

    def to_dict(self) -> dict[str, object]:
        """A JSON-serializable summary of the report."""
        return {
            "files_scanned": len(self.files),
            "compliant": len(self.compliant_files),
            "violation_count": len(self.violations),
            "warning_count": len(self.warnings),
            "findings": [
                {
                    "path": f.path.as_posix(),
                    "level": f.level,
                    "code": f.code,
                    "message": f.message,
                }
                for fr in self.files
                for f in fr.findings
            ],
        }


def parse_frontmatter(text: str) -> dict[str, str] | None:
    """Parse a leading YAML frontmatter block of flat ``key: value`` scalars.

    Returns the field map, or ``None`` when the text does not open with a ``---``
    fence or the fence is never closed. Handles CRLF and LF line endings, strips
    surrounding quotes, and drops trailing ``' #'`` inline comments on unquoted
    values (matching the documented example style). Nested/structured YAML is out of
    scope by design — the convention mandates flat scalars.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None

    fields: dict[str, str] = {}
    for raw in lines[1:]:
        stripped = raw.strip()
        if stripped == "---":
            return fields
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            # Not a key: value line inside a flat block — ignore it rather than
            # guessing; a malformed value surfaces as a missing required field.
            continue
        key, _, value = stripped.partition(":")
        fields[key.strip()] = _clean_value(value.strip())
    # Opened but never closed → treat as no usable frontmatter.
    return None


def _clean_value(value: str) -> str:
    """Strip an inline comment from an unquoted value, then strip wrapping quotes."""
    if value[:1] in {'"', "'"}:
        quote = value[0]
        end = value.find(quote, 1)
        if end != -1:
            return value[1:end]
        return value[1:]
    # Unquoted: an inline comment is ' #' (whitespace then hash).
    for i in range(1, len(value)):
        if value[i] == "#" and value[i - 1].isspace():
            value = value[:i]
            break
    return value.strip()


def check_file(path: Path) -> FileReport:
    """Validate one Markdown document against the lifecycle frontmatter convention."""
    report = FileReport(path=path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:  # pragma: no cover - defensive
        report.findings.append(
            Finding(path, "violation", "UNREADABLE", f"could not read file: {exc}")
        )
        return report

    fields = parse_frontmatter(text)
    if fields is None:
        report.findings.append(
            Finding(
                path,
                "violation",
                "MISSING_FRONTMATTER",
                "no lifecycle frontmatter (expected a leading '---' … '---' block)",
            )
        )
        return report

    for name in REQUIRED_FIELDS:
        if not fields.get(name):
            report.findings.append(
                Finding(
                    path,
                    "violation",
                    "MISSING_FIELD",
                    f"required frontmatter field '{name}' is missing or empty",
                )
            )

    raw_status = fields.get("status", "")
    status = STATUS_ALIASES.get(raw_status, raw_status)
    if raw_status and status not in CANONICAL_STATUSES:
        report.findings.append(
            Finding(
                path,
                "violation",
                "BAD_STATUS",
                f"status '{raw_status}' is not one of "
                f"{sorted(CANONICAL_STATUSES)} (alias: 'active'='living')",
            )
        )

    superseded_by = fields.get("superseded_by", "")
    if status == "superseded":
        if not superseded_by:
            report.findings.append(
                Finding(
                    path,
                    "violation",
                    "MISSING_SUPERSEDED_BY",
                    "status 'superseded' requires a 'superseded_by:' pointer",
                )
            )
        else:
            target = (path.parent / superseded_by).resolve()
            if not target.exists():
                report.findings.append(
                    Finding(
                        path,
                        "warning",
                        "SUPERSEDED_TARGET_MISSING",
                        f"superseded_by target does not resolve on disk: "
                        f"{superseded_by}",
                    )
                )
    elif superseded_by:
        report.findings.append(
            Finding(
                path,
                "violation",
                "SUPERSEDED_BY_MISUSE",
                "'superseded_by:' is only valid when status is 'superseded'",
            )
        )

    return report


def iter_markdown(paths: Sequence[Path], *, recursive: bool = False) -> Iterator[Path]:
    """Yield the Markdown files to lint, deduplicated and sorted for determinism.

    A file path is yielded as-is. A directory yields its direct ``*.md`` children;
    with ``recursive`` it descends, skipping ``_SKIP_DIRS`` (notably the gitignored
    ``node_modules`` under ``docs/**/_validate`` that would otherwise dominate).
    """
    seen: set[Path] = set()
    ordered: list[Path] = []

    def _add(p: Path) -> None:
        rp = p.resolve()
        if rp not in seen:
            seen.add(rp)
            ordered.append(p)

    for path in paths:
        if path.is_dir():
            if recursive:
                for child in path.rglob("*.md"):
                    if any(part in _SKIP_DIRS for part in child.relative_to(path).parts):
                        continue
                    _add(child)
            else:
                for child in sorted(path.glob("*.md")):
                    _add(child)
        elif path.suffix.lower() == ".md" or path.is_file():
            _add(path)
    return iter(sorted(ordered, key=lambda p: p.as_posix()))


def check_paths(paths: Iterable[Path], *, recursive: bool = False) -> LintReport:
    """Lint every Markdown document reachable from ``paths``."""
    targets = list(iter_markdown(list(paths), recursive=recursive))
    return LintReport(files=[check_file(p) for p in targets])
