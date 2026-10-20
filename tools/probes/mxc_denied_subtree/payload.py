"""In-container payload for the MXC denied-subtree probe (also run unconfined as the S4 control).

WHAT IT DOES. Runs inside the container (or, with --mode control, as an ordinary process on the same
account). Given the tree root T it performs, in order: the handshake (create T/ready.flag, wait for
T/go.flag so the host can capture the ACL of T/sub while the container is alive), the S1 writes
(outside T/sub), the S3 reads (inside T/sub), then the five S2 write attempts into T/sub.

Every attempt is made with a Win32 call (CreateFile via _winapi, MoveFileExW, DeleteFileW,
CreateDirectoryW, FindFirstFileW) so a refusal carries the real Win32 error code, never a C runtime errno.
Each is recorded as {ok, winerror, error}. The append opens with FILE_APPEND_DATA only. Layout of T/sub: marker.txt (read target and append target),
delete_me.txt (delete target), rename_me.txt (rename source).

The report is the container's own account only. Whether a write landed is judged by the host from the
tree afterwards (landing.py), never from this file.

WHAT IT DOES NOT DO. It does not touch anything outside T, it opens no network connection, and it
never retries a refused attempt.
"""

from __future__ import annotations

import _winapi
import argparse
import ctypes
import ctypes.wintypes as wt
import faulthandler
import hashlib
import json
import os
import time
from pathlib import Path

READY = "ready.flag"
GO = "go.flag"
HANDSHAKE_MAX_SECS = 12.0
HANG_SECS = 90.0  # a payload still running after this dumps its stack to stderr and exits non-zero
SUB = "sub"
MARKER = "marker.txt"
DELETE_ME = "delete_me.txt"
RENAME_SRC = "rename_me.txt"
RENAME_DST = "renamed.txt"
NEW_FILE = "s2_new.txt"
NEW_DIR = "s2_dir"
S1_NEW = "s1_new.txt"
APPEND_BYTES = b"APPENDED-BY-PAYLOAD\n"
ATTEMPTS = ("create_file", "open_write_append", "rename", "delete", "mkdir")

GENERIC_READ, GENERIC_WRITE = 0x80000000, 0x40000000
FILE_APPEND_DATA = 0x4
SHARE_ALL = 7
CREATE_NEW, OPEN_EXISTING = 1, 3
FILE_ATTRIBUTE_NORMAL = 0x80

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.MoveFileExW.argtypes = [wt.LPCWSTR, wt.LPCWSTR, wt.DWORD]
k32.DeleteFileW.argtypes = [wt.LPCWSTR]
k32.CreateDirectoryW.argtypes = [wt.LPCWSTR, ctypes.c_void_p]
k32.FindFirstFileW.argtypes = [wt.LPCWSTR, ctypes.POINTER(wt.WIN32_FIND_DATAW)]
k32.FindFirstFileW.restype = wt.HANDLE
k32.FindNextFileW.argtypes = [wt.HANDLE, ctypes.POINTER(wt.WIN32_FIND_DATAW)]
k32.FindClose.argtypes = [wt.HANDLE]
INVALID = wt.HANDLE(-1).value


def sub_contents(tag: str) -> dict[str, bytes]:
    """The files the tree builder writes into T/sub, by name, for run tag."""
    return {MARKER: f"SUB-MARKER {tag}\n".encode(), DELETE_ME: f"DELETE-ME {tag}\n".encode(),
            RENAME_SRC: f"RENAME-ME {tag}\n".encode()}


def _w(p: Path | str) -> str:
    return str(p).replace("/", "\\")


def _raise() -> None:
    raise ctypes.WinError(ctypes.get_last_error())


def create_new(path: Path, data: bytes) -> None:
    h = _winapi.CreateFile(_w(path), GENERIC_WRITE, 0, 0, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, 0)
    try:
        _winapi.WriteFile(h, data)
    finally:
        _winapi.CloseHandle(h)


def open_write_append(path: Path, data: bytes) -> None:
    """Open with FILE_APPEND_DATA only (every write lands at end of file) and append data."""
    h = _winapi.CreateFile(_w(path), FILE_APPEND_DATA, SHARE_ALL, 0, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, 0)
    try:
        _winapi.WriteFile(h, data)
    finally:
        _winapi.CloseHandle(h)


def rename(src: Path, dst: Path) -> None:
    if not k32.MoveFileExW(_w(src), _w(dst), 0):
        _raise()


def delete(path: Path) -> None:
    if not k32.DeleteFileW(_w(path)):
        _raise()


def mkdir(path: Path) -> None:
    if not k32.CreateDirectoryW(_w(path), None):
        _raise()


def read_all(path: Path) -> bytes:
    h = _winapi.CreateFile(_w(path), GENERIC_READ, SHARE_ALL, 0, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, 0)
    try:
        out = b""
        while True:
            chunk, _ = _winapi.ReadFile(h, 65536)
            if not chunk:
                return out
            out += chunk
    finally:
        _winapi.CloseHandle(h)


def list_dir(path: Path) -> list[str]:
    data = wt.WIN32_FIND_DATAW()
    h = k32.FindFirstFileW(_w(path) + "\\*", ctypes.byref(data))
    if h == INVALID or h is None:
        _raise()
    names: list[str] = []
    try:
        while True:
            if data.cFileName not in (".", ".."):
                names.append(data.cFileName)
            if not k32.FindNextFileW(h, ctypes.byref(data)):
                break
    finally:
        k32.FindClose(h)
    return sorted(names)


def _rec(fn: object) -> dict[str, object]:
    """Run fn(); return {ok, winerror, error}. winerror is the Win32 error code (None on success)."""
    try:
        fn()  # type: ignore[operator]
        return {"ok": True, "winerror": None, "error": None}
    except OSError as exc:
        return {"ok": False, "winerror": getattr(exc, "winerror", None), "error": f"{type(exc).__name__}: {exc}"[:600]}


def s1_writes(t: Path) -> dict[str, dict[str, object]]:
    return {"create_file": _rec(lambda: create_new(t / S1_NEW, b"s1-created\n")),
            "append_marker": _rec(lambda: open_write_append(t / MARKER, APPEND_BYTES))}


def s3_reads(t: Path) -> dict[str, dict[str, object]]:
    sub = t / SUB
    got: dict[str, object] = {}

    def read() -> None:
        data = read_all(sub / MARKER)
        got["read_len"], got["read_sha256"] = len(data), hashlib.sha256(data).hexdigest()

    def listing() -> None:
        got["listing"] = list_dir(sub)

    r, ls = _rec(read), _rec(listing)
    return {"read_marker": {**r, **{k: v for k, v in got.items() if k.startswith("read_")}},
            "list_sub": {**ls, **({"listing": got["listing"]} if "listing" in got else {})}}


def s2_attempts(t: Path) -> dict[str, dict[str, object]]:
    sub = t / SUB
    fns = {"create_file": lambda: create_new(sub / NEW_FILE, b"s2-created\n"),
           "open_write_append": lambda: open_write_append(sub / MARKER, APPEND_BYTES),
           "rename": lambda: rename(sub / RENAME_SRC, sub / RENAME_DST),
           "delete": lambda: delete(sub / DELETE_ME),
           "mkdir": lambda: mkdir(sub / NEW_DIR)}
    return {name: _rec(fns[name]) for name in ATTEMPTS}


def handshake(t: Path) -> dict[str, object]:
    t0 = time.perf_counter()
    rec = _rec(lambda: create_new(t / READY, b"ready\n"))
    seen_go = False
    while rec["ok"] and time.perf_counter() - t0 < HANDSHAKE_MAX_SECS:
        if (t / GO).exists():
            seen_go = True
            break
        time.sleep(0.05)
    return {"ready_written": rec, "go_seen": seen_go, "waited_secs": round(time.perf_counter() - t0, 3)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--t", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--mode", choices=("container", "control"), default="container")
    a = ap.parse_args()
    faulthandler.dump_traceback_later(HANG_SECS, exit=True)
    rep: dict[str, object] = {"mode": a.mode, "pid": os.getpid()}
    if a.mode == "container":
        rep["handshake"] = handshake(a.t)
    rep["s1"] = s1_writes(a.t)
    rep["s3"] = s3_reads(a.t)
    rep["s2"] = s2_attempts(a.t)
    a.out.write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(json.dumps({"mode": a.mode, "s2_ok": {k: v["ok"] for k, v in rep["s2"].items()}}))  # type: ignore[union-attr]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
