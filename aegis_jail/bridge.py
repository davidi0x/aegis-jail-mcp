# SPDX-License-Identifier: AGPL-3.0-or-later
"""In-sandbox bridge (Linux): 127.0.0.1:PORT -> Aegis proxy unix socket.

Usage: python -m aegis_jail.bridge SOCKET PORT -- command [args...]

The sandbox has its own network namespace with only loopback, so this
bridge is the single path to the outside world, and it only leads to the
filtering proxy.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import threading

from aegis_jail.netproxy import _pump


def _serve(listener: socket.socket, sock_path: str) -> None:
    while True:
        try:
            client, _ = listener.accept()
        except OSError:
            return

        def handle(c: socket.socket = client) -> None:
            try:
                up = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                up.connect(sock_path)
            except OSError:
                c.close()
                return
            with c, up:
                _pump(c, up)

        threading.Thread(target=handle, daemon=True).start()


def main(argv: list[str]) -> int:
    if "--" not in argv or len(argv) < 4:
        print(__doc__, file=sys.stderr)
        return 2
    sep = argv.index("--")
    sock_path, port = argv[0], int(argv[1])
    cmd = argv[sep + 1:]
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", port))
    listener.listen(64)
    threading.Thread(target=_serve, args=(listener, sock_path), daemon=True).start()
    try:
        return subprocess.call(cmd)
    except FileNotFoundError:
        print(f"aegis: command not found: {cmd[0]}", file=sys.stderr)
        return 127


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
