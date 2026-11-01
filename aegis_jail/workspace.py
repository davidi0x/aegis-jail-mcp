"""Working copies: the agent never touches the real project directly.

Aegis copies the project into the run directory, the agent works there, and
afterwards the user reviews the diff and applies (or discards) it. Applying
refuses to overwrite files that changed in the real project meanwhile.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

IGNORED_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".pytest_cache",
                ".mypy_cache", ".tox", ".aegis-tmp"}


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    root = root.resolve()
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root)
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS and not (rel_dir == Path(".") and d == ".aegis")]
        for fn in filenames:
            p = Path(dirpath) / fn
            if p.is_symlink() or not p.is_file():
                continue
            out[(rel_dir / fn).as_posix()] = _sha(p)
    return out


def create(project: Path, dest: Path) -> dict[str, str]:
    """Copy project to dest and return the baseline snapshot."""
    project = project.resolve()

    def ignore(d: str, names: list[str]) -> set[str]:
        return {".aegis"} & set(names) if Path(d).resolve() == project else set()

    shutil.copytree(project, dest, symlinks=True, ignore=ignore)
    snap = snapshot(project)
    return snap


@dataclass
class Change:
    path: str
    kind: str  # added | modified | deleted

    def to_dict(self) -> dict:
        return {"path": self.path, "kind": self.kind}


def changes(baseline: dict[str, str], workspace: Path) -> list[Change]:
    now = snapshot(workspace)
    out: list[Change] = []
    for path in sorted(set(baseline) | set(now)):
        if path not in now:
            out.append(Change(path, "deleted"))
        elif path not in baseline:
            out.append(Change(path, "added"))
        elif baseline[path] != now[path]:
            out.append(Change(path, "modified"))
    return out


def unified_diff(project: Path, workspace: Path, chs: list[Change], max_lines: int = 4000) -> str:
    out: list[str] = []
    for c in chs:
        a = project / c.path
        b = workspace / c.path
        try:
            old = a.read_text(encoding="utf-8").splitlines(keepends=True) if c.kind != "added" else []
            new = b.read_text(encoding="utf-8").splitlines(keepends=True) if c.kind != "deleted" else []
        except (UnicodeDecodeError, OSError):
            out.append(f"Binary or unreadable file {c.kind}: {c.path}\n")
            continue
        out.extend(difflib.unified_diff(old, new, f"a/{c.path}", f"b/{c.path}"))
        if len(out) > max_lines:
            out.append("... diff truncated ...\n")
            break
    return "".join(out)


class ApplyConflict(RuntimeError):
    pass


def apply(project: Path, workspace: Path, baseline: dict[str, str], chs: list[Change]) -> list[str]:
    conflicts = []
    for c in chs:
        target = project / c.path
        expected = baseline.get(c.path)
        current = _sha(target) if target.is_file() else None
        if current != expected:
            conflicts.append(c.path)
    if conflicts:
        raise ApplyConflict("files changed in the project since the run started: " + ", ".join(conflicts))
    applied = []
    for c in chs:
        target = project / c.path
        if c.kind == "deleted":
            target.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(workspace / c.path, target)
        applied.append(c.path)
    return applied


def save_baseline(path: Path, snap: dict[str, str]) -> None:
    path.write_text(json.dumps(snap), encoding="utf-8")


def load_baseline(path: Path) -> dict[str, str]:
    return json.loads(path.read_text(encoding="utf-8"))
