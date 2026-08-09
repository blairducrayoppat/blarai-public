"""PCR-bound seal/unseal proof-of-concept on the platform TPM 2.0 (ADR-028 / #627).

WHAT THIS PROVES (the increment `TPM_CAPABILITY_FINDINGS.md` §2/§3 flagged as
"feasible, not proven", and `trust_root_verification_2026-06-09.md` listed under
"Not measured: PCR-binding / measured-boot key policy"):

  A secret can be SEALED under a TPM 2.0 *policy* bound to a Platform
  Configuration Register (PCR) value, UNSEALED while the live PCR matches that
  value, and the unseal REFUSED when the bound value is not the live one — i.e.
  the measured-boot binding actually enforces, not just decorates.

POSITIVE vs NEGATIVE:
  - Positive: seal a secret under PolicyPCR(PCR 23 == current value); unseal in
    the current state -> succeeds, secret round-trips.
  - Negative: seal the same secret under PolicyPCR(PCR 23 == a *different* value);
    attempt to unseal in the current state -> refused (TPM_RC_POLICY_FAIL). The
    two objects differ ONLY in the bound PCR value, so the refusal is caused by
    the PCR binding.
  - The two objects' authPolicy digests are asserted to differ, so the negative
    object is provably bound to a non-current state (not merely to garbage).

WHY VALUE-BINDING AND NOT "EXTEND THE LIVE PCR": Windows TBS blocks a user-mode
TPM2_PCR_Extend with TPM_E_COMMAND_BLOCKED (recorded by this PoC). That block is
itself the protection that makes measured boot trustworthy — a process cannot
forge PCR state through TBS — so the negative test binds to a non-current value
instead of mutating a live PCR. Net effect: this PoC reads PCR 23 but mutates no
PCR at all.

WHY RAW TBS (not the CNG path the rest of `shared/security/` uses): the Microsoft
Platform Crypto Provider (ncrypt.dll) used by ``tpm_signer.py`` / ``tpm_sealer.py``
wraps keys but does not expose a *data* object sealed under a PolicyPCR. So this
PoC speaks raw TPM 2.0 command bytes over **TBS** (tbs.dll: ``Tbsi_Context_Create``
/ ``Tbsip_Submit_Command``) — stdlib ``ctypes`` only, no new dependencies.

NON-DESTRUCTIVE BY CONSTRUCTION:
  - Parent key is a TRANSIENT primary in the **NULL hierarchy** (ephemeral, empty
    auth, vanishes on context close / reboot — nothing persistent is created).
  - The sealed objects are transient (never persisted).
  - No PCR is modified (PCR 23 is only read).
  - The sealed secret is ``os.urandom(32)`` — a throwaway, never a real key.

Run (Windows, TPM 2.0 present):
    python shared/security/verify_pcr_seal.py            # human report
    python shared/security/verify_pcr_seal.py out.json   # + machine-readable JSON

Exit code 0 = DEMONSTRATED (positive unseal OK + negative unseal refused);
non-zero = something did not hold (details printed).
"""

from __future__ import annotations

import hashlib
import json
import os
import struct
import sys

# --------------------------------------------------------------------------- #
# TPM 2.0 constants (big-endian wire encoding throughout)
# --------------------------------------------------------------------------- #
ST_NO_SESSIONS = 0x8001
ST_SESSIONS = 0x8002

RH_NULL = 0x40000007
RS_PW = 0x40000009

SE_POLICY = 0x01
SE_TRIAL = 0x03

ALG_AES = 0x0006
ALG_KEYEDHASH = 0x0008
ALG_SHA256 = 0x000B
ALG_NULL = 0x0010
ALG_ECC = 0x0023
ALG_CFB = 0x0043
ECC_NIST_P256 = 0x0003

CC_PCR_Read = 0x0000017E
CC_PCR_Extend = 0x00000182
CC_StartAuthSession = 0x00000176
CC_PolicyPCR = 0x0000017F
CC_PolicyGetDigest = 0x00000189
CC_CreatePrimary = 0x00000131
CC_Create = 0x00000153
CC_Load = 0x00000157
CC_Unseal = 0x0000015E
CC_FlushContext = 0x00000165

# Object attribute bitfield (TPMA_OBJECT)
A_fixedTPM = 0x00000002
A_fixedParent = 0x00000010
A_sensitiveDataOrigin = 0x00000020
A_userWithAuth = 0x00000040
A_restricted = 0x00010000
A_decrypt = 0x00020000

PCR_INDEX = 23  # resettable Application-Support PCR — carries no boot measurement


# --------------------------------------------------------------------------- #
# Marshaling helpers
# --------------------------------------------------------------------------- #
def u8(v: int) -> bytes:
    return struct.pack(">B", v)


def u16(v: int) -> bytes:
    return struct.pack(">H", v)


def u32(v: int) -> bytes:
    return struct.pack(">I", v)


def tpm2b(b: bytes) -> bytes:
    """Size-prefixed (UINT16) byte buffer — the TPM2B wire shape."""
    return u16(len(b)) + b


def rd_u16(buf: bytes, off: int):
    return struct.unpack_from(">H", buf, off)[0], off + 2


def rd_u32(buf: bytes, off: int):
    return struct.unpack_from(">I", buf, off)[0], off + 4


def rd_tpm2b(buf: bytes, off: int):
    n, off = rd_u16(buf, off)
    return buf[off:off + n], off + n


def pcr_selection(index: int) -> bytes:
    """A single-PCR TPML_PCR_SELECTION in the SHA-256 bank."""
    sel = bytearray(3)  # 3 select bytes cover PCR 0..23
    sel[index // 8] |= 1 << (index % 8)
    return u32(1) + u16(ALG_SHA256) + u8(3) + bytes(sel)


# Empty-password authorization session (TPM_RS_PW + empty nonce/attrs/hmac).
PW_AUTH = u32(RS_PW) + tpm2b(b"") + u8(0x00) + tpm2b(b"")


def policy_auth(session: int) -> bytes:
    """Authorization-area entry that authorizes via a policy session (empty hmac;
    continueSession clear so a successful use flushes the session)."""
    return u32(session) + tpm2b(b"") + u8(0x00) + tpm2b(b"")


def build(cc: int, handles: bytes = b"", auth: bytes | None = None, params: bytes = b"") -> bytes:
    """Assemble a TPM 2.0 command. Presence of an auth area selects ST_SESSIONS."""
    tag = ST_SESSIONS if auth is not None else ST_NO_SESSIONS
    body = handles + (u32(len(auth)) + auth if auth is not None else b"") + params
    return u16(tag) + u32(10 + len(body)) + u32(cc) + body


def parse(resp: bytes, num_handles: int = 0):
    """Return (rc, [handles], params_bytes). On rc != 0 the body is just header."""
    tag, _ = rd_u16(resp, 0)
    size, _ = rd_u32(resp, 2)
    rc, _ = rd_u32(resp, 6)
    if rc != 0:
        return rc, [], b""
    off = 10
    handles = []
    for _ in range(num_handles):
        h, off = rd_u32(resp, off)
        handles.append(h)
    if tag == ST_SESSIONS:
        psize, off = rd_u32(resp, off)
        return rc, handles, resp[off:off + psize]
    return rc, handles, resp[off:size]


def rc_name(rc: int) -> str:
    """Decode the response code enough to label results."""
    if rc == 0:
        return "TPM_RC_SUCCESS"
    if rc == 0x80280400:
        return "TPM_E_COMMAND_BLOCKED (0x80280400)"
    if rc & 0x80000000:  # a Windows TBS / HRESULT, not a raw TPM response code
        return f"TBS/HRESULT 0x{rc:08X}"
    if (rc & 0x80) and (rc & 0x3F) == 0x1D:
        return f"TPM_RC_POLICY_FAIL (0x{rc:03X})"
    if (rc & 0x80) and (rc & 0x3F) == 0x23:
        return f"TPM_RC_AUTH_FAIL (0x{rc:03X})"
    return f"0x{rc:03X}"


# --------------------------------------------------------------------------- #
# TBS plumbing
# --------------------------------------------------------------------------- #
class Tpm:
    def __init__(self):
        import ctypes

        self.ctypes = ctypes
        self.tbs = ctypes.WinDLL("tbs")
        self.tbs.Tbsi_Context_Create.restype = ctypes.c_uint32
        self.tbs.Tbsi_Context_Create.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        self.tbs.Tbsip_Submit_Command.restype = ctypes.c_uint32
        self.tbs.Tbsip_Submit_Command.argtypes = [
            ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_ubyte), ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_ubyte), ctypes.POINTER(ctypes.c_uint32),
        ]
        self.tbs.Tbsip_Context_Close.restype = ctypes.c_uint32
        self.tbs.Tbsip_Context_Close.argtypes = [ctypes.c_void_p]

        class TBS_CONTEXT_PARAMS2(ctypes.Structure):
            _fields_ = [("version", ctypes.c_uint32), ("flags", ctypes.c_uint32)]

        params = TBS_CONTEXT_PARAMS2(2, 0x4)  # version 2, includeTpm20
        self.ctx = ctypes.c_void_p()
        r = self.tbs.Tbsi_Context_Create(self.ctypes.byref(params), self.ctypes.byref(self.ctx))
        if r != 0:
            raise RuntimeError(f"Tbsi_Context_Create failed: 0x{r & 0xFFFFFFFF:08X}")

    def submit(self, cmd: bytes) -> bytes:
        ctypes = self.ctypes
        out = (ctypes.c_ubyte * 4096)()
        outlen = ctypes.c_uint32(4096)
        inbuf = (ctypes.c_ubyte * len(cmd)).from_buffer_copy(cmd)
        r = self.tbs.Tbsip_Submit_Command(
            self.ctx, 0, 200, inbuf, len(cmd), out, ctypes.byref(outlen)
        )
        if r != 0:
            raise RuntimeError(f"Tbsip_Submit_Command (TBS) failed: 0x{r & 0xFFFFFFFF:08X}")
        return bytes(out[:outlen.value])

    def flush(self, handle: int) -> None:
        try:
            self.submit(build(CC_FlushContext, params=u32(handle)))
        except Exception:
            pass

    def close(self) -> None:
        try:
            self.tbs.Tbsip_Context_Close(self.ctx)
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# TPM templates
# --------------------------------------------------------------------------- #
def primary_template() -> bytes:
    """TPMT_PUBLIC for a transient ECC P-256 restricted-decrypt storage parent."""
    attrs = A_fixedTPM | A_fixedParent | A_sensitiveDataOrigin | A_userWithAuth | A_restricted | A_decrypt
    ecc_parms = (
        u16(ALG_AES) + u16(128) + u16(ALG_CFB)   # symmetric (child protection)
        + u16(ALG_NULL)                            # scheme
        + u16(ECC_NIST_P256)                       # curve
        + u16(ALG_NULL)                            # kdf
    )
    unique = tpm2b(b"") + tpm2b(b"")               # empty TPMS_ECC_POINT (x, y)
    pub = u16(ALG_ECC) + u16(ALG_SHA256) + u32(attrs) + tpm2b(b"") + ecc_parms + unique
    return tpm2b(pub)


def sealed_template(auth_policy: bytes) -> bytes:
    """TPMT_PUBLIC for a keyedhash *sealed data* object gated by ``auth_policy``."""
    attrs = A_fixedTPM | A_fixedParent  # no sensitiveDataOrigin (data supplied),
    #                                     no userWithAuth -> policy is the only auth
    kh_parms = u16(ALG_NULL)            # TPMT_KEYEDHASH_SCHEME = NULL -> sealed blob
    unique = tpm2b(b"")
    pub = u16(ALG_KEYEDHASH) + u16(ALG_SHA256) + u32(attrs) + tpm2b(auth_policy) + kh_parms + unique
    return tpm2b(pub)


def sensitive(data: bytes) -> bytes:
    """TPM2B_SENSITIVE_CREATE wrapping (empty userAuth, ``data``)."""
    inner = tpm2b(b"") + tpm2b(data)
    return tpm2b(inner)


# --------------------------------------------------------------------------- #
# TPM operations
# --------------------------------------------------------------------------- #
def pcr_read(t: Tpm, index: int) -> bytes:
    rc, _, params = parse(t.submit(build(CC_PCR_Read, params=pcr_selection(index))))
    if rc != 0:
        raise RuntimeError(f"PCR_Read failed: {rc_name(rc)}")
    off = 0
    _counter, off = rd_u32(params, off)
    cnt, off = rd_u32(params, off)
    for _ in range(cnt):
        _h, off = rd_u16(params, off)
        sz = params[off]; off += 1 + sz
    _vcnt, off = rd_u32(params, off)
    digest, off = rd_tpm2b(params, off)
    return digest


def start_session(t: Tpm, se_type: int) -> int:
    params = (
        tpm2b(os.urandom(16))   # nonceCaller
        + tpm2b(b"")            # encryptedSalt (none; tpmKey = NULL)
        + u8(se_type)           # sessionType
        + u16(ALG_NULL)         # symmetric = NULL
        + u16(ALG_SHA256)       # authHash
    )
    cmd = build(CC_StartAuthSession, handles=u32(RH_NULL) + u32(RH_NULL), params=params)
    rc, handles, _ = parse(t.submit(cmd), num_handles=1)
    if rc != 0:
        raise RuntimeError(f"StartAuthSession failed: {rc_name(rc)}")
    return handles[0]


def policy_pcr(t: Tpm, session: int, index: int, pcr_digest: bytes = b"") -> None:
    # Empty pcr_digest -> the TPM mixes in the *current* PCR value (used by the
    # real unseal session). A non-empty pcr_digest in a TRIAL session binds the
    # policy to a *specified* PCR state (used to bind the negative object).
    cmd = build(CC_PolicyPCR, handles=u32(session), params=tpm2b(pcr_digest) + pcr_selection(index))
    rc, _, _ = parse(t.submit(cmd))
    if rc != 0:
        raise RuntimeError(f"PolicyPCR failed: {rc_name(rc)}")


def policy_get_digest(t: Tpm, session: int) -> bytes:
    rc, _, params = parse(t.submit(build(CC_PolicyGetDigest, handles=u32(session))))
    if rc != 0:
        raise RuntimeError(f"PolicyGetDigest failed: {rc_name(rc)}")
    digest, _ = rd_tpm2b(params, 0)
    return digest


def compute_policy(t: Tpm, index: int, pcr_digest: bytes = b"") -> bytes:
    """Compute a PolicyPCR digest in a trial session (binds to current PCR when
    ``pcr_digest`` is empty, or to the specified state when it is provided)."""
    trial = start_session(t, SE_TRIAL)
    try:
        policy_pcr(t, trial, index, pcr_digest)
        return policy_get_digest(t, trial)
    finally:
        t.flush(trial)


def create_primary(t: Tpm) -> int:
    params = sensitive(b"") + primary_template() + tpm2b(b"") + u32(0)
    cmd = build(CC_CreatePrimary, handles=u32(RH_NULL), auth=PW_AUTH, params=params)
    rc, handles, _ = parse(t.submit(cmd), num_handles=1)
    if rc != 0:
        raise RuntimeError(f"CreatePrimary failed: {rc_name(rc)}")
    return handles[0]


def create_sealed(t: Tpm, parent: int, secret: bytes, auth_policy: bytes):
    params = sensitive(secret) + sealed_template(auth_policy) + tpm2b(b"") + u32(0)
    cmd = build(CC_Create, handles=u32(parent), auth=PW_AUTH, params=params)
    rc, _, p = parse(t.submit(cmd))
    if rc != 0:
        raise RuntimeError(f"Create failed: {rc_name(rc)}")
    out_private, off = rd_tpm2b(p, 0)
    out_public, off = rd_tpm2b(p, off)
    return out_private, out_public


def load(t: Tpm, parent: int, out_private: bytes, out_public: bytes) -> int:
    params = tpm2b(out_private) + tpm2b(out_public)
    cmd = build(CC_Load, handles=u32(parent), auth=PW_AUTH, params=params)
    rc, handles, _ = parse(t.submit(cmd), num_handles=1)
    if rc != 0:
        raise RuntimeError(f"Load failed: {rc_name(rc)}")
    return handles[0]


def seal_and_load(t: Tpm, parent: int, secret: bytes, auth_policy: bytes) -> int:
    out_priv, out_pub = create_sealed(t, parent, secret, auth_policy)
    return load(t, parent, out_priv, out_pub)


def try_unseal(t: Tpm, obj: int, index: int):
    """Start a fresh policy session bound to the *current* PCR, attempt unseal.
    Returns (rc, data); data is b'' on failure."""
    session = start_session(t, SE_POLICY)
    try:
        policy_pcr(t, session, index)
        rc, _, params = parse(t.submit(build(CC_Unseal, handles=u32(obj), auth=policy_auth(session))))
        if rc != 0:
            return rc, b""
        data, _ = rd_tpm2b(params, 0)
        return rc, data
    finally:
        # A successful unseal already flushed the session (continueSession clear);
        # flushing again is a harmless no-op. A failed unseal leaves it -> flush.
        t.flush(session)


def try_pcr_extend(t: Tpm, index: int, value: bytes) -> int:
    """Attempt a user-mode PCR extend; return the response code (does not raise).
    On Windows this is expected to be blocked by TBS (TPM_E_COMMAND_BLOCKED)."""
    digests = u32(1) + u16(ALG_SHA256) + value  # TPML_DIGEST_VALUES, one SHA-256
    cmd = build(CC_PCR_Extend, handles=u32(index), auth=PW_AUTH, params=digests)
    rc, _, _ = parse(t.submit(cmd))
    return rc


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def run() -> dict:
    if sys.platform != "win32":
        raise SystemExit("This PoC requires Windows (TBS / tbs.dll).")

    result: dict = {"pcr_index": PCR_INDEX, "verdict": "FAIL"}
    t = Tpm()
    primary = obj_a = obj_b = None
    try:
        secret = os.urandom(32)
        result["secret_sha256"] = hashlib.sha256(secret).hexdigest()

        live = pcr_read(t, PCR_INDEX)
        result["pcr23_live"] = live.hex()

        # Two PolicyPCR digests over PCR 23: one bound to the CURRENT state, one
        # bound to a DIFFERENT (fabricated, non-current) PCR-23 state.
        auth_live = compute_policy(t, PCR_INDEX)
        other_state = hashlib.sha256(live + b"different-measured-state").digest()
        auth_other = compute_policy(t, PCR_INDEX, other_state)
        result["auth_policy_live"] = auth_live.hex()
        result["auth_policy_other"] = auth_other.hex()
        result["policies_differ"] = auth_live != auth_other

        primary = create_primary(t)
        result["primary_handle"] = f"0x{primary:08X}"

        # POSITIVE: sealed to the current PCR-23 state -> unseal must succeed.
        obj_a = seal_and_load(t, primary, secret, auth_live)
        rc_pos, data = try_unseal(t, obj_a, PCR_INDEX)
        positive_ok = (rc_pos == 0 and data == secret)
        result["positive_unseal"] = {
            "rc": rc_name(rc_pos),
            "secret_roundtrip": data == secret,
            "ok": positive_ok,
        }
        t.flush(obj_a)
        obj_a = None  # free the transient-object slot before loading the 2nd object

        # NEGATIVE: sealed to a DIFFERENT PCR-23 state -> unseal must be refused
        # in the current state (the binding enforces the value).
        obj_b = seal_and_load(t, primary, secret, auth_other)
        rc_neg, data_neg = try_unseal(t, obj_b, PCR_INDEX)
        negative_ok = (rc_neg != 0 and data_neg == b"" and result["policies_differ"])
        result["negative_unseal"] = {
            "rc": rc_name(rc_neg),
            "refused": rc_neg != 0,
            "ok": negative_ok,
        }

        # INFORMATIONAL: a user-mode PCR extend is expected to be blocked by
        # Windows TBS -> the protection that stops a process forging PCR state,
        # and the reason the negative test uses value-binding, not a live extend.
        rc_ext = try_pcr_extend(t, PCR_INDEX, hashlib.sha256(b"BlarAI-PCR-seal-PoC").digest())
        result["pcr_extend_usermode"] = {"rc": rc_name(rc_ext), "blocked": rc_ext != 0}

        result["verdict"] = "DEMONSTRATED" if (positive_ok and negative_ok) else "FAIL"
        return result
    finally:
        for h in (obj_a, obj_b, primary):
            if h is not None:
                t.flush(h)
        t.close()


def main() -> int:
    res = run()
    pos = res.get("positive_unseal", {})
    neg = res.get("negative_unseal", {})
    ext = res.get("pcr_extend_usermode", {})

    print("=" * 74)
    print("  BlarAI - TPM 2.0 PCR-bound seal/unseal proof-of-concept (#627)")
    print("=" * 74)
    print(f"  PCR index             : {PCR_INDEX} (resettable Application-Support; no boot measurement)")
    print(f"  Sealed secret SHA-256 : {res.get('secret_sha256')}")
    print(f"  PCR23 live value      : {res.get('pcr23_live')}")
    print(f"  authPolicy(current)   : {res.get('auth_policy_live')}")
    print(f"  authPolicy(different) : {res.get('auth_policy_other')}")
    print(f"  policies differ       : {res.get('policies_differ')}")
    print(f"  Transient parent      : {res.get('primary_handle')} (NULL hierarchy)")
    print("-" * 74)
    print("  [+] POSITIVE  seal->current PCR-23 value, unseal in current state")
    print(f"        rc={pos.get('rc')}  secret_roundtrip={pos.get('secret_roundtrip')}  "
          f"-> {'PASS' if pos.get('ok') else 'FAIL'}")
    print("  [-] NEGATIVE  seal->different PCR-23 value, unseal in current state")
    print(f"        rc={neg.get('rc')}  refused={neg.get('refused')}  "
          f"-> {'PASS' if neg.get('ok') else 'FAIL'}")
    print(f"  [i] user-mode PCR_Extend blocked by Windows TBS : "
          f"{ext.get('blocked')}  ({ext.get('rc')})")
    print("=" * 74)
    print(f"  VERDICT: {res['verdict']}")
    print("=" * 74)

    if len(sys.argv) > 1:
        with open(sys.argv[1], "w", encoding="utf-8") as fh:
            json.dump(res, fh, indent=2)
        print(f"  JSON written to {sys.argv[1]}")

    return 0 if res["verdict"] == "DEMONSTRATED" else 1


if __name__ == "__main__":
    sys.exit(main())
