"""A small filtering HTTP(S) proxy.

Agents in allowlist mode can reach the network *only* through this proxy
(the sandbox blocks every other outbound connection). The proxy allows
`CONNECT host:port` and plain `http://` requests to allowed domains and logs
every decision, which is how Hydra reports blocked network operations.

Domain patterns: "example.com" (exact), "*.example.com" (subdomains and the
domain itself), "*" (anything).
"""

from __future__ import annotations

import base64
import os
import select
import socket
import socketserver
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit


def host_allowed(host: str, patterns: list[str]) -> bool:
    host = host.lower().rstrip(".")
    for p in patterns:
        p = p.lower().rstrip(".")
        if p == "*" or p == host:
            return True
        if p.startswith("*.") and (host == p[2:] or host.endswith(p[1:])):
            return True
    return False


@dataclass
class NetEvent:
    time: float
    host: str
    port: int
    allowed: bool
    reason: str

    def to_dict(self) -> dict:
        return {"time": round(self.time, 3), "host": self.host, "port": self.port,
                "allowed": self.allowed, "reason": self.reason}


def _pump(a: socket.socket, b: socket.socket) -> None:
    socks = [a, b]
    try:
        while True:
            r, _, x = select.select(socks, [], socks, 300)
            if x or not r:
                return
            for s in r:
                data = s.recv(65536)
                if not data:
                    return
                (b if s is a else a).sendall(data)
    except OSError:
        return


def _upstream_proxy() -> tuple[str, int, str | None] | None:
    url = os.environ.get("HYDRA_UPSTREAM_PROXY") or os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if not url:
        return None
    u = urlsplit(url if "://" in url else "http://" + url)
    if not u.hostname:
        return None
    auth = None
    if u.username:
        auth = base64.b64encode(f"{u.username}:{u.password or ''}".encode()).decode()
    return u.hostname, u.port or 80, auth


def _no_proxy(host: str) -> bool:
    raw = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
    for entry in (e.strip().lower() for e in raw.split(",") if e.strip()):
        entry = entry.lstrip("*")
        if host == entry.lstrip(".") or (entry.startswith(".") and host.endswith(entry)):
            return True
    return host in ("localhost", "127.0.0.1", "::1")


def open_upstream(host: str, port: int, timeout: float = 30) -> socket.socket:
    """Connect to host:port, through the host's own proxy if it has one."""
    up = _upstream_proxy()
    if up and not _no_proxy(host):
        s = socket.create_connection((up[0], up[1]), timeout=timeout)
        req = f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n"
        if up[2]:
            req += f"Proxy-Authorization: Basic {up[2]}\r\n"
        s.sendall((req + "\r\n").encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = s.recv(4096)
            if not chunk:
                break
            resp += chunk
        status = resp.split(b"\r\n", 1)[0].split()
        if len(status) < 2 or status[1] != b"200":
            s.close()
            raise OSError(f"upstream proxy refused CONNECT {host}:{port}: {resp[:80]!r}")
        s.settimeout(None)
        return s
    s = socket.create_connection((host, port), timeout=timeout)
    s.settimeout(None)
    return s


class _Handler(socketserver.BaseRequestHandler):
    server: "_Server"

    def handle(self) -> None:
        sock: socket.socket = self.request
        sock.settimeout(60)
        data = b""
        try:
            while b"\r\n\r\n" not in data:
                chunk = sock.recv(8192)
                if not chunk:
                    return
                data += chunk
                if len(data) > 65536:
                    return
        except OSError:
            return
        head, _, rest = data.partition(b"\r\n\r\n")
        lines = head.decode("latin-1").split("\r\n")
        parts = lines[0].split()
        if len(parts) < 3:
            return
        method, target = parts[0].upper(), parts[1]
        if method == "CONNECT":
            host, _, port_s = target.rpartition(":")
            host = host.strip("[]")
            port = int(port_s) if port_s.isdigit() else 443
        else:
            u = urlsplit(target)
            if u.scheme != "http" or not u.hostname:
                sock.sendall(b"HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n")
                return
            host, port = u.hostname, u.port or 80
        owner = self.server.owner
        if not owner.decide(host, port):
            msg = f"Hydra blocked network access to {host}:{port} (not in this profile's allowlist)\n".encode()
            sock.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Type: text/plain\r\nConnection: close\r\n"
                         + f"Content-Length: {len(msg)}\r\n\r\n".encode() + msg)
            return
        try:
            up = open_upstream(host, port)
        except OSError as e:
            owner.log(host, port, True, f"upstream error: {e}")
            sock.sendall(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n")
            return
        with up:
            sock.settimeout(None)
            if method == "CONNECT":
                sock.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
                if rest:
                    up.sendall(rest)
            else:
                u = urlsplit(target)
                path = (u.path or "/") + (f"?{u.query}" if u.query else "")
                hdrs = [h for h in lines[1:] if not h.lower().startswith(("proxy-", "connection:"))]
                req = "\r\n".join([f"{method} {path} {parts[2]}", *hdrs, "Connection: close", "", ""])
                up.sendall(req.encode("latin-1") + rest)
            _pump(sock, up)


class _Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True
    owner: "FilteringProxy"


if hasattr(socketserver, "UnixStreamServer"):
    class _UnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
        daemon_threads = True
        owner: "FilteringProxy"


class FilteringProxy:
    def __init__(self, domains: list[str], *, ask: Callable[[str, int], bool] | None = None,
                 tcp: bool = True, unix: bool = False) -> None:
        self.domains = list(domains)
        self.session_exceptions: list[str] = []
        self.events: list[NetEvent] = []
        self.ask = ask
        self._lock = threading.Lock()
        self._servers: list[socketserver.BaseServer] = []
        self.tcp_port: int | None = None
        self.unix_path: str | None = None
        self._tmpdir: str | None = None
        if tcp:
            s = _Server(("127.0.0.1", 0), _Handler)
            s.owner = self
            self.tcp_port = s.server_address[1]
            self._servers.append(s)
        if unix:
            self._tmpdir = tempfile.mkdtemp(prefix="hydra-proxy-")
            self.unix_path = str(Path(self._tmpdir) / "proxy.sock")
            us = _UnixServer(self.unix_path, _Handler)
            us.owner = self
            self._servers.append(us)

    def log(self, host: str, port: int, allowed: bool, reason: str) -> None:
        with self._lock:
            self.events.append(NetEvent(time.time(), host, port, allowed, reason))

    def decide(self, host: str, port: int) -> bool:
        if host_allowed(host, self.domains):
            self.log(host, port, True, "allowlist")
            return True
        if host_allowed(host, self.session_exceptions):
            self.log(host, port, True, "session exception")
            return True
        if self.ask is not None:
            with self._lock:
                granted = self.ask(host, port)
                if granted:
                    self.session_exceptions.append(host)
            if granted:
                self.log(host, port, True, "session exception (granted by user)")
                return True
        self.log(host, port, False, "not in allowlist")
        return False

    def start(self) -> "FilteringProxy":
        for s in self._servers:
            threading.Thread(target=s.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        for s in self._servers:
            s.shutdown()
            s.server_close()
        if self.unix_path:
            try:
                os.unlink(self.unix_path)
                os.rmdir(self._tmpdir or "")
            except OSError:
                pass

    def __enter__(self) -> "FilteringProxy":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()
