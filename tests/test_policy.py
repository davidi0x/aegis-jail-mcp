import unittest
from pathlib import Path

from aegis_jail import paths
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
        self.assertEqual(self.compile(grants, "setup").network, "all")
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


if __name__ == "__main__":
    unittest.main()
