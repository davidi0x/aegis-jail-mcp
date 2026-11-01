# SPDX-License-Identifier: AGPL-3.0-or-later
"""Run a task in a protected session: working copy -> setup -> agent -> verify -> report."""

from __future__ import annotations

import json
import platform
import re
import secrets
import shutil
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from aegis_jail import __version__, paths, workspace
from aegis_jail.agents import Task, get_agent, runtime_paths, shell
from aegis_jail.netproxy import FilteringProxy
from aegis_jail.policy import Profile
from aegis_jail.sandbox import Backend, SandboxSpec, get_backend

BLOCK_HINTS = re.compile(
    r"(Permission denied|Operation not permitted|EACCES|EPERM|Read-only file system|"
    r"Access is denied|Aegis blocked network access[^\n]*|Network is unreachable|"
    r"Could not resolve host[^\n]*|getaddrinfo [A-Z_]+[^\n]*|Temporary failure in name resolution|"
    r"Name or service not known|nodename nor servname provided)", re.I)


@dataclass
class PhaseResult:
    name: str
    command: list[str]
    exit_code: int
    timed_out: bool
    duration: float
    network: str
    log: str
    net_events: list[dict] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["ok"] = self.ok
        return d


@dataclass
class RunReport:
    run_id: str
    project: str
    run_dir: str
    profile: dict
    task: dict
    backend: str
    started: float
    phases: list[PhaseResult]
    changes: list[dict]
    exceptions: list[str]
    aegis_version: str = __version__
    platform: str = field(default_factory=lambda: f"{platform.system()} {platform.release()} {platform.machine()}")
    agent_version: str = ""
    status: str = "pending"  # pending | applied | discarded
    notes: list[str] = field(default_factory=list)
    hidden: list[str] = field(default_factory=list)
    tripwires: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.phases) and all(p.ok for p in self.phases)

    @property
    def blocked_network(self) -> list[str]:
        out = []
        for p in self.phases:
            for e in p.net_events:
                if not e["allowed"]:
                    item = f"{e['host']}:{e['port']}"
                    if item not in out:
                        out.append(item)
        return out

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["phases"] = [p.to_dict() for p in self.phases]
        d["ok"] = self.ok
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "RunReport":
        d = dict(d)
        d.pop("ok", None)
        phases = []
        for p in d.pop("phases"):
            p = dict(p)
            p.pop("ok", None)
            phases.append(PhaseResult(**p))
        return cls(phases=phases, **d)

    def save(self) -> None:
        rd = Path(self.run_dir)
        (rd / "report.json").write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        from aegis_jail.report import render_run
        (rd / "report.md").write_text(render_run(self), encoding="utf-8")


def load_report(run_dir: Path) -> RunReport:
    return RunReport.from_dict(json.loads((run_dir / "report.json").read_text(encoding="utf-8")))


def find_run(project: Path, run_id: str | None) -> Path:
    base = paths.runs_dir(project)
    runs = sorted((p for p in base.iterdir() if (p / "report.json").exists()), key=lambda p: p.name)
    if not runs:
        raise FileNotFoundError("no runs yet for this project")
    if run_id in (None, "last", "latest"):
        return runs[-1]
    matches = [r for r in runs if r.name.startswith(run_id or "")]
    if len(matches) != 1:
        raise FileNotFoundError(f"run {run_id!r} not found (or ambiguous)")
    return matches[0]


def terminal_ask(lock: threading.Lock | None = None) -> Callable[[str, int], bool]:
    lock = lock or threading.Lock()

    def ask(host: str, port: int) -> bool:
        if not sys.stdin.isatty():
            return False
        with lock:
            print(f"\n[aegis] The agent is trying to connect to {host}:{port}, which this profile does not allow.")
            ans = input("[aegis] Allow this host for the rest of THIS session only? [y/N] ").strip().lower()
        return ans in ("y", "yes", "t", "tak")

    return ask


def run_phase(backend: Backend, spec: SandboxSpec, name: str, argv: list[str], run_dir: Path, timeout: float,
              ask: Callable[[str, int], bool] | None, exceptions: list[str]) -> PhaseResult:
    log_path = run_dir / f"{name}.log"
    log_path.write_bytes(b"")
    proxy = None
    if isinstance(spec.network, list):
        proxy = FilteringProxy(spec.network, ask=ask, tcp=backend.name != "linux-bwrap",
                               unix=backend.name == "linux-bwrap").start()
    try:
        res = backend.run(spec, argv, log_path=log_path, timeout=timeout, proxy=proxy)
    finally:
        if proxy:
            proxy.stop()
            exceptions.extend(h for h in proxy.session_exceptions if h not in exceptions)
    text = log_path.read_text(encoding="utf-8", errors="replace")
    hints = []
    for m in BLOCK_HINTS.finditer(text):
        line_start = text.rfind("\n", 0, m.start()) + 1
        line_end = text.find("\n", m.end())
        line = text[line_start: line_end if line_end != -1 else None].strip()[:300]
        if line not in hints:
            hints.append(line)
        if len(hints) >= 20:
            break
    return PhaseResult(name=name, command=argv, exit_code=res.exit_code, timed_out=res.timed_out,
                       duration=round(res.duration, 2), network=spec.describe_network(), log=str(log_path),
                       net_events=[e.to_dict() for e in proxy.events] if proxy else [], hints=hints)


def new_run_dir(project: Path) -> tuple[str, Path]:
    run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
    rd = paths.runs_dir(project) / run_id
    rd.mkdir(parents=True)
    return run_id, rd


def run_task(project: Path, profile: Profile, task: Task, *, ask: Callable[[str, int], bool] | None = None,
             backend: Backend | None = None, quiet: bool = False) -> RunReport:
    project = project.resolve()
    backend = backend or get_backend()
    agent = get_agent(task.agent)
    profile = profile.merged(agent.grants(task))
    run_id, rd = new_run_dir(project)
    ws = rd / "workspace"
    tmp = rd / "tmp"
    tmp.mkdir()
    copy = workspace.create(project, ws, profile.expose_globs())
    baseline = copy.baseline
    workspace.save_baseline(rd / "baseline.json", baseline)
    rt = runtime_paths()

    def spec(phase: str) -> SandboxSpec:
        return profile.compile(phase, project=project, workspace=ws, tmp=tmp, runtime_paths=rt)

    exceptions: list[str] = []
    phases: list[PhaseResult] = []
    plan: list[tuple[str, str, list[str]]] = []
    if task.setup:
        plan.append(("setup", "setup", shell(task.expand(task.setup))))
    plan.append(("agent", "task", agent.argv(task)))
    if task.verify:
        plan.append(("verify", "task", shell(task.expand(task.verify))))

    started = time.time()
    for name, phase, argv in plan:
        if not quiet:
            print(f"[aegis] {name}: {' '.join(argv)[:120]}", flush=True)
        pr = run_phase(backend, spec(phase), name, argv, rd, task.timeout, ask, exceptions)
        phases.append(pr)
        if not quiet:
            state = "ok" if pr.ok else ("timed out" if pr.timed_out else f"failed (exit {pr.exit_code})")
            print(f"[aegis] {name}: {state} in {pr.duration:.1f}s", flush=True)
        if not pr.ok:
            break

    chs = workspace.changes(baseline, ws, project)
    report = RunReport(run_id=run_id, project=str(project), run_dir=str(rd), profile=profile.to_dict(),
                       task=task.__dict__.copy(), backend=backend.name, started=started, phases=phases,
                       changes=[c.to_dict() for c in chs], exceptions=exceptions,
                       agent_version=agent.version(task), notes=copy.notes, hidden=sorted(copy.hidden),
                       tripwires=find_tripwires(phases, chs, ws))
    report.save()
    return report


def find_tripwires(phases: list[PhaseResult], chs, ws: Path) -> list[str]:
    """Hard evidence of credential theft attempts (decoys / canary showing up anywhere)."""
    from aegis_jail import secretscan
    out: list[str] = []
    for p in phases:
        for e in p.net_events:
            if e.get("tripwire"):
                out.append(f"{p.name}: network: {e['host']}:{e['port']} - {e['reason']}")
        try:
            if secretscan.is_decoy_hit(Path(p.log).read_text(encoding="utf-8", errors="replace")):
                out.append(f"{p.name}: decoy credentials appeared in the program's output")
        except OSError:
            pass
    for c in chs:
        if c.kind == "deleted":
            continue
        try:
            data = (ws / c.path).read_bytes()[:2_000_000].decode("utf-8", "replace")
        except OSError:
            continue
        if secretscan.is_decoy_hit(data):
            out.append(f"files: decoy credentials were written into {c.path}")
    return out


def cleanup_run(run_dir: Path, keep_report: bool = True) -> None:
    for name in ("workspace", "tmp", "tmp-decoys"):
        p = run_dir / name
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)
    if not keep_report:
        shutil.rmtree(run_dir, ignore_errors=True)
