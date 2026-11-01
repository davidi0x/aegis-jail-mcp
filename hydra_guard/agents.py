"""Agent adapters and task definitions.

The first release supports one real agent CLI (Claude Code) plus a generic
`command` adapter used for demos, tests and scripting.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from hydra_guard import paths
from hydra_guard.policy import Grant


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

    def fingerprint(self) -> str:
        blob = json.dumps(asdict(self), sort_keys=True).encode()
        return hashlib.sha256(blob).hexdigest()[:12]


def shell(cmd: str) -> list[str]:
    if os.name == "nt":
        return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", cmd]
    return ["/bin/sh", "-c", cmd]


def _resolve(exe: str) -> str:
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
        out = [a.replace("{prompt}", task.prompt) for a in task.command]
        out[0] = _resolve(out[0])
        return out

    def grants(self, task: Task) -> list[Grant]:
        return _install_grants(self.argv(task)[0], "agent") if task.command else []


class ClaudeCodeAgent(Agent):
    """Claude Code in headless mode.

    Hydra enforces the boundaries itself, so Claude Code's own per-tool
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


AGENTS: dict[str, type[Agent]] = {"command": CommandAgent, "claude-code": ClaudeCodeAgent}


def get_agent(name: str) -> Agent:
    try:
        return AGENTS[name]()
    except KeyError:
        raise ValueError(f"unknown agent {name!r}; supported: {', '.join(AGENTS)}") from None


def runtime_paths() -> list[Path]:
    """Hydra's own interpreter and package, needed inside the sandbox for probes and the network bridge."""
    out = {Path(__file__).resolve().parent, Path(sys.executable).resolve().parent,
           Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve()}
    return sorted(out)
