from __future__ import annotations

import os
import secrets
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "aegis_jail" / "demo"

_AEGIS_HOME: Path | None = None


def isolated_aegis_home() -> Path:
    """Use a throwaway AEGIS_HOME inside the real home (so it is a denied area)."""
    global _AEGIS_HOME
    if _AEGIS_HOME is None:
        _AEGIS_HOME = Path.home() / f".aegis-test-{secrets.token_hex(4)}"
        os.environ["AEGIS_HOME"] = str(_AEGIS_HOME)
    return _AEGIS_HOME


def cleanup_aegis_home() -> None:
    if _AEGIS_HOME and _AEGIS_HOME.exists():
        shutil.rmtree(_AEGIS_HOME, ignore_errors=True)


def demo_copy() -> Path:
    d = Path(tempfile.mkdtemp(prefix="aegis-demo-")).resolve() / "demo-project"
    shutil.copytree(DEMO, d)
    return d


def demo_task():
    from aegis_jail.agents import Task
    py = sys.executable
    return Task(name="fix-calc", agent="command", prompt="Fix the failing test",
                command=[py, "tools/scripted_agent.py", "{prompt}"],
                verify=f'"{py}" -m unittest discover -s tests', timeout=120)


def backend_or_skip(testcase):
    from aegis_jail.sandbox import SandboxUnavailable, get_backend
    try:
        return get_backend()
    except SandboxUnavailable as e:
        if os.environ.get("AEGIS_REQUIRE_SANDBOX"):
            raise
        testcase.skipTest(f"sandbox unavailable: {e}")
