# Security policy

Aegis is a security boundary, so sandbox escapes are the most important bugs we can get.

**Please report escapes privately** through GitHub's "Report a vulnerability" button (Security tab → Advisories), not in public issues. Include:

- OS and version, Aegis version (`aegis --version`), backend (`aegis doctor`);
- the profile used and a minimal command that reaches something it should not (a file, a host, an env var, a write outside the working copy).

`aegis probe --json` output is very helpful.

## Scope

In scope: anything run by `aegis run`, `aegis wrap`, `aegis mcp-jail`, `aegis optimize` or the `aegis_run` MCP tool reaching what its profile denies, including through child processes.

Out of scope (documented limits): the Claude Code credential hook (best-effort string matching for unsandboxed sessions); programs that ignore `HTTPS_PROXY` being *blocked*; IPC other than files and network on macOS.
