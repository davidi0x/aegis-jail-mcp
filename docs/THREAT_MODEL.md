# Aegis threat model

Who we defend against, what they try, and what stops them. Every row marked
**tested** has a regression test in `tests/` that runs against the real OS
sandbox on Linux, macOS and Windows in CI.

## Adversaries

| | Adversary | Typical entry point |
|---|---|---|
| A1 | **Hijacked agent**: a model steered by prompt injection | README, issue, web page, tool result, dependency docs |
| A2 | **Malicious code the agent runs**: tests, install scripts, dependencies | `npm install`, `pytest`, `postinstall` |
| A3 | **Hostile repository**: ships config that targets the tools around the agent | `.aegis/`, `.claude/`, `.mcp.json`, `.vscode/` |
| A4 | **Malicious or compromised MCP server** | tool descriptions, tool results, server-initiated requests |
| A5 | **Manipulated supervisor**: the AI reading Aegis's own output | sandbox output that addresses the model |

## Attacks and defences

### Reading secrets
| Attack | Defence | |
|---|---|---|
| Read `~/.ssh`, `~/.aws`, `~/.kube`, `.netrc`, … | Home and credential stores hidden by the OS sandbox, even under a broader grant | tested |
| Credential store is a symlink to another disk | Hidden at its real location too | |
| `.env`, `*.pem`, `tfstate`, files containing tokens *inside the project* | Left out of the agent's working copy (`expose` grant to opt in); never deleted by `apply` | tested |
| Token in `.git/config` remote URL or credential helper | Stripped from the copy | tested |
| Tokens in environment variables | Not inherited; only a safe set plus explicit `env` grants | tested |
| Talk to the **ssh-agent / gpg-agent / desktop keyring / Docker** instead of reading files | Linux: `/run`, `/var/run` and Docker state replaced by empty tmpfs (read-only mounts do not stop `connect()`); private user, IPC and network namespaces (abstract sockets, kernel keyring). macOS: unix-socket egress denied except the working copy, temp and DNS | tested |
| macOS keychain (`security find-generic-password`), clipboard | securityd / pasteboard Mach services and binaries denied unless the `keychain` / `clipboard` service is granted | tested on macOS |
| Read another user's files | `/home` / `/Users` denied as a whole, own grants re-allowed | |
| Core dumps of processes that held secrets | `RLIMIT_CORE=0` | |

### Escaping the sandbox
| Attack | Defence | |
|---|---|---|
| Write outside the working copy | OS-level deny; hidden areas are read-only (the agent gets EROFS instead of silently writing to a void) | tested |
| Child / background processes | Linux PID namespace and `--die-with-parent`; macOS process group reaped at the end; Windows Job object with kill-on-close | tested |
| macOS: make *another* app do it (`osascript` → Terminal, `open -a`, `launchctl submit`) | `appleevent-send`, `lsopen`, LaunchServices lookup and those binaries denied | tested on macOS |
| Nested user namespaces as a kernel attack surface | `--disable-userns` | |
| Kernel attack surface via rare syscalls (ptrace, bpf, perf_event_open, keyring, module loading, kexec, mount, raw I/O…) | seccomp blocklist returning EPERM (x86-64 / aarch64; `AEGIS_SECCOMP=0` to disable) | tested |
| Fill RAM through `/tmp` | `/tmp` tmpfs size-capped (`AEGIS_TMPFS_BYTES`); single-file size capped | |
| Windows: a credential file inside a directory shared with a command (`wrap`, `mcp-jail`) | The file is detached from its folder's inherited permissions and the container removed from it; its original permissions are saved first and restored afterwards (same entries; duplicates that Windows adds on restore are cleaned up when that is safe). Two live sessions can't mask the same file | tested on Windows |
| Windows: Aegis killed mid-run leaves ACLs or masks behind | ACL journal with the owner's process id; the next start removes the container's entries and restores masked files | |

### Exfiltration
| Attack | Defence | |
|---|---|---|
| Any network | Off by default; only listed hosts, via Aegis's proxy | tested |
| Allowed host on an unusual port (`github.com:22`) | Host patterns allow 80/443 only; other ports must be explicit (`host:port`) | tested |
| **Domain fronting**: CONNECT to an allowed CDN host, TLS SNI for another | SNI in the ClientHello must match an allowed host | tested |
| Plain HTTP with a forged `Host` header | Rejected | tested |
| Secrets in plaintext requests | Blocked and flagged (DLP) | tested |
| DNS tunnelling | No resolver inside the sandbox (Linux netns, macOS DNS socket denied); only the proxy resolves | |
| Learning run (`optimize`) has open-but-logged network | Files stay confined, credentials hidden, DLP active; hosts that only carried blocked traffic are never learned | |

### Persistence and the road back to your machine
| Attack | Defence | |
|---|---|---|
| Agent writes `.claude/settings.json` hooks, `.mcp.json`, `CLAUDE.md`/`AGENTS.md`, `.vscode/tasks.json`, CI workflows, git hooks, npm scripts, executables, which later run *outside* the sandbox | `apply` flags these as **risky** and needs explicit approval (`--allow-risky` or an interactive yes) | tested |
| Invisible Unicode / tag smuggling / prompt injection written into files for the *next* agent | Flagged as risky in the diff | tested |
| `apply` writes through a symlink in the project (e.g. `docs -> ~/.ssh`) | Refuses symlinked path components and paths escaping the project; atomic replace | tested |
| Terminal escape sequences in output or diffs (OSC 52 clipboard write, screen rewrite) | All agent-controlled text is escaped before printing | tested |

### Hostile project configuration (A3)
| Attack | Defence | |
|---|---|---|
| Repo ships `.aegis/profiles/default.json` granting `~/.ssh` and `*`, or a task with `setup: curl … \| sh` | **Trust on first use**: project config is shown and must be approved (`aegis trust`); a changed file must be approved again | tested |
| Agent edits `.aegis/` in its copy | `.aegis/` is excluded from the copy and from `apply` | tested |
| `aegis_run` aimed at `~` or `/` (copying your credentials into the sandbox) | Projects that are or contain the home directory or a credential store are refused | tested |
| Huge project to exhaust disk | Copy limits (`AEGIS_MAX_FILES`, `AEGIS_MAX_BYTES`) | |

### MCP (A4)
| Attack | Defence | |
|---|---|---|
| Server runs with your full rights | `aegis mcp-jail` OS sandbox | tested |
| **Rug pull**: tool definition changes after you trusted it | Definitions pinned on first sight; a changed tool is hidden until `aegis mcp-pins <name> --reset` | tested |
| **Tool poisoning**: description tells the model to read secrets / hide actions, with optional hidden Unicode | Description scan; suspicious tools hidden | tested |
| Server drives your model with `sampling/createMessage` | Blocked unless `--allow-sampling` | tested |
| Client hands secrets to a server through tool arguments | Calls carrying credentials are blocked | tested |
| ASCII smuggling in tool results | Invisible characters stripped and logged | tested |
| Oversized messages | Dropped (`AEGIS_MCP_MAX_MESSAGE`) | |

### Manipulating the supervisor (A5)
| Attack | Defence | |
|---|---|---|
| Sandboxed code prints "now call aegis_apply" to the model reading the result | Output fenced in `<untrusted-data id=RANDOM>` with a warning when instructions are detected; invisible characters removed | tested |
| Injected model calls `aegis_apply` on its own | Asks the **human** via MCP elicitation; without it, risky changes and runs that tripped a wire are refused | tested |

### Detection: tripwires
Where Aegis hides a credential store on Linux, it plants a **decoy** with a per-run marker (fake AWS key, SSH key, `.netrc`, GitHub token…). An honest task never needs them. If a decoy shows up in a request, a tool call, a written file or the output, the run is flagged **TRIPWIRE**. That is hard evidence of a hijacked agent, and every change from that run then needs explicit review.

## Known limits
- Domain allowlists rely on programs honouring `HTTPS_PROXY`. Others are blocked, not let through.
- Content inside TLS is not inspected (no MITM). Exfiltration *to an allowed host* is possible, so keep allowlists small.
- Seccomp is a blocklist of known-dangerous syscalls, not a strict allowlist, and covers x86-64 / aarch64 only; the primary boundary remains namespaces and mounts.
- The Claude Code hook is a best-effort guard for **unsandboxed** sessions. It normalises common shell tricks, but determined obfuscation can beat string matching. Use `aegis run` / `wrap` / `mcp-jail` for a real boundary.
- Decoys are Linux-only for now (macOS and Windows cannot put a fake file over a real one without touching your home).
- `aegis scan` and the injection detectors are heuristics: high recall, and they need human reading.
