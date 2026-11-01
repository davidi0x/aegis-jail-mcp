"""End-to-end tests with the real OS sandbox (bubblewrap / Seatbelt / AppContainer)."""

import shutil
import unittest
from pathlib import Path

from aegis_jail import paths
from aegis_jail.optimize import optimize
from aegis_jail.policy import Grant, Profile, baseline_profile
from aegis_jail.probe import run_probe
from aegis_jail.agents import Task
from aegis_jail.runner import run_task

from tests.helpers import backend_or_skip, cleanup_aegis_home, demo_copy, demo_task, isolated_aegis_home


def tearDownModule():
    cleanup_aegis_home()


class SandboxTest(unittest.TestCase):
    def setUp(self):
        isolated_aegis_home()
        self.backend = backend_or_skip(self)
        self.project = demo_copy()

    def tearDown(self):
        shutil.rmtree(self.project.parent, ignore_errors=True)
        leftover = paths.user_home() / ".bashrc_aegis_demo"
        self.assertFalse(leftover.exists(), "agent managed to write into the home directory")

    def test_demo_task_passes_and_secrets_stay_hidden(self):
        canary = (paths.canary_dir() / "secret.txt").read_text()
        rep = run_task(self.project, Profile("default", "command"), demo_task(), backend=self.backend, quiet=True)
        log = Path(rep.phases[0].log).read_text(errors="replace")
        self.assertTrue(rep.ok, log)
        self.assertNotIn(canary.strip(), log)
        from aegis_jail import decoys, secretscan
        # Whatever the agent managed to "read" must be a decoy, never a real credential.
        for line in log.splitlines():
            if (line.startswith("[agent] read ") and "Error" not in line and "(empty)" not in line
                    and not line.rstrip().endswith("]")):  # directory listings carry no secret
                self.assertTrue(secretscan.is_decoy_hit(line) or line.endswith("[]"), line)
        if decoys.enabled():
            self.assertTrue(rep.tripwires, "decoy credentials in the output should trip the wire")
        self.assertNotIn("exfiltration: SENT", log)
        self.assertEqual([c["path"] for c in rep.changes], ["src/calc.py"])
        # The real project is untouched until `aegis apply`.
        self.assertIn("a - b", (self.project / "src" / "calc.py").read_text())

    def test_allowlist_blocks_and_logs_other_hosts(self):
        prof = Profile("allow", "command", [Grant(id="n", kind="net", domains=["example.com"], phase="task")])
        rep = run_task(self.project, prof, demo_task(), backend=self.backend, quiet=True)
        self.assertTrue(rep.ok, Path(rep.phases[0].log).read_text(errors="replace"))
        self.assertIn("collector.evil.example:80", rep.blocked_network)

    def test_probe_boundaries_hold(self):
        res = run_probe(self.project, Profile("default", "command"), backend=self.backend)
        bad = [c for c in res["checks"] if c["status"] in ("fail", "error")]
        self.assertEqual(bad, [], bad)
        ids = {c["id"] for c in res["checks"]}
        for must in ("read-canary-secret", "read-original-project", "write-home", "write-workspace", "net-direct"):
            self.assertIn(must, ids)

    def test_probe_with_home_read_still_hides_secrets(self):
        prof = Profile("home", "command", [Grant(id="home-read", kind="read", path="~")])
        res = run_probe(self.project, prof, backend=self.backend)
        bad = [c for c in res["checks"] if c["status"] in ("fail", "error")]
        self.assertEqual(bad, [], bad)
        canary = next(c for c in res["checks"] if c["id"] == "read-canary-secret")
        self.assertEqual(canary["expect"], "deny")

    def test_optimize_removes_unneeded_access(self):
        start = baseline_profile("command", [])
        res = optimize(self.project, start, demo_task(), max_runs=12, confirm=1, backend=self.backend,
                       log=lambda _: None)
        self.assertFalse(res.baseline_failed, [t.to_dict() for t in res.trials])
        removed = {g.id for g in res.removed}
        self.assertIn("home-read", removed)
        self.assertIn("net-task-any", removed)
        self.assertEqual(res.confirmed, 1)
        self.assertIsNotNone(res.final.verified)


class SeccompTest(unittest.TestCase):
    def test_dangerous_syscall_blocked(self):
        isolated_aegis_home()
        backend = backend_or_skip(self)
        from aegis_jail import seccomp
        if not getattr(backend, "seccomp_enabled", False):
            self.skipTest("seccomp not active on this host")
        nr = seccomp._BLOCK["ptrace"][seccomp.arch()]
        project = demo_copy()
        try:
            code = (f"import ctypes; libc=ctypes.CDLL(None,use_errno=True); libc.syscall({nr},0,0,0,0); "
                    "import os; print('EPERM' if ctypes.get_errno()==1 else 'OPEN')")
            task = Task(name="s", agent="command", command=["{python}", "-c", code], timeout=30)
            rep = run_task(project, Profile("d", "command"), task, backend=backend, quiet=True)
            self.assertIn("EPERM", Path(rep.phases[0].log).read_text(errors="replace"))
        finally:
            shutil.rmtree(project.parent, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()


class LearnTest(unittest.TestCase):
    """optimize learns exactly the host a task needs, starting from no network."""

    def test_learns_needed_host(self):
        import http.server
        import socketserver
        import threading
        from aegis_jail.agents import Task

        isolated_aegis_home()
        backend = backend_or_skip(self)

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, *a):
                pass

        srv = socketserver.TCPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        project = demo_copy()
        try:
            agent = project / "tools" / "needs_net.py"
            agent.write_text(
                "import os, urllib.request\n"
                "for k in ('NO_PROXY', 'no_proxy'): os.environ.pop(k, None)\n"
                f"body = urllib.request.urlopen('http://127.0.0.1:{srv.server_address[1]}/', timeout=10).read()\n"
                "assert body == b'ok', body\n")
            task = Task(name="net", agent="command", command=["{python}", "tools/needs_net.py"], timeout=60)
            res = optimize(project, Profile("default", "command"), task, max_runs=8, confirm=1, backend=backend,
                           escalate=[], log=lambda _: None)
            self.assertFalse(res.baseline_failed, [t.to_dict() for t in res.trials])
            want = f"net-task:127.0.0.1:{srv.server_address[1]}"
            self.assertEqual([g.id for g in res.added], [want])
            self.assertIn(want, [g.id for g in res.final.grants])
        finally:
            srv.shutdown()
            srv.server_close()
            shutil.rmtree(project.parent, ignore_errors=True)
