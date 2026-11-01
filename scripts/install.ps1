# Install Aegis (Windows). Usage: irm <raw-url>/scripts/install.ps1 | iex
$ErrorActionPreference = "Stop"
$repo = if ($env:AEGIS_REPO) { $env:AEGIS_REPO } else { "https://github.com/davidi0x/aegis-jail-mcp" }
$ref = if ($env:AEGIS_REF) { $env:AEGIS_REF } else { "main" }
$py = Get-Command py -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command python -ErrorAction SilentlyContinue }
if (-not $py) { throw "Aegis needs Python 3.10+ (https://www.python.org/downloads/windows/)" }
& $py.Source -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if ($LASTEXITCODE -ne 0) { throw "Aegis needs Python 3.10+" }
& $py.Source -m pip install --user --upgrade "git+$repo@$ref"
& $py.Source -m aegis_jail doctor
