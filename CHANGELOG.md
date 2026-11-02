# Changelog

## 0.5.0

**Autopilot and dashboard**
- `aegis watch`: background watcher for MCP configs (Claude Code, Claude Desktop, Cursor, Windsurf, VS Code, Codex), audit logs of jailed servers, run reports and new projects. Events go to `~/.aegis/events.jsonl`.
- `aegis watch install` starts it at login (systemd, launchd, scheduled task). `auto_jail` wraps unjailed servers in `aegis mcp-jail` with a backup and an undo, including Codex's `config.toml`.
- Agents handle detections: MCP tools `aegis_events`, `aegis_jail_mcp_server`, `aegis_resolve`, `aegis_watch_status`; Claude Code plugin hooks that tell Claude about open events; an optional responder (Claude Code or Codex) limited to the Aegis tools. A responder can contain a problem but never approve one.
- `aegis dashboard`: local web UI (127.0.0.1, token, Host and Origin checks, CSP) with Overview, Activity, Agents, MCP servers, Boundaries, Autopilot and Setup. A task bar starts sandboxed runs.
- Plugin commands `/aegis:events` and `/aegis:watch`.

**Fixes**
- Claude Code now runs unattended inside the sandbox when Aegis runs as root (`IS_SANDBOX=1`).
- Dashboard runs, the responder and rewritten MCP configs start the same copy of Aegis that created them.
- A dashboard run that never started (for example an unapproved task) is reported as an event.
- A busy dashboard port moves on to the next free one.
- `aegis probe` explains the bubblewrap remount error instead of printing a traceback.
- Removed unused imports; CI now runs pyflakes.

## 0.4.0
Windows per-file masking, MCP jail hardening, Claude Code plugin guard, AGPL-3.0 licence and trademark policy.
