"""Claude Code PreToolUse guard: keep credentials out of reach even outside the sandbox.

Configured by the Aegis plugin (hooks/hooks.json). Claude Code sends the
pending tool call as JSON on stdin; exit code 2 blocks it and the stderr
message is shown to the model.

This is a best-effort guard for *unsandboxed* sessions (it matches paths in
tool arguments and shell commands). Real enforcement is `aegis run` /
`aegis wrap`, where the operating system blocks access.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from aegis_jail import paths

FILE_TOOLS = {"Read", "Edit", "Write", "MultiEdit", "NotebookEdit", "NotebookRead", "Grep", "Glob", "LS"}
SECRET_WORDS = [
    r"\.ssh/", r"\.ssh\b", r"id_rsa", r"id_ed25519", r"id_ecdsa", r"\.aws/credentials", r"\.aws\b",
    r"\.gnupg", r"\.kube/config", r"\.docker/config\.json", r"\.netrc", r"\.npmrc", r"\.pypirc",
    r"\.git-credentials", r"\.password-store", r"Library/Keychains", r"\.config/gcloud", r"\.config/gh\b",
    r"\.azure\b", r"\.aegis/canary",
]
_SECRET_RE = re.compile("|".join(SECRET_WORDS), re.I)


def _secret_paths() -> list[Path]:
    return [paths.expand(s) for s in paths.SECRET_PATHS] + [paths.aegis_home() / "canary"]


def _is_secret_path(value: str, cwd: Path) -> bool:
    try:
        p = Path(os.path.expanduser(value))
        p = (p if p.is_absolute() else cwd / p).resolve()
    except (OSError, RuntimeError, ValueError):
        return False
    s = str(p).lower()
    return any(s == str(sp).lower() or s.startswith(str(sp).lower() + os.sep) for sp in _secret_paths())


def check(event: dict) -> str | None:
    """Return a reason to block, or None."""
    tool = event.get("tool_name", "")
    args = event.get("tool_input") or {}
    cwd = Path(event.get("cwd") or os.getcwd())
    if tool in FILE_TOOLS:
        for key in ("file_path", "path", "notebook_path", "pattern"):
            v = args.get(key)
            if isinstance(v, str) and v and (_is_secret_path(v, cwd) or (key == "pattern" and _SECRET_RE.search(v))):
                return f"Aegis: {tool} on '{v}' touches a credential store; access is blocked."
    if tool == "Bash":
        cmd = str(args.get("command", ""))
        m = _SECRET_RE.search(cmd)
        if m:
            return (f"Aegis: this command references a credential location ('{m.group(0)}'), which is blocked. "
                    "If the task really needs it, ask the user to allow it explicitly.")
    return None


def main(stdin=None) -> int:
    if os.environ.get("AEGIS_HOOK_DISABLE") == "1":
        return 0
    try:
        event = json.load(stdin or sys.stdin)
    except ValueError:
        return 0
    reason = check(event if isinstance(event, dict) else {})
    if reason:
        print(reason, file=sys.stderr)
        return 2
    return 0
