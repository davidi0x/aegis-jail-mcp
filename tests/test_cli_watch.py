"""The `aegis watch`, `aegis events` and `aegis dashboard` commands, run as a user would run them."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class CliWatchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="aegis-cli-")).resolve()
        (self.tmp / "home").mkdir()
        self.env = dict(os.environ, HOME=str(self.tmp / "home"), USERPROFILE=str(self.tmp / "home"),
                        AEGIS_HOME=str(self.tmp / "aegis"), PYTHONPATH=str(ROOT))
        (self.tmp / "home" / ".claude.json").write_text(json.dumps(
            {"mcpServers": {"fs": {"command": "npx", "args": ["server-filesystem"]}}}), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def aegis(self, *args, timeout=60):
        return subprocess.run([sys.executable, "-m", "aegis_jail", *args], capture_output=True, text=True,
                              env=self.env, timeout=timeout, stdin=subprocess.DEVNULL)

    def test_status_set_and_once(self):
        r = self.aegis("watch", "status")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("not running", r.stdout)
        r = self.aegis("watch", "set", "auto_jail=off", "interval=9", "notify=off", "scan_projects=off")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("9", r.stdout)
        r = self.aegis("watch", "set", "responder=gemini")
        self.assertNotEqual(r.returncode, 0)  # not one of '', claude, codex
        r = self.aegis("watch", "once")
        self.assertIn("1 new event", r.stdout)
        self.assertIn("full user rights", r.stdout)
        self.assertIn("0 new event", self.aegis("watch", "once").stdout)  # nothing repeated

    def test_events_list_resolve_and_act(self):
        self.aegis("watch", "set", "notify=off", "scan_projects=off")
        self.aegis("watch", "once")
        listing = self.aegis("events").stdout
        self.assertIn("[jail]", listing)
        event_id = listing.split()[0]
        r = self.aegis("events", "--act", f"{event_id}:jail")
        self.assertEqual(r.returncode, 0, r.stderr)
        cfg = json.loads((self.tmp / "home" / ".claude.json").read_text())
        self.assertIn("mcp-jail", cfg["mcpServers"]["fs"]["args"])
        self.assertIn("No open events", self.aegis("events").stdout)
        r = self.aegis("events", "--all")
        self.assertIn("resolved", r.stdout)
        r = self.aegis("events", "--resolve", event_id)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_dashboard_command_serves_the_page(self):
        import re
        import urllib.request
        proc = subprocess.Popen([sys.executable, "-m", "aegis_jail", "dashboard", "--no-open", "--port", "0"],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=self.env,
                                stdin=subprocess.DEVNULL)
        try:
            line = proc.stdout.readline()
            m = re.search(r"(http://127\.0\.0\.1:(\d+)/\?t=([\w-]+))", line)
            self.assertTrue(m, line)
            req = urllib.request.Request(f"http://127.0.0.1:{m.group(2)}/api/state", headers={"X-Aegis-Token": m.group(3)})
            data = json.load(urllib.request.urlopen(req, timeout=20))
            self.assertEqual(data["counts"]["servers"], 1)
            self.assertIn("agents", data)
        finally:
            proc.terminate()
            proc.wait(timeout=10)
            proc.stdout.close()

    def test_every_command_has_help(self):
        for cmd in ("watch", "events", "dashboard", "mcp-jail", "mcp-pins", "mcp-server", "scan", "probe", "optimize"):
            r = self.aegis(cmd, "--help")
            self.assertEqual(r.returncode, 0, f"{cmd}: {r.stderr}")


if __name__ == "__main__":
    unittest.main()
