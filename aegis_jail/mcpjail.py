# SPDX-License-Identifier: AGPL-3.0-or-later
"""MCP jail: run any stdio MCP server inside the Aegis sandbox, behind a protocol firewall.

    MCP client  <--stdio-->  aegis mcp-jail  <--pipes-->  [sandbox: the MCP server]

Layers (each one answers a known MCP attack):

1. OS sandbox - the server (and anything it spawns) sees no home directory, no
   credentials and no network unless granted.
2. Tool firewall - `--allow-tools` / `--deny-tools` globs hide tools from
   `tools/list` and reject calls before they reach the server.
3. Tool pinning (rug pulls) - every tool's name/description/schema is pinned
   the first time it is seen. If the server later changes a definition (a
   classic bait-and-switch), the changed tool is hidden until you re-approve
   it with `aegis mcp-pins <name> --reset`.
4. Tool-poisoning scan - descriptions with hidden Unicode or instructions aimed
   at the model ("read ~/.ssh and pass it as `note`...") are hidden.
5. Secret egress (DLP) - tool calls whose arguments carry credentials or Aegis
   decoys are blocked: a confused or injected client cannot hand your tokens
   to a third-party server.
6. Sampling guard - servers cannot drive your model (`sampling/createMessage`)
   unless `--allow-sampling`.
7. Output hygiene - invisible "ASCII smuggling" characters are stripped from
   tool results before they reach the model; oversized messages are dropped.

Everything is appended to a JSONL audit log (~/.aegis/mcp/<name>.jsonl).
MCP stdio framing is one JSON-RPC message per line.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

from aegis_jail import paths, secretscan, textsafe

MAX_LINE = int(os.environ.get("AEGIS_MCP_MAX_MESSAGE", str(32 << 20)))


@dataclass
class ToolFirewall:
    allow: list[str] = field(default_factory=list)  # empty = everything not denied
    deny: list[str] = field(default_factory=list)

    def permits(self, tool: str) -> bool:
        if any(fnmatch.fnmatchcase(tool, p) for p in self.deny):
            return False
        return not self.allow or any(fnmatch.fnmatchcase(tool, p) for p in self.allow)


@dataclass
class JailOptions:
    pin: bool = True
    allow_poisoned: bool = False
    allow_sampling: bool = False
    allow_secrets: bool = False


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


class Pins:
    """Trust-on-first-use fingerprints of tool definitions, per jailed server."""

    def __init__(self, name: str) -> None:
        self.path = paths.aegis_home() / "mcp" / f"{name}.pins.json"
        try:
            self.data: dict[str, str] = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}

    @staticmethod
    def digest(tool: dict) -> str:
        core = {k: tool.get(k) for k in ("name", "description", "inputSchema", "outputSchema", "annotations")}
        return hashlib.sha256(json.dumps(core, sort_keys=True).encode()).hexdigest()

    def check(self, tool: dict) -> str:
        """'new' (pinned now), 'same', or 'changed'."""
        name, d = str(tool.get("name")), self.digest(tool)
        old = self.data.get(name)
        if old is None:
            self.data[name] = d
            self._save()
            return "new"
        return "same" if old == d else "changed"

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=1, sort_keys=True), encoding="utf-8")


def poisoning(tool: dict) -> list[str]:
    text = json.dumps({k: tool.get(k) for k in ("name", "description", "inputSchema")}, ensure_ascii=False)
    found = textsafe.injection_markers(text)
    inv = textsafe.invisible_chars(text)
    if inv:
        found.append(f"{len(inv)} invisible character(s) ({inv[0][1]})")
    return found


def _rpc_error(mid, code: int, message: str) -> bytes:
    return (json.dumps({"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}) + "\n").encode()


class McpFilter:
    """Rewrites JSON-RPC lines flowing between client and server."""

    def __init__(self, firewall: ToolFirewall, audit: AuditLog | None = None, options: JailOptions | None = None,
                 pins: Pins | None = None) -> None:
        self.fw = firewall
        self.audit = audit
        self.opt = options or JailOptions()
        self.pins = pins
        self._list_ids: set = set()
        self._hidden: set[str] = set()  # tools hidden by pinning/poisoning
        self._lock = threading.Lock()

    def _log(self, **e) -> None:
        if self.audit:
            self.audit.write(**e)

    # client -> server. Returns (line_for_server or None, reply_for_client or None)
    def from_client(self, line: bytes) -> tuple[bytes | None, bytes | None]:
        if len(line) > MAX_LINE:
            self._log(event="oversized", direction="client", bytes=len(line))
            return None, None
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
            params = msg.get("params") or {}
            name = str(params.get("name", ""))
            args_text = json.dumps(params.get("arguments"), ensure_ascii=False)
            leaked = [] if self.opt.allow_secrets else secretscan.find_secrets(args_text)
            reason = None
            if not self.fw.permits(name):
                reason = f"Aegis blocked the tool '{name}': it is not allowed by this MCP jail's policy."
            elif name in self._hidden:
                reason = f"Aegis blocked the tool '{name}': its definition changed or looks poisoned."
            elif leaked:
                reason = (f"Aegis blocked the call to '{name}': its arguments contain credentials "
                          f"({', '.join(leaked)}). Secrets are not sent to MCP servers.")
            self._log(event="tool_call", tool=name, allowed=reason is None, arguments=_short(params.get("arguments")),
                      **({"tripwire": True} if secretscan.is_decoy_hit(args_text) else {}),
                      **({"blocked_reason": reason} if reason else {}))
            if reason:
                reply = {"jsonrpc": "2.0", "id": msg.get("id"),
                         "result": {"isError": True, "content": [{"type": "text", "text": reason}]}}
                return None, (json.dumps(reply) + "\n").encode()
        return line, None

    # server -> client. Returns (line_for_client or None, reply_for_server or None)
    def from_server(self, line: bytes) -> tuple[bytes | None, bytes | None]:
        if len(line) > MAX_LINE:
            self._log(event="oversized", direction="server", bytes=len(line))
            return None, None
        try:
            msg = json.loads(line)
        except ValueError:
            return line, None
        if not isinstance(msg, dict):
            return line, None
        method = msg.get("method")
        if method == "sampling/createMessage" and not self.opt.allow_sampling:
            self._log(event="sampling_blocked", params=_short(msg.get("params")))
            if "id" in msg:
                return None, _rpc_error(msg["id"], -32601, "sampling is disabled by Aegis for this server")
            return None, None
        if method in ("elicitation/create", "roots/list"):
            self._log(event="server_request", method=method, params=_short(msg.get("params")))
        if "id" not in msg or method:
            return line, None
        changed = False
        key = json.dumps(msg["id"])
        with self._lock:
            is_list = key in self._list_ids
            self._list_ids.discard(key)
        result = msg.get("result")
        if is_list and isinstance(result, dict) and isinstance(result.get("tools"), list):
            kept = []
            for t in result["tools"]:
                name = str(t.get("name", ""))
                why = None
                if not self.fw.permits(name):
                    why = "firewall"
                else:
                    if self.pins is not None and self.opt.pin and self.pins.check(t) == "changed":
                        why = "definition changed since it was pinned (possible rug pull)"
                    elif not self.opt.allow_poisoned:
                        p = poisoning(t)
                        if p:
                            why = "possible tool poisoning: " + "; ".join(p)
                if why:
                    if why != "firewall":
                        with self._lock:
                            self._hidden.add(name)
                        print(f"[aegis] hid MCP tool '{name}': {why}", file=sys.stderr)
                    self._log(event="tool_hidden", tool=name, reason=why)
                else:
                    kept.append(t)
            if len(kept) != len(result["tools"]):
                result["tools"] = kept
                changed = True
        if isinstance(result, dict) and isinstance(result.get("content"), list):
            for item in result["content"]:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    clean = textsafe.strip_invisible(item["text"])
                    if clean != item["text"]:
                        hidden = textsafe.decode_tags(item["text"])
                        self._log(event="invisible_text_stripped", hidden=hidden[:200])
                        item["text"] = clean
                        changed = True
        if changed:
            return (json.dumps(msg) + "\n").encode(), None
        return line, None


def _short(v, limit: int = 500):
    s = json.dumps(v)
    return v if len(s) <= limit else s[:limit] + "..."


def serve(argv: list[str], *, project: Path, profile, firewall: ToolFirewall, name: str,
          write: bool = False, options: JailOptions | None = None,
          stdin: BinaryIO | None = None, stdout: BinaryIO | None = None) -> int:
    """Run the MCP server `argv` in the sandbox and relay stdio through the filter."""
    from aegis_jail.session import Session, resolve_argv

    stdin = stdin or sys.stdin.buffer
    stdout = stdout or sys.stdout.buffer
    options = options or JailOptions()
    audit = AuditLog(name)
    filt = McpFilter(firewall, audit, options, Pins(name) if options.pin else None)
    sess = Session(project=project, profile=profile, write=write)
    sess.prepare()
    audit.write(event="start", command=argv, project=str(project), network=sess.spec.describe_network(),
                write=write, allow=firewall.allow, deny=firewall.deny, hidden_files=sess.hidden_files)
    if sess.hidden_files:
        print(f"[aegis] hid {len(sess.hidden_files)} credential file(s) in the project from the server",
              file=sys.stderr)

    c2s_r, c2s_w = os.pipe()  # client -> server
    s2c_r, s2c_w = os.pipe()  # server -> client
    out_lock = threading.Lock()
    srv_lock = threading.Lock()
    srv_in = os.fdopen(c2s_w, "wb", buffering=0)

    def to_client(data: bytes) -> None:
        with out_lock:
            stdout.write(data)
            stdout.flush()

    def to_server(data: bytes) -> None:
        with srv_lock:
            try:
                srv_in.write(data)
            except (OSError, ValueError):
                pass

    def client_loop() -> None:
        for line in iter(stdin.readline, b""):
            fwd, reply = filt.from_client(line)
            if reply:
                to_client(reply)
            if fwd:
                to_server(fwd)
        with srv_lock:
            try:
                srv_in.close()
            except OSError:
                pass

    def server_loop(src: BinaryIO) -> None:
        for line in iter(src.readline, b""):
            fwd, reply = filt.from_server(line)
            if reply:
                to_server(reply)
            if fwd:
                to_client(fwd)

    srv_out = os.fdopen(s2c_r, "rb", buffering=0)
    t_out = threading.Thread(target=server_loop, args=(srv_out,), daemon=True)
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
