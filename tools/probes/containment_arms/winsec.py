"""Windows security primitives for the #1740 containment comparison (ctypes, stdlib only).

Dev-side measurement tooling: it builds BlarAI, it never ships inside it. Nothing here
changes machine state. Every token it makes lives only in this process's memory; no
account is logged on, no AppContainer profile is registered, no ACL on a real path is
written. Functions that would change machine state (creating an AppContainer profile,
launching a process in one) live in ``run_arm.py`` behind an explicit phase-2 switch.

Two independent access-check instruments are provided so they can be compared:

* ``kernel_access`` — ``AccessCheck`` (advapi32), the same check the kernel runs on
  open, evaluated against a real token. It honours restricting SIDs, write-restricted
  tokens, AppContainer (lowbox) tokens and mandatory integrity labels.
* ``authz_access`` — ``AuthzAccessCheck`` against a client context built from a bare
  SID (no logon). This is the only way to evaluate an account without logging it on;
  its group set is computed by AuthZ and is reported alongside every result.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
from dataclasses import dataclass

advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernelbase = ctypes.WinDLL("kernelbase", use_last_error=True)
userenv = ctypes.WinDLL("userenv", use_last_error=True)
authz = ctypes.WinDLL("authz", use_last_error=True)
ntdll = ctypes.WinDLL("ntdll")

PSID = ctypes.c_void_p
HANDLE = wt.HANDLE
kernel32.GetCurrentProcess.restype = HANDLE

# Token access and information classes.
TOKEN_QUERY = 0x0008
TOKEN_DUPLICATE = 0x0002
TOKEN_ASSIGN_PRIMARY = 0x0001
TOKEN_ADJUST_PRIVILEGES = 0x0020
TOKEN_ADJUST_DEFAULT = 0x0080
TOKEN_ALL_ACCESS = 0xF01FF
MAXIMUM_ALLOWED = 0x02000000
TokenUser = 1
TokenGroups = 2
TokenPrivileges = 3
TokenRestrictedSids = 11
TokenElevationType = 18
TokenLinkedToken = 19
TokenIntegrityLevel = 25
TokenIsAppContainer = 29
TokenAppContainerSid = 31
SecurityIdentification = 1
SecurityImpersonation = 2
TokenPrimary = 1
TokenImpersonation = 2

# CreateRestrictedToken flags.
DISABLE_MAX_PRIVILEGE = 0x1
SANDBOX_INERT = 0x2
WRITE_RESTRICTED = 0x8

# SAFER levels (what `runas /trustlevel:0x20000` computes).
SAFER_SCOPEID_USER = 2
SAFER_LEVELID_NORMALUSER = 0x20000
SAFER_LEVEL_OPEN = 1

# Security information.
OWNER_SECURITY_INFORMATION = 0x1
GROUP_SECURITY_INFORMATION = 0x2
DACL_SECURITY_INFORMATION = 0x4
LABEL_SECURITY_INFORMATION = 0x10
SE_FILE_OBJECT = 1

# File rights (directory meanings in comments).
FILE_READ_DATA = 0x1  # list directory
FILE_WRITE_DATA = 0x2  # add file
FILE_APPEND_DATA = 0x4  # add subdirectory
FILE_EXECUTE = 0x20  # traverse
DELETE = 0x10000
WRITE_DAC = 0x40000
WRITE_OWNER = 0x80000
FILE_GENERIC_READ = 0x120089
FILE_GENERIC_WRITE = 0x120116
FILE_GENERIC_EXECUTE = 0x1200A0
FILE_ALL_ACCESS = 0x1F01FF


class GENERIC_MAPPING(ctypes.Structure):
    _fields_ = [("GenericRead", wt.DWORD), ("GenericWrite", wt.DWORD),
                ("GenericExecute", wt.DWORD), ("GenericAll", wt.DWORD)]


FILE_MAPPING = GENERIC_MAPPING(FILE_GENERIC_READ, FILE_GENERIC_WRITE,
                               FILE_GENERIC_EXECUTE, FILE_ALL_ACCESS)


class SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", PSID), ("Attributes", wt.DWORD)]


class LUID(ctypes.Structure):
    _fields_ = [("LowPart", wt.DWORD), ("HighPart", wt.LONG)]


class LUID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Luid", LUID), ("Attributes", wt.DWORD)]


class AUTHZ_ACCESS_REQUEST(ctypes.Structure):
    _fields_ = [("DesiredAccess", wt.DWORD), ("PrincipalSelfSid", PSID),
                ("ObjectTypeList", ctypes.c_void_p), ("ObjectTypeListLength", wt.DWORD),
                ("OptionalArguments", ctypes.c_void_p)]


class AUTHZ_ACCESS_REPLY(ctypes.Structure):
    _fields_ = [("ResultListLength", wt.DWORD), ("GrantedAccessMask", ctypes.POINTER(wt.DWORD)),
                ("SaclEvaluationResults", ctypes.POINTER(wt.DWORD)),
                ("Error", ctypes.POINTER(wt.DWORD))]


class WinSecError(OSError):
    """A Windows security call failed; the message names the call and the error code."""


def _check(ok: object, call: str) -> None:
    if not ok:
        err = ctypes.get_last_error()
        raise WinSecError(err, f"{call} failed: {ctypes.FormatError(err).strip()} ({err})")


# ---------------------------------------------------------------- SIDs

def sid_from_string(text: str) -> ctypes.c_void_p:
    p = PSID()
    _check(advapi32.ConvertStringSidToSidW(wt.LPCWSTR(text), ctypes.byref(p)),
           f"ConvertStringSidToSidW({text})")
    return p


def sid_to_string(sid: int | ctypes.c_void_p) -> str:
    out = wt.LPWSTR()
    _check(advapi32.ConvertSidToStringSidW(PSID(sid if isinstance(sid, int) else sid.value),
                                           ctypes.byref(out)), "ConvertSidToStringSidW")
    try:
        return out.value or ""
    finally:
        kernel32.LocalFree(out)


def sid_of_account(name: str) -> str:
    sid_buf = ctypes.create_string_buffer(256)
    sid_len = wt.DWORD(256)
    dom = ctypes.create_unicode_buffer(256)
    dom_len = wt.DWORD(256)
    use = wt.DWORD()
    _check(advapi32.LookupAccountNameW(None, name, sid_buf, ctypes.byref(sid_len), dom,
                                       ctypes.byref(dom_len), ctypes.byref(use)),
           f"LookupAccountNameW({name})")
    return sid_to_string(ctypes.addressof(sid_buf))


def account_of_sid(text: str) -> str:
    sid = sid_from_string(text)
    name = ctypes.create_unicode_buffer(256)
    n_len = wt.DWORD(256)
    dom = ctypes.create_unicode_buffer(256)
    d_len = wt.DWORD(256)
    use = wt.DWORD()
    if not advapi32.LookupAccountSidW(None, sid, name, ctypes.byref(n_len), dom,
                                      ctypes.byref(d_len), ctypes.byref(use)):
        return text
    return f"{dom.value}\\{name.value}" if dom.value else name.value


def derive_appcontainer_sid(name: str) -> str:
    """Package SID for an AppContainer name. Pure derivation: registers nothing."""
    p = PSID()
    hr = userenv.DeriveAppContainerSidFromAppContainerName(wt.LPCWSTR(name), ctypes.byref(p))
    if hr != 0:
        raise WinSecError(hr, f"DeriveAppContainerSidFromAppContainerName hr=0x{hr & 0xFFFFFFFF:08x}")
    try:
        return sid_to_string(p)
    finally:
        advapi32.FreeSid(p)


def derive_capability_sid(name: str) -> str:
    """Capability SID (S-1-15-3-1024-...) for a capability name. Pure derivation."""
    grp = ctypes.POINTER(PSID)()
    grp_n = wt.DWORD()
    caps = ctypes.POINTER(PSID)()
    caps_n = wt.DWORD()
    _check(kernelbase.DeriveCapabilitySidsFromName(wt.LPCWSTR(name), ctypes.byref(grp),
                                                   ctypes.byref(grp_n), ctypes.byref(caps),
                                                   ctypes.byref(caps_n)),
           f"DeriveCapabilitySidsFromName({name})")
    try:
        return sid_to_string(caps[0])
    finally:
        for i in range(grp_n.value):
            kernel32.LocalFree(grp[i])
        for i in range(caps_n.value):
            kernel32.LocalFree(caps[i])
        kernel32.LocalFree(grp)
        kernel32.LocalFree(caps)


# ---------------------------------------------------------------- tokens

def process_token(access: int = TOKEN_QUERY | TOKEN_DUPLICATE | TOKEN_ASSIGN_PRIMARY
                  | TOKEN_ADJUST_DEFAULT) -> HANDLE:
    h = HANDLE()
    _check(advapi32.OpenProcessToken(HANDLE(kernel32.GetCurrentProcess()), access, ctypes.byref(h)),
           "OpenProcessToken")
    return h


def _token_info(token: HANDLE, cls: int) -> ctypes.Array:
    need = wt.DWORD()
    advapi32.GetTokenInformation(token, cls, None, 0, ctypes.byref(need))
    buf = ctypes.create_string_buffer(max(need.value, 4))
    _check(advapi32.GetTokenInformation(token, cls, buf, need, ctypes.byref(need)),
           f"GetTokenInformation({cls})")
    return buf


def linked_token(token: HANDLE) -> HANDLE:
    """The other half of a split admin token: from an elevated token, the limited one."""
    buf = _token_info(token, TokenLinkedToken)
    return HANDLE(ctypes.cast(buf, ctypes.POINTER(HANDLE))[0])


def elevation_type(token: HANDLE) -> int:
    """1 default (not split), 2 full (elevated), 3 limited."""
    return ctypes.cast(_token_info(token, TokenElevationType), ctypes.POINTER(wt.DWORD))[0]


def _groups(buf: ctypes.Array) -> list[tuple[str, int]]:
    count = ctypes.cast(buf, ctypes.POINTER(wt.DWORD))[0]
    arr = ctypes.cast(ctypes.addressof(buf) + ctypes.sizeof(ctypes.c_void_p),
                      ctypes.POINTER(SID_AND_ATTRIBUTES))
    return [(sid_to_string(arr[i].Sid), arr[i].Attributes) for i in range(count)]


SE_GROUP_ENABLED = 0x4
SE_GROUP_USE_FOR_DENY_ONLY = 0x10
SE_GROUP_INTEGRITY = 0x20
SE_GROUP_LOGON_ID = 0xC0000000


def describe_token(token: HANDLE) -> dict[str, object]:
    """User, groups (enabled / deny-only), restricting SIDs, integrity, AppContainer, privileges."""
    user_buf = _token_info(token, TokenUser)
    user = sid_to_string(ctypes.cast(user_buf, ctypes.POINTER(SID_AND_ATTRIBUTES))[0].Sid)
    groups = _groups(_token_info(token, TokenGroups))
    restricted = _groups(_token_info(token, TokenRestrictedSids))
    il_buf = _token_info(token, TokenIntegrityLevel)
    il = sid_to_string(ctypes.cast(il_buf, ctypes.POINTER(SID_AND_ATTRIBUTES))[0].Sid)
    is_ac = ctypes.cast(_token_info(token, TokenIsAppContainer), ctypes.POINTER(wt.DWORD))[0]
    ac_sid = ""
    if is_ac:
        ac_buf = _token_info(token, TokenAppContainerSid)
        ac_sid = sid_to_string(ctypes.cast(ac_buf, ctypes.POINTER(PSID))[0])
    priv_buf = _token_info(token, TokenPrivileges)
    n_priv = ctypes.cast(priv_buf, ctypes.POINTER(wt.DWORD))[0]
    privs = ctypes.cast(ctypes.addressof(priv_buf) + 4, ctypes.POINTER(LUID_AND_ATTRIBUTES))
    priv_names = []
    for i in range(n_priv):
        name = ctypes.create_unicode_buffer(64)
        size = wt.DWORD(64)
        advapi32.LookupPrivilegeNameW(None, ctypes.byref(privs[i].Luid), name, ctypes.byref(size))
        priv_names.append(name.value)
    return {
        "user": user,
        "groups_enabled": [s for s, a in groups if a & SE_GROUP_ENABLED and not a & SE_GROUP_INTEGRITY],
        "groups_deny_only": [s for s, a in groups if a & SE_GROUP_USE_FOR_DENY_ONLY],
        "restricting_sids": [s for s, _ in restricted],
        "integrity": il,
        "appcontainer_sid": ac_sid,
        "privileges": priv_names,
    }


def to_impersonation(token: HANDLE) -> HANDLE:
    out = HANDLE()
    _check(advapi32.DuplicateTokenEx(token, MAXIMUM_ALLOWED, None, SecurityIdentification,
                                     TokenImpersonation, ctypes.byref(out)), "DuplicateTokenEx")
    return out


def to_primary(token: HANDLE) -> HANDLE:
    out = HANDLE()
    _check(advapi32.DuplicateTokenEx(token, MAXIMUM_ALLOWED, None, SecurityImpersonation,
                                     TokenPrimary, ctypes.byref(out)), "DuplicateTokenEx(primary)")
    return out


def restricted_token(base: HANDLE, *, flags: int, deny_only: list[str],
                     restricting: list[str]) -> HANDLE:
    """CreateRestrictedToken: deny-only groups, privileges stripped, optional restricting SIDs."""
    keep = []
    deny = (SID_AND_ATTRIBUTES * max(len(deny_only), 1))()
    for i, s in enumerate(deny_only):
        p = sid_from_string(s)
        keep.append(p)
        deny[i].Sid = p
    rest = (SID_AND_ATTRIBUTES * max(len(restricting), 1))()
    for i, s in enumerate(restricting):
        p = sid_from_string(s)
        keep.append(p)
        rest[i].Sid = p
    out = HANDLE()
    _check(advapi32.CreateRestrictedToken(base, flags, len(deny_only), deny if deny_only else None,
                                          0, None, len(restricting), rest if restricting else None,
                                          ctypes.byref(out)), "CreateRestrictedToken")
    return out


class TOKEN_MANDATORY_LABEL(ctypes.Structure):
    _fields_ = [("Label", SID_AND_ATTRIBUTES)]


def set_integrity(token: HANDLE, il_sid: str) -> None:
    """Lower a token's integrity level (raising needs a privilege this tool never uses)."""
    p = sid_from_string(il_sid)
    tml = TOKEN_MANDATORY_LABEL(SID_AND_ATTRIBUTES(p, SE_GROUP_INTEGRITY))
    _check(advapi32.SetTokenInformation(token, TokenIntegrityLevel, ctypes.byref(tml),
                                        ctypes.sizeof(tml) + 64), "SetTokenInformation(IL)")


ADMINISTRATORS = "S-1-5-32-544"
LOCAL_ACCOUNT_AND_ADMIN = "S-1-5-114"
MEDIUM_IL = "S-1-16-8192"


def limited_equivalent(elevated: HANDLE) -> HANDLE:
    """A PRIMARY token shaped like the operator's limited (UAC-filtered) token.

    The real limited token is only reachable at identification level from here, which
    ``NtCreateLowBoxToken`` and ``CreateProcessAsUser`` refuse. This one disables the
    administrator groups as deny-only, strips privileges and sets medium integrity; the
    caller must compare its access results with the real limited token's before use.
    """
    tok = restricted_token(elevated, flags=DISABLE_MAX_PRIVILEGE,
                           deny_only=[ADMINISTRATORS, LOCAL_ACCOUNT_AND_ADMIN], restricting=[])
    set_integrity(tok, MEDIUM_IL)
    return tok


TokenDefaultDacl = 6


class TOKEN_DEFAULT_DACL(ctypes.Structure):
    _fields_ = [("DefaultDacl", ctypes.c_void_p)]


def set_default_dacl(token: HANDLE, sids: list[str]) -> None:
    """Make the token's default access list grant GENERIC_ALL to ``sids``.

    A restricted process must pass the restricting check on its OWN process and thread objects, whose
    security descriptor comes from the token's default list; without entries for the restricting SIDs it
    cannot open itself and dies during DLL initialisation (0xC0000142). Chromium and Codex both set it.
    Pass only identities that need to open the process's own objects (the user, SYSTEM, the logon identity and
    a sandbox-specific identity), not broad groups.
    """
    sddl = "D:" + "".join(f"(A;;GA;;;{sid})" for sid in sids)
    sd = ctypes.c_void_p()
    _check(advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(wt.LPCWSTR(sddl), 1,
                                                                         ctypes.byref(sd), None),
           "ConvertStringSecurityDescriptorToSecurityDescriptorW(default dacl)")
    try:
        present = wt.BOOL()
        acl = ctypes.c_void_p()
        defaulted = wt.BOOL()
        _check(advapi32.GetSecurityDescriptorDacl(sd, ctypes.byref(present), ctypes.byref(acl),
                                                  ctypes.byref(defaulted)), "GetSecurityDescriptorDacl")
        info = TOKEN_DEFAULT_DACL(acl)
        _check(advapi32.SetTokenInformation(token, TokenDefaultDacl, ctypes.byref(info),
                                            ctypes.sizeof(info)), "SetTokenInformation(DefaultDacl)")
    finally:
        kernel32.LocalFree(sd)


def logon_sid(token: HANDLE) -> str:
    """The logon-session SID of ``token`` (SE_GROUP_LOGON_ID), which window-station and desktop objects grant."""
    for sid, attrs in _groups(_token_info(token, TokenGroups)):
        if attrs & SE_GROUP_LOGON_ID == SE_GROUP_LOGON_ID:
            return sid
    raise WinSecError(0, "token has no logon SID")


def limited_restricted(elevated: HANDLE, *, flags: int, restricting: list[str]) -> HANDLE:
    """The operator's limited-shaped token with restricting SIDs, derived from ``elevated`` in ONE step.

    ``CreateProcessAsUser`` accepts a token only when it is derived directly from the caller's own
    token, so a restricted token made from ``limited_equivalent`` (two steps) cannot be launched. This
    builds the same shape in one step: administrator groups deny-only, privileges stripped, the
    restricting list, then medium integrity.
    """
    tok = restricted_token(elevated, flags=flags | DISABLE_MAX_PRIVILEGE,
                           deny_only=[ADMINISTRATORS, LOCAL_ACCOUNT_AND_ADMIN], restricting=restricting)
    set_integrity(tok, MEDIUM_IL)
    user = describe_token(elevated)["user"]
    # Only identities that must be able to open the process's own objects: not the broad groups in the
    # restricting list (Everyone, Users, Authenticated Users, RESTRICTED), which would let any other
    # account's process open this one.
    own = [s for s in restricting if s.startswith("S-1-5-80-") or s == logon_sid(elevated)]
    set_default_dacl(tok, list(dict.fromkeys([user, "S-1-5-18", logon_sid(elevated), *own])))
    return tok


def safer_normal_user_token(base: HANDLE) -> HANDLE:
    """The token `runas /trustlevel:0x20000` computes from ``base``."""
    level = HANDLE()
    _check(advapi32.SaferCreateLevel(SAFER_SCOPEID_USER, SAFER_LEVELID_NORMALUSER,
                                     SAFER_LEVEL_OPEN, ctypes.byref(level), None),
           "SaferCreateLevel")
    out = HANDLE()
    try:
        _check(advapi32.SaferComputeTokenFromLevel(level, base, ctypes.byref(out), 0, None),
               "SaferComputeTokenFromLevel")
    finally:
        advapi32.SaferCloseLevel(level)
    return out


def lowbox_token(base: HANDLE, package_sid: str, capabilities: list[str]) -> HANDLE:
    """An AppContainer (lowbox) token in memory, via NtCreateLowBoxToken.

    No profile, folder or registry key is created. A process launched for real also gets
    a per-package object directory and profile-scoped folders; this token does not, so an
    access result from it is a PREDICTION of the real launch for file access only.
    """
    pkg = sid_from_string(package_sid)
    caps = (SID_AND_ATTRIBUTES * max(len(capabilities), 1))()
    keep = [pkg]
    for i, s in enumerate(capabilities):
        p = sid_from_string(s)
        keep.append(p)
        caps[i].Sid = p
        caps[i].Attributes = SE_GROUP_ENABLED
    out = HANDLE()
    status = ntdll.NtCreateLowBoxToken(ctypes.byref(out), base, MAXIMUM_ALLOWED, None, pkg,
                                       len(capabilities), caps if capabilities else None, 0, None)
    if status != 0:
        raise WinSecError(status, f"NtCreateLowBoxToken status=0x{status & 0xFFFFFFFF:08x}")
    return out


def enable_privilege(name: str) -> bool:
    tok = process_token(TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY)
    luid = LUID()
    if not advapi32.LookupPrivilegeValueW(None, name, ctypes.byref(luid)):
        return False

    class TP(ctypes.Structure):
        _fields_ = [("Count", wt.DWORD), ("Priv", LUID_AND_ATTRIBUTES)]

    tp = TP(1, LUID_AND_ATTRIBUTES(luid, 0x2))
    ok = advapi32.AdjustTokenPrivileges(tok, False, ctypes.byref(tp), 0, None, None)
    err = ctypes.get_last_error()
    kernel32.CloseHandle(tok)
    return bool(ok) and err == 0


# ---------------------------------------------------------------- security descriptors

FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
READ_CONTROL = 0x20000
OPEN_EXISTING = 3
INVALID_HANDLE = HANDLE(-1).value


@dataclass
class Descriptor:
    path: str
    sd: ctypes.c_void_p
    sddl: str


def read_descriptor(path: str) -> Descriptor:
    """Owner, group, DACL and integrity label of ``path``, read-only (READ_CONTROL handle)."""
    kernel32.CreateFileW.restype = HANDLE
    h = kernel32.CreateFileW(wt.LPCWSTR(path), READ_CONTROL, 7, None, OPEN_EXISTING,
                             FILE_FLAG_BACKUP_SEMANTICS, None)
    if h in (INVALID_HANDLE, None):
        err = ctypes.get_last_error()
        raise WinSecError(err, f"open {path}: {ctypes.FormatError(err).strip()} ({err})")
    try:
        sd = ctypes.c_void_p()
        info = (OWNER_SECURITY_INFORMATION | GROUP_SECURITY_INFORMATION
                | DACL_SECURITY_INFORMATION | LABEL_SECURITY_INFORMATION)
        rc = advapi32.GetSecurityInfo(h, SE_FILE_OBJECT, info, None, None, None, None,
                                      ctypes.byref(sd))
        if rc != 0:
            raise WinSecError(rc, f"GetSecurityInfo {path}: {ctypes.FormatError(rc).strip()}")
        text = wt.LPWSTR()
        advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW(sd, 1, info,
                                                                      ctypes.byref(text), None)
        sddl = text.value or ""
        kernel32.LocalFree(text)
        return Descriptor(path, sd, sddl)
    finally:
        kernel32.CloseHandle(h)


# ---------------------------------------------------------------- access checks

def kernel_access(desc: Descriptor, imp_token: HANDLE) -> int:
    """Granted mask from AccessCheck(MAXIMUM_ALLOWED) for an impersonation token."""
    ps = ctypes.create_string_buffer(256)
    ps_len = wt.DWORD(256)
    granted = wt.DWORD()
    status = wt.BOOL()
    _check(advapi32.AccessCheck(desc.sd, imp_token, MAXIMUM_ALLOWED, ctypes.byref(FILE_MAPPING),
                                ps, ctypes.byref(ps_len), ctypes.byref(granted),
                                ctypes.byref(status)), f"AccessCheck {desc.path}")
    return granted.value if status.value else 0


class AuthzContext:
    """An AuthZ client context for a bare SID (no logon), with optional added groups."""

    def __init__(self, user_sid: str, extra_groups: list[str]) -> None:
        self._rm = HANDLE()
        _check(authz.AuthzInitializeResourceManager(1, None, None, None, None,
                                                    ctypes.byref(self._rm)),
               "AuthzInitializeResourceManager")
        base = HANDLE()
        self._keep = [sid_from_string(user_sid)]
        _check(authz.AuthzInitializeContextFromSid(0, self._keep[0], self._rm, None, LUID(0, 0),
                                                   None, ctypes.byref(base)),
               f"AuthzInitializeContextFromSid({user_sid})")
        self.computed_groups = self._group_sids(base)
        missing = [g for g in extra_groups if g not in self.computed_groups]
        self.added_groups = missing
        if missing:
            arr = (SID_AND_ATTRIBUTES * len(missing))()
            for i, s in enumerate(missing):
                p = sid_from_string(s)
                self._keep.append(p)
                arr[i].Sid = p
                arr[i].Attributes = SE_GROUP_ENABLED
            ctx = HANDLE()
            _check(authz.AuthzAddSidsToContext(base, arr, len(missing), None, 0,
                                               ctypes.byref(ctx)), "AuthzAddSidsToContext")
            authz.AuthzFreeContext(base)
            self._ctx = ctx
        else:
            self._ctx = base

    @staticmethod
    def _group_sids(ctx: HANDLE) -> list[str]:
        need = wt.DWORD()
        authz.AuthzGetInformationFromContext(ctx, 2, 0, ctypes.byref(need), None)
        buf = ctypes.create_string_buffer(max(need.value, 8))
        _check(authz.AuthzGetInformationFromContext(ctx, 2, need, ctypes.byref(need), buf),
               "AuthzGetInformationFromContext(groups)")
        return [s for s, _ in _groups(buf)]

    def access(self, desc: Descriptor) -> int:
        granted = wt.DWORD()
        sacl = wt.DWORD()
        error = wt.DWORD()
        req = AUTHZ_ACCESS_REQUEST(MAXIMUM_ALLOWED, None, None, 0, None)
        rep = AUTHZ_ACCESS_REPLY(1, ctypes.pointer(granted), ctypes.pointer(sacl),
                                 ctypes.pointer(error))
        _check(authz.AuthzAccessCheck(0, self._ctx, ctypes.byref(req), None, desc.sd, None, 0,
                                      ctypes.byref(rep), None), f"AuthzAccessCheck {desc.path}")
        return granted.value if error.value == 0 else 0

    def close(self) -> None:
        authz.AuthzFreeContext(self._ctx)
        authz.AuthzFreeResourceManager(self._rm)


def summarize(mask: int, is_dir: bool) -> dict[str, bool]:
    """Plain verdicts from a granted mask."""
    return {
        "read": bool(mask & FILE_READ_DATA),
        "write": bool(mask & FILE_WRITE_DATA),
        "create_subfolder" if is_dir else "append": bool(mask & FILE_APPEND_DATA),
        "delete": bool(mask & DELETE),
        "change_permissions": bool(mask & WRITE_DAC),
    }
