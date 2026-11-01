"""Common sandbox types.

A SandboxSpec is the platform-neutral result of compiling a profile for one
phase. Each backend translates it to native isolation:

* Linux   - bubblewrap (mount + network namespaces)
* macOS   - Seatbelt (sandbox-exec) profile
* Windows - AppContainer + per-path ACLs + Job object

fs_rules are evaluated in order and the *last* matching rule wins:
  ("deny", p)  - p is unreadable and unwritable
  ("read", p)  - p is readable
  ("write", p) - p is readable and writable
Everything not covered by a rule is readable (system files) but not writable.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SandboxSpec:
    fs_rules: list[tuple[str, Path]]
    network: None | str | list[str]  # None = offline, "all", or allowed domains
    env: dict[str, str]
    cwd: Path
    tmp: Path
    notes: list[str] = field(default_factory=list)

    def describe_network(self) -> str:
        if self.network is None:
            return "none"
        if self.network == "all":
            return "unrestricted"
        return "only " + ", ".join(self.network)


@dataclass
class RunResult:
    exit_code: int
    timed_out: bool
    duration: float
    log_path: Path

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


class SandboxUnavailable(RuntimeError):
    pass


class Backend:
    name = "base"
    # Whether the backend can confine to a domain allowlist (via the proxy).
    supports_allowlist = True

    def check(self) -> None:
        """Raise SandboxUnavailable if this backend cannot run here."""

    def run(self, spec: SandboxSpec, argv: list[str], *, log_path: Path,
            timeout: float, proxy=None) -> RunResult:  # pragma: no cover - abstract
        raise NotImplementedError


def proxy_env(url: str) -> dict[str, str]:
    env = {}
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env[k] = url
    env["NO_PROXY"] = env["no_proxy"] = "localhost,127.0.0.1,::1"
    return env


def run_posix(argv: list[str], env: dict[str, str], cwd: Path, log_path: Path, timeout: float) -> RunResult:
    start = time.monotonic()
    timed_out = False
    with open(log_path, "ab") as log:
        proc = subprocess.Popen(argv, env=env, cwd=str(cwd), stdin=subprocess.DEVNULL,
                                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            code = proc.wait()
    return RunResult(exit_code=code, timed_out=timed_out, duration=time.monotonic() - start, log_path=log_path)
