"""Windows backend: AppContainer.

An AppContainer process starts with access to almost nothing in the user
profile: only objects whose ACL names the container's SID (or "ALL
APPLICATION PACKAGES") are reachable. Aegis therefore:

1. creates a per-run AppContainer profile (and SID),
2. adds ACEs for that SID on granted paths (read or modify) and explicit
   deny ACEs where a deny rule sits inside a granted path,
3. starts the agent with SECURITY_CAPABILITIES inside a Job object (so all
   child processes stay in the container and die with the session),
4. removes the ACEs and the profile afterwards.

Network: offline = no capabilities; "all" = internetClient + privateNetwork;
allowlist = no internet capability and a loopback exemption so the process
can reach only Aegis's proxy. Adding an exemption needs elevation, so a
non-elevated Aegis uses one shared container prepared once with
`aegis windows-setup`; without it Aegis refuses rather than widening access.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
import uuid
from ctypes import wintypes
from pathlib import Path

from aegis_jail.sandbox.base import Backend, RunResult, SandboxSpec, SandboxUnavailable, proxy_env

if sys.platform == "win32":  # pragma: no cover - exercised on Windows CI
    import msvcrt

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    userenv = ctypes.WinDLL("userenv")

    LPVOID = ctypes.c_void_p
    PSID = ctypes.c_void_p

    class SID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Sid", PSID), ("Attributes", wintypes.DWORD)]

    class SECURITY_CAPABILITIES(ctypes.Structure):
        _fields_ = [("AppContainerSid", PSID), ("Capabilities", ctypes.POINTER(SID_AND_ATTRIBUTES)),
                    ("CapabilityCount", wintypes.DWORD), ("Reserved", wintypes.DWORD)]

    class STARTUPINFOW(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR), ("lpDesktop", wintypes.LPWSTR),
                    ("lpTitle", wintypes.LPWSTR), ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
                    ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD), ("dwXCountChars", wintypes.DWORD),
                    ("dwYCountChars", wintypes.DWORD), ("dwFillAttribute", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
                    ("lpReserved2", LPVOID), ("hStdInput", wintypes.HANDLE), ("hStdOutput", wintypes.HANDLE),
                    ("hStdError", wintypes.HANDLE)]

    class STARTUPINFOEXW(ctypes.Structure):
        _fields_ = [("StartupInfo", STARTUPINFOW), ("lpAttributeList", LPVOID)]

    class PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                    ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD)]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in ("Read", "Write", "Other", "ReadT", "WriteT", "OtherT")]

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION), ("IoInfo", IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    userenv.CreateAppContainerProfile.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                                  ctypes.POINTER(SID_AND_ATTRIBUTES), wintypes.DWORD,
                                                  ctypes.POINTER(PSID)]
    userenv.CreateAppContainerProfile.restype = ctypes.c_long
    userenv.DeriveAppContainerSidFromAppContainerName.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(PSID)]
    userenv.DeriveAppContainerSidFromAppContainerName.restype = ctypes.c_long
    userenv.DeleteAppContainerProfile.argtypes = [wintypes.LPCWSTR]
    userenv.DeleteAppContainerProfile.restype = ctypes.c_long
    advapi32.ConvertSidToStringSidW.argtypes = [PSID, ctypes.POINTER(wintypes.LPWSTR)]
    advapi32.ConvertStringSidToSidW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(PSID)]
    kernel32.InitializeProcThreadAttributeList.argtypes = [LPVOID, wintypes.DWORD, wintypes.DWORD,
                                                           ctypes.POINTER(ctypes.c_size_t)]
    kernel32.UpdateProcThreadAttribute.argtypes = [LPVOID, wintypes.DWORD, ctypes.c_size_t, LPVOID,
                                                   ctypes.c_size_t, LPVOID, LPVOID]
    kernel32.DeleteProcThreadAttributeList.argtypes = [LPVOID]
    kernel32.CreateProcessW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, LPVOID, LPVOID, wintypes.BOOL,
                                        wintypes.DWORD, LPVOID, wintypes.LPCWSTR,
                                        ctypes.POINTER(STARTUPINFOEXW), ctypes.POINTER(PROCESS_INFORMATION)]
    kernel32.CreateJobObjectW.argtypes = [LPVOID, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, LPVOID, wintypes.DWORD]
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
    kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.LocalFree.argtypes = [LPVOID]
    advapi32.FreeSid.argtypes = [PSID]

PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x00020002
PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009
EXTENDED_STARTUPINFO_PRESENT = 0x00080000
CREATE_SUSPENDED = 0x00000004
CREATE_UNICODE_ENVIRONMENT = 0x00000400
CREATE_NO_WINDOW = 0x08000000
STARTF_USESTDHANDLES = 0x00000100
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JobObjectExtendedLimitInformation = 9
WAIT_TIMEOUT = 0x102
HRESULT_ALREADY_EXISTS = ctypes.c_long(0x800700B7).value

CAP_INTERNET_CLIENT = "S-1-15-3-1"
CAP_INTERNET_CLIENT_SERVER = "S-1-15-3-2"
CAP_PRIVATE_NETWORK = "S-1-15-3-3"


def _sid_to_str(sid) -> str:
    out = wintypes.LPWSTR()
    if not advapi32.ConvertSidToStringSidW(sid, ctypes.byref(out)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return out.value or ""
    finally:
        kernel32.LocalFree(out)


def _str_to_sid(s: str):
    sid = PSID()
    if not advapi32.ConvertStringSidToSidW(s, ctypes.byref(sid)):
        raise ctypes.WinError(ctypes.get_last_error())
    return sid


def _icacls(*args: str) -> None:
    r = subprocess.run(["icacls", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"icacls {' '.join(args)} failed: {r.stdout.strip()} {r.stderr.strip()}")


class AppContainerBackend(Backend):
    name = "windows-appcontainer"

    def check(self) -> None:
        if sys.platform != "win32":
            raise SandboxUnavailable("not Windows")
        if sys.getwindowsversion().build < 9200:
            raise SandboxUnavailable("AppContainer needs Windows 8 / Server 2012 or newer")

    # -- ACL management --------------------------------------------------
    @staticmethod
    def plan_acls(rules: list[tuple[str, Path]]) -> list[tuple[Path, str, bool]]:
        """Turn last-match-wins rules into allow-only ACEs: (path, "RX"|"M", inheritable).

        AppContainers start with no access, so Aegis never needs deny ACEs:
        a grant that contains a denied sub-path is "carved" - the directory
        itself is made listable and each child is granted separately, except
        the denied one. (Deny ACEs for package SIDs proved unreliable.)
        """
        out: list[tuple[Path, str, bool]] = []
        for i, (action, a) in enumerate(rules):
            if action not in ("read", "write") or not a.exists():
                continue
            later_denies = [d for act, d in rules[i + 1:] if act == "deny"]
            if any(_within(a, d) for d in later_denies):
                continue
            perm = "M" if action == "write" else "RX"
            inside = [d for d in later_denies if _within(d, a)]
            _carve(a, perm, inside, out)
        return out

    def _apply_acls(self, spec: SandboxSpec, sid: str) -> list[Path]:
        touched: list[Path] = []
        for path, perm, inherit in self.plan_acls(spec.fs_rules):
            flags = "(OI)(CI)" if inherit and path.is_dir() else ""
            _icacls(str(path), "/grant", f"*{sid}:{flags}({perm})", "/Q")
            touched.append(path)
        return touched

    def _remove_acls(self, touched: list[Path], sid: str) -> None:
        for p in reversed(touched):
            try:
                _icacls(str(p), "/remove", f"*{sid}", "/Q")
            except Exception:
                pass

    # -- run -------------------------------------------------------------
    def _profile(self, name: str, cap_arr, cap_count: int):
        sid = PSID()
        hr = userenv.CreateAppContainerProfile(name, name, "Aegis sandbox session",
                                               cap_arr if cap_count else None, cap_count, ctypes.byref(sid))
        if hr == HRESULT_ALREADY_EXISTS:
            hr = userenv.DeriveAppContainerSidFromAppContainerName(name, ctypes.byref(sid))
        if hr != 0:
            raise SandboxUnavailable(f"CreateAppContainerProfile failed (HRESULT {hr & 0xFFFFFFFF:#x})")
        return sid

    def run(self, spec: SandboxSpec, argv: list[str], *, log_path: Path | None, timeout: float | None,
            proxy=None, stdio=None) -> RunResult:
        caps: list[str] = []
        env = dict(spec.env)
        if spec.network == "all":
            caps = [CAP_INTERNET_CLIENT, CAP_INTERNET_CLIENT_SERVER, CAP_PRIVATE_NETWORK]
        cap_sids = [_str_to_sid(c) for c in caps]
        cap_arr = (SID_AND_ATTRIBUTES * max(1, len(cap_sids)))()
        for i, s in enumerate(cap_sids):
            cap_arr[i].Sid = s
            cap_arr[i].Attributes = 0x00000004  # SE_GROUP_ENABLED

        name = f"aegis.{uuid.uuid4().hex[:12]}"
        persistent = False
        lock = None
        touched: list[Path] = []
        loopback = False
        sid = self._profile(name, cap_arr, len(cap_sids))
        sid_str = _sid_to_str(sid)
        try:
            if isinstance(spec.network, list):
                if proxy is None or proxy.tcp_port is None:
                    raise RuntimeError("allowlist networking needs the Aegis proxy")
                if _loopback_exempt(sid_str, add=True):
                    loopback = True
                else:
                    # Not elevated: fall back to the shared container prepared once by
                    # `aegis windows-setup` (runs are serialised with a lock file).
                    userenv.DeleteAppContainerProfile(name)
                    name, persistent = SHARED_NET_CONTAINER, True
                    sid = self._profile(name, None, 0)
                    sid_str = _sid_to_str(sid)
                    if not _loopback_exempt(sid_str, add=False):
                        raise SandboxUnavailable(
                            "domain allowlists on Windows need a one-time setup: open an *elevated* terminal and run "
                            "`aegis windows-setup` (or run Aegis elevated)")
                    lock = _acquire_lock()
                env.update(proxy_env(f"http://127.0.0.1:{proxy.tcp_port}"))
            touched = self._apply_acls(spec, sid_str)
            return self._spawn(sid, cap_arr, len(cap_sids), argv, env, spec.cwd, log_path, timeout, stdio)
        finally:
            self._remove_acls(touched, sid_str)
            if loopback:
                subprocess.run(["CheckNetIsolation.exe", "LoopbackExempt", "-d", f"-p={sid_str}"],
                               capture_output=True)
            if not persistent:
                userenv.DeleteAppContainerProfile(name)
            if lock is not None:
                lock.close()
            for s in cap_sids:
                kernel32.LocalFree(s)

    def _spawn(self, sid, cap_arr, cap_count, argv, env, cwd: Path, log_path: Path | None,
               timeout: float | None, stdio=None) -> RunResult:
        sc = SECURITY_CAPABILITIES()
        sc.AppContainerSid = sid
        sc.Capabilities = cap_arr if cap_count else None
        sc.CapabilityCount = cap_count

        opened = []
        if stdio is None:
            log = open(log_path, "ab")
            nul = open(os.devnull, "rb")
            opened = [log, nul]
            h_in, h_out, h_err = (msvcrt.get_osfhandle(nul.fileno()), msvcrt.get_osfhandle(log.fileno()),
                                  msvcrt.get_osfhandle(log.fileno()))
        else:
            h_in, h_out, h_err = (msvcrt.get_osfhandle(fd) for fd in stdio)
        uniq = list(dict.fromkeys([h_in, h_out, h_err]))
        for h in uniq:
            os.set_handle_inheritable(h, True)
        handles = (wintypes.HANDLE * len(uniq))(*uniq)

        size = ctypes.c_size_t(0)
        kernel32.InitializeProcThreadAttributeList(None, 2, 0, ctypes.byref(size))
        attr = ctypes.create_string_buffer(size.value)
        if not kernel32.InitializeProcThreadAttributeList(attr, 2, 0, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        job = None
        pi = PROCESS_INFORMATION()
        start = time.monotonic()
        try:
            if not kernel32.UpdateProcThreadAttribute(attr, 0, PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,
                                                      ctypes.byref(sc), ctypes.sizeof(sc), None, None):
                raise ctypes.WinError(ctypes.get_last_error())
            if not kernel32.UpdateProcThreadAttribute(attr, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
                                                      handles, ctypes.sizeof(handles), None, None):
                raise ctypes.WinError(ctypes.get_last_error())
            si = STARTUPINFOEXW()
            si.StartupInfo.cb = ctypes.sizeof(STARTUPINFOEXW)
            si.StartupInfo.dwFlags = STARTF_USESTDHANDLES
            si.StartupInfo.hStdInput = h_in
            si.StartupInfo.hStdOutput = h_out
            si.StartupInfo.hStdError = h_err
            si.lpAttributeList = ctypes.cast(attr, LPVOID)

            cmdline = ctypes.create_unicode_buffer(_cmdline(argv))
            # Note: create_unicode_buffer() would stop at the first NUL, truncating the block.
            block = "".join(f"{k}={v}\0" for k, v in sorted(env.items(), key=lambda kv: kv[0].upper())) + "\0"
            env_block = (ctypes.c_wchar * len(block))()
            env_block[:] = block
            flags = EXTENDED_STARTUPINFO_PRESENT | CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT | CREATE_NO_WINDOW
            if not kernel32.CreateProcessW(None, cmdline, None, None, True, flags, env_block, str(cwd),
                                           ctypes.byref(si), ctypes.byref(pi)):
                raise ctypes.WinError(ctypes.get_last_error())

            job = kernel32.CreateJobObjectW(None, None)
            info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            kernel32.SetInformationJobObject(job, JobObjectExtendedLimitInformation, ctypes.byref(info),
                                             ctypes.sizeof(info))
            if not kernel32.AssignProcessToJobObject(job, pi.hProcess):
                kernel32.TerminateProcess(pi.hProcess, 1)
                raise ctypes.WinError(ctypes.get_last_error())
            kernel32.ResumeThread(pi.hThread)

            timed_out = False
            ms = INFINITE if timeout is None else int(timeout * 1000)
            if kernel32.WaitForSingleObject(pi.hProcess, ms) == WAIT_TIMEOUT:
                timed_out = True
                kernel32.TerminateJobObject(job, 1)
                kernel32.WaitForSingleObject(pi.hProcess, 5000)
            code = wintypes.DWORD()
            kernel32.GetExitCodeProcess(pi.hProcess, ctypes.byref(code))
            return RunResult(exit_code=int(code.value), timed_out=timed_out,
                             duration=time.monotonic() - start, log_path=log_path or Path(os.devnull))
        finally:
            kernel32.DeleteProcThreadAttributeList(attr)
            for h in (pi.hThread, pi.hProcess, job):
                if h:
                    kernel32.CloseHandle(h)
            for f in opened:
                f.close()


SHARED_NET_CONTAINER = "aegis.net.v1"
INFINITE = 0xFFFFFFFF


def _loopback_exempt(sid_str: str, add: bool) -> bool:
    """Is (or can we make) this AppContainer SID exempt from loopback isolation?"""
    if add:
        r = subprocess.run(["CheckNetIsolation.exe", "LoopbackExempt", "-a", f"-p={sid_str}"],
                           capture_output=True, text=True)
        if r.returncode == 0:
            return True
    r = subprocess.run(["CheckNetIsolation.exe", "LoopbackExempt", "-s"], capture_output=True, text=True)
    return sid_str.lower() in (r.stdout or "").lower()


def _acquire_lock():
    from aegis_jail import paths
    f = open(paths.aegis_home() / "windows-net.lock", "a+b")
    while True:
        try:
            msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
            return f
        except OSError:
            time.sleep(0.5)


def windows_setup() -> str:
    """One-time elevated setup for domain allowlists without running Aegis elevated."""
    sid = AppContainerBackend()._profile(SHARED_NET_CONTAINER, None, 0)
    sid_str = _sid_to_str(sid)
    if not _loopback_exempt(sid_str, add=True):
        raise SandboxUnavailable("could not add the loopback exemption - run this from an elevated terminal")
    return sid_str


def _within(child: Path, parent: Path) -> bool:
    try:
        Path(str(child).lower()).relative_to(Path(str(parent).lower()))
        return True
    except ValueError:
        return False


def _carve(path: Path, perm: str, denies: list[Path], out: list[tuple[Path, str, bool]]) -> None:
    if any(_within(path, d) for d in denies):
        return
    inside = [d for d in denies if _within(d, path)]
    if not inside or not path.is_dir():
        out.append((path, perm, True))
        return
    out.append((path, "RX", False))  # list / traverse this directory only
    try:
        children = list(path.iterdir())
    except OSError:
        return
    for child in children:
        _carve(child, perm, [d for d in inside if _within(d, child)], out)


def _cmdline(argv: list[str]) -> str:
    # cmd.exe does not understand the backslash-escaped quotes produced by
    # list2cmdline, so `cmd /d /s /c "<command>"` is passed verbatim.
    if (len(argv) == 5 and argv[0].replace("\\", "/").rsplit("/", 1)[-1].lower() == "cmd.exe"
            and [a.lower() for a in argv[1:4]] == ["/d", "/s", "/c"]):
        return f'{subprocess.list2cmdline([argv[0]])} /d /s /c "{argv[4]}"'
    return subprocess.list2cmdline(argv)
