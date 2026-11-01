import shutil
import tempfile
import unittest
from pathlib import Path

from tests.helpers import fake_aws, fake_github, fake_stripe

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
        base = workspace.create(self.proj, self.ws).baseline
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
        base = workspace.create(self.proj, self.ws).baseline
        (self.ws / "src" / "a.py").write_text("agent\n")
        (self.proj / "src" / "a.py").write_text("human edit\n")
        chs = workspace.changes(base, self.ws)
        with self.assertRaises(workspace.ApplyConflict):
            workspace.apply(self.proj, self.ws, base, chs)
        self.assertEqual((self.proj / "src" / "a.py").read_text(), "human edit\n")


class WorkspaceSecurityTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.proj = self.root / "proj"
        self.proj.mkdir()
        (self.proj / "app.py").write_text("print(1)\n")
        self.ws = self.root / "ws"

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_credential_files_hidden_and_never_deleted(self):
        (self.proj / ".env").write_text(f"STRIPE={fake_stripe()}\n")
        (self.proj / ".env.example").write_text("STRIPE=\n")
        (self.proj / "config.py").write_text(f"KEY = '{fake_aws()}'\n")
        res = workspace.create(self.proj, self.ws)
        self.assertFalse((self.ws / ".env").exists())
        self.assertFalse((self.ws / "config.py").exists())
        self.assertTrue((self.ws / ".env.example").exists())
        self.assertEqual(set(res.hidden), {".env", "config.py"})
        chs = workspace.changes(res.baseline, self.ws, self.proj)
        self.assertEqual(chs, [])  # hidden files are not "deleted"
        self.assertTrue((self.root / "ws").exists())

    def test_expose_glob(self):
        (self.proj / ".env").write_text("X=1\n")
        res = workspace.create(self.proj, self.ws, expose=[".env"])
        self.assertTrue((self.ws / ".env").exists())
        self.assertEqual(res.hidden, {})

    def test_git_credentials_stripped(self):
        git = self.proj / ".git"
        git.mkdir()
        (git / "config").write_text(f'[remote "origin"]\n\turl = https://x:{fake_github()}@github.com/a/b\n'
                                    '[credential]\n\thelper = store\n')
        workspace.create(self.proj, self.ws)
        cfg = (self.ws / ".git" / "config").read_text()
        self.assertNotIn("ghp_", cfg)
        self.assertNotIn("helper", cfg)
        self.assertIn("https://github.com/a/b", cfg)

    def test_apply_refuses_symlinked_path(self):
        outside = self.root / "outside"
        outside.mkdir()
        (self.proj / "docs").symlink_to(outside)
        base = workspace.create(self.proj, self.ws).baseline
        (self.ws / "docs").unlink()
        (self.ws / "docs").mkdir()
        (self.ws / "docs" / "authorized_keys").write_text("ssh-rsa ATTACKER\n")
        chs = workspace.changes(base, self.ws, self.proj)
        with self.assertRaises(workspace.ApplyConflict):
            workspace.apply(self.proj, self.ws, base, chs, allow_risky=True)
        self.assertFalse((outside / "authorized_keys").exists())

    def test_risky_changes_need_approval(self):
        base = workspace.create(self.proj, self.ws).baseline
        (self.ws / ".claude").mkdir()
        (self.ws / ".claude" / "settings.json").write_text('{"hooks": {}}')
        (self.ws / ".mcp.json").write_text("{}")
        (self.ws / "notes.md").write_text("hello \U000e0069\U000e0067\U000e006e\n")  # tag-smuggled text
        (self.ws / "app.py").write_text("print(2)\n")
        chs = {c.path: c for c in workspace.changes(base, self.ws, self.proj)}
        self.assertTrue(chs[".claude/settings.json"].risks)
        self.assertTrue(chs[".mcp.json"].risks)
        self.assertTrue(any("invisible" in r for r in chs["notes.md"].risks))
        self.assertEqual(chs["app.py"].risks, [])
        with self.assertRaises(workspace.RiskyChanges):
            workspace.apply(self.proj, self.ws, base, list(chs.values()))
        self.assertEqual((self.proj / "app.py").read_text(), "print(1)\n")  # nothing applied
        workspace.apply(self.proj, self.ws, base, list(chs.values()), allow_risky=True)
        self.assertTrue((self.proj / ".mcp.json").exists())

    def test_refuses_home_as_project(self):
        from aegis_jail import paths
        with self.assertRaises(workspace.UnsafeProject):
            workspace.check_project_root(paths.user_home())
        with self.assertRaises(workspace.UnsafeProject):
            workspace.check_project_root(Path("/"))

    def test_diff_is_terminal_safe(self):
        base = workspace.create(self.proj, self.ws).baseline
        (self.ws / "app.py").write_text("\x1b]52;c;cHduZWQ=\x07print(3)\n")
        diff = workspace.unified_diff(self.proj, self.ws, workspace.changes(base, self.ws, self.proj))
        self.assertNotIn("\x1b", diff)
        self.assertIn("\\x1b", diff)


if __name__ == "__main__":
    unittest.main()
