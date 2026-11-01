import shutil
import tempfile
import unittest
from pathlib import Path

from aegis_jail.sandbox.windows import AppContainerBackend, _cmdline, _parse_icacls


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

    def test_write_grant_is_masked_not_carved(self):
        h = self.root / "home"
        proj = h / "code"
        (proj / ".env").write_text("X=1")
        rules = [("deny", h), ("write", proj), ("deny", proj / ".env")]
        plan = AppContainerBackend.plan_acls(rules)
        self.assertEqual([(p.name, perm, inh) for p, perm, inh in plan], [("code", "M", True)])  # whole, inheritable
        self.assertEqual(AppContainerBackend.plan_masks(rules), [proj / ".env"])
        # a read grant is still carved (nothing needs to be created in it) and masks nothing
        read_rules = [("deny", h), ("read", proj), ("deny", proj / ".env")]
        self.assertEqual(AppContainerBackend.plan_masks(read_rules), [])
        self.assertTrue(any(not inh for _, _, inh in AppContainerBackend.plan_acls(read_rules)))

    def test_grant_inside_later_deny_is_dropped(self):
        h = self.root / "home"
        rules = [("read", h / "code"), ("deny", h)]
        self.assertEqual(AppContainerBackend.plan_acls(rules), [])

    def test_icacls_output_parsing(self):
        explicit = (".env NT AUTHORITY\\SYSTEM:(F)\n         BUILTIN\\Administrators:(F)\n"
                    "         OWNER RIGHTS:(F)\n\nSuccessfully processed 1 files; Failed processing 0 files\n")
        inherited = explicit.replace(":(F)", ":(I)(F)")
        doubled = (".env NT AUTHORITY\\SYSTEM:(F)\n         BUILTIN\\Administrators:(F)\n"
                   "         NT AUTHORITY\\SYSTEM:(I)(F)\n         BUILTIN\\Administrators:(I)(F)\n\n"
                   "Successfully processed 1 files; Failed processing 0 files\n")
        a, b, d = (_parse_icacls(t, ".env") for t in (explicit, inherited, doubled))
        self.assertEqual(a, ["NT AUTHORITY\\SYSTEM:(F)", "BUILTIN\\Administrators:(F)", "OWNER RIGHTS:(F)"])
        self.assertEqual(a, b)                       # inherited == explicit once the marker is ignored
        self.assertEqual(sorted(set(d)), ["BUILTIN\\Administrators:(F)", "NT AUTHORITY\\SYSTEM:(F)"])
        self.assertGreater(len(d), len(set(d)))      # and duplicates are detectable

    def test_cmd_quoting(self):
        line = _cmdline([r"C:\Windows\System32\cmd.exe", "/d", "/s", "/c", '"C:\\Py\\python.exe" -m unittest'])
        self.assertEqual(line, r'C:\Windows\System32\cmd.exe /d /s /c ""C:\Py\python.exe" -m unittest"')


if __name__ == "__main__":
    unittest.main()
