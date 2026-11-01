---
description: Explain what an AI agent could access in this project, and how Aegis would limit it
---

Without reading any credential files, explain to the user:
1. What a coding agent running unsandboxed in this project could reach (home directory, credential stores such as ~/.ssh and ~/.aws, other projects, network, environment variables with tokens).
2. Use the `aegis_profiles` MCP tool to show which Aegis profiles exist for this project and what each allows.
3. Recommend next steps: `aegis_probe`, running tests via `aegis_run`, and `aegis optimize` in a terminal to find a minimal verified profile for a representative task.
