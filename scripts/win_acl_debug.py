"""Temporary CI diagnostics: how do icacls /save, /inheritance:d, /remove and /restore behave here?"""
import os, subprocess, sys, tempfile
from pathlib import Path

def run(*a):
    r = subprocess.run(["icacls", *a], capture_output=True, text=True)
    return (r.stdout + r.stderr).strip()

def show(title, p):
    print(f"\n===== {title}\n" + run(str(p)).replace(str(p), "<path>"), flush=True)

tmp = Path(tempfile.mkdtemp()); proj = tmp / "proj"; proj.mkdir()
f = proj / ".env"; f.write_text("x")
sid = "*S-1-5-32-545"  # BUILTIN\Users, stand-in for the container SID
show("tmp dir", tmp); show("proj dir", proj); show("A0 original .env", f)
acl = tmp / "saved.acl"
print("\nsave:", run(str(f), "/save", str(acl), "/Q"))
raw = acl.read_bytes()
print("saved file bytes:", len(raw), "->", raw.decode("utf-16", "replace") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("latin-1", "replace"))
print("grant:", run(str(proj), "/grant", f"{sid}:(OI)(CI)(M)", "/Q"))
show("A1 after grant on dir (inherits into file)", f)
print("inheritance:d ->", run(str(f), "/inheritance:d", "/Q")); print("remove ->", run(str(f), "/remove", sid, "/Q"))
show("A2 masked", f)
print("dir remove ->", run(str(proj), "/remove", sid, "/Q"))
show("A3 after dir grant removed", f)
print("restore ->", run(str(proj), "/restore", str(acl), "/Q"))
show("A4 after /restore", f)
print("reset ->", run(str(f), "/reset", "/Q"))
show("A5 after /reset", f)
