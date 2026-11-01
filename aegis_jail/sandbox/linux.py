# SPDX-License-Identifier: AGPL-3.0-or-later
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

import os
import shutil
import subprocess
import sys
from pathlib import Path

from aegis_jail import seccomp
from aegis_jail.sandbox.base import Backend, RunResult, SandboxSpec, SandboxUnavailable, proxy_env, run_posix

BRIDGE_PORT = 3128
SOCK_MOUNT = "/tmp/.aegis-proxy"  # /tmp is a private tmpfs inside the sandbox


class BwrapBackend(Backend):
    name = "linux-bwrap"

    def __init__(self) -> None:
        self.bwrap = shutil.which("bwrap")
        self.hardening: list[str] = []
        self.seccomp: bytes | None = seccomp.build_filter() if seccomp.supported() else None

    def check(self) -> None:
        if not self.bwrap:
            raise SandboxUnavailable("bubblewrap (bwrap) is not installed - e.g. `sudo apt install bubblewrap`")
        probe = subprocess.run([self.bwrap, "--ro-bind", "/", "/", "--unshare-net", "true"],
                               capture_output=True, text=True)
        if probe.returncode != 0:
            raise SandboxUnavailable(f"bubblewrap cannot create namespaces here: {probe.stderr.strip()}")
        # Optional hardening, used when this bwrap/kernel supports it:
        #  - own user namespace (also isolates the kernel keyring) and no nested user namespaces
        #    (shrinks kernel attack surface for escapes),
        #  - own cgroup namespace,
        #  - size-capped /tmp (a RAM-backed tmpfs could otherwise be used to exhaust memory).
        for flags in (["--unshare-user", "--disable-userns"], ["--unshare-cgroup-try"]):
            r = subprocess.run([self.bwrap, "--ro-bind", "/", "/", *flags, "true"], capture_output=True)
            if r.returncode == 0:
                self.hardening += flags
        r = subprocess.run([self.bwrap, "--ro-bind", "/", "/", "--size", "1048576", "--tmpfs", "/tmp", "true"],
                           capture_output=True)
        self.sized_tmp = r.returncode == 0
        if self.seccomp:  # confirm this kernel/bwrap accepts our filter; disable quietly if not
            try:
                rfd, wfd = os.pipe()
                os.write(wfd, self.seccomp)
                os.close(wfd)
                r = subprocess.run([self.bwrap, "--ro-bind", "/", "/", "--seccomp", str(rfd), "true"],
                                   pass_fds=(rfd,), capture_output=True)
                os.close(rfd)
                if r.returncode != 0:
                    self.seccomp = None
            except OSError:
                self.seccomp = None

    @property
    def seccomp_enabled(self) -> bool:
        return self.seccomp is not None

    def build_argv(self, spec: SandboxSpec, argv: list[str], proxy=None,
                   seccomp_fd: int | None = None) -> tuple[list[str], dict[str, str]]:
        assert self.bwrap
        tmp_size = os.environ.get("AEGIS_TMPFS_BYTES", str(1 << 30))
        a = [self.bwrap, "--die-with-parent", "--unshare-pid", "--unshare-ipc", "--unshare-uts",
             "--new-session", *(["--seccomp", str(seccomp_fd)] if seccomp_fd is not None else []), *self.hardening, "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
             *(["--size", tmp_size] if getattr(self, "sized_tmp", False) else []), "--tmpfs", "/tmp"]
        hidden: list[str] = []
        # Host services live behind unix sockets under /run (Docker, containerd/podman, D-Bus with the
        # desktop keyring, ssh-agent / gpg-agent in /run/user/UID, systemd). A read-only mount does
        # NOT stop connect() on a socket, so these directories must be replaced, not just made read-only.
        for d in ("/run", "/var/run", "/var/lib/docker", "/var/lib/containerd"):
            if os.path.isdir(d) and not os.path.islink(d):
                a += ["--tmpfs", d]
                hidden.append(d)
        if spec.network == "all":  # host network only with AEGIS_HOST_NETWORK=1: keep DNS working
            for d in ("/run/systemd/resolve", "/run/NetworkManager", "/run/resolvconf"):
                if os.path.isdir(d):
                    a += ["--ro-bind", d, d]
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
        # Decoy credentials (honeytokens) where real ones were hidden: if anything later shows up
        # carrying them - in a request, a tool call, a file or the output - it is a tripwire.
        for target, src in spec.decoys.items():
            a += ["--ro-bind", src, target]
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
        fd = None
        try:
            if self.seccomp:
                bpf = spec.tmp / "seccomp.bpf"
                bpf.write_bytes(self.seccomp)
                fd = os.open(str(bpf), os.O_RDONLY)
                os.set_inheritable(fd, True)
            full, env = self.build_argv(spec, argv, proxy, fd)
            return run_posix(full, env, spec.cwd, log_path, timeout, stdio,
                             pass_fds=(fd,) if fd is not None else ())
        finally:
            if fd is not None:
                os.close(fd)
