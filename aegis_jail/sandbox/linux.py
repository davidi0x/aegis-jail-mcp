"""Linux backend: bubblewrap.

Filesystem: the host root is mounted read-only; denied paths are covered by
an empty tmpfs (directories) or /dev/null (files); granted paths are bind
mounted back read-only or read-write. All child processes inherit the mounts.

Network: offline and allowlist modes run in a fresh network namespace that
has only its own loopback. In allowlist mode a small bridge inside the
sandbox forwards 127.0.0.1:3128 to Aegis's filtering proxy over a unix
socket, so the only way out is through the allowlist.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from aegis_jail.sandbox.base import Backend, RunResult, SandboxSpec, SandboxUnavailable, proxy_env, run_posix

BRIDGE_PORT = 3128
SOCK_MOUNT = "/tmp/.aegis-proxy"  # /tmp is a private tmpfs inside the sandbox


class BwrapBackend(Backend):
    name = "linux-bwrap"

    def __init__(self) -> None:
        self.bwrap = shutil.which("bwrap")

    def check(self) -> None:
        if not self.bwrap:
            raise SandboxUnavailable("bubblewrap (bwrap) is not installed - e.g. `sudo apt install bubblewrap`")
        probe = subprocess.run([self.bwrap, "--ro-bind", "/", "/", "--unshare-net", "true"],
                               capture_output=True, text=True)
        if probe.returncode != 0:
            raise SandboxUnavailable(f"bubblewrap cannot create namespaces here: {probe.stderr.strip()}")

    def build_argv(self, spec: SandboxSpec, argv: list[str], proxy=None) -> tuple[list[str], dict[str, str]]:
        assert self.bwrap
        a = [self.bwrap, "--die-with-parent", "--unshare-pid", "--unshare-ipc", "--unshare-uts",
             "--new-session", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp"]
        hidden: list[str] = []
        for action, p in spec.fs_rules:
            if not p.exists():
                continue
            s = str(p)
            if action == "deny":
                if p.is_dir():
                    a += ["--tmpfs", s]
                    hidden.append(s)
                else:
                    a += ["--ro-bind", "/dev/null", s]
            elif action == "read":
                a += ["--ro-bind", s, s]
            elif action == "write":
                a += ["--bind", s, s]
        # Make the empty stand-ins read-only, so writes there fail loudly instead
        # of silently landing in a throwaway tmpfs. Mounts nested inside keep
        # their own flags (e.g. the writable working copy).
        for s in hidden:
            a += ["--remount-ro", s]
        env = dict(spec.env)
        if spec.network is None:
            a += ["--unshare-net"]
        elif spec.network != "all":
            if proxy is None or proxy.unix_path is None:
                raise RuntimeError("allowlist networking needs the Aegis proxy on a unix socket")
            sock_dir = str(Path(proxy.unix_path).parent)
            a += ["--unshare-net", "--bind", sock_dir, SOCK_MOUNT]
            sock = f"{SOCK_MOUNT}/{Path(proxy.unix_path).name}"
            pkg_parent = str(Path(__file__).resolve().parent.parent.parent)
            boot = f"import sys; sys.path.insert(0, {pkg_parent!r}); from aegis_jail.bridge import main; sys.exit(main(sys.argv[1:]))"
            argv = [sys.executable, "-c", boot, sock, str(BRIDGE_PORT), "--", *argv]
            env.update(proxy_env(f"http://127.0.0.1:{BRIDGE_PORT}"))
        a += ["--chdir", str(spec.cwd), "--", *argv]
        return a, env

    def run(self, spec: SandboxSpec, argv: list[str], *, log_path: Path | None, timeout: float | None,
            proxy=None, stdio=None) -> RunResult:
        full, env = self.build_argv(spec, argv, proxy)
        return run_posix(full, env, spec.cwd, log_path, timeout, stdio)
