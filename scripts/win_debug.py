"""CI diagnostics for the Windows AppContainer backend (temporary)."""
import ctypes, os, tempfile
from pathlib import Path
from hydra_guard.sandbox import windows as w

d = Path(tempfile.mkdtemp())
log = d / "log.txt"
base = {k: os.environ[k] for k in ("SYSTEMROOT", "PATH", "TEMP", "TMP") if k in os.environ}
argv = [os.path.join(os.environ["SYSTEMROOT"], "System32", "cmd.exe"), "/c", "echo hello"]
b = w.AppContainerBackend()


def attempt(label, env):
    sid = w.PSID()
    name = "hydra.dbg." + str(abs(hash(label)))[:8]
    hr = w.userenv.CreateAppContainerProfile(name, name, "d", None, 0, ctypes.byref(sid))
    if hr == w.HRESULT_ALREADY_EXISTS:
        w.userenv.DeriveAppContainerSidFromAppContainerName(name, ctypes.byref(sid))
    try:
        b._spawn(sid, (w.SID_AND_ATTRIBUTES * 1)(), 0, argv, env, d, log, 30)
        return True
    except OSError:
        return False
    finally:
        w.userenv.DeleteAppContainerProfile(name)


print("minimal:", attempt("minimal", base))
for k in sorted(os.environ):
    if k not in base and attempt(k, {**base, k: os.environ[k]}):
        print("minimal +", k, "works")
