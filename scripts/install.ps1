# Install Hydra (Windows). Usage: irm <raw-url>/scripts/install.ps1 | iex
$ErrorActionPreference = "Stop"
$repo = if ($env:HYDRA_REPO) { $env:HYDRA_REPO } else { "https://github.com/IwanskyDD/aegis-mcp-jail" }
$ref = if ($env:HYDRA_REF) { $env:HYDRA_REF } else { "main" }
$py = Get-Command py -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command python -ErrorAction SilentlyContinue }
if (-not $py) { throw "Hydra needs Python 3.10+ (https://www.python.org/downloads/windows/)" }
& $py.Source -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if ($LASTEXITCODE -ne 0) { throw "Hydra needs Python 3.10+" }
& $py.Source -m pip install --user --upgrade "git+$repo@$ref"
& $py.Source -m hydra_guard doctor
