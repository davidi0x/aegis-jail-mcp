"""Autopilot (aegis watch), its MCP tools, the Claude Code context hooks and the dashboard server."""

import http.client
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aegis_jail import dashboard, hook, mcpserver, watch


class WatchBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="aegis-watch-")).resolve()
        self.home = self.tmp / "home"
        self.home.mkdir()
        self._old = os.environ.get("AEGIS_HOME")
        os.environ["AEGIS_HOME"] = str(self.tmp / "aegis")
        self.patch = mock.patch.object(watch, "_home", return_value=self.home)
        self.patch.start()
        watch.save_config({"notify": False, "scan_projects": False})

    def tearDown(self):
        self.patch.stop()
        if self._old is None:
            os.environ.pop("AEGIS_HOME", None)
        else:
            os.environ["AEGIS_HOME"] = self._old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_claude_config(self, servers):
        (self.home / ".claude.json").write_text(json.dumps({"mcpServers": servers}), encoding="utf-8")


class WatchTest(WatchBase):
    def test_finds_unjailed_servers_once(self):
        self.write_claude_config({
            "files": {"command": "npx", "args": ["-y", "server-filesystem", "/"]},
            "safe": {"command": "aegis", "args": ["mcp-jail", "--name", "safe", "--", "python3", "s.py"]},
            "aegis": {"command": "python3", "args": ["/x/scripts/aegis.py", "mcp-server"]},
            "remote": {"url": "https://mcp.example.com/sse"},
        })
        servers = {s["name"]: s for s in watch.mcp_servers()}
        self.assertFalse(servers["files"]["jailed"])
        self.assertTrue(servers["safe"]["jailed"])
        self.assertTrue(servers["aegis"]["jailed"])
        self.assertTrue(servers["remote"]["remote"])
        new = watch.scan_once()
        kinds = sorted(e.kind for e in new)
        self.assertEqual(kinds, ["mcp_remote", "mcp_unjailed"])
        self.assertEqual(watch.scan_once(), [])  # same findings are not repeated

    def test_jail_and_restore(self):
        self.write_claude_config({"gh": {"command": "npx", "args": ["server-github"], "env": {"GITHUB_TOKEN": "x"}}})
        ev = next(e for e in watch.scan_once() if e.kind == "mcp_unjailed")
        res = watch.act(ev.id, "jail", by="test")
        self.assertTrue(res["changed"])
        entry = json.loads((self.home / ".claude.json").read_text())["mcpServers"]["gh"]
        self.assertTrue(watch.is_jailed(entry))
        self.assertIn("mcp-jail", entry["args"])
        self.assertEqual(entry["args"][entry["args"].index("--pass-env") + 1], "GITHUB_TOKEN")
        self.assertEqual(entry["args"][-2:], ["npx", "server-github"])
        self.assertEqual(entry["env"]["GITHUB_TOKEN"], "x")  # the user's variables are kept
        self.assertEqual(watch.get_event(ev.id)["status"], "resolved")
        watch.unjail_server(str(self.home / ".claude.json"), ["mcpServers", "gh"])
        entry = json.loads((self.home / ".claude.json").read_text())["mcpServers"]["gh"]
        self.assertEqual(entry["command"], "npx")
        self.assertEqual(watch.get_event(ev.id)["status"], "open")  # undo brings the warning back

    def test_auto_jail(self):
        watch.save_config({"auto_jail": True})
        self.write_claude_config({"db": {"command": "npx", "args": ["server-postgres"]}})
        watch.scan_once()
        entry = json.loads((self.home / ".claude.json").read_text())["mcpServers"]["db"]
        self.assertTrue(watch.is_jailed(entry))

    def test_audit_log_and_runs(self):
        mcp = Path(os.environ["AEGIS_HOME"]) / "mcp"
        mcp.mkdir(parents=True)
        log = mcp / "weather.jsonl"
        lines = [{"time": 1, "event": "start"},
                 {"time": 2, "event": "tool_hidden", "tool": "get_weather",
                  "reason": "definition changed since it was pinned (possible rug pull)"},
                 {"time": 3, "event": "tool_call", "tool": "rm", "allowed": False, "blocked_reason": "not allowed"}]
        log.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
        run = Path(os.environ["AEGIS_HOME"]) / "runs" / "shop-1" / "20260101-000000-aaaaaa"
        run.mkdir(parents=True)
        (run / "report.json").write_text(json.dumps({
            "run_id": run.name, "project": str(self.tmp), "started": 5, "status": "pending", "tripwires": ["decoy read"],
            "changes": [], "phases": [{"name": "agent", "net_events": [{"host": "evil.example", "port": 443, "allowed": False}]}]}))
        kinds = sorted(e.kind for e in watch.scan_once())
        self.assertEqual(kinds, ["mcp_blocked_call", "mcp_rug_pull", "network_blocked", "tripwire"])
        with log.open("a") as f:
            f.write(json.dumps({"time": 4, "event": "sampling_blocked"}) + "\n")
        self.assertEqual([e.kind for e in watch.scan_once()], ["mcp_sampling_blocked"])  # only the new line
        trip = next(e for e in watch.open_events("high") if e["kind"] == "tripwire")
        self.assertIn("discard", trip["actions"])

    def test_resolve(self):
        self.write_claude_config({"x": {"command": "node", "args": ["x.js"]}})
        ev = watch.scan_once()[0]
        watch.resolve(ev.id, "ignored", "accepted", by="test")
        self.assertEqual(watch.open_events(), [])
        watch.resolve(ev.id, "open")
        self.assertEqual(len(watch.open_events()), 1)
        with self.assertRaises(ValueError):
            watch.act(ev.id, "discard")  # not an action of this event

    def test_responder_command_is_limited_to_aegis_tools(self):
        cmd = watch.responder_command("claude")
        allowed = cmd[cmd.index("--allowedTools") + 1].split(",")
        self.assertTrue(allowed and all(t.startswith("mcp__aegis__") for t in allowed))
        self.assertNotIn("mcp__aegis__aegis_apply", allowed)
        self.assertIn("--strict-mcp-config", cmd)


class StatusTest(WatchBase):
    def test_status_reports_a_live_daemon_only(self):
        self.assertFalse(watch.status()["running"])
        watch._write_json(watch.watch_dir() / "daemon.json", {"pid": os.getpid(), "dashboard": "http://127.0.0.1:1/"})
        watch.scan_once()
        st = watch.status()
        self.assertTrue(st["running"])
        self.assertTrue(watch._pid_alive(os.getpid()))


class AgentFacingTest(WatchBase):
    def test_mcp_tools(self):
        self.write_claude_config({"fs": {"command": "npx", "args": ["server-filesystem"]}})
        text = mcpserver.tool_events({})
        self.assertIn("full user rights", text)
        ev = watch.open_events()[0]
        self.assertIn("Jailed", mcpserver.tool_jail_server({"event": ev["id"]}))
        self.assertIn("No open security events", mcpserver.tool_events({}))
        names = {t["name"] for t in mcpserver.TOOLS}
        self.assertTrue({"aegis_events", "aegis_jail_mcp_server", "aegis_resolve", "aegis_watch_status"} <= names)

    def test_context_hooks(self):
        self.write_claude_config({"fs": {"command": "npx", "args": ["server-filesystem"]}})
        watch.scan_once()
        out = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO("{}")), mock.patch.object(sys, "stdout", out):
            hook.context_hook("SessionStart", only_new=False)
        data = json.loads(out.getvalue())
        self.assertEqual(data["hookSpecificOutput"]["hookEventName"], "SessionStart")
        self.assertIn("aegis_jail_mcp_server", data["hookSpecificOutput"]["additionalContext"])
        out = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO("{}")), mock.patch.object(sys, "stdout", out):
            hook.context_hook("UserPromptSubmit", only_new=True)
        self.assertEqual(out.getvalue(), "")  # already announced


class DashboardTest(WatchBase):
    def setUp(self):
        super().setUp()
        self.srv, self.url = dashboard.start(0)
        self.port = self.srv.server_address[1]
        self.token = self.srv.token

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        super().tearDown()

    def req(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": f"127.0.0.1:{self.port}", **(headers or {})}
        c.request(method, path, body=json.dumps(body) if body is not None else None, headers=h)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r, data

    def test_needs_token(self):
        r, _ = self.req("GET", "/api/state")
        self.assertEqual(r.status, 401)
        r, _ = self.req("GET", "/?t=wrong")
        self.assertEqual(r.status, 403)
        r, _ = self.req("GET", f"/?t={self.token}")
        self.assertEqual(r.status, 303)
        self.assertIn("HttpOnly", r.getheader("Set-Cookie"))
        self.assertIn("SameSite=Strict", r.getheader("Set-Cookie"))

    def test_state_and_actions(self):
        self.write_claude_config({"fs": {"command": "npx", "args": ["server-filesystem"]}})
        auth = {"Cookie": f"{dashboard.COOKIE}={self.token}"}
        r, data = self.req("GET", "/api/state", headers=auth)
        self.assertEqual(r.status, 200)
        st = json.loads(data)
        self.assertEqual(st["counts"]["servers"], 1)
        ev = next(e for e in st["events"] if e["kind"] == "mcp_unjailed")
        r, _ = self.req("POST", "/api/action", {"kind": "resolve", "id": ev["id"], "status": "ignored"},
                        {**auth, "Origin": "http://evil.example"})
        self.assertEqual(r.status, 403)
        r, data = self.req("POST", "/api/action", {"kind": "event", "id": ev["id"], "action": "jail"},
                           {**auth, "Origin": f"http://127.0.0.1:{self.port}", "Content-Type": "application/json"})
        self.assertEqual(r.status, 200, data)
        self.assertTrue(watch.is_jailed(json.loads((self.home / ".claude.json").read_text())["mcpServers"]["fs"]))
        for page in ("/", "/app.js", "/app.css"):
            r, _ = self.req("GET", page, headers=auth)
            self.assertEqual(r.status, 200)
            self.assertIn("default-src 'self'", r.getheader("Content-Security-Policy"))

    def test_run_from_dashboard_is_validated(self):
        with self.assertRaises(ValueError):
            dashboard.start_run("/etc", "claude-code", "x", known=[str(self.tmp)])
        with self.assertRaises(ValueError):
            dashboard.start_run(str(self.tmp), "rm -rf", "x", known=[str(self.tmp)])
        with self.assertRaises(ValueError):
            dashboard.start_run(str(self.tmp), "codex", "   ", known=[str(self.tmp)])
        auth = {"Cookie": f"{dashboard.COOKIE}={self.token}", "Origin": f"http://127.0.0.1:{self.port}"}
        r, _ = self.req("POST", "/api/action", {"kind": "run", "project": "/", "agent": "codex", "prompt": "hi"}, auth)
        self.assertEqual(r.status, 400)
        for font in ("/fonts/figtree.woff2", "/fonts/jetbrains-mono.woff2"):
            r, _ = self.req("GET", font, headers=auth)
            self.assertEqual(r.status, 200)

    def test_rejects_foreign_host(self):
        r, _ = self.req("GET", "/api/state", headers={"Host": "attacker.example",
                                                      "Cookie": f"{dashboard.COOKIE}={self.token}"})
        self.assertEqual(r.status, 421)

    def test_diff_cannot_escape_runs(self):
        auth = {"Cookie": f"{dashboard.COOKIE}={self.token}"}
        r, _ = self.req("GET", "/api/diff?key=..&run=..", headers=auth)
        self.assertEqual(r.status, 404)


if __name__ == "__main__":
    unittest.main()
