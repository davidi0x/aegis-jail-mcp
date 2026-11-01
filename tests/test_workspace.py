import shutil
import tempfile
import unittest
from pathlib import Path

from aegis_jail import workspace


class WorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.proj = self.root / "proj"
        (self.proj / "src").mkdir(parents=True)
        (self.proj / "src" / "a.py").write_text("a = 1\n")
        (self.proj / "b.txt").write_text("b\n")
        (self.proj / ".aegis").mkdir()
        (self.proj / ".aegis" / "task.json").write_text("{}")
        self.ws = self.root / "ws"

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_copy_diff_apply(self):
        base = workspace.create(self.proj, self.ws)
        self.assertFalse((self.ws / ".aegis").exists())
        (self.ws / "src" / "a.py").write_text("a = 2\n")
        (self.ws / "b.txt").unlink()
        (self.ws / "c.txt").write_text("new\n")
        (self.ws / "node_modules").mkdir()
        (self.ws / "node_modules" / "x.js").write_text("ignored")
        chs = workspace.changes(base, self.ws)
        self.assertEqual({(c.path, c.kind) for c in chs},
                         {("src/a.py", "modified"), ("b.txt", "deleted"), ("c.txt", "added")})
        diff = workspace.unified_diff(self.proj, self.ws, chs)
        self.assertIn("-a = 1", diff)
        self.assertIn("+a = 2", diff)
        workspace.apply(self.proj, self.ws, base, chs)
        self.assertEqual((self.proj / "src" / "a.py").read_text(), "a = 2\n")
        self.assertFalse((self.proj / "b.txt").exists())
        self.assertEqual((self.proj / "c.txt").read_text(), "new\n")

    def test_conflict_detected(self):
        base = workspace.create(self.proj, self.ws)
        (self.ws / "src" / "a.py").write_text("agent\n")
        (self.proj / "src" / "a.py").write_text("human edit\n")
        chs = workspace.changes(base, self.ws)
        with self.assertRaises(workspace.ApplyConflict):
            workspace.apply(self.proj, self.ws, base, chs)
        self.assertEqual((self.proj / "src" / "a.py").read_text(), "human edit\n")


if __name__ == "__main__":
    unittest.main()
