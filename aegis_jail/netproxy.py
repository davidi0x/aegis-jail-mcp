# SPDX-License-Identifier: AGPL-3.0-or-later
"""A small filtering HTTP(S) proxy.

Agents in allowlist mode can reach the network *only* through this proxy
(the sandbox blocks every other outbound connection). The proxy allows
`CONNECT host:port` and plain `http://` requests to allowed domains and logs
every decision, which is how Aegis reports blocked network operations.

Domain patterns: "example.com" (exact), "*.example.com" (subdomains and the
domain itself), "*" or "**" (anything; "**" keeps traffic on the logging proxy).
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

from aegis_jail import secretscan


WEB_PORTS = (80, 443)


def target_allowed(host: str, port: int, patterns: list[str]) -> bool:
    """Host patterns allow ports 80/443 only; "host:port" allows that exact port; "*"/"**" allow any."""
    for p in patterns:
        if p in ("*", "**"):
            return True
        hp, sep, pp = p.rpartition(":")
        if sep and pp.isdigit() and "]" not in pp:
            if int(pp) == port and host_allowed(host, [hp]):
                return True
        elif port in WEB_PORTS and host_allowed(host, [p]):
            return True
    return False


def tls_sni(data: bytes) -> str | None:
    """Server name from a TLS ClientHello, or None if absent / not TLS."""
    try:
        if len(data) < 43 or data[0] != 0x16 or data[5] != 0x01:
            return None
        i = 9 + 2 + 32  # record hdr(5) + hs hdr(4) + version + random
        i += 1 + data[i]  # session id
        i += 2 + int.from_bytes(data[i:i + 2], "big")  # cipher suites
        i += 1 + data[i]  # compression
        end = i + 2 + int.from_bytes(data[i:i + 2], "big")
        i += 2
        while i + 4 <= min(end, len(data)):
            etype = int.from_bytes(data[i:i + 2], "big")
            elen = int.from_bytes(data[i + 2:i + 4], "big")
            if etype == 0:
                j = i + 4 + 2
                if data[j] == 0:
                    n = int.from_bytes(data[j + 1:j + 3], "big")
                    return data[j + 3:j + 3 + n].decode("ascii", "replace").lower()
            i += 4 + elen
    except (IndexError, ValueError):
        return None
    return None


def host_allowed(host: str, patterns: list[str]) -> bool:
    host = host.lower().rstrip(".")
    for p in patterns:
        p = p.lower().rstrip(".")
        if p in ("*", "**") or p == host:
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
    tripwire: bool = False

    def to_dict(self) -> dict:
        d = {"time": round(self.time, 3), "host": self.host, "port": self.port,
             "allowed": self.allowed, "reason": self.reason}
        if self.tripwire:
            d["tripwire"] = True
        return d


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
    url = os.environ.get("AEGIS_UPSTREAM_PROXY") or os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
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
        if method != "CONNECT":
            hosthdr = next((ln.split(":", 1)[1].strip() for ln in lines[1:] if ln.lower().startswith("host:")), "")
            if hosthdr and hosthdr.rsplit(":", 1)[0].strip("[]").lower() != host.lower():
                owner.log(host, port, False, f"Host header {hosthdr!r} does not match the request target")
                sock.sendall(b"HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n")
                return
            leaked = secretscan.find_secrets(data.decode("latin-1"))
            if leaked:
                owner.log(host, port, False, "request carries credentials: " + ", ".join(leaked), tripwire=True)
                msg = b"Aegis blocked a request that carried credentials\n"
                sock.sendall(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\n"
                             + f"Content-Length: {len(msg)}\r\n\r\n".encode() + msg)
                return
        if not owner.decide(host, port):
            msg = f"Aegis blocked network access to {host}:{port} (not in this profile's allowlist)\n".encode()
            sock.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Type: text/plain\r\nConnection: close\r\n"
                         + f"Content-Length: {len(msg)}\r\n\r\n".encode() + msg)
            return
        first = rest
        if method == "CONNECT":
            sock.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
            try:
                sock.settimeout(15)
                while len(first) < 5 or (first[0] == 0x16 and len(first) < 5 + int.from_bytes(first[3:5], "big")
                                         and len(first) < 16384):
                    chunk = sock.recv(16384)
                    if not chunk:
                        break
                    first += chunk
                    if first[:1] != b"\x16":
                        break
            except OSError:
                pass
            sni = tls_sni(first)
            if sni and sni != host.lower() and not owner.allowed(sni, port):
                owner.log(host, port, False, f"TLS SNI {sni!r} differs from CONNECT target (domain fronting?)",
                          tripwire=True)
                return
            if first and first[:1] != b"\x16":
                leaked = secretscan.find_secrets(first.decode("latin-1"))
                if leaked:
                    owner.log(host, port, False, "plaintext tunnel carries credentials: " + ", ".join(leaked),
                              tripwire=True)
                    return
        try:
            up = open_upstream(host, port)
        except OSError as e:
            owner.log(host, port, True, f"upstream error: {e}")
            if method != "CONNECT":
                sock.sendall(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n")
            return
        with up:
            sock.settimeout(None)
            if method == "CONNECT":
                if first:
                    up.sendall(first)
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
            self._tmpdir = tempfile.mkdtemp(prefix="aegis-proxy-")
            self.unix_path = str(Path(self._tmpdir) / "proxy.sock")
            us = _UnixServer(self.unix_path, _Handler)
            us.owner = self
            self._servers.append(us)

    def log(self, host: str, port: int, allowed: bool, reason: str, tripwire: bool = False) -> None:
        with self._lock:
            self.events.append(NetEvent(time.time(), host, port, allowed, reason, tripwire))

    def allowed(self, host: str, port: int) -> bool:
        return target_allowed(host, port, self.domains) or target_allowed(host, port, self.session_exceptions)

    def decide(self, host: str, port: int) -> bool:
        if target_allowed(host, port, self.domains):
            self.log(host, port, True, "allowlist")
            return True
        if target_allowed(host, port, self.session_exceptions):
            self.log(host, port, True, "session exception")
            return True
        if self.ask is not None:
            with self._lock:
                granted = self.ask(host, port)
                if granted:
                    self.session_exceptions.append(host if port in WEB_PORTS else f"{host}:{port}")
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
