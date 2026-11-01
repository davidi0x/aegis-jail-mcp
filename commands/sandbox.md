---
description: Run a command in the Aegis sandbox (no home dir, no credentials, no network) and review its changes
argument-hint: <shell command>
---

Run this command with the `aegis_run` MCP tool (project = the current working directory): `$ARGUMENTS`

Then:
1. Summarise the exit code and the important part of the output.
2. If files changed, show the diff with `aegis_diff` and ask the user whether to apply it. Only call `aegis_apply` after they say yes; otherwise call `aegis_discard`.
3. If network hosts were blocked and the command needs them, explain which hosts and offer to rerun with `allow_hosts` set to exactly those hosts.
