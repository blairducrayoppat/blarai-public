"""On-chip Intel Key Locker capability probe (CPUID) - BlarAI #611.

Resolves the single open hardware question from the #611 live-memory feasibility
study (docs/handoffs/611-live-memory-feasibility.md, §5 item 1): does this CPU
expose Intel Key Locker (AESKLE)? Public sources confirm Key Locker on Tiger Lake
-> Raptor Lake but say nothing about Lunar Lake (Core Ultra 200V), so this reads
the silicon directly.

Detection (Intel Key Locker Specification 343965):
  - Key Locker present : CPUID.(EAX=07H, ECX=0).ECX[23]  (the "KL" bit)
  - If present, leaf 0x19 enumerates the sub-features:
      EBX[0] = AESKLE (AES Key Locker instructions)
      EBX[2] = WIDE_KL (wide Key Locker instructions)
      EBX[4] = backup of IWKEY supported

Pure-Python, no compiler / no install: a tiny machine-code CPUID shim is written
into executable memory and called via ctypes. Windows x64 only (matches BlarAI's
target). Read-only - CPUID changes no machine state. Self-validating: it first
confirms the vendor string is "GenuineIntel" and the AES-NI bit is set, so a
broken shim is caught before the Key Locker bit is trusted.

Run:  .venv/Scripts/python.exe scripts/probe_keylocker.py

Measured result (2026-06-09, Intel Core Ultra 7 258V / Lunar Lake, Windows 11):
  vendor=GenuineIntel  max_basic_leaf=0x23  leaf1.ECX=0xfffaf38b (AES-NI=1, sane)
  leaf7.0 ECX=0x184007a4  ->  Key Locker CPUID.(7,0).ECX[23] = 0  ->  NOT EXPOSED.
  Conclusion: Intel Key Locker is absent on this silicon; #611 mitigation 1
  (Key Locker) is permanently moot here (not merely deferred). Novel data point:
  no public source confirmed Key Locker exposure for Lunar Lake / Core Ultra 200V.
"""

from __future__ import annotations

import ctypes
import sys

# Windows x64 CPUID shim: void cpuid(uint32 leaf /*rcx*/, uint32 subleaf /*rdx*/,
# uint32* out /*r8 -> [eax,ebx,ecx,edx]*/). rbx is callee-saved on Win64 and is
# clobbered by CPUID, so it is preserved.
_SHIM = bytes(
    [
        0x53,                    # push rbx
        0x89, 0xC8,              # mov  eax, ecx        ; leaf
        0x89, 0xD1,              # mov  ecx, edx        ; subleaf
        0x0F, 0xA2,              # cpuid
        0x41, 0x89, 0x00,        # mov  [r8],    eax
        0x41, 0x89, 0x58, 0x04,  # mov  [r8+4],  ebx
        0x41, 0x89, 0x48, 0x08,  # mov  [r8+8],  ecx
        0x41, 0x89, 0x50, 0x0C,  # mov  [r8+12], edx
        0x5B,                    # pop  rbx
        0xC3,                    # ret
    ]
)

_MEM_COMMIT_RESERVE = 0x3000
_PAGE_EXECUTE_READWRITE = 0x40


def _make_cpuid():
    k32 = ctypes.windll.kernel32
    k32.VirtualAlloc.restype = ctypes.c_void_p
    k32.VirtualAlloc.argtypes = [
        ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_uint32,
    ]
    addr = k32.VirtualAlloc(
        None, len(_SHIM), _MEM_COMMIT_RESERVE, _PAGE_EXECUTE_READWRITE,
    )
    if not addr:
        raise OSError("VirtualAlloc failed for the CPUID shim")
    ctypes.memmove(addr, _SHIM, len(_SHIM))
    proto = ctypes.CFUNCTYPE(
        None, ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32),
    )
    return proto(addr)


def main() -> int:
    if sys.platform != "win32":
        print("This probe is Windows x64 only.")
        return 2

    cpuid = _make_cpuid()

    def regs(leaf: int, subleaf: int = 0):
        out = (ctypes.c_uint32 * 4)()
        cpuid(leaf, subleaf, out)
        return out[0], out[1], out[2], out[3]  # eax, ebx, ecx, edx

    eax0, ebx0, ecx0, edx0 = regs(0)
    max_leaf = eax0
    vendor = (
        ebx0.to_bytes(4, "little")
        + edx0.to_bytes(4, "little")
        + ecx0.to_bytes(4, "little")
    ).decode("ascii", "replace")

    _, _, ecx1, _ = regs(1)
    aes_ni = (ecx1 >> 25) & 1  # leaf 1 ECX[25] - sanity check (Intel: should be 1)

    print(f"vendor              : {vendor!r}")
    print(f"max basic leaf      : 0x{max_leaf:x}")
    print(f"leaf 1  ECX         : 0x{ecx1:08x}   AES-NI(ECX[25]) = {aes_ni}")

    if vendor != "GenuineIntel" or aes_ni != 1:
        print(
            "\nSANITY CHECK FAILED - vendor/AES-NI unexpected; the CPUID shim is "
            "not returning trustworthy values. Do NOT trust the Key Locker bit."
        )
        return 3

    a7, b7, c7, d7 = regs(7, 0)
    kl = (c7 >> 23) & 1
    print(
        f"leaf 7.0            : eax=0x{a7:08x} ebx=0x{b7:08x} "
        f"ecx=0x{c7:08x} edx=0x{d7:08x}"
    )
    print(f"KEY LOCKER (KL)     : CPUID.(7,0).ECX[23] = {kl}")

    if not kl:
        print(
            "\nVERDICT: Key Locker is NOT exposed on this silicon (KL bit = 0).\n"
            "         The Key Locker mitigation (#611 mitigation 1) is permanently\n"
            "         moot on this CPU - close that limb."
        )
        return 0

    if max_leaf < 0x19:
        print(
            "\nVERDICT: KL bit set but leaf 0x19 is unavailable - inconclusive "
            "sub-feature enumeration."
        )
        return 0

    a19, b19, c19, _ = regs(0x19, 0)
    aeskle = (b19 >> 0) & 1
    wide_kl = (b19 >> 2) & 1
    iwkey_backup = (b19 >> 4) & 1
    print(f"leaf 0x19.0         : eax=0x{a19:08x} ebx=0x{b19:08x} ecx=0x{c19:08x}")
    print(
        f"  AESKLE(EBX[0])={aeskle}  WIDE_KL(EBX[2])={wide_kl}  "
        f"IWKEY_BACKUP(EBX[4])={iwkey_backup}"
    )
    if aeskle:
        print(
            "\nVERDICT: Key Locker IS exposed (KL + AESKLE present). The hardware\n"
            "         limb is open - but see the feasibility study: it is still\n"
            "         blocked in pure Python (statically-linked OpenSSL does not\n"
            "         route to Key Locker on Windows) and protects only the key,\n"
            "         not the decrypted embeddings. So: not moot, but still low-\n"
            "         feasibility for BlarAI's stack without native code."
        )
    else:
        print(
            "\nVERDICT: KL bit set but AESKLE absent - the AES Key Locker "
            "instructions are not exposed; mitigation 1 remains moot for AES."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
