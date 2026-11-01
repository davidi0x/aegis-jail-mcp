# SPDX-License-Identifier: AGPL-3.0-or-later
"""Human-readable reports (Markdown) for runs, probes and optimisations."""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

from aegis_jail.policy import Grant, Profile
from aegis_jail.sandbox.base import SandboxSpec

if TYPE_CHECKING:
    from aegis_jail.optimize import OptimizeResult
    from aegis_jail.runner import RunReport


def plain_removed(grants: list[Grant]) -> list[str]:
    out = []
    for g in grants:
        if g.id.startswith("secret:"):
            out.append(f"access to {g.path} (credentials)")
        elif g.id == "home-read":
            out.append("reading the rest of the home directory (other projects, dotfiles)")
        elif g.kind == "net" and "*" in (g.domains or []):
            out.append("internet " + ("after dependency installation" if g.phase == "task" else
                                      "during dependency installation" if g.phase == "setup" else "at all"))
        elif g.kind == "env":
            names = g.names or []
            more = f" and {len(names) - 4} more" if len(names) > 4 else ""
            out.append(f"{len(names)} credential-like environment variable(s) ({', '.join(names[:4])}{more})")
        else:
            out.append(g.describe())
    return out


def describe_profile(profile: Profile, spec: SandboxSpec | None = None) -> str:
    """The short 'before the task' summary."""
    lines = [f"Profile: {profile.name}  (agent: {profile.agent})",
             "  Write: project working copy" + "".join(f", {g.path}" for g in profile.grants if g.kind == "write"),
             ]
    reads = [g.path for g in profile.grants if g.kind == "read"]
    lines.append("  Extra read access: " + (", ".join(reads) if reads else "none"))
    secrets = [g.path for g in profile.grants if g.id.startswith("secret:")]
    lines.append("  Private files and keys: " + ("ACCESSIBLE: " + ", ".join(secrets) if secrets else "not accessible"))
    for phase in ("setup", "task"):
        doms: list[str] = []
        for g in profile.grants:
            if g.kind == "net" and g.applies_to(phase):
                doms += g.domains or []
        net = "unrestricted" if "*" in doms else ("only " + ", ".join(sorted(set(doms))) if doms else "none")
        lines.append(f"  Network ({phase}): {net}")
    lines.append("  Applying changes to the project: requires your approval (aegis apply)")
    if profile.verified:
        v = profile.verified
        lines.append(f"  Verified: {v.get('date')} on task '{v.get('task', {}).get('name')}' "
                     f"({v.get('confirmed')} confirmation runs passed)")
    return "\n".join(lines)


def render_run(r: "RunReport") -> str:
    when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r.started))
    status = "PASSED" if r.ok else "FAILED"
    out = [f"# Aegis run {r.run_id}", "",
           f"- **Result:** {status}", f"- **Project:** `{r.project}`", f"- **Started:** {when}",
           f"- **Profile:** {r.profile.get('name')} - agent `{r.task.get('agent')}` ({r.agent_version})",
           f"- **Sandbox:** {r.backend} on {r.platform}", f"- **Aegis:** {r.aegis_version}",
           f"- **Changes:** {r.status}", ""]
    trip = getattr(r, "tripwires", [])
    if trip:
        out += ["## TRIPWIRE - likely compromised or prompt-injected agent", "",
                "The agent handled decoy credentials that no legitimate task needs:", ""]
        out += [f"- {t}" for t in trip]
        out += ["", "Treat this run as hostile: review the diff carefully or discard it, and check what the agent "
                "read (its instructions, README, issues, web pages, tool results).", ""]
    out += ["## Phases", "",
           "| Phase | Result | Time | Network |", "|---|---|---|---|"]
    for p in r.phases:
        res = "ok" if p.ok else ("timed out" if p.timed_out else f"exit {p.exit_code}")
        out.append(f"| {p.name} | {res} | {p.duration:.1f}s | {p.network} |")
    out += ["", "## Changed files", ""]
    if r.changes:
        for c in r.changes:
            risk = f" - **RISKY:** {'; '.join(c['risks'])}" if c.get("risks") else ""
            out.append(f"- `{c['path']}` ({c['kind']}){risk}")
    else:
        out.append("No changes.")
    out += ["", "## Blocked operations", ""]
    blocked = r.blocked_network
    if blocked:
        out += [f"- Network: agent tried to reach `{h}` - blocked" for h in blocked]
    hints = [h for p in r.phases for h in p.hints if "Aegis blocked network" not in h]
    if hints:
        out.append("- Possible file/permission denials seen in output:")
        out += [f"  - `{h}`" for h in hints[:15]]
    if not blocked and not hints:
        out.append("None detected.")
    notes = getattr(r, "notes", [])
    if notes:
        out += ["", "## Protection notes", ""] + [f"- {n}" for n in notes]
    out += ["", "## Exceptions used", ""]
    out += [f"- Temporary network exception for `{e}` (this session only)" for e in r.exceptions] or ["None."]
    out += ["", "## Next steps", "",
            f"- Review: `aegis diff {r.run_id}`",
            f"- Accept: `aegis apply {r.run_id}`  /  reject: `aegis discard {r.run_id}`",
            "- Logs: " + ", ".join(f"`{Path(p.log).name}`" for p in r.phases), ""]
    from aegis_jail.textsafe import for_terminal
    return for_terminal("\n".join(out))


def render_probe(p: dict, regressions: list[str] | None = None) -> str:
    s = p["summary"]
    out = [f"# Aegis boundary probe - profile '{p['profile']}' ({p['phase']} phase)", "",
           f"- Sandbox: {p['backend']}, network: {p['network']}",
           f"- Result: {s['pass']} pass, {s['fail']} fail, {s['inconclusive']} inconclusive, {s['error']} error",
           "", "| Check | Target | Expected | Observed (process / child) | Status |", "|---|---|---|---|---|"]
    for c in p["checks"]:
        obs = c["observed"] + (f" / {c['observed_child']}" if c["observed_child"] else "")
        out.append(f"| {c['id']} | `{c['target']}` | {c['expect']} | {obs} | **{c['status'].upper()}** |")
    if regressions is not None:
        out += ["", "## Compared with previous probe", ""]
        out += [f"- {r}" for r in regressions] or ["- No changes."]
    return "\n".join(out) + "\n"


def render_optimize(res: "OptimizeResult") -> str:
    out = ["# Aegis permission optimisation", "", f"**{res.summary}**", ""]
    if res.added:
        out += ["## Added (the task needed it)", ""] + [f"- `{g.id}` - {g.describe()}" for g in res.added] + [""]
    if res.removed:
        out += ["## Removed (task still passed)", ""] + [f"- `{g.id}` - {d}" for g, d in zip(res.removed, plain_removed(res.removed))] + [""]
    out += ["## Kept", ""]
    if not res.kept:
        out.append("- Nothing beyond Aegis's base: the working copy, a private temp dir and read-only system files.")
    for g in res.kept:
        out.append(f"- `{g.id}` - {g.describe()}" + (" (required by the agent)" if g.locked else ""))
    out += ["", "## Runs", "", "| # | Without | Result |", "|---|---|---|"]
    for i, t in enumerate(res.trials, 1):
        out.append(f"| {i} | {', '.join(t.removed) or 'baseline'} | {'pass' if t.ok else 'fail: ' + t.reason} |")
    out += ["", f"Confirmation runs passed: {res.confirmed}/{res.confirm_runs}"]
    if res.stopped_early:
        out.append(f"\nStopped early: {res.stopped_early}")
    out += ["", "_This is evidence for the tested task only; one successful run does not prove the profile "
            "is enough for every task._", ""]
    return "\n".join(out)
