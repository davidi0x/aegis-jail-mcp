"""Well-known locations used by Hydra."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path


def user_home() -> Path:
    return Path.home().resolve()


def hydra_home() -> Path:
    """Per-user Hydra state (runs, canaries). Never shared with agents."""
    env = os.environ.get("HYDRA_HOME")
    root = Path(env).expanduser() if env else user_home() / ".hydra"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def project_key(project: Path) -> str:
    project = project.resolve()
    digest = hashlib.sha256(str(project).encode()).hexdigest()[:8]
    return f"{project.name}-{digest}"


def runs_dir(project: Path) -> Path:
    d = hydra_home() / "runs" / project_key(project)
    d.mkdir(parents=True, exist_ok=True)
    return d


def canary_dir() -> Path:
    """A directory with a fake secret used by boundary probes."""
    d = hydra_home() / "canary"
    d.mkdir(parents=True, exist_ok=True)
    secret = d / "secret.txt"
    if not secret.exists():
        secret.write_text("HYDRA-CANARY-SECRET: if an agent can read this, the boundary failed\n")
    return d


def project_config_dir(project: Path) -> Path:
    """Per-project, shareable configuration (profiles, tasks). Safe to commit."""
    return project.resolve() / ".hydra"


def expand(path: str, home: Path | None = None) -> Path:
    home = home or user_home()
    if path == "~":
        return home
    if path.startswith("~/") or path.startswith("~\\"):
        return home / path[2:]
    return Path(os.path.expandvars(path)).expanduser()


# Paths that hold credentials. They stay unreadable even when a broader read
# grant (e.g. the whole home directory) is given, unless granted explicitly.
SECRET_PATHS = [
    "~/.ssh",
    "~/.aws",
    "~/.azure",
    "~/.gnupg",
    "~/.config/gcloud",
    "~/.config/gh",
    "~/.kube",
    "~/.docker/config.json",
    "~/.netrc",
    "~/.npmrc",
    "~/.pypirc",
    "~/.git-credentials",
    "~/.password-store",
    "~/Library/Keychains",
]
