import shutil
import tempfile
import unittest
from pathlib import Path

from aegis_jail.sandbox.windows import AppContainerBackend, _cmdline


class WindowsPlanTest(unittest.TestCase):
    """Pure-logic tests of the Windows ACL planner (run on every OS)."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        for d in ("home/.ssh", "home/code/a", "home/.aegis/runs/ws", "home/docs"):
            (self.root / d).mkdir(parents=True)
        (self.root / "home/.ssh/id_rsa").write_text("k")
        (self.root / "home/notes.txt").write_text("n")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_carves_denied_paths_out_of_grants(self):
        h = self.root / "home"
        rules = [("deny", h), ("read", h), ("deny", h / ".ssh"), ("deny", h / ".aegis"),
                 ("write", h / ".aegis" / "runs" / "ws")]
        plan = {(p.relative_to(self.root).as_posix(), perm, inh)
                for p, perm, inh in AppContainerBackend.plan_acls(rules)}
        self.assertIn(("home", "RX", False), plan)
        self.assertIn(("home/code", "RX", True), plan)
        self.assertIn(("home/notes.txt", "RX", True), plan)
        self.assertIn(("home/.aegis/runs/ws", "M", True), plan)
        paths = {p for p, _, _ in plan}
        self.assertFalse(any(p.startswith("home/.ssh") for p in paths), plan)
        self.assertNotIn("home/.aegis", paths)

    def test_grant_inside_later_deny_is_dropped(self):
        h = self.root / "home"
        rules = [("read", h / "code"), ("deny", h)]
        self.assertEqual(AppContainerBackend.plan_acls(rules), [])

    def test_cmd_quoting(self):
        line = _cmdline([r"C:\Windows\System32\cmd.exe", "/d", "/s", "/c", '"C:\\Py\\python.exe" -m unittest'])
        self.assertEqual(line, r'C:\Windows\System32\cmd.exe /d /s /c ""C:\Py\python.exe" -m unittest"')


if __name__ == "__main__":
    unittest.main()
