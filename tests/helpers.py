from __future__ import annotations

import os
import secrets
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "examples" / "demo-project"

_HYDRA_HOME: Path | None = None


def isolated_hydra_home() -> Path:
    """Use a throwaway HYDRA_HOME inside the real home (so it is a denied area)."""
    global _HYDRA_HOME
    if _HYDRA_HOME is None:
        _HYDRA_HOME = Path.home() / f".hydra-test-{secrets.token_hex(4)}"
        os.environ["HYDRA_HOME"] = str(_HYDRA_HOME)
    return _HYDRA_HOME


def cleanup_hydra_home() -> None:
    if _HYDRA_HOME and _HYDRA_HOME.exists():
        shutil.rmtree(_HYDRA_HOME, ignore_errors=True)


def demo_copy() -> Path:
    d = Path(tempfile.mkdtemp(prefix="hydra-demo-")).resolve() / "demo-project"
    shutil.copytree(DEMO, d)
    return d


def demo_task():
    from hydra_guard.agents import Task
    py = sys.executable
    return Task(name="fix-calc", agent="command", prompt="Fix the failing test",
                command=[py, "tools/scripted_agent.py", "{prompt}"],
                verify=f'"{py}" -m unittest discover -s tests', timeout=120)


def backend_or_skip(testcase):
    from hydra_guard.sandbox import SandboxUnavailable, get_backend
    try:
        return get_backend()
    except SandboxUnavailable as e:
        if os.environ.get("HYDRA_REQUIRE_SANDBOX"):
            raise
        testcase.skipTest(f"sandbox unavailable: {e}")
