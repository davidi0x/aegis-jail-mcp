#!/usr/bin/env python3
"""Record a REAL aegis session in a pty -> asciicast-style JSON (events: [t, text]).

Nothing here is faked: each command is typed into a real bash and its real output is captured.
Usage: record.py OUT.json   (expects `aegis` on PATH and the project in ~/shop)
"""
import json, os, re, pty, select, shutil, subprocess, sys, time, random

ROWS, COLS = 40, 104
SCEN = None
HOME = os.path.expanduser("~")
SHOP = os.path.join(HOME, "shop")
SCRIPT = [  # (command, pause after, wait for prompt seconds max)
    ("cat app.py", 1.3),
    ("python3 test_app.py", 2.2),
    ('aegis run --agent command --verify "python3 test_app.py" --agent-cmd my-agent', 6.0),
    ("clear", 0.2),
    ("aegis diff", 3.0),
    ("aegis apply", 2.5),
    ("python3 test_app.py", 2.0),
    ("grep -c evil ~/.bashrc", 3.0),
]


def fresh():
    if SCEN:
        subprocess.run(SCEN["setup"], shell=True, check=True)
        return
    shutil.rmtree(SHOP, ignore_errors=True)
    os.makedirs(SHOP)
    open(f"{SHOP}/app.py", "w").write("def total(prices):\n    return sum(prices) + 1\n")
    open(f"{SHOP}/test_app.py", "w").write('from app import total\nassert total([1, 2, 3]) == 6, "total is wrong"\nprint("ok")\n')
    for c in (["git", "init", "-q"], ["git", "add", "-A"], ["git", "-c", "user.email=a@b", "-c", "user.name=x", "commit", "-qm", "init"]):
        subprocess.run(c, cwd=SHOP, check=True)
    subprocess.run(["sed", "-i", "/evil/d", f"{HOME}/.bashrc"], check=False)
    shutil.rmtree(f"{HOME}/.aegis/runs", ignore_errors=True)


def main(out):
    global SHOP, ROWS, COLS, SCRIPT
    if SCEN:
        SHOP, ROWS, COLS = os.path.expanduser(SCEN["cwd"]), SCEN.get("rows", ROWS), SCEN.get("cols", COLS)
        SCRIPT = [tuple(x) for x in SCEN["steps"]]
    fresh()
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(SHOP)
        os.environ.update(TERM="xterm-256color", PS1=(SCEN or {}).get("ps1", "\\[\\e[1;32m\\]~/shop\\[\\e[0m\\] \\$ "), COLUMNS=str(COLS), LINES=str(ROWS))
        os.execvp("bash", ["bash", "--norc", "--noprofile"])
    import fcntl, struct, termios
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))
    ev, t0 = [], time.time()

    def pump(dur):
        end = time.time() + dur
        while time.time() < end:
            r, _, _ = select.select([fd], [], [], 0.05)
            if r:
                try:
                    d = os.read(fd, 65536)
                except OSError:
                    return
                ev.append([round(time.time() - t0, 3), d.decode("utf-8", "replace")])

    def wait_prompt(maxs):
        end = time.time() + maxs
        while time.time() < end:
            pump(0.2)
            tail = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", "".join(e[1] for e in ev[-6:])).rstrip()
            if tail.endswith(("$", "#")):
                return

    pump(0.8)
    for cmd, pause in SCRIPT:
        if cmd.startswith("__UP__"):  # recall the previous command from shell history, like a person would
            pump(1.2)
            for _ in range(int(cmd[6:] or 1)):
                os.write(fd, b"\x1b[A"); pump(0.5)
        else:
            for ch in cmd:
                os.write(fd, ch.encode())
                pump(random.uniform(0.025, 0.06))
        pump(0.5 if cmd.startswith("__UP__") else 0.35)
        os.write(fd, b"\r")
        if cmd == "aegis apply":  # real confirmation prompt: let the viewer read the warning, then answer
            pump(4.5)
            for ch in "y":
                os.write(fd, ch.encode()); pump(0.3)
            os.write(fd, b"\r")
        sys.stderr.write(f"cmd: {cmd[:30]} t={time.time()-t0:.1f}\n"); wait_prompt(150)
        pump(pause)
    os.write(fd, b"exit\r")
    pump(0.3)
    json.dump({"rows": ROWS, "cols": COLS, "events": ev}, open(out, "w"))
    print("recorded", len(ev), "chunks,", round(ev[-1][0], 1), "s")


if len(sys.argv) > 2:
    SCEN = json.load(open(sys.argv[2]))
main(sys.argv[1])
