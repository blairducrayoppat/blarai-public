"""Publish a finished research dataset directory to the public Hugging Face dataset repo.

Subcommands (all deterministic, fail-closed; exit 0 only when every check passed):

* ``preflight --dir D``   scan every file in D for identity leaks, generated text, oversize files,
                          non-UTF-8 bytes and absolute local paths.
* ``card-check --readme P``  the dataset card carries the sections a community-grade study needs.
* ``plan --dir D --config NAME --path-in-repo P``  dry run: files, the exact upload command, the
                          card front-matter lines the config needs. Touches nothing.
* ``upload ...``          preflight, then ``hf upload``; refuses on any preflight hit.
* ``verify ...``          compares the remote file listing (names and sizes) to the local dir.

The Hugging Face CLI is ``hf.exe`` only (path in ``HF_EXE`` or ``DEFAULT_HF_EXE``). It is never
installed or substituted here. There is no token option: authentication is the CLI's own login state.
Free-text arguments (--message, --path-in-repo, --config) are validated against an allowlist before any
subprocess runs, and the hf positionals follow a literal ``--``. Preflight additionally refuses
credential and e-mail shapes anywhere in the tree: in file contents, in file names, and in the decoded
form of every JSON string (an escaped ``\u0040`` does not hide an address).

Generated text is refused by deny-by-default rules, not by key name alone: a bare JSON string, a list
of strings and a nested object are all walked; a string over ``FREE_TEXT_MAX`` chars is refused under any key
outside ``AUTHORED_NOTE_KEYS``; a CSV may carry only ``KNOWN_CSV_COLUMNS``; only ``ALLOWED_SUFFIXES`` are
accepted at all; prose files other than the root README.md are capped line by line and in total size. JSON keys are
length-capped, CSV cells are checked per column (numeric, hash or short id) and extra cells beyond the header are
refused, and a per-file budget bounds the total free text so chunking cannot evade the per-string caps. Honest
limit: a string under ``FREE_TEXT_MAX`` chars under an unlisted key cannot be told from an id or a label, and the
budgets bound, not eliminate, what chunking can carry. The commit message, config name and path-in-repo are
scanned for identity, e-mail and credential shapes before any subprocess runs.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = "blairducrayoppat/openvino-arc140v-lunarlake"
DEFAULT_HF_EXE = str(Path.home() / ".local" / "bin" / "hf.exe")
DEFAULT_MAX_BYTES = 50 * 1024 * 1024

# Same bound as scripts/build_phase1_dataset.py SHORT_LABEL_MAX: a verdict label, never a generation.
SHORT_LABEL_MAX = 24

# Identity strings that must never reach the public repo (matched case-insensitively). The values of the
# USERNAME / COMPUTERNAME environment variables of the machine running the preflight are added at call time.
DENY_STRINGS = ("mrbla", "NORTHSTAR100")
_ENV_IDENTITY_VARS = ("USERNAME", "COMPUTERNAME")
_MIN_ENV_IDENTITY_LEN = 4

# Credential and contact shapes. Each is a refusal, never a warning.
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Hugging Face token shape", re.compile(r"hf_[A-Za-z0-9]{20,}")),
    ("API-key shape", re.compile(
        r"(?:\b(?:sk|pk|rk)[-_][A-Za-z0-9_-]{16,}|\bAKIA[0-9A-Z]{16}\b|\bgh[pousr]_[A-Za-z0-9]{20,}"
        r"|\bgithub_pat_[A-Za-z0-9_]{20,}|\bxox[abprs]-[A-Za-z0-9-]{10,})")),
    ("bearer/credential assignment", re.compile(
        r"(?i)(?:bearer\s+[A-Za-z0-9._~+/=-]{20,}"
        r"|(?:api[_-]?key|secret|token|passw(?:or)?d|authorization)[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9._~+/=-]{16,})")),
    ("e-mail address", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")),
)

# JSON / CSV keys that carry model output or free text; a string value longer than SHORT_LABEL_MAX
# under one of these keys is generated text.
TEXT_KEYS = frozenset({
    "out_text", "output_text", "completion", "response", "generated_text", "reply", "answer",
    "detail", "actual", "content", "messages", "assistant", "model_output",
    "text", "prompt", "out", "output", "message", "answer_text",
})

# Deny-by-default backstop: a string this long under ANY json key is free text, not a label or a hash.
LONG_STRING_MAX = 500

# A string this long under any key outside AUTHORED_NOTE_KEYS is free text. Builder-truncated fixture
# descriptions (<= 203 chars) sit below it; anything an unlisted key carries above it is refused.
FREE_TEXT_MAX = 240

# Keys whose values the analysers AUTHOR (notes about the data, formula strings); still bounded by LONG_STRING_MAX.
AUTHORED_NOTE_KEYS = frozenset({
    "notes", "note", "overall", "formula", "design", "plateau_rule", "prefix_cache_note",
    "cold_gate_note", "cold_gate_operationalisation_note", "cold_strict_start_note",
})

# Only these file types are accepted; any other suffix (yaml, tsv, no extension, ...) is refused.
ALLOWED_SUFFIXES = frozenset({".json", ".jsonl", ".csv", ".md", ".txt"})

# Metric columns the dataset builders write. A CSV column outside this set is refused: it may carry text.
KNOWN_CSV_COLUMNS = frozenset({
    "invocation", "arm", "visit", "protocol", "cell", "rep", "status", "t", "ttft_ms", "tpot_ms", "decode_tps",
    "decode_tps_wall", "input_tokens", "generated_tokens", "wall_ms", "output_sha256", "draft_tokens",
    "accepted_tokens", "temp_c_before", "temp_c_after", "passive_limit_pct_before", "throttle_reasons_before",
    "genai_version", "openvino_version", "gpu_driver", "uptime_h",
    "n_reps", "decode_tps_mean", "ttft_ms_rep0", "ttft_ms_mean",
    "model", "job", "suite", "case_id", "passed", "failed", "errors", "skipped_hardware", "tool_calls",
    "evaluated", "total", "turn", "reply_sha256",
})
CSV_CELL_MAX = 200  # backstop for allow-listed keys given via --allow-key

# Per-file budgets: the total characters of free text (strings over SHORT_LABEL_MAX chars) a JSON/JSONL file may carry
# outside / inside the authored-note keys, and the size of a prose file, so chunking under the per-string caps is bounded.
FREE_TEXT_BUDGET = 60000
AUTHORED_NOTE_BUDGET = 20000
PROSE_FILE_MAX = 30000
KEY_MAX = 120  # a JSON object key longer than this is free text used as a key (e.g. a histogram keyed by output text)

# CSV column classes (a column in KNOWN_CSV_COLUMNS is in exactly one): numeric, hex hash, or short id.
NUMERIC_COLUMNS = frozenset({
    "visit", "rep", "ttft_ms", "tpot_ms", "decode_tps", "decode_tps_wall", "input_tokens", "generated_tokens", "wall_ms",
    "draft_tokens", "accepted_tokens", "temp_c_before", "temp_c_after", "passive_limit_pct_before", "uptime_h", "n_reps",
    "decode_tps_mean", "ttft_ms_rep0", "ttft_ms_mean", "passed", "failed", "errors", "skipped_hardware", "tool_calls",
    "evaluated", "total", "turn", "throttle_reasons_before",
})
HASH_COLUMNS = frozenset({"output_sha256", "reply_sha256"})
_NUMERIC_CELL = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?\Z")
_HASH_CELL = re.compile(r"[0-9a-f]{1,64}\Z")
_ID_CELL = re.compile(r"[A-Za-z0-9_.:@/+()-]{0,48}\Z")

# Non-table prose lines in any .md / .txt file other than the root README.md; a table row has its own cap.
PROSE_LINE_MAX = 120
TABLE_LINE_MAX = 300

# An absolute local path. The sanitised ``Users/<user>`` and the generic ``/home/user`` fixture path are allowed.
_ABS_PATH = re.compile(r"(?:[A-Za-z]:[\\/]+|/)(?:Users|home|Windows|Program Files|projects)[\\/]+([^\\/\"'\s,]*)", re.I)
_GENERIC_NAMES = frozenset({"<user>", "user"})  # sanitised placeholder; the generic fixture home dir


class HfExeMissing(RuntimeError):
    pass


def hf_exe() -> str:
    """The hf CLI path: ``HF_EXE`` if set, else the uv-tool location. Absent -> HfExeMissing, no fallback."""
    path = os.environ.get("HF_EXE") or DEFAULT_HF_EXE
    if not Path(path).is_file():
        raise HfExeMissing(f"hf CLI not found at {path}; set HF_EXE to a working hf.exe (no other installer is used)")
    return path


# ---------------------------------------------------------------------------------------------
# preflight
# ---------------------------------------------------------------------------------------------

def _files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file())


def _walk_json(node, rel: str, hits: list[str], where: str, allow: frozenset[str] = frozenset(), key: str | None = None,
               strings: list[str] | None = None, budget: list[int] | None = None) -> None:
    """Walk one parsed JSON value. ``key`` is the nearest enclosing dict key (lists inherit it); every decoded
    string is appended to ``strings`` so the identity/secret scan also sees JSON-escaped forms."""
    lk = key.lower() if isinstance(key, str) else None
    if isinstance(node, dict):
        for k, v in node.items():
            if strings is not None and isinstance(k, str):
                strings.append(k)
            if isinstance(k, str) and len(k) > KEY_MAX and k.lower() not in allow:
                hits.append(f"{rel}: object key of {len(k)} chars ({where}); free text used as a key")
            if budget is not None and isinstance(k, str) and len(k) > SHORT_LABEL_MAX:
                budget[0] += len(k)
            if isinstance(k, str) and k.lower() == "messages" and k.lower() not in allow and v:
                hits.append(f"{rel}: generated-text field '{k}' ({where})")
            _walk_json(v, rel, hits, where, allow, k if isinstance(k, str) else None, strings, budget)
    elif isinstance(node, list):
        for v in node:
            _walk_json(v, rel, hits, where, allow, key, strings, budget)
    elif isinstance(node, str):
        if strings is not None:
            strings.append(node)
        n = len(node)
        if budget is not None and n > SHORT_LABEL_MAX:
            budget[1 if lk in AUTHORED_NOTE_KEYS else 0] += n
        if lk is None:
            if n > SHORT_LABEL_MAX:
                hits.append(f"{rel}: bare string of {n} chars ({where}); free text")
        elif lk in allow:
            return
        elif lk in TEXT_KEYS:
            if n > SHORT_LABEL_MAX:
                hits.append(f"{rel}: generated-text field '{key}' ({where})")
        elif n > LONG_STRING_MAX:
            hits.append(f"{rel}: string of {n} chars under key '{key}' ({where}); free text")
        elif n > FREE_TEXT_MAX and lk not in AUTHORED_NOTE_KEYS:
            hits.append(f"{rel}: string of {n} chars under key '{key}' ({where}); free text outside the authored-note keys")


def _scan_text(rel: str, text: str, deny: tuple[str, ...], hits: list[str]) -> None:
    low = text.lower()
    for s in deny:
        if s.lower() in low:
            hits.append(f"{rel}: contains identity string '{s}'")
    for m in _ABS_PATH.finditer(text):
        if m.group(1) in _GENERIC_NAMES:
            continue
        hits.append(f"{rel}: absolute local path '{m.group(0)[:60]}'")
        break
    for label, pat in _SECRET_PATTERNS:
        if pat.search(text):
            hits.append(f"{rel}: {label}")


def env_identity_strings() -> tuple[str, ...]:
    """The machine's own USERNAME / COMPUTERNAME values (skipped when short or generic placeholders)."""
    out: list[str] = []
    for var in _ENV_IDENTITY_VARS:
        v = os.environ.get(var, "").strip()
        if len(v) >= _MIN_ENV_IDENTITY_LEN and v.lower() not in _GENERIC_NAMES and v not in out:
            out.append(v)
    return tuple(out)


def preflight(root: Path, max_bytes: int = DEFAULT_MAX_BYTES, extra_deny: tuple[str, ...] = (),
              allow_keys: tuple[str, ...] = ()) -> list[str]:
    """Return the list of problems ('<file>: <reason>'); empty means clean. Empty dir is a problem.

    ``allow_keys`` exempts named text keys (e.g. grader diagnostics) and is always an explicit, visible flag."""
    allow = frozenset(k.lower() for k in allow_keys)
    hits: list[str] = []
    if not root.is_dir():
        return [f"{root}: not a directory"]
    files = _files(root)
    if not files:
        return [f"{root}: no files to upload"]
    deny = DENY_STRINGS + env_identity_strings() + tuple(extra_deny)
    for p in files:
        rel = p.relative_to(root).as_posix()
        size = p.stat().st_size
        if size > max_bytes:
            hits.append(f"{rel}: {size} bytes exceeds cap {max_bytes}")
            continue
        raw = p.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            hits.append(f"{rel}: not valid UTF-8 (binary or other encoding)")
            continue
        for d in deny:  # the file NAME can leak too: identity strings and credential/e-mail shapes
            if d.lower() in rel.lower():
                hits.append(f"{rel}: file name contains identity string '{d}'")
        for label, pat in _SECRET_PATTERNS:
            if pat.search(rel):
                hits.append(f"{rel}: file name matches a {label}")
        _scan_text(rel, text, deny, hits)
        suffix = p.suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            hits.append(f"{rel}: file type '{suffix or '(none)'}' is not accepted (allowed: {', '.join(sorted(ALLOWED_SUFFIXES))})")
            continue
        if suffix in (".md", ".txt") and rel.lower() != "readme.md":  # only the dataset's own root README is authored prose
            _scan_prose(rel, text, suffix, hits)
        if suffix == ".json":
            try:
                strings: list[str] = []
                budget = [0, 0]
                _walk_json(json.loads(text), rel, hits, "json", allow, None, strings, budget)
                _check_budget(rel, budget, hits)
                _scan_text(rel, chr(10).join(strings), deny, hits)
            except json.JSONDecodeError:
                hits.append(f"{rel}: invalid JSON")
        elif suffix == ".jsonl":
            strings = []
            budget = [0, 0]
            for n, line in enumerate(text.splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    _walk_json(json.loads(line), rel, hits, f"line {n}", allow, None, strings, budget)
                except json.JSONDecodeError:
                    hits.append(f"{rel}: invalid JSON on line {n}")
                    break
            _check_budget(rel, budget, hits)
            _scan_text(rel, chr(10).join(strings), deny, hits)
        elif suffix == ".csv":
            _scan_csv(rel, text, allow, hits)
    return list(dict.fromkeys(hits))


def _check_budget(rel: str, budget: list[int], hits: list[str]) -> None:
    if budget[0] > FREE_TEXT_BUDGET:
        hits.append(f"{rel}: {budget[0]} chars of free text exceed the per-file budget {FREE_TEXT_BUDGET}")
    if budget[1] > AUTHORED_NOTE_BUDGET:
        hits.append(f"{rel}: {budget[1]} chars of authored notes exceed the per-file budget {AUTHORED_NOTE_BUDGET}")


def _scan_prose(rel: str, text: str, suffix: str, hits: list[str]) -> None:
    """A prose file in a data directory: free text cannot be told from generated text, so line length and size are capped."""
    if len(text) > PROSE_FILE_MAX:
        hits.append(f"{rel}: prose file of {len(text)} chars exceeds the budget {PROSE_FILE_MAX}")
    for ln in text.splitlines():
        cap = TABLE_LINE_MAX if ln.lstrip().startswith("|") else PROSE_LINE_MAX
        if len(ln) > cap:
            hits.append(f"{rel}: prose line of {len(ln)} chars (cap {cap}) in a {suffix} file; free text cannot be told from generated text")
            return


def _scan_csv(rel: str, text: str, allow: frozenset[str], hits: list[str]) -> None:
    import csv
    import io

    reader = csv.DictReader(io.StringIO(text), restkey="\x00extra")
    unknown = sorted(c for c in (reader.fieldnames or []) if c and c.lower() not in KNOWN_CSV_COLUMNS and c.lower() not in allow)
    for c in unknown:
        hits.append(f"{rel}: column '{c}' is not a known metric column")
    bad: set[str] = set()
    extra = False
    for row in reader:
        if "\x00extra" in row:
            extra = True
        for k, v in row.items():
            if not k or k == "\x00extra" or v is None or k.lower() in allow:
                continue
            lk = k.lower()
            if lk in NUMERIC_COLUMNS:
                ok = v == "" or bool(_NUMERIC_CELL.match(v)) or v in ("True", "False", "None")
            elif lk in HASH_COLUMNS:
                ok = v == "" or bool(_HASH_CELL.match(v))
            else:
                ok = bool(_ID_CELL.match(v)) and not (lk in TEXT_KEYS and len(v) > SHORT_LABEL_MAX)
            if not ok or len(v) > CSV_CELL_MAX:
                bad.add(k)
    if extra:
        hits.append(f"{rel}: row with more cells than the header; the extra cells are unchecked free text")
    for k in sorted(bad):
        hits.append(f"{rel}: generated-text column '{k}' (cell is not numeric / hash / short id as the column requires)")


# ---------------------------------------------------------------------------------------------
# card-check
# ---------------------------------------------------------------------------------------------

_CARD_CHECKS: tuple[tuple[str, str], ...] = (
    ("hardware CPU", r"Core\s+Ultra|\bCPU\b|Lunar\s+Lake"),
    ("hardware GPU", r"\bArc\b|iGPU|\bGPU\b"),
    ("OpenVINO version", r"OpenVINO\s+\d{4}\.\d+"),
    ("GenAI version", r"GenAI\s+\d{4}\.\d+"),
    ("GPU driver version", r"driver\W+\d+\.\d+\.\d+\.\d+"),
    ("model precision", r"\b(?:INT4|INT8|FP16|BF16|f16)\b"),
    ("model revision (40-hex)", r"\b[0-9a-f]{40}\b"),
    ("methodology heading", r"(?im)^#+\s.*(?:method|setup|protocol)"),
    ("conditions", r"(?i)\bconditions?\b"),
    ("NOT-measured section", r"(?im)^#+\s.*not\s+measured"),
    ("pre-registered limits", r"(?i)pre-?registered"),
    ("license CC-BY-4.0", r"(?i)cc-by-4\.0"),
)


def card_check(text: str, config: str | None = None, path_in_repo: str | None = None) -> list[str]:
    """Return failed check names. With config/path_in_repo, also require the front-matter entry."""
    failed = [name for name, pat in _CARD_CHECKS if not re.search(pat, text)]
    if config:
        fm = _front_matter(text)
        if not re.search(rf"config_name:\s*{re.escape(config)}\s*$", fm, re.M):
            failed.append(f"front-matter config_name: {config}")
        elif path_in_repo and not _config_lists_path(fm, config, path_in_repo):
            failed.append(f"front-matter data_files under {path_in_repo}/ for {config}")
    return failed


def _config_lists_path(fm: str, config: str, path_in_repo: str) -> bool:
    """True when the config's ``data_files`` (one inline path, or a ``- `` list) has an entry under the path."""
    m = re.search(rf"config_name:\s*{re.escape(config)}\s*\n(?P<body>(?:(?!\s*-\s*config_name:).*\n?)*)", fm)
    if not m:
        return False
    df = re.search(r"data_files:(?P<v>[^\n]*(?:\n[ \t]+-[^\n]*)*)", m.group("body"))
    if not df:
        return False
    entries = [t for t in re.split(r"[\s]+", df.group("v").replace("- ", " ")) if t]
    return any(re.fullmatch(rf"{re.escape(path_in_repo)}/\S+", t) for t in entries)


def _front_matter(text: str) -> str:
    m = re.match(r"---\r?\n(.*?)\r?\n---", text, re.S)
    return m.group(1) if m else ""


# ---------------------------------------------------------------------------------------------
# plan / upload / verify
# ---------------------------------------------------------------------------------------------

_CONFIG_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")


_SEGMENT_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*\Z")
# A commit message is free text but must not read as an option and must stay one printable line.
_MESSAGE_RE = re.compile(r"^[A-Za-z0-9_.,:;()#/+=@'\[\] -]+$")
MESSAGE_MAX = 200


def _validate_message(message: str) -> str | None:
    if (not message or message.startswith("-") or message.strip() != message or len(message) > MESSAGE_MAX
            or not _MESSAGE_RE.fullmatch(message)):
        return (f"commit message {message[:40]!r} must be 1-{MESSAGE_MAX} chars of [A-Za-z0-9 _.,:;()#/+=@'[]-], "
                "not starting with '-'")
    return None


def _scan_target_text(config: str, path_in_repo: str, message: str | None, deny: tuple[str, ...]) -> str | None:
    """Config, path-in-repo and commit message become permanent public metadata: scan them like file content."""
    hits: list[str] = []
    for name, value in (("--config", config), ("--path-in-repo", path_in_repo), ("--message", message)):
        if value:
            hits += preflight_text(name, value, deny)
    return "; ".join(hits) if hits else None


def _validate_target(config: str, path_in_repo: str, message: str | None = None, deny: tuple[str, ...] = ()) -> str | None:
    """Config, path-in-repo and message are untrusted argv text that lands in the hf command line.

    Every path segment starts with a letter, digit or '_' (so none can read as an option), '..' and
    empty segments are refused, and the only characters are letters, digits, '_', '-', '.', '/'."""
    if not _CONFIG_RE.match(config):
        return f"config name '{config}' is not [A-Za-z0-9][A-Za-z0-9_.-]*"
    p = path_in_repo
    if (not p or p.endswith("/") or not all(_SEGMENT_RE.match(seg) and seg != ".." for seg in p.split("/"))
            or ".." in p.split("/")):
        return (f"path-in-repo '{p}' must be relative posix segments of [A-Za-z0-9_.-], each starting with "
                "a letter, digit or '_', with no '..'")
    if message is not None:
        err = _validate_message(message)
        if err:
            return err
    return _scan_target_text(config, path_in_repo, message, deny)


def _data_file(root: Path, explicit: str | None) -> str | None:
    if explicit:
        return explicit
    if (root / "speed_visits.csv").is_file():
        return "speed_visits.csv"
    csvs = sorted(p.relative_to(root).as_posix() for p in root.rglob("*.csv"))
    return csvs[0] if csvs else None


def front_matter_lines(config: str, path_in_repo: str, data_file: str | None) -> str:
    df = data_file or "<primary>.csv"
    return f"  - config_name: {config}\n    data_files: {path_in_repo}/{df}\n"


def upload_command(root: Path, path_in_repo: str, message: str) -> list[str]:
    # Options first, then '--', then the positionals: nothing after the separator can be parsed as a flag.
    return [hf_exe(), "upload", "--repo-type", "dataset", "--commit-message", message, "--", REPO, str(root), path_in_repo]


def cmd_plan(a) -> int:
    err = _validate_target(a.config, a.path_in_repo, a.message, tuple(a.deny))
    if err:
        print(f"FAIL {err}")
        return 2
    root = Path(a.dir)
    hits = preflight(root, a.max_bytes, tuple(a.deny), tuple(a.allow_key))
    files = _files(root) if root.is_dir() else []
    print(f"repo: {REPO} (dataset)")
    print(f"files ({len(files)}) -> {a.path_in_repo}/")
    for p in files:
        print(f"  {p.relative_to(root).as_posix()}  {p.stat().st_size}")
    print("card front-matter (configs: block of the repo README.md) needs:")
    print(front_matter_lines(a.config, a.path_in_repo, _data_file(root, a.data_file)), end="")
    try:
        print("command: " + " ".join(upload_command(root, a.path_in_repo, a.message or "<message>")))
    except HfExeMissing as e:
        print(f"hf CLI: {e}")
    print(f"preflight: {'CLEAN' if not hits else str(len(hits)) + ' problem(s)'}")
    for h in hits:
        print(f"  {h}")
    return 0 if not hits else 1


def cmd_upload(a) -> int:
    err = _validate_target(a.config, a.path_in_repo, a.message, tuple(a.deny))
    if err:
        print(f"FAIL {err}")
        return 2
    root = Path(a.dir)
    hits = preflight(root, a.max_bytes, tuple(a.deny), tuple(a.allow_key))
    hits += preflight_text("--message", a.message, tuple(a.deny))  # the commit message is public too
    if hits:
        print("REFUSED: preflight failed; nothing uploaded")
        for h in hits:
            print(f"  {h}")
        return 1
    card_text = None
    if a.card:
        card_text = Path(a.card).read_text(encoding="utf-8")
        card_hits = preflight_text("card", card_text, tuple(a.deny))
        failed = card_check(card_text, a.config, a.path_in_repo) + card_hits
        if failed:
            print("REFUSED: card failed; nothing uploaded")
            for f in failed:
                print(f"  {f}")
            return 1
    try:
        cmd = upload_command(root, a.path_in_repo, a.message)
    except HfExeMissing as e:
        print(f"FAIL {e}")
        return 3
    runs = [cmd]
    if a.card:
        runs.append([cmd[0], "upload", "--repo-type", "dataset", "--commit-message", f"README: {a.config} card",
                     "--", REPO, str(Path(a.card)), "README.md"])
    for c in runs:
        res = subprocess.run(c, capture_output=True, text=True)
        out = (res.stdout or "") + (res.stderr or "")
        if res.returncode != 0:
            print(f"FAIL hf upload exited {res.returncode}: {out.strip()[-400:]}")
            return 4
        urls = re.findall(r"url=(\S+)", out)
        print(f"committed: {urls[-1] if urls else '(no commit url in output)'}")
    print(f"uploaded {len(_files(root))} file(s) to {a.path_in_repo}/; run verify next")
    return 0


def preflight_text(rel: str, text: str, deny: tuple[str, ...]) -> list[str]:
    hits: list[str] = []
    _scan_text(rel, text, DENY_STRINGS + env_identity_strings() + tuple(deny), hits)
    return hits


def parse_listing(stdout: str) -> dict[str, int | None]:
    """Parse ``hf datasets ls REPO -R --format json`` into {path: size}. Raises ValueError if unparseable."""
    data = json.loads(stdout)
    if isinstance(data, dict):
        data = data.get("files") or data.get("siblings") or data.get("items") or []
    out: dict[str, int | None] = {}
    for e in data:
        if isinstance(e, str):
            out[e] = None
            continue
        path = e.get("path") or e.get("rfilename") or e.get("name")
        size = e.get("size")
        if size is None and isinstance(e.get("lfs"), dict):
            size = e["lfs"].get("size")
        if path:
            out[path] = size
    return out


def cmd_verify(a) -> int:
    err = _validate_target(a.config, a.path_in_repo, None, tuple(a.deny))
    if err:
        print(f"FAIL {err}")
        return 2
    root = Path(a.dir)
    try:
        exe = hf_exe()
    except HfExeMissing as e:
        print(f"FAIL {e}")
        return 3
    res = subprocess.run([exe, "datasets", "ls", REPO, "-R", "--format", "json"], capture_output=True, text=True)
    if res.returncode != 0:
        print(f"FAIL remote listing exited {res.returncode}: {(res.stderr or res.stdout).strip()[-300:]}")
        return 4
    try:
        remote = parse_listing(res.stdout)
    except (ValueError, AttributeError, TypeError) as e:
        print(f"FAIL remote listing not parseable: {e}")
        return 4
    problems: list[str] = []
    local = {p.relative_to(root).as_posix(): p.stat().st_size for p in _files(root)}
    prefix = a.path_in_repo + "/"
    for rel, size in local.items():
        rp = prefix + rel
        if rp not in remote:
            problems.append(f"missing remote: {rp}")
        elif remote[rp] is None:
            problems.append(f"remote size unknown (cannot verify): {rp}")
        elif remote[rp] != size:
            problems.append(f"size mismatch: {rp} local {size} remote {remote[rp]}")
    extra = sorted(p for p in remote if p.startswith(prefix) and p[len(prefix):] not in local)
    print(f"local files {len(local)}; remote files under {a.path_in_repo}/: {sum(1 for p in remote if p.startswith(prefix))}")
    for e in extra:
        print(f"note: remote-only file {e}")
    for p in problems:
        print(f"MISMATCH {p}")
    return 0 if not problems else 1


def cmd_preflight(a) -> int:
    hits = preflight(Path(a.dir), a.max_bytes, tuple(a.deny), tuple(a.allow_key))
    for h in hits:
        print(f"FAIL {h}")
    print("preflight: CLEAN" if not hits else f"preflight: {len(hits)} problem(s)")
    return 0 if not hits else 1


def cmd_card_check(a) -> int:
    text = Path(a.readme).read_text(encoding="utf-8")
    failed = card_check(text, a.config, a.path_in_repo)
    for name, _ in _CARD_CHECKS:
        print(f"{'FAIL' if name in failed else 'ok  '} {name}")
    for f in failed:
        if f.startswith("front-matter"):
            print(f"FAIL {f}")
    return 0 if not failed else 1


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="hf_publish", allow_abbrev=False, description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, target: bool = True):
        p.add_argument("--dir", required=True)
        p.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
        p.add_argument("--deny", action="append", default=[], help="extra identity string to refuse (repeatable)")
        p.add_argument("--allow-key", action="append", default=[], help="exempt one generated-text key (repeatable, explicit)")
        if target:
            p.add_argument("--config", required=True)
            p.add_argument("--path-in-repo", required=True)

    p = sub.add_parser("preflight"); common(p, False); p.set_defaults(fn=cmd_preflight)
    p = sub.add_parser("plan"); common(p); p.add_argument("--message"); p.add_argument("--data-file"); p.set_defaults(fn=cmd_plan)
    p = sub.add_parser("upload"); common(p); p.add_argument("--message", required=True)
    p.add_argument("--card", help="updated dataset card to publish as README.md after the folder")
    p.set_defaults(fn=cmd_upload)
    p = sub.add_parser("verify"); common(p); p.set_defaults(fn=cmd_verify)
    p = sub.add_parser("card-check"); p.add_argument("--readme", required=True)
    p.add_argument("--config"); p.add_argument("--path-in-repo"); p.set_defaults(fn=cmd_card_check)
    return ap


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # a refusal message that quotes non-console text must not crash the printer
        try:
            stream.reconfigure(errors="backslashreplace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    a = build_parser().parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
