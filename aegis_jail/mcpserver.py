"""Aegis as an MCP server: lets an AI client run commands in the Aegis sandbox.

Start with `aegis mcp-server` (stdio). Works with Claude Code, Claude Desktop,
Cursor and any MCP client. No third-party dependencies: the small subset of
MCP needed for tools is implemented here (newline-delimited JSON-RPC 2.0).
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import traceback
from pathlib import Path
from typing import Any, Callable

from aegis_jail import __version__, paths, workspace

PROTOCOL_VERSIONS = ["2025-06-18", "2025-03-26", "2024-11-05"]

_PROJECT = {"type": "string", "description": "Absolute path of the project directory (default: server's cwd)."}
_PROFILE = {"type": "string", "description": "Aegis profile name from .aegis/profiles (default: 'default', "
                                             "the strict base: no home dir, no credentials, no network)."}
_RUN = {"type": "string", "description": "Run id (or 'last')."}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "aegis_run",
        "description": ("Run a shell command inside the Aegis sandbox on a fresh *copy* of the project. The command "
                        "cannot read the home directory or credentials, cannot write outside the copy and has no "
                        "network unless the profile allows it. Returns exit code, output, changed files and blocked "
                        "operations. Changes stay in the copy until aegis_apply."),
        "inputSchema": {"type": "object", "properties": {
            "command": {"type": "string", "description": "Shell command, e.g. 'npm test' or 'python script.py'."},
            "project": _PROJECT, "profile": _PROFILE,
            "allow_hosts": {"type": "array", "items": {"type": "string"},
                            "description": "Extra hosts this run may reach (e.g. ['registry.npmjs.org'])."},
            "timeout": {"type": "number", "description": "Seconds (default 600)."}},
            "required": ["command"]},
        "annotations": {"title": "Run in sandbox", "openWorldHint": False},
    },
    {
        "name": "aegis_probe",
        "description": "Test in practice that a profile's boundaries hold (secrets, writes, network, child processes).",
        "inputSchema": {"type": "object", "properties": {"project": _PROJECT, "profile": _PROFILE}},
        "annotations": {"title": "Probe boundaries", "readOnlyHint": True},
    },
    {
        "name": "aegis_runs",
        "description": "List recent Aegis runs of a project.",
        "inputSchema": {"type": "object", "properties": {"project": _PROJECT}},
        "annotations": {"title": "List runs", "readOnlyHint": True},
    },
    {
        "name": "aegis_diff",
        "description": "Show the unified diff of the files a run changed in its working copy.",
        "inputSchema": {"type": "object", "properties": {"project": _PROJECT, "run": _RUN}},
        "annotations": {"title": "Show changes", "readOnlyHint": True},
    },
    {
        "name": "aegis_apply",
        "description": ("Copy a run's changes into the real project (refuses if those files changed meanwhile). "
                        "Only call this after the user has reviewed the diff and agreed."),
        "inputSchema": {"type": "object", "properties": {"project": _PROJECT, "run": _RUN}, "required": ["run"]},
        "annotations": {"title": "Apply changes", "destructiveHint": True},
    },
    {
        "name": "aegis_discard",
        "description": "Throw away a run's working copy.",
        "inputSchema": {"type": "object", "properties": {"project": _PROJECT, "run": _RUN}, "required": ["run"]},
        "annotations": {"title": "Discard changes"},
    },
    {
        "name": "aegis_profiles",
        "description": "List the project's Aegis profiles and what each one allows.",
        "inputSchema": {"type": "object", "properties": {"project": _PROJECT}},
        "annotations": {"title": "List profiles", "readOnlyHint": True},
    },
]


def _project(args: dict) -> Path:
    p = Path(args.get("project") or Path.cwd()).expanduser().resolve()
    if not p.is_dir():
        raise ValueError(f"project directory not found: {p}")
    return p


def _profile(project: Path, name: str | None):
    from aegis_jail.cli import _load_profile
    return _load_profile(project, name or "default", "command")


def tool_run(args: dict) -> str:
    from aegis_jail.agents import Task, shell
    from aegis_jail.policy import Grant
    from aegis_jail.runner import run_task
    project = _project(args)
    profile = _profile(project, args.get("profile"))
    hosts = [h for h in args.get("allow_hosts") or [] if isinstance(h, str) and h.strip()]
    if hosts:
        profile = profile.merged([Grant(id="mcp-allow-hosts", kind="net", domains=hosts, phase="task")])
    task = Task(name="mcp", agent="command", command=shell(args["command"]),
                timeout=float(args.get("timeout") or 600))
    rep = run_task(project, profile, task, quiet=True)
    phase = rep.phases[0]
    out = Path(phase.log).read_text(encoding="utf-8", errors="replace")
    if len(out) > 20000:
        out = out[:4000] + "\n... (output truncated) ...\n" + out[-15000:]
    lines = [f"exit code: {phase.exit_code}" + (" (timed out)" if phase.timed_out else ""),
             f"run id: {rep.run_id}", f"network: {phase.network}"]
    if rep.changes:
        lines.append("changed files (in the working copy): " + ", ".join(f"{c['path']} ({c['kind']})"
                                                                     for c in rep.changes))
        lines.append(f"review with aegis_diff, then aegis_apply run='{rep.run_id}' or aegis_discard")
    if rep.blocked_network:
        lines.append("blocked network: " + ", ".join(rep.blocked_network))
    hints = [h for h in phase.hints if "Aegis blocked network" not in h]
    if hints:
        lines.append("possible blocked file operations:\n  " + "\n  ".join(hints[:10]))
    return "\n".join(lines) + "\n\n--- output ---\n" + out


def tool_probe(args: dict) -> str:
    from aegis_jail.probe import run_probe
    from aegis_jail.report import render_probe
    project = _project(args)
    return render_probe(run_probe(project, _profile(project, args.get("profile"))))


def tool_runs(args: dict) -> str:
    from aegis_jail.runner import load_report
    project = _project(args)
    rows = sorted(p for p in paths.runs_dir(project).iterdir() if (p / "report.json").exists())[-20:]
    out = []
    for p in rows:
        r = load_report(p)
        out.append(f"{r.run_id}  {'PASS' if r.ok else 'FAIL'}  {len(r.changes)} changes  {r.status}")
    return "\n".join(out) or "No runs yet."


def _run_ctx(args: dict):
    from aegis_jail.runner import find_run, load_report
    project = _project(args)
    rd = find_run(project, args.get("run") or "last")
    return project, rd, load_report(rd)


def tool_diff(args: dict) -> str:
    project, rd, rep = _run_ctx(args)
    if not (rd / "workspace").exists():
        return f"Run {rep.run_id} is {rep.status}; its working copy is gone."
    chs = [workspace.Change(**c) for c in rep.changes]
    return workspace.unified_diff(project, rd / "workspace", chs) or "No changes."


def tool_apply(args: dict) -> str:
    from aegis_jail.runner import cleanup_run
    project, rd, rep = _run_ctx(args)
    if rep.status != "pending" or not (rd / "workspace").exists():
        return f"Run {rep.run_id} is already {rep.status}."
    chs = [workspace.Change(**c) for c in rep.changes]
    applied = workspace.apply(project, rd / "workspace", workspace.load_baseline(rd / "baseline.json"), chs)
    rep.status = "applied"
    rep.save()
    cleanup_run(rd)
    return f"Applied {len(applied)} change(s): " + ", ".join(applied)


def tool_discard(args: dict) -> str:
    from aegis_jail.runner import cleanup_run
    _, rd, rep = _run_ctx(args)
    rep.status = "discarded"
    rep.save()
    cleanup_run(rd)
    return f"Discarded run {rep.run_id}."


def tool_profiles(args: dict) -> str:
    from aegis_jail.policy import Profile
    from aegis_jail.report import describe_profile
    project = _project(args)
    d = paths.project_config_dir(project) / "profiles"
    profiles = [Profile.load(p) for p in sorted(d.glob("*.json"))] if d.exists() else []
    if not any(p.name == "default" for p in profiles):
        profiles.insert(0, Profile("default", "command", []))
    return "\n\n".join(describe_profile(p) for p in profiles)


HANDLERS: dict[str, Callable[[dict], str]] = {
    "aegis_run": tool_run, "aegis_probe": tool_probe, "aegis_runs": tool_runs, "aegis_diff": tool_diff,
    "aegis_apply": tool_apply, "aegis_discard": tool_discard, "aegis_profiles": tool_profiles,
}


def handle(msg: dict) -> dict | None:
    """Handle one JSON-RPC message; returns the response (None for notifications)."""
    mid = msg.get("id")
    method = msg.get("method")
    if mid is None:
        return None  # notification (e.g. notifications/initialized)
    try:
        if method == "initialize":
            asked = (msg.get("params") or {}).get("protocolVersion")
            result: dict = {
                "protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "aegis", "title": "Aegis sandbox", "version": __version__},
                "instructions": ("Use aegis_run to execute shell commands (tests, builds, untrusted scripts) in a "
                                 "sandbox that hides the user's home directory and credentials and blocks network "
                                 "access unless allowed. Changes land in a working copy; show aegis_diff to the "
                                 "user and only aegis_apply after they agree."),
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            params = msg.get("params") or {}
            fn = HANDLERS.get(params.get("name", ""))
            if fn is None:
                return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "unknown tool"}}
            try:
                with contextlib.redirect_stdout(io.StringIO()):  # never corrupt the protocol stream
                    text = fn(params.get("arguments") or {})
                result = {"content": [{"type": "text", "text": text}], "isError": False}
            except Exception as e:  # noqa: BLE001 - reported to the client as a tool error
                result = {"content": [{"type": "text", "text": f"aegis error: {e}"}], "isError": True}
                traceback.print_exc(file=sys.stderr)
        else:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}
    except Exception as e:  # noqa: BLE001
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": str(e)}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def serve(stdin=None, stdout=None) -> int:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            resp: dict | None = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            resp = handle(msg) if isinstance(msg, dict) else None
        if resp is not None:
            stdout.write(json.dumps(resp) + "\n")
            stdout.flush()
    return 0
