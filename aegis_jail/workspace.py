# SPDX-License-Identifier: AGPL-3.0-or-later
"""Working copies: the agent never touches the real project directly.

Aegis copies the project into the run directory, the agent works there, and
afterwards the user reviews the diff and applies (or discards) it.

Hardening (each item closes a real attack path):

* credential files in the project (.env, keys, tfstate, files containing
  tokens) are left out of the copy, and never deleted by `apply`;
* tokens in `.git/config` remote URLs and credential helpers are stripped from
  the copy;
* `apply` refuses to write through symlinks or outside the project, and
  refuses files that changed in the project meanwhile;
* changes that would run code *outside* the sandbox later (agent configs and
  hooks, MCP server lists, CI workflows, git hooks, package scripts, editor
  tasks, executables) or that smuggle invisible instructions / secrets are
  flagged as risky and need explicit approval;
* projects that are (or contain) the home directory are refused, and copies
  are size-capped.
"""

from __future__ import annotations

import difflib
import fnmatch
import hashlib
import json
import os
import re
import shutil
import stat
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from aegis_jail import paths, secretscan, textsafe

IGNORED_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".pytest_cache",
                ".mypy_cache", ".tox", ".aegis-tmp"}
MAX_FILES = int(os.environ.get("AEGIS_MAX_FILES", "300000"))
MAX_BYTES = int(os.environ.get("AEGIS_MAX_BYTES", str(8 * 1024 ** 3)))

# Files that are executed or obeyed later, *outside* the sandbox.
RISKY_GLOBS: list[tuple[str, str]] = [
    (".claude/*", "Claude Code settings/hooks run commands on your machine"),
    ("CLAUDE.md", "instructions every future agent session will follow"),
    ("AGENTS.md", "instructions every future agent session will follow"),
    ("GEMINI.md", "instructions every future agent session will follow"),
    (".cursorrules", "instructions every future agent session will follow"),
    (".cursor/*", "Cursor rules / MCP config"),
    (".windsurfrules", "instructions every future agent session will follow"),
    (".github/copilot-instructions.md", "instructions for Copilot"),
    (".mcp.json", "adds MCP servers that start automatically"),
    ("*mcp*.json", "may add MCP servers"),
    (".vscode/*", "editor tasks/settings can run commands"),
    (".idea/*", "IDE run configurations"),
    (".github/workflows/*", "CI workflows run with repository secrets"),
    (".gitlab-ci.yml", "CI pipeline"),
    (".husky/*", "git hooks"),
    (".pre-commit-config.yaml", "git hooks"),
    (".gitattributes", "can enable filters that run commands"),
    (".gitmodules", "submodule URLs"),
    (".envrc", "direnv runs it when you cd into the project"),
    (".npmrc", "registry / token configuration"),
    ("setup.py", "runs on install"),
    ("conftest.py", "runs during tests"),
    ("Makefile", "build commands"),
    ("Dockerfile", "build commands"),
    ("docker-compose*.y*ml", "container configuration"),
    ("*.sh", "shell script"), ("*.ps1", "PowerShell script"), ("*.bat", "batch script"), ("*.cmd", "batch script"),
]


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _fingerprint(p: Path) -> str:
    st = p.stat()
    return _sha(p) + (":x" if st.st_mode & stat.S_IXUSR else "")


class UnsafeProject(ValueError):
    pass


def check_project_root(project: Path) -> None:
    """Refuse roots that would copy the user's credentials into the sandbox."""
    project = project.resolve()
    home = paths.user_home()
    if project == Path(project.anchor) or project == home or home.is_relative_to(project):
        raise UnsafeProject(f"refusing to use {project} as a project: it is (or contains) your home directory")
    for s in paths.SECRET_PATHS:
        sp = paths.expand(s)
        if sp.resolve().is_relative_to(project) if sp.exists() else False:
            raise UnsafeProject(f"refusing to use {project} as a project: it contains {sp}")
    if project.is_relative_to(paths.aegis_home()):
        raise UnsafeProject("refusing to use Aegis's own state directory as a project")


def _walk(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root)
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS and not (rel_dir == Path(".") and d == ".aegis")]
        for fn in filenames:
            yield rel_dir, Path(dirpath) / fn


def snapshot(root: Path, hidden: set[str] | None = None) -> dict[str, str]:
    out: dict[str, str] = {}
    root = root.resolve()
    for rel_dir, p in _walk(root):
        rel = (rel_dir / p.name).as_posix()
        if (hidden and rel in hidden) or p.is_symlink() or not p.is_file():
            continue
        out[rel] = _fingerprint(p)
    return out


def _exposed(rel: str, expose: list[str]) -> bool:
    return any(fnmatch.fnmatch(rel, g) or fnmatch.fnmatch(PurePosixPath(rel).name, g) for g in expose)


def find_secret_files(project: Path, expose: list[str] | None = None) -> dict[str, list[str]]:
    """{relative path: reasons} for files in the project that hold credentials."""
    expose = expose or []
    found: dict[str, list[str]] = {}
    count = 0
    total = 0
    for rel_dir, p in _walk(project):
        rel = (rel_dir / p.name).as_posix()
        count += 1
        try:
            if p.is_symlink() or not p.is_file():
                continue
            size = p.stat().st_size
        except OSError:
            continue
        total += size
        if count > MAX_FILES or total > MAX_BYTES:
            raise UnsafeProject(f"project is too large to copy ({count} files / {total >> 20} MiB so far); "
                                f"set AEGIS_MAX_FILES / AEGIS_MAX_BYTES to raise the limit")
        if _exposed(rel, expose):
            continue
        reasons = []
        if secretscan.is_secret_filename(rel):
            reasons.append("credential file name")
        if size <= 1_000_000:
            try:
                with open(p, "rb") as f:
                    reasons += secretscan.file_has_secret(f.read())
            except OSError:
                pass
        if reasons:
            found[rel] = reasons
    return found


def _sanitize_git_config(dest: Path) -> list[str]:
    cfg = dest / ".git" / "config"
    if not cfg.is_file():
        return []
    text = cfg.read_text(encoding="utf-8", errors="replace")
    notes = []
    new = re.sub(r"(\w+://)[^/@\s]+@", r"\1", text)
    if new != text:
        notes.append("removed credentials from git remote URLs")
    lines = [ln for ln in new.splitlines() if not re.match(r"\s*helper\s*=", ln)]
    if len(lines) != len(new.splitlines()):
        notes.append("removed git credential helpers")
    cfg.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return notes


@dataclass
class CopyResult:
    baseline: dict[str, str]
    hidden: dict[str, list[str]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def create(project: Path, dest: Path, expose: list[str] | None = None) -> CopyResult:
    """Copy project to dest (minus credential files) and return the baseline snapshot."""
    project = project.resolve()
    check_project_root(project)
    hidden = find_secret_files(project, expose)

    def ignore(d: str, names: list[str]) -> set[str]:
        rel_dir = Path(d).resolve().relative_to(project)
        skip = {n for n in names if (rel_dir / n).as_posix() in hidden}
        if rel_dir == Path("."):
            skip |= {".aegis"} & set(names)
        return skip

    shutil.copytree(project, dest, symlinks=True, ignore=ignore)
    notes = _sanitize_git_config(dest)
    if hidden:
        notes.append(f"hid {len(hidden)} credential file(s) from the agent: " + ", ".join(sorted(hidden)[:10]))
    return CopyResult(baseline=snapshot(project, set(hidden)), hidden=hidden, notes=notes)


@dataclass
class Change:
    path: str
    kind: str  # added | modified | deleted
    risks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {"path": self.path, "kind": self.kind}
        if self.risks:
            d["risks"] = self.risks
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Change":
        return cls(d["path"], d["kind"], list(d.get("risks", [])))


def _json_key(data: bytes | None, key: str):
    try:
        return json.loads(data or b"{}").get(key)
    except (ValueError, AttributeError):
        return "<unparseable>"


def assess(rel: str, kind: str, before: str | None, after: str | None, data: bytes | None,
           old_data: bytes | None = None) -> list[str]:
    """Why applying this change could hurt you outside the sandbox."""
    risks = []
    if PurePosixPath(rel).name == "package.json" and kind != "deleted":
        if _json_key(data, "scripts") != _json_key(old_data, "scripts"):
            risks.append("changes npm scripts (they run on install/test)")
    name = PurePosixPath(rel).name
    for g, why in RISKY_GLOBS:
        if fnmatch.fnmatch(rel, g) or ("/" not in g and fnmatch.fnmatch(name, g)):
            risks.append(why)
            break
    if after and after.endswith(":x") and not (before or "").endswith(":x"):
        risks.append("made executable")
    if data is not None and kind != "deleted":
        if b"\0" in data[:8192]:
            if data[:4] in (b"\x7fELF", b"MZ\x90\x00") or data[:4] in (b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe"):
                risks.append("native executable")
        else:
            text = data[:1_000_000].decode("utf-8", "replace")
            inv = textsafe.invisible_chars(text)
            if inv:
                risks.append(f"contains {len(inv)} invisible/bidi character(s): {inv[0][1]}")
            sec = secretscan.find_secrets(text)
            if sec:
                risks.append("contains credentials: " + ", ".join(sec))
            inj = textsafe.injection_markers(text) if len(text) < 300_000 else []
            if inj:
                risks.append("possible prompt injection: " + "; ".join(inj[:3]))
    return risks


def _read(p: Path, limit: int = 1_000_001) -> bytes | None:
    try:
        with open(p, "rb") as f:
            return f.read(limit)
    except OSError:
        return None


def changes(baseline: dict[str, str], workspace: Path, project: Path | None = None) -> list[Change]:
    now = snapshot(workspace)
    out: list[Change] = []
    for path in sorted(set(baseline) | set(now)):
        if path not in now:
            kind = "deleted"
        elif path not in baseline:
            kind = "added"
        elif baseline[path] != now[path]:
            kind = "modified"
        else:
            continue
        data = _read(workspace / path) if kind != "deleted" else None
        old = _read(project / path) if (project is not None and kind == "modified") else None
        out.append(Change(path, kind, assess(path, kind, baseline.get(path), now.get(path), data, old)))
    return out


def unified_diff(project: Path, workspace: Path, chs: list[Change], max_lines: int = 4000) -> str:
    """Diff of agent-controlled content - always sanitised for the terminal."""
    out: list[str] = []
    for c in chs:
        if c.risks:
            out.append(f"!! RISKY {c.path}: " + "; ".join(c.risks) + "\n")
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
    return textsafe.for_terminal("".join(out))


class ApplyConflict(RuntimeError):
    pass


class RiskyChanges(RuntimeError):
    pass


def _safe_target(project: Path, rel: str) -> Path:
    """Resolve rel inside project without following any symlink on the way."""
    if PurePosixPath(rel).is_absolute() or ".." in PurePosixPath(rel).parts:
        raise ApplyConflict(f"unsafe path: {rel}")
    cur = project
    for part in PurePosixPath(rel).parts:
        cur = cur / part
        if cur.is_symlink():
            raise ApplyConflict(f"refusing to write through a symlink: {rel}")
    if not cur.resolve().is_relative_to(project.resolve()) and cur.exists():
        raise ApplyConflict(f"path escapes the project: {rel}")
    return cur


def apply(project: Path, workspace: Path, baseline: dict[str, str], chs: list[Change],
          allow_risky: bool = False) -> list[str]:
    project = project.resolve()
    risky = [c for c in chs if c.risks]
    if risky and not allow_risky:
        raise RiskyChanges("these changes could run code or steer agents outside the sandbox:\n" +
                           "\n".join(f"  {c.path}: {'; '.join(c.risks)}" for c in risky) +
                           "\nreview them (aegis diff) and re-run with --allow-risky to apply anyway")
    conflicts = []
    targets = {}
    for c in chs:
        target = _safe_target(project, c.path)
        targets[c.path] = target
        expected = baseline.get(c.path)
        current = _fingerprint(target) if target.is_file() and not target.is_symlink() else None
        if current != expected:
            conflicts.append(c.path)
    if conflicts:
        raise ApplyConflict("files changed in the project since the run started: " + ", ".join(conflicts))
    applied = []
    for c in chs:
        target = targets[c.path]
        src = workspace / c.path
        if c.kind == "deleted":
            target.unlink()
        else:
            if src.is_symlink():
                raise ApplyConflict(f"refusing to apply a symlink: {c.path}")
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(f".{target.name}.aegis-tmp")
            shutil.copyfile(src, tmp)
            os.chmod(tmp, stat.S_IMODE(src.stat().st_mode))
            os.replace(tmp, target)
        applied.append(c.path)
    return applied


def save_baseline(path: Path, snap: dict[str, str]) -> None:
    path.write_text(json.dumps(snap), encoding="utf-8")


def load_baseline(path: Path) -> dict[str, str]:
    return json.loads(path.read_text(encoding="utf-8"))
