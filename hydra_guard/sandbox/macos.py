"""macOS backend: Seatbelt via sandbox-exec.

Hydra generates an SBPL profile per run. Seatbelt applies to the process and
every process it spawns. Rules later in the profile take precedence, which
matches the "last rule wins" semantics of SandboxSpec.fs_rules.

Reads of denied paths are blocked at the data level (file contents and
directory listings); writes are denied everywhere except granted paths.
Outbound network is denied except to Hydra's proxy port (allowlist mode).
"""

from __future__ import annotations

import shutil
from pathlib import Path

from hydra_guard.sandbox.base import Backend, RunResult, SandboxSpec, SandboxUnavailable, proxy_env, run_posix


def _q(p: Path | str) -> str:
    return '"' + str(p).replace("\\", "\\\\").replace('"', '\\"') + '"'


class SeatbeltBackend(Backend):
    name = "macos-seatbelt"

    def __init__(self) -> None:
        self.exe = shutil.which("sandbox-exec") or "/usr/bin/sandbox-exec"

    def check(self) -> None:
        if not Path(self.exe).exists():
            raise SandboxUnavailable("sandbox-exec not found")

    def profile(self, spec: SandboxSpec, proxy_port: int | None) -> str:
        lines = [
            "(version 1)",
            "(allow default)",
            '(deny file-write* (subpath "/"))',
        ]
        for action, p in spec.fs_rules:
            if action == "deny":
                lines.append(f"(deny file-read-data file-read-xattr file-write* (subpath {_q(p)}))")
            elif action == "read":
                lines.append(f"(allow file-read* (subpath {_q(p)}))")
                lines.append(f"(deny file-write* (subpath {_q(p)}))")
            elif action == "write":
                lines.append(f"(allow file-read* file-write* (subpath {_q(p)}))")
        lines += [
            '(allow file-write* (literal "/dev/null") (literal "/dev/zero") (literal "/dev/dtracehelper")',
            '  (regex #"^/dev/tty") (regex #"^/dev/fd/") (literal "/dev/ptmx") (regex #"^/dev/ttys"))',
        ]
        if spec.network != "all":
            lines.append("(deny network-outbound)")
            # Local IPC inside the working copy / temp dir is fine.
            lines.append(f"(allow network-outbound (remote unix-socket (subpath {_q(spec.tmp)})))")
            lines.append(f"(allow network-outbound (remote unix-socket (subpath {_q(spec.cwd)})))")
            if proxy_port:
                lines.append(f'(allow network-outbound (remote ip "localhost:{proxy_port}"))')
            if isinstance(spec.network, list) and "localhost" in spec.network:
                lines.append('(allow network-outbound (remote ip "localhost:*"))')
        return "\n".join(lines) + "\n"

    def run(self, spec: SandboxSpec, argv: list[str], *, log_path: Path, timeout: float, proxy=None) -> RunResult:
        env = dict(spec.env)
        port = None
        if isinstance(spec.network, list):
            if proxy is None or proxy.tcp_port is None:
                raise RuntimeError("allowlist networking needs the Hydra proxy")
            port = proxy.tcp_port
            env.update(proxy_env(f"http://127.0.0.1:{port}"))
        prof = log_path.with_suffix(".sb")
        prof.write_text(self.profile(spec, port), encoding="utf-8")
        return run_posix([self.exe, "-f", str(prof), *argv], env, spec.cwd, log_path, timeout)
