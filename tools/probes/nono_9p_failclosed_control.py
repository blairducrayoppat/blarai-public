r"""#1755 control for nono #2089: does a nono sandbox on a WSL 9P mount (/mnt/c) let a
process do something its OWN policy denies?

README
======
Question. nono grants paths on the command line. On a 9P mount the kernel may not
enforce what was granted. The first control (4 cases x 4 probes) found no
violation but never tested how the 9P server resolves Windows reparse points,
renames, links, `..`, alternate spellings of a path, or alternate data streams.
This script tests those, and answers the working-directory prompt properly.

Steps (the fixture needs Windows-side objects, so prepare, pre-flight and cleanup
run on Windows python, the live run runs inside WSL):

  1. Windows, an ELEVATED shell for the symlink probes (junctions need no elevation):
       python <this file> --prepare-windows [--fixture p1755-NAME]
     Prints the fixture name and writes C:\wsl\<fixture>.prepare.json (what was
     created, what failed and why, secrets, 8.3 names, host facts). A link kind
     that could not be created is named at the end; its probes read INCONCLUSIVE.
  1b. Windows, optional but advised:
       python <this file> --preflight-windows --fixture <fixture>
     Drives every probe at the fixture with a runner that enforces nothing. Each
     denied-by-policy probe must then read POLICY_VIOLATION, which shows the probe
     can see a leak through that junction, link, spelling or stream. It says
     nothing about nono or 9P.
  2. WSL, root, in the distribution that has nono:
       python3 <wsl path of this file> --live --fixture <fixture> \
           --operator agent|LA --out <result.json> [--stdin-mode pty|piped]
     Refuses with exit 4 (INCONCLUSIVE) if the prepare record or the fixture is missing.
  3. Windows:
       python <this file> --cleanup-windows --fixture <fixture>
     First sweeps the ungranted folders from the Windows side; any entry or
     content change there prints the do-not-post notice, exits 10 and KEEPS the
     fixture (--force-cleanup removes it anyway). Then removes the links first
     (never through them), then the fixture and its record, and verifies removal.
     It refuses a folder without the fixture marker file. The live run never
     deletes the fixture.

Other modes: --self-test (in-memory model, no filesystem effects, no WSL; prints
the check count; run it inside WSL as well to exercise the pty runner),
--dry-run or no mode (prints the full command matrix and its size, starts nothing).

Cases (all with a throwaway fixture C:\wsl\<fixture>: leaf = the grant, other and
ungranted_long_dir = ungranted siblings):
  A  #2089 step 4  cwd /root/work   --allow leaf
  B  #2089 step 6  cwd /root/work   --read /mnt/c --allow leaf
  C  #2089 step 7  cwd leaf         --allow .
  D  #2089 step 5  cwd /root/work   --read <fixture> --allow leaf

Judgement. Each probe is judged against what the command line GRANTS, not against
what "should" work. A policy-denied operation that SUCCEEDS is POLICY_VIOLATION:
the run prints a do-not-post notice and exits 10 (publish NOTHING; use the
project's private security-advisory form, tell the LA first). Success is read
from OUTSIDE nono afterwards (the file exists on the Windows-visible side, or
the secret token is in the output). Effects are absent before each run, so a
success belongs to that run. Every probe also runs once OUTSIDE nono; if the
operation fails there the probe is INCONCLUSIVE (a denial inside means nothing).
A sandbox banner ("Applying sandbox") must appear, else INCONCLUSIVE.

Verdict classes: DENIED_AS_POLICY, ALLOWED_AS_POLICY, OVERDENIAL (policy allows,
sandbox denied: the #2089 finding), POLICY_VIOLATION, INCONCLUSIVE (reason on
the row). After the matrix a sweep lists the ungranted folders; an unexpected
file or changed content there is also FAIL_OPEN_SUSPECTED. NO_POLICY_VIOLATION_OBSERVED
means only that none was seen in the listed cases and runs; it is never "secure".

Exit codes: 0 done, none seen; 10 violation suspected; 4 inconclusive (nono or the
prepare record missing, nothing ran); 2 refused or bad usage; 1 self-test or
Windows-side step failed.

Working-directory prompt and review menu (--stdin-mode, default pty). nono skips its
prompt when stdin is not a terminal. In pty mode each nono run gets a pseudo-terminal
and "N" is sent when a yes/no prompt appears. Under a pty nono also opens an
interactive "Review denied paths" menu AFTER the command has run (keys: a grant-all,
d deny-all, Space cycle, Enter confirm, Esc cancel) and waits. The runner types Esc
there, after the key hints have been up for 0.3 s (nono ignores keys for about a
second after drawing it), repeats it every 2 s up to 3 times while the process
lives, and never types a, d, Space or Enter. The denied-path lines nono printed
there are kept on the row as nono_review_denied (nono's own statement of what it
denied). The path taken is on every row, as <prompt part>+<menu part>: prompt part
pty_prompt_answered_N, pty_no_prompt_seen, pty_answered_on_idle_cwd_text or
pty_timeout_no_prompt_pattern_matched; menu part review_cancelled (with _xN when Esc
was repeated), no_review_menu or review_menu_seen_unanswered; piped_* when pty was
not used. stdout and stderr are merged by a pty. If pty cannot be used the run falls
back to piped stdin and the row says so; that fallback is a stated limit, not an
equivalent.

A run that times out (exit 124, 60 s) always reads INCONCLUSIVE: an unfinished run
proves neither a denial nor an allowance. The one exception is the rule above all
others: an effect already seen from a denied operation is still POLICY_VIOLATION.
Six timeouts in a row abort the matrix, and an aborted matrix reads INCONCLUSIVE
overall (exit 4), never "none seen".

PROBE TABLE (policy per case A B C D; the reason for each policy class is in TARGETS)
  ID            Inside the sandbox                                              Policy
  W_OUT         write a file beside the grant                                   deny deny deny deny
  R_OUT         read other/secret.txt                                           deny allow deny allow
  W_IN          write a file inside the grant                                   allow allow allow allow
  L_IN          list the grant                                                  allow allow allow allow
  JCT_R         cat leaf/jct/secret.txt (junction to other)                     deny allow deny allow
  JCT_W         write leaf/jct/leak (lands in other)                            deny deny deny deny
  JCT_L         ls leaf/jct/                                                    deny allow deny allow
  DSD_REL_R     cat through a directory symlink, relative target                deny allow deny allow
  DSD_REL_W     write through it                                                deny deny deny deny
  DSD_REL_L     ls through it                                                   deny allow deny allow
  DSD_ABS_R     cat through a directory symlink, absolute target                deny allow deny allow
  DSD_ABS_W     write through it                                                deny deny deny deny
  DSD_ABS_L     ls through it                                                   deny allow deny allow
  FSL_REL_R     cat a file symlink, relative target, to other/secret.txt        deny allow deny allow
  FSL_REL_W     write a file symlink, relative target, to other/wtarget         deny deny deny deny
  FSL_ABS_R     cat a file symlink, absolute target, to other/secret.txt        deny allow deny allow
  FSL_ABS_W     write a file symlink, absolute target, to other/wtarget         deny deny deny deny
  MV_OUT        mv a file from the grant into other/ (via sh -c)                deny deny deny deny
  HL_IN         ln other/secret.txt into the grant (hard link)                  deny deny deny deny
  TRAV_R        cat leaf/../other/secret.txt                                    deny allow deny allow
  TRAV_W        write leaf/../leak                                              deny deny deny deny
  CASE_UP_R     read other/secret.txt spelled in UPPER CASE                     deny allow deny allow
  CASE_UP_W     write into other spelled in UPPER CASE                          deny deny deny deny
  CASE_MIX_R    read it spelled in Title Case                                   deny allow deny allow
  CASE_MIX_W    write into other spelled in Title Case                          deny deny deny deny
  S83_R         read ungranted_long_dir/secret_long_filename.txt by 8.3 names   deny allow deny allow
  S83_W         write into ungranted_long_dir by its 8.3 name                   deny deny deny deny
  ADS_R         read other/ads_host.txt:ads_stream (NTFS alternate stream)      deny allow deny allow
  ADS_W         write a new stream on other/ads_host.txt                        deny deny deny deny
  GRANT_CASE_R  read leaf/f.txt spelled in UPPER CASE                           allow allow allow allow
END PROBE TABLE

MV_OUT runs mv through sh -c because nono refuses a bare mv as the startup command
before it applies any sandbox (NONO_BLOCKED_STARTUP; the self-test model refuses it
the same way and checks no probe starts with a blocked command).

ADS_R reads a stream by name:stream. On the observed setup 9P does not address it:
the control outside nono fails with "No such file or directory", so ADS_R is
expected to read INCONCLUSIVE in every case; it stays as the record of that limit,
not as a probe result. ADS_W's control does succeed, but whether the entry it makes
is an NTFS stream or a plain file under a mapped name was not checked from the
Windows side, so its denial shows only that a write of a colon-named entry into the
ungranted folder is denied.

Policy basis for HL_IN: a hard link inside the write grant to a file the grant
does not cover would give write access to that file's content under a granted
name, so a success is treated as a violation in every case, including B and D
where the source is readable. A hard link or link kind the 9P server cannot create
fails its control and reads INCONCLUSIVE, with the error on the control record.

Environment record: kernel (read, never fixed), Landlock ABI (syscall query), nono
version and banner, findmnt options of /mnt/c, Bitdefender processes (from WSL and
from the prepare step), stdin mode and prompt paths taken, script SHA-256, Windows
facts (elevation, Developer Mode, 8.3 setting, WSL and .wslconfig) from prepare.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import datetime as dt
import hashlib
import importlib.util
import inspect
import io
import json
import os
import pathlib
import platform
import posixpath
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Callable
from typing import Any, NamedTuple, Protocol

TICKET = "#1755"
SCHEMA = 2
RUNS = 3
WIN_ROOT_NT = "C:\\wsl"
WIN_ROOT_WSL = "/mnt/c/wsl"
SANDBOX_MARKER = "Applying sandbox"
FIXTURE_RE = re.compile(r"^p1755-[a-z0-9][a-z0-9-]{0,30}\Z")
MARKER_FILE = "P1755_FIXTURE.txt"
LEAF, OTHER, LONG_DIR = "leaf", "other", "ungranted_long_dir"
LONG_FILE, LEAF_FILE = "secret_long_filename.txt", "f.txt"
ADS_HOST, ADS_STREAM = "ads_host.txt", "ads_stream"
WTARGETS = {"rel": "wtarget_rel.txt", "abs": "wtarget_abs.txt"}
ORIG = "orig"
MAX_CONSECUTIVE_TIMEOUTS = 6
# nono refuses these as the directly-invoked startup command, before it applies any sandbox ("Command 'mv' is
# blocked: Command blocking is deprecated in v0.33.0 and only checks the directly-invoked startup command").
# A probe that needs one runs it through `sh -c`, so the sandbox is applied and Landlock judges the operation.
NONO_BLOCKED_STARTUP = ("mv",)
# probes whose control outside nono is expected to fail on the observed setup, so INCONCLUSIVE is their result
EXPECTED_INCONCLUSIVE = {
    "ADS_R": "a stream read by name:stream is not addressable through 9P (cat: No such file or directory)",
}
CASE_IDS = ("A", "B", "C", "D")
VERDICTS = ("DENIED_AS_POLICY", "ALLOWED_AS_POLICY", "OVERDENIAL", "POLICY_VIOLATION", "INCONCLUSIVE")
NOT_MEASURED = [
    "virtiofs (needs .wslconfig change and wsl --shutdown)",
    "truncate, delete, chmod, utime and extended attributes",
    "links created from inside the sandbox; multi-hop links; links in nested folders",
    "reparse points other than junction and symlink (placeholders, app execution aliases)",
    "8.3 names of the granted path itself; case-sensitive-flagged folders",
    "alternate data streams on folders",
    "Windows-side changes while a run is in progress",
    "other mounts, other drives, UNC paths",
    "other nono versions, other kernels, non-root users",
    "network behaviour",
    "more than 3 runs per case and probe; one machine",
]
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
PROMPT_RE = re.compile(r"[\[(]\s*y(?:es)?\s*/\s*n(?:o)?\s*[\])]\s*[:>?]*\s*$", re.IGNORECASE)
CWD_WORDS_RE = re.compile(r"(?:current|working)\s+director|\bcwd\b", re.IGNORECASE)
BD_NAMES = {
    "bdservicehost.exe", "bdagent.exe", "bdredline.exe", "bdntwrk.exe", "bdparentalservice.exe",
    "bdsubwiz.exe", "bdwtxag.exe", "vsserv.exe", "updatesrv.exe", "seccenter.exe", "productagentservice.exe",
    "discoverysrv.exe", "epsecurityservice.exe", "epprotectedservice.exe", "epintegrationservice.exe",
    "epupdateservice.exe",
}
BD_PS = "Get-Process | Where-Object { $_.Company -like '*Bitdefender*' } | ForEach-Object { $_.ProcessName }"
TASKLIST_WSL = "/mnt/c/Windows/System32/tasklist.exe"
POWERSHELL_WSL = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"


class RunResult(NamedTuple):
    rc: int
    out: str
    err: str
    prompt_path: str
    review: tuple[str, ...] = ()  # the denied-path lines nono printed in its post-run review menu


class FS(Protocol):
    def lexists(self, path: str) -> bool: ...
    def read(self, path: str) -> str: ...
    def write(self, path: str, text: str) -> None: ...
    def remove(self, path: str) -> None: ...
    def listdir(self, path: str) -> list[str]: ...


Runner = Callable[[list[str], str], RunResult]
Check = Callable[[FS, int, str, str], tuple[bool, str]]


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


# --------------------------------------------------------------------------- fixture model
class Link(NamedTuple):
    name: str
    kind: str  # junction | dir_symlink | file_symlink
    target: str  # relative to the fixture root, "/" separated
    style: str  # abs | rel (junctions are always absolute)


LINKS = (
    Link("jct", "junction", OTHER, "abs"),
    Link("dsym_rel", "dir_symlink", OTHER, "rel"),
    Link("dsym_abs", "dir_symlink", OTHER, "abs"),
    Link("fsym_rel", "file_symlink", f"{OTHER}/secret.txt", "rel"),
    Link("fsym_abs", "file_symlink", f"{OTHER}/secret.txt", "abs"),
    Link("fsymw_rel", "file_symlink", f"{OTHER}/{WTARGETS['rel']}", "rel"),
    Link("fsymw_abs", "file_symlink", f"{OTHER}/{WTARGETS['abs']}", "abs"),
)


def cases(base: str) -> list[dict[str, Any]]:
    leaf, work = f"{base}/{LEAF}", "/root/work"
    return [
        {"id": "A", "ref": "#2089 step 4", "cwd": work, "flags": ["--allow", leaf]},
        {"id": "B", "ref": "#2089 step 6", "cwd": work, "flags": ["--read", "/mnt/c", "--allow", leaf]},
        {"id": "C", "ref": "#2089 step 7", "cwd": leaf, "flags": ["--allow", "."]},
        {"id": "D", "ref": "#2089 step 5", "cwd": work, "flags": ["--read", base, "--allow", leaf]},
    ]


def make_record(base: str, short: tuple[str, str] = ("UNGRAN~1", "SECRET~1.TXT")) -> dict[str, Any]:
    """A prepare record in the schema --prepare-windows writes (used by the dry run and the self-test)."""
    return {
        "schema": SCHEMA, "fixture": base.rsplit("/", 1)[-1], "wsl_base": base,
        "secrets": {k: f"S1755-{k}-{uuid.uuid4().hex}" for k in ("main", "long", "ads", "leaf")},
        "items": {ln.name: {"kind": ln.kind, "created": True, "error": None} for ln in LINKS},
        "short_names": {"created": True, "dir": short[0], "file": short[1], "error": None},
        "ads": {"created": True, "host": ADS_HOST, "stream": ADS_STREAM, "error": None},
    }


class Ctx:
    """Names of everything a probe may touch, from the prepare record; nothing is hard-coded per machine."""

    def __init__(self, base: str, record: dict[str, Any]) -> None:
        self.base, self.record = base, record
        self.secrets: dict[str, str] = record["secrets"]
        self.leaf, self.other = f"{base}/{LEAF}", f"{base}/{OTHER}"
        self.long_dir = f"{base}/{LONG_DIR}"

    @property
    def short_dir(self) -> str:
        return str((self.record.get("short_names") or {}).get("dir"))

    @property
    def short_file(self) -> str:
        return str((self.record.get("short_names") or {}).get("file"))

    def missing(self, needs: tuple[str, ...]) -> str | None:
        """A reason string when a fixture item a probe needs was not created, else None."""
        for need in needs:
            if need.startswith("link:"):
                item = (self.record.get("items") or {}).get(need[5:])
                if not item or not item.get("created"):
                    return f"{need}: {(item or {}).get('error') or 'not in the prepare record'}"
            else:
                key = {"short83": "short_names", "ads": "ads"}[need]
                item = self.record.get(key) or {}
                if not item.get("created"):
                    return f"{need}: {item.get('error') or 'not in the prepare record'}"
        return None

    def respell(self, path: str, how: str) -> str:
        """The part of a /mnt/c path below the mount point, in UPPER or Title case."""
        head = "/mnt/c"
        if not path.startswith(head + "/"):
            raise ValueError(path)
        tail = path[len(head):]
        if how == "up":
            return head + tail.upper()
        return head + "/".join(seg.title() for seg in tail.split("/"))


# --------------------------------------------------------------------------- probes
class Probe(NamedTuple):
    id: str
    group: str
    target: str
    needs: tuple[str, ...]
    summary: str


class Spec:
    """argv to run inside the sandbox, and how to read its effect from OUTSIDE it."""

    def __init__(self, argv: list[str], check: Check, setup: Callable[[FS], None] | None = None,
                 cleanup: Callable[[FS], list[str]] | None = None) -> None:
        self.argv, self.check = argv, check
        self.setup = setup or (lambda fs: None)
        self.cleanup = cleanup or (lambda fs: [])


TARGETS = {
    "write_ungranted": "deny in every case: no case grants write outside leaf",
    "read_ungranted": "allow in B and D (they grant read there), deny in A and C",
    "link_ungranted": "deny in every case: a link into the write grant needs write rights on the source",
    "granted": "allow in every case: inside the write grant",
}
PROBES: dict[str, Probe] = {}
BUILDERS: dict[str, Callable[[Ctx, str, str], Spec]] = {}


def policy(case_id: str, probe_id: str) -> str:
    """What the command line grants for this probe: 'allow' or 'deny'."""
    target = PROBES[probe_id].target
    if target == "granted":
        return "allow"
    if target in ("write_ungranted", "link_ungranted"):
        return "deny"
    if target == "read_ungranted":
        return "allow" if case_id in ("B", "D") else "deny"
    raise ValueError(target)


def _add(pid: str, group: str, target: str, summary: str, needs: tuple[str, ...],
         build: Callable[[Ctx, str, str], Spec]) -> None:
    PROBES[pid] = Probe(pid, group, target, needs, summary)
    BUILDERS[pid] = build


def _rm_all(fs: FS, paths: list[str]) -> list[str]:
    errs = []
    for path in paths:
        try:
            if fs.lexists(path):
                fs.remove(path)
        except OSError as exc:
            errs.append(f"{path}: {exc}")
    return errs


def _need_clean(fs: FS, paths: list[str]) -> None:
    errs = _rm_all(fs, paths)
    if errs:
        raise OSError("stale effect could not be removed: " + "; ".join(errs))


def read_spec(path: str, expect: str) -> Spec:
    return Spec(["cat", path], lambda fs, rc, out, err: (expect in out, "token in output" if expect in out else ""))


def list_spec(path: str, expect: str) -> Spec:
    # the name in the listing is the effect; the exit code is not consulted, so a listing that printed the
    # name and then hung or exited oddly is still seen
    return Spec(["ls", "-la", path], lambda fs, rc, out, err: (expect in out, f"exit {rc}"))


def write_spec(token: str, write_path: str, verify_path: str, restore: str | None = None) -> Spec:
    """Write through write_path; the effect is read at verify_path (the real location).

    restore: the file already exists (a link target); the effect is its content changing.
    """
    argv = ["sh", "-c", f"echo {token} > {shlex.quote(write_path)}"]

    def setup(fs: FS) -> None:
        if restore is None:
            _need_clean(fs, [verify_path, write_path])
        else:
            fs.write(verify_path, restore + "\n")

    def check(fs: FS, rc: int, out: str, err: str) -> tuple[bool, str]:
        if not fs.lexists(verify_path):
            return False, ""
        text = fs.read(verify_path)
        if restore is not None:
            return text.strip() != restore, "target content changed" if text.strip() != restore else ""
        return True, "file present, token present" if token in text else "file present, token ABSENT (empty file)"

    def cleanup(fs: FS) -> list[str]:
        if restore is not None:
            try:
                fs.write(verify_path, restore + "\n")
            except OSError as exc:
                return [f"{verify_path}: {exc}"]
            return []
        return _rm_all(fs, [verify_path, write_path])

    return Spec(argv, check, setup, cleanup)


def _build_base() -> None:
    _add("W_OUT", "base", "write_ungranted", "write a file beside the grant", (),
         lambda c, tag, tok: write_spec(tok, f"{c.base}/leak_{tag}.txt", f"{c.base}/leak_{tag}.txt"))
    _add("R_OUT", "base", "read_ungranted", "read a secret in an ungranted sibling", (),
         lambda c, tag, tok: read_spec(f"{c.other}/secret.txt", c.secrets["main"]))
    _add("W_IN", "base", "granted", "write a file inside the grant", (),
         lambda c, tag, tok: write_spec(tok, f"{c.leaf}/win_{tag}.txt", f"{c.leaf}/win_{tag}.txt"))
    _add("L_IN", "base", "granted", "list the grant", (),
         lambda c, tag, tok: list_spec(c.leaf, LEAF_FILE))


def _build_reparse() -> None:
    def dir_link(name: str, label: str, what: str) -> None:
        need = (f"link:{name}",)
        _add(f"{label}_R", "reparse", "read_ungranted", f"cat through the {what} {name}", need,
             lambda c, tag, tok: read_spec(f"{c.leaf}/{name}/secret.txt", c.secrets["main"]))
        _add(f"{label}_W", "reparse", "write_ungranted", f"write through the {what} {name}", need,
             lambda c, tag, tok: write_spec(tok, f"{c.leaf}/{name}/leak_{tag}.txt", f"{c.other}/leak_{tag}.txt"))
        _add(f"{label}_L", "reparse", "read_ungranted", f"ls through the {what} {name}", need,
             lambda c, tag, tok: list_spec(f"{c.leaf}/{name}/", "secret.txt"))

    dir_link("jct", "JCT", "junction")
    dir_link("dsym_rel", "DSD_REL", "directory symlink")
    dir_link("dsym_abs", "DSD_ABS", "directory symlink")

    def file_link(label: str, rname: str, wname: str, wkey: str) -> None:
        _add(f"{label}_R", "reparse", "read_ungranted", f"cat the file symlink {rname}", (f"link:{rname}",),
             lambda c, tag, tok: read_spec(f"{c.leaf}/{rname}", c.secrets["main"]))
        _add(f"{label}_W", "reparse", "write_ungranted", f"write the file symlink {wname}", (f"link:{wname}",),
             lambda c, tag, tok: write_spec(tok, f"{c.leaf}/{wname}", f"{c.other}/{WTARGETS[wkey]}", restore=ORIG))

    file_link("FSL_REL", "fsym_rel", "fsymw_rel", "rel")
    file_link("FSL_ABS", "fsym_abs", "fsymw_abs", "abs")


def _mv_out(c: Ctx, tag: str, tok: str) -> Spec:
    src, dst = f"{c.leaf}/mvsrc_{tag}.txt", f"{c.other}/moved_{tag}.txt"

    def setup(fs: FS) -> None:
        _need_clean(fs, [dst, src])
        fs.write(src, tok + "\n")

    def check(fs: FS, rc: int, out: str, err: str) -> tuple[bool, str]:
        if not fs.lexists(dst):
            return False, ""
        return True, "moved file present" + (", token present" if tok in fs.read(dst) else ", token ABSENT")

    # through sh: nono refuses a bare `mv` as the startup command before it applies any sandbox
    argv = ["sh", "-c", f"mv {shlex.quote(src)} {shlex.quote(dst)}"]
    return Spec(argv, check, setup, lambda fs: _rm_all(fs, [dst, src]))


def _hl_in(c: Ctx, tag: str, tok: str) -> Spec:
    src, dst = f"{c.other}/secret.txt", f"{c.leaf}/hl_{tag}"

    def check(fs: FS, rc: int, out: str, err: str) -> tuple[bool, str]:
        if not fs.lexists(dst):
            return False, ""
        return True, "link present" + (", reads as the secret" if c.secrets["main"] in fs.read(dst) else "")

    return Spec(["ln", src, dst], check, lambda fs: _need_clean(fs, [dst]), lambda fs: _rm_all(fs, [dst]))


def _build_escape() -> None:
    _add("MV_OUT", "escape", "write_ungranted", "mv (via sh -c) a file from the grant into the ungranted sibling", (),
         _mv_out)
    _add("HL_IN", "escape", "link_ungranted", "hard-link an ungranted file into the grant", (), _hl_in)
    _add("TRAV_R", "escape", "read_ungranted", "cat leaf/../other/secret.txt", (),
         lambda c, tag, tok: read_spec(f"{c.leaf}/../{OTHER}/secret.txt", c.secrets["main"]))
    _add("TRAV_W", "escape", "write_ungranted", "write leaf/../leak", (),
         lambda c, tag, tok: write_spec(tok, f"{c.leaf}/../leak_{tag}.txt", f"{c.base}/leak_{tag}.txt"))


def _build_spelling() -> None:
    def case_pair(label: str, how: str) -> None:
        _add(f"{label}_R", "spelling", "read_ungranted", f"read the ungranted file spelled {how}", (),
             lambda c, tag, tok: read_spec(c.respell(f"{c.other}/secret.txt", how), c.secrets["main"]))
        _add(f"{label}_W", "spelling", "write_ungranted", f"write into the ungranted folder spelled {how}", (),
             lambda c, tag, tok: write_spec(tok, f"{c.respell(c.other, how)}/leak_{tag}.txt",
                                            f"{c.other}/leak_{tag}.txt"))

    case_pair("CASE_UP", "up")
    case_pair("CASE_MIX", "mix")
    short = ("short83",)
    _add("S83_R", "spelling", "read_ungranted", "read the ungranted long-named file by its 8.3 names", short,
         lambda c, tag, tok: read_spec(f"{c.base}/{c.short_dir}/{c.short_file}", c.secrets["long"]))
    _add("S83_W", "spelling", "write_ungranted", "write into the ungranted long-named folder by its 8.3 name", short,
         lambda c, tag, tok: write_spec(tok, f"{c.base}/{c.short_dir}/leak_{tag}.txt", f"{c.long_dir}/leak_{tag}.txt"))
    _add("ADS_R", "spelling", "read_ungranted", "read an alternate data stream of an ungranted file (expected "
         "INCONCLUSIVE: not addressable through 9P on the observed setup)", ("ads",),
         lambda c, tag, tok: read_spec(f"{c.other}/{ADS_HOST}:{ADS_STREAM}", c.secrets["ads"]))
    _add("ADS_W", "spelling", "write_ungranted", "write a new alternate data stream on an ungranted file", ("ads",),
         lambda c, tag, tok: write_spec(tok, f"{c.other}/{ADS_HOST}:ads_w_{tag}",
                                        f"{c.other}/{ADS_HOST}:ads_w_{tag}"))
    _add("GRANT_CASE_R", "spelling", "granted", "read the granted file spelled in UPPER CASE", (),
         lambda c, tag, tok: read_spec(c.respell(f"{c.leaf}/{LEAF_FILE}", "up"), c.secrets["leaf"]))


for _builder in (_build_base, _build_reparse, _build_escape, _build_spelling):
    _builder()


# --------------------------------------------------------------------------- judgement
def judge_run(pol: str, effect: bool | None, started: bool, control_ok: bool,
              timed_out: bool = False) -> tuple[str, str]:
    """(verdict, reason). A seen effect of a denied operation is a violation whatever else failed.

    A run that timed out never finished, so no effect seen proves neither a denial nor an allowance.
    """
    if effect is True and pol == "deny":
        return "POLICY_VIOLATION", ""
    if timed_out:
        return "INCONCLUSIVE", "the run timed out (exit 124) before nono finished; an unfinished run proves nothing"
    if not started:
        return "INCONCLUSIVE", f"sandbox banner '{SANDBOX_MARKER}' not seen: nono did not apply a sandbox"
    if not control_ok:
        return "INCONCLUSIVE", "the same operation failed OUTSIDE nono (control), so a denial proves nothing"
    if effect is None:
        return "INCONCLUSIVE", "the effect could not be read from outside the sandbox"
    if pol == "deny":
        return "DENIED_AS_POLICY", ""
    return ("ALLOWED_AS_POLICY" if effect else "OVERDENIAL"), ""


def overall(results: list[dict[str, Any]], sweep_alarm: bool = False, aborted: bool = False) -> str:
    verdicts = [r["verdict"] for r in results]
    if "POLICY_VIOLATION" in verdicts or sweep_alarm:
        return "FAIL_OPEN_SUSPECTED"
    if aborted or not verdicts or all(v == "INCONCLUSIVE" for v in verdicts):
        return "INCONCLUSIVE"
    return "NO_POLICY_VIOLATION_OBSERVED"


def tail_after_banner(text: str, n: int = 400) -> str:
    clean = strip_ansi(text).replace("\r", "")
    cut = clean.find(SANDBOX_MARKER)
    return (clean[cut + len(SANDBOX_MARKER):] if cut >= 0 else clean).strip()[-n:]


def execute(case: dict[str, Any], probe: Probe, ctx: Ctx, fs: FS, runner: Runner, tag: str,
            control: dict[str, Any]) -> dict[str, Any]:
    pol = policy(case["id"], probe.id)
    row: dict[str, Any] = {
        "case": case["id"], "ref": case["ref"], "probe": probe.id, "group": probe.group, "run_tag": tag,
        "cwd": case["cwd"], "policy": pol, "exit": None, "effect_seen": None, "detail": "",
        "prompt_path": None, "cleanup_errors": [], "reason": "", "nono_review_denied": [],
    }
    gap = ctx.missing(probe.needs)
    if gap:
        row.update(verdict="INCONCLUSIVE", reason=f"fixture item missing: {gap}", cmd="(not run)")
        return row
    token = uuid.uuid4().hex
    spec = BUILDERS[probe.id](ctx, tag, token)
    cmd = ["nono", "run"] + case["flags"] + ["--"] + spec.argv
    row["cmd"] = " ".join(shlex.quote(x) for x in cmd)
    try:
        spec.setup(fs)
    except OSError as exc:
        row.update(verdict="INCONCLUSIVE", reason=f"setup failed, not run: {exc}", cmd=row["cmd"])
        return row
    t0 = time.monotonic()
    try:
        res = runner(cmd, case["cwd"])
    except Exception as exc:  # noqa: BLE001 - a runner fault must read as INCONCLUSIVE, never as a denial
        res = RunResult(125, "", f"runner error: {exc!r}", "runner_error")
    row["seconds"] = round(time.monotonic() - t0, 2)
    effect: bool | None
    try:
        effect, detail = spec.check(fs, res.rc, res.out, res.err)
        row["detail"] = detail
    except Exception as exc:  # noqa: BLE001 - an unreadable effect is INCONCLUSIVE, never a denial
        effect, row["detail"] = None, f"check failed: {exc!r}"
    try:
        row["cleanup_errors"] = spec.cleanup(fs)
    except Exception as exc:  # noqa: BLE001 - a cleanup fault is recorded on the row, never swallowed
        row["cleanup_errors"] = [f"cleanup failed: {exc!r}"]
    started = SANDBOX_MARKER in (res.out + res.err)
    verdict, why = judge_run(pol, effect, started, bool(control.get("ok")), timed_out=(res.rc == 124))
    row.update(exit=res.rc, effect_seen=effect, prompt_path=res.prompt_path, started=started,
               verdict=verdict, reason=why, output_tail=tail_after_banner(res.out + "\n" + res.err, 700),
               skipped_prompt_text="Skipping CWD prompt" in (res.out + res.err),
               nono_review_denied=list(res.review))
    return row


def run_control(probe: Probe, ctx: Ctx, fs: FS, plain: Runner) -> dict[str, Any]:
    """The same operation OUTSIDE nono, once: it must succeed or the probe cannot conclude."""
    gap = ctx.missing(probe.needs)
    if gap:
        return {"probe": probe.id, "ok": False, "skipped": f"fixture item missing: {gap}"}
    spec = BUILDERS[probe.id](ctx, "ctl", uuid.uuid4().hex)
    try:
        spec.setup(fs)
        res = plain(spec.argv, "/root/work")
        effect, detail = spec.check(fs, res.rc, res.out, res.err)
        errs = spec.cleanup(fs)
    except Exception as exc:  # noqa: BLE001 - a failed control makes the probe INCONCLUSIVE
        return {"probe": probe.id, "ok": False, "error": repr(exc)}
    return {"probe": probe.id, "ok": bool(effect), "exit": res.rc, "detail": detail,
            "output_tail": strip_ansi(res.out + "\n" + res.err).strip()[-300:], "cleanup_errors": errs}


def run_matrix(case_list: list[dict[str, Any]], ctx: Ctx, fs: FS, runner: Runner, controls: dict[str, Any],
               runs: int = RUNS, say: Callable[[str], None] = print) -> tuple[list[dict[str, Any]], str | None]:
    results: list[dict[str, Any]] = []
    streak = 0
    for case in case_list:
        for probe in PROBES.values():
            letters = []
            for n in range(1, runs + 1):
                row = execute(case, probe, ctx, fs, runner, f"{case['id']}{probe.id}{n}", controls[probe.id])
                results.append(row)
                letters.append(row["verdict"][0])
                streak = streak + 1 if row["exit"] == 124 else 0
                if streak >= MAX_CONSECUTIVE_TIMEOUTS:
                    return results, f"aborted after {streak} consecutive timeouts at case {case['id']} probe {probe.id}"
            say(f"{case['id']} {probe.id:<13}{' '.join(letters)}")
    return results, None


def summary_table(results: list[dict[str, Any]]) -> str:
    cell: dict[tuple[str, str], dict[str, int]] = {}
    for r in results:
        d = cell.setdefault((r["probe"], r["case"]), {})
        d[r["verdict"][0]] = d.get(r["verdict"][0], 0) + 1
    lines = ["probe          " + "  ".join(f"{c:<8}" for c in CASE_IDS)
             + "   (D denied, A allowed, O overdenial, V VIOLATION, I inconclusive)"]
    for pid in PROBES:
        cells = ["".join(f"{k}{v}" for k, v in sorted(cell.get((pid, c), {}).items())) or "-" for c in CASE_IDS]
        lines.append(f"{pid:<14} " + "  ".join(f"{x:<8}" for x in cells))
    return "\n".join(lines)


NOTICE = ("\n*** A POLICY-DENIED OPERATION SUCCEEDED (or an ungranted folder changed). Do NOT post anything public. "
          "Use nono's private security advisory form and tell the LA first. ***")


def conclude(rec: dict[str, Any], out_path: str | None) -> int:
    rec["overall"] = overall(rec["results"], bool((rec.get("sweep") or {}).get("alarm")), bool(rec.get("aborted")))
    rec["counts"] = {k: sum(1 for r in rec["results"] if r["verdict"] == k) for k in VERDICTS}
    rec["inconclusive_probes"] = sorted({r["probe"] for r in rec["results"] if r["verdict"] == "INCONCLUSIVE"})
    rec["expected_inconclusive"] = EXPECTED_INCONCLUSIVE
    rec["unexpected_inconclusive_probes"] = [p for p in rec["inconclusive_probes"] if p not in EXPECTED_INCONCLUSIVE]
    if out_path:
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(rec, fh, indent=2)
    print(summary_table(rec["results"]))
    print("RESULT:", rec["overall"], rec["counts"], "->", out_path)
    if rec["inconclusive_probes"]:
        print("INCONCLUSIVE probes (read the reason on the row):", ", ".join(rec["inconclusive_probes"]))
        expected = [p for p in rec["inconclusive_probes"] if p in EXPECTED_INCONCLUSIVE]
        print("  expected INCONCLUSIVE:", ", ".join(expected) or "none",
              "| NOT expected:", ", ".join(rec["unexpected_inconclusive_probes"]) or "none")
    if rec["overall"] == "FAIL_OPEN_SUSPECTED":
        print(NOTICE)
        return 10
    return 4 if rec["overall"] == "INCONCLUSIVE" else 0


# --------------------------------------------------------------------------- sweep
def sweep(fs: FS, ctx: Ctx) -> dict[str, Any]:
    """After the matrix: nothing new in the ungranted folders, secrets and write targets unchanged."""
    expected = {
        ctx.base: {LEAF, OTHER, LONG_DIR, MARKER_FILE},
        ctx.other: {"secret.txt", *WTARGETS.values(), ADS_HOST},
        ctx.long_dir: {LONG_FILE},
    }
    problems: list[str] = []
    for folder, names in expected.items():
        try:
            got = set(fs.listdir(folder))
        except OSError as exc:
            problems.append(f"{folder}: cannot list ({exc})")
            continue
        problems += [f"{folder}: unexpected entry {n}" for n in sorted(got - names)]
        problems += [f"{folder}: expected entry missing {n}" for n in sorted(names - got)]
    content = {
        f"{ctx.other}/secret.txt": ctx.secrets["main"], f"{ctx.long_dir}/{LONG_FILE}": ctx.secrets["long"],
        f"{ctx.other}/{WTARGETS['rel']}": ORIG, f"{ctx.other}/{WTARGETS['abs']}": ORIG,
    }
    for path, want in content.items():
        try:
            if fs.read(path).strip() != want:
                problems.append(f"{path}: content changed")
        except OSError as exc:
            problems.append(f"{path}: unreadable ({exc})")
    try:
        in_grant = sorted(set(fs.listdir(ctx.leaf)) - {LEAF_FILE} - {ln.name for ln in LINKS})
    except OSError:
        in_grant = ["(cannot list)"]
    return {"alarm": bool(problems), "problems": problems, "leftovers_in_grant": in_grant}


# --------------------------------------------------------------------------- real filesystem and runners
class RealFS:
    def lexists(self, path: str) -> bool:
        return os.path.lexists(path)

    def read(self, path: str) -> str:
        with open(path, errors="replace") as fh:
            return fh.read()

    def write(self, path: str, text: str) -> None:
        with open(path, "w") as fh:
            fh.write(text)

    def remove(self, path: str) -> None:
        os.remove(path)

    def listdir(self, path: str) -> list[str]:
        return sorted(os.listdir(path))

    def link(self, src: str, dst: str) -> None:
        os.link(src, dst)

    def resolve(self, path: str) -> str:
        return path


class MappedFS(RealFS):
    """RealFS on Windows for the pre-flight: /mnt/c/... paths are served from C:/... (or wsl_root from nt_root)."""

    def __init__(self, wsl_root: str = "/mnt/c", nt_root: str = "C:") -> None:
        self.wsl_root, self.nt_root = wsl_root.rstrip("/"), nt_root.replace("\\", "/").rstrip("/")

    def _m(self, path: str) -> str:
        return self.nt_root + path[len(self.wsl_root):] if path.lower().startswith(self.wsl_root.lower() + "/") else path

    def lexists(self, path: str) -> bool:
        return super().lexists(self._m(path))

    def read(self, path: str) -> str:
        return super().read(self._m(path))

    def write(self, path: str, text: str) -> None:
        super().write(self._m(path), text)

    def remove(self, path: str) -> None:
        super().remove(self._m(path))

    def listdir(self, path: str) -> list[str]:
        return super().listdir(self._m(path))

    def link(self, src: str, dst: str) -> None:
        super().link(self._m(src), self._m(dst))


def run_plain(cmd: list[str], cwd: str | None = None, timeout: int = 60) -> RunResult:
    try:
        p = subprocess.run(cmd, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="replace",
                           timeout=timeout, check=False)
        return RunResult(p.returncode, p.stdout, p.stderr, "none")
    except FileNotFoundError:
        return RunResult(127, "", "not found", "none")
    except subprocess.TimeoutExpired:
        return RunResult(124, "", "timeout", "none")


def run_piped(cmd: list[str], cwd: str, timeout: int = 60) -> RunResult:
    """Stdin is a pipe carrying 'N': nono sees a non-interactive stdin and skips its prompt."""
    try:
        p = subprocess.run(cmd, cwd=cwd, input="N\n", capture_output=True, text=True, errors="replace", check=False,
                           timeout=timeout)
    except FileNotFoundError:
        return RunResult(127, "", "not found", "piped_stdin")
    except subprocess.TimeoutExpired:
        return RunResult(124, "", "timeout", "piped_stdin")
    text = p.stdout + p.stderr
    path = "piped_stdin_prompt_skipped" if "Skipping CWD prompt" in text else "piped_stdin_no_prompt_text"
    return RunResult(p.returncode, p.stdout, p.stderr, path)


def prompt_wanted(text: str) -> bool:
    """True when the tail of the terminal text is a yes/no prompt waiting for input."""
    return bool(PROMPT_RE.search(strip_ansi(text).replace("\r", "")[-300:]))


REVIEW_HEADER = "Review denied paths"
REVIEW_FOOTER = "Esc cancel"
ESC_KEY = b"\x1b"
CURSOR_REPORT = b"\x1b[24;80R"
_REVIEW_ENTRY_RE = re.compile(r"[A-Za-z][A-Za-z-]*\s+/\S")


def parse_review(text: str) -> tuple[str, ...]:
    """The denied-path lines in nono's post-run review menu, as nono printed them (menu redraws collapsed)."""
    start = text.find(REVIEW_HEADER)
    if start < 0:
        return ()
    seen: dict[str, None] = {}
    for line in text[start:].splitlines():
        entry = re.sub(r"^[^\w/]+", "", line.strip())  # drop the selection glyph
        if _REVIEW_ENTRY_RE.match(entry):
            seen.setdefault(re.sub(r"\s+", " ", entry), None)
    return tuple(list(seen)[:40])


class PtyDriver:
    """Decides what to type into nono's terminal from the text seen so far and the clock; it does no I/O.

    It types only two things: `answer` (N) at a yes/no prompt, and Esc at the post-run "Review denied paths"
    menu, which cancels the review. It never types a, d, Space or Enter there: those grant or confirm.
    nono ignores keys for about a second after drawing the menu and then redraws it with the key hints, so
    Esc goes out `settle` seconds after the hints appear, or after `menu_wait` seconds without them, and
    is repeated every `esc_every` seconds, at most `max_esc` times, while the process is still running.
    """

    def __init__(self, start: float, answer: str = "N", idle: float = 1.5, settle: float = 0.3,
                 menu_wait: float = 2.5, esc_every: float = 2.0, max_esc: int = 3) -> None:
        self.answer, self.idle, self.settle = answer, idle, settle
        self.menu_wait, self.esc_every, self.max_esc = menu_wait, esc_every, max_esc
        self.raw = bytearray()
        self.text = ""
        self.scan_from = 0
        self.answers = 0
        self.idle_answered = False
        self.last_data = start
        self.menu_at: float | None = None
        self.footer_at: float | None = None
        self.esc_sent = 0
        self.last_esc = float("-inf")

    def _answer(self) -> bytes:
        self.answers += 1
        self.scan_from = len(self.text)
        return (self.answer + "\n").encode()

    def feed(self, data: bytes, now: float) -> list[bytes]:
        """New terminal bytes arrived; returns what to type in reply."""
        self.raw += data
        self.last_data = now
        self.text = strip_ansi(self.raw.decode("utf-8", "replace")).replace("\r", "")
        sends: list[bytes] = []
        if b"\x1b[6n" in data:  # a terminal UI asking where the cursor is
            sends.append(CURSOR_REPORT)
        if self.menu_at is None and REVIEW_HEADER in self.text:
            self.menu_at = now
        if self.menu_at is not None:
            if self.footer_at is None and REVIEW_FOOTER in self.text:
                self.footer_at = now
        elif prompt_wanted(self.text[self.scan_from:]):
            sends.append(self._answer())
        return sends

    def tick(self, now: float) -> list[bytes]:
        """Time passed with or without new bytes; returns what to type."""
        if self.menu_at is not None:
            ready = ((self.footer_at is not None and now - self.footer_at >= self.settle)
                     or now - self.menu_at >= self.menu_wait)
            if ready and self.esc_sent < self.max_esc and now - self.last_esc >= self.esc_every:
                self.esc_sent += 1
                self.last_esc = now
                return [ESC_KEY]
        elif (self.answers == 0 and now - self.last_data > self.idle and CWD_WORDS_RE.search(self.text)
              and SANDBOX_MARKER not in self.text):  # still before the sandbox: a prompt of a shape not known
            self.idle_answered = True
            self.last_data = now
            return [self._answer()]
        return []

    def path(self, timed_out: bool) -> str:
        """Which way the run went, for the row: the working-directory prompt, then the review menu."""
        if self.idle_answered:
            base = "pty_answered_on_idle_cwd_text"
        elif self.answers:
            base = f"pty_prompt_answered_{self.answer}" + (f"x{self.answers}" if self.answers > 1 else "")
        elif timed_out and self.menu_at is None:
            base = "pty_timeout_no_prompt_pattern_matched"
        else:
            base = "pty_no_prompt_seen"
        if self.menu_at is None:
            return base + "+no_review_menu"
        if self.esc_sent:
            return base + "+review_cancelled" + (f"_x{self.esc_sent}" if self.esc_sent > 1 else "")
        return base + "+review_menu_seen_unanswered"


def run_pty(cmd: list[str], cwd: str, answer: str = "N", timeout: int = 60, idle: float = 1.5) -> RunResult:
    """Run under a pseudo-terminal, typing only what PtyDriver says."""
    import fcntl
    import pty
    import select
    import signal
    import struct
    import termios

    pid, fd = pty.fork()
    if pid == 0:
        try:
            os.chdir(cwd)
            os.execvp(cmd[0], cmd)
        except OSError as exc:
            os.write(2, f"exec failed: {exc}\n".encode())
        os._exit(127)
    with contextlib.suppress(OSError):
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 200, 0, 0))

    def send(chunks: list[bytes]) -> None:
        for chunk in chunks:
            with contextlib.suppress(OSError):  # the child may already be gone
                os.write(fd, chunk)

    t0 = time.monotonic()
    driver = PtyDriver(t0, answer=answer, idle=idle)
    timed_out = False
    while True:
        if time.monotonic() - t0 > timeout:
            timed_out = True
            break
        ready, _, _ = select.select([fd], [], [], 0.2)
        if ready:
            try:
                data = os.read(fd, 65536)
            except OSError:  # EIO: the child side closed
                break
            if not data:
                break
            send(driver.feed(data, time.monotonic()))
        send(driver.tick(time.monotonic()))
    if timed_out:
        with contextlib.suppress(OSError):
            os.killpg(pid, signal.SIGKILL)
    os.close(fd)
    _, status = os.waitpid(pid, 0)
    rc = 124 if timed_out else os.waitstatus_to_exitcode(status)
    return RunResult(rc, driver.text, "", driver.path(timed_out), parse_review(driver.text))


def pty_available() -> tuple[bool, str]:
    if os.name == "nt":
        return False, "no pty on this host"
    missing = [m for m in ("pty", "termios", "fcntl", "select") if importlib.util.find_spec(m) is None]
    return (False, "missing modules: " + ", ".join(missing)) if missing else (True, "")


def make_runner(stdin_mode: str) -> Runner:
    ok, why = pty_available()

    def runner(cmd: list[str], cwd: str) -> RunResult:
        if stdin_mode == "pty":
            if not ok:
                return run_piped(cmd, cwd)._replace(prompt_path=f"piped_fallback_pty_unavailable: {why}")
            try:
                return run_pty(cmd, cwd)
            except OSError as exc:
                return run_piped(cmd, cwd)._replace(prompt_path=f"piped_fallback_pty_error: {exc}")
        return run_piped(cmd, cwd)

    return runner


# --------------------------------------------------------------------------- environment record
def match_bitdefender(tasklist_csv: str) -> list[str]:
    hits = set()
    for row in csv.reader(io.StringIO(tasklist_csv)):
        if row:
            name = row[0].strip().lower()
            if name in BD_NAMES or "bitdefender" in name:
                hits.add(name)
    return sorted(hits)


def bitdefender_view(tasklist: str, powershell: str,
                     run: Callable[..., RunResult] | None = None) -> dict[str, Any]:
    """Bitdefender processes by two independent routes: image names, and the process Company field.

    status is 'absent' only when a route ran and found nothing; 'unknown' when neither could run.
    """
    run = run or run_plain
    t = run([tasklist, "/FO", "CSV", "/NH"], timeout=30)
    p = run([powershell, "-NoProfile", "-Command", BD_PS], timeout=60)
    view: dict[str, Any] = {
        "tasklist_names": match_bitdefender(t.out) if t.rc == 0 else None,
        "company_names": sorted({ln.strip().lower() for ln in p.out.splitlines() if ln.strip()}) if p.rc == 0 else None,
    }
    seen = [v for v in (view["tasklist_names"], view["company_names"]) if v is not None]
    view["status"] = "unknown" if not seen else ("present" if any(seen) else "absent")
    return view


def landlock_abi() -> Any:
    try:
        import ctypes
        libc = ctypes.CDLL(None, use_errno=True)
        value = libc.syscall(444, None, 0, 1)  # landlock_create_ruleset(NULL, 0, VERSION): a query, makes nothing
        return int(value) if value >= 0 else f"error errno={ctypes.get_errno()}"
    except Exception as exc:  # noqa: BLE001 - recorded in the environment record as text
        return f"unavailable: {exc!r}"


def read_text(path: str, limit: int = 400) -> str:
    try:
        with open(path, errors="replace") as fh:
            return fh.read(limit).strip()
    except OSError as exc:
        return f"unreadable: {exc}"


def command_fact(cmd: list[str], run: Callable[..., RunResult] | None = None) -> str:
    """A fact read from a command's output; a command that is absent or silent reads 'missing: ...'."""
    res = (run or run_plain)(cmd)
    text = res.out.strip()[:400]
    return text if res.rc == 0 and text else f"missing: {cmd[0]} exit {res.rc}, no output"


def env_record(stdin_mode: str) -> dict[str, Any]:
    sh = command_fact
    ok, why = pty_available()
    return {
        "utc": dt.datetime.now(dt.UTC).isoformat(),
        "tz": dt.datetime.now().astimezone().tzname(),
        "kernel": sh(["uname", "-r"]),
        "proc_version": read_text("/proc/version", 200),
        "distro": next((ln.split("=", 1)[1].strip('"') for ln in read_text("/etc/os-release", 4000).splitlines()
                        if ln.startswith("PRETTY_NAME=")), "unknown"),
        "python": platform.python_version(),
        "nono_path": shutil.which("nono"),
        "nono_version": sh(["nono", "--version"]),
        "uid": os.getuid(),
        "landlock_abi": landlock_abi(),
        "lsm": read_text("/sys/kernel/security/lsm"),
        "findmnt_c": sh(["findmnt", "-T", "/mnt/c", "-n", "-o", "TARGET,FSTYPE,OPTIONS"]),
        "mem_total_kb": next((ln.split()[1] for ln in read_text("/proc/meminfo", 400).splitlines()
                              if ln.startswith("MemTotal")), "?"),
        "bitdefender_wsl_view": (bitdefender_view(TASKLIST_WSL, POWERSHELL_WSL) if os.path.exists(TASKLIST_WSL)
                                 else {"status": "unknown", "why": "tasklist.exe not reachable from WSL (interop off?)"}),
        "stdin_mode": stdin_mode,
        "pty_available": ok, "pty_unavailable_reason": why,
        "script_sha256": hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),
    }


# --------------------------------------------------------------------------- Windows side: prepare and cleanup
FILE_ATTRIBUTE_DIRECTORY = 0x10
FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def win_attrs(path: str) -> int:
    return getattr(os.lstat(path), "st_file_attributes", 0)


def is_reparse(path: str) -> bool:
    return bool(win_attrs(path) & FILE_ATTRIBUTE_REPARSE_POINT)


def remove_link(path: str) -> None:
    """Remove a junction, directory symlink or file symlink itself, never what it points at."""
    if win_attrs(path) & FILE_ATTRIBUTE_DIRECTORY:
        os.rmdir(path)
    else:
        os.unlink(path)


def remove_tree_no_follow(path: str) -> None:
    """Delete a tree without ever listing or deleting through a reparse point."""
    if is_reparse(path):
        remove_link(path)
        return
    if win_attrs(path) & FILE_ATTRIBUTE_DIRECTORY:
        for name in os.listdir(path):
            remove_tree_no_follow(os.path.join(path, name))
        os.rmdir(path)
        return
    os.chmod(path, 0o666)
    os.unlink(path)


def parse_dir_x(listing: str, longname: str) -> str | None:
    """The 8.3 name `cmd /c dir /x` shows for longname, or None when it shows none."""
    for line in listing.splitlines():
        m = re.search(r"(\S+)\s+" + re.escape(longname) + r"\s*$", line)
        if m and "~" in m.group(1) and m.group(1).lower() != longname.lower():
            return m.group(1)
    return None


DIR_ENTRY_RE = re.compile(r"^\s*\d{1,4}[/.\-]\d{1,2}[/.\-]\d{1,4}\s")


def dir_entry_lines(listing: str) -> str:
    """Only the entry lines of a `dir` listing. The header (volume label and serial number), the directory
    line and the free-space footer name the machine, not the fixture, so they are never recorded."""
    return "\n".join(line for line in listing.splitlines() if DIR_ENTRY_RE.match(line))


def api_short_name(path: str) -> str | None:
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(520)
        n = ctypes.windll.kernel32.GetShortPathNameW(path, buf, 520)  # type: ignore[attr-defined]
        return os.path.basename(buf.value) if n else None
    except Exception:  # noqa: BLE001 - the cross-check is optional; dir /x stays the source
        return None


def make_link(link: Link, path: str, target_abs: str) -> None:
    if link.kind == "junction":
        p = subprocess.run(["cmd", "/c", "mklink", "/J", path, target_abs], capture_output=True, text=True, check=False)
        if p.returncode != 0:
            raise OSError(f"mklink /J exit {p.returncode}: {(p.stdout + p.stderr).strip()}")
        return
    arg = os.path.relpath(target_abs, os.path.dirname(path)) if link.style == "rel" else target_abs
    os.symlink(arg, path, target_is_directory=(link.kind == "dir_symlink"))


def windows_env(win_root: str) -> dict[str, Any]:
    import ctypes

    def best_effort(cmd: list[str], decode: str = "utf-8") -> str:
        try:
            p = subprocess.run(cmd, capture_output=True, timeout=30, check=False)
            return (p.stdout + p.stderr).decode(decode, "replace").replace("\x00", "").strip()[:1500]
        except Exception as exc:  # noqa: BLE001 - best-effort host fact, recorded as text
            return f"unavailable: {exc!r}"

    env: dict[str, Any] = {
        "platform": platform.platform(), "python": platform.python_version(),
        "elevated": bool(ctypes.windll.shell32.IsUserAnAdmin()),  # type: ignore[attr-defined]
        "fsutil_8dot3": best_effort(["fsutil", "8dot3name", "query", "C:"]),
        "fsutil_case_sensitivity": best_effort(["fsutil", "file", "queryCaseSensitiveInfo", win_root]),
        "wsl_version": best_effort(["wsl.exe", "--version"], "utf-16-le"),
        "wslconfig": read_text(os.path.join(os.path.expanduser("~"), ".wslconfig"), 1500),
        "bitdefender_windows_view": bitdefender_view("tasklist", "powershell"),
    }
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock")
        env["developer_mode"] = bool(winreg.QueryValueEx(key, "AllowDevelopmentWithoutDevLicense")[0])
    except OSError as exc:
        env["developer_mode"] = f"unknown: {exc}"
    return env


def prepare_windows(fixture: str, win_root: str = WIN_ROOT_NT, wsl_root: str = WIN_ROOT_WSL) -> int:
    if os.name != "nt":
        print("REFUSED: --prepare-windows runs on Windows python", file=sys.stderr)
        return 2
    if not FIXTURE_RE.match(fixture):
        print(f"REFUSED: fixture name must match {FIXTURE_RE.pattern}", file=sys.stderr)
        return 2
    base, rec_path = os.path.join(win_root, fixture), os.path.join(win_root, fixture) + ".prepare.json"
    if os.path.lexists(base) or os.path.lexists(rec_path):
        print(f"REFUSED: {base} or its record already exists; run --cleanup-windows or pick a new name",
              file=sys.stderr)
        return 2
    os.makedirs(base)
    put(os.path.join(base, MARKER_FILE), f"{TICKET} fixture; removed by --cleanup-windows only\n")
    secrets = {k: f"S1755-{k}-{uuid.uuid4().hex}" for k in ("main", "long", "ads", "leaf")}
    leaf, other, long_dir = (os.path.join(base, d) for d in (LEAF, OTHER, LONG_DIR))
    for d in (leaf, other, long_dir):
        os.makedirs(d)
    put(os.path.join(leaf, LEAF_FILE), secrets["leaf"] + "\n")
    put(os.path.join(other, "secret.txt"), secrets["main"] + "\n")
    put(os.path.join(other, ADS_HOST), "plain\n")
    for name in WTARGETS.values():
        put(os.path.join(other, name), ORIG + "\n")
    put(os.path.join(long_dir, LONG_FILE), secrets["long"] + "\n")

    items: dict[str, Any] = {}
    for link in LINKS:
        path = os.path.join(leaf, link.name)
        item: dict[str, Any] = {"kind": link.kind, "style": link.style, "path": path, "created": False,
                                "error": None, "verified": False, "verify_note": ""}
        try:
            make_link(link, path, os.path.join(base, *link.target.split("/")))
            item["created"] = True
            item["reparse_tag"] = hex(getattr(os.lstat(path), "st_reparse_tag", 0))
            if link.kind == "file_symlink":
                item["verified"] = get(path) in (secrets["main"], ORIG)
            else:
                item["verified"] = "secret.txt" in os.listdir(path)
        except OSError as exc:
            item["error"] = repr(exc)
            if getattr(exc, "winerror", None) == 1314:
                item["error"] += " (needs an elevated shell or Developer Mode)"
        except Exception as exc:  # noqa: BLE001 - recorded on the item as verify_note
            item["verify_note"] = f"verify failed: {exc!r}"
        items[link.name] = item

    ads: dict[str, Any] = {"created": False, "host": ADS_HOST, "stream": ADS_STREAM, "error": None}
    try:
        put(os.path.join(other, ADS_HOST) + ":" + ADS_STREAM, secrets["ads"] + "\n")
        ads["created"] = get(os.path.join(other, ADS_HOST) + ":" + ADS_STREAM) == secrets["ads"]
        ads["error"] = None if ads["created"] else "stream read-back differs"
    except OSError as exc:
        ads["error"] = repr(exc)

    listing = subprocess.run(["cmd", "/c", "dir", "/x", base], capture_output=True, text=True, check=False).stdout
    long_listing = subprocess.run(["cmd", "/c", "dir", "/x", long_dir], capture_output=True, text=True, check=False).stdout
    sd, sf = parse_dir_x(listing, LONG_DIR), parse_dir_x(long_listing, LONG_FILE)
    short: dict[str, Any] = {
        "created": bool(sd and sf), "dir": sd, "file": sf,
        "api_dir": api_short_name(long_dir), "api_file": api_short_name(os.path.join(long_dir, LONG_FILE)),
        "error": None if sd and sf else "dir /x shows no 8.3 name (8.3 creation disabled for this volume?)",
        "dir_x_base": dir_entry_lines(listing)[-1200:], "dir_x_long_dir": dir_entry_lines(long_listing)[-800:],
    }
    short["api_agrees"] = (short["api_dir"], short["api_file"]) == (sd, sf) if sd and sf else None

    env = windows_env(win_root)
    env["case_insensitive_on_windows"] = os.path.exists(
        os.path.join(win_root.upper(), fixture.upper(), "OTHER", "SECRET.TXT"))
    rec = {
        "schema": SCHEMA, "ticket": TICKET, "fixture": fixture, "created_utc": dt.datetime.now(dt.UTC).isoformat(),
        "win_base": base, "wsl_base": f"{wsl_root}/{fixture}", "secrets": secrets, "items": items,
        "short_names": short, "ads": ads, "windows": env,
    }
    with open(rec_path, "w", encoding="utf-8") as fh:
        json.dump(rec, fh, indent=2)
    print(f"PREPARED {base}\nrecord   {rec_path}")
    for name, item in items.items():
        state = "created" if item["created"] else "FAILED"
        print(f"  {name:<10} {item['kind']:<13} {state:<8} verified={item['verified']} {item['error'] or ''}")
    print(f"  8.3 names  {'created' if short['created'] else 'FAILED'}: {sd} / {sf}  {short['error'] or ''}")
    print(f"  ADS        {'created' if ads['created'] else 'FAILED'}  {ads['error'] or ''}")
    print(f"  elevated={env['elevated']} developer_mode={env['developer_mode']} "
          f"bitdefender={env['bitdefender_windows_view']}")
    not_made = [name for name, item in items.items() if not item["created"]]
    if not_made:
        print(f"  WARNING: {len(not_made)} link kinds were not created ({', '.join(not_made)}); their probes will "
              "read INCONCLUSIVE. For symlinks run this from an ELEVATED shell (after --cleanup-windows).")
    if env["bitdefender_windows_view"]["status"] == "unknown":
        print("  WARNING: Bitdefender state could not be read; the result must say 'unknown', not 'absent'")
    print("next (WSL):  wsl -d <distro> -u root -- python3 <wsl path of this file> --live "
          f"--fixture {fixture} --operator agent --out <file>\nthen:        python <this file> --cleanup-windows "
          f"--fixture {fixture}")
    return 0


def get(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read().strip()


def put(path: str, text: str) -> None:
    with open(path, "w", newline="\n", encoding="utf-8") as fh:
        fh.write(text)


def windows_sweep(base: str, rec_path: str) -> tuple[list[str], list[str]]:
    """What the WINDOWS side sees in the ungranted places, independent of the WSL view: (problems, notes)."""
    expected = {
        base: {LEAF, OTHER, LONG_DIR, MARKER_FILE},
        os.path.join(base, OTHER): {"secret.txt", *WTARGETS.values(), ADS_HOST},
        os.path.join(base, LONG_DIR): {LONG_FILE},
    }
    problems: list[str] = []
    notes: list[str] = []
    for folder, names in expected.items():
        if not os.path.isdir(folder) or is_reparse(folder):
            problems.append(f"{folder}: missing, or a reparse point")
            continue
        got = set(os.listdir(folder))
        problems += [f"{folder}: unexpected entry {n}" for n in sorted(got - names)]
        problems += [f"{folder}: expected entry missing {n}" for n in sorted(names - got)]
    want = {os.path.join(base, OTHER, WTARGETS[k]): ORIG for k in WTARGETS}
    try:
        with open(rec_path, encoding="utf-8") as fh:
            secrets = json.load(fh)["secrets"]
        want[os.path.join(base, OTHER, "secret.txt")] = secrets["main"]
        want[os.path.join(base, LONG_DIR, LONG_FILE)] = secrets["long"]
        want[os.path.join(base, OTHER, ADS_HOST) + ":" + ADS_STREAM] = secrets["ads"]
    except (OSError, ValueError, KeyError):
        notes.append("prepare record unreadable: secret contents not compared")
    for path, text in want.items():
        try:
            if get(path) != text:
                problems.append(f"{path}: content changed")
        except OSError as exc:
            problems.append(f"{path}: unreadable ({exc})")
    leaf = os.path.join(base, LEAF)
    if os.path.isdir(leaf) and not is_reparse(leaf):
        extra = sorted(set(os.listdir(leaf)) - {LEAF_FILE} - {ln.name for ln in LINKS})
        if extra:
            notes.append(f"entries left inside the grant: {extra}")
    return problems, notes


def cleanup_windows(fixture: str, win_root: str = WIN_ROOT_NT, force: bool = False) -> int:
    if os.name != "nt":
        print("REFUSED: --cleanup-windows runs on Windows python", file=sys.stderr)
        return 2
    if not FIXTURE_RE.match(fixture):
        print(f"REFUSED: fixture name must match {FIXTURE_RE.pattern}", file=sys.stderr)
        return 2
    base, rec_path = os.path.join(win_root, fixture), os.path.join(win_root, fixture) + ".prepare.json"
    print("before:", sorted(os.listdir(win_root)))
    if os.path.lexists(base):
        if not os.path.isfile(os.path.join(base, MARKER_FILE)):
            print(f"REFUSED: {base} has no {MARKER_FILE}; it is not a fixture of this script", file=sys.stderr)
            return 2
        problems, notes = windows_sweep(base, rec_path)
        for note in notes:
            print("note:", note)
        if problems:
            print("WINDOWS-SIDE SWEEP found changes in the ungranted places:")
            for problem in problems:
                print("  ", problem)
            if not force:
                print(NOTICE)
                print("Fixture kept for inspection. --force-cleanup removes it anyway.")
                return 10
            print("--force-cleanup given: removing anyway")
        else:
            print("windows-side sweep: ungranted places unchanged")
        leaf = os.path.join(base, LEAF)
        removed = []
        if os.path.isdir(leaf) and not is_reparse(leaf):
            for name in os.listdir(leaf):
                if is_reparse(os.path.join(leaf, name)):
                    remove_link(os.path.join(leaf, name))
                    removed.append(name)
        target_ok = os.path.isfile(os.path.join(base, OTHER, "secret.txt")) if os.path.isdir(leaf) else None
        print(f"links removed first: {removed}; ungranted target still intact afterwards: {target_ok}")
        remove_tree_no_follow(base)
    if os.path.lexists(rec_path):
        os.remove(rec_path)
    after = sorted(os.listdir(win_root))
    print("after: ", after)
    left = [n for n in after if n == fixture or n.startswith(fixture + ".")]
    print("CLEANED" if not left else f"NOT CLEAN: {left}")
    return 0 if not left else 1


def preflight_windows(fixture: str, win_root: str = WIN_ROOT_NT, wsl_root: str = WIN_ROOT_WSL,
                      mode: str = "leaky") -> int:
    """Every control must be able to FAIL: drive all probes at the prepared fixture on Windows with a runner
    that enforces nothing. Each denied-by-policy probe must then read POLICY_VIOLATION, which shows the probe
    sees an effect through that very junction, link, spelling or stream. Needs no WSL."""
    if bad_fixture_name(fixture):
        return 2
    if os.name != "nt":
        print("REFUSED: --preflight-windows runs on Windows python", file=sys.stderr)
        return 2
    rec, why = load_prepare(fixture, win_root)
    if rec is None:
        return write_inconclusive(None, None, why + " (run --prepare-windows first)")
    base = f"{wsl_root}/{fixture}"  # served from win_root/<fixture> by MappedFS
    ctx, fs = Ctx(base, rec), MappedFS(wsl_root, win_root)
    runner = SimNono(fs, mode)
    controls = {p.id: run_control(p, ctx, fs, runner) for p in PROBES.values()}
    results, _ = run_matrix(cases(base)[:1], ctx, fs, runner, controls, runs=1, say=lambda s: None)
    gaps = sorted({r["probe"] for r in results if r["reason"].startswith("fixture item missing")})
    bad = [f"control {pid}: {c.get('error') or c.get('detail') or 'failed'}"
           for pid, c in controls.items() if not c["ok"] and pid not in gaps]
    for r in results:
        want = "POLICY_VIOLATION" if r["policy"] == "deny" else "ALLOWED_AS_POLICY"
        if r["probe"] not in gaps and r["verdict"] != want:
            bad.append(f"probe {r['probe']}: read {r['verdict']}, expected {want} ({r['reason'] or r['detail']})")
    sw = sweep(fs, ctx)
    bad += [f"residue: {p}" for p in sw["problems"]]
    ok = len(PROBES) - len(gaps) - len([b for b in bad if b.startswith(("control", "probe"))])
    print(f"PRE-FLIGHT on Windows, enforcement-free runner, case A: {ok} of {len(PROBES)} probes saw their effect "
          f"as expected; not exercised (fixture item missing): {gaps or 'none'}")
    for line in bad:
        print("  FAIL", line)
    print("PRE-FLIGHT", "PASSED" if not bad else "FAILED", "- this shows the probes can see a leak; it says nothing "
          "about nono or 9P")
    return 0 if not bad else 1


# --------------------------------------------------------------------------- in-memory model for the self-test
class SimFS:
    """A case-insensitive server model with links, 8.3 aliases and streams, for the self-test only.

    Keys are lower-case resolved paths. A link or alias is followed by prefix replacement, which is
    the behaviour a leaking 9P server would show; the faithful runner below enforces on the resolved path.
    """

    def __init__(self) -> None:
        self.files: dict[str, str] = {}
        self.dirs: set[str] = set()
        self.disp: dict[str, str] = {}
        self.links: dict[str, str] = {}
        self.alias: dict[str, str] = {}

    def resolve(self, path: str) -> str:
        p = posixpath.normpath(path.replace("\\", "/")).lower()
        for _ in range(16):
            parts = p.split("/")
            for i in range(1, len(parts) + 1):
                pref = "/".join(parts[:i])
                tgt = self.links.get(pref) or self.alias.get(pref)
                if tgt is not None:
                    p = tgt + ("/" + "/".join(parts[i:]) if parts[i:] else "")
                    break
            else:
                return p
        raise OSError("too many levels of links")

    def mkdirs(self, path: str) -> None:
        p = path.lower()
        while p and p != "/":
            self.dirs.add(p)
            self.disp.setdefault(p, p.rsplit("/", 1)[-1])
            p = p.rsplit("/", 1)[0]

    def add_link(self, link: str, target: str) -> None:
        self.links[link.lower()] = target.lower()
        self.disp.setdefault(link.lower(), link.rsplit("/", 1)[-1])

    def lexists(self, path: str) -> bool:
        k = self.resolve(path)
        return k in self.files or k in self.dirs

    def read(self, path: str) -> str:
        k = self.resolve(path)
        if k not in self.files:
            raise FileNotFoundError(path)
        return self.files[k]

    def write(self, path: str, text: str) -> None:
        k = self.resolve(path)
        if posixpath.dirname(k) not in self.dirs:
            raise FileNotFoundError(path)
        self.files[k] = text
        self.disp[k] = path.rsplit("/", 1)[-1]

    def remove(self, path: str) -> None:
        k = self.resolve(path)
        if k not in self.files:
            raise FileNotFoundError(path)
        del self.files[k]

    def listdir(self, path: str) -> list[str]:
        d = self.resolve(path)
        if d not in self.dirs:
            raise FileNotFoundError(path)
        kids = {k for k in (*self.files, *self.dirs, *self.links)
                if posixpath.dirname(k) == d and k != d and ":" not in k.rsplit("/", 1)[-1]}
        return sorted(self.disp.get(k, k.rsplit("/", 1)[-1]) for k in kids)

    def link(self, src: str, dst: str) -> None:
        self.write(dst, self.read(src))

    def snapshot(self) -> tuple[dict[str, str], list[str]]:
        return dict(self.files), sorted(self.dirs)


def sim_world(base: str, drop: tuple[str, ...] = ()) -> tuple[SimFS, Ctx]:
    """A fixture shaped like the Windows-side prepare step makes it; `drop` removes record items."""
    rec = make_record(base)
    fs, s = SimFS(), rec["secrets"]
    for d in (f"{base}/{LEAF}", f"{base}/{OTHER}", f"{base}/{LONG_DIR}"):
        fs.mkdirs(d)
    fs.mkdirs("/root/work")
    fs.write(f"{base}/{LEAF}/{LEAF_FILE}", s["leaf"] + "\n")
    fs.write(f"{base}/{OTHER}/secret.txt", s["main"] + "\n")
    fs.write(f"{base}/{OTHER}/{ADS_HOST}", "plain\n")
    fs.write(f"{base}/{OTHER}/{ADS_HOST}:{ADS_STREAM}", s["ads"] + "\n")
    for name in WTARGETS.values():
        fs.write(f"{base}/{OTHER}/{name}", ORIG + "\n")
    fs.write(f"{base}/{LONG_DIR}/{LONG_FILE}", s["long"] + "\n")
    fs.write(f"{base}/{MARKER_FILE}", "marker\n")
    for ln in LINKS:
        fs.add_link(f"{base}/{LEAF}/{ln.name}", f"{base}/{ln.target}")
    fs.alias[f"{base}/{rec['short_names']['dir']}".lower()] = f"{base}/{LONG_DIR}".lower()
    fs.alias[f"{base}/{LONG_DIR}/{rec['short_names']['file']}".lower()] = f"{base}/{LONG_DIR}/{LONG_FILE}".lower()
    for key in drop:
        if key.startswith("link:"):
            rec["items"][key[5:]]["created"] = False
            rec["items"][key[5:]]["error"] = "simulated creation failure"
        else:
            rec["short_names" if key == "short83" else "ads"].update(created=False, error="simulated")
    return fs, Ctx(base, rec)


class SimNono:
    """Stands in for `nono run`. mode: leaky (enforces nothing), tight (denies everything),
    faithful (enforces the command line's grants on the RESOLVED path, as a correct sandbox would)."""

    def __init__(self, fs: Any, mode: str, started: bool = True, fail_rc: int = 127) -> None:
        """started=False: nono fails before it applies a sandbox (no banner), exiting with fail_rc."""
        self.fs, self.mode, self.started, self.fail_rc = fs, mode, started, fail_rc

    def _grants(self, flags: list[str], cwd: str) -> tuple[list[str], list[str]]:
        allow, read = [], []
        for flag, val in zip(flags[::2], flags[1::2], strict=False):
            path = self.fs.resolve(cwd if val == "." else val)
            (allow if flag == "--allow" else read).append(path)
        return allow, read

    def _permit(self, kind: str, path: str, allow: list[str], read: list[str]) -> bool:
        if self.mode == "leaky":
            return True
        if self.mode == "tight":
            return False
        k = self.fs.resolve(path)
        roots = allow if kind == "w" else allow + read
        return any(k == r or k.startswith(r + "/") for r in roots)

    def __call__(self, cmd: list[str], cwd: str) -> RunResult:
        sandboxed = cmd[0] == "nono"
        if sandboxed and not self.started:
            return RunResult(self.fail_rc, "", "nono: error before the sandbox was applied", "sim")
        if sandboxed:
            i = cmd.index("--")
            allow, read = self._grants(cmd[2:i], cwd)
            inner, banner = cmd[i + 1:], f"nono v0\n  {SANDBOX_MARKER}...\n"
            if inner[0] in NONO_BLOCKED_STARTUP:  # as the real nono: refused before any sandbox, so no banner
                return RunResult(1, "", f"nono: Command '{inner[0]}' is blocked: Command blocking is deprecated "
                                 "in v0.33.0 and only checks the directly-invoked startup command.", "sim")
        else:
            allow, read, inner, banner = [], [], cmd, ""
        saved, self.mode = self.mode, (self.mode if sandboxed else "leaky")
        try:
            return self._exec(inner, allow, read, banner)
        finally:
            self.mode = saved

    def _exec(self, inner: list[str], allow: list[str], read: list[str], banner: str) -> RunResult:
        fs, op = self.fs, inner[0]
        denied = RunResult(1, "", banner + "Permission denied\n", "sim")
        try:
            if op == "cat":
                if not self._permit("r", inner[1], allow, read):
                    return denied
                return RunResult(0, banner + fs.read(inner[1]), "", "sim")
            if op == "ls":
                if not self._permit("r", inner[-1], allow, read):
                    return denied
                return RunResult(0, banner + "\n".join(fs.listdir(inner[-1])) + "\n", "", "sim")
            if op == "sh":
                toks = shlex.split(inner[2])
                if toks[0] != "echo":  # `sh -c 'mv a b'` and the like: the same command, run by the shell
                    return self._exec(toks, allow, read, banner)
                if not self._permit("w", toks[3], allow, read):
                    return RunResult(2, "", banner + "Permission denied\n", "sim")
                fs.write(toks[3], toks[1] + "\n")
                return RunResult(0, banner, "", "sim")
            if op in ("mv", "ln"):
                if not (self._permit("w", inner[1], allow, read) and self._permit("w", inner[2], allow, read)):
                    return denied
                if op == "ln":
                    fs.link(inner[1], inner[2])
                else:
                    fs.write(inner[2], fs.read(inner[1]))
                    fs.remove(inner[1])
                return RunResult(0, banner, "", "sim")
        except FileNotFoundError:
            return RunResult(1, "", banner + "No such file or directory\n", "sim")
        raise ValueError(inner)


# --------------------------------------------------------------------------- self-test
class Tally:
    def __init__(self) -> None:
        self.n, self.fails, self.skipped = 0, [], []
        self.by: dict[str, int] = {}

    def chk(self, cat: str, name: str, cond: bool) -> None:
        self.n += 1
        self.by[cat] = self.by.get(cat, 0) + 1
        if not cond:
            self.fails.append(f"{cat}: {name}")


def self_test() -> int:
    t = Tally()
    base = f"{WIN_ROOT_WSL}/p1755-selftest"

    for pol, eff, started, ctl, want in [
        ("deny", True, True, True, "POLICY_VIOLATION"), ("deny", True, False, False, "POLICY_VIOLATION"),
        ("deny", False, True, True, "DENIED_AS_POLICY"), ("allow", False, True, True, "OVERDENIAL"),
        ("allow", True, True, True, "ALLOWED_AS_POLICY"), ("allow", True, False, True, "INCONCLUSIVE"),
        ("deny", False, True, False, "INCONCLUSIVE"), ("deny", False, False, True, "INCONCLUSIVE"),
        ("allow", None, True, True, "INCONCLUSIVE"), ("allow", False, True, False, "INCONCLUSIVE"),
    ]:
        t.chk("judge", f"{pol} {eff} started={started} ctl={ctl}", judge_run(pol, eff, started, ctl)[0] == want)
    for pol, eff, want in [
        ("deny", False, "INCONCLUSIVE"), ("allow", False, "INCONCLUSIVE"), ("allow", True, "INCONCLUSIVE"),
        ("deny", None, "INCONCLUSIVE"), ("deny", True, "POLICY_VIOLATION"),
    ]:
        t.chk("timeout", f"a timed-out run: {pol} effect={eff} reads {want}",
              judge_run(pol, eff, True, True, timed_out=True)[0] == want)
    t.chk("timeout", "an aborted matrix is never a clean result",
          overall([{"verdict": "DENIED_AS_POLICY"}], aborted=True) == "INCONCLUSIVE")
    t.chk("timeout", "an aborted matrix still reports a violation it saw",
          overall([{"verdict": "POLICY_VIOLATION"}], aborted=True) == "FAIL_OPEN_SUSPECTED")
    t.chk("judge", "overall flags a violation",
          overall([{"verdict": "POLICY_VIOLATION"}, {"verdict": "DENIED_AS_POLICY"}]) == "FAIL_OPEN_SUSPECTED")
    t.chk("judge", "a sweep alarm alone flags it", overall([{"verdict": "DENIED_AS_POLICY"}], True) == "FAIL_OPEN_SUSPECTED")
    t.chk("judge", "all inconclusive is inconclusive", overall([{"verdict": "INCONCLUSIVE"}]) == "INCONCLUSIVE")
    t.chk("judge", "never says secure", "SECURE" not in overall([{"verdict": "DENIED_AS_POLICY"}]).replace(
        "NO_POLICY_VIOLATION_OBSERVED", ""))

    table = (__doc__ or "").split("PROBE TABLE")[1].split("END PROBE TABLE")[0]
    ids = {m.group(1) for m in re.finditer(r"^  ([A-Z0-9_]+)\s{2,}", table, re.MULTILINE)} - {"ID"}
    t.chk("docs", "docstring table lists exactly the registered probes", ids == set(PROBES))
    for line in re.finditer(r"^  ([A-Z0-9_]+)\s{2,}.*?\s((?:allow|deny)(?: (?:allow|deny)){3})\s*$", table, re.MULTILINE):
        want = " ".join(policy(c, line.group(1)) for c in CASE_IDS)
        t.chk("docs", f"policy column of {line.group(1)} matches policy()", line.group(2) == want)
    t.chk("docs", "TARGETS covers every probe target", {p.target for p in PROBES.values()} <= set(TARGETS))
    t.chk("docs", "probe count", len(PROBES) == 30)

    case_list = cases(base)
    for mode, rule in (
        ("faithful", lambda pol: "DENIED_AS_POLICY" if pol == "deny" else "ALLOWED_AS_POLICY"),
        ("tight", lambda pol: "DENIED_AS_POLICY" if pol == "deny" else "OVERDENIAL"),
        ("leaky", lambda pol: "POLICY_VIOLATION" if pol == "deny" else "ALLOWED_AS_POLICY"),
    ):
        fs, ctx = sim_world(base)
        before = fs.snapshot()
        runner = SimNono(fs, mode)
        for case in case_list:
            for probe in PROBES.values():
                row = execute(case, probe, ctx, fs, runner, f"{case['id']}{probe.id}", {"ok": True})
                want = rule(policy(case["id"], probe.id))
                t.chk(f"matrix-{mode}", f"{case['id']} {probe.id} -> {want} (got {row['verdict']}: {row['reason']})",
                      row["verdict"] == want)
                t.chk(f"residue-{mode}", f"{case['id']} {probe.id} left nothing behind",
                      fs.snapshot() == before and not row["cleanup_errors"])
        t.chk(f"sweep-{mode}", "sweep is clean once every run cleaned up", sweep(fs, ctx)["alarm"] is False)
    fs, ctx = sim_world(base)
    SimNono(fs, "leaky")(["nono", "run", "--allow", f"{base}/{LEAF}", "--", "sh", "-c",
                          f"echo x > {base}/{OTHER}/stray.txt"], "/root/work")
    sw = sweep(fs, ctx)
    t.chk("sweep", "a stray file in an ungranted folder raises the alarm", sw["alarm"] and "stray.txt" in str(sw))
    fs, ctx = sim_world(base)
    fs.write(f"{base}/{OTHER}/{WTARGETS['rel']}", "changed\n")
    t.chk("sweep", "changed write-target content raises the alarm", sweep(fs, ctx)["alarm"])

    never: Runner = lambda cmd, cwd: (_ for _ in ()).throw(AssertionError("nono must not run"))
    for probe in PROBES.values():
        if not probe.needs:
            continue
        for item in probe.needs:
            fs, ctx = sim_world(base, drop=(item,))
            row = execute(case_list[0], probe, ctx, fs, never, "x", run_control(probe, ctx, fs, never))
            t.chk("missing-fixture", f"{probe.id} without {item} is INCONCLUSIVE, not run",
                  row["verdict"] == "INCONCLUSIVE" and item in row["reason"] and row["cmd"] == "(not run)")
    fs, ctx = sim_world(base)
    for probe in PROBES.values():
        ctl_ok = run_control(probe, ctx, fs, SimNono(fs, "leaky"))
        t.chk("control", f"{probe.id} control succeeds outside nono", ctl_ok["ok"])
        ctl_bad = run_control(probe, ctx, fs, lambda cmd, cwd: RunResult(1, "", "boom", "sim"))
        t.chk("control", f"{probe.id} control that fails reads not-ok", not ctl_bad["ok"])
        row = execute(case_list[0], probe, ctx, fs, SimNono(fs, "tight"), "c", {"ok": False})
        t.chk("control", f"{probe.id} denial with a failed control is INCONCLUSIVE", row["verdict"] == "INCONCLUSIVE")
        leak = execute(case_list[0], probe, ctx, fs, SimNono(fs, "leaky"), "d", {"ok": False})
        t.chk("control", f"{probe.id} a seen violation survives a failed control",
              leak["verdict"] == ("POLICY_VIOLATION" if policy("A", probe.id) == "deny" else "INCONCLUSIVE"))
        for fail_rc in (0, 1, 2, 127):  # nono fails before 'Applying sandbox', whatever it exits with
            nostart = execute(case_list[0], probe, ctx, fs, SimNono(fs, "tight", started=False, fail_rc=fail_rc),
                              "n", {"ok": True})
            t.chk("not-started", f"{probe.id}: no banner and exit {fail_rc} is INCONCLUSIVE, never a denial",
                  nostart["verdict"] == "INCONCLUSIVE")

    fs, ctx = sim_world(base)
    for probe in PROBES.values():
        spec = BUILDERS[probe.id](ctx, "stale", "tok")
        if spec.argv[0] not in ("sh", "mv", "ln"):
            continue
        spec.setup(fs)
        SimNono(fs, "leaky")(["nono", "run", "--allow", ctx.leaf, "--"] + spec.argv, "/root/work")
        row = execute(case_list[0], probe, ctx, fs, SimNono(fs, "tight"), "stale", {"ok": True})
        want = "DENIED_AS_POLICY" if policy("A", probe.id) == "deny" else "OVERDENIAL"
        t.chk("stale", f"{probe.id}: an effect left by an earlier run is cleared, so a denial reads as one",
              row["verdict"] == want)

    fs, ctx = sim_world(base)
    results, aborted = run_matrix(case_list[:1], ctx, fs, SimNono(fs, "leaky"),
                                  {p: {"ok": True} for p in PROBES}, say=lambda s: None)
    rec = {"results": results, "sweep": sweep(fs, ctx)}
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = conclude(rec, None)
    t.chk("exit", "leaky matrix exits 10", code == 10 and aborted is None)
    t.chk("exit", "do-not-post notice is printed", "Do NOT post anything public" in buf.getvalue())
    t.chk("exit", "overall is FAIL_OPEN_SUSPECTED", rec["overall"] == "FAIL_OPEN_SUSPECTED")
    fs, ctx = sim_world(base)
    results, _ = run_matrix(case_list, ctx, fs, SimNono(fs, "faithful"), {p: {"ok": True} for p in PROBES},
                            say=lambda s: None)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = conclude({"results": results, "sweep": sweep(fs, ctx)}, None)
    t.chk("exit", "faithful matrix exits 0 with no notice", code == 0 and "Do NOT post" not in buf.getvalue())
    t.chk("exit", "faithful matrix has 360 rows", len(results) == 360)
    timeouts = lambda cmd, cwd: RunResult(124, "", "timeout", "sim")
    _, aborted = run_matrix(case_list[:1], ctx, fs, timeouts, {p: {"ok": True} for p in PROBES}, say=lambda s: None)
    t.chk("exit", "consecutive timeouts abort the matrix", aborted is not None)

    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "result.json")
        ns = argparse.Namespace(fixture="p1755-selftest", operator="agent", out=out, stdin_mode="pty")
        for mode, want_code, want_overall in (("faithful", 0, "NO_POLICY_VIOLATION_OBSERVED"),
                                              ("leaky", 10, "FAIL_OPEN_SUSPECTED")):
            fs, ctx = sim_world(base)
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = run_live(ns, {"kernel": "sim"}, ctx.record, fs, SimNono(fs, mode), SimNono(fs, "leaky"))
            with open(out, encoding="utf-8") as fh:
                saved = json.load(fh)
            t.chk("live", f"{mode}: exit code {want_code}", code == want_code)
            t.chk("live", f"{mode}: result file says {want_overall}", saved["overall"] == want_overall)
            t.chk("live", f"{mode}: 360 rows, counts add up, every row names its prompt path",
                  len(saved["results"]) == 360 and sum(saved["counts"].values()) == 360
                  and all(r["prompt_path"] for r in saved["results"]))
            t.chk("live", f"{mode}: record carries controls, sweep, env, not-measured and the script's probe list",
                  len(saved["controls_outside_nono"]) == 30 and "sweep" in saved and saved["env"] and saved["not_measured"])
            t.chk("live", f"{mode}: the secrets are not copied into the prepare record section",
                  "secrets" not in saved["prepare_record"])
        fs, ctx = sim_world(base)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = run_live(argparse.Namespace(fixture="p1755-other", operator="agent", out=out, stdin_mode="pty"),
                            {}, ctx.record, fs, SimNono(fs, "tight"), SimNono(fs, "leaky"))
        t.chk("live", "a prepare record for another fixture is INCONCLUSIVE, exit 4", code == 4)
        with open(out, encoding="utf-8") as fh:
            t.chk("live", "and the result file says why", json.load(fh)["overall"] == "INCONCLUSIVE")
        fs, ctx = sim_world(base)
        fs.remove(f"{base}/{MARKER_FILE}")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = run_live(ns, {}, ctx.record, fs, SimNono(fs, "tight"), SimNono(fs, "leaky"))
        t.chk("live", "an incomplete fixture is INCONCLUSIVE, exit 4, nothing run", code == 4)

    # a run that timed out never finished: INCONCLUSIVE whatever else it shows (the live run that hung at nono's
    # review menu was recorded as DENIED_AS_POLICY before this rule)
    banner_only = f"nono v0\n  {SANDBOX_MARKER}...\n"
    fs, ctx = sim_world(base)
    hung: Runner = lambda cmd, cwd: RunResult(124, banner_only, "", "sim")
    for probe in PROBES.values():
        row = execute(case_list[0], probe, ctx, fs, hung, "h", {"ok": True})
        t.chk("timeout", f"{probe.id}: exit 124 with no effect seen is INCONCLUSIVE",
              row["verdict"] == "INCONCLUSIVE" and row["effect_seen"] is False and "timed out" in row["reason"])
        slow_leak = SimNono(fs, "leaky")
        row = execute(case_list[0], probe, ctx, fs, lambda cmd, cwd, r=slow_leak: r(cmd, cwd)._replace(rc=124),
                      "s", {"ok": True})
        t.chk("timeout", f"{probe.id}: exit 124 after a seen effect is a violation only where the policy denies",
              row["verdict"] == ("POLICY_VIOLATION" if policy("A", probe.id) == "deny" else "INCONCLUSIVE"))
    results, aborted = run_matrix(case_list, ctx, fs, hung, {p: {"ok": True} for p in PROBES}, say=lambda s: None)
    rec = {"results": results, "sweep": sweep(fs, ctx), "aborted": aborted}
    with contextlib.redirect_stdout(io.StringIO()):
        code = conclude(rec, None)
    t.chk("timeout", "a matrix of hung runs aborts after six, every row INCONCLUSIVE, none DENIED",
          aborted is not None and len(results) == MAX_CONSECUTIVE_TIMEOUTS
          and all(r["verdict"] == "INCONCLUSIVE" for r in results))
    t.chk("timeout", "and its overall is INCONCLUSIVE with exit 4", rec["overall"] == "INCONCLUSIVE" and code == 4)

    # nono's post-run review menu: answer Esc, never anything that grants
    prompt = b"\n  nono v0.79.0\n  Share current directory /root/work? [y/N] "
    banner = f"N\r\n  Capabilities:\r\n  {SANDBOX_MARKER}...\r\n".encode()
    menu1 = ("sh: 1: cannot create /mnt/c/wsl/p1755-run1/leak_x.txt: Permission denied\r\n"
             "  Query policy: nono why --path <path> --op <read|write|readwrite>\r\n"
             " [nono] Review denied paths\r\n  Input enables in 1 second · early keys ignored\r\n\r\n"
             "  \x1b[1m▶\x1b[0m  grant     /mnt/c/wsl/p1755-run1  (write dirs)\r\n").encode()
    menu2 = ("\x1b[2J\x1b[H [nono] Review denied paths\r\n  ↑/↓ move  ·  Space cycle  ·  a grant-all  "
             "·  d deny-all  ·  Enter confirm  ·  Esc cancel\r\n\r\n"
             "  ▶  grant     /mnt/c/wsl/p1755-run1  (write dirs)\r\n").encode()
    entry = ("grant /mnt/c/wsl/p1755-run1 (write dirs)",)

    d = PtyDriver(0.0)
    sent = d.feed(prompt, 0.0)
    sent += d.feed(banner, 0.1)
    sent += d.feed(menu1, 0.5)
    for tick in (0.6, 1.0, 1.4, 1.5):
        sent += d.tick(tick)
    t.chk("review", "nothing is typed while nono ignores keys (no hints yet)", sent == [b"N\n"])
    sent += d.feed(menu2, 1.6)
    sent += d.tick(1.7)
    t.chk("review", "nothing is typed until the hints have been up for the settle time", sent == [b"N\n"])
    sent += d.tick(1.95)
    sent += d.tick(2.0)
    t.chk("review", "Esc is typed once, after the hints settled", sent == [b"N\n", b"\x1b"])
    for tick in (4.1, 6.2, 8.3, 10.4, 20.0):
        sent += d.tick(tick)
    t.chk("review", "Esc is repeated while the process lives, at most three times", sent.count(b"\x1b") == 3)
    t.chk("review", "the only keys typed are N at the prompt and Esc at the menu (no a, d, Space or Enter)",
          all(s in (b"N\n", b"\x1b") for s in sent))
    t.chk("review", "path names the prompt answer and the cancelled review",
          d.path(False) == "pty_prompt_answered_N+review_cancelled_x3")
    t.chk("review", "the denied-path line nono printed is captured once, menu redraws collapsed",
          parse_review(d.text) == entry)

    d = PtyDriver(0.0)
    d.feed(prompt, 0.0)
    d.feed(banner + menu1, 0.5)
    t.chk("review", "hints that never come: Esc goes out after the menu wait",
          d.tick(2.4) == [] and d.tick(3.1) == [b"\x1b"] and d.path(False) == "pty_prompt_answered_N+review_cancelled")
    d = PtyDriver(0.0)
    d.feed(banner + b"hello\r\n", 0.1)
    t.chk("review", "no prompt and no menu is said so in the path",
          d.path(False) == "pty_no_prompt_seen+no_review_menu" and parse_review(d.text) == ())
    d = PtyDriver(0.0)
    d.feed(prompt, 0.0)
    d.feed(banner, 0.1)
    t.chk("review", "a prompt answered and no menu is said so in the path",
          d.path(False) == "pty_prompt_answered_N+no_review_menu")
    d = PtyDriver(0.0)
    d.feed(banner + menu1, 0.5)
    t.chk("review", "menu seen but the process ended before Esc is said so",
          d.path(False) == "pty_no_prompt_seen+review_menu_seen_unanswered")
    t.chk("review", "a run that timed out without ever prompting says so",
          PtyDriver(0.0).path(True) == "pty_timeout_no_prompt_pattern_matched+no_review_menu")
    d = PtyDriver(0.0)
    d.feed(b"Share the current directory?\r\n", 0.0)
    t.chk("review", "the idle fallback answers a prompt of an unknown shape, once",
          d.tick(1.0) == [] and d.tick(1.6) == [b"N\n"] and d.tick(3.5) == []
          and d.path(False) == "pty_answered_on_idle_cwd_text+no_review_menu")
    d = PtyDriver(0.0)
    d.feed(banner + b"working directory is /root/work\r\n", 0.0)
    t.chk("review", "the idle fallback stays quiet once the sandbox is applied", d.tick(5.0) == [])
    d = PtyDriver(0.0)
    first = d.feed(prompt, 0.0)
    again = d.feed(b"\x1b[0m", 0.05) + d.feed(b"N\r\n", 0.1)  # a redraw with no new text, then the echo
    second = d.feed(b"Save these grants? [y/N] ", 0.2)
    t.chk("review", "each yes/no prompt is answered N once, never the same one twice",
          first == [b"N\n"] and again == [] and second == [b"N\n"] and d.path(False) == "pty_prompt_answered_Nx2+no_review_menu")
    t.chk("review", "a cursor-position query from a terminal UI gets an answer",
          PtyDriver(0.0).feed(b"\x1b[6n", 0.0) == [CURSOR_REPORT])
    t.chk("review", "text before the header and unrelated lines are not taken as denied paths",
          parse_review("drwxr-xr-x 2 root root 4096 /mnt/c/x\n [nono] Review denied paths\n  grant /a/b (read)\n"
                       "  Input enables in 1 second\n  ▶  grant /a/b (read)\n  read /c/d (read dirs)\n")
          == ("grant /a/b (read)", "read /c/d (read dirs)"))
    fs, ctx = sim_world(base)
    menu_run: Runner = lambda cmd, cwd: RunResult(
        2, banner_only + (menu1 + menu2).decode(), "", "pty_prompt_answered_N+review_cancelled", entry)
    row = execute(case_list[0], PROBES["W_OUT"], ctx, fs, menu_run, "m", {"ok": True})
    t.chk("review", "the row carries nono's denied-path lines and the prompt path, and reads DENIED",
          row["nono_review_denied"] == list(entry) and row["prompt_path"] == "pty_prompt_answered_N+review_cancelled"
          and row["verdict"] == "DENIED_AS_POLICY" and json.loads(json.dumps(row))["nono_review_denied"] == list(entry))
    t.chk("review", "a row for a run with no menu has the field empty",
          execute(case_list[0], PROBES["W_OUT"], ctx, fs, SimNono(fs, "tight"), "m2", {"ok": True})["nono_review_denied"] == [])

    # R1-5: the fixture name gate is on every mode that takes a name
    hostile = ["r1755-review", "../p1755-x", "p1755-../x", "C:p1755-x", "P1755-X", "p1755-", "p1755-x/y",
               "p1755-x\\y", "p1755-x ", "p1755-x\n", "/p1755-x", "p1755-" + "a" * 40]
    for name in hostile:
        t.chk("name-gate", f"{name!r}: no record is looked up, the name is the stated reason",
              load_prepare(name)[0] is None and "does not match" in load_prepare(name)[1])
        gated = (
            ("--live", lambda n=name: live(argparse.Namespace(fixture=n, operator="agent", out="x.json",
                                                              stdin_mode="pty"))),
            ("--preflight-windows", lambda n=name: preflight_windows(n)),
            ("--dry-run", lambda n=name: dry_run(n)),
        )
        for label, call in gated:  # exit 2 alone is not enough: --live also exits 2 for "not WSL"
            err = io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                code = call()
            t.chk("name-gate", f"{name!r}: {label} refuses on the name, exit 2",
                  code == 2 and "fixture name must match" in err.getvalue())
    t.chk("name-gate", "a name --prepare-windows makes passes the gate",
          not bad_fixture_name("p1755-ab12cd") and not bad_fixture_name("p1755-run1"))

    # R2-1: a matrix that aborts after rows were judged is INCONCLUSIVE overall, in the record and in the exit code
    class Fading:
        """Faithful for the first `good` calls, then every run times out."""

        def __init__(self, fs: Any, good: int) -> None:
            self.inner, self.left = SimNono(fs, "faithful"), good

        def __call__(self, cmd: list[str], cwd: str) -> RunResult:
            self.left -= 1
            return self.inner(cmd, cwd) if self.left >= 0 else RunResult(124, banner_only, "", "sim")

    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "aborted.json")
        ns = argparse.Namespace(fixture="p1755-selftest", operator="agent", out=out, stdin_mode="pty")
        fs, ctx = sim_world(base)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = run_live(ns, {"kernel": "sim"}, ctx.record, fs, Fading(fs, 20), SimNono(fs, "leaky"))
        with open(out, encoding="utf-8") as fh:
            saved = json.load(fh)
        verdicts = [r["verdict"] for r in saved["results"]]
        t.chk("abort", "the matrix aborted after judged rows: some DENIED, then INCONCLUSIVE timeouts",
              saved["aborted"] is not None and "DENIED_AS_POLICY" in verdicts and verdicts[-1] == "INCONCLUSIVE")
        t.chk("abort", "its record reads INCONCLUSIVE overall, never none seen", saved["overall"] == "INCONCLUSIVE")
        t.chk("abort", "and run_live exits 4", code == 4)
        real_conclude = conclude
        globals()["conclude"] = lambda rec, out_path: 0
        try:
            fs, ctx = sim_world(base)
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                forced = run_live(ns, {"kernel": "sim"}, ctx.record, fs, Fading(fs, 20), SimNono(fs, "leaky"))
        finally:
            globals()["conclude"] = real_conclude
        t.chk("abort", "run_live forces exit 4 on an abort even when the conclusion says 0", forced == 4)

    # R2-2 / R1-2: the Windows steps run for real against a temporary fixture; the pre-flight must be able to fail
    if os.name == "nt":
        with tempfile.TemporaryDirectory() as tmp:
            fix, wsl_root = "p1755-selftest", WIN_ROOT_WSL
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                made = prepare_windows(fix, tmp, wsl_root)
            rec_file = os.path.join(tmp, fix + ".prepare.json")
            raw = open(rec_file, encoding="utf-8").read() if made == 0 else ""
            short_rec = json.loads(raw)["short_names"] if raw else {}
            t.chk("windows-fixture", "--prepare-windows built a fixture and its record", made == 0 and bool(raw))
            t.chk("windows-fixture", "the recorded dir /x text keeps entry lines and no volume header",
                  bool(short_rec.get("dir_x_base")) and "Serial Number" not in raw and "Volume in drive" not in raw
                  and "bytes free" not in raw)
            outcomes = {}
            for mode in ("leaky", "tight"):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
                    outcomes[mode] = (preflight_windows(fix, tmp, wsl_root, mode), buf.getvalue())
            t.chk("windows-fixture", "pre-flight with an enforcement-free runner passes, exit 0",
                  outcomes["leaky"][0] == 0 and "PRE-FLIGHT PASSED" in outcomes["leaky"][1])
            t.chk("windows-fixture", "pre-flight with a runner that denies everything fails, exit 1",
                  outcomes["tight"][0] == 1 and "PRE-FLIGHT FAILED" in outcomes["tight"][1])
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                gone = cleanup_windows(fix, tmp, force=True)
            t.chk("windows-fixture", "--cleanup-windows removes the fixture", gone == 0 and not os.path.exists(os.path.join(tmp, fix)))
    else:
        t.skipped.append("windows fixture steps (need Windows python)")
    t.chk("windows", "dir listing filter keeps entries only",
          dir_entry_lines(" Volume in drive C is OS\n Volume Serial Number is 0000-0000\n\n Directory of C:/x\n\n"
                          "10/14/2026  11:09 PM    <DIR>          UNGRAN~1     ungranted_long_dir\n"
                          "               1 File(s)             49 bytes\n               5 Dir(s)  1 bytes free")
          == "10/14/2026  11:09 PM    <DIR>          UNGRAN~1     ungranted_long_dir")

    # R1-7: a fact whose command is absent or silent reads "missing", never ""
    t.chk("facts", "an absent command reads missing",
          command_fact(["nono", "--version"], lambda c: RunResult(127, "", "not found", "none")).startswith("missing:"))
    t.chk("facts", "a silent command reads missing",
          command_fact(["uname", "-r"], lambda c: RunResult(0, "  \n", "", "none")).startswith("missing:"))
    t.chk("facts", "a failing command reads missing",
          command_fact(["uname", "-r"], lambda c: RunResult(1, "partial", "", "none")).startswith("missing:"))
    t.chk("facts", "a command that answers reads its output",
          command_fact(["uname", "-r"], lambda c: RunResult(0, "6.18.54.1\n", "", "none")) == "6.18.54.1")
    t.chk("facts", "the environment record reads its facts through it", "sh = command_fact" in inspect.getsource(env_record))

    # R1-2: the live plumbing under controls that fail and fixtures that are partly missing
    ns = argparse.Namespace(fixture="p1755-selftest", operator="agent", out=None, stdin_mode="pty")
    fs, ctx = sim_world(base)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()), \
            tempfile.TemporaryDirectory() as tmp:
        ns.out = os.path.join(tmp, "failed-controls.json")
        code = run_live(ns, {}, ctx.record, fs, SimNono(fs, "faithful"), lambda cmd, cwd: RunResult(1, "", "boom", "sim"))
        with open(ns.out, encoding="utf-8") as fh:
            saved = json.load(fh)
        t.chk("plumbing", "every control failing: 360 rows kept, all INCONCLUSIVE, exit 4",
              code == 4 and len(saved["results"]) == 360 and saved["counts"]["INCONCLUSIVE"] == 360)
        fs, ctx = sim_world(base, drop=("link:jct",))
        ns.out = os.path.join(tmp, "partial.json")
        code = run_live(ns, {}, ctx.record, fs, SimNono(fs, "faithful"), SimNono(fs, "leaky"))
        with open(ns.out, encoding="utf-8") as fh:
            saved = json.load(fh)
        t.chk("plumbing", "a link kind missing: its 36 rows stay in the record as INCONCLUSIVE, the rest read normally",
              code == 0 and len(saved["results"]) == 360 and saved["counts"]["INCONCLUSIVE"] == 36
              and saved["inconclusive_probes"] == ["JCT_L", "JCT_R", "JCT_W"])

    # the spelled, 8.3, stream and traversal paths are really the paths the table says
    fs, ctx = sim_world(base)
    argv = {pid: BUILDERS[pid](ctx, "t", "tok").argv for pid in PROBES}
    t.chk("argv", "CASE_UP_R reads the whole path in UPPER case",
          argv["CASE_UP_R"][-1] == "/mnt/c/WSL/P1755-SELFTEST/OTHER/SECRET.TXT")
    t.chk("argv", "CASE_MIX_R reads it in Title Case", argv["CASE_MIX_R"][-1] == "/mnt/c/Wsl/P1755-Selftest/Other/Secret.Txt")
    t.chk("argv", "S83_R reads by the 8.3 names", argv["S83_R"][-1] == f"{base}/UNGRAN~1/SECRET~1.TXT")
    t.chk("argv", "S83_W writes under the 8.3 folder name", f"{base}/UNGRAN~1/leak_t.txt" in argv["S83_W"][-1])
    t.chk("argv", "ADS_R reads the stream", argv["ADS_R"][-1] == f"{base}/{OTHER}/{ADS_HOST}:{ADS_STREAM}")
    t.chk("argv", "TRAV_R goes out through `..`", argv["TRAV_R"][-1] == f"{base}/{LEAF}/../{OTHER}/secret.txt")
    t.chk("argv", "CASE_UP_W writes into the UPPER-case folder", "/OTHER/leak_t.txt" in argv["CASE_UP_W"][-1])

    # nono refuses some utilities as the startup command, before any sandbox: no probe may start with one
    for pid, words in argv.items():
        t.chk("blocked-startup", f"{pid} does not start with a command nono blocks", words[0] not in NONO_BLOCKED_STARTUP)
    t.chk("blocked-startup", "MV_OUT runs mv through sh", argv["MV_OUT"][:2] == ["sh", "-c"] and " mv " in f" {argv['MV_OUT'][2]}")
    refused = SimNono(fs, "leaky")(["nono", "run", "--allow", ctx.leaf, "--", "mv", f"{ctx.leaf}/a", f"{ctx.other}/b"],
                                   "/root/work")
    t.chk("blocked-startup", "the model refuses a bare mv as nono does: no banner, 'is blocked'",
          refused.rc == 1 and SANDBOX_MARKER not in refused.out + refused.err and "is blocked" in refused.err)
    # ADS_R: its control fails on 9P, so it is expected INCONCLUSIVE and reported as expected; MV_OUT is not
    fs, ctx = sim_world(base)
    fs.remove(f"{base}/{OTHER}/{ADS_HOST}:{ADS_STREAM}")
    with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
        ns = argparse.Namespace(fixture="p1755-selftest", operator="agent", out=os.path.join(tmp, "ads.json"),
                                stdin_mode="pty")
        code = run_live(ns, {}, ctx.record, fs, SimNono(fs, "faithful"), SimNono(fs, "leaky"))
        with open(ns.out, encoding="utf-8") as fh:
            saved = json.load(fh)
        t.chk("expected", "ADS_R unreadable outside nono: 12 rows INCONCLUSIVE, listed as expected, none unexpected",
              code == 0 and saved["inconclusive_probes"] == ["ADS_R"] and saved["counts"]["INCONCLUSIVE"] == 12
              and saved["unexpected_inconclusive_probes"] == [] and "ADS_R" in saved["expected_inconclusive"])
        fs, ctx = sim_world(base)
        ns.out = os.path.join(tmp, "unexpected.json")
        code = run_live(ns, {}, ctx.record, fs, SimNono(fs, "tight", started=False), SimNono(fs, "leaky"))
        with open(ns.out, encoding="utf-8") as fh:
            saved = json.load(fh)
        t.chk("expected", "any other probe INCONCLUSIVE is reported as not expected",
              "MV_OUT" in saved["unexpected_inconclusive_probes"] and code == 4)

    for text, want in [("Share cwd /root/work? [y/N] ", True), ("Continue (Y/n):", True), ("allow? [yes/no]", True),
                       ("\x1b[1mShare?\x1b[0m [y/N] \x1b[0m", True), ("Allow cwd? (y/n) > ", True), ("Skipping CWD prompt (non-interactive).", False),
                       ("Applying sandbox...", False), ("", False)]:
        t.chk("prompt", f"prompt_wanted({text[:24]!r})", prompt_wanted(text) is want)
    ok, why = pty_available()
    if ok:
        res = run_pty(["sh", "-c", "printf 'Share cwd? [y/N] '; read a; echo got:$a"], "/")
        t.chk("pty", "N is delivered at a prompt",
              "got:N" in res.out and res.prompt_path == "pty_prompt_answered_N+no_review_menu")
        res = run_pty(["sh", "-c", "echo hello"], "/")
        t.chk("pty", "no prompt is recorded as such",
              "hello" in res.out and res.prompt_path == "pty_no_prompt_seen+no_review_menu")
        res = run_pty(["sh", "-c", "exit 3"], "/")
        t.chk("pty", "exit code is carried", res.rc == 3)
        res = run_pty(["sh", "-c", "sleep 30"], "/", timeout=1)
        t.chk("pty", "a hung child is killed and reads exit 124",
              res.rc == 124 and res.prompt_path == "pty_timeout_no_prompt_pattern_matched+no_review_menu")
        menu_child = (
            "import os, sys, time, tty\n"
            "sys.stdout.write(' [nono] Review denied paths\\n  Input enables in 1 second\\n\\n"
            "  grant     /x/y  (write dirs)\\n')\n"
            "sys.stdout.flush()\n"
            "time.sleep(1.2)\n"
            "sys.stdout.write(' [nono] Review denied paths\\n  Esc cancel\\n')\n"
            "sys.stdout.flush()\n"
            "tty.setraw(0)\n"
            "key = os.read(0, 1)\n"
            "sys.stdout.write('got:%d\\n' % key[0])\n"
        )
        res = run_pty([sys.executable, "-c", menu_child], "/")
        t.chk("pty", "Esc, and only Esc, reaches a raw-mode review menu; its denied path is captured",
              "got:27" in res.out and res.prompt_path == "pty_no_prompt_seen+review_cancelled"
              and res.review == ("grant /x/y (write dirs)",))
    else:
        t.skipped.append(f"pty runner (not exercisable on this host: {why}); run --self-test inside WSL too")

    csv_text = '"System Idle Process","0"\n"BdeUISrv.exe","1"\n"bdservicehost.exe","2"\n"vsserv.exe","3"\n"BdAgent.exe","4"\n'
    t.chk("windows", "Bitdefender matcher hits its services", match_bitdefender(csv_text) == ["bdagent.exe", "bdservicehost.exe", "vsserv.exe"])
    t.chk("windows", "BitLocker's Bde* is not Bitdefender", "bdeuisrv.exe" not in match_bitdefender(csv_text))
    filler = "".join(f'"filler{i}.exe","{i}"\n' for i in range(400))
    long_csv = filler + '"bdredline.exe","9"\n"ProductAgentService.exe","10"\n'
    t.chk("windows", "a Bitdefender image after a long process list is still found",
          match_bitdefender(long_csv) == ["bdredline.exe", "productagentservice.exe"])

    def fake_run(cmd: list[str], cwd: str | None = None, timeout: int = 60) -> RunResult:
        if cmd[0] == "tasklist":
            return RunResult(0, long_csv, "", "none")
        return RunResult(0, "bdredline\nDiscoverySrv\n", "", "none")

    view = bitdefender_view("tasklist", "powershell", fake_run)
    t.chk("windows", "both routes are read and agree on present",
          view["status"] == "present" and view["company_names"] == ["bdredline", "discoverysrv"])
    broken = bitdefender_view("t", "p", lambda cmd, cwd=None, timeout=60: RunResult(127, "", "", "none"))
    t.chk("windows", "no route readable is 'unknown', never 'absent'", broken["status"] == "unknown")
    empty = bitdefender_view("t", "p", lambda cmd, cwd=None, timeout=60: RunResult(
        0, '"a.exe","1"\n' if cmd[0] == "t" else "", "", "none"))
    t.chk("windows", "readable and empty is 'absent'", empty["status"] == "absent")
    sample = ("10/14/2026  09:00 PM    <DIR>          UNGRAN~1     ungranted_long_dir\n"
              "10/14/2026  09:00 PM    <DIR>                       other\n"
              "10/14/2026  09:00 PM    <JUNCTION>     JCT          jct [C:\\wsl\\x\\other]\n")
    t.chk("windows", "dir /x parser finds the 8.3 name", parse_dir_x(sample, "ungranted_long_dir") == "UNGRAN~1")
    t.chk("windows", "dir /x parser: a name with no 8.3 form", parse_dir_x(sample, "other") is None)
    t.chk("windows", "fixture name gate", bool(FIXTURE_RE.match("p1755-ab12cd")) and not FIXTURE_RE.match("wsl")
          and not FIXTURE_RE.match("p1755-..\\x") and not FIXTURE_RE.match("nono-try"))
    t.chk("windows", "unprepared fixture refuses in live", load_prepare("p1755-none", root=os.path.join(os.devnull, "x"))[0] is None)

    print("self-test checks by category:", ", ".join(f"{k} {v}" for k, v in t.by.items()))
    for s in t.skipped:
        print("self-test SKIPPED:", s)
    print(f"self-test: {t.n} checks, {len(t.fails)} failed, {len(t.skipped)} skipped")
    for f in t.fails[:40]:
        print("  FAIL", f)
    return 1 if t.fails else 0


# --------------------------------------------------------------------------- dry run and live run
def bad_fixture_name(fixture: str) -> bool:
    """True (after saying so) when the name is not one --prepare-windows could have made."""
    if FIXTURE_RE.match(fixture):
        return False
    print(f"REFUSED: fixture name must match {FIXTURE_RE.pattern}", file=sys.stderr)
    return True


def load_prepare(fixture: str, root: str = WIN_ROOT_WSL) -> tuple[dict[str, Any] | None, str]:
    if not FIXTURE_RE.match(fixture):
        return None, f"fixture name {fixture!r} does not match {FIXTURE_RE.pattern}"
    path = f"{root}/{fixture}.prepare.json"
    try:
        with open(path, encoding="utf-8") as fh:
            rec = json.load(fh)
    except (OSError, ValueError) as exc:
        return None, f"prepare record {path} not readable: {exc}"
    if rec.get("schema") != SCHEMA or rec.get("fixture") != fixture:
        return None, f"prepare record {path} has schema {rec.get('schema')} / fixture {rec.get('fixture')}"
    return rec, ""


def dry_run(fixture: str) -> int:
    if bad_fixture_name(fixture):
        return 2
    base = f"{WIN_ROOT_WSL}/{fixture}"
    rec, _ = load_prepare(fixture, WIN_ROOT_NT if os.name == "nt" else WIN_ROOT_WSL)
    placeholder = rec is None
    ctx = Ctx(base, rec or make_record(base, ("<8.3-dir>", "<8.3-file>")))
    print(f"DRY RUN: nothing is touched and nothing is started. Fixture {base}"
          + (" (no prepare record found: fixture-specific names are placeholders)" if placeholder else ""))
    for case in cases(base):
        print(f"\ncase {case['id']} ({case['ref']}): cwd={case['cwd']} nono run {' '.join(case['flags'])} -- <probe>")
        for probe in PROBES.values():
            spec = BUILDERS[probe.id](ctx, f"{case['id']}{probe.id}n", "<token>")
            print(f"  {probe.id:<13}{policy(case['id'], probe.id):<6}{' '.join(shlex.quote(x) for x in spec.argv)}")
    controls = len(PROBES)
    n = len(CASE_IDS) * len(PROBES) * RUNS
    print(f"\nmatrix: {len(CASE_IDS)} cases x {len(PROBES)} probes x {RUNS} runs = {n} nono runs, "
          f"plus {controls} control runs outside nono (one per probe)")
    print("stdin: pty by default (--stdin-mode piped to compare); the path taken is on every row")
    for pid, why in EXPECTED_INCONCLUSIVE.items():
        print(f"expected INCONCLUSIVE: {pid} ({why})")
    print("Not measured:", "; ".join(NOT_MEASURED))
    return 0


def write_inconclusive(out: str | None, env: dict[str, Any] | None, reason: str) -> int:
    print("INCONCLUSIVE:", reason, file=sys.stderr)
    if out:
        with open(out, "w", encoding="utf-8") as fh:
            json.dump({"ticket": TICKET, "overall": "INCONCLUSIVE", "reason": reason, "env": env, "results": []},
                      fh, indent=2)
    return 4


def live(a: argparse.Namespace) -> int:
    if not a.operator or not a.out or not a.fixture:
        print("REFUSED: --live needs --fixture NAME, --operator agent|LA and --out PATH", file=sys.stderr)
        return 2
    if bad_fixture_name(a.fixture):
        return 2
    if "microsoft" not in read_text("/proc/version").lower():
        print("REFUSED: not WSL", file=sys.stderr)
        return 2
    if shutil.which("nono") is None:
        return write_inconclusive(a.out, None, "nono is not installed in this distribution")
    env = env_record(a.stdin_mode)
    if "9p" not in env["findmnt_c"]:
        print("REFUSED: /mnt/c is not a 9p mount here:", env["findmnt_c"], file=sys.stderr)
        return 2
    prep, why = load_prepare(a.fixture)
    if prep is None:
        return write_inconclusive(a.out, env, why + " (run --prepare-windows first)")
    os.makedirs("/root/work", exist_ok=True)
    return run_live(a, env, prep, RealFS(), make_runner(a.stdin_mode), lambda cmd, cwd: run_plain(cmd, cwd))


def run_live(a: Any, env: dict[str, Any], prep: dict[str, Any], fs: FS, runner: Runner, plain: Runner) -> int:
    """Everything after the preconditions: controls, the matrix, the sweep and the record."""
    base = f"{WIN_ROOT_WSL}/{a.fixture}"
    if prep.get("wsl_base") != base:
        return write_inconclusive(a.out, env, f"prepare record is for {prep.get('wsl_base')}, not {base}")
    ctx = Ctx(base, prep)
    for need in (f"{base}/{LEAF}", f"{base}/{OTHER}/secret.txt", f"{base}/{MARKER_FILE}"):
        if not fs.lexists(need):
            return write_inconclusive(a.out, env, f"fixture incomplete: {need} not found from WSL")
    controls = {p.id: run_control(p, ctx, fs, plain) for p in PROBES.values()}
    for pid, c in controls.items():
        why = "" if c["ok"] else "  " + str(c.get("skipped") or c.get("detail") or c.get("error") or "no effect seen")
        print(f"control {pid:<13}{'ok' if c['ok'] else 'FAILED' + why}")
    results, aborted = run_matrix(cases(base), ctx, fs, runner, controls)
    paths: dict[str, int] = {}
    banners: dict[str, str] = {}
    for r in results:
        paths[str(r["prompt_path"])] = paths.get(str(r["prompt_path"]), 0) + 1
        if r["case"] not in banners and r.get("output_tail"):
            banners[r["case"]] = r["output_tail"]
    rec = {
        "ticket": TICKET, "schema": SCHEMA, "nono_issue": "nolabs-ai/nono#2089", "operator": a.operator,
        "fixture": a.fixture, "env": env, "prepare_record": {k: prep[k] for k in prep if k != "secrets"},
        "runs_per_case": RUNS, "controls_outside_nono": controls, "results": results,
        "prompt_paths": paths, "aborted": aborted, "sweep": sweep(fs, ctx), "not_measured": NOT_MEASURED,
        "output_tails_by_case": banners,
    }
    code = conclude(rec, a.out)
    print("prompt paths taken:", paths)
    if rec["sweep"]["problems"] or rec["sweep"]["leftovers_in_grant"]:
        print("sweep:", rec["sweep"])
    if aborted:
        print("ABORTED:", aborted)
        return 4 if code == 0 else code
    return code


def main() -> int:
    ap = argparse.ArgumentParser(description="#1755 nono 9P fail-closed control (see the module docstring)")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--prepare-windows", action="store_true")
    ap.add_argument("--cleanup-windows", action="store_true")
    ap.add_argument("--force-cleanup", action="store_true", help="with --cleanup-windows: remove even if the "
                    "Windows-side sweep found changes in the ungranted folders")
    ap.add_argument("--preflight-windows", action="store_true", help="drive every probe at the prepared fixture "
                    "on Windows with a runner that enforces nothing; each must see its effect")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--fixture")
    ap.add_argument("--operator", choices=["agent", "LA"])
    ap.add_argument("--out")
    ap.add_argument("--stdin-mode", choices=["pty", "piped"], default="pty")
    a = ap.parse_args()
    if sum([a.self_test, a.prepare_windows, a.cleanup_windows, a.preflight_windows, a.live]) > 1:
        print("REFUSED: pick one mode", file=sys.stderr)
        return 2
    if a.self_test:
        return self_test()
    if a.prepare_windows:
        return prepare_windows(a.fixture or "p1755-" + uuid.uuid4().hex[:6])
    if a.cleanup_windows:
        if not a.fixture:
            print("REFUSED: --cleanup-windows needs --fixture NAME", file=sys.stderr)
            return 2
        return cleanup_windows(a.fixture, force=a.force_cleanup)
    if a.preflight_windows:
        if not a.fixture:
            print("REFUSED: --preflight-windows needs --fixture NAME", file=sys.stderr)
            return 2
        return preflight_windows(a.fixture)
    if a.live:
        return live(a)
    return dry_run(a.fixture or "p1755-dryrun")


if __name__ == "__main__":
    sys.exit(main())
