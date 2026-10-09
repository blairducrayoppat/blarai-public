"""#1182 — the deterministic SECURITY floor over a banked GREEN's delivered tree.

A Layer-1-class check (cheap, no model, bounded, fail-soft, ADVISORY) that lives in its own
module because it answers a question none of the other layers ask. The coder was never told
to write secure code (``AGENTS.md`` house rules 4-6 now say it), never asked for it by a card,
and never graded on whether it did — so a delivered web app with a hardcoded credential, a
string-built SQL query, or unescaped markup written straight into the DOM banked GREEN band A
and read to the operator as "Looks clean". This module is the deterministic half of closing
that: what the brief now DEMANDS, this scan can then OBSERVE.

Three scans over the shipped tree, each mapping to a house rule:

* :func:`scan_secrets` — credential material in source (house rule 4). Provider-shaped keys
  and private-key blocks are unambiguous; a secret-NAMED identifier assigned a string literal
  is graded by the literal's shape, so ``password = "hunter2"`` is a caveat and a 32-char
  random-looking ``SECRET_KEY`` is a finding.
* :func:`scan_dangerous_sinks` — code and queries built out of strings (house rule 5):
  ``eval``/``exec``/``new Function`` on a non-literal, ``os.system``/``shell=True``, and SQL
  assembled by f-string, concatenation, ``%`` or ``.format``.
* :func:`scan_web_injection` — untrusted text reaching a browser as markup (house rule 6):
  ``innerHTML``/``outerHTML``/``insertAdjacentHTML``/``document.write``/``dangerouslySetInnerHTML``
  fed anything that is not a static literal.

WHAT CAN SILENCE EACH CHECK (#1183's lesson, applied here before it cost anything). That
ticket's ``lint_stale_readme`` keyed on marker STRINGS that lived in the seed; a later edit
neutralised the seed text, the marker vanished from the shipped copy, and the lint went blind
to the one file it existed to catch — silently, for a week. A security lint fails the same way
but worse, because a lint that finds nothing is indistinguishable from a secure deliverable.
So, per check, the edit that would blind it and what stops it:

* **Secret NAMES** (``api_key``, ``password``, …) are a word list, and a word list is silenced
  by renaming the identifier. It is therefore NOT the only path to a secret finding:
  :func:`scan_entropy_literals` flags a long random-looking literal by its SHAPE, whatever it
  is assigned to, so a rename downgrades the finding rather than erasing it.
* **Placeholder words** (``example``, ``dummy``, …) DOWNGRADE a finding, which makes them the
  sharpest silencing vector in this module — a real key containing the substring "example"
  would read clean. They therefore cannot override entropy: a value that looks generated is
  graded on its shape, and the placeholder list only applies to values that do not.
* **Provider key shapes** (``AKIA…``, ``ghp_…``) are defined by AWS and GitHub, not by this
  repo, so no edit here can silence them. They can only be OUT-RUN — a credential in a format
  not listed. That is a coverage limit, named below, not a silencing vector.
* **Dangerous sinks** are detected from the Python AST where the file parses
  (:func:`scan_python_ast`), so ``eval`` is found as a call node rather than as the text
  ``eval(`` — reformatting, line-splitting and comments cannot hide it, and an f-string
  reaching ``.execute()`` is caught structurally without matching any SQL keyword. Regex
  remains the fallback for other languages and for files that do not parse.
* **Skipped directories** are a real blind spot: a secret living only in a skipped tree is
  invisible. Only true dependency and VCS trees are skipped outright. Build OUTPUT is read,
  because a secret in a bundle is a shipped secret — but only for CREDENTIALS, because
  grading a toolchain's output as authored code blames the coder for a vendored SDK asset.
  Both bounds are NAMED in the result status: the trees not read at all, and the count of
  files read under the narrower rule set. A bound the reader cannot see is a bound that
  becomes a false clean.

KNOWN LIMITS, stated because a named limit is usable and an unnamed one reads as coverage:
a credential in no listed provider format and with low apparent entropy (a short memorable
password under a renamed identifier) is not detected; ``.md`` files and build-output trees are
read for SECRETS only, because a credential in a README or a bundle is a shipped credential
while prose *about* SQL injection is not SQL injection and a compiler's output is not the
coder's code — so an injection sink the coder really did write into ``dist/`` is graded from
the source it was built from, and not a second time from the bundle; a dangerous builtin
reached through an object
(``window.eval(...)``) is not flagged, the price of not flagging every ``regex.exec()`` and
``db.exec()`` in idiomatic JavaScript; indirect sink access
(``getattr(builtins, "ev" + "al")``) defeats both the AST and the regex path; and this is a
lint over source text, so it reasons about constructs, never about reachability.

Two properties are load-bearing and are the reason this is not simply another craft lint:

* **FAIL-SOFT, NEVER FAIL-OPEN.** Every read is guarded and the whole scan is total, so an
  unreadable tree never sinks battery close. But a scan that could not run reports
  ``measured=False`` — "could not determine" — and the band treats that as a CAVEAT, never as
  a clean result. A security control that degrades silently is worse than none.
* **FINDINGS ARE REDACTED.** A finding names the rule, the file, and the line; matched
  credential material is MASKED before it reaches the sidecar or the scorecard evidence.
  Flagging a leaked secret must not copy it into a second artifact.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Pattern

from .constants import (
    EVIDENCE_VALUE_CAP,
    SEVERITY_HIGH,
    SEVERITY_INFO,
    SEVERITY_MEDIUM,
    SEVERITY_ORDER,
    clip_rule_list,
)

# ---------------------------------------------------------------------------
# Scan bounds (a battery-close scan is seconds; these are the ceilings that keep it so)
# ---------------------------------------------------------------------------

#: Files examined per repo. A deliverable far past this is not a hand-written project.
_MAX_FILES = 800
#: Bytes read per file (a generated data blob carries no house-rule signal past this).
_MAX_FILE_BYTES = 256 * 1024
#: Findings recorded. The band needs the worst severity, the operator needs examples —
#: neither needs an unbounded list, and the sidecar stays small. Past this point the scan
#: keeps going but records ONLY high-severity findings: a cap that could drop the one HIGH
#: sitting behind fifty INFO lines would quietly lower the band, which is the exact
#: fail-open this module exists to refuse.
_MAX_FINDINGS = 50
#: The hard ceiling once only HIGHs are being kept. A tree past this is pathological and the
#: status says the list is partial — the severity is right either way.
_MAX_HIGH_FINDINGS = 200
#: Characters of matched source kept in a finding detail (one line, then capped again on stamp).
_SNIPPET_CAP = 120

#: Extensions worth reading. Everything else in a delivered tree is an asset, not source.
_SOURCE_SUFFIXES: frozenset[str] = frozenset({
    ".py", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".vue", ".svelte",
    ".html", ".htm", ".ejs", ".hbs", ".php", ".rb", ".go", ".java", ".cs",
    ".json", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".env", ".sh", ".ps1", ".sql", ".md",
})

#: Directories never scanned at all — DEPENDENCY and VCS trees. These are not the coder's
#: authored work, they are not what the deliverable ships, and scanning them would drown every
#: real finding in third-party noise. Anything skipped is NAMED in the result status.
#:
#: ``vendor`` sits here rather than in the build-output tier below: Go and PHP vendor
#: directories are third-party DEPENDENCIES, the same category as ``node_modules``, and the
#: two are treated identically. Volume is why dependency trees are skipped outright instead of
#: read for credentials — a vendored tree can exhaust the per-repo file budget and starve the
#: coder's own source, which would be a worse fail-open than the one it closed.
_SKIP_DIRS: frozenset[str] = frozenset({
    "node_modules", "vendor", ".git", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", "venv", ".venv", "site-packages", ".tox", ".idea", ".vscode",
})

#: Build OUTPUT — read for CREDENTIALS ONLY, never for authored constructs.
#:
#: The middle tier, and it exists because both simpler answers are wrong. Skipping these trees
#: outright is a fail-open: a deliverable whose only credential sat in ``dist/`` scored band A
#: and reported CLEAN, which is why they came OFF :data:`_SKIP_DIRS`. But scanning them like
#: source grades the COMPILER'S output as the coder's work — the WinUI SDK bundles its own
#: ``map.html``, whose ``innerHTML = p.join("")`` forced band C on every winui deliverable
#: before a coder wrote a line, and told the operator his project "puts text straight into the
#: page as page-code" while pointing at a Microsoft file he cannot fix.
#:
#: The split follows the question each rule asks, the same asymmetry that keeps ``.md`` in the
#: secret scan and out of the sink scan. *Does this file carry a live key?* is about what
#: SHIPS, and a bundle ships — so the secret scan reads here. *Did the coder write this
#: construct?* is about AUTHORSHIP, and generated output was authored by a toolchain — so the
#: sink, entropy and web-injection rules do not.
#:
#: Measured over the real seeds and the 144-repo archive (53 source files inside these trees):
#: the secret scan contributes ZERO findings from build output, while entropy contributes 4
#: MEDIUM from XAML codegen and web-injection 2 HIGH from the vendored SDK asset. Keeping the
#: secret scan here costs nothing and keeps the fail-open closed.
#:
#: ``obj`` was on :data:`_SKIP_DIRS` as ".NET restore intermediates" and belongs here instead:
#: it is build output, exactly as a .NET ``bin`` tree is, and skipping one while reading the
#: other is incoherent. It also hid only ONE of the two copies of that SDK asset.
#:
#: ``bin`` is NOT on this list, because the name alone does not decide it — see
#: :data:`_DOTNET_OUTPUT_SEGMENT_RE`.
_BUILD_OUTPUT_DIRS: frozenset[str] = frozenset({
    "obj", "dist", "build", "out", "coverage", ".next", "target",
})

#: What makes a ``bin/`` tree BUILD OUTPUT rather than authored source: the segment beneath it.
#:
#: ``bin`` is the one name on either list that means opposite things in different ecosystems.
#: .NET writes compiler output under a configuration, architecture or target-framework segment
#: — ``bin/Debug/``, ``bin/x64/``, ``bin/Release/net8.0-windows10.0.19041.0/``. Node and Python
#: put a HAND-WRITTEN executable DIRECTLY in ``bin/``: the node-cli seed declares
#: ``"bin": {"app": "bin/cli.mjs"}`` in its ``package.json``, making that file the authored
#: entry point of every node-cli deliverable — and the single most likely file in a
#: command-line tool to carry argv handling, a shell invocation or an ``eval``.
#:
#: Classifying ``bin`` by NAME therefore stopped grading the one file most worth grading: a
#: planted ``bin/cli.js`` containing ``eval(process.argv[2])`` and a concatenated SQL query
#: scanned CLEAN at band A. That is the mirror of the fail-open that put build output back in
#: scope in the first place — secrets invisible in ``dist/`` then, sinks invisible in ``bin/``
#: now — so shape decides, not the name.
#:
#: Measured over the seed trees: 506 files nested under ``bin/x64/…`` (all .NET output) and
#: exactly one directly in ``bin/`` (the authored Node entry point). A corroborating signal
#: (a sibling ``*.csproj``) was considered and rejected: a discriminator that needs two facts
#: fails when one is absent, and the shape alone separates the measured population cleanly.
_DOTNET_OUTPUT_SEGMENT_RE: Pattern[str] = re.compile(
    r"^(?:debug|release|x64|x86|win32|arm|arm64|anycpu"
    r"|net\d+(?:\.\d+)*(?:-[\w.]+)?"
    r"|net(?:standard|coreapp)\d+(?:\.\d+)*)$", re.IGNORECASE)

#: Files never scanned: minified bundles and lockfiles are machine output — high-entropy
#: noise that would false-positive the secret scan on every run.
_SKIP_FILE_RE: Pattern[str] = re.compile(
    r"(\.min\.(js|css)$|^package-lock\.json$|^yarn\.lock$|^poetry\.lock$|"
    r"^pnpm-lock\.yaml$|^Cargo\.lock$|\.map$)", re.IGNORECASE)

#: A finding inside the test suite is demoted one level: test fixtures legitimately carry
#: dummy credentials and deliberately odd calls. Demoted, never dropped — a real key pasted
#: into a test is still a real key in the shipped tree.
_TEST_PATH_RE: Pattern[str] = re.compile(
    r"(^|[/\\])(tests?|spec|__tests__|fixtures?)([/\\]|$)|"
    r"(^|[/\\])(test_[^/\\]*|[^/\\]*_test|[^/\\]*\.(test|spec))\.[a-z]+$", re.IGNORECASE)

_DEMOTE: dict[str, str] = {
    SEVERITY_HIGH: SEVERITY_MEDIUM,
    SEVERITY_MEDIUM: SEVERITY_INFO,
    SEVERITY_INFO: SEVERITY_INFO,
}


# ---------------------------------------------------------------------------
# Rule ids (stable strings — the sidecar, the evidence stamp and the tests name these)
# ---------------------------------------------------------------------------

RULE_PRIVATE_KEY = "private-key-material"
RULE_PROVIDER_CREDENTIAL = "provider-credential"
RULE_CONNECTION_STRING = "connection-string-password"
RULE_HARDCODED_SECRET = "hardcoded-secret"
RULE_HIGH_ENTROPY_LITERAL = "generated-looking-literal"
RULE_CODE_FROM_STRING = "code-built-from-string"
RULE_SHELL_INVOCATION = "shell-invocation"
RULE_UNSAFE_DESERIALIZE = "unsafe-deserialization"
RULE_SQL_FROM_STRING = "sql-built-from-string"
RULE_HTML_INJECTION = "unescaped-html-sink"

#: What each rule means to a NON-CODER, in one sentence. The card renders these; the operator
#: is the reader who has to decide whether to rely on the deliverable.
RULE_PLAIN_LANGUAGE: dict[str, str] = {
    RULE_PRIVATE_KEY:
        "it has a private security key written directly into the code — that key should be "
        "treated as compromised and the code should read it from somewhere else.",
    RULE_PROVIDER_CREDENTIAL:
        "it has what looks like a real account key written directly into the code — worth "
        "removing (and changing that key) before you share or publish this.",
    RULE_CONNECTION_STRING:
        "it has a database address with the password written into it — anyone who reads the "
        "code can reach that database.",
    RULE_HARDCODED_SECRET:
        "it has a password or key typed directly into the code rather than kept separately — "
        "worth checking before you share or publish this.",
    RULE_HIGH_ENTROPY_LITERAL:
        "it has a long random-looking value written into the code, which is often a key or "
        "token left behind — worth a glance to confirm it is not one.",
    RULE_CODE_FROM_STRING:
        "it turns text into running instructions — if that text ever comes from someone else, "
        "they can make it do things it was never meant to do.",
    RULE_SHELL_INVOCATION:
        "it hands text to the operating system to run as a command — risky if any of that "
        "text is something a user typed.",
    RULE_UNSAFE_DESERIALIZE:
        "it rebuilds saved data in a way that can execute instructions hidden inside the "
        "file — only safe if the file can never come from anyone else.",
    RULE_SQL_FROM_STRING:
        "it builds database queries by pasting text together, which is the classic way data "
        "gets stolen or deleted by someone typing the right thing into a box.",
    RULE_HTML_INJECTION:
        "it puts text straight into the page as page-code, so anything typed in that looks "
        "like code could run in the browser.",
}


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SecurityFinding:
    """One deterministic security observation at a named file and line.

    ``detail`` is REDACTED source — matched credential material is masked before it is
    stored, so flagging a leaked secret never copies it into the audit's own artifacts."""

    rule: str
    severity: str
    path: str
    line: int
    detail: str

    def render(self) -> str:
        """The one-line human finding (the shape :meth:`SecurityResult.findings_lines` emits)."""
        return f"[{self.severity}] {self.rule} — {self.path}:{self.line}: {self.detail}"


@dataclass(frozen=True)
class SecurityResult:
    """The security scan of one delivered tree.

    ``measured`` is the honesty bit and the reason this type exists rather than a bare list:
    an empty ``findings`` tuple means "clean" ONLY when ``measured`` is True. When the tree
    could not be read, ``measured`` is False and ``status`` says why — the band and the card
    must render that as *could not determine*, never as clean. Callers asking "is this
    deliverable clean?" must use :meth:`is_clean`, which cannot answer yes unmeasured.

    The two fields are INDEPENDENT, and reading ``measured`` as a gate on ``findings`` is the
    error worth naming: a scan can be interrupted AFTER finding a live credential, and
    ``measured=False`` means "there may be more", never "disregard what was found". Every
    consumer must carry both facts — what was found, and that the looking did not finish."""

    findings: tuple[SecurityFinding, ...] = ()
    measured: bool = False
    status: str = "security scan did not run"
    files_scanned: int = 0
    #: True when the scan RAN but part of the tree it INTENDED to examine went unexamined —
    #: the file bound was hit, a file could not be read, a python file would not parse (so the
    #: AST tier never ran on it), or the walk was abandoned on the high-severity ceiling.
    #: A THIRD independent fact, on exactly the reasoning the docstring above gives for the
    #: first two: ``measured`` answers "did the looking HAPPEN", this answers "did the looking
    #: FINISH", and a bounded scan answers True to both.
    #:
    #: NOT set by deliberately excluded content — ``_present_skipped_dirs`` (.git, caches) and
    #: build output. Those were never in scope, and ``.git`` is present in every archived
    #: delivery measured, so counting them would make this true on every run and leave it
    #: carrying no information. The exclusions are disclosed in ``status`` regardless.
    #: An excluded region is not a shortfall; an intended region that went unread is.
    #:
    #: Before #1396 this fact existed only as English appended to ``status``, so any rendering
    #: that did not substring-match that English dropped it silently. ``summary()`` did, and
    #: ``summary()`` is the string that reaches the scorecard. The field exists so that a
    #: renderer written later cannot lose the caveat by simply not knowing to look for it —
    #: which is also why the card's helper takes the RESULT and derives the predicate itself
    #: rather than accepting a bool a caller can get wrong.
    coverage_partial: bool = False

    @property
    def worst_severity(self) -> Optional[str]:
        """The highest severity present, or ``None`` when there are no findings."""
        if not self.findings:
            return None
        return max((f.severity for f in self.findings), key=lambda s: SEVERITY_ORDER.get(s, 0))

    def at_or_above(self, severity: str) -> tuple[SecurityFinding, ...]:
        """Every finding at *severity* or worse (the band's input)."""
        floor = SEVERITY_ORDER.get(severity, 0)
        return tuple(f for f in self.findings if SEVERITY_ORDER.get(f.severity, 0) >= floor)

    def is_clean(self) -> bool:
        """True ONLY when the tree was actually scanned and nothing was found. An unmeasured
        scan is never clean — that is the fail-closed reading of a fail-soft control."""
        return self.measured and not self.findings

    def findings_lines(self) -> list[str]:
        """The human finding lines, worst first (the honest report)."""
        ordered = sorted(self.findings,
                         key=lambda f: (-SEVERITY_ORDER.get(f.severity, 0), f.path, f.line))
        return [f.render() for f in ordered]

    def summary(self) -> str:
        """A single capped line for the scorecard evidence stamp.

        An unfinished scan that nonetheless FOUND something states both halves. Reporting only
        "could-not-determine" dropped the findings out of the stamp while the KPI line went on
        counting them, so the two disagreed about the same run.

        A BOUNDED scan says so on BOTH branches (#1396). The prefix used to key off ``measured``
        alone, and a capped scan is ``measured=True`` — so the one combination that most needs
        the caveat, *ran fine and found nothing but did not look everywhere*, was the one
        combination that rendered as an unqualified "clean". The word "clean" is not used at
        all when coverage was partial: what was established is that nothing was found in the
        part that was reached, which is a different claim and is the one worth publishing."""
        if not self.measured and not self.findings:
            return f"could-not-determine: {self.status}"[:EVIDENCE_VALUE_CAP]
        # THE GUARD IS INLINED AT BOTH BRANCHES, not bound to a local name, and that is a
        # requirement rather than a style choice. `instrument_registry.guard_alias_reads`
        # refuses a local alias of a registered status, because the guard analysis matches on
        # the dotted PATH and `if incomplete:` is invisible to it. This function held exactly
        # such an alias until #1400 tightened that refusal to see compound boolean bindings,
        # and the first thing the tightened control convicted was this line.
        #
        # The duplication is the accepted cost: two reads two lines apart, against a guard no
        # analysis can follow. If the expression ever grows past this, the honest move is a
        # JUSTIFIED_COLLAPSES entry carrying an argument, never a quiet re-alias.
        if not self.findings:
            if not self.measured or self.coverage_partial:
                return (f"PARTIAL SCAN — nothing found in the {self.files_scanned} file(s) "
                        f"reached, coverage incomplete")[:EVIDENCE_VALUE_CAP]
            return f"clean ({self.files_scanned} files scanned)"[:EVIDENCE_VALUE_CAP]
        counts = {s: sum(1 for f in self.findings if f.severity == s)
                  for s in (SEVERITY_HIGH, SEVERITY_MEDIUM, SEVERITY_INFO)}
        rules = sorted({f.rule for f in self.at_or_above(SEVERITY_MEDIUM)})
        head = ", ".join(f"{n} {s}" for s, n in counts.items() if n)
        prefix = "PARTIAL SCAN — " if (not self.measured or self.coverage_partial) else ""
        # #1400: THE RULE LIST IS TRIMMED TO FIT AND SAYS WHEN IT TRIMMED. The line used to be
        # built whole and then sliced by [:EVIDENCE_VALUE_CAP], so a stamp with many distinct
        # rule ids simply lost its tail — and adding the "PARTIAL SCAN — " prefix made that
        # 15 characters likelier. A silently clipped list is this ticket family's own defect
        # committed by its own disclosure: the reader cannot tell a two-rule finding from a
        # nine-rule finding whose last seven fell off the end.
        #
        # The trimming itself now lives in constants.clip_rule_list, shared with
        # placeholder_prose, because the first version of this fix landed HERE and not on the
        # sibling — one implementation cannot drift the way two did.
        return clip_rule_list(f"{prefix}{head}: ", rules)


# ---------------------------------------------------------------------------
# Redaction (principle: never copy a secret into a second artifact)
# ---------------------------------------------------------------------------

#: Anything quoted that is long enough to be a credential gets masked in a stored detail.
_QUOTED_RE: Pattern[str] = re.compile(r"""(['"])([^'"]{4,})\1""")


def _mask(value: str) -> str:
    """Mask a matched credential: keep a 3-character prefix so a human can locate it in the
    file, replace the rest. ``"AKIAIOSFODNN7EXAMPLE"`` -> ``"AKI***(20 chars)"``."""
    v = str(value)
    return f"{v[:3]}***({len(v)} chars)" if len(v) > 6 else "***"


def _redact_line(text: str) -> str:
    """One line of source with every quoted literal masked — safe to store and to show."""
    flat = re.sub(r"\s+", " ", str(text)).strip()
    return _QUOTED_RE.sub(lambda m: f"{m.group(1)}{_mask(m.group(2))}{m.group(1)}", flat)[:_SNIPPET_CAP]


def _plain_line(text: str) -> str:
    """One line of source, whitespace-flattened and capped — for non-credential findings,
    where the matched code IS the useful detail and carries nothing to leak."""
    return re.sub(r"\s+", " ", str(text)).strip()[:_SNIPPET_CAP]


# ---------------------------------------------------------------------------
# Secret detection
# ---------------------------------------------------------------------------

#: Unambiguous credential shapes — a provider's own key format or a private-key header.
#: Each is specific enough that a match is a finding, not a heuristic.
_PROVIDER_PATTERNS: tuple[tuple[Pattern[str], str], ...] = (
    (re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY-----"),
     RULE_PRIVATE_KEY),
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), RULE_PROVIDER_CREDENTIAL),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"), RULE_PROVIDER_CREDENTIAL),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b"), RULE_PROVIDER_CREDENTIAL),
    (re.compile(r"\b[sr]k_live_[A-Za-z0-9]{16,}\b"), RULE_PROVIDER_CREDENTIAL),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), RULE_PROVIDER_CREDENTIAL),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"), RULE_PROVIDER_CREDENTIAL),
    (re.compile(r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://[^\s:@/\"']+"
                r":[^\s:@/\"']+@"), RULE_CONNECTION_STRING),
)

#: An identifier whose NAME says the value is a credential.
_SECRET_NAME_RE: Pattern[str] = re.compile(
    r"""\b(?P<name>pass(?:wor)?d|passwd|secret|secret_key|api[_-]?key|apikey|token|
        access[_-]?token|auth[_-]?token|refresh[_-]?token|private[_-]?key|client[_-]?secret|
        db[_-]?pass\w*|encryption[_-]?key)\b\s*[:=]\s*(?P<q>['"])(?P<value>[^'"]{4,})(?P=q)""",
    re.IGNORECASE | re.VERBOSE)

#: Values that are obviously NOT a credential: the placeholder vocabulary a coder writes when
#: it is deliberately deferring the real value. Matching one downgrades the finding to info.
_PLACEHOLDER_RE: Pattern[str] = re.compile(
    r"^\s*(|changeme|change[_-]?me|your[_-].*|<.*>|\{\{.*\}\}|\$\{.*\}|x{3,}|"
    r".*(example|placeholder|redacted|dummy|fake|sample|todo|none|null|undefined).*)\s*$",
    re.IGNORECASE)


def _mixes_digits_and_letters(value: str) -> bool:
    """Alphanumeric with BOTH digits and letters — the shape that separates a generated token
    from a long identifier.

    Counting character CLASSES was not enough: ``runtimeIdentifierGraphPath`` is 26
    alphanumeric characters across two classes (lower and upper) and was flagged as
    credential material. Every camelCase name in a JSON file looked like a key. Real tokens
    interleave digits; identifiers essentially never do."""
    v = str(value)
    return (v.isalnum()
            and any(c.isdigit() for c in v)
            and any(c.isalpha() for c in v))


def _looks_random(value: str) -> bool:
    """Does a literal look like generated credential material rather than a typed word?

    Two ways to qualify, and the second exists because the first missed real keys. Mixed
    punctuation plus three classes catches the obvious case; but a 32-character run of
    lowercase and digits with no separators — the shape of most hex and base32 keys — carries
    only two classes and was slipping through into the placeholder branch. Requiring
    ALPHANUMERIC-ONLY for the two-class path is what keeps ``"your-api-key-goes-here"``
    (separators, one class) out while letting a real key in."""
    if len(value) < 20:
        return False
    classes = sum(bool(re.search(p, value)) for p in (r"[a-z]", r"[A-Z]", r"[0-9]", r"[^A-Za-z0-9]"))
    if classes >= 3:
        return True
    return len(value) >= 24 and _mixes_digits_and_letters(value)


def scan_secrets(rel_path: str, text: str) -> list[SecurityFinding]:
    """Credential material in one file (house rule 4). Matched values are masked in the
    stored detail — a finding must never become the second place the secret lives."""
    out: list[SecurityFinding] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if len(line) > 4096:  # a minified/one-line blob carries no reviewable signal
            continue
        provider_hit = False
        for pattern, rule in _PROVIDER_PATTERNS:
            if pattern.search(line):
                out.append(SecurityFinding(rule, SEVERITY_HIGH, rel_path, lineno,
                                           _redact_line(line)))
                provider_hit = True
                break
        if provider_hit:
            # The provider pattern already named this line at its sharpest. Running the
            # name-based rule too would report one leaked key twice and inflate every count
            # downstream of it.
            continue
        for m in _SECRET_NAME_RE.finditer(line):
            value = m.group("value")
            # ENTROPY OUTRANKS THE WORD LIST, and the order here is the whole point. Checking
            # the placeholder list first let a real 32-character key containing the substring
            # "example" grade INFO and band A — the word list silencing the finding from
            # inside the secret's own value. A value that looks generated is graded on its
            # shape; the placeholder vocabulary only speaks for values that do not.
            if _looks_random(value):
                severity = SEVERITY_HIGH
            elif _PLACEHOLDER_RE.match(value):
                severity = SEVERITY_INFO
            else:
                severity = SEVERITY_MEDIUM
            out.append(SecurityFinding(
                RULE_HARDCODED_SECRET, severity, rel_path, lineno,
                f"{m.group('name')} assigned a literal — {_redact_line(line)}"))
    return out


#: A literal long and mixed enough to look GENERATED rather than typed. Deliberately stricter
#: than :func:`_looks_random`, because this rule fires with no identifier name to corroborate
#: it — shape is the only evidence, so the bar is higher.
_ENTROPY_MIN_LEN = 24
#: Shapes that are long and mixed but routinely benign in a small project: a UUID, a path, a
#: URL, a data URI, a dotted identifier.
#:
#: A bare hex run was on this list and has been REMOVED. Excluding it as "probably a digest"
#: meant a 32-character hex key under an unrecognised identifier name was invisible to BOTH
#: the name rule and this one — the exact renamed-secret hole this function exists to close.
#: A hash constant now costs one MEDIUM caveat, which is the right side of that trade.
_BENIGN_SHAPE_RE: Pattern[str] = re.compile(
    r"^(?:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    r"|data:[^,]*,.*|[A-Za-z]+://.*|[./\\][^\s]*|[\w.]+\.[\w.]+)$")


def _is_high_entropy_literal(value: str) -> bool:
    """Does this literal look like generated credential material on SHAPE ALONE?

    The name-independent path, and the reason renaming ``API_KEY`` to ``SVC_CRED`` can no
    longer erase a finding. Conservative by construction: the bar is length, an interleaving
    of digits and letters (a separator means a phrase; all-letters means an identifier), and
    none of the benign long-string shapes a small project actually contains."""
    v = str(value)
    if len(v) < _ENTROPY_MIN_LEN or not _mixes_digits_and_letters(v):
        return False
    return not _BENIGN_SHAPE_RE.match(v)


#: Any quoted literal long enough to be worth shape-testing.
_LONG_LITERAL_RE: Pattern[str] = re.compile(r"""(['"`])([^'"`\s]{%d,})\1""" % _ENTROPY_MIN_LEN)


def scan_entropy_literals(rel_path: str, text: str) -> list[SecurityFinding]:
    """Long, generated-looking string literals, WHATEVER they are assigned to.

    The structural counterpart to :func:`scan_secrets`'s identifier-name list. A word list is
    silenced by a rename; a shape test is not, so a secret under an unrecognised name goes
    from "clean" to "flagged" rather than from "clean" to "clean".

    Graded MEDIUM, not HIGH, on purpose: with no name and no provider format to corroborate
    it, this rule reasons only from shape, and a band C the operator cannot act on costs more
    than a caveat he can. A literal that IS provider-shaped is already HIGH by another rule."""
    out: list[SecurityFinding] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if len(line) > 4096:
            continue
        for m in _LONG_LITERAL_RE.finditer(line):
            if _is_high_entropy_literal(m.group(2)):
                out.append(SecurityFinding(
                    RULE_HIGH_ENTROPY_LITERAL, SEVERITY_MEDIUM, rel_path, lineno,
                    f"a {len(m.group(2))}-character generated-looking literal — "
                    f"{_redact_line(line)}"))
                break  # one shape finding per line is enough to earn the look
    return out


# ---------------------------------------------------------------------------
# Dangerous sinks
# ---------------------------------------------------------------------------

#: ``eval``/``exec``/``new Function`` — the direct text-to-code sinks. A literal-only argument
#: is a smell rather than a hole, so the argument shape grades the severity. A DOTTED match is
#: rejected by :func:`_is_method_access` below, not by this pattern.
_CODE_SINK_RE: Pattern[str] = re.compile(
    r"\b(?P<sink>eval|exec|new\s+Function)\s*\(\s*(?P<arg>.{0,60})", re.DOTALL)


def _is_method_access(line: str, start: int) -> bool:
    """Is the name at *start* reached through a dot rather than called as a bare name?

    ``exec`` is a method name in ordinary, safe code — ``/re/.exec(s)`` is the JavaScript
    regular-expression API, ``db.exec(sql)`` is better-sqlite3, ``cursor.exec(...)`` is a
    database handle — and flagging those as text-to-code sinks graded every clean web
    deliverable band C. Only the BARE builtin executes text, so the dot decides.

    The test is written here rather than as a lookbehind because Python's lookbehind is
    fixed-width and the dot is not adjacent in a chained call split across lines
    (``builder\\n  .exec(sql)``), where the dot leads its own line."""
    return line[:start].rstrip().endswith(".")


#: Shell invocation. ``shell=True`` is the flag that turns an argv list into a command line.
_SHELL_SINK_RE: Pattern[str] = re.compile(
    r"\b(?:os\.system|os\.popen|commands\.getoutput)\s*\(\s*(?P<arg>.{0,60})|"
    r"\bshell\s*=\s*True\b|"
    r"\bchild_process\s*\.\s*exec\s*\(\s*(?P<jsarg>.{0,60})", re.DOTALL)

_DESERIALIZE_RE: Pattern[str] = re.compile(
    r"\bpickle\s*\.\s*loads?\s*\(|\bmarshal\s*\.\s*loads?\s*\(|"
    r"\byaml\s*\.\s*load\s*\((?![^)]*(?:Safe|safe_))")

#: A SQL statement built by interpolation. Requiring BOTH a statement verb and a clause
#: keyword keeps ordinary prose ("Created 5 entries") out of the results.
_SQL_VERB = r"(?:SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE)"
_SQL_CLAUSE = r"(?:FROM|INTO|SET|VALUES|WHERE|TABLE|JOIN)"
_SQL_FSTRING_RE: Pattern[str] = re.compile(
    rf"""[fF](['"]).*?\b{_SQL_VERB}\b.*?\b{_SQL_CLAUSE}\b.*?\{{.*?\1""",
    re.IGNORECASE | re.DOTALL)
_SQL_TEMPLATE_RE: Pattern[str] = re.compile(
    rf"`[^`]*?\b{_SQL_VERB}\b[^`]*?\b{_SQL_CLAUSE}\b[^`]*?\$\{{", re.IGNORECASE | re.DOTALL)
_SQL_CONCAT_RE: Pattern[str] = re.compile(
    rf"""(['"])[^'"]*?\b{_SQL_VERB}\b[^'"]*?\b{_SQL_CLAUSE}\b[^'"]*?\1\s*(?:\+|%|\.format\()""",
    re.IGNORECASE)

#: An argument that is a self-contained literal cannot carry untrusted input.
_LITERAL_ARG_RE: Pattern[str] = re.compile(r"""^\s*(?:(['"])(?:(?!\1).)*\1|\d+(?:\.\d+)?)\s*[,)]""")


def _arg_is_literal(arg: str) -> bool:
    """Is the captured first argument a plain literal (no name, no call, no interpolation)?"""
    return bool(_LITERAL_ARG_RE.match(arg or "")) and "${" not in (arg or "")


def scan_dangerous_sinks(rel_path: str, text: str) -> list[SecurityFinding]:
    """Code and queries assembled out of strings (house rule 5).

    Applied to EXECUTABLE source only. :func:`scan_repo` does not route ``.md`` here, on the
    same reasoning that already excludes it from :func:`scan_entropy_literals` and
    :func:`scan_web_injection`: markdown is documentation, and prose about an unsafe construct
    is not the construct. A rulebook that spells out ``Never f"SELECT ... WHERE id =
    {user_id}"`` is the house rule itself, and reading it as three HIGH findings banded every
    deliverable C over its own instructions. :func:`scan_secrets` DOES still read markdown,
    because that is a different question — a credential pasted into a README ships as surely
    as one in a config file, whether or not the file executes."""
    out: list[SecurityFinding] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if len(line) > 4096:
            continue
        stripped = line.lstrip()
        if stripped.startswith(("#", "//", "*", "<!--")):
            continue  # a commented-out sink is not a reachable sink
        for m in _CODE_SINK_RE.finditer(line):
            if _is_method_access(line, m.start("sink")):
                continue  # `re.exec(s)`, `db.exec(sql)` — a method, not the bare builtin
            severity = SEVERITY_INFO if _arg_is_literal(m.group("arg")) else SEVERITY_HIGH
            out.append(SecurityFinding(RULE_CODE_FROM_STRING, severity, rel_path, lineno,
                                       _plain_line(line)))
        for m in _SHELL_SINK_RE.finditer(line):
            arg = m.group("arg") or m.group("jsarg") or ""
            severity = SEVERITY_MEDIUM if (arg and _arg_is_literal(arg)) else SEVERITY_HIGH
            out.append(SecurityFinding(RULE_SHELL_INVOCATION, severity, rel_path, lineno,
                                       _plain_line(line)))
        if _DESERIALIZE_RE.search(line):
            out.append(SecurityFinding(RULE_UNSAFE_DESERIALIZE, SEVERITY_MEDIUM, rel_path,
                                       lineno, _plain_line(line)))
        if (_SQL_FSTRING_RE.search(line) or _SQL_TEMPLATE_RE.search(line)
                or _SQL_CONCAT_RE.search(line)):
            out.append(SecurityFinding(RULE_SQL_FROM_STRING, SEVERITY_HIGH, rel_path, lineno,
                                       _plain_line(line)))
    return out


# ---------------------------------------------------------------------------
# Structural (AST) detection for Python — the path a rename or a reformat cannot silence
# ---------------------------------------------------------------------------

#: Builtins that execute text as code.
_AST_CODE_SINKS: frozenset[str] = frozenset({"eval", "exec", "compile"})
#: ``os``/``subprocess`` attributes that hand text to a shell.
_AST_SHELL_ATTRS: frozenset[str] = frozenset({"system", "popen"})
#: Methods whose first argument is a query. An f-string reaching one of these is SQL built by
#: interpolation, detectable WITHOUT matching any SQL keyword — which is the point: the verb
#: list in the regex path is a word list, and this one is not.
_AST_QUERY_METHODS: frozenset[str] = frozenset({"execute", "executemany", "executescript"})
_AST_DESERIALIZE: frozenset[str] = frozenset({"loads", "load"})


def _ast_arg_is_literal(node: "ast.AST") -> bool:
    """Is this argument a self-contained constant (so it cannot carry untrusted input)?"""
    return isinstance(node, ast.Constant)


def scan_python_ast(rel_path: str, text: str) -> Optional[list[SecurityFinding]]:
    """Dangerous constructs read from the Python syntax tree, or ``None`` when the file does
    not parse (the caller then falls back to the regex path — fail-soft, never fail-silent).

    This exists because a regex on ``eval(`` is a string match on source text, and #1183's
    lesson is that a control keyed on a string can be edited into silence. A call node is a
    structural fact: reformatting, splitting the call across lines, or burying it in an
    expression cannot hide it, and ``eval`` appearing inside a comment or a docstring cannot
    fake it. It does NOT defeat deliberate indirection (``getattr(builtins, "ev" + "al")``),
    which is named as a known limit in this module's docstring rather than left implicit."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return None

    out: list[SecurityFinding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        first = node.args[0] if node.args else None
        line = getattr(node, "lineno", 0)

        if isinstance(func, ast.Name) and func.id in _AST_CODE_SINKS:
            severity = SEVERITY_INFO if (first is not None and _ast_arg_is_literal(first)) \
                else SEVERITY_HIGH
            out.append(SecurityFinding(RULE_CODE_FROM_STRING, severity, rel_path, line,
                                       f"{func.id}() called on a "
                                       f"{'literal' if severity == SEVERITY_INFO else 'runtime value'}"))

        if isinstance(func, ast.Attribute):
            if func.attr in _AST_SHELL_ATTRS and isinstance(func.value, ast.Name) \
                    and func.value.id == "os":
                severity = SEVERITY_MEDIUM if (first is not None and _ast_arg_is_literal(first)) \
                    else SEVERITY_HIGH
                out.append(SecurityFinding(RULE_SHELL_INVOCATION, severity, rel_path, line,
                                           f"os.{func.attr}() builds a shell command"))
            if func.attr in _AST_QUERY_METHODS and isinstance(first, ast.JoinedStr):
                # A JoinedStr IS an f-string. No SQL vocabulary consulted, so an unusual verb
                # or a query in another dialect is caught just the same.
                out.append(SecurityFinding(RULE_SQL_FROM_STRING, SEVERITY_HIGH, rel_path, line,
                                           f".{func.attr}() called with an f-string — the "
                                           f"query is built by interpolation"))
            if func.attr in _AST_QUERY_METHODS and isinstance(first, ast.BinOp) \
                    and isinstance(first.op, (ast.Add, ast.Mod)):
                out.append(SecurityFinding(RULE_SQL_FROM_STRING, SEVERITY_HIGH, rel_path, line,
                                           f".{func.attr}() called with a concatenated or "
                                           f"%-formatted string"))
            if func.attr in _AST_DESERIALIZE and isinstance(func.value, ast.Name) \
                    and func.value.id in {"pickle", "marshal"}:
                out.append(SecurityFinding(RULE_UNSAFE_DESERIALIZE, SEVERITY_MEDIUM, rel_path,
                                           line, f"{func.value.id}.{func.attr}() rebuilds "
                                                 f"objects from a serialized stream"))

        for kw in node.keywords:
            if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                out.append(SecurityFinding(RULE_SHELL_INVOCATION, SEVERITY_HIGH, rel_path, line,
                                           "shell=True passes the command through a shell"))
    return out


# ---------------------------------------------------------------------------
# Web injection
# ---------------------------------------------------------------------------

#: The DOM sinks that interpret their input as markup rather than text.
#:
#: ``(?!=)`` is what makes this an ASSIGNMENT rule rather than an ``=`` rule. Without it,
#: ``el.innerHTML === previous`` matched at the first ``=``, leaving an ``rhs`` of
#: ``"== previous…"`` that is not a static literal — so a read-only comparison graded as an
#: injection sink. (``!==`` never matched, because ``!`` is not ``=``; that asymmetry was the
#: tell.) ``+=`` is still an assignment and still matches.
_HTML_ASSIGN_RE: Pattern[str] = re.compile(
    r"\.\s*(?P<sink>innerHTML|outerHTML)\s*(?:\+)?=(?!=)\s*(?P<rhs>.+)$")
_HTML_CALL_RE: Pattern[str] = re.compile(
    r"\b(?P<sink>insertAdjacentHTML|document\s*\.\s*write(?:ln)?)\s*\(\s*(?P<rhs>.+)$")
_JQUERY_HTML_RE: Pattern[str] = re.compile(r"\)\s*\.\s*html\s*\(\s*(?P<rhs>[^)]+)\)")
_REACT_HTML_RE: Pattern[str] = re.compile(r"\bdangerouslySetInnerHTML\b")

#: A right-hand side that is one self-contained literal with no interpolation is static
#: markup the coder wrote — not a sink for anything a user typed.
_STATIC_RHS_RE: Pattern[str] = re.compile(
    r"""^\s*(?:(['"])(?:(?!\1).)*\1|`[^`$]*`)\s*;?\s*$""")


def _rhs_is_static(rhs: str) -> bool:
    """Is this assignment's value a fixed literal (safe) rather than built at runtime?"""
    return bool(_STATIC_RHS_RE.match((rhs or "").strip()))


def scan_web_injection(rel_path: str, text: str) -> list[SecurityFinding]:
    """Untrusted text reaching the browser as markup (house rule 6).

    Scanned for every tree that contains web source, not only a declared ``node-web`` card:
    a page shipped inside a library is still a page, and the surface label is the card's
    claim rather than an observation of what was delivered."""
    out: list[SecurityFinding] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if len(line) > 4096:
            continue
        stripped = line.lstrip()
        if stripped.startswith(("//", "*", "<!--", "#")):
            continue
        for pattern in (_HTML_ASSIGN_RE, _HTML_CALL_RE, _JQUERY_HTML_RE):
            m = pattern.search(line)
            if m and not _rhs_is_static(m.group("rhs")):
                out.append(SecurityFinding(RULE_HTML_INJECTION, SEVERITY_HIGH, rel_path,
                                           lineno, _plain_line(line)))
        if _REACT_HTML_RE.search(line):
            out.append(SecurityFinding(RULE_HTML_INJECTION, SEVERITY_HIGH, rel_path, lineno,
                                       _plain_line(line)))
    return out


# ---------------------------------------------------------------------------
# The repo scan
# ---------------------------------------------------------------------------


def _dedupe(findings: list[SecurityFinding]) -> list[SecurityFinding]:
    """Collapse findings that two detectors reported at the same rule, file and line, keeping
    the SHARPEST severity. The AST and regex paths overlap on purpose; the operator should see
    one ``eval`` at line 12, not the same one twice because two detectors agreed."""
    best: dict[tuple[str, str, int], SecurityFinding] = {}
    for f in findings:
        key = (f.rule, f.path, f.line)
        current = best.get(key)
        if current is None or SEVERITY_ORDER.get(f.severity, 0) > SEVERITY_ORDER.get(current.severity, 0):
            best[key] = f
    return list(best.values())


def _is_build_output(rel_path: str) -> bool:
    """Is this file the TOOLCHAIN's output rather than something the coder wrote?

    Decides which rules apply, never whether the file is read at all — see
    :data:`_BUILD_OUTPUT_DIRS` for why those are different questions.

    Most names decide themselves. ``bin`` does not, and is classified by the segment BENEATH
    it (:data:`_DOTNET_OUTPUT_SEGMENT_RE`) — ``bin/x64/Debug/…`` is a compiler's output,
    ``bin/cli.mjs`` is a hand-written command-line entry point."""
    parts = str(rel_path).replace("\\", "/").split("/")[:-1]  # directory components only
    for index, part in enumerate(parts):
        if part in _BUILD_OUTPUT_DIRS:
            return True
        if part.lower() == "bin":
            below = parts[index + 1] if index + 1 < len(parts) else ""
            if _DOTNET_OUTPUT_SEGMENT_RE.match(below):
                return True
    return False


def _is_skipped(path: Path, root: Path) -> bool:
    """Does *path* lie inside a skipped directory WITHIN the delivered tree?

    Compared RELATIVE to *root*, because ``path.parts`` carries every ancestor of the repo as
    well: a deliverable checked out under ``…/obj/``, ``…/node_modules/`` or a ``venv`` — none
    of which are part of what was delivered — matched on an ancestor and skipped the entire
    tree, so a scan that reached nothing reported ``files_scanned=0``. Fail-soft rather than
    fail-open, but the credential still went unreported, and where a tree happens to live says
    nothing about what is in it."""
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    return any(part in _SKIP_DIRS for part in relative.parts)


def _present_skipped_dirs(root: Path) -> list[str]:
    """The skipped directories that ACTUALLY EXIST in this tree, so the status can name the
    blind spot instead of leaving the reader to assume 'clean' meant 'everywhere'.

    Relative to *root* for the reason :func:`_is_skipped` gives — the status must name what
    was not scanned INSIDE the deliverable, never a directory the deliverable merely sits in."""
    found: set[str] = set()
    try:
        for path in root.rglob("*"):
            try:
                parts = set(path.relative_to(root).parts)
            except ValueError:
                continue
            found |= parts & _SKIP_DIRS
            if len(found) >= len(_SKIP_DIRS):
                break
    except OSError:
        return sorted(found)
    return sorted(found)


def _iter_source_files(root: Path) -> Iterable[Path]:
    """Every scannable source file under *root*, dependency and build trees excluded.

    YIELDS ONE PAST THE BOUND ON PURPOSE (#1400). `scanned >= _MAX_FILES` cannot distinguish
    "the walk was cut short" from "the tree happens to hold exactly that many", so a repo of
    exactly _MAX_FILES files claimed partial coverage on a scan that was complete. Handing the
    caller one extra item makes the distinction decidable without a second walk: the extra
    item exists only when there was more to see.

    Kept a GENERATOR rather than returning ``(files, truncated)`` — which is how the sibling
    ``layer1._walk_python`` reports the same fact — because two tests monkeypatch this with
    their own generators to simulate a tree that dies mid-walk, and changing the shape here
    would break a fault-injection path that has nothing to do with counting."""
    count = 0
    for path in sorted(root.rglob("*")):
        if count > _MAX_FILES:
            return
        try:
            if not path.is_file():
                continue
        except OSError:
            continue
        if _is_skipped(path, root):
            continue
        if path.suffix.lower() not in _SOURCE_SUFFIXES and not path.name.startswith(".env"):
            continue
        if _SKIP_FILE_RE.search(path.name):
            continue
        count += 1
        yield path


def scan_repo(repo: Optional[Path], surface: str = "") -> SecurityResult:
    """Scan one delivered tree and return the honest :class:`SecurityResult`.

    *surface* is accepted for signature parity with the package's other injected checks and
    is recorded in the status line; it never gates WHICH scans run, because the surface is
    the card's claim about the deliverable rather than a reading of it — a tree containing
    web source gets the web scan whatever the card said it would build.

    Total by construction. A missing or unreadable tree yields ``measured=False`` with a
    status naming the reason; it never yields an empty-and-clean result."""
    if repo is None:
        return SecurityResult(status="no delivered tree to scan (repo not resolved)")
    root = Path(repo)
    try:
        if not root.is_dir():
            return SecurityResult(status=f"delivered tree not found at {root.name}")
    except OSError as exc:
        return SecurityResult(status=f"delivered tree unreadable ({type(exc).__name__})")

    findings: list[SecurityFinding] = []
    scanned = 0
    unreadable = 0
    walk_abandoned = False
    truncated_reads = 0
    truncated = False
    unparsed_python = 0
    build_output_files = 0
    skipped_dirs = _present_skipped_dirs(root)
    file_cap_hit = False
    try:
        for seen, path in enumerate(_iter_source_files(root)):
            if seen >= _MAX_FILES:
                # #1400: the iterator hands us ONE past the bound, so arriving here proves
                # there was more tree to walk — as opposed to `scanned >= _MAX_FILES`, which
                # is also true of a repo holding exactly that many and nothing more.
                file_cap_hit = True
                break
            try:
                # #1395: the slice is the whole defect. The file is read in full and then cut
                # to _MAX_FILE_BYTES, so everything past the cut is never scanned — and nothing
                # recorded that it happened. A credential below the cut in a large bundled file
                # was simply not looked for, and the result said "clean".
                #
                # NOTE the units, because the constant's name is wrong and a reader will trust
                # it: `read_text` returns str, so this slices CHARACTERS, not bytes. On non-ASCII
                # source the real byte ceiling is higher than 256 KiB. Renaming the constant is
                # left alone deliberately — it is referenced by name in tests and tickets, and a
                # rename inside a fix is how a fix becomes hard to review.
                raw = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                unreadable += 1
                continue
            text = raw[:_MAX_FILE_BYTES]
            if len(raw) > _MAX_FILE_BYTES:
                truncated_reads += 1
            try:
                rel = str(path.relative_to(root)).replace("\\", "/")
            except ValueError:
                rel = path.name
            scanned += 1
            suffix = path.suffix.lower()
            # THE SECRET SCAN RUNS ON EVERYTHING READ. It asks what the deliverable SHIPS, and
            # a bundle ships, a README ships, a generated config ships. Every rule below asks
            # the different question of what the CODER WROTE, and each is gated accordingly.
            raw = scan_secrets(rel, text)
            if _is_build_output(rel):
                # Compiler output, vendored SDK assets, XAML codegen. The coder authored none
                # of it and cannot fix any of it, so an authored-construct finding here names
                # the wrong person: the WinUI SDK's own bundled map.html banded every winui
                # deliverable C before a coder wrote a line. Credentials above still count.
                build_output_files += 1
            else:
                if suffix != ".md":
                    # Documentation routinely carries long tokens that are examples, not
                    # secrets; provider-shaped keys in a README are still caught above.
                    raw += scan_entropy_literals(rel, text)
                    # Documentation is not executable, and the rulebook shipped in every
                    # deliverable spells out the anti-patterns this scan hunts. Reading it as
                    # source turned the house rules themselves into HIGH findings and banded
                    # every deliverable C over its own instructions.
                    #
                    # BOTH detectors, unioned — not one or the other. The AST sees constructs
                    # the regex cannot (an f-string reaching .execute() with no SQL keyword in
                    # it); the regex sees constructs the AST cannot (an f-string BOUND TO A
                    # VARIABLE and executed a line later, which the AST reads only as a Name).
                    # Running AST alone measurably lost that second case.
                    raw += scan_dangerous_sinks(rel, text)
                if suffix == ".py":
                    structural = scan_python_ast(rel, text)
                    if structural is None:
                        unparsed_python += 1  # unparseable: regex above is the whole coverage
                    else:
                        raw += structural
                if suffix not in {".py", ".sql", ".md", ".sh", ".ps1"}:
                    raw += scan_web_injection(rel, text)
            raw = _dedupe(raw)
            if _TEST_PATH_RE.search(rel):
                raw = [SecurityFinding(f.rule, _DEMOTE.get(f.severity, f.severity),
                                       f.path, f.line, f.detail) for f in raw]
            if len(findings) < _MAX_FINDINGS:
                findings.extend(raw)
            else:
                # Past the cap the list is no longer a full record, so it becomes a severity
                # record: keep every HIGH so the band and the worst-severity read stay true,
                # and drop the rest rather than let a truncation decide the band.
                truncated = True
                findings.extend(f for f in raw if f.severity == SEVERITY_HIGH)
                if len(findings) >= _MAX_HIGH_FINDINGS:
                    # ABANDONS THE WALK — every remaining file goes unexamined. Distinct from
                    # `truncated` above, which is partial RECORDING of a completed look; this
                    # is partial COVERAGE and must reach the reader as such. Measured on a
                    # real 430-file tree with findings front-loaded: the walk stopped at 10
                    # files, 97.7% of the tree unexamined, and the result rendered as a
                    # finished search on both the stamp and the card.
                    walk_abandoned = True
                    break
    except OSError as exc:
        # A tree that became unwalkable mid-scan: keep what was found, but the result is
        # explicitly PARTIAL — an interrupted scan must not read as a clean one.
        return SecurityResult(tuple(findings), measured=False,
                              status=f"scan interrupted after {scanned} files "
                                     f"({type(exc).__name__})", files_scanned=scanned)

    if scanned == 0:
        return SecurityResult(status=f"no scannable source found in {root.name}")
    status = f"scanned {scanned} file(s)" + (f", {unreadable} unreadable" if unreadable else "")
    if skipped_dirs:
        # The blind spot, named. A secret living only in a skipped tree is invisible to this
        # scan, so the reader is told which trees were not looked at rather than being left
        # to infer that "clean" meant "everywhere".
        status += f", NOT scanned: {'/, '.join(skipped_dirs)}/"
    if build_output_files:
        # The partial bound, named on the same principle as the skipped trees above: these
        # files WERE read, but only for credentials. A reader told "clean" is entitled to
        # know which rules were not applied to which part of the tree.
        status += (f", {build_output_files} build-output file(s) read for credentials only "
                   f"(not graded as authored code)")
    if unparsed_python:
        status += f", {unparsed_python} python file(s) did not parse (regex fallback used)"
    if file_cap_hit:
        # Partial COVERAGE, unlike the finding cap below which is partial RECORDING. Both are
        # named in the status for the same reason: a bound the reader cannot see is a bound
        # that turns into a false clean.
        status += f", file list capped at {_MAX_FILES} (coverage is partial)"
    if truncated:
        status += f", finding list capped at {_MAX_FINDINGS} (high-severity findings kept in full)"
    if truncated_reads:
        status += (f", {truncated_reads} file(s) read only in part (first {_MAX_FILE_BYTES} "
                   f"characters scanned; the rest was never examined)")
    if walk_abandoned:
        status += (f", scan ABANDONED after {_MAX_HIGH_FINDINGS} high-severity findings — the "
                   f"rest of the tree was never examined")
    if surface:
        status += f" [surface: {surface}]"
    return SecurityResult(
        tuple(findings), measured=True, status=status, files_scanned=scanned,
        # EVERY shortfall that means "part of the tree was not examined". Each disjunct is the
        # same variable that writes its own sentence into `status` above, so the flag and the
        # prose cannot drift apart.
        #
        # `unreadable` is in here for a specific reason: `scanned` counts only SUCCESSFUL reads,
        # so an unreadable file SHRINKS the counter and can hold `scanned >= _MAX_FILES` false
        # on a walk that really was truncated. Keying solely on the bound left the fact
        # droppable by the very files that prove it.
        #
        # DELIBERATELY ABSENT: `skipped_dirs` and `build_output_files`. Both are content that
        # was never in scope — .git and the caches are not authored code, build output is not
        # graded as authored code — and `.git` is present in every archived delivery measured
        # (183 of 183), so counting them would make the flag true on every run and therefore
        # worthless. Both are still NAMED in `status`; a disclosed exclusion is not a shortfall.
        coverage_partial=bool(file_cap_hit or unreadable or unparsed_python
                              or walk_abandoned or truncated_reads),
    )
