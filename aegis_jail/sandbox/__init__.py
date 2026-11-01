# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

import sys

from aegis_jail.sandbox.base import Backend, RunResult, SandboxSpec, SandboxUnavailable


def get_backend() -> Backend:
    if sys.platform.startswith("linux"):
        from aegis_jail.sandbox.linux import BwrapBackend
        b: Backend = BwrapBackend()
    elif sys.platform == "darwin":
        from aegis_jail.sandbox.macos import SeatbeltBackend
        b = SeatbeltBackend()
    elif sys.platform == "win32":
        from aegis_jail.sandbox.windows import AppContainerBackend
        b = AppContainerBackend()
    else:
        raise SandboxUnavailable(f"unsupported platform: {sys.platform}")
    b.check()
    return b


__all__ = ["Backend", "RunResult", "SandboxSpec", "SandboxUnavailable", "get_backend"]
