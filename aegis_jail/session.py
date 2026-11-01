"""Long-running sandboxed processes with stdio attached (interactive tools, MCP servers).

Unlike `run_task`, which works on a throwaway copy, a session runs a command
against the real project directory - read-only by default, or writable with
`write=True` - and keeps the caller's stdin/stdout connected.
"""

from __future__ import annotations

import os
import secrets
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from aegis_jail import paths
from aegis_jail.agents import runtime_paths
from aegis_jail.netproxy import FilteringProxy
from aegis_jail.policy import Profile
from aegis_jail.sandbox import Backend, SandboxSpec, get_backend
from aegis_jail.sandbox.base import RunResult


@dataclass
class Session:
    project: Path
    profile: Profile
    write: bool = False
    phase: str = "task"
    backend: Backend | None = None
    ask: Callable[[str, int], bool] | None = None
    proxy: FilteringProxy | None = field(default=None, init=False)
    spec: SandboxSpec | None = field(default=None, init=False)
    tmp: Path | None = field(default=None, init=False)

    def prepare(self) -> SandboxSpec:
        self.project = self.project.resolve()
        self.backend = self.backend or get_backend()
        self.tmp = paths.aegis_home() / "sessions" / secrets.token_hex(6)
        self.tmp.mkdir(parents=True)
        spec = self.profile.compile(self.phase, project=self.project, workspace=self.project, tmp=self.tmp,
                                    runtime_paths=runtime_paths())
        if not self.write:
            # Same rules, but the project becomes read-only instead of writable.
            spec.fs_rules = [("read", p) if (a == "write" and p == self.project) else (a, p)
                             for a, p in spec.fs_rules]
        self.spec = spec
        if isinstance(spec.network, list):
            linux = self.backend.name == "linux-bwrap"
            self.proxy = FilteringProxy(spec.network, ask=self.ask, tcp=not linux, unix=linux).start()
        return spec

    def run(self, argv: list[str], stdio: tuple[int, int, int] | None = None) -> RunResult:
        spec = self.spec or self.prepare()
        assert self.backend is not None
        stdio = stdio or (sys.stdin.fileno(), sys.stdout.fileno(), sys.stderr.fileno())
        try:
            return self.backend.run(spec, argv, log_path=None, timeout=None, proxy=self.proxy, stdio=stdio)
        finally:
            self.close()

    def blocked_hosts(self) -> list[str]:
        if not self.proxy:
            return []
        return sorted({f"{e.host}:{e.port}" for e in self.proxy.events if not e.allowed})

    def close(self) -> None:
        if self.proxy:
            self.proxy.stop()
        if self.tmp and self.tmp.exists():
            shutil.rmtree(self.tmp, ignore_errors=True)


def resolve_argv(argv: list[str]) -> list[str]:
    """Resolve the program to an absolute real path (symlinks in hidden dirs would not work)."""
    from aegis_jail.agents import _resolve
    if not argv:
        raise ValueError("no command given")
    out = list(argv)
    out[0] = _resolve(out[0])
    if os.name != "nt" and not os.path.isabs(out[0]):
        raise ValueError(f"command not found: {argv[0]}")
    return out
