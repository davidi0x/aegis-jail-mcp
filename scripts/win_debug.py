"""Temporary CI diagnostics: which verify command forms work in the Windows sandbox."""
import shutil, sys, tempfile
from pathlib import Path
from aegis_jail.agents import Task
from aegis_jail.policy import Profile
from aegis_jail.runner import run_task

src = Path(__file__).resolve().parent.parent / "aegis_jail" / "demo"
for verify in ["{python} -m unittest discover -s tests -v", f'"{sys.executable}" -m unittest discover -s tests -v',
               "echo hello", "dir", "{python} -c \"print(1)\""]:
    d = Path(tempfile.mkdtemp()) / "p"
    shutil.copytree(src, d)
    t = Task(name="x", agent="command", command=["{python}", "-c", "print('agent ok')"], verify=verify, timeout=60)
    rep = run_task(d, Profile("d", "command"), t, quiet=True)
    v = rep.phases[-1]
    print("VERIFY", repr(verify), "->", v.exit_code, v.command)
    print("   ", Path(v.log).read_text(errors="replace")[-300:].replace("\n", " | "))
