"""End-to-end tests with the real OS sandbox (bubblewrap / Seatbelt / AppContainer)."""

import shutil
import unittest
from pathlib import Path

from hydra_guard import paths
from hydra_guard.optimize import optimize
from hydra_guard.policy import Grant, Profile, baseline_profile
from hydra_guard.probe import run_probe
from hydra_guard.runner import run_task

from tests.helpers import backend_or_skip, cleanup_hydra_home, demo_copy, demo_task, isolated_hydra_home


def tearDownModule():
    cleanup_hydra_home()


class SandboxTest(unittest.TestCase):
    def setUp(self):
        isolated_hydra_home()
        self.backend = backend_or_skip(self)
        self.project = demo_copy()

    def tearDown(self):
        shutil.rmtree(self.project.parent, ignore_errors=True)
        leftover = paths.user_home() / ".bashrc_hydra_demo"
        self.assertFalse(leftover.exists(), "agent managed to write into the home directory")

    def test_demo_task_passes_and_secrets_stay_hidden(self):
        canary = (paths.canary_dir() / "secret.txt").read_text()
        rep = run_task(self.project, Profile("default", "command"), demo_task(), backend=self.backend, quiet=True)
        log = Path(rep.phases[0].log).read_text(errors="replace")
        self.assertTrue(rep.ok, log)
        self.assertNotIn("GOT DATA", log)
        self.assertNotIn(canary.strip(), log)
        self.assertNotIn("exfiltration: SENT", log)
        self.assertEqual([c["path"] for c in rep.changes], ["src/calc.py"])
        # The real project is untouched until `hydra apply`.
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


if __name__ == "__main__":
    unittest.main()
