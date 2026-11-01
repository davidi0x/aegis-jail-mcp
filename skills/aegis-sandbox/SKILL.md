---
name: aegis-sandbox
description: Use when running untrusted or risky shell commands (scripts from the internet, install scripts, unfamiliar repos, tests of code you did not write), or when the user asks to keep secrets, credentials or the network out of reach. Runs the command through the Aegis sandbox MCP tools.
---

# Running commands safely with Aegis

Aegis runs a command on a copy of the project inside an OS sandbox (bubblewrap on Linux, Seatbelt on macOS, AppContainer on Windows):
the home directory and credential stores are hidden, writes outside the copy fail, and there is no network unless allowed.

1. Prefer `aegis_run` over running the command directly when the command or the code it executes is not trusted.
2. Start with no network. If output shows blocked hosts that the command legitimately needs (for example a package registry), rerun with `allow_hosts` listing only those hosts.
3. Changes stay in the working copy. Show `aegis_diff`, and call `aegis_apply` only after the user agrees.
4. Never try to work around a block (e.g. by copying credentials into the project). Explain what was blocked and let the user decide.
