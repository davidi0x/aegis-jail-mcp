"""CI diagnostics for the Windows AppContainer backend (temporary)."""
import ctypes, os, sys, tempfile
from pathlib import Path
from hydra_guard.sandbox import windows as w

d = Path(tempfile.mkdtemp())
log = d / "log.txt"
env = {k: os.environ[k] for k in ("SYSTEMROOT", "PATH", "TEMP", "TMP") if k in os.environ}
argv = [os.path.join(os.environ["SYSTEMROOT"], "System32", "cmd.exe"), "/c", "echo hello"]
b = w.AppContainerBackend()
orig = w.kernel32.UpdateProcThreadAttribute
for label, use_env in (("with env", env), ("no env (inherit)", None)):
    sid = w.PSID()
    name = "hydra.debug." + label.replace(" ", "")[:10]
    hr = w.userenv.CreateAppContainerProfile(name, name, "d", None, 0, ctypes.byref(sid))
    if hr == w.HRESULT_ALREADY_EXISTS:
        w.userenv.DeriveAppContainerSidFromAppContainerName(name, ctypes.byref(sid))
    try:
        r = b._spawn(sid, (w.SID_AND_ATTRIBUTES * 1)(), 0, argv, use_env if use_env is not None else os.environ.copy(), d, log, 30)
        print(label, "OK", r.exit_code, log.read_text(errors="replace"))
    except OSError as e:
        print(label, "FAILED", e)
    finally:
        w.userenv.DeleteAppContainerProfile(name)
