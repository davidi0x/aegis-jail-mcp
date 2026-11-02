# Contributing to Aegis Jail MCP

Thanks for helping make AI agents safer to use!

## Ground rules

- **Zero runtime dependencies.** Aegis runs from a plain checkout (`python3 scripts/aegis.py`), and that is what makes the Claude Code plugin install in one step. Use the standard library only.
- **Fail closed.** If a boundary cannot be enforced on a platform, refuse with a clear message rather than silently widening access.
- **Prove it.** Every sandbox change needs a test in `tests/` that runs against the real OS sandbox. CI runs them on Linux, macOS and Windows with `AEGIS_REQUIRE_SANDBOX=1`.

## Good first contributions

- **Agent adapters:** try `--agent codex|gemini|aider` with your real account and report what the agent needed. Better still, open a PR with fixed grants in `aegis_jail/agents.py`.
- **Probe checks:** new escape attempts for `aegis_jail/probe.py`.
- **MCP servers:** tested `aegis mcp-jail` recipes for popular servers (which hosts and env vars they need).

## Pictures in the README

The images in `docs/images/` are generated: terminal screenshots from *real* command output, diagrams from code. After changing what a command prints, re-capture it and run `python3 scripts/make_images.py --demo demo.txt --optimize optimize.txt --scan scan.txt` (see the docstring in that script).

## Running tests

```sh
sudo apt install bubblewrap          # Linux only
AEGIS_REQUIRE_SANDBOX=1 python3 -m unittest discover -s tests -t . -v
```

## Checking the dashboard

`scripts/dev/` has a browser click-through and a readability audit for `aegis dashboard` (see its README). Run them after changing `aegis_jail/web/`.
