# SPDX-License-Identifier: AGPL-3.0-or-later
"""`aegis watch`: Aegis Autopilot, a background watcher that finds problems before you do.

It runs quietly (as a user service, see `aegis watch install`) and on every pass:

* reads the MCP configs of Claude Code, Claude Desktop, Cursor, Windsurf, VS Code and Codex and flags
  servers that run with your full user rights instead of through `aegis mcp-jail`
  (and, with auto-jail on, wraps them itself, keeping a backup of the original entry),
* follows the audit logs of jailed MCP servers: rug pulls, poisoned tool descriptions, blocked tool
  calls, sampling and secret-egress attempts,
* reads new `aegis run` reports: tripwires, blocked connections, runs waiting for review,
* scans projects that Claude Code opens for the first time for hidden instructions aimed at AI.

Every finding becomes an event in ~/.aegis/events.jsonl. Events are what the dashboard shows, what the
Claude Code plugin tells the agent about at the start of a session, and what the Aegis MCP server
exposes to any AI client (`aegis_events`, `aegis_resolve`, `aegis_jail_mcp_server`). With a responder
configured, the watcher starts Claude Code or Codex in the background, limited to the Aegis MCP tools,
to triage new events on its own. A responder can contain a problem (jail a server, discard a run) but
can never approve one: re-trusting a changed tool or applying a run always needs a person.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from aegis_jail import paths

SEVERITY = {"high": 3, "medium": 2, "info": 1}
DEFAULT_CONFIG: dict[str, Any] = {
    "interval": 5,            # seconds between passes
    "auto_jail": False,       # wrap newly found unjailed MCP servers automatically
    "notify": True,           # desktop notifications for medium/high events
    "scan_projects": True,    # scan projects Claude Code opens for the first time
    "responder": "",          # "", "claude" or "codex": let an agent triage new events
    "respond_min": "medium",  # lowest severity the responder is started for
}


# --------------------------------------------------------------------------------------------- storage
def watch_dir() -> Path:
    d = paths.aegis_home() / "watch"
    d.mkdir(parents=True, exist_ok=True)
    return d


def events_path() -> Path:
    return paths.aegis_home() / "events.jsonl"


def _read_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(p: Path, data) -> None:
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    cfg.update({k: v for k, v in _read_json(watch_dir() / "config.json", {}).items() if k in DEFAULT_CONFIG})
    return cfg


def save_config(updates: dict) -> dict:
    cfg = load_config()
    for k, v in updates.items():
        if k not in DEFAULT_CONFIG:
            raise ValueError(f"unknown setting: {k}")
        if k == "responder" and v not in ("", "claude", "codex"):
            raise ValueError("responder must be '', 'claude' or 'codex'")
        if k == "respond_min" and v not in SEVERITY:
            raise ValueError("respond_min must be high, medium or info")
        if k == "interval":
            v = max(2, min(int(v), 3600))
        if isinstance(DEFAULT_CONFIG[k], bool):
            v = bool(v)
        cfg[k] = v
    _write_json(watch_dir() / "config.json", cfg)
    return cfg


def _event_id(*parts: str) -> str:
    return hashlib.sha256("\x00".join(parts).encode()).hexdigest()[:12]


@dataclass
class Event:
    id: str
    kind: str
    severity: str
    title: str
    detail: str
    time: float = field(default_factory=time.time)
    source: str = ""
    data: dict = field(default_factory=dict)
    actions: list[str] = field(default_factory=list)


def _resolutions() -> dict:
    return _read_json(watch_dir() / "resolved.json", {})


def all_events() -> list[dict]:
    """Every event, newest first, each with its current status (open / resolved / ignored)."""
    out: dict[str, dict] = {}
    try:
        with events_path().open(encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if isinstance(e, dict) and "id" in e:
                    out[e["id"]] = e
    except OSError:
        pass
    res = _resolutions()
    for e in out.values():
        r = res.get(e["id"])
        e["status"] = r["status"] if r else "open"
        if r:
            e["resolution"] = r
    return sorted(out.values(), key=lambda e: e.get("time", 0), reverse=True)


def open_events(min_severity: str = "info") -> list[dict]:
    floor = SEVERITY.get(min_severity, 1)
    return [e for e in all_events() if e["status"] == "open" and SEVERITY.get(e["severity"], 1) >= floor]


def get_event(event_id: str) -> dict:
    for e in all_events():
        if e["id"] == event_id or (len(event_id) >= 4 and e["id"].startswith(event_id)):
            return e
    raise KeyError(f"no event {event_id!r}")


def record(ev: Event) -> bool:
    """Append an event unless one with the same id exists. Returns True when it is new."""
    known = {e["id"] for e in all_events()}
    if ev.id in known:
        return False
    with events_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(ev.__dict__) + "\n")
    return True


def resolve(event_id: str, status: str = "resolved", note: str = "", by: str = "user") -> dict:
    if status not in ("resolved", "ignored", "open"):
        raise ValueError("status must be resolved, ignored or open")
    e = get_event(event_id)
    res = _resolutions()
    if status == "open":
        res.pop(e["id"], None)
    else:
        res[e["id"]] = {"status": status, "note": note[:500], "by": by[:40], "time": time.time()}
    _write_json(watch_dir() / "resolved.json", res)
    return get_event(e["id"])


# ----------------------------------------------------------------------------------------- MCP configs
def _home() -> Path:
    return paths.user_home()


def config_files() -> list[tuple[str, Path, str]]:
    """(client, path, key) for every MCP config Aegis knows how to read and edit."""
    h = _home()
    out: list[tuple[str, Path, str]] = [
        ("Claude Code", h / ".claude.json", "mcpServers"),
        ("Cursor", h / ".cursor" / "mcp.json", "mcpServers"),
        ("Windsurf", h / ".codeium" / "windsurf" / "mcp_config.json", "mcpServers"),
    ]
    system = platform.system()
    if system == "Darwin":
        desktop = h / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    elif system == "Windows":
        desktop = Path(os.environ.get("APPDATA", h / "AppData" / "Roaming")) / "Claude" / "claude_desktop_config.json"
    else:
        desktop = h / ".config" / "Claude" / "claude_desktop_config.json"
    out.append(("Claude Desktop", desktop, "mcpServers"))
    for proj in known_projects():
        out.append(("Claude Code (project)", proj / ".mcp.json", "mcpServers"))
        out.append(("Cursor (project)", proj / ".cursor" / "mcp.json", "mcpServers"))
        out.append(("VS Code (project)", proj / ".vscode" / "mcp.json", "servers"))
    return out


def known_projects() -> list[Path]:
    """Projects Claude Code has been opened in (from ~/.claude.json), plus any listed in watch config."""
    data = _read_json(_home() / ".claude.json", {})
    out = []
    for p in (data.get("projects") or {}) if isinstance(data, dict) else {}:
        pp = Path(p)
        if pp.is_dir() and pp != _home():
            out.append(pp)
    for p in _read_json(watch_dir() / "projects.json", []):
        pp = Path(p).expanduser()
        if pp.is_dir() and pp not in out:
            out.append(pp)
    return out


def is_jailed(entry: dict) -> bool:
    """True when the server is started through `aegis mcp-jail` (or is Aegis itself)."""
    cmd = str(entry.get("command", ""))
    args = [str(a) for a in entry.get("args") or []]
    words = [Path(cmd).name.lower()] + args
    if "mcp-jail" in args:
        return True
    is_aegis = Path(cmd).name.lower() in ("aegis", "aegis.exe") or any(
        w.endswith("aegis.py") or w == "aegis_jail" for w in words)
    return is_aegis and "mcp-server" in args


def _server_entries(path: Path, key: str) -> Iterable[tuple[str, dict, list[str]]]:
    """(name, entry, json-path) for each server in a config file, including Claude Code's per-project ones."""
    data = _read_json(path, None)
    if not isinstance(data, dict):
        return
    for name, entry in (data.get(key) or {}).items():
        if isinstance(entry, dict):
            yield name, entry, [key, name]
    if path.name == ".claude.json":
        for proj, pdata in (data.get("projects") or {}).items():
            if isinstance(pdata, dict):
                for name, entry in (pdata.get("mcpServers") or {}).items():
                    if isinstance(entry, dict):
                        yield name, entry, ["projects", proj, "mcpServers", name]


def codex_servers() -> list[dict]:
    """Codex keeps MCP servers in TOML. Read-only: listed, never rewritten."""
    p = _home() / ".codex" / "config.toml"
    try:
        import tomllib  # Python 3.11+
        data = tomllib.loads(p.read_text(encoding="utf-8"))
    except (ImportError, OSError, ValueError):
        return []
    out = []
    for name, entry in (data.get("mcp_servers") or {}).items():
        if isinstance(entry, dict):
            out.append({"client": "Codex", "file": str(p), "name": name, "jsonpath": None,
                        "command": entry.get("command", ""), "args": entry.get("args") or [],
                        "remote": bool(entry.get("url")), "jailed": is_jailed(entry), "editable": False})
    return out


def mcp_servers() -> list[dict]:
    """Every MCP server configured on this machine, with whether it is jailed."""
    out = []
    seen = set()
    for client, path, key in config_files():
        if not path.exists():
            continue
        for name, entry, jp in _server_entries(path, key):
            ident = (str(path), tuple(jp))
            if ident in seen:
                continue
            seen.add(ident)
            remote = "url" in entry or entry.get("type") in ("http", "sse")
            out.append({"client": client, "file": str(path), "name": name, "jsonpath": jp,
                        "command": entry.get("command", ""), "args": entry.get("args") or [],
                        "remote": remote, "url": entry.get("url", ""), "jailed": is_jailed(entry),
                        "editable": not remote, "project": jp[1] if jp[0] == "projects" else ""})
    out.extend(codex_servers())
    return out


def _aegis_command() -> list[str]:
    exe = shutil.which("aegis")
    return [exe] if exe else [sys.executable, "-m", "aegis_jail"]


def _get_in(data: dict, jp: list[str]) -> dict:
    cur: Any = data
    for k in jp:
        cur = cur[k]
    return cur


def jail_server(file: str, jsonpath: list[str]) -> dict:
    """Rewrite one MCP server entry so it starts through `aegis mcp-jail`. Keeps a backup; reversible."""
    path = Path(file)
    data = json.loads(path.read_text(encoding="utf-8"))
    entry = _get_in(data, jsonpath)
    if is_jailed(entry):
        return {"changed": False, "entry": entry}
    if "command" not in entry:
        raise ValueError("remote (URL) MCP servers cannot be sandboxed locally; review them instead")
    original = json.loads(json.dumps(entry))
    name = jsonpath[-1]
    aegis = _aegis_command()
    args = aegis[1:] + ["mcp-jail", "--name", name]
    env = entry.get("env") or {}
    if env:
        args += ["--pass-env", ",".join(sorted(env))]
    if entry.get("cwd"):
        args += ["--project", str(entry["cwd"])]
    args += ["--", str(entry["command"]), *[str(a) for a in entry.get("args") or []]]
    entry["command"] = aegis[0]
    entry["args"] = args
    backups = watch_dir() / "backups"
    backups.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    shutil.copy2(path, backups / f"{stamp}-{path.name}")
    store = _read_json(watch_dir() / "originals.json", {})
    store[_event_id(file, *jsonpath)] = {"file": file, "jsonpath": jsonpath, "entry": original}
    _write_json(watch_dir() / "originals.json", store)
    _write_json(path, data)
    return {"changed": True, "entry": entry, "backup": str(backups / f"{stamp}-{path.name}")}


def unjail_server(file: str, jsonpath: list[str]) -> dict:
    store = _read_json(watch_dir() / "originals.json", {})
    key = _event_id(file, *jsonpath)
    if key not in store:
        raise KeyError("no saved original for this server (it was not jailed by Aegis Autopilot)")
    path = Path(file)
    data = json.loads(path.read_text(encoding="utf-8"))
    parent = _get_in(data, jsonpath[:-1])
    parent[jsonpath[-1]] = store.pop(key)["entry"]
    _write_json(path, data)
    _write_json(watch_dir() / "originals.json", store)
    return {"changed": True}


# ------------------------------------------------------------------------------------------- detectors
def _mcp_event(s: dict) -> Event | None:
    where = f"{s['client']}: {s['file']}"
    if s["remote"]:
        return Event(id=_event_id("remote", s["file"], s["name"], s.get("url", "")), kind="mcp_remote", severity="info",
                     title=f"Remote MCP server '{s['name']}'",
                     detail=f"{where}. It runs on someone else's machine, so Aegis cannot sandbox it. If you reach it through a "
                            "local stdio bridge (such as mcp-remote), start that bridge with `aegis mcp-jail` to pin and "
                            "filter its tools.",
                     source="config", data=s)
    if s["jailed"]:
        return None
    cmd = " ".join([str(s["command"]), *[str(a) for a in s["args"]]])[:300]
    return Event(id=_event_id("unjailed", s["file"], *(s["jsonpath"] or [s["name"]]), cmd), kind="mcp_unjailed",
                 severity="medium", title=f"MCP server '{s['name']}' runs with your full user rights",
                 detail=f"{where}\nCommand: {cmd}\nIt can read your home directory, keys and tokens and reach any "
                        "host. Jailing it starts it through `aegis mcp-jail` instead.",
                 source="config", data=s, actions=["jail"] if s["editable"] else [])


AUDIT_KINDS = {
    "tool_hidden": ("high", "Tool hidden: {tool}", "{reason}"),
    "sampling_blocked": ("medium", "Server tried to use your model (sampling)", "The request was blocked."),
    "invisible_text_stripped": ("medium", "Invisible text removed from a tool result", "Hidden characters: {hidden}"),
    "secret_blocked": ("high", "Credential kept from leaving through {tool}", "{reason}"),
    "oversized": ("info", "Oversized message dropped", "{bytes} bytes from the {direction}"),
}


def _audit_events(state: dict) -> list[Event]:
    out = []
    offsets = state.setdefault("audit_offsets", {})
    mcp_dir = paths.aegis_home() / "mcp"
    if not mcp_dir.is_dir():
        return out
    for log in sorted(mcp_dir.glob("*.jsonl")):
        name = log.stem
        try:
            size = log.stat().st_size
            start = offsets.get(str(log), 0)
            if start > size:
                start = 0
            with log.open("rb") as f:
                f.seek(start)
                chunk = f.read()
            offsets[str(log)] = start + len(chunk)
        except OSError:
            continue
        for raw in chunk.decode("utf-8", "replace").splitlines():
            try:
                e = json.loads(raw)
            except ValueError:
                continue
            kind = e.get("event")
            fmt = {k: str(v)[:300] for k, v in e.items()}
            if kind == "tool_call" and (e.get("allowed") is False or e.get("tripwire")):
                trip = bool(e.get("tripwire"))
                out.append(Event(id=_event_id("audit", name, raw), kind="tripwire" if trip else "mcp_blocked_call",
                                 severity="high" if trip else "medium",
                                 title=(f"Decoy credential sent to '{e.get('tool')}' on {name}" if trip
                                        else f"Blocked call to '{e.get('tool')}' on {name}"),
                                 detail=e.get("blocked_reason") or ("An agent passed a planted fake key to this tool: "
                                        "it was probably prompt-injected." if trip else "Blocked by the tool firewall."),
                                 time=e.get("time", time.time()), source=f"mcp:{name}",
                                 data={"server": name, "tool": e.get("tool"), "arguments": e.get("arguments")}))
            elif kind in AUDIT_KINDS:
                sev, title, detail = AUDIT_KINDS[kind]
                fmt.setdefault("tool", "?")
                fmt.setdefault("reason", "")
                rugpull = kind == "tool_hidden" and "changed" in str(e.get("reason", ""))
                out.append(Event(id=_event_id("audit", name, raw), kind="mcp_rug_pull" if rugpull else f"mcp_{kind}",
                                 severity=sev, title=(title.format_map(_Safe(fmt)) + f" on {name}"),
                                 detail=detail.format_map(_Safe(fmt)), time=e.get("time", time.time()),
                                 source=f"mcp:{name}", data={"server": name, **{k: e[k] for k in e if k != "time"}},
                                 actions=["review_pins"] if rugpull else []))
    return out


class _Safe(dict):
    def __missing__(self, key):
        return ""


def _run_events(state: dict) -> list[Event]:
    out = []
    seen = set(state.setdefault("runs_seen", []))
    base = paths.aegis_home() / "runs"
    if not base.is_dir():
        return out
    for rep in sorted(base.glob("*/*/report.json")):
        rid = f"{rep.parent.parent.name}/{rep.parent.name}"
        if rid in seen:
            continue
        seen.add(rid)
        d = _read_json(rep, None)
        if not isinstance(d, dict):
            continue
        project = d.get("project", "")
        ref = {"project": project, "run": d.get("run_id", rep.parent.name), "project_key": rep.parent.parent.name}
        if d.get("tripwires"):
            out.append(Event(id=_event_id("tripwire", rid), kind="tripwire", severity="high",
                             title=f"Tripwire in run {ref['run']}",
                             detail="The agent handled decoy credentials that no honest task needs: "
                                    + "; ".join(d["tripwires"])[:400] + ". Treat the run as hostile.",
                             time=d.get("started", time.time()), source="run", data=ref, actions=["discard"]))
        blocked = sorted({f"{e['host']}:{e['port']}" for p in d.get("phases", []) for e in p.get("net_events", [])
                          if not e.get("allowed")})
        if blocked:
            out.append(Event(id=_event_id("blocked", rid), kind="network_blocked", severity="medium",
                             title=f"{len(blocked)} connection(s) blocked in run {ref['run']}",
                             detail=", ".join(blocked)[:400], time=d.get("started", time.time()),
                             source="run", data={**ref, "hosts": blocked}))
        if d.get("status") == "pending" and d.get("changes"):
            out.append(Event(id=_event_id("review", rid), kind="run_review", severity="info",
                             title=f"Run {ref['run']} is waiting for review",
                             detail=f"{len(d['changes'])} changed file(s) in {project}. "
                                    "Review with `aegis diff`, then apply or discard.",
                             time=d.get("started", time.time()), source="run", data=ref, actions=["discard"]))
    state["runs_seen"] = sorted(seen)[-5000:]
    return out


def _project_events(state: dict) -> list[Event]:
    from aegis_jail import scan
    out = []
    scanned = set(state.setdefault("projects_scanned", []))
    for proj in known_projects():
        if str(proj) in scanned:
            continue
        scanned.add(str(proj))
        try:
            findings = [f for f in scan.scan(proj, max_files=4000) if f.severity == "high"]
        except Exception:  # noqa: BLE001 - one unreadable project must not stop the watcher
            continue
        if findings:
            lines = [f"{f.path}:{f.line} {f.what}" for f in findings[:8]]
            out.append(Event(id=_event_id("scan", str(proj), *lines), kind="project_risk", severity="high",
                             title=f"{len(findings)} high-risk finding(s) in {proj.name}",
                             detail="\n".join(lines), source="scan", data={"project": str(proj)}))
    state["projects_scanned"] = sorted(scanned)
    return out


# --------------------------------------------------------------------------------------------- actions
def act(event_id: str, action: str, by: str = "user") -> dict:
    """Run one of an event's safe actions. Nothing here approves anything."""
    e = get_event(event_id)
    if action not in e.get("actions", []):
        raise ValueError(f"action {action!r} is not available for this event")
    if action == "jail":
        res = jail_server(e["data"]["file"], e["data"]["jsonpath"])
        resolve(e["id"], note="jailed: the server now starts through aegis mcp-jail", by=by)
        return {"ok": True, "message": "Jailed. Restart the MCP client to use the sandboxed server.", **res}
    if action == "discard":
        from aegis_jail.runner import cleanup_run, find_run, load_report
        run_dir = find_run(Path(e["data"]["project"]), e["data"]["run"])
        rep = load_report(run_dir)
        rep.status = "discarded"
        rep.save()
        cleanup_run(run_dir)
        resolve(e["id"], note="run discarded", by=by)
        return {"ok": True, "message": f"Run {rep.run_id} discarded."}
    if action == "review_pins":
        return {"ok": True, "message": "A person must review this change: run `aegis mcp-pins "
                                       f"{e['data'].get('server')}` and reset the pin only if the new tool is safe."}
    raise ValueError(action)


def notify(title: str, body: str) -> None:
    """Best-effort desktop notification; silent when no notifier exists."""
    try:
        system = platform.system()
        if system == "Linux" and shutil.which("notify-send"):
            subprocess.run(["notify-send", "-a", "Aegis", title, body[:200]], timeout=5, check=False)
        elif system == "Darwin":
            script = f'display notification {json.dumps(body[:200])} with title {json.dumps(title)}'
            subprocess.run(["osascript", "-e", script], timeout=5, check=False)
        elif system == "Windows":
            ps = ("[void][System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms');"
                  "$n=New-Object System.Windows.Forms.NotifyIcon;$n.Icon=[System.Drawing.SystemIcons]::Shield;"
                  "$n.Visible=$true;$n.ShowBalloonTip(8000,$env:AEGIS_T,$env:AEGIS_B,'Warning');Start-Sleep 9")
            env = dict(os.environ, AEGIS_T=title, AEGIS_B=body[:200])
            subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps], env=env)
    except (OSError, subprocess.SubprocessError):
        pass


RESPONDER_TOOLS = ["aegis_events", "aegis_resolve", "aegis_jail_mcp_server", "aegis_discard", "aegis_diff",
                   "aegis_scan", "aegis_watch_status"]
RESPONDER_PROMPT = (
    "You are Aegis Autopilot's responder. New security events were detected on this machine. "
    "Call aegis_events to read the open events. For each one: contain it if that is safe (jail an unjailed MCP "
    "server with aegis_jail_mcp_server; discard a run that tripped a wire with aegis_discard), otherwise leave it "
    "open. Never approve a changed or poisoned tool and never apply a run: those need a person. Resolve only what "
    "you contained, with a one-line note. Finish with a short summary for the user.")


def responder_command(agent: str) -> list[str]:
    aegis = _aegis_command()
    if agent == "claude":
        cfg = {"mcpServers": {"aegis": {"command": aegis[0], "args": aegis[1:] + ["mcp-server"]}}}
        cfg_path = watch_dir() / "responder-mcp.json"
        _write_json(cfg_path, cfg)
        allowed = ",".join(f"mcp__aegis__{t}" for t in RESPONDER_TOOLS)
        return ["claude", "-p", RESPONDER_PROMPT, "--mcp-config", str(cfg_path), "--strict-mcp-config",
                "--allowedTools", allowed]
    if agent == "codex":
        return ["codex", "exec", "-c", f"mcp_servers.aegis.command={json.dumps(aegis[0])}",
                "-c", f"mcp_servers.aegis.args={json.dumps(aegis[1:] + ['mcp-server'])}", RESPONDER_PROMPT]
    raise ValueError(agent)


_RESPONDER: dict[str, Any] = {"proc": None, "last": 0.0}


def start_responder(agent: str) -> bool:
    """Start the responder agent in the background (one at a time, at most once a minute)."""
    proc = _RESPONDER["proc"]
    if proc is not None and proc.poll() is None:
        return False
    if time.time() - _RESPONDER["last"] < 60:
        return False
    cmd = responder_command(agent)
    if not shutil.which(cmd[0]):
        record(Event(id=_event_id("responder-missing", agent), kind="autopilot", severity="info",
                     title=f"Responder '{agent}' is not installed", detail=f"`{cmd[0]}` was not found on PATH.",
                     source="autopilot"))
        return False
    log = (watch_dir() / "responder.log").open("a", encoding="utf-8")
    log.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} {agent} ===\n")
    log.flush()
    _RESPONDER["proc"] = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                          cwd=str(watch_dir()))
    _RESPONDER["last"] = time.time()
    return True


# ------------------------------------------------------------------------------------------------ loop
def scan_once(cfg: dict | None = None) -> list[Event]:
    """One pass of every detector. Returns the events that are new."""
    cfg = cfg or load_config()
    state_p = watch_dir() / "state.json"
    state = _read_json(state_p, {})
    found: list[Event] = []
    servers = mcp_servers()
    for s in servers:
        ev = _mcp_event(s)
        if ev:
            found.append(ev)
    found += _audit_events(state)
    found += _run_events(state)
    if cfg.get("scan_projects"):
        found += _project_events(state)
    new = [ev for ev in found if record(ev)]
    if cfg.get("auto_jail"):
        for ev in new:
            if ev.kind == "mcp_unjailed" and "jail" in ev.actions:
                try:
                    act(ev.id, "jail", by="autopilot")
                except (OSError, ValueError, KeyError) as e:
                    record(Event(id=_event_id("jail-failed", ev.id), kind="autopilot", severity="info",
                                 title=f"Could not jail '{ev.data.get('name')}'", detail=str(e), source="autopilot"))
    state["last_pass"] = time.time()
    state["servers"] = len(servers)
    _write_json(state_p, state)
    loud = [e for e in new if SEVERITY[e.severity] >= SEVERITY["medium"]]
    if loud and cfg.get("notify"):
        notify(f"Aegis: {len(loud)} new event(s)", loud[0].title)
    if cfg.get("responder") and any(SEVERITY[e.severity] >= SEVERITY[cfg.get("respond_min", "medium")] for e in new):
        start_responder(cfg["responder"])
    return new


def _pid_alive(pid: int) -> bool:
    """Whether a process exists. Never signals it (on Windows, os.kill(pid, 0) would send Ctrl+C)."""
    if os.name == "nt":
        import ctypes
        k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        h = k32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
        k32.CloseHandle(h)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    try:
        os.kill(int(pid), 0)
        return True
    except PermissionError:
        return True
    except (OSError, ValueError):
        return False


def status() -> dict:
    state = _read_json(watch_dir() / "state.json", {})
    pid = _read_json(watch_dir() / "daemon.json", {})
    alive = False
    if pid.get("pid") and _pid_alive(pid["pid"]):
        alive = time.time() - state.get("last_pass", 0) < max(60, 6 * load_config()["interval"])
    return {"running": alive, "pid": pid.get("pid") if alive else None, "last_pass": state.get("last_pass"),
            "dashboard": pid.get("dashboard") if alive else None, "config": load_config(),
            "open": len(open_events()), "servers": state.get("servers", 0)}


def run_forever(dashboard_port: int | None = 7341, stop: threading.Event | None = None) -> int:
    stop = stop or threading.Event()
    info: dict[str, Any] = {"pid": os.getpid(), "started": time.time()}
    server = None
    if dashboard_port is not None:
        from aegis_jail import dashboard
        try:
            server, url = dashboard.start(dashboard_port)
            info["dashboard"] = url
            print(f"Aegis dashboard: {url}", flush=True)
        except OSError as e:
            print(f"aegis watch: dashboard not started ({e})", file=sys.stderr, flush=True)
    _write_json(watch_dir() / "daemon.json", info)
    print("Aegis Autopilot is watching. Ctrl+C to stop.", flush=True)
    try:
        while not stop.is_set():
            try:
                for ev in scan_once():
                    print(f"[{ev.severity}] {ev.title}", flush=True)
            except Exception as e:  # noqa: BLE001 - keep watching
                print(f"aegis watch: pass failed: {e}", file=sys.stderr, flush=True)
            stop.wait(load_config()["interval"])
    except KeyboardInterrupt:
        pass
    finally:
        if server:
            server.shutdown()
        try:
            (watch_dir() / "daemon.json").unlink()
        except OSError:
            pass
    return 0


# ------------------------------------------------------------------------------------------- autostart
def _python_cmd() -> list[str]:
    return [sys.executable, "-m", "aegis_jail", "watch"]


def install_service() -> str:
    system = platform.system()
    cmd = _python_cmd()
    if system == "Linux":
        unit_dir = _home() / ".config" / "systemd" / "user"
        unit_dir.mkdir(parents=True, exist_ok=True)
        unit = unit_dir / "aegis-watch.service"
        unit.write_text("[Unit]\nDescription=Aegis Autopilot (aegis watch)\n\n[Service]\n"
                        f"ExecStart={' '.join(_q(c) for c in cmd)}\nRestart=on-failure\nRestartSec=10\n\n"
                        "[Install]\nWantedBy=default.target\n", encoding="utf-8")
        if shutil.which("systemctl"):
            r = subprocess.run(["systemctl", "--user", "enable", "--now", "aegis-watch.service"],
                               capture_output=True, text=True, check=False)
            if r.returncode == 0:
                return f"Installed and started {unit} (systemd user service)."
            return f"Wrote {unit}, but systemctl failed: {r.stderr.strip()}. Start it with: {' '.join(cmd)}"
        return f"Wrote {unit}. No systemctl here: start it from your session startup with: {' '.join(cmd)}"
    if system == "Darwin":
        agents = _home() / "Library" / "LaunchAgents"
        agents.mkdir(parents=True, exist_ok=True)
        plist = agents / "dev.aegis.watch.plist"
        items = "".join(f"<string>{c}</string>" for c in cmd)
        plist.write_text('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
                         '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n<plist version="1.0"><dict>'
                         f"<key>Label</key><string>dev.aegis.watch</string><key>ProgramArguments</key><array>{items}</array>"
                         "<key>RunAtLoad</key><true/><key>KeepAlive</key><true/>"
                         f"<key>StandardOutPath</key><string>{watch_dir() / 'daemon.log'}</string>"
                         f"<key>StandardErrorPath</key><string>{watch_dir() / 'daemon.log'}</string>"
                         "</dict></plist>\n", encoding="utf-8")
        subprocess.run(["launchctl", "unload", str(plist)], capture_output=True, check=False)
        r = subprocess.run(["launchctl", "load", str(plist)], capture_output=True, text=True, check=False)
        return f"Installed {plist} (launchd)." + ("" if r.returncode == 0 else f" launchctl: {r.stderr.strip()}")
    if system == "Windows":
        pyw = Path(sys.executable).with_name("pythonw.exe")
        exe = str(pyw if pyw.exists() else sys.executable)
        tr = subprocess.list2cmdline([exe, *cmd[1:]])
        r = subprocess.run(["schtasks", "/Create", "/F", "/SC", "ONLOGON", "/TN", "AegisWatch", "/TR", tr],
                           capture_output=True, text=True, check=False)
        if r.returncode == 0:
            subprocess.run(["schtasks", "/Run", "/TN", "AegisWatch"], capture_output=True, check=False)
            return "Installed the AegisWatch scheduled task (starts at logon) and started it."
        return f"schtasks failed: {r.stderr.strip() or r.stdout.strip()}"
    return f"Unsupported system {system}; run `{' '.join(cmd)}` at login."


def uninstall_service() -> str:
    system = platform.system()
    if system == "Linux":
        unit = _home() / ".config" / "systemd" / "user" / "aegis-watch.service"
        if shutil.which("systemctl"):
            subprocess.run(["systemctl", "--user", "disable", "--now", "aegis-watch.service"],
                           capture_output=True, check=False)
        unit.unlink(missing_ok=True)
        return "Removed the systemd user service."
    if system == "Darwin":
        plist = _home() / "Library" / "LaunchAgents" / "dev.aegis.watch.plist"
        subprocess.run(["launchctl", "unload", str(plist)], capture_output=True, check=False)
        plist.unlink(missing_ok=True)
        return "Removed the launchd agent."
    if system == "Windows":
        subprocess.run(["schtasks", "/Delete", "/F", "/TN", "AegisWatch"], capture_output=True, check=False)
        return "Removed the AegisWatch scheduled task."
    return "Nothing to remove."


def _q(s: str) -> str:
    return f'"{s}"' if " " in s else s
