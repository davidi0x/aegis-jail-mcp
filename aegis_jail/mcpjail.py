"""MCP jail: run any stdio MCP server inside the Aegis sandbox, with a tool firewall.

    MCP client  <--stdio-->  aegis mcp-jail  <--pipes-->  [sandbox: the MCP server]

* The server process (and everything it spawns) is confined by an Aegis
  profile: no home directory, no credentials, no network unless granted.
* Tool calls are filtered: `--allow-tools` / `--deny-tools` (glob patterns)
  hide tools from `tools/list` and reject `tools/call` before it reaches the
  server.
* Every tool call and every blocked network host is appended to a JSONL audit
  log (~/.aegis/mcp/<name>.jsonl).

MCP stdio transport = one JSON-RPC message per line, so the filter only has
to parse and rewrite individual lines.
"""

from __future__ import annotations

import fnmatch
import json
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

from aegis_jail import paths


@dataclass
class ToolFirewall:
    allow: list[str] = field(default_factory=list)  # empty = everything not denied
    deny: list[str] = field(default_factory=list)

    def permits(self, tool: str) -> bool:
        if any(fnmatch.fnmatchcase(tool, p) for p in self.deny):
            return False
        return not self.allow or any(fnmatch.fnmatchcase(tool, p) for p in self.allow)


class AuditLog:
    def __init__(self, name: str) -> None:
        d = paths.aegis_home() / "mcp"
        d.mkdir(parents=True, exist_ok=True)
        self.path = d / f"{name}.jsonl"
        self._lock = threading.Lock()

    def write(self, **event) -> None:
        event = {"time": round(time.time(), 3), **event}
        with self._lock, open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")


class McpFilter:
    """Rewrites JSON-RPC lines flowing between client and server."""

    def __init__(self, firewall: ToolFirewall, audit: AuditLog | None = None) -> None:
        self.fw = firewall
        self.audit = audit
        self._list_ids: set = set()
        self._lock = threading.Lock()

    # client -> server. Returns (line_for_server or None, reply_for_client or None)
    def from_client(self, line: bytes) -> tuple[bytes | None, bytes | None]:
        try:
            msg = json.loads(line)
        except ValueError:
            return line, None
        if not isinstance(msg, dict):
            return line, None
        method = msg.get("method")
        if method == "tools/list" and "id" in msg:
            with self._lock:
                self._list_ids.add(json.dumps(msg["id"]))
        elif method == "tools/call":
            name = str((msg.get("params") or {}).get("name", ""))
            allowed = self.fw.permits(name)
            if self.audit:
                self.audit.write(event="tool_call", tool=name, allowed=allowed,
                                 arguments=_short((msg.get("params") or {}).get("arguments")))
            if not allowed:
                reply = {"jsonrpc": "2.0", "id": msg.get("id"),
                         "result": {"isError": True, "content": [{"type": "text", "text":
                                    f"Aegis blocked the tool '{name}': it is not allowed by this MCP jail's policy."}]}}
                return None, (json.dumps(reply) + "\n").encode()
        return line, None

    # server -> client
    def from_server(self, line: bytes) -> bytes:
        try:
            msg = json.loads(line)
        except ValueError:
            return line
        if not isinstance(msg, dict) or "id" not in msg:
            return line
        key = json.dumps(msg["id"])
        with self._lock:
            is_list = key in self._list_ids
            self._list_ids.discard(key)
        if is_list and isinstance(msg.get("result"), dict) and isinstance(msg["result"].get("tools"), list):
            tools = msg["result"]["tools"]
            kept = [t for t in tools if self.fw.permits(str(t.get("name", "")))]
            if len(kept) != len(tools):
                msg["result"]["tools"] = kept
                if self.audit:
                    self.audit.write(event="tools_hidden",
                                     tools=[t.get("name") for t in tools if t not in kept])
                return (json.dumps(msg) + "\n").encode()
        return line


def _short(v, limit: int = 500):
    s = json.dumps(v)
    return v if len(s) <= limit else s[:limit] + "..."


def _pump_lines(src: BinaryIO, handle) -> None:
    for line in iter(src.readline, b""):
        handle(line)


def serve(argv: list[str], *, project: Path, profile, firewall: ToolFirewall, name: str,
          write: bool = False, stdin: BinaryIO | None = None, stdout: BinaryIO | None = None) -> int:
    """Run the MCP server `argv` in the sandbox and relay stdio through the filter."""
    from aegis_jail.session import Session, resolve_argv

    stdin = stdin or sys.stdin.buffer
    stdout = stdout or sys.stdout.buffer
    audit = AuditLog(name)
    filt = McpFilter(firewall, audit)
    sess = Session(project=project, profile=profile, write=write)
    sess.prepare()
    audit.write(event="start", command=argv, project=str(project), network=sess.spec.describe_network(),
                write=write, allow=firewall.allow, deny=firewall.deny)

    c2s_r, c2s_w = os.pipe()  # client -> server
    s2c_r, s2c_w = os.pipe()  # server -> client
    out_lock = threading.Lock()

    def to_client(data: bytes) -> None:
        with out_lock:
            stdout.write(data)
            stdout.flush()

    srv_in = os.fdopen(c2s_w, "wb", buffering=0)

    def client_loop() -> None:
        for line in iter(stdin.readline, b""):
            fwd, reply = filt.from_client(line)
            if reply:
                to_client(reply)
            if fwd:
                try:
                    srv_in.write(fwd)
                except OSError:
                    break
        try:
            srv_in.close()
        except OSError:
            pass

    srv_out = os.fdopen(s2c_r, "rb", buffering=0)
    t_out = threading.Thread(target=_pump_lines, args=(srv_out, lambda ln: to_client(filt.from_server(ln))),
                             daemon=True)
    t_in = threading.Thread(target=client_loop, daemon=True)
    t_out.start()
    t_in.start()
    try:
        res = sess.run(resolve_argv(argv), stdio=(c2s_r, s2c_w, sys.stderr.fileno()))
    finally:
        for fd in (c2s_r, s2c_w):
            try:
                os.close(fd)
            except OSError:
                pass
    t_out.join(timeout=5)
    blocked = sess.blocked_hosts()
    if blocked:
        audit.write(event="network_blocked", hosts=blocked)
        print(f"[aegis] blocked network access to: {', '.join(blocked)}", file=sys.stderr)
    audit.write(event="exit", code=res.exit_code)
    return res.exit_code
