# SPDX-License-Identifier: AGPL-3.0-or-later
"""A seccomp-BPF syscall filter for the Linux sandbox (defence in depth).

Namespaces and mounts already contain a sandboxed process; seccomp shrinks the
*kernel* attack surface underneath them. Most sandbox escapes in the wild are
kernel bugs reached through rarely-used syscalls, so Aegis installs a
**blocklist** (not an allowlist - allowlists break normal programs) of syscalls
that honest build/test/agent workloads never need but exploits and escape
primitives do: `ptrace`, `bpf`, `perf_event_open`, `userfaultfd`, the keyring,
module loading, `kexec`, `process_vm_*`, `mount`, `pivot_root`, `reboot`, raw
I/O ports, and so on. Blocked calls return EPERM (recoverable), never a crash.

Pure Python, no libseccomp: we emit the classic-BPF program bwrap's `--seccomp`
expects. Only architectures whose syscall numbers we pin here are filtered;
anywhere else the filter is simply skipped (the other layers still apply).
Disable with AEGIS_SECCOMP=0.
"""

from __future__ import annotations

import os
import platform
import struct

# struct seccomp_data: nr(u32)@0, arch(u32)@4, ip(u64)@8, args[6]@16
_NR, _ARCH = 0, 4

# BPF opcodes
_LD_W_ABS = 0x20          # BPF_LD | BPF_W | BPF_ABS
_JEQ_K = 0x15             # BPF_JMP | BPF_JEQ | BPF_K
_RET_K = 0x06             # BPF_RET | BPF_K

# seccomp return actions
_ALLOW = 0x7FFF0000       # SECCOMP_RET_ALLOW
_ERRNO_EPERM = 0x00050001  # SECCOMP_RET_ERRNO | EPERM

_AUDIT = {"x86_64": 0xC000003E, "aarch64": 0xC00000B7}

# Syscalls blocked everywhere they exist on the arch. {name: {arch: nr}}
_BLOCK = {
    "ptrace": {"x86_64": 101, "aarch64": 117},
    "process_vm_readv": {"x86_64": 310, "aarch64": 270},
    "process_vm_writev": {"x86_64": 311, "aarch64": 271},
    "kcmp": {"x86_64": 312, "aarch64": 272},
    "bpf": {"x86_64": 321, "aarch64": 280},
    "perf_event_open": {"x86_64": 298, "aarch64": 241},
    "userfaultfd": {"x86_64": 323, "aarch64": 282},
    "keyctl": {"x86_64": 250, "aarch64": 219},
    "add_key": {"x86_64": 248, "aarch64": 217},
    "request_key": {"x86_64": 249, "aarch64": 218},
    "kexec_load": {"x86_64": 246, "aarch64": 104},
    "kexec_file_load": {"x86_64": 320, "aarch64": 294},
    "init_module": {"x86_64": 175, "aarch64": 105},
    "finit_module": {"x86_64": 313, "aarch64": 273},
    "delete_module": {"x86_64": 176, "aarch64": 106},
    "open_by_handle_at": {"x86_64": 304, "aarch64": 265},
    "pivot_root": {"x86_64": 155, "aarch64": 41},
    "mount": {"x86_64": 165, "aarch64": 40},
    "umount2": {"x86_64": 166, "aarch64": 39},
    "swapon": {"x86_64": 167, "aarch64": 224},
    "swapoff": {"x86_64": 168, "aarch64": 225},
    "reboot": {"x86_64": 169, "aarch64": 142},
    "acct": {"x86_64": 163, "aarch64": 89},
    "quotactl": {"x86_64": 179, "aarch64": 60},
    "_sysctl": {"x86_64": 156},
    "iopl": {"x86_64": 172},
    "ioperm": {"x86_64": 173},
}


def arch() -> str | None:
    m = platform.machine().lower()
    if m in ("x86_64", "amd64"):
        return "x86_64"
    if m in ("aarch64", "arm64"):
        return "aarch64"
    return None


def blocked_numbers(a: str | None = None) -> list[int]:
    a = a or arch()
    if not a:
        return []
    return sorted({tbl[a] for tbl in _BLOCK.values() if a in tbl})


def supported() -> bool:
    return os.name == "posix" and arch() is not None and os.environ.get("AEGIS_SECCOMP") != "0"


def _stmt(code: int, k: int) -> bytes:
    return struct.pack("HBBI", code, 0, 0, k)


def _jeq(k: int, jt: int, jf: int) -> bytes:
    return struct.pack("HBBI", _JEQ_K, jt, jf, k)


def build_filter(a: str | None = None) -> bytes | None:
    """The raw sock_filter program for bwrap --seccomp, or None if this arch is not pinned."""
    a = a or arch()
    if a is None or a not in _AUDIT:
        return None
    nrs = blocked_numbers(a)
    n = len(nrs)
    # Layout (indices): 0 LD arch | 1 JEQ native? | 2 LD nr | 3..3+n-1 JEQ nr_i
    #                   3+n RET ALLOW | 3+n+1 RET EPERM
    allow_idx, deny_idx = 3 + n, 3 + n + 1
    prog = [
        _stmt(_LD_W_ABS, _ARCH),
        _jeq(_AUDIT[a], 0, allow_idx - 2),   # not our arch -> allow (don't break compat binaries)
        _stmt(_LD_W_ABS, _NR),
    ]
    for i, nr in enumerate(nrs):
        here = 3 + i
        prog.append(_jeq(nr, deny_idx - (here + 1), 0))  # match -> EPERM, else next
    prog.append(_stmt(_RET_K, _ALLOW))
    prog.append(_stmt(_RET_K, _ERRNO_EPERM))
    return b"".join(prog)
