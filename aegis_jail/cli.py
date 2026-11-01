# SPDX-License-Identifier: AGPL-3.0-or-later
"""aegis - command line interface."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from aegis_jail import __version__, paths, trust, workspace
from aegis_jail.agents import Task, get_agent
from aegis_jail.policy import Grant, Profile, baseline_profile


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
        if name == "default":
            # Zero-config: the strict base profile (no extra access at all).
            return Profile(name="default", agent=agent or "claude-code", grants=[])
        raise SystemExit(f"aegis: profile not found: {path} (see `aegis profile list`)")
    prof = Profile.load(path)
    if prof.grants and _in_project(project, path):
        trust.ensure(path)
    return prof


def _in_project(project: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(project.resolve())
        return True
    except ValueError:
        return False


def _load_task(project: Path, args) -> Task:
    tf = Path(args.task_file) if getattr(args, "task_file", None) else paths.project_config_dir(project) / "task.json"
    if tf.exists() and _in_project(project, tf):
        trust.ensure(tf)
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
        raise SystemExit("aegis: no task prompt - use --prompt or set \"prompt\" in .aegis/task.json")
    return task


# ---------------------------------------------------------------- commands

def cmd_init(args) -> int:
    project = _project(args)
    cfg = paths.project_config_dir(project)
    prof_path = cfg / "profiles" / "default.json"
    if prof_path.exists() and not args.force:
        print(f"aegis: {prof_path} already exists (use --force to overwrite)")
        return 1
    agent = get_agent(args.agent)
    starter = Profile(name="default", agent=args.agent, grants=[
        Grant(id="net-setup-any", kind="net", domains=["*"], phase="setup",
              note="internet while installing dependencies"),
    ])
    starter.save(prof_path)
    trust.record(prof_path)
    task_path = cfg / "task.json"
    if not task_path.exists():
        Task(name="example", agent=args.agent, prompt="Describe a representative task for your agent here",
             verify="", setup="").save(task_path)
        trust.record(task_path)
    print(f"Created {prof_path.relative_to(project)} and {task_path.relative_to(project)}\n")
    from aegis_jail.report import describe_profile
    print(describe_profile(starter.merged(agent.grants(Task(agent=args.agent)))))
    print("\nNext: edit .aegis/task.json (prompt, setup, verify), then run `aegis probe` and `aegis run`.")
    return 0


def cmd_doctor(args) -> int:
    from aegis_jail.sandbox import SandboxUnavailable, get_backend
    print(f"Aegis {__version__} on {sys.platform}, Python {sys.version.split()[0]}")
    try:
        b = get_backend()
        from aegis_jail import seccomp
        extra = f" (+ seccomp, {len(seccomp.blocked_numbers())} syscalls blocked)" if getattr(b, "seccomp_enabled", False) else ""
        print(f"Sandbox backend: {b.name} - OK{extra}")
    except SandboxUnavailable as e:
        print(f"Sandbox backend: NOT AVAILABLE - {e}")
        return 1
    for name in ("claude-code", "codex", "gemini", "aider"):
        print(f"Agent {name}: {get_agent(name).version(Task(agent=name))}")
    print(f"State directory: {paths.aegis_home()}")
    return 0


def cmd_run(args) -> int:
    from aegis_jail.report import describe_profile
    from aegis_jail.runner import run_task, terminal_ask
    project = _project(args)
    task = _load_task(project, args)
    profile = _load_profile(project, args.profile, task.agent)
    print(describe_profile(profile.merged(get_agent(task.agent).grants(task))) + "\n")
    rep = run_task(project, profile, task, ask=terminal_ask() if args.ask else None)
    print()
    print(Path(rep.run_dir, "report.md").read_text(encoding="utf-8"))
    if rep.ok and args.apply and rep.changes:
        return cmd_apply(argparse.Namespace(project=args.project, run=rep.run_id, allow_risky=False))
    return 0 if rep.ok else 2


def cmd_probe(args) -> int:
    from aegis_jail.probe import compare, previous_probe, run_probe
    from aegis_jail.report import render_probe
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
    from aegis_jail.optimize import optimize
    from aegis_jail.report import render_optimize
    project = _project(args)
    task = _load_task(project, args)
    start = _load_profile(project, args.start, task.agent)
    if args.start == "baseline":
        start = baseline_profile(task.agent, get_agent(task.agent).grants(task))
        print("[aegis] note: --start baseline gives the first run broad access (home directory, credentials, "
              "internet), roughly what the agent gets without Aegis. Writes stay confined to the working copy.")
    escalate = [Grant(id="home-read", kind="read", path="~", note="read the home directory (not credentials)")]
    print(f"[aegis] optimising '{start.name}' for task '{task.name}' "
          f"(max {args.max_runs} runs, {args.max_minutes:g} min). Each run executes the agent again.")
    res = optimize(project, start, task, max_runs=args.max_runs, max_minutes=args.max_minutes, confirm=args.confirm,
                   escalate=[] if args.no_escalate else escalate)
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
    trust.record(dest)
    print(f"Saved verified profile to {dest}")
    print(f"Use it with: aegis run --profile {args.save}")
    return 0


def cmd_runs(args) -> int:
    from aegis_jail.runner import load_report
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
    from aegis_jail.runner import find_run, load_report
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
    allow_risky = getattr(args, "allow_risky", False)
    risky = [c for c in chs if c.risks]
    if rep.tripwires:
        print("aegis: WARNING - this run tripped a wire (the agent handled decoy credentials):")
        print("\n".join(f"  - {t}" for t in rep.tripwires))
        risky = chs  # every change from a hostile run deserves review
    if risky and not allow_risky and sys.stdin.isatty():
        print("These changes could run code or steer agents outside the sandbox:")
        for c in risky:
            print(f"  {c.path}: {'; '.join(c.risks) or 'from a run that tripped a wire'}")
        allow_risky = input("Apply them anyway? (review `aegis diff` first) [y/N] ").strip().lower() in ("y", "yes", "t", "tak")
        if not allow_risky:
            print("Nothing applied.")
            return 1
    if rep.tripwires and not allow_risky:
        print("aegis: not applied - re-run with --allow-risky after reviewing the diff")
        return 1
    try:
        applied = workspace.apply(project, ws, workspace.load_baseline(rd / "baseline.json"), chs,
                                  allow_risky=allow_risky)
    except (workspace.ApplyConflict, workspace.RiskyChanges) as e:
        print(f"aegis: not applied - {e}")
        return 1
    rep.status = "applied"
    rep.save()
    from aegis_jail.runner import cleanup_run
    cleanup_run(rd)
    print(f"Applied {len(applied)} change(s) to {project}")
    return 0


def cmd_trust(args) -> int:
    project = _project(args)
    files = [Path(f) for f in args.files] or sorted((paths.project_config_dir(project) / "profiles").glob("*.json"))
    task = paths.project_config_dir(project) / "task.json"
    if not args.files and task.exists():
        files.append(task)
    if not files:
        print("No project configuration to trust.")
        return 0
    for f in files:
        state = "trusted" if trust.is_trusted(f) else "NOT trusted"
        print(f"{f} ({state}):\n{trust.summary(f)}\n")
    if args.yes or (sys.stdin.isatty() and input("Trust all of the above? [y/N] ").strip().lower() in ("y", "yes", "t", "tak")):
        for f in files:
            trust.record(f)
        print(f"Trusted {len(files)} file(s).")
        return 0
    print("Nothing changed.")
    return 1


def cmd_discard(args) -> int:
    from aegis_jail.runner import cleanup_run
    _, rd, rep = _run_ctx(args)
    rep.status = "discarded"
    rep.save()
    cleanup_run(rd)
    print(f"Discarded changes from run {rep.run_id}.")
    return 0


def cmd_profile(args) -> int:
    from aegis_jail.report import describe_profile
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



def cmd_wrap(args) -> int:
    from aegis_jail.session import Session, resolve_argv
    project = _project(args)
    profile = _load_profile(project, args.profile, None)
    argv = _strip_dashdash(args.command)
    if not argv:
        raise SystemExit("aegis: give the command to run after --, e.g. aegis wrap -- npm test")
    profile = _with_command_grants(profile, argv, args)
    sess = Session(project=project, profile=profile, write=args.write,
                   ask=_ask() if args.ask else None)
    spec = sess.prepare()
    print(f"[aegis] sandbox: project {'read-write' if args.write else 'read-only'}, network: "
          f"{spec.describe_network()}, home directory and credentials hidden", file=sys.stderr)
    res = sess.run(resolve_argv(argv))
    blocked = sess.blocked_hosts()
    if blocked:
        print(f"[aegis] blocked network access to: {', '.join(blocked)}", file=sys.stderr)
    return res.exit_code


def _with_command_grants(profile, argv, args):
    from aegis_jail.session import command_grants
    grants, notes = command_grants(argv)
    for n in notes:
        print(f"[aegis] {n}", file=sys.stderr)
    extra = [Grant(id=f"cli-read-{i}", kind="read", path=p) for i, p in enumerate(_split(args.allow_read))]
    extra += [Grant(id=f"cli-write-{i}", kind="write", path=p) for i, p in enumerate(_split(args.allow_write))]
    return profile.merged(grants + extra)


def _ask():
    from aegis_jail.runner import terminal_ask
    return terminal_ask()


def _strip_dashdash(cmd: list[str]) -> list[str]:
    return cmd[1:] if cmd and cmd[0] == "--" else cmd


def _split(values: list[str] | None) -> list[str]:
    out: list[str] = []
    for v in values or []:
        out += [x.strip() for x in v.split(",") if x.strip()]
    return out


def cmd_mcp_jail(args) -> int:
    from aegis_jail import mcpjail
    project = _project(args)
    profile = _load_profile(project, args.profile, None)
    hosts = _split(args.allow_hosts)
    if hosts:
        profile = profile.merged([Grant(id="jail-hosts", kind="net", domains=hosts, phase="task")])
    env_names = _split(args.pass_env)
    if env_names:
        profile = profile.merged([Grant(id="jail-env", kind="env", names=env_names)])
    argv = _strip_dashdash(args.command)
    if not argv:
        raise SystemExit("aegis: give the MCP server command after --, e.g. aegis mcp-jail -- npx some-mcp-server")
    profile = _with_command_grants(profile, argv, args)
    name = args.name or Path(argv[-1]).name.replace("/", "_") or "server"
    fw = mcpjail.ToolFirewall(allow=_split(args.allow_tools), deny=_split(args.deny_tools))
    opts = mcpjail.JailOptions(pin=not args.no_pin, allow_poisoned=args.allow_poisoned,
                               allow_sampling=args.allow_sampling, allow_secrets=args.allow_secrets)
    return mcpjail.serve(argv, project=project, profile=profile, firewall=fw, name=name, write=args.write,
                         options=opts)


def cmd_mcp_pins(args) -> int:
    from aegis_jail.mcpjail import Pins
    pins = Pins(args.name)
    if args.reset is not None:
        if args.reset == "ALL":
            pins.data = {}
        else:
            pins.data.pop(args.reset, None)
        pins._save()
        print(f"Reset pins for {args.name}: {args.reset}. Changed tools are accepted on the next start.")
        return 0
    if not pins.data:
        print(f"No pinned tools for '{args.name}' yet.")
    for tool, digest in sorted(pins.data.items()):
        print(f"{tool:40s} {digest[:16]}")
    return 0


def cmd_scan(args) -> int:
    from aegis_jail import scan
    root = Path(args.path).resolve()
    if not root.exists():
        raise SystemExit(f"aegis: no such path: {root}")
    findings = scan.scan(root)
    if args.json:
        print(json.dumps([f.to_dict() for f in findings], indent=2))
    else:
        print(scan.render(findings, root))
    return 2 if any(f.severity == "high" for f in findings) else 0


def cmd_mcp_server(args) -> int:
    from aegis_jail import mcpserver
    return mcpserver.serve()


def cmd_hook(args) -> int:
    from aegis_jail import hook
    return hook.main()


def cmd_windows_setup(args) -> int:
    if sys.platform != "win32":
        print("Nothing to do: this one-time setup is only needed on Windows.")
        return 0
    from aegis_jail.sandbox.windows import windows_setup
    sid = windows_setup()
    print(f"Done. Domain allowlists now work without elevation (shared container {sid}).")
    return 0


def cmd_demo(args) -> int:
    import tempfile
    from aegis_jail.agents import Task
    from aegis_jail.probe import run_probe
    from aegis_jail.report import render_probe
    from aegis_jail.runner import run_task
    src = Path(__file__).resolve().parent / "demo"
    root = Path(tempfile.mkdtemp(prefix="aegis-demo-")).resolve()
    project = root / "shop"
    shutil.copytree(src, project)
    task = Task.load(project / ".aegis" / "task.json")
    bar = "=" * 72
    print(f"{bar}\nAegis demo - a coding agent that was prompt-injected by a README\n{bar}")
    print("The project has a failing test. Its README hides an instruction telling AI agents to read")
    print("~/.ssh and ~/.aws, send them to collector.evil.example and write to your home directory.")
    print("The (scripted, free, reproducible) agent obeys - then fixes the bug.\n")
    print("1) Checking that the sandbox boundaries hold on this machine...")
    probe = run_probe(project, Profile("default", "command"))
    s = probe["summary"]
    print(f"   {s['pass']} checks passed, {s['fail']} failed, {s['inconclusive']} inconclusive\n")
    if args.verbose:
        print(render_probe(probe))
    print("2) Running the agent inside Aegis (allowing only example.com)...")
    prof = Profile("demo", "command", [Grant(id="net-example", kind="net", domains=["example.com"], phase="task")])
    rep = run_task(project, prof, task, quiet=True)
    log = Path(rep.phases[0].log).read_text(encoding="utf-8", errors="replace")
    for line in log.splitlines():
        if line.startswith("[agent]"):
            print("   " + line)
    print()
    ok = rep.ok and not any(w in log for w in ("GOT DATA", "SENT"))
    print(f"   result: tests {'PASS' if rep.ok else 'FAIL'}; changed: {', '.join(c['path'] for c in rep.changes)}")
    for ph in rep.phases:
        if not ph.ok:
            tail = Path(ph.log).read_text(encoding="utf-8", errors="replace").strip().splitlines()[-25:]
            print(f"   --- {ph.name} failed (exit {ph.exit_code}); last lines of its log:")
            print("\n".join("   | " + ln for ln in tail))
    if rep.blocked_network:
        print(f"   blocked network: {', '.join(rep.blocked_network)}")
    for t in rep.tripwires:
        print(f"   TRIPWIRE: {t}")
    if rep.tripwires:
        print("   (the 'keys' the agent read were decoys planted by Aegis - its theft attempt is now on record)")
    print("   your real project is untouched until you run `aegis apply`.\n")
    print(bar)
    print("Secrets stayed hidden, nothing left the machine, the bug got fixed." if ok else
          "Something unexpected happened - please open an issue with this output.")
    print(f"Demo files: {project}\nTry next:  cd {project} && aegis optimize")
    print(bar)
    return 0 if ok else 1

# ---------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="aegis", description="Give an AI agent a task. Keep control of what it can access.")
    ap.add_argument("--version", action="version", version=f"aegis {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--project", default=".", help="project directory (default: current)")
        return p

    def task_opts(p):
        p.add_argument("--task-file", help="task definition (default: .aegis/task.json)")
        p.add_argument("--agent", help="agent: claude-code | codex | gemini | aider | command")
        p.add_argument("--prompt", help="task for the agent")
        p.add_argument("--setup", help="setup command, e.g. 'npm ci'")
        p.add_argument("--verify", help="independent check, e.g. 'npm test'")
        p.add_argument("--timeout", type=float, help="seconds per phase")
        p.add_argument("--agent-cmd", nargs=argparse.REMAINDER,
                       help="run an arbitrary command as the agent ({prompt} is substituted); must be last")

    p = common(sub.add_parser("init", help="create .aegis/ with a starter profile and task"))
    p.add_argument("--agent", default="claude-code")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_init)

    p = sub.add_parser("demo", help="60-second demo: a prompt-injected agent, contained")
    p.add_argument("--verbose", action="store_true")
    p.set_defaults(fn=cmd_demo)

    p = common(sub.add_parser("wrap", help="run any command in the sandbox, interactively (e.g. a shell, a dev tool)"))
    p.add_argument("--profile", default="default")
    p.add_argument("--write", action="store_true", help="let the command write to the project directory")
    p.add_argument("--ask", action="store_true", help="ask before blocking a network host")
    p.add_argument("--allow-read", action="append", help="extra readable paths (comma-separated)")
    p.add_argument("--allow-write", action="append", help="extra writable paths (comma-separated)")
    p.add_argument("command", nargs=argparse.REMAINDER, help="-- command [args...]")
    p.set_defaults(fn=cmd_wrap)

    p = common(sub.add_parser("mcp-jail", help="run an MCP server in the sandbox with a tool firewall + audit log"))
    p.add_argument("--profile", default="default")
    p.add_argument("--name", help="name for the audit log (~/.aegis/mcp/<name>.jsonl)")
    p.add_argument("--write", action="store_true", help="let the server write to the project directory")
    p.add_argument("--allow-hosts", action="append", help="hosts the server may reach (comma-separated)")
    p.add_argument("--allow-tools", action="append", help="only expose these tools (globs, comma-separated)")
    p.add_argument("--deny-tools", action="append", help="hide and block these tools (globs, comma-separated)")
    p.add_argument("--pass-env", action="append", help="environment variables to pass (e.g. GITHUB_TOKEN)")
    p.add_argument("--no-pin", action="store_true", help="do not pin tool definitions (rug-pull protection)")
    p.add_argument("--allow-poisoned", action="store_true", help="show tools whose descriptions look poisoned")
    p.add_argument("--allow-sampling", action="store_true", help="let the server request completions from your model")
    p.add_argument("--allow-secrets", action="store_true", help="let tool arguments carry credentials")
    p.add_argument("--allow-read", action="append", help="extra readable paths (comma-separated)")
    p.add_argument("--allow-write", action="append", help="extra writable paths (comma-separated)")
    p.add_argument("command", nargs=argparse.REMAINDER, help="-- server command [args...]")
    p.set_defaults(fn=cmd_mcp_jail)

    p = sub.add_parser("scan", help="scan a repo / skill / plugin / MCP server for agent-hijacking risks (runs nothing)")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_scan)

    p = sub.add_parser("mcp-pins", help="show / reset the pinned tool definitions of a jailed MCP server")
    p.add_argument("name")
    p.add_argument("--reset", nargs="?", const="ALL", help="forget one tool's pin (or all) to accept a change")
    p.set_defaults(fn=cmd_mcp_pins)

    p = sub.add_parser("mcp-server", help="expose Aegis tools to AI clients over MCP (stdio)")
    p.set_defaults(fn=cmd_mcp_server)

    p = sub.add_parser("hook", help="Claude Code PreToolUse guard (used by the plugin)")
    p.add_argument("kind", choices=["claude-pretooluse"])
    p.set_defaults(fn=cmd_hook)

    p = sub.add_parser("windows-setup", help="one-time elevated setup for domain allowlists on Windows")
    p.set_defaults(fn=cmd_windows_setup)

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
    p.add_argument("--start", default="default",
                   help="starting profile (default: the project's profile; 'baseline' = broad access, then shrink)")
    p.add_argument("--no-escalate", action="store_true", help="never add read access to the home directory")
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
        if name == "apply":
            p.add_argument("--allow-risky", action="store_true",
                           help="also apply changes flagged as risky (agent configs, hooks, CI, scripts...)")
        p.set_defaults(fn=fn)

    p = common(sub.add_parser("trust", help="review and approve the project's .aegis profiles / task"))
    p.add_argument("files", nargs="*")
    p.add_argument("--yes", action="store_true", help="approve without asking")
    p.set_defaults(fn=cmd_trust)

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
        print(f"aegis: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001 - top-level user-facing error
        from aegis_jail.sandbox import SandboxUnavailable
        from aegis_jail.trust import Untrusted
        from aegis_jail.workspace import ApplyConflict, RiskyChanges
        if isinstance(e, (SandboxUnavailable, ValueError, Untrusted, ApplyConflict, RiskyChanges)):
            print(f"aegis: {e}", file=sys.stderr)
            return 1
        raise
