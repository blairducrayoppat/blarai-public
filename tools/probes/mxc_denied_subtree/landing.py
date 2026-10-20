"""Host-side landing detection for the MXC denied-subtree probe.

WHAT IT DECIDES. Whether T/sub is exactly as it was before the run, from the tree on disk: every entry's
kind, size, sha256, attributes (read-only, hidden, system), last-write time (files only) and alternate data streams
(name, size, sha256). Any difference inside T/sub (``sub_changes``) is a FAIL candidate; the five per-attempt
predicates (``landings``) attribute a difference to the attempt that made it and decide nothing on their own.
The container's report is carried alongside and compared, never trusted.

NOT COMPARED: access times; change time; the archive bit; per-entry ACLs inside T/sub; a directory's own
last-write time (it moved by a few milliseconds shortly after the tree builder wrote into it, which made
every first comparison unstable). Bound: a file created and deleted again inside T/sub (or renamed and renamed
back) leaves only the directory stamp behind and is not seen here.

READ ERRORS. A failed read (sha256, streams or stat of an entry) and a failed LISTING (a directory that could
not be enumerated) are recorded in the snapshot's ``errors`` and make the run INSTRUMENT-BLIND
(``read_errors`` non-empty) unless a landing elsewhere already makes it FAIL. They exclude different things.
A failed read excludes only the CONTENT comparison of that entry (``content_blind``): its kind, and whether it
exists in each snapshot, are still evidence, because the parent listing succeeded. An entry that appears in a
successful listing, or vanishes from one, is a change and a landing whatever its bytes. A failed listing
excludes everything strictly below that directory in either snapshot (``listing_blind``); the directory entry
itself is still compared. A read error alone never produces a change or a landing for an entry present in both
snapshots.
``layout_ok`` asserts that the before-snapshot holds exactly the files the tree builder wrote.

``judge(..., host_side=False)`` judges from the container report alone. It exists so the self-test can show
the host-side comparison is what catches a landing the report does not admit.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import hashlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import payload as P  # noqa: E402

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)


class _StreamData(ctypes.Structure):
    _fields_ = [("StreamSize", ctypes.c_longlong), ("cStreamName", ctypes.c_wchar * 296)]


_k32.FindFirstStreamW.argtypes = [wt.LPCWSTR, ctypes.c_int, ctypes.POINTER(_StreamData), wt.DWORD]
_k32.FindFirstStreamW.restype = wt.HANDLE
_k32.FindNextStreamW.argtypes = [wt.HANDLE, ctypes.POINTER(_StreamData)]
_k32.FindClose.argtypes = [wt.HANDLE]
_k32.GetFileAttributesW.argtypes = [wt.LPCWSTR]
_k32.GetFileAttributesW.restype = wt.DWORD
_INVALID = wt.HANDLE(-1).value
ERROR_HANDLE_EOF = 38
ATTR_MASK = 0x1 | 0x2 | 0x4  # read-only, hidden, system


def read_bytes(p: Path | str) -> bytes:
    """Whole-file read with plain share flags (read, write, delete) and no backup semantics."""
    return P.read_all(Path(p))


def streams_of(p: Path, errors: list[dict[str, str]], rel: str) -> list[dict[str, object]]:
    """Alternate data streams of a file or directory (FindFirstStreamW); the default data stream is omitted."""
    out: list[dict[str, object]] = []
    data = _StreamData()
    ctypes.set_last_error(0)
    h = _k32.FindFirstStreamW(str(p), 0, ctypes.byref(data), 0)
    if h == _INVALID or h is None:
        err = ctypes.get_last_error()
        if err not in (0, ERROR_HANDLE_EOF):
            errors.append({"path": rel, "op": "streams", "error": str(err)})
        return out
    try:
        while True:
            name = data.cStreamName
            if name != "::$DATA":
                sha = None
                try:
                    sha = hashlib.sha256(read_bytes(str(p) + name.replace(":$DATA", ""))).hexdigest()
                except OSError as exc:
                    errors.append({"path": f"{rel}{name}", "op": "stream-read", "error": repr(exc)[:200]})
                out.append({"name": name, "size": data.StreamSize, "sha256": sha})
            if not _k32.FindNextStreamW(h, ctypes.byref(data)):
                break
    finally:
        _k32.FindClose(h)
    return out


def snapshot_tree(t: Path) -> dict[str, object]:
    """Recursive listing of T with kind, size, sha256, attributes, mtime and streams per entry.

    Keys are posix paths relative to T. ``errors`` lists every read that failed; such an entry carries
    ``unreadable: True`` and its content fields are left out of comparisons.
    """
    entries: dict[str, dict[str, object]] = {}
    errors: list[dict[str, str]] = []

    def walk(d: Path) -> None:
        try:
            with os.scandir(d) as it:
                children = sorted(it, key=lambda e: e.name)
        except OSError as exc:
            errors.append({"path": d.relative_to(t).as_posix() if d != t else ".", "op": "list", "error": repr(exc)[:200]})
            return
        for e in children:
            p = Path(e.path)
            rel = p.relative_to(t).as_posix()
            ent: dict[str, object] = {}
            bad = len(errors)
            attr = _k32.GetFileAttributesW(str(p))
            try:
                st = e.stat(follow_symlinks=False)
                if not e.is_dir(follow_symlinks=False):  # a directory's own stamp is updated lazily; its entries are compared instead
                    ent["mtime_ns"] = st.st_mtime_ns
            except OSError as exc:
                errors.append({"path": rel, "op": "stat", "error": repr(exc)[:200]})
                st = None
            ent["attrs"] = (attr & ATTR_MASK) if attr != 0xFFFFFFFF else None
            ent["streams"] = streams_of(p, errors, rel)
            if e.is_dir(follow_symlinks=False):
                ent["kind"] = "dir"
            else:
                ent["kind"] = "file"
                ent["size"] = st.st_size if st else None
                try:
                    ent["sha256"] = hashlib.sha256(read_bytes(p)).hexdigest()
                except OSError as exc:
                    ent["sha256"] = None
                    errors.append({"path": rel, "op": "read", "error": repr(exc)[:200]})
            if len(errors) > bad:
                ent["unreadable"] = True
            entries[rel] = ent
            if ent["kind"] == "dir":
                walk(p)

    walk(t)
    return {"entries": entries, "errors": errors}


def _e(snap: dict[str, object], rel: str) -> dict[str, object] | None:
    return snap["entries"].get(rel)  # type: ignore[union-attr]


def _in_sub(rel: str) -> bool:
    return rel == P.SUB or rel.startswith(f"{P.SUB}/")


def relevant_errors(snap: dict[str, object]) -> list[dict[str, str]]:
    """Read errors on paths the judgement depends on: T/sub, the T marker and the S1 file."""
    keep = {P.MARKER, P.S1_NEW}
    return [e for e in snap["errors"] if _in_sub(e["path"].split(":")[0]) or e["path"].split(":")[0] in keep or e["path"] == "."]  # type: ignore[union-attr]


def skipped_paths(*snaps: dict[str, object]) -> tuple[set[str], list[str]]:
    """(paths whose content could not be read, directories whose listing failed) across the given snapshots."""
    paths: set[str] = set()
    dirs: list[str] = []
    for snap in snaps:
        for e in snap["errors"]:  # type: ignore[union-attr]
            base = e["path"].split(":")[0]
            if e["op"] == "list":
                dirs.append("" if base == "." else base)
            else:
                paths.add(base)
        paths |= {k for k, v in snap["entries"].items() if v.get("unreadable")}  # type: ignore[union-attr]
    return paths, dirs


def listing_blind(rel: str, skip: tuple[set[str], list[str]]) -> bool:
    """rel lies strictly below a directory whose listing failed: its existence is not evidenced either way."""
    return any(d == "" or rel.startswith(d + "/") for d in skip[1])


def content_blind(rel: str, skip: tuple[set[str], list[str]]) -> bool:
    """rel's bytes, streams or stamps cannot be compared: a read of it failed, or it lies below an unlisted directory."""
    return rel in skip[0] or listing_blind(rel, skip)


def sub_changes(before: dict[str, object], after: dict[str, object]) -> list[str]:
    """Every path at or under T/sub whose entry differs, appeared or vanished.

    An entry present in only one snapshot is a change even when its content is unreadable. An entry present in
    both whose content could not be read on either side is compared by kind only. Paths below a directory whose
    listing failed are left out.
    """
    b, a = before["entries"], after["entries"]  # type: ignore[index]
    skip = skipped_paths(before, after)
    out = []
    for k in sorted(set(b) | set(a)):  # type: ignore[arg-type]
        if not _in_sub(k) or listing_blind(k, skip):
            continue
        eb, ea = b.get(k), a.get(k)  # type: ignore[union-attr]
        if eb is None or ea is None:
            out.append(k)
        elif eb.get("unreadable") or ea.get("unreadable") or content_blind(k, skip):
            if eb.get("kind") != ea.get("kind"):
                out.append(k)
        elif eb != ea:
            out.append(k)
    return out


def layout_ok(before: dict[str, object], tag: str) -> bool:
    """The before-snapshot holds sub and each file the tree builder wrote, with the bytes it wrote, all readable."""
    if _e(before, P.SUB) is None or relevant_errors(before):
        return False
    for name, data in P.sub_contents(tag).items():
        ent = _e(before, f"{P.SUB}/{name}")
        if ent is None or ent.get("sha256") != hashlib.sha256(data).hexdigest():
            return False
    return True


def landings(before: dict[str, object], after: dict[str, object]) -> dict[str, bool]:
    """Per-attempt attribution: did this attempt's own effect appear inside T/sub.

    The existence predicates (create, rename, delete, mkdir) read listings and kinds, so an unreadable entry
    still counts; only a directory whose listing failed hides them. The append predicate compares bytes and is
    False when either marker read failed.
    """
    sub = P.SUB
    skip = skipped_paths(before, after)

    def ent(snap: dict[str, object], name: str) -> dict[str, object] | None:
        return _e(snap, f"{sub}/{name}")

    def listed(*names: str) -> bool:
        return not any(listing_blind(f"{sub}/{n}", skip) for n in names)

    b_marker, a_marker = ent(before, P.MARKER), ent(after, P.MARKER)
    a_new, a_dir = ent(after, P.NEW_FILE), ent(after, P.NEW_DIR)
    return {
        "create_file": listed(P.NEW_FILE) and a_new is not None and a_new.get("kind") == "file",
        "open_write_append": (not content_blind(f"{sub}/{P.MARKER}", skip) and b_marker is not None and a_marker is not None
                              and a_marker.get("sha256") != b_marker.get("sha256")),
        "rename": (listed(P.RENAME_SRC, P.RENAME_DST) and ent(before, P.RENAME_SRC) is not None
                   and ent(after, P.RENAME_SRC) is None and ent(after, P.RENAME_DST) is not None),
        "delete": listed(P.DELETE_ME) and ent(before, P.DELETE_ME) is not None and ent(after, P.DELETE_ME) is None,
        "mkdir": listed(P.NEW_DIR) and a_dir is not None and a_dir.get("kind") == "dir",
    }


def unattributed(changes: list[str]) -> list[str]:
    """Changed paths in T/sub that none of the five named attempts accounts for."""
    named = {f"{P.SUB}/{n}" for n in (P.MARKER, P.DELETE_ME, P.RENAME_SRC, P.RENAME_DST, P.NEW_FILE, P.NEW_DIR)}
    return [c for c in changes if c not in named]


def s1_effects(before: dict[str, object], after: dict[str, object]) -> dict[str, bool]:
    """S1 judged from the host: the new file exists in T, and T's marker carries exactly the appended bytes."""
    new = _e(after, P.S1_NEW)
    b, a = _e(before, P.MARKER), _e(after, P.MARKER)
    return {"create_file": new is not None and new.get("kind") == "file",
            "append_marker": (b is not None and a is not None
                              and a.get("size") == int(b.get("size", -1)) + len(P.APPEND_BYTES)  # type: ignore[call-overload]
                              and a.get("sha256") != b.get("sha256"))}


def judge(report: dict[str, object] | None, before: dict[str, object], after: dict[str, object],
          host_side: bool = True, tag: str | None = None) -> dict[str, object]:
    """Judgement for one run: host-side comparison of T/sub, the container's report, and their disagreements."""
    rep_s2 = (report or {}).get("s2") or {}
    reported = {n: bool(rep_s2.get(n, {}).get("ok")) for n in P.ATTEMPTS}  # type: ignore[union-attr]
    attempted = all(n in rep_s2 for n in P.ATTEMPTS)  # type: ignore[operator]
    host = landings(before, after) if host_side else dict(reported)
    # an attempt the host could not judge (unlisted directory; unreadable marker for the append) cannot be compared with the report
    skip = skipped_paths(before, after)
    blind_paths = {n for n, names in (("create_file", (P.NEW_FILE,)), ("open_write_append", (P.MARKER,)),
                                      ("rename", (P.RENAME_SRC, P.RENAME_DST)), ("delete", (P.DELETE_ME,)),
                                      ("mkdir", (P.NEW_DIR,)))
                   if any((content_blind if n == "open_write_append" else listing_blind)(f"{P.SUB}/{x}", skip) for x in names)}
    changes = sub_changes(before, after) if host_side else []
    errs = relevant_errors(before) + relevant_errors(after)
    return {
        "host_side": host_side, "attempts_executed": attempted, "landed": host,
        "landed_count": sum(host.values()), "reported_success": reported,
        "disagreements": sorted(n for n in P.ATTEMPTS if reported[n] != host[n] and n not in blind_paths) if host_side else [],
        "sub_changes": changes, "sub_unchanged": not changes, "unattributed_changes": unattributed(changes),
        "read_errors": errs, "layout_ok": layout_ok(before, tag) if tag else None,
    }
