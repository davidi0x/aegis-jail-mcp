"""Access profiles: what an agent session may read, write and connect to.

A profile is a list of *grants* on top of a fixed, deny-by-default base:

* the whole user home directory is unreadable,
* credential stores (SECRET_PATHS) are unreadable even if a broader grant
  covers them, unless granted explicitly,
* the original project directory is unreadable - the agent works on a copy,
* nothing outside the working copy and a private temp dir is writable,
* there is no network access,
* environment variables are not inherited except a small safe set.

Grants are individually removable, which is what `hydra optimize` relies on.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from hydra_guard import paths

KINDS = ("read", "write", "net", "env")
PHASES = ("setup", "task", "all")

# Environment variables that are always passed through.
SAFE_ENV = [
    "PATH", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "USER", "USERNAME", "LOGNAME",
    "SHELL", "TZ", "COLORTERM", "SYSTEMROOT", "SystemRoot", "WINDIR", "COMSPEC",
    "PATHEXT", "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS", "OS",
    "ProgramFiles", "ProgramFiles(x86)", "ProgramData", "CommonProgramFiles",
    # Windows needs these to start processes inside an AppContainer (none are secrets;
    # the folders they point to stay inaccessible unless granted).
    "SystemDrive", "LOCALAPPDATA", "APPDATA", "HOMEDRIVE", "HOMEPATH", "ALLUSERSPROFILE",
    "PUBLIC", "COMPUTERNAME", "USERDOMAIN", "ProgramW6432", "CommonProgramFiles(x86)",
    "CommonProgramW6432", "DriverData",
]


@dataclass
class Grant:
    id: str
    kind: str
    path: str | None = None
    domains: list[str] | None = None
    names: list[str] | None = None
    phase: str = "all"
    locked: bool = False
    note: str = ""

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"grant {self.id!r}: unknown kind {self.kind!r}")
        if self.phase not in PHASES:
            raise ValueError(f"grant {self.id!r}: unknown phase {self.phase!r}")
        if self.kind in ("read", "write") and not self.path:
            raise ValueError(f"grant {self.id!r}: {self.kind} grant needs a path")
        if self.kind == "net" and not self.domains:
            raise ValueError(f"grant {self.id!r}: net grant needs domains")
        if self.kind == "env" and not self.names:
            raise ValueError(f"grant {self.id!r}: env grant needs names")

    def applies_to(self, phase: str) -> bool:
        return self.phase == "all" or self.phase == phase

    def describe(self) -> str:
        if self.kind == "read":
            return f"read {self.path}"
        if self.kind == "write":
            return f"write {self.path}"
        if self.kind == "net":
            where = "" if self.phase == "all" else f" ({self.phase} phase)"
            doms = "any host" if "*" in (self.domains or []) else ", ".join(self.domains or [])
            return f"network to {doms}{where}"
        return f"env vars {', '.join(self.names or [])}"

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v not in (None, False, "") or k in ("id", "kind")}


@dataclass
class Profile:
    name: str
    agent: str
    grants: list[Grant] = field(default_factory=list)
    verified: dict[str, Any] | None = None

    # ---- serialisation -------------------------------------------------
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Profile":
        if data.get("hydra") != 1:
            raise ValueError("not a Hydra v1 profile (missing \"hydra\": 1)")
        grants = [Grant(**g) for g in data.get("grants", [])]
        ids = [g.id for g in grants]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate grant ids in profile")
        return cls(name=data["name"], agent=data["agent"], grants=grants, verified=data.get("verified"))

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"hydra": 1, "name": self.name, "agent": self.agent,
                               "grants": [g.to_dict() for g in self.grants]}
        if self.verified:
            out["verified"] = self.verified
        return out

    @classmethod
    def load(cls, path: Path) -> "Profile":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")

    # ---- manipulation --------------------------------------------------
    def without(self, grant_id: str) -> "Profile":
        return Profile(self.name, self.agent, [g for g in self.grants if g.id != grant_id], None)

    def merged(self, extra: list[Grant]) -> "Profile":
        have = {g.id for g in self.grants}
        return Profile(self.name, self.agent, self.grants + [g for g in extra if g.id not in have], self.verified)

    # ---- compilation ---------------------------------------------------
    def compile(self, phase: str, *, project: Path, workspace: Path, tmp: Path,
                runtime_paths: list[Path] | None = None,
                host_env: dict[str, str] | None = None) -> "SandboxSpec":
        from hydra_guard.sandbox.base import SandboxSpec

        home = paths.user_home()
        host_env = dict(os.environ if host_env is None else host_env)
        rules: list[tuple[str, Path]] = [("deny", home)]
        # Hydra's own runtime (interpreter, package) must stay readable.
        for rp in runtime_paths or []:
            rules.append(("read", rp.resolve()))
        granted_paths: list[Path] = []
        for g in self.grants:
            if g.kind in ("read", "write") and g.applies_to(phase):
                p = paths.expand(g.path or "", home).resolve()
                rules.append((g.kind, p))
                granted_paths.append(p)
        for s in paths.SECRET_PATHS:
            sp = paths.expand(s, home)
            explicitly = any(_is_within(gp, sp) for gp in granted_paths)
            if not explicitly:
                rules.append(("deny", sp))
        rules.append(("deny", project.resolve()))
        rules.append(("deny", paths.hydra_home()))
        rules.append(("write", workspace.resolve()))
        rules.append(("write", tmp.resolve()))

        domains: list[str] = []
        for g in self.grants:
            if g.kind == "net" and g.applies_to(phase):
                domains.extend(g.domains or [])
        network: None | str | list[str]
        if "*" in domains:
            network = "all"
        elif domains:
            network = sorted(set(d.lower() for d in domains))
        else:
            network = None

        env_names = list(SAFE_ENV)
        for g in self.grants:
            if g.kind == "env" and g.applies_to(phase):
                env_names.extend(g.names or [])
        env = {k: host_env[k] for k in env_names if k in host_env}
        env["HOME"] = str(home)
        if os.name == "nt":
            env["USERPROFILE"] = str(home)
        env["TMPDIR"] = env["TMP"] = env["TEMP"] = str(tmp.resolve())
        env["HYDRA_SANDBOX"] = "1"
        return SandboxSpec(fs_rules=rules, network=network, env=env, cwd=workspace.resolve(), tmp=tmp.resolve())


# macOS and Windows file systems are case-insensitive by default; the
# sandboxes there match paths case-insensitively too.
CASE_INSENSITIVE = sys.platform in ("darwin", "win32")


def _norm(p: Path) -> Path:
    return Path(str(p).lower()) if CASE_INSENSITIVE else p


def _is_within(child: Path, parent: Path) -> bool:
    try:
        _norm(child).relative_to(_norm(parent))
        return True
    except ValueError:
        return False


def baseline_profile(agent_name: str, agent_grants: list[Grant]) -> Profile:
    """A deliberately broad starting point - roughly 'what people give agents today'.

    `hydra optimize` starts here and removes whatever the task does not need.
    """
    secrets = [Grant(id=f"secret:{Path(s).name.lstrip('.') or s}", kind="read", path=s,
                     note="credential store") for s in paths.SECRET_PATHS
               if paths.expand(s).exists()]
    grants = [
        Grant(id="home-read", kind="read", path="~", note="read the whole home directory (other projects, dotfiles)"),
        *secrets,
        Grant(id="net-setup-any", kind="net", domains=["*"], phase="setup", note="internet while installing dependencies"),
        Grant(id="net-task-any", kind="net", domains=["*"], phase="task", note="internet while the agent works"),
        Grant(id="env-all-ish", kind="env", names=_interesting_env(), note="credentials found in environment variables"),
    ]
    prof = Profile(name="baseline", agent=agent_name, grants=[g for g in grants if g.kind != "env" or g.names])
    return prof.merged(agent_grants)


def _interesting_env() -> list[str]:
    markers = ("TOKEN", "KEY", "SECRET", "PASSWORD", "CREDENTIAL", "AWS_", "GITHUB", "OPENAI", "ANTHROPIC")
    return sorted(k for k in os.environ if any(m in k.upper() for m in markers))
