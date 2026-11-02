# SPDX-License-Identifier: AGPL-3.0-or-later
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

from aegis_jail import paths, secretscan

FILE_TOOLS = {"Read", "Edit", "Write", "MultiEdit", "NotebookEdit", "NotebookRead", "Grep", "Glob", "LS"}
# (label, pattern). Only the label is ever shown to the user: a message is built from these constants,
# never from the text that matched, so no part of a command or file ends up in the output.
BLOCKED_LOCATIONS = [
    ("SSH keys", r"\.ssh/"), ("SSH keys", r"\.ssh\b"), ("SSH keys", r"id_rsa"), ("SSH keys", r"id_ed25519"),
    ("SSH keys", r"id_ecdsa"), ("AWS credentials", r"\.aws/credentials"), ("AWS credentials", r"\.aws\b"),
    ("GnuPG keys", r"\.gnupg"), ("Kubernetes config", r"\.kube/config"),
    ("Docker credentials", r"\.docker/config\.json"), ("netrc login file", r"\.netrc"),
    ("npm login file", r"\.npmrc"), ("PyPI login file", r"\.pypirc"), ("git credentials", r"\.git-credentials"),
    ("password store", r"\.password-store"), ("macOS keychain", r"Library/Keychains"),
    ("Google Cloud config", r"\.config/gcloud"), ("GitHub CLI config", r"\.config/gh\b"),
    ("Azure config", r"\.azure\b"), ("Aegis canary", r"\.aegis/canary"),
    ("process environment", r"/proc/[^/\s]+/environ"),
    ("keychain command", r"security\s+find-(generic|internet)-password"),
    ("kernel keyring", r"\bkeyctl\s+(print|read|pipe)"), ("desktop keyring", r"secret-tool\s+lookup"),
    ("GitHub CLI login", r"gh\s+auth\s+token"),
]
_LOCATION_RES = [(label, re.compile(rx, re.I)) for label, rx in BLOCKED_LOCATIONS]
# The kinds of credential `secretscan` can find, as constants we are allowed to print.
_KIND_LABEL = {name: name for name, _ in secretscan.PATTERNS}


def normalize_command(cmd: str) -> str:
    """Undo common shell obfuscation so ~/.s'sh', ~/".ssh", $HOME/.ssh and ${HOME}/.ssh all match."""
    s = cmd.replace("\\\n", "")
    s = re.sub(r"""['"\\]""", "", s)
    s = re.sub(r"\$\{?HOME\}?|\$\{?USERPROFILE\}?|%USERPROFILE%", "~", s)
    s = s.replace(str(Path.home()), "~")
    return s


def _blocked_label(text: str) -> str | None:
    """The label of the first protected location mentioned in `text`, or None."""
    for label, rx in _LOCATION_RES:
        if rx.search(text):
            return label
    return None


def _protected_paths() -> list[Path]:
    return [paths.expand(s) for s in paths.SECRET_PATHS] + [paths.aegis_home() / "canary"]


def _is_protected_path(value: str, cwd: Path) -> bool:
    try:
        p = Path(os.path.expanduser(value))
        p = (p if p.is_absolute() else cwd / p).resolve()
    except (OSError, RuntimeError, ValueError):
        return False
    s = str(p).lower()
    return any(s == str(sp).lower() or s.startswith(str(sp).lower() + os.sep) for sp in _protected_paths())


def check(event: dict) -> str | None:
    """Return a reason to block, or None."""
    tool = event.get("tool_name", "")
    args = event.get("tool_input") or {}
    cwd = Path(event.get("cwd") or os.getcwd())
    if tool in FILE_TOOLS:
        for key in ("file_path", "path", "notebook_path", "pattern"):
            v = args.get(key)
            if not (isinstance(v, str) and v):
                continue
            if _is_protected_path(v, cwd):
                return f"Aegis: {tool} on '{v}' touches a credential store; access is blocked."
            label = _blocked_label(v) if key == "pattern" else None
            if label:
                return f"Aegis: {tool} on '{v}' searches for a credential location ({label}); access is blocked."
    if tool == "Bash":
        cmd = str(args.get("command", ""))
        label = _blocked_label(cmd) or _blocked_label(normalize_command(cmd))
        if label:
            return (f"Aegis: this command references a credential location ({label}), which is blocked. "
                    "If the task really needs it, ask the user to allow it explicitly.")
    # Data-loss prevention: nothing that leaves the machine may carry a credential.
    outbound = tool == "Bash" or tool.startswith("mcp__") or tool in ("WebFetch", "WebSearch", "Task")
    if outbound:
        kinds = secretscan.find_secrets(json.dumps(args, ensure_ascii=False))
        if kinds:
            shown = ", ".join(sorted({_KIND_LABEL.get(k, "credential") for k in kinds}))
            return (f"Aegis: this {tool} call contains a credential ({shown}); sending it to "
                    "tools, commands or websites is blocked. Use an environment variable or ask the user.")
    return None


def autopilot_context(only_new: bool = False) -> str | None:
    """Open Autopilot events, phrased for the agent. With only_new, just those not announced yet."""
    try:
        from aegis_jail import watch
        events = watch.open_events("medium")
        seen_p = watch.watch_dir() / "announced.json"
        seen = set(json.loads(seen_p.read_text(encoding="utf-8"))) if seen_p.exists() else set()
    except (OSError, ValueError):
        return None
    if only_new:
        events = [e for e in events if e["id"] not in seen]
    if not events:
        return None
    seen.update(e["id"] for e in events)
    try:
        seen_p.write_text(json.dumps(sorted(seen)[-2000:]), encoding="utf-8")
    except OSError:
        pass
    lines = [f"- [{e['severity']}] {e['title']} (event {e['id']})" for e in events[:10]]
    more = f"\n- ...and {len(events) - 10} more" if len(events) > 10 else ""
    return ("Aegis Autopilot has open security events on this machine:\n" + "\n".join(lines) + more +
            "\nTell the user about them briefly. Use the Aegis MCP tools to help: aegis_events for details, "
            "aegis_jail_mcp_server to contain an MCP server that runs with full user rights, aegis_resolve once "
            "something is handled. Never re-approve a changed tool or apply a run without the user's explicit yes.")


def context_hook(event_name: str, only_new: bool) -> int:
    """SessionStart / UserPromptSubmit: hand open Autopilot events to the agent as context."""
    if os.environ.get("AEGIS_HOOK_DISABLE") == "1":
        return 0
    try:
        json.load(sys.stdin)
    except ValueError:
        pass
    text = autopilot_context(only_new=only_new)
    if text:
        sys.stdout.write(json.dumps({"hookSpecificOutput": {"hookEventName": event_name, "additionalContext": text}}))
    return 0


def main(stdin=None) -> int:
    if os.environ.get("AEGIS_HOOK_DISABLE") == "1":
        return 0
    try:
        event = json.load(stdin or sys.stdin)
    except ValueError:
        return 0
    verdict = check(event if isinstance(event, dict) else {})
    if verdict:
        sys.stderr.write(verdict + "\n")  # shown to the model; built only from constant labels (see above)
        return 2
    return 0
