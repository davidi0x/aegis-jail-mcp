from __future__ import annotations

import sys

from hydra_guard.sandbox.base import Backend, RunResult, SandboxSpec, SandboxUnavailable


def get_backend() -> Backend:
    if sys.platform.startswith("linux"):
        from hydra_guard.sandbox.linux import BwrapBackend
        b: Backend = BwrapBackend()
    elif sys.platform == "darwin":
        from hydra_guard.sandbox.macos import SeatbeltBackend
        b = SeatbeltBackend()
    elif sys.platform == "win32":
        from hydra_guard.sandbox.windows import AppContainerBackend
        b = AppContainerBackend()
    else:
        raise SandboxUnavailable(f"unsupported platform: {sys.platform}")
    b.check()
    return b


__all__ = ["Backend", "RunResult", "SandboxSpec", "SandboxUnavailable", "get_backend"]
