"""Agent adapters and task definitions.

The first release supports one real agent CLI (Claude Code) plus a generic
`command` adapter used for demos, tests and scripting.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from aegis_jail import paths
from aegis_jail.policy import Grant


@dataclass
class Task:
    name: str = "task"
    agent: str = "command"
    prompt: str = ""
    command: list[str] = field(default_factory=list)  # for the `command` agent; "{prompt}" is substituted
    setup: str = ""   # shell command run before the agent (e.g. "npm ci")
    verify: str = ""  # shell command that must succeed afterwards (e.g. "npm test")
    timeout: float = 1800

    @classmethod
    def load(cls, path: Path) -> "Task":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def expand(self, s: str) -> str:
        """Substitute {python} so task files work on every OS."""
        # Always quoted on Windows: cmd.exe inside an AppContainer cannot start an
        # unquoted absolute path (it probes parent directories it may not list).
        return s.replace("{python}", f'"{sys.executable}"' if os.name == "nt" else shlex.quote(sys.executable))

    def fingerprint(self) -> str:
        blob = json.dumps(asdict(self), sort_keys=True).encode()
        return hashlib.sha256(blob).hexdigest()[:12]


def shell(cmd: str) -> list[str]:
    if os.name == "nt":
        comspec = os.environ.get("COMSPEC") or os.path.join(os.environ.get("SYSTEMROOT", r"C:\Windows"), "System32", "cmd.exe")
        return [comspec, "/d", "/s", "/c", cmd]
    return ["/bin/sh", "-c", cmd]


def _resolve(exe: str) -> str:
    if exe in ("{python}", "python3", "python") and (exe == "{python}" or not shutil.which(exe)):
        return sys.executable
    found = shutil.which(exe)
    return os.path.realpath(found) if found else exe


def _install_grants(exe_path: str, prefix: str) -> list[Grant]:
    """Read access to an executable's install dir if it lives in the home dir."""
    grants = []
    p = Path(exe_path)
    home = paths.user_home()
    if p.is_absolute() and p.exists():
        try:
            p.resolve().relative_to(home)
        except ValueError:
            return grants
        grants.append(Grant(id=f"{prefix}-install", kind="read", path=str(p.resolve().parent), locked=True,
                            note="agent program files"))
    return grants


class Agent:
    name = "base"

    def argv(self, task: Task) -> list[str]:
        raise NotImplementedError

    def grants(self, task: Task) -> list[Grant]:
        return []

    def version(self, task: Task) -> str:
        return "unknown"


class CommandAgent(Agent):
    """Any command line program; `{prompt}` in its arguments is replaced."""

    name = "command"

    def argv(self, task: Task) -> list[str]:
        if not task.command:
            raise ValueError("the `command` agent needs task.command (e.g. [\"python\", \"agent.py\", \"{prompt}\"])")
        out = [a.replace("{prompt}", task.prompt).replace("{python}", sys.executable) for a in task.command]
        out[0] = _resolve(out[0])
        return out

    def grants(self, task: Task) -> list[Grant]:
        return _install_grants(self.argv(task)[0], "agent") if task.command else []


class ClaudeCodeAgent(Agent):
    """Claude Code in headless mode.

    Aegis enforces the boundaries itself, so Claude Code's own per-tool
    prompts are turned off inside the sandbox - that is the point: the
    agent can work without interruptions, but cannot leave the profile.
    """

    name = "claude-code"
    exe = "claude"

    def argv(self, task: Task) -> list[str]:
        return [_resolve(self.exe), "-p", task.prompt, "--dangerously-skip-permissions"]

    def grants(self, task: Task) -> list[Grant]:
        g = [
            Grant(id="claude-config", kind="write", path="~/.claude", locked=True, note="Claude Code settings and sessions"),
            Grant(id="claude-state", kind="write", path="~/.claude.json", locked=True, note="Claude Code login state"),
            Grant(id="claude-api", kind="net", domains=["api.anthropic.com"], phase="task", locked=True,
                  note="model API"),
            Grant(id="claude-telemetry", kind="net", domains=["statsig.anthropic.com", "sentry.io", "*.sentry.io"],
                  phase="task", note="Claude Code telemetry / error reporting"),
            Grant(id="claude-env", kind="env",
                  names=[k for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
                                     "ANTHROPIC_MODEL", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX")
                         if k in os.environ] or ["ANTHROPIC_API_KEY"],
                  locked=True, note="model credentials"),
        ]
        if sys.platform == "darwin":
            g.append(Grant(id="claude-keychain", kind="service", names=["keychain"], locked=True,
                           note="Claude Code stores its login in the macOS keychain"))
        g += _install_grants(_resolve(self.exe), "claude")
        node = shutil.which("node")
        if node:
            g += _install_grants(os.path.realpath(node), "node")
        return g

    def version(self, task: Task) -> str:
        try:
            r = subprocess.run([_resolve(self.exe), "--version"], capture_output=True, text=True, timeout=30)
            return r.stdout.strip() or "unknown"
        except (OSError, subprocess.SubprocessError):
            return "not installed"


class _SimpleAgent(Agent):
    """An agent CLI described by its command line, config paths, hosts and env vars."""

    exe = ""
    config_paths: list[str] = []
    hosts: list[str] = []
    env_names: list[str] = []

    def base_args(self, task: Task) -> list[str]:  # pragma: no cover - overridden
        raise NotImplementedError

    def argv(self, task: Task) -> list[str]:
        return [_resolve(self.exe), *self.base_args(task)]

    def grants(self, task: Task) -> list[Grant]:
        g = [Grant(id=f"{self.name}-config-{i}", kind="write", path=p, locked=True, note=f"{self.name} settings")
             for i, p in enumerate(self.config_paths)]
        g.append(Grant(id=f"{self.name}-api", kind="net", domains=list(self.hosts), phase="task", locked=True,
                       note="model API"))
        present = [k for k in self.env_names if k in os.environ]
        g.append(Grant(id=f"{self.name}-env", kind="env", names=present or self.env_names[:1], locked=True,
                       note="model credentials"))
        g += _install_grants(_resolve(self.exe), self.name)
        node = shutil.which("node")
        if node:
            g += _install_grants(os.path.realpath(node), "node")
        return g

    def version(self, task: Task) -> str:
        try:
            r = subprocess.run([_resolve(self.exe), "--version"], capture_output=True, text=True, timeout=30)
            return (r.stdout or r.stderr).strip().splitlines()[0] if (r.stdout or r.stderr).strip() else "unknown"
        except (OSError, subprocess.SubprocessError, IndexError):
            return "not installed"


class CodexAgent(_SimpleAgent):
    """OpenAI Codex CLI (`codex exec`). Aegis replaces Codex's own sandbox."""

    name = "codex"
    exe = "codex"
    config_paths = ["~/.codex"]
    hosts = ["api.openai.com", "auth.openai.com", "chatgpt.com"]
    env_names = ["OPENAI_API_KEY", "OPENAI_BASE_URL", "CODEX_HOME"]

    def base_args(self, task: Task) -> list[str]:
        return ["exec", "--dangerously-bypass-approvals-and-sandbox", task.prompt]


class GeminiAgent(_SimpleAgent):
    """Google Gemini CLI in non-interactive mode."""

    name = "gemini"
    exe = "gemini"
    config_paths = ["~/.gemini"]
    hosts = ["generativelanguage.googleapis.com", "oauth2.googleapis.com", "cloudcode-pa.googleapis.com",
             "*.googleapis.com"]
    env_names = ["GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_CLOUD_PROJECT", "GOOGLE_GENAI_USE_VERTEXAI"]

    def base_args(self, task: Task) -> list[str]:
        return ["--yolo", "-p", task.prompt]


class AiderAgent(_SimpleAgent):
    """Aider (`aider --message`)."""

    name = "aider"
    exe = "aider"
    config_paths = ["~/.aider"]
    hosts = ["api.openai.com", "api.anthropic.com", "openrouter.ai"]
    env_names = ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "AIDER_MODEL"]

    def base_args(self, task: Task) -> list[str]:
        return ["--yes-always", "--no-auto-commits", "--no-check-update", "--message", task.prompt]


AGENTS: dict[str, type[Agent]] = {"command": CommandAgent, "claude-code": ClaudeCodeAgent, "codex": CodexAgent,
                                  "gemini": GeminiAgent, "aider": AiderAgent}


def get_agent(name: str) -> Agent:
    try:
        return AGENTS[name]()
    except KeyError:
        raise ValueError(f"unknown agent {name!r}; supported: {', '.join(AGENTS)}") from None


def runtime_paths() -> list[Path]:
    """Aegis's own interpreter and package, needed inside the sandbox for probes and the network bridge."""
    out = {Path(__file__).resolve().parent, Path(sys.executable).resolve().parent,
           Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve()}
    return sorted(out)
