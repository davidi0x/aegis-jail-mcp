"""hydra - command line interface."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from hydra_guard import __version__, paths, workspace
from hydra_guard.agents import Task, get_agent
from hydra_guard.policy import Grant, Profile, baseline_profile


def _project(args) -> Path:
    return Path(args.project).resolve()


def _profile_path(project: Path, name: str) -> Path:
    p = Path(name)
    if p.suffix == ".json" and p.exists():
        return p
    return paths.project_config_dir(project) / "profiles" / f"{name}.json"


def _load_profile(project: Path, name: str, agent: str | None) -> Profile:
    if name == "baseline":
        a = agent or "claude-code"
        return baseline_profile(a, [])
    path = _profile_path(project, name)
    if not path.exists():
        raise SystemExit(f"hydra: profile not found: {path} (run `hydra init` first)")
    return Profile.load(path)


def _load_task(project: Path, args) -> Task:
    tf = Path(args.task_file) if getattr(args, "task_file", None) else paths.project_config_dir(project) / "task.json"
    task = Task.load(tf) if tf.exists() else Task()
    if getattr(args, "agent", None):
        task.agent = args.agent
    if getattr(args, "prompt", None):
        task.prompt = args.prompt
    if getattr(args, "verify", None) is not None:
        task.verify = args.verify
    if getattr(args, "setup", None) is not None:
        task.setup = args.setup
    if getattr(args, "timeout", None):
        task.timeout = args.timeout
    if getattr(args, "agent_cmd", None):
        task.command = args.agent_cmd
        task.agent = "command"
    if task.agent == "claude-code" and not task.prompt:
        raise SystemExit("hydra: no task prompt - use --prompt or set \"prompt\" in .hydra/task.json")
    return task


# ---------------------------------------------------------------- commands

def cmd_init(args) -> int:
    project = _project(args)
    cfg = paths.project_config_dir(project)
    prof_path = cfg / "profiles" / "default.json"
    if prof_path.exists() and not args.force:
        print(f"hydra: {prof_path} already exists (use --force to overwrite)")
        return 1
    agent = get_agent(args.agent)
    starter = Profile(name="default", agent=args.agent, grants=[
        Grant(id="net-setup-any", kind="net", domains=["*"], phase="setup",
              note="internet while installing dependencies"),
    ])
    starter.save(prof_path)
    task_path = cfg / "task.json"
    if not task_path.exists():
        Task(name="example", agent=args.agent, prompt="Describe a representative task for your agent here",
             verify="", setup="").save(task_path)
    print(f"Created {prof_path.relative_to(project)} and {task_path.relative_to(project)}\n")
    from hydra_guard.report import describe_profile
    print(describe_profile(starter.merged(agent.grants(Task(agent=args.agent)))))
    print("\nNext: edit .hydra/task.json (prompt, setup, verify), then run `hydra probe` and `hydra run`.")
    return 0


def cmd_doctor(args) -> int:
    from hydra_guard.sandbox import SandboxUnavailable, get_backend
    print(f"Hydra {__version__} on {sys.platform}, Python {sys.version.split()[0]}")
    try:
        b = get_backend()
        print(f"Sandbox backend: {b.name} - OK")
    except SandboxUnavailable as e:
        print(f"Sandbox backend: NOT AVAILABLE - {e}")
        return 1
    for name in ("claude-code",):
        print(f"Agent {name}: {get_agent(name).version(Task(agent=name))}")
    print(f"State directory: {paths.hydra_home()}")
    return 0


def cmd_run(args) -> int:
    from hydra_guard.report import describe_profile
    from hydra_guard.runner import run_task, terminal_ask
    project = _project(args)
    task = _load_task(project, args)
    profile = _load_profile(project, args.profile, task.agent)
    print(describe_profile(profile.merged(get_agent(task.agent).grants(task))) + "\n")
    rep = run_task(project, profile, task, ask=terminal_ask() if args.ask else None)
    print()
    print(Path(rep.run_dir, "report.md").read_text(encoding="utf-8"))
    if rep.ok and args.apply and rep.changes:
        return cmd_apply(argparse.Namespace(project=args.project, run=rep.run_id))
    return 0 if rep.ok else 2


def cmd_probe(args) -> int:
    from hydra_guard.probe import compare, previous_probe, run_probe
    from hydra_guard.report import render_probe
    project = _project(args)
    profile = _load_profile(project, args.profile, args.agent)
    task = Task(agent=args.agent or profile.agent, command=["true"])
    result = run_probe(project, profile, phase=args.phase, task=task)
    regs = None
    if args.compare:
        prev = previous_probe(project, profile.name, result["run_id"])
        regs = compare(prev, result) if prev else ["no previous probe of this profile to compare with"]
    print(render_probe(result, regs))
    if args.json:
        print(json.dumps(result, indent=2))
    failed = result["summary"]["fail"] + result["summary"]["error"]
    if regs and any(r.startswith("REGRESSION") for r in regs):
        failed += 1
    return 1 if failed else 0


def cmd_optimize(args) -> int:
    from hydra_guard.optimize import optimize
    from hydra_guard.report import render_optimize
    project = _project(args)
    task = _load_task(project, args)
    start = _load_profile(project, args.start, task.agent)
    if args.start == "baseline":
        start = baseline_profile(task.agent, get_agent(task.agent).grants(task))
    if args.start == "baseline":
        print("[hydra] note: the first run uses a broad baseline (home directory, credentials, internet) to show the "
              "task can pass at all - roughly what the agent gets without Hydra. Writes stay confined to the working "
              "copy. Use --start <profile> to begin from a narrower profile instead.")
    print(f"[hydra] optimising '{start.name}' for task '{task.name}' "
          f"(max {args.max_runs} runs, {args.max_minutes:g} min). Each run executes the agent again.")
    res = optimize(project, start, task, max_runs=args.max_runs, max_minutes=args.max_minutes, confirm=args.confirm)
    md = render_optimize(res)
    print("\n" + md)
    out_dir = paths.runs_dir(project) / "optimizations"
    out_dir.mkdir(exist_ok=True)
    (out_dir / f"{res.trials[0].run_id}.md").write_text(md, encoding="utf-8")
    if res.baseline_failed:
        return 2
    res.final.name = args.save
    dest = _profile_path(project, args.save)
    res.final.save(dest)
    print(f"Saved verified profile to {dest}")
    print(f"Use it with: hydra run --profile {args.save}")
    return 0


def cmd_runs(args) -> int:
    from hydra_guard.runner import load_report
    project = _project(args)
    base = paths.runs_dir(project)
    rows = sorted(p for p in base.iterdir() if (p / "report.json").exists())
    if not rows:
        print("No runs yet.")
    for p in rows[-args.limit:]:
        r = load_report(p)
        print(f"{r.run_id}  {'PASS' if r.ok else 'FAIL'}  {len(r.changes):3d} changes  {r.status:9s}  "
              f"{r.profile.get('name')}  {r.task.get('name')}")
    return 0


def _run_ctx(args):
    from hydra_guard.runner import find_run, load_report
    project = _project(args)
    rd = find_run(project, args.run)
    return project, rd, load_report(rd)


def cmd_show(args) -> int:
    _, rd, _ = _run_ctx(args)
    print((rd / "report.md").read_text(encoding="utf-8"))
    return 0


def cmd_diff(args) -> int:
    project, rd, rep = _run_ctx(args)
    ws = rd / "workspace"
    if not ws.exists():
        print("The working copy of this run was already removed.")
        return 1
    chs = [workspace.Change(**c) for c in rep.changes]
    print(workspace.unified_diff(project, ws, chs) or "No changes.")
    return 0


def cmd_apply(args) -> int:
    project, rd, rep = _run_ctx(args)
    ws = rd / "workspace"
    if rep.status != "pending" or not ws.exists():
        print(f"Run {rep.run_id} is already {rep.status}.")
        return 1
    chs = [workspace.Change(**c) for c in rep.changes]
    try:
        applied = workspace.apply(project, ws, workspace.load_baseline(rd / "baseline.json"), chs)
    except workspace.ApplyConflict as e:
        print(f"hydra: not applied - {e}")
        return 1
    rep.status = "applied"
    rep.save()
    from hydra_guard.runner import cleanup_run
    cleanup_run(rd)
    print(f"Applied {len(applied)} change(s) to {project}")
    return 0


def cmd_discard(args) -> int:
    from hydra_guard.runner import cleanup_run
    _, rd, rep = _run_ctx(args)
    rep.status = "discarded"
    rep.save()
    cleanup_run(rd)
    print(f"Discarded changes from run {rep.run_id}.")
    return 0


def cmd_profile(args) -> int:
    from hydra_guard.report import describe_profile
    project = _project(args)
    if args.action == "list":
        d = paths.project_config_dir(project) / "profiles"
        for p in sorted(d.glob("*.json")) if d.exists() else []:
            prof = Profile.load(p)
            print(f"{prof.name:20s} agent={prof.agent:12s} grants={len(prof.grants):2d} "
                  f"{'verified ' + prof.verified['date'] if prof.verified else 'not verified'}")
        return 0
    profile = _load_profile(project, args.name, None)
    if args.action == "show":
        print(describe_profile(profile))
    elif args.action == "export":
        print(json.dumps(profile.to_dict(), indent=2))
    return 0


def cmd_gc(args) -> int:
    project = _project(args)
    base = paths.runs_dir(project)
    removed = 0
    for p in sorted(base.iterdir()):
        if p.is_dir() and p.name not in ("probes", "optimizations"):
            shutil.rmtree(p, ignore_errors=True)
            removed += 1
    print(f"Removed {removed} run(s).")
    return 0


# ---------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="hydra", description="Give an AI agent a task. Keep control of what it can access.")
    ap.add_argument("--version", action="version", version=f"hydra {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--project", default=".", help="project directory (default: current)")
        return p

    def task_opts(p):
        p.add_argument("--task-file", help="task definition (default: .hydra/task.json)")
        p.add_argument("--agent", help="agent adapter: claude-code | command")
        p.add_argument("--prompt", help="task for the agent")
        p.add_argument("--setup", help="setup command, e.g. 'npm ci'")
        p.add_argument("--verify", help="independent check, e.g. 'npm test'")
        p.add_argument("--timeout", type=float, help="seconds per phase")
        p.add_argument("--agent-cmd", nargs=argparse.REMAINDER,
                       help="run an arbitrary command as the agent ({prompt} is substituted); must be last")

    p = common(sub.add_parser("init", help="create .hydra/ with a starter profile and task"))
    p.add_argument("--agent", default="claude-code")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_init)

    p = sub.add_parser("doctor", help="check that sandboxing works on this machine")
    p.set_defaults(fn=cmd_doctor)

    p = common(sub.add_parser("run", help="run the task in a protected session"))
    p.add_argument("--profile", default="default")
    p.add_argument("--ask", action="store_true", help="ask before blocking a network host (session-only exception)")
    p.add_argument("--apply", action="store_true", help="apply the changes if every phase passed")
    task_opts(p)
    p.set_defaults(fn=cmd_run)

    p = common(sub.add_parser("probe", help="test that a profile's boundaries hold in practice"))
    p.add_argument("--profile", default="default")
    p.add_argument("--agent")
    p.add_argument("--phase", default="task", choices=["setup", "task"])
    p.add_argument("--compare", action="store_true", help="compare with the previous probe of this profile")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_probe)

    p = common(sub.add_parser("optimize", help="find the smallest permissions with which the task still passes"))
    p.add_argument("--start", default="baseline", help="starting profile (default: a broad baseline)")
    p.add_argument("--save", default="verified", help="name for the resulting profile")
    p.add_argument("--max-runs", type=int, default=12)
    p.add_argument("--max-minutes", type=float, default=60)
    p.add_argument("--confirm", type=int, default=1, help="extra runs of the final profile")
    task_opts(p)
    p.set_defaults(fn=cmd_optimize)

    for name, fn, hlp in (("show", cmd_show, "show a run report"), ("diff", cmd_diff, "show a run's changes"),
                          ("apply", cmd_apply, "copy a run's changes into the project"),
                          ("discard", cmd_discard, "throw away a run's changes")):
        p = common(sub.add_parser(name, help=hlp))
        p.add_argument("run", nargs="?", default="last")
        p.set_defaults(fn=fn)

    p = common(sub.add_parser("runs", help="list runs"))
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(fn=cmd_runs)

    p = common(sub.add_parser("profile", help="list / show / export profiles"))
    p.add_argument("action", choices=["list", "show", "export"])
    p.add_argument("name", nargs="?", default="default")
    p.set_defaults(fn=cmd_profile)

    p = common(sub.add_parser("gc", help="delete stored runs of this project"))
    p.set_defaults(fn=cmd_gc)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.fn(args) or 0)
    except FileNotFoundError as e:
        print(f"hydra: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001 - top-level user-facing error
        from hydra_guard.sandbox import SandboxUnavailable
        if isinstance(e, (SandboxUnavailable, ValueError)):
            print(f"hydra: {e}", file=sys.stderr)
            return 1
        raise
