import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from aegis_jail import mcpserver
from aegis_jail.hook import check
from aegis_jail.mcpjail import McpFilter, ToolFirewall

from tests.helpers import ROOT, backend_or_skip, demo_copy, isolated_aegis_home

FAKE = Path(__file__).resolve().parent / "fake_mcp_server.py"


def rpc(i, method, params=None):
    m = {"jsonrpc": "2.0", "id": i, "method": method}
    if params is not None:
        m["params"] = params
    return json.dumps(m) + "\n"


class FilterTest(unittest.TestCase):
    def test_firewall_globs(self):
        fw = ToolFirewall(allow=["read_*", "fetch"], deny=["read_secret"])
        self.assertTrue(fw.permits("read_file"))
        self.assertTrue(fw.permits("fetch"))
        self.assertFalse(fw.permits("read_secret"))
        self.assertFalse(fw.permits("delete_all"))
        self.assertTrue(ToolFirewall().permits("anything"))

    def test_hides_and_blocks(self):
        f = McpFilter(ToolFirewall(deny=["delete_*"]))
        fwd, reply = f.from_client(rpc(7, "tools/list").encode())
        self.assertIsNotNone(fwd)
        self.assertIsNone(reply)
        server = {"jsonrpc": "2.0", "id": 7, "result": {"tools": [{"name": "a"}, {"name": "delete_x"}]}}
        out = json.loads(f.from_server(json.dumps(server).encode()))
        self.assertEqual([t["name"] for t in out["result"]["tools"]], ["a"])
        fwd, reply = f.from_client(rpc(8, "tools/call", {"name": "delete_x"}).encode())
        self.assertIsNone(fwd)
        self.assertTrue(json.loads(reply)["result"]["isError"])
        fwd, reply = f.from_client(rpc(9, "tools/call", {"name": "a"}).encode())
        self.assertIsNotNone(fwd)


class HookTest(unittest.TestCase):
    def test_blocks_credentials(self):
        self.assertIsNotNone(check({"tool_name": "Read", "tool_input": {"file_path": "~/.ssh/id_rsa"}}))
        self.assertIsNotNone(check({"tool_name": "Bash", "tool_input": {"command": "cat ~/.aws/credentials"}}))
        self.assertIsNotNone(check({"tool_name": "Grep", "tool_input": {"pattern": "x", "path": "~/.ssh"}}))
        self.assertIsNone(check({"tool_name": "Read", "tool_input": {"file_path": "src/main.py"}}))
        self.assertIsNone(check({"tool_name": "Bash", "tool_input": {"command": "npm test"}}))


class McpServerTest(unittest.TestCase):
    def test_protocol(self):
        init = mcpserver.handle(json.loads(rpc(1, "initialize", {"protocolVersion": "2025-06-18"})))
        self.assertEqual(init["result"]["protocolVersion"], "2025-06-18")
        self.assertIsNone(mcpserver.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        tools = mcpserver.handle(json.loads(rpc(2, "tools/list")))["result"]["tools"]
        self.assertIn("aegis_run", [t["name"] for t in tools])
        err = mcpserver.handle(json.loads(rpc(3, "nope")))
        self.assertEqual(err["error"]["code"], -32601)

    def test_run_tool_in_sandbox(self):
        isolated_aegis_home()
        backend_or_skip(self)
        project = demo_copy()
        try:
            py = sys.executable.replace("\\", "/")
            cmd = (f'"{py}" -c "import os,pathlib; pathlib.Path(\'out.txt\').write_text(\'hi\'); '
                   f'print(os.path.exists(os.path.expanduser(\'~/.ssh\')))"')
            out = io.StringIO()
            mcpserver.serve(io.StringIO(rpc(1, "tools/call", {"name": "aegis_run", "arguments": {
                "project": str(project), "command": cmd}})), out)
            res = json.loads(out.getvalue())["result"]
            text = res["content"][0]["text"]
            self.assertFalse(res["isError"], text)
            self.assertIn("exit code: 0", text)
            self.assertIn("out.txt (added)", text)
            self.assertFalse((project / "out.txt").exists())
        finally:
            shutil.rmtree(project.parent, ignore_errors=True)


class McpJailTest(unittest.TestCase):
    def test_jailed_server(self):
        isolated_aegis_home()
        backend_or_skip(self)
        proj = Path(tempfile.mkdtemp()).resolve()
        try:
            from aegis_jail import paths
            canary = paths.canary_dir() / "secret.txt"
            msgs = "".join([
                rpc(1, "initialize", {}), rpc(2, "tools/list"),
                rpc(3, "tools/call", {"name": "delete_everything"}),
                rpc(4, "tools/call", {"name": "read_secret", "arguments": {"path": str(canary)}}),
                rpc(5, "tools/call", {"name": "write_note", "arguments": {"path": str(paths.user_home() / "aegis-jail-note.txt")}}),
            ])
            r = subprocess.run([sys.executable, str(ROOT / "scripts" / "aegis.py"), "mcp-jail", "--project", str(proj),
                                "--name", "test", "--deny-tools", "delete_*", "--", sys.executable, str(FAKE)],
                               input=msgs, capture_output=True, text=True, timeout=120, env=dict(os.environ))
            replies = {m["id"]: m for m in map(json.loads, r.stdout.strip().splitlines())}
            self.assertEqual(len(replies), 5, r.stdout + r.stderr)
            names = [t["name"] for t in replies[2]["result"]["tools"]]
            self.assertNotIn("delete_everything", names)
            self.assertTrue(replies[3]["result"]["isError"])
            self.assertNotIn("GOT:", replies[4]["result"]["content"][0]["text"])
            self.assertFalse((paths.user_home() / "aegis-jail-note.txt").exists())
            self.assertTrue((paths.aegis_home() / "mcp" / "test.jsonl").exists())
        finally:
            shutil.rmtree(proj, ignore_errors=True)
            note = Path.home() / "aegis-jail-note.txt"
            if note.exists():
                note.unlink()


if __name__ == "__main__":
    unittest.main()
