"""Permission minimisation with proof that the task still works.

Starting from a profile where the task passes, Hydra removes grants one
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

from hydra_guard import __version__
from hydra_guard.agents import Task
from hydra_guard.policy import Grant, Profile
from hydra_guard.runner import RunReport, cleanup_run, run_task
from hydra_guard.sandbox import Backend, get_backend


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
    confirmed: int = 0
    confirm_runs: int = 0
    stopped_early: str = ""
    baseline_failed: bool = False

    @property
    def summary(self) -> str:
        from hydra_guard.report import plain_removed
        if self.baseline_failed:
            return "The task did not pass even with the starting profile; nothing was optimised."
        if not self.removed:
            return "Every removable permission turned out to be needed (or the budget ran out first)."
        return "The task passed its tests without: " + "; ".join(plain_removed(self.removed)) + "."


def _failure_reason(rep: RunReport) -> str:
    for p in rep.phases:
        if not p.ok:
            what = "timed out" if p.timed_out else f"exit {p.exit_code}"
            extra = f"; blocked: {', '.join(rep.blocked_network[:3])}" if rep.blocked_network else ""
            return f"{p.name} {what}{extra}"
    return "ok"


def optimize(project: Path, start: Profile, task: Task, *, max_runs: int = 12, max_minutes: float = 60,
             confirm: int = 1, backend: Backend | None = None,
             log: Callable[[str], None] = print) -> OptimizeResult:
    backend = backend or get_backend()
    deadline = time.monotonic() + max_minutes * 60
    runs = 0
    trials: list[Trial] = []

    def attempt(profile: Profile, removed: list[str]) -> bool:
        nonlocal runs
        runs += 1
        rep = run_task(project, profile, task, backend=backend, quiet=True)
        ok = rep.ok
        trials.append(Trial(removed, rep.run_id, ok, _failure_reason(rep)))
        cleanup_run(Path(rep.run_dir))
        label = "baseline" if not removed else "without " + ", ".join(removed)
        log(f"[hydra] run {runs}/{max_runs}: {label}: {'PASS' if ok else 'FAIL - ' + _failure_reason(rep)}")
        return ok

    def budget_left() -> str:
        if runs >= max_runs:
            return f"run limit ({max_runs}) reached"
        if time.monotonic() > deadline:
            return f"time budget ({max_minutes:g} min) reached"
        return ""

    result = OptimizeResult(start=start, final=start, removed=[], kept=[], trials=trials)
    if not attempt(start, []):
        result.baseline_failed = True
        return result

    current = start
    removable = [g for g in start.grants if not g.locked]
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
        "hydra_version": __version__,
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
