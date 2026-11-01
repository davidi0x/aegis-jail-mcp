"""A tiny stdio MCP server used by the tests. Its tools misbehave on purpose."""
import json
import os
import sys
import urllib.request

TOOLS = [{"name": n, "description": n, "inputSchema": {"type": "object"}}
         for n in ("read_secret", "delete_everything", "fetch", "write_note")]


def call(name, args):
    if name == "read_secret":
        p = os.path.expanduser(args.get("path", "~/.ssh/id_rsa"))
        try:
            return "GOT:" + open(p).read()[:30]
        except Exception as e:
            return f"denied: {type(e).__name__}"
    if name == "fetch":
        try:
            urllib.request.urlopen(args.get("url", "http://evil.example/"), timeout=5)
            return "fetched"
        except Exception as e:
            return f"fetch failed: {e}"
    if name == "write_note":
        try:
            with open(args["path"], "w") as f:
                f.write("note")
            return "written"
        except Exception as e:
            return f"write failed: {type(e).__name__}"
    return "deleted everything!"


for line in sys.stdin:
    msg = json.loads(line)
    if "id" not in msg:
        continue
    m = msg["method"]
    if m == "initialize":
        res = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "fake"}}
    elif m == "tools/list":
        res = {"tools": TOOLS}
    elif m == "tools/call":
        res = {"content": [{"type": "text", "text": call(msg["params"]["name"], msg["params"].get("arguments", {}))}]}
    else:
        res = {}
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": res}) + "\n")
    sys.stdout.flush()
