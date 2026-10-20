"""Publish a finished research dataset directory to the public Hugging Face dataset repo.

Subcommands (all deterministic, fail-closed; exit 0 only when every check passed):

* ``preflight --dir D``   scan every file in D for identity leaks, generated text, oversize files,
                          non-UTF-8 bytes and absolute local paths.
* ``card-check --readme P``  the dataset card carries the sections a community-grade study needs.
* ``plan --dir D --config NAME --path-in-repo P``  dry run: files, the exact upload command, the
                          card front-matter lines the config needs. Touches nothing.
* ``upload ...``          preflight, then ``hf upload``; refuses on any preflight hit.
                          A dataset manifest may carry ``cited_repository_paths`` (paths its card says the public snapshot
                          carries): ``plan`` and ``upload`` refuse while ``--public-ref`` (default ``PUBLIC_REF``, only a ref of
                          the public mirror) lacks any of them, does not resolve, or differs from HEAD under any of them. A manifest key ``hf_default_data_file`` must name an existing
                          ``.csv`` directly under the dataset directory, or ``plan`` and ``upload`` refuse.
* ``verify ...``          compares the remote file listing (names and sizes) to the local dir.

The Hugging Face CLI is ``hf.exe`` only (path in ``HF_EXE`` or ``DEFAULT_HF_EXE``). It is never
installed or substituted here. There is no token option: authentication is the CLI's own login state.
Free-text arguments (--message, --path-in-repo, --config) are validated against an allowlist before any
subprocess runs, and the hf positionals follow a literal ``--``. Preflight additionally refuses
credential and e-mail shapes anywhere in the tree: in file contents, in file names, and in the decoded
form of every JSON string (an escaped ``\u0040`` does not hide an address). Absolute local paths are refused by scope: the
user-profile roots (``Users``, ``home``, ``Windows``, ``Program Files``, ``projects``) in every file, and the wider roots
(any drive, POSIX system folders, ``ProgramData``, UNC shares) in every CSV cell and in every file of a dataset whose
``manifest.json`` declares ``NEP5_SCHEMA``; a machine SID, with or without its relative id, is refused everywhere,
file names included.

Generated text is refused by deny-by-default rules, not by key name alone: a bare JSON string, a list
of strings and a nested object are all walked; a string over ``FREE_TEXT_MAX`` chars is refused under any key
outside ``AUTHORED_NOTE_KEYS``; a CSV may carry only ``KNOWN_CSV_COLUMNS`` (plus ``NEP5_COLUMNS``, each value-checked, inside a
directory whose ``manifest.json`` declares ``NEP5_SCHEMA``), and a header with an empty or repeated name is refused; only ``ALLOWED_SUFFIXES`` are
accepted at all; prose files other than the root README.md are capped line by line and in total size. JSON keys are
length-capped, CSV cells are checked per column (numeric, hash or short id) and extra cells beyond the header are
refused, and a per-file budget bounds the total free text so chunking cannot evade the per-string caps. Honest
limit: a string under ``FREE_TEXT_MAX`` chars under an unlisted key cannot be told from an id or a label, and the
budgets bound, not eliminate, what chunking can carry. The commit message, config name and path-in-repo are
scanned for identity, e-mail and credential shapes before any subprocess runs.

Known limits of the path and SID rules (they read raw text; the identity lock alone also decodes percent and JSON
escapes): a ``Users`` path written with backslashes and no drive letter (``<backslash>Users<backslash>someone``) is accepted in prose, in every dataset. A SID split
by a space or a line break, percent-encoded (``S%2D1%2D5%2D21...``), written with a non-breaking hyphen (U+2011) or with a
zero-width space after ``S-1-5-21-`` is accepted in prose, and so is a percent-encoded path in the prose of a declared
dataset. A Microsoft-account or Entra ID account SID (``S-1-11-96-...``, ``S-1-12-1-...``) is refused by the same lock's account
rule (``identity_lock.find_account_sid_hits``), under the same limits; not seen either are its binary or ``hex:01,..``
registry-export form and a SID glued after a letter or digit. A hex status code in
lower case (``0x8032000a``) in a declared dataset's cell is refused by the ``_HEX_CODE`` column check, so a builder that
copies one produces a dataset this script blocks. A ``manifest.json`` spelled ``MANIFEST.json`` declares the schema only
on a case-insensitive file system; elsewhere the directory is refused for unknown columns (the fail-closed direction).
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import functools
import platform
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import identity_lock as _il  # noqa: E402  (digest recognition of this machine's names; works under any account)

REPO = "blairducrayoppat/openvino-arc140v-lunarlake"
DEFAULT_HF_EXE = str(Path.home() / ".local" / "bin" / "hf.exe")
DEFAULT_MAX_BYTES = 50 * 1024 * 1024

# Same bound as scripts/build_phase1_dataset.py SHORT_LABEL_MAX: a verdict label, never a generation.
SHORT_LABEL_MAX = 24

# Identity strings that must never reach the public repo (matched case-insensitively): the operator user name and the
# host name, read from the machine at import (USERNAME / COMPUTERNAME, else getpass / platform) and again at call time.
# Never hold them as literals: the gate lock tests/security/test_no_host_identity_in_tree.py scans every tracked file.
DENY_STRINGS = tuple(s for s in _il.live_names() if s)
# Recognition by digest (identity_lock.find_hits) runs beside the string list, so the preflight refuses this machine's
# names under any account, not only the operator's.
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

# Columns of the NEP-0005 containment study tables (scripts/build_nep0005_dataset.py). They apply only to CSV files under a
# directory whose ``manifest.json`` declares ``"schema": NEP5_SCHEMA``; any other directory is held to KNOWN_CSV_COLUMNS.
# Each is ``(class, reason)``; class ``id`` = short id/label cell (value-checked per column by NEP5_VALUE_CHECKS),
# ``num`` = number / True / False, ``hash`` = lower-case hex digest.
NEP5_SCHEMA = "nep0005-halfset-export-v1"
NEP5_COLUMNS: dict[str, tuple[str, str]] = {
    "state_id": ("id", "short state code (R0-R7, O1-O6, N1, F, H6, H4, HP, '-after-reinstall')"),
    "phase": ("id", "run phase word (halfset, ours, n1, taskcheck-first, taskcheck-second)"),
    "pass_no": ("num", "1-based pass counter"),
    "record_class": ("id", "the harness record class word (ok)"),
    "started": ("id", "ISO-8601 timestamp with offset"),
    "finished": ("id", "ISO-8601 timestamp with offset"),
    "srt_status_word": ("id", "srt-win status word (installed, partial, absent)"),
    "s1_filters": ("num", "filter count in test sublayer S1"),
    "s2_filters": ("num", "filter count in test sublayer S2"),
    "s3_filters": ("num", "filter count in test sublayer S3"),
    "our_keys_state": ("id", "state word of our own key read (PRESENT, ABSENT)"),
    "attempt_status": ("id", "first word of the engine add-attempt status (added, error)"),
    "attempt_code": ("id", "engine status code in hex (0x...) when the add was refused"),
    "acct_before_open": ("num", "count of the six account connects that connected before any filter"),
    "acct_during_open": ("num", "count of account connects that connected with the state in place"),
    "acct_during_blocked": ("num", "count of account connects blocked with the state in place"),
    "op_outside_ok": ("num", "count of operator connects outside the permit range that succeeded"),
    "op_before_ok": ("num", "count of operator loopback connects that succeeded before the filters"),
    "op_during_ok": ("num", "count of operator loopback connects that succeeded during the state"),
    "probe_ms_min": ("num", "fastest account connect during the state, milliseconds"),
    "probe_ms_max": ("num", "slowest account connect during the state, milliseconds"),
    "wd_connects": ("num", "operator watchdog connects made"),
    "wd_failures": ("num", "operator watchdog connect failures"),
    "removal_ok": ("num", "removal by key read back ok (True/False)"),
    "sweep_after_clean": ("num", "post-removal sweep read clean (True/False)"),
    "provider_present_after": ("num", "provider still present after removal (True/False)"),
    "filters_left_after": ("num", "filters left in S1+S2+S3 after removal"),
    "export_hits_total": ("num", "marker/name hits in the post-removal engine export"),
    "export_after_sha256": ("hash", "sha256 of the post-removal engine export (hex digest)"),
    "probe_when": ("id", "before or during: when in the cycle the connect ran"),
    "target": ("id", "loopback target as family:port (v4:61763)"),
    "result": ("id", "connect result word (connected, blocked)"),
    "win32": ("num", "Windows socket error code of the connect (0, 10013)"),
    "probe_ms": ("num", "duration of one probe in milliseconds"),
    "add_class": ("id", "N1 direct add verdict word (denied)"),
    "add_code": ("id", "N1 add status code in hex"),
    "add_phase": ("id", "N1 add: phase the verdict came at (call)"),
    "add_filter_present_after": ("num", "N1: the attempted filter existed afterwards (True/False)"),
    "delete_class": ("id", "N1 direct delete verdict word (denied)"),
    "delete_code": ("id", "N1 delete status code in hex"),
    "delete_phase": ("id", "N1 delete: phase the verdict came at (call)"),
    "delete_filter_still_present": ("num", "N1: the test filter still existed afterwards (True/False)"),
    "source_file": ("id", "name of the source record file the row was read from"),
    "exit_code": ("num", "process exit code"),
    "records": ("num", "records in the phase file"),
    "passes": ("num", "passes requested"),
    "task_restored": ("num", "account task restored at session end (True/False)"),
    "definition_matches": ("num", "restored task equals the recorded baseline (True/False)"),
    "reprovision_exit": ("num", "exit code of the end-of-session re-provision"),
    "files_left": ("num", "files left in the probe folder at session end"),
    "build": ("id", "srt-win build word (stock, patched)"),
    "filters": ("num", "filter count srt-win reported"),
    "has_block_v4": ("num", "an IPv4 block filter is present (True/False)"),
    "has_block_v6": ("num", "an IPv6 block filter is present (True/False)"),
    "has_permit_v4": ("num", "an IPv4 loopback permit filter is present (True/False)"),
    "has_permit_v6": ("num", "an IPv6 loopback permit filter is present (True/False)"),
    "verify_v4_out": ("id", "wfp verify result on the IPv4 listener outside the range (blocked, connected)"),
    "verify_v6_out": ("id", "wfp verify result on the IPv6 listener outside the range"),
    "verify_v4_in": ("id", "wfp verify result on the IPv4 in-range listener"),
    "verify_v6_in": ("id", "wfp verify result on the IPv6 in-range listener"),
    "host_check_stock_ts": ("id", "stock host readiness check outcome word (pass, wfp_fence_inactive)"),
    "host_check_patched_ts": ("id", "patched host readiness check outcome word"),
    "step": ("id", "install step word (reinstall, restore_force)"),
    "ms": ("num", "command duration in milliseconds"),
    "said_installed": ("num", "srt-win message contains 'installed (' (True/False; the message itself is not published)"),
    "said_already_installed": ("num", "srt-win message contains 'already installed' (True/False)"),
    "said_no_changes": ("num", "srt-win message contains 'no changes' (True/False)"),
    "said_port_range_unknown": ("num", "srt-win message contains 'port_range=<unknown>' (True/False)"),
    "said_filters": ("num", "filter count srt-win printed in its message, blank if none"),
    "windows_version": ("id", "Windows version string from the driver (10.0.26200.0)"),
    "install_exit": ("num", "srt-win install exit code in the cycle"),
    "install_ms": ("num", "srt-win install duration in milliseconds"),
    "ambient_paths": ("num", "system paths srt-win stamped at install"),
    "control_srt_win_hits": ("num", "positive-control export hits for srt-win names"),
    "control_s1_hits": ("num", "positive-control export hits for sublayer S1"),
    "uninstall_clean": ("num", "post-uninstall direct checks read clean (True/False)"),
    "uninstall_exit": ("num", "srt-win uninstall exit code"),
    "uninstall_ms": ("num", "srt-win uninstall duration in milliseconds"),
    "footprint_items_present": ("num", "of seven install footprint items, how many remain after uninstall"),
    "store_dir_present": ("num", "the store folder remains after uninstall (True/False)"),
    "store_dir_has_deny_ace": ("num", "the store folder's access list carries a deny entry (True/False)"),
    "enum_s1_after": ("num", "filters enumerated in S1 after uninstall"),
    "enum_s2_after": ("num", "filters enumerated in S2 after uninstall"),
    "enum_s3_after": ("num", "filters enumerated in S3 after uninstall"),
    "sweep_count": ("num", "foreign filters the sweep found after uninstall"),
    "wfp_srt_win_hits": ("num", "engine export hits for srt-win after uninstall"),
    "wfp_s1_hits": ("num", "engine export hits for S1 after uninstall"),
    "wfp_s2_hits": ("num", "engine export hits for S2 after uninstall"),
    "wfp_s3_hits": ("num", "engine export hits for S3 after uninstall"),
    "wfp_default_hits": ("num", "engine export hits for srt-win's default sublayer after uninstall"),
    "user_rights_sid_hits": ("num", "exported user rights naming either sandbox SID after uninstall"),
    "acl_entries": ("num", "access-list entries snapshotted"),
    "acl_sid_hits": ("num", "snapshot entries naming a sandbox SID"),
    "acl_changed": ("num", "snapshot entries whose access text changed versus the baseline"),
    "store_dir_deny_rid": ("num", "relative identifier (last component) of the store folder's deny-entry SID; never the domain"),
    "exe_sha256": ("hash", "sha256 of the srt-win executable under test"),
    "driver_sha256": ("hash", "sha256 of the measurement driver script"),
    "run_id": ("id", "run identifier"),
    "sample_n": ("num", "1-based sample counter"),
    "offset_s": ("num", "seconds from hold start to the sample"),
    "outcome": ("id", "probe outcome word (blocked, open)"),
    "error_code": ("num", "Windows socket error code of the probe"),
    "windows_build": ("id", "Windows build and revision (26200.9457)"),
    "bitdefender_processes": ("num", "count of Bitdefender processes seen at run start"),
    "filter_set": ("id", "filter set word of the hold run"),
    "hold_seconds": ("num", "planned hold length in seconds"),
    "samples_expected": ("num", "samples planned"),
    "samples_blocked": ("num", "samples blocked"),
    "samples_open": ("num", "samples that connected"),
    "objects_existed_s": ("num", "seconds the filters stood"),
    "uptime_s": ("num", "seconds of uptime at the post-restart check"),
    "reboot_confirmed": ("num", "a restart since arming was confirmed (True/False)"),
    "fence_state": ("id", "fence state word at the check (PRESENT, ABSENT)"),
    "all_persistent": ("num", "all four objects persistent (True/False)"),
    "probe_blocked": ("num", "the account's probe under the fence was refused (True/False)"),
    "probe_error_code": ("num", "Windows socket error code of that probe"),
    "removal_verified": ("num", "removal by key verified (True/False)"),
    "guard_refused_after_removal": ("num", "the absence gate refused after removal (True/False)"),
}

KNOWN_CSV_COLUMNS = frozenset({
    "invocation", "arm", "visit", "protocol", "cell", "rep", "status", "t", "ttft_ms", "tpot_ms", "decode_tps",
    "decode_tps_wall", "input_tokens", "generated_tokens", "wall_ms", "output_sha256", "draft_tokens",
    "accepted_tokens", "temp_c_before", "temp_c_after", "passive_limit_pct_before", "throttle_reasons_before",
    "genai_version", "openvino_version", "gpu_driver", "uptime_h",
    "n_reps", "decode_tps_mean", "ttft_ms_rep0", "ttft_ms_mean",
    "model", "job", "suite", "case_id", "passed", "failed", "errors", "skipped_hardware", "tool_calls",
    "evaluated", "total", "turn", "reply_sha256",
})
# Metric columns the dataset builders write. A CSV column outside KNOWN_CSV_COLUMNS (and outside NEP5_COLUMNS inside a
# dataset that declares NEP5_SCHEMA) is refused: it may carry text.
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
NEP5_NUMERIC_COLUMNS = frozenset(c for c, (k, _) in NEP5_COLUMNS.items() if k == "num")
NEP5_HASH_COLUMNS = frozenset(c for c, (k, _) in NEP5_COLUMNS.items() if k == "hash")
_NUMERIC_CELL = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?\Z")
_HASH_CELL = re.compile(r"[0-9a-f]{1,64}\Z")
_ID_CELL = re.compile(r"[A-Za-z0-9_.:@/+()-]{0,48}\Z")

# Value-level checks of the NEP-0005 id-class columns: an enumerated set, or a pattern that cannot carry a sentence, a
# path or a name. A blank cell passes (an absent reading); anything else must match its column's check.
_ISO_OFFSET = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,7})?[+-]\d{2}:\d{2}\Z")
_HEX_CODE = re.compile(r"0x[0-9A-F]{8}\Z")
_TARGET = re.compile(r"v[46]:\d+\Z")
# A run id and a source file name are one to four short lower-case words and a date-time stamp, so a hyphenated sentence
# (more words, longer words, no stamp) is refused. Honest limit: four short words and a stamp can still carry a phrase.
_WORD = r"[a-z0-9]{1,10}"
_STAMP = r"\d{8}-\d{6}"
_RUN_TOKEN = re.compile(rf"{_WORD}(?:-{_WORD}){{0,3}}-{_STAMP}\Z")
_SOURCE_FILE = re.compile(rf"{_WORD}(?:-{_WORD}){{0,3}}-{_STAMP}\.json\Z")
_WINDOWS_VERSION = re.compile(r"\d+\.\d+\.\d+\.\d+\Z")
_WINDOWS_BUILD = re.compile(r"\d+\.\d+\Z")
_STATES = frozenset({"R0", "R1", "R2", "R3", "R4", "R5", "R6", "R7", "O1", "O2", "O3", "O4", "O5", "O6", "N1", "F", "H6", "H4",
                     "HP", "H6-after-reinstall", "H4-after-reinstall", "HP-after-reinstall"})
_VERIFY = frozenset({"blocked", "connected"})
_HOST_CHECK = frozenset({"pass", "wfp_fence_inactive"})
_PRESENCE = frozenset({"PRESENT", "ABSENT"})
NEP5_VALUE_CHECKS: dict[str, frozenset[str] | re.Pattern[str]] = {
    "state_id": _STATES,
    "phase": frozenset({"halfset", "ours", "n1", "taskcheck-first", "taskcheck-second"}),
    "record_class": frozenset({"ok"}),
    "started": _ISO_OFFSET, "finished": _ISO_OFFSET, "t": _ISO_OFFSET,
    "srt_status_word": frozenset({"installed", "partial", "absent"}),
    "our_keys_state": _PRESENCE,
    "attempt_status": frozenset({"added", "error"}),
    "attempt_code": _HEX_CODE,
    "probe_when": frozenset({"before", "during"}),
    "target": _TARGET,
    "result": _VERIFY,
    "add_class": frozenset({"denied"}), "add_code": _HEX_CODE, "add_phase": frozenset({"call"}),
    "delete_class": frozenset({"denied"}), "delete_code": _HEX_CODE, "delete_phase": frozenset({"call"}),
    "source_file": _SOURCE_FILE,
    "build": frozenset({"stock", "patched"}),
    "verify_v4_out": _VERIFY, "verify_v6_out": _VERIFY, "verify_v4_in": _VERIFY, "verify_v6_in": _VERIFY,
    "host_check_stock_ts": _HOST_CHECK, "host_check_patched_ts": _HOST_CHECK,
    "step": frozenset({"reinstall", "restore_force"}),
    "windows_version": _WINDOWS_VERSION,
    "run_id": _RUN_TOKEN,
    "outcome": frozenset({"blocked", "open"}),
    "windows_build": _WINDOWS_BUILD,
    "filter_set": frozenset({"permit_on", "permit_off"}),
    "fence_state": _PRESENCE,
    "arm": frozenset({"arm2", "arm3a", "arm3b", "arm3b-arming-refused", "arm3b-armed"}),
}
# Non-table prose lines in any .md / .txt file other than the root README.md; a table row has its own cap.
PROSE_LINE_MAX = 120
TABLE_LINE_MAX = 300

# An absolute local path. The sanitised ``Users/<user>`` and the generic ``/home/user`` fixture path are allowed.
# These roots apply to every file of every dataset.
_ABS_PATH = re.compile(r"(?:[A-Za-z]:[\\/]+|/)(?:Users|home|Windows|Program Files|projects)[\\/]+([^\\/\"'\s,]*)", re.I)
_GENERIC_NAMES = frozenset({"<user>", "user"})  # sanitised placeholder; the generic fixture home dir
# The wider roots: any drive root (the letter not inside a word, so ``https://`` is not one), a POSIX system root, a
# ProgramData folder with or without a drive, and a UNC share. They apply to CSV cells in every dataset and to every
# file of a dataset whose ``manifest.json`` declares NEP5_SCHEMA. Elsewhere they would refuse text that merely quotes a
# path (an eval case describing ``/tmp/export/``, a regex source such as ``\d\d:\d\d``) and model-store paths already
# published. The generic fixture paths stay exempt (see find_abs_path).
_DRIVE_ROOT = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]")
_POSIX_ROOT = re.compile(r"(?<![\w.\-/<>])/(?:tmp|var|etc|mnt|opt|usr|data|root|ProgramData)(?:[\\/]|\Z)")
_PROGRAMDATA = re.compile(r"(?<![A-Za-z0-9])ProgramData[\\/]", re.I)
# A network share, with either separator in any mix, with or without the ``\\?\UNC\`` or ``\\.\UNC\`` device prefix:
# ``\\host\share``, ``//host/share``, ``\\host/share``, ``//?/UNC/host/share``. A forward-slash start is not a share
# after a scheme colon, a path character or a dot, so ``https://host/x`` and ``a//b/c`` are not shares; the ``file:``
# form is its own rule below.
_UNC_ROOT = re.compile(
    r"(?:(?<![A-Za-z0-9_])\\[\\/]|(?<![A-Za-z0-9_:/.\-])/[\\/])[\\/]*(?:[?.][\\/]+UNC[\\/]+)?"
    r"[A-Za-z0-9_$][A-Za-z0-9_.$-]*[\\/]+[A-Za-z0-9_$]")
# A ``file:`` URI names a local resource or a share, whatever follows the slashes.
_FILE_URL = re.compile(r"(?<![A-Za-z0-9])file:/+[^\s/]", re.I)
# A machine-domain Windows SID names an account on a real machine and is refused anywhere: the full form with its
# relative id (S-1-5-21-a-b-c-rid), the domain part alone (S-1-5-21-a-b-c, the machine itself), either in lower case.
_SID = re.compile(r"(?<![A-Za-z0-9])S-1-5-21-\d+-\d+-\d+", re.I)


def find_abs_path(text: str, wide: bool = False) -> str | None:
    """The first absolute local path in ``text`` (a refusal), or None. The sanitised ``Users/<user>`` and the generic
    ``/home/user`` fixture paths are not refusals. ``wide`` adds the drive, POSIX, ProgramData and UNC roots."""
    for m in _ABS_PATH.finditer(text):
        if m.group(1) not in _GENERIC_NAMES:
            return m.group(0)
    if not wide:
        return None
    for m in _DRIVE_ROOT.finditer(text):
        known = _ABS_PATH.match(text, m.start())
        if known and known.group(1) in _GENERIC_NAMES:
            continue
        return text[m.start():m.start() + 60]
    for rx in (_POSIX_ROOT, _PROGRAMDATA, _UNC_ROOT, _FILE_URL):
        m = rx.search(text)
        if m:
            return text[m.start():m.start() + 60]
    return None


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


@functools.lru_cache(maxsize=1)
def _serial_digests() -> frozenset[str]:
    return _il.serial_digests()


def _scan_serials(rel: str, data: bytes, hits: list[str], what: str = "content") -> None:
    """Volume serial numbers (identity_lock.find_serial_hits): this machine's, and any 'Volume Serial Number is' header. A machine
    whose serials cannot be read refuses, because the preflight would otherwise certify what it cannot see."""
    digests = _serial_digests()
    if not digests:
        hits.append(f"{rel}: volume serials are not readable on this machine; the preflight cannot rule out a serial")
    kinds = _il.find_serial_hits(data, digests)
    if "live" in kinds:
        hits.append(f"{rel}: {what} carries a volume serial number of this machine")
    if "header" in kinds:
        hits.append(f"{rel}: {what} carries a 'Volume Serial Number is' header")


def _scan_identity(rel: str, text: str, hits: list[str]) -> None:
    _scan_serials(rel, text.encode('utf-8', 'surrogatepass'), hits)
    hosts, users = _il.find_hits(text.encode('utf-8', 'surrogatepass'))
    if hosts:
        hits.append(f"{rel}: identity string (host name, digest match)")
    if users:
        hits.append(f"{rel}: identity string (operator name, digest match)")


def _scan_text(rel: str, text: str, deny: tuple[str, ...], hits: list[str], wide: bool = False) -> None:
    _scan_text_patterns(rel, text, deny, hits, wide)
    _scan_identity(rel, text, hits)


def _scan_text_patterns(rel: str, text: str, deny: tuple[str, ...], hits: list[str], wide: bool = False) -> None:
    low = text.lower()
    for s in deny:
        if s.lower() in low:
            hits.append(f"{rel}: contains identity string '{s}'")
    path = find_abs_path(text, wide)
    if path:
        hits.append(f"{rel}: absolute local path '{path[:60]}'")
    if _SID.search(text):
        hits.append(f"{rel}: machine-domain SID shape")
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

    ``allow_keys`` exempts named text keys (e.g. grader diagnostics) and is always an explicit, visible flag.

    Unreadable input (a gzip member that does not decompress, wide-character text that does not decode) and any per-file failure
    (permission, an unencodable name, a JSON document nested past the recursion limit) is a named problem, never an exception, and the
    rest of the problem list is still produced. A file name that carries a SID is shown as ``file #n`` on every line.

    SIDs: a file whose content or name carries any ``S-1-5-21-<a>-<b>-<c>`` (``identity_lock.find_sid_hits``: the lock the scrub's
    ``--check`` uses, so it reads the plain bytes, gzip members, UTF-16 with or without a BOM and the escaped shapes the rewrite
    clears) is refused. It does not compare against the running machine's own domain: ``S-1-5-21`` is the machine-or-domain
    account authority, so a foreign value names a real machine or domain just as this machine's does, and the scrub rewrites every
    such value, not only this machine's. A check keyed on the live domain would pass a foreign SID and would refuse nothing when
    the domain cannot be read. The scrubbed ``S-1-5-21-__MACHINE__`` and the integrity, AppContainer and BUILTIN SIDs
    (``S-1-16-*``, ``S-1-15-*``, ``S-1-5-32-*``) do not match and pass. A Microsoft-account or Entra ID account SID
    (``identity_lock.find_account_sid_hits``) in the content or the name is refused the same way; ``__ACCOUNT__`` passes."""
    allow = frozenset(k.lower() for k in allow_keys)
    hits: list[str] = []
    sid_named: dict[str, str] = {}  # names that carry a SID; every FAIL line shows them as ``file #n``
    if not root.is_dir():
        return [f"{root}: not a directory"]
    files = _files(root)
    if not files:
        return [f"{root}: no files to upload"]
    deny = DENY_STRINGS + env_identity_strings() + tuple(extra_deny)
    for p in files:
        rel = p.relative_to(root).as_posix()
        try:
            rel.encode("utf-8")
            hidden = _il.find_sid_hits(rel.encode("utf-8")) or _il.find_account_sid_hits(rel.encode("utf-8"))
        except UnicodeEncodeError:
            hidden = True
        if hidden:  # a name that carries a SID, or cannot be encoded, is shown as ``file #n`` on every line, size-cap line included
            sid_named[rel] = f"file #{len(sid_named)}"
        try:
            size = p.stat().st_size
            if size > max_bytes:
                hits.append(f"{rel}: {size} bytes exceeds cap {max_bytes}")
                continue
            raw = p.read_bytes()
            unreadable = _il.unreadable_reason(raw)
            if unreadable:
                hits.append(f"{rel}: {unreadable}")
            if _il.find_sid_hits(raw):
                hits.append(f"{rel}: machine/domain account SID (S-1-5-21-...) in the content, plain, gzip, UTF-16 or escaped")
            if _il.find_sid_hits(rel.encode("utf-8")):
                hits.append(f"{rel}: file name carries a machine/domain account SID (S-1-5-21-...)")
            if _il.find_account_sid_hits(raw):
                hits.append(f"{rel}: Microsoft-account or Entra ID account SID (S-1-11-96-... / S-1-12-1-...) in the content, plain, gzip, UTF-16 or escaped")
            if _il.find_account_sid_hits(rel.encode("utf-8")):
                hits.append(f"{rel}: file name carries a Microsoft-account or Entra ID account SID")
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                hits.append(f"{rel}: not valid UTF-8 (binary or other encoding)")
                continue
            for d in deny:  # the file NAME can leak too: identity strings and credential/e-mail shapes
                if d.lower() in rel.lower():
                    hits.append(f"{rel}: file name contains identity string '{d}'")
            name_hosts, name_users = _il.find_hits(rel.encode("utf-8"))  # by digest: holds under any account
            if name_hosts or name_users:
                hits.append(f"{rel}: file name carries this machine's identity (digest match)")
            _scan_serials(rel, rel.encode("utf-8"), hits, "file name")
            for label, pat in _SECRET_PATTERNS:
                if pat.search(rel):
                    hits.append(f"{rel}: file name matches a {label}")
            wide = _declares_nep5(root, p)
            name_path = find_abs_path(rel, wide=True)  # a file name can carry a path or a machine SID as well as content
            if name_path:
                hits.append(f"{rel}: file name carries an absolute local path '{name_path}'")
            if _SID.search(rel):
                hits.append(f"{rel}: file name carries a machine-domain SID shape")
            _scan_text(rel, text, deny, hits, wide)
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
                    _scan_text(rel, chr(10).join(strings), deny, hits, wide)
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
                _scan_text(rel, chr(10).join(strings), deny, hits, wide)
            elif suffix == ".csv":
                _scan_csv(rel, text, allow, hits, nep5=wide)
        except (OSError, UnicodeError, ValueError, RecursionError, MemoryError) as e:
            hits.append(f"{rel}: could not be checked ({type(e).__name__}); refused")
    for real, label in sid_named.items():
        hits = [h.replace(real, label) for h in hits]
    return list(dict.fromkeys(_il.redact_serials(h, _serial_digests()) for h in hits))  # a finding that names a file never prints its serial


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


def _declares_nep5(root: Path, csv_path: Path) -> bool:
    """True when any ``manifest.json`` at or above the file (not above ``root``) declares NEP5_SCHEMA. A nested manifest
    that does not declare it never opts its subtree out of the scope a parent declares."""
    d = csv_path.parent
    while True:
        m = d / "manifest.json"
        if m.is_file():
            try:
                doc = json.loads(m.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                doc = None
            if isinstance(doc, dict) and doc.get("schema") == NEP5_SCHEMA:
                return True
        if d == root or root not in d.parents:
            return False
        d = d.parent


def _check_csv_header(rel: str, header: list[str], hits: list[str]) -> bool:
    """Refuse an empty or duplicate column name outright (a nameless or shadowed column escapes the per-cell checks).
    Returns True when the header is acceptable."""
    ok = True
    if any(not c.strip() for c in header):
        hits.append(f"{rel}: header has an empty column name; its cells would escape every per-cell check")
        ok = False
    seen: set[str] = set()
    for c in header:
        lc = c.strip().lower()
        if lc and lc in seen:
            hits.append(f"{rel}: duplicate column name '{c}'; the shadowed copy would escape every per-cell check")
            ok = False
        seen.add(lc)
    return ok


def _cell_ok(lk: str, v: str, nep5: bool) -> bool:
    if lk in NUMERIC_COLUMNS or (nep5 and lk in NEP5_NUMERIC_COLUMNS):
        return v == "" or bool(_NUMERIC_CELL.match(v)) or v in ("True", "False", "None")
    if lk in HASH_COLUMNS or (nep5 and lk in NEP5_HASH_COLUMNS):
        return v == "" or bool(_HASH_CELL.match(v))
    if not (_ID_CELL.match(v) and not (lk in TEXT_KEYS and len(v) > SHORT_LABEL_MAX)):
        return False
    check = NEP5_VALUE_CHECKS.get(lk) if nep5 else None
    if check is None or v == "":
        return True
    return v in check if isinstance(check, frozenset) else bool(check.match(v))


def _scan_csv(rel: str, text: str, allow: frozenset[str], hits: list[str], nep5: bool = False) -> None:
    import csv
    import io

    rows = csv.reader(io.StringIO(text, newline=""))
    header = next(rows, None)
    if header is None:
        return
    known = KNOWN_CSV_COLUMNS | frozenset(NEP5_COLUMNS) if nep5 else KNOWN_CSV_COLUMNS
    if not _check_csv_header(rel, header, hits):
        return
    for c in sorted(c for c in header if c.lower() not in known and c.lower() not in allow):
        hits.append(f"{rel}: column '{c}' is not a known metric column")
    bad: set[str] = set()
    bad_path: dict[str, str] = {}
    extra = False
    for row in rows:
        if len(row) > len(header):
            extra = True
        for k, v in zip(header, row):
            lk = k.lower()
            path = find_abs_path(v, wide=True)  # a cell is a label or a number: no path root is a quotation in one
            if path:
                bad_path.setdefault(k, path)
            if lk in allow:
                continue
            if not _cell_ok(lk, v, nep5) or len(v) > CSV_CELL_MAX:
                bad.add(k)
    if extra:
        hits.append(f"{rel}: row with more cells than the header; the extra cells are unchecked free text")
    for k in sorted(bad):
        hits.append(f"{rel}: generated-text column '{k}' (cell is not numeric / hash / short id as the column requires)")
    for k in sorted(bad_path):
        hits.append(f"{rel}: absolute local path '{bad_path[k][:60]}' in a cell of column '{k}'")


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


def card_check(text: str, config: str | None = None, path_in_repo: str | None = None,
               require_headings: tuple[str, ...] = ()) -> list[str]:
    """Return failed check names. With config/path_in_repo, also require the front-matter entry; each
    ``require_headings`` text must appear as a whole markdown heading line."""
    failed = [name for name, pat in _CARD_CHECKS if not re.search(pat, text)]
    for h in require_headings:
        if not re.search(rf"(?m)^#{{1,6}}[ \t]+{re.escape(h.strip())}[ \t]*\r?$", text):
            failed.append(f"required heading: {h}")
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


def _scan_target_text(config: str, path_in_repo: str, message: str | None, deny: tuple[str, ...],
                      wide: bool = False) -> str | None:
    """Config, path-in-repo and commit message become permanent public metadata: scan them like file content."""
    hits: list[str] = []
    for name, value in (("--config", config), ("--path-in-repo", path_in_repo), ("--message", message)):
        if value:
            hits += preflight_text(name, value, deny, wide)
    return "; ".join(hits) if hits else None


def _validate_target(config: str, path_in_repo: str, message: str | None = None, deny: tuple[str, ...] = (),
                     wide: bool = False) -> str | None:
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
    return _scan_target_text(config, path_in_repo, message, deny, wide)


_DATA_FILE_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*\.csv")


def manifest_data_file_problem(root: Path) -> str | None:
    """A refusal text when the dataset manifest carries ``hf_default_data_file`` and it does not name an existing
    ``.csv`` directly under ``root`` (no separator, no ``..``); None when the key is absent or valid."""
    try:
        doc = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict) or "hf_default_data_file" not in doc:
        return None
    named = doc["hf_default_data_file"]
    if not (isinstance(named, str) and _DATA_FILE_NAME.fullmatch(named) and ".." not in named):
        return f"manifest.json key hf_default_data_file {named!r} must name a .csv directly under the dataset directory"
    if not (root / named).is_file():
        return f"manifest.json key hf_default_data_file names '{named}', which is not a file in the dataset directory"
    return None


def _data_file(root: Path, explicit: str | None) -> str | None:
    """The data file the config lists: ``--data-file``, else the dataset manifest's ``hf_default_data_file`` (the
    author's choice of headline table; ``manifest_data_file_problem`` refuses an invalid one before this is read), else
    ``speed_visits.csv``, else the first CSV by name."""
    if explicit:
        return explicit
    try:
        doc = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        doc = None
    named = doc.get("hf_default_data_file") if isinstance(doc, dict) else None
    if isinstance(named, str) and named and (root / named).is_file():
        return named
    if (root / "speed_visits.csv").is_file():
        return "speed_visits.csv"
    csvs = sorted(p.relative_to(root).as_posix() for p in root.rglob("*.csv"))
    return csvs[0] if csvs else None


# R4-1: a dataset whose manifest lists ``cited_repository_paths`` (paths its card names as carried by the public
# snapshot) is uploaded only while the public mirror's ref carries every one of them.
PUBLIC_REF = "refs/public-snapshots/main"  # the ref the public-mirror sync keeps (scripts/check_public_mirror_sync.py)
# Only the public mirror's refs are accepted: never HEAD or a private branch.
_REF_RE = re.compile(r"refs/(?:remotes/public|public-snapshots)/[A-Za-z0-9_][A-Za-z0-9_./-]*")
_CITED_PATH_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./-]*")


def _blobs(top: str, ref: str, path: str) -> tuple[dict[str, str] | None, str]:
    """{file path: blob id} of every file under ``path`` at ``ref`` (``git ls-tree -r``), or (None, reason)."""
    try:
        res = subprocess.run(["git", "-C", top, "ls-tree", "-r", ref, "--", path], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        return None, f"git could not run ({e})"
    if res.returncode != 0:
        return None, f"ref '{ref}' does not resolve ({(res.stderr or '').strip()[-120:]})"
    out: dict[str, str] = {}
    for ln in res.stdout.splitlines():
        meta, _, name = ln.partition("\t")
        parts = meta.split()
        if len(parts) == 3 and name:
            out[name] = parts[2]
    return out, ""


def mirror_problems(root: Path, ref: str = PUBLIC_REF, repo: Path | None = None,
                    source_repo: Path | None = None) -> list[str]:
    """Problems with the manifest's ``cited_repository_paths`` against the public mirror ref. Fail-closed: a ref outside
    ``refs/remotes/public/*`` and ``refs/public-snapshots/*``, a ref that does not resolve, a git failure, a malformed
    list, a path with no file on the mirror, or any difference in the files under the path (a missing file, a different
    blob id, an extra file) between the mirror ref and ``HEAD`` of ``source_repo`` is a problem."""
    try:
        doc = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(doc, dict) or "cited_repository_paths" not in doc:
        return []
    paths = doc["cited_repository_paths"]
    if not (isinstance(paths, list) and paths and all(isinstance(x, str) for x in paths)):
        return ["manifest.json key cited_repository_paths must be a non-empty list of paths"]
    if not _REF_RE.fullmatch(ref) or ".." in ref:
        return [f"public ref '{ref}' must be under refs/remotes/public/ or refs/public-snapshots/"]
    here = str(Path(__file__).resolve().parents[1])
    mirror_top = str(repo if repo is not None else here)
    source_top = str(source_repo if source_repo is not None else here)
    problems: list[str] = []
    for path in paths:
        if not _CITED_PATH_RE.fullmatch(path) or ".." in path.split("/"):
            problems.append(f"cited path {path!r} is not a plain repository-relative path")
            continue
        mirror, why = _blobs(mirror_top, ref, path)
        if mirror is None:
            problems.append(f"cited path '{path}': {why}")
            continue
        if not mirror:
            problems.append(f"cited path '{path}' is absent from the public mirror ({ref}); the card says the public "
                            "snapshot carries it, so sync the snapshot first")
            continue
        source, why = _blobs(source_top, "HEAD", path)
        if source is None:
            problems.append(f"cited path '{path}': {why}")
        elif source != mirror:
            diff = sorted(k for k in set(source) | set(mirror) if source.get(k) != mirror.get(k))
            problems.append(f"cited path '{path}' differs between the public mirror ({ref}) and HEAD in {len(diff)} file(s), "
                            f"first {diff[0]!r}; the card says the snapshot carries the same files, so sync the snapshot")
    return problems


def _release_problems(a, root: Path) -> list[str]:
    return ([p for p in [manifest_data_file_problem(root)] if p]
            + mirror_problems(root, a.public_ref, Path(a.mirror_repo) if a.mirror_repo else None,
                              Path(a.source_repo) if a.source_repo else None))


def front_matter_lines(config: str, path_in_repo: str, data_file: str | None) -> str:
    df = data_file or "<primary>.csv"
    return f"  - config_name: {config}\n    data_files: {path_in_repo}/{df}\n"


def upload_command(root: Path, path_in_repo: str, message: str) -> list[str]:
    # Options first, then '--', then the positionals: nothing after the separator can be parsed as a flag.
    return [hf_exe(), "upload", "--repo-type", "dataset", "--commit-message", message, "--", REPO, str(root), path_in_repo]


def cmd_plan(a) -> int:
    root = Path(a.dir)
    wide = _declares_nep5(root, root / "manifest.json")
    err = _validate_target(a.config, a.path_in_repo, a.message, tuple(a.deny), wide)
    if err:
        print(f"FAIL {err}")
        return 2
    hits = preflight(root, a.max_bytes, tuple(a.deny), tuple(a.allow_key))
    files = _files(root) if root.is_dir() else []
    print(f"repo: {REPO} (dataset)")
    print(f"files ({len(files)}) -> {a.path_in_repo}/")
    for p in files:
        print(f"  {p.relative_to(root).as_posix()}  {p.stat().st_size}")
    release = _release_problems(a, root)
    print("card front-matter (configs: block of the repo README.md) needs:")
    print(front_matter_lines(a.config, a.path_in_repo, _data_file(root, a.data_file)), end="")
    try:
        print("command: " + " ".join(upload_command(root, a.path_in_repo, a.message or "<message>")))
    except HfExeMissing as e:
        print(f"hf CLI: {e}")
    print(f"preflight: {'CLEAN' if not hits else str(len(hits)) + ' problem(s)'}")
    for h in hits:
        print(f"  {h}")
    for r in release:
        print(f"REFUSED {r}")
    return 2 if release else (0 if not hits else 1)


def cmd_upload(a) -> int:
    root = Path(a.dir)
    wide = _declares_nep5(root, root / "manifest.json")
    err = _validate_target(a.config, a.path_in_repo, a.message, tuple(a.deny), wide)
    if err:
        print(f"FAIL {err}")
        return 2
    hits = preflight(root, a.max_bytes, tuple(a.deny), tuple(a.allow_key))
    hits += preflight_text("--message", a.message, tuple(a.deny), wide)  # the commit message is public too
    hits += _release_problems(a, root)
    if hits:
        print("REFUSED: preflight failed; nothing uploaded")
        for h in hits:
            print(f"  {h}")
        return 1
    card_text = None
    if a.card:
        card_text = Path(a.card).read_text(encoding="utf-8")
        card_hits = preflight_text("card", card_text, tuple(a.deny), wide)
        failed = card_check(card_text, a.config, a.path_in_repo, tuple(a.require_heading)) + card_hits
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


def preflight_text(rel: str, text: str, deny: tuple[str, ...], wide: bool = False) -> list[str]:
    hits: list[str] = []
    _scan_text(rel, text, DENY_STRINGS + env_identity_strings() + tuple(deny), hits, wide)
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
    failed = card_check(text, a.config, a.path_in_repo, tuple(a.require_heading))
    for name, _ in _CARD_CHECKS:
        print(f"{'FAIL' if name in failed else 'ok  '} {name}")
    for f in failed:
        if f.startswith(("front-matter", "required heading")):
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
            p.add_argument("--public-ref", default=PUBLIC_REF, help="ref of the public mirror the card's cited paths must exist on")
            p.add_argument("--mirror-repo", help="git repository holding that ref (default: this repository)")
            p.add_argument("--source-repo", help="git repository whose HEAD the mirror must equal under each cited path (default: this one)")

    p = sub.add_parser("preflight"); common(p, False); p.set_defaults(fn=cmd_preflight)
    p = sub.add_parser("plan"); common(p); p.add_argument("--message"); p.add_argument("--data-file"); p.set_defaults(fn=cmd_plan)
    p = sub.add_parser("upload"); common(p); p.add_argument("--message", required=True)
    p.add_argument("--card", help="updated dataset card to publish as README.md after the folder")
    p.add_argument("--require-heading", action="append", default=[], help="heading text the card must carry (repeatable)")
    p.set_defaults(fn=cmd_upload)
    p = sub.add_parser("verify"); common(p); p.set_defaults(fn=cmd_verify)
    p = sub.add_parser("card-check"); p.add_argument("--readme", required=True)
    p.add_argument("--config"); p.add_argument("--path-in-repo")
    p.add_argument("--require-heading", action="append", default=[], help="heading text the README must carry (repeatable)")
    p.set_defaults(fn=cmd_card_check)
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
