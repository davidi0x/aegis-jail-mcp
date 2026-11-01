"""Permission minimisation with proof that the task still works.

Starting from a profile where the task passes, Aegis removes grants one
group / one grant at a time, reruns the task from a fresh working copy and
keeps a removal only if the task (agent + independent verify command) still
passes. The run count and wall-clock budget are capped because every rerun
may cost model calls.

The result is evidence about *these* tasks, not a proof that the profile is
enough for every possible task.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from aegis_jail import __version__
from aegis_jail.agents import Task
from aegis_jail.policy import Grant, Profile
from aegis_jail.runner import RunReport, cleanup_run, run_task
from aegis_jail.sandbox import Backend, get_backend


@dataclass
class Trial:
    removed: list[str]
    run_id: str
    ok: bool
    reason: str

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class OptimizeResult:
    start: Profile
    final: Profile
    removed: list[Grant]
    kept: list[Grant]
    trials: list[Trial] = field(default_factory=list)
    added: list[Grant] = field(default_factory=list)
    confirmed: int = 0
    confirm_runs: int = 0
    stopped_early: str = ""
    baseline_failed: bool = False

    @property
    def summary(self) -> str:
        from aegis_jail.report import plain_removed
        if self.baseline_failed:
            return ("The task did not pass, even after learning the hosts it uses; check the logs - the task, "
                    "the verify command or a needed file grant may be missing.")
        if not self.removed and not self.added and not any(g for g in self.start.grants if not g.locked):
            return "The task already passes with the strict base profile - there is nothing to remove."
        if not self.removed:
            if self.added:
                return "The task needed: " + "; ".join(g.describe() for g in self.added) + " - nothing else."
            return "Every removable permission turned out to be needed (or the budget ran out first)."
        return "The task passed its tests without: " + "; ".join(plain_removed(self.removed)) + "."


def _failure_reason(rep: RunReport) -> str:
    for p in rep.phases:
        if not p.ok:
            what = "timed out" if p.timed_out else f"exit {p.exit_code}"
            extra = f"; blocked: {', '.join(rep.blocked_network[:3])}" if rep.blocked_network else ""
            return f"{p.name} {what}{extra}"
    return "ok"


def _hosts(rep: RunReport, phase_names: tuple[str, ...]) -> list[str]:
    out: list[str] = []
    for p in rep.phases:
        if p.name in phase_names:
            for e in p.net_events:
                if not e["allowed"] or e.get("tripwire"):
                    continue  # never learn hosts that only received blocked / credential-carrying traffic
                h = e["host"] if e["port"] in (80, 443) else f"{e['host']}:{e['port']}"
                if h not in out:
                    out.append(h)
    return out


def learn_network(rep: RunReport) -> list[Grant]:
    """Turn the hosts seen by the logging proxy into narrow per-host grants."""
    grants = []
    for phase, names in (("setup", ("setup",)), ("task", ("agent", "verify"))):
        for h in _hosts(rep, names):
            grants.append(Grant(id=f"net-{phase}:{h}", kind="net", domains=[h], phase=phase,
                                note="learned from a logged run"))
    return grants


def optimize(project: Path, start: Profile, task: Task, *, max_runs: int = 12, max_minutes: float = 60,
             confirm: int = 1, backend: Backend | None = None, escalate: list[Grant] | None = None,
             log: Callable[[str], None] = print) -> OptimizeResult:
    """Find a small profile under which the task passes.

    1. Try the starting profile (by default the project's narrow profile).
    2. If it fails, run once with *logged* network (every host allowed but
       recorded by the proxy, files still confined) and retry with exactly
       the hosts that were used.
    3. If it still fails, add broader grants from `escalate` one at a time
       (credentials are never added automatically).
    4. Remove every grant that turns out not to be needed.
    """
    backend = backend or get_backend()
    deadline = time.monotonic() + max_minutes * 60
    runs = 0
    trials: list[Trial] = []

    last: dict[str, RunReport] = {}

    def attempt(profile: Profile, removed: list[str], label: str | None = None) -> bool:
        nonlocal runs
        runs += 1
        rep = run_task(project, profile, task, backend=backend, quiet=True)
        last["rep"] = rep
        ok = rep.ok
        trials.append(Trial(removed if label is None else [label], rep.run_id, ok, _failure_reason(rep)))
        cleanup_run(Path(rep.run_dir))
        label = label or ("starting profile" if not removed else "without " + ", ".join(removed))
        log(f"[aegis] run {runs}/{max_runs}: {label}: {'PASS' if ok else 'FAIL - ' + _failure_reason(rep)}")
        return ok

    def budget_left() -> str:
        if runs >= max_runs:
            return f"run limit ({max_runs}) reached"
        if time.monotonic() > deadline:
            return f"time budget ({max_minutes:g} min) reached"
        return ""

    result = OptimizeResult(start=start, final=start, removed=[], kept=[], trials=trials)
    current = start
    if not attempt(start, []):
        # Learn which hosts the task needs, with network fully logged.
        probe = start.merged([Grant(id="net-learn", kind="net", domains=["**"], phase="all")])
        attempt(probe, [], label="learning: network allowed but logged")
        learned = learn_network(last["rep"])
        passed = False
        if learned:
            log("[aegis] hosts used: " + ", ".join(sorted({g.domains[0] for g in learned})))
            current = start.merged(learned)
            result.added.extend(learned)
            passed = attempt(current, [], label="with learned hosts only")
        for extra in escalate or []:
            if passed or budget_left():
                break
            current = current.merged([extra])
            result.added.append(extra)
            passed = attempt(current, [], label=f"adding {extra.id}")
        if not passed:
            result.baseline_failed = True
            return result
    removable = [g for g in current.grants if not g.locked]
    groups: dict[str, list[Grant]] = {}
    for g in removable:
        key = g.id.split(":", 1)[0] if ":" in g.id else g.id
        groups.setdefault(key, []).append(g)

    queue: list[list[Grant]] = []
    for members in groups.values():
        queue.append(members)
    removed: list[Grant] = []
    while queue:
        why = budget_left()
        if why:
            result.stopped_early = why
            break
        batch = queue.pop(0)
        candidate = current
        for g in batch:
            candidate = candidate.without(g.id)
        if attempt(candidate, [g.id for g in batch]):
            current = candidate
            removed.extend(batch)
        elif len(batch) > 1:
            # The group as a whole is needed - try its members individually.
            queue[0:0] = [[g] for g in batch]

    passes = 0
    for _ in range(confirm):
        if budget_left() and passes > 0:
            break
        if attempt(current, [g.id for g in removed] or ["(confirmation)"]):
            passes += 1
        else:
            break
    result.confirm_runs = confirm
    result.confirmed = passes
    if confirm and passes < confirm:
        result.stopped_early = result.stopped_early or "confirmation run failed - the task may be flaky"

    kept = [g for g in current.grants]
    final = Profile(name=start.name, agent=start.agent, grants=kept)
    final.verified = {
        "date": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "aegis_version": __version__,
        "backend": backend.name,
        "task": {"name": task.name, "fingerprint": task.fingerprint(), "prompt": task.prompt,
                 "verify": task.verify},
        "runs": [t.to_dict() for t in trials],
        "removed": [g.id for g in removed],
        "confirmed": f"{passes}/{confirm}",
        "note": "Evidence for the task above only; one passing run does not prove the profile fits every task.",
    }
    result.final = final
    result.removed = removed
    result.kept = kept
    return result
