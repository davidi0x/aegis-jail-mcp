# SPDX-License-Identifier: AGPL-3.0-or-later
"""macOS backend: Seatbelt via sandbox-exec.

Aegis generates an SBPL profile per run. Seatbelt applies to the process and
every process it spawns. Rules later in the profile take precedence, which
matches the "last rule wins" semantics of SandboxSpec.fs_rules.

Reads of denied paths are blocked at the data level (file contents and
directory listings); writes are denied everywhere except granted paths.
Outbound network is denied except to Aegis's proxy port (allowlist mode).
"""

from __future__ import annotations

import shutil
from pathlib import Path

from aegis_jail.sandbox.base import Backend, RunResult, SandboxSpec, SandboxUnavailable, proxy_env, run_posix


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
        """Translate "last matching rule wins" into order-independent SBPL.

        Every restricting rule carries explicit exceptions (`require-not`) for
        the later rules that override it, so the result does not depend on
        how Seatbelt prioritises overlapping allow/deny rules.
        """
        rules = list(spec.fs_rules)
        lines = ["(version 1)", "(allow default)"]

        def deny(ops: str, path: Path, exceptions: list[Path]) -> str:
            flt = f"(subpath {_q(path)})"
            if exceptions:
                nots = " ".join(f"(require-not (subpath {_q(e)}))" for e in exceptions)
                flt = f"(require-all {flt} {nots})"
            return f"(deny {ops} {flt})"

        # Reads: denied where the last matching rule is "deny".
        for i, (action, p) in enumerate(rules):
            if action == "deny":
                later = [q for a, q in rules[i + 1:] if a in ("read", "write")]
                lines.append(deny("file-read-data file-read-xattr", p, later))
        # Writes: allowed only where the last matching rule is "write".
        writers = [("base", Path("/"))] + [(a, p) for a, p in rules]
        for i, (action, p) in enumerate(writers):
            if action != "write":
                later = [q for a, q in writers[i + 1:] if a == "write"]
                if action == "base":
                    later += [Path(x) for x in ("/dev/null", "/dev/zero", "/dev/dtracehelper", "/dev/fd",
                                                "/dev/ptmx", "/dev/tty")]
                lines.append(deny("file-write*", p, later))
        lines.append('(allow file-write* (regex #"^/dev/ttys[0-9]+$"))')
        lines += self._escape_hatches(spec)
        if spec.network == "all":
            # Even with full network, host services behind unix sockets (Docker, ssh-agent, gpg-agent,
            # databases) stay unreachable; only DNS is needed.
            ok = ['(remote unix-socket (path-literal "/private/var/run/mDNSResponder"))',
                  f"(remote unix-socket (subpath {_q(spec.tmp)}))", f"(remote unix-socket (subpath {_q(spec.cwd)}))"]
            nots = " ".join(f"(require-not {o})" for o in ok)
            lines.append(f"(deny network-outbound (require-all (remote unix-socket) {nots}))")
        if spec.network != "all":
            ok = [f"(remote unix-socket (subpath {_q(spec.tmp)}))",
                  f"(remote unix-socket (subpath {_q(spec.cwd)}))"]
            if proxy_port:
                ok.append(f'(remote ip "localhost:{proxy_port}")')
            if isinstance(spec.network, list) and "localhost" in spec.network:
                ok.append('(remote ip "localhost:*")')
            nots = " ".join(f"(require-not {o})" for o in ok)
            lines.append(f"(deny network-outbound (require-all {nots}))")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _escape_hatches(spec: SandboxSpec) -> list[str]:
        """Close the ways a sandboxed process can get *another* process to act for it.

        Seatbelt confines a process and its children, but on macOS a process can ask
        other, unsandboxed programs to do things: AppleEvents (`osascript -e 'tell app
        "Terminal" to do script ...'`), LaunchServices (`open -a`), launchd jobs, the
        pasteboard (often holds passwords) and the keychain daemon.
        """
        svc = spec.services
        out = []
        if "apple-events" not in svc:
            out.append("(deny appleevent-send)")
            out.append('(deny process-exec (literal "/usr/bin/osascript") (literal "/usr/bin/automator"))')
        if "open-apps" not in svc:
            out.append("(deny lsopen)")
            out.append('(deny mach-lookup (global-name "com.apple.coreservices.launchservicesd"))')
            out.append('(deny process-exec (literal "/usr/bin/open") (literal "/bin/launchctl"))')
        if "clipboard" not in svc:
            out.append('(deny mach-lookup (global-name "com.apple.pasteboard.1"))')
            out.append('(deny process-exec (literal "/usr/bin/pbcopy") (literal "/usr/bin/pbpaste"))')
        if "keychain" not in svc:
            out.append('(deny mach-lookup (global-name "com.apple.SecurityServer") '
                       '(global-name "com.apple.securityd.xpc") (global-name "com.apple.security.agent"))')
            out.append('(deny process-exec (literal "/usr/bin/security"))')
        out.append('(deny process-exec (literal "/usr/sbin/screencapture"))')
        out.append('(deny mach-lookup (global-name "com.apple.screencaptureui.agent") '
                   '(global-name "com.apple.tccd") (global-name "com.apple.tccd.system"))')
        return out

    def run(self, spec: SandboxSpec, argv: list[str], *, log_path: Path | None, timeout: float | None,
            proxy=None, stdio=None) -> RunResult:
        env = dict(spec.env)
        port = None
        if isinstance(spec.network, list):
            if proxy is None or proxy.tcp_port is None:
                raise RuntimeError("allowlist networking needs the Aegis proxy")
            port = proxy.tcp_port
            env.update(proxy_env(f"http://127.0.0.1:{port}"))
        prof = (log_path.with_suffix(".sb") if log_path else spec.tmp / "aegis-profile.sb")
        prof.write_text(self.profile(spec, port), encoding="utf-8")
        return run_posix([self.exe, "-f", str(prof), *argv], env, spec.cwd, log_path, timeout, stdio)
