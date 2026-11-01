"""Windows backend: AppContainer.

An AppContainer process starts with access to almost nothing in the user
profile: only objects whose ACL names the container's SID (or "ALL
APPLICATION PACKAGES") are reachable. Hydra therefore:

1. creates a per-run AppContainer profile (and SID),
2. adds ACEs for that SID on granted paths (read or modify) and explicit
   deny ACEs where a deny rule sits inside a granted path,
3. starts the agent with SECURITY_CAPABILITIES inside a Job object (so all
   child processes stay in the container and die with the session),
4. removes the ACEs and the profile afterwards.

Network: offline = no capabilities; "all" = internetClient + privateNetwork;
allowlist = no internet capability and a loopback exemption so the process
can reach only Hydra's proxy. Adding the loopback exemption requires an
elevated prompt on most systems; without it Hydra refuses to widen access.
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

from hydra_guard.sandbox.base import Backend, RunResult, SandboxSpec, SandboxUnavailable, proxy_env

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


def _quote_arg(a: str) -> str:
    return subprocess.list2cmdline([a])


class AppContainerBackend(Backend):
    name = "windows-appcontainer"

    def check(self) -> None:
        if sys.platform != "win32":
            raise SandboxUnavailable("not Windows")
        if sys.getwindowsversion().build < 9200:
            raise SandboxUnavailable("AppContainer needs Windows 8 / Server 2012 or newer")

    # -- ACL management --------------------------------------------------
    def _apply_acls(self, spec: SandboxSpec, sid: str) -> list[Path]:
        touched: list[Path] = []
        allowed: list[Path] = []
        for action, p in spec.fs_rules:
            if not p.exists():
                continue
            if action in ("read", "write"):
                perm = "(OI)(CI)(M)" if action == "write" else "(OI)(CI)(RX)"
                if p.is_file():
                    perm = "(M)" if action == "write" else "(RX)"
                _icacls(str(p), "/grant", f"*{sid}:{perm}", "/Q")
                touched.append(p)
                allowed.append(p)
            elif action == "deny":
                # AppContainers see nothing by default; a deny ACE is needed
                # only where an earlier grant would otherwise expose the path.
                if any(_within(p, a) for a in allowed):
                    perm = "(OI)(CI)(F)" if p.is_dir() else "(F)"
                    _icacls(str(p), "/deny", f"*{sid}:{perm}", "/Q")
                    touched.append(p)
        return touched

    def _remove_acls(self, touched: list[Path], sid: str) -> None:
        for p in reversed(touched):
            try:
                _icacls(str(p), "/remove", f"*{sid}", "/Q")
            except Exception:
                pass

    # -- run -------------------------------------------------------------
    def run(self, spec: SandboxSpec, argv: list[str], *, log_path: Path, timeout: float, proxy=None) -> RunResult:
        name = f"hydra.{uuid.uuid4().hex[:12]}"
        caps: list[str] = []
        env = dict(spec.env)
        if spec.network == "all":
            caps = [CAP_INTERNET_CLIENT, CAP_INTERNET_CLIENT_SERVER, CAP_PRIVATE_NETWORK]
        cap_sids = [_str_to_sid(c) for c in caps]
        cap_arr = (SID_AND_ATTRIBUTES * max(1, len(cap_sids)))()
        for i, s in enumerate(cap_sids):
            cap_arr[i].Sid = s
            cap_arr[i].Attributes = 0x00000004  # SE_GROUP_ENABLED
        sid = PSID()
        hr = userenv.CreateAppContainerProfile(name, name, "Hydra sandbox session",
                                               cap_arr if cap_sids else None, len(cap_sids), ctypes.byref(sid))
        if hr == HRESULT_ALREADY_EXISTS:
            hr = userenv.DeriveAppContainerSidFromAppContainerName(name, ctypes.byref(sid))
        if hr != 0:
            raise SandboxUnavailable(f"CreateAppContainerProfile failed (HRESULT {hr & 0xFFFFFFFF:#x})")
        sid_str = _sid_to_str(sid)
        touched: list[Path] = []
        loopback = False
        try:
            if isinstance(spec.network, list):
                if proxy is None or proxy.tcp_port is None:
                    raise RuntimeError("allowlist networking needs the Hydra proxy")
                r = subprocess.run(["CheckNetIsolation.exe", "LoopbackExempt", "-a", f"-p={sid_str}"],
                                   capture_output=True, text=True)
                if r.returncode != 0:
                    raise SandboxUnavailable(
                        "domain allowlists on Windows need a loopback exemption for the sandbox; run Hydra from an "
                        "elevated terminal, or use offline / unrestricted network for this phase")
                loopback = True
                env.update(proxy_env(f"http://127.0.0.1:{proxy.tcp_port}"))
            touched = self._apply_acls(spec, sid_str)
            return self._spawn(sid, cap_arr, len(cap_sids), argv, env, spec.cwd, log_path, timeout)
        finally:
            self._remove_acls(touched, sid_str)
            if loopback:
                subprocess.run(["CheckNetIsolation.exe", "LoopbackExempt", "-d", f"-p={sid_str}"],
                               capture_output=True)
            userenv.DeleteAppContainerProfile(name)
            for s in cap_sids:
                kernel32.LocalFree(s)

    def _spawn(self, sid, cap_arr, cap_count, argv, env, cwd: Path, log_path: Path, timeout: float) -> RunResult:
        sc = SECURITY_CAPABILITIES()
        sc.AppContainerSid = sid
        sc.Capabilities = cap_arr if cap_count else None
        sc.CapabilityCount = cap_count

        log = open(log_path, "ab")
        nul = open(os.devnull, "rb")
        h_out = msvcrt.get_osfhandle(log.fileno())
        h_in = msvcrt.get_osfhandle(nul.fileno())
        os.set_handle_inheritable(h_out, True)
        os.set_handle_inheritable(h_in, True)
        handles = (wintypes.HANDLE * 2)(h_in, h_out)

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
            si.StartupInfo.hStdError = h_out
            si.lpAttributeList = ctypes.cast(attr, LPVOID)

            cmdline = ctypes.create_unicode_buffer(" ".join(_quote_arg(a) for a in argv))
            env_block = ctypes.create_unicode_buffer("".join(f"{k}={v}\0" for k, v in sorted(env.items())) + "\0")
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
            ms = int(timeout * 1000)
            if kernel32.WaitForSingleObject(pi.hProcess, ms) == WAIT_TIMEOUT:
                timed_out = True
                kernel32.TerminateJobObject(job, 1)
                kernel32.WaitForSingleObject(pi.hProcess, 5000)
            code = wintypes.DWORD()
            kernel32.GetExitCodeProcess(pi.hProcess, ctypes.byref(code))
            return RunResult(exit_code=int(code.value), timed_out=timed_out,
                             duration=time.monotonic() - start, log_path=log_path)
        finally:
            kernel32.DeleteProcThreadAttributeList(attr)
            for h in (pi.hThread, pi.hProcess, job):
                if h:
                    kernel32.CloseHandle(h)
            log.close()
            nul.close()


def _within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False
