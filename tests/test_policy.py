import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from aegis_jail import paths
from aegis_jail.agents import _symlink_chain
from aegis_jail.policy import Grant, Profile, baseline_profile
from aegis_jail.probe import expected_fs

from tests.helpers import isolated_aegis_home


class PolicyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        isolated_aegis_home()

    def compile(self, grants, phase="task", env=None):
        prof = Profile("t", "command", grants)
        home = paths.user_home()
        return prof.compile(phase, project=home / "proj", workspace=paths.aegis_home() / "ws",
                            tmp=paths.aegis_home() / "tmp", host_env=env or {"PATH": "/bin", "GH_TOKEN": "x"})

    def test_default_denies_home_and_secrets(self):
        spec = self.compile([])
        home = paths.user_home()
        self.assertEqual(expected_fs(spec.fs_rules, home / ".ssh" / "id_rsa", "read"), "deny")
        self.assertEqual(expected_fs(spec.fs_rules, home / "other-project" / "a.txt", "read"), "deny")
        self.assertEqual(expected_fs(spec.fs_rules, home / "proj" / "a.txt", "read"), "deny")
        self.assertEqual(expected_fs(spec.fs_rules, paths.aegis_home() / "ws" / "a.txt", "write"), "allow")
        self.assertEqual(expected_fs(spec.fs_rules, home / "x.txt", "write"), "deny")
        self.assertEqual(expected_fs(spec.fs_rules, Path("/usr/bin/env"), "write"), "deny")
        self.assertIsNone(spec.network)

    def test_home_read_does_not_expose_secrets_or_project(self):
        spec = self.compile([Grant(id="home-read", kind="read", path="~")])
        home = paths.user_home()
        self.assertEqual(expected_fs(spec.fs_rules, home / "notes.txt", "read"), "allow")
        self.assertEqual(expected_fs(spec.fs_rules, home / ".ssh" / "id_rsa", "read"), "deny")
        self.assertEqual(expected_fs(spec.fs_rules, home / ".aws" / "credentials", "read"), "deny")
        self.assertEqual(expected_fs(spec.fs_rules, home / "proj" / "main.py", "read"), "deny")
        self.assertEqual(expected_fs(spec.fs_rules, paths.aegis_home() / "canary" / "secret.txt", "read"), "deny")

    def test_explicit_secret_grant(self):
        spec = self.compile([Grant(id="secret:ssh", kind="read", path="~/.ssh")])
        self.assertEqual(expected_fs(spec.fs_rules, paths.user_home() / ".ssh" / "id_rsa", "read"), "allow")
        self.assertEqual(expected_fs(spec.fs_rules, paths.user_home() / ".aws" / "x", "read"), "deny")

    def test_network_phases(self):
        grants = [Grant(id="a", kind="net", domains=["*"], phase="setup"),
                  Grant(id="b", kind="net", domains=["API.example.com"], phase="task")]
        expected = ["*"] if sys.platform.startswith("linux") else "all"  # Linux: always via the proxy
        self.assertEqual(self.compile(grants, "setup").network, expected)
        self.assertEqual(self.compile(grants, "task").network, ["api.example.com"])

    def test_env_filtered(self):
        spec = self.compile([])
        self.assertNotIn("GH_TOKEN", spec.env)
        self.assertEqual(spec.env["PATH"], "/bin")
        spec = self.compile([Grant(id="e", kind="env", names=["GH_TOKEN"])])
        self.assertEqual(spec.env["GH_TOKEN"], "x")

    def test_roundtrip_and_validation(self):
        p = Profile("x", "command", [Grant(id="n", kind="net", domains=["a.com"], locked=True)])
        q = Profile.from_dict(p.to_dict())
        self.assertEqual(q.grants[0].domains, ["a.com"])
        self.assertTrue(q.grants[0].locked)
        with self.assertRaises(ValueError):
            Grant(id="bad", kind="read")
        with self.assertRaises(ValueError):
            Profile.from_dict({"aegis": 1, "name": "x", "agent": "c",
                               "grants": [{"id": "a", "kind": "env", "names": ["X"]}] * 2})

    def test_baseline_is_broad(self):
        b = baseline_profile("command", [])
        ids = {g.id for g in b.grants}
        self.assertIn("home-read", ids)
        self.assertIn("net-task-any", ids)


class RuntimePathsTest(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "needs symlinks")
    def test_symlink_chain_keeps_alias_names(self):
        """venv/bin/python -> alias/bin/python3.10, where `alias` is itself a link (uv, pyenv, Homebrew...)."""
        root = Path(tempfile.mkdtemp()).resolve()
        try:
            real = root / "cpython-3.10.20" / "bin"
            real.mkdir(parents=True)
            (real / "python3.10").write_text("")
            (root / "cpython-3.10").symlink_to(root / "cpython-3.10.20")
            (root / "venv" / "bin").mkdir(parents=True)
            link = root / "venv" / "bin" / "python"
            link.symlink_to(root / "cpython-3.10" / "bin" / "python3.10")
            parents = {hop.parent for hop in _symlink_chain(link)}
            self.assertIn(root / "cpython-3.10" / "bin", parents)  # the alias name, not only the final target
            self.assertIn(root / "venv" / "bin", parents)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_runtime_path_not_remounted_inside_a_broad_grant(self):
        isolated_aegis_home()
        home = paths.user_home()
        rp = home / ".local" / "py" / "bin"

        def rules(grants):
            spec = Profile("t", "command", grants).compile(
                "task", project=home / "proj", workspace=paths.aegis_home() / "ws",
                tmp=paths.aegis_home() / "tmp", runtime_paths=[rp], host_env={})
            return spec.fs_rules

        self.assertNotIn(("read", rp), rules([Grant(id="h", kind="read", path="~")]))
        self.assertIn(("read", rp), rules([]))


if __name__ == "__main__":
    unittest.main()
