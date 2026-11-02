# SPDX-License-Identifier: AGPL-3.0-or-later
"""`aegis dashboard`: a local web UI for Autopilot events, runs, MCP servers and boundaries.

Standard library only. It listens on 127.0.0.1 and nowhere else, needs a per-user token (kept in
~/.aegis/watch/dashboard.json and handed to the browser once, then stored in a SameSite=Strict cookie),
rejects requests whose Host header is not the loopback address (DNS rebinding) and cross-origin writes.
Everything the page shows that came from an agent or an MCP server is rendered as text, never as HTML.
"""

from __future__ import annotations

import http.server
import json
import secrets
import socketserver
import threading
import time
import webbrowser
from http import cookies
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from aegis_jail import __version__, paths, watch

WEB = Path(__file__).parent / "web"
STATIC = {"/": ("index.html", "text/html; charset=utf-8"), "/app.css": ("app.css", "text/css; charset=utf-8"),
          "/fonts/figtree.woff2": ("fonts/figtree.woff2", "font/woff2"),
          "/fonts/jetbrains-mono.woff2": ("fonts/jetbrains-mono.woff2", "font/woff2"),
          "/app.js": ("app.js", "text/javascript; charset=utf-8")}
COOKIE = "aegis_dash"


def token() -> str:
    p = watch.watch_dir() / "dashboard.json"
    data = watch._read_json(p, {})
    if not data.get("token"):
        data["token"] = secrets.token_urlsafe(24)
        watch._write_json(p, data)
        try:
            p.chmod(0o600)
        except OSError:
            pass
    return data["token"]


# ------------------------------------------------------------------------------------------------ data
def _runs(limit: int = 80) -> list[dict]:
    base = paths.aegis_home() / "runs"
    out = []
    for rep in base.glob("*/*/report.json") if base.is_dir() else []:
        d = watch._read_json(rep, None)
        if not isinstance(d, dict):
            continue
        blocked = sorted({f"{e['host']}:{e['port']}" for p in d.get("phases", []) for e in p.get("net_events", [])
                          if not e.get("allowed")})
        hints = [h for p in d.get("phases", []) for h in p.get("hints", [])]
        out.append({
            "id": d.get("run_id", rep.parent.name), "key": rep.parent.parent.name, "project": d.get("project", ""),
            "agent": (d.get("task") or {}).get("agent") or (d.get("profile") or {}).get("agent", ""),
            "profile": (d.get("profile") or {}).get("name", ""), "backend": d.get("backend", ""),
            "started": d.get("started", 0), "status": d.get("status", "pending"),
            "ok": bool(d.get("phases")) and all(p.get("exit_code") == 0 and not p.get("timed_out") for p in d["phases"]),
            "phases": [{"name": p.get("name"), "ok": p.get("exit_code") == 0 and not p.get("timed_out"),
                        "duration": p.get("duration", 0), "network": p.get("network", "")} for p in d.get("phases", [])],
            "changes": [{"path": c.get("path"), "kind": c.get("kind"), "risk": c.get("risk", "")} for c in d.get("changes", [])],
            "tripwires": d.get("tripwires", []), "blocked": blocked, "denials": hints[:12],
            "hidden": d.get("hidden", [])[:40], "workspace": (rep.parent / "workspace").exists(),
            "failure": _failure(d),
            "prompt": ((d.get("task") or {}).get("prompt") or " ".join((d.get("task") or {}).get("command") or []))[:200],
            "duration": round(sum(p.get("duration", 0) for p in d.get("phases", [])), 2),
        })
    out.sort(key=lambda r: r["started"], reverse=True)
    return out[:limit]


def _failure(d: dict) -> str:
    """The last lines of the first failed phase's log: why a run failed, in the agent's own words."""
    for ph in d.get("phases", []):
        if ph.get("exit_code") == 0 and not ph.get("timed_out"):
            continue
        if ph.get("timed_out"):
            return f"{ph.get('name')} timed out after {ph.get('duration')}s"
        try:
            with open(ph.get("log", ""), "rb") as f:
                f.seek(0, 2)
                f.seek(max(0, f.tell() - 1500))
                tail = f.read().decode("utf-8", "replace")
        except OSError:
            tail = ""
        lines = [ln for ln in tail.splitlines() if ln.strip()][-6:]
        return f"{ph.get('name')} exited with code {ph.get('exit_code')}" + ("\n" + "\n".join(lines) if lines else "")
    return ""


def _activity(limit: int = 200) -> list[dict]:
    mcp_dir = paths.aegis_home() / "mcp"
    rows: list[dict] = []
    for log in mcp_dir.glob("*.jsonl") if mcp_dir.is_dir() else []:
        try:
            lines = log.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
        except OSError:
            continue
        for line in lines:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if isinstance(e, dict):
                e["server"] = log.stem
                rows.append(e)
    rows.sort(key=lambda e: e.get("time", 0), reverse=True)
    return rows[:limit]


def _pins() -> dict:
    mcp_dir = paths.aegis_home() / "mcp"
    out = {}
    for p in mcp_dir.glob("*.pins.json") if mcp_dir.is_dir() else []:
        out[p.name[:-len(".pins.json")]] = len(watch._read_json(p, {}))
    return out


AGENT_INFO = [("claude-code", "Claude", "Anthropic"), ("codex", "Codex", "OpenAI"), ("gemini", "Gemini", "Google"),
              ("aider", "Aider", "open source")]
_AGENT_CACHE: dict = {"t": 0.0, "data": []}


def _agents(runs: list[dict]) -> list[dict]:
    """Which agent CLIs are installed (cached for five minutes) and how their sandboxed runs went."""
    if time.time() - _AGENT_CACHE["t"] > 300:
        from aegis_jail.agents import Task, get_agent
        data = []
        for aid, name, vendor in AGENT_INFO:
            try:
                ver = get_agent(aid).version(Task(agent=aid))
            except Exception:  # noqa: BLE001
                ver = "not installed"
            data.append({"id": aid, "name": name, "vendor": vendor, "version": ver,
                         "installed": ver != "not installed"})
        _AGENT_CACHE.update(t=time.time(), data=data)
    out = []
    for a in _AGENT_CACHE["data"]:
        mine = [r for r in runs if r["agent"] == a["id"]]
        out.append({**a, "runs": len(mine), "passed": sum(1 for r in mine if r["ok"]),
                    "tripwires": sum(1 for r in mine if r["tripwires"]),
                    "end_to_end_tested": a["id"] == "claude-code"})
    return out


def _projects(runs: list[dict]) -> list[dict]:
    seen: list[Path] = []
    for p in [*watch.known_projects(), *(Path(r["project"]) for r in runs if r["project"])]:
        p = Path(p)
        if p.is_dir() and p not in seen:
            seen.append(p)
    out = []
    for p in seen[:40]:
        prof_dir = paths.project_config_dir(p) / "profiles"
        profiles = sorted(x.stem for x in prof_dir.glob("*.json")) if prof_dir.is_dir() else []
        if "default" not in profiles:
            profiles.insert(0, "default")
        out.append({"path": str(p), "name": p.name, "profiles": profiles,
                    "runs": sum(1 for r in runs if r["project"] == str(p)),
                    "task": (paths.project_config_dir(p) / "task.json").exists()})
    return out


def _active() -> list[dict]:
    """Runs started from the dashboard that are still going."""
    p = watch.watch_dir() / "active.json"
    items = watch._read_json(p, [])
    alive = [a for a in items if watch._pid_alive(a.get("pid", 0))]
    if len(alive) != len(items):
        watch._write_json(p, alive)
    return alive


def start_run(project: str, agent: str, prompt: str, known: list[str]) -> dict:
    import subprocess
    if project not in known:
        raise ValueError("pick one of the projects Aegis knows about")
    if agent not in {a for a, _, _ in AGENT_INFO}:
        raise ValueError("unknown agent")
    prompt = prompt.strip()
    if not prompt or len(prompt) > 4000:
        raise ValueError("describe the task in a few words (up to 4000 characters)")
    import os
    run_log = watch.watch_dir() / f"dashboard-run-{int(time.time())}.log"
    log = run_log.open("w", encoding="utf-8")
    aegis, extra_env = watch.aegis_invocation()
    env = dict(os.environ)
    if extra_env.get("PYTHONPATH"):
        env["PYTHONPATH"] = os.pathsep.join(x for x in (extra_env["PYTHONPATH"], env.get("PYTHONPATH")) if x)
    proc = subprocess.Popen([*aegis, "run", "--project", project, "--agent", agent, "--prompt", prompt],
                            stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, cwd=project, env=env)
    log.close()  # the child keeps its own copy
    items = _active()
    items.append({"pid": proc.pid, "project": project, "agent": agent, "prompt": prompt[:200], "started": time.time()})
    watch._write_json(watch.watch_dir() / "active.json", items)
    threading.Thread(target=_watch_run, args=(proc, run_log, project, agent), daemon=True).start()
    return {"ok": True, "message": f"Started {agent} in the sandbox on {Path(project).name}. "
                                   "Its changes wait for your review."}


def _watch_run(proc, log_path: Path, project: str, agent: str) -> None:
    """A run that exits without writing a report never started properly (untrusted task, missing agent, ...).
    Say so in the dashboard instead of letting it vanish."""
    code = proc.wait()
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    if "# Aegis run" in text or code == 0:
        try:
            log_path.unlink()
        except OSError:
            pass
        return
    tail = "\n".join(ln for ln in text.splitlines() if ln.strip())[-700:] or f"exit code {code}"
    watch.record(watch.Event(id=watch._event_id("run-failed", str(log_path)), kind="autopilot", severity="medium",
                             title=f"The {agent} run on {Path(project).name} did not start",
                             detail=tail, source="dashboard", data={"project": project, "agent": agent}))


def _setup() -> dict:
    import platform
    import sys
    from aegis_jail.sandbox import SandboxUnavailable, get_backend
    try:
        backend, ok, why = get_backend().name, True, ""
    except SandboxUnavailable as e:
        backend, ok, why = "unavailable", False, str(e)
    return {"backend": backend, "backend_ok": ok, "backend_note": why, "system": platform.system(),
            "machine": platform.machine(), "python": sys.version.split()[0], "version": __version__}


_LAST_SCAN = {"t": 0.0}


def state() -> dict:
    st = watch.status()
    if not st["running"] and time.time() - _LAST_SCAN["t"] > 10:
        # No background watcher: keep the page truthful by running the detectors on demand.
        _LAST_SCAN["t"] = time.time()
        try:
            watch.scan_once(dict(st["config"], responder="", notify=False, auto_jail=False))
        except Exception:  # noqa: BLE001
            pass
        st = watch.status()
    events = watch.all_events()
    runs = _runs()
    servers = watch.mcp_servers()
    originals = watch._read_json(watch.watch_dir() / "originals.json", {})
    for srv in servers:
        srv["restorable"] = bool(srv.get("jsonpath")) and watch._event_id(srv["file"], *srv["jsonpath"]) in originals
    local = [s for s in servers if not s["remote"]]
    from aegis_jail.sandbox import get_backend
    try:
        backend = get_backend().name
    except Exception:  # noqa: BLE001
        backend = "unavailable"
    return {
        "version": __version__, "backend": backend, "home": str(paths.aegis_home()), "now": time.time(),
        "watch": st, "events": events[:300], "runs": runs, "agents": _agents(runs), "projects": _projects(runs),
        "active": _active(), "setup": _setup(), "servers": servers, "activity": _activity(), "pins": _pins(),
        "counts": {
            "open": sum(1 for e in events if e["status"] == "open"),
            "open_high": sum(1 for e in events if e["status"] == "open" and e["severity"] == "high"),
            "runs": len(runs), "blocked": sum(len(r["blocked"]) + len(r["denials"]) for r in runs) + sum(
                1 for e in events if e["kind"] == "mcp_blocked_call"),
            "tripwires": sum(1 for r in runs if r["tripwires"]) + sum(1 for e in events if e["kind"] == "tripwire" and e["source"] != "run"),
            "servers": len(local), "jailed": sum(1 for s in local if s["jailed"]),
            "pending": sum(1 for r in runs if r["status"] == "pending" and r["changes"] and r["workspace"]),
        },
    }


def _diff(key: str, run_id: str) -> str:
    from aegis_jail import workspace
    from aegis_jail.runner import load_report
    base = (paths.aegis_home() / "runs").resolve()
    rd = (base / key / run_id).resolve()
    if base not in rd.parents or not (rd / "report.json").exists():
        raise FileNotFoundError("run not found")
    rep = load_report(rd)
    ws = rd / "workspace"
    if not ws.exists():
        return "The working copy of this run was already removed."
    chs = [workspace.Change(**c) for c in rep.changes]
    return workspace.unified_diff(Path(rep.project), ws, chs) or "No changes."


def _change_marker() -> str:
    """Changes when something the page shows changes (not on every Autopilot pass)."""
    home = paths.aegis_home()
    files = [watch.events_path(), watch.watch_dir() / "resolved.json", watch.watch_dir() / "config.json",
             watch.watch_dir() / "originals.json", watch.watch_dir() / "active.json",
             *(home / "mcp").glob("*.jsonl"), *(home / "runs").glob("*/*/report.json")]
    parts = []
    for p in files:
        try:
            parts.append(f"{p.name}:{p.stat().st_mtime_ns}")
        except OSError:
            parts.append("0")
    import hashlib
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------------------------- server
class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "aegis-dashboard"
    sys_version = ""

    def log_message(self, fmt, *args):  # quiet
        return

    # -- guards
    def _host_ok(self) -> bool:
        port = self.server.server_address[1]
        return self.headers.get("Host", "") in (f"127.0.0.1:{port}", f"localhost:{port}")

    def _authed(self) -> bool:
        c = cookies.SimpleCookie(self.headers.get("Cookie", ""))
        tok = c[COOKIE].value if COOKIE in c else self.headers.get("X-Aegis-Token", "")
        return secrets.compare_digest(tok, self.server.token)

    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self'; "
                                                     "script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, code: int = 200) -> None:
        self._send(code, json.dumps(data).encode(), "application/json")

    def do_GET(self) -> None:  # noqa: N802
        if not self._host_ok():
            return self._send(421, b"Misdirected request", "text/plain")
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if "t" in q:
            if secrets.compare_digest(q["t"][0], self.server.token):
                return self._send(303, b"", "text/plain", {
                    "Location": "/", "Set-Cookie": f"{COOKIE}={self.server.token}; HttpOnly; SameSite=Strict; Path=/"})
            return self._send(403, b"Wrong token. Open the link that `aegis dashboard` prints.", "text/plain")
        if not self._authed():
            return self._send(401, "Open the dashboard with the link `aegis dashboard` prints.".encode(), "text/plain")
        if u.path in STATIC:
            name, ctype = STATIC[u.path]
            return self._send(200, (WEB / name).read_bytes(), ctype)
        if u.path == "/api/state":
            return self._json(state())
        if u.path == "/api/diff":
            try:
                return self._json({"diff": _diff(q.get("key", [""])[0], q.get("run", [""])[0])})
            except (OSError, ValueError) as e:
                return self._json({"error": str(e)}, 404)
        if u.path == "/api/stream":
            return self._stream()
        return self._send(404, b"Not found", "text/plain")

    def _stream(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        last = None
        try:
            for _ in range(3600):
                mark = _change_marker()
                if mark != last:
                    last = mark
                    self.wfile.write(f"data: {mark}\n\n".encode())
                else:
                    self.wfile.write(b": keep-alive\n\n")
                self.wfile.flush()
                time.sleep(1)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self) -> None:  # noqa: N802
        if not self._host_ok():
            return self._send(421, b"Misdirected request", "text/plain")
        port = self.server.server_address[1]
        origin = self.headers.get("Origin")
        if origin not in (None, f"http://127.0.0.1:{port}", f"http://localhost:{port}") or not self._authed():
            return self._json({"error": "forbidden"}, 403)
        try:
            n = min(int(self.headers.get("Content-Length", "0")), 65536)
            body = json.loads(self.rfile.read(n) or b"{}")
            return self._json(self._action(body))
        except (KeyError, ValueError, OSError) as e:
            return self._json({"error": str(e)}, 400)

    def _action(self, b: dict) -> dict:
        kind = b.get("kind")
        if kind == "event":
            return watch.act(str(b["id"]), str(b["action"]), by="dashboard")
        if kind == "resolve":
            e = watch.resolve(str(b["id"]), str(b.get("status", "resolved")), str(b.get("note", "")), by="dashboard")
            return {"ok": True, "message": f"Marked {e['status']}."}
        if kind == "config":
            return {"ok": True, "config": watch.save_config(dict(b.get("updates") or {})), "message": "Saved."}
        if kind == "jail":
            res = watch.jail_server(str(b["file"]), [str(x) for x in b["jsonpath"]])
            return {"ok": True, "message": "Jailed. Restart the MCP client to use the sandboxed server."
                    if res["changed"] else "Already jailed."}
        if kind == "unjail":
            watch.unjail_server(str(b["file"]), [str(x) for x in b["jsonpath"]])
            return {"ok": True, "message": "Restored the original entry."}
        if kind == "run":
            known = [p["path"] for p in _projects(_runs())]
            return start_run(str(b.get("project", "")), str(b.get("agent", "")), str(b.get("prompt", "")), known)
        if kind == "scan":
            new = watch.scan_once(dict(watch.load_config(), responder="", notify=False))
            return {"ok": True, "message": f"Checked. {len(new)} new event(s)."}
        raise ValueError("unknown action")


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    token = ""


def start(port: int = 7341) -> tuple[Server, str]:
    """Listen on 127.0.0.1. A busy preferred port moves on to the next ones (port 0 means "any free port")."""
    last: OSError | None = None
    for p in ([0] if port == 0 else range(port, port + 10)):
        try:
            srv = Server(("127.0.0.1", p), Handler)
            break
        except OSError as e:
            last = e
    else:
        raise last or OSError("no free port")
    srv.token = token()
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/?t={srv.token}"
    return srv, url


def main(port: int = 7341, open_browser: bool = True) -> int:
    st = watch.status()
    if st["running"] and st.get("dashboard"):
        url = st["dashboard"]
        print(f"Autopilot is running. Dashboard: {url}")
        if open_browser:
            webbrowser.open(url)
        return 0
    try:
        srv, url = start(port)
    except OSError as e:
        print(f"aegis: could not start the dashboard ({e}). Try another port: aegis dashboard --port 7400")
        return 1
    print(f"Aegis dashboard: {url}\n(Autopilot is not running in the background; this page checks on demand. "
          "Ctrl+C to stop.)", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        srv.shutdown()
    return 0
