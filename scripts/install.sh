#!/bin/sh
# Install Hydra (macOS / Linux). Usage: curl -fsSL <raw-url>/scripts/install.sh | sh
set -e
REPO="${HYDRA_REPO:-https://github.com/IwanskyDD/Hydra}"
REF="${HYDRA_REF:-main}"
PY="$(command -v python3 || true)"
[ -n "$PY" ] || { echo "Hydra needs Python 3.10+ (python3 not found)"; exit 1; }
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || { echo "Hydra needs Python 3.10+"; exit 1; }
if [ "$(uname)" = "Linux" ] && ! command -v bwrap >/dev/null 2>&1; then
  echo "Note: Linux sandboxing needs bubblewrap - install it with your package manager (e.g. sudo apt install bubblewrap)."
fi
if command -v pipx >/dev/null 2>&1; then
  pipx install --force "git+${REPO}@${REF}"
else
  "$PY" -m pip install --user --upgrade "git+${REPO}@${REF}"
  echo "Installed with pip --user; make sure ~/.local/bin (Linux) or ~/Library/Python/*/bin (macOS) is on PATH."
fi
hydra doctor || true
