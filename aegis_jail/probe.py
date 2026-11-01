"""Boundary probes: check in practice that a profile's limits really hold.

Aegis runs a small probe program *inside* the sandbox (and again in a child
process it spawns) that tries to read secrets, write outside the working
copy and open network connections. Each attempt is compared with what the
profile says should happen. Writes are confirmed from the host side, reads
are compared against the real content's fingerprint, and network checks get
a host-side control attempt so an offline machine yields "inconclusive"
instead of a false "pass".
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import socket
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from aegis_jail import paths, workspace
from aegis_jail.agents import Task, get_agent, runtime_paths
from aegis_jail.netproxy import open_upstream
from aegis_jail.policy import Profile
from aegis_jail.sandbox import Backend, SandboxSpec, get_backend
from aegis_jail.runner import new_run_dir

PAYLOAD = r'''
import hashlib, json, os, socket, subprocess, sys

def fp(path):
    try:
        if os.path.isdir(path):
            return hashlib.sha256("\n".join(sorted(os.listdir(path))).encode()).hexdigest()
        with open(path, "rb") as f:
            return hashlib.sha256(f.read(4096)).hexdigest()
    except Exception as e:
        return "error:" + type(e).__name__

def via_proxy(host, port):
    url = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if not url:
        return "deny"
    hp = url.split("://", 1)[-1].rstrip("/")
    ph, _, pp = hp.rpartition(":")
    try:
        s = socket.create_connection((ph, int(pp)), timeout=10)
        s.sendall(("CONNECT %s:%d HTTP/1.1\r\nHost: %s:%d\r\n\r\n" % (host, port, host, port)).encode())
        line = s.recv(1024).split(b"\r\n", 1)[0]
        s.close()
        return "allow" if b" 200" in line else "deny"
    except Exception:
        return "deny"

def run(plan, child):
    out = {}
    for c in plan["checks"]:
        if child and not c.get("child", True):
            continue
        op = c["op"]
        if op == "read":
            got = fp(c["path"])
            out[c["id"]] = "allow" if got == c["fingerprint"] else "deny"
        elif op == "write":
            path = c["path"] + (".child" if child else "")
            try:
                with open(path, "w") as f:
                    f.write("aegis-probe")
                out[c["id"]] = "attempted"
            except Exception:
                out[c["id"]] = "deny"
        elif op == "connect":
            try:
                socket.create_connection((c["host"], c["port"]), timeout=5).close()
                out[c["id"]] = "allow"
            except Exception:
                out[c["id"]] = "deny"
        elif op == "proxy":
            out[c["id"]] = via_proxy(c["host"], c["port"])
    return out

plan = json.load(open(sys.argv[1]))
child = len(sys.argv) > 2 and sys.argv[2] == "--child"
res = {"results": run(plan, child)}
if not child:
    p = subprocess.run([sys.executable, sys.argv[0], sys.argv[1], "--child"], capture_output=True, text=True)
    try:
        res["child"] = json.loads(p.stdout.strip().splitlines()[-1])["results"]
    except Exception:
        res["child_error"] = (p.stdout + p.stderr)[-500:]
print(json.dumps(res))
'''


def expected_fs(rules: list[tuple[str, Path]], path: Path, op: str) -> str:
    """Evaluate SandboxSpec fs_rules (last match wins) for a path."""
    from aegis_jail.policy import _is_within
    action = None
    for a, p in rules:
        if _is_within(path, p):
            action = a
    if op == "read":
        return "deny" if action == "deny" else "allow"
    return "allow" if action == "write" else "deny"


def _fingerprint(path: Path) -> str:
    if path.is_dir():
        return hashlib.sha256("\n".join(sorted(os.listdir(path))).encode()).hexdigest()
    with open(path, "rb") as f:
        return hashlib.sha256(f.read(4096)).hexdigest()


@dataclass
class Check:
    id: str
    op: str
    target: str
    expect: str
    observed: str = ""
    observed_child: str = ""
    control: str = ""
    status: str = ""

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def _control_connect(host: str, port: int, via_upstream: bool) -> str:
    try:
        if via_upstream:
            open_upstream(host, port, timeout=8).close()
        else:
            socket.create_connection((host, port), timeout=5).close()
        return "allow"
    except OSError:
        return "deny"


def build_checks(spec: SandboxSpec, project: Path, ws: Path) -> list[Check]:
    home = paths.user_home()
    tag = secrets.token_hex(4)
    checks: list[Check] = []

    def read(cid: str, p: Path) -> None:
        if not p.exists():
            return
        if p.is_dir():
            # Prefer reading a real file inside: an empty listing is indistinguishable from a hidden one.
            try:
                entries = sorted(p.iterdir())
            except OSError:
                return
            files = [e for e in entries if e.is_file() and not e.is_symlink()]
            if files:
                p = files[0]
            elif not entries:
                return
        checks.append(Check(cid, "read", str(p), expected_fs(spec.fs_rules, p.resolve(), "read")))

    def write(cid: str, p: Path) -> None:
        if p.parent.exists():
            checks.append(Check(cid, "write", str(p), expected_fs(spec.fs_rules, p.parent.resolve(), "write")))

    read("read-canary-secret", paths.canary_dir() / "secret.txt")
    for s in paths.SECRET_PATHS:
        sp = paths.expand(s, home)
        read(f"read-secret:{s}", sp)
    snap = workspace.snapshot(project)
    if snap:
        read("read-original-project", project / sorted(snap)[0])
    skip = {".aegis"} | {Path(s).parts[1].lower() for s in paths.SECRET_PATHS if s.startswith("~/")}
    skip |= {paths.aegis_home().name.lower()}
    for entry in sorted(home.iterdir()) if home.exists() else []:
        if entry.name.lower() not in skip and not entry.name.startswith(".aegis") and not entry.is_symlink():
            try:
                _fingerprint(entry)
            except OSError:
                continue
            read("read-home-other", entry)
            break
    system_file = Path(os.environ.get("WINDIR", "C:\\Windows")) / "win.ini" if os.name == "nt" else Path("/etc/hosts")
    read("read-system-file", system_file)
    read("read-workspace", ws / sorted(snap)[0] if snap else ws)

    write("write-aegis-state", paths.canary_dir() / f"probe-{tag}.txt")
    write("write-home", home / f".aegis-probe-{tag}.txt")
    write("write-original-project", project / f".aegis-probe-{tag}.txt")
    write("write-workspace", ws / f".aegis-probe-{tag}.txt")
    write("write-tmp", spec.tmp / f"probe-{tag}.txt")

    if spec.network == "all":
        checks.append(Check("net-direct", "connect", "1.1.1.1:443", "allow"))
    else:
        checks.append(Check("net-direct", "connect", "1.1.1.1:443", "deny"))
    if isinstance(spec.network, list):
        checks.append(Check("net-proxy-blocked", "proxy", "blocked.aegis-probe.example:443", "deny"))
        allowed = next((d for d in spec.network if "*" not in d and d != "localhost"), None)
        if allowed:
            checks.append(Check("net-proxy-allowed", "proxy", f"{allowed}:443", "allow"))
    return checks


def run_probe(project: Path, profile: Profile, *, phase: str = "task", task: Task | None = None,
              backend: Backend | None = None) -> dict:
    project = project.resolve()
    backend = backend or get_backend()
    task = task or Task(agent=profile.agent)
    try:
        profile = profile.merged(get_agent(task.agent).grants(task))
    except ValueError:
        pass
    run_id, rd = new_run_dir(project)
    ws = rd / "workspace"
    tmp = rd / "tmp"
    tmp.mkdir()
    workspace.create(project, ws)
    spec = profile.compile(phase, project=project, workspace=ws, tmp=tmp, runtime_paths=runtime_paths())
    checks = build_checks(spec, project, ws)

    plan = {"checks": []}
    for c in checks:
        item = {"id": c.id, "op": c.op}
        if c.op == "read":
            item["path"] = c.target
            item["fingerprint"] = _fingerprint(Path(c.target))
        elif c.op == "write":
            item["path"] = c.target
        else:
            host, _, port = c.target.rpartition(":")
            item["host"], item["port"] = host, int(port)
            item["child"] = c.op == "connect"
        plan["checks"].append(item)
    (tmp / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    (tmp / "probe.py").write_text(PAYLOAD, encoding="utf-8")

    from aegis_jail.runner import run_phase
    exceptions: list[str] = []
    pr = run_phase(backend, spec, "probe", [sys.executable, str(tmp / "probe.py"), str(tmp / "plan.json")],
                   rd, 120, None, exceptions)
    log = Path(pr.log).read_text(encoding="utf-8", errors="replace").strip().splitlines()
    try:
        data = json.loads(log[-1])
    except (IndexError, json.JSONDecodeError):
        raise RuntimeError("probe program failed inside the sandbox:\n" + "\n".join(log[-20:]))
    res, child = data.get("results", {}), data.get("child", {})

    for c in checks:
        c.observed = res.get(c.id, "missing")
        c.observed_child = child.get(c.id, "") if c.op in ("read", "write", "connect") else ""
        if c.op == "write":
            # The host decides: did the file actually appear outside the sandbox?
            for suffix, attr in (("", "observed"), (".child", "observed_child")):
                p = Path(c.target + suffix)
                landed = p.exists()
                if landed:
                    try:
                        p.unlink()
                    except OSError:
                        pass
                setattr(c, attr, "allow" if landed else "deny")
        if c.op in ("connect", "proxy"):
            host, _, port = c.target.rpartition(":")
            if c.op == "connect":
                c.control = _control_connect(host, int(port), via_upstream=False)
            elif c.expect == "allow":
                c.control = _control_connect(host, int(port), via_upstream=True)
        observed = [c.observed] + ([c.observed_child] if c.observed_child else [])
        if any(o not in ("allow", "deny") for o in observed):
            c.status = "error"
        elif all(o == c.expect for o in observed):
            c.status = "pass"
            if c.control == "deny" and c.expect == "deny" and c.op == "connect":
                c.status = "inconclusive"  # host itself cannot connect; the block proves nothing
        else:
            if c.expect == "allow" and c.control == "deny":
                c.status = "inconclusive"
            else:
                c.status = "fail"

    result = {
        "aegis_probe": 1,
        "time": time.time(),
        "run_id": run_id,
        "project": str(project),
        "profile": profile.name,
        "phase": phase,
        "backend": backend.name,
        "network": spec.describe_network(),
        "checks": [c.to_dict() for c in checks],
        "summary": {s: sum(1 for c in checks if c.status == s) for s in ("pass", "fail", "inconclusive", "error")},
    }
    (rd / "probe.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    hist = paths.runs_dir(project) / "probes" / profile.name
    hist.mkdir(parents=True, exist_ok=True)
    (hist / f"{run_id}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    from aegis_jail.runner import cleanup_run
    cleanup_run(rd)
    return result


def previous_probe(project: Path, profile_name: str, before_run: str) -> dict | None:
    hist = paths.runs_dir(project) / "probes" / profile_name
    if not hist.exists():
        return None
    older = sorted(p for p in hist.glob("*.json") if p.stem < before_run)
    return json.loads(older[-1].read_text(encoding="utf-8")) if older else None


def compare(old: dict, new: dict) -> list[str]:
    """Human-readable regressions/changes between two probe results."""
    o = {c["id"]: c for c in old["checks"]}
    out = []
    for c in new["checks"]:
        prev = o.get(c["id"])
        if prev is None:
            out.append(f"new check {c['id']}: {c['status']}")
        elif prev["status"] != c["status"]:
            marker = "REGRESSION" if c["status"] == "fail" else "changed"
            out.append(f"{marker}: {c['id']} {prev['status']} -> {c['status']}")
    for cid in o.keys() - {c["id"] for c in new["checks"]}:
        out.append(f"check no longer run: {cid}")
    return out

